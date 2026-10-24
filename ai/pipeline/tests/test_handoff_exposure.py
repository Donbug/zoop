"""Consumer-facing cases of the read-only handoff exposure report: the pure closure over hand-authored bundles, the query contract and the whole-command
refusals that happen before any ledger is opened. The actual-CLI-over-real-ledgers cases live in `tests/test_handoff_exposure_cli.py`."""
from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
from unittest import mock

import pytest
from pydantic import ValidationError

from scripts import graph_handoff_smoke as hs
from tests.test_handoff import Rig
from zoop_ai_pipeline import handoff_exposure_cli
from zoop_ai_pipeline.handoff_contracts import BUNDLE_SCHEMA
from zoop_ai_pipeline.handoff_contracts import SCHEMA as HANDOFF_SCHEMA
from zoop_ai_pipeline.handoff_exposure import Seeds, close, relation_seeds, source_seeds, unresolved
from zoop_ai_pipeline.handoff_exposure_contracts import MAX_COMMAND, SCHEMA, Query

H = "a" * 64
UP = {"jobId": "s2-1", "inputDigest": "1" * 64}
RC1, RC2, RC3 = ("rc-" + c * 64 for c in "123")


def article(n: int) -> dict:
    return {"articleId": f"doc-{n:064x}", "articleVersion": f"{n:064x}", "documentId": f"d{n}", "documentVersion": f"{n:064x}"}


def evidence(n: int) -> dict:
    return {"id": f"ev-{n:064x}", "articleId": article(n)["articleId"], "articleVersion": article(n)["articleVersion"]}


def source_event(n: int, kind: str = "event-candidate", ref: str | None = None) -> dict:
    return {"upstream": UP, "kind": kind, "ref": ref or f"evc-{n:064x}", "mentionId": "m", "documentId": f"d{n}", "documentVersion": f"{n:064x}"}


def involves(edge: str, issue: str, company: str, evidence_ids: list, refs: list) -> dict:
    return {"id": edge, "type": "INVOLVES", "source": issue, "target": company, "evidenceIds": evidence_ids, "basis": [], "structuralPath": None,
            "sourceRefs": [{"kind": "s3-relation", "jobId": "s3-1", "id": rc} for rc in refs]}


def bundle() -> dict:
    """supply (docs 1,2) and demand (doc 3); each has one INVOLVES edge; supply also has a structural edge on RC3 and a FOLLOWS edge to demand."""
    structural = {"id": "edge-struct", "type": "STRUCTURALLY_RELATED_TO", "source": "supply", "target": "far", "evidenceIds": [evidence(2)["id"]],
                  "basis": [{"sourceRelation": {"jobId": "s3-1", "relationCandidateId": RC3}, "evidenceIds": [evidence(4)["id"]],
                             "sourceArticles": [{"articleId": article(4)["articleId"], "articleVersion": article(4)["articleVersion"]}]}],
                  "structuralPath": {"status": "unavailable", "reason": "intermediate_company_unmapped"},
                  "sourceRefs": [{"kind": "s3-relation", "jobId": "s3-1", "id": RC3}]}
    follows = {"id": "edge-follows", "type": "FOLLOWS", "source": "demand", "target": "supply", "evidenceIds": [evidence(3)["id"]], "basis": [],
               "structuralPath": None, "sourceRefs": [{"kind": "s2-comparison", "jobId": "s2-1", "id": "evc->x"}]}
    return {"sources": [{"relation": {"jobId": "s3-1", "inputDigest": H}, "upstream": {**UP, "digest": H}}],
            "articles": [article(n) for n in (1, 2, 3, 4)], "evidence": [evidence(n) for n in (1, 2, 3, 4)],
            "issues": [{"id": "supply", "sourceEvents": [source_event(1), source_event(2, "snapshot-event", "ev-snap")]},
                       {"id": "demand", "sourceEvents": [source_event(3)]}],
            "relations": [involves("edge-a", "supply", "c1", [evidence(1)["id"]], [RC1]), involves("edge-b", "demand", "c2", [evidence(3)["id"]], [RC2]),
                          structural, follows]}


def docs(*numbers: int) -> frozenset:
    return frozenset((f"d{n}", f"{n:064x}") for n in numbers)


def names(items: list) -> dict:
    return {i["id"]: i["reasons"] for i in items}


def test_cited_document_closes_issue_edges_and_only_its_own_quotes():
    found = close(bundle(), Seeds(documents=docs(1), bound=True))
    assert names(found["issues"]) == {"supply": ["source-document"]}
    assert names(found["relations"]) == {"edge-a": ["evidence", "issue"], "edge-struct": ["anchor-undetermined", "issue"], "edge-follows": ["issue"]}
    assert found["evidenceIds"] == [evidence(1)["id"]]
    assert [a["documentId"] for a in found["articles"]] == ["d1"]


def test_uncited_input_document_still_reaches_issue_but_exposes_no_other_quote():
    found = close(bundle(), Seeds(documents=docs(2)))
    assert names(found["issues"]) == {"supply": ["source-document"]}
    assert found["evidenceIds"] == [evidence(2)["id"]]
    assert names(found["relations"])["edge-struct"] == ["anchor-undetermined", "evidence", "issue"]


def test_basis_only_quote_hits_structural_edge_but_not_the_issue():
    found = close(bundle(), Seeds(documents=docs(4)))
    assert found["issues"] == []
    assert names(found["relations"]) == {"edge-struct": ["basis-evidence"]}
    assert found["evidenceIds"] == [evidence(4)["id"]]


def test_snapshot_event_and_disposition_input_reach_the_issue_without_a_document():
    assert names(close(bundle(), Seeds(snapshot_events=frozenset([("s2-1", "ev-snap")])))["issues"]) == {"supply": ["source-document"]}
    only = close(bundle(), Seeds(dispositions=frozenset([("s2-1", f"evc-{3:064x}")])))
    assert names(only["issues"]) == {"demand": ["disposition-input"]}
    assert only["articles"] == [] and only["evidenceIds"] == []


def test_snapshot_event_of_another_upstream_is_not_reached():
    assert close(bundle(), Seeds(snapshot_events=frozenset([("other", "ev-snap")]))) == {"articles": [], "issues": [], "relations": [], "evidenceIds": []}


def test_retraction_marks_shared_edge_and_last_involvement_but_never_withdraws_quotes():
    shared = bundle()
    shared["relations"][0]["sourceRefs"].append({"kind": "s3-relation", "jobId": "s3-1", "id": RC2})
    found = close(shared, relation_seeds(shared, "s3-1", RC2))
    # RC2 is one of two sources of edge-a (shared edge, listed whole) and the only source of edge-b.
    assert names(found["relations"])["edge-a"] == ["source-relation"] and names(found["relations"])["edge-b"] == ["source-relation"]
    assert names(found["issues"]) == {"demand": ["involvement-lost"], "supply": ["involvement-lost"]}
    assert found["articles"] == [] and found["evidenceIds"] == []
    assert names(found["relations"])["edge-follows"] == ["issue"]


def test_retraction_of_one_of_several_involvements_keeps_the_issue():
    two = bundle()
    two["relations"].append(involves("edge-a2", "supply", "c9", [evidence(1)["id"]], [RC3]))
    found = close(two, relation_seeds(two, "s3-1", RC1))
    assert names(found["relations"]) == {"edge-a": ["source-relation"]} | {"edge-struct": ["anchor-undetermined"]}
    assert found["issues"] == []


def test_complete_path_marks_anchor_only_for_the_affected_participant():
    complete = bundle()
    complete["relations"][2]["structuralPath"] = {"status": "complete", "companyIds": ["c1", "mid", "far"], "links": []}
    assert "anchor" in names(close(complete, relation_seeds(complete, "s3-1", RC1))["relations"])["edge-struct"]
    other = bundle()
    other["relations"][2]["structuralPath"] = {"status": "complete", "companyIds": ["c9", "mid", "far"], "links": []}
    assert "anchor" not in names(close(other, relation_seeds(other, "s3-1", RC1))["relations"])["edge-struct"]


def test_relation_pair_must_name_the_job_and_candidate_together():
    assert relation_seeds(bundle(), "s3-1", RC1).bound is True
    assert relation_seeds(bundle(), "other-job", RC1).bound is False      # same candidate id, another job: not this bundle's relation
    assert relation_seeds(bundle(), "s3-1", "rc-" + "9" * 64).bound is False
    assert relation_seeds(bundle(), "s3-1", RC3).bound is True            # structural basis counts as used


def scan(affected: bool = True, documents: frozenset = frozenset(), **over) -> dict:
    """The S4 join index entry of the bundle's S2 upstream (what `extraction.dependents` returns beside the ledger report)."""
    return {UP["jobId"]: {"inputDigest": UP["inputDigest"], "ready": True, "digest": lambda: H, "affected": affected, "documents": documents,
                          "events": set(), "topics": set(), **over}}


def listing(*entries: dict) -> dict:
    return {"jobs": list(entries)}


def test_unresolved_names_the_pinned_upstream_the_scan_cannot_prove():
    b = bundle()
    assert unresolved(b, scan()) is None
    assert unresolved(b, {}) == ("s2-1", "upstream_not_in_scanned_ledger")
    assert unresolved(b, scan(inputDigest="f" * 64)) == ("s2-1", "upstream_input_mismatch")
    assert unresolved(b, scan(ready=False)) == ("s2-1", "upstream_binding_mismatch")
    assert unresolved(b, scan(digest=lambda: "b" * 64)) == ("s2-1", "upstream_binding_mismatch")      # same job under another frozen grant revision


def test_uncited_bound_document_taints_every_used_relation_of_the_job_and_cascades():
    b = bundle()
    seeds = source_seeds(b, listing({"jobId": "s2-1", "snapshotEvents": [], "eventCandidates": []}), scan(documents=docs(9)))
    assert seeds.bound and seeds.documents == docs(9) and seeds.relations == frozenset()
    assert seeds.inputs == frozenset(("s3-1", rc) for rc in (RC1, RC2, RC3))
    found = close(b, seeds)
    # no quote or article of the bundle is touched; the issues are listed only because every INVOLVES edge is gone
    assert found["articles"] == [] and found["evidenceIds"] == []
    assert names(found["issues"]) == {"demand": ["involvement-lost"], "supply": ["involvement-lost"]}
    assert names(found["relations"]) == {"edge-a": ["upstream-input"], "edge-b": ["upstream-input"], "edge-follows": ["issue"],
                                         "edge-struct": ["anchor-undetermined", "issue", "upstream-input"]}


def test_source_change_never_uses_the_precise_retraction_reason():
    found = close(bundle(), source_seeds(bundle(), listing({"jobId": "s2-1", "snapshotEvents": [], "eventCandidates": []}), scan(documents=docs(9))))
    assert all("source-relation" not in r["reasons"] for r in found["relations"])


def test_affected_upstream_without_a_used_relation_or_touched_item_is_bound_but_not_exposed():
    empty = bundle()
    empty["relations"], empty["issues"] = [], []
    seeds = source_seeds(empty, listing({"jobId": "s2-1", "snapshotEvents": [], "eventCandidates": []}), scan(documents=docs(9)))
    found = close(empty, seeds)
    assert seeds.bound and found == {"articles": [], "issues": [], "relations": [], "evidenceIds": []}


def test_unaffected_upstream_marks_nothing():
    seeds = source_seeds(bundle(), listing(), scan(affected=False))
    assert not seeds.bound and seeds.inputs == frozenset()
    assert close(bundle(), seeds) == {"articles": [], "issues": [], "relations": [], "evidenceIds": []}


def test_snapshot_and_disposition_seeds_come_only_from_the_scanned_extraction_report():
    entry = {"jobId": "s2-1", "snapshotEvents": [{"eventId": "ev-snap"}],
             "eventCandidates": [{"eventCandidateId": "evc-a", "reasons": [{"code": "disposition_input", "targetEventId": "t"}]},
                                 {"eventCandidateId": "evc-b", "reasons": [{"code": "extracted_from"}]}]}
    seeds = source_seeds(bundle(), listing(entry, {"jobId": "other", "snapshotEvents": [{"eventId": "x"}], "eventCandidates": []}), scan())
    assert seeds.snapshot_events == frozenset([("s2-1", "ev-snap")]) and seeds.dispositions == frozenset([("s2-1", "evc-a")])


def test_closure_is_deterministic_and_independent_of_input_order():
    forward, reverse = bundle(), bundle()
    reverse["issues"].reverse()
    reverse["relations"].reverse()
    reverse["articles"].reverse()
    reverse["evidence"].reverse()
    seeds = Seeds(documents=docs(1, 2, 3, 4))
    assert json.dumps(close(forward, seeds)) == json.dumps(close(reverse, seeds))


def query(**over) -> dict:
    return {"schemaVersion": SCHEMA, "handoffIds": ["h1"], "changed": {"kind": "source", "sourceId": "s"}, **over}


@pytest.mark.parametrize("bad", [
    query(handoffIds=[]), query(handoffIds=["h"] * 2), query(handoffIds=[f"h{n}" for n in range(21)]), query(handoffIds=["bad id"]),
    query(changed={"kind": "s3-relation", "relationCandidateId": RC1}),
    query(changed={"kind": "s3-relation", "jobId": "j", "relationCandidateId": "evc-1"}),
    query(changed={"kind": "document", "documentId": "d", "documentVersion": None}),
    query(extra=1), {k: v for k, v in query().items() if k != "handoffIds"},
])
def test_query_is_closed_and_every_key_is_required(bad):
    with pytest.raises(ValidationError):
        Query.model_validate(bad)


def run(raw: bytes, *argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with mock.patch.object(sys, "argv", ["x", "--state-dir", "/nonexistent/h", *argv]), mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw))), \
            contextlib.redirect_stdout(out):
        code = handoff_exposure_cli.main()
    assert out.getvalue().count("\n") == 1
    return code, json.loads(out.getvalue())


SOURCES = ("--ingestion-state-dir", "/nonexistent/i", "--extraction-state-dir", "/nonexistent/e")
RELATION = {"kind": "s3-relation", "jobId": "j", "relationCandidateId": RC1}


@pytest.mark.parametrize("raw,argv,code", [
    (b"{", (), "input_or_configuration_invalid"),
    (b"x" * (MAX_COMMAND + 1), (), "command_input_limit"),
    (json.dumps(query()).encode(), (), "input_or_configuration_invalid"),                                  # source change without ledgers
    (json.dumps(query()).encode(), SOURCES[:2], "input_or_configuration_invalid"),                         # partial flags
    (json.dumps(query(changed=RELATION)).encode(), SOURCES, "input_or_configuration_invalid"),             # relation retraction forbids ledgers
    (json.dumps(query(handoffIds=["h", "h"])).encode(), SOURCES, "input_or_configuration_invalid"),
])
def test_bad_input_is_refused_before_any_ledger_is_opened(raw, argv, code):
    status, out = run(raw, *argv)
    assert status == 2 and out == {"schemaVersion": SCHEMA, "error": {"code": code}}


def test_missing_handoff_ledger_is_a_whole_command_error_with_no_ids():
    status, out = run(json.dumps(query(changed=RELATION)).encode())
    assert status == 2 and out == {"schemaVersion": SCHEMA, "error": {"code": "handoff_state_missing"}}


# ---------------------------------------------------------------- current-receipt integrity over a REAL frozen ledger ----------------

@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    return hs.build_world(tmp_path_factory.mktemp("zoop-exposure-receipt") / "owned")


@pytest.fixture
def rig(shared, tmp_path):
    return Rig(shared, tmp_path)


def used_pair(bundle: dict) -> dict:
    ref = next(r for e in bundle["relations"] if e["type"] == "INVOLVES" for r in e["sourceRefs"])
    return {"kind": "s3-relation", "jobId": ref["jobId"], "relationCandidateId": ref["id"]}


def expose(rig: Rig, ids: list, changed: dict) -> tuple[int, dict]:
    """The actual command over the rig's handoff ledger (a relation retraction needs no source ledger)."""
    out = io.StringIO()
    raw = json.dumps({"schemaVersion": SCHEMA, "handoffIds": ids, "changed": changed}).encode()
    with mock.patch.object(sys, "argv", ["x", "--state-dir", str(rig.state)]), mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw))), \
            contextlib.redirect_stdout(out):
        code = handoff_exposure_cli.main()
    assert out.getvalue().count("\n") == 1
    return code, json.loads(out.getvalue())


def rewrite_receipt(rig: Rig, handoff_id: str, change) -> None:
    """Replace one stored receipt exactly as a damaged or hand-edited ledger would hold it (the ledger's immutability triggers are lifted for the edit only)."""
    guards = ("immutable_handoffs_identity", "terminal_handoffs")
    originals = [rig.sql("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,))[0][0] for name in guards]
    receipt = json.loads(rig.sql("SELECT receipt FROM handoffs WHERE handoff_id=?", (handoff_id,))[0][0])
    text = json.dumps(change(receipt), sort_keys=True, separators=(",", ":"))
    try:
        for name in guards:
            rig.sql(f"DROP TRIGGER {name}")
        rig.sql("UPDATE handoffs SET receipt=? WHERE handoff_id=?", (text, handoff_id))
    finally:
        for sql in originals:
            rig.sql(sql)


def damaged(**edit):
    def change(receipt: dict) -> dict:
        return {**receipt, **edit}
    return change


def without(*names):
    return lambda receipt: {k: v for k, v in receipt.items() if k not in names}


def pin_forged(receipt: dict) -> dict:
    return {**receipt, "sources": [{**receipt["sources"][0], "reviewDigest": "0" * 64}, *receipt["sources"][1:]]}


DAMAGES = {
    "schema-only": lambda receipt: {"bundleSchema": BUNDLE_SCHEMA},
    "contentDigest": damaged(contentDigest="0" * 64),
    "bundleDigest": damaged(bundleDigest="0" * 64),
    "manifestDigest": damaged(manifestDigest="0" * 64),
    "bundleBytes": lambda receipt: {**receipt, "bundleBytes": receipt["bundleBytes"] + 1},
    "source-pin": pin_forged,
    "files": damaged(files={"canonical": "0" * 64, "decisions": "0" * 64, "bindings": "0" * 64}),
    "counts": damaged(counts={}),
    "missing-key": without("frozenAt"),
    "extra-key": damaged(unexpected=True),
    "bad-frozenAt": damaged(frozenAt="yesterday"),
}


def retyped(convert):
    """Every integer of the receipt `counts` swapped for a Python-equal value of another JSON type (True == 1, 1.0 == 1)."""
    def walk(value):
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return convert(value) if type(value) is int else value
    return lambda receipt: {**receipt, "counts": walk(receipt["counts"])}


DAMAGES |= {
    "bundleBytes-float": lambda receipt: {**receipt, "bundleBytes": float(receipt["bundleBytes"])},
    "counts-float": retyped(float),
    "counts-bool": retyped(lambda n: bool(n) if n in (0, 1) else n),
}


def test_intact_current_receipt_is_reported_and_the_report_carries_no_receipt_time(rig):
    bundle = rig.bundle("h1")
    code, out = expose(rig, ["h1"], used_pair(bundle))
    assert code == 0 and out["handoffs"][0]["handoffId"] == "h1" and out["handoffs"][0]["bound"] is True
    assert "frozenAt" not in json.dumps(out)


@pytest.mark.parametrize("damage", sorted(DAMAGES))
def test_current_receipt_that_does_not_match_row_manifest_and_bundle_refuses_the_whole_report(rig, damage):
    bundle = rig.bundle("h1")
    rewrite_receipt(rig, "h1", DAMAGES[damage])
    code, out = expose(rig, ["h1"], used_pair(bundle))
    assert code == 2 and out == {"schemaVersion": SCHEMA, "error": {"code": "handoff_selection_unmappable",
                                                                    "detail": {"handoffs": [{"handoffId": "h1", "code": "handoff_state_invalid"}]}}}, out


def test_one_bad_receipt_beside_a_good_and_a_history_handoff_yields_no_report_and_lists_only_the_failing(rig):
    bundle = rig.bundle("h1")
    rig.freeze("h2")
    hs.plant_legacy_handoff(rig.state, rig.manifest("old"), bundle, schema=hs.BUNDLE_2, artifact="garbage")
    rewrite_receipt(rig, "h2", DAMAGES["schema-only"])
    code, out = expose(rig, ["h1", "h2", "old"], used_pair(bundle))
    assert code == 2 and "handoffs" not in out and out["error"]["code"] == "handoff_selection_unmappable"
    assert out["error"]["detail"]["handoffs"] == [{"handoffId": "h2", "code": "handoff_state_invalid"}, {"handoffId": "old", "code": "handoff_contract_changed"}]


def test_a_history_row_is_still_classified_from_its_receipt_alone_and_its_artifact_is_never_read(rig):
    bundle = rig.bundle("h1")
    hs.plant_legacy_handoff(rig.state, rig.manifest("old"), bundle, schema=hs.BUNDLE_2, artifact="garbage")
    code, out = expose(rig, ["old"], used_pair(bundle))
    assert code == 2 and out["error"]["detail"] == {"handoffs": [{"handoffId": "old", "code": "handoff_contract_changed"}]}
