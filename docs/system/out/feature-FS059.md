# FS059 · 분석 결과 저장 및 조회 반영

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 71 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:70 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/09-데이터-관리.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/09-데이터-관리.csv) — 분석 결과 저장 및 조회 반영: 시스템은 수집·분석된 뉴스, 이슈, 기업 관계, 사건 시각 및 근거 정보를 서로 연결하여 저장해야 한다. 저장된 공개 대상 결과는 메인 그래프와 기업 상세페이지에서 각 화면의 기업·기간·선택 조건에 맞게 조회할 수 있어야 한다. 처리 중이거나 검증에 실패한 결과는 공개 조회에서 제외해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:244 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getPipelineOverview](../../api/out/zoop-api-spec.md#getpipelineoverview) | GET /api/v1/admin/pipeline/overview | 6.1.2, 6.10.1, 6.4.5, 6.4.6, 6.4.10, 6.9.3 | 관리자(작업별 권한) |
| [decideAnalysisCandidate](../../api/out/zoop-api-spec.md#decideanalysiscandidate) | POST /api/v1/admin/pipeline/candidates/{candidate_id}/decision | 6.1.2, 6.10.1, 6.4.6, 6.9.3 | 관리자(작업별 권한) |
| [listPublicationRules](../../api/out/zoop-api-spec.md#listpublicationrules) | GET /api/v1/admin/pipeline/rules | 6.1.2, 6.10.1, 6.4.6, 6.9.3 | 관리자(작업별 권한) |
| [setPublicationRule](../../api/out/zoop-api-spec.md#setpublicationrule) | PUT /api/v1/admin/pipeline/rules/{rule_id} | 6.1.2, 6.10.1, 6.4.6, 6.9.3 | 관리자(작업별 권한) |
| [listGraphVersions](../../api/out/zoop-api-spec.md#listgraphversions) | GET /api/v1/admin/graph/versions | 6.1.2, 6.10.1, 6.4.6, 6.9.3 | 관리자(작업별 권한) |
| [publishGraphVersion](../../api/out/zoop-api-spec.md#publishgraphversion) | POST /api/v1/admin/graph/versions | 6.1.2, 6.10.1, 6.4.6, 6.9.3 | 관리자(작업별 권한) |
| [activateGraphVersion](../../api/out/zoop-api-spec.md#activategraphversion) | POST /api/v1/admin/graph/versions/{version_id}/activate | 6.1.2, 6.10.1, 6.4.6, 6.9.3 | 관리자(작업별 권한) |
| [createAnalysisJob](../../api/out/zoop-api-spec.md#createanalysisjob) | POST /api/v1/admin/jobs | 6.1.2, 6.10.1, 6.4.5, 6.4.6, 6.4.10, 6.4.11 | 관리자(작업별 권한) |
