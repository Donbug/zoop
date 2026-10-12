# 인증 첫 migration 로컬 적용 검증 — 2026-10-12

## 대상과 환경

- SQL: [`V20261012210200__create_auth_identity.sql`](../../api/src/main/resources/db/migration/V20261012210200__create_auth_identity.sql)
- 앱: Java 21, Spring Boot 4.1.1, JPA `ddl-auto: validate`, Flyway
- DB: PostgreSQL 16.13 Alpine, 별도 Docker Compose 프로젝트와 임시 볼륨
- 입력: `example.invalid` 도메인과 합성 해시·ID만 사용. 기존 개발 DB 또는 프로토타입 DB에 연결하지 않음

## 확인 결과

| 시나리오 | 관측 결과 |
| --- | --- |
| 빈 DB에 Spring Boot 최초 기동 | Flyway 버전 `20261012210200` 1개 적용, 앱 기동·JPA 검증 성공 |
| 테이블·이력 | `members`, `member_credentials`, `member_sessions`, `flyway_schema_history` 생성; 이력의 `success=true` |
| 인덱스 | PK·고유 인덱스 외에 활성 회원 세션 `(member_id, expires_at)` 부분 인덱스와 `expires_at` 인덱스 존재 |
| 정상 데이터 | 합성 회원 1건, 자격 1건, 회원 세션 1건, 비회원 세션 1건 삽입 성공 |
| 제약 | 중복 `email_key`는 UNIQUE, 없는 `member_id`는 FK, 소유자 없는 회원 세션과 CSRF 버전 0은 CHECK에서 거절 |
| 데이터가 있는 DB에 재기동 | Flyway `No migration necessary`, JPA 검증·앱 기동 성공; 이력 1건과 합성 데이터 건수 유지 |
| 회원 삭제 정책 | 트랜잭션에서 회원 삭제 시 자격·회원 세션은 CASCADE로 사라지고 독립 비회원 세션은 유지됨; 검증 트랜잭션은 ROLLBACK |

재기동 후 관측된 건수는 `members=1`, `member_credentials=1`, `member_sessions=2`이며 성공한 Flyway 이력은 1건이다. 검증용 컨테이너와 임시 볼륨은 확인 후 제거했다.

## 검증 범위의 한계

이 파일이 **첫 Flyway migration**이므로 적용 전의 구버전 업무 스키마나 이전 Flyway 버전이 존재하지 않는다. 따라서 `V1 → V2` 형태의 실제 스키마 업그레이드는 아직 시험할 수 없다. 이번 검증은 빈 DB의 첫 적용과, 데이터가 있는 같은 DB의 재기동·재적용 방지·보존을 확인했다. 다음 migration이 생기면 바로 이전 버전과 새 빈 DB 양쪽에서 순차 적용을 검증한다.

이 결과는 DB 스키마와 JPA 매핑의 검증이다. 회원가입·로그인·세션 발급·CSRF 서비스 동작 또는 운영 배포를 증명하지 않는다.
