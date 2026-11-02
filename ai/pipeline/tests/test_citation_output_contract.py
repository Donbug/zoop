"""Opt-in exact citation output contracts, exercised through preparation and durable receipts."""
from __future__ import annotations

import json
import copy

import httpx
import pytest

from tests.live_support import PAYLOADS, environment, extract_payload, facts, openai_reply
from tests.test_live_prompts import extraction_case
from zoop_ai_pipeline import live_prompts, live_runtime
from zoop_ai_pipeline import extraction_replay as analysis, extraction_topic as topics, live_funding, relation_rules as rules
from zoop_ai_pipeline.country_context import CountryContext
from zoop_ai_pipeline.extraction_contracts import Catalogue, Mention, PairDecision, ReplyInvalid
from zoop_ai_pipeline.relation_contracts import digest
from zoop_ai_pipeline.live_runtime import LiveFailure, LiveRuntime

OUTPUT_ENV = "ZOOP_AI_PIPELINE_LIVE_OUTPUT_CONTRACT"
OUTPUT = "citation-enum-1"


def test_opt_in_request_rejects_provider_unknown_id_after_receipt(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path, **{OUTPUT_ENV: OUTPUT})
    _, payload, answer = extraction_case("첫째\n둘째")
    answer["mentions"][0]["evidence"] = [{"segmentId": "q-never-supplied"}]
    runtime = LiveRuntime.from_env(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=openai_reply(answer))))
    prepared = runtime.prepare("extract", payload)
    schema = prepared["body"]["response_format"]["json_schema"]["schema"]
    allowed = schema["$defs"]["Evidence"]["properties"]["segmentId"]["enum"]
    assert allowed == list(live_prompts.catalogue("extract", payload)[1])
    receipt = runtime.send(prepared, attempt_id="enum-unknown", authorize=lambda: None)
    # The HTTP answer is an accounting receipt, even when the peer ignored the enum.
    assert receipt["http"]["status"] == 200 and receipt["cost"]["settled"] is True
    with pytest.raises(LiveFailure, match="live_answers_invalid"):
        LiveRuntime.from_binding(runtime.binding()).answer("extract", receipt, prepared=prepared)


@pytest.mark.parametrize("bad", [
    {"segmentId": "q-foreign-request-0-0-1"}, {"segmentId": None}, {"segmentId": 1}, None, [],
    {"segmentId": "q-never-supplied", "quote": "invented"}])
def test_concrete_citation_definition_refuses_foreign_ids_and_wrong_shapes(monkeypatch, tmp_path, bad):
    environment(monkeypatch, tmp_path, **{OUTPUT_ENV: OUTPUT})
    _, payload, answer = extraction_case("한😀e\u0301 '*'\n반복\n반복")
    runtime = LiveRuntime.from_env()
    schema = runtime.prepare("extract", payload)["body"]["response_format"]["json_schema"]["schema"]
    _, references = live_prompts.catalogue("extract", payload)
    answer["mentions"][0]["evidence"] = [{"segmentId": key} for key in references]
    assert live_funding.schema_matches(answer, schema)
    expanded = live_prompts.expand("extract", payload, answer)
    assert expanded["mentions"][0]["evidence"] == list(references.values())
    answer["mentions"][0]["evidence"][0] = bad
    assert live_funding.schema_matches(answer, schema) is False


@pytest.mark.parametrize("fault", ["profile", "compiler", "template", "version"])
def test_binding_restoration_refuses_reinterpreted_contract(monkeypatch, tmp_path, fault):
    environment(monkeypatch, tmp_path, **{OUTPUT_ENV: OUTPUT})
    binding = LiveRuntime.from_env().binding()
    if fault == "profile":
        binding["generation"]["outputContract"]["name"] = "other"
    elif fault == "compiler":
        binding["generation"]["outputContract"]["compiler"] = "other"
    elif fault == "template":
        binding["stages"]["extract"]["templateSchemaDigest"] = "0" * 64
    else:
        binding["version"] = live_runtime.VERSION
    binding["identity"] = digest({k: v for k, v in binding.items() if k != "identity"})
    with pytest.raises(LiveFailure, match="live_binding_mismatch"):
        LiveRuntime.from_binding(binding)


@pytest.mark.parametrize("fault", ["schema", "template", "digest", "foreign-preimage"])
def test_receipt_restore_requires_exact_native_request_before_decoding(monkeypatch, tmp_path, fault):
    environment(monkeypatch, tmp_path, **{OUTPUT_ENV: OUTPUT})
    runtime = LiveRuntime.from_env(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=openai_reply(
        {"citationFormat": live_prompts.CITATION_FORMAT, "mentions": []}))))
    payload = extract_payload()
    prepared = runtime.prepare("extract", payload)
    restored = LiveRuntime.from_binding(runtime.binding())
    assert restored.prepare("extract", payload) == prepared
    receipt = runtime.send(prepared, attempt_id="restore", authorize=lambda: None)
    assert restored.answer("extract", receipt, prepared=prepared)["mentions"] == []
    if fault == "foreign-preimage":
        payload["companies"][0]["name"] = "another request"
        prepared = restored.prepare("extract", payload)
    else:
        receipt = copy.deepcopy(receipt)
        embedded = receipt["prepared"]
        if fault == "schema":
            embedded["body"]["response_format"]["json_schema"]["schema"]["$defs"]["Evidence"]["properties"]["segmentId"].pop("enum")
            embedded["schemaDigest"] = digest(embedded["body"]["response_format"]["json_schema"]["schema"])
        elif fault == "template":
            embedded["templateSchemaDigest"] = "0" * 64
        else:
            embedded["schemaDigest"] = "0" * 64
        embedded["requestDigest"] = digest(embedded["body"])
        embedded["digest"] = digest({k: v for k, v in embedded.items() if k != "digest"})
    with pytest.raises(LiveFailure, match="live_receipt_request_mismatch"):
        restored.answer("extract", receipt, prepared=prepared)


@pytest.mark.parametrize("stage", live_prompts.SPECS)
def test_empty_catalogue_prohibits_all_citations_and_preserves_native_empty_policy(monkeypatch, tmp_path, stage):
    environment(monkeypatch, tmp_path, **{OUTPUT_ENV: OUTPUT})
    payload = PAYLOADS[stage]()
    for source in payload["citationSources"]:
        source["mapped"] = []
    schema = LiveRuntime.from_env().prepare(stage, payload)["body"]["response_format"]["json_schema"]["schema"]
    citation_name = next(name for name, node in schema["$defs"].items() if set(node.get("properties", {})) == {"segmentId"})
    from tests.test_live_prompts import schema_nodes
    arrays = [node for node in schema_nodes(schema) if node.get("items", {}).get("$ref") == "#/$defs/" + citation_name]
    assert arrays and all(node.get("maxItems") == 0 for node in arrays)
    for node in arrays:
        assert live_funding.schema_matches([{"segmentId": "anything"}], node, schema) is False
    format_field = {"citationFormat": live_prompts.CITATION_FORMAT}
    no_cite = lambda *args: pytest.fail("an empty result tried to resolve source evidence")
    if stage == "extract":
        raw = {**format_field, "mentions": []}
        parsed = analysis.parse_extraction(live_prompts.expand(stage, payload, raw), analysis.Article.model_validate(payload["article"]), Catalogue(companies=[], revision="empty"))
        assert parsed.mentions == []
        _, _, invalid = extraction_case(payload["article"]["body"])
        with pytest.raises(ReplyInvalid, match="extraction_reply_invalid"):
            analysis.parse_extraction(live_prompts.expand(stage, payload, invalid), analysis.Article.model_validate(payload["article"]), Catalogue(companies=[], revision="empty"))
    elif stage == "compare":
        raw = {**format_field, "relation": "SAME", "reason": "missing evidence", "evidence": []}
        parsed = PairDecision.model_validate(live_prompts.expand(stage, payload, raw))
        a, _, mention = extraction_case("authored")
        m = Mention.model_validate(mention["mentions"][0])
        result = analysis.effective(m, [m], a, parsed, [])
        assert (result["relation"], result["rule"]) == ("HOLD", "evidence_missing")
    elif stage == "topic":
        raw = {**format_field, "schemaVersion": "zoop-topic-response-1", "producerVersion": "zoop-topic-replay-producer-1", "topics": []}
        parsed = topics.parse(live_prompts.expand(stage, payload, raw))
        assert topics.candidates(payload, parsed, no_cite) == []
        raw["topics"] = [{"label": "empty", "criteria": "authored", "rationale": "authored", "members": [{"kind": "event-candidate", "ref": "e"}], "citations": []}]
        with pytest.raises(ReplyInvalid, match="topic_reply_invalid"):
            topics.parse(live_prompts.expand(stage, payload, raw))
    elif stage == "relation":
        proposal = {**facts(), "subject": {"kind": "company", "ref": "SYNTH-3"}, "object": {"kind": "company", "ref": "SYNTH-1"},
                    "validity": {"from": None, "until": None, "citations": []}, "reason": "authored", "citations": []}
        proposal.pop("direction")
        raw = {**format_field, "schemaVersion": "zoop-relation-response-1", "producerVersion": "zoop-relation-producer-1", "relations": [proposal]}
        parsed = rules.parse_relations(live_prompts.expand(stage, payload, raw))
        view = rules.View({"SYNTH-3": ["supplier"], "SYNTH-1": ["customer"]}, {}, {}, CountryContext((), frozenset(), ()), no_cite)
        evaluated = rules.evaluate(rules.merge([p.wire() for p in parsed.relations])[0], view)
        assert evaluated["precheck"] == {"state": "hold", "reasons": [{"code": "evidence_missing"}]}
    else:
        raw = {**format_field, "schemaVersion": "zoop-impact-response-1", "producerVersion": "zoop-impact-producer-1",
               "impacts": [{"impactedCompanyId": "SYNTH-1", "direction": "undetermined", "reason": "missing evidence", "supporting": [], "opposing": [], "limitations": None}]}
        parsed = rules.parse_impacts(live_prompts.expand(stage, payload, raw))
        evaluated = rules.evaluate_impacts(parsed, {**facts(), "facts": facts()}, set(), no_cite)
        assert evaluated[0]["precheck"]["state"] == "no-evidence" and evaluated[0]["proposal"]["direction"] == "undetermined"
    assert live_funding.schema_matches(raw, schema)


def object_schema(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


@pytest.mark.parametrize("boundary", ["enums", "large-enum", "threshold", "characters", "properties", "nesting"])
def test_complete_schema_limits_accept_boundary_and_refuse_one_over(boundary):
    if boundary == "enums":
        accepted = object_schema({"a": {"type": "string", "enum": [str(i) for i in range(1000)]}})
        refused = copy.deepcopy(accepted)
        refused["properties"]["a"]["enum"].append("1000")
    elif boundary == "large-enum":
        values = [str(i).zfill(5) for i in range(250)] + ["x" * 13750]
        accepted = object_schema({"a": {"type": "string", "enum": values}})
        refused = copy.deepcopy(accepted)
        refused["properties"]["a"]["enum"][-1] += "x"
    elif boundary == "threshold":
        values = [str(i).zfill(61) for i in range(250)]
        accepted = object_schema({"a": {"type": "string", "enum": values}})
        refused = copy.deepcopy(accepted)
        refused["properties"]["a"]["enum"].append("last")
    elif boundary == "characters":
        accepted = object_schema({"a" * 120000: {"type": "string"}})
        refused = object_schema({"a" * 120001: {"type": "string"}})
    elif boundary == "properties":
        accepted = object_schema({str(i): {"type": "string"} for i in range(5000)})
        refused = object_schema({str(i): {"type": "string"} for i in range(5001)})
    else:
        node = {"type": "string"}
        for _ in range(9):
            node = {"type": "array", "items": node}
        accepted = object_schema({"a": node})
        refused = object_schema({"a": {"type": "array", "items": node}})
    live_prompts.check_output_limits(accepted)
    with pytest.raises(ValueError, match="live_output_schema_limits"):
        live_prompts.check_output_limits(refused)


def test_compiler_counts_domain_enums_and_request_bytes_before_send(monkeypatch, tmp_path):
    live_prompts.citation_schema("extract", [str(i) for i in range(993)])
    with pytest.raises(ValueError, match="live_output_schema_limits"):
        live_prompts.citation_schema("extract", [str(i) for i in range(994)])
    environment(monkeypatch, tmp_path, **{OUTPUT_ENV: OUTPUT})
    runtime = LiveRuntime.from_env()
    payload = extract_payload()
    payload["companies"][0]["name"] = ""
    size = runtime.prepare("extract", payload)["requestBytes"]
    payload["companies"][0]["name"] = "a" * (live_runtime.MAX_REQUEST_BYTES - size)
    assert runtime.prepare("extract", payload)["requestBytes"] == 300000
    payload["companies"][0]["name"] += "a"
    with pytest.raises(LiveFailure, match="live_request_too_large"):
        runtime.prepare("extract", payload)


@pytest.mark.parametrize("route", ["deepseek-v4-pro", "deepseek-v4-flash", "summary"])
def test_unsupported_output_routes_refuse_freezing(monkeypatch, tmp_path, route):
    environment(monkeypatch, tmp_path, **{OUTPUT_ENV: OUTPUT})
    family = live_runtime.ISSUE_SUMMARY if route == "summary" else live_runtime.PIPELINE
    if route != "summary":
        monkeypatch.setenv(live_runtime.MODEL_VAR, route)
    with pytest.raises(LiveFailure, match="live_output_route_unsupported"):
        LiveRuntime.from_env(family=family)


@pytest.mark.parametrize("fault", ["unknown-id", "unknown-outcome", "success"])
def test_native_s2_s3_owner_receipts_exports_and_unknown_recovery(monkeypatch, tmp_path, fault):
    import socket
    import sqlite3
    from scripts.extraction_smoke import LiveWorld, simulate, simulator_env
    from tests.test_extraction_live import go, session
    from zoop_ai_pipeline.extraction import Sources
    from zoop_ai_pipeline.ingestion_contracts import Authority
    from zoop_ai_pipeline.relation import Engine, Fixtures, Store
    from zoop_ai_pipeline.relation_contracts import Submit

    env = simulator_env("https://api.openai.com/v1", tmp_path / "budget", **{OUTPUT_ENV: OUTPUT})
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    world = LiveWorld(tmp_path / "world", env)
    world.kit.allow_model_send(world.runtime, stages=world.runtime.family.stages)
    requests = []

    def network_forbidden(*args, **kwargs):
        raise AssertionError("offline citation proof attempted a socket")

    monkeypatch.setattr(socket.socket, "connect", network_forbidden)
    monkeypatch.setattr(socket, "create_connection", network_forbidden)

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if "questions" in body:
            return httpx.Response(200, json=simulate(body))
        shown = json.loads(body["messages"][1]["content"])
        if shown["stage"] == "relation" and fault == "unknown-outcome":
            raise httpx.ReadTimeout("authored unknown outcome")
        response = simulate(body)
        if shown["stage"] == "relation" and fault == "unknown-id":
            raw = json.loads(response["choices"][0]["message"]["content"])
            raw["relations"][0]["citations"][0]["segmentId"] = "q-unknown"
            response["choices"][0]["message"]["content"] = json.dumps(raw)
        return httpx.Response(200, json=response)

    transport = httpx.MockTransport(handler)
    factory = lambda need_send=False: LiveRuntime.from_env(need_send=need_send, transport=transport)
    from zoop_ai_pipeline.extraction import LiveAccess
    done = go(world, LiveAccess(from_env=factory), "enum-s2")
    assert done["state"] == "ready"
    with session(world, LiveAccess(from_env=factory)) as owner:
        _, exported = owner.export("enum-s2")
        assert exported == done
    request = Submit.model_validate({"schemaVersion": "zoop-relation-s3", "jobId": "enum-s3", "provenance": done["provenance"],
                                    "upstream": {"jobId": done["jobId"], "inputDigest": done["inputDigest"]}})

    def s3(resume=False):
        store = Store(world.kit.root / "relation", world.kit.root / "extraction", world.kit.root / "ingestion")
        try:
            engine = Engine(store, Sources(world.kit.root / "ingestion", Authority(world.kit.registry_path)),
                            world.kit.root / "extraction", world.kit.root / "ingestion", factory)
            return engine.resume("enum-s3", Fixtures(None, None)) if resume else engine.run(request, Fixtures(None, None))
        finally:
            store.close()

    out = s3()
    if fault == "success":
        assert out["state"] == "ready" and out["counts"]["eligibility"]["eligible"] == 1
        for citation in out["relations"][0]["citations"]:
            doc = next(world.kit.export(ref)["document"]["text"] for ref in (world.a1, world.a2) if ref["documentId"] == citation["documentId"])
            assert citation["quote"] == doc[citation["start"]:citation["end"]]
    else:
        assert out["state"] == ("stopped" if fault == "unknown-id" else "reconciling")
        assert out["failure"]["code"] == ("live_answers_invalid" if fault == "unknown-id" else "live_response_unknown")
    with sqlite3.connect(world.kit.root / "relation" / "relation.sqlite3") as db:
        saved = db.execute("SELECT state,response,response_digest FROM calls ORDER BY started_at,attempt_id").fetchall()
    if fault == "unknown-outcome":
        assert saved == [("started", None, None)]
    else:
        for state, response, response_digest in saved:
            receipt = json.loads(response)
            assert state == "received" and digest(receipt) == response_digest
            if receipt["stage"] in live_prompts.SPECS:
                assert receipt["prepared"]["requestDigest"] == receipt["requestDigest"]
    sent = len(requests)
    assert s3(resume=True) == out and len(requests) == sent
    for body in requests:
        if "questions" in body:
            continue
        shown = json.loads(body["messages"][1]["content"])
        schema = body["response_format"]["json_schema"]["schema"]
        definition = next(node for node in schema["$defs"].values() if set(node.get("properties", {})) == {"segmentId"})
        assert definition["properties"]["segmentId"]["enum"] == [
            s["segmentId"] for source in shown["sources"] for s in source["segments"] if s["segmentId"] is not None]


def test_operating_receipts_validate_concrete_schema_and_refuse_oversize_forged_preparation(monkeypatch, tmp_path):
    from tests.live_support import json_response
    from tests.test_operating import runtime_session

    monkeypatch.setenv(OUTPUT_ENV, OUTPUT)
    _, payload, invalid = extraction_case("operating source")
    invalid["mentions"][0]["evidence"] = [{"segmentId": "q-not-in-operating-catalogue"}]
    with runtime_session(monkeypatch, tmp_path, handler=lambda request: json_response(openai_reply(invalid))) as (budget, runtime, peer):
        prepared = runtime.prepare("extract", payload)
        receipt = runtime.send(prepared, attempt_id="operating-enum", authorize=lambda: None)
        assert budget.receipt("operating-enum") == receipt
        restored = LiveRuntime.from_binding(runtime.binding())
        with pytest.raises(LiveFailure, match="live_answers_invalid"):
            restored.answer("extract", receipt, prepared=restored.prepare("extract", payload))
        forged = copy.deepcopy(prepared)
        schema = forged["body"]["response_format"]["json_schema"]["schema"]
        schema["$defs"]["Evidence"]["properties"]["segmentId"]["enum"] = [str(i) for i in range(1001)]
        forged["schemaDigest"] = digest(schema)
        forged["requestDigest"] = digest(forged["body"])
        forged["requestBytes"] = len(live_runtime.canonical(forged["body"]).encode())
        forged["reservation"] = runtime._worst_case("extract", forged["requestBytes"], 1)
        forged["digest"] = digest({k: v for k, v in forged.items() if k != "digest"})
        with pytest.raises(LiveFailure, match="live_prepared_invalid"):
            runtime.send(forged, attempt_id="forged-oversize", authorize=lambda: None)
        assert budget.snapshot()["calls"] == len(peer.requests) == 1


@pytest.mark.parametrize("stage", live_prompts.SPECS)
def test_every_reference_array_uses_the_single_constrained_definition(monkeypatch, tmp_path, stage):
    from tests.test_live_prompts import schema_nodes

    environment(monkeypatch, tmp_path, **{OUTPUT_ENV: OUTPUT})
    payload = PAYLOADS[stage]()
    if stage == "topic":
        payload["citationSources"] = PAYLOADS["relation"]()["citationSources"]
    prepared = LiveRuntime.from_env().prepare(stage, payload)
    schema = prepared["body"]["response_format"]["json_schema"]["schema"]
    ids = list(live_prompts.catalogue(stage, payload)[1])
    citation_name = next(name for name, node in schema["$defs"].items() if set(node.get("properties", {})) == {"segmentId"})
    constrained = [node for node in schema_nodes(schema) if node.get("enum") == ids]
    assert len(constrained) == 1
    for node in schema_nodes(schema):
        if node.get("items", {}).get("$ref") == "#/$defs/" + citation_name:
            assert live_funding.schema_matches([{"segmentId": ids[0]}], node, schema)
            assert live_funding.schema_matches([{"segmentId": "q-foreign"}], node, schema) is False


@pytest.mark.parametrize("shape", ["inline", "direct", "composition"])
def test_empty_compiler_refuses_uncovered_reference_shapes(monkeypatch, shape):
    from dataclasses import replace

    spec = live_prompts.SPECS["extract"]
    schema = copy.deepcopy(spec.schema)
    if shape == "inline":
        schema["$defs"]["Mention"]["properties"]["evidence"]["items"] = copy.deepcopy(schema["$defs"]["Evidence"])
    elif shape == "direct":
        schema["properties"]["unexpectedCitation"] = {"$ref": "#/$defs/Evidence"}
        schema["required"].append("unexpectedCitation")
    else:
        schema["allOf"] = []
    monkeypatch.setitem(live_prompts.SPECS, "extract", replace(spec, schema=schema))
    with pytest.raises(ValueError, match="live_output_schema_unsupported"):
        live_prompts.citation_schema("extract", [])


@pytest.mark.parametrize("failure", ["http-error", "unknown-id", "unknown-outcome"])
def test_capped_opt_in_keeps_one_physical_attempt_and_refuses_resend(monkeypatch, tmp_path, failure):
    from tests.live_support import json_response
    from tests.test_live_funding import chain_runtime
    from datetime import datetime
    from zoop_ai_pipeline import live_budget

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(live_budget._now())

    monkeypatch.setattr(live_funding, "datetime", Clock)

    _, payload, invalid = extraction_case("authored capped source")
    invalid["mentions"][0]["evidence"] = [{"segmentId": "q-not-supplied"}]

    def handler(request):
        if failure == "unknown-outcome":
            raise httpx.ReadTimeout("authored unknown outcome")
        return json_response({"error": {"code": "capacity"}}, 503) if failure == "http-error" else json_response(openai_reply(invalid, model=live_runtime.MODEL))

    runtime, peer, budget = chain_runtime(monkeypatch, tmp_path, handler, **{OUTPUT_ENV: OUTPUT})
    prepared = runtime.prepare("extract", payload)
    if failure == "unknown-outcome":
        with pytest.raises(LiveFailure, match="live_response_unknown") as caught:
            runtime.send(prepared, attempt_id="enum-capped", authorize=lambda: None)
        assert caught.value.uncertain is True
        assert budget.snapshot()["buckets"]["shared"]["reservedUsd"] != "0.000000000"
    else:
        receipt = runtime.send(prepared, attempt_id="enum-capped", authorize=lambda: None)
        with pytest.raises(LiveFailure, match="live_http_503" if failure == "http-error" else "live_answers_invalid"):
            runtime.answer("extract", receipt, prepared=prepared)
    with pytest.raises(LiveFailure, match="live_budget_attempt_duplicate"):
        runtime.send(prepared, attempt_id="enum-capped", authorize=lambda: None)
    snapshot = budget.snapshot()
    assert len(peer.requests) == snapshot["calls"] == snapshot["buckets"]["shared"]["calls"] == 1
    assert snapshot["buckets"]["personal"]["calls"] == 0
