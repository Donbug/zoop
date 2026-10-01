"""Rule-based question interpretation (FS047): relative dates in KST and company mentions.

Nothing here calls a model. Everything is derived from the question text and the frozen first-receipt time, so a
retry of the same job resolves to the same result. A phrase that cannot be pinned down is reported as ambiguous and
the caller asks the member instead of guessing.

[팀 확인 필요] Period words beyond the ones listed (분기, 상·하반기, 'N월' without a year ...) are not interpreted;
'N월' without a year and the vague words below are treated as ambiguous.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from .dataset import CompanyRec, Dataset

KST = ZoneInfo("Asia/Seoul")
DEFAULT_RECENT_MONTHS = 1  # FS047 v1.2 proposal: '최근' alone means the last month.


def kst_date(moment: datetime) -> date:
    return moment.astimezone(KST).date()


def published_date(value: str | None) -> date | None:
    """KST calendar day of an article's publication time (``None`` when unknown or unreadable)."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(KST).date()


# ---- period


@dataclass(frozen=True)
class ResolvedPeriod:
    start: str  # ISO date, inclusive
    end: str
    expression: str  # the words in the question that produced it


@dataclass(frozen=True)
class PeriodReading:
    period: ResolvedPeriod | None
    ambiguous: str | None  # the phrase that could not be resolved (or conflicting phrases joined by ' / ')


_VAGUE = re.compile(r"그때|그\s*무렵|그\s*당시|예전|옛날|언젠가|지난번|얼마\s*전|요즘|한동안|오래\s*전")
_UNIT_MONTHS = {"개월": 1, "달": 1, "년": 12}
_RECENT = re.compile(r"(?:최근|지난)\s*(\d{1,3})\s*(일|주일|주|개월|달|년)")
# The first pattern wins where spans overlap, so list the most specific ones first.
_EXPLICIT_DAY = re.compile(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})|(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_EXPLICIT_MONTH = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월")
_EXPLICIT_YEAR = re.compile(r"(\d{4})\s*년")
_MONTH_ONLY = re.compile(r"(?<![\d년])(\d{1,2})\s*월")
_REL_YEAR_MONTH = re.compile(r"(작년|지난해|올해|금년)\s*(\d{1,2})\s*월")
_AGO = re.compile(r"\d{1,3}\s*(?:일|주일|주|개월|달|년)\s*전")  # a point or a range? -> ask
_WORDS = (
    "오늘",
    "어제",
    "이번\\s*주(?![말간일])",
    "지난\\s*주(?![말간일])",
    "이번\\s*달",
    "지난\\s*달",
    "올해",
    "금년",
    "작년",
    "지난해",
    "최근",
)
_WORD = re.compile("|".join(_WORDS))


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _iso(start: date, end: date, expression: str) -> ResolvedPeriod:
    return ResolvedPeriod(start.isoformat(), end.isoformat(), re.sub(r"\s+", " ", expression).strip())


def _word_period(word: str, today: date) -> tuple[date, date]:
    squashed = re.sub(r"\s+", "", word)
    if squashed == "오늘":
        return today, today
    if squashed == "어제":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    if squashed == "이번주":
        return today - timedelta(days=today.weekday()), today
    if squashed == "지난주":
        monday = today - timedelta(days=today.weekday() + 7)
        return monday, monday + timedelta(days=6)
    if squashed == "이번달":
        return today.replace(day=1), today
    if squashed == "지난달":
        previous = _add_months(today.replace(day=1), -1)
        return _month_range(previous.year, previous.month)
    if squashed in ("올해", "금년"):
        return date(today.year, 1, 1), today
    if squashed in ("작년", "지난해"):  # the whole previous calendar year
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return _add_months(today, -DEFAULT_RECENT_MONTHS), today  # 최근


def _valid_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def read_period(question: str, today: date) -> PeriodReading:
    """Period named in the question, relative to ``today`` (the KST day the question was first received)."""
    taken: list[tuple[int, int]] = []
    found: dict[tuple[str, str], str] = {}  # (start, end) -> expression
    unresolved: list[str] = []

    def free(span: tuple[int, int]) -> bool:
        return all(span[1] <= a or span[0] >= b for a, b in taken)

    def add(span: tuple[int, int], period: tuple[date, date] | None, text: str) -> None:
        if not free(span):
            return
        taken.append(span)
        if period is None:
            unresolved.append(text)
            return
        resolved = _iso(period[0], period[1], text)
        found.setdefault((resolved.start, resolved.end), resolved.expression)

    for m in _EXPLICIT_DAY.finditer(question):
        y, mo, d = (int(x) for x in (m.group(1, 2, 3) if m.group(1) else m.group(4, 5, 6)))
        day = _valid_date(y, mo, d)
        add(m.span(), (day, day) if day else None, m.group(0))
    for m in _EXPLICIT_MONTH.finditer(question):
        y, mo = int(m.group(1)), int(m.group(2))
        add(m.span(), _month_range(y, mo) if 1 <= mo <= 12 else None, m.group(0))
    for m in _REL_YEAR_MONTH.finditer(question):
        mo = int(m.group(2))
        year = today.year - 1 if m.group(1) in ("작년", "지난해") else today.year
        add(m.span(), _month_range(year, mo) if 1 <= mo <= 12 else None, m.group(0))
    for m in _AGO.finditer(question):
        add(m.span(), None, m.group(0))
    for m in _EXPLICIT_YEAR.finditer(question):
        add(m.span(), (date(int(m.group(1)), 1, 1), date(int(m.group(1)), 12, 31)), m.group(0))
    for m in _RECENT.finditer(question):
        n, unit = int(m.group(1)), m.group(2)
        if n == 0:
            add(m.span(), None, m.group(0))
        elif unit == "일":
            add(m.span(), (today - timedelta(days=n), today), m.group(0))
        elif unit in ("주", "주일"):
            add(m.span(), (today - timedelta(weeks=n), today), m.group(0))
        else:
            add(m.span(), (_add_months(today, -n * _UNIT_MONTHS[unit]), today), m.group(0))
    for m in _WORD.finditer(question):
        add(m.span(), _word_period(m.group(0), today), m.group(0))
    for m in _MONTH_ONLY.finditer(question):
        if free(m.span()):
            add(m.span(), None, m.group(0))  # which year? -> ask
    for m in _VAGUE.finditer(question):
        if free(m.span()):
            add(m.span(), None, m.group(0))

    if unresolved:  # one phrase we cannot pin down makes the whole period unknown: ask, do not drop it
        return PeriodReading(None, unresolved[0])
    if len(found) > 1:
        return PeriodReading(None, " / ".join(found.values()))
    if found:
        (start, end), expression = next(iter(found.items()))
        return PeriodReading(ResolvedPeriod(start, end, expression), None)
    return PeriodReading(None, None)


# ---- companies

_TOKEN = re.compile(r"[0-9A-Za-z가-힣&.]{2,}")
_PARTICLES = "은는이가을를의도와과에로"
_ASCII = re.compile(r"^[\x00-\x7f]+$")
_DEICTIC = re.compile(r"(?<![가-힣])(?:이|그|저|해당)\s*(?:회사|기업|종목|사건|이슈|관계|연결선|뉴스|기사)|(?<![가-힣])여기(?:서|에|는)?(?![가-힣])")
_PERSONAL = re.compile(r"내\s*(?:관심|보유|종목|포트폴리오|자산|주식)|관심\s*종목|보유\s*종목|우리\s*종목")


def is_personal(question: str) -> bool:
    return bool(_PERSONAL.search(question))


def deictic_phrase(question: str) -> str | None:
    """'이 회사', '그 기업', '여기' ... words that point at a target the question does not name."""
    found = _DEICTIC.search(question)
    return re.sub(r"\s+", " ", found.group(0)) if found else None


@dataclass(frozen=True)
class CompanyReading:
    matched: tuple[CompanyRec, ...]  # companies named outright
    ambiguous: tuple[tuple[str, tuple[CompanyRec, ...]], ...]  # (text in question, candidates)


def _variants(company: CompanyRec) -> list[tuple[str, bool]]:
    """(text, case_sensitive): a ticker must be typed as written, so 'NOW' or 'NET' never match the English word."""
    names = [(n.strip(), False) for n in (company.name, *company.aliases)]
    if company.ticker:
        names.append((company.ticker.strip(), True))
    return [(n, strict) for n, strict in dict.fromkeys(names) if len(n) >= 2]


def _find_variant(question: str, variant: str, strict: bool) -> tuple[int, int] | None:
    if _ASCII.match(variant):
        # Latin names and tickers must stand alone (so a short name never matches inside another word).
        pattern = re.compile(rf"(?<![0-9A-Za-z]){re.escape(variant)}(?![0-9A-Za-z])", 0 if strict or len(variant) < 3 else re.IGNORECASE)
        found = pattern.search(question)
        return found.span() if found else None
    index = question.lower().find(variant.lower())
    return (index, index + len(variant)) if index >= 0 else None


def read_companies(ds: Dataset, question: str) -> CompanyReading:
    """Companies the question names outright, plus names that fit several companies (e.g. '삼성', 'LG')."""
    spans: list[tuple[int, int, str, str]] = []  # start, end, variant, company id
    for company in ds.companies.values():
        for variant, strict in _variants(company):
            span = _find_variant(question, variant, strict)
            if span:
                spans.append((span[0], span[1], variant, company.id))
    # A name inside a longer matched name belongs to the longer one ('삼성' in '삼성전자').
    kept = [s for s in spans if not any(o is not s and o[0] <= s[0] and s[1] <= o[1] and (o[1] - o[0]) > (s[1] - s[0]) for o in spans)]
    by_span: dict[tuple[int, int], set[str]] = {}
    for start, end, _, company_id in kept:
        by_span.setdefault((start, end), set()).add(company_id)
    matched: dict[str, CompanyRec] = {}
    ambiguous: list[tuple[str, tuple[CompanyRec, ...]]] = []
    covered: list[tuple[int, int]] = []
    for (start, end), ids in sorted(by_span.items()):
        covered.append((start, end))
        if len(ids) == 1:
            (company_id,) = ids
            matched[company_id] = ds.companies[company_id]
        else:
            ambiguous.append((question[start:end], tuple(ds.companies[i] for i in sorted(ids))))
    for token in _TOKEN.finditer(question):
        if any(token.start() < b and a < token.end() for a, b in covered):
            continue
        stems = {token.group(0)}
        if len(token.group(0)) >= 3 and token.group(0)[-1] in _PARTICLES:
            stems.add(token.group(0)[:-1])
        for stem in sorted(stems, key=len, reverse=True):
            candidates = [c for c in ds.companies.values() if c.name.lower().startswith(stem.lower())]
            if len(candidates) >= 2:
                ambiguous.append((stem, tuple(candidates)))
                break
    return CompanyReading(tuple(matched.values()), tuple(ambiguous))
