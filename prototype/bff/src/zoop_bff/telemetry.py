"""Collection of user behaviour events (requirement 74).

The client sends small batches of whitelisted events (``insights_schemas.TelemetryEvent``); this module
stores them under a pseudonymous subject. Time is the server's receive time. Company links are resolved
once, at ingestion, against the graph the user was looking at, so later graph versions cannot rewrite
old statistics. AI questions and onboarding are *not* taken from events: they come from the server's own
chat and member records.
"""

from __future__ import annotations

import json

from .audit import Clock
from .dataset import Dataset
from .errors import ApiError
from .insights_common import RateLimiter, Subject, companies_of, node_kind
from .insights_schemas import MAX_BATCH, TelemetryEvent
from .statedb import StateDb, utc_iso

MAX_BODY_BYTES = 16 * 1024
EVENTS_PER_MINUTE = 240  # per subject
REQUESTS_PER_MINUTE = 60  # per subject


class TelemetryService:
    def __init__(self, db: StateDb, clock: Clock):
        self._db = db
        self._clock = clock
        self._events = RateLimiter(clock, EVENTS_PER_MINUTE, 60)
        self._requests = RateLimiter(clock, REQUESTS_PER_MINUTE, 60)

    def record(self, subject: Subject, events: list[TelemetryEvent], ds: Dataset | None) -> int:
        """Store a validated batch. Over the rate limit the whole batch is refused (429), never half-stored."""
        if not events or len(events) > MAX_BATCH:  # the schema bounds this; kept as a guard for direct callers
            raise ApiError(422, "invalid_batch", f"한 번에 1–{MAX_BATCH}개의 이벤트만 보낼 수 있습니다.")
        if not self._requests.allow(subject.id) or not self._events.allow(subject.id, len(events)):
            raise ApiError(429, "rate_limited", "이벤트를 너무 자주 보내고 있습니다. 잠시 뒤에 다시 보내 주세요.")
        at = utc_iso(self._clock.now())
        rows = [self._row(at, subject, event, ds) for event in events]
        with self._db.transaction() as conn:
            conn.executemany(
                "INSERT INTO telemetry_events(at,subject,subject_kind,type,screen,target_id,target_kind,round_id,view_id,company_ids)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        return len(rows)

    @staticmethod
    def _row(at: str, subject: Subject, event: TelemetryEvent, ds: Dataset | None) -> tuple[object, ...]:
        kind: str | None
        companies: list[str] = []
        if event.type == "graph_node_select":
            kind = node_kind(ds, event.target_id or "")
            companies = companies_of(ds, event.target_id or "") if ds else []
        elif event.type == "graph_edge_select":
            kind = "edge" if ds and event.target_id in ds.edges else "other"
            companies = companies_of(ds, event.target_id or "") if ds else []
        elif event.type == "briefing_issue_open":
            kind = "issue"
            companies = companies_of(ds, event.target_id or "") if ds else []
        elif event.type == "briefing_view":
            kind = "round"
        else:
            kind = None
        return (
            at,
            subject.id,
            subject.kind,
            event.type,
            event.screen,
            event.target_id,
            kind,
            event.round_id or (event.target_id if event.type == "briefing_view" else None),
            event.view_id,
            json.dumps(companies, ensure_ascii=False),
        )
