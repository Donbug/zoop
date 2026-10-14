#!/usr/bin/env python3
"""Operator smoke for the document analysis: installed S2-1 CLI + real ai/service (replay) + built Spring jar + real PostgreSQL.

Everything is synthetic and local; no provider, no model, no network beyond loopback. The script
  1. builds a fresh S2-1 ledger with the INSTALLED `zoop-ai-ingest` (six authored documents) and registers them with the document
     import of the built jar,
  2. seeds two synthetic catalog companies in the real `companies` table,
  3. authors an exact replay recording (the worker's own `request_identity` and `stage_config`, in the order the calls will be
     made) and starts a REAL `ai/service` process with the matching flat grant registry,
  4. drives the built jar as a non-web operator process through `prepare` and `advance` runs (a loopback proxy sits between the
     jar and the service, only to lose a submit reply and to rewrite two results: one with another input, one with edited main
     claims that are re-hashed so that only the verifier's old verdicts disagree),
  5. reads every result back with psql (and the worker's own SQLite ledger) and compares ids, hashes, offsets and counts with
     values computed here, independently of the Java code. Authority is exercised at its edges: an app grant copy revoked between
     prepare and advance (the service still allows it) must not cause a submit, a grant revoked or expired while the settlement
     waits for a REAL PostgreSQL row lock must not become `available`, and a file conflict after other files were stored must
     remove exactly the files that attempt created.

Run it with the ai/service interpreter (zoop_ai and the service test harness are importable), against an EMPTY dedicated
loopback PostgreSQL database that the jar will migrate:

  DB_URL=jdbc:postgresql://127.0.0.1:<port>/<db> DB_USERNAME=<user> DB_PASSWORD=<dummy> \
    ai/service/.venv/bin/python api/scripts/document_analysis_smoke.py \
      --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --ingest-cli "$PWD/ai/pipeline/.venv/bin/zoop-ai-ingest" \
      --psql-container <container> --db-user <user> --db-name <db>

The artifact root, the ledger, the AI service state and every request and result file live in a fresh temporary directory that is
removed at exit; the service and the proxy are stopped. The database is NOT cleaned: use a throwaway one. On success the last
stdout line is {"status": "passed", "steps": N, "providerCalls": 0, "modelCalls": 0, ...}; any failed expectation exits non-zero.
"""
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "ai" / "service" / "tests"))

import document_import_smoke as imp  # noqa: E402
from support import ServiceProcess, Workspace  # noqa: E402
from zoop_ai.provider import request_identity, stage_config  # noqa: E402

ANALYSIS_SCHEMA = "zoop-document-analysis-1"
AI_SCHEMA = "zoop-ai-s1-1"
ANALYSIS_MIGRATION = "20261014130000"
GRANT_ID = "grant-smoke"
GRANT_REVISION = "rev-1"
LIMITATION = "합성 문서에 적힌 내용만 다룹니다."
COMPANIES = {"SYNTH-A": "합성 알파", "SYNTH-B": "합성 베타"}
SECOND_QUOTE = "둘째 문단은 합성 베타의 비용 증가를 다룹니다."
check = imp.check
step = imp.step
sha = imp.sha


def body(n: int) -> str:
    return (f'<html><body><article><p>삼성전자 &amp; "인용" \\ 경로 \U0001F600 문서{n} 첫째 문장입니다.</p>'
            f'<p>{SECOND_QUOTE}</p></article></body></html>')


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def flat_grants(*, enabled: bool = True, operations: list[str] | None = None, expires_at: str | None = None) -> dict:
    return {"schemaVersion": AI_SCHEMA, "grants": [{
        "grantId": GRANT_ID, "revision": GRANT_REVISION, "sourceId": imp.SOURCE, "enabled": enabled, "rights": "known",
        "allowedOperations": operations or ["read", "store", "model-send", "quote-display"], "recipients": ["authored-replay"],
        "purposes": ["document-summary", "document-sentiment", "semantic-verification"],
        "evidence": ["authored synthetic smoke"], "expiresAt": expires_at}]}


# --------------------------------------------------------------------------------------------------------------------
# authored answers: computed from the exported text with Python code point offsets, independent of the Java code
# --------------------------------------------------------------------------------------------------------------------
def citation(document: dict, evidence_id: str, quote: str) -> dict:
    text = document["text"]
    start = text.index(quote)  # str.index counts code points, exactly the unit of the contract
    end = start + len(quote)
    locator = next(item["locatorId"] for item in document["rawLocators"] if item["start"] <= start and end <= item["end"])
    return {"evidenceId": evidence_id, "documentId": document["documentId"], "documentVersion": document["documentVersion"],
            "textArtifactId": document["textArtifactId"], "offsetUnit": "unicode_code_point", "start": start, "end": end,
            "quote": quote, "inputKind": "body", "rawLocatorIds": [locator]}


def answer(document: dict, kind: str, n: int) -> dict:
    first = f"문서{n} 첫째 문장입니다."
    assertion = "fact" if kind == "document-summary" else "interpretation"
    claims = [{"claimId": "claim-a", "text": first, "assertionKind": assertion, "evidenceIds": ["e1"]},
              {"claimId": "claim-b", "text": SECOND_QUOTE, "assertionKind": assertion, "evidenceIds": ["e2"]},
              {"claimId": "claim-limit", "text": LIMITATION, "assertionKind": "limitation", "evidenceIds": []}]
    base = {"claims": claims, "citations": [citation(document, "e1", first), citation(document, "e2", SECOND_QUOTE)],
            "limitations": [LIMITATION]}
    rendered = first + "\n" + SECOND_QUOTE
    return {"text": rendered, **base} if kind == "document-summary" else {"label": "mixed", "rationale": rendered, **base}


def verdict(candidate: dict, decision: str) -> dict:
    return {"claims": [{"claimId": c["claimId"], "decision": decision if index == 0 else "supported", "reason": "합성 판정 표본"}
                       for index, c in enumerate(candidate["claims"])],
            "prohibitedAdvice": False, "unsupportedCausality": False}


def worker_payload(document: dict, company: dict, candidate: dict | None = None) -> dict:
    data = {"schemaVersion": AI_SCHEMA, "document": document, "company": company,
            "grantRef": {"grantId": GRANT_ID, "revision": GRANT_REVISION}}
    if candidate is not None:
        data["candidate"] = candidate
    return data


def tamper_company(document: dict) -> None:
    """A result computed for another input: the company name the service echoes back differs from the stored submit."""
    document["job"]["input"]["input"]["company"]["name"] += "!"


def rewrite_main_claims(document: dict) -> None:
    """The generation artifact's second claim is edited, the text is re-rendered and the result version is recomputed as the
    worker defines it, so every digest is consistent; only the verifier's verdicts and claims still describe the old claim."""
    main = next(item for item in document["job"]["artifacts"] if item["kind"] == "document-summary")
    changed = "합성 알파의 이익이 급증했다."
    first = main["result"]["claims"][0]["text"]
    main["claims"][1]["text"] = changed
    main["result"]["claims"][1]["text"] = changed
    main["result"]["text"] = first + "\n" + changed
    main["resultVersion"] = "result-" + sha(canonical({"inputDigest": main["inputDigest"], "kind": main["kind"],
                                                         "result": main["result"]}).encode("utf-8"))


# --------------------------------------------------------------------------------------------------------------------
# a loopback proxy between the jar and the service: it only loses one submit reply or tampers one result on demand
# --------------------------------------------------------------------------------------------------------------------
class Proxy:
    def __init__(self, upstream_port: int):
        self.upstream = f"http://127.0.0.1:{upstream_port}"
        self.requests: list[tuple[str, str]] = []
        self.drop_next_submit_reply = False
        self.tamper_result = None  # a function that edits the decoded result envelope in place
        self.tampered = 0
        outer = self
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # noqa: D401 - silence the default access log
                pass

            def forward(self):
                length = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(length) if length else None
                request = urllib.request.Request(outer.upstream + self.path, data=data, method=self.command)
                for name in ("Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID", "Accept"):
                    if self.headers.get(name):
                        request.add_header(name, self.headers[name])
                try:
                    with opener.open(request, timeout=60) as response:
                        status, headers, payload = response.status, response.headers, response.read()
                except urllib.error.HTTPError as error:
                    status, headers, payload = error.code, error.headers, error.read()
                outer.requests.append((self.command, self.path))
                if self.command == "POST" and self.path.endswith("/analysis-jobs") and outer.drop_next_submit_reply:
                    outer.drop_next_submit_reply = False
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)  # the service answered; the app never sees it
                    return
                if self.command == "GET" and self.path.endswith("/result") and outer.tamper_result and status == 200:
                    document = json.loads(payload)
                    outer.tamper_result(document)
                    outer.tampered += 1
                    payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                for name in ("Content-Type", "X-Request-ID", "Retry-After"):
                    if headers.get(name):
                        self.send_header(name, headers[name])
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = forward
            do_POST = forward

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def count(self, method: str, suffix: str) -> int:
        return sum(1 for m, path in self.requests if m == method and path.endswith(suffix))

    def close(self):
        self.server.shutdown()
        self.server.server_close()


# --------------------------------------------------------------------------------------------------------------------
# the jar as an analysis operator process
# --------------------------------------------------------------------------------------------------------------------
class Analysis:
    def __init__(self, jar, world, db, proxy: Proxy, token: str, grants_file: Path):
        self.jar, self.world, self.db, self.proxy, self.token, self.grants_file = jar, world, db, proxy, token, grants_file

    def env(self, request: Path, result: Path, base_url: str | None = None) -> dict[str, str]:
        return {**self.jar.base_env(), "ZOOP_DOCUMENT_ANALYSIS_ENABLED": "true", "ZOOP_DOCUMENT_ANALYSIS_REQUEST": str(request),
                "ZOOP_DOCUMENT_ANALYSIS_RESULT": str(result), "ZOOP_DOCUMENT_ANALYSIS_GRANTS": str(self.grants_file),
                "ZOOP_INGESTION_CLI": str(self.world.ingest_cli), "ZOOP_INGESTION_STATE_DIR": str(self.world.state),
                "ZOOP_INGESTION_SOURCES": str(self.world.registry_path), "ZOOP_ARTIFACT_ROOT": str(self.world.artifacts),
                **self.world.ownership_env(), "ZOOP_AI_CLIENT_ENABLED": "true", "ZOOP_AI_CLIENT_TOKEN": self.token,
                "ZOOP_AI_CLIENT_BASE_URL": base_url or f"http://127.0.0.1:{self.proxy.port}"}

    def files(self, label: str, command: str, items) -> tuple[Path, Path]:
        self.jar.counter += 1
        stem = f"a{self.jar.counter:02d}-{label}"
        request = self.world.requests / f"{stem}-request.json"
        result = self.world.requests / f"{stem}-result.json"
        if isinstance(items, bytes):
            request.write_bytes(items)
        else:
            request.write_bytes(json.dumps({"schemaVersion": ANALYSIS_SCHEMA, "command": command, "items": items},
                                           ensure_ascii=False).encode("utf-8"))
        return request, result

    def read(self, label: str, result: Path) -> dict | None:
        if not result.exists():
            return None
        check(stat.S_IMODE(result.stat().st_mode) & 0o077 == 0, f"{label}: result file is not owner-only")
        text = result.read_text("utf-8")
        check(text, f"{label}: the result file was reserved but left empty")
        check(str(self.world.root) not in text, f"{label}: the result file leaks a path")
        for document_text in TEXTS:
            check(document_text not in text, f"{label}: the result file carries document text")
        return json.loads(text)

    def run(self, label: str, command: str, items, *, base_url: str | None = None) -> tuple[int, dict | None, Path]:
        request, result = self.files(label, command, items)
        done = subprocess.run(self.jar.argv("--spring.main.web-application-type=none"), env=self.env(request, result, base_url),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        imp.OUTPUT.append(done.stdout.decode("utf-8", "replace"))
        return done.returncode, self.read(label, result), result

    def start(self, label: str, command: str, items) -> tuple[subprocess.Popen, Path]:
        request, result = self.files(label, command, items)
        process = subprocess.Popen(self.jar.argv("--spring.main.web-application-type=none"), env=self.env(request, result),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return process, result

    def prepare(self, label: str, items, *, expect_ok: bool = True) -> dict:
        code, result, _ = self.run(label, "prepare", items)
        if expect_ok:
            check(code == 0 and result["status"] == "succeeded", f"{label}: prepare failed: {json.dumps(result)[:500]}")
        return result

    def settle(self, label: str, analysis_id: str, *, tries: int = 15, recover: bool = False) -> dict:
        """Advance one analysis until it is terminal (pending is a success and is simply advanced again)."""
        for attempt in range(tries):
            code, result, _ = self.run(f"{label}-{attempt}", "advance", [{"analysisId": analysis_id, "recover": recover}])
            item = result["items"][0]
            if item["status"] in ("settled", "already_settled"):
                check(code == 0, f"{label}: a terminal analysis must exit 0")
                return item
            check(code == 0 and item["status"] == "pending", f"{label}: advance failed: {json.dumps(result)[:500]}")
            time.sleep(1)
        raise AssertionError(f"{label}: {analysis_id} did not settle in {tries} advances")

    def advance_failure(self, label: str, analysis_id: str, code_name: str, **kwargs) -> dict:
        code, result, _ = self.run(label, "advance", [{"analysisId": analysis_id}], **kwargs)
        item = result["items"][0]
        check(code != 0 and item["status"] == "failed" and item["failure"]["code"] == code_name,
              f"{label}: expected {code_name}, got {json.dumps(result)[:500]}")
        return item["failure"]


def hold(db, sql: str, marker: str) -> subprocess.Popen:
    """A psql session that takes the row lock `sql` takes and keeps it (a long sleep) until released."""
    argv, env = db.command(f"{sql}; SELECT pg_sleep(600) /*{marker}*/")
    return subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def release(db, lock: subprocess.Popen, marker: str) -> None:
    db.run("SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
           f"WHERE query LIKE '%{marker}%' AND pid <> pg_backend_pid()")
    lock.terminate()
    lock.wait(timeout=30)


def pitem(ref: dict, kind: str, company: str, *, mode: str = "replay", source_kind: str = "synthetic", expected=None) -> dict:
    observation = {k: ref[k] for k in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")}
    return {"observation": observation, "kind": kind, "companyId": company, "grant": {"grantId": GRANT_ID, "revision": GRANT_REVISION},
            "mode": mode, "sourceKind": source_kind, "latest": {"expected": expected}}


TEXTS: list[str] = []
CONTENT_DIRECTORIES = ("analysis_result", "semantic_receipt", "exact_receipt")  # the artifact kind is the directory name
CONTENT_KINDS = CONTENT_DIRECTORIES
PLANTED = b'{"planted":true}'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--ingest-cli", required=True, type=Path)
    parser.add_argument("--java", default=None)
    parser.add_argument("--psql-container", default=None)
    parser.add_argument("--psql", default=shutil.which("psql"))
    parser.add_argument("--db-user", default=None)
    parser.add_argument("--db-name", default=None)
    args = parser.parse_args()

    for name in ("DB_URL", "DB_USERNAME", "DB_PASSWORD"):
        check(os.environ.get(name), f"{name} must be set (a dedicated loopback database)")
    java = args.java or (str(Path(os.environ["JAVA_HOME"]) / "bin" / "java") if os.environ.get("JAVA_HOME") else shutil.which("java"))
    check(java, "no java: set JAVA_HOME or pass --java")
    check(args.jar.is_file(), "--jar does not exist (build it with ./api/gradlew -p api assemble)")
    ingest_cli = args.ingest_cli.resolve()
    check(ingest_cli.is_file() and os.access(ingest_cli, os.X_OK), "--ingest-cli is not an executable file")
    db = imp.Database(os.environ["DB_URL"], args.db_user or os.environ["DB_USERNAME"], os.environ["DB_PASSWORD"], args.db_name,
                      args.psql_container, args.psql)
    if db.tables_exist():
        check(db.scalar("SELECT (SELECT count(*) FROM articles) + (SELECT count(*) FROM artifacts) = 0"),
              "the database already holds document rows: use a dedicated empty database")
    world = imp.World(ingest_cli)
    jar = imp.Jar(java, args.jar.resolve(), db, world)
    scratch = Path(tempfile.mkdtemp(prefix="zoop-docanalysis-")).resolve()
    imp.atexit.register(shutil.rmtree, scratch, True)

    # ---- the ledger and the registered documents ---------------------------------------------------------------------
    refs = {n: world.round(f"a{n}", imp.SOURCE, f"a{n}", n - 1,
                           [imp.ledger_item(f"c-{n}", f"supplier-a{n}", f"https://example.invalid/a{n}", "2026-10-08T09:00:00+09:00")],
                           body(n))[0] for n in range(1, 7)}
    exports = {n: world.export(ref) for n, ref in refs.items()}
    documents = {n: export["document"] for n, export in exports.items()}
    TEXTS.extend(document["text"] for document in documents.values())
    label = step("ledger from the installed CLI: six synthetic documents with emoji text (UTF-16 and code point offsets differ)")
    for n, document in documents.items():
        check(len(document["text"].encode("utf-16-le")) // 2 > len(document["text"]), f"{label}: document {n} has no non-BMP character")
    ledger = world.ledger_fingerprint()

    label = step("document import registers the six documents; the analysis migration is applied by the same jar start")
    code, result, _ = jar.run("import", [imp.item(ref, expected=None) for ref in refs.values()])
    check(code == 0 and result["status"] == "succeeded", f"{label}: {json.dumps(result)[:400]}")
    applied = db.rows("SELECT version, success FROM flyway_schema_history WHERE version IS NOT NULL ORDER BY installed_rank")
    check(all(row["success"] for row in applied) and applied[-1]["version"] == ANALYSIS_MIGRATION,
          f"{label}: the analysis migration is not the last applied version: {applied}")
    db.run("INSERT INTO companies (id, ticker, exchange_code, name, market) VALUES "
           + ", ".join(f"('{key}', '90000{index}', 'KRX', '{name}', 'KOSPI')" for index, (key, name) in enumerate(COMPANIES.items(), 1)))
    company = {key: {"companyId": key, "name": name} for key, name in COMPANIES.items()}

    # ---- the replay recording, in the order the calls will be made ------------------------------------------------------
    entries: list[dict] = []
    answers: dict[str, dict] = {}

    def author(job: str, n: int, kind: str, owner: str, *, decision: str = "supported", bad_limitation: bool = False):
        generated = answer(documents[n], kind, n)
        if bad_limitation:
            generated["limitations"] = []  # the limitation claim is still there: the worker's exact check must refuse it
        answers[job] = generated
        entries.append({"stage": kind, "inputDigest": request_identity(kind, worker_payload(documents[n], company[owner]),
                                                                       stage_config(kind, "replay")), "response": generated})
        if not bad_limitation:
            entries.append({"stage": "semantic-verification", "inputDigest": request_identity(
                "semantic-verification", worker_payload(documents[n], company[owner], generated),
                stage_config("semantic-verification", "replay")), "response": verdict(generated, decision)})

    author("J1", 1, "document-summary", "SYNTH-A")
    author("J2", 1, "document-sentiment", "SYNTH-A")
    author("J3", 2, "document-summary", "SYNTH-A", decision="insufficient")
    author("J4", 3, "document-summary", "SYNTH-A")
    author("J5", 3, "document-sentiment", "SYNTH-B")
    author("J6", 4, "document-summary", "SYNTH-A")
    author("J7", 5, "document-summary", "SYNTH-A")
    author("J8", 6, "document-summary", "SYNTH-A", bad_limitation=True)
    author("J9", 2, "document-summary", "SYNTH-A")
    # The worker consumes the recording strictly in call order, so these are authored in the order their steps run below.
    author("J11", 4, "document-summary", "SYNTH-B")
    author("J12", 5, "document-sentiment", "SYNTH-A")
    author("J13", 6, "document-sentiment", "SYNTH-A")
    author("J14", 5, "document-sentiment", "SYNTH-B")
    author("J15", 4, "document-sentiment", "SYNTH-A")
    replay = {"schemaVersion": AI_SCHEMA, "recordingKind": "authored-test", "responses": entries}

    workspace = Workspace(scratch / "service", replay=replay, grants=flat_grants())
    service = ServiceProcess(workspace).start()
    proxy = Proxy(workspace.port)
    app_grants = world.root / "app-grants.json"

    def save_app_grants(document: dict):
        temporary = world.root / "next-app-grants.json"
        temporary.write_text(json.dumps(document), encoding="utf-8")
        temporary.replace(app_grants)

    def save_service_grants(document: dict):
        workspace.grants_path.write_text(json.dumps(document), encoding="utf-8")

    save_app_grants(flat_grants())
    analysis = Analysis(jar, world, db, proxy, workspace.credentials.tokens["alpha"], app_grants)
    worker_db = workspace.worker / "worker.sqlite3"

    def worker_calls() -> list[dict]:
        if not worker_db.exists():
            return []
        connection = sqlite3.connect(f"file:{worker_db}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute("SELECT attempt_id, job_id, stage, mode, state FROM calls ORDER BY started_at")]
        finally:
            connection.close()

    def worker_artifact(artifact_id: str) -> str:
        connection = sqlite3.connect(f"file:{worker_db}?mode=ro", uri=True)
        try:
            return connection.execute("SELECT payload FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()[0]
        finally:
            connection.close()

    def row(analysis_id: str) -> dict:
        return db.rows(f"SELECT * FROM document_analyses WHERE id = '{analysis_id}'")[0]

    def executions(job: str | None = None) -> list[dict]:
        where = f"WHERE ai_job_id = '{job}'" if job else ""
        return db.rows(f"SELECT * FROM ai_executions {where} ORDER BY ai_attempt_id")

    def kinds() -> dict[str, int]:
        return {r["kind"]: r["n"] for r in db.rows("SELECT kind, count(*) AS n FROM artifacts GROUP BY kind")}

    def counts() -> dict:
        return {"analyses": db.scalar("SELECT count(*) FROM document_analyses"), "artifacts": db.scalar("SELECT count(*) FROM artifacts"),
                "executions": db.scalar("SELECT count(*) FROM ai_executions"), "evidence": db.scalar("SELECT count(*) FROM evidence")}

    def files(directory: str) -> list[str]:
        folder = world.artifacts / directory
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def wait_ready(job_id: str):
        service.wait_state(job_id, {"ready", "failed"}, timeout=60)

    def blocked_backends() -> int:
        """Backends of this database that are waiting for a lock (the jar waiting for the row lock this script holds)."""
        return db.scalar("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")

    def worker_artifact_id(job_id: str, kind: str) -> str:
        connection = sqlite3.connect(f"file:{worker_db}?mode=ro", uri=True)
        try:
            return connection.execute("SELECT artifact_id FROM artifacts WHERE job_id = ? AND kind = ?", (job_id, kind)).fetchone()[0]
        finally:
            connection.close()

    def assert_no_content(label: str, item: dict, before_kinds: dict, before_evidence: int, before_content: dict) -> None:
        """A withheld analysis holds no result or content artifact, no evidence and no content file that this attempt wrote;
        its receipts and executions were kept."""
        stored = row(item["analysisId"])
        check(stored["status"] == "withheld" and stored["result"] is None and stored["result_version"] is None
              and stored["result_artifact_id"] is None and stored["exact_receipt_id"] is None
              and stored["semantic_receipt_id"] is None and stored["produced_at"] is None,
              f"{label}: a withheld analysis holds content: {stored}")
        after = kinds()
        check(after.get("ai_call_receipt", 0) == before_kinds.get("ai_call_receipt", 0) + 2
              and all(after.get(kind, 0) == before_kinds.get(kind, 0) for kind in CONTENT_KINDS)
              and counts()["evidence"] == before_evidence and len(executions(item["aiJobId"])) == 2,
              f"{label}: the receipts must be kept and no content or evidence registered: {after}")
        check({d: files(d) for d in CONTENT_DIRECTORIES} == before_content,
              f"{label}: content files of a withheld analysis were left behind: {({d: files(d) for d in CONTENT_DIRECTORIES})}")

    def settle_across_row_lock(name: str, item: dict, change, *, expires_at: float | None = None) -> dict:
        """One advance of a READY job whose settlement is blocked on the analysis row lock that this script holds in PostgreSQL.

        By then the jar has read the result, judged it against the app grant file as it was and written its content files.
        `change()` edits the app grant copy while the jar waits; with `expires_at` (epoch seconds, the grant's own expiry) the
        script also waits until the grant has expired before it releases the lock.
        """
        analysis_id = item["analysisId"]
        marker = f"zoop-smoke-wait-{name}-{os.getpid()}"
        content_files = len(files("analysis_result"))
        lock = hold(db, f"SELECT 1 FROM document_analyses WHERE id = '{analysis_id}' FOR UPDATE", marker)
        process = None
        try:
            time.sleep(2)
            process, result_path = analysis.start(name, "advance", [{"analysisId": analysis_id}])
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline and process.poll() is None and not (
                    len(files("analysis_result")) > content_files and blocked_backends() >= 1):
                time.sleep(0.3)
            check(process.poll() is None and len(files("analysis_result")) == content_files + 1 and blocked_backends() >= 1,
                  f"{name}: the jar must be waiting for the row lock with its content files already written")
            if expires_at is not None:
                check(time.time() < expires_at - 2, f"{name}: the grant expired before the jar judged the result (raise the margin)")
            change()
            if expires_at is not None:
                time.sleep(max(0.0, expires_at + 1 - time.time()))
        except BaseException:
            if process is not None and process.poll() is None:
                process.kill()
            raise
        finally:
            release(db, lock, marker)
        process.wait(timeout=180)
        imp.OUTPUT.append(process.stdout.read().decode("utf-8", "replace"))
        result = analysis.read(name, result_path)
        check(process.returncode == 0 and result is not None and result["items"][0]["status"] == "settled",
              f"{name}: the released settlement did not finish: {json.dumps(result)[:500]}")
        return result["items"][0]

    def evidence_id(analysis_id: str, model_id: str) -> str:
        return "ev-" + sha(canonical({"analysisId": analysis_id, "evidenceId": model_id}).encode("utf-8"))

    try:
        # ---- 1: prepare ------------------------------------------------------------------------------------------------
        label = step("prepare J1/J2: a pending row with a new AI job id and an immutable ai_submit, and no service job at all")
        result = analysis.prepare("prepare-d1", [pitem(refs[1], "document-summary", "SYNTH-A"),
                                                 pitem(refs[1], "document-sentiment", "SYNTH-A")])
        j1, j2 = result["items"]
        check(j1["status"] == j2["status"] == "prepared" and j1["requestNo"] == j2["requestNo"] == 1
              and (j1["stage"], j2["stage"]) == ("summary", "sentiment"), f"{label}: {result}")
        check(j1["aiJobId"] != j2["aiJobId"] and j1["aiJobId"].startswith("s1-") and len(j1["aiJobId"]) == 35, f"{label}: job ids")
        r1, r2 = row(j1["analysisId"]), row(j2["analysisId"])
        check((r1["status"], r1["company_id"], r1["grant_reference"], r1["grant_revision"], r1["ai_job_id"], r1["owner_token"],
               r1["lease_until"], r1["analysis_job_id"]) == ("pending", None, GRANT_ID, GRANT_REVISION, j1["aiJobId"], None, None, None),
              f"{label}: {r1}")
        check(r2["company_id"] == "SYNTH-A" and r1["grant_checked_at"] is not None, f"{label}: {r2}")
        for item_, n_ in ((j1, "document-summary"), (j2, "document-sentiment")):
            artifact = db.rows(f"SELECT * FROM artifacts WHERE id = 'submit-{item_['aiJobId']}'")[0]
            stored = world.artifacts / "ai_submit" / f"submit-{item_['aiJobId']}.json"
            raw = stored.read_bytes()
            submit = json.loads(raw)
            check(artifact["kind"] == "ai_submit" and artifact["sha256"] == sha(raw) and artifact["bytes"] == len(raw)
                  and artifact["storage_uri"] == f"artifact-root:ai_submit/submit-{item_['aiJobId']}.json"
                  and stat.S_IMODE(stored.stat().st_mode) == 0o600, f"{label}: artifact {artifact}")
            check(raw.decode("utf-8") == canonical(submit), f"{label}: the stored submit is not Python-canonical JSON")
            check((submit["kind"], submit["mode"], submit["jobId"]) == (n_, "replay", item_["aiJobId"])
                  and submit["input"]["company"] == company["SYNTH-A"] and submit["input"]["document"] == documents[1]
                  and submit["input"]["candidate"] is None and submit["provenance"] == {
                      "sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}, f"{label}: submit")
            check(service.status(item_["aiJobId"]).status_code == 404, f"{label}: the service must not know the job yet")
        check(proxy.requests == [] and worker_calls() == [], f"{label}: prepare called the AI service")

        label = step("prepare again for the same scope: latest_conflict, nothing written")
        before = counts()
        code, result, _ = analysis.run("prepare-again", "prepare", [pitem(refs[1], "document-summary", "SYNTH-A")])
        check(code != 0 and result["items"][0]["failure"]["code"] == "latest_conflict"
              and result["items"][0]["failure"]["latestAnalysisId"] == j1["analysisId"], f"{label}: {result}")
        code, result, _ = analysis.run("prepare-pending", "prepare", [pitem(refs[1], "document-summary", "SYNTH-A", expected=j1["analysisId"])])
        check(code != 0 and result["items"][0]["failure"]["code"] == "analysis_pending", f"{label}: {result}")
        check(counts() == before and len(files("ai_submit")) == 2, f"{label}: a refused prepare changed state")

        # ---- 2: advance: submit once, then the AI service decides --------------------------------------------------------
        label = step("advance J1: status 404 -> one submit of the stored bytes -> ready -> available (digest parity on real worker output)")
        done = analysis.settle("advance-j1", j1["analysisId"])
        check(done["status"] == "settled" and done["outcome"] == "available" and done["evidence"] == 2
              and done["executions"] == {"recorded": 2, "existing": 0}, f"{label}: {done}")
        check(proxy.count("POST", "/analysis-jobs") == 1, f"{label}: the job was submitted {proxy.count('POST', '/analysis-jobs')} times")
        r1 = row(j1["analysisId"])
        main_artifact = json.loads((world.artifacts / "analysis_result" / f"{r1['result_artifact_id']}.json").read_bytes())
        verifier = json.loads((world.artifacts / "semantic_receipt" / f"{r1['semantic_receipt_id']}.json").read_bytes())
        check((r1["status"], r1["reason"], r1["exact_receipt_id"]) == ("available", None, "exact-" + j1["analysisId"]), f"{label}: {r1}")
        check(r1["result_version"] == main_artifact["resultVersion"] and main_artifact["kind"] == "document-summary"
              and verifier["kind"] == "semantic-verification" and main_artifact["dependencyRefs"] == [verifier["artifactId"]]
              and r1["model"] == "authored-synthetic-document-summary" and r1["prompt_version"] == main_artifact["promptVersion"],
              f"{label}: row does not match the worker artifact")
        stored_text = (world.artifacts / "analysis_result" / f"{main_artifact['artifactId']}.json").read_text("utf-8")
        check(canonical(main_artifact) == stored_text == worker_artifact(main_artifact["artifactId"]),
              f"{label}: the stored artifact is not the worker's own canonical artifact, byte for byte")
        check((world.artifacts / "semantic_receipt" / f"{verifier['artifactId']}.json").read_text("utf-8")
              == worker_artifact(verifier["artifactId"]), f"{label}: the stored verifier is not the worker's own artifact")
        dto = r1["result"]
        check(dto["text"] == answers["J1"]["text"] and dto["limitations"] == [LIMITATION] and dto["artifactId"] == main_artifact["artifactId"]
              and dto["resultVersion"] == r1["result_version"] and dto["documentId"] == refs[1]["documentId"]
              and dto["documentVersion"] == refs[1]["documentVersion"] and dto["provenance"] == main_artifact["provenance"],
              f"{label}: dto {dto}")
        check(dto["claims"][0]["evidenceIds"] == [evidence_id(j1["analysisId"], "e1")]
              and [c["evidenceId"] for c in dto["citations"]] == [evidence_id(j1["analysisId"], "e1"), evidence_id(j1["analysisId"], "e2")],
              f"{label}: app evidence ids")
        evidence = db.rows("SELECT * FROM evidence ORDER BY start_offset")
        text1 = documents[1]["text"]
        check(len(evidence) == 2, f"{label}: evidence rows {len(evidence)}")
        for ev, expected in zip(evidence, answers["J1"]["citations"]):
            check(ev["quote"] == text1[ev["start_offset"]:ev["end_offset"]] == expected["quote"]
                  and (ev["start_offset"], ev["end_offset"]) == (expected["start"], expected["end"])
                  and ev["offset_unit"] == "unicode_code_point" and ev["input_kind"] == "body" and ev["summary_analysis_id"] is None
                  and ev["quote_verified"] is True and ev["verification_artifact_id"] == "exact-" + j1["analysisId"]
                  and ev["text_artifact_id"] == "text-" + refs[1]["documentVersion"] and ev["raw_locator_ids"] == expected["rawLocatorIds"],
                  f"{label}: evidence {ev}")
        exact = json.loads((world.artifacts / "exact_receipt" / f"exact-{j1['analysisId']}.json").read_bytes())
        check(exact["textSha256"] == sha(text1.encode("utf-8")) and exact["resultVersion"] == r1["result_version"]
              and exact["policyVersion"] == "zoop-document-gate-2", f"{label}: exact receipt")
        calls = {c["attempt_id"]: c for c in worker_calls() if c["job_id"] == j1["aiJobId"]}
        run1 = executions(j1["aiJobId"])
        check(len(run1) == 2 == len(calls) and {e["ai_attempt_id"] for e in run1} == set(calls)
              and all(e["feature"] == "news-analysis" and e["execution_mode"] == "replay" and e["status"] == "succeeded"
                      and e["document_analysis_id"] == j1["analysisId"] and e["grant_id"] == GRANT_ID
                      and e["grant_scope"] == {"sourceId": imp.SOURCE, "requiredOperations": ["read", "store", "model-send", "quote-display"],
                                               "requiredPurposes": ["document-summary", "semantic-verification"],
                                               "requiredRecipients": ["authored-replay"]}
                      and e["grant_checked_at"] is None and e["actual_cost"] is None and e["estimated_cost"] is None
                      and e["input_tokens"] is None for e in run1), f"{label}: executions {run1}")
        check(kinds().get("analysis_result") == 1 and kinds().get("ai_call_receipt") == 2, f"{label}: artifact kinds {kinds()}")

        label = step("advance J2 (sentiment of the same document and company): no evidence rows, DocumentSentiment fields, feature mapping")
        done = analysis.settle("advance-j2", j2["analysisId"])
        check(done["outcome"] == "available" and done["evidence"] == 0, f"{label}: {done}")
        r2 = row(j2["analysisId"])
        dto = r2["result"]
        check(dto["label"] == "mixed" and dto["companyId"] == "SYNTH-A" and dto["rationale"] == answers["J2"]["rationale"]
              and dto["quotes"] == [c["quote"] for c in answers["J2"]["citations"]] and dto["model"] == "authored-synthetic-document-sentiment"
              and set(dto) == {"label", "companyId", "rationale", "quotes", "judgedAt", "model", "promptVersion"}, f"{label}: dto {dto}")
        check({(e["stage"], e["feature"]) for e in executions(j2["aiJobId"])}
              == {("document-sentiment", "document-sentiment"), ("semantic-verification", "news-analysis")}, f"{label}: features")
        check(db.scalar("SELECT count(*) FROM evidence") == 2, f"{label}: sentiment wrote evidence")

        label = step("advance again: already_settled, no HTTP, row counts and updated_at unchanged")
        before, snapshot = counts(), db.rows("SELECT id, updated_at FROM document_analyses ORDER BY id")
        requests_before = len(proxy.requests)
        code, result, _ = analysis.run("advance-again", "advance", [{"analysisId": j1["analysisId"]}, {"analysisId": j2["analysisId"]}])
        check(code == 0 and [i["status"] for i in result["items"]] == ["already_settled"] * 2
              and all(i["outcome"] == "available" for i in result["items"]), f"{label}: {result}")
        check(counts() == before and db.rows("SELECT id, updated_at FROM document_analyses ORDER BY id") == snapshot
              and len(proxy.requests) == requests_before and len(worker_calls()) == 4, f"{label}: state or calls changed")

        label = step("prepare for an unchanged input is refused; an unknown company, a private article and a revoked grant leave nothing behind")
        before = counts()
        code, result, _ = analysis.run("unchanged", "prepare", [pitem(refs[1], "document-summary", "SYNTH-A", expected=j1["analysisId"])])
        check(code != 0 and result["items"][0]["failure"]["code"] == "analysis_unchanged"
              and result["items"][0]["failure"]["analysisId"] == j1["analysisId"], f"{label}: {result}")
        code, result, _ = analysis.run("no-company", "prepare", [pitem(refs[2], "document-summary", "NO-SUCH")])
        check(code != 0 and result["items"][0]["failure"]["code"] == "company_unknown", f"{label}: {result}")
        code, result, _ = analysis.run("replay-actual", "prepare", [pitem(refs[2], "document-summary", "SYNTH-A", source_kind="actual")])
        check(code != 0 and result["failure"]["code"] == "request_invalid" and result["items"] == [], f"{label}: {result}")
        db.run(f"UPDATE articles SET access_status = 'private' WHERE id = '{refs[2]['documentId']}'")
        code, result, _ = analysis.run("private", "prepare", [pitem(refs[2], "document-summary", "SYNTH-A")])
        check(code != 0 and result["items"][0]["failure"]["code"] == "article_access_unavailable", f"{label}: {result}")
        db.run(f"UPDATE articles SET access_status = 'available' WHERE id = '{refs[2]['documentId']}'")
        save_app_grants(flat_grants(enabled=False))
        code, result, _ = analysis.run("revoked", "prepare", [pitem(refs[2], "document-summary", "SYNTH-A")])
        check(code != 0 and result["items"][0]["failure"]["code"] == "grant_denied"
              and result["items"][0]["failure"]["grantCode"] == "source_rights_unknown_or_denied", f"{label}: {result}")
        save_app_grants(flat_grants(operations=["read", "store", "model-send"]))
        code, result, _ = analysis.run("no-quote-display", "prepare", [pitem(refs[2], "document-summary", "SYNTH-A")])
        check(code != 0 and result["items"][0]["failure"]["grantCode"] == "source_operation_denied", f"{label}: {result}")
        save_app_grants(flat_grants())
        check(counts() == before and len(files("ai_submit")) == 2, f"{label}: a refused prepare changed state")

        # ---- 3: verifier hold ---------------------------------------------------------------------------------------------
        label = step("J3: the verifier answers insufficient -> withheld semantic_hold, receipts and executions kept, no content")
        j3 = analysis.prepare("prepare-j3", [pitem(refs[2], "document-summary", "SYNTH-A")])["items"][0]
        done = analysis.settle("advance-j3", j3["analysisId"])
        check(done["outcome"] == "withheld" and done["reason"] == "semantic_hold" and done["executions"]["recorded"] == 2, f"{label}: {done}")
        r3 = row(j3["analysisId"])
        check(r3["status"] == "withheld" and r3["result"] is None and r3["result_version"] is None and r3["result_artifact_id"] is None
              and r3["model"] == "authored-synthetic-document-summary", f"{label}: {r3}")
        check(kinds().get("analysis_result") == 2 and len(files("analysis_result")) == 2 and len(executions(j3["aiJobId"])) == 2,
              f"{label}: content of a withheld result was stored")

        # ---- 4: the service withholds, then a cache-served re-request ----------------------------------------------------------
        label = step("J4: the service registry is revoked after the job is ready -> withheld with the service's code, receipts kept")
        j4 = analysis.prepare("prepare-j4", [pitem(refs[3], "document-summary", "SYNTH-A")])["items"][0]
        code, result, _ = analysis.run("submit-j4", "advance", [{"analysisId": j4["analysisId"]}])
        check(code == 0 and result["items"][0]["status"] == "pending", f"{label}: {result}")
        wait_ready(j4["aiJobId"])
        save_service_grants(flat_grants(enabled=False))
        done = analysis.settle("advance-j4", j4["analysisId"])
        check(done["outcome"] == "withheld" and done["reason"] == "source_rights_unknown_or_denied"
              and done["executions"]["recorded"] == 2, f"{label}: {done}")
        check(row(j4["analysisId"])["result"] is None and len(executions(j4["aiJobId"])) == 2, f"{label}: {row(j4['analysisId'])}")
        calls_before = len(worker_calls())

        label = step("J4 again after the rights are restored at the same revision: worker cache hit -> available, attempts counted once")
        save_service_grants(flat_grants())
        j4b = analysis.prepare("prepare-j4b", [pitem(refs[3], "document-summary", "SYNTH-A", expected=j4["analysisId"])])["items"][0]
        check(j4b["requestNo"] == 2 and j4b["aiJobId"] != j4["aiJobId"], f"{label}: {j4b}")
        done = analysis.settle("advance-j4b", j4b["analysisId"])
        check(done["outcome"] == "available" and done["executions"] == {"recorded": 0, "existing": 2} and done["evidence"] == 2, f"{label}: {done}")
        cached = service.status(j4b["aiJobId"]).json()
        check(cached["phase"] == "artifact.cache_hit" and len(worker_calls()) == calls_before, f"{label}: no new worker call may happen: {cached['phase']}")
        check(len(executions()) == 8 and all(e["document_analysis_id"] == j4["analysisId"] for e in executions(j4["aiJobId"]))
              and executions(j4b["aiJobId"]) == [], f"{label}: usage must stay with the creator of the attempts")
        cached_row = row(j4b["analysisId"])
        check(row(j4["analysisId"])["status"] == "withheld" and cached_row["status"] == "available"
              and (world.artifacts / "analysis_result" / f"{cached_row['result_artifact_id']}.json").is_file(), f"{label}: terminal rows")

        # ---- 5: the app's own registry --------------------------------------------------------------------------------
        label = step("J5: the app's registry copy lacks quote-display while the service still delivers -> withheld source_operation_denied")
        j5 = analysis.prepare("prepare-j5", [pitem(refs[3], "document-sentiment", "SYNTH-B")])["items"][0]
        code, result, _ = analysis.run("submit-j5", "advance", [{"analysisId": j5["analysisId"]}])
        check(code == 0 and result["items"][0]["status"] == "pending", f"{label}: {result}")
        wait_ready(j5["aiJobId"])
        save_app_grants(flat_grants(operations=["read", "store", "model-send"]))
        done = analysis.settle("advance-j5", j5["analysisId"])
        check(done["outcome"] == "withheld" and done["reason"] == "source_operation_denied" and done["executions"]["recorded"] == 2,
              f"{label}: {done}")
        save_app_grants(flat_grants())

        # ---- 6: a lost submit reply, then a crash inside the settlement ----------------------------------------------------
        label = step("J6: the submit reply is lost -> submit_outcome_unknown; the next advance reads status 200 and never submits again")
        j6 = analysis.prepare("prepare-j6", [pitem(refs[4], "document-summary", "SYNTH-A")])["items"][0]
        proxy.drop_next_submit_reply = True
        posts_before = proxy.count("POST", "/analysis-jobs")
        analysis.advance_failure("lost-reply", j6["analysisId"], "submit_outcome_unknown")
        check(proxy.count("POST", "/analysis-jobs") == posts_before + 1 and row(j6["analysisId"])["status"] == "pending", f"{label}: posts")
        wait_ready(j6["aiJobId"])
        check(len([c for c in worker_calls() if c["job_id"] == j6["aiJobId"]]) == 2, f"{label}: the worker must have made exactly two calls")

        label = step("J6 settlement: kill -9 while the transaction waits on a row lock (files written, nothing committed), then rerun")
        marker = f"zoop-smoke-lock-{os.getpid()}"
        j6_id = j6["analysisId"]
        lock = hold(db, f"SELECT 1 FROM document_analyses WHERE id = '{j6_id}' FOR UPDATE", marker)
        try:
            time.sleep(2)
            before, result_files = counts(), len(files("analysis_result"))
            process, result_path = analysis.start("crash-settle", "advance", [{"analysisId": j6_id}])
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and process.poll() is None and len(files("analysis_result")) <= result_files:
                time.sleep(0.3)
            check(process.poll() is None and len(files("analysis_result")) == result_files + 1,
                  f"{label}: the jar must be blocked inside the settlement with its files written")
            process.send_signal(signal.SIGKILL)
            process.wait(timeout=30)
            imp.OUTPUT.append(process.stdout.read().decode("utf-8", "replace"))
        finally:
            release(db, lock, marker)
        check(counts() == before and row(j6_id)["status"] == "pending" and result_path.read_bytes() == b"",
              f"{label}: a killed settlement must commit nothing and leave its result file empty ('outcome unknown')")
        orphan_files = {d: files(d) for d in ("analysis_result", "semantic_receipt", "exact_receipt", "ai_call_receipt")}
        done = analysis.settle("advance-j6", j6["analysisId"])
        check(done["outcome"] == "available" and done["executions"] == {"recorded": 2, "existing": 0}, f"{label}: {done}")
        check({d: files(d) for d in orphan_files} == orphan_files, f"{label}: the rerun must adopt the same files, not create others")
        check(len([c for c in worker_calls() if c["job_id"] == j6["aiJobId"]]) == 2 and len(executions(j6["aiJobId"])) == 2
              and proxy.count("POST", "/analysis-jobs") == posts_before + 1, f"{label}: usage or submits were duplicated")

        # ---- 7: a crash while preparing, then a tampered result ---------------------------------------------------------------
        label = step("prepare crash: kill -9 after the submit file is written and before the transaction -> only an unreferenced orphan file")
        files_before = files("ai_submit")
        doc5_id = refs[5]["documentId"]
        lock = hold(db, f"SELECT 1 FROM articles WHERE id = '{doc5_id}' FOR UPDATE", marker + "-p")
        try:
            time.sleep(2)
            before = counts()
            process, _ = analysis.start("crash-prepare", "prepare", [pitem(refs[5], "document-summary", "SYNTH-A")])
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and process.poll() is None and len(files("ai_submit")) == len(files_before):
                time.sleep(0.3)
            check(process.poll() is None and len(files("ai_submit")) == len(files_before) + 1, f"{label}: no orphan file appeared")
            process.send_signal(signal.SIGKILL)
            process.wait(timeout=30)
            imp.OUTPUT.append(process.stdout.read().decode("utf-8", "replace"))
        finally:
            release(db, lock, marker + "-p")
        orphan = (set(files("ai_submit")) - set(files_before)).pop()
        check(counts() == before and db.scalar(f"SELECT count(*) FROM artifacts WHERE storage_uri = 'artifact-root:ai_submit/{orphan}'") == 0,
              f"{label}: the orphan must be unreferenced")
        j7 = analysis.prepare("prepare-j7", [pitem(refs[5], "document-summary", "SYNTH-A")])["items"][0]
        check(f"submit-{j7['aiJobId']}.json" != orphan and orphan in files("ai_submit"), f"{label}: a new job id, and the orphan is never deleted")

        label = step("J7: a result computed for another input is refused (pending, nothing written); the clean result then settles")
        code, result, _ = analysis.run("submit-j7", "advance", [{"analysisId": j7["analysisId"]}])
        check(code == 0 and result["items"][0]["status"] == "pending", f"{label}: {result}")
        wait_ready(j7["aiJobId"])
        before = counts()
        proxy.tamper_result = tamper_company
        failure = analysis.advance_failure("tampered", j7["analysisId"], "result_binding_invalid")
        proxy.tamper_result = None
        check(failure["detail"] == "input_changed" and counts() == before and row(j7["analysisId"])["status"] == "pending",
              f"{label}: {failure}")
        done = analysis.settle("advance-j7", j7["analysisId"])
        check(done["outcome"] == "available" and len(executions(j7["aiJobId"])) == 2, f"{label}: {done}")

        # ---- 8: the worker refuses the answer ---------------------------------------------------------------------------------
        label = step("J8: limitations that do not match the limitation claims -> the worker's exact check fails -> failed with its code")
        j8 = analysis.prepare("prepare-j8", [pitem(refs[6], "document-summary", "SYNTH-A")])["items"][0]
        done = analysis.settle("advance-j8", j8["analysisId"])
        check(done["outcome"] == "failed" and done["reason"] == "limitation_claim_coverage_invalid"
              and done["executions"]["recorded"] == 1, f"{label}: {done}")
        failed_execution = executions(j8["aiJobId"])
        check(len(failed_execution) == 1 and failed_execution[0]["status"] == "failed" and failed_execution[0]["stage"] == "document-summary"
              and failed_execution[0]["error_code"] == "limitation_claim_coverage_invalid", f"{label}: {failed_execution}")
        check(row(j8["analysisId"])["status"] == "failed" and row(j8["analysisId"])["result"] is None, f"{label}: row")

        # ---- 9: an explicit re-request after a hold, with a settlement that is refused and rolled back -----------------------------
        label = step("J9: re-request of the held document; a conflicting exact-receipt row rolls the settlement back and removes its files")
        j9 = analysis.prepare("prepare-j9", [pitem(refs[2], "document-summary", "SYNTH-A", expected=j3["analysisId"])])["items"][0]
        check(j9["requestNo"] == 2, f"{label}: {j9}")
        code, result, _ = analysis.run("submit-j9", "advance", [{"analysisId": j9["analysisId"]}])
        check(code == 0 and result["items"][0]["status"] == "pending", f"{label}: {result}")
        wait_ready(j9["aiJobId"])
        db.run("INSERT INTO artifacts (id, kind, storage_uri, sha256, bytes, media_type, created_at) VALUES "
               f"('exact-{j9['analysisId']}', 'exact_receipt', 'artifact-root:exact_receipt/planted.json', '{'0' * 64}', 1, 'application/json', now())")
        before, file_state = counts(), {d: files(d) for d in ("analysis_result", "semantic_receipt", "exact_receipt", "ai_call_receipt")}
        analysis.advance_failure("rollback", j9["analysisId"], "artifact_conflict")
        check(counts() == before and {d: files(d) for d in file_state} == file_state and row(j9["analysisId"])["status"] == "pending",
              f"{label}: a refused settlement must change neither the database nor the files it was not the first to create")
        db.run(f"DELETE FROM artifacts WHERE id = 'exact-{j9['analysisId']}'")
        done = analysis.settle("advance-j9", j9["analysisId"])
        check(done["outcome"] == "available" and done["evidence"] == 2, f"{label}: {done}")
        check(row(j3["analysisId"])["status"] == "withheld" and row(j9["analysisId"])["request_no"] == 2, f"{label}: history is kept")

        # ---- 10: a tampered stored file and a private article ------------------------------------------------------------------
        label = step("a submit file that no longer matches its registry row is never sent")
        j10 = analysis.prepare("prepare-j10", [pitem(refs[1], "document-summary", "SYNTH-B", expected=j1["analysisId"])])["items"][0]
        stored = world.artifacts / "ai_submit" / f"submit-{j10['aiJobId']}.json"
        original = stored.read_bytes()
        stored.write_bytes(original.replace(b"SYNTH-B", b"SYNTH-X"))
        posts = proxy.count("POST", "/analysis-jobs")
        analysis.advance_failure("tampered-submit", j10["analysisId"], "artifact_file_conflict")
        check(proxy.count("POST", "/analysis-jobs") == posts and service.status(j10["aiJobId"]).status_code == 404, f"{label}: bytes were sent")
        stored.write_bytes(original)

        # ---- 10b: the verifier must have verified exactly the claims the answer makes ------------------------------------------
        label = step("J11: main claims edited and re-hashed while the verifier's verdicts describe the old claims -> withheld, receipts kept, no content")
        j11 = analysis.prepare("prepare-j11", [pitem(refs[4], "document-summary", "SYNTH-B", expected=j6["analysisId"])])["items"][0]
        code, result, _ = analysis.run("submit-j11", "advance", [{"analysisId": j11["analysisId"]}])
        check(code == 0 and result["items"][0]["status"] == "pending", f"{label}: {result}")
        wait_ready(j11["aiJobId"])
        before_kinds, before_evidence, before_content = kinds(), counts()["evidence"], {d: files(d) for d in CONTENT_DIRECTORIES}
        tampered_before = proxy.tampered
        proxy.tamper_result = rewrite_main_claims
        done = analysis.settle("advance-j11", j11["analysisId"])
        proxy.tamper_result = None
        check(proxy.tampered == tampered_before + 1, f"{label}: the proxy rewrote {proxy.tampered - tampered_before} results, not one")
        check(done["outcome"] == "withheld" and done["reason"] == "semantic_claim_coverage_invalid"
              and done["executions"] == {"recorded": 2, "existing": 0}, f"{label}: {done}")
        assert_no_content(label, j11, before_kinds, before_evidence, before_content)

        # ---- 10c: authority is read again before the app asks the service to do work ------------------------------------------------
        label = step("J12: the app's grant copy loses model-send (the service still allows it) between prepare and advance -> no submit, nothing written")
        j12 = analysis.prepare("prepare-j12", [pitem(refs[5], "document-sentiment", "SYNTH-A")])["items"][0]
        posts_before, before = proxy.count("POST", "/analysis-jobs"), counts()
        save_app_grants(flat_grants(operations=["read", "store", "quote-display"]))
        failure = analysis.advance_failure("revoked-before-submit", j12["analysisId"], "grant_denied")
        check(failure["grantCode"] == "source_operation_denied", f"{label}: {failure}")
        check(proxy.count("POST", "/analysis-jobs") == posts_before and service.status(j12["aiJobId"]).status_code == 404
              and counts() == before and row(j12["analysisId"])["status"] == "pending",
              f"{label}: a revoked grant still caused a submit or a write")
        save_app_grants(flat_grants())
        label = step("J12: the article became private between prepare and advance -> no submit, nothing written")
        db.run(f"UPDATE articles SET access_status = 'private' WHERE id = '{refs[5]['documentId']}'")
        try:
            analysis.advance_failure("private-before-submit", j12["analysisId"], "article_access_unavailable")
        finally:
            db.run(f"UPDATE articles SET access_status = 'available' WHERE id = '{refs[5]['documentId']}'")
        check(proxy.count("POST", "/analysis-jobs") == posts_before and service.status(j12["aiJobId"]).status_code == 404
              and counts() == before and row(j12["analysisId"])["status"] == "pending",
              f"{label}: a private article still caused a submit or a write")
        label = step("J12 with authority restored: exactly one submit, then available")
        done = analysis.settle("advance-j12", j12["analysisId"])
        check(done["outcome"] == "available" and done["evidence"] == 0 and done["executions"] == {"recorded": 2, "existing": 0}
              and proxy.count("POST", "/analysis-jobs") == posts_before + 1, f"{label}: {done}")

        # ---- 10d: authority is judged again after the database row lock was won --------------------------------------------------
        label = step("J13: the app's grant copy loses an operation while the settlement waits for a real PostgreSQL row lock -> withheld, receipts kept, no content")
        j13 = analysis.prepare("prepare-j13", [pitem(refs[6], "document-sentiment", "SYNTH-A")])["items"][0]
        code, result, _ = analysis.run("submit-j13", "advance", [{"analysisId": j13["analysisId"]}])
        check(code == 0 and result["items"][0]["status"] == "pending", f"{label}: {result}")
        wait_ready(j13["aiJobId"])
        before_kinds, before_evidence = kinds(), counts()["evidence"]
        before_content = {d: files(d) for d in CONTENT_DIRECTORIES}
        done = settle_across_row_lock("revoked-in-wait", j13,
                                      lambda: save_app_grants(flat_grants(operations=["read", "store", "model-send"])))
        check(done["outcome"] == "withheld" and done["reason"] == "source_operation_denied"
              and done["executions"] == {"recorded": 2, "existing": 0}, f"{label}: {done}")
        assert_no_content(label, j13, before_kinds, before_evidence, before_content)
        save_app_grants(flat_grants())

        label = step("J14: the app's grant copy expires while the settlement waits for the row lock -> withheld source_grant_expired, receipts kept, no content")
        j14 = analysis.prepare("prepare-j14", [pitem(refs[5], "document-sentiment", "SYNTH-B")])["items"][0]
        code, result, _ = analysis.run("submit-j14", "advance", [{"analysisId": j14["analysisId"]}])
        check(code == 0 and result["items"][0]["status"] == "pending", f"{label}: {result}")
        wait_ready(j14["aiJobId"])
        before_kinds, before_evidence = kinds(), counts()["evidence"]
        before_content = {d: files(d) for d in CONTENT_DIRECTORIES}
        expiry = time.time() + 45  # valid while the jar judges the result, expired by the time the lock is released
        save_app_grants(flat_grants(expires_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expiry))))
        done = settle_across_row_lock("expired-in-wait", j14, lambda: None, expires_at=expiry)
        check(done["outcome"] == "withheld" and done["reason"] == "source_grant_expired"
              and done["executions"] == {"recorded": 2, "existing": 0}, f"{label}: {done}")
        assert_no_content(label, j14, before_kinds, before_evidence, before_content)
        save_app_grants(flat_grants())

        # ---- 10e: a file conflict after other files were stored is not a database rollback --------------------------------------
        label = step("J15: a different file already sits at the verifier's path -> artifact_file_conflict removes the files this attempt created and nothing else")
        j15 = analysis.prepare("prepare-j15", [pitem(refs[4], "document-sentiment", "SYNTH-A")])["items"][0]
        code, result, _ = analysis.run("submit-j15", "advance", [{"analysisId": j15["analysisId"]}])
        check(code == 0 and result["items"][0]["status"] == "pending", f"{label}: {result}")
        wait_ready(j15["aiJobId"])
        planted = world.artifacts / "semantic_receipt" / f"{worker_artifact_id(j15['aiJobId'], 'semantic-verification')}.json"
        check(not planted.exists(), f"{label}: the verifier file already exists")
        before, file_state = counts(), {d: files(d) for d in CONTENT_DIRECTORIES + ("ai_call_receipt",)}
        descriptor = os.open(planted, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, PLANTED)
        finally:
            os.close(descriptor)
        analysis.advance_failure("late-file-conflict", j15["analysisId"], "artifact_file_conflict")
        expected_files = {**file_state, "semantic_receipt": sorted(file_state["semantic_receipt"] + [planted.name])}
        check(counts() == before and row(j15["analysisId"])["status"] == "pending" and executions(j15["aiJobId"]) == [],
              f"{label}: the database changed")
        check(planted.read_bytes() == PLANTED, f"{label}: the file that was already there was modified")
        check({d: files(d) for d in file_state} == expected_files,
              f"{label}: files created by the refused attempt were left behind: {({d: files(d) for d in file_state})}")
        planted.unlink()
        done = analysis.settle("advance-j15", j15["analysisId"])
        check(done["outcome"] == "available" and done["executions"] == {"recorded": 2, "existing": 0}, f"{label}: {done}")

        # ---- 11: the operator guards ------------------------------------------------------------------------------------------
        label = step("enabled without --spring.main.web-application-type=none, or next to the document import, refuses to start")
        request, result = analysis.files("web-refusal", "advance", [{"analysisId": j1["analysisId"]}])
        done = subprocess.run(jar.argv("--server.port=0"), env=analysis.env(request, result), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=240)
        output = done.stdout.decode("utf-8", "replace")
        imp.OUTPUT.append(output)
        check(done.returncode != 0 and "zoop.document-analysis.enabled" in output and "web-application-type" in output
              and "Tomcat started" not in output and not result.exists(), f"{label}: the web start was not refused")
        request, result = analysis.files("both-enabled", "advance", [{"analysisId": j1["analysisId"]}])
        done = subprocess.run(jar.argv("--spring.main.web-application-type=none"),
                              env={**analysis.env(request, result), "ZOOP_DOCUMENT_IMPORT_ENABLED": "true",
                                   "ZOOP_DOCUMENT_IMPORT_REQUEST": str(request), "ZOOP_DOCUMENT_IMPORT_RESULT": str(world.requests / "x.json")},
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
        output = done.stdout.decode("utf-8", "replace")
        imp.OUTPUT.append(output)
        check(done.returncode != 0 and "cannot run together" in output, f"{label}: both enabled started")
        check(not result.exists(), f"{label}: a refused start created a result file")
        imp.normal_start(jar)

        # ---- final ----------------------------------------------------------------------------------------------------------------
        label = step("final state: no provider call, usage equals the worker ledger, read-only S2-1 ledger, nothing leaked")
        calls_all = worker_calls()
        all_executions = executions()
        check(all(c["mode"] == "replay" for c in calls_all) and len(calls_all) == len(all_executions)
              and {c["attempt_id"] for c in calls_all} == {e["ai_attempt_id"] for e in all_executions},
              f"{label}: {len(calls_all)} worker calls vs {len(all_executions)} counted executions")
        for job_id in [j["aiJobId"] for j in (j1, j2, j3, j4, j4b, j5, j6, j7, j8, j9, j11, j12, j13, j14, j15)]:
            usage = service.status(job_id).json()["usage"]
            check(usage["providerAttempts"] == 0, f"{label}: {job_id} reports {usage['providerAttempts']} provider attempts")
        statuses = db.rows("SELECT status, count(*) AS n FROM document_analyses GROUP BY status ORDER BY status")
        check({s["status"]: s["n"] for s in statuses} == {"available": 8, "failed": 1, "pending": 1, "withheld": 6}, f"{label}: {statuses}")
        # Expected independently of the code under test: J1..J9 made 17 worker calls (J4b was a cache hit, J8 stopped after one
        # call); J11..J15 made two each; only the five summaries that settled as available (J1, J4b, J6, J7, J9) have evidence.
        check(len(calls_all) == 17 + 5 * 2 and db.scalar("SELECT count(*) FROM evidence") == 10,
              f"{label}: {len(calls_all)} worker calls and {db.scalar('SELECT count(*) FROM evidence')} evidence rows")
        check(world.ledger_fingerprint() == ledger, f"{label}: the S2-1 ledger changed")
        joined = "\n".join(imp.OUTPUT) + service.logs()
        check(len(db.password) < 8 or db.password not in joined, f"{label}: the database password appears in output")
        check(workspace.credentials.tokens["alpha"] not in joined and workspace.api_key not in joined, f"{label}: a token appears in output")
        check(str(world.root) not in "\n".join(imp.OUTPUT) and all(text not in "\n".join(imp.OUTPUT) for text in TEXTS),
              f"{label}: a path or document text appears in process output")
        print(json.dumps({"status": "passed", "steps": len(imp.STEPS), "providerCalls": 0, "modelCalls": 0,
                          "analyses": db.scalar("SELECT count(*) FROM document_analyses"), "executions": len(all_executions),
                          "workerCalls": len(calls_all), "evidence": db.scalar("SELECT count(*) FROM evidence"),
                          "jarRuns": jar.counter, "ledgerReadOnly": True}))
        return 0
    finally:
        proxy.close()
        service.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as failure:
        print("document analysis smoke FAILED: " + str(failure).replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        for output in imp.OUTPUT[-1:]:
            print("--- last process output (tail) ---\n" + output[-2500:].replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
        sys.exit(1)
