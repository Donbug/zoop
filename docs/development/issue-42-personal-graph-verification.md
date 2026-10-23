# #42 FS014 초기 개인화 관계 그래프 검증

> 적용 범위: 프론트 동작·테스트 결과는 해당 구현이 포함된 `82d6236` 기준의 과거 기록이다. 프론트 변경과 테스트는 `c9ee3c0`에서 이 PR 범위에서 제거됐다. 현재 PR은 API 회귀 테스트·HTTP smoke·계약·문서 변경을 포함하며, 이 문서는 현재 head의 프론트 전환 검증 증거가 아니다.

2026-10-22 · 연결 이슈: [#42](https://github.com/Donbug/zoop/issues/42), [#45](https://github.com/Donbug/zoop/issues/45)

## 범위와 화면 추적

| 단계 | 화면 ID | 확인 대상 |
| --- | --- | --- |
| 투자 여부·모의 계좌 | D-ONB-01, D-ONB-02 | 선택 저장, 선택적 모의 계좌 연결 |
| 관심 종목 선택 | D-WAT-01 | 관심 종목 저장 직후 첫 지도 라우팅 |
| 첫 지도 | D-GRP-01, D-GRP-01b | 시장 전체·개인화 그래프, 범위 필터, 빈 결과, 실패·재시도 |
| 모바일 지도 | M-GRP-01 | 기존 지도 캔버스의 빈 결과·실패 상태 회귀 |

시각·이동 기준은 `docs/wireframe/README.md`, `docs/wireframe/manifest.json`의 보드와 D-WAT-01·D-GRP-01·D-GRP-01b 개별 화면, `docs/screen-plan/captures/D-GRP-01*.json`을 확인했다. M-GRP-01은 와이어프레임 manifest에 없으므로 화면 계획과 기존 모바일 지도 테스트를 기준으로 확인했다. 정적 이미지에 없는 오류·로딩·빈 상태는 FS014와 화면 계획을 적용했다.

## 계약 결정

- `GET /api/v1/graph?mode=personal`은 회원의 모의 보유와 관심 종목을 요청 때 읽는다. `personalFilter`가 고른 범위에 기준 기업이 없으면 빈 응답과 `emptyReason=no_personal_stocks`를 반환한다. 다른 범위에 종목이 있는지는 이 값만으로 알 수 없다.
- 프론트 요구사항/이전 구현(`82d6236`): 온보딩에서 둘 다 없으면 `/?mode=all`로 이동한다. 이후 개인화 URL에 직접 들어온 경우 전체 개인화 범위도 비어 있음을 확인한 다음 시장 전체 지도로 전환한다. 보유만 또는 관심만 빈 필터는 유지한다. 이 동작은 현재 PR head에 구현되어 있지 않다.
- 같은 `companies` 카탈로그가 관심 종목 검색·설정 유효성 검사·그래프 기준 기업 조회에 쓰인다. 카탈로그에는 있지만 현재 fixture 스냅샷에 없는 기준 기업은 관계 없는 노드로 유지된다. 관계나 사건을 만들어 내지 않는다.
- 그래프 조회 실패는 오류 응답이다. 빈 그래프로 대체하지 않으며 화면에서 재시도를 제공한다. 개인화 모드에 브리핑 `round`를 보내면 422다.

## 검증 기록

아래 화면 전환 및 웹 테스트 결과는 프론트 구현이 포함된 `82d6236`에서 수행한 이력이며, 현재 PR head에서 재검증한 결과가 아니다.

실제 HTTP 확인은 일회용 PostgreSQL, 로컬 API, 합성 graph fixture에서 수행했다. `api/scripts/initial_personal_graph_smoke.py`는 필수 약관을 조회해 합성 회원을 만들고 아래 경로를 재실행한다. 로그에 쿠키·CSRF 토큰을 출력하지 않는다.

| 경우 | 실제 HTTP 결과 | 화면 검증 |
| --- | --- | --- |
| 보유 O · 관심 O | 200, 보유 우선 기준 기업, 중복 종목 `holding=true`, `watch=true` | D-GRP-01b 첫 지도 테스트 통과 |
| 보유 O · 관심 X | 200, 보유 기준 기업, 관심 표시 없음 | D-GRP-01b 첫 지도 테스트 통과 |
| 보유 X · 관심 O | 200, 저장 직후 관심 기준 기업·표시 반영 | D-GRP-01b 첫 지도 테스트 통과 |
| 보유 X · 관심 X | 개인화 200 `no_personal_stocks`; 시장 전체 200 | 온보딩과 개인화 직접 진입의 D-GRP-01 전환 테스트 통과 |
| 관심 목록 변경·삭제 | 다음 개인화 HTTP 조회에 즉시 반영 | 빈 필터와 전체 종목 부재 구분 테스트 통과 |
| 인증 없음·비회원 세션 | 각각 401·403, 개인화 노드 없음 | API 컨트롤러 테스트 통과 |
| 스냅샷 소스 없음 | 503 `SOURCE_UNAVAILABLE`, 그래프 본문 없음 | D-GRP-01b 조회 실패·재시도 테스트 통과 |

온보딩 프런트 통합 테스트는 D-WAT-01에서 첫 지도까지 네 조합과 D-ONB-01 → D-ONB-02 → D-WAT-01 → D-GRP-01b의 모의 계좌 연결 경로를 검증한다. 가입·로그인·세션 회복은 기존 `web/tests/auth/authJourney.test.tsx` 회귀 테스트로 확인했다. 실제 브라우저와 실제 API를 동시에 실행하는 E2E는 수행하지 않았으며, 프런트 통합 테스트는 API 형식의 합성 응답을 사용한다.

과거 실행 결과 (`82d6236`; 현재 head에서 재실행하지 않음):

- API: `GraphVersionPostgresIntegrationTest.fs014SavedWatchlistAndMockHoldingsAppearInTheNextPersonalRead`, `GraphControllerTest`, `GraphQueryServiceTest` 통과.
- 웹: `initial-personal-graph.test.tsx`, `watchlist.test.tsx`, `investmentChoice.test.tsx`, `virtualAccount.test.tsx`, `MainGraphCompletion.test.tsx`, `GraphCanvas.selection.test.tsx`, `mobile-and-isolated.test.tsx`, `authJourney.test.tsx` 통과.
- `pnpm lint`, `pnpm build`, `make contracts-check`, `git diff --check` 통과.
- 2026-10-22 재확인: 첫 기록 이후 `pnpm lint`가 `MapPage`의 effect 안 동기 `setState`(`react-hooks/set-state-in-effect`)로 실패해, 재시도 상태 초기화를 비동기 콜백과 재시도 버튼으로 옮겼다. 전체 개인화 범위 확인이 실패한 뒤 재시도로 시장 전체 지도에 도달하는 D-GRP-01b 테스트를 추가했다. 최신 `main` 위에서 웹 전체 테스트(69 파일, 640건), `pnpm lint`, `pnpm build`, `make contracts-check`, `git diff --check`가 통과했다. API 테스트는 이 재확인 환경에서 Maven 저장소 접근이 막혀 다시 실행하지 못했다.

재실행 예시(격리된 로컬 API와 fixture가 준비된 경우):

```sh
ZOOP_GRAPH_SMOKE_BASE_URL=http://127.0.0.1:8080 \
ZOOP_GRAPH_SMOKE_ORIGIN=http://localhost:8080 \
python3 api/scripts/initial_personal_graph_smoke.py
```

## 현재 PR 범위와 롤백

현재 PR은 개인화 응답의 API 계약, 백엔드 회귀 테스트, HTTP smoke와 검증 문서 범위다. 프론트 시장 전체 전환 구현·테스트는 포함하지 않는다. API 계약 변경을 되돌릴 때는 `docs/api/openapi.yaml`과 생성 명세를 함께 되돌린다. 과거 `MapPage` 동작과 화면 테스트는 별도 프론트 작업에서 관리한다.
