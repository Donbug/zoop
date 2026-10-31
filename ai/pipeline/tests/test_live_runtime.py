"""Live runtime transport, offline: fake HTTP only (httpx MockTransport and one loopback server). No key, endpoint or text is real.

Covers frozen configuration, the seven real request builders, one-shot transport (no retry/redirect/proxy), raw receipts for any
HTTP response, strict answer decoding, the shared USD/call budget under concurrency and process death, and secret hygiene."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from tests.live_support import (JEV_KEY, OPENAI_KEY, PAYLOADS, SECRETS, Fake, article, article_source, environment, extract_payload, jev_reply, json_response,
                                no_authorization, openai_reply, verify_relation_payload)
from zoop_ai_pipeline import live_runtime as live
from zoop_ai_pipeline.live_budget import Budget, nano_from_usd
from zoop_ai_pipeline.live_runtime import LiveFailure, LiveRuntime
from zoop_ai_pipeline.relation_contracts import canonical, digest

PIPELINE = Path(__file__).resolve().parents[1]
RECEIPT_KEYS = {"format", "stage", "attemptId", "recipient", "purpose", "bindingIdentity", "requestDigest", "http", "model", "usage", "cost", "expect"}
GOOD = openai_reply({"mentions": []})


def build(monkeypatch, tmp_path, handler=None, **override):
    environment(monkeypatch, tmp_path, **override)
    fake = Fake(handler or (lambda request: json_response(GOOD)))
    return LiveRuntime.from_env(transport=fake.transport), fake


def run(rt: LiveRuntime, stage: str = "extract", attempt: str = "att-1", authorize=no_authorization, payload=None) -> dict:
    return rt.send(rt.prepare(stage, payload or PAYLOADS[stage]()), attempt_id=attempt, authorize=authorize)


def snapshot(tmp_path, usd: str = "1", calls: int = 10) -> dict:
    return Budget(tmp_path / "budget", nano_from_usd(usd), calls).snapshot()


def failure(call) -> LiveFailure:
    with pytest.raises(LiveFailure) as caught:
        call()
    return caught.value


# ---------------------------------------------------------------- configuration -----------------------------------------

@pytest.mark.parametrize("override, code", [
    ({live.GATE: None}, "live_not_enabled"), ({live.GATE: "true"}, "live_not_enabled"), ({live.GATE: "0"}, "live_not_enabled"),
    ({live.MODEL_VAR: None}, "live_model_unsupported"), ({live.MODEL_VAR: "gpt-5"}, "live_model_unsupported"),
    ({live.EFFORT_VAR: None}, "live_reasoning_effort_invalid"), ({live.EFFORT_VAR: "minimal"}, "live_reasoning_effort_invalid"),
    ({live.JEV_MODEL_VAR: None}, "live_jev_model_unsupported"), ({live.JEV_MODEL_VAR: "jev-latest"}, "live_jev_model_unsupported"),
    ({live.OPENAI_URL_VAR: "http://api.example.test/v1"}, "live_endpoint_invalid"),
    ({live.OPENAI_URL_VAR: "https://user:PW-SECRET@api.example.test/v1"}, "live_endpoint_invalid"),
    ({live.OPENAI_URL_VAR: "https://api.example.test/v1?key=1"}, "live_endpoint_invalid"),
    ({live.JEV_URL_VAR: "https://api.typesafe.ai/v1/systemone"}, "live_endpoint_invalid"),
    ({live.JEV_URL_VAR: "ftp://api.typesafe.ai/v1"}, "live_endpoint_invalid"),
    ({live.MAX_OUTPUT_VAR: "10"}, "live_limit_invalid"), ({live.MAX_OUTPUT_VAR: "many"}, "live_limit_invalid"), ({live.TIMEOUT_VAR: "5"}, "live_limit_invalid"),
])
def test_the_explicit_gate_and_every_frozen_setting_is_validated_without_a_network_or_a_leak(monkeypatch, tmp_path, override, code):
    environment(monkeypatch, tmp_path, **override)
    caught = failure(LiveRuntime.from_env)
    assert caught.code == code and caught.uncertain is False and "PW-SECRET" not in str(caught) and not (tmp_path / "budget").exists()


def test_loopback_plain_http_is_the_only_non_https_endpoint(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path, **{live.OPENAI_URL_VAR: "http://127.0.0.1:9/v1/", live.JEV_URL_VAR: "http://localhost:9/v1"})
    rt = LiveRuntime.from_env()
    assert rt.binding()["generation"]["endpoint"] == "http://127.0.0.1:9/v1" and rt.binding()["verifier"]["endpoint"] == "http://localhost:9/v1"


def test_keys_and_ceilings_are_not_needed_to_freeze_validate_or_prepare_and_nothing_is_created(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path, **{live.OPENAI_KEY_VAR: None, live.JEV_KEY_VAR: None, live.MAX_USD_VAR: None, live.MAX_CALLS_VAR: None})
    rt = LiveRuntime.from_env()
    prepared = rt.prepare("extract", extract_payload())
    assert rt.accepts(rt.binding()) and prepared["stage"] == "extract" and list(tmp_path.iterdir()) == [], "no directory is created"
    assert failure(lambda: LiveRuntime.from_env(need_send=True)).code == "live_budget_config_invalid"


@pytest.mark.parametrize("directory", [None, "", "relative/dir", "../up"])
def test_the_budget_directory_is_pinned_at_freeze_time_so_it_is_required_without_keys_and_never_created(monkeypatch, tmp_path, directory):
    environment(monkeypatch, tmp_path, **{live.BUDGET_DIR_VAR: directory, live.OPENAI_KEY_VAR: None, live.JEV_KEY_VAR: None})
    caught = failure(LiveRuntime.from_env)
    assert (caught.code, caught.kind, caught.uncertain) == ("live_budget_config_invalid", "config", False) and list(tmp_path.iterdir()) == []


def test_a_missing_credential_fails_definitely_before_any_reservation_or_socket(monkeypatch, tmp_path):
    rt, fake = build(monkeypatch, tmp_path, **{live.OPENAI_KEY_VAR: None})
    caught = failure(lambda: run(rt, "extract"))
    assert (caught.code, caught.uncertain, caught.kind) == ("live_api_key_required", False, "config") and fake.requests == []
    assert not (tmp_path / "budget").exists(), "no reservation was made"
    assert run(rt, "verify-relation", attempt="att-2", payload=verify_relation_payload())["http"]["status"] == 200, "the verifier needs only its own key"
    rt, fake = build(monkeypatch, tmp_path, **{live.JEV_KEY_VAR: None})
    assert failure(lambda: run(rt, "verify-relation")).code == "live_typesafe_key_required" and fake.requests == []
    assert run(rt, "extract")["http"]["status"] == 200, "the generation stage needs only its own key"
    rt, fake = build(monkeypatch, tmp_path, **{live.MAX_USD_VAR: None})
    assert failure(lambda: run(rt, "extract", "att-9")).code == "live_budget_config_invalid" and fake.requests == []


def test_binding_is_complete_stable_secret_free_and_identical_for_every_stage_user(monkeypatch, tmp_path):
    rt, _ = build(monkeypatch, tmp_path)
    binding = rt.binding()
    assert binding == rt.binding() and rt.accepts(binding) and binding["identity"] == digest({k: v for k, v in binding.items() if k != "identity"})
    assert set(binding) == {"version", "generation", "verifier", "stages", "pricing", "budget", "limits", "identity"} and set(binding["stages"]) == set(live.STAGES)
    assert binding["generation"]["model"] == "gpt-6-luna" and binding["generation"]["reasoningEffort"] == "high" and binding["verifier"]["model"] == "jev-1.14.0"
    assert binding["pricing"]["gpt-6-luna"] == {"input": 200, "output": 750} and binding["pricing"]["jev-1.14.0"] == {"input": 42, "output": 0}
    for stage in live.GENERATION_STAGES:
        assert rt.purpose(stage) == f"pipeline:{stage}" and rt.recipient(stage) == "openai-compatible:" + digest({"endpoint": "https://api.openai.com/v1"})
    for stage in live.VERIFY_STAGES:
        assert rt.recipient(stage) == "typesafe-native:" + digest({"api": "systemone", "endpoint": "https://api.typesafe.ai/v1"})
    text = canonical(binding)
    assert all(secret not in text for secret in SECRETS) and str(tmp_path) not in text
    assert json.loads(json.dumps(binding)) == binding and failure(lambda: rt.recipient("nope")).code == "live_stage_unsupported"


def test_ceilings_and_timeout_do_not_change_the_binding_but_the_budget_directory_and_every_frozen_setting_do(monkeypatch, tmp_path):
    base, _ = build(monkeypatch, tmp_path)
    lowered, _ = build(monkeypatch, tmp_path, **{live.MAX_USD_VAR: "0.5", live.MAX_CALLS_VAR: "2", live.TIMEOUT_VAR: "30"})
    assert lowered.accepts(base.binding()), "ceilings and timeout may change: caps only ever decrease inside the pinned budget"
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    through_real, _ = build(monkeypatch, tmp_path, **{live.BUDGET_DIR_VAR: str(tmp_path / "real" / "b")})
    through_alias, _ = build(monkeypatch, tmp_path, **{live.BUDGET_DIR_VAR: str(tmp_path / "alias" / "b")})
    assert through_real.accepts(through_alias.binding()), "the identity is the validated realpath, not the spelling"
    assert through_real.binding()["budget"] == {"scope": "directory", "directoryIdentity": digest({"realpath": os.path.realpath(tmp_path / "real" / "b")}),
                                                "unit": "nanoUsd"}
    for override in ({live.BUDGET_DIR_VAR: str(tmp_path / "elsewhere")}, {live.EFFORT_VAR: "low"}, {live.MAX_OUTPUT_VAR: "5000"},
                     {live.OPENAI_URL_VAR: "https://other.example.test/v1"}, {live.JEV_URL_VAR: "https://other.example.test/v1"}):
        drifted, _ = build(monkeypatch, tmp_path, **override)
        assert not drifted.accepts(base.binding()) and not base.accepts(drifted.binding()), override
    assert not base.accepts({}) and not base.accepts(None) and not base.accepts({**base.binding(), "identity": "x"})


def test_a_runtime_rebuilt_from_a_frozen_binding_decodes_and_prepares_but_never_sends_and_forgeries_are_refused(monkeypatch, tmp_path):
    rt, _ = build(monkeypatch, tmp_path)
    offline = LiveRuntime.from_binding(rt.binding())
    assert offline.binding() == rt.binding() and offline.prepare("extract", extract_payload()) == rt.prepare("extract", extract_payload())
    caught = failure(lambda: offline.send(offline.prepare("extract", extract_payload()), attempt_id="a", authorize=no_authorization))
    assert caught.code == "live_send_unavailable" and caught.uncertain is False
    forged = rt.binding()
    forged["generation"]["model"] = "gpt-6-luna "
    other_budget = rt.binding()
    other_budget["budget"]["directoryIdentity"] = "0" * 64
    for bad in (forged, other_budget, {**rt.binding(), "pricing": {}}, {**rt.binding(), "budget": {"directoryIdentity": "x"}},
                {k: v for k, v in rt.binding().items() if k != "budget"}, {}, {"generation": {}}):
        assert failure(lambda: LiveRuntime.from_binding(bad)).code == "live_binding_mismatch"


# ---------------------------------------------------------------- prepare (pure) ---------------------------------------

@pytest.mark.parametrize("stage", live.STAGES)
def test_every_stage_builds_a_deterministic_json_request_and_a_worst_case_reservation_without_io(monkeypatch, tmp_path, stage):
    rt, fake = build(monkeypatch, tmp_path)
    prepared = rt.prepare(stage, PAYLOADS[stage]())
    assert prepared == rt.prepare(stage, PAYLOADS[stage]()) and json.loads(json.dumps(prepared)) == prepared and fake.requests == []
    assert not (tmp_path / "budget").exists()
    assert prepared["format"] == "zoop-live-prepared-1" and prepared["purpose"] == f"pipeline:{stage}" and prepared["recipient"] == rt.recipient(stage)
    body = prepared["body"]
    assert prepared["requestDigest"] == digest(body) and prepared["requestBytes"] == len(canonical(body).encode()) and prepared["bindingIdentity"] == rt.binding()["identity"]
    assert prepared["digest"] == digest({k: v for k, v in prepared.items() if k != "digest"})
    reservation = prepared["reservation"]
    if stage in live.GENERATION_STAGES:
        assert prepared["provider"] == "openai-compatible" and prepared["path"] == "chat/completions" and prepared["expect"] is None
        assert body["model"] == "gpt-6-luna" and body["reasoning_effort"] == "high" and body["max_completion_tokens"] == 24_000
        assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
        assert [m["role"] for m in body["messages"]] == ["system", "user"] and "temperature" not in body and "tools" not in body
        assert reservation["outputTokensMax"] == 24_000
        assert reservation["worstCaseNanoUsd"] == (prepared["requestBytes"] + 1024) * 200 + 24_000 * 750
    else:
        assert prepared["provider"] == "typesafe-native" and prepared["path"] == "systemone" and prepared["expect"]["kind"] == stage
        assert body["model"] == "jev-1.14.0" and set(body) == {"model", "state", "questions"} and reservation["outputTokensMax"] == 0
        assert reservation["worstCaseNanoUsd"] == (prepared["requestBytes"] * len(body["questions"]) + 1024) * 42, "billing of the shared state is assumed per question"
        assert reservation["inputTokensUpperBound"] == prepared["requestBytes"] * len(body["questions"]) + 1024 and len(body["questions"]) > 1
    assert reservation["worstCaseUsd"].count(".") == 1


def test_the_generation_request_never_contains_private_article_fields_or_the_job_identity(monkeypatch, tmp_path):
    rt, _ = build(monkeypatch, tmp_path)
    text = canonical(rt.prepare("extract", extract_payload())["body"]) + canonical(rt.prepare("relation", PAYLOADS["relation"]())["body"])
    for private in ("private.example", "PRIVATE-PUBLISHER", "ORIGIN-X", "allow_model_send", "JOB-SECRET", *SECRETS):
        assert private not in text, private
    assert "가상공급은 2026년" in text, "the document text itself is sent"


def test_unsupported_stages_unbuildable_payloads_and_oversize_requests_are_refused_before_any_effect(monkeypatch, tmp_path):
    rt, fake = build(monkeypatch, tmp_path)
    assert failure(lambda: rt.prepare("summary", {})).code == "live_stage_unsupported"
    for stage in live.STAGES:
        assert failure(lambda: rt.prepare(stage, {})).code == "live_payload_invalid" and failure(lambda: rt.prepare(stage, [])).code == "live_payload_invalid"
    huge_article = article("가" * 100_000)  # 300 kB of UTF-8, over the request cap
    huge = extract_payload()
    huge.update(article=huge_article.model_dump(mode="json"), article_version=huge_article.version, citationSources=[article_source(huge_article)])
    assert failure(lambda: rt.prepare("extract", huge)).code == "live_request_too_large"
    verify = verify_relation_payload()
    verify["quotes"][0]["text"] = "나" * 60_000
    assert failure(lambda: rt.prepare("verify-relation", verify)).code == "live_request_too_large"
    assert fake.requests == [] and not (tmp_path / "budget").exists()


def test_a_tampered_or_foreign_prepared_request_is_refused_before_the_budget_is_touched(monkeypatch, tmp_path):
    rt, fake = build(monkeypatch, tmp_path)
    prepared = rt.prepare("extract", extract_payload())
    send = lambda p, a="a": rt.send(p, attempt_id=a, authorize=no_authorization)  # noqa: E731
    tampered = json.loads(json.dumps(prepared))
    tampered["body"]["messages"][1]["content"] = "other"
    assert failure(lambda: send(tampered)).code == "live_prepared_invalid"
    cheaper = json.loads(json.dumps(prepared))
    cheaper["reservation"]["worstCaseNanoUsd"] = 1
    assert failure(lambda: send(cheaper)).code == "live_prepared_invalid"
    assert failure(lambda: send({})).code == "live_prepared_invalid" and failure(lambda: send(None)).code == "live_prepared_invalid"
    assert failure(lambda: send(prepared, "")).code == "live_prepared_invalid" and failure(lambda: send(prepared, "x" * 201)).code == "live_prepared_invalid"
    other, _ = build(monkeypatch, tmp_path, **{live.EFFORT_VAR: "low"})
    assert failure(lambda: other.send(prepared, attempt_id="a", authorize=no_authorization)).code == "live_binding_mismatch"
    assert fake.requests == [] and not (tmp_path / "budget").exists()


# ---------------------------------------------------------------- send ---------------------------------------------------

def test_one_generation_request_is_sent_exactly_as_prepared_with_its_own_key_and_settled_from_reported_usage(monkeypatch, tmp_path):
    rt, fake = build(monkeypatch, tmp_path)
    prepared = rt.prepare("extract", extract_payload())
    calls: list[str] = []
    receipt = rt.send(prepared, attempt_id="att-1", authorize=lambda: calls.append(f"authorized after {len(fake.requests)} requests"))
    assert calls == ["authorized after 0 requests"] and len(fake.requests) == 1
    request = fake.requests[0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions" and request.method == "POST"
    assert request.headers["authorization"] == "Bearer " + OPENAI_KEY and JEV_KEY not in str(request.headers)
    assert request.content == canonical(prepared["body"]).encode() and hashlib.sha256(request.content).hexdigest() == prepared["requestDigest"]
    assert set(receipt) == RECEIPT_KEYS and receipt["format"] == "zoop-live-receipt-1" and receipt["attemptId"] == "att-1"
    assert receipt["recipient"] == rt.recipient("extract") and receipt["purpose"] == "pipeline:extract" and receipt["bindingIdentity"] == rt.binding()["identity"]
    assert receipt["http"] == {"status": 200, "contentType": "application/json", "bodySha256": hashlib.sha256(receipt["http"]["bodyText"].encode()).hexdigest(),
                               "bodyText": receipt["http"]["bodyText"], "truncated": False}
    assert receipt["model"] == {"requested": "gpt-6-luna", "reported": "gpt-6-luna-2026-10-01"}
    assert receipt["usage"] == {"inputTokens": 1000, "outputTokens": 500, "cachedTokens": 0, "reasoningTokens": 300}
    cost = receipt["cost"]
    assert cost["usageKnown"] is True and cost["estimatedUsd"] == cost["chargedUsd"] == "0.000575000" and cost["tier"] == "conservative-long"
    assert cost["reservedUsd"] == prepared["reservation"]["worstCaseUsd"] and float(cost["reservedUsd"]) > float(cost["chargedUsd"])
    assert snapshot(tmp_path)["chargedUsd"] == "0.000575000" and snapshot(tmp_path)["calls"] == 1
    assert rt.answer("extract", receipt) == {"mentions": []}
    assert rt.usage(receipt) == {"model": "gpt-6-luna-2026-10-01", "inputTokens": 1000, "outputTokens": 500, "cachedTokens": 0, "reasoningTokens": 300,
                                 "estimatedUsd": "0.000575000", "chargedUsd": "0.000575000", "usageKnown": True}
    assert json.loads(json.dumps(receipt)) == receipt and all(secret not in canonical(receipt) + canonical(prepared) + repr(rt) for secret in SECRETS)


def test_a_jev_verifier_request_goes_to_the_native_endpoint_with_only_the_jev_key_and_decodes_through_the_policy(monkeypatch, tmp_path):
    holder: dict = {}
    rt, fake = build(monkeypatch, tmp_path, handler=lambda request: json_response(jev_reply(holder["prepared"])))
    holder["prepared"] = rt.prepare("verify-relation", verify_relation_payload())
    receipt = rt.send(holder["prepared"], attempt_id="att-j", authorize=no_authorization)
    request = fake.requests[0]
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone" and request.headers["authorization"] == "Bearer " + JEV_KEY
    assert OPENAI_KEY not in str(request.headers) and not any(h.lower().startswith("typesafe-danger") for h in request.headers)
    assert receipt["model"]["requested"] == "jev-1.14.0" and receipt["usage"]["inputTokens"] == 1000 and receipt["cost"]["chargedUsd"] == "0.000042000"
    answer = rt.answer("verify-relation", receipt)
    assert [c["verdict"] for c in answer["claims"]] == ["supported"] * 5 and answer["claims"][2]["quoteIds"] == ["ev-b"]
    assert len(rt.audit("verify-relation", receipt)) == 5 and rt.audit("extract", {**receipt, "stage": "extract", "http": {**receipt["http"], "bodyText": canonical(GOOD)}}) == []


def test_a_non_2xx_answer_is_a_receipt_with_the_worst_case_kept_and_is_never_retried_or_followed(monkeypatch, tmp_path):
    for status in (400, 401, 429, 500, 503, 302):
        rt, fake = build(monkeypatch, tmp_path / str(status), handler=lambda request: httpx.Response(status, text="denied", headers={"location": "https://evil.example.test/"}))
        receipt = run(rt)
        assert len(fake.requests) == 1 and receipt["http"]["status"] == status and receipt["http"]["bodyText"] == "denied"
        assert receipt["cost"]["usageKnown"] is False and receipt["cost"]["estimatedUsd"] is None and receipt["cost"]["chargedUsd"] == receipt["cost"]["reservedUsd"]
        caught = failure(lambda: rt.answer("extract", receipt))
        assert (caught.code, caught.uncertain, caught.kind) == (f"live_http_{status}", False, "unavailable")
        assert snapshot(tmp_path / str(status))["chargedUsd"] == receipt["cost"]["reservedUsd"]


@pytest.mark.parametrize("error", [httpx.ConnectError("boom"), httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("cut"), OSError("reset")])
def test_a_transport_failure_is_an_uncertain_failure_that_keeps_the_charge_and_can_never_be_resent(monkeypatch, tmp_path, error):
    rt, fake = build(monkeypatch, tmp_path, handler=lambda request: error)
    prepared = rt.prepare("extract", extract_payload())
    caught = failure(lambda: rt.send(prepared, attempt_id="att-1", authorize=no_authorization))
    assert (caught.code, caught.uncertain, caught.kind) == ("live_response_unknown", True, "unavailable") and len(fake.requests) == 1
    state = snapshot(tmp_path)
    assert state["states"] == {"reserved": 1} and state["chargedUsd"] == prepared["reservation"]["worstCaseUsd"]
    assert failure(lambda: rt.send(prepared, attempt_id="att-1", authorize=no_authorization)).code == "live_budget_attempt_duplicate"
    assert len(fake.requests) == 1, "the same attempt is never sent twice"


def test_a_refusing_authorize_sends_nothing_releases_the_reservation_and_propagates_the_owners_exception(monkeypatch, tmp_path):
    class Denied(Exception):
        pass

    denial = Denied("rights changed")
    rt, fake = build(monkeypatch, tmp_path)

    def deny() -> None:
        raise denial

    with pytest.raises(Denied) as caught:
        run(rt, "extract", "att-1", authorize=deny)
    assert caught.value is denial and fake.requests == []
    state = snapshot(tmp_path)
    assert state["calls"] == 0 and state["chargedUsd"] == "0.000000000" and state["states"] == {"released": 1}
    assert failure(lambda: run(rt, "extract", "att-1")).code == "live_budget_attempt_duplicate", "a spent attempt id is never reused"
    assert run(rt, "extract", "att-2")["http"]["status"] == 200


@pytest.mark.parametrize("response, code, kind", [
    (lambda: httpx.Response(200, text="not json at all"), "live_reply_not_json", "invalid"),
    (lambda: json_response(openai_reply("oops, prose")), "live_reply_not_json", "invalid"),
    (lambda: json_response(openai_reply("[1, 2]")), "live_reply_not_json", "invalid"),
    (lambda: json_response(openai_reply({"mentions": []}, finish="length")), "live_output_truncated", "invalid"),
    (lambda: json_response(openai_reply(None, refusal="I cannot")), "live_model_refusal", "refused"),
    (lambda: json_response(openai_reply({"mentions": []}, finish="content_filter")), "live_model_refusal", "refused"),
    (lambda: json_response({"choices": []}), "live_answers_invalid", "invalid"),
    (lambda: json_response([1]), "live_answers_invalid", "invalid"),
    (lambda: json_response({"choices": [{"message": {"content": None}}]}), "live_answers_invalid", "invalid"),
])
def test_a_malformed_2xx_reply_is_returned_as_a_raw_receipt_and_only_answer_fails_it_without_resending(monkeypatch, tmp_path, response, code, kind):
    rt, fake = build(monkeypatch, tmp_path, handler=lambda request: response())
    receipt = run(rt)
    assert len(fake.requests) == 1 and receipt["http"]["status"] == 200 and receipt["http"]["bodyText"]
    caught = failure(lambda: rt.answer("extract", receipt))
    assert (caught.code, caught.uncertain, caught.kind) == (code, False, kind) and len(fake.requests) == 1


def test_usage_that_is_missing_partial_or_malformed_keeps_the_worst_case_and_is_never_zero(monkeypatch, tmp_path):
    for index, usage in enumerate((None, {}, {"prompt_tokens": 5}, {"prompt_tokens": -1, "completion_tokens": 5}, {"prompt_tokens": True, "completion_tokens": 5},
                                   {"prompt_tokens": "5", "completion_tokens": 5})):
        rt, _ = build(monkeypatch, tmp_path / str(index), handler=lambda request: json_response(openai_reply({"mentions": []}, usage=usage)))
        receipt = run(rt)
        assert receipt["cost"]["usageKnown"] is False and receipt["cost"]["chargedUsd"] == receipt["cost"]["reservedUsd"], usage
        assert rt.usage(receipt)["estimatedUsd"] is None


def test_an_oversize_response_is_cut_kept_as_a_receipt_and_decodes_to_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "MAX_RESPONSE_BYTES", 100)
    rt, fake = build(monkeypatch, tmp_path, handler=lambda request: httpx.Response(200, content=b"x" * 1000))
    receipt = run(rt)
    assert receipt["http"]["truncated"] is True and len(receipt["http"]["bodyText"]) == 100 and receipt["cost"]["usageKnown"] is False
    assert failure(lambda: rt.answer("extract", receipt)).code == "live_response_oversize" and len(fake.requests) == 1


def test_the_shared_usd_and_call_ceilings_refuse_before_any_socket(monkeypatch, tmp_path):
    rt, fake = build(monkeypatch, tmp_path, **{live.MAX_USD_VAR: "0.001"})
    caught = failure(lambda: run(rt))
    assert (caught.code, caught.kind, caught.uncertain) == ("live_budget_exhausted_usd", "budget", False) and fake.requests == []
    rt, fake = build(monkeypatch, tmp_path / "calls", **{live.MAX_CALLS_VAR: "1"})
    run(rt, "extract", "att-1")
    assert failure(lambda: run(rt, "extract", "att-2")).code == "live_budget_exhausted_calls" and len(fake.requests) == 1


def test_the_ceiling_can_be_lowered_but_never_raised_for_a_directory_that_has_been_used(monkeypatch, tmp_path):
    rt, _ = build(monkeypatch, tmp_path)
    run(rt, "extract", "att-1")
    higher, fake = build(monkeypatch, tmp_path, **{live.MAX_CALLS_VAR: "20"})
    assert failure(lambda: run(higher, "extract", "att-2")).code == "live_budget_ceiling_increase" and fake.requests == []
    lower, _ = build(monkeypatch, tmp_path, **{live.MAX_CALLS_VAR: "2"})
    run(lower, "extract", "att-3")
    assert failure(lambda: run(lower, "extract", "att-4")).code == "live_budget_exhausted_calls"


def test_s2_and_s3_runtimes_in_many_threads_share_one_call_ceiling_and_send_exactly_the_allowed_number(monkeypatch, tmp_path):
    holder: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.typesafe.ai":
            return json_response(jev_reply(holder["prepared"]))
        return json_response(GOOD)

    s2, fake2 = build(monkeypatch, tmp_path, handler=handler, **{live.MAX_CALLS_VAR: "3"})
    s3, fake3 = build(monkeypatch, tmp_path, handler=handler, **{live.MAX_CALLS_VAR: "3"})
    holder["prepared"] = s3.prepare("verify-relation", verify_relation_payload())
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        try:
            if index % 2:
                s3.send(holder["prepared"], attempt_id=f"s3-{index}", authorize=no_authorization)
            else:
                run(s2, "extract", f"s2-{index}")
            result = "sent"
        except LiveFailure as exc:
            result = exc.code
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("sent") == 3 and outcomes.count("live_budget_exhausted_calls") == 9
    assert len(fake2.requests) + len(fake3.requests) == 3 and snapshot(tmp_path, calls=3)["calls"] == 3


# ---------------------------------------------------------------- answer / usage are pure on the receipt ---------------------

def test_decoding_a_stored_receipt_needs_no_environment_no_keys_and_no_matching_configuration(monkeypatch, tmp_path):
    rt, _ = build(monkeypatch, tmp_path)
    receipt = json.loads(json.dumps(run(rt)))
    offline = LiveRuntime.from_binding(rt.binding())
    for name in (live.GATE, live.MODEL_VAR, live.EFFORT_VAR, live.OPENAI_KEY_VAR, live.JEV_KEY_VAR, live.BUDGET_DIR_VAR):
        monkeypatch.delenv(name, raising=False)
    assert offline.answer("extract", receipt) == {"mentions": []} and offline.usage(receipt)["chargedUsd"] == "0.000575000"
    drifted = {**receipt, "bindingIdentity": "0" * 64}
    assert offline.answer("extract", drifted) == {"mentions": []}


@pytest.mark.parametrize("break_receipt", [
    lambda r: r.__setitem__("format", "other"), lambda r: r.__setitem__("stage", "relation"), lambda r: r.pop("http"),
    lambda r: r["http"].__setitem__("status", "200"), lambda r: r["http"].__setitem__("bodyText", None), lambda r: r["model"].pop("requested"),
])
def test_a_malformed_stored_receipt_is_a_stable_failure_never_an_exception(monkeypatch, tmp_path, break_receipt):
    rt, _ = build(monkeypatch, tmp_path)
    receipt = json.loads(json.dumps(run(rt)))
    break_receipt(receipt)
    assert failure(lambda: rt.answer("extract", receipt)).code == "live_receipt_invalid"
    assert failure(lambda: rt.answer("unknown", receipt)).code == "live_receipt_invalid"
    assert failure(lambda: rt.usage({})).code == "live_receipt_invalid"


def test_a_jev_receipt_with_a_wrong_echoed_model_or_a_broken_answer_set_fails_closed_without_repair(monkeypatch, tmp_path):
    holder: dict = {}
    rt, _ = build(monkeypatch, tmp_path, handler=lambda request: json_response(jev_reply(holder["prepared"], model="jev-latest")))
    holder["prepared"] = rt.prepare("verify-relation", verify_relation_payload())
    receipt = rt.send(holder["prepared"], attempt_id="att-1", authorize=no_authorization)
    assert failure(lambda: rt.answer("verify-relation", receipt)).code == "live_model_mismatch"
    missing = json.loads(json.dumps(receipt))
    body = json.loads(missing["http"]["bodyText"])
    body["model"] = "jev-1.14.0"
    body["answers"].pop("claim-0")
    missing["http"]["bodyText"] = json.dumps(body)
    caught = failure(lambda: rt.answer("verify-relation", missing))
    assert (caught.code, caught.kind) == ("live_answers_invalid", "invalid")
    broken = json.loads(json.dumps(receipt))
    broken["expect"] = {"kind": "verify-relation"}
    assert failure(lambda: rt.answer("verify-relation", broken)).code == "live_receipt_invalid"


# ---------------------------------------------------------------- real sockets: no proxy, no redirect, one request ---------

class Recorder(ThreadingHTTPServer):
    def __init__(self, behavior):
        super().__init__(("127.0.0.1", 0), self.Handler)
        self.behavior, self.seen = behavior, []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("content-length", "0"))
            self.server.seen.append({"path": self.path, "auth": self.headers.get("authorization"), "body": self.rfile.read(length)})
            status, headers, payload = self.server.behavior(self)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass


def serve(behavior):
    server = Recorder(behavior)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_over_a_real_loopback_socket_exactly_one_request_is_sent_ignoring_proxies_and_redirects(monkeypatch, tmp_path):
    ok = serve(lambda h: (200, {"content-type": "application/json"}, json.dumps(GOOD).encode()))
    redirect = serve(lambda h: (302, {"location": f"http://127.0.0.1:{ok.server_port}/v1/chat/completions"}, b""))
    try:
        for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(name, "http://127.0.0.1:9")  # a dead proxy: the runtime must not route through it
        environment(monkeypatch, tmp_path, **{live.OPENAI_URL_VAR: f"http://127.0.0.1:{ok.server_port}/v1"})
        rt = LiveRuntime.from_env()
        receipt = run(rt)
        assert receipt["http"]["status"] == 200 and len(ok.seen) == 1 and ok.seen[0]["path"] == "/v1/chat/completions"
        assert ok.seen[0]["auth"] == "Bearer " + OPENAI_KEY and rt.answer("extract", receipt) == {"mentions": []}
        ok.seen.clear()
        environment(monkeypatch, tmp_path / "b", **{live.OPENAI_URL_VAR: f"http://127.0.0.1:{redirect.server_port}/v1"})
        followed = run(LiveRuntime.from_env())
        assert followed["http"]["status"] == 302 and len(redirect.seen) == 1 and ok.seen == [], "a redirect is a receipt, never followed"
    finally:
        ok.shutdown()
        redirect.shutdown()


def test_a_server_that_never_answers_is_an_uncertain_timeout_with_the_charge_kept(monkeypatch, tmp_path):
    release = threading.Event()
    stalled = serve(lambda h: (release.wait(30), (200, {}, b"{}"))[1])
    try:
        environment(monkeypatch, tmp_path, **{live.OPENAI_URL_VAR: f"http://127.0.0.1:{stalled.server_port}/v1", live.TIMEOUT_VAR: "10"})
        rt = LiveRuntime.from_env()
        monkeypatch.setattr(rt, "_timeout", 0.3)
        caught = failure(lambda: run(rt))
        assert (caught.code, caught.uncertain) == ("live_response_unknown", True) and snapshot(tmp_path)["states"] == {"reserved": 1}
    finally:
        release.set()
        stalled.shutdown()


# ---------------------------------------------------------------- operator CLI --------------------------------------------

def test_the_operator_commands_are_offline_and_print_no_secret(monkeypatch, tmp_path, capsys):
    environment(monkeypatch, tmp_path)
    assert live.main(["binding"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and report["identity"] == report["binding"]["identity"] and report["network"] == "none" and report["keysPresent"] == {"openai": True, "typesafe": True}
    assert set(report["recipients"]) == set(live.STAGES) and all(secret not in json.dumps(report) for secret in SECRETS) and not (tmp_path / "budget").exists()
    assert live.main(["check"]) == 0 and json.loads(capsys.readouterr().out)["check"] is True
    monkeypatch.delenv(live.OPENAI_KEY_VAR)
    assert live.main(["check"]) == 2 and json.loads(capsys.readouterr().out) == {"ok": False, "error": "live_api_key_required", "kind": "config"}
    assert live.main(["binding"]) == 0 and json.loads(capsys.readouterr().out)["keysPresent"]["openai"] is False
    monkeypatch.delenv(live.GATE)
    assert live.main(["binding"]) == 2 and json.loads(capsys.readouterr().out)["error"] == "live_not_enabled"
    assert live.main([]) == 2 and live.main(["send"]) == 2
    environment(monkeypatch, tmp_path, **{live.BUDGET_DIR_VAR: None})
    assert live.main(["binding"]) == 2 and json.loads(capsys.readouterr().out)["error"] == "live_budget_config_invalid", "the budget directory is pinned at freeze time"


def test_the_module_runs_as_a_script_with_a_minimal_environment(tmp_path):
    env = {"PATH": os.environ.get("PATH", ""), live.GATE: "1", live.MODEL_VAR: "gpt-6-luna", live.EFFORT_VAR: "high", live.JEV_MODEL_VAR: "jev-1.14.0",
           live.BUDGET_DIR_VAR: str(tmp_path / "budget")}
    child = subprocess.run([sys.executable, "-B", "-m", "zoop_ai_pipeline.live_runtime", "binding"], cwd=PIPELINE, env=env, capture_output=True, timeout=120)
    assert child.returncode == 0 and child.stderr == b"", child.stderr.decode()
    assert json.loads(child.stdout)["keysPresent"] == {"openai": False, "typesafe": False}


# ---------------------------------------------------------------- a received response always becomes a raw receipt -------------

def test_pathologically_nested_json_is_still_a_raw_receipt_and_only_answer_fails_it(monkeypatch, tmp_path):
    nested = "[" * 200_000 + "]" * 200_000
    rt, fake = build(monkeypatch, tmp_path, handler=lambda request: httpx.Response(200, content=nested.encode(), headers={"content-type": "application/json"}))
    receipt = run(rt)  # used to raise RecursionError after the response had already been paid for
    assert receipt["http"]["status"] == 200 and receipt["http"]["bodyText"] == nested and len(fake.requests) == 1
    assert receipt["cost"]["usageKnown"] is False and receipt["cost"]["settled"] is True and receipt["cost"]["chargedUsd"] == receipt["cost"]["reservedUsd"]
    caught = failure(lambda: rt.answer("extract", receipt))
    assert (caught.code, caught.kind, caught.uncertain) == ("live_reply_not_json", "invalid", False)
    assert snapshot(tmp_path)["states"] == {"settled": 1} and snapshot(tmp_path)["chargedUsd"] == receipt["cost"]["reservedUsd"]
    # the same nesting inside an otherwise valid envelope is a stable failure too, not a RecursionError
    rt, _ = build(monkeypatch, tmp_path / "inner", handler=lambda request: json_response(openai_reply(nested)))
    inner = run(rt)
    assert inner["cost"]["usageKnown"] is True and failure(lambda: rt.answer("extract", inner)).code == "live_reply_not_json"


@pytest.mark.parametrize("usage", [{"prompt_tokens": 10**18, "completion_tokens": 1}, {"prompt_tokens": 1, "completion_tokens": 10**30},
                                   {"prompt_tokens": 2**63, "completion_tokens": 0}, {"prompt_tokens": live.live_jev.MAX_REPORTED_TOKENS + 1, "completion_tokens": 0},
                                   {"prompt_tokens": 5, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 10**18}}])
def test_an_absurd_reported_usage_is_unknown_keeps_the_worst_case_and_never_loses_the_body(monkeypatch, tmp_path, usage):
    rt, fake = build(monkeypatch, tmp_path, handler=lambda request: json_response(openai_reply({"mentions": []}, usage=usage)))
    receipt = run(rt)  # used to raise sqlite3 OverflowError from settle() and lose the received body
    assert receipt["http"]["status"] == 200 and "mentions" in receipt["http"]["bodyText"] and len(fake.requests) == 1
    assert receipt["usage"] == {"inputTokens": None, "outputTokens": None, "cachedTokens": None, "reasoningTokens": None}
    assert receipt["cost"]["usageKnown"] is False and receipt["cost"]["settled"] is True and receipt["cost"]["chargedUsd"] == receipt["cost"]["reservedUsd"]
    assert rt.answer("extract", receipt) == {"mentions": []} and snapshot(tmp_path)["chargedUsd"] == receipt["cost"]["reservedUsd"]


def test_an_absurd_jev_usage_is_unknown_too(monkeypatch, tmp_path):
    holder: dict = {}
    rt, _ = build(monkeypatch, tmp_path, handler=lambda request: json_response({**jev_reply(holder["prepared"]), "usage": {"input_tokens": 10**18, "output_tokens": 0}}))
    holder["prepared"] = rt.prepare("verify-relation", verify_relation_payload())
    receipt = rt.send(holder["prepared"], attempt_id="att-1", authorize=no_authorization)
    assert receipt["cost"]["usageKnown"] is False and receipt["cost"]["chargedUsd"] == holder["prepared"]["reservation"]["worstCaseUsd"]
    assert rt.answer("verify-relation", receipt)["claims"][0]["verdict"] == "supported"


@pytest.mark.parametrize("failing", [OverflowError("Python int too large to convert to SQLite INTEGER"), sqlite3.OperationalError("database is locked"),
                                     RuntimeError("anything")])
def test_a_settlement_failure_keeps_the_worst_case_returns_the_raw_receipt_and_marks_it_unusable(monkeypatch, tmp_path, failing):
    def settle(self, attempt_id, actual_nano):
        raise failing

    monkeypatch.setattr(Budget, "settle", settle)
    rt, fake = build(monkeypatch, tmp_path)
    receipt = run(rt)
    assert receipt["http"]["status"] == 200 and "mentions" in receipt["http"]["bodyText"] and len(fake.requests) == 1
    assert receipt["cost"]["settled"] is False and receipt["cost"]["chargedUsd"] == receipt["cost"]["reservedUsd"]
    assert snapshot(tmp_path)["states"] == {"reserved": 1}, "the durable reservation still charges the worst case"
    caught = failure(lambda: rt.answer("extract", receipt))
    assert (caught.code, caught.kind, caught.uncertain) == ("live_receipt_invalid", "invalid", False), "signalled only after the owner has the receipt"
    assert rt.usage(receipt)["usageKnown"] is True, "what the provider reported stays readable for the audit"


@pytest.mark.parametrize("status", [400, 429, 500])
def test_a_non_2xx_keeps_the_worst_case_even_when_its_body_reports_zero_or_plausible_usage(monkeypatch, tmp_path, status):
    for index, usage in enumerate(({"prompt_tokens": 0, "completion_tokens": 0}, {"prompt_tokens": 10, "completion_tokens": 10})):
        rt, _ = build(monkeypatch, tmp_path / str(index), handler=lambda request: httpx.Response(status, json={"usage": usage, "error": {"message": "no"}}))
        receipt = run(rt)
        assert receipt["http"]["status"] == status and receipt["usage"]["inputTokens"] == usage["prompt_tokens"], "the reported figure is recorded as observed"
        assert receipt["cost"]["usageKnown"] is False and receipt["cost"]["estimatedUsd"] is None
        assert receipt["cost"]["chargedUsd"] == receipt["cost"]["reservedUsd"] and snapshot(tmp_path / str(index))["chargedUsd"] == receipt["cost"]["reservedUsd"]


# ---------------------------------------------------------------- the budget directory is part of the frozen identity --------

def test_a_changed_budget_directory_cannot_replenish_a_frozen_job_and_is_refused_before_any_effect(monkeypatch, tmp_path):
    frozen, fake = build(monkeypatch, tmp_path, **{live.MAX_CALLS_VAR: "1"})
    prepared = frozen.prepare("extract", extract_payload())
    frozen.send(prepared, attempt_id="att-1", authorize=no_authorization)
    assert failure(lambda: frozen.send(prepared, attempt_id="att-2", authorize=no_authorization)).code == "live_budget_exhausted_calls"
    fresh = tmp_path / "fresh"
    switched, switched_fake = build(monkeypatch, tmp_path, **{live.BUDGET_DIR_VAR: str(fresh / "budget")})
    assert not switched.accepts(frozen.binding()), "the owner's accepts(frozen) refuses before it reserves or sends"
    assert failure(lambda: switched.send(prepared, attempt_id="att-3", authorize=no_authorization)).code == "live_binding_mismatch"
    assert len(fake.requests) == 1 and switched_fake.requests == [] and not fresh.exists(), "no request, and no fresh budget was created"
    assert snapshot(tmp_path, calls=1)["calls"] == 1


def test_a_budget_path_re_pointed_after_freezing_is_refused_at_send_with_live_config_changed(monkeypatch, tmp_path):
    first, second, link = tmp_path / "a", tmp_path / "b", tmp_path / "link"
    first.mkdir()
    second.mkdir()
    link.symlink_to(first)
    rt, fake = build(monkeypatch, tmp_path, **{live.BUDGET_DIR_VAR: str(link / "budget")})
    prepared = rt.prepare("extract", extract_payload())
    link.unlink()
    link.symlink_to(second)
    caught = failure(lambda: rt.send(prepared, attempt_id="att-1", authorize=no_authorization))
    assert (caught.code, caught.kind, caught.uncertain) == ("live_config_changed", "config", False)
    assert fake.requests == [] and not (first / "budget").exists() and not (second / "budget").exists()


def test_a_ceiling_lowered_by_a_denied_send_stays_lowered_through_the_runtime(monkeypatch, tmp_path):
    tight, fake = build(monkeypatch, tmp_path, **{live.MAX_USD_VAR: "0.001"})
    assert failure(lambda: run(tight)).code == "live_budget_exhausted_usd" and fake.requests == []
    roomy, roomy_fake = build(monkeypatch, tmp_path)
    assert failure(lambda: run(roomy)).code == "live_budget_ceiling_increase" and roomy_fake.requests == []
    assert snapshot(tmp_path, usd="0.001")["maxUsd"] == "0.001000000"


@pytest.mark.parametrize("usage, reason", [
    ({"prompt_tokens": 1000, "completion_tokens": 1_000_000}, "output_exceeds_bound"),  # under 100M but far above max_completion_tokens 24000
    ({"prompt_tokens": 10_000_000, "completion_tokens": 10}, "input_exceeds_bound"),
    ({"prompt_tokens": 10, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 11}}, "cached_exceeds_input"),
    ({"prompt_tokens": 10, "completion_tokens": 10, "completion_tokens_details": {"reasoning_tokens": 11}}, "reasoning_exceeds_output"),
])
def test_reported_usage_above_the_request_bound_is_never_settled_keeps_the_raw_report_and_the_worst_case(monkeypatch, tmp_path, usage, reason):
    rt, fake = build(monkeypatch, tmp_path, handler=lambda request: json_response(openai_reply({"mentions": []}, usage=usage)))
    prepared = rt.prepare("extract", extract_payload())
    receipt = rt.send(prepared, attempt_id="att-1", authorize=no_authorization)
    assert receipt["http"]["status"] == 200 and "mentions" in receipt["http"]["bodyText"] and len(fake.requests) == 1
    assert receipt["usage"]["inputTokens"] == usage["prompt_tokens"] and receipt["usage"]["outputTokens"] == usage["completion_tokens"], "the raw report stays"
    cost = receipt["cost"]
    assert cost["usageKnown"] is False and cost["usageRejected"] == reason and cost["estimatedUsd"] is None and cost["settled"] is True
    assert cost["chargedUsd"] == cost["reservedUsd"] == prepared["reservation"]["worstCaseUsd"]
    assert snapshot(tmp_path)["chargedUsd"] == prepared["reservation"]["worstCaseUsd"], "no unbounded settlement reached the budget"
    caught = failure(lambda: rt.answer("extract", receipt))
    assert (caught.code, caught.kind, caught.uncertain) == ("live_receipt_invalid", "invalid", False)


def test_a_jev_input_above_the_per_question_bound_is_rejected_and_a_valid_one_below_it_still_settles_lower(monkeypatch, tmp_path):
    holder: dict = {}
    state = {"input": 5_000_000}
    rt, _ = build(monkeypatch, tmp_path, handler=lambda request: json_response({**jev_reply(holder["prepared"]), "usage": {"input_tokens": state["input"], "output_tokens": 7}}))
    holder["prepared"] = rt.prepare("verify-relation", verify_relation_payload())
    bound = holder["prepared"]["reservation"]["inputTokensUpperBound"]
    assert bound < 5_000_000
    over = rt.send(holder["prepared"], attempt_id="att-1", authorize=no_authorization)
    assert over["cost"]["usageRejected"] == "input_exceeds_bound" and over["cost"]["chargedUsd"] == holder["prepared"]["reservation"]["worstCaseUsd"]
    state["input"] = bound
    exact = rt.send(holder["prepared"], attempt_id="att-2", authorize=no_authorization)
    assert exact["cost"]["usageRejected"] is None and exact["cost"]["usageKnown"] is True and exact["cost"]["estimatedUsd"] == exact["cost"]["chargedUsd"]


def test_valid_usage_below_the_bound_still_settles_lower_than_the_reservation(monkeypatch, tmp_path):
    rt, _ = build(monkeypatch, tmp_path, handler=lambda request: json_response(openai_reply({"mentions": []}, usage={"prompt_tokens": 100, "completion_tokens": 24_000})))
    receipt = run(rt)  # exactly max_completion_tokens is allowed
    assert receipt["cost"]["usageKnown"] is True and receipt["cost"]["usageRejected"] is None and float(receipt["cost"]["chargedUsd"]) < float(receipt["cost"]["reservedUsd"])
