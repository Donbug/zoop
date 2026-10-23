"""The operator service plan of `zoop-ai-extract plan-round` against the REAL service: its registry files pass the actual loaders, an operator installs
them, the app's per-unit S2 submit is accepted over HTTP, and the S3 upstream it lists is refused until that S2 job is ready and permitted afterwards.

Plan publication is the final SOURCE-RIGHTS gate (read/store/quote-display authority is re-checked after the plan is built). Snapshot grounding and the
freeze-time source context are NOT checked at plan time: an approval is syntactically valid and rights-checked, not freeze-validated; the service's first
dispatch runs the freeze checks.
Nothing here executes a model: plan generation opens no ledger, the S2 job runs the authored replay fixture, and the plan never edits an installed file
(the test, standing in for the operator, copies the two registry files itself). An `enqueue-round`/CLI job id is never adopted."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from extraction_support import EXTRACT_CLI, pipeline_env
from relation_support import PIPELINE, PIPELINE_PYTHON
from zoop_ai_service import extraction_access, relation_access

PRINCIPALS = ["alpha", "beta"]
AUTHOR = Path(__file__).resolve().parent / "author_plan_relation.py"


def descriptor(world) -> dict:
    """The descriptor of the world's authored S2 request (topic stage included), as an enqueue-round request."""
    request = world.s2_request
    return {"schemaVersion": request["schemaVersion"], "enqueueId": "svc-plan", "roundId": request["incoming"]["roundId"], "sourceId": request["incoming"]["sourceId"],
            "provenance": request["provenance"], "promptVersion": request["promptVersion"], "catalogue": request["catalogue"], "snapshot": request["snapshot"],
            "topic": request["topic"]}


def plan(workspace, world, output: Path, *, principal: str = "alpha") -> tuple[int, dict]:
    argv = [str(EXTRACT_CLI), "plan-round", "--ingestion-state-dir", str(world.ingestion), "--sources", str(workspace.sources), "--replay", str(workspace.s2_replay), "--topic-replay", str(workspace.s2_topic),
            "--principal", principal, "--output", str(output)]
    done = subprocess.run(argv, input=json.dumps(descriptor(world)).encode(), capture_output=True, env=pipeline_env(workspace), timeout=300)
    assert done.stderr == b""
    return done.returncode, json.loads(done.stdout.decode())


def author_s3_fixtures(workspace, world, output: Path, job_id: str) -> dict:
    """S3 replay fixtures for THIS plan's upstream (its request carries the upstream job id and input digest), authored by the pipeline's own loop."""
    argv = [str(PIPELINE_PYTHON), str(AUTHOR), str(PIPELINE), str(world.root), str(output / "approvals.json"), job_id, str(workspace.s2_replay), str(workspace.root / "s3-scratch"), str(workspace.s2_topic)]
    done = subprocess.run(argv, capture_output=True, env=pipeline_env(workspace), timeout=600)
    assert done.returncode == 0, done.stderr.decode()[-3000:]
    return json.loads(done.stdout.decode().strip().splitlines()[-1])


def test_a_plan_installs_into_the_real_service_and_gates_s3_on_s2(start_extraction, world):
    service = start_extraction(chain=True, requests=(), hold=True)  # accepted S2 jobs stay queued until `workspace.go()`
    workspace = service.workspace
    output = workspace.root / "plan"
    code, receipt = plan(workspace, world, output)
    assert code == 0, receipt
    assert receipt["outcome"] == "created" and not workspace.extraction_state.joinpath("extraction.sqlite3").exists()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    # The actual loaders accept exactly what the plan wrote.
    approvals = extraction_access.load(output / "approvals.json", PRINCIPALS, topic_available=True)
    relation_access.load(output / "relation-upstreams.json", PRINCIPALS)

    main = world.s2_request["incoming"]["documentVersion"]
    unit = next(item for item in manifest["units"] if item["documentVersion"] == main)
    approval = approvals.find("alpha", unit["jobId"])
    assert approval is not None and approval.input_digest == unit["inputDigest"] and approval.approved_digest == unit["approvedRequestDigest"]
    assert approval.request == {**world.s2_request, "jobId": unit["jobId"]} and not unit["jobId"].startswith("s2r-")
    assert approval.topic_digest is not None and approval.request["topic"] is not None  # the supported topic stage is planned, pinned and run

    # Nothing is installed by planning: the service refuses the unit until the operator copies the files.
    refused = service.esubmit(unit["jobId"], digest_=unit["approvedRequestDigest"])
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "request_not_approved"
    shutil.copyfile(output / "approvals.json", workspace.approvals)

    upstream = {"jobId": unit["jobId"], "inputDigest": unit["inputDigest"]}
    shutil.copyfile(output / "relation-upstreams.json", workspace.upstreams)
    authored = author_s3_fixtures(workspace, world, output, unit["jobId"])
    assert authored["inputDigest"] == unit["inputDigest"]  # the scratch S2 run is byte-identical to what the service will produce
    shutil.copyfile(authored["producer"], workspace.producer)
    shutil.copyfile(authored["verifier"], workspace.verifier)
    accepted = service.esubmit(unit["jobId"], digest_=unit["approvedRequestDigest"])
    assert accepted.status_code == 202, accepted.text
    early = service.rsubmit(upstream=upstream)  # listed, but its S2 job is only queued: not ready, so not an upstream yet
    assert early.status_code == 409 and early.json()["error"]["code"] == "upstream_unavailable" and early.json()["error"]["runtimeCode"] == "upstream_not_ready", early.text
    workspace.go()
    ready = service.ewait(unit["jobId"], states={"ready"}, dispatch={"idle"})
    assert ready["inputDigest"] == unit["inputDigest"] and ready["usage"]["providerCalls"] == 0
    assert service.rsubmit(upstream=upstream).status_code == 202
    done = service.rwait(states={"ready"}, dispatch={"idle"})  # S3 reaches ready over the planned S2 job, not merely accepted
    assert done["usage"]["providerCalls"] == 0
    assert workspace.network_attempts() == ""


def test_planning_is_idempotent_and_never_clobbers(start_extraction, world):
    service = start_extraction(chain=True, requests=())
    workspace = service.workspace
    output = workspace.root / "plan"
    first = plan(workspace, world, output)[1]
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    code, again = plan(workspace, world, output)
    assert code == 0 and again == {**first, "outcome": "existing"} and {p.name: p.read_bytes() for p in output.iterdir()} == before
    code, refused = plan(workspace, world, output, principal="beta")
    assert code == 2 and refused["error"]["code"] == "plan_output_conflict" and {p.name: p.read_bytes() for p in output.iterdir()} == before
