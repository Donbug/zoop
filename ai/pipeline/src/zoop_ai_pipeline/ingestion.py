"""Independent offline ingestion ledger; no application, S1 or PoC state imports."""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from . import ingestion_parsers as parsers
from .ingestion_contracts import (SCHEMA, reserved_state_roots, MAX_INPUT, Authority, Export, IngestionFailure, Inspect, Item,
    Manifest, Receipt, Registry, Run, byte_hash, canonical, digest, now, read_file, timestamp)

PROVENANCE = {"authored-files": "authored_control", "collected-http": "collected_http"}

_SQL = """
CREATE TABLE IF NOT EXISTS blobs(hash TEXT PRIMARY KEY, data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS scopes(source TEXT, scope TEXT, config TEXT NOT NULL, revision INTEGER NOT NULL,
 cursor TEXT, through_time TEXT, PRIMARY KEY(source,scope));
CREATE TABLE IF NOT EXISTS rounds(id TEXT, source TEXT, input_digest TEXT NOT NULL, request TEXT NOT NULL,
 config TEXT NOT NULL, manifest TEXT NOT NULL, parser TEXT NOT NULL, expected_revision INTEGER NOT NULL,
 next_page INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'running', phase TEXT NOT NULL DEFAULT 'registered',
 failure TEXT, completion TEXT, registry_hash TEXT NOT NULL, PRIMARY KEY(id,source));
CREATE TABLE IF NOT EXISTS pages(round TEXT, source TEXT, ordinal INTEGER, page_id TEXT NOT NULL,
 raw_hash TEXT NOT NULL REFERENCES blobs(hash), status TEXT NOT NULL, observed_at TEXT NOT NULL,
 complete INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(round,source,ordinal),
 FOREIGN KEY(round,source) REFERENCES rounds(id,source));
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, source TEXT NOT NULL, supplier TEXT);
CREATE TABLE IF NOT EXISTS supplier_aliases(source TEXT, supplier TEXT, document TEXT REFERENCES documents(id),
 PRIMARY KEY(source,supplier));
CREATE TABLE IF NOT EXISTS url_aliases(source TEXT, url TEXT, document TEXT REFERENCES documents(id),
 PRIMARY KEY(source,url,document));
CREATE TABLE IF NOT EXISTS raw_versions(id TEXT PRIMARY KEY, document TEXT NOT NULL REFERENCES documents(id),
 raw_hash TEXT NOT NULL REFERENCES blobs(hash), metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS preparations(key TEXT PRIMARY KEY, raw_version TEXT REFERENCES raw_versions(id),
 version TEXT, hold TEXT, content TEXT);
CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, document TEXT NOT NULL REFERENCES documents(id),
 raw_version TEXT NOT NULL REFERENCES raw_versions(id), content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates(round TEXT, source TEXT, page INTEGER, ordinal INTEGER,
 data TEXT NOT NULL, document TEXT REFERENCES documents(id), raw_version TEXT REFERENCES raw_versions(id),
 version TEXT REFERENCES versions(id), hold TEXT, error TEXT, ambiguity TEXT, failure TEXT,
 new_raw INTEGER NOT NULL DEFAULT 0, new_text INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(round,source,page,ordinal), FOREIGN KEY(round,source,page) REFERENCES pages(round,source,ordinal));
"""


class Store:
    def __init__(self, root: Path, *, existing: bool = False):
        # Explicit dedicated namespace, not merely another filename in app/S1 state.
        root = Path(os.path.abspath(root))
        forbidden = reserved_state_roots()
        if any(root == p or root.is_relative_to(p) or p.is_relative_to(root) for p in forbidden):
            raise IngestionFailure("state_namespace_conflict")
        for parent in [*reversed(root.parents), root]:
            if parent.exists() and parent.is_symlink():
                raise IngestionFailure("state_namespace_invalid")
        if existing:
            self._open_existing(root)
            return
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if any(p.name not in {"ingestion.sqlite3", "ingestion.sqlite3-wal", "ingestion.sqlite3-shm", "ingestion.lock"} or p.is_symlink() for p in root.iterdir()):
            raise IngestionFailure("state_namespace_conflict")
        os.chmod(root, 0o700)
        self.lock = os.open(root / "ingestion.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(self.lock, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self.lock)
            raise IngestionFailure("ingestion_busy") from exc
        db = root / "ingestion.sqlite3"
        fd = os.open(db, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        try:
            self.db = sqlite3.connect(db, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(_SQL)
            for table in ("blobs", "raw_versions", "versions", "preparations", "pages"):
                # Pages only allow completion metadata to change, not saved receipts.
                if table != "pages":
                    self.db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END")
            self.db.execute("""CREATE TRIGGER IF NOT EXISTS immutable_page_receipt BEFORE UPDATE OF raw_hash,status,observed_at,page_id ON pages BEGIN SELECT RAISE(ABORT,'immutable'); END""")
            for p in root.iterdir():
                os.chmod(p, 0o600)
        except BaseException:
            self.close()
            raise

    def _open_existing(self, root: Path):
        """Read-only consumer access: no mkdir/chmod/ownership repair, no create, no schema/WAL/PRAGMA writes.

        Lock policy: a shared non-blocking flock on the existing lock file. Readers coexist; an active writer (exclusive) makes
        the reader fail with ingestion_busy and a reader makes a starting writer fail with ingestion_busy, so the file cannot change under
        an immutable read. A non-empty -wal means committed data a reader must not ignore or recover (that needs a write), so the
        operator runs the ingestion writer (resume) first.
        """
        database, lock = root / "ingestion.sqlite3", root / "ingestion.lock"
        if not root.is_dir() or not database.is_file() or not lock.is_file():
            raise IngestionFailure("ingestion_state_missing")
        if any(p.name not in {"ingestion.sqlite3", "ingestion.sqlite3-wal", "ingestion.sqlite3-shm", "ingestion.lock"} or p.is_symlink() for p in root.iterdir()):
            raise IngestionFailure("state_namespace_conflict")
        self.lock = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.close()
            raise IngestionFailure("ingestion_busy") from exc
        try:
            wal = root / "ingestion.sqlite3-wal"
            if wal.exists() and wal.stat().st_size > 0:
                raise IngestionFailure("ingestion_recovery_required")
            self.db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA query_only=ON")
            self.db.execute("SELECT 1 FROM rounds LIMIT 1")
        except sqlite3.DatabaseError as exc:
            self.close()
            raise IngestionFailure("ingestion_state_invalid") from exc
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

    def blob(self, raw):
        key = byte_hash(raw)
        self.db.execute("INSERT OR IGNORE INTO blobs VALUES(?,?)", (key, raw))
        return key


class Ingestor:
    def __init__(self, store: Store, authority: Authority):
        self.store, self.authority = store, authority
        self.db = store.db

    def _round(self, rid, source):
        row = self.store.one("SELECT * FROM rounds WHERE id=? AND source=?", (rid, source))
        if row is None:
            raise IngestionFailure("round_not_found")
        return row

    def _authorize(self, row, operations=("read", "store")):
        request = Run.model_validate_json(row["request"])
        return self.authority.check(row["source"], request.scope_id, operations, json.loads(row["config"]))

    def authorize_round(self, rid, source, operations):
        """Read-only: the saved round's source, scope and frozen configuration against the CURRENT registry for `operations`, before anything of the
        round is read. Returns the saved `(scopeId, config)` a later `Authority.check` re-verifies. `round_not_found` precedes authorization,
        exactly as for export/inspect; nothing is written."""
        row = self._round(rid, source)
        self._authorize(row, operations)
        return Run.model_validate_json(row["request"]).scope_id, json.loads(row["config"])

    def run(self, request: Run, manifest_path: Path):
        source, scope = self.authority.check(request.source_id, request.scope_id)
        raw = read_file(manifest_path, MAX_INPUT)
        if byte_hash(raw) != request.fixture_manifest_hash:
            raise IngestionFailure("fixture_manifest_hash_mismatch")
        manifest = Manifest.model_validate_json(raw)
        if (manifest.source_id, manifest.scope_id) != (request.source_id, request.scope_id) or manifest.pages[0].cursor != scope.initial_cursor:
            raise IngestionFailure("fixture_scope_conflict")
        # Validate all relative refs before any manifest-issued file access.
        config, parser = source.configuration(scope), parsers.profile(scope.article_xpath)
        input_digest = digest({"request": request.wire(), "configuration": config, "parser": parser})
        existing = self.store.one("SELECT * FROM rounds WHERE id=? AND source=?", (request.round_id, request.source_id))
        if existing and existing["input_digest"] != input_digest:
            raise IngestionFailure("round_input_conflict")
        self.authority.check(request.source_id, request.scope_id, config=config)
        if not existing:
            with self.store.transaction(lambda: self.authority.check(request.source_id, request.scope_id, config=config)):
                checkpoint = self.store.one("SELECT * FROM scopes WHERE source=? AND scope=?", (request.source_id, request.scope_id))
                if checkpoint and checkpoint["config"] != canonical(config):
                    raise IngestionFailure("scope_configuration_conflict")
                self.db.execute("INSERT OR IGNORE INTO scopes VALUES(?,?,?,0,?,NULL)", (request.source_id, request.scope_id, canonical(config), scope.initial_cursor))
                self.store.blob(raw)
                self.store.blob(self.authority.raw)
                self.db.execute("INSERT INTO rounds(id,source,input_digest,request,config,manifest,parser,expected_revision,registry_hash) VALUES(?,?,?,?,?,?,?,?,?)",
                    (request.round_id, request.source_id, input_digest, canonical(request.wire()), canonical(config), canonical(manifest.wire()), canonical(parser), request.checkpoint_revision, byte_hash(self.authority.raw)))
        return self.resume(request.round_id, request.source_id)

    def _identity(self, source, supplier, url, observation):
        supplier_match = self.store.one("SELECT document FROM supplier_aliases WHERE source=? AND supplier=?", (source, supplier)) if supplier else None
        aliases = self.db.execute("SELECT d.* FROM documents d JOIN url_aliases a ON d.id=a.document WHERE a.source=? AND a.url=? ORDER BY d.id", (source, url)).fetchall()
        ambiguity = None
        if supplier_match:
            document = supplier_match["document"]
        elif supplier and len(aliases) == 1 and aliases[0]["supplier"] in (None, supplier):
            document = aliases[0]["id"]
            self.db.execute("UPDATE documents SET supplier=? WHERE id=?", (supplier, document))
        elif not supplier and len(aliases) == 1:
            document = aliases[0]["id"]
        else:
            if aliases:
                ambiguity = "source_identity_ambiguous"
            # Do not guess a supplier when a reused URL has competing identities.
            document = "doc-" + digest([source, "ambiguous-url", url, observation] if not supplier and aliases else [source, "supplier" if supplier else "url", supplier or url])
        self.db.execute("INSERT OR IGNORE INTO documents VALUES(?,?,?)", (document, source, supplier))
        if supplier:
            self.db.execute("INSERT OR IGNORE INTO supplier_aliases VALUES(?,?,?)", (source, supplier, document))
        if aliases and any(a["id"] != document for a in aliases):
            ambiguity = "source_identity_ambiguous"
        if supplier or len(aliases) < 2:
            self.db.execute("INSERT OR IGNORE INTO url_aliases VALUES(?,?,?)", (source, url, document))
        return document, ambiguity

    def _receive_page(self, row, ordinal, page, source):
        saved = self.store.one("SELECT * FROM pages WHERE round=? AND source=? AND ordinal=?", (row["id"], row["source"], ordinal))
        if saved:
            return saved
        self._authorize(row)
        raw = self.authority.fixture(source, page.response, MAX_INPUT)
        self._authorize(row)
        with self.store.transaction(lambda: self._authorize(row)):
            raw_hash = self.store.blob(raw)
            self.db.execute("INSERT INTO pages(round,source,ordinal,page_id,raw_hash,status,observed_at) VALUES(?,?,?,?,?,?,?)", (row["id"], row["source"], ordinal, page.page_id, raw_hash, page.status, now()))
        return self.store.one("SELECT * FROM pages WHERE round=? AND source=? AND ordinal=?", (row["id"], row["source"], ordinal))

    def _discover(self, row, page, saved):
        raw = self.store.one("SELECT data FROM blobs WHERE hash=?", (saved["raw_hash"],))["data"]
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or set(payload) != {"items", "more", "nextCursor"} or not isinstance(payload["items"], list) or type(payload["more"]) is not bool or payload["more"] != (not page.terminal) or payload["nextCursor"] != page.next_cursor or len(payload["items"]) > 1000:
                raise IngestionFailure("discovery_response_invalid")
        except (ValueError, UnicodeError) as exc:
            raise IngestionFailure("discovery_response_invalid") from exc
        source, _ = self._authorize(row)
        candidate_ids = set()
        for ordinal, data in enumerate(payload["items"]):
            key = (row["id"], row["source"], saved["ordinal"], ordinal)
            error = None
            try:
                item = Item.model_validate(data)
                parsers.normalize_url(item.url, source.allowed_hosts)
                if (item.collection is not None) != (source.adapter == "collected-http"):
                    # Collected records need a recorded acquisition; authored fixtures can never claim one.
                    raise IngestionFailure("collection_provenance_conflict")
                if item.candidate_id in candidate_ids:
                    raise IngestionFailure("candidate_identity_duplicate")
                candidate_ids.add(item.candidate_id)
            except (ValidationError, IngestionFailure):
                error = "discovery_item_invalid"
            if self.store.one("SELECT 1 FROM candidates WHERE round=? AND source=? AND page=? AND ordinal=?", key):
                continue
            self._authorize(row)
            with self.store.transaction(lambda: self._authorize(row)):
                self.db.execute("INSERT INTO candidates(round,source,page,ordinal,data,error) VALUES(?,?,?,?,?,?)", (*key, canonical(data), error))

    def _receipt(self, row, source, item, ref, url) -> bytes:
        """The hash-pinned acquisition record behind a collected item, bound to this exact source, scope, candidate and grant revision.

        An unsigned operator-local file can still be forged by whoever controls the input namespace; this check proves the record
        is internally consistent with the bytes and the registry, not that a network fetch happened."""
        collected = item.collection
        saved = self.store.one("SELECT data FROM blobs WHERE hash=?", (collected.receipt.sha256,))
        raw = saved["data"] if saved is not None else self.authority.fixture(source, collected.receipt, MAX_INPUT)
        try:
            receipt = Receipt.model_validate_json(raw)
        except ValidationError as exc:
            raise IngestionFailure("collection_receipt_invalid") from exc
        grant, scope_id = source.grant, Run.model_validate_json(row["request"]).scope_id
        bound = ((receipt.collection_id, receipt.source_id, receipt.scope_id, receipt.candidate_id, receipt.grant_id, receipt.grant_revision, receipt.requested_url),
                 (collected.collection_id, row["source"], scope_id, item.candidate_id, grant.grant_id, grant.revision, url))
        observed = ((receipt.final_url, receipt.fetched_at, receipt.http_status, receipt.content_type, receipt.media_type, receipt.body_sha256, receipt.network),
                    (collected.final_url, collected.fetched_at, collected.http_status, collected.content_type, item.media_type, collected.body_sha256, collected.network))
        if byte_hash(raw) != collected.receipt.sha256 or bound[0] != bound[1] or observed[0] != observed[1] or ref.sha256 != collected.body_sha256:
            raise IngestionFailure("collection_receipt_invalid")
        return raw

    def _candidate(self, row, candidate, source, scope, manifest):
        key = (row["id"], row["source"], candidate["page"], candidate["ordinal"])
        if candidate["error"]:
            raise IngestionFailure(candidate["error"])
        if candidate["hold"] or candidate["version"]:
            return
        item = Item.model_validate_json(candidate["data"])
        url = parsers.normalize_url(item.url, source.allowed_hosts)
        raw_version = candidate["raw_version"]
        if not raw_version:
            ref = manifest.documents.get(item.body_ref)
            if ref is None:
                raise IngestionFailure("document_response_missing")
            self._authorize(row)
            # Reuse only document bytes already durably acquired in this exact
            # authorized source/round slice, never an unrelated global BLOB.
            saved = self.store.one("""SELECT b.data FROM candidates c JOIN raw_versions r ON r.id=c.raw_version
                JOIN blobs b ON b.hash=r.raw_hash WHERE c.round=? AND c.source=? AND r.raw_hash=? LIMIT 1""",
                (row["id"], row["source"], ref.sha256))
            receipt = self._receipt(row, source, item, ref, url) if item.collection is not None else None
            raw = saved["data"] if saved is not None else self.authority.fixture(source, ref)
            if byte_hash(raw) != ref.sha256:
                raise IngestionFailure("saved_response_hash_mismatch")
            self._authorize(row)
            with self.store.transaction(lambda: self._authorize(row)):
                document, ambiguity = self._identity(row["source"], item.supplier_document_id, url, key)
                raw_hash = self.store.blob(raw)
                if receipt is not None:
                    self.store.blob(receipt)
                raw_version = digest([document, raw_hash, item.metadata()])
                new_raw = self.store.one("SELECT 1 FROM raw_versions WHERE id=?", (raw_version,)) is None
                self.db.execute("INSERT OR IGNORE INTO raw_versions VALUES(?,?,?,?)", (raw_version, document, raw_hash, canonical(item.metadata())))
                self.db.execute("UPDATE candidates SET document=?,raw_version=?,ambiguity=?,new_raw=? WHERE round=? AND source=? AND page=? AND ordinal=?", (document, raw_version, ambiguity, int(new_raw), *key))
        raw_record = self.store.one("SELECT * FROM raw_versions WHERE id=?", (raw_version,))
        if json.loads(row["parser"]) != parsers.profile(scope.article_xpath):
            raise IngestionFailure("parser_profile_changed")
        preparation_key = digest([raw_version, json.loads(row["parser"]), json.loads(row["request"])["cleanerVersion"]])
        prior = self.store.one("SELECT * FROM preparations WHERE key=?", (preparation_key,))
        self._authorize(row)
        if prior:
            with self.store.transaction(lambda: self._authorize(row)):
                self.db.execute("UPDATE candidates SET version=?,hold=?,failure=NULL WHERE round=? AND source=? AND page=? AND ordinal=?", (prior["version"], prior["hold"], *key))
            return
        raw = self.store.one("SELECT data FROM blobs WHERE hash=?", (raw_record["raw_hash"],))["data"]
        try:
            current = self.store.one("SELECT ambiguity FROM candidates WHERE round=? AND source=? AND page=? AND ordinal=?", key)
            if not item.supplier_document_id and current["ambiguity"] == "source_identity_ambiguous":
                raise IngestionFailure("source_identity_ambiguous")
            parsed = parsers.prepare(raw, item.media_type, scope.article_xpath)
        except IngestionFailure as exc:
            self._authorize(row)
            held_content = None
            if exc.preparation is not None:
                held_content = {**exc.preparation, "rawArtifactId": "raw-" + raw_record["raw_hash"],
                    "rawHash": raw_record["raw_hash"], "parserProfile": json.loads(row["parser"]),
                    "representationHash": digest(exc.preparation["sources"])}
            with self.store.transaction(lambda: self._authorize(row)):
                self.db.execute("INSERT INTO preparations VALUES(?,?,NULL,?,?)", (preparation_key, raw_version, exc.code, canonical(held_content) if held_content is not None else None))
                self.db.execute("UPDATE candidates SET hold=?,failure=NULL WHERE round=? AND source=? AND page=? AND ordinal=?", (exc.code, *key))
            return
        representation_hash = digest(parsed["sources"])
        mapping_hash = digest({"representationHash": representation_hash, "segments": parsed["segments"], "runs": parsed["runs"]})
        text_hash = digest(parsed["text"])
        version = digest([raw_record["document"], raw_version, json.loads(row["parser"]), json.loads(row["request"])["cleanerVersion"], text_hash, mapping_hash])
        locators = [{"locatorId": "loc-" + digest([version, run, mapping_hash]), **run} for run in parsed.pop("runs")]
        content = {**parsed, "rawArtifactId": "raw-" + raw_record["raw_hash"], "rawHash": raw_record["raw_hash"],
                   "rawVersion": raw_version, "representationHash": representation_hash, "mappingHash": mapping_hash,
                   "parserProfile": json.loads(row["parser"]), "textHash": text_hash, "rawLocators": locators,
                   "cleanerVersion": json.loads(row["request"])["cleanerVersion"]}
        self._authorize(row)
        with self.store.transaction(lambda: self._authorize(row)):
            self.db.execute("INSERT INTO versions VALUES(?,?,?,?)", (version, raw_record["document"], raw_version, canonical(content)))
            self.db.execute("INSERT INTO preparations VALUES(?,?,?,NULL,NULL)", (preparation_key, raw_version, version))
            self.db.execute("UPDATE candidates SET version=?,new_text=1,failure=NULL WHERE round=? AND source=? AND page=? AND ordinal=?", (version, *key))

    def _complete_page(self, row, ordinal, page, request, final):
        self._authorize(row)
        with self.store.transaction(lambda: self._authorize(row)):
            checkpoint = self.store.one("SELECT * FROM scopes WHERE source=? AND scope=?", (row["source"], request.scope_id))
            if checkpoint["revision"] != row["expected_revision"]:
                raise IngestionFailure("checkpoint_stale")
            missing = self.store.one("""SELECT COUNT(*) n FROM candidates c LEFT JOIN raw_versions r ON r.id=c.raw_version
                LEFT JOIN blobs b ON b.hash=r.raw_hash LEFT JOIN versions v ON v.id=c.version
                WHERE c.round=? AND c.source=? AND c.page=? AND
                (c.error IS NOT NULL OR r.id IS NULL OR b.hash IS NULL OR (c.hold IS NULL AND v.id IS NULL))""", (row["id"], row["source"], ordinal))["n"]
            if missing:
                raise IngestionFailure("page_candidates_incomplete")
            through = checkpoint["through_time"]
            covered = page.terminal and (request.window is None or page.coverage_through == request.window.through)
            if covered and page.coverage_through and (through is None or timestamp(through) < timestamp(page.coverage_through)):
                through = page.coverage_through
            revision = checkpoint["revision"] + 1
            self.db.execute("UPDATE scopes SET revision=?,cursor=?,through_time=? WHERE source=? AND scope=? AND revision=?", (revision, page.next_cursor, through, row["source"], request.scope_id, row["expected_revision"]))
            self.db.execute("UPDATE pages SET complete=1 WHERE round=? AND source=? AND ordinal=?", (row["id"], row["source"], ordinal))
            count = self.store.one("SELECT COUNT(*) n FROM candidates WHERE round=? AND source=?", (row["id"], row["source"]))["n"]
            state = "complete" if final and covered else "incomplete" if final else "running"
            failure = None if not final or covered else "coverage_incomplete"
            completion = ("source-zero" if count == 0 else "nonzero-discovery") if state == "complete" else None
            self.db.execute("UPDATE rounds SET next_page=?,expected_revision=?,state=?,phase=?,failure=?,completion=? WHERE id=? AND source=?",
                (ordinal + 1, revision, state, "complete" if state == "complete" else "page-complete", failure, completion, row["id"], row["source"]))

    def resume(self, rid, source_id):
        row = self._round(rid, source_id)
        if row["state"] == "complete":
            self._authorize(row)
            return self.result(rid, source_id)
        try:
            source, scope = self._authorize(row)
            request = Run.model_validate_json(row["request"])
            manifest = Manifest.model_validate_json(row["manifest"])
            checkpoint = self.store.one("SELECT revision FROM scopes WHERE source=? AND scope=?", (source_id, request.scope_id))
            if checkpoint["revision"] != row["expected_revision"]:
                raise IngestionFailure("checkpoint_stale")
            for ordinal in range(row["next_page"], len(manifest.pages)):
                row = self._round(rid, source_id)
                page = manifest.pages[ordinal]
                saved = self._receive_page(row, ordinal, page, source)
                self._discover(row, page, saved)
                candidates = self.db.execute("SELECT * FROM candidates WHERE round=? AND source=? AND page=? ORDER BY ordinal", (rid, source_id, ordinal)).fetchall()
                failure = None
                for candidate in candidates:
                    try:
                        self._candidate(row, candidate, source, scope, manifest)
                    except (IngestionFailure, OSError, sqlite3.Error) as exc:
                        code = exc.code if isinstance(exc, IngestionFailure) else "persistence_or_input_failed"
                        self.db.execute("UPDATE candidates SET failure=? WHERE round=? AND source=? AND page=? AND ordinal=?", (code, rid, source_id, ordinal, candidate["ordinal"]))
                        failure = failure or IngestionFailure(code)
                if failure:
                    raise failure
                if page.status != "ok":
                    raise IngestionFailure("discovery_page_" + page.status)
                self._complete_page(row, ordinal, page, request, ordinal == len(manifest.pages) - 1)
        except IngestionFailure as exc:
            self.db.execute("UPDATE rounds SET state='incomplete',phase='stopped',failure=? WHERE id=? AND source=?", (exc.code, rid, source_id))
        except (OSError, sqlite3.Error) as exc:
            self.db.execute("UPDATE rounds SET state='incomplete',phase='stopped',failure='persistence_or_input_failed' WHERE id=? AND source=?", (rid, source_id))
        return self.result(rid, source_id)

    def result(self, rid, source, offset=0, limit=50):
        row = self._round(rid, source)
        request = json.loads(row["request"])
        cp = self.store.one("SELECT * FROM scopes WHERE source=? AND scope=?", (source, request["scopeId"]))
        counts = self.store.one("""SELECT COUNT(*) discoveredCandidates, COALESCE(SUM(new_raw),0) newRawVersions,
            COALESCE(SUM(new_text),0) newTextVersions, SUM(version IS NOT NULL) textReady,
            SUM(version IS NOT NULL AND new_text=0) reusedVersions, SUM(hold IS NOT NULL) held,
            SUM(error IS NOT NULL OR (hold IS NULL AND version IS NULL)) unfinished FROM candidates WHERE round=? AND source=?""", (rid, source))
        refs = self.db.execute("SELECT page,ordinal,document,raw_version,version,hold,error,ambiguity,failure FROM candidates WHERE round=? AND source=? ORDER BY page,ordinal LIMIT ? OFFSET ?", (rid, source, limit, offset)).fetchall()
        pages = self.db.execute("SELECT ordinal,page_id,status,complete FROM pages WHERE round=? AND source=? ORDER BY ordinal LIMIT ? OFFSET ?", (rid, source, limit, offset)).fetchall()
        refs_output = []
        for ref in refs:
            public_ref = {"page": ref["page"], "ordinal": ref["ordinal"], "documentId": ref["document"], "rawVersion": ref["raw_version"],
                "documentVersion": ref["version"], "hold": ref["hold"], "error": ref["error"], "ambiguity": ref["ambiguity"],
                "failure": {"code": ref["failure"]} if ref["failure"] else None}
            if ref["hold"] and ref["raw_version"]:
                key = digest([ref["raw_version"], json.loads(row["parser"]), request["cleanerVersion"]])
                held = self.store.one("SELECT content FROM preparations WHERE key=?", (key,))
                if held and held["content"]:
                    private = json.loads(held["content"])
                    public_ref["preparationMetadata"] = {k: private[k] for k in ("rawArtifactId", "representationHash", "limitations", "pageCount", "emptyPageCount") if k in private}
            refs_output.append(public_ref)
        return {"schemaVersion": SCHEMA, "roundId": rid, "sourceId": source, "provenance": PROVENANCE[json.loads(row["config"])["adapter"]], "inputDigest": row["input_digest"],
                "state": row["state"], "phase": row["phase"], "checkpoint": {"revision": cp["revision"], "continuation": cp["cursor"], "through": cp["through_time"], "roundRevision": row["expected_revision"]},
                "checkedWindow": request["window"], "timestampLimitations": json.loads(row["config"])["scope"]["timestampLimitations"],
                "counts": {k: counts[k] or 0 for k in counts.keys()}, "completion": row["completion"],
                "documentRefs": refs_output,
                "pages": [{"ordinal": p["ordinal"], "pageId": p["page_id"], "status": p["status"], "complete": bool(p["complete"])} for p in pages],
                "pagination": {"offset": offset, "limit": limit, "nextOffset": offset + limit if counts["discoveredCandidates"] > offset + limit or self.store.one("SELECT COUNT(*) n FROM pages WHERE round=? AND source=?", (rid, source))["n"] > offset + limit else None},
                "failure": {"code": row["failure"]} if row["failure"] else None}

    def inspect(self, request: Inspect):
        row = self._round(request.round_id, request.source_id)
        result = self.result(request.round_id, request.source_id, request.offset, request.limit)
        if not request.document_id:
            return result
        operations = ("read", "quote-display") if request.locator_id else ("read",)
        source, version, content, projection, metadata = self._prepared(row, request.round_id, request.source_id, request.document_id, request.document_version, operations)
        result["document"] = projection
        result["locatorMetadata"] = metadata
        if request.locator_id:
            locator = next((r for r in content["rawLocators"] if r["locatorId"] == request.locator_id), None)
            if locator is None or not locator["start"] <= request.start < request.end <= locator["end"]:
                raise IngestionFailure("locator_interval_unmapped")
            resolved = []
            for segment in content["segments"]:
                a, b = max(request.start, segment["cleanStart"]), min(request.end, segment["cleanEnd"])
                if a >= b:
                    continue
                source = content["sources"][segment["sourceIndex"]]
                start = segment["sourceStart"] + a - segment["cleanStart"]
                end = start + b - a
                resolved.append({"rawArtifactId": content["rawArtifactId"], "representationHash": content["representationHash"],
                    **{k: v for k, v in source.items() if k != "text"}, "sourceStart": start, "sourceEnd": end,
                    "cleanStart": a, "cleanEnd": b, "text": source["text"][start:end]})
            if "".join(s["text"] for s in resolved) != content["text"][request.start:request.end]:
                raise IngestionFailure("source_mapping_invalid")
            result["resolvedLocator"] = {"locatorId": locator["locatorId"], "start": request.start, "end": request.end, "segments": resolved}
        self._authorize(row, operations)
        return result

    def _prepared(self, row, round_id, source_id, document_id, document_version, operations):
        source, _ = self._authorize(row, operations)
        version = self.store.one("""SELECT v.* FROM versions v WHERE v.id=? AND v.document=? AND EXISTS
            (SELECT 1 FROM candidates c WHERE c.round=? AND c.source=? AND c.version=v.id)""", (document_version, document_id, round_id, source_id))
        if version is None:
            raise IngestionFailure("document_version_not_in_round")
        content = json.loads(version["content"])
        selector = json.loads(row["config"])["scope"]["articleXPath"]
        if "articleXPath" not in content["parserProfile"] or content["parserProfile"]["articleXPath"] != selector or content["parserProfile"] != json.loads(row["parser"]):
            raise IngestionFailure("preparation_profile_unbound")
        projection = {"documentId": version["document"], "documentVersion": version["id"], "sourceId": source_id,
            "textArtifactId": "text-" + version["id"], "inputKind": "body", "cleanerVersion": content["cleanerVersion"],
            "text": content["text"], "sourceHash": content["textHash"], "rawLocators": content["rawLocators"]}
        metadata = {k: content[k] for k in ("rawArtifactId", "rawHash", "rawVersion", "representationHash", "mappingHash", "parserProfile", "limitations")}
        for name in ("pageCount", "emptyPageCount"):
            if name in content:
                metadata[name] = content[name]
        return source, version, content, projection, metadata

    def export(self, request: Export, require_store: bool = False):
        """Exact observation + server-owned metadata for a downstream consumer; read-only on all ingestion state.

        By default a consumer needs read and quote-display. A consumer that PERSISTS the exported text (the app document import)
        must pass `require_store`, which additionally requires the current grant to allow `store`; the check runs against the
        current registry on this call like every other right, so no consumer has to parse or trust the registry itself."""
        row = self._round(request.round_id, request.source_id)
        operations = ("read", "store", "quote-display") if require_store else ("read", "quote-display")
        candidate = self.store.one("SELECT * FROM candidates WHERE round=? AND source=? AND page=? AND ordinal=?", (request.round_id, request.source_id, request.page, request.ordinal))
        if candidate is None or candidate["hold"] or candidate["error"] or (candidate["document"], candidate["raw_version"], candidate["version"]) != (request.document_id, request.raw_version, request.document_version):
            raise IngestionFailure("observation_not_found")
        source, version, content, projection, metadata = self._prepared(row, request.round_id, request.source_id, request.document_id, request.document_version, operations)
        if content["rawVersion"] != request.raw_version:
            raise IngestionFailure("observation_not_found")
        item = Item.model_validate_json(candidate["data"])
        page = self.store.one("SELECT page_id,observed_at FROM pages WHERE round=? AND source=? AND ordinal=?", (request.round_id, request.source_id, request.page))
        grant = source.grant
        result = {"schemaVersion": SCHEMA, "observation": {"roundId": request.round_id, "sourceId": request.source_id, "page": request.page,
            "ordinal": request.ordinal, "pageId": page["page_id"], "observedAt": page["observed_at"], "documentId": request.document_id,
            "rawVersion": request.raw_version, "documentVersion": request.document_version,
            "url": parsers.normalize_url(item.url, source.allowed_hosts), "title": item.title, "publishedAt": item.published_at,
            "modifiedAt": item.modified_at, "sourceRevision": item.source_revision, "mediaType": item.media_type},
            "grant": {"grantId": grant.grant_id, "revision": grant.revision}, "document": projection, "locatorMetadata": metadata}
        if item.publisher is not None:
            # Only a declared outlet is exported: absence means unspecified, never null, so an unspecified export keeps its exact earlier keys.
            result["observation"]["publisher"] = item.publisher
        if item.collection is not None:
            # Collected observations alone add provenance + acquisition facts. An authored export keeps exactly the keys the closed
            # application importer (IngestionExportParser) accepts, so its absence of these keys means "authored control".
            result["observation"].update(provenance=PROVENANCE["collected-http"], collection=item.collection.wire())
        self._authorize(row, operations)
        return result


def recorded(store: Store, changed: dict) -> bool:
    """Whether the normalized changed identity (document/source/grant wire) is recorded in this ingestion ledger.

    Pure read of an `existing=True` store: no authority, registry file or delivery. It only decides whether an empty downstream result
    is a real absence or an identity this ledger never saw. Grants are matched in the registry snapshots frozen at round registration,
    for the source each round belongs to. A snapshot that is missing or does not parse is `dependency_record_invalid`, never a miss."""
    try:
        kind = changed["kind"]
        if kind == "source":
            return store.one("SELECT 1 FROM rounds WHERE source=? LIMIT 1", (changed["sourceId"],)) is not None
        if kind == "document":
            document, version, raw = changed["documentId"], changed["documentVersion"], changed["rawVersion"]
            if version is not None:
                sql, args = "SELECT 1 FROM versions WHERE id=? AND document=?", [version, document]
                if raw is not None:
                    sql, args = sql + " AND raw_version=?", [*args, raw]
            elif raw is not None:
                sql, args = "SELECT 1 FROM raw_versions WHERE id=? AND document=?", [raw, document]
            else:
                sql, args = "SELECT 1 FROM documents WHERE id=?", [document]
            return store.one(sql, args) is not None
        for row in store.db.execute("SELECT DISTINCT r.source, r.registry_hash, b.data FROM rounds r LEFT JOIN blobs b ON b.hash=r.registry_hash "
                                    "ORDER BY r.registry_hash, r.source").fetchall():
            if row["data"] is None:
                raise IngestionFailure("dependency_record_invalid")
            try:
                registry = Registry.model_validate_json(row["data"])
            except ValueError as exc:
                raise IngestionFailure("dependency_record_invalid") from exc
            grant = next((s.grant for s in registry.sources if s.source_id == row["source"]), None)
            if grant is not None and grant.grant_id == changed["grantId"] and (changed["revision"] is None or grant.revision == changed["revision"]):
                return True
        return False
    except sqlite3.DatabaseError as exc:
        raise IngestionFailure("ingestion_state_invalid") from exc
