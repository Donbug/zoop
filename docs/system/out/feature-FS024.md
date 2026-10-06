# FS024 · 관계 근거 확인

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 24 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:34 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv:107 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv) — 관계 근거 확인: 사용자가 그래프의 연결과 설명을 직접 확인할 수 있도록 기업·이슈·관계에 연결된 근거 자료를 제공한다. 근거 뉴스·공시의 제목, 출처, 발행 시각, 확보된 원문 구간과 원문 링크를 표시해야 한다. 원문 접근이 불가능하거나 근거가 충분하지 않은 경우 해당 상태를 안내하고, 문서 발행 시각과 관계 확인 시점을 구분해야 한다.
- [docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv:112 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv) — 관계 근거 확인: 기업·이슈·관계 설명에 사용된 뉴스·공시 근거를 제공하고 사용자가 요약 내용의 근거 원문을 직접 확인할 수 있도록 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:76 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-04](screen-D-GRP-04.md) · [D-GRP-05](screen-D-GRP-05.md) · [D-COM-02](screen-D-COM-02.md) · [D-AI-01](screen-D-AI-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-GRP-06](screen-D-GRP-06.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompanyRelation](../../api/out/zoop-api-spec.md#getcompanyrelation) | GET /api/v1/graph/edges/{id} | 6.1.2, 6.10.1, 6.5.7, 6.5.8, 6.4.2 | 공개 |
| [getEvidence](../../api/out/zoop-api-spec.md#getevidence) | GET /api/v1/evidence/{id} | 6.1.2, 6.10.1, 6.5.8, 6.6.6, 6.8.5, 6.4.2 | 공개 |
| [getCompanyIssueImpact](../../api/out/zoop-api-spec.md#getcompanyissueimpact) | GET /api/v1/companies/{id}/issues/{issueId}/impact | 6.1.2, 6.10.1, 6.5.6, 6.5.8, 6.4.2 | 공개 |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
