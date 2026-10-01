"""AI question jobs: one question = one stored job with a status, a frozen request and (when done) a saved result.

Why a job (FS046, FS049, FS053, NFS003, NFS009): a client that loses a response must be able to ask the server what
became of its question instead of asking again, and nothing may run twice or be shown unsaved.

* The client makes the job id (an idempotency key). The first request freezes the question, selection, period, the
  KST day it was asked and the graph version; the same id with the same body returns the stored job, with another
  body it is a conflict. A conversation has at most one queued/running job (a partial unique index, so concurrent
  requests cannot both be accepted).
* A worker thread runs the job. Every write a run makes is *fenced* by the run number: a run that was cancelled,
  timed out, replaced by a retry or outlived by a restart can neither save nor change anything.
* The answer is validated, then kept (``verified``), then saved together with its message row. A save that fails
  keeps the verified result, so the retry only saves; it never asks the engine again.
* What may be retried: a *confirmed temporary* failure (rerun with the frozen context) and a failed save of a kept
  result (save only). A failed validation, a lost result, an unclassified error or a lost permission is never rerun.

[팀 확인 필요] ``LEASE_SECONDS`` (when a silent run counts as interrupted), ``MAX_RERUNS`` (how often a temporary
failure may be retried), how long a verified result and job ids are kept, and where the verified result is kept
(here: the job row) are placeholders until measured in operation (FS053, NFS003, NFS009).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from .accounts import AccountStore, Principal, UserState
from .admin_usage import UsageService
from .audit import Clock
from .chat import GENERATED_BY, AnswerEngine, EngineUnavailable, RuleEngine, evidence_pool, resolve_all, validate_draft
from .chat_interpret import KST
from .chat_pipeline import Resolution, build_plan, interpret, result_of_draft, result_of_terminal, version_unavailable
from .errors import ApiError
from .schemas import (
    ChatContextItem,
    ChatContextRequest,
    ChatConversation,
    ChatFailure,
    ChatFrozenContext,
    ChatJob,
    ChatPeriod,
    ChatResult,
    ChatSessionResponse,
)
from .sources import DataProvider
from .statedb import StateDb, utc_iso

log = logging.getLogger("zoop_bff.chat")

LEASE_SECONDS = 120
MAX_RERUNS = 3
WORKERS = 4
HISTORY = 10  # earlier answers of the conversation recorded with a new question
ACTIVE = ("queued", "running")


class Superseded(Exception):
    """The run no longer owns the job (cancelled, timed out, replaced by a newer run, or a restart took over)."""


class Failure(Exception):
    def __init__(self, kind: str, reason: str):
        super().__init__(f"{kind}: {reason}")
        self.kind = kind
        self.reason = reason


@dataclass(frozen=True)
class Job:
    id: str
    session_id: str
    owner_id: str
    seq: int
    status: str
    outcome: str | None
    failure: str | None
    failure_reason: str | None
    run: int
    reruns: int
    request: dict[str, Any]
    resolution: dict[str, Any] | None
    verified: dict[str, Any] | None
    result: dict[str, Any] | None
    created_at: str
    updated_at: str
    finished_at: str | None
    lease_until: str | None

    @staticmethod
    def of(row: sqlite3.Row) -> Job:
        def parse(name: str) -> Any:
            return json.loads(row[name]) if row[name] else None

        return Job(
            row["id"], row["session_id"], row["owner_id"], row["seq"], row["status"], row["outcome"], row["failure"],
            row["failure_reason"], row["run"], row["reruns"], json.loads(row["request"]), parse("resolution"),
            parse("verified"), parse("result"), row["created_at"], row["updated_at"], row["finished_at"], row["lease_until"],
        )

    @property
    def message_id(self) -> str:
        return f"{self.session_id}-m{self.seq}"


def retry_mode(job: Job) -> str | None:
    """What a retry of this job would do (``None``: nothing is allowed)."""
    if job.status != "failed":
        return None
    if job.failure == "transient":
        return "rerun" if job.reruns < MAX_RERUNS else None
    if job.failure == "save_failed" and job.verified is not None:
        return "save_only"
    return None


_FAILURE_TEXT = {
    "validation_failed": "답변이 검증을 통과하지 못해 보여드리지 않아요. 같은 작업을 다시 만들지 않으니, 질문을 고쳐 새 질문으로 보내 주세요.",
    "result_lost": "검증한 결과를 보관하지 못해 복구할 수 없어요. 질문을 새 질문으로 다시 보내 주세요.",
    "permission_denied": "이 질문을 처리할 권한을 확인하지 못했어요. 로그인 상태를 확인해 주세요.",
    "internal": "답변을 만드는 중 예상하지 못한 오류가 났어요. 질문을 새 질문으로 다시 보내 주세요.",
}
_TRANSIENT_TEXT = {
    "server_restarted": "서버가 다시 시작되어 처리가 중단됐어요.",
    "execution_timeout": "처리가 오래 걸려 중단됐어요.",
    "source_unavailable": "승인 데이터를 읽지 못했어요.",
    "engine_unavailable": "답변 엔진이 잠시 응답하지 않아요.",
}


def _failure_view(job: Job) -> ChatFailure | None:
    if job.status != "failed" or job.failure is None:
        return None
    mode = retry_mode(job)
    if job.failure == "save_failed":
        text = "답변을 저장하지 못했어요. 검증한 결과는 남아 있어서 저장만 다시 시도할 수 있어요."
    elif job.failure == "transient":
        why = _TRANSIENT_TEXT.get(job.failure_reason or "", "일시적인 문제가 생겼어요.")
        text = f"{why} 같은 질문과 같은 조건으로 다시 시도할 수 있어요." if mode else f"{why} 다시 시도할 수 있는 횟수를 넘었어요. 새 질문으로 보내 주세요."
    else:
        text = _FAILURE_TEXT[job.failure]
    return ChatFailure(kind=job.failure, reason=job.failure_reason, message=text, retry=mode)  # type: ignore[arg-type]


def view(job: Job) -> ChatJob:
    req = job.request
    context = ChatFrozenContext(
        items=[ChatContextItem(**item) for item in req["contexts"]],
        evidence_count=req["evidenceCount"],
        period=ChatPeriod(**req["period"]) if req["period"] else None,
    )
    return ChatJob(
        id=job.id,
        session_id=job.session_id,
        seq=job.seq,
        question=req["question"],
        status=job.status,  # type: ignore[arg-type]
        outcome=job.outcome,  # type: ignore[arg-type]
        asked_at=req["askedAt"],
        context=context,
        failure=_failure_view(job),
        result=ChatResult.model_validate(job.result) if job.status == "completed" and job.result else None,
        runs=job.run,
        created_at=job.created_at,
        updated_at=job.updated_at,
        finished_at=job.finished_at,
    )


def _digest(session_id: str, question: str, context: ChatContextRequest) -> str:
    body = {
        "session": session_id,
        "question": question,
        "contexts": sorted(set(context.context_ids)),
        "evidence": sorted(set(context.evidence_ids)),
        "period": [context.period.start, context.period.end] if context.period else None,
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def busy_error(job_id: str, status: str) -> ApiError:
    return ApiError(
        409,
        "chat_session_busy",
        "이 대화에서 아직 처리 중인 질문이 있어요. 끝난 뒤에 새 질문을 보낼 수 있어요.",
        {"activeJobId": job_id, "status": status},
    )


class ChatStore:
    """SQL for conversations and jobs. Every state change of a run is fenced by the run number."""

    def __init__(self, db: StateDb, clock: Clock):
        self._db = db
        self._clock = clock

    def now(self) -> str:
        return utc_iso(self._clock.now())

    # ---- conversations

    def create_session(self, owner_id: str, owner_kind: str, session_id: str) -> tuple[sqlite3.Row, bool]:
        with self._db.transaction() as conn:
            row = conn.execute("SELECT * FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
            if row is not None:
                self._own(row, owner_id)
                return row, False
            conn.execute(
                "INSERT INTO chat_sessions(id,owner_id,owner_kind,context_ids,created_at) VALUES (?,?,?,?,?)",
                (session_id, owner_id, owner_kind, "[]", self.now()),
            )
            return conn.execute("SELECT * FROM chat_sessions WHERE id=?", (session_id,)).fetchone(), True

    @staticmethod
    def _own(row: sqlite3.Row, owner_id: str) -> sqlite3.Row:
        if row["owner_id"] != owner_id:
            raise ApiError(403, "forbidden", "다른 사용자의 대화에는 접근할 수 없습니다.")
        return row

    def owned_session(self, conn: sqlite3.Connection, session_id: str, owner_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise ApiError(404, "chat_session_not_found", "대화를 찾을 수 없습니다.")
        return self._own(row, owner_id)

    def assert_session(self, session_id: str, owner_id: str) -> None:
        with self._db.transaction() as conn:
            self.owned_session(conn, session_id, owner_id)

    def current_session_id(self, owner_id: str) -> str | None:
        row = self._db.one("SELECT id FROM chat_sessions WHERE owner_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (owner_id,))
        return row["id"] if row else None

    def job_count(self, session_id: str) -> int:
        return int(self._db.one("SELECT COUNT(*) AS n FROM chat_jobs WHERE session_id=?", (session_id,))["n"])  # type: ignore[index]

    def jobs_of(self, session_id: str, owner_id: str) -> tuple[sqlite3.Row, list[Job]]:
        with self._db.transaction() as conn:
            session = self.owned_session(conn, session_id, owner_id)
            self.expire_overdue(conn, session_id=session_id)
            rows = conn.execute("SELECT * FROM chat_jobs WHERE session_id=? ORDER BY seq", (session_id,)).fetchall()
            return session, [Job.of(r) for r in rows]

    # ---- jobs

    def find(self, job_id: str) -> bool:
        return self._db.one("SELECT 1 FROM chat_jobs WHERE id=?", (job_id,)) is not None

    def history(self, session_id: str) -> list[str]:
        rows = self._db.query(
            "SELECT message_id FROM chat_jobs WHERE session_id=? AND status='completed' ORDER BY seq DESC LIMIT ?", (session_id, HISTORY)
        )
        return [r["message_id"] for r in reversed(rows)]

    def accept(self, owner_id: str, session_id: str, job_id: str, digest: str, request: dict[str, Any]) -> tuple[Job, bool]:
        """Store a new job, or return the one this id already names (``False``). Raises 409 for a different body under
        the same id, and for a second queued/running job in the conversation."""
        with self._db.transaction() as conn:
            self.owned_session(conn, session_id, owner_id)
            existing = conn.execute("SELECT * FROM chat_jobs WHERE id=?", (job_id,)).fetchone()
            if existing is not None:
                if existing["owner_id"] != owner_id or existing["session_id"] != session_id or existing["digest"] != digest:
                    raise ApiError(
                        409,
                        "chat_job_conflict",
                        "같은 작업 ID로 다른 내용이 전송됐어요. 처음 받은 질문은 그대로 유지돼요. 고친 질문은 새 질문으로 보내 주세요.",
                        {"jobId": job_id, "status": existing["status"]},
                    )
                self.expire_overdue(conn, job_id=job_id)
                return Job.of(conn.execute("SELECT * FROM chat_jobs WHERE id=?", (job_id,)).fetchone()), False
            self.expire_overdue(conn, session_id=session_id)
            active = conn.execute(
                "SELECT id, status FROM chat_jobs WHERE session_id=? AND status IN ('queued','running')", (session_id,)
            ).fetchone()
            if active is not None:
                raise busy_error(active["id"], active["status"])
            seq = int(conn.execute("SELECT COALESCE(MAX(seq),0)+1 AS n FROM chat_jobs WHERE session_id=?", (session_id,)).fetchone()["n"])
            now = self.now()
            try:
                conn.execute(
                    "INSERT INTO chat_jobs(id,session_id,owner_id,seq,digest,request,status,created_at,updated_at) VALUES (?,?,?,?,?,?,'queued',?,?)",
                    (job_id, session_id, owner_id, seq, digest, json.dumps(request, ensure_ascii=False), now, now),
                )
            except sqlite3.IntegrityError as exc:  # the unique index is the last word on 'one active job per conversation'
                raise busy_error(job_id, "queued") from exc
            return Job.of(conn.execute("SELECT * FROM chat_jobs WHERE id=?", (job_id,)).fetchone()), True

    def owned_job(self, job_id: str, owner_id: str) -> Job:
        with self._db.transaction() as conn:
            return self._owned_job(conn, job_id, owner_id)

    def _owned_job(self, conn: sqlite3.Connection, job_id: str, owner_id: str) -> Job:
        row = conn.execute("SELECT * FROM chat_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ApiError(404, "chat_job_not_found", "질문 작업을 찾을 수 없습니다.", {"jobId": job_id})
        if row["owner_id"] != owner_id:
            raise ApiError(403, "forbidden", "다른 사용자의 질문에는 접근할 수 없습니다.")
        self.expire_overdue(conn, job_id=job_id)
        return Job.of(conn.execute("SELECT * FROM chat_jobs WHERE id=?", (job_id,)).fetchone())

    def expire_overdue(self, conn: sqlite3.Connection, *, session_id: str | None = None, job_id: str | None = None) -> None:
        """A running job whose lease ran out is no longer trusted: it is failed (a kept verified result stays
        saveable, anything else is a temporary failure). The silent run is fenced off by the status change."""
        where, args = ("session_id=?", session_id) if session_id else ("id=?", job_id)
        now = self.now()
        for row in conn.execute(f"SELECT * FROM chat_jobs WHERE {where} AND status='running' AND lease_until < ?", (args, now)).fetchall():
            kind = "save_failed" if row["verified"] else "transient"
            reason = "execution_timeout"
            conn.execute(
                "UPDATE chat_jobs SET status='failed', failure=?, failure_reason=?, finished_at=?, updated_at=?, lease_until=NULL WHERE id=?",
                (kind, reason, now, now, row["id"]),
            )

    def begin_run(self, job_id: str, lease_seconds: float) -> Job | None:
        """queued -> running as a new run (the fencing token is ``run``)."""
        with self._db.transaction() as conn:
            now = self.now()
            lease = utc_iso(self._clock.now() + timedelta(seconds=lease_seconds))
            changed = conn.execute(
                "UPDATE chat_jobs SET status='running', run=run+1, started_at=?, lease_until=?, updated_at=? WHERE id=? AND status='queued'",
                (now, lease, now, job_id),
            ).rowcount
            if not changed:
                return None
            return Job.of(conn.execute("SELECT * FROM chat_jobs WHERE id=?", (job_id,)).fetchone())

    @staticmethod
    def _fence(conn: sqlite3.Connection, job_id: str, run: int) -> None:
        row = conn.execute("SELECT status, run FROM chat_jobs WHERE id=?", (job_id,)).fetchone()
        if row is None or row["status"] != "running" or row["run"] != run:
            raise Superseded()

    def save_resolution(self, job_id: str, run: int, resolution: dict[str, Any]) -> None:
        with self._db.transaction() as conn:
            self._fence(conn, job_id, run)
            conn.execute("UPDATE chat_jobs SET resolution=?, updated_at=? WHERE id=?", (json.dumps(resolution, ensure_ascii=False), self.now(), job_id))

    def preserve(self, job_id: str, run: int, result: dict[str, Any]) -> None:
        """Keep the verified result before it is saved, so a failed save can be repaired without the engine."""
        with self._db.transaction() as conn:
            self._fence(conn, job_id, run)
            conn.execute("UPDATE chat_jobs SET verified=?, updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False), self.now(), job_id))

    def commit(self, job: Job, run: int, result: dict[str, Any], company_ids: list[str], context_ids: list[str]) -> None:
        """Save the answer: its message row and the completed job, together, only for the current run."""
        with self._db.transaction() as conn:
            self._fence(conn, job.id, run)
            now = self.now()
            conn.execute(
                "INSERT INTO chat_messages(id,session_id,seq,at,question,answer,status,reason,context_ids,company_ids,citation_count)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    result["messageId"], job.session_id, job.seq, now, job.request["question"], result["answer"], result["outcome"],
                    result.get("reason"), json.dumps(context_ids), json.dumps(company_ids), len(result["citations"]),
                ),
            )
            conn.execute("UPDATE chat_sessions SET messages = messages + 1 WHERE id=?", (job.session_id,))
            conn.execute(
                "UPDATE chat_jobs SET status='completed', outcome=?, result=?, message_id=?, verified=NULL, failure=NULL, failure_reason=NULL,"
                " finished_at=?, updated_at=?, lease_until=NULL WHERE id=?",
                (result["outcome"], json.dumps(result, ensure_ascii=False), result["messageId"], now, now, job.id),
            )

    def fail(self, job_id: str, run: int, kind: str, reason: str) -> None:
        with self._db.transaction() as conn:
            self._fence(conn, job_id, run)
            now = self.now()
            conn.execute(
                "UPDATE chat_jobs SET status='failed', failure=?, failure_reason=?, finished_at=?, updated_at=?, lease_until=NULL WHERE id=?",
                (kind, reason[:300], now, now, job_id),
            )

    def cancel(self, job_id: str, owner_id: str) -> Job:
        with self._db.transaction() as conn:
            job = self._owned_job(conn, job_id, owner_id)
            if job.status == "cancelled":
                return job
            if job.status not in ACTIVE:
                raise ApiError(409, "chat_job_not_cancellable", "이미 끝난 질문은 취소할 수 없어요.", {"jobId": job_id, "status": job.status})
            now = self.now()
            conn.execute("UPDATE chat_jobs SET status='cancelled', finished_at=?, updated_at=?, lease_until=NULL WHERE id=?", (now, now, job_id))
            return Job.of(conn.execute("SELECT * FROM chat_jobs WHERE id=?", (job_id,)).fetchone())

    def requeue(self, job_id: str, owner_id: str) -> tuple[Job, bool]:
        """failed -> queued when a retry is allowed (``True``); running/completed jobs are returned as they are."""
        with self._db.transaction() as conn:
            job = self._owned_job(conn, job_id, owner_id)
            if job.status in ACTIVE or job.status == "completed":
                return job, False
            mode = retry_mode(job)
            if job.status == "cancelled":
                raise ApiError(409, "chat_job_not_retryable", "취소한 질문은 다시 실행하지 않아요. 새 질문으로 보내 주세요.", {"jobId": job_id, "status": "cancelled"})
            if mode is None:
                failure = _failure_view(job)
                raise ApiError(
                    409,
                    "chat_job_not_retryable",
                    failure.message if failure else "이 작업은 다시 실행할 수 없어요.",
                    {"jobId": job_id, "failure": job.failure, "reason": job.failure_reason},
                )
            now = self.now()
            try:
                conn.execute(
                    "UPDATE chat_jobs SET status='queued', failure=NULL, failure_reason=NULL, finished_at=NULL, reruns=reruns+?, updated_at=? WHERE id=? AND status='failed'",
                    (1 if mode == "rerun" else 0, now, job_id),
                )
            except sqlite3.IntegrityError as exc:
                active = conn.execute("SELECT id, status FROM chat_jobs WHERE session_id=? AND status IN ('queued','running')", (job.session_id,)).fetchone()
                raise busy_error(active["id"] if active else job_id, active["status"] if active else "queued") from exc
            return Job.of(conn.execute("SELECT * FROM chat_jobs WHERE id=?", (job_id,)).fetchone()), True

    def recover(self) -> list[str]:
        """After a restart no run is alive. Never-started jobs are queued again; a run that had already kept its verified
        result goes back to the queue to be *saved* (no engine call); any other started run is a temporary failure the
        member can retry."""
        resume: list[str] = []
        with self._db.transaction() as conn:
            now = self.now()
            for row in conn.execute("SELECT * FROM chat_jobs WHERE status IN ('queued','running') ORDER BY created_at, rowid").fetchall():
                if row["status"] == "queued":
                    resume.append(row["id"])
                elif row["verified"]:
                    conn.execute("UPDATE chat_jobs SET status='queued', updated_at=?, lease_until=NULL WHERE id=?", (now, row["id"]))
                    resume.append(row["id"])
                else:
                    conn.execute(
                        "UPDATE chat_jobs SET status='failed', failure='transient', failure_reason='server_restarted', finished_at=?, updated_at=?, lease_until=NULL WHERE id=?",
                        (now, now, row["id"]),
                    )
        return resume


class ChatService:
    """Conversations and jobs for members. ``engine`` is replaceable (tests inject fakes; a model-backed engine fits)."""

    def __init__(
        self,
        db: StateDb,
        clock: Clock,
        provider: DataProvider,
        accounts: AccountStore,
        usage: UsageService,
        engine: AnswerEngine | None = None,
        *,
        lease_seconds: float = LEASE_SECONDS,
    ):
        self.store = ChatStore(db, clock)
        self.engine: AnswerEngine = engine or RuleEngine()
        self.lease_seconds = lease_seconds
        self._clock = clock
        self._provider = provider
        self._accounts = accounts
        self._usage = usage
        self._pool: ThreadPoolExecutor | None = None
        for job_id in self.store.recover():
            self._enqueue(job_id)

    # ---- plumbing

    def _enqueue(self, job_id: str) -> None:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="chat-job")
        self._pool.submit(self._run, job_id)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _member(principal: Principal) -> UserState:
        if principal.user is None:
            raise ApiError(403, "guest_forbidden", "AI 질문은 로그인한 회원만 쓸 수 있어요. 로그인한 뒤 다시 질문해 주세요.")
        return principal.user

    # ---- conversations

    def _conversation(self, session: sqlite3.Row, jobs: list[Job]) -> ChatConversation:
        return ChatConversation(
            session=ChatSessionResponse(id=session["id"], created_at=session["created_at"], jobs=len(jobs)),
            jobs=[view(j) for j in jobs],
        )

    def create_session(self, principal: Principal, session_id: str) -> tuple[ChatSessionResponse, bool]:
        """Idempotent: the same id returns the conversation made before (a lost response never makes a duplicate)."""
        member = self._member(principal)
        row, created = self.store.create_session(member.id, "member", session_id)
        return ChatSessionResponse(id=row["id"], created_at=row["created_at"], jobs=self.store.job_count(session_id)), created

    def conversation(self, principal: Principal, session_id: str) -> ChatConversation:
        member = self._member(principal)
        session, jobs = self.store.jobs_of(session_id, member.id)
        return self._conversation(session, jobs)

    def current(self, principal: Principal) -> ChatConversation | None:
        member = self._member(principal)
        session_id = self.store.current_session_id(member.id)
        return self.conversation(principal, session_id) if session_id else None

    # ---- jobs

    def submit(self, principal: Principal, session_id: str, body: Any) -> tuple[ChatJob, bool]:
        """Returns the job and whether this call accepted a new one (``False``: the stored job of a resent id)."""
        member = self._member(principal)
        question = body.question.strip()
        if not question:
            raise ApiError(422, "empty_question", "질문을 입력해 주세요.")
        context: ChatContextRequest = body.context
        digest = _digest(session_id, question, context)
        if self.store.find(body.job_id):
            job, created = self.store.accept(member.id, session_id, body.job_id, digest, {})
        else:
            request = self._freeze(member, session_id, question, context)
            job, created = self.store.accept(member.id, session_id, body.job_id, digest, request)
        if created:
            self._enqueue(job.id)
        return view(job), created

    def _freeze(self, member: UserState, session_id: str, question: str, context: ChatContextRequest) -> dict[str, Any]:
        self.store.assert_session(session_id, member.id)
        started = time.perf_counter()
        try:
            ds = self._provider.get()
        except ApiError as exc:
            if exc.status >= 500:  # the request failed before it became a job: count it as a failed AI request
                self._usage.record("chatbot", False, (time.perf_counter() - started) * 1000, code=exc.code, message=exc.message)
            raise
        if context.period:
            try:
                if date.fromisoformat(context.period.start) > date.fromisoformat(context.period.end):
                    raise ValueError
            except ValueError:
                raise ApiError(422, "invalid_period", "기간의 시작과 끝을 확인해 주세요.") from None
        nodes = resolve_all(ds, [*context.context_ids, *context.evidence_ids])  # 422 for ids the graph does not know
        by_id = {n.id: n for n in nodes}
        shown = [by_id[i] for i in dict.fromkeys(context.context_ids or context.evidence_ids)]
        pool = evidence_pool(ds, [by_id[i] for i in dict.fromkeys(context.context_ids or context.evidence_ids)], tuple(context.evidence_ids) if context.context_ids else (), None)
        asked = self._clock.now()
        return {
            "question": question,
            "contextIds": list(dict.fromkeys(context.context_ids)),
            "evidenceIds": list(dict.fromkeys(context.evidence_ids)),
            "period": {"start": context.period.start, "end": context.period.end} if context.period else None,
            "contexts": [{"id": n.id, "kind": n.kind, "label": n.label} for n in shown],
            "evidenceCount": len(pool.ids),
            "askedAt": utc_iso(asked),
            "askedDay": asked.astimezone(KST).date().isoformat(),
            "graphVersion": ds.graph_version,
            "dataAsOf": ds.as_of,
            "history": self.store.history(session_id),
        }

    def job(self, principal: Principal, job_id: str) -> ChatJob:
        member = self._member(principal)
        return view(self.store.owned_job(job_id, member.id))

    def retry(self, principal: Principal, job_id: str) -> tuple[ChatJob, bool]:
        member = self._member(principal)
        job, started = self.store.requeue(job_id, member.id)
        if started:
            self._enqueue(job_id)
        return view(job), started

    def cancel(self, principal: Principal, job_id: str) -> ChatJob:
        member = self._member(principal)
        return view(self.store.cancel(job_id, member.id))

    # ---- execution (worker thread)

    def _run(self, job_id: str) -> None:
        try:
            job = self.store.begin_run(job_id, self.lease_seconds)
        except Exception:
            log.exception("chat job %s could not start", job_id)
            return
        if job is None:
            return
        started = time.perf_counter()
        failure: Failure | None = None
        try:
            self._execute(job)
        except Superseded:
            return  # another run, a cancel or a timeout owns the job now: this run leaves no trace
        except Failure as exc:
            failure = exc
        except EngineUnavailable as exc:
            failure = Failure("transient", "engine_unavailable")
            log.warning("chat job %s: engine unavailable: %s", job_id, exc)
        except ApiError as exc:
            failure = Failure("transient", "source_unavailable") if exc.status >= 500 else Failure("internal", exc.code)
        except Exception as exc:
            log.exception("chat job %s failed unexpectedly", job_id)
            failure = Failure("internal", type(exc).__name__)
        if failure is not None:
            try:
                self.store.fail(job_id, job.run, failure.kind, failure.reason)
            except Superseded:
                return
            except Exception:
                log.exception("chat job %s: failure could not be recorded; the lease will expire it", job_id)
        try:
            self._usage.record(
                "chatbot",
                failure is None,
                (time.perf_counter() - started) * 1000,
                code=None if failure is None else failure.reason or failure.kind,
                message=None if failure is None else failure.kind,
            )
        except Exception:
            log.exception("chat usage event could not be recorded")

    def _execute(self, job: Job) -> None:
        run = job.run
        member = self._accounts.member(job.owner_id)
        if member is None or member.status != "active":
            raise Failure("permission_denied", "member_unavailable")
        if job.verified is not None:  # repair: the verified result survived, so only the save is repeated
            self._save(job, run, job.verified)
            return
        engine = self.engine
        generated_by = getattr(engine, "generated_by", GENERATED_BY)
        ds = self._provider.get()
        stored = Resolution.from_json(job.resolution) if job.resolution else None
        gone = version_unavailable(job.request, ds)  # the frozen graph version must still be the one served
        if gone is not None:
            resolution, terminal = stored or Resolution(), gone
        else:
            resolution = stored or interpret(ds, job.request, member)
            if stored is None:
                self.store.save_resolution(job.id, run, resolution.to_json())
            terminal = resolution.terminal
        if terminal is not None:
            result = result_of_terminal(ds, terminal, resolution, job.message_id, generated_by)
        else:
            plan = build_plan(ds, job.request, resolution)
            draft = engine.generate(ds, plan)
            problems = validate_draft(ds, plan, draft)
            if problems:
                raise Failure("validation_failed", ", ".join(problems[:5]))
            result = result_of_draft(ds, plan, resolution, draft, job.message_id, generated_by)
        self._save(job, run, result.model_dump(mode="json", by_alias=True))

    def _save(self, job: Job, run: int, result: dict[str, Any]) -> None:
        if job.verified is None:
            try:
                self.store.preserve(job.id, run, result)
            except Superseded:
                raise
            except Exception as exc:
                log.exception("chat job %s: verified result could not be kept", job.id)
                raise Failure("result_lost", type(exc).__name__) from exc
        context_ids = (job.resolution or {}).get("contextIds") or job.request["contextIds"]
        companies = [c["id"] for c in result["applied"]["companies"]]
        try:
            self.store.commit(job, run, result, companies, list(context_ids))
        except Superseded:
            raise
        except Exception as exc:
            log.exception("chat job %s: answer could not be saved", job.id)
            raise Failure("save_failed", type(exc).__name__) from exc
