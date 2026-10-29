"""One credential-free installed ingestion export, always requiring store rights."""
from __future__ import annotations

import json

from .config import ServiceConfig
from .handoff_runtime import _duplicate_free, _no_constant, canonical
from .observation_wire import SCHEMA, ObservationExportRequest
from .runtime import CODE, Deadlines, Outcome, WorkerProcess


def interpret(code: int, raw: bytes) -> Outcome:
    if code not in (0, 2):
        return Outcome("abnormal", exit_code=code)
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
        if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA or canonical(value) + "\n" != text:
            return Outcome("contract", exit_code=code)
    except (UnicodeError, ValueError, RecursionError):
        return Outcome("contract", exit_code=code)
    if code == 2:
        error = value.get("error")
        name = error.get("code") if isinstance(error, dict) else None
        if set(value) != {"schemaVersion", "error"} or not isinstance(error, dict) or set(error) != {"code"} or not isinstance(name, str) or not CODE.fullmatch(name):
            return Outcome("contract", exit_code=code)
        return Outcome("error", code=name, exit_code=code)
    return Outcome("result", result=value, exit_code=code)


class ObservationProcess:
    def __init__(self, config: ServiceConfig, deadlines: Deadlines = Deadlines()):
        assert config.observation is not None
        self._observation, self._deadlines = config.observation, deadlines
        self._runner = WorkerProcess(config, deadlines, env=self._observation.child_env)

    def export(self, request: ObservationExportRequest) -> Outcome:
        cfg = self._observation
        return self._runner.execute([str(cfg.command), "export", "--state-dir", str(cfg.ingestion_state_dir),
                                     "--sources", str(cfg.sources_path), "--require-store"],
                                    request.wire(), self._deadlines.read, interpret=interpret)
