# FS042 · 재무와 실적 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 42 |
| API 대응 | 기존 API로 지원 |
| 사유 | 10-08 상세 FS042는 FS0?? 시점 그래프 ID를 승계해 getCompanyGraphAsOf에 연결한다. 목차/요구42/옛 판정은 재무·실적 의미를 유지하므로 getCompanyFinancials는 충돌 별도 추적한다. 재무 폐기·시점그래프 완료·팀 승인으로 승격하지 않는다. |
| 프로토타입 문서 판정 | 충돌(시점그래프 부분·재무 미구현) |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:52 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/06-기업-상세-타임라인.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/06-기업-상세-타임라인.csv) — 시점 기반 관계 그래프 조회: 시스템은 기업 상세에서 선택한 기준 시점의 기업 관계 그래프를 제공한다. 기업의 비교적 고정적인 구조 관계와, 해당 시점까지 공개되어 유효한 이슈 기반 관계를 구분하여 함께 표시한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:111 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.7.5 | BE | (BE) 시점 기반 관계 그래프 조회 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |
| 6.7.11 | FE | (FE) D-COM-04 기업 중심 관계 그래프 및 시점 조회 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |
| 6.7.12 | FE | (FE) D-COM-05·06 사건 타임라인·차트·그래프 선택 동기화 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |
| 6.7.13 | 공통/통합 | 기업 상세·타임라인 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |

## 화면·목표 API

[D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-01b](screen-D-COM-01b.md) · [D-COM-02](screen-D-COM-02.md) · [D-COM-04](screen-D-COM-04.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompanyFinancials](../../api/out/zoop-api-spec.md#getcompanyfinancials) | GET /api/v1/companies/{id}/financials | 6.1.2, 6.11.1 | 공개 |
| [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | 6.1.2, 6.11.1, 6.7.2, 6.7.3, 6.7.4, 6.7.5, 6.7.8, 6.7.10, 6.7.11, 6.7.12, 6.5.1 | 공개 |

## 확인 필요

- SPEC_ID_MEANING_CONFLICT: 목차 FS042는 재무·실적, 상세 FS042는 FS0??를 승계한 시점 관계 그래프다. ID 정리는 완료됐지만 재무 폐기 선언은 없다. 두 의미를 별도로 추적한다.
