# #94 · D-COM-04 기업 중심 관계 그래프 인계

2026-10-16 · WBS 6.7.11 · FS038 / FS040 / FS044.

## 범위와 기준

최신 main `cb345f7`에서 기존 로컬 #94 변경만 분리했다. 원본 `zoop-94-tailwind`는 보존했다. #93(PR #185) 기업 정보 탭과 #95 차트·시간 버킷 고도화는 포함하지 않는다. D-COM-04는 manifest의 독립 프레임이 아니라 D-COM-01 기업 상세의 오른쪽 관계 그래프 영역이다. board 04와 node 663:13515 개별 화면을 확인했다.

## 동작

- 기업 원·사건 마름모와 실제 노드/연결 수, 선택 상태 및 키보드 노드 목록을 표시한다.
- 50~400% 확대·축소, 전체 보기, 포인터 드래그를 제공한다. 포인터 ID를 추적하고 취소·capture 상실 시 이동을 끝낸다.
- 기업/asOf/공개 버전/관계 단계가 바뀌면 viewport를 초기화한다. 사건 선택만 바뀌면 viewport를 유지한다.
- 사건 선택 시 이전 문서·근거·버킷을 해제하고 탭·기간·기준 시점을 유지한다. 큰 지도 왕복 시 원래 상세 URL을 복원한다.
- getCompanyGraphAsOf 응답의 기업 중심, 단계, asOf, 공개 버전을 검증한다. 동일 시각의 UTC/KST 표기는 허용한다. 요청한 버전이 응답에 없으면 기존 VERSION_UNAVAILABLE 처리를 유지한다.
- 큰 역사 지도도 같은 API 검증을 사용한다. 오류 시 최신 mock이나 다른 시점으로 대체하지 않는다.
- 확인된 실제 근거 경로에 포함된 비파생 `confirmed` 간선만 강조한다. 미확정·파생 관계는 확정 영향 경로로 강조하지 않는다.
- 관계 없음, 부분 실패, 표시 상한, 권한 없음과 일시 장애를 구분한다. 부분 실패는 같은 스냅샷으로 재조회한다.

## 스타일

새 UI는 Tailwind, 기존 zoop 토큰과 `panelStyles.button`을 사용한다. 새 CSS·인라인 스타일·의존성은 없다. SVG viewBox·points·좌표는 그래프 기하 데이터 속성이다.

## 검증과 한계

- 단위·통합: 확대/초기화/선택, 포인터 capture 상실, 잘못된 중심·단계·시점·버전 거부, UTC/KST 동치, 권한, 파생·미확정 간선, 단계 전환 viewport 초기화와 선택 시 viewport 유지.
- Chromium 1440px / 390px: 실제 드래그·확대·초기화·지도 왕복 상세 URL 복원, 가로 넘침·실행 오류 없음 확인. 합성 API fixture만 사용한다.
- 실제 graph producer의 공개/유효 시점·hop·권한을 포함한 E2E는 미검증이다. 기존 지도 번들 크기 및 fixture 정적/동적 import 경고는 유지한다.
- 최종 전체 Vitest 29개 파일 / 272개 테스트 통과(133.28초). ESLint, 테스트 TypeScript, 전체 web Prettier, TypeScript/Vite build 및 git diff --check 통과.

PR 브랜치 `feat/94-company-graph-review`. 병합은 팀장 담당이다.
