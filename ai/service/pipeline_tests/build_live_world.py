#!/usr/bin/env python3
"""A LIVE operator world for the service tests, served by the pipeline's own interpreter. Run with the interpreter of `ai/pipeline/.venv`, never the service's.

It builds, with the actual pipeline code, the world the pipeline's own loopback smoke uses (`scripts.extraction_smoke.LiveWorld`): two synthetic documents
ingested by the real `zoop-ai-ingest`, a frozen snapshot event, and exactly the model-send grant the live runtime asks for (for the S2 AND the S3 stages). It
then hosts TWO OFFLINE loopback providers and stays alive as their host. Neither is an AI and neither is a stand-in for one: each answers with a reply grounded
in the exact projection the real `LiveRuntime` sent (the same technique as the pipeline's own simulator), so the real request building, budget, receipt,
decode, parse and exact-grounding code all run.

  * the pipeline's `SimulatedProvider` on the OpenAI chat wire (`/v1/chat/completions`): the S2 stages as the pipeline's own simulator answers them, plus the S3
    `relation` stage (one SUPPLIES relation, every citation an exact quote of a sent document) and the S3 `impact` stage (no impact);
  * `JevProvider` on the native TypeSafe wire (`POST /v1/systemone`): one Choice per question. `mode ok` answers every claim with its supporting option;
    `mode hold` answers every claim `insufficient` (a VALID verifier judgment: the relation is held for a human); `mode silent` closes without a reply.

No external host is ever contacted and every key is a fake.

Protocol (stdin/stdout, one JSON document per line):
  first line out     the world: roots, registry, the live environment (fake keys), the runtime identity, the authored live S2 requests, both provider URLs
  `count`            -> every request each provider saw, in order (`paths`, `authorizations`, and for the chat provider the stage of each request)
  `mode <name>`      -> chat provider: ok | garbage | http500 | silent
  `jev <name>`       -> native provider: ok | hold | silent
  EOF                the providers stop and the process exits

usage: build_live_world.py <pipeline project dir> <empty output dir>
"""
from __future__ import annotations

import http.server
import json
import sys
import threading
from pathlib import Path

PIPELINE = Path(sys.argv[1]).resolve()
ROOT = Path(sys.argv[2]).resolve()
sys.path[:0] = [str(PIPELINE)]

from scripts import extraction_smoke as smoke  # noqa: E402
from scripts.extraction_smoke import LiveWorld, SimulatedProvider, simulator_env  # noqa: E402

JOBS = ("live-svc-1", "live-svc-2", "live-svc-3")
STAGES = ("extract", "compare", "topic", "relation", "verify-relation", "impact", "verify-impact")
_pipeline_answer = smoke.simulated_answer


def relation_answer(projection: dict, sources: list[dict]) -> dict:
    """One directed company relation between the first two catalogue companies, citing the first citable segment of up to two sent sources.
    The pipeline expands each reference to the exact native source quote."""
    companies = [company["companyId"] for company in projection["catalogue"]][:2]
    relation_type = "SUPPLIES" if "SUPPLIES" in projection["vocabulary"] else next(iter(projection["vocabulary"]))
    citations = [smoke.first_reference(source) for source in sources[:2]]
    return {"schemaVersion": "zoop-relation-response-1", "producerVersion": projection["producerVersion"], "relations": [{
        "type": relation_type, "subject": {"kind": "company", "ref": companies[0]}, "object": {"kind": "company", "ref": companies[1]},
        "connection": "direct", "businessScope": None, "productScope": None, "validity": {"from": None, "until": None, "citations": []},
        "countries": [], "reason": "simulated: the cited sentences state the relationship", "citations": citations, "path": []}]}


def simulated_answer(stage: str, projection: dict, sources: list[dict]) -> dict:
    if stage == "relation":
        return relation_answer(projection, sources)
    if stage == "impact":
        # "Return no impact for a company the text does not decide": an empty list is a valid reply and asks for no impact verifier call.
        return {"schemaVersion": "zoop-impact-response-1", "producerVersion": projection["producerVersion"], "impacts": []}
    return _pipeline_answer(stage, projection, sources)


smoke.simulated_answer = simulated_answer  # the pipeline simulator's handler resolves this name at call time


def choice(winner: str, options: list[str]) -> dict:
    rest = (1 - 0.97) / (len(options) - 1)
    return {"type": "choice", "choice": winner, "probabilities": {o: (0.97 if o == winner else rest) for o in options}, "confidence": 0.95}


class JevProvider:
    """Loopback server for the native TypeSafe Jev wire (`POST /v1/systemone`). `requests` records every request that reached it, in order."""

    def __init__(self):
        self.mode, self.requests = "ok", []
        provider = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                provider.requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), "body": body})
                if provider.mode == "silent":
                    self.close_connection = True
                    return
                answers = {}
                for key, question in body["questions"].items():
                    options = list(question["criteria"])
                    if provider.mode == "hold":
                        winner = "insufficient" if "insufficient" in options else options[-1]
                    else:
                        winner = "supported" if "supported" in options else "positive" if "positive" in options else options[0]
                    answers[key] = choice(winner, options)
                data = json.dumps({"model": body["model"], "answers": answers, "usage": {"input_tokens": 1000, "output_tokens": 0}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self) -> "JevProvider":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def stage_of(body: dict) -> str:
    return json.loads(body["messages"][1]["content"])["stage"]


def main() -> None:
    with SimulatedProvider() as provider, JevProvider() as jev:
        env = simulator_env(provider.base_url, ROOT / "budget", TYPESAFE_BASE_URL=jev.base_url, ZOOP_AI_PIPELINE_LIVE_MAX_USD="50",
                            ZOOP_AI_PIPELINE_LIVE_MAX_CALLS="200")
        world = LiveWorld(ROOT / "world", env)
        world.kit.allow_model_send(world.runtime, stages=STAGES)  # the S3 stages need their own purposes and the Jev recipient too
        info = {"root": str(ROOT), "ingestion": str(world.kit.root / "ingestion"), "registry": str(world.kit.registry_path), "baseUrl": provider.base_url,
                "jevUrl": jev.base_url, "env": env, "identity": world.identity, "requests": {job: world.request(job) for job in JOBS},
                "sourceTexts": [text for text in world.documents().values()]}
        print(json.dumps(info, ensure_ascii=False), flush=True)
        for line in sys.stdin:
            command = line.split()
            if command[:1] == ["count"]:
                seen, native = list(provider.requests), list(jev.requests)
                print(json.dumps({"count": len(seen), "authorizations": [r["authorization"] for r in seen], "paths": [r["path"] for r in seen],
                                  "stages": [stage_of(r["body"]) for r in seen],
                                  "allowModelSend": any("allow_model_send" in json.dumps(r["body"]) for r in seen),
                                  "jev": {"count": len(native), "authorizations": [r["authorization"] for r in native], "paths": [r["path"] for r in native],
                                          "questions": [len(r["body"]["questions"]) for r in native]}}), flush=True)
            elif command[:1] == ["mode"] and len(command) == 2:
                provider.mode = command[1]
                print(json.dumps({"mode": provider.mode}), flush=True)
            elif command[:1] == ["jev"] and len(command) == 2:
                jev.mode = command[1]
                print(json.dumps({"jev": jev.mode}), flush=True)
            else:
                print(json.dumps({"error": "unknown command"}), flush=True)


if __name__ == "__main__":
    main()
