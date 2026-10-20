"""The handoff door over the REAL installed `zoop-ai-handoff` and an actual two-S3-job world (no stand-in command).

What a stand-in cannot prove, this does: the argv the service builds is accepted by the real command, the real exit codes and canonical stdout are interpreted as
documented, the bundle the HTTP response delivers equals the real CLI export byte for byte in canonical form and is accepted by the PRODUCER's own validator,
the closed bundle model accepts every shape the real producer emits (all three relation types, structural basis, exclusions, a second source job), and the real
current-authority checks (a revoked grant, an operator file change) withhold content over HTTP exactly as the CLI withholds it. The world is built by the
pipeline's interpreter from authored replay: no model, provider or network. Expectations are hand-written from the authored world (`build_handoff_world.py`
reads them from the pipeline smoke's own hand-written `expected`), never derived from the service.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import time
from typing import Any, Callable

import pytest

from handoff_support import bundle_url, status_url
from real_handoff_support import RealWorkspace, digest_of, pin_entry, producer_accepts, producer_accepts_manifest
from relation_support import PIPELINE
from support import canonical
from zoop_ai_service.handoff_doc import example_bundle, example_manifest

PRINCIPAL = "handoffer"
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
    assert (bundle["readiness"], wire["verification"]["provenance"]) == ({"app": "import-pending", "evidenceRegistration": "not-registered", "publicActivation": "none",
                                                                          "graphDb": "none"}, bundle["provenance"])
    assert producer_accepts(response.content)
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
