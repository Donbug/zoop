# Web 개발 진행 기록

이 문서는 `web` 구현 변경을 날짜순으로 누적한다. 완료 표시는 코드 작성만이 아니라 명시된 검증까지 통과한 경우에만 사용한다.

## 2026-10-14 · PR #23 리뷰 반영 · D-GRP-01 / D-GRP-01b

- 화면 추적 ID: `D-GRP-01`(Figma `619:1819`), `D-GRP-01b`(Figma `619:2374`)
- `/stocks`, `/companies/:id`, `/briefing`, `/my`의 기존 화면 라우트와 `/my`의 `ProtectedRoute`를 복원했다.
- 그래프 전용 `ServiceHeader`와 `relationship-map.css`를 `MapPage`로 한정하고, 다른 화면의 `DesktopHeader`·`BottomNav`·공통 레이아웃을 유지했다.
- 동일 사건-기업 쌍에 직접·구조 관계가 함께 있어도 고유 기업 한 곳으로 집계하여 공유 사건과 접힘 배지를 계산한다.
- 기업 노드 크기는 연결된 고유 이슈 수를 `0 / 1 / 2 / 3~4 / 5+`의 5단계로 표시한다. 이 값은 중요도나 인과가 아닌 그래프 활동량이다.
- 현재 단계 경계는 합성 fixture의 `0~6` 분포에 맞춘 검토값이다. 실제 API 데이터 분포가 확보되면 경계를 재검증한다.
- `corepack pnpm test`: 4 files / 19 tests 통과
- `corepack pnpm lint`, `corepack pnpm format:check`, `corepack pnpm build`: 통과. 지도 chunk 크기 경고는 기존과 동일하게 남는다.
- production build에서 그래프 스타일이 `MapPage-*.css`로 분리되고 기존 종목·기업·브리핑·내 종목 페이지 chunk가 생성됨을 확인했다.

## 2026-10-13 · WBS 6.6.21 · D-GRP-01 / D-GRP-01b

- 담당: 김도현
- 범위: `(FE) D-GRP-01·01b 전체·개인화 관계 그래프 화면 및 조회 API 연동`
- 화면 추적 ID: `D-GRP-01`(Figma `619:1819`), `D-GRP-01b`(Figma `619:2374`)
- 확인 자료: `docs/wireframe/README.md`, `docs/wireframe/manifest.json`, 보드 `03-map-relationships-evidence.jpg`, 두 개별 화면 PNG, `docs/api/openapi.yaml`, `docs/erd/zoop-core-erd-v6.md`, 현행 `04-메인그래프-v2.csv`

### 구현

- AntV G6 5.1.1 기반 캔버스에 드래그 이동, 휠/+/- 확대, 전체 맞춤, 노드 선택·포커스를 연결했다.
- Figma의 48px 헤더·툴바, 캔버스, 범례, 타이포그래피를 구현하고 Pretendard Variable, Inter Variable, JetBrains Mono Variable, Instrument Serif를 프로젝트 자산으로 사용했다.
- Figma MCP가 제공한 아이콘·기업 로고를 `public/graph-assets`에 저장했다. 화면계획 설명용 검은 숫자 배지는 제품 UI에서 제외했다.
- `GET /api/v1/graph`의 `GraphResponse` DTO와 요청 URL 어댑터를 만들었다. 개발 환경 기본값은 mock이며 `VITE_GRAPH_DATA_SOURCE=api`에서 실제 조회로 전환한다.
- ERD에 따라 기업 카탈로그·보유·관심은 관계형 저장소 ID를 공유하고, Issue/관계는 Neo4j 외부 ID로 표현했다. `SHARES_ISSUE`는 공통 Issue에서 파생하며 근거 ID를 임의 생성하지 않는다.
- 개인화 전체/보유/관심 필터, 기준 기업 유지, 관계 없음/기준 없음/최초 실패/재조회 실패, 지연 응답 폐기, 세션 교체 시 개인 데이터 제거를 구현했다.
- 전체 모드에는 회원 보유·관심 데이터를 포함하지 않는다. 화면 수치는 Figma 예시 상수가 아니라 현재 응답에서 집계한다.

### 범위 정리

- 지도 페이지에서 사건·기업·연결선 상세 패널, 근거, 경로, 브리핑 회차, 튜토리얼, AI 질의 연결을 제거했다. 이 기능들은 WBS 6.6.21 범위가 아니다.
- 종목·브리핑·내 종목·AI 질의의 이전 임시 구현은 라우트에서 분리했다. 종목·브리핑·내 종목은 공통 헤더만 유지하는 범위 안내 페이지이며 AI 질의는 비활성 상태다.
- 공통 헤더는 Figma `619:1824`를 기준으로 `AppLayout`에 한 번만 배치했다. `/`, `/stocks`, `/briefing`, `/my` 이동 시 헤더의 위치·크기·구조가 동일하다.
- D-GRP-01/01b에 열린 내 종목 사이드바 프레임이 없어 사이드바 본문은 추측 구현하지 않았다. 관련 Figma 프레임이 제공되면 FS026 범위로 이어서 구현한다.

### 검증

- `pnpm test`: 3 files / 15 tests 통과
- `pnpm lint`: 통과
- `pnpm build`: 통과. G6가 포함된 지도 chunk 크기 경고는 남아 있으며 기능 오류는 아니다.
- 브라우저 1280px 검증: 지도 헤더와 `/stocks` 헤더 모두 `(x=0, y=0, width=1280, height=48)`로 동일함을 확인했다.
- 브라우저 조작 검증: 확대 버튼으로 `100% → 120%` 변경, G6 렌더링, 종목 범위 안내 페이지 전환을 확인했다.
