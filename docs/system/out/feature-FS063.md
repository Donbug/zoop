# FS063 · 뉴스와 시장 데이터 연동

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 75 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:74 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/10-외부-연동.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/10-외부-연동.csv) — 뉴스와 시장 데이터 연동: 기업·기간에 맞는 시세·재무·뉴스·공시와 근거를 실제 제공 범위와 접근 권한이 확인된 공급원에서 조회한다. 출처·자료 기준 시점·미제공·지연·오류 상태를 구분해 전달한다. 원본의 토스 API·뉴스 크롤링은 연동 후보이며 실제 이용 가능성이 확인된 것으로 간주하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:253 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-03](screen-D-GRP-03.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-COM-03](screen-D-COM-03.md) · [M-COM-02](screen-M-COM-02.md) · [D-COM-02](screen-D-COM-02.md) · [D-SEN-01](screen-D-SEN-01.md) · [A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompanyQuote](../../api/out/zoop-api-spec.md#getcompanyquote) | GET /api/v1/companies/{id}/quote | 6.1.2, 6.10.1, 6.5.4, 6.6.1, 6.4.10 | 공개 |
| [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | 6.1.2, 6.10.1, 6.5.5, 6.6.6, 6.4.3, 6.4.10, 6.4.11 | 공개 |
| [getPipelineOverview](../../api/out/zoop-api-spec.md#getpipelineoverview) | GET /api/v1/admin/pipeline/overview | 6.1.2, 6.10.1, 6.4.5, 6.4.6, 6.4.10, 6.9.3 | 관리자(작업별 권한) |
| [createAnalysisJob](../../api/out/zoop-api-spec.md#createanalysisjob) | POST /api/v1/admin/jobs | 6.1.2, 6.10.1, 6.4.5, 6.4.6, 6.4.10, 6.4.11 | 관리자(작업별 권한) |
