# 브리핑 시각 정리 증거 (2026-11-05)

- 소스: `work/zoop-briefing-visual-hierarchy`, branch `fix/web-briefing-visual-hierarchy`.
- 기준: origin/main `10d6e9d4`. 비교 서버의 브리핑 components/pages 트리는 해당 main과 동일함을 Git tree hash로 확인.
- 실제 BriefingPage와 기존 morningBriefing 테스트 fixture에서 파생한 합성 HTTP 응답을 사용. 제목·요약·출처 및 화면 데이터 상태에 합성/시뮬레이션 표시. 운영 발행 데이터가 아님.
- Impeccable 공식 문서의 원칙을 수동 적용. CLI/플러그인 설치·자동 디자인 점수 산출 없음.

## 화면

- before/after-1440-full-light.jpg, before/after-1440-full-dark.jpg: 1440×900 전체 보기.
- before/after-390-full-light.jpg, before/after-390-full-dark.jpg: 390×844 전체 보기.
- before/after-1440-compact-light.jpg: 기본 간단히 읽기 전후.
- before/after-390-compact-light.jpg: 기본 간단히 읽기 모바일 전후.
- after-390-compact-dark.jpg: 간단히 읽기 모바일 다크.
- after-390-failed-light.jpg, after-390-failed-expanded-light.jpg: 생성 실패 및 발행 정보 펼침.

파일 이름은 요청한 뷰포트 폭을 뜻합니다. 캡처 API가 반환한 원본 이미지 크기는
데스크톱 1425×891, 모바일 정상 발행본 375×811, 실패 상태 390×843입니다.
전후 이미지는 같은 캡처 크기로 비교했습니다. 모바일 이미지를 데스크톱으로
중복 저장한 파일은 증거에서 제외했습니다.

## 실제 브라우저 확인

- 간단히/전체 보기 전환 후 쿼리 및 aria-pressed 유지.
- 이슈 summary에서 Enter로 열기/닫기 후 summary 포커스 유지.
- 퇴근 전환 시 edition=evening과 퇴근 브리핑 제목·회차 지도 링크 반영.
- 비회원 개인화 기준 선택 시 로그인 안내 유지.
- 390px: innerWidth=390, document scrollWidth=375, 가로 넘침 없음.
- 라이트·다크 및 생성 실패 안내 확인. 운영 회원 데이터나 실제 인증 사용 없음.

## 재현

`preview-server.mjs`는 저장소 외부의 로컬 검증 도구이며 빌드에 포함되지 않음.
현재 수정본: `node outputs/impeccable-briefing-2026-11-05/preview-server.mjs` (15782).
실패 상태: 같은 명령에 `--failed` (15783).
기존 코드 비교: `--baseline` (15784; 기준 worktree 경로가 helper 안에 고정됨).
Vite configFile/envDir=false로 .env를 읽지 않음. 서버 종료 후 포트 재사용 가능.

단위 테스트에서 jsdom의 native summary Enter 동작을 억지로 흉내 내기 위해 제품에 핸들러를 추가하지 않음. 단위 테스트는 클릭·DOM 구조, 실제 브라우저는 Enter와 포커스를 분담해 확인.

## 검사 결과

- tsc -b / lint / prettier --check . / build / git diff --check PASS.
- 브리핑 관련 101건 PASS.
- 전체 Vitest: 1573/1575 PASS, 139/141파일 PASS. 내 종목 회원 전환·소셜 로그인 URL 테스트 각1건 실패.
- 실패 파일 단일 워커 재검사:40/41 PASS(내 종목17/17 PASS). 남은 인증 테스트 한 건을 이름 필터로 분리하면 현재 수정본과 비교 코드에서 각각1/1 PASS. 전체 일괄 통과와 구분해서 해석해야 함.
- 이 검사 중 다른 작업의 무거운 테스트도 실행 중이었음. 실행 부하를 실패 원인으로 확정하지 않음. 인증·종목 소스/테스트는 수정하지 않았음.
- 세부 로그와 경로: root의 RESUME-briefing-visual-hierarchy-2026-11-05.md.
