# FS060 · 대화와 질문 기록

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 72 |
| 의미 기준 요구사항 | 72 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv:67 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-12/09-데이터-관리.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/09-데이터-관리.csv) — 대화와 질문 기록: 회원의 대화별로 질문 작업과 실행을 구분하고, 최초 질문 시각·맥락·대상·기간·근거 버전, 처리 상태와 저장 결과를 기록한다. 동일 작업 재시도는 최초 조건을 유지하며 현재 권한과 실행의 유효성을 확인한다. 새 질문과 기존 상태·결과 회수를 구분한다.

## 상세 권한과 의미 이행

- 옛 FS046 AI 권한과 중복 작업 통제에서 이행됨(단일 신규 ID 없음 · 서버 공통 의무로 분산 보존). 보존: 로그인·대화 소유권·근거 접근 권한 재검증, 같은 작업 ID의 내용 불일치 거절, 같은 대화에 서로 다른 작업 ID가 동시에 와도 유효 실행 하나, 상태 조회·결과 회수는 신규 접수와 구분. 버튼 비활성화만으로 대체하지 않는다. 공통 규칙 aiJobs·idempotency와 NFS001/003이 서버 계약으로 유지한다.
- 옛 FS052-02 AI 내부 패널 닫기·재열기와 대화 유지에서 이행됨(병합·번호 이동). 보존: 닫기는 취소·삭제가 아니고 재열기는 새 생성이 아님, 대화·작업 회수, 상세 기업 변경이 기존 대화 맥락을 바꾸지 않음.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:259 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.10 | BE | (BE) 대화와 질문 기록 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.11 | FE | (FE) D-AI-01 AI 챗봇 기본 화면 및 세션 API 연동 | 기본 화면·세션 연동은 질문 진입(FS045)과 새 대화·후속 질문(FS050, 옛 FS051)을 소비한다. 원문 산출물의 번호는 옛 체계다. |
| 6.9.14 | FE | (FE) D-AI-02b 대화 이력·후속 질문·답변 재조회 API 연동 | 대화 이력·후속 질문·재조회는 근거 탐색(FS049)·새 대화/후속 질문(FS050)·결과 재조회(FS051)·질문 기록(FS060)을 소비한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | AI v2 FS045~051과 질문 기록, 권한·작업 일관성 공통 의무를 통합 시험 대상으로 연결한다. 원문 종료일이 시작일보다 앞서는 오류는 별도 경고로 보존한다. |

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02b](screen-D-AI-02b.md) · [D-AI-01b](screen-D-AI-01b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [createConversation](../../api/out/zoop-api-spec.md#createconversation) | PUT /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.6, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [getConversation](../../api/out/zoop-api-spec.md#getconversation) | GET /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.6, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [getCurrentConversation](../../api/out/zoop-api-spec.md#getcurrentconversation) | GET /api/v1/chat/sessions/current | 6.1.2, 6.11.1, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 | 회원(본인) |
