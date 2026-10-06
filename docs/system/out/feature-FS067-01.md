# FS067-01 · 이슈 분석·공개 반영 상태 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 미기재 |
| 요구사항 번호 | 79 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:80 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — 이슈 분석·공개 반영 상태 조회: 관리자가 이슈·기업 관계의 분석 회차별 진행, 검증 통과·보류·폐기, GraphDB 저장, 그래프·기업 상세의 실제 공개 버전과 실패 사유를 구분하여 확인한다. 상태 조회 자체는 검수·재실행·공개를 수행하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:62 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getPipelineOverview](../../api/out/zoop-api-spec.md#getpipelineoverview) | GET /api/v1/admin/pipeline/overview | 6.1.2, 6.10.1, 6.4.5, 6.4.6, 6.4.10, 6.9.3 | 관리자(작업별 권한) |
| [listAnalysisCandidates](../../api/out/zoop-api-spec.md#listanalysiscandidates) | GET /api/v1/admin/pipeline/candidates | 6.1.2, 6.10.1, 6.9.3 | 관리자(작업별 권한) |
| [getAnalysisCandidate](../../api/out/zoop-api-spec.md#getanalysiscandidate) | GET /api/v1/admin/pipeline/candidates/{candidate_id} | 6.1.2, 6.10.1, 6.9.3 | 관리자(작업별 권한) |
| [listPublicationRules](../../api/out/zoop-api-spec.md#listpublicationrules) | GET /api/v1/admin/pipeline/rules | 6.1.2, 6.10.1, 6.4.6, 6.9.3 | 관리자(작업별 권한) |
| [listGraphVersions](../../api/out/zoop-api-spec.md#listgraphversions) | GET /api/v1/admin/graph/versions | 6.1.2, 6.10.1, 6.4.6, 6.9.3 | 관리자(작업별 권한) |
| [listAnalysisJobs](../../api/out/zoop-api-spec.md#listanalysisjobs) | GET /api/v1/admin/jobs | 6.1.2, 6.10.1, 6.4.5, 6.9.3 | 관리자(작업별 권한) |
| [getAnalysisJob](../../api/out/zoop-api-spec.md#getanalysisjob) | GET /api/v1/admin/jobs/{job_id} | 6.1.2, 6.10.1, 6.9.3 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '이슈 분석·공개 반영 상태 조회' ↔ 요구사항 79 'AI 기반 이슈 판단의 진행 상태, 이슈 각각의 통과/보류/폐기 상태 등 확인 및 보류된 이슈의 검수 후 허용/거부 선택'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
