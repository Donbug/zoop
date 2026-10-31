"""Chatbot model stages (`zoop-ai-chat`): Jev router and verification policy, Luna answer checks, the invocation ledger, grants,
the live gate and budget, replay and the CLI. No network: live calls go to an in-process `httpx.MockTransport`."""
from __future__ import annotations

import io
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from zoop_ai import chat_cli, chat_jev, chat_luna, chat_runtime
from zoop_ai.chat_contracts import ChatGrantRegistry, Receipt, RouterInput, StageRequest, VerificationInput, estimated_tokens
from zoop_ai.chat_runtime import ChatLedger, LiveSender, ReplaySender, invoke, request_identity, stage_config
from zoop_ai.provider import ProviderError

EV1 = "ev-" + "1" * 64
EV2 = "ev-" + "2" * 64
LIVE = {"ZOOP_AI_CHAT_LIVE_ENABLED": "1", "ZOOP_AI_CHAT_MAX_CALLS": "5", "ZOOP_AI_API_KEY": "luna-key-synthetic",
        "ZOOP_AI_CHAT_ANSWER_MODEL": "gpt-6-luna", "ZOOP_AI_CHAT_ANSWER_REASONING_EFFORT": "high",
        "TYPESAFE_API_KEY": "jev-key-synthetic", "ZOOP_AI_CHAT_JEV_MODEL": chat_jev.MODEL}


def router_input() -> dict[str, Any]:
    return {"turns": [{"text": "HBM이 뭐고 SK하이닉스 최근 뉴스는?"}],
            "requirements": [{"requirementId": "r1", "text": "HBM이 뭐야", "explicit": True},
                             {"requirementId": "r2", "text": "SK하이닉스 최근 뉴스", "explicit": True}],
            "capabilities": [{"capabilityId": "company.read", "description": "기업과 관계 근거 읽기"}]}


def answer_input() -> dict[str, Any]:
    return {"turns": [{"text": "SK하이닉스 HBM 뉴스"}],
            "branches": [{"requirementId": "r2", "label": "SK하이닉스 뉴스", "general": False, "noneFound": False,
                          "items": [{"id": "KRX:000660", "kind": "company", "label": "SK하이닉스"}],
                          "evidence": [{"evidenceId": EV1, "sourceId": "src-news", "quote": "HBM 공급 계약을 맺었다"}]}],
            "maxCitations": 20}


def verification_input(invocation: str = "job-1:a1:stage") -> dict[str, Any]:
    return {"requestBinding": {"invocationId": invocation, "graphVersionId": "gv-new", "asOf": "2026-10-21T00:00:00Z"},
            "sections": [{"sectionId": "s0", "requirementIds": ["r1"], "serverFacts": [],
                          "basis": "evidence_grounded", "text": "SK하이닉스는 HBM을 공급한다.", "evidenceIds": [EV1]},
                         {"sectionId": "s1", "requirementIds": ["r2"], "serverFacts": [],
                          "basis": "general_knowledge", "text": "HBM은 메모리다.", "evidenceIds": []}],
            "citations": [{"evidenceId": EV1, "sourceId": "src-news", "quote": "HBM 공급 계약을 맺었다"}]}


def request(stage: str, payload: dict[str, Any], *, mode: str = "live", invocation: str = "job-1:a1:stage") -> StageRequest:
    return StageRequest.model_validate({"schemaVersion": "zoop-ai-chat-4", "invocationId": invocation, "stage": stage,
                                        "mode": mode, "input": payload})


def grants(recipient: str, stages: list[str] | None = None, **change: Any) -> ChatGrantRegistry:
    grant = {"grantId": "g-news", "revision": "1", "sourceId": "src-news", "enabled": True, "rights": "known",
             "allowedOperations": ["read", "model-send", "quote-display"], "recipients": [recipient],
             "purposes": stages or ["chat-answer", "chat-verification"], "evidence": ["synthetic"], "expiresAt": None}
    grant.update(change)
    return ChatGrantRegistry.model_validate({"schemaVersion": "zoop-ai-chat-1", "grants": [grant]})


def noul(p: float) -> dict[str, Any]:
    return {"type": "noul", "noul": p}


def choice(name: str, p: float = 0.97, confidence: float = 0.93) -> dict[str, Any]:
    rest = round((1 - p) / 2, 6)
    probabilities = dict.fromkeys(("supported", "contradicted", "insufficient"), rest)
    probabilities[name] = p
    return {"type": "choice", "choice": name, "probabilities": probabilities, "confidence": confidence}


def categorical_choice(name: str, names: list[str], p: float = 0.97, confidence: float = 0.93) -> dict[str, Any]:
    rest = (1 - p) / (len(names) - 1)
    probabilities = {candidate: (p if candidate == name else rest) for candidate in names}
    return {"type": "choice", "choice": name, "probabilities": probabilities, "confidence": confidence}


def scripted_answer(question: dict[str, Any], p: float = 0.9) -> dict[str, Any]:
    if question["type"] == "noul":
        return noul(p)
    names = list(question["criteria"])
    winner = "none" if "none" in names else "supported" if "supported" in names else names[0]
    return categorical_choice(winner, names)


class Endpoint:
    """Records what reached the fake provider and answers with `respond(path, body)`."""

    def __init__(self, respond):
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self.respond = respond

    def transport(self) -> httpx.MockTransport:
        def handle(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            self.calls.append((req.url.path, body, req.headers.get("authorization", "")))
            return self.respond(req.url.path, body)
        return httpx.MockTransport(handle)


def jev_all(p: float = 0.9, model: str = chat_jev.MODEL):
    def respond(path, body):
        return httpx.Response(200, json={"model": model, "answers": {k: scripted_answer(q, p)
                                                                        for k, q in body["questions"].items()},
                                         "usage": {"input_tokens": 40, "output_tokens": 3}})
    return respond


def run(req: StageRequest, tmp: Path, endpoint: Endpoint | None = None, *, env=None, registry=None):
    env = LIVE if env is None else env
    sender = LiveSender(env, endpoint.transport() if endpoint else None)
    return invoke(req, state_dir=tmp, registry=registry, sender=sender, env=env)


# ---- Jev router and verification policy -------------------------------------------------------------------------------------

def test_router_request_carries_texts_and_dependency_choices_without_application_ids():
    body = chat_jev.build_router_request(RouterInput.model_validate(router_input()), chat_jev.MODEL)
    assert body["model"] == chat_jev.MODEL
    assert len(body["questions"]) == 2 * (8 + 1 + 1) + 3
    assert {key for key, q in body["questions"].items() if q["type"] == "choice"} == {
        "r1-dependency-source", "r1-dependency-cardinality", "r1-dependency-count"}
    assert set(body["questions"]["r1-dependency-source"]["criteria"]) == {"none", "r0"}
    assert body["state"]["requirements"] == [{"key": "r0", "text": "HBM이 뭐야"}, {"key": "r1", "text": "SK하이닉스 최근 뉴스"}]
    assert "requirementId" not in json.dumps(body["state"]) and "company.read" not in json.dumps(body)


def test_router_answer_keeps_probabilities_and_refuses_a_partial_or_foreign_answer():
    payload = RouterInput.model_validate(router_input())
    questions = chat_jev.build_router_request(payload, chat_jev.MODEL)["questions"]
    answers = {k: scripted_answer(question, 0.05) for k, question in questions.items()}
    answers["r0-q02"] = noul(0.93)
    answers["r1-cap0"] = noul(0.81)
    answers["r1-advice"] = noul(0.4)
    routed = chat_jev.interpret_router({"model": chat_jev.MODEL, "answers": answers}, payload, chat_jev.MODEL)
    first, second = routed.requirements
    assert first.requirement_id == "r1" and first.types["Q02"] == 0.93 and first.types["Q03"] == 0.05
    assert second.capabilities == {"company.read": 0.81} and second.prohibited_advice == 0.4
    assert second.depends_on is None
    with pytest.raises(ValueError, match="native_answers_invalid"):
        chat_jev.interpret_router({"model": chat_jev.MODEL, "answers": dict(list(answers.items())[1:])}, payload,
                                  chat_jev.MODEL)
    with pytest.raises(ValueError, match="native_model_mismatch"):
        chat_jev.interpret_router({"model": "jev-latest", "answers": answers}, payload, chat_jev.MODEL)


def test_router_emits_only_a_confident_dependency_on_an_earlier_requirement():
    payload = RouterInput.model_validate(router_input())
    questions = chat_jev.build_router_request(payload, chat_jev.MODEL)["questions"]
    answers = {key: scripted_answer(question, 0.05) for key, question in questions.items()}
    answers["r1-dependency-source"] = categorical_choice("r0", ["none", "r0"])
    answers["r1-dependency-cardinality"] = categorical_choice("exactly", ["exactly", "atLeast", "atMost"])
    answers["r1-dependency-count"] = categorical_choice("count2", [f"count{count}" for count in range(1, 6)])
    routed = chat_jev.interpret_router({"model": chat_jev.MODEL, "answers": answers}, payload, chat_jev.MODEL)
    assert routed.requirements[1].depends_on.wire() == {
        "requirementId": "r1", "cardinality": "exactly", "count": 2}

    answers["r1-dependency-source"] = categorical_choice("r0", ["none", "r0"], p=0.6)
    assert chat_jev.interpret_router({"model": chat_jev.MODEL, "answers": answers}, payload,
                                     chat_jev.MODEL).requirements[1].depends_on is None


def test_verification_policy_holds_whatever_is_uncertain():
    payload = VerificationInput.model_validate(verification_input())
    body = chat_jev.build_verification_request(payload, chat_jev.MODEL)
    assert set(body["questions"]) == {"s0-support", "s0-advice", "s1-advice"}
    assert body["state"]["sections"][0]["citedQuotes"] == [{"quote": "HBM 공급 계약을 맺었다"}]

    def verdicts(support, advice):
        raw = {"model": chat_jev.MODEL, "answers": {"s0-support": support, "s0-advice": noul(advice), "s1-advice": noul(0.02)}}
        return [v.wire() for v in chat_jev.interpret_verification(raw, payload, chat_jev.MODEL).sections]

    assert verdicts(choice("supported"), 0.02) == [{"support": "supported", "prohibitedAdvice": "no"},
                                                   {"support": None, "prohibitedAdvice": "no"}]
    assert verdicts(choice("supported", confidence=0.5), 0.02)[0]["support"] == "hold"
    assert verdicts(choice("contradicted"), 0.02)[0]["support"] == "contradicted"
    assert verdicts(choice("insufficient"), 0.02)[0]["support"] == "hold"
    assert verdicts(choice("supported"), 0.95)[0]["prohibitedAdvice"] == "yes"
    assert verdicts(choice("supported"), 0.5)[0]["prohibitedAdvice"] == "hold"


def test_a_zoop_document_section_is_checked_against_its_quotes_like_evidence():
    payload = VerificationInput.model_validate({
        "requestBinding": verification_input()["requestBinding"],
        "sections": [{"sectionId": "s0", "requirementIds": ["r1"], "serverFacts": [],
                      "basis": "zoop_documented", "text": "탈퇴하면 대화 기록이 지워집니다.", "evidenceIds": [EV2]}],
        "citations": [{"evidenceId": EV2, "sourceId": "zoop-docs", "quote": "## 2. 보유 기간\n\n탈퇴하면 지웁니다."}]})
    body = chat_jev.build_verification_request(payload, chat_jev.MODEL)
    assert set(body["questions"]) == {"s0-support", "s0-advice"}
    raw = {"model": chat_jev.MODEL, "answers": {"s0-support": choice("insufficient"), "s0-advice": noul(0.02)}}
    assert [v.wire() for v in chat_jev.interpret_verification(raw, payload, chat_jev.MODEL).sections] == [
        {"support": "hold", "prohibitedAdvice": "no"}]


def test_stage_identities_are_separate_from_s1_and_from_each_other():
    versions = {chat_jev.prompt_version("chat-router"), chat_jev.prompt_version("chat-verification"),
                chat_luna.prompt_version()}
    assert len(versions) == 3 and all(v.startswith("zoop-") for v in versions)


def facts_input() -> dict[str, Any]:
    payload = verification_input()
    payload["sections"][0]["serverFacts"] = [
        {"kind": "portfolio_scope", "requirementId": "r1", "timing": "current_request_read",
         "queryScope": "current_member", "companyIds": [], "companyLimit": 5, "truncated": True,
         "companies": [{"companyId": "KRX:000660", "name": "SK하이닉스", "held": True, "watched": False},
                       {"companyId": "NASDAQ:NVDA", "name": "NVIDIA", "held": False, "watched": True}]},
        {"kind": "graph_comparison", "requirementId": "r1", "fromVersion": "gv-old", "toVersion": "gv-new",
         "asOf": "2026-10-21T00:00:00Z", "since": "2026-10-01T00:00:00Z", "queryScope": "targets",
         "targetIds": ["KRX:000660"], "evidenceLimit": 20, "changeLimit": 40, "evidenceRestricted": False, "truncated": True,
         "changes": [{"id": "iss-new", "kind": "issue", "name": "공급 계약", "change": "added"},
                     {"id": "iss-old", "kind": "issue", "name": "이전 사건", "change": "removed"}]}]
    return payload


def test_server_facts_reach_the_real_jev_http_builder_without_becoming_quotes(tmp_path):
    payload = facts_input()

    def respond(path, body):
        assert path == "/v1/systemone"
        assert body["state"]["requestBinding"] == payload["requestBinding"]
        first, second = body["state"]["sections"]
        assert first["serverFacts"] == payload["sections"][0]["serverFacts"]
        assert second["serverFacts"] == []
        assert first["citedQuotes"] == [{"quote": "HBM 공급 계약을 맺었다"}]
        assert set(body["questions"]) == {"s0-support", "s0-advice", "s1-advice"}
        # A scripted insufficient answer tests HOLD plumbing, never semantic accuracy.
        return httpx.Response(200, json={"model": chat_jev.MODEL, "answers": {
            "s0-support": choice("insufficient"), "s0-advice": noul(0.02), "s1-advice": noul(0.02)}})

    endpoint = Endpoint(respond)
    recipient = f"typesafe-native:{stage_config('chat-verification', 'live', LIVE).provider_revision}"
    req = request("chat-verification", payload)
    result = run(req, tmp_path, endpoint, registry=grants(recipient))
    assert result.status == "succeeded" and result.answer["sections"][0]["support"] == "hold"
    assert run(req, tmp_path, endpoint, registry=grants(recipient)).wire() == result.wire()
    assert len(endpoint.calls) == 1
    outbound = json.dumps(endpoint.calls[0][1]["state"])
    for field in ("memberId", "accountId", "quantity", "money", "articleBody", "member:self"):
        assert field not in outbound


def test_canonical_facts_do_not_bypass_quote_grants(tmp_path):
    endpoint = Endpoint(jev_all())
    result = run(request("chat-verification", facts_input()), tmp_path, endpoint, registry=None)
    assert result.failure.code == "source_grant_required" and not result.failure.sent
    assert endpoint.calls == []


@pytest.mark.parametrize("mutate", [
    lambda p: p.pop("requestBinding"),
    lambda p: p["sections"][0].update(sectionId="s1"),
    lambda p: p["sections"][0]["serverFacts"][0].update(requirementId="r-other"),
    lambda p: p["sections"][0]["serverFacts"][1].update(toVersion="gv-stale"),
    lambda p: p["sections"][0]["serverFacts"][1].update(asOf="2026-10-20T00:00:00Z"),
    lambda p: p["sections"][0]["serverFacts"][0].update(memberId="unrelated-member"),
    lambda p: p["sections"][0]["serverFacts"][0]["companies"][0].update(quantity=100),
    lambda p: p["sections"][0]["serverFacts"][1].update(articleBody="not allowed"),
    lambda p: p["sections"][0]["serverFacts"][1]["changes"][0].update(name="가" * 301),
    lambda p: p["sections"][0]["serverFacts"][0].update(queryScope="named_companies", companyIds=["member:self"]),
    lambda p: p["sections"][0]["serverFacts"][0].update(companies=p["sections"][0]["serverFacts"][0]["companies"] * 3),
    lambda p: p["sections"][0]["serverFacts"][0]["companies"][0].update(held=False, watched=False),
    lambda p: p["sections"][1].update(serverFacts=p["sections"][0]["serverFacts"]),
    lambda p: p["sections"][0].update(evidenceIds=["ev-" + "f" * 64]),
])
def test_closed_server_fact_contract_rejects_misbinding_and_extra_private_data(mutate):
    payload = facts_input()
    mutate(payload)
    with pytest.raises(ValueError):
        VerificationInput.model_validate(payload)


def selection_input() -> dict[str, Any]:
    payload = verification_input()
    payload["sections"][0]["serverFacts"] = [
        {"kind": "publication_record", "requirementId": "r1", "issueId": "iss-1", "issueTitle": "HBM 공급 계약",
         "graphVersion": "gv-new", "reviewRevision": 12, "ruleRevision": 3, "decision": "allow",
         "decisionPath": "admin_review", "decidedAt": "2026-10-20T05:00:00Z",
         "rules": [{"ruleId": "single-source@1", "title": "출처가 기사 1개뿐인 관계 숨기기", "summary": "근거 기사 2개 미만인 관계를 숨깁니다."}]},
        {"kind": "briefing_selection", "requirementId": "r1", "issueId": "iss-1", "issueTitle": "HBM 공급 계약",
         "roundId": "br-1", "date": "2026-10-21", "edition": "morning", "rank": 1, "reason": "관심 기업 두 곳이 연결"}]
    return payload


def test_selection_records_are_closed_server_facts_bound_to_the_pinned_version():
    # D-AI-02 Q08: the recorded publication and briefing selection reach Jev as facts, never as quotes.
    parsed = VerificationInput.model_validate(selection_input())
    kinds = [type(f).__name__ for f in parsed.sections[0].server_facts]
    assert kinds == ["PublicationFact", "BriefingSelectionFact"]
    none = selection_input()
    none["sections"][0]["serverFacts"][0].update(decision=None, decisionPath="none", decidedAt=None, ruleRevision=None,
                                                 rules=[])
    VerificationInput.model_validate(none)
    assert "publication_record" in chat_jev.VERIFY_TASK and "not an automatic approval" in chat_jev.VERIFY_TASK


@pytest.mark.parametrize("mutate", [
    lambda f: f[0].update(graphVersion="gv-stale"),
    lambda f: f[0].update(decisionPath="none"),
    lambda f: f[0].update(decidedAt=None),
    lambda f: f[0].update(decidedAt="2026-10-20T05:00:00"),
    lambda f: f[0].update(adminEmail="admin@zoop.example"),
    lambda f: f[0].update(reason="운영 메모"),
    lambda f: f[0]["rules"].append(dict(f[0]["rules"][0])),
    lambda f: f[0]["rules"][0].update(ruleId="no-version"),
    lambda f: f[1].update(edition="noon"),
    lambda f: f[1].update(rank=0),
    lambda f: f[1].update(reason=""),
    lambda f: f[1].update(requirementId="r-other"),
])
def test_selection_facts_refuse_misbinding_and_any_decider_detail(mutate):
    payload = selection_input()
    mutate(payload["sections"][0]["serverFacts"])
    with pytest.raises(ValueError):
        VerificationInput.model_validate(payload)


WEB_HIT = "web-" + "a" * 32


def web_input() -> dict[str, Any]:
    payload = verification_input()
    payload["sections"] = [{"sectionId": "s0", "requirementIds": ["r1"], "serverFacts": [], "basis": "web_reported",
                            "text": "웹 검색 결과에 따르면 HBM은 D램을 쌓은 메모리다.", "evidenceIds": [WEB_HIT]}]
    payload["citations"] = [{"evidenceId": WEB_HIT, "sourceId": "web-search:synthetic",
                             "quote": "[합성 자료] HBM은 D램을 쌓은 메모리다.", "articleTitle": "[합성] HBM이란"}]
    return payload


def test_a_web_section_is_checked_against_its_snippets_under_the_providers_grant():
    # D-AI-02: what the web reported is verified against the snippet, never taken as ZOOP's own fact.
    payload = VerificationInput.model_validate(web_input())
    body = chat_jev.build_verification_request(payload, chat_jev.MODEL)
    assert set(body["questions"]) == {"s0-support", "s0-advice"}
    assert "web_reported" in chat_jev.VERIFY_TASK
    from zoop_ai import chat_agent
    assert "web_reported" in chat_agent.PROMPT


@pytest.mark.parametrize("mutate", [
    lambda p: p["sections"][0].update(basis="evidence_grounded"),
    lambda p: p["sections"][0].update(evidenceIds=[]),
    lambda p: p["citations"][0].update(sourceId="news-provider-1"),
    lambda p: p["citations"][0].update(evidenceId="web-short"),
])
def test_web_hits_and_evidence_never_mix(mutate):
    payload = web_input()
    mutate(payload)
    with pytest.raises(ValueError):
        VerificationInput.model_validate(payload)


def test_a_verification_request_binds_to_its_own_invocation_and_refuses_the_v1_wire():
    payload = facts_input()
    request("chat-verification", payload).parsed()
    request("chat-verification", payload, invocation="app:job-1:a1:stage").parsed()
    with pytest.raises(ValueError, match="another invocation"):
        request("chat-verification", payload, invocation="other-job.1.verify").parsed()
    with pytest.raises(ValueError):
        StageRequest.model_validate({"schemaVersion": "zoop-ai-chat-1", "invocationId": "job-1:a1:stage",
                                     "stage": "chat-verification", "mode": "replay", "input": payload})
    from zoop_ai.chat_contracts import ChatAnswer
    with pytest.raises(ValueError):
        ChatAnswer.model_validate({"sections": [{"basis": "evidence_grounded", "text": "claim",
            "requirementIds": ["r1"], "evidenceIds": [], "serverFacts": payload["sections"][0]["serverFacts"]}],
            "insufficientRequirementIds": [], "graphTargetIds": []})


def test_missing_quotes_and_server_facts_cannot_be_auto_supported():
    payload = verification_input()
    payload["sections"][0]["evidenceIds"] = []
    payload["citations"] = []
    parsed = VerificationInput.model_validate(payload)
    raw = {"model": chat_jev.MODEL, "answers": {
        "s0-support": choice("supported"), "s0-advice": noul(0.02), "s1-advice": noul(0.02)}}
    assert chat_jev.build_verification_request(parsed, chat_jev.MODEL)["state"]["sections"][0]["serverFacts"] == []
    assert chat_jev.interpret_verification(raw, parsed, chat_jev.MODEL).sections[0].support == "hold"


# ---- live gate, keys, grants -----------------------------------------------------------------------------------------------

def test_nothing_is_sent_without_the_live_gate_or_a_key(tmp_path):
    endpoint = Endpoint(jev_all())
    closed = run(request("chat-router", router_input()), tmp_path, endpoint, env={**LIVE, "ZOOP_AI_CHAT_LIVE_ENABLED": "0"})
    assert closed.failure.code == "chat_live_disabled" and not closed.failure.sent
    keyless = run(request("chat-router", router_input()), tmp_path, endpoint, env={**LIVE, "TYPESAFE_API_KEY": ""})
    assert keyless.failure.code == "provider_key_required" and not keyless.failure.sent
    assert endpoint.calls == []
    # Refusals before sending leave nothing behind: the same invocation can run once allowed.
    assert run(request("chat-router", router_input()), tmp_path, endpoint).status == "succeeded"


def test_a_key_that_cannot_travel_in_a_header_is_refused_before_anything_is_reserved(tmp_path):
    endpoint = Endpoint(jev_all())
    for bad in ("jev-key-synthetic ", " jev-key-synthetic", "jev-key	synthetic"):
        refused = run(request("chat-router", router_input()), tmp_path, endpoint, env={**LIVE, "TYPESAFE_API_KEY": bad})
        assert refused.failure.code == "provider_key_invalid" and not refused.failure.sent and not refused.failure.unknown
    assert endpoint.calls == []
    assert run(request("chat-router", router_input()), tmp_path, endpoint).status == "succeeded", "nothing was reserved"


def test_the_router_goes_to_jev_with_the_jev_key_and_records_a_receipt(tmp_path):
    endpoint = Endpoint(jev_all(0.9))
    result = run(request("chat-router", router_input()), tmp_path, endpoint)
    assert result.status == "succeeded"
    path, body, auth = endpoint.calls[0]
    assert path.endswith("/systemone") and auth == "Bearer jev-key-synthetic"
    assert result.receipt.provider == "typesafe-native" and result.receipt.model == chat_jev.MODEL
    assert result.receipt.usage.input_tokens == 40 and result.receipt.received_at is not None
    assert result.answer["requirements"][0]["types"]["Q01"] == 0.9


def test_quotes_are_sent_only_under_a_matching_chat_grant(tmp_path):
    endpoint = Endpoint(lambda path, body: httpx.Response(500))
    config = stage_config("chat-answer", "live", LIVE)
    recipient = f"openai-compatible:{config.provider_revision}"
    for registry, code in [(None, "source_grant_required"), (grants("openai-compatible"), "source_grant_denied"),
                           (grants(recipient, ["chat-verification"]), "source_grant_denied"),
                           (grants(recipient, rights="unknown"), "source_grant_denied"),
                           (grants(recipient, expiresAt="2020-01-01T00:00:00+00:00"), "source_grant_denied")]:
        result = run(request("chat-answer", answer_input()), tmp_path, endpoint, registry=registry)
        assert result.failure.code == code and not result.failure.sent
    assert endpoint.calls == []
    sent = run(request("chat-answer", answer_input()), tmp_path, endpoint, registry=grants(recipient))
    assert sent.failure.code == "provider_http_500" and sent.failure.sent and not sent.failure.unknown


# ---- Luna answer ------------------------------------------------------------------------------------------------------------

def luna(content: Any, model: str = "gpt-6-luna"):
    def respond(path, body):
        return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": json.dumps(content)}}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                                                   "completion_tokens_details": {"reasoning_tokens": 7}}})
    return respond


def test_the_answer_request_is_strict_json_with_the_chat_prompt_and_its_answer_is_checked(tmp_path):
    good = {"sections": [{"basis": "evidence_grounded", "text": "SK하이닉스는 HBM을 공급한다.", "requirementIds": ["r2"],
                          "evidenceIds": [EV1]}], "insufficientRequirementIds": [], "graphTargetIds": ["KRX:000660"]}
    endpoint = Endpoint(luna(good))
    recipient = f"openai-compatible:{stage_config('chat-answer', 'live', LIVE).provider_revision}"
    result = run(request("chat-answer", answer_input()), tmp_path, endpoint, registry=grants(recipient))
    assert result.status == "succeeded" and result.answer == good
    path, body, auth = endpoint.calls[0]
    assert path.endswith("/chat/completions") and auth == "Bearer luna-key-synthetic"
    assert body["messages"][0]["content"] == chat_luna.PROMPT and body["reasoning_effort"] == "high"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert result.receipt.usage.reasoning_tokens == 7

    for i, (content, code) in enumerate([
            ({**good, "sections": [{**good["sections"][0], "evidenceIds": [EV2]}]}, "answer_evidence_unknown"),
            ({**good, "sections": [{**good["sections"][0], "requirementIds": ["r9"]}]}, "answer_requirement_unknown"),
            ({"sections": "x"}, "answer_schema_invalid")]):
        bad = run(request("chat-answer", answer_input(), invocation=f"job-1:a1:answer-{i}"), tmp_path, Endpoint(luna(content)),
                  registry=grants(recipient))
        assert bad.failure.code == code and bad.failure.sent and not bad.failure.unknown
        assert bad.receipt is not None, "a received answer keeps its receipt"


def sized(content: Any, *, output: int, reasoning: int, finish: str = "stop"):
    def respond(path, body):
        return httpx.Response(200, json={"model": "gpt-6-luna", "choices": [{"finish_reason": finish,
                                                                             "message": {"content": json.dumps(content)}}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": output,
                                                   "completion_tokens_details": {"reasoning_tokens": reasoning}}})
    return respond


GOOD_ANSWER = {"sections": [{"basis": "evidence_grounded", "text": "SK하이닉스는 HBM을 공급한다.", "requirementIds": ["r2"],
                             "evidenceIds": [EV1]}], "insufficientRequirementIds": [], "graphTargetIds": []}


def test_an_answer_is_limited_to_2k_tokens_without_its_reasoning_and_cut_answers_fail_alike(tmp_path):
    recipient = f"openai-compatible:{stage_config('chat-answer', 'live', LIVE).provider_revision}"
    endpoint = Endpoint(sized(GOOD_ANSWER, output=7000, reasoning=5000))
    fits = run(request("chat-answer", answer_input()), tmp_path, endpoint, registry=grants(recipient))
    assert fits.status == "succeeded", fits
    assert endpoint.calls[0][1]["max_completion_tokens"] == 8000

    for i, response in enumerate([sized(GOOD_ANSWER, output=7000, reasoning=4999),
                                  sized(GOOD_ANSWER, output=8000, reasoning=7000, finish="length")]):
        over = run(request("chat-answer", answer_input(), invocation=f"job-1:a1:long-{i}"), tmp_path, Endpoint(response),
                   registry=grants(recipient))
        assert over.failure.code == "output_budget_exceeded" and over.failure.sent and not over.failure.unknown
        assert over.receipt is not None


def test_a_direct_answer_over_its_input_limit_is_refused_before_anything_is_sent(tmp_path, monkeypatch):
    recipient = f"openai-compatible:{stage_config('chat-answer', 'live', LIVE).provider_revision}"
    monkeypatch.setattr(chat_runtime, "MAX_INPUT_TOKENS", chat_luna.input_tokens(request("chat-answer", answer_input()).parsed()) - 1)
    endpoint = Endpoint(sized(GOOD_ANSWER, output=10, reasoning=0))
    refused = run(request("chat-answer", answer_input()), tmp_path, endpoint, registry=grants(recipient))
    assert refused.failure.code == "input_budget_exceeded" and not refused.failure.sent
    assert endpoint.calls == []


def test_token_estimates_count_korean_higher_than_latin_text():
    assert estimated_tokens("a" * 400) == 100 and estimated_tokens("가" * 400) == 300


# ---- ledger: idempotency, unknown fate, budget ---------------------------------------------------------------------------

def test_an_invocation_is_sent_once_and_another_input_under_its_id_is_refused(tmp_path):
    endpoint = Endpoint(jev_all())
    first = run(request("chat-router", router_input()), tmp_path, endpoint)
    again = run(request("chat-router", router_input()), tmp_path, endpoint)
    assert again == first and len(endpoint.calls) == 1
    other = {**router_input(), "turns": [{"text": "다른 질문"}]}
    conflict = run(request("chat-router", other), tmp_path, endpoint)
    assert conflict.failure.code == "invocation_conflict" and not conflict.failure.sent


def test_a_timeout_after_sending_is_unknown_and_never_sent_again(tmp_path):
    def timeout(path, body):
        raise httpx.ReadTimeout("slow")
    endpoint = Endpoint(timeout)
    first = run(request("chat-router", router_input()), tmp_path, endpoint)
    assert first.failure.code == "provider_response_unknown" and first.failure.unknown and first.failure.sent
    assert run(request("chat-router", router_input()), tmp_path, endpoint) == first
    assert len(endpoint.calls) == 1


def receipt_for(stage: str) -> Receipt:
    config = stage_config(stage, "live", LIVE)
    return Receipt(provider=config.provider, provider_revision=config.provider_revision, model=config.model,
                   prompt_version=config.prompt_version, execution_mode="live",
                   usage={"inputTokens": None, "outputTokens": None, "cachedTokens": None, "reasoningTokens": None},
                   sent_at="2026-10-23T00:00:00+00:00", received_at=None)


def test_a_request_claimed_by_a_process_that_died_is_unknown_with_its_receipt(tmp_path):
    req = request("chat-router", router_input())
    ledger = ChatLedger(tmp_path)
    assert ledger.claim(req, request_identity(req, stage_config("chat-router", "live", LIVE)), 5,
                        receipt_for("chat-router")) is None
    ledger.close()
    endpoint = Endpoint(jev_all())
    result = run(req, tmp_path, endpoint)
    assert result.failure.code == "provider_response_unknown" and result.failure.unknown and result.failure.sent
    assert result.receipt is not None and result.receipt.model == chat_jev.MODEL
    assert endpoint.calls == []


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX file modes")
def test_the_ledger_file_is_private_from_creation(tmp_path):
    ChatLedger(tmp_path).close()
    assert (tmp_path / "chat.sqlite3").stat().st_mode & 0o077 == 0


def test_only_one_claimer_sends_and_an_open_claim_counts_against_the_ceiling(tmp_path):
    req = request("chat-router", router_input())
    identity = request_identity(req, stage_config("chat-router", "live", LIVE))
    first, second = ChatLedger(tmp_path), ChatLedger(tmp_path)
    assert first.claim(req, identity, 5, receipt_for("chat-router")) is None
    raced = second.claim(req, identity, 5, receipt_for("chat-router"))
    assert raced is not None and raced.failure.unknown and raced.failure.sent, "the loser never sends"
    other = request("chat-router", router_input(), invocation="job-2:a1:stage")
    with pytest.raises(ProviderError, match="chat_budget_exhausted"):
        second.claim(other, identity, 1, receipt_for("chat-router"))
    first.close()
    second.close()


def test_a_known_invocation_answers_from_its_record_whatever_the_gate_or_keys_are_now(tmp_path):
    def timeout(path, body):
        raise httpx.ReadTimeout("slow")
    endpoint = Endpoint(timeout)
    first = run(request("chat-router", router_input()), tmp_path, endpoint)
    assert first.failure.unknown
    for env in ({**LIVE, "ZOOP_AI_CHAT_LIVE_ENABLED": "0"}, {**LIVE, "TYPESAFE_API_KEY": ""},
                {**LIVE, "ZOOP_AI_CHAT_JEV_MODEL": ""}):
        again = run(request("chat-router", router_input()), tmp_path, endpoint, env=env)
        assert again == first and again.failure.sent and again.failure.unknown and again.receipt is not None
    assert len(endpoint.calls) == 1


def test_a_stored_answer_whose_grant_was_withdrawn_is_withheld_as_sent(tmp_path):
    good = {"sections": [{"basis": "evidence_grounded", "text": "HBM 공급", "requirementIds": ["r2"], "evidenceIds": [EV1]}],
            "insufficientRequirementIds": [], "graphTargetIds": []}
    endpoint = Endpoint(luna(good))
    recipient = f"openai-compatible:{stage_config('chat-answer', 'live', LIVE).provider_revision}"
    assert run(request("chat-answer", answer_input()), tmp_path, endpoint, registry=grants(recipient)).status == "succeeded"
    withheld = run(request("chat-answer", answer_input()), tmp_path, endpoint, registry=grants(recipient, enabled=False))
    assert withheld.failure.code == "source_grant_withdrawn" and withheld.failure.sent and not withheld.failure.unknown
    assert withheld.answer is None and withheld.receipt is not None
    assert len(endpoint.calls) == 1


def stored_row(tmp: Path, invocation: str) -> tuple:
    db = sqlite3.connect(tmp / "chat.sqlite3")
    try:
        return db.execute("SELECT status, raw FROM chat_invocations WHERE invocation_id=?", (invocation,)).fetchone()
    finally:
        db.close()


def test_the_raw_answer_is_stored_before_it_is_interpreted(tmp_path, monkeypatch):
    def odd_usage(path, body):
        return httpx.Response(200, json={"model": chat_jev.MODEL, "answers": {},
                                         "usage": {"input_tokens": 1, "output_tokens": [3]}})
    bad = run(request("chat-router", router_input()), tmp_path, Endpoint(odd_usage))
    assert bad.failure.code == "provider_usage_invalid" and bad.failure.sent and bad.receipt.received_at is not None
    assert json.loads(stored_row(tmp_path, "job-1:a1:stage")[1])["usage"]["output_tokens"] == [3]

    def details_list(path, body):
        return httpx.Response(200, json={"model": "gpt-6-luna", "choices": [], "usage": {"prompt_tokens_details": []}})
    recipient = f"openai-compatible:{stage_config('chat-answer', 'live', LIVE).provider_revision}"
    odd = run(request("chat-answer", answer_input(), invocation="job-1:a1:odd"), tmp_path, Endpoint(details_list),
              registry=grants(recipient))
    assert odd.failure.code == "provider_usage_invalid" and odd.failure.sent

    # The process stops after the raw answer is stored and before the outcome: the record keeps the raw answer and the
    # invocation is unknown from then on, never sent again.
    def stop(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(chat_runtime, "interpret", stop)
    endpoint = Endpoint(jev_all())
    with pytest.raises(KeyboardInterrupt):
        run(request("chat-router", router_input(), invocation="job-3:a1:r"), tmp_path, endpoint)
    status, raw = stored_row(tmp_path, "job-3:a1:r")
    assert status == "sent" and json.loads(raw)["model"] == chat_jev.MODEL
    monkeypatch.undo()
    after = run(request("chat-router", router_input(), invocation="job-3:a1:r"), tmp_path, endpoint)
    assert after.failure.unknown and after.failure.sent and len(endpoint.calls) == 1


def test_the_answer_model_is_pinned_and_the_model_that_answered_is_checked_and_recorded(tmp_path):
    for env, code in (({**LIVE, "ZOOP_AI_CHAT_ANSWER_MODEL": "gpt-5"}, "answer_model_unsupported"),
                      ({**LIVE, "ZOOP_AI_CHAT_ANSWER_REASONING_EFFORT": "low"}, "reasoning_effort_unsupported")):
        refused = run(request("chat-answer", answer_input()), tmp_path, Endpoint(luna({})), env=env)
        assert refused.failure.code == code and not refused.failure.sent
    good = {"sections": [], "insufficientRequirementIds": ["r2"], "graphTargetIds": []}
    recipient = f"openai-compatible:{stage_config('chat-answer', 'live', LIVE).provider_revision}"
    for i, (model, code) in enumerate((("gpt-6-mini", "provider_model_mismatch"), ("", "provider_model_missing"))):
        wrong = run(request("chat-answer", answer_input(), invocation=f"job-1:a1:m{i}"), tmp_path,
                    Endpoint(luna(good, model)), registry=grants(recipient))
        assert wrong.failure.code == code and wrong.failure.sent and wrong.receipt is not None
    snapshot = run(request("chat-answer", answer_input(), invocation="job-1:a1:snap"), tmp_path,
                   Endpoint(luna(good, "gpt-6-luna-2026-09-30")), registry=grants(recipient))
    assert snapshot.status == "succeeded" and snapshot.receipt.model == "gpt-6-luna-2026-09-30"


def test_the_live_ceiling_is_shared_by_all_chat_stages(tmp_path):
    endpoint = Endpoint(jev_all())
    env = {**LIVE, "ZOOP_AI_CHAT_MAX_CALLS": "1"}
    assert run(request("chat-router", router_input(), invocation="job-1:a1:router"), tmp_path, endpoint, env=env).status \
        == "succeeded"
    over = run(request("chat-verification", verification_input("job-1:a1:verify"), invocation="job-1:a1:verify"), tmp_path, endpoint, env=env,
               registry=grants(f"typesafe-native:{stage_config('chat-verification', 'live', env).provider_revision}"))
    assert over.failure.code == "chat_budget_exhausted" and not over.failure.sent
    assert len(endpoint.calls) == 1


# ---- replay and the CLI -----------------------------------------------------------------------------------------------------

def replay_file(tmp: Path, req: StageRequest, response: Any) -> Path:
    path = tmp / "replay.json"
    entry = {"stage": req.stage, "inputDigest": request_identity(req, stage_config(req.stage, "replay")), "response": response}
    path.write_text(json.dumps({"schemaVersion": "zoop-ai-chat-4", "recordingKind": "authored-test", "responses": [entry]}),
                    encoding="utf-8")
    return path


def test_replay_answers_by_exact_identity_and_a_mismatch_sends_nothing(tmp_path):
    req = request("chat-router", router_input(), mode="replay")
    questions = chat_jev.build_router_request(req.parsed(), "authored-synthetic-chat-router")["questions"]
    path = replay_file(tmp_path, req, {"model": "authored-synthetic-chat-router",
                                      "answers": {k: scripted_answer(q, 0.5) for k, q in questions.items()}})
    result = invoke(req, state_dir=tmp_path, registry=None, sender=ReplaySender(path), env={})
    assert result.status == "succeeded" and result.receipt.execution_mode == "replay"
    other = request("chat-router", {**router_input(), "turns": [{"text": "다른"}]}, mode="replay", invocation="job-2:a1:r")
    missed = invoke(other, state_dir=tmp_path, registry=None, sender=ReplaySender(path), env={})
    assert missed.failure.code == "replay_input_mismatch" and not missed.failure.sent


def test_cli_prints_the_result_and_exits_by_outcome(tmp_path, monkeypatch, capsys):
    req = request("chat-router", router_input(), mode="replay")
    questions = chat_jev.build_router_request(req.parsed(), "authored-synthetic-chat-router")["questions"]
    path = replay_file(tmp_path, req, {"model": "authored-synthetic-chat-router",
                                      "answers": {k: scripted_answer(q, 0.5) for k, q in questions.items()}})
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("sys.stdin", io.StringIO(req.model_dump_json(by_alias=True)))
    assert chat_cli.main(["invoke", "--state-dir", str(state), "--replay", str(path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "succeeded" and printed["invocationId"] == req.invocation_id

    monkeypatch.setattr("sys.stdin", io.StringIO('{"schemaVersion":"zoop-ai-chat-4"}'))
    assert chat_cli.main(["invoke", "--state-dir", str(state)]) == 64
    assert json.loads(capsys.readouterr().out) == {"error": "request_invalid"}


def path_branch(*paths: dict[str, Any]) -> dict[str, Any]:
    payload = answer_input()
    payload["branches"][0]["paths"] = list(paths)
    return payload


def step(edge: str, evidence: list[str]) -> dict[str, Any]:
    return {"edgeId": edge, "sourceId": "iss-hbm", "targetId": "KRX:000660", "relation": "INVOLVES", "role": None,
            "evidenceIds": evidence}


def test_path_pairs_keep_their_status_and_steps_name_only_quoted_evidence():
    found = {"fromId": "KRX:000660", "toId": "NASDAQ:NVDA", "status": "found", "steps": [step("e-1", [EV1])]}
    cut = {"fromId": "KRX:000660", "toId": "NASDAQ:AMD", "status": "cut", "steps": []}
    none = {**cut, "status": "none"}
    with_cut = request("chat-answer", path_branch(found, cut)).parsed().wire()
    with_none = request("chat-answer", path_branch(found, none)).parsed().wire()
    assert with_cut["branches"][0]["paths"][1]["status"] == "cut"
    assert with_cut != with_none, "a pair cut by the limit never reads like a pair proven unconnected"
    assert request("chat-answer", answer_input()).parsed().wire()["branches"][0]["paths"] == []

    for bad in ({**found, "steps": []}, {**cut, "steps": [step("e-1", [EV1])]},
                {**found, "steps": [step("e-1", ["ev-" + "9" * 64])]}):
        with pytest.raises(ValueError):
            request("chat-answer", path_branch(bad)).parsed()


def test_the_answer_prompt_explains_paths_and_its_version_moved():
    assert "status=cut" in chat_luna.PROMPT and "evidenceIds" in chat_luna.PROMPT
    assert chat_luna.prompt_version().startswith("zoop-chat-answer-2026-10-30-1-")


def test_the_answer_prompt_and_schema_know_zoop_document_sections():
    assert "zoop_documented" in chat_luna.PROMPT and "zoop-docs" in chat_luna.PROMPT
    basis = json.dumps(chat_luna.schema(), ensure_ascii=False)
    assert "zoop_documented" in basis
