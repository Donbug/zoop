"""Frozen live producer contracts: strict schemas, sanitised outbound projections and deterministic citation resolution (offline)."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest

from tests.live_support import DOC_TEXT, VERSION_A, article, article_source, compare_payload, extract_payload, impact_payload, relation_payload, topic_payload
from zoop_ai_pipeline import live_prompts as prompts
from zoop_ai_pipeline import extraction_replay as analysis, extraction_topic as topics, relation_rules as rules
from zoop_ai_pipeline.extraction_contracts import Extraction, PairDecision, ReplyInvalid
from zoop_ai_pipeline.relation_contracts import RelationResponse

FORBIDDEN_KEYWORDS = {"default", "title", "minLength", "maxLength", "pattern", "format", "minimum", "maximum", "exclusiveMinimum", "const",
                      "minItems", "maxItems", "uniqueItems"}


def schema_nodes(node):
    """Every schema node of a JSON schema (never the property-name maps)."""
    if not isinstance(node, dict):
        return
    yield node
    for child in (node.get("properties") or {}).values():
        yield from schema_nodes(child)
    for key in ("items",):
        yield from schema_nodes(node.get(key))
    for key in ("anyOf", "allOf", "oneOf"):
        for child in node.get(key, []):
            yield from schema_nodes(child)
    for child in (node.get("$defs") or {}).values():
        yield from schema_nodes(child)


@pytest.mark.parametrize("stage", prompts.SPECS)
def test_every_live_schema_is_openai_strict_every_property_required_nothing_extra_and_no_validation_keywords(stage):
    schema = prompts.SPECS[stage].schema
    assert schema["type"] == "object"
    for node in schema_nodes(schema):
        assert not FORBIDDEN_KEYWORDS & set(node), (stage, FORBIDDEN_KEYWORDS & set(node))
        if "properties" in node:
            assert node["additionalProperties"] is False and node["required"] == list(node["properties"]), stage


def test_provider_references_replace_native_quotes_and_offsets_only_on_the_live_wire():
    extraction = prompts.SPECS["extract"].schema
    evidence = extraction["$defs"]["Evidence"]["properties"]
    assert evidence == {"segmentId": {"type": "string"}} and "keywords" in extraction["$defs"]["Mention"]["required"]
    assert prompts.SPECS["compare"].schema["properties"]["relation"]["enum"] == ["SAME", "DIFFERENT", "FOLLOWS", "CONFLICT", "HOLD"]
    relation = prompts.SPECS["relation"].schema
    assert relation["properties"]["schemaVersion"]["enum"] == ["zoop-relation-response-1"], "constants become one-value enums"
    assert relation["$defs"]["Citation"]["properties"] == {"segmentId": {"type": "string"}} and "from" in relation["$defs"]["Validity"]["properties"]
    # the native contracts are unchanged and still own validation after decoding
    assert Extraction.model_json_schema()["$defs"]["Evidence"]["properties"]["start"]["minimum"] == 0
    assert "minLength" in PairDecision.model_json_schema()["$defs"]["Evidence"]["properties"]["quote"]
    assert RelationResponse.model_json_schema(by_alias=True)["$defs"]["Citation"]["properties"]["start"]["minimum"] == 0


def test_extract_projection_keeps_text_and_identity_and_drops_everything_private():
    messages = prompts.SPECS["extract"].messages(extract_payload())
    assert [m["role"] for m in messages] == ["system", "user"]
    user = json.loads(messages[1]["content"])
    assert user["stage"] == "extract" and user["input"]["article"] == {
        "article_id": "doc-1", "article_version": article().version, "title": "가상 제목", "published_at": "2026-10-01",
        "language": "ko", "input_kind": "body"}
    assert "".join(s["text"] for s in user["sources"][0]["segments"]) == DOC_TEXT
    assert messages[1]["content"].count(DOC_TEXT) == 1
    text = messages[1]["content"]
    for private in ("private.example", "PRIVATE-PUBLISHER", "ORIGIN-X", "allow_model_send", "withdrawn", "synthetic", "prompt_version", "legacy"):
        assert private not in text, private


def test_a_tampered_or_incomplete_extract_payload_is_refused():
    payload = extract_payload()
    payload["article_version"] = "0" * 64
    with pytest.raises(ValueError, match="live_payload_invalid"):
        prompts.SPECS["extract"].messages(payload)
    payload = extract_payload()
    payload["article"]["unexpected"] = 1
    with pytest.raises(ValueError, match="live_payload_invalid"):
        prompts.SPECS["extract"].messages(payload)
    with pytest.raises(ValueError, match="live_payload_invalid"):
        prompts.SPECS["extract"].messages({"article": extract_payload()["article"]})


def test_compare_projection_adds_the_genuine_version_of_every_article_so_evidence_can_cite_it():
    first, second = article("본문 하나"), article("본문 둘")
    payload = compare_payload()
    user = json.loads(prompts.SPECS["compare"].messages(payload)[1]["content"])["input"]
    assert user["issue"]["articles"][0]["article_version"] == first.version and user["article"]["article_version"] == second.version != first.version
    assert "url" not in user["article"] and "publisher" not in user["article"]


def test_relation_projection_drops_the_job_identity_and_keeps_the_documents():
    user = json.loads(prompts.SPECS["relation"].messages(relation_payload())[1]["content"])["input"]
    assert "upstream" not in user and "JOB-SECRET" not in json.dumps(user) and user["documents"][0]["documentVersion"] == VERSION_A
    with pytest.raises(ValueError, match="live_payload_invalid"):
        prompts.SPECS["relation"].messages({"schemaVersion": "x"})


def test_prompt_and_schema_identities_are_deterministic_and_bind_their_text():
    spec = prompts.SPECS["relation"]
    assert spec.prompt_version == prompts.SPECS["relation"].prompt_version and spec.schema_digest == prompts.SPECS["relation"].schema_digest
    assert len({s.prompt_version for s in prompts.SPECS.values()}) == len(prompts.SPECS) == 5
    changed = replace(spec, system=spec.system + " changed")
    assert changed.prompt_version != spec.prompt_version and changed.schema_digest == spec.schema_digest
    assert spec.schema_name == "zoop_relation" and all("untrusted" in s.system.lower() for s in prompts.SPECS.values())


def extraction_case(text):
    a = article(text)
    payload = {**extract_payload(), "article": a.model_dump(mode="json"), "article_version": a.version, "citationSources": [article_source(a)]}
    mention = {"mention_id": "m1", "article_id": a.article_id, "article_version": a.version, "title": "합성 사건",
               "event_type": "reported", "action": "발표", "target": None, "event_time": None, "period": None, "assertion_status": "announced",
               "participants": [], "evidence": [], "keywords": [], "background": False, "countries": []}
    return a, payload, {"citationFormat": prompts.CITATION_FORMAT, "mentions": [mention]}


@pytest.mark.parametrize("text, expected_sha", [
    ("'조사 착수 전' 은닉·폐기 행위에 대해 형사처벌 규정 마련", None),
    ("우버가 국내 1위 배달 플랫폼***인 '배달의민족'에 대한 경영권을 인수하게 된다.",
     "31521c92a5e7c00db9204057c90ea4721b5429a1a9f887dfe53b3693fc9717fc")])
def test_retained_failure_excerpts_as_synthetic_sources_preserve_every_literal(text, expected_sha):
    a, payload, response = extraction_case(text)
    shown, refs = prompts.catalogue("extract", payload)
    reference = {"segmentId": shown["sources"][0]["segments"][0]["segmentId"]}
    response["mentions"][0]["evidence"] = [reference]
    before = copy.deepcopy(response)
    expanded = prompts.expand("extract", payload, response)
    evidence = analysis.parse_extraction(expanded, a).mentions[0].evidence[0]
    assert evidence.quote == text and (evidence.start, evidence.end) == (0, len(text)) and evidence.matches(a)
    assert evidence.model_dump() == refs[reference["segmentId"]] and response == before
    if expected_sha:
        assert hashlib.sha256(evidence.quote.encode()).hexdigest() == expected_sha
    corrupted = copy.deepcopy(expanded)
    corrupted["mentions"][0]["evidence"][0]["quote"] = text.replace("***", "").replace("'", "")
    with pytest.raises(ReplyInvalid, match="extraction_reply_invalid"):
        analysis.parse_extraction(corrupted, a)


def test_segments_preserve_repeated_text_unicode_whitespace_and_unmapped_boundaries():
    text = "한😀e\u0301 '*'\n반복\n생성문\n반복\n" + "가" * (prompts.MAX_SEGMENT + 1)
    a, payload, response = extraction_case(text)
    gap = text.index("생성문")
    payload["citationSources"][0]["mapped"] = [[0, gap], [gap + 4, len(text)]]
    shown, refs = prompts.catalogue("extract", payload)
    segments = shown["sources"][0]["segments"]
    assert "".join(s["text"] for s in segments) == text
    assert [s["text"] for s in segments if s["segmentId"] is None] == ["생성문\n"]
    repeats = [s for s in segments if s["text"] == "반복\n"]
    assert len(repeats) == 2 and repeats[0]["segmentId"] != repeats[1]["segmentId"]
    response["mentions"][0]["evidence"] = [{"segmentId": repeats[1]["segmentId"]}]
    evidence = analysis.parse_extraction(prompts.expand("extract", payload, response), a).mentions[0].evidence[0]
    assert evidence.start == text.rindex("반복") and evidence.end == text.rindex("반복") + 3
    for c in refs.values():
        assert c["quote"] == text[c["start"]:c["end"]] and len(c["quote"]) <= 20_000
        assert any(left <= c["start"] < c["end"] <= right for left, right in payload["citationSources"][0]["mapped"])
    assert prompts.catalogue("extract", payload) == (shown, refs)


@pytest.mark.parametrize("fault", ["unknown", "stale-request", "stale-document", "extra", "legacy", "missing-format"])
def test_invalid_references_fail_atomically_without_mutating_a_valid_sibling(fault):
    _, payload, response = extraction_case("첫째\n둘째")
    _, refs = prompts.catalogue("extract", payload)
    first = {"segmentId": next(iter(refs))}
    bad = dict(first)
    if fault == "unknown":
        bad["segmentId"] = "q-not-sent"
    elif fault == "stale-request":
        payload["companies"][0]["name"] = "다른 요청"
    elif fault == "stale-document":
        payload["citationSources"][0]["documentVersion"] = "f" * 64
    elif fault == "extra":
        bad["quote"] = "첫째"
    elif fault == "legacy":
        bad = refs[first["segmentId"]]
    else:
        response.pop("citationFormat")
    response["mentions"][0]["evidence"] = [first, bad]
    before = copy.deepcopy(response)
    with pytest.raises(ReplyInvalid, match="live_citation_"):
        prompts.expand("extract", payload, response)
    assert response == before


def test_all_other_generation_paths_expand_into_the_existing_native_parsers_and_topic_membership():
    payload = compare_payload()
    _, refs = prompts.catalogue("compare", payload)
    expanded = prompts.expand("compare", payload, {"citationFormat": prompts.CITATION_FORMAT, "relation": "DIFFERENT", "reason": "distinct",
                                                   "evidence": [{"segmentId": r} for r in refs]})
    assert [c.quote for c in PairDecision.model_validate(expanded).evidence] == ["본문 하나", "본문 둘"]
    for stage in ("topic", "relation", "impact"):
        payload = relation_payload() if stage == "relation" else impact_payload() if stage == "impact" else {
            **topic_payload(), "documents": relation_payload()["documents"], "citationSources": relation_payload()["citationSources"],
            "events": [{"kind": "event-candidate", "ref": "event", "revision": None,
                        "documents": [{"documentId": "doc-1", "documentVersion": VERSION_A}]}]}
        _, refs = prompts.catalogue(stage, payload)
        citations = [{"segmentId": next(iter(refs))}]
        if stage == "topic":
            raw = {"schemaVersion": "zoop-topic-response-1", "producerVersion": "zoop-topic-replay-producer-1",
                   "topics": [{"label": "합성", "criteria": "공급", "rationale": "합성", "members": [{"kind": "event-candidate", "ref": "event"}], "citations": citations}]}
            parsed = topics.parse(prompts.expand(stage, payload, {**raw, "citationFormat": prompts.CITATION_FORMAT}))
            assert parsed.topics[0].citations[0].quote == DOC_TEXT
            payload["events"][0]["documents"] = [{"documentId": "other", "documentVersion": VERSION_A}]
            with pytest.raises(ReplyInvalid, match="topic_citation_unbound"):
                topics.candidates(payload, parsed, lambda *args: pytest.fail("unbound citation reached source resolution"))
            parsed.topics[0].members.append(parsed.topics[0].members[0])
            with pytest.raises(ReplyInvalid, match="topic_member_duplicate"):
                topics.candidates(payload, parsed, lambda *args: pytest.fail("duplicate membership reached source resolution"))
        elif stage == "relation":
            raw = {"schemaVersion": "zoop-relation-response-1", "producerVersion": "zoop-relation-producer-1",
                   "relations": [{"type": "SUPPLIES", "subject": {"kind": "company", "ref": "SYNTH-3"}, "object": {"kind": "company", "ref": "SYNTH-1"},
                                  "connection": "direct", "businessScope": None, "productScope": None, "validity": {"from": None, "until": None, "citations": []},
                                  "countries": [], "reason": "합성", "citations": citations, "path": []}]}
            parsed = rules.parse_relations(prompts.expand(stage, payload, {**raw, "citationFormat": prompts.CITATION_FORMAT}))
            assert parsed.relations[0].citations[0].quote == DOC_TEXT
        else:
            raw = {"schemaVersion": "zoop-impact-response-1", "producerVersion": "zoop-impact-producer-1",
                   "impacts": [{"impactedCompanyId": "SYNTH-1", "direction": "positive", "reason": "합성", "supporting": citations, "opposing": [], "limitations": None}]}
            parsed = rules.parse_impacts(prompts.expand(stage, payload, {**raw, "citationFormat": prompts.CITATION_FORMAT}))
            assert parsed.impacts[0].supporting[0].quote == DOC_TEXT


def test_response_schemas_pin_the_response_version_constants_that_differ_from_the_request_versions():
    """The model cannot copy a request schemaVersion: the strict schema allows exactly one (different) response value per stage."""
    for stage, payload in (("topic", topic_payload()), ("relation", relation_payload()), ("impact", impact_payload())):
        constant = prompts.SPECS[stage].schema["properties"]["schemaVersion"]["enum"]
        assert len(constant) == 1 and constant[0] != payload["schemaVersion"] and constant[0].endswith("response-1"), stage
        assert len(prompts.SPECS[stage].schema["properties"]["producerVersion"]["enum"]) == 1
