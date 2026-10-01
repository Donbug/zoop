"""Stand-ins for the systems outside the BFF: PoC ledger, Neo4j, the sandbox and the CLI child process."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

from zoop_bff.admin_jobs import LaunchSpec
from zoop_bff.admin_ledger import LedgerUnavailable

SECRET = "sk-test-secret-value-0123456789"
POLICY = "zoop-test-relaxed-1:0123456789abcdef"


class FakeLedger:
    database = "fake_ledger"

    def __init__(self, payload: dict[str, Any], policy: str = POLICY):
        self.payload = payload
        self.policy_version = policy
        self.pending = 0
        self.down = False
        self.runs: list[dict[str, Any]] = []

    def _check(self) -> None:
        if self.down:
            raise LedgerUnavailable("PoC 원장(PostgreSQL)에 연결할 수 없습니다.")

    def inspect(self) -> dict[str, Any]:
        self._check()
        return copy.deepcopy(self.payload)

    def policy(self) -> dict[str, Any]:
        self._check()
        return {
            "version": self.policy_version,
            "metadata": {
                "web": None,
                "validation_model": "jev-test",
                "decision_policy": {"support_min": 0.65, "contradiction_max": 0.1, "reject_min": 0.9},
            },
        }

    def projection(self) -> dict[str, Any]:
        self._check()
        return {
            "pending": self.pending,
            "oldest_pending_at": "2026-09-01T00:00:00+00:00" if self.pending else None,
            "last_completed_at": "2026-08-31T00:00:00+00:00",
            "total": 3,
        }

    def run_reports(self) -> list[dict[str, Any]]:
        self._check()
        return copy.deepcopy(self.runs)


class FakeNeo4j:
    def __init__(self, ledger: FakeLedger):
        self._ledger = ledger
        self.down = False
        self.extra: dict[str, set[str]] = {}
        self.drop: set[str] = set()

    def projected(self) -> dict[str, set[str]]:
        if self.down:
            raise ConnectionError("neo4j down")
        view = {
            i["issue_id"]: {r["relation_id"] for r in i.get("relations") or []}
            for i in self._ledger.payload["issues"]
            if i["issue_id"] not in self.drop
        }
        for issue_id, relations in self.extra.items():  # extra issues, or extra relations on a ledger issue
            view[issue_id] = view.get(issue_id, set()) | relations
        return view


class FakeSandbox:
    def __init__(self, root: Path):
        self.path = root / "sandbox"
        self.path.mkdir(parents=True, exist_ok=True)
        self.poc = self.path / "poc"
        self.settings_file = self.path / "zoop-real-relaxed-settings.json"
        self.settings_file.write_text(json.dumps({"policy_version": "zoop-test-relaxed-1", "max_calls": 200}))
        self.expected = POLICY
        self.problem_list: list[str] = []
        self.datasets_dir = self.path / "zoop-expansion" / "datasets"
        self.datasets_dir.mkdir(parents=True, exist_ok=True)

    def datasets(self) -> list[str]:
        return sorted(p.name for p in self.datasets_dir.glob("*.jsonl"))

    def dataset_path(self, name: str) -> Path | None:
        path = self.datasets_dir / name
        return path if "/" not in name and path.is_file() else None

    def problems(self, *, paid: bool) -> list[str]:
        return list(self.problem_list)

    def child_env(self, *, paid: bool) -> dict[str, str]:
        return {"OPENAI_API_KEY": SECRET, "DATABASE_URL": "postgresql://u:pw@host/db"}

    def secrets(self) -> set[str]:
        return {SECRET}

    def expected_policy(self) -> tuple[str | None, str | None]:
        return self.expected, None


class FakeProcess:
    def __init__(self, pid: int, spec: LaunchSpec, outcome: dict[str, Any]):
        self.pid = pid
        self.spec = spec
        self.signals: list[int] = []
        self._code: int | None = None
        self._outcome = outcome
        self.spec.stdout.write_text(outcome.get("stdout", ""))
        self.spec.stderr.write_text(outcome.get("stderr", ""))
        if not outcome.get("hold"):
            self._code = outcome.get("code", 0)

    def poll(self) -> int | None:
        return self._code

    def finish(self, code: int | None = None, stdout: str | None = None) -> None:
        if stdout is not None:
            self.spec.stdout.write_text(stdout)
        self._code = self._outcome.get("code", 0) if code is None else code

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)
        self._code = 130  # the PoC exits with 130 on KeyboardInterrupt


class FakeLauncher:
    """Scripted CLI runs: ``script(...)`` queues the outcome of the next launch."""

    def __init__(self) -> None:
        self.launches: list[FakeProcess] = []
        self._queue: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def script(self, **outcome: Any) -> None:
        self._queue.append(outcome)

    def __call__(self, spec: LaunchSpec) -> FakeProcess:
        with self._lock:
            outcome = self._queue.pop(0) if self._queue else {"stdout": json.dumps({"completed_projection_jobs": 0})}
            process = FakeProcess(900_000 + len(self.launches), spec, outcome)
            self.launches.append(process)
        return process


def run_report(*, calls: int = 12, errors: int = 0, run_id: str = "run-test-1") -> dict[str, Any]:
    """A PoC RunReport as the CLI prints it."""
    return {
        "run_id": run_id,
        "processed": 4,
        "skipped": 2,
        "approved": 1,
        "held": 3,
        "rejected": 0,
        "pending": errors,
        "errors": [
            {"error": "ModelResponseError", "stage": "mention", "detail": f"failed with key {SECRET}", "article_id": "a1"}
            for _ in range(errors)
        ],
        "elapsed_seconds": 12.5,
        "execution_mode": "live",
        "usage": {
            "calls": calls,
            "replay_calls": 0,
            "input_tokens": 1000,
            "output_tokens": 200,
            "elapsed_seconds": 11.0,
            "estimated_cost": None,
        },
        "collection_errors": [],
        "evaluation_snapshot": {"issues": [], "candidates": []},
    }
