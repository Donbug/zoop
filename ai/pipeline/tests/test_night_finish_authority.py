"""Fresh v3 authority, actual native CLI/loopback and shared acquisition admission.

Only clock inputs and provider transport addresses are controlled. Deadline and
admission predicates, SQLite authority, native CLIs and source grants are real.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE), str(PIPELINE / "scripts")]
from scripts import overnight_collect as collect, overnight_run as runner
from scripts.collection_smoke import LocalSite
from scripts.extraction_smoke import LiveWorld, simulator_env
from scripts.korea_corpus_smoke import article, config as native_config, listing
from tests.live_support import extract_payload
from tests.test_extraction_live import ChainPeer, chain_cli, chain_receipts
from tests.test_overnight_collection_behavior import Clock, ProcessBoundary, frozen
from zoop_ai_pipeline import direct_deepseek, live_budget, live_funding, live_runtime as live
from zoop_ai_pipeline.korea_portal import ROUTES

START, END, FINISH = "2026-10-28T12:00:00Z", "2026-10-28T21:00:00Z", "2026-10-28T22:00:00Z"


@pytest.fixture
def night(tmp_path, monkeypatch):
    clock = SimpleNamespace(moment=datetime(2026, 10, 28, 20, tzinfo=timezone.utc))
    class ControlledClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.moment
    monkeypatch.setattr(live_budget, "_now", lambda: clock.moment.isoformat())
    monkeypatch.setattr(live_funding, "datetime", ControlledClock)
    monkeypatch.setattr(runner, "datetime", ControlledClock)
    root = (tmp_path / "night").resolve()
    config = {"schemaVersion": "zoop-private-run-4", "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"}, "runId": "finish-authority-test", "root": str(root),
              "admitFrom": START, "admitUntil": END, "finishBy": FINISH, "graphPort": 32829, "maxCalls": 100000,
              "processingActor": {"kind": "user-private-experiment", "acceptedBy": "Main", "decidedAt": START,
                                  "statement": "Synthetic offline authorization; no external collection or paid calls."}}
    path = tmp_path / "run-config.json"
    runner.save(path, config)
    index = root / "collection/INDEX.json"
    runner.save(index, {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": []})
    for name in ("RUN_CONFIG", "RUN_CONFIG_PATH", "ROOT", "RUN_ID", "ADMIT_UNTIL", "GRAPH_PORT", "MAX_CALLS"):
        monkeypatch.setattr(runner, name, getattr(runner, name))
    args = runner.parse(["--check", "--run-config", str(path), "--collection-index", str(index)])
    runner.configure(args)
    env = {**simulator_env(live_funding.OPENAI_URL, root / "modelbudget"), **runner.profile_env(root, "luna"),
           live.SET_ID_VAR: "set-native", direct_deepseek.KEY_VAR: "synthetic-direct-test-key"}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    budget = runner.funding(root)
    budget.snapshot()
    return SimpleNamespace(root=root, config=config, args=args, env=env, clock=clock, budget=budget)


def native_world(night):
    world = LiveWorld(night.root / "world", night.env)
    world.kit.allow_model_send(world.runtime, live.STAGES)
    world.kit.registry["sources"][0]["grant"]["recipients"].append(world.runtime.fallback_recipient("extract"))
    world.kit.save_registry()
    world.budget = night.budget
    world.budget.admit_set("set-native", "a" * 64, dict.fromkeys(live_funding.GENERATION_STAGES + live_funding.VERIFY_STAGES, 8))
    return world


def clock_hook(current, *, after_request=None):
    hook = f"""
from datetime import datetime as RealDateTime
from zoop_ai_pipeline import live_funding
clock = [RealDateTime.fromisoformat({current!r}.replace('Z', '+00:00'))]
class Clock(RealDateTime):
    @classmethod
    def now(cls, tz=None):
        return clock[0]
live_funding.datetime = Clock
live_budget._now = lambda: clock[0].isoformat()
"""
    if after_request:
        hook += f"""
previous_transport = httpx.HTTPTransport.handle_request
def advance_after_transport(self, request):
    try:
        return previous_transport(self, request)
    finally:
        clock[0] = RealDateTime.fromisoformat({after_request!r}.replace('Z', '+00:00'))
httpx.HTTPTransport.handle_request = advance_after_transport
"""
    return hook


@pytest.mark.parametrize("override", [None, "2030-01-01T00:00:00Z"])
def test_actual_cli_missing_or_extended_send_override_cannot_remove_finish(night, override):
    world = native_world(night)
    if override is None:
        world.env.pop(live_funding.SEND_BEFORE_ENV, None)
    else:
        world.env[live_funding.SEND_BEFORE_ENV] = override
    with ChainPeer() as peer:
        out = chain_cli(world, peer, "run", world.request("late", topic=False),
                        hook=clock_hook("2026-10-28T21:52:00Z"))
        assert out["state"] == "stopped" and out["failure"]["code"] == "live_finish_deadline"
        assert peer.requests == []
        assert world.budget.snapshot()["chargedUsd"] == "0.000000000"
        assert world.budget.snapshot()["finishAuthority"] == live_funding.finish_policy(FINISH)


def test_actual_cli_requires_finish_and_changed_finish_rebinds_request_and_readiness(night, monkeypatch):
    world = native_world(night)
    original = world.runtime.binding()
    prepared = world.runtime.prepare("extract", extract_payload())
    world.env.pop(live.FINISH_BY_VAR)
    with ChainPeer() as peer:
        refused = chain_cli(world, peer, "run", world.request("missing-finish"), expected=2,
                            hook=clock_hook("2026-10-28T20:00:00Z"))
        assert refused["error"]["code"] == "live_finish_policy_required" and peer.requests == []
    monkeypatch.setenv(live.FINISH_BY_VAR, "2026-10-28T22:01:00Z")
    changed = live.LiveRuntime.from_env()
    assert not changed.accepts(original)
    assert changed.prepare("extract", extract_payload())["digest"] != prepared["digest"]
    assert live.LiveRuntime.from_binding(original).binding() == original
    pins = {"codePins": runner.code_pins(), "runConfig": night.config,
            "funding": {"policyVersion": original["funding"]["version"], "policyIdentity": runner.sha(runner.encoded(original["funding"])),
                        "totalMaxNanoUsd": 4_000_000_000, "bucketMaxNanoUsd": {"shared": 3_500_000_000, "personal": 500_000_000}, "maxCalls": 100000},
            "identityPolicy": runner.POLICY, "runtimeBindings": {"luna": {"pipeline": original}}}
    replacement = {**pins, "runConfig": {**night.config, "finishBy": "2026-10-28T22:01:00Z"},
                   "runtimeBindings": {"luna": {"pipeline": changed.binding()}}}
    assert runner.provider_approval_digest(pins) != runner.provider_approval_digest(replacement)
    before = night.budget.path.read_bytes()
    with pytest.raises(live_budget.BudgetError, match="live_finish_policy_mismatch"):
        changed._send["budget"].snapshot()
    assert night.budget.path.read_bytes() == before


@pytest.mark.parametrize("response", [None, "http500", "unknown"])
def test_actual_cli_second_request_or_fallback_stops_at_finish_without_erasing_first(night, response):
    world = native_world(night)
    with ChainPeer() as peer:
        peer.behavior["openai", "extract"] = response
        out = chain_cli(world, peer, "run", world.request("cross-boundary", topic=False),
                        hook=clock_hook("2026-10-28T20:00:00Z", after_request="2026-10-28T21:52:00Z"))
        assert [(role, stage) for role, stage, _ in peer.requests] == [("openai", "extract")]
        saved = chain_receipts(world)
        if response == "unknown":
            assert out["state"] == "reconciling" and out["resumeMode"] == "reconcile_only"
            assert world.budget.snapshot()["states"] == {"reserved": 1}
        else:
            assert out["state"] == "stopped" and out["failure"]["code"] == "live_finish_deadline"
            assert out["usage"]["receivedCalls"] == 1
            assert world.budget.snapshot()["states"] == {"settled": 1}
        again = chain_cli(world, peer, "inspect", world.kit.job_selector("cross-boundary"), live=False)
        assert again["usage"] == out["usage"]
        assert chain_receipts(world) == saved and len(peer.requests) == 1


def test_unchanged_fetch_budget_handle_enforces_persisted_full_timeout_boundary(night):
    borrowed = live_budget.Budget(night.root / "modelbudget", 4 * live_budget.NANO, 100000,
        funding=live_funding.run_policy(night.config), bucket_caps={"shared": 3_500_000_000, "personal": 500_000_000})
    night.budget.admit_set("fetch-set", "a" * 64, {"fetch": 4})
    night.clock.moment = datetime(2026, 10, 28, 21, 51, 59, 999999, tzinfo=timezone.utc)
    borrowed.reserve("known", "fetch", "deepseek-fetch", "b" * 64, 750000,
                     account_role="personal-deepseek", set_id="fetch-set")
    borrowed.check_send("known")
    borrowed.settle("known", 750000)
    borrowed.reserve("unknown", "fetch", "deepseek-fetch", "c" * 64, 750000,
                     account_role="personal-deepseek", set_id="fetch-set")
    night.clock.moment += timedelta(microseconds=1)
    with pytest.raises(live_budget.BudgetError, match="live_finish_deadline"):
        borrowed.check_send("unknown")
    with pytest.raises(live_budget.BudgetError, match="live_finish_deadline"):
        borrowed.reserve("late", "fetch", "deepseek-fetch", "d" * 64, 750000,
                         account_role="personal-deepseek", set_id="fetch-set")
    assert borrowed.snapshot()["states"] == {"reserved": 1, "settled": 1}
    assert borrowed.snapshot()["buckets"]["personal"]["reservedUsd"] == "0.000750000"


def test_finish_authority_never_retrofits_a_historical_set_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T20:00:00Z")
    policy = live_funding.set_funding_policy("historical", START, END)
    old = live_budget.Budget(tmp_path / "budget", 20 * live_budget.NANO, 100000, funding=policy)
    old.admit_set("old", "a" * 64, {"fetch": 1})
    old.reserve("old-unknown", "fetch", "deepseek-fetch", "b" * 64, 750000,
                account_role="personal-deepseek", set_id="old")
    original = old.path.read_bytes()
    with pytest.raises(live_budget.BudgetError, match="live_finish_policy_mismatch"):
        live_budget.Budget(tmp_path / "budget", 20 * live_budget.NANO, 100000, funding=policy, finish_by=FINISH).snapshot()
    assert old.path.read_bytes() == original
    assert old.snapshot()["states"] == {"reserved": 1} and "finishAuthority" not in old.snapshot()


@pytest.mark.parametrize("kind", ["native", "official", "hn", "private"])
@pytest.mark.parametrize("stop", ["TERM", "INT", "cutoff", "local-pause"])
def test_cross_owner_stop_fences_every_collector_kind_atomically(night, frozen, monkeypatch, kind, stop):
    root, manifest, ledger = frozen(hosts=("first.test", "next.test"), concurrency=1)
    clock = Clock()
    clock.value = night.clock.moment
    manifest["options"]["stopNewWorkAt"] = END
    manifest["plans"][1]["kind"] = kind
    if kind == "private":
        manifest["plans"][1]["funding"] = {"setId": "acquisition:set-1", "unitDigest": "b" * 64,
                                            "allowance": {"fetch": 1}}
    controller = runner.Controller(night.args)
    boundary = ProcessBoundary(clock, finishes={"set-0": 3})
    def interrupt(current):
        night.clock.moment = current.now()
        if current.ticks == 1:
            if stop == "local-pause":
                controller.pause()
            elif stop == "cutoff":
                night.clock.moment = datetime.fromisoformat(END.replace("Z", "+00:00"))
                clock.value = night.clock.moment
            else:
                controller.stop(signal.SIGTERM if stop == "TERM" else signal.SIGINT, None)
            controller.sync_stop()
    clock.on_sleep = interrupt
    collect.execute(root, manifest, ledger, launch=boundary, now=clock.now, sleep=clock.sleep,
                    disk_free=lambda: 10**12, budget=night.budget)
    assert boundary.finished == boundary.launched
    if stop == "local-pause":
        assert boundary.launched == ["set-0", "set-1"]
        assert night.budget.snapshot()["stopIntent"] is None
    else:
        assert boundary.launched == ["set-0"]
        assert ledger["plans"]["set-1"]["status"] == "not_started"
        assert night.budget.set_status("acquisition:set-1") is None
        assert night.budget.snapshot()["stopIntent"]["reason"] == ("admission_cutoff" if stop == "cutoff" else "soft_signal")
    assert night.budget.snapshot()["chargedUsd"] == "0.000000000"


def test_stop_between_collector_check_and_admission_cannot_launch(night, frozen, monkeypatch):
    root, manifest, ledger = frozen(hosts=("one.test",), concurrency=1)
    manifest["options"]["stopNewWorkAt"] = END
    admit = night.budget.admit_set
    other_owner = live_budget.Budget(night.root / "modelbudget", 4 * live_budget.NANO, 100000,
        funding=live_funding.run_policy(night.config), bucket_caps={"shared": 3_500_000_000, "personal": 500_000_000})
    def close_before_atomic_admission(*args):
        other_owner.close_admission("analysis-stop")
        return admit(*args)
    monkeypatch.setattr(night.budget, "admit_set", close_before_atomic_admission)
    boundary = ProcessBoundary(Clock())
    collect.execute(root, manifest, ledger, launch=boundary, now=lambda: night.clock.moment,
                    sleep=lambda _: pytest.fail("closed admission must not wait"), disk_free=lambda: 10**12, budget=night.budget)
    assert boundary.launched == [] and night.budget.snapshot()["sets"] == {}
    assert ledger["held"] == {"requests": 0, "bytes": 0}


def test_real_native_collector_drains_before_shared_stop_blocks_next_plan(night, frozen):
    root, manifest, ledger = frozen(hosts=("127.0.0.1", "next.test"), concurrency=1)
    manifest["options"]["stopNewWorkAt"] = END
    site = LocalSite()
    controller = runner.Controller(night.args)
    children = []
    try:
        value, _ = native_config(root / "authored-native", site, planId="set-0", stateDir=str(root / "state/set-0"))
        first = manifest["plans"][0]
        first.update(kind="native", sourceId="korea-portal", configTemplate=value)
        first["ceilings"] = {"requests": value["policy"]["maxRequests"], "bytes": value["policy"]["maxTotalBytes"],
                             "seconds": value["policy"]["maxTotalSeconds"]}
        manifest["options"]["caps"]["bytes"] = 10000000
        manifest["sourceMatrix"][0]["kind"] = "native"
        site.route("/robots.txt", b"User-agent: *\nAllow: /\n", content_type="text/plain")
        site.route(ROUTES["policy-news"][0], listing(["100000001"]))
        def stop_analysis():
            controller.stop(signal.SIGTERM, None)
            controller.sync_stop()
        site.route(ROUTES["policy-news"][1], article(site, "100000001"), hook=stop_analysis)
        def launch(*args, **kwargs):
            child = collect.RunningChild(*args, **kwargs)
            children.append(child)
            return child
        collect.execute(root, manifest, ledger, launch=launch, now=lambda: night.clock.moment,
                        disk_free=lambda: 10**12, budget=night.budget)
        assert len(children) == 1 and children[0].poll() == 0
        assert ledger["plans"]["set-0"]["summary"]["counts"]["exported"] == 1
        assert ledger["plans"]["set-1"]["status"] == "not_started"
        assert site.hits(ROUTES["policy-news"][1]) == 1
        assert night.budget.snapshot()["sets"] == {"completed": 1}
        assert night.budget.snapshot()["calls"] == 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        site.close()


def test_real_child_finish_uses_configured_clock_not_a_replaced_deadline_predicate(night):
    controller = runner.Controller(night.args)
    ready = night.root / "child-ready"
    script = "from pathlib import Path; import sys,time; Path(" + repr(str(ready)) + ").write_text('ready'); time.sleep(30); sys.stdin.buffer.read()"
    def advance_clock():
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if ready.exists():
            night.clock.moment = datetime(2026, 10, 28, 21, 57, tzinfo=timezone.utc)
    observer = threading.Thread(target=advance_clock)
    observer.start()
    try:
        with pytest.raises(runner.Refused, match="controller_finish_deadline"):
            controller.command([sys.executable, "-c", script], finite_work=True,
                               payload={"text": "synthetic delayed stdin\n" * 50000})
    finally:
        observer.join(timeout=11)
    assert ready.read_text() == "ready" and controller.child_reaped and controller.child is None
    assert runner.load(night.root / "control/finish-intent.json")["finishBy"] == FINISH
    assert night.budget.snapshot()["stopIntent"]["reason"] == "finish_deadline"


def test_finish_rechecked_after_payload_spooling_before_spawn(night, monkeypatch):
    controller = runner.Controller(night.args)
    encode = runner.encoded
    def encode_at_finish(payload):
        raw = encode(payload)
        night.clock.moment = datetime(2026, 10, 28, 21, 57, tzinfo=timezone.utc)
        return raw
    monkeypatch.setattr(runner, "encoded", encode_at_finish)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("late input must not spawn"))
    with pytest.raises(runner.Refused, match="controller_finish_deadline") as refused:
        controller.command([sys.executable, "-c", "raise SystemExit(99)"], finite_work=True,
                           payload={"text": "synthetic delayed spool\n" * 50000})
    assert refused.value.unknown is False and controller.child is None
    assert night.budget.snapshot()["calls"] == 0
    assert night.budget.snapshot()["stopIntent"]["reason"] == "finish_deadline"
