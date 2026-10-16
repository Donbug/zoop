#!/usr/bin/env python3
"""Operator smoke for HTTP-collected documents: local HTTP server -> installed `zoop-ai-collect` -> installed `zoop-ai-ingest`
-> built Spring jar -> real PostgreSQL. Every hop is a real process (or a real socket); nothing is mocked.

Companion of `document_import_smoke.py` (authored fixtures; it is imported for its database, world and jar helpers and its checks
stay as they are). Everything is synthetic and loopback only: no external network, no provider, no model, no PoC key. Run it
with the default pipeline environment (public dependencies only; `investmate` is verified absent from it), against an EMPTY dedicated database
(not the one the authored smoke filled):

  make pipeline-install                 # once: ai/pipeline/.venv
  DB_URL=jdbc:postgresql://127.0.0.1:<port>/<db> DB_USERNAME=<user> DB_PASSWORD=<dummy> \
    ai/pipeline/.venv/bin/python api/scripts/document_import_collected_smoke.py \
      --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar \
      --ingest-cli "$PWD/ai/pipeline/.venv/bin/zoop-ai-ingest" \
      --collect-cli "$PWD/ai/pipeline/.venv/bin/zoop-ai-collect" \
      --psql-container <container> --db-user <user> --db-name <db>

Scenario: four documents served by the local server (declared day / offset instant / offset-less local time / nothing) are
collected, prepared by the ledger and imported by the jar. The script checks the persisted rows, files and result document against
facts it knows independently (the bytes it served, the time window of the collection, the receipt file on disk). It then proves
the refusals (wrong request kind, tampered collection metadata) leave no row and no file, and that repeating the import is a no-op.
On success the last stdout line is {"status": "passed", "steps": N, "providerCalls": 0, "modelCalls": 0, ...}.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parent))
import document_import_smoke as base  # noqa: E402  (helpers only; its authored scenario is not run)

check, step, sha, json_bytes, iso_us, item = base.check, base.step, base.sha, base.json_bytes, base.iso_us, base.item
SOURCE = "synthetic-source"
COLLECTION_SCHEMA = "zoop-collection-1"
COLLECTION_ID = "collect-1"
USER_AGENT = "ZoopSyntheticCollector/1.0 (+synthetic-local-test)"
PROXY_ENV = {name: "http://127.0.0.1:9" for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")}
CONTENT_TYPE = "text/html; charset=utf-8"
ROBOTS = b"User-agent: *\nAllow: /\n"

# key, route, label, declared kind, declared publication, expected (precision, published_at, published_date, declared precision)
DOCUMENTS = [
    ("day", "/news/day", "일자만 선언된 기사", "news", "2026-10-14", ("day", None, "2026-10-14"), "day"),
    ("instant", "/disclosure/instant", "오프셋 있는 공시", "disclosure", "2026-10-14T09:00:00+09:00",
     ("datetime", "2026-10-14T00:00:00.000000Z", None), "instant"),
    ("unresolved", "/news/unresolved", "오프셋 없는 기사", "news", "2026-10-14T09:00:00", ("unknown", None, None), "unresolved"),
    ("undeclared", "/news/undeclared", "시각 미선언 기사", "news", None, ("unknown", None, None), "unknown"),
]


def page(label: str) -> bytes:
    return (f"<html><head><title>합성</title></head><body><article><p>{label} &amp; <b>본문😀</b> 끝</p><p>둘째 문단</p></article>"
            "</body></html>").encode("utf-8")


def expected_text(label: str) -> str:
    return f"{label} & 본문😀 끝\n둘째 문단"


class Site:
    """A real HTTP/1.0 server on 127.0.0.1 with fixed routes and a request log."""

    def __init__(self, routes: dict[str, tuple[bytes, str]]):
        self.log: list[dict] = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.log.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
                body, content_type = routes.get(self.path.split("?")[0], (b"missing", "text/plain"))
                self.send_response(200 if self.path.split("?")[0] in routes else 404)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class CollectedWorld(base.World):
    """The base world with ONE `collected-http` source for the loopback host, plus the collector policy and CLI."""

    def __init__(self, ingest_cli: Path, collect_cli: Path):
        self.collect_cli = collect_cli
        super().__init__(ingest_cli)
        self.registry["sources"] = self.registry["sources"][:1]
        self.save_registry()
        self.policy_path = self.root / "policy.json"
        self.policy_path.write_bytes(json_bytes({
            "schemaVersion": "zoop-collection-policy-1", "userAgent": USER_AGENT, "timeoutSeconds": 5, "maxTotalSeconds": 60,
            "maxRedirects": 3, "maxRequests": 40, "maxResponseBytes": 200_000, "maxTotalBytes": 3_000_000, "minIntervalSeconds": 0,
            "allowedMediaTypes": ["text/html", "application/pdf"], "syntheticLoopback": True}))

    def source_entry(self, source_id: str, grant_id: str, revision: str) -> dict:
        entry = super().source_entry(source_id, grant_id, revision)
        entry["adapter"], entry["allowedHosts"] = "collected-http", ["127.0.0.1"]
        entry["scopes"][0]["timestampLimitations"] = ["one-off explicit URL list; no discovery or time-window coverage"]
        return entry

    def collect(self, request: dict) -> dict:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", **self.ownership_env(), **PROXY_ENV}
        done = subprocess.run([str(self.collect_cli), "run", "--sources", str(self.registry_path), "--policy", str(self.policy_path)],
                              input=json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=180)
        check(done.returncode == 0, f"zoop-ai-collect exited {done.returncode}: {done.stdout.decode()[:400]}")
        return json.loads(done.stdout)

    def tree(self, root: Path) -> dict:
        """(size, mtime, hash) of every file below `root`: the proof that the import only reads the collection and the ledger."""
        return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns, sha(p.read_bytes()))
                for p in sorted(root.rglob("*")) if p.is_file()}


PROXY_SCRIPT = """#!{python}
import json, os, subprocess, sys
done = subprocess.run([{real!r}, *sys.argv[1:]], input=sys.stdin.buffer.read(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=os.environ)
out = done.stdout
try:
    mode = json.load(open({mode!r}))
except FileNotFoundError:
    mode = None
if mode and done.returncode == 0 and sys.argv[1] == "export":
    value = json.loads(out)
    for path, new in mode.get("set", []):
        node = value
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = new
    for path in mode.get("delete", []):
        node = value
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
    out = json.dumps(value, ensure_ascii=False).encode("utf-8")
sys.stdout.buffer.write(out)
sys.exit(done.returncode)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--ingest-cli", required=True, type=Path)
    parser.add_argument("--collect-cli", required=True, type=Path)
    parser.add_argument("--java", default=None, help="java binary (default: $JAVA_HOME/bin/java, then PATH)")
    parser.add_argument("--psql-container", default=None, help="database container to `docker exec psql` in")
    parser.add_argument("--psql", default=shutil.which("psql"), help="host psql (used without --psql-container)")
    parser.add_argument("--db-user", default=None)
    parser.add_argument("--db-name", default=None)
    args = parser.parse_args()

    for name in ("DB_URL", "DB_USERNAME", "DB_PASSWORD"):
        check(os.environ.get(name), f"{name} must be set (a dedicated loopback database)")
    java = args.java or (str(Path(os.environ["JAVA_HOME"]) / "bin" / "java") if os.environ.get("JAVA_HOME") else shutil.which("java"))
    check(java, "no java: set JAVA_HOME or pass --java")
    check(args.jar.is_file(), "--jar does not exist (build it with ./api/gradlew -p api assemble)")
    ingest_cli, collect_cli = args.ingest_cli.absolute(), args.collect_cli.absolute()
    for cli in (ingest_cli, collect_cli):
        check(cli.is_file() and os.access(cli, os.X_OK), f"{cli.name} is not an executable file")
    check(ingest_cli.parent == collect_cli.parent, "the collector and the ingestion CLI must come from the same environment")
    db = base.Database(os.environ["DB_URL"], args.db_user or os.environ["DB_USERNAME"], os.environ["DB_PASSWORD"], args.db_name,
                       args.psql_container, args.psql)
    if db.tables_exist():
        check(db.scalar("SELECT (SELECT count(*) FROM articles) + (SELECT count(*) FROM article_versions) + (SELECT count(*) FROM artifacts) = 0"),
              "the database already holds document rows: use a dedicated empty database")

    label = step("environment: the CLIs' interpreter cannot import the original PoC")
    interpreter = ingest_cli.parent / "python"
    check(interpreter.exists(), f"{label}: no interpreter next to the CLIs")
    absent = subprocess.run([str(interpreter), "-c", "import importlib.util as u, sys; sys.exit(0 if u.find_spec('investmate') is None else 1)"])
    check(absent.returncode == 0, f"{label}: `investmate` is importable: this is not the PoC-free pipeline environment")

    world = CollectedWorld(ingest_cli, collect_cli)
    jar = base.Jar(java, args.jar.resolve(), db, world)
    site = Site({"/robots.txt": (ROBOTS, "text/plain"), **{route: (page(text), CONTENT_TYPE) for _, route, text, *_ in DOCUMENTS}})
    try:
        # ---- collect: the real collector over a real socket ---------------------------------------------------------
        label = step("zoop-ai-collect: robots first, then each URL once; declared metadata only")
        targets = [{"candidateId": f"cand-{key}", "url": site.url(route), "title": text, "documentKind": kind, "supplierDocumentId": f"supplier-{key}",
                    "publishedAt": published, "modifiedAt": None, "sourceRevision": None}
                   for key, route, text, kind, published, *_ in DOCUMENTS]
        collected = world.collect({"schemaVersion": COLLECTION_SCHEMA, "collectionId": COLLECTION_ID, "sourceId": SOURCE, "scopeId": "body", "targets": targets})
        check(collected["state"] == "complete" and collected["provenance"] == "collected_http" and collected["replayed"] is False, f"{label}: {collected}")
        check([entry["path"] for entry in site.log][0] == "/robots.txt" and sorted(entry["path"] for entry in site.log[1:]) == sorted(r for _, r, *_ in DOCUMENTS),
              f"{label}: request log {[e['path'] for e in site.log]}")
        check(all(entry["headers"]["user-agent"] == USER_AGENT and not {"cookie", "authorization", "referer"} & set(entry["headers"]) for entry in site.log),
              f"{label}: unexpected request headers")
        manifest = Path(collected["manifestPath"])
        check(collected["manifest"]["sha256"] == sha(manifest.read_bytes()), f"{label}: manifest hash")
        outcomes = {entry["candidateId"]: entry for entry in collected["targets"]}
        for key, route, text, *_ in DOCUMENTS:
            check(outcomes[f"cand-{key}"]["bodySha256"] == sha(page(text)) and outcomes[f"cand-{key}"]["code"] is None, f"{label}: {key} body hash")

        # ---- ingest: the real ledger -----------------------------------------------------------------------------------
        label = step("zoop-ai-ingest run --fixture-manifest: four text-ready versions")
        request = {"schemaVersion": base.SCHEMA, "roundId": "collected-r1", "sourceId": SOURCE, "scopeId": "body", "window": None,
                   "checkpointRevision": 0, "fixtureManifestHash": collected["manifest"]["sha256"], "cleanerVersion": "exact-copy-1"}
        ran = world.cli("run", request, manifest=manifest)
        check(ran["state"] == "complete" and ran["provenance"] == "collected_http" and ran["counts"]["textReady"] == 4 == len(ran["documentRefs"]), f"{label}: {ran}")
        refs_by_url, exports = {}, {}
        for ref in ran["documentRefs"]:
            full = {"roundId": "collected-r1", "sourceId": SOURCE, **{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
            export = world.export(full)
            refs_by_url[export["observation"]["url"]] = full
            exports[export["observation"]["url"]] = export
        refs, exp, facts = {}, {}, {}
        for key, route, text, kind, published, row, declared in DOCUMENTS:
            url = site.url(route)
            check(url in refs_by_url, f"{label}: {key} missing from the ledger")
            refs[key], exp[key] = refs_by_url[url], exports[url]
            facts[key] = {"text": expected_text(text), "title": text, "kind": kind, "published": published, "row": row, "declared": declared,
                          "version": refs[key]["documentVersion"], "url": url}

        label = step("export: acquisition facts match the served bytes, the receipt file and the collection time window")
        window = (iso_us(collected["startedAt"]), iso_us(collected["completedAt"]))
        for key, route, text, kind, published, row, declared in DOCUMENTS:
            export, observation = exp[key], exp[key]["observation"]
            collection = observation["collection"]
            receipt_file = world.inputs / collection["receipt"]["file"]
            receipt = json.loads(receipt_file.read_bytes())
            check(sha(receipt_file.read_bytes()) == collection["receipt"]["sha256"] == outcomes[f"cand-{key}"]["receiptSha256"], f"{label}: {key} receipt hash")
            check(observation["provenance"] == "collected_http" and collection["bodySha256"] == sha(page(text)) == export["locatorMetadata"]["rawHash"]
                  and receipt["bodySha256"] == collection["bodySha256"] and receipt["fetchedAt"] == collection["fetchedAt"], f"{label}: {key} body/receipt binding")
            check(collection["network"] == "synthetic_loopback" and collection["documentKind"] == kind and collection["httpStatus"] == 200
                  and collection["contentType"] == CONTENT_TYPE and collection["finalUrl"] == site.url(route) == observation["url"], f"{label}: {key} facts {collection}")
            check(window[0] <= iso_us(collection["fetchedAt"]) <= window[1], f"{label}: {key} fetchedAt is outside the collection window")
            check(iso_us(observation["observedAt"]) > iso_us(collection["fetchedAt"]), f"{label}: {key} the ledger receipt must be later than the fetch")
            check(collection["published"]["raw"] == published and collection["published"]["precision"] == declared and collection["published"]["basis"], f"{label}: {key} published")
            check(export["document"]["text"] == expected_text(text) and observation["title"] == text, f"{label}: {key} text/title")
            check((observation["publishedAt"] is not None) == (declared == "instant"), f"{label}: {key} ledger publishedAt must be set only for an offset instant")

        collection_tree = world.tree(world.inputs)

        # ---- the jar: refusals first, so a refusal is proven against an untouched database --------------------------------
        proxy = world.root / "ingest-proxy"
        mode = world.root / "ingest-proxy-mode.json"
        proxy.write_text(PROXY_SCRIPT.format(python=sys.executable, real=str(ingest_cli), mode=str(mode)))
        os.chmod(proxy, 0o700)
        artifact_root = world.artifacts

        def stored() -> list[str]:
            return sorted(str(p.relative_to(artifact_root)) for p in artifact_root.rglob("*") if p.is_file() and p.name != ".document-import.lock")

        def counts_zero() -> bool:
            return db.scalar("SELECT (SELECT count(*) FROM articles) + (SELECT count(*) FROM article_versions) + (SELECT count(*) FROM artifacts) = 0")

        def refuse(name: str, key: str, kind: str | None, code: str, tamper: dict | None = None):
            """One import that must fail with `code` while leaving no row and no file."""
            if tamper:
                mode.write_text(json.dumps(tamper))
                world.ingest_cli = proxy
            try:
                status, result, _ = jar.run(name, [item(refs[key], kind or facts[key]["kind"], None)])
            finally:
                world.ingest_cli = ingest_cli
                mode.unlink(missing_ok=True)
            check(status != 0 and result is not None and result["status"] == "failed" and result["items"][0]["status"] == "failed"
                  and result["items"][0]["failure"]["code"] == code, f"{name}: expected {code}, got {json.dumps(result)[:400]}")
            check(counts_zero() and stored() == [], f"{name}: a refused import left a row or a file")

        label = step("refusals leave no row and no file: request kind that differs from the declared kind")
        refuse("kind-news-as-disclosure", "day", "disclosure", "article_kind_conflict")
        refuse("kind-disclosure-as-news", "instant", "news", "article_kind_conflict")
        before = db.snapshot()

        label = step("refusals leave no row and no file: real CLI output with mismatched or forged collection metadata")
        collection_path = ["observation", "collection"]
        cases = [
            ("body-hash", "day", ("set", [collection_path + ["bodySha256"], "0" * 64]), "export_invalid"),
            ("receipt-hash", "day", ("set", [collection_path + ["receipt", "sha256"], "not-a-hash"]), "export_invalid"),
            ("day-date", "day", ("set", [collection_path + ["published", "date"], "2026-10-15"]), "export_invalid"),
            ("day-as-instant", "day", ("set", [collection_path + ["published", "precision"], "instant"]), "export_invalid"),
            ("unresolved-as-instant", "unresolved", ("set", [collection_path + ["published", "precision"], "instant"]), "export_invalid"),
            ("unresolved-with-instant", "unresolved", ("set", [["observation", "publishedAt"], "2026-10-14T09:00:00+09:00"]), "export_invalid"),
            ("instant-raw", "instant", ("set", [collection_path + ["published", "raw"], "2026-10-14T10:00:00+09:00"]), "export_invalid"),
            ("instant-published-at", "instant", ("set", [["observation", "publishedAt"], "2026-10-14T10:00:00+09:00"]), "export_invalid"),
            ("unknown-with-raw", "undeclared", ("set", [collection_path + ["published", "raw"], "2026-10-14"]), "export_invalid"),
            ("network", "day", ("set", [collection_path + ["network"], "internet"]), "export_invalid"),
            ("http-status", "day", ("set", [collection_path + ["httpStatus"], 500]), "export_invalid"),
            ("document-kind", "day", ("set", [collection_path + ["documentKind"], "blog"]), "export_invalid"),
            ("collection-dropped", "day", ("delete", collection_path), "export_invalid"),
            ("collection-extra-key", "day", ("set", [collection_path + ["trusted"], True]), "export_invalid"),
            ("declared-kind-differs", "instant", ("set", [collection_path + ["documentKind"], "news"]), "article_kind_conflict"),
        ]
        for name, key, (operation, spec), code in cases:
            refuse("tamper-" + name, key, None, code, {"set": [spec]} if operation == "set" else {"delete": [spec]})
        check(db.snapshot() == before and counts_zero() and stored() == [], f"{label}: the database or the files changed")

        # ---- the import itself ------------------------------------------------------------------------------------------
        label = step("import: day-only, offset instant, offset-less and undeclared publication with exact rows, files and result facts")
        requested = [item(refs[key], facts[key]["kind"], None) for key, *_ in DOCUMENTS]
        status, result, _ = jar.run("collected", requested)
        check(status == 0 and result["status"] == "succeeded", f"{label}: exit {status} {json.dumps(result)[:600]}")
        by_document = {}
        for index, (key, *_rest) in enumerate(DOCUMENTS):
            outcome, export, fact = result["items"][index], exp[key], facts[key]
            collection = export["observation"]["collection"]
            check(outcome["status"] == "imported" and (outcome["article"], outcome["artifact"], outcome["artifactFile"], outcome["version"]) == ("created",) * 4,
                  f"{label}: {key} not created: {outcome}")
            check(outcome["currentVersion"] == {"result": "moved", "value": fact["version"]} and outcome["documentId"] == refs[key]["documentId"]
                  and outcome["documentVersion"] == fact["version"] and outcome["textArtifactId"] == "text-" + fact["version"], f"{label}: {key} identity")
            check(iso_us(outcome["collectedAt"]) == iso_us(collection["fetchedAt"]) != iso_us(export["observation"]["observedAt"]),
                  f"{label}: {key} collectedAt must be the HTTP fetch time, not the ledger receipt time")
            check(outcome["grant"] == export["grant"], f"{label}: {key} grant echo")
            expected_precision = fact["row"][0]
            check(outcome["publicationPrecision"] == expected_precision, f"{label}: {key} publicationPrecision {outcome['publicationPrecision']}")
            reported = outcome["collection"]
            check(reported["provenance"] == "collected_http" and reported["collectionId"] == COLLECTION_ID and reported["receiptSha256"] == collection["receipt"]["sha256"]
                  and reported["bodySha256"] == sha(page(DOCUMENTS[index][2])) and iso_us(reported["fetchedAt"]) == iso_us(collection["fetchedAt"])
                  and reported["finalUrl"] == fact["url"] and reported["httpStatus"] == 200 and reported["contentType"] == CONTENT_TYPE
                  and reported["network"] == "synthetic_loopback" and reported["documentKind"] == fact["kind"], f"{label}: {key} collection echo {reported}")
            check(reported["declaredPublication"] == {"precision": fact["declared"], "raw": fact["published"], "basis": collection["published"]["basis"]}
                  and reported["declaredPublication"]["basis"], f"{label}: {key} declared publication {reported['declaredPublication']}")
            by_document[key] = outcome

        articles = {row["id"]: row for row in db.articles()}
        versions = {(row["article_id"], row["version"]): row for row in db.versions()}
        artifacts = {row["id"]: row for row in db.artifacts()}
        check(set(articles) == {refs[k]["documentId"] for k in refs} and len(versions) == 4 and len(artifacts) == 4, f"{label}: row counts {len(articles)}/{len(versions)}/{len(artifacts)}")
        for key, *_rest in DOCUMENTS:
            fact, ref, export = facts[key], refs[key], exp[key]
            article = articles[ref["documentId"]]
            check((article["kind"], article["provider"], article["provider_key"], article["lineage_key"], article["current_version"], article["access_status"])
                  == (fact["kind"], SOURCE, None, None, fact["version"], "available"), f"{label}: article {key} {article}")
            row = versions[(ref["documentId"], fact["version"])]
            precision, published_at, published_date = fact["row"]
            check((row["publication_precision"], row["published_at"], row["published_date"]) == (precision, published_at, published_date),
                  f"{label}: {key} publication columns {row}")
            check(row["collected_at"] == iso_us(export["observation"]["collection"]["fetchedAt"]), f"{label}: {key} collected_at {row['collected_at']}")
            check((row["title"], row["publisher"], row["url"], row["raw_artifact_id"], row["text_artifact_id"])
                  == (fact["title"], None, fact["url"], None, "text-" + fact["version"]), f"{label}: version {key} {row}")
            body = fact["text"].encode("utf-8")
            artifact = artifacts["text-" + fact["version"]]
            check((artifact["kind"], artifact["storage_uri"], artifact["sha256"], artifact["bytes"], artifact["media_type"])
                  == ("extracted_text", f"artifact-root:extracted_text/text-{fact['version']}.txt", sha(body), len(body), "text/plain; charset=utf-8"),
                  f"{label}: artifact {key} {artifact}")
            check(world.text_file(fact["version"]).read_bytes() == body, f"{label}: file bytes of {key}")
        check(stored() == sorted(f"extracted_text/text-{facts[k]['version']}.txt" for k in facts), f"{label}: unexpected files {stored()}")
        check(by_document["day"]["collection"]["declaredPublication"]["raw"] == "2026-10-14" and versions[(refs["day"]["documentId"], facts["day"]["version"])]["published_at"] is None,
              f"{label}: a day was widened to an instant")
        check(by_document["unresolved"]["collection"]["declaredPublication"]["raw"] == "2026-10-14T09:00:00"
              and versions[(refs["unresolved"]["documentId"], facts["unresolved"]["version"])]["published_at"] is None, f"{label}: an offset-less time became an instant")
        check(by_document["undeclared"]["collection"]["declaredPublication"]["raw"] is None, f"{label}: an undeclared time gained a raw value")

        # ---- idempotence and refusals against existing rows --------------------------------------------------------------
        label = step("the same import again is a no-op: nothing is rewritten")
        after = db.snapshot()
        files = {name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for name in stored() for p in [artifact_root / name]}
        status, again, _ = jar.run("collected-again", requested)
        check(status == 0 and again["status"] == "succeeded", f"{label}: {json.dumps(again)[:400]}")
        for index, (key, *_rest) in enumerate(DOCUMENTS):
            outcome = again["items"][index]
            check((outcome["article"], outcome["artifact"], outcome["artifactFile"], outcome["version"]) == ("existing",) * 4
                  and outcome["currentVersion"] == {"result": "already-current", "value": facts[key]["version"]}
                  and outcome["collection"] == by_document[key]["collection"] and outcome["collectedAt"] == by_document[key]["collectedAt"], f"{label}: {key} {outcome}")
        check(db.snapshot() == after, f"{label}: the database changed")
        check({name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for name in stored() for p in [artifact_root / name]} == files, f"{label}: a file was rewritten")

        label = step("a wrong request kind or collection metadata against registered rows changes nothing")
        refuse_after = after
        for name, key, kind in (("kind-registered-day", "day", "disclosure"), ("kind-registered-instant", "instant", "news")):
            status, result, _ = jar.run(name, [item(refs[key], kind, None)])
            check(status != 0 and result["items"][0]["failure"]["code"] == "article_kind_conflict", f"{name}: {json.dumps(result)[:300]}")
            check(db.snapshot() == refuse_after, f"{name}: the database changed")
        mode.write_text(json.dumps({"set": [[collection_path + ["published", "date"], "2026-10-15"]]}))
        world.ingest_cli = proxy
        try:
            status, result, _ = jar.run("tamper-registered-day", [item(refs["day"], "news", None)])
        finally:
            world.ingest_cli = ingest_cli
            mode.unlink(missing_ok=True)
        check(status != 0 and result["items"][0]["failure"]["code"] == "export_invalid" and db.snapshot() == refuse_after, f"{label}: tampered day on a registered row")
        check({name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes()) for name in stored() for p in [artifact_root / name]} == files, f"{label}: a file changed")

        # ---- final -----------------------------------------------------------------------------------------------------------
        label = step("final state: collection files and ledger untouched, rows exact, nothing leaked")
        check(world.tree(world.inputs) == collection_tree, f"{label}: the import changed the collection directory")
        check(len(db.articles()) == 4 and len(db.versions()) == 4 and len(db.artifacts()) == 4, f"{label}: final counts")
        joined = "\n".join(base.OUTPUT)
        check(len(db.password) < 8 or db.password not in joined, f"{label}: the database password appears in process output")
        check(str(world.root) not in joined, f"{label}: an artifact, collection or ledger path was logged")
        for fact in facts.values():
            check(fact["text"] not in joined, f"{label}: document text was logged")
        print(json.dumps({"status": "passed", "steps": len(base.STEPS), "providerCalls": 0, "modelCalls": 0, "externalNetwork": "none: loopback server only",
                          "documents": 4, "refusals": 2 + len(cases) + 3, "importRuns": jar.counter, "publicEnvironment": True}))
        return 0
    finally:
        site.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as failure:
        print("document import collected smoke FAILED: " + str(failure).replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        for output in base.OUTPUT[-1:]:
            print("--- last process output (tail) ---\n" + output[-2500:].replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        sys.exit(1)
