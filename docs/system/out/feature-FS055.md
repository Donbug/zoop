# FS055 · 관계와 근거 연결

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 67 |
| 의미 기준 요구사항 | 67 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv:63 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-12/09-데이터-관리.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/09-데이터-관리.csv) — 관계와 근거 연결: 기업·이슈 간 관계와 이를 뒷받침하는 뉴스·공시를 연결해 저장한다. 관계 유형별 필수 정보, 근거 확보 상태, 검증·공개 상태와 변경 버전을 함께 관리한다. 근거 미확보 관계는 비공개 검토 후보로 보관할 수 있으며, 필수 근거와 자동 검증·공개 조건을 통과한 결과만 기존 공개 조회에 반영한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:255 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.5.1 | BE | (BE) 관계와 근거 연결 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.5.8 | 공통/통합 | 데이터 관리·외부 연동 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-COM-04](screen-D-COM-04.md) · [D-GRP-04](screen-D-GRP-04.md) · [D-COM-01b](screen-D-COM-01b.md) · [D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md) · [D-GRP-05](screen-D-GRP-05.md) · [D-AI-01](screen-D-AI-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-GRP-06](screen-D-GRP-06.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | 6.1.2, 6.11.1, 6.3.6, 6.4.7, 6.6.1, 6.6.2, 6.6.3, 6.6.11, 6.6.21, 6.6.23, 6.7.3, 6.7.7, 6.7.8, 6.7.10, 6.7.11, 6.7.12, 6.8.5, 6.8.14, 6.5.1 | 공개(all) / 회원 본인(personal) |
| [getCompanyRelation](../../api/out/zoop-api-spec.md#getcompanyrelation) | GET /api/v1/graph/edges/{id} | 6.1.2, 6.11.1, 6.6.8, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.5.1 | 공개 |
| [listEvents](../../api/out/zoop-api-spec.md#listevents) | GET /api/v1/events | 6.1.2, 6.11.1, 6.7.3, 6.7.4, 6.7.8, 6.7.11, 6.7.12, 6.5.2, 6.5.1 | 공개 |
| [getEvidence](../../api/out/zoop-api-spec.md#getevidence) | GET /api/v1/evidence/{id} | 6.1.2, 6.11.1, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.7.6, 6.7.9, 6.9.5, 6.9.14, 6.5.1 | 공개 |
| [getCompanyIssueImpact](../../api/out/zoop-api-spec.md#getcompanyissueimpact) | GET /api/v1/companies/{id}/issues/{issueId}/impact | 6.1.2, 6.11.1, 6.6.6, 6.6.7, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.5.1 | 공개 |
| [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | 6.1.2, 6.11.1, 6.7.2, 6.7.3, 6.7.4, 6.7.5, 6.7.8, 6.7.10, 6.7.11, 6.7.12, 6.5.1 | 공개 |
