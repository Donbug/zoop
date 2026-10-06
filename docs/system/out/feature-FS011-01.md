# FS011-01 · 관심종목 검색

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 11 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:20 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv) — 관심종목 검색: 로그인 회원이 종목명 또는 종목 코드를 입력하고 검색하면 등록 가능한 종목을 조회하여 선택 후보로 제공한다. 검색만으로 관심종목을 저장하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:24 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-WAT-01](screen-D-WAT-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-COM-03](screen-D-COM-03.md) · [M-COM-02](screen-M-COM-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [searchCompanies](../../api/out/zoop-api-spec.md#searchcompanies) | GET /api/v1/companies | 6.1.2, 6.10.1, 6.3.4, 6.5.10, 6.6 | 공개 |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '관심종목 검색' ↔ 요구사항 11 '관심종목 검색과 추천 조회'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
