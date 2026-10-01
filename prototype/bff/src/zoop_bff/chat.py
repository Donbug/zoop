"""Example (LLM-free) answers built only from approved evidence quotes of the selected context."""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass

from .audit import Clock
from .dataset import COMPANY_LINKS, Dataset, EvidenceRec
from .errors import ApiError
from .graph import edge_evidence_via
from .schemas import Citation, GraphTarget
from .statedb import StateDb, utc_iso

GENERATED_BY = "bff-example-v0"
MAX_CITATIONS = 3
_PREDICTION = re.compile(r"예측|전망|오를|내릴|호재|악재|매수|매도|추천|목표가|수익률")
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")

DISCLAIMER = "인용한 문장은 원인이나 투자 판단을 뜻하지 않아요."


@dataclass
class ChatSession:
    id: str
    owner_id: str
    context_ids: list[str]
    created_at: str
    messages: int = 0


class ChatStore:
    """Conversations live in the state database (``chat_sessions``/``chat_messages``): a restart keeps them and
    the admin transcript view (requirement 75) reads the same rows. Only the owner can post to a session."""

    def __init__(self, db: StateDb, clock: Clock):
        self._db = db
        self._clock = clock

    def create(self, owner_id: str, owner_kind: str, context_ids: list[str]) -> ChatSession:
        session = ChatSession(f"chat-{secrets.token_hex(8)}", owner_id, context_ids, utc_iso(self._clock.now()))
        self._db.execute(
            "INSERT INTO chat_sessions(id,owner_id,owner_kind,context_ids,created_at) VALUES (?,?,?,?,?)",
            (session.id, owner_id, owner_kind, json.dumps(context_ids), session.created_at),
        )
        return session

    def owned(self, session_id: str, owner_id: str) -> ChatSession:
        row = self._db.one("SELECT * FROM chat_sessions WHERE id=?", (session_id,))
        if row is None:
            raise ApiError(404, "chat_session_not_found", "대화를 찾을 수 없습니다.")
        if row["owner_id"] != owner_id:
            raise ApiError(403, "forbidden", "다른 사용자의 대화에는 접근할 수 없습니다.")
        return ChatSession(row["id"], row["owner_id"], json.loads(row["context_ids"]), row["created_at"], row["messages"])

    def record_exchange(
        self, session: ChatSession, question: str, answer: Answer, context_ids: list[str], company_ids: list[str]
    ) -> str:
        """Store one question and its answer; returns the new message id (``<session>-m<n>``)."""
        with self._db.transaction() as conn:
            conn.execute("UPDATE chat_sessions SET messages = messages + 1 WHERE id=?", (session.id,))
            seq = int(conn.execute("SELECT messages FROM chat_sessions WHERE id=?", (session.id,)).fetchone()["messages"])
            message_id = f"{session.id}-m{seq}"
            conn.execute(
                "INSERT INTO chat_messages(id,session_id,seq,at,question,answer,status,reason,context_ids,company_ids,citation_count)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    session.id,
                    seq,
                    utc_iso(self._clock.now()),
                    question,
                    answer.text,
                    answer.status,
                    answer.reason,
                    json.dumps(context_ids),
                    json.dumps(company_ids),
                    len(answer.citations),
                ),
            )
        session.messages = seq
        return message_id


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


@dataclass(frozen=True)
class Answer:
    status: str
    text: str
    reason: str | None
    evidence_ids: tuple[str, ...]
    targets: tuple[GraphTarget, ...]
    citations: tuple[Citation, ...]


def _citation(ds: Dataset, ev: EvidenceRec) -> Citation:
    article = ds.article_for(ev.article_id, ev.article_version)
    return Citation(
        evidence_id=ev.id,
        quote=ev.quote,
        article_title=article.title if article else None,
        publisher=article.publisher if article else None,
        url=article.url if article else None,
    )


def _insufficient(reason: str, text: str) -> Answer:
    return Answer("insufficient_evidence", f"{text}\n{DISCLAIMER}", reason, (), (), ())


def compose_answer(ds: Dataset, question: str, contexts: list[ContextNode]) -> Answer:
    if not contexts:
        return _insufficient(
            "no_context",
            "선택된 맥락이 없어 근거를 찾을 수 없습니다. 그래프에서 기업·사건·관계를 선택한 뒤 질문해 주세요.",
        )
    if _PREDICTION.search(question):
        return _insufficient(
            "prediction_or_advice_not_supported",
            "주가 예측·매매 판단·호재/악재 평가는 제공하지 않습니다. 선택한 맥락의 근거 인용만 확인할 수 있습니다.",
        )
    ordered = list(dict.fromkeys(e for c in contexts for e in c.evidence_ids))
    usable = [ds.evidence[e] for e in ordered if e in ds.evidence and ds.evidence[e].quote_verified is not False]
    if not usable:
        reason = "quote_verification_failed" if ordered else "no_evidence_for_context"
        return _insufficient(
            reason,
            "선택한 맥락에서 원문과 대조되는 승인 근거를 찾지 못해 답변을 보류합니다.",
        )
    tokens = [t.lower() for t in _TOKEN.findall(question)]
    scores = {ev.id: sum(t in ev.quote.lower() for t in tokens) for ev in usable}
    ranked = sorted(usable, key=lambda ev: -scores[ev.id])
    matching = [ev for ev in ranked if scores[ev.id] > 0]
    chosen = (matching or ranked)[:MAX_CITATIONS]  # no overlap at all: fall back to the context's own quotes
    citations = tuple(_citation(ds, ev) for ev in chosen)
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
        if c.kind != "evidence":
            targets[(c.kind, c.id)] = GraphTarget(id=c.id, kind=c.kind)  # type: ignore[arg-type]
    for ev in chosen:
        for issue_id in ds.evidence_issues.get(ev.id, ()):
            targets.setdefault(("issue", issue_id), GraphTarget(id=issue_id, kind="issue"))
    return Answer(
        "answered",
        "\n".join(lines),
        None,
        tuple(ev.id for ev in chosen),
        tuple(targets.values()),
        citations,
    )
