# API Flyway migration 소유권과 초기 범위

## 역할과 순서

공통 기반 담당자는 Flyway 설정, 파일명·버전·검증 규칙, 충돌 조정과 공통 문서를 관리한다. ERD의 모든 테이블을 혼자 SQL로 구현하거나 다른 담당자의 Entity·데이터 정책을 확정하지 않는다. 업무 테이블의 migration은 해당 기능 담당자가 대응 Entity와 DB 적용 검증을 함께 작성한다. API 로직은 같은 기능의 후속 작업으로 구현할 수 있다. 여러 기능이 참조하는 테이블은 소유 담당자가 먼저 제공하고, 소비 기능은 참조·삭제 정책을 합의한 뒤 자신의 migration에서 FK를 추가한다.

테이블·컬럼 이름은 [ERD v3.5](../erd/zoop-core-erd-v3.5.md)에 명시된 이름을 우선한다. 따라서 `members`, `member_sessions`, `companies`, `company_aliases`처럼 ERD의 복수형 이름을 단수형으로 바꾸지 않는다. 전체 60개 테이블을 초기 migration 하나에 넣지 않는다. 현재 첫 migration은 인증 저장 기반만 만들며, 다른 기능 담당자는 독립적으로 개발할 수 있다.

| 범위 | 소유 담당 | 처음 필요한 테이블 | 후속 테이블·조건 |
| --- | --- | --- | --- |
| 이메일 인증·회원 세션 | 임현 — WBS 6.2.1 | `members`, `member_credentials`, `member_sessions` | 실제 회원가입에는 `terms`, `term_versions`, `term_agreements`와 승인된 약관 데이터가 필요하다. 비회원 세션은 `member_sessions`를 공유한다. |
| 소셜 인증·온보딩·관리자 인증 | 임현 — 관련 WBS | 첫 인증 범위에 추가하지 않음 | 기능 착수 시 각각 `social_identities`, `member_settings`, `admins`·관리자 권한/세션 테이블을 추가한다. |
| 기업 목록·검색 | 정세빈 — WBS 6.6.11·6.7.1 | `companies`, `company_aliases` | 검색어 `q`가 이름·별칭·티커·ID를 지원하므로 두 테이블을 함께 설계한다. |
| 관심종목 | 임현 — WBS 6.3.4·6.4.1·6.4.2 | `watchlist` | `members.id`, `companies.id`에 의존한다. 두 소유자와 FK·삭제 정책·적용 순서를 합의한다. |

첫 인증 migration인 [`V20261012210200__create_auth_identity.sql`](../../api/src/main/resources/db/migration/V20261012210200__create_auth_identity.sql)은 `members`의 ID·이메일 고유성·상태, `member_credentials`의 비밀번호 **해시**와 회원 FK, `member_sessions`의 토큰 **해시**·회원/비회원 구분·만료/폐기·CSRF 메타데이터를 ERD대로 정의한다. 대응 JPA Entity는 `api/src/main/java/com/zoop/auth/entity/`에 있다. 비밀번호·세션 토큰·CSRF 비밀 키 원문은 DB에 저장하지 않는다. 이메일 가입을 완료했다고 주장하려면 위 약관 테이블과 버전/동의 검증까지 구현한다. 첫 migration에 모든 인증 하위 기능을 밀어 넣을 필요는 없다.

첫 적용과 데이터 보존의 로컬 검증 결과는 [2026-10-12 인증 migration 검증 기록](auth-migration-verification-2026-10-12.md)에 있다.

기업 카탈로그 migration의 소유자는 정세빈이다. `companies.id`는 Neo4j 기업 노드와 동일 ID를 사용하고, `company_aliases.company_id`는 `companies.id`를 참조한다. 기업 검색 담당자가 ERD의 부분 UNIQUE 인덱스와 검색 인덱스를 구현한다. PostgreSQL에 Neo4j Issue·Relation 원본이나 가짜 SQL FK를 만들지 않는다. 기업 데이터 공급원·ID 공유 절차와 `alias_key` 정규화 규칙은 실제 적재·검색 전에 기업·데이터 담당자가 합의한다.

## 공통 적용 규칙

1. 기능 담당자는 `api/src/main/resources/db/migration/V<버전>__<설명>.sql`을 추가하고 같은 PR에서 대응 Entity와 검증 결과를 제출한다. 이미 공유 DB에 적용된 migration을 수정하지 않는다.
2. 병렬 브랜치의 버전·FK 순서는 병합 전에 조정한다. 아직 공유되지 않은 자신의 파일만 이름을 바꾸고, 새 DB와 이전 버전 DB 양쪽에 순서대로 적용되는지 확인한다.
3. JPA `ddl-auto: validate`를 유지한다. 테이블은 Flyway SQL이 만들며, Spring Boot 기동 시 Entity와 스키마가 맞는지 검증한다.
4. 공통 기반 담당자는 버전 충돌·공유 설정·검증 절차를 조정한다. 업무 컬럼의 의미·데이터 출처·삭제 정책은 해당 테이블 소유자가 ERD·API 계약에 맞춰 결정하고 영향받는 담당자와 협의한다.
