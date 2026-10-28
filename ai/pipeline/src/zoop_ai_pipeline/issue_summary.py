"""Independent ISSUE SUMMARY job ledger (authored replay or the bound live runtime): one multi-article summary of ONE public issue per job.
Private to this ledger: no application, S1, ingestion, S2, S3 or handoff writer, and no public route.

Flow: `submit` freezes the exact input (the issue's title and its mention quotes, pinned to article versions and quote hashes, read through the handoff
Planner without freezing or exporting anything) as a `queued` job and calls nothing. `run`/`resume` execute it: ONE generation call, then ONE independent
Jev verification of the produced claims against the quotes they cite. Every decision is deterministic from the stored receipts:

* an issue with ANY HOLD/REJECT field verdict, or with more quotes than `MAX_QUOTES`, never gets a job (rejected at `submit`: no row, no call);
* the only outcomes of a finished (`ready`) job are `available` or a withheld code (`producer-invalid`, `verifier-hold`, `verifier-reject`): a job that
  could not reach a usable outcome is `stopped` (nothing consumed, `resume` retries) or `failed` (terminal), never an empty or partial summary;
* model-send rights are checked for every basis document immediately before a send and again after the reply; the raw provider receipt is persisted
  BEFORE anything decodes it; a call that was started but has no receipt is `provider_outcome_unknown` and is NEVER resent (`failed`, terminal).

Replay is authored-response replay (`Fixtures`), not independent model inference; a summary it produces says so (`authored-replay`). A job is bound to the
manifest it was submitted with: when a pinned operator file or review state moves before the job finished, `resume` stops with the planner's code and a new
job under the new manifest is submitted. The finished result is read by the handoff through `load_result` only (read-only, ledger shape stays private).
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from . import issue_summary_jev as jev
from . import issue_summary_prompts as prompts
from .extraction_contracts import ExtractionFailure, ProviderResponseUnknown
from .handoff_contracts import HASH as HASH_PATTERN
from .handoff_contracts import ID as ID_PATTERN
from .handoff_contracts import Manifest, text_sha256
from .ingestion_contracts import IngestionFailure, Wire, byte_hash, now, reserved_state_roots
from .issue_summary_contracts import (INPUT_TOO_LARGE, JOB_CODES, POLICY, SCHEMA, TEMPORAL_PENDING, assemble, available_body, basis_digest,
    deterministic_code, result_digest, summary_basis, withheld_body)
from .live_runtime import ISSUE_SUMMARY, LiveFailure, LiveRuntime
from .relation_contracts import canonical, digest

LEDGER_VERSION = "zoop-issue-summary-ledger-1"
FIXTURE = "zoop-issue-summary-fixture-1"
MAX_COMMAND = 65_536
MAX_FIXTURE = 20_000_000
PRODUCE, VERIFY = prompts.STAGE, jev.STAGE
STAGES = (PRODUCE, VERIFY)
# A reply the provider DID deliver whose content breaks the generation contract: the producer's output is invalid, a permanent and auditable outcome.
CONTENT_FAULTS = frozenset({"live_reply_not_json", "live_answers_invalid", "live_output_truncated", "live_model_refusal", "live_model_mismatch"})
PRODUCER_INVALID = CONTENT_FAULTS | {"producer-invalid"}
CHECK_DECISIONS = (*jev.CHECK_OPTIONS, "uncertain")

_SQL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, input_digest TEXT NOT NULL, request TEXT NOT NULL, binding TEXT NOT NULL,
 state TEXT NOT NULL, phase TEXT NOT NULL, failure TEXT, detail TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calls(attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id), stage TEXT NOT NULL, request_digest TEXT NOT NULL,
 fixture_hash TEXT NOT NULL, state TEXT NOT NULL, response TEXT, response_digest TEXT, verdict TEXT, started_at TEXT NOT NULL, received_at TEXT,
 UNIQUE(job_id,stage));
CREATE TABLE IF NOT EXISTS refusals(attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id), code TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS results(job_id TEXT PRIMARY KEY REFERENCES jobs(job_id), outcome TEXT NOT NULL, body TEXT NOT NULL, result_digest TEXT NOT NULL,
 created_at TEXT NOT NULL);
"""
_IMMUTABLE = ("meta", "refusals", "results")
_FILES = {"issue-summary.sqlite3", "issue-summary.sqlite3-wal", "issue-summary.sqlite3-shm", "issue-summary.lock"}


# ---------------------------------------------------------------------------------------------------- wire ----------------------

class Submit(Wire):
    """One summary job over one PUBLIC issue of the handoff `manifest` (exactly the operator's `zoop-ai-handoff freeze` request). `mode` must equal the
    execution mode the manifest's sources really ran (`provenance_mode_conflict` otherwise)."""
    schema_version: Literal["zoop-issue-summary-1"]
    job_id: str = Field(pattern=ID_PATTERN)
    issue_id: str = Field(pattern=ID_PATTERN)
    mode: Literal["replay", "live"]
    manifest: Manifest


class Selector(Wire):
    schema_version: Literal["zoop-issue-summary-1"]
    job_id: str = Field(pattern=ID_PATTERN)


class FixtureRecord(Wire):
    stage: Literal["issue-summary", "verify-issue-summary"]
    request_digest: str = Field(pattern=HASH_PATTERN)
    response: dict[str, Any]


class FixtureDoc(Wire):
    """Authored replay: each response answers ONE exact native stage payload (keyed by its digest). `issue-summary` records hold the model reply
    (`{"claims": [{"text", "quoteIds": ["q1", ...]}]}` with positional labels), `verify-issue-summary` records the interpreted verifier answer."""
    format: Literal["zoop-issue-summary-fixture-1"]
    synthetic: bool
    recording_kind: Literal["authored-test"]
    records: list[FixtureRecord] = Field(max_length=2000)

    @model_validator(mode="after")
    def unique(self):
        keys = [(r.stage, r.request_digest) for r in self.records]
        if len(set(keys)) != len(keys):
            raise ValueError("fixture records")
        return self


class Fixtures:
    """Authored replay for this process only; its hash is recorded on the call it answered, its bytes are never authority."""

    def __init__(self, raw: bytes | None):
        self.loaded = None
        if raw is not None:
            try:
                doc = FixtureDoc.model_validate_json(raw)
            except ValueError as exc:
                raise ExtractionFailure("issue_summary_fixture_invalid") from exc
            self.loaded = (doc, byte_hash(raw), {(r.stage, r.request_digest): r.response for r in doc.records})

    @property
    def provided(self) -> bool:
        return self.loaded is not None

    def find(self, stage: str, key: str, synthetic: bool) -> tuple[dict, str]:
        detail = {"stage": stage, "requestDigest": key}
        if self.loaded is None:
            raise ExtractionFailure("replay_fixture_required", detail)
        doc, fixture_hash, records = self.loaded
        if doc.synthetic != synthetic:
            raise ExtractionFailure("replay_provenance_conflict")
        if (stage, key) not in records:
            raise ExtractionFailure("replay_fixture_missing", detail)
        return records[(stage, key)], fixture_hash


# ---------------------------------------------------------------------------------------------------- ledger --------------------

class Store:
    """The summary ledger (`issue-summary.sqlite3` + `issue-summary.lock`), same rules as the other pipeline ledgers: a dedicated directory disjoint from the
    app, S1 and every source ledger, no symlinks, 0700/0600, one exclusive non-blocking writer lock, WAL + synchronous=FULL. mode `read` takes a shared
    lock, opens the file immutable and read-only, creates nothing and refuses a hot WAL (a writer command settles it first)."""

    def __init__(self, root: Path, *upstream_roots: Path, mode: str = "write"):
        root = Path(os.path.abspath(root))
        forbidden = [*reserved_state_roots(), *(Path(os.path.abspath(p)) for p in upstream_roots)]
        if any(root == p or root.is_relative_to(p) or p.is_relative_to(root) for p in forbidden):
            raise ExtractionFailure("state_namespace_conflict")
        for parent in [*reversed(root.parents), root]:
            if parent.exists() and parent.is_symlink():
                raise ExtractionFailure("state_namespace_invalid")
        if mode == "read":
            self._open_existing(root)
            return
        fresh = not root.exists() or (root.is_dir() and not any(root.iterdir()))          # only an absent path or an EMPTY directory is a new ledger
        if root.exists():
            if not root.is_dir() or any(p.name not in _FILES or p.is_symlink() for p in root.iterdir()):
                raise ExtractionFailure("state_namespace_conflict")
            if not fresh and not all((root / name).is_file() for name in ("issue-summary.sqlite3", "issue-summary.lock")):
                # A partial ledger (history lost) is never recreated: a retried job id would run, and send, again.
                raise ExtractionFailure("issue_summary_state_partial")
        else:
            root.mkdir(mode=0o700, parents=True)
        self.lock = os.open(root / "issue-summary.lock", os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if fresh else 0), 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.lock)
            del self.lock
            raise ExtractionFailure("issue_summary_busy") from exc
        try:
            database = root / "issue-summary.sqlite3"
            fd = os.open(database, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if fresh else 0), 0o600)
            os.close(fd)
            self.db = sqlite3.connect(database, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            if not fresh:
                # An established ledger proves itself BEFORE any pragma, schema or marker write: an empty or foreign database is never initialised as new history.
                try:
                    marker = self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
                except sqlite3.DatabaseError as exc:
                    raise ExtractionFailure("issue_summary_state_invalid") from exc
                if marker is None or marker["value"] != LEDGER_VERSION:
                    raise ExtractionFailure("issue_summary_ledger_unknown")
            os.fchmod(self.lock, 0o600)
            os.chmod(root, 0o700)
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(_SQL)
            for table in _IMMUTABLE:
                for op in ("UPDATE", "DELETE"):
                    self.db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_jobs_delete BEFORE DELETE ON jobs BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_jobs_input BEFORE UPDATE OF job_id,request_digest,input_digest,request,binding,created_at ON jobs "
                            "BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS terminal_jobs_state BEFORE UPDATE OF state,phase,failure,detail ON jobs WHEN OLD.state IN ('ready','failed') "
                            "BEGIN SELECT RAISE(ABORT,'terminal'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_calls_delete BEFORE DELETE ON calls BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_calls_identity BEFORE UPDATE OF job_id,stage,request_digest,fixture_hash,started_at ON calls "
                            "BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_calls_receipt BEFORE UPDATE OF response,response_digest,received_at ON calls "
                            "WHEN OLD.response IS NOT NULL BEGIN SELECT RAISE(ABORT,'immutable receipt'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_calls_verdict BEFORE UPDATE OF verdict ON calls WHEN OLD.verdict IS NOT NULL "
                            "BEGIN SELECT RAISE(ABORT,'immutable verdict'); END")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('ledger',?)", (LEDGER_VERSION,))
            if self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()["value"] != LEDGER_VERSION:
                raise ExtractionFailure("issue_summary_ledger_unknown")
            for p in root.iterdir():
                os.chmod(p, 0o600)
        except BaseException:
            self.close()
            raise

    def _open_existing(self, root: Path) -> None:
        database, lock = root / "issue-summary.sqlite3", root / "issue-summary.lock"
        if not root.is_dir() or not database.is_file() or not lock.is_file() or database.is_symlink() or lock.is_symlink():
            raise ExtractionFailure("issue_summary_state_missing")
        if any(p.name not in _FILES or p.is_symlink() for p in root.iterdir()):
            raise ExtractionFailure("state_namespace_conflict")
        self.lock = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.close()
            raise ExtractionFailure("issue_summary_busy") from exc
        try:
            wal = root / "issue-summary.sqlite3-wal"
            if wal.exists() and wal.stat().st_size > 0:
                raise ExtractionFailure("issue_summary_recovery_required")
            self.db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA query_only=ON")
            self.db.execute("SELECT 1 FROM jobs LIMIT 1")
            meta = self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
            if meta is None or meta["value"] != LEDGER_VERSION:
                raise ExtractionFailure("issue_summary_ledger_unknown")
        except sqlite3.DatabaseError as exc:
            self.close()
            raise ExtractionFailure("issue_summary_state_invalid") from exc
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if hasattr(self, "db"):
            self.db.close()
            del self.db
        if hasattr(self, "lock"):
            os.close(self.lock)
            del self.lock

    @contextmanager
    def transaction(self, guard=None):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            if guard:
                guard()
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def one(self, sql, args=()):
        return self.db.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()


# ---------------------------------------------------------------------------------------------------- pure payloads ------------

def producer_payload(basis: dict, texts: dict[str, str]) -> dict:
    """The native `issue-summary` stage payload: the basis title and every basis quote (in basis order) with its exact text. `texts` maps evidence id -> the
    quoted text. Its digest is the request identity of the generation call (and the key of an authored replay record)."""
    return {"issueTitle": basis["title"], "quotes": [{"quoteId": q["evidenceId"], "context": q["context"], "text": texts[q["evidenceId"]]} for q in basis["quotes"]]}


def verifier_payload(payload: dict, claims: list[dict]) -> dict:
    """The native `verify-issue-summary` stage payload: the claims with the quotes they cite (only those, with the same `context` the producer saw), in payload order."""
    cited = {i for c in claims for i in c["evidenceIds"]}
    return {"quotes": [{"quoteId": q["quoteId"], "context": q["context"], "text": q["text"]} for q in payload["quotes"] if q["quoteId"] in cited],
            "claims": [{"claimId": c["claimId"], "text": c["text"], "quoteIds": list(c["evidenceIds"])} for c in claims]}


def answer_closed(answer: Any, claims: list[dict]) -> bool:
    """The interpreted verifier answer is exactly the asked shape: one decision per produced claim in order, closed key sets, known decision values."""
    try:
        return (set(answer) == {"claims", "prohibitedAdvice", "unsupportedCausality", "backgroundAsCurrent"} and isinstance(answer["claims"], list)
                and [c["claimId"] for c in answer["claims"]] == [c["claimId"] for c in claims]
                and all(set(c) == {"claimId", "decision", "reason"} and c["decision"] in jev.CLAIM_OPTIONS and isinstance(c["reason"], str) for c in answer["claims"])
                and all(answer[k] in CHECK_DECISIONS for k in ("prohibitedAdvice", "unsupportedCausality", "backgroundAsCurrent")))
    except (KeyError, TypeError):
        return False


# ---------------------------------------------------------------------------------------------------- engine ------------------

@dataclass
class Context:
    request: Submit
    planned: Any              # handoff.PlannedIssue, read NOW
    basis: dict
    basis_digest: str
    payload: dict
    refs: list                # ObservationRef of every document of the basis (what a send discloses)
    live: bool
    synthetic: bool


@dataclass
class Exchange:
    attempt: str
    key: str
    raw: dict                 # the persisted receipt (live) or the authored response (replay)
    fixture_hash: str
    verdict: str | None


class Unusable(ExtractionFailure):
    """A call's outcome is not a usable judgment and the call is consumed: the job is terminal (`failed`); another call needs a new job."""


class Engine:
    def __init__(self, store: Store, plan: Callable[[Manifest, str], Any], runtime_factory: Callable[..., LiveRuntime] | None = None):
        """`plan(manifest, issue_id)` is the handoff's read-only `plan_summary_input` (no ledger, no artifact, no provider). `runtime_factory(need_send=bool)`
        builds the issue-summary live runtime lazily and only for a live job."""
        self.store, self.plan, self.db = store, plan, store.db
        self.runtime_factory = runtime_factory
        self._runtimes: dict[bool, LiveRuntime] = {}
        self._phase = "produce"

    # seams for process-level crash tests (no production effect)
    def _after_reserve(self, stage: str) -> None:
        """Called once the attempt is durably `started` and before the provider is contacted."""

    def _after_send(self, stage: str) -> None:
        """Called once the provider replied and before its receipt is stored."""

    def _after_receipt(self, stage: str) -> None:
        """Called once the receipt is durable and before anything decodes it."""

    # ------------------------------------------------------------------ planning ----------------------------------------

    def _context(self, request: Submit) -> Context:
        """The exact input NOW, from the handoff planner. Deterministic rejections come first and never reach a ledger row or a provider."""
        planned = self.plan(request.manifest, request.issue_id)
        issue = planned.issue
        if issue["id"] != request.issue_id:
            raise ExtractionFailure("issue_not_public")
        basis = summary_basis(issue, planned.evidence, planned.articles)
        code = deterministic_code(issue, basis)
        if code == TEMPORAL_PENDING:
            raise ExtractionFailure("issue_temporal_review_pending")
        if code == INPUT_TOO_LARGE:
            raise ExtractionFailure("issue_summary_input_too_large")
        if tuple(planned.execution) != (("live", "provider") if request.mode == "live" else ("replay", "authored-test")):
            raise ExtractionFailure("provenance_mode_conflict")
        articles = {(a["articleId"], a["articleVersion"]): a for a in basis["articles"]}
        texts = {}
        for q in basis["quotes"]:
            article = articles[(q["articleId"], q["articleVersion"])]
            found = planned.documents.get((article["documentId"], article["documentVersion"]))
            if not found:
                raise ExtractionFailure("issue_summary_source_missing")
            text = found[0][1]["document"]["text"]
            piece = text[q["start"]:q["end"]]
            if text_sha256(text) != article["textSha256"] or not 0 <= q["start"] < q["end"] <= len(text) or text_sha256(piece) != q["quoteSha256"]:
                raise ExtractionFailure("issue_summary_quote_mismatch")
            texts[q["evidenceId"]] = piece
        payload = producer_payload(basis, texts)
        try:
            prompts.quote_labels(payload)
        except ValueError:
            raise ExtractionFailure("issue_summary_payload_invalid") from None
        refs = [ref for key in sorted({(a["documentId"], a["documentVersion"]) for a in basis["articles"]}) for ref, _ in planned.documents[key]]
        return Context(request, planned, basis, basis_digest(basis), payload, refs, request.mode == "live", planned.source_kind == "synthetic")

    def _binding(self, ctx: Context) -> dict:
        """Frozen identity of the input (replay-identical); a live job adds the secret-free runtime binding at freeze only."""
        spec = prompts.SPECS[PRODUCE]
        execution, recording = ctx.planned.execution
        return {"schema": SCHEMA, "policy": POLICY, "issueId": ctx.request.issue_id, "basis": ctx.basis, "basisDigest": ctx.basis_digest,
                "provenance": {"sourceKind": ctx.planned.source_kind, "executionMode": execution, "recordingKind": recording},
                "producer": {"stage": PRODUCE, "revision": prompts.REVISION, "promptVersion": spec.prompt_version, "schemaDigest": spec.schema_digest},
                "verifier": {"stage": VERIFY, "adapterRevision": jev.ADAPTER_REVISION, "adapterIdentity": jev.identity()}}

    def _check_binding(self, ctx: Context, row) -> None:
        stored = json.loads(row["binding"])
        runtime = stored.pop("runtime", None)
        if (runtime is not None) != ctx.live:
            raise ExtractionFailure("job_binding_changed")
        fresh = self._binding(ctx)
        if fresh != stored:
            raise ExtractionFailure("issue_summary_basis_changed" if fresh["basisDigest"] != stored["basisDigest"] else "job_binding_changed")

    def _authorize(self, ctx: Context, runtime: LiveRuntime, stage: str) -> None:
        """Current model-send authority (operation, this stage's purpose and recipient) for EVERY document of the basis: the title and quotes come from all of them."""
        purpose, recipient = runtime.purpose(stage), runtime.recipient(stage)
        for ref in ctx.refs:
            ctx.planned.sources.authorize_model_send(ref, purpose, recipient)

    def _verify(self, ctx: Context, runtime: LiveRuntime | None = None, stage: str | tuple[str, ...] | None = None) -> None:
        """The input and its authority as they are NOW: a fresh plan (pinned sources, read and quote-display rights, no HOLD/REJECT time verdict, same mode)
        must give the exact frozen basis; with `runtime` also model-send rights for `stage` (one stage or several). Any change fails closed: nothing is
        silently refreshed."""
        fresh = self._context(ctx.request)
        if fresh.basis_digest != ctx.basis_digest:
            raise ExtractionFailure("issue_summary_basis_changed")
        if runtime is not None:
            for each in (stage,) if isinstance(stage, str) else stage:
                self._authorize(fresh, runtime, each)

    # ------------------------------------------------------------------ live runtime ------------------------------------

    def _build_runtime(self, send: bool) -> LiveRuntime:
        if self.runtime_factory is None:
            raise ExtractionFailure("live_runtime_unavailable")
        if send not in self._runtimes:
            try:
                runtime = self.runtime_factory(need_send=send)
            except LiveFailure as exc:
                raise ExtractionFailure(exc.code) from exc
            if runtime.family.version != ISSUE_SUMMARY.version:
                raise ExtractionFailure("live_binding_mismatch")
            self._runtimes[send] = runtime
        return self._runtimes[send]

    def _runtime(self, row, *, send: bool) -> LiveRuntime:
        """The runtime of a live job. `send=False` is rebuilt PURELY from the frozen binding (decoding saved receipts needs no key, budget or environment).
        `send=True` is the environment runtime, and only while it still equals the frozen binding."""
        frozen = json.loads(row["binding"])["runtime"]
        if not send:
            try:
                runtime = LiveRuntime.from_binding(frozen)
            except LiveFailure as exc:
                raise ExtractionFailure(exc.code) from exc
            if runtime.family.version != ISSUE_SUMMARY.version:
                raise ExtractionFailure("live_binding_mismatch")
            return runtime
        runtime = self._build_runtime(True)
        if not runtime.accepts(frozen):
            raise ExtractionFailure("live_config_changed")
        return runtime

    @staticmethod
    def _is_live(row) -> bool:
        return json.loads(row["request"])["mode"] == "live"

    # ------------------------------------------------------------------ commands ----------------------------------------

    def _job(self, job_id: str):
        row = self.store.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        if row is None:
            raise ExtractionFailure("job_not_found")
        return row

    def freeze(self, request: Submit) -> None:
        """The only registration path: read the exact input through the planner and durably freeze it as `queued`: no call, no execution, no handoff effect.

        A job that already exists is not touched at all: the same request returns without reading anything, another request under its id is
        `job_input_conflict` with nothing written. A held/rejected time field is `issue_temporal_review_pending`, an oversized input
        `issue_summary_input_too_large`, a mode that is not the sources' `provenance_mode_conflict`: all before any row exists. A second job over the exact
        same input while another one is not `failed` is `issue_summary_input_duplicate` (the finished result is reused by pinning it, never re-run)."""
        request_digest = digest(request.wire())
        row = self.store.one("SELECT * FROM jobs WHERE job_id=?", (request.job_id,))
        if row is not None:
            if row["request_digest"] != request_digest:
                raise ExtractionFailure("job_input_conflict")
            return
        ctx = self._context(request)
        binding = self._binding(ctx)
        if ctx.live:
            runtime = self._build_runtime(False)
            binding["runtime"] = runtime.binding()
            try:
                runtime.prepare(PRODUCE, ctx.payload)         # pure: the request must fit the provider limits BEFORE a job exists
            except LiveFailure as exc:
                raise ExtractionFailure("issue_summary_input_too_large" if exc.code == "live_request_too_large" else exc.code) from exc
        input_digest = digest(binding)

        def guard() -> None:
            self._verify(ctx)
            twin = self.store.one("SELECT job_id FROM jobs WHERE input_digest=? AND state!='failed' AND job_id!=?", (input_digest, request.job_id))
            if twin is not None:
                raise ExtractionFailure("issue_summary_input_duplicate", {"jobId": twin["job_id"]})

        with self.store.transaction(guard):
            self.db.execute("INSERT INTO jobs(job_id,request_digest,input_digest,request,binding,state,phase,created_at,updated_at) VALUES(?,?,?,?,?,'queued','produce',?,?)",
                (request.job_id, request_digest, input_digest, canonical(request.wire()), canonical(binding), now(), now()))

    def run(self, request: Submit, fixtures: Fixtures) -> dict:
        """Convenience: `freeze` then `resume` the same job."""
        self.freeze(request)
        return self.resume(request.job_id, fixtures)

    def resume(self, job_id: str, fixtures: Fixtures) -> dict:
        """Execute (or recover) the job from its stored receipts. A `ready` or `failed` job is returned as it is: nothing is re-planned, re-verified or re-called."""
        row = self._job(job_id)
        if self._is_live(row) and fixtures.provided:
            raise ExtractionFailure("fixture_not_allowed")
        self._execute(row, fixtures)
        return self.result(job_id)

    def inspect(self, job_id: str) -> dict:
        self._job(job_id)
        return self.result(job_id)

    def cancel(self, job_id: str) -> dict:
        """Release a job that cannot finish (a `queued` or `stopped` job, e.g. bound to a manifest whose pinned files or review state moved): it becomes `failed`
        (`job_cancelled`, terminal) and no longer holds its input, so a NEW job under the current manifest can be submitted. Stored receipts stay as audit; a
        `ready` or `failed` job is refused (`job_already_terminal`). Calls nothing, reads no source."""
        row = self._job(job_id)
        if row["state"] in {"ready", "failed"}:
            raise ExtractionFailure("job_already_terminal", {"state": row["state"]})
        self._status(job_id, "failed", row["phase"], "job_cancelled")
        return self.result(job_id)

    # ------------------------------------------------------------------ execution ---------------------------------------

    def _status(self, job_id: str, state: str, phase: str, failure: str | None = None, detail: dict | None = None) -> None:
        self.db.execute("UPDATE jobs SET state=?,phase=?,failure=?,detail=?,updated_at=? WHERE job_id=?",
            (state, phase, failure, canonical(detail) if detail else None, now(), job_id))

    def _unknown_calls(self, job_id: str) -> list:
        """Started calls with no receipt whose transmission is UNKNOWN (never one definitively refused before it was sent)."""
        return self.store.all("SELECT attempt_id FROM calls WHERE job_id=? AND state='started' AND response IS NULL AND attempt_id NOT IN (SELECT attempt_id FROM refusals)",
                              (job_id,))

    def _execute(self, row, fixtures: Fixtures) -> None:
        job_id = row["job_id"]
        if row["state"] in {"ready", "failed"}:
            return
        if self._unknown_calls(job_id):
            # Holding the ledger lock proves the previous process stopped, not that its call was never sent: never resend.
            self._status(job_id, "failed", row["phase"], "provider_outcome_unknown")
            return
        self._status(job_id, "running", row["phase"])
        try:
            ctx = self._context(Submit.model_validate_json(row["request"]))
            self._check_binding(ctx, row)
        except ExtractionFailure as exc:
            self._status(job_id, "stopped", row["phase"], exc.code, exc.detail)
            return
        self._finish(row, ctx, fixtures)

    def _finish(self, row, ctx: Context, fixtures: Fixtures) -> None:
        job_id = row["job_id"]
        try:
            body = self._work(row, ctx, fixtures)
            self._complete(row, ctx, body)
        except ProviderResponseUnknown:
            # A request may have reached the provider: terminal and never resent. The operator submits a NEW job (a new, explicit spend) after investigating.
            self._status(job_id, "failed", self._phase, "provider_outcome_unknown")
        except Unusable as exc:
            self._status(job_id, "failed", self._phase, exc.code, exc.detail)
        except ExtractionFailure as exc:
            self._status(job_id, "stopped", self._phase, exc.code, exc.detail)
        except (sqlite3.Error, OSError):
            self._status(job_id, "stopped", self._phase, "persistence_failed")

    def _complete(self, row, ctx: Context, body: dict) -> None:
        """The result and the `ready` state commit together, under the current input and rights."""
        job_id, created = row["job_id"], now()
        # The last gate before a result exists: every stage that sent something this result rests on must still be authorized NOW, not only the stage answered last.
        used = tuple(stage for stage in STAGES if self.store.one("SELECT 1 FROM calls WHERE job_id=? AND stage=? AND state='received'", (job_id, stage)))
        with self.store.transaction(lambda: self._verify(ctx, self._runtime(row, send=False) if ctx.live else None, used)):
            self.db.execute("INSERT INTO results VALUES(?,?,?,?,?)",
                (job_id, "available" if body["status"] == "available" else body["code"], canonical(body),
                 result_digest(job_id, row["input_digest"], ctx.basis_digest, body), created))
            self._status(job_id, "ready", "complete")

    def _work(self, row, ctx: Context, fixtures: Fixtures) -> dict:
        """Generation, then verification; returns the result body. A usable-but-negative outcome is a withheld body, an unusable one raises."""
        binding = json.loads(row["binding"])
        self._phase = "produce"
        produced = self._produce(row, ctx, fixtures)
        if produced is None:
            return withheld_body("producer-invalid")
        claims, first = produced
        self._phase = "verify"
        payload = verifier_payload(ctx.payload, claims)
        second = self._exchange(row, ctx, fixtures, VERIFY, payload)
        runtime = self._runtime(row, send=False) if ctx.live else None
        if second.verdict:
            raise Unusable("verification_unavailable", {"stage": VERIFY, "code": second.verdict})
        try:
            answer = self._decode(runtime, VERIFY, second)
            if not answer_closed(answer, claims):
                raise LiveFailure("verifier_reply_invalid")
        except LiveFailure as exc:
            self._mark(second.attempt, exc.code)
            raise Unusable("verification_unavailable", {"stage": VERIFY, "code": exc.code}) from exc
        verdict = jev.outcome(answer)
        if verdict != "available":
            return withheld_body(verdict)
        producer = {"kind": "provider" if ctx.live else "authored-replay", "model": None, "reasoningEffort": None, "promptVersion": binding["producer"]["promptVersion"],
                    "schemaDigest": binding["producer"]["schemaDigest"], "runtimeIdentity": first.fixture_hash}
        verifier = {"kind": "independent-verifier" if ctx.live else "authored-replay", "model": None, "adapterIdentity": binding["verifier"]["adapterIdentity"],
                    "requestDigest": second.key}
        if ctx.live:
            producer.update(model=first.raw["model"]["requested"], reasoningEffort=binding["runtime"]["generation"]["reasoningEffort"],
                            runtimeIdentity=binding["runtime"]["identity"])
            verifier.update(model=second.raw["model"]["requested"], requestDigest=second.raw["requestDigest"])
        return available_body(ctx.basis_digest, claims, now(), producer, verifier)

    def _produce(self, row, ctx: Context, fixtures: Fixtures) -> tuple[list[dict], Exchange] | None:
        """The claims of a usable generation reply, or None when the producer's output is invalid (permanent, auditable, no verifier call)."""
        first = self._exchange(row, ctx, fixtures, PRODUCE, ctx.payload)
        if first.verdict:
            if first.verdict in PRODUCER_INVALID:
                return None
            raise Unusable(first.verdict)
        runtime = self._runtime(row, send=False) if ctx.live else None
        try:
            return prompts.claims_from(self._decode(runtime, PRODUCE, first), ctx.payload), first
        except LiveFailure as exc:
            self._mark(first.attempt, exc.code)
            if exc.code in CONTENT_FAULTS:
                return None
            raise Unusable(exc.code) from exc
        except ValueError:
            self._mark(first.attempt, "producer-invalid")
            return None

    @staticmethod
    def _decode(runtime: LiveRuntime | None, stage: str, ex: Exchange) -> Any:
        """The stage's native answer from the persisted receipt (live: strict pure decode, never a network call) or the authored response (replay)."""
        return ex.raw if runtime is None else runtime.answer(stage, ex.raw)

    # ------------------------------------------------------------------ one provider-style exchange ---------------------

    def _exchange(self, row, ctx: Context, fixtures: Fixtures, stage: str, payload: dict) -> Exchange:
        """One attempt over the native stage `payload` (its digest is the request identity; at most one per stage and job).

        Replay: the authored reply is located BEFORE a call is recorded, and recorded as received in the same transaction (no unknown window). Live:
        prepare, check model-send rights of every document, reserve durably, send once, persist the raw receipt BEFORE decoding. A saved receipt is never
        re-fetched; a started call without a receipt is unknown and never resent. After the reply (fresh or saved) the rights are checked again: a stored
        receipt is never used while the authority behind it is gone."""
        job_id, key = row["job_id"], digest(payload)
        call = self.store.one("SELECT * FROM calls WHERE job_id=? AND stage=?", (job_id, stage))
        if call is not None and call["state"] == "started" and call["response"] is None and self.store.one("SELECT 1 FROM refusals WHERE attempt_id=?", (call["attempt_id"],)):
            call = None  # definitively never sent: `_reserve` re-arms the same row under a new attempt id
        if call is None:
            if ctx.live:
                ex = self._send(row, ctx, stage, key, payload)
            else:
                raw, fixture_hash = fixtures.find(stage, key, ctx.synthetic)
                ex = self._record(job_id, stage, key, raw, fixture_hash)
        else:
            if call["request_digest"] != key:
                raise ExtractionFailure("receipt_request_mismatch")
            if call["state"] != "received":
                raise ProviderResponseUnknown("provider_outcome_unknown")
            raw = json.loads(call["response"])
            if digest(raw) != call["response_digest"] or (ctx.live and (not isinstance(raw, dict) or raw.get("attemptId") != call["attempt_id"])):
                raise ExtractionFailure("receipt_integrity_failed")
            ex = Exchange(call["attempt_id"], key, raw, call["fixture_hash"], call["verdict"])
        self._verify(ctx, self._runtime(row, send=False) if ctx.live else None, stage)
        return ex

    def _record(self, job_id: str, stage: str, key: str, raw: dict, fixture_hash: str) -> Exchange:
        attempt = "attempt-" + uuid.uuid4().hex
        with self.store.transaction():
            self.db.execute("INSERT INTO calls(attempt_id,job_id,stage,request_digest,fixture_hash,state,response,response_digest,started_at,received_at) "
                            "VALUES(?,?,?,?,?,'received',?,?,?,?)", (attempt, job_id, stage, key, fixture_hash, canonical(raw), digest(raw), now(), now()))
        return Exchange(attempt, key, raw, fixture_hash, None)

    def _reserve(self, job_id: str, stage: str, key: str, fixture_hash: str) -> str:
        """The durable attempt record, written BEFORE anything is sent. A call definitively refused before sending is re-armed under a new attempt id
        (same row, same request); any other existing call is never re-reserved."""
        attempt = "attempt-" + uuid.uuid4().hex
        with self.store.transaction():
            old = self.store.one("SELECT attempt_id,request_digest,state,response FROM calls WHERE job_id=? AND stage=?", (job_id, stage))
            if old is None:
                self.db.execute("INSERT INTO calls(attempt_id,job_id,stage,request_digest,fixture_hash,state,started_at) VALUES(?,?,?,?,?,'started',?)",
                    (attempt, job_id, stage, key, fixture_hash, now()))
            elif (old["request_digest"] != key or old["state"] != "started" or old["response"] is not None
                  or not self.store.one("SELECT 1 FROM refusals WHERE attempt_id=?", (old["attempt_id"],))):
                raise ExtractionFailure("receipt_request_mismatch")
            else:
                self.db.execute("UPDATE calls SET attempt_id=? WHERE attempt_id=?", (attempt, old["attempt_id"]))
        return attempt

    def _refuse(self, job_id: str, attempt: str, code: str) -> None:
        """Durably record that this attempt was refused BEFORE any transmission (it is not an unknown call)."""
        self.db.execute("INSERT OR IGNORE INTO refusals VALUES(?,?,?,?)", (attempt, job_id, code, now()))

    def _mark(self, attempt: str, code: str) -> None:
        self.db.execute("UPDATE calls SET verdict=? WHERE attempt_id=? AND verdict IS NULL", (code, attempt))

    def _send(self, row, ctx: Context, stage: str, key: str, payload: dict) -> Exchange:
        """Live transmission. Ordering: pure prepare -> current model-send rights for every document -> durable reservation -> the runtime reserves budget,
        calls `authorize` immediately before sending and sends once -> the raw receipt is persisted before anything parses it. A transport failure leaves the
        reservation `started` (unknown, never resent); a refusal before the socket is recorded as such."""
        job_id = row["job_id"]
        runtime = self._runtime(row, send=True)
        try:
            prepared = runtime.prepare(stage, payload)
        except LiveFailure as exc:
            raise ExtractionFailure(exc.code) from exc
        self._verify(ctx, runtime, stage)
        attempt = self._reserve(job_id, stage, key, digest(json.loads(row["binding"])["runtime"]))
        self._after_reserve(stage)

        def authorize() -> None:
            self._verify(ctx, runtime, stage)

        try:
            receipt = runtime.send(prepared, attempt_id=attempt, authorize=authorize)
        except LiveFailure as exc:
            if exc.uncertain:
                raise ProviderResponseUnknown("provider_outcome_unknown") from exc
            self._refuse(job_id, attempt, exc.code)
            raise ExtractionFailure(exc.code) from exc
        except ExtractionFailure as exc:
            self._refuse(job_id, attempt, exc.code)
            raise
        self._after_send(stage)
        self.db.execute("UPDATE calls SET state='received',response=?,response_digest=?,received_at=? WHERE attempt_id=? AND state='started'",
            (canonical(receipt), digest(receipt), now(), attempt))
        self._after_receipt(stage)
        return Exchange(attempt, key, receipt, digest(json.loads(row["binding"])["runtime"]), None)

    # ------------------------------------------------------------------ result ------------------------------------------

    def result(self, job_id: str) -> dict:
        """The job as the ledger holds it: identity, state, failure and accounting always; for a `ready` job also the stored `result` (outcome, result digest and the exact
        bundle `summary` value) ONLY while `delivery.status` is `current` (see `_delivery`). A withheld delivery keeps everything else and carries a stable code, never text.
        No provider is touched, and no call is ever made here."""
        row = self._job(job_id)
        request = json.loads(row["request"])
        binding = json.loads(row["binding"])
        live = request["mode"] == "live"
        calls = self.store.all("SELECT * FROM calls WHERE job_id=? ORDER BY started_at,stage", (job_id,))
        refused = {r["attempt_id"]: r["code"] for r in self.store.all("SELECT attempt_id,code FROM refusals WHERE job_id=?", (job_id,))}
        received = sum(c["state"] == "received" for c in calls)
        unknown = sum(c["state"] == "started" and c["attempt_id"] not in refused for c in calls)
        out = {"schemaVersion": SCHEMA, "jobId": job_id, "inputDigest": row["input_digest"], "issueId": binding["issueId"], "state": row["state"], "phase": row["phase"],
               "failure": {"code": row["failure"], **({"detail": json.loads(row["detail"])} if row["detail"] else {})} if row["failure"] else None,
               "provenance": binding["provenance"], "basis": {"digest": binding["basisDigest"], "quotes": len(binding["basis"]["quotes"]),
                                                              "articles": len(binding["basis"]["articles"])},
               "usage": {"executionMode": "live" if live else "replay", "replayCalls": 0 if live else received, "startedWithoutReceipt": unknown,
                         "providerCalls": received + unknown if live else 0, "modelCalls": received + unknown if live else 0, "creatorJobId": job_id},
               "calls": [{"stage": c["stage"], "state": "refused" if c["state"] == "started" and c["attempt_id"] in refused else c["state"], "requestDigest": c["request_digest"],
                          "fixtureHash": c["fixture_hash"], "responseDigest": c["response_digest"], "verdict": c["verdict"] or refused.get(c["attempt_id"]),
                          **({"cost": self._cost(c)} if live and c["state"] == "received" else {})} for c in calls],
               "delivery": {"status": "not-ready"}, "result": None}
        found = self.store.one("SELECT * FROM results WHERE job_id=?", (job_id,))
        if found is not None:
            summary = _summary(row, binding, found)                  # the stored result proves itself first (a damaged row is an error, never content)
            out["delivery"] = self._delivery(row)
            if out["delivery"]["status"] == "current":
                out["result"] = {"outcome": found["outcome"], "resultDigest": found["result_digest"], "summary": summary}
        return out

    def _delivery(self, row) -> dict:
        """May the stored result of this `ready` job be shown NOW? Same rule as the S2/S3 results: the CURRENT source read + quote-display rights, the pinned
        sources/files and the exact frozen basis are re-proven through a fresh plan; anything else (revoked, missing, moved, changed) withholds the content with a
        stable code while the identity, state and usage stay. `ready` is not deliverable by itself. Model-send rights are NOT re-read here: they gate the send, the
        reply and the completion of the run, never a later read of an immutable result."""
        if self.plan is None:
            return {"status": "withheld", "code": "delivery_unproven"}
        try:
            ctx = self._context(Submit.model_validate_json(row["request"]))
            self._check_binding(ctx, row)
        except (ExtractionFailure, IngestionFailure) as exc:
            return {"status": "withheld", "code": exc.code}
        return {"status": "current", "authority": "source read and quote-display rights, pinned sources and the exact frozen basis verified now"}

    @staticmethod
    def _cost(call) -> dict | None:
        try:
            receipt = json.loads(call["response"])
            return {"usageKnown": receipt["cost"]["usageKnown"], "estimatedUsd": receipt["cost"]["estimatedUsd"], "chargedUsd": receipt["cost"]["chargedUsd"]}
        except (KeyError, TypeError, ValueError):
            return None


def _summary(row, binding: dict, found) -> dict:
    """The exact bundle `issues[].summary` of a stored result, proven against its own digests (a damaged or hand-edited row is `issue_summary_state_invalid`)."""
    body = json.loads(found["body"])
    ok = (digest(binding) == row["input_digest"] and found["result_digest"] == result_digest(row["job_id"], row["input_digest"], binding["basisDigest"], body)
          and found["outcome"] == ("available" if body.get("status") == "available" else body.get("code"))
          and (body.get("status") == "available" or body.get("code") in JOB_CODES))
    if not ok:
        raise ExtractionFailure("issue_summary_state_invalid")
    return assemble(row["job_id"], row["input_digest"], binding["basisDigest"], body)


# ---------------------------------------------------------------------------------------------------- read seam --------------

@dataclass(frozen=True)
class ReadyResult:
    """One finished job as the handoff consumes it. `summary` is EXACTLY the bundle `issues[].summary` value; `issue_id` the PUBLIC id it summarises."""
    job_id: str
    input_digest: str
    result_digest: str
    issue_id: str
    execution: tuple[str, str]
    source_kind: str
    summary: dict


def load_result(state_dir: Path, *upstream_roots: Path, job_id: str) -> ReadyResult:
    """Read-only (shared lock, immutable SQLite; nothing is created, chmodded or recovered; a hot WAL is `issue_summary_recovery_required`). Only a `ready`
    job (available or withheld) is a result; an unknown job is `issue_summary_not_found`, any other state `issue_summary_not_ready`. The stored input and result
    digests are re-proven; the caller still proves the pin, the basis, the mode and the rights itself."""
    store = Store(state_dir, *upstream_roots, mode="read")
    try:
        row = store.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        if row is None:
            raise ExtractionFailure("issue_summary_not_found")
        if row["state"] != "ready":
            raise ExtractionFailure("issue_summary_not_ready", {"state": row["state"]})
        found = store.one("SELECT * FROM results WHERE job_id=?", (job_id,))
        if found is None:
            raise ExtractionFailure("issue_summary_state_invalid")
        try:
            binding = json.loads(row["binding"])
            summary = _summary(row, binding, found)
            provenance = binding["provenance"]
            return ReadyResult(job_id, row["input_digest"], found["result_digest"], binding["issueId"], (provenance["executionMode"], provenance["recordingKind"]),
                               provenance["sourceKind"], summary)
        except (KeyError, TypeError, ValueError):
            raise ExtractionFailure("issue_summary_state_invalid") from None
    finally:
        store.close()
