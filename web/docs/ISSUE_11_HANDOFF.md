# Issue #11 · D-WAT-01 / D-WAT-01b · WBS 6.4.5

2026-10-14 · 박주형 · 구현 및 검증 완료. 사용자 요청으로 PR을 제출하며 머지는 팀장이 담당한다.

## 작업 위치

`C:/Users/user/Downloads/zoop-project/zoop-11-onboarding-watchlist`
브랜치 `feat/11-initial-watchlist`, main 기준 `774f87a`.
기존 zoop-integration의 prototype/web 변경은 수정하지 않았다.

## 구현

- 기업 검색 버튼·Enter, 결과 추가, 고른 종목 칩 해제, 중복 방지. 추천 목록·페이지 더 보기는 제외.
- 0개 안내는 보유 종목 유무에 따라 구분. 마지막 해제 후 검색어 유지.
- 단계 왕복 시 선택 목록·검색어 유지. 미투자 진입이면 /onboarding, 그 외 /onboarding/account로 이전 이동.
- settings/portfolio 조회 실패와 지연 중 완료 차단, 다시 조회. 검색 실패·빈 결과·이전 검색 지연 응답 폐기.
- 저장 중 완료·이전·검색·선택·공통 단계 링크 차단. 실패 시 초안 유지와 다시 저장.
- settings version을 포함해 관심 목록과 completed=true 저장. investor는 초안에 답이 있을 때만 변경하고 tutorialCompleted는 덮어쓰지 않음.
- 보유·관심 모두 0 => /?mode=all, 하나 이상 => /?mode=personal. 설정 mode=assets/watchlist는 지도 모드와 구분.
- 같은 회원의 토큰 갱신은 초안을 유지, 다른 회원은 이전 초안을 재사용하지 않음.

API consumer: GET /api/v1/companies, GET/PUT /api/v1/me/settings, GET /api/v1/portfolio. 정본의 직접 DTO를 사용하고 공통 call()은 변경하지 않았다. 실제 backend 통합은 미검증이며 테스트·브라우저 API 응답은 합성 fixture다.

## main 반영과 충돌 확인

main을 pull하여 #23의 수정 커밋 3614592 및 merge 774f87a를 반영했다. 기존 다른 화면 라우트·/my 보호·DesktopHeader/BottomNav 복원과 관계 고유 집계·이슈 수 5단계 크기 코드를 확인했다.

이전에 가져온 미머지 PR 패치를 소스 ZIP으로 백업한 뒤 역적용하고, Issue #11 파일을 유지한 상태로 fast-forward pull했다. git ls-files --unmerged, 충돌 마커 검색, git diff --check 모두 문제 없음. 업데이트 후 변경 목록에는 #11 작업만 남음. 아래 무스테이징 확인은 PR 제출 전 검증 시점의 기록이다.

## 검증

- 전체 Vitest: 5 files / 34 tests 통과; #11 화면 테스트 15개 포함.
- pnpm 10.34.6 frozen install, lint, format:check, build 통과. 지도 chunk 크기 경고는 남음.
- Chromium: 1280px·390px, 가로 넘침 없음, 검색→추가→저장→개인화 지도 이동, console page error 없음.
- 실제 API 서버·실제 회원 계정·실제 시장 데이터 검증은 하지 않음.

## 이어서 작업

web 폴더에서 `pnpm dev` 실행 후 /onboarding/watchlist 확인. 로그인은 기존 인증 담당 구현에 의존한다. 투자 여부/계좌 화면은 다른 이슈 작업이 main에 반영된 뒤 동선을 통합 검증한다. PR은 main 대상으로 제출한다. 이슈 자동 종료는 병합 시 Closes #11로 처리되며, 머지는 팀장이 담당한다.
