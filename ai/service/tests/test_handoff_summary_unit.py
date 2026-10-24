"""The issue SUMMARY (`issues[].summary`, bundle `-7`) of the closed bundle model, without any child process.

The service recomputes the summary decision table from the bundle itself (the producer's `issue_summary_contracts`): the exact input basis and its digest, the
deterministic temporal-review and input-size codes, the claim/result identity (`resultVersion`, `source.resultDigest`) and the execution-mode provenance of the producer and
verifier. These tests pin that behaviour with authored synthetic data: a hand-written expected basis and digest (never derived by the code under test), every legal outcome,
rich multi-quote summaries and one illegal value per rule. An old schema, a dropped summary or a stale basis is never read as current.

`pipeline_tests/test_handoff_real_cli.py` runs the same rules against bundles the INSTALLED producer wrote and checks the producer's own validator accepts the fixtures used
here.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from handoff_support import SUMMARY_BASIS_CHANGES as BASIS_CHANGES
from handoff_support import SUMMARY_NOT_BASIS as NOT_BASIS
from handoff_support import SUMMARY_TAMPER as TAMPER
from handoff_support import HIDDEN_EVIDENCE as HIDDEN
from handoff_support import (SUMMARY_TIME_ACCEPTED, SUMMARY_TIME_REFUSED, assemble, basis_of, edit_claim_text, full_bundle, live_bundle, reseal, resummarize, with_quotes,
                             with_side_evidence)
from handoff_support import issue_summary as summary
from support import canonical
from zoop_ai_service.handoff_doc import example_bundle, summary_of
from zoop_ai_service.handoff_wire import MAX_QUOTES, Bundle, basis_digest, result_version, summary_time_valid

OUTCOMES = ("available", "not-requested", "temporal-review-pending", "verifier-hold", "producer-invalid", "verifier-reject")
JOB_CODES = ("producer-invalid", "verifier-hold", "verifier-reject")


def accepted(bundle: dict[str, Any]) -> None:
    parsed = Bundle.model_validate(bundle)
    assert parsed.wire() == bundle and canonical(parsed.wire()) == canonical(bundle)


def refused(bundle: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Bundle.model_validate(bundle)


def sha(value: Any) -> str:
    """An independent digest: the canonical JSON of the producer, written out here rather than imported from the code under test."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# ---- every legal outcome, with a hand-written basis --------------------------------------------------------------------------------

@pytest.mark.parametrize("outcome", OUTCOMES)
def test_every_legal_summary_outcome_is_accepted_and_relayed_exactly(outcome):
    bundle = example_bundle(outcome)
    accepted(bundle)
    accepted(json.loads(json.dumps(bundle, sort_keys=True)))        # key order is never part of the contract
    value = summary(bundle)
    assert (value["status"], value.get("code")) == (("available", None) if outcome == "available" else ("unavailable", outcome))
    assert (value["source"] is None) == (outcome in ("not-requested", "temporal-review-pending", "input-too-large"))


def test_the_example_basis_and_every_digest_equal_a_hand_written_expectation():
    bundle = example_bundle()
    evidence, article = bundle["evidence"][0], bundle["articles"][0]
    expected = {"policy": "zoop-issue-summary-policy-1", "issueId": "issue:synthetic-supply", "title": "합성 공급 계약",
                "quotes": [{"evidenceId": evidence["id"], "articleId": "doc-" + "c" * 64, "articleVersion": "a" * 64, "start": 12, "end": 48, "quoteSha256": "e" * 64,
                            "context": "report"}],
                "articles": [{"articleId": "doc-" + "c" * 64, "articleVersion": "a" * 64, "documentId": "synthetic-doc-1", "documentVersion": "a" * 64, "textSha256": "5" * 64}]}
    assert basis_of(bundle) == expected and article["articleId"] == "doc-" + "c" * 64
    value = summary(bundle)
    assert value["source"]["basisDigest"] == basis_digest(expected) == sha(expected)
    assert value["resultVersion"] == "isr-" + sha({"basisDigest": sha(expected), "claims": value["claims"]})
    body = {key: item for key, item in value.items() if key != "source"}
    source = value["source"]
    assert source["resultDigest"] == sha({"jobId": source["jobId"], "inputDigest": source["inputDigest"], "basisDigest": sha(expected), "result": body})
    for code in JOB_CODES:                                           # a job-coded value pins the same basis and its own body
        coded = summary(example_bundle(code))
        assert coded["source"]["basisDigest"] == sha(expected)
        assert coded["source"]["resultDigest"] == sha({"jobId": coded["source"]["jobId"], "inputDigest": coded["source"]["inputDigest"], "basisDigest": sha(expected),
                                                        "result": {"status": "unavailable", "code": code}})


def test_the_available_example_is_a_rich_nonempty_summary_of_the_issue():
    value = summary(example_bundle())
    quotes = {q["evidenceId"] for q in basis_of(example_bundle())["quotes"]}
    assert value["text"] == "\n".join(c["text"] for c in value["claims"]) and len(value["claims"]) == 3
    assert [c["claimId"] for c in value["claims"]] == ["c1", "c2", "c3"] and value["language"] == "ko" and value["resultVersion"].startswith("isr-")
    assert all(any("\uac00" <= ch <= "\ud7a3" for ch in c["text"]) and 1 <= len(c["text"]) <= 280 for c in value["claims"])
    assert value["evidenceIds"] == sorted({i for c in value["claims"] for i in c["evidenceIds"]}) and set(value["evidenceIds"]) <= quotes
    assert (value["producer"]["kind"], value["producer"]["model"], value["verifier"]["kind"]) == ("authored-replay", None, "authored-replay")


def test_a_multi_quote_summary_cites_the_union_of_its_claims_and_every_quote_is_an_input():
    bundle = resummarize(with_quotes(example_bundle(), 4))
    accepted(bundle)
    basis = basis_of(bundle)
    quotes = [q["evidenceId"] for q in basis["quotes"]]
    assert len(quotes) == 5 and quotes == sorted(quotes) and summary(bundle)["claims"][2]["evidenceIds"] == quotes
    assert summary(bundle)["evidenceIds"] == sorted({summary(bundle)["claims"][0]["evidenceIds"][0], summary(bundle)["claims"][1]["evidenceIds"][0], *quotes})
    assert len(bundle["issues"][0]["evidenceIds"]) == 5


# ---- an old schema, a dropped summary or a dropped policy is never current ---------------------------------------------------------

OLD_OR_DROPPED = {
    "schema-6": lambda b: b.update(schemaVersion="zoop-graph-handoff-bundle-6"),
    "summary-dropped": lambda b: b["issues"][0].pop("summary"),
    "summary-null": lambda b: b["issues"][0].update(summary=None),
    "summary-empty-object": lambda b: b["issues"][0].update(summary={}),
    "summary-status-only": lambda b: b["issues"][0].update(summary={"status": "unavailable"}),
    "policy-dropped": lambda b: b["policy"].pop("issueSummary"),
    "policy-other": lambda b: b["policy"].update(issueSummary="zoop-issue-summary-policy-2"),
    "policy-null": lambda b: b["policy"].update(issueSummary=None),
    "schema-6-shape": lambda b: (b.update(schemaVersion="zoop-graph-handoff-bundle-6"), b["policy"].pop("issueSummary"), b["issues"][0].pop("summary")),
}


@pytest.mark.parametrize("name", sorted(OLD_OR_DROPPED))
def test_an_old_schema_a_dropped_summary_or_a_dropped_policy_is_refused(name):
    for bundle in (example_bundle(), full_bundle()):
        OLD_OR_DROPPED[name](bundle)
        refused(bundle)


# ---- tampered content ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(TAMPER))
def test_a_tampered_available_summary_is_refused(name):
    bundle = example_bundle()
    TAMPER[name](bundle)
    refused(bundle)


def test_each_identity_is_recomputed_so_a_changed_claim_with_its_identities_recomputed_is_a_different_valid_summary():
    """The check is a recomputation, not an allowlist of one authored text: another claim set whose version and result digest were derived for it is legal."""
    bundle = example_bundle()
    summary(bundle).update(assemble(bundle, ["합성기업이 공급 계약을 발표했다.", "계약은 2026년 3분기 국내 시장 중심이다."]))
    accepted(bundle)
    stale = copy.deepcopy(bundle)
    edit_claim_text(stale, 1, "계약은 해외 시장 중심이다.")        # the same edit without recomputing the identities
    refused(stale)
    edit_claim_text(bundle, 1, "계약은 해외 시장 중심이다.")
    summary(bundle)["resultVersion"] = result_version(summary(bundle)["source"]["basisDigest"], summary(bundle)["claims"])
    refused(bundle)                                              # a version without the result digest is still refused
    reseal(bundle)
    accepted(bundle)


@pytest.mark.parametrize("texts,legal", [
    (["가" * 280] * 5, True),                                                     # 5 claims of 280 code points: the largest legal summary
    (["가" * 281], False),
    (["😀" + "가" * 279], True),                                                   # 280 code points, 281 UTF-16 units: lengths are code points
    (["😀" + "가" * 280], False),
    (["가"], True),
    (["a" * 279 + "가"], True),
    (["a" * 280], False),                                                         # no Hangul syllable
    (["\ud7a3"], True), (["\uabff"], False),                                      # the syllable block ends at U+D7A3; U+ABFF is no Hangul syllable
    ([" " * 279 + "가"], True),
])
def test_claim_text_length_and_hangul_boundaries_are_exact(texts, legal):
    bundle = example_bundle()
    summary(bundle).update(assemble(bundle, texts))
    if legal:
        accepted(bundle)
    else:
        refused(bundle)


# ---- hidden ids: only the issue's own input quotes may be cited -------------------------------------------------------------------------

@pytest.mark.parametrize("where", ("geography", "verdict"))
def test_geography_only_and_verdict_only_evidence_is_not_an_input_and_cannot_be_cited(where):
    bundle = example_bundle()
    side = with_side_evidence(bundle, where)
    assert side in bundle["issues"][0]["evidenceIds"] and side not in {q["evidenceId"] for q in basis_of(bundle)["quotes"]}
    accepted(bundle)                                                  # the basis, hence the pinned summary, is unchanged by evidence no mention cites
    assert summary(bundle)["source"]["basisDigest"] == basis_digest(basis_of(example_bundle()))
    cited = copy.deepcopy(bundle)
    summary(cited).update(assemble(cited, ["합성기업이 공급 계약을 발표했다."], [[side]]))
    refused(cited)                                                    # recomputed identities, but the cited id is an evidence id of the issue and not an input quote
    mixed = copy.deepcopy(bundle)
    quote = basis_of(mixed)["quotes"][0]["evidenceId"]
    summary(mixed).update(assemble(mixed, ["합성기업이 공급 계약을 발표했다."], [[quote, side]]))
    refused(mixed)


def test_a_claim_naming_an_evidence_id_the_bundle_does_not_hold_is_refused_even_with_its_identities_recomputed():
    bundle = example_bundle()
    summary(bundle).update(assemble(bundle, ["합성기업이 공급 계약을 발표했다."], [[HIDDEN]]))
    refused(bundle)


def test_a_mention_citing_evidence_the_bundle_does_not_hold_leaves_no_basis_and_is_refused():
    bundle = example_bundle()
    bundle["issues"][0]["mentions"][0]["evidenceIds"] = [HIDDEN]
    refused(bundle)


# ---- a wrong basis ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("outcome", ("available", "verifier-hold", "producer-invalid", "verifier-reject"))
@pytest.mark.parametrize("name", sorted(BASIS_CHANGES))
def test_a_summary_pinned_to_another_basis_is_refused_and_accepted_again_only_when_re_pinned(name, outcome):
    bundle = example_bundle(outcome)
    BASIS_CHANGES[name](bundle)
    refused(bundle)
    repinned = resummarize(bundle)
    accepted(repinned)
    assert summary(repinned)["source"]["basisDigest"] != summary(example_bundle(outcome))["source"]["basisDigest"]


@pytest.mark.parametrize("name", sorted(NOT_BASIS))
def test_what_a_summary_does_not_rest_on_does_not_invalidate_it(name):
    bundle = example_bundle()
    NOT_BASIS[name](bundle)
    accepted(bundle)


def test_a_quote_is_background_only_when_every_mention_citing_it_is_background():
    bundle = full_bundle()                                            # two mentions citing the same quote: the first is not a background mention, the second is
    bundle["issues"][0]["fieldVerdicts"] = [v for v in bundle["issues"][0]["fieldVerdicts"] if v["decision"] == "ALLOW"]   # the HOLD that made it `temporal-review-pending` is gone
    mentions = bundle["issues"][0]["mentions"]
    assert [m["background"] for m in mentions] == [False, True] and mentions[0]["evidenceIds"] == mentions[1]["evidenceIds"]
    assert [q["context"] for q in basis_of(bundle)["quotes"]] == ["report"]
    summary_ = summary_of(bundle, "available")
    bundle["issues"][0]["summary"] = summary_
    accepted(bundle)
    mentions[0]["background"] = True
    assert [q["context"] for q in basis_of(bundle)["quotes"]] == ["background"]
    refused(bundle)                                                   # every citing mention is now background: the basis (and its digest) changed
    accepted(resummarize(bundle))
    assert summary(bundle)["source"]["basisDigest"] != summary_["source"]["basisDigest"]


# ---- the deterministic table: temporal review first, then the input size ------------------------------------------------------------

def held_with(decision: str, reason: str) -> dict[str, Any]:
    bundle = example_bundle()
    bundle["issues"][0]["fieldVerdicts"][0].update(decision=decision, reasonCode=reason)
    return bundle


def test_a_held_issue_carries_exactly_temporal_review_pending_and_nothing_else():
    held = example_bundle("temporal-review-pending")
    accepted(held)
    assert summary(held) == {"status": "unavailable", "code": "temporal-review-pending", "source": None}
    assert held["issues"][0]["eventTime"] is None and held["issues"][0]["fieldProvenance"]["withheld"] == ["eventTime"]
    for outcome in ("available", "not-requested", "input-too-large", *JOB_CODES):
        other = copy.deepcopy(held)
        other["issues"][0]["summary"] = summary_of(other, outcome)    # a perfectly derived value for this basis, but the issue has no summary at all
        refused(other)


@pytest.mark.parametrize("decision,reason", [("HOLD", "ambiguous"), ("REJECT", "contradicted")])
def test_any_hold_or_reject_verdict_makes_the_summary_temporal_review_pending(decision, reason):
    bundle = held_with(decision, reason)
    assert summary(bundle)["status"] == "available"
    refused(bundle)                                                   # the available summary of the unheld issue may not stay
    bundle["issues"][0]["summary"] = summary_of(bundle, "temporal-review-pending")
    accepted(bundle)


def test_a_hold_on_a_non_selected_mention_still_leaves_the_whole_issue_without_a_summary():
    bundle = full_bundle()
    assert [v["decision"] for v in bundle["issues"][0]["fieldVerdicts"]] == ["ALLOW", "HOLD"] and bundle["issues"][0]["fieldProvenance"]["withheld"] == []
    assert summary(bundle) == {"status": "unavailable", "code": "temporal-review-pending", "source": None}
    accepted(bundle)
    for outcome in ("available", "not-requested"):
        other = copy.deepcopy(bundle)
        other["issues"][0]["summary"] = summary_of(other, outcome)
        refused(other)


def test_a_deterministic_code_is_legal_only_while_its_condition_holds():
    bundle = example_bundle()
    accepted(bundle)
    for code in ("temporal-review-pending", "input-too-large"):
        other = copy.deepcopy(bundle)
        other["issues"][0]["summary"] = summary_of(other, code)
        refused(other)
    ok = copy.deepcopy(bundle)
    ok["issues"][0]["summary"] = summary_of(ok, "not-requested")
    accepted(ok)


@pytest.mark.parametrize("extra,legal,illegal", [
    (MAX_QUOTES - 2, ("available", "not-requested", *JOB_CODES), ("input-too-large", "temporal-review-pending")),      # 59 quotes
    (MAX_QUOTES - 1, ("available", "not-requested", *JOB_CODES), ("input-too-large", "temporal-review-pending")),      # exactly 60 quotes: still a job's input
    (MAX_QUOTES, ("input-too-large",), ("available", "not-requested", "temporal-review-pending", *JOB_CODES)),          # 61 quotes
    (MAX_QUOTES + 40, ("input-too-large",), ("available", "not-requested", *JOB_CODES)),
])
def test_the_input_size_cap_is_exactly_sixty_quotes(extra, legal, illegal):
    bundle = with_quotes(example_bundle(), extra)
    assert len(basis_of(bundle)["quotes"]) == extra + 1
    for outcome in legal:
        other = copy.deepcopy(bundle)
        other["issues"][0]["summary"] = summary_of(other, outcome)
        accepted(other)
    for outcome in illegal:
        other = copy.deepcopy(bundle)
        other["issues"][0]["summary"] = summary_of(other, outcome)
        refused(other)


def test_a_held_oversized_issue_is_temporal_review_pending_first():
    bundle = held_with("HOLD", "ambiguous")
    with_quotes(bundle, MAX_QUOTES)
    for outcome, legal in (("temporal-review-pending", True), ("input-too-large", False), ("available", False), ("not-requested", False)):
        other = copy.deepcopy(bundle)
        other["issues"][0]["summary"] = summary_of(other, outcome)
        (accepted if legal else refused)(other)


# ---- a job-coded unavailable summary names its own result --------------------------------------------------------------------------

@pytest.mark.parametrize("code", JOB_CODES)
def test_a_job_coded_summary_must_name_its_job_basis_and_own_result_digest(code):
    bundle = example_bundle(code)
    accepted(bundle)
    for change in (lambda s: s.update(code=next(c for c in JOB_CODES if c != code)),            # the digest binds the code it was produced for
                   lambda s: s["source"].update(basisDigest="0" * 64), lambda s: s["source"].update(resultDigest="0" * 64),
                   lambda s: s["source"].update(jobId="isum-forged-1"), lambda s: s["source"].update(inputDigest="1" * 64),
                   lambda s: s.update(source=None), lambda s: s.update(code="not-requested"), lambda s: s.update(code="other"),
                   lambda s: s.update(text="합성기업이 계약을 발표했다."), lambda s: s.pop("source")):
        other = copy.deepcopy(bundle)
        change(summary(other))
        refused(other)


def test_a_deterministic_code_has_no_source():
    for code in ("not-requested", "input-too-large", "temporal-review-pending"):
        bundle = example_bundle("not-requested")
        summary(bundle).update(code=code, source=summary_of(example_bundle(), "verifier-hold")["source"])
        refused(bundle)


# ---- the execution mode: replay is authored, only a live bundle names a provider -----------------------------------------------------

def test_a_live_bundle_carries_provider_and_independent_verifier_identities():
    bundle = live_bundle()
    accepted(bundle)
    value = summary(bundle)
    assert (value["producer"]["kind"], value["verifier"]["kind"]) == ("provider", "independent-verifier")
    assert value["producer"]["model"] and value["producer"]["reasoningEffort"] and value["verifier"]["model"]
    assert value["source"]["basisDigest"] == summary(example_bundle())["source"]["basisDigest"]       # the same basis, another execution mode


def test_a_replay_summary_never_sits_in_a_live_bundle_and_a_provider_summary_never_in_a_replay_bundle():
    live, replay = live_bundle(), example_bundle()
    swapped = copy.deepcopy(live)
    swapped["issues"][0]["summary"] = copy.deepcopy(summary(replay))
    refused(swapped)
    swapped = copy.deepcopy(replay)
    swapped["issues"][0]["summary"] = copy.deepcopy(summary(live))
    refused(swapped)


@pytest.mark.parametrize("change", [
    lambda s: s["producer"].update(model=None), lambda s: s["producer"].update(reasoningEffort=None), lambda s: s["verifier"].update(model=None),
    lambda s: s["producer"].update(kind="authored-replay"), lambda s: s["verifier"].update(kind="authored-replay"),
    lambda s: s["producer"].update(model=""), lambda s: s["producer"].update(reasoningEffort="x" * 51), lambda s: s["verifier"].update(model="m" * 201),
], ids=["producer-model", "producer-effort", "verifier-model", "producer-replay-kind", "verifier-replay-kind", "model-empty", "effort-long", "verifier-model-long"])
def test_a_live_summary_names_a_model_and_a_reasoning_effort_exactly(change):
    bundle = live_bundle()
    change(summary(bundle))
    reseal(bundle)                                                    # identities recomputed: only the provenance rule can refuse it
    refused(bundle)


def test_the_model_names_of_a_replay_summary_must_be_absent_even_with_identities_recomputed():
    for change in (lambda s: s["producer"].update(model="m"), lambda s: s["producer"].update(reasoningEffort="high"), lambda s: s["verifier"].update(model="m")):
        bundle = example_bundle()
        change(summary(bundle))
        reseal(bundle)
        refused(bundle)


def test_a_bundle_with_an_unpaired_execution_mode_is_refused_whatever_its_summary():
    bundle = example_bundle()
    bundle["provenance"].update(executionMode="live")                 # live + authored-test is no legal execution pair at all
    refused(bundle)


# ---- generatedAt: the strict grammar shared with the producer and the app ---------------------------------------------------------------

def timed(value: str) -> dict[str, Any]:
    bundle = example_bundle()
    summary(bundle)["generatedAt"] = value
    return reseal(bundle)                                              # identities recomputed: only the time can decide


@pytest.mark.parametrize("value", SUMMARY_TIME_ACCEPTED)
def test_a_generated_at_in_the_shared_grammar_is_accepted(value):
    accepted(timed(value))
    assert summary_time_valid(value)


@pytest.mark.parametrize("value", SUMMARY_TIME_REFUSED)
def test_a_generated_at_outside_the_shared_grammar_is_refused(value):
    refused(timed(value))
    assert not summary_time_valid(value)


@pytest.mark.parametrize("value", ["20261016T023000+0000", "2026-W42-5T02:30:00+00:00", "2026-10-16 02:30:00+00:00", "2026-10-16T02:30+00:00"])
def test_the_python_library_parser_is_not_the_rule_it_takes_forms_the_other_languages_refuse(value):
    assert datetime.fromisoformat(value).tzinfo is not None            # the library is lenient (basic, week, space, no seconds) ...
    assert not summary_time_valid(value)                              # ... the shared grammar is not


# The vectors the producer (`issue_summary_contracts.validate_generated_at`) and the app (`HandoffBundleVerifier`) read as well: three languages, one accept list, one reject list.
TIME_VECTORS_PATH = Path(__file__).resolve().parents[3] / "api" / "src" / "test" / "resources" / "graph-handoff" / "summary-time-vectors.json"
TIME_VECTORS = json.loads(TIME_VECTORS_PATH.read_text("utf-8"))


def test_the_shared_time_vector_file_is_the_one_this_service_expects():
    assert TIME_VECTORS["schemaVersion"] == "zoop-summary-time-vectors-1" and len(TIME_VECTORS["accept"]) >= 20 and len(TIME_VECTORS["reject"]) >= 60
    assert all(isinstance(value, str) for value in TIME_VECTORS["accept"]) and len(set(TIME_VECTORS["accept"])) == len(TIME_VECTORS["accept"])
    assert all(set(item) == {"value", "why"} and item["why"] for item in TIME_VECTORS["reject"])


@pytest.mark.parametrize("value", TIME_VECTORS["accept"])
def test_every_shared_accept_vector_is_a_valid_generated_at(value):
    assert summary_time_valid(value)
    accepted(timed(value))


@pytest.mark.parametrize("item", TIME_VECTORS["reject"], ids=lambda item: item["why"])
def test_every_shared_reject_vector_is_an_invalid_generated_at_and_never_a_string_coerced(item):
    assert not summary_time_valid(item["value"])
    refused(timed(item["value"]))                                    # a null, a number or a boolean is refused as a type, never read as a time
