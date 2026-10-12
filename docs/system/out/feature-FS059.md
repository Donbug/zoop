# FS059 · 분석 결과 저장 및 조회 반영

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 71 |
| 의미 기준 요구사항 | 71 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:66 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-10/09-데이터-관리.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/09-데이터-관리.csv) — 분석 결과 저장 및 조회 반영: 시스템은 수집·분석된 뉴스, 이슈, 기업 관계, 사건 시각 및 근거 정보를 서로 연결하여 저장해야 한다. 저장된 공개 대상 결과는 메인 그래프와 기업 상세페이지에서 각 화면의 기업·기간·선택 조건에 맞게 조회할 수 있어야 한다. 처리 중이거나 검증에 실패한 결과는 공개 조회에서 제외해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:258 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.5.5 | BE | (BE) 분석 결과 저장 및 조회 반영 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.5.8 | 공통/통합 | 데이터 관리·외부 연동 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getPipelineOverview](../../api/out/zoop-api-spec.md#getpipelineoverview) | GET /api/v1/admin/pipeline/overview | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4, 6.5.5, 6.5.6 | 관리자(작업별 권한) |
| [decideAnalysisCandidate](../../api/out/zoop-api-spec.md#decideanalysiscandidate) | POST /api/v1/admin/pipeline/candidates/{candidate_id}/decision | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 | 관리자(작업별 권한) |
| [listPublicationRules](../../api/out/zoop-api-spec.md#listpublicationrules) | GET /api/v1/admin/pipeline/rules | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.5 | 관리자(작업별 권한) |
| [setPublicationRule](../../api/out/zoop-api-spec.md#setpublicationrule) | PUT /api/v1/admin/pipeline/rules/{rule_id} | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 | 관리자(작업별 권한) |
| [listGraphVersions](../../api/out/zoop-api-spec.md#listgraphversions) | GET /api/v1/admin/graph/versions | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.5 | 관리자(작업별 권한) |
| [publishGraphVersion](../../api/out/zoop-api-spec.md#publishgraphversion) | POST /api/v1/admin/graph/versions | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 | 관리자(작업별 권한) |
| [activateGraphVersion](../../api/out/zoop-api-spec.md#activategraphversion) | POST /api/v1/admin/graph/versions/{version_id}/activate | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 | 관리자(작업별 권한) |
| [createAnalysisJob](../../api/out/zoop-api-spec.md#createanalysisjob) | POST /api/v1/admin/jobs | 6.1.2, 6.11.1, 6.5.4, 6.5.5, 6.5.6, 6.5.7 | 관리자(작업별 권한) |
