"""Read-only complete verification followed by one atomic paired-authority admission."""
from __future__ import annotations

import os
import sqlite3
import stat
import threading
from dataclasses import dataclass
from pathlib import Path

from . import extraction_access, relation_access, plan_verify
from .jobs import ApiError, Observation, Reply
from .plan_authority import PlanAuthority, canonical, digest, etag, fail
from .plan_wire import PlanAdmissionEnvelope, PlanErrorEnvelope, PlanPolicyState, PlanPolicyUpdate, PlanReference, MAX_REPLY
from .wire import ErrorBody
from .ledger import stamp


class PlanError(ApiError):
    def envelope(self, request_id):
        return PlanErrorEnvelope(error=ErrorBody(code=self.code, retryable=self.code in {"service_busy", "plan_verifier_unavailable", "authority_unavailable"},
                                                request_id=request_id, field=self.field, runtime_code=self.runtime_code))


@dataclass(frozen=True)
class VerifySettings:
    state: Path
    targets: tuple
    env: dict
    environ: dict


def settings(config):
    e, r = config.extraction, config.relation
    env = dict(e.child_env)
    if config.pipeline_live:
        env.update(config.pipeline_live.public)
        env["ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"] = config.pipeline_live.budget["ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"]
    names = {"ZOOP_AI_SERVICE_EXTRACTION_COMMAND": str(e.command), "ZOOP_AI_INGESTION_STATE_DIR": str(e.ingestion_state_dir),
             "ZOOP_AI_SERVICE_SOURCES": str(e.sources_path), "ZOOP_AI_SERVICE_EXTRACTION_REPLAY": str(e.producer_replay)}
    if e.topic_replay is not None:
        names["ZOOP_AI_SERVICE_EXTRACTION_TOPIC_REPLAY"] = str(e.topic_replay)
    return VerifySettings(config.state_dir, (), env, names)


class PlanAdmissionService:
    def __init__(self, config, authority: PlanAuthority):
        self.config, self.authority = config, authority
        self._slots = threading.BoundedSemaphore(4)

    @staticmethod
    def _run(call):
        try:
            return call()
        except PlanError:
            raise
        except ApiError as error:
            raise PlanError(error.status, error.code, field=error.field, headers=error.headers) from None
        except plan_verify.InstallError as error:
            code = "plan_verifier_unavailable" if error.code == "plan_verifier_unavailable" else "plan_verification_failed"
            raise PlanError(503 if code == "plan_verifier_unavailable" else 409, code) from None
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, relation_access.AccessError):
            raise PlanError(503, "authority_unavailable") from None

    def status(self, owner: str, plan_id: str, plan_digest: str, seen: Observation) -> Reply:
        return self._run(lambda: Reply(200, PlanAdmissionEnvelope.model_validate(self.authority.find(owner, plan_id, plan_digest, query=True)),
                                      {"Location": f"/internal/v1/plan-admissions/{plan_id}?planDigest={plan_digest}"}))

    def policy_status(self, operator: str, seen: Observation) -> Reply:
        def run():
            state = self.authority.policy_status()
            return Reply(200, PlanPolicyState.model_validate(state), {"ETag": etag(state["revision"], state["policyDigest"])})
        return self._run(run)

    def set_policy(self, operator: str, operation_id: str, document: dict, expected_etag: str, seen: Observation) -> Reply:
        def run():
            result = self.authority.set_policy(operator, operation_id, document, expected_etag)
            return Reply(200, PlanPolicyUpdate.model_validate(result), {"ETag": etag(result["revision"], result["policyDigest"])})
        return self._run(run)

    def admit(self, owner: str, reference: PlanReference, seen: Observation) -> Reply:
        if not self._slots.acquire(blocking=False):
            raise PlanError(503, "service_busy")
        try:
            return self._run(lambda: self._admit(owner, reference))
        finally:
            self._slots.release()

    def _admit(self, owner, reference):
        plan_id, plan_digest = reference.plan_id, reference.plan_digest
        location = {"Location": f"/internal/v1/plan-admissions/{plan_id}?planDigest={plan_digest}"}
        old = self.authority.find(owner, plan_id, plan_digest)
        if old is not None:
            return Reply(200, PlanAdmissionEnvelope.model_validate(old), location)
        captured = self.authority.capture(owner)
        cfg = settings(self.config)
        root = self.config.plan_root
        path = root / plan_id
        try:
            # No caller path, symlink component, special file or extra plan file is accepted.
            if os.path.realpath(root) != str(root) or os.path.realpath(path) != str(path):
                fail("plan_not_found", 404)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                fail("plan_not_found", 404)
            files, original, receipt = plan_verify.plan_files(path, cfg)
        except (OSError, plan_verify.InstallError):
            fail("plan_not_found", 404)
        if (receipt["planId"], receipt["planDigest"]) != (plan_id, plan_digest):
            fail("plan_verification_failed")
        if original["principal"] != owner:
            fail("plan_not_found", 404)
        verified = plan_verify.verify_plan(path, cfg, files, original, receipt)
        approvals = extraction_access.parse(files["approvals.json"], [owner], topic_available=self.config.extraction.topic_replay is not None,
                                             live_available=self.config.pipeline_live is not None)
        upstreams = relation_access.parse(files["relation-upstreams.json"], [owner])
        raw_approvals = {a["jobId"]: a for a in plan_verify.decode(files["approvals.json"])["approvals"]}
        self._policy(captured[2], original, approvals)
        public = {"schemaVersion": "zoop-ai-plan-manifest-1", "planId": plan_id, "planDigest": plan_digest,
                  "receiptSha256": plan_verify.sha(files["receipt.json"]), "principal": owner,
                  "round": original["round"], "provenance": original["provenance"], "units": []}
        grants = []
        for unit in original["units"]:
            approval = approvals.find(owner, unit["jobId"])
            if approval is None or (owner, approval.job_id, approval.input_digest) not in upstreams.entries:
                fail("plan_verification_failed")
            relation_id = "s3p-" + digest({"format": "zoop-plan-admission-relation-job-1", "planId": plan_id, "planDigest": plan_digest,
                                           "upstream": {"jobId": approval.job_id, "inputDigest": approval.input_digest}})
            submission = {"schemaVersion": "zoop-relation-s3", "jobId": relation_id, "provenance": original["provenance"],
                          "upstream": {"jobId": approval.job_id, "inputDigest": approval.input_digest}}
            public["units"].append({"unitKey": approval.job_id, "extractionSubmit": unit["submit"],
                                    "extractionInputDigest": approval.input_digest, "relationSubmit": submission})
            grants.append({"s2": approval.job_id, "s3": relation_id, "approval": raw_approvals[approval.job_id], "submission": submission})
        public["manifestDigest"] = digest(public)
        # Validate the whole public contract and exact encoded response bound BEFORE any write.
        from .plan_wire import PublicManifest
        PublicManifest.model_validate(public)
        preview = {"schemaVersion": "zoop-ai-plan-admission-1", "admissionId": "pa-" + digest({
            "format": "zoop-plan-admission-identity-1", "principal": owner, "planId": plan_id, "planDigest": plan_digest}),
            "acceptedAt": stamp(self.authority.clock()), "policyRevision": captured[0], "policyDigest": captured[1],
            "manifest": public, "authority": {"state": "active", "reason": None}}
        if len(canonical(preview).encode()) > MAX_REPLY:
            fail("plan_verification_failed")
        pins = self._pins(path, cfg, files)
        # Complete current-source verification remains outside BEGIN IMMEDIATE.
        if plan_verify.verify_plan(path, cfg, files, original, receipt) != verified:
            fail("plan_verification_failed")
        def recheck():
            current_info = path.lstat()
            if (current_info.st_dev, current_info.st_ino, current_info.st_mode) != (info.st_dev, info.st_ino, info.st_mode):
                fail("plan_verification_failed")
            if self._pins(path, cfg, files) != pins:
                fail("plan_verification_failed")
            if plan_verify.sha(plan_verify.read_file(self.config.extraction.sources_path, 20_000_000)) != verified["sourceRegistrySha256"]:
                fail("plan_verification_failed")
            if self.authority._fixtures(captured[2]["runtime"]):
                fail("policy_mismatch")
        created, result = self.authority.commit(owner, captured, public, verified, grants, recheck)
        return Reply(201 if created else 200, PlanAdmissionEnvelope.model_validate(result), location)

    def _pins(self, path, cfg, files):
        current, _, _ = plan_verify.plan_files(path, cfg)
        if current != files:
            fail("plan_verification_failed")
        e, r = self.config.extraction, self.config.relation
        return {str(p): plan_verify.sha(plan_verify.read_file(p, 100_000_000)) for p in (e.command, r.command)}

    def _policy(self, policy, manifest, approvals):
        runtime = policy["runtime"]
        provenance = {"sourceKind": policy["sourceKind"], "executionMode": runtime["kind"],
                      "recordingKind": "provider" if runtime["kind"] == "live" else "authored-test"}
        if manifest["provenance"] != provenance or manifest["round"]["sourceId"] not in policy["sourceIds"]:
            fail("policy_mismatch")
        for approval in approvals.entries.values():
            request = approval.request
            if (request["promptVersion"] != policy["promptVersion"] or digest(request["catalogue"]) != policy["catalogueDigest"]
                    or digest(request["snapshot"]) != policy["snapshotDigest"] or request["topic"] != policy["topic"]):
                fail("policy_mismatch")
            def sources(value):
                if isinstance(value, dict):
                    if "sourceId" in value and value["sourceId"] not in policy["sourceIds"]:
                        fail("policy_mismatch")
                    for child in value.values():
                        sources(child)
                elif isinstance(value, list):
                    for child in value:
                        sources(child)
            sources(request)
            if runtime["kind"] == "replay":
                if (approval.producer_digest, approval.topic_digest) != (runtime["producerReplayDigest"], runtime["topicReplayDigest"]):
                    fail("policy_mismatch")
            elif approval.live_identity != runtime["liveRuntimeIdentity"]:
                fail("policy_mismatch")
        if self.authority._fixtures(runtime):
            fail("policy_mismatch")
