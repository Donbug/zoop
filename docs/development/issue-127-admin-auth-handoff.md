# Issue #127 — 관리자 인증 API 구현 인계

## 포함 범위

- Task 1: 관리자 계정·세션·감사로그·인증 제한 저장소 및 운영자 전용 계정 프로비저닝 명령.
- Task 2: 관리자 이메일/비밀번호 로그인, 자격 증명 오류 통합 응답, IP/이메일 속도 제한, 실패 감사 이벤트.
- Task 3: 별도 `zoop_admin_session` HttpOnly 쿠키, DB에는 토큰 해시만 저장, 30분 유휴/8시간 절대 만료, 현재 계정 상태 재검증, 관리자 세션 조회·로그아웃.
- Task 4: 관리자 경로 권한 인터셉터. 승인된 `admin` 역할은 모든 관리자 권한을 가진다. 회원 CSRF와 독립된 세션 결합 관리자 CSRF 토큰을 쓴다.
- Task 5: 로그인/실패/로그아웃 감사 추적과 PostgreSQL 기반 인증·세션 회귀 테스트.
- Task 6: API 계약 및 화면/요구사항 추적 문서 갱신.

## API

| 메서드 | 경로 | 동작 |
| --- | --- | --- |
| POST | `/api/v1/admin/auth/login` | 허용 Origin + 자격 증명으로 로그인. 세션 JSON, CSRF 토큰, `zoop_admin_session` 쿠키 반환 |
| GET | `/api/v1/admin/auth/session` | 관리자 세션 상태 확인. 만료/무효 세션이면 관리자 쿠키 제거 |
| POST | `/api/v1/admin/auth/logout` | 활성 세션은 허용 Origin 및 동일 세션 CSRF 검증 후 폐기. 반복·무세션 로그아웃은 204 |
| `/api/v1/admin/**` | 기타 경로 | 인증된 활성 `admin` 계정만 허용. 쓰기 요청은 Origin 및 관리자 CSRF 검증 |

로그인 실패는 계정 존재 여부를 드러내지 않으며 비밀번호를 로그/감사 이벤트에 기록하지 않는다. 세션 생성과 성공 감사 로그는 동일 트랜잭션으로 처리한다. 실패 감사는 인증 요청 롤백과 분리해 보존한다. 로그인 성공 시 기존 관리자 세션이 있으면 폐기한다. 회원 세션/쿠키/소유권 정책은 변경하지 않는다.

## 설정 및 운영

- `ZOOP_ADMIN_IDLE_TIMEOUT` 기본 `30m`, `ZOOP_ADMIN_ABSOLUTE_TIMEOUT` 기본 `8h`.
- `ZOOP_AUTH_ALLOWED_ORIGINS`에 관리자 웹 Origin을 포함하고 TLS에서 `zoop.auth.session-cookie-secure=true` 유지.
- `AdminProvisioningRunner`는 웹 서버가 아닌 명시적 `--spring.main.web-application-type=none` 실행에서만 활성화된다. 비밀번호는 대화형 입력으로 받고 DB에는 기존 password encoder 형식 해시로 저장한다. 계정은 migration seed로 만들지 않는다.
- 인증 CSRF key ring의 활성/이전 키 설정은 회원 인증과 공통이다. CSRF 목적 도메인은 `admin`으로 분리한다.

## 요구사항·화면 추적

인증 계약은 FS073을 구현하고 NFS001 회원 데이터 소유권 경계의 회귀를 막는다. 관리자 로그인 화면 `A-ADM-05c`, 관리자 진입/로그아웃 화면 `A-ADM-01`은 `docs/api/openapi.yaml`의 `x-zoop.screenIds`로 연결했다. 이슈에서 함께 연결한 화면 ID 전체는 `A-ADM-05c`, `A-ADM-01`, `D-AUT-01`, `D-ONB-01`, `D-AUT-02`, `M-GRP-01`, `D-MY-01`, `D-GRP-T`, `D-GRP-T2`, `D-GRP-T3`, `D-GRP-T4`, `D-GRP-T5`, `D-WAT-01`, `D-ONB-02`, `D-WAT-01b`, `D-GRP-03`, `D-STK-01`, `M-STK-01`, `D-COM-01`, `M-COM-01`, `D-GRP-01`, `D-GRP-01b`, `D-GRP-07`, `D-GRP-07b`, `D-BRF-04`, `D-COM-04`, `D-GRP-04`, `D-COM-03`, `M-COM-02`, `D-COM-01b`, `D-COM-05`, `D-COM-06`, `D-COM-02`, `D-SEN-01`, `D-GRP-02`, `D-GRP-05`, `D-AI-01`, `D-BRF-01`, `D-BRF-02`, `M-BRF-01`, `D-SEN-02`, `M-AI-01`, `D-AI-02b`, `D-AI-01b`, `D-AI-02`, `A-ADM-05b`, `A-ADM-03`, `A-ADM-04b`, `A-ADM-04`, `A-ADM-02`, `A-ADM-02b`, `A-ADM-05`, `D-GRP-06`이다. 나머지 화면은 해당 API 작업에서 UI/상태를 수정하지 않는다. NFS001 회귀는 기존 회원 세션·설정·관심종목·포트폴리오 API의 PostgreSQL 테스트(`MemberSessionPostgresTest`, `MemberSettingsPostgresTest`, `PortfolioPostgresTest`)로 확인한다. 이 문서는 화면 디자인 검증을 주장하지 않는다.

## 검증

- `./api/gradlew -p api test --tests 'com.zoop.admin.auth.*'`
- PostgreSQL 통합 테스트는 `DB_URL` 등 테스트 DB 설정이 제공될 때 활성화된다. 관련 클래스: `AdminAuthPostgresTest`, `AdminAuthMigrationPostgresTest`, `AuthRatePostgresTest`.
- 관리자 UI는 구현하지 않았다.
- 롤백: 애플리케이션/API 변경은 PR revert로 되돌릴 수 있다. 이미 적용된 migration의 테이블 삭제는 계정·감사 기록을 파괴하므로 자동 롤백하지 않는다. 스키마를 제거해야 하면 계정/세션/감사 데이터 보존 필요성을 운영자가 확인한 뒤 별도 승인 migration으로 처리한다.
