"""The steps of one question job that do not touch job state: interpret the question, build the plan, shape results.

FS047 (freeze and ask back), FS048 (conditions and evidence) and the result shape of FS049. The job lifecycle -- who
may run, what is saved, what a retry may do -- lives in ``chat_jobs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .accounts import UserState
from .chat import (
    AnswerPlan,
    Draft,
    applied_scope,
    asks_for_prediction,
    evidence_pool,
    resolve_all,
)
from .chat_interpret import (
    ResolvedPeriod,
    deictic_phrase,
    is_personal,
    read_companies,
    read_period,
)
from .dataset import Dataset
from .insights_common import companies_of
from .schemas import ChatAction, ChatApplied, ChatAppliedPeriod, ChatChoice, ChatResult
from .views import meta, user_holding_ids

MAX_CHOICES = 6


@dataclass(frozen=True)
class Terminal:
    """A result that needs no answer engine: a question back, a missing condition, or unusable data."""

    outcome: str  # clarification | guidance | insufficient_evidence
    reason: str
    text: str
    choices: tuple[tuple[str, str], ...] = ()  # (company id, label)
    action: tuple[str, str] | None = None  # (kind, label)

    def to_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "text": self.text,
            "choices": [list(c) for c in self.choices],
            "action": list(self.action) if self.action else None,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Terminal:
        return cls(
            raw["outcome"],
            raw["reason"],
            raw["text"],
            tuple((c[0], c[1]) for c in raw["choices"]),
            (raw["action"][0], raw["action"][1]) if raw["action"] else None,
        )


@dataclass(frozen=True)
class Resolution:
    """What the question means, decided once from the frozen request and then kept for every retry."""

    context_ids: tuple[str, ...] = ()
    evidence_only: tuple[str, ...] = ()
    period: dict[str, Any] | None = None  # start, end, expression, basis ("question" | "context")
    overrode_context: bool = False
    terminal: Terminal | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "contextIds": list(self.context_ids),
            "evidenceOnly": list(self.evidence_only),
            "period": self.period,
            "overrodeContext": self.overrode_context,
            "terminal": self.terminal.to_json() if self.terminal else None,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Resolution:
        return cls(
            tuple(raw["contextIds"]),
            tuple(raw["evidenceOnly"]),
            raw["period"],
            raw["overrodeContext"],
            Terminal.from_json(raw["terminal"]) if raw["terminal"] else None,
        )


def _ask_back(reason: str, text: str, choices: tuple[tuple[str, str], ...] = ()) -> Resolution:
    return Resolution(terminal=Terminal("clarification", reason, text, choices))


def _popular_companies(ds: Dataset) -> tuple[tuple[str, str], ...]:
    ranked = sorted(ds.companies, key=lambda c: (-len(ds.issues_of_company(c)), c))
    return tuple((c, ds.companies[c].name) for c in ranked if ds.issues_of_company(c))[:MAX_CHOICES]


def personal_company_ids(ds: Dataset, member: UserState) -> list[str]:
    """Watch list and connected virtual holdings together (one personalized graph, D02)."""
    mine = [*member.watchlist_ids, *user_holding_ids(ds, member)]
    return [c for c in dict.fromkeys(mine) if c in ds.companies]


def version_unavailable(request: dict[str, Any], ds: Dataset) -> Terminal | None:
    """The selection was made on another graph version than the one served now. The newer data is never swapped in."""
    if ds.graph_version == request["graphVersion"]:
        return None
    return Terminal(
        "insufficient_evidence",
        "pinned_version_unavailable",
        f"질문할 때 고른 자료(그래프 버전 {request['graphVersion'] or '미상'})를 지금은 쓸 수 없어요. "
        "최신 자료로 바꿔서 답하지는 않아요. 지금 자료로 보려면 대상을 다시 골라 새로 질문해 주세요.",
    )


def interpret(ds: Dataset, request: dict[str, Any], member: UserState) -> Resolution:
    """FS047/FS048 with rules only. Anything that cannot be decided is asked back, never guessed."""
    question: str = request["question"]
    today = date.fromisoformat(request["askedDay"])

    context_ids: list[str] = list(request["contextIds"])
    only: list[str] = list(request["evidenceIds"])
    companies = read_companies(ds, question)
    # A name that fits several companies is settled once the member picked one of them (a choice of an earlier ask-back).
    unsettled = [(text, found) for text, found in companies.ambiguous if not any(c.id in context_ids for c in found)]
    if unsettled:
        text, candidates = unsettled[0]
        return _ask_back(
            "ambiguous_company",
            f"‘{text}’에 해당하는 기업이 여러 곳이에요. 어느 기업을 말씀하시나요?",
            tuple((c.id, c.name) for c in candidates[:MAX_CHOICES]),
        )
    overrode = False
    if is_personal(question):
        mine = personal_company_ids(ds, member)
        if not mine:
            return Resolution(
                terminal=Terminal(
                    "guidance",
                    "watchlist_empty",
                    "내 관심 종목이나 보유 종목이 없어 ‘내 종목’ 기준으로는 답할 수 없어요. 종목을 설정한 뒤 다시 질문해 주세요.",
                    action=("set_watchlist", "내 종목 설정하기"),
                )
            )
        overrode = bool(context_ids or only)
        context_ids, only = mine, []
    elif companies.matched:
        explicit = [c.id for c in companies.matched]
        related = [i for i in context_ids if i not in ds.companies and set(companies_of(ds, i)) & set(explicit)]
        overrode = any(i not in explicit and i not in related for i in context_ids)
        context_ids = [*explicit, *related]
        if overrode:
            only = []  # the evidence references belonged to the selection the question replaced
    if not context_ids and not only and not asks_for_prediction(question):
        phrase = deictic_phrase(question)
        if phrase:
            return _ask_back("ambiguous_target", f"‘{phrase}’만으로는 어느 대상인지 알 수 없어요. 그래프에서 기업이나 사건을 고르거나 기업 이름을 알려 주세요.")
        return _ask_back(
            "no_target",
            "어느 기업이나 사건에 대한 질문인지 알려 주세요. 그래프에서 대상을 고르거나 기업 이름을 함께 적어 주세요.",
            _popular_companies(ds),
        )
    reading = read_period(question, today)
    if reading.ambiguous and not asks_for_prediction(question):  # a declined question needs no period
        return _ask_back(
            "ambiguous_period",
            f"‘{reading.ambiguous}’만으로는 어느 기간인지 정할 수 없어요. ‘작년’, ‘최근 3개월’, ‘2025년 3월’처럼 기간을 알려 주세요.",
        )
    period: dict[str, Any] | None = None
    if reading.period:  # a period written in the question beats the one that came with the selection
        period = {"start": reading.period.start, "end": reading.period.end, "expression": reading.period.expression, "basis": "question"}
    elif request["period"]:
        period = {**request["period"], "expression": None, "basis": "context"}
    return Resolution(tuple(context_ids), tuple(only), period, overrode)


def build_plan(ds: Dataset, request: dict[str, Any], resolution: Resolution) -> AnswerPlan:
    ids = list(resolution.context_ids or resolution.evidence_only)
    contexts = resolve_all(ds, ids)
    period = None
    basis = None
    if resolution.period:
        period = ResolvedPeriod(resolution.period["start"], resolution.period["end"], resolution.period.get("expression") or "")
        basis = resolution.period["basis"]
    pool = evidence_pool(ds, contexts, resolution.evidence_only if resolution.context_ids else (), period)
    return AnswerPlan(request["question"], tuple(contexts), pool.ids, period, basis, pool.excluded_by_period)


def result_of_draft(ds: Dataset, plan: AnswerPlan, resolution: Resolution, draft: Draft, message_id: str, generated_by: str) -> ChatResult:
    return ChatResult(
        outcome=draft.status,  # type: ignore[arg-type]
        message_id=message_id,
        answer=draft.text,
        reason=draft.reason,
        sources=list(draft.evidence_ids),
        citations=list(draft.citations),
        graph_targets=list(draft.targets),
        applied=applied_scope(ds, plan, draft, overrode_context=resolution.overrode_context),
        choices=[],
        action=None,
        metadata=meta(ds, generated_by),
    )


def result_of_terminal(ds: Dataset, terminal: Terminal, resolution: Resolution, message_id: str, generated_by: str) -> ChatResult:
    period = None
    if resolution.period:
        period = ChatAppliedPeriod(start=resolution.period["start"], end=resolution.period["end"], basis=resolution.period["basis"], expression=resolution.period.get("expression"))
    return ChatResult(
        outcome=terminal.outcome,  # type: ignore[arg-type]
        message_id=message_id,
        answer=terminal.text,
        reason=terminal.reason,
        sources=[],
        citations=[],
        graph_targets=[],
        applied=ChatApplied(
            companies=[],
            issues=[],
            period=period,
            graph_version=ds.graph_version,
            data_as_of=ds.as_of,
            question_overrode_context=False,
        ),
        choices=[ChatChoice(id=i, label=label) for i, label in terminal.choices],
        action=ChatAction(kind=terminal.action[0], label=terminal.action[1]) if terminal.action else None,  # type: ignore[arg-type]
        metadata=meta(ds, generated_by),
    )
