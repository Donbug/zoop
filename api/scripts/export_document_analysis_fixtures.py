#!/usr/bin/env python3
"""Authors the worker-result fixtures of the Spring document analysis tests with the REAL worker and the REAL service wire models.

Nothing here is derived from the Java code under test. A synthetic document (Korean, an emoji and quote/backslash characters, so
that UTF-16 and code point offsets differ) is answered by an authored replay recording, run through `zoop_ai.runner.Runner` (the
worker the AI service dispatches), and the job, its status and its result envelope are rendered with `zoop_ai_service.wire` (the
models the service answers with). The scenarios are: a supported summary (plus the same question asked by a second job, which the
worker serves from its artifact cache), a supported sentiment, a summary the verifier holds, a summary the verifier rejects and a
job whose provider answer failed.

Run it with the ai/service interpreter (it has zoop_ai and zoop_ai_service installed), from the repository root:

  ai/service/.venv/bin/python api/scripts/export_document_analysis_fixtures.py

The output is committed: api/src/test/resources/document-analysis/worker-results.json. Ids, attempt ids and timestamps change on
every run, so regenerate only when the contract changes, and re-run the Java tests afterwards.
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from zoop_ai.contracts import SCHEMA_VERSION, SourceGrant, Submit, digest
from zoop_ai.provider import ReplayProvider, request_identity, stage_config
from zoop_ai.runner import Runner
from zoop_ai.store import Store
from zoop_ai_service.wire import (Delivery, Dispatch, JobStatus, JobView, ResultEnvelope, Usage, next_action,
                                  unreceipted_attempts)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "api" / "src" / "test" / "resources" / "document-analysis" / "worker-results.json"
STAMP = "2026-10-14T01:02:03Z"

SOURCE_ID = "authored-synthetic"
DOCUMENT_ID = "doc-" + "ab" * 32
DOCUMENT_VERSION = "7e" * 32
TEXT = "\U0001F600 삼성전자 매출이 늘었다. \"인용\" 부호와 \\ 역슬래시.\n두 번째 문단: 합성 베타의 비용이 늘었다."
FIRST = "\U0001F600 삼성전자 매출이 늘었다."
SECOND = "합성 베타의 비용이 늘었다."
LIMITATION = "합성 문서에 적힌 내용만 다룹니다."
COMPANY = {"companyId": "SYNTH-A", "name": "합성 알파"}
GRANT = {"grantId": "grant-analysis-fixture", "revision": "rev-1"}


def document() -> dict:
    return {"documentId": DOCUMENT_ID, "documentVersion": DOCUMENT_VERSION, "sourceId": SOURCE_ID,
            "textArtifactId": "text-" + DOCUMENT_VERSION, "inputKind": "body", "cleanerVersion": "exact-copy-1", "text": TEXT,
            "sourceHash": digest(TEXT), "rawLocators": [{"locatorId": "raw-1", "start": 0, "end": len(TEXT)}]}


def citation(evidence_id: str, quote: str) -> dict:
    start = TEXT.index(quote)
    return {"evidenceId": evidence_id, "documentId": DOCUMENT_ID, "documentVersion": DOCUMENT_VERSION,
            "textArtifactId": "text-" + DOCUMENT_VERSION, "offsetUnit": "unicode_code_point", "start": start,
            "end": start + len(quote), "quote": quote, "inputKind": "body", "rawLocatorIds": ["raw-1"]}


def answer(kind: str) -> dict:
    claims = [{"claimId": "claim-a", "text": FIRST, "assertionKind": "fact" if kind == "document-summary" else "interpretation",
               "evidenceIds": ["e1"]},
              {"claimId": "claim-b", "text": SECOND, "assertionKind": "fact" if kind == "document-summary" else "interpretation",
               "evidenceIds": ["e2"]},
              {"claimId": "claim-limit", "text": LIMITATION, "assertionKind": "limitation", "evidenceIds": []}]
    rendered = FIRST + "\n" + SECOND
    base = {"claims": claims, "citations": [citation("e1", FIRST), citation("e2", SECOND)], "limitations": [LIMITATION]}
    if kind == "document-summary":
        return {"text": rendered, **base}
    return {"label": "mixed", "rationale": rendered, **base}


def verdict(answer_: dict, decision: str = "supported", *, advice: bool = False) -> dict:
    return {"claims": [{"claimId": c["claimId"], "decision": decision if index == 0 else "supported", "reason": "합성 판정 표본"}
                       for index, c in enumerate(answer_["claims"])],
            "prohibitedAdvice": advice, "unsupportedCausality": False}


def submit_of(job_id: str, kind: str) -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "jobId": job_id, "kind": kind,
            "input": {"document": document(), "company": COMPANY, "grantId": GRANT["grantId"],
                      "grantRevision": GRANT["revision"], "candidate": None},
            "mode": "replay",
            "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}}


def payload(request: Submit, candidate: dict | None = None) -> dict:
    data = {"schemaVersion": SCHEMA_VERSION, "document": request.input.document.wire(), "company": request.input.company.wire(),
            "grantRef": {"grantId": request.input.grant_id, "revision": request.input.grant_revision}}
    if candidate is not None:
        data["candidate"] = candidate
    return data


def recording(directory: Path, request: Submit, generated: dict | None, checked: dict | None, *, error: str | None = None) -> ReplayProvider:
    config = stage_config(request.kind, request.mode)
    entries = []
    if error is not None:
        entries.append({"stage": request.kind, "inputDigest": request_identity(request.kind, payload(request), config), "error": error})
    else:
        entries.append({"stage": request.kind, "inputDigest": request_identity(request.kind, payload(request), config),
                        "response": generated})
        entries.append({"stage": "semantic-verification",
                        "inputDigest": request_identity("semantic-verification", payload(request, generated),
                                                        stage_config("semantic-verification", request.mode)),
                        "response": checked})
    file = directory / "recording.json"
    file.write_text(json.dumps({"schemaVersion": SCHEMA_VERSION, "recordingKind": "authored-test", "responses": entries},
                               ensure_ascii=False), encoding="utf-8")
    return ReplayProvider(file)


def render(runner: Runner, job_id: str, kind: str) -> tuple[dict, dict]:
    """The service's own status and result envelope for a job, built with the service's own wire models."""
    view = JobView.model_validate(runner.get(job_id).wire())
    status = JobStatus(
        job_id=view.job_id, kind=kind, mode="replay", input_digest=view.input_digest, state=view.state, phase=view.phase,
        resume_mode=view.resume_mode,
        failure=None if view.failure is None else {"code": view.failure.code, "stage": view.failure.stage},
        artifact_ids=view.artifact_ids, usage=Usage.model_validate(view.usage.model_dump()),
        unreceipted_attempts=unreceipted_attempts(view),
        dispatch=Dispatch(state="idle", command="run", dispatch_count=1, last_outcome="exited", last_runtime_code=None,
                          updated_at=STAMP),
        next=next_action(view.state, view.resume_mode, "idle"), accepted_at=STAMP, observed_at=STAMP)
    envelope = ResultEnvelope(status=status, delivery=Delivery(state="available", reason=None), job=view.wire(),
                              receipts=view.calls)
    return status.wire(), envelope.wire()


def scenario(kind: str, job_id: str, *, decision: str = "supported", advice: bool = False, error: str | None = None,
             cache_job_id: str | None = None) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        directory = Path(folder)
        request = Submit.model_validate(submit_of(job_id, kind))
        generated = None if error else answer(kind)
        checked = None if error else verdict(generated, decision, advice=advice)
        store = Store(directory / "worker")
        store.register_grants([SourceGrant.model_validate({
            "grantId": GRANT["grantId"], "revision": GRANT["revision"], "sourceId": SOURCE_ID, "enabled": True, "rights": "known",
            "allowedOperations": ["read", "store", "model-send", "quote-display"], "recipients": ["authored-replay"],
            "purposes": ["document-summary", "document-sentiment", "semantic-verification"],
            "evidence": ["authored synthetic fixture"], "expiresAt": None})])
        runner = Runner(store, recording(directory, request, generated, checked, error=error))
        runner.submit(request)
        runner.run(job_id)
        status, envelope = render(runner, job_id, kind)
        result = {"submit": request.wire(), "status": status, "envelope": envelope}
        if cache_job_id:
            again = Submit.model_validate(submit_of(cache_job_id, kind))
            runner.submit(again)
            runner.run(cache_job_id)
            cache_status, cache_envelope = render(runner, cache_job_id, kind)
            result["cache"] = {"submit": again.wire(), "status": cache_status, "envelope": cache_envelope}
        return result


def main() -> None:
    scenarios = {
        "summary": scenario("document-summary", "s1-" + "01" * 16, cache_job_id="s1-" + "02" * 16),
        "sentiment": scenario("document-sentiment", "s1-" + "03" * 16),
        "summaryHold": scenario("document-summary", "s1-" + "04" * 16, decision="insufficient"),
        "summaryReject": scenario("document-summary", "s1-" + "05" * 16, advice=True),
        "summaryFailed": scenario("document-summary", "s1-" + "06" * 16, error="provider_http_500"),
    }
    document_wire = copy.deepcopy(document())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "generator": "api/scripts/export_document_analysis_fixtures.py",
        "document": document_wire, "company": COMPANY, "grant": GRANT, "sourceId": SOURCE_ID, "scenarios": scenarios,
    }, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} with {len(scenarios)} scenarios")


if __name__ == "__main__":
    main()
