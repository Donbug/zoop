# 소셜 인증·계정 연결 구현 정책 — 이슈 #30 / WBS 6.2.2

상태: **Task 1–7 구현 기준**. FS004의 동일 이메일 연결 요구는 FS061의 기존 서비스 계정 본인·연결 권한 확인을 통과한 경우에 적용한다. 원본 명세의 승인 상태를 바꾸는 문서는 아니다. 실제 Google·카카오 앱 등록과 운영 자격 정보는 별도 배포 준비가 필요하다.

추적: FS004 · FS061 · NFS001/002/004/008 · D-AUT-01. API 정본은 [`docs/api/openapi.yaml`](../api/openapi.yaml), 저장 구조는 [ERD v6](../erd/zoop-core-erd-v6.md)이다. D-AUT-01의 원본 와이어프레임은 시작 화면의 시각·이동 기준이며 OAuth 오류·추가 동의 화면의 동작 증거는 아니다.

## 식별 및 동의 기준

| 항목 | 구현 기준 |
| --- | --- |
| 제공자 | 회원 로그인은 `google`, `kakao`만 지원한다. 관리자 SSO와 구분한다. |
| Google | OIDC 인가 코드 흐름에 `openid email`을 요청한다. 서명·발급자·대상 클라이언트·만료·nonce를 서버에서 검증한다. 식별자는 `sub`이며 최초 가입·연결의 이메일은 `email_verified=true`인 경우만 사용한다. |
| 카카오 | OIDC를 켠 앱의 인가 코드 흐름에 `openid account_email`을 요청한다. ID 토큰의 서명·발급자·대상 앱·만료·nonce를 검증하고, 같은 코드 교환에서 받은 액세스 토큰으로 조회한 사용자 정보의 서비스 사용자 ID와 `sub`를 대조한다. 최초 가입·연결은 `is_email_valid=true`, `is_email_verified=true`인 `kakao_account.email`만 사용한다. |
| 추가 정보 | 이름·사진·전화번호는 필수가 아니며 로그인 목적으로 요청·저장하지 않는다. 표시명은 회원가입 정책의 기본값 `회원`을 사용하고, 사용자가 직접 입력한 값만 별도 검증한다. |
| 이메일 비교 | 기존 `EmailAddress`의 `email_key`: 앞뒤 공백 제거 후 전체 `Locale.ROOT` 소문자. 제공자별 별칭은 합치지 않는다. 이미 연결된 `(provider, subject)`는 이메일 변경·누락과 관계없이 같은 회원을 가리킨다. |
| 서비스 약관 | 신규 소셜 회원도 이메일 가입과 동일한 현재 승인 필수 약관 버전에 명시적으로 동의해야 한다. 제공자 동의를 서비스 약관 동의로 간주하지 않는다. |

Google의 `email_verified`, 카카오의 `is_email_valid`·`is_email_verified`는 **제공자 측 이메일 상태**다. 기존 줍 계정의 연결 권한을 증명하지 않는다. 이메일이 없거나 사용할 수 없으면 미연결 계정의 가입·연결을 중단하고 이메일 제공 동의 재요청 또는 다른 로그인 방법을 안내한다. 이미 연결된 subject의 로그인에는 이메일을 다시 요구하지 않는다.

## 서버 흐름

1. `GET /api/v1/auth/social/{provider}/authorize`는 **로그인**을 시작한다. 제공자·허용된 상대 `returnTo`를 검사하고 IP 및 브라우저 결합 키로 시도를 제한한다. 난수 state·nonce·PKCE(S256), 등록된 정확한 redirect URI와 만료 시각을 pending에 묶는다. 브라우저 탐색 GET에는 `Origin` 헤더가 없을 수 있으므로 이 경로와 제공자 callback은 Origin을 인증 근거로 사용하지 않는다.
2. `zoop_oauth_pending`은 `HttpOnly; SameSite=Lax; Path=/api/v1/auth/social`의 host-only 단명 쿠키다. HTTPS에서는 `Secure`를 설정한다. 로컬 개발에서 `ZOOP_AUTH_SOCIAL_ALLOW_INSECURE_LOCALHOST=true`를 명시한 경우에만 HTTP localhost/loopback redirect와 Secure 미설정 쿠키를 허용한다. 공개 인증 주체나 회원 세션이 아니다. state 해시와 쿠키, 제공자, redirect URI, PKCE 및 만료를 서버에서 대조하고 callback을 일회성으로 claim한다. 서명·issuer·audience·만료·nonce 검증이 끝나면 provider subject와 사용할 수 있는 이메일만 같은 만료의 identity_verified pending에 보관하고 OAuth 토큰 원문과 PKCE verifier는 제거한다. 같은 브라우저에서 새 시작 요청은 이전 pending을 폐기한다. 기존 `zoop_session`은 시작 시 변경하지 않는다.
   검증을 마친 pending은 `identity_verified`로 저장한다. Task 5 callback 완료 단계에서 기존 연결 로그인, 신규 이메일의 `consent_pending` 전환, 기존 이메일의 `link_required`, 이메일 부재·미검증의 `email_required`로 일회성 분기한다. 신규 가입 분기에서는 쿠키 토큰도 회전한다.
3. 검증된 `(provider, subject)` 연결이 있으면 회원 상태를 확인해 새 회원 세션을 발급한다. 제공자 이메일 변경으로 회원을 재배정하지 않는다.
4. 연결이 없고 사용 가능한 이메일의 기존 회원이 **없으면**, 검증된 제공자 결과를 짧게 보관하고 `/signup?social=pending`으로 돌려보낸다. signup endpoint 완료 전에는 회원 세션을 발급하지 않는다.
5. 연결이 없고 같은 `email_key`의 기존 회원이 **있으면**, callback은 계정을 연결하거나 로그인하지 않고 `/login?social=link_required`로 돌려보낸다. 검증된 결과를 나중에 자동 연결하는 티켓으로 남기지 않는다. 사용자는 기존 계정으로 먼저 로그인한 후 명시적으로 연결을 시작한다.
6. Task 6 `POST /api/v1/auth/social/signup`은 pending 쿠키의 검증 이메일·provider subject, 현재 필수 약관 동의, 허용 Origin을 확인한다. 요청 본문은 표시명과 동의 내역만 받는다. pending 소비, 회원 생성, 동의 기록, identity 연결, 회원 세션 발급은 하나의 DB 트랜잭션에서 처리하며 성공 시 새 세션 쿠키와 pending 삭제 쿠키를 보낸다. 같은 이메일의 회원이 생겼으면 pending을 소비하고 `SOCIAL_LINK_REQUIRED`를 반환한다.
7. Task 7 `POST /api/v1/auth/social/{provider}/link/authorize`는 활성 회원 세션과 그 세션의 `X-CSRF-Token`, 허용 Origin을 요구한다. 응답의 제공자 URL로 이동하면 새로운 OAuth 왕복이 시작된다. pending에 회원 ID와 **그 세션 ID** 및 `intent=link`를 묶는다. callback에서 같은 활성 세션인지 재검증하고 subject가 다른 회원에 연결되지 않았으며 확인된 이메일의 `email_key`가 기존 회원과 일치할 때만 연결한다. 연결만으로 새 회원 세션을 발급하지 않는다. 세션 교체·만료, 이메일 불일치, 다른 회원에 연결된 subject는 거절한다. 이미 같은 회원에 연결된 subject는 중복 identity를 만들지 않고 성공으로 처리한다.
8. 기존 이메일 계정은 기존 비밀번호 로그인으로, 소셜 전용 계정은 이미 연결된 제공자로 로그인한 후 7번을 이용한다. 제공자의 이메일 확인 표시나 이메일 주소만으로 기존 계정을 인증하거나 연결하지 않는다. 복구 수단이 없는 회원에게 우회 연결을 허용하지 않는다.

이미 같은 회원에 연결된 `(provider, subject)`의 명시적 연결 재시도는 중복 행을 만들지 않고 완료 상태로 처리한다. 다른 회원에 연결돼 있으면 현재 회원에게 이전 연결을 이전하지 않는다.

`returnTo`는 동일 서비스의 허용된 상대 경로만 받고 외부 URL·`//`·역슬래시·제어 문자를 거절한다. 실패·취소의 복귀 URL에는 이메일, subject, 인가 코드, 토큰 또는 state를 넣지 않는다. 성공 후 화면 이동은 기존 `getMemberSession`의 `setup.completed`와 회원 본인의 설정에 따른다. callback 응답 미수신 시에는 세션을 재조회하며 동일 코드를 재사용해 새 회원을 만들지 않는다.

## 실패와 복구

| 상황 | 결과 |
| --- | --- |
| 사용자 취소 | pending 폐기, 회원·연결·세션 변경 없음, `/login?social=cancelled`에서 재선택 |
| state/nonce/쿠키/코드 검증 실패 또는 재사용 | pending 폐기, 변경 없음, `/login?social=failed`; 상세 인증 정보를 URL·로그에 노출하지 않음 |
| 제공자 장애 | 변경 없음, 다시 시도 가능하다고 안내. 요청 전체 실패는 `SOURCE_UNAVAILABLE` |
| 이메일 없음·확인 불가 | 미연결 계정의 가입·연결 중지, `/login?social=email_required`에서 동의 재요청/다른 방식 안내 |
| 기존 이메일 계정 발견 | 연결·로그인 없음, `/login?social=link_required`에서 기존 계정 로그인 후 명시적 연결 안내 |
| 가입 약관 누락·승인 버전 변경 | 회원·연결·세션 생성 없음, 약관을 다시 조회해 동의 |
| 연결 중 기존 세션 변경·subject 충돌 | 연결 없음; 재인증 또는 계정 확인 안내 |

모든 완료 경로는 DB 유일 제약과 트랜잭션으로 경합을 처리한다. `social_identities`에 `(provider, provider_subject)` 유일성을 둔다. OAuth pending 만료와 시작 요청 제한값은 운영 설정으로 관리하고 테스트에서는 고정 시계로 검증한다. 비밀값·토큰·제공자 원문 응답은 로그와 fixture에 남기지 않는다.

## 구현·배포 전 확인

- Google·카카오 개발자 콘솔에 OIDC 사용, 이메일 동의 항목, 정확한 HTTPS callback URI를 등록한다. 카카오에서 필요한 이메일 동의를 제공할 수 없는 앱 설정이면 해당 제공자의 신규 가입·연결을 활성화하지 않는다.
- OAuth pending TTL은 `ZOOP_AUTH_SOCIAL_PENDING_TTL`(기본 10분), 15분 시작 제한은 `ZOOP_AUTH_SOCIAL_START_IP_LIMIT`(기본 IP당 30회)과 `ZOOP_AUTH_SOCIAL_START_BROWSER_LIMIT`(기본 브라우저당 10회), 허용 복귀 경로는 `ZOOP_AUTH_SOCIAL_RETURN_PATHS`(기본 `/login,/signup,/`)로 설정한다. Google은 `ZOOP_AUTH_SOCIAL_GOOGLE_CLIENT_ID`, `ZOOP_AUTH_SOCIAL_GOOGLE_CLIENT_SECRET`, `ZOOP_AUTH_SOCIAL_GOOGLE_REDIRECT_URI`, 카카오는 `ZOOP_AUTH_SOCIAL_KAKAO_CLIENT_ID`, `ZOOP_AUTH_SOCIAL_KAKAO_CLIENT_SECRET`, `ZOOP_AUTH_SOCIAL_KAKAO_REDIRECT_URI`를 설정한다. callback 완료 후 프론트엔드 복귀 origin은 `ZOOP_AUTH_SOCIAL_FRONTEND_ORIGIN`으로 지정하며, 소셜 제공자가 활성화된 환경에서는 유효한 origin이 필수다. 로컬 프로필 기본값은 `http://localhost:5173`이다. 운영에서는 프론트엔드 HTTPS origin을 지정한다. 운영 redirect URI는 등록한 정확한 HTTPS callback 주소여야 한다. 로컬에서는 Google `http://localhost:8080/api/v1/auth/social/google/callback`, 카카오 `http://localhost:8080/api/v1/auth/social/kakao/callback`을 등록하고, 개발 환경에서만 `ZOOP_AUTH_SOCIAL_ALLOW_INSECURE_LOCALHOST=true`를 설정한다. 미설정 provider는 목록에 노출되지만 authorize는 `SOURCE_UNAVAILABLE`로 응답한다.
- D-AUT-01의 `link_required`·`email_required` 안내 및 소셜 신규 가입 약관 동의 UI는 후속 UI 작업에서 화면 계획과 함께 검증한다. 새 화면 ID를 임의로 만들지 않는다.

제공자 문서: [Google OIDC](https://developers.google.com/identity/openid-connect/openid-connect), [카카오 로그인 REST API](https://developers.kakao.com/docs/en/kakaologin/rest-api), [카카오 OIDC 검증](https://developers.kakao.com/docs/en/kakaologin/utilize).
