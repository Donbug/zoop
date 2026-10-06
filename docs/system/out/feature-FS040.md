# FS040 · 차트와 타임라인 기간 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 검토 중 |
| 요구사항 번호 | 40 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:50 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv) — 차트와 타임라인 기간 조회: 시스템은 기업별 1일, 1주, 1개월, 1년 기간을 제공한다. 사용자가 차트 또는 타임라인에서 기준 시점을 선택하면 해당 시점까지 공개·유효한 이슈를 함께 표시한다. 기본 기간은 1개월, 기본 기준 시점은 최신 제공 시점이다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:78 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-COM-04](screen-D-COM-04.md) · [D-COM-01b](screen-D-COM-01b.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md) · [D-COM-02](screen-D-COM-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | 6.1.2, 6.10.1, 6.3.7, 6.5.1, 6.5.2, 6.5.3, 6.5.10, 6.7.5, 6.6.3, 6.6.7, 6.4.2 | 공개(all) / 회원 본인(personal) |
| [getCompanyPrices](../../api/out/zoop-api-spec.md#getcompanyprices) | GET /api/v1/companies/{id}/prices | 6.1.2, 6.10.1, 6.6.1, 6.6.3 | 공개 |
| [listEvents](../../api/out/zoop-api-spec.md#listevents) | GET /api/v1/events | 6.1.2, 6.10.1, 6.6.3, 6.6.4, 6.4.3 | 공개 |
| [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | 6.1.2, 6.6.3, 6.6.4, 6.4.2, 6.10.1 | 공개 |
