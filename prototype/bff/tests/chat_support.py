"""Helpers for tests that ask the AI chat (members only; answers come from a background job)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi.testclient import TestClient

from .conftest import ALPHA_ISSUES

TERMINAL = ("completed", "failed", "cancelled")
SIGNUP = {"password": "zoop-pass-1", "agreements": ["service", "privacy"]}


def new_member(app_client: TestClient, email: str | None = None, name: str = "질문자") -> TestClient:
    """A signed-up member with its own cookie jar over the same app."""
    client = TestClient(app_client.app)
    email = email or f"asker-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/auth/signup", json={**SIGNUP, "email": email, "displayName": name})
    assert response.status_code == 201, response.text
    return client


def new_id(prefix: str = "chat") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def open_conversation(client: TestClient) -> str:
    session_id = new_id("chat")
    response = client.put(f"/api/chat/sessions/{session_id}")
    assert response.status_code == 201, response.text
    return session_id


def job_body(question: str, contexts: list[str] | None = None, *, job_id: str | None = None, **context: Any) -> dict[str, Any]:
    return {"jobId": job_id or new_id("job"), "question": question, "context": {"contextIds": contexts or [], **context}}


def wait_for(client: TestClient, job_id: str, *, until=lambda job: job["status"] in TERMINAL, timeout: float = 10.0) -> dict[str, Any]:
    """Poll the job status the way the panel does until ``until`` holds."""
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/api/chat/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if until(job):
            return job
        assert time.monotonic() < deadline, f"job did not settle: {job['status']}"
        time.sleep(0.02)


def ask_job(client: TestClient, question: str, contexts: list[str] | None = None, *, session_id: str | None = None, **context: Any) -> dict[str, Any]:
    """Ask in a (new) conversation and return the settled job."""
    session_id = session_id or open_conversation(client)
    body = job_body(question, contexts, **context)
    response = client.post(f"/api/chat/sessions/{session_id}/jobs", json=body)
    assert response.status_code == 202, response.text
    return wait_for(client, body["jobId"])


def ask(client: TestClient, question: str, contexts: list[str] | None = None, **context: Any) -> dict[str, Any]:
    """The saved result of a completed job, plus its ``sessionId`` and ``jobId``."""
    job = ask_job(client, question, contexts if contexts is not None else [ALPHA_ISSUES["q1"]], **context)
    assert job["status"] == "completed", job
    return {**job["result"], "sessionId": job["sessionId"], "jobId": job["id"]}
