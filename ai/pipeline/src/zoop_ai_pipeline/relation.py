"""Independent offline S3 relation/impact candidate ledger. Private to this ledger: no application, S1, ingestion or S2 writer.

Flow: read-only snapshot of one completed, currently authorized S2 job -> relation generation receipt -> per-relation independent
verifier receipts -> impact producer receipt per eligible relation -> per-impact independent verifier receipts. Every decision is an
append-only verdict; HOLD review can only request a new automatic revalidation attempt. Replay is authored-response replay, not
independent AI inference; nothing here is approved, published or a graph write.
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import relation_rules as rules
from .extraction import Extractor, Sources, cite_exact
from .extraction import Store as ExtractionStore
from .extraction_contracts import ObservationRef
from .ingestion_contracts import byte_hash, now, reserved_state_roots
from .relation_contracts import (CANDIDATE_VERSION, IMPACT_CANDIDATE_VERSION, IMPACT_POLICY, IMPACT_PRODUCER, IMPACT_VERIFIER, LABEL_NOTE,
    LABELS, LEDGER_VERSION, MAX_DOCUMENTS, POLICY, PRODUCER, REQUEST, REVALIDATION_POLICY, SCHEMA, VERIFIER, VOCABULARY, CitationFailure,
    ExtractionFailure, Replay, ReplyInvalid, Review, Revalidate, Submit, canonical, digest)

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
    def __init__(self, root: Path, *upstream_roots: Path):
        root = Path(os.path.abspath(root))
        forbidden = [*reserved_state_roots(),
                     *(Path(os.path.abspath(p)) for p in upstream_roots)]
        if any(root == p or root.is_relative_to(p) or p.is_relative_to(root) for p in forbidden):
            raise ExtractionFailure("state_namespace_conflict")
        for parent in [*reversed(root.parents), root]:
            if parent.exists() and parent.is_symlink():
                raise ExtractionFailure("state_namespace_invalid")
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


def document_view(export: dict) -> dict:
    return {"documentId": export["observation"]["documentId"], "documentVersion": export["observation"]["documentVersion"],
            "title": export["observation"]["title"], "text": export["document"]["text"]}


def upstream_digest(result: dict) -> str:
    return digest({"jobId": result["jobId"], "inputDigest": result["inputDigest"], "binding": result["binding"],
                   "eventCandidates": result["eventCandidates"], "topicCandidates": result["topicCandidates"]})


def next_attempt(events: list[dict], kind: str) -> dict:
    """Distinct identity of the next verification attempt: kind, ordinal, its own policy, and the prior verdict it supersedes."""
    verdicts = [e for e in events if e["kind"] == "verdict"]
    prior = digest({k: v for k, v in verdicts[-1].items() if k not in {"seq", "createdAt"}}) if verdicts else None
    return rules.attempt_wire(kind, len(verdicts), REVALIDATION_POLICY if kind == "revalidation" else POLICY, prior)


def standing(events: list[dict]) -> dict:
    """Effective state from the append-only chain: the latest verdict, then later reviews. `allow` never changes eligibility."""
    verdict_at = max((i for i, e in enumerate(events) if e["kind"] == "verdict"), default=None)
    if verdict_at is None:
        return {"eligibility": "pending", "reasons": [], "reviewPending": False, "revision": len(events), "verdicts": 0}
    last = events[verdict_at]
    status, reasons, pending = last["eligibility"], last["reasons"], False
    for event in events[verdict_at + 1:]:
        if event["decision"] == "reject":
            status, reasons, pending = "reject", [{"code": "admin_rejected"}], False
        else:
            pending = True
    return {"eligibility": status, "reasons": reasons, "reviewPending": pending, "revision": len(events),
            "verdicts": sum(e["kind"] == "verdict" for e in events)}


class Engine:
    def __init__(self, store: Store, sources: Sources, extraction_dir: Path, ingestion_dir: Path):
        self.store, self.sources = store, sources
        self.extraction_dir, self.ingestion_dir = extraction_dir, ingestion_dir
        self.db = store.db
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
        view = rules.View(companies, view_events, view_topics, {str(c) for c in countries}, self._cite_for(docs))
        return Context(request, request.provenance.source_kind == "synthetic", result, docs, view,
                       sorted(events, key=lambda e: e["ref"]), sorted(topics, key=lambda t: t["ref"]), upstream_digest(result))

    def _cite_for(self, docs: dict):
        def cite(c: dict) -> dict:
            doc = docs.get((c["documentId"], c["documentVersion"]))
            if doc is None:
                raise CitationFailure("citation_document_unbound")
            return cite_exact(self.sources, doc.ref, doc.export, c["start"], c["end"], c["quote"])
        return cite

    def _binding(self, ctx: Context) -> dict:
        return {"schema": SCHEMA, "candidate": CANDIDATE_VERSION, "impactCandidate": IMPACT_CANDIDATE_VERSION,
                "versions": {"producer": PRODUCER, "verifier": VERIFIER, "impactProducer": IMPACT_PRODUCER, "impactVerifier": IMPACT_VERIFIER,
                             "policy": POLICY, "revalidationPolicy": REVALIDATION_POLICY, "impactPolicy": IMPACT_POLICY},
                "upstream": {"jobId": ctx.request.upstream.job_id, "inputDigest": ctx.request.upstream.input_digest, "digest": ctx.digest},
                "provenance": ctx.request.provenance.wire()}

    def _verify(self, ctx: Context) -> None:
        """Current upstream state, rights and exact candidate set, now. Any change fails closed (nothing is silently refreshed)."""
        _, result = self._upstream(ctx.request.upstream.job_id)
        if upstream_digest(result) != ctx.digest:
            raise ExtractionFailure("upstream_changed")

    def _check_binding(self, ctx: Context, row) -> None:
        stored, fresh = json.loads(row["binding"]), self._binding(ctx)
        if fresh != stored:
            raise ExtractionFailure("upstream_changed" if fresh["upstream"] != stored["upstream"] else "job_binding_changed")

    # ------------------------------------------------------------------ commands -----------------------------------------

    def _job(self, job_id: str):
        row = self.store.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        if row is None:
            raise ExtractionFailure("job_not_found")
        return row

    def run(self, request: Submit, fixtures: Fixtures) -> dict:
        input_digest = digest(request.wire())
        row = self.store.one("SELECT * FROM jobs WHERE job_id=?", (request.job_id,))
        if row is not None:
            if row["input_digest"] != input_digest:
                raise ExtractionFailure("job_input_conflict")
            return self.resume(request.job_id, fixtures)
        ctx = self._context(request)
        with self.store.transaction(lambda: self._verify(ctx)):
            self.db.execute("INSERT INTO jobs(job_id,input_digest,request,binding,state,phase,resume_mode,created_at,updated_at) VALUES(?,?,?,?,'queued','relation','resume',?,?)",
                (request.job_id, input_digest, canonical(request.wire()), canonical(self._binding(ctx)), now(), now()))
        return self.resume(request.job_id, fixtures)

    def resume(self, job_id: str, fixtures: Fixtures) -> dict:
        self._execute(self._job(job_id), fixtures)
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
        """Append-only HOLD review bound to the expected revision. `allow` requests revalidation only; `reject` can only exclude."""
        row = self._job(request.job_id)
        if row["state"] == "cancelled":
            raise ExtractionFailure("job_cancelled")
        ctx = self._context(Submit.model_validate_json(row["request"]))
        self._check_binding(ctx, row)
        with self.store.transaction(lambda: self._verify(ctx)):
            self._candidate(request.job_id, request.relation_candidate_id)
            events = self._events(request.job_id, request.relation_candidate_id)
            state = standing(events)
            if request.expected_revision != state["revision"]:
                raise ExtractionFailure("review_revision_conflict", {"currentRevision": state["revision"]})
            if state["eligibility"] != "hold":
                raise ExtractionFailure("review_target_not_hold")
            if state["reviewPending"] and request.decision == "allow":
                raise ExtractionFailure("review_already_pending")
            self._append(request.job_id, request.relation_candidate_id, state["revision"] + 1, "review",
                {"decision": request.decision, "reviewer": request.reviewer, "note": request.note, "expectedRevision": request.expected_revision,
                 "effect": "revalidation-requested" if request.decision == "allow" else "excluded"})
        return self.result(request.job_id)

    def revalidate(self, request: Revalidate, fixtures: Fixtures) -> dict:
        """A new, distinctly identified automatic verification attempt over the fixed stored candidate. Never regenerates, never auto-allows."""
        row = self._job(request.job_id)
        if row["state"] not in {"ready", "stopped", "running"}:  # `running` under our exclusive lock is a process that died mid-attempt
            raise ExtractionFailure("job_not_revalidatable", {"state": row["state"]})
        ctx = self._context(Submit.model_validate_json(row["request"]))
        self._check_binding(ctx, row)
        if self.store.one("SELECT 1 FROM calls WHERE job_id=? AND state='started' AND response IS NULL", (row["job_id"],)):
            self._status(row["job_id"], row["fence"], "reconciling", row["phase"], "replay_response_unknown", "reconcile_only")
            raise ExtractionFailure("replay_response_unknown")
        candidate = self._candidate(request.job_id, request.relation_candidate_id)
        state = standing(self._events(request.job_id, request.relation_candidate_id))
        if state["revision"] != request.expected_revision:
            raise ExtractionFailure("review_revision_conflict", {"currentRevision": state["revision"]})
        if not state["reviewPending"]:
            raise ExtractionFailure("revalidation_not_requested")
        previous = (row["state"], row["phase"], row["failure"], row["detail"], row["resume_mode"])
        fence = row["fence"]
        self.db.execute("UPDATE jobs SET state='running',phase='revalidate',updated_at=? WHERE job_id=? AND fence=?", (now(), row["job_id"], fence))
        try:
            self._verify_relation(row, ctx, fixtures, fence, candidate, "revalidation")
        except ExtractionFailure:
            self.db.execute("UPDATE jobs SET state=?,phase=?,failure=?,detail=?,resume_mode=?,updated_at=? WHERE job_id=? AND fence=?", (*previous, now(), row["job_id"], fence))
            raise
        self._finish(row, ctx, fixtures, fence)
        return self.result(request.job_id)

    # ------------------------------------------------------------------ execution ---------------------------------------

    def _status(self, job_id, fence, state, phase, failure=None, resume="resume", detail=None):
        self.db.execute("UPDATE jobs SET state=?,phase=?,failure=?,detail=?,resume_mode=?,updated_at=? WHERE job_id=? AND fence=?",
            (state, phase, failure, canonical(detail) if detail else None, resume, now(), job_id, fence))

    def _guard(self, job_id: str, fence: int) -> None:
        row = self._job(job_id)
        if row["fence"] != fence or row["state"] != "running":
            raise ExtractionFailure("job_cancelled_or_fenced")

    def _execute(self, row, fixtures: Fixtures) -> None:
        job_id, fence = row["job_id"], row["fence"]
        if row["state"] in {"cancelled", "reconciling"} or (row["state"] == "ready" and not self._has_saved_revalidation(job_id)):
            # A ready job only re-enters for a DURABLY saved revalidation receipt; a newly allowed review never auto-executes.
            return
        if self.store.one("SELECT 1 FROM calls WHERE job_id=? AND state='started' AND response IS NULL", (job_id,)):
            # Holding the lock proves the previous process stopped, not that its call was never sent: never auto-resend.
            self._status(job_id, fence, "reconciling", row["phase"], "replay_response_unknown", "reconcile_only")
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
        for candidate in self.store.all("SELECT * FROM relation_candidates WHERE job_id=? ORDER BY relation_candidate_id", (job_id,)):
            events = self._events(job_id, candidate["relation_candidate_id"])
            kind = "initial" if not events else self._saved_revalidation(job_id, candidate["relation_candidate_id"], events)
            if kind:
                self._at(job_id, fence, "verify-relation" if kind == "initial" else "revalidate")
                self._verify_relation(row, ctx, fixtures, fence, candidate, kind)
        for candidate in self.store.all("SELECT * FROM relation_candidates WHERE job_id=? ORDER BY relation_candidate_id", (job_id,)):
            rc = candidate["relation_candidate_id"]
            if standing(self._events(job_id, rc))["eligibility"] == "eligible" and not self.store.one("SELECT 1 FROM stages WHERE job_id=? AND stage='impact' AND ref=?", (job_id, rc)):
                self._at(job_id, fence, "impact")
                self._impact(row, ctx, fixtures, fence, candidate)
        for impact in self.store.all("SELECT * FROM impact_candidates WHERE job_id=? ORDER BY impact_candidate_id", (job_id,)):
            if not self.store.one("SELECT 1 FROM impact_verdicts WHERE job_id=? AND impact_candidate_id=?", (job_id, impact["impact_candidate_id"])):
                self._at(job_id, fence, "verify-impact")
                self._verify_impact(row, ctx, fixtures, fence, impact)

    def _persist(self, row, ctx: Context, fence: int, write) -> None:
        """Candidates/verdicts and their completion record commit together, under the current fence and current upstream rights."""
        def guard():
            self._guard(row["job_id"], fence)
            self._verify(ctx)

        with self.store.transaction(guard):
            write()

    def _reserve(self, job_id: str, fence: int, stage: str, ref: str, key: str, fixture_hash: str) -> str:
        attempt = "attempt-" + uuid.uuid4().hex
        with self.store.transaction(lambda: self._guard(job_id, fence)):
            self.db.execute("INSERT INTO calls(attempt_id,job_id,stage,ref,request_digest,fixture_hash,state,started_at) VALUES(?,?,?,?,?,?,'started',?)",
                (attempt, job_id, stage, ref, key, fixture_hash, now()))
        return attempt

    def _receive(self, attempt: str, raw) -> None:
        self.db.execute("UPDATE calls SET state='received',response=?,response_digest=?,received_at=? WHERE attempt_id=? AND state='started'",
            (canonical(raw), digest(raw), now(), attempt))

    def _receipted(self, row, ctx: Context, fence: int, stage: str, ref: str, key: str, lookup, parse, check=None):
        """One provider-style attempt. The whole fixture is already valid; `lookup()` finds the authored reply BEFORE a call is reserved.

        A saved receipt is re-parsed through the same pure production parser and never re-fetched; a started call without a receipt is
        unknown and never resent; a received reply that violates its contract is permanently marked and never reusable. `check` is the
        post-receipt validation (citations/membership): reply faults mark the receipt, authority failures leave a valid receipt behind.
        """
        job_id = row["job_id"]
        call = self.store.one("SELECT * FROM calls WHERE job_id=? AND stage=? AND ref=?", (job_id, stage, ref))
        if call is None:
            raw, fixture_hash = lookup()
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
                raise ExtractionFailure("replay_response_unknown")
            if call["verdict"]:
                raise ReplyInvalid(call["verdict"])
            raw = json.loads(call["response"])
            if digest(raw) != call["response_digest"]:
                raise ExtractionFailure("receipt_integrity_failed")
            attempt = call["attempt_id"]
            try:
                result = parse(raw)
            except ReplyInvalid as exc:
                self._mark(attempt, exc.code)
                raise
        self._verify(ctx)
        if check is not None:
            try:
                result = check(result)
            except ReplyInvalid as exc:
                self._mark(attempt, exc.code)
                raise
        return result

    def _mark(self, attempt: str, code: str) -> None:
        self.db.execute("UPDATE calls SET verdict=? WHERE attempt_id=? AND verdict IS NULL", (code, attempt))

    # ------------------------------------------------------------------ stages -----------------------------------------

    def _events(self, job_id: str, rc: str) -> list[dict]:
        return [{"seq": e["seq"], "kind": e["kind"], "createdAt": e["created_at"], **json.loads(e["payload"])}
                for e in self.store.all("SELECT * FROM relation_events WHERE job_id=? AND relation_candidate_id=? ORDER BY seq", (job_id, rc))]

    def _has_saved_revalidation(self, job_id: str) -> bool:
        return any(self._saved_revalidation(job_id, c["relation_candidate_id"], self._events(job_id, c["relation_candidate_id"]))
                   for c in self.store.all("SELECT relation_candidate_id FROM relation_candidates WHERE job_id=?", (job_id,)))

    def _saved_revalidation(self, job_id: str, rc: str, events: list[dict]) -> str | None:
        """A requested revalidation whose receipt is saved but whose verdict was never committed (the process died between).

        It is a durable stage: the saved receipt is re-parsed and its verdict appended, never re-called and never overwriting
        history. If the request was withdrawn (admin reject) or already answered, the orphaned receipt is simply never consumed."""
        if not standing(events)["reviewPending"]:
            return None
        ref = f"{rc}|revalidation|{next_attempt(events, 'revalidation')['seq']}"
        return "revalidation" if self.store.one("SELECT 1 FROM calls WHERE job_id=? AND stage='verify-relation' AND ref=?", (job_id, ref)) else None

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
        response = self._receipted(row, ctx, fence, "relation", "job", key, lambda: fixtures.find("producer", "relation", key, ctx.synthetic), rules.parse_relations)
        candidates = []
        for merged in rules.merge([p.wire() for p in response.relations]):
            candidate = rules.evaluate(merged, ctx.view)
            candidate["relationCandidateId"] = "rc-" + digest({"version": CANDIDATE_VERSION, "requestDigest": key, "relationKey": merged["relationKey"]})
            candidates.append(candidate)

        def write():
            for c in candidates:
                self.db.execute("INSERT OR IGNORE INTO relation_candidates VALUES(?,?,?,?)", (job_id, c["relationCandidateId"], c["relationKey"], canonical(c)))
                if c["precheck"]["state"] != "pending":
                    self._append(job_id, c["relationCandidateId"], 1, "verdict", self._deterministic(c, next_attempt([], "initial")))
            self.db.execute("INSERT INTO stages VALUES(?,?,?,?,?)", (job_id, "relation", "job",
                canonical({"relations": len(candidates), "proposals": len(response.relations), "requestDigest": key}), now()))

        self._persist(row, ctx, fence, write)
        self._stage_saved("relation")

    @staticmethod
    def _deterministic(candidate: dict, attempt: dict) -> dict:
        return {"kind": "verdict", "attempt": attempt, "eligibility": candidate["precheck"]["state"],
                "reasons": candidate["precheck"]["reasons"], "claims": None, "verifier": "not-called", "requestDigest": None}

    def _verify_relation(self, row, ctx: Context, fixtures: Fixtures, fence: int, candidate_row, kind: str) -> None:
        job_id, rc = row["job_id"], candidate_row["relation_candidate_id"]
        candidate = json.loads(candidate_row["payload"])
        attempt = next_attempt(self._events(job_id, rc), kind)
        if candidate["precheck"]["state"] != "pending":
            verdict = self._deterministic(candidate, attempt)
        else:
            key = digest(rules.verifier_request(candidate, attempt))
            try:
                decision = self._receipted(row, ctx, fence, "verify-relation", f"{rc}|{kind}|{attempt['seq']}", key,
                    lambda: fixtures.find("verifier", "verify-relation", key, ctx.synthetic), lambda raw: rules.decide_relation(candidate, raw))
            except ReplyInvalid as exc:
                decision = {"eligibility": "reject", "reasons": [{"code": "verification_reply_invalid", "detail": exc.code}], "claims": None}
            verdict = {"kind": "verdict", "attempt": attempt, **decision, "verifier": "called", "requestDigest": key}

        def write():
            seq = self.store.one("SELECT COUNT(*) AS n FROM relation_events WHERE job_id=? AND relation_candidate_id=?", (job_id, rc))["n"] + 1
            self._append(job_id, rc, seq, "verdict", verdict)

        self._persist(row, ctx, fence, write)

    def _impact(self, row, ctx: Context, fixtures: Fixtures, fence: int, candidate_row) -> None:
        job_id, rc = row["job_id"], candidate_row["relation_candidate_id"]
        candidate = json.loads(candidate_row["payload"])
        allowed = {(q["documentId"], q["documentVersion"]) for q in candidate["quotes"]}
        documents = [document_view(ctx.docs[k].export) for k in sorted(allowed)]
        request = rules.impact_request(candidate, documents)
        key = digest(request)
        try:
            impacts = self._receipted(row, ctx, fence, "impact", rc, key, lambda: fixtures.find("producer", "impact", key, ctx.synthetic),
                rules.parse_impacts, lambda response: rules.evaluate_impacts(response, candidate, allowed, ctx.view.cite))
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
        try:
            decision = self._receipted(row, ctx, fence, "verify-impact", ic, key, lambda: fixtures.find("verifier", "verify-impact", key, ctx.synthetic),
                lambda raw: rules.decide_impact(candidate, raw))
        except ReplyInvalid as exc:
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
        binding = json.loads(row["binding"])
        calls = self.store.all("SELECT * FROM calls WHERE job_id=? ORDER BY started_at,attempt_id", (job_id,))
        stages = self.store.all("SELECT * FROM stages WHERE job_id=?", (job_id,))
        candidates = self.store.all("SELECT * FROM relation_candidates WHERE job_id=? ORDER BY relation_candidate_id", (job_id,))
        result = {"schemaVersion": SCHEMA, "jobId": job_id, "inputDigest": row["input_digest"], "state": row["state"], "phase": row["phase"],
            "resumeMode": row["resume_mode"], "failure": {"code": row["failure"], **({"detail": json.loads(row["detail"])} if row["detail"] else {})} if row["failure"] else None,
            "provenance": request.provenance.wire(), "binding": binding,
            "stages": {"relation": {"state": "complete", **json.loads(next(s["summary"] for s in stages if s["stage"] == "relation"))} if any(s["stage"] == "relation" for s in stages) else {"state": "pending"},
                       "impact": {"complete": sum(s["stage"] == "impact" for s in stages)}},
            "usage": {"executionMode": "replay", "replayCalls": sum(c["state"] == "received" for c in calls), "startedWithoutReceipt": sum(c["state"] == "started" for c in calls),
                      "providerCalls": 0, "modelCalls": 0, "creatorJobId": job_id},
            "calls": [{"stage": c["stage"], "state": c["state"], "requestDigest": c["request_digest"], "fixtureHash": c["fixture_hash"],
                       "responseDigest": c["response_digest"], "verdict": c["verdict"]} for c in calls]}
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
            impact_state = ("not-applicable" if state["eligibility"] in {"hold", "reject"} else "pending" if marker is None
                            else marker["status"] if marker["status"] != "complete" else "complete")
            relations.append({**payload, "eligibility": {"status": state["eligibility"], "reasons": state["reasons"], "revision": state["revision"],
                "reviewPending": state["reviewPending"]}, "history": events,
                "impact": {"status": impact_state, "labelNote": LABEL_NOTE, "candidates": found}})
        result["counts"] = {"relations": len(candidates), "eligibility": counts, "impactLabels": labels,
                            "impactCandidates": sum(len(v) for v in impacts.values())}
        result["relations"] = relations
        result["delivery"] = {"status": "current", "authority": "S2 job, read+quote-display rights and exact candidate set verified at delivery"}
        return result
