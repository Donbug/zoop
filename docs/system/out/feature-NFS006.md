# NFS006 · 모델 전달 데이터 최소화

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 59 |
| 의미 기준 요구사항 | 59 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/12-비기능-상세.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/12-비기능-상세.csv) — 모델 전달 데이터 최소화: AI 모델에는 답변 생성에 필요한 기업, 이슈, 관계 경로 및 허용된 근거만 전달해야 한다. 비밀번호, 인증토큰, 세션 정보 및 불필요한 개인식별정보는 모델 입력과 로그에 포함해서는 안 된다. 보유 종목과 관심 종목 정보는 개인화 답변에 필요한 경우에만 최소 범위로 전달해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:300 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |

## 화면·목표 API

[D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md) · [D-AI-01](screen-D-AI-01.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02b](screen-D-AI-02b.md) · [D-AI-01b](screen-D-AI-01b.md) · [D-AI-02](screen-D-AI-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.6, 6.7.9, 6.5.2, 6.5.6, 6.5.7 | 공개 |
| [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | 6.1.2, 6.11.1, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 | 공개 |
| [createConversation](../../api/out/zoop-api-spec.md#createconversation) | PUT /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.6, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [getConversation](../../api/out/zoop-api-spec.md#getconversation) | GET /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.6, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [getCurrentConversation](../../api/out/zoop-api-spec.md#getcurrentconversation) | GET /api/v1/chat/sessions/current | 6.1.2, 6.11.1, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 | 회원(본인) |
| [getQuestionJob](../../api/out/zoop-api-spec.md#getquestionjob) | GET /api/v1/chat/jobs/{job_id} | 6.1.2, 6.11.1, 6.9.4, 6.9.5, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |
| [retryQuestionJob](../../api/out/zoop-api-spec.md#retryquestionjob) | POST /api/v1/chat/jobs/{job_id}/retry | 6.1.2, 6.11.1, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |
| [cancelQuestionJob](../../api/out/zoop-api-spec.md#cancelquestionjob) | POST /api/v1/chat/jobs/{job_id}/cancel | 6.1.2, 6.11.1, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |
