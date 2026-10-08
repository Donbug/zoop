"""S1 only: document generation, independent semantic verification, durable save/recovery."""
from __future__ import annotations

import fcntl
import json
import sqlite3
import re
import time
import uuid
from contextlib import contextmanager
from typing import Any

from pydantic import ValidationError

from .contracts import (AnalysisArtifact, Failure, JobResult, SCHEMA_VERSION, StageConfig, Submit,
                        Usage, Validation, VerificationAnswer, canonical, digest, exact, now)
from .provider import ANSWERS, PROMPTS, ProviderError, ReplayProvider, request_identity, stage_config
from .store import Store, WorkerFailure

_LEGACY_PREDICTION = re.compile(r"예측|전망|오를|내릴|호재|악재|매수|매도|추천|목표가|수익률")
_OUTLOOK_PROHIBITED = re.compile(
    r"매수|매도|추천|목표가|주가|수익.{0,8}보장|지수.{0,16}(상승|하락)|"
    r"가격.{0,16}(상승|하락|오른|내린)|확정.{0,8}인과|때문에.{0,12}(상승|하락)|"
    r"\b(buy|sell|invest|recommend|forecast|predict|stock\s*price|price\s*target|profit\s*guarantee)\b",
    re.I,
)


def _outlook_has_prohibited_expression(text: str) -> bool:
    # Preserve the prior BFF rule exactly, including its producer's whitespace normalization,
    # while retaining the worker's additional English, price and unsupported-causality checks.
    return bool(_LEGACY_PREDICTION.search(re.sub(r"\s+", "", text)) or _OUTLOOK_PROHIBITED.search(text))




class Runner:
    def __init__(self, store: Store, provider=None, *, live_enabled: bool = False, max_calls: int = 0):
        self.store, self.provider = store, provider
        self.live_enabled, self.max_calls = live_enabled, max_calls

    def submit(self, request: Submit) -> JobResult:
        stages = [request.kind] if request.kind in {"semantic-verification", "briefing-outlook"} else [request.kind, "semantic-verification"]
        configs = {k: stage_config(k, request.mode).wire() for k in stages}
        frozen = request.wire()
        identity = dict(frozen)
        identity.pop("jobId")
        revisions = {k: {"prompt": digest(PROMPTS[k]), "schema": digest(ANSWERS[k].model_json_schema(by_alias=True))} for k in stages}
        input_digest = digest({"request": identity, "configs": configs, "revisions": revisions})
        with self.store.transaction() as c:
            old = c.execute("SELECT input_digest FROM jobs WHERE job_id=?", (request.job_id,)).fetchone()
            if old and old["input_digest"] != input_digest:
                raise WorkerFailure("job_input_conflict")
            if not old:
                c.execute("INSERT INTO jobs(job_id,input_digest,request,configs,state,phase,resume_mode,created_at) VALUES (?,?,?,?,'queued','input.persisted','unsent_only',?)",
                          (request.job_id, input_digest, canonical(frozen), canonical(configs), now()))
        return self.get(request.job_id)

    def get(self, job_id: str) -> JobResult:
        row = self.store.job(job_id)
        request = Submit.model_validate_json(row["request"])
        calls = self.store.calls(job_id)
        usage_calls = calls
        usages = [json.loads(c["usage"]) if c["usage"] else {} for c in calls]
        def total(key):
            values = [u.get(key) for u in usages]
            return sum(values) if values and all(v is not None for v in values) else None
        artifacts = self.store.artifacts(job_id)
        cached = self.store.db.execute("SELECT a.payload FROM cache a0 JOIN artifacts a ON a.artifact_id=a0.artifact_id WHERE a0.input_digest=?", (row["input_digest"],)).fetchone()
        if row["phase"] == "artifact.cache_hit" and cached:
            original = json.loads(cached["payload"])
            artifacts = self.store.artifacts(original["jobId"])
            calls = self.store.calls(original["jobId"])
        public_calls = [{"attemptId": c["attempt_id"], "stage": c["stage"], "state": c["state"],
                         "mode": c["mode"], "startedAt": c["started_at"], "receivedAt": c["received_at"],
                         "inputDigest": c["request_digest"], "config": json.loads(c["config"]),
                         "usage": json.loads(c["usage"]) if c["usage"] else None,
                         "error": c["error"], "durationMs": c["duration_ms"]} for c in calls]
        return JobResult(schema_version=SCHEMA_VERSION, job_id=job_id, input_digest=row["input_digest"],
                         state=row["state"], phase=row["phase"], attempt_id=row["attempt_id"],
                         artifact_ids=[a["artifactId"] for a in artifacts], artifacts=artifacts,
                         failure=Failure.model_validate_json(row["failure"]) if row["failure"] else None,
                         resume_mode=row["resume_mode"], input=request,
                         grant=self.store.grant(request.input.grant_id), calls=public_calls,
                         usage=Usage(provider_attempts=sum(c["mode"] == "live" for c in usage_calls),
                                     replay_calls=sum(c["mode"] == "replay" for c in usage_calls),
                                     input_tokens=total("inputTokens"), output_tokens=total("outputTokens"),
                                     cached_tokens=total("cachedTokens"), reasoning_tokens=total("reasoningTokens"), cost=None))

    @contextmanager
    def _lock(self, job_id: str):
        path = self.store.directory / ("job-" + digest(job_id) + ".lock")
        with path.open("a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
            else:
                try:
                    yield True
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

    def cancel(self, job_id: str) -> JobResult:
        with self.store.transaction() as c:
            row = self.store.job(job_id)
            if row["state"] not in {"ready", "failed", "cancelled"}:
                c.execute("UPDATE jobs SET state='cancelled',phase='cancel.requested',resume_mode='none',fence=fence+1 WHERE job_id=?", (job_id,))
        return self.get(job_id)

    def resume(self, job_id: str) -> JobResult:
        row = self.store.job(job_id)
        if row["state"] in {"ready", "cancelled", "reconciling"}:
            return self.get(job_id)
        if row["resume_mode"] not in {"validate_only", "save_only", "unsent_only"}:
            return self.get(job_id)
        return self.run(job_id, resume=True)

    def run(self, job_id: str, *, resume: bool = False) -> JobResult:
        with self._lock(job_id) as acquired:
            if not acquired:
                return self.get(job_id)
            row = self.store.job(job_id)
            if row["state"] in {"ready", "cancelled", "reconciling"} or (row["state"] == "failed" and not resume):
                return self.get(job_id)
            # Acquiring the OS lock proves the previous process stopped, not that its HTTP call was uncharged.
            lost = next((c for c in self.store.calls(job_id) if c["state"] == "started"), None)
            if lost:
                self.store.status(job_id, "reconciling", "provider.response_unknown", "provider_response_unknown", lost["stage"], "reconcile_only")
                return self.get(job_id)
            request = Submit.model_validate_json(row["request"])
            configs = {k: StageConfig.model_validate(v) for k, v in json.loads(row["configs"]).items()}
            fence = row["fence"]
            stage = request.kind
            try:
                if request.kind == "briefing-outlook" and not request.input.issues:
                    self.store.status(job_id, "ready", "empty_round.no_call", fence=fence)
                    return self.get(job_id)
                for kind, config in configs.items():
                    self.store.authorize(request, kind, config)
                cached = self.store.db.execute("SELECT a.payload FROM cache c JOIN artifacts a ON a.artifact_id=c.artifact_id WHERE c.input_digest=?", (row["input_digest"],)).fetchone()
                if cached:
                    self.store.status(job_id, "ready", "artifact.cache_hit", fence=fence)
                    return self.get(job_id)
                received_stages = {c["stage"] for c in self.store.calls(job_id) if c["receipt"] is not None}
                if request.mode == "live" and not configs.keys() <= received_stages:
                    if not self.live_enabled:
                        raise WorkerFailure("live_opt_in_required")
                    self.store.configure_budget(self.max_calls)
                if request.kind == "briefing-outlook":
                    answer, call = self._call(request, stage, self._payload(request), configs[stage], fence)
                    known = {i.event_id for i in request.input.issues}
                    if len(answer.issue_ids) != len(set(answer.issue_ids)) or not set(answer.issue_ids) <= known:
                        raise ValueError("issue_reference_invalid")
                    if _outlook_has_prohibited_expression(answer.rationale):
                        raise ValueError("prohibited_expression")
                    self.store.authorize(request, stage, configs[stage])
                    cfg = configs[stage]
                    artifact = AnalysisArtifact(
                        schema_version=SCHEMA_VERSION, artifact_id="artifact-" + digest({"jobId": job_id, "kind": stage, "inputDigest": row["input_digest"]}),
                        kind=stage, result_version="result-" + digest({"inputDigest": row["input_digest"], "result": answer.wire()}),
                        job_id=job_id, attempt_id=call["attempt_id"], input_digest=row["input_digest"], source_refs=[],
                        dependency_refs=["judgment-" + digest(s) for s in request.input.document_sentiments],
                        model_config_revision=digest(cfg.wire()), prompt_version=cfg.prompt_version, policy_version=cfg.policy_version,
                        produced_at=now(), provenance=request.provenance, company_id=None, grant_id=request.input.grant_id,
                        grant_revision=request.input.grant_revision, claims=[],
                        validation=Validation(exact=True, semantic=None, eligible=True, reason="legacy_outlook_exact_policy"), result=answer)
                    self.store.status(job_id, "persisting", "artifact.validated", resume="save_only", fence=fence)
                    self.store.save_artifact(artifact, row["input_digest"], fence)
                elif request.kind == "semantic-verification":
                    own = next((a for a in self.store.artifacts(job_id) if a["kind"] == request.kind), None)
                    if own:
                        self.store.authorize(request, stage, configs[stage])
                        self.store.status(job_id, "ready", "artifact.persisted", fence=fence)
                        return self.get(job_id)
                    candidate = request.input.candidate
                    exact(candidate, request.input.document)
                    verdict, call = self._call(request, stage, self._payload(request, candidate), configs[stage], fence)
                    eligibility = self._validate_verdict(candidate, verdict)
                    # A receipt proves what was returned, not that authority remained current while it was in flight.
                    self.store.authorize(request, stage, configs[stage])
                    artifact = self._artifact(request, stage, verdict, call, configs[stage], row["input_digest"],
                                              [], candidate.claims, eligibility=eligibility)
                    self.store.status(job_id, "persisting", "artifact.validated", resume="save_only", fence=fence)
                    self.store.save_artifact(artifact, row["input_digest"], fence)
                else:
                    own = next((a for a in self.store.artifacts(job_id) if a["kind"] == request.kind), None)
                    if own:
                        self.store.status(job_id, "ready", "artifact.persisted", fence=fence)
                        return self.get(job_id)
                    candidate, generation = self._call(request, stage, self._payload(request), configs[stage], fence)
                    exact(candidate, request.input.document)
                    stage = "semantic-verification"
                    verdict, verification = self._call(request, stage, self._payload(request, candidate), configs[stage], fence)
                    eligibility = self._validate_verdict(candidate, verdict)
                    verification_artifact = next((a for a in self.store.artifacts(job_id) if a["kind"] == stage), None)
                    if not verification_artifact:
                        va = self._artifact(request, stage, verdict, verification, configs[stage], row["input_digest"], [], candidate.claims)
                        self.store.save_artifact(va, None, fence)
                        verification_artifact = va.wire()
                    # Re-check current grants after receiving the model output, before making an artifact eligible.
                    for kind, config in configs.items():
                        self.store.authorize(request, kind, config)
                    artifact = self._artifact(request, request.kind, candidate, generation, configs[request.kind],
                                              row["input_digest"], [verification_artifact["artifactId"]], candidate.claims,
                                              eligibility=eligibility)
                    self.store.status(job_id, "persisting", "artifact.validated", resume="save_only", fence=fence)
                    self.store.save_artifact(artifact, row["input_digest"], fence)
                self.store.status(job_id, "ready", "artifact.persisted", fence=fence)
            except ProviderError as exc:
                self.store.status(job_id, "reconciling" if exc.uncertain else "failed", "provider.response_unknown" if exc.uncertain else "provider.failed",
                                  exc.code, stage, "reconcile_only" if exc.uncertain else "none", fence=fence)
            except (ValueError, ValidationError) as exc:
                code = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, ValidationError) else "response_schema_invalid"
                self.store.db.execute("UPDATE calls SET state='failed',error=? WHERE job_id=? AND stage=? AND state='received'", (code, job_id, stage))
                self.store.status(job_id, "failed", "validation.failed", code, stage, fence=fence)
            except WorkerFailure as exc:
                resume_mode = "unsent_only" if exc.code in {"global_budget_exhausted", "live_opt_in_required", "live_budget_required"} else "none"
                self.store.status(job_id, "failed", "authorization_or_budget.failed", exc.code, stage, resume_mode, fence=fence)
            except (OSError, sqlite3.Error):
                unknown = any(c["state"] == "started" for c in self.store.calls(job_id))
                if unknown:
                    self.store.status(job_id, "reconciling", "provider.response_unknown", "provider_receipt_not_saved", stage, "reconcile_only", fence=fence)
                else:
                    self.store.status(job_id, "persisting", "storage.failed", "artifact_storage_failed", stage, "save_only", fence=fence)
            return self.get(job_id)

    def _payload(self, request, candidate=None):
        if request.kind == "briefing-outlook":
            return {"schemaVersion": SCHEMA_VERSION, **request.input.wire()}
        payload = {"schemaVersion": SCHEMA_VERSION, "document": request.input.document.wire(),
                   "company": request.input.company.wire(),
                   "grantRef": {"grantId": request.input.grant_id, "revision": request.input.grant_revision}}
        if candidate is not None:
            payload["candidate"] = candidate.wire()
        return payload

    def _call(self, request, stage, payload, config, fence):
        previous = next((c for c in self.store.calls(request.job_id) if c["stage"] == stage), None)
        if previous:
            if previous["receipt"] is None:
                if previous["error"]:
                    raise ProviderError(previous["error"], uncertain=previous["state"] == "unknown")
                raise ProviderError("provider_response_unknown", uncertain=True)
            return ANSWERS[stage].model_validate_json(previous["content"]), previous
        if self.provider is None:
            raise WorkerFailure("provider_not_configured")
        if (request.mode == "replay") != isinstance(self.provider, ReplayProvider):
            raise ProviderError("provider_mode_mismatch")
        if request.mode == "live" and self.provider.provider_revision != config.provider_revision:
            raise ProviderError("provider_configuration_changed")
        self.store.authorize(request, stage, config)
        attempt_id = "attempt-" + uuid.uuid4().hex
        ordinal = self.store.reserve(job_id=request.job_id, stage=stage, request_digest=request_identity(stage, payload, config),
                                     config=config.wire(), mode=request.mode, fence=fence, attempt_id=attempt_id,
                                     fixture_digest=self.provider.fixture_digest if isinstance(self.provider, ReplayProvider) else None)
        started = time.perf_counter()
        try:
            reply = self.provider.complete(stage, payload, config, ordinal=ordinal or 0)
        except ProviderError as exc:
            self.store.db.execute("UPDATE calls SET state=?,error=?,duration_ms=? WHERE attempt_id=?",
                                  ("unknown" if exc.uncertain else "failed", exc.code, (time.perf_counter() - started) * 1000, attempt_id))
            raise
        self.store.receive(attempt_id, reply, (time.perf_counter() - started) * 1000)
        call = next(c for c in self.store.calls(request.job_id) if c["attempt_id"] == attempt_id)
        return ANSWERS[stage].model_validate_json(reply.content), call

    def _validate_verdict(self, candidate, verdict: VerificationAnswer):
        known = {c.claim_id for c in candidate.claims}
        returned = [v.claim_id for v in verdict.claims]
        if set(returned) != known or len(returned) != len(known):
            raise ValueError("semantic_claim_coverage_invalid")
        if verdict.prohibited_advice or verdict.unsupported_causality or any(c.decision == "contradicted" for c in verdict.claims):
            return "reject"
        if any(c.decision == "insufficient" for c in verdict.claims):
            return "hold"
        return "supported"

    def _artifact(self, request, kind, result, call, config, input_digest, dependencies, claims, *, eligibility=None):
        if eligibility is not None:
            semantic = eligibility
        else:
            known = {c.claim_id for c in claims}
            returned = [c.claim_id for c in result.claims]
            if set(returned) != known or len(returned) != len(known):
                raise ValueError("semantic_claim_coverage_invalid")
            semantic = "reject" if result.prohibited_advice or result.unsupported_causality or any(c.decision == "contradicted" for c in result.claims) else "hold" if any(c.decision == "insufficient" for c in result.claims) else "supported"
        identifier = "artifact-" + digest({"jobId": request.job_id, "kind": kind, "inputDigest": input_digest})
        return AnalysisArtifact(schema_version=SCHEMA_VERSION, artifact_id=identifier, kind=kind,
                                result_version="result-" + digest({"inputDigest": input_digest, "kind": kind, "result": result.wire()}),
                                job_id=request.job_id, attempt_id=call["attempt_id"], input_digest=input_digest,
                                source_refs=[request.input.document], dependency_refs=dependencies,
                                model_config_revision=digest(config.wire()), prompt_version=config.prompt_version,
                                policy_version=config.policy_version, produced_at=now(), provenance=request.provenance,
                                company_id=request.input.company.company_id, grant_id=request.input.grant_id,
                                grant_revision=request.input.grant_revision, claims=claims,
                                validation=Validation(exact=True, semantic=semantic, eligible=semantic == "supported",
                                                      reason=None if semantic == "supported" else "semantic_" + semantic), result=result)
