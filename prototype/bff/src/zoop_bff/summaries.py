"""Short Korean edge labels for the graph, derived only from approved data.

INVOLVES shows the role the article gave the company (roles are free text in the article's language,
so known English values are mapped to Korean and Korean text is kept, shortened to its first clause);
STRUCTURALLY_RELATED_TO shows the catalog relation kinds behind it; nothing else is ever invented.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .dataset import BasisRec, EdgeRec

ROLE_FALLBACK = "직접 관련"
STRUCTURAL_FALLBACK = "구조적 관계"
FOLLOWS_SUMMARY = "후속 사건"
_MAX_ROLE_CHARS = 14

# Keys are normalized (lower case, ``-``/``_`` as spaces). Values seen in real PoC output plus their plain variants.
ROLE_KO = {
    "technology provider": "기술 제공사",
    "system provider": "시스템 공급사",
    "platform provider": "플랫폼 제공사",
    "rollout provider": "출시 제공사",
    "service provider": "서비스 제공사",
    "collaborator": "협력사",
    "collaborators": "협력사",
    "partner": "파트너",
    "co launcher": "공동 출시사",
    "subject": "주체",
    "submitter": "제출자",
    "developer": "개발사",
    "adopter": "도입사",
    "system developer": "시스템 개발사",
    "operator": "운영사",
    "ai factory operator": "AI 팩토리 운영사",
    "utility program operator": "전력 프로그램 운영사",
    "integrator": "통합 사업자",
    "researcher": "연구자",
    "research institution": "연구기관",
    "benchmarker": "벤치마크 수행",
    "demonstrator": "시연 주체",
    "host": "주최자",
    "certification holder": "인증 보유사",
    "issuing agency": "발행 기관",
    "parent agency": "상위 기관",
    "signer": "서명 당사자",
    "speaker": "발표자",
    "presenter": "발표자",
    "recipient": "수신자",
    "company": "기업",
    "user": "사용자",
    "planner": "기획자",
    "platform": "플랫폼",
    "manufacturer": "제조사",
    "supplier": "공급사",
    "customer": "고객사",
    "organizer": "주최자",
}

# PoC structural basis kinds (``structural_edge_eligible``), in display order.
BASIS_KO = {
    "SUPPLIES": "공급",
    "PRODUCES": "생산",
    "USES": "사용",
    "MANUFACTURES": "제조",
    "BUYS": "구매",
    "DEVELOPS": "개발",
}

_HANGUL = re.compile(r"[가-힣]")
_CLAUSE = re.compile(r"[,;]")
_SPACES = re.compile(r"[\s_-]+")


def _normalize(text: str) -> str:
    return _SPACES.sub(" ", text).strip().lower()


def role_label(role: str) -> str | None:
    """Korean label for one article role; ``None`` when it cannot be shown without guessing."""
    clause = _CLAUSE.split(role, maxsplit=1)[0].strip()
    if not clause:
        return None
    if _HANGUL.search(clause):
        return clause if len(clause) <= _MAX_ROLE_CHARS else clause[: _MAX_ROLE_CHARS - 1].rstrip() + "…"
    parts = [_normalize(p) for p in re.split(r"/|\s+and\s+", clause, flags=re.IGNORECASE)]
    return "·".join(ROLE_KO[p] for p in parts) if all(p in ROLE_KO for p in parts) else None


def _role_summary(roles: Iterable[str]) -> str:
    return next((label for label in map(role_label, roles) if label), ROLE_FALLBACK)


def _basis_summary(basis: Iterable[BasisRec]) -> str:
    kinds = {b.relation_type.upper() for b in basis}
    labels = [ko for kind, ko in BASIS_KO.items() if kind in kinds]
    return "·".join(labels) if labels else STRUCTURAL_FALLBACK


def edge_summary(edge: EdgeRec) -> str:
    """The label shown on a graph edge; also returned by the edge detail endpoint."""
    if edge.relation_type == "STRUCTURALLY_RELATED_TO":
        return _basis_summary(edge.basis)
    if edge.relation_type == "FOLLOWS":
        return FOLLOWS_SUMMARY
    if edge.relation_type == "SHARES_ISSUE":
        return f"같은 사건 {len(edge.via)}건"
    return _role_summary(edge.roles)
