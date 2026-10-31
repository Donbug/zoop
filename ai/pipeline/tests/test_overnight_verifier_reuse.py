"""Same-set verifier reuse over real private source authority, runtime and money ledger.

All input and HTTP responses are authored. CLI proofs redirect ONLY the test
transport to loopback; funded endpoint/policy validation remains unchanged.
"""
from __future__ import annotations

import argparse
import copy
import http.server
import importlib.util
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE), str(PIPELINE / "scripts")]
from scripts import overnight_run as runner, overnight_metrics as metrics
from scripts.issue_summary_smoke import GUARD, jev_reply
from tests import test_overnight_history as history_fixture
from tests.live_support import Fake, openai_reply
from tests.test_overnight_controller import ACTOR, write_ready_canary
from zoop_ai_pipeline import live_budget, live_funding, live_runtime as live
from zoop_ai_pipeline.extraction import Sources, cite_exact
from zoop_ai_pipeline.extraction_contracts import ObservationRef
from zoop_ai_pipeline.private_processing import PrivateAuthority

STAGE = "verify-issue-summary"
QUOTE = history_fixture.QUOTE
SANDBOX = '(version 1)(allow default)(deny network*)(allow network-outbound (remote ip "localhost:*"))(allow network-inbound (local ip "localhost:*"))'


def response(body):
    if "messages" in body:
        quote = json.loads(body["messages"][1]["content"])["input"]["quotes"][0]
        return openai_reply({"claims": [{"text": QUOTE, "quoteIds": [quote["id"]]}]}, model=live.MODEL)
    return jev_reply(body)


class World:
    def __init__(self, root, monkeypatch, *, transport=None):
        self.root, self.monkeypatch = root, monkeypatch
        self.mode, self.on_chat, self.on_verify = "ok", None, None
        self.peer = Fake(self.reply)
        current = datetime.now(UTC).replace(microsecond=0)
        stamp = lambda value: value.strftime("%Y-%m-%dT%H:%M:%SZ")
        config = {"schemaVersion": "zoop-private-run-4", "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"}, "runId": "synthetic-verifier-reuse", "root": str(root),
                  "admitFrom": stamp(current - timedelta(minutes=1)), "admitUntil": stamp(current + timedelta(hours=1)),
                  "finishBy": stamp(current + timedelta(hours=2)), "graphPort": 32829, "maxCalls": 100000, "processingActor": ACTOR}
        self.config_path = root / "control/run-config.json"
        runner.save(self.config_path, config)
        for name in ("RUN_CONFIG", "RUN_CONFIG_PATH", "ROOT", "RUN_ID", "ADMIT_UNTIL", "GRAPH_PORT", "MAX_CALLS"):
            monkeypatch.setattr(runner, name, getattr(runner, name))
        runner.configure(SimpleNamespace(run_config=self.config_path, root=root))
        # Only explicit synthetic values enter either runtime; inherited secrets/proxies are absent.
        env = {"PATH": "/usr/bin:/bin", "HOME": str(root / "home"), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONPATH": os.pathsep.join(map(str, (runner.REPO / "ai/pipeline/src", runner.REPO / "ai/worker/src",
                                                     runner.REPO / "ai/pipeline", runner.REPO / "ai/pipeline/scripts"))),
               live.GATE: "1", live.MODEL_VAR: live.MODEL, live.EFFORT_VAR: "high", live.JEV_MODEL_VAR: "jev-1.14.0",
               live.PROFILE_VAR: live_funding.CAPPED_PROFILE, live.RUN_ID_VAR: config["runId"],
               live.ADMIT_FROM_VAR: config["admitFrom"], live.ADMIT_UNTIL_VAR: config["admitUntil"], live.FINISH_BY_VAR: config["finishBy"],
               live.BUDGET_DIR_VAR: str(root / "modelbudget"), live.MAX_USD_VAR: "4", live.MAX_CALLS_VAR: "100000",
               live.SHARED_MAX_VAR: "3.5", live.PERSONAL_MAX_VAR: "0.5", live.MAX_OUTPUT_VAR: "24000", live.TIMEOUT_VAR: "10",
               live.SET_ID_VAR: "set-summary", live.OPENAI_KEY_VAR: "synthetic-loopback-only", live.JEV_KEY_VAR: "synthetic-loopback-only"}
        for key in list(os.environ):
            monkeypatch.delenv(key)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        self.env = env
        self.runtime = live.LiveRuntime.from_env(need_send=True, family=live.ISSUE_SUMMARY, transport=transport or self.peer.transport)
        with monkeypatch.context() as fixture:
            fixture.setattr(history_fixture, "runtimes", lambda: [self.runtime])
            fixture.setattr(history_fixture, "QUOTE", QUOTE + " " + QUOTE)
            _, unit = history_fixture.make_original(root / "originals", "authored", root / "originals/native", fixture)
        self.unit = runner.bind_execution(unit, {"setId": "set-summary", "fundingPolicy": live_funding.CAPPED_POLICY_VERSION}, [self.runtime])
        self.directory = root / "analysis/luna" / self.unit["unitId"]
        self.budget = runner.funding(root)
        self.budget.admit_set("set-summary", runner.source_identity(self.unit), {"issue-summary": 8, STAGE: 8})
        authority = PrivateAuthority(Path(self.unit["privateProcessing"]))
        exported = runner.load(self.unit["export"])
        self.sources = Sources(Path(self.unit["ingestionStateDir"]), authority)
        ref = ObservationRef.model_validate(self.unit["observation"])
        start = exported["document"]["text"].index(QUOTE)
        citation = cite_exact(self.sources, ref, exported, start, start + len(QUOTE), QUOTE)
        second = exported["document"]["text"].index(QUOTE, start + len(QUOTE))
        self.second_citation = cite_exact(self.sources, ref, exported, second, second + len(QUOTE), QUOTE)
        self.s2 = {"inputDigest": runner.sha(b"authored-s2-input"), "eventCandidates": [
            {"eventCandidateId": "candidate-" + name, "state": "candidate", "mention": {"title": "Authored " + name},
             "citations": [copy.deepcopy(citation)]} for name in ("A", "B", "C")]}
        self.write_unit()
        runner.save(self.directory / "summary-runtime.json", self.runtime.binding())
        pins = {"codePins": runner.code_pins(), "runConfig": config, "identityPolicy": runner.POLICY, "units": [self.unit],
                "runtimeBindings": {"luna": {"pipeline": self.runtime.binding(), "summary": self.runtime.binding()}},
                "funding": {"policyVersion": self.runtime.binding()["funding"]["version"],
                            "policyIdentity": runner.sha(runner.encoded(self.runtime.binding()["funding"])),
                            "totalMaxNanoUsd": 4_000_000_000, "bucketMaxNanoUsd": {"shared": 3_500_000_000, "personal": 500_000_000}, "maxCalls": 100000}}
        checked = {"checkDigest": runner.sha(runner.encoded(pins)), "pins": pins}
        runner.save(root / "control/CHECK.json", checked)
        runner.save(root / "control/greenlight.json", runner.v2_greenlight(checked, "run"))
        for profile in ("luna", "deepseek-diagnostic"):
            write_ready_canary(root, checked, profile, self.unit)

    def write_unit(self):
        runner.save(self.directory / "unit.json", self.unit)
        runner.save(self.directory / "s2-result.json", self.s2)

    def reply(self, request):
        body = json.loads(request.content)
        chat = "messages" in body
        if chat and self.on_chat:
            self.on_chat()
        if not chat and self.on_verify:
            self.on_verify()
        if not chat and self.mode == "silent":
            raise httpx.ReadTimeout("authored unknown")
        reply = response(body)
        if not chat and self.mode == "overbound":
            reply["usage"]["input_tokens"] = 1_000_000
        return httpx.Response(500 if not chat and self.mode == "http500" else 200, json=reply)

    def run(self, candidate="A"):
        with self.monkeypatch.context() as context:
            context.setattr(live.LiveRuntime, "from_env", classmethod(lambda cls, **kwargs: self.runtime))
            return runner.private_summary_child(self.directory, "candidate-" + candidate)

    def folder(self, candidate="A"):
        return self.directory / "candidate-summaries" / runner.sha(("candidate-" + candidate).encode())[:24]

    def verifier_hits(self):
        return sum(request.url.path.endswith("/systemone") for request in self.peer.requests)

    def verifier_rows(self):
        with sqlite3.connect(self.budget.path) as db:
            return db.execute("SELECT r.attempt_id,r.state,r.charged_nano FROM reservations r JOIN reservation_sets s USING(attempt_id) WHERE s.stage=?", (STAGE,)).fetchall()


@pytest.fixture
def world(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("unit controls may not open sockets")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    return World(tmp_path / "offline-verification", monkeypatch)


def tree(directory):
    return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("*") if path.is_file()}


def no_verifier_files(world, candidate="B"):
    assert not list(world.folder(candidate).glob(STAGE + "-*"))
    assert not (world.folder(candidate) / "result.json").exists()


def refused(world, code, candidate="B", *, unknown=False):
    with pytest.raises(Exception) as caught:
        world.run(candidate)
    assert getattr(caught.value, "code", str(caught.value)) == code
    assert bool(getattr(caught.value, "unknown", getattr(caught.value, "uncertain", False))) is unknown


def test_exact_reuse_preserves_distinct_candidates_and_one_verifier_charge(world):
    assert world.run()["candidateSummaryStatus"] == "available"
    source = tree(world.folder())
    money = world.budget.snapshot()["buckets"]["personal"]
    for candidate in ("B", "C"):
        assert world.run(candidate)["candidateSummaryStatus"] == "available"
        result = runner.load(world.folder(candidate) / "result.json")
        record = runner.load(world.folder(candidate) / (STAGE + "-reuse.json"))
        assert result["schemaVersion"] == "zoop-private-candidate-summary-2"
        assert result["candidateId"] == "candidate-" + candidate
        assert result["verdict"] == json.loads(source["result.json"])["verdict"]
        assert result["inputDigest"] != json.loads(source["result.json"])["inputDigest"]
        assert result["verifierSource"] == {"kind": "same-set-receipt-reuse", "record": STAGE + "-reuse.json",
                                            "sourceAttemptId": world.verifier_rows()[0][0],
                                            "sourceReceiptSha256": runner.sha(source[STAGE + "-receipt.json"])}
        assert record["source"]["receiptSha256"] == result["verifierSource"]["sourceReceiptSha256"]
        assert record["physicalProviderCalls"] == record["reservations"] == 0
        assert set(path.name for path in world.folder(candidate).glob(STAGE + "-*")) == {STAGE + "-reuse.json"}
        before = tree(world.folder(candidate))
        snapshot = world.budget.snapshot()
        world.run(candidate)
        assert tree(world.folder(candidate)) == before and world.budget.snapshot() == snapshot
    assert tree(world.folder()) == source
    assert world.budget.snapshot()["buckets"]["personal"] == money
    assert world.budget.snapshot()["calls"] == 4
    assert len(world.verifier_rows()) == world.verifier_hits() == 1


@pytest.mark.parametrize("mode,code", [("silent", "summary_verifier_reuse_source_unsettled"),
                                        ("http500", "summary_verifier_reuse_source_invalid"),
                                        ("overbound", "summary_verifier_reuse_source_invalid")])
def test_unknown_and_invalid_settled_sources_are_never_resent(world, mode, code):
    world.mode = mode
    with pytest.raises(live.LiveFailure):
        world.run()
    source = tree(world.folder())
    charge = world.verifier_rows()
    world.mode = "ok"
    refused(world, code)
    no_verifier_files(world)
    assert world.verifier_hits() == 1 and world.verifier_rows() == charge
    assert tree(world.folder()) == source


def test_released_owner_is_not_reused_or_resent(world, monkeypatch):
    # The real runtime releases a reserved request when the second rights check refuses.
    original = Sources.authorize_model_send
    checks = []
    def revoke(self, ref, purpose, recipient):
        if purpose.endswith(STAGE):
            checks.append(purpose)
            if len(checks) == 2:
                raise ValueError("authored_rights_revoked")
        return original(self, ref, purpose, recipient)
    with monkeypatch.context() as m:
        m.setattr(Sources, "authorize_model_send", revoke)
        with pytest.raises(ValueError, match="authored_rights_revoked"):
            world.run()
    assert world.verifier_rows()[0][1:] == ("released", 0)
    refused(world, "summary_verifier_reuse_source_unsettled")
    no_verifier_files(world)
    assert world.verifier_hits() == 0


@pytest.mark.parametrize("change", ["span", "quote-id", "expect", "bindingIdentity", "recipient", "purpose", "attemptId", "chargedUsd", "set", "bucket", "missing", "ambiguous", "symlink"])
def test_exact_identity_failures_do_not_create_verifier_attempts(world, change):
    world.run()
    path = world.folder() / (STAGE + "-receipt.json")
    receipt = runner.load(path)
    expected = "summary_verifier_reuse_mismatch"
    if change == "span":
        world.s2["eventCandidates"][1]["citations"] = [world.second_citation]
        world.write_unit()
    elif change == "quote-id":
        world.s2["eventCandidates"][1]["citations"][0]["evidenceId"] = "ev-different-owner"
        world.write_unit()
    elif change == "missing":
        path.rename(path.with_suffix(".retained"))
        expected = "summary_verifier_reuse_source_missing"
    elif change == "ambiguous":
        runner.save(world.folder("C") / (STAGE + "-intent.json"), runner.load(world.folder() / (STAGE + "-intent.json")))
        runner.save(world.folder("C") / (STAGE + "-receipt.json"), receipt)
        expected = "summary_verifier_reuse_source_missing"
    elif change == "symlink":
        retained = path.with_suffix(".retained")
        path.rename(retained)
        path.symlink_to(retained)
        expected = "summary_verifier_reuse_source_missing"
    else:
        if change == "chargedUsd":
            receipt["cost"][change] = "0.000000001"
        elif change == "set":
            receipt["admittedSet"]["setId"] = "foreign-set"
        elif change == "bucket":
            receipt["funding"]["bucket"] = "shared"
        elif change == "expect":
            receipt["expect"]["quoteIds"] = ["foreign-quote"]
        else:
            receipt[change] = "changed"
        runner.save(path, receipt)
    before = world.verifier_rows()
    refused(world, expected)
    no_verifier_files(world)
    assert world.verifier_hits() == 1 and world.verifier_rows() == before


@pytest.mark.parametrize("change", ["rights", "source", "runtime", "receipt"])
def test_reuse_resume_rechecks_current_authority_and_source(world, change, monkeypatch):
    world.run()
    world.run("B")
    before = tree(world.folder("B"))
    charge = world.budget.snapshot()
    if change == "rights":
        original = Sources.authorize_model_send
        def deny(self, ref, purpose, recipient):
            if purpose.endswith(STAGE):
                raise ValueError("source_purpose_or_recipient_denied")
            return original(self, ref, purpose, recipient)
        monkeypatch.setattr(Sources, "authorize_model_send", deny)
        code = "source_purpose_or_recipient_denied"
    elif change == "source":
        path = Path(world.unit["originalPins"][0]["path"])
        path.write_bytes(path.read_bytes() + b" ")
        code = "successful_provider_chain_canary_required"
    elif change == "runtime":
        binding = runner.load(world.directory / "summary-runtime.json")
        binding["identity"] = "0" * 64
        runner.save(world.directory / "summary-runtime.json", binding)
        code = "summary_runtime_pin_changed"
    else:
        path = world.folder() / (STAGE + "-receipt.json")
        receipt = runner.load(path)
        receipt["timing"]["durationMs"] += 1
        runner.save(path, receipt)
        code = "summary_verifier_reuse_mismatch"
    refused(world, code)
    assert tree(world.folder("B")) == before and world.budget.snapshot() == charge
    assert world.verifier_hits() == 1


def test_current_verifier_rights_refusal_leaves_no_consumer_verifier_artifact(world, monkeypatch):
    world.run()
    original = Sources.authorize_model_send
    def deny(self, ref, purpose, recipient):
        if purpose.endswith(STAGE):
            raise ValueError("source_purpose_or_recipient_denied")
        return original(self, ref, purpose, recipient)
    monkeypatch.setattr(Sources, "authorize_model_send", deny)
    source = tree(world.folder())
    charge = world.verifier_rows()
    refused(world, "source_purpose_or_recipient_denied")
    no_verifier_files(world)
    assert tree(world.folder()) == source and world.verifier_rows() == charge
    assert world.verifier_hits() == 1


def test_crash_after_reuse_record_resumes_without_new_send(world, monkeypatch):
    from zoop_ai_pipeline import issue_summary_jev
    world.run()
    def interrupted(answer):
        raise RuntimeError("authored crash after durable reuse")
    with monkeypatch.context() as m:
        m.setattr(issue_summary_jev, "outcome", interrupted)
        with pytest.raises(RuntimeError):
            world.run("B")
    record = (world.folder("B") / (STAGE + "-reuse.json")).read_bytes()
    assert not (world.folder("B") / "result.json").exists()
    before = world.budget.snapshot()
    world.run("B")
    world.run("B")
    assert (world.folder("B") / (STAGE + "-reuse.json")).read_bytes() == record
    assert world.budget.snapshot() == before and world.verifier_hits() == 1


def test_old_duplicate_failure_folder_is_not_adopted_and_producer_guard_is_unchanged(world):
    world.run()
    folder = world.folder("B")
    runner.save(folder / (STAGE + "-intent.json"), {"attemptId": "old-failed-consumer", "stage": STAGE})
    runner.save(folder / (STAGE + "-failure.json"), {"code": "live_set_request_duplicate", "uncertain": False})
    retained = {name: raw for name, raw in tree(folder).items()}
    refused(world, "summary_previous_attempt_unknown", unknown=True)
    assert all((folder / name).read_bytes() == raw for name, raw in retained.items())
    assert not (folder / (STAGE + "-reuse.json")).exists()
    world.s2["eventCandidates"][2]["mention"] = world.s2["eventCandidates"][0]["mention"]
    world.write_unit()
    refused(world, "live_set_request_duplicate", "C")
    no_verifier_files(world, "C")
    assert len(world.peer.requests) == 3 and world.verifier_hits() == 1


def test_second_admitted_unit_never_uses_foreign_set_receipt(world, monkeypatch):
    world.run()
    original = world.folder()
    world.unit = runner.bind_execution(world.unit, {"setId": "set-second", "fundingPolicy": live_funding.CAPPED_POLICY_VERSION}, [world.runtime])
    world.unit["unitId"] = "second-unit"
    world.directory = world.root / "analysis/luna/second-unit"
    world.write_unit()
    runner.save(world.directory / "summary-runtime.json", world.runtime.binding())
    # The foreign source looks like a sibling, but the new set has no request holder.
    for name, raw in tree(original).items():
        target = world.folder() / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    monkeypatch.setenv(live.SET_ID_VAR, "set-second")
    world.runtime = live.LiveRuntime.from_env(need_send=True, family=live.ISSUE_SUMMARY, transport=world.peer.transport)
    world.budget.admit_set("set-second", runner.source_identity(world.unit), {"issue-summary": 8, STAGE: 8})
    world.run("B")
    assert world.verifier_hits() == len(world.verifier_rows()) == 2
    assert runner.load(world.folder("B") / "result.json")["verifierSource"]["kind"] == "provider-receipt"


def collect(world, *, reuse_only_restart=False):
    controller = runner.Controller(SimpleNamespace(root=world.root, collection_index=world.root / "collection/INDEX.json"))
    controller.cohort = "luna"
    if reuse_only_restart:
        controller.collect_summary_calls(world.unit, world.folder("B"))
        rows = [json.loads(line) for line in (world.root / "events.jsonl").read_text().splitlines()]
        (world.root / "events.jsonl").rename(world.root / "pre-restart-events.jsonl")
        for row in rows:
            if row["attemptState"] == "reused":
                metrics.record_event(world.root / "events.jsonl", {key: value for key, value in row.items() if key != "append"})
        controller = runner.Controller(SimpleNamespace(root=world.root, collection_index=world.root / "collection/INDEX.json"))
        controller.cohort = "luna"
        assert not controller.emitted_attempts
    for candidate in ("B", "A", "C"):
        if world.folder(candidate).exists():
            controller.collect_summary_calls(world.unit, world.folder(candidate))
    return controller


def test_reuse_only_journal_restart_retains_actual_attempt_and_no_double_cost(world):
    from scripts.experiment_snapshots import money_metrics, read_budget
    for name in ("A", "B", "C"):
        world.run(name)
    controller = collect(world, reuse_only_restart=True)
    report = metrics.summarize(world.root)
    attempts = report["attempts"]
    assert attempts["received"] == 4 and attempts["reusedObservations"] == 2
    assert attempts["reuseOnly"] == attempts["conflictingAttempts"] == 0
    assert report["integrity"]["status"] == "complete"
    assert controller.physical_provider_calls == {"shared-openai": 3, "personal-typesafe": 1}
    events = [json.loads(line) for line in (world.root / "events.jsonl").read_text().splitlines()]
    reused = [row for row in events if row["attemptState"] == "reused"]
    assert all(row["httpStatus"] is None and all(value is None for value in row["usage"].values())
               and row["cost"]["chargedNanoUsd"] is None for row in reused)
    ledger = read_budget(world.budget.path)
    assert ledger["status"] == "complete"
    actual = money_metrics(ledger, events)
    without = money_metrics(ledger, [row for row in events if row["attemptState"] != "reused"])
    assert actual == without
    assert attempts["cost"]["chargedNanoUsd"]["total"] == sum(row[2] for row in world.verifier_rows()) + sum(
        row["charged_nano"] for row in ledger["reservations"] if row["stage"] != STAGE)
    before = (world.root / "events.jsonl").read_bytes()
    collect(world)
    assert (world.root / "events.jsonl").read_bytes() == before


def test_collector_refuses_changed_reuse_source_instead_of_complete_receipt_export(world):
    world.run()
    world.run("B")
    path = world.folder() / (STAGE + "-receipt.json")
    receipt = runner.load(path)
    receipt["timing"]["durationMs"] += 1
    runner.save(path, receipt)
    with pytest.raises(runner.Refused) as caught:
        collect(world)
    assert caught.value.code == "receipt_snapshot_incomplete" and caught.value.unknown
    events = [json.loads(line) for line in (world.root / "events.jsonl").read_text().splitlines()]
    assert all(event["attemptState"] != "reused" for event in events)


BOOTSTRAP = GUARD + '''
import httpx
from zoop_ai_pipeline.live_runtime import LiveRuntime
class LoopbackTransport(httpx.BaseTransport):
 def handle_request(self, request):
  if request.url.host not in {"api.openai.com", "api.typesafe.ai", "api.deepseek.com"}:
   raise RuntimeError("unexpected synthetic transport host")
  url = request.url.copy_with(scheme="http", host="127.0.0.1", port=int(os.environ["REUSE_PROOF_PORT"]))
  mapped = httpx.Request(request.method, url, headers=request.headers, content=request.read(), extensions=request.extensions)
  with httpx.HTTPTransport(retries=0) as inner:
   response = inner.handle_request(mapped)
   response.read()
   return response
original_from_env = LiveRuntime.from_env.__func__
LiveRuntime.from_env = classmethod(lambda cls, **kw: original_from_env(cls, transport=LoopbackTransport(), **kw))
if os.environ.get("REUSE_PROOF_CRASH") == "1":
 from zoop_ai_pipeline import issue_summary_jev
 issue_summary_jev.outcome = lambda answer: os._exit(9)
runpy.run_path(sys.argv.pop(1), run_name="__main__")
'''


class Simulator:
    def __init__(self):
        self.requests, self.mode = [], "ok"
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append({"path": self.path, "body": body})
                if self.path.endswith("/systemone") and owner.mode == "silent":
                    self.close_connection = True
                    return
                raw = runner.encoded(response(body))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def log_message(self, *args):
                pass
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def verifier_hits(self):
        return sum(row["path"].endswith("/systemone") for row in self.requests)


def child(world, provider, candidate, *, crash=False):
    env = {**world.env, "ZOOP_SMOKE_LOOPBACK": "1", "REUSE_PROOF_PORT": str(provider.server.server_port)}
    if crash:
        env["REUSE_PROOF_CRASH"] = "1"
    argv = ["/usr/bin/sandbox-exec", "-p", SANDBOX, sys.executable, "-B", "-c", BOOTSTRAP,
            str(runner.REPO / "ai/pipeline/scripts/overnight_run.py"), "--run-config", str(world.config_path),
            "--root", str(world.root), "--private-summary", str(world.directory), "--candidate", "candidate-" + candidate]
    result = subprocess.run(argv, cwd=runner.REPO / "ai/pipeline", env=env, capture_output=True, timeout=60)
    counter = len(list((world.root / "proof").glob("child-*.json")))
    runner.save(world.root / "proof" / f"child-{counter:02d}.json", {"candidate": candidate, "crash": crash,
        "exitCode": result.returncode, "stdout": result.stdout.decode(), "stderr": result.stderr.decode()})
    return result


def cli_proof(root, monkeypatch, *, baseline=False, silent=False):
    world = World(root, monkeypatch)
    with Simulator() as provider:
        if silent:
            provider.mode = "silent"
        first = child(world, provider, "A")
        if silent:
            assert first.returncode == 2 and b"live_response_unknown" in first.stdout, first
            before = world.verifier_rows()
            provider.mode = "ok"
            second = child(world, provider, "B")
            assert second.returncode == 2 and b"summary_verifier_reuse_source_unsettled" in second.stdout, second
            assert json.loads(second.stdout)["unknown"] is False
            assert world.verifier_rows() == before and provider.verifier_hits() == 1
            no_verifier_files(world)
        else:
            assert first.returncode == 0, (first.stdout, first.stderr)
            source = tree(world.folder())
            second = child(world, provider, "B")
            if baseline:
                assert second.returncode == 2 and b"live_set_request_duplicate" in second.stdout, (second.stdout, second.stderr)
                assert (world.folder("B") / (STAGE + "-intent.json")).exists()
                assert not (world.folder("B") / "result.json").exists()
            else:
                assert second.returncode == 0, (second.stdout, second.stderr)
                interrupted = child(world, provider, "C", crash=True)
                assert interrupted.returncode == 9, (interrupted.stdout, interrupted.stderr)
                record = (world.folder("C") / (STAGE + "-reuse.json")).read_bytes()
                assert not (world.folder("C") / "result.json").exists()
                assert child(world, provider, "C").returncode == 0
                assert child(world, provider, "C").returncode == 0
                assert (world.folder("C") / (STAGE + "-reuse.json")).read_bytes() == record
                results = [runner.load(world.folder(c) / "result.json") for c in ("A", "B", "C")]
                assert len({row["candidateId"] for row in results}) == 3
                assert results[0]["verdict"] == results[1]["verdict"] == results[2]["verdict"]
                assert tree(world.folder()) == source
                controller = collect(world, reuse_only_restart=True)
                assert controller.physical_provider_calls == {"shared-openai": 3, "personal-typesafe": 1}
                argv = ["/usr/bin/sandbox-exec", "-p", SANDBOX, sys.executable, "-B", str(PIPELINE / "scripts/overnight_metrics.py"), "summarize", "--root", str(root)]
                summary = subprocess.run(argv, env=world.env, capture_output=True, timeout=60)
                runner.save(root / "proof/metrics-cli.json", {"exitCode": summary.returncode, "stdout": summary.stdout.decode(), "stderr": summary.stderr.decode()})
                assert summary.returncode == 0, (summary.stdout, summary.stderr)
                report = json.loads(summary.stdout)
                assert report["attempts"]["received"] == 4 and report["attempts"]["reusedObservations"] == 2
                assert report["attempts"]["reuseOnly"] == report["attempts"]["conflictingAttempts"] == 0
                assert report["integrity"]["status"] == "complete"
            assert all((world.folder() / name).read_bytes() == raw for name, raw in source.items())
            assert provider.verifier_hits() == len(world.verifier_rows()) == 1
        evidence = {"baseline": baseline, "silent": silent, "verifierHttpCalls": provider.verifier_hits(),
                    "producerHttpCalls": len(provider.requests) - provider.verifier_hits(), "verifierReservations": world.verifier_rows(),
                    "budget": world.budget.snapshot(), "network": "OS sandbox denies external network; test transport redirects to 127.0.0.1 only",
                    "requests": provider.requests}
        runner.save(root / "proof/result.json", evidence)
        return evidence


@pytest.mark.skipif(sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
                    reason="actual-child proof requires macOS OS network containment; never run unsandboxed")
@pytest.mark.parametrize("silent", [False, True])
def test_real_private_summary_child_loopback(tmp_path, monkeypatch, silent):
    cli_proof(tmp_path / "offline-verification", monkeypatch, silent=silent)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline-repo", type=Path)
    parser.add_argument("--silent", action="store_true")
    args = parser.parse_args()
    if args.root.exists():
        raise SystemExit("fresh synthetic proof root required")
    if args.baseline_repo:
        path = args.baseline_repo / "ai/pipeline/scripts/overnight_run.py"
        spec = importlib.util.spec_from_file_location("baseline_overnight_run", path)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
    with pytest.MonkeyPatch.context() as patch:
        result = cli_proof(args.root, patch, baseline=bool(args.baseline_repo), silent=args.silent)
    print(json.dumps({k: v for k, v in result.items() if k != "requests"}))
