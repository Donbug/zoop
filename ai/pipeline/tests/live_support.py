"""Synthetic payloads, provider replies and environment for the offline live-runtime tests. No key, endpoint or text is real."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from zoop_ai_pipeline import live_runtime as live
from zoop_ai_pipeline.extraction_contracts import Article

OPENAI_KEY = "sk-test-SECRET-openai-0001"
JEV_KEY = "tsk-test-SECRET-jev-0002"
SECRETS = (OPENAI_KEY, JEV_KEY)
DOC_TEXT = "가상공급은 2026년 가상고객에 반도체를 공급한다. 가상고객은 이를 확인했다."
VERSION_A = "a" * 64


def environment(monkeypatch, tmp_path: Path, **override: str | None) -> None:
    values: dict[str, str | None] = {
        live.GATE: "1", live.MODEL_VAR: "gpt-6-luna", live.EFFORT_VAR: "high", live.JEV_MODEL_VAR: "jev-1.14.0",
        live.BUDGET_DIR_VAR: str(tmp_path / "budget"), live.MAX_USD_VAR: "1", live.MAX_CALLS_VAR: "10",
        live.OPENAI_KEY_VAR: OPENAI_KEY, live.JEV_KEY_VAR: JEV_KEY,
        live.OPENAI_URL_VAR: None, live.JEV_URL_VAR: None, live.MAX_OUTPUT_VAR: None, live.TIMEOUT_VAR: None}
    values.update(override)
    for name, value in values.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def article(body: str = DOC_TEXT) -> Article:
    return Article(article_id="doc-1", url="https://private.example.invalid/secret-path?token=1", title="가상 제목", body=body,
                   publisher="PRIVATE-PUBLISHER", published_at="2026-10-01", language="ko", input_kind="body", origin_id="ORIGIN-X",
                   withdrawn=False, allow_model_send=False, synthetic=True)


def extract_payload() -> dict[str, Any]:
    a = article()
    return {"article": a.model_dump(mode="json"), "article_version": a.version, "prompt_version": "legacy",
            "companies": [{"company_id": "SYNTH-1", "name": "가상고객", "aliases": [], "ticker": None}]}


def relation_payload() -> dict[str, Any]:
    return {"schemaVersion": "zoop-relation-request-1", "stage": "relation", "producerVersion": "zoop-relation-producer-1",
            "vocabulary": {"SUPPLIES": {"subject": "company", "object": "company", "direction": "directed"}},
            "upstream": {"jobId": "JOB-SECRET", "inputDigest": "b" * 64},
            "catalogue": [{"companyId": "SYNTH-1", "names": ["가상고객"]}, {"companyId": "SYNTH-3", "names": ["가상공급"]}],
            "events": [], "topics": [],
            "documents": [{"documentId": "doc-1", "documentVersion": VERSION_A, "title": "가상 제목", "text": DOC_TEXT}]}


def endpoint(kind: str, ref: str, name: str) -> dict[str, Any]:
    return {"kind": kind, "ref": ref, "names": [name]}


def facts() -> dict[str, Any]:
    return {"type": "SUPPLIES", "direction": "directed", "subject": endpoint("company", "SYNTH-3", "가상공급"),
            "object": endpoint("company", "SYNTH-1", "가상고객"), "connection": "direct", "businessScope": None, "productScope": "반도체",
            "validity": {"from": None, "until": None}, "countries": [], "path": []}


def quote(quote_id: str, text: str = "가상공급은 2026년 가상고객에 반도체를 공급한다.") -> dict[str, Any]:
    return {"quoteId": quote_id, "documentId": "doc-1", "documentVersion": VERSION_A, "start": 0, "end": len(text), "text": text}


def verify_relation_payload() -> dict[str, Any]:
    return {"schemaVersion": "zoop-relation-verify-request-1", "stage": "verify-relation", "verifierVersion": "zoop-relation-verifier-1",
            "policyVersion": "zoop-relation-policy-1", "attempt": {"kind": "initial", "seq": 0, "policyVersion": "p", "priorVerdictDigest": None},
            "relation": facts(), "quotes": [quote("ev-b"), quote("ev-a", "가상고객은 이를 확인했다.")],
            "claims": [{"claimId": "subject", "quoteIds": ["ev-a", "ev-b"]}, {"claimId": "object", "quoteIds": ["ev-a", "ev-b"]},
                       {"claimId": "type", "quoteIds": ["ev-b"]}, {"claimId": "direction", "quoteIds": ["ev-b"]},
                       {"claimId": "scope", "quoteIds": ["ev-a", "ev-b"]}]}


def verify_impact_payload() -> dict[str, Any]:
    return {"schemaVersion": "zoop-impact-verify-request-1", "stage": "verify-impact", "verifierVersion": "zoop-impact-verifier-1",
            "policyVersion": "zoop-impact-policy-1", "attempt": {"kind": "initial", "seq": 0}, "relation": facts(),
            "target": endpoint("company", "SYNTH-1", "가상고객"), "quotes": [quote("ev-a", "가상고객은 이를 확인했다."), quote("ev-b")]}


def choice(winner: str, options: list[str] | tuple[str, ...], p: float = 0.97, confidence: float = 0.95) -> dict[str, Any]:
    rest = (1 - p) / (len(options) - 1)
    return {"type": "choice", "choice": winner, "probabilities": {o: (p if o == winner else rest) for o in options}, "confidence": confidence}


def jev_reply(prepared: dict, winners: dict[str, str] | None = None, *, model: str = "jev-1.14.0", p: float = 0.97, confidence: float = 0.95) -> dict:
    """A well-formed Jev reply for a prepared request: every question answered with its default winner unless overridden."""
    answers = {}
    for key, question in prepared["body"]["questions"].items():
        options = list(question["criteria"])
        default = "supported" if "supported" in options else "positive"
        answers[key] = choice((winners or {}).get(key, default), options, p, confidence)
    return {"model": model, "answers": answers, "usage": {"input_tokens": 1000, "output_tokens": 0}}


def openai_reply(content: Any, *, finish: str = "stop", usage: dict | None = ..., model: str = "gpt-6-luna-2026-10-01", refusal: str | None = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)}
    if refusal:
        message["refusal"] = refusal
    reply: dict[str, Any] = {"id": "chatcmpl-test", "model": model, "choices": [{"index": 0, "finish_reason": finish, "message": message}]}
    if usage is ...:
        usage = {"prompt_tokens": 1000, "completion_tokens": 500, "prompt_tokens_details": {"cached_tokens": 0},
                 "completion_tokens_details": {"reasoning_tokens": 300}}
    if usage is not None:
        reply["usage"] = usage
    return reply


class Fake:
    """In-process provider: records every request it receives and answers with `handler(request) -> httpx.Response | Exception`."""

    def __init__(self, handler):
        self.handler, self.requests = handler, []
        self.transport = httpx.MockTransport(self.respond)

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.handler(request)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def no_authorization() -> None:
    return None


def compare_payload() -> dict[str, Any]:
    first, second = article("본문 하나"), article("본문 둘")
    return {"mention": {"mention_id": "m1"}, "issue": {"issue_id": "evc-1", "mentions": [], "articles": [first.model_dump(mode="json")]},
            "article": second.model_dump(mode="json")}


def topic_payload() -> dict[str, Any]:
    return {"schemaVersion": "zoop-topic-request-1", "producerVersion": "zoop-topic-replay-producer-1", "events": [], "documents": []}


def impact_payload() -> dict[str, Any]:
    return {"schemaVersion": "zoop-impact-request-1", "stage": "impact", "producerVersion": "zoop-impact-producer-1",
            "policyVersion": "zoop-impact-policy-1", "relation": facts(), "relationQuotes": [quote("ev-a")],
            "companies": [endpoint("company", "SYNTH-1", "가상고객")],
            "documents": [{"documentId": "doc-1", "documentVersion": VERSION_A, "title": "가상 제목", "text": DOC_TEXT}]}


PAYLOADS = {"extract": extract_payload, "compare": compare_payload, "topic": topic_payload, "relation": relation_payload,
            "impact": impact_payload, "verify-relation": verify_relation_payload, "verify-impact": verify_impact_payload}
