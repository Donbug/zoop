"""Independent S3 relation/impact candidate ledger (authored replay or the bound live runtime). Private to this ledger: no application, S1, ingestion or S2 writer.

Flow: read-only snapshot of one completed, currently authorized S2 job -> relation generation receipt -> per-relation independent
verifier receipts -> impact producer receipt per automatically eligible relation -> per-impact independent verifier receipts. Every automatic decision
is an append-only verdict. A HOLD can later receive ONE final human decision (approve or reject) by revision CAS; approval re-runs only the
deterministic gate and calls no model. Replay is authored-response replay, not independent AI inference; nothing here is published or a graph write.
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

from . import live_prompts
from . import relation_rules as rules
from . import country_context
from .dependency_contracts import array, cites, invalid
from .extraction import Extractor, Sources, cite_exact, live_physical_calls, live_usage, upstream_digest
from .extraction import Store as ExtractionStore
from .extraction_contracts import ObservationRef, ProviderResponseUnknown
from .ingestion_contracts import byte_hash, now, reserved_state_roots
from .live_runtime import LiveFailure, LiveRuntime, physical_attempts
from .relation_contracts import (BASIS_AUTOMATIC, BASIS_OPERATOR, CANDIDATE_VERSION, EFFECT_APPROVED, EFFECT_EXCLUDED, EFFECT_LEGACY_REVALIDATION,
    EFFECT_OF, IMPACT_CANDIDATE_VERSION, IMPACT_POLICY, IMPACT_PRODUCER, IMPACT_VERIFIER, LABEL_NOTE, LABELS, LEDGER_VERSION, MAX_DOCUMENTS, POLICY,
    PRODUCER, REQUEST, REVALIDATION_POLICY, SCHEMA, VERIFIER, VOCABULARY, CitationFailure, ExtractionFailure, Replay, ReplyInvalid, Review, Submit,
    canonical, digest)

_SQL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, input_digest TEXT NOT NULL, request TEXT NOT NULL, binding TEXT NOT NULL,
 state TEXT NOT NULL, phase TEXT NOT NULL, failure TEXT, detail TEXT, resume_mode TEXT NOT NULL, fence INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stages(job_id TEXT NOT NULL REFERENCES jobs(job_id), stage TEXT NOT NULL, ref TEXT NOT NULL, summary TEXT NOT NULL,
 completed_at TEXT NOT NULL, PRIMARY KEY(job_id,stage,ref));
CREATE TABLE IF NOT EXISTS calls(attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id), stage TEXT NOT NULL,
 ref TEXT NOT NULL, request_digest TEXT NOT NULL, fixture_hash TEXT NOT NULL, state TEXT NOT NULL, response TEXT, response_digest TEXT,
 verdict TEXT, started_at TEXT NOT NULL, received_at TEXT, UNIQUE(job_id,stage,ref));
CREATE TABLE IF NOT EXISTS relation_candidates(job_id TEXT NOT NULL REFERENCES jobs(job_id), relation_candidate_id TEXT NOT NULL,
 relation_key TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(job_id,relation_candidate_id));
CREATE TABLE IF NOT EXISTS relation_events(job_id TEXT NOT NULL, relation_candidate_id TEXT NOT NULL, seq INTEGER NOT NULL,
 kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(job_id,relation_candidate_id,seq),
 FOREIGN KEY(job_id,relation_candidate_id) REFERENCES relation_candidates(job_id,relation_candidate_id));
CREATE TABLE IF NOT EXISTS impact_candidates(job_id TEXT NOT NULL, impact_candidate_id TEXT NOT NULL, relation_candidate_id TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(job_id,impact_candidate_id),
 FOREIGN KEY(job_id,relation_candidate_id) REFERENCES relation_candidates(job_id,relation_candidate_id));
CREATE TABLE IF NOT EXISTS impact_verdicts(job_id TEXT NOT NULL, impact_candidate_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(job_id,impact_candidate_id), FOREIGN KEY(job_id,impact_candidate_id) REFERENCES impact_candidates(job_id,impact_candidate_id));
"""
_IMMUTABLE = ("meta", "stages", "relation_candidates", "relation_events", "impact_candidates", "impact_verdicts")
_FILES = {"relation.sqlite3", "relation.sqlite3-wal", "relation.sqlite3-shm", "relation.lock"}
_STAGES = ("relation", "verify-relation", "impact", "verify-impact")


class Store:
    def __init__(self, root: Path, *upstream_roots: Path, existing: bool = False):
        root = Path(os.path.abspath(root))
        forbidden = [*reserved_state_roots(),
                     *(Path(os.path.abspath(p)) for p in upstream_roots)]
        if any(root == p or root.is_relative_to(p) or p.is_relative_to(root) for p in forbidden):
            raise ExtractionFailure("state_namespace_conflict")
        for parent in [*reversed(root.parents), root]:
            if parent.exists() and parent.is_symlink():
                raise ExtractionFailure("state_namespace_invalid")
        if existing:
            self._open_existing(root)
            return
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if any(p.name not in _FILES or p.is_symlink() for p in root.iterdir()):
            raise ExtractionFailure("state_namespace_conflict")
        os.chmod(root, 0o700)
        self.lock = os.open(root / "relation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(self.lock, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.lock)
            raise ExtractionFailure("relation_busy") from exc
        try:
            database = root / "relation.sqlite3"
            fd = os.open(database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            os.close(fd)
            self.db = sqlite3.connect(database, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(_SQL)
            for table in _IMMUTABLE:
                for op in ("UPDATE", "DELETE"):
                    self.db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_jobs_delete BEFORE DELETE ON jobs BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_jobs_input BEFORE UPDATE OF job_id,input_digest,request,binding,created_at ON jobs BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_calls_delete BEFORE DELETE ON calls BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_calls_identity BEFORE UPDATE OF job_id,stage,ref,request_digest,fixture_hash,started_at ON calls BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_calls_receipt BEFORE UPDATE OF response,response_digest,received_at ON calls WHEN OLD.response IS NOT NULL BEGIN SELECT RAISE(ABORT,'immutable receipt'); END")
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_calls_verdict BEFORE UPDATE OF verdict ON calls WHEN OLD.verdict IS NOT NULL BEGIN SELECT RAISE(ABORT,'immutable verdict'); END")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('ledger',?)", (LEDGER_VERSION,))
            if self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()["value"] != LEDGER_VERSION:
                raise ExtractionFailure("ledger_version_unknown")
            for p in root.iterdir():
                os.chmod(p, 0o600)
        except BaseException:
            self.close()
            raise

    def _open_existing(self, root: Path):
        """Read-only access for the S4 dependents report (same policy as the extraction and ingestion readers): shared non-blocking flock
        on the existing lock, no mkdir/chmod/create/PRAGMA/schema/WAL write, immutable read-only SQLite. A non-empty -wal is committed data a
        reader must not ignore or recover, so the operator runs the relation writer (resume) first. An active writer makes the reader fail busy."""
        database, lock = root / "relation.sqlite3", root / "relation.lock"
        if not root.is_dir() or not database.is_file() or not lock.is_file():
            raise ExtractionFailure("relation_state_missing")
        if any(p.name not in _FILES or p.is_symlink() for p in root.iterdir()):
            raise ExtractionFailure("state_namespace_conflict")
        self.lock = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.close()
            raise ExtractionFailure("relation_busy") from exc
        try:
            wal = root / "relation.sqlite3-wal"
            if wal.exists() and wal.stat().st_size > 0:
                raise ExtractionFailure("relation_recovery_required")
            self.db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA query_only=ON")
            self.db.execute("SELECT 1 FROM jobs LIMIT 1")
            meta = self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
            if meta is None or meta["value"] != LEDGER_VERSION:
                raise ExtractionFailure("ledger_version_unknown")
        except sqlite3.DatabaseError as exc:
            self.close()
            raise ExtractionFailure("relation_state_invalid") from exc
        except BaseException:
            self.close()
            raise

    def close(self):
        if hasattr(self, "db"):
            self.db.close()
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


class Fixtures:
    """Authored replay for this process only. Producer and verifier fixtures are independent files; each is validated whole at load."""

    def __init__(self, producer: bytes | None, verifier: bytes | None):
        self.docs = {"producer": self._load(producer, "producer"), "verifier": self._load(verifier, "verifier")}

    @property
    def provided(self) -> bool:
        return any(doc is not None for doc in self.docs.values())

    @staticmethod
    def _load(raw: bytes | None, role: str):
        if raw is None:
            return None
        try:
            doc = Replay.model_validate_json(raw)
        except ValueError as exc:
            raise ExtractionFailure("relation_replay_invalid") from exc
        if doc.role != role:
            raise ExtractionFailure("relation_replay_role_conflict")
        return doc, byte_hash(raw), {(r.stage, r.request_digest): r.response for r in doc.records}

    def find(self, role: str, stage: str, key: str, synthetic: bool):
        detail = {"stage": stage, "requestDigest": key}
        loaded = self.docs[role]
        if loaded is None:
            raise ExtractionFailure(f"{role}_replay_required", detail)
        doc, fixture_hash, records = loaded
        if doc.synthetic != synthetic:
            raise ExtractionFailure("replay_provenance_conflict")
        if (stage, key) not in records:
            raise ExtractionFailure(f"{role}_replay_missing", detail)
        return records[(stage, key)], fixture_hash


@dataclass
class Doc:
    ref: ObservationRef
    export: dict


class VerificationUnavailable(ExtractionFailure):
    """A live verifier produced no usable semantic judgment (transport, HTTP, malformed or schema-invalid reply). Never a verdict."""

    def __init__(self, stage: str, ref: str, code: str):
        super().__init__("verification_unavailable", {"stage": stage, "ref": ref, "code": code})


@dataclass
class Context:
    request: Submit
    synthetic: bool
    result: dict
    docs: dict  # (documentId, documentVersion) -> Doc
    view: rules.View
    events: list
    topics: list
    digest: str
    live: bool = False


def document_view(export: dict) -> dict:
    return {"documentId": export["observation"]["documentId"], "documentVersion": export["observation"]["documentVersion"],
            "title": export["observation"]["title"], "text": export["document"]["text"]}


INITIAL_ATTEMPT = rules.attempt_wire("initial", 0, POLICY, None)


def chain(store: Store, job_id: str, rc: str) -> list[dict]:
    """The append-only verdict/review events of one relation candidate in order (shared by the engine and the S4 read-only report)."""
    return [{"seq": e["seq"], "kind": e["kind"], "createdAt": e["created_at"], **json.loads(e["payload"])}
            for e in store.all("SELECT * FROM relation_events WHERE job_id=? AND relation_candidate_id=? ORDER BY seq", (job_id, rc))]


def _basis(kind: str, event: dict) -> dict:
    return {"kind": kind, "revision": event["seq"], "reviewer": event.get("reviewer") if kind == BASIS_OPERATOR else None, "decidedAt": event["createdAt"]}


def standing(events: list[dict]) -> dict:
    """Effective state from the append-only chain: the latest verdict, then later reviews by their recorded effect.

    `approved` (a human's FINAL decision on a HOLD) makes the relation eligible with `approvalBasis.kind == operator-final-approval`; `excluded`
    rejects. `revalidation-requested` only exists in ledgers written before the cutover: it is history (a still-open legacy request keeps
    `reviewPending`), never an approval. `approvalBasis` is null unless eligible; its `revision` is the seq of the deciding event."""
    verdict_at = max((i for i, e in enumerate(events) if e["kind"] == "verdict"), default=None)
    if verdict_at is None:
        return {"eligibility": "pending", "reasons": [], "reviewPending": False, "revision": len(events), "verdicts": 0, "approvalBasis": None}
    last = events[verdict_at]
    status, reasons, pending, deciding = last["eligibility"], last["reasons"], False, ("verdict", last)
    for event in events[verdict_at + 1:]:
        effect = event.get("effect")
        if effect == EFFECT_EXCLUDED:
            status, reasons, pending, deciding = "reject", [{"code": "admin_rejected"}], False, None
        elif effect == EFFECT_APPROVED:
            status, reasons, pending, deciding = "eligible", [], False, ("review", event)
        elif effect == EFFECT_LEGACY_REVALIDATION:
            pending = True
        else:
            raise ValueError("review effect")
    basis = None
    if status == "eligible" and deciding is not None:
        basis = _basis(BASIS_AUTOMATIC if deciding[0] == "verdict" else BASIS_OPERATOR, deciding[1])
    return {"eligibility": status, "reasons": reasons, "reviewPending": pending, "revision": len(events),
            "verdicts": sum(e["kind"] == "verdict" for e in events), "approvalBasis": basis}


class Engine:
    def __init__(self, store: Store, sources: Sources, extraction_dir: Path, ingestion_dir: Path, runtime_factory: Callable[..., LiveRuntime] | None = None):
        """`runtime_factory(need_send=bool)` builds the live runtime lazily and only for a live job (the CLI passes it solely for run/submit/resume)."""
        self.store, self.sources = store, sources
        self.extraction_dir, self.ingestion_dir = extraction_dir, ingestion_dir
        self.db = store.db
        self.runtime_factory = runtime_factory
        self._runtimes: dict[bool, LiveRuntime] = {}
        self._phase = "relation"

    # ------------------------------------------------------------------ upstream snapshot --------------------------------

    def _upstream(self, job_id: str):
        """Fresh read-only snapshot of the completed S2 job; rights/binding are re-verified by the owner on every call."""
        store = ExtractionStore(self.extraction_dir, self.ingestion_dir, existing=True)
        try:
            return Extractor(store, self.sources).export(job_id)
        finally:
            store.close()

    def _context(self, request: Submit) -> Context:
        submit, result = self._upstream(request.upstream.job_id)
        if result["inputDigest"] != request.upstream.input_digest:
            raise ExtractionFailure("upstream_input_mismatch")
        if submit.provenance != request.provenance:
            raise ExtractionFailure("provenance_conflict")
        if len(result["binding"]["documents"]) > MAX_DOCUMENTS:
            raise ExtractionFailure("document_limit_exceeded")
        docs: dict = {}
        for _, bound in sorted(result["binding"]["documents"].items()):
            ref = ObservationRef.model_validate(bound["observation"])
            docs.setdefault((ref.document_id, ref.document_version), Doc(ref, self.sources.export(ref)))
        snapshot = {e.event_id: e for e in submit.snapshot.events}
        events, view_events, countries = [], {}, set()
        for e in result["eventCandidates"]:
            if e["state"] != "candidate":
                continue
            mention = e["mention"]
            countries.update(mention.get("countries") or [])
            keys = [(e["document"]["documentId"], e["document"]["documentVersion"])]
            events.append({"ref": e["eventCandidateId"], "origin": "event-candidate", "title": mention["title"],
                           "participants": [{"companyId": p["company_id"], "name": p["name"], "role": p["role"]} for p in mention["participants"]],
                           "documents": [{"documentId": a, "documentVersion": b} for a, b in keys]})
            view_events[e["eventCandidateId"]] = {"origin": "event-candidate", "names": [mention["title"]], "docs": set(keys)}
        for event_id, e in sorted(snapshot.items()):
            keys = sorted({(m.observation.document_id, m.observation.document_version) for m in e.members})
            titles = sorted({m.mention.get("title") for m in e.members if isinstance(m.mention.get("title"), str)})
            for m in e.members:
                countries.update(m.mention.get("countries") or [])
            events.append({"ref": event_id, "origin": "snapshot-event", "title": titles[0] if titles else event_id, "participants": [],
                           "documents": [{"documentId": a, "documentVersion": b} for a, b in keys]})
            view_events[event_id] = {"origin": "snapshot-event", "names": titles or [event_id], "docs": set(keys)}
        topics, view_topics = [], {}
        for t in result["topicCandidates"]:
            keys = set().union(*(view_events[m["ref"]]["docs"] for m in t["members"] if m["ref"] in view_events))
            topics.append({"ref": t["topicCandidateId"], "label": t["label"], "criteria": t["criteria"], "members": [{"kind": m["kind"], "ref": m["ref"]} for m in t["members"]]})
            view_topics[t["topicCandidateId"]] = {"names": [t["label"]], "docs": keys}
        companies = {c.company_id: [c.name, *c.aliases] for c in submit.catalogue.companies}
        view = rules.View(companies, view_events, view_topics, country_context.resolve(countries), self._cite_for(docs))
        return Context(request, request.provenance.source_kind == "synthetic", result, docs, view,
                       sorted(events, key=lambda e: e["ref"]), sorted(topics, key=lambda t: t["ref"]), upstream_digest(result),
                       live=request.provenance.execution_mode == "live")

    def _cite_for(self, docs: dict):
        def cite(c: dict) -> dict:
            doc = docs.get((c["documentId"], c["documentVersion"]))
            if doc is None:
                raise CitationFailure("citation_document_unbound")
            return cite_exact(self.sources, doc.ref, doc.export, c["start"], c["end"], c["quote"])
        return cite

    def _binding(self, ctx: Context) -> dict:
        """Replay-identical frozen identity. A live job adds `runtime` (the secret-free provider/prompt/budget-free runtime binding) at freeze only."""
        return {"schema": SCHEMA, "candidate": CANDIDATE_VERSION, "impactCandidate": IMPACT_CANDIDATE_VERSION,
                "versions": {"producer": PRODUCER, "verifier": VERIFIER, "impactProducer": IMPACT_PRODUCER, "impactVerifier": IMPACT_VERIFIER,
                             "policy": POLICY, "revalidationPolicy": REVALIDATION_POLICY, "impactPolicy": IMPACT_POLICY,
                             "countryContext": country_context.VERSION},
                "upstream": {"jobId": ctx.request.upstream.job_id, "inputDigest": ctx.request.upstream.input_digest, "digest": ctx.digest},
                "provenance": ctx.request.provenance.wire()}

    def _verify(self, ctx: Context) -> None:
        """Current upstream state, rights and exact candidate set, now. Any change fails closed (nothing is silently refreshed)."""
        _, result = self._upstream(ctx.request.upstream.job_id)
        if upstream_digest(result) != ctx.digest:
            raise ExtractionFailure("upstream_changed")

    def _check_binding(self, ctx: Context, row) -> None:
        stored = json.loads(row["binding"])
        runtime = stored.pop("runtime", None)
        if (runtime is not None) != ctx.live:
            raise ExtractionFailure("job_binding_changed")
        fresh = self._binding(ctx)
        if fresh != stored:
            raise ExtractionFailure("upstream_changed" if fresh["upstream"] != stored["upstream"] else "job_binding_changed")

    # ------------------------------------------------------------------ live runtime ------------------------------------

    def _build_runtime(self, send: bool) -> LiveRuntime:
        if self.runtime_factory is None:
            raise ExtractionFailure("live_runtime_unavailable")
        if send not in self._runtimes:
            try:
                self._runtimes[send] = self.runtime_factory(need_send=send)
            except LiveFailure as exc:
                raise ExtractionFailure(exc.code) from exc
        return self._runtimes[send]

    def _runtime(self, row, *, send: bool) -> LiveRuntime:
        """The runtime of a live job. `send=False` is rebuilt PURELY from the frozen binding (decoding saved receipts and rechecking purpose/recipient
        need no key, budget or environment). `send=True` is the environment runtime, and only while it still equals the frozen binding."""
        frozen = json.loads(row["binding"])["runtime"]
        if not send:
            try:
                return LiveRuntime.from_binding(frozen)
            except LiveFailure as exc:
                raise ExtractionFailure(exc.code) from exc
        runtime = self._build_runtime(True)
        if not runtime.accepts(frozen):
            raise ExtractionFailure("live_config_changed")
        return runtime

    @staticmethod
    def _is_live(row) -> bool:
        return json.loads(row["request"])["provenance"]["executionMode"] == "live"

    def _authorize_send(self, ctx: Context, runtime: LiveRuntime, stage: str, documents=None, *, recipient: str | None = None) -> None:
        """Current model-send authority for the whole SOURCE DEPENDENCY CLOSURE of this stage, under this stage's purpose and recipient.

        Quoted documents are not the only source-derived content that reaches the provider: endpoint names, event titles/participants, topic labels and
        the generated relation itself all derive from EVERY document the S2 job bound (the producer saw them all, and a name cannot be attributed to
        one document). So every downstream model stage (generation, verification, impact, impact verification) requires model-send for each
        bound source document, even though only `documents` have their raw text sent. This only widens the authority check; no extra text is sent."""
        purpose, recipient = runtime.purpose(stage), runtime.recipient(stage) if recipient is None else recipient
        for key in sorted(ctx.docs):
            self.sources.authorize_model_send(ctx.docs[key].ref, purpose, recipient)

    # ------------------------------------------------------------------ commands -----------------------------------------

    def _job(self, job_id: str):
        row = self.store.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        if row is None:
            raise ExtractionFailure("job_not_found")
        return row

    def freeze(self, request: Submit) -> None:
        """The only registration path: durably freeze the exact upstream (a ready, currently authorized S2 job) as `queued`, with no replay
        fixture, call or candidate effect. The producer/verifier fixtures are per-call inputs, not part of the frozen job. A live job also
        freezes the non-secret runtime binding (configuration only: no key, budget or network is touched).

        A job that already exists is not touched at all: same input returns without re-freezing, resuming, resetting a stopped job or
        reading the upstream; another input is `job_input_conflict` with nothing written. A new job needs a ready current upstream
        (`upstream_not_ready` and the S2 failure codes otherwise). Execution is `resume`'s business."""
        input_digest = digest(request.wire())
        row = self.store.one("SELECT * FROM jobs WHERE job_id=?", (request.job_id,))
        if row is not None:
            if row["input_digest"] != input_digest:
                raise ExtractionFailure("job_input_conflict")
            return
        ctx = self._context(request)
        binding = self._binding(ctx)
        if ctx.live:
            binding["runtime"] = self._build_runtime(False).binding()
        with self.store.transaction(lambda: self._verify(ctx)):
            self.db.execute("INSERT INTO jobs(job_id,input_digest,request,binding,state,phase,resume_mode,created_at,updated_at) VALUES(?,?,?,?,'queued','relation','resume',?,?)",
                (request.job_id, input_digest, canonical(request.wire()), canonical(binding), now(), now()))

    def run(self, request: Submit, fixtures: Fixtures) -> dict:
        """Convenience: `freeze` then `resume` the same job."""
        self.freeze(request)
        return self.resume(request.job_id, fixtures)

    def resume(self, job_id: str, fixtures: Fixtures, *, initial_only: bool = False) -> dict:
        """Execute (or recover) the job. `initial_only` is the service's first-dispatch gate: under the ledger lock the first dispatch is recorded
        durably, and any later initial-only dispatch is `initial_dispatch_taken` with no effect, so a retrying caller can never resume or
        stimulate work; plain `resume` is explicit operator recovery."""
        row = self._job(job_id)
        if self._is_live(row) and fixtures.provided:
            raise ExtractionFailure("fixture_not_allowed")
        with self.store.transaction():
            if initial_only and (row["state"] != "queued" or self.store.one("SELECT 1 FROM stages WHERE job_id=? AND stage='dispatch'", (job_id,))
                                 or self.store.one("SELECT 1 FROM calls WHERE job_id=?", (job_id,))):
                raise ExtractionFailure("initial_dispatch_taken")
            self.db.execute("INSERT OR IGNORE INTO stages VALUES(?,'dispatch','initial',?,?)", (job_id, canonical({"initialOnly": initial_only}), now()))
        self._execute(row, fixtures)
        return self.result(job_id)

    def inspect(self, job_id: str) -> dict:
        self._job(job_id)
        return self.result(job_id)

    def cancel(self, job_id: str) -> dict:
        with self.store.transaction():
            row = self._job(job_id)
            if row["state"] != "cancelled":
                self.db.execute("UPDATE jobs SET state='cancelled',phase='cancelled',resume_mode='none',fence=fence+1,updated_at=? WHERE job_id=?", (now(), job_id))
        return self.result(job_id)

    def review(self, request: Review) -> dict:
        """Append-only HOLD review bound to the expected revision. `allow` is the operator's FINAL approval: after the deterministic candidate and
        current-rights gate it appends effect `approved` and nothing else (no model, verifier or impact call, no revalidation). `reject` excludes.
        Only a HOLD can be decided (approving an eligible relation or reversing a reject is not supported)."""
        row = self._job(request.job_id)
        if row["state"] == "cancelled":
            raise ExtractionFailure("job_cancelled")
        ctx = self._context(Submit.model_validate_json(row["request"]))
        self._check_binding(ctx, row)
        with self.store.transaction(lambda: self._verify(ctx)):
            candidate = self._candidate(request.job_id, request.relation_candidate_id)
            events = self._events(request.job_id, request.relation_candidate_id)
            state = standing(events)
            if request.expected_revision != state["revision"]:
                raise ExtractionFailure("review_revision_conflict", {"currentRevision": state["revision"]})
            if state["eligibility"] != "hold":
                raise ExtractionFailure("review_target_not_hold")
            if request.decision == "allow":
                if self._unknown_calls(request.job_id, request.relation_candidate_id):
                    raise ExtractionFailure("review_call_in_flight")
                self._recheck(candidate, ctx)
            self._append(request.job_id, request.relation_candidate_id, state["revision"] + 1, "review",
                {"decision": request.decision, "reviewer": request.reviewer, "note": request.note, "expectedRevision": request.expected_revision,
                 "effect": EFFECT_OF[request.decision]})
        return self.result(request.job_id)

    def _recheck(self, candidate_row, ctx: Context) -> None:
        """The deterministic gate a human approval can never override: the stored candidate must have passed the schema/endpoint/evidence precheck
        and must still be exactly what that precheck derives NOW from the current exact sources and upstream."""
        stored = json.loads(candidate_row["payload"])
        stored.pop("relationCandidateId", None)
        if stored["precheck"]["state"] != "pending":
            raise ExtractionFailure("review_candidate_ineligible", {"reasons": stored["precheck"]["reasons"]})
        fresh = rules.reevaluate(stored, ctx.view)
        if fresh["precheck"]["state"] != "pending":
            raise ExtractionFailure("review_candidate_ineligible", {"reasons": fresh["precheck"]["reasons"]})
        if canonical(fresh) != canonical(stored):
            raise ExtractionFailure("review_candidate_ineligible", {"reasons": [{"code": "candidate_changed"}]})

    # ------------------------------------------------------------------ execution ---------------------------------------

    def _status(self, job_id, fence, state, phase, failure=None, resume="resume", detail=None):
        self.db.execute("UPDATE jobs SET state=?,phase=?,failure=?,detail=?,resume_mode=?,updated_at=? WHERE job_id=? AND fence=?",
            (state, phase, failure, canonical(detail) if detail else None, resume, now(), job_id, fence))

    def _guard(self, job_id: str, fence: int) -> None:
        row = self._job(job_id)
        if row["fence"] != fence or row["state"] != "running":
            raise ExtractionFailure("job_cancelled_or_fenced")

    def _unknown_calls(self, job_id: str, rc: str | None = None) -> list:
        """Started logical invocations with an UNKNOWN physical outcome, including a partial chain containing a known primary receipt.
        A definitively refused invocation is excluded. With `rc`, only calls that could still write that relation's verdict or impact."""
        rows = self.store.all("SELECT ref FROM calls WHERE job_id=? AND state='started' AND attempt_id NOT IN "
                              "(SELECT ref FROM stages WHERE job_id=? AND stage='refusal')", (job_id, job_id))
        if rc is None:
            return rows
        impacts = {i["impact_candidate_id"] for i in self.store.all("SELECT impact_candidate_id FROM impact_candidates WHERE job_id=? AND relation_candidate_id=?", (job_id, rc))}
        return [r for r in rows if r["ref"] == rc or r["ref"].startswith(rc + "|") or r["ref"] in impacts]

    def _execute(self, row, fixtures: Fixtures) -> None:
        job_id, fence = row["job_id"], row["fence"]
        if row["state"] in {"cancelled", "reconciling", "ready"}:
            # A ready job is complete: a human decision never re-enters execution, and nothing is verified or re-called afterwards.
            return
        if self._unknown_calls(job_id):
            # Holding the lock proves the previous process stopped, not that its call was never sent: never auto-resend.
            self._status(job_id, fence, "reconciling", row["phase"], "live_response_unknown" if self._is_live(row) else "replay_response_unknown", "reconcile_only")
            return
        self._status(job_id, fence, "running", row["phase"])
        try:
            ctx = self._context(Submit.model_validate_json(row["request"]))
            self._check_binding(ctx, row)
        except ExtractionFailure as exc:
            self._status(job_id, fence, "stopped", row["phase"], exc.code, detail=exc.detail)
            return
        self._finish(row, ctx, fixtures, fence)

    def _finish(self, row, ctx: Context, fixtures: Fixtures, fence: int) -> None:
        job_id = row["job_id"]
        try:
            self._work(row, ctx, fixtures, fence)
            self._status(job_id, fence, "ready", "complete", resume="none")
        except ProviderResponseUnknown as exc:
            # A request may have reached the provider: the job is reconciling (operator reconcile, never recover/resend), not a stopped failure.
            self._status(job_id, fence, "reconciling", self._phase, exc.code, "reconcile_only")
        except ExtractionFailure as exc:
            self._status(job_id, fence, "stopped", self._phase, exc.code, detail=exc.detail)
        except (sqlite3.Error, OSError):
            self._status(job_id, fence, "stopped", self._phase, "persistence_failed")

    def _at(self, job_id: str, fence: int, phase: str) -> None:
        self._phase = phase
        self._status(job_id, fence, "running", phase)

    def _work(self, row, ctx: Context, fixtures: Fixtures, fence: int) -> None:
        job_id = row["job_id"]
        if not self.store.one("SELECT 1 FROM stages WHERE job_id=? AND stage='relation'", (job_id,)):
            self._at(job_id, fence, "relation")
            self._generate(row, ctx, fixtures, fence)
        unavailable: list[dict] = []
        for candidate in self.store.all("SELECT * FROM relation_candidates WHERE job_id=? ORDER BY relation_candidate_id", (job_id,)):
            if not self._events(job_id, candidate["relation_candidate_id"]):
                self._at(job_id, fence, "verify-relation")
                try:
                    self._verify_relation(row, ctx, fixtures, fence, candidate)
                except VerificationUnavailable as exc:
                    unavailable.append(exc.detail)
        for candidate in self.store.all("SELECT * FROM relation_candidates WHERE job_id=? ORDER BY relation_candidate_id", (job_id,)):
            rc = candidate["relation_candidate_id"]
            state = standing(self._events(job_id, rc))
            # Impact exists only for relations the independent verifier made eligible. A human-approved relation never triggers a model call.
            if (state["approvalBasis"] or {}).get("kind") == BASIS_AUTOMATIC and not self.store.one("SELECT 1 FROM stages WHERE job_id=? AND stage='impact' AND ref=?", (job_id, rc)):
                self._at(job_id, fence, "impact")
                self._impact(row, ctx, fixtures, fence, candidate)
        for impact in self.store.all("SELECT * FROM impact_candidates WHERE job_id=? ORDER BY impact_candidate_id", (job_id,)):
            if not self.store.one("SELECT 1 FROM impact_verdicts WHERE job_id=? AND impact_candidate_id=?", (job_id, impact["impact_candidate_id"])):
                self._at(job_id, fence, "verify-impact")
                try:
                    self._verify_impact(row, ctx, fixtures, fence, impact)
                except VerificationUnavailable as exc:
                    unavailable.append(exc.detail)
        if unavailable:
            raise ExtractionFailure("verification_unavailable", {"calls": unavailable})

    def _persist(self, row, ctx: Context, fence: int, write) -> None:
        """Candidates/verdicts and their completion record commit together, under the current fence and current upstream rights."""
        def guard():
            self._guard(row["job_id"], fence)
            self._verify(ctx)

        with self.store.transaction(guard):
            write()

    def _reserve(self, job_id: str, fence: int, stage: str, ref: str, key: str, fixture_hash: str) -> str:
        """The durable attempt record, written BEFORE anything is sent. A call whose transmission was definitively refused before sending is
        re-armed under a new attempt id (same row, same request); any other existing call is never re-reserved."""
        attempt = "attempt-" + uuid.uuid4().hex
        with self.store.transaction(lambda: self._guard(job_id, fence)):
            old = self.store.one("SELECT attempt_id,request_digest,state,response FROM calls WHERE job_id=? AND stage=? AND ref=?", (job_id, stage, ref))
            if old is None:
                self.db.execute("INSERT INTO calls(attempt_id,job_id,stage,ref,request_digest,fixture_hash,state,started_at) VALUES(?,?,?,?,?,?,'started',?)",
                    (attempt, job_id, stage, ref, key, fixture_hash, now()))
            elif (old["request_digest"] != key or old["state"] != "started" or old["response"] is not None
                  or not self.store.one("SELECT 1 FROM stages WHERE job_id=? AND stage='refusal' AND ref=?", (job_id, old["attempt_id"]))):
                raise ExtractionFailure("receipt_request_mismatch")
            else:
                self.db.execute("UPDATE calls SET attempt_id=? WHERE attempt_id=?", (attempt, old["attempt_id"]))
        return attempt

    def _refuse(self, job_id: str, attempt: str, code: str) -> None:
        """Durably record that this attempt was refused BEFORE any transmission (it is not an unknown call)."""
        self.db.execute("INSERT OR IGNORE INTO stages VALUES(?,'refusal',?,?,?)", (job_id, attempt, canonical({"code": code}), now()))

    def _receive(self, attempt: str, raw) -> None:
        unknown = isinstance(raw, dict) and raw.get("format") == "zoop-live-chain-receipt-1" and any(
            a["state"] == "unknown" for a in physical_attempts(raw))
        self.db.execute("UPDATE calls SET state=?,response=?,response_digest=?,received_at=? WHERE attempt_id=? AND state='started' AND response IS NULL",
            ("started" if unknown else "received", canonical(raw), digest(raw), now(), attempt))

    def _receipted(self, row, ctx: Context, fence: int, stage: str, ref: str, payload: dict, parse, *, fixtures: Fixtures | None = None,
                   role: str | None = None, documents=(), check=None):
        """One provider-style attempt over the native stage `payload` (its digest is the request identity).

        Replay: the whole fixture is already valid and `fixtures.find` locates the authored reply BEFORE a call is reserved. Live: prepare, check the
        current model-send rights of every document that is sent, reserve durably, send once, persist the raw receipt BEFORE decoding.

        A saved receipt is re-decoded through the same pure production parser and never re-fetched; a started call without a receipt is unknown
        and never resent; a received reply that violates its contract is permanently marked and never reusable. `check` is the post-receipt
        validation (citations/membership): reply faults mark the receipt, authority failures leave a valid receipt behind.
        """
        job_id = row["job_id"]
        key = digest(payload)
        unknown = "live_response_unknown" if ctx.live else "replay_response_unknown"
        call = self.store.one("SELECT * FROM calls WHERE job_id=? AND stage=? AND ref=?", (job_id, stage, ref))
        if call is not None and ctx.live and call["state"] == "started" and call["response"] is None and self.store.one(
                "SELECT 1 FROM stages WHERE job_id=? AND stage='refusal' AND ref=?", (job_id, call["attempt_id"])):
            call = None  # definitively never sent: `_reserve` re-arms the same row under a new attempt id
        if call is None:
            if ctx.live:
                attempt, receipt = self._send(row, ctx, fence, stage, ref, key, payload, documents)
                result = self._answer(row, ctx, stage, attempt, receipt, payload, parse, documents)
            else:
                raw, fixture_hash = fixtures.find(role, stage, key, ctx.synthetic)
                self._verify(ctx)
                attempt = self._reserve(job_id, fence, stage, ref, key, fixture_hash)
                try:
                    result = parse(raw)
                except ReplyInvalid as exc:
                    self._receive(attempt, raw)
                    self._mark(attempt, exc.code)
                    raise
                self._receive(attempt, raw)
        else:
            if call["request_digest"] != key:
                raise ExtractionFailure("receipt_request_mismatch")
            if call["state"] != "received":
                raise ProviderResponseUnknown(unknown)
            if call["verdict"]:
                raise ReplyInvalid(call["verdict"])
            raw = json.loads(call["response"])
            if digest(raw) != call["response_digest"]:
                raise ExtractionFailure("receipt_integrity_failed")
            attempt = call["attempt_id"]
            if ctx.live:
                if not isinstance(raw, dict) or raw.get("attemptId") != attempt:
                    raise ExtractionFailure("receipt_integrity_failed")
                result = self._answer(row, ctx, stage, attempt, raw, payload, parse, documents)
            else:
                try:
                    result = parse(raw)
                except ReplyInvalid as exc:
                    self._mark(attempt, exc.code)
                    raise
        self._verify(ctx)
        if ctx.live:
            self._authorize_send(ctx, self._runtime(row, send=False), stage, documents)
        if check is not None:
            try:
                result = check(result)
            except ReplyInvalid as exc:
                self._mark(attempt, exc.code)
                raise
        return result

    def _send(self, row, ctx: Context, fence: int, stage: str, ref: str, key: str, payload: dict, documents):
        """Reserve one logical invocation; runtime journals each physical attempt before considering fallback.
        Primary and fallback callbacks independently authorize the same source dependency closure for the exact recipient. A partial unknown
        envelope is stored once with state started, never treated as a completed receipt or permission to resend."""
        job_id = row["job_id"]
        runtime = self._runtime(row, send=True)
        fallback = runtime.fallback_recipient(stage)
        try:
            prepared = runtime.prepare(stage, payload)
        except LiveFailure as exc:
            raise ExtractionFailure(exc.code) from exc
        self._authorize_send(ctx, runtime, stage, documents)
        self._verify(ctx)
        attempt = self._reserve(job_id, fence, stage, ref, key, digest(json.loads(row["binding"])["runtime"]))

        def authorize() -> None:
            self._guard(job_id, fence)
            self._verify(ctx)
            self._authorize_send(ctx, runtime, stage, documents)

        def authorize_fallback() -> None:
            self._guard(job_id, fence)
            self._verify(ctx)
            self._authorize_send(ctx, runtime, stage, documents, recipient=fallback)

        try:
            receipt = runtime.send(prepared, attempt_id=attempt, authorize=authorize,
                                   **({"authorize_fallback": authorize_fallback} if fallback is not None else {}))
        except LiveFailure as exc:
            if exc.receipt is not None:
                self._receive(attempt, exc.receipt)
            if exc.uncertain:
                raise ProviderResponseUnknown(exc.code) from exc
            if exc.receipt is None:
                self._refuse(job_id, attempt, exc.code)
            raise ExtractionFailure(exc.code) from exc
        except ExtractionFailure as exc:
            self._refuse(job_id, attempt, exc.code)
            raise
        self._receive(attempt, receipt)
        return attempt, receipt

    def _answer(self, row, ctx: Context, stage: str, attempt: str, receipt: dict, payload: dict, parse, documents):
        """Strict decode of a PERSISTED receipt into the native response and its pure parser. Any fault marks the receipt permanently.

        A producer model cannot count code points, so its citations may carry no offsets: `resolve_citations` fills them ONLY from a unique literal
        quote in the exact prepared text of a document that was sent (identity is never repaired); everything else still faces the exact check."""
        runtime = self._runtime(row, send=False)
        frozen = json.loads(row["binding"])["runtime"]
        if "fallback" in frozen.get("generation", {}):
            if runtime.fallback_recipient(stage) is not None and receipt.get("format") != "zoop-live-chain-receipt-1":
                raise ExtractionFailure("receipt_binding_mismatch")
            expected = runtime.prepare(stage, payload)["requestDigest"]
            if (receipt.get("attemptId"), receipt.get("stage"), receipt.get("bindingIdentity"), receipt.get("requestDigest")) != (
                    attempt, stage, frozen["identity"], expected):
                raise ExtractionFailure("receipt_binding_mismatch")
            if receipt.get("format") == "zoop-live-chain-receipt-1" and receipt.get("logicalAttemptId") != attempt:
                raise ExtractionFailure("receipt_binding_mismatch")
        try:
            raw = runtime.answer(stage, receipt)
            if stage in {"relation", "impact"}:
                raw = live_prompts.resolve_citations(raw, {key: ctx.docs[key].export["document"]["text"] for key in documents})
        except LiveFailure as exc:
            if exc.uncertain:
                raise ProviderResponseUnknown(exc.code) from exc
            self._mark(attempt, exc.code)
            raise ReplyInvalid(exc.code) from exc
        if receipt.get("format") == "zoop-live-chain-receipt-1":
            for physical in physical_attempts(receipt):
                if physical["state"] == "received":
                    self._authorize_send(ctx, runtime, stage, documents, recipient=physical["receipt"]["recipient"])
        try:
            return parse(raw)
        except ReplyInvalid as exc:
            self._mark(attempt, exc.code)
            raise

    def _mark(self, attempt: str, code: str) -> None:
        self.db.execute("UPDATE calls SET verdict=? WHERE attempt_id=? AND verdict IS NULL", (code, attempt))

    # ------------------------------------------------------------------ stages -----------------------------------------

    def _events(self, job_id: str, rc: str) -> list[dict]:
        return chain(self.store, job_id, rc)

    def _candidate(self, job_id: str, rc: str):
        row = self.store.one("SELECT * FROM relation_candidates WHERE job_id=? AND relation_candidate_id=?", (job_id, rc))
        if row is None:
            raise ExtractionFailure("relation_candidate_not_found")
        return row

    def _append(self, job_id: str, rc: str, seq: int, kind: str, payload: dict) -> None:
        self.db.execute("INSERT INTO relation_events VALUES(?,?,?,?,?,?)", (job_id, rc, seq, kind, canonical(payload), now()))

    def generation_request(self, ctx: Context) -> dict:
        docs = [document_view(d.export) for _, d in sorted(ctx.docs.items())]
        catalogue = sorted(({"companyId": cid, "names": names} for cid, names in ctx.view.companies.items()), key=lambda c: c["companyId"])
        return {"schemaVersion": REQUEST, "stage": "relation", "producerVersion": PRODUCER, "vocabulary": VOCABULARY,
                "upstream": {"jobId": ctx.request.upstream.job_id, "inputDigest": ctx.request.upstream.input_digest},
                "catalogue": catalogue, "events": ctx.events, "topics": ctx.topics, "documents": docs}

    def _generate(self, row, ctx: Context, fixtures: Fixtures, fence: int) -> None:
        job_id = row["job_id"]
        request = self.generation_request(ctx)
        key = digest(request)
        response = self._receipted(row, ctx, fence, "relation", "job", request, rules.parse_relations, fixtures=fixtures, role="producer", documents=set(ctx.docs))
        candidates = []
        for merged in rules.merge([p.wire() for p in response.relations]):
            candidate = rules.evaluate(merged, ctx.view)
            candidate["relationCandidateId"] = "rc-" + digest({"version": CANDIDATE_VERSION, "requestDigest": key, "relationKey": merged["relationKey"]})
            candidates.append(candidate)

        def write():
            for c in candidates:
                self.db.execute("INSERT OR IGNORE INTO relation_candidates VALUES(?,?,?,?)", (job_id, c["relationCandidateId"], c["relationKey"], canonical(c)))
                if c["precheck"]["state"] != "pending":
                    self._append(job_id, c["relationCandidateId"], 1, "verdict", self._deterministic(c, INITIAL_ATTEMPT))
            self.db.execute("INSERT INTO stages VALUES(?,?,?,?,?)", (job_id, "relation", "job",
                canonical({"relations": len(candidates), "proposals": len(response.relations), "requestDigest": key}), now()))

        self._persist(row, ctx, fence, write)
        self._stage_saved("relation")

    @staticmethod
    def _deterministic(candidate: dict, attempt: dict) -> dict:
        return {"kind": "verdict", "attempt": attempt, "eligibility": candidate["precheck"]["state"],
                "reasons": candidate["precheck"]["reasons"], "claims": None, "verifier": "not-called", "requestDigest": None}

    def _verify_relation(self, row, ctx: Context, fixtures: Fixtures, fence: int, candidate_row) -> None:
        job_id, rc = row["job_id"], candidate_row["relation_candidate_id"]
        candidate = json.loads(candidate_row["payload"])
        if candidate["precheck"]["state"] != "pending":
            verdict = self._deterministic(candidate, INITIAL_ATTEMPT)
        else:
            request = rules.verifier_request(candidate, INITIAL_ATTEMPT)
            key = digest(request)
            documents = {(q["documentId"], q["documentVersion"]) for q in candidate["quotes"]}
            try:
                decision = self._receipted(row, ctx, fence, "verify-relation", f"{rc}|initial|0", request, lambda raw: rules.decide_relation(candidate, raw),
                                           fixtures=fixtures, role="verifier", documents=documents)
            except ReplyInvalid as exc:
                if ctx.live:
                    # A transport/HTTP/malformed/schema-invalid reply is no semantic judgment: no verdict is written (the candidate stays pending and
                    # non-eligible, never a HOLD a human could approve) and the job stops. Only a valid interpreted answer yields a verdict.
                    raise VerificationUnavailable("verify-relation", rc, exc.code) from exc
                decision = {"eligibility": "reject", "reasons": [{"code": "verification_reply_invalid", "detail": exc.code}], "claims": None}
            verdict = {"kind": "verdict", "attempt": INITIAL_ATTEMPT, **decision, "verifier": "called", "requestDigest": key}

        def write():
            if self.store.one("SELECT 1 FROM relation_events WHERE job_id=? AND relation_candidate_id=?", (job_id, rc)):
                raise ExtractionFailure("verdict_superseded")  # a decision already exists: an automatic verdict never follows or overwrites it
            self._append(job_id, rc, 1, "verdict", verdict)

        self._persist(row, ctx, fence, write)

    def _impact(self, row, ctx: Context, fixtures: Fixtures, fence: int, candidate_row) -> None:
        job_id, rc = row["job_id"], candidate_row["relation_candidate_id"]
        candidate = json.loads(candidate_row["payload"])
        allowed = {(q["documentId"], q["documentVersion"]) for q in candidate["quotes"]}
        documents = [document_view(ctx.docs[k].export) for k in sorted(allowed)]
        request = rules.impact_request(candidate, documents)
        key = digest(request)
        try:
            impacts = self._receipted(row, ctx, fence, "impact", rc, request, rules.parse_impacts, fixtures=fixtures, role="producer", documents=allowed,
                check=lambda response: rules.evaluate_impacts(response, candidate, allowed, ctx.view.cite))
            summary = {"status": "complete", "candidates": len(impacts), "requestDigest": key}
        except ReplyInvalid as exc:
            # A faulty impact reply never touches the verified relation: it is recorded and the relation stays eligible.
            impacts, summary = [], {"status": "producer-reply-invalid", "code": exc.code, "requestDigest": key}

        def write():
            for impact in impacts:
                ic = "ic-" + digest({"version": IMPACT_CANDIDATE_VERSION, "relationCandidateId": rc, "impactedCompanyId": impact["impactedCompanyId"], "requestDigest": key})
                self.db.execute("INSERT OR IGNORE INTO impact_candidates VALUES(?,?,?,?)", (job_id, ic, rc, canonical({**impact, "impactCandidateId": ic, "relationCandidateId": rc})))
                if impact["precheck"]["state"] == "reject":
                    verdict = {"status": "reject", "label": None, "reasons": impact["precheck"]["reasons"], "targetVerdict": None, "mapped": None, "verifier": "not-called"}
                elif impact["precheck"]["state"] == "no-evidence":
                    verdict = {"status": "verified", "label": "undetermined", "reasons": [{"code": "no_cited_evidence"}], "targetVerdict": None,
                               "mapped": {"positive": [], "negative": [], "neutral": []}, "verifier": "not-called"}
                else:
                    continue
                self.db.execute("INSERT INTO impact_verdicts VALUES(?,?,?,?)", (job_id, ic, canonical(verdict), now()))
            self.db.execute("INSERT INTO stages VALUES(?,?,?,?,?)", (job_id, "impact", rc, canonical(summary), now()))

        self._persist(row, ctx, fence, write)
        self._stage_saved("impact")

    def _verify_impact(self, row, ctx: Context, fixtures: Fixtures, fence: int, impact_row) -> None:
        job_id, ic = row["job_id"], impact_row["impact_candidate_id"]
        candidate = json.loads(impact_row["payload"])
        attempt = rules.attempt_wire("initial", 0, IMPACT_POLICY, None)
        request = rules.impact_verifier_request(candidate, attempt)
        key = digest(request)
        documents = {(q["documentId"], q["documentVersion"]) for q in candidate["quotes"]}
        try:
            decision = self._receipted(row, ctx, fence, "verify-impact", ic, request, lambda raw: rules.decide_impact(candidate, raw),
                                       fixtures=fixtures, role="verifier", documents=documents)
        except ReplyInvalid as exc:
            if ctx.live:
                raise VerificationUnavailable("verify-impact", ic, exc.code) from exc  # no judgment exists: nothing is written, no label is invented
            decision = {"status": "reject", "label": None, "reasons": [{"code": "verification_reply_invalid", "detail": exc.code}], "targetVerdict": None, "mapped": None}
        verdict = {**decision, "verifier": "called", "attempt": attempt, "requestDigest": key}

        def write():
            self.db.execute("INSERT INTO impact_verdicts VALUES(?,?,?,?)", (job_id, ic, canonical(verdict), now()))

        self._persist(row, ctx, fence, write)

    def _stage_saved(self, stage: str) -> None:
        """Seam after a stage commit; a process boundary here proves resume reuses committed work and receipts."""

    # ------------------------------------------------------------------ result ------------------------------------------

    def result(self, job_id: str) -> dict:
        row = self._job(job_id)
        request = Submit.model_validate_json(row["request"])
        live = request.provenance.execution_mode == "live"
        binding = json.loads(row["binding"])
        calls = self.store.all("SELECT * FROM calls WHERE job_id=? ORDER BY started_at,attempt_id", (job_id,))
        stages = self.store.all("SELECT * FROM stages WHERE job_id=?", (job_id,))
        refused = {s["ref"]: json.loads(s["summary"])["code"] for s in stages if s["stage"] == "refusal"}
        received = sum(c["state"] == "received" for c in calls)
        unknown = sum(c["state"] == "started" and c["attempt_id"] not in refused for c in calls)
        chain_live = live and "fallback" in binding.get("runtime", {}).get("generation", {})
        physical_usage = live_usage(job_id, [{**dict(c), "state": "unsent" if c["attempt_id"] in refused else c["state"]} for c in calls]) if chain_live else None
        candidates = self.store.all("SELECT * FROM relation_candidates WHERE job_id=? ORDER BY relation_candidate_id", (job_id,))
        result = {"schemaVersion": SCHEMA, "jobId": job_id, "inputDigest": row["input_digest"], "state": row["state"], "phase": row["phase"],
            "resumeMode": row["resume_mode"], "failure": {"code": row["failure"], **({"detail": json.loads(row["detail"])} if row["detail"] else {})} if row["failure"] else None,
            "provenance": request.provenance.wire(), "binding": binding,
            "stages": {"relation": {"state": "complete", **json.loads(next(s["summary"] for s in stages if s["stage"] == "relation"))} if any(s["stage"] == "relation" for s in stages) else {"state": "pending"},
                       "impact": {"complete": sum(s["stage"] == "impact" for s in stages)}},
            "usage": {"executionMode": "live" if live else "replay", "replayCalls": 0 if live else received, "startedWithoutReceipt": unknown,
                      # Conservative like S2: every attempt that was or may have been transmitted (received + unknown), never one proven refused.
                      # `startedWithoutReceipt` keeps receipts (received = providerCalls - startedWithoutReceipt) distinct from unknown outcomes.
                      "providerCalls": received + unknown if live else 0, "modelCalls": received + unknown if live else 0, "creatorJobId": job_id},
            "calls": [{"stage": c["stage"], "state": "refused" if c["state"] == "started" and c["attempt_id"] in refused else c["state"], "requestDigest": c["request_digest"],
                       "fixtureHash": c["fixture_hash"], "responseDigest": c["response_digest"], "verdict": c["verdict"] or refused.get(c["attempt_id"])} for c in calls]}
        if physical_usage is not None:
            result["usage"] = {**physical_usage, "modelCalls": physical_usage["providerCalls"]}
            for projected, call in zip(result["calls"], calls):
                projected["physicalAttempts"] = live_physical_calls(call)
        if row["state"] == "cancelled":
            result["delivery"] = {"status": "withheld", "code": "job_cancelled"}
            return result
        try:
            ctx = self._context(request)
            self._check_binding(ctx, row)
        except ExtractionFailure as exc:
            result["delivery"] = {"status": "withheld", "code": exc.code}
            return result
        impacts: dict[str, list] = {}
        for i in self.store.all("SELECT * FROM impact_candidates WHERE job_id=? ORDER BY impact_candidate_id", (job_id,)):
            verdict = self.store.one("SELECT * FROM impact_verdicts WHERE job_id=? AND impact_candidate_id=?", (job_id, i["impact_candidate_id"]))
            payload = json.loads(i["payload"])
            impacts.setdefault(i["relation_candidate_id"], []).append({**payload, "verdict": json.loads(verdict["payload"]) if verdict else None,
                "agreement": None if verdict is None or json.loads(verdict["payload"])["label"] is None else payload["proposal"]["direction"] == json.loads(verdict["payload"])["label"]})
        relations, counts, labels = [], {"pending": 0, "eligible": 0, "hold": 0, "reject": 0}, {label: 0 for label in LABELS}
        for c in candidates:
            payload = json.loads(c["payload"])
            events = self._events(job_id, c["relation_candidate_id"])
            state = standing(events)
            counts[state["eligibility"]] += 1
            marker = next((json.loads(s["summary"]) for s in stages if s["stage"] == "impact" and s["ref"] == c["relation_candidate_id"]), None)
            found = sorted(impacts.get(c["relation_candidate_id"], []), key=lambda i: i["impactedCompanyId"])
            for i in found:
                if i["verdict"] and i["verdict"]["label"]:
                    labels[i["verdict"]["label"]] += 1
            # A human-approved relation was never given an impact stage (no model call follows a human allow).
            impact_state = ("not-applicable" if state["eligibility"] in {"hold", "reject"} or (marker is None and (state["approvalBasis"] or {}).get("kind") == BASIS_OPERATOR)
                            else "pending" if marker is None else marker["status"] if marker["status"] != "complete" else "complete")
            relations.append({**payload, "eligibility": {"status": state["eligibility"], "reasons": state["reasons"], "revision": state["revision"],
                "reviewPending": state["reviewPending"], "approvalBasis": state["approvalBasis"]}, "history": events,
                "impact": {"status": impact_state, "labelNote": LABEL_NOTE, "candidates": found}})
        result["counts"] = {"relations": len(candidates), "eligibility": counts, "impactLabels": labels,
                            "impactCandidates": sum(len(v) for v in impacts.values())}
        result["relations"] = relations
        result["delivery"] = {"status": "current", "authority": "S2 job, read+quote-display rights and exact candidate set verified at delivery"}
        return result


# ---------------------------------------------------------------------- S4 dependents (read-only) -----------------------------------

def dependents(store: Store, index: dict) -> dict:
    """Identity-only S4 report over EVERY job of an `existing=True` relation store, joined to the S2 scan `index` by the upstream the S3 job froze:
    (jobId, inputDigest) AND the pinned `upstream.digest` (frozen binding incl. grants + delivered candidates).

    inputDigest covers only the request and replay, not the frozen grant, and a relation binding does not record which extraction ledger it read.
    So an upstream that is absent from the scanned ledger, has another input digest, is not the ready job S3 can only originate from, or whose
    recomputed digest differs from the pinned one (e.g. the same job under another frozen grant revision) is listed as `unresolved` BEFORE any
    affected/unaffected decision, never omitted or attributed to a different binding. A job whose upstream is the exact pinned one and is affected
    is listed, and its direct entries are the relation/impact candidates that name an affected event/topic endpoint (matching kind) or cite an
    affected document. Eligibility is the pure `standing()` of the stored chain; no delivery, authority or registry is involved. A row that does
    not parse, or a dependency container that is not an array, fails the whole report."""
    buckets: dict[str, list] = {"jobs": [], "unresolved": []}
    scanned = 0
    try:
        for row in store.all("SELECT job_id,input_digest,request,binding,state,phase,failure FROM jobs ORDER BY job_id"):
            scanned += 1
            try:
                found = _dependents_of(store, row, index)
            except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
                raise invalid("relation", row["job_id"]) from exc
            if found is not None:
                buckets[found[0]].append(found[1])
    except sqlite3.DatabaseError as exc:
        raise ExtractionFailure("relation_state_invalid") from exc
    return {"ledgerVersion": LEDGER_VERSION, "scannedJobs": scanned, **buckets}


def _dependents_of(store: Store, row, index: dict) -> tuple[str, dict] | None:
    job_id = row["job_id"]
    request, upstream = Submit.model_validate_json(row["request"]), json.loads(row["binding"])["upstream"]
    if (request.upstream.job_id, request.upstream.input_digest) != (upstream["jobId"], upstream["inputDigest"]):
        raise ValueError("upstream identity")
    pinned = {"jobId": upstream["jobId"], "inputDigest": upstream["inputDigest"]}
    if not isinstance(upstream["digest"], str):
        raise ValueError("upstream digest")
    found = index.get(pinned["jobId"])
    code = ("upstream_not_in_scanned_ledger" if found is None else "upstream_input_mismatch" if found["inputDigest"] != pinned["inputDigest"]
            # Export is ready-only and ready is terminal, so any other state cannot be what S3 consumed; the digest settles the rest.
            else "upstream_binding_mismatch" if not found["ready"] or found["digest"]() != upstream["digest"] else None)
    if code is not None:
        return "unresolved", {"jobId": job_id, "inputDigest": row["input_digest"], "state": row["state"], "upstream": pinned, "code": code}
    if not found["affected"]:
        return None
    documents, events, topics = found["documents"], found["events"], found["topics"]
    relations = store.all("SELECT relation_candidate_id,relation_key,payload FROM relation_candidates WHERE job_id=? ORDER BY relation_candidate_id", (job_id,))
    impacts = store.all("SELECT impact_candidate_id,relation_candidate_id,payload FROM impact_candidates WHERE job_id=? ORDER BY impact_candidate_id", (job_id,))
    relation_ids = {r["relation_candidate_id"] for r in relations}

    relation_entries, listed = [], set()
    for r in relations:
        payload = json.loads(r["payload"])
        if payload["relationKey"] != r["relation_key"]:
            raise ValueError("relation identity")
        reasons = []
        for role in ("subject", "object"):
            kind, ref = payload[role]["kind"], payload[role]["ref"]
            # Event and topic are different endpoint kinds: a topic endpoint that spells an event ID is not a dependency on that event.
            if (kind == "event" and ref in events) or (kind == "topic" and ref in topics):
                reasons.append({"code": "endpoint_" + kind, "role": role, "ref": ref})
        reasons += cites(payload["citations"], documents, at="citations")
        reasons += cites(payload["validity"]["citations"], documents, at="validity")
        for number, step in enumerate(array(payload["path"]), 1):
            reasons += cites(step["citations"], documents, at=f"step:{number}")
        if reasons:
            listed.add(r["relation_candidate_id"])
            relation_entries.append({"relationCandidateId": r["relation_candidate_id"], "relationKey": r["relation_key"],
                                     "eligibility": standing(chain(store, job_id, r["relation_candidate_id"]))["eligibility"], "reasons": reasons})

    impact_entries = []
    for i in impacts:
        payload = json.loads(i["payload"])
        if payload["impactCandidateId"] != i["impact_candidate_id"] or payload["relationCandidateId"] != i["relation_candidate_id"] or i["relation_candidate_id"] not in relation_ids:
            raise ValueError("impact identity")
        reasons = [*([{"code": "relation", "relationCandidateId": i["relation_candidate_id"]}] if i["relation_candidate_id"] in listed else []),
                   *cites(payload["proposal"]["supporting"], documents, at="supporting"), *cites(payload["proposal"]["opposing"], documents, at="opposing")]
        if reasons:
            verdict = store.one("SELECT payload FROM impact_verdicts WHERE job_id=? AND impact_candidate_id=?", (job_id, i["impact_candidate_id"]))
            impact_entries.append({"impactCandidateId": i["impact_candidate_id"], "relationCandidateId": i["relation_candidate_id"],
                                   "verdictStatus": json.loads(verdict["payload"])["status"] if verdict else None, "reasons": reasons})

    return "jobs", {"jobId": job_id, "inputDigest": row["input_digest"], "state": row["state"], "phase": row["phase"], "failureCode": row["failure"],
                    "upstream": pinned, "reasons": [{"code": "upstream"}],
                    # The producer request carried every upstream document and delivery re-verifies the whole upstream: a change withholds all of the job.
                    "jobScope": {"relationCandidates": len(relations), "impactCandidates": len(impacts)},
                    "relationCandidates": relation_entries, "impactCandidates": impact_entries}
