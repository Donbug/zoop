"""Commute briefing rounds (requirements 26-33, 79, 80): generate, verify, publish, correct, suspend.

A round is (publication date in KST, ``morning`` | ``evening``) scheduled at 07:40 / 18:10 KST. Its data
window ends at the scheduled time and starts at the previous round's scheduled time, a pure calendar
rule that does not depend on whether the previous round was published. The first round the service ever
generates (the *epoch* round, remembered in the state database) has no lower bound, and rounds scheduled
before it are never generated. The published payload is stored once and cannot be updated or deleted
(a SQLite trigger enforces it); corrections and suspensions are separate records laid next to it.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time as clock_time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

from .admin_schemas import (
    AttemptOut,
    BriefingPayload,
    CorrectionOut,
    DataWindow,
    RoundDetail,
    RoundList,
    RoundOut,
    RoundSchedule,
    StageOut,
    StagesOut,
    SuspensionOut,
)
from .admin_usage import UsageService
from .audit import SYSTEM_SCHEDULER, Actor, AuditLog, Clock
from .briefing_market import MarketIndicators
from .briefing_since import compare as compare_with_morning
from .briefing_since import unavailable_reason
from .dataset import Dataset, IssueRec, sort_recent
from .errors import ApiError, SourceUnavailable
from .schemas import (
    BriefingCorrection,
    BriefingItem,
    BriefingMetadata,
    BriefingNotice,
    BriefingReferences,
    BriefingResponse,
    BriefingRoundRef,
    BriefingRoundsResponse,
    BriefingSchedule,
    BriefingSelection,
    BriefingWindow,
    MarketVariables,
    SinceMorning,
    Unavailable,
)
from .sentiment import SentimentService, outlook_input
from .statedb import StateDb, dumps, utc_iso
from .views import SUMMARY_UNAVAILABLE, company_links, meta, mock_meta, source_support_out

if TYPE_CHECKING:
    from .sources import DataProvider

log = logging.getLogger("zoop_bff.briefings")

Edition = Literal["morning", "evening"]
KST = timezone(timedelta(hours=9))
SLOT_TIMES: dict[str, time] = {"morning": time(7, 40), "evening": time(18, 10)}
MAX_ITEMS = 3
GRACE = timedelta(minutes=10)  # later than this after the scheduled time counts as delayed
CATCH_UP = timedelta(hours=6)  # a restarted scheduler only fills a missed round this recent
GENERATED_BY = "bff-rule-v1"
FAILURE_NOTICE = "이번 회차는 아직 발행하지 못했어요. 잠시 뒤에 다시 확인해 주세요."
MARKET_SUMMARY_UNAVAILABLE = "시장 요약 생산자(PoC 범위 밖)가 아직 없습니다."
MARKET_NOT_STORED = "이 회차에는 시장 지표가 저장되지 않았어요."
MARKET_NOT_SHOWN = "발행된 회차에서만 시장 지표를 볼 수 있어요."
_ID = re.compile(r"^brf-(\d{4}-\d{2}-\d{2})-(morning|evening)$")
SCHEDULE_LABEL = {"morning": "07:40", "evening": "18:10"}


# ---------------------------------------------------------------- calendar


def round_id(day: date, edition: str) -> str:
    return f"brf-{day.isoformat()}-{edition}"


def parse_round_id(value: str) -> tuple[date, Edition] | None:
    match = _ID.match(value)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1)), match.group(2)  # type: ignore[return-value]
    except ValueError:
        return None


def scheduled_at(day: date, edition: str) -> datetime:
    return datetime.combine(day, SLOT_TIMES[edition], tzinfo=KST)


def previous_slot(day: date, edition: str) -> tuple[date, Edition]:
    return (day - timedelta(days=1), "evening") if edition == "morning" else (day, "morning")


def latest_started(now: datetime) -> tuple[date, Edition]:
    local = now.astimezone(KST)
    if local >= scheduled_at(local.date(), "evening"):
        return local.date(), "evening"
    if local >= scheduled_at(local.date(), "morning"):
        return local.date(), "morning"
    return local.date() - timedelta(days=1), "evening"


def _published_at(value: str | None) -> datetime | None:
    """Article publication time; a value without an offset is read as KST."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def _kst(moment: datetime) -> str:
    return moment.astimezone(KST).isoformat(timespec="seconds")


_HAS_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _reported_at(value: str | None) -> str | None:
    """The newest article's time in KST for a round item; only its date when the article carries no time (never midnight)."""
    at = _published_at(value)
    if at is None or value is None:
        return None
    return _kst(at) if _HAS_TIME.match(value) else at.astimezone(KST).date().isoformat()


@dataclass
class Row:
    id: str
    date: date
    edition: Edition
    status: str
    data: dict[str, Any]
    payload: dict[str, Any] | None

    @property
    def scheduled(self) -> datetime:
        return scheduled_at(self.date, self.edition)


def _row(r: Any) -> Row:
    parsed = parse_round_id(r["id"])
    assert parsed is not None
    return Row(
        id=r["id"],
        date=parsed[0],
        edition=parsed[1],
        status=r["status"],
        data=json.loads(r["data"]),
        payload=json.loads(r["payload"]) if r["payload"] else None,
    )


class BriefingService:
    def __init__(
        self,
        *,
        db: StateDb,
        clock: Clock,
        audit: AuditLog,
        usage: UsageService,
        provider: DataProvider,
        indicators: MarketIndicators,
        sentiment: SentimentService | None = None,
    ):
        self._db = db
        self._clock = clock
        self._audit = audit
        self._usage = usage
        self._provider = provider
        self._indicators = indicators
        self._sentiment = sentiment or SentimentService(db, clock, usage)
        self._gen = threading.Lock()

    # ---------------------------------------------------------------- storage
    def _get(self, rid: str) -> Row | None:
        r = self._db.one("SELECT * FROM briefing_rounds WHERE id=?", (rid,))
        return _row(r) if r else None

    def epoch(self) -> str | None:
        r = self._db.one("SELECT value FROM meta WHERE key='briefing_epoch'")
        return r["value"] if r else None

    def _corrections(self, rid: str) -> list[Any]:
        return self._db.query("SELECT * FROM briefing_corrections WHERE round_id=? ORDER BY seq", (rid,))

    def record(self, rid: str) -> Row | None:
        """The stored round with its immutable payload (``None`` when it was never generated)."""
        return self._get(rid)

    def correction_count(self, rid: str) -> int:
        return int(self._db.one("SELECT COUNT(*) AS n FROM briefing_corrections WHERE round_id=?", (rid,))["n"])

    # ---------------------------------------------------------------- windows
    def _window(self, day: date, edition: Edition, row: Row | None, now: datetime) -> dict[str, Any]:
        if row is not None and row.data.get("window"):
            return row.data["window"]
        end = scheduled_at(day, edition)
        prev_day, prev_edition = previous_slot(day, edition)
        epoch = self.epoch()
        rid = round_id(day, edition)
        # With no epoch yet, the round that would start the service is the latest one already due.
        open_start = rid == epoch if epoch else rid == round_id(*latest_started(now))
        return {
            "start": None if open_start else _kst(scheduled_at(prev_day, prev_edition)),
            "end": _kst(end),
            "open_start": open_start,
        }

    # ---------------------------------------------------------------- admin views
    def _blocked(self, day: date, edition: Edition, row: Row | None, now: datetime) -> str | None:
        sched = scheduled_at(day, edition)
        if row is not None:
            if row.status in ("published", "suspended"):
                return "발행된 회차는 교체할 수 없습니다."
            if row.status in ("generating", "verifying"):
                return "생성 중인 회차입니다."
        if now < sched:
            return "예정 시각 전의 회차입니다."
        epoch = self.epoch()
        rid = round_id(day, edition)
        if epoch:
            first = parse_round_id(epoch)
            if first and sched < scheduled_at(*first):
                return "서비스의 첫 회차보다 앞선 회차는 만들지 않습니다."
        elif rid != round_id(*latest_started(now)):
            return "서비스의 첫 회차는 가장 최근에 시작된 회차부터 만듭니다."
        return None

    def round_out(self, day: date, edition: Edition, *, row: Row | None = None, now: datetime | None = None) -> RoundOut:
        now = now or self._clock.now()
        rid = round_id(day, edition)
        row = row if row is not None else self._get(rid)
        sched = scheduled_at(day, edition)
        data = row.data if row else {}
        window = self._window(day, edition, row, now)
        if row is None:
            status = "scheduled" if now < sched else "missing"
        else:
            status = row.status
        blocked = self._blocked(day, edition, row, now)
        reprocessable = status in ("missing", "failed") and blocked is None
        generated_at = data.get("generated_at")
        delayed = (
            now > sched + GRACE if row is None and now >= sched
            else bool(row and generated_at and _parse(generated_at) > sched + GRACE)
        )
        suspension = data.get("suspension")
        return RoundOut(
            id=rid,
            date=day.isoformat(),
            edition=edition,
            scheduled_at=_kst(sched),
            data_window=DataWindow(start=window["start"], end=window["end"], open_start=bool(window["open_start"])),
            status=status,  # type: ignore[arg-type]
            stages=self._stages(row),
            failure_reason=data.get("failure_reason") if status == "failed" else None,
            generated_at=generated_at,
            published_at=data.get("published_at"),
            graph_version=data.get("graph_version"),
            review_revision=data.get("review_revision"),
            item_count=data.get("item_count"),
            trigger=data.get("trigger"),
            attempts=int(data.get("attempts") or 0),
            delayed=delayed,
            correction_count=self.correction_count(rid),
            suspension=SuspensionOut(**suspension) if suspension else None,
            reprocessable=reprocessable,
            blocked_reason=blocked if status in ("scheduled", "missing", "failed") else None,
        )

    @staticmethod
    def _stages(row: Row | None) -> StagesOut:
        pending = StageOut(status="pending", at=None)
        if row is None:
            return StagesOut(generate=pending, verify=pending, publish=pending)
        s = row.data.get("stages") or {}

        def stage(name: str) -> StageOut:
            raw = s.get(name)
            return StageOut(status=raw["status"], at=raw.get("at")) if raw else pending

        return StagesOut(generate=stage("generate"), verify=stage("verify"), publish=stage("publish"))

    def rounds(self, from_: date | None, to: date | None) -> RoundList:
        now = self._clock.now()
        today = now.astimezone(KST).date()
        end = to or today
        start = from_ or (end - timedelta(days=13))
        if start > end:
            raise ApiError(422, "invalid_range", "from은 to보다 늦을 수 없습니다.")
        if (end - start).days > 92:
            raise ApiError(422, "invalid_range", "조회 기간은 93일을 넘을 수 없습니다.")
        epoch = self.epoch()
        first = parse_round_id(epoch) if epoch else None
        floor = scheduled_at(*first) if first else scheduled_at(*latest_started(now))
        items: list[RoundOut] = []
        day = end
        while day >= start:
            for edition in ("evening", "morning"):
                sched = scheduled_at(day, edition)  # type: ignore[arg-type]
                row = self._get(round_id(day, edition))
                if row is None and (sched < floor or (sched > now and day != today)):
                    continue  # before the service's first round, or an upcoming round beyond today
                items.append(self.round_out(day, edition, row=row, now=now))  # type: ignore[arg-type]
            day -= timedelta(days=1)
        return RoundList(items=items, schedule=RoundSchedule(morning="07:40", evening="18:10", timezone="Asia/Seoul"))

    def detail(self, rid: str) -> RoundDetail:
        parsed = parse_round_id(rid)
        if parsed is None:
            raise ApiError(404, "briefing_round_not_found", "브리핑 회차를 찾을 수 없습니다.")
        row = self._get(rid)
        base = self.round_out(parsed[0], parsed[1], row=row)
        attempts = self._db.query("SELECT * FROM briefing_attempts WHERE round_id=? ORDER BY n", (rid,))
        return RoundDetail(
            **base.model_dump(),
            published=BriefingPayload.model_validate(row.payload) if row and row.payload else None,
            corrections=[self._correction_out(c) for c in self._corrections(rid)],
            attempts_log=[
                AttemptOut(
                    n=a["n"],
                    trigger=a["trigger"],
                    started_at=a["started_at"],
                    finished_at=a["finished_at"],
                    status=a["status"],
                    failure_reason=a["failure_reason"],
                    admin_email=a["admin_email"],
                )
                for a in attempts
            ],
        )

    @staticmethod
    def _correction_out(c: Any) -> CorrectionOut:
        return CorrectionOut(
            id=c["id"],
            seq=c["seq"],
            event_id=c["event_id"],
            original=c["original"],
            corrected=c["corrected"],
            reason=c["reason"],
            created_at=c["created_at"],
            admin_email=c["admin_email"],
        )

    def sentiment_preview(self, rid: str) -> dict[str, Any]:
        """Selection only: no state changes, market reads or model calls (CLI dry-run)."""
        parsed = parse_round_id(rid)
        if parsed is None:
            raise ValueError("invalid briefing round id")
        row = self._get(rid)
        now = self._clock.now()
        reason = self._blocked(*parsed, row, now)
        if reason:
            return {"id": rid, "eligible": False, "items": (row.payload or {}).get("items", []) if row else [], "reason": reason}
        window = self._window(*parsed, row, now)
        items, _ = self._select(self._provider.get(), window)
        return {"id": rid, "eligible": True, "items": items, "reason": None}

    # ---------------------------------------------------------------- generation
    def reprocess(self, rid: str, admin: Actor, reason: str) -> RoundOut:
        parsed = parse_round_id(rid)
        if parsed is None:
            raise ApiError(404, "briefing_round_not_found", "브리핑 회차를 찾을 수 없습니다.")
        try:
            self.generate(parsed[0], parsed[1], trigger="admin", actor=admin, blocking=False)
        except ApiError as exc:
            self._audit.record(
                admin, "briefing.reprocess", "briefing-round", rid, reason=reason, outcome="denied", detail={"code": exc.code}
            )
            raise
        self._audit.record(admin, "briefing.reprocess", "briefing-round", rid, reason=reason)
        return self.round_out(parsed[0], parsed[1])

    def generate(
        self, day: date, edition: Edition, *, trigger: Literal["scheduler", "admin"], actor: Actor, blocking: bool
    ) -> None:
        if not self._gen.acquire(blocking=blocking):
            raise ApiError(409, "round_in_progress", "다른 회차를 생성하고 있습니다. 잠시 뒤에 다시 시도해 주세요.")
        try:
            self._generate(day, edition, trigger, actor)
        finally:
            self._gen.release()

    def _generate(self, day: date, edition: Edition, trigger: str, actor: Actor) -> None:
        now = self._clock.now()
        rid = round_id(day, edition)
        row = self._get(rid)
        if row is not None and row.status in ("published", "suspended"):
            raise ApiError(409, "already_published", "이미 발행된 회차는 다시 만들거나 교체할 수 없습니다.", {"publishedAt": row.data.get("published_at")})
        if row is not None and row.status in ("generating", "verifying"):
            raise ApiError(409, "round_in_progress", "이 회차를 생성하고 있습니다.")
        if now < scheduled_at(day, edition):
            raise ApiError(409, "round_not_due", "예정 시각 전의 회차는 만들 수 없습니다.", {"scheduledAt": _kst(scheduled_at(day, edition))})
        blocked = self._blocked(day, edition, row, now)
        if blocked:
            raise ApiError(409, "round_not_allowed", blocked)

        started = utc_iso(now)
        attempts = int((row.data if row else {}).get("attempts") or 0) + 1
        window = self._window(day, edition, row, now)
        data: dict[str, Any] = {
            "window": window,
            "attempts": attempts,
            "trigger": trigger,
            "stages": {"generate": {"status": "running", "at": started}},
        }
        with self._db.transaction() as conn:
            if self.epoch() is None:
                conn.execute("INSERT INTO meta(key,value) VALUES ('briefing_epoch', ?)", (rid,))
            conn.execute(
                "INSERT INTO briefing_rounds(id,date,edition,status,data,payload,updated_at) VALUES (?,?,?,?,?,NULL,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, data=excluded.data, updated_at=excluded.updated_at",
                (rid, day.isoformat(), edition, "generating", dumps(data), started),
            )
            conn.execute(
                "INSERT INTO briefing_attempts(round_id,n,trigger,admin_email,started_at,status) VALUES (?,?,?,?,?,'running')",
                (rid, attempts, trigger, actor.email if trigger == "admin" else None, started),
            )
        t0 = clock_time.perf_counter()
        failure: tuple[str, str, str] | None = None  # (stage, code, reason)
        published: dict[str, Any] | None = None
        try:
            try:
                stamp = self._provider.source.stamp()
                dataset = self._provider.get()
                items, selected_from = self._select(dataset, window)
            except SourceUnavailable as exc:
                failure = ("generate", "data_unavailable", f"그래프 데이터를 읽지 못했습니다: {exc.message}")
            else:
                data["stages"] = {
                    "generate": {"status": "done", "at": utc_iso(self._clock.now())},
                    "verify": {"status": "running", "at": utc_iso(self._clock.now())},
                }
                data["generated_at"] = utc_iso(self._clock.now())
                self._update(rid, "verifying", data)
                problems = self._verify(stamp, window, items)
                if problems:
                    failure = ("verify", "verification_failed", "검증 실패: " + "; ".join(problems))
                else:
                    # Fixed now, at generation: the stored values are what the round shows from then on (FS035).
                    market = self._indicators.collect(day, edition, scheduled_at(day, edition), now=self._clock.now())
                    published = self._payload(rid, day, edition, dataset, stamp, window, items, selected_from, data, market)
        except Exception as exc:  # a bug must end as a visible failed round, never a stuck "generating"
            log.exception("briefing generation crashed for %s", rid)
            failure = ("generate", "generation_error", f"생성 중 예기치 않은 오류({type(exc).__name__})")

        finished = utc_iso(self._clock.now())
        duration_ms = (clock_time.perf_counter() - t0) * 1000
        if failure is not None:
            stage, code, reason = failure
            stages = data.get("stages", {})
            stages[stage] = {"status": "failed", "at": finished}
            for later in ("verify", "publish"):
                if later not in stages or (stage == "generate" and later == "verify"):
                    stages[later] = {"status": "skipped", "at": None}
            data.update(stages=stages, failure_reason=reason, failure_code=code)
            self._finish_attempt(rid, attempts, "failed", reason)
            self._update(rid, "failed", data)
            self._usage.record("briefing", False, duration_ms, code=code, message=reason)
            self._audit.record(
                actor if trigger == "admin" else SYSTEM_SCHEDULER,
                "briefing.generate",
                "briefing-round",
                rid,
                outcome="failed",
                detail={"trigger": trigger, "attempt": attempts, "failureCode": code, "reason": reason},
            )
            return
        assert published is not None
        data["stages"] = {
            "generate": {"status": "done", "at": data["generated_at"]},
            "verify": {"status": "done", "at": data["generated_at"]},
            "publish": {"status": "done", "at": finished},
        }
        data.update(
            published_at=finished,
            graph_version=published["graphVersion"],
            review_revision=published["reviewRevision"],
            item_count=len(published["items"]),
        )
        data.pop("failure_reason", None)
        data.pop("failure_code", None)
        self._finish_attempt(rid, attempts, "published", None)
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE briefing_rounds SET status='published', payload=?, data=?, updated_at=? WHERE id=? AND payload IS NULL",
                (dumps(published), dumps(data), finished, rid),
            )
        self._usage.record("briefing", True, duration_ms)
        self._audit.record(
            actor if trigger == "admin" else SYSTEM_SCHEDULER,
            "briefing.generate",
            "briefing-round",
            rid,
            detail={
                "trigger": trigger,
                "attempt": attempts,
                "itemCount": len(published["items"]),
                "graphVersion": published["graphVersion"],
            },
        )

    def _update(self, rid: str, status: str, data: dict[str, Any]) -> None:
        """Generation bookkeeping: only a round that has no published payload yet may change."""
        self._db.execute(
            "UPDATE briefing_rounds SET status=?, data=?, updated_at=? WHERE id=? AND payload IS NULL",
            (status, dumps(data), utc_iso(self._clock.now()), rid),
        )

    def _set_state(self, rid: str, status: str, data: dict[str, Any]) -> None:
        """Suspension bookkeeping on a published round; the payload column is never part of the SET."""
        self._db.execute(
            "UPDATE briefing_rounds SET status=?, data=?, updated_at=? WHERE id=? AND payload IS NOT NULL",
            (status, dumps(data), utc_iso(self._clock.now()), rid),
        )

    def _finish_attempt(self, rid: str, n: int, status: str, reason: str | None) -> None:
        self._db.execute(
            "UPDATE briefing_attempts SET finished_at=?, status=?, failure_reason=? WHERE round_id=? AND n=?",
            (utc_iso(self._clock.now()), status, reason, rid, n),
        )

    def _select(self, ds: Dataset, window: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        """Up to MAX_ITEMS approved issues reported inside the window, newest event first (never padded)."""
        start = _published_at(window["start"]) if window["start"] else None
        end = _published_at(window["end"])
        assert end is not None
        inside: list[IssueRec] = []
        for issue in ds.issues.values():
            at = _published_at(issue.latest_published_at)
            if at is None or not issue.evidence_ids:
                continue
            if (start is None or at > start) and at <= end:
                inside.append(issue)
        ranked = sort_recent(inside)[:MAX_ITEMS]
        items = []
        for rank, issue in enumerate(ranked, start=1):
            assert issue.latest_published_at is not None  # only issues with a report time were selected
            item = BriefingItem(
                event_id=issue.id,
                title=issue.title,
                event_time=issue.event_time,
                time_precision=issue.time_precision,
                companies=company_links(ds, issue),
                evidence_count=len(issue.evidence_ids),
                source_support=source_support_out(issue),
                matched_company_ids=[],
                rank=rank,
                reason=f"이번 회차 데이터 창 안의 승인 이슈 {len(inside)}건 중 사건 시각이 {rank}번째로 최근입니다 · 근거 {len(issue.evidence_ids)}건",
                evidence_ids=list(issue.evidence_ids),
                summary=Unavailable(reason=SUMMARY_UNAVAILABLE),
                reported_at=_reported_at(issue.latest_published_at),
            )
            items.append(item.model_dump(by_alias=True, mode="json"))
        return items, len(inside)

    def _verify(self, stamp: object, window: dict[str, Any], items: list[dict[str, Any]]) -> list[str]:
        """Only checks that can really be made: references exist in the same graph version, rules hold."""
        problems: list[str] = []
        if len(items) > MAX_ITEMS:
            problems.append(f"핵심 이슈가 {MAX_ITEMS}개를 넘음({len(items)}개)")
        try:
            current = self._provider.source.stamp()
            ds = self._provider.get()
        except SourceUnavailable as exc:
            return [f"그래프 데이터를 다시 읽지 못함({exc.message})"]
        if current != stamp:
            problems.append("생성 중 그래프 버전 또는 검수 기록이 바뀜")
        start = _published_at(window["start"]) if window["start"] else None
        end = _published_at(window["end"])
        for item in items:
            issue = ds.issues.get(item["eventId"])
            if issue is None:
                problems.append(f"이슈 {item['eventId']}가 그래프 버전에 없음")
                continue
            at = _published_at(issue.latest_published_at)
            if at is None or (start is not None and at <= start) or (end is not None and at > end):
                problems.append(f"이슈 {item['eventId']}가 데이터 창 밖")
            for evidence_id in item["evidenceIds"]:
                evidence = ds.evidence.get(evidence_id)
                if evidence is None or item["eventId"] not in ds.evidence_issues.get(evidence_id, ()):
                    problems.append(f"근거 {evidence_id}가 이슈 {item['eventId']}에 없음")
                elif evidence.quote_verified is False:
                    problems.append(f"근거 {evidence_id}의 인용이 원문과 맞지 않음")
            for company in item["companies"]:
                if company["id"] not in ds.companies:
                    problems.append(f"기업 {company['id']}가 그래프 버전에 없음")
        return problems

    def _payload(
        self,
        rid: str,
        day: date,
        edition: Edition,
        ds: Dataset,
        stamp: object,
        window: dict[str, Any],
        items: list[dict[str, Any]],
        selected_from: int,
        data: dict[str, Any],
        market: MarketVariables,
    ) -> dict[str, Any]:
        graph_version, revision, (_, rule_revision) = stamp  # type: ignore[misc]
        companies = list(dict.fromkeys(c["id"] for item in items for c in item["companies"]))
        self._sentiment.freeze_documents(ds, items)
        outlook = self._sentiment.judge_outlook(outlook_input(rid, _kst(scheduled_at(day, edition)), items, market.model_dump(by_alias=True, mode="json")))
        evidence = list(dict.fromkeys(e for item in items for e in item["evidenceIds"]))
        metadata = BriefingMetadata(
            **meta(ds, GENERATED_BY).model_dump(),
            schedule=BriefingSchedule(morning="07:40", evening="18:10", confirmed=True),
            selection=BriefingSelection(basis="market", reason="recent_in_window"),
        )
        return {
            "id": rid,
            "date": day.isoformat(),
            "edition": edition,
            "scheduledAt": _kst(scheduled_at(day, edition)),
            "generatedAt": data["generated_at"],
            "dataWindow": {"start": window["start"], "end": window["end"], "openStart": bool(window["open_start"])},
            "graphVersion": graph_version,
            "reviewRevision": revision,
            "ruleRevision": rule_revision,
            "items": items,
            "outlook": outlook.model_dump(by_alias=True, mode="json") if outlook else None,
            "references": {"eventIds": [i["eventId"] for i in items], "evidenceIds": evidence, "companyIds": companies},
            "emptyReason": None if items else "no_issues_in_window",
            "selectedFrom": selected_from,
            "marketVariables": market.model_dump(by_alias=True, mode="json"),
            "metadata": metadata.model_dump(by_alias=True, mode="json"),
        }

    # ---------------------------------------------------------------- scheduler + recovery
    def tick(self) -> list[str]:
        """One scheduler pass: generate the rounds that fell due and have no record (never retries a failure)."""
        now = self._clock.now()
        made: list[str] = []
        day, edition = latest_started(now)
        slots: list[tuple[date, Edition]] = []
        for _ in range(4):  # the rounds of the last two days that are still inside the catch-up span
            if now - scheduled_at(day, edition) <= CATCH_UP:
                slots.append((day, edition))
            day, edition = previous_slot(day, edition)
        for day, edition in reversed(slots):
            rid = round_id(day, edition)
            if self._get(rid) is not None:
                continue
            try:
                self.generate(day, edition, trigger="scheduler", actor=SYSTEM_SCHEDULER, blocking=True)
                made.append(rid)
            except ApiError as exc:
                log.info("scheduler skipped %s: %s", rid, exc.code)
        return made

    def recover(self) -> int:
        """Rounds that were generating when the process ended can never finish: settle them as failed."""
        recovered = 0
        for r in self._db.query("SELECT * FROM briefing_rounds WHERE status IN ('generating','verifying')"):
            row = _row(r)
            stage = "verify" if row.status == "verifying" else "generate"
            reason = "BFF가 다시 시작되어 생성이 중단되었습니다."
            stages = row.data.get("stages") or {}
            stages[stage] = {"status": "failed", "at": utc_iso(self._clock.now())}
            for later in ("verify", "publish"):
                stages.setdefault(later, {"status": "skipped", "at": None})
            row.data.update(stages=stages, failure_reason=reason, failure_code="interrupted_by_restart")
            self._finish_attempt(row.id, int(row.data.get("attempts") or 1), "failed", reason)
            self._update(row.id, "failed", row.data)
            self._audit.record(
                SYSTEM_SCHEDULER,
                "briefing.generate",
                "briefing-round",
                row.id,
                outcome="failed",
                detail={"failureCode": "interrupted_by_restart"},
            )
            recovered += 1
        return recovered

    # ---------------------------------------------------------------- corrections + suspension
    def add_correction(self, rid: str, admin: Actor, *, event_id: str | None, corrected: str, reason: str) -> CorrectionOut:
        row = self._get(rid)
        if row is None or row.payload is None:
            raise ApiError(409 if parse_round_id(rid) else 404, "not_published", "발행되지 않은 회차에는 정정을 등록할 수 없습니다.")
        original: str | None = None
        if event_id is not None:
            item = next((i for i in row.payload["items"] if i["eventId"] == event_id), None)
            if item is None:
                raise ApiError(422, "unknown_item", "이 회차에 없는 핵심 이슈입니다.", {"eventId": event_id})
            original = item["title"]  # the text as published, preserved apart from the correction
        with self._db.transaction() as conn:
            seq = int(conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM briefing_corrections WHERE round_id=?", (rid,)).fetchone()[0])
            cursor = conn.execute(
                "INSERT INTO briefing_corrections(round_id,seq,event_id,original,corrected,reason,created_at,admin_email) VALUES (?,?,?,?,?,?,?,?)",
                (rid, seq, event_id, original, corrected, reason, utc_iso(self._clock.now()), admin.email or admin.id),
            )
            created = conn.execute("SELECT * FROM briefing_corrections WHERE id=?", (cursor.lastrowid,)).fetchone()
        self._audit.record(
            admin,
            "briefing.correct",
            "briefing-round",
            rid,
            reason=reason,
            detail={"eventId": event_id, "seq": seq, "original": original, "corrected": corrected},
        )
        return self._correction_out(created)

    def set_suspension(self, rid: str, admin: Actor, *, action: Literal["suspend", "resume"], reason: str) -> RoundOut:
        parsed = parse_round_id(rid)
        row = self._get(rid) if parsed else None
        if parsed is None or row is None or row.payload is None:
            raise ApiError(409 if parsed else 404, "not_published", "발행된 회차만 제공을 중단하거나 재개할 수 있습니다.")
        now = utc_iso(self._clock.now())
        if action == "suspend" and row.status != "suspended":
            row.data["suspension"] = {"reason": reason, "at": now, "admin_email": admin.email or admin.id}
            self._set_state(rid, "suspended", row.data)
            self._audit.record(admin, "briefing.suspend", "briefing-round", rid, reason=reason)
        elif action == "resume" and row.status == "suspended":
            row.data["suspension"] = None
            self._set_state(rid, "published", row.data)
            self._audit.record(admin, "briefing.resume", "briefing-round", rid, reason=reason)
        return self.round_out(parsed[0], parsed[1])

    # ---------------------------------------------------------------- user view
    def public_rounds(self, limit: int) -> BriefingRoundsResponse:
        rows = self._db.query(
            "SELECT * FROM briefing_rounds WHERE status IN ('published','suspended') ORDER BY date DESC, edition ASC LIMIT ?",
            (limit,),
        )
        # 'evening' sorts before 'morning' alphabetically, so ASC on edition lists the later round first.
        return BriefingRoundsResponse(
            items=[
                BriefingRoundRef(
                    id=r["id"],
                    date=r["date"],
                    edition=r["edition"],
                    status=r["status"],
                    published_at=json.loads(r["data"]).get("published_at"),
                )
                for r in rows
            ]
        )

    def public(self, day: date | None, edition: Edition | None) -> BriefingResponse:
        now = self._clock.now()
        if day is None and edition is None:
            day, edition = latest_started(now)
        elif day is None:
            started_day, started_edition = latest_started(now)
            day = started_day
            if edition != started_edition and not (edition == "morning" and started_edition == "evening"):
                day = started_day - timedelta(days=1)  # that edition has not started today
        elif edition is None:
            edition = "evening" if now >= scheduled_at(day, "evening") else "morning"
        assert day is not None and edition is not None
        rid = round_id(day, edition)
        sched = scheduled_at(day, edition)
        row = self._get(rid)
        window = self._window(day, edition, row, now)
        base = {
            "id": rid,
            "date": day.isoformat(),
            "edition": edition,
            "scheduled_at": _kst(sched),
            "market_summary": Unavailable(reason=MARKET_SUMMARY_UNAVAILABLE),
            "market_variables": Unavailable(reason=MARKET_NOT_SHOWN),
            "since_morning": None,
            "references": BriefingReferences(event_ids=[], evidence_ids=[], company_ids=[]),
        }

        def metadata(payload: dict[str, Any] | None) -> BriefingMetadata:
            if payload is not None:
                return BriefingMetadata.model_validate(payload["metadata"])
            return BriefingMetadata(
                **mock_meta(GENERATED_BY).model_dump(),
                schedule=BriefingSchedule(morning="07:40", evening="18:10", confirmed=True),
                selection=BriefingSelection(basis="market", reason="recent_in_window"),
            )

        def empty(status: str, notice: BriefingNotice) -> BriefingResponse:
            return BriefingResponse(
                status=status,  # type: ignore[arg-type]
                published_at=None,
                generated_at=None,
                data_window=BriefingWindow(start=window["start"], end=window["end"], open_start=bool(window["open_start"])),
                data_as_of=None,
                graph_version=None,
                items=[],
                empty_reason=None,
                corrections=[],
                notice=notice,
                metadata=metadata(None),
                **base,
            )

        if row is None:
            message = (
                f"{SCHEDULE_LABEL[edition]}에 발행할 예정이에요."
                if now < sched
                else "아직 발행 전이에요. 준비되는 대로 보여드릴게요."
            )
            return empty("not_ready", BriefingNotice(kind="not_ready", message=message, reason=None, at=None))
        if row.status in ("generating", "verifying"):
            return empty("generating", BriefingNotice(kind="not_ready", message="브리핑을 만드는 중이에요.", reason=None, at=None))
        if row.status == "failed":
            failed_at = next((s["at"] for s in (row.data.get("stages") or {}).values() if s.get("status") == "failed"), None)
            return empty("failed", BriefingNotice(kind="failed", message=FAILURE_NOTICE, reason=None, at=failed_at))
        assert row.payload is not None
        payload = row.payload
        corrections = [
            BriefingCorrection(
                id=c["id"],
                event_id=c["event_id"],
                original=c["original"],
                corrected=c["corrected"],
                reason=c["reason"],
                created_at=c["created_at"],
            )
            for c in self._corrections(rid)
        ]
        shown = {
            **base,
            "published_at": row.data.get("published_at"),
            "generated_at": payload.get("generatedAt"),
            "data_window": BriefingWindow(**{"start": payload["dataWindow"]["start"], "end": payload["dataWindow"]["end"], "open_start": payload["dataWindow"]["openStart"]}),
            "data_as_of": payload["dataWindow"]["end"],
            "graph_version": payload["graphVersion"],
            "corrections": corrections,
            "metadata": metadata(payload),
        }
        if row.status == "suspended":
            suspension = row.data["suspension"]
            return BriefingResponse(
                status="suspended",
                items=[],
                empty_reason=None,
                notice=BriefingNotice(kind="suspended", message="이 회차는 제공을 잠시 중단했어요.", reason=suspension["reason"], at=suspension["at"]),
                **shown,
            )
        shown["references"] = BriefingReferences(
            event_ids=payload["references"]["eventIds"],
            evidence_ids=payload["references"]["evidenceIds"],
            company_ids=payload["references"]["companyIds"],
        )
        shown["market_variables"] = self._stored_market(payload)
        shown["since_morning"] = self._since_morning(day, edition, payload)
        shown["outlook"] = payload.get("outlook")
        return BriefingResponse(
            status="published",
            items=[BriefingItem.model_validate(i) for i in payload["items"]],
            empty_reason=payload["emptyReason"],
            notice=None,
            **shown,
        )

    @staticmethod
    def _stored_market(payload: dict[str, Any]) -> MarketVariables | Unavailable:
        """The indicators stored with the round; rounds published before they were collected say so."""
        raw = payload.get("marketVariables")
        return MarketVariables.model_validate(raw) if raw else Unavailable(reason=MARKET_NOT_STORED)

    def _since_morning(self, day: date, edition: Edition, payload: dict[str, Any]) -> SinceMorning | Unavailable | None:
        """Evening rounds only: the key issues compared with the same day's published morning round."""
        if edition != "evening":
            return None
        morning = self._get(round_id(day, "morning"))
        reason = unavailable_reason(morning.status if morning else None)
        if reason is not None:
            return Unavailable(reason=reason)
        assert morning is not None and morning.payload is not None  # published rounds always carry their payload
        return compare_with_morning(
            morning_id=morning.id,
            morning_published_at=morning.data.get("published_at"),
            morning=morning.payload,
            evening_items=payload["items"],
        )

    def count_view(self) -> None:
        self._usage.briefing_views += 1

    # ---------------------------------------------------------------- dashboard
    def latest_rounds(self, count: int = 4) -> list[RoundOut]:
        """The most recent rounds that have started (published or not), newest first."""
        now = self._clock.now()
        epoch = parse_round_id(self.epoch() or "")
        floor = scheduled_at(*epoch) if epoch else None
        day, edition = latest_started(now)
        out: list[RoundOut] = []
        while len(out) < count:
            row = self._get(round_id(day, edition))
            if row is None and floor is not None and scheduled_at(day, edition) < floor:
                break
            out.append(self.round_out(day, edition, row=row, now=now))
            if floor is None and row is None:
                break  # the service has no first round yet: only the latest due round is a candidate
            day, edition = previous_slot(day, edition)
        return out


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)
