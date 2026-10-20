"""Synthetic fake providers shared by the native-Jev tests and `scripts/native_jev_smoke.py`.

An OpenAI-compatible chat endpoint and a native `systemone` endpoint, each recording exactly what reached it (path, headers, JSON
body). Nothing here reads an environment or a real key, and nothing leaves the loopback interface.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from zoop_ai import native_jev

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/contracts/synthetic-document"
# One request record in, (HTTP status, JSON-able payload or raw bytes) out.
Respond = Callable[[dict[str, Any]], tuple[int, Any]]


def fixture(name: str) -> Any:
    return json.loads((FIXTURE / (name + ".json")).read_text(encoding="utf-8"))


def choice_answer(choice: str, p: float = 0.97, confidence: float = 0.93) -> dict[str, Any]:
    rest = round((1 - p) / 2, 6)
    probabilities = dict.fromkeys(native_jev.CHOICES, rest)
    probabilities[choice] = p
    return {"type": "choice", "choice": choice, "probabilities": probabilities, "confidence": confidence}


def jev_body(questions: dict[str, Any], *, choice: str = "supported", p: float = 0.97, confidence: float = 0.93,
             prohibited: float = 0.02, causality: float = 0.03, model: str = native_jev.MODEL) -> dict[str, Any]:
    """A well-formed systemone response to exactly these questions: every claim Choice gets the same distribution."""
    answers: dict[str, Any] = {}
    for key, question in questions.items():
        if question["type"] == "choice":
            answers[key] = choice_answer(choice, p, confidence)
        else:
            answers[key] = {"type": "noul", "noul": prohibited if key == native_jev.PROHIBITED_KEY else causality}
    return {"model": model, "answers": answers, "usage": {"input_tokens": 321, "output_tokens": 17}}


def jev_respond(**answer: Any) -> Respond:
    return lambda request: (200, jev_body(request["body"]["questions"], **answer))


def luna_respond(request: dict[str, Any]) -> tuple[int, Any]:
    """Chat completions for the synthetic summary job: the authored generation, or a supported verdict for a chat verifier."""
    body = request["body"]
    if body["response_format"]["json_schema"]["name"] == "semantic_verification":
        claims = json.loads(body["messages"][1]["content"])["candidate"]["claims"]
        content: Any = {"claims": [{"claimId": c["claimId"], "decision": "supported", "reason": "합성 판정 표본"} for c in claims],
                        "prohibitedAdvice": False, "unsupportedCausality": False}
    else:
        content = fixture("replay")["responses"][0]["response"]
    return 200, {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
                 "usage": {"prompt_tokens": 21, "completion_tokens": 13}}


class FakeServer:
    """A loopback HTTP server. `requests` records what reached it; `base` is the `/v1` base URL a provider is pointed at."""

    def __init__(self, respond: Respond):
        self.requests: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                request = {"path": self.path, "authorization": self.headers.get("Authorization"),
                           "headers": {k.lower(): v for k, v in self.headers.items()}, "body": json.loads(raw)}
                outer.requests.append(request)
                status, payload = respond(request)
                data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
