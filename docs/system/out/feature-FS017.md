# FS017 · 개인화 관계 그래프

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 17 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/web/tests/personal-filter.test.ts, prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:27 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv) — 개인화 관계 그래프: 로그인 회원의 보유종목과 관심종목을 기준으로 개인화 관계 그래프를 제공한다. 개인화 그래프에는 기준 기업과 해당 기업에 연결된 관련 기업, 이슈, 제품 및 관계가 표시된다. 보유종목과 관심종목은 하나의 그래프에서 함께 표시할 수 있으며 각 기업 노드에는 보유·관심 상태를 구분하여 표시한다. 사용자는 전체, 보유, 관심 필터를 통해 개인화 그래프의 기준 종목 범위를 변경할 수 있다.
- [docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv) — 개인화 관계 그래프: 로그인 회원의 보유종목과 관심종목을 기준으로 개인화 관계 그래프를 제공한다. 개인화 그래프는 기업 노드와 이슈 노드로 구성하며, 기준 기업과 관련 기업 및 관련 이슈의 관계를 표시한다. 기업 노드는 보유·관심 상태를 구분하여 표시하고, 이슈 노드는 국내 / 국제 속성을 가진다. 사용자는 전체 / 보유 / 관심 필터를 이용하여 그래프의 기준 종목 범위를 변경할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:80 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-COM-04](screen-D-COM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | 6.1.2, 6.10.1, 6.3.7, 6.5.1, 6.5.2, 6.5.3, 6.5.10, 6.7.5, 6.6.3, 6.6.7, 6.4.2 | 공개(all) / 회원 본인(personal) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
