# F8 직접 진입 글꼴 검증

작업 4는 #394·#415가 병합된 main `4f7934b5`와 통합했습니다. 변경은 index.css의 공통 font import·body 역할 토큰과 service-shell.css의 중복 import 제거입니다. 기존 글꼴·토큰·레이아웃은 추가하거나 바꾸지 않습니다. #415의 모션 토큰·동작 줄이기 규칙을 유지합니다.

2026-10-29 로컬 Chrome에서 document.fonts와 DevTools CSS.getPlatformFontsForNode를 확인했습니다. `measurements.json`의 platformFonts는 실제 렌더링 글꼴과 glyphCount를 기록합니다. document.fonts에 등록돼도 쓰지 않는 언어 subset은 unloaded일 수 있습니다.

| 직접 진입     | 폭             | 실제 사용 글꼴                             |
| ------------- | -------------- | ------------------------------------------ |
| 관리자 로그인 | 1440, 다크 390 | h1 Pretendard Variable (custom, 5 glyphs)  |
| 404           | 390            | h1 Pretendard Variable (custom, 13 glyphs) |
| 로그인        | 1440           | h1 Pretendard Variable, 로고 Inter         |
| 회원가입      | 1440           | h1 Pretendard Variable, 로고 Inter         |
| 지도          | 1440           | 로고 Inter, 본문 기존 Pretendard 역할      |
| 기업 상세     | 1440           | h1 Pretendard Variable, 로고 Inter         |

body는 모든 화면에서 `"Pretendard Variable", Pretendard, sans-serif`입니다. 서비스 화면의 기존 `.service-surface`도 이 이름을 사용하므로 본문 역할을 유지합니다. `.font-inter`는 기존 Inter Variable face(플랫폼 이름 Inter)를 사용합니다. SOURCE/AS OF mono 설정은 수정하지 않습니다.

관리자 로그인(라이트·다크), 404, 로그인, 회원가입은 main `4f7934b5` 통합본에서 다시 촬영했습니다. 지도·기업 상세 이미지는 앞서 #394 `71fb8b71` 기반에서 확인한 동일 글꼴 수정의 기록입니다. 두 서비스 화면의 명시적인 `.service-surface` 글꼴 역할은 그대로입니다. App/경로 변경은 PR에 포함하지 않습니다.

| 수정 전                                      | 수정 후                                                                          |
| -------------------------------------------- | -------------------------------------------------------------------------------- |
| [관리자 로그인](before-admin-login-1440.jpg) | [관리자 로그인 1440](admin-login-1440.png), [다크 390](admin-login-dark-390.png) |
| [404](before-404-390.jpg)                    | [main 통합 404 390](404-390.png)                                                 |

추가 화면: [로그인](login-1440.png), [회원가입](signup-1440.png), [지도](map-1440.png), [기업 상세](company-1440.png).

빌드 산출물의 woff/woff2 17개는 SHA-256도 17개로 중복 파일이 없습니다. Pretendard Variable 1개, Inter 언어별 subset 7개이며 나머지는 기존 지도 글꼴입니다. 새 글꼴·의존성은 추가하지 않았습니다.

단위 테스트로 글꼴 로딩을 흉내 내지 않고 실제 브라우저와 빌드 파일을 검사했습니다. 화면은 로컬 테스트용이며 지도·계좌는 합성 fixture입니다. 인증 값·개인 계좌·운영 로그를 포함하지 않습니다.

PR의 대상은 main입니다. 기존 #394 기반 검증에서 발생했던 인증 테스트 시간 초과는 main 통합 후 두 파일 49건 전체 재실행에서 통과했습니다. 단위 테스트로 글꼴 로딩을 흉내 내거나 테스트 타임아웃을 늘리지 않았습니다.
