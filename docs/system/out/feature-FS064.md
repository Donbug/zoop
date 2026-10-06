# FS064 · AI 분석 연동

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 76 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:75 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/10-외부-연동.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/10-외부-연동.csv) — AI 분석 연동: 호출 기능의 작업·유효 실행에 맞는 허용된 질문과 근거만 분석 서비스에 전달하고, 응답의 형식·인용·대상 참조를 검증한다. 중복 요청·응답 미수신·호출 장애·근거 부족·검증 실패·결과 저장 실패를 구분하여 불필요한 재호출을 막는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:254 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md) · [A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | 6.1.2, 6.10.1, 6.5.5, 6.6.6, 6.4.3, 6.4.10, 6.4.11 | 공개 |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.10.1, 6.5.9, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.5, 6.8.6, 6.4.7, 6.4.11 | 회원(본인) |
| [createAnalysisJob](../../api/out/zoop-api-spec.md#createanalysisjob) | POST /api/v1/admin/jobs | 6.1.2, 6.10.1, 6.4.5, 6.4.6, 6.4.10, 6.4.11 | 관리자(작업별 권한) |
