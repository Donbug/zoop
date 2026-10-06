# FS065 · 기업 및 사용자 통계 조사 및 확인

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P2 · 미기재 |
| 요구사항 번호 | 77 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:76 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — 기업 및 사용자 통계 조사 및 확인: 관리자는 인증된 별도 관리자 패널에서 관심 종목, 고정 Mock 보유 종목, 자주 확인한 노드 등을 요약 및 기업별 통계로 확인한다. 온보딩 완료율, 그래프 노드·간선 클릭률, 브리핑 조회율 및 관심도, AI 질문 이용률을 포함하되 지표별 집계 정의가 확정되고 필요한 원천 자료가 확보된 범위에서 제공한다. 통계에 사용자의 실명 등 개인 식별 정보를 포함하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:260 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[M-GRP-01](screen-M-GRP-01.md) · [D-GRP-01](screen-D-GRP-01.md) · [A-ADM-02](screen-A-ADM-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [recordInteractionEvents](../../api/out/zoop-api-spec.md#recordinteractionevents) | POST /api/v1/telemetry | 6.1.2, 6.10.1, 6.9.1 | 회원 또는 비회원 세션 |
| [getInsightsOverview](../../api/out/zoop-api-spec.md#getinsightsoverview) | GET /api/v1/admin/insights/overview | 6.1.2, 6.10.1, 6.9.1 | 관리자(작업별 권한) |
| [getInsightsSummary](../../api/out/zoop-api-spec.md#getinsightssummary) | GET /api/v1/admin/insights/summary | 6.1.2, 6.10.1, 6.9.1 | 관리자(작업별 권한) |
| [listCompanyInsights](../../api/out/zoop-api-spec.md#listcompanyinsights) | GET /api/v1/admin/insights/companies | 6.1.2, 6.10.1, 6.9.1 | 관리자(작업별 권한) |
| [getCompanyInsights](../../api/out/zoop-api-spec.md#getcompanyinsights) | GET /api/v1/admin/insights/companies/{company_id} | 6.1.2, 6.10.1, 6.9.1 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '기업 및 사용자 통계 조사 및 확인' ↔ 요구사항 77 '기업 및 사용자 통계 조사와 확인'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
