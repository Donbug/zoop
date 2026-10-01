"""Read-only access to the PoC ledger (PostgreSQL) and its Neo4j projection for the admin side.

Only SELECTs run here. Short-lived connections keep the BFF free of stale sockets, and every failure
becomes ``503 ledger_unavailable`` without echoing the DSN.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlparse

from .errors import ApiError

log = logging.getLogger("zoop_bff.ledger")


class LedgerUnavailable(ApiError):
    def __init__(self, message: str, cause: BaseException | None = None):
        super().__init__(
            503,
            "ledger_unavailable",
            message,
            {"cause": type(cause).__name__} if cause is not None else None,
        )


class Ledger(Protocol):
    database: str

    def inspect(self) -> dict[str, Any]: ...

    def policy(self) -> dict[str, Any]: ...

    def projection(self) -> dict[str, Any]: ...

    def run_reports(self) -> list[dict[str, Any]]: ...


class Neo4jProbe(Protocol):
    def projected(self) -> dict[str, set[str]]:
        """issue_id -> relation ids that Neo4j currently holds for active issues."""


def _iso(value: Any) -> str | None:
    return value.isoformat(timespec="seconds") if isinstance(value, datetime) else None


def database_name(dsn: str) -> str:
    parsed = urlparse(dsn)
    return parsed.path.lstrip("/") or "unknown"


class PocLedger:
    """PostgresRepository.inspect() plus read-only SQL for policy, projection state and run reports."""

    def __init__(self, dsn: str, connect_timeout_seconds: int = 5):
        self._dsn = dsn
        self._timeout = connect_timeout_seconds
        self.database = database_name(dsn)

    def _dsn_with_timeout(self) -> str:
        if "connect_timeout" in self._dsn:
            return self._dsn
        sep = "&" if "?" in self._dsn else "?"
        if self._dsn.startswith(("postgresql://", "postgres://")):
            return f"{self._dsn}{sep}connect_timeout={self._timeout}"
        return f"{self._dsn} connect_timeout={self._timeout}"

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        try:
            return psycopg.connect(self._dsn_with_timeout(), autocommit=True, row_factory=dict_row)
        except Exception as exc:
            log.warning("ledger connection failed: %s", type(exc).__name__)
            raise LedgerUnavailable("PoC 원장(PostgreSQL)에 연결할 수 없습니다.", exc) from exc

    def _read(self, fn):
        conn = self._connect()
        try:
            return fn(conn)
        except LedgerUnavailable:
            raise
        except Exception as exc:
            log.warning("ledger read failed: %s", type(exc).__name__)
            raise LedgerUnavailable("PoC 원장을 읽지 못했습니다.", exc) from exc
        finally:
            conn.close()

    def inspect(self) -> dict[str, Any]:
        from investmate.storage import PostgresRepository

        try:
            repo = PostgresRepository(self._dsn_with_timeout())
        except Exception as exc:
            log.warning("ledger connection failed: %s", type(exc).__name__)
            raise LedgerUnavailable("PoC 원장(PostgreSQL)에 연결할 수 없습니다.", exc) from exc
        try:
            return repo.inspect(None)
        except Exception as exc:
            log.warning("ledger inspect failed: %s", type(exc).__name__)
            raise LedgerUnavailable("PoC 원장을 읽지 못했습니다.", exc) from exc
        finally:
            repo.close()

    def policy(self) -> dict[str, Any]:
        def read(conn):
            row = conn.execute("SELECT version, metadata FROM investmate.policy WHERE singleton").fetchone()
            return {"version": row["version"], "metadata": row["metadata"]} if row else {"version": None, "metadata": {}}

        return self._read(read)

    def projection(self) -> dict[str, Any]:
        """Outbox state: unfinished GraphDB projection jobs are what "미반영" means in the PoC."""

        def read(conn):
            row = conn.execute(
                "SELECT count(*) FILTER (WHERE completed_at IS NULL) AS pending, "
                "min(created_at) FILTER (WHERE completed_at IS NULL) AS oldest_pending, "
                "max(completed_at) AS last_completed, count(*) AS total FROM investmate.outbox"
            ).fetchone()
            return {
                "pending": int(row["pending"]),
                "oldest_pending_at": _iso(row["oldest_pending"]),
                "last_completed_at": _iso(row["last_completed"]),
                "total": int(row["total"]),
            }

        return self._read(read)

    def run_reports(self) -> list[dict[str, Any]]:
        def read(conn):
            rows = conn.execute("SELECT run_id, report FROM investmate.runs").fetchall()
            return [{"run_id": r["run_id"], "report": r["report"]} for r in rows]

        return self._read(read)


class Neo4jReader:
    """Which relations Neo4j holds per active issue (compared with the ledger, never written)."""

    def __init__(self, uri: str, user: str, password: str):
        self._uri, self._user, self._password = uri, user, password

    def projected(self) -> dict[str, set[str]]:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password), connection_timeout=5)
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                issues = {
                    r["issue_id"]: set()
                    for r in session.run("MATCH (i:InvestMateIssue) WHERE i.active = true RETURN i.issue_id AS issue_id")
                }
                for r in session.run(
                    "MATCH ()-[r]->() WHERE r.investmate_owner IS NOT NULL "
                    "RETURN r.investmate_owner AS owner, r.relation_id AS relation_id"
                ):
                    if r["owner"] in issues:
                        issues[r["owner"]].add(r["relation_id"])
                return issues
        finally:
            driver.close()
