# ERD v6 인증 migration 적용 검증 — 2026-10-13

## 범위와 환경

- 기존 [`V20261012210200__create_auth_identity.sql`](../../api/src/main/resources/db/migration/V20261012210200__create_auth_identity.sql)은 변경하지 않았다.
- 신규 [`V20261013000000__align_auth_identity_with_erd_v6.sql`](../../api/src/main/resources/db/migration/V20261013000000__align_auth_identity_with_erd_v6.sql)을 추가했다.
- PostgreSQL 16.13 Alpine의 별도 임시 컨테이너·빈 DB를 사용했다. 일반 개발 DB와 프로토타입 DB는 사용하지 않았다.
- 인증 테이블에 기존 데이터가 없다는 현재 프로젝트 전제에 따라 백필은 없다. 다른 DB에 예전 인증 데이터가 있으면 신규 migration이 실패하도록 보호 조건을 뒀다.

## 관측 결과

| 검증 | 결과 |
| --- | --- |
| 빈 DB에서 Spring Boot 기동 | Flyway가 `20261012210200`과 `20261013000000`을 순서대로 적용했고 JPA `ddl-auto: validate`와 앱 기동이 성공했다. |
| 회원 스키마 | `member_credentials`가 없고, 비밀번호 해시·설정 컬럼이 `members`에 있다. 이메일 회원은 해시가 필요하고 소셜 회원의 해시 NULL은 허용된다. |
| 세션 스키마 | `member`, `guest`, `oauth_pending` 정상 행이 삽입됐다. `(member_id, created_at)` 인덱스가 존재한다. |
| 거절 조건 | 이메일 회원의 해시 누락, 잘못된 `mode`, `settings_version=0`, member 세션의 `auth_flow`, guest 세션의 analytics key 누락, pending 세션의 회원 소유·튜토리얼 완료를 모두 CHECK가 거절했다. |
| 회귀 | `./gradlew test`와 `./gradlew build`가 통과했다. |

DB 제약은 [`auth-erd-v6-verification.sql`](../../api/src/test/resources/sql/auth-erd-v6-verification.sql)로 확인했다. SQL은 합성 `example.invalid` 계정과 토큰 해시 표식만 사용하고 마지막에 `ROLLBACK`한다. 기존 데이터가 있는 DB의 이관은 이 변경의 범위가 아니며, 보호 조건이 감지하면 migration을 중단한다. 이 결과는 회원가입·로그인·OAuth 서비스 동작의 검증이 아니다.
