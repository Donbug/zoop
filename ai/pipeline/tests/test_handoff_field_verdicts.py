"""Operator per-field verdicts (`eventTime` / `period`) of the public graph handoff (bundle `-4`, decisions `-2`).

A verdict is an OPERATOR review of one original mention's value; S2/S3 verify neither field, and nothing here derives a verdict from a selection, a geography or a model.
Expectations are written by hand from the authored world (`scripts/graph_handoff_smoke.py`: `verdict_cases`, `expected_verdicts`, `expected_headlines`); the reviews are
SYNTHETIC. Binding failures exclude only the issue (visible code), a malformed file is refused whole, and the public validator recomputes what the producer withheld.
"""
from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from scripts import graph_handoff_smoke as hs
from tests.test_handoff import (Rig, assert_withheld_without_content, collision_rig, collision_same, dated_world, excluded, factory_of, mention_of, mentions_of,  # noqa: F401
                                rehashed, rig, shared, structural_edges, supply_of)
from zoop_ai_pipeline.handoff_contracts import Decisions, app_evidence_id, ExtractionFailure, content_digest, validate_bundle

SUPPLY, FACTORY = "issue:supply-2026q3", "issue:factory-2026q4"


def review(rig: Rig, cases: dict | None = None, **options) -> None:
    """Replaces the rig's decisions with the world's hand-authored review (or `cases`) and writes the operator files."""
    rig.docs["decisions"] = hs.decisions_doc(rig.world, verdicts=json.loads(json.dumps(hs.verdict_cases(rig.world) if cases is None else cases)), **options)
    rig.write()


@pytest.fixture(scope="module")
def verdict_bundle(shared, tmp_path_factory):
    docs = {"canonical": hs.canonical_doc(shared), "bindings": hs.bindings_doc(shared),
            "decisions": hs.decisions_doc(shared, verdicts=hs.verdict_cases(shared), published_time=None)}
    return Rig(shared, tmp_path_factory.mktemp("zoop-handoff-verdicts"), docs=docs).bundle()


# ---------------------------------------------------------------- the operator file ----------------------------------------------------

def test_the_hand_authored_review_is_a_valid_decisions_file_in_every_decision_and_reason_combination(shared):
    world = shared
    for decision, reason, quotes in (("ALLOW", "stated", [hs.PERIOD_A]), ("HOLD", "ambiguous", [hs.PERIOD_A]), ("REJECT", "contradicted", [hs.PERIOD_A]), ("HOLD", "unstated", [])):
        doc = hs.decisions_doc(world, verdicts={"issue:supply": [hs.field_verdict(world, "a", "m-a", "period", "2026Q3", decision, reason, quotes)]})
        assert doc["schemaVersion"] == "zoop-public-decisions-2"
        Decisions.model_validate(doc)


def malformed() -> dict:
    """name -> change of the supply issue's verdict list (the hand-authored review: [a2 period REJECT, a period ALLOW, a2 eventTime HOLD/unstated, a eventTime REJECT])."""
    return {
        "a duplicate (mention, field)": lambda w, v: v.append(json.loads(json.dumps(v[1]))),
        "ALLOW without a span": lambda w, v: v[1].update(evidence=[]),
        "HOLD/unstated with a span": lambda w, v: v[2].update(evidence=[hs.span(w, "a2", hs.PERIOD_A2)]),
        "REJECT with the reason stated": lambda w, v: v[0].update(reasonCode="stated"),
        "ALLOW with the reason unstated": lambda w, v: v[1].update(reasonCode="unstated"),
        "HOLD/ambiguous without a span": lambda w, v: v.append(hs.field_verdict(w, "b", "m-b", "eventTime", "2026-11-15", "HOLD", "ambiguous")),
        "a free-text note": lambda w, v: v[0].update(note="private review note"),
        "a missing reviewer": lambda w, v: v[0].pop("reviewer"),
        "a null value": lambda w, v: v[0].update(value=None),
        "a judged field that is not eventTime or period": lambda w, v: v[0].update(field="title"),
        "a lowercase decision": lambda w, v: v[1].update(decision="allow"),
        "more than twenty spans": lambda w, v: v[1].update(evidence=[hs.span(w, "a", hs.EVT_A[:n]) for n in range(3, 24)]),
        "a span with an unknown key": lambda w, v: v[1]["evidence"][0].update(quote="text"),
    }


@pytest.mark.parametrize("name,change", list(malformed().items()), ids=list(malformed()))
def test_a_malformed_review_file_is_refused_whole_and_nothing_is_frozen(rig, name, change):
    doc = hs.decisions_doc(rig.world, verdicts=json.loads(json.dumps(hs.verdict_cases(rig.world))))
    change(rig.world, doc["issues"][0]["fieldVerdicts"])
    with pytest.raises(ValidationError):
        Decisions.model_validate(doc)
    rig.docs["decisions"] = doc
    rig.write()
    assert rig.run("freeze", rig.manifest(), expected=2)["error"]["code"] == "decisions_invalid"
    assert rig.rows() == 0


def test_a_decisions_file_without_the_verdict_list_or_of_the_earlier_schema_is_refused(rig):
    doc = hs.decisions_doc(rig.world)
    for issue in doc["issues"]:
        del issue["fieldVerdicts"]
    with pytest.raises(ValidationError):
        Decisions.model_validate(doc)
    with pytest.raises(ValidationError):
        Decisions.model_validate({**hs.decisions_doc(rig.world), "schemaVersion": "zoop-public-decisions-1"})
    rig.docs["decisions"] = {**doc, "schemaVersion": "zoop-public-decisions-1"}
    rig.write()
    assert rig.run("freeze", rig.manifest(), expected=2)["error"]["code"] == "decisions_invalid"


# ---------------------------------------------------------------- producer ----------------------------------------------------

def test_the_review_is_exported_as_hand_written_and_withholds_exactly_what_the_selection_basis_rejects(verdict_bundle, shared):
    bundle = verdict_bundle
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-4"
    assert {i["id"]: i["fieldVerdicts"] for i in bundle["issues"]} == hs.expected_verdicts(shared, hs.verdict_cases(shared))
    assert {i["id"]: i["fieldProvenance"] for i in bundle["issues"]} == hs.expected_field_provenance(shared, hs.VERDICT_WITHHELD)
    assert {i["id"]: (i["eventTime"], i["timePrecision"], i["period"]) for i in bundle["issues"]} == hs.expected_headlines(shared, hs.VERDICT_WITHHELD)
    assert mentions_of(bundle) == hs.expected_mentions(shared), "a verdict changed an original mention value"
    hs.assert_field_provenance_closed(bundle)
    hs.assert_mentions_reachable(bundle)
    validate_bundle(bundle)


def test_a_withheld_headline_never_falls_back_to_another_mentions_value(verdict_bundle):
    supply = supply_of(verdict_bundle)
    assert {m["mentionId"]: m["eventTime"] for m in supply["mentions"]} == {"m-a": "2026-09-30", "m-a2": "2026-09-30"}       # both mentions state a day ...
    assert (supply["eventTime"], supply["timePrecision"]) == (None, "unknown")                                                # ... the representative's REJECT withholds the headline
    assert factory_of(verdict_bundle)["period"] is None and mention_of(factory_of(verdict_bundle), "m-b")["period"] == "2026Q4"


def test_a_verdict_names_an_operator_never_ai_and_exports_no_review_text(verdict_bundle):
    verdicts = [v for i in verdict_bundle["issues"] for v in i["fieldVerdicts"]]
    assert verdicts and {v["verification"] for v in verdicts} == {"operator-field-verdict"} and {v["reviewer"] for v in verdicts} == {hs.REVIEWER}
    assert all(set(v) == {"documentId", "documentVersion", "mentionId", "field", "value", "decision", "reasonCode", "evidenceIds", "verification", "reviewer", "decisionRef",
                          "decisionVersion"} for v in verdicts)
    text = json.dumps(verdict_bundle, ensure_ascii=False)
    assert not any(quote in text for quote in (hs.PERIOD_A, hs.PERIOD_A2, hs.PERIOD_B, *hs.PRIVATE))


def test_only_the_verdicts_spans_extend_the_issue_evidence_and_the_relations_keep_theirs(verdict_bundle, shared):
    ids = {name: hs.evidence_id(shared, name, quote) for name, quote in (("a", hs.PERIOD_A), ("a2", hs.PERIOD_A2), ("b", hs.PERIOD_B))}
    base = hs.expected(shared)
    assert supply_of(verdict_bundle)["evidenceIds"] == sorted({*base["issues"][SUPPLY]["evidenceIds"], ids["a"], ids["a2"]})
    assert factory_of(verdict_bundle)["evidenceIds"] == sorted({*base["issues"][FACTORY]["evidenceIds"], ids["b"]})
    assert {(r["type"], r["source"], r["target"]): r["evidenceIds"] for r in verdict_bundle["relations"]} == base["relations"]


def test_without_any_review_every_headline_is_kept_and_nothing_is_withheld_or_verified(rig):
    bundle = rig.bundle()
    assert [i["fieldVerdicts"] for i in bundle["issues"]] == [[], []] and all(i["fieldProvenance"]["withheld"] == [] for i in bundle["issues"])
    assert {i["id"]: (i["eventTime"], i["timePrecision"], i["period"]) for i in bundle["issues"]} == hs.expected_headlines(rig.world)


def test_a_hold_or_reject_on_a_non_representative_mention_withholds_nothing(rig):
    world = rig.world
    review(rig, {"issue:supply": [hs.field_verdict(world, "a2", "m-a2", "eventTime", "2026-09-30", "HOLD", "unstated"),
                                  hs.field_verdict(world, "a2", "m-a2", "period", "2026Q3", "REJECT", "contradicted", [hs.PERIOD_A2])]})
    bundle = rig.bundle()
    supply = supply_of(bundle)
    assert supply["fieldProvenance"]["withheld"] == [] and (supply["eventTime"], supply["period"]) == ("2026-09-30", "2026Q3")
    assert [(v["mentionId"], v["field"], v["decision"]) for v in supply["fieldVerdicts"]] == [("m-a2", "eventTime", "HOLD"), ("m-a2", "period", "REJECT")]
    hs.assert_field_provenance_closed(bundle)


def test_without_a_representative_a_hold_on_any_mention_withholds_the_shared_value(collision_same, tmp_path):
    rig = collision_rig(collision_same, tmp_path)
    rig.docs["decisions"]["issues"][0]["fieldVerdicts"] = [hs.field_verdict(collision_same, "a2", "m-a", "period", "2026Q3", "HOLD", "ambiguous", [hs.PERIOD_A2])]
    rig.write()
    supply = supply_of(rig.bundle())
    assert supply["representative"] is None and supply["fieldProvenance"]["withheld"] == ["period"] and supply["period"] is None
    assert supply["eventTime"] == "2026-09-30" and {m["period"] for m in supply["mentions"]} == {"2026Q3"}
    assert supply["fieldProvenance"]["sameValueMentions"]["period"] == [{k: m[k] for k in ("documentId", "documentVersion", "mentionId")} for m in supply["mentions"]]


def unbindable() -> dict:
    """name -> (code, change of the supply verdict list). Index 3 is the representative's eventTime REJECT, 1 its period ALLOW."""
    return {
        "a value other than the mention's": ("field_verdict_stale", lambda w, v: v[3].update(value="2026-10-01")),
        "a value with another form of the same day": ("field_verdict_stale", lambda w, v: v[3].update(value="2026-09-30T00:00+09:00")),
        "a mention of another issue": ("field_verdict_unbound", lambda w, v: v.append(hs.field_verdict(w, "b", "m-b", "period", "2026Q4", "ALLOW", "stated", [hs.PERIOD_B]))),
        "an unknown mention": ("field_verdict_unbound", lambda w, v: v[3].update(mentionId="m-zzz")),
        "the right mention id in another document version": ("field_verdict_unbound", lambda w, v: v[3].update(documentVersion="f" * 64)),
        "a span of another document": ("field_verdict_evidence_unbound", lambda w, v: v[1].update(evidence=[hs.span(w, "b", hs.PERIOD_B)])),
        "a span of another version of the document": ("field_verdict_evidence_unbound", lambda w, v: v[1]["evidence"][0].update(documentVersion="e" * 64)),
        "a tampered quote hash": ("field_verdict_evidence_mismatch", lambda w, v: v[1]["evidence"][0].update(quoteSha256="0" * 64)),
        "a shifted span": ("field_verdict_evidence_mismatch", lambda w, v: v[1]["evidence"][0].update(start=v[1]["evidence"][0]["start"] + 1, end=v[1]["evidence"][0]["end"] + 1)),
        "a span past the text": ("field_verdict_evidence_mismatch", lambda w, v: v[1]["evidence"][0].update(end=10_000)),
    }


@pytest.mark.parametrize("name", list(unbindable()))
def test_a_review_that_cannot_be_bound_excludes_only_its_issue_visibly(rig, name):
    code, change = unbindable()[name]
    review(rig)
    change(rig.world, rig.docs["decisions"]["issues"][0]["fieldVerdicts"])
    rig.write()
    bundle = rig.bundle()
    assert [i for i in bundle["exclusions"]["items"] if i["id"] == "issue:supply"] == [{"kind": "issue", "id": "issue:supply", "jobId": None, "code": code}], name
    assert [i["id"] for i in bundle["issues"]] == [FACTORY]
    assert bundle["issues"][0]["fieldVerdicts"] == hs.expected_verdicts(rig.world, hs.verdict_cases(rig.world))[FACTORY] and bundle["issues"][0]["period"] is None


def test_a_withheld_event_time_is_a_structural_input_and_the_old_attestation_is_refused_with_the_new_digest(rig):
    world = rig.world
    review(rig, {"issue:supply": [hs.field_verdict(world, "a", "m-a", "eventTime", "2026-09-30", "REJECT", "contradicted", [hs.EVT_A])]})
    bundle = rig.bundle()
    supply = supply_of(bundle)
    assert (supply["eventTime"], supply["timePrecision"], supply["fieldProvenance"]["withheld"]) == (None, "unknown", ["eventTime"]) and supply["period"] == "2026Q3"
    assert not structural_edges(bundle) and excluded(bundle)[("structural", "issue:supply>co:synth-3")] == "applicability_binding_mismatch"
    detail = next(i for i in bundle["exclusions"]["items"] if i["kind"] == "structural")["detail"]
    assert detail == {"expectedBindingDigest": hs.structural_binding(world, published_time=None)}
    assert any(r["type"] == "FOLLOWS" for r in bundle["relations"]), "FOLLOWS does not depend on the event time"
    # The operator re-reviews the attestation against the withheld time and the edge is exported.
    review(rig, {"issue:supply": [hs.field_verdict(world, "a", "m-a", "eventTime", "2026-09-30", "REJECT", "contradicted", [hs.EVT_A])]}, published_time=None)
    assert len(structural_edges(rig.bundle("h2"))) == 1


def test_a_dated_basis_cannot_be_proven_against_a_withheld_event_time(dated_world, tmp_path):
    rig = Rig(dated_world, tmp_path, docs={"canonical": hs.canonical_doc(dated_world), "bindings": hs.bindings_doc(dated_world), "decisions": hs.decisions_doc(
        dated_world, verdicts={"issue:supply": [hs.field_verdict(dated_world, "a", "m-a", "eventTime", "2026-09-30", "HOLD", "ambiguous", [hs.EVT_A])]})})
    bundle = rig.bundle()
    assert not structural_edges(bundle) and excluded(bundle)[("structural", "issue:supply>co:synth-3")] == "basis_validity_unprovable"


def test_a_changed_review_withholds_the_frozen_handoff_keeps_its_receipt_and_a_new_id_carries_the_new_review(rig):
    review(rig)
    frozen = rig.freeze("h1")
    receipt = rig.run("inspect", rig.sel("h1"))
    changed = json.loads(json.dumps(hs.verdict_cases(rig.world)))
    changed["issue:supply"][3] = hs.field_verdict(rig.world, "a", "m-a", "eventTime", "2026-09-30", "ALLOW", "stated", [hs.EVT_A], version="fv2")
    review(rig, changed)
    assert_withheld_without_content(rig.run("export", rig.sel("h1"), expected=2))
    assert rig.run("inspect", rig.sel("h1")) == receipt
    second = rig.bundle("h2")
    assert second["handoffId"] == "h2" and second["digests"]["content"] != frozen["receipt"]["contentDigest"]
    assert (supply_of(second)["eventTime"], supply_of(second)["fieldProvenance"]["withheld"]) == ("2026-09-30", [])


# ---------------------------------------------------------------- public validator ----------------------------------------------------

def verdict_of(bundle: dict, mention_id: str, field: str, issue=supply_of) -> dict:
    return next(v for v in issue(bundle)["fieldVerdicts"] if (v["mentionId"], v["field"]) == (mention_id, field))


def refusals() -> dict:
    """name -> (corruption of the verdict export, `at` of the refusal written by hand from the rules). The supply issue has the representative `m-a` (eventTime REJECT ->
    withheld, period ALLOW) and the non-representative `m-a2` (eventTime HOLD/unstated, period REJECT); the factory issue is unanimous with a period HOLD."""
    FV, FP = "issue.fieldVerdicts", "issue.fieldProvenance"
    foreign = lambda b: [e["id"] for e in b["evidence"] if e["articleId"] != mention_of(supply_of(b), "m-a")["articleId"]][0]  # noqa: E731

    def cite_foreign(b):
        verdict_of(b, "m-a", "period")["evidenceIds"] = [foreign(b)]
        supply_of(b)["evidenceIds"] = sorted({*supply_of(b)["evidenceIds"], foreign(b)})

    def unstated_with_evidence(b):
        verdict_of(b, "m-a2", "eventTime")["evidenceIds"] = list(verdict_of(b, "m-a2", "period")["evidenceIds"])

    def orphan(b):
        lost = verdict_of(b, "m-a2", "period")["evidenceIds"][0]
        supply_of(b)["evidenceIds"] = [i for i in supply_of(b)["evidenceIds"] if i != lost]

    return {
        "the headline period not withheld": (lambda b: factory_of(b).update(period="2026Q4"), f"{FP}.period.published"),
        "the withheld headline replaced by another mention's value": (lambda b: supply_of(b).update(eventTime="2026-09-30"), f"{FP}.eventTime.published"),
        "a field withheld that no verdict withholds": (lambda b: supply_of(b)["fieldProvenance"].update(withheld=["eventTime", "period"]), f"{FP}.withheld"),
        "a withheld field not listed": (lambda b: factory_of(b)["fieldProvenance"].update(withheld=[]), f"{FP}.withheld"),
        "a withheld event time with a known precision": (lambda b: supply_of(b).update(timePrecision="day"), "issue.timePrecision.withheld"),
        "an issue precision that is not the selected mention's although the time is published": (lambda b: factory_of(b).update(timePrecision="month"), "issue.timePrecision.selected"),
        "a verdict value that is not the mention's": (lambda b: verdict_of(b, "m-a", "eventTime").update(value="2026-10-01"), f"{FV}.value.exact"),
        "a verdict on another form of the same day": (lambda b: verdict_of(b, "m-a", "eventTime").update(value="2026-09-30T00:00+09:00"), f"{FV}.value.exact"),
        "a verdict evidence of another article": (cite_foreign, f"{FV}.evidenceClosure"),
        "an unstated verdict that cites evidence": (unstated_with_evidence, f"{FV}.evidenceCount"),
        "an ALLOW without evidence": (lambda b: verdict_of(b, "m-a", "period").update(evidenceIds=[]), f"{FV}.evidenceIds"),
        "a verdict evidence missing from the issue evidence": (orphan, "issue.evidenceClosure"),
        "a duplicate verdict": (lambda b: supply_of(b)["fieldVerdicts"].append(json.loads(json.dumps(supply_of(b)["fieldVerdicts"][0]))), f"{FV}.order"),
        "verdicts out of order": (lambda b: supply_of(b)["fieldVerdicts"].reverse(), f"{FV}.order"),
        "a note": (lambda b: supply_of(b)["fieldVerdicts"][0].update(note="private note"), FV),
        "a missing verification": (lambda b: supply_of(b)["fieldVerdicts"][0].pop("verification"), FV),
        "a verification that is not the operator's": (lambda b: supply_of(b)["fieldVerdicts"][0].update(verification="none"), f"{FV}.verification"),
        "a decision and reason that do not go together": (lambda b: verdict_of(b, "m-a2", "period").update(reasonCode="stated"), f"{FV}.reasonCode"),
        "a verdict on a mention of no issue": (lambda b: factory_of(b)["fieldVerdicts"][0].update(mentionId="m-zzz"), f"{FV}.mentionClosure"),
        "a judged field that is not eventTime or period": (lambda b: factory_of(b)["fieldVerdicts"][0].update(field="title"), f"{FV}.field"),
        "a verdict list that is not a list": (lambda b: supply_of(b).update(fieldVerdicts=None), FV),
        "no verdict list": (lambda b: supply_of(b).pop("fieldVerdicts"), "issue"),
        "a field decision beside the verdicts": (lambda b: supply_of(b).update(fieldDecisions=[]), "issue"),
    }


@pytest.mark.parametrize("name", list(refusals()))
def test_the_public_validator_refuses_a_verdict_bundle_that_is_not_what_the_rules_derive_even_with_a_refreshed_digest(verdict_bundle, name):
    validate_bundle(verdict_bundle)
    change, at = refusals()[name]
    broken = rehashed(verdict_bundle, change)
    assert broken["digests"]["content"] == content_digest(broken)
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(broken)
    assert exc.value.code == "handoff_bundle_invalid" and exc.value.detail == {"at": at}, name


# ---------------------------------------------------------------- verdict evidence bound ----------------------------------------------------

def with_verdict_evidence(count: int):
    """A change giving the representative's period verdict `count` DISTINCT, otherwise valid evidence rows of that mention's own article, all also in the issue evidence,
    so only the per-verdict bound (at most 20, like the operator file, the service and the app) can refuse it."""
    def change(b):
        supply = supply_of(b)
        verdict = verdict_of(b, "m-a", "period")
        template = next(e for e in b["evidence"] if e["id"] == verdict["evidenceIds"][0])
        rows = []
        for n in range(count - 1):
            row = copy.deepcopy(template)
            row["start"], row["end"] = 5000 + n, 5001 + n
            row["id"] = app_evidence_id(row["articleId"], row["articleVersion"], row["start"], row["end"])
            rows.append(row)
        b["evidence"].extend(rows)
        b["counts"]["evidence"] = len(b["evidence"])
        verdict["evidenceIds"] = sorted([template["id"], *(row["id"] for row in rows)])        # the original span stays cited, so the issue union stays exact
        supply["evidenceIds"] = sorted({*supply["evidenceIds"], *verdict["evidenceIds"]})
    return change


def test_a_verdict_may_cite_twenty_evidence_rows_and_never_twenty_one(verdict_bundle):
    validate_bundle(rehashed(verdict_bundle, with_verdict_evidence(20)))
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(rehashed(verdict_bundle, with_verdict_evidence(21)))
    assert exc.value.code == "handoff_bundle_invalid" and exc.value.detail == {"at": "issue.fieldVerdicts.evidenceIds"}
