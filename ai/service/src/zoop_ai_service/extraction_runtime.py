"""The only door to the S2 pipeline: four fixed `zoop-ai-extract` commands (`submit`, `inspect`, `cancel`, `resume`), stdin JSON in, one canonical stdout
JSON out. `run` is never used: a registration and an execution are separate commands with separate authority checks.

The same rules as the S3 door (`relation_runtime.py`, whose gate, exit-code interpreter and generic child runner this reuses): request data reaches
the child only through an anonymous stdin file, argv/environment/working directory are server-owned, stderr is discarded, the child runs in its own
session. Fixtures are the one extra input: a REPLAY `submit` and `resume` name the server-configured producer replay file, and only a replay `resume`
may name the topic file (the pipeline refuses a topic fixture at `submit`, any fixture at `inspect`/`cancel`, and any fixture for a live job).
The environment is the replay-only child environment (no provider key, URL, model setting or live switch) for every replay command and for `inspect`
and `cancel` always. A LIVE job's `submit` child additionally gets the gate and the non-secret model settings, and only its `resume` child (the one that
may send) the budget and both keys (`config.PipelineLive`).
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
        self._live = config.pipeline_live

    @property
    def live_available(self) -> bool:
        """Whether this service process was started with the live group; a live job must never reach `_env` without it."""
        return self._live is not None

    def _env(self, live: bool, *, send: bool) -> dict[str, str] | None:
        """None: the runner's fixed replay-only environment."""
        if not live:
            return None
        assert self._live is not None
        base = self._extraction.child_env
        return self._live.send_env(base) if send else self._live.freeze_env(base)

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

    def submit(self, body: dict[str, Any], *, live: bool = False) -> Outcome:
        """Registration only: the pipeline freezes the approved request (and, for a replay job, the producer fixture hash; for a live job, the runtime
        binding) as a queued job; no call, no candidate."""
        return self._runner.execute(self._argv("submit", replay=not live), body, self._deadlines.quick, interpret=interpret, env=self._env(live, send=False))

    def inspect(self, job_id: str) -> Outcome:
        return self._runner.execute(self._argv("inspect"), reference(job_id), self._deadlines.quick, interpret=interpret)

    def cancel(self, job_id: str) -> Outcome:
        return self._runner.execute(self._argv("cancel"), reference(job_id), self._deadlines.quick, interpret=interpret)

    def resume(self, job_id: str, *, topic: bool, stop: threading.Event | None = None, live: bool = False, initial_only: bool = False) -> Outcome:
        """One execution attempt over the frozen job. The pipeline sends at most one call per stage ref and never resends a started one.
        `initial_only` is its under-lock restriction for the automatic dispatch (`initial_dispatch_taken`, no effect, for a job that already took
        its first dispatch). A live job names no fixture."""
        argv = self._argv("resume", replay=not live, topic=topic and not live)
        if initial_only:
            argv.append("--initial-only")
        return self._runner.execute(argv, reference(job_id), self._deadlines.long, stop, interpret=interpret, env=self._env(live, send=True))
