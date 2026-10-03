"""Market indicators of a briefing round (FS031): KOSPI, KOSDAQ and the won/dollar rate.

A round asks the source once, while it is generated, for what was known at the round's reference point, and stores
the answer in its immutable payload (FS035). Reading a published round never reaches the source again, and a later
value never replaces the stored one. Because the question is "what was known at the reference point", a round for a
past date (the demo rebuild) gets the same kind of answer: only observations made before the cut-off are used.

- Indexes (``^KS11``, ``^KQ11``) come from daily bars. The value is the closing value of the last session the round can
  know (morning: the day before, evening: the same day) and the change is measured against the session before it.
- The rate (``KRW=X``) comes from 5-minute bars. The value is the last observation at or before the cut-off (morning
  07:40, evening 18:05, FS031), with its real time. The change is measured against the rate at 15:30 KST of the last
  weekday before the round's date that has data (the Seoul market close; the same "previous trading day close" base).
- Each indicator stands alone: one that fails, is missing or is late never changes the others or the round.

Prototype assumptions (the spec leaves the numbers open): ``RATE_STALE_AFTER`` and the "both indexes must agree on
the newest session" rule that marks an index as late. A calendar of exchange holidays is deliberately not kept: a
holiday shows up as the previous session's date on the card, which is true, instead of a guess about a delay.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, Protocol

from .market_data import KST, QuoteUnavailable, Series, Source
from .schemas import IndicatorBaseline, MarketIndicator, MarketVariables, QuoteSourceOut
from .statedb import utc_iso

log = logging.getLogger("zoop_bff.briefing_market")

Edition = Literal["morning", "evening"]
RATE_CUTOFF: dict[str, time] = {"morning": time(7, 40), "evening": time(18, 5)}  # FS031: 18:05 이전 최근 환율
SEOUL_CLOSE = time(15, 30)
RATE_STALE_AFTER = timedelta(minutes=30)  # 프로토타입 가정: 평일에 마지막 값이 기준 시각보다 30분 넘게 앞서면 지연
RATE_WEEK_OPEN = time(7, 0)  # 프로토타입 가정: 환율 시장은 월요일 07:00 KST에 열린다. 그 전의 값은 휴장 때문이지 지연이 아니다.
INDEX_LOOKBACK = timedelta(days=21)
RATE_LOOKBACK = timedelta(days=7)
NOT_CONNECTED = "시장 지표 출처를 연결하지 않았어요."
INTERNAL_FAILURE = "지표를 처리하지 못했어요."
# The provider's own wording invites "try again later", which a stored round cannot do: say what happened at generation.
STORED_REASON = {
    "temporary_failure": "이 회차를 만들 때 출처에 연결하지 못했어요.",
    "auth_failed": "이 회차를 만들 때 출처가 요청을 받아주지 않았어요.",
    "unsupported_symbol": "출처에서 이 지표를 찾지 못했어요.",
}


class IndicatorHistory(Protocol):
    def history(
        self, symbol: str, start: datetime, end: datetime, interval: Literal["1d", "5m"]
    ) -> tuple[Source, Series]: ...


@dataclass(frozen=True)
class Spec:
    id: Literal["kospi", "kosdaq", "usdkrw"]
    label: str
    symbol: str
    unit: Literal["pt", "KRW"]


SPECS: tuple[Spec, ...] = (
    Spec("kospi", "KOSPI", "^KS11", "pt"),
    Spec("kosdaq", "KOSDAQ", "^KQ11", "pt"),
    Spec("usdkrw", "원/달러", "KRW=X", "KRW"),
)
_NO_VALUE = {"no_data", "unsupported_symbol", "not_connected"}  # the source answered, or is absent: 아직 없음


def _source_out(source: Source) -> QuoteSourceOut:
    return QuoteSourceOut(
        provider=source.provider,
        name=source.name,
        official=source.official,
        delay_note=source.delay_note,
        symbol=source.symbol,
        url=source.url,
    )


def _kst(moment: datetime) -> str:
    return moment.astimezone(KST).isoformat(timespec="seconds")


def _move(value: float, base: float | None) -> tuple[float | None, float | None]:
    if base is None:
        return None, None
    change = round(value - base, 4)
    return change, (round(change / base, 8) if base else None)


class MarketIndicators:
    """Collects the three indicators for one round. ``history=None`` is a BFF without a market source."""

    def __init__(self, history: IndicatorHistory | None):
        self._history = history

    def collect(self, day: date, edition: Edition, reference: datetime, *, now: datetime) -> MarketVariables:
        cutoff = datetime.combine(day, RATE_CUTOFF[edition], tzinfo=KST)
        with ThreadPoolExecutor(max_workers=len(SPECS)) as pool:
            found = list(pool.map(lambda spec: self._one(spec, day, edition, cutoff), SPECS))
        return MarketVariables(
            reference_at=_kst(reference),
            rate_cutoff_at=_kst(cutoff),
            collected_at=utc_iso(now),
            indicators=self._late_index(found),
        )

    # ------------------------------------------------------------------ one indicator
    def _one(self, spec: Spec, day: date, edition: Edition, cutoff: datetime) -> MarketIndicator:
        try:
            if self._history is None:
                raise QuoteUnavailable("not_connected", NOT_CONNECTED)
            if spec.id == "usdkrw":
                return self._rate(self._history, spec, day, cutoff)
            return self._index(self._history, spec, day, edition)
        except QuoteUnavailable as exc:
            return self._without_value(spec, exc.code, exc.reason)
        except Exception:  # one indicator's bug must not take the round down
            log.exception("indicator %s crashed", spec.id)
            return self._without_value(spec, "internal", INTERNAL_FAILURE)

    @staticmethod
    def _without_value(spec: Spec, code: str, reason: str) -> MarketIndicator:
        return MarketIndicator(
            id=spec.id,
            label=spec.label,
            unit=spec.unit,
            status="unavailable" if code in _NO_VALUE else "failed",
            value=None,
            value_kind=None,
            observed_date=None,
            observed_at=None,
            baseline=None,
            change=None,
            change_rate=None,
            source=None,
            reason_code=code,  # type: ignore[arg-type]
            reason=STORED_REASON.get(code, reason),
        )

    @staticmethod
    def _index(history: IndicatorHistory, spec: Spec, day: date, edition: Edition) -> MarketIndicator:
        last_session = day if edition == "evening" else day - timedelta(days=1)
        start = datetime.combine(day - INDEX_LOOKBACK, time(0), tzinfo=KST)
        end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=KST)
        source, series = history.history(spec.symbol, start, end, "1d")
        closes: dict[date, float] = {}
        for bar in series.bars:  # the bar's own date in the exchange's zone; a later bar of the same date wins
            closes[bar.time.date()] = bar.close
        sessions = sorted(d for d in closes if d <= last_session)
        if not sessions:
            raise QuoteUnavailable("no_data", "출처에 이 시점 이전의 지수 자료가 없어요.")
        latest = sessions[-1]
        value = round(closes[latest], 4)
        base_day = sessions[-2] if len(sessions) > 1 else None
        base = round(closes[base_day], 4) if base_day else None
        change, rate = _move(value, base)
        return MarketIndicator(
            id=spec.id,
            label=spec.label,
            unit=spec.unit,
            status="ok",
            value=value,
            value_kind="close",
            observed_date=latest.isoformat(),
            observed_at=None,
            baseline=IndicatorBaseline(value=base, date=base_day.isoformat(), at=None) if base_day and base is not None else None,
            change=change,
            change_rate=rate,
            source=_source_out(source),
            reason_code=None,
            reason=None,
        )

    @staticmethod
    def _rate(history: IndicatorHistory, spec: Spec, day: date, cutoff: datetime) -> MarketIndicator:
        source, series = history.history(spec.symbol, cutoff - RATE_LOOKBACK, cutoff, "5m")
        bars = [b for b in series.bars if b.time <= cutoff]  # the source's window edge is not trusted
        if not bars:
            raise QuoteUnavailable("no_data", f"{cutoff:%H:%M} 이전 환율이 출처에 없어요.")
        last = bars[-1]
        seen = last.time.astimezone(KST)
        base_day = next(
            (d for d in sorted({b.time.astimezone(KST).date() for b in bars}, reverse=True) if d < day and d.weekday() < 5),
            None,
        )
        base_bar = None
        if base_day is not None:
            close = datetime.combine(base_day, SEOUL_CLOSE, tzinfo=KST)
            candidate = next((b for b in reversed(bars) if b.time <= close and b.time.astimezone(KST).date() == base_day), None)
            base_bar = candidate if candidate is not last else None  # the latest value is not its own base
        value = round(last.close, 4)
        base = round(base_bar.close, 4) if base_bar else None
        change, rate = _move(value, base)
        gap = cutoff - last.time
        week_open = datetime.combine(cutoff.date() - timedelta(days=cutoff.weekday()), RATE_WEEK_OPEN, tzinfo=KST)
        late = cutoff.weekday() < 5 and gap > RATE_STALE_AFTER and last.time >= week_open  # a weekend gap is not a delay
        return MarketIndicator(
            id=spec.id,
            label=spec.label,
            unit=spec.unit,
            status="delayed" if late else "ok",
            value=value,
            value_kind="latest",
            observed_date=seen.date().isoformat(),
            observed_at=seen.isoformat(timespec="seconds"),
            baseline=IndicatorBaseline(value=base, date=base_day.isoformat(), at=_kst(base_bar.time))
            if base_bar and base_day and base is not None
            else None,
            change=change,
            change_rate=rate,
            source=_source_out(source),
            reason_code=None,
            reason=f"기준 시각보다 {int(gap.total_seconds() // 60)}분 앞선 값이에요." if late else None,
        )

    @staticmethod
    def _late_index(found: list[MarketIndicator]) -> list[MarketIndicator]:
        """KOSPI and KOSDAQ share one exchange calendar: if one has a newer session than the other, the older one is late."""
        indexes = [i for i in found if i.unit == "pt" and i.status == "ok" and i.observed_date]
        newest = max((i.observed_date for i in indexes if i.observed_date), default=None)
        if newest is None:
            return found
        seen = date.fromisoformat(newest)
        return [
            i.model_copy(update={"status": "delayed", "reason": f"다른 지수는 {seen.month}월 {seen.day}일 값이 있어요."})
            if i in indexes and i.observed_date != newest
            else i
            for i in found
        ]
