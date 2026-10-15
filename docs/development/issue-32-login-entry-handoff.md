# 이슈 #32 로그인 후 초기 진입 상태 인계

**범위:** BE WBS 6.2.4 · FS001 · FS006 · NFS001
**화면 추적:** `D-AUT-01` · `D-ONB-01`
**API 계약:** `docs/api/openapi.yaml`의 `getMemberSession`, `login_api_auth_login_post`

## 검증된 서버 동작

- `POST /api/v1/auth/login` 성공 응답은 발급한 회원 세션을 나타냅니다. `GET /api/v1/auth/session`은 같은 `zoop_session` 쿠키로 현재 회원과 설정 상태를 다시 조회합니다.
- 로그인 응답의 `user`와 `setup`은 로그인 직후 세션 조회의 값과 일치해야 합니다. PostgreSQL 통합 테스트가 이를 확인합니다.
- 회원 세션은 발급 시점에 설정 상태를 고정하지 않습니다. 세션 조회 때 회원 행의 최신 `completed`, `tutorial_completed` 값을 읽으며 회원 간 값을 공유하지 않습니다.
- `anonymous`에는 회원의 `user` 및 `setup`이 없습니다. `guest`는 `user=null`, `setup.completed=false`, `setup.tutorialCompleted=false`입니다. 게스트 세션은 회원 설정을 나타내지 않습니다.
- 로그인 실패와 차단 계정은 인증된 세션을 발급하지 않습니다. 잘못된 자격 증명은 `401 INVALID_CREDENTIALS`, 차단 계정은 `403 MEMBER_BLOCKED`입니다.

## FE 진입 분기 인계

| `GET /api/v1/auth/session` 결과 | FE 처리 기준 | 추적 |
|---|---|---|
| `anonymous` | 로그인/시작 화면 표시 | `D-AUT-01`, FS001 |
| `guest` | 게스트의 시장 진입 흐름 유지; 회원 설정을 적용하지 않음 | `D-AUT-01`, FS001 |
| `member`, `setup.completed=false` | 초기 설정 흐름으로 이동 | `D-ONB-01`, FS006 |
| `member`, `setup.completed=true` | 메인 진입. 보유종목·관심종목이 있으면 해당 데이터를 그래프 조회에 사용하고, 둘 다 없으면 전체 시장 그래프 기준을 적용 | FS006 |

화면 이동과 로딩·실패·재시도 UX는 FE WBS 6.2.6/6.2.7의 책임입니다. 이 BE 범위는 분기에 필요한 세션 상태와 로그인 응답의 일관성을 제공합니다.

세션 응답은 보유종목이나 관심종목을 싣지 않습니다. FE는 각 데이터의 전용 조회 계약을 별도로 호출해야 합니다. 사용 가능한 실제 조회 경로와 저장 상태를 확인한 뒤 해당 API에 연결해야 하며, 세션 상태만으로 종목 데이터가 존재한다고 추정하면 안 됩니다.

## 오류 및 복구 기준

회원 또는 설정 상태 조회에서 저장소 오류가 발생하면 완료 상태로 대체하지 않고 API 오류로 처리합니다. 구체적인 사용자 안내와 재시도 시점은 원문 요구에서 결정되지 않았으므로 FE/제품 결정으로 남깁니다. FE는 세션 조회 실패를 `setup.completed=true`로 간주하지 않고 오류 응답에 따라 재조회/복구 UX를 결정해야 합니다.

## 확인 명령

- `make api-test api-build`
- PostgreSQL 환경에서 `authIntegrationTest` 실행: 로그인 응답과 세션 재조회 일치, 최신 설정값, 회원 간 격리, 기존 로그인 실패·차단 계정 동작 확인
