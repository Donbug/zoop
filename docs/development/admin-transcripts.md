# 관리자 대화록 마스킹 조회 인계

2026-11-03 · FS066-03 · A-ADM-02b · WBS 6.10.11 · Refs #137

## 읽기 경계

`listMaskedTranscripts`와 `getMaskedTranscript`는 기존 관리자 세션 검증 뒤 별도
`transcript:read` 허용 목록, 열람 목적, DB 조회, 마스킹, 감사 저장 순으로 처리한다.
`admin:all`만으로는 대화록을 열 수 없다. 다른 관리자 API의 권한과
`admins.role` 제약은 바꾸지 않는다.

`zoop.admin.transcript-readers` / `ZOOP_ADMIN_TRANSCRIPT_READERS`는 관리자 ID를
쉼표로 구분한 설정이다. 기본값은 빈 목록이다. 변경하려면 애플리케이션을 재시작해야
한다. 권한 정책 객체는 요청마다 확인하지만 설정을 동적으로 다시 읽지는 않는다.
허용 목록을 비우고 모든 인스턴스를 재시작하면 열람이 차단된다.

목적은 앞뒤 공백 제거 후 1~200자이며 원래 입력의 제어문자도 거부한다.
`AuditReasonPolicy.safeMemberReason`과 번호/이메일/URL 토큰 검사를 통과해야 한다.
거부한 원래 목적은 감사 로그에 저장하지 않는다. 목적 사전은 아직 정하지 않았다.

## 데이터와 마스킹

회원 `chat_sessions`와 `chat_jobs`, 현재 `chatbot_answer` 평가만 읽는다.
`userKind`는 `member`이며 비회원 대화를 합성하지 않는다. 회원 표시는 서명 키의
별도 목적 `admin-transcript-user-v1`로 만든 가명이다. 키 교체 시 가명도 달라진다.

`TranscriptMasker`에서 다음 규칙을 관리한다.

- URL 쿼리의 token/password/secret/authorization/api_key/signature/credential 계열 값.
  인코딩된 키도 검사한다.
- 이메일, 국내 전화번호와 +82/0082 번호, 주민등록번호 형태.
- 카드번호 형태(13~19자리), 계좌번호 형태(8~25자리). 앞선 규칙과 일치한 번호는
  그 규칙으로만 집계한다. 숫자 형태를 보수적으로 가리므로 일반 숫자도 가려질 수 있다.
- 해당 대화 소유자의 저장된 회원 ID·이메일·표시 이름을 포함한 텍스트.

질문·답변·평가 사유뿐 아니라 실패 사유와 컨텍스트 라벨도 가린다. 목록의 첫 질문은
전체를 먼저 가리고 나서 120 코드 포인트로 자른다. 원본 DB 값을 수정하지 않는다.
규칙은 범용 익명화 보증이나 모든 이름·우회 표기의 탐지기가 아니다. 팀은 실제 열람을
허용하기 전에 규칙 범위와 과도한 치환, 탐지하지 못하는 형태를 검토해야 한다.

목록은 세션 생성 시각/ID 내림차순으로 이어 받으며 커서는 관리자·목적·필터·limit에
묶인다. 각 요청은 repeatable-read 트랜잭션에서 읽는다. 커서의 기준 시각은 이후 생성된
세션/질문을 제외하는 기준이며 과거 평가 이력을 복원하는 기능은 아니다.

## 감사 저장과 실패

`TranscriptAudit.record`는 `REQUIRES_NEW` 트랜잭션으로 커밋한 뒤 반환한다.
따라서 거부/실패로 바깥 읽기 트랜잭션이 롤백돼도 감사 기록은 남는다. 커밋 실패도
서비스에서 `AUDIT_UNAVAILABLE`로 변환한다. 읽기 결과 캐시는 없으며 응답은
`Cache-Control: no-store`다. 상세의 `masking.completed=true`는 마스킹과 감사 저장
성공 뒤에만 내보낸다. 웹도 이 표시가 없거나 false이면 본문을 표시하지 않는다.

감사 action은 `transcript.view`, target은 `chat_session` 또는
`chat_session_list`, outcome은 `succeeded|denied|failed`다. detail은
only/limit/returned/maskingCounts만 포함한다. 질문·답변·평가 사유·대화 소유자 ID나
이메일은 넣지 않는다. 기존 감사 스키마의 행위자 관리자 식별 정보는 유지한다.

권한 거부는 403, 목적/조회 조건 오류는 422, 없는 세션은 404다. 마스킹 실패는
503 `MASKING_FAILED`, 감사 저장 실패는 503 `AUDIT_UNAVAILABLE`로 본문 없이
차단한다. 내부 예외의 원래 메시지나 cause를 응답/로그로 넘기지 않는다.

## 재검증

새 테스트는 `TranscriptMaskerTest`, `TranscriptServiceTest`,
`TranscriptPostgresTest`와 웹 `tests/admin/adminInsights.test.tsx`에 있다.
피드백 목록의 sessionId 연결은 `AiResultFeedbackPostgresTest`에서 확인한다.
PostgreSQL 테스트는 기존 `auth-postgres` 태그와 DB_URL 조건을 사용한다.

API 전체 `test` 및 기존 `authIntegrationTest`, 웹 타입/린트/포맷/빌드/Vitest,
`scripts/repo_checks.py`의 계약 검사를 실행한다. DB는 작업용 일회용 PostgreSQL을
명시적으로 지정하고 합성 fixture만 사용한다. 운영 환경 파일이나 DB를 읽지 않는다.
Windows에서는 긴 JVM 명령줄, POSIX 파일 권한, 심볼릭 링크 권한, WSL Bash 문제를
실제 기능 실패와 구분해 기록한다. 이를 우회하려고 저장소의 CI나 테스트를 약화하지 않는다.

## 팀 확인 필요

1. 설정 허용 목록을 정식 권한 부여 방식으로 사용할지와 승인/회수 절차.
2. 마스킹 규칙·허용 한계·실패 시 운영 절차.
3. 자유 입력 목적 대신 사용할 목적 사전.
4. 감사 로그 보존 기간과 접근/삭제 정책.

이 결정 전에는 기본 허용 목록을 비운 상태로 둔다. 이 구현만으로 #137의 정책 확정과
운영 수용 완료를 주장하지 않는다.
