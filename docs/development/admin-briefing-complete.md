# 관리자 브리핑 기록·사용량·평가·재처리 연결

FS068·FS070·FS066의 기존 조회/변경/평가 구현을 하나의 통합 브랜치에서 연결한다. 기존 PR #418, #421, #425의 커밋을 보존하고 최신 main의 챗봇 토큰·문맥 보호를 포함한다. 기존 PR 브랜치를 수정하거나 병합하지 않는다.

## 저장 위치와 읽기

- PostgreSQL `briefing_rounds`, `briefing_attempts`, `ai_executions`: 발행 원문과 생성 시도, 각 모델 실행 메타데이터. `GET /api/v1/admin/briefings`와 `/{roundId}`에서 조회한다. 생성 시도와 전망 시도는 구분하며 모델 기록에는 두 feature를 모두 반환한다.
- `GET /api/v1/admin/ai/usage`: 실제 전송이 확인된 live만 모델 호출로 집계한다. replay/save_only는 실제 호출·재시도에 포함하지 않는다. 입력/출력 토큰의 미확인은 독립적으로 NULL이다. 청구 자료와 단가 자료가 없으면 실제/추정 비용·통화는 NULL이다.
- `briefing_feedback`: 브리핑 회차/핵심 이슈. `ai_result_feedback`: 저장된 챗봇 답변/검증된 뉴스 요약. `PUT /api/v1/member/feedback`, `GET /api/v1/member/feedback`와 관리자 summary/dislikes는 동일한 회원별·대상별 마지막 표를 읽는다. 취소, 과거 버전, 차단 회원, 현재 열 수 없는 결과를 집계에서 제외한다. 원천 조회 장애는 성공 0건으로 바꾸지 않는다.
- 챗봇은 `ChatJob.result.messageId` + `ChatJob.feedbackVersion`, 뉴스는 evidence ID + `documentSummary.resultVersion`을 그대로 제출한다. 챗봇 버전은 요청별 metadata를 제외한 저장 답변에 결합한다. 요약/답변 본문은 평가 테이블에 복사하지 않는다.
- 관리자 대시보드와 이용 개요도 같은 조회 모델을 사용한다. 표본 5개 미만의 비율은 숨기며, 사유는 조회 시 마스킹한다. 회원 원래 사유는 변경하지 않는다.

## 재처리 운영 설정

기본은 비활성화다. 모델 호출 권한이나 입력을 브라우저에서 받지 않는다. 운영자는 먼저 미발행 회차와 읽기 권한이 확인된 입력을 준비하고, 비공개 artifact root 및 DB 환경 `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `BRIEFING_USAGE_ARTIFACT_ROOT`를 설정한다.

1. `BriefingReprocessInputCommand`를 비웹 CLI로 실행한다. 인수는 `round-id input-file generation|save_only_generation max-calls authorization-ref true|false`다. `save_only_generation`은 동일 회차의 검증 PASS 저장 결과와 호출 상한 0이 필요하다. 입력 파일은 원장 본문이 아니라 private artifact에 보존한다.
2. API 설정 `zoop.briefing.reprocess.enabled=true`, `.root=<private-root>`, `.command=<JSON 문자열 배열>`을 설정한다. command의 예시는 Python 실행 파일과 `scripts/briefing_admin_reprocess.py`의 절대 경로로 된 두 원소 배열이다. 셸 명령 문자열은 받지 않는다.
3. API 프로세스의 `ZOOP_BRIEFING_LEDGER_COMMAND`는 Java 실행 파일, `-cp`, 런타임 classpath, `com.zoop.briefing.usage.BriefingUsageCommand`, `--stdio`로 된 JSON 배열이다. 실행 jar에서는 Boot `PropertiesLauncher`와 `-Dloader.main`도 사용할 수 있다.
4. live 생성은 별도로 `.allow-live=true`, `ZOOP_BRIEFING_REPROCESS_ALLOW_LIVE=true`, 운영자 키 파일 경로 `ZOOP_BRIEFING_REPROCESS_KEY_FILE`과 회차별 승인 근거·최대 16회 상한이 모두 필요하다. 저장 복구에는 키가 필요 없다. 이번 검증에서는 live를 비활성화했다.
5. 관리자 화면에서 사유를 입력해 `POST /api/v1/admin/briefings/{roundId}/reprocess`를 보낸다. 세션·Origin·CSRF·Idempotency-Key를 확인한다. 같은 관리자/회차/키/사유는 최초 202를 재반환하고 내용 변경은 409다.

`briefing_reprocess_jobs`는 queued → running → completed/failed 상태다. 접수 시 회차 잠금, 새 briefing_attempts, 작업, 감사 로그와 최초 응답을 하나의 트랜잭션에 저장한다. 진행 중인 동일 회차는 중복 접수하지 않는다. 완료는 생성·독립 검증·결과 저장을 뜻한다. **발행은 별도 승인 절차이며 이 작업이 기존 발행본을 덮어쓰거나 자동 발행하지 않는다.**

실패 단계는 briefing_attempts.stages.failureStage에 보존한다. 실행기/결과 저장 장애는 admin_worker, 모델 생성/검증은 기존 producer의 단계명이다. 미확인 전송은 unknown으로 남긴다. 종료·만료된 실행기를 복구할 때 모호한 live 호출을 자동 재전송하지 않으며, 관리자의 새 요청이 새 시도를 만든다. 원래 모델 호출 없이 저장만 복구하면 mode=save_only이며 실제 호출·재시도는 0이다. 작업 출력과 결과는 private artifact root 아래에만 저장한다.

## 과거 영수증의 제한적 정합화

`BriefingUsageArchiveCommand manifest.json operator-admin-id`는 등록된 메타데이터 영수증만 수집한다. manifest 형식은 schemaVersion=briefing-usage-archive-v1, rounds 배열 안에 roundId/resultArtifactId/calls 배열의 receiptArtifactId를 둔다. 발행본 public_snapshot에 결합된 결과와 request digest·response SHA가 일치해야 한다. 외부 모델 호출은 없다.

`recording_origin=archive`와 purpose=history를 사용하며 원래 생성 시도 횟수를 복원했다고 표시하지 않는다. 알 수 없는 원래 시작 시각과 비용은 NULL이다. 같은 요청 digest+응답 SHA를 재수집해도 한 AI 실행으로 유지하며 다른 회차로 옮기지 못한다. 수집은 관리자 감사 기록을 남긴다. 발행 원문/스냅샷은 변경하지 않는다.

과거 원장 전체가 없으면 전체 호출·토큰을 NULL로 유지하고 확인된 기록만 별도 설명·일별 추이에 표시한다. 일별 귀속은 실제 시작 시각, 시작을 모르는 archive는 종료 시각의 KST 날짜를 사용한다. 브리핑 대상 날짜로 과거 실제 호출 시각을 역산하지 않는다. 이 PR에는 실데이터·영수증·DB·키·개인정보를 포함하지 않는다.

## 검증 방법

`authIntegrationTest`의 관리자 브리핑/대시보드/사용량/평가 테스트, `BriefingUsagePostgresTest`, `AdminBriefingReprocessPostgresTest`를 disposable PostgreSQL에서 실행한다. 후자는 실제 Python bridge↔Java CLI로 save_only 완료, 발행 보존, 0 live 호출을 검증한다. 실패 단계, 멱등성, CSRF, 타인 답변, 버전 변경, 읽기 권한 철회와 장애도 검증한다. Python `test_briefing_admin_reprocess.py`는 live 승인 누락과 고정 입력 훼손 시 원장 접수·전송이 시작되지 않음을 확인한다.
