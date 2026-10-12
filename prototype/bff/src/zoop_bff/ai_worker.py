"""Process transport and application import gate. HTTP readers only read this BFF store."""
from __future__ import annotations

import hashlib
import json
import re
import os
import signal
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from .admin_jobs import LaunchSpec, Launcher, popen_launcher
from .config import BFF_ROOT
from .dataset import Dataset
from .schemas import AnalysisSummary, BriefingOutlook, DocumentSentiment
from .statedb import StateDb, dumps, utc_iso

SCHEMA_VERSION = "zoop-ai-s1-1"
DOCUMENT_POLICY_VERSION = "zoop-document-gate-2"

# The S1 worker is a separately installed process (ai/worker, `make worker-install`); the BFF never imports it.
WORKER_ROOT = BFF_ROOT.parents[1] / "ai" / "worker"
WORKER_COMMAND = (str(WORKER_ROOT / ".venv" / "bin" / "zoop-ai"),)
_LEGACY_OUTLOOK_PREDICTION = re.compile(r"예측|전망|오를|내릴|호재|악재|매수|매도|추천|목표가|수익률")
_OUTLOOK_PROHIBITED = re.compile(
    r"매수|매도|추천|목표가|주가|수익.{0,8}보장|지수.{0,16}(상승|하락)|"
    r"가격.{0,16}(상승|하락|오른|내린)|확정.{0,8}인과|때문에.{0,12}(상승|하락)|"
    r"\b(buy|sell|invest|recommend|forecast|predict|stock\s*price|price\s*target|profit\s*guarantee)\b",
    re.I,
)


def _outlook_has_prohibited_expression(text: str) -> bool:
    return bool(
        _LEGACY_OUTLOOK_PREDICTION.search(re.sub(r"\s+", "", text))
        or _OUTLOOK_PROHIBITED.search(text)
    )




def _digest(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def outlook_job(payload: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    frozen = {**payload, "sourceId": context["sourceId"], "grantId": context["grantId"],
              "grantRevision": context["grantRevision"]}
    return {"schemaVersion": SCHEMA_VERSION, "jobId": "outlook-" + payload["roundId"] + "-" + _digest(frozen)[:24],
            "kind": "briefing-outlook", "mode": context["mode"], "input": frozen,
            "provenance": {"sourceKind": context["sourceKind"], "executionMode": context["mode"],
                           "recordingKind": "authored-test" if context["mode"] == "replay" else "provider"}}


class AnalysisImportError(ValueError):
    pass


class AiWorkerClient:
    """Uses the established LaunchSpec/process-group supervision seam; never reads a worker DB."""
    def __init__(self, *, state_dir: Path, worker_state: Path, grants: Path | None = None,
                 replay: Path | None = None, env: dict[str, str] | None = None, launcher: Launcher = popen_launcher,
                 worker_command: Sequence[str] = WORKER_COMMAND):
        # The worker runs in a throwaway request folder, so every caller path is made absolute here, against the
        # caller's working directory, before any launch.
        def absolute(path):
            return None if path is None else Path(os.path.abspath(path))
        self.state_dir, self.worker_state = absolute(state_dir), absolute(worker_state)
        self.grants, self.replay, self.env, self.launcher = absolute(grants), absolute(replay), env, launcher
        self.worker_command = tuple(os.path.abspath(part) if index == 0 and os.sep in part else part
                                    for index, part in enumerate(worker_command))

    def command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.worker_command or not os.access(self.worker_command[0], os.X_OK):
            raise AnalysisImportError("worker_unavailable")
        private = self.state_dir / "ai-transport"
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(private, 0o700)
        with tempfile.TemporaryDirectory(prefix="request-", dir=private) as tmp:
            folder = Path(tmp)
            incoming, outgoing, errors = folder / "input.json", folder / "output.json", folder / "stderr.txt"
            incoming.write_text(dumps(payload), encoding="utf-8")
            os.chmod(incoming, 0o600)
            argv = [*self.worker_command, command, "--state-dir", str(self.worker_state)]
            if self.grants:
                argv += ["--grants", str(self.grants)]
            if self.replay:
                argv += ["--replay", str(self.replay)]
            # Caller explicitly selects stage settings. No .env, PoC private probe, or automatic model opt-in.
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()),
                   "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
            if self.env:
                env.update(self.env)
            spec = LaunchSpec(argv=argv, cwd=folder, env=env, stdin=incoming, stdout=outgoing, stderr=errors)
            process = self.launcher(spec)
            deadline = time.monotonic() + 120
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    process.send_signal(signal.SIGTERM)
                    raise AnalysisImportError("worker_transport_unknown; use get/resume, never resubmit a new job")
                time.sleep(0.02)
            if outgoing.stat().st_size > 16 * 1024 * 1024:
                raise AnalysisImportError("worker_output_too_large")
            result = json.loads(outgoing.read_text(encoding="utf-8"))
            if result.get("schemaVersion") != SCHEMA_VERSION or "error" in result:
                raise AnalysisImportError(result.get("error", {}).get("code", "worker_schema_invalid"))
            return result

    def get(self, job_id: str) -> dict[str, Any]:
        return self.command("get", {"schemaVersion": SCHEMA_VERSION, "jobId": job_id})


class DocumentAnalysisStore:
    def __init__(self, db: StateDb, clock):
        self.db, self.clock = db, clock

    def deny(self, document_id: str, reason: str) -> None:
        """Current gate is separate from immutable worker receipts and imported artifacts."""
        if not reason.strip():
            raise AnalysisImportError("visibility_reason_required")
        self.db.execute("INSERT INTO document_analysis_visibility VALUES (?,1,?,1) ON CONFLICT(document_id) DO UPDATE SET denied=1,reason=excluded.reason,revision=revision+1", (document_id, reason))

    def denied(self, document_id: str) -> bool:
        row = self.db.one("SELECT denied FROM document_analysis_visibility WHERE document_id=?", (document_id,))
        return bool(row and row["denied"])

    def replace_current_grants(self, grants: list[dict[str, Any]]) -> None:
        """Replace the server-owned authority snapshot; worker job output cannot call this path."""
        required = {"grantId", "revision", "sourceId", "enabled", "rights", "allowedOperations",
                    "recipients", "purposes", "evidence", "expiresAt"}
        ids: list[str] = []
        for grant in grants:
            if set(grant) != required or not all(isinstance(grant.get(k), str) and grant[k] for k in ("grantId", "revision", "sourceId")):
                raise AnalysisImportError("current_grant_schema_invalid")
            ids.append(grant["grantId"])
        if len(ids) != len(set(ids)):
            raise AnalysisImportError("current_grant_duplicate")
        with self.db.transaction() as c:
            if ids:
                c.execute("DELETE FROM document_analysis_grants WHERE grant_id NOT IN (" + ",".join("?" for _ in ids) + ")", ids)
            else:
                c.execute("DELETE FROM document_analysis_grants")
            for grant in grants:
                c.execute("INSERT INTO document_analysis_grants VALUES (?,?,?) ON CONFLICT(grant_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload",
                          (grant["grantId"], grant["revision"], dumps(grant)))

    def _artifact_source_job(self, result: dict[str, Any]) -> str:
        artifacts = result.get("artifacts", [])
        if not artifacts:
            return result["jobId"]
        artifact_ids = [a.get("artifactId") for a in artifacts]
        source_jobs = {a.get("jobId") for a in artifacts}
        if (len(source_jobs) != 1 or None in source_jobs or len(artifact_ids) != len(set(artifact_ids))
                or set(artifact_ids) != set(result.get("artifactIds", []))):
            raise AnalysisImportError("artifact_source_job_invalid")
        source_job = next(iter(source_jobs))
        if result.get("phase") == "artifact.cache_hit":
            artifact_attempts = {a.get("attemptId") for a in artifacts}
            call_attempts = {call.get("attemptId") for call in result.get("calls", [])}
            if None in artifact_attempts or artifact_attempts != call_attempts:
                raise AnalysisImportError("cached_artifact_receipts_invalid")
        elif source_job != result["jobId"]:
            raise AnalysisImportError("artifact_source_job_invalid")
        return source_job

    def _import_call(self, c, job_id: str, call: dict[str, Any]) -> None:
        existing = c.execute("SELECT * FROM document_analysis_calls WHERE attempt_id=?", (call["attemptId"],)).fetchone()
        if existing is None:
            c.execute("INSERT INTO document_analysis_calls VALUES (?,?,?,?,?,?,?)",
                      (call["attemptId"], job_id, call["stage"], call["mode"], call["state"], call["startedAt"], dumps(call)))
            return
        old = json.loads(existing["payload"])
        fixed = ("attemptId", "stage", "mode", "startedAt", "inputDigest", "config")
        if existing["job_id"] != job_id or any(old.get(key) != call.get(key) for key in fixed):
            raise AnalysisImportError("attempt_identity_conflict")
        transitions = {
            "started": {"received", "validated", "failed", "unknown"},
            "received": {"validated", "failed"},
            "validated": set(),
            "failed": set(),
            "unknown": set(),
        }
        old_state, new_state = old["state"], call["state"]
        if old_state == new_state:
            state = old_state
        elif new_state in transitions.get(old_state, set()):
            state = new_state
        elif old_state in transitions.get(new_state, set()):
            state = old_state  # a delayed earlier snapshot is a no-op
        else:
            raise AnalysisImportError("attempt_state_conflict")
        merged = dict(old)
        for key in ("receivedAt", "error", "durationMs"):
            previous, incoming = old.get(key), call.get(key)
            if previous is not None and incoming is not None and previous != incoming:
                raise AnalysisImportError("attempt_receipt_conflict")
            if previous is None and incoming is not None:
                merged[key] = incoming
        previous_usage, incoming_usage = old.get("usage"), call.get("usage")
        if previous_usage is None:
            if incoming_usage is not None:
                merged["usage"] = incoming_usage
        elif incoming_usage is not None:
            usage = dict(previous_usage)
            for key, incoming in incoming_usage.items():
                previous = usage.get(key)
                if previous is not None and incoming is not None and previous != incoming:
                    raise AnalysisImportError("attempt_usage_conflict")
                if previous is None and incoming is not None:
                    usage[key] = incoming
            merged["usage"] = usage
        merged["state"] = state
        if merged != old:
            c.execute("UPDATE document_analysis_calls SET state=?,payload=? WHERE attempt_id=?",
                      (state, dumps(merged), call["attemptId"]))

    def _import_job_state(self, c, result: dict[str, Any], kind: str, document_id: str,
                          document_version: str, company_id: str, status: str, reason: str | None) -> None:
        old = c.execute("SELECT * FROM document_analysis_jobs WHERE job_id=?", (result["jobId"],)).fetchone()
        values = (result["inputDigest"], kind, document_id, document_version, company_id)
        if old is None:
            c.execute("INSERT INTO document_analysis_jobs VALUES (?,?,?,?,?,?,?,?,?)",
                      (result["jobId"], *values, status, reason, utc_iso(self.clock.now())))
            return
        if tuple(old[key] for key in ("input_digest", "kind", "document_id", "document_version", "company_id")) != values:
            raise AnalysisImportError("job_input_conflict")
        # Worker terminal results are immutable. Re-importing one must not move it ahead of a newer job.
        if old["status"] != "pending":
            return
        if old["status"] != status or old["reason"] != reason:
            c.execute("UPDATE document_analysis_jobs SET status=?,reason=?,updated_at=? WHERE job_id=?",
                      (status, reason, utc_iso(self.clock.now()), result["jobId"]))

    def _grant(self, grant: dict[str, Any] | None, source_id: str, revision: str, kind: str, provider: str) -> str | None:
        if not grant or grant.get("rights") != "known" or not grant.get("enabled") or not grant.get("evidence"):
            return "source_rights_unknown_or_denied"
        if grant.get("sourceId") != source_id or grant.get("revision") != revision:
            return "grant_revision_or_source_changed"
        if not {"read", "store", "model-send", "quote-display"} <= set(grant.get("allowedOperations", [])):
            return "source_operation_denied"
        if kind not in grant.get("purposes", []) or provider not in grant.get("recipients", []):
            return "source_purpose_or_recipient_denied"
        expiry = grant.get("expiresAt")
        if expiry:
            try:
                if datetime.fromisoformat(expiry) <= datetime.now(UTC):
                    return "source_grant_expired"
            except (ValueError, TypeError):
                return "source_grant_expiry_invalid"
        return None

    def import_outlook(self, expected: dict[str, Any], result: dict[str, Any]) -> BriefingOutlook:
        if result.get("schemaVersion") != SCHEMA_VERSION or result.get("state") != "ready" or result["input"] != expected:
            raise AnalysisImportError("outlook_worker_not_ready_or_context_changed")
        artifacts = [a for a in result["artifacts"] if a["kind"] == "briefing-outlook"]
        if len(artifacts) != 1:
            raise AnalysisImportError("outlook_artifact_missing")
        a = artifacts[0]
        call = next((c for c in result["calls"] if c["attemptId"] == a["attemptId"]), None)
        if not call or call["state"] != "validated" or call["stage"] != "briefing-outlook" or a["inputDigest"] != result["inputDigest"] or a["modelConfigRevision"] != _digest(call["config"]):
            raise AnalysisImportError("outlook_receipt_invalid")
        if a["policyVersion"] != "legacy-outlook-exact-1" or a["validation"] != {"exact": True, "semantic": None, "eligible": True, "reason": "legacy_outlook_exact_policy"} or a["provenance"] != expected["provenance"] or a["sourceRefs"] != [] or a["companyId"] is not None:
            raise AnalysisImportError("outlook_validation_invalid")
        context = expected["input"]
        cfg = call["config"]
        recipient = cfg["provider"] if cfg["provider"] == "authored-replay" else cfg["provider"] + ":" + cfg["providerRevision"]
        reason = self._grant(result.get("grant"), context["sourceId"], context["grantRevision"], "briefing-outlook", recipient)
        if reason or a["grantId"] != context["grantId"] or a["grantRevision"] != context["grantRevision"]:
            raise AnalysisImportError(reason or "outlook_grant_mismatch")
        answer = a["result"]
        if _outlook_has_prohibited_expression(answer["rationale"]):
            raise AnalysisImportError("prohibited_expression")
        known = {i["eventId"] for i in context["issues"]}
        if not answer["issueIds"] or len(set(answer["issueIds"])) != len(answer["issueIds"]) or not set(answer["issueIds"]) <= known:
            raise AnalysisImportError("issue_reference_invalid")
        output = BriefingOutlook(label=answer["label"], rationale=answer["rationale"], issue_ids=answer["issueIds"],
                                judged_at=a["producedAt"], model=cfg["model"], prompt_version=a["promptVersion"])
        with self.db.transaction() as c:
            old = c.execute("SELECT payload FROM briefing_outlook_results WHERE artifact_id=?", (a["artifactId"],)).fetchone()
            if old and old["payload"] != dumps(a):
                raise AnalysisImportError("outlook_artifact_conflict")
            c.execute("INSERT OR IGNORE INTO briefing_outlook_results VALUES (?,?,?,?,?,?)",
                      (a["artifactId"], result["jobId"], result["inputDigest"], context["roundId"], utc_iso(self.clock.now()), dumps(a)))
            for receipt in result["calls"]:
                self._import_call(c, result["jobId"], receipt)
        return output

    def import_outlook_failure(self, expected: dict[str, Any], result: dict[str, Any]) -> None:
        if result.get("schemaVersion") != SCHEMA_VERSION or result["input"] != expected:
            raise AnalysisImportError("outlook_failure_context_changed")
        with self.db.transaction() as c:
            for receipt in result["calls"]:
                if receipt["stage"] != "briefing-outlook":
                    raise AnalysisImportError("outlook_failure_receipt_scope_invalid")
                self._import_call(c, result["jobId"], receipt)

    def import_job(self, ds: Dataset, result: dict[str, Any]) -> dict[str, Any]:
        if result.get("schemaVersion") != SCHEMA_VERSION:
            raise AnalysisImportError("worker_schema_invalid")
        request = result["input"]
        if request.get("schemaVersion") != SCHEMA_VERSION or request["jobId"] != result["jobId"]:
            raise AnalysisImportError("worker_job_reference_invalid")
        kind = request["kind"]
        if kind not in {"document-summary", "document-sentiment"}:
            raise AnalysisImportError("document_import_kind_invalid")
        source = request["input"]["document"]
        company_id = request["input"]["company"]["companyId"]
        rec = ds.article_for(source["documentId"])
        if rec is None or rec.poc is None or company_id not in ds.companies:
            raise AnalysisImportError("document_context_unknown")
        if request["input"]["company"]["name"] != ds.companies[company_id].name or not any(rec.id in issue.article_ids for issue in ds.issues_of_company(company_id)):
            raise AnalysisImportError("company_context_mismatch")
        provenance = request["provenance"]
        if provenance["sourceKind"] != ("synthetic" if rec.synthetic else "actual") or (request["mode"] == "replay" and (not rec.synthetic or provenance["recordingKind"] != "authored-test")):
            raise AnalysisImportError("authored_replay_requires_synthetic")
        if source["documentVersion"] != rec.version or source["sourceHash"] != _digest(rec.poc.body) or source["text"] != rec.poc.body or source["inputKind"] != rec.poc.input_kind:
            raise AnalysisImportError("document_version_or_hash_changed")
        denied = self.db.one("SELECT denied FROM document_analysis_visibility WHERE document_id=?", (rec.id,))
        if rec.poc.withdrawn or denied and denied["denied"]:
            raise AnalysisImportError("document_withdrawn")
        artifact_source_job = self._artifact_source_job(result)
        candidates = [a for a in result["artifacts"] if a["kind"] == kind]
        artifact = candidates[0] if len(candidates) == 1 else None
        status = "pending" if result["state"] in {"queued", "running", "persisting", "reconciling"} else "failed"
        reason = result["failure"]["code"] if result.get("failure") else result["phase"]
        if result["state"] == "cancelled":
            status, reason = "failed", "cancelled"
        if result["state"] != "ready":
            artifact = None
        execution_grant = result.get("grant")
        call = next((c for c in result.get("calls", []) if artifact and c["attemptId"] == artifact["attemptId"]), None)
        recipient = "authored-replay" if request["mode"] == "replay" else (
            call["config"]["provider"] + ":" + call["config"]["providerRevision"] if call else "unresolved-recipient")
        execution_grant_reason = self._grant(
            execution_grant, source["sourceId"], request["input"]["grantRevision"], kind, recipient
        )
        if artifact:
            if artifact.get("policyVersion") != DOCUMENT_POLICY_VERSION:
                status, reason = "withheld", "document_policy_outdated"
                artifact = None
            else:
                self._validate_artifact(ds, result, artifact, source, company_id, artifact_source_job)
                if execution_grant_reason:
                    status, reason = "withheld", execution_grant_reason
                    artifact = None
                elif not artifact["validation"]["eligible"]:
                    status, reason = "withheld", artifact["validation"].get("reason") or "semantic_hold"
                    artifact = None
                else:
                    status, reason = "available", None
        with self.db.transaction() as c:
            if artifact:
                current_row = c.execute(
                    "SELECT payload FROM document_analysis_grants WHERE grant_id=?", (artifact["grantId"],)
                ).fetchone()
                current_grant = json.loads(current_row["payload"]) if current_row else None
                current_reason = self._grant(
                    current_grant, source["sourceId"], artifact["grantRevision"], kind, recipient
                )
                if not current_reason:
                    current_reason = self._grant(
                        current_grant, source["sourceId"], artifact["grantRevision"],
                        "semantic-verification", recipient
                    )
                if current_reason:
                    status, reason = "withheld", current_reason
                    artifact = None
            self._import_job_state(c, result, kind, rec.id, rec.version, company_id, status, reason)
            # Model/replay receipt accounting is imported even if semantic validation withheld the public result.
            for imported_call in result.get("calls", []):
                self._import_call(c, artifact_source_job, imported_call)
            if artifact:
                existing = c.execute("SELECT payload FROM document_analysis WHERE artifact_id=?", (artifact["artifactId"],)).fetchone()
                if existing and existing["payload"] != dumps(artifact):
                    raise AnalysisImportError("artifact_input_conflict")
                c.execute("INSERT OR IGNORE INTO document_analysis VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (artifact["artifactId"], artifact_source_job, result["inputDigest"], kind, rec.id, rec.version,
                           source["sourceHash"], company_id, artifact["grantId"], artifact["grantRevision"], utc_iso(self.clock.now()), dumps(artifact)))
        return {"jobId": result["jobId"], "status": status, "reason": reason, "artifactId": artifact["artifactId"] if artifact else None}

    def _validate_artifact(self, ds, job, artifact, source, company_id, artifact_source_job):
        if (artifact.get("schemaVersion") != SCHEMA_VERSION or artifact["inputDigest"] != job["inputDigest"]
                or artifact.get("jobId") != artifact_source_job or artifact["companyId"] != company_id
                or artifact["sourceRefs"] != [source] or artifact["provenance"] != job["input"]["provenance"]):
            raise AnalysisImportError("artifact_context_mismatch")
        if artifact.get("policyVersion") != DOCUMENT_POLICY_VERSION:
            raise AnalysisImportError("document_policy_outdated")
        v = artifact["validation"]
        if not v["exact"] or v["eligible"] != (v["semantic"] == "supported"):
            raise AnalysisImportError("artifact_validation_invalid")
        calls = {c["attemptId"]: c for c in job.get("calls", [])}
        call = calls.get(artifact["attemptId"])
        if (not call or call["state"] != "validated" or call["stage"] != artifact["kind"]
                or artifact["modelConfigRevision"] != _digest(call["config"])
                or call["config"].get("policyVersion") != DOCUMENT_POLICY_VERSION):
            raise AnalysisImportError("artifact_receipt_missing")
        dependencies = {a["artifactId"]: a for a in job["artifacts"] if a["kind"] == "semantic-verification"}
        if len(artifact["dependencyRefs"]) != 1 or artifact["dependencyRefs"][0] not in dependencies:
            raise AnalysisImportError("semantic_receipt_missing")
        verifier = dependencies[artifact["dependencyRefs"][0]]
        verdict = verifier["result"]
        semantic = "reject" if verdict["prohibitedAdvice"] or verdict["unsupportedCausality"] or any(c["decision"] == "contradicted" for c in verdict["claims"]) else "hold" if any(c["decision"] == "insufficient" for c in verdict["claims"]) else "supported"
        verify_call = calls.get(verifier["attemptId"])
        if (not verify_call or verify_call["state"] != "validated" or verify_call["stage"] != "semantic-verification"
                or semantic != v["semantic"] or verifier.get("jobId") != artifact_source_job
                or verifier["companyId"] != company_id or verifier["sourceRefs"] != [source]
                or verifier.get("policyVersion") != DOCUMENT_POLICY_VERSION
                or verifier.get("modelConfigRevision") != _digest(verify_call["config"])
                or verify_call["config"].get("policyVersion") != DOCUMENT_POLICY_VERSION):
            raise AnalysisImportError("semantic_receipt_invalid")
        claims = artifact["claims"]
        if claims != artifact["result"]["claims"] or {c["claimId"] for c in claims} != {c["claimId"] for c in verdict["claims"]}:
            raise AnalysisImportError("semantic_claim_coverage_invalid")
        refs = {e["evidenceId"]: e for e in artifact["result"]["citations"]}
        for evidence_id, citation in refs.items():
            ev = ds.evidence.get(evidence_id)
            start, end = citation["start"], citation["end"]
            if ev is None or (ev.article_id, ev.article_version, ev.start, ev.end, ev.quote) != (source["documentId"], source["documentVersion"], start, end, citation["quote"]) or citation["offsetUnit"] != "unicode_code_point" or citation["textArtifactId"] != source["textArtifactId"] or citation["inputKind"] != source["inputKind"] or not 0 <= start < end <= len(source["text"]) or source["text"][start:end] != citation["quote"]:
                raise AnalysisImportError("citation_current_evidence_mismatch")
        if any(not set(c["evidenceIds"]) <= refs.keys() or c["assertionKind"] != "limitation" and not c["evidenceIds"] for c in claims):
            raise AnalysisImportError("claim_citation_missing")
        limitation_texts = [c["text"] for c in claims if c["assertionKind"] == "limitation"]
        if artifact["result"].get("limitations") != limitation_texts:
            raise AnalysisImportError("limitation_claim_coverage_invalid")
        rendered = "\n".join(c["text"] for c in claims if c["assertionKind"] != "limitation")
        if artifact["result"].get("text", artifact["result"].get("rationale")) != rendered:
            raise AnalysisImportError("artifact_unattributed_text")
        if artifact["kind"] == "document-summary":
            self._summary(artifact)
        else:
            self._sentiment(artifact, call)

    def _summary(self, a):
        source = a["sourceRefs"][0]
        return AnalysisSummary(schema_version=SCHEMA_VERSION, artifact_id=a["artifactId"],
                               document_id=source["documentId"], document_version=source["documentVersion"],
                               result_version=a["resultVersion"], produced_at=a["producedAt"], provenance=a["provenance"],
                               **a["result"])

    def _sentiment(self, a, call):
        return DocumentSentiment(label=a["result"]["label"], company_id=a["companyId"],
                                 rationale=a["result"]["rationale"], quotes=[e["quote"] for e in a["result"]["citations"]],
                                 judged_at=a["producedAt"], model=call["config"]["model"], prompt_version=a["promptVersion"])

    def public(self, ds: Dataset, document_id: str, company_id: str, *, document_version: str | None = None):
        rec = ds.article_for(document_id, document_version) if document_version else ds.article_for(document_id)
        statuses = {name: {"status": "not_requested", "reason": "분석을 요청하지 않았습니다."} for name in ("summary", "sentiment")}
        output = {"document_summary": None, "sentiment": None, "analysis_status": statuses,
                  "analysis_provenance": None, "result_version": None, "document_version": rec.version if rec else document_version}
        current = ds.article_for(document_id)
        visibility = self.db.one("SELECT * FROM document_analysis_visibility WHERE document_id=?", (document_id,))
        for name, kind in (("summary", "document-summary"), ("sentiment", "document-sentiment")):
            job = self.db.one("SELECT * FROM document_analysis_jobs WHERE document_id=? AND company_id=? AND kind=? ORDER BY updated_at DESC,rowid DESC", (document_id, company_id, kind))
            if not job:
                continue
            statuses[name] = {"status": job["status"], "reason": job["reason"]}
            row = self.db.one("SELECT * FROM document_analysis WHERE input_digest=? AND kind=?", (job["input_digest"], kind))
            if not row:
                continue
            a = json.loads(row["payload"])
            grant_row = self.db.one("SELECT payload FROM document_analysis_grants WHERE grant_id=?", (row["grant_id"],))
            grant = json.loads(grant_row["payload"]) if grant_row else None
            call_row = self.db.one("SELECT payload FROM document_analysis_calls WHERE attempt_id=?", (a["attemptId"],))
            call = json.loads(call_row["payload"]) if call_row else None
            reason = None
            if visibility and visibility["denied"]:
                reason = visibility["reason"]
            elif rec is None or rec.poc is None or rec.poc.withdrawn:
                reason = "document_withdrawn"
            elif current is None or rec.version != current.version or row["document_version"] != rec.version or row["source_hash"] != _digest(rec.poc.body):
                reason = "document_version_or_hash_changed"
            elif a.get("policyVersion") != DOCUMENT_POLICY_VERSION:
                reason = "document_policy_outdated"
            elif not call:
                reason = "artifact_receipt_missing"
            else:
                cfg = call["config"]
                recipient = cfg["provider"] if cfg["provider"] == "authored-replay" else cfg["provider"] + ":" + cfg["providerRevision"]
                reason = self._grant(grant, a["sourceRefs"][0]["sourceId"], row["grant_revision"], kind, recipient)
                if not reason:
                    reason = self._grant(grant, a["sourceRefs"][0]["sourceId"], row["grant_revision"], "semantic-verification", recipient)
            if reason:
                statuses[name] = {"status": "withheld", "reason": reason}
                continue
            statuses[name] = {"status": "available", "reason": None}
            if name == "summary":
                output["document_summary"] = self._summary(a)
            else:
                output["sentiment"] = self._sentiment(a, call)
            if name == "summary" or output["result_version"] is None:
                output["result_version"], output["analysis_provenance"] = a["resultVersion"], a["provenance"]
        return output
