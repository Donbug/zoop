"""AI-side, versioned, immutable public-graph HANDOFF bundle (not an app graph version, not activation, not public readiness).

Flow: `freeze` pins an operator manifest (>= 1 S3 relation jobs with their S2 upstreams, review revisions and the exact operator files), re-reads every
source through the existing owner seams (the same gates as `zoop-ai-graph`: S3 `inspect` re-verifies the S2 job, grants/rights and candidate set), builds
ONE canonical public issue-centric projection, validates it strictly and stores it as a content-addressed artifact bound to the handoff ID.
`recover` settles a `reserved` handoff from the stored artifact only (it never regenerates). `inspect` is ledger + artifact integrity.
`export` re-validates CURRENT authority, then prints the bundle; any drift is a content-free `withheld` result.

What this module does NOT do: write the app, register evidence, activate a version, decide asOf policy, call a model/provider/network, touch Neo4j, or
write any source ledger. The producer confirms only SOURCE-side facts; app-side verification stays `appImportPending` in the bundle.
"""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .extraction import Extractor, Sources, cite_exact, upstream_digest
from .extraction import Store as ExtractionStore
from .extraction_contracts import CitationFailure, ExtractionFailure, Mention, ObservationRef
from .graph_projection import Paths as SourcePaths
from .graph_projection import Registry, Source, gate, load_registry, review_state
from .graph_projection_contracts import MAX_REGISTRY, Withheld, entry_key
from .handoff_contracts import (APP_IMPORT_PENDING, BUNDLE_SCHEMA, EVIDENCE_KIND, LEDGER_VERSION, MAX_ATTEMPTS, MAX_BUNDLE, MAX_EVIDENCE, MAX_EXCLUSIONS,
    MAX_ISSUES, MAX_OPERATOR_FILE, MAX_RELATIONS, OFFSET_UNIT, POLICY, PRODUCER_CHECKS, SCHEMA, STRUCTURAL_BASIS_TYPES, Bindings, Decisions, Manifest, Selector,
    app_evidence_id, content_digest, countries_class, text_sha256, time_precision, validate_bundle)
from .ingestion_contracts import Authority, IngestionFailure, byte_hash, canonical, digest, now, read_file, reserved_state_roots

_SQL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS handoffs(handoff_id TEXT PRIMARY KEY, input_digest TEXT NOT NULL, manifest TEXT NOT NULL, bundle_digest TEXT NOT NULL,
 content_digest TEXT NOT NULL, bundle_bytes INTEGER NOT NULL, receipt TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('reserved','ready','failed')), failure TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(handoff_id TEXT NOT NULL REFERENCES handoffs(handoff_id), n INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('freeze','recover')),
 outcome TEXT NOT NULL CHECK(outcome IN ('written','confirmed','artifact-missing','artifact-invalid')), code TEXT, at TEXT NOT NULL, PRIMARY KEY(handoff_id,n));
"""
_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS immutable_meta_update BEFORE UPDATE ON meta BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_meta_delete BEFORE DELETE ON meta BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_handoffs_delete BEFORE DELETE ON handoffs BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_handoffs_identity BEFORE UPDATE OF handoff_id,input_digest,manifest,bundle_digest,content_digest,bundle_bytes,receipt,"
    "created_at ON handoffs BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS terminal_handoffs BEFORE UPDATE ON handoffs WHEN OLD.state IN ('ready','failed') BEGIN SELECT RAISE(ABORT,'terminal'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_attempts_update BEFORE UPDATE ON attempts BEGIN SELECT RAISE(ABORT,'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS immutable_attempts_delete BEFORE DELETE ON attempts BEGIN SELECT RAISE(ABORT,'immutable'); END",
)
_FILES = {"handoff.sqlite3", "handoff.sqlite3-wal", "handoff.sqlite3-shm", "handoff.lock", "bundles"}
NEXT = {"reserved": "recover", "ready": "export", "failed": None}
USAGE = {"providerCalls": 0, "modelCalls": 0}
POLICIES = {"geography": "operator-field-verdict", "structural": "manual-operator-review", "sequence": "s2-comparison-with-operator-decision"}


# ---------------------------------------------------------------------------------------------- ledger -------------------------------

class Store:
    """The handoff ledger (`handoff.sqlite3` + `handoff.lock` + `bundles/`), same rules as the other pipeline ledgers: a dedicated directory disjoint from
    the app, S1 and every source ledger, no symlinks, 0700/0600, one exclusive non-blocking writer lock, WAL + synchronous=FULL.

    mode `create` (freeze only) may create the directory and ledger; `write` needs an existing ledger; `read` takes a shared lock, opens the file immutable
    and read-only, creates nothing and refuses a hot WAL (a writer command must settle it first). A writer holding the lock is `handoff_busy`."""

    def __init__(self, root: Path, *upstream_roots: Path, mode: str = "write"):
        self.root = root = Path(os.path.abspath(root))
        forbidden = [*reserved_state_roots(), *(Path(os.path.abspath(p)) for p in upstream_roots)]
        if any(root == p or root.is_relative_to(p) or p.is_relative_to(root) for p in forbidden):
            raise ExtractionFailure("state_namespace_conflict")
        for parent in [*reversed(root.parents), root]:
            if parent.exists() and parent.is_symlink():
                raise ExtractionFailure("state_namespace_invalid")
        if mode == "read":
            self._open_existing(root)
            return
        if mode == "create":
            if root.exists():
                if not root.is_dir():
                    raise ExtractionFailure("state_namespace_conflict")
                self._check_names(root)
                if list(root.iterdir()):
                    self._preflight_existing(root)
            else:
                root.mkdir(mode=0o700, parents=True)
            (root / "bundles").mkdir(mode=0o700, exist_ok=True)
        elif not root.is_dir() or not (root / "handoff.sqlite3").is_file() or not (root / "handoff.lock").is_file():
            raise ExtractionFailure("handoff_state_missing")
        else:
            self._check_names(root)
            self._preflight_existing(root)
        self._check_names(root)
        os.chmod(root, 0o700)
        self.lock = os.open(root / "handoff.lock", os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if mode == "create" else 0), 0o600)
        os.fchmod(self.lock, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.lock)
            del self.lock
            raise ExtractionFailure("handoff_busy") from exc
        try:
            database = root / "handoff.sqlite3"
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
                self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            try:
                ledger = self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
            except sqlite3.DatabaseError as exc:
                raise ExtractionFailure("handoff_state_invalid") from exc
            if ledger is None or ledger["value"] != LEDGER_VERSION:
                raise ExtractionFailure("ledger_version_unknown")
            for p in root.iterdir():
                os.chmod(p, 0o700 if p.is_dir() else 0o600)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _check_names(root: Path) -> None:
        if any(p.name not in _FILES or p.is_symlink() or (p.name == "bundles" and not p.is_dir()) for p in root.iterdir()):
            raise ExtractionFailure("state_namespace_conflict")

    @staticmethod
    def _preflight_existing(root: Path) -> None:
        """No chmod, lock creation or SQLite write until an existing ledger proves ownership."""
        database, lock = root / "handoff.sqlite3", root / "handoff.lock"
        if not database.is_file() or database.is_symlink() or not lock.is_file() or lock.is_symlink() or not (root / "bundles").is_dir():
            raise ExtractionFailure("state_namespace_conflict")
        # A newly owned ledger checkpoints its identity before accepting handoffs;
        # an immutable preflight can identify it even after a killed writer left a WAL.
        try:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
                identity = db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
                objects = {(kind, name) for kind, name in db.execute("SELECT type,name FROM sqlite_master") if not name.startswith("sqlite_autoindex_")}
            expected = {("table", name) for name in ("meta", "handoffs", "attempts")}
            expected.update(("trigger", statement.split()[5]) for statement in _TRIGGERS)
            if identity is None or identity[0] != LEDGER_VERSION or objects != expected:
                raise ExtractionFailure("ledger_version_unknown")
        except sqlite3.DatabaseError as exc:
            raise ExtractionFailure("handoff_state_invalid") from exc

    def _open_existing(self, root: Path) -> None:
        database, lock = root / "handoff.sqlite3", root / "handoff.lock"
        if not root.is_dir() or not database.is_file() or not lock.is_file():
            raise ExtractionFailure("handoff_state_missing")
        self._check_names(root)
        self.lock = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.close()
            raise ExtractionFailure("handoff_busy") from exc
        try:
            wal = root / "handoff.sqlite3-wal"
            if wal.exists() and wal.stat().st_size > 0:
                raise ExtractionFailure("handoff_recovery_required")
            self.db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA query_only=ON")
            self.db.execute("SELECT 1 FROM handoffs LIMIT 1")
            meta = self.db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()
            if meta is None or meta["value"] != LEDGER_VERSION:
                raise ExtractionFailure("ledger_version_unknown")
        except sqlite3.DatabaseError as exc:
            self.close()
            raise ExtractionFailure("handoff_state_invalid") from exc
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

    def handoff(self, handoff_id: str):
        return self.db.execute("SELECT * FROM handoffs WHERE handoff_id=?", (handoff_id,)).fetchone()

    def attempts(self, handoff_id: str) -> list:
        return self.db.execute("SELECT n,kind,outcome,code FROM attempts WHERE handoff_id=? ORDER BY n", (handoff_id,)).fetchall()

    def settle(self, handoff_id: str, kind: str, state: str, outcome: str, code: str | None = None) -> None:
        """One atomic ledger step: the attempt receipt and the state change together. `ready` and `failed` are terminal (a trigger refuses any later change)."""
        with self.transaction():
            n = self.db.execute("SELECT COUNT(*) AS n FROM attempts WHERE handoff_id=?", (handoff_id,)).fetchone()["n"] + 1
            if n > MAX_ATTEMPTS:
                raise ExtractionFailure("attempt_limit_exceeded")
            self.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?)", (handoff_id, n, kind, outcome, code, now()))
            self.db.execute("UPDATE handoffs SET state=?,failure=?,updated_at=? WHERE handoff_id=?", (state, code if state == "failed" else None, now(), handoff_id))


# ---------------------------------------------------------------------------------------------- artifact file -----------------------

def artifact_path(root: Path, bundle_digest: str) -> Path:
    return root / "bundles" / f"{bundle_digest}.json"


def write_artifact(root: Path, raw: bytes, bundle_digest: str) -> None:
    """Content-addressed, written once: temporary 0600 file -> fsync -> no-overwrite hard link -> directory fsync. An existing file of that name is
    adopted ONLY when its bytes hash to the name (a crash between write and ledger step leaves exactly that); anything else is a conflict."""
    directory, final = root / "bundles", artifact_path(root, bundle_digest)
    if final.exists() or final.is_symlink():
        if byte_hash(read_file(final, MAX_BUNDLE)) != bundle_digest:
            raise ExtractionFailure("handoff_artifact_conflict")
        return
    temporary = directory / f".tmp-{uuid.uuid4().hex}"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view, written = memoryview(raw), 0
        while written < len(raw):
            written += os.write(fd, view[written:])
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(temporary, final)
    except FileExistsError:
        if byte_hash(read_file(final, MAX_BUNDLE)) != bundle_digest:
            raise ExtractionFailure("handoff_artifact_conflict") from None
    finally:
        os.unlink(temporary)
    dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def read_bundle(root: Path, row) -> dict:
    """The stored artifact exactly as frozen: file present, bytes hash to the ledger digest, canonical form, strict validation and ledger identity."""
    try:
        raw = read_file(artifact_path(root, row["bundle_digest"]), MAX_BUNDLE)
    except (IngestionFailure, OSError):
        raise ExtractionFailure("handoff_artifact_missing") from None
    ok = False
    try:
        bundle = json.loads(raw)
        ok = (byte_hash(raw) == row["bundle_digest"] and len(raw) == row["bundle_bytes"] and canonical(bundle).encode("utf-8") == raw)
        if ok:
            validate_bundle(bundle)
            ok = (bundle["handoffId"] == row["handoff_id"] and bundle["manifestDigest"] == row["input_digest"]
                  and bundle["digests"]["content"] == row["content_digest"] and content_digest(bundle) == row["content_digest"])
    except ExtractionFailure:
        ok = False
    except (ValueError, KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        raise ExtractionFailure("handoff_artifact_invalid")
    return bundle


def read_manifest(row, bundle: dict) -> tuple[Manifest, dict]:
    """The manifest exactly as frozen in the ledger row: canonical text, the SHA-256 of that canonical form is the ledger input digest AND the bundle's
    `manifestDigest`, and it agrees with the bundle on identity, declaration, policy version, operator file pins and source pins. Never rebuilt from today's
    configuration or files: a missing, damaged or hand-edited ledger manifest is `handoff_artifact_invalid`."""
    try:
        text = row["manifest"]
        manifest = Manifest.model_validate_json(text)
        wire = manifest.wire()
        pins = [{"relation": s.relation.wire(), "upstream": s.upstream.wire(), "reviewDigest": s.review_digest} for s in manifest.sources]
        used = [{"relation": s["relation"], "upstream": s["upstream"], "reviewDigest": s["reviewDigest"]} for s in bundle["sources"]]
        ok = (canonical(wire) == text and digest(wire) == row["input_digest"] == bundle["manifestDigest"]
              and manifest.handoff_id == row["handoff_id"] == bundle["handoffId"]
              and manifest.source_kind == bundle["provenance"]["declaredSourceKind"] and manifest.policy_version == bundle["policy"]["version"]
              and manifest.files.wire() == bundle["policy"]["files"] and sorted(pins, key=canonical) == sorted(used, key=canonical))
    except (ValueError, KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        raise ExtractionFailure("handoff_artifact_invalid")
    return manifest, wire


# ---------------------------------------------------------------------------------------------- operator files ----------------------

@dataclass(frozen=True)
class HandoffPaths:
    relation: Path
    extraction: Path
    ingestion: Path
    sources: Path
    canonical: Path
    decisions: Path
    bindings: Path

    def source(self) -> SourcePaths:
        return SourcePaths(self.relation, self.extraction, self.ingestion, self.sources, self.canonical)


@dataclass
class Operator:
    """The three operator-owned files as read NOW (raw bytes are kept to prove they did not change during one command)."""
    registry: Registry
    decisions: Decisions
    decisions_raw: bytes
    bindings: dict
    bindings_raw: bytes

    def hashes(self) -> dict:
        return {"canonical": byte_hash(self.registry.raw), "decisions": byte_hash(self.decisions_raw), "bindings": byte_hash(self.bindings_raw)}


def load_operator(paths: HandoffPaths) -> Operator:
    registry = load_registry(paths.canonical)
    try:
        decisions_raw = read_file(paths.decisions, MAX_OPERATOR_FILE)
        decisions = Decisions.model_validate_json(decisions_raw)
    except (IngestionFailure, OSError, ValueError):
        raise ExtractionFailure("decisions_invalid") from None
    try:
        bindings_raw = read_file(paths.bindings, MAX_OPERATOR_FILE)
        parsed = Bindings.model_validate_json(bindings_raw)
    except (IngestionFailure, OSError, ValueError):
        raise ExtractionFailure("bindings_invalid") from None
    return Operator(registry, decisions, decisions_raw, {(b.document_id, b.document_version): b for b in parsed.bindings}, bindings_raw)


def operator_unchanged(op: Operator, paths: HandoffPaths) -> None:
    try:
        same = (read_file(paths.canonical, MAX_REGISTRY) == op.registry.raw and read_file(paths.decisions, MAX_OPERATOR_FILE) == op.decisions_raw
                and read_file(paths.bindings, MAX_OPERATOR_FILE) == op.bindings_raw)
    except (IngestionFailure, OSError):
        same = False
    if not same:
        raise ExtractionFailure("operator_file_changed")


# ---------------------------------------------------------------------------------------------- source loading --------------------

@dataclass
class Loaded:
    """One constituent S3 job read NOW through the owner seams, with its S2 upstream and every bound document export."""
    pin: object
    s3: dict
    submit: object
    s2: dict
    docs: dict            # (documentId, documentVersion) -> list[(exact ObservationRef, export)]
    sources: Sources
    upstream_key: tuple   # (S2 jobId, S2 inputDigest): what canonical decisions are bound to
    relations: dict       # relationCandidateId -> S3 relation payload


def load_source(source: Source, paths: HandoffPaths, manifest: Manifest, pin, *, strict: bool) -> Loaded:
    """The S3 result only while it is ready, currently delivered and bound to the pinned upstream (grant revision included) and, when `strict`, the exactly
    pinned whole review state. The S2 upstream is re-read through its own owner and must be the exact one S3 consumed (its digest equals the pin)."""
    result = gate(source, pin.relation.wire(), pin.upstream.wire())
    if strict and digest(review_state(result)) != pin.review_digest:
        raise ExtractionFailure("review_revision_changed")
    sources = Sources(paths.ingestion, Authority(paths.sources))
    store = ExtractionStore(paths.extraction, paths.ingestion, existing=True)
    try:
        submit, s2 = Extractor(store, sources).export(pin.upstream.job_id)
    finally:
        store.close()
    if upstream_digest(s2) != pin.upstream.digest:
        raise Withheld("upstream_changed")
    for kind in (result["provenance"]["sourceKind"], s2["provenance"]["sourceKind"]):
        if kind != manifest.source_kind:
            raise ExtractionFailure("provenance_conflict")
    docs: dict = {}
    for _, bound in sorted(s2["binding"]["documents"].items()):
        ref = ObservationRef.model_validate(bound["observation"])
        docs.setdefault((ref.document_id, ref.document_version), []).append((ref, sources.export(ref)))
    return Loaded(pin, result, submit, s2, docs, sources, (pin.upstream.job_id, pin.upstream.input_digest),
                  {r["relationCandidateId"]: r for r in result["relations"]})


def current(source: Source, paths: HandoffPaths, manifest: Manifest, op: Operator, *, strict: bool) -> list[Loaded]:
    """Every pinned operator file byte-identical to the manifest, then every constituent source current. `strict` (freeze and its idempotent echo) also
    demands the exact pinned review state and reports mismatches as errors; export (not strict) answers any drift as `withheld`."""
    names = {"canonical": "canonical_mapping_changed", "decisions": "decisions_changed", "bindings": "bindings_changed"}
    for name, value in op.hashes().items():
        if value != getattr(manifest.files, name):
            raise ExtractionFailure("operator_file_pin_mismatch", {"file": name}) if strict else Withheld(names[name])
    return [load_source(source, paths, manifest, pin, strict=strict) for pin in sorted(manifest.sources, key=lambda p: p.relation.job_id)]


# ---------------------------------------------------------------------------------------------- planning ---------------------------

class Skip(Exception):
    """One public item cannot be proven from source: it is excluded VISIBLY (id and code only), never fabricated, repaired or silently dropped."""

    def __init__(self, code: str, detail: dict | None = None):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass
class Member:
    loaded: Loaded
    kind: str           # event-candidate | snapshot-event
    ref: str
    mention_id: str
    mention: dict
    doc: tuple
    observation: dict
    evidence: list

    def source_event(self) -> dict:
        return {"upstream": {"jobId": self.loaded.upstream_key[0], "inputDigest": self.loaded.upstream_key[1]}, "kind": self.kind, "ref": self.ref,
                "mentionId": self.mention_id, "documentId": self.doc[0], "documentVersion": self.doc[1], "observation": self.observation}


def members_of(loaded: Loaded) -> list[Member]:
    found = []
    try:
        for c in loaded.s2["eventCandidates"]:
            if c["state"] != "candidate":
                continue
            mention = Mention.model_validate(c["mention"]).model_dump(mode="json")
            found.append(Member(loaded, "event-candidate", c["eventCandidateId"], mention["mention_id"], mention,
                                (c["document"]["documentId"], c["document"]["documentVersion"]), loaded.submit.incoming.wire(), list(c["citations"])))
        for event in loaded.submit.snapshot.events:
            for member in event.members:
                mention = Mention.model_validate(member.mention).model_dump(mode="json")
                doc = (member.observation.document_id, member.observation.document_version)
                found.append(Member(loaded, "snapshot-event", event.event_id, mention["mention_id"], mention, doc, member.observation.wire(),
                                    [{"documentId": doc[0], "documentVersion": doc[1], "start": e["start"], "end": e["end"], "quote": e["quote"]}
                                     for e in mention["evidence"]]))
    except (ValidationError, KeyError, TypeError, AttributeError):
        raise ExtractionFailure("s2_payload_invalid") from None
    return found


def article_metadata(export: dict) -> tuple:
    """(title, url, publication value, precision) of one exported observation.

    A collected export that declared only a calendar date keeps it as a `day` (the value is the `YYYY-MM-DD` date); it is never
    widened to an instant. An offset-less declared time stays `unknown` (the instant is not known; its declared form remains in the
    ingestion export). Authored exports and instants keep the earlier `datetime`/`unknown` rule."""
    observation = export["observation"]
    declared = (observation.get("collection") or {}).get("published")
    if declared is not None and declared["precision"] == "day":
        return observation["title"], observation["url"], declared["date"], "day"
    published = observation["publishedAt"]
    return observation["title"], observation["url"], published, "datetime" if published is not None else "unknown"


class Resolver:
    """Exact evidence for the bundle. Each citation is re-resolved NOW against the source text through the owner (`cite_exact`) and must equal what the
    source payload recorded. The app evidence id comes from the explicit app document binding only; a binding whose text digest is not the source text's
    is refused, so an arbitrarily mapped articleVersion can never be reported as verified."""

    def __init__(self, bindings: dict):
        self.bindings = bindings
        self.memo: dict = {}
        self.by_id: dict = {}
        self.docs: dict = {}      # (documentId, documentVersion) -> list[(ref, export)]

    def add(self, loaded: Loaded) -> None:
        for key, entries in loaded.docs.items():
            known = self.docs.setdefault(key, [])
            for entry in entries:
                metadata = article_metadata(entry[1])
                if any(article_metadata(other[1]) != metadata for other in known):
                    raise ExtractionFailure("article_metadata_conflict")
                if all(entry[0].wire() != other[0].wire() for other in known):
                    known.append(entry)

    def cite(self, loaded: Loaded, c: dict) -> str:
        key = (c["documentId"], c["documentVersion"])
        found = loaded.docs.get(key)
        if not found:
            raise ExtractionFailure("evidence_document_unbound")
        ref, export = found[0]
        binding = self.bindings.get(key)
        if binding is None:
            raise Skip("app_binding_missing")
        if binding.text_sha256 != text_sha256(export["document"]["text"]):
            raise Skip("app_binding_text_mismatch")
        memo_key = (*key, c["start"], c["end"])
        record = self.memo.get(memo_key)
        if record is None:
            try:
                exact = cite_exact(loaded.sources, ref, export, c["start"], c["end"], c["quote"])
            except CitationFailure as exc:
                raise ExtractionFailure("evidence_unresolvable", {"code": exc.code}) from None
            for name in ("evidenceId", "rawVersion", "textArtifactId", "rawLocatorIds"):
                if name in c and c[name] != exact[name]:
                    raise ExtractionFailure("evidence_source_mismatch")
            if exact["inputKind"] != "body":
                raise ExtractionFailure("evidence_input_kind_unsupported")
            record = {"id": app_evidence_id(binding.article_id, binding.article_version, c["start"], c["end"]), "kind": EVIDENCE_KIND,
                      "articleId": binding.article_id, "articleVersion": binding.article_version, "start": c["start"], "end": c["end"], "offsetUnit": OFFSET_UNIT,
                      "quoteSha256": text_sha256(c["quote"]), "rawLocatorIds": sorted(exact["rawLocatorIds"]),
                      "source": {"documentId": key[0], "documentVersion": key[1], "rawVersion": exact["rawVersion"], "textArtifactId": exact["textArtifactId"],
                                 "sourceEvidenceId": exact["evidenceId"], "inputKind": exact["inputKind"]}}
            self.memo[memo_key] = record
            self.by_id[record["id"]] = record
        return record["id"]

    def article(self, record: dict) -> dict:
        key = (record["source"]["documentId"], record["source"]["documentVersion"])
        entries = self.docs[key]
        meta = {article_metadata(e[1]) for e in entries}
        if len(meta) != 1:
            raise ExtractionFailure("article_metadata_conflict")
        title, url, published, precision = next(iter(meta))
        observations = sorted(({"roundId": o["roundId"], "sourceId": o["sourceId"], "page": o["page"], "ordinal": o["ordinal"], "observedAt": o["observedAt"],
                                "grant": {"grantId": e[1]["grant"]["grantId"], "revision": e[1]["grant"]["revision"]}}
                               for e in entries for o in (e[1]["observation"],)), key=canonical)
        return {"articleId": record["articleId"], "articleVersion": record["articleVersion"], "documentId": key[0], "documentVersion": key[1],
                "rawVersion": record["source"]["rawVersion"], "title": title, "url": url, "publishedAt": published,
                "publicationPrecision": precision, "observations": observations}


ISSUE_FIELDS = (("title", "title"), ("action", "action"), ("target", "target"), ("event_time", "eventTime"), ("period", "period"),
                ("assertion_status", "assertionStatus"))


class Planner:
    """The pure (given loaded sources and operator files) projection. Every S3/S2 item the operator intended to publish is either emitted or excluded
    with a visible code; nothing is guessed, merged by last-wins or inferred from company/ticker/exchange/language."""

    def __init__(self, manifest: Manifest, handoff_id: str, input_digest: str, loaded: list[Loaded], op: Operator):
        self.manifest, self.handoff_id, self.input_digest, self.op = manifest, handoff_id, input_digest, op
        self.loaded = sorted(loaded, key=lambda item: item.pin.relation.job_id)
        self.by_job = {item.pin.relation.job_id: item for item in self.loaded}
        self.by_upstream: dict = {}
        for item in self.loaded:
            self.by_upstream.setdefault(item.upstream_key, item)
        self.resolver = Resolver(op.bindings)
        for item in self.loaded:
            self.resolver.add(item)
        self.companies = {c.canonical_id: c for c in op.decisions.companies}
        self.exclusions: list[dict] = []
        self.issues: dict = {}            # public issue id -> issue dict
        self.info: dict = {}              # public issue id -> internal facts
        self.by_canonical: dict = {}      # canonical issue id -> public issue id
        self.involves: dict = {}          # (public issue, public company) -> accumulated INVOLVES
        self.involved: dict = {}          # public issue -> {canonical company -> public company}
        self.relations: list[dict] = []
        self.used_review: dict = {}       # (jobId, rc) -> revision of every S3 relation behind an emitted edge
        self.not_public: dict = {item.pin.relation.job_id: {} for item in self.loaded}

    # ---- helpers ------------------------------------------------------------------------------------------------------------------------

    def exclude(self, kind: str, ident: str, code: str, job: str | None = None, detail: dict | None = None) -> None:
        item = {"kind": kind, "id": ident, "jobId": job, "code": code}
        if detail:
            item["detail"] = detail
        self.exclusions.append(item)
        if len(self.exclusions) > MAX_EXCLUSIONS:
            raise ExtractionFailure("handoff_limit_exceeded", {"exclusions": "items"})

    def canon(self, loaded: Loaded, kind: str, ref: str) -> str:
        entry = self.op.registry.entries.get(entry_key(loaded.upstream_key[0], loaded.upstream_key[1], kind, ref))
        if entry is None:
            raise Skip("canonical_company_unmapped" if kind == "company" else "canonical_event_unmapped")
        return entry.canonical_id

    def cite(self, loaded: Loaded, c: dict) -> str:
        return self.resolver.cite(loaded, c)

    # ---- issues -------------------------------------------------------------------------------------------------------------------------

    def groups(self) -> dict:
        """canonical issue id -> members: only events the operator's canonical registry explicitly maps to that issue (never inferred, never SAME/topic)."""
        seen, groups = set(), {}
        for loaded in self.loaded:
            for member in members_of(loaded):
                identity = canonical(member.source_event())
                if identity in seen:
                    continue
                seen.add(identity)
                entry = self.op.registry.entries.get(entry_key(loaded.upstream_key[0], loaded.upstream_key[1], "event", member.ref))
                if entry is not None:
                    groups.setdefault(entry.canonical_id, []).append(member)
        return groups

    @staticmethod
    def fields(decision, members: list[Member]) -> dict:
        """Issue metadata. Members that disagree conflict unless the operator names ONE representative mention (an explicit canonical decision)."""
        rep = decision.representative
        if rep is not None:
            chosen = [m for m in members if m.loaded.upstream_key == (rep.upstream.job_id, rep.upstream.input_digest) and m.kind == rep.kind
                      and m.ref == rep.ref and m.mention_id == rep.mention_id and m.doc == (rep.document_id, rep.document_version)
                      and m.observation == rep.observation.wire()]
            if len(chosen) != 1:
                raise Skip("issue_representative_invalid")
            source = chosen[0].mention
        else:
            conflicts = [wire for key, wire in ISSUE_FIELDS if len({json.dumps(m.mention.get(key)) for m in members}) > 1]
            if conflicts:
                raise Skip("issue_metadata_conflict", {"fields": conflicts})
            source = members[0].mention
        return {wire: source.get(key) for key, wire in ISSUE_FIELDS}

    def geography(self, decision, members: list[Member]) -> dict:
        """Source-proven geography: the operator's country-field verdict must be well formed, class-consistent, pinned to exact text spans of this issue's
        own documents, and EQUAL to every member mention's country field. Disagreement, absent or unverified fields exclude the issue; nothing maps to
        international by default."""
        g = decision.geography
        countries = sorted(set(g.countries))
        shape = countries_class(countries)
        if shape == "invalid":
            raise Skip("geography_countries_invalid")
        if shape != g.classification:
            raise Skip("geography_decision_mismatch")
        basis = []
        for m in members:
            seen = sorted(set(m.mention.get("countries") or []))
            if not seen:
                raise Skip("geography_unproven")
            if seen != countries:
                raise Skip("geography_countries_disagree")
            basis.append({**{k: v for k, v in m.source_event().items()}, "countries": seen})
        evidence = []
        for span in g.evidence:
            member = next((m for m in members if m.doc == (span.document_id, span.document_version)), None)
            if member is None:
                raise Skip("geography_evidence_unbound")
            text = member.loaded.docs[member.doc][0][1]["document"]["text"]
            if not (0 <= span.start < span.end <= len(text)) or text_sha256(text[span.start:span.end]) != span.quote_sha256:
                raise Skip("geography_evidence_mismatch")
            evidence.append(self.cite(member.loaded, {"documentId": span.document_id, "documentVersion": span.document_version, "start": span.start,
                                                      "end": span.end, "quote": text[span.start:span.end]}))
        return {"value": g.classification, "decisionRef": g.decision_ref, "decisionVersion": g.decision_version, "policyVersion": POLICY, "countries": countries,
                "verification": "operator-field-verdict", "evidenceIds": sorted(set(evidence)),
                "basis": sorted(basis, key=canonical)}

    def issue(self, decision, members: list[Member]) -> tuple[dict, dict]:
        fields = self.fields(decision, members)
        if not isinstance(fields["title"], str) or not fields["title"].strip():
            raise Skip("issue_title_missing")
        try:
            precision = time_precision(fields["eventTime"])
        except ValueError:
            raise Skip("event_time_unsupported") from None
        geography = self.geography(decision, members)
        event_evidence = sorted({self.cite(m.loaded, c) for m in members for c in m.evidence})
        if not event_evidence:
            raise Skip("issue_evidence_missing")
        issue = {"id": decision.public_id, "canonicalId": decision.canonical_id, **fields, "timePrecision": precision, "geography": geography,
                 "evidenceIds": sorted(set(event_evidence) | set(geography["evidenceIds"])),
                 "sourceEvents": sorted({canonical(m.source_event()): m.source_event() for m in members}.values(), key=canonical),
                 "decisionRef": decision.decision_ref, "representative": decision.representative.wire() if decision.representative else None}
        return issue, {"decision": decision, "members": members, "eventEvidence": event_evidence}

    def build_issues(self) -> None:
        groups = self.groups()
        decided = {d.canonical_id for d in self.op.decisions.issues}
        for canonical_id in sorted(set(groups) - decided):
            self.exclude("issue", canonical_id, "issue_unreviewed")
        for decision in sorted(self.op.decisions.issues, key=lambda d: d.canonical_id):
            members = groups.get(decision.canonical_id)
            if not members:
                self.exclude("issue", decision.canonical_id, "issue_source_missing")
                continue
            try:
                issue, info = self.issue(decision, members)
            except Skip as skip:
                self.exclude("issue", decision.canonical_id, skip.code, detail=skip.detail)
                continue
            self.issues[issue["id"]] = issue
            self.info[issue["id"]] = info
            self.by_canonical[decision.canonical_id] = issue["id"]
        if len(self.issues) > MAX_ISSUES:
            raise ExtractionFailure("handoff_limit_exceeded", {"issues": "count"})

    # ---- INVOLVES (S3 PARTICIPATES_IN, direction reversed) -----------------------------------------------------------------------------

    def build_involves(self) -> None:
        for loaded in self.loaded:
            job = loaded.pin.relation.job_id
            for rc in sorted(loaded.relations):
                r = loaded.relations[rc]
                state = r["eligibility"]
                if state["status"] != "eligible" or state["reviewPending"]:
                    continue
                if r["type"] != "PARTICIPATES_IN":
                    self.not_public[job][r["type"]] = self.not_public[job].get(r["type"], 0) + 1
                    continue
                if r["direction"] != "directed" or r["connection"] != "direct" or r["subject"]["kind"] != "company" or r["object"]["kind"] != "event":
                    raise ExtractionFailure("relation_payload_invalid")
                try:
                    company_canonical = self.canon(loaded, "company", r["subject"]["ref"])
                    company = self.companies.get(company_canonical)
                    if company is None:
                        raise Skip("company_unmapped")
                    issue_id = self.by_canonical.get(self.canon(loaded, "event", r["object"]["ref"]))
                    if issue_id is None:
                        raise Skip("issue_not_public")
                    if any("error" in c for c in r["citations"]) or not r["citations"]:
                        raise ExtractionFailure("relation_payload_invalid")
                    evidence = sorted({self.cite(loaded, c) for c in r["citations"]})
                except Skip as skip:
                    self.exclude("relation", rc, skip.code, job)
                    continue
                edge = self.involves.setdefault((issue_id, company.public_id), {"evidence": set(), "refs": set(), "canonicalCompany": company_canonical})
                edge["evidence"].update(evidence)
                edge["refs"].add((job, rc))
                self.used_review[(job, rc)] = state["revision"]
        involved_issues = {issue_id for issue_id, _ in self.involves}
        for issue_id in sorted(set(self.issues) - involved_issues):
            self.exclude("issue", self.issues[issue_id]["canonicalId"], "issue_without_involvement")
            del self.issues[issue_id]
            del self.info[issue_id]
        self.by_canonical = {issue["canonicalId"]: issue_id for issue_id, issue in self.issues.items()}
        for (issue_id, company_id), edge in sorted(self.involves.items()):
            self.involved.setdefault(issue_id, {})[edge["canonicalCompany"]] = company_id
            self.relations.append({
                "id": "edge-" + digest({"type": "INVOLVES", "source": issue_id, "target": company_id}), "type": "INVOLVES", "source": issue_id, "target": company_id,
                "role": None, "assertionStatus": self.issues[issue_id]["assertionStatus"], "evidenceIds": sorted(edge["evidence"]), "basis": [],
                "provenance": {"origin": "s3-relation", "s3SemanticValidation": "independent-verifier-supported-all-claims"}, "decisionRef": None,
                "sourceRefs": [{"kind": "s3-relation", "jobId": j, "id": rc} for j, rc in sorted(edge["refs"])]})

    # ---- STRUCTURALLY_RELATED_TO (manual operator assertion over eligible S3 SUPPLIES basis) -------------------------------------------------

    def structural(self, decision) -> dict:
        issue_id = self.by_canonical.get(decision.issue)
        if issue_id is None:
            raise Skip("issue_not_public")
        company = self.companies.get(decision.company)
        if company is None:
            raise Skip("company_unmapped")
        involved = self.involved[issue_id]
        if decision.company in involved:
            raise Skip("structural_target_is_participant")
        issue, rows = self.issues[issue_id], []
        for ref in decision.basis:
            loaded = self.by_job.get(ref.job_id)
            r = loaded.relations.get(ref.relation_candidate_id) if loaded is not None else None
            if r is None:
                raise Skip("basis_relation_missing")
            if r["eligibility"]["status"] != "eligible" or r["eligibility"]["reviewPending"]:
                raise Skip("basis_relation_ineligible")
            if r["type"] not in STRUCTURAL_BASIS_TYPES:
                raise Skip("basis_type_unsupported")
            if r["connection"] != "direct" or r["subject"]["kind"] != "company" or r["object"]["kind"] != "company":
                raise Skip("basis_indirect_unsupported")
            rows.append((loaded, r, self.canon(loaded, "company", r["subject"]["ref"]), self.canon(loaded, "company", r["object"]["ref"])))
        if not self.connected(rows, set(involved), decision.company):
            raise Skip("basis_path_disconnected")
        when, countries = issue["eventTime"], set(issue["geography"]["countries"])
        for _, r, _, _ in rows:
            validity = r["validity"]
            if validity["from"] or validity["until"]:
                if not when or len(when) < 10:
                    raise Skip("basis_validity_unprovable")
                if (validity["from"] and when[:10] < validity["from"][:10]) or (validity["until"] and when[:10] > validity["until"][:10]):
                    raise Skip("basis_validity_outside_event_time")
            if r["countries"] and not countries <= set(r["countries"]):
                raise Skip("basis_countries_mismatch")
        a = decision.applicability
        expected = digest({"policy": POLICY, "issue": decision.issue, "company": decision.company, "decisionVersion": a.decision_version,
                           "eventTime": issue["eventTime"], "geography": issue["geography"]["value"], "sourceEvents": issue["sourceEvents"],
                           "basis": [{"jobId": ref.job_id, "relationCandidateId": ref.relation_candidate_id, "relationKey": r["relationKey"], "type": r["type"],
                                      "revision": r["eligibility"]["revision"]} for ref, (_, r, _, _) in zip(decision.basis, rows)]})
        if a.binding_digest != expected:
            raise Skip("applicability_binding_mismatch", {"expectedBindingDigest": expected})
        basis = []
        for ref, (loaded, r, _, _) in zip(decision.basis, rows):
            verdicts = [e for e in r["history"] if e["kind"] == "verdict" and e["eligibility"] == "eligible"]
            if not verdicts:
                raise Skip("basis_verification_missing")
            evidence = sorted({self.cite(loaded, c) for c in (*r["citations"], *r["validity"]["citations"])})
            articles = sorted({(self.resolver.by_id[i]["articleId"], self.resolver.by_id[i]["articleVersion"]) for i in evidence})
            basis.append({"sourceRelation": {"jobId": ref.job_id, "relationCandidateId": ref.relation_candidate_id},
                          "relationKey": r["relationKey"], "relationType": r["type"],
                          "validFrom": r["validity"]["from"], "validUntil": r["validity"]["until"], "countries": sorted(r["countries"]),
                          "verifiedAt": max(verdicts, key=lambda e: e["seq"])["createdAt"],
                          "sourceArticles": [{"articleId": x, "articleVersion": y} for x, y in articles], "evidenceIds": evidence})
        for ref, (_, r, _, _) in zip(decision.basis, rows):
            self.used_review[(ref.job_id, ref.relation_candidate_id)] = r["eligibility"]["revision"]
        return {"id": "edge-" + digest({"type": "STRUCTURALLY_RELATED_TO", "source": issue_id, "target": company.public_id,
                                         "basis": [r["relationKey"] for _, r, _, _ in rows]}),
                "type": "STRUCTURALLY_RELATED_TO", "source": issue_id, "target": company.public_id, "role": None, "assertionStatus": issue["assertionStatus"],
                "evidenceIds": sorted(self.info[issue_id]["eventEvidence"]), "basis": basis,
                "provenance": {"origin": "manual-operator-review", "s3SemanticValidation": "none", "status": a.status, "reviewer": a.reviewer,
                               "decisionRef": a.decision_ref, "decisionVersion": a.decision_version, "bindingDigest": a.binding_digest,
                               "basisEligibility": "s3-independent-verifier-supported-all-claims"},
                "decisionRef": a.decision_ref,
                "sourceRefs": [{"kind": "s3-relation", "jobId": ref.job_id, "id": ref.relation_candidate_id} for ref in decision.basis]}

    @staticmethod
    def connected(rows: list, participants: set, target: str) -> bool:
        """An undirected chain participant -> (middle ->) target over the ordered basis relations, no node repeated (path length <= 2)."""
        first = rows[0]
        for start, other in ((first[2], first[3]), (first[3], first[2])):
            if start not in participants or start == other:
                continue
            if len(rows) == 1:
                if other == target:
                    return True
                continue
            second = rows[1]
            if other in (second[2], second[3]):
                end = second[3] if other == second[2] else second[2]
                if end == target and len({start, other, end}) == 3:
                    return True
        return False

    # ---- FOLLOWS (S2 comparison effective FOLLOWS + operator sequence decision) -------------------------------------------------------------

    def follows(self, decision, edges: dict) -> dict:
        s = decision.source
        loaded = self.by_upstream.get((s.upstream.job_id, s.upstream.input_digest))
        if loaded is None:
            raise Skip("follows_source_unpinned")
        candidate = next((c for c in loaded.s2["eventCandidates"] if c["eventCandidateId"] == s.event_candidate_id and c["state"] == "candidate"), None)
        comparison = next((c for c in candidate["comparisons"] if c["targetEventId"] == s.target_event_id), None) if candidate else None
        if comparison is None:
            raise Skip("follows_source_missing")
        if comparison["effective"]["relation"] != "FOLLOWS":
            raise Skip("follows_source_not_follows")
        if comparison["groupDigest"] != s.group_digest:
            raise Skip("follows_group_changed")
        if not comparison["citations"]:
            raise Skip("follows_evidence_missing")
        later = self.canon(loaded, "event", s.event_candidate_id)
        prior = self.canon(loaded, "event", s.target_event_id)
        if (later, prior) != (decision.from_, decision.to):
            raise Skip("follows_canonical_mismatch")
        if later == prior:
            raise Skip("follows_self")
        source, target = self.by_canonical.get(later), self.by_canonical.get(prior)
        if source is None or target is None:
            raise Skip("issue_not_public")
        seen, frontier = set(), [target]
        while frontier:
            node = frontier.pop()
            if node == source:
                raise Skip("follows_cycle")
            if node not in seen:
                seen.add(node)
                frontier.extend(edges.get(node, ()))
        edges.setdefault(source, set()).add(target)
        evidence = sorted({self.cite(loaded, c) for c in comparison["citations"]})
        return {"id": "edge-" + digest({"type": "FOLLOWS", "source": source, "target": target}), "type": "FOLLOWS", "source": source, "target": target, "role": None,
                "assertionStatus": None, "evidenceIds": evidence, "basis": [],
                "provenance": {"origin": "s2-comparison-with-operator-decision", "s3SemanticValidation": "none", "s2Relation": "FOLLOWS",
                               "evidenceGate": "exact-source-citation-in-incoming-article", "groupDigest": s.group_digest,
                               "decisionRef": decision.decision_ref, "decisionVersion": decision.decision_version},
                "decisionRef": decision.decision_ref,
                "sourceRefs": [{"kind": "s2-comparison", "jobId": s.upstream.job_id, "id": f"{s.event_candidate_id}>{s.target_event_id}"}]}

    # ---- assembly -------------------------------------------------------------------------------------------------------------------------

    def run(self) -> dict:
        self.build_issues()
        self.build_involves()
        for decision in sorted(self.op.decisions.structural, key=lambda d: (d.issue, d.company)):
            try:
                self.relations.append(self.structural(decision))
            except Skip as skip:
                self.exclude("structural", f"{decision.issue}>{decision.company}", skip.code, detail=skip.detail)
        edges: dict = {}
        for decision in sorted(self.op.decisions.follows, key=lambda d: (d.from_, d.to)):
            try:
                self.relations.append(self.follows(decision, edges))
            except Skip as skip:
                self.exclude("follows", f"{decision.from_}>{decision.to}", skip.code, detail=skip.detail)
        relations = sorted(self.relations, key=lambda r: (r["type"], r["id"]))
        if len(relations) > MAX_RELATIONS:
            raise ExtractionFailure("handoff_limit_exceeded", {"relations": "count"})
        evidence_ids = {i for issue in self.issues.values() for i in issue["evidenceIds"]}
        for r in relations:
            evidence_ids.update(r["evidenceIds"])
            for b in r["basis"]:
                evidence_ids.update(b["evidenceIds"])
        if len(evidence_ids) > MAX_EVIDENCE:
            raise ExtractionFailure("handoff_limit_exceeded", {"evidence": "count"})
        evidence = [self.resolver.by_id[i] for i in sorted(evidence_ids)]
        articles = sorted({(e["articleId"], e["articleVersion"]): self.resolver.article(e) for e in evidence}.values(), key=lambda a: (a["articleId"], a["articleVersion"]))
        companies = sorted(({"id": c.public_id, "canonicalId": c.canonical_id, "label": c.label, "decisionRef": c.decision_ref} for c in self.companies.values()
                            if any(r["target"] == c.public_id for r in relations if r["type"] != "FOLLOWS")), key=lambda c: c["id"])
        issues = [self.issues[i] for i in sorted(self.issues)]
        tally: dict[str, int] = {}
        for item in self.exclusions:
            tally[item["code"]] = tally.get(item["code"], 0) + 1
        items = sorted(self.exclusions, key=canonical)
        sources = []
        for loaded in self.loaded:
            counts = loaded.s3["counts"]
            job = loaded.pin.relation.job_id
            sources.append({"relation": loaded.pin.relation.wire(), "upstream": loaded.pin.upstream.wire(), "reviewDigest": digest(review_state(loaded.s3)),
                            "policies": loaded.s3["binding"]["versions"],
                            "reviewUsed": sorted([rc, revision] for (j, rc), revision in self.used_review.items() if j == job),
                            "audit": {"s3Relations": len(loaded.relations), "eligibility": {k: counts["eligibility"][k] for k in ("eligible", "hold", "reject", "pending")},
                                      "reviewPending": sum(bool(r["eligibility"]["reviewPending"]) for r in loaded.relations.values()),
                                      "impactCandidates": counts["impactCandidates"], "eligibleNotPublicByType": dict(sorted(self.not_public[job].items()))}})
        observed = {item.s3["provenance"]["sourceKind"] for item in self.loaded}
        first = self.loaded[0].s3["provenance"]
        bundle = {"schemaVersion": BUNDLE_SCHEMA, "handoffId": self.handoff_id, "manifestDigest": self.input_digest,
                  "provenance": {"declaredSourceKind": self.manifest.source_kind, "observedSourceKind": next(iter(observed)) if len(observed) == 1 else "mixed",
                                 "executionMode": first["executionMode"], "recordingKind": first["recordingKind"]},
                  "policy": {"version": POLICY, "files": self.manifest.files.wire(), "evidenceIdKind": EVIDENCE_KIND, "offsetUnit": OFFSET_UNIT, **POLICIES},
                  "sources": sources, "companies": companies, "issues": issues, "relations": relations, "evidence": evidence, "articles": articles,
                  "exclusions": {"counts": dict(sorted(tally.items())), "items": items},
                  "counts": {"companies": len(companies), "issues": len(issues), "relations": {t: sum(r["type"] == t for r in relations) for t in
                                                                                         ("INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS")},
                             "evidence": len(evidence), "articles": len(articles), "exclusions": len(items)},
                  "checks": {"producerConfirmed": list(PRODUCER_CHECKS), "appImportPending": list(APP_IMPORT_PENDING)},
                  "readiness": {"app": "import-pending", "evidenceRegistration": "not-registered", "publicActivation": "none", "graphDb": "none"},
                  "digests": {"content": ""}}
        bundle["digests"]["content"] = content_digest(bundle)
        return bundle


# ---------------------------------------------------------------------------------------------- the engine -------------------------

def receipt_of(manifest: Manifest, input_digest: str, bundle: dict, bundle_digest: str, size: int) -> dict:
    """Bound to the handoff ID, manifest digest and source revisions; lists only what the producer actually confirmed. No public/graph status."""
    return {"handoffId": manifest.handoff_id, "manifestDigest": input_digest, "bundleSchema": BUNDLE_SCHEMA, "bundleDigest": bundle_digest,
            "contentDigest": bundle["digests"]["content"], "bundleBytes": size, "provenance": bundle["provenance"],
            "sources": [{"relation": s["relation"], "upstream": s["upstream"], "reviewDigest": s["reviewDigest"]} for s in bundle["sources"]],
            "files": manifest.files.wire(), "counts": bundle["counts"], "exclusionCodes": bundle["exclusions"]["counts"], "checks": bundle["checks"],
            "frozenAt": now()}


def withheld_result(row, code: str) -> dict:
    """Nothing but identity, state and reason: no bundle, counts, exclusions, ids, scopes, titles or URLs of a handoff that is not currently deliverable."""
    return {"schemaVersion": SCHEMA, "handoffId": row["handoff_id"], "state": row["state"], "publication": "not-published",
            "delivery": {"status": "withheld", "code": code}, "usage": USAGE}


class Handoff:
    def __init__(self, store: Store, paths: HandoffPaths | None = None):
        self.store, self.paths = store, paths

    # seams for process-level crash tests (no production effect)
    def _after_reserve(self) -> None:
        """Called once the handoff is durably `reserved` and before the artifact is written."""

    def _after_artifact(self) -> None:
        """Called once the artifact is durable and before the ledger marks the handoff `ready`."""

    def _existing(self, handoff_id: str):
        row = self.store.handoff(handoff_id)
        if row is None:
            raise ExtractionFailure("handoff_not_found")
        return row

    def result(self, row) -> dict:
        failure = {"code": row["failure"]} if row["failure"] else None
        return {"schemaVersion": SCHEMA, "handoffId": row["handoff_id"], "state": row["state"], "publication": "not-published", "next": NEXT[row["state"]],
                "failure": failure, "receipt": json.loads(row["receipt"]),
                "attempts": [{"n": a["n"], "kind": a["kind"], "outcome": a["outcome"], "code": a["code"]} for a in self.store.attempts(row["handoff_id"])],
                "usage": USAGE}

    def freeze(self, manifest: Manifest) -> dict:
        """Pin, build, validate, reserve, write the artifact, settle. A handoff that already exists is never changed: the same request is echoed ONLY while
        every pinned source and file is still current, a different request is `handoff_input_conflict` with nothing written."""
        paths, input_digest = self.paths, digest(manifest.wire())
        op = load_operator(paths)
        with Source(paths.source()) as source:
            row = self.store.handoff(manifest.handoff_id)
            if row is not None:
                if row["input_digest"] != input_digest:
                    raise ExtractionFailure("handoff_input_conflict")
                if row["state"] != "failed":
                    current(source, paths, manifest, op, strict=True)
                return self.result(row)
            loaded = current(source, paths, manifest, op, strict=True)
            bundle = Planner(manifest, manifest.handoff_id, input_digest, loaded, op).run()
            validate_bundle(bundle)
            raw = canonical(bundle).encode("utf-8")
            if len(raw) > MAX_BUNDLE:
                raise ExtractionFailure("handoff_limit_exceeded", {"bundle": "bytes"})
            bundle_digest = byte_hash(raw)
            receipt = receipt_of(manifest, input_digest, bundle, bundle_digest, len(raw))

            def guard() -> None:
                current(source, paths, manifest, op, strict=True)
                operator_unchanged(op, paths)

            with self.store.transaction(guard):
                self.store.db.execute("INSERT INTO handoffs(handoff_id,input_digest,manifest,bundle_digest,content_digest,bundle_bytes,receipt,state,created_at,updated_at) "
                                      "VALUES(?,?,?,?,?,?,?,'reserved',?,?)",
                                      (manifest.handoff_id, input_digest, canonical(manifest.wire()), bundle_digest, bundle["digests"]["content"], len(raw),
                                       canonical(receipt), now(), now()))
        self._after_reserve()
        write_artifact(self.store.root, raw, bundle_digest)
        self._after_artifact()
        self.store.settle(manifest.handoff_id, "freeze", "ready", "written")
        return self.result(self._existing(manifest.handoff_id))

    def inspect(self, request: Selector) -> dict:
        row = self._existing(request.handoff_id)
        if row["state"] == "ready":
            read_manifest(row, read_bundle(self.store.root, row))
        return self.result(row)

    def recover(self, request: Selector) -> dict:
        """Settle a `reserved` handoff from the stored artifact ONLY: no source is read, nothing is regenerated and no new ID or bundle is minted. A missing
        or altered artifact makes this handoff `failed` (terminal); the operator freezes a NEW handoff ID."""
        row = self._existing(request.handoff_id)
        if row["state"] != "reserved":
            raise ExtractionFailure("recovery_not_required", {"state": row["state"]})
        try:
            read_bundle(self.store.root, row)
        except ExtractionFailure as exc:
            outcome = "artifact-missing" if exc.code == "handoff_artifact_missing" else "artifact-invalid"
            self.store.settle(row["handoff_id"], "recover", "failed", outcome, exc.code)
        else:
            self.store.settle(row["handoff_id"], "recover", "ready", "confirmed")
        return self.result(self._existing(request.handoff_id))

    def export(self, request: Selector, *, serialized: bool = False) -> dict | tuple[dict, str]:
        """The bundle, only after the artifact verifies AND every pinned authority is current NOW: operator files byte-identical to the manifest, every S3
        job ready/delivered/bound to its upstream pin (grants, rights, candidate set), the used relations' review revisions unchanged and the rebuilt
        content digest equal. Any drift is a `withheld` result with no content; a busy writer is an error, never an empty bundle."""
        paths = self.paths
        row = self._existing(request.handoff_id)
        if row["state"] != "ready":
            raise ExtractionFailure("handoff_not_ready", {"state": row["state"]})
        bundle = read_bundle(self.store.root, row)
        manifest, manifest_wire = read_manifest(row, bundle)
        try:
            try:
                op = load_operator(paths)
            except ExtractionFailure as exc:
                if exc.code in {"canonical_registry_invalid", "decisions_invalid", "bindings_invalid"}:
                    raise Withheld(exc.code) from None
                raise
            with Source(paths.source()) as source:
                loaded = current(source, paths, manifest, op, strict=False)
                self.used_reviews(loaded, bundle)
                fresh = Planner(manifest, manifest.handoff_id, row["input_digest"], loaded, op).run()
                if fresh["digests"]["content"] != bundle["digests"]["content"]:
                    raise Withheld("handoff_content_changed")
                review_matches = all(digest(review_state(item.s3)) == item.pin.review_digest for item in loaded)
                # Recheck every constituent while the S3 lock is held, immediately before assembling output.
                for pin in sorted(manifest.sources, key=lambda p: p.relation.job_id):
                    load_source(source, paths, manifest, pin, strict=False)
                for name, path in (("canonical", paths.canonical), ("decisions", paths.decisions), ("bindings", paths.bindings)):
                    try:
                        actual = byte_hash(read_file(path, MAX_REGISTRY if name == "canonical" else MAX_OPERATOR_FILE))
                    except (IngestionFailure, OSError):
                        raise Withheld({"canonical": "canonical_mapping_changed", "decisions": "decisions_changed", "bindings": "bindings_changed"}[name]) from None
                    if actual != getattr(manifest.files, name):
                        raise Withheld({"canonical": "canonical_mapping_changed", "decisions": "decisions_changed", "bindings": "bindings_changed"}[name])
                out = self.result(row)
                out["delivery"] = {"status": "current", "checkedAt": now(), "reviewDigestMatches": review_matches,
                                   "checks": ["operator_files_equal_manifest_pins", "s3_authority_and_s2_upstream_pin_current", "used_review_revisions_unchanged",
                                              "content_digest_rebuilt_equal"]}
                out["manifest"] = manifest_wire
                out["bundle"] = bundle
                return (out, canonical(out)) if serialized else out
        except Withheld as exc:
            out = withheld_result(row, exc.code)
            return (out, canonical(out)) if serialized else out

    @staticmethod
    def used_reviews(loaded: list[Loaded], bundle: dict) -> None:
        """Every S3 relation behind an emitted edge is still eligible, not review-pending and at the revision the bundle was built from."""
        by_job = {item.pin.relation.job_id: item for item in loaded}
        for source in bundle["sources"]:
            item = by_job.get(source["relation"]["jobId"])
            if item is None:
                raise Withheld("source_pin_missing")
            for rc, revision in source["reviewUsed"]:
                state = item.relations.get(rc, {}).get("eligibility")
                if state is None or state["status"] != "eligible" or state["reviewPending"] or state["revision"] != revision:
                    raise Withheld("review_revision_changed")
