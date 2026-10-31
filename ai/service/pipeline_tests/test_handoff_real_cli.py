"""The handoff door over the REAL installed `zoop-ai-handoff` and an actual two-S3-job world (no stand-in command).

What a stand-in cannot prove, this does: the argv the service builds is accepted by the real command, the real exit codes and canonical stdout are interpreted as
documented, the bundle the HTTP response delivers equals the real CLI export byte for byte in canonical form and is accepted by the PRODUCER's own validator,
the closed bundle model accepts every shape the real producer emits (all three relation types, structural basis, exclusions, a second source job), and the real
current-authority checks (a revoked grant, an operator file change) withhold content over HTTP exactly as the CLI withholds it. The world is built by the
pipeline's interpreter from authored replay: no model, provider or network. Expectations are hand-written from the authored world (`build_handoff_world.py`
reads them from the pipeline smoke's own hand-written `expected`), never derived from the service.
"""
from __future__ import annotations

import copy
import fcntl
import json
import os
import shutil
import subprocess
import time
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from handoff_support import SUMMARY_KEYS, basis_of, bundle_url, json_keys, status_url, summary_corpus
from real_handoff_support import (FORGERIES, IMPACT_HANDOFF, SUMMARY_HANDOFF, SUMMARY_WITHHELD_HANDOFF, VERDICT_HANDOFF, RealWorkspace, digest_of, forge_command, pin_entry,
                                  producer_accepts, producer_accepts_manifest, producer_verdicts, summary_problems, verdict_problems)
from relation_support import PIPELINE
from support import canonical
from zoop_ai_service.handoff_doc import example_bundle, example_manifest
from zoop_ai_service.handoff_wire import Bundle

PRINCIPAL = "handoffer"
NOT_REQUESTED = {"status": "unavailable", "code": "not-requested", "source": None}
TEMPORAL_PENDING = {"status": "unavailable", "code": "temporal-review-pending", "source": None}
NODE = shutil.which("node")
JS_DIGEST = r"""
const fs = require('fs'), crypto = require('crypto');
const canon = (v) => Array.isArray(v) ? '[' + v.map(canon).join(',') + ']'
  : (v !== null && typeof v === 'object') ? '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}' : JSON.stringify(v);
const doc = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(crypto.createHash('sha256').update(canon(doc.bundle), 'utf8').digest('hex'));
"""
Start = Callable[..., tuple[RealWorkspace, Any]]


def error_of(response) -> dict[str, Any]:
    return response.json()["error"]


def get(service, url: str, as_: str = PRINCIPAL):
    return service.request("GET", url, as_=as_)


def listed(world, *ids: str, principal: str = PRINCIPAL) -> list[dict]:
    return [pin_entry(world, principal, handoff_id) for handoff_id in ids]


def test_the_authored_openapi_example_bundle_is_a_bundle_the_producers_own_validator_accepts():
    """The documented example is not a hand-waved sample: id formulas, referential closure, counts and digests satisfy `validate_bundle` of the installed pipeline."""
    assert producer_accepts(json.dumps({"bundle": example_bundle()}).encode("utf-8"))
    broken = example_bundle()
    broken["relations"][0]["target"] = "KRX:999999"       # the validator is not a rubber stamp: a dangling endpoint is refused
    assert not producer_accepts(json.dumps({"bundle": broken}).encode("utf-8"))
    assert producer_accepts_manifest(json.dumps({"manifest": example_manifest(), "bundle": example_bundle()}).encode("utf-8"))   # the example manifest is the producer's own shape


def test_the_service_summary_rules_agree_with_the_producers_validator_on_every_fixture_and_edit():
    """Differential: the closed service model and the installed producer's own `validate_bundle` judge the SAME 100+ bundles - every legal outcome, live provenance, a
    multi-quote summary, the 59/60/61 quote cap, a held issue with every other outcome, every authored content edit, stale versus re-pinned summaries, geography/verdict-only
    evidence and execution-mode swaps - and must give the identical verdict for each. A rule the service mirrored wrongly (a boundary, a digest, a provenance pairing)
    shows up here as a disagreement with the producer, not as a self-consistent test."""
    corpus = summary_corpus()
    producer = producer_verdicts(corpus)
    service = {}
    for name, bundle in corpus.items():
        try:
            Bundle.model_validate(bundle)
            service[name] = True
        except ValidationError:
            service[name] = False
    assert set(producer) == set(corpus) and len(corpus) >= 100
    assert {name: (producer[name], service[name]) for name in corpus if producer[name] != service[name]} == {}
    assert 20 <= sum(producer.values()) < len(corpus) - 20          # not vacuous: both verdicts occur, many times
    for name in ("outcome:available", "outcome:not-requested", "outcome:temporal-review-pending", "outcome:verifier-hold", "live", "multi-quote", "quotes:60:available",
                 "quotes:61:input-too-large", "repinned:one-more-quote:available"):
        assert producer[name] and service[name], name
    for name in ("held:available", "quotes:61:available", "quotes:60:input-too-large", "swap:replay-summary-in-live-bundle", "stale:quote-hash:available",
                 "side:geography:cited", "side:verdict:cited", "tamper:claim-evidence-hidden"):
        assert not producer[name] and not service[name], name


def test_the_http_bundle_is_the_real_cli_export_of_a_two_job_world_and_the_producer_accepts_it(handoff_world, start_handoff: Start):
    pins = handoff_world.handoffs["handoff-1"]
    ws, service = start_handoff(listed(handoff_world, "handoff-1"))
    code, oracle, _ = ws.direct("handoff-1")
    assert code == 0 and oracle["delivery"]["status"] == "current" and oracle["usage"] == {"providerCalls": 0, "modelCalls": 0}
    response = get(service, bundle_url("handoff-1"))
    wire = response.json()
    assert response.status_code == 200 and wire["delivery"]["state"] == "current" and (wire["state"], wire["publication"], wire["appImport"]) == ("ready", "not-published", "pending")
    bundle = wire["bundle"]
    assert bundle == oracle["bundle"] and canonical(bundle) == canonical(oracle["bundle"])         # no key added, dropped, defaulted or normalised
    assert digest_of(bundle) == pins["bundleDigest"] == wire["verification"]["bundleDigest"] == oracle["receipt"]["bundleDigest"]
    assert wire["verification"]["manifestDigest"] == pins["manifestDigest"] == bundle["manifestDigest"] and wire["verification"]["contentDigest"] == pins["contentDigest"]
    assert wire["verification"]["bundleBytes"] == pins["bundleBytes"] == len(canonical(bundle).encode("utf-8"))
    # at least two source jobs, from two S2 upstreams (hand-authored world)
    assert [s["relation"]["jobId"] for s in bundle["sources"]] == pins["sourceJobs"] == ["rel-a", "rel-b"] and len(set(pins["upstreamJobs"])) == 2
    assert wire["verification"]["sources"] == 2 and wire["verification"]["counts"] == bundle["counts"] == handoff_world.counts
    # the hand-written expectation of the authored world
    assert [e["id"] for e in bundle["evidence"]] == handoff_world.evidence_ids
    assert sorted(i["id"] for i in bundle["issues"]) == handoff_world.issue_ids
    assert sorted([r["type"], r["source"], r["target"], r["evidenceIds"]] for r in bundle["relations"]) == handoff_world.relation_edges
    assert bundle["exclusions"]["counts"] == handoff_world.exclusions and sorted(a["articleId"] for a in bundle["articles"]) == handoff_world.article_ids
    assert {r["type"] for r in bundle["relations"]} == {"INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS"}   # every provenance variant of the closed model, from the real producer
    for issue in bundle["issues"]:     # the contract's partition rule, stated here independently of the producer's validator: every source event is one original mention and no other exists
        identity = lambda item: canonical({k: item[k] for k in ("documentId", "documentVersion", "mentionId")})  # noqa: E731
        assert [identity(m) for m in issue["mentions"]] == sorted({identity(e) for e in issue["sourceEvents"]}) and all(m["verification"] == "none" for m in issue["mentions"])
        # the selection rule's closure, stated independently of the producer's validator: exact equality against the SELECTED original value (the representative's
        # mention, else the unanimous one; null equals null, no normalisation, never the redacted null), nonempty, ordered as the mentions
        provenance, fields = issue["fieldProvenance"], ("title", "action", "target", "eventTime", "period", "assertionStatus")
        assert "fieldDecisions" not in issue and "fieldDecisions" not in provenance
        assert set(provenance) == {"selection", "verification", "withheld", "sameValueMentions"} and provenance["verification"] == "none"
        assert provenance["selection"] == ("operator-representative" if issue["representative"] is not None else "unanimous")
        assert set(provenance["sameValueMentions"]) == set(fields)
        ident = lambda item: {k: item[k] for k in ("documentId", "documentVersion", "mentionId")}  # noqa: E731
        by_identity = {canonical(ident(m)): m for m in issue["mentions"]}
        basis = [by_identity[canonical(ident(issue["representative"]))]] if issue["representative"] is not None else list(issue["mentions"])
        verdicts = issue["fieldVerdicts"]
        # operator verdicts: closed keys, own mention, the exact reviewed value, own-document evidence, the legal decision/reason/span combinations, canonical order
        assert [(canonical(ident(v)), ("eventTime", "period").index(v["field"])) for v in verdicts] == sorted((canonical(ident(v)), ("eventTime", "period").index(v["field"])) for v in verdicts)
        assert len({(canonical(ident(v)), v["field"]) for v in verdicts}) == len(verdicts)
        article_of = {e["id"]: e["articleId"] for e in bundle["evidence"]}
        for verdict in verdicts:
            assert set(verdict) == {"documentId", "documentVersion", "mentionId", "field", "value", "decision", "reasonCode", "evidenceIds", "verification", "reviewer",
                                    "decisionRef", "decisionVersion"} and verdict["verification"] == "operator-field-verdict"
            mention = by_identity[canonical(ident(verdict))]
            assert verdict["value"] == mention[verdict["field"]] is not None
            assert (verdict["decision"], verdict["reasonCode"], bool(verdict["evidenceIds"])) in {("ALLOW", "stated", True), ("HOLD", "unstated", False), ("HOLD", "ambiguous", True),
                                                                                                 ("REJECT", "contradicted", True)}
            assert all(article_of[e] == mention["articleId"] and e in issue["evidenceIds"] for e in verdict["evidenceIds"])
        suppressed = [f for f in ("eventTime", "period") if any(v["field"] == f and v["decision"] != "ALLOW" and any(canonical(ident(v)) == canonical(ident(m)) for m in basis) for v in verdicts)]
        assert provenance["withheld"] == suppressed
        for name in fields:
            selected = basis[0][name]
            assert all(m[name] == selected for m in basis)
            expected = [ident(m) for m in issue["mentions"] if m[name] == selected]
            assert expected and provenance["sameValueMentions"][name] == expected, (issue["id"], name)
            assert issue[name] == (None if name in suppressed else selected)
        assert issue["timePrecision"] == ("unknown" if "eventTime" in suppressed else issue["timePrecision"])
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8" and bundle["policy"]["issueSummary"] == "zoop-issue-summary-policy-1"
    # no decision of the default world pins a summary and no verdict holds any field: every issue states `not-requested` (never an absent summary, never a guess)
    assert [i["summary"] for i in bundle["issues"]] == [NOT_REQUESTED] * len(bundle["issues"]) and bundle["issues"]
    assert (bundle["readiness"], wire["verification"]["provenance"]) == ({"app": "import-pending", "evidenceRegistration": "not-registered", "publicActivation": "none",
                                                                          "graphDb": "none"}, bundle["provenance"])
    assert producer_accepts(response.content)
    # impacts: the real producer's rows, relayed exactly and equal to the pipeline world's hand-written expectation (never derived from the bundle or the service)
    assert handoff_world.impacts and bundle["impacts"] == handoff_world.impacts and bundle["counts"]["impacts"] == len(bundle["impacts"])
    assert bundle["policy"]["impacts"] == "s3-independent-verifier-quote-effect"
    involves = sorted((r["id"], ref["jobId"], ref["id"]) for r in bundle["relations"] if r["type"] == "INVOLVES" for ref in r["sourceRefs"] if ref["kind"] == "s3-relation")
    assert [(i["edgeId"], i["sourceRelation"]["jobId"], i["sourceRelation"]["relationCandidateId"]) for i in bundle["impacts"]] == involves
    assert all(set(i) == {"edgeId", "issueId", "companyId", "sourceRelation", "impactCandidateId", "status", "code", "label", "targetVerdict", "effects", "verifier",
                          "verifierRequestDigest", "proposal"} for i in bundle["impacts"])
    manifest = wire["manifest"]                                    # the ledger's frozen request, carried beside the bundle
    assert manifest == oracle["manifest"] and canonical(manifest) == canonical(oracle["manifest"])
    assert digest_of(manifest) == pins["manifestDigest"] == bundle["manifestDigest"] == wire["verification"]["manifestDigest"] == oracle["receipt"]["manifestDigest"]
    assert manifest["files"] == bundle["policy"]["files"] and manifest["handoffId"] == "handoff-1" and producer_accepts_manifest(response.content)
    assert sorted(s["relation"]["jobId"] for s in manifest["sources"]) == ["rel-a", "rel-b"]


@pytest.mark.skipif(NODE is None, reason="the cross-language check needs node")
def test_the_real_bundle_hashes_to_the_pin_in_another_language_after_a_plain_json_round_trip(handoff_world, start_handoff: Start):
    _, service = start_handoff(listed(handoff_world, "handoff-1"))
    response = get(service, bundle_url("handoff-1"))
    digest = subprocess.run([NODE, "-e", JS_DIGEST], input=response.content, capture_output=True, timeout=60, check=True).stdout.decode()
    assert response.status_code == 200 and digest == handoff_world.handoffs["handoff-1"]["bundleDigest"]


def test_the_default_world_relays_not_proposed_rows_for_every_automatic_participation(handoff_world, start_handoff: Start):
    _, service = start_handoff(listed(handoff_world, "handoff-1"))
    rows = get(service, bundle_url("handoff-1")).json()["bundle"]["impacts"]
    assert rows == handoff_world.impacts and rows and all(r["status"] == "not-proposed" and r["impactCandidateId"] is None and r["proposal"] is None for r in rows)


def test_the_real_impact_world_is_relayed_with_every_state_the_pipeline_authored(impact_world, start_impact_handoff: Start):
    """The pipeline's hand-written rich-world expectation (`impact_world.impacts`, never derived from the service) spans the real states and the HTTP bundle relays exactly
    those rows, byte-equal to the CLI export: on the supply edge four rows of one edge kept apart (verified positive, verifier-reject, verified negative of the other job,
    verified undetermined for an insufficient target), on the factory edge a no-evidence row (label null) and a precheck-rejected technical reject. The verifier is an authored
    replay, not independent inference."""
    ws, service = start_impact_handoff(listed(impact_world, IMPACT_HANDOFF))
    code, oracle, _ = ws.direct(IMPACT_HANDOFF)
    response = get(service, bundle_url(IMPACT_HANDOFF))
    wire = response.json()
    assert code == 0 and response.status_code == 200 and wire["delivery"]["state"] == "current", response.text[:300]
    bundle = wire["bundle"]
    rows = bundle["impacts"]
    assert bundle == oracle["bundle"] and canonical(bundle) == canonical(oracle["bundle"]) and digest_of(bundle) == impact_world.handoffs[IMPACT_HANDOFF]["bundleDigest"]
    assert rows == impact_world.impacts and bundle["counts"]["impacts"] == len(rows) == 6 and producer_accepts(response.content)
    assert sorted(((r["status"], r["code"]) for r in rows), key=repr) == sorted([("verified", None)] * 3 + [("verifier-reject", None), ("no-evidence", None),
                                                                                 ("technical-reject", "impact_precheck_rejected")], key=repr)
    verified = [r for r in rows if r["status"] == "verified"]
    assert {r["label"] for r in verified} == {"positive", "negative", "undetermined"}
    assert all(r["effects"] and sum(map(len, r["effects"].values())) >= 1 and r["proposal"]["verification"] == "none" and r["verifier"] == "called" for r in verified)
    assert all(r["label"] is None and r["effects"] is None for r in rows if r["status"] != "verified")
    assert all(r["targetVerdict"] == "contradicted" for r in rows if r["status"] == "verifier-reject")
    assert all(r["impactCandidateId"] is not None and r["proposal"] is not None for r in rows if r["status"] in ("no-evidence", "verified", "verifier-reject"))
    assert all(r["impactCandidateId"] is not None and r["proposal"] is None and r["verifier"] == "not-called" for r in rows if r["status"] == "technical-reject")
    supply = [r for r in rows if r["issueId"] == "issue:supply-2026q3"]
    assert len(supply) == 4 and len({r["edgeId"] for r in supply}) == 1 and len({r["sourceRelation"]["relationCandidateId"] for r in supply}) == 4
    by_label = {r["label"]: r for r in supply if r["status"] == "verified"}
    assert {"positive", "negative"} <= set(by_label), "the same edge keeps its opposite verified labels as separate rows, never aggregated"
    assert by_label["positive"]["edgeId"] == by_label["negative"]["edgeId"] and by_label["positive"]["sourceRelation"] != by_label["negative"]["sourceRelation"]
    assert by_label["positive"]["effects"]["positive"] and by_label["negative"]["effects"]["negative"]
    assert by_label["positive"]["impactCandidateId"] != by_label["negative"]["impactCandidateId"]
    status = get(service, status_url(IMPACT_HANDOFF))
    assert status.status_code == 200 and "bundle" not in status.json() and status.json()["verification"]["counts"]["impacts"] == 6
    assert not [s for s in ("effects", "proposal", "verifierRequestDigest", "targetVerdict", "impactCandidateId", "positive") if s in status.text]
    assert not [s for s in ws.world.private if s in response.text + status.text]


def test_the_service_model_refuses_every_negative_the_producers_validator_refuses_and_accepts_the_unicode_length_bundle(impact_world):
    """The pipeline's one-rule-broken bundles of the REAL rich export (digest recomputed, so only the broken rule can refuse them) against the service's closed model. A case
    about the content digest itself is not a model rule: the rebuilt digest must differ from the one the bundle states."""
    from pydantic import ValidationError
    from zoop_ai_service.handoff_reads import content_digest
    from zoop_ai_service.handoff_wire import Bundle
    assert len(impact_world.impact_negatives) >= 30
    survived = []
    for name, case in impact_world.impact_negatives.items():
        bundle = case["bundle"]
        if not case["digestRefreshed"]:
            assert content_digest(bundle) != bundle["digests"]["content"], name
            continue
        try:
            Bundle.model_validate(bundle)
        except ValidationError:
            continue
        survived.append((name, case["validatorLocation"]))
    assert survived == [], survived
    unicode_bundle = impact_world.impact_unicode
    row = next(r for r in unicode_bundle["impacts"] if r["status"] == "verified")
    assert len(row["proposal"]["reason"]) == 2000 and len(row["proposal"]["reason"].encode("utf-16-le")) == 8000
    assert Bundle.model_validate(unicode_bundle).wire() == unicode_bundle


def test_a_status_over_the_real_cli_is_content_free_and_agrees_with_the_receipt(handoff_world, start_handoff: Start):
    ws, service = start_handoff(listed(handoff_world, "handoff-1"))
    _, oracle, _ = ws.direct("handoff-1")
    response = get(service, status_url("handoff-1"))
    wire = response.json()
    receipt = oracle["receipt"]
    assert response.status_code == 200 and "bundle" not in wire and "manifest" not in wire
    assert wire["verification"] == {"manifestDigest": receipt["manifestDigest"], "bundleDigest": receipt["bundleDigest"], "contentDigest": receipt["contentDigest"],
                                    "bundleBytes": receipt["bundleBytes"], "counts": receipt["counts"], "sources": 2, "provenance": receipt["provenance"]}
    assert (wire["delivery"]["state"], wire["delivery"]["reason"]) == ("current", None) and wire["delivery"]["checkedAt"]   # its own check time, not the oracle's
    for private in (*ws.private_strings(), "rel-a", "rel-b", "KRX:005930", "doc-", "ev-", "issue:supply", "reviewDigest", "attempts"):
        assert private not in response.text, private
    assert not [s for s in ("effects", "proposal", "verifierRequestDigest", "targetVerdict", "impactCandidateId") if s in response.text]   # status carries no impact content (only the count)


def test_principals_see_only_their_own_pinned_handoffs_and_every_refusal_is_the_same_before_any_child(handoff_world, start_handoff: Start):
    ws, service = start_handoff([*listed(handoff_world, "handoff-1", principal="alpha"), *listed(handoff_world, "handoff-2", principal="beta")])
    refusals = [get(service, status_url("handoff-2"), "alpha"), get(service, bundle_url("handoff-1"), "beta"), get(service, status_url("handoff-3"), "alpha"),
                get(service, bundle_url("handoff-1"), PRINCIPAL)]
    assert all(r.status_code == 403 for r in refusals)
    assert len({json.dumps({k: v for k, v in error_of(r).items() if k != "requestId"}, sort_keys=True) for r in refusals}) == 1 and error_of(refusals[0])["code"] == "handoff_not_allowed"
    first = get(service, bundle_url("handoff-1"), "alpha").json()
    second = get(service, bundle_url("handoff-2"), "beta").json()
    assert first["handoffId"] == first["bundle"]["handoffId"] == "handoff-1" and second["handoffId"] == second["bundle"]["handoffId"] == "handoff-2"
    assert first["verification"]["bundleDigest"] != second["verification"]["bundleDigest"]
    assert digest_of(first["bundle"]) == handoff_world.handoffs["handoff-1"]["bundleDigest"] and digest_of(second["bundle"]) == handoff_world.handoffs["handoff-2"]["bundleDigest"]


def test_a_pin_that_is_not_the_stored_bundle_is_withheld_with_no_content_and_a_listed_absent_handoff_is_404(handoff_world, start_handoff: Start):
    wrong = pin_entry(handoff_world, PRINCIPAL, "handoff-1", bundleDigest=handoff_world.handoffs["handoff-2"]["bundleDigest"])
    absent = {**pin_entry(handoff_world, PRINCIPAL, "handoff-1"), "handoffId": "handoff-absent"}
    _, service = start_handoff([wrong, absent])
    for url in (status_url("handoff-1"), bundle_url("handoff-1")):
        wire = get(service, url).json()
        assert wire["delivery"]["state"] == "withheld" and wire["delivery"]["reason"] == "handoff_pin_mismatch" and wire["verification"] is None and wire.get("bundle") is None
    missing = get(service, bundle_url("handoff-absent"))
    assert missing.status_code == 404 and error_of(missing)["code"] == "handoff_not_found" and "bundle" not in missing.json()


def test_source_revocation_and_operator_file_changes_withhold_exactly_as_the_cli_does_and_restore(handoff_world, start_handoff: Start):
    ws, service = start_handoff(listed(handoff_world, "handoff-1"))
    assert get(service, bundle_url("handoff-1")).json()["delivery"]["state"] == "current"

    def withheld(expected: str | None) -> str:
        code, oracle, _ = ws.direct("handoff-1")
        assert code == 2 and oracle["delivery"]["status"] == "withheld" and "bundle" not in oracle
        reason = oracle["delivery"]["code"]
        for url in (status_url("handoff-1"), bundle_url("handoff-1")):
            response = get(service, url)
            wire = response.json()
            assert response.status_code == 200 and wire["delivery"]["state"] == "withheld" and wire["delivery"]["reason"] == reason, (reason, response.text[:300])
            assert wire["verification"] is None and wire.get("bundle") is None
            for text in (*ws.world.private, "KRX:005930", "rel-a", handoff_world.handoffs["handoff-1"]["bundleDigest"]):
                assert text not in response.text
        if expected is not None:
            assert reason == expected
        return reason

    registry = json.loads(ws.originals["sources"])
    registry["sources"][0]["grant"]["enabled"] = False       # a source right is revoked
    ws.sources.write_text(canonical(registry), encoding="utf-8")
    try:
        withheld(None)
    finally:
        ws.restore("sources")
    assert get(service, bundle_url("handoff-1")).json()["delivery"]["state"] == "current"
    for name, expected in (("decisions", "decisions_changed"), ("canonical", "canonical_mapping_changed"), ("bindings", "bindings_changed")):
        getattr(ws, name).write_bytes(ws.originals[name] + b"\n")       # same meaning, other bytes: the manifest pinned the exact hash
        try:
            withheld(expected)
        finally:
            ws.restore(name)
        assert get(service, bundle_url("handoff-1")).json()["delivery"]["state"] == "current"


def test_an_operator_writer_holding_the_handoff_ledger_is_a_busy_503_and_releasing_it_restores_service(handoff_world, start_handoff: Start):
    ws, service = start_handoff(listed(handoff_world, "handoff-1"))
    descriptor = os.open(handoff_world.state / "handoff.lock", os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)   # what a `freeze` or `recover` command holds
        for url in (status_url("handoff-1"), bundle_url("handoff-1")):
            response = get(service, url)
            error = error_of(response)
            assert response.status_code == 503 and (error["code"], error["runtimeCode"], error["retryable"]) == ("runtime_busy", "handoff_busy", True)
            assert response.headers["retry-after"] and "state" not in response.json() and "bundle" not in response.json()   # busy is never an empty or stale answer
    finally:
        os.close(descriptor)
    assert get(service, bundle_url("handoff-1")).status_code == 200


def test_a_real_child_that_cannot_finish_inside_the_deadline_is_a_retryable_503_and_leaves_no_process(handoff_world, start_handoff: Start):
    ws, service = start_handoff(listed(handoff_world, "handoff-1"), launcher_env={"ZOOP_TEST_HANDOFF_DEADLINE": "0.05"})
    began = time.monotonic()
    response = get(service, bundle_url("handoff-1"))
    assert time.monotonic() - began < 30
    error = error_of(response)
    assert response.status_code == 503 and (error["code"], error["retryable"]) == ("runtime_unavailable", True) and response.headers["retry-after"] and "bundle" not in response.json()
    time.sleep(1)
    leftovers = subprocess.run(["pgrep", "-f", f"zoop-ai-handoff export --state-dir {handoff_world.state}"], capture_output=True, text=True)
    assert leftovers.returncode == 1 and leftovers.stdout.strip() == ""   # pgrep exit 1 is a genuine no-match


def test_nothing_private_reaches_a_response_header_or_log_and_no_credential_or_path_reaches_the_child(handoff_world, start_handoff: Start):
    ws, service = start_handoff(listed(handoff_world, "handoff-1"))
    responses = [get(service, status_url("handoff-1")), get(service, bundle_url("handoff-1")), get(service, status_url("handoff-3")), get(service, f"{status_url('handoff-1')}?x=1")]
    service.stop()
    # The bundle route legitimately delivers the bundle's own data (titles, URLs, ids); the authored source SENTENCES and every server path never appear anywhere.
    forbidden = [*handoff_world.private, str(handoff_world.root), str(ws.root), str(PIPELINE)]
    for response in responses:
        blob = response.text + json.dumps(dict(response.headers))
        assert not [s for s in forbidden if s in blob]
    assert not [s for s in (*ws.private_strings(), *handoff_world.private) if s in service.logs()]


def test_the_http_bundle_carries_the_operators_real_field_verdicts_with_the_suppressed_headlines_null_and_the_original_mentions_intact(verdict_world, start_verdict_handoff: Start):
    """NOT the empty default world: the installed command exports a reviewed world (SYNTHETIC verdicts authored in the pipeline smoke) and the service relays it. Every
    expectation is the pipeline smoke's hand-written one (`verdict_world.expect`), the delivered bytes equal the direct CLI export and the producer's own validator accepts
    them, so a service that echoed, defaulted, dropped or reshaped a verdict could not pass."""
    pins = verdict_world.handoffs[VERDICT_HANDOFF]
    ws, service = start_verdict_handoff(listed(verdict_world, VERDICT_HANDOFF))
    code, oracle, _ = ws.direct(VERDICT_HANDOFF)
    assert code == 0 and oracle["delivery"]["status"] == "current" and oracle["usage"] == {"providerCalls": 0, "modelCalls": 0}
    response = get(service, bundle_url(VERDICT_HANDOFF))
    wire = response.json()
    assert response.status_code == 200 and wire["delivery"]["state"] == "current", response.text[:300]
    bundle = wire["bundle"]
    assert bundle == oracle["bundle"] and canonical(bundle) == canonical(oracle["bundle"]) and bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8"
    # the reviewed world holds a REJECT on the supply representative's event time and a HOLD on the factory's period: ANY HOLD/REJECT leaves the issue exactly
    # `temporal-review-pending` (no job, no source, no summary text) - a hand-written expectation, never derived from the bundle or the service
    assert {i["id"]: i["summary"] for i in bundle["issues"]} == {"issue:supply-2026q3": TEMPORAL_PENDING, "issue:factory-2026q4": TEMPORAL_PENDING}
    assert bundle["policy"]["issueSummary"] == "zoop-issue-summary-policy-1"
    assert digest_of(bundle) == pins["bundleDigest"] == wire["verification"]["bundleDigest"] == oracle["receipt"]["bundleDigest"]
    delivered = [v for issue in bundle["issues"] for v in issue["fieldVerdicts"]]
    assert len(delivered) == 5 and {v["decision"] for v in delivered} == {"ALLOW", "HOLD", "REJECT"}      # non-empty, every decision, from the real producer
    assert {i["id"]: i["fieldProvenance"]["withheld"] for i in bundle["issues"]} == {"issue:supply-2026q3": ["eventTime"], "issue:factory-2026q4": ["period"]}
    assert verdict_problems(bundle, verdict_world) == []
    supply = next(i for i in bundle["issues"] if i["id"] == "issue:supply-2026q3")
    assert supply["eventTime"] is None and supply["timePrecision"] == "unknown" and any(m["eventTime"] == "2026-09-30" for m in supply["mentions"])
    assert producer_accepts(response.content)
    assert wire["verification"]["counts"] == bundle["counts"] == verdict_world.counts
    status = get(service, status_url(VERDICT_HANDOFF))
    assert status.status_code == 200 and "fieldVerdicts" not in status.text and "bundle" not in status.json()                 # the status never carries a verdict
    for private in (*ws.private_strings(), "operator-field-verdict"):
        assert private not in status.text


def test_verdict_content_follows_the_current_rights_and_the_pinned_operator_files_and_returns_exactly_when_they_are_restored(verdict_world, start_verdict_handoff: Start):
    ws, service = start_verdict_handoff(listed(verdict_world, VERDICT_HANDOFF))
    first = get(service, bundle_url(VERDICT_HANDOFF))
    assert first.json()["delivery"]["state"] == "current" and verdict_problems(first.json()["bundle"], verdict_world) == []
    refs = {v["decisionRef"] for issue in verdict_world.expect["verdicts"].values() for v in issue}
    assert len(refs) >= 2

    def withheld() -> str:
        code, oracle, _ = ws.direct(VERDICT_HANDOFF)
        assert code == 2 and oracle["delivery"]["status"] == "withheld" and "bundle" not in oracle
        for url in (status_url(VERDICT_HANDOFF), bundle_url(VERDICT_HANDOFF)):
            response = get(service, url)
            wire = response.json()
            assert response.status_code == 200 and wire["delivery"]["state"] == "withheld" and wire["delivery"]["reason"] == oracle["delivery"]["code"]
            assert wire["verification"] is None and wire.get("bundle") is None and wire.get("manifest") is None
            for text in (*verdict_world.private, *refs, "operator-field-verdict", "fieldVerdicts", "2026-09-30", "REJECT", "contradicted"):
                assert text not in response.text, text
        return oracle["delivery"]["code"]

    registry = json.loads(ws.originals["sources"])
    registry["sources"][0]["grant"]["enabled"] = False                        # the source right is revoked: no verdict leaves although the pins and files are unchanged
    ws.sources.write_text(canonical(registry), encoding="utf-8")
    try:
        withheld()
    finally:
        ws.restore("sources")
    ws.decisions.write_bytes(ws.originals["decisions"] + b"\n")               # the review file the verdicts live in is hash-pinned by the manifest
    try:
        assert withheld() == "decisions_changed"
    finally:
        ws.restore("decisions")
    again = get(service, bundle_url(VERDICT_HANDOFF)).json()
    assert again["delivery"]["state"] == "current" and canonical(again["bundle"]) == canonical(first.json()["bundle"])       # restored: the very same verdict bytes come back


# ---- bundle 7: the issue summary the REAL producer froze ------------------------------------------------------------------------------

def _issue(bundle: dict[str, Any], issue_id: str) -> dict[str, Any]:
    return next(i for i in bundle["issues"] if i["id"] == issue_id)


def test_the_http_bundle_carries_the_pinned_available_summary_the_real_producer_froze(summary_world, start_summary_handoff: Start):
    """NOT a literal: the installed `zoop-ai-issue-summary` (authored replay, no model) summarised the supply issue over TWO articles but cites only the first, the operator's
    decisions pinned that immutable result, the installed `zoop-ai-handoff` froze and exported it, and the service relays it byte for byte. Every expectation is the pipeline
    smoke's hand-written one (`summary_world.expect`): the claim text, the evidence union, the kinds and the exact pinned job result. The factory issue carries an operator
    HOLD period verdict, so it states `temporal-review-pending` with no job and no source."""
    world = summary_world
    pins, expect = world.handoffs[SUMMARY_HANDOFF], world.expect
    ws, service = start_summary_handoff(listed(world, SUMMARY_HANDOFF))
    code, oracle, _ = ws.direct(SUMMARY_HANDOFF)
    assert code == 0 and oracle["delivery"]["status"] == "current" and oracle["usage"] == {"providerCalls": 0, "modelCalls": 0}
    response = get(service, bundle_url(SUMMARY_HANDOFF))
    wire = response.json()
    assert response.status_code == 200 and wire["delivery"]["state"] == "current", response.text[:300]
    bundle = wire["bundle"]
    assert bundle == oracle["bundle"] and canonical(bundle) == canonical(oracle["bundle"]) and bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8"
    assert digest_of(bundle) == pins["bundleDigest"] == wire["verification"]["bundleDigest"] == oracle["receipt"]["bundleDigest"]
    assert bundle["policy"]["issueSummary"] == "zoop-issue-summary-policy-1" and producer_accepts(response.content)
    assert summary_problems(bundle, world) == []
    supply, factory = _issue(bundle, expect["supply"]), _issue(bundle, expect["factory"])
    summary = supply["summary"]
    assert summary["status"] == "available" and [c["text"] for c in summary["claims"]] == expect["claimTexts"] and summary["text"] == "\n".join(expect["claimTexts"])
    basis = basis_of(bundle, bundle["issues"].index(supply))
    quote_ids, cited = {q["evidenceId"] for q in basis["quotes"]}, set(summary["evidenceIds"])
    assert len(basis["quotes"]) == 2 and len({q["articleId"] for q in basis["quotes"]}) == 2, "two mentions of two articles are the summary's input"
    assert summary["source"]["basisDigest"] == digest_of(basis) and cited and cited < quote_ids, "the summary cites FEWER quotes than it read: every input quote, cited or not, is part of its basis"
    assert (summary["source"]["jobId"], summary["source"]["inputDigest"], summary["source"]["resultDigest"]) == tuple(expect["pin"][k] for k in ("jobId", "inputDigest", "resultDigest"))
    assert factory["summary"] == TEMPORAL_PENDING and any(v["decision"] == "HOLD" for v in factory["fieldVerdicts"]), "any HOLD leaves exactly temporal-review-pending"
    status = get(service, status_url(SUMMARY_HANDOFF))
    shown = json.dumps(status.json(), ensure_ascii=False)
    assert status.status_code == 200 and "bundle" not in status.json() and not json_keys(status.json()) & SUMMARY_KEYS and not [t for t in (*expect["claimTexts"], expect["job"]) if t in shown]
    assert str(world.summaries) not in json.dumps(ws.env()), "the service is never told where a summary ledger is"
    service.stop()
    assert not [s for s in (*expect["claimTexts"], expect["job"], str(world.summaries), *world.private) if s in service.logs()]


def test_a_job_coded_unavailable_summary_is_relayed_with_its_pinned_source_and_none_of_the_failed_claims(summary_withheld_world, start_summary_withheld_handoff: Start):
    world = summary_withheld_world
    pins, expect = world.handoffs[SUMMARY_WITHHELD_HANDOFF], world.expect
    ws, service = start_summary_withheld_handoff(listed(world, SUMMARY_WITHHELD_HANDOFF))
    code, oracle, _ = ws.direct(SUMMARY_WITHHELD_HANDOFF)
    response = get(service, bundle_url(SUMMARY_WITHHELD_HANDOFF))
    wire = response.json()
    assert code == 0 and response.status_code == 200 and wire["delivery"]["state"] == "current", response.text[:300]
    bundle = wire["bundle"]
    assert bundle == oracle["bundle"] and digest_of(bundle) == pins["bundleDigest"] and producer_accepts(response.content)
    assert summary_problems(bundle, world) == []
    held = _issue(bundle, expect["supply"])["summary"]
    assert held["status"] == "unavailable" and held["code"] == "verifier-hold" and set(held) == {"status", "code", "source"} and held["source"] is not None
    assert _issue(bundle, expect["factory"])["summary"] == NOT_REQUESTED
    shown = json.dumps(wire, ensure_ascii=False)
    assert not [t for t in expect["claimTexts"] if t in shown], "the claims of a job the verifier held are never part of the handoff"


@pytest.mark.parametrize("name", sorted(FORGERIES))
def test_a_forged_summary_is_refused_over_the_real_command_even_when_every_digest_and_the_pin_match(summary_world, start_summary_handoff: Start, tmp_path, name):
    """The REAL installed export, one summary forgery applied with the producer's own functions and every digest, the receipt and the operator's pin re-derived for the forged
    bytes: the producer's validator refuses the bundle, and so does the service's closed model (500 `runtime_contract_mismatch`, no bundle, no claim text, no digest) on both
    routes. Tampered content, a hidden (geography-only) evidence id, a wrong basis, a wrong provenance, a deterministic code without its condition and a dropped summary."""
    world = summary_world
    wrapper = forge_command(tmp_path / f"forge-{name}.py", FORGERIES[name])
    code, forged, _ = RealWorkspace(tmp_path / f"probe-{name}", world, []).direct(SUMMARY_HANDOFF, command=wrapper)
    assert code == 0, forged
    bundle = forged["bundle"]
    assert digest_of(bundle) != world.handoffs[SUMMARY_HANDOFF]["bundleDigest"] and not producer_accepts(json.dumps({"bundle": bundle}, ensure_ascii=False).encode("utf-8"))
    entry = {"principal": PRINCIPAL, "handoffId": SUMMARY_HANDOFF, "manifestDigest": bundle["manifestDigest"], "bundleDigest": digest_of(bundle)}
    _, service = start_summary_handoff([entry], command=wrapper)
    for url in (bundle_url(SUMMARY_HANDOFF), status_url(SUMMARY_HANDOFF)):
        response = get(service, url)
        assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch" and not error_of(response)["retryable"], (name, response.text[:300])
        shown = json.dumps(response.json(), ensure_ascii=False)
        assert "bundle" not in response.json() and not [t for t in world.expect["claimTexts"] if t in shown] and digest_of(bundle) not in response.text


def test_the_summary_follows_the_current_rights_and_the_pinned_operator_files_and_returns_exactly_when_they_are_restored(summary_world, start_summary_handoff: Start):
    world, expect = summary_world, summary_world.expect
    ws, service = start_summary_handoff(listed(world, SUMMARY_HANDOFF))
    first = get(service, bundle_url(SUMMARY_HANDOFF)).json()
    assert first["delivery"]["state"] == "current" and summary_problems(first["bundle"], world) == []

    def withheld() -> str:
        code, oracle, _ = ws.direct(SUMMARY_HANDOFF)
        assert code == 2 and oracle["delivery"]["status"] == "withheld" and "bundle" not in oracle
        for url in (status_url(SUMMARY_HANDOFF), bundle_url(SUMMARY_HANDOFF)):
            response = get(service, url)
            wire = response.json()
            shown = json.dumps(wire, ensure_ascii=False)
            assert response.status_code == 200 and wire["delivery"]["state"] == "withheld" and wire["delivery"]["reason"] == oracle["delivery"]["code"]
            assert wire["verification"] is None and wire.get("bundle") is None and wire.get("manifest") is None
            assert not json_keys(wire) & SUMMARY_KEYS and not [t for t in (*expect["claimTexts"], expect["job"]) if t in shown]
        return oracle["delivery"]["code"]

    registry = json.loads(ws.originals["sources"])
    # The summary READ two articles but cites one. The second article lives in its OWN source with its OWN grant: revoking EITHER source's grant withholds the whole handoff, summary
    # included, so the right of every input - not only of the cited ones - gates the summary. The source of the uncited article is derived from the delivered bundle and equals the
    # pipeline world's hand-written one.
    supply_issue = _issue(first["bundle"], expect["supply"])
    basis = basis_of(first["bundle"], first["bundle"]["issues"].index(supply_issue))
    articles = {a["articleId"]: a for a in first["bundle"]["articles"]}
    sources_of = lambda quotes: {o["sourceId"] for q in quotes for o in articles[q["articleId"]]["observations"]}  # noqa: E731
    cited_quotes = [q for q in basis["quotes"] if q["evidenceId"] in supply_issue["summary"]["evidenceIds"]]
    uncited_quotes = [q for q in basis["quotes"] if q["evidenceId"] not in supply_issue["summary"]["evidenceIds"]]
    cited_sources, uncited_sources = sources_of(cited_quotes), sources_of(uncited_quotes)
    assert cited_quotes and uncited_quotes and uncited_sources and not cited_sources & uncited_sources, "the uncited article has a source of its own"
    assert uncited_sources | cited_sources <= {s["sourceId"] for s in registry["sources"]}
    if expect["uncited"] is not None:
        assert uncited_sources == {expect["uncited"]["source"]} and expect["uncited"]["evidence_id"] in {q["evidenceId"] for q in uncited_quotes}
    for revoked in sorted(cited_sources | uncited_sources):
        broken = copy.deepcopy(registry)
        next(s for s in broken["sources"] if s["sourceId"] == revoked)["grant"]["enabled"] = False      # ONE source right is revoked: no summary leaves, pins and files unchanged
        ws.sources.write_text(canonical(broken), encoding="utf-8")
        try:
            withheld()
        finally:
            ws.restore("sources")
        restored = get(service, bundle_url(SUMMARY_HANDOFF)).json()
        assert restored["delivery"]["state"] == "current" and canonical(restored["bundle"]) == canonical(first["bundle"]), revoked
    ws.decisions.write_bytes(ws.originals["decisions"] + b"\n")               # the file that pins the summary is hash-pinned by the manifest
    try:
        assert withheld() == "decisions_changed"
    finally:
        ws.restore("decisions")
    again = get(service, bundle_url(SUMMARY_HANDOFF)).json()
    assert again["delivery"]["state"] == "current" and canonical(again["bundle"]) == canonical(first["bundle"])       # restored: the very same summary bytes come back
