"""Receipt-only impact rows of the public graph handoff (bundle `-6`): one closed row per emitted INVOLVES source relation.

A row is the S3 result's own words about the relation's impact stage: its status, the verifier's quote effects and the deterministic label that follows from them, never an
aggregate, a price view or a verification of the producer's own proposal. Expectations are hand-written from the authored worlds (`scripts/graph_handoff_smoke.py`:
`expected_impacts`, `impact_scripts`). The real-CLI worlds prove the replay path; the pure cases drive `Planner.impact_row` with hand-built S3 relation payloads for every
status a replay world cannot reach (`withheld`, `verifier_reply_invalid`, `producer_reply_invalid`, uncertain effects) and for the impossible ledger states that must fail whole.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import graph_handoff_smoke as hs
from tests.test_handoff import Rig, approved_world, rehashed, rig, shared, valid_bundle, world_fixture  # noqa: F401
from zoop_ai_pipeline import relation_rules as rules
from zoop_ai_pipeline.handoff import Planner
from zoop_ai_pipeline.handoff_contracts import ExtractionFailure, content_digest, impact_label, validate_bundle
from zoop_ai_pipeline.relation_contracts import IMPACT_POLICY

rich_world = world_fixture("rich", impact="rich")


@pytest.fixture(scope="module")
def rich_bundle(rich_world, tmp_path_factory):
    return Rig(rich_world, tmp_path_factory.mktemp("zoop-handoff-rich")).bundle()


# ---------------------------------------------------------------- real CLI worlds ---------------------------------------------------

def test_the_default_world_has_one_not_proposed_row_per_automatic_involves_source_relation(valid_bundle, shared):
    assert valid_bundle["impacts"] == hs.expected_impacts(shared) and len(valid_bundle["impacts"]) == 3
    assert {r["status"] for r in valid_bundle["impacts"]} == {"not-proposed"}
    assert all(r["impactCandidateId"] is None and r["verifier"] == "not-called" and r["proposal"] is None and r["effects"] is None and r["label"] is None
               for r in valid_bundle["impacts"])
    assert valid_bundle["policy"]["impacts"] == "s3-independent-verifier-quote-effect" and valid_bundle["counts"]["impacts"] == 3
    assert len(valid_bundle["evidence"]) == 6              # an impact row of this world adds no evidence


def test_an_operator_approved_relation_is_not_applicable_and_its_s3_calls_are_unchanged(approved_world, tmp_path):
    bundle = Rig(approved_world, tmp_path).bundle()
    assert bundle["impacts"] == hs.expected_impacts(approved_world)
    manual = [r for r in bundle["impacts"] if r["status"] == "not-applicable"]
    assert len(manual) == 1 and manual[0]["impactCandidateId"] is None and manual[0]["verifier"] == "not-called" and manual[0]["proposal"] is None
    assert {r["status"] for r in bundle["impacts"] if r["status"] != "not-applicable"} == {"not-proposed"}
    assert all(c["impact"]["candidates"] == [] for out in approved_world.jobs.values() for c in out["relations"] if c["type"] == "PARTICIPATES_IN")


def test_the_rich_world_exports_every_replay_status_and_keeps_the_relations_of_one_edge_apart(rich_bundle, rich_world):
    rows = rich_bundle["impacts"]
    assert rows == hs.expected_impacts(rich_world) and rich_bundle["counts"]["impacts"] == 6
    supply = [r for r in rows if r["issueId"] == "issue:supply-2026q3"]
    assert len({r["edgeId"] for r in supply}) == 1 and len(supply) == 4
    labels = sorted((r["sourceRelation"]["jobId"], r["label"]) for r in supply if r["status"] == "verified")
    assert labels == [("rel-a", "positive"), ("rel-b", "negative"), ("rel-b", "undetermined")]        # positive and negative on ONE edge are both preserved, never aggregated
    by_status = {r["status"] + ("/" + r["code"] if r["code"] else ""): r for r in rows if r["status"] != "verified"}
    assert by_status["verifier-reject"]["targetVerdict"] == "contradicted" and by_status["verifier-reject"]["effects"] is None and by_status["verifier-reject"]["label"] is None
    assert by_status["no-evidence"]["label"] is None and by_status["no-evidence"]["verifier"] == "not-called" and by_status["no-evidence"]["proposal"]["direction"] == "undetermined"
    reject = by_status["technical-reject/impact_precheck_rejected"]
    assert reject["proposal"] is None and reject["impactCandidateId"] and reject["verifier"] == "not-called"
    text = json.dumps(rich_bundle, ensure_ascii=False)
    assert hs.IMPACT_OFF_TARGET not in text, "an off-target company id the model invented must never be exported"
    validate_bundle(rich_bundle)


def test_an_impact_only_sentence_is_bundle_evidence_of_the_edges_own_article_and_nothing_else_cites_it(rich_bundle, rich_world):
    inv = hs.evidence_id(rich_world, "a", hs.INV)
    assert inv in {e["id"] for e in rich_bundle["evidence"]}
    cited = {x for i in rich_bundle["issues"] for x in i["evidenceIds"]} | {x for r in rich_bundle["relations"] for x in r["evidenceIds"]}
    assert inv not in cited and inv in {x for r in rich_bundle["impacts"] if r["effects"] for side in r["effects"].values() for x in side}
    assert all(hs.INV not in json.dumps(e, ensure_ascii=False) for e in rich_bundle["evidence"]), "a quote text must never be exported"


def test_a_proposal_is_exported_unverified_and_the_label_is_the_verifiers_not_the_producers(rich_bundle):
    verified = [r for r in rich_bundle["impacts"] if r["status"] == "verified"]
    assert all(r["proposal"]["verification"] == "none" and r["proposal"]["reason"] == hs.IMPACT_REASON for r in verified)
    undetermined = next(r for r in verified if r["targetVerdict"] == "insufficient")
    assert undetermined["proposal"]["direction"] == "positive" and undetermined["label"] == "undetermined"      # the producer said positive; the verifier's target verdict decides
    assert next(r for r in verified if r["effects"]["neutral"])["proposal"]["limitations"] == hs.IMPACT_LIMITS


def test_the_receipt_counts_impacts_and_the_stored_artifact_is_the_exported_bytes(rich_world, tmp_path):
    rig_ = Rig(rich_world, tmp_path)
    frozen = rig_.freeze()
    out = rig_.run("export", rig_.sel())
    assert frozen["receipt"]["counts"]["impacts"] == 6 and frozen["receipt"]["bundleSchema"] == "zoop-graph-handoff-bundle-6"
    assert frozen["usage"] == {"providerCalls": 0, "modelCalls": 0}
    assert hs.canonical(out["bundle"]).encode() == (rig_.state / "bundles" / f"{frozen['receipt']['bundleDigest']}.json").read_bytes()


# ---------------------------------------------------------------- the shared closed validator ----------------------------------------

@pytest.mark.parametrize("name", list(hs.impact_mutations()))
def test_every_broken_impact_rule_is_refused_at_its_own_location(rich_bundle, name):
    change, at, refresh = hs.impact_mutations()[name]
    broken = json.loads(json.dumps(rich_bundle))
    change(broken)
    if refresh:
        broken["digests"]["content"] = content_digest(broken)
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(broken)
    assert exc.value.code == "handoff_bundle_invalid" and exc.value.detail == {"at": at}, (name, exc.value.detail)


def test_proposal_lengths_are_unicode_code_points_not_utf16_units(rich_bundle):
    bundle = hs.unicode_impact_bundle(rich_bundle)
    row = next(r for r in bundle["impacts"] if r["status"] == "verified")
    assert len(row["proposal"]["reason"]) == 2000 and len(row["proposal"]["reason"].encode("utf-16-le")) == 8000
    validate_bundle(bundle)
    row["proposal"]["reason"] += "x"
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(rehashed(bundle, lambda b: None))
    assert exc.value.detail == {"at": "impacts.proposal.reason.length"}


def test_the_label_rule_is_deterministic_over_the_verifiers_effects():
    side = lambda **kw: {"positive": [], "negative": [], "neutral": [], "uncertain": [], **kw}      # noqa: E731
    assert impact_label("supported", side(positive=["a"])) == "positive"
    assert impact_label("supported", side(negative=["a"])) == "negative"
    assert impact_label("supported", side(positive=["a"], negative=["b"])) == "mixed"
    assert impact_label("supported", side(neutral=["a"])) == "undetermined"
    assert impact_label("supported", side(positive=["a"], uncertain=["b"])) == "undetermined"          # one unconfident quote leaves no label
    assert impact_label("insufficient", side(positive=["a"])) == "undetermined"


def test_a_scripted_edit_of_the_s3_impact_rows_cannot_reach_a_valid_bundle(rich_bundle):
    forged = json.loads(json.dumps(rich_bundle))
    next(r for r in forged["impacts"] if r["status"] == "verified").update(label="negative")
    forged["digests"]["content"] = content_digest(forged)
    with pytest.raises(ExtractionFailure):
        validate_bundle(forged)


# ---------------------------------------------------------------- pure producer cases ----------------------------------------------

H = "a" * 64
DOC = "doc-1"


def quote_of(n: int, document: str = DOC) -> dict:
    return {"quoteId": "ev-" + f"{n:032x}", "documentId": document, "documentVersion": H, "start": n, "end": n + 5, "text": f"q{n}"}


def citation_of(q: dict, document: str | None = None) -> dict:
    return {"evidenceId": q["quoteId"], "documentId": document or q["documentId"], "documentVersion": q["documentVersion"], "start": q["start"], "end": q["end"], "quote": q["text"]}


def app_id(c: dict) -> str:
    return "ev-" + hashlib.sha256(f"{c['documentId']}:{c['start']}:{c['end']}".encode()).hexdigest()


ATTEMPT = {"kind": "initial", "seq": 0, "policyVersion": IMPACT_POLICY, "priorVerdictDigest": None}
FACTS = {"subject": {"kind": "company", "ref": "SYNTH-1"}, "object": {"kind": "event", "ref": "evc-x"}}
TARGET = {"kind": "company", "ref": "SYNTH-1"}


def candidate(quotes: list, *, supporting=None, opposing=None, verdict="unset", precheck: str = "pending", company: str = "SYNTH-1", direction: str = "positive") -> dict:
    c = {"impactCandidateId": "ic-" + hashlib.sha256(company.encode() + direction.encode()).hexdigest(), "impactedCompanyId": company, "target": TARGET, "relationFacts": FACTS,
         "proposal": {"direction": direction, "reason": "r", "limitations": None, "supporting": [citation_of(q) for q in quotes] if supporting is None else supporting,
                      "opposing": opposing or []},
         "precheck": {"state": precheck, "reasons": []}, "quotes": quotes if precheck == "pending" else [], "approved": False, "verdict": None if verdict == "unset" else verdict}
    return c


def called(c: dict, **change) -> dict:
    base = {"verifier": "called", "attempt": ATTEMPT, "requestDigest": hs.digest(rules.impact_verifier_request(c, ATTEMPT))}
    return {**base, **change}


def verified(c: dict, mapped: dict, target: str = "supported", label: str | None = None) -> dict:
    full = {"positive": [], "negative": [], "neutral": [], **mapped}
    effects = {"positive": full["positive"], "negative": full["negative"], "uncertain": full.get("uncertain", [])}
    wanted = label or impact_label(target, {**effects, "neutral": full["neutral"]})
    return called(c, status="verified", label=wanted, reasons=[], targetVerdict=target, mapped=full)


def planner(relation: dict, *, kind: str = "automatic-verifier") -> tuple[Planner, dict, SimpleNamespace]:
    p = Planner.__new__(Planner)
    p.used_review = {("job", "rc-" + "1" * 64): {"kind": kind, "revision": 1, "reviewer": None, "decidedAt": "2026-10-21T00:00:00+00:00"}}
    p.cite = lambda loaded, c: app_id(c)
    p.impacts, p.impact_evidence = [], set()
    loaded = SimpleNamespace(pin=SimpleNamespace(relation=SimpleNamespace(job_id="job")), relations={"rc-" + "1" * 64: relation},
                             s3={"binding": {"versions": {"impactPolicy": IMPACT_POLICY}}})
    edge = {"id": "edge-" + "e" * 64, "source": "issue:a", "target": "KRX:1", "sourceRefs": [{"kind": "s3-relation", "jobId": "job", "id": "rc-" + "1" * 64}]}
    p.relations, p.by_job = [edge], {"job": loaded}
    return p, edge, loaded


def relation_of(candidates: list, status: str = "complete", documents=(DOC,)) -> dict:
    return {"subject": TARGET, "citations": [{"documentId": d, "documentVersion": H, "start": 0, "end": 1, "quote": "x"} for d in documents],
            "impact": {"status": status, "candidates": candidates}}


def row_of(relation: dict, **kw) -> tuple[dict, set]:
    p, edge, loaded = planner(relation, **kw)
    return p.impact_row(edge, loaded, "rc-" + "1" * 64)


def test_a_complete_stage_without_an_on_target_candidate_is_not_proposed_and_an_off_target_one_is_never_exported():
    row, evidence = row_of(relation_of([]))
    assert row["status"] == "not-proposed" and row["impactCandidateId"] is None and row["proposal"] is None and evidence == set()
    off = candidate([quote_of(1)], precheck="reject", company="SYNTH-77", verdict={"status": "reject", "label": None, "reasons": [], "targetVerdict": None, "mapped": None,
                                                                                    "verifier": "not-called"})
    row, _ = row_of(relation_of([off]))
    assert row["status"] == "not-proposed" and "SYNTH-77" not in json.dumps(row) and off["impactCandidateId"] not in json.dumps(row)


def test_an_automatic_relation_whose_producer_reply_was_invalid_is_a_technical_reject_without_a_candidate():
    row, evidence = row_of(relation_of([], status="producer-reply-invalid"))
    assert (row["status"], row["code"], row["impactCandidateId"], row["verifier"], row["proposal"]) == ("technical-reject", "producer_reply_invalid", None, "not-called", None)
    assert evidence == set()


def test_a_precheck_reject_exports_no_reason_detail_and_no_proposal():
    c = candidate([quote_of(1)], precheck="reject", verdict={"status": "reject", "label": None, "targetVerdict": None, "mapped": None, "verifier": "not-called",
                                                              "reasons": [{"code": "citation_invalid", "at": "supporting:1", "detail": "secret detail"}]})
    row, evidence = row_of(relation_of([c]))
    assert (row["status"], row["code"], row["proposal"], row["label"], row["effects"]) == ("technical-reject", "impact_precheck_rejected", None, None, None)
    assert row["impactCandidateId"] == c["impactCandidateId"] and "secret detail" not in json.dumps(row) and evidence == set()


def test_no_cited_evidence_is_no_evidence_with_the_proposal_and_never_an_undetermined_label():
    c = candidate([], precheck="no-evidence", verdict={"status": "verified", "label": "undetermined", "reasons": [{"code": "no_cited_evidence"}], "targetVerdict": None,
                                                        "mapped": {"positive": [], "negative": [], "neutral": []}, "verifier": "not-called"})
    row, _ = row_of(relation_of([c]))
    assert (row["status"], row["label"], row["targetVerdict"], row["effects"], row["verifier"], row["verifierRequestDigest"]) == ("no-evidence", None, None, None, "not-called", None)
    assert row["proposal"]["direction"] == "positive" and row["proposal"]["verification"] == "none"


def test_a_replayed_invalid_verifier_reply_is_a_technical_reject_that_keeps_the_proposal():
    c = candidate([quote_of(1)])
    c["verdict"] = called(c, status="reject", label=None, targetVerdict=None, mapped=None, reasons=[{"code": "verification_reply_invalid", "detail": "x"}])
    row, evidence = row_of(relation_of([c]))
    assert (row["status"], row["code"], row["verifier"]) == ("technical-reject", "verifier_reply_invalid", "called") and row["proposal"] and evidence == set()
    assert row["verifierRequestDigest"] == c["verdict"]["requestDigest"]


def test_a_contradicted_target_is_a_verifier_reject_without_label_or_effects():
    c = candidate([quote_of(1)])
    c["verdict"] = called(c, status="reject", label=None, targetVerdict="contradicted", mapped={"positive": ["x"], "negative": [], "neutral": []},
                          reasons=[{"code": "impact_target_contradicted"}])
    row, evidence = row_of(relation_of([c]))
    assert (row["status"], row["targetVerdict"], row["label"], row["effects"]) == ("verifier-reject", "contradicted", None, None) and evidence == set()


def test_a_verified_row_maps_the_verifiers_effects_to_app_evidence_and_computes_the_label_from_them():
    q1, q2, q3 = quote_of(1), quote_of(2), quote_of(3)
    c = candidate([q1, q2, q3])
    c["verdict"] = verified(c, {"positive": [q1["quoteId"]], "negative": [q2["quoteId"]], "neutral": [q3["quoteId"]]})
    row, evidence = row_of(relation_of([c]))
    ids = {q["text"]: app_id(citation_of(q)) for q in (q1, q2, q3)}
    assert (row["status"], row["label"], row["targetVerdict"]) == ("verified", "mixed", "supported")
    assert row["effects"] == {"positive": [ids["q1"]], "negative": [ids["q2"]], "neutral": [ids["q3"]], "uncertain": []} and evidence == set(ids.values())


def test_uncertain_and_insufficient_leave_the_label_undetermined_and_keep_every_mapped_effect():
    q1, q2 = quote_of(1), quote_of(2)
    c = candidate([q1, q2])
    c["verdict"] = verified(c, {"positive": [q1["quoteId"]], "uncertain": [q2["quoteId"]]})
    row, _ = row_of(relation_of([c]))
    assert row["label"] == "undetermined" and row["effects"]["positive"] == [app_id(citation_of(q1))] and row["effects"]["uncertain"] == [app_id(citation_of(q2))]
    c["verdict"] = verified(c, {"positive": [q1["quoteId"], q2["quoteId"]]}, target="insufficient")
    row, _ = row_of(relation_of([c]))
    assert (row["label"], row["targetVerdict"]) == ("undetermined", "insufficient")


def test_a_quote_id_two_documents_share_is_withheld_never_resolved_by_choice():
    q = quote_of(1)
    c = candidate([q], supporting=[citation_of(q), citation_of(q, "doc-2")])
    c["verdict"] = verified(c, {"positive": [q["quoteId"]]})
    row, evidence = row_of(relation_of([c], documents=(DOC, "doc-2")))
    assert (row["status"], row["code"], row["label"], row["effects"], row["targetVerdict"]) == ("withheld", "impact_quote_ambiguous", None, None, None)
    assert row["verifier"] == "called" and row["proposal"] and row["impactCandidateId"] and evidence == set()


def test_a_verified_quote_outside_the_relations_documents_is_withheld_and_never_recomputed_from_a_subset():
    inside, outside = quote_of(1), quote_of(2, "doc-9")
    c = candidate([inside, outside])
    c["verdict"] = verified(c, {"positive": [inside["quoteId"]], "negative": [outside["quoteId"]]})
    row, evidence = row_of(relation_of([c]))
    assert (row["status"], row["code"], row["label"], row["effects"]) == ("withheld", "impact_evidence_outside_relation_documents", None, None) and evidence == set()


def test_a_row_that_cannot_be_proven_leaves_no_provisional_evidence_behind():
    q1, q2 = quote_of(1), quote_of(2)
    c = candidate([q1, q2])
    c["verdict"] = verified(c, {"positive": [q1["quoteId"], q2["quoteId"]]})
    p, edge, loaded = planner(relation_of([c]))
    seen = []

    def cite(loaded_, c_):
        seen.append(c_["start"])
        if len(seen) == 2:
            raise ExtractionFailure("evidence_unresolvable")
        return app_id(c_)

    p.cite = cite
    with pytest.raises(ExtractionFailure):
        p.build_impacts()
    assert p.impact_evidence == set() and p.impacts == []


def test_a_withheld_row_after_a_verified_one_adds_only_the_verified_rows_evidence():
    ok, bad = quote_of(1), quote_of(2, "doc-9")
    first, second = candidate([ok]), candidate([bad], company="SYNTH-1", direction="negative")
    first["verdict"], second["verdict"] = verified(first, {"positive": [ok["quoteId"]]}), verified(second, {"negative": [bad["quoteId"]]})
    p, edge, loaded = planner(relation_of([first]))
    other = relation_of([second])
    loaded.relations["rc-" + "2" * 64] = other
    edge["sourceRefs"].append({"kind": "s3-relation", "jobId": "job", "id": "rc-" + "2" * 64})
    p.used_review[("job", "rc-" + "2" * 64)] = p.used_review[("job", "rc-" + "1" * 64)]
    p.build_impacts()
    assert [r["status"] for r in p.impacts] == ["verified", "withheld"] and p.impact_evidence == {app_id(citation_of(ok))}


@pytest.mark.parametrize("name,build", [
    ("an automatic relation whose impact stage is still pending", lambda: row_of(relation_of([], status="pending"))),
    ("a candidate without a verdict", lambda: row_of(relation_of([candidate([quote_of(1)])]))),
    ("a candidate whose verdict is None", lambda: row_of(relation_of([candidate([quote_of(1)], verdict=None)]))),
    ("two candidates for the same on-target company", lambda: row_of(relation_of([candidate([quote_of(1)]), candidate([quote_of(2)], direction="negative")]))),
    ("an operator-approved relation that has a candidate", lambda: row_of(relation_of([candidate([quote_of(1)])], status="not-applicable"), kind="operator-final-approval")),
    ("an operator-approved relation whose stage is not not-applicable", lambda: row_of(relation_of([]), kind="operator-final-approval")),
])
def test_an_impossible_ledger_state_fails_the_whole_freeze(name, build):
    with pytest.raises(ExtractionFailure) as exc:
        build()
    assert exc.value.code == "relation_payload_invalid", name


def test_a_called_verdict_must_carry_the_digest_policy_and_label_the_rules_recompute():
    q = quote_of(1)
    base = candidate([q])

    def with_verdict(change) -> None:
        c = json.loads(json.dumps(base))
        c["verdict"] = {**verified(c, {"positive": [q["quoteId"]]}), **change}
        with pytest.raises(ExtractionFailure) as exc:
            row_of(relation_of([c]))
        assert exc.value.code == "relation_payload_invalid", change

    with_verdict({"requestDigest": "b" * 64})                                         # not the digest of the request this candidate and attempt produce
    with_verdict({"attempt": {**ATTEMPT, "policyVersion": "zoop-impact-policy-0"}})   # another impact policy than the one this S3 job was bound to
    with_verdict({"label": "negative"})                                               # a label the quote effects do not yield
    with_verdict({"mapped": {"positive": [], "negative": [], "neutral": []}})        # a quote the verifier never mapped


# ---------------------------------------------------------------- fixture consistency (focused proofs) ----------------------------------

def test_the_unicode_fixture_envelope_is_resealed_and_its_expected_rows_are_the_unicode_proposal(rich_bundle, rich_world):
    out = {"bundle": rich_bundle, "receipt": {"bundleDigest": "0" * 64, "contentDigest": rich_bundle["digests"]["content"], "bundleBytes": 1, "counts": rich_bundle["counts"]}}
    sealed = hs.unicode_impact_envelope(out)
    raw = hs.canonical(sealed["bundle"]).encode("utf-8")
    assert sealed["receipt"]["contentDigest"] == sealed["bundle"]["digests"]["content"] == content_digest(sealed["bundle"]) != rich_bundle["digests"]["content"]
    assert sealed["receipt"]["bundleDigest"] == hashlib.sha256(raw).hexdigest() and sealed["receipt"]["bundleBytes"] == len(raw)
    rows = hs.unicode_impact_rows(hs.expected_impacts(rich_world))
    assert rows == sealed["bundle"]["impacts"] and rows != hs.expected_impacts(rich_world)
    assert len(next(r for r in rows if r["status"] == "verified")["proposal"]["reason"]) == 2000


def test_the_other_article_negative_has_a_valid_label_so_only_the_article_rule_refuses_it(rich_bundle):
    change, at, refresh = hs.impact_mutations()["an effect on another article version than the edge's"]
    broken = json.loads(json.dumps(rich_bundle))
    change(broken)
    row = next(r for r in broken["impacts"] if r["effects"] and r["effects"]["uncertain"])
    assert row["label"] == impact_label(row["targetVerdict"], row["effects"]) == "undetermined"
    broken["digests"]["content"] = content_digest(broken)
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(broken)
    assert exc.value.detail == {"at": "impacts.effects.articleClosure"}
