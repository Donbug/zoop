# API Flyway migration 소유권과 초기 범위

## 역할과 순서

공통 기반 담당자는 Flyway 설정, 파일명·버전·검증 규칙, 충돌 조정과 공통 문서를 관리한다. ERD의 모든 테이블을 혼자 SQL로 구현하거나 다른 담당자의 Entity·데이터 정책을 확정하지 않는다. 업무 테이블의 migration은 해당 기능 담당자가 대응 Entity와 DB 적용 검증을 함께 작성한다. API 로직은 같은 기능의 후속 작업으로 구현할 수 있다. 여러 기능이 참조하는 테이블은 소유 담당자가 먼저 제공하고, 소비 기능은 참조·삭제 정책을 합의한 뒤 자신의 migration에서 FK를 추가한다.

새 테이블·컬럼 이름과 제약은 [ERD v6](../erd/zoop-core-erd-v6.md)을 우선한다. 따라서 `members`, `member_sessions`, `companies`처럼 ERD의 복수형 이름을 단수형으로 바꾸지 않는다. v6의 전체 테이블을 초기 migration 하나에 넣지 않는다. 현재 적용된 migration은 인증 저장 기반만 만들며, 다른 기능 담당자는 독립적으로 개발할 수 있다.

| 범위 | 소유 담당 | 처음 필요한 테이블 | 후속 테이블·조건 |
| --- | --- | --- | --- |
| 이메일 인증·회원 세션 | 임현 — WBS 6.2.1 | `members`, `member_sessions` | 비밀번호 해시·회원 설정은 `members` 컬럼에 둔다. 실제 회원가입에는 `terms`, `term_versions`, `term_agreements`와 승인된 약관 데이터가 필요하다. 비회원 세션은 `member_sessions`를 공유한다. |
| 소셜 인증·온보딩·관리자 인증 | 임현 — 관련 WBS | 약관 테이블·승인 본문까지 구현, 나머지 미구현 | 약관 `terms`, `term_versions`, `term_agreements`는 등록됐다. 기능 착수 시 `social_identities`, `admins`, `admin_sessions`를 추가한다. 관리자 role→permissions는 코드에서 관리한다. OAuth 진행 상태는 `member_sessions.auth_flow`를 사용한다. |
| 기업 목록·검색 | 정세빈 — WBS 6.6.11·6.7.1 | `companies` | 별칭은 `companies.aliases`에 저장한다. 검색용 `search_text`·트리거와 `pg_trgm` 인덱스는 기업 담당자가 구현한다. |
| 관심종목 | 임현 — WBS 6.3.4·6.4.1·6.4.2 | `watchlist` | `members.id`, `companies.id`에 의존한다. 두 소유자와 FK·삭제 정책·적용 순서를 합의한다. |
| 문서·근거·AI 분석 저장 | 미확정 — `api/README.md` 범위표의 문서·근거·분석 연동 담당(윤서진)이 후보 | 아직 migration 없음. v6 기준 `artifacts`, `articles`, `article_versions`, `evidence`, `document_analyses`, `analysis_jobs`, `ai_executions`(v3.5의 분석 하위 5개·시도·projection 테이블은 합쳐짐) | `artifacts`처럼 여러 기능이 참조하는 테이블은 소유자가 먼저 제공한다. `analysis_jobs`·`review_*`는 `pipeline`을 정세빈·윤서진이 함께 쓰므로 소유자를 먼저 정한다. 공개 `analysis_jobs.id`와 내부 AI `jobId`의 분리, `document_analyses.ai_job_id`, `ai_executions`의 호출 영수증·grant snapshot 열은 v6가 정했다. 남은 외부 계약과 AI 서비스 대응은 [ai-system 대조](../design/ai-system.md#erd-v6와-ai-저장-책임-대조)에 있다. |

첫 인증 migration인 [`V20261012210200__create_auth_identity.sql`](../../api/src/main/resources/db/migration/V20261012210200__create_auth_identity.sql)은 당시 설계의 `members`, `member_credentials`, `member_sessions`를 만든다. 이미 적용된 파일이므로 수정하지 않는다. 후속 [`V20261013000000__align_auth_identity_with_erd_v6.sql`](../../api/src/main/resources/db/migration/V20261013000000__align_auth_identity_with_erd_v6.sql)은 비어 있는 인증 스키마를 v6으로 변경한다. 최종 스키마의 비밀번호 **해시**·회원 설정은 `members`에 있고 `member_credentials`는 없다. `member_sessions`는 회원·비회원과 내부 `oauth_pending`을 구분한다. 대응 JPA Entity는 `api/src/main/java/com/zoop/auth/entity/`에 있다. 비밀번호·세션 토큰·CSRF 비밀 키 원문은 DB에 저장하지 않는다. 이메일 가입을 완료했다고 주장하려면 위 약관 테이블과 버전/동의 검증까지 구현한다.

첫 migration 당시 검증 결과는 [2026-10-12 인증 migration 검증 기록](auth-migration-verification-2026-10-12.md)에 보관한다. v6 적용 검증은 [2026-10-13 인증 migration 검증 기록](auth-migration-verification-2026-10-13.md)을 따른다.

기업 카탈로그 migration의 소유자는 정세빈이다. `companies.id`는 Neo4j 기업 노드와 동일 ID를 사용한다. 별칭은 `companies.aliases` 배열에 두고 별도 `company_aliases` 테이블을 생성하지 않는다. 기업 검색 담당자가 ERD의 `(exchange_code, ticker)` 부분 UNIQUE, `name_key`·`ticker` B-tree, `search_text`용 `pg_trgm` GIN 및 검색 문자열 갱신 트리거를 구현한다. PostgreSQL에 Neo4j Issue·Relation 원본이나 가짜 SQL FK를 만들지 않는다. 기업 데이터 공급원·ID 공유 절차와 검색 정규화 규칙은 실제 적재·검색 전에 기업·데이터 담당자가 합의한다.

## 인증 v6 이행 뒤 남은 결정

[`V20261013000000`](../../api/src/main/resources/db/migration/V20261013000000__align_auth_identity_with_erd_v6.sql)은 `member_credentials`를 `members`로 합치고 설정 컬럼과 내부 `oauth_pending` 세션을 추가했다([검증 기록](auth-migration-verification-2026-10-13.md)). 인증 테이블이 비어 있다는 전제이며 기존 행이 있으면 보호 조건이 migration을 중단한다. 아래는 이 migration과 v6가 정하지 않은 항목이다. 임현이 영향받는 담당자와 합의하며, 합의 전에는 임의로 채우지 않는다.

| 대상 | 현재 상태 | 남은 결정 |
| --- | --- | --- |
| 기존 데이터가 있는 DB | 보호 조건이 중단하며 `member_credentials` 행을 `members`로 옮기는 이행은 없다 | 비어 있지 않은 DB가 생기면 데이터 보존 이행을 별도 migration으로 정한다 |
| 비밀번호 변경 시각 | 옛 `member_credentials.updated_at`은 삭제됐고 v6 `members`에 대응 컬럼이 없다 | 변경 시각을 저장할지 정한다 |
| 설정 기본값 | `members.mode`·`completed`·`tutorial_completed`·`settings_version`·`updated_at`은 NOT NULL이며 DB 기본값이 없다 | 회원 생성 시 값은 가입·설정 구현이 정한다(v6는 `mode` 기본값을 정하지 않는다). 튜토리얼 PUT이 `settings_version`을 올릴지도 정한다(v6는 설정 PUT만 규정) |
| 튜토리얼 상태 (미해결 충돌) | `members`·`member_sessions` 모두 `tutorial_completed` boolean | 현행 FS016은 회원의 `COMPLETED`/`SKIPPED`를 구분해 저장하고 비회원 상태는 저장하지 않는다고 한다. 공개 `TutorialUpdate`·`SetupState`는 boolean 하나이고 비회원 값은 세션에 둔다. v6는 후자를 따르며 건너뜀과 미시작의 구분·비회원 저장 문제를 해결하지 않는다. 이 문서는 공개 스키마를 바꾸지 않는다 |
| OAuth 보조 쿠키 | ERD v6는 `zoop_oauth_pending` 쿠키(Path·SameSite·Max-Age)를 정의하지만 `docs/api/openapi.yaml`에는 이 쿠키가 없다 | 소셜 인증 착수 때 OAuth API 문서에 Set-Cookie 규칙을 반영한다 |
| 관리자 | 미구현. v6는 `admins`·`admin_sessions`와 코드의 role→permission 매핑을 정의한다 | 허용 role registry(v6 §10: 배포 시 확정한 코드 값)와 기존 다중 역할이 있을 때의 이행 방식을 합의한다. 임의로 하나를 고르지 않는다 |

v6는 AI 관련 저장도 합쳤다(`document_analyses` 6→1, `analysis_jobs` 3→1, `artifacts`·`ai_executions` 유지). 공개 `analysis_jobs.id`와 내부 AI `jobId`의 분리, `document_analyses.ai_job_id`, `ai_executions`의 `ai_job_id`·`ai_attempt_id`·`receipt_artifact_id`와 실행 당시 grant snapshot은 v6 문서가 정했지만 앱 migration·SQL 실행은 아직 없다. grant 발급·회수와 검증 영수증 형식은 v6 §8 항목 4가 담당자와 맞출 외부 계약으로 남겼다. 소유 담당과 열린 항목은 [ai-system 대조](../design/ai-system.md#erd-v6와-ai-저장-책임-대조)에 두고, 합의 전에는 다른 담당의 테이블에 FK나 값 의미를 앞서 정하지 않는다.

## 공통 적용 규칙

1. 기능 담당자는 `api/src/main/resources/db/migration/V<버전>__<설명>.sql`을 추가하고 같은 PR에서 대응 Entity와 검증 결과를 제출한다. 이미 공유 DB에 적용된 migration을 수정하지 않는다.
2. 병렬 브랜치의 버전·FK 순서는 병합 전에 조정한다. 아직 공유되지 않은 자신의 파일만 이름을 바꾸고, 새 DB와 이전 버전 DB 양쪽에 순서대로 적용되는지 확인한다.
3. JPA `ddl-auto: validate`를 유지한다. 테이블은 Flyway SQL이 만들며, Spring Boot 기동 시 Entity와 스키마가 맞는지 검증한다.
4. 공통 기반 담당자는 버전 충돌·공유 설정·검증 절차를 조정한다. 업무 컬럼의 의미·데이터 출처·삭제 정책은 해당 테이블 소유자가 ERD·API 계약에 맞춰 결정하고 영향받는 담당자와 협의한다.
