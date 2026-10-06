# FS037 · 종목 목록·검색 및 상세 진입

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 ·  |
| 요구사항 번호 |  |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/web/tests/companies-menu.test.tsx, prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:47 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv) — 종목 목록·검색 및 상세 진입: 사용자는 상단 메뉴의 종목을 선택해 MVP 분석 대상 종목 목록을 확인할 수 있어야 한다. 사용자는 기업명 또는 티커로 종목을 검색하고, 목록 또는 검색 결과에서 종목을 선택해 해당 기업 상세 페이지로 이동할 수 있어야 한다. 관심 종목 추가·해제를 할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:96 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-WAT-01](screen-D-WAT-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-COM-03](screen-D-COM-03.md) · [M-COM-02](screen-M-COM-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [searchCompanies](../../api/out/zoop-api-spec.md#searchcompanies) | GET /api/v1/companies | 6.1.2, 6.10.1, 6.3.4, 6.5.10, 6.6 | 공개 |
