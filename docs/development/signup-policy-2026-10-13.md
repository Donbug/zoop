# 이메일 회원가입 정책 결정 기록 — 2026-10-13

상태: **가입 직후 로그인 및 온보딩 전 `mode=NULL` 확정, 나머지 구현 결정안 검토 중**. 이 문서는 `signUp`·`listTerms` 작업의 입력 정책을 한곳에 모은다. 승인된 약관 본문과 버전은 현재 없다는 프로젝트 담당자의 2026-10-13 확인을 반영한다. 이 문서만으로 법적 약관의 승인이나 회원가입 기능의 완료를 주장하지 않는다.

## 이미 정해진 계약

| 항목 | 적용 기준 | 근거 |
| --- | --- | --- |
| 가입 요청 | `email`, `password`, `agreements[]` 필수, `displayName` 선택 | [`SignupRequest`](../api/openapi.yaml) |
| 가입 응답 | 성공 시 HTTP 201 `SessionResponse`; `EMAIL_TAKEN` 409, `TERMS_REQUIRED` 422, 입력 오류 422, 제한 초과 `RATE_LIMITED` 429 | [`signUp`](../api/openapi.yaml) |
| 약관 조회 | `GET /api/v1/auth/terms`는 `items`·`nextCursor`를 반환한다. 승인 본문이 없는 항목의 `body`·`version`은 NULL이고 `bodyAvailable=false`다. | [`TermOut`·`TermsResponse`](../api/openapi.yaml), [ERD v6](../erd/zoop-core-erd-v6.md) |
| 동의 검증 | 요청의 약관 ID·버전·`accepted`를 서버의 현재 유효한 승인 버전과 대조한다. 필수 본문/버전이 없거나 필수 동의가 빠지면 회원 행을 만들지 않는다. | [`SignupRequest`](../api/openapi.yaml), [ERD v6](../erd/zoop-core-erd-v6.md) |
| 저장 | 이메일 가입에는 비밀번호 해시가 필요하다. 회원·약관 동의는 같은 트랜잭션에서 기록한다. 비밀번호 원문·세션 토큰 원문은 저장하지 않는다. | [ERD v6](../erd/zoop-core-erd-v6.md) |

## 확정된 가입 후 동작과 초기 상태

프로젝트 담당자가 2026-10-13 **가입 성공 직후 새 회원 세션을 발급해 바로 로그인**하는 정책을 선택했다. HTTP 201 `SessionResponse`는 방금 발급한 `kind=member` 세션을 나타낸다. 기존 guest 세션을 회원 권한으로 승격하지 않고 새 토큰을 발급한다. 이메일 소유 확인 절차가 필요한지는 별도로 결정해야 하며, 확인 전 이메일을 검증된 소유 주소라고 표시하지 않는다.

프로젝트 담당자는 온보딩 방식이 미선택인 신규 회원의 `mode=NULL` 저장도 선택했다. `completed=false`, `investor=NULL`로 시작하고, 관심 기업과 포트폴리오 연결은 해당 관계 행이 없으면 빈 상태다. `SettingsResponse.mode`는 필드를 항상 포함하되 방식 선택 전에는 JSON `null`을 반환한다.

## 구현 결정안

아래 값은 코드 작성에 사용할 **제안**이다. 명세의 `teamQuestions`를 해결한 팀 결정으로 표시하거나 OpenAPI에 반영하기 전에는 확정값으로 소개하지 않는다.

| 주제 | 결정안 | 확인할 부분 |
| --- | --- | --- |
| 이메일 | 앞뒤 공백 제거 후 서비스 내부 비교키 `email_key`를 소문자로 정규화한다. 최대 254자, 빈 값·기본 이메일 형식 오류는 422. `email`에는 사용자가 입력한 주소를 공백 제거해 보관하고, 중복의 최종 판정은 DB UNIQUE로 한다. | FS002·FS003의 정규화 기준과 일치. Gmail 점·플러스 등을 임의 통합하지 않는다. |
| 표시명 | 생략 시 ERD가 제안한 `회원`을 저장한다. 명시 입력은 앞뒤 공백을 제거하고 빈 문자열을 거절한다. 중복 이름은 허용하고 이메일·실명에서 추정하지 않는다. | 최대 길이와 허용 문자 정책은 UI·팀과 확정해야 한다. |
| 비밀번호 | 단일 인증수단으로 최소 15자, 최소 64자를 허용한다. 문자 종류 혼합 규칙은 두지 않고 Unicode·공백을 허용한다. 앞뒤 공백을 자동 제거하지 않는다. 가입 시 흔한/유출된 비밀번호 차단 목록과 비교한다. 저장에는 개별 salt가 있는 적응형 해시를 사용한다. | 구체 최대 길이, 차단 목록의 소유·갱신 방법, Java 해시 라이브러리와 성능값을 구현 전 확정해야 한다. 프로토타입의 영문+숫자·8자 정책을 그대로 이식하지 않는다. |
| 회원 초기 상태 | `signup_method=email`, `status=active`, `tutorial_completed=false`, `settings_version=1`, `created_at=updated_at=생성시각`을 제안한다. 관심 기업과 보유 기업은 별도 관계/연결 행이 없으면 빈 상태로 저장한다. | `mode=NULL`, `completed=false`, `investor=NULL`은 확정했다. 가명 `id`와 `analytics_key`는 각각 독립적인 암호학적 난수로 발급한다. |
| 가입 직후 인증 | 새 회원 세션과 `zoop_session`을 발급한다. | 위 확정 정책을 따른다. `Secure`·`HttpOnly`·`SameSite`와 Origin 검증은 API 계약을 따른다. |
| 세션 수명·제한 | 서버에서 만료·폐기를 검증하고 `expiresAt`에 실제 만료를 보낸다. 가입 반복 시도는 IP 및 이메일 비교키 기준으로 제한하고 429를 반환한다. | 수명·idle 정책, 운영 임계값, 공유 저장소/원자성 및 프록시의 신뢰 IP 기준은 운영 담당자와 확정한다. 숫자를 API 계약에 임의로 고정하지 않는다. |

비밀번호 길이·복잡도·차단 목록 제안은 [NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html)를 따른다. 해시 구현 시 [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)의 현재 Argon2id 권고값을 출발점으로 성능을 측정한다. 세션 수명은 위험도와 사용성을 함께 정하고 서버가 강제해야 한다([OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)).

### 온보딩 전 `mode` 검토

`mode`는 관심·보유 종목의 **존재 여부**가 아니라 회원이 선택한 온보딩 방식이다. 두 목록은 `watchlist`와 포트폴리오 연결/보유 행으로 따로 표현한다. 따라서 관심·보유 종목이 모두 없는 신규 회원에게 `watchlist`를 저장하면 목록이 비었다는 사실은 보존되지만, 방식을 이미 골랐다는 오해를 만들 수 있다. 기존 프로토타입은 가입 시 `watchlist`를 기본값으로 저장하나 목표 계약의 확정 정책은 아니다.

**확정 정책:** 가입 직후에는 `mode=NULL`, `completed=false`, `investor=NULL`로 두고 관심 목록과 포트폴리오 연결은 빈 상태로 둔다. 온보딩에서 방식을 선택·저장할 때 `mode=assets|watchlist`로 바꾼다. ERD·JPA·`SettingsResponse`를 이에 맞추고, 이미 게시된 Flyway 파일은 수정하지 않고 새 migration에서 `NOT NULL`을 해제한다. 기존 `ck_members_mode`는 PostgreSQL의 CHECK 의미상 NULL을 허용하며 다른 문자열은 계속 거절한다. `SettingsUpdate.mode`의 `null` 또는 생략은 “변경하지 않음”이므로 출력의 미선택 상태와 구분한다.

## 약관 공개 본문과 후속 작업

팀은 2026-10-13 17:00 KST에 약관 정책을 승인했다. [공개용 약관](../legal/README.md)의 `service`와 `privacy` 본문을 버전 `2026-10-13.1`로 등록했으며, 두 항목 모두 필수 동의다. 시행 시각은 2026-10-13 17:00 KST다. 그 전에는 유효한 본문이 없으므로 `listTerms`는 본문 부재를 표시하고 `signUp`은 성공시키지 않는다. 본문 등록만으로 가입 서비스나 탈퇴 삭제가 구현된 것은 아니다.

구현 전 확정이 필요한 사항: **① 이메일 소유 확인 절차, ② 표시명 길이·비밀번호 최대 길이와 차단 목록, ③ 회원 세션 수명과 가입 요청 제한값.** 인증 담당자는 팀 결정이 나면 이 문서의 상태와 원문 결정 출처를 갱신하고 필요한 경우 OpenAPI의 `teamQuestions`·응답 설명을 같은 변경에서 정리한다.
