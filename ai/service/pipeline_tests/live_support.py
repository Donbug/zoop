"""Harness for the LIVE service tests: a real uvicorn service, the real installed `zoop-ai-extract` / `zoop-ai-relation` running their live path, and the
pipeline's offline provider simulator (a deterministic loopback server for the OpenAI chat wire) hosted by a long-lived `build_live_world.py` process.

Nothing here imports `zoop_ai_pipeline`; the pipeline's interpreter runs the world builder, and the commands the service starts are the installed ones.
No external host is contacted and every key is a fake of the simulator.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from extraction_support import EXTRACT_CLI, ExtractionService, ExtractionWorkspace, digest
from relation_support import PIPELINE, PIPELINE_PYTHON, canonical

BUILD_LIVE_WORLD = Path(__file__).resolve().parent / "build_live_world.py"
PIPELINE_LIVE_SWITCH = "ZOOP_AI_SERVICE_PIPELINE_LIVE"


class LiveWorldProcess:
    """The live operator world plus the provider simulator, living in one subprocess of the pipeline's interpreter."""

    def __init__(self, root: Path):
        assert PIPELINE_PYTHON.is_file() and EXTRACT_CLI.is_file(), "run `make pipeline-install` before service-pipeline-test"
        root.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen([str(PIPELINE_PYTHON), str(BUILD_LIVE_WORLD), str(PIPELINE), str(root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        text=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
                                                        "PYTHONDONTWRITEBYTECODE": "1"})
        first = self.process.stdout.readline()  # type: ignore[union-attr]
        assert first, "the live world builder died before it printed its world"
        self.info: dict[str, Any] = json.loads(first)
        self.root = root
        self.identity: str = self.info["identity"]
        self.env: dict[str, str] = self.info["env"]
        self.requests: dict[str, dict[str, Any]] = self.info["requests"]
        self.source_texts: list[str] = self.info["sourceTexts"]

    def _ask(self, line: str) -> dict[str, Any]:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def seen(self) -> dict[str, Any]:
        """Every request the simulated provider has received so far."""
        return self._ask("count")

    def mode(self, name: str) -> None:
        assert self._ask(f"mode {name}") == {"mode": name}

    def jev(self, name: str) -> None:
        """The native (Jev) provider's behaviour: ok | hold | silent."""
        assert self._ask(f"jev {name}") == {"jev": name}

    def close(self) -> None:
        if self.process.poll() is None:
            assert self.process.stdin is not None
            self.process.stdin.close()
            try:
                self.process.wait(30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


class LiveWorkspace(ExtractionWorkspace):
    """One service's fresh state over the LIVE world: the S2 group's approval file carries LIVE approvals (pinned runtime identity, no fixture), the child
    command is the real installed CLI with NO network audit (a live child must reach the loopback simulator), and the service's live group is switched on with
    the world's fake keys and budget."""

    def __init__(self, root: Path, live: LiveWorldProcess, *, chain: bool = False):
        root.mkdir(parents=True, exist_ok=True)
        stubs = root / "operator-stubs"
        stubs.mkdir()
        for name in ("producer.json", "verifier.json", "s2-replay.json", "s2-topic.json"):
            (stubs / name).write_text("{}")
        (stubs / "extraction").mkdir()
        world = SimpleNamespace(registry=Path(live.info["registry"]), producer=stubs / "producer.json", verifier=stubs / "verifier.json",
                                upstream={"jobId": "none", "inputDigest": "0" * 64}, extraction=stubs / "extraction", ingestion=Path(live.info["ingestion"]),
                                s2_replay=stubs / "s2-replay.json", s2_topic=stubs / "s2-topic.json", s2_request={}, s2_plain_request={},
                                source_texts=live.source_texts)
        super().__init__(root / "ws", world, chain=chain, topic=False, requests=())  # type: ignore[arg-type]
        self.live = live
        self.s2_command = EXTRACT_CLI  # the real command, not the network-auditing stand-in
        self.requests = dict(live.requests)
        self.write_live_approvals({"alpha": list(live.requests)})

    def live_entry(self, principal: str, job_id: str, *, identity: str | None = None) -> dict[str, Any]:
        request = self.requests[job_id]
        return {"principal": principal, "jobId": job_id, "approvedRequestDigest": digest(request), "request": request, "producerReplayDigest": None,
                "topicReplayDigest": None, "liveRuntimeIdentity": identity or self.live.identity}

    def write_live_approvals(self, listed: dict[str, list[str]], *, identity: str | None = None) -> None:
        self.listed = listed
        self.write_entries([self.live_entry(principal, job_id, identity=identity) for principal, jobs in listed.items() for job_id in jobs])

    def write_live_upstreams(self, entries: list[tuple[str, str, str, str | None]]) -> None:
        """The S3 upstream allowlist: (principal, S2 job id, its inputDigest, the live runtime identity this pair may run under or None for replay only)."""
        self.upstreams.write_text(json.dumps({"schemaVersion": "zoop-ai-relation-upstreams-1", "upstreams": [
            {"principal": principal, "jobId": job_id, "inputDigest": input_digest, **({} if identity is None else {"liveRuntimeIdentity": identity})}
            for principal, job_id, input_digest, identity in entries]}))

    def env(self, **overrides: str | None) -> dict[str, str]:
        values = super().env()
        values.update({PIPELINE_LIVE_SWITCH: "1", **self.live.env})
        for key, value in overrides.items():
            if value is None:
                values.pop(key, None)
            else:
                values[key] = value
        return values

    def private_strings(self) -> list[str]:
        return [*super().private_strings(), *(self.live.env[name] for name in ("ZOOP_AI_API_KEY", "TYPESAFE_API_KEY"))]

    def write_wrapper(self, hooks: str = "", command: str = "resume") -> Path:  # type: ignore[override]
        script = super().write_wrapper(hooks, command)
        self.s2_command = EXTRACT_CLI
        return script


def live_service(workspace: LiveWorkspace, *, hold: bool = False, **kwargs: Any) -> ExtractionService:
    """A started service over the live workspace. `hold` keeps accepted S3 jobs queued (the S2 dispatcher is never held)."""
    launcher_env = {"ZOOP_TEST_RELATION_HOLD_FILE": str(workspace.root / "go")} if hold else {}
    return ExtractionService(workspace, env=workspace.env(), launcher=bool(launcher_env), launcher_env=launcher_env, **kwargs).start()


__all__ = ["LiveWorkspace", "LiveWorldProcess", "canonical", "live_service"]
