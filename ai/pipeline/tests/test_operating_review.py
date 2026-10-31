"""Operating review regressions at native, ledger, signal and real request boundaries."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import httpx
import pytest

from scripts.extraction_smoke import FAKE_KEYS
from scripts.operating_smoke import fixture, response
from tests.live_support import SECRETS, json_response, openai_reply
from tests.test_operating import native, runtime_session, send
from zoop_ai_pipeline import extraction, operating
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure
from zoop_ai_pipeline.live_budget import Budget, BudgetError
from zoop_ai_pipeline.live_funding import STAGES
from zoop_ai_pipeline.live_runtime import LiveFailure


@pytest.mark.parametrize("boundary", ["s2-pacing", "s3-reserved"])
def test_maintenance_deferral_resumes_same_unsent_native_attempt(native, monkeypatch, boundary):
    kit, config, inputs, owner, sent, transport = native
    triggered = []
    original = Budget.pacing_delay if boundary == "s2-pacing" else Budget.reserve

    def pacing(self):
        if not triggered:
            triggered.append(True)
            owner.budget.control("pause", "maintenance")
            return 0.01
        return original(self)

    def reserve(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if args[1] == "relation" and not triggered:
            triggered.append(True)
            owner.budget.control("pause", "maintenance")
        return result

    monkeypatch.setattr(Budget, "pacing_delay" if boundary == "s2-pacing" else "reserve", pacing if boundary == "s2-pacing" else reserve)
    stopped = owner.run(1)
    assert stopped["status"] == "blocked"
    before = owner.status()["nativeAttempts"]
    count = len(sent)
    owner.budget.control("resume", "maintenance-complete")
    completed = operating.Owner(config, transport=transport).run(1)
    assert completed["status"] == "complete", completed
    assert len(sent) == 7 and count == (0 if boundary == "s2-pacing" else 3)
    assert set(before) <= set(owner.status()["nativeAttempts"])


def test_fault_pause_overrides_drain_without_reopening_admission(monkeypatch, tmp_path):
    with runtime_session(monkeypatch, tmp_path, lambda r: json_response(openai_reply({"mentions": []}, usage=None))) as (budget, runtime, fake):
        budget.control("stop", "finish-admitted")
        before = budget.snapshot()["control"]["drainUntil"]
        receipt = send(runtime)
        assert receipt["cost"]["usageKnown"] is False
        assert budget.snapshot()["control"]["state"] == "paused"
        budget.control("resume", "usage-reviewed")
        assert budget.snapshot()["control"] == {"state": "stopping", "reason": "usage-reviewed", "drainUntil": before}
        with pytest.raises(BudgetError, match="operating_stopping"):
            budget.admit_operating_set("other", {"runtimeIdentity": runtime.binding()["identity"]}, {s: 1 for s in STAGES}, runtime._send["owner"])


def test_first_bad_verifier_stops_later_candidate_requests(native):
    kit, config, inputs, owner, sent, transport = native
    stages = []

    def handler(request):
        body = json.loads(request.content)
        if "questions" in body:
            stages.append("verify")
            return json_response({"model": "jev-1.14.0", "answers": {}, "usage": {"input_tokens": 1000, "output_tokens": 0}})
        stage = json.loads(body["messages"][1]["content"])["stage"]
        stages.append(stage)
        answer = response(body)
        if stage == "relation":
            parsed = json.loads(answer["choices"][0]["message"]["content"])
            second = json.loads(json.dumps(parsed["relations"][0]))
            second["productScope"] = "another-synthetic-product"
            parsed["relations"].append(second)
            answer["choices"][0]["message"]["content"] = json.dumps(parsed)
        return json_response(answer)

    owner.transport = httpx.MockTransport(handler)
    result = owner.run(1)
    assert stages == ["extract", "compare", "topic", "relation", "verify"], (stages, result)
    assert owner.budget.snapshot()["control"]["state"] == "paused"


def unregistered(tmp_path, monkeypatch, frontier):
    for name in ("ZOOP_AI_PIPELINE_LIVE_MAX_USD", "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {"ZOOP_AI_PIPELINE_LIVE_ENABLED": "1", **FAKE_KEYS}.items():
        monkeypatch.setenv(name, value)
    kit, config, inputs = fixture(tmp_path, "https://synthetic.invalid/v1")
    config["policy"]["lifecycle"] = {"kind": "frontier", "setIds": frontier}
    owner = operating.Owner(config, initialize=True, transport=httpx.MockTransport(lambda request: json_response(response(json.loads(request.content)))))
    kit.allow_model_send(owner.runtime(inputs["sets"][0], "offline"), STAGES)
    return owner, config, inputs


def test_rejected_registration_does_not_claim_frontier_or_job_ids(tmp_path, monkeypatch):
    owner, config, inputs = unregistered(tmp_path, monkeypatch, ["set-1"])
    bad = json.loads(json.dumps(inputs))
    bad["sets"][0]["extraction"]["incoming"]["documentId"] = "doc-not-present"
    with pytest.raises(ExtractionFailure, match="observation_not_found"):
        owner.register(bad)
    assert owner.budget.sets() == []
    assert owner.budget.bound("job:native-s2-1") is None and owner.budget.bound("job:native-s3-1") is None
    owner.register(inputs)
    assert owner.run(1)["status"] == "complete"


@pytest.mark.parametrize("kind", ["dns", "ledger-contention"])
def test_request_deadline_includes_resolver_and_ledger_poll(monkeypatch, tmp_path, kind):
    locker = []
    entered = threading.Event()

    def locked_database(path):
        with sqlite3.connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            entered.set()
            time.sleep(1.6)

    async def handler(request):
        thread = threading.Thread(target=locked_database, args=(tmp_path / "budget" / "live-budget.sqlite3",))
        locker.append(thread)
        thread.start()
        assert entered.wait(2)
        await asyncio.sleep(3)
        return json_response(openai_reply({"mentions": []}))

    def stalled_dns(*args, **kwargs):
        time.sleep(1.6)
        raise socket.gaierror("synthetic resolver stall")

    if kind == "dns":
        monkeypatch.setattr(socket, "getaddrinfo", stalled_dns)
        original_popen = subprocess.Popen

        def stalled_child(command, **kwargs):
            code = "import socket,time,runpy\ndef stalled(*a,**k):\n time.sleep(10)\n raise socket.gaierror('synthetic')\nsocket.getaddrinfo=stalled\nrunpy.run_module('zoop_ai_pipeline.operating_transport',run_name='__main__')"
            return original_popen([sys.executable, "-c", code], **kwargs)

        monkeypatch.setattr(subprocess, "Popen", stalled_child)
    try:
        with runtime_session(monkeypatch, tmp_path, handler if kind == "ledger-contention" else None,
                             endpoint="https://resolver.invalid/v1" if kind == "dns" else None) as (budget, runtime, fake):
            runtime._timeout = 0.1
            start = time.monotonic()
            with pytest.raises(LiveFailure) as caught:
                send(runtime)
            elapsed = time.monotonic() - start
            for thread in locker:
                thread.join(3)
            assert caught.value.uncertain and elapsed < 1.3, elapsed
            assert budget.snapshot()["states"] == {"reserved": 1}
    finally:
        for thread in locker:
            thread.join(3)


def test_signal_stop_is_durable_before_owner_lock_handoff(native, monkeypatch, tmp_path, capsys):
    kit, config, inputs, owner, sent, transport = native
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    original = Budget.owner
    observed = []

    @contextmanager
    def observe_handoff(self):
        try:
            with original(self) as token:
                yield token
        finally:
            with original(self):
                observed.append(self.snapshot()["control"]["state"])

    def interrupt(self):
        os.kill(os.getpid(), signal.SIGTERM)
        raise AssertionError("signal did not interrupt")

    monkeypatch.setattr(Budget, "owner", observe_handoff)
    monkeypatch.setattr(Budget, "sets", interrupt)
    assert operating.main(["run", "--config", str(path), "--max-sets", "1"]) == 2
    capsys.readouterr()
    assert observed == ["stopped"], observed


def test_partial_frontier_is_not_operation_complete(tmp_path, monkeypatch):
    owner, config, inputs = unregistered(tmp_path, monkeypatch, ["set-1", "set-2"])
    assert owner.run(1)["status"] == "batch-complete"
    owner.register(inputs)
    result = owner.run(1)
    assert result["status"] == "batch-complete" and result["metering"]["sets"]["complete"] == 1


def test_accepted_registration_interruption_recovers_same_pins(tmp_path, monkeypatch):
    owner, config, inputs = unregistered(tmp_path, monkeypatch, ["set-1"])
    with monkeypatch.context() as patch:
        def interrupted(*args):
            raise SystemExit(75)
        patch.setattr(extraction.Extractor, "freeze", interrupted)
        with pytest.raises(SystemExit):
            owner.register(inputs)
    assert owner.budget.snapshot()["sets"] == {"admitted": 1, "complete": 0}
    assert owner.run(1)["status"] == "complete"
    assert owner.budget.snapshot()["calls"] == 7


def test_conflicting_job_claim_does_not_partially_claim_new_set(native):
    kit, config, inputs, owner, sent, transport = native
    conflicting = json.loads(json.dumps(inputs))
    conflicting["sets"][0]["setId"] = "set-2"
    conflicting["sets"][0]["extraction"]["jobId"] = "new-s2"
    with pytest.raises(BudgetError, match="operating_binding_changed"):
        owner.register(conflicting)
    assert owner.budget.bound("job:new-s2") is None
    assert [entry["id"] for entry in owner.budget.sets()] == ["set-1"]
    assert sent == []


def test_owned_resolver_process_is_reaped_and_secrets_stay_in_private_fds(monkeypatch, tmp_path):
    marker = tmp_path / "resolver-entered"
    spawned = []
    original = subprocess.Popen

    def resolver_child(command, **kwargs):
        assert all(value not in repr(command) + repr(kwargs["env"]) for value in SECRETS)
        assert os.fstat(kwargs["stdin"].fileno()).st_mode & 0o777 == 0o600
        assert os.fstat(kwargs["stdout"].fileno()).st_mode & 0o777 == 0o600
        code = ("import socket,time,runpy\nfrom pathlib import Path\ndef stalled(*a,**k):\n"
                f" Path({str(marker)!r}).write_text('entered')\n time.sleep(10)\n raise socket.gaierror('synthetic')\n"
                "socket.getaddrinfo=stalled\nrunpy.run_module('zoop_ai_pipeline.operating_transport',run_name='__main__')")
        child = original([sys.executable, "-c", code], **kwargs)
        spawned.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", resolver_child)
    with runtime_session(monkeypatch, tmp_path, endpoint="https://resolver.invalid/v1") as (budget, runtime, fake):
        runtime._timeout = 1
        start = time.monotonic()
        with pytest.raises(LiveFailure) as caught:
            send(runtime)
        assert caught.value.uncertain and time.monotonic() - start < 3
        assert marker.read_text() == "entered"
        assert len(spawned) == 1 and spawned[0].returncode is not None
        assert budget.snapshot()["states"] == {"reserved": 1}


@pytest.mark.parametrize("stage,boundary,wait", [
    ("extract", "reserve", "serialize"),
    ("extract", "reserve", "exhaust"),
    ("extract", "begin_send", "exhaust"),
    ("relation", "reserve", "exhaust"),
])
def test_contended_control_write_preserves_same_unsent_attempt(native, monkeypatch, stage, boundary, wait):
    from zoop_ai_pipeline import live_budget

    kit, config, inputs, owner, sent, transport = native
    acquired = threading.Event()
    threads, attempts = [], []
    original_tx, original_boundary = Budget._tx, getattr(Budget, boundary)
    monkeypatch.setattr(live_budget, "BUSY_SECONDS", 0.05 if wait == "exhaust" else 2)

    @contextmanager
    def held_control(self, **options):
        with original_tx(self, **options) as db:
            if threading.current_thread().name == "contended-maintenance":
                acquired.set()
                time.sleep(0.2)
            yield db

    def at_native_intent(self, *args, **kwargs):
        current_stage = args[1] if boundary == "reserve" else "extract"
        if current_stage == stage and not attempts:
            attempts.append(args[0])
            thread = threading.Thread(target=lambda: owner.budget.control("pause", "contended-maintenance"),
                                      name="contended-maintenance")
            threads.append(thread)
            thread.start()
            assert acquired.wait(2)
        return original_boundary(self, *args, **kwargs)

    monkeypatch.setattr(Budget, "_tx", held_control)
    monkeypatch.setattr(Budget, boundary, at_native_intent)
    try:
        try:
            initial = owner.run(1)
        except BudgetError as exc:
            initial = {"error": exc.code}
    finally:
        for thread in threads:
            thread.join(3)
    assert len(sent) == (0 if stage == "extract" else 3)
    with owner.native(inputs["sets"][0], "s2" if stage == "extract" else "s3") as store:
        before = dict(store.one("SELECT attempt_id,state,verdict FROM calls WHERE stage=?", (stage,)))
        proofs = [json.loads(row["value"]) for row in store.all("SELECT value FROM meta WHERE key LIKE 'operating-deferral:%'")]
        assert len(proofs) == 1 and proofs[0]["attemptId"] == attempts[0]
        assert proofs[0]["reason"] == ("operating_paused" if wait == "serialize" else "operating_ledger_busy")
    owner.budget.control("resume", "maintenance-complete")
    completed = operating.Owner(config, transport=transport).run(1)
    assert completed["status"] == "complete", (initial, before, completed)
    assert before["state"] == "deferred" and before["attempt_id"] == attempts[0]
    assert len(sent) == 7 and owner.budget.snapshot()["calls"] == 7
    assert attempts[0] in owner.status()["nativeAttempts"]


def test_sqlite_locked_before_dispatch_preserves_native_proof(native, monkeypatch):
    kit, config, inputs, owner, sent, transport = native
    original = Budget.reserve
    attempts = []

    def locked_once(self, *args, **kwargs):
        if not attempts:
            attempts.append(args[0])
            with self._tx() as db:
                db.execute("CREATE TEMP TABLE contention_probe(value INTEGER)")
                db.executemany("INSERT INTO contention_probe VALUES(?)", [(1,), (2,)])
                cursor = db.execute("SELECT value FROM contention_probe")
                cursor.fetchone()
                try:
                    db.execute("DROP TABLE contention_probe")
                finally:
                    cursor.close()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Budget, "reserve", locked_once)
    result = owner.run(1)
    assert result["status"] == "blocked" and sent == []
    assert result["sets"][0]["s2"]["failure"]["code"] == "operating_ledger_busy"
    assert owner.run(1)["status"] == "complete" and len(sent) == 7
    assert attempts[0] in owner.status()["nativeAttempts"]


def test_corrupt_accounting_is_not_a_resumable_deferral(native, monkeypatch):
    kit, config, inputs, owner, sent, transport = native
    original = Budget.reserve

    def corrupt(self, *args, **kwargs):
        self.path.write_bytes(b"authored invalid sqlite header")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Budget, "reserve", corrupt)
    with pytest.raises(BudgetError, match="live_budget_unavailable"):
        owner.run(1)
    with sqlite3.connect((owner.directory("s2") / "extraction.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("SELECT state,verdict FROM calls").fetchall() == [("unsent", "live_budget_unavailable")]
        assert db.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'operating-deferral:%'").fetchone()[0] == 0
    assert sent == []


@pytest.mark.parametrize("outcome", ["unknown", "settled", "released"])
def test_unsent_proof_cannot_override_existing_attempt_outcome(monkeypatch, tmp_path, outcome):
    from tests.live_support import PAYLOADS
    from zoop_ai_pipeline.live_runtime import LiveDeferred

    def handler(request):
        if outcome == "unknown":
            raise httpx.ReadTimeout("authored unknown")
        return json_response(openai_reply({"mentions": []}))

    def denied():
        raise PermissionError("authored source refusal")

    with runtime_session(monkeypatch, tmp_path, handler) as (budget, runtime, fake):
        prepared = runtime.prepare("extract", PAYLOADS["extract"]())
        if outcome == "released":
            with pytest.raises(PermissionError):
                runtime.send(prepared, attempt_id="existing", authorize=denied)
        elif outcome == "unknown":
            with pytest.raises(LiveFailure) as caught:
                runtime.send(prepared, attempt_id="existing", authorize=lambda: None)
            assert caught.value.uncertain
        else:
            runtime.send(prepared, attempt_id="existing", authorize=lambda: None)
        proof = LiveDeferred("operating_ledger_busy", "existing", prepared["digest"]).proof
        with pytest.raises(LiveFailure, match="live_budget_attempt_duplicate") as duplicate:
            runtime.send(prepared, attempt_id="existing", authorize=lambda: None, unsent_proof=proof)
        assert not isinstance(duplicate.value, LiveDeferred)
        assert len(fake.requests) == (0 if outcome == "released" else 1)
        assert budget.snapshot()["states"] == {{"unknown": "reserved", "settled": "settled", "released": "released"}[outcome]: 1}
