"""Offline funded profiles: real SQLite authority and runtime, authored HTTP peers only; never paid calls."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest

from tests.live_support import Fake, PAYLOADS, environment, extract_payload, jev_reply, json_response, no_authorization, openai_reply
from zoop_ai_pipeline import live_budget, live_funding as funding, live_runtime as live
from zoop_ai_pipeline.live_budget import Budget, BudgetError, NANO
from zoop_ai_pipeline.live_runtime import LiveFailure, LiveRuntime
from zoop_ai_pipeline.relation_contracts import canonical, digest

END = "2026-10-27T20:50:00Z"
BEFORE = "2026-10-27T20:00:00+00:00"
PIPELINE = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: BEFORE)
    from datetime import datetime
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(live_budget._now())
    monkeypatch.setattr(funding, "datetime", Clock)


def policy(run="test-night", end=END):
    return funding.funding_policy(run, end)


def authority(tmp_path, *, caps=None, run="test-night", end=END, calls=100):
    return Budget(tmp_path / "budget", 20 * NANO, calls, funding=policy(run, end), bucket_caps=caps)


def reserve(b, attempt, role="personal-typesafe", amount=NANO):
    route = b.funding["roles"][role]
    b.reserve(attempt, route["stages"][0], route["recipient"], "d" * 64, amount, account_role=role)


def refused(call, code, error=BudgetError):
    with pytest.raises(error) as caught:
        call()
    assert caught.value.code == code
    if isinstance(caught.value, LiveFailure):
        assert caught.value.uncertain is False


def runtime(monkeypatch, tmp_path, *, go=False, handler=None, family=live.PIPELINE, **overrides):
    values = {live.PROFILE_VAR: funding.PROFILE, live.RUN_ID_VAR: "test-night", live.NOT_AFTER_VAR: END,
              live.MAX_USD_VAR: "20", live.MAX_CALLS_VAR: "100", live.SHARED_MAX_VAR: "10", live.PERSONAL_MAX_VAR: "10",
              live.MODEL_VAR: funding.GO_MODEL if go else live.MODEL,
              live.EFFORT_VAR: "provider-default" if go else "high",
              live.OPENAI_URL_VAR: funding.GO_URL if go else funding.OPENAI_URL, live.MAX_OUTPUT_VAR: "24000"}
    if overrides.get(live.PROFILE_VAR) == funding.CAPPED_PROFILE:
        values.update({live.MAX_USD_VAR: "4", live.SHARED_MAX_VAR: "3.5", live.PERSONAL_MAX_VAR: "0.5",
                       live.FINISH_BY_VAR: "2026-10-28T09:30:00Z"})
    values.update(overrides)
    environment(monkeypatch, tmp_path, **values)
    model = funding.GO_MODEL if go else live.MODEL
    peer = Fake(handler or (lambda request: json_response(openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=model))))
    return LiveRuntime.from_env(transport=peer.transport, family=family), peer


def send(rt, attempt="one", stage="extract", payload=None, authorize=no_authorization):
    return rt.send(rt.prepare(stage, payload or PAYLOADS[stage]()), attempt_id=attempt, authorize=authorize)


def test_go_and_all_jev_compete_for_one_personal_bucket_while_openai_is_separate(tmp_path):
    b = authority(tmp_path)
    reserve(b, "openai", "shared-openai", 8 * NANO)
    reserve(b, "go", "personal-opencode", 4 * NANO)
    reserve(b, "jev", amount=6 * NANO)
    refused(lambda: reserve(b, "more-go", "personal-opencode", 1), "live_budget_exhausted_personal")
    refused(lambda: reserve(b, "more-jev", amount=1), "live_budget_exhausted_personal")
    refused(lambda: reserve(b, "generation-after-verifier-block", "shared-openai", 1), "live_budget_verification_blocked")
    assert b.snapshot()["chargedUsd"] == "18.000000000"
    assert {name: row["chargedUsd"] for name, row in b.snapshot()["buckets"].items()} == {"shared": "8.000000000", "personal": "10.000000000"}


def test_bucket_concurrency_serializes_across_roles_and_independent_handles(tmp_path):
    outcomes = []
    lock = threading.Lock()
    reserve(authority(tmp_path), "shared", "shared-openai", 9 * NANO)

    def attempt(i):
        role = "personal-opencode" if i % 2 else "personal-typesafe"
        try:
            reserve(authority(tmp_path), str(i), role, 3 * NANO)
            result = "ok"
        except BudgetError as exc:
            result = exc.code
        with lock:
            outcomes.append((role, result))

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    snapshot = authority(tmp_path).snapshot()
    assert snapshot["calls"] == 4 and snapshot["chargedUsd"] == "18.000000000"
    assert all(row["chargedUsd"] == "9.000000000" for row in snapshot["buckets"].values())
    assert sum(result == "ok" for _, result in outcomes) == 3


def test_known_unknown_pending_release_and_attempt_identity_remain_distinct(tmp_path):
    b = authority(tmp_path)
    reserve(b, "known", amount=2 * NANO)
    reserve(b, "bad-usage", "personal-opencode", 2 * NANO)
    reserve(b, "unknown", amount=2 * NANO)
    reserve(b, "unsent", "shared-openai", NANO)
    b.settle("known", NANO)
    b.settle("bad-usage", None)
    b.release("unsent")
    bucket = b.snapshot()["buckets"]["personal"]
    assert bucket == {"maxUsd": "10.000000000", "chargedUsd": "5.000000000", "actualUsd": "1.000000000",
                      "reservedUsd": "2.000000000", "unknownUsd": "4.000000000", "remainingUsd": "5.000000000", "calls": 3}
    for attempt in ("known", "bad-usage", "unknown", "unsent"):
        refused(lambda: reserve(b, attempt, "shared-openai", 1), "live_budget_attempt_duplicate")
    b.release("known")
    assert b.snapshot()["calls"] == 3


def test_bucket_decrease_persists_on_refusal_and_old_handle_cannot_extend_it(tmp_path):
    original = authority(tmp_path)
    reserve(original, "first", amount=4 * NANO)
    lower = authority(tmp_path, caps={"shared": 10 * NANO, "personal": 3 * NANO})
    refused(lambda: reserve(lower, "refused", amount=1), "live_budget_exhausted_personal")
    refused(lambda: reserve(original, "increase", amount=1), "live_budget_ceiling_increase")
    refused(lambda: lower.check_send("first"), "live_budget_exhausted_personal")
    assert lower.snapshot()["buckets"]["personal"]["maxUsd"] == "3.000000000"
    assert lower.snapshot()["buckets"]["personal"]["remainingUsd"] == "0.000000000"
    refused(lambda: authority(tmp_path, caps={"shared": 11 * NANO, "personal": 3 * NANO}), "live_funding_config_invalid")


def test_deadline_is_nonextendable_and_rechecked_but_receipts_settle_after_close(tmp_path, monkeypatch):
    initial = authority(tmp_path)
    reserve(initial, "inflight")
    earlier = authority(tmp_path, end="2026-10-27T20:10:00Z")
    assert earlier.snapshot()["notAfter"] == "2026-10-27T20:10:00Z"
    refused(lambda: initial.snapshot(), "live_budget_deadline_increase")
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-27T20:10:00+00:00")
    refused(lambda: reserve(earlier, "late"), "live_budget_deadline")
    refused(lambda: earlier.check_send("inflight"), "live_budget_deadline")
    assert earlier.settle("inflight", 42) == 42
    assert earlier.snapshot()["calls"] == 1
    with pytest.raises(ValueError):
        policy(end="2026-10-27T21:00:01Z")


def test_funding_cannot_relabel_an_old_ledger_or_be_removed_and_routing_is_exact(tmp_path):
    b = authority(tmp_path)
    reserve(b, "a")
    refused(lambda: authority(tmp_path, run="different").snapshot(), "live_budget_policy_mismatch")
    legacy = Budget(tmp_path / "budget", 20 * NANO, 100)
    refused(legacy.snapshot, "live_budget_policy_mismatch")
    refused(lambda: legacy.settle("a", 0), "live_budget_policy_mismatch")
    refused(lambda: legacy.release("a"), "live_budget_policy_mismatch")
    role = b.funding["roles"]["personal-typesafe"]
    refused(lambda: b.reserve("wrong", "extract", role["recipient"], "d" * 64, 1, account_role="personal-typesafe"), "live_budget_policy_mismatch")
    refused(lambda: b.reserve("wrong", "verify-relation", role["recipient"], "d" * 64, 1, account_role="shared-openai"), "live_budget_policy_mismatch")
    old = tmp_path / "legacy"
    Budget(old / "budget", NANO, 10).snapshot()
    refused(lambda: authority(old).snapshot(), "live_budget_policy_mismatch")
    changed = policy()
    changed["roles"]["personal-typesafe"]["bucket"] = "shared"
    refused(lambda: Budget(tmp_path / "other", 20 * NANO, 100, funding=changed), "live_funding_config_invalid")


def test_process_death_keeps_funded_reservation_and_blocks_cross_role_reuse(tmp_path):
    script = ("import os\nfrom zoop_ai_pipeline import live_budget as b\nfrom zoop_ai_pipeline.live_funding import funding_policy\n"
              f"b._now=lambda:{BEFORE!r}\np=funding_policy('test-night',{END!r})\n"
              f"budget=b.Budget({str(tmp_path / 'budget')!r},20*b.NANO,100,funding=p)\n"
              "budget.reserve('dead','extract',p['roles']['personal-opencode']['recipient'],'d'*64,700000,account_role='personal-opencode')\n"
              "os._exit(9)\n")
    child = subprocess.run([sys.executable, "-B", "-c", script], cwd=PIPELINE, capture_output=True, timeout=60)
    assert child.returncode == 9, child.stderr.decode()
    b = authority(tmp_path)
    assert b.snapshot()["buckets"]["personal"]["unknownUsd"] == "0.000700000"
    refused(lambda: reserve(b, "dead", "shared-openai", 1), "live_budget_attempt_duplicate")


@pytest.mark.parametrize("go", [False, True])
def test_new_profile_binding_roundtrip_and_pins_keep_legacy_separate(monkeypatch, tmp_path, go):
    rt, peer = runtime(monkeypatch, tmp_path, go=go)
    frozen = rt.binding()
    assert frozen["version"] == "zoop-live-runtime-1-funded-1"
    assert frozen["funding"] == policy() and frozen["generation"]["reportedModelAliases"] == []
    decoded = LiveRuntime.from_binding(frozen)
    assert decoded.prepare("extract", extract_payload()) == rt.prepare("extract", extract_payload())
    refused(lambda: send(decoded), "live_send_unavailable", LiveFailure)
    other, _ = runtime(monkeypatch, tmp_path, go=not go)
    assert not other.accepts(frozen)
    refused(lambda: other.send(rt.prepare("extract", extract_payload()), attempt_id="x", authorize=no_authorization), "live_binding_mismatch", LiveFailure)
    assert peer.requests == [] and not (tmp_path / "budget").exists()


def test_funded_freeze_does_not_need_credentials_or_caps_and_go_requires_explicit_cap(monkeypatch, tmp_path):
    rt, _ = runtime(monkeypatch, tmp_path, go=True, **{live.OPENAI_KEY_VAR: None, live.JEV_KEY_VAR: None,
                                                    live.MAX_USD_VAR: None, live.MAX_CALLS_VAR: None})
    assert rt.prepare("extract", extract_payload())["format"] == live.FUNDED_PREPARED
    assert not (tmp_path / "budget").exists()
    refused(lambda: LiveRuntime.from_env(need_send=True), "live_budget_config_invalid", LiveFailure)
    monkeypatch.delenv(live.MAX_OUTPUT_VAR)
    refused(LiveRuntime.from_env, "live_limit_invalid", LiveFailure)


@pytest.mark.parametrize("override,code", [
    ({live.OPENAI_URL_VAR: "https://opencode.ai/inference/go/openai/v1"}, "live_endpoint_invalid"),
    ({live.JEV_URL_VAR: "https://opencode.ai/zen/v1"}, "live_endpoint_invalid"),
    ({live.EFFORT_VAR: "high"}, "live_reasoning_effort_invalid"),
    ({live.JEV_MODEL_VAR: "jev-1.13.0"}, "live_jev_model_unsupported"),
    ({live.PROFILE_VAR: "future-profile"}, "live_profile_unsupported"),
])
def test_funded_profile_rejects_routing_and_model_drift(monkeypatch, tmp_path, override, code):
    refused(lambda: runtime(monkeypatch, tmp_path, go=True, **override), code, LiveFailure)


def test_go_wire_session_schema_usage_and_nominal_allowance_are_honest(monkeypatch, tmp_path):
    reply = openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=funding.GO_MODEL)
    reply["usage"].update(cost=0, opencode={"billing_source": "go", "allowance": 0.0009, "list_cost": 0.0009})
    rt, peer = runtime(monkeypatch, tmp_path, go=True, handler=lambda request: json_response(reply))
    prepared = rt.prepare("extract", extract_payload())
    body = prepared["body"]
    assert set(body) == {"model", "messages", "response_format", "max_tokens"}
    assert body["response_format"] == {"type": "json_object"} and body["max_tokens"] == 24000
    assert canonical(rt.family.generation["extract"].schema) in body["messages"][0]["content"]
    assert "provider-default" == rt.binding()["generation"]["reasoningEffort"]
    assert prepared["reservation"]["worstCaseNanoUsd"] == (prepared["requestBytes"] + 1024) * 300 + 24000 * 1200
    first, second = send(rt), send(rt, "two")
    assert str(peer.requests[0].url) == funding.GO_URL + "/chat/completions"
    assert peer.requests[0].headers["user-agent"] == "zoop-data-pipeline/1.0"
    assert peer.requests[0].headers["x-opencode-session"] == peer.requests[1].headers["x-opencode-session"]
    assert first["format"] == "zoop-live-receipt-2" and rt.answer("extract", first) == {"mentions": [], "citationFormat": "zoop-live-source-segments-1"}
    assert first["cost"]["chargedUsd"] == "0.000900000" and first["cost"]["basis"] == "go-nominal-allowance-upper-estimate"
    assert first["cost"]["providerReported"] == {"billingSource": "go", "billableUsd": "0", "allowanceUsd": "0.0009", "listUsd": "0.0009"}
    assert first["timing"]["durationMs"] >= 0 and first["timing"]["provenance"] == "http-transport-monotonic"
    assert second["funding"]["bucket"] == "personal"
    assert authority(tmp_path).snapshot()["buckets"]["personal"]["actualUsd"] == "0.001800000"


def test_standard_tier_is_explicit_and_unexpected_fast_usage_is_not_accepted(monkeypatch, tmp_path):
    reply = openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=live.MODEL)
    reply["service_tier"] = "priority"
    rt, peer = runtime(monkeypatch, tmp_path, handler=lambda request: json_response(reply))
    receipt = send(rt)
    assert json.loads(peer.requests[0].content)["service_tier"] == "default"
    assert rt.binding()["generation"]["serviceTier"] == "default"
    assert receipt["cost"]["chargedUsd"] == receipt["cost"]["reservedUsd"]
    refused(lambda: rt.answer("extract", receipt), "live_receipt_invalid", LiveFailure)


@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-v4.1-flash-other", "gpt-6-luna", None])
def test_reported_model_mismatch_retains_worst_and_cannot_be_accepted(monkeypatch, tmp_path, model):
    rt, _ = runtime(monkeypatch, tmp_path, go=True, handler=lambda request: json_response(openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=model)))
    receipt = send(rt)
    assert receipt["cost"]["estimatedUsd"] is None and receipt["cost"]["chargedUsd"] == receipt["cost"]["reservedUsd"]
    refused(lambda: rt.answer("extract", receipt), "live_model_mismatch", LiveFailure)


@pytest.mark.parametrize("answer", [{}, {"mentions": [], "extra": True, "citationFormat": "zoop-live-source-segments-1"},
                                    {"mentions": "[]", "citationFormat": "zoop-live-source-segments-1"},
                                    {"mentions": [{}], "citationFormat": "zoop-live-source-segments-1"}])
def test_json_object_is_not_mistaken_for_schema_validity(monkeypatch, tmp_path, answer):
    rt, _ = runtime(monkeypatch, tmp_path, go=True, handler=lambda request: json_response(openai_reply(answer, model=funding.GO_MODEL)))
    receipt = send(rt)
    refused(lambda: rt.answer("extract", receipt), "live_answers_invalid", LiveFailure)


@pytest.mark.parametrize("go", [False, True])
def test_all_native_jev_calls_keep_personal_funding_and_exact_native_model(monkeypatch, tmp_path, go):
    holder = {}
    rt, peer = runtime(monkeypatch, tmp_path, go=go, handler=lambda request: json_response(jev_reply(holder["prepared"])))
    for stage in live.VERIFY_STAGES:
        holder["prepared"] = rt.prepare(stage, PAYLOADS[stage]())
        receipt = rt.send(holder["prepared"], attempt_id=stage, authorize=no_authorization)
        assert receipt["funding"]["accountRole"] == "personal-typesafe" and receipt["funding"]["bucket"] == "personal"
        assert receipt["model"] == {"requested": "jev-1.14.0", "reported": "jev-1.14.0"}
        assert rt.answer(stage, receipt)
    assert all(str(request.url) == funding.JEV_URL + "/systemone" for request in peer.requests)
    assert all("x-opencode-session" not in request.headers for request in peer.requests)
    assert authority(tmp_path).snapshot()["buckets"]["personal"]["calls"] == 2


def test_issue_summary_family_also_uses_funded_profiles(monkeypatch, tmp_path):
    reply = openai_reply({"claims": [{"text": "합성 확인 문장이다.", "quoteIds": ["q1"]}]}, model=funding.GO_MODEL)
    rt, _ = runtime(monkeypatch, tmp_path, go=True, family=live.ISSUE_SUMMARY, handler=lambda request: json_response(reply))
    payload = {"issueTitle": "합성", "quotes": [{"quoteId": "e1", "context": "report", "text": "합성 확인 문장이다."}]}
    receipt = send(rt, stage="issue-summary", payload=payload)
    assert LiveRuntime.from_binding(rt.binding()).answer("issue-summary", receipt)["claims"]
    assert rt.binding()["stages"]["verify-issue-summary"]["funding"]["accountRole"] == "personal-typesafe"


def test_timeout_is_unknown_and_same_attempt_cannot_cross_to_shared(monkeypatch, tmp_path):
    rt, peer = runtime(monkeypatch, tmp_path, go=True, handler=lambda request: httpx.ReadTimeout("authored timeout"))
    with pytest.raises(LiveFailure) as caught:
        send(rt)
    assert caught.value.uncertain and caught.value.code == "live_response_unknown"
    shared, shared_peer = runtime(monkeypatch, tmp_path)
    refused(lambda: send(shared), "live_budget_attempt_duplicate", LiveFailure)
    assert len(peer.requests) == 1 and not shared_peer.requests
    assert authority(tmp_path).snapshot()["buckets"]["personal"]["unknownUsd"] != "0.000000000"


def test_authorization_and_deadline_refusals_release_only_unsent_attempts(monkeypatch, tmp_path):
    rt, peer = runtime(monkeypatch, tmp_path, go=True)

    def expired():
        monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-27T20:50:00+00:00")

    refused(lambda: send(rt, authorize=expired), "live_budget_deadline", LiveFailure)
    snapshot = authority(tmp_path).snapshot()
    assert not peer.requests and snapshot["calls"] == 0 and snapshot["states"] == {"released": 1}
    monkeypatch.setattr(live_budget, "_now", lambda: BEFORE)
    refused(lambda: send(rt), "live_budget_attempt_duplicate", LiveFailure)

    def denied():
        raise PermissionError("authored denial")

    with pytest.raises(PermissionError):
        send(rt, "denied", authorize=denied)
    assert not peer.requests and authority(tmp_path).snapshot()["states"] == {"released": 2}


@pytest.mark.parametrize("response", [httpx.Response(429, json={"usage": {"prompt_tokens": 0, "completion_tokens": 0}}),
                                      json_response(openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=funding.GO_MODEL, usage=None)),
                                      json_response(openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=funding.GO_MODEL,
                                                                usage={"prompt_tokens": 1000, "completion_tokens": 24001}))])
def test_missing_bad_or_non_success_usage_never_releases_reserved_exposure(monkeypatch, tmp_path, response):
    rt, peer = runtime(monkeypatch, tmp_path, go=True, handler=lambda request: response)
    receipt = send(rt)
    assert receipt["cost"]["usageKnown"] is False and receipt["cost"]["estimatedUsd"] is None
    assert receipt["cost"]["chargedUsd"] == receipt["cost"]["reservedUsd"]
    assert len(peer.requests) == 1
    assert authority(tmp_path).snapshot()["buckets"]["personal"]["unknownUsd"] == receipt["cost"]["reservedUsd"]


def test_legacy_receipt_decoding_and_unfunded_ledgers_are_not_reinterpreted(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    monkeypatch.delenv(live.PROFILE_VAR, raising=False)
    peer = Fake(lambda request: json_response(openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"})))
    rt = LiveRuntime.from_env(transport=peer.transport)
    old_binding = rt.binding()
    receipt = send(rt)
    assert receipt["format"] == "zoop-live-receipt-1" and "funding" not in receipt and "timing" not in receipt
    assert "funding" not in old_binding and old_binding["version"] == "zoop-live-runtime-1"
    assert LiveRuntime.from_binding(old_binding).answer("extract", receipt) == {"mentions": [], "citationFormat": "zoop-live-source-segments-1"}
    assert "buckets" not in Budget(tmp_path / "budget", NANO, 10).snapshot()
    funded, _ = runtime(monkeypatch, tmp_path)
    refused(lambda: funded.answer("extract", receipt), "live_receipt_invalid", LiveFailure)


def test_native_jobs_cannot_switch_a_frozen_model_but_new_cohort_freezes_separately(monkeypatch, tmp_path):
    from scripts.extraction_smoke import LiveWorld
    from zoop_ai_pipeline.extraction import Extractor, Fixtures, LiveAccess, Sources, Store
    from zoop_ai_pipeline.extraction_contracts import ExtractionFailure, Submit
    from zoop_ai_pipeline.ingestion_contracts import Authority

    primary, peer = runtime(monkeypatch, tmp_path)
    world = LiveWorld(tmp_path / "world", {})
    store = Store(world.kit.root / "extraction", world.kit.root / "ingestion")
    fixtures = Fixtures(None, None)
    access = LiveAccess(from_env=lambda **kwargs: LiveRuntime.from_env(transport=peer.transport))
    try:
        extractor = Extractor(store, Sources(world.kit.root / "ingestion", Authority(world.kit.registry_path)), access)
        request = Submit.model_validate(world.request("primary", snapshot=False, topic=False))
        extractor.freeze(request, fixtures)
        fallback, _ = runtime(monkeypatch, tmp_path, go=True)
        # A cohort switch runs in a fresh CLI process; LiveAccess intentionally caches configuration within one process.
        access = LiveAccess(from_env=lambda **kwargs: LiveRuntime.from_env(transport=peer.transport))
        extractor = Extractor(store, Sources(world.kit.root / "ingestion", Authority(world.kit.registry_path)), access)
        with pytest.raises(ExtractionFailure, match="job_input_conflict"):
            extractor.freeze(request, fixtures)
        stopped = extractor.resume("primary", fixtures)
        assert stopped["failure"]["code"] == "live_config_changed" and stopped["calls"] == []
        world.kit.allow_model_send(fallback)
        extractor = Extractor(store, Sources(world.kit.root / "ingestion", Authority(world.kit.registry_path)), access)
        extractor.freeze(Submit.model_validate(world.request("fallback", snapshot=False, topic=False)), fixtures)
        assert extractor.inspect("primary")["binding"]["live"]["runtime"] == primary.binding()
        assert extractor.inspect("fallback")["binding"]["live"]["runtime"] == fallback.binding()
        assert not peer.requests
    finally:
        store.close()


def test_rehashed_prepared_request_cannot_change_model_or_output_cap(monkeypatch, tmp_path):
    rt, peer = runtime(monkeypatch, tmp_path, go=True)
    for field, value in (("model", live.MODEL), ("max_tokens", 100000)):
        prepared = rt.prepare("extract", extract_payload())
        prepared["body"][field] = value
        prepared["requestDigest"] = digest(prepared["body"])
        prepared["requestBytes"] = len(canonical(prepared["body"]).encode())
        # Preserve the original worst-case to model an attempt to escape the pinned output bound.
        prepared["digest"] = digest({k: v for k, v in prepared.items() if k != "digest"})
        refused(lambda: rt.send(prepared, attempt_id=field, authorize=no_authorization), "live_prepared_invalid", LiveFailure)
    assert not peer.requests and not (tmp_path / "budget").exists()


def test_funded_global_calls_and_hard_twenty_dollar_ceiling_still_apply(tmp_path):
    b = authority(tmp_path, calls=1)
    reserve(b, "one", "shared-openai", 1)
    refused(lambda: reserve(b, "two", amount=1), "live_budget_exhausted_calls")
    refused(lambda: Budget(tmp_path / "bigger", 21 * NANO, 100, funding=policy()), "live_funding_config_invalid")


def test_zero_bucket_cap_revokes_admission_without_erasing_existing_accounting(tmp_path):
    b = authority(tmp_path)
    reserve(b, "old", amount=1)
    b.settle("old", 1)
    stopped = authority(tmp_path, caps={"shared": 10 * NANO, "personal": 0})
    refused(lambda: reserve(stopped, "new", amount=1), "live_budget_exhausted_personal")
    assert stopped.snapshot()["buckets"]["personal"]["chargedUsd"] == "0.000000001"
    refused(lambda: reserve(stopped, "generation", "shared-openai", 1), "live_budget_verification_blocked")


def test_quote_null_offsets_are_structurally_valid_but_coerced_types_are_not():
    schema = {"type": "object", "properties": {"start": {"anyOf": [{"type": "integer"}, {"type": "null"}]}},
              "required": ["start"], "additionalProperties": False}
    assert funding.schema_matches({"start": None}, schema)
    assert funding.schema_matches({"start": 0}, schema)
    assert not funding.schema_matches({"start": "0"}, schema)
    assert not funding.schema_matches({"start": False}, schema)
    assert not funding.schema_matches({}, schema)
    assert not funding.schema_matches({"start": 0, "extra": 1}, schema)
    assert not funding.schema_matches(1, {"type": "integer", "unknownValidation": True})


def test_provider_cost_unknowns_are_not_zero_or_unbounded_decimal_output():
    observed = funding.provider_cost({"usage": {"cost": False, "opencode": {"allowance": "1e-99999999", "list_cost": "NaN"}}})
    assert observed == {"billingSource": None, "billableUsd": None, "allowanceUsd": None, "listUsd": None}


def test_known_verifier_refusal_stops_internal_generation_even_with_large_remaining_balance(tmp_path):
    b = authority(tmp_path)
    reserve(b, "go", "personal-opencode", 4 * NANO)
    b.settle("go", 4 * NANO)
    refused(lambda: reserve(b, "too-large-verifier", amount=7 * NANO), "live_budget_exhausted_personal")
    assert b.snapshot()["buckets"]["personal"]["remainingUsd"] == "6.000000000"
    assert authority(tmp_path).snapshot()["verificationBlocked"] is True
    refused(lambda: reserve(authority(tmp_path), "next-impact", "shared-openai", 1), "live_budget_verification_blocked")
    assert b.snapshot()["calls"] == 1


def test_generation_preserves_pinned_minimum_verifier_liveness_floor_without_fanout_holds(tmp_path):
    b = authority(tmp_path)
    refused(lambda: reserve(b, "last-go", "personal-opencode", 10 * NANO), "live_budget_verification_blocked")
    assert b.snapshot()["calls"] == 0
    reserve(b, "go-with-floor", "personal-opencode", 10 * NANO - 1_000_000)
    b.settle("go-with-floor", 10 * NANO - 1_000_000)
    reserve(b, "actual-verifier", amount=1_000_000)
    assert b.snapshot()["buckets"]["personal"]["chargedUsd"] == "10.000000000"


@pytest.mark.parametrize("settled", [False, True])
def test_unknown_keeps_worst_charge_but_independent_fresh_units_can_continue(tmp_path, settled):
    b = authority(tmp_path)
    reserve(b, "unknown", "personal-opencode", NANO)
    if settled:
        b.settle("unknown", None)
    for role in ("shared-openai", "personal-opencode", "personal-typesafe"):
        reserve(authority(tmp_path), role, role, 1)
        b.settle(role, 1)
    assert b.snapshot()["buckets"]["personal"]["unknownUsd"] == "1.000000000"
    assert b.snapshot()["calls"] == 4
    refused(lambda: reserve(b, "unknown", "shared-openai", 1), "live_budget_attempt_duplicate")


DAY_START = "2026-10-28T00:15:00Z"
DAY_END = "2026-10-28T08:30:00Z"


def day_authority(tmp_path):
    return Budget(tmp_path / "budget", 20 * NANO, 100_000,
                  funding=funding.set_funding_policy("day-test", DAY_START, DAY_END))


def capped_day_authority(tmp_path):
    return Budget(tmp_path / "budget", 4 * NANO, 100_000,
                  funding=funding.capped_set_funding_policy("day-test", DAY_START, DAY_END, 4 * NANO, 3_500_000_000, 500_000_000),
                  bucket_caps={"shared": 3_500_000_000, "personal": 500_000_000}, finish_by="2026-10-28T09:30:00Z")


def finite_plan(**changes):
    return {**dict.fromkeys(funding.GENERATION_STAGES + funding.VERIFY_STAGES, 2), **changes}


def day_reserve(b, attempt, set_id="set-one", *, stage="extract", amount=1, request=None):
    role = "personal-typesafe" if stage.startswith("verify-") else "shared-openai"
    b.reserve(attempt, stage, b.funding["roles"][role]["recipient"], request or digest(attempt), amount,
              account_role=role, set_id=set_id)


def test_admitted_set_softstop_drains_but_cannot_admit_or_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:29:59+00:00")
    b = day_authority(tmp_path)
    b.admit_set("set-one", "a" * 64, finite_plan())
    day_reserve(b, "first")
    b.settle("first", 1)
    b.close_admission("soft_signal")
    day_reserve(b, "second")
    b.check_send("second")
    b.settle("second", 1)
    refused(lambda: b.admit_set("set-two", "b" * 64, finite_plan()), "live_set_admission_closed")
    refused(lambda: b.admit_set("set-one", "a" * 64, finite_plan()), "live_set_admission_duplicate")
    refused(lambda: day_reserve(b, "third"), "live_set_work_exhausted")
    b.finish_set("set-one", "completed")
    refused(lambda: day_reserve(b, "after-finish", stage="topic"), "live_set_not_admitted")
    assert b.snapshot()["sets"] == {"completed": 1}
    assert b.snapshot()["stopIntent"]["reason"] == "soft_signal"
    assert b.snapshot()["calls"] == 2


def test_exact_1730_boundary_serializes_admission_but_preserves_reserved_send(tmp_path, monkeypatch):
    instant = ["2026-10-28T08:29:59+00:00"]
    monkeypatch.setattr(live_budget, "_now", lambda: instant[0])
    b = day_authority(tmp_path)
    b.admit_set("set-one", "a" * 64, finite_plan())
    day_reserve(b, "reserved-before-boundary")
    instant[0] = "2026-10-28T08:30:00+00:00"
    refused(lambda: day_authority(tmp_path).admit_set("late", "b" * 64, finite_plan()), "live_set_admission_closed")
    b.check_send("reserved-before-boundary")
    b.settle("reserved-before-boundary", 1)
    day_reserve(b, "draining-stage", stage="topic")
    assert b.snapshot()["calls"] == 2
    assert b.snapshot()["stopIntent"]["reason"] == "admission_cutoff"
    changed = Budget(tmp_path / "budget", 20 * NANO, 100_000,
                     funding=funding.set_funding_policy("day-test", DAY_START, "2026-10-28T09:30:00Z"))
    refused(changed.snapshot, "live_budget_policy_mismatch")


@pytest.mark.parametrize("known", [True, False])
def test_restart_continues_same_admission_only_with_known_receipts(tmp_path, monkeypatch, known):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:00:00+00:00")
    original = day_authority(tmp_path)
    original.admit_set("set-one", "a" * 64, finite_plan())
    day_reserve(original, "first")
    if known:
        original.settle("first", 1)
    restarted = day_authority(tmp_path)
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:31:00+00:00")
    if known:
        assert restarted.resume_set("set-one", "a" * 64) == finite_plan()
        day_reserve(restarted, "missing-topic", stage="topic")
        refused(lambda: day_reserve(restarted, "duplicate-request", request=digest("first")), "live_set_request_duplicate")
        assert restarted.snapshot()["calls"] == 2
    else:
        refused(lambda: restarted.resume_set("set-one", "a" * 64), "live_set_reconcile_only")
        assert restarted.snapshot()["states"] == {"reserved": 1}
    refused(lambda: restarted.admit_set("set-one", "a" * 64, finite_plan()), "live_set_admission_duplicate")
    assert restarted.snapshot()["sets"] == {"admitted": 1}


def test_parallel_units_never_overspend_either_bucket(tmp_path, monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:00:00+00:00")
    for i in range(24):
        day_authority(tmp_path).admit_set(f"set-{i}", digest(i), finite_plan())
    barrier = threading.Barrier(24)
    outcomes, lock = [], threading.Lock()

    def work(i):
        b = day_authority(tmp_path)
        barrier.wait()
        try:
            day_reserve(b, f"call-{i}", f"set-{i}", stage="extract" if i % 2 else "verify-relation", amount=3 * NANO)
            result = "reserved"
        except BudgetError as exc:
            result = exc.code
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    snapshot = day_authority(tmp_path).snapshot()
    assert snapshot["calls"] == outcomes.count("reserved")
    assert int(snapshot["chargedUsd"].split(".")[0]) <= 20
    for bucket in snapshot["buckets"].values():
        assert int(bucket["chargedUsd"].split(".")[0]) <= 10
        assert bucket["chargedUsd"] == bucket["reservedUsd"] == bucket["unknownUsd"]


def test_emergency_stop_revokes_drain_but_keeps_unknown_charge(tmp_path, monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:00:00+00:00")
    b = day_authority(tmp_path)
    b.admit_set("set-one", "a" * 64, finite_plan())
    day_reserve(b, "uncertain", amount=NANO)
    b.close_admission("soft_signal")
    b.close_admission("emergency_signal", forced=True)
    refused(lambda: b.check_send("uncertain"), "live_set_forced_stop")
    refused(lambda: day_reserve(b, "new-stage", stage="topic"), "live_set_forced_stop")
    b.finish_set("set-one", "unknown")
    assert b.snapshot()["buckets"]["shared"]["unknownUsd"] == "1.000000000"
    assert b.snapshot()["stopIntent"]["forced"] is True


def test_new_day_cannot_adopt_old_policy_or_unfunded_ledger(tmp_path, monkeypatch):
    authority(tmp_path).snapshot()
    refused(lambda: day_authority(tmp_path).snapshot(), "live_budget_policy_mismatch")
    with pytest.raises(ValueError, match="live_funding_config_invalid"):
        policy(end=DAY_END)
    fresh = tmp_path / "fresh"
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T00:14:59+00:00")
    refused(lambda: day_authority(fresh).admit_set("too-early", "a" * 64, finite_plan()), "live_set_admission_not_open")


def test_capped_runtime_binding_and_boundary_drain_are_distinct_from_old_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:29:59+00:00")
    rt, peer = runtime(monkeypatch, tmp_path, **{
        live.PROFILE_VAR: funding.CAPPED_PROFILE, live.RUN_ID_VAR: "day-test",
        live.NOT_AFTER_VAR: None, live.ADMIT_FROM_VAR: DAY_START, live.ADMIT_UNTIL_VAR: DAY_END,
        live.SET_ID_VAR: "set-one", live.MAX_CALLS_VAR: "100000"})
    b = capped_day_authority(tmp_path)
    b.admit_set("set-one", "a" * 64, finite_plan())
    assert rt.binding()["version"] == "zoop-live-runtime-1-funded-3"
    assert LiveRuntime.from_binding(rt.binding()).binding() == rt.binding()

    def boundary():
        monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:30:00+00:00")
        b.close_admission("admission_cutoff")

    receipt = send(rt, authorize=boundary)
    assert len(peer.requests) == 1
    assert receipt["format"] == live.CHAIN_RECEIPT
    assert len(live.physical_attempts(receipt)) == 1
    assert receipt["admittedSet"] == {"setId": "set-one"}
    assert rt.answer("extract", receipt) == {"mentions": [], "citationFormat": "zoop-live-source-segments-1"}
    refused(lambda: b.admit_set("next", "b" * 64, finite_plan()), "live_set_admission_closed")


def test_loopback_transport_timeout_retains_v2_unknown_and_never_resends(tmp_path, monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received, release = threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            received.set()
            release.wait(5)
            self.close_connection = True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever)
    worker.start()

    class LoopbackTransport(httpx.BaseTransport):
        def __init__(self):
            self.inner = httpx.HTTPTransport(retries=0)

        def close(self):
            self.inner.close()

        def handle_request(self, request):
            assert str(request.url).startswith(funding.OPENAI_URL)
            url = request.url.copy_with(scheme="http", host="127.0.0.1", port=server.server_port)
            # Test-only short socket wait; production still uses its configured
            # finite per-call timeout, never a whole native-CLI wall timer.
            extensions = {**request.extensions, "timeout": {"connect": 1, "read": 0.05, "write": 1, "pool": 1}}
            mapped = httpx.Request(request.method, url, headers=request.headers, content=request.read(), extensions=extensions)
            return self.inner.handle_request(mapped)

    try:
        monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:29:59+00:00")
        runtime(monkeypatch, tmp_path, **{
            live.PROFILE_VAR: funding.CAPPED_PROFILE, live.RUN_ID_VAR: "day-test",
            live.NOT_AFTER_VAR: None, live.ADMIT_FROM_VAR: DAY_START, live.ADMIT_UNTIL_VAR: DAY_END,
            live.SET_ID_VAR: "set-one", live.MAX_CALLS_VAR: "100000"})
        rt = LiveRuntime.from_env(transport=LoopbackTransport())
        b = capped_day_authority(tmp_path)
        b.admit_set("set-one", "a" * 64, finite_plan())
        with pytest.raises(LiveFailure) as caught:
            send(rt)
        assert received.is_set()
        assert caught.value.code == "live_response_unknown" and caught.value.uncertain
        snapshot = b.snapshot()
        assert snapshot["states"] == {"reserved": 1}
        assert snapshot["buckets"]["shared"]["unknownUsd"] == snapshot["buckets"]["shared"]["chargedUsd"] != "0.000000000"
        refused(lambda: send(rt), "live_budget_attempt_duplicate", LiveFailure)
        refused(lambda: b.resume_set("set-one", "a" * 64), "live_set_reconcile_only")
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join()


def chain_runtime(monkeypatch, tmp_path, handler, **overrides):
    from zoop_ai_pipeline import direct_deepseek
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:00:00+00:00")
    rt, peer = runtime(monkeypatch, tmp_path, handler=handler, **{
        live.PROFILE_VAR: funding.CAPPED_PROFILE, live.RUN_ID_VAR: "day-test",
        live.NOT_AFTER_VAR: None, live.ADMIT_FROM_VAR: DAY_START, live.ADMIT_UNTIL_VAR: DAY_END,
        live.SET_ID_VAR: "set-one", live.MAX_CALLS_VAR: "100000",
        direct_deepseek.KEY_VAR: "synthetic-direct-test", **overrides})
    b = capped_day_authority(tmp_path)
    b.admit_set("set-one", "a" * 64, finite_plan())
    return rt, peer, b


def test_request_granular_fallback_journals_primary_before_successor_and_keeps_both_buckets(tmp_path, monkeypatch):
    from zoop_ai_pipeline import direct_deepseek
    holder, authorized = {}, []
    def handler(request):
        if request.url.host == "api.openai.com":
            return json_response({"error": {"code": "overloaded"}}, 503)
        assert request.url.host == "api.deepseek.com"
        attempts = holder["budget"].provider_attempts("logical")
        assert len(attempts) == 2 and attempts[0]["state"] == "received" and attempts[1]["state"] == "unknown"
        assert attempts[0]["receipt"]["http"]["status"] == 503
        assert attempts[0]["error"]["code"] == "live_http_503"
        assert authorized == ["primary", "fallback"]
        return json_response(openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=direct_deepseek.MODEL))
    rt, peer, b = chain_runtime(monkeypatch, tmp_path, handler)
    holder["budget"] = b
    receipt = rt.send(rt.prepare("extract", extract_payload()), attempt_id="logical",
                      authorize=lambda: authorized.append("primary"), authorize_fallback=lambda: authorized.append("fallback"))
    assert rt.answer("extract", receipt) == {"mentions": [], "citationFormat": "zoop-live-source-segments-1"}
    assert LiveRuntime.from_binding(rt.binding()).answer("extract", receipt) == {"mentions": [], "citationFormat": "zoop-live-source-segments-1"}
    attempts = live.physical_attempts(receipt)
    assert len(peer.requests) == len(attempts) == 2
    assert receipt["winnerAttemptId"] == attempts[1]["attemptId"]
    assert receipt["logicalAttemptId"] == "logical"
    assert [row["funding"]["accountRole"] for row in attempts] == ["shared-openai", "personal-deepseek"]
    assert all(row["receipt"]["admittedSet"] == {"setId": "set-one"} for row in attempts)
    snapshot = b.snapshot()
    assert snapshot["calls"] == 2
    assert snapshot["buckets"]["shared"]["calls"] == snapshot["buckets"]["personal"]["calls"] == 1
    assert receipt["cost"]["chargedUsd"] == snapshot["chargedUsd"]
    assert "personal-opencode" not in rt.binding()["funding"]["roles"]
    refused(lambda: send(rt, "logical"), "live_budget_attempt_duplicate", LiveFailure)
    assert len(peer.requests) == 2


def test_primary_known_error_fallback_timeout_preserves_partial_chain_and_unknown_cost(tmp_path, monkeypatch):
    def handler(request):
        return json_response({"error": {"code": "capacity"}}, 429) if request.url.host == "api.openai.com" else httpx.ReadTimeout("authored")
    rt, peer, b = chain_runtime(monkeypatch, tmp_path, handler)
    with pytest.raises(LiveFailure) as caught:
        rt.send(rt.prepare("extract", extract_payload()), attempt_id="logical",
                authorize=no_authorization, authorize_fallback=no_authorization)
    assert caught.value.uncertain and caught.value.code == "live_response_unknown"
    partial = caught.value.receipt
    assert partial["winnerAttemptId"] is None
    assert [row["state"] for row in partial["physicalAttempts"]] == ["received", "unknown"]
    assert partial["physicalAttempts"][0]["receipt"]["http"]["status"] == 429
    assert partial["physicalAttempts"][1]["receipt"] is None
    assert partial["cost"]["chargedUsd"] == b.snapshot()["chargedUsd"]
    assert b.snapshot()["buckets"]["personal"]["reservedUsd"] != "0.000000000"
    assert b.provider_attempts("logical") == partial["physicalAttempts"]
    with pytest.raises(LiveFailure) as decoded:
        rt.answer("extract", partial)
    assert decoded.value.uncertain
    refused(lambda: b.resume_set("set-one", "a" * 64), "live_set_reconcile_only")
    assert len(peer.requests) == 2


@pytest.mark.parametrize("mode", ["permission", "refusal", "model-mismatch", "unknown", "gateway-unknown"])
def test_chain_never_model_hops_source_refusal_or_unknown(tmp_path, monkeypatch, mode):
    def handler(request):
        assert request.url.host == "api.openai.com"
        if mode == "unknown":
            return httpx.ReadTimeout("authored")
        if mode == "gateway-unknown":
            return json_response({"error": "upstream"}, 502)
        return json_response(openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model="wrong" if mode == "model-mismatch" else live.MODEL,
                                         refusal="policy" if mode == "refusal" else None))
    rt, peer, b = chain_runtime(monkeypatch, tmp_path, handler)
    def authorize():
        if mode == "permission":
            raise LiveFailure("source_permission_denied")
    if mode in {"unknown", "gateway-unknown"}:
        with pytest.raises(LiveFailure) as caught:
            rt.send(rt.prepare("extract", extract_payload()), attempt_id="logical",
                    authorize=authorize, authorize_fallback=no_authorization)
        assert caught.value.uncertain and len(caught.value.receipt["physicalAttempts"]) == 1
    else:
        receipt = rt.send(rt.prepare("extract", extract_payload()), attempt_id="logical",
                          authorize=authorize, authorize_fallback=no_authorization)
        assert receipt["winnerAttemptId"] is None
        with pytest.raises(LiveFailure):
            rt.answer("extract", receipt)
    assert len(peer.requests) == (0 if mode == "permission" else 1)
    assert b.snapshot()["buckets"]["personal"]["calls"] == 0


def test_fallback_requires_fresh_recipient_authorization_and_preserves_primary_error(tmp_path, monkeypatch):
    rt, peer, b = chain_runtime(monkeypatch, tmp_path, lambda request: json_response({"error": "capacity"}, 503))
    def deny():
        raise LiveFailure("source_permission_denied")
    receipt = rt.send(rt.prepare("extract", extract_payload()), attempt_id="logical",
                      authorize=no_authorization, authorize_fallback=deny)
    assert len(peer.requests) == 1
    assert [row["state"] for row in receipt["physicalAttempts"]] == ["received", "released"]
    assert receipt["physicalAttempts"][0]["receipt"]["http"]["status"] == 503
    refused(lambda: rt.answer("extract", receipt), "source_permission_denied", LiveFailure)
    assert b.snapshot()["buckets"]["personal"]["chargedUsd"] == "0.000000000"


def test_chain_can_finish_after_cutoff_but_missing_set_and_third_attempt_are_refused(tmp_path, monkeypatch):
    from zoop_ai_pipeline import direct_deepseek
    holder = {}
    def handler(request):
        if request.url.host == "api.openai.com":
            monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:30:00+00:00")
            holder["budget"].close_admission("admission_cutoff")
            return json_response({"error": "capacity"}, 503)
        return json_response(openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=direct_deepseek.MODEL))
    rt, peer, b = chain_runtime(monkeypatch, tmp_path, handler)
    holder["budget"] = b
    receipt = rt.send(rt.prepare("extract", extract_payload()), attempt_id="logical",
                      authorize=no_authorization, authorize_fallback=no_authorization)
    assert rt.answer("extract", receipt) == {"mentions": [], "citationFormat": "zoop-live-source-segments-1"}
    refused(lambda: b.admit_set("next", "b" * 64, finite_plan()), "live_set_admission_closed")
    next_payload = extract_payload()
    next_payload["prompt_version"] = "different-input"
    exhausted = rt.send(rt.prepare("extract", next_payload), attempt_id="third",
                        authorize=no_authorization, authorize_fallback=no_authorization)
    refused(lambda: rt.answer("extract", exhausted), "live_set_work_exhausted", LiveFailure)
    assert len(peer.requests) == 2


def test_forged_chain_winner_or_fallback_input_is_not_decoded(tmp_path, monkeypatch):
    import copy
    from zoop_ai_pipeline import direct_deepseek
    rt, _, _ = chain_runtime(monkeypatch, tmp_path, lambda request:
        json_response({"error": "capacity"}, 503) if request.url.host == "api.openai.com"
        else json_response(openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=direct_deepseek.MODEL)))
    receipt = rt.send(rt.prepare("extract", extract_payload()), attempt_id="logical",
                      authorize=no_authorization, authorize_fallback=no_authorization)
    wrong_winner = copy.deepcopy(receipt)
    wrong_winner["winnerAttemptId"] = wrong_winner["physicalAttempts"][0]["attemptId"]
    refused(lambda: rt.answer("extract", wrong_winner), "live_receipt_invalid", LiveFailure)
    wrong_input = copy.deepcopy(receipt)
    wrong_input["physicalAttempts"][1]["receipt"]["requestDigest"] = "f" * 64
    refused(lambda: rt.answer("extract", wrong_input), "live_receipt_invalid", LiveFailure)


@pytest.mark.parametrize("cache_write", [None, 0, 500, 1000])
def test_v2_cache_write_highest_rate_covers_unknown_retention_without_double_counting(tmp_path, monkeypatch, cache_write):
    reply = openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=live.MODEL)
    if cache_write is not None:
        reply["usage"]["prompt_tokens_details"]["cache_write_tokens"] = cache_write
    # Unknown future breakdown does not produce a discount: total input still
    # receives the maximum documented Standard long-context category rate.
    reply["usage"]["prompt_tokens_details"]["unclassified_input_tokens"] = 17
    rt, peer, budget = chain_runtime(monkeypatch, tmp_path, lambda request: json_response(reply))
    prepared = rt.prepare("extract", extract_payload())
    expected_reservation = (prepared["requestBytes"] + 1024) * 500 + 24000 * 750
    assert prepared["reservation"]["worstCaseNanoUsd"] == expected_reservation
    receipt = rt.send(prepared, attempt_id="cache-write", authorize=no_authorization, authorize_fallback=no_authorization)
    physical = live.physical_attempts(receipt)[0]["receipt"]
    assert physical["usage"]["cacheWriteTokens"] == cache_write
    assert physical["cost"]["chargedUsd"] == physical["cost"]["estimatedUsd"] == "0.000875000"
    assert physical["cost"]["usageKnown"] is True
    assert budget.snapshot()["chargedUsd"] == "0.000875000"
    assert rt.answer("extract", receipt) == {"mentions": [], "citationFormat": "zoop-live-source-segments-1"}
    assert len(peer.requests) == 1
    pricing = rt.binding()["pricing"]
    assert pricing["revision"] == "zoop-set-pricing-cache-write-1"
    assert pricing[live.MODEL]["input"] == pricing[live.MODEL]["cacheWrite12h"] == 500
    assert pricing[live.MODEL]["inputChargePolicy"] == "highest-standard-category-on-total-input-once"


@pytest.mark.parametrize("cache_write,reason", [
    (True, "cache_write_usage_invalid"), (-1, "cache_write_usage_invalid"),
    (1.5, "cache_write_usage_invalid"), ("500", "cache_write_usage_invalid"),
    (None, "cache_write_usage_invalid"), (1001, "cache_write_exceeds_input"),
])
def test_v2_cache_write_invalid_usage_keeps_reservation_and_never_falls_back(tmp_path, monkeypatch, cache_write, reason):
    reply = openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=live.MODEL)
    reply["usage"]["prompt_tokens_details"]["cache_write_tokens"] = cache_write
    rt, peer, budget = chain_runtime(monkeypatch, tmp_path, lambda request: json_response(reply))
    prepared = rt.prepare("extract", extract_payload())
    receipt = rt.send(prepared, attempt_id="bad-cache-write", authorize=no_authorization, authorize_fallback=no_authorization)
    physical = live.physical_attempts(receipt)[0]["receipt"]
    assert physical["cost"]["usageRejected"] == reason
    assert physical["cost"]["chargedUsd"] == physical["cost"]["reservedUsd"] == prepared["reservation"]["worstCaseUsd"]
    assert physical["cost"]["estimatedUsd"] is None
    assert budget.snapshot()["chargedUsd"] == prepared["reservation"]["worstCaseUsd"]
    assert receipt["winnerAttemptId"] is None and len(peer.requests) == 1
    refused(lambda: rt.answer("extract", receipt), "live_receipt_invalid", LiveFailure)


def test_cache_write_v2_pricing_does_not_reinterpret_v1_bindings_or_receipts(tmp_path, monkeypatch):
    reply = openai_reply({"mentions": [], "citationFormat": "zoop-live-source-segments-1"}, model=live.MODEL)
    reply["usage"]["prompt_tokens_details"]["cache_write_tokens"] = 1000
    rt, peer = runtime(monkeypatch, tmp_path, handler=lambda request: json_response(reply))
    prepared = rt.prepare("extract", extract_payload())
    assert prepared["reservation"]["worstCaseNanoUsd"] == (prepared["requestBytes"] + 1024) * 200 + 24000 * 750
    receipt = send(rt)
    assert "cacheWriteTokens" not in receipt["usage"]
    assert receipt["cost"]["chargedUsd"] == "0.000575000"
    assert rt.binding()["pricing"] == live.FUNDED_PRICING
    assert live.PRICING[live.MODEL] == live.FUNDED_PRICING[live.MODEL] == {"input": 200, "output": 750}
    assert LiveRuntime.from_binding(rt.binding()).answer("extract", receipt) == {"mentions": [], "citationFormat": "zoop-live-source-segments-1"}
    assert len(peer.requests) == 1


@pytest.mark.parametrize("after_authorization", [False, True])
def test_finish_deadline_refuses_unsent_request_without_charging_or_fallback(tmp_path, monkeypatch, after_authorization):
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    expired = "2026-01-01T00:00:00Z"
    rt, peer = runtime(monkeypatch, tmp_path, **{
        live.PROFILE_VAR: funding.CAPPED_PROFILE, live.RUN_ID_VAR: "day-test",
        live.NOT_AFTER_VAR: None, live.ADMIT_FROM_VAR: DAY_START, live.ADMIT_UNTIL_VAR: DAY_END,
        live.SET_ID_VAR: "set-one", live.MAX_CALLS_VAR: "100000",
        funding.SEND_BEFORE_ENV: future if after_authorization else expired})
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:00:00+00:00")
    budget = capped_day_authority(tmp_path)
    budget.admit_set("set-one", "a" * 64, finite_plan())
    def authorize():
        rt._send["sendBefore"] = expired
    receipt = rt.send(rt.prepare("extract", extract_payload()), attempt_id="late-request",
                      authorize=authorize, authorize_fallback=no_authorization)
    assert peer.requests == []
    attempts = live.physical_attempts(receipt)
    assert len(attempts) == 1
    assert attempts[0]["state"] == "released" and attempts[0]["error"]["code"] == "live_finish_deadline"
    snapshot = budget.snapshot()
    assert snapshot["chargedUsd"] == "0.000000000"
    assert {name: bucket["reservedUsd"] for name, bucket in snapshot["buckets"].items()} == {
        "shared": "0.000000000", "personal": "0.000000000"}


def test_set_request_holder_observes_states_without_spend_or_work_consumption(tmp_path, monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:00:00+00:00")
    budget = day_authority(tmp_path)
    stage, request = "verify-issue-summary", "d" * 64
    recipient = budget.funding["roles"]["personal-typesafe"]["recipient"]
    budget.admit_set("set-one", "a" * 64, finite_plan())
    before = budget.snapshot()
    assert budget.set_request_holder("set-one", stage, request) is None
    assert budget.snapshot() == before
    budget.reserve("owner", stage, recipient, request, 100, account_role="personal-typesafe", set_id="set-one")
    for state, charged in (("reserved", 100), ("settled", 42)):
        if state == "settled":
            budget.settle("owner", charged)
        before = budget.snapshot()
        assert budget.set_request_holder("set-one", stage, request) == {
            "attemptId": "owner", "state": state, "recipient": recipient, "chargedNano": charged,
            "accountRole": "personal-typesafe", "bucket": "personal"}
        assert budget.snapshot() == before
    budget.reserve("unsent", stage, recipient, "e" * 64, 100, account_role="personal-typesafe", set_id="set-one")
    budget.release("unsent")
    before = budget.snapshot()
    assert budget.set_request_holder("set-one", stage, "e" * 64)["state"] == "released"
    assert budget.snapshot() == before
    budget.finish_set("set-one", "completed")
    refused(lambda: budget.set_request_holder("set-one", stage, request), "live_set_not_admitted")
    budget.close_admission("forced", forced=True)
    refused(lambda: budget.set_request_holder("set-one", stage, request), "live_set_forced_stop")


def test_set_request_holder_keeps_execution_finish_without_another_http_allowance(tmp_path, monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:00:00+00:00")
    budget = Budget(tmp_path / "budget", 20 * NANO, 100000,
                    funding=funding.set_funding_policy("day-test", DAY_START, DAY_END),
                    finish_by="2026-10-28T09:30:00Z")
    budget.admit_set("set-one", "a" * 64, finite_plan())
    stage, request = "verify-issue-summary", "d" * 64
    recipient = budget.funding["roles"]["personal-typesafe"]["recipient"]
    budget.reserve("owner", stage, recipient, request, 100, account_role="personal-typesafe", set_id="set-one")
    budget.settle("owner", 42)
    before = budget.snapshot()
    # Only one second remains before cleanup, not a new 300-second HTTP slot.
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T09:26:59+00:00")
    assert budget.set_request_holder("set-one", stage, request)["chargedNano"] == 42
    assert budget.snapshot() == before
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T09:27:00+00:00")
    refused(lambda: budget.set_request_holder("set-one", stage, request), "live_finish_deadline")
    assert budget.snapshot() == before
