# FS020 · 기업 노드 정보

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 20 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:30 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv) — 기업 노드 정보: 사용자가 선택한 기업의 현황과 관련 이슈를 빠르게 이해할 수 있도록 기업 정보 패널을 제공.기업의 기본 정보, 시세, 주요 재무 정보, AI 요약, 직접·간접 이슈 및 관련 기업을 표시하고, 상세 정보는 기업 상세페이지에서 확인할 수 있어야 한다.
- [docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv:53 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv) — 기업 노드 정보: 사용자가 기업 노드를 선택하면 해당 기업의 기본 정보, 시세, 주요 재무, AI 요약, 관련 이슈, 관련 기업을 정보 패널에 표시한다. 관련 이슈에는 국내·국제 속성을 표시하고 관련 뉴스 요약 및 근거 자료로 이동할 수 있도록 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:97 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-03](screen-D-GRP-03.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-03](screen-D-COM-03.md) · [D-COM-04](screen-D-COM-04.md) · [M-COM-02](screen-M-COM-02.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompany](../../api/out/zoop-api-spec.md#getcompany) | GET /api/v1/companies/{id} | 6.1.2, 6.10.1, 6.5.4, 6.6.1, 6.6.7 | 공개 |
| [getCompanyQuote](../../api/out/zoop-api-spec.md#getcompanyquote) | GET /api/v1/companies/{id}/quote | 6.1.2, 6.10.1, 6.5.4, 6.6.1, 6.4.10 | 공개 |
| [getCompanyMetrics](../../api/out/zoop-api-spec.md#getcompanymetrics) | GET /api/v1/companies/{id}/metrics | 6.1.2, 6.10.1, 6.5.4, 6.6.5 | 공개 |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
