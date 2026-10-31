"""Independent S2-2 candidate ledger and recovery. No application, S1, PoC repository or ingestion-cursor writer.

Flow: freeze exact authorized observations (+ whole-event snapshot) -> extraction receipt -> per-whole-event comparison
receipts -> optional separate topic-producer receipt. Every stage commits its candidates and completion marker atomically.
Replay is authored-response replay, not independent AI inference. A live job (provenance executionMode live) is answered by the native provider
runtime instead: one reserved attempt per call slot, the raw receipt durable before any parsing, current model-send rights and frozen config at
reserve/send/receipt, and never an automatic resend. Candidates are never ALLOW/published in either mode.
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import extraction_replay as analysis
from . import extraction_topic as topics
from . import live_prompts
from .dependency_contracts import array, cites, invalid
from .extraction_contracts import (ADAPTER_VERSION, CANDIDATE_VERSION, LEDGER_VERSION, LIVE_ADAPTER_VERSION, MAX_COMPARISONS, MAX_DOCUMENTS, SCHEMA, Article,
    CitationFailure, ExtractionFailure, Mention, ObservationRef, ProviderResponseUnknown, ReplyInvalid, Submit, canonical, digest)
from .ingestion import Ingestor
from .ingestion import Store as IngestionStore
from .ingestion_contracts import Authority, Export, IngestionFailure, Inspect, byte_hash, now, reserved_state_roots
from .live_runtime import LiveDeferred, LiveFailure, LiveRuntime


_SQL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY, input_digest TEXT NOT NULL, request TEXT NOT NULL, binding TEXT NOT NULL,
 replay_hash TEXT NOT NULL, state TEXT NOT NULL, phase TEXT NOT NULL, failure TEXT, detail TEXT, resume_mode TEXT NOT NULL,
 fence INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stages(job_id TEXT NOT NULL REFERENCES jobs(job_id), stage TEXT NOT NULL, summary TEXT NOT NULL,
 completed_at TEXT NOT NULL, PRIMARY KEY(job_id,stage));
CREATE TABLE IF NOT EXISTS calls(attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id), stage TEXT NOT NULL,
 ref TEXT NOT NULL, request_digest TEXT NOT NULL, fixture_hash TEXT NOT NULL, state TEXT NOT NULL, response TEXT, response_digest TEXT,
 verdict TEXT, started_at TEXT NOT NULL, received_at TEXT, UNIQUE(job_id,stage,ref));
CREATE TABLE IF NOT EXISTS event_candidates(job_id TEXT NOT NULL REFERENCES jobs(job_id), event_candidate_id TEXT NOT NULL,
 mention_candidate_id TEXT NOT NULL, document_id TEXT NOT NULL, document_version TEXT NOT NULL, raw_version TEXT NOT NULL,
 local_mention_id TEXT NOT NULL, state TEXT NOT NULL, reason TEXT, payload TEXT NOT NULL, PRIMARY KEY(job_id,event_candidate_id));
CREATE TABLE IF NOT EXISTS comparisons(job_id TEXT NOT NULL, event_candidate_id TEXT NOT NULL, target_event_id TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(job_id,event_candidate_id,target_event_id),
 FOREIGN KEY(job_id,event_candidate_id) REFERENCES event_candidates(job_id,event_candidate_id));
CREATE TABLE IF NOT EXISTS dispositions(job_id TEXT NOT NULL, event_candidate_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(job_id,event_candidate_id), FOREIGN KEY(job_id,event_candidate_id) REFERENCES event_candidates(job_id,event_candidate_id));
CREATE TABLE IF NOT EXISTS topic_candidates(job_id TEXT NOT NULL REFERENCES jobs(job_id), topic_candidate_id TEXT NOT NULL,
 payload TEXT NOT NULL, PRIMARY KEY(job_id,topic_candidate_id));
"""
_IMMUTABLE = ("meta", "stages", "event_candidates", "comparisons", "dispositions", "topic_candidates")
_FILES = {"extraction.sqlite3", "extraction.sqlite3-wal", "extraction.sqlite3-shm", "extraction.lock"}
_CITATION_CODES = {"locator_interval_unmapped", "source_mapping_invalid"}
_RELATIONS = ("SAME", "DIFFERENT", "FOLLOWS", "CONFLICT", "HOLD")


class Store:
    def __init__(self, root: Path, ingestion_root: Path, *, existing: bool = False):
        root, ingestion_root = Path(os.path.abspath(root)), Path(os.path.abspath(ingestion_root))
        forbidden = [*reserved_state_roots(), ingestion_root]
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
            # Mixed app/S1/ingestion directories and unknown files are never adopted as an extraction ledger.
            raise ExtractionFailure("state_namespace_conflict")
        os.chmod(root, 0o700)
        self.lock = os.open(root / "extraction.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(self.lock, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.lock)
            raise ExtractionFailure("extraction_busy") from exc
        try:
            database = root / "extraction.sqlite3"
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
            self.db.execute("CREATE TRIGGER IF NOT EXISTS immutable_jobs_input BEFORE UPDATE OF job_id,input_digest,request,binding,replay_hash,created_at ON jobs BEGIN SELECT RAISE(ABORT,'immutable'); END")
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
        """Read-only downstream access (same policy as the ingestion consumer): shared non-blocking flock on the existing lock, no
        mkdir/chmod/create/PRAGMA/schema/WAL write, immutable read-only SQLite. A non-empty -wal is committed data a reader must not
        ignore or recover, so the operator runs the extraction writer (resume) first. An active writer makes the reader fail busy."""
        database, lock = root / "extraction.sqlite3", root / "extraction.lock"
        if not root.is_dir() or not database.is_file() or not lock.is_file():
            raise ExtractionFailure("extraction_state_missing")
        if any(p.name not in _FILES or p.is_symlink() for p in root.iterdir()):
            raise ExtractionFailure("state_namespace_conflict")
        self.lock = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.close()
            raise ExtractionFailure("extraction_busy") from exc
        try:
            wal = root / "extraction.sqlite3-wal"
            if wal.exists() and wal.stat().st_size > 0:
                raise ExtractionFailure("extraction_recovery_required")
            self.db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA query_only=ON")
            self.db.execute("SELECT 1 FROM jobs LIMIT 1")
            meta = self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
            if meta is None or meta["value"] != LEDGER_VERSION:
                raise ExtractionFailure("ledger_version_unknown")
        except sqlite3.DatabaseError as exc:
            self.close()
            raise ExtractionFailure("extraction_state_invalid") from exc
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


class Sources:
    """Authorized exact-observation reader. Each call re-reads current registry authority; nothing is cached."""

    def __init__(self, directory: Path, authority: Authority):
        self.directory, self.authority = directory, authority

    def _run(self, call, send=None):
        if send is not None and self.authority is None:
            raise ExtractionFailure("source_unauthorized")
        try:
            store = IngestionStore(self.directory, existing=True)
        except IngestionFailure as exc:
            raise ExtractionFailure(exc.code) from exc
        try:
            return call(Ingestor(store, self.authority if send is None else self.authority.sending(*send)))
        except IngestionFailure as exc:
            if exc.code in _CITATION_CODES:
                raise CitationFailure(exc.code) from exc
            raise ExtractionFailure(exc.code) from exc
        finally:
            store.close()

    def export(self, ref: ObservationRef, *, send: tuple[str, str] | None = None) -> dict:
        """The exact observation under current read + quote-display authority. `send=(purpose, recipient)` makes it the live model-send check for this one
        document: it additionally needs `model-send` and that exact purpose and recipient currently granted. The export is the same either way."""
        return self._run(lambda ingestor: ingestor.export(Export.model_validate(ref.export_wire())), send)

    def authorize_model_send(self, ref: ObservationRef, purpose: str, recipient: str) -> None:
        self.export(ref, send=(purpose, recipient))

    def resolve(self, ref: ObservationRef, locator_id: str, start: int, end: int) -> dict:
        request = Inspect.model_validate({"schemaVersion": ref.export_wire()["schemaVersion"], "roundId": ref.round_id, "sourceId": ref.source_id,
            "documentId": ref.document_id, "documentVersion": ref.document_version, "locatorId": locator_id, "start": start, "end": end, "limit": 1})
        return self._run(lambda ingestor: ingestor.inspect(request))["resolvedLocator"]


class Fixtures:
    """Authored replay inputs for this process only; their hashes are frozen/recorded, their bytes are not authority."""

    def __init__(self, replay: bytes | None, topic: bytes | None):
        self.replay_hash = byte_hash(replay) if replay is not None else None
        self.topic_raw = topic
        self.doc = None
        self._index = None
        if replay is not None:
            try:
                self.doc = json.loads(replay)
            except (ValueError, UnicodeError) as exc:
                raise ExtractionFailure("replay_fixture_invalid") from exc

    def require(self) -> dict:
        if self.doc is None:
            raise ExtractionFailure("replay_fixture_required")
        return self.doc

    def index(self) -> dict:
        """The whole fixture validated once (duplicates included) as {(stage, requestDigest): authored response}."""
        if self._index is None:
            self._index = analysis.index(self.require())
        return self._index

    def producer(self, synthetic: bool):
        if self.topic_raw is None:
            raise ExtractionFailure("topic_replay_required")
        return topics.ReplayProducer(self.topic_raw, synthetic)


class LiveAccess:
    """Lazy, process-local access to the live runtime. Replay, inspect, cancel, export and the decode of a stored receipt never read the environment
    or a key: `config` (current environment, no secrets) is built only to freeze a new live job, `sender` (environment + keys + budget) only at the
    first real send, and `frozen` rebuilds a decoder from the job's own stored binding. A refusal of the runtime surfaces as its stable code."""

    def __init__(self, from_env=LiveRuntime.from_env, from_binding=LiveRuntime.from_binding):
        self._from_env, self._from_binding, self._built = from_env, from_binding, {}

    def _get(self, key, make):
        if key not in self._built:
            try:
                self._built[key] = make()
            except LiveFailure as exc:
                raise ExtractionFailure(exc.code) from exc
        return self._built[key]

    def config(self) -> LiveRuntime:
        return self._get("config", lambda: self._from_env(need_send=False))

    def sender(self) -> LiveRuntime:
        return self._get("send", lambda: self._from_env(need_send=True))

    def frozen(self, binding: dict) -> LiveRuntime:
        return self._get(("frozen", binding["identity"]), lambda: self._from_binding(binding))


@dataclass
class Doc:
    key: str
    ref: ObservationRef
    export: dict
    article: Article
    binding: dict


@dataclass
class Group:
    event_id: str
    revision: str
    members: list  # [(docKey, Mention)]
    articles: list  # [Article] of the unique documents of this whole event, in documents order
    digest: str
    documents: list  # unique docKeys


@dataclass
class Context:
    request: Submit
    synthetic: bool
    docs: dict
    incoming: str
    groups: list
    snapshot_digest: str

    def by_version(self, version: str) -> Doc:
        # Same documentVersion observed twice resolves identically; deterministic key order, never "newest".
        return next(d for k, d in sorted(self.docs.items()) if d.ref.document_version == version)

    def by_document(self, document_id: str, version: str) -> Doc | None:
        found = [d for k, d in sorted(self.docs.items()) if (d.ref.document_id, d.ref.document_version) == (document_id, version)]
        return found[0] if found else None


@dataclass
class Admitted:
    """The prepared values of a job `freeze` is about to register. `Extractor.admission` discards them."""
    ctx: Context
    binding: dict
    input_digest: str
    frozen_hash: str


def doc_key(ref: ObservationRef) -> str:
    return digest(ref.wire())


def current(binding: dict) -> bool:
    """A job is native only when its frozen adapter is this build's (replay or live). Anything else (ledger rows written before the native
    cutover) stays readable as history but is never resumed, delivered or re-analysed: its analysis contract cannot be reproduced."""
    adapter = binding.get("adapter")
    version = adapter.get("version") if isinstance(adapter, dict) else None
    return version == ADAPTER_VERSION or (version == LIVE_ADAPTER_VERSION and "live" in binding)


def is_live(binding: dict) -> bool:
    """A live job's binding carries the frozen runtime under `live`; a replay job's carries its fixture identity under `replay`, never both."""
    return "live" in binding


def analysis_version(binding: dict) -> str:
    return (binding["live"] if is_live(binding) else binding["replay"])["analysisVersion"]


def _receipt_total(receipts: list[dict], group: str, name: str):
    values = [(r.get(group) or {}).get(name) for r in receipts]
    return sum(values) if all(type(v) is int for v in values) else None


def _usd_total(receipts: list[dict], name: str) -> str | None:
    try:
        return format(sum((Decimal(r["cost"][name]) for r in receipts), Decimal(0)), "f")
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None


def live_usage(job_id: str, calls) -> dict:
    """Truthful live counts from the stored receipts alone (no runtime, environment or key). `providerCalls` counts every attempt that was or may have
    been transmitted; the token/USD totals are over received receipts and are null (unknown, never zero) when any value is unreported OR when a
    transmitted call has no receipt, whose real usage this ledger cannot know."""
    receipts = [json.loads(c["response"]) for c in calls if c["state"] == "received"]
    unreceipted = sum(c["state"] == "started" for c in calls)
    totals = {} if unreceipted else {"inputTokens": _receipt_total(receipts, "usage", "inputTokens"), "outputTokens": _receipt_total(receipts, "usage", "outputTokens"),
                                     "reasoningTokens": _receipt_total(receipts, "usage", "reasoningTokens"), "estimatedUsd": _usd_total(receipts, "estimatedUsd"),
                                     "chargedUsd": _usd_total(receipts, "chargedUsd")}
    return {"executionMode": "live", "replayCalls": 0, "providerCalls": len(receipts) + unreceipted, "receivedCalls": len(receipts),
            "startedWithoutReceipt": unreceipted, "unsentCalls": sum(c["state"] == "unsent" for c in calls),
            "paidModelCalls": sum(any(type((r.get("usage") or {}).get(n)) is int and r["usage"][n] > 0 for n in ("inputTokens", "outputTokens")) for r in receipts),
            **{name: totals.get(name) for name in ("inputTokens", "outputTokens", "reasoningTokens", "estimatedUsd", "chargedUsd")}, "creatorJobId": job_id}


def live_call(binding: dict, call) -> dict:
    """One stored call as delivered: purpose/recipient come from the frozen binding, outcome facts from the stored receipt (null when there is none)."""
    stage = binding["live"]["runtime"]["stages"][call["stage"]]
    receipt = json.loads(call["response"]) if call["state"] == "received" else {}
    cost = receipt.get("cost")
    return {"stage": call["stage"], "state": call["state"], "requestDigest": call["request_digest"], "fixtureHash": None, "responseDigest": call["response_digest"],
            "verdict": call["verdict"], "attemptId": call["attempt_id"], "recipient": stage["recipient"], "purpose": stage["purpose"],
            "httpStatus": (receipt.get("http") or {}).get("status"), "model": (receipt.get("model") or {}).get("reported"), "usage": receipt.get("usage"),
            "cost": {k: cost.get(k) for k in ("usageKnown", "estimatedUsd", "chargedUsd")} if isinstance(cost, dict) else None}


def save_live_deferral(store, attempt: str, proof: dict) -> None:
    """Persist causal pre-HTTP evidence independently of a contended monetary ledger, atomically with the native call state."""
    with store.transaction():
        row = store.one("SELECT state,response FROM calls WHERE attempt_id=?", (attempt,))
        if row is None or row["state"] != "started" or row["response"] is not None or proof["attemptId"] != attempt:
            raise ExtractionFailure("receipt_request_mismatch")
        store.db.execute("INSERT INTO meta VALUES(?,?)", ("operating-deferral:" + attempt + ":" + uuid.uuid4().hex, canonical(proof)))
        store.db.execute("UPDATE calls SET state='deferred' WHERE attempt_id=?", (attempt,))


def load_live_deferral(store, attempt: str) -> dict | None:
    row = store.one("SELECT value FROM meta WHERE key LIKE ? ORDER BY rowid DESC LIMIT 1", ("operating-deferral:" + attempt + ":%",))
    return json.loads(row["value"]) if row else None


def open_legacy_history(root: Path, ingestion_root: Path, job_id: str) -> "Store | None":
    """Ledger-only, read-only preflight. Returns an open read-only Store when the ledger holds `job_id` under a non-current adapter, else None.

    It never reads fixtures or source authority and never opens the writer (no chmod/DDL/WAL write). Anything it cannot answer (no ledger, busy,
    recovery needed, foreign namespace, unknown job, unreadable row) is None, so the ordinary path reports that exactly as before."""
    try:
        store = Store(root, ingestion_root, existing=True)
    except (ExtractionFailure, OSError):
        return None
    try:
        row = store.one("SELECT binding FROM jobs WHERE job_id=?", (job_id,))
        if row is not None and not current(json.loads(row["binding"])):
            return store
    except (sqlite3.Error, ValueError, TypeError):
        pass
    store.close()
    return None


def locators_containing(document: dict, start: int, end: int) -> list[str]:
    """Whole interval must lie inside one mapped run (same rule as S1 exact), never across removed/generated text."""
    return [r["locatorId"] for r in document["rawLocators"] if r["start"] <= start < end <= r["end"]]


def cite_exact(sources: "Sources", ref: ObservationRef, export: dict, start: int, end: int, quote: str) -> dict:
    """Exact quote -> whole mapped locator run -> ingestion source resolver. Shared by every consumer of exact citations."""
    document = export["document"]
    text = document["text"]
    if not 0 <= start < end <= len(text) or text[start:end] != quote:
        raise CitationFailure("quote_mismatch")
    locators = locators_containing(document, start, end)
    if not locators:
        raise CitationFailure("raw_locator_mismatch")
    resolved = sources.resolve(ref, locators[0], start, end)
    if "".join(s["text"] for s in resolved["segments"]) != quote:
        raise CitationFailure("source_mapping_invalid")
    return {"evidenceId": "ev-" + digest([ref.document_version, start, end])[:32], "documentId": ref.document_id,
            "documentVersion": ref.document_version, "rawVersion": ref.raw_version, "textArtifactId": document["textArtifactId"],
            "offsetUnit": "unicode_code_point", "start": start, "end": end, "quote": quote, "inputKind": document["inputKind"],
            "rawLocatorIds": locators, "sourceSegments": [{k: v for k, v in s.items() if k != "text"} for s in resolved["segments"]]}


class Extractor:
    def __init__(self, store: Store, sources: Sources, live: "LiveAccess | None" = None):
        self.store, self.sources = store, sources
        self.live = live or LiveAccess()
        self.db = store.db

    # ------------------------------------------------------------------ freeze / verify ---------------------------------

    def _context(self, request: Submit) -> Context:
        synthetic = request.provenance.source_kind == "synthetic"
        refs: dict[str, ObservationRef] = {doc_key(request.incoming): request.incoming}
        for event in request.snapshot.events:
            for member in event.members:
                refs.setdefault(doc_key(member.observation), member.observation)
        if len(refs) > MAX_DOCUMENTS:
            raise ExtractionFailure("document_limit_exceeded")
        docs = {}
        for key, ref in refs.items():
            export = self.sources.export(ref)
            projected = analysis.article(export, synthetic)
            docs[key] = Doc(key, ref, export, projected, analysis.bind(export, projected))
        incoming = doc_key(request.incoming)
        groups, seen = [], set()
        for event in request.snapshot.events:
            members, keys = [], []
            for member in event.members:
                key = doc_key(member.observation)
                doc = docs[key]
                mention = analysis.member_mention(member.mention, doc.article)
                identity = (doc.ref.document_version, mention.mention_id)
                if doc.ref.document_version == docs[incoming].ref.document_version or identity in seen:
                    raise ExtractionFailure("snapshot_member_invalid")
                seen.add(identity)
                members.append((key, mention))
                if key not in keys:
                    keys.append(key)
            articles = [docs[k].article for k in keys]
            group_digest = digest({"eventId": event.event_id, "revision": event.revision,
                                   "members": [{"binding": digest(docs[k].binding), "mention": m.model_dump(mode="json")} for k, m in members]})
            groups.append(Group(event.event_id, event.revision, members, articles, group_digest, keys))
        snapshot_digest = digest({"revision": request.snapshot.revision, "events": sorted([g.event_id, g.revision, g.digest] for g in groups)})
        return Context(request, synthetic, docs, incoming, groups, snapshot_digest)

    def _binding(self, ctx: Context, source: dict, live: bool = False) -> dict:
        """The immutable job binding. `source` is the replay identity (+fixtureHash) or, for `live`, the frozen runtime block; the two never share a key."""
        request = ctx.request
        if live:
            adapter = {"version": LIVE_ADAPTER_VERSION, "candidate": CANDIDATE_VERSION, "fingerprint": analysis.fingerprint(source, request.catalogue, LIVE_ADAPTER_VERSION)}
            mode = {"live": source}
        else:
            identity = {k: source[k] for k in ("format", "synthetic", "recordingKind", "promptVersion", "analysisVersion")}
            adapter = {"version": ADAPTER_VERSION, "candidate": CANDIDATE_VERSION, "fingerprint": analysis.fingerprint(identity, request.catalogue)}
            mode = {"replay": source}
        return {"adapter": adapter,
                **mode,
                "catalogue": {"revision": request.catalogue.revision, "digest": digest(request.catalogue.wire())},
                "incoming": ctx.incoming, "documents": {k: ctx.docs[k].binding for k in sorted(ctx.docs)},
                "snapshot": {"revision": request.snapshot.revision, "digest": ctx.snapshot_digest,
                             "events": [{"eventId": g.event_id, "revision": g.revision, "digest": g.digest} for g in ctx.groups]},
                "topic": request.topic.wire() if request.topic else None}

    def _verify(self, ctx: Context, send: tuple | None = None) -> None:
        """Current read/store/quote authority and exact immutable binding for every document, now. For a live call, `send` is (purpose, recipient,
        document keys): every document in it must also currently allow model-send for exactly that purpose and recipient."""
        for key, doc in ctx.docs.items():
            export = self.sources.export(doc.ref, send=(send[0], send[1]) if send is not None and key in send[2] else None)
            bound = analysis.bind(export, analysis.article(export, ctx.synthetic))
            if bound["grant"] != doc.binding["grant"]:
                raise ExtractionFailure("grant_revision_changed")
            if bound != doc.binding:
                raise ExtractionFailure("document_binding_changed")

    def _ground_members(self, ctx: Context) -> None:
        """Snapshot member evidence must be exact whole mapped runs resolved by ingestion, not merely Evidence.matches."""
        for group in ctx.groups:
            for key, mention in group.members:
                for evidence in mention.evidence:
                    try:
                        self._cite(ctx, ctx.docs[key], evidence.start, evidence.end, evidence.quote)
                    except CitationFailure as exc:
                        raise ExtractionFailure("snapshot_member_unmapped") from exc

    def _check_binding(self, ctx: Context, row) -> None:
        stored = json.loads(row["binding"])
        if not current(stored):
            raise ExtractionFailure("analysis_contract_changed")
        fresh = self._binding(ctx, stored["live"], live=True) if is_live(stored) else self._binding(ctx, stored["replay"])
        if fresh == stored:
            return
        for key, binding in stored["documents"].items():
            if fresh["documents"].get(key) != binding:
                raise ExtractionFailure("grant_revision_changed" if fresh["documents"].get(key, {}).get("grant") != binding["grant"] else "document_binding_changed")
        if fresh["adapter"] != stored["adapter"]:
            raise ExtractionFailure("analysis_contract_changed")
        raise ExtractionFailure("job_binding_changed")

    # ------------------------------------------------------------------ commands -----------------------------------------

    def _job(self, job_id: str):
        row = self.store.one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        if row is None:
            raise ExtractionFailure("job_not_found")
        return row

    def require_legacy(self, job_id: str) -> None:
        """Under the writer lock already held by this Store: the job must still be a stored legacy one (jobs are immutable, so this only fails if the ledger changed)."""
        if current(json.loads(self._job(job_id)["binding"])):
            raise ExtractionFailure("job_binding_changed")

    def _admit(self, request: Submit, fixtures: Fixtures) -> "Admitted | None":
        """Everything `freeze` decides before its write transaction, in `freeze`'s order, against whichever Store this extractor holds (a read-only one
        suffices): the stored legacy binding is refused first, then the job's identity (replay fixture header or live runtime binding) and input
        digest. None means the job already exists with this very input. Only for a NEW job it also builds and validates the source context, the
        grounded snapshot members and the frozen binding, and returns them for `freeze` to register. Nothing is written here."""
        row = self.store.one("SELECT * FROM jobs WHERE job_id=?", (request.job_id,))
        if row is not None and not current(json.loads(row["binding"])):
            # A stored legacy job is history: say so before its fixture bytes (old format or none) are looked at.
            raise ExtractionFailure("analysis_contract_changed")
        live = request.provenance.execution_mode == "live"
        if live:
            if fixtures.replay_hash is not None or fixtures.topic_raw is not None:
                raise ExtractionFailure("fixture_not_allowed")
            runtime = self.live.config().binding()
            identity = {"promptVersion": request.prompt_version, "analysisVersion": "live-" + runtime["identity"]}
            input_digest = digest({"request": request.wire(), "liveBindingDigest": runtime["identity"]})
            frozen_hash = runtime["identity"]  # stored in the immutable `replay_hash` column: the external contract this job is bound to
        else:
            identity = analysis.identity(fixtures.require(), request.provenance, request.prompt_version)
            input_digest = digest({"request": request.wire(), "replayFixtureHash": fixtures.replay_hash})
            frozen_hash = fixtures.replay_hash
        if row is not None:
            if row["input_digest"] != input_digest:
                raise ExtractionFailure("job_input_conflict")
            return None
        ctx = self._context(request)
        self._ground_members(ctx)
        if live:
            binding = self._binding(ctx, {**identity, "runtime": runtime, "bindingDigest": runtime["identity"]}, live=True)
        else:
            binding = self._binding(ctx, {**identity, "fixtureHash": fixtures.replay_hash})
        return Admitted(ctx, binding, input_digest, frozen_hash)

    def admission(self, request: Submit, fixtures: Fixtures) -> str:
        """`new` when `freeze` of this request would register a job, `existing` when the job is already stored with exactly this input. Every refusal
        `freeze` would raise before its transaction is raised here (`analysis_contract_changed`, `job_input_conflict`, fixture/runtime, source and
        snapshot-grounding failures); nothing is written, so it also works on a read-only Store."""
        return "existing" if self._admit(request, fixtures) is None else "new"

    def freeze(self, request: Submit, fixtures: Fixtures) -> None:
        """The only registration path: durably freeze the exact bound input as `queued`, with no provider/replay call or candidate effect.

        A replay job's replay file is part of the frozen input (its hash is in the input digest and the binding), so it is required here, but only its
        header is read; its records are validated by the first lookup. A live job freezes the complete secret-free runtime binding instead (current
        environment, no network, no key) and takes no fixture. A job that already exists is not touched at all: same input returns without re-freezing,
        resuming, resetting a stopped job or reading authority; another input is `job_input_conflict` with nothing written. Execution is `resume`'s business."""
        admitted = self._admit(request, fixtures)
        if admitted is None:
            return
        # The exact binding is durable before any replay/provider call; nothing below can change it.
        with self.store.transaction(lambda: self._verify(admitted.ctx)):
            self.db.execute("INSERT INTO jobs(job_id,input_digest,request,binding,replay_hash,state,phase,resume_mode,created_at,updated_at) VALUES(?,?,?,?,?,'queued','extract','resume',?,?)",
                (request.job_id, admitted.input_digest, canonical(request.wire()), canonical(admitted.binding), admitted.frozen_hash, now(), now()))

    def run(self, request: Submit, fixtures: Fixtures, *, initial_only: bool = False) -> dict:
        """Convenience: `freeze` then `resume` the same job."""
        self.freeze(request, fixtures)
        return self.resume(request.job_id, fixtures, initial_only=initial_only)

    def resume(self, job_id: str, fixtures: Fixtures, *, initial_only: bool = False) -> dict:
        row = self._job(job_id)
        binding = json.loads(row["binding"])
        if not current(binding):
            # A job frozen under another analysis contract is history: refuse before any fixture, source, authority or state access.
            raise ExtractionFailure("analysis_contract_changed")
        if is_live(binding):
            if fixtures.replay_hash is not None or fixtures.topic_raw is not None:
                raise ExtractionFailure("fixture_not_allowed")  # a live job is answered by the provider, never by an authored file
        elif fixtures.replay_hash is not None and fixtures.replay_hash != row["replay_hash"]:
            raise ExtractionFailure("replay_fixture_changed")
        if initial_only:
            self._take_initial_dispatch(job_id)
        self._execute(row, fixtures)
        return self.result(job_id)

    def _take_initial_dispatch(self, job_id: str) -> None:
        """Under the writer lock, atomically: the automatic (service) dispatch of a job may happen once and only for a job nothing has touched.
        A mark, a started call or any state beyond `queued` means a previous dispatch already ran (or an operator did): refuse with no effect.
        Explicit operator recovery is plain `resume`, which never consults the mark."""
        mark = "initial-dispatch:" + job_id
        with self.store.transaction():
            row = self._job(job_id)
            if (row["state"] != "queued" or self.db.execute("SELECT 1 FROM meta WHERE key=?", (mark,)).fetchone()
                    or self.db.execute("SELECT 1 FROM calls WHERE job_id=? LIMIT 1", (job_id,)).fetchone()):
                raise ExtractionFailure("initial_dispatch_taken")
            self.db.execute("INSERT INTO meta VALUES(?,?)", (mark, now()))

    def inspect(self, job_id: str) -> dict:
        self._job(job_id)
        return self.result(job_id)

    def export(self, job_id: str) -> tuple[Submit, dict]:
        """Read-only snapshot for a private downstream consumer: the immutable frozen request and the delivered result, only while
        the job is ready AND its whole binding/rights are currently verified. Anything else is a failure code, never partial data."""
        row = self._job(job_id)
        if row["state"] != "ready":
            raise ExtractionFailure("upstream_not_ready", {"state": row["state"]})
        result = self.result(job_id)
        if result["delivery"]["status"] != "current":
            raise ExtractionFailure(result["delivery"]["code"])
        return Submit.model_validate_json(row["request"]), result

    def cancel(self, job_id: str) -> dict:
        with self.store.transaction():
            row = self._job(job_id)
            if row["state"] not in {"ready", "cancelled"}:
                self.db.execute("UPDATE jobs SET state='cancelled',phase='cancelled',resume_mode='none',fence=fence+1,updated_at=? WHERE job_id=?", (now(), job_id))
        return self.result(job_id)

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
        if row["state"] in {"ready", "cancelled", "reconciling"}:
            return
        if self.store.one("SELECT 1 FROM calls WHERE job_id=? AND state='started' AND response IS NULL", (job_id,)):
            # Holding the lock proves the previous process stopped, not that its call was never sent: never auto-resend.
            code = "live_response_unknown" if is_live(json.loads(row["binding"])) else "replay_response_unknown"
            self._status(job_id, fence, "reconciling", row["phase"], code, "reconcile_only")
            return
        request = Submit.model_validate_json(row["request"])
        stage = row["phase"] if row["phase"] in {"extract", "compare", "topic"} else "extract"
        self._status(job_id, fence, "running", row["phase"])
        try:
            ctx = self._context(request)
            self._check_binding(ctx, row)
            for stage, run in (("extract", self._extract), ("compare", self._compare), ("topic", self._topic)):
                if not self.store.one("SELECT 1 FROM stages WHERE job_id=? AND stage=?", (job_id, stage)):
                    self._status(job_id, fence, "running", stage)
                    run(row, ctx, fixtures, fence)
            self._status(job_id, fence, "ready", "complete", resume="none")
        except ProviderResponseUnknown as exc:
            self._status(job_id, fence, "reconciling", stage, exc.code, "reconcile_only")
        except ExtractionFailure as exc:
            self._status(job_id, fence, "stopped", stage, exc.code, detail=exc.detail)
        except (sqlite3.Error, OSError):
            self._status(job_id, fence, "stopped", stage, "persistence_failed")

    def _persist(self, row, ctx: Context, fence: int, stage: str, write, send=None) -> None:
        """Candidates and the stage completion marker commit together, under the current fence and rights (and, for a live stage, the model-send
        rights of every document that was sent)."""
        job_id = row["job_id"]

        def guard():
            self._guard(job_id, fence)
            self._verify(ctx, send)

        with self.store.transaction(guard):
            summary = write()
            self.db.execute("INSERT INTO stages VALUES(?,?,?,?)", (job_id, stage, canonical(summary), now()))

    def _reserve(self, job_id: str, fence: int, stage: str, ref: str, key: str, fixture_hash: str) -> str:
        attempt = "attempt-" + uuid.uuid4().hex
        with self.store.transaction(lambda: self._guard(job_id, fence)):
            self.db.execute("INSERT INTO calls(attempt_id,job_id,stage,ref,request_digest,fixture_hash,state,started_at) VALUES(?,?,?,?,?,?,'started',?)",
                (attempt, job_id, stage, ref, key, fixture_hash, now()))
        return attempt

    def _receive(self, attempt: str, raw) -> None:
        self.db.execute("UPDATE calls SET state='received',response=?,response_digest=?,received_at=? WHERE attempt_id=? AND state='started'",
            (canonical(raw), digest(raw), now(), attempt))

    def _receipted(self, row, ctx: Context, fence: int, stage: str, ref: str, key: str, fixture_hash, lookup, fresh, saved, check=None):
        """One provider-style attempt. A saved receipt is validated/saved only; a started call without receipt is unknown.

        `lookup()` must fully validate the fixture and find the authored response BEFORE a call is reserved, so an invalid fixture
        can never become a received receipt that a later fixture-less resume would sanitize. `fresh/saved` are the pure production
        parsers; `check` is the post-receipt validation (membership/citations) whose reply faults mark the receipt rejected while
        environment/authority failures leave a valid receipt for a later revalidating resume.
        """
        job_id = row["job_id"]
        call = self.store.one("SELECT * FROM calls WHERE job_id=? AND stage=? AND ref=?", (job_id, stage, ref))
        if call is None:
            raw = lookup()
            self._verify(ctx)
            attempt = self._reserve(job_id, fence, stage, ref, key, fixture_hash())
            try:
                result = fresh(raw)
            except ReplyInvalid as exc:
                # Received but contract-invalid: auditable, permanently unusable, never retried or repaired.
                self._receive(attempt, raw)
                self.db.execute("UPDATE calls SET verdict=? WHERE attempt_id=? AND verdict IS NULL", (exc.code, attempt))
                raise
            self._receive(attempt, raw)
        else:
            if call["request_digest"] != key:
                raise ExtractionFailure("receipt_request_mismatch")
            if call["state"] != "received":
                raise ExtractionFailure("replay_response_unknown")
            if call["verdict"]:
                raise ExtractionFailure(call["verdict"])
            raw = json.loads(call["response"])
            if digest(raw) != call["response_digest"]:
                raise ExtractionFailure("receipt_integrity_failed")
            attempt = call["attempt_id"]
            try:
                result = saved(raw)
            except ReplyInvalid as exc:
                self.db.execute("UPDATE calls SET verdict=? WHERE attempt_id=? AND verdict IS NULL", (exc.code, attempt))
                raise
        self._verify(ctx)
        if check is not None:
            try:
                result = check(result)
            except ReplyInvalid as exc:
                self.db.execute("UPDATE calls SET verdict=? WHERE attempt_id=? AND verdict IS NULL", (exc.code, attempt))
                raise
        return result

    # ------------------------------------------------------------------ live provider call ---------------------------------

    def _sending(self, stored: dict, stage: str, keys) -> tuple | None:
        """(purpose, recipient, document keys) of the outbound live call of `stage`, from the FROZEN runtime. None for replay, which sends nothing anywhere."""
        if not is_live(stored):
            return None
        decoder = self.live.frozen(stored["live"]["runtime"])
        return decoder.purpose(stage), decoder.recipient(stage), frozenset(keys)

    def _unsent(self, attempt: str, code: str) -> None:
        """The reservation never reached the provider (authority/config/budget refused before the single send): terminal for this call slot."""
        self.db.execute("UPDATE calls SET state='unsent',verdict=? WHERE attempt_id=? AND state='started' AND response IS NULL", (code, attempt))

    def _reject(self, attempt: str, code: str) -> None:
        self.db.execute("UPDATE calls SET verdict=? WHERE attempt_id=? AND verdict IS NULL", (code, attempt))

    def _live_receipted(self, row, ctx: Context, fence: int, stage: str, ref: str, key: str, payload: dict, keys: list, parse, check=None):
        """One provider attempt, in the only safe order: pure prepare -> current config + model-send rights -> durable reservation -> ONE send ->
        durable raw receipt -> strict decode -> exact parse/grounding -> rights again. `keys` are the documents whose text is in `payload`.

        A call slot (job, stage, ref) has exactly one attempt: a reservation without a receipt is a possibly-sent request and is never resent
        (reconciling), a reservation refused before the send is terminal `unsent`, and a received reply that cannot be used keeps its verdict and is
        never repaired by another call. A stored receipt is decoded from the FROZEN binding, so recovery needs neither the environment nor a key."""
        job_id = row["job_id"]
        live = json.loads(row["binding"])["live"]
        frozen = live["runtime"]
        payload = {**payload, "citationSources": [live_prompts.source(ctx.docs[k].export, ctx.docs[k].article) for k in sorted(set(keys))]}
        decoder = self.live.frozen(frozen)
        send = (decoder.purpose(stage), decoder.recipient(stage), frozenset(keys))
        call = self.store.one("SELECT * FROM calls WHERE job_id=? AND stage=? AND ref=?", (job_id, stage, ref))
        if call is None or call["state"] == "deferred":
            sender = self.live.sender()
            if not sender.accepts(frozen):
                raise ExtractionFailure("live_config_changed")
            try:
                prepared = sender.prepare(stage, payload)
            except LiveFailure as exc:
                raise ExtractionFailure(exc.code) from exc
            if (prepared["purpose"], prepared["recipient"]) != send[:2]:
                raise ExtractionFailure("live_prepared_invalid")
            self._verify(ctx, send)
            unsent_proof = None
            if call is None:
                attempt = self._reserve(job_id, fence, stage, ref, key, live["bindingDigest"])
            else:
                if call["request_digest"] != key or "funding" not in frozen:
                    raise ExtractionFailure("receipt_request_mismatch")
                attempt = call["attempt_id"]
                unsent_proof = load_live_deferral(self.store, attempt)
                self.db.execute("UPDATE calls SET state='started' WHERE attempt_id=? AND state='deferred'", (attempt,))

            def authorize():
                # Runs inside send(), immediately before the one request: config, fence/cancel and every sent document's current rights.
                if not sender.accepts(frozen):
                    raise ExtractionFailure("live_config_changed")
                self._guard(job_id, fence)
                self._verify(ctx, send)

            try:
                if unsent_proof is None:
                    receipt = sender.send(prepared, attempt_id=attempt, authorize=authorize)
                else:
                    receipt = sender.send(prepared, attempt_id=attempt, authorize=authorize, unsent_proof=unsent_proof)
            except LiveDeferred as exc:
                save_live_deferral(self.store, attempt, exc.proof)
                raise ExtractionFailure(exc.code) from exc
            except ExtractionFailure as exc:
                self._unsent(attempt, exc.code)
                raise
            except LiveFailure as exc:
                if exc.uncertain:
                    # The request may have reached the provider: the reservation stays `started` and charged; never resent.
                    raise ProviderResponseUnknown(exc.code) from exc
                self._unsent(attempt, exc.code)
                raise ExtractionFailure(exc.code) from exc
            self._receive(attempt, receipt)  # durable BEFORE any parsing, for every HTTP answer
        else:
            if call["request_digest"] != key:
                raise ExtractionFailure("receipt_request_mismatch")
            if call["state"] == "unsent":
                raise ExtractionFailure(call["verdict"])
            if call["state"] != "received":
                raise ProviderResponseUnknown("live_response_unknown")
            if call["verdict"]:
                raise ExtractionFailure(call["verdict"])
            receipt = json.loads(call["response"])
            if digest(receipt) != call["response_digest"]:
                raise ExtractionFailure("receipt_integrity_failed")
            attempt = call["attempt_id"]
            if (receipt.get("attemptId"), receipt.get("stage"), receipt.get("bindingIdentity")) != (attempt, stage, live["bindingDigest"]):
                raise ExtractionFailure("receipt_binding_mismatch")
        try:
            answer = decoder.answer(stage, receipt)
        except LiveFailure as exc:
            self._reject(attempt, exc.code)
            raise ReplyInvalid(exc.code) from exc
        try:
            result = parse(live_prompts.expand(stage, payload, answer))
        except ReplyInvalid as exc:
            self._reject(attempt, exc.code)
            raise
        self._verify(ctx, send)
        if check is not None:
            try:
                result = check(result)
            except ReplyInvalid as exc:
                self._reject(attempt, exc.code)
                raise
        return result

    # ------------------------------------------------------------------ stages -----------------------------------------

    def _cite(self, ctx: Context, doc: Doc, start: int, end: int, quote: str) -> dict:
        """Exact quote -> whole mapped locator run -> ingestion source resolver. Evidence.matches alone is insufficient."""
        return cite_exact(self.sources, doc.ref, doc.export, start, end, quote)

    def _extract(self, row, ctx: Context, fixtures: Fixtures, fence: int) -> None:
        stored = json.loads(row["binding"])
        incoming = ctx.docs[ctx.incoming]
        request_input = analysis.extract_input(incoming.article, ctx.request.prompt_version, ctx.request.catalogue)
        key = analysis.request_digest("extract", request_input, analysis_version(stored))

        def parse(raw):
            return analysis.parse_extraction(raw, incoming.article)

        if is_live(stored):
            extraction = self._live_receipted(row, ctx, fence, "extract", "incoming", key, request_input, [ctx.incoming], parse)
        else:
            def lookup():
                found = fixtures.index().get(("extract", key))  # the whole fixture (duplicates, shape) is valid before any call is reserved
                if found is None:
                    raise ExtractionFailure("replay_response_missing")
                return found

            extraction = self._receipted(row, ctx, fence, "extract", "incoming", key, lambda: fixtures.replay_hash, lookup, parse, parse)
        rows = []
        for mention in extraction.mentions:
            mention_candidate = analysis.mention_candidate_id(incoming.binding, key, stored["adapter"]["fingerprint"], mention.mention_id)
            state, reason, citations = "candidate", None, []
            try:
                citations = [self._cite(ctx, incoming, e.start, e.end, e.quote) for e in mention.evidence]
            except CitationFailure as exc:
                state, reason = "rejected", exc.code
            rows.append((analysis.event_candidate_id(mention_candidate), mention_candidate, mention.mention_id, state, reason,
                         canonical({"mention": mention.model_dump(mode="json"), "citations": citations})))

        def write():
            for event, mention_candidate, local, state, reason, payload in rows:
                self.db.execute("INSERT OR IGNORE INTO event_candidates VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (row["job_id"], event, mention_candidate, incoming.ref.document_id, incoming.ref.document_version, incoming.ref.raw_version, local, state, reason, payload))
            return {"mentions": len(rows), "candidates": sum(r[3] == "candidate" for r in rows), "rejected": sum(r[3] == "rejected" for r in rows)}

        self._persist(row, ctx, fence, "extract", write, self._sending(stored, "extract", [ctx.incoming]))
        self._stage_saved("extract")

    def _compare(self, row, ctx: Context, fixtures: Fixtures, fence: int) -> None:
        job_id = row["job_id"]
        stored = json.loads(row["binding"])
        version = analysis_version(stored)
        live = is_live(stored)
        incoming = ctx.docs[ctx.incoming]
        candidates = self.store.all("SELECT * FROM event_candidates WHERE job_id=? AND state='candidate' ORDER BY event_candidate_id", (job_id,))
        if len(candidates) * len(ctx.groups) > MAX_COMPARISONS:
            raise ExtractionFailure("comparison_limit_exceeded")
        comparisons, dispositions, sent = [], [], set()
        for candidate in candidates:
            mention = Mention.model_validate(json.loads(candidate["payload"])["mention"])
            decided = []
            for group in ctx.groups:
                request_input = analysis.compare_input(mention, group.event_id, [m for _, m in group.members], group.articles, incoming.article)
                key = analysis.request_digest("compare", request_input, version)
                ref = f"{candidate['event_candidate_id']}|{group.event_id}|{group.revision}"

                def parse(raw, m=mention, g=group):
                    return analysis.parse_comparison(raw, m, incoming.article, g.articles)

                if live:
                    # The outbound payload carries the incoming article and every article of this whole event: each needs model-send rights.
                    sent.update([ctx.incoming, *group.documents])
                    decision = self._live_receipted(row, ctx, fence, "compare", ref, key, request_input, [ctx.incoming, *group.documents], parse)
                else:
                    def lookup(key=key):
                        found = fixtures.index().get(("compare", key))  # the whole fixture (duplicates, shape) is valid before any call is reserved
                        if found is None:
                            raise ExtractionFailure("replay_response_missing")
                        return found

                    decision = self._receipted(row, ctx, fence, "compare", ref, key, lambda: fixtures.replay_hash, lookup, parse, parse)
                sources = [(incoming.ref.document_version, incoming.article), *((ctx.docs[k].ref.document_version, ctx.docs[k].article) for k in group.documents)]
                effective = analysis.effective(mention, [m for _, m in group.members], incoming.article, decision, sources)
                citations = []
                for evidence, version_ in zip(decision.evidence, effective["evidenceDocuments"]):
                    if version_ is None:
                        continue
                    try:
                        citations.append(self._cite(ctx, ctx.by_version(version_), evidence.start, evidence.end, evidence.quote))
                    except CitationFailure as exc:
                        if effective["relation"] in {"SAME", "FOLLOWS"}:
                            effective = {"relation": "HOLD", "reason": "evidence citation is not an exact mapped source interval", "rule": exc.code, "evidenceDocuments": []}
                            citations = []
                            break
                payload = {"eventCandidateId": candidate["event_candidate_id"], "targetEventId": group.event_id, "targetRevision": group.revision,
                           "groupDigest": group.digest, "snapshotDigest": ctx.snapshot_digest, "requestKey": key,
                           "original": decision.model_dump(mode="json"),
                           "effective": {k: effective[k] for k in ("relation", "reason", "rule")}, "citations": citations}
                comparisons.append((candidate["event_candidate_id"], group.event_id, canonical(payload)))
                decided.append(payload)
            dispositions.append((candidate["event_candidate_id"], canonical({**analysis.disposition(decided), "comparedEvents": len(ctx.groups), "snapshotDigest": ctx.snapshot_digest})))

        def write():
            for event, target, payload in comparisons:
                self.db.execute("INSERT OR IGNORE INTO comparisons VALUES(?,?,?,?)", (job_id, event, target, payload))
            for event, payload in dispositions:
                self.db.execute("INSERT OR IGNORE INTO dispositions VALUES(?,?,?)", (job_id, event, payload))
            return {"candidates": len(candidates), "snapshotEvents": len(ctx.groups), "comparisons": len(comparisons)}

        self._persist(row, ctx, fence, "compare", write, self._sending(stored, "compare", sent) if sent else None)
        self._stage_saved("compare")

    def _topic(self, row, ctx: Context, fixtures: Fixtures, fence: int) -> None:
        job_id = row["job_id"]
        stored = json.loads(row["binding"])
        if ctx.request.topic is None:
            self._persist(row, ctx, fence, "topic", lambda: {"status": "not-requested"})
            return
        candidates = self.store.all("SELECT * FROM event_candidates WHERE job_id=? AND state='candidate' ORDER BY event_candidate_id", (job_id,))
        if not candidates:
            self._persist(row, ctx, fence, "topic", lambda: {"status": "no-events", "topics": 0})
            return
        incoming = ctx.docs[ctx.incoming]
        events, doc_keys = [], {ctx.incoming}
        for c in candidates:
            events.append({"kind": "event-candidate", "ref": c["event_candidate_id"], "revision": None,
                           "mentions": [json.loads(c["payload"])["mention"]],
                           "documents": [{"documentId": incoming.ref.document_id, "documentVersion": incoming.ref.document_version}]})
        for g in sorted(ctx.groups, key=lambda g: g.event_id):
            doc_keys.update(g.documents)
            events.append({"kind": "snapshot-event", "ref": g.event_id, "revision": g.revision, "mentions": [m.model_dump(mode="json") for _, m in g.members],
                           "documents": [{"documentId": ctx.docs[k].ref.document_id, "documentVersion": ctx.docs[k].ref.document_version} for k in g.documents]})
        documents = sorted(({"documentId": d.ref.document_id, "documentVersion": d.ref.document_version, "title": d.export["observation"]["title"],
                             "sourceHash": d.export["document"]["sourceHash"]} for d in (ctx.docs[k] for k in doc_keys)),
                           key=lambda d: (d["documentId"], d["documentVersion"]))
        request = topics.build_request(events, documents)
        key = topics.request_digest(request)

        def cite(document_id, version, start, end, quote):
            doc = ctx.by_document(document_id, version)
            if doc is None:
                raise ReplyInvalid("topic_citation_unbound")
            return self._cite(ctx, doc, start, end, quote)

        def membership(response):
            return topics.candidates(request, response, cite)

        if is_live(stored):
            found = self._live_receipted(row, ctx, fence, "topic", "topic", key, request, sorted(doc_keys),
                                         topics.parse, membership)
        else:
            def lookup():
                if fixtures.topic_raw is None:
                    raise ExtractionFailure("topic_replay_required", {"topicRequestDigest": key})
                found = fixtures.producer(ctx.synthetic).response(key)
                if found is None:
                    raise ExtractionFailure("topic_replay_missing", {"topicRequestDigest": key})
                return found

            found = self._receipted(row, ctx, fence, "topic", "topic", key, lambda: fixtures.producer(ctx.synthetic).hash, lookup,
                topics.parse, topics.parse, membership)

        def write():
            for topic in found:
                self.db.execute("INSERT OR IGNORE INTO topic_candidates VALUES(?,?,?)", (job_id, topic["topicCandidateId"], canonical(topic)))
            return {"status": "complete", "topics": len(found), "requestDigest": key}

        self._persist(row, ctx, fence, "topic", write, self._sending(stored, "topic", doc_keys))
        self._stage_saved("topic")

    def _stage_saved(self, stage: str) -> None:
        """Seam after a stage commit; a process boundary here proves resume reuses committed stages and receipts."""

    # ------------------------------------------------------------------ result ------------------------------------------

    def result(self, job_id: str) -> dict:
        row = self._job(job_id)
        request = Submit.model_validate_json(row["request"])
        binding = json.loads(row["binding"])
        live = is_live(binding)
        stages = {s["stage"]: json.loads(s["summary"]) for s in self.store.all("SELECT * FROM stages WHERE job_id=?", (job_id,))}
        calls = self.store.all("SELECT * FROM calls WHERE job_id=? ORDER BY started_at,attempt_id", (job_id,))
        events, comparisons, dispositions, topic_rows = candidate_rows(self.store, job_id)
        statuses: dict[str, int] = {}
        for d in dispositions.values():
            statuses[d["status"]] = statuses.get(d["status"], 0) + 1
        result = {"schemaVersion": SCHEMA, "jobId": job_id, "inputDigest": row["input_digest"], "state": row["state"], "phase": row["phase"],
            "resumeMode": row["resume_mode"], "failure": {"code": row["failure"], **({"detail": json.loads(row["detail"])} if row["detail"] else {})} if row["failure"] else None,
            "provenance": request.provenance.wire(), "binding": binding,
            "stages": {name: {"state": "complete", **stages[name]} if name in stages else {"state": "pending"} for name in ("extract", "compare", "topic")},
            "comparisonScope": {"kind": "frozen-whole-event-list", "events": len(binding["snapshot"]["events"]), "retrieval": "none",
                                "completeness": "operator-frozen list; not claimed equal to B0-B4 retrieval"},
            "counts": {"documents": len(binding["documents"]), "snapshotEvents": len(binding["snapshot"]["events"]),
                       "eventCandidates": {"total": len(events), "candidate": sum(e["state"] == "candidate" for e in events), "rejected": sum(e["state"] == "rejected" for e in events)},
                       "comparisons": len(comparisons), "effectiveRelations": {r: sum(c["effective"]["relation"] == r for c in comparisons) for r in _RELATIONS},
                       "dispositions": statuses, "topicCandidates": len(topic_rows)},
            "usage": live_usage(job_id, calls) if live else
            {"executionMode": "replay", "replayCalls": sum(c["state"] == "received" for c in calls), "startedWithoutReceipt": sum(c["state"] == "started" for c in calls),
             "providerCalls": 0, "paidModelCalls": 0, "creatorJobId": job_id},
            "calls": [live_call(binding, c) for c in calls] if live else
            [{"stage": c["stage"], "state": c["state"], "requestDigest": c["request_digest"], "fixtureHash": c["fixture_hash"],
              "responseDigest": c["response_digest"], "verdict": c["verdict"]} for c in calls]}
        if row["state"] == "cancelled":
            result["delivery"] = {"status": "withheld", "code": "job_cancelled"}
            return result
        if not current(binding):
            # Stored history stays inspectable verbatim, but a job frozen under another analysis contract delivers nothing and reads no source.
            result["delivery"] = {"status": "withheld", "code": "analysis_contract_changed"}
            return result
        try:
            ctx = self._context(request)
            self._check_binding(ctx, row)
        except ExtractionFailure as exc:
            result["delivery"] = {"status": "withheld", "code": exc.code}
            return result
        result["eventCandidates"], result["topicCandidates"] = project_candidates(events, comparisons, dispositions, topic_rows)
        result["delivery"] = {"status": "current", "authority": "read+quote-display verified for every bound document at delivery"}
        return result


def candidate_rows(store: Store, job_id: str) -> tuple:
    """Stored candidate rows of one job exactly as the delivered result reads them: (event rows, comparison payloads, disposition payloads by
    candidate, topic payloads). A pure database read: no authority, registry or delivery."""
    events = store.all("SELECT * FROM event_candidates WHERE job_id=? ORDER BY event_candidate_id", (job_id,))
    comparisons = [json.loads(c["payload"]) for c in store.all("SELECT * FROM comparisons WHERE job_id=? ORDER BY event_candidate_id,target_event_id", (job_id,))]
    dispositions = {d["event_candidate_id"]: json.loads(d["payload"]) for d in store.all("SELECT * FROM dispositions WHERE job_id=?", (job_id,))}
    topic_rows = [json.loads(t["payload"]) for t in store.all("SELECT * FROM topic_candidates WHERE job_id=? ORDER BY topic_candidate_id", (job_id,))]
    return events, comparisons, dispositions, topic_rows


def project_candidates(events, comparisons: list[dict], dispositions: dict, topic_rows: list[dict]) -> tuple[list, list]:
    """The delivered `eventCandidates` (with their comparisons and disposition, never approved) and `topicCandidates`. Pure over stored rows, so
    the normal result (after the authority gate) and the read-only S4 digest below cannot drift apart."""
    mine = {e["event_candidate_id"]: [] for e in events}
    for comparison in comparisons:
        mine[comparison["eventCandidateId"]].append(comparison)
    return [{"eventCandidateId": e["event_candidate_id"], "mentionCandidateId": e["mention_candidate_id"], "localMentionId": e["local_mention_id"],
            "document": {"documentId": e["document_id"], "documentVersion": e["document_version"], "rawVersion": e["raw_version"]},
            "state": e["state"], "reason": e["reason"], "approved": False, **json.loads(e["payload"]),
            "comparisons": mine[e["event_candidate_id"]], "disposition": dispositions.get(e["event_candidate_id"])} for e in events], topic_rows


def upstream_digest(result: dict) -> str:
    """Identity of the exact upstream an S3 job consumes: the frozen binding (grants included) plus the delivered event/topic candidates.
    Owned here, not in relation, so the S4 reader can recompute it from stored rows without importing the consumer."""
    return digest({"jobId": result["jobId"], "inputDigest": result["inputDigest"], "binding": result["binding"],
                   "eventCandidates": result["eventCandidates"], "topicCandidates": result["topicCandidates"]})


# ---------------------------------------------------------------------- S4 dependents (read-only) -----------------------------------

def dependents(store: Store, matches) -> tuple[dict, dict]:
    """Identity-only S4 report over EVERY job of an `existing=True` store, from frozen bindings and stored candidate rows alone.

    No Extractor, Sources, authority, registry or delivery is involved, so a revoked job is reported exactly like a current one. A job is
    affected when one of its frozen bound observations (with the grant frozen beside it) satisfies `matches`: `_context` builds every
    citable document from the incoming document and the snapshot members only, so no other job can depend on the seed. Returns
    (ledger report, join index for S3). The index covers every scanned job, affected or not, so an S3 upstream is never silently dropped.
    Any stored row that does not parse fails the whole report as `dependency_record_invalid`; nothing is skipped."""
    jobs, index, scanned = [], {}, 0
    try:
        for row in store.all("SELECT job_id,input_digest,request,binding,state,phase,failure FROM jobs ORDER BY job_id"):
            scanned += 1
            try:
                entry, found = _dependents_of(store, row, matches)
            except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
                raise invalid("extraction", row["job_id"]) from exc
            index[row["job_id"]] = found
            if entry is not None:
                jobs.append(entry)
    except sqlite3.DatabaseError as exc:
        raise ExtractionFailure("extraction_state_invalid") from exc
    return {"ledgerVersion": LEDGER_VERSION, "scannedJobs": scanned, "jobs": jobs}, index


def _dependents_of(store: Store, row, matches) -> tuple[dict | None, dict]:
    job_id = row["job_id"]
    request = Submit.model_validate_json(row["request"])
    binding = json.loads(row["binding"])
    incoming = doc_key(request.incoming)
    members = {event.event_id: {doc_key(m.observation) for m in event.members} for event in request.snapshot.events}
    bound = {}
    for key, document in binding["documents"].items():
        ref, grant = ObservationRef.model_validate(document["observation"]), document["grant"]
        if doc_key(ref) != key or not all(isinstance(grant[name], str) for name in ("grantId", "revision")):
            raise ValueError("binding identity")
        bound[key] = (ref, grant["grantId"], grant["revision"])
    everyone = set().union(*members.values())
    if binding["incoming"] != incoming or incoming in everyone or set(bound) != {incoming} | everyone:
        raise ValueError("binding scope")

    projection: list[str] = []

    def projected() -> str:
        """Digest of the delivered candidate projection that S3 pins as `upstream.digest`, recomputed from stored rows only (no delivery gate).
        Evaluated lazily and once, and only for a job an S3 job names; a stored row that cannot be projected fails the whole report."""
        if not projection:
            try:
                event_candidates, topic_candidates = project_candidates(*candidate_rows(store, job_id))
                projection.append(upstream_digest({"jobId": job_id, "inputDigest": row["input_digest"], "binding": binding,
                                                   "eventCandidates": event_candidates, "topicCandidates": topic_candidates}))
            except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
                raise invalid("extraction", job_id) from exc
            except sqlite3.DatabaseError as exc:
                raise ExtractionFailure("extraction_state_invalid") from exc
        return projection[0]

    hit = {key for key, (ref, grant_id, revision) in bound.items() if matches(ref, grant_id, revision)}
    if not hit:
        return None, {"inputDigest": row["input_digest"], "ready": row["state"] == "ready", "digest": projected, "affected": False,
                      "documents": set(), "events": set(), "topics": set()}
    documents = {(bound[key][0].document_id, bound[key][0].document_version) for key in hit}
    from_incoming = incoming in hit

    matched = sorted(({"role": "incoming" if key == incoming else "snapshot-member", "roundId": ref.round_id, "sourceId": ref.source_id, "page": ref.page,
                       "ordinal": ref.ordinal, "documentId": ref.document_id, "rawVersion": ref.raw_version, "documentVersion": ref.document_version,
                       "grant": {"grantId": grant_id, "revision": revision}} for key in hit for ref, grant_id, revision in [bound[key]]),
                     key=lambda m: (m["documentId"], m["documentVersion"], m["rawVersion"], m["roundId"], m["sourceId"], m["page"], m["ordinal"], m["role"]))

    snapshot_events, affected_events = [], set()
    for event in sorted(request.snapshot.events, key=lambda e: e.event_id):
        named = sorted({(bound[doc_key(m.observation)][0].document_id, bound[doc_key(m.observation)][0].document_version)
                        for m in event.members if doc_key(m.observation) in hit})
        if named:
            affected_events.add(event.event_id)
            snapshot_events.append({"eventId": event.event_id, "revision": event.revision,
                                    "reasons": [{"code": "member_document", "documentId": d, "documentVersion": v} for d, v in named]})

    candidates = store.all("SELECT event_candidate_id,document_id,document_version,raw_version,state FROM event_candidates WHERE job_id=? ORDER BY event_candidate_id", (job_id,))
    comparisons = store.all("SELECT event_candidate_id,target_event_id,payload FROM comparisons WHERE job_id=? ORDER BY event_candidate_id,target_event_id", (job_id,))
    topics = store.all("SELECT topic_candidate_id,payload FROM topic_candidates WHERE job_id=? ORDER BY topic_candidate_id", (job_id,))
    origin = bound[incoming][0]
    if any((c["document_id"], c["document_version"], c["raw_version"]) != (origin.document_id, origin.document_version, origin.raw_version) for c in candidates):
        raise ValueError("candidate origin")

    # The disposition of a candidate is computed over its comparison with EVERY snapshot event, so each affected target it was compared with is an input.
    compared: dict[str, list[str]] = {}
    for c in comparisons:
        if c["target_event_id"] in affected_events:
            compared.setdefault(c["event_candidate_id"], []).append(c["target_event_id"])
    event_candidates = []
    for c in candidates:
        reasons = [*([{"code": "extracted_from"}] if from_incoming else []), *({"code": "disposition_input", "targetEventId": t} for t in compared.get(c["event_candidate_id"], []))]
        if reasons:
            event_candidates.append({"eventCandidateId": c["event_candidate_id"], "state": c["state"], "reasons": reasons})

    compared_entries = []
    for c in comparisons:
        payload = json.loads(c["payload"])
        if payload["eventCandidateId"] != c["event_candidate_id"] or payload["targetEventId"] != c["target_event_id"] or not isinstance(payload["targetRevision"], str):
            raise ValueError("comparison identity")
        reasons = [*([{"code": "incoming_document"}] if from_incoming else []), *([{"code": "target_event_member"}] if c["target_event_id"] in affected_events else []),
                   *cites(payload["citations"], documents)]
        if reasons:
            compared_entries.append({"eventCandidateId": c["event_candidate_id"], "targetEventId": c["target_event_id"], "targetRevision": payload["targetRevision"], "reasons": reasons})

    candidate_ids = {c["event_candidate_id"] for c in candidates}
    topic_entries, affected_topics = [], set()
    for t in topics:
        payload = json.loads(t["payload"])
        if payload["topicCandidateId"] != t["topic_candidate_id"]:
            raise ValueError("topic identity")
        reasons = [{"code": "member_event", "kind": m["kind"], "ref": m["ref"]} for m in sorted(array(payload["members"]), key=lambda m: (m["kind"], m["ref"]))
                   if (m["kind"] == "event-candidate" and from_incoming and m["ref"] in candidate_ids) or (m["kind"] == "snapshot-event" and m["ref"] in affected_events)]
        reasons += cites(payload["citations"], documents)
        if reasons:
            affected_topics.add(t["topic_candidate_id"])
            topic_entries.append({"topicCandidateId": t["topic_candidate_id"], "reasons": reasons})

    # Scope of the whole job: owner delivery re-verifies every bound document, so a rights or binding change withholds all of it.
    entry = {"jobId": job_id, "inputDigest": row["input_digest"], "state": row["state"], "phase": row["phase"], "failureCode": row["failure"],
             "matchedDocuments": matched,
             "jobScope": {"boundDocuments": len(bound), "snapshotEvents": len(request.snapshot.events), "eventCandidates": len(candidates),
                          "comparisons": len(comparisons), "topicCandidates": len(topics)},
             "snapshotEvents": snapshot_events, "eventCandidates": event_candidates, "comparisons": compared_entries, "topicCandidates": topic_entries}
    return entry, {"inputDigest": row["input_digest"], "ready": row["state"] == "ready", "digest": projected, "affected": True, "documents": documents,
                   "events": (candidate_ids if from_incoming else set()) | affected_events, "topics": affected_topics}
