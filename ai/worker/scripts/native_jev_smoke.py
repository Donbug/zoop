#!/usr/bin/env python3
"""Real-process smoke for S1 native-Jev semantic verification. No real key, endpoint, account or model is involved.

Starts TWO loopback fake providers (an OpenAI-compatible chat endpoint for the generator and a native `systemone` endpoint for the
verifier) and drives the ACTUAL installed `zoop-ai` CLI as a child process with a hand-built environment (nothing of this process's
environment, `.env` or shell is inherited). Per scenario it checks:

  * endpoint isolation: every key reaches only its own server, each server sees only its own path, no `TypeSafe-*` header;
  * the native request: pinned model, no reasoning effort, one POST, one claim Choice per candidate claim plus two Nouls;
  * the recorded model, usage and raw receipt, and that the ceiling of 2 counts both providers;
  * ready (supported), hold (uncertain) and reject (contradicted / advice) outcomes under the provisional thresholds;
  * a malformed or refused response: raw receipt kept, stage fails closed, repeated run/resume/get send nothing more;
  * a missing Jev key refuses the job before the generator is paid.

Run (from the repository root, after `make worker-install`):

    ai/worker/.venv/bin/python ai/worker/scripts/native_jev_smoke.py

Exit 0 only if every check passed.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

WORKER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER / "tests"))

from fake_providers import FakeServer, fixture, jev_body, jev_respond, luna_respond  # noqa: E402
from zoop_ai import native_jev  # noqa: E402
from zoop_ai.contracts import SCHEMA_VERSION, digest  # noqa: E402
from zoop_ai.provider import native_revision  # noqa: E402

CLI = WORKER / ".venv" / "bin" / "zoop-ai"
VERIFY = "semantic-verification"
FAILURES: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + message)
    if not ok:
        FAILURES.append(message)


class Run:
    """One scenario: fresh servers, fresh keys, fresh ledger and grants."""

    def __init__(self, jev_response, root: Path, *, jev_key: bool = True):
        self.luna, self.jev = FakeServer(luna_respond), FakeServer(jev_response)
        self.luna_key, self.jev_key = "smoke-luna-" + secrets.token_hex(8), "smoke-jev-" + secrets.token_hex(8)
        self.state, self.root = root / "ledger", root
        self.grants = root / "grants.json"
        grant = {**fixture("grants")["grants"][0], "recipients": [
            "openai-compatible:" + digest({"endpoint": self.luna.base}), "typesafe-native:" + native_revision(self.jev.base)]}
        self.grants.write_text(json.dumps({"schemaVersion": SCHEMA_VERSION, "grants": [grant]}))
        # Built from nothing: no inherited variable can carry a real key, endpoint, proxy or model.
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                    "ZOOP_AI_LIVE_ENABLED": "1", "ZOOP_AI_GLOBAL_MAX_CALLS": "2",
                    "ZOOP_AI_BASE_URL": self.luna.base, "ZOOP_AI_API_KEY": self.luna_key,
                    "ZOOP_AI_DOCUMENT_SUMMARY_MODEL": "smoke-generator-model", "ZOOP_AI_DOCUMENT_SENTIMENT_MODEL": "smoke-generator-model",
                    "ZOOP_AI_VERIFY_PROVIDER": "typesafe-native", "TYPESAFE_VALIDATION_MODEL": native_jev.MODEL,
                    "TYPESAFE_BASE_URL": self.jev.base}
        if jev_key:
            self.env["TYPESAFE_API_KEY"] = self.jev_key

    def close(self) -> None:
        self.luna.close()
        self.jev.close()

    def job(self, job_id: str) -> dict:
        data = fixture("jobs")["jobs"][0]
        data.update(jobId=job_id, mode="live", provenance={"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"})
        return data

    def cli(self, command: str, data: dict, env: dict | None = None) -> tuple[int, dict]:
        done = subprocess.run([str(CLI), command, "--state-dir", str(self.state), "--grants", str(self.grants)],
                              input=json.dumps(data, ensure_ascii=False), env=env or self.env, capture_output=True, text=True, timeout=60)
        return done.returncode, json.loads(done.stdout)

    def ref(self, job_id: str) -> dict:
        return {"schemaVersion": SCHEMA_VERSION, "jobId": job_id}

    def receipt(self) -> tuple[str, str | None, dict | None]:
        """(call state, error code, raw receipt) of the verification stage, read straight from the worker ledger."""
        db = sqlite3.connect(f"file:{self.state / 'worker.sqlite3'}?mode=ro", uri=True)
        try:
            row = db.execute("SELECT state, error, receipt FROM calls WHERE stage=?", (VERIFY,)).fetchone()
        finally:
            db.close()
        return row[0], row[1], json.loads(row[2]) if row[2] else None

    def counts(self) -> tuple[int, int]:
        return len(self.luna.requests), len(self.jev.requests)


def isolation(run: Run) -> None:
    check([r["path"] for r in run.luna.requests] == ["/v1/chat/completions"], "the chat server saw exactly one /chat/completions request")
    check([r["path"] for r in run.jev.requests] == ["/v1/systemone"], "the native server saw exactly one /systemone request")
    check(all(r["authorization"] == "Bearer " + run.luna_key for r in run.luna.requests), "the chat server received only the chat key")
    check(all(r["authorization"] == "Bearer " + run.jev_key for r in run.jev.requests), "the native server received only the Jev key")
    check(run.jev_key not in json.dumps(run.luna.requests) and run.luna_key not in json.dumps(run.jev.requests),
          "neither key appears anywhere in the other server's traffic")
    check(not [h for r in run.jev.requests for h in r["headers"] if h.startswith("typesafe-")], "no TypeSafe-* (danger-zone/data-sharing) header was sent")
    sent = run.jev.requests[0]["body"] if run.jev.requests else {}
    claims = len(sent.get("state", {}).get("candidate", {}).get("claims", []))
    check(sent.get("model") == native_jev.MODEL and "reasoning_effort" not in sent, "the native request pins the model and carries no reasoning effort")
    check(len(sent.get("questions", {})) == claims + 2 and claims > 0, "one Choice per claim plus the two Nouls, in a single request")


def verdicts(result: dict) -> tuple[str | None, bool | None]:
    artifact = next((a for a in result["artifacts"] if a["kind"] == "document-summary"), None)
    verifier = next((a for a in result["artifacts"] if a["kind"] == VERIFY), None)
    return (verifier["validation"]["semantic"] if verifier else None), (artifact["validation"]["eligible"] if artifact else None)


def outcome(smoke_name: str, root: Path, response, semantic: str, eligible: bool) -> None:
    print(f"== {smoke_name}")
    run = Run(response, root)
    try:
        check(run.cli("submit", run.job("smoke-1"))[0] == 0, "submit accepted under the native verifier configuration")
        code, result = run.cli("run", run.ref("smoke-1"))
        check(code == 0 and result["state"] == "ready", f"job ready (state={result.get('state')})")
        check(verdicts(result) == (semantic, eligible), f"semantic gate = {semantic}, generation eligible = {eligible}")
        check(result["usage"]["providerAttempts"] == 2, "two provider attempts (generator + verifier) were counted")
        isolation(run)
        call = next(c for c in result["calls"] if c["stage"] == VERIFY)
        check(call["config"]["provider"] == "typesafe-native" and call["config"]["model"] == native_jev.MODEL
              and call["config"]["reasoningEffort"] is None, "the receipt records the native provider and the pinned model")
        check(call["usage"] == {"inputTokens": 321, "outputTokens": 17, "cachedTokens": None, "reasoningTokens": None},
              "the receipt records the usage the native server reported")
        state, error, raw = run.receipt()
        check(state == "validated" and error is None and raw is not None and raw["model"] == native_jev.MODEL, "the raw native response is the durable receipt")
        before = run.counts()
        code, again = run.cli("resume", run.ref("smoke-1"), {k: v for k, v in run.env.items() if not k.endswith("_KEY")})
        check(code == 0 and again["artifactIds"] == result["artifactIds"] and run.counts() == before, "resume needs no key and sends nothing")
        check(run.cli("submit", run.job("smoke-2"))[0] == 0, "a second job with the same input can be submitted")
        code, second = run.cli("run", run.ref("smoke-2"))
        if eligible:
            # An eligible result is cached under the frozen configuration (endpoint, model, thresholds): nothing is sent again.
            check(second.get("phase") == "artifact.cache_hit" and second["artifactIds"] == result["artifactIds"] and run.counts() == before,
                  "the same input is a cache hit under the same native identity and sends nothing")
        else:
            # A hold/reject is never cached; the ceiling of 2 was consumed by one chat and one native call, so the retry is refused.
            check(second.get("failure", {}).get("code") == "global_budget_exhausted" and run.counts() == before,
                  "the shared ceiling counts the native call too: the second job is blocked and nothing is sent")
    finally:
        run.close()


def refusal(smoke_name: str, root: Path, response, code_expected: str, *, receipt_kept: bool) -> None:
    print(f"== {smoke_name}")
    run = Run(response, root)
    try:
        check(run.cli("submit", run.job("smoke-1"))[0] == 0, "submit accepted")
        code, result = run.cli("run", run.ref("smoke-1"))
        check(result.get("state") == "failed" and result["failure"]["code"] == code_expected and result["artifacts"] == [],
              f"the stage failed closed with {code_expected} and no artifact")
        state, error, raw = run.receipt()
        check(state == "failed" and error == code_expected, "the call is recorded as failed under the same code")
        check((raw is not None) == receipt_kept, "the raw response is kept as the receipt" if receipt_kept else "no receipt exists for a status the server refused")
        before = run.counts()
        check(before == (1, 1), "one generator request and one native request: no retry")
        for command in ("run", "resume", "get"):
            run.cli(command, run.ref("smoke-1"))
        check(run.counts() == before, "run, resume and get send nothing more")
    finally:
        run.close()


def missing_key(root: Path) -> None:
    print("== missing Jev key")
    run = Run(jev_respond(), root, jev_key=False)
    try:
        check(run.cli("submit", run.job("smoke-1"))[0] == 0, "submit accepted")
        code, refused = run.cli("run", run.ref("smoke-1"))
        check(code == 2 and refused["error"]["code"] == "provider_key_required", "run is refused with provider_key_required")
        check(run.counts() == (0, 0), "the generator was not paid for a job whose verifier could not be sent")
    finally:
        run.close()


def main() -> int:
    if not CLI.exists():
        print(f"installed CLI missing: {CLI} (run `make worker-install`)", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="zoop-native-smoke-") as tmp:
        root = Path(tmp)

        def fresh(name: str) -> Path:
            path = root / name
            path.mkdir()
            return path

        outcome("ready: every claim supported, no finding", fresh("ready"), jev_respond(), "supported", True)
        outcome("hold: uncertain Choice (p below 0.90)", fresh("hold"), jev_respond(choice="supported", p=0.80, confidence=0.70), "hold", False)
        outcome("hold: Noul between 0.10 and 0.90", fresh("hold-noul"), jev_respond(prohibited=0.50), "hold", False)
        outcome("reject: contradicted with high probability and confidence", fresh("reject"), jev_respond(choice="contradicted"), "reject", False)
        outcome("reject: prohibited advice at or above 0.90", fresh("reject-advice"), jev_respond(prohibited=0.95), "reject", False)
        refusal("malformed: another model than the pinned one", fresh("model"),
                lambda request: (200, jev_body(request["body"]["questions"], model="jev-latest")), "native_model_mismatch", receipt_kept=True)
        refusal("malformed: not JSON", fresh("html"), lambda request: (200, b"<html>gateway</html>"), "native_response_invalid", receipt_kept=True)
        refusal("refused: HTTP 500 is definite and never retried", fresh("http500"), lambda request: (500, {"error": "synthetic"}),
                "provider_http_500", receipt_kept=False)
        missing_key(fresh("keyless"))
    print()
    print("native-jev smoke: " + ("PASS" if not FAILURES else f"FAIL ({len(FAILURES)} checks)"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
