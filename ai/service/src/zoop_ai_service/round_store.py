"""Exact request admissions and atomic ready/read grants under the service lifetime lock."""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
from pathlib import Path

from .config import ConfigError
from .jobs import ApiError
from .plan_authority import canonical
from .plan_verify import decode, read_file


class RoundStore:
    def __init__(self, root: Path, binding: dict):
        self.root = root / "rounds"
        self._lock = threading.RLock()
        marker = self.root / "binding.json"
        database = self.root / "rounds.sqlite3"
        if not self.root.exists():
            self.root.mkdir(mode=0o700)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ConfigError("ZOOP_AI_SERVICE_ROUND_PROFILE", "round_state_unusable")
        expected = {"schemaVersion": "zoop-ai-round-state-1", "binding": binding}
        existing = marker.exists()
        if existing:
            if decode(read_file(marker, 65536, owned=True)) != expected or not database.exists():
                raise ConfigError("ZOOP_AI_SERVICE_ROUND_PROFILE", "round_binding_mismatch")
        elif any(self.root.iterdir()):
            raise ConfigError("ZOOP_AI_SERVICE_ROUND_PROFILE", "round_initialization_incomplete")
        if not existing:
            fd = os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        for path in (database, *(self.root / (database.name + suffix) for suffix in ("-wal", "-shm"))):
            if os.path.lexists(path):
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
                    raise ConfigError("ZOOP_AI_SERVICE_ROUND_PROFILE", "round_state_unusable")
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        if not existing:
            self.db.executescript("""
                CREATE TABLE requests(owner TEXT NOT NULL, family TEXT NOT NULL, round_id TEXT NOT NULL,
                    body BLOB NOT NULL, context TEXT NOT NULL, result TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(owner,family,round_id));
                CREATE TABLE grants(owner TEXT NOT NULL, handoff_id TEXT NOT NULL, round_id TEXT NOT NULL,
                    manifest_digest TEXT NOT NULL, bundle_digest TEXT NOT NULL, active INTEGER NOT NULL,
                    PRIMARY KEY(owner,handoff_id));
                CREATE TABLE observation_claims(ref TEXT PRIMARY KEY, owner TEXT NOT NULL, round_id TEXT NOT NULL);
            """)
            self.db.commit()
            save_private(marker, canonical(expected).encode())
        else:
            with self.db:
                columns = {column["name"] for column in self.db.execute("PRAGMA table_info(requests)")}
                if "version" not in columns:
                    self.db.execute("ALTER TABLE requests ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
                self.db.execute("""CREATE TABLE IF NOT EXISTS observation_claims(
                    ref TEXT PRIMARY KEY, owner TEXT NOT NULL, round_id TEXT NOT NULL)""")
        with self._lock, self.db:
            self.db.execute("""CREATE INDEX IF NOT EXISTS requests_execution_state
                ON requests(json_extract(result,'$.state'),round_id,owner,family)""")
            for row in self.db.execute("""SELECT owner,family,round_id,result,context FROM requests
                    WHERE json_extract(result,'$.state')='running'""").fetchall():
                result = json.loads(row["result"])
                if result["state"] == "running" and json.loads(row["context"]).get("started", False):
                    result.update(state="failed", code="round_outcome_unknown")
                    self.db.execute("UPDATE requests SET result=?,version=version+1 WHERE owner=? AND family=? AND round_id=?",
                                    (canonical(result), row["owner"], row["family"], row["round_id"]))
            for row in self.db.execute("SELECT owner,round_id,context FROM requests WHERE family='run'").fetchall():
                for observation in json.loads(row["context"]).get("observations", []):
                    ref = canonical(observation)
                    prior = self.db.execute("SELECT owner,round_id FROM observation_claims WHERE ref=?", (ref,)).fetchone()
                    if prior is not None and (prior["owner"], prior["round_id"]) != (row["owner"], row["round_id"]):
                        raise ConfigError("ZOOP_AI_SERVICE_ROUND_PROFILE", "round_observation_conflict")
                    self.db.execute("INSERT OR IGNORE INTO observation_claims VALUES(?,?,?)", (ref, row["owner"], row["round_id"]))

    def close(self):
        self.db.close()

    @staticmethod
    def unpack(row):
        return {**dict(row), "context": json.loads(row["context"]), "result": json.loads(row["result"])} if row else None

    def get(self, owner, family, round_id):
        with self._lock:
            return self.unpack(self.db.execute("SELECT * FROM requests WHERE owner=? AND family=? AND round_id=?",
                                              (owner, family, round_id)).fetchone())

    def _busy(self):
        return self.db.execute("SELECT 1 FROM requests WHERE json_extract(result,'$.state')='running' LIMIT 1").fetchone() is not None

    def reserve(self, owner, family, round_id, raw, context, *, preflight=None):
        with self._lock, self.db:
            row = self.get(owner, family, round_id)
            if row is not None:
                if row["body"] != raw:
                    raise ApiError(409, "request_conflict")
                return False, row
            if self._busy():
                raise ApiError(409, "round_busy", retry_after=1)
            if preflight is not None:
                preflight()
            result = {"schemaVersion": "zoop-ai-round-" + family + "-1", "roundId": round_id, "state": "running"}
            self.db.execute("INSERT INTO requests(owner,family,round_id,body,context,result) VALUES(?,?,?,?,?,?)",
                            (owner, family, round_id, raw, canonical(context), canonical(result)))
        return True, self.get(owner, family, round_id)

    def save(self, row, result, *, grant=False):
        with self._lock, self.db:
            current = self.get(row["owner"], row["family"], row["round_id"])
            if current is None or current["version"] != row["version"]:
                raise ApiError(409, "round_state_conflict")
            if grant:
                old = self.db.execute("SELECT * FROM grants WHERE owner=? AND handoff_id=?", (row["owner"], result["handoffId"])).fetchone()
                pins = (result["manifestDigest"], result["bundleDigest"])
                if old is not None and (old["manifest_digest"], old["bundle_digest"]) != pins:
                    raise ApiError(409, "handoff_pin_mismatch")
                if old is None:
                    self.db.execute("INSERT INTO grants VALUES(?,?,?,?,?,1)", (row["owner"], result["handoffId"], row["round_id"], *pins))
                elif not old["active"]:
                    raise ApiError(403, "handoff_not_allowed")
            changed = self.db.execute(
                "UPDATE requests SET context=?,result=?,version=version+1 WHERE owner=? AND family=? AND round_id=? AND version=?",
                (canonical(row["context"]), canonical(result), row["owner"], row["family"], row["round_id"], row["version"]))
            if changed.rowcount != 1:
                raise ApiError(409, "round_state_conflict")
        row["version"] += 1
        row["result"] = result

    def rows(self, owner, family):
        with self._lock:
            return [self.unpack(row) for row in self.db.execute(
                "SELECT * FROM requests WHERE owner=? AND family=? ORDER BY round_id", (owner, family)).fetchall()]

    def pending(self):
        with self._lock:
            return [self.unpack(row) for row in self.db.execute("""
                SELECT * FROM requests WHERE json_extract(result,'$.state')='running'
                AND COALESCE(json_extract(context,'$.started'),0)=0 ORDER BY round_id,owner,family""").fetchall()]

    def incomplete(self):
        with self._lock:
            return [self.unpack(row) for row in self.db.execute("""
                SELECT * FROM requests WHERE family='handoff' AND json_extract(result,'$.state')='analysis_incomplete'
                ORDER BY round_id,owner""").fetchall()]

    def claim(self, row, context=None):
        with self._lock, self.db:
            current = self.get(row["owner"], row["family"], row["round_id"])
            if current is None or current["version"] != row["version"] or current["result"]["state"] not in {"running", "analysis_incomplete"} \
                    or current["context"].get("started", False) and current["result"]["state"] == "running":
                return None
            if current["result"]["state"] == "analysis_incomplete" and self._busy():
                return None
            if context is not None:
                current["context"].update(context)
            current["context"]["started"] = True
            current["result"] = {"schemaVersion": current["result"]["schemaVersion"], "roundId": current["round_id"], "state": "running"}
            self.save(current, current["result"])
            return current

    def claim_observations(self, row, observations, carryover):
        """Claim exact native refs before a plan can be published; never release on uncertainty."""
        with self._lock, self.db:
            current = self.get(row["owner"], row["family"], row["round_id"])
            if current is None or current["version"] != row["version"] or current["result"]["state"] != "running":
                raise ApiError(409, "round_state_conflict")
            for observation in observations:
                try:
                    self.db.execute("INSERT INTO observation_claims VALUES(?,?,?)",
                                    (canonical(observation), row["owner"], row["round_id"]))
                except sqlite3.IntegrityError:
                    raise ApiError(409, "round_observation_conflict") from None
            row["context"].update(observations=observations, carryover=carryover)
            self.save(row, row["result"])

    def claimed(self, observations):
        """Indexed permanent-claim lookup for one bounded native inventory page."""
        if not observations:
            return set()
        if len(observations) > 100:
            raise ValueError("observation page limit")
        refs = [canonical(ref) for ref in observations]
        with self._lock:
            return {row["ref"] for row in self.db.execute(
                "SELECT ref FROM observation_claims WHERE ref IN (" + ",".join("?" for _ in refs) + ")", refs)}

    def grant(self, owner, handoff_id):
        with self._lock:
            row = self.db.execute("SELECT * FROM grants WHERE owner=? AND handoff_id=? AND active=1", (owner, handoff_id)).fetchone()
            return dict(row) if row else None

    def owns(self, handoff_id):
        with self._lock:
            return self.db.execute("SELECT 1 FROM grants WHERE handoff_id=?", (handoff_id,)).fetchone() is not None


def save_private(path, raw):
    """Immutable, fsynced input bytes; an existing different file is never adopted."""
    if os.path.lexists(path):
        if read_file(path, max(len(raw), 1), owned=True) != raw:
            raise ApiError(409, "round_input_conflict")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
