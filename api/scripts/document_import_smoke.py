#!/usr/bin/env python3
"""Operator smoke for the document import: installed S2-1 CLI -> built Spring jar -> real PostgreSQL.

Everything is synthetic and local. The script
  1. generates an S2-1 ledger with the INSTALLED `zoop-ai-ingest run` (authored HTML, no network, no model, no provider),
  2. launches the BUILT boot jar as a non-web operator process (`--spring.main.web-application-type=none`) once per step,
     against a dedicated loopback PostgreSQL given by DB_URL / DB_USERNAME / DB_PASSWORD,
  3. reads the persisted rows back with psql (`docker exec` into the database container, or a host psql) and compares the
     exact IDs, hashes, timestamps and bytes with a fresh `zoop-ai-ingest export` of the same observation.

Run it with any Python >= 3.10 (stdlib only), e.g. the pipeline venv's, against an EMPTY dedicated database:

  DB_URL=jdbc:postgresql://127.0.0.1:<port>/<db> DB_USERNAME=<user> DB_PASSWORD=<dummy> \
    ai/pipeline/.venv/bin/python api/scripts/document_import_smoke.py \
      --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --ingest-cli "$PWD/ai/pipeline/.venv/bin/zoop-ai-ingest" \
      --psql-container <container> --db-user <user> --db-name <db>

The artifact root, the ledger, the requests and the results live in a fresh temporary directory that is removed at exit. The
database is NOT cleaned: use a throwaway one. On success the last stdout line is
{"status": "passed", "steps": N, "providerCalls": 0, "modelCalls": 0, ...}; any failed expectation exits non-zero.
"""
from __future__ import annotations

import base64
import argparse
import atexit
import datetime as dt
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

SCHEMA = "zoop-ingestion-s2-1"
IMPORT_SCHEMA = "zoop-document-import-1"
SOURCE = "synthetic-source"
UNICODE_SOURCE = "출처-\U0001F600-source"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
KEEP = object()  # request item without `currentVersion`: insertion only

BODY1 = '<html><body><article><p>삼성전자 &amp; "인용" \\ 경로 \U0001F600 첫째</p><p>둘째 문단</p></article></body></html>'
BODY2 = BODY1.replace("첫째", "변경")
BODY3 = BODY1.replace("둘째", "셋째")
BODY4 = BODY1.replace("둘째", "넷째")

# Operator-declared publishers, written out by hand (never read back from the code under test). Every other observation of
# this scenario declares none, so its export has no `publisher` key and its version row must keep a NULL publisher.
DECLARED = {"u1": "합성일보 \U0001F600 Daily", "a8": "Synthetic Daily"}

STEPS: list[str] = []
DOCUMENT_MIGRATION = "20261014120000"
OUTPUT: list[str] = []  # every jar run's combined output, checked for leaks at the end


def check(condition, message: str):
    if not condition:
        raise AssertionError(message)


def step(label: str) -> str:
    STEPS.append(label)
    print(f"[step {len(STEPS)}] {label}", file=sys.stderr, flush=True)
    return label


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def python_source_hash(text: str) -> str:
    # The S2-1 ledger's `sourceHash`: sha256 over json.dumps(text, ensure_ascii=False).
    return sha(json.dumps(text, ensure_ascii=False).encode("utf-8"))


_STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d)$")


def iso_us(value: str) -> str:
    """Any ISO-8601 instant (Z or an offset, 0 to 9 fraction digits) as UTC with exactly six fraction digits."""
    match = _STAMP.match(value)
    check(match, "not an ISO-8601 instant: " + value)
    base, fraction, zone = match.groups()
    parsed = dt.datetime.fromisoformat(f"{base}.{(fraction or '').ljust(6, '0')[:6]}{'+00:00' if zone == 'Z' else zone}")
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# --------------------------------------------------------------------------------------------------------------------
# database access (psql only; the jar is the only writer under test)
# --------------------------------------------------------------------------------------------------------------------
class Database:
    def __init__(self, url: str, user: str, password: str, name: str | None, container: str | None, psql: str | None):
        parsed = urlparse(url[len("jdbc:"):] if url.startswith("jdbc:") else url)
        check(parsed.scheme == "postgresql", "DB_URL must be a jdbc:postgresql:// URL")
        self.host = parsed.hostname or ""
        check(self.host in LOOPBACK, "refusing a non-loopback database host")
        self.port = str(parsed.port or 5432)
        self.name = name or parsed.path.lstrip("/")
        self.user = user
        self.password = password
        self.container = container
        self.psql = psql

    def command(self, sql: str) -> tuple[list[str], dict[str, str]]:
        base = ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-U", self.user, "-d", self.name, "-c", sql]
        if self.container:
            return ["docker", "exec", "-i", "-e", "PGCLIENTENCODING=UTF8", self.container, *base], dict(os.environ)
        check(self.psql, "no psql: pass --psql-container or put psql on PATH")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PGPASSWORD": self.password, "PGCLIENTENCODING": "UTF8"}
        return [self.psql, *base[1:3], "-h", self.host, "-p", self.port, *base[3:]], env

    def run(self, sql: str) -> str:
        argv, env = self.command(sql)
        done = subprocess.run(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        check(done.returncode == 0, "psql failed: " + done.stderr.decode("utf-8", "replace").replace(self.password, "***")[-400:])
        return done.stdout.decode("utf-8").strip()

    def rows(self, sql: str) -> list[dict]:
        return json.loads(self.run(f"SELECT coalesce(json_agg(t), '[]'::json) FROM ({sql}) t"))

    def scalar(self, sql: str):
        return json.loads(self.run(f"SELECT to_json(({sql}))"))

    def tables_exist(self) -> bool:
        return self.scalar("SELECT to_regclass('public.articles') IS NOT NULL")

    def snapshot(self) -> dict:
        return json.loads(self.run("""
            SELECT json_build_object(
              'articles', (SELECT md5(coalesce(string_agg(a::text, '|' ORDER BY a.id), '')) FROM articles a),
              'versions', (SELECT md5(coalesce(string_agg(v::text, '|' ORDER BY v.article_id, v.version), '')) FROM article_versions v),
              'artifacts', (SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x.id), '')) FROM artifacts x))"""))

    def articles(self) -> list[dict]:
        return self.rows("SELECT id, kind, provider, provider_key, lineage_key, current_version, access_status "
                         "FROM articles ORDER BY id")

    def versions(self) -> list[dict]:
        stamp = "'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'"
        return self.rows(f"""SELECT article_id, version, title, publisher, url,
            to_char(published_at AT TIME ZONE 'UTC', {stamp}) AS published_at, published_date::text AS published_date,
            publication_precision, raw_artifact_id, text_artifact_id,
            to_char(collected_at AT TIME ZONE 'UTC', {stamp}) AS collected_at
            FROM article_versions ORDER BY article_id, version""")

    def artifacts(self) -> list[dict]:
        return self.rows("SELECT id, kind, storage_uri, sha256, bytes, media_type FROM artifacts ORDER BY id")


# --------------------------------------------------------------------------------------------------------------------
# the world: ledger fixture generated by the installed CLI, artifact root, request/result files
# --------------------------------------------------------------------------------------------------------------------
class World:
    def __init__(self, ingest_cli: Path):
        self.ingest_cli = ingest_cli
        self.root = Path(tempfile.mkdtemp(prefix="zoop-docimport-")).resolve()  # real path: no /var symlink on macOS
        atexit.register(shutil.rmtree, self.root, True)
        self.inputs = self.root / "inputs"
        self.state = self.root / "ingestion-state"
        self.artifacts = self.root / "artifacts"
        self.requests = self.root / "requests"
        self.reserved_app = self.root / "reserved-app"
        self.reserved_worker = self.root / "reserved-worker"
        for folder in (self.inputs, self.artifacts, self.requests, self.reserved_app, self.reserved_worker):
            folder.mkdir(mode=0o700)
        self.registry_path = self.root / "sources.json"
        self.registry = {"schemaVersion": SCHEMA, "revision": "operator-1",
                         "sources": [self.source_entry(SOURCE, "operator-grant", "rights-1"),
                                     self.source_entry(UNICODE_SOURCE, "operator-grant-2", "rights-2")]}
        self.save_registry()

    def source_entry(self, source_id: str, grant_id: str, revision: str) -> dict:
        return {"sourceId": source_id, "adapter": "authored-files", "inputRoot": str(self.inputs), "allowedHosts": ["example.invalid"],
                "scopes": [{"scopeId": "body", "selection": "authored source slice", "initialCursor": None, "articleXPath": None,
                            "timestampLimitations": ["authored fixtures; no real provider late-registration guarantee"]}],
                "grant": {"grantId": grant_id, "revision": revision, "sourceId": source_id, "enabled": True, "rights": "known",
                          "allowedOperations": ["read", "store", "quote-display"], "recipients": [], "purposes": [],
                          "evidence": ["operator-owned authored synthetic fixtures"], "expiresAt": None}}

    def save_registry(self):
        temporary = self.root / "next-sources.json"
        temporary.write_bytes(json_bytes(self.registry))
        temporary.replace(self.registry_path)  # atomic: a reader sees the old or the new registry, never half

    def grant(self, source_id: str) -> dict:
        return next(s for s in self.registry["sources"] if s["sourceId"] == source_id)["grant"]

    def ownership_env(self) -> dict[str, str]:
        return {"ZOOP_STATE_DIR": str(self.reserved_app), "ZOOP_AI_WORKER_STATE_DIR": str(self.reserved_worker)}

    def cli(self, command: str, payload: dict, *, sources: bool = True, manifest: Path | None = None, expect: int = 0) -> dict:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", **self.ownership_env()}
        argv = [str(self.ingest_cli), command, "--state-dir", str(self.state)]
        if sources:
            argv += ["--sources", str(self.registry_path)]
        if manifest:
            argv += ["--fixture-manifest", str(manifest)]
        done = subprocess.run(argv, input=json_bytes(payload), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=120)
        check(done.returncode == expect, f"zoop-ai-ingest {command} exited {done.returncode}: {done.stdout.decode()[:300]}")
        return json.loads(done.stdout)

    def file_ref(self, name: str, raw: bytes) -> dict:
        (self.inputs / name).write_bytes(raw)
        return {"file": name, "sha256": sha(raw)}

    def round(self, name: str, source_id: str, round_id: str, revision: int, items: list[dict], body: str) -> list[dict]:
        documents = {"html": self.file_ref(f"{name}-html.bin", body.encode("utf-8"))}
        response = self.file_ref(f"{name}-page-0.json", json_bytes({"items": items, "more": False, "nextCursor": None}))
        page = {"pageId": "page-0", "cursor": None, "response": response, "status": "ok", "nextCursor": None, "terminal": True,
                "coverageThrough": None}
        manifest = self.root / f"{name}-manifest.json"
        manifest.write_bytes(json_bytes({"schemaVersion": SCHEMA, "sourceId": source_id, "scopeId": "body", "pages": [page],
                                         "documents": documents}))
        request = {"schemaVersion": SCHEMA, "roundId": round_id, "sourceId": source_id, "scopeId": "body", "window": None,
                   "checkpointRevision": revision, "fixtureManifestHash": sha(manifest.read_bytes()), "cleanerVersion": "exact-copy-1"}
        result = self.cli("run", request, manifest=manifest)
        check(result["state"] == "complete", f"ledger round {round_id} is {result['state']}")
        return [{"roundId": round_id, "sourceId": source_id, **{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
                for ref in result["documentRefs"]]

    def export(self, ref: dict) -> dict:
        return self.cli("export", {"schemaVersion": SCHEMA, **ref})

    def ledger_fingerprint(self) -> dict:
        fingerprint = {}
        for path in sorted(self.state.rglob("*")):
            if path.is_file():
                info = path.stat()
                fingerprint[str(path.relative_to(self.state))] = (info.st_size, info.st_mtime_ns, sha(path.read_bytes()))
        return fingerprint

    def text_file(self, version: str) -> Path:
        return self.artifacts / "extracted_text" / f"text-{version}.txt"


def item(ref: dict, kind: str = "news", expected=KEEP) -> dict:
    value = {"kind": kind, "observation": {k: ref[k] for k in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
    if expected is not KEEP:
        value["currentVersion"] = {"expected": expected}
    return value


def ledger_item(candidate: str, supplier: str, url: str, published: str | None, publisher: str | None = None) -> dict:
    value = {"candidateId": candidate, "supplierDocumentId": supplier, "url": url, "bodyRef": "html", "mediaType": "text/html",
             "title": "authored", "publishedAt": published, "modifiedAt": None, "sourceRevision": None}
    return value if publisher is None else {**value, "publisher": publisher}


# --------------------------------------------------------------------------------------------------------------------
# the Spring jar as an operator process
# --------------------------------------------------------------------------------------------------------------------
class Jar:
    def __init__(self, java: str, jar: Path, db: Database, world: World):
        self.java, self.jar, self.db, self.world = java, jar, db, world
        self.counter = 0

    def base_env(self) -> dict[str, str]:
        # The app's CSRF key ring is required at startup (auth stays enabled). A fresh random synthetic key per process run;
        # it is never printed or stored, and nothing in these smokes ever issues a session.
        csrf_key = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        return {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LANG": "C.UTF-8", "DB_URL": os.environ["DB_URL"],
                "DB_USERNAME": self.db.user, "DB_PASSWORD": self.db.password,
                "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "smoke-v1", "ZOOP_AUTH_CSRF_KEYS": "smoke-v1=" + csrf_key}

    def import_env(self, request: Path, result: Path, artifact_root: Path) -> dict[str, str]:
        return {**self.base_env(), "ZOOP_DOCUMENT_IMPORT_ENABLED": "true", "ZOOP_DOCUMENT_IMPORT_REQUEST": str(request),
                "ZOOP_DOCUMENT_IMPORT_RESULT": str(result), "ZOOP_INGESTION_CLI": str(self.world.ingest_cli),
                "ZOOP_INGESTION_STATE_DIR": str(self.world.state), "ZOOP_INGESTION_SOURCES": str(self.world.registry_path),
                "ZOOP_ARTIFACT_ROOT": str(artifact_root), **self.world.ownership_env()}

    def argv(self, *extra: str) -> list[str]:
        return [self.java, "-XX:TieredStopAtLevel=1", "-jar", str(self.jar), *extra]

    def run(self, label: str, request_body, *, artifact_root: Path | None = None) -> tuple[int, dict | None, Path]:
        """One operator run. `request_body` is a list of items, or raw bytes for a deliberately malformed request."""
        self.counter += 1
        stem = f"{self.counter:02d}-{label}"
        request = self.world.requests / f"{stem}-request.json"
        result = self.world.requests / f"{stem}-result.json"
        if isinstance(request_body, bytes):
            request.write_bytes(request_body)
        else:
            request.write_bytes(json.dumps({"schemaVersion": IMPORT_SCHEMA, "items": request_body}, ensure_ascii=False).encode("utf-8"))
        try:
            done = subprocess.run(self.argv("--spring.main.web-application-type=none"),
                                  env=self.import_env(request, result, artifact_root or self.world.artifacts),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
        except subprocess.TimeoutExpired as expired:
            OUTPUT.append((expired.stdout or b"").decode("utf-8", "replace"))
            raise AssertionError(f"{label}: the import JVM did not exit within 240s (result file exists: {result.exists()})")
        output = done.stdout.decode("utf-8", "replace")
        OUTPUT.append(output)
        parsed = None
        if result.exists():
            check(stat.S_IMODE(result.stat().st_mode) & 0o077 == 0, f"{label}: result file is not owner-only")
            text = result.read_text("utf-8")
            check(text, f"{label}: the result file was reserved but left empty")
            check(str(self.world.root) not in text, f"{label}: the result file leaks a path")
            parsed = json.loads(text)
        return done.returncode, parsed, result


# --------------------------------------------------------------------------------------------------------------------
# scenario
# --------------------------------------------------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--ingest-cli", required=True, type=Path)
    parser.add_argument("--java", default=None, help="java binary (default: $JAVA_HOME/bin/java, then PATH)")
    parser.add_argument("--psql-container", default=None, help="database container to `docker exec psql` in")
    parser.add_argument("--psql", default=shutil.which("psql"), help="host psql (used without --psql-container)")
    parser.add_argument("--db-user", default=None)
    parser.add_argument("--db-name", default=None)
    parser.add_argument("--upgrade-from", default=None, metavar="VERSION",
                        help="first migrate an empty database up to this existing Flyway version (e.g. 20261014102810), then run the whole scenario")
    args = parser.parse_args()

    for name in ("DB_URL", "DB_USERNAME", "DB_PASSWORD"):
        check(os.environ.get(name), f"{name} must be set (a dedicated loopback database)")
    java = args.java or (str(Path(os.environ["JAVA_HOME"]) / "bin" / "java") if os.environ.get("JAVA_HOME") else shutil.which("java"))
    check(java, "no java: set JAVA_HOME or pass --java")
    check(args.jar.is_file(), "--jar does not exist (build it with ./api/gradlew -p api assemble)")
    ingest_cli = args.ingest_cli.resolve()
    check(ingest_cli.is_file() and os.access(ingest_cli, os.X_OK), "--ingest-cli is not an executable file")
    db = Database(os.environ["DB_URL"], args.db_user or os.environ["DB_USERNAME"], os.environ["DB_PASSWORD"], args.db_name,
                  args.psql_container, args.psql)
    if db.tables_exist():
        check(db.scalar("SELECT (SELECT count(*) FROM articles) + (SELECT count(*) FROM article_versions) + (SELECT count(*) FROM artifacts) = 0"),
              "the database already holds document rows: use a dedicated empty database")

    world = World(ingest_cli)
    jar = Jar(java, args.jar.resolve(), db, world)

    if args.upgrade_from:
        # Upgrade acceptance: the database already carries every migration up to the team's latest (existing
        # `spring.flyway.target`), without the document registry. That bounded run is not a startup proof: Hibernate's
        # schema validation may refuse the missing document tables, so only the recorded Flyway state is judged.
        label = step(f"pre-migrate to {args.upgrade_from}: the registry tables do not exist yet")
        before_upgrade = db.run("SELECT to_json(to_regclass('public.articles') IS NULL AND to_regclass('public.artifacts') IS NULL)")
        check(before_upgrade == "true" and not db.tables_exist(), f"{label}: the document tables already exist")
        subprocess.run(jar.argv("--spring.main.web-application-type=none"), env={**jar.base_env(), "SPRING_FLYWAY_TARGET": args.upgrade_from},
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
        history = db.rows("SELECT version, success FROM flyway_schema_history WHERE version IS NOT NULL ORDER BY installed_rank")
        check(history and history[-1] == {"version": args.upgrade_from, "success": True} and all(row["success"] for row in history)
              and DOCUMENT_MIGRATION not in [row["version"] for row in history] and not db.tables_exist(),
              f"{label}: unexpected Flyway state {history}")

    # ---- the S2-1 ledger, generated by the installed CLI ----------------------------------------------------------
    r1 = world.round("r1", SOURCE, "r1", 0, [ledger_item("c-a", "supplier-a", "https://example.invalid/a", "2026-10-08T09:00:00+09:00"),
                                             ledger_item("c-b", "supplier-b", "https://example.invalid/b", None)], BODY1)
    r2 = world.round("r2", SOURCE, "r2", 1, [ledger_item("c-a", "supplier-a", "https://example.invalid/a", "2026-10-08T09:00:00+09:00")], BODY2)
    r3 = world.round("r3", SOURCE, "r3", 2, [ledger_item("c-a", "supplier-a", "https://example.invalid/a", "2026-10-08T09:00:00+09:00")], BODY1)
    r4 = world.round("r4", SOURCE, "r4", 3, [ledger_item("c-a", "supplier-a", "https://example.invalid/a", "2026-10-08T09:00:00+09:00")], BODY3)
    r5 = world.round("r5", SOURCE, "r5", 4, [ledger_item("c-a", "supplier-a", "https://example.invalid/a", "2026-10-08T09:00:00+09:00")], BODY4)
    r6 = world.round("r6", SOURCE, "r6", 5, [ledger_item("c-c", "supplier-c", "https://example.invalid/c", None)], BODY1)
    r7 = world.round("r7", UNICODE_SOURCE, "라운드-\U0001F600-1", 0, [ledger_item("c-u", "supplier-u", "https://example.invalid/u", None, DECLARED["u1"])], BODY1)
    # The same document and bytes as A1, now with a declared outlet: another raw/document version of document A.
    r8 = world.round("r8", SOURCE, "r8", 6, [ledger_item("c-a", "supplier-a", "https://example.invalid/a", "2026-10-08T09:00:00+09:00", DECLARED["a8"])], BODY1)
    a1, b1 = r1
    (a2,), (a1p,), (a3,), (a4,), (c1,), (u1,), (a8,) = r2, r3, r4, r5, r6, r7, r8

    step("ledger from the installed CLI: identities, replay, same bytes under two suppliers and two sources")
    fingerprint = world.ledger_fingerprint()
    exports = {name: world.export(ref) for name, ref in {"a1": a1, "b1": b1, "a2": a2, "a1p": a1p, "a3": a3, "a4": a4, "c1": c1, "u1": u1, "a8": a8}.items()}
    check(a1["documentId"] == a2["documentId"] == a1p["documentId"] == a3["documentId"] == a4["documentId"], "document A changed identity across rounds")
    check(a1["documentVersion"] == a1p["documentVersion"], "a replay of the same content must reuse the version")
    check(len({a1["documentVersion"], a2["documentVersion"], a3["documentVersion"], a4["documentVersion"]}) == 4, "changed content must be a new version")
    check(b1["documentId"] != a1["documentId"] and u1["documentId"] != a1["documentId"] and c1["documentId"] != a1["documentId"], "other suppliers or sources must be other documents")
    check(exports["a1"]["observation"]["observedAt"] != exports["a1p"]["observation"]["observedAt"], "the replay must have its own observation time")
    for name, export in exports.items():
        document = export["document"]
        check(document["textArtifactId"] == "text-" + document["documentVersion"], f"{name}: textArtifactId is not text-<version>")
        check(document["sourceHash"] == python_source_hash(document["text"]), f"{name}: sourceHash is not Python's canonical JSON hash")
    check(exports["a1"]["document"]["text"] == exports["b1"]["document"]["text"] == exports["u1"]["document"]["text"], "same body bytes must give the same text")
    version = {name: ref["documentVersion"] for name, ref in {"a1": a1, "b1": b1, "a2": a2, "a3": a3, "a4": a4, "c1": c1, "u1": u1, "a8": a8}.items()}
    text = {name: exports[name]["document"]["text"] for name in exports}

    def file_state(path: Path) -> tuple:
        info = path.stat()
        return info.st_ino, info.st_mtime_ns, path.read_bytes()

    def assert_unchanged(label: str, before: dict):
        check(db.snapshot() == before, f"{label}: the database changed")

    def failed(label: str, code: int, result: dict | None, failure: str, index: int = 0):
        check(code != 0, f"{label}: the process must exit non-zero")
        check(result is not None and result["status"] == "failed", f"{label}: no failed result")
        check(result["items"][index]["status"] == "failed" and result["items"][index]["failure"]["code"] == failure,
              f"{label}: expected {failure}, got {json.dumps(result)[:400]}")
        return result["items"][index]["failure"]

    # ---- 1: first registration of A1, B1 (same bytes) and U1 (another source), explicit pointer from "none" --------
    label = step("first import: exact identities, rows, bytes and permissions")
    code, result, _ = jar.run("first", [item(a1, expected=None), item(b1, expected=None), item(u1, expected=None)])
    check(code == 0 and result["status"] == "succeeded", f"{label}: exit {code} {json.dumps(result)[:500]}")
    for index, name in enumerate(("a1", "b1", "u1")):
        outcome = result["items"][index]
        check(outcome["status"] == "imported" and (outcome["article"], outcome["artifact"], outcome["artifactFile"], outcome["version"])
              == ("created",) * 4, f"{label}: {name} was not created: {outcome}")
        check(outcome["currentVersion"] == {"result": "moved", "value": version[name]}, f"{label}: {name} pointer {outcome['currentVersion']}")
        check(outcome["documentId"] == exports[name]["document"]["documentId"] and outcome["textArtifactId"] == "text-" + version[name], f"{label}: {name} identity")
        check(iso_us(outcome["collectedAt"]) == iso_us(exports[name]["observation"]["observedAt"]), f"{label}: {name} collectedAt")
        check(outcome["grant"] == exports[name]["grant"], f"{label}: {name} grant echo")
    articles = {row["id"]: row for row in db.articles()}
    check(len(articles) == 3, f"{label}: expected 3 articles, got {len(articles)}")
    for name, ref in (("a1", a1), ("b1", b1), ("u1", u1)):
        row = articles[ref["documentId"]]
        check((row["kind"], row["provider"], row["provider_key"], row["lineage_key"], row["current_version"], row["access_status"])
              == ("news", ref["sourceId"], None, None, version[name], "available"), f"{label}: article {name} {row}")
    check(articles[u1["documentId"]]["provider"] == UNICODE_SOURCE, f"{label}: the Unicode provider was not stored exactly")
    versions = {(row["article_id"], row["version"]): row for row in db.versions()}
    for name, ref in (("a1", a1), ("b1", b1), ("u1", u1)):
        row = versions[(ref["documentId"], version[name])]
        observation = exports[name]["observation"]
        published = observation["publishedAt"]
        check((row["title"], row["publisher"], row["url"], row["raw_artifact_id"], row["text_artifact_id"], row["published_date"])
              == ("authored", DECLARED.get(name), observation["url"], None, "text-" + version[name], None), f"{label}: version {name} {row}")
        check(observation.get("publisher") == DECLARED.get(name) and ("publisher" in observation) == (name in DECLARED),
              f"{label}: {name} export publisher key {observation.get('publisher')!r}")
        check(row["collected_at"] == iso_us(observation["observedAt"]), f"{label}: version {name} collected_at {row['collected_at']}")
        if published is None:
            check((row["publication_precision"], row["published_at"]) == ("unknown", None), f"{label}: {name} precision {row}")
        else:
            check((row["publication_precision"], row["published_at"]) == ("datetime", iso_us(published)), f"{label}: {name} publication {row}")
    check(versions[(a1["documentId"], version["a1"])]["published_at"] == "2026-10-08T00:00:00.000000Z", f"{label}: +09:00 was not converted exactly")
    artifacts = {row["id"]: row for row in db.artifacts()}
    check(len(artifacts) == 3, f"{label}: expected 3 artifacts")
    for name in ("a1", "b1", "u1"):
        raw = text[name].encode("utf-8")
        row = artifacts["text-" + version[name]]
        check((row["kind"], row["storage_uri"], row["sha256"], row["bytes"], row["media_type"])
              == ("extracted_text", f"artifact-root:extracted_text/text-{version[name]}.txt", sha(raw), len(raw), "text/plain; charset=utf-8"),
              f"{label}: artifact {name} {row}")
        stored = world.text_file(version[name])
        check(stored.read_bytes() == raw, f"{label}: file bytes of {name} differ from the exported text")
        check(stat.S_IMODE(stored.stat().st_mode) == 0o600 and stored.stat().st_size == row["bytes"], f"{label}: file {name} mode/size")
    check(len({artifacts["text-" + version["a1"]]["storage_uri"], artifacts["text-" + version["b1"]]["storage_uri"]}) == 2
          and artifacts["text-" + version["a1"]]["sha256"] == artifacts["text-" + version["b1"]]["sha256"] == artifacts["text-" + version["u1"]]["sha256"],
          f"{label}: same bytes must keep separate artifact identities")
    check(stat.S_IMODE((world.artifacts / "extracted_text").stat().st_mode) == 0o700, f"{label}: extracted_text is not 0700")
    check(stat.S_IMODE((world.artifacts / ".document-import.lock").stat().st_mode) == 0o600, f"{label}: the lock file is not 0600")
    check(sorted(p.name for p in (world.artifacts / "extracted_text").iterdir()) == sorted(f"text-{version[n]}.txt" for n in ("a1", "b1", "u1")),
          f"{label}: unexpected files (temporary leftovers?) in the artifact directory")

    # ---- 2: the identical request again is a no-op ----------------------------------------------------------------
    label = step("repeat: idempotent, nothing rewritten")
    before = db.snapshot()
    inode_before = file_state(world.text_file(version["a1"]))
    code, result, _ = jar.run("repeat", [item(a1, expected=None), item(b1, expected=None), item(u1, expected=None)])
    check(code == 0, f"{label}: exit {code}")
    for outcome in result["items"]:
        check((outcome["article"], outcome["artifact"], outcome["artifactFile"], outcome["version"], outcome["currentVersion"]["result"])
              == ("existing", "existing", "existing", "existing", "already-current"), f"{label}: {outcome}")
    assert_unchanged(label, before)
    check(file_state(world.text_file(version["a1"])) == inode_before, f"{label}: the text file was rewritten")

    # ---- 3..5: new version, replay of the old one, explicit pointer move -------------------------------------------
    label = step("new version of the same document keeps the pointer")
    code, result, _ = jar.run("new-version", [item(a2)])
    check(code == 0, f"{label}: exit {code}")
    outcome = result["items"][0]
    check((outcome["article"], outcome["artifact"], outcome["artifactFile"], outcome["version"], outcome["currentVersion"])
          == ("existing", "created", "created", "created", {"result": "unchanged", "value": version["a1"]}), f"{label}: {outcome}")
    check(text["a2"] != text["a1"] and world.text_file(version["a2"]).read_bytes() == text["a2"].encode("utf-8"), f"{label}: A2 text")
    check({row["id"]: row["current_version"] for row in db.articles()}[a1["documentId"]] == version["a1"], f"{label}: the pointer moved")

    label = step("replay of an old version: existing, first observation kept, snapshot unchanged")
    before = db.snapshot()
    code, result, _ = jar.run("replay", [item(a1p)])
    check(code == 0, f"{label}: exit {code}")
    outcome = result["items"][0]
    check(outcome["version"] == "existing" and iso_us(outcome["collectedAt"]) == iso_us(exports["a1"]["observation"]["observedAt"])
          and iso_us(outcome["collectedAt"]) != iso_us(exports["a1p"]["observation"]["observedAt"]), f"{label}: {outcome}")
    assert_unchanged(label, before)

    label = step("explicit compare-and-set to the newer version")
    code, result, _ = jar.run("move", [item(a2, expected=version["a1"])])
    check(code == 0 and result["items"][0]["currentVersion"] == {"result": "moved", "value": version["a2"]}, f"{label}: {result}")

    # ---- 6..8: stale pointer, rollback and file compensation, crash orphan ----------------------------------------
    label = step("stale compare-and-set conflicts, stops the batch and changes nothing")
    before = db.snapshot()
    code, result, _ = jar.run("stale-batch", [item(a1p, expected=version["a1"]), item(a3)])
    failure = failed(label, code, result, "current_version_conflict")
    check(failure["currentVersion"] == version["a2"], f"{label}: the reported pointer is {failure}")
    check(result["items"][1] == {"index": 1, "status": "not_attempted"}, f"{label}: item 1 {result['items'][1]}")
    assert_unchanged(label, before)
    check(not world.text_file(version["a3"]).exists(), f"{label}: a file was created for the item that was not attempted")

    label = step("a new version with a stale pointer rolls back rows and removes its own new file")
    code, result, _ = jar.run("stale-new-version", [item(a3, expected=version["a1"])])
    failure = failed(label, code, result, "current_version_conflict")
    check(failure["currentVersion"] == version["a2"], f"{label}: {failure}")
    assert_unchanged(label, before)
    check(not world.text_file(version["a3"]).exists(), f"{label}: the new text file survived the rollback")
    check(sorted(p.name for p in (world.artifacts / "extracted_text").iterdir()) == sorted(f"text-{version[n]}.txt" for n in ("a1", "b1", "a2", "u1")),
          f"{label}: stray files in the artifact directory")

    label = step("crash orphan with the same bytes is never removed by a rollback and is adopted afterwards")
    orphan = world.text_file(version["a3"])
    orphan.write_bytes(text["a3"].encode("utf-8"))
    os.chmod(orphan, 0o600)
    orphan_state = file_state(orphan)
    code, result, _ = jar.run("orphan-stale", [item(a3, expected=version["a1"])])
    failed(label, code, result, "current_version_conflict")
    assert_unchanged(label, before)
    check(orphan.exists() and file_state(orphan) == orphan_state, f"{label}: the pre-existing file was touched")
    code, result, _ = jar.run("orphan-adopt", [item(a3)])
    check(code == 0, f"{label}: exit {code}")
    outcome = result["items"][0]
    check((outcome["artifactFile"], outcome["artifact"], outcome["version"], outcome["currentVersion"]["value"])
          == ("existing", "created", "created", version["a2"]), f"{label}: {outcome}")
    check(file_state(orphan) == orphan_state, f"{label}: the adopted file was rewritten")

    # ---- 9: conflicting immutable contents ---------------------------------------------------------------------------
    label = step("conflicts: article kind, tampered file, artifact row, version row, provider")
    before = db.snapshot()
    code, result, _ = jar.run("kind-conflict", [item(a2, kind="disclosure")])
    failed(label, code, result, "article_kind_conflict")
    assert_unchanged(label + " kind", before)

    tampered = world.text_file(version["a4"])
    tampered.write_bytes(b"tampered")
    os.chmod(tampered, 0o600)
    code, result, _ = jar.run("file-conflict", [item(a4)])
    failed(label, code, result, "artifact_file_conflict")
    check(tampered.read_bytes() == b"tampered", f"{label}: a tampered file was overwritten")
    tampered.unlink()
    assert_unchanged(label + " file", before)

    a4_artifact = "text-" + version["a4"]
    raw_a4 = text["a4"].encode("utf-8")
    db.run(f"INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at) VALUES ('{a4_artifact}', 'extracted_text', "
           f"'artifact-root:extracted_text/{a4_artifact}.txt', '{'0' * 64}', 1, 'text/plain; charset=utf-8', now())")
    planted = db.snapshot()
    code, result, _ = jar.run("artifact-conflict", [item(a4)])
    failed(label, code, result, "artifact_conflict")
    assert_unchanged(label + " artifact", planted)
    check(not world.text_file(version["a4"]).exists(), f"{label}: the file of a rolled-back conflicting item survived")
    db.run(f"DELETE FROM artifacts WHERE id = '{a4_artifact}'")

    db.run(f"INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at) VALUES ('{a4_artifact}', 'extracted_text', "
           f"'artifact-root:extracted_text/{a4_artifact}.txt', '{sha(raw_a4)}', {len(raw_a4)}, 'text/plain; charset=utf-8', now())")
    db.run(f"INSERT INTO article_versions (article_id, version, title, publication_precision, text_artifact_id, collected_at) "
           f"VALUES ('{a4['documentId']}', '{version['a4']}', 'a different title', 'unknown', '{a4_artifact}', now())")
    planted = db.snapshot()
    code, result, _ = jar.run("version-conflict", [item(a4)])
    failed(label, code, result, "version_conflict")
    assert_unchanged(label + " version", planted)
    check(not world.text_file(version["a4"]).exists(), f"{label}: the file of a rolled-back conflicting item survived")
    db.run(f"DELETE FROM article_versions WHERE article_id = '{a4['documentId']}' AND version = '{version['a4']}'")
    db.run(f"DELETE FROM artifacts WHERE id = '{a4_artifact}'")
    assert_unchanged(label + " cleanup", before)

    db.run(f"INSERT INTO articles (id, kind, provider, access_status, created_at) VALUES ('{c1['documentId']}', 'news', 'another-provider', 'available', now())")
    planted = db.snapshot()
    code, result, _ = jar.run("provider-conflict", [item(c1)])
    failed(label, code, result, "article_provider_conflict")
    assert_unchanged(label + " provider", planted)
    db.run(f"DELETE FROM articles WHERE id = '{c1['documentId']}'")

    # ---- 10: private / deleted articles are never written and never reset --------------------------------------------
    label = step("private and deleted articles are denied and keep their access status")
    for access in ("private", "deleted"):
        db.run(f"INSERT INTO articles (id, kind, provider, access_status, created_at) VALUES ('{c1['documentId']}', 'news', '{SOURCE}', '{access}', now())")
        planted = db.snapshot()
        code, result, _ = jar.run(f"denied-{access}", [item(c1, expected=None)])
        failed(f"{label} ({access})", code, result, "article_access_unavailable")
        assert_unchanged(f"{label} ({access})", planted)
        check(db.scalar(f"SELECT access_status FROM articles WHERE id = '{c1['documentId']}'") == access, f"{label}: {access} was reset")
        check(not world.text_file(version["c1"]).exists(), f"{label}: the file of a denied item survived")
        db.run(f"DELETE FROM articles WHERE id = '{c1['documentId']}'")
    assert_unchanged(label + " cleanup", before)

    # ---- 11: no grant bypass ----------------------------------------------------------------------------------------
    label = step("no grant bypass: pre-exported content is not accepted and a revoked grant blocks every write")
    for key in ("export", "document", "grant", "text"):
        bad = item(a3)
        bad[key] = {"text": text["a3"]}
        code, result, _ = jar.run(f"bypass-{key}", [bad])
        check(code != 0 and result["status"] == "failed" and result["failure"] == {"code": "request_invalid"} and result["items"] == [],
              f"{label}: {key} was not refused: {result}")
    assert_unchanged(label + " request", before)
    files_before = sorted(p.name for p in (world.artifacts / "extracted_text").iterdir())

    world.grant(SOURCE)["enabled"] = False
    world.save_registry()
    for name, requested in (("keep-registered", [item(a3)]), ("pointer-only", [item(a2, expected=version["a2"])]),
                            ("new-version", [item(a4)]), ("pointer-move", [item(a1, expected=version["a2"])])):
        code, result, _ = jar.run(f"revoked-{name}", requested)
        failure = failed(f"{label} ({name})", code, result, "ingestion_export_failed")
        check(failure.get("ingestionCode") == "source_unauthorized", f"{label}: {name} {failure}")
    assert_unchanged(label + " revoked", before)
    check(sorted(p.name for p in (world.artifacts / "extracted_text").iterdir()) == files_before, f"{label}: a revoked import created or removed a file")

    world.grant(SOURCE)["enabled"] = True
    # Rights the export needs: read and quote-display from the pipeline's own check, and `store` because the importer
    # persists the text and always asks the CLI for --require-store. Removing any ONE of them must stop every write.
    for missing, remaining in (("quote-display", ["read", "store"]), ("store", ["read", "quote-display"]), ("read", ["store", "quote-display"])):
        world.grant(SOURCE)["allowedOperations"] = remaining
        world.save_registry()
        files_now = sorted(p.name for p in (world.artifacts / "extracted_text").iterdir())
        for name, requested in (("keep-registered", [item(a3)]), ("new-version", [item(a4, expected=version["a2"])]),
                                ("pointer-move", [item(a1, expected=version["a2"])])):
            code, result, _ = jar.run(f"no-{missing}-{name}", requested)
            failure = failed(f"{label} (grant without {missing}: {name})", code, result, "ingestion_export_failed")
            check(failure.get("ingestionCode") == "source_unauthorized", f"{label}: without {missing}: {name} {failure}")
        assert_unchanged(f"{label} (grant without {missing})", before)
        check(sorted(p.name for p in (world.artifacts / "extracted_text").iterdir()) == files_now and not world.text_file(version["a4"]).exists(),
              f"{label}: an import without the {missing} right created or removed a file")
    world.grant(SOURCE)["allowedOperations"] = ["read", "store", "quote-display"]
    world.save_registry()
    code, result, _ = jar.run("restored", [item(a3)])
    check(code == 0 and result["items"][0]["version"] == "existing" and result["items"][0]["currentVersion"]["value"] == version["a2"], f"{label}: restored {result}")
    assert_unchanged(label + " restored", before)

    # ---- 12: filesystem failure never touches the database --------------------------------------------------------
    label = step("filesystem failure: no database write")
    broken = world.root / "artifacts-broken"
    broken.mkdir(mode=0o700)
    blocked_directory = broken / "extracted_text"
    blocked_directory.write_text("a file where the directory must be")
    os.chmod(blocked_directory, 0o600)
    code, result, _ = jar.run("fs-failure", [item(a4)], artifact_root=broken)
    failed(label, code, result, "artifact_store_unavailable")
    assert_unchanged(label, before)

    # ---- 13: the operator lock ---------------------------------------------------------------------------------------
    label = step("a held operator lock fails the whole request before any export")
    descriptor = os.open(world.artifacts / ".document-import.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code, result, _ = jar.run("busy", [item(a4), item(a3)])
    finally:
        os.close(descriptor)
    check(code != 0 and result["status"] == "failed" and result["failure"] == {"code": "import_busy"}
          and [i["status"] for i in result["items"]] == ["not_attempted", "not_attempted"], f"{label}: {result}")
    assert_unchanged(label, before)

    # ---- 14: the web guard and the unchanged normal start --------------------------------------------------------------
    label = step("enabled without --spring.main.web-application-type=none refuses to start; normal start is unchanged")
    refused_result = world.requests / "web-refusal-result.json"
    refused_request = world.requests / "web-refusal-request.json"
    refused_request.write_bytes(json.dumps({"schemaVersion": IMPORT_SCHEMA, "items": [item(a3)]}).encode("utf-8"))
    done = subprocess.run(jar.argv("--server.port=0"), env=jar.import_env(refused_request, refused_result, world.artifacts),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
    output = done.stdout.decode("utf-8", "replace")
    OUTPUT.append(output)
    check(done.returncode != 0 and "zoop.document-import.enabled" in output and "web-application-type" in output, f"{label}: the web start was not refused")
    check("Tomcat started" not in output and "Started ZoopApplication" not in output, f"{label}: a web server started next to an import")
    check(not refused_result.exists(), f"{label}: a refused start still created a result file")
    assert_unchanged(label, before)
    normal_start(jar)

    # ---- 15: a declared publisher is version-bound: a new version of document A, the older ones keep NULL -------------------
    label = step("declared publisher: a new version of an existing document stores it; NULL versions stay NULL; a NULL/other publisher conflicts")
    a_id = a1["documentId"]
    check(a8["documentId"] == a_id and a8["rawVersion"] != a1["rawVersion"] and version["a8"] != version["a1"],
          f"{label}: a declared publisher must be another raw/document version of the same document")
    check(text["a8"] == text["a1"] and exports["a8"]["observation"]["publisher"] == DECLARED["a8"]
          and all("publisher" not in exports[n]["observation"] for n in ("a1", "b1", "a2", "a1p", "a3", "a4", "c1")),
          f"{label}: exports must carry the publisher key only when one was declared")
    before = db.snapshot()
    old_versions = {(r["article_id"], r["version"]): r for r in db.versions()}
    a8_artifact = "text-" + version["a8"]
    raw_a8 = text["a8"].encode("utf-8")
    db.run(f"INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at) VALUES ('{a8_artifact}', 'extracted_text', "
           f"'artifact-root:extracted_text/{a8_artifact}.txt', '{sha(raw_a8)}', {len(raw_a8)}, 'text/plain; charset=utf-8', now())")
    db.run(f"INSERT INTO article_versions (article_id, version, title, publisher, url, published_at, publication_precision, text_artifact_id, collected_at) "
           f"VALUES ('{a_id}', '{version['a8']}', 'authored', NULL, 'https://example.invalid/a', '{exports['a8']['observation']['publishedAt']}', "
           f"'datetime', '{a8_artifact}', now())")
    planted = db.snapshot()
    code, result, _ = jar.run("publisher-null-conflict", [item(a8)])
    failed(label, code, result, "version_conflict")
    assert_unchanged(label + " (stored NULL vs declared)", planted)
    check(not world.text_file(version["a8"]).exists(), f"{label}: the file of a rolled-back conflicting item survived")
    db.run(f"DELETE FROM article_versions WHERE article_id = '{a_id}' AND version = '{version['a8']}'")
    db.run(f"DELETE FROM artifacts WHERE id = '{a8_artifact}'")
    assert_unchanged(label + " (cleanup)", before)

    code, result, _ = jar.run("publisher-new-version", [item(a8)])
    check(code == 0, f"{label}: exit {code} {json.dumps(result)[:400]}")
    outcome = result["items"][0]
    check((outcome["article"], outcome["artifact"], outcome["artifactFile"], outcome["version"]) == ("existing", "created", "created", "created")
          and outcome["currentVersion"] == {"result": "unchanged", "value": version["a2"]} and "publisher" not in outcome,
          f"{label}: {outcome}")
    after = {(r["article_id"], r["version"]): r for r in db.versions()}
    check(after[(a_id, version["a8"])]["publisher"] == DECLARED["a8"], f"{label}: publisher not stored exactly")
    check({k: v for k, v in after.items() if k != (a_id, version["a8"])} == old_versions,
          f"{label}: an earlier version row changed")
    check([after[(a_id, version[n])]["publisher"] for n in ("a1", "a2")] == [None, None], f"{label}: an older version gained a publisher")
    check(after[(u1["documentId"], version["u1"])]["publisher"] == DECLARED["u1"], f"{label}: Unicode publisher")
    before = db.snapshot()
    code, result, _ = jar.run("publisher-repeat", [item(a8)])
    check(code == 0 and result["items"][0]["version"] == "existing", f"{label}: repeat {result}")
    assert_unchanged(label + " (repeat)", before)

    # ---- final -----------------------------------------------------------------------------------------------------------
    label = step("final state, read-only ledger and no leaked credentials")
    check(len(db.articles()) == 3 and len(db.versions()) == 6 and len(db.artifacts()) == 6, f"{label}: final counts {len(db.articles())}/{len(db.versions())}/{len(db.artifacts())}")
    check(all(row["publication_precision"] in ("datetime", "unknown") for row in db.versions()), f"{label}: a day-precision row exists")
    check({row["id"]: row["current_version"] for row in db.articles()} == {a1["documentId"]: version["a2"], b1["documentId"]: version["b1"], u1["documentId"]: version["u1"]},
          f"{label}: unexpected pointers {db.articles()}")
    expected_files = sorted(f"text-{version[n]}.txt" for n in ("a1", "b1", "a2", "a3", "u1", "a8"))
    check(sorted(p.name for p in (world.artifacts / "extracted_text").iterdir()) == expected_files,
          f"{label}: unexpected files (temporary leftovers?) in the artifact directory")
    check(world.ledger_fingerprint() == fingerprint, f"{label}: the S2-1 ledger changed: the import must treat it as read-only")
    if args.upgrade_from:
        applied = db.rows("SELECT version, success FROM flyway_schema_history WHERE version IS NOT NULL ORDER BY installed_rank")
        versions = [row["version"] for row in applied]
        check(all(row["success"] for row in applied) and DOCUMENT_MIGRATION in versions and versions == sorted(versions)
              and versions.index(DOCUMENT_MIGRATION) > versions.index(args.upgrade_from) and versions[-1] == DOCUMENT_MIGRATION,
              f"{label}: the document migration did not apply after {args.upgrade_from}: {versions}")
    joined = "\n".join(OUTPUT)
    # A throwaway password such as "x" would match ordinary log text; only an unambiguous one can be searched for.
    check(len(db.password) < 8 or db.password not in joined, f"{label}: the database password appears in process output")
    check("jdbc:postgresql://" + db.user + ":" not in joined, f"{label}: credentials in a JDBC URL in process output")
    check(str(world.root) not in joined, f"{label}: an artifact or ledger path was logged")
    for body_text in (text["a1"], text["a2"], text["a3"]):
        check(body_text not in joined, f"{label}: document text was logged")

    print(json.dumps({"status": "passed", "steps": len(STEPS), "providerCalls": 0, "modelCalls": 0, "articles": 3, "versions": 6,
                      "artifacts": 6, "importRuns": jar.counter, "ledgerReadOnly": True}))
    return 0


def normal_start(jar: Jar):
    """The application without any import setting starts its web server as before (random port), then is stopped."""
    process = subprocess.Popen(jar.argv("--server.port=0"), env=jar.base_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines: list[str] = []

    def drain():
        for raw in process.stdout:
            lines.append(raw.decode("utf-8", "replace"))

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    deadline = time.monotonic() + 180
    try:
        while time.monotonic() < deadline and process.poll() is None and not any("Started ZoopApplication" in line for line in lines):
            time.sleep(0.5)
    finally:
        started = any("Started ZoopApplication" in line for line in lines)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
        reader.join(timeout=10)
    output = "".join(lines)
    OUTPUT.append(output)
    check(started and "Tomcat started" in output, "the application without import settings did not start its web server as before")
    check("document import" not in output.lower(), "the import ran or logged during a normal start")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as failure:
        print("document import smoke FAILED: " + str(failure).replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        for output in OUTPUT[-1:]:
            print("--- last process output (tail) ---\n" + output[-2500:].replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        sys.exit(1)
