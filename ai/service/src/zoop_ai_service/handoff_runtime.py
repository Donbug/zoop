"""The only door to the AI handoff: one fixed `zoop-ai-handoff export` command, stdin JSON in, one canonical stdout JSON out.

The same rules as the other doors (`runtime.py`, whose generic child runner this reuses): request data reaches the child only through an anonymous stdin
file, argv/environment/working directory are server-owned, stderr is discarded, the child runs in its own session. Differences that matter:

  * only `export` exists here. There is no `freeze`, `recover` or `inspect`: the service can neither create nor settle a handoff, and `inspect` would
    report the stored state without proving the current authority, which is never what this door delivers;
  * the argv carries server-owned paths only: the handoff ledger, the S3/S2/ingestion roots, the source registry and the three operator files the
    manifest pinned. The stdin holds exactly `{schemaVersion, handoffId}`;
  * the environment is the plain ownership environment: no graph credential, provider key, token digest or model setting. The handoff makes no network
    or model call and opens the source ledgers read-only;
  * the pipeline exits 2 BOTH for an error object and for a complete result whose delivery is withheld, so a withheld result is a `result` outcome and only
    an object with an `error` key is an `error` outcome. A `handoff_not_ready` error keeps its parsed object (`Outcome.result`) because it carries the state;
  * the answer must already be the producer's canonical JSON line (sorted keys, compact separators, no duplicate key, no NaN/Infinity): the bundle hash is
    over canonical bytes, so a stdout that is not byte-identical to its own canonical re-serialisation is refused instead of relayed.
"""
from __future__ import annotations

import json
from typing import Any

from .config import ServiceConfig
from .runtime import CODE, Deadlines, Outcome, WorkerProcess

RUNTIME_SCHEMA = "zoop-ai-handoff-1"


def canonical(value: Any) -> str:
    """The producer's canonical form (`ingestion_contracts.canonical`): the bytes whose SHA-256 is the bundle digest."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _duplicate_free(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(_: str) -> Any:
    raise ValueError("non-finite number")


def interpret(code: int, raw: bytes) -> Outcome:
    if code not in (0, 2):
        return Outcome("abnormal", exit_code=code)
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
        if canonical(value) != text.removesuffix("\n"):
            return Outcome("abnormal", exit_code=code)     # not the producer's canonical line: its bundle bytes cannot be proven
    except (UnicodeDecodeError, ValueError, RecursionError):
        return Outcome("abnormal", exit_code=code)
    if not isinstance(value, dict) or value.get("schemaVersion") != RUNTIME_SCHEMA:
        return Outcome("abnormal", exit_code=code)
    if "error" in value:
        error = value["error"]
        name = error.get("code") if isinstance(error, dict) else None
        if code != 2 or not isinstance(name, str) or not CODE.fullmatch(name):
            return Outcome("abnormal", exit_code=code)
        return Outcome("error", result=value, code=name, exit_code=2)
    delivery = value.get("delivery")
    status = delivery.get("status") if isinstance(delivery, dict) else None
    if not isinstance(value.get("handoffId"), str) or status != ("current" if code == 0 else "withheld"):
        return Outcome("abnormal", exit_code=code)
    return Outcome("result", result=value, exit_code=code)


class HandoffProcess:
    def __init__(self, config: ServiceConfig, deadlines: Deadlines = Deadlines()):
        assert config.handoff is not None
        self._handoff, self._deadlines = config.handoff, deadlines
        self._runner = WorkerProcess(config, deadlines, env=config.handoff.child_env)

    def _argv(self) -> list[str]:
        handoff = self._handoff
        return [str(handoff.command), "export", "--state-dir", str(handoff.state_dir), "--relation-state-dir", str(handoff.relation_state_dir),
                "--extraction-state-dir", str(handoff.extraction_state_dir), "--ingestion-state-dir", str(handoff.ingestion_state_dir),
                "--sources", str(handoff.sources_path), "--canonical", str(handoff.canonical_path), "--decisions", str(handoff.decisions_path),
                "--bindings", str(handoff.bindings_path)]

    def export(self, handoff_id: str) -> Outcome:
        """One child, one attempt, never retried: the full gate chain over one handoff. The service keeps the pins, the digests and, for the bundle route,
        the parsed bundle of exactly this answer."""
        return self._runner.execute(self._argv(), {"schemaVersion": RUNTIME_SCHEMA, "handoffId": handoff_id}, self._deadlines.handoff, interpret=interpret)
