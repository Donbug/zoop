"""AI chat answering: context resolution, the replaceable answer engine, and the validator in front of the member.

The shipped engine is rule-based (no model call): it quotes approved evidence of the selected context. The job
pipeline (``chat_jobs``) only knows ``AnswerEngine`` -- a frozen ``AnswerPlan`` goes in, an unverified ``Draft``
comes out -- and ``validate_draft`` decides whether a draft may be shown, whatever produced it. A model-backed engine
can therefore replace ``RuleEngine`` without touching the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .chat_interpret import ResolvedPeriod, published_date
from .dataset import COMPANY_LINKS, Dataset, EvidenceRec
from .errors import ApiError
from .graph import edge_evidence_via
from .insights_common import companies_of
from .schemas import ChatApplied, ChatAppliedItem, ChatAppliedPeriod, Citation, GraphTarget

GENERATED_BY = "bff-example-v0"
MAX_CITATIONS = 3
_PREDICTION = re.compile(r"예측|전망|오를|내릴|호재|악재|매수|매도|추천|목표가|수익률")
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")

DISCLAIMER = "인용한 문장은 원인이나 투자 판단을 뜻하지 않아요."


def asks_for_prediction(question: str) -> bool:
    return bool(_PREDICTION.search(question))


class EngineUnavailable(Exception):
    """The answer engine failed in a way that is *confirmed* temporary: the same job may be run again.

    Any other exception from an engine is an unclassified technical failure and is never retried.
    """


# ---- contexts


@dataclass(frozen=True)
class ContextNode:
    id: str
    kind: str  # company | issue | edge | evidence
    label: str
    evidence_ids: tuple[str, ...]
    issue_ids: tuple[str, ...]


def resolve_context(ds: Dataset, context_id: str) -> ContextNode | None:
    if context_id in ds.issues:
        issue = ds.issues[context_id]
        return ContextNode(context_id, "issue", issue.title, issue.evidence_ids, (issue.id,))
    if context_id in ds.companies:
        edges = ds.company_edges.get(context_id, ())
        evidence = tuple(dict.fromkeys(e for edge in edges for e in edge.evidence_ids))
        issues = tuple(dict.fromkeys(edge.source for edge in edges))
        return ContextNode(context_id, "company", ds.companies[context_id].name, evidence, issues)
    if context_id in ds.edges:
        edge = ds.edges[context_id]
        if edge.derived:
            per_issue = edge_evidence_via(ds, edge)
            evidence = tuple(dict.fromkeys(e for ids in per_issue.values() for e in ids))
            issues = edge.via
        else:
            evidence, issues = edge.evidence_ids, (edge.source,) if edge.relation_type in COMPANY_LINKS else (edge.source, edge.target)
        return ContextNode(context_id, "edge", f"{edge.relation_type} {edge.source}→{edge.target}", evidence, issues)
    if context_id in ds.evidence:
        return ContextNode(context_id, "evidence", "근거", (context_id,), ds.evidence_issues.get(context_id, ()))
    return None


def resolve_all(ds: Dataset, context_ids: list[str]) -> list[ContextNode]:
    nodes = [resolve_context(ds, c) for c in dict.fromkeys(context_ids)]
    unknown = [c for c, n in zip(dict.fromkeys(context_ids), nodes) if n is None]
    if unknown:
        raise ApiError(422, "unknown_context_id", "알 수 없는 맥락 ID가 포함되어 있습니다.", {"contextIds": unknown})
    return [n for n in nodes if n is not None]


# ---- plan and draft


@dataclass(frozen=True)
class EvidencePool:
    ids: tuple[str, ...]
    excluded_by_period: int  # evidence of the contexts left out because its article is outside the period
    undated: int  # ... of which the article has no usable publication date


def evidence_pool(
    ds: Dataset, contexts: list[ContextNode], only: tuple[str, ...], period: ResolvedPeriod | None
) -> EvidencePool:
    """The evidence the answer may use: the contexts' own evidence, narrowed by explicit references and the period.

    A period is matched against the *article publication day* (KST). It is never read as the event day
    (design D05); evidence whose article date is unknown cannot be placed in a period and is left out.
    """
    ordered = [e for e in dict.fromkeys(e for c in contexts for e in c.evidence_ids) if e in ds.evidence]
    if only:
        wanted = set(only)
        ordered = [e for e in ordered if e in wanted]
    if period is None:
        return EvidencePool(tuple(ordered), 0, 0)
    start, end = date.fromisoformat(period.start), date.fromisoformat(period.end)
    kept: list[str] = []
    undated = 0
    for evidence_id in ordered:
        ev = ds.evidence[evidence_id]
        article = _article(ds, ev)
        day = published_date(article.published_at) if article else None
        if day is None:
            undated += 1
        elif start <= day <= end:
            kept.append(evidence_id)
    return EvidencePool(tuple(kept), len(ordered) - len(kept), undated)


@dataclass(frozen=True)
class AnswerPlan:
    """Everything the engine may use. Frozen at the first receipt of the question; a retry builds the same plan."""

    question: str
    contexts: tuple[ContextNode, ...]
    evidence_ids: tuple[str, ...]
    period: ResolvedPeriod | None
    period_basis: str | None  # "question" | "context"
    excluded_by_period: int = 0


@dataclass(frozen=True)
class Draft:
    """An engine's answer before validation."""

    status: str  # answered | insufficient_evidence
    text: str
    reason: str | None
    evidence_ids: tuple[str, ...]
    targets: tuple[GraphTarget, ...]
    citations: tuple[Citation, ...]


class AnswerEngine(Protocol):
    def generate(self, ds: Dataset, plan: AnswerPlan) -> Draft: ...


def _article(ds: Dataset, ev: EvidenceRec):
    """The article *version* the evidence points at (never another version of the same article)."""
    return next((a for a in ds.articles_by_id.get(ev.article_id, ()) if a.version == ev.article_version), None)



def _citation(ds: Dataset, ev: EvidenceRec) -> Citation:
    article = _article(ds, ev)
    return Citation(
        evidence_id=ev.id,
        quote=ev.quote,
        article_id=ev.article_id,
        article_version=ev.article_version,
        start=ev.start,
        end=ev.end,
        article_title=article.title if article else None,
        publisher=article.publisher if article else None,
        published_at=article.published_at if article else None,
        url=article.url if article else None,
    )


def _insufficient(reason: str, text: str) -> Draft:
    return Draft("insufficient_evidence", f"{text}\n{DISCLAIMER}", reason, (), (), ())


class RuleEngine:
    """Example answers without a model: quotes of approved evidence of the selected context."""

    generated_by = GENERATED_BY

    def generate(self, ds: Dataset, plan: AnswerPlan) -> Draft:
        if asks_for_prediction(plan.question):
            return self._prediction()
        if not plan.contexts:
            return _insufficient("no_context", "선택된 맥락이 없어 근거를 찾을 수 없습니다. 그래프에서 기업·사건·관계를 선택한 뒤 질문해 주세요.")
        usable = [ds.evidence[e] for e in plan.evidence_ids if e in ds.evidence and ds.evidence[e].quote_verified is not False]
        if not usable:
            if plan.period is not None and not plan.evidence_ids and plan.excluded_by_period:
                return _insufficient(
                    "no_evidence_in_period",
                    f"선택한 기간({plan.period.start} ~ {plan.period.end})에 발행된 근거가 없어 답변을 보류합니다. "
                    f"기간 밖의 근거 {plan.excluded_by_period}건은 쓰지 않았어요.",
                )
            reason = "quote_verification_failed" if plan.evidence_ids else "no_evidence_for_context"
            return _insufficient(reason, "선택한 맥락에서 원문과 대조되는 승인 근거를 찾지 못해 답변을 보류합니다.")
        tokens = [t.lower() for t in _TOKEN.findall(plan.question)]
        scores = {ev.id: sum(t in ev.quote.lower() for t in tokens) for ev in usable}
        ranked = sorted(usable, key=lambda ev: -scores[ev.id])
        matching = [ev for ev in ranked if scores[ev.id] > 0]
        chosen = (matching or ranked)[:MAX_CITATIONS]  # no overlap at all: fall back to the context's own quotes
        citations = tuple(_citation(ds, ev) for ev in chosen)
        contexts = list(plan.contexts)
        labels = ", ".join(c.label for c in contexts[:3]) + (f" 외 {len(contexts) - 3}개" if len(contexts) > 3 else "")
        lines = [f"선택한 {labels}에 연결된 근거 문장이에요."]
        for n, (ev, cite) in enumerate(zip(chosen, citations), 1):
            origin = " · ".join(x for x in (cite.publisher, cite.article_title) if x) or ev.article_id
            note = "" if ev.quote_verified else " (원문 대조 불가)"
            lines.append(f"{n}. “{ev.quote}” — {origin}{note}")
        lines.append(DISCLAIMER)
        contributing = [c for c in contexts if set(c.evidence_ids) & {ev.id for ev in chosen}]
        targets: dict[tuple[str, str], GraphTarget] = {}
        for c in contributing:
            target = GraphTarget(id=c.id, kind=c.kind) if c.kind in ("company", "issue", "edge") else None  # type: ignore[arg-type]
            if target is not None and target_exists(ds, target):
                targets[(c.kind, c.id)] = target
        for ev in chosen:
            for issue_id in ds.evidence_issues.get(ev.id, ()):
                targets.setdefault(("issue", issue_id), GraphTarget(id=issue_id, kind="issue"))
        return Draft("answered", "\n".join(lines), None, tuple(ev.id for ev in chosen), tuple(targets.values()), citations)

    @staticmethod
    def _prediction() -> Draft:
        return _insufficient(
            "prediction_or_advice_not_supported",
            "주가 예측·매매 판단·호재/악재 평가는 제공하지 않습니다. 선택한 맥락의 근거 인용만 확인할 수 있습니다.",
        )


# ---- validation (FS049)


def target_exists(ds: Dataset, target: GraphTarget) -> bool:
    """A graph target is real only if the published graph has it and it can be opened there: a company needs at least
    one relation, and only company-company edges are selectable (D03: an issue-company edge is never a click target)."""
    if target.kind == "company":
        return target.id in ds.companies and bool(ds.company_edges.get(target.id))
    if target.kind == "issue":
        return target.id in ds.issues
    edge = ds.edges.get(target.id)
    return edge is not None and edge.derived


def validate_draft(ds: Dataset, plan: AnswerPlan, draft: Draft) -> list[str]:
    """Reasons a draft must not be shown (empty = valid). Form, citations and graph targets are checked against the
    published data; a pass says the references are real, not that the sentence is true."""
    problems: list[str] = []
    if draft.status not in ("answered", "insufficient_evidence"):
        problems.append("bad_status")
    if not draft.text.strip():
        problems.append("empty_text")
    if draft.status == "insufficient_evidence" and not draft.reason:
        problems.append("missing_reason")
    if draft.status == "answered" and not draft.citations:
        problems.append("no_citation")
    if set(draft.evidence_ids) != {c.evidence_id for c in draft.citations}:
        problems.append("sources_do_not_match_citations")
    pool = set(plan.evidence_ids)
    for cite in draft.citations:
        ev = ds.evidence.get(cite.evidence_id)
        if ev is None:
            problems.append(f"unknown_evidence:{cite.evidence_id}")
            continue
        if cite.evidence_id not in pool:
            problems.append(f"evidence_out_of_scope:{cite.evidence_id}")
        if ev.quote_verified is False:
            problems.append(f"quote_not_verified:{cite.evidence_id}")
        if (cite.quote, cite.article_id, cite.article_version, cite.start, cite.end) != (ev.quote, ev.article_id, ev.article_version, ev.start, ev.end):
            problems.append(f"citation_span_mismatch:{cite.evidence_id}")
            continue
        if not 0 <= cite.start < cite.end:
            problems.append(f"bad_span:{cite.evidence_id}")
        article = _article(ds, ev)
        if article is None:
            problems.append(f"article_missing:{cite.evidence_id}")
        elif (cite.article_title, cite.publisher, cite.published_at, cite.url) != (article.title, article.publisher, article.published_at, article.url):
            problems.append(f"citation_source_mismatch:{cite.evidence_id}")
    allowed = {c.id for c in plan.contexts if c.kind != "evidence"}
    for cite in draft.citations:
        allowed.update(ds.evidence_issues.get(cite.evidence_id, ()))
    for target in draft.targets:
        if not target_exists(ds, target):
            problems.append(f"graph_target_missing:{target.kind}:{target.id}")
        elif target.id not in allowed:
            problems.append(f"graph_target_unrelated:{target.kind}:{target.id}")
    return problems


# ---- what was applied


def company_ids_of(ds: Dataset, contexts: list[ContextNode]) -> list[str]:
    return list(dict.fromkeys(c for node in contexts for c in _context_companies(ds, node)))


def _context_companies(ds: Dataset, node: ContextNode) -> list[str]:
    if node.kind != "evidence":
        return companies_of(ds, node.id)
    return [c for issue_id in node.issue_ids for c in companies_of(ds, issue_id)]


def applied_scope(ds: Dataset, plan: AnswerPlan, draft: Draft | None, *, overrode_context: bool) -> ChatApplied:
    """The companies, issues and period the answer was actually built on (shown with every result)."""
    contexts = list(plan.contexts)
    companies = company_ids_of(ds, contexts)
    issue_ids = list(dict.fromkeys(i for node in contexts for i in node.issue_ids if i in ds.issues))
    if draft is not None:
        issue_ids = list(dict.fromkeys([*issue_ids, *(t.id for t in draft.targets if t.kind == "issue")]))
    period: ChatAppliedPeriod | None = None
    if plan.period is not None:
        period = ChatAppliedPeriod(start=plan.period.start, end=plan.period.end, basis=plan.period_basis or "question", expression=plan.period.expression)
    elif draft is not None and draft.citations:
        days = sorted(d for d in (published_date(c.published_at) for c in draft.citations) if d)
        if days:
            period = ChatAppliedPeriod(start=days[0].isoformat(), end=days[-1].isoformat(), basis="evidence", expression=None)
    return ChatApplied(
        companies=[ChatAppliedItem(id=c, label=ds.companies[c].name) for c in companies if c in ds.companies],
        issues=[ChatAppliedItem(id=i, label=ds.issues[i].title) for i in issue_ids],
        period=period,
        graph_version=ds.graph_version,
        data_as_of=ds.as_of,
        question_overrode_context=overrode_context,
    )
