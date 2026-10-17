# #36 · 인증 기능 통합 검증

2026-10-16 · WBS 6.2.8 · 담당: 임현·박주형.
기준: main `5f790a9` / 로컬 브랜치 `test/36-auth-integration`.
로컬 검증 후 사용자 요청으로 PR을 제출한다. 병합은 팀장이 담당한다.

## 범위와 재현된 결함

D-AUT-01 로그인·비회원 시작, D-AUT-02 이메일/소셜 가입 완료, 보호 라우트와 D-MY-01 로그아웃 경계를 검증한다. 목표 인증 계약은 `docs/api/openapi.yaml`의 `/api/v1/auth/*`와 HttpOnly 세션 쿠키·CSRF다. 관리자 인증은 #145 범위다.

기존 `logout()`이 요청 성공 여부와 무관하게 `finally`에서 회원 상태를 지웠다. 서버 통신이 실패해 쿠키가 유효한데도 로그인 화면으로 이동했으며, 실제 페이지의 비동기 클릭 오류도 처리하지 않았다. 새 테스트에서 먼저 실패를 확인했다.

- 서버의 로그아웃 성공을 확인한 뒤에만 현재 세션·초안·개인 필터를 지운다.
- 실패 시 로그인 상태를 유지하고 내 종목의 로그아웃 버튼 옆에 안내·재시도를 제공한다. 요청 중 중복 클릭을 막는다.
- 이전 회원의 성공/실패 응답이 새 회원의 세션이나 안내를 덮어쓰지 않게 한다.
- 기존 회원/비회원 라우트·로그인 복귀 주소·쿠키 및 CSRF 방식을 유지한다. 새 UI는 Tailwind와 기존 토큰을 사용한다.

## 자동 테스트

`web/tests/auth/authJourney.test.tsx`의 13개 사례는 실제 LoginPage·SignupPage·MyStocksPage·ProtectedRoute, 인증 훅, 공통 전송 계층과 스토어를 함께 사용한다. HTTP producer만 합성이다. 목적지의 지도·온보딩 본문은 해당 WBS와 분리해 목적지 표시로 확인한다.

| 검증                                                                                        | 증거                                    |
| ------------------------------------------------------------------------------------------- | --------------------------------------- |
| 보호 주소 → 로그인 → 원래 query/hash 복귀 → 메모리 초기화 후 쿠키 복원 → 실제 로그아웃 버튼 | authJourney                             |
| 회원 API 401 → 이전 데이터 초기화 → 다른 회원 재로그인                                      | authJourney + session-regressions       |
| 게스트/위조 로컬 토큰의 회원 화면 차단, 세션 조회 실패/재시도                               | authJourney + login                     |
| 인증 성공 후 종목 조회 실패 시 재조회만 제공·로그인 POST 중복 방지                          | authJourney                             |
| 최신 약관으로 이메일 가입 → 쿠키 확인 → 초기 설정                                           | authJourney + email-entry               |
| 구글/카카오 콜백 후 쿠키 복원, 소셜 가입 응답 유실 복구                                     | authJourney + social-signup             |
| CSRF·권한·소셜 state/PKCE/nonce/콜백 실패·이메일 충돌                                       | 기존 api 인증 controller/service 테스트 |
| 실제 PostgreSQL의 가입·비밀번호·동의·세션·만료·폐기·동시성·롤백                             | 기존 authIntegrationTest                |
| 로그아웃 실패 재현, 성공 후 정리, 중복 클릭 방지, 이전 회원 응답 무시                       | authJourney                             |

### 최종 실행 결과

- `pnpm --dir web exec vitest run --maxWorkers=1 --no-file-parallelism`: **34 files / 320 tests 통과** (164.02초).
- `pnpm --dir web exec vitest run tests/auth tests/my --maxWorkers=1 --no-file-parallelism`: **7 files / 95 tests 통과**.
- `pnpm --dir web lint`, 테스트 TypeScript, `format:check`, `build`, `git diff --check`: 통과. 기존 지도 번들 크기 및 fixture import 경고 유지.
- Java 21에서 `api/gradlew.bat test --tests 'com.zoop.auth.*' --no-daemon`: **72개 실행·통과**. DB 환경이 없는 이 태스크에서 건너뛴 19개는 다음 전용 태스크로 별도 실행했다. 건너뛴 사례를 통과 수에 넣지 않았다.
- 별도 DB 환경에서 `api/gradlew.bat authIntegrationTest --no-daemon`: **5개 클래스 / 19개 테스트 통과, skip 0**. Flyway·JPA validate 포함.

## 실제 브라우저·API·DB 확인

Chromium 1440px·390px, 테스트 전용 HTTPS Vite → 실제 Java API → 별도 PostgreSQL DB로 실행했다. 원격 사용자 데이터나 기존 개발 DB는 사용하지 않았다.

1. 새 쿠키 컨텍스트에서 `/my` 접근 시 로그인으로 이동한다.
2. 실제 약관을 조회하고 고유한 합성 이메일로 가입해 `/onboarding`에 도착한다.
3. 발급 쿠키의 HttpOnly·Secure·SameSite=Lax와 새로고침 후 세션 유지를 확인한다. 쿠키 원문은 출력·저장하지 않는다.
4. CSRF가 없는 로그아웃은 실제 서버에서 403이며 회원 세션은 유지된다.
5. 로그아웃 전송만 한 번 강제 실패시켜 안내·회원 상태 유지·재시도를 확인한다. 다른 인증 요청은 실제 서버를 사용한다.
6. 재시도 성공 후 쿠키 제거·anonymous 세션, 틀린 비밀번호 안내와 올바른 재로그인을 확인한다.
7. 해당 고유 합성 회원의 세션만 테스트 DB에서 만료시킨 뒤 새로고침하면 로그인으로 돌아가고 쿠키가 제거되는지 확인한다.
8. 두 너비에서 문서 가로 넘침·런타임 오류가 없음을 확인했다.

브라우저 자동화는 로그인과 가입 화면의 필드 이름이 같으므로, 가입 링크 클릭 후 **가입 화면 제목이 나타날 때까지 기다린 뒤** 입력해야 한다. 초기 검증 스크립트가 전환 전 로그인 필드에 입력해 가입 대기 시간이 초과됐으며, 화면 전환 대기를 추가한 후 두 너비가 통과했다.

### 재실행 환경

- Java 21, pnpm은 `web/package.json` 기준. PostgreSQL 16.13.
- DB는 새 일회성 테스트 DB를 만든다. 이번 실행은 기존 로컬 PostgreSQL 컨테이너의 **별도 DB `zoop_auth_issue36_20261016`**만 사용했다. 기존 `zoop` DB는 변경하지 않았다.
- `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`는 테스트 프로세스 환경으로만 주입한다. 실제 `.env`를 복사하거나 출력하지 않는다.
- Java API: 테스트용 `ZOOP_AUTH_CSRF_ACTIVE_KEY_ID`/`ZOOP_AUTH_CSRF_KEYS`, 정확한 `ZOOP_AUTH_ALLOWED_ORIGINS=https://localhost:5342`, `SERVER_PORT=8186`로 실행했다.
- HTTPS Vite: `ZOOP_DEV_API_TARGET=http://127.0.0.1:8186`와 로컬 개발 인증서 경로를 환경에 넣고 `pnpm exec vite --host localhost --port 5342 --strictPort`로 실행한다. 인증서·개인키는 Git에 넣지 않는다.
- 브라우저는 위 순서대로 검증한다. 네트워크 로그·storageState·trace·쿠키 원문을 저장하지 않는다. 재실행마다 새 합성 이메일과 컨텍스트를 사용한다. 만료 시험은 전용 DB의 그 회원만 수정한다.

## 검증 한계와 인계

- 외부 구글·카카오 로그인 창에서 실제 계정을 인증하는 절차는 이번에 다시 실행하지 않았다. 기존 사용자 확인 결과를 대체하지 않으며 서버의 소셜 테스트와 프론트 콜백 이후 흐름을 확인했다.
- 내 종목의 실제 보유/관심 API는 이번 Java 서버에서 미구현 응답이 있어 해당 조회 실패 안내가 표시됐다. 이 검증의 대상은 보호·인증·로그아웃이며, 내 종목 전체 실제 연동 완료를 의미하지 않는다(#51 별도).
- 저장소 와이어프레임 manifest에 D-MY-01 개별 이미지가 없다. 인증 보드·D-AUT-01/02 이미지를 확인하고 D-MY 기존 구현의 로그아웃 영역에만 상태 안내를 보완했다. 다른 화면 배치를 변경하지 않았다.
- 새 의존성·DB migration·계약 정본·서버 제품 코드 변경은 없다. 아래 증거는 로컬 실행 결과이며 원격 CI는 PR checks에서 별도로 확인한다. 배포는 실행하지 않았다.
- 되돌릴 경우 회원 logout helper와 MyStocksPage의 처리, 새 테스트·이 문서를 하나의 변경으로 되돌린다. 테스트 DB에는 합성 검증 자료만 남긴다.
