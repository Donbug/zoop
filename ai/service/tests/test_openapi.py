"""The generated internal OpenAPI is the backend handoff: current, consistent with enforced behavior, and its examples really work."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

from support import Workspace, document_jobs, document_replay
from zoop_ai_service.app import create_app
from zoop_ai_service.openapi_doc import examples
from zoop_ai_service.wire import ErrorEnvelope, JobStatus, ResultEnvelope, next_action

ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "docs/api/internal-ai-openapi.json"
SCRIPT = ROOT / "ai/service/scripts/export_openapi.py"


def spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def test_committed_documents_match_a_fresh_generation():
    done = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr


def test_every_route_is_documented_with_its_enforced_scope():
    documented = {(method.upper(), path): operation["security"][0]["bearerAuth"][0]
                  for path, item in spec()["paths"].items() for method, operation in item.items()}
    routes = {(method, route.path) for route in create_app().routes if hasattr(route, "methods") and route.path.startswith("/internal")
              for method in route.methods}
    assert set(documented) == routes and len(routes) == 33
    assert set(documented.values()) == {"analysis.submit", "analysis.read", "analysis.cancel", "analysis.recover",
                                        "relation.submit", "relation.read", "relation.cancel", "relation.recover", "relation.review",
                                        "extraction.submit", "extraction.read", "extraction.cancel", "extraction.recover", "graph.read", "handoff.read",
                                        "handoff.exposure", "chat.invoke", "plan.admit", "plan.read", "plan.policy", "observation.read", "round.run", "round.read"}


def test_documented_scopes_are_what_the_service_enforces(start, tmp_path):
    workspace = Workspace(tmp_path / "scope-workspace", replay=document_replay())
    workspace.credentials.scopes["alpha"] += ["plan.admit", "plan.read", "observation.read", "round.run", "round.read"]
    workspace.credentials.tokens["policy-operator"] = "t" + "synthetic-policy-token-" * 3
    workspace.credentials.scopes["policy-operator"] = ["plan.policy"]
    service = start(workspace=workspace)
    job_id = document_jobs()[0]["jobId"]
    for (method, path), scope in {(m.upper(), p): o["security"][0]["bearerAuth"][0]
                                   for p, i in spec()["paths"].items() for m, o in i.items()}.items():
        url = path.replace("{jobId}", job_id).replace("{operationId}", "review-op-1").replace("{versionId}", "graph-main-1").replace("{handoffId}", "handoff-synthetic-1").replace("{stage}", "chat-router").replace("{planId}", "s2plan-" + "0" * 64).replace("{roundId}", "round-20261031T0905")
        lacking = "submitter" if scope != "analysis.submit" else "reader"
        assert service.request(method, url, as_=lacking).status_code == 403, (method, path)
        assert service.request(method, url, as_=None).status_code == 401, (method, path)
        authorized = "policy-operator" if scope == "plan.policy" else "alpha"
        assert service.request(method, url, as_=authorized).status_code != 403, (method, path)


def test_the_s1_wire_contract_is_referenced_never_copied():
    document = spec()
    text = json.dumps(document)
    assert "ai-contract.schema.json#/$defs/Submit" in text and "ai-contract.schema.json#/$defs/JobResult" in text
    assert not {"Submit", "JobResult", "AnalysisArtifact", "SourceGrant", "Document"} & set(document["components"]["schemas"])
    assert (ROOT / "docs/api/ai-contract.schema.json").is_file()


def test_every_local_openapi_reference_resolves():
    document = spec()

    def check(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/"):
                target = document
                for token in unquote(ref[2:]).split("/"):
                    key = token.replace("~1", "/").replace("~0", "~")
                    try:
                        target = target[int(key)] if isinstance(target, list) else target[key]
                    except (KeyError, IndexError, TypeError, ValueError):
                        pytest.fail(f"Unresolved local OpenAPI reference: {ref}")
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(document)


def test_authored_request_example_is_accepted_by_the_real_service(start):
    example = spec()["paths"]["/internal/v1/analysis-jobs"]["post"]["requestBody"]["content"]["application/json"]["examples"]["documentSummary"]["value"]
    assert example == document_jobs()[0]
    service = start(replay=document_replay())
    accepted = service.submit(example)
    assert accepted.status_code == 202 and accepted.json()["jobId"] == example["jobId"]
    assert service.wait_state(example["jobId"], {"ready"}, dispatch={"idle"})["next"] == "fetch_result"


def collect(node):
    if isinstance(node, dict):
        if node.get("schemaVersion") == "zoop-ai-internal-1":
            yield node
        for value in node.values():
            yield from collect(value)
    elif isinstance(node, list):
        for value in node:
            yield from collect(value)


def test_authored_examples_validate_against_the_models_and_the_next_rule():
    found = list(collect(spec()["paths"]))
    assert len(found) >= 15
    statuses = errors = results = 0
    for value in found:
        if "error" in value:
            ErrorEnvelope.model_validate(value)
            assert set(value["error"]) == {"code", "retryable", "requestId", "runtimeCode", "field"}
            errors += 1
        elif "delivery" in value:
            ResultEnvelope.model_validate(value)
            assert value["delivery"]["state"] == "withheld" and value["job"] is None
            results += 1
        else:
            status = JobStatus.model_validate(value)
            assert status.next == next_action(status.state, status.resume_mode, status.dispatch.state)
            statuses += 1
    assert statuses and errors and results


def test_recovery_examples_tell_the_documented_story():
    sample = examples()
    blocked = sample["status.200"]["blockedByRuntimeConfiguration"]["value"]
    assert (blocked["state"], blocked["dispatch"]["lastOutcome"], blocked["next"]) == ("queued", "runtime_error", "recover")
    reconciling = sample["status.200"]["reconciling"]["value"]
    assert (reconciling["next"], reconciling["unreceiptedAttempts"]) == ("operator_reconcile", 1)
    assert sample["errors"]["409.reconcileRequired"]["value"]["status"]["state"] == "reconciling"
    assert sample["recover.202"]["enqueued"]["value"]["next"] == "wait"
    exhausted = sample["status.200"]["budgetExhausted"]["value"]
    assert (exhausted["resumeMode"], exhausted["next"]) == ("unsent_only", "recover")


def test_models_forbid_unknown_fields_and_never_carry_a_message():
    for model in (JobStatus, ErrorEnvelope, ResultEnvelope):
        assert model.model_config["extra"] == "forbid"
    assert "message" not in ErrorEnvelope.model_json_schema()["$defs"]["ErrorBody"]["properties"]
    with pytest.raises(Exception):
        ErrorEnvelope.model_validate({"schemaVersion": "zoop-ai-internal-1", "error": {"code": "x", "retryable": False, "requestId": "r",
                                                                                          "message": "stack"}})


def test_observation_export_documents_exact_native_selector_and_response():
    document = spec()
    operation = document["paths"]["/internal/v1/observations/export"]["post"]
    assert operation["security"] == [{"bearerAuth": ["observation.read"]}]
    schemas = document["components"]["schemas"]
    selector = schemas["ObservationExportRequest"]
    assert selector["additionalProperties"] is False
    assert set(selector["required"]) == {"schemaVersion", "roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion"}
    assert set(selector["properties"]) == set(selector["required"])
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ObservationExport"}
    assert "text" in schemas["NativeProjection"]["required"]
    assert "202" not in operation["responses"]
    assert all(parameter["name"] != "Idempotency-Key" for parameter in operation.get("parameters", []))
    assert operation["responses"]["200"]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"


def test_round_request_schemas_keep_original_body_identity_and_full_bindings():
    document = spec()
    for family, model in (("runs", "RunRequest"), ("handoffs", "HandoffRequest")):
        post = document["paths"]["/internal/v1/round-" + family]["post"]
        get = document["paths"]["/internal/v1/round-" + family + "/{roundId}"]["get"]
        assert post["security"] == [{"bearerAuth": ["round.run"]}]
        assert get["security"] == [{"bearerAuth": ["round.read"]}]
        assert {"200", "202", "409", "422"} <= set(post["responses"])
        assert post["requestBody"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/" + model}
        assert document["components"]["schemas"][model]["additionalProperties"] is False
    assert "bindings" in document["components"]["schemas"]["HandoffRequest"]["required"]
    assert document["components"]["schemas"]["DocumentBindings"]["properties"]["bindings"]["maxItems"] == 20000
