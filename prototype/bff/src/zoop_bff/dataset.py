"""Single normalized model built from a PoC ``inspect()``-shaped payload.

Only ``issues`` (current ALLOW approvals) feed the public model. ``candidates`` is read solely
to drop an issue that a hand-edited snapshot contradicts (a listed candidate that is HOLD/REJECT
or inactive); HOLD/REJECT content is never copied into any public record.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Callable, Literal, Mapping, Sequence

from investmate.domain import Article, Evidence
from pydantic import ValidationError

TimePrecision = Literal["year", "month", "day", "datetime", "unknown"]
COMPANY_LINKS = ("INVOLVES", "STRUCTURALLY_RELATED_TO")
ARTICLE_LINKS = ("REPORTS", "PROVIDES_BACKGROUND")
KNOWN_RELATIONS = (*COMPANY_LINKS, *ARTICLE_LINKS, "FOLLOWS")

# Catalog brand fields (``brand_color``, ``logo``) are optional; a malformed value is dropped, never repaired.
LOGO_URL_PREFIX = "/logos/"
_BRAND_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")
_LOGO_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class DatasetFormatError(ValueError):
    """The payload is not an inspect()-shaped document."""


# --------------------------------------------------------------------------- time helpers

_YEAR = re.compile(r"^\d{4}$")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DAY = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def time_precision(value: str | None) -> TimePrecision:
    if not value:
        return "unknown"
    if _DATETIME.match(value):
        return "datetime"
    if _DAY.match(value):
        return "day"
    if _MONTH.match(value):
        return "month"
    if _YEAR.match(value):
        return "year"
    return "unknown"


def event_interval(value: str | None) -> tuple[str, str] | None:
    """Inclusive ISO-date interval an event time may cover; ``None`` when the time is unknown."""
    precision = time_precision(value)
    if precision == "unknown" or value is None:
        return None
    if precision == "year":
        return f"{value}-01-01", f"{value}-12-31"
    if precision == "month":
        year, month = int(value[:4]), int(value[5:7])
        return f"{value}-01", f"{value}-{calendar.monthrange(year, month)[1]:02d}"
    return value[:10], value[:10]


# --------------------------------------------------------------------------- records


@dataclass(frozen=True)
class CompanyRec:
    id: str
    name: str
    ticker: str | None = None
    aliases: tuple[str, ...] = ()
    sector: str | None = None
    name_source: str = "company-id"
    brand_color: str | None = None
    logo: str | None = None
    brand_source: str | None = None

    @property
    def logo_url(self) -> str | None:
        return f"{LOGO_URL_PREFIX}{self.logo}" if self.logo else None


@dataclass(frozen=True)
class ArticleRec:
    id: str
    version: str | None
    title: str | None
    publisher: str | None
    url: str | None
    published_at: str | None
    synthetic: bool
    poc: Article | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class EvidenceRec:
    id: str
    article_id: str
    article_version: str
    start: int
    end: int
    quote: str
    quote_verified: bool | None


@dataclass(frozen=True)
class ParticipantRec:
    company_id: str | None
    name: str
    role: str | None
    role_unconfirmed: bool = False


@dataclass(frozen=True)
class MentionRec:
    mention_id: str
    article_id: str
    title: str
    action: str
    target: str | None
    event_time: str | None
    time_precision: TimePrecision
    period: str | None
    assertion_status: str
    participants: tuple[ParticipantRec, ...]
    evidence_ids: tuple[str, ...]
    background: bool


@dataclass(frozen=True)
class BasisRec:
    edge_id: str
    relation_type: str
    source_url: str | None
    verified_at: str | None
    valid_from: str | None
    valid_until: str | None
    countries: tuple[str, ...]


@dataclass(frozen=True)
class RelationRec:
    relation_id: str
    source: str
    target: str
    relation_type: str
    role: str | None
    assertion_status: str | None
    evidence_ids: tuple[str, ...]
    basis: tuple[BasisRec, ...]
    role_unconfirmed: bool = False


@dataclass(frozen=True)
class FieldOutcomeRec:
    field: str
    decision: str
    reason: str | None


@dataclass(frozen=True)
class FieldDecisionRec:
    candidate_id: str | None
    mention_id: str | None
    outcomes: tuple[FieldOutcomeRec, ...]


@dataclass(frozen=True)
class SourceSupportRec:
    article_count: int
    known_lineage_count: int | None
    unknown_lineage_articles: tuple[str, ...]
    independent_source_count: int | None
    duplicate_groups: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class EdgeRec:
    """One graph edge: approved relations sharing (type, source, target), or a derived pair."""

    id: str
    source: str
    target: str
    relation_type: str
    role: str | None
    roles: tuple[str, ...]
    assertion_status: str | None
    derived: bool
    via: tuple[str, ...]
    relation_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    basis: tuple[BasisRec, ...]
    role_unconfirmed: bool = False


@dataclass(frozen=True)
class ApprovalRec:
    """Set only when an admin review or a publication rule (not the PoC validation alone) put content on the graph."""

    source: str
    label: str
    scope: str
    candidate_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    rule_id: str | None = None
    rule_candidate_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IssueRec:
    id: str
    title: str
    action: str | None
    target: str | None
    event_time: str | None
    time_precision: TimePrecision
    period: str | None
    mentions: tuple[MentionRec, ...]
    article_ids: tuple[str, ...]
    article_relation: Mapping[str, str]
    relations: tuple[RelationRec, ...]
    company_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    field_decisions: tuple[FieldDecisionRec, ...]
    source_support: SourceSupportRec
    latest_published_at: str | None
    approval: ApprovalRec | None = None

    @property
    def article_count(self) -> int:
        return self.source_support.article_count

    @property
    def event_start(self) -> str:
        interval = event_interval(self.event_time)
        return interval[0] if interval else ""


@dataclass(frozen=True)
class HoldingRec:
    company_id: str
    quantity: float
    avg_price: float
    # Currency of avg_price (ISO 4217). None when unknown (e.g. connections stored before it existed);
    # profit/loss is shown only when it matches the quote currency (never converted).
    currency: str | None = None


@dataclass(frozen=True)
class MockPortfolioRec:
    """A project mock profile (FS062): profile id, account id, cash (예수금) and holdings. ``cash`` is None when the
    mock does not provide it (never read as 0). ``as_of`` is the mock information's own as-of time when given."""

    id: str
    label: str
    holdings: tuple[HoldingRec, ...]
    generated_by: str
    account_id: str
    cash: float | None = None
    cash_currency: str | None = None
    as_of: str | None = None


@dataclass(frozen=True)
class Dataset:
    as_of: str
    source_mode: Literal["snapshot"]
    source_label: str
    synthetic: bool
    issues: dict[str, IssueRec]
    companies: dict[str, CompanyRec]
    articles_by_id: dict[str, tuple[ArticleRec, ...]]
    evidence: dict[str, EvidenceRec]
    evidence_issues: dict[str, tuple[str, ...]]
    edges: dict[str, EdgeRec]
    issue_company_edges: dict[str, tuple[EdgeRec, ...]]
    company_edges: dict[str, tuple[EdgeRec, ...]]
    follows_previous: dict[str, tuple[str, ...]]
    follows_next: dict[str, tuple[str, ...]]
    mock_portfolios: dict[str, MockPortfolioRec]
    source_errors: tuple[str, ...]
    warnings: tuple[str, ...]
    graph_version: str | None = None

    @property
    def dataset_kind(self) -> Literal["approved-snapshot", "synthetic-preview"]:
        """Provenance of the articles. Every published version is a stored snapshot, never live."""
        if self.synthetic or not self.articles_by_id:
            return "synthetic-preview"
        return "approved-snapshot"

    def issues_of_company(self, company_id: str) -> list[IssueRec]:
        seen: dict[str, IssueRec] = {}
        for edge in self.company_edges.get(company_id, ()):
            seen.setdefault(edge.source, self.issues[edge.source])
        return list(seen.values())

    def article_for(self, article_id: str, version: str | None = None) -> ArticleRec | None:
        candidates = self.articles_by_id.get(article_id, ())
        for rec in candidates:
            if version is not None and rec.version == version:
                return rec
        return candidates[0] if candidates else None


def sort_recent(issues: Sequence[IssueRec]) -> list[IssueRec]:
    """Newest event first; unknown event time last; ties by newest article, then id.

    Article publication only orders otherwise-tied issues, it never becomes an event time.
    """
    ordered = sorted(issues, key=lambda i: i.id)
    ordered.sort(key=lambda i: i.latest_published_at or "", reverse=True)
    ordered.sort(key=lambda i: i.event_start, reverse=True)
    return ordered


# --------------------------------------------------------------------------- building


def _hash(prefix: str, *parts: object, length: int = 20) -> str:
    return prefix + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:length]


def evidence_id(article_id: str, version: str, start: int, end: int) -> str:
    return _hash("ev-", article_id, version, start, end, length=24)


def edge_id(relation_type: str, source: str, target: str) -> str:
    return _hash("edge-", relation_type, source, target, length=16)


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise DatasetFormatError(message)


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _approval_rec(raw: Any) -> ApprovalRec | None:
    if not isinstance(raw, dict) or raw.get("source") not in ("admin-review", "review-rule"):
        return None
    by_rule = raw["source"] == "review-rule"
    return ApprovalRec(
        source=raw["source"],
        label=_str_or_none(raw.get("label")) or ("자동 검수 규칙" if by_rule else "관리자 승인"),
        scope=_str_or_none(raw.get("scope")) or "issue",
        candidate_ids=tuple(raw.get("candidate_ids") or ()),
        relation_ids=tuple(raw.get("relation_ids") or ()),
        rule_id=_str_or_none(raw.get("rule_id")),
        rule_candidate_ids=tuple(raw.get("rule_candidate_ids") or ()),
    )


def _is_logo_file(value: str) -> bool:
    """A bare file name for ``public/logos/``: no separators, ``..``, query or fragment characters."""
    return bool(_LOGO_FILE.fullmatch(value)) and ".." not in value


def _brand_field(
    item: Mapping[str, Any], key: str, valid: Callable[[str], object], origin: str, warnings: list[str]
) -> str | None:
    """A brand catalog value, or ``None`` with a warning when present but malformed (the value is never echoed)."""
    value = item.get(key)
    if value is None:
        return None
    if isinstance(value, str) and valid(value):
        return value
    warnings.append(f"{origin}: {key} of {item['company_id']} ignored (invalid format)")
    return None


def parse_companies(items: Any, origin: str) -> tuple[list[CompanyRec], list[str]]:
    """Catalog records plus warnings for optional brand fields that were dropped as malformed."""
    _expect(isinstance(items, list), f"{origin}: companies must be an array")
    result = []
    warnings: list[str] = []
    for item in items:
        _expect(
            isinstance(item, dict)
            and isinstance(item.get("company_id"), str)
            and isinstance(item.get("name"), str),
            f"{origin}: each company needs string company_id and name",
        )
        aliases = item.get("aliases") or []
        _expect(
            isinstance(aliases, list) and all(isinstance(a, str) for a in aliases),
            f"{origin}: aliases must be an array of strings",
        )
        result.append(
            CompanyRec(
                id=item["company_id"],
                name=item["name"],
                ticker=_str_or_none(item.get("ticker")),
                aliases=tuple(aliases),
                sector=_str_or_none(item.get("sector")),
                name_source=origin,
                brand_color=_brand_field(item, "brand_color", _BRAND_COLOR.fullmatch, origin, warnings),
                logo=_brand_field(item, "logo", _is_logo_file, origin, warnings),
                brand_source=_str_or_none(item.get("brand_source")),
            )
        )
    return result, warnings


def _parse_portfolios(items: Any) -> list[MockPortfolioRec]:
    _expect(isinstance(items, list), "zoop.mockPortfolios must be an array")
    result = []
    for item in items:
        _expect(
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("label"), str)
            and isinstance(item.get("accountId"), str)
            and isinstance(item.get("holdings"), list),
            "zoop.mockPortfolios[]: id, label, accountId and holdings are required",
        )
        holdings = []
        for h in item["holdings"]:
            _expect(
                isinstance(h, dict)
                and isinstance(h.get("companyId"), str)
                and isinstance(h.get("quantity"), (int, float))
                and not isinstance(h.get("quantity"), bool)
                and h["quantity"] > 0
                and isinstance(h.get("avgPrice"), (int, float))
                and not isinstance(h.get("avgPrice"), bool)
                and h["avgPrice"] >= 0,
                "zoop.mockPortfolios[].holdings[]: companyId, quantity>0 and avgPrice>=0 are required",
            )
            currency = h.get("currency")
            _expect(currency is None or isinstance(currency, str), "zoop.mockPortfolios[].holdings[].currency must be a string")
            holdings.append(HoldingRec(h["companyId"], h["quantity"], h["avgPrice"], currency))
        cash = item.get("cash")
        _expect(
            cash is None
            or (
                isinstance(cash, dict)
                and isinstance(cash.get("amount"), (int, float))
                and not isinstance(cash.get("amount"), bool)
                and cash["amount"] >= 0
                and isinstance(cash.get("currency"), str)
            ),
            "zoop.mockPortfolios[].cash must be {amount>=0, currency} when given",
        )
        as_of = item.get("asOf")
        _expect(as_of is None or isinstance(as_of, str), "zoop.mockPortfolios[].asOf must be a string")
        result.append(
            MockPortfolioRec(
                item["id"],
                item["label"],
                tuple(holdings),
                "snapshot",
                item["accountId"],
                cash["amount"] if cash else None,
                cash["currency"] if cash else None,
                as_of,
            )
        )
    return result


# Currency of the BFF-made default mock prices, by the exchange in the catalog id (KRX:005930 -> KRW).
_DEFAULT_MOCK_CURRENCY = {"KRX": "KRW", "NASDAQ": "USD", "NYSE": "USD", "AMEX": "USD", "TSE": "JPY"}
_DEFAULT_MOCK_PRICE = {"KRW": (50000, 10000), "USD": (100, 10), "JPY": (5000, 1000)}


def _default_mock_holding(index: int, company_id: str) -> HoldingRec:
    """BFF-defined mock values (not provider data): KRW unless the listing says otherwise."""
    currency = _DEFAULT_MOCK_CURRENCY.get(company_id.partition(":")[0].upper(), "KRW")
    base, step = _DEFAULT_MOCK_PRICE[currency]
    return HoldingRec(company_id, 10 * (index + 1), base + step * index, currency)


def _publicly_approved(issue: Mapping[str, Any], audit: Mapping[str, Mapping[str, Any]]) -> bool:
    """False when the payload itself lists a HOLD/REJECT/inactive candidate under an issue."""
    for candidate_id in issue.get("candidate_ids") or []:
        record = audit.get(candidate_id)
        if record is not None and (record.get("status") != "ALLOW" or record.get("active") is False):
            return False
    return True


def _article_rec(raw: Mapping[str, Any]) -> ArticleRec:
    poc: Article | None
    try:
        poc = Article.model_validate(raw)
    except ValidationError:
        poc = None  # e.g. inspect output without bodies: quotes stay unverifiable (null)
    return ArticleRec(
        id=raw["article_id"],
        version=poc.version if poc else None,
        title=_str_or_none(raw.get("title")),
        publisher=_str_or_none(raw.get("publisher")),
        url=_str_or_none(raw.get("url")),
        published_at=_str_or_none(raw.get("published_at")),
        synthetic=raw.get("synthetic") is not False,
        poc=poc,
    )


def build_dataset(
    raw: Mapping[str, Any],
    *,
    source_mode: Literal["snapshot"],
    source_label: str,
    as_of: str,
    catalog: Sequence[CompanyRec] = (),
    warnings: Sequence[str] = (),
    graph_version: str | None = None,
) -> Dataset:
    _expect(isinstance(raw, Mapping), "inspect payload must be an object")
    raw_issues = raw.get("issues")
    _expect(isinstance(raw_issues, list), "inspect payload needs an 'issues' array")
    errors = raw.get("errors") or []
    _expect(isinstance(errors, list), "'errors' must be an array")
    extension = raw.get("zoop") or {}
    _expect(isinstance(extension, dict), "'zoop' extension must be an object")
    audit = {
        c["candidate"]["candidate_id"]: c
        for c in raw.get("candidates") or []
        if isinstance(c, dict) and isinstance(c.get("candidate"), dict) and "candidate_id" in c["candidate"]
    }
    for issue in raw_issues:
        _expect(
            isinstance(issue, dict) and isinstance(issue.get("issue_id"), str),
            "every issue needs a string issue_id",
        )
    approved = [i for i in raw_issues if _publicly_approved(i, audit)]

    # -- company catalog: PoC settings < snapshot extension < participant names < bare ids
    companies: dict[str, CompanyRec] = {c.id: c for c in catalog}
    extension_companies, extension_warnings = parse_companies(extension.get("companies", []), "snapshot-extension")
    for rec in extension_companies:
        companies[rec.id] = rec
    for issue in approved:
        for mention in issue.get("mentions") or []:
            for p in mention.get("participants") or []:
                cid = p.get("company_id")
                if cid and cid not in companies and p.get("name"):
                    companies[cid] = CompanyRec(cid, p["name"], name_source="mention-participant")

    # -- pass 1: articles (evidence verification needs every article body)
    articles_by_id: dict[str, list[ArticleRec]] = defaultdict(list)
    per_issue_articles: dict[str, list[str]] = {}
    for issue in approved:
        ids = []
        for article in issue.get("articles") or []:
            rec = _article_rec(article)
            known = articles_by_id[rec.id]
            if not any(k.version == rec.version for k in known):
                known.append(rec)
            ids.append(rec.id)
        per_issue_articles[issue["issue_id"]] = ids

    evidence: dict[str, EvidenceRec] = {}
    evidence_issues: dict[str, list[str]] = defaultdict(list)

    def register(item: Mapping[str, Any], issue_id: str) -> str:
        article_id, version = item["article_id"], item["article_version"]
        eid = evidence_id(article_id, version, item["start"], item["end"])
        if eid not in evidence:
            evidence[eid] = EvidenceRec(
                id=eid,
                article_id=article_id,
                article_version=version,
                start=item["start"],
                end=item["end"],
                quote=item["quote"],
                quote_verified=_verify(item, articles_by_id.get(article_id, ())),
            )
        if issue_id not in evidence_issues[eid]:
            evidence_issues[eid].append(issue_id)
        return eid

    # -- pass 2: issues
    issues: dict[str, IssueRec] = {}
    for issue in approved:
        issue_id = issue["issue_id"]
        denied: dict[str | None, set[str]] = defaultdict(set)
        decisions = []
        for fd in issue.get("field_decisions") or []:
            outcomes = tuple(
                FieldOutcomeRec(o["field"], o["decision"], _str_or_none(o.get("reason")))
                for o in fd.get("outcomes") or []
            )
            for o in outcomes:
                if o.decision != "ALLOW":
                    denied[fd.get("mention_id")].add(o.field)
            decisions.append(FieldDecisionRec(fd.get("candidate_id"), fd.get("mention_id"), outcomes))

        mentions = []
        for m in issue.get("mentions") or []:
            blocked = denied.get(m["mention_id"], set())
            event_time = None if "event_time" in blocked else _str_or_none(m.get("event_time"))
            mentions.append(
                MentionRec(
                    mention_id=m["mention_id"],
                    article_id=m["article_id"],
                    title=m["title"],
                    action=m["action"],
                    target=_str_or_none(m.get("target")),
                    event_time=event_time,
                    time_precision=time_precision(event_time),
                    period=None if "period" in blocked else _str_or_none(m.get("period")),
                    assertion_status=m.get("assertion_status") or "unknown",
                    participants=tuple(
                        ParticipantRec(
                            p.get("company_id"), p["name"], _str_or_none(p.get("role")), bool(p.get("role_unconfirmed"))
                        )
                        for p in m.get("participants") or []
                    ),
                    evidence_ids=tuple(dict.fromkeys(register(e, issue_id) for e in m.get("evidence") or [])),
                    background=bool(m.get("background")),
                )
            )

        relations = []
        for r in issue.get("relations") or []:
            if r.get("relation_type") not in KNOWN_RELATIONS:
                continue
            relations.append(
                RelationRec(
                    relation_id=r["relation_id"],
                    source=r["source"],
                    target=r["target"],
                    relation_type=r["relation_type"],
                    role=_str_or_none(r.get("role")),
                    assertion_status=_str_or_none(r.get("assertion_status")),
                    evidence_ids=tuple(dict.fromkeys(register(e, issue_id) for e in r.get("evidence") or [])),
                    basis=tuple(
                        BasisRec(
                            edge_id=b["edge_id"],
                            relation_type=b["relation_type"],
                            source_url=_str_or_none(b.get("source_url")),
                            verified_at=_str_or_none(b.get("verified_at")),
                            valid_from=_str_or_none(b.get("valid_from")),
                            valid_until=_str_or_none(b.get("valid_until")),
                            countries=tuple(b.get("countries") or ()),
                        )
                        for b in r.get("basis") or []
                    ),
                    role_unconfirmed=bool(r.get("role_unconfirmed")),
                )
            )

        representative = next((m for m in mentions if not m.background), mentions[0] if mentions else None)
        dated = ([representative] if representative and representative.event_time else []) + [
            m for m in mentions if m.event_time
        ]
        periodic = ([representative] if representative and representative.period else []) + [
            m for m in mentions if m.period
        ]
        event_time = dated[0].event_time if dated else None
        support = issue.get("source_support") or {}
        article_ids = tuple(dict.fromkeys(per_issue_articles[issue_id]))
        published = [
            a.published_at
            for aid in article_ids
            for a in articles_by_id[aid][:1]
            if a.published_at
        ]
        company_ids = tuple(
            dict.fromkeys(
                r.target for r in relations if r.relation_type in COMPANY_LINKS and r.source == issue_id
            )
        )
        issues[issue_id] = IssueRec(
            id=issue_id,
            title=representative.title if representative else issue_id,
            action=representative.action if representative else None,
            target=representative.target if representative else None,
            event_time=event_time,
            time_precision=time_precision(event_time),
            period=periodic[0].period if periodic else None,
            mentions=tuple(mentions),
            article_ids=article_ids,
            article_relation={
                r.source: r.relation_type
                for r in reversed(relations)
                if r.relation_type in ARTICLE_LINKS and r.target == issue_id
            },
            relations=tuple(relations),
            company_ids=company_ids,
            evidence_ids=tuple(
                dict.fromkeys([*(e for m in mentions for e in m.evidence_ids), *(e for r in relations for e in r.evidence_ids)])
            ),
            field_decisions=tuple(decisions),
            source_support=SourceSupportRec(
                article_count=support.get("article_count", len(article_ids)),
                known_lineage_count=support.get("known_lineage_count"),
                unknown_lineage_articles=tuple(support.get("unknown_lineage_articles") or ()),
                independent_source_count=support.get("independent_source_count"),
                duplicate_groups=tuple(tuple(g) for g in support.get("duplicate_groups") or ()),
            ),
            latest_published_at=max(published) if published else None,
            approval=_approval_rec(issue.get("zoop_approval")),
        )

    # -- graph edges: approved relations aggregated per (type, source, target)
    grouped: dict[tuple[str, str, str], list[RelationRec]] = {}
    for issue in issues.values():
        for r in issue.relations:
            if r.relation_type in COMPANY_LINKS and r.source == issue.id:
                grouped.setdefault((r.relation_type, r.source, r.target), []).append(r)
            elif r.relation_type == "FOLLOWS" and r.source == issue.id and r.target in issues:
                grouped.setdefault((r.relation_type, r.source, r.target), []).append(r)
    edges: dict[str, EdgeRec] = {}
    for (rtype, source, target), rels in grouped.items():
        roles = tuple(dict.fromkeys(r.role for r in rels if r.role))
        basis = {b.edge_id: b for r in rels for b in r.basis}
        eid = edge_id(rtype, source, target)
        edges[eid] = EdgeRec(
            id=eid,
            source=source,
            target=target,
            relation_type=rtype,
            role=roles[0] if roles else None,
            roles=roles,
            assertion_status=next((r.assertion_status for r in rels if r.assertion_status), None),
            derived=False,
            via=(),
            relation_ids=tuple(r.relation_id for r in rels),
            evidence_ids=tuple(dict.fromkeys(e for r in rels for e in r.evidence_ids)),
            basis=tuple(basis.values()),
            role_unconfirmed=not roles and any(r.role_unconfirmed for r in rels),
        )
        if rtype in COMPANY_LINKS and target not in companies:
            companies[target] = CompanyRec(target, target)

    # -- derived company-company pairs: companies sharing an approved issue (not approved edges)
    pair_via: dict[tuple[str, str], list[str]] = defaultdict(list)
    for issue in issues.values():
        for a, b in combinations(sorted(set(issue.company_ids)), 2):
            pair_via[(a, b)].append(issue.id)
    for (a, b), via in pair_via.items():
        eid = edge_id("SHARES_ISSUE", a, b)
        edges[eid] = EdgeRec(eid, a, b, "SHARES_ISSUE", None, (), None, True, tuple(via), (), (), ())

    issue_company: dict[str, list[EdgeRec]] = defaultdict(list)
    company_edges: dict[str, list[EdgeRec]] = defaultdict(list)
    previous: dict[str, list[str]] = defaultdict(list)
    following: dict[str, list[str]] = defaultdict(list)
    for e in edges.values():
        if e.relation_type in COMPANY_LINKS:
            issue_company[e.source].append(e)
            company_edges[e.target].append(e)
        elif e.relation_type == "FOLLOWS":
            previous[e.source].append(e.target)
            following[e.target].append(e.source)

    # -- mock portfolios (extension, else one BFF-generated default over linked companies)
    portfolios = {p.id: p for p in _parse_portfolios(extension.get("mockPortfolios", []))}
    for p in portfolios.values():
        for h in p.holdings:
            companies.setdefault(h.company_id, CompanyRec(h.company_id, h.company_id))
    if not portfolios:
        linked = sorted(company_edges, key=lambda c: (-len(company_edges[c]), c))[:3]
        if linked:
            portfolios["mock-basic"] = MockPortfolioRec(
                "mock-basic",
                "가상 계좌 예시",
                tuple(_default_mock_holding(i, c) for i, c in enumerate(linked)),
                "bff-default",
                account_id="MOCK-0001",
                # BFF-made mock cash (FS062 예수금); excluded from holding weights (FS054).
                cash=3_000_000,
                cash_currency="KRW",
            )

    override_as_of = extension.get("asOf")
    _expect(override_as_of is None or isinstance(override_as_of, str), "zoop.asOf must be a string")
    return Dataset(
        as_of=override_as_of or as_of,
        source_mode=source_mode,
        source_label=source_label,
        synthetic=any(a.synthetic for recs in articles_by_id.values() for a in recs),
        issues=issues,
        companies=companies,
        articles_by_id={k: tuple(v) for k, v in articles_by_id.items()},
        evidence=evidence,
        evidence_issues={k: tuple(v) for k, v in evidence_issues.items()},
        edges=edges,
        issue_company_edges={k: tuple(v) for k, v in issue_company.items()},
        company_edges={k: tuple(v) for k, v in company_edges.items()},
        follows_previous={k: tuple(v) for k, v in previous.items()},
        follows_next={k: tuple(v) for k, v in following.items()},
        mock_portfolios=portfolios,
        source_errors=tuple(str(e) for e in errors),
        warnings=(*warnings, *extension_warnings),
        graph_version=graph_version,
    )


def _verify(item: Mapping[str, Any], candidates: Sequence[ArticleRec]) -> bool | None:
    """PoC ``Evidence.matches`` against the cited article, ``None`` when no body is available."""
    article = next((a for a in candidates if a.version == item["article_version"]), None)
    article = article or next((a for a in candidates if a.poc is not None), None)
    if article is None or article.poc is None:
        return None
    try:
        return Evidence.model_validate(item).matches(article.poc)
    except ValidationError:
        return False
