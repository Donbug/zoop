# FS060 · 대화와 질문 기록

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 72 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:71 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/09-데이터-관리.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/09-데이터-관리.csv) — 대화와 질문 기록: 회원의 대화별로 질문 작업과 실행을 구분하고, 최초 질문 시각·맥락·대상·기간·근거 버전, 처리 상태와 저장 결과를 기록한다. 동일 작업 재시도는 최초 조건을 유지하며 현재 권한과 실행의 유효성을 확인한다. 새 질문과 기존 상태·결과 회수를 구분한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:259 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.10 | BE | (BE) 대화와 질문 기록 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.11 | FE | (FE) D-AI-01 AI 챗봇 기본 화면 및 세션 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.14 | FE | (FE) D-AI-02b 대화 이력·후속 질문·답변 재조회 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02b](screen-D-AI-02b.md) · [D-AI-01b](screen-D-AI-01b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [createConversation](../../api/out/zoop-api-spec.md#createconversation) | PUT /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.6, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [getConversation](../../api/out/zoop-api-spec.md#getconversation) | GET /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.6, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [getCurrentConversation](../../api/out/zoop-api-spec.md#getcurrentconversation) | GET /api/v1/chat/sessions/current | 6.1.2, 6.11.1, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 | 회원(본인) |
