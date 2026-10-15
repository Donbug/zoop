# Issue #31 · 비회원 접근 및 권한 처리 인계

**추적:** WBS 6.2.3 · FS005 · NFS001 · API 목표 계약 `docs/api/openapi.yaml`

## 구현 범위와 증거

| 항목 | 동작 | 구현·검증 근거 |
|---|---|---|
| 비회원 시작 | `POST /api/v1/auth/guest`가 guest 세션과 `zoop_session` 쿠키를 발급한다. 12시간 절대 만료이며 기존 guest 쿠키를 받으면 그 guest 행을 회전 폐기한다. 회원 행은 guest 시작 때문에 폐기하지 않는다. | `GuestSessionController`, `MemberSessionService.issueGuest`, `JdbcMemberSessionRepository.insertGuestSession` |
| 세션 복구 | `GET /api/v1/auth/session`은 유효 guest에 `kind=guest`, `user=null`, `completed=false`, `tutorialCompleted=false`, 만료 시각, guest 결합 CSRF를 반환한다. 만료·폐기·무효 세션은 anonymous이며 무효 쿠키를 지운다. | `MemberSessionService.lookup`; `MemberSessionServiceTest` |
| 튜토리얼 무저장 | guest의 완료 응답은 항상 false다. DB는 guest 행의 `tutorial_completed=true`를 거부한다. 계약상 튜토리얼 저장은 회원 전용이며, 해당 컨트롤러를 구현하면 등록된 권한 경계가 guest를 `403 MEMBER_REQUIRED`로 거부한다. 현재 이 API 모듈에는 튜토리얼 저장 컨트롤러가 없으므로 실제 HTTP 호출은 아직 구현된 동작이 아니다. 클라이언트는 진행·완료·건너뛰기 상태를 로컬에서만 관리한다. | `MemberAuthorizationInterceptor`; `V20261015120000__keep_guest_tutorial_state_unset.sql`; 서비스·권한 테스트 |
| 세션의 개인 정보 | `GET /api/v1/auth/session`은 쿠키에 연결된 member만 반환하고 guest에는 `user=null`을 반환한다. PostgreSQL 통합 테스트가 회원 A/B의 쿠키별 응답과 guest 응답을 실제 컨트롤러 경로에서 확인한다. | `MemberSessionService.lookup`; `MemberSessionPostgresTest.sessionHttpResponseOnlyReturnsTheMemberBoundToTheCookie` |
| 회원 전용 경계 기반 | 회원 전용으로 등록된 핸들러는 인증 없는 요청을 `401 AUTH_REQUIRED`, guest를 `403 MEMBER_REQUIRED`로 거부하며, 리소스 소유자와 principal이 다르면 `requireOwner`가 `403 ACCESS_DENIED`를 낸다. | `MemberSessionService.requireMember/requireOwner`; `MemberAuthorizationInterceptorTest`; `MemberSessionServiceTest` |

현재 `api` 앱에는 `/me`, `/portfolio`, `/chat`, `/feedback`, 개인화 브리핑의 업무 컨트롤러가 없고, `requireOwner`를 실제 리소스 조회에서 호출하는 코드도 없습니다. 따라서 세션 API의 개인 정보가 쿠키별로 격리되는 것은 검증됐지만, 개인 리소스의 타 회원 접근 차단은 아직 종단 간으로 검증되지 않았습니다. 해당 컨트롤러를 구현할 때 저장소 조회를 principal에 결합하고 HTTP/PostgreSQL 통합 테스트로 회원 A·회원 B·guest의 접근을 확인해야 합니다.

## 화면 ID 연결

요구사항 연결 화면 ID를 빠짐없이 보존합니다. 이 목록은 FE 인계와 추적용이며, BE 변경이 해당 화면 UI 구현을 완료했다는 뜻은 아닙니다.

| 흐름 | 화면 ID | FE에서 확인할 동작 |
|---|---|---|
| 시작·세션·온보딩 | `D-AUT-01`, `M-GRP-01`, `D-ONB-01`, `D-AUT-02`, `D-MY-01` | guest 시작 후 개인 설정을 건너뛰고 시장 그래프로 진입. 회원 시작·로그인 분기는 기존 동작 유지. |
| 그래프 튜토리얼 | `D-GRP-T`, `D-GRP-T2`, `D-GRP-T3`, `D-GRP-T4`, `D-GRP-T5` | guest와 회원에게 같은 튜토리얼을 제공. guest 진행·완료·건너뛰기는 저장하지 않고 다시 보기는 첫 단계부터 실행. |
| 회원 전용 초기 설정 | `D-WAT-01`, `D-ONB-02`, `D-WAT-01b` | guest의 관심 종목·가상 계좌 조작은 로그인 안내로 연결하고 서버 요청도 거절되는지 확인. |
| 그래프·종목·기업·사건·근거 | `D-GRP-01`, `D-GRP-01b`, `D-GRP-02`, `D-GRP-03`, `D-GRP-04`, `D-GRP-05`, `D-GRP-06`, `D-GRP-07`, `D-GRP-07b`, `D-STK-01`, `M-STK-01`, `D-COM-01`, `D-COM-01b`, `D-COM-02`, `D-COM-03`, `D-COM-04`, `D-COM-05`, `D-COM-06`, `M-COM-01`, `M-COM-02` | 공개 그래프·기업·사건·근거는 읽기 허용. 개인 지도·다른 회원 데이터는 접근 불가. |
| 브리핑 | `D-BRF-01`, `D-BRF-02`, `D-BRF-04`, `M-BRF-01` | 공개 브리핑은 읽기 허용, 개인화 브리핑은 회원 세션 및 소유 범위 확인. |
| AI·개인 피드백 | `D-AI-01`, `D-AI-01b`, `D-AI-02`, `D-AI-02b`, `M-AI-01` | guest 질문 제출은 UI 안내와 서버 `MEMBER_REQUIRED`로 모두 차단. 저장된 개인 대화·피드백은 회원 소유권 확인. |
| 센티먼트·뉴스 상세 | `D-SEN-01`, `D-SEN-02` | 공개 데이터 읽기는 공개 조회 권한에 따르고 개인 데이터는 반환하지 않는다. |
| 관리자 | `A-ADM-01`, `A-ADM-02`, `A-ADM-02b`, `A-ADM-03`, `A-ADM-04`, `A-ADM-04b`, `A-ADM-05`, `A-ADM-05b`, `A-ADM-05c` | 관리자 인증 경계는 이 구현의 회원/guest 인터셉터 범위가 아니다. 관리자 권한 검증을 별도로 적용한다. |

## 상태·복구 검증 인계

| 상태 | 계약·검증 책임 |
|---|---|
| 정상 | guest 세션은 200이며 공개 그래프·기업·브리핑 조회를 계속 허용한다. 세션 테스트는 응답 kind, 비어 있는 user, false 설정 상태, CSRF 및 만료를 검증한다. |
| 로딩 | 세션 발급·조회와 공개 데이터 조회 중 UI 로딩 표시는 FE에서 확인한다. API가 로딩 상태를 별도 응답으로 만들지 않는다. |
| 빈 데이터 | 빈 공개 목록/그래프 데이터는 성공 상태로 처리한다. `api`에 그래프·브리핑 컨트롤러가 없어 실제 데이터 경계는 해당 기능 통합 테스트에서 확인한다. |
| 권한 없음 | 등록된 회원 전용 핸들러에서 유효 세션 없음은 401, guest는 403 `MEMBER_REQUIRED`, 타 회원 소유 데이터는 403 `ACCESS_DENIED`. 응답에 보호 데이터가 없어야 한다. 해당 개인 리소스·튜토리얼 저장 핸들러는 이 앱에 아직 없으며 통합 시 HTTP 수준으로 확인한다. |
| 실패 | 잘못된 Origin/CSRF는 `ACCESS_DENIED`; 저장소 장애와 5xx는 공통 오류 응답을 따른다. 메인 그래프 진입은 튜토리얼 진행/저장 장애 때문에 막히지 않는다. |
| 재시도·복구 | session GET은 새 세션을 만들지 않는다. 만료/무효 쿠키를 제거한 뒤 guest 시작을 다시 할 수 있다. 공개 읽기는 실패 영역만 다시 조회하며, 화면 입력·선택은 FE가 보존한다. |

화면계획서 v1.7 38쪽은 guest의 튜토리얼 상태 미저장, 개인 설정·AI 질문 로그인 제한, 그래프 오류 재시도와 튜토리얼 로딩 실패가 메인 그래프를 막지 않는 동작을 명시합니다. 개별 화면 연결은 `docs/wireframe/manifest.json`과 `docs/system/out/screen-D-GRP-T*.md`를 참조하세요.

## 검증과 롤백

- `./gradlew test`: 전체 API 단위·웹 계층 테스트 통과.
- 관련 테스트: `MemberSessionServiceTest`, `GuestSessionControllerTest`, `MemberAuthorizationInterceptorTest`, `SessionControllerTest`.
- `DB_URL=jdbc:postgresql://127.0.0.1:55439/zoop_auth_test ./api/gradlew -p api --console=plain authIntegrationTest`: 2026-10-15 Docker 임시 PostgreSQL에서 16개 통합 테스트 통과. guest 저장·회전·CHECK 제약 및 세션 HTTP 응답의 회원/guest 격리를 확인했습니다.
- DB migration은 Flyway 순방향 변경입니다. 애플리케이션 롤백 시 새 guest/tutorial 기능 호출을 중단하고 기존 앱을 재배포합니다. 이미 적용된 CHECK 제약은 false 상태를 강제하며 기존 member/OAuth 행에는 영향을 주지 않습니다.
