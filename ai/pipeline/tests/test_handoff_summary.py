"""Issue summaries in the public graph handoff (bundle `-7`, decisions `-3`): a produced summary job result is PINNED by the operator's decisions, `freeze` reads it from the
separate `zoop-ai-issue-summary` ledger (read-only), `export` takes it from the frozen artifact, and the validator recomputes the whole zero-call decision table.

The summary jobs here are REAL authored-replay jobs of the installed engine over the authored world, run in-process through the handoff's own planner seam (`plan_summary_input`);
the claims are written by hand in `scripts/graph_handoff_smoke.py` (`SUMMARY_CLAIMS`). No model, provider, key or network.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from scripts import graph_handoff_smoke as hs
from scripts.ingestion_smoke import json_bytes
from scripts.relation_smoke import tree
from tests.test_handoff import Rig, error, factory_of, rehashed, rig, shared, supply_of  # noqa: F401
from zoop_ai_pipeline import issue_summary as isum
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure
from zoop_ai_pipeline.graph_projection_contracts import Withheld
from zoop_ai_pipeline.handoff import FrozenSummaries, HandoffPaths, LedgerSummaries, plan_summary_input
from zoop_ai_pipeline.handoff_contracts import Manifest, validate_bundle
from zoop_ai_pipeline.issue_summary_contracts import basis_digest, summary_basis

NOT_REQUESTED = {"status": "unavailable", "code": "not-requested", "source": None}
PENDING = {"status": "unavailable", "code": "temporal-review-pending", "source": None}
REPLAY = ("replay", "authored-test")
NO_CALLS = {"providerCalls": 0, "modelCalls": 0}


def paths_of(rig: Rig) -> HandoffPaths:
    return HandoffPaths(rig.root / "relation", rig.root / "extraction", rig.root / "ingestion", rig.sources, rig.root / "canonical.json", rig.root / "decisions.json",
                        rig.root / "bindings.json")


def run_job(rig: Rig, base: Path, first: dict, *, decision: str = "supported", job: str = "isum-1"):
    """An authored-replay summary job over the rig's UNPINNED handoff `h0` (its bundle `first` is the basis), run in-process through the real planner seam."""
    paths = paths_of(rig)
    ledger = base / "summary"
    store = isum.Store(ledger, paths.relation, paths.extraction, paths.ingestion)
    try:
        engine = isum.Engine(store, lambda manifest, issue_id: plan_summary_input(paths, manifest, issue_id))
        fixture = hs.summary_fixture(rig.world, first, hs.SUPPLY, hs.SUMMARY_CLAIMS, [decision])
        request = isum.Submit.model_validate({"schemaVersion": "zoop-issue-summary-1", "jobId": job, "issueId": hs.SUPPLY, "mode": "replay", "manifest": rig.manifest("h0")})
        out = engine.run(request, isum.Fixtures(json_bytes(fixture)))
    finally:
        store.close()
    assert out["state"] == "ready" and out["usage"]["replayCalls"] == 2 and out["usage"]["providerCalls"] == 0, out
    found = isum.load_result(ledger, paths.relation, paths.extraction, paths.ingestion, job_id=job)
    return ledger, {"jobId": found.job_id, "inputDigest": found.input_digest, "resultDigest": found.result_digest}, found


@pytest.fixture(scope="module")
def pinned(shared, tmp_path_factory):
    """One finished (available) summary job of the supply issue; the factory issue carries a HOLD period verdict (deterministic `temporal-review-pending`)."""
    base = tmp_path_factory.mktemp("zoop-handoff-summary")
    rig = Rig(shared, base)
    verdicts = {"issue:factory": [hs.field_verdict(shared, "b", "m-b", "period", "2026Q4", "HOLD", "ambiguous", [hs.PERIOD_B])]}
    rig.docs["decisions"] = hs.decisions_doc(shared, verdicts=verdicts)
    rig.write()
    first = rig.bundle("h0")
    ledger, pin, found = run_job(rig, base, first)
    return SimpleNamespace(ledger=ledger, pin=pin, found=found, first=first, verdicts=verdicts)


def pinned_rig(shared, tmp_path: Path, pinned) -> Rig:
    """A private rig whose decisions pin the supply issue's finished job (and carry the factory issue's HOLD verdict)."""
    rig = Rig(shared, tmp_path)
    rig.docs["decisions"] = hs.decisions_doc(shared, verdicts=pinned.verdicts, summaries={"issue:supply": pinned.pin})
    rig.write()
    return rig


@pytest.fixture(scope="module")
def pinned_bundle(shared, tmp_path_factory, pinned):
    rig = pinned_rig(shared, tmp_path_factory.mktemp("zoop-handoff-summary-bundle"), pinned)
    rig.run("freeze", rig.manifest("h1"), summaries=pinned.ledger)
    out = rig.run("export", rig.sel("h1"))
    assert out["delivery"]["status"] == "current"
    return out["bundle"]


# ---------------------------------------------------------------- the zero-call table (no pin) ---------------------------------------------

def test_an_unpinned_handoff_states_not_requested_for_every_issue_and_needs_no_summary_ledger(rig):
    bundle = rig.bundle()
    assert {i["id"]: i["summary"] for i in bundle["issues"]} == {hs.SUPPLY: NOT_REQUESTED, hs.FACTORY: NOT_REQUESTED}
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8" and bundle["policy"]["issueSummary"] == "zoop-issue-summary-policy-1"
    validate_bundle(bundle)


def test_any_hold_or_reject_verdict_on_an_issue_leaves_temporal_review_pending_even_when_it_withholds_no_headline(rig):
    world = rig.world
    rig.docs["decisions"] = hs.decisions_doc(world, verdicts={"issue:supply": [hs.field_verdict(world, "a2", "m-a2", "eventTime", "2026-09-30", "HOLD", "unstated")]})
    rig.write()
    bundle = rig.bundle()
    supply = supply_of(bundle)
    assert supply["fieldProvenance"]["withheld"] == [] and supply["eventTime"] == "2026-09-30"          # a non-representative HOLD withholds nothing ...
    assert supply["summary"] == PENDING and factory_of(bundle)["summary"] == NOT_REQUESTED               # ... but no summary text can exist for that issue
    validate_bundle(bundle)


def test_an_allow_verdict_does_not_hold_the_issue(rig):
    world = rig.world
    rig.docs["decisions"] = hs.decisions_doc(world, verdicts={"issue:supply": [hs.field_verdict(world, "a", "m-a", "period", "2026Q3", "ALLOW", "stated", [hs.PERIOD_A])]})
    rig.write()
    assert supply_of(rig.bundle())["summary"] == NOT_REQUESTED


def test_the_hand_reviewed_world_holds_both_issues(rig):
    rig.docs["decisions"] = hs.reviewed(rig.world, published_time=None)
    rig.write()
    bundle = rig.bundle()
    assert [i["summary"] for i in bundle["issues"]] == [PENDING, PENDING]
    validate_bundle(bundle)


def test_the_basis_rests_on_the_uncited_quote_too(shared, pinned):
    """The one claim cites one quote; the summary still rests on BOTH quotes of the issue (a second article), so the uncited one is in the pinned basis and not in the summary's evidence."""
    uncited, cited = hs.evidence_id(shared, "a2", hs.EVT_A2), hs.evidence_id(shared, "a", hs.EVT_A)
    supply = next(i for i in pinned.first["issues"] if i["id"] == hs.SUPPLY)
    basis = summary_basis(supply, {e["id"]: e for e in pinned.first["evidence"]}, {(a["articleId"], a["articleVersion"]): a for a in pinned.first["articles"]})
    assert {q["evidenceId"] for q in basis["quotes"]} == {uncited, cited} and len(hs.SUMMARY_CLAIMS) == 1
    assert pinned.found.summary["evidenceIds"] == [cited] and uncited not in pinned.found.summary["evidenceIds"]
    assert pinned.found.summary["source"]["basisDigest"] == basis_digest(basis)


# ---------------------------------------------------------------- freeze reads the pinned result, export the frozen artifact ----------------

def test_the_pinned_result_is_carried_exactly_and_export_works_without_the_summary_ledger_or_any_call(shared, tmp_path, pinned):
    rig = pinned_rig(shared, tmp_path, pinned)
    before = hs.ledger_snapshot(pinned.ledger)
    frozen = rig.run("freeze", rig.manifest("h1"), summaries=pinned.ledger)
    assert frozen["state"] == "ready" and frozen["usage"] == NO_CALLS
    out = rig.run("export", rig.sel("h1"))
    assert out["delivery"]["status"] == "current" and out["usage"] == NO_CALLS
    bundle = out["bundle"]
    supply = supply_of(bundle)["summary"]
    assert supply == pinned.found.summary and supply["status"] == "available"
    assert supply["text"] == "\n".join(text for text, _, _ in hs.SUMMARY_CLAIMS)
    assert [c["text"] for c in supply["claims"]] == [text for text, _, _ in hs.SUMMARY_CLAIMS]
    assert supply["evidenceIds"] == sorted(hs.evidence_id(shared, name, quote) for _, name, quote in hs.SUMMARY_CLAIMS)
    assert (supply["source"]["jobId"], supply["source"]["inputDigest"], supply["source"]["resultDigest"]) == (pinned.pin["jobId"], pinned.pin["inputDigest"],
                                                                                                             pinned.pin["resultDigest"])
    assert supply["producer"]["kind"] == supply["verifier"]["kind"] == "authored-replay"
    assert factory_of(bundle)["summary"] == PENDING
    validate_bundle(bundle)
    assert hs.canonical(bundle).encode() == (rig.state / "bundles" / f"{frozen['receipt']['bundleDigest']}.json").read_bytes()
    assert hs.ledger_snapshot(pinned.ledger) == before          # freeze and export never write the summary ledger

    moved = tmp_path / "ledger-moved"
    pinned.ledger.rename(moved)
    try:
        assert rig.run("export", rig.sel("h1"))["bundle"] == bundle          # export reads the frozen artifact, not the ledger
    finally:
        moved.rename(pinned.ledger)


def test_the_summary_ledger_flag_belongs_to_freeze_only(rig, tmp_path):
    rig.freeze()
    for command in ("export", "inspect", "recover"):
        error(rig.run(command, rig.sel(), expected=2, summaries=tmp_path / "ledger"), "input_or_configuration_invalid")


def refusals(shared, pinned) -> dict:
    """name -> (code, decisions options, bindings change or None, whether the ledger flag is given)."""
    pin, supply = pinned.pin, {"issue:supply": pinned.pin}
    held = {**pinned.verdicts, "issue:supply": [hs.field_verdict(shared, "a", "m-a", "period", "2026Q3", "HOLD", "ambiguous", [hs.PERIOD_A])]}

    def rebind(doc: dict) -> None:
        next(b for b in doc["bindings"] if b["documentId"] == shared.refs["a2"]["documentId"])["articleId"] = "doc-" + "5" * 64

    return {
        "a pin without the ledger flag": ("issue_summary_state_missing", {"summaries": supply}, None, False),
        "the ledger flag without any pin": ("issue_summary_state_unused", {"summaries": None}, None, True),
        "a wrong result digest": ("issue_summary_pin_mismatch", {"summaries": {"issue:supply": {**pin, "resultDigest": "0" * 64}}}, None, True),
        "a wrong input digest": ("issue_summary_pin_mismatch", {"summaries": {"issue:supply": {**pin, "inputDigest": "0" * 64}}}, None, True),
        "an unknown job": ("issue_summary_not_found", {"summaries": {"issue:supply": {**pin, "jobId": "no-such-summary-job"}}}, None, True),
        "a pinned issue that is now held": ("issue_summary_temporal_review_pending", {"summaries": supply, "verdicts": held}, None, True),
        "a pinned issue the freeze did not publish": ("issue_summary_issue_not_public", {"summaries": {**supply, "issue:overseas": pin}}, None, True),
        "a pin whose basis the current bindings no longer give": ("issue_summary_basis_changed", {"summaries": supply}, rebind, True),
    }


REFUSALS = ("a pin without the ledger flag", "the ledger flag without any pin", "a wrong result digest", "a wrong input digest", "an unknown job", "a pinned issue that is now held",
            "a pinned issue the freeze did not publish", "a pin whose basis the current bindings no longer give")


@pytest.mark.parametrize("name", REFUSALS)
def test_a_pin_the_handoff_cannot_honor_refuses_the_whole_freeze_and_writes_nothing(shared, tmp_path, pinned, name):
    code, options, rebind, flag = refusals(shared, pinned)[name]
    rig = Rig(shared, tmp_path)
    rig.docs["decisions"] = hs.decisions_doc(shared, verdicts=options.get("verdicts", pinned.verdicts), summaries=options["summaries"])
    if rebind is not None:
        rebind(rig.docs["bindings"])
    rig.write()
    before = hs.ledger_snapshot(pinned.ledger)
    refused = rig.run("freeze", rig.manifest("h1"), expected=2, summaries=pinned.ledger if flag else None)
    assert refused["error"]["code"] == code, (name, refused)
    assert rig.rows() == 0, f"{name}: a refused freeze left a handoff row"
    assert hs.ledger_snapshot(pinned.ledger) == before


# ---------------------------------------------------------------- the validator recomputes the table -------------------------------------

@pytest.mark.parametrize("name", list(hs.summary_mutations()))
def test_the_validator_recomputes_the_summary_and_refuses_each_tamper_at_its_own_rule(pinned_bundle, name):
    change, at = hs.summary_mutations()[name]
    validate_bundle(pinned_bundle)
    with pytest.raises(ExtractionFailure) as exc:
        validate_bundle(rehashed(pinned_bundle, change))
    assert exc.value.code == "handoff_bundle_invalid" and exc.value.detail == {"at": at}, name


# ---------------------------------------------------------------- the two summary sources (pure, mocked ledger) ---------------------------

def source_world():
    basis = {"policy": "p", "issueId": "i", "title": "t", "quotes": [], "articles": []}
    source = {"jobId": "j", "inputDigest": "1" * 64, "resultDigest": "2" * 64, "basisDigest": basis_digest(basis)}
    summary = {"status": "unavailable", "code": "verifier-hold", "source": source}
    pin = SimpleNamespace(job_id="j", input_digest="1" * 64, result_digest="2" * 64)
    return basis, summary, pin


def test_the_frozen_summaries_honor_only_the_pinned_result_for_the_recomputed_basis_and_refuse_as_withheld():
    basis, summary, pin = source_world()
    frozen = FrozenSummaries({"issues": [{"id": "i", "summary": summary}]})
    assert FrozenSummaries.refuse is Withheld
    got = frozen.result({"id": "i"}, basis, pin, REPLAY, "synthetic")
    assert got == summary and got is not summary
    for other, code in ((SimpleNamespace(job_id="x", input_digest="1" * 64, result_digest="2" * 64), "issue_summary_pin_mismatch"),
                        (SimpleNamespace(job_id="j", input_digest="3" * 64, result_digest="2" * 64), "issue_summary_pin_mismatch"),
                        (SimpleNamespace(job_id="j", input_digest="1" * 64, result_digest="4" * 64), "issue_summary_pin_mismatch")):
        with pytest.raises(Withheld) as exc:
            frozen.result({"id": "i"}, basis, other, REPLAY, "synthetic")
        assert exc.value.code == code
    with pytest.raises(Withheld) as exc:
        frozen.result({"id": "i"}, {**basis, "title": "another"}, pin, REPLAY, "synthetic")
    assert exc.value.code == "issue_summary_basis_changed"
    with pytest.raises(Withheld) as exc:
        frozen.result({"id": "unknown"}, basis, pin, REPLAY, "synthetic")
    assert exc.value.code == "handoff_content_changed"
    with pytest.raises(Withheld) as exc:          # the artifact holds a deterministic summary (no job) where the decisions now pin one
        FrozenSummaries({"issues": [{"id": "i", "summary": NOT_REQUESTED}]}).result({"id": "i"}, basis, pin, REPLAY, "synthetic")
    assert exc.value.code == "issue_summary_pin_mismatch"


def test_the_ledger_summaries_require_the_exact_pin_issue_mode_source_kind_and_basis_and_refuse_strictly():
    basis, summary, pin = source_world()
    found = isum.ReadyResult("j", "1" * 64, "2" * 64, "i", REPLAY, "synthetic", summary)
    ledger = LedgerSummaries(Path("/nonexistent-summary-ledger"))
    assert LedgerSummaries.refuse is ExtractionFailure

    def code_of(found_result, *, issue="i", execution=REPLAY, source_kind="synthetic", basis_=basis, pin_=pin) -> str:
        with mock.patch.object(isum, "load_result", return_value=found_result):
            with pytest.raises(ExtractionFailure) as exc:
                ledger.result({"id": issue}, basis_, pin_, execution, source_kind)
        return exc.value.code

    with mock.patch.object(isum, "load_result", return_value=found):
        got = ledger.result({"id": "i"}, basis, pin, REPLAY, "synthetic")
    assert got == summary and got is not summary
    assert code_of(found, issue="another") == "issue_summary_pin_mismatch"
    assert code_of(found, pin_=SimpleNamespace(job_id="j", input_digest="1" * 64, result_digest="9" * 64)) == "issue_summary_pin_mismatch"
    assert code_of(found, execution=("live", "provider")) == "provenance_mode_conflict"
    assert code_of(found, source_kind="actual") == "provenance_conflict"
    assert code_of(found, basis_={**basis, "title": "another"}) == "issue_summary_basis_changed"
    other_source = {**summary, "source": {**summary["source"], "resultDigest": "8" * 64}}
    assert code_of(isum.ReadyResult("j", "1" * 64, "2" * 64, "i", REPLAY, "synthetic", other_source)) == "issue_summary_pin_mismatch"
    with mock.patch.object(isum, "load_result", side_effect=ExtractionFailure("issue_summary_not_ready")):          # a failed or unfinished job is never a result
        with pytest.raises(ExtractionFailure) as exc:
            ledger.result({"id": "i"}, basis, pin, REPLAY, "synthetic")
    assert exc.value.code == "issue_summary_not_ready"


# ---------------------------------------------------------------- the read-only planned data a summary job consumes ------------------------

def test_the_planned_input_is_read_only_ignores_pins_and_is_the_public_issue_without_its_summary(shared, tmp_path, pinned):
    rig = pinned_rig(shared, tmp_path, pinned)
    manifest = Manifest.model_validate(rig.manifest("h0"))
    before = {name: tree(rig.root / name) for name in ("ingestion", "extraction", "relation")}
    planned = plan_summary_input(paths_of(rig), manifest, hs.SUPPLY)          # the supply decision pins a result: it is neither read nor required
    assert planned.handoff_id == "h0" and planned.issue["id"] == hs.SUPPLY and "summary" not in planned.issue
    assert planned.execution == REPLAY and planned.source_kind == "synthetic"
    assert set(planned.issue["evidenceIds"]) <= set(planned.evidence) and len(planned.articles) == 3
    texts = {key: entries[0][1]["document"]["text"] for key, entries in planned.documents.items()}
    assert set(texts.values()) == {art.body for art in shared.art.values()}
    quoted = {texts[(planned.evidence[i]["source"]["documentId"], planned.evidence[i]["source"]["documentVersion"])][planned.evidence[i]["start"]:planned.evidence[i]["end"]]
              for mention in planned.issue["mentions"] for i in mention["evidenceIds"]}
    assert quoted == {hs.EVT_A, hs.EVT_A2}          # the exact quotes a summary job slices from the current ingestion exports
    assert {name: tree(rig.root / name) for name in ("ingestion", "extraction", "relation")} == before and rig.rows() == 0
    with pytest.raises(ExtractionFailure) as exc:
        plan_summary_input(paths_of(rig), manifest, "issue:no-such-issue")
    assert exc.value.code == "issue_not_public"
    rig.docs["decisions"] = hs.decisions_doc(shared)          # an operator file that is no longer the manifest's pin is refused like a freeze would
    rig.write()
    with pytest.raises(ExtractionFailure) as exc:
        plan_summary_input(paths_of(rig), manifest, hs.SUPPLY)
    assert exc.value.code == "operator_file_pin_mismatch"
