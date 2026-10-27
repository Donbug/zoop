# FS051 · AI 패널 상태 유지와 결과 재조회

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 50 |
| 의미 기준 요구사항 | 52, 53 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 옛 FS046: 구현 / 옛 FS052-02: 구현 / 옛 FS053: 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:61 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/08-AI-챗봇-v2.csv:94 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/08-AI-챗봇-v2.csv) — AI 패널 상태 유지와 결과 재조회: 사용자가 AI 패널을 닫았다가 다시 열거나 네트워크 응답을 받지 못해도, 기존 질문 작업의 상태와 저장된 결과를 재조회할 수 있다. 패널 닫기·재열기는 질문 취소나 새 AI 생성으로 처리하지 않는다.
- [이력 정의] [docs/evidence/raw/functional-spec_2026-10-12/07-AI-챗봇.csv:107 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/07-AI-챗봇.csv) — 새 대화 시작: 사용자가 이전 대화와 독립된 주제로 질문할 수 있도록 ‘새 대화’ 기능을 제공해야 한다. 새 대화를 시작하면 별도의 대화 ID를 부여하고 이전 대화의 질문·답변 및 선택 조건을 자동으로 이어받지 않아야 한다. 기존 대화 기록은 유지하며, 이전 대화에서 처리 중이던 답변이 새 대화 화면에 표시되지 않아야 한다.

## 상세 권한과 의미 이행

- 옛 FS046 AI 권한과 중복 작업 통제에서 이행됨(단일 신규 ID 없음 · 서버 공통 의무로 분산 보존). 보존: 로그인·대화 소유권·근거 접근 권한 재검증, 같은 작업 ID의 내용 불일치 거절, 같은 대화에 서로 다른 작업 ID가 동시에 와도 유효 실행 하나, 상태 조회·결과 회수는 신규 접수와 구분. 버튼 비활성화만으로 대체하지 않는다. 공통 규칙 aiJobs·idempotency와 NFS001/003이 서버 계약으로 유지한다.
- 이 번호의 옛 AI 탭 정의는 현재 FS050로 이행된다(병합·번호 이동(현 FS051은 다른 의미)). 보존: 새 대화는 별도 ID·빈 맥락, 기존 대화·작업 삭제·취소 아님, 생성 실패 시 기존 대화와 입력 유지.
- 옛 FS052-02 AI 내부 패널 닫기·재열기와 대화 유지에서 이행됨(병합·번호 이동). 보존: 닫기는 취소·삭제가 아니고 재열기는 새 생성이 아님, 대화·작업 회수, 상세 기업 변경이 기존 대화 맥락을 바꾸지 않음.
- 옛 FS053 AI 결과 회수와 재시도에서 이행됨(병합·번호 이동). 보존: 상태 조회·결과 회수 먼저, 조회 장애를 미등록·실패로 단정하지 않음, 서버가 확정한 일시 장애만 같은 맥락으로 허용된 방식의 재시도, 검증 실패·권한 오류·결과 소실의 자동 재생성 금지.

문서 판정 출처: 옛 FS046 [docs/evidence/spec-v1.2-gap.md:39 (text-line)](../../../docs/evidence/spec-v1.2-gap.md) / 옛 FS052-02 [docs/evidence/spec-v1.2-gap.md:47 (text-line)](../../../docs/evidence/spec-v1.2-gap.md) / 옛 FS053 [docs/evidence/spec-v1.2-gap.md:48 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.7 | BE | (BE) 패널 상태 유지·결과 재조회 | 패널 상태 유지·결과 재조회는 AI v2 FS051 의미다. 원문 산출물은 10-10까지 옛 FS052-02+FS053이었고 10-12 공유 시트에서 FS051로 정정됐다. 복구 기준은 NFS003/009와 함께 본다. |
| 6.9.8 | BE | (BE) 대화와 내부 패널 유지 | 대화·내부 패널 유지는 AI v2 FS051의 패널 상태 유지 의미다. 원문 산출물은 10-10까지 옛 FS052-02였고 10-12 공유 시트에서 FS051로 정정됐다. |
| 6.9.9 | BE | (BE) AI 결과 회수와 재시도 | 결과 회수·재시도는 AI v2 FS051의 결과 재조회 의미다. 원문 산출물은 10-10까지 옛 FS053이었고 10-12 공유 시트에서 FS051로 정정됐다. |
| 6.9.13 | FE | (FE) D-AI-02 AI 비동기 작업 상태·결과·재시도 API 연동 | 작업 상태·결과·재시도 UI는 검증된 답변(FS048)과 결과 재조회(FS051), 권한·중복 통제 공통 의무(NFS001/003, 옛 FS046)를 소비한다. |
| 6.9.14 | FE | (FE) D-AI-02b 대화 이력·후속 질문·답변 재조회 API 연동 | 대화 이력·후속 질문·재조회는 근거 탐색(FS049)·새 대화/후속 질문(FS050)·결과 재조회(FS051)·질문 기록(FS060)을 소비한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | AI v2 FS045~051과 질문 기록, 권한·작업 일관성 공통 의무를 통합 시험 대상으로 연결한다. 원문 종료일이 시작일보다 앞서는 오류는 별도 경고로 보존한다. |

## 화면·목표 API

[D-AI-02](screen-D-AI-02.md) · [D-AI-01](screen-D-AI-01.md) · [D-AI-02b](screen-D-AI-02b.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listConversations](../../api/out/zoop-api-spec.md#listconversations) | GET /api/v1/chat/sessions | 6.1.2, 6.11.1, 6.9.7, 6.9.8, 6.9.14 | 회원(본인) |
| [getConversation](../../api/out/zoop-api-spec.md#getconversation) | GET /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.6, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [deleteConversation](../../api/out/zoop-api-spec.md#deleteconversation) | DELETE /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.14 | 회원(본인) |
| [getCurrentConversation](../../api/out/zoop-api-spec.md#getcurrentconversation) | GET /api/v1/chat/sessions/current | 6.1.2, 6.11.1, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 | 회원(본인) |
| [getQuestionJob](../../api/out/zoop-api-spec.md#getquestionjob) | GET /api/v1/chat/jobs/{job_id} | 6.1.2, 6.11.1, 6.9.4, 6.9.5, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |
| [retryQuestionJob](../../api/out/zoop-api-spec.md#retryquestionjob) | POST /api/v1/chat/jobs/{job_id}/retry | 6.1.2, 6.11.1, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |
| [cancelQuestionJob](../../api/out/zoop-api-spec.md#cancelquestionjob) | POST /api/v1/chat/jobs/{job_id}/cancel | 6.1.2, 6.11.1, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |

## 확인 필요

- HISTORICAL_DETAIL_SUPERSEDED: 옛 시트 07-AI-챗봇.csv의 정의는 이력으로 보존한다. 현행 상세는 08-AI-챗봇-v2.csv이며 같은 번호라도 의미가 다를 수 있어 번호 일치로 합치지 않는다.
- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A91:B103와 현행 상세 구획 제목 행 [92]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
- INDEX_REQUIREMENT_META_MISMATCH: 목차 요구 번호 ['50']와 현행 상세 메타 요구 번호 ['51']가 다르다. 원문을 보존한다.
- REQUIREMENT_BINDING_BY_MEANING: 명세 'AI 패널 상태 유지와 결과 재조회' ↔ 원문 요구 번호 50 '답변 근거와 그래프 탐색'. 의미 기준 연결은 요구 ['52', '53']이다(의미 기준 재연결): 현 FS051(패널 상태 유지와 결과 재조회)은 요구 52의 패널 유지와 요구 53이다. 목차 G61의 상세 위치와 요구 50, 상세 메타 51은 서로 다르며 모두 원문대로 보존한다.
