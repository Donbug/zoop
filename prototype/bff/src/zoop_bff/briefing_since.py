"""What changed in an evening round since the same day's morning round (screen plan M-BRF-01).

Both rounds are published and immutable, so the comparison is a pure function of two stored payloads and gives the same
answer whenever it is read. Issues are matched by issue id: *new* = not among the morning round's key issues,
*continuing* = in both rounds, *dropped* = only in the morning round. Windows tile the calendar, so an issue is in both
rounds only when evidence for it arrived after the morning round's cut-off. The list runs oldest first by the time the
issue's newest article was published (``reportedAt``; an article with only a date sorts after the timed ones of that
day); rounds published before ``reportedAt`` was stored keep their rank order, after the dated ones.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .schemas import SinceMorning, SinceMorningItem

NO_MORNING_ROUND = "같은 날 출근 브리핑이 없어요."
MORNING_NOT_PUBLISHED = "출근 브리핑이 발행되지 않아서 비교할 수 없어요."
MORNING_SUSPENDED = "출근 브리핑이 제공 중단 상태라서 비교할 수 없어요."


def unavailable_reason(morning_status: str | None) -> str | None:
    """Why the comparison cannot be made for a morning round in this state (``None`` = it can)."""
    if morning_status is None:
        return NO_MORNING_ROUND
    if morning_status == "published":
        return None
    if morning_status == "suspended":
        return MORNING_SUSPENDED
    return MORNING_NOT_PUBLISHED


def _order(item: SinceMorningItem) -> tuple[bool, str, bool, float, int]:
    """Oldest report first. On one day, items with a time come (by time) before items that only know the date; items
    with no stored report time come last, in rank order."""
    rank = item.rank if item.rank is not None else (item.morning_rank or 0)
    if item.reported_at is None:
        return (True, "", False, 0.0, rank)
    date_only = len(item.reported_at) == 10
    stamp = 0.0 if date_only else datetime.fromisoformat(item.reported_at).timestamp()
    return (False, item.reported_at[:10], date_only, stamp, rank)


def _entry(item: dict[str, Any], change: str, earlier: dict[str, Any] | None) -> SinceMorningItem:
    """``item`` is this round's issue (new, continuing) or, for ``dropped``, the morning round's."""
    dropped = change == "dropped"
    return SinceMorningItem(
        event_id=item["eventId"],
        title=item["title"],
        event_time=item["eventTime"],
        time_precision=item["timePrecision"],
        reported_at=item.get("reportedAt"),
        company_names=[c["name"] for c in item.get("companies", [])],
        change=change,  # type: ignore[arg-type]
        rank=None if dropped else item["rank"],
        morning_rank=item["rank"] if dropped else (earlier["rank"] if earlier else None),
        evidence_count=None if dropped else item["evidenceCount"],
        morning_evidence_count=item["evidenceCount"] if dropped else (earlier["evidenceCount"] if earlier else None),
    )


def compare(
    *, morning_id: str, morning_published_at: str | None, morning: dict[str, Any], evening_items: list[dict[str, Any]]
) -> SinceMorning:
    """``morning`` and ``evening_items`` are stored payload data (camelCase keys)."""
    earlier = {i["eventId"]: i for i in morning["items"]}
    now_ids = {i["eventId"] for i in evening_items}
    out = [
        _entry(item, "continuing" if item["eventId"] in earlier else "new", earlier.get(item["eventId"]))
        for item in evening_items
    ]
    out += [_entry(item, "dropped", None) for item in morning["items"] if item["eventId"] not in now_ids]
    out.sort(key=_order)
    return SinceMorning(
        morning_round_id=morning_id,
        morning_published_at=morning_published_at,
        morning_data_as_of=morning["dataWindow"]["end"],
        items=out,
    )
