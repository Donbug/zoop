"""Offline S3 relation/impact candidate behavior: typed vocabulary, path/evidence gates, independent verification, impact labels,
HOLD review -> final human approval, receipt recovery, rights and isolation.

Replay (producer AND verifier) is authored-response replay, never independent AI inference. No network, model, PoC database or app state.
The upstream is a REAL ingestion + S2 extraction job read through the owner seam; nothing is mocked or echoed.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts import relation_smoke as rs
from scripts.relation_smoke import (BAD, COMP, CO, EVT, GOOD, INV, QB, SUP, SUP2, VALID, build_world, co, converge, ev, find, forged_span, impact_item,
    impact_reply, impact_verifier_reply, proposal, relation_reply, step, tp, verifier_reply, world_cite)
from tests.legacy_ledger import copy_as_legacy
from zoop_ai_pipeline import relation_rules as rules
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure
from zoop_ai_pipeline.relation import INITIAL_ATTEMPT, Engine, Store
from zoop_ai_pipeline.relation_contracts import Review, Submit, digest


@pytest.fixture
def world(tmp_path):
    return build_world(tmp_path / "owned")


def c(w, text, nth=0):
    return world_cite(w, "main", text, nth)


def codes(r):
    return [(x["code"], x.get("at")) for x in r["eligibility"]["reasons"]]


def database(w):
    db = sqlite3.connect(w.kit.root / "relation" / "relation.sqlite3")
    db.row_factory = sqlite3.Row
    return db


def tree(path):
    return rs.tree(path)


def stop_at_generation(w, job="gen"):
    out = w.kit.rel_job("run", w.kit.rsubmit(job, w.s2))
    assert out["failure"]["code"] == "producer_replay_required"
    return out["failure"]["detail"]["requestDigest"]


def review(w, job, relation, decision="allow", revision=None):
    return {**w.kit.rsel(job), "relationCandidateId": relation["relationCandidateId"], "decision": decision, "reviewer": "operator-a",
            "note": "authored review", "expectedRevision": relation["eligibility"]["revision"] if revision is None else revision}


# ---------------------------------------------------------------- typed vocabulary, direction, canonical pairs ---------

def test_direction_reversal_is_held_by_the_independent_verifier_and_never_flipped(world):
    w = world
    props = [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="배터리 부품"),
             proposal("SUPPLIES", co("SYNTH-1"), co("SYNTH-3"), [c(w, SUP)], product="배터리 부품", reason="생성기 사유: 고객이 공급한다")]
    out = converge(w, "j", props, verify=lambda r: {"direction": "reversed"} if r["subject"]["ref"] == "SYNTH-1" else None)
    right, wrong = find(out, "SUPPLIES", "SYNTH-3", "SYNTH-1"), find(out, "SUPPLIES", "SYNTH-1", "SYNTH-3")
    assert right["eligibility"]["status"] == "eligible" and right["relationCandidateId"] != wrong["relationCandidateId"]
    assert wrong["eligibility"]["status"] == "hold" and codes(wrong) == [("direction_reversed", "direction")]
    assert (wrong["subject"]["ref"], wrong["object"]["ref"]) == ("SYNTH-1", "SYNTH-3") and wrong["impact"]["status"] == "not-applicable"
    request = json.dumps(rules.verifier_request(wrong, INITIAL_ATTEMPT), ensure_ascii=False)
    assert "생성기 사유" not in request and "reason" not in request.lower() and wrong["relationCandidateId"] not in request
    assert SUP in request and "배터리 부품" in request  # fixed facts + exact quotes only


def test_competition_is_one_canonical_pair_while_type_and_scope_differences_stay_separate(world):
    w = world
    pair = lambda a, b, scope: proposal("COMPETES_WITH", co(a), co(b), [c(w, COMP)], business=scope)  # noqa: E731
    props = [pair("SYNTH-2", "SYNTH-1", "전기차 시장"), pair("SYNTH-1", "SYNTH-2", "전기차 시장"), pair("SYNTH-1", "SYNTH-2", "배터리 시장"),
             proposal("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(w, SUP2)], product="완성차"),
             proposal("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(w, SUP2)], product="부품")]
    out = converge(w, "j", props)
    assert len(out["relations"]) == 4
    market = next(r for r in out["relations"] if r["businessScope"] == "전기차 시장")
    assert (market["subject"]["ref"], market["object"]["ref"], market["proposalCount"], market["reordered"]) == ("SYNTH-1", "SYNTH-2", 2, True)
    assert market["relationKey"] == rules.relation_key(rules.normalize(pair("SYNTH-1", "SYNTH-2", "전기차 시장")))
    assert market["relationKey"] == rules.relation_key(rules.normalize(pair("SYNTH-2", "SYNTH-1", "전기차 시장")))
    assert {r["productScope"] for r in out["relations"] if r["type"] == "SUPPLIES"} == {"완성차", "부품"}
    assert all(r["eligibility"]["status"] == "eligible" and r["approved"] is False for r in out["relations"])


def test_directed_types_keep_orientation_and_symmetric_types_are_sorted(world):
    w = world
    out = converge(w, "j", [proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(w, INV)]), proposal("INVESTS_IN", co("SYNTH-3"), co("SYNTH-4"), [c(w, INV)])])
    forward, backward = find(out, "INVESTS_IN", "SYNTH-4", "SYNTH-3"), find(out, "INVESTS_IN", "SYNTH-3", "SYNTH-4")
    assert forward["direction"] == backward["direction"] == "directed" and forward["relationKey"] != backward["relationKey"]


# ---------------------------------------------------------------- paths, endpoints, direct vs indirect ----------------

def test_indirect_paths_need_connected_cited_steps_and_direct_is_distinct_from_two_hop(world):
    w = world
    s1, s2 = step("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)]), step("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(w, SUP2)])
    props = [
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", path=[s1, s2], product="two-hop"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [c(w, SUP)], product="direct"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", path=[s1, {**s2, "citations": []}], product="uncited"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", path=[s1], product="one-step"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", product="no-path"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", path=[s1, step("SUPPLIES", co("SYNTH-4"), co("SYNTH-2"), [c(w, SUP2)])], product="gap"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", path=[s1, {**s2, "type": "INVESTS_IN"}], product="mismatch"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", path=[s1, s2, s2], product="long"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [c(w, SUP)], path=[s1], product="direct-with-path"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], product="direct-without-evidence"),
        proposal("COMPETES_WITH", co("SYNTH-1"), co("SYNTH-2"), [], connection="indirect", path=[s1, s2], product="indirect-competition"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", path=[s1, step("SUPPLIES", co("SYNTH-1"), co("SYNTH-9"), [c(w, SUP2)])], product="unknown-step")]
    out = converge(w, "j", props)
    by = {r["productScope"]: r for r in out["relations"]}
    assert by["two-hop"]["eligibility"]["status"] == by["direct"]["eligibility"]["status"] == "eligible"
    assert [x["claimId"] for x in by["two-hop"]["claims"]][2:5] == ["step:1", "step:2", "connection"] and "step:1" not in [x["claimId"] for x in by["direct"]["claims"]]
    assert by["two-hop"]["connection"] == "indirect" and by["direct"]["connection"] == "direct" and len(by["two-hop"]["path"]) == 2
    expected = {"uncited": [("path_step_uncited", "step:2")], "one-step": [("path_incomplete", None)], "no-path": [("path_incomplete", None)],
                "gap": [("path_disconnected", None)], "mismatch": [("path_step_type_mismatch", "step:2")], "long": [("path_too_long", None)],
                "direct-without-evidence": [("evidence_missing", None)], "indirect-competition": [("indirect_unsupported_for_type", None)],
                "unknown-step": [("target_unknown", "step:2:object"), ("path_disconnected", None)]}
    for scope, reasons in expected.items():
        assert (by[scope]["eligibility"]["status"], codes(by[scope])) == ("hold", reasons), scope
    assert by["direct-with-path"]["eligibility"]["status"] == "reject" and codes(by["direct-with-path"]) == [("path_not_allowed_for_direct", None)]
    assert all(by[s]["history"][0]["verifier"] == "not-called" for s in expected)


def test_a_step_the_verifier_finds_reversed_or_contradicted_keeps_the_whole_path_ineligible(world):
    w = world
    s1, s2 = step("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)]), step("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(w, SUP2)])
    props = [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", path=[s1, s2], product=name) for name in ("rev", "con", "ins")]
    mapping = {"rev": {"step_1": "reversed"}, "con": {"step_2": "contradicted"}, "ins": {"connection": "insufficient"}}
    out = converge(w, "j", props, verify=lambda r: mapping[r["productScope"]])
    by = {r["productScope"]: r for r in out["relations"]}
    assert (by["rev"]["eligibility"]["status"], codes(by["rev"])) == ("hold", [("direction_reversed", "step:1")])
    assert (by["con"]["eligibility"]["status"], codes(by["con"])) == ("reject", [("claim_contradicted", "step:2")])
    assert (by["ins"]["eligibility"]["status"], codes(by["ins"])) == ("hold", [("claim_insufficient", "connection")])


def test_unknown_endpoint_is_a_private_hold_and_wrong_target_is_contradicted_by_the_verifier(world):
    w = world
    props = [proposal("SUPPLIES", co("SYNTH-9"), co("SYNTH-1"), [c(w, SUP)], product="unknown"),
             proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP2)], product="wrong-target")]
    out = converge(w, "j", props, verify=lambda r: {"object": "contradicted"})
    unknown, wrong = find(out, "SUPPLIES", "SYNTH-9", "SYNTH-1"), find(out, "SUPPLIES", "SYNTH-3", "SYNTH-1")
    assert (unknown["eligibility"]["status"], codes(unknown)) == ("hold", [("target_unknown", "subject")]) and unknown["history"][0]["verifier"] == "not-called"
    assert (wrong["eligibility"]["status"], codes(wrong)) == ("reject", [("claim_contradicted", "object")])


# ---------------------------------------------------------------- event vs topic; non-proof signals -------------------

def test_event_participation_and_company_topic_are_explicit_distinct_kinds(world):
    w = world
    props = [proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(w.evc), [c(w, EVT)]),
             proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(w.event), [world_cite(w, "b", QB)]),
             proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp(w.tp), [c(w, EVT)]),
             proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp(w.event), [c(w, EVT)]),
             proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp(w.evc), [c(w, EVT)]),
             proposal("PARTICIPATES_IN", co("SYNTH-1"), tp(w.tp), [c(w, EVT)]),
             proposal("RELATES_TO_TOPIC", co("SYNTH-1"), ev(w.evc), [c(w, EVT)]),
             proposal("PARTICIPATES_IN", co("SYNTH-1"), ev("tp-unknown"), [c(w, EVT)]),
             proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp("tp-" + "0" * 64), [c(w, EVT)]),
             proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(w.evc), [world_cite(w, "b", QB)], product="outside-evidence")]
    out = converge(w, "j", props)
    ok = [r for r in out["relations"] if r["eligibility"]["status"] == "eligible"]
    assert {(r["type"], r["object"]["kind"], r["object"]["ref"]) for r in ok} == {("PARTICIPATES_IN", "event", w.evc), ("PARTICIPATES_IN", "event", w.event), ("RELATES_TO_TOPIC", "topic", w.tp)}
    assert codes(find(out, "RELATES_TO_TOPIC", "SYNTH-1", w.event)) == [("event_id_not_topic", "object")]
    assert codes(find(out, "RELATES_TO_TOPIC", "SYNTH-1", w.evc, **{"object": {"kind": "topic", "ref": w.evc}})) == [("event_id_not_topic", "object")]
    assert codes(find(out, "PARTICIPATES_IN", "SYNTH-1", w.tp)) == [("endpoint_kind_invalid", "object")]
    assert codes(find(out, "RELATES_TO_TOPIC", "SYNTH-1", w.evc, **{"object": {"kind": "event", "ref": w.evc}})) == [("endpoint_kind_invalid", "object")]
    assert codes(find(out, "PARTICIPATES_IN", "SYNTH-1", "tp-unknown")) == [("target_unknown", "object")]
    assert codes(find(out, "RELATES_TO_TOPIC", "SYNTH-1", "tp-" + "0" * 64)) == [("target_unknown", "object")]
    outside = next(r for r in out["relations"] if r["eligibility"]["status"] == "reject" and r["productScope"] == "outside-evidence")
    assert outside["citations"][0]["error"] == "citation_not_target_evidence" and codes(outside) == [("citation_invalid", "citations:1")]
    assert all(r["approved"] is False for r in out["relations"])


def test_identity_signals_cooccurrence_and_unsupported_types_are_never_relationship_proof(world):
    w = world
    names = ("SAME", "FOLLOWS", "SHARES_ISSUE", "CO_MENTION", "INVOLVES", "STRUCTURALLY_RELATED_TO")
    props = [proposal(name, co("SYNTH-1"), co("SYNTH-2"), [c(w, CO)]) for name in names] + [proposal("OWNS", co("SYNTH-1"), co("SYNTH-2"), [c(w, CO)]),
             proposal("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(w, CO)])]
    out = converge(w, "j", props, verify=lambda r: {"type": "insufficient", "direction": "insufficient", "subject": "insufficient"})
    for name in names:
        assert codes(find(out, name)) == [("non_relationship_basis", None)], name
    assert codes(find(out, "OWNS")) == [("relation_type_unsupported", None)]
    comention = find(out, "SUPPLIES")
    assert comention["eligibility"]["status"] == "hold" and {x[0] for x in codes(comention)} == {"claim_insufficient"}
    assert not [r for r in out["relations"] if r["eligibility"]["status"] == "eligible"] and out["counts"]["impactCandidates"] == 0


# ---------------------------------------------------------------- validity / country -----------------------------------

def test_validity_is_unknown_unless_cited_and_never_invented(world):
    w = world
    props = [proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(w, INV)]),
             proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(w, INV)], validity={"from": "2026-01-01", "until": "2026-12-31", "citations": [c(w, VALID)]}),
             proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(w, INV)], validity={"from": "2026-01-01", "until": None, "citations": []}),
             proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(w, INV)], validity={"from": "2026-12-31", "until": "2026-01-01", "citations": [c(w, VALID)]})]
    out = converge(w, "j", props)
    by = {(r["validity"]["from"], r["validity"]["until"]): r for r in out["relations"]}
    unknown, known = by[(None, None)], by[("2026-01-01", "2026-12-31")]
    assert (unknown["validity"]["fromStatus"], unknown["validity"]["untilStatus"]) == ("unknown", "unknown") and unknown["eligibility"]["status"] == "eligible"
    assert (known["validity"]["fromStatus"], known["validity"]["untilStatus"]) == ("known", "known") and "validity" in [x["claimId"] for x in known["claims"]]
    assert known["eligibility"]["status"] == "eligible" and "validity" not in [x["claimId"] for x in unknown["claims"]]
    assert codes(by[("2026-01-01", None)]) == [("validity_uncited", None)] and by[("2026-01-01", None)]["validity"]["untilStatus"] == "unknown"
    assert codes(by[("2026-12-31", "2026-01-01")]) == [("validity_order_invalid", None)]


def test_a_malformed_date_is_a_permanently_rejected_reply_not_a_guess(world):
    w = world
    bad = proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(w, INV)], validity={"from": "2026-13-45", "until": None, "citations": []})
    out = converge(w, "j", [bad])
    assert out["state"] == "stopped" and out["failure"]["code"] == "relation_reply_invalid" and out["calls"][0]["verdict"] == "relation_reply_invalid"
    assert out["relations"] == [] and out["usage"]["replayCalls"] == 1


@pytest.mark.parametrize("declared,known,check,market", [(["KR"], ["US"], "conflict", "domestic"), (["US"], ["US"], "pass", "international"),
                                                         (["US", "KR"], ["US"], "conflict", "international"), ([], ["US"], "unknown", "unknown"),
                                                         (["KR"], [], "unverified", "domestic")])
def test_country_and_context_checks_are_explicit(tmp_path, declared, known, check, market):
    w = build_world(tmp_path / "owned", tuple(known))
    out = converge(w, "j", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], countries=declared)])
    r = out["relations"][0]
    assert r["context"] == {"market": market, "check": check, "knownCountries": sorted(known),
                            "normalizationVersion": "zoop-country-context-1", "rawGeography": sorted(known), "unresolvedGeography": []}
    assert r["eligibility"]["status"] == ("hold" if check == "conflict" else "eligible")
    assert (("country_context_conflict", None) in codes(r)) == (check == "conflict")
    if check != "conflict":
        assert ("context" in [x["claimId"] for x in r["claims"]]) == bool(declared)


# ---------------------------------------------------------------- citations --------------------------------------------

def test_exact_korean_emoji_entity_quotes_pass_and_forged_offset_unit_or_separator_spans_are_rejected(world):
    w = world
    text = w.art["main"].body
    assert len(SUP) == 31 and len(SUP.encode("utf-8")) != len(SUP) and len(SUP.encode("utf-16-le")) // 2 != len(SUP)
    utf16 = {**c(w, SUP), "start": len(text[:c(w, SUP)["start"]].encode("utf-16-le")) // 2}
    utf16["end"] = utf16["start"] + len(SUP.encode("utf-16-le")) // 2
    byte = {**c(w, SUP), "start": len(text[:c(w, SUP)["start"]].encode()), "end": len(text[:c(w, SUP)["start"]].encode()) + len(SUP.encode())}
    props = [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="exact"),
             proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP[:SUP.index(" &")])], product="substring"),
             proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [utf16], product="utf16"),
             proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [byte], product="bytes"),
             proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [rs.cross_separator(w)], product="separator"),
             proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [forged_span(w, "main", SUP)], product="shifted"),
             proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [{**c(w, SUP), "documentVersion": "f" * 64}], product="wrong-version"),
             proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [{**c(w, SUP), "documentId": "doc-forged"}], product="wrong-document")]
    out = converge(w, "j", props)
    by = {r["productScope"]: r for r in out["relations"]}
    exact = by["exact"]["citations"][0]
    assert by["exact"]["eligibility"]["status"] == "eligible" and exact["quote"] == SUP and exact["end"] - exact["start"] == len(SUP) and exact["offsetUnit"] == "unicode_code_point"
    assert "😀" in exact["quote"] and "&" in exact["quote"] and exact["rawLocatorIds"] and exact["sourceSegments"]
    assert all(by[n]["eligibility"]["status"] == "reject" and by[n]["citations"][0]["error"] for n in set(by) - {"exact", "substring"})
    assert by["substring"]["eligibility"]["status"] == "eligible" and by["substring"]["citations"][0]["quote"] == SUP[:SUP.index(" &")]
    assert by["separator"]["citations"][0]["error"] == "raw_locator_mismatch" and by["shifted"]["citations"][0]["error"] == "quote_mismatch"
    assert by["wrong-version"]["citations"][0]["error"] == by["wrong-document"]["citations"][0]["error"] == "citation_document_unbound"
    assert by["utf16"]["citations"][0]["error"] == by["bytes"]["citations"][0]["error"] == "quote_mismatch"
    assert all(by[n]["history"][0]["verifier"] == "not-called" for n in by if n not in {"exact", "substring"})


# ---------------------------------------------------------------- independent verification --------------------------------

def test_malformed_or_forged_verifier_replies_reject_that_candidate_permanently_without_retry(world):
    w = world
    props = [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product=name) for name in ("ok", "unbound", "missing", "unknown", "dup", "shape", "rev", "support")]

    def verify(r):
        good = verifier_reply(r)
        claims = good["claims"]
        name = r["productScope"]
        if name == "unbound":
            return {**good, "claims": [{**claims[0], "quoteIds": ["ev-forged"]}, *claims[1:]]}
        if name == "missing":
            return {**good, "claims": claims[:-1]}
        if name == "unknown":
            return {**good, "claims": [*claims, {"claimId": "unrequested", "verdict": "supported", "quoteIds": claims[0]["quoteIds"]}]}
        if name == "dup":
            return {**good, "claims": [*claims, claims[0]]}
        if name == "shape":
            return {"schemaVersion": "zoop-relation-verify-response-1", "verifierVersion": "zoop-relation-verifier-1", "claims": "no"}
        if name == "rev":
            return {**good, "claims": [{**claims[0], "verdict": "reversed"}, *claims[1:]]}
        if name == "support":
            return {**good, "claims": [{**claims[0], "quoteIds": []}, *claims[1:]]}
        return good

    out = converge(w, "j", props, verify=verify)
    by = {r["productScope"]: r for r in out["relations"]}
    assert by["ok"]["eligibility"]["status"] == "eligible" and out["state"] == "ready"
    expected = {"unbound": "verifier_quote_unbound", "missing": "verifier_claim_missing", "unknown": "verifier_claim_unknown", "dup": "verifier_claim_duplicate",
                "shape": "verifier_reply_invalid", "rev": "verifier_verdict_invalid", "support": "verifier_support_uncited"}
    for name, code in expected.items():
        assert by[name]["eligibility"]["status"] == "reject" and by[name]["eligibility"]["reasons"] == [{"code": "verification_reply_invalid", "detail": code}], name
    invalid = sorted(call["verdict"] for call in out["calls"] if call["verdict"])
    assert invalid == sorted(expected.values())
    again = w.kit.rel_job("resume", w.kit.rsel("j"))
    assert again["usage"]["replayCalls"] == out["usage"]["replayCalls"] and again["calls"] == out["calls"]


def test_generator_reply_that_violates_its_contract_is_permanent_and_a_better_fixture_is_ignored(world):
    w = world
    digest_ = stop_at_generation(w)
    bad = {"schemaVersion": "zoop-relation-response-1", "producerVersion": rs.PRODUCER, "relations": [{"type": "SUPPLIES"}]}
    first = w.kit.rel_job("run", w.kit.rsubmit("gen", w.s2), replay=w.kit.fixture("producer", "bad", [("relation", digest_, bad)]))
    assert first["state"] == "stopped" and first["failure"]["code"] == "relation_reply_invalid" and first["calls"][0]["verdict"] == "relation_reply_invalid"
    better = w.kit.fixture("producer", "better", [("relation", digest_, relation_reply([proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)])]))])
    second = w.kit.rel_job("resume", w.kit.rsel("gen"), replay=better)
    assert second["state"] == "stopped" and second["failure"]["code"] == "relation_reply_invalid" and second["usage"]["replayCalls"] == 1 and second["relations"] == []


@pytest.mark.parametrize("variant,code", [("unknown-field", "relation_reply_invalid"), ("bad-schema", "relation_reply_invalid"), ("too-many", "relation_reply_invalid"),
                                          ("too-many-citations", "relation_reply_invalid"), ("bad-country", "relation_reply_invalid"), ("bad-kind", "relation_reply_invalid")])
def test_explicit_bounds_and_closed_shapes_reject_the_whole_generator_reply(world, variant, code):
    w = world
    base = proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)])
    reply = {"unknown-field": relation_reply([{**base, "extra": 1}]), "bad-schema": {**relation_reply([base]), "schemaVersion": "other"},
             "too-many": relation_reply([base] * 101), "too-many-citations": relation_reply([{**base, "citations": [c(w, SUP)] * 21}]),
             "bad-country": relation_reply([{**base, "countries": ["korea"]}]),
             "bad-kind": relation_reply([{**base, "subject": {"kind": "industry", "ref": "x"}}])}[variant]
    out = converge(w, "j", [], seed=([("relation", stop_at_generation(w, "probe"), reply)], []))
    assert out["state"] == "stopped" and out["failure"]["code"] == code and out["relations"] == []


def test_verifier_receives_only_fixed_facts_and_quotes_so_generator_wording_cannot_change_it(world):
    w = world
    out = converge(w, "j", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="p", reason="이 관계는 틀림없다")])
    r = out["relations"][0]
    request = rules.verifier_request(r, INITIAL_ATTEMPT)
    assert set(request) == {"schemaVersion", "stage", "verifierVersion", "policyVersion", "attempt", "relation", "quotes", "claims"}
    assert digest(request) == digest(rules.verifier_request({**r, "generatorReasons": ["전혀 다른 사유"], "relationCandidateId": "rc-x", "proposalCount": 9}, INITIAL_ATTEMPT))
    assert [x["quoteId"] for x in request["quotes"]] == sorted(x["quoteId"] for x in request["quotes"])
    verifier_calls = [x for x in out["calls"] if x["stage"] == "verify-relation"]
    assert verifier_calls[0]["requestDigest"] == digest(request) and verifier_calls[0]["fixtureHash"] != next(x for x in out["calls"] if x["stage"] == "relation")["fixtureHash"]


# ---------------------------------------------------------------- impact -----------------------------------------------

def impact_cases(w):
    base = [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="base")]
    return base, {"good": c(w, GOOD), "bad": c(w, BAD)}


def run_impact(w, job, items, effects=None, **kw):
    base, _ = impact_cases(w)
    return converge(w, job, base, impacts=lambda r: items, effects=effects, **kw)


def only(out):
    return out["relations"][0], out["relations"][0]["impact"]["candidates"]


def test_both_sided_cited_evidence_is_mixed_and_label_comes_from_the_verifier_mapping(world):
    w = world
    _, cites = impact_cases(w)
    out = run_impact(w, "mixed", [impact_item("SYNTH-1", "positive", [cites["good"]], [cites["bad"]])], effects=lambda i: {GOOD: "positive", BAD: "negative"})
    relation, (impact,) = only(out)
    assert relation["eligibility"]["status"] == "eligible" and impact["verdict"]["label"] == "mixed" and impact["verdict"]["status"] == "verified"
    assert impact["proposal"]["direction"] == "positive" and impact["agreement"] is False
    assert len(impact["verdict"]["mapped"]["positive"]) == len(impact["verdict"]["mapped"]["negative"]) == 1 and impact["approved"] is False
    assert relation["impact"]["labelNote"].startswith("textual impact direction") and "price" in relation["impact"]["labelNote"]
    # The producer's own label is only compared, never trusted: the verifier maps both quotes positive -> positive.
    out = run_impact(w, "positive", [impact_item("SYNTH-1", "mixed", [cites["good"]], [cites["bad"]])], effects=lambda i: {GOOD: "positive", BAD: "positive"})
    assert only(out)[1][0]["verdict"]["label"] == "positive" and only(out)[1][0]["agreement"] is False
    out = run_impact(w, "negative", [impact_item("SYNTH-1", "negative", [cites["bad"]], [])], effects=lambda i: {BAD: "negative"})
    assert only(out)[1][0]["verdict"]["label"] == "negative" and only(out)[1][0]["agreement"] is True


def test_insufficient_direction_is_undetermined_without_invalidating_the_verified_relation(world):
    w = world
    _, cites = impact_cases(w)
    cases = {"neutral": ([impact_item("SYNTH-1", "negative", [cites["bad"]], [])], lambda i: {}, "direction_insufficient", "called"),
             "target-insufficient": ([impact_item("SYNTH-1", "positive", [cites["good"]], [])], lambda i: impact_verifier_reply(i, {GOOD: "positive"}, target="insufficient"), "impact_target_insufficient", "called"),
             "no-evidence": ([impact_item("SYNTH-1", "positive", [], [], "근거 없음")], None, "no_cited_evidence", "not-called")}
    for name, (items, effects, reason, verifier) in cases.items():
        out = run_impact(w, name, items, effects=effects)
        relation, (impact,) = only(out)
        assert relation["eligibility"]["status"] == "eligible" and relation["impact"]["status"] == "complete", name
        assert impact["verdict"]["label"] == "undetermined" and impact["verdict"]["status"] == "verified" and impact["verdict"]["reasons"][0]["code"] == reason and impact["verdict"]["verifier"] == verifier
        assert (out["counts"]["eligibility"]["eligible"], out["counts"]["impactLabels"]["undetermined"]) == (1, 1)
    assert sum(x["stage"] == "verify-impact" for x in run_impact(w, "no-evidence", cases["no-evidence"][0])["calls"]) == 0


def test_one_uncertain_quote_effect_gives_no_label_even_beside_a_confident_positive_quote(world):
    w = world
    _, cites = impact_cases(w)
    out = run_impact(w, "uncertain", [impact_item("SYNTH-1", "positive", [cites["good"]], [cites["bad"]])], effects=lambda i: impact_verifier_reply(i, {GOOD: "positive", BAD: "uncertain"}))
    relation, (impact,) = only(out)
    verdict = impact["verdict"]
    assert relation["eligibility"]["status"] == "eligible" and verdict["status"] == "verified" and verdict["label"] == "undetermined"
    assert [r["code"] for r in verdict["reasons"]] == ["quote_effect_uncertain"] and len(verdict["mapped"]["uncertain"]) == 1 and len(verdict["mapped"]["positive"]) == 1
    assert out["counts"]["impactLabels"]["positive"] == 0
    # All-confident answers keep their exact earlier shape (no `uncertain` key) and label.
    confident = only(run_impact(w, "confident", [impact_item("SYNTH-1", "positive", [cites["good"]], [cites["bad"]])], effects=lambda i: {GOOD: "positive", BAD: "negative"}))[1][0]["verdict"]
    assert confident["label"] == "mixed" and set(confident["mapped"]) == {"positive", "negative", "neutral"}


def test_wrong_impact_target_fabricated_citation_or_contradicted_target_cannot_pass(world):
    w = world
    _, cites = impact_cases(w)
    other = {**world_cite(w, "b", QB)}
    cases = {"wrong-company": [impact_item("SYNTH-2", "positive", [cites["good"]], [])],
             "fabricated": [impact_item("SYNTH-1", "positive", [forged_span(w, "main", GOOD)], [])],
             "unbound-document": [impact_item("SYNTH-1", "positive", [other], [])],
             "one-fabricated-one-real": [impact_item("SYNTH-1", "mixed", [cites["good"]], [{**cites["bad"], "documentId": "doc-forged"}])]}
    expected = {"wrong-company": "impact_target_invalid", "fabricated": "citation_invalid", "unbound-document": "citation_invalid", "one-fabricated-one-real": "citation_invalid"}
    for name, items in cases.items():
        out = run_impact(w, name, items, effects=lambda i: {GOOD: "positive"})
        relation, (impact,) = only(out)
        assert impact["verdict"]["status"] == "reject" and impact["verdict"]["label"] is None and impact["verdict"]["reasons"][0]["code"] == expected[name], name
        assert relation["eligibility"]["status"] == "eligible" and impact["verdict"]["verifier"] == "not-called"
        assert all(x["stage"] != "verify-impact" for x in out["calls"])
    out = run_impact(w, "contradicted", [impact_item("SYNTH-1", "positive", [cites["good"]], [])], effects=lambda i: impact_verifier_reply(i, {GOOD: "positive"}, target="contradicted"))
    relation, (impact,) = only(out)
    assert impact["verdict"]["status"] == "reject" and impact["verdict"]["reasons"] == [{"code": "impact_target_contradicted"}] and relation["eligibility"]["status"] == "eligible"


def test_impact_producer_and_verifier_faults_are_recorded_but_never_touch_the_relation(world):
    w = world
    _, cites = impact_cases(w)
    twice = impact_reply([impact_item("SYNTH-1", "positive", [cites["good"]], []), impact_item("SYNTH-1", "negative", [cites["bad"]], [])])
    out = run_impact(w, "dup", twice)
    relation = out["relations"][0]
    assert relation["eligibility"]["status"] == "eligible" and relation["impact"]["status"] == "producer-reply-invalid" and relation["impact"]["candidates"] == []
    assert out["state"] == "ready" and [x["verdict"] for x in out["calls"] if x["stage"] == "impact"] == ["impact_duplicate_target"]
    broken = lambda i: {"schemaVersion": "zoop-impact-verify-response-1", "verifierVersion": "zoop-impact-verifier-1", "target": "supported", "quotes": []}  # noqa: E731
    out = run_impact(w, "broken", [impact_item("SYNTH-1", "positive", [cites["good"]], [])], effects=broken)
    relation, (impact,) = only(out)
    assert relation["eligibility"]["status"] == "eligible" and impact["verdict"]["status"] == "reject"
    assert impact["verdict"]["reasons"] == [{"code": "verification_reply_invalid", "detail": "verifier_quote_missing"}]
    forged = lambda i: {**impact_verifier_reply(i, {GOOD: "positive"}), "quotes": [{"quoteId": "ev-forged", "effect": "positive"}]}  # noqa: E731
    out = run_impact(w, "forged", [impact_item("SYNTH-1", "positive", [cites["good"]], [])], effects=forged)
    assert only(out)[1][0]["verdict"]["reasons"][0]["detail"] == "verifier_quote_unbound"


def test_two_company_impacts_are_independent_and_sorted(world):
    w = world
    _, cites = impact_cases(w)
    out = run_impact(w, "two", [impact_item("SYNTH-3", "negative", [cites["bad"]], []), impact_item("SYNTH-1", "positive", [cites["good"]], [])],
                     effects=lambda i: {GOOD: "positive", BAD: "negative"})
    relation, impacts = only(out)
    assert [i["impactedCompanyId"] for i in impacts] == ["SYNTH-1", "SYNTH-3"] and [i["verdict"]["label"] for i in impacts] == ["positive", "negative"]
    assert len({i["impactCandidateId"] for i in impacts}) == 2 and all(i["impactCandidateId"].startswith("ic-") and i["relationCandidateId"] == relation["relationCandidateId"] for i in impacts)


# ---------------------------------------------------------------- HOLD review -> final human approval -----------------

def scope_hold(w, job="j", extra=()):
    props = [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="scope-hold"), *extra]
    return converge(w, job, props, verify=lambda r: {"scope": "insufficient"} if r["productScope"] == "scope-hold" else None)


def test_admin_allow_is_the_final_approval_and_calls_nothing(world):
    w = world
    out = scope_hold(w)
    held = find(out, "SUPPLIES", productScope="scope-hold")
    assert held["eligibility"] == {"status": "hold", "reasons": [{"code": "claim_insufficient", "at": "scope"}], "revision": 1, "reviewPending": False, "approvalBasis": None}
    with pytest.raises(ExtractionFailure, match="review_revision_conflict"):
        w.kit.rel_job("review", review(w, "j", held, revision=7))
    allowed = w.kit.rel_job("review", review(w, "j", held))
    item = find(allowed, "SUPPLIES", productScope="scope-hold")
    assert item["eligibility"] == {"status": "eligible", "reasons": [], "revision": 2, "reviewPending": False,
                                   "approvalBasis": {"kind": "operator-final-approval", "revision": 2, "reviewer": "operator-a", "decidedAt": item["history"][-1]["createdAt"]}}
    assert item["history"][-1] | {"createdAt": None, "seq": None} == {"kind": "review", "seq": None, "createdAt": None, "decision": "allow", "reviewer": "operator-a",
                                                                       "note": "authored review", "expectedRevision": 1, "effect": "approved"}
    assert item["history"][0] == held["history"][0] and item["approved"] is False and item["impact"] == {"status": "not-applicable", "labelNote": item["impact"]["labelNote"], "candidates": []}
    assert allowed["counts"]["eligibility"] == {"pending": 0, "eligible": 1, "hold": 0, "reject": 0} and allowed["counts"]["impactCandidates"] == 0
    assert allowed["calls"] == out["calls"] and allowed["usage"] == out["usage"]  # no model, verifier or impact call
    assert w.kit.rel_job("resume", w.kit.rsel("j"))["calls"] == out["calls"]
    for decision in ("allow", "reject"):  # a decided relation is not a HOLD any more: no second decision, no reversal
        with pytest.raises(ExtractionFailure, match="review_target_not_hold"):
            w.kit.rel_job("review", review(w, "j", item, decision))
    with pytest.raises(ExtractionFailure, match="review_revision_conflict"):
        w.kit.rel_job("review", review(w, "j", held, "reject"))  # the same-revision race: the first decision won


def test_automatic_eligibility_has_the_automatic_basis_with_no_reviewer(world):
    w = world
    out = converge(w, "j", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="p")])
    item = out["relations"][0]
    assert item["eligibility"]["status"] == "eligible" and item["eligibility"]["approvalBasis"] == {
        "kind": "automatic-verifier", "revision": 1, "reviewer": None, "decidedAt": item["history"][0]["createdAt"]}


def test_a_human_approval_never_starts_impact_while_the_automatic_relation_still_does(world):
    w = world
    fine = proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="fine")
    producer, verifier = scope_hold(w, "ref", (fine,))["fixtures"]
    partial = w.kit.fixture("producer", "partial", [r for r in producer if r[0] != "impact"])
    verifier_file = w.kit.fixture("verifier", "vv", verifier)
    stopped = w.kit.rel_job("run", w.kit.rsubmit("k", w.s2), replay=partial, verifier=verifier_file)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "producer_replay_missing"
    w.kit.rel_job("review", review(w, "k", find(stopped, "SUPPLIES", productScope="scope-hold")))
    done = w.kit.rel_job("resume", w.kit.rsel("k"), replay=w.kit.fixture("producer", "whole", producer), verifier=verifier_file)
    assert done["state"] == "ready" and [x["stage"] for x in done["calls"]].count("impact") == 1
    assert find(done, "SUPPLIES", productScope="scope-hold")["impact"]["status"] == "not-applicable" and find(done, "SUPPLIES", productScope="fine")["impact"]["status"] == "complete"


def test_the_deterministic_gate_cannot_be_overridden_by_a_human_allow(world):
    w = world
    out = scope_hold(w, extra=(proposal("SUPPLIES", co("SYNTH-9"), co("SYNTH-1"), [c(w, SUP)], product="unknown"),
                                proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [forged_span(w, "main", SUP)], product="forged"),
                                proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="fine")))
    unknown, forged, fine = (find(out, "SUPPLIES", productScope=name) for name in ("unknown", "forged", "fine"))
    with pytest.raises(ExtractionFailure, match="review_candidate_ineligible") as info:
        w.kit.rel_job("review", review(w, "j", unknown))
    assert info.value.detail == {"reasons": [{"code": "target_unknown", "at": "subject"}]}
    assert forged["eligibility"]["status"] == "reject"
    with pytest.raises(ExtractionFailure, match="review_target_not_hold"):
        w.kit.rel_job("review", review(w, "j", forged))
    with pytest.raises(ExtractionFailure, match="review_target_not_hold"):
        w.kit.rel_job("review", review(w, "j", fine))
    assert find(w.kit.rel_job("inspect", w.kit.rsel("j")), "SUPPLIES", productScope="unknown")["eligibility"]["revision"] == 1  # nothing was appended


def test_a_candidate_that_no_longer_matches_its_deterministic_precheck_is_not_approvable(world, monkeypatch):
    w = world
    held = find(scope_hold(w), "SUPPLIES", productScope="scope-hold")
    original = rules.reevaluate
    monkeypatch.setattr(rules, "reevaluate", lambda stored, view: {**original(stored, view), "countries": ["XX"]})
    with pytest.raises(ExtractionFailure, match="review_candidate_ineligible") as info:
        w.kit.rel_job("review", review(w, "j", held))
    assert info.value.detail == {"reasons": [{"code": "candidate_changed"}]}


def test_final_approval_needs_current_rights_and_appends_nothing_without_them(world):
    w = world
    held = find(scope_hold(w), "SUPPLIES", productScope="scope-hold")
    grant = w.kit.registry["sources"][0]["grant"]
    grant["enabled"] = False
    w.kit.save_registry()
    with pytest.raises(ExtractionFailure, match="source_unauthorized"):
        w.kit.rel_job("review", review(w, "j", held))
    grant["enabled"] = True
    w.kit.save_registry()
    db = database(w)
    assert db.execute("SELECT COUNT(*) FROM relation_events").fetchone()[0] == 1
    db.close()
    assert find(w.kit.rel_job("review", review(w, "j", held)), "SUPPLIES", productScope="scope-hold")["eligibility"]["status"] == "eligible"


def test_allow_is_refused_while_a_call_for_that_relation_is_unknown_but_a_refused_attempt_does_not_block(world):
    w = world
    held = find(scope_hold(w), "SUPPLIES", productScope="scope-hold")
    db = database(w)
    db.execute("INSERT INTO calls(attempt_id,job_id,stage,ref,request_digest,fixture_hash,state,started_at) VALUES(?,?,?,?,?,?,'started',?)",
               ("attempt-unknown", "j", "verify-relation", held["relationCandidateId"] + "|initial|9", "a" * 64, "b" * 64, "2026-10-13T00:00:00+00:00"))
    db.commit()
    with pytest.raises(ExtractionFailure, match="review_call_in_flight"):
        w.kit.rel_job("review", review(w, "j", held))
    db.execute("INSERT INTO stages VALUES(?,?,?,?,?)", ("j", "refusal", "attempt-unknown", json.dumps({"code": "live_budget_exhausted_usd"}), "2026-10-13T00:00:01+00:00"))
    db.commit()
    db.close()
    assert find(w.kit.rel_job("review", review(w, "j", held)), "SUPPLIES", productScope="scope-hold")["eligibility"]["status"] == "eligible"


def test_admin_reject_only_excludes_and_deterministic_holds_stay_held(world):
    w = world
    out = scope_hold(w, extra=(proposal("SUPPLIES", co("SYNTH-9"), co("SYNTH-1"), [c(w, SUP)], product="unknown"),
                                proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="fine")))
    held, fine = (find(out, "SUPPLIES", productScope=name) for name in ("scope-hold", "fine"))
    with pytest.raises(ExtractionFailure, match="review_target_not_hold"):
        w.kit.rel_job("review", review(w, "j", fine))
    rejected = find(w.kit.rel_job("review", review(w, "j", held, "reject")), "SUPPLIES", productScope="scope-hold")
    assert rejected["eligibility"] == {"status": "reject", "reasons": [{"code": "admin_rejected"}], "revision": 2, "reviewPending": False, "approvalBasis": None}
    assert rejected["history"][0]["eligibility"] == "hold" and rejected["history"][-1]["effect"] == "excluded"
    with pytest.raises(ExtractionFailure, match="review_target_not_hold"):
        w.kit.rel_job("review", review(w, "j", rejected))
    with pytest.raises(ExtractionFailure, match="review_target_not_hold"):
        w.kit.rel_job("review", review(w, "j", rejected, "allow"))  # a final reject is never reversed


# ---------------------------------------------------------------- fixtures / upstream / rights -------------------------

def test_the_whole_fixture_is_validated_before_any_call_is_reserved(world):
    w = world
    d = stop_at_generation(w)
    good = relation_reply([])
    duplicate = w.kit.fixture("producer", "dup", [("relation", d, good), ("relation", d, good)])
    with pytest.raises(ExtractionFailure, match="relation_replay_invalid"):
        w.kit.rel_job("run", w.kit.rsubmit("gen", w.s2), replay=duplicate)
    with pytest.raises(ExtractionFailure, match="relation_replay_role_conflict"):
        w.kit.rel_job("run", w.kit.rsubmit("gen", w.s2), replay=w.kit.fixture("verifier", "as-producer", [("verify-relation", d, good)]))
    raw = json.loads(w.kit.fixture("producer", "stage", [("relation", d, good)]).read_text())
    raw["records"][0]["stage"] = "verify-relation"
    broken = w.kit.root / "stage.json"
    broken.write_text(json.dumps(raw))
    with pytest.raises(ExtractionFailure, match="relation_replay_invalid"):
        w.kit.rel_job("run", w.kit.rsubmit("gen", w.s2), replay=broken)
    raw["records"][0]["stage"] = "relation"
    raw["synthetic"] = False
    actual = w.kit.root / "actual.json"
    actual.write_text(json.dumps(raw))
    refused = w.kit.rel_job("run", w.kit.rsubmit("gen", w.s2), replay=actual)
    assert refused["state"] == "stopped" and refused["failure"]["code"] == "replay_provenance_conflict" and refused["calls"] == []
    raw["extra"] = 1
    raw["synthetic"] = True
    extra = w.kit.root / "extra.json"
    extra.write_text(json.dumps(raw))
    with pytest.raises(ExtractionFailure, match="relation_replay_invalid"):
        w.kit.rel_job("run", w.kit.rsubmit("gen", w.s2), replay=extra)
    assert database(w).execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0


def test_forged_or_unusable_upstream_is_refused_before_any_job_exists(world):
    w = world
    request = w.kit.rsubmit("forged", w.s2)
    with pytest.raises(ExtractionFailure, match="upstream_input_mismatch"):
        w.kit.rel_job("run", {**request, "upstream": {"jobId": "s2-job", "inputDigest": "0" * 64}})
    with pytest.raises(ExtractionFailure, match="job_not_found"):
        w.kit.rel_job("run", {**request, "upstream": {"jobId": "missing-s2", "inputDigest": w.s2["inputDigest"]}})
    with pytest.raises(ExtractionFailure, match="provenance_conflict"):
        w.kit.rel_job("run", w.kit.rsubmit("forged", w.s2, source_kind="actual"))
    pending = w.kit.job("run", w.kit.submit("s2-pending", w.refs["main"], [w.snapshot], topic=True), replay=w.s2_replay)
    assert pending["state"] == "stopped"
    with pytest.raises(ExtractionFailure, match="upstream_not_ready"):
        w.kit.rel_job("run", {**request, "upstream": {"jobId": "s2-pending", "inputDigest": pending["inputDigest"]}})
    for forged in ({"relations": []}, {"eventCandidates": []}, {"upstream": {**request["upstream"], "candidates": []}}, {"approved": True}):
        with pytest.raises(ValidationError):
            Submit.model_validate({**request, **forged})
    assert database(w).execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    # The input digest pins the exact S2 version; same job id with a different upstream is a conflict, never a silent rebind.
    ready = converge(w, "kept", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)])])
    with pytest.raises(ExtractionFailure, match="job_input_conflict"):
        w.kit.rel_job("run", {**w.kit.rsubmit("kept", pending), "upstream": {"jobId": "s2-pending", "inputDigest": pending["inputDigest"]}})
    assert ready["state"] == "ready"


def test_a_legacy_s2_upstream_is_refused_by_its_owner_before_any_s3_job_exists(world):
    w = world
    legacy = copy_as_legacy(w.kit.root, "s2-job", "s2-legacy")
    with pytest.raises(ExtractionFailure, match="analysis_contract_changed"):
        w.kit.rel_job("run", w.kit.rsubmit("from-legacy", {"jobId": "s2-legacy", "inputDigest": legacy["input_digest"]}))
    assert database(w).execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert w.kit.job("inspect", w.kit.job_selector("s2-job"))["delivery"]["status"] == "current"


def test_revoked_or_changed_rights_withhold_delivery_and_stop_resume_without_calls_then_recover(world):
    w = world
    props = [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="p")]
    ready = converge(w, "done", props)
    assert ready["delivery"]["status"] == "current"
    w.kit.registry["sources"][0]["grant"]["enabled"] = False
    w.kit.save_registry()
    withheld = w.kit.rel_job("inspect", w.kit.rsel("done"))
    text = json.dumps(withheld, ensure_ascii=False)
    assert withheld["delivery"] == {"status": "withheld", "code": "source_unauthorized"} and SUP not in text and "relations" not in withheld and withheld["state"] == "ready"
    with pytest.raises(ExtractionFailure, match="source_unauthorized"):
        w.kit.rel_job("review", {**review(w, "done", ready["relations"][0]), "relationCandidateId": ready["relations"][0]["relationCandidateId"]})
    w.kit.registry["sources"][0]["grant"]["enabled"] = True
    w.kit.registry["sources"][0]["grant"]["revision"] = "rights-2"
    w.kit.save_registry()
    changed = w.kit.rel_job("inspect", w.kit.rsel("done"))
    assert changed["delivery"] == {"status": "withheld", "code": "grant_revision_changed"} and SUP not in json.dumps(changed, ensure_ascii=False)
    w.kit.registry["sources"][0]["grant"]["revision"] = "rights-1"
    w.kit.save_registry()
    assert w.kit.rel_job("inspect", w.kit.rsel("done"))["delivery"]["status"] == "current"
    # Mid-flight: the job stops on lost rights without a single new call and continues after current rights return.
    d = stop_at_generation(w, "mid")
    producer = w.kit.fixture("producer", "mid", [("relation", d, relation_reply(props))])
    first = w.kit.rel_job("run", w.kit.rsubmit("mid", w.s2), replay=producer)
    assert first["failure"]["code"] == "verifier_replay_required"
    calls_before = first["calls"]
    w.kit.registry["sources"][0]["grant"]["enabled"] = False
    w.kit.save_registry()
    stopped = w.kit.rel_job("resume", w.kit.rsel("mid"), replay=producer)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "source_unauthorized" and stopped["delivery"]["status"] == "withheld"
    w.kit.registry["sources"][0]["grant"]["enabled"] = True
    w.kit.save_registry()
    resumed = w.kit.rel_job("resume", w.kit.rsel("mid"), replay=producer)
    assert resumed["failure"]["code"] == "verifier_replay_required" and resumed["calls"] == calls_before


def test_rights_lost_after_a_receipt_leave_a_valid_receipt_and_commit_nothing_until_rights_return(world, monkeypatch):
    from zoop_ai_pipeline.relation import Engine
    w = world
    props = [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="p")]
    digest_ = stop_at_generation(w, "probe")
    producer = w.kit.fixture("producer", "p", [("relation", digest_, relation_reply(props))])
    original = Engine._receive

    def revoke_after_receipt(self, attempt, raw):
        original(self, attempt, raw)
        w.kit.registry["sources"][0]["grant"]["enabled"] = False
        w.kit.save_registry()

    monkeypatch.setattr(Engine, "_receive", revoke_after_receipt)
    stopped = w.kit.rel_job("run", w.kit.rsubmit("late", w.s2), replay=producer)
    monkeypatch.setattr(Engine, "_receive", original)
    # This process holds the registry it started with: any change fails closed as registry_changed (a fresh process reports source_unauthorized).
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "registry_changed" and stopped["delivery"]["status"] == "withheld"
    db = database(w)
    assert db.execute("SELECT state,verdict FROM calls").fetchall()[0]["state"] == "received" and db.execute("SELECT COUNT(*) FROM relation_candidates").fetchone()[0] == 0
    # Only the first-dispatch markers (one per job that ever ran: `probe` and `late`) exist: no stage, candidate or event was materialized after the rights change.
    assert db.execute("SELECT COUNT(*) FROM stages WHERE stage!='dispatch'").fetchone()[0] == 0 and db.execute("SELECT COUNT(*) FROM relation_events").fetchone()[0] == 0
    db.close()
    w.kit.registry["sources"][0]["grant"]["enabled"] = True
    w.kit.save_registry()
    resumed = w.kit.rel_job("resume", w.kit.rsel("late"))
    assert resumed["stages"]["relation"]["relations"] == 1 and resumed["usage"]["replayCalls"] == 1 and resumed["failure"]["code"] == "verifier_replay_required"


def test_registry_removal_or_expiry_also_denies_the_relation_job(world):
    w = world
    ready = converge(w, "done", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)])])
    for mutate in (lambda g: g.update(expiresAt="2000-01-01T00:00:00+00:00"), lambda g: g.update(rights="denied"), lambda g: g.update(allowedOperations=["read", "store"])):
        grant = w.kit.registry["sources"][0]["grant"]
        saved = dict(grant)
        mutate(grant)
        w.kit.save_registry()
        assert w.kit.rel_job("inspect", w.kit.rsel("done"))["delivery"]["status"] == "withheld"
        grant.clear()
        grant.update(saved)
        w.kit.save_registry()
    assert ready["delivery"]["status"] == "current" and w.kit.rel_job("inspect", w.kit.rsel("done"))["delivery"]["status"] == "current"


def test_cancel_fences_a_stopped_job_and_blocks_review(world):
    w = world
    d = stop_at_generation(w, "c")
    producer = w.kit.fixture("producer", "c", [("relation", d, relation_reply([proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)])]))])
    first = w.kit.rel_job("run", w.kit.rsubmit("c", w.s2), replay=producer)
    cancelled = w.kit.rel_job("cancel", w.kit.rsel("c"))
    assert cancelled["state"] == "cancelled" and cancelled["delivery"] == {"status": "withheld", "code": "job_cancelled"} and "relations" not in cancelled
    again = w.kit.rel_job("resume", w.kit.rsel("c"), replay=producer)
    assert again["state"] == "cancelled" and again["calls"] == first["calls"]
    with pytest.raises(ExtractionFailure, match="job_cancelled"):
        w.kit.rel_job("review", {**w.kit.rsel("c"), "relationCandidateId": "rc-" + "0" * 64, "decision": "allow", "reviewer": "r", "note": "n", "expectedRevision": 1})


# ---------------------------------------------------------------- recovery (actual processes) --------------------------

def legacy_request(w, job, held, *, seq=2):
    """A `revalidation-requested` review event exactly as a pre-cutover ledger stored it (history only; nothing writes this any more)."""
    db = database(w)
    db.execute("INSERT INTO relation_events VALUES(?,?,?,?,?,?)", (job, held["relationCandidateId"], seq, "review", json.dumps(
        {"decision": "allow", "reviewer": "operator-a", "note": "legacy request", "expectedRevision": seq - 1, "effect": "revalidation-requested"}), "2026-10-13T00:01:00+00:00"))
    db.commit()
    db.close()


def test_legacy_revalidation_history_is_readable_never_approved_and_takes_a_new_final_decision_at_the_current_revision(world):
    w = world
    held = find(scope_hold(w), "SUPPLIES", productScope="scope-hold")
    legacy_request(w, "j", held)
    before = w.kit.rel_job("inspect", w.kit.rsel("j"))
    stuck = find(before, "SUPPLIES", productScope="scope-hold")
    assert stuck["eligibility"] == {"status": "hold", "reasons": held["eligibility"]["reasons"], "revision": 2, "reviewPending": True, "approvalBasis": None}
    assert stuck["history"][-1]["effect"] == "revalidation-requested" and stuck["approved"] is False
    assert w.kit.rel("revalidate", {**w.kit.rsel("j"), "relationCandidateId": held["relationCandidateId"], "expectedRevision": 2}, expected=2) is None
    with pytest.raises(ExtractionFailure, match="review_revision_conflict"):
        w.kit.rel_job("review", review(w, "j", stuck, revision=1))  # the old intent is never retroactively accepted at an older revision
    ready = w.kit.rel_job("resume", w.kit.rsel("j"))
    assert ready["calls"] == before["calls"] and ready["usage"] == before["usage"] and ready["state"] == "ready"  # a ready job with a legacy request executes nothing
    done = find(w.kit.rel_job("review", review(w, "j", stuck)), "SUPPLIES", productScope="scope-hold")
    assert done["eligibility"] == {"status": "eligible", "reasons": [], "revision": 3, "reviewPending": False,
                                   "approvalBasis": {"kind": "operator-final-approval", "revision": 3, "reviewer": "operator-a", "decidedAt": done["history"][2]["createdAt"]}}
    assert [e.get("effect") for e in done["history"]] == [None, "revalidation-requested", "approved"]


def test_a_legacy_pending_hold_can_still_be_rejected_by_a_new_decision(world):
    w = world
    held = find(scope_hold(w), "SUPPLIES", productScope="scope-hold")
    legacy_request(w, "j", held)
    stuck = find(w.kit.rel_job("inspect", w.kit.rsel("j")), "SUPPLIES", productScope="scope-hold")
    rejected = find(w.kit.rel_job("review", review(w, "j", stuck, "reject")), "SUPPLIES", productScope="scope-hold")
    assert rejected["eligibility"] == {"status": "reject", "reasons": [{"code": "admin_rejected"}], "revision": 3, "reviewPending": False, "approvalBasis": None}


def test_process_death_after_receipt_resumes_without_fixture_or_additional_call_and_unknown_is_never_resent(world):
    w = world
    kit = w.kit
    d = stop_at_generation(w, "probe")
    producer = kit.fixture("producer", "p", [("relation", d, relation_reply([proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="p")]))])
    request = kit.rsubmit("crash", w.s2)
    kit.rel("run", request, replay=producer, crash="receipt:1", expected=75)
    resumed = kit.rel("resume", kit.rsel("crash"))
    assert resumed["failure"]["code"] == "verifier_replay_required" and [x["stage"] for x in resumed["calls"]] == ["relation"] and resumed["usage"]["replayCalls"] == 1
    candidate = resumed["relations"][0]
    verifier = kit.fixture("verifier", "v", [("verify-relation", digest(rules.verifier_request(candidate, INITIAL_ATTEMPT)), verifier_reply(candidate))])
    kit.rel("resume", kit.rsel("crash"), verifier=verifier, crash="receipt:1", expected=75)
    verifier.unlink()
    producer.unlink()
    after = kit.rel("resume", kit.rsel("crash"))
    assert after["relations"][0]["eligibility"]["status"] == "eligible" and after["usage"]["replayCalls"] == 2 and after["failure"]["code"] == "producer_replay_required"
    assert [x["stage"] for x in after["calls"]] == ["relation", "verify-relation"]
    again = kit.rel("resume", kit.rsel("crash"))
    assert again["calls"] == after["calls"] and again["usage"] == after["usage"]
    # A stage-commit boundary also resumes from committed work.
    kit.rel("run", kit.rsubmit("stage", w.s2), replay=kit.fixture("producer", "p2", [("relation", d, relation_reply([]))]), crash="stage:relation", expected=75)
    done = kit.rel("resume", kit.rsel("stage"))
    assert done["state"] == "ready" and done["usage"]["replayCalls"] == 1 and done["relations"] == []
    kit.rel("run", kit.rsubmit("lost", w.s2), replay=kit.fixture("producer", "p3", [("relation", d, relation_reply([]))]), crash="unknown", expected=75)
    lost = kit.rel("resume", kit.rsel("lost"), replay=kit.fixture("producer", "p3", [("relation", d, relation_reply([]))]))
    assert lost["state"] == "reconciling" and lost["resumeMode"] == "reconcile_only" and lost["usage"]["replayCalls"] == 0 and lost["usage"]["startedWithoutReceipt"] == 1
    assert lost["failure"]["code"] == "replay_response_unknown"


def test_receipts_candidates_events_and_verdicts_are_immutable(world):
    w = world
    out = converge(w, "j", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)])], impacts=lambda r: [impact_item("SYNTH-1", "positive", [c(w, GOOD)], [])],
                   effects=lambda i: {GOOD: "positive"})
    db = database(w)
    for sql in ("UPDATE calls SET response='{}'", "UPDATE calls SET request_digest='x'", "DELETE FROM calls", "UPDATE relation_candidates SET payload='{}'",
                "DELETE FROM relation_candidates", "UPDATE relation_events SET payload='{}'", "DELETE FROM relation_events", "UPDATE impact_candidates SET payload='{}'",
                "UPDATE impact_verdicts SET payload='{}'", "DELETE FROM impact_verdicts", "UPDATE stages SET summary='{}'", "UPDATE jobs SET input_digest='x'", "UPDATE jobs SET binding='x'",
                "DELETE FROM jobs", "UPDATE meta SET value='x'"):
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            db.execute(sql)
    db.close()
    assert out["state"] == "ready"


# ---------------------------------------------------------------- isolation ----------------------------------------------

def test_relation_never_writes_upstream_state_and_keeps_candidates_private(world):
    w = world
    before = {name: tree(w.kit.root / name) for name in ("ingestion", "extraction")}
    modes = {name: {p.name: p.stat().st_mode for p in (w.kit.root / name).iterdir()} for name in ("ingestion", "extraction")}
    out = scope_hold(w)
    held = find(out, "SUPPLIES", productScope="scope-hold")
    w.kit.rel_job("review", review(w, "j", held))
    assert {name: tree(w.kit.root / name) for name in ("ingestion", "extraction")} == before
    assert {name: {p.name: p.stat().st_mode for p in (w.kit.root / name).iterdir()} for name in ("ingestion", "extraction")} == modes
    assert sorted(p.name for p in (w.kit.root / "relation").iterdir()) == ["relation.lock", "relation.sqlite3"]
    assert sorted(p.name for p in (w.kit.root / "extraction").iterdir()) == ["extraction.lock", "extraction.sqlite3"]
    assert out["usage"]["providerCalls"] == 0 and out["usage"]["modelCalls"] == 0 and out["usage"]["executionMode"] == "replay"
    relation_ids = {r["relationCandidateId"] for r in out["relations"]}
    assert all(i.startswith("rc-") for i in relation_ids) and relation_ids.isdisjoint({w.evc, w.tp, "event-1", w.refs["main"]["documentId"]})
    assert all(r["approved"] is False and "published" not in r for r in out["relations"])


def test_upstream_read_follows_the_shared_lock_and_never_ignores_a_hot_wal(world):
    from zoop_ai_pipeline.extraction import Store as ExtractionStore
    w = world
    writer = ExtractionStore(w.kit.root / "extraction", w.kit.root / "ingestion")
    try:
        with pytest.raises(ExtractionFailure, match="extraction_busy"):
            w.kit.rel_job("run", w.kit.rsubmit("busy", w.s2))
    finally:
        writer.close()
    wal = w.kit.root / "extraction" / "extraction.sqlite3-wal"
    wal.write_bytes(b"hot")
    try:
        with pytest.raises(ExtractionFailure, match="extraction_recovery_required"):
            w.kit.rel_job("run", w.kit.rsubmit("hot", w.s2))
    finally:
        wal.unlink()
    assert w.kit.rel_job("run", w.kit.rsubmit("busy", w.s2))["failure"]["code"] == "producer_replay_required"


def test_dedicated_ledger_rejects_overlapping_mixed_and_app_roots(world, tmp_path, monkeypatch):
    w = world
    extraction, ingestion = w.kit.root / "extraction", w.kit.root / "ingestion"
    for bad in (extraction, extraction / "relation", ingestion, w.kit.root, w.kit.root / "inputs"):
        with pytest.raises(ExtractionFailure, match="state_namespace_conflict"):
            Store(bad, extraction, ingestion)
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    (mixed / "notes.txt").write_text("x")
    with pytest.raises(ExtractionFailure, match="state_namespace_conflict"):
        Store(mixed, extraction, ingestion)
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    with pytest.raises(ExtractionFailure, match="state_namespace_invalid"):
        Store(link / "ledger", extraction, ingestion)
    for name in ("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"):
        shared = tmp_path / name.lower()
        monkeypatch.setenv(name, str(shared))
        for candidate in (shared, shared / "relation"):
            with pytest.raises(ExtractionFailure, match="state_namespace_conflict"):
                Store(candidate, extraction, ingestion)
        monkeypatch.delenv(name)
    first = Store(tmp_path / "ok", extraction, ingestion)
    try:
        with pytest.raises(ExtractionFailure, match="relation_busy"):
            Store(tmp_path / "ok", extraction, ingestion)
    finally:
        first.close()
    other = Store(tmp_path / "ok", extraction, ingestion)
    other.db.execute("SELECT 1").fetchone()
    other.close()


def test_no_database_pipeline_graph_or_network_modules_are_loaded(world):
    code = ("import sys\nfrom zoop_ai_pipeline import relation, relation_cli\nprint([m for m in sys.modules if m.startswith(('investmate', "
            "'psycopg', 'neo4j', 'zoop_bff', 'zoop_ai.', 'socket', 'httpx', 'requests'))] + (['zoop_ai'] if 'zoop_ai' in sys.modules else []))")
    child = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, cwd=world.kit.root, env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PATH": "/usr/bin:/bin"})
    assert child.returncode == 0 and "investmate" not in child.stdout and "zoop_bff" not in child.stdout and "neo4j" not in child.stdout, child.stderr + child.stdout


def test_wire_is_closed_versioned_and_review_cannot_name_a_publication_decision(world):
    w = world
    base = {**w.kit.rsel("j"), "relationCandidateId": "rc-" + "0" * 64, "expectedRevision": 1}
    for decision in ("eligible", "publish", "approve", "reject ", ""):
        with pytest.raises(ValidationError):
            Review.model_validate({**base, "decision": decision, "reviewer": "r", "note": "n"})
    for bad in ({"schemaVersion": "zoop-relation-s2"}, {"extra": 1}, {"expectedRevision": 0}, {"relationCandidateId": "evc-" + "0" * 64}, {"jobId": "bad id"}):
        with pytest.raises(ValidationError):
            Review.model_validate({**base, "decision": "allow", "reviewer": "r", "note": "n", **bad})
    with pytest.raises(ValidationError):
        Review.model_validate({**base, "decision": "allow", "reviewer": "", "note": "n"})
    process = w.kit.rel("run", {**w.kit.rsubmit("live", w.s2), "provenance": {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}}, expected=2)
    assert process == {"schemaVersion": "zoop-relation-s3", "error": {"code": "provenance_conflict"}}  # a live S3 job needs a live S2 upstream
    forbidden = w.kit.rel("inspect", w.kit.rsel("x"), replay=w.kit.fixture("producer", "x", []), expected=2)
    assert forbidden["error"]["code"] == "fixture_not_allowed"
    assert w.kit.rel("revalidate", {**base}, expected=2) is None  # the command no longer exists
    assert w.kit.rel("inspect", w.kit.rsel("nope"), expected=2)["error"]["code"] == "job_not_found"
    assert w.kit.rel("inspect", {"nonsense": True}, expected=2)["error"]["code"] == "input_or_configuration_invalid"
    assert w.kit.rel("inspect", {**w.kit.rsel("j"), "pad": "x" * 2_000_100}, expected=2)["error"]["code"] == "command_input_limit"


# ---------------------------------------------------------------- submit-only registration ----------------------------

def jobs(w):
    """Every stored job row verbatim (including fence/updated_at), to prove a repeated submit writes nothing."""
    db = database(w)
    try:
        return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY job_id")]
    finally:
        db.close()


def no_execution(monkeypatch):
    """Anything past registration (stage execution or a call reservation) fails the test."""
    def forbidden(*args, **kwargs):
        raise AssertionError("a submit reached execution")

    for name in ("_execute", "_receipted", "_reserve"):
        monkeypatch.setattr(Engine, name, forbidden)


def supplies(w):
    return [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(w, SUP)], product="p")]


def authored(w, job):
    """A completed reference job plus the producer/verifier files its authoring loop recorded, for a later resume of another job."""
    reference = converge(w, job, supplies(w))
    assert reference["state"] == "ready"
    return reference, w.kit.fixture("producer", f"{job}-saved-p", reference["fixtures"][0]), w.kit.fixture("verifier", f"{job}-saved-v", reference["fixtures"][1])


def test_submit_needs_a_ready_current_upstream_and_writes_no_job_otherwise(world):
    w = world
    pending = w.kit.job("run", w.kit.submit("s2-pending", w.refs["main"], [w.snapshot], topic=True), replay=w.s2_replay)
    assert pending["state"] == "stopped"
    early = {**w.kit.rsubmit("early", w.s2), "upstream": {"jobId": "s2-pending", "inputDigest": pending["inputDigest"]}}
    with pytest.raises(ExtractionFailure, match="upstream_not_ready"):
        w.kit.rel_job("submit", early)
    assert w.kit.rel("submit", early, expected=2, forbid_execution=True)["error"]["code"] == "upstream_not_ready"
    with pytest.raises(ExtractionFailure, match="upstream_input_mismatch"):
        w.kit.rel_job("submit", {**early, "upstream": {"jobId": "s2-job", "inputDigest": "0" * 64}})
    w.kit.registry["sources"][0]["grant"]["enabled"] = False
    w.kit.save_registry()
    with pytest.raises(ExtractionFailure, match="source_unauthorized"):
        w.kit.rel_job("submit", w.kit.rsubmit("early", w.s2))
    assert jobs(w) == []


def test_submit_freezes_without_a_fixture_model_or_call_and_resume_completes_the_job_like_run(world, monkeypatch):
    w = world
    reference, producer, verifier = authored(w, "reference")
    no_execution(monkeypatch)
    queued = w.kit.rel_job("submit", w.kit.rsubmit("late", w.s2))
    assert queued["state"] == "queued" and queued["phase"] == "relation" and queued["resumeMode"] == "resume" and queued["failure"] is None
    assert queued["calls"] == [] and queued["usage"]["replayCalls"] == 0 and queued["relations"] == [] and queued["delivery"]["status"] == "current"
    assert queued["stages"]["relation"] == {"state": "pending"} and queued["binding"] == reference["binding"]
    assert database(w).execute("SELECT COUNT(*) FROM calls WHERE job_id='late'").fetchone()[0] == 0
    monkeypatch.undo()
    done = w.kit.rel_job("resume", w.kit.rsel("late"), replay=producer, verifier=verifier)
    assert done["state"] == "ready" and done["counts"] == reference["counts"] and done["usage"]["replayCalls"] == reference["usage"]["replayCalls"] > 0
    assert [r["relationCandidateId"] for r in done["relations"]] == [r["relationCandidateId"] for r in reference["relations"]]
    assert sorted((x["stage"], x["requestDigest"]) for x in done["calls"]) == sorted((x["stage"], x["requestDigest"]) for x in reference["calls"])


@pytest.mark.parametrize("state", ["queued", "stopped", "ready", "cancelled"])
def test_same_submit_reports_the_stored_job_and_never_executes_resets_or_refreezes_it(world, monkeypatch, state):
    w = world
    request = w.kit.rsubmit("dup", w.s2)
    if state == "ready":
        converge(w, "dup", supplies(w))
    elif state == "stopped":
        w.kit.rel_job("run", request)  # no producer fixture: stops at generation
    else:
        w.kit.rel_job("submit", request)
        if state == "cancelled":
            w.kit.rel_job("cancel", w.kit.rsel("dup"))
    stored, before = jobs(w), w.kit.rel_job("inspect", w.kit.rsel("dup"))
    assert before["state"] == state
    no_execution(monkeypatch)
    monkeypatch.setattr(Engine, "_verify", lambda *a: pytest.fail("a repeated submit froze the job again"))
    assert w.kit.rel_job("submit", request) == before and jobs(w) == stored


def test_submit_conflict_and_cli_fixture_rules_leave_the_stored_job_untouched(world):
    w = world
    request = w.kit.rsubmit("sub", w.s2)
    queued = w.kit.rel_job("submit", request)
    stored = jobs(w)
    pending = w.kit.job("run", w.kit.submit("s2-pending", w.refs["main"], [w.snapshot], topic=True), replay=w.s2_replay)
    with pytest.raises(ExtractionFailure, match="job_input_conflict"):
        w.kit.rel_job("submit", {**request, "upstream": {"jobId": "s2-pending", "inputDigest": pending["inputDigest"]}})
    with pytest.raises(ExtractionFailure, match="job_input_conflict"):
        w.kit.rel_job("run", w.kit.rsubmit("sub", w.s2, source_kind="actual"))
    producer, verifier = w.kit.fixture("producer", "p", []), w.kit.fixture("verifier", "v", [])
    for fixtures in ({"replay": producer}, {"verifier": verifier}, {"replay": producer, "verifier": verifier}):
        assert w.kit.rel("submit", request, expected=2, **fixtures)["error"]["code"] == "fixture_not_allowed"
    live = {**request, "provenance": {**request["provenance"], "executionMode": "live", "recordingKind": "provider"}}
    assert w.kit.rel("submit", live, expected=2)["error"]["code"] == "job_input_conflict"  # same jobId, different frozen input: the stored job wins
    fresh = {**live, "jobId": "sub-live"}
    assert w.kit.rel("submit", fresh, expected=2)["error"]["code"] == "provenance_conflict"  # a new live job over a replay S2 upstream
    assert w.kit.rel("inspect", w.kit.rsel("sub-live"), expected=2)["error"]["code"] == "job_not_found"
    assert w.kit.rel("submit", {**request, "unknown": 1}, expected=2)["error"]["code"] == "input_or_configuration_invalid"
    assert jobs(w) == stored and w.kit.rel_job("inspect", w.kit.rsel("sub")) == queued
    assert database(w).execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0


def test_rights_change_between_submit_and_resume_stops_without_a_call_and_a_repeated_submit_never_restores_or_refreezes(world, monkeypatch):
    w = world
    reference, producer, verifier = authored(w, "reference")
    request, selector = w.kit.rsubmit("late", w.s2), w.kit.rsel("late")
    w.kit.rel_job("submit", request)
    stored = jobs(w)
    grant = w.kit.registry["sources"][0]["grant"]
    grant["revision"] = "rights-2"
    w.kit.save_registry()
    moved = w.kit.rel_job("inspect", selector)
    assert moved["state"] == "queued" and moved["delivery"] == {"status": "withheld", "code": "grant_revision_changed"} and "relations" not in moved
    assert w.kit.rel_job("submit", request) == moved and jobs(w) == stored  # the frozen binding is never replaced by the changed grant
    stopped = w.kit.rel_job("resume", selector, replay=producer, verifier=verifier)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "grant_revision_changed" and stopped["calls"] == [] and stopped["usage"]["replayCalls"] == 0
    grant["revision"] = "rights-1"
    w.kit.save_registry()
    no_execution(monkeypatch)
    again = w.kit.rel_job("submit", request)
    assert again["state"] == "stopped" and again["failure"]["code"] == "grant_revision_changed" and again["calls"] == [] and again["delivery"]["status"] == "current"
    monkeypatch.undo()
    done = w.kit.rel_job("resume", selector, replay=producer, verifier=verifier)
    assert done["state"] == "ready" and done["usage"]["replayCalls"] == reference["usage"]["replayCalls"]
    grant["enabled"] = False
    w.kit.save_registry()
    with pytest.raises(ExtractionFailure, match="source_unauthorized"):
        w.kit.rel_job("submit", w.kit.rsubmit("late-2", w.s2))
    assert [j["job_id"] for j in jobs(w)] == ["late", "reference"]


def test_a_queued_relation_job_cancels_before_any_execution_and_neither_resume_nor_submit_revives_it(world, monkeypatch):
    w = world
    request = w.kit.rsubmit("qc", w.s2)
    w.kit.rel_job("submit", request)
    cancelled = w.kit.rel_job("cancel", w.kit.rsel("qc"))
    assert cancelled["state"] == "cancelled" and cancelled["resumeMode"] == "none" and cancelled["calls"] == []
    assert cancelled["delivery"] == {"status": "withheld", "code": "job_cancelled"} and "relations" not in cancelled
    assert w.kit.rel_job("resume", w.kit.rsel("qc")) == cancelled
    no_execution(monkeypatch)
    assert w.kit.rel_job("submit", request) == cancelled and database(w).execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0
