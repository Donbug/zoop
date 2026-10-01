"""Job runner (requirements 76, 59): runs the real PoC CLI in the sandbox, one job at a time.

``flush-graph`` (GraphDB projection retry, no model call), ``retry-model-errors``
(``poc run --live --retry-model-errors``, billable) and ``ingest-run`` (``poc run --live --dataset FILE``:
process newly collected articles, billable, bounded by ``max_calls``) are launched as child processes of the sandbox
interpreter. Job records live in the state database, so a BFF restart can settle jobs that were
queued or running (``recover``). Secrets only exist in the child's environment; every line that
reaches the API or the log tail is masked.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from .admin_pipeline import PipelineService
from .admin_schemas import (
    FlushResult,
    JobError,
    JobLimits,
    JobList,
    JobLock,
    JobOut,
    LedgerCounts,
    PolicyCheck,
    RunReport,
    SandboxInfo,
)
from .admin_usage import PAID_JOB_KINDS, usage_from_report
from .audit import SYSTEM_STARTUP, Actor, AuditLog, Clock
from .config import Settings
from .errors import ApiError
from .statedb import StateDb, dumps, utc_iso

Kind = Literal["flush-graph", "retry-model-errors", "ingest-run"]
LABELS: dict[str, str] = {
    "flush-graph": "GraphDB 반영 재시도",
    "retry-model-errors": "모델 오류 재처리",
    "ingest-run": "신규 기사 처리",
}
PAID_KINDS = PAID_JOB_KINDS  # the kinds that spend model calls
DATASET_DIR = "zoop-expansion/datasets"  # inside the sandbox: article JSONL files the ingest-run job may read
_DATASET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.jsonl")
LOG_TAIL_LINES = 300
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_SECRET_KEY = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD)", re.I)
_DSN_PASSWORD = re.compile(r"(\w+://[^:/\s@]+:)[^@\s]+(@)")
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}")
_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}")
_CANCEL_GRACE = (10.0, 5.0)  # seconds after SIGINT, then after SIGTERM, before SIGKILL


# ---------------------------------------------------------------- process plumbing


@dataclass(frozen=True)
class LaunchSpec:
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    stdout: Path
    stderr: Path


class Process(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def send_signal(self, sig: int) -> None: ...


Launcher = Callable[[LaunchSpec], Process]


class _PopenProcess:
    def __init__(self, popen: subprocess.Popen[bytes]):
        self._popen = popen
        self.pid = popen.pid

    def poll(self) -> int | None:
        return self._popen.poll()

    def send_signal(self, sig: int) -> None:
        try:
            os.killpg(self.pid, sig)  # the child runs in its own session: signal the whole group
        except ProcessLookupError:
            pass


def popen_launcher(spec: LaunchSpec) -> Process:
    spec.stdout.parent.mkdir(parents=True, exist_ok=True)
    with spec.stdout.open("wb") as out, spec.stderr.open("wb") as err:
        popen = subprocess.Popen(
            spec.argv,
            cwd=spec.cwd,
            env=spec.env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
    return _PopenProcess(popen)


# ---------------------------------------------------------------- sandbox


_PROBE = """
import argparse, json, sys
from contextlib import ExitStack
from investmate import cli
settings = cli._settings(sys.argv[1])
args = argparse.Namespace(replay=None, live=True, command="run", web_verify=False, web_sources_config=None)
with ExitStack() as stack:
    model = cli._model(args, settings, stack)  # builds the client only; no request is sent
    print(json.dumps({"expected": settings.policy_for(model.version)}))
"""


def parse_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines (optional ``export`` and quotes). Never evaluated by a shell."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


class Sandbox:
    """The copied PoC checkout the jobs run in (``ZOOP_POC_SANDBOX``); its ``src/`` mirrors the original."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self.path = settings.poc_sandbox
        self._expected: tuple[tuple[float, float], str | None, str | None] | None = None
        self._lock = threading.Lock()

    @property
    def poc(self) -> Path:
        return self.path / ".venv" / "bin" / "poc"

    @property
    def python(self) -> Path:
        return self.path / ".venv" / "bin" / "python"

    @property
    def env_file(self) -> Path:
        return self.path / ".env"

    @property
    def settings_file(self) -> Path:
        return self.path / self._settings.poc_settings_file

    @property
    def datasets_dir(self) -> Path:
        return self.path / DATASET_DIR

    def datasets(self) -> list[str]:
        try:
            return sorted(p.name for p in self.datasets_dir.glob("*.jsonl") if _DATASET_NAME.fullmatch(p.name) and p.is_file())
        except OSError:
            return []

    def dataset_path(self, name: str) -> Path | None:
        """The dataset file for a plain name, or None (no directories, no symlink out of the datasets folder)."""
        if not _DATASET_NAME.fullmatch(name):
            return None
        path = self.datasets_dir / name
        if not path.is_file() or path.resolve().parent != self.datasets_dir.resolve():
            return None
        return path

    def problems(self, *, paid: bool) -> list[str]:
        problems: list[str] = []
        if not self.path.is_dir():
            return [f"샌드박스 디렉터리가 없습니다: {self.path}"]
        if not os.access(self.poc, os.X_OK):
            problems.append("샌드박스에 .venv/bin/poc가 없습니다(uv sync --offline --locked 필요).")
        if paid:
            if not self.env_file.is_file():
                problems.append("샌드박스에 .env가 없어 모델 호출 설정을 읽을 수 없습니다.")
            if not self.settings_file.is_file():
                problems.append(f"샌드박스에 {self._settings.poc_settings_file}가 없습니다.")
        return problems

    def child_env(self, *, paid: bool) -> dict[str, str]:
        env = {
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(Path.home()),
            "LANG": "en_US.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
        if paid and self.env_file.is_file():
            env.update(parse_env_file(self.env_file))
        # The BFF decides which ledger the child touches, whatever the sandbox .env says.
        env.update(
            DATABASE_URL=self._settings.admin_poc_dsn,
            NEO4J_URI=self._settings.admin_neo4j_uri,
            NEO4J_USERNAME=self._settings.admin_neo4j_user,
            NEO4J_PASSWORD=self._settings.admin_neo4j_password,
            REDIS_URL="",
        )
        return env

    def secrets(self) -> set[str]:
        values = {self._settings.admin_poc_dsn, self._settings.admin_neo4j_password}
        if self.env_file.is_file():
            for key, value in parse_env_file(self.env_file).items():
                if _SECRET_KEY.search(key) or key == "DATABASE_URL":
                    values.add(value)
        return {v for v in values if len(v) >= 6}

    def expected_policy(self) -> tuple[str | None, str | None]:
        """(policy id the sandbox settings would activate, error). Cached per settings/.env stamp."""
        problems = self.problems(paid=True)
        if problems:
            return None, problems[0]
        stamp = (self.settings_file.stat().st_mtime, self.env_file.stat().st_mtime)
        with self._lock:
            if self._expected is not None and self._expected[0] == stamp:
                return self._expected[1], self._expected[2]
        try:
            result = subprocess.run(
                [str(self.python), "-c", _PROBE, str(self.settings_file)],
                cwd=self.path,
                env=self.child_env(paid=True),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            expected = json.loads(result.stdout.strip().splitlines()[-1])["expected"] if result.returncode == 0 else None
            error = None if expected else f"정책 해시를 계산하지 못했습니다(종료 코드 {result.returncode})."
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError) as exc:
            expected, error = None, f"정책 해시를 계산하지 못했습니다({type(exc).__name__})."
        with self._lock:
            self._expected = (stamp, expected, error)
        return expected, error


# ---------------------------------------------------------------- records


@dataclass
class JobRecord:
    id: str
    seq: int
    kind: Kind
    reason: str
    requested_by: str
    requested_at: str
    status: str = "queued"
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    max_model_calls: int | None = None
    command: list[str] = field(default_factory=list)
    dataset: str | None = None
    retry_of: str | None = None
    cancel_requested: bool = False
    recovered: bool = False
    pid: int | None = None
    elapsed_seconds: float | None = None  # measured with a monotonic clock; timestamps only have 1 s resolution
    report: dict[str, Any] | None = None
    flush: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    ledger_before: dict[str, Any] | None = None
    ledger_after: dict[str, Any] | None = None

    @property
    def paid(self) -> bool:
        return self.kind in PAID_KINDS


def _record(row: Any) -> JobRecord:
    return JobRecord(seq=row["seq"], **json.loads(row["data"]))


class Masker:
    def __init__(self, secrets: set[str]):
        self._secrets = sorted(secrets, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "[redacted]")
        text = _DSN_PASSWORD.sub(r"\1[redacted]\2", text)
        text = _BEARER.sub(r"\1[redacted]", text)
        return _SK_TOKEN.sub("[redacted]", text)


class JobRunner:
    def __init__(
        self,
        *,
        settings: Settings,
        db: StateDb,
        clock: Clock,
        audit: AuditLog,
        pipeline: PipelineService,
        sandbox: Sandbox | Any | None = None,
        launcher: Launcher = popen_launcher,
    ):
        self._settings = settings
        self._db = db
        self._clock = clock
        self._audit = audit
        self._pipeline = pipeline
        self.sandbox = sandbox or Sandbox(settings)
        self._launcher = launcher
        self._dir = db.directory / "jobs"
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}

    # ---- persistence
    def _load(self, job_id: str) -> JobRecord | None:
        row = self._db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        return _record(row) if row else None

    def _save(self, rec: JobRecord) -> None:
        data = {k: v for k, v in rec.__dict__.items() if k != "seq"}
        self._db.execute(
            "UPDATE jobs SET status=?, data=? WHERE id=?", (rec.status, dumps(data), rec.id)
        )

    def _insert(self, rec_args: dict[str, Any]) -> JobRecord:
        with self._db.transaction() as conn:
            seq = int(conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM jobs").fetchone()[0])
            rec = JobRecord(id=f"job-{seq:04d}", seq=seq, **rec_args)
            data = {k: v for k, v in rec.__dict__.items() if k != "seq"}
            conn.execute(
                "INSERT INTO jobs(id,seq,kind,status,requested_at,data) VALUES (?,?,?,?,?,?)",
                (rec.id, seq, rec.kind, rec.status, rec.requested_at, dumps(data)),
            )
        return rec

    def _active(self) -> JobRecord | None:
        row = self._db.one("SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY seq LIMIT 1")
        return _record(row) if row else None

    # ---- views
    def _masker(self) -> Masker:
        return Masker(self.sandbox.secrets())

    def _log_tail(self, rec: JobRecord) -> list[str]:
        mask = self._masker()
        job_dir = self._dir / rec.id
        lines: list[str] = []
        stderr = job_dir / "stderr.log"
        if stderr.is_file():
            lines += stderr.read_text(encoding="utf-8", errors="replace").splitlines()
        if rec.report is not None or rec.flush is not None:
            summary = {"report": rec.report, "flush": rec.flush}
            lines += ["--- stdout (요약) ---", *json.dumps(summary, ensure_ascii=False, indent=2).splitlines()]
        elif (job_dir / "stdout.log").is_file():
            raw = (job_dir / "stdout.log").read_text(encoding="utf-8", errors="replace").splitlines()
            if raw:
                lines += ["--- stdout ---", *raw[-100:]]
        return [mask(line)[:2000] for line in lines[-LOG_TAIL_LINES:]]

    def to_out(self, rec: JobRecord, *, with_log: bool) -> JobOut:
        duration = rec.elapsed_seconds
        if duration is None and rec.started_at and rec.finished_at:
            duration = (_parse(rec.finished_at) - _parse(rec.started_at)).total_seconds()
        return JobOut(
            id=rec.id,
            kind=rec.kind,
            dataset=rec.dataset,
            label=LABELS[rec.kind],
            paid=rec.paid,
            status=rec.status,  # type: ignore[arg-type]
            reason=rec.reason,
            requested_by=rec.requested_by,
            requested_at=rec.requested_at,
            started_at=rec.started_at,
            finished_at=rec.finished_at,
            duration_seconds=duration,
            exit_code=rec.exit_code,
            max_model_calls=rec.max_model_calls,
            command=rec.command,
            retry_of=rec.retry_of,
            cancel_requested=rec.cancel_requested,
            recovered=rec.recovered,
            retryable=rec.status in ("failed", "cancelled"),
            report=RunReport(**rec.report) if rec.report else None,
            flush=FlushResult(**rec.flush) if rec.flush else None,
            error=JobError(**rec.error) if rec.error else None,
            ledger_before=LedgerCounts(**rec.ledger_before) if rec.ledger_before else None,
            ledger_after=LedgerCounts(**rec.ledger_after) if rec.ledger_after else None,
            log_tail=self._log_tail(rec) if with_log else None,
        )

    def get(self, job_id: str) -> JobOut:
        rec = self._load(job_id)
        if rec is None:
            raise ApiError(404, "job_not_found", "작업을 찾을 수 없습니다.")
        return self.to_out(rec, with_log=True)

    def recent(self, limit: int, status: str | None = None) -> list[JobOut]:
        if status:
            rows = self._db.query("SELECT * FROM jobs WHERE status=? ORDER BY seq DESC LIMIT ?", (status, limit))
        else:
            rows = self._db.query("SELECT * FROM jobs ORDER BY seq DESC LIMIT ?", (limit,))
        return [self.to_out(_record(r), with_log=False) for r in rows]

    def all_data(self) -> list[dict[str, Any]]:
        """Every job as a camelCase dict (AI usage aggregation)."""
        rows = self._db.query("SELECT * FROM jobs ORDER BY seq")
        return [self.to_out(_record(r), with_log=False).model_dump(by_alias=True, mode="json") for r in rows]

    def counts(self, since_iso: str) -> dict[str, int]:
        def one(sql: str, *params: Any) -> int:
            row = self._db.one(sql, params)
            return int(row[0]) if row else 0

        return {
            "running": one("SELECT COUNT(*) FROM jobs WHERE status='running'"),
            "queued": one("SELECT COUNT(*) FROM jobs WHERE status='queued'"),
            "failed24h": one(
                "SELECT COUNT(*) FROM jobs WHERE status='failed' AND json_extract(data,'$.finished_at') >= ?", since_iso
            ),
        }

    def active_out(self) -> JobOut | None:
        rec = self._active()
        return self.to_out(rec, with_log=False) if rec else None

    def policy_check(self) -> PolicyCheck:
        expected, error = self.sandbox.expected_policy()
        active: str | None = None
        try:
            active = self._pipeline_policy_version()
        except ApiError as exc:
            error = error or exc.message
        match = (expected == active) if expected and active else None
        return PolicyCheck(
            expected=expected, active=active, match=match, checked_at=utc_iso(self._clock.now()), error=error
        )

    def _pipeline_policy_version(self) -> str | None:
        return self._pipeline.policy_info().version

    def listing(self, status: str | None, limit: int) -> JobList:
        active = self._active()
        problems = self.sandbox.problems(paid=True)
        policy = self.policy_check() if not problems else None
        if policy is not None and policy.match is False:
            problems.append("DB의 활성 정책이 샌드박스 설정의 정책 해시와 다릅니다(activate-policy는 자동 실행하지 않습니다).")
        elif policy is not None and policy.match is None and policy.error:
            problems.append(policy.error)
        return JobList(
            items=self.recent(limit, status),
            active=self.to_out(active, with_log=False) if active else None,
            lock=JobLock(
                locked=active is not None,
                job_id=active.id if active else None,
                reason=f"{LABELS[active.kind]} 작업({active.id})이 {'실행 중' if active.status == 'running' else '대기 중'}입니다." if active else None,
            ),
            limits=JobLimits(
                default_max_model_calls=self._settings.admin_default_model_calls,
                max_model_calls=self._settings.admin_max_model_calls,
            ),
            sandbox=SandboxInfo(
                ready=not self.sandbox.problems(paid=False),
                path=str(self.sandbox.path),
                problems=problems,
                policy=policy,
                datasets=self.sandbox.datasets(),
            ),
        )

    # ---- create / retry
    def create(
        self,
        *,
        kind: Kind,
        reason: str,
        max_model_calls: int | None,
        confirm_paid: bool | None,
        admin: Actor,
        retry_of: str | None = None,
        dataset: str | None = None,
    ) -> tuple[JobOut, bool]:
        paid = kind in PAID_KINDS
        if kind == "ingest-run":
            if dataset is None:
                raise ApiError(422, "dataset_required", "신규 기사 처리에는 처리할 기사 파일(dataset)이 필요합니다.", {"datasets": self.sandbox.datasets()})
            if self.sandbox.dataset_path(dataset) is None:
                raise ApiError(422, "dataset_not_found", "샌드박스의 기사 파일 목록에 없는 파일입니다.", {"datasets": self.sandbox.datasets()})
        elif dataset is not None:
            raise ApiError(422, "dataset_not_allowed", "기사 파일(dataset)은 신규 기사 처리에서만 쓸 수 있습니다.")
        cap: int | None = None
        if paid:
            if confirm_paid is not True:
                raise ApiError(422, "paid_confirmation_required", "유료 작업은 비용 확인(confirmPaid=true)이 필요합니다.")
            cap = self._settings.admin_default_model_calls if max_model_calls is None else max_model_calls
            if cap < 1 or cap > self._settings.admin_max_model_calls:
                raise ApiError(
                    422,
                    "max_model_calls_invalid",
                    f"모델 호출 상한은 1~{self._settings.admin_max_model_calls}회여야 합니다.",
                    {"maxModelCalls": cap, "allowedMax": self._settings.admin_max_model_calls},
                )
        with self._lock:
            active = self._active()
            if active is not None:
                if active.kind == kind and active.dataset == dataset:
                    return self.to_out(active, with_log=False), True
                raise ApiError(409, "job_in_progress", "다른 작업이 실행 중입니다. 끝난 뒤 다시 요청해 주세요.", {"jobId": active.id})
        problems = self.sandbox.problems(paid=paid)
        if problems:
            raise ApiError(409, "sandbox_not_ready", "PoC 샌드박스가 준비되지 않았습니다.", {"problems": problems})
        if paid:
            check = self.policy_check()
            if check.match is None:
                raise ApiError(409, "sandbox_not_ready", "활성 정책을 확인하지 못해 유료 작업을 시작하지 않습니다.", {"problems": [check.error or "정책 확인 불가"]})
            if check.match is False:
                raise ApiError(
                    409,
                    "policy_mismatch",
                    "DB의 활성 정책이 샌드박스 설정과 달라 유료 작업을 시작하지 않습니다. activate-policy는 자동으로 실행하지 않습니다.",
                    {"expected": check.expected, "active": check.active},
                )
        with self._lock:
            active = self._active()
            if active is not None:
                if active.kind == kind and active.dataset == dataset:
                    return self.to_out(active, with_log=False), True
                raise ApiError(409, "job_in_progress", "다른 작업이 실행 중입니다. 끝난 뒤 다시 요청해 주세요.", {"jobId": active.id})
            rec = self._insert(
                dict(
                    kind=kind,
                    reason=reason,
                    requested_by=admin.email or admin.id,
                    requested_at=utc_iso(self._clock.now()),
                    max_model_calls=cap,
                    retry_of=retry_of,
                    command=self._display_command(kind, cap, dataset),
                    dataset=dataset,
                )
            )
            self._audit.record(
                admin,
                "job.retry" if retry_of else "job.create",
                "job",
                rec.id,
                reason=reason,
                detail={"kind": kind, "paid": paid, "maxModelCalls": cap, "retryOf": retry_of},
            )
            self._cancel[rec.id] = threading.Event()
            thread = threading.Thread(target=self._run, args=(rec.id,), name=f"job-{rec.id}", daemon=True)
            self._threads[rec.id] = thread
            thread.start()
        return self.to_out(self._load(rec.id) or rec, with_log=False), False

    def retry(
        self, job_id: str, *, reason: str, max_model_calls: int | None, confirm_paid: bool | None, admin: Actor
    ) -> tuple[JobOut, bool]:
        rec = self._load(job_id)
        if rec is None:
            raise ApiError(404, "job_not_found", "작업을 찾을 수 없습니다.")
        if rec.status not in ("failed", "cancelled"):
            raise ApiError(409, "job_not_retryable", "실패하거나 취소된 작업만 다시 시도할 수 있습니다.", {"status": rec.status})
        return self.create(
            kind=rec.kind,
            reason=reason,
            max_model_calls=max_model_calls,
            confirm_paid=confirm_paid,
            admin=admin,
            retry_of=rec.id,
            dataset=rec.dataset,
        )

    def _display_command(self, kind: Kind, cap: int | None, dataset: str | None = None) -> list[str]:
        if kind == "flush-graph":
            return ["poc", "flush-graph"]
        config = f"{self._settings.poc_settings_file} (max_calls={cap})"
        if kind == "ingest-run":
            return ["poc", "run", "--live", "--config", config, "--dataset", f"{DATASET_DIR}/{dataset}"]
        return ["poc", "run", "--live", "--retry-model-errors", "--config", config]

    # ---- execution
    def _spec(self, rec: JobRecord) -> LaunchSpec:
        job_dir = self._dir / rec.id
        job_dir.mkdir(parents=True, exist_ok=True)
        argv = [str(self.sandbox.poc)]
        if rec.kind == "flush-graph":
            argv.append("flush-graph")
        else:
            base = json.loads(self.sandbox.settings_file.read_text(encoding="utf-8"))
            base["max_calls"] = rec.max_model_calls  # the PoC stops calling the model at this count
            config = job_dir / "settings.json"
            config.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
            if rec.kind == "ingest-run":
                path = self.sandbox.dataset_path(rec.dataset or "")
                if path is None:
                    raise FileNotFoundError(rec.dataset)
                argv += ["run", "--live", "--config", str(config), "--dataset", str(path)]
            else:
                argv += ["run", "--live", "--retry-model-errors", "--config", str(config)]
        return LaunchSpec(
            argv=argv,
            cwd=self.sandbox.path,
            env=self.sandbox.child_env(paid=rec.paid),
            stdout=job_dir / "stdout.log",
            stderr=job_dir / "stderr.log",
        )

    def _counts(self) -> dict[str, Any] | None:
        try:
            return self._pipeline.ledger_counts().model_dump(by_alias=False)
        except Exception:
            return None

    def _run(self, job_id: str) -> None:
        cancel = self._cancel[job_id]
        rec = self._load(job_id)
        assert rec is not None
        code: int | None = None
        try:
            if cancel.is_set():
                self._settle(rec, None, cancelled=True)
                return
            rec.ledger_before = self._counts()
            proc = self._launcher(self._spec(rec))
            rec.status, rec.started_at, rec.pid = "running", utc_iso(self._clock.now()), proc.pid
            self._save(rec)
            began = time.monotonic()
            code = self._wait(proc, cancel)
            self._settle(rec, code, cancelled=cancel.is_set(), elapsed=time.monotonic() - began)
        except Exception as exc:  # launch or bookkeeping failure: never leave the lock held
            rec = self._load(job_id) or rec
            rec.error = {"code": "launch_failed", "message": self._masker()(f"작업을 실행하지 못했습니다({type(exc).__name__}).")}
            self._finish(rec, "failed", code)
        finally:
            self._pipeline.forget()
            with self._lock:
                self._cancel.pop(job_id, None)

    def _wait(self, proc: Process, cancel: threading.Event) -> int:
        """Poll until exit; on cancel escalate SIGINT -> SIGTERM -> SIGKILL with a grace period each."""
        ladder = (signal.SIGINT, signal.SIGTERM, signal.SIGKILL)
        phase, phase_started = -1, 0.0
        while True:
            code = proc.poll()
            if code is not None:
                return code
            if cancel.is_set():
                now = time.monotonic()
                if phase < 0:
                    phase, phase_started = 0, now
                    proc.send_signal(ladder[0])
                elif phase < len(_CANCEL_GRACE) and now - phase_started >= _CANCEL_GRACE[phase]:
                    phase, phase_started = phase + 1, now
                    proc.send_signal(ladder[phase])
            time.sleep(0.05)

    def _settle(self, rec: JobRecord, code: int | None, *, cancelled: bool, elapsed: float | None = None) -> None:
        rec = self._load(rec.id) or rec
        rec.exit_code = code
        rec.elapsed_seconds = elapsed
        job_dir = self._dir / rec.id
        mask = self._masker()
        data = _read_json(job_dir / "stdout.log")
        report = _run_report(data, mask) if rec.paid else None
        flush = (
            {"completed_projection_jobs": int(data["completed_projection_jobs"])}
            if not rec.paid and isinstance(data, dict) and "completed_projection_jobs" in data
            else None
        )
        rec.report, rec.flush = report, flush
        if cancelled:
            status = "cancelled"
        elif code == 0:
            status = "succeeded"
        else:
            status = "failed"
            rec.error = self._failure(rec, code, report, job_dir, mask)
        self._finish(rec, status, code)

    def _failure(
        self, rec: JobRecord, code: int | None, report: dict[str, Any] | None, job_dir: Path, mask: Masker
    ) -> dict[str, str]:
        if report is not None:
            calls = int(report["usage"].get("calls") or 0)
            hit = (
                f" 모델 호출 {calls}회로 상한({rec.max_model_calls}회)에 닿아 멈췄을 수 있습니다."
                if rec.max_model_calls and calls >= rec.max_model_calls
                else ""
            )
            return {
                "code": "cli_nonzero_exit",
                "message": f"PoC가 종료 코드 {code}로 끝났습니다(남은 오류 {report['error_count']}건).{hit}",
            }
        message = f"PoC가 종료 코드 {code}로 끝났습니다."
        stderr = job_dir / "stderr.log"
        if stderr.is_file():
            lines = [l for l in stderr.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            if lines:
                try:
                    parsed = json.loads(lines[-1])
                    message += f" {parsed.get('error', '')}: {parsed.get('message', '')}".rstrip(": ")
                except ValueError:
                    message += f" {lines[-1][:300]}"
        return {"code": "cli_nonzero_exit", "message": mask(message)}

    def _finish(self, rec: JobRecord, status: str, code: int | None) -> None:
        current = self._load(rec.id)
        if current is not None and current.status not in ("queued", "running"):
            return  # already settled elsewhere (restart recovery): the first verdict stands
        rec.status = status
        rec.exit_code = code if code is not None else rec.exit_code
        rec.finished_at = utc_iso(self._clock.now())
        rec.ledger_after = self._counts()
        self._save(rec)

    # ---- cancel
    def cancel(self, job_id: str, *, reason: str, admin: Actor) -> JobOut:
        rec = self._load(job_id)
        if rec is None:
            raise ApiError(404, "job_not_found", "작업을 찾을 수 없습니다.")
        if rec.status == "cancelled":
            return self.to_out(rec, with_log=True)
        if rec.status not in ("queued", "running"):
            raise ApiError(409, "job_not_cancellable", "이미 끝난 작업은 취소할 수 없습니다.", {"status": rec.status})
        with self._lock:
            event = self._cancel.get(job_id)
            thread = self._threads.get(job_id)
            rec.cancel_requested = True
            self._save(rec)
            self._audit.record(admin, "job.cancel", "job", job_id, reason=reason, detail={"kind": rec.kind, "status": rec.status})
        if event is not None:
            event.set()
        if thread is not None:
            thread.join(timeout=sum(_CANCEL_GRACE) + 10)
        return self.get(job_id)

    def wait(self, job_id: str, timeout: float = 30.0) -> JobOut:
        """Block until the job's monitor thread ended (tests and shutdown)."""
        thread = self._threads.get(job_id)
        if thread is not None:
            thread.join(timeout)
        return self.get(job_id)

    # ---- restart recovery (requirement 59)
    def recover(self) -> int:
        """Settle jobs that were queued or running when the previous BFF process ended."""
        settled = 0
        for row in self._db.query("SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY seq"):
            rec = _record(row)
            self._stop_orphan(rec)
            data = _read_json(self._dir / rec.id / "stdout.log")
            mask = self._masker()
            rec.report = _run_report(data, mask) if rec.paid else None
            rec.recovered = True
            rec.error = {
                "code": "interrupted_by_restart",
                "message": "BFF가 다시 시작되어 진행 중이던 작업을 중단 처리했습니다."
                + (" 출력된 보고서가 있어 함께 보존했습니다." if rec.report else ""),
            }
            self._finish(rec, "failed", rec.exit_code)
            self._audit.record(
                SYSTEM_STARTUP,
                "job.recover",
                "job",
                rec.id,
                reason="BFF 재시작 때 진행 중이던 작업 정리",
                outcome="failed",
                detail={"kind": rec.kind, "pid": rec.pid, "hadReport": rec.report is not None},
            )
            settled += 1
        return settled

    def _stop_orphan(self, rec: JobRecord) -> None:
        """Kill the leftover child of a job the previous process started (only if it is still ours)."""
        if not rec.pid:
            return
        try:
            command = subprocess.run(
                ["ps", "-p", str(rec.pid), "-o", "command="], capture_output=True, text=True, check=False
            ).stdout
        except OSError:
            return
        if str(self.sandbox.path) not in command:
            return
        for sig, wait_seconds in ((signal.SIGINT, 5.0), (signal.SIGTERM, 5.0), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(rec.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                try:
                    os.kill(rec.pid, 0)
                except ProcessLookupError:
                    return
                time.sleep(0.1)


# ---------------------------------------------------------------- helpers


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _read_json(path: Path) -> Any:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_OUTPUT_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _run_report(data: Any, mask: Masker) -> dict[str, Any] | None:
    """The CLI's RunReport JSON -> the API shape (snake_case dict for ``RunReport``)."""
    if not isinstance(data, Mapping) or "run_id" not in data or "processed" not in data:
        return None
    errors = [e for e in data.get("errors") or [] if isinstance(e, Mapping)]
    usage = usage_from_report(data.get("usage") if isinstance(data.get("usage"), Mapping) else None)
    return {
        "run_id": str(data["run_id"]),
        "processed": int(data.get("processed") or 0),
        "skipped": int(data.get("skipped") or 0),
        "approved": int(data.get("approved") or 0),
        "held": int(data.get("held") or 0),
        "rejected": int(data.get("rejected") or 0),
        "pending": int(data.get("pending") or 0),
        "error_count": len(errors),
        "errors": [
            {
                k: mask(str(v))[:400]
                for k, v in (("stage", e.get("stage")), ("type", e.get("error")), ("message", e.get("detail")))
                if v is not None
            }
            for e in errors[:50]
        ],
        "elapsed_seconds": float(data.get("elapsed_seconds") or 0.0),
        "execution_mode": data.get("execution_mode"),
        "usage": usage.model_dump(),
    }
