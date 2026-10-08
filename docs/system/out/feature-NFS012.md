# NFS012 · 정기 갱신 반영 시간 보장

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 추가 제안 · 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 65 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 데이터 없음 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:103 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/12-비기능-상세.csv:163 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/12-비기능-상세.csv) — 정기 갱신 반영 시간 보장: 정상 운영 시 시스템은 한국 시간 기준 매시 05분에 시작한 회차의 공개 대상 결과를 해당 시각 10분까지, 매시 35분에 시작한 회차의 결과를 해당 시각 40분까지 조회 가능하게 해야 한다. 완료 여부는 저장소 반영만이 아니라, 메인 그래프와 기업 상세페이지 조회에서 해당 새 결과를 확인할 수 있는지를 기준으로 판단해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:306 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |

## 화면·목표 API

[A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getPipelineOverview](../../api/out/zoop-api-spec.md#getpipelineoverview) | GET /api/v1/admin/pipeline/overview | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4, 6.5.5, 6.5.6 | 관리자(작업별 권한) |
| [listAnalysisCandidates](../../api/out/zoop-api-spec.md#listanalysiscandidates) | GET /api/v1/admin/pipeline/candidates | 6.1.2, 6.11.1, 6.10.6, 6.10.7, 6.10.16 | 관리자(작업별 권한) |
| [getAnalysisCandidate](../../api/out/zoop-api-spec.md#getanalysiscandidate) | GET /api/v1/admin/pipeline/candidates/{candidate_id} | 6.1.2, 6.11.1, 6.10.6, 6.10.7, 6.10.16 | 관리자(작업별 권한) |
| [decideAnalysisCandidate](../../api/out/zoop-api-spec.md#decideanalysiscandidate) | POST /api/v1/admin/pipeline/candidates/{candidate_id}/decision | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 | 관리자(작업별 권한) |
| [listPublicationRules](../../api/out/zoop-api-spec.md#listpublicationrules) | GET /api/v1/admin/pipeline/rules | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.5 | 관리자(작업별 권한) |
| [setPublicationRule](../../api/out/zoop-api-spec.md#setpublicationrule) | PUT /api/v1/admin/pipeline/rules/{rule_id} | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 | 관리자(작업별 권한) |
| [listAnalysisJobs](../../api/out/zoop-api-spec.md#listanalysisjobs) | GET /api/v1/admin/jobs | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4 | 관리자(작업별 권한) |
| [createAnalysisJob](../../api/out/zoop-api-spec.md#createanalysisjob) | POST /api/v1/admin/jobs | 6.1.2, 6.11.1, 6.5.4, 6.5.5, 6.5.6, 6.5.7 | 관리자(작업별 권한) |
| [getAnalysisJob](../../api/out/zoop-api-spec.md#getanalysisjob) | GET /api/v1/admin/jobs/{job_id} | 6.1.2, 6.11.1, 6.10.6, 6.10.16 | 관리자(작업별 권한) |
| [retryAnalysisJob](../../api/out/zoop-api-spec.md#retryanalysisjob) | POST /api/v1/admin/jobs/{job_id}/retry | 6.1.2, 6.11.1, 6.10.7, 6.10.16 | 관리자(작업별 권한) |
| [cancelAnalysisJob](../../api/out/zoop-api-spec.md#cancelanalysisjob) | POST /api/v1/admin/jobs/{job_id}/cancel | 6.1.2, 6.11.1, 6.10.7, 6.10.16 | 관리자(작업별 권한) |
