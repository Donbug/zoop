# FS063 · 뉴스와 시장 데이터 연동

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 75 |
| 의미 기준 요구사항 | 75 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:70 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/10-외부-연동.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/10-외부-연동.csv) — 뉴스와 시장 데이터 연동: 기업·기간에 맞는 시세·재무·뉴스·공시와 근거를 실제 제공 범위와 접근 권한이 확인된 공급원에서 조회한다. 출처·자료 기준 시점·미제공·지연·오류 상태를 구분해 전달한다. 원본의 토스 API·뉴스 크롤링은 연동 후보이며 실제 이용 가능성이 확인된 것으로 간주하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:267 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.5.6 | BE | (BE) 뉴스와 시장 데이터 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.5.8 | 공통/통합 | 데이터 관리·외부 연동 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-GRP-03](screen-D-GRP-03.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-COM-03](screen-D-COM-03.md) · [M-COM-02](screen-M-COM-02.md) · [D-COM-02](screen-D-COM-02.md) · [D-SEN-01](screen-D-SEN-01.md) · [A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompanyQuote](../../api/out/zoop-api-spec.md#getcompanyquote) | GET /api/v1/companies/{id}/quote | 6.1.2, 6.11.1, 6.6.4, 6.6.23, 6.6.26, 6.7.2, 6.7.8, 6.7.10, 6.7.11, 6.5.6 | 공개 |
| [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.6, 6.7.9, 6.5.2, 6.5.6, 6.5.7 | 공개 |
| [getPipelineOverview](../../api/out/zoop-api-spec.md#getpipelineoverview) | GET /api/v1/admin/pipeline/overview | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4, 6.5.5, 6.5.6 | 관리자(작업별 권한) |
| [listGraphRounds](../../api/out/zoop-api-spec.md#listgraphrounds) | GET /api/v1/admin/pipeline/rounds | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4, 6.5.5, 6.5.6 | 관리자(작업별 권한) |
| [startGraphRound](../../api/out/zoop-api-spec.md#startgraphround) | POST /api/v1/admin/pipeline/rounds | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4, 6.5.5, 6.5.6 | 관리자(작업별 권한) |
| [getGraphRound](../../api/out/zoop-api-spec.md#getgraphround) | GET /api/v1/admin/pipeline/rounds/{roundId} | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4, 6.5.5, 6.5.6 | 관리자(작업별 권한) |
| [retryGraphRound](../../api/out/zoop-api-spec.md#retrygraphround) | POST /api/v1/admin/pipeline/rounds/{roundId}/retry | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4, 6.5.5, 6.5.6 | 관리자(작업별 권한) |
| [createAnalysisJob](../../api/out/zoop-api-spec.md#createanalysisjob) | POST /api/v1/admin/jobs | 6.1.2, 6.11.1, 6.5.4, 6.5.5, 6.5.6, 6.5.7 | 관리자(작업별 권한) |
