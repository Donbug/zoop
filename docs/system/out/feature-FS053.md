# FS053 · AI 결과 회수와 재시도

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 53 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv:149 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv) — AI 결과 회수와 재시도: 응답을 받지 못하면 새 답변 생성 전에 기존 질문 작업의 상태를 확인해야 한다. 완료 작업은 저장된 결과를 받고, 처리 중이면 대기하며, 서버가 확인한 실패만 허용된 방식으로 재실행해야 한다. 상태 조회 장애를 작업 미등록으로 취급하지 않고 같은 작업 재시도는 원래 질문 맥락을 유지해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:48 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.7 | BE | (BE) 패널 상태 유지·결과 재조회 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.9 | BE | (BE) AI 결과 회수와 재시도 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.13 | FE | (FE) D-AI-02 AI 비동기 작업 상태·결과·재시도 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.14 | FE | (FE) D-AI-02b 대화 이력·후속 질문·답변 재조회 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-AI-02](screen-D-AI-02.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getQuestionJob](../../api/out/zoop-api-spec.md#getquestionjob) | GET /api/v1/chat/jobs/{job_id} | 6.1.2, 6.11.1, 6.9.4, 6.9.5, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |
| [retryQuestionJob](../../api/out/zoop-api-spec.md#retryquestionjob) | POST /api/v1/chat/jobs/{job_id}/retry | 6.1.2, 6.11.1, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |
| [cancelQuestionJob](../../api/out/zoop-api-spec.md#cancelquestionjob) | POST /api/v1/chat/jobs/{job_id}/cancel | 6.1.2, 6.11.1, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |
