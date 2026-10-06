# FS044 · 기업 상세와 관계 그래프 이동·상태 복원

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 44 |
| API 대응 | 기존 API로 지원 |
| 사유 | 카메라·선택·탭·스크롤 복원은 클라이언트 상태다. 기업/그래프 API가 필요한 조회 조건과 버전을 제공하며 복원 전용 서버 API는 만들지 않는다. |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:54 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv:107 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv) — 기업 상세와 관계 그래프 이동·상태 복원: 사용자가 기업 상세와 관계 그래프를 오갈 때 선택 기업, 차트 기간, 기준 시점, 선택 탭, 선택 이슈를 유지한다. 사건에서 그래프로 이동하면 해당 기업·이슈의 실제 영향 경로만 강조한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:95 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-COM-04](screen-D-COM-04.md) · [D-GRP-03](screen-D-GRP-03.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-03](screen-D-COM-03.md) · [M-COM-02](screen-M-COM-02.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | 6.1.2, 6.10.1, 6.3.7, 6.5.1, 6.5.2, 6.5.3, 6.5.10, 6.7.5, 6.6.3, 6.6.7, 6.4.2 | 공개(all) / 회원 본인(personal) |
| [getCompany](../../api/out/zoop-api-spec.md#getcompany) | GET /api/v1/companies/{id} | 6.1.2, 6.10.1, 6.5.4, 6.6.1, 6.6.7 | 공개 |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '기업 상세와 관계 그래프 이동·상태 복원' ↔ 요구사항 44 '상세 화면 상태와 이동'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
