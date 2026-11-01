"""Synthetic operating CLI smoke. --long-job exercises a real native job exceeding 300 seconds over loopback."""
from __future__ import annotations

import argparse
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import httpx

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE), str(PIPELINE / "src")]

from scripts.collection_smoke import CollectionKit, NEWS
from scripts.extraction_smoke import CATALOGUE, FAKE_KEYS, Kit, LIVE_PROMPT, Q3, Q3B, chat_reply, page, simulate
from scripts.ingestion_smoke import json_bytes, ownership_env, sha
from zoop_ai_pipeline import extraction, handoff_cli, operating, operating_collection
from zoop_ai_pipeline.collection_contracts import declared_published
from zoop_ai_pipeline.graph_projection import Source, digest, review_state
from zoop_ai_pipeline.handoff import HandoffPaths, load_operator
from zoop_ai_pipeline.handoff_contracts import POLICY, content_digest
from zoop_ai_pipeline.live_budget import Budget
from zoop_ai_pipeline.live_funding import MODE, SCHEMA, STAGES
from zoop_ai_pipeline.operating import CONFIG, MANIFEST, Owner


def policy(lifecycle=None) -> dict:
    return {"schemaVersion": SCHEMA, "mode": MODE, "operationId": "synthetic-operation",
            "accounts": {"openai-compatible": "synthetic-generation-account", "typesafe-native": "synthetic-verifier-account"},
            "lifecycle": lifecycle if lifecycle is not None else {"kind": "explicit-stop"}, "requestTimeoutSeconds": 300,
            "drainSeconds": 600, "cleanupSeconds": 2, "minIntervalMilliseconds": 1}


def fixture(root: Path, endpoint: str):
    kit = Kit(root / "inputs")
    first, incoming = kit.ingest("operating", [{"supplier": "s1", "html": page(Q3, "합성기업은 합성상대에 반도체를 공급한다.")},
        {"supplier": "s2", "html": page(Q3B, "합성기업은 합성상대에 반도체를 공급한다.", "계약은 합성기업의 매출 증가에 도움이 된다.")}])
    article = kit.article(first)
    event = kit.event("snapshot-event", [(first, kit.mention(article, "old-mention", [kit.evidence(article, Q3)]))])
    config = {"schemaVersion": CONFIG, "policy": policy(), "ledgerDirectory": str(root / "metering"),
              "stateDirectory": str(root / "native"),
              "runtime": {"model": "gpt-6-luna", "effort": "high", "maxOutputTokens": 24000,
                          "openaiEndpoint": endpoint, "verifierEndpoint": endpoint, "verifierModel": "jev-1.14.0"}}
    unit = {"setId": "set-1", "extraction": kit.submit_live("native-s2-1", incoming, [event], topic=True), "relationJobId": "native-s3-1",
            "stageAllowances": {stage: 10 for stage in STAGES}, "ingestionStateDirectory": str(kit.root / "ingestion"),
            "sources": str(kit.registry_path)}
    return kit, config, {"schemaVersion": MANIFEST, "sets": [unit]}


def response(body):
    if "questions" in body:
        answers = {}
        for key, question in body["questions"].items():
            options = list(question["criteria"])
            winner = "supported" if "supported" in options else "positive"
            answers[key] = {"type": "choice", "choice": winner, "confidence": 0.99,
                            "probabilities": {k: 0.99 if k == winner else 0.01 / (len(options) - 1) for k in options}}
        return {"model": "jev-1.14.0", "answers": answers, "usage": {"input_tokens": 1000, "output_tokens": 0}}
    projection = json.loads(body["messages"][1]["content"])
    stage, value = projection["stage"], projection["input"]
    if stage in {"extract", "compare", "topic"}:
        return simulate(body)
    document = value["documents"][0]
    quote = "합성기업은 합성상대에 반도체를 공급한다."
    source = next(s for s in projection["sources"] if all(s[k] == document[k] for k in ("documentId", "documentVersion")))
    citation = {"segmentId": next(s["segmentId"] for s in source["segments"] if s["segmentId"] is not None and quote in s["text"])}
    if stage == "relation":
        answer = {"schemaVersion": "zoop-relation-response-1", "producerVersion": "zoop-relation-producer-1", "relations": [{
            "type": "SUPPLIES", "subject": {"kind": "company", "ref": "SYNTH-1"}, "object": {"kind": "company", "ref": "SYNTH-2"},
            "connection": "direct", "businessScope": None, "productScope": "반도체", "validity": {"from": None, "until": None, "citations": []},
            "countries": [], "reason": "authored synthetic supply", "citations": [citation], "path": []}]}
    else:
        assert stage == "impact"
        answer = {"schemaVersion": "zoop-impact-response-1", "producerVersion": "zoop-impact-producer-1", "impacts": [{
            "impactedCompanyId": "SYNTH-1", "direction": "positive", "reason": "authored synthetic effect", "supporting": [citation],
            "opposing": [], "limitations": "synthetic fixture"}]}
    return chat_reply(json.dumps({**answer, "citationFormat": projection["citationFormat"]}, ensure_ascii=False))


class Provider:
    def __init__(self, delay=0, fault=None):
        self.stages = []
        self.delay = delay
        self.fault = fault
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stage = ("verify-impact" if "target" in body["questions"] else "verify-relation") if "questions" in body else json.loads(body["messages"][1]["content"])["stage"]
                provider.stages.append(stage)
                if stage in {"extract", "compare"}:
                    time.sleep(provider.delay)
                answer = response(body)
                if provider.fault == "usage" and stage == "extract":
                    answer.pop("usage")
                if provider.fault == "verifier":
                    if stage == "relation":
                        parsed = json.loads(answer["choices"][0]["message"]["content"])
                        second = json.loads(json.dumps(parsed["relations"][0]))
                        second["productScope"] = "another-synthetic-product"
                        parsed["relations"].append(second)
                        answer["choices"][0]["message"]["content"] = json.dumps(parsed)
                    elif stage == "verify-relation":
                        answer["answers"] = {}
                raw = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def smoke(root: Path, long_job: bool = False):
    with Provider(delay=151 if long_job else 0) as provider:
        kit, config, inputs = fixture(root, provider.endpoint)
        config_path, manifest_path = root / "config.json", root / "manifest.json"
        config_path.write_text(json.dumps(config))
        manifest_path.write_text(json.dumps(inputs))
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(PIPELINE / "src"), "PYTHONDONTWRITEBYTECODE": "1",
               "ZOOP_AI_PIPELINE_LIVE_ENABLED": "1", **FAKE_KEYS}
        for name in ("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"):
            if name in os.environ:
                env[name] = os.environ[name]

        def cli(command, *args, expected=0):
            child = subprocess.run([sys.executable, "-m", "zoop_ai_pipeline.operating", command, "--config", str(config_path), *args],
                                   env=env, capture_output=True, timeout=480)
            assert child.returncode == expected, (command, child.returncode, child.stdout.decode(), child.stderr.decode())
            return json.loads(child.stdout)

        initialized = cli("init")
        owner = Owner(config)
        kit.allow_model_send(owner.runtime(inputs["sets"][0], "offline"), STAGES)
        registered = cli("register", "--manifest", str(manifest_path))
        assert registered["metering"]["calls"] == 0
        assert cli("register", "--manifest", str(manifest_path))["metering"]["calls"] == 0
        start = time.monotonic()
        done = cli("run", "--max-sets", "1")
        elapsed = time.monotonic() - start
        assert done["status"] == "complete" and done["sets"][0]["s2"]["state"] == done["sets"][0]["s3"]["state"] == "ready", done
        assert provider.stages == ["extract", "compare", "topic", "relation", "verify-relation", "impact", "verify-impact"], provider.stages
        assert done["metering"]["chargedUsd"] == "0.002409000", done["metering"]
        again = cli("run", "--max-sets", "1")
        assert again["sets"] == [] and again["metering"]["calls"] == 7
        status = cli("status")
        assert status["reconciliation"] == {"monetaryWithoutNative": [], "nativeWithoutMonetary": [], "receiptsAwaitingNativeRecovery": []}
        assert status["metering"]["ledgerId"] == initialized["metering"]["ledgerId"]
        assert set(status["monetaryAttempts"]) == set(status["nativeAttempts"]) and len(status["nativeAttempts"]) == 7
        if long_job:
            assert elapsed > 300
        return {"status": "passed", "network": "127.0.0.1 only", "sourceKind": "synthetic", "externalProviderCalls": 0,
                "elapsedJobSeconds": elapsed, "stages": provider.stages, "metering": status["metering"], "reconciliation": status["reconciliation"]}


def fault_smoke(root: Path):
    checks = []
    for mode in ("pause", "usage", "verifier", "registration", "contention", "contention-exhaust"):
        case = root / mode
        case.mkdir()
        with Provider(fault=mode) as provider:
            kit, config, inputs = fixture(case, provider.endpoint)
            if mode == "pause":
                config["policy"]["minIntervalMilliseconds"] = 1000
            if mode == "registration":
                config["policy"]["lifecycle"] = {"kind": "frontier", "setIds": ["set-1", "set-2"]}
            config_path, manifest_path = case / "config.json", case / "manifest.json"
            config_path.write_text(json.dumps(config))
            manifest_path.write_text(json.dumps(inputs))
            env = {"PATH": os.defpath, "PYTHONPATH": str(PIPELINE / "src"), "PYTHONDONTWRITEBYTECODE": "1",
                   "ZOOP_AI_PIPELINE_LIVE_ENABLED": "1", **FAKE_KEYS}
            for name in ("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"):
                if name in os.environ:
                    env[name] = os.environ[name]

            def command(name, *args):
                return [sys.executable, "-m", "zoop_ai_pipeline.operating", name, "--config", str(config_path), *args]

            def cli(name, *args, expected=0):
                result = subprocess.run(command(name, *args), env=env, capture_output=True, timeout=30)
                assert result.returncode == expected, (name, result.stdout.decode(), result.stderr.decode())
                return json.loads(result.stdout)

            cli("init")
            owner = Owner(config)
            kit.allow_model_send(owner.runtime(inputs["sets"][0], "offline"), STAGES)
            if mode == "registration":
                bad = json.loads(json.dumps(inputs))
                bad["sets"][0]["extraction"]["incoming"]["documentId"] = "doc-not-present"
                manifest_path.write_text(json.dumps(bad))
                assert cli("register", "--manifest", str(manifest_path), expected=2)["error"] == "observation_not_found"
                assert cli("status")["metering"]["sets"]["admitted"] == 0
                assert cli("run", "--max-sets", "1")["status"] == "batch-complete"
                manifest_path.write_text(json.dumps(inputs))
            cli("register", "--manifest", str(manifest_path))
            if mode in {"contention", "contention-exhaust"}:
                native_marker, writer_marker = case / "native-intent", case / "control-writer"
                run_code = (
                    "import runpy,time\nfrom pathlib import Path\n"
                    "from zoop_ai_pipeline import live_budget\nfrom zoop_ai_pipeline.extraction import Extractor\n"
                    + ("live_budget.BUSY_SECONDS=0.05\n" if mode == "contention-exhaust" else "")
                    + "original=Extractor._reserve\nseen=[]\n"
                    "def reserve(self,*args,**kwargs):\n attempt=original(self,*args,**kwargs)\n"
                    " if args[2]=='extract' and not seen:\n  seen.append(attempt)\n"
                    f"  Path({str(native_marker)!r}).write_text(attempt)\n  until=time.monotonic()+10\n"
                    f"  while not Path({str(writer_marker)!r}).exists():\n"
                    "   if time.monotonic()>until: raise TimeoutError('control boundary')\n   time.sleep(0.005)\n"
                    " return attempt\nExtractor._reserve=reserve\n"
                    "runpy.run_module('zoop_ai_pipeline.operating',run_name='__main__')"
                )
                pause_code = (
                    "import runpy,time\nfrom pathlib import Path\nfrom contextlib import contextmanager\n"
                    "from zoop_ai_pipeline.live_budget import Budget\noriginal=Budget._tx\n"
                    "@contextmanager\ndef held(self,**options):\n with original(self,**options) as db:\n"
                    "  if not options.get('readonly',False):\n"
                    f"   Path({str(writer_marker)!r}).write_text('held')\n   time.sleep(0.2)\n"
                    "  yield db\nBudget._tx=held\n"
                    "runpy.run_module('zoop_ai_pipeline.operating',run_name='__main__')"
                )
                child = subprocess.Popen([sys.executable, "-c", run_code, *command("run", "--max-sets", "1")[3:]],
                                         env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 10
                    while not native_marker.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    assert native_marker.is_file(), "native intent boundary not reached"
                    paused = subprocess.run([sys.executable, "-c", pause_code, *command("pause", "--reason", "contended-maintenance")[3:]],
                                            env=env, capture_output=True, timeout=10)
                    assert paused.returncode == 0, (paused.stdout.decode(), paused.stderr.decode())
                    stdout, stderr = child.communicate(timeout=10)
                    assert child.returncode == 2, (stdout, stderr)
                    result = json.loads(stdout)
                    if "error" in result:
                        assert result["error"] == "operating_ledger_busy"
                    else:
                        assert result["status"] == "blocked"
                    assert provider.stages == []
                    attempt = native_marker.read_text()
                    assert cli("status")["nativeAttempts"][attempt]["state"] == "deferred"
                    cli("resume", "--reason", "maintenance-complete")
                    assert cli("run", "--max-sets", "1")["status"] == "complete"
                    status = cli("status")
                    assert status["nativeAttempts"][attempt]["state"] == "received"
                    assert status["monetaryAttempts"][attempt]["state"] == "settled"
                    assert len(provider.stages) == 7
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=5)
            elif mode == "pause":
                child = subprocess.Popen(command("run", "--max-sets", "1"), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 10
                    attempts = {}
                    while time.monotonic() < deadline:
                        attempts = owner.budget.attempts()
                        if any(a["stage"] == "compare" and not a["dispatched"] for a in attempts.values()):
                            break
                        time.sleep(0.01)
                    else:
                        raise AssertionError("compare pacing boundary not reached")
                    cli("pause", "--reason", "maintenance")
                    stdout, stderr = child.communicate(timeout=10)
                    assert child.returncode == 2 and json.loads(stdout)["status"] == "blocked", (stdout, stderr)
                    assert provider.stages == ["extract"]
                    cli("resume", "--reason", "maintenance-complete")
                    assert cli("run", "--max-sets", "1")["status"] == "complete"
                    assert set(attempts) <= set(cli("status")["nativeAttempts"])
                    assert len(provider.stages) == 7
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=5)
            elif mode == "usage":
                stopping = cli("stop", "--reason", "drain")
                stopped = cli("run", "--max-sets", "1", expected=2)
                assert stopped["metering"]["control"]["state"] == "paused"
                assert provider.stages == ["extract"]
                resumed = cli("resume", "--reason", "usage-reviewed")
                assert resumed["metering"]["control"]["state"] == "stopping"
                assert resumed["metering"]["control"]["drainUntil"] == stopping["metering"]["control"]["drainUntil"]
                assert cli("run", "--max-sets", "1")["status"] == "complete"
                assert len(provider.stages) == 7
            elif mode == "verifier":
                stopped = cli("run", "--max-sets", "1", expected=2)
                assert provider.stages == ["extract", "compare", "topic", "relation", "verify-relation"]
                assert stopped["metering"]["control"]["state"] == "paused"
            else:
                assert cli("run", "--max-sets", "1")["status"] == "batch-complete"
            checks.append({"case": mode, "status": "passed", "stages": list(provider.stages)})
    return checks


STAMP = "2026-10-14T09:00:00+00:00"


def authored_collection(kit, name="batch", *, bodies=(NEWS, NEWS, NEWS), source_id="synthetic-source"):
    """Write synthetic receipt/body bytes directly; this fixture performs no acquisition."""
    base = kit.inputs / "collections" / name
    (base / "bodies").mkdir(parents=True)
    (base / "receipts").mkdir()
    source = next(source for source in kit.registry["sources"] if source["sourceId"] == source_id)
    grant = source["grant"]
    items, targets, documents = [], [], {}
    published = [None, "2026-10-14", "2026-10-14T09:30:00"]
    for index, body in enumerate(bodies):
        candidate, url = f"c-{index}", f"http://127.0.0.1/news/{index}"
        body_hash = sha(body)
        (base / "bodies" / f"{body_hash}.bin").write_bytes(body)
        receipt = {"schemaVersion": "zoop-collection-receipt-1", "collectionId": name, "sourceId": source_id,
            "scopeId": "body", "candidateId": candidate, "grantId": grant["grantId"], "grantRevision": grant["revision"],
            "requestedUrl": url, "finalUrl": url, "redirects": [], "httpStatus": 200, "contentType": "text/html",
            "mediaType": "text/html", "contentLength": str(len(body)), "etag": None, "lastModified": None, "serverDate": None,
            "bodySha256": body_hash, "bodyBytes": len(body), "fetchedAt": STAMP, "userAgent": "AuthoredSynthetic/1.0",
            "network": "synthetic_loopback", "robots": [], "requestCount": 1}
        receipt_raw = json_bytes(receipt)
        receipt_hash = sha(receipt_raw)
        (base / "receipts" / f"{receipt_hash}.json").write_bytes(receipt_raw)
        acquired = {"provenance": "collected_http", "collectionId": name,
            "receipt": {"file": f"collections/{name}/receipts/{receipt_hash}.json", "sha256": receipt_hash},
            "fetchedAt": STAMP, "finalUrl": url, "httpStatus": 200, "contentType": "text/html", "bodySha256": body_hash,
            "documentKind": "news", "network": "synthetic_loopback", "published": declared_published(published[index % 3]).wire()}
        items.append({"candidateId": candidate, "supplierDocumentId": f"{name}-{index}", "url": url,
            "bodyRef": body_hash, "mediaType": "text/html", "title": "Authored synthetic article", "publishedAt": None,
            "modifiedAt": None, "sourceRevision": None, "publisher": "Authored Synthetic Publisher", "collection": acquired})
        targets.append({"candidateId": candidate, "url": url, "outcome": "collected", "code": None,
                        "bodySha256": body_hash, "receiptSha256": receipt_hash})
        documents[body_hash] = {"file": f"collections/{name}/bodies/{body_hash}.bin", "sha256": body_hash}
    page_raw = json_bytes({"items": items, "more": False, "nextCursor": None})
    (base / "page-0.json").write_bytes(page_raw)
    manifest = {"schemaVersion": "zoop-ingestion-s2-1", "sourceId": source_id, "scopeId": "body",
        "pages": [{"pageId": f"collection-{name}", "cursor": None,
            "response": {"file": f"collections/{name}/page-0.json", "sha256": sha(page_raw)},
            "status": "ok", "nextCursor": None, "terminal": True, "coverageThrough": None}], "documents": documents}
    manifest_raw = json_bytes(manifest)
    (base / "manifest.json").write_bytes(manifest_raw)
    result = {"schemaVersion": "zoop-collection-1", "collectionId": name, "requestDigest": digest(["authored", name]),
        "sourceId": source_id, "scopeId": "body", "provenance": "collected_http", "state": "complete",
        "startedAt": STAMP, "completedAt": STAMP, "grant": {"grantId": grant["grantId"], "revision": grant["revision"]},
        "manifest": {"file": f"collections/{name}/manifest.json", "sha256": sha(manifest_raw)}, "targets": targets,
        "usage": {"requests": len(items), "bytes": sum(map(len, bodies)), "targets": len(items), "collected": len(items)}}
    raw = json_bytes(result)
    (base / "collection.json").write_bytes(raw)
    return {"schemaVersion": operating_collection.REQUEST, "sources": str(kit.registry_path),
        "ingestionStateDirectory": str(kit.root / "ingestion"), "sourceId": source_id, "scopeId": "body",
        "collection": {"file": f"collections/{name}/collection.json", "sha256": sha(raw)}, "roundId": name,
        "checkpointRevision": 0, "provenance": {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"},
        "promptVersion": LIVE_PROMPT, "catalogue": deepcopy(CATALOGUE), "snapshot": {"revision": "empty-history", "events": []},
        "topic": None, "sets": [{"candidateId": f"c-{index}", "setId": f"{name}-set-{index}",
            "extractionJobId": f"{name}-s2-{index}", "relationJobId": f"{name}-s3-{index}",
            "stageAllowances": {stage: 10 for stage in STAGES}} for index in range(len(items))]}


def two_sets(inputs):
    combined = json.loads(json.dumps(inputs))
    second = json.loads(json.dumps(combined["sets"][0]))
    second.update(setId="set-2", relationJobId="native-s3-2")
    second["extraction"].update(jobId="native-s2-2", incoming=second["extraction"]["snapshot"]["events"][0]["members"][0]["observation"],
                                snapshot={"revision": "empty-native-history", "events": []}, topic=None)
    combined["sets"].append(second)
    return combined


def combined_handoff_source_check(root: Path, config: dict, units: list[dict]) -> dict:
    """Exercise the existing combined handoff reader with real file pins; editorial decisions are an empty authored set."""
    from zoop_ai_pipeline.handoff import HandoffPaths, current, load_operator
    from zoop_ai_pipeline.handoff_contracts import Manifest, POLICY
    from zoop_ai_pipeline.graph_projection import Source, digest, review_state

    operator = root / "handoff-operator"
    operator.mkdir()
    documents = {"canonical": {"schemaVersion": "zoop-graph-canonical-1", "entries": []},
                 "decisions": {"schemaVersion": "zoop-public-decisions-4", "policyVersion": POLICY,
                               "companies": [], "issues": [], "structural": [], "follows": [], "origins": []},
                 "bindings": {"schemaVersion": "zoop-app-document-bindings-1", "bindings": []}}
    for name, document in documents.items():
        (operator / (name + ".json")).write_text(json.dumps(document))
    paths = HandoffPaths(Path(config["stateDirectory"]) / "s3", Path(config["stateDirectory"]) / "s2",
                         Path(units[0]["ingestionStateDirectory"]), Path(units[0]["sources"]),
                         operator / "canonical.json", operator / "decisions.json", operator / "bindings.json")
    operator_files = load_operator(paths)
    contexts = paths.contexts()
    with Source(contexts.routes[0].paths) as source:
        pins = []
        for unit in units:
            result = source.inspect(unit["relationJobId"])
            pins.append({"relation": {"jobId": result["jobId"], "inputDigest": result["inputDigest"]},
                         "upstream": result["binding"]["upstream"], "reviewDigest": digest(review_state(result))})
        manifest = Manifest.model_validate({"schemaVersion": "zoop-ai-handoff-1", "handoffId": "shared-operating-sources",
            "sourceKind": "synthetic", "policyVersion": POLICY, "sources": pins, "files": operator_files.hashes()})
        loaded = current({"single": source}, contexts, paths, manifest, operator_files, strict=True)
    assert {item.s3["jobId"] for item in loaded} == {unit["relationJobId"] for unit in units}
    assert {item.s2["jobId"] for item in loaded} == {unit["extraction"]["jobId"] for unit in units}
    assert {item.submit.incoming.document_id for item in loaded} == {unit["extraction"]["incoming"]["documentId"] for unit in units}
    return {"sourceCount": len(loaded), "relationJobs": sorted(item.s3["jobId"] for item in loaded),
            "upstreamJobs": sorted(item.s2["jobId"] for item in loaded),
            "incomingDocuments": sorted(item.submit.incoming.document_id for item in loaded),
            "consumer": "handoff.current(strict=True)", "publication": "source-read proof; editorial decisions remain empty"}


def shared_handoff_smoke(root: Path):
    """Operator-pinned finite collection -> original native jobs -> populated, current handoff."""
    root.mkdir()
    kit = CollectionKit(root / "inputs")
    geography = "계약은 국내 시장 중심이다."
    events = [("supply-q3", Q3, "2026Q3"), ("supply-q4", "합성기업은 2026년 4분기 공급 계약을 발표했다.", "2026Q4")]
    batch = authored_collection(kit, bodies=tuple(page(quote, geography) for _, quote, _ in events))
    config = {"schemaVersion": CONFIG, "policy": policy(), "ledgerDirectory": str(root / "metering"),
              "stateDirectory": str(root / "native"),
              "runtime": {"model": "gpt-6-luna", "effort": "high", "maxOutputTokens": 24000,
                          "openaiEndpoint": "https://synthetic.invalid/v1", "verifierEndpoint": "https://synthetic.invalid/v1",
                          "verifierModel": "jev-1.14.0"}}
    config_path, batch_path = root / "config.json", root / "batch.json"
    config_path.write_bytes(json_bytes(config))
    batch_path.write_bytes(json_bytes(batch))
    sent = []

    def transport_reply(request):
        body = json.loads(request.content)
        stage = ("verify-impact" if "target" in body["questions"] else "verify-relation") if "questions" in body else json.loads(body["messages"][1]["content"])["stage"]
        sent.append(stage)
        answer = simulate(body)
        if stage == "extract":
            projection = json.loads(body["messages"][1]["content"])
            event = next(event for event in events if any(event[1] in segment["text"] for segment in projection["sources"][0]["segments"]))
            parsed = json.loads(answer["choices"][0]["message"]["content"])
            parsed["mentions"][0].update(title=f"합성 공급 계약 {event[2]}", period=event[2], countries=["KR"])
            answer["choices"][0]["message"]["content"] = json.dumps(parsed, ensure_ascii=False)
        return httpx.Response(200, json=answer)

    def register():
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(Budget, "reserve", side_effect=AssertionError("registration attempted a reservation")):
            code = operating.main(["register-collection", "--config", str(config_path), "--batch", str(batch_path)])
        result = json.loads(out.getvalue())
        assert code == 0 and result["status"] == "registered" and result["error"] is None, result
        return result

    env = {"PATH": os.defpath, "HOME": str(Path.home()), **ownership_env()}
    with (mock.patch.dict(os.environ, env, clear=True),
          mock.patch.object(socket.socket, "connect", side_effect=AssertionError("synthetic smoke attempted a socket")),
          mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("synthetic smoke attempted DNS")),
          mock.patch.object(subprocess, "Popen", side_effect=AssertionError("synthetic smoke attempted a subprocess")),
          httpx.MockTransport(transport_reply) as transport):
        owner = Owner(config, initialize=True, transport=transport)
        registered = register()
        original_ids = [unit["setId"] for unit in batch["sets"]]
        assert registered["registration"] == {"registered": original_ids, "interruptedSetId": None, "notAttempted": []}
        units = registered["manifest"]["sets"]
        assert [(u["setId"], u["extraction"]["jobId"], u["relationJobId"]) for u in units] == [
            (u["setId"], u["extractionJobId"], u["relationJobId"]) for u in batch["sets"]]
        assert registered["requestDigest"] == digest(operating_collection.Request.model_validate(batch).wire())
        assert registered["collection"]["resultSha256"] == batch["collection"]["sha256"]
        collection = json.loads((kit.inputs / batch["collection"]["file"]).read_bytes())
        assert registered["collection"]["manifestSha256"] == collection["manifest"]["sha256"]
        assert registered["ingestion"]["checkedWindow"] is None and registered["ingestion"]["checkpoint"]["through"] is None
        assert registered["ingestion"]["counts"]["textReady"] == 2
        assert register() == registered
        assert owner.budget.snapshot()["calls"] == 0 and sent == [] and not owner.directory("s3").exists()
        assert [entry["pins"]["unit"] for entry in owner.budget.sets()] == units
        observations = [u["extraction"]["incoming"] for u in units]
        exports = [Kit.export(kit, ref) for ref in observations]
        assert [out["observation"]["collection"]["published"]["precision"] for out in exports] == ["unknown", "day"]
        assert len({ref["documentId"] for ref in observations}) == 2

        Kit.allow_model_send(kit, owner.runtime(units[0], "offline"), STAGES)
        with mock.patch.dict(os.environ, {"ZOOP_AI_PIPELINE_LIVE_ENABLED": "1", **FAKE_KEYS}):
            with mock.patch.object(extraction.Extractor, "_receive", side_effect=SystemExit(75)):
                try:
                    Owner(config, transport=transport).run(1, set_ids=original_ids)
                except SystemExit as exc:
                    assert exc.code == 75
                else:
                    raise AssertionError("native receipt interruption was not reached")
            assert sent == ["extract"] and owner.budget.snapshot()["states"] == {"settled": 1}
            owner = Owner(config, transport=transport)
            assert len(owner.status()["reconciliation"]["receiptsAwaitingNativeRecovery"]) == 1
            first = owner.run(1, set_ids=original_ids)
            assert first["status"] == "batch-complete" and first["sets"][0]["recoveredReceipts"] == 1, first
            assert [item["setId"] for item in first["sets"]] == original_ids[:1]
            assert [entry["complete"] for entry in Owner(config).budget.sets()] == [True, False]
            second = Owner(config, transport=transport).run(1, set_ids=original_ids)
            assert second["status"] == "complete" and [item["setId"] for item in second["sets"]] == original_ids[1:], second
            assert Owner(config, transport=transport).run(2, set_ids=original_ids)["sets"] == []
        assert sent == ["extract", "relation", "verify-relation", "impact", "verify-impact"] * 2, sent
        completed = Owner(config).budget.sets()
        assert [entry["id"] for entry in completed] == original_ids
        assert all(entry["complete"] for entry in completed) and [entry["pins"]["unit"] for entry in completed] == units
        replayed = register()
        assert replayed["requestDigest"] == registered["requestDigest"] and replayed["manifest"] == registered["manifest"]
        assert replayed["collection"] == registered["collection"] and replayed["registration"] == registered["registration"]

        paths = HandoffPaths(owner.directory("s3"), owner.directory("s2"), kit.root / "ingestion", kit.registry_path,
                             root / "canonical.json", root / "decisions.json", root / "bindings.json")
        canonical = {"schemaVersion": "zoop-graph-canonical-1", "entries": []}
        decisions = {"schemaVersion": "zoop-public-decisions-4", "policyVersion": POLICY,
                     "companies": [{"canonicalId": "co:synth-1", "publicId": "SYNTH:000001", "label": "합성기업",
                                    "decisionRef": "authored-company"}],
                     "issues": [], "structural": [], "follows": [], "origins": []}
        bindings = {"schemaVersion": "zoop-app-document-bindings-1", "bindings": []}
        pins, expected_evidence, source_events = [], [], []
        with Source(paths.contexts().routes[0].paths) as source:
            for unit, ref, exported, (name, quote, _) in zip(units, observations, exports, events, strict=True):
                result = source.inspect(unit["relationJobId"])
                assert result["state"] == "ready" and result["delivery"]["status"] == "current", result
                assert result["provenance"] == batch["provenance"]
                with owner.native(unit, "s2") as store:
                    submit, s2 = extraction.Extractor(store, owner.sources(unit)).export(unit["extraction"]["jobId"])
                assert submit.wire() == unit["extraction"]
                upstream = {"jobId": s2["jobId"], "inputDigest": s2["inputDigest"]}
                assert {key: result["binding"]["upstream"][key] for key in upstream} == upstream
                assert owner.budget.bound("native:" + unit["setId"] + ":s2") == {**upstream, "bindingDigest": digest(s2["binding"])}
                assert result["binding"]["upstream"]["digest"] == extraction.upstream_digest(s2)
                pins.append({"relation": {"jobId": result["jobId"], "inputDigest": result["inputDigest"]},
                             "upstream": result["binding"]["upstream"], "reviewDigest": digest(review_state(result))})
                assert len(s2["eventCandidates"]) == 1
                event_id = s2["eventCandidates"][0]["eventCandidateId"]
                canonical["entries"].extend([
                    {"upstream": upstream, "kind": "company", "ref": "SYNTH-1", "canonicalId": "co:synth-1", "decisionRef": "authored-company"},
                    {"upstream": upstream, "kind": "event", "ref": event_id, "canonicalId": f"issue:{name}", "decisionRef": f"authored-{name}"}])
                text = exported["document"]["text"]
                spans = []
                for sentence in (quote, geography):
                    start = text.index(sentence)
                    spans.append({"documentId": ref["documentId"], "documentVersion": ref["documentVersion"],
                                  "start": start, "end": start + len(sentence), "quoteSha256": sha(sentence.encode())})
                expected_evidence.extend(spans)
                source_events.append({"upstream": upstream, "kind": "event-candidate", "ref": event_id, "mentionId": "m-sim-1",
                                      "documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "observation": ref})
                decisions["issues"].append({"canonicalId": f"issue:{name}", "publicId": f"issue:{name}", "decisionRef": f"authored-{name}",
                    "geography": {"classification": "domestic", "countries": ["KR"], "evidence": [spans[1]],
                                  "decisionRef": "authored-country", "decisionVersion": "1"},
                    "representative": None, "fieldVerdicts": [], "summary": None})
                bindings["bindings"].append({"documentId": ref["documentId"], "documentVersion": ref["documentVersion"],
                    "articleId": ref["documentId"], "articleVersion": ref["documentVersion"], "textSha256": sha(text.encode()),
                    "offsetUnit": "unicode_code_point"})
        for name, document in (("canonical", canonical), ("decisions", decisions), ("bindings", bindings)):
            (root / f"{name}.json").write_bytes(json_bytes(document))
        manifest = {"schemaVersion": "zoop-ai-handoff-1", "handoffId": "finite-collection-handoff", "sourceKind": "synthetic",
                    "policyVersion": POLICY, "sources": pins, "files": load_operator(paths).hashes()}
        manifest_path = root / "handoff-manifest.json"
        manifest_path.write_bytes(json_bytes(manifest))
        selector = {"schemaVersion": manifest["schemaVersion"], "handoffId": manifest["handoffId"]}

        def handoff(command, request, expected=0):
            argv = ["zoop-ai-handoff", command, "--state-dir", str(root / "handoff"),
                    "--relation-state-dir", str(paths.relation), "--extraction-state-dir", str(paths.extraction),
                    "--ingestion-state-dir", str(paths.ingestion), "--sources", str(paths.sources),
                    "--canonical", str(paths.canonical), "--decisions", str(paths.decisions), "--bindings", str(paths.bindings)]
            out = io.StringIO()
            with (mock.patch.object(sys, "argv", argv),
                  mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(json_bytes(request)))), redirect_stdout(out)):
                code = handoff_cli.main()
            result = json.loads(out.getvalue())
            assert code == expected, result
            return result

        frozen = handoff("freeze", json.loads(manifest_path.read_bytes()))
        assert frozen["state"] == "ready" and frozen["publication"] == "not-published", frozen
        out = handoff("export", selector)
        assert out["delivery"]["status"] == "current" and out["manifest"] == manifest
        bundle, receipt = out["bundle"], out["receipt"]
        assert receipt == frozen["receipt"] and receipt["sources"] == pins
        assert digest(manifest) == receipt["manifestDigest"] == bundle["manifestDigest"]
        assert digest(bundle) == receipt["bundleDigest"]
        assert content_digest(bundle) == bundle["digests"]["content"] == receipt["contentDigest"]
        assert sha((root / "handoff" / "bundles" / f"{receipt['bundleDigest']}.json").read_bytes()) == receipt["bundleDigest"]
        assert [{key: source[key] for key in ("relation", "upstream", "reviewDigest")} for source in bundle["sources"]] == pins
        assert bundle["provenance"] == {"declaredSourceKind": "synthetic", "observedSourceKind": "synthetic",
                                        "executionMode": "live", "recordingKind": "provider"}
        assert bundle["counts"] == receipt["counts"] == {"companies": 1, "pathCompanies": 0, "issues": 2,
            "relations": {"INVOLVES": 2, "STRUCTURALLY_RELATED_TO": 0, "FOLLOWS": 0}, "evidence": 4, "articles": 2, "impacts": 2, "exclusions": 0}
        assert {issue["id"]: issue["sourceEvents"] for issue in bundle["issues"]} == {
            f"issue:{event[0]}": [source_event] for event, source_event in zip(events, source_events, strict=True)}
        assert {(r["type"], r["source"], r["target"]) for r in bundle["relations"]} == {
            ("INVOLVES", f"issue:{name}", "SYNTH:000001") for name, _, _ in events}
        actual_evidence = [{**{key: e["source"][key] for key in ("documentId", "documentVersion")},
                            **{key: e[key] for key in ("start", "end", "quoteSha256")}} for e in bundle["evidence"]]
        assert sorted(actual_evidence, key=digest) == sorted(expected_evidence, key=digest)
        assert {(a["articleId"], a["articleVersion"]) for a in bundle["articles"]} == {
            (ref["documentId"], ref["documentVersion"]) for ref in observations}
        articles = {article["documentId"]: article for article in bundle["articles"]}
        for ref, exported, precision in zip(observations, exports, ("unknown", "day"), strict=True):
            article = articles[ref["documentId"]]
            assert article["rawVersion"] == ref["rawVersion"] and article["publicationPrecision"] == precision
            assert article["publishedAt"] == (None if precision == "unknown" else "2026-10-14")
            assert article["observations"] == [{
                **{key: ref[key] for key in ("roundId", "sourceId", "page", "ordinal")},
                "observedAt": exported["observation"]["observedAt"], "grant": exported["grant"]}]
        assert handoff("freeze", json.loads(manifest_path.read_bytes())) == frozen and len(frozen["attempts"]) == 1
        assert handoff("export", selector)["bundle"] == bundle
        changed = deepcopy(manifest)
        changed["sources"][0]["reviewDigest"] = "0" * 64
        assert handoff("freeze", changed, expected=2)["error"]["code"] == "handoff_input_conflict"
        kit.registry["sources"][0]["grant"]["allowedOperations"].remove("quote-display")
        kit.save_registry()
        held = handoff("export", selector, expected=2)
        assert held["delivery"] == {"status": "withheld", "code": "source_unauthorized"} and "bundle" not in held, held
        assert len(sent) == 10
        status = Owner(config).status()
        assert status["reconciliation"] == {"monetaryWithoutNative": [], "nativeWithoutMonetary": [], "receiptsAwaitingNativeRecovery": []}
        assert len(status["monetaryAttempts"]) == len(status["nativeAttempts"]) == status["metering"]["calls"] == 10
        return {"status": "passed", "consumer": "register-collection -> Owner.run(original set IDs) -> handoff freeze/export",
                "requestDigest": registered["requestDigest"], "collection": registered["collection"], "setIds": original_ids,
                "relationJobs": [pin["relation"]["jobId"] for pin in pins], "upstreamJobs": [pin["upstream"]["jobId"] for pin in pins],
                "durableCompletedSets": len(completed), "checkedWindow": None, "coverageThrough": None,
                "sourceKind": "synthetic", "executionMode": "live", "network": "httpx.MockTransport; sockets and subprocesses forbidden",
                "externalProviderCalls": 0, "physicalRequests": len(sent), "recoveredReceipts": first["sets"][0]["recoveredReceipts"],
                "handoffAttempts": len(frozen["attempts"]), "counts": receipt["counts"], "receipt": receipt,
                "publication": out["publication"], "replayAdditionalCalls": 0, "rightsRevocation": held["delivery"],
                "reconciliation": status["reconciliation"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long-job", action="store_true")
    parser.add_argument("--faults", action="store_true")
    parser.add_argument("--shared-handoff", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="zoop-operating-smoke-") as directory:
        result = smoke(Path(directory).resolve(), args.long_job)
        if args.faults:
            result["faultCases"] = fault_smoke(Path(directory).resolve())
        if args.shared_handoff:
            result["sharedHandoff"] = shared_handoff_smoke(Path(directory).resolve() / "shared-handoff")
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
