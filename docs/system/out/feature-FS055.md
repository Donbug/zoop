# FS055 · 관계와 근거 연결

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 67 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:67 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/09-데이터-관리.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/09-데이터-관리.csv) — 관계와 근거 연결: 기업·이슈 간 관계와 이를 뒷받침하는 뉴스·공시를 연결해 저장한다. 관계 유형별 필수 정보, 근거 확보 상태, 검증·공개 상태와 변경 버전을 함께 관리한다. 근거 미확보 관계는 비공개 검토 후보로 보관할 수 있으며, 필수 근거와 자동 검증·공개 조건을 통과한 결과만 기존 공개 조회에 반영한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:241 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-COM-04](screen-D-COM-04.md) · [D-GRP-04](screen-D-GRP-04.md) · [D-GRP-05](screen-D-GRP-05.md) · [D-COM-02](screen-D-COM-02.md) · [D-AI-01](screen-D-AI-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-GRP-06](screen-D-GRP-06.md) · [D-COM-01b](screen-D-COM-01b.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | 6.1.2, 6.10.1, 6.3.7, 6.5.1, 6.5.2, 6.5.3, 6.5.10, 6.7.5, 6.6.3, 6.6.7, 6.4.2 | 공개(all) / 회원 본인(personal) |
| [getCompanyRelation](../../api/out/zoop-api-spec.md#getcompanyrelation) | GET /api/v1/graph/edges/{id} | 6.1.2, 6.10.1, 6.5.7, 6.5.8, 6.4.2 | 공개 |
| [getEvidence](../../api/out/zoop-api-spec.md#getevidence) | GET /api/v1/evidence/{id} | 6.1.2, 6.10.1, 6.5.8, 6.6.6, 6.8.5, 6.4.2 | 공개 |
| [getCompanyIssueImpact](../../api/out/zoop-api-spec.md#getcompanyissueimpact) | GET /api/v1/companies/{id}/issues/{issueId}/impact | 6.1.2, 6.10.1, 6.5.6, 6.5.8, 6.4.2 | 공개 |
| [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | 6.1.2, 6.6.3, 6.6.4, 6.4.2, 6.10.1 | 공개 |
