# FS037 · 종목 목록·검색 및 상세 진입

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 ·  |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 |  |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/web/tests/companies-menu.test.tsx, prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:47 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/06-기업-상세-타임라인.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/06-기업-상세-타임라인.csv) — 종목 목록·검색 및 상세 진입: 사용자는 상단 메뉴의 종목을 선택해 MVP 분석 대상 종목 목록을 확인할 수 있어야 한다. 사용자는 기업명 또는 티커로 종목을 검색하고, 목록 또는 검색 결과에서 종목을 선택해 해당 기업 상세 페이지로 이동할 수 있어야 한다. 관심 종목 추가·해제를 할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:102 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.4.7 | FE | (FE) D-STK-01 종목 검색·사이드바 및 관심종목 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.1 | BE | (BE) 종목 목록·검색 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.13 | 공통/통합 | 기업 상세·타임라인 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |

## 화면·목표 API

[D-WAT-01](screen-D-WAT-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-COM-03](screen-D-COM-03.md) · [M-COM-02](screen-M-COM-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [searchCompanies](../../api/out/zoop-api-spec.md#searchcompanies) | GET /api/v1/companies | 6.1.2, 6.11.1, 6.3.3, 6.4.5, 6.4.7, 6.6.11, 6.6.21, 6.6.23, 6.7.1 | 공개 |
