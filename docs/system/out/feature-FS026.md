# FS026 · 사이드바 기업 선택

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 26 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:36 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv:135 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv) — 사이드바 기업 선택: 사용자는 사이드바에서 선택한 기업을 중심으로 그래프를 확대 및 이동 시킬 수 있다.
- [docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv:139 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv) — 사이드바 기업 선택: 사용자는 메인 화면의 사이드바에서 보유종목 및 관심종목 목록을 확인하고 기업을 선택할 수 있다. 선택한 기업이 현재 그래프에 존재하면 해당 노드를 중심으로 이동·확대한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:82 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-COM-04](screen-D-COM-04.md) · [D-WAT-01](screen-D-WAT-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md) · [D-COM-03](screen-D-COM-03.md) · [M-COM-02](screen-M-COM-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | 6.1.2, 6.10.1, 6.3.7, 6.5.1, 6.5.2, 6.5.3, 6.5.10, 6.7.5, 6.6.3, 6.6.7, 6.4.2 | 공개(all) / 회원 본인(personal) |
| [searchCompanies](../../api/out/zoop-api-spec.md#searchcompanies) | GET /api/v1/companies | 6.1.2, 6.10.1, 6.3.4, 6.5.10, 6.6 | 공개 |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
