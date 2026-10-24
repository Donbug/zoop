# PR #327 · main 통합

- 화면: D-GRP-01/01b, D-GRP-03. 기준 main 40f6758b(#321 및 #312 포함), 기존 #327 head 668764e2.
- 기존 Downloads 작업 사본은 수정하지 않고 최신 origin/main에서 fix/map327-main-sync를 만든 뒤 기존 #327을 병합했다. 원격 PR의 base를 main으로 바꾸고 기존 head 브랜치를 fast-forward로 업데이트한다.
- graph-model, MapPage, graph-appearance 시험 충돌을 해결했다. main의 묶음 여백 압축, 일반선/선택선 구분, 배치 버전 3, 시세/다크/아이콘·출처 보정을 유지한다.
- 중복 readableLabels 보정은 복원하지 않는다. 이름표는 main의 graph-readability(기본 화면 13px, 충돌 숨김) 한 경로만 사용한다.
- 선택 기업 강조가 13px 보정에 묻히는 회귀를 발견했다. selected 최소 16px, 다른 이름표 최소 13px로 구분하고 맞춤 footprint에도 같은 함수를 사용한다. 선택 기업의 원래 큰 글자·800 굵기·잉크색과 G6 선택 상태를 유지한다.
- 노드/연결 위에서 끌면 drag-canvas가 지도만 이동한다. 4px 넘게 끈 직후 node/edge/canvas 클릭은 무시하고 다음 정상 클릭은 허용한다. 노드 좌표 변경/저장은 추가하지 않는다.
- 아래 중앙 선택 상태는 sr-only role=status로 남기고 시각 표시는 상세에서 제공한다. 사이드바 버튼은 보유 종목, 지도 모드는 내 종목으로 구분한다.
- 튜토리얼 흐름·데이터·계약은 변경하지 않는다. #330의 추가 전역 글자/로고 변경이나 #319 상세 패널 기능은 가져오지 않는다. #330의 graph-model/appearance/MapPage/사이드바는 파일이 겹치므로 나중에 통합 검사가 필요하다.

## 검증

- 선택 강조 회귀는 수정 전 0.1/0.37/0.53 배율에서 3개 실패했다. 적용 후 graph-appearance/geometry/readability/GraphCanvas.selection/holdings-sidebar 5개 파일 74개 통과.
- 전체 필수 검사 결과는 PR Evidence에 기록한다. HTTP·G6/matchMedia 대체 입력은 운영 API나 실제 휴대전화·보조 기술 검증과 다르다.
- 참고 프로토타입: prototype/web/src/features/graph-explorer.tsx. main의 G6 및 상태/경로/계약을 유지하며 새로운 prototype runtime import·의존성·에셋은 추가하지 않았다.

- 실제 G6 브라우저(1280×720, 합성 지도/게스트): 선택한 삼성전자 원 위 좌표 드래그로 이웃 노드들이 함께 이동하며 삼성전자 선택이 유지됐다. 이어 SK하이닉스 정상 클릭으로 상세·선택 이름이 SK하이닉스로 바뀌는 것을 확인했다. 물리 마우스·실기기 터치 검증은 아니다. before-node-pan.png / after-node-pan.png에 전후를 보관했다.

- 최종 필수 검사: 타입·lint·prettier·build 통과. 기존 관리자 Fast Refresh 경고 2건 및 번들/fixture import 경고는 유지됐다. 전체 Vitest 82개 파일 795개 통과(264.00초), --maxWorkers=2 --testTimeout=15000 사용(설정 파일 변경 없음).
