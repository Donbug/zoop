# Figma 공개 읽기 수집 기록

- 수집일: 2026-10-08 KST. 최초 시각 확인: 02:51:48 +0900.
- 프레임 PNG 수집: 2026-10-07T17:59:06.789Z ~ 2026-10-07T18:02:55.897Z (UTC).
- 문서 작성일: 2026-10-08 KST.
- 사용자 지정 출발 URL: https://www.figma.com/design/B1nkTuCLKWMohgXNdEB6un/%EB%8F%88%EB%B2%8C%EB%A0%88-%EC%B5%9C%EC%A2%85-%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8?node-id=620-617&p=f&t=APMusrEH4HtLh3fv-0
- 파일 이름: 돈벌레 최종 프로젝트. 출발 node-id: 620-617. 공개 브라우저에서 출발 페이지는 05 · 출퇴근 브리핑이었다.
- reader의 HTML 메타데이터: og:article:published_time = 2026-09-15 03:31:14 UTC; og:article:modified_time = 2026-10-07 09:01:26 UTC. 파일 전체 메타데이터이며 각 프레임 작성일은 확인되지 않았다.
- 원본 페이지 안내 텍스트의 기준일: 줍 화면계획서 v2.1 · 2026-10-06. 수집일·파일 메타데이터·안내 기준일은 서로 다른 값이다.

## 실제 접근 결과

1. read URL: JavaScript 앱 셸과 메타데이터만 반환했다. 프레임 내용을 reader로 읽었다고 주장하지 않는다.
2. 로그인하지 않은 별도 headless 탭: 공개 캔버스·10개 페이지·레이어 이름을 읽을 수 있었다. 선택 프레임의 공개 node permalink로 매번 이동하면 자동 맞춤 배율로 실제 화면을 확대할 수 있었다. 동일한 전체조망 타일을 반복 수집하지 않았다.
3. 쿠키는 Do not allow cookies를 선택했다. 로그인·Google Continue·Sign up·댓글·편집·Share 제출·유료 호출·인증 API는 사용하지 않았다.
4. 페이지·레이어 navigation으로 DOM에 표시된 node IDs를 수집했다. 설명 프레임 57개는 하나씩 확장해 원문 텍스트 레이어 이름을 저장했다. 앱 UI의 모든 텍스트를 DOM 추출했다고 주장하지 않는다.
5. 화면/그룹 52개 각각의 PNG를 실제 브라우저 screenshot으로 저장했다. 7개 contact JPG는 해당 PNG로 만든 열람용 파생물이다. 개별 PNG가 1차 시각 증거이다. contact sheet의 작은 글자를 원문 판독 근거로 사용하지 않는다.

## 캡처 한계

- viewport 1440×1000 CSS px, deviceScaleFactor 1.25, PNG 1800×1250 px. Figma chrome·선택 외곽선·설명 일부가 함께 보인다. 선택 프레임 맞춤 배율은 PC 대부분 84%, 모바일 복합 그룹 82%였다. 정확한 앱 뷰포트와 다르므로 screenshot 픽셀을 CSS 크기로 단정하지 않는다.
- 공개 정적 렌더이며 prototype interaction·반응형 breakpoint·키보드 순서·hit area·hidden layer·variable·font identity를 검증하지 않았다.
- 6개 모바일 그룹은 현재 캡처에서 휴대폰 상태 1개와 오른쪽 빈 영역이 보인다. 원문 설명의 전/후 쌍이 현재 2개 다 보인다고 주장하지 않는다.
- 레이어 selector click은 인접 행을 선택하는 좌표 불일치가 관찰되어 보고했다. 이후 DOM의 정확한 이름/node를 사용해 읽기 전용 navigation과 설명 펼치기를 수행했고, 실제 node permalink로 캡처했다.
- 원본 개인정보/자격증명 파일과 .env는 읽지 않았다. 프로토타입 실행/로그인·원본 var 변경·서버 시작을 하지 않았다.

## 파일

- figma-public-layers.json: 10개 페이지의 최상위 레이어/node ID와 57개 설명의 원문 텍스트. 원문을 가결정으로 수정하지 않았다.
- captures.json: 52개 PNG의 source permalink, 이름, 시각, 경로.
- coverage.json: 프레임별 정적 확인/동작 미확인, 현재 slide-index의 화면 ID·페이지·라우트 대응. 대응 후보는 확정 매핑과 구분했다.
- frame-<node-id>.png: 실제 선택 프레임별 screenshot.
- contact-1.jpg ~ contact-7.jpg: 검토용 파생 묶음.

권한: 사용자가 지정한 팀 Figma의 문서 근거 수집 범위에서 공개 읽기만 수행했다. 공개 접근 성공은 설계 변경 최종승인이나 배포 허가가 아니다.
