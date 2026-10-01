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
    # 확장 실제 기사(poc-real-inspect)에 나온 역할 어휘. 고유명사·서술형 문구는 번역하지 않고 원문 그대로 둔다.
    "participant": "참여사",
    "provider": "제공사",
    "investor": "투자사",
    "builder": "구축사",
    "announcer": "발표사",
    "co announcer": "공동 발표사",
    "model provider": "모델 제공사",
    "approved entity": "승인 대상",
    "approver": "승인 주체",
    "cloud provider": "클라우드 제공사",
    "ai cloud provider": "AI 클라우드 제공사",
    "cloud platform": "클라우드 플랫폼",
    "cloud platform provider": "클라우드 플랫폼 제공사",
    "system vendor": "시스템 공급사",
    "issuer": "발행사",
    "gpu provider": "GPU 제공사",
    "gpu technology provider": "GPU 기술 제공사",
    "cpu provider": "CPU 제공사",
    "attendee": "참석자",
    "contract counterparty": "계약 상대방",
    "counterparty": "상대방",
    "party": "당사자",
    "partnership party": "제휴 당사자",
    "collaboration party": "협력 당사자",
    "solution provider": "솔루션 제공사",
    "co provider": "공동 제공사",
    "ai infrastructure builder": "AI 인프라 구축사",
    "infrastructure provider": "인프라 제공사",
    "technology partner": "기술 파트너",
    "ecosystem partner": "생태계 파트너",
    "ecosystem provider": "생태계 제공사",
    "security partner": "보안 파트너",
    "software partner": "소프트웨어 파트너",
    "utility partner": "전력 파트너",
    "expansion partner": "확장 파트너",
    "joint lab partner": "공동 연구소 파트너",
    "research university partner": "연구 대학 파트너",
    "designated partner": "지정 파트너",
    "first industry partner": "첫 산업 파트너",
    "founder": "창업자",
    "ceo": "CEO",
    "co founding investor": "공동 설립 투자사",
    "unveiler": "공개 주체",
    "releaser": "공개 주체",
    "introducer": "소개 주체",
    "hardware provider": "하드웨어 제공사",
    "hardware platform": "하드웨어 플랫폼",
    "software provider": "소프트웨어 제공사",
    "runtime provider": "런타임 제공사",
    "agent runtime provider": "에이전트 런타임 제공사",
    "accelerator provider": "가속기 제공사",
    "accelerated computing provider": "가속 컴퓨팅 제공사",
    "confidential computing provider": "기밀 컴퓨팅 제공사",
    "computing platform": "컴퓨팅 플랫폼",
    "libraries provider": "라이브러리 제공사",
    "blueprint provider": "블루프린트 제공사",
    "hub provider": "허브 제공사",
    "scada provider": "SCADA 제공사",
    "benchmark provider": "벤치마크 제공사",
    "benchmark subject": "벤치마크 대상",
    "benchmark organizer": "벤치마크 주최자",
    "benchmark organization": "벤치마크 기관",
    "benchmark platform": "벤치마크 플랫폼",
    "vehicle platform provider": "차량 플랫폼 제공사",
    "autonomous vehicle platform provider": "자율주행 플랫폼 제공사",
    "hbm4 memory supplier": "HBM4 메모리 공급사",
    "professor": "교수",
    "co organizer": "공동 주최자",
    "coalition organizer": "연합 주최자",
    "consortium leader": "컨소시엄 주관사",
    "initiative leader": "이니셔티브 주도 주체",
    "seller": "판매사",
    "contractor": "계약사",
    "disclosing company": "공시 기업",
    "disclosure filer": "공시 제출사",
    "filer": "제출사",
    "mou signatory": "MOU 체결사",
    "visitor": "방문자",
    "strategy author": "전략 작성 주체",
    "recipient of support": "지원 수혜자",
    "recipients": "수신자",
    "beneficiary": "수혜자",
    "certification recipient": "인증 취득사",
    "announcing company": "발표 기업",
    "launching company": "출시 기업",
    "expanding company": "확장 기업",
    "demonstrated company": "시연 기업",
    "established company": "설립 기업",
    "product developer": "제품 개발사",
    "model developer": "모델 개발사",
    "ai model developer": "AI 모델 개발사",
    "co developer": "공동 개발사",
    "applicant": "신청자",
    "requester": "요청자",
    "subscriber": "가입자",
    "participating storage vendor": "참여 스토리지 공급사",
    "acquirer": "인수사",
    "target": "대상",
    "designating party": "지정 주체",
    "ai platform company": "AI 플랫폼 기업",
    "ai platform": "AI 플랫폼",
    "ai research lab": "AI 연구소",
    "moderator": "진행자",
    "supporter": "지원 주체",
    "promoter": "추진 주체",
    "portfolio owner": "포트폴리오 보유사",
    "owner": "소유주",
    "keynote participant": "기조연설 참여자",
    "keynote host": "기조연설 주최자",
    "validator": "검증 주체",
    "deployer": "배포 주체",
    "tester": "시험 주체",
    "regulator": "규제 기관",
    "project owner": "프로젝트 발주처",
    "pilot operator": "시범 운영사",
    "demonstrators": "시연 주체",
    "showcaser": "전시 주체",
    "venue": "장소",
    "parent": "모회사",
    "subsidiary": "자회사",
    "expanding": "확장 주체",
    "extending": "확장 주체",
    "represented by speaker": "발표자 소속 기업",
}


def role_display(role: str | None) -> str | None:
    """Role text for detail panels (R5): the Korean label when the vocabulary is known, otherwise the article's
    original text unchanged. Unknown phrases are never translated or guessed."""
    if not role:
        return role
    return role_label(role) or role


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
