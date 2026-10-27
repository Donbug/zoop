# Issue #138 · 관리자 감사 조회 계약 (Task 1)

## 범위와 기준

- WBS `6.10.12`, FS072, NFS008, 화면 `A-ADM-05b`.
- 정본 HTTP 계약은 [`docs/api/openapi.yaml`](../api/openapi.yaml)의 `listAuditRecords`다. 이 문서는 DB와 HTTP 사이의 변환 및 개인정보 경계를 설명한다.
- 현재 저장소는 `audit_logs`에 관리자 로그인·실패·로그아웃·프로비저닝·회원 차단/해제를 기록한다. 여기서 다른 관리자 작업이나 AI 작업이 이미 기록된 것으로 간주하지 않는다.
- 현재 관리 화면은 `outcome=ok|denied|failed`를 소비한다. DB의 기존 값은 `succeeded|denied|failed`다.

> 후속 상태 갱신(2026-10-24): 이 문서의 Task 5·6 판단은 작성 당시의 스냅샷이다. 챗봇 쪽은 이후 `/api/v1/chat/**`, `V20261021120000__create_chat_jobs.sql`, executor와 `ai_executions.chat_job_id` FK가 구현돼 실제 질문 작업 상태와 모델 단계 기록을 보존한다. 브리핑 생성 `briefing_attempts` 경로는 여전히 없어 NFS008 전체 종단 충족을 선언하지 않는다.

## 응답 투영

| `AuditEntry` | `audit_logs` | 규칙 |
| --- | --- | --- |
| `id`, `at` | `id`, `occurred_at` | 시각은 오프셋을 포함한 RFC 3339 문자열. |
| `actorKind`, `actorId` | `actor_kind`, `actor_id` | `admin`, `system`, `anonymous`를 유지한다. 익명 로그인 실패의 `actorId=unknown`은 실제 관리자 식별자가 아니다. |
| `actorEmail` | `actor_email_snapshot` | 관리자 기록 당시 이메일. 익명·시스템은 `null`; 회원 이메일로 대체하지 않는다. |
| `action`, `targetType`, `targetId` | 같은 이름의 snake_case 열 | 코드와 식별자를 그대로 사용한다. 대상 ID에 표시명·원문을 넣지 않는다. |
| `outcome` | `outcome` | `succeeded → ok`, `denied → denied`, `failed → failed`. 알 수 없는 값은 성공으로 취급하지 않는다. |
| `reason` | `reason` | 필요한 운영 사유만 반환한다. 고정된 인증/시스템 사유 코드와 관리자 회원 조치의 목적에 맞는 사유가 대상이다. 비밀값·불필요한 개인정보가 포함된 과거 값은 반환 전에 `null`로 처리한다. |
| `detail` | `detail` | 동작별 허용 목록만 투영한다. 현재 회원 조치는 `beforeStatus`, `afterStatus`, `beforeRevision`, `afterRevision`만 허용한다. 로그인·로그아웃·프로비저닝의 기존 빈/역할 객체는 비민감 필드만 남긴다. 미등록 동작의 상세는 `{}`다. |

`request_id`, `admin_id`, `purpose`와 DB 원본 `detail` 전체는 응답에 포함하지 않는다. `request_id`는 내부 상관관계 확인용이고 응답 헤더의 `X-Request-ID`는 **현재 조회 요청**의 ID다. 감사 행의 요청 ID를 대신 반환하지 않는다.

## 필터와 페이지

- `action`, `targetType`: 공백 제거 후 코드 정확 일치. `actor`: 공백 제거 후 `actor_id` 또는 `actor_email_snapshot` 정확 일치. `q`: 공백 제거 후 `action`, `actor_id`, `actor_email_snapshot`, `target_id`, **공개 허용된** `reason`에서 대소문자 구분 없는 부분 일치. 각 필터는 AND, `actor` 내부의 두 대상과 `q` 내부의 다섯 대상은 OR다. 숨긴 사유가 검색 결과의 존재 여부로도 드러나지 않아야 한다. `%`, `_`는 와일드카드가 아닌 문자로 취급한다.
- 생략·빈 문자열은 필터 없음이다. 제어 문자는 422 `INVALID_REQUEST`. 최대 길이는 `action`·`targetType` 80자, `actor`·`q` 200자다. `detail`, 질문·브리핑 원문, 인증정보는 검색하지 않는다.
- 기본 `limit=50`, 허용 범위 `1..100`. `occurred_at DESC, id DESC`로 정렬하며 `limit+1`개를 읽어 `nextCursor` 유무를 결정한다. 일치 행이 없으면 `200 {"items":[],"nextCursor":null}`이다.
- 커서는 서버가 발급한 불투명하고 변조를 검출할 수 있는 값이다. 조회 관리자 ID, 정규화된 필터, limit, 첫 페이지의 기준 시각, 마지막 `(occurred_at,id)`, 형식 버전을 결합한다. 다음 페이지는 기준 시각 이후의 행을 제외하고 마지막 정렬 키보다 앞선 행을 읽는다. 다른 관리자·필터·limit에 재사용하거나 훼손·미지원 버전이면 422 `INVALID_CURSOR`다. 필터를 바꾸면 커서 없이 첫 페이지부터 시작한다.
- 기준 시각은 뒤늦게 삽입된 과거 시각 행까지 완전히 고정하는 DB 스냅샷이 아니다. 페이지 순회 중 새 행의 완전한 스냅샷이 필요한 운영 기능은 별도 계약이 필요하다.

## 접근·개인정보·실패

- 관리자 세션으로만 조회한다. 세션 없음·만료는 401 `AUTH_REQUIRED`, 권한 부족은 403 `ACCESS_DENIED`다. 조회 자체는 관리자 작업이나 AI 작업을 실행하지 않는다.
- 감사 저장 경로는 비밀번호, 세션 쿠키·토큰, 인증 헤더, 프롬프트·답변·브리핑 원문, 불필요한 회원 개인정보를 기록하지 않는다. 자유 입력 사유는 운영 목적에 필요한 내용으로 제한하고 민감값이 포함된 행은 조회에서 감춘다. 기존 행을 포함해 `reason`·`detail`의 공개 투영을 검증하는 것은 후속 구현 Task 2~4의 책임이다.
- 감사 저장 실패의 변경 작업 처리와 조회 실패는 분리한다. 이 목록 조회의 저장소 장애는 503 `SOURCE_UNAVAILABLE`; 임의의 빈 목록으로 바꾸지 않는다. 감사가 필수인 변경 작업의 저장 실패는 별도 `AUDIT_UNAVAILABLE` 정책을 따른다.
- 보존기간과 삭제 권한은 아직 확정되지 않았다. 이 Task에서 자동 삭제·보존기간을 만들지 않는다.

## 구현 검증 인계

- 기존 `anonymous/auth.login_failed`와 `admin/member.block` 행이 각각 정의된 enum·값으로 직렬화되는지 확인한다.
- 같은 `occurred_at`의 행, 필터 변경, 다른 관리자 커서 재사용, 훼손 커서, 마지막 페이지를 검증한다.
- 회원 조치의 허용 상세만 반환하고 비밀값·미등록 상세가 응답과 검색 결과에 나타나지 않는지 합성 fixture로 검증한다.
- 현재 `web/src/types/admin/members.ts`의 `AuditEntry.actorKind`는 `anonymous`를 포함하지 않는다. API 구현·화면 연동 시 타입과 익명 주체 표시를 함께 맞춘다. 이 Task는 화면 구현을 변경하지 않는다.

## Task 2·3 구현 현황

| 관리자 변경 경로 | 감사 저장 | 실패 원자성 |
| --- | --- | --- |
| 계정 프로비저닝 | `admin.provision`, 성공 또는 중복 거절 | 생성과 감사 INSERT가 같은 트랜잭션이다. 감사 실패 시 계정 생성도 롤백된다. |
| 로그인 성공·로그아웃 | `auth.login`, `auth.logout` | 세션 생성·폐기와 성공 감사가 같은 트랜잭션이다. 감사 실패 시 세션 변경도 롤백된다. |
| 로그인 실패 | `auth.login_failed` | 별도 트랜잭션으로 거절 기록을 남기며 이메일·비밀번호를 저장하지 않는다. |
| 회원 차단·해제 | `member.block`, `member.unblock` | 상태·세션 폐기·멱등 결과·성공 감사가 같은 트랜잭션이다. 감사 실패 시 모두 롤백된다. 상태 변경이 없는 재전송은 새 성공 감사 행을 만들지 않는다. |

회원 조치의 자유 입력 사유는 저장 전 검사한다. 인증 관련 문자열, URL, `@`, 긴 불투명 문자열, 제어 문자가 있으면 422 `INVALID_REQUEST`로 거절한다. 감사 `detail`은 상태와 revision만 저장한다. 이 검사는 모든 개인정보를 자동 판별한다는 뜻이 아니므로 운영자는 목적에 필요한 사유만 입력해야 한다. 과거 사유도 같은 금지 패턴이 있으면 목록에서 `null`로 반환하고 검색 대상에서 제외한다.

`AdminAuditQueryService`와 `JdbcAdminAuditReadRepository`는 필터·공개 사유·허용 상세·서명된 keyset 커서를 구현했다. 커서 MAC은 관리자 인증 키의 별도 도메인(`admin-audit-cursor-v1`)을 사용한다. 키 회전으로 이전 키가 제거되면 해당 커서는 `INVALID_CURSOR`가 되고 첫 페이지부터 다시 조회한다. Task 4에서 `/api/v1/admin/audit-log` 컨트롤러를 연결하고 관리자 세션, 필터, 빈 목록, 잘못된 요청·커서를 PostgreSQL HTTP 테스트로 확인했다. 화면 `A-ADM-05b`의 `AuditEntry` 타입과 익명 주체 표시도 API의 `anonymous` 값에 맞췄다.

검증: 단위 테스트 `AdminAuditQueryServiceTest`, `AdminMemberStatusServiceTest`; 격리 PostgreSQL 통합 테스트 `AdminAuditPostgresTest`에서 동일 시각 페이지, 필터·사유 노출, 회원·세션·프로비저닝 감사 실패 롤백을 확인한다.

## Task 5·6 · NFS008 생성 작업 추적의 구현 경계

NFS008은 **실제로 접수된 AI 답변과 브리핑 생성 작업** 각각에 ID, `queued/running/completed/failed/cancelled` 상태, 시작·종료 시각, 재시도 횟수, 오류 코드를 요구한다. 관리자 감사 행이나 `ai_executions`의 모델 호출 행을 작업 행으로 대체하면 작업 접수·취소·재시도와 모델 호출의 단위가 뒤섞인다.

현재 본개발 `api/`에는 `/api/v1/chat/**` 생성 컨트롤러와 `chat_jobs` migration·writer가 없다. `docs/development/ai-chatbot-implementation-plan.md`는 이를 챗봇 공개 API 개발의 첫 단계로 명시한다. `briefing_rounds`는 조회용 저장소로 설치됐지만 migration 자체가 생성·발행 writer 부재를 명시하며 `briefing_attempts` migration·writer도 없다. `ai_executions.chat_job_id`와 `briefing_attempt_id`는 장래 소유자를 위한 nullable 참조값이고, 현재 실제 작업의 상태 기록을 뜻하지 않는다. `prototype/bff`의 SQLite 작업 상태는 `/api/v1` 본개발 계약의 증거로 사용하지 않는다.

따라서 Task 5·6의 생성 작업 **실행 경로 연결은 미완료**다. 이 이슈에서 임의의 stand-in 작업이나 성공 감사를 만들어 NFS008을 충족한 것으로 표시하지 않는다. 후속 생성 경로 소유자가 다음을 한 트랜잭션 경계에 구현·검증해야 한다.

| 작업 | 완료 기준 |
| --- | --- |
| AI 답변 (`chat_jobs`) | 회원의 질문 접수 시 작업 ID와 `queued` 행을 영속화한다. 실행권 획득 때 `running/started_at`과 시도 번호를 기록한다. 완료·실패·취소 때 `finished_at`, 허용 오류 코드와 재시도 횟수를 기록하고 늦은 완료를 거절한다. 세션 소유권과 멱등 재전송을 검증하며 질문·답변 원문, 인증정보를 운영 로그에 남기지 않는다. |
| 브리핑 생성 (`briefing_attempts`) | 회차 잠금 아래 시도 ID와 `queued` 행을 만든다. `briefing_rounds.generation_token`과 실행권을 같은 트랜잭션으로 결합하고 실행·검증·완료/실패/취소 상태와 시각·재시도 번호·오류 코드를 보존한다. 임대 만료 회수와 늦은 완료를 검증하며 브리핑 원문과 인증정보를 운영 로그에 남기지 않는다. |

이 경계는 `docs/erd/zoop-core-erd-v6.md`의 `chat_jobs`·`briefing_attempts` 소유 모델을 따른다. 두 생성 경로가 설치된 뒤에야 NFS008의 종단 충족과 관리자 사용량 집계를 선언할 수 있다.

## Task 7 · 추적 및 회귀 검증

| 수용 기준 | 구현·검증 증거 | 상태 |
| --- | --- | --- |
| FS072 관리자 진입과 감사 목록 조회 | `A-ADM-01` 관리자 대시보드의 기존 감사 로그 이동 경로, `A-ADM-05b` 화면, `AdminAuditController`, `AdminAuthPostgresTest` | 완료 |
| 관리자 접근 제한 | `AdminAuthorizationInterceptorTest`의 권한 부족 403, PostgreSQL HTTP 테스트의 세션 없음 401 | 완료 |
| 정상·로딩·빈 데이터·실패·재시도 | `AuditLogTable`의 기존 상태별 UI와 `web/tests/admin/adminMembers.test.tsx`; API의 빈 목록 200, 유효하지 않은 입력 422, 저장소 장애 503 정책 | 감사 조회 범위 완료 |
| 개인정보와 감사 원자성 | `AdminAuditQueryServiceTest`, `AdminAuditPostgresTest`, 관리자 인증·회원 조치 테스트; 허용 상세만 반환하고 금지 사유는 검색·응답에서 제외 | 완료 |
| NFS008 AI 답변·브리핑 생성 작업별 상태 추적 | 위 Task 5·6의 본개발 writer와 종단 테스트가 필요 | 미완료 |

검증 명령: `api/./gradlew test`, 격리 PostgreSQL의 `authIntegrationTest`(감사 조회 HTTP 및 감사 저장 원자성), `web/pnpm exec vitest run tests/admin/adminMembers.test.tsx`, `web/pnpm run lint`, `web/pnpm run build`, 루트 `make contracts-check`, `make docs-check`, `git diff --check`. PostgreSQL 테스트는 합성 관리자·회원 fixture만 사용했다. 화면 `A-ADM-05b`의 와이어프레임과 화면 계획은 조회 표·필터의 기준으로 확인했고, 로딩·오류·빈 상태는 별도 화면 테스트로 검증했다.
