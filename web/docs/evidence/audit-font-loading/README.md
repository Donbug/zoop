# F8 직접 진입 글꼴 검증

작업 4는 사용자 지정에 따라 #394 최신 head `5a522cfe`를 기반으로 합니다. 변경은 index.css의 공통 font import·body 역할 토큰과 service-shell.css의 중복 import 제거입니다. 기존 글꼴·토큰·레이아웃은 추가하거나 바꾸지 않습니다.

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

#394 자체는 아직 404를 포함하지 않고 없는 주소를 지도로 보냅니다. 404 이미지는 main `86c8f530`에 동일한 두 CSS 수정만 적용한 별도 임시 체크아웃에서 촬영했습니다. App/경로 코드는 PR에 가져오지 않았습니다. 나머지 화면은 #394 기반이며, 이후 최신 head 변경은 브리핑 파일에만 있습니다.

| 수정 전                                      | 수정 후                                                                          |
| -------------------------------------------- | -------------------------------------------------------------------------------- |
| [관리자 로그인](before-admin-login-1440.jpg) | [관리자 로그인 1440](admin-login-1440.png), [다크 390](admin-login-dark-390.png) |
| [404](before-404-390.jpg)                    | [main 통합 404 390](404-390.png)                                                 |

추가 화면: [로그인](login-1440.png), [회원가입](signup-1440.png), [지도](map-1440.png), [기업 상세](company-1440.png).

빌드 산출물의 woff/woff2 17개는 SHA-256도 17개로 중복 파일이 없습니다. Pretendard Variable 1개, Inter 언어별 subset 7개이며 나머지는 기존 지도 글꼴입니다. 새 글꼴·의존성은 추가하지 않았습니다.

단위 테스트로 글꼴 로딩을 흉내 내지 않고 실제 브라우저와 빌드 파일을 검사했습니다. 화면은 로컬 테스트용이며 지도·계좌는 합성 fixture입니다. 인증 값·개인 계좌·운영 로그를 포함하지 않습니다.

이 PR은 #394가 main에 병합된 뒤 base를 main으로 바꾸고 통합 검증해야 합니다. #394 브랜치로 병합하지 않습니다.
