"""Nonpublic, immutable, version-scoped Neo4j projection of ONE frozen S3 relation job (FS080 slice; not publication, not FS081 withdrawal).

Flow: `init` binds this ledger to one empty, isolated Neo4j database -> `freeze` pins a ready, currently delivered S3 job plus the exact canonical
mapping decisions into an immutable plan (SQLite only) -> `project` writes that plan as one version in ONE explicit unmanaged Neo4j transaction ->
`recover` settles an unknown commit by reading the full graph back -> `read`/`focus` serve a version only after every current authority gate and a
full content verification (never the marker alone). Nothing here calls a model, a provider or the network beyond the one bound Neo4j instance.

Authority and identity rules this module enforces:
* the S3 job is read ONLY through the existing read-only owner seam (`relation.Store(existing=True)` + `Engine.inspect`), which re-verifies the
  S2 job, its grants, rights and exact candidate set; the S3 `inputDigest`, the S2 upstream digest (grant revision included), the review state and
  every used canonical decision are pinned in the frozen plan and compared again by every command;
* canonical IDs come only from the server-owned registry file, bound to the exact S2 upstream (job AND inputDigest). Nothing infers them from
  S2 catalogue IDs, SAME, candidate IDs or any earlier read; the file is re-read by every command and never cached on disk;
* no raw quote, title, URL, model rationale or review note is ever stored in the graph, the plan or any output (evidence is IDs plus
  document/version/span coordinates only).
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from neo4j.exceptions import ConstraintError, DriverError, Neo4jError

from . import graph_neo4j as neo
from .extraction import Sources
from .graph_projection_contracts import (APPROVAL_KEYS, APPROVAL_KINDS, DEPTHS, EDGE_SPECS, HISTORIC_PLAN_VERSIONS, KIND_OF_LABEL, KINDS, LABELS, LEDGER_VERSION,
    MAX_ATTEMPTS, MAX_EDGES, MAX_EVIDENCE, MAX_NODES, MAX_PLAN, MAX_REGISTRY, PLAN_VERSION, SCHEMA, STORE_SCHEMA, UNRESOLVED_SHOWN, CanonicalEntry,
    CanonicalRegistry, ExtractionFailure, Focus, Freeze, Init, Selector, Withheld, canonical, digest, entry_key, graph_digest, marker_props, normalized_props,
    plan_graph_digest, relation_id, stored_props)
from .ingestion_contracts import IngestionFailure, copy_bounded, now, read_file, reserved_state_roots, timestamp
from .relation import Engine
from .relation import Store as RelationStore
from .relation_contracts import MAX_PATH
from .private_processing import select_authority

_SQL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS versions(version_id TEXT PRIMARY KEY, input_digest TEXT NOT NULL, request TEXT NOT NULL, plan TEXT NOT NULL,
 payload_digest TEXT NOT NULL, graph_digest TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('frozen','reserved','unknown','ready','failed')), failure TEXT, detail TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(version_id TEXT NOT NULL REFERENCES versions(version_id), n INTEGER NOT NULL, reserved_at TEXT NOT NULL,
 outcome TEXT CHECK(outcome IS NULL OR outcome IN ('committed','confirmed','not-committed','rolled-back','unknown')), code TEXT, finished_at TEXT,
 PRIMARY KEY(version_id,n));
"""
_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS immutable_meta_update BEFORE UPDATE ON meta BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_meta_delete BEFORE DELETE ON meta BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_versions_delete BEFORE DELETE ON versions BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_versions_identity BEFORE UPDATE OF version_id,input_digest,request,plan,payload_digest,graph_digest,created_at "
    "ON versions BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS terminal_versions BEFORE UPDATE ON versions WHEN OLD.state IN ('ready','failed') BEGIN SELECT RAISE(ABORT,'terminal'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_attempts_delete BEFORE DELETE ON attempts BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_attempts_identity BEFORE UPDATE OF version_id,n,reserved_at ON attempts BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS settled_attempts BEFORE UPDATE ON attempts WHEN OLD.outcome IS NOT NULL AND OLD.outcome <> 'unknown' "
    "BEGIN SELECT RAISE(ABORT,'settled'); END",
)
_FILES = {"graph.sqlite3", "graph.sqlite3-wal", "graph.sqlite3-shm", "graph.lock"}
NEXT = {"frozen": "project", "reserved": "recover", "unknown": "recover", "ready": "read", "failed": None}
USAGE = {"providerCalls": 0, "modelCalls": 0}
# Store/graph integrity refusals that a read answers as `withheld` (a stored version must never be served while any of them holds).
_STORE_WITHHOLDS = frozenset({"graph_store_identity_mismatch", "graph_store_foreign_data", "graph_store_schema_mismatch"})


# ---------------------------------------------------------------------------------------------- pure placement and target rules -----

def checked_root(root: Path, *upstream_roots: Path) -> Path:
    """The absolute ledger directory, after the ownership rules every graph command shares (pure: nothing is created, opened or locked): disjoint from
    the app, S1 and retired-prototype roots and from every given source ledger (`state_namespace_conflict`; an installed package without configured
    ownership roots is `state_ownership_unconfigured`), and no symlinked component, dangling or not (`state_namespace_invalid`)."""
    root = Path(os.path.abspath(root))
    forbidden = [*reserved_state_roots(), *(Path(os.path.abspath(p)) for p in upstream_roots)]
    if any(root == p or root.is_relative_to(p) or p.is_relative_to(root) for p in forbidden):
        raise ExtractionFailure("state_namespace_conflict")
    for parent in [*reversed(root.parents), root]:
        if parent.is_symlink():
            raise ExtractionFailure("state_namespace_invalid")
    return root


def ours_only(root: Path) -> list[Path]:
    """The entries of an existing ledger directory; anything that is not exactly this ledger's own file set (or is a symlink) is `state_namespace_conflict`."""
    entries = list(root.iterdir())
    if any(p.name not in _FILES or p.is_symlink() for p in entries):
        raise ExtractionFailure("state_namespace_conflict")
    return entries


def ledger_state(root: Path) -> str:
    """`absent` (no directory, or an empty one: `init` would create the ledger) or `present` (some ledger file exists), by directory listing only: no
    SQLite open, no lock, no chmod, no creation. A path that is not a directory, or a directory holding anything foreign, is `state_namespace_conflict`."""
    if not os.path.lexists(root):
        return "absent"
    if not root.is_dir():
        raise ExtractionFailure("state_namespace_conflict")
    return "present" if ours_only(root) else "absent"


def tolerated_schema(facts: dict) -> bool:
    """Only objects of this schema (by name) may already exist in a database `init` can bind (an interrupted earlier `init` leaves some of them)."""
    expected_constraints, expected_indexes = neo.expected_schema()
    return set(facts["constraints"]) <= set(expected_constraints) and set(facts["indexes"]) <= set(expected_indexes)


def refuse_unbound_target(facts: dict, database: str) -> None:
    """The ONE rule deciding whether a probed database may be bound by a ledger that has no binding yet. `init` and `preflight` both call it, so they
    cannot diverge: wrong database name -> identity mismatch; any node, relationship, store marker or foreign schema object -> not empty; an object
    with an expected NAME but another definition -> schema mismatch (all BEFORE any intent, DDL or store marker)."""
    if facts["database"].lower() != database.lower():
        raise ExtractionFailure("graph_store_identity_mismatch")
    if facts["nodes"] or facts["relationships"] or facts["stores"] or not tolerated_schema(facts):
        raise ExtractionFailure("graph_store_not_empty")
    if neo.schema_conflicts(facts["constraints"], facts["indexes"]):
        raise ExtractionFailure("graph_store_schema_mismatch")


def preflight(request: Init, uri: str, state_dir: Path) -> dict:
    """Read-only candidate check for `init`; it binds nothing and writes nothing anywhere.

    It never creates, chmods, opens or locks a ledger, runs no DDL and no write transaction, and uses only the closed read statements of the adapter's
    own `probe()`. A ledger already present at `state_dir` is refused (`graph_store_already_bound`): re-verifying a bound store is the idempotent `init`
    re-run, and a read-only check must never adopt or interpret a ledger. What it proves: the target answers over the intended transport (TLS is
    certificate-verified for `bolt+s`) with the given credentials, is a supported Neo4j 5 server, selects the requested database and holds no data. What
    it cannot prove: that the user may run DDL, or that the database stays unchanged until `init`."""
    root = checked_root(state_dir)
    if ledger_state(root) != "absent":
        raise ExtractionFailure("graph_store_already_bound")
    auth = neo.read_auth(uri)
    graph = neo.Graph(uri, request.database, auth)
    try:
        facts = neo.probe(graph)
    finally:
        graph.close()
    refuse_unbound_target(facts, request.database)
    return {"schemaVersion": SCHEMA,
            "preflight": {"result": "eligible-empty-target", "ddlPermission": "unverified", "tls": "verified" if neo.is_secure(uri) else "loopback-plain",
                          "ledger": "absent", "server": facts["server"], "database": facts["database"], "dbId": facts["dbId"],
                          "counts": {"nodes": facts["nodes"], "relationships": facts["relationships"]},
                          "schemaObjects": {"constraints": len(facts["constraints"]), "indexes": len(facts["indexes"])}},
            "usage": USAGE}


# ---------------------------------------------------------------------------------------------- ledger -------------------------------

class Store:
    """The graph ledger (`graph.sqlite3` + `graph.lock`), same rules as the other pipeline ledgers: a dedicated directory disjoint from the app, S1
    and every source ledger, no symlinks, 0700/0600, one exclusive non-blocking writer lock, WAL + synchronous=FULL.

    mode `create` (init only) may create the directory and ledger; `write` needs an existing ledger and never creates one; `read` takes a shared
    lock, opens the file immutable and read-only, creates nothing and refuses a hot WAL (a writer command must settle it first)."""

    def __init__(self, root: Path, *upstream_roots: Path, mode: str = "write"):
        root = checked_root(root, *upstream_roots)
        if mode == "read":
            self._open_existing(root)
            return
        if mode == "create":
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
        elif not root.is_dir() or not (root / "graph.sqlite3").is_file() or not (root / "graph.lock").is_file():
            raise ExtractionFailure("graph_state_missing")
        ours_only(root)
        os.chmod(root, 0o700)
        self.lock = os.open(root / "graph.lock", os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if mode == "create" else 0), 0o600)
        os.fchmod(self.lock, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.lock)
            del self.lock
            raise ExtractionFailure("graph_busy") from exc
        try:
            database = root / "graph.sqlite3"
            fd = os.open(database, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if mode == "create" else 0), 0o600)
            os.fchmod(fd, 0o600)
            os.close(fd)
            self.db = sqlite3.connect(database, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            if mode == "create":
                self.db.executescript(_SQL)
                for trigger in _TRIGGERS:
                    self.db.execute(trigger)
                self.db.execute("INSERT OR IGNORE INTO meta VALUES('ledger',?)", (LEDGER_VERSION,))
            try:
                ledger = self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
            except sqlite3.DatabaseError as exc:
                raise ExtractionFailure("graph_state_invalid") from exc
            if ledger is None or ledger["value"] != LEDGER_VERSION:
                raise ExtractionFailure("ledger_version_unknown")
            for p in root.iterdir():
                os.chmod(p, 0o600)
        except BaseException:
            self.close()
            raise

    def _open_existing(self, root: Path) -> None:
        database, lock = root / "graph.sqlite3", root / "graph.lock"
        if not root.is_dir() or not database.is_file() or not lock.is_file():
            raise ExtractionFailure("graph_state_missing")
        ours_only(root)
        self.lock = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.close()
            raise ExtractionFailure("graph_busy") from exc
        try:
            wal = root / "graph.sqlite3-wal"
            if wal.exists() and wal.stat().st_size > 0:
                raise ExtractionFailure("graph_recovery_required")
            self.db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA query_only=ON")
            self.db.execute("SELECT 1 FROM versions LIMIT 1")
            meta = self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
            if meta is None or meta["value"] != LEDGER_VERSION:
                raise ExtractionFailure("ledger_version_unknown")
        except sqlite3.DatabaseError as exc:
            self.close()
            raise ExtractionFailure("graph_state_invalid") from exc
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
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

    # ---- store binding ------------------------------------------------------------------------------------------------------------

    def meta(self, key: str) -> str | None:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return None if row is None else row["value"]

    def bound(self) -> dict | None:
        raw = self.meta("store")
        return None if raw is None else json.loads(raw)

    def ready_binding(self) -> dict:
        """The binding of an initialized store; `graph_store_unbound` while `init` has not completed."""
        binding = self.bound()
        if binding is None or self.meta("store-ready") != digest(binding):
            raise ExtractionFailure("graph_store_unbound")
        return binding

    def bind(self, binding: dict) -> None:
        with self.transaction():
            self.db.execute("INSERT INTO meta VALUES('store',?)", (canonical(binding),))

    def mark_ready(self, binding: dict) -> None:
        with self.transaction():
            self.db.execute("INSERT INTO meta VALUES('store-ready',?)", (digest(binding),))

    # ---- versions ---------------------------------------------------------------------------------------------------------------------

    def version(self, version_id: str):
        return self.one("SELECT * FROM versions WHERE version_id=?", (version_id,))

    def attempts(self, version_id: str) -> list:
        return self.all("SELECT n,outcome,code FROM attempts WHERE version_id=? ORDER BY n", (version_id,))

    def note_failure(self, version_id: str, code: str, detail: dict | None) -> None:
        """A refused `project` that sent nothing to Neo4j: the version stays `frozen`, only the reason is recorded."""
        with self.transaction():
            self.db.execute("UPDATE versions SET failure=?,detail=?,updated_at=? WHERE version_id=? AND state='frozen'",
                            (code, canonical(detail) if detail else None, now(), version_id))

    def reserve(self, version_id: str) -> int:
        """Durably record the attempt and `reserved` BEFORE anything is written to Neo4j."""
        with self.transaction():
            row = self.version(version_id)
            if row is None or row["state"] != "frozen":
                raise ExtractionFailure("version_not_frozen", {"state": None if row is None else row["state"]})
            n = self.one("SELECT COUNT(*) AS n FROM attempts WHERE version_id=?", (version_id,))["n"] + 1
            if n > MAX_ATTEMPTS:
                raise ExtractionFailure("attempt_limit_exceeded")
            self.db.execute("INSERT INTO attempts(version_id,n,reserved_at) VALUES(?,?,?)", (version_id, n, now()))
            self.db.execute("UPDATE versions SET state='reserved',failure=NULL,detail=NULL,updated_at=? WHERE version_id=?", (now(), version_id))
        return n

    def finish(self, version_id: str, n: int, state: str, outcome: str, code: str | None = None, detail: dict | None = None) -> None:
        """Settle attempt `n` and the version state together; `ready` and `failed` are terminal (a trigger refuses any later change)."""
        with self.transaction():
            self.db.execute("UPDATE attempts SET outcome=?,code=?,finished_at=? WHERE version_id=? AND n=?", (outcome, code, now(), version_id, n))
            self.db.execute("UPDATE versions SET state=?,failure=?,detail=?,updated_at=? WHERE version_id=?",
                            (state, code if state != "ready" else None, canonical(detail) if detail and state != "ready" else None, now(), version_id))


# ---------------------------------------------------------------------------------------------- history preflight ----------

def _ledger_identity_ok(db: sqlite3.Connection) -> bool:
    """The database is exactly THIS ledger: its identity row and its complete object set (tables and guard triggers), judged from reads only. A foreign or
    altered schema is never classified as absent, current or history, so it can never fall through to a writable open."""
    identity = db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
    objects = {(kind, name) for kind, name in db.execute("SELECT type,name FROM sqlite_master") if not name.startswith("sqlite_autoindex_")}
    expected = {("table", name) for name in ("meta", "versions", "attempts")}
    expected.update(("trigger", statement.split()[5]) for statement in _TRIGGERS)
    return identity is not None and identity[0] == LEDGER_VERSION and objects == expected


class WalHistory:
    """A read-only view of a graph ledger whose committed rows still sit in a HOT write-ahead log (a writer died before checkpointing).

    An immutable open ignores the WAL and any other open of the real files may create `-shm`, replay or checkpoint it, so the view never opens the real files
    with SQLite: under a held SHARED ledger lock the main file and the WAL are copied, bounded, into a private 0700 scratch directory and SQLite opens THAT
    copy. The real directory, its modes, its WAL and its `-shm` are never written; the scratch directory is removed on `close`. It offers the reads
    `Projector` needs of a history row (`version`, `attempts`, `one`, `all`)."""

    def __init__(self, root: Path):
        self.lock = os.open(root / "graph.lock", os.O_RDONLY | os.O_NOFOLLOW)
        self.scratch: Path | None = None
        try:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ExtractionFailure("graph_busy") from exc
            self.scratch = Path(tempfile.mkdtemp(prefix="zoop-graph-history-"))
            try:
                for name in ("graph.sqlite3", "graph.sqlite3-wal"):
                    copy_bounded(root / name, self.scratch / name)
            except ValueError:
                raise ExtractionFailure("graph_state_invalid") from None
            self.db = sqlite3.connect(self.scratch / "graph.sqlite3", isolation_level=None)
            self.db.row_factory = sqlite3.Row
            if not _ledger_identity_ok(self.db):
                raise ExtractionFailure("ledger_version_unknown")
        except sqlite3.DatabaseError as exc:
            self.close()
            raise ExtractionFailure("graph_state_invalid") from exc
        except BaseException:
            self.close()
            raise

    def one(self, sql, args=()):
        return self.db.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def version(self, version_id: str):
        return self.one("SELECT * FROM versions WHERE version_id=?", (version_id,))

    def attempts(self, version_id: str) -> list:
        return self.all("SELECT n,outcome,code FROM attempts WHERE version_id=? ORDER BY n", (version_id,))

    def close(self) -> None:
        if hasattr(self, "db"):
            self.db.close()
            del self.db
        if self.scratch is not None:
            shutil.rmtree(self.scratch, ignore_errors=True)
            self.scratch = None
        if hasattr(self, "lock"):
            os.close(self.lock)
            del self.lock


def open_legacy_history(root: Path, *upstream_roots: Path, version_id: str) -> "Store | WalHistory | None":
    """Ledger-only, read-only preflight, BEFORE any writable `Store`, authority, registry or Neo4j (same discipline as the handoff's).

    Returns a read-only view when the ledger already holds `version_id` under an earlier plan contract. Returns None ONLY when that is PROVEN not to be the
    case: no state directory, no ledger file, or the row is absent or current. Everything inconclusive (busy writer, foreign or invalid namespace/ledger,
    unreadable or oversize state) is raised exactly as the ordinary open would, never turned into a fall-through to a writable open, whose chmod, WAL
    checkpoint or DDL would change a history ledger before the refusal. It writes nothing: a ledger with a non-empty WAL is read through a private copy
    (`WalHistory`); otherwise through the immutable read-only store. A current row (including one that needs `recover` over a hot WAL) falls through to the
    ordinary writer, which settles the WAL itself."""
    root = checked_root(root, *upstream_roots)
    if not os.path.lexists(root):
        return None
    if not root.is_dir():
        raise ExtractionFailure("state_namespace_conflict")
    ours_only(root)
    if not os.path.lexists(root / "graph.sqlite3"):
        return None
    if not (root / "graph.lock").is_file() or (root / "graph.lock").is_symlink() or (root / "graph.sqlite3").is_symlink():
        raise ExtractionFailure("graph_state_invalid")
    wal = root / "graph.sqlite3-wal"
    view = WalHistory(root) if wal.exists() and wal.stat().st_size > 0 else Store(root, *upstream_roots, mode="read")
    try:
        if not _ledger_identity_ok(view.db):
            raise ExtractionFailure("ledger_version_unknown")
        row = view.version(version_id)
        if row is not None and not plan_current(row):
            return view
    except sqlite3.DatabaseError as exc:
        view.close()
        raise ExtractionFailure("graph_state_invalid") from exc
    except BaseException:
        view.close()
        raise
    view.close()
    return None


# ---------------------------------------------------------------------------------------------- canonical registry ------------------

@dataclass
class Registry:
    """The server-owned canonical decisions as read NOW. `raw` is kept only to prove the file did not change during one command."""
    raw: bytes
    entries: dict


def load_registry(path: Path) -> Registry:
    try:
        raw = read_file(path, MAX_REGISTRY)
        parsed = CanonicalRegistry.model_validate_json(raw)
    except (IngestionFailure, OSError, ValueError):
        raise ExtractionFailure("canonical_registry_invalid") from None
    return Registry(raw, {entry_key(e.upstream.job_id, e.upstream.input_digest, e.kind, e.ref): e for e in parsed.entries})


def registry_unchanged(registry: Registry, path: Path) -> None:
    try:
        same = read_file(path, MAX_REGISTRY) == registry.raw
    except (IngestionFailure, OSError):
        same = False
    if not same:
        raise ExtractionFailure("canonical_registry_changed")


# ---------------------------------------------------------------------------------------------- source gates ---------------------------

@dataclass(frozen=True)
class Paths:
    relation: Path
    extraction: Path
    ingestion: Path
    sources: Path | None
    canonical: Path
    private_processing: Path | None = None


class Source:
    """The S3 relation ledger opened ONCE through its read-only seam (shared lock held until the command ends, so no S3 writer can change it
    under this command). Each `inspect` builds a fresh authority and re-verifies the S2 job, grants, rights and candidate set through the owners."""

    def __init__(self, paths: Paths):
        self.paths = paths

    def __enter__(self) -> "Source":
        self.store = RelationStore(self.paths.relation, self.paths.extraction, self.paths.ingestion, existing=True)
        return self

    def __exit__(self, *exc) -> None:
        self.store.close()

    def inspect(self, job_id: str) -> dict:
        authority = select_authority(self.paths.sources, self.paths.private_processing)
        engine = Engine(self.store, Sources(self.paths.ingestion, authority), self.paths.extraction, self.paths.ingestion)
        return engine.inspect(job_id)


def gate(source: Source, relation: dict, pin: dict | None) -> dict:
    """The S3 result, only while it is ready, currently delivered (S2 grants/rights/binding re-verified by the owners), the exact frozen input and,
    when pinned, the exact frozen upstream identity including the S2 digest that covers the grant revision."""
    result = source.inspect(relation["jobId"])
    delivery = result["delivery"]
    if delivery["status"] != "current":
        raise Withheld(delivery["code"])
    if result["state"] != "ready":
        raise Withheld("relation_not_ready", {"state": result["state"]})
    if result["inputDigest"] != relation["inputDigest"]:
        raise Withheld("relation_input_mismatch")
    if pin is not None and result["binding"]["upstream"] != pin:
        raise Withheld("upstream_changed")
    return result


def review_state(result: dict) -> list:
    return sorted([r["relationCandidateId"], r["relationKey"], r["eligibility"]["status"], bool(r["eligibility"]["reviewPending"]), r["eligibility"]["revision"]]
                  for r in result["relations"])


def offset_timestamp(value) -> bool:
    """Whether `value` is an ISO timestamp WITH an offset (the native `timestamp` rule; the backend parses the same text as an OffsetDateTime)."""
    try:
        timestamp(value)
    except (ValueError, TypeError):
        return False
    return True


def approval_basis(relation: dict) -> dict:
    """The effective approval of ONE projectable S3 relation (eligible, not review-pending), proven against its own append-only history.

    The S3 owner reports `eligibility.approvalBasis`; this never trusts it alone. The deciding event is the LAST event of the chain and its sequence is the
    revision. `automatic-verifier` needs that event to be a verdict that made the relation eligible (no reviewer); `operator-final-approval` needs it to be
    a review `allow` whose effect is `approved` by exactly the named reviewer. Anything else (a legacy `revalidation-requested`, a stale or forged basis, a
    chain that does not end at the revision) is `relation_payload_invalid`: a basis is never guessed, repaired or defaulted to automatic."""
    invalid = ExtractionFailure("relation_payload_invalid", {"relationCandidateId": relation.get("relationCandidateId")})
    state, history = relation["eligibility"], relation["history"]
    basis = state.get("approvalBasis")
    if state["status"] != "eligible" or state["reviewPending"] or not isinstance(basis, dict) or set(basis) != set(APPROVAL_KEYS) or not history:
        raise invalid
    last = history[-1]
    if (basis["revision"] != state["revision"] or last["seq"] != basis["revision"] or last["createdAt"] != basis["decidedAt"]
            or not offset_timestamp(basis["decidedAt"])):
        raise invalid
    if basis["kind"] == "automatic-verifier":
        proven = basis["reviewer"] is None and last["kind"] == "verdict" and last["eligibility"] == "eligible"
    elif basis["kind"] == "operator-final-approval":
        proven = (isinstance(basis["reviewer"], str) and last["kind"] == "review" and last["decision"] == "allow" and last.get("effect") == "approved"
                  and last["reviewer"] == basis["reviewer"])
    else:
        proven = False
    if not proven:
        raise invalid
    return {key: basis[key] for key in APPROVAL_KEYS}



# ---------------------------------------------------------------------------------------------- planning (pure) --------------------

def _evidence(citations: list, records: dict) -> list[str]:
    """Evidence IDs of exactly resolved citations; the record keeps coordinates only. A failed or malformed citation never reaches the graph."""
    found = set()
    for c in citations:
        if "error" in c:
            raise ValueError("failed citation")
        record = {"evidenceId": c["evidenceId"], "documentId": c["documentId"], "documentVersion": c["documentVersion"], "rawVersion": c["rawVersion"],
                  "start": c["start"], "end": c["end"]}
        if not (isinstance(record["evidenceId"], str) and record["evidenceId"].startswith("ev-") and isinstance(record["start"], int)
                and isinstance(record["end"], int) and all(isinstance(record[k], str) for k in ("documentId", "documentVersion", "rawVersion"))):
            raise ValueError("citation shape")
        if records.setdefault(record["evidenceId"], record) != record:
            raise ExtractionFailure("evidence_record_conflict")
        found.add(record["evidenceId"])
    return sorted(found)


def plan_version(version_id: str, result: dict, entries: dict) -> dict:
    """The immutable plan of one version from a current S3 result and the canonical registry. Pure: no I/O.

    Only eligible relations without a pending review are projected; HOLD/REJECT/pending/review-pending ones are excluded and only counted. Every
    endpoint of a projected relation must have a registry decision for this exact S2 upstream, or the WHOLE freeze fails: nothing is guessed,
    dropped or half-written. Aliases may merge relations; a merge that makes a relation its own object or collapses a path fails the whole freeze."""
    try:
        return _plan(version_id, result, entries)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        raise ExtractionFailure("relation_payload_invalid") from None


def _plan(version_id: str, result: dict, entries: dict) -> dict:
    upstream = {key: result["binding"]["upstream"][key] for key in ("jobId", "inputDigest", "digest")}
    selected = [r for r in result["relations"] if r["eligibility"]["status"] == "eligible" and not r["eligibility"]["reviewPending"]]
    approvals = {r["relationCandidateId"]: approval_basis(r) for r in selected}      # the effective, history-proven basis of every projected relation
    used: dict[tuple, CanonicalEntry] = {}
    missing: set[tuple] = set()

    def resolve(endpoint: dict) -> dict | None:
        kind, ref = endpoint["kind"], endpoint["ref"]
        entry = entries.get(entry_key(upstream["jobId"], upstream["inputDigest"], kind, ref))
        if entry is None:
            missing.add((kind, ref))
            return None
        used[(kind, ref)] = entry
        return {"kind": kind, "id": entry.canonical_id}

    resolved = []
    for r in selected:
        spec = EDGE_SPECS.get(r["type"])
        if spec is None:
            raise ExtractionFailure("relation_type_unsupported", {"relationCandidateId": r["relationCandidateId"]})
        resolved.append((r, spec, resolve(r["subject"]), resolve(r["object"]), [(s, resolve(s["subject"]), resolve(s["object"])) for s in r["path"]]))
    if missing:
        ordered = sorted(missing)
        raise ExtractionFailure("canonical_mapping_unresolved", {"total": len(ordered),
                                                                  "unresolved": [{"kind": kind, "ref": ref} for kind, ref in ordered[:UNRESOLVED_SHOWN]]})
    records: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    for r, spec, subject, obj, steps in resolved:
        rc = r["relationCandidateId"]
        invalid = ExtractionFailure("relation_payload_invalid", {"relationCandidateId": rc})
        if (subject["kind"], obj["kind"]) != (spec.subject, spec.object) or r["direction"] != spec.direction:
            raise invalid
        if spec.direction == "symmetric":
            subject, obj = sorted([subject, obj], key=lambda e: (e["kind"], e["id"]))
        if subject == obj:
            raise ExtractionFailure("canonical_mapping_conflict", {"relationCandidateId": rc, "reason": "self_relation"})
        path_ids: list[str] = []
        if r["connection"] == "indirect":
            # MAX_PATH is the S3 production path length; it is unrelated to the read depth of `focus`.
            if spec.direction != "directed" or len(steps) != MAX_PATH or any(s["type"] != r["type"] or a["kind"] != "company" or b["kind"] != "company"
                                                                             for s, a, b in steps):
                raise invalid
            (_, a1, b1), (_, a2, b2) = steps
            if not (a1 == subject and b1 == a2 and b2 == obj):
                raise invalid
            if len({a1["id"], b1["id"], b2["id"]}) != 3:
                raise ExtractionFailure("canonical_mapping_conflict", {"relationCandidateId": rc, "reason": "path_collapsed"})
            path_ids = [a1["id"], b1["id"], b2["id"]]
        elif r["connection"] != "direct" or steps:
            raise invalid
        validity = r["validity"]
        countries = sorted(set(r["countries"]))
        step_evidence = [_evidence(s["citations"], records) for s, _, _ in steps]
        edge_id = relation_id(r["type"], subject, obj, r["businessScope"], r["productScope"], validity["from"], validity["until"], r["connection"], countries,
                              [{"type": s["type"], "subject": a, "object": b} for s, a, b in steps])
        props = normalized_props({"id": edge_id, "direction": spec.direction, "connection": r["connection"], "businessScope": r["businessScope"],
                                  "productScope": r["productScope"], "validFrom": validity["from"], "validUntil": validity["until"], "countries": countries,
                                  "pathCompanyIds": path_ids, "evidenceIds": _evidence(r["citations"], records),
                                  "validityEvidenceIds": _evidence(validity["citations"], records),
                                  "step1EvidenceIds": step_evidence[0] if step_evidence else [],
                                  "step2EvidenceIds": step_evidence[1] if len(step_evidence) > 1 else [], "sourceRelationCandidateIds": [rc]})
        mine = [{"relationCandidateId": rc, "kind": approvals[rc]["kind"]}]
        edge = edges.setdefault(edge_id, {"type": r["type"], "subject": subject, "object": obj, "props": props, "approvals": mine})
        if edge["props"] is not props:
            for key in ("evidenceIds", "validityEvidenceIds", "step1EvidenceIds", "step2EvidenceIds", "sourceRelationCandidateIds"):
                edge["props"][key] = sorted(set(edge["props"][key]) | set(props[key]))
            edge["approvals"] = sorted([*edge["approvals"], *mine], key=lambda a: a["relationCandidateId"])
    nodes = sorted({(LABELS[e[role]["kind"]], e[role]["id"]) for e in edges.values() for role in ("subject", "object")}
                   | {(LABELS["company"], company) for e in edges.values() for company in e["props"]["pathCompanyIds"]})
    ordered_edges = sorted(edges.values(), key=lambda e: (e["type"], e["props"]["id"]))
    evidence = [records[key] for key in sorted(records)]
    if len(ordered_edges) > MAX_EDGES or len(nodes) > MAX_NODES or len(evidence) > MAX_EVIDENCE:
        raise ExtractionFailure("version_limit_exceeded", {"edges": len(ordered_edges), "nodes": len(nodes), "evidence": len(evidence)})
    counts = result["counts"]
    entry_list = [used[key].wire() for key in sorted(used)]
    plan = {"schema": PLAN_VERSION, "versionId": version_id,
            "source": {"relation": {"jobId": result["jobId"], "inputDigest": result["inputDigest"]}, "upstream": upstream, "provenance": result["provenance"],
                       "policies": result["binding"]["versions"],
                       "review": {"digest": digest(review_state(result)),
                                  "projected": [{"relationCandidateId": rc, "revision": approvals[rc]["revision"], "approvalBasis": approvals[rc]} for rc in sorted(approvals)]}},
            "canonical": {"digest": digest(entry_list), "entries": entry_list},
            "nodes": [list(n) for n in nodes], "edges": ordered_edges, "evidence": evidence,
            "audit": {"s3Relations": len(result["relations"]), "eligibility": {key: counts["eligibility"][key] for key in ("eligible", "hold", "reject", "pending")},
                      "reviewPending": sum(bool(r["eligibility"]["reviewPending"]) for r in result["relations"]), "projectedCandidates": len(selected),
                      "approvals": {"automatic": sum(a["kind"] == "automatic-verifier" for a in approvals.values()),
                                    "operatorFinal": sum(a["kind"] == "operator-final-approval" for a in approvals.values())},
                      "canonicalMerges": len(selected) - len(ordered_edges), "impactCandidatesNotProjected": counts["impactCandidates"]}}
    if len(canonical(plan).encode("utf-8")) > MAX_PLAN:
        raise ExtractionFailure("version_limit_exceeded", {"plan": "bytes"})
    return plan


def plan_current(row) -> bool:
    """Whether a ledger row was frozen under THIS build's plan contract, read from its stored immutable plan schema alone (before any authority, registry or
    Neo4j is touched). A plan of an earlier contract is HISTORY: it carries no pinned approval basis, so it is shown as stored and never projected, recovered
    or served. A schema this build has never heard of is a damaged ledger."""
    try:
        schema = json.loads(row["plan"])["schema"]
    except (ValueError, KeyError, TypeError):
        raise ExtractionFailure("graph_state_invalid") from None
    if schema in HISTORIC_PLAN_VERSIONS:
        return False
    if schema != PLAN_VERSION:
        raise ExtractionFailure("graph_state_invalid")
    return True


def _approvals_closed(plan: dict) -> bool:
    """The pinned approval basis of every projected relation is well formed, unique and consistent with the edges' per-source kinds and the audit counts."""
    projected = plan["source"]["review"]["projected"]
    by_rc: dict[str, dict] = {}
    for item in projected:
        basis = item["approvalBasis"]
        if (set(item) != {"relationCandidateId", "revision", "approvalBasis"} or set(basis) != set(APPROVAL_KEYS) or basis["kind"] not in APPROVAL_KINDS
                or basis["revision"] != item["revision"] or type(item["revision"]) is not int or (basis["reviewer"] is None) != (basis["kind"] == "automatic-verifier")
                or not offset_timestamp(basis["decidedAt"]) or item["relationCandidateId"] in by_rc):
            return False
        by_rc[item["relationCandidateId"]] = basis
    if [i["relationCandidateId"] for i in projected] != sorted(by_rc) or plan["audit"]["projectedCandidates"] != len(by_rc):
        return False
    if plan["audit"]["approvals"] != {"automatic": sum(b["kind"] == "automatic-verifier" for b in by_rc.values()),
                                      "operatorFinal": sum(b["kind"] == "operator-final-approval" for b in by_rc.values())}:
        return False
    seen: set[str] = set()
    for e in plan["edges"]:
        listed = e["approvals"]
        if ([a["relationCandidateId"] for a in listed] != e["props"]["sourceRelationCandidateIds"]
                or any(set(a) != {"relationCandidateId", "kind"} or by_rc.get(a["relationCandidateId"], {}).get("kind") != a["kind"] for a in listed)):
            return False
        seen.update(a["relationCandidateId"] for a in listed)
    return seen == set(by_rc)


def verify_plan(row) -> dict:
    """The stored plan is exactly what was frozen: digests recomputed, endpoints and evidence closed. Anything else is a damaged ledger."""
    try:
        plan = json.loads(row["plan"])
        nodes = {tuple(n) for n in plan["nodes"]}
        evidence = {e["evidenceId"] for e in plan["evidence"]}
        ok = (plan["schema"] == PLAN_VERSION and plan["versionId"] == row["version_id"] and digest(plan) == row["payload_digest"]
              and plan_graph_digest(plan) == row["graph_digest"] and len(plan["edges"]) <= MAX_EDGES and len(nodes) <= MAX_NODES)
        for e in plan["edges"]:
            p = e["props"]
            ok = ok and (LABELS[e["subject"]["kind"]], e["subject"]["id"]) in nodes and (LABELS[e["object"]["kind"]], e["object"]["id"]) in nodes
            ok = ok and set(p["evidenceIds"] + p["validityEvidenceIds"] + p["step1EvidenceIds"] + p["step2EvidenceIds"]) <= evidence
        ok = ok and _approvals_closed(plan)
    except (ValueError, KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        raise ExtractionFailure("graph_state_invalid")
    return plan


# ---------------------------------------------------------------------------------------------- views --------------------------------

def ledger_result(row, attempts: list) -> dict:
    plan = json.loads(row["plan"])
    state = row["state"]
    history = not plan_current(row)
    return {"schemaVersion": SCHEMA, "versionId": row["version_id"], "state": state, "publication": "not-published", "next": None if history else NEXT[state],
            "failure": {"code": row["failure"], **({"detail": json.loads(row["detail"])} if row["detail"] else {})} if row["failure"] else None,
            "source": {"provenance": plan["source"]["provenance"], "relation": plan["source"]["relation"], "upstream": plan["source"]["upstream"],
                       "reviewDigest": plan["source"]["review"]["digest"]},
            "canonical": {"entries": len(plan["canonical"]["entries"]), "digest": plan["canonical"]["digest"]},
            "counts": {"nodes": {kind: sum(label == LABELS[kind] for label, _ in plan["nodes"]) for kind in KINDS},
                       "edges": {name: sum(e["type"] == name for e in plan["edges"]) for name in EDGE_SPECS}, "evidence": len(plan["evidence"])},
            "audit": plan["audit"], "digests": {"payload": row["payload_digest"], "graph": row["graph_digest"]},
            "attempts": [{"n": a["n"], "outcome": a["outcome"], "code": a["code"]} for a in attempts], "usage": USAGE,
            **({"delivery": {"status": "withheld", "code": "graph_contract_changed"}} if history else {})}


def withheld_result(row, code: str) -> dict:
    """Nothing but the identity, the state and the reason: no nodes, edges, evidence, scopes, quotes or titles of a version that is not currently served."""
    return {"schemaVersion": SCHEMA, "versionId": row["version_id"], "state": row["state"], "publication": "not-published",
            "delivery": {"status": "withheld", "code": code}, "usage": USAGE}


def edge_view(edge: dict) -> dict:
    p = edge["props"]
    return {"relationId": p["id"], "type": edge["type"], "direction": p["direction"], "connection": p["connection"], "subject": edge["subject"],
            "object": edge["object"], "businessScope": p["businessScope"], "productScope": p["productScope"],
            "validity": {"from": p["validFrom"], "until": p["validUntil"]}, "countries": p["countries"], "path": {"companyIds": p["pathCompanyIds"]},
            "evidence": {"relation": p["evidenceIds"], "validity": p["validityEvidenceIds"], "steps": [p["step1EvidenceIds"], p["step2EvidenceIds"]]},
            "sourceRelationCandidateIds": p["sourceRelationCandidateIds"], "sourceApprovals": edge["approvals"]}


def focus_of(plan: dict, company_id: str, depth: int) -> dict:
    """Breadth-first over the undirected adjacency of the ALREADY VERIFIED, bounded (<= MAX_EDGES) version. An edge is shown iff one endpoint is
    closer than `depth`, so depth 1 is the company's own edges and no edge between two outermost nodes is added. This is a read-only view limited
    to depth 1..3; it is not the S3 production path length."""
    # Presence is a property of the verified NODE set, not of the edges: a path-intermediate company is a node of the version although no projected edge has
    # it as an endpoint. Adjacency still comes only from the projected edges; no path-step edge is synthesized.
    adjacency: dict[tuple, set] = {(KIND_OF_LABEL[label], ident): set() for label, ident in plan["nodes"]}
    for e in plan["edges"]:
        a, b = (e["subject"]["kind"], e["subject"]["id"]), (e["object"]["kind"], e["object"]["id"])
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    start = ("company", company_id)
    if depth not in DEPTHS or start not in adjacency:
        return {"found": False, "nodes": [], "edges": []}
    distance = {start: 0}
    frontier = [start]
    for step in range(1, depth + 1):
        following = []
        for node in frontier:
            for other in sorted(adjacency[node]):
                if other not in distance:
                    distance[other] = step
                    following.append(other)
        frontier = following
    edges = [e for e in plan["edges"] if min(distance.get((e["subject"]["kind"], e["subject"]["id"]), depth + 1),
                                              distance.get((e["object"]["kind"], e["object"]["id"]), depth + 1)) <= depth - 1]
    return {"found": True, "nodes": [{"kind": kind, "id": ident, "distance": d} for (kind, ident), d in sorted(distance.items())], "edges": edges}


# ---------------------------------------------------------------------------------------------- the projector -----------------------

class _Verdict(Exception):
    """How one `project` attempt ended without a commit, or with an unknown one: the version state, the attempt outcome and the reported code."""

    def __init__(self, state: str, outcome: str, code: str, detail: dict | None = None):
        self.state, self.outcome, self.code, self.detail = state, outcome, code, detail
        super().__init__(code)


def _open_graph(binding: dict) -> neo.Graph:
    return neo.Graph(binding["uri"], binding["database"], neo.read_auth(binding["uri"]))


def _compare(observed: neo.Observed, plan: dict, marker: dict) -> bool:
    """Extra, missing or altered nodes/edges/properties change the content digest or the counts, so they can never read as the planned version."""
    return (observed.marker == marker and len(observed.nodes) == len(plan["nodes"]) and len(observed.edges) == len(plan["edges"])
            and graph_digest(plan["versionId"], observed.nodes, observed.edges) == marker["graphDigest"])


class Projector:
    def __init__(self, store: Store, paths: Paths | None = None):
        self.store, self.paths = store, paths

    # ---- seams for process-level tests (no production effect) -------------------------------------------------------------------------

    def _after_reserve(self) -> None:
        """Called once the attempt is durably `reserved` and before the first Neo4j write."""

    def _written(self, tx, stage: str) -> None:
        """Called after each write stage (`nodes:<kind>`, `edges:<type>`, `marker`) inside the still-uncommitted transaction `tx`."""

    def _commit(self, tx) -> None:
        tx.commit()

    # ---- shared helpers ---------------------------------------------------------------------------------------------------------------------

    def _existing(self, version_id: str):
        row = self.store.version(version_id)
        if row is None:
            raise ExtractionFailure("version_not_found")
        return row

    def result(self, row) -> dict:
        return ledger_result(row, self.store.attempts(row["version_id"]))

    def _authority(self, source: Source, plan: dict, registry: Registry) -> dict:
        """Current S3/S2 authority bound to the frozen upstream, and every used canonical decision still present and identical."""
        result = gate(source, plan["source"]["relation"], plan["source"]["upstream"])
        for entry in plan["canonical"]["entries"]:
            found = registry.entries.get(entry_key(entry["upstream"]["jobId"], entry["upstream"]["inputDigest"], entry["kind"], entry["ref"]))
            if found is None or found.wire() != entry:
                raise Withheld("canonical_mapping_changed")
        return result

    @staticmethod
    def _unchanged_review(plan: dict, result: dict) -> bool:
        """Every projected relation is still eligible, not review-pending, at the same revision and with exactly the pinned approval basis (kind, reviewer,
        decision time; proven against its own history again). Returns whether the WHOLE review state (also excluded candidates) is still the frozen one; a
        newer review state calls for a new version, it does not withhold this immutable one."""
        by_id = {r["relationCandidateId"]: r for r in result["relations"]}
        for item in plan["source"]["review"]["projected"]:
            relation = by_id.get(item["relationCandidateId"])
            state = relation["eligibility"] if relation is not None else None
            if state is None or state["status"] != "eligible" or state["reviewPending"] or state["revision"] != item["revision"]:
                raise Withheld("review_revision_changed")
            try:
                current = approval_basis(relation)
            except ExtractionFailure:
                raise Withheld("review_revision_changed") from None
            if current != item["approvalBasis"]:
                raise Withheld("review_revision_changed")
        return digest(review_state(result)) == plan["source"]["review"]["digest"]

    def _strict(self, source: Source, plan: dict, registry: Registry) -> None:
        """The gate of a write: authority plus the WHOLE review state exactly as frozen (the ERD's `input revision == current revision` at commit)."""
        result = self._authority(source, plan, registry)
        if digest(review_state(result)) != plan["source"]["review"]["digest"]:
            raise ExtractionFailure("review_revision_changed")

    # ---- init ------------------------------------------------------------------------------------------------------------------------------

    def init(self, request: Init, uri: str) -> dict:
        """Bind this ledger to ONE empty database. The intent (including a random owner identity that only this ledger knows) is committed to SQLite
        before any DDL or marker is written, and only that exact owner can resume or re-verify the store: a database that is not empty, or whose
        marker belongs to someone else, is never adopted."""
        auth = neo.read_auth(uri)
        binding = self.store.bound()
        if binding is not None and (binding["storeId"] != request.store_id or binding["database"] != request.database or binding["uri"] != uri):
            raise ExtractionFailure("graph_store_already_bound")
        graph = neo.Graph(uri, request.database, auth)
        try:
            facts = neo.probe(graph)
            if binding is None:
                refuse_unbound_target(facts, request.database)   # the same rule `preflight` applies; refused before any intent, DDL or store marker
            elif facts["database"].lower() != request.database.lower() or facts["dbId"] != binding["dbId"]:
                raise ExtractionFailure("graph_store_identity_mismatch")
            if binding is not None and self.store.meta("store-ready") is not None:
                server = neo.verify_binding(graph, self.store.ready_binding())
                return self._init_result(binding, server)
            if binding is None:
                binding = {"uri": uri, "database": request.database, "dbId": facts["dbId"], "storeId": request.store_id, "owner": uuid.uuid4().hex,
                           "schema": STORE_SCHEMA, "server": facts["server"]}
                self.store.bind(binding)
                adopted = False
            else:
                ours = {"slot": neo.STORE_SLOT, "storeId": binding["storeId"], "schema": STORE_SCHEMA, "owner": binding["owner"]}
                adopted = bool(facts["stores"])
                if adopted:
                    # A crashed earlier `init` of THIS ledger: exactly its own marker and nothing else.
                    if not (len(facts["stores"]) == 1 and facts["stores"][0]["l"] == [neo.STORE_LABEL] and facts["stores"][0]["p"] == ours
                            and facts["nodes"] == 1 and facts["relationships"] == 0):
                        raise ExtractionFailure("graph_store_not_empty")
                elif facts["nodes"] or facts["relationships"] or not tolerated_schema(facts):
                    raise ExtractionFailure("graph_store_not_empty")
                if neo.schema_conflicts(facts["constraints"], facts["indexes"]):
                    raise ExtractionFailure("graph_store_schema_mismatch")   # same, for an interrupted init: before any DDL
            neo.ensure_schema(graph)
            if not adopted:
                neo.create_store(graph, binding)
            server = neo.verify_binding(graph, binding)
            self.store.mark_ready(binding)
            return self._init_result(binding, server)
        finally:
            graph.close()

    @staticmethod
    def _init_result(binding: dict, server: dict) -> dict:
        return {"schemaVersion": SCHEMA, "store": {"state": "bound", "storeId": binding["storeId"], "database": binding["database"], "dbId": binding["dbId"],
                                                   "server": server, "schemaObjects": {"constraints": len(neo.CONSTRAINTS), "indexes": len(neo.INDEXES)}},
                "usage": USAGE}

    # ---- freeze ----------------------------------------------------------------------------------------------------------------------------

    def freeze(self, request: Freeze) -> dict:
        """Pure SQLite: pin one ready, currently delivered S3 job and the exact canonical decisions into an immutable `frozen` version. Never touches
        Neo4j. A version that already exists is never changed: the same request is echoed ONLY while the pinned upstream (grant revision included)
        and every used canonical decision are still current, a different request is `version_input_conflict` with nothing written."""
        paths = self.paths
        relation = request.wire()["relation"]
        input_digest = digest(request.wire())
        row = self.store.version(request.version_id)
        if row is not None and not plan_current(row):
            raise ExtractionFailure("graph_contract_changed")        # history: decided from the stored plan schema alone; a changed review needs a NEW version id
        registry = load_registry(paths.canonical)
        with Source(paths) as source:
            if row is not None:
                if row["input_digest"] != input_digest:
                    raise ExtractionFailure("version_input_conflict")
                self._authority(source, verify_plan(row), registry)
                return self.result(row)
            result = gate(source, relation, None)
            plan = plan_version(request.version_id, result, registry.entries)
            payload, graph = digest(plan), plan_graph_digest(plan)

            def guard() -> None:
                fresh = gate(source, relation, plan["source"]["upstream"])
                if digest(review_state(fresh)) != plan["source"]["review"]["digest"]:
                    raise ExtractionFailure("review_revision_changed")
                registry_unchanged(registry, paths.canonical)

            with self.store.transaction(guard):
                self.store.db.execute("INSERT INTO versions(version_id,input_digest,request,plan,payload_digest,graph_digest,state,created_at,updated_at) "
                                      "VALUES(?,?,?,?,?,?,'frozen',?,?)", (request.version_id, input_digest, canonical(request.wire()), canonical(plan),
                                                                          payload, graph, now(), now()))
        return self.result(self._existing(request.version_id))

    def inspect(self, request: Selector) -> dict:
        row = self._existing(request.version_id)
        if plan_current(row):
            verify_plan(row)
        return self.result(row)

    # ---- project ---------------------------------------------------------------------------------------------------------------------------

    def project(self, request: Selector) -> dict:
        """Write one frozen version as ONE explicit unmanaged transaction (never retried automatically). The attempt is `reserved` in SQLite first;
        a commit whose outcome is unknown stays `unknown` until `recover` has read the whole graph back."""
        row = self._existing(request.version_id)
        if not plan_current(row):
            raise ExtractionFailure("graph_contract_changed")        # never projected, resumed or settled: an earlier contract's plan has no pinned approval basis
        version_id, state = row["version_id"], row["state"]
        if state == "ready":
            return self.result(row)
        if state in {"reserved", "unknown"}:
            raise ExtractionFailure("graph_commit_unknown", {"state": state})
        if state != "frozen":
            raise ExtractionFailure("version_not_frozen", {"state": state})
        if self.store.one("SELECT COUNT(*) AS n FROM attempts WHERE version_id=?", (version_id,))["n"] >= MAX_ATTEMPTS:
            raise ExtractionFailure("attempt_limit_exceeded")
        plan = verify_plan(row)
        binding = self.store.ready_binding()
        registry = load_registry(self.paths.canonical)
        with Source(self.paths) as source:
            try:
                self._strict(source, plan, registry)
            except ExtractionFailure as exc:
                self.store.note_failure(version_id, exc.code, exc.detail)
                raise
            graph = _open_graph(binding)
            try:
                neo.verify_binding(graph, binding)
                n = self.store.reserve(version_id)
                self._after_reserve()
                return self._write(graph, source, registry, row, plan, binding, n)
            finally:
                graph.close()

    def _write(self, graph: neo.Graph, source: Source, registry: Registry, row, plan: dict, binding: dict, n: int) -> dict:
        version_id = row["version_id"]
        marker = marker_props(plan, binding["storeId"], row["payload_digest"], row["graph_digest"])
        committing = False
        verdict: _Verdict | None = None
        interrupted: BaseException | None = None
        try:
            with graph.transaction(write=True, raw=True, metadata={"zoopVersionId": version_id, "zoopAttempt": n, "zoopPayloadDigest": row["payload_digest"]}) as tx:
                self._guard(tx, version_id, binding)
                self._writes(tx, plan, marker)
                observed = self._observe(tx, version_id)
                if not _compare(observed, plan, marker):
                    raise _Verdict("frozen", "rolled-back", "graph_write_mismatch")
                try:
                    self._strict(source, plan, registry)
                    registry_unchanged(registry, self.paths.canonical)
                except ExtractionFailure as exc:
                    raise _Verdict("frozen", "rolled-back", exc.code, exc.detail) from None
                committing = True
                self._commit(tx)
        except _Verdict as exc:
            verdict = exc
        except Exception as exc:  # noqa: BLE001 - classified: before commit() nothing is committed, anything from commit() is unknown
            verdict = self._classify(exc, committing)
        except BaseException as exc:  # noqa: BLE001 - interrupt: same rule, then re-raised
            interrupted = exc
            verdict = _Verdict("unknown", "unknown", "graph_commit_unknown") if committing else _Verdict("frozen", "not-committed", "graph_internal_failure")
        if verdict is None:
            # If this write fails (sqlite3.Error) the row stays `reserved` and `recover` proves what Neo4j holds.
            self.store.finish(version_id, n, "ready", "committed")
            return self.result(self._existing(version_id))
        self.store.finish(version_id, n, verdict.state, verdict.outcome, verdict.code, verdict.detail)
        if interrupted is not None:
            raise interrupted
        raise ExtractionFailure(verdict.code, verdict.detail)

    @staticmethod
    def _classify(exc: Exception, committing: bool) -> _Verdict:
        if committing or isinstance(exc, ConstraintError):
            # ConstraintError: another writer may have committed this version's marker, so a clean `not committed` cannot be claimed.
            return _Verdict("unknown", "unknown", "graph_commit_unknown")
        if isinstance(exc, ExtractionFailure):
            return _Verdict("frozen", "rolled-back", exc.code, exc.detail)
        if isinstance(exc, (DriverError, Neo4jError, OSError)):
            failure = neo.translate(exc, True)
            return _Verdict("frozen", "not-committed", failure.code, failure.detail)
        return _Verdict("frozen", "not-committed", "graph_internal_failure")

    @staticmethod
    def _guard(tx, version_id: str, binding: dict) -> None:
        """Inside the write transaction, before any write: still the bound database and store, and no trace of this version."""
        info, stores = neo.run(tx, neo.DB_INFO), neo.run(tx, neo.STORE_READ)
        ours = {"slot": neo.STORE_SLOT, "storeId": binding["storeId"], "schema": STORE_SCHEMA, "owner": binding["owner"]}
        if (len(info) != 1 or str(info[0]["id"]) != binding["dbId"] or len(stores) != 1 or stores[0]["l"] != [neo.STORE_LABEL] or stores[0]["p"] != ours):
            raise _Verdict("frozen", "rolled-back", "graph_store_identity_mismatch")
        markers, nodes = neo.presence(tx, version_id)
        if markers:
            raise _Verdict("unknown", "unknown", "graph_commit_unknown")
        if nodes:
            raise _Verdict("failed", "not-committed", "graph_version_corrupt")

    def _writes(self, tx, plan: dict, marker: dict) -> None:
        version_id = plan["versionId"]
        for kind, label in LABELS.items():
            ids = sorted(ident for node_label, ident in plan["nodes"] if node_label == label)
            if ids:
                neo.write_nodes(tx, version_id, label, ids)
            self._written(tx, f"nodes:{kind}")
        for name in EDGE_SPECS:
            rows = [{"subject": e["subject"]["id"], "object": e["object"]["id"], "props": stored_props(version_id, e["props"])}
                    for e in plan["edges"] if e["type"] == name]
            if rows:
                neo.write_edges(tx, version_id, name, rows)
            self._written(tx, f"edges:{name}")
        neo.write_marker(tx, marker)
        self._written(tx, "marker")

    @staticmethod
    def _observe(tx, version_id: str) -> neo.Observed:
        try:
            return neo.observe(tx, version_id)
        except neo.Mismatch:
            raise _Verdict("frozen", "rolled-back", "graph_write_mismatch") from None

    # ---- recover ---------------------------------------------------------------------------------------------------------------------------

    def recover(self, request: Selector) -> dict:
        """Settle a `reserved`/`unknown` version from what Neo4j actually holds. Reads only: it never writes the graph, never regenerates anything
        and never calls a model. The decision comes from the FULL stored graph, not from the marker alone."""
        row = self._existing(request.version_id)
        if not plan_current(row):
            raise ExtractionFailure("graph_contract_changed")        # an earlier contract's attempt is never settled by this build
        version_id = row["version_id"]
        if row["state"] not in {"reserved", "unknown"}:
            raise ExtractionFailure("recovery_not_required", {"state": row["state"]})
        plan = verify_plan(row)
        binding = self.store.ready_binding()
        latest = self.store.one("SELECT MAX(n) AS n FROM attempts WHERE version_id=?", (version_id,))["n"]
        graph = _open_graph(binding)
        try:
            neo.verify_binding(graph, binding)
            marker = marker_props(plan, binding["storeId"], row["payload_digest"], row["graph_digest"])
            with graph.transaction(write=False) as tx:
                markers, nodes = neo.presence(tx, version_id)
                if len(markers) > 1:
                    verdict = ("failed", "unknown", "graph_version_corrupt")
                elif markers:
                    if markers[0]["l"] != [neo.VERSION_LABEL] or markers[0]["p"] != marker:
                        verdict = ("failed", "unknown", "graph_version_conflict")
                    else:
                        try:
                            ok = _compare(neo.observe(tx, version_id), plan, marker)
                        except neo.Mismatch:
                            ok = False
                        verdict = ("ready", "confirmed", None) if ok else ("failed", "unknown", "graph_version_corrupt")
                elif nodes:
                    verdict = ("failed", "not-committed", "graph_version_corrupt")
                else:
                    verdict = ("frozen", "not-committed", None)
        finally:
            graph.close()
        self.store.finish(version_id, latest, *verdict)
        return self.result(self._existing(version_id))

    # ---- read / focus ---------------------------------------------------------------------------------------------------------------------

    def read(self, request: Selector | Focus) -> dict:
        """A ready version, only after: the S3/S2 authority is current and bound to the frozen upstream, the used canonical decisions are unchanged,
        the projected relations are unchanged, the Neo4j database is still exactly the bound store, and the FULL stored graph matches the frozen
        content digest. Any failure is a `withheld` result with no content. Read-only: no ledger write, no S3 write, no model call."""
        row = self._existing(request.version_id)
        if not plan_current(row):
            return withheld_result(row, "graph_contract_changed")
        if row["state"] != "ready":
            raise ExtractionFailure("version_not_ready", {"state": row["state"]})
        plan = verify_plan(row)
        binding = self.store.ready_binding()
        registry = load_registry(self.paths.canonical)
        try:
            with Source(self.paths) as source:
                result = self._authority(source, plan, registry)
                review_matches = self._unchanged_review(plan, result)
                graph = _open_graph(binding)
                try:
                    try:
                        neo.verify_binding(graph, binding)
                    except ExtractionFailure as exc:
                        if exc.code in _STORE_WITHHOLDS:
                            raise Withheld(exc.code) from None
                        raise
                    marker = marker_props(plan, binding["storeId"], row["payload_digest"], row["graph_digest"])
                    with graph.transaction(write=False) as tx:
                        try:
                            observed = neo.observe(tx, request.version_id)
                        except neo.Mismatch:
                            raise Withheld("graph_version_corrupt") from None
                    if not _compare(observed, plan, marker):
                        raise Withheld("graph_version_corrupt")
                finally:
                    graph.close()
        except Withheld as exc:
            return withheld_result(row, exc.code)
        out = self.result(row)
        out["delivery"] = {"status": "current", "authority": "S3/S2 authority, canonical decisions, review state and the full stored graph verified now"}
        out["current"] = {"s3ReviewDigestMatches": review_matches}
        verification = {"marker": "matched", "graphDigest": row["graph_digest"], "nodes": len(observed.nodes), "edges": len(observed.edges)}
        if isinstance(request, Focus):
            view = focus_of(plan, request.company_id, request.depth)
            referenced = {i for e in view["edges"] for i in e["props"]["evidenceIds"] + e["props"]["validityEvidenceIds"] + e["props"]["step1EvidenceIds"]
                          + e["props"]["step2EvidenceIds"]}
            out["focus"] = {"companyId": request.company_id, "depth": request.depth, "found": view["found"]}
            out["graph"] = {"nodes": view["nodes"], "edges": [edge_view(e) for e in view["edges"]]}
            out["evidence"] = [e for e in plan["evidence"] if e["evidenceId"] in referenced]
        else:
            out["graph"] = {"nodes": [{"kind": KIND_OF_LABEL[node_label], "id": ident} for node_label, ident in plan["nodes"]],
                            "edges": [edge_view(e) for e in plan["edges"]]}
            out["evidence"] = plan["evidence"]
        out["verification"] = verification
        return out
