# FS027 · 관심 종목 수정

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 27 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv:149 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv) — 관심 종목 수정: 사용자는 사이드바 또는 기업 노드를 클릭하여 관심 종목을 선택 및 해제할 수 있다.
- [docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv:154 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv) — 관심 종목 수정: 사용자는 사이드바 또는 기업 노드를 클릭하여 관심 종목을 선택 및 해제할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:27 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-MY-01](screen-D-MY-01.md) · [D-GRP-03](screen-D-GRP-03.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [setWatchlistCompany](../../api/out/zoop-api-spec.md#setwatchlistcompany) | PUT /api/v1/me/watchlist/{id} | 6.1.2, 6.10.1, 6.5.11 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
