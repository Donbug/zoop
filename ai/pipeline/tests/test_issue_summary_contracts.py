"""Pure issue-summary contract: the basis, the zero-call rule table and the closed `issues[].summary` check. Expectations are written out by hand from the
rules (no planner, no ledger, no model); every rejection names the one rule that must refuse it."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from zoop_ai_pipeline import issue_summary_contracts as c
from zoop_ai_pipeline.relation_contracts import digest

RESOURCES = Path(__file__).resolve().parents[3] / "api" / "src" / "test" / "resources" / "graph-handoff"
TIME = json.loads((RESOURCES / "summary-time-vectors.json").read_text("utf-8"))       # shared with the Java verifier: both sides accept and refuse the same strings
REPLAY = ("replay", "authored-test")
LIVE = ("live", "provider")


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


E1, E2, E3, E4 = (f"ev-{h(name)}" for name in ("e1", "e2", "e3", "e4"))
S12, S123 = sorted([E1, E2]), sorted([E1, E2, E3])           # the digests above have no useful order: every sorted expectation is stated explicitly
ART_A, ART_B = f"doc-{h('a')}", f"doc-{h('b')}"
VER_A, VER_B = h("version-a"), h("version-b")


def issue(*, verdicts=(), extra_evidence=(), background=(False, False, True)) -> dict:
    """One issue of three mentions: m1 cites E2 and E1 (report), m2 cites E2 again (report), m3 cites E3 (background by default)."""
    return {"id": "issue:one", "title": "합성 공급 계약",
            "mentions": [{"mentionId": "m1", "background": background[0], "evidenceIds": [E2, E1]},
                         {"mentionId": "m2", "background": background[1], "evidenceIds": [E2]},
                         {"mentionId": "m3", "background": background[2], "evidenceIds": [E3]}],
            "fieldVerdicts": [{"field": "eventTime", "decision": d} for d in verdicts],
            "evidenceIds": sorted({E1, E2, E3, E4, *extra_evidence})}


EVIDENCE = {E1: {"id": E1, "articleId": ART_A, "articleVersion": VER_A, "start": 0, "end": 10, "quoteSha256": h("q1")},
            E2: {"id": E2, "articleId": ART_A, "articleVersion": VER_A, "start": 11, "end": 20, "quoteSha256": h("q2")},
            E3: {"id": E3, "articleId": ART_B, "articleVersion": VER_B, "start": 3, "end": 9, "quoteSha256": h("q3")},
            E4: {"id": E4, "articleId": ART_B, "articleVersion": VER_B, "start": 30, "end": 40, "quoteSha256": h("q4")}}
ARTICLES = {(ART_A, VER_A): {"articleId": ART_A, "articleVersion": VER_A, "documentId": "doc-a", "documentVersion": h("dv-a"), "textSha256": h("text-a"), "title": "x"},
            (ART_B, VER_B): {"articleId": ART_B, "articleVersion": VER_B, "documentId": "doc-b", "documentVersion": h("dv-b"), "textSha256": h("text-b"), "title": "y"}}


def basis_of(item=None) -> dict:
    return c.summary_basis(item or issue(), EVIDENCE, ARTICLES)


def expected_basis(contexts=("report", "report", "background")) -> dict:
    """Written out by hand: the union of the mentions' evidence ONLY (E4 is cited by no mention), sorted by evidence id, with the quotes' own coordinates."""
    rows = {E1: ("a", 0, 10, "q1", contexts[0]), E2: ("a", 11, 20, "q2", contexts[1]), E3: ("b", 3, 9, "q3", contexts[2])}
    quotes = [{"evidenceId": ident, "articleId": ART_A if rows[ident][0] == "a" else ART_B, "articleVersion": VER_A if rows[ident][0] == "a" else VER_B,
               "start": rows[ident][1], "end": rows[ident][2], "quoteSha256": h(rows[ident][3]), "context": rows[ident][4]} for ident in sorted(rows)]
    return {"policy": "zoop-issue-summary-policy-1", "issueId": "issue:one", "title": "합성 공급 계약", "quotes": quotes,
            "articles": sorted([{"articleId": ART_A, "articleVersion": VER_A, "documentId": "doc-a", "documentVersion": h("dv-a"), "textSha256": h("text-a")},
                                {"articleId": ART_B, "articleVersion": VER_B, "documentId": "doc-b", "documentVersion": h("dv-b"), "textSha256": h("text-b")}],
                               key=lambda a: (a["articleId"], a["articleVersion"]))}


# ---------------------------------------------------------------------------------------------------- basis -------------------

def test_the_basis_is_exactly_the_mention_evidence_union_with_pinned_article_versions():
    assert basis_of() == expected_basis()
    assert c.basis_digest(basis_of()) == digest(expected_basis()) and c.POLICY == "zoop-issue-summary-policy-1" and c.SCHEMA == "zoop-issue-summary-1"


def test_geography_or_verdict_only_evidence_is_not_part_of_the_basis():
    # E4 sits in the issue's own evidence list but no mention cites it: it never reaches the model.
    assert E4 in issue()["evidenceIds"] and E4 not in {q["evidenceId"] for q in basis_of()["quotes"]}


def test_a_quote_is_background_only_when_every_mention_citing_it_is_background():
    assert {q["evidenceId"]: q["context"] for q in basis_of(issue(background=(False, True, True)))["quotes"]} == {E1: "report", E2: "report", E3: "background"}
    # E2 is cited by m1 (report) and m2 (background): one report mention makes the quote a report quote.
    assert {q["evidenceId"]: q["context"] for q in basis_of(issue(background=(False, True, False)))["quotes"]}[E2] == "report"
    # all of E2's mentions are background: the quote is background; E1 (cited by the report mention m1 only) stays report.
    both = {q["evidenceId"]: q["context"] for q in basis_of(issue(background=(True, True, True)))["quotes"]}
    assert both == {E1: "background", E2: "background", E3: "background"}


def test_the_basis_digest_changes_with_every_input_it_pins():
    base = c.basis_digest(basis_of())
    for mutate in (lambda i, e, a: i.update(title="다른 제목"), lambda i, e, a: e[E1].update(quoteSha256=h("other")), lambda i, e, a: e[E1].update(end=11),
                   lambda i, e, a: a[(ART_A, VER_A)].update(textSha256=h("changed")), lambda i, e, a: a[(ART_A, VER_A)].update(documentVersion=h("dv-x")),
                   lambda i, e, a: i["mentions"][2].update(background=False), lambda i, e, a: i["mentions"][2].update(evidenceIds=[E3, E4])):
        item, evidence, articles = issue(), copy.deepcopy(EVIDENCE), copy.deepcopy(ARTICLES)
        mutate(item, evidence, articles)
        assert c.basis_digest(c.summary_basis(item, evidence, articles)) != base


def test_the_zero_call_rule_table_has_temporal_first_then_size():
    assert c.deterministic_code(issue(), basis_of()) is None
    for verdicts in (("HOLD",), ("REJECT",), ("ALLOW", "HOLD"), ("REJECT", "ALLOW")):
        assert c.temporal_review_pending(issue(verdicts=verdicts)) and c.deterministic_code(issue(verdicts=verdicts), basis_of()) == "temporal-review-pending"
    assert not c.temporal_review_pending(issue(verdicts=("ALLOW", "ALLOW")))
    big = {"quotes": [None] * (c.MAX_QUOTES + 1)}
    assert c.deterministic_code(issue(), big) == "input-too-large" and c.deterministic_code(issue(), {"quotes": [None] * c.MAX_QUOTES}) is None
    assert c.deterministic_code(issue(verdicts=("HOLD",)), big) == "temporal-review-pending"


def test_the_limits_and_code_tables_are_the_agreed_constants():
    assert (c.MAX_QUOTES, c.MAX_CLAIMS, c.MAX_CLAIM_QUOTES, c.MAX_CLAIM_TEXT) == (60, 5, 5, 280)
    assert c.DETERMINISTIC == ("not-requested", "temporal-review-pending", "input-too-large") and c.JOB_CODES == ("producer-invalid", "verifier-hold", "verifier-reject")


# ---------------------------------------------------------------------------------------------------- check_summary ------------

CLAIMS = [{"claimId": "c1", "text": "합성기업은 공급 계약을 발표했다.", "evidenceIds": S12},
          {"claimId": "c2", "text": "계약 상대는 합성부품이다.", "evidenceIds": [E3]}]
JOB, INPUT = "isum-1", h("input")
PRODUCER_REPLAY = {"kind": "authored-replay", "model": None, "reasoningEffort": None, "promptVersion": "zoop-live-prompt-x", "schemaDigest": h("schema"), "runtimeIdentity": h("fixture")}
VERIFIER_REPLAY = {"kind": "authored-replay", "model": None, "adapterIdentity": h("adapter"), "requestDigest": h("request")}
PRODUCER_LIVE = {"kind": "provider", "model": "gpt-6-luna", "reasoningEffort": "high", "promptVersion": "zoop-live-prompt-x", "schemaDigest": h("schema"),
                 "runtimeIdentity": h("runtime")}
VERIFIER_LIVE = {"kind": "independent-verifier", "model": "jev-1.14.0", "adapterIdentity": h("adapter"), "requestDigest": h("request")}


def available(pair=REPLAY, claims=None, item=None, generated_at="2026-10-22T01:02:03.456789+00:00") -> dict:
    basis = basis_of(item)
    replay = pair == REPLAY
    body = c.available_body(c.basis_digest(basis), claims or copy.deepcopy(CLAIMS), generated_at,
                            dict(PRODUCER_REPLAY if replay else PRODUCER_LIVE), dict(VERIFIER_REPLAY if replay else VERIFIER_LIVE))
    return c.assemble(JOB, INPUT, c.basis_digest(basis), body)


def withheld(code: str, item=None) -> dict:
    return c.assemble(JOB, INPUT, c.basis_digest(basis_of(item)), c.withheld_body(code))


def accepted(summary, pair=REPLAY, item=None) -> None:
    c.check_summary(item or issue(), summary, basis_of(item), pair)


def refused(summary, where: str, pair=REPLAY, item=None) -> None:
    with pytest.raises(ValueError) as caught:
        c.check_summary(item or issue(), summary, basis_of(item), pair)
    assert str(caught.value) == f"summary.{where}", caught.value


def test_an_available_replay_and_an_available_live_summary_are_accepted_with_the_hand_written_shape():
    summary = available()
    assert set(summary) == {"status", "text", "claims", "evidenceIds", "generatedAt", "resultVersion", "language", "source", "producer", "verifier"}
    assert summary["text"] == "합성기업은 공급 계약을 발표했다.\n계약 상대는 합성부품이다." and summary["evidenceIds"] == S123 and summary["language"] == "ko"
    assert summary["resultVersion"] == "isr-" + digest({"basisDigest": digest(expected_basis()), "claims": CLAIMS})
    assert set(summary["source"]) == {"jobId", "inputDigest", "resultDigest", "basisDigest"} and summary["source"]["basisDigest"] == digest(expected_basis())
    accepted(summary)
    accepted(available(LIVE), LIVE)


def test_every_job_code_and_every_applicable_deterministic_code_is_accepted():
    for code in c.JOB_CODES:
        accepted(withheld(code))
    accepted(c.deterministic_summary("not-requested"))
    accepted(c.deterministic_summary("temporal-review-pending"), item=issue(verdicts=("HOLD",)))
    accepted(c.deterministic_summary("temporal-review-pending"), item=issue(verdicts=("REJECT", "ALLOW")))


def test_an_issue_with_a_held_time_verdict_accepts_exactly_the_temporal_code_and_nothing_else():
    held = issue(verdicts=("HOLD",))
    for other in (available(item=held), withheld("verifier-hold", held), withheld("producer-invalid", held), c.deterministic_summary("not-requested"),
                  c.deterministic_summary("input-too-large")):
        refused(other, "code" if other["status"] == "unavailable" else "status", item=held)


def test_a_deterministic_code_is_refused_while_its_condition_does_not_hold():
    refused(c.deterministic_summary("temporal-review-pending"), "code")                 # nothing is held
    refused(c.deterministic_summary("input-too-large"), "code")                         # 3 quotes
    # `not-requested` is only valid while no rule applies.
    big = {"policy": c.POLICY, "issueId": "issue:one", "title": "t", "quotes": [{"evidenceId": f"ev-{i}"} for i in range(61)], "articles": []}
    with pytest.raises(ValueError, match="summary.code"):
        c.check_summary(issue(), c.deterministic_summary("not-requested"), big, REPLAY)
    c.check_summary(issue(), c.deterministic_summary("input-too-large"), big, REPLAY)
    with pytest.raises(ValueError, match="summary.status"):
        c.check_summary(issue(), available(), big, REPLAY)


def test_a_deterministic_code_never_carries_a_source_and_a_job_code_always_does():
    refused({"status": "unavailable", "code": "not-requested", "source": withheld("verifier-hold")["source"]}, "code")
    refused({"status": "unavailable", "code": "verifier-hold", "source": None}, "source")
    refused({"status": "unavailable", "code": "verifier-hold"}, "shape")
    refused({"status": "unavailable", "code": "made-up", "source": None}, "code")
    refused({**withheld("verifier-hold"), "extra": 1}, "shape")


def test_a_job_result_is_pinned_to_exactly_this_basis():
    summary = withheld("verifier-reject")
    summary["source"]["basisDigest"] = h("another basis")
    refused(summary, "source.basisDigest")
    other = issue()
    other["title"] = "다른 제목"
    refused(withheld("verifier-hold"), "source.basisDigest", item=other)     # a job result produced for the old title is not valid for the changed basis
    refused(available(), "resultVersion", item=other)                       # the content identity covers the basis too


@pytest.mark.parametrize("mutate,where", [
    (lambda s: s["source"].update(resultDigest=h("forged")), "source.resultDigest"),
    (lambda s: s["source"].update(jobId="isum-2"), "source.resultDigest"),
    (lambda s: s["source"].update(inputDigest=h("other input")), "source.resultDigest"),
    (lambda s: s["source"].update(jobId="bad id"), "source.jobId"),
    (lambda s: s["source"].pop("jobId"), "source"),
    (lambda s: s.update(text=s["text"] + "."), "text"),
    (lambda s: s.update(evidenceIds=[E1]), "evidenceIds"),
    (lambda s: s.update(evidenceIds=S123[::-1]), "evidenceIds"),
    (lambda s: s.update(language="en"), "language"),
    (lambda s: s.update(generatedAt="2026-10-22T01:02:03"), "generatedAt"),
    (lambda s: s.update(generatedAt="yesterday"), "generatedAt"),
    (lambda s: s.update(generatedAt="20261022T010203Z"), "generatedAt"),
    (lambda s: s.update(generatedAt="2026-10-22 01:02:03+00:00"), "generatedAt"),
    (lambda s: s.update(generatedAt="2026-10-22T01:02:03+0000"), "generatedAt"),
    (lambda s: s.update(generatedAt="2026-10-22t01:02:03z"), "generatedAt"),
    (lambda s: s.update(generatedAt=None), "generatedAt"),
    (lambda s: s.update(resultVersion="isr-" + h("x")), "resultVersion"),
    (lambda s: s.update(unknown=1), "shape"),
    (lambda s: s.pop("language"), "shape"),
    (lambda s: s.update(status="summary"), "status"),
    (lambda s: s["claims"].append({"claimId": "c3", "text": "가", "evidenceIds": [E1]}), "text"),
    (lambda s: s["claims"][0].update(claimId="c2"), "claims.claimId"),
    (lambda s: s["claims"][0].update(text="Synthetic English only."), "claims.text"),
    (lambda s: s["claims"][0].update(text="가" * 281), "claims.text"),
    (lambda s: s["claims"][0].update(text="첫 줄\n둘째 줄"), "claims.text"),
    (lambda s: s["claims"][0].update(text=""), "claims.text"),
    (lambda s: s["claims"][0].update(evidenceIds=[]), "claims.evidenceIds"),
    (lambda s: s["claims"][0].update(evidenceIds=S12[::-1]), "claims.evidenceIds"),
    (lambda s: s["claims"][0].update(evidenceIds=[E1, E1]), "claims.evidenceIds"),
    (lambda s: s["claims"][0].update(evidenceIds=[E1, "ev-" + h("outside the basis")]), "claims.evidenceIds"),
    (lambda s: s["claims"][0].update(evidenceIds=[E4]), "claims.evidenceIds"),
    (lambda s: s["claims"][0].update(extra=1), "claims.shape"),
    (lambda s: s.update(claims=[]), "claims"),
    (lambda s: s["producer"].update(kind="provider"), "producer.kind"),
    (lambda s: s["verifier"].update(kind="independent-verifier"), "verifier.kind"),
    (lambda s: s["producer"].update(model="gpt-6-luna"), "producer.model"),
    (lambda s: s["producer"].update(reasoningEffort="high"), "producer.reasoningEffort"),
    (lambda s: s["producer"].update(schemaDigest="x"), "producer.schemaDigest"),
    (lambda s: s["producer"].update(runtimeIdentity=None), "producer.runtimeIdentity"),
    (lambda s: s["producer"].update(promptVersion=""), "producer.promptVersion"),
    (lambda s: s["producer"].pop("runtimeIdentity"), "producer"),
    (lambda s: s["verifier"].update(adapterIdentity="x"), "verifier.adapterIdentity"),
    (lambda s: s["verifier"].update(requestDigest=None), "verifier.requestDigest"),
    (lambda s: s["verifier"].update(model="jev-1.14.0"), "verifier.model")])
def test_each_available_summary_defect_is_refused_by_its_own_rule(mutate, where):
    summary = available()
    mutate(summary)
    # The result digest covers the body, so a body edit also breaks it; every rule above it in the check order fires first.
    refused(summary, where)


def test_claim_count_and_citation_count_limits_are_inclusive():
    five = [{"claimId": f"c{i}", "text": "합성기업은 계약을 발표했다.", "evidenceIds": S123} for i in range(1, 6)]
    accepted(available(claims=five))
    refused(available(claims=five + [{"claimId": "c6", "text": "가", "evidenceIds": [E1]}]), "claims")
    six_ids = {"claimId": "c1", "text": "합성기업은 계약을 발표했다.", "evidenceIds": sorted([E1, E2, E3, E4, "ev-" + h("x"), "ev-" + h("y")])}
    refused(available(claims=[six_ids]), "claims.evidenceIds")
    accepted(available(claims=[{"claimId": "c1", "text": "가" * 280, "evidenceIds": [E1]}]))


def test_the_live_summary_needs_live_identities_and_a_replay_summary_cannot_sit_in_a_live_bundle():
    refused(available(REPLAY), "producer.kind", LIVE)
    refused(available(LIVE), "producer.kind", REPLAY)
    for bad in ({"model": None}, {"reasoningEffort": None}):
        summary = available(LIVE)
        summary["producer"].update(bad)
        refused(summary, "producer.model" if "model" in bad else "producer.reasoningEffort", LIVE)
    refused(available(), "mode", ("replay", "provider"))
    # An available summary whose result digest does not match its body is a tampered body.
    tampered = available()
    tampered["claims"][1]["text"] = "계약 상대는 다른 회사다."
    tampered["text"] = "\n".join(claim["text"] for claim in tampered["claims"])
    refused(tampered, "resultVersion")


def test_a_hangul_syllable_is_required_but_the_length_counts_code_points_not_utf16_units():
    accepted(available(claims=[{"claimId": "c1", "text": "😀" * 279 + "가", "evidenceIds": [E1]}]))            # 280 code points (559 UTF-16 units)
    refused(available(claims=[{"claimId": "c1", "text": "😀" * 281, "evidenceIds": [E1]}]), "claims.text")
    refused(available(claims=[{"claimId": "c1", "text": "😀" * 10 + "abc", "evidenceIds": [E1]}]), "claims.text")
    accepted(available(claims=[{"claimId": "c1", "text": "😀" * 270 + "가나다", "evidenceIds": [E1]}]))


# ------------------------------------------------------------------------------------------------------ generatedAt grammar -----------

@pytest.mark.parametrize("value", TIME["accept"])
def test_every_accepted_time_vector_passes_the_summary_check(value):
    accepted(available(generated_at=value))


@pytest.mark.parametrize("item", [pytest.param(item, id=item["why"]) for item in TIME["reject"]])
def test_every_rejected_time_vector_is_refused_by_the_summary_check(item):
    summary = available()
    summary["generatedAt"] = item["value"]
    refused(summary, "generatedAt")
