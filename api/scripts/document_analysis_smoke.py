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
     remove exactly the files that attempt created,
  6. then (default; --no-with-evidence-read skips it) starts the SAME jar as a real web server on 127.0.0.1 with only the
     ZOOP_DOCUMENT_READ_* settings and reads EVERY stored evidence row through GET /api/v1/evidence/{id}: the shape and the
     quote against the exported text, pins, company context, a grant changed while the server runs, a private article, a moved
     current version, a newer pending request, and the cache-served J4b (its calls are recorded under the withheld J4, so one
     verified read of its exact receipt proves the creator; missing, altered or insecure receipt, missing creator executions, an
     operator holding the store lock, no artifact root). Expectations come from psql and the grant file, not from the Java code. It
     proves the reads change nothing: no AI request, no worker call, no row or table write, no file or lock file.

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
import datetime as dt
import fcntl
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


# --------------------------------------------------------------------------------------------------------------------
# the public evidence read: the built jar as a REAL web server on loopback (no operator flag, no AI client)
# --------------------------------------------------------------------------------------------------------------------
EVIDENCE_KEYS = {"id", "quote", "start", "end", "articleId", "articleVersion", "article", "quoteVerified", "eventIds", "metadata",
                 "sentiment", "documentVersion", "documentSummary", "analysisStatus", "analysisProvenance", "resultVersion"}
METADATA_KEYS = {"source", "asOf", "graphVersion", "requestId", "partial", "failures"}
FAILURE_KEYS = {"section", "code", "message", "retryable", "asOf"}
ARTICLE_KEYS = {"title", "publisher", "url", "publishedAt"}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Web:
    """`java -jar` as a web server on 127.0.0.1 with only the read settings; the log is kept for the leak checks."""
    logs: list[str] = []  # the whole log of every server this script started

    def __init__(self, jar):
        self.jar = jar
        self.process: subprocess.Popen | None = None
        self.lines: list[str] = []
        self.port = 0

    def start(self, grants: Path | None, root: Path | None) -> None:
        check(self.process is None, "a web server is already running")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        env = self.jar.base_env()
        if grants is not None:
            env["ZOOP_DOCUMENT_READ_GRANTS"] = str(grants)
        if root is not None:
            env["ZOOP_DOCUMENT_READ_ARTIFACT_ROOT"] = str(root)
        self.lines = []
        self.process = subprocess.Popen(self.jar.argv("--server.address=127.0.0.1", f"--server.port={self.port}"), env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        process = self.process

        def drain():
            for raw in process.stdout:
                self.lines.append(raw.decode("utf-8", "replace"))

        threading.Thread(target=drain, daemon=True).start()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and process.poll() is None and not any("Started ZoopApplication" in line for line in self.lines):
            time.sleep(0.3)
        check(process.poll() is None and any("Started ZoopApplication" in line for line in self.lines),
              "the web server did not start: " + "".join(self.lines)[-1500:])

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=30)
        time.sleep(0.3)
        imp.OUTPUT.append("".join(self.lines))
        Web.logs.append("".join(self.lines))
        self.process = None

    def get(self, path: str, headers: dict | None = None) -> tuple[int, dict, dict]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
        try:
            with OPENER.open(request, timeout=30) as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, {k.lower(): v for k, v in error.headers.items()}, json.loads(error.read())


def refuses_to_start(jar, env_extra: dict, needle: str, secret: str) -> None:
    done = subprocess.run(jar.argv("--server.address=127.0.0.1", "--server.port=0"), env={**jar.base_env(), **env_extra},
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
    output = done.stdout.decode("utf-8", "replace")
    imp.OUTPUT.append(output)
    check(done.returncode != 0 and needle in output and "Tomcat started" not in output and secret not in output,
          f"an unusable read setting must fail startup naming only the setting ({needle}): {output[-600:]}")


def tree_snapshot(root: Path) -> list:
    entries = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        entries.append((str(path.relative_to(root)), stat.S_IMODE(info.st_mode), info.st_mtime_ns, info.st_size))
    return entries


def content_snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (stat.S_IMODE(p.lstat().st_mode), sha(p.read_bytes())) for p in sorted(root.rglob("*")) if p.is_file()}


def evidence_read_steps(jar, db, world, scratch: Path, refs: dict, documents: dict, cases: dict, observe) -> dict:
    """Every real evidence row through the real HTTP route, against the state the analysis steps left behind.

    Expectations are computed here from psql, the exported texts and the read grant file, never from the Java code. `cases` names
    the analyses the scenario made: `j1` (summary whose document later got a pending request), `j4` (withheld: it made the calls), `j4b` (a
    summary served from the AI artifact cache: its calls are recorded under J4), `j9`, `j6` (document whose latest request was withheld).
    `observe()` returns the counters that a read must never move: AI service requests, worker calls and database row counts.
    """
    grants_file = scratch / "read-grants.json"
    web = Web(jar)
    article_doc = {refs[n]["documentId"]: n for n in refs}
    served = {"requests": 0}

    def save(document: dict | None, raw: str | None = None) -> None:
        if document is None and raw is None:
            grants_file.unlink(missing_ok=True)
            return
        temporary = scratch / "next-read-grants.json"
        temporary.write_text(raw if raw is not None else json.dumps(document), encoding="utf-8")
        temporary.replace(grants_file)

    def grants(**changes) -> dict:
        document = flat_grants()
        document["grants"][0].update(changes)
        return document

    def rows() -> list[dict]:
        return db.rows("SELECT e.id, e.article_id, e.article_version, e.quote, e.start_offset, e.end_offset, e.verification_artifact_id, "
                       "d.id AS analysis_id, d.ai_job_id, d.result_version, d.result FROM evidence e "
                       "JOIN document_analyses d ON d.exact_receipt_id = e.verification_artifact_id ORDER BY e.id")

    def latest() -> dict:
        found = db.rows("SELECT DISTINCT ON (article_id, article_version) id, article_id, article_version, status, result_version, result "
                        "FROM document_analyses WHERE stage = 'summary' ORDER BY article_id, article_version, request_no DESC")
        return {(r["article_id"], r["article_version"]): r for r in found}

    def versions() -> dict:
        found = db.rows("SELECT article_id, version, title, publisher, url, publication_precision, "
                        "to_char(published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS published_at FROM article_versions")
        return {(r["article_id"], r["version"]): r for r in found}

    def get(evidence_id: str, query: str = "", request_id: str | None = None) -> tuple[int, dict, dict]:
        served["requests"] += 1
        return web.get(f"/api/v1/evidence/{evidence_id}{query}", {"X-Request-ID": request_id} if request_id else None)

    def error(status: int, headers: dict, body: dict, http_status: int, code: str, message: str) -> None:
        check(status == http_status and set(body) == {"error"} and set(body["error"]) == {"code", "message", "requestId", "retryable"}
              and body["error"]["code"] == code and body["error"]["requestId"] == headers.get("x-request-id"),
              f"{message}: expected {http_status} {code}, got {status} {json.dumps(body)[:300]}")

    def expect_each(label: str, http_status: int, code: str | None = None, only: set | None = None) -> None:
        """Every evidence row (or the `only` ids) answers `http_status`; a 200 is verified in full by `verify`."""
        context = (versions(), latest()) if http_status == 200 else None
        for ev in rows():
            if only is not None and ev["id"] not in only:
                continue
            status, headers, body = get(ev["id"], request_id=f"smoke-{ev['id'][3:11]}")
            if http_status == 200:
                verify(label, ev, status, headers, body, context=context)
            else:
                error(status, headers, body, http_status, code, f"{label}: {ev['id']}")

    def verify(label: str, ev: dict, status: int, headers: dict, body: dict, query: str = "", context=None) -> None:
        known_versions, known_latest = context or (versions(), latest())
        check(status == 200, f"{label}: {ev['id']} answered {status}: {json.dumps(body)[:300]}")
        number = article_doc[ev["article_id"]]
        text = documents[number]["text"]
        check(set(body) == EVIDENCE_KEYS and set(body["metadata"]) == METADATA_KEYS and set(body["article"]) == ARTICLE_KEYS
              and all(set(f) == FAILURE_KEYS for f in body["metadata"]["failures"]), f"{label}: keys {sorted(body)}")
        check(body["id"] == ev["id"] and body["quote"] == ev["quote"] == text[ev["start_offset"]:ev["end_offset"]]
              and (body["start"], body["end"]) == (ev["start_offset"], ev["end_offset"]),
              f"{label}: the quote is not the Python code point slice of the exported text")
        check(body["quoteVerified"] is True
              and (body["articleId"], body["articleVersion"], body["documentVersion"]) == (ev["article_id"], ev["article_version"], ev["article_version"])
              and body["eventIds"] == [] and body["sentiment"] is None and body["analysisStatus"] is None, f"{label}: base fields {body}")
        version = known_versions[(ev["article_id"], ev["article_version"])]
        published = None if version["publication_precision"] != "datetime" else version["published_at"]
        check(body["article"] == {"title": version["title"], "publisher": version["publisher"], "url": version["url"],
                                  "publishedAt": published}, f"{label}: article {body['article']} vs {version}")
        meta = body["metadata"]
        check(meta["source"] == "document-analysis" and meta["graphVersion"] is None and meta["partial"] is True
              and meta["requestId"] == headers.get("x-request-id") and meta["failures"][0] == {
                  "section": "eventIds", "code": "SOURCE_UNAVAILABLE", "message": meta["failures"][0]["message"], "retryable": False,
                  "asOf": None} and len(meta["failures"]) == (2 if "companyId=SYNTH-A" in query else 1), f"{label}: metadata {meta}")
        as_of = dt.datetime.fromisoformat(meta["asOf"].replace("Z", "+00:00"))
        check(abs((dt.datetime.now(dt.timezone.utc) - as_of).total_seconds()) < 600, f"{label}: asOf {meta['asOf']} is not the request time")
        newest = known_latest[(ev["article_id"], ev["article_version"])]
        if newest["status"] == "available":
            check(body["documentSummary"] == newest["result"] and body["resultVersion"] == newest["result_version"]
                  and body["analysisProvenance"] == newest["result"]["provenance"],
                  f"{label}: documentSummary is not the latest available result")
            if newest["id"] == ev["analysis_id"]:
                check(ev["id"] in [c["evidenceId"] for c in body["documentSummary"]["citations"]], f"{label}: the summary does not cite its evidence")
        else:
            check(body["documentSummary"] is None and body["resultVersion"] is None and body["analysisProvenance"] is None,
                  f"{label}: a {newest['status']} latest request must not fall back to an older summary")
        text_dump = json.dumps(body, ensure_ascii=False)
        check(str(world.root) not in text_dump and "artifact-root:" not in text_dump and "storage_uri" not in text_dump,
              f"{label}: the body names a storage location")

    def database_digest() -> str:
        return db.run("SELECT md5(concat_ws('|', "
                      "(SELECT coalesce(string_agg(t::text, '|' ORDER BY t.id), '') FROM document_analyses t), "
                      "(SELECT coalesce(string_agg(t::text, '|' ORDER BY t.id), '') FROM ai_executions t), "
                      "(SELECT coalesce(string_agg(t::text, '|' ORDER BY t.id), '') FROM evidence t), "
                      "(SELECT coalesce(string_agg(t::text, '|' ORDER BY t.id), '') FROM artifacts t), "
                      "(SELECT coalesce(string_agg(t::text, '|' ORDER BY t.id), '') FROM articles t)))")

    def table_writes() -> int:
        time.sleep(3)  # the statistics collector reports on idle backends after about a second
        return db.scalar("SELECT coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_user_tables")

    j1, j4b, j9, j6 = cases["j1"], cases["j4b"], cases["j9"], cases["j6"]
    ids = {name: [e["id"] for e in rows() if e["analysis_id"] == cases[name]["analysisId"]] for name in ("j1", "j4b", "j6", "j9")}
    check(all(len(v) == 2 for v in ids.values()), f"every case summary must own two evidence rows: {ids}")
    check(len(rows()) == 10, f"expected ten stored evidence rows, got {len(rows())}")
    cached_ids = set(ids["j4b"])
    exact = lambda case: world.artifacts / "exact_receipt" / f"exact-{case['analysisId']}.json"  # noqa: E731
    save(flat_grants())
    try:
        # ---- A: every stored evidence row, with the artifact root --------------------------------------------------------------
        label = step("evidence read: the built jar as a real web server; EVERY stored evidence row (incl. the cache-served J4b) answers 200 with a verified shape")
        web.start(grants_file, world.artifacts)
        baseline, files_before, db_before, contents = observe(), tree_snapshot(world.artifacts), database_digest(), content_snapshot(world.artifacts)
        writes_before = table_writes()
        check(world.artifacts.joinpath(".document-import.lock").exists(), f"{label}: the analysis runs must have created the lock file")
        expect_each(label, 200)
        check(len(cached_ids & {e["id"] for e in rows()}) == 2 and db.rows(
            f"SELECT 1 FROM ai_executions WHERE ai_job_id = '{j4b['aiJobId']}'") == [], f"{label}: J4b must be the cache-served case")

        label = step("evidence read: public (no credential), X-Request-ID echoed or generated, JSON content type, unknown and malformed ids")
        first = ids["j1"][0]
        status, headers, body = get(first, request_id="smoke-echo-1")
        check(status == 200 and headers.get("x-request-id") == "smoke-echo-1" and body["metadata"]["requestId"] == "smoke-echo-1"
              and headers.get("content-type", "").startswith("application/json"), f"{label}: {status} {headers}")
        status, headers, body = get(first)
        check(status == 200 and headers.get("x-request-id") and body["metadata"]["requestId"] == headers["x-request-id"], f"{label}: generated id")
        for bad in ("ev-" + "0" * 64, "ev-" + "0" * 63, "EV-" + "0" * 64, "nope", "ev-" + "g" * 64):
            status, headers, body = get(bad)
            error(status, headers, body, 404, "RESOURCE_NOT_FOUND", f"{label}: {bad}")

        label = step("evidence read: pinned round/graphVersion/asOf are 409 VERSION_UNAVAILABLE (never the latest), blank or offset-less values 422")
        for query in ("?round=brf-2026-09-17-morning", "?graphVersion=gv-1", "?asOf=2026-10-15T00:00:00Z", "?asOf=2026-10-15T09%3A00%3A00%2B09%3A00"):
            status, headers, body = get(first, query)
            error(status, headers, body, 409, "VERSION_UNAVAILABLE", f"{label}: {query}")
            check(body["error"]["retryable"] is False, f"{label}: {query} is not retryable")
        for query in ("?round=", "?graphVersion=", "?asOf=", "?companyId=", "?asOf=2026-10-15T00:00:00", "?asOf=yesterday"):
            status, headers, body = get(first, query)
            error(status, headers, body, 422, "INVALID_REQUEST", f"{label}: {query}")

        label = step("evidence read: companyId has no approved link (no graph): a known company adds a failed sentiment section and NEVER a sentiment; unknown 404")
        status, headers, body = get(first, "?companyId=SYNTH-A")
        verify(label, next(e for e in rows() if e["id"] == first), status, headers, body, "?companyId=SYNTH-A")
        check([f["section"] for f in body["metadata"]["failures"]] == ["eventIds", "sentiment"] and body["sentiment"] is None
              and all(f["retryable"] is False and f["code"] == "SOURCE_UNAVAILABLE" for f in body["metadata"]["failures"]),
              f"{label}: {body['metadata']}")
        sentiment_rows = db.scalar("SELECT count(*) FROM document_analyses WHERE stage = 'sentiment' AND status = 'available'")
        check(sentiment_rows >= 1, f"{label}: the scenario must hold available sentiment rows that the read still never serves")
        status, headers, body = get(first, "?companyId=NO-SUCH")
        error(status, headers, body, 404, "RESOURCE_NOT_FOUND", label)

        label = step("evidence read: GET changed nothing - no AI request, no worker call, no row, no file, no lock file, no table write")
        check(table_writes() == writes_before, f"{label}: PostgreSQL counted writes while only GETs ran")
        check(observe() == baseline and database_digest() == db_before, f"{label}: counters or rows changed: {observe()} vs {baseline}")
        check(tree_snapshot(world.artifacts) == files_before and content_snapshot(world.artifacts) == contents,
              f"{label}: the artifact root changed")

        # ---- B: the current grant is judged on every request ----------------------------------------------------------------------
        label = step("evidence read: a grant that changes while the server runs withholds EVERY evidence at the next request (404 EVIDENCE_UNAVAILABLE), no reason on the wire")
        past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
        variants = {
            "disabled": grants(enabled=False), "rights unknown": grants(rights="unknown"), "expired": grants(expiresAt=past),
            "quote-display removed": grants(allowedOperations=["read", "store", "model-send"]),
            "new revision": grants(revision="rev-2"), "source changed": grants(sourceId="other-source"),
            "recipient removed": grants(recipients=["someone-else"]), "no recipients": grants(recipients=[]),
            "purpose removed": grants(purposes=["document-sentiment", "semantic-verification"]),
            "verifier purpose removed": grants(purposes=["document-summary", "document-sentiment"]),
            "other grant id": grants(grantId="other-grant"),
        }
        for name, document in variants.items():
            save(document)
            expect_each(f"{label} [{name}]", 404, "EVIDENCE_UNAVAILABLE")
            save(flat_grants())
            status, headers, body = get(ids["j1"][0])
            check(status == 200, f"{label} [{name}]: restoring the grant did not restore the evidence ({status})")
        save(grants(revision="rev-2"))
        status, headers, body = get(ids["j1"][0])
        check(status == 404 and "rev-2" not in json.dumps(body) and "grant" not in json.dumps(body).lower(),
              f"{label}: the denial reason leaked: {body}")
        save(flat_grants())

        label = step("evidence read: an unreadable, invalid or missing registry is 503 SOURCE_UNAVAILABLE (never open, never empty), recovery is immediate")
        for name, raw in (("truncated", "{"), ("wrong schema", json.dumps({"schemaVersion": "other", "grants": []})),
                          ("duplicate key", '{"schemaVersion":"zoop-ai-s1-1","grants":[],"grants":[]}')):
            save(None, raw)
            expect_each(f"{label} [{name}]", 503, "SOURCE_UNAVAILABLE")
        save(None)
        expect_each(f"{label} [missing]", 503, "SOURCE_UNAVAILABLE")
        status, headers, body = get(first)
        check(body["error"]["retryable"] is True, f"{label}: SOURCE_UNAVAILABLE must be retryable")
        save(flat_grants())
        expect_each(f"{label} [restored]", 200)

        # ---- C: the current document state ------------------------------------------------------------------------------------------
        doc1 = refs[1]["documentId"]
        doc1_ids = {e["id"] for e in rows() if e["article_id"] == doc1}
        label = step("evidence read: private article, then a moved current version, then a newer pending request - each judged at the next request")
        db.run(f"UPDATE articles SET access_status = 'private' WHERE id = '{doc1}'")
        try:
            expect_each(f"{label} [private]", 404, "EVIDENCE_UNAVAILABLE", only=doc1_ids)
            expect_each(f"{label} [private: other documents]", 200, only={e["id"] for e in rows()} - doc1_ids)
        finally:
            db.run(f"UPDATE articles SET access_status = 'available' WHERE id = '{doc1}'")
        expect_each(f"{label} [restored]", 200)
        version1 = refs[1]["documentVersion"]
        db.run("INSERT INTO article_versions (article_id, version, publication_precision, text_artifact_id, collected_at) "
               f"SELECT article_id, 'smoke-next', 'unknown', text_artifact_id, now() FROM article_versions "
               f"WHERE article_id = '{doc1}' AND version = '{version1}'")
        db.run(f"UPDATE articles SET current_version = 'smoke-next' WHERE id = '{doc1}'")
        try:
            expect_each(f"{label} [pointer moved]", 404, "EVIDENCE_UNAVAILABLE", only=doc1_ids)
        finally:
            db.run(f"UPDATE articles SET current_version = '{version1}' WHERE id = '{doc1}'")
            db.run(f"DELETE FROM article_versions WHERE article_id = '{doc1}' AND version = 'smoke-next'")
        expect_each(f"{label} [pointer back]", 200)
        doc2 = refs[2]["documentId"]
        doc2_version = refs[2]["documentVersion"]
        doc2_ids = {e["id"] for e in rows() if e["article_id"] == doc2}
        owner9 = db.rows(f"SELECT grant_reference, grant_revision FROM document_analyses WHERE id = '{j9['analysisId']}'")[0]
        db.run("INSERT INTO document_analyses (id, article_id, article_version, stage, company_id, request_no, status, grant_reference, "
               "grant_revision, grant_checked_at, ai_job_id, created_at, updated_at) VALUES "
               f"('smoke-pending', '{doc2}', '{doc2_version}', 'summary', NULL, "
               f"(SELECT max(request_no) + 1 FROM document_analyses WHERE article_id = '{doc2}' AND stage = 'summary'), 'pending', "
               f"'{owner9['grant_reference']}', '{owner9['grant_revision']}', now(), 'smoke-read-pending', now(), now())")
        try:
            for evidence_id in sorted(doc2_ids):
                status, headers, body = get(evidence_id)
                check(status == 200 and body["documentSummary"] is None and body["resultVersion"] is None
                      and body["analysisProvenance"] is None and body["quote"], f"{label} [pending]: {status} {json.dumps(body)[:300]}")
        finally:
            db.run("DELETE FROM document_analyses WHERE id = 'smoke-pending'")
        expect_each(f"{label} [pending removed]", 200)
        doc4_ids = {e["id"] for e in rows() if e["article_id"] == refs[4]["documentId"]}
        for evidence_id in sorted(doc4_ids):
            status, headers, body = get(evidence_id)
            check(status == 200 and body["documentSummary"] is None, f"{label}: J6's evidence while J11 (withheld) is the latest request")

        # ---- D: the cache-served summary (J4b) --------------------------------------------------------------------------------------
        label = step("evidence read: J4b (served from the artifact cache, calls recorded under the withheld J4) is proven by ONE verified receipt read")
        receipt = exact(j4b)
        original = receipt.read_bytes()
        check(stat.S_IMODE(receipt.stat().st_mode) == 0o600 and json.loads(original)["creatorJobId"] == cases["j4"]["aiJobId"],
              f"{label}: the receipt names the creator job")
        receipt.rename(receipt.with_name("exact-moved.json"))
        try:
            expect_each(f"{label} [receipt file missing]", 404, "EVIDENCE_UNAVAILABLE", only=cached_ids)
            expect_each(f"{label} [other summaries unaffected]", 200, only=set(ids["j1"]))
        finally:
            receipt.with_name("exact-moved.json").rename(receipt)
        receipt.write_bytes(original.replace(b'"documentVersion"', b'"documentVersioN"'))
        try:
            expect_each(f"{label} [receipt bytes differ from the registered hash]", 404, "EVIDENCE_UNAVAILABLE", only=cached_ids)
        finally:
            receipt.write_bytes(original)
        receipt.chmod(0o644)
        try:
            expect_each(f"{label} [receipt file insecure]", 503, "SOURCE_UNAVAILABLE", only=cached_ids)
            expect_each(f"{label} [insecure receipt, other summaries]", 200, only=set(ids["j1"]))
        finally:
            receipt.chmod(0o600)
        expect_each(f"{label} [receipt restored]", 200, only=cached_ids)
        creator = cases["j4"]
        db.run("CREATE TABLE zz_smoke_exec AS SELECT * FROM ai_executions "
               f"WHERE ai_job_id = '{creator['aiJobId']}' AND document_analysis_id = '{creator['analysisId']}'")
        check(db.scalar("SELECT count(*) FROM zz_smoke_exec") == 2, f"{label}: the creator's two executions")
        db.run(f"DELETE FROM ai_executions WHERE ai_job_id = '{creator['aiJobId']}'")
        try:
            expect_each(f"{label} [creator executions missing]", 404, "EVIDENCE_UNAVAILABLE", only=cached_ids)
        finally:
            db.run("INSERT INTO ai_executions SELECT * FROM zz_smoke_exec")
            db.run("DROP TABLE zz_smoke_exec")
        expect_each(f"{label} [creator executions restored]", 200, only=cached_ids)

        label = step("evidence read: an operator holding the artifact-store lock does not block any read (the proof takes no lock)")
        descriptor = os.open(world.artifacts / ".document-import.lock", os.O_RDWR)
        try:
            fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            expect_each(f"{label} [lock held]", 200)
        finally:
            os.close(descriptor)

        label = step("evidence read: web server stopped; J4b without a configured artifact root is 503 (retryable) while normal summaries stay 200")
        files_before_stop = tree_snapshot(world.artifacts)
        web.stop()
        web.start(grants_file, None)
        expect_each(f"{label} [no root: cache-served]", 503, "SOURCE_UNAVAILABLE", only=cached_ids)
        expect_each(f"{label} [no root: normal]", 200, only={e["id"] for e in rows()} - cached_ids)
        web.stop()
        web.start(None, world.artifacts)
        expect_each(f"{label} [no grants]", 503, "SOURCE_UNAVAILABLE")
        web.stop()
        check(tree_snapshot(world.artifacts) == files_before_stop, f"{label}: starting the read server changed the artifact root")

        label = step("evidence read: an unusable read setting refuses to start and names only the setting, never its value")
        secret_dir = scratch / "secret-location-xyz"
        refuses_to_start(jar, {"ZOOP_DOCUMENT_READ_GRANTS": "relative/grants.json"}, "zoop.document-read.grants", "relative/grants.json")
        refuses_to_start(jar, {"ZOOP_DOCUMENT_READ_GRANTS": str(secret_dir / "grants.json")}, "zoop.document-read.grants", "secret-location-xyz")
        refuses_to_start(jar, {"ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(secret_dir)}, "zoop.document-read.artifact-root", "secret-location-xyz")
        check(not secret_dir.exists() and tree_snapshot(world.artifacts) == files_before_stop, f"{label}: a refused start created something")

        label = step("evidence read: final - no AI request, no worker call, no row or file changed by any read; grants file and server are cleaned up")
        check(observe() == baseline and database_digest() == db_before, f"{label}: counters or rows differ from before the reads")
        check(content_snapshot(world.artifacts) == contents, f"{label}: artifact content changed")
        server_logs = "\n".join(Web.logs)
        check(server_logs and all(e["quote"] not in server_logs for e in rows()) and str(world.root) not in server_logs
              and str(scratch) not in server_logs and (len(db.password) < 8 or db.password not in server_logs), f"{label}: a server log carries a quote, a path or the password")
        return {"evidenceRequests": served["requests"]}
    finally:
        web.stop()
        grants_file.unlink(missing_ok=True)


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
    parser.add_argument("--with-evidence-read", action=argparse.BooleanOptionalAction, default=True,
                        help="after the analysis steps, exercise GET /api/v1/evidence/{id} against the built jar as a real web server "
                             "(default: on; --no-with-evidence-read keeps the analysis-only run)")
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

        # ---- 10f: the public evidence read over everything the steps above created ------------------------------------------------
        evidence_summary = {}
        if args.with_evidence_read:
            read_before = (counts(), len(worker_calls()), len(proxy.requests), db.scalar("SELECT count(*) FROM ai_executions"))
            evidence_summary = evidence_read_steps(
                jar, db, world, scratch, refs, documents,
                {"j1": j1, "j4": j4, "j4b": j4b, "j6": j6, "j9": j9},
                lambda: {"counts": counts(), "workerCalls": len(worker_calls()), "aiRequests": len(proxy.requests),
                         "serviceJobs": sorted(c["job_id"] for c in worker_calls())})
            check(read_before == (counts(), len(worker_calls()), len(proxy.requests), db.scalar("SELECT count(*) FROM ai_executions")),
                  "the evidence read steps changed the analysis counts that the final checks rely on")

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
                          "jarRuns": jar.counter, "ledgerReadOnly": True, "evidenceRead": bool(evidence_summary), **evidence_summary}))
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
