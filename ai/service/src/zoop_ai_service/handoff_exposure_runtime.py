"""One credential-free exposure CLI invocation; no ordinary export, retry or persistent state."""
from __future__ import annotations

import json

from .config import ServiceConfig
from .handoff_exposure_wire import MAX_OUTPUT, SCHEMA, ExposureQuery
from .handoff_runtime import _duplicate_free, _no_constant, canonical
from .runtime import CODE, Deadlines, Outcome, WorkerProcess


def interpret(code: int, raw: bytes) -> Outcome:
    if code not in (0, 2):
        return Outcome("abnormal", exit_code=code)
    if len(raw) > MAX_OUTPUT:
        return Outcome("contract", exit_code=code)
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
        if canonical(value) + "\n" != text or not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA:
            return Outcome("contract", exit_code=code)
    except (UnicodeError, ValueError, RecursionError):
        return Outcome("contract", exit_code=code)
    if code == 2:
        error = value.get("error")
        name = error.get("code") if isinstance(error, dict) else None
        if set(value) != {"schemaVersion", "error"} or not isinstance(name, str) or not CODE.fullmatch(name):
            return Outcome("contract", exit_code=code)
        # No raw error detail survives the process boundary.
        return Outcome("error", code=name, exit_code=code)
    return Outcome("result", result=value, exit_code=code)


class HandoffExposureProcess:
    def __init__(self, config: ServiceConfig, deadlines: Deadlines = Deadlines()):
        assert config.handoff_exposure is not None
        self._exposure, self._deadlines = config.handoff_exposure, deadlines
        self._runner = WorkerProcess(config, deadlines, env=self._exposure.child_env)

    def query(self, query: ExposureQuery) -> Outcome:
        cfg = self._exposure
        argv = [str(cfg.command), "--state-dir", str(cfg.state_dir)]
        if query.changed.kind != "s3-relation":
            if cfg.source_contexts:
                argv += ["--source-contexts", str(cfg.source_contexts), "--source-contexts-sha256", cfg.source_contexts_sha256]
            else:
                argv += ["--ingestion-state-dir", str(cfg.ingestion_state_dir), "--extraction-state-dir", str(cfg.extraction_state_dir)]
        return self._runner.execute(argv, query.wire(), self._deadlines.handoff, interpret=interpret)
