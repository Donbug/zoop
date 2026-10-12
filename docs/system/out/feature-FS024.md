# FS024 · 관계 근거 확인

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 24 |
| 의미 기준 요구사항 | 24 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:34 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [이력 정의] [docs/evidence/raw/functional-spec_2026-10-10/03-메인-그래프.csv:107 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/03-메인-그래프.csv) — 관계 근거 확인: 사용자가 그래프의 연결과 설명을 직접 확인할 수 있도록 기업·이슈·관계에 연결된 근거 자료를 제공한다. 근거 뉴스·공시의 제목, 출처, 발행 시각, 확보된 원문 구간과 원문 링크를 표시해야 한다. 원문 접근이 불가능하거나 근거가 충분하지 않은 경우 해당 상태를 안내하고, 문서 발행 시각과 관계 확인 시점을 구분해야 한다.
- [docs/evidence/raw/functional-spec_2026-10-10/04-메인그래프-v2.csv:112 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/04-메인그래프-v2.csv) — 관계 근거 확인: 기업·이슈·관계 설명에 사용된 뉴스·공시 근거를 제공하고 사용자가 요약 내용의 근거 원문을 직접 확인할 수 있도록 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:82 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.6.9 | BE | (BE) 관계 근거 조회 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.22 | FE | (FE) D-GRP-02 이슈 노드 상세 패널 및 이슈 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.24 | FE | (FE) D-GRP-04 간선 상세 패널 및 관계 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.25 | FE | (FE) D-GRP-05 근거 상세 창 및 근거 문서 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.26 | FE | (FE) D-GRP-06·07b 영향 경로·포커스 그래프 및 경로 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.27 | 공통/통합 | 메인 그래프 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-GRP-04](screen-D-GRP-04.md) · [D-GRP-05](screen-D-GRP-05.md) · [D-COM-02](screen-D-COM-02.md) · [D-AI-01](screen-D-AI-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-GRP-06](screen-D-GRP-06.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getCompanyRelation](../../api/out/zoop-api-spec.md#getcompanyrelation) | GET /api/v1/graph/edges/{id} | 6.1.2, 6.11.1, 6.6.8, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.5.1 | 공개 |
| [getEvidence](../../api/out/zoop-api-spec.md#getevidence) | GET /api/v1/evidence/{id} | 6.1.2, 6.11.1, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.7.6, 6.7.9, 6.9.5, 6.9.14, 6.5.1 | 공개 |
| [getCompanyIssueImpact](../../api/out/zoop-api-spec.md#getcompanyissueimpact) | GET /api/v1/companies/{id}/issues/{issueId}/impact | 6.1.2, 6.11.1, 6.6.6, 6.6.7, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.5.1 | 공개 |

## 확인 필요

- HISTORICAL_DETAIL_SUPERSEDED: 옛 시트 03-메인-그래프.csv의 정의는 이력으로 보존한다. 현행 상세는 04-메인그래프-v2.csv이며 같은 번호라도 의미가 다를 수 있어 번호 일치로 합치지 않는다.
- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A105:B117와 현행 상세 구획 제목 행 [109]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
