#!/usr/bin/env python3
"""Operator smoke for the graph handoff import: installed `zoop-ai-handoff` + `zoop-ai-ingest` -> built Spring jar -> real PostgreSQL.

Every hop is a real process; nothing is mocked. Everything is synthetic and local: no network, no model, no provider. The script
  1. builds the authored ingestion + S2 + S3 world of `ai/pipeline/scripts/graph_handoff_smoke.py`, writes the operator files and
     FREEZES two handoffs with the installed `zoop-ai-handoff` (public company ids are `SYNTH:*`, so the seeded catalog is never
     touched),
  2. registers the three source documents in PostgreSQL with the built jar's document import (the app's own article rows, text
     artifacts and files),
  3. seeds the synthetic fixture graph versions (one ACTIVE pointer and its activation history) by starting the jar once with the
     fixture source, so there is a real pointer to leave untouched,
  4. runs the jar's non-web graph handoff import: it calls the installed `zoop-ai-handoff export` and, for EVERY observation,
     `zoop-ai-ingest export --require-store`, verifies the bundle, registers evidence and an INACTIVE graph version, and writes the
     retained receipt,
  5. checks the persisted rows, files and result document against facts it knows independently (the authored texts, hand-written
     evidence ids and offsets, the producer's own export of the handoff) and proves the refusals: wrong pins, a revoked `store`
     right, a withheld handoff, and an identical import being a no-op; it also starts the web application and shows that the staged
     version is not publicly readable.

Run it with the pipeline venv's Python (it imports the AI smoke world), against an EMPTY dedicated database (a throwaway one: it is
not cleaned):

  make pipeline-install api-build       # once: ai/pipeline/.venv and the jar (not run automatically)
  DB_URL=jdbc:postgresql://127.0.0.1:<port>/<db> DB_USERNAME=<user> DB_PASSWORD=<dummy> \
    [GRAPH_IMPORT_PSQL_CONTAINER=<container>] [GRAPH_IMPORT_DB_USER=<user>] [GRAPH_IMPORT_DB_NAME=<db>] \
    make api-graph-handoff-import-smoke

(the Make target runs this script with --jar/--handoff-cli/--ingest-cli; the direct python invocation with those flags and
--psql-container/--db-user/--db-name still works.) Handoff format 1 only: PR #217's future integration may change it.

On success the last stdout line is {"status": "passed", "steps": N, "providerCalls": 0, "modelCalls": 0, ...}; any failed
expectation exits non-zero.
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

API_SCRIPTS = Path(__file__).resolve().parent
PIPELINE = API_SCRIPTS.parents[1] / "ai" / "pipeline"
sys.path[:0] = [str(PIPELINE), str(API_SCRIPTS)]

import document_import_smoke as base  # noqa: E402  (database, jar and step helpers)
from scripts import graph_handoff_smoke as hs  # noqa: E402  (the authored AI world and its operator documents)

check, step = base.check, base.step
PUBLIC_IDS = {"KRX:005930": "SYNTH:000001", "KRX:000660": "SYNTH:000002"}   # the catalog's seeded ids are never reused
SCHEMA = "zoop-graph-handoff-import-1"
COMPANIES = (("SYNTH:000001", "합성기업"), ("SYNTH:000002", "합성부품"))
HANDOFFS = ("handoff-smoke-1", "handoff-smoke-2")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def version_id(handoff_id: str) -> str:
    return "gv-" + sha256(handoff_id.encode("utf-8"))


def fingerprint(path: Path) -> dict:
    """Every file under `path`: mode, size, mtime and hash (a read-only ledger must be identical afterwards)."""
    found = {}
    for item in sorted(path.rglob("*")):
        if item.is_file():
            info = item.stat()
            found[str(item.relative_to(path))] = (stat.S_IMODE(info.st_mode), info.st_size, info.st_mtime_ns, sha256(item.read_bytes()))
    return found


class Layout:
    """The directories of the world and of the app side, in the names the jar's settings use."""

    def __init__(self, world, ingest_cli: Path):
        self.world = world
        self.ingest_cli = ingest_cli
        self.work = Path(tempfile.mkdtemp(prefix="zoop-graphimport-app-")).resolve()   # a real path: no /var symlink on macOS
        atexit.register(shutil.rmtree, self.work, True)
        self.requests = self.work / "requests"
        self.artifacts = self.work / "artifacts"
        self.requests.mkdir(mode=0o700)
        self.artifacts.mkdir(mode=0o700)
        self.root = self.work                       # the names base.Jar expects from its "world"
        self.state = world.root / "ingestion"
        self.registry_path = world.kit.registry_path

    def ownership_env(self) -> dict:
        return hs.ownership_env()

    @property
    def ledgers(self) -> dict:
        return {name: self.world.root / name for name in ("ingestion", "extraction", "relation", "handoff")}


class Smoke:
    def __init__(self, args, db, layout):
        self.args, self.db, self.layout, self.world = args, db, layout, layout.world
        self.java = args.java
        self.jar = base.Jar(args.java, args.jar, db, layout)
        self.runs = 0

    # ---------------------------------------------------------------------------------------------------- jar runs ----
    def graph_env(self, request: Path, result: Path) -> dict:
        root = self.world.root
        return {**self.jar.base_env(), "ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED": "true",
                "ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST": str(request), "ZOOP_GRAPH_HANDOFF_IMPORT_RESULT": str(result),
                "ZOOP_HANDOFF_CLI": str(self.args.handoff_cli), "ZOOP_HANDOFF_STATE_DIR": str(root / "handoff"),
                "ZOOP_RELATION_STATE_DIR": str(root / "relation"), "ZOOP_EXTRACTION_STATE_DIR": str(root / "extraction"),
                "ZOOP_INGESTION_CLI": str(self.args.ingest_cli), "ZOOP_INGESTION_STATE_DIR": str(root / "ingestion"),
                "ZOOP_INGESTION_SOURCES": str(self.layout.registry_path), "ZOOP_HANDOFF_CANONICAL": str(root / "canonical.json"),
                "ZOOP_HANDOFF_DECISIONS": str(root / "decisions.json"), "ZOOP_HANDOFF_BINDINGS": str(root / "bindings.json"),
                "ZOOP_ARTIFACT_ROOT": str(self.layout.artifacts), **hs.ownership_env()}

    def graph_import(self, label: str, request: dict | bytes) -> tuple[int, dict | None, str]:
        """One operator run of the graph handoff import; returns (exit status, parsed result file, process output)."""
        self.runs += 1
        stem = f"{self.runs:02d}-{label}"
        request_path = self.layout.requests / f"{stem}-request.json"
        result_path = self.layout.requests / f"{stem}-result.json"
        request_path.write_bytes(request if isinstance(request, bytes) else json.dumps(request).encode("utf-8"))
        try:
            done = subprocess.run(self.jar.argv("--spring.main.web-application-type=none"), env=self.graph_env(request_path, result_path),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=420)
        except subprocess.TimeoutExpired as expired:
            base.OUTPUT.append((expired.stdout or b"").decode("utf-8", "replace"))
            raise AssertionError(f"{label}: the import JVM did not exit within 420s (result file exists: {result_path.exists()})")
        output = done.stdout.decode("utf-8", "replace")
        base.OUTPUT.append(output)
        parsed = None
        if result_path.exists():
            check(stat.S_IMODE(result_path.stat().st_mode) & 0o077 == 0, f"{label}: result file is not owner-only")
            text = result_path.read_text("utf-8")
            check(text, f"{label}: the result file was reserved but left empty")
            for private in (str(self.world.root), str(self.layout.work)):
                check(private not in text, f"{label}: the result file leaks a path")
            for secret in hs.PRIVATE:
                check(secret not in text, f"{label}: the result file leaks source or review text")
            parsed = json.loads(text)
        return done.returncode, parsed, output

    @staticmethod
    def request(handoff_id: str, manifest_digest: str, bundle_digest: str) -> dict:
        return {"schemaVersion": SCHEMA, "handoffId": handoff_id, "expectedManifestDigest": manifest_digest,
                "expectedBundleDigest": bundle_digest, "operator": "smoke-operator"}

    # ---------------------------------------------------------------------------------------------------- web runs ----
    def web(self, extra_env: dict, ready: str | None = None):
        """The built application as a web server on a free loopback port; `with` stops it (after `ready` appeared in its log)."""
        return WebRun(self.jar, extra_env, ready)

    # ---------------------------------------------------------------------------------------------------- database -----
    def table_fingerprint(self) -> dict:
        return json.loads(self.db.run("""
            SELECT json_build_object(
              'versions', (SELECT md5(coalesce(string_agg(v::text, '|' ORDER BY v.id), '')) FROM graph_versions v),
              'activations', (SELECT md5(coalesce(string_agg(a::text, '|' ORDER BY a.id), '')) FROM graph_activations a),
              'evidence', (SELECT md5(coalesce(string_agg(e::text, '|' ORDER BY e.id), '')) FROM evidence e),
              'artifacts', (SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x.id), '')) FROM artifacts x),
              'articles', (SELECT md5(coalesce(string_agg(a::text, '|' ORDER BY a.id), '')) FROM articles a),
              'versionsOfArticles', (SELECT md5(coalesce(string_agg(v::text, '|' ORDER BY v.article_id, v.version), '')) FROM article_versions v))"""))

    def set_registry(self, change):
        """Atomically rewrites the one source registry both CLIs read (a reader sees the old or the new file)."""
        path = self.layout.registry_path
        registry = json.loads(path.read_text("utf-8"))
        change(registry["sources"][0]["grant"])
        temporary = path.parent / "next-sources.json"
        temporary.write_bytes(hs.json_bytes(registry))
        temporary.replace(path)

    def ingest_export(self, ref: dict, *, require_store: bool) -> int:
        """Runs the installed `zoop-ai-ingest export` for one observation against the CURRENT registry; returns its exit status."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1", **hs.ownership_env()}
        argv = [str(self.args.ingest_cli), "export", "--state-dir", str(self.world.root / "ingestion"), "--sources",
                str(self.layout.registry_path)] + (["--require-store"] if require_store else [])
        done = subprocess.run(argv, input=hs.json_bytes({"schemaVersion": "zoop-ingestion-s2-1", **ref}), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env, timeout=120)
        return done.returncode

    def fixture_source_start(self) -> tuple[int, str]:
        """Starts the application with the local/dev fixture source against the CURRENT database; returns (exit status, output)."""
        port = "--server.port=0"
        done = subprocess.run(self.jar.argv(port, "--server.address=127.0.0.1"), env={**self.jar.base_env(), "ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture"},
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        output = done.stdout.decode("utf-8", "replace")
        base.OUTPUT.append(output)
        return done.returncode, output


class WebRun:
    def __init__(self, jar, extra_env: dict, ready: str | None = None):
        self.ready = ready
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.lines: list[str] = []
        self.process = subprocess.Popen(jar.argv(f"--server.port={self.port}", "--server.address=127.0.0.1"),
                                        env={**jar.base_env(), **extra_env}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        threading.Thread(target=self.drain, daemon=True).start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def drain(self):
        for raw in self.process.stdout:
            self.lines.append(raw.decode("utf-8", "replace"))

    def __enter__(self):
        deadline = time.monotonic() + 240
        # "Started ..." is logged BEFORE the application runners run, so a runner's own log line is the readiness of its work.
        marker = self.ready or "Started ZoopApplication"
        while time.monotonic() < deadline and self.process.poll() is None and not any(marker in l for l in self.lines):
            time.sleep(0.5)
        check(any(marker in l for l in self.lines), "the web application did not become ready:\n" + "".join(self.lines)[-1500:])
        return self

    def __exit__(self, *exc):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
        base.OUTPUT.append("".join(self.lines))

    def get(self, path: str) -> tuple[int, str]:
        try:
            with self.opener.open(f"http://127.0.0.1:{self.port}{path}", timeout=30) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--handoff-cli", required=True, type=Path)
    parser.add_argument("--ingest-cli", required=True, type=Path)
    parser.add_argument("--java", default=None, help="java binary (default: $JAVA_HOME/bin/java, then PATH)")
    parser.add_argument("--psql-container", default=None, help="database container to `docker exec psql` in")
    parser.add_argument("--psql", default=shutil.which("psql"), help="host psql (used without --psql-container)")
    parser.add_argument("--db-user", default=None)
    parser.add_argument("--db-name", default=None)
    args = parser.parse_args()
    for name in ("DB_URL", "DB_USERNAME", "DB_PASSWORD"):
        check(os.environ.get(name), f"{name} must be set (a dedicated loopback database)")
    args.java = args.java or (str(Path(os.environ["JAVA_HOME"]) / "bin" / "java") if os.environ.get("JAVA_HOME") else shutil.which("java"))
    check(args.java, "no java: set JAVA_HOME or pass --java")
    args.jar, args.handoff_cli, args.ingest_cli = args.jar.resolve(), args.handoff_cli.resolve(), args.ingest_cli.resolve()
    check(args.jar.is_file(), "--jar does not exist (build it with ./api/gradlew -p api assemble)")
    for cli in (args.handoff_cli, args.ingest_cli):
        check(cli.is_file() and os.access(cli, os.X_OK), f"{cli.name} is not an executable file")
    db = base.Database(os.environ["DB_URL"], args.db_user or os.environ["DB_USERNAME"], os.environ["DB_PASSWORD"], args.db_name,
                       args.psql_container, args.psql)
    if db.tables_exist():
        check(db.scalar("SELECT (SELECT count(*) FROM articles) + (SELECT count(*) FROM article_versions) + (SELECT count(*) FROM artifacts)"
                        " + (SELECT count(*) FROM graph_versions) + (SELECT count(*) FROM evidence) = 0"),
              "the database already holds document or graph rows: use a dedicated empty database")

    # ---- the authored world and two frozen handoffs, through the installed handoff CLI ---------------------------------
    scratch = Path(tempfile.mkdtemp(prefix="zoop-graphimport-world-")).resolve()
    atexit.register(shutil.rmtree, scratch, True)
    world = hs.build_world(scratch / "owned")
    decisions = hs.decisions_doc(world)
    for company in decisions["companies"]:
        company["publicId"] = PUBLIC_IDS[company["publicId"]]
    hs.write_operator(world, decisions=decisions)
    operator = hs.Operator(world)
    manifests = {hid: hs.manifest_doc(world, hid, hs.file_hashes(world.root)) for hid in HANDOFFS}
    for hid, manifest in manifests.items():
        frozen = operator.cli("freeze", manifest)
        check(frozen["state"] == "ready" and frozen["publication"] == "not-published", f"freeze {hid}: {frozen}")
    exported = {hid: operator.cli("export", operator.sel(hid)) for hid in HANDOFFS}
    pins = {}
    for hid in HANDOFFS:
        manifest_digest = hs.digest(manifests[hid])
        bundle_digest = sha256(hs.canonical(exported[hid]["bundle"]).encode("utf-8"))
        check(manifest_digest == exported[hid]["receipt"]["manifestDigest"] and bundle_digest == exported[hid]["receipt"]["bundleDigest"],
              f"{hid}: the producer's digests are not the canonical hashes")
        pins[hid] = (manifest_digest, bundle_digest)
    layout = Layout(world, args.ingest_cli)
    smoke = Smoke(args, db, layout)
    ledgers_before = {name: fingerprint(path) for name, path in layout.ledgers.items()}
    step("two handoffs frozen by the installed zoop-ai-handoff over the authored S2/S3 world (synthetic company ids SYNTH:*)")

    # ---- the app's own documents, registered by the jar's document import ----------------------------------------------
    items = [base.item(ref) for ref in world.refs.values()]
    status, result, _ = smoke.jar.run("documents", items, artifact_root=layout.artifacts)
    check(status == 0 and result and result["status"] == "succeeded", f"document import failed: {result}")
    db.run("INSERT INTO companies (id, name, name_key, search_text) VALUES "
           + ", ".join(f"('{cid}', '{name}', '', '')" for cid, name in COMPANIES))
    step("three source documents registered by the document import; two synthetic catalog companies inserted")

    # ---- a real active pointer to leave untouched ----------------------------------------------------------------------
    with smoke.web({"ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture"}, ready="Graph fixture fixture-2026-10-08 "):
        pass
    active_before = db.scalar("SELECT id FROM graph_versions WHERE active")
    history_before = db.scalar("SELECT coalesce(md5(string_agg(a::text, '|' ORDER BY a.id)), '') FROM graph_activations a")
    check(active_before == "fixture-2026-10-08", f"unexpected active fixture version {active_before}")
    check(db.scalar("SELECT count(*) FROM graph_activations") == 2, "the fixture activation history is not two rows")
    step("fixture versions seeded: fixture-2026-10-08 is the active pointer with two activation rows")

    # ---- the import --------------------------------------------------------------------------------------------------
    hid = HANDOFFS[0]
    vid = version_id(hid)
    manifest_digest, bundle_digest = pins[hid]
    before = smoke.table_fingerprint()
    status, result, output = smoke.graph_import("first", smoke.request(hid, manifest_digest, bundle_digest))
    check(status == 0 and result and result["status"] == "succeeded", f"the import failed: {result} {output[-800:]}")
    check(result["outcome"] == "staged" and result["graphVersionId"] == vid and result["handoffId"] == hid, f"unexpected result {result}")
    check(result["publication"] == "not-published" and result["activation"] == "not-activated" and result["active"] is False
          and result["publicRead"] == "unavailable" and result["nextActivation"] == "unsupported", f"the result overclaims: {result}")
    check(result["digests"] == {"manifest": manifest_digest, "bundle": bundle_digest,
                                "content": exported[hid]["receipt"]["contentDigest"]}, f"digests: {result['digests']}")
    check(result["provenance"]["sourceKind"] == "synthetic" and result["provenance"]["executionMode"] == "replay"
          and result["provenance"]["relationOrigins"] == {"manual-operator-review": 1, "s2-comparison-with-operator-decision": 1,
                                                          "s3-relation": 2}, f"provenance: {result['provenance']}")
    check(result["quoteVerification"] == "quote-integrity-only", "the quote check overclaims")
    check(result["counts"] == {"companies": 2, "issues": 2, "relations": 4, "articles": 3, "evidence": 6}, f"counts: {result['counts']}")
    check(result["evidenceRows"] == {"registered": 6, "existing": 0}, f"evidence rows: {result['evidenceRows']}")
    step("import: real handoff export + per-observation ingestion export --require-store, 6 evidence rows and an inactive version staged")

    # the version row and the untouched pointer ------------------------------------------------------------------------
    row = db.rows(f"""SELECT id, kind, active, review_revision, created_by, policy_version, source_label, issue_count, relation_count,
        article_count, snapshot_artifact_id, rule_revision, candidate_count, published_at IS NULL AS unpublished
        FROM graph_versions WHERE id = '{vid}'""")
    check(len(row) == 1, f"graph_versions rows for {vid}: {row}")
    row = row[0]
    check(row["kind"] == "snapshot" and row["active"] is False and row["review_revision"] == 0 and row["unpublished"] is True
          and row["created_by"] == "operator:smoke-operator" and row["policy_version"] == "zoop-public-projection-policy-1"
          and row["source_label"] == f"graph-handoff:{hid}" and (row["issue_count"], row["relation_count"], row["article_count"]) == (2, 4, 3)
          and row["snapshot_artifact_id"] == f"artifact-{vid}" and row["rule_revision"] is None and row["candidate_count"] is None,
          f"version row: {row}")
    check(db.scalar("SELECT id FROM graph_versions WHERE active") == active_before, "the active pointer moved")
    check(db.scalar("SELECT count(*) FROM graph_versions WHERE active") == 1, "not exactly one active version")
    check(db.scalar("SELECT coalesce(md5(string_agg(a::text, '|' ORDER BY a.id)), '') FROM graph_activations a") == history_before,
          "the activation history changed")
    check(db.scalar(f"SELECT count(*) FROM graph_activations WHERE version_id = '{vid}'") == 0, "the import wrote an activation")
    step("the active pointer, its history and every other version are untouched; the staged row is inactive, unpublished, revision 0")

    # evidence: hand-written ids, code point offsets, exact quotes, the retained receipt as verification artifact --------
    spans = [("a", hs.EVT_A), ("a", hs.GEO_A), ("a", hs.SUP), ("a2", hs.EVT_A2), ("b", hs.QB), ("b", hs.GEO_B)]
    rows = {r["id"]: r for r in db.rows("""SELECT id, article_id, article_version, text_artifact_id, quote, start_offset, end_offset,
        offset_unit, input_kind, raw_locator_ids, quote_verified, verification_artifact_id, summary_analysis_id FROM evidence""")}
    check(set(rows) == {hs.evidence_id(world, name, quote) for name, quote in spans}, "evidence ids differ from the hand-written formula")
    for name, quote in spans:
        span = hs.span(world, name, quote)
        stored = rows[hs.evidence_id(world, name, quote)]
        check(stored["quote"] == quote and stored["start_offset"] == span["start"] and stored["end_offset"] == span["end"]
              and stored["article_id"] == span["documentId"] and stored["article_version"] == span["documentVersion"]
              and stored["offset_unit"] == "unicode_code_point" and stored["input_kind"] == "body"
              and stored["text_artifact_id"] == "text-" + span["documentVersion"] and stored["summary_analysis_id"] is None
              and stored["raw_locator_ids"] and all(isinstance(x, str) for x in stored["raw_locator_ids"]),
              f"evidence row of {name}: {stored}")
        check(stored["quote_verified"] is True and stored["verification_artifact_id"] == f"artifact-receipt-{vid}",
              f"the evidence is not tied to the retained receipt: {stored}")
    step("evidence rows: app formula ids, exact quotes at code point offsets, verification artifact = the retained receipt")

    # the two artifacts and their files ---------------------------------------------------------------------------------
    artifacts = {a["id"]: a for a in db.rows("SELECT id, kind, storage_uri, sha256, bytes, media_type FROM artifacts "
                                             f"WHERE id IN ('artifact-{vid}', 'artifact-receipt-{vid}')")}
    check(set(artifacts) == {f"artifact-{vid}", f"artifact-receipt-{vid}"}, f"artifacts: {sorted(artifacts)}")
    snapshot_file = layout.artifacts / "graph_snapshot" / f"{vid}.json"
    receipt_file = layout.artifacts / "verification_receipt" / f"{vid}.json"
    for artifact_id, path, kind in ((f"artifact-{vid}", snapshot_file, "graph_snapshot"), (f"artifact-receipt-{vid}", receipt_file, "verification_receipt")):
        raw = path.read_bytes()
        record = artifacts[artifact_id]
        check(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{path.name} is not owner-only")
        check(record["kind"] == kind and record["sha256"] == sha256(raw) and record["bytes"] == len(raw)
              and record["storage_uri"] == f"artifact-root:{path.parent.name}/{path.name}" and record["media_type"] == "application/json",
              f"artifact row {record}")
    snapshot = json.loads(snapshot_file.read_text("utf-8"))
    check(set(snapshot) == {"snapshotFormat", "versionId", "sourceBundleId", "companies", "issues", "relations", "articles", "evidence"}
          and snapshot["snapshotFormat"] == 1 and snapshot["versionId"] == vid and snapshot["sourceBundleId"] == hid,
          "the snapshot is not format 1 of this handoff")
    check({c["companyId"] for c in snapshot["companies"]} == {cid for cid, _ in COMPANIES} and len(snapshot["issues"]) == 2
          and len(snapshot["relations"]) == 4 and len(snapshot["articles"]) == 3 and len(snapshot["evidence"]) == 6, "snapshot content")
    check(sorted(str(a["publishedAt"]) for a in snapshot["articles"]) == sorted(["2026-10-08T00:00:00Z", "2026-10-08T00:00:00Z", "None"]),
          f"article publication times: {[a['publishedAt'] for a in snapshot['articles']]}")
    structural = next(r for r in snapshot["relations"] if r["relationType"] == "STRUCTURALLY_RELATED_TO")
    check(structural["basis"][0]["validFrom"] is None and structural["basis"][0]["validUntil"] is None,
          "an unknown validity was not kept unknown")
    receipt = json.loads(receipt_file.read_text("utf-8"))
    check(receipt["bundle"] == exported[hid]["bundle"] and receipt["manifest"] == manifests[hid], "the receipt does not retain the original")
    check(hs.digest(receipt["manifest"]) == manifest_digest and sha256(hs.canonical(receipt["bundle"]).encode("utf-8")) == bundle_digest,
          "the receipt's manifest and bundle do not hash to the pins")
    check(receipt["appVerification"]["semanticTruth"] == "not-verified" and receipt["appVerification"]["activation"] == "none",
          "the receipt overclaims")
    check(db.scalar("SELECT count(*) FROM artifacts WHERE kind IN ('graph_snapshot', 'verification_receipt')") == 2 + 2,
          "unexpected extra graph artifacts (two fixture snapshots and this import's two are expected)")
    step("snapshot (format 1) and receipt files registered with the registry's hash and size; the receipt retains the original manifest and bundle")

    # nothing public ----------------------------------------------------------------------------------------------------
    with smoke.web({"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts)}) as web:
        code, body = web.get(f"/api/v1/graph?graphVersion={vid}")
        check(code == 409 and "VERSION_UNAVAILABLE" in body, f"the staged version is publicly readable: {code} {body[:300]}")
        # Reads that do not name the staged version are exactly what they were: the artifact source serves the registered fixture
        # versions through the existing fixture reader, and the default and asOf selection still follow the activation history.
        code, body = web.get("/api/v1/graph")
        graph = json.loads(body) if code == 200 else {}
        check(code == 200 and graph["metadata"]["graphVersion"] == active_before and graph["nodes"] and vid not in body and hid not in body,
              f"the default read is not the unchanged active fixture version: {code} {body[:300]}")
        code, body = web.get("/api/v1/graph?asOf=2026-10-05T00:00:00Z")
        check(code == 200 and json.loads(body)["metadata"]["graphVersion"] == "fixture-2026-10-01" and vid not in body,
              f"the asOf read is not the unchanged historical fixture version: {code} {body[:300]}")
    check(db.scalar("SELECT id FROM graph_versions WHERE active") == active_before, "starting the web application moved the pointer")
    step("web (artifact source): graphVersion=<staged> is 409 VERSION_UNAVAILABLE; the default and asOf reads still serve the unchanged fixture versions")

    # the fixture seeder keeps refusing a database that holds imported versions, and refusing changes nothing -------------
    refused_status, refused_output = smoke.fixture_source_start()
    check(refused_status != 0 and "refuses a database that already has imported graph versions" in refused_output,
          f"the fixture source did not refuse a database with an imported version (exit {refused_status})")
    check(db.scalar("SELECT id FROM graph_versions WHERE active") == active_before
          and db.scalar("SELECT coalesce(md5(string_agg(a::text, '|' ORDER BY a.id)), '') FROM graph_activations a") == history_before,
          "the refused fixture start changed the pointer or its history")
    step("starting the fixture source after an import is refused (existing guard) and leaves the pointer and history untouched")

    # an identical import is a no-op ------------------------------------------------------------------------------------
    after_first = smoke.table_fingerprint()
    inode, mtime = snapshot_file.stat().st_ino, snapshot_file.stat().st_mtime_ns
    status, result, output = smoke.graph_import("again", smoke.request(hid, manifest_digest, bundle_digest))
    check(status == 0 and result["outcome"] == "unchanged" and result["evidenceRows"] == {"registered": 0, "existing": 6}, f"rerun: {result}")
    check(smoke.table_fingerprint() == after_first, "an identical import changed the database")
    check((snapshot_file.stat().st_ino, snapshot_file.stat().st_mtime_ns) == (inode, mtime), "an identical import rewrote the snapshot file")
    step("an identical import is a no-op: unchanged outcome, identical rows and files")

    # wrong pins --------------------------------------------------------------------------------------------------------
    for label, request in (("pin-manifest", smoke.request(hid, "0" * 64, bundle_digest)), ("pin-bundle", smoke.request(hid, manifest_digest, "0" * 64))):
        status, result, output = smoke.graph_import(label, request)
        check(status != 0 and result["status"] == "failed" and result["failure"]["code"] == "pin_mismatch", f"{label}: {result}")
    status, result, output = smoke.graph_import("not-a-request", b'{"schemaVersion": "zoop-graph-handoff-import-1"}')
    check(status != 0 and result["failure"]["code"] == "request_invalid", f"request: {result}")
    check(smoke.table_fingerprint() == after_first, "a refused request changed the database")
    step("wrong pins and an invalid request are refused (pin_mismatch / request_invalid) with nothing written")

    # a second handoff: rights are decided by the CURRENT registry -----------------------------------------------------------
    hid2 = HANDOFFS[1]
    vid2 = version_id(hid2)
    manifest2, bundle2 = pins[hid2]
    before_rights = smoke.table_fingerprint()
    smoke.set_registry(lambda grant: grant.update({"allowedOperations": [op for op in grant["allowedOperations"] if op != "store"]}))
    first_ref = base.item(next(iter(world.refs.values())))["observation"]
    # The CLI distinction the importer relies on: without the store right a plain export still works, --require-store refuses.
    check(smoke.ingest_export(first_ref, require_store=False) == 0 and smoke.ingest_export(first_ref, require_store=True) == 2,
          "zoop-ai-ingest export does not distinguish the store right")
    status, result, output = smoke.graph_import("no-store-right", smoke.request(hid2, manifest2, bundle2))
    failure = result["failure"]
    # The handoff CLI does not check `store` (it needs read + quote-display), so the per-observation export is what refuses.
    check(status != 0 and failure["code"] == "ingestion_export_failed" and re_code(failure.get("ingestionCode")) and failure["observation"] == 0,
          f"a missing store right was not refused by the per-observation export: {result}")
    check(smoke.table_fingerprint() == before_rights and not (layout.artifacts / "graph_snapshot" / f"{vid2}.json").exists(),
          "a refused right left rows or files behind")
    smoke.set_registry(lambda grant: grant.update({"allowedOperations": ["read", "store", "quote-display"], "enabled": False}))
    status, result, output = smoke.graph_import("grant-disabled", smoke.request(hid2, manifest2, bundle2))
    check(status != 0 and result["failure"]["code"] == "handoff_withheld" and re_code(result["failure"].get("handoffCode")), f"withheld: {result}")
    check(smoke.table_fingerprint() == before_rights, "a withheld handoff left rows behind")
    smoke.set_registry(lambda grant: grant.update({"enabled": True}))
    status, result, output = smoke.graph_import("rights-restored", smoke.request(hid2, manifest2, bundle2))
    check(status == 0 and result["outcome"] == "staged" and result["graphVersionId"] == vid2, f"restored: {result}")
    check(db.scalar("SELECT count(*) FROM graph_versions WHERE active") == 1 and db.scalar("SELECT id FROM graph_versions WHERE active") == active_before
          and db.scalar("SELECT count(*) FROM graph_versions WHERE kind = 'snapshot' AND NOT active") == 2
          and db.scalar("SELECT count(*) FROM graph_activations") == 2, "the second import moved the pointer or activated a version")
    check(db.scalar("SELECT count(*) FROM evidence") == 6 and db.scalar(f"SELECT count(*) FROM evidence WHERE verification_artifact_id = 'artifact-receipt-{vid}'") == 6,
          "the second handoff re-registered or re-pointed shared evidence")
    step("rights: a missing store right (per-observation export), a revoked grant (withheld handoff) and their restoration; the second handoff stages and shares the evidence rows")

    # ledgers, logs --------------------------------------------------------------------------------------------------------
    check({name: fingerprint(path) for name, path in layout.ledgers.items()} == ledgers_before,
          "a source or handoff ledger changed (they are opened read-only)")
    joined = "\n".join(base.OUTPUT)
    password = os.environ["DB_PASSWORD"]
    check(str(world.root) not in joined and str(layout.work) not in joined and (len(password) < 8 or password not in joined),
          "a path or secret reached a process output")
    for text in hs.PRIVATE:
        check(text not in joined, "source or review text reached a process output")
    step("every ledger is byte/mode/mtime identical; no path, secret or source text in any output")

    print(json.dumps({"status": "passed", "steps": len(base.STEPS), "providerCalls": 0, "modelCalls": 0, "handoffs": 2,
                      "evidenceRows": 6, "stagedVersions": 2, "activationsWritten": 0, "importRuns": smoke.runs, "ledgerReadOnly": True}))
    return 0


def re_code(value) -> bool:
    return isinstance(value, str) and value.replace("_", "").isalnum() and value == value.lower()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as failure:
        print("graph handoff import smoke FAILED: " + str(failure).replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        for output in base.OUTPUT[-1:]:
            print("--- last process output (tail) ---\n" + output[-2500:].replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        sys.exit(1)
