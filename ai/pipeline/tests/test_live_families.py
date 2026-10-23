"""Live runtime families, offline: the default PIPELINE binding and prepared requests stay byte-identical (literals snapshotted from the
code BEFORE families existed), the ISSUE_SUMMARY family has its own stages that never cross, and the issue-summary prompt/verifier
projection, reply mapping and verdict policy are deterministic. Fake HTTP only; no key, endpoint or text is real."""
from __future__ import annotations

import json

import pytest

from tests.live_support import PAYLOADS, Fake, choice, environment, json_response, no_authorization, openai_reply
from zoop_ai_pipeline import issue_summary_jev as jev
from zoop_ai_pipeline import issue_summary_prompts as prompts
from zoop_ai_pipeline import live_runtime as live
from zoop_ai_pipeline.live_runtime import ISSUE_SUMMARY, PIPELINE, LiveFailure, LiveRuntime
from zoop_ai_pipeline.relation_contracts import canonical, digest

BUDGET_IDENTITY = "ab" * 32

# Snapshot of the unmodified runtime (constructor with a fixed budget identity, so it is path independent).
GOLDEN_IDENTITY = "54e2b9e00c4d8cb4a88376a7cb3aa0eeea908e59ed807a736094e70c1a84db57"
GOLDEN_BINDING_DIGEST = "0bd8f3972cb0a863b4d87307591fe1119250ac8a48e8b401b317d5ad13f7684a"
GOLDEN_GENERATION = "d9ed73de755509652f5e071cc7be0dc800bff4c3daa8f648ff8acf3eacd08ec7"
GOLDEN_VERIFIER = "ae7890815ca4c3622f58def8ee0d6ecbd330c01c40ab970ee4d08978930b8a32"
GOLDEN_STAGES = {
    "compare": "32a60d3071fbb6b9baf5e7fe552d00f1fb25431a0debdd74ab8044e48226c876",
    "extract": "817c884c47f807e8a82faec118b95538e9426f8f69e463507909183f10a105f9",
    "impact": "0bb0c7852df951336129d613b4f9c0be881acbaeb8c1035a2631607b56dec262",
    "relation": "b5b3fd96dc56fd6bf913c46c1f816a5bc1bdac4c22f62da413ea4bab86cf10c9",
    "topic": "49ccbe8e336111372503f5519f0ba089594502dd6820583788103110bf0f9f58",
    "verify-impact": "44e278186db7e56aba621c980172325a12f26126c371a7b2b82a43fc3fe61db8",
    "verify-relation": "8f5ac93576e0a3f473ad6b542ce70bda7bb1fcefe6dfaa3c2bd8256076707799"}
GOLDEN_PREPARED = {
    "extract": "e6b38213148c8eb4dd529cb14ed2a7deb0d5f615fed8a996a9e4eb7adcf02926",
    "compare": "ef5ff59394784af6aff465ee2487cc58b30d8dab14c978a99b1561ac9f094af9",
    "topic": "b45f6581c6bc5ef00bdda04f87d41e146ec60b7e9773b75134592101c0842655",
    "relation": "6fe7d3ef434e26c9fdc5f0118ecee0516c5fc7ef8a5eb5db421e9af6f95e9996",
    "impact": "7a4fffb33703fa26c14a3028dc6a58f74bee3cbfc2dfe39b251029fcd67a08c7",
    "verify-relation": "ad0931921d916200fd76324c73bd080d44bc4845e67c1028837fd13d322cf24f",
    "verify-impact": "13f040b4d44139ebce73f37ce08410a47198aa8a1884bd123c6256cdda945581"}


def fixed(family=None, **override) -> LiveRuntime:
    """A runtime with fixed, path-independent settings (no environment); `family=None` is the constructor default."""
    arguments = dict(model="gpt-6-luna", effort="high", max_output=24000, timeout=300, openai_url="https://api.openai.com/v1",
                     jev_url="https://api.typesafe.ai/v1", jev_model="jev-1.14.0", budget_identity=BUDGET_IDENTITY, send=None,
                     send_code="live_send_unavailable")
    arguments.update(override)
    return LiveRuntime(**arguments) if family is None else LiveRuntime(family=family, **arguments)


def built(monkeypatch, tmp_path, family=PIPELINE, handler=None):
    environment(monkeypatch, tmp_path)
    fake = Fake(handler or (lambda request: json_response({})))
    return LiveRuntime.from_env(transport=fake.transport, family=family), fake


def failure(call) -> LiveFailure:
    with pytest.raises(LiveFailure) as caught:
        call()
    return caught.value


# ---------------------------------------------------------------- the default family is unchanged -----------------------

def test_the_default_pipeline_binding_is_byte_identical_to_the_snapshot_taken_before_families_existed():
    binding = fixed().binding()
    assert binding["version"] == "zoop-live-runtime-1" and binding["identity"] == GOLDEN_IDENTITY
    assert digest(binding) == GOLDEN_BINDING_DIGEST and canonical(binding) == canonical(fixed(PIPELINE).binding())
    assert digest(binding["generation"]) == GOLDEN_GENERATION and digest(binding["verifier"]) == GOLDEN_VERIFIER
    assert {stage: digest(entry) for stage, entry in binding["stages"].items()} == GOLDEN_STAGES


def test_every_pipeline_prepared_request_is_byte_identical_to_the_snapshot():
    runtime = fixed()
    assert {stage: runtime.prepare(stage, PAYLOADS[stage]())["digest"] for stage in live.STAGES} == GOLDEN_PREPARED
    assert runtime.family is PIPELINE and PIPELINE.stages == live.STAGES and PIPELINE.generation_stages == live.GENERATION_STAGES
    assert PIPELINE.verify_stages == live.VERIFY_STAGES and PIPELINE.version == live.VERSION


def test_an_existing_binding_still_rebuilds_a_pipeline_runtime_and_the_default_env_family_is_pipeline(monkeypatch, tmp_path):
    runtime, _ = built(monkeypatch, tmp_path)
    assert runtime.family is PIPELINE and LiveRuntime.from_binding(runtime.binding()).family is PIPELINE
    assert LiveRuntime.from_binding(fixed().binding()).binding() == fixed().binding()


# ---------------------------------------------------------------- family boundaries -------------------------------------

def test_the_issue_summary_family_is_a_separate_versioned_binding_with_exactly_its_two_stages():
    binding = fixed(ISSUE_SUMMARY).binding()
    assert binding["version"] == "zoop-issue-summary-runtime-1" and binding["version"] != fixed().binding()["version"]
    assert set(binding["stages"]) == {"issue-summary", "verify-issue-summary"} == set(ISSUE_SUMMARY.stages)
    assert ISSUE_SUMMARY.generation_stages == ("issue-summary",) and ISSUE_SUMMARY.verify_stages == ("verify-issue-summary",)
    assert not set(ISSUE_SUMMARY.stages) & set(PIPELINE.stages) and binding["identity"] != GOLDEN_IDENTITY
    assert binding["verifier"]["model"] == "jev-1.14.0" and binding["verifier"]["adapterRevision"] == jev.ADAPTER_REVISION
    assert binding["verifier"]["adapterIdentity"] == jev.identity() and binding["generation"] == fixed().binding()["generation"]
    runtime = fixed(ISSUE_SUMMARY)
    assert runtime.purpose("issue-summary") == "pipeline:issue-summary" and runtime.purpose("verify-issue-summary") == "pipeline:verify-issue-summary"
    assert runtime.recipient("issue-summary") == fixed().recipient("extract")
    assert runtime.recipient("verify-issue-summary") == fixed().recipient("verify-relation")
    assert binding["stages"]["issue-summary"]["promptVersion"] == prompts.SPECS["issue-summary"].prompt_version
    assert binding["stages"]["verify-issue-summary"]["promptVersion"] == jev.PROMPT_PREFIX + jev.identity()[:16]


def test_a_stage_of_the_other_family_is_refused_everywhere_before_any_work():
    pipeline, summary = fixed(), fixed(ISSUE_SUMMARY)
    for runtime, stages in ((pipeline, ISSUE_SUMMARY.stages), (summary, PIPELINE.stages)):
        for stage in stages:
            assert failure(lambda: runtime.recipient(stage)).code == "live_stage_unsupported"
            assert failure(lambda: runtime.purpose(stage)).code == "live_stage_unsupported"
            assert failure(lambda: runtime.prepare(stage, {})).code == "live_stage_unsupported"
            assert failure(lambda: runtime.answer(stage, {"format": live.RECEIPT, "stage": stage})).code == "live_receipt_invalid"


def test_from_binding_selects_the_family_by_version_and_refuses_unknown_or_cross_family_forgeries():
    summary = fixed(ISSUE_SUMMARY)
    rebuilt = LiveRuntime.from_binding(summary.binding())
    assert rebuilt.family is ISSUE_SUMMARY and rebuilt.binding() == summary.binding()
    assert not rebuilt.accepts(fixed().binding()) and not fixed().accepts(summary.binding())
    body = {k: v for k, v in summary.binding().items() if k != "identity"}
    for forged in ({**summary.binding(), "version": "zoop-live-runtime-1"}, {**summary.binding(), "version": "zoop-live-runtime-2"},
                   {**summary.binding(), "version": ["zoop-live-runtime-1"]}, {**summary.binding(), "stages": fixed().binding()["stages"]},
                   {**body, "stages": {**body["stages"], "extract": fixed().binding()["stages"]["extract"]}, "identity": "x"}):
        assert failure(lambda: LiveRuntime.from_binding(forged)).code == "live_binding_mismatch"
    pipeline_as_summary = {**fixed().binding(), "version": ISSUE_SUMMARY.version}
    assert failure(lambda: LiveRuntime.from_binding(pipeline_as_summary)).code == "live_binding_mismatch"


def test_the_family_keeps_the_pinned_models_and_the_same_environment(monkeypatch, tmp_path):
    runtime, _ = built(monkeypatch, tmp_path, ISSUE_SUMMARY)
    assert runtime.family is ISSUE_SUMMARY and runtime.binding()["budget"] == built(monkeypatch, tmp_path)[0].binding()["budget"]
    environment(monkeypatch, tmp_path, **{live.JEV_MODEL_VAR: "jev-latest"})
    assert failure(lambda: LiveRuntime.from_env(family=ISSUE_SUMMARY)).code == "live_jev_model_unsupported"
    environment(monkeypatch, tmp_path, **{live.MODEL_VAR: "gpt-5"})
    assert failure(lambda: LiveRuntime.from_env(family=ISSUE_SUMMARY)).code == "live_model_unsupported"
    assert failure(lambda: fixed(ISSUE_SUMMARY, jev_model="jev-latest")).code == "live_jev_model_unsupported"


def test_the_offline_cli_defaults_to_pipeline_and_selects_the_family_by_name(monkeypatch, tmp_path, capsys):
    environment(monkeypatch, tmp_path)
    assert live.main(["binding"]) == 0
    default = json.loads(capsys.readouterr().out)
    assert default["binding"]["version"] == "zoop-live-runtime-1" and set(default["purposes"]) == set(live.STAGES)
    assert live.main(["binding", "pipeline"]) == 0 and json.loads(capsys.readouterr().out) == default
    assert live.main(["binding", "issue-summary"]) == 0
    chosen = json.loads(capsys.readouterr().out)
    assert chosen["binding"]["version"] == ISSUE_SUMMARY.version and set(chosen["purposes"]) == set(ISSUE_SUMMARY.stages) and chosen["network"] == "none"
    assert live.main(["binding", "other"]) == 2 and live.main([]) == 2 and live.main(["binding", "issue-summary", "x"]) == 2
    capsys.readouterr()


# ---------------------------------------------------------------- issue-summary generation ------------------------------

TITLE = "가상 공급 계약"
QUOTES = [{"quoteId": "ev-b", "context": "report", "text": "가상공급은 가상고객에 반도체를 공급한다."},
          {"quoteId": "ev-a", "context": "background", "text": "가상고객은 이를 확인했다."}]


def summary_payload() -> dict:
    return {"issueTitle": TITLE, "quotes": [dict(q) for q in QUOTES]}


def test_the_generation_request_is_a_strict_chat_request_with_only_the_projection():
    runtime = fixed(ISSUE_SUMMARY)
    prepared = runtime.prepare("issue-summary", summary_payload())
    body = prepared["body"]
    assert prepared["path"] == "chat/completions" and prepared["provider"] == "openai-compatible" and prepared["expect"] is None
    assert body["model"] == "gpt-6-luna" and body["reasoning_effort"] == "high" and body["max_completion_tokens"] == 24000
    assert body["response_format"]["json_schema"]["strict"] is True and body["response_format"]["json_schema"]["name"] == "zoop_issue_summary"
    assert body["messages"][0] == {"role": "system", "content": prompts.SYSTEM}
    assert json.loads(body["messages"][1]["content"]) == {"stage": "issue-summary", "input": {
        "issueTitle": TITLE, "titleNote": prompts.TITLE_NOTE,
        "quotes": [{"id": "q1", "context": "report", "text": QUOTES[0]["text"]}, {"id": "q2", "context": "background", "text": QUOTES[1]["text"]}]}}
    assert "ev-a" not in canonical(body) and "ev-b" not in canonical(body)
    assert prepared["schemaDigest"] == prompts.SPECS["issue-summary"].schema_digest and prepared["reservation"]["outputTokensMax"] == 24000
    assert prepared == runtime.prepare("issue-summary", summary_payload()) == LiveRuntime.from_binding(runtime.binding()).prepare("issue-summary", summary_payload())


def test_the_strict_schema_is_exactly_the_claims_object():
    schema = prompts.SPECS["issue-summary"].schema
    claim = schema["$defs"]["SummaryClaim"]
    assert schema["additionalProperties"] is False and schema["required"] == ["claims"]
    assert claim["additionalProperties"] is False and claim["required"] == ["text", "quoteIds"]


@pytest.mark.parametrize("payload", [
    {}, {"issueTitle": "", "quotes": QUOTES}, {"issueTitle": TITLE, "quotes": []}, {"issueTitle": TITLE, "quotes": QUOTES + [QUOTES[0]]},
    {"issueTitle": TITLE, "quotes": [{**QUOTES[0], "context": "other"}]}, {"issueTitle": TITLE, "quotes": [{**QUOTES[0], "text": ""}]},
    {"issueTitle": TITLE, "quotes": [{"quoteId": f"e{i}", "context": "report", "text": "가"} for i in range(61)]}])
def test_an_invalid_generation_payload_is_refused_before_any_request(payload):
    assert failure(lambda: fixed(ISSUE_SUMMARY).prepare("issue-summary", payload)).code == "live_payload_invalid"


def reply(claims) -> dict:
    return {"claims": claims}


GOOD_CLAIMS = [{"text": "가상공급이 가상고객에 반도체를 공급한다.", "quoteIds": ["q1"]},
               {"text": "가상고객이 이 사실을 확인했다.", "quoteIds": ["q2", "q1"]}]


def test_the_reply_maps_to_numbered_claims_with_sorted_owner_evidence_ids():
    assert prompts.claims_from(reply(GOOD_CLAIMS), summary_payload()) == [
        {"claimId": "c1", "text": GOOD_CLAIMS[0]["text"], "evidenceIds": ["ev-b"]},
        {"claimId": "c2", "text": GOOD_CLAIMS[1]["text"], "evidenceIds": ["ev-a", "ev-b"]}]
    assert prompts.quote_labels(summary_payload()) == {"q1": "ev-b", "q2": "ev-a"}


@pytest.mark.parametrize("answer", [
    None, [], {}, {"claims": []}, {"claims": GOOD_CLAIMS, "extra": 1}, {"claims": [{"text": GOOD_CLAIMS[0]["text"]}]},
    {"claims": [{**GOOD_CLAIMS[0], "extra": 1}]}, {"claims": [{"text": GOOD_CLAIMS[0]["text"], "quote_ids": ["q1"]}]},
    {"claims": [{**GOOD_CLAIMS[0], "text": "Supplier supplies chips."}]},  # no Hangul syllable
    {"claims": [{**GOOD_CLAIMS[0], "text": ""}]}, {"claims": [{**GOOD_CLAIMS[0], "text": " " + GOOD_CLAIMS[0]["text"]}]},
    {"claims": [{**GOOD_CLAIMS[0], "text": "가상공급이\n공급한다."}]}, {"claims": [{**GOOD_CLAIMS[0], "text": "가" * 281}]},
    {"claims": [{**GOOD_CLAIMS[0], "quoteIds": []}]}, {"claims": [{**GOOD_CLAIMS[0], "quoteIds": ["q9"]}]},
    {"claims": [{**GOOD_CLAIMS[0], "quoteIds": ["ev-b"]}]}, {"claims": [{**GOOD_CLAIMS[0], "quoteIds": ["q1", "q1"]}]},
    {"claims": [{**GOOD_CLAIMS[0], "quoteIds": [1]}]}, {"claims": [GOOD_CLAIMS[0]] * 6}])
def test_any_reply_deviation_is_a_deterministic_producer_invalid(answer):
    with pytest.raises(ValueError) as caught:
        prompts.claims_from(answer, summary_payload())
    assert str(caught.value) == "producer-invalid"


def test_the_limits_are_inclusive():
    five = [{"text": "가" * 280, "quoteIds": ["q1"]}] * 5
    assert len(prompts.claims_from(reply(five), summary_payload())) == 5
    many = {"issueTitle": TITLE, "quotes": [{"quoteId": f"e{i:02}", "context": "report", "text": "가상"} for i in range(60)]}
    cited = [f"q{i}" for i in range(1, 6)]
    assert prompts.claims_from(reply([{"text": "가상", "quoteIds": cited}]), many)[0]["evidenceIds"] == ["e00", "e01", "e02", "e03", "e04"]
    assert fixed(ISSUE_SUMMARY).prepare("issue-summary", many)["stage"] == "issue-summary", "exactly MAX_QUOTES quotes are accepted"
    over = [{"text": "가상", "quoteIds": cited + ["q6"]}]
    with pytest.raises(ValueError):
        prompts.claims_from(reply(over), many)


def test_a_generation_reply_round_trips_through_a_receipt_and_the_mapping(monkeypatch, tmp_path):
    runtime, fake = built(monkeypatch, tmp_path, ISSUE_SUMMARY, handler=lambda request: json_response(openai_reply(reply(GOOD_CLAIMS))))
    receipt = runtime.send(runtime.prepare("issue-summary", summary_payload()), attempt_id="isum:1", authorize=no_authorization)
    assert len(fake.requests) == 1 and receipt["stage"] == "issue-summary" and receipt["purpose"] == "pipeline:issue-summary"
    answer = runtime.answer("issue-summary", receipt)
    assert answer == reply(GOOD_CLAIMS) and runtime.audit("issue-summary", receipt) == []
    assert [c["claimId"] for c in prompts.claims_from(answer, summary_payload())] == ["c1", "c2"]
    refusal = openai_reply("{}", refusal="no")
    runtime, _ = built(monkeypatch, tmp_path, ISSUE_SUMMARY, handler=lambda request: json_response(refusal))
    stored = runtime.send(runtime.prepare("issue-summary", summary_payload()), attempt_id="isum:2", authorize=no_authorization)
    assert failure(lambda: runtime.answer("issue-summary", stored)).code == "live_model_refusal"


# ---------------------------------------------------------------- verifier ---------------------------------------------

VERIFY_QUOTES = [{"quoteId": "ev-b", "context": "report", "text": "가상공급은 가상고객에 반도체를 공급한다."},
                 {"quoteId": "ev-a", "context": "background", "text": "가상고객은 이를 확인했다."},
                 {"quoteId": "ev-c", "context": "report", "text": "인용되지 않은 문장이다."}]
VERIFY_CLAIMS = [{"claimId": "c1", "text": "가상공급이 가상고객에 반도체를 공급한다.", "quoteIds": ["ev-b"]},
                 {"claimId": "c2", "text": "가상고객이 이 사실을 확인했다.", "quoteIds": ["ev-b", "ev-a"]}]


def verify_payload() -> dict:
    return {"quotes": [dict(q) for q in VERIFY_QUOTES], "claims": [dict(c) for c in VERIFY_CLAIMS]}


def jev_answers(prepared: dict, winners: dict[str, str] | None = None, *, p: float = 0.97, confidence: float = 0.95, model: str = "jev-1.14.0") -> dict:
    answers = {}
    for key, question in prepared["body"]["questions"].items():
        options = list(question["criteria"])
        answers[key] = choice((winners or {}).get(key, "supported" if "supported" in options else "absent"), options, p, confidence)
    return {"model": model, "answers": answers, "usage": {"input_tokens": 1000, "output_tokens": 0}}


def decode(prepared: dict, **options) -> tuple[dict, list]:
    receipt_like = {"format": live.RECEIPT, "stage": "verify-issue-summary", "http": {"status": 200, "bodyText": json.dumps(jev_answers(prepared, **options)), "truncated": False},
                    "model": {"requested": "jev-1.14.0", "reported": None}, "expect": prepared["expect"], "cost": {"settled": True}}
    runtime = fixed(ISSUE_SUMMARY)
    return runtime.answer("verify-issue-summary", receipt_like), runtime.audit("verify-issue-summary", receipt_like)


def test_the_verifier_request_sends_only_the_cited_quotes_and_one_question_per_claim_plus_the_two_checks():
    runtime = fixed(ISSUE_SUMMARY)
    prepared = runtime.prepare("verify-issue-summary", verify_payload())
    body = prepared["body"]
    assert prepared["path"] == "systemone" and prepared["provider"] == "typesafe-native" and body["model"] == "jev-1.14.0"
    assert body["state"] == {"quotes": [{"label": "Q1", "context": "report", "text": VERIFY_QUOTES[0]["text"]},
                                        {"label": "Q2", "context": "background", "text": VERIFY_QUOTES[1]["text"]}],
                             "claims": [{"label": "C1", "text": VERIFY_CLAIMS[0]["text"], "quotes": ["Q1"]},
                                        {"label": "C2", "text": VERIFY_CLAIMS[1]["text"], "quotes": ["Q1", "Q2"]}]}
    assert list(body["questions"]) == ["claim-0", "claim-1", "advice", "causality", "framing"]
    assert list(body["questions"]["claim-0"]["criteria"]) == list(jev.CLAIM_OPTIONS) and list(body["questions"]["advice"]["criteria"]) == list(jev.CHECK_OPTIONS)
    assert "Q1" in body["questions"]["claim-0"]["instructions"]["question"] and "Q2" not in body["questions"]["claim-0"]["instructions"]["question"]
    assert "Q1, Q2" in body["questions"]["claim-1"]["instructions"]["question"] and "C2" in body["questions"]["claim-1"]["instructions"]["question"]
    assert all(question["instructions"]["task"] == jev.TASK for question in body["questions"].values())
    assert prepared["expect"] == {"kind": "verify-issue-summary", "claims": [{"claimId": "c1", "quoteIds": ["ev-b"]}, {"claimId": "c2", "quoteIds": ["ev-a", "ev-b"]}]}
    text = canonical(body)
    assert "ev-a" not in text and "ev-b" not in text and "ev-c" not in text and "인용되지 않은" not in text and TITLE not in text
    assert prepared["reservation"]["inputTokensUpperBound"] == prepared["requestBytes"] * 5 + live.INPUT_OVERHEAD_TOKENS
    assert prepared["schemaDigest"] == jev.identity()


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(claims=[]), lambda p: p.update(claims=[dict(p["claims"][0], claimId=f"c{i}") for i in range(6)]),
    lambda p: p["claims"][0].update(quoteIds=[]), lambda p: p["claims"][0].update(quoteIds=["ev-zz"]),
    lambda p: p["claims"][0].update(quoteIds=["ev-b", "ev-b"]), lambda p: p["claims"][1].update(claimId="c1"),
    lambda p: p["claims"][0].update(text=""), lambda p: p["quotes"][0].update(text=""), lambda p: p["quotes"].append(dict(p["quotes"][0])),
    lambda p: p.pop("quotes"), lambda p: p["quotes"][0].pop("context"), lambda p: p["quotes"][0].update(context="current"),
    lambda p: p["quotes"][1].update(context=None)])
def test_an_invalid_verifier_payload_is_refused_before_any_request(mutate):
    payload = verify_payload()
    mutate(payload)
    assert failure(lambda: fixed(ISSUE_SUMMARY).prepare("verify-issue-summary", payload)).code == "live_payload_invalid"


def test_all_supported_and_all_three_checks_absent_is_available():
    prepared = fixed(ISSUE_SUMMARY).prepare("verify-issue-summary", verify_payload())
    answer, audit = decode(prepared)
    assert answer == {"claims": [{"claimId": "c1", "decision": "supported", "reason": answer["claims"][0]["reason"]},
                                 {"claimId": "c2", "decision": "supported", "reason": answer["claims"][1]["reason"]}],
                      "prohibitedAdvice": "absent", "unsupportedCausality": "absent", "backgroundAsCurrent": "absent"}
    assert jev.outcome(answer) == "available" and [a["question"] for a in audit] == ["claim-0", "claim-1", "advice", "causality", "framing"]
    assert answer["claims"][0]["reason"].startswith("native_policy: supported accepted")


@pytest.mark.parametrize("winners, kwargs, expected, expect_answer", [
    ({"claim-1": "contradicted"}, {}, "verifier-reject", {"claim-1": "contradicted"}),
    ({"advice": "present"}, {}, "verifier-reject", {"prohibitedAdvice": "present"}),
    ({"causality": "present"}, {}, "verifier-reject", {"unsupportedCausality": "present"}),
    ({"framing": "present"}, {}, "verifier-reject", {"backgroundAsCurrent": "present"}),
    ({"claim-0": "insufficient"}, {}, "verifier-hold", {"claim-0": "insufficient"}),
    ({"claim-0": "contradicted", "claim-1": "insufficient"}, {}, "verifier-reject", {}),
    ({}, {"p": 0.6, "confidence": 0.95}, "verifier-hold", {"claim-0": "insufficient", "prohibitedAdvice": "uncertain"}),
    ({}, {"confidence": 0.5}, "verifier-hold", {"claim-1": "insufficient", "unsupportedCausality": "uncertain", "backgroundAsCurrent": "uncertain"}),
    ({"claim-0": "contradicted"}, {"p": 0.6}, "verifier-hold", {"claim-0": "insufficient"})])
def test_the_verdict_mapping_is_deterministic_and_low_confidence_is_a_hold_never_a_reject(winners, kwargs, expected, expect_answer):
    prepared = fixed(ISSUE_SUMMARY).prepare("verify-issue-summary", verify_payload())
    answer, _ = decode(prepared, winners=winners, **kwargs)
    assert jev.outcome(answer) == expected
    shown = {**{f"claim-{i}": c["decision"] for i, c in enumerate(answer["claims"])}, "prohibitedAdvice": answer["prohibitedAdvice"],
             "unsupportedCausality": answer["unsupportedCausality"], "backgroundAsCurrent": answer["backgroundAsCurrent"]}
    assert all(shown[key] == value for key, value in expect_answer.items())


@pytest.mark.parametrize("break_reply, code", [
    (lambda r: r.update(model="jev-latest"), "live_model_mismatch"), (lambda r: r["answers"].pop("advice"), "live_answers_invalid"),
    (lambda r: r["answers"].update(extra=r["answers"]["advice"]), "live_answers_invalid"),
    (lambda r: r["answers"].update(advice=choice("supported", list(jev.CLAIM_OPTIONS))), "live_answers_invalid"),
    (lambda r: r["answers"]["claim-0"].update(confidence=2), "live_answers_invalid")])
def test_a_verifier_reply_that_breaks_the_question_contract_fails_strictly(break_reply, code):
    prepared = fixed(ISSUE_SUMMARY).prepare("verify-issue-summary", verify_payload())
    reply_json = jev_answers(prepared)
    break_reply(reply_json)
    receipt = {"format": live.RECEIPT, "stage": "verify-issue-summary", "http": {"status": 200, "bodyText": json.dumps(reply_json), "truncated": False},
               "model": {"requested": "jev-1.14.0", "reported": None}, "expect": prepared["expect"], "cost": {"settled": True}}
    assert failure(lambda: fixed(ISSUE_SUMMARY).answer("verify-issue-summary", receipt)).code == code
    receipt["expect"] = {**prepared["expect"], "kind": "verify-relation"}
    assert failure(lambda: fixed(ISSUE_SUMMARY).answer("verify-issue-summary", receipt)).code == "live_receipt_invalid"


def test_a_verifier_request_round_trips_through_the_transport_with_only_the_jev_key(monkeypatch, tmp_path):
    holder: dict = {}
    runtime, fake = built(monkeypatch, tmp_path, ISSUE_SUMMARY, handler=lambda request: json_response(jev_answers(holder["prepared"])))
    holder["prepared"] = runtime.prepare("verify-issue-summary", verify_payload())
    receipt = runtime.send(holder["prepared"], attempt_id="isum:v", authorize=no_authorization)
    assert len(fake.requests) == 1 and str(fake.requests[0].url).endswith("/v1/systemone") and fake.requests[0].headers["authorization"].startswith("Bearer tsk-")
    assert receipt["purpose"] == "pipeline:verify-issue-summary" and jev.outcome(runtime.answer("verify-issue-summary", receipt)) == "available"
    assert runtime.audit("verify-issue-summary", receipt)[2]["question"] == "advice"


OLD_QUOTE = "가상공급은 작년에 가상고객과 계약을 체결했다."
CURRENT_CLAIM = "가상공급이 오늘 가상고객과 계약을 체결했다."
PAST_CLAIM = "가상공급이 이전에 가상고객과 계약을 체결했다."


def framing_payload(context: str, claim: str) -> dict:
    return {"quotes": [{"quoteId": "ev-1", "context": context, "text": OLD_QUOTE}], "claims": [{"claimId": "c1", "text": claim, "quoteIds": ["ev-1"]}]}


def authored_classifier(request):
    """An authored Jev decision computed from what the REQUEST shows, not a canned verdict: every claim and check is accepted except
    `framing`, which is `present` exactly when a claim that cites only `background`-labelled quotes is worded as happening now."""
    body = json.loads(request.content)
    contexts = {quote["label"]: quote["context"] for quote in body["state"]["quotes"]}
    current = any(all(contexts[label] == "background" for label in claim["quotes"]) and any(word in claim["text"] for word in ("오늘", "방금"))
                  for claim in body["state"]["claims"])
    answers = {}
    for key, question in body["questions"].items():
        options = list(question["criteria"])
        answers[key] = choice(("present" if current else "absent") if key == "framing" else "supported" if "supported" in options else "absent", options)
    return json_response({"model": "jev-1.14.0", "answers": answers, "usage": {"input_tokens": 1000, "output_tokens": 0}})


def judged(monkeypatch, tmp_path, payload: dict, attempt: str) -> tuple[dict, dict]:
    runtime, fake = built(monkeypatch, tmp_path, ISSUE_SUMMARY, handler=authored_classifier)
    receipt = runtime.send(runtime.prepare("verify-issue-summary", payload), attempt_id=attempt, authorize=no_authorization)
    return json.loads(fake.requests[0].content), runtime.answer("verify-issue-summary", receipt)


def test_a_background_quote_reaches_the_verifier_labelled_so_a_fabricated_current_framing_is_rejected_at_the_gate(monkeypatch, tmp_path):
    request, answer = judged(monkeypatch, tmp_path, framing_payload("background", CURRENT_CLAIM), "isum:bg-current")
    assert request["state"]["quotes"] == [{"label": "Q1", "context": "background", "text": OLD_QUOTE}]
    assert "background" in request["questions"]["framing"]["instructions"]["question"] and "background" in request["questions"]["claim-0"]["instructions"]["question"]
    assert [c["decision"] for c in answer["claims"]] == ["supported"], "the text alone supports the fact; only the framing is wrong"
    assert answer["backgroundAsCurrent"] == "present" and jev.outcome(answer) == "verifier-reject"


def test_the_same_wording_over_a_report_quote_or_a_past_wording_over_a_background_quote_is_available(monkeypatch, tmp_path):
    request, answer = judged(monkeypatch, tmp_path, framing_payload("report", CURRENT_CLAIM), "isum:report-current")
    assert request["state"]["quotes"][0]["context"] == "report" and answer["backgroundAsCurrent"] == "absent" and jev.outcome(answer) == "available"
    request, answer = judged(monkeypatch, tmp_path, framing_payload("background", PAST_CLAIM), "isum:bg-past")
    assert request["state"]["quotes"][0]["context"] == "background" and answer["backgroundAsCurrent"] == "absent" and jev.outcome(answer) == "available"


def test_the_verifier_identity_binds_every_question_and_threshold_and_differs_from_the_pipeline_adapter():
    from zoop_ai_pipeline import live_jev
    assert jev.identity() != live_jev.identity() and jev.VERIFIER.model == live_jev.MODEL and jev.VERIFIER.api == live_jev.API
    assert jev.policy()["choiceProbability"] == live_jev.CHOICE_PROBABILITY and jev.policy()["lowConfidence"]["advice"] == "uncertain"
    assert jev.outcome({"claims": [], "prohibitedAdvice": "absent", "unsupportedCausality": "absent", "backgroundAsCurrent": "absent"}) == "verifier-hold"
    assert jev.policy()["lowConfidence"]["framing"] == "uncertain"
