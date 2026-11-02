"""Metered policy, durable ownership, physical request accounting and native completion; synthetic peers only."""
from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from scripts.extraction_smoke import FAKE_KEYS
from scripts.operating_smoke import fixture, policy, response, smoke
from tests.live_support import Fake, PAYLOADS, environment, json_response, openai_reply
from zoop_ai_pipeline import extraction, live_budget, live_runtime as live
from zoop_ai_pipeline.live_budget import Budget, BudgetError, NANO
from zoop_ai_pipeline.live_funding import MODE, STAGES, capped_set_funding_policy, operating_policy
from zoop_ai_pipeline.live_runtime import LiveFailure, LiveRuntime
from zoop_ai_pipeline.operating import Owner


def allowances(count=10):
    return {stage: count for stage in STAGES}


def reserve(budget, token, attempt, cost=100, request=None):
    budget.reserve(attempt, "extract", "recipient", request or attempt, cost, set_id="set-1", owner=token, binding_identity="binding")


@contextmanager
def runtime_session(monkeypatch, tmp_path, handler=None, endpoint=None):
    funding = policy()
    funding["requestTimeoutSeconds"] = 10
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(funding))
    environment(monkeypatch, tmp_path, **{live.MAX_USD_VAR: None, live.MAX_CALLS_VAR: None, live.PROFILE_VAR: MODE,
        live.POLICY_VAR: str(path), live.SET_VAR: "set-1", live.OPENAI_URL_VAR: endpoint, live.JEV_URL_VAR: endpoint})
    budget = Budget.initialize(tmp_path / "budget", funding)
    fake = Fake(handler or (lambda request: json_response(openai_reply({"mentions": []}))))
    with budget.owner() as token:
        monkeypatch.setenv(live.OWNER_VAR, token)
        runtime = LiveRuntime.from_env(need_send=True, transport=None if endpoint else fake.transport)
        budget.admit_operating_set("set-1", {"runtimeIdentity": runtime.binding()["identity"]}, allowances(), token)
        yield budget, runtime, fake


def send(runtime, attempt="attempt-1", stage="extract", authorize=lambda: None):
    return runtime.send(runtime.prepare(stage, PAYLOADS[stage]()), attempt_id=attempt, authorize=authorize)


def test_metered_exceeds_twenty_dollars_and_day_boundary_on_same_reopened_ledger(monkeypatch, tmp_path):
    clock = [1800000000.0]
    monkeypatch.setattr(live_budget.time, "time", lambda: clock[0])
    funding = policy()
    budget = Budget.initialize(tmp_path / "budget", funding)
    identity = budget.snapshot()["ledgerId"]
    with budget.owner() as token:
        budget.admit_operating_set("set-1", {"runtimeIdentity": "binding"}, allowances(3), token)
        reserve(budget, token, "a", 15 * NANO)
        budget.settle("a", 12_345_678_901)
    clock[0] += 90000
    reopened = Budget(tmp_path / "budget", None, None, policy=funding)
    with reopened.owner() as token:
        reserve(reopened, token, "b", 15 * NANO)
        reopened.settle("b", 13_000_000_009)
        reserve(reopened, token, "c", 7)
        reopened.settle("c", None)
        with pytest.raises(BudgetError, match="operating_stage_exhausted"):
            reserve(reopened, token, "d")
    snapshot = reopened.snapshot()
    assert snapshot["ledgerId"] == identity and snapshot["chargedUsd"] == "25.345678917"
    assert (snapshot["maxUsd"], snapshot["maxCalls"], snapshot["remainingUsd"]) == (None, None, None)
    assert snapshot["settledKnownUsageUsd"] == "25.345678910" and snapshot["settledUnknownUsageUsd"] == "0.000000007"
    assert snapshot["outstandingHoldUsd"] == "0.000000000" and snapshot["calls"] == 3
    with sqlite3.connect(reopened.path) as db:
        assert db.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 0


def test_caps_and_lifecycle_are_discriminated_and_old_cap_contract_stays_enforced(tmp_path):
    with pytest.raises(ValueError):
        operating_policy({**policy(), "maxUsd": None})
    with pytest.raises(ValueError):
        operating_policy({**policy(), "lifecycle": {}})
    with pytest.raises(BudgetError, match="live_budget_config_invalid"):
        Budget(tmp_path / "invalid", None, None)
    old = Budget(tmp_path / "old", 20, 1)
    old.reserve("old-a", "extract", "r", "d", 20)
    with pytest.raises(BudgetError, match="live_budget_exhausted_calls"):
        old.reserve("old-b", "extract", "r", "e", 1)
    with pytest.raises(BudgetError, match="operating_initialization_refused"):
        Budget.initialize(tmp_path / "old", policy())
    new = Budget.initialize(tmp_path / "new", policy())
    with pytest.raises(BudgetError, match="live_budget_policy_mismatch"):
        Budget(tmp_path / "new", 100, 10).snapshot()
    assert new.snapshot()["calls"] == 0


def test_metered_and_capped_authorities_keep_independent_admission_and_settlement(tmp_path, monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T01:00:00+00:00")
    metered_policy = policy()
    metered = Budget.initialize(tmp_path / "metered", metered_policy)
    capped_policy = capped_set_funding_policy("synthetic-merge", "2026-10-28T00:15:00Z", "2026-10-28T08:30:00Z",
                                            4 * NANO, 3 * NANO, NANO)
    capped = Budget(tmp_path / "capped", 4 * NANO, 10, funding=capped_policy,
                    bucket_caps=capped_policy["bucketMaxNanoUsd"])
    capped.admit_set("set-1", "a" * 64, {"extract": 1})
    route = capped_policy["roles"]["shared-openai"]
    capped.reserve("attempt-1", "extract", route["recipient"], "b" * 64, 100,
                   account_role="shared-openai", set_id="set-1")
    capped.settle("attempt-1", 7)
    with metered.owner() as token:
        metered.admit_operating_set("set-1", {"runtimeIdentity": "binding"}, allowances(1), token)
        reserve(metered, token, "attempt-1", 200)
        metered.settle("attempt-1", 11)
    capped_snapshot, metered_snapshot = capped.snapshot(), metered.snapshot()
    assert capped_snapshot["chargedUsd"] == "0.000000007" and capped_snapshot["maxUsd"] == "4.000000000"
    assert metered_snapshot["chargedUsd"] == "0.000000011" and metered_snapshot["maxUsd"] is None
    assert capped_snapshot["states"] == metered_snapshot["states"] == {"settled": 1}
    with pytest.raises(BudgetError, match="live_budget_policy_mismatch"):
        Budget(tmp_path / "metered", 4 * NANO, 10, funding=capped_policy,
               bucket_caps=capped_policy["bucketMaxNanoUsd"]).snapshot()
    with pytest.raises(BudgetError, match="operating_ledger_missing"):
        Budget(tmp_path / "capped", None, None, policy=metered_policy)
    with pytest.raises(BudgetError, match="live_budget_policy_mismatch"):
        Budget(tmp_path / "metered", None, None, policy=metered_policy, funding=capped_policy)
    assert capped.snapshot() == capped_snapshot and metered.snapshot() == metered_snapshot


@pytest.mark.parametrize("change", ["missing", "replacement"])
def test_missing_or_replaced_ledger_refuses_reopen_and_reinitialization(tmp_path, change):
    budget = Budget.initialize(tmp_path / "budget", policy())
    if change == "replacement":
        replacement = tmp_path / "copy.sqlite3"
        shutil.copyfile(budget.path, replacement)
        replacement.replace(budget.path)
    else:
        budget.path.unlink()
    with pytest.raises(BudgetError, match="operating_ledger_(missing|replaced)"):
        Budget(tmp_path / "budget", None, None, policy=policy())
    with pytest.raises(BudgetError, match="operating_initialization_refused"):
        Budget.initialize(tmp_path / "budget", policy())


def test_duplicate_attempt_and_logical_request_never_send_again(monkeypatch, tmp_path):
    with runtime_session(monkeypatch, tmp_path) as (budget, runtime, fake):
        receipt = send(runtime)
        assert LiveRuntime.from_binding(runtime.binding()).answer("extract", receipt) == {"mentions": []}
        with pytest.raises(LiveFailure, match="live_budget_attempt_duplicate"):
            send(runtime)
        with pytest.raises(LiveFailure, match="live_budget_request_duplicate"):
            send(runtime, "different-attempt")
        assert len(fake.requests) == 1 and budget.receipt("attempt-1") == receipt
        assert budget.snapshot()["chargedUsd"] == "0.000575000"


def test_single_owner_and_single_physical_send_cover_generation_and_verifier(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()

    async def handler(request):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return json_response(openai_reply({"mentions": []}))

    with runtime_session(monkeypatch, tmp_path, handler) as (budget, runtime, fake):
        with pytest.raises(BudgetError, match="operating_busy"):
            with budget.owner():
                pytest.fail("second owner admitted")
        outcomes = []
        thread = threading.Thread(target=lambda: outcomes.append(send(runtime)))
        thread.start()
        assert entered.wait(5)
        try:
            with pytest.raises(LiveFailure, match="operating_busy"):
                send(runtime, "verifier", "verify-relation")
        finally:
            release.set()
            thread.join(5)
        assert len(outcomes) == 1 and len(fake.requests) == 1 and budget.snapshot()["calls"] == 1


def test_presend_forced_stop_releases_only_proven_unsent_reservation(monkeypatch, tmp_path):
    with runtime_session(monkeypatch, tmp_path) as (budget, runtime, fake):
        with pytest.raises(LiveFailure, match="operating_stopped"):
            send(runtime, authorize=lambda: budget.control("force-stop", "authored-stop-race"))
        assert fake.requests == [] and budget.snapshot()["states"] == {"released": 1}
        assert budget.snapshot()["chargedUsd"] == "0.000000000"
        with pytest.raises(BudgetError, match="operating_control_terminal"):
            budget.control("resume", "not-a-pause")


def test_inflight_forced_stop_and_malformed_usage_keep_exposure(monkeypatch, tmp_path):
    holder = {}

    async def handler(request):
        holder["budget"].control("force-stop", "authored-inflight-stop")
        await asyncio.sleep(1)
        return json_response(openai_reply({"mentions": []}))

    with runtime_session(monkeypatch, tmp_path, handler) as (budget, runtime, fake):
        holder["budget"] = budget
        with pytest.raises(LiveFailure) as caught:
            send(runtime)
        assert caught.value.uncertain and len(fake.requests) == 1
        assert budget.snapshot()["states"] == {"reserved": 1}
        with pytest.raises(BudgetError, match="operating_release_not_proven_unsent"):
            budget.release("attempt-1")
    other = tmp_path / "malformed"
    other.mkdir()
    with runtime_session(monkeypatch, other, lambda r: json_response(openai_reply({"mentions": []}, usage={"prompt_tokens": -1}))) as (budget, runtime, fake):
        receipt = send(runtime)
        snapshot = budget.snapshot()
        assert receipt["cost"]["usageKnown"] is False and snapshot["control"]["state"] == "paused"
        assert snapshot["chargedUsd"] == snapshot["settledUnknownUsageUsd"] == receipt["cost"]["reservedUsd"]
        assert snapshot["outstandingHoldUsd"] == "0.000000000"
        with pytest.raises(LiveFailure, match="operating_paused"):
            send(runtime, "next", "relation")
        assert len(fake.requests) == 1


def test_pause_resume_history_and_soft_stop_drain_survive_reopen(monkeypatch, tmp_path):
    clock = [1800000000.0]
    monkeypatch.setattr(live_budget.time, "time", lambda: clock[0])
    budget = Budget.initialize(tmp_path / "budget", policy())
    with budget.owner() as token:
        budget.admit_operating_set("set-1", {"runtimeIdentity": "binding"}, allowances(), token)
    budget.control("pause", "maintenance")
    reopened = Budget(tmp_path / "budget", None, None, policy=policy())
    with reopened.owner() as token:
        with pytest.raises(BudgetError, match="operating_paused"):
            reserve(reopened, token, "paused")
        reopened.control("resume", "maintenance-complete")
        reserve(reopened, token, "a")
        reopened.settle("a", 1)
        reopened.control("stop", "finite-drain")
        with pytest.raises(BudgetError, match="operating_stopping"):
            reopened.admit_operating_set("new-set", {"runtimeIdentity": "binding"}, allowances(), token)
        reserve(reopened, token, "drained")
        reopened.settle("drained", 2)
        clock[0] += 601
        with pytest.raises(BudgetError, match="operating_stopping"):
            reserve(reopened, token, "too-late")
    with sqlite3.connect(reopened.path) as db:
        assert db.execute("SELECT action,reason FROM operating_history WHERE action IN ('pause','resume','stop') ORDER BY seq").fetchall() == [
            ("pause", "maintenance"), ("resume", "maintenance-complete"), ("stop", "finite-drain")]


@pytest.mark.parametrize("mode", ["headers", "stalled-body", "trickle"])
def test_absolute_request_deadline_closes_delayed_headers_and_body(monkeypatch, tmp_path, mode):
    done = threading.Event()
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            hits.append(1)
            try:
                if mode == "headers":
                    done.wait(2)
                self.send_response(200)
                self.send_header("Content-Length", "100000")
                self.end_headers()
                if mode == "stalled-body":
                    done.wait(2)
                else:
                    while not done.wait(0.03):
                        self.wfile.write(b" ")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with runtime_session(monkeypatch, tmp_path, endpoint=f"http://127.0.0.1:{server.server_port}/v1") as (budget, runtime, fake):
            monkeypatch.setattr(runtime, "_timeout", 0.3)
            start = time.monotonic()
            with pytest.raises(LiveFailure) as caught:
                send(runtime)
            elapsed = time.monotonic() - start
            assert caught.value.uncertain and 0.25 <= elapsed < 1.2 and hits == [1]
            assert budget.snapshot()["states"] == {"reserved": 1}
    finally:
        done.set()
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def native(monkeypatch, tmp_path):
    for name in (live.MAX_USD_VAR, live.MAX_CALLS_VAR, live.PROFILE_VAR):
        monkeypatch.delenv(name, raising=False)
    for name, value in {live.GATE: "1", **FAKE_KEYS}.items():
        monkeypatch.setenv(name, value)
    kit, config, inputs = fixture(tmp_path, "https://synthetic.invalid/v1")
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        return json_response(response(body))

    transport = httpx.MockTransport(handler)
    owner = Owner(config, initialize=True, transport=transport)
    kit.allow_model_send(owner.runtime(inputs["sets"][0], "offline"), STAGES)
    owner.register(inputs)
    return kit, config, inputs, owner, sent, transport


def test_native_progress_and_receipt_recovery_reuse_original_attempts(native, monkeypatch):
    kit, config, inputs, owner, sent, transport = native

    def crash_before_native_receipt(self, attempt, receipt):
        raise SystemExit(75)

    with monkeypatch.context() as patch:
        patch.setattr(extraction.Extractor, "_receive", crash_before_native_receipt)
        with pytest.raises(SystemExit):
            owner.run(1)
    assert len(sent) == 1 and owner.budget.snapshot()["states"] == {"settled": 1}
    restarted = Owner(config, transport=transport)
    pending = restarted.status()
    assert len(pending["reconciliation"]["receiptsAwaitingNativeRecovery"]) == 1
    result = restarted.run(1)
    assert result["status"] == "complete" and result["sets"][0]["recoveredReceipts"] == 1
    assert result["sets"][0]["s2"]["jobId"] == "native-s2-1" and result["sets"][0]["s3"]["jobId"] == "native-s3-1"
    assert len(sent) == 7 and restarted.run(1)["sets"] == [] and len(sent) == 7
    status = restarted.status()
    assert status["reconciliation"] == {"monetaryWithoutNative": [], "nativeWithoutMonetary": [], "receiptsAwaitingNativeRecovery": []}
    assert status["metering"]["chargedUsd"] == "0.002409000"
    assert len(status["monetaryAttempts"]) == len(status["nativeAttempts"]) == 7


def test_registered_native_input_revocation_refuses_dispatch(native):
    kit, config, inputs, owner, sent, transport = native
    kit.registry["sources"][0]["grant"]["allowedOperations"] = ["read", "store", "quote-display"]
    kit.save_registry()
    result = owner.run(1)
    assert result["status"] == "blocked" and result["sets"][0]["s2"]["failure"]["code"] == "source_operation_denied"
    assert sent == [] and owner.budget.snapshot()["calls"] == 0


def test_new_batch_and_lost_native_state_keep_same_ledger(native):
    kit, config, inputs, owner, sent, transport = native
    assert owner.run(1)["status"] == "complete"
    first_id = owner.budget.snapshot()["ledgerId"]
    second = json.loads(json.dumps(inputs))
    second["sets"][0].update(setId="set-2", relationJobId="native-s3-2")
    second["sets"][0]["extraction"]["jobId"] = "native-s2-2"
    restarted = Owner(config, transport=transport)
    restarted.register(second)
    assert restarted.run(1)["status"] == "complete"
    assert restarted.budget.snapshot()["ledgerId"] == first_id and restarted.budget.snapshot()["calls"] == 14
    (restarted.directory("s2") / "extraction.sqlite3").unlink()
    with pytest.raises(BudgetError, match="operating_native_state_missing"):
        restarted.status()


def test_cli_subprocess_loopback_smoke(tmp_path):
    result = smoke(tmp_path)
    assert result["status"] == "passed" and result["metering"]["calls"] == 7


def test_different_source_context_is_refused_without_rebasing_grants(native, tmp_path):
    first_kit, config, first_inputs, owner, sent, transport = native
    second_kit, _, second_inputs = fixture(tmp_path / "second-source", "https://synthetic.invalid/v1")
    unit = second_inputs["sets"][0]
    unit.update(setId="set-2", relationJobId="native-s3-2")
    unit["extraction"]["jobId"] = "native-s2-2"
    second_kit.registry["sources"][0]["grant"]["grantId"] = "operator-grant-two"
    second_kit.allow_model_send(owner.runtime(unit, "offline"), STAGES)
    with pytest.raises(BudgetError, match="operating_source_context_changed"):
        owner.register(second_inputs)
    assert owner.budget.bound("job:native-s2-2") is None
    assert owner.budget.snapshot()["sets"] == {"admitted": 1, "complete": 0}
    assert owner.run(1)["status"] == "complete" and len(sent) == 7
    current = first_inputs["sets"][0]
    with owner.native(current, "s2") as store:
        binding = json.loads(store.one("SELECT binding FROM jobs WHERE job_id=?", (current["extraction"]["jobId"],))["binding"])
        assert {doc["grant"]["grantId"] for doc in binding["documents"].values()} == {"operator-grant"}
