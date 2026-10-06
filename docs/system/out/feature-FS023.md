# FS023 · 기업 간 관계 확인(기업 간 간선 클릭)

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 23 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:33 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv) — 기업 간 관계 확인(기업 간 간선 클릭): 사용자가 두 기업이 연결된 이유를 이해할 수 있도록 기업 간 관계선을 선택하면 관계 설명을 제공해야 한다. 공급·고객·경쟁·투자 등 확인된 관계 유형과 관계의 방향, 관련 사업·제품 범위, 현재 상태 및 확인 시점을 표시해야함.
- [docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv:94 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv) — 기업 간 관계 확인(기업 간 간선 클릭): 사용자가 두 기업이 연결된 이유를 이해할 수 있도록 기업 간 관계선을 선택하면 관계 설명을 제공해야 한다. 공급·고객·경쟁·투자 등 확인된 관계 유형과 관계의 방향, 관련 사업·제품 범위, 현재 상태 및 확인 시점을 표시해야함.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:188 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-04](screen-D-GRP-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompanyRelation](../../api/out/zoop-api-spec.md#getcompanyrelation) | GET /api/v1/graph/edges/{id} | 6.1.2, 6.10.1, 6.5.7, 6.5.8, 6.4.2 | 공개 |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
- REQUIREMENT_TITLE_REVIEW: 명세 '기업 간 관계 확인(기업 간 간선 클릭)' ↔ 요구사항 23 '기업 간 관계 확인(기업 간 간선 클릭) '. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
