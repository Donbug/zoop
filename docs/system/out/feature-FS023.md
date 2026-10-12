# FS023 · 기업 간 관계 확인(기업 간 간선 클릭)

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 23 |
| 의미 기준 요구사항 | 23 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:33 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [이력 정의] [docs/evidence/raw/functional-spec_2026-10-10/03-메인-그래프.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/03-메인-그래프.csv) — 기업 간 관계 확인(기업 간 간선 클릭): 사용자가 두 기업이 연결된 이유를 이해할 수 있도록 기업 간 관계선을 선택하면 관계 설명을 제공해야 한다. 공급·고객·경쟁·투자 등 확인된 관계 유형과 관계의 방향, 관련 사업·제품 범위, 현재 상태 및 확인 시점을 표시해야함.
- [docs/evidence/raw/functional-spec_2026-10-10/04-메인그래프-v2.csv:94 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/04-메인그래프-v2.csv) — 기업 간 관계 확인(기업 간 간선 클릭): 사용자가 두 기업이 연결된 이유를 이해할 수 있도록 기업 간 관계선을 선택하면 관계 설명을 제공해야 한다. 공급·고객·경쟁·투자 등 확인된 관계 유형과 관계의 방향, 관련 사업·제품 범위, 현재 상태 및 확인 시점을 표시해야함.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:202 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.6.8 | BE | (BE) 기업 간 관계 상세 조회 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.24 | FE | (FE) D-GRP-04 간선 상세 패널 및 관계 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.27 | 공통/통합 | 메인 그래프 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-GRP-04](screen-D-GRP-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompanyRelation](../../api/out/zoop-api-spec.md#getcompanyrelation) | GET /api/v1/graph/edges/{id} | 6.1.2, 6.11.1, 6.6.8, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.5.1 | 공개 |

## 확인 필요

- HISTORICAL_DETAIL_SUPERSEDED: 옛 시트 03-메인-그래프.csv의 정의는 이력으로 보존한다. 현행 상세는 04-메인그래프-v2.csv이며 같은 번호라도 의미가 다를 수 있어 번호 일치로 합치지 않는다.
- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A91:B103와 현행 상세 구획 제목 행 [92]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
- REQUIREMENT_TITLE_REVIEW: 명세 '기업 간 관계 확인(기업 간 간선 클릭)' ↔ 요구사항 23 '기업 간 관계 확인(기업 간 간선 클릭) '. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
