"""BFF state directory: one SQLite file for admin records plus immutable graph snapshot files.

Everything the admin side must remember across restarts lives here (audit log, review decisions,
graph version metadata, jobs, briefing rounds, AI usage events). The PoC ledger is never written.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL, actor_kind TEXT NOT NULL, actor_id TEXT NOT NULL, actor_email TEXT,
  action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT, reason TEXT,
  outcome TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_action ON audit_log(action, id);
CREATE TABLE IF NOT EXISTS admin_accounts (
  id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
  role TEXT NOT NULL, password_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_type TEXT NOT NULL, target_id TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
  admin_id TEXT NOT NULL, admin_email TEXT NOT NULL, at TEXT NOT NULL, origin TEXT NOT NULL,
  payload TEXT
);
CREATE INDEX IF NOT EXISTS review_target ON review_decisions(target_type, target_id, id);
-- Publication rule switches (review_rules.py): append-only; the newest row per rule is its state, no row = the rule's default.
CREATE TABLE IF NOT EXISTS review_rule_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id TEXT NOT NULL, enabled INTEGER NOT NULL CHECK (enabled IN (0,1)), reason TEXT NOT NULL,
  admin_id TEXT NOT NULL, admin_email TEXT NOT NULL, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS review_rule_target ON review_rule_changes(rule_id, id);
CREATE TABLE IF NOT EXISTS graph_versions (
  id TEXT PRIMARY KEY, sequence INTEGER NOT NULL UNIQUE, kind TEXT NOT NULL,
  created_at TEXT NOT NULL, created_by TEXT NOT NULL, reason TEXT, source_label TEXT NOT NULL,
  source_as_of TEXT NOT NULL, policy_version TEXT, issue_count INTEGER NOT NULL,
  relation_count INTEGER NOT NULL, article_count INTEGER NOT NULL, candidate_count INTEGER,
  synthetic INTEGER NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, file TEXT NOT NULL,
  graph_db TEXT NOT NULL, seed_sha256 TEXT, content_digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_activations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version_id TEXT NOT NULL REFERENCES graph_versions(id), previous_version_id TEXT,
  at TEXT NOT NULL, admin_email TEXT NOT NULL, reason TEXT, action TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, seq INTEGER NOT NULL UNIQUE, kind TEXT NOT NULL, status TEXT NOT NULL,
  requested_at TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, seq);
CREATE TABLE IF NOT EXISTS briefing_rounds (
  id TEXT PRIMARY KEY, date TEXT NOT NULL, edition TEXT NOT NULL, status TEXT NOT NULL,
  data TEXT NOT NULL, payload TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS briefing_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, round_id TEXT NOT NULL REFERENCES briefing_rounds(id),
  n INTEGER NOT NULL, trigger TEXT NOT NULL, admin_email TEXT, started_at TEXT NOT NULL,
  finished_at TEXT, status TEXT NOT NULL, failure_reason TEXT
);
CREATE TABLE IF NOT EXISTS briefing_corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT, round_id TEXT NOT NULL REFERENCES briefing_rounds(id),
  seq INTEGER NOT NULL, event_id TEXT, original TEXT, corrected TEXT NOT NULL, reason TEXT NOT NULL,
  created_at TEXT NOT NULL, admin_email TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, feature TEXT NOT NULL, ok INTEGER NOT NULL,
  duration_ms REAL NOT NULL, model_calls INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  code TEXT, message TEXT
);
CREATE INDEX IF NOT EXISTS ai_feature_at ON ai_events(feature, at);
-- user behaviour events (telemetry.py), chat transcripts (chat.py) and votes (feedback.py).
-- No real name, e-mail or IP is stored: ``subject`` is a member id or a keyed hash of a guest session id.
CREATE TABLE IF NOT EXISTS telemetry_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, subject TEXT NOT NULL, subject_kind TEXT NOT NULL,
  type TEXT NOT NULL, screen TEXT, target_id TEXT, target_kind TEXT, round_id TEXT, view_id TEXT,
  company_ids TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS telemetry_at ON telemetry_events(at);
CREATE INDEX IF NOT EXISTS telemetry_type_at ON telemetry_events(type, at);
CREATE TABLE IF NOT EXISTS chat_sessions (
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, owner_kind TEXT NOT NULL, context_ids TEXT NOT NULL,
  created_at TEXT NOT NULL, messages INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS chat_sessions_owner ON chat_sessions(owner_id);
CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES chat_sessions(id), seq INTEGER NOT NULL,
  at TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
  context_ids TEXT NOT NULL, company_ids TEXT NOT NULL, citation_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS chat_messages_at ON chat_messages(at);
CREATE INDEX IF NOT EXISTS chat_messages_session ON chat_messages(session_id, seq);
CREATE TABLE IF NOT EXISTS feedback (
  feature TEXT NOT NULL, target_id TEXT NOT NULL, subject TEXT NOT NULL, subject_kind TEXT NOT NULL,
  value TEXT NOT NULL CHECK (value IN ('up','down')), reason TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (feature, target_id, subject)
);
CREATE INDEX IF NOT EXISTS feedback_updated ON feedback(updated_at);
-- members, sessions and settings (accounts.py). Tokens are stored as SHA-256 digests only.
CREATE TABLE IF NOT EXISTS members (
  id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, password_hash TEXT,
  signup_method TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','blocked')),
  created_at TEXT NOT NULL, last_active_at TEXT, login_count INTEGER NOT NULL DEFAULT 0, terms TEXT,
  investor INTEGER, mode TEXT NOT NULL DEFAULT 'watchlist', watchlist TEXT NOT NULL DEFAULT '[]',
  tutorial_completed INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS member_identities (
  provider TEXT NOT NULL, subject TEXT NOT NULL, member_id TEXT NOT NULL REFERENCES members(id),
  created_at TEXT NOT NULL, PRIMARY KEY (provider, subject)
);
CREATE TABLE IF NOT EXISTS member_connections (
  member_id TEXT PRIMARY KEY REFERENCES members(id), id TEXT NOT NULL, mock_portfolio_id TEXT NOT NULL,
  label TEXT NOT NULL, connected_at TEXT NOT NULL, holdings TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS member_sessions (
  token_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, principal_id TEXT NOT NULL,
  member_id TEXT REFERENCES members(id), created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  tutorial_completed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS member_sessions_member ON member_sessions(member_id);
CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY, provider TEXT NOT NULL, binding TEXT NOT NULL, return_to TEXT NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS briefing_payload_immutable
BEFORE UPDATE OF payload ON briefing_rounds
WHEN OLD.payload IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'published briefing payload is immutable');
END;
CREATE TRIGGER IF NOT EXISTS briefing_round_no_delete
BEFORE DELETE ON briefing_rounds
WHEN OLD.payload IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'published briefing cannot be deleted');
END;
"""


def utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class StateDb:
    """Thread-safe SQLite wrapper. Writers serialize on one lock; a transaction is all-or-nothing."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "zoop-admin.sqlite3"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.path, check_same_thread=False, isolation_level=None, timeout=30
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """BEGIN IMMEDIATE ... COMMIT; re-entrant inside the same thread."""
        with self._lock:
            if self._conn.in_transaction:
                yield self._conn
                return
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self.transaction() as conn:
            return conn.execute(sql, params)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
