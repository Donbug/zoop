"""The only door to the S2 pipeline: four fixed `zoop-ai-extract` commands (`submit`, `inspect`, `cancel`, `resume`), stdin JSON in, one canonical stdout
JSON out. `run` is never used: a registration and an execution are separate commands with separate authority checks.

The same rules as the S3 door (`relation_runtime.py`, whose gate, exit-code interpreter and generic child runner this reuses): request data reaches
the child only through an anonymous stdin file, argv/environment/working directory are server-owned, stderr is discarded, the child runs in its own
session. Fixtures are the one extra input: `submit` and `resume` name the server-configured producer replay file, and only `resume` may name the
topic file (the pipeline refuses a topic fixture at `submit` and any fixture at `inspect`/`cancel`). The environment is the replay-only child
environment: no provider key, URL, model setting or live switch exists in it, and the pipeline has no live path, so no command, an error path
included, can reach a network.
"""
from __future__ import annotations

import threading
from typing import Any

from .config import ServiceConfig
from .relation_runtime import interpreter
from .runtime import Deadlines, Outcome, WorkerProcess

RUNTIME_SCHEMA = "zoop-extraction-s2-2"
interpret = interpreter(RUNTIME_SCHEMA)


def reference(job_id: str) -> dict[str, str]:
    return {"schemaVersion": RUNTIME_SCHEMA, "jobId": job_id}


class ExtractionProcess:
    def __init__(self, config: ServiceConfig, deadlines: Deadlines = Deadlines()):
        assert config.extraction is not None
        self._extraction, self._deadlines = config.extraction, deadlines
        self._runner = WorkerProcess(config, deadlines, env=config.extraction.child_env)

    def _argv(self, command: str, *, replay: bool = False, topic: bool = False) -> list[str]:
        extraction = self._extraction
        argv = [str(extraction.command), command, "--state-dir", str(extraction.state_dir),
                "--ingestion-state-dir", str(extraction.ingestion_state_dir), "--sources", str(extraction.sources_path)]
        if replay:
            argv += ["--replay", str(extraction.producer_replay)]
        if topic:
            assert extraction.topic_replay is not None
            argv += ["--topic-replay", str(extraction.topic_replay)]
        return argv

    def submit(self, body: dict[str, Any]) -> Outcome:
        """Registration only: the pipeline freezes the approved request and the producer fixture hash as a queued job; no call, no candidate."""
        return self._runner.execute(self._argv("submit", replay=True), body, self._deadlines.quick, interpret=interpret)

    def inspect(self, job_id: str) -> Outcome:
        return self._runner.execute(self._argv("inspect"), reference(job_id), self._deadlines.quick, interpret=interpret)

    def cancel(self, job_id: str) -> Outcome:
        return self._runner.execute(self._argv("cancel"), reference(job_id), self._deadlines.quick, interpret=interpret)

    def resume(self, job_id: str, *, topic: bool, stop: threading.Event | None = None) -> Outcome:
        """One execution attempt over the frozen job. The pipeline sends at most one call per stage ref and never resends a started one."""
        return self._runner.execute(self._argv("resume", replay=True, topic=topic), reference(job_id), self._deadlines.long, stop, interpret=interpret)
