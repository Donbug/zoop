"""The read-only handoff door over a REAL service process (uvicorn on 127.0.0.1) and a test-owned stand-in for `zoop-ai-handoff`.

The stand-in records the argv, stdin, environment, working directory and timing the service gave it and answers what a test scripted, so this file proves the
transport and the delivery rules: fixed argv, minimal environment, auth and allowlist order, pins, the closed bundle model, byte-exact canonical relay, withheld
and refused shapes, busy and deadline behavior, concurrency and logs. It does not prove the pipeline: the real installed `zoop-ai-handoff` over an actual
two-job world is `pipeline_tests/test_handoff_real_cli.py` and `scripts/handoff_service_smoke.py`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from handoff_support import (HANDOFF, OTHER_HANDOFF, PRINCIPAL, SOURCE_DATA, HandoffWorkspace, bundle_url, envelope, error_output, export_entry, full_bundle,
                             manifest_of, mutated, status_url, structural, withheld_output)
from support import canonical, document_replay
from zoop_ai_service.handoff_doc import digest, example_bundle, pins

BASE_KEYS = {"PATH", "LANG", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "PYTHONNOUSERSITE", "PYTHONUTF8"}
OS_ADDED = {"__CF_USER_TEXT_ENCODING", "LC_CTYPE"}   # the operating system or the interpreter may add these to any child
NODE = shutil.which("node")
JS_DIGEST = r"""
const fs = require('fs'), crypto = require('crypto');
const canon = (v) => Array.isArray(v) ? '[' + v.map(canon).join(',') + ']'
  : (v !== null && typeof v === 'object') ? '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}' : JSON.stringify(v);
const doc = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(crypto.createHash('sha256').update(canon(doc.bundle), 'utf8').digest('hex'));
"""
JS_MANIFEST_DIGEST = JS_DIGEST.replace("doc.bundle", "doc.manifest")


HANDOFF_ROOT = "/internal/v1/graph-handoffs"


def workspace(tmp_path: Path, name: str = "h", **kwargs: Any) -> HandoffWorkspace:
    return HandoffWorkspace(tmp_path / name, **kwargs)


def tree(*paths: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in paths:
        for item in ([path] if path.is_file() else sorted(path.rglob("*"))):
            if item.is_file():
                found[str(item)] = hashlib.sha256(item.read_bytes()).hexdigest()
    return found


def operator_state(ws: HandoffWorkspace) -> dict[str, str]:
    return tree(ws.handoff_state, ws.relation_state, ws.extraction_state, ws.ingestion_state, ws.sources, ws.canonical, ws.decisions, ws.bindings, ws.exports)


def error_of(response) -> dict[str, Any]:
    body = response.json()
    assert body["schemaVersion"] == "zoop-ai-internal-handoff-1" and set(body) == {"schemaVersion", "error"}, body
    assert set(body["error"]) == {"code", "retryable", "requestId", "runtimeCode", "field"}
    assert body["error"]["requestId"] == response.headers["x-request-id"]
    return body["error"]


def anonymous(error: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in error.items() if key != "requestId"}


def serve(ws: HandoffWorkspace, bundle: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Script the stand-in with a producer-shaped export of `bundle` and list exactly that bundle's pins for the principal."""
    ws.script({"mode": "result", "output": envelope(bundle, **overrides)})
    ws.write_exports([export_entry(bundle=bundle)])
    return bundle


def sha(bundle: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(bundle).encode("utf-8")).hexdigest()


def get(service, url: str, as_: str = PRINCIPAL):
    return service.request("GET", url, as_=as_)


# ---- off by default, auth and framing ----------------------------------------------------------------------------------

def test_without_the_group_every_handoff_route_answers_409_after_authentication(start):
    service = start(replay=document_replay())
    for url in (status_url(), bundle_url()):
        refused = get(service, url)
        assert refused.status_code == 409 and error_of(refused)["code"] == "execution_unavailable"
        assert error_of(get(service, url, None))["code"] == "authentication_required"
        assert error_of(get(service, url, "reader"))["code"] == "scope_denied"   # authentication and scope come before everything
        assert error_of(get(service, url, "grapher"))["code"] == "scope_denied"  # graph.read is not handoff.read


def test_authentication_scope_and_routing_use_the_handoff_envelope_and_never_start_a_child(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    unauthenticated = get(service, status_url(), None)
    assert unauthenticated.status_code == 401 and unauthenticated.headers["www-authenticate"] == "Bearer"
    assert error_of(unauthenticated)["code"] == "authentication_required"
    assert error_of(service.request("GET", status_url(), token="u" * 43))["code"] == "authentication_required"
    for reader in ("reader", "submitter", "viewer", "grapher"):   # every other scope is refused, however privileged
        denied = get(service, bundle_url(), reader)
        assert denied.status_code == 403 and error_of(denied)["code"] == "scope_denied"
    posted = service.request("POST", status_url(), as_=PRINCIPAL, body={})
    assert posted.status_code == 405 and error_of(posted)["code"] == "method_not_allowed"
    for url in (HANDOFF_ROOT, HANDOFF_ROOT + "/", f"{bundle_url()}/x", f"{status_url()}/export"):
        missing = get(service, url)
        assert missing.status_code in (404, 422) and error_of(missing)["code"] in {"route_not_found", "invalid_request"}, url   # no list route exists
    assert ws.calls() == []



@pytest.mark.parametrize("url", [f"{HANDOFF_ROOT}/{HANDOFF}?x=1", f"{HANDOFF_ROOT}/{HANDOFF}/bundle?path=/etc/passwd", f"{HANDOFF_ROOT}/{HANDOFF}?handoffId=other",
                                 f"{HANDOFF_ROOT}/bad%20id", f"{HANDOFF_ROOT}/{'h' * 201}", f"{HANDOFF_ROOT}/{HANDOFF}/bundle?command=freeze",
                                 f"{HANDOFF_ROOT}/%EA%B0%80"])
def test_any_query_parameter_or_malformed_id_is_422_and_never_reaches_a_child(tmp_path, start, url):
    ws = workspace(tmp_path)
    response = get(start(workspace=ws), url)
    error = error_of(response)
    assert response.status_code == 422 and error["code"] == "invalid_request" and error["retryable"] is False, (url, response.status_code, error)
    assert ws.calls() == []


# ---- a current read: the exact child contract -----------------------------------------------------------------------------

def test_a_bundle_read_runs_one_fixed_export_child_with_server_owned_argv_and_a_minimal_environment(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws, env={"ZOOP_GRAPH_PASSWORD": "pw-secret", "ZOOP_GRAPH_USER": "neo", "OPENAI_API_KEY": "sk-secret",
                                       "TYPESAFE_API_KEY": "ts-secret", "ZOOP_AI_API_KEY": "ai-secret", "NEO4J_PASSWORD": "n4j-secret"})
    before = operator_state(ws)
    response = get(service, bundle_url())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store" and response.headers["x-content-type-options"] == "nosniff"
    (call,) = ws.calls()
    assert call["argv"] == ["export", "--state-dir", str(ws.handoff_state), "--relation-state-dir", str(ws.relation_state), "--extraction-state-dir",
                            str(ws.extraction_state), "--ingestion-state-dir", str(ws.ingestion_state), "--sources", str(ws.sources), "--canonical",
                            str(ws.canonical), "--decisions", str(ws.decisions), "--bindings", str(ws.bindings)]
    assert json.loads(call["stdin"]) == {"schemaVersion": "zoop-ai-handoff-1", "handoffId": HANDOFF}
    names = set(call["env"])
    assert BASE_KEYS | {"ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"} <= names <= BASE_KEYS | {"ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"} | OS_ADDED
    assert not [name for name in names if name.startswith(("ZOOP_AI_SERVICE", "ZOOP_AI_LIVE", "ZOOP_AI_API", "ZOOP_AI_PROVIDER", "ZOOP_GRAPH", "OPENAI", "TYPESAFE", "NEO4J"))]
    assert "pw-secret" not in json.dumps(call["env"]) and "sk-secret" not in json.dumps(call["env"])
    assert Path(call["cwd"]).resolve() == (ws.state / "transport").resolve()
    assert not any(str(path) in json.dumps(call["argv"]) for path in (ws.exports,))   # the allowlist is never an argument of the child
    assert operator_state(ws) == before and not list((ws.state / "transport").iterdir())   # nothing written, no transport file left behind


def test_a_current_bundle_is_the_producers_artifact_byte_for_byte_and_hashes_to_the_pin(tmp_path, start):
    ws = workspace(tmp_path)
    bundle = example_bundle()
    response = get(start(workspace=ws), bundle_url())
    wire = response.json()
    assert response.status_code == 200 and set(wire) == {"schemaVersion", "handoffId", "state", "publication", "appImport", "delivery", "verification",
                                                         "manifest", "bundle", "observedAt"}
    assert (wire["state"], wire["publication"], wire["appImport"]) == ("ready", "not-published", "pending")
    assert wire["delivery"] == {"state": "current", "reason": None, "checkedAt": "2026-10-16T03:00:00.123456+00:00"}
    assert wire["bundle"] == bundle                                    # no added key, no dropped key, no default, no normalised value
    assert sha(wire["bundle"]) == pins(bundle)["bundleDigest"] == wire["verification"]["bundleDigest"]
    assert wire["verification"] == {**pins(bundle), "counts": bundle["counts"], "sources": 1, "provenance": bundle["provenance"]}
    assert wire["verification"]["bundleBytes"] == len(canonical(bundle).encode("utf-8"))
    manifest = manifest_of(bundle)                                      # the frozen manifest, carried beside the bundle from this one response
    assert wire["manifest"] == manifest and sha(wire["manifest"]) == digest(manifest) == bundle["manifestDigest"] == wire["verification"]["manifestDigest"]
    assert set(wire["manifest"]) == {"schemaVersion", "handoffId", "sourceKind", "policyVersion", "sources", "files"}


@pytest.mark.skipif(NODE is None, reason="the cross-language check needs node")
def test_the_response_manifest_hashes_to_the_manifest_digest_in_another_language(tmp_path, start):
    ws = workspace(tmp_path)
    response = get(start(workspace=ws), bundle_url())
    wire = response.json()
    digest_js = subprocess.run([NODE, "-e", JS_MANIFEST_DIGEST], input=response.content, capture_output=True, timeout=60, check=True).stdout.decode()
    assert digest_js == wire["verification"]["manifestDigest"] == wire["bundle"]["manifestDigest"]


def test_a_status_never_carries_the_manifest_or_its_source_pins(tmp_path, start):
    ws = workspace(tmp_path)
    response = get(start(workspace=ws), status_url())
    assert response.status_code == 200 and "manifest" not in response.json()
    for text in ("s3-synthetic-relation", "s2-synthetic-extraction", "sourceKind", "policyVersion", "6" * 64, "d" * 64):
        assert text not in response.text


def test_a_missing_manifest_is_a_contract_mismatch_on_both_routes_never_a_bundle_without_it(tmp_path, start):
    ws = workspace(tmp_path)
    output = envelope()
    del output["manifest"]
    ws.script({"mode": "result", "output": output})
    service = start(workspace=ws)
    for url in (status_url(), bundle_url()):
        response = get(service, url)
        assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch" and error_of(response)["retryable"] is False
        assert "bundle" not in response.json() and "KRX:005930" not in response.text


def _tampered(change) -> dict[str, Any]:
    bundle = example_bundle()
    manifest = manifest_of(bundle)
    change(manifest)
    return envelope(bundle, manifest=manifest)


@pytest.mark.parametrize("change", [
    lambda m: m["sources"][0].update(reviewDigest="a" * 64),                      # a source pin the bundle did not use: wrong digest AND wrong pin
    lambda m: m["sources"][0]["upstream"].update(digest="a" * 64),
    lambda m: m["sources"][0]["relation"].update(inputDigest="a" * 64),
    lambda m: m["sources"].append({**m["sources"][0], "relation": {"jobId": "s3-other", "inputDigest": "1" * 64}}),
    lambda m: m["files"].update(bindings="a" * 64),
    lambda m: m.update(handoffId=OTHER_HANDOFF),
    lambda m: m.update(sourceKind="actual"),
])
def test_a_manifest_that_does_not_hash_to_the_manifest_digest_or_disagrees_with_the_bundle_is_a_binding_mismatch(tmp_path, start, change):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": _tampered(change)})
    response = get(start(workspace=ws), bundle_url())
    assert response.status_code == 500 and error_of(response)["code"] == "runtime_binding_mismatch" and error_of(response)["retryable"] is False
    assert "bundle" not in response.json() and "KRX:005930" not in response.text and "s3-synthetic-relation" not in response.text


def test_a_manifest_that_matches_every_digest_but_carries_an_unknown_field_is_refused_by_the_closed_model(tmp_path, start):
    ws = workspace(tmp_path)
    bundle = example_bundle()
    manifest = manifest_of(bundle)
    manifest["operatorNote"] = "/private/operator/path"
    bundle["manifestDigest"] = digest(manifest)                      # self-consistent: only the closed model can refuse it
    serve(ws, bundle, manifest=manifest)
    service = start(workspace=ws)
    for url in (status_url(), bundle_url()):
        response = get(service, url)
        assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch" and error_of(response)["retryable"] is False
        assert "/private/operator/path" not in response.text and "bundle" not in response.json()
    for change in (lambda m: m["files"].update(extra="x"), lambda m: m["sources"][0]["upstream"].update(extra="x")):   # nested: refused, never relayed
        ws.script({"mode": "result", "output": _tampered(change)})
        response = get(service, bundle_url())
        assert response.status_code == 500 and error_of(response)["code"] in {"runtime_binding_mismatch", "runtime_contract_mismatch"}
        assert '"extra"' not in response.text and "bundle" not in response.json()


def test_a_withheld_answer_carries_no_manifest_and_no_source_pin(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": withheld_output(code="source_unauthorized"), "exit": 2})
    service = start(workspace=ws)
    for url in (status_url(), bundle_url()):
        response = get(service, url)
        wire = response.json()
        assert response.status_code == 200 and wire["delivery"]["state"] == "withheld" and wire.get("manifest") is None and wire.get("bundle") is None
        for text in ("s3-synthetic-relation", "s2-synthetic-extraction", "sourceKind", "6" * 64, "d" * 64, *SOURCE_DATA):
            assert text not in response.text


@pytest.mark.skipif(NODE is None, reason="the cross-language check needs node")
def test_the_response_bundle_hashes_to_the_pin_in_another_language_after_a_plain_json_round_trip(tmp_path, start):
    """A JavaScript consumer parses the HTTP body and serialises with sorted keys and its own string escaping: the SHA-256 is the producer's pin."""
    ws = workspace(tmp_path)
    tricky = mutated(lambda b: (b["articles"][0].update(title='제목 "인용" \\ \u2028 \U0001F600 \x7f \t\n', url="https://example.invalid/가/\u00e9"),
                                b["articles"][0].update(publishedAt="2026-09-30T01:00:00Z"), b["companies"][0].update(label="합성\u0301기업 \u0000")))
    serve(ws, tricky)
    response = get(start(workspace=ws), bundle_url())
    assert response.status_code == 200 and response.json()["bundle"] == tricky
    digest = subprocess.run([NODE, "-e", JS_DIGEST], input=response.content, capture_output=True, timeout=60, check=True).stdout.decode()
    assert digest == pins(tricky)["bundleDigest"] == response.json()["verification"]["bundleDigest"]
    assert response.json()["bundle"]["articles"][0]["publishedAt"] == "2026-09-30T01:00:00Z"   # a timestamp string is never re-formatted


def test_every_variant_of_the_closed_model_is_relayed_exactly(tmp_path, start):
    ws = workspace(tmp_path)
    bundle = serve(ws, full_bundle())   # structural and FOLLOWS relations, a representative, two sources, both exclusion detail shapes and two mentions
    wire = get(start(workspace=ws), bundle_url()).json()
    assert wire["bundle"] == bundle and sha(wire["bundle"]) == wire["verification"]["bundleDigest"]
    items = wire["bundle"]["exclusions"]["items"]
    assert "detail" not in items[0] and items[1]["detail"] == {"fields": ["title", "eventTime"]}   # an absent optional key stays absent, never null
    first, second = wire["bundle"]["issues"][0]["mentions"]
    assert (first["mentionId"], first["verification"], first["background"]) == (second["mentionId"], "none", False) and first["documentId"] != second["documentId"]
    assert first["participants"][1] == {"sourceCompanyId": None, "companyId": None, "name": "합성 협력사", "role": "수요자"}   # null stays null, role is S2's text
    assert (second["eventTime"], second["period"], second["background"], second["participants"]) == (None, "2026Q4", True, [])   # not copied from the merged issue


def test_a_large_bundle_is_relayed_whole_and_a_status_of_it_stays_small(tmp_path, start):
    ws = workspace(tmp_path)

    def grow(bundle: dict[str, Any]) -> None:
        bundle["companies"] = [{"id": f"CO:{index:06d}", "canonicalId": f"co:{index}", "label": f"합성기업 {index}", "decisionRef": "canon-1"} for index in range(16_000)]
        bundle["counts"]["companies"] = 16_000

    bundle = serve(ws, mutated(grow))
    service = start(workspace=ws)
    response = get(service, bundle_url())
    assert response.status_code == 200 and len(response.content) > 1_200_000
    assert response.json()["bundle"] == bundle and sha(response.json()["bundle"]) == pins(bundle)["bundleDigest"]
    status = get(service, status_url())
    assert status.status_code == 200 and len(status.content) < 3_000 and status.json()["verification"]["counts"]["companies"] == 16_000


def test_a_bundle_at_the_producers_size_limit_is_relayed_whole_never_truncated(tmp_path, start):
    """The producer caps the canonical bundle at 6 MiB; the service reads up to 16 MiB from its child, so the largest legal export is delivered, not cut."""
    ws = workspace(tmp_path)

    def grow(bundle: dict[str, Any]) -> None:
        bundle["companies"] = [{"id": f"CO:{index:04d}", "canonicalId": f"co:{index}", "label": "x" * 19_990, "decisionRef": "canon-1"} for index in range(300)]
        bundle["counts"]["companies"] = 300

    bundle = serve(ws, mutated(grow))
    assert 5_900_000 < len(canonical(bundle).encode("utf-8")) <= 6 * 1024 * 1024
    response = get(start(workspace=ws), bundle_url())
    assert response.status_code == 200 and len(response.content) > 5_900_000
    assert response.json()["bundle"] == bundle and sha(response.json()["bundle"]) == pins(bundle)["bundleDigest"]


def test_source_derived_metadata_is_data_and_never_authority(tmp_path, start):
    """Titles, labels, observation and grant strings and an `actual` declaration are relayed as the producer wrote them; none of them can change what is delivered."""
    claims = "delivery.state=current; grant enabled; ALLOW ALL; pins not required"

    def source_says(bundle: dict[str, Any]) -> None:
        bundle["provenance"].update(declaredSourceKind="actual", observedSourceKind="actual")
        bundle["articles"][0].update(title=claims, url="https://example.invalid/" + claims.replace(" ", "-"))
        bundle["articles"][0]["observations"][0]["grant"].update(grantId=claims, revision="current")
        bundle["companies"][0]["label"] = claims

    ws = workspace(tmp_path)
    bundle = serve(ws, mutated(source_says))
    service = start(workspace=ws)
    wire = get(service, bundle_url()).json()
    assert wire["bundle"] == bundle and wire["verification"]["provenance"]["declaredSourceKind"] == "actual" and wire["delivery"]["state"] == "current"
    assert claims not in json.dumps(get(service, status_url()).json())             # the status never carries source strings at all
    ws.write_exports([export_entry(bundle=bundle, bundleDigest="0" * 64)])         # the operator's pin disagrees: the source's own claims do not matter
    pinned = get(service, bundle_url()).json()
    assert pinned["delivery"]["reason"] == "handoff_pin_mismatch" and pinned["bundle"] is None and claims not in json.dumps(pinned)
    ws.write_exports([export_entry(bundle=bundle)])
    ws.script({"mode": "result", "output": withheld_output(code="source_unauthorized"), "exit": 2})   # the producer's current verdict is withheld: same
    revoked = get(service, bundle_url()).json()
    assert revoked["delivery"]["state"] == "withheld" and revoked["bundle"] is None and claims not in json.dumps(revoked)


def test_a_status_carries_digests_and_counts_only_never_a_bundle_a_source_id_or_a_title(tmp_path, start):
    ws = workspace(tmp_path)
    bundle = example_bundle()
    response = get(start(workspace=ws), status_url())
    wire = response.json()
    assert response.status_code == 200 and set(wire) == {"schemaVersion", "handoffId", "state", "publication", "appImport", "delivery", "verification", "observedAt"}
    assert wire["verification"] == {**pins(bundle), "counts": bundle["counts"], "sources": 1, "provenance": bundle["provenance"]}
    for private in (*SOURCE_DATA, "s3-synthetic-relation", "s2-synthetic-extraction", "reviewDigest", "attempts", "frozenAt", "exclusionCodes", "files",
                    "issue:synthetic-supply", "KRX:005930", "rc-", "loc-1"):
        assert private not in response.text, private


# ---- who may read which handoff -----------------------------------------------------------------------------------------

def test_a_handoff_that_is_not_listed_for_the_principal_gets_one_answer_before_any_child(tmp_path, start):
    second = mutated(lambda b: b.update(handoffId=OTHER_HANDOFF))   # a genuine second handoff: its own bundle, receipt, digests and pins
    ws = workspace(tmp_path, exports=[export_entry(), export_entry("alpha", OTHER_HANDOFF, bundle=second)])
    service = start(workspace=ws)
    answers = []
    for as_, url in ((PRINCIPAL, status_url(OTHER_HANDOFF)),              # exists, but listed for another principal
                     (PRINCIPAL, status_url("handoff-never-existed")),
                     ("beta", status_url()),                              # a principal without any entry
                     (PRINCIPAL, bundle_url(OTHER_HANDOFF)), ("alpha", bundle_url(HANDOFF))):
        denied = get(service, url, as_)
        assert denied.status_code == 403
        answers.append(anonymous(error_of(denied)))
    assert all(answer == {"code": "handoff_not_allowed", "retryable": False, "runtimeCode": None, "field": None} for answer in answers)
    assert ws.calls() == []
    ws.script({"mode": "result", "output": envelope(second, handoff_id=OTHER_HANDOFF)})
    own = get(service, bundle_url(OTHER_HANDOFF), "alpha")
    assert own.status_code == 200 and own.json()["handoffId"] == own.json()["bundle"]["handoffId"] == OTHER_HANDOFF   # alpha's own entry works
    assert own.json()["verification"]["bundleDigest"] == pins(second)["bundleDigest"] != pins(example_bundle())["bundleDigest"]
    assert [json.loads(call["stdin"])["handoffId"] for call in ws.calls()] == [OTHER_HANDOFF]


def test_the_allowlist_is_read_on_every_request_and_a_removed_entry_takes_effect_at_once(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    assert get(service, bundle_url()).status_code == 200
    ws.write_exports([])
    assert error_of(get(service, bundle_url()))["code"] == "handoff_not_allowed"
    assert len(ws.calls()) == 1   # the removed entry never started a child
    ws.exports.unlink()
    unreadable = get(service, bundle_url())
    assert unreadable.status_code == 503 and unreadable.headers["retry-after"] and error_of(unreadable)["code"] == "service_configuration_invalid"
    assert len(ws.calls()) == 1


def test_an_entry_revoked_while_the_child_runs_returns_nothing_of_its_answer(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": envelope(), "rewrite": {"path": str(ws.exports), "content": json.dumps({"schemaVersion": "zoop-ai-handoff-exports-1", "handoffs": []})}})
    response = get(start(workspace=ws), bundle_url())
    assert response.status_code == 403 and error_of(response)["code"] == "handoff_not_allowed"
    for text in (*SOURCE_DATA, "ev-", "KRX:005930"):
        assert text not in response.text
    assert len(ws.calls()) == 1


# ---- the pins -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["manifestDigest", "bundleDigest"])
def test_a_pin_that_differs_from_what_the_ledger_holds_is_withheld_on_both_routes_with_no_count_or_bundle(tmp_path, start, field):
    ws = workspace(tmp_path)
    ws.write_exports([export_entry(**{field: "0" * 64})])
    service = start(workspace=ws)
    for url in (status_url(), bundle_url()):
        response = get(service, url)
        wire = response.json()
        assert response.status_code == 200 and wire["delivery"] == {"state": "withheld", "reason": "handoff_pin_mismatch", "checkedAt": None}, response.text[:400]
        assert wire["verification"] is None and wire.get("bundle") is None and wire["state"] == "ready"
        for text in (*SOURCE_DATA, pins(example_bundle())["bundleDigest"], "KRX:005930"):
            assert text not in response.text


def test_a_bundle_that_hashes_differently_than_the_receipt_says_is_a_binding_mismatch_never_a_delivery(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    for receipt in ({"bundleDigest": "1" * 64}, {"contentDigest": "2" * 64}, {"manifestDigest": "3" * 64}, {"bundleBytes": 5}, {"handoffId": OTHER_HANDOFF}):
        ws.script({"mode": "result", "output": envelope(receipt=receipt)})
        response = get(service, bundle_url())
        assert response.status_code == 500 and error_of(response)["code"] == "runtime_binding_mismatch" and error_of(response)["retryable"] is False, receipt
        assert "bundle" not in response.json() and "KRX:005930" not in response.text


def test_a_bundle_whose_own_digest_or_identity_disagrees_with_its_content_is_refused(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    for change, code in ((lambda b: b["digests"].update(content="4" * 64), "runtime_binding_mismatch"),
                         (lambda b: b.update(handoffId=OTHER_HANDOFF), "runtime_binding_mismatch"),
                         (lambda b: b.update(schemaVersion="zoop-graph-handoff-bundle-unsupported"), "runtime_contract_mismatch")):
        bundle = example_bundle()
        change(bundle)
        serve(ws, bundle)
        response = get(service, bundle_url())
        assert response.status_code == 500 and error_of(response)["code"] == code and "KRX:005930" not in response.text


def test_an_answer_for_another_handoff_is_a_500_binding_mismatch(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": envelope(handoff_id=OTHER_HANDOFF)})
    response = get(start(workspace=ws), status_url())
    assert response.status_code == 500 and error_of(response)["code"] == "runtime_binding_mismatch"


# ---- the closed bundle model, even with a self-consistent updated digest --------------------------------------------------------

def _set(path: tuple, value: Any):
    def change(bundle: dict[str, Any]) -> None:
        node = bundle
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = value
    return change


UNKNOWN = [_set(("extra",), 1), _set(("policy", "extra"), 1), _set(("policy", "files", "extra"), 1), _set(("provenance", "extra"), 1),
           _set(("sources", 0, "audit", "extra"), 1), _set(("sources", 0, "audit", "eligibility", "extra"), 1), _set(("sources", 0, "policies", "extra"), 1),
           _set(("sources", 0, "upstream", "extra"), 1), _set(("companies", 0, "extra"), "x"), _set(("issues", 0, "geography", "extra"), 1),
           _set(("issues", 0, "geography", "basis", 0, "observation", "extra"), 1), _set(("issues", 0, "sourceEvents", 0, "upstream", "extra"), 1),
           _set(("relations", 0, "provenance", "extra"), 1), _set(("relations", 0, "sourceRefs", 0, "extra"), 1), _set(("evidence", 0, "source", "extra"), 1),
           _set(("articles", 0, "observations", 0, "grant", "extra"), 1), _set(("exclusions", "extra"), 1), _set(("counts", "relations", "extra"), 1),
           _set(("checks", "extra"), 1), _set(("readiness", "extra"), 1), _set(("digests", "extra"), 1)]
WRONG_TYPE = [_set(("counts", "companies"), 1.0), _set(("companies", 0, "label"), 5), _set(("articles", 0, "observations", 0, "page"), True),
              _set(("articles", 0, "observations", 0, "page"), "1"), _set(("relations", 0, "type"), "SHARES_ISSUE"), _set(("evidence", 0, "start"), -1),
              _set(("readiness", "app"), "active"), _set(("provenance", "executionMode"), "live"), _set(("issues", 0, "timePrecision"), "second"),
              _set(("evidence", 0, "offsetUnit"), "utf16"), _set(("articles", 0, "publicationPrecision"), "date"), _set(("companies", 0, "label"), None),
              _set(("relations", 0, "provenance", "origin"), "manual-operator-review"), _set(("relations", 0, "provenance", "s3SemanticValidation"), "none"),
              _set(("sources", 0, "reviewUsed"), [["rc-" + "4" * 64, 1.0]]), _set(("sources", 0, "reviewUsed"), [["bad", 1]]),
              _set(("exclusions", "items"), [{"kind": "issue", "id": "x", "jobId": None, "code": "c", "detail": {"unknown": 1}}]),
              _set(("exclusions", "counts"), {"bad key!": 1}), _set(("checks", "producerConfirmed"), ["has space"])]


def _drop(path: tuple):
    def change(bundle: dict[str, Any]) -> None:
        node = bundle
        for step in path[:-1]:
            node = node[step]
        del node[path[-1]]
    return change


MENTION = ("issues", 0, "mentions", 0)
UNKNOWN_MENTION = [_set((*MENTION, "extra"), 1), _set((*MENTION, "participants", 0, "extra"), 1), _set((*MENTION, "publisher"), "x"), _set((*MENTION, "approval"), "none"),
                   _set((*MENTION, "fieldDecisions"), {}), _set((*MENTION, "sourceSupport"), [])]
PROVENANCE = ("issues", 0, "fieldProvenance")
UNKNOWN_PROVENANCE = [_set(("issues", 0, "fieldDecisions"), []), _set((*PROVENANCE, "extra"), 1), _set((*PROVENANCE, "fieldDecisions"), []),
                      _set((*PROVENANCE, "sameValueMentions", "extra"), []), _set((*PROVENANCE, "sameValueMentions", "geography"), []),
                      _set((*PROVENANCE, "sameValueMentions", "timePrecision"), []), _set((*PROVENANCE, "sameValueMentions", "title", 0, "extra"), 1),
                      _set((*PROVENANCE, "sameValueMentions", "title", 0, "articleId"), "doc-" + "c" * 64)]
MISSING_PROVENANCE = [_drop(PROVENANCE), *[_drop((*PROVENANCE, key)) for key in ("selection", "verification", "sameValueMentions")],
                      *[_drop((*PROVENANCE, "sameValueMentions", key)) for key in ("title", "action", "target", "eventTime", "period", "assertionStatus")],
                      *[_drop((*PROVENANCE, "sameValueMentions", "title", 0, key)) for key in ("documentId", "documentVersion", "mentionId")]]
WRONG_PROVENANCE = [_set(PROVENANCE, None), _set((*PROVENANCE, "selection"), "consensus"), _set((*PROVENANCE, "selection"), None),
                    _set((*PROVENANCE, "verification"), "verified"), _set((*PROVENANCE, "verification"), "operator-field-verdict"), _set((*PROVENANCE, "verification"), None),
                    _set((*PROVENANCE, "sameValueMentions"), None), _set((*PROVENANCE, "sameValueMentions"), []),
                    *[_set((*PROVENANCE, "sameValueMentions", key), value) for key in ("title", "action", "target", "eventTime", "period", "assertionStatus")
                      for value in ([], None, {}, [0], [None])],
                    _set((*PROVENANCE, "sameValueMentions", "title", 0, "documentVersion"), "short"), _set((*PROVENANCE, "sameValueMentions", "title", 0, "mentionId"), ""),
                    _set((*PROVENANCE, "sameValueMentions", "title", 0, "documentId"), "bad id with space"),
                    _set((*PROVENANCE, "sameValueMentions", "title"), [{"documentId": "synthetic-doc-1", "documentVersion": "a" * 64, "mentionId": "m-synthetic-1"}] * 1001)]
MISSING_MENTION = [_drop(("issues", 0, "mentions")), *[_drop((*MENTION, key)) for key in
                   ("documentId", "documentVersion", "mentionId", "articleId", "articleVersion", "verification", "title", "action", "target", "eventTime", "timePrecision",
                    "period", "assertionStatus", "background", "participants", "evidenceIds")],
                   *[_drop((*MENTION, "participants", 0, key)) for key in ("sourceCompanyId", "companyId", "name", "role")]]
WRONG_MENTION = [_set((*MENTION, "verification"), "verified"), _set((*MENTION, "verification"), None), _set((*MENTION, "background"), "false"),
                 _set((*MENTION, "background"), 0), _set((*MENTION, "background"), None), _set((*MENTION, "timePrecision"), "second"),
                 _set((*MENTION, "assertionStatus"), "confirmed"), _set((*MENTION, "assertionStatus"), None), _set((*MENTION, "action"), None),
                 _set((*MENTION, "title"), None), _set((*MENTION, "evidenceIds"), []), _set((*MENTION, "evidenceIds"), ["ev-bad"]),
                 _set((*MENTION, "articleId"), "synthetic-doc-1"), _set((*MENTION, "articleVersion"), "short"), _set((*MENTION, "documentVersion"), "short"),
                 _set((*MENTION, "mentionId"), ""), _set((*MENTION, "mentionId"), 1), _set((*MENTION, "participants"), {}),
                 _set((*MENTION, "participants", 0, "companyId"), 5), _set((*MENTION, "participants", 0, "companyId"), "bad id with space"),
                 _set((*MENTION, "participants", 0, "role"), None), _set((*MENTION, "participants", 0, "name"), None),
                 _set((*MENTION, "participants", 0, "sourceCompanyId"), 5),
                 _set(("schemaVersion",), "zoop-graph-handoff-bundle-1"), _set(("schemaVersion",), "zoop-graph-handoff-bundle-2"),
                 _set(("schemaVersion",), "zoop-graph-handoff-bundle-3"), _set(("schemaVersion",), "zoop-graph-handoff-bundle-4")]
VERDICTS = ("issues", 0, "fieldVerdicts")
VERDICT = (*VERDICTS, 0)
UNKNOWN_VERDICT = [_set((*VERDICT, "extra"), 1), _set((*VERDICT, "note"), "review prose"), _set((*VERDICT, "evidence"), []), _set((*VERDICT, "notes"), "x"),
                   _set((*VERDICT, "candidateId"), "c-1")]
MISSING_VERDICT = [_drop(VERDICTS), _drop((*PROVENANCE, "withheld")),
                   *[_drop((*VERDICT, key)) for key in ("documentId", "documentVersion", "mentionId", "field", "value", "decision", "reasonCode", "evidenceIds", "verification",
                                                         "reviewer", "decisionRef", "decisionVersion")]]
WRONG_VERDICT = [_set(VERDICTS, None), _set(VERDICTS, {}), _set((*VERDICT, "field"), "title"), _set((*VERDICT, "value"), None), _set((*VERDICT, "decision"), "PASS"),
                 _set((*VERDICT, "reasonCode"), "free text"), _set((*VERDICT, "verification"), "none"), _set((*VERDICT, "evidenceIds"), []),
                 _set((*VERDICT, "evidenceIds"), [{"start": 0, "end": 1}]), _set((*VERDICT, "evidenceIds"), ["ev-bad"]),
                 _set((*VERDICT, "decision"), "REJECT"), _set((*VERDICT, "reviewer"), "bad reviewer"), _set((*PROVENANCE, "withheld"), None),
                 _set((*PROVENANCE, "withheld"), ["title"]), _set((*PROVENANCE, "withheld"), ["eventTime", "period", "period"])]


@pytest.mark.parametrize("change", [*UNKNOWN, *UNKNOWN_MENTION, *UNKNOWN_PROVENANCE, *UNKNOWN_VERDICT], ids=lambda change: "unknown")
def test_an_unknown_nested_field_is_refused_even_when_every_digest_and_pin_was_updated_to_match(tmp_path, start, change):
    ws = workspace(tmp_path)
    bundle = serve(ws, mutated(change))        # content digest, receipt, bundle digest and the operator's pin all describe THIS bundle
    response = get(start(workspace=ws), bundle_url())
    assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch" and error_of(response)["retryable"] is False
    assert "bundle" not in response.json() and "KRX:005930" not in response.text and pins(bundle)["bundleDigest"] not in response.text


@pytest.mark.parametrize("change", [*WRONG_TYPE, *WRONG_MENTION, *MISSING_MENTION, *MISSING_PROVENANCE, *WRONG_PROVENANCE, *MISSING_VERDICT, *WRONG_VERDICT],
                         ids=lambda change: "type")
def test_a_wrongly_typed_or_out_of_contract_value_is_refused_even_with_updated_digests(tmp_path, start, change):
    ws = workspace(tmp_path)
    serve(ws, mutated(change))
    service = start(workspace=ws)
    for url in (bundle_url(), status_url()):                           # the status validates the same bundle: a count it reports is never trusted unchecked
        response = get(service, url)
        assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch", response.text[:300]


# ---- bundle 5: private path companies, structural paths and basis scopes ------------------------------------------------------------

def _structural(hops: int, middle: str = "private", *changes):
    def build(bundle: dict[str, Any]) -> None:
        structural(bundle, hops, middle)
        for change in changes:
            change(bundle)
    return build


def _path(bundle: dict[str, Any]) -> dict[str, Any]:
    return bundle["relations"][-1]["structuralPath"]


@pytest.mark.parametrize("hops,middle", [(1, "private"), (2, "private"), (2, "main"), (2, "unmapped")])
def test_a_structural_path_and_its_private_companies_are_relayed_exactly(tmp_path, start, hops, middle):
    ws = workspace(tmp_path)
    bundle = serve(ws, mutated(_structural(hops, middle)))
    wire = get(start(workspace=ws), bundle_url()).json()
    assert wire["bundle"] == bundle and sha(wire["bundle"]) == wire["verification"]["bundleDigest"]
    path = wire["bundle"]["relations"][-1]["structuralPath"]
    assert path["status"] == ("unavailable" if middle == "unmapped" else "complete")
    assert [c["id"] for c in wire["bundle"]["pathCompanies"]] == (["KRX:000270"] if (hops, middle) == (2, "private") else [])
    assert wire["verification"]["counts"]["pathCompanies"] == len(wire["bundle"]["pathCompanies"])
    assert wire["bundle"]["relations"][0]["structuralPath"] is None           # INVOLVES carries an explicit null
    assert wire["bundle"]["relations"][-1]["basis"][0]["businessScope"] == "합성 사업 범위" and wire["bundle"]["relations"][-1]["basis"][-1]["productScope"] in ("합성 제품 범위", None)


def _reverse_link(bundle: dict[str, Any]) -> None:
    link = _path(bundle)["links"][0]
    link["supplierCompanyId"], link["customerCompanyId"] = link["customerCompanyId"], link["supplierCompanyId"]


BUNDLE5_REFUSED = {
    "unavailable_with_one_basis": _structural(1, "unmapped"),
    "unavailable_reason": _structural(2, "unmapped", lambda b: _path(b).update(reason="anything")),
    "orphan_private_company": _structural(1, "private", lambda b: (b["pathCompanies"].append({"id": "KRX:009999", "canonicalId": "co:orphan", "label": "고아", "decisionRef": "c"}),
                                                                  b["counts"].update(pathCompanies=1))),
    "used_middle_missing_from_catalogue": _structural(2, "private", lambda b: (b["pathCompanies"].clear(), b["counts"].update(pathCompanies=0))),
    "private_company_also_public": _structural(2, "private", lambda b: (b["companies"].append(copy.deepcopy(b["pathCompanies"][0])), b["companies"].sort(key=lambda c: c["id"]),
                                                                        b["counts"].update(companies=len(b["companies"])))),
    "private_company_is_an_issue": _structural(2, "private", lambda b: b["pathCompanies"][0].update(id="issue:synthetic-supply")),
    "path_companies_count": _structural(2, "private", lambda b: b["counts"].update(pathCompanies=2)),
    "companies_count": _structural(1, "private", lambda b: b["counts"].update(companies=1)),
    "path_on_involves": lambda b: b["relations"][0].update(structuralPath={"status": "unavailable", "reason": "intermediate_company_unmapped"}),
    "missing_path_key": lambda b: b["relations"][0].pop("structuralPath"),
    "null_path_on_structural": _structural(1, "private", lambda b: b["relations"][-1].update(structuralPath=None)),
    "link_count": _structural(2, "private", lambda b: _path(b)["links"].pop()),
    "link_endpoints": _structural(2, "private", lambda b: _path(b)["links"][0].update(customerCompanyId="KRX:000660")),
    "repeated_company": _structural(2, "private", lambda b: _path(b).update(companyIds=["KRX:005930", "KRX:005930", "KRX:000660"])),
    "path_ends_elsewhere": _structural(1, "private", lambda b: b["relations"][-1].update(target="KRX:005930")),
    "target_is_a_participant": _structural(1, "private", lambda b: b["relations"].append({**copy.deepcopy(b["relations"][0]), "target": "KRX:000660", "id": "edge-x"})),
    "start_is_not_a_participant": _structural(1, "private", lambda b: b["relations"].pop(0)),
    "extra_path_key": _structural(1, "private", lambda b: _path(b).update(extra=1)),
    "unknown_status": _structural(1, "private", lambda b: _path(b).update(status="partial")),
    "three_hops": _structural(2, "private", lambda b: _path(b).update(companyIds=["KRX:005930", "KRX:000270", "KRX:000660", "KRX:001"])),
    "oversized_business_scope": _structural(1, "private", lambda b: b["relations"][-1]["basis"][0].update(businessScope="x" * 501)),
    "oversized_product_scope": _structural(1, "private", lambda b: b["relations"][-1]["basis"][0].update(productScope="가" * 501)),
    "scope_not_text": _structural(1, "private", lambda b: b["relations"][-1]["basis"][0].update(businessScope=["x"])),
    "missing_scope": _structural(1, "private", lambda b: b["relations"][-1]["basis"][0].pop("productScope")),
}


@pytest.mark.parametrize("change", [pytest.param(change, id=name) for name, change in BUNDLE5_REFUSED.items() if change is not None])
def test_a_malformed_or_unclosed_structural_path_is_refused_even_with_updated_digests(tmp_path, start, change):
    ws = workspace(tmp_path)
    serve(ws, mutated(change))
    service = start(workspace=ws)
    for url in (bundle_url(), status_url()):
        response = get(service, url)
        assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch", response.text[:300]


def test_a_supplier_customer_direction_is_relayed_as_the_producer_states_it_and_scopes_at_the_limit_are_accepted(tmp_path, start):
    ws = workspace(tmp_path)
    bundle = serve(ws, mutated(_structural(2, "private", _reverse_link, lambda b: b["relations"][-1]["basis"][0].update(businessScope="가" * 500, productScope="x" * 500))))
    wire = get(start(workspace=ws), bundle_url()).json()
    assert wire["bundle"] == bundle and _path(wire["bundle"])["links"][0] == {"supplierCompanyId": "KRX:000270", "customerCompanyId": "KRX:005930"}


def test_a_current_answer_in_an_earlier_bundle_schema_is_refused_and_a_legacy_handoff_is_withheld_without_any_old_content(tmp_path, start):
    """The service knows only `zoop-graph-handoff-bundle-5`: a bundle-1 shaped export (no mentions), a bundle-2 shaped export (mentions, no `fieldProvenance`), a
    bundle-3 shaped export (provenance, no `fieldVerdicts`/`withheld`) or a bundle-4 shaped export (no `pathCompanies`/`structuralPath`/basis scopes) is never relayed,
    and the producer's own withheld answer for a handoff frozen under any of them reaches the caller as a 200 with that reason and nothing of the old receipt."""
    ws = workspace(tmp_path)
    service = start(workspace=ws)

    def four() -> dict[str, Any]:
        """A genuine bundle-4 shape: no pathCompanies/structuralPath/scopes, sealed over the HISTORICAL five content lists (never the current-schema seal)."""
        b = copy.deepcopy(example_bundle())
        b["schemaVersion"] = "zoop-graph-handoff-bundle-4"
        del b["pathCompanies"], b["counts"]["pathCompanies"]
        for relation in b["relations"]:
            del relation["structuralPath"]
        b["manifestDigest"] = digest(manifest_of(b))
        b["digests"]["content"] = digest({key: b[key] for key in ("companies", "issues", "relations", "evidence", "articles")})
        return b

    earlier = (mutated(lambda b: (b.update(schemaVersion="zoop-graph-handoff-bundle-1"), [(issue.pop("mentions"), issue.pop("fieldProvenance"), issue.pop("fieldVerdicts"))
                                                                                       for issue in b["issues"]])),
               mutated(lambda b: (b.update(schemaVersion="zoop-graph-handoff-bundle-2"), [(issue.pop("fieldProvenance"), issue.pop("fieldVerdicts")) for issue in b["issues"]])),
               mutated(lambda b: (b.update(schemaVersion="zoop-graph-handoff-bundle-3"), [(issue.pop("fieldVerdicts"), issue["fieldProvenance"].pop("withheld"))
                                                                                       for issue in b["issues"]])),
               four())
    for legacy in earlier:
        serve(ws, legacy)
        for url in (bundle_url(), status_url()):
            response = get(service, url)
            assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch" and "bundle" not in response.json()
            assert "KRX:005930" not in response.text and pins(legacy)["bundleDigest"] not in response.text
    ws.script({"mode": "result", "output": withheld_output(code="handoff_contract_changed"), "exit": 2})
    for url in (status_url(), bundle_url()):
        wire = get(service, url).json()
        assert wire["delivery"] == {"state": "withheld", "reason": "handoff_contract_changed", "checkedAt": None}
        assert wire["verification"] is None and wire.get("bundle") is None and wire.get("manifest") is None


# ---- withheld, refused and unreadable answers ----------------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["source_unauthorized", "canonical_mapping_changed", "decisions_changed", "bindings_changed", "review_revision_changed",
                                  "upstream_changed", "source_pin_missing", "handoff_content_changed", "handoff_contract_changed"])
def test_a_withheld_answer_is_a_200_with_identity_and_a_reason_and_nothing_else(tmp_path, start, code):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": withheld_output(code=code), "exit": 2})
    service = start(workspace=ws)
    for url in (status_url(), bundle_url()):
        response = get(service, url)
        wire = response.json()
        assert response.status_code == 200 and wire["delivery"] == {"state": "withheld", "reason": code, "checkedAt": None} and wire["publication"] == "not-published"
        assert wire["verification"] is None and wire.get("bundle") is None
        for text in (*SOURCE_DATA, "KRX:005930", "ev-", pins(example_bundle())["bundleDigest"]):
            assert text not in response.text


def test_a_free_text_reason_is_redacted_never_echoed(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": withheld_output(code="/private/path with spaces: secret"), "exit": 2})
    wire = get(start(workspace=ws), status_url()).json()
    assert wire["delivery"] == {"state": "withheld", "reason": "redacted", "checkedAt": None}


def test_a_handoff_that_is_not_ready_is_withheld_with_its_state(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    for state in ("reserved", "failed"):
        ws.script({"mode": "result", "output": error_output("handoff_not_ready", {"state": state}), "exit": 2})
        wire = get(service, status_url()).json()
        assert (wire["state"], wire["delivery"]["reason"], wire["verification"]) == (state, "handoff_not_ready", None)
    ws.script({"mode": "result", "output": error_output("handoff_not_ready", {"state": "ready"}), "exit": 2})   # ready is not a reason to be not ready
    assert get(service, status_url()).status_code == 503


@pytest.mark.parametrize("code,status,public,retryable", [
    ("handoff_busy", 503, "runtime_busy", True), ("relation_busy", 503, "runtime_busy", True), ("extraction_busy", 503, "runtime_busy", True),
    ("ingestion_busy", 503, "runtime_busy", True), ("handoff_recovery_required", 503, "service_configuration_invalid", True),
    ("handoff_artifact_invalid", 503, "service_configuration_invalid", True), ("handoff_artifact_missing", 503, "service_configuration_invalid", True),
    ("operator_file_changed", 503, "service_configuration_invalid", True), ("decisions_invalid", 503, "service_configuration_invalid", True),
    ("handoff_state_missing", 503, "service_configuration_invalid", True), ("evidence_unresolvable", 503, "service_configuration_invalid", True),
    ("handoff_not_found", 404, "handoff_not_found", False), ("brand_new_code", 500, "internal_error", False)])
def test_producer_refusals_are_stable_codes_with_a_retry_hint_and_never_an_empty_bundle(tmp_path, start, code, status, public, retryable):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": error_output(code, {"path": "/private/ledger", "message": "stack trace"}), "exit": 2})
    response = get(start(workspace=ws), bundle_url())
    error = error_of(response)
    assert (response.status_code, error["code"], error["retryable"]) == (status, public, retryable)
    assert ("retry-after" in response.headers) == (status == 503)
    assert "bundle" not in response.json() and "/private/ledger" not in response.text and "stack trace" not in response.text   # the detail is never relayed


NON_CANONICAL = json.dumps(envelope(), ensure_ascii=True)       # valid JSON, but the keys are not sorted/compact/unescaped as the bundle hash requires
RAW = [{"mode": "raw", "raw": "not json", "exit": 0}, {"mode": "raw", "raw": "", "exit": 0}, {"mode": "raw", "raw": "{}", "exit": 0},
       {"mode": "raw", "raw": json.dumps(envelope(), sort_keys=True, ensure_ascii=False, separators=(", ", ": ")), "exit": 0},
       {"mode": "raw", "raw": NON_CANONICAL, "exit": 0},
       {"mode": "raw", "raw": canonical(withheld_output()) + "\n", "exit": 0},                   # withheld must exit 2
       {"mode": "raw", "raw": canonical(envelope()) + "\n", "exit": 2},                          # current must exit 0
       {"mode": "raw", "raw": canonical(envelope()) + "\n", "exit": 1}, {"mode": "raw", "raw": canonical(envelope()) + "\n", "exit": 3},
       {"mode": "raw", "raw": canonical({**envelope(), "schemaVersion": "other"}) + "\n", "exit": 0},
       {"mode": "raw", "raw": '{"a":1,"a":2}\n', "exit": 0}, {"mode": "raw", "raw": '{"schemaVersion":"zoop-ai-handoff-1","x":NaN}\n', "exit": 0},
       {"mode": "big", "bytes": 17 * 1024 * 1024}, {"mode": "die"}]


@pytest.mark.parametrize("behavior", RAW, ids=lambda behavior: behavior["mode"])
def test_a_malformed_non_canonical_oversized_or_abnormal_child_is_a_retryable_503_and_never_content(tmp_path, start, behavior):
    ws = workspace(tmp_path)
    ws.script(behavior)
    response = get(start(workspace=ws), bundle_url())
    error = error_of(response)
    assert (response.status_code, error["code"], error["retryable"]) == (503, "runtime_unavailable", True) and response.headers["retry-after"]
    assert "bundle" not in response.json() and "KRX:005930" not in response.text


@pytest.mark.parametrize("output", [{**envelope(), "usage": {"providerCalls": 1, "modelCalls": 0}}, {k: v for k, v in envelope().items() if k != "receipt"},
                                    {k: v for k, v in envelope().items() if k != "bundle"}, {**envelope(), "state": "failed"},
                                    {**envelope(), "delivery": {"status": "current"}}, {**envelope(), "publication": "published"}])
def test_an_answer_that_is_not_the_producers_contract_is_a_500_and_never_content(tmp_path, start, output):
    ws = workspace(tmp_path)
    ws.script({"mode": "result", "output": output})
    response = get(start(workspace=ws), bundle_url())
    assert response.status_code == 500 and error_of(response)["code"] == "runtime_contract_mismatch" and "KRX:005930" not in response.text


def test_a_child_that_misses_the_deadline_is_stopped_once_and_the_service_stays_usable(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "sleep", "seconds": 60, "output": envelope()})
    service = start(workspace=ws, launcher=True, launcher_env={"ZOOP_TEST_HANDOFF_DEADLINE": "1"})
    began = time.monotonic()
    response = get(service, bundle_url())
    assert time.monotonic() - began < 20
    assert response.status_code == 503 and error_of(response)["code"] == "runtime_unavailable" and response.headers["retry-after"]
    assert len(ws.calls()) <= 1   # one child per request and no automatic retry
    ws.script({"mode": "result", "output": envelope()})
    assert get(service, bundle_url()).status_code == 200
    assert len(ws.calls()) <= 2


# ---- concurrency ----------------------------------------------------------------------------------------------------------------------

def concurrently(service, urls: list[str]) -> list[tuple[int, str | None]]:
    results: list[tuple[int, str | None]] = [(0, None)] * len(urls)

    def read(index: int) -> None:
        response = service.client.get(urls[index], headers={"Authorization": f"Bearer {service.workspace.credentials.tokens[PRINCIPAL]}"})
        results[index] = (response.status_code, response.json().get("error", {}).get("code"))

    threads = [threading.Thread(target=read, args=(index,)) for index in range(len(urls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    return results


def overlapping(calls: list[dict[str, Any]]) -> bool:
    spans = sorted((call["t0"], call["t1"]) for call in calls)
    return any(later[0] < earlier[1] for earlier, later in zip(spans, spans[1:]))


def test_without_an_s3_group_reads_run_side_by_side_up_to_two_and_then_answer_busy(tmp_path, start):
    ws = workspace(tmp_path)
    ws.script({"mode": "sleep", "seconds": 3, "output": envelope()})
    service = start(workspace=ws)
    results = concurrently(service, [status_url()] * 5)
    ok = [r for r in results if r == (200, None)]
    busy = [r for r in results if r == (503, "service_busy")]
    assert len(ok) + len(busy) == 5 and 1 <= len(ok) <= 2 and len(busy) >= 3, results
    assert len(ws.calls()) == len(ok) and overlapping(ws.calls())   # no S2/S3 group in this process: nothing to serialize against


def test_with_an_s3_group_in_the_same_process_handoff_children_wait_for_its_gate_one_at_a_time(tmp_path, start):
    ws = workspace(tmp_path, with_relation=True)
    ws.script({"mode": "sleep", "seconds": 1.5, "output": envelope()})
    service = start(workspace=ws)
    results = concurrently(service, [status_url()] * 2)
    assert results == [(200, None)] * 2, results   # each waits (up to 10 s) for the gate; none is answered empty
    calls = ws.calls()
    assert len(calls) == 2 and not overlapping(calls)


# ---- logs, secrets and the other families --------------------------------------------------------------------------------------------

def test_nothing_private_reaches_a_response_header_or_log_line_and_the_logged_route_is_the_template(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    responses = [get(service, status_url()), get(service, bundle_url()), get(service, status_url("handoff-never-existed")), get(service, f"{status_url()}?x=1")]
    ws.script({"mode": "result", "output": error_output("handoff_artifact_invalid"), "exit": 2})
    responses.append(get(service, status_url()))
    secrets = ws.private_strings()
    for response in responses[2:]:   # the bundle route legitimately delivers the bundle's own data; every other answer must not carry it
        blob = response.text + json.dumps(dict(response.headers))
        assert not [s for s in (*secrets, *SOURCE_DATA) if s in blob]
    for response in responses:
        assert not [s for s in secrets if s in response.text + json.dumps(dict(response.headers))]
    service.stop()
    logs = service.logs()
    assert not [s for s in (*secrets, *SOURCE_DATA, "KRX:005930", pins(example_bundle())["bundleDigest"]) if s in logs], \
        [s for s in (*secrets, *SOURCE_DATA, "KRX:005930") if s in logs]
    lines = [json.loads(line) for line in service.logs("out").splitlines() if line.startswith("{") and '"event":"request"' in line]
    routes = {line["route"] for line in lines}
    assert "/internal/v1/graph-handoffs/{handoffId}" in routes and "/internal/v1/graph-handoffs/{handoffId}/bundle" in routes
    assert {line["handoffId"] for line in lines if "handoffId" in line} >= {HANDOFF}


def test_a_partial_handoff_group_refuses_to_start_with_a_field_name_and_reason_only(tmp_path, start):
    ws = workspace(tmp_path)
    service = start(workspace=ws, env={"ZOOP_AI_SERVICE_HANDOFF_BINDINGS": None}, wait=False)
    assert service.exited() == 78
    line = json.loads(service.logs("out").strip().splitlines()[-1])
    assert line == {"error": "service_config_invalid", "field": "ZOOP_AI_SERVICE_HANDOFF_BINDINGS", "reason": "handoff_group_incomplete"}
    assert not [s for s in ws.private_strings() if s in service.logs()]


def test_the_handoff_group_does_not_change_the_other_families(tmp_path, start):
    """An S1 route on a service with the handoff group answers exactly as before, and the graph.read family stays off without its own group."""
    ws = workspace(tmp_path)
    service = start(workspace=ws)
    missing = service.request("GET", "/internal/v1/analysis-jobs/never-submitted", as_="alpha")
    assert missing.status_code == 404 and missing.json()["schemaVersion"] == "zoop-ai-internal-1"
    unconfigured = service.request("GET", "/internal/v1/relation-jobs/never-submitted", as_="alpha")
    assert unconfigured.status_code == 409 and unconfigured.json()["schemaVersion"] == "zoop-ai-internal-relation-1"
    graph = service.request("GET", "/internal/v1/graph-versions/graph-main-1", as_="grapher")
    assert graph.status_code == 409 and graph.json()["schemaVersion"] == "zoop-ai-internal-graph-1"
    assert ws.calls() == []
