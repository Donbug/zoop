"""Round identity, crash, admission and HTTP-scope invariants without provider execution."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from support import Workspace
from zoop_ai_service.handoff_reads import HandoffError
from zoop_ai_service.jobs import ApiError
from zoop_ai_service.relation_runtime import RelationGate
from zoop_ai_service.round_service import HandoffRouter, RoundService
from zoop_ai_service.round_store import RoundStore
from zoop_ai_service.round_wire import HandoffRequest, HandoffStatus, RunStatus
from zoop_ai_service.runtime import Outcome

ROUND = "round-20261031T0905"
BINDINGS = {"schemaVersion": "zoop-app-document-bindings-1", "bindings": []}


def facade(store):
    service = object.__new__(RoundService)
    service.store, service.gate = store, RelationGate()
    service.clock = lambda: datetime(2026, 10, 31, 9, 5, tzinfo=timezone.utc).timestamp()
    service._operation = threading.Lock()
    service._wake, service._stop = threading.Event(), threading.Event()
    service._log = lambda event: None
    service.profile = SimpleNamespace(max_age_seconds=86400, limit=8, source_id="shared", scope_id="scope",
                                      initial_from="2026-10-30T00:00:00+09:00", descriptor={})
    return service


def test_exact_request_bytes_and_owner_survive_restart(tmp_path):
    root, binding = tmp_path.resolve(), {"profile": "authored-private-profile"}
    raw = b'{"schemaVersion":"zoop-ai-round-run-1","roundId":"round-20261031T0905"}'
    store = RoundStore(root, binding)
    created, row = store.reserve("alpha", "run", ROUND, raw, {"started": True, "selection": {"asOf": "2026-10-31T00:05:00Z"}})
    assert created and store.get("beta", "run", ROUND) is None
    store.close()
    store = RoundStore(root, binding)
    try:
        recreated, preserved = store.reserve("alpha", "run", ROUND, raw, {})
        assert not recreated
        assert preserved["result"]["state"] == "failed"
        assert preserved["result"]["code"] == "round_outcome_unknown"
        assert preserved["context"]["selection"] == {"asOf": "2026-10-31T00:05:00Z"}
        assert preserved["body"] == raw
        with pytest.raises(ApiError) as conflict:
            store.reserve("alpha", "run", ROUND, raw + b"\n", {})
        assert (conflict.value.status, conflict.value.code) == (409, "request_conflict")
        assert store.pending() == []
    finally:
        store.close()


def test_profile_busy_is_atomic_across_principals_and_families_and_replay_wins(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "slot"})
    try:
        _, first = store.reserve("alpha", "run", ROUND, b"original", {"started": False})
        assert store.reserve("alpha", "run", ROUND, b"original", {})[0] is False
        for owner, family in (("beta", "run"), ("alpha", "handoff"), ("beta", "handoff")):
            with pytest.raises(ApiError) as busy:
                store.reserve(owner, family, ROUND, b"other", {}, preflight=lambda: pytest.fail("busy executed preflight"))
            assert busy.value.code == "round_busy"
            assert store.get(owner, family, ROUND) is None
        assert not any(path.is_dir() for path in store.root.iterdir())
        store.save(first, {"schemaVersion": "zoop-ai-round-run-1", "roundId": ROUND, "state": "failed", "code": "round_outcome_unknown"})
        barrier = threading.Barrier(3)
        outcomes = []

        def admit(owner):
            barrier.wait()
            try:
                outcomes.append(store.reserve(owner, "handoff", ROUND, b"request", {})[0])
            except ApiError as error:
                outcomes.append(error.code)

        threads = [threading.Thread(target=admit, args=(owner,)) for owner in ("alpha", "beta")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(2)
        assert sorted(map(str, outcomes)) == ["True", "round_busy"]
    finally:
        store.close()


def test_dormant_incomplete_reacquires_only_a_free_profile_slot(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "dormant"})
    try:
        _, waiting = store.reserve("alpha", "handoff", ROUND, b"freeze", {"started": True})
        store.save(waiting, {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": ROUND,
                             "state": "analysis_incomplete", "code": "analysis_incomplete"})
        _, running = store.reserve("beta", "run", ROUND, b"run", {"started": False})
        assert store.claim(waiting) is None
        store.save(running, {"schemaVersion": "zoop-ai-round-run-1", "roundId": ROUND, "state": "failed", "code": "test_failed"})
        assert store.claim(waiting)["result"]["state"] == "running"
    finally:
        store.close()


def test_initial_completion_refusal_writes_no_admission_or_private_bindings(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "preflight"})
    service = facade(store)
    body = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": ROUND, "bindings": BINDINGS}
    service.process = SimpleNamespace(completion=lambda body: Outcome("error", code="analysis_incomplete", exit_code=2, started=True))
    before = store.db.total_changes
    try:
        with pytest.raises(ApiError) as error:
            service.submit("alpha", "handoff", body, json.dumps(body).encode(), SimpleNamespace(runtime=[]))
        assert (error.value.status, error.value.code) == (409, "analysis_incomplete")
        assert store.db.total_changes == before
        assert store.get("alpha", "handoff", ROUND) is None
        assert not any(path.is_dir() for path in store.root.iterdir())
        with pytest.raises(ApiError) as absent:
            service.status("alpha", "handoff", ROUND, SimpleNamespace(runtime=[]))
        assert (absent.value.status, absent.value.code) == (404, "round_not_found")
    finally:
        store.close()


def test_accepted_readiness_race_waits_but_unknown_started_freeze_is_terminal(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "race"})
    service = facade(store)
    body = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": ROUND, "bindings": BINDINGS}
    complete = Outcome("result", result={"schemaVersion": "zoop-ai-handoff-1", "roundId": ROUND, "state": "complete"}, exit_code=0, started=True)
    service.process = SimpleNamespace(completion=lambda body: complete, freeze=lambda *args: Outcome("timeout", started=True))
    try:
        assert service.submit("alpha", "handoff", body, json.dumps(body).encode(), SimpleNamespace(runtime=[])).status == 202
        service.process.completion = lambda body: Outcome("error", code="analysis_incomplete", exit_code=2, started=True)
        assert service.step()
        assert service.status("alpha", "handoff", ROUND, SimpleNamespace(runtime=[])).body.state == "analysis_incomplete"
        assert not any(path.is_dir() for path in store.root.iterdir())
        service.process.completion = lambda body: complete
        assert service.step()
        assert service.status("alpha", "handoff", ROUND, SimpleNamespace(runtime=[])).body.code == "round_outcome_unknown"
        assert service.submit("alpha", "handoff", body, json.dumps(body).encode(), SimpleNamespace(runtime=[])).status == 200
        assert not service.step()
    finally:
        store.close()


def test_window_empty_preserves_all_withheld_selection_and_creates_no_grant(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "empty"})
    service = facade(store)
    body = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": ROUND, "bindings": BINDINGS}
    selection = {"schemaVersion": "zoop-ai-handoff-selection-1", "roundId": ROUND, "planId": None, "limit": 20,
                 "jobs": [{"jobId": "old", "status": "withheld", "code": "analysis_contract_changed"}]}
    service._analysis_complete = lambda *args: True
    service.process = SimpleNamespace(freeze=lambda *args: Outcome("error", code="window_empty", exit_code=2, started=True,
                                      result={"schemaVersion": "zoop-ai-handoff-1", "error": {"code": "window_empty", "detail": {"selection": selection}}}))
    try:
        service.submit("alpha", "handoff", body, json.dumps(body).encode(), SimpleNamespace(runtime=[]))
        assert service.step()
        status = service.status("alpha", "handoff", ROUND, SimpleNamespace(runtime=[])).body.wire()
        assert status["state"] == "no_public_material" and status["code"] == "window_empty"
        assert status["selection"] == selection and "handoffId" not in status
        assert store.db.execute("SELECT count(*) FROM grants").fetchone()[0] == 0
    finally:
        store.close()


def test_ready_and_read_grant_commit_together_and_pin_conflict_rolls_back(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "test"})
    try:
        _, first = store.reserve("alpha", "handoff", ROUND, b"first", {})
        ready = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": ROUND, "state": "ready", "handoffId": "hr-" + "a" * 64,
                 "manifestDigest": "b" * 64, "bundleDigest": "c" * 64}
        store.save(first, ready, grant=True)
        assert store.grant("alpha", ready["handoffId"])["bundle_digest"] == "c" * 64
        assert store.get("alpha", "handoff", ROUND)["result"] == ready
        other = "round-20261031T0935"
        _, second = store.reserve("alpha", "handoff", other, b"second", {})
        with pytest.raises(ApiError):
            store.save(second, {**ready, "roundId": other, "bundleDigest": "d" * 64}, grant=True)
        assert store.get("alpha", "handoff", other)["result"]["state"] == "running"
        assert store.grant("alpha", ready["handoffId"])["bundle_digest"] == "c" * 64
        assert store.grant("beta", ready["handoffId"]) is None
        with store.db:
            store.db.execute("UPDATE grants SET active=0")
        service = facade(store)
        router = HandoffRouter(SimpleNamespace(status=lambda *args: pytest.fail("revoked round fell back to static grant")), service)
        with pytest.raises(HandoffError, match="handoff_not_allowed"):
            router.status("alpha", ready["handoffId"], SimpleNamespace(runtime=[]))
    finally:
        store.close()


def test_full_bindings_are_closed_and_terminal_pins_are_state_specific():
    body = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": ROUND, "bindings": BINDINGS}
    assert HandoffRequest.model_validate(body).wire() == body
    for invalid in ({**body, "bindings": json.dumps(BINDINGS)}, {**body, "canonical": "/caller/path"}):
        with pytest.raises(ValidationError):
            HandoffRequest.model_validate(invalid)
    with pytest.raises(ValidationError):
        RunStatus.model_validate({"roundId": ROUND, "state": "ready", "observedAt": "2026-10-31T00:05:00Z"})
    with pytest.raises(ValidationError):
        HandoffStatus.model_validate({"roundId": ROUND, "state": "no_public_material", "code": "window_empty", "observedAt": "2026-10-31T00:05:00Z"})


def test_round_scope_precedes_disabled_profile(start, tmp_path):
    workspace = Workspace(tmp_path / "disabled-rounds")
    workspace.credentials.scopes["alpha"] += ["round.run", "round.read"]
    service = start(workspace=workspace)
    request = {"schemaVersion": "zoop-ai-round-run-1", "roundId": ROUND}
    denied = service.request("POST", "/internal/v1/round-runs", as_="beta", body=request, key=ROUND)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "scope_denied"
    disabled = service.request("POST", "/internal/v1/round-runs", body=request, key=ROUND)
    assert disabled.status_code == 503 and disabled.json()["error"]["code"] == "execution_unavailable"


def test_get_is_observational_and_stale_claim_cannot_redispatch(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "claim"})
    try:
        _, pending = store.reserve("alpha", "run", ROUND, b"request", {"started": False})
        service = facade(store)
        service.process = SimpleNamespace(tick=lambda *args: pytest.fail("GET started native child"))
        stale = store.get("alpha", "run", ROUND)
        assert service.status("alpha", "run", ROUND, SimpleNamespace(runtime=[])).body.state == "running"
        claimed = store.claim(pending)
        store.save(claimed, {"schemaVersion": "zoop-ai-round-run-1", "roundId": ROUND, "state": "failed", "code": "round_outcome_unknown"})
        assert store.claim(stale) is None
        assert service.status("alpha", "run", ROUND, SimpleNamespace(runtime=[])).body.code == "round_outcome_unknown"
        assert not any(path.is_dir() for path in store.root.iterdir())
    finally:
        store.close()


def test_exact_observation_claims_cross_principals_and_survive_crash(tmp_path):
    root, binding = tmp_path.resolve(), {"profile": "observation"}
    ref = {"roundId": "slot-native", "sourceId": "shared", "page": 1, "ordinal": 1}
    store = RoundStore(root, binding)
    _, first = store.reserve("alpha", "run", ROUND, b"first", {"started": False})
    store.claim_observations(store.claim(first), [ref], [])
    store.close()
    store = RoundStore(root, binding)
    try:
        assert store.get("alpha", "run", ROUND)["result"]["code"] == "round_outcome_unknown"
        from zoop_ai_service.plan_authority import canonical
        assert store.claimed([ref]) == {canonical(ref)}
        _, second = store.reserve("beta", "run", "round-20261031T0935", b"second", {"started": False})
        with pytest.raises(ApiError) as conflict:
            store.claim_observations(store.claim(second), [ref], [])
        assert conflict.value.code == "round_observation_conflict"
        assert store.get("beta", "run", second["round_id"])["context"].get("observations") is None
    finally:
        store.close()


def test_calendar_no_work_has_no_native_effect_and_invalid_dates_have_no_row(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "calendar"})
    service = facade(store)
    try:
        for round_id, code in (("round-20261031T1805", "outside_operating_window"), ("round-20261031T0906", "not_due")):
            body = {"schemaVersion": "zoop-ai-round-run-1", "roundId": round_id}
            assert service.submit("alpha", "run", body, json.dumps(body).encode(), SimpleNamespace(runtime=[])).status == 202
            assert service.step()
            assert service.status("alpha", "run", round_id, SimpleNamespace(runtime=[])).body.code == code
        for family, round_id in (("run", "round-20260230T0905"), ("handoff", "round-20260230T1805"),
                                 ("run", "round-20261101T0905"), ("handoff", "round-20261101T1805")):
            with pytest.raises(ApiError) as refused:
                service.submit("alpha", family, {"roundId": round_id}, b"invalid", SimpleNamespace(runtime=[]))
            assert refused.value.status == 422 and refused.value.field == "roundId"
            assert store.get("alpha", family, round_id) is None
        assert service._slot("handoff", {"roundId": "round-20261031T1805"}).hour == 18
        assert not any(path.is_dir() for path in store.root.iterdir())
    finally:
        store.close()


def test_admitted_work_progresses_without_get_or_repost(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "background"})
    service = facade(store)
    service._thread = threading.Thread(target=service._loop, daemon=True)
    done = threading.Event()

    def freeze(row, seen):
        store.save(row, {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": ROUND, "state": "failed", "code": "test_failed"})
        done.set()

    service._freeze = freeze
    try:
        store.reserve("alpha", "handoff", ROUND, b"{}", {"started": False})
        service.start()
        assert done.wait(2)
        assert store.get("alpha", "handoff", ROUND)["result"]["code"] == "test_failed"
    finally:
        service.stop()
        service._thread.join(2)
        store.close()


def test_ready_get_does_not_recreate_missing_private_handoff_directory(tmp_path):
    store = RoundStore(tmp_path.resolve(), {"profile": "missing-private-input"})
    try:
        _, row = store.reserve("alpha", "handoff", ROUND, b"first", {"started": True})
        ready = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": ROUND, "state": "ready",
                 "handoffId": "hr-" + "a" * 64, "manifestDigest": "b" * 64, "bundleDigest": "c" * 64}
        store.save(row, ready, grant=True)
        service = facade(store)
        owner_directory = store.root / hashlib.sha256(b"alpha").hexdigest()
        with pytest.raises(HandoffError) as error:
            service._reader("alpha", ready["handoffId"])
        assert error.value.code == "service_configuration_invalid"
        assert not owner_directory.exists()
    finally:
        store.close()


def test_round_profile_requires_operator_age_and_a_single_writable_source(tmp_path):
    from zoop_ai_service.config import ConfigError
    from zoop_ai_service.round_config import PROFILE, load_round
    root = tmp_path.resolve()
    profile, fixture = root / "profile.json", root / "fixture.json"
    fixture.write_text("{}")
    handoff = SimpleNamespace(source_contexts=None, command=fixture, state_dir=root / "handoff",
                              canonical_path=fixture, decisions_path=fixture, sources_path=fixture)
    observation = SimpleNamespace(source_contexts=None, command=fixture)
    kwargs = dict(extraction=object(), relation=object(), handoff=handoff, observation=observation, plan_root=root / "plans")
    assert load_round({}, **kwargs) is None
    document = {"schemaVersion": "zoop-ai-round-profile-1", "sourceId": "synthetic-source", "scopeId": "body",
                "initialFrom": "2026-10-31T00:00:00+09:00", "fixtureManifest": str(fixture),
                "descriptor": {"schemaVersion": "zoop-extraction-s2-2", "provenance": {}, "promptVersion": "authored",
                               "catalogue": {}, "snapshot": {}, "topic": None},
                "selection": {"limit": 8, "cadenceMinutes": 30}}
    profile.write_text(json.dumps(document))
    with pytest.raises(ConfigError) as missing_age:
        load_round({PROFILE: str(profile)}, **kwargs)
    assert missing_age.value.reason == "round_profile_invalid"
    document["selection"]["maxAgeSeconds"] = 3600
    profile.write_text(json.dumps(document))
    assert load_round({PROFILE: str(profile)}, **kwargs).max_age_seconds == 3600
    handoff.source_contexts = fixture
    with pytest.raises(ConfigError) as archive:
        load_round({PROFILE: str(profile)}, **kwargs)
    assert archive.value.reason == "round_writable_source_required"


def test_long_history_stays_private_and_pending_candidates_survive_bounded_selection(tmp_path):
    from zoop_ai_service.plan_authority import canonical
    store = RoundStore(tmp_path.resolve(), {"profile": "long-history"})
    service = facade(store)
    service.profile.descriptor = {"snapshot": {"events": []}}
    old_refs = [{"roundId": f"slot-{index:05d}", "sourceId": "shared", "page": 0, "ordinal": 0,
                 "documentId": "historical-" + str(index) + "-" + "x" * 128,
                 "rawVersion": "a" * 64, "documentVersion": "b" * 64} for index in range(8000)]
    pending = [{"roundId": "slot-pending", "sourceId": "shared", "page": 0, "ordinal": index,
                "documentId": f"pending-{index}", "rawVersion": "c" * 64, "documentVersion": "d" * 64} for index in range(9)]
    assert len(canonical(old_refs).encode()) > 2_000_000
    _, history = store.reserve("alpha", "run", ROUND, b"original-unknown", {"started": False})
    history = store.claim(history)
    store.claim_observations(history, [old_refs[0]], old_refs)
    store.save(history, {"schemaVersion": "zoop-ai-round-run-1", "roundId": ROUND, "state": "failed", "code": "round_outcome_unknown"})
    with store.db:
        store.db.executemany("INSERT INTO observation_claims VALUES(?,?,?)",
                             ((canonical(ref), "alpha", ROUND) for ref in old_refs[1:]))
    original = store.get("alpha", "run", ROUND)
    calls = []

    def inventory(request):
        calls.append(request)
        refs = old_refs[:64] if request["after"] is None else pending
        slot = "2026-10-31T08:00:00+00:00" if request["after"] is None else "2026-10-31T08:30:00+00:00"
        following = {"slot": slot, "roundId": refs[-1]["roundId"], "page": 0, "ordinal": 0} if request["after"] is None else None
        return Outcome("result", result={**{key: request[key] for key in ("schemaVersion", "sourceId", "scopeId", "asOf", "maxAgeSeconds")},
            "checkpoint": {"revision": 8001, "through": "2026-10-31T08:30:00+00:00"},
            "observations": [{"slot": slot, "observation": ref} for ref in refs], "next": following}, exit_code=0, started=True)

    service.process = SimpleNamespace(inventory=inventory)
    try:
        for round_id, expected in (("round-20261031T0935", pending[:8]), ("round-20261031T1005", pending[8:])):
            _, row = store.reserve("beta", "run", round_id, round_id.encode(), {"started": False})
            row = store.claim(row, service._run_context({"roundId": round_id}))
            selection = service._working_selection(row, SimpleNamespace(runtime=[]))
            assert selection["observations"] == expected
            assert len(canonical(selection).encode()) < 10_000
            assert "inFlight" not in selection and "settled" not in selection and "carryover" not in selection
            store.claim_observations(row, selection["observations"], [])
            store.save(row, {"schemaVersion": "zoop-ai-round-run-1", "roundId": round_id, "state": "failed", "code": "round_outcome_unknown"})
        assert len(calls) == 4 and all(call["limit"] == 64 for call in calls)
        assert store.get("alpha", "run", ROUND) == original
        assert store.claimed([old_refs[-1], *pending]) == {canonical(ref) for ref in [old_refs[-1], *pending]}
        assert store.db.execute("SELECT count(*) FROM observation_claims").fetchone()[0] == 8009
    finally:
        store.close()
