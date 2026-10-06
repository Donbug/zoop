# FS038 · 기업 상세 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 38 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:48 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv) — 기업 상세 조회: 시스템은 메뉴의 종목 목록에서 선택하거나, 그래프 기업 노드의 패널에서 `상세 페이지 이동`을 선택하거나, 직접 URL로 진입한 기업의 상세를 표시한다. 기업 개요, 시세·차트, 이슈 타임라인, 시점 기반 관계 그래프, 핵심 재무, 뉴스·공시, 가상 보유 정보를 독립 영역으로 표시한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:56 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-03](screen-D-GRP-03.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-03](screen-D-COM-03.md) · [D-COM-04](screen-D-COM-04.md) · [M-COM-02](screen-M-COM-02.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-COM-01b](screen-D-COM-01b.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md) · [D-COM-02](screen-D-COM-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompany](../../api/out/zoop-api-spec.md#getcompany) | GET /api/v1/companies/{id} | 6.1.2, 6.10.1, 6.5.4, 6.6.1, 6.6.7 | 공개 |
| [getCompanyQuote](../../api/out/zoop-api-spec.md#getcompanyquote) | GET /api/v1/companies/{id}/quote | 6.1.2, 6.10.1, 6.5.4, 6.6.1, 6.4.10 | 공개 |
| [getCompanyPrices](../../api/out/zoop-api-spec.md#getcompanyprices) | GET /api/v1/companies/{id}/prices | 6.1.2, 6.10.1, 6.6.1, 6.6.3 | 공개 |
| [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | 6.1.2, 6.6.3, 6.6.4, 6.4.2, 6.10.1 | 공개 |
