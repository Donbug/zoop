"""Immutable published graph versions (requirement 76).

What users see = the active version's snapshot file + the admin review records. A version is a
canonical JSON copy of an inspect()-shaped payload plus metadata rows; the file is written once
(read-only) and its SHA-256 is re-checked on every read. The first start registers
``ZOOP_SNAPSHOT_PATH`` as ``v1`` (kind ``seed``); later versions are published from the PoC ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .audit import Actor, AuditLog, Clock
from .dataset import DatasetFormatError, build_dataset
from .errors import ApiError, SourceUnavailable
from .review import ReviewStore
from .statedb import StateDb, dumps, utc_iso


@dataclass(frozen=True)
class GraphVersion:
    id: str
    sequence: int
    kind: str  # seed | ledger
    created_at: str
    created_by: str
    reason: str | None
    source_label: str
    source_as_of: str
    policy_version: str | None
    issue_count: int
    relation_count: int
    article_count: int
    candidate_count: int | None
    synthetic: bool
    sha256: str
    bytes: int
    file: str
    graph_db: dict[str, Any]
    seed_sha256: str | None


@dataclass(frozen=True)
class Activation:
    version_id: str
    previous_version_id: str | None
    at: str
    admin_email: str
    reason: str | None
    action: str


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    issues = [i for i in payload.get("issues") or [] if isinstance(i, dict)]
    articles = {
        a.get("article_id"): a for i in issues for a in i.get("articles") or [] if isinstance(a, dict)
    }
    candidates = payload.get("candidates")
    return {
        "issue_count": len(issues),
        "relation_count": sum(len(i.get("relations") or []) for i in issues),
        "article_count": len(articles),
        "candidate_count": len(candidates) if isinstance(candidates, list) else None,
        "synthetic": not articles or any(a.get("synthetic") is not False for a in articles.values()),
    }


def _company_ids(payload: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for issue in payload.get("issues") or []:
        for mention in issue.get("mentions") or []:
            for participant in mention.get("participants") or []:
                if isinstance(participant, dict) and isinstance(participant.get("company_id"), str):
                    ids.add(participant["company_id"])
        for relation in issue.get("relations") or []:
            if relation.get("relation_type") in ("INVOLVES", "STRUCTURALLY_RELATED_TO") and isinstance(relation.get("target"), str):
                ids.add(relation["target"])
    extension = payload.get("zoop") if isinstance(payload.get("zoop"), dict) else {}
    for company in extension.get("companies") or []:
        if isinstance(company, dict) and isinstance(company.get("company_id"), str):
            ids.add(company["company_id"])
    return ids


def _version(row: Any) -> GraphVersion:
    return GraphVersion(
        id=row["id"],
        sequence=row["sequence"],
        kind=row["kind"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        reason=row["reason"],
        source_label=row["source_label"],
        source_as_of=row["source_as_of"],
        policy_version=row["policy_version"],
        issue_count=row["issue_count"],
        relation_count=row["relation_count"],
        article_count=row["article_count"],
        candidate_count=row["candidate_count"],
        synthetic=bool(row["synthetic"]),
        sha256=row["sha256"],
        bytes=row["bytes"],
        file=row["file"],
        graph_db=json.loads(row["graph_db"]),
        seed_sha256=row["seed_sha256"],
    )


class GraphStore:
    def __init__(
        self, db: StateDb, clock: Clock, audit: AuditLog, reviews: ReviewStore, seed_path: Path
    ):
        self._db = db
        self._clock = clock
        self._audit = audit
        self._reviews = reviews
        self._seed_path = seed_path
        self._dir = db.directory / "graph"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._seed_error: SourceUnavailable | None = None
        self._company_cache: dict[str, frozenset[str]] = {}

    # -- reads
    def versions(self) -> list[GraphVersion]:
        return [_version(r) for r in self._db.query("SELECT * FROM graph_versions ORDER BY sequence DESC")]

    def get(self, version_id: str) -> GraphVersion | None:
        row = self._db.one("SELECT * FROM graph_versions WHERE id = ?", (version_id,))
        return _version(row) if row else None

    def activations(self) -> list[Activation]:
        rows = self._db.query("SELECT * FROM graph_activations ORDER BY id DESC")
        return [
            Activation(r["version_id"], r["previous_version_id"], r["at"], r["admin_email"], r["reason"], r["action"])
            for r in rows
        ]

    def active_id(self) -> str | None:
        row = self._db.one("SELECT version_id FROM graph_activations ORDER BY id DESC LIMIT 1")
        return row["version_id"] if row else None

    def active(self) -> GraphVersion | None:
        active_id = self.active_id()
        return self.get(active_id) if active_id else None

    def activated_at(self, version_id: str) -> str | None:
        """Time of the latest activation of this version while it is the active one."""
        if self.active_id() != version_id:
            return None
        row = self._db.one(
            "SELECT at FROM graph_activations WHERE version_id = ? ORDER BY id DESC LIMIT 1", (version_id,)
        )
        return row["at"] if row else None

    def published_company_ids(self) -> frozenset[str]:
        """Company ids that appear in any registered version (cached: a version never changes).

        Watchlist validation uses this so that publishing or rolling back a version can never make an
        already saved company unknown.
        """
        ids: set[str] = set()
        for version in self.versions():
            cached = self._company_cache.get(version.id)
            if cached is None:
                cached = frozenset(_company_ids(self.read_payload(version)))
                self._company_cache[version.id] = cached
            ids |= cached
        return frozenset(ids)

    def file_stamp(self, version: GraphVersion) -> tuple[int, int] | None:
        """(mtime, size) of the version file: a changed file forces a re-read and a checksum check."""
        try:
            stat = (self._dir / version.file).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def read_payload(self, version: GraphVersion) -> dict[str, Any]:
        path = self._dir / version.file
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise SourceUnavailable(
                "게시된 그래프 버전 파일을 읽을 수 없습니다.",
                {"source": "graph-version", "cause": type(exc).__name__, "version": version.id},
            ) from exc
        if hashlib.sha256(raw).hexdigest() != version.sha256:
            raise SourceUnavailable(
                "게시된 그래프 버전 파일이 기록된 해시와 다릅니다.",
                {"source": "graph-version", "cause": "ChecksumMismatch", "version": version.id},
            )
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise SourceUnavailable("게시된 그래프 버전의 최상위 값이 객체가 아닙니다.", {"version": version.id})
        return payload

    def warnings(self) -> list[str]:
        """Seed drift: the configured snapshot no longer matches what v1 was registered from."""
        first = self._db.one("SELECT * FROM graph_versions WHERE kind='seed' ORDER BY sequence LIMIT 1")
        if first is None or not first["seed_sha256"]:
            return []
        try:
            current = hashlib.sha256(self._seed_path.read_bytes()).hexdigest()
        except OSError:
            return []
        if current != first["seed_sha256"]:
            return [
                f"ZOOP_SNAPSHOT_PATH({self._seed_path.name}) differs from the registered seed {first['id']}; "
                "use a new ZOOP_STATE_DIR to register it"
            ]
        return []

    # -- seed
    def ensure_seed(self) -> None:
        """Register the configured snapshot as the first version (idempotent, lazy)."""
        if self.active_id() is not None:
            return
        with self._lock:
            if self.active_id() is not None:
                return
            path = self._seed_path
            try:
                stat = path.stat()
                raw = path.read_bytes()
                payload = json.loads(raw)
            except (OSError, ValueError) as exc:
                raise self._unavailable("스냅샷 파일을 읽을 수 없습니다.", exc) from exc
            if not isinstance(payload, dict):
                raise self._unavailable("스냅샷 JSON의 최상위 값이 객체가 아닙니다.", None)
            try:
                build_dataset(payload, source_mode="snapshot", source_label=path.name, as_of="validation")
            except (DatasetFormatError, KeyError, TypeError, AttributeError) as exc:
                raise SourceUnavailable(
                    "승인 데이터의 형식이 올바르지 않습니다.",
                    {"source": "snapshot", "cause": type(exc).__name__, "reason": str(exc)},
                ) from exc
            as_of = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds")
            with self._db.transaction():
                version = self._store(
                    payload,
                    kind="seed",
                    created_by="system",
                    reason="최초 기동 시드 스냅샷 등록",
                    source_label=f"snapshot:{path.name}",
                    source_as_of=as_of,
                    policy_version=None,
                    graph_db={"status": "unknown", "pendingJobsAtCreation": None, "note": "스냅샷 파일: 원장 연결 없음"},
                    seed_sha256=hashlib.sha256(raw).hexdigest(),
                )
                self._activate(version.id, None, "system", "최초 기동 시드 스냅샷 등록", "seed")
                migrated = self._reviews.migrate_exclusions(payload.get("review_exclusions") or [], as_of)
            self._audit.record(
                Actor("system", "startup"),
                "graph.seed",
                "graph-version",
                version.id,
                reason="최초 기동 시드 스냅샷 등록",
                detail={"source": path.name, "migratedReviewExclusions": migrated},
            )

    def _unavailable(self, message: str, exc: BaseException | None) -> SourceUnavailable:
        return SourceUnavailable(
            message,
            {"source": "snapshot", "cause": type(exc).__name__ if exc else "InvalidSnapshot"},
        )

    # -- writes
    def _store(
        self,
        payload: dict[str, Any],
        *,
        kind: str,
        created_by: str,
        reason: str | None,
        source_label: str,
        source_as_of: str,
        policy_version: str | None,
        graph_db: dict[str, Any],
        seed_sha256: str | None = None,
    ) -> GraphVersion:
        body = canonical(payload)
        digest = hashlib.sha256(body).hexdigest()
        sequence = int((self._db.one("SELECT COALESCE(MAX(sequence),0)+1 AS n FROM graph_versions") or {"n": 1})["n"])
        version_id = f"v{sequence}"
        filename = f"{version_id}.json"
        target = self._dir / filename
        if target.exists():
            target.chmod(0o644)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, target)
        target.chmod(0o444)
        stats = summarize(payload)
        self._db.execute(
            "INSERT INTO graph_versions(id,sequence,kind,created_at,created_by,reason,source_label,source_as_of,"
            "policy_version,issue_count,relation_count,article_count,candidate_count,synthetic,sha256,bytes,file,"
            "graph_db,seed_sha256,content_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                version_id,
                sequence,
                kind,
                utc_iso(self._clock.now()),
                created_by,
                reason,
                source_label,
                source_as_of,
                policy_version,
                stats["issue_count"],
                stats["relation_count"],
                stats["article_count"],
                stats["candidate_count"],
                int(stats["synthetic"]),
                digest,
                len(body),
                filename,
                dumps(graph_db),
                seed_sha256,
                digest,
            ),
        )
        created = self.get(version_id)
        assert created is not None
        return created

    def _activate(
        self, version_id: str, previous: str | None, admin_email: str, reason: str | None, action: str
    ) -> None:
        self._db.execute(
            "INSERT INTO graph_activations(version_id,previous_version_id,at,admin_email,reason,action) VALUES (?,?,?,?,?,?)",
            (version_id, previous, utc_iso(self._clock.now()), admin_email, reason, action),
        )

    def publish(
        self,
        payload: dict[str, Any],
        *,
        admin: Actor,
        reason: str,
        source_label: str,
        policy_version: str | None,
        graph_db: dict[str, Any],
    ) -> tuple[GraphVersion, str | None]:
        """Store ``payload`` as a new immutable version and activate it. 409 when unchanged."""
        digest = hashlib.sha256(canonical(payload)).hexdigest()
        with self._lock, self._db.transaction():
            current = self.active()
            if current is not None and current.sha256 == digest:
                raise ApiError(
                    409,
                    "version_unchanged",
                    "원장 내용이 현재 활성 버전과 같아 새 버전을 만들지 않았습니다.",
                    {"activeVersionId": current.id},
                )
            version = self._store(
                payload,
                kind="ledger",
                created_by=admin.email or admin.id,
                reason=reason,
                source_label=source_label,
                source_as_of=utc_iso(self._clock.now()),
                policy_version=policy_version,
                graph_db=graph_db,
            )
            self._activate(version.id, current.id if current else None, admin.email or admin.id, reason, "publish")
        return version, current.id if current else None

    def activate(self, version_id: str, *, admin: Actor, reason: str) -> tuple[str | None, bool]:
        """(previous active id, idempotent)."""
        with self._lock, self._db.transaction():
            target = self.get(version_id)
            if target is None:
                raise ApiError(404, "graph_version_not_found", "그래프 버전을 찾을 수 없습니다.")
            previous = self.active_id()
            if previous == version_id:
                return previous, True
            self._activate(version_id, previous, admin.email or admin.id, reason, "activate")
            return previous, False
