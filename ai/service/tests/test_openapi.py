"""The generated internal OpenAPI is the backend handoff: current, consistent with enforced behavior, and its examples really work."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from support import document_jobs, document_replay
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
    assert set(documented) == routes and len(routes) == 21
    assert set(documented.values()) == {"analysis.submit", "analysis.read", "analysis.cancel", "analysis.recover",
                                        "relation.submit", "relation.read", "relation.cancel", "relation.recover", "relation.review",
                                        "extraction.submit", "extraction.read", "extraction.cancel", "extraction.recover", "graph.read", "handoff.read"}


def test_documented_scopes_are_what_the_service_enforces(start):
    service = start(replay=document_replay())
    job_id = document_jobs()[0]["jobId"]
    for (method, path), scope in {(m.upper(), p): o["security"][0]["bearerAuth"][0]
                                   for p, i in spec()["paths"].items() for m, o in i.items()}.items():
        url = path.replace("{jobId}", job_id).replace("{operationId}", "review-op-1").replace("{versionId}", "graph-main-1").replace("{handoffId}", "handoff-synthetic-1")
        lacking = "submitter" if scope != "analysis.submit" else "reader"
        assert service.request(method, url, as_=lacking).status_code == 403, (method, path)
        assert service.request(method, url, as_=None).status_code == 401, (method, path)
        assert service.request(method, url, as_="alpha").status_code != 403, (method, path)


def test_the_s1_wire_contract_is_referenced_never_copied():
    document = spec()
    text = json.dumps(document)
    assert "ai-contract.schema.json#/$defs/Submit" in text and "ai-contract.schema.json#/$defs/JobResult" in text
    assert not {"Submit", "JobResult", "AnalysisArtifact", "SourceGrant", "Document"} & set(document["components"]["schemas"])
    assert (ROOT / "docs/api/ai-contract.schema.json").is_file()


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
