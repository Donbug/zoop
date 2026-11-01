"""Native Jev verifier policy for S3: request shape, typed Choice questions, conservative answer mapping (pure, offline)."""
from __future__ import annotations

import copy

import pytest

from tests.live_support import choice, endpoint, environment, facts, quote, verify_impact_payload, verify_relation_payload
from zoop_ai_pipeline import live_jev as jev
from zoop_ai_pipeline import relation_rules as rules
from zoop_ai_pipeline.live_runtime import LiveFailure, LiveRuntime
from zoop_ai_pipeline.relation_contracts import ImpactVerifierResponse, VerifierResponse
from zoop_ai_pipeline.relation_rules import claims, decide_impact, decide_relation

MODEL = "jev-1.14.0"

# Historical prompt fixture, not a compatibility path. The comparison changes this one question only.
OLD_SCOPE_QUESTION = (
    "Read the quotes {labels} in `state.quotes` together as one passage. Do they describe the relationship as limited to "
    "exactly `state.relation.businessScope` (business) and `state.relation.productScope` (product)? A null value asserts no "
    "restriction and must not be contradicted."
)


def relation_body():
    return jev.build_relation_request(verify_relation_payload(), MODEL)


def answers_for(body: dict, winners: dict[str, str] | None = None, p: float = 0.97, confidence: float = 0.95) -> dict:
    out = {}
    for key, question in body["questions"].items():
        options = list(question["criteria"])
        out[key] = choice((winners or {}).get(key, "supported" if "supported" in options else "positive"), options, p, confidence)
    return {"model": MODEL, "answers": out}


def test_the_relation_request_sends_only_quote_text_and_fixed_facts_and_one_typed_choice_per_claim():
    body, expect = relation_body()
    assert body["model"] == MODEL and list(body) == ["model", "state", "questions"]
    assert [c["claimId"] for c in expect["claims"]] == ["subject", "object", "type", "direction", "scope"]
    assert list(body["questions"]) == [f"claim-{i}" for i in range(5)]
    state = body["state"]
    assert [q["label"] for q in state["quotes"]] == ["Q1", "Q2"] and "documentId" not in str(state) and "ev-a" not in str(state)
    assert "SYNTH-1" not in str(body) and "JOB" not in str(body), "internal refs and ids are never sent"
    assert state["relation"]["subject"] == {"kind": "company", "names": ["가상공급"]}
    for question in body["questions"].values():
        assert question["type"] == "choice" and question["instructions"]["task"] and "state.quotes" in question["instructions"]["question"]
    assert list(body["questions"]["claim-3"]["criteria"]) == ["supported", "contradicted", "insufficient", "reversed"], "direction may be reversed"
    assert list(body["questions"]["claim-0"]["criteria"]) == ["supported", "contradicted", "insufficient"], "reversed is illegal for a subject"
    assert "Q1" in body["questions"]["claim-2"]["instructions"]["question"] and "Q2" not in body["questions"]["claim-2"]["instructions"]["question"], \
        "a claim names only its own allowed quotes (ev-b is the first quote of the payload, so Q1)"



@pytest.mark.parametrize("business, product, count", [(None, None, 4), (None, "반도체", 5), ("제조", None, 5), ("제조", "반도체", 5)])
def test_scope_questions_cover_only_stated_attributes_with_the_same_allowed_quotes(business, product, count):
    payload = verify_relation_payload()
    payload["relation"].update(businessScope=business, productScope=product)
    payload["claims"] = claims({**payload["relation"], "citations": [{"evidenceId": "ev-a"}, {"evidenceId": "ev-b"}],
                                "validity": {"from": None, "until": None, "citations": []}})
    body, expect = jev.build_relation_request(payload, MODEL)
    assert len(body["questions"]) == count
    assert body["state"]["relation"]["businessScope"] == business and body["state"]["relation"]["productScope"] == product
    assert expect["claims"] == [{"claimId": name, "quoteIds": ["ev-a", "ev-b"], "options": list(jev.REVERSIBLE_OPTIONS if name == "direction" else jev.CLAIM_OPTIONS)}
                                for name in (["subject", "object", "type", "direction"] + (["scope"] if count == 5 else []))]


@pytest.mark.parametrize("business, product, text, verdicts, eligibility", [
    pytest.param(None, "반도체", "가상공급은 가상고객에 반도체를 공급한다.", {}, "eligible", id="unknown-business"),
    pytest.param("반도체 사업", None, "가상공급은 반도체 사업에서 가상고객에 제품을 공급한다.", {}, "eligible", id="unknown-product"),
    pytest.param(None, None, "가상공급은 가상고객에 반도체를 공급한다.", {}, "eligible", id="both-unknown"),
    pytest.param("의료 사업", "반도체", "가상공급은 가상고객에 반도체를 공급한다.",
                 {"scope": "insufficient"}, "hold", id="one-of-two-facts-unsupported"),
    pytest.param(None, "반도체만", "가상공급은 가상고객에 반도체를 공급한다.",
                 {"scope": "insufficient"}, "hold", id="exclusivity-unsupported"),
    pytest.param(None, "반도체만", "가상공급은 가상고객에 반도체만 공급한다.", {}, "eligible", id="exclusivity-stated"),
    pytest.param(None, "자동차 부품", "가상공급은 가상고객에 반도체를 공급하며 자동차 부품은 공급하지 않는다.",
                 {"scope": "contradicted"}, "reject", id="scope-contradicted"),
    pytest.param(None, "반도체", "다른공급은 가상고객에 반도체를 공급한다.",
                 {"subject": "contradicted"}, "reject", id="wrong-business-identity"),
    pytest.param(None, None, "가상공급과 가상고객은 각각 반도체 사업을 운영한다.",
                 {"type": "insufficient", "direction": "insufficient"}, "hold", id="same-business-is-not-supply"),
])
def test_scope_requests_preserve_facts_and_all_claims_still_gate_the_decision(business, product, text, verdicts, eligibility):
    """Synthetic request/gate contract only: authored provider choices do not prove Jev's semantic accuracy."""
    candidate = {**facts(), "businessScope": business, "productScope": product,
                 "citations": [{"evidenceId": "ev-scope"}], "validity": {"from": None, "until": None, "citations": []}}
    payload = verify_relation_payload()
    payload["relation"] = {**facts(), "businessScope": business, "productScope": product}
    payload["quotes"] = [quote("ev-scope", text)]
    payload["claims"] = rules.claims(candidate)
    before = copy.deepcopy(payload)
    body, expect = jev.build_relation_request(payload, MODEL)
    assert payload == before
    assert body["state"]["relation"]["businessScope"] == business
    assert body["state"]["relation"]["productScope"] == product
    assert body["state"]["relation"]["subject"] == {"kind": "company", "names": ["가상공급"]}
    assert body["state"]["relation"]["object"] == {"kind": "company", "names": ["가상고객"]}
    assert body["state"]["quotes"] == [{"label": "Q1", "text": text}]
    expected_ids = ["subject", "object", "type", "direction"]
    if business is not None or product is not None:
        expected_ids.append("scope")
    assert [claim["claimId"] for claim in expect["claims"]] == expected_ids
    assert all(claim["quoteIds"] == ["ev-scope"] for claim in expect["claims"])
    winners = {f"claim-{i}": verdicts.get(claim_id, "supported") for i, claim_id in enumerate(expected_ids)}
    response, audit = jev.interpret_relation(answers_for(body, winners), expect, MODEL)
    assert decide_relation({"claims": payload["claims"]}, response)["eligibility"] == eligibility
    assert [row["decision"] for row in audit] == [verdicts.get(claim_id, "supported") for claim_id in expected_ids]
    assert all(row["quoteIds"] == (["ev-scope"] if row["verdict"] == "supported" else []) for row in response["claims"])
    if "scope" in expected_ids:
        # Keeping the scope claim in the request is not enough: a missing/uncertain answer must never auto-pass it.
        missing = answers_for(body, winners)
        missing["answers"].pop(f"claim-{expected_ids.index('scope')}")
        with pytest.raises(ValueError, match="live_answers_invalid"):
            jev.interpret_relation(missing, expect, MODEL)


@pytest.mark.parametrize("p, confidence, expected", [(0.90, 0.80, "eligible"), (0.899, 0.95, "hold"), (0.97, 0.799, "hold")])
def test_scope_correction_keeps_the_existing_probability_and_confidence_gates(p, confidence, expected):
    body, expect = relation_body()
    reply = answers_for(body)
    reply["answers"]["claim-4"] = choice("supported", jev.CLAIM_OPTIONS, p, confidence)
    response, audit = jev.interpret_relation(reply, expect, MODEL)
    assert decide_relation({"claims": verify_relation_payload()["claims"]}, response)["eligibility"] == expected
    assert audit[4]["choice"] == "supported"
    assert audit[4]["probabilities"]["supported"] == p and audit[4]["confidence"] == confidence


def test_scope_question_change_has_a_new_binding_without_changing_other_questions_or_reinterpreting_answers(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    current = LiveRuntime.from_env()
    payload = verify_relation_payload()
    prepared = current.prepare("verify-relation", payload)
    with monkeypatch.context() as prior:
        prior.setitem(jev.CLAIM_TEMPLATES, "scope", OLD_SCOPE_QUESTION)
        historical = LiveRuntime.from_env()
        old_binding = historical.binding()
        old_prepared = historical.prepare("verify-relation", payload)
        old_reply = answers_for(old_prepared["body"], {"claim-4": "insufficient"})
        old_decoded = jev.interpret_relation(old_reply, old_prepared["expect"], MODEL)
    assert prepared["bindingIdentity"] != old_prepared["bindingIdentity"]
    assert prepared["promptVersion"] != old_prepared["promptVersion"]
    assert prepared["schemaDigest"] != old_prepared["schemaDigest"]
    assert prepared["requestDigest"] != old_prepared["requestDigest"]
    assert prepared["body"]["state"] == old_prepared["body"]["state"]
    assert prepared["expect"] == old_prepared["expect"]
    questions, old_questions = prepared["body"]["questions"], old_prepared["body"]["questions"]
    assert {key for key in questions if questions[key] != old_questions[key]} == {"claim-4"}
    assert questions["claim-4"]["criteria"] == old_questions["claim-4"]["criteria"]
    assert current.binding()["verifier"]["policy"] == old_binding["verifier"]["policy"]
    assert not current.accepts(old_binding)
    with pytest.raises(LiveFailure, match="live_binding_mismatch"):
        LiveRuntime.from_binding(old_binding)
    # The pure decoder retains the historical insufficient verdict; this is not a fresh semantic judgment.
    assert jev.interpret_relation(old_reply, old_prepared["expect"], MODEL) == old_decoded
    assert decide_relation({"claims": payload["claims"]}, old_decoded[0])["eligibility"] == "hold"
    assert list(tmp_path.iterdir()) == [], "preparing/comparing identities must not create a budget or state"


def test_supported_claims_cite_exactly_their_allowed_quotes_and_the_result_satisfies_the_native_contract():
    body, expect = relation_body()
    response, audit = jev.interpret_relation(answers_for(body), expect, MODEL)
    assert [c["quoteIds"] for c in response["claims"]] == [["ev-a", "ev-b"], ["ev-a", "ev-b"], ["ev-b"], ["ev-b"], ["ev-a", "ev-b"]]
    assert all(c["verdict"] == "supported" for c in response["claims"]) and len(audit) == 5 and audit[0]["probabilities"]["supported"] == pytest.approx(0.97)
    VerifierResponse.model_validate(response)
    candidate = {"claims": copy.deepcopy(verify_relation_payload()["claims"])}
    assert decide_relation(candidate, response)["eligibility"] == "eligible"


@pytest.mark.parametrize("p, confidence", [(0.89, 0.95), (0.97, 0.79), (0.5, 0.5)])
def test_a_low_probability_or_low_confidence_is_insufficient_and_therefore_a_hold_never_a_reject(p, confidence):
    body, expect = relation_body()
    response, audit = jev.interpret_relation(answers_for(body, {"claim-1": "contradicted"}, p, confidence), expect, MODEL)
    assert response["claims"][1] == {"claimId": "object", "verdict": "insufficient", "quoteIds": []}
    assert "not accepted" in audit[1]["note"] and audit[1]["choice"] == "contradicted"
    candidate = {"claims": verify_relation_payload()["claims"]}
    assert decide_relation(candidate, jev.interpret_relation(answers_for(body, {"claim-1": "contradicted"}, p, confidence), expect, MODEL)[0])["eligibility"] != "reject"


def test_confident_contradiction_rejects_and_confident_reversal_holds_only_where_it_is_legal():
    body, expect = relation_body()
    response, _ = jev.interpret_relation(answers_for(body, {"claim-1": "contradicted", "claim-3": "reversed"}), expect, MODEL)
    assert [c["verdict"] for c in response["claims"]] == ["supported", "contradicted", "supported", "reversed", "supported"]
    assert response["claims"][3]["quoteIds"] == [] and response["claims"][1]["quoteIds"] == []
    decision = decide_relation({"claims": verify_relation_payload()["claims"]}, response)
    assert decision["eligibility"] == "reject"
    held = jev.interpret_relation(answers_for(body, {"claim-3": "reversed"}), expect, MODEL)[0]
    assert decide_relation({"claims": verify_relation_payload()["claims"]}, held)["eligibility"] == "hold"
    # `reversed` is not an option for a subject claim, so a reply that names it is a contract violation
    bad = answers_for(body)
    bad["answers"]["claim-0"] = choice("reversed", ["supported", "contradicted", "insufficient", "reversed"])
    with pytest.raises(ValueError, match="live_answers_invalid"):
        jev.interpret_relation(bad, expect, MODEL)


def test_indirect_relations_get_step_and_connection_questions():
    payload = verify_relation_payload()
    path = [{"type": "SUPPLIES", "subject": endpoint("company", "A", "가"), "object": endpoint("company", "B", "나")},
            {"type": "SUPPLIES", "subject": endpoint("company", "B", "나"), "object": endpoint("company", "C", "다")}]
    payload["relation"] = {**facts(), "connection": "indirect", "path": path}
    payload["claims"] = [{"claimId": "step:1", "quoteIds": ["ev-a"]}, {"claimId": "step:2", "quoteIds": ["ev-b"]},
                         {"claimId": "connection", "quoteIds": ["ev-a", "ev-b"]}]
    body, expect = jev.build_relation_request(payload, MODEL)
    assert list(body["questions"]["claim-0"]["criteria"])[-1] == "reversed" and list(body["questions"]["claim-2"]["criteria"]) == list(jev.CLAIM_OPTIONS)
    assert "step 1" in body["questions"]["claim-0"]["instructions"]["question"] and body["state"]["relation"]["path"][1]["object"] == {"kind": "company", "names": ["다"]}
    payload["claims"][0]["claimId"] = "step:3"
    with pytest.raises(ValueError, match="live_payload_invalid"):
        jev.build_relation_request(payload, MODEL)


@pytest.mark.parametrize("mutate", [
    lambda p: p["claims"].append({"claimId": "invented", "quoteIds": ["ev-a"]}),
    lambda p: p["claims"].__setitem__(0, {"claimId": "subject", "quoteIds": ["ev-unknown"]}),
    lambda p: p["claims"].__setitem__(4, {"claimId": "scope", "quoteIds": ["ev-unseen"]}),
    lambda p: p.__setitem__("claims", []),
    lambda p: p["quotes"].append(quote("ev-a")),
    lambda p: p["quotes"][0].__setitem__("text", ""),
    lambda p: p["relation"].__setitem__("type", "SAME"),
    lambda p: p.pop("relation"),
])
def test_an_unbuildable_relation_payload_is_refused_before_anything_is_sent(mutate):
    payload = verify_relation_payload()
    mutate(payload)
    with pytest.raises(ValueError, match="live_payload_invalid"):
        jev.build_relation_request(payload, MODEL)


def test_a_supported_verdict_without_any_allowed_quote_can_never_be_produced():
    payload = verify_relation_payload()
    payload["claims"][0] = {"claimId": "subject", "quoteIds": []}
    body, expect = jev.build_relation_request(payload, MODEL)
    response, audit = jev.interpret_relation(answers_for(body), expect, MODEL)
    assert response["claims"][0] == {"claimId": "subject", "verdict": "insufficient", "quoteIds": []} and "without any allowed quote" in audit[0]["note"]


@pytest.mark.parametrize("break_reply, code", [
    (lambda r: r.__setitem__("model", "jev-latest"), "live_model_mismatch"),
    (lambda r: r.__setitem__("model", None), "live_model_mismatch"),
    (lambda r: r["answers"].pop("claim-0"), "live_answers_invalid"),
    (lambda r: r["answers"].__setitem__("claim-9", r["answers"]["claim-0"]), "live_answers_invalid"),
    (lambda r: r["answers"].__setitem__("claim-0", {"type": "noul", "noul": 0.9}), "live_answers_invalid"),
    (lambda r: r["answers"]["claim-0"]["probabilities"].__setitem__("supported", 0.5), "live_answers_invalid"),
    (lambda r: r["answers"]["claim-0"]["probabilities"].pop("insufficient"), "live_answers_invalid"),
    (lambda r: r["answers"]["claim-0"].__setitem__("choice", "insufficient"), "live_answers_invalid"),
    (lambda r: r["answers"]["claim-0"].__setitem__("confidence", 1.5), "live_answers_invalid"),
    (lambda r: r["answers"]["claim-0"].__setitem__("confidence", True), "live_answers_invalid"),
    (lambda r: r["answers"]["claim-0"].__setitem__("confidence", float("nan")), "live_answers_invalid"),
    (lambda r: r.__setitem__("answers", []), "live_answers_invalid"),
])
def test_every_contract_violation_of_a_jev_reply_is_a_stable_code_and_is_never_repaired(break_reply, code):
    body, expect = relation_body()
    reply = answers_for(body)
    break_reply(reply)
    with pytest.raises(ValueError, match=code):
        jev.interpret_relation(reply, expect, MODEL)
    with pytest.raises(ValueError, match="live_answers_invalid"):
        jev.interpret_relation("not a reply", expect, MODEL)


def test_impact_request_asks_the_target_and_every_quote_and_maps_effects_conservatively():
    body, expect = jev.build_impact_request(verify_impact_payload(), MODEL)
    assert list(body["questions"]) == ["target", "quote-0", "quote-1"] and expect == {"kind": "verify-impact", "quoteIds": ["ev-a", "ev-b"]}
    assert list(body["questions"]["target"]["criteria"]) == ["supported", "contradicted", "insufficient"]
    assert list(body["questions"]["quote-1"]["criteria"]) == ["positive", "negative", "neutral", "uncertain"] and "never a price forecast" in body["questions"]["quote-0"]["instructions"]["question"]
    assert "mixed" in body["questions"]["quote-1"]["criteria"]["uncertain"] and "no adequate evidence" in body["questions"]["quote-1"]["criteria"]["uncertain"]
    assert body["state"]["target"] == {"kind": "company", "names": ["가상고객"]} and "SYNTH" not in str(body)
    response, audit = jev.interpret_impact(answers_for(body, {"quote-0": "positive", "quote-1": "negative"}), expect, MODEL)
    assert response["target"] == "supported" and response["quotes"] == [{"quoteId": "ev-a", "effect": "positive"}, {"quoteId": "ev-b", "effect": "negative"}]
    ImpactVerifierResponse.model_validate(response)
    decision = decide_impact({"quotes": [{"quoteId": "ev-a"}, {"quoteId": "ev-b"}]}, response)
    assert decision["status"] == "verified" and decision["label"] == "mixed" and len(audit) == 3
    unsure, _ = jev.interpret_impact(answers_for(body, {"target": "contradicted", "quote-0": "positive"}, p=0.8), expect, MODEL)
    assert unsure["target"] == "insufficient" and [q["effect"] for q in unsure["quotes"]] == ["uncertain", "uncertain"]
    # one confident quote does not hide an unsure one: the unsure quote is explicit, never a verified neutral
    reply = answers_for(body, {"quote-0": "positive", "quote-1": "negative"})
    reply["answers"]["quote-1"] = choice("negative", list(body["questions"]["quote-1"]["criteria"]), p=0.7, confidence=0.95)
    partly, audit = jev.interpret_impact(reply, expect, MODEL)
    assert [q["effect"] for q in partly["quotes"]] == ["positive", "uncertain"] and "not accepted" in audit[2]["note"]
    reply["answers"]["quote-1"] = choice("neutral", list(body["questions"]["quote-1"]["criteria"]), p=0.97, confidence=0.5)
    assert [q["effect"] for q in jev.interpret_impact(reply, expect, MODEL)[0]["quotes"]] == ["positive", "uncertain"], "a low-confidence neutral is uncertain too"
    reply["answers"]["quote-1"] = choice("neutral", list(body["questions"]["quote-1"]["criteria"]), p=0.97, confidence=0.95)
    assert [q["effect"] for q in jev.interpret_impact(reply, expect, MODEL)[0]["quotes"]] == ["positive", "neutral"]
    # the model may say so itself: an explicit `uncertain` choice always maps to uncertain, however confident the model is about it
    reply["answers"]["quote-1"] = choice("uncertain", list(body["questions"]["quote-1"]["criteria"]), p=0.99, confidence=0.99)
    chose, audit = jev.interpret_impact(reply, expect, MODEL)
    assert [q["effect"] for q in chose["quotes"]] == ["positive", "uncertain"] and "chose uncertain" in audit[2]["note"]
    reply["answers"]["quote-1"] = choice("uncertain", list(body["questions"]["quote-1"]["criteria"]), p=0.4, confidence=0.1)
    assert [q["effect"] for q in jev.interpret_impact(reply, expect, MODEL)[0]["quotes"]] == ["positive", "uncertain"]
    contradicted, _ = jev.interpret_impact(answers_for(body, {"target": "contradicted"}), expect, MODEL)
    assert contradicted["target"] == "contradicted" and decide_impact({"quotes": [{"quoteId": "ev-a"}, {"quoteId": "ev-b"}]}, contradicted)["status"] == "reject"


@pytest.mark.parametrize("mutate", [lambda p: p.__setitem__("target", None), lambda p: p.__setitem__("quotes", []), lambda p: p.pop("relation")])
def test_an_unbuildable_impact_payload_is_refused(mutate):
    payload = verify_impact_payload()
    mutate(payload)
    with pytest.raises(ValueError, match="live_payload_invalid"):
        jev.build_impact_request(payload, MODEL)


def test_usage_reports_only_what_jev_reported_and_the_identity_binds_every_question_text():
    assert jev.usage({"usage": {"input_tokens": 12, "output_tokens": 0}}) == {"inputTokens": 12, "outputTokens": 0, "cachedTokens": None, "reasoningTokens": None}
    for bad in (None, {}, {"usage": {"input_tokens": -1, "output_tokens": 0}}, {"usage": {"input_tokens": True, "output_tokens": 0}}, {"usage": {"input_tokens": 1}},
                {"usage": {"input_tokens": 10**18, "output_tokens": 0}}, {"usage": {"input_tokens": jev.MAX_REPORTED_TOKENS + 1, "output_tokens": 0}},
                {"usage": {"input_tokens": 1.5, "output_tokens": 0}}):
        assert jev.usage(bad)["inputTokens"] is None
    assert jev.usage({"usage": {"input_tokens": jev.MAX_REPORTED_TOKENS, "output_tokens": 0}})["inputTokens"] == jev.MAX_REPORTED_TOKENS
    before = jev.identity()
    original = jev.CLAIM_TEMPLATES["type"]
    try:
        jev.CLAIM_TEMPLATES["type"] = original + " changed"
        assert jev.identity() != before
    finally:
        jev.CLAIM_TEMPLATES["type"] = original
    assert jev.identity() == before
