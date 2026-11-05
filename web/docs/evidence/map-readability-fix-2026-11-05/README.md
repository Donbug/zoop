# 지도 문제 1·2·3 수정 증거

## 기준과 데이터

- D-GRP-01/03. main fab64130 + 승인된 PR570 head d7635908의 통합 커밋5586cde2를 수정 전 기준으로 사용.
- 실제 MapPage·G6·기업 패널을 기존 개발용 합성 그래프(기업24·사건43)·합성 기업 응답·비회원 세션으로 실행. 운영 시세·사용자 정보가 아님.
- 모든 전후 쌍은 같은 합성 데이터·뷰포트·테마·선택 과정을 사용.
- 로컬 전용 Vite 서버는 configFile=false, envDir=false이며 .env를 읽지 않음. 저장소 밖 preview helper는 빌드에 포함되지 않음.
- 수정 전 서버는 통합 기준 커밋의 GraphCanvas/graph-geometry/graph-readability/map-appearance-styles 네 파일을 읽으며 다른 입력과 컴포넌트는 수정 후와 같음.

## 이미지

| 확인                                | 수정 전                                                                | 수정 후                                                              |
| ----------------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------- |
| 모바일 라이트 전체 지도             | [before-mobile-light.jpg](before-mobile-light.jpg)                     | [after-mobile-light.jpg](after-mobile-light.jpg)                     |
| 모바일 새로 고침                    | [before-mobile-reload-light.jpg](before-mobile-reload-light.jpg)       | [after-mobile-reload-light.jpg](after-mobile-reload-light.jpg)       |
| 데스크톱 전체 맞춤 후 삼성전자 선택 | [before-desktop-selected-light.jpg](before-desktop-selected-light.jpg) | [after-desktop-selected-light.jpg](after-desktop-selected-light.jpg) |
| 다크 관련 기업 카드                 | [before-desktop-related-dark.jpg](before-desktop-related-dark.jpg)     | [after-desktop-related-dark.jpg](after-desktop-related-dark.jpg)     |

추가 확인:

- [모바일 새로 고침 라이트](after-mobile-reload-light.jpg)
- [모바일 새로 고침 다크](after-mobile-reload-dark.jpg)
- [모바일 다크](after-mobile-dark.jpg)
- [가로 전환](after-landscape-dark.jpg)
- [사건 키보드 선택](after-desktop-event-dark.jpg)

데스크톱 이미지는1440×900, 모바일 이미지는390×843으로 캡처됨(요청 viewport390×844).
가로 전환 이미지는829×383으로 반환됨(요청844×390). 재가공·크기 변경하지 않은 원본임.

## 측정·동작

관련 기업 버튼의 실제 계산 스타일:

- 수정 전: 배경rgb255,255,255 / 기업명250,250,250 / 설명212,212,212.
- 수정 후: 배경rgb38,38,38 / 기업명250,250,250 / 설명212,212,212.
- 기업명 대비1.04:1 →14.50:1, 설명1.48:1 →10.21:1.
- 키보드로 관련 기업 선택 후 aria-pressed=true, 배경rgb54,54,56.
- 모바일 문서 scrollWidth=innerWidth=390. 기존 툴바 내부 가로 스크롤은 이번 범위가 아니므로 유지.
- 새 진입·새로 고침·전체 맞춤·세로/가로 전환·기업/사건/관련 기업 키보드 선택 확인.
- 전체 보기에서 모든 사건 제목을 동시에 읽게 만드는 변경은 아님. 좁은 화면의 불필요한 맞춤 여백과 제목 겹침을 줄이고 원·간선·키보드 목록은 유지.
- reduced-motion은 기존 자동 카메라 테스트로 확인. OS 설정을 직접 변경한 검증은 수행하지 않음.

## 검사

`web/`에서 아래 환경으로 실행:

`COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CI=true HUSKY=0 VITE_GRAPH_DATA_SOURCE=mock`

| 명령                                                 | 결과                                                                                                     |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| corepack pnpm@10.34.6 exec tsc -b                    | PASS                                                                                                     |
| corepack pnpm@10.34.6 lint                           | PASS                                                                                                     |
| corepack pnpm@10.34.6 exec prettier --check .        | PASS(전후 증거 문서 포함)                                                                                |
| corepack pnpm@10.34.6 build                          | PASS, 기존 chunk 크기 경고                                                                               |
| 관련 Vitest 4파일                                    | 151건 PASS                                                                                               |
| corepack pnpm@10.34.6 exec vitest run --maxWorkers=2 | 전체 140파일·1613건 중 1612건 PASS. 실패 1건(MainGraphCompletion, 5초 시간 초과)은 단독 재실행 49건 PASS |

추가 재현: 기존 새로 고침 캡처는 실제로 빈 화면이었다. 최종 검토에서 발견해 보관 이미지를 교체하고, G6 저장 이동량을 배율에 맞는 픽셀로 복원하는 회귀 테스트의 실패/성공 및 라이트·다크 반복 새로 고침을 확인했다. 이미 잘못 저장된 화면 위치는 전체 맞춤1회로 복구 가능.

RED 확인: 테마 카드2건·숨겨진 제목 맞춤1건·선택 이웃 제목 충돌1건 및 노드별 라벨 경계1건.
검사 대상은 실제 코드이며 데이터·HTTP 응답은 합성 fixture임. 원격 CI·배포 결과가 아님.
