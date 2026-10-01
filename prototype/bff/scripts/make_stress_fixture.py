#!/usr/bin/env python3
"""Deterministic generator for ``fixtures/synthetic-stress-300.json``.

A 300-node (40 companies + 260 events) SYNTHETIC ``inspect()``-shaped snapshot for exercising the graph
screen: isolated events, hub companies, company pairs sharing several events, FOLLOWS chains, structural
relations with a catalog ``basis``, a "company -> event -> other company -> event" cluster for two-step focus,
and HOLD/REJECT candidates that must never reach the public API.

Every article is ``synthetic: true``, every company name is an obviously fictional one, and there are no logos.
Same seed, same bytes. Run from ``prototype/bff``::

    uv run python scripts/make_stress_fixture.py            # (re)write the fixture
    uv run python scripts/make_stress_fixture.py --check    # fail if the committed file differs

Article versions, relation ids and source support are computed with the PoC's own code (``investmate``), and
every emitted record is validated against the PoC models, so ``quoteVerified`` is ``true`` for every evidence.
The ALLOW candidate audit rows are left out (``candidates`` is optional); only HOLD/REJECT candidates are kept.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from investmate.domain import Article, Candidate, Evidence, Mention, Relation, digest
from investmate.storage import PostgresRepository

SEED = 300
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic-stress-300.json"
AS_OF = "2026-09-29T00:00:00+00:00"
START, END = date(2026, 7, 1), date(2026, 9, 24)  # event dates spread over ~12 weeks
LAST_PUBLISHED = date(2026, 9, 28)
BURSTS = (date(2026, 7, 17), date(2026, 8, 21), date(2026, 9, 10))

EVENT_COUNT = 260
ISOLATED_COUNT = 39  # 15%: events without any company link
UNKNOWN_TIME_COUNT = 5
MONTH_TIME_COUNT = 20

POLICY_VERSION = "policy-1:7ff4c2c0cbb8fadd"
EXTRACTION_VERSION = "fixture-model-1:prompt-1"
VERIFIER_VERSION = "fixture-model-1"
PUBLISHER = "SYNTHETIC—not real news"
UNRESOLVED = "가상 미등록업체"

# 1-based company numbers: 1-3 hubs, 4-9 mid-size, 10-19 two-step cluster, 20-29 pairs, 30-37 chains, 38-40 filler.
COMPANIES: tuple[tuple[str, str], ...] = (
    ("가상전자", "전자"), ("시험반도체", "반도체"), ("모의배터리", "배터리"), ("예시소재", "소재"),
    ("샘플바이오", "바이오"), ("임시제약", "제약"), ("더미화학", "화학"), ("가상로보틱스", "로봇"),
    ("시험모빌리티", "모빌리티"), ("모의에너지", "에너지"), ("예시통신", "통신"), ("샘플유통", "유통"),
    ("임시물류", "물류"), ("더미건설", "건설"), ("가상조선", "조선"), ("시험철강", "철강"),
    ("모의게임즈", "게임"), ("예시소프트", "소프트웨어"), ("샘플금융", "금융"), ("임시식품", "식품"),
    ("더미디스플레이", "디스플레이"), ("가상센서", "센서"), ("시험광학", "광학"), ("모의패키징", "패키징"),
    ("예시장비", "장비"), ("샘플플랫폼", "플랫폼"), ("임시클라우드", "클라우드"), ("더미보안", "보안"),
    ("가상항공", "항공"), ("시험해운", "해운"), ("모의태양광", "태양광"), ("예시풍력", "풍력"),
    ("샘플수소", "수소"), ("임시원전", "원전"), ("더미가전", "가전"), ("가상의료기기", "의료기기"),
    ("시험헬스케어", "헬스케어"), ("모의미디어", "미디어"), ("예시엔터", "엔터테인먼트"), ("샘플리테일", "리테일"),
)
HUBS = ((1, 24), (2, 19), (3, 16))
MIDS = (4, 5, 6, 7, 8, 9)
TAIL = (38, 39, 40)
STRUCTURAL_POOL = (*MIDS, *TAIL)
BASIS_KINDS = ("SUPPLIES", "PRODUCES", "USES", "MANUFACTURES", "BUYS", "DEVELOPS")

OBJECTS = (
    "메모리", "배터리 셀", "디스플레이 패널", "특수 소재", "바이오 의약품", "스마트 가전", "통신 장비",
    "클라우드 서비스", "물류 자동화", "플랜트", "선박 엔진", "모바일 플랫폼", "반도체 장비", "전력 기기", "협동 로봇",
)
DETAILS = (
    "회사 측은 구체적인 금액과 일정은 추후 공시할 예정이라고 밝혔다.",
    "관계자는 {X} 부문의 중장기 수요에 대응하기 위한 결정이라고 설명했다.",
    "업계에서는 이번 결정이 {X} 시장의 경쟁 구도에 영향을 줄 수 있다고 본다.",
    "증권가에서는 후속 발표 일정에 관심이 쏠린다는 반응이 나온다.",
    "해당 사업의 세부 계획은 이사회 논의를 거쳐 확정될 전망이다.",
    "시장 참여자들은 관련 공급망 전반의 파급 효과를 지켜보고 있다.",
)
DISCLAIMER = "이 기사는 시험용으로 만든 가상 기사다."


# --------------------------------------------------------------------------- Korean text

_JOSA = {"topic": ("은", "는"), "subj": ("이", "가"), "obj": ("을", "를"), "with": ("과", "와")}


class Word(str):
    """``"{A:topic}".format(A=Word("가상전자"))`` -> ``가상전자는``."""

    def __format__(self, spec: str) -> str:
        if not spec:
            return str(self)
        last = self[-1]
        final = ("\uac00" <= last <= "\ud7a3" and (ord(last) - 0xAC00) % 28 != 0) or last in "013678"  # 영 일 삼 육 칠 팔
        return str(self) + _JOSA[spec][0 if final else 1]


@dataclass(frozen=True)
class Template:
    event_type: str
    action: str
    target: str
    title: str
    sentence: str
    status: str
    roles: tuple[str, ...]  # per participant position; the last one repeats
    period: bool = False


SINGLE = (
    Template("earnings", "실적 발표", "{X} 실적", "{A}, 2분기 {X} 실적 발표",
             "{A:topic} {when} 2분기 {X} 실적을 발표했다.", "announced", ("발표자",), period=True),
    Template("capex", "설비 투자", "{X} 생산라인", "{A}, {X} 생산라인 증설 투자 결정",
             "{A:topic} {when} {X} 생산라인 증설에 투자하기로 했다고 밝혔다.", "announced",
             ("투자 주체, 신규 생산라인 운영사",)),
    Template("launch", "신제품 공개", "차세대 {X}", "{A}, 차세대 {X} 신제품 공개",
             "{A:topic} {when} 차세대 {X} 신제품을 공개했다.", "occurred", ("발표자",)),
    Template("plant", "가동 재개", "{X} 공장", "{A}, {X} 공장 가동 재개",
             "{A:subj} {when} {X} 공장의 가동을 재개했다.", "occurred", ("운영사",)),
    Template("regulatory", "규제 심사", "{X} 사업", "{A}, {X} 사업 규제 심사 통과",
             "{A:subj} {when} {X} 사업에 대한 규제 심사를 통과했다.", "occurred", ("심사 대상",)),
    Template("executive", "인사", "{X} 부문장", "{A}, 신임 {X} 부문장 선임",
             "{A:topic} {when} 신임 {X} 부문장을 선임했다.", "occurred", ("발표자",)),
    Template("forecast", "전망 발표", "{X} 수요", "{A}, 내년 {X} 수요 전망 상향",
             "{A:topic} {when} 내년 {X} 수요 전망을 상향 조정했다.", "forecast", ("전망 발표자",)),
)
PAIR = (
    Template("contract", "공급 계약", "{X} 공급", "{A}, {B:with} {X} 공급 계약 체결",
             "{A:topic} {when} {B:with} {X} 공급 계약을 맺었다.", "announced", ("공급사", "고객사")),
    Template("partnership", "공동 개발", "{X} 공동 개발", "{A}·{B}, {X} 공동 개발 협약",
             "{A:topic} {when} {B:with} {X} 공동 개발 협약을 체결했다.", "announced", ("협약 당사자",)),
    Template("acquisition", "지분 인수", "{B} 지분", "{A}, {B} 지분 인수 추진",
             "{A:topic} {when} {B} 지분 일부를 인수하는 방안을 추진한다고 밝혔다.", "planned", ("인수 주체", "인수 대상")),
    Template("settlement", "특허 분쟁 합의", "{X} 특허", "{A}·{B}, {X} 특허 분쟁 합의",
             "{A:topic} {when} {B:with} {X} 특허 분쟁에 합의했다.", "occurred", ("합의 당사자",)),
)
GROUP = (
    Template("consortium", "컨소시엄 구성", "{X} 컨소시엄", "{A}·{B}·{C}, {X} 컨소시엄 구성",
             "{A}, {B}, {C:topic} {when} {X} 컨소시엄을 구성했다.", "announced", ("컨소시엄 참여사",)),
)
# HOLD/REJECT candidates: distinctive wording so a leak into the public API is easy to spot.
HELD = Template("unverified-report", "미확인 보도", "{X} 관련 사안", "{A}, {X} 관련 미확인 보도",
                "{A:topic} {when} {X} 관련 사안이 있다는 미확인 제보가 나왔다.", "unknown", ("제보 대상",))


def render(text: str, names: list[Word], x: Word, when: str, **extra: str) -> str:
    fields: dict[str, Any] = {"A": names[0], "X": x, "when": when, **extra}
    for key, name in zip("BC", names[1:3]):
        fields[key] = name
    return text.format(**fields)


# --------------------------------------------------------------------------- plan


def company_id(number: int) -> str:
    return f"STRESS-C{number:02d}"


@dataclass(eq=False)
class Spec:
    """One planned event: who is directly involved, what it structurally touches, what it follows."""

    label: str
    companies: list[int]
    structural: list[tuple[int, list[tuple[int, int, str]]]] = field(default_factory=list)
    prior: Spec | None = None
    day: date | None = None
    precision: str = "day"  # day | month | unknown
    ordinal: int = 0
    # filled by choose_text
    names: list[Word] = field(default_factory=list)
    template: Template | None = None
    x: Word = Word("")
    title: str = ""

    @property
    def event_time(self) -> str | None:
        if self.day is None or self.precision == "unknown":
            return None
        return self.day.isoformat() if self.precision == "day" else self.day.strftime("%Y-%m")

    @property
    def when(self) -> str:
        if self.precision == "unknown" or self.day is None:
            return "최근"
        return f"{self.day.month}월 {self.day.day}일" if self.precision == "day" else f"{self.day.month}월 중"


def pick_day(rng: random.Random, low: date = START, high: date = END) -> date:
    if rng.random() < 0.3:  # bursts make the timeline uneven
        day = rng.choice(BURSTS) + timedelta(days=round(rng.gauss(0, 3)))
        if low <= day <= high:
            return day
    return low + timedelta(days=rng.randrange((high - low).days + 1))


def pick_companies(rng: random.Random, pool: list[int], count: int) -> list[int]:
    chosen: list[int] = []
    while len(chosen) < count:
        candidate = rng.choice(pool)
        if candidate not in chosen:
            chosen.append(candidate)
    return chosen


CHAINS = (  # (companies, index of the event it follows)
    [([30], None), ([30, 31], 0), ([30], 1), ([31], 2), ([30], 0)],  # linear plus a branch
    [([32], None), ([32], 0), ([32], 1), ([32], 2)],
    [([33], None), ([33, 34], 0), ([34], 1)],
    [([35], None), ([35], 0), ([35], 1)],
    [([36], None), ([37], 0)],  # joined to another company only through FOLLOWS
)


def plan(rng: random.Random) -> list[Spec]:
    specs: list[Spec] = []

    def add(label: str, companies: list[int], **kwargs: Any) -> Spec:
        spec = Spec(label, list(companies), **kwargs)
        specs.append(spec)
        return spec

    # Hubs: one company with 15+ events.
    for hub, count in HUBS:
        other_hubs = [h for h, _ in HUBS if h != hub]
        for _ in range(count):
            partners: list[int] = []
            for _ in range(rng.choices([0, 1, 2], [0.5, 0.38, 0.12])[0]):
                pool = [*MIDS, *TAIL, *(other_hubs if rng.random() < 0.15 else [])]
                partner = rng.choice(pool)
                if partner not in partners:
                    partners.append(partner)
            add("hub", [hub, *partners])

    # Two-step cluster: 10 -> its 4 events -> 11..13 -> their own events -> 14..19 (never 10).
    for partners in ([11], [12], [13], [11, 12]):
        add("focus", [10, *partners])
    for center in (11, 12, 13):
        for _ in range(5):
            add("focus", [center, *rng.sample(range(14, 20), rng.choice([1, 1, 2]))])

    # Pairs that keep meeting: several events shared by the same two companies (derived SHARES_ISSUE).
    for first, second, count in ((20, 21, 5), (22, 23, 3), (24, 25, 3), (26, 27, 2), (28, 29, 2)):
        for _ in range(count):
            add("pair", [first, second] if rng.random() < 0.5 else [second, first])

    # FOLLOWS chains, oldest first, 6-16 days apart.
    for chain in CHAINS:
        depth: dict[int, int] = {}
        for index, (_, parent) in enumerate(chain):
            depth[index] = 0 if parent is None else depth[parent] + 1
        latest = END - timedelta(days=16 * max(depth.values()))
        members: list[Spec] = []
        for companies, parent in chain:
            spec = add("chain", companies, prior=members[parent] if parent is not None else None)
            spec.day = (
                pick_day(rng, START, latest)
                if parent is None
                else members[parent].day + timedelta(days=rng.randint(6, 16))  # type: ignore[operator]
            )
            members.append(spec)

    # Structural relations: the event names company P, the catalog basis links P (via M) to Q.
    for index in range(14):
        p, q = rng.sample(STRUCTURAL_POOL, 2)
        if index % 4 == 3:
            m = rng.choice([c for c in STRUCTURAL_POOL if c not in (p, q)])
            path = [(p, m, rng.choice(BASIS_KINDS)), (m, q, rng.choice(BASIS_KINDS))]
        else:
            path = [(p, q, rng.choice(BASIS_KINDS))]
        add("structural", [p], structural=[(q, path)])

    # Filler, after making sure every company has at least one event.
    linked = {c for s in specs for c in s.companies} | {q for s in specs for q, _ in s.structural}
    pool = [c for c in range(1, len(COMPANIES) + 1) if c not in (1, 2, 3, 10)]
    # Uniform on purpose: only the three hubs may reach 15 events.
    for number in range(1, len(COMPANIES) + 1):
        if number not in linked:
            extras = [c for c in pool if c != number]
            add("filler", [number, *pick_companies(rng, extras, rng.choice([0, 0, 1]))])
    while len(specs) < EVENT_COUNT - ISOLATED_COUNT:
        add("filler", pick_companies(rng, pool, rng.choices([1, 2, 3], [0.6, 0.3, 0.1])[0]))
    for _ in range(ISOLATED_COUNT):
        add("isolated", [])
    assert len(specs) == EVENT_COUNT, len(specs)

    rng.shuffle(specs)
    for ordinal, spec in enumerate(specs, start=1):
        spec.ordinal = ordinal

    # Time: fill in dates, then blur some to month precision and leave a few unknown.
    for spec in specs:
        if spec.day is None:
            spec.day = pick_day(rng)
    free = [s for s in specs if s.label in ("hub", "focus", "pair", "filler", "isolated")]
    blurred = rng.sample(free, UNKNOWN_TIME_COUNT + MONTH_TIME_COUNT)
    for spec in blurred[:UNKNOWN_TIME_COUNT]:
        spec.precision = "unknown"
    for spec in blurred[UNKNOWN_TIME_COUNT:]:
        spec.precision = "month"
    return specs


def choose_text(rng: random.Random, spec: Spec, used_titles: set[str]) -> None:
    if spec.companies:
        spec.names = [Word(COMPANIES[c - 1][0]) for c in spec.companies]
    else:
        spec.names = [Word(f"{UNRESOLVED}{1 + rng.randrange(8)}")]
    pool = SINGLE if len(spec.names) == 1 else PAIR if len(spec.names) == 2 else GROUP
    for _ in range(500):
        template, x = rng.choice(pool), Word(rng.choice(OBJECTS))
        title = render(template.title, spec.names, x, spec.when)
        if title not in used_titles:
            break
    else:
        raise RuntimeError("could not find an unused title")
    used_titles.add(title)
    spec.template, spec.x, spec.title = template, x, title


# --------------------------------------------------------------------------- records


def issue_id_for(ordinal: int) -> str:
    return "issue-" + hashlib.sha256(f"stress-issue-{ordinal}".encode()).hexdigest()[:24]


def compose(sentences: list[str]) -> tuple[str, list[tuple[int, int]]]:
    """Article body and the (start, end) span of every sentence (code point offsets, like the PoC)."""
    body, spans = "", []
    for sentence in sentences:
        if body:
            body += " "
        spans.append((len(body), len(body) + len(sentence)))
        body += sentence
    return body, spans


def iso(day: date, rng: random.Random) -> str:
    return datetime(day.year, day.month, day.day, rng.randrange(6, 22), rng.choice([0, 15, 30, 45]), tzinfo=UTC).isoformat()


class Builder:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.counters: dict[str, int] = {}
        self.basis: dict[tuple[int, int, str], dict[str, Any]] = {}

    def basis_edge(self, source: int, target: int, kind: str, event_day: date | None) -> dict[str, Any]:
        key = (source, target, kind)
        if key not in self.basis:
            number = len(self.basis) + 1
            windowed = self.rng.random() < 0.3 and event_day is not None
            self.basis[key] = {
                "edge_id": f"basis-stress-{number:03d}",
                "source": company_id(source),
                "target": company_id(target),
                "relation_type": kind,
                "source_url": f"https://synthetic.invalid/basis/{number:03d}",
                "verified_at": "2026-06-30",
                "valid_from": "2026-01-01" if windowed else None,
                "valid_until": "2026-12-31" if windowed else None,
                "countries": ["KR"],
                "approved": True,
            }
        return self.basis[key]

    @staticmethod
    def relation(kind: str, source: str, target: str, evidence: list[dict[str, Any]], candidate_id: str, **extra: Any) -> dict[str, Any]:
        value = {"relation_type": kind, "source": source, "target": target, "evidence": evidence, **extra}
        return {
            "relation_id": "relation-" + digest(value)[:24],
            "source": source,
            "target": target,
            "relation_type": kind,
            "role": extra.get("role"),
            "assertion_status": extra.get("assertion_status"),
            "evidence": evidence,
            "basis": extra.get("basis", []),
            "candidate_ids": [candidate_id],
        }

    def build(self, spec: Spec, *, prefix: str, issue_id: str, articles_count: int) -> dict[str, Any]:
        rng, template = self.rng, spec.template
        assert template is not None
        event_time = spec.event_time
        details = [d.format(X=spec.x) for d in DETAILS]
        s1 = render(template.sentence, spec.names, spec.x, spec.when)
        target = render(template.target, spec.names, spec.x, spec.when)
        articles: list[dict[str, Any]] = []
        mentions: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        candidate_ids: list[str] = []
        first_origin: str | None = None
        assert spec.day is not None

        for k in range(articles_count):
            number = self.counters[prefix] = self.counters.get(prefix, 0) + 1
            article_id, mention_id = f"{prefix}-article-{number:04d}", f"{prefix}-m{number:04d}"
            follows = k == 0 and spec.prior is not None
            sentences = [s1]
            if follows:
                prior = spec.prior
                assert prior is not None and prior.template is not None
                sentences.append(f"이는 앞서 {prior.when} 알려진 {prior.template.action} 건의 후속 조치다.")
            sentences.append(details.pop(rng.randrange(len(details))))
            sentences.append(DISCLAIMER)
            body, spans = compose(sentences)
            origin = f"{prefix}-origin-{number:04d}"
            if k == 0:
                first_origin = origin
            elif rng.random() < 0.3:
                origin = first_origin or origin  # a syndicated copy of the first article's lineage
            published = min(spec.day + timedelta(days=rng.randint(0, 2) + k), LAST_PUBLISHED)
            article = {
                "article_id": article_id,
                "url": f"https://synthetic.invalid/{prefix}/{number:04d}",
                "title": f"[SYNTHETIC] {spec.title}" + ("" if k == 0 else f" ({k + 1}보)"),
                "body": body,
                "publisher": PUBLISHER,
                "published_at": iso(published, rng),
                "collected_at": AS_OF,
                "language": "ko",
                "input_kind": "body",
                "origin_id": origin,
                "withdrawn": False,
                "allow_model_send": False,
                "synthetic": True,
            }
            version = Article.model_validate(article).version
            articles.append(article)

            def evidence(span: tuple[int, int]) -> dict[str, Any]:
                return {
                    "article_id": article_id,
                    "article_version": version,
                    "start": span[0],
                    "end": span[1],
                    "quote": body[span[0] : span[1]],
                }

            mention_evidence = [evidence(spans[0])]
            if rng.random() < 0.35:
                mention_evidence.append(evidence(spans[-2]))  # the detail sentence, just before the disclaimer
            names = spec.names if (k == 0 or len(spec.names) < 2 or rng.random() < 0.5) else spec.names[:-1]
            participants = [
                {
                    "company_id": company_id(spec.companies[i]) if spec.companies else None,
                    "name": str(name),
                    "role": template.roles[min(i, len(template.roles) - 1)],
                }
                for i, name in enumerate(names)
            ]
            background = k > 0 and rng.random() < 0.1
            mention: dict[str, Any] = {
                "mention_id": mention_id,
                "article_id": article_id,
                "article_version": version,
                "title": spec.title,
                "event_type": template.event_type,
                "action": template.action,
                "target": target,
                "period": "2026-Q2" if template.period else None,
                "assertion_status": template.status,
                "participants": participants,
                "evidence": mention_evidence,
                "keywords": [str(spec.names[0]), str(spec.x)],
                "background": background,
                "countries": ["KR"],
            }
            if event_time:
                mention["event_time"] = event_time
            mentions.append(mention)

            candidate_id = "candidate-" + digest([prefix, issue_id, mention_id])[:24]
            candidate_ids.append(candidate_id)
            relations.append(
                self.relation(
                    "PROVIDES_BACKGROUND" if background else "REPORTS", article_id, issue_id, mention_evidence, candidate_id
                )
            )
            for participant in participants:
                if participant["company_id"]:
                    relations.append(
                        self.relation(
                            "INVOLVES", issue_id, participant["company_id"], mention_evidence, candidate_id,
                            role=participant["role"], assertion_status=template.status,
                        )
                    )
            if k == 0:
                for target_company, path in spec.structural:
                    relations.append(
                        self.relation(
                            "STRUCTURALLY_RELATED_TO", issue_id, company_id(target_company), mention_evidence, candidate_id,
                            basis=[self.basis_edge(s, t, kind, spec.day) for s, t, kind in path],
                        )
                    )
                if follows:
                    assert spec.prior is not None
                    relations.append(
                        self.relation("FOLLOWS", issue_id, issue_id_for(spec.prior.ordinal), [evidence(spans[1])], candidate_id)
                    )
            reason = "Every required check satisfies the configured probability policy."
            outcomes = [
                {"field": "event_time", "decision": "ALLOW" if event_time else "HOLD",
                 "reason": reason if event_time else "Required checks do not satisfy the configured probability policy."},
                {"field": "countries", "decision": "ALLOW", "reason": reason},
            ]
            if template.period:
                outcomes.append({"field": "period", "decision": "ALLOW", "reason": reason})
            decisions.append({"candidate_id": candidate_id, "mention_id": mention_id, "outcomes": outcomes})

        return {
            "issue_id": issue_id,
            "mentions": mentions,
            "articles": articles,
            "relations": relations,
            "candidate_ids": candidate_ids,
            "field_decisions": decisions,
            "source_support": PostgresRepository._source_support(articles),
        }


def held_candidate(record: dict[str, Any], status: str) -> dict[str, Any]:
    """The audit row ``inspect()`` reports for a candidate that was not approved."""
    candidate = {
        "candidate_id": record["candidate_ids"][0],
        "issue_id": record["issue_id"],
        "mention": record["mentions"][0],
        "articles": record["articles"],
        "relations": [{k: v for k, v in r.items() if k != "candidate_ids"} for r in record["relations"]],
        "prior_issues": [],
        "supersedes": [],
        "policy_version": POLICY_VERSION,
        "extraction_version": EXTRACTION_VERSION,
    }
    revision = Candidate.model_validate(candidate).revision
    verdicts = [{"target": "issue", "decision": status, "reason": "SYNTHETIC scripted identity decision"}]
    verdicts += [
        {"target": r["relation_id"], "decision": "ALLOW", "reason": "SYNTHETIC independent relation decision"}
        for r in candidate["relations"]
    ]
    return {
        "candidate": candidate,
        "validation": {
            "trace": None,
            "verdicts": verdicts,
            "candidate_id": candidate["candidate_id"],
            "policy_version": POLICY_VERSION,
            "verifier_version": VERIFIER_VERSION,
            "candidate_revision": revision,
        },
        "status": status,
        "active": True,
        "reasons": [],
        "invalidation_reason": None,
    }


HELD_PLAN = (  # (companies, status): they touch hubs and the cluster centre, so a leak would be visible
    ([1, 10], "HOLD"), ([2], "HOLD"), ([3, 20, 21], "HOLD"), ([5], "HOLD"), ([9, 38], "HOLD"),
    ([1, 2, 3], "REJECT"), ([4, 10], "REJECT"),
)


def build_payload() -> dict[str, Any]:
    rng = random.Random(SEED)
    specs = plan(rng)
    used_titles: set[str] = set()
    for spec in specs:
        choose_text(rng, spec, used_titles)
    builder = Builder(rng)

    issues = []
    for spec in specs:
        count = rng.choices([1, 2, 3], [0.62, 0.28, 0.10])[0] if spec.companies else rng.choices([1, 2], [0.85, 0.15])[0]
        issues.append(builder.build(spec, prefix="stress", issue_id=issue_id_for(spec.ordinal), articles_count=count))

    candidates = []
    for number, (companies, status) in enumerate(HELD_PLAN, start=1):
        spec = Spec("held", companies, day=pick_day(rng), ordinal=number)
        spec.names = [Word(COMPANIES[c - 1][0]) for c in companies]
        spec.template, spec.x = HELD, Word(rng.choice(OBJECTS))
        spec.title = render(HELD.title, spec.names, spec.x, spec.when)
        issue_id = "issue-" + hashlib.sha256(f"stress-held-{number}".encode()).hexdigest()[:24]
        record = builder.build(spec, prefix="stress-held", issue_id=issue_id, articles_count=1)
        candidates.append(held_candidate(record, status))

    payload = {
        "issues": issues,
        "candidates": candidates,
        "errors": [],
        "zoop": {
            "asOf": AS_OF,
            "generator": {"script": "scripts/make_stress_fixture.py", "seed": SEED, "synthetic": True},
            "companies": [
                {"company_id": company_id(i), "name": name, "aliases": [], "sector": sector}
                for i, (name, sector) in enumerate(COMPANIES, start=1)
            ],
        },
    }
    validate(payload, specs)
    return payload


# --------------------------------------------------------------------------- checks


def validate(payload: dict[str, Any], specs: list[Spec]) -> None:
    """Fail loudly if the fixture stops being what the graph screen is tested against."""
    records = [*payload["issues"], *({**c["candidate"]} for c in payload["candidates"])]
    for record in records:
        articles = {a["article_id"]: Article.model_validate(a) for a in record["articles"]}
        mentions = record["mentions"] if "mentions" in record else [record["mention"]]
        for mention in mentions:
            Mention.model_validate(mention)
            for item in mention["evidence"]:
                assert Evidence.model_validate(item).matches(articles[item["article_id"]]), item
        for relation in record["relations"]:
            Relation.model_validate({k: v for k, v in relation.items() if k != "candidate_ids"})
            for item in relation["evidence"]:
                assert Evidence.model_validate(item).matches(articles[item["article_id"]]), item
        assert all(a.synthetic for a in articles.values())

    issues = payload["issues"]
    linked: dict[str, set[str]] = {}
    for issue in issues:
        linked[issue["issue_id"]] = {
            r["target"] for r in issue["relations"] if r["relation_type"] in ("INVOLVES", "STRUCTURALLY_RELATED_TO")
        }
    follows = [r for i in issues for r in i["relations"] if r["relation_type"] == "FOLLOWS"]
    structural = [r for i in issues for r in i["relations"] if r["relation_type"] == "STRUCTURALLY_RELATED_TO"]
    followed = {r["target"] for r in follows} | {r["source"] for r in follows}
    isolated = [i for i in linked if not linked[i] and i not in followed]
    per_company: dict[str, int] = {}
    pairs: dict[tuple[str, str], int] = {}
    for companies in linked.values():
        for c in companies:
            per_company[c] = per_company.get(c, 0) + 1
        ordered = sorted(companies)
        for a_index, a in enumerate(ordered):
            for b in ordered[a_index + 1 :]:
                pairs[(a, b)] = pairs.get((a, b), 0) + 1
    days = sorted(s.day for s in specs if s.precision == "day" and s.day)
    titles = [s.title for s in specs]

    assert len(issues) == EVENT_COUNT and len(per_company) == len(COMPANIES), (len(issues), len(per_company))
    assert len(isolated) == ISOLATED_COUNT, len(isolated)
    top = sorted(per_company.values(), reverse=True)
    assert top[2] >= 15 > top[3], top[:5]  # exactly three hub companies
    assert len(follows) == 12 and len(structural) == 14
    assert sum(len(r["basis"]) == 2 for r in structural) >= 3 and all(r["basis"] for r in structural)
    assert max(pairs.values()) >= 5 and sum(v >= 2 for v in pairs.values()) >= 8
    assert (days[-1] - days[0]).days >= 60
    assert len(set(titles)) == len(titles)
    assert len({r["relation_id"] for i in issues for r in i["relations"]}) == sum(len(i["relations"]) for i in issues)
    assert {c["status"] for c in payload["candidates"]} == {"HOLD", "REJECT"}


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def serialize(payload: dict[str, Any]) -> str:
    """One top-level key per line, one array element per line: greppable without pretty-printing 1 MB."""
    parts = []
    for key, value in payload.items():
        if isinstance(value, list) and value:
            parts.append(f'"{key}":[\n' + ",\n".join(dump(item) for item in value) + "\n]")
        else:
            parts.append(f'"{key}":{dump(value)}')
    return "{\n" + ",\n".join(parts) + "\n}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="exit 1 when the file differs from the generated content")
    args = parser.parse_args()
    text = serialize(build_payload())
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != text:
            print(f"{args.output} is out of date; run scripts/make_stress_fixture.py", file=sys.stderr)
            return 1
        print(f"{args.output} is up to date")
        return 0
    args.output.write_text(text, encoding="utf-8")
    print(f"wrote {args.output} ({len(text.encode()) / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
