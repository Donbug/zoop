# FS022 · 기업 패널에서 이슈 영향 경로 확인

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 검토 중 |
| 요구사항 번호 | 22 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:32 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv) — 기업 패널에서 이슈 영향 경로 확인: 사용자가 기업 노드를 선택한 뒤 기업 패널의 관련 이슈를 선택하면 해당 이슈와 기업의 직접·간접 영향 경로, 단계별 연결 이유와 근거를 확인한다.
- [docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv:80 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv) — 기업 패널에서 이슈 영향 경로 확인: 사용자가 기업 노드를 선택한 뒤 기업 패널의 관련 이슈를 선택하면 해당 이슈와 기업의 직접·간접 영향 경로, 단계별 연결 이유와 근거를 확인한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:26 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-06](screen-D-GRP-06.md) · [D-GRP-05](screen-D-GRP-05.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompanyIssueImpact](../../api/out/zoop-api-spec.md#getcompanyissueimpact) | GET /api/v1/companies/{id}/issues/{issueId}/impact | 6.1.2, 6.10.1, 6.5.6, 6.5.8, 6.4.2 | 공개 |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
- REQUIREMENT_TITLE_REVIEW: 명세 '기업 패널에서 이슈 영향 경로 확인' ↔ 요구사항 22 '이슈와 기업의 영향 경로 확인(기업 노드 클릭)'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
