# 줍(Zoop) 그래프 시각화 레퍼런스 — 디자인 언어·상호작용 패턴 카탈로그

| 항목 | 내용 |
|:--|:--|
| 작성일 | 2026-09-30 |
| 목적 | 그래프 중심 화면(줍 v3)의 **다음 개선 방향 후보**를 고르기 위한 레퍼런스 1차 조사. 사용자가 직접 훑고 방향을 고를 수 있도록 "가져올 요소 / 맞지 않는 점" 중심으로 정리 |
| 범위 | (1) 그래프 UX 디자인 가이드·도구 공식 문서 (2) 노드·간선 시각 언어 (3) 탐색 상호작용 (4) 금융·뉴스 맥락 패턴 (5) 모바일 (6) Cytoscape.js 구현 가능성 |
| 연계 | `docs/design/v3/` 캡처, `prototype/web/src/components/domain/graph-canvas.tsx`(fcose+dagre, LOD, 이웃 강조, 더블탭 확대), `prototype/web/src/lib/graph-visuals.ts`(기업 로고 글리프/사건 아이콘) |
| 중복 회피 | `docs/research/design-ux-research.md` §4(Bloom 씬 상호작용, Kumu focus, 에고네트워크, 노드 예산, 모바일 조작, 접근성, 라이브러리 비교)와 `tds-seed-reference.md`의 일반론은 **반복하지 않는다.** 이 문서는 "패턴 카탈로그 + 구현 가능성 + 신규 레퍼런스"에 집중한다 |
| 표기 | 사실(출처 확인·URL 병기) / `[추론]`(원문에 없는 해석) / `[미확인]`(확인 실패) |

## 0. 방법과 한계

- **방법**: 1차 출처(제품 공식 문서·공식 데모·공식 블로그·논문)만 근거로 사용. 페이지를 직접 열람한 뒤 인용했고, 스니펫만 본 것은 근거로 쓰지 않았다.
- **한계 1 — 캡처**: 이 조사 세션에는 브라우저/스크린샷 도구가 없어 PNG를 직접 만들지 못했다. 본문에는 저장 예정 상대경로 `img/pattern-*.png`를 표기했고, 문서 끝 `## 캡처 대상` 표에 **Main이 열어 저장할 공개 URL·화면 부분**을 정리했다. 공식 이미지 URL은 각 항목에 병기했다.
- **한계 2 — 문서 렌더링**: AntV G6 문서 사이트(g6.antv.antgroup.com)는 클라이언트 렌더링이라 텍스트 추출이 안 되는 페이지가 있다. 이 경우 같은 내용의 **GitHub 원문(v5 브랜치 `packages/site/docs/**/*.en.md`)** 을 근거로 쓰고 함께 링크했다.
- **한계 3 — 접속 실패**: `docs.graphistry.com`은 TLS 인증서 오류(`ERR_TLS_CERT_ALTNAME_INVALID`)로 실패 → 공식 **UI Guide PDF**(hub.graphistry.com)로 대체. NVL 문서의 "Examples" 링크(`/docs/api/nvl/current/examples.html`)는 **404**였다.
- **한계 4 — 시점**: 라이브러리 버전은 조회 시점 기준(G6 v5, Cytoscape.js master, Ogma latest, yFiles for HTML 데모 현행판).

---

## 1. 디자인 가이드·레퍼런스 지도

각 항목: 무엇인지 → 볼 수 있는 링크 → **줍에 가져올 요소** → 맞지 않는 점.

### 1.1 Cambridge Intelligence — 그래프 UX 원칙 시리즈 ★

- **무엇**: KeyLines/ReGraph(상용 SDK) 제작사의 공개 디자인 가이드. ① UX 총론 ② hairball ③ snowstorm ④ starburst 4부작 + Figma Design Kit + GraphRAG 시각화 실험글.
- **링크**: [UX 가이드(2025)](https://cambridge-intelligence.com/blog/designing-intuitive-data-experiences-with-graph-visualizations/) · [hairball](https://cambridge-intelligence.com/blog/hairball-effect-in-graph-visualization/) · [starburst](https://cambridge-intelligence.com/blog/starburst-effect-in-graph-visualization/) · [Figma Design Kit](https://cambridge-intelligence.com/developers/figma-design-kit/) · [GraphRAG 실험(2026)](https://cambridge-intelligence.com/blog/5-ways-graph-visualization-enhances-graphrag/)
- **가져올 요소**
  - **와이어프레임 vs 스타일링 비교**: 같은 네트워크를 무스타일로 그리면 "읽을 수 없다"는 것을 나란히 보여준다 — 줍의 LOD/범례 설계 근거로 유용([UX 가이드 이미지 `wireframe-700x383-1.png`](https://cambridge-intelligence.com/wp-content/uploads/2026/04/wireframe-700x383-1.png)).
  - **색 규칙**: "인터랙션·중요 상태 강조색은 흑/백을 아껴 쓰라", "신호등 색(빨·초·노·주)은 성과/위험 의미를 함축하므로 중립 데이터엔 파랑·분홍·보라", "색만으로 의미 전달 금지, 그레이스케일에서도 읽혀야 함", "범례 배경색은 그래프 배경과 같게" — 줍의 사건=범주색/기업=상징색 구조에 그대로 적용 가능.
  - **과밀 대응 3종(hairball/snowstorm/starburst)의 처방**: hairball은 **데이터 리모델링**(사람만 노드로, 경로 기반으로 엣지 연결, betweenness로 크기), snowstorm(고립·저연결)은 **데이터 보강/그룹핑**, starburst(허브 폭발)는 ① 확장 개수 제한 시 "7329개를 가져옵니다 — 계속할까요?"처럼 **정직하게 고지** ② 타입별 필터 확장 ③ 백엔드 centrality로 우선순위 ④ **리프 노드를 콤보로 묶기** ⑤ organic/structural/sequential + **스태킹(리프를 격자로 정렬)** 레이아웃.
  - **GraphRAG 실험의 "설명 가능한 시각화"**: 답변 근거가 되는 사실을 그래프에서 강조하고, **주석(annotation)과 내러티브 챕터를 순차 애니메이션(diffing)으로 넘겨** "왜 이런 답이 나왔는지"를 설명한다. 노드 클릭 → 원문(Wikipedia) 데이터로 이동하는 연결도 구현.
- **맞지 않는 점**: 상용 SDK 기능(콤보, 구조적 레이아웃, 애니메이션 diffing)은 문서만 공개되고 **체험 데모는 트라이얼 로그인 필요** — 줍은 Cytoscape.js로 같은 원리를 재구현해야 하고, 제품 캡처를 근거로 쓸 수 없다(캡처 대상에서 제외).

![CI UX 가이드 캡처](img/pattern-ci-ux-guide.png)
![CI starburst 캡처](img/pattern-ci-starburst.png)

### 1.2 AntV G6 v5 — 그래프 엔진 + 디자인 자산 ★

- **무엇**: Ant Group의 오픈소스(MIT) 그래프 엔진. **2종 테마(light/dark) + 20여 개 팔레트**, 노드/엣지/콤보 상태(state), 애니메이션, 플러그인 17종, 레이아웃 19종, Canvas/SVG/WebGL 렌더링, React 노드.
- **링크**: [v5 README](https://github.com/antvis/G6/blob/v5/README.md) · [문서 소스(영문)](https://github.com/antvis/G6/tree/v5/packages/site/docs/manual) · [예제 갤러리](https://g6.antv.antgroup.com/en/examples)
- **가져올 요소**: §2~§3 카탈로그 대부분의 **"이미 만들어진 문법"** — 뱃지, 도넛 노드, 콤보, 헐/버블셋, 미니맵, 타임바, 엣지 번들링, 팔레트 매핑(범주형 `palette: {type:'group', field:'category'}`). 디자인 토큰 관점에서 "라이트/다크 테마 = 노드·엣지·캔버스 스타일의 부분집합"이라는 정의도 참고([`manual/theme/custom-theme`](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/theme/custom-theme.en.md)).
- **맞지 않는 점**: 줍은 Cytoscape.js를 이미 쓰고 있고, G6로 가면 성능상 이점이 거의 없는 34~수백 노드 규모에서 학습 비용·마이그레이션 비용만 발생한다. G6는 목표 화면을 그릴 때의 **"정답지(스타일 스펙)"** 로만 쓰는 것이 합리적이다. `[추론]`

> 도넛 노드 문서 페이지는 데모가 작게 렌더돼 캡처하지 않았다. 원문: [Donut node](https://g6.antv.antgroup.com/en/manual/element/node/donut)
![G6 타임바 캡처](img/pattern-g6-timebar.png)

### 1.3 yWorks yFiles — "상용 데모가 곧 패턴 사전" ★

- **무엇**: 다이어그램 SDK yFiles for HTML의 **공개 데모 모음**(로그인 불요). 그래프·시간·지도·공급망·사기탐지 데모가 각각 하나의 UX 교과서다.
- **링크**: [데모 목록](https://www.yfiles.com/demos) · [Interactive Knowledge Graph](https://www.yfiles.com/demos/showcase/knowledge-graphs) · [Event Timeline](https://www.yfiles.com/demos/showcase/event-timeline) · [Fraud Detection](https://www.yfiles.com/demos/showcase/frauddetection) · [Large Graphs](https://www.yfiles.com/demos/showcase/large-graphs) · [Sankey](https://www.yworks.com/pages/interactive-sankey-diagram-visualization)
- **가져올 요소**
  - **지식 그래프 데모**: 트리플(주어-술어-목적어) 기반 **온톨로지 뷰 필터**(엣지 클릭 → 그 술어에 맞는 것만 표시/페이드), **문제 감지 패널**(중복 노드·잘못 연결된 엣지·**고립 노드**를 찾아 "제거/병합/재연결" 자동 수정), Louvain 클러스터 색 + PageRank 크기, **비콘 애니메이션으로 문제 요소 전체 스포트라이트**, 더블클릭 → **이웃 뷰(neighborhood view)**, 'Group By' 드롭다운으로 레이아웃 전환.
  - **사기 탐지 데모**: 하단 **타임라인 컴포넌트**(생성/삭제 이벤트 수를 막대로), **기간 사각형 드래그 선택**, **스크롤로 일/월/년 3단 상세 전환**, **재생 버튼**, 우측 **검사(inspection) 패널**, 사기 링 하이라이트, WebGL 렌더링.
  - **이벤트 타임라인 데모**: 노드=가로 레인, 엣지=**발생 시각을 x좌표로 갖는 수직선**; 줌아웃하면 엣지가 **집계**되고, 같은 시각의 엣지는 **하이퍼엣지**로 묶여 클릭 시 상세로 확장; 노드 그룹 클릭으로 접기/펴기.
- **맞지 않는 점**: 상용 SDK 데모라 **코드 재사용 불가**(개념만 차용). WebGL/비콘 등 일부 기능은 브라우저 제약 안내가 붙는다(데모 문서에 "WebGL browsers only" 표기).

![yFiles 지식그래프 캡처](img/pattern-yworks-knowledge-graph.png)
![yFiles 이벤트 타임라인 캡처](img/pattern-yworks-event-timeline.png)

### 1.4 Neo4j — NVL / Bloom / Browser GraSS

- **무엇**: 그래프 DB 제작사의 **시각화 라이브러리(NVL, TypeScript)와 제품 UI 규약**.
- **링크**: [NVL Base library](https://neo4j.com/docs/nvl/current/base-library) · [NVL Node 인터페이스](https://neo4j.com/docs/api/nvl/current/interfaces/_neo4j_nvl_base.Node.html) · [Bloom Perspectives](https://neo4j.com/docs/bloom-user-guide/current/bloom-perspectives/bloom-perspectives/) · [Browser GraSS 스타일시트](https://github.com/neo4j/neo4j-browser/blob/master/docs/modules/ROOT/pages/operations/browser-styling.adoc)
- **가져올 요소**
  - **NVL 노드 속성**: `caption/captions`(스타일 포함 다중 캡션), `icon`, **`overlayIcon`(위치 %·크기 %로 노드 위 어디든 — 사실상 뱃지)**, `html`(노드 위 DOM), 상태 플래그 `activated/disabled/hovered/selected/pinned`. 옵션에 **미니맵 컨테이너**와 렌더러 선택이 있다. 캡션은 **canvas 렌더러에서만** 보인다는 제약도 명시.
  - **GraSS**: `node { }`, `node.Person { caption: "{name}" }`처럼 **CSS 유사 스타일시트**로 노드/관계 유형별 채움색·테두리색·**라벨 텍스트색(`text-color-internal`/`text-color-external`)**·캡션을 선언하고 파일로 내보내기/가져오기. 배경과 무관하게 **색 역할을 분리해 선언**하는 구조가 줍의 "기업 상징색/사건 범주색" 규칙을 데이터 주도 스타일시트로 승격시키는 참고 모델.
  - **Perspectives**: 그래프의 "업무 관점(business view)"을 정의·저장·공유하고 **역할 기반 접근 제어**까지 붙이는 개념.
- **맞지 않는 점**: NVL은 캔버스 렌더러 한정 캡션 등 제약이 있고, Bloom/Browser는 Neo4j 제품 전용 UI다(줍은 재사용 불가, 개념만). NVL 예제/데모 페이지는 **404**[미확인].

### 1.5 Graphistry — 대규모 GPU 그래프 + 툴바 설계

- **무엇**: GPU 기반 그래프 분석 제품. 공식 **UI Guide PDF**(2017)에 툴바·필터·클러스터링·격리 노드 정리 규약이 정리돼 있다.
- **링크**: [Graphistry UI Guide PDF](https://hub.graphistry.com/static/docs/ui/graphistry-ui-guide.pdf) · [GPU 제품 페이지](https://www.graphistry.com/gpu)
- **가져올 요소**
  - **툴바를 4계열로 분류**: 그래프 도구 / 선택 도구 / 질의(필터·제외) / 검사(데이터 패널·히스토그램) + 워크북. 줍의 그래프 상단 컨트롤을 묶는 정보구조로 참고.
  - **Scene Settings**: 노드/엣지 스케일, 투명도, **엣지 화살표 표시 토글**, 배경색, **Prune Isolated Nodes(차수 0 노드 일괄 제외)**.
  - **히스토그램 + 데이터 브러시**: 속성 분포를 히스토그램으로 만들고 구간을 칠해 그래프를 필터링, 제외(exclusion)는 별도 패널로 관리.
- **맞지 않는 점**: 2017년 문서라 "선택·이동" 중심의 편집 워크플로가 섞여 있고, 색·타이포 디테일은 없다. 제품은 로그인 필요(캡처 제외, PDF만 캡처).

### 1.6 Tom Sawyer Software — 패널·LOD·툴바의 "완성형 체크리스트"

- **무엇**: Perspectives(상용 그래프 앱 개발 플랫폼)의 공개 기능 문서.
- **링크**: [Graph Visualization 페이지](https://www.tomsawyer.com/graph-visualization)
- **가져올 요소**: **레벨 오브 디테일 UI**(확대/축소에 따라 노드가 보여주는 정보가 달라짐), **돋보기 도구**(스페이스바로 부분 확대), **Overview window**(미니맵), HTML 툴팁, **invokable view**(드로잉·인스펙터·테이블·트리·**타임라인**·지도·차트를 다이얼로그로 띄우는 패널 구성), 툴바 항목 목록(선택/팬/링크 탐색/개요/줌/돋보기/레이아웃/분석), **레이아웃 전환 애니메이션(멘탈 맵 보존)**, 데이터 기반 UI 표현식(위치별 색·부하별 엣지 굵기).
- **맞지 않는 점**: 제품 스크린샷 위주이고 라이브 데모 없음. 컴포넌트 명세는 판매 문서 수준.

### 1.7 Ogma (Linkurious) — 240+ 공개 예제와 테마 프리셋 ★

- **무엇**: JavaScript 그래프 라이브러리. **모든 예제가 문서 페이지에서 바로 실행**되고, 공식 테마/팔레트 저장소가 공개돼 있다.
- **링크**: [예제 인덱스](https://doc.linkurious.com/ogma/latest/examples/) · [스타일 규칙(1차 규칙/맵/슬라이스)](https://doc.linkurious.com/ogma/latest/tutorials/getting-started/design.html) · [EdgeAttributes](https://doc.linkurious.com/ogma/latest/api/types/edgeattributes.html) · [ogma-styles(테마·팔레트)](https://github.com/Linkurious/ogma-styles)
- **가져올 요소**
  - **스타일 3계층**: 전역 **규칙(rules)** → 개별 요소 스타일 → **테마** 프리셋. 규칙에 `map`(범주 매핑; **배열 값이면 노드가 파이차트로 분할**)·`slices`(수치 구간 매핑)를 제공.
  - **배지(최대 4개, 4개 코너)**, **halo/outline/pulse**, **텍스트 `minVisibleSize`(확대 수준별 자동 숨김 LOD)**, 엣지 텍스트 위치(`centered|shifted`, source/target 별도), `scalingMethod: fixed|scaled`(줌에 따라 크기 고정/확대), 레이어 z-index(-1~3).
  - **다크 테마 프리셋 "Midsummer night"** + Paul Tol/Wong 색각 안전 팔레트 세트.
  - 예제 목록에서 줍에 직접 대응하는 것: **AML 데모**(노드/엣지 그룹핑으로 패턴 단순화), **Fraud**, **Supply chain**, **Cyber security log analysis**(이벤트/기간 필터), **Versioned graph**(버전별 레이어), **Identity card nodes**(HTML 카드형 노드), **Cluster annotation**(클러스터 배경 + **도넛 차트 오버레이**), **Accessibility**(키보드+스크린리더), **커뮤니티 검출(Leiden)**.
- **맞지 않는 점**: 상용(오픈소스 아님). DOM 레이어·플러그인 기반 기능은 Cytoscape.js에서 같은 결과를 내려면 커스텀 코드가 필요(§6 표).

![Ogma 배지 캡처](img/pattern-ogma-badge.png)
![Ogma 다크 테마 캡처](img/pattern-ogma-theme-dark.png)

### 1.8 Cosmograph / Gephi Lite / Retina — 브라우저에서 바로 보는 공개 앱

- **Cosmograph**: GPU force layout 엔진 기반 공개 앱·JS/React 라이브러리. 앱 문서에 "**수십만 노드·엣지를 노트북에서**"라고 명시. [앱](https://cosmograph.app/run) · [일반 문서](https://cosmograph.app/docs-general) · [라이브러리](https://next.cosmograph.app/library) · 3D force/카메라 투어 예제: [dev 갤러리](https://cosmograph.app/dev/) → **가져올 요소**: 수백 노드 규모에서는 성능 이점이 없으므로 `[추론]` "미래 대비 화면(수천 노드 뷰)"의 후보로만 기록.
- **Gephi Lite**: GPL-3.0 오픈소스 웹 앱(서버 없음, 데이터는 로컬; GitHub Gist 저장/불러오기; GEXF/GraphML/JSON). **모바일·태블릿 지원을 제품 문서에서 명시**(터치·멀티터치, 반응형 UI), 외관 패널(색·크기·캡션을 데이터 속성에 매핑), 데이터 테이블, iframe 임베드 + JS 드라이버로 외부 제어. 논문: Digital Humanities 2025. [제품 페이지](https://gephi.org/lite) · [앱](https://lite.gephi.org/) · [문서](https://docs.gephi.org/lite/user-manual/) → **가져올 요소**: "**동적 캡션**"(색·크기·캡션을 데이터로 매핑)과 모바일 대응 서술, 그리고 **외부 앱이 그래프 뷰를 제어하는 드라이버** 패턴(줍의 상세 패널↔그래프 연동과 동형).
- **Retina**: OuestWare(같은 팀)의 **서버 없는 공유용 네트워크 뷰어**(GEXF/GraphML). Gephi Lite에서 "Retina로 열기"가 연결된다. [GitLab](https://gitlab.com/ouestware/retina) · [앱](https://ouestware.gitlab.io/retina/) → **가져올 요소**: "**뷰를 파일/URL로 공유**"라는 제품 정의(줍의 '내 지도 공유' 후보). 상세 기능 문서는 [미확인](README 수준만 확인).

---

## 2. 노드·간선 시각 언어

### 2.1 노드

| 패턴 | 실제 제품 예 | 줍 적용 메모 |
|:--|:--|:--|
| **로고/아이콘 노드** | G6 `image` 노드와 노드 구성요소(key/label/icon/badge/halo/port) ([BaseNode](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/element/node/BaseNode.en.md)) · NVL `icon` + `overlayIcon`(위치·크기 %) ([Node](https://neo4j.com/docs/api/nvl/current/interfaces/_neo4j_nvl_base.Node.html)) · Cytoscape `background-image`(+`background-fit`, `background-clip`) ([style.md](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/style.md)) · Ogma node image + badge image ([ogma-styles 배지 예시](https://user-images.githubusercontent.com/26884/132239390-7abf79ef-f9ad-4c8d-bf1a-3129b4739a33.png)) | **이미 구현**(`graph-visuals.ts`: 로고 실루엣 PNG + 이니셜 폴백). 개선 여지는 "로고 없는 기업"의 이니셜 타이포 규격화뿐 |
| **뱃지(개수·상태)** | Ogma: 노드당 **4개 코너 배지**, 배지에 배경색/이미지/아이콘, "고정 크기 vs 노드와 함께 확대" 선택 ([badge 예제](https://doc.linkurious.com/ogma/latest/examples/node-badge.html)) · G6 `badges`(placement right-top 등) · NVL `overlayIcon` | 줍: 기업 노드 우상단 `근거 N`, 사건 노드 `출처 N`; 검증 상태(일치/불일치/보류)는 배지 색 + 아이콘 |
| **상태(state)별 스타일** | G6 state(active/selected/highlight/inactive/disabled) 시스템 · NVL `activated/hovered/selected/disabled/pinned` | **이미 구현**(emph/faded). 추가 후보: `pinned`(사용자가 고정한 노드 표시) |
| **도넛/파이 노드(비율)** | **G6 `donut` 노드**: `donuts: number[]` 또는 `{value,color,fill,stroke...}[]`, `innerR`(%), 기본 팔레트 `tableau` ([Donut 노드](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/element/node/Donut.en.md)) · **Ogma**: 속성이 배열이면 노드 색이 **파이차트로 분할**되고, 레이어로 **클러스터 도넛**을 그리는 예제 존재 ([Cluster annotation](https://doc.linkurious.com/ogma/latest/examples/layers-clusters.html)) · Cytoscape: 기본 없음 → 동적 SVG를 `background-image`로 넣는 패턴이 공식 문서에 예시됨(위 style.md의 SVG 예시) | 줍: 기업 노드 링 = "이슈 영향 구성(호재/악재/혼합/보류)" 또는 "근거 검증 상태 구성". **색+각도**라 색각 이상 대응이 필요(§색 규칙) |
| **그룹/콤보 노드** | G6 **콤보**(circle/rect, `collapsed`, 뱃지/라벨/할로) + `CollapseExpand` 상호작용 · Ogma **NodeGrouping/EdgeGrouping**(AML 데모가 이걸로 패턴 단순화) · Cytoscape **compound nodes**(부모-자식) + `expand-collapse` 확장 | 줍: "동일 토픽 사건 묶음", "같은 매체 출처 묶음", 허브 기업의 리프 이슈 묶기 |
| **헐/버블셋(묶음 영역)** | G6 `Hull` 플러그인 — "점 집합의 **볼록/오목 폴리곤**으로 감싸기" ([plugin/hull](https://g6.antv.antgroup.com/en/manual/plugin/hull)) · `BubbleSets` 플러그인 · Cytoscape `bubblesets` 확장([확장 목록](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/extensions.md)) | 줍: 클러스터를 **콤보 노드 대신 배경 영역**으로 표현(레이아웃을 흔들지 않고 테마 표시) |
| **HTML/카드형 노드** | Ogma **Identity card nodes** · G6 HTML/React 노드 · Cytoscape `dom-node`/`node-html-label` 확장 | 줍: "사건 카드 노드"(제목·매체·시각 2줄)는 확대 시에만; 모바일은 금지 후보(성능·겹침) |

### 2.2 간선

| 패턴 | 근거 | 줍 적용 메모 |
|:--|:--|:--|
| **모양으로 의미 구분** | Cytoscape `curve-style` 9종: `haystack`(기본·빠름), `bezier`(평행 자동 번들), `unbundled-bezier`, `segments`, `round-segments`, `straight`, `straight-triangle`, `taxi`, `round-taxi`(계층용 직각·번들) ([style.md](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/style.md)) · G6 엣지 6종(line/polyline/cubic/cubic-horizontal/cubic-vertical/quadratic) | 줍은 이미 실선/파선/점선 + 화살표로 관계 유형을 구분(v3) — 유지 권장. **`line-style: dashed/dotted`은 렌더 비용이 크다**는 공식 성능 문서 주의([performance.md](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/performance.md)) |
| **방향(화살표)** | Cytoscape 성능 문서: "화살표는 비용이 크다 — 의미가 없다면 쓰지 말라. **불투명+화살표가 반투명+화살표보다 2배 이상 빠르다**" · Ogma `shape.head/tail`, G6 `startArrow/endArrow` | 줍: `FOLLOWS`, `INVOLES`는 방향 의미가 있으므로 유지, `SHARES_ISSUE`는 무방향(이미 구현) — **의미 없는 화살표를 붙이지 않는 원칙**을 문서화 |
| **다중 간선(평행 엣지)** | Cytoscape `bezier`: 평행 엣지를 **곡률만 바꿔 자동 번들**, 개수가 홀수면 가운데가 직선; `haystack`: "**평행 엣지가 많은 그래프**에 효과적" (단, 루프·컴파운드·화살표 미지원) | 줍: 여러 사건이 같은 기업쌍을 잇는 경우(파생 `SHARES_ISSUE`)가 이에 해당 — 현재도 bezier라 자동 분리된다. 문제는 **라벨 겹침** |
| **간선 라벨 배치** | Cytoscape `text-rotation: autorotate`, `source-label/target-label` + 각종 offset/margin, `text-background-*`(배경 사각형/둥근 사각형), `text-wrap: ellipsis` + `text-max-width` · Ogma 엣지 텍스트: `position: centered|shifted`, source/target 별도 텍스트, `minVisibleSize`(기본 4px — **가늘면 자동 숨김**) | 줍: 이미 중앙 `summary` + 배경. 개선 후보 = **"짧은 엣지는 자동으로 요약 생략"**(길이 기반), 선택 시에만 전문 표시 |
| **라벨 LOD(확대 수준별)** | Cytoscape `min-zoomed-font-size`(작으면 라벨 미표시) · Ogma `minVisibleSize`(엣지/텍스트/스트로크/아웃라인 각각) · Tom Sawyer "LOD UIs" · CI "줌 단계에 따라 정보량이 달라진다" | 줍: `lodFor()`로 이미 구현(노드 0.55 / 엣지 0.95 + 엣지 160개 예산). 남은 개선 = **밀집 구간에서 라벨 충돌 회피**(라벨 스프라이트 겹침 계산) |
| **간선 번들링(힘 기반)** | G6 `EdgeBundling` 플러그인(문서: "엣지 번들링") · CI 지오 예제: 라우트를 묶으면("bundled") **이동 추세가 보인다** vs 안 묶으면 개별 경로만 보임 | 줍: 수백 간선 단계에서 후보. Cytoscape 코어엔 힘 기반 번들링이 없다 → §6 표 참조 |

### 2.3 다크 배경 팔레트

- **Ogma 테마 프리셋**: "Midsummer night"(다크), "Afternoon nap", "Morning breeze" — 각 테마가 **node/edge halo 폭, edge outline 폭** 같은 다크 전용 변수를 함께 배포한다([ogma-styles](https://github.com/Linkurious/ogma-styles)).
- **G6**: "**light and dark 2종 내장 테마 + 20여 개 커뮤니티 팔레트**"([v5 README](https://github.com/antvis/G6/blob/v5/README.md)) — 다크에서는 채도·명도 기준을 따로 두는 것이 전제.
- **yFiles 데모 전부**: 모든 공개 데모 페이지에 `dark_mode` 토글이 있어, **같은 그래프의 라이트/다크 대조**를 직접 볼 수 있다(예: [Knowledge Graph](https://www.yfiles.com/demos/showcase/knowledge-graphs) 우상단).
- **Neo4j GraSS**: 노드 채움색·테두리색과 함께 **라벨 내부/외부 텍스트색을 별도 속성으로 지정**한다(`text-color-internal`, `text-color-external`) — 줍의 "라벨 배경 + 대비 텍스트" 조합과 같은 역할 분리([GraSS 문서](https://github.com/neo4j/neo4j-browser/blob/master/docs/modules/ROOT/pages/operations/browser-styling.adoc)).
- **줍 적용 원칙 `[추론]`**: ① 어두운 배경에서는 채도 높은 상징색이 배경과 붙어 보이므로 **1px 테두리/halo로 윤곽 보장**(줍은 이미 `lowContrast` 노드에 테두리 적용) ② 간선은 배경 대비 3:1 이상 ③ 라벨은 배경 불투명도 0.92 유지(가독 배경 필수) ④ 다크에서만 팔레트를 다시 고르지 말고 **동일 토큰명 + 값만 교체**.

---

## 3. 탐색 상호작용 패턴

### 3.1 점진 확장 / 드릴다운

- yFiles 지식 그래프: **더블클릭 → 이웃 뷰**가 열리고 메인 그래프는 그 노드로 줌([링크](https://www.yfiles.com/demos/showcase/knowledge-graphs)).
- Ogma: **비동기 확장**(그룹 펼칠 때 로딩 스피너·자식 온디맨드: `visual-grouping-async-expand`), **제자리 확대**(더블클릭 시 노드를 20배로 키우는 `fisheye-expand`), **확장/축소 in place**(`fisheye-circlepack`) ([예제 인덱스](https://doc.linkurious.com/ogma/latest/examples/)).
- G6: `collapse-expand`, `focus-element`, `click-select`, `hover-activate` 등 상호작용 15종([behavior 디렉터리](https://github.com/antvis/G6/tree/v5/packages/site/docs/manual/behavior)).
- **줍**: 이미 "더블탭 → 이웃 확대"가 있다. 다음 단계는 ① **"n홉만 보기" 필터**(현재 `isolate` 토글 확장) ② 확장 시 **개수 예고 + 상한**(CI starburst 권고).

### 3.2 포커스 + 컨텍스트

- Cytoscape: 선택/호버 시 클래스 + `opacity` 조합으로 디밍(줍 구현과 동일 계열), **`cytoscape.js-view-utilities`**가 "검색·하이라이트" API 제공([확장 목록](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/extensions.md)).
- G6 `focus-element`·`hover-activate`, G6 `fisheye` 플러그인(돋보기 왜곡) — 줍에는 과함.
- CI UX 가이드: **점진적 공개(progressive disclosure)** 를 명시적 원칙으로 둔다("상세는 요구 시점에").

### 3.3 경로 하이라이트 ("이 둘은 어떻게 연결되나")

- Cytoscape **코어에 그래프 알고리즘 내장**: `eles.dijkstra()`, `eles.aStar()`(가중/비가중, 휴리스틱), BFS/DFS 등([API 타입 정의에서 확인](https://github.com/cytoscape/cytoscape.js/blob/master/index.d.ts) · 문서 앵커: https://js.cytoscape.org/#eles.aStar).
- yFiles **Graph Analysis 데모**: 최단 경로·흐름·중심성 등 알고리즘을 툴바에서 골라 실행하고 결과를 그래프에 그대로 반영([데모](https://www.yfiles.com/demos/showcase/graphanalysis)).
- Ogma **Transport network analysis**: "find shortest paths"를 지도 위 그래프에서 수행([예제](https://doc.linkurious.com/ogma/latest/examples/)).
- **줍**: "기업 A→기업 B 경로 찾기"를 **경로를 목록으로도 함께 표시**(접근성 대안 뷰와 공유).

### 3.4 필터·검색에서 그래프로

- yFiles 지식 그래프의 **온톨로지 뷰**: 트리플(타입)을 클릭 → 그 타입만 남김/숨김; "click an edge to filter the graph to show only items matching its triplet".
- Graphistry: **히스토그램 브러시 + 필터/제외 패널**(UI Guide 8~9p, 32p~).
- Ogma: **Cyber security log analysis**("Filter cybersecurity logs to focus on relevant events and timeframes") · **Performance Filter**(범위 슬라이더 필터 성능).
- **줍**: 기존 필터(관계 유형 토글)에 ① **매체/출처 유형 필터** ② **기간 필터**(§3.5와 결합) ③ 검색 결과 → 그래프 하이라이트(리스트에서 선택 시 카메라 이동 + 이웃 강조).

### 3.5 시간 슬라이더 · 애니메이션 재생

- **G6 Timebar**: 타임라인/차트 2모드, `elementTypes: node|edge|combo`, **필터 방식 `modify`(데이터에서 제거) | `visibility`(숨김)**, `loop`, 재생/속도/앞뒤 이동 콜백, 요소에 `data.timestamp` 필요 ([Timebar 문서](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/plugin/Timebar.en.md) · [라이브 예제](https://g6.antv.antgroup.com/en/examples/plugin/timebar)).
- **KronoGraph**(CI): 대량 이벤트를 **집계→줌으로 개별 확대**, Reveal/Ping/heatmap 강조, **주석**으로 내러티브, 그래프·지도 SDK와 연동 ([제품 페이지](https://cambridge-intelligence.com/kronograph/)).
- **yFiles Timeline / Fraud Detection**: 타임라인 막대 = 시점별 노드 생성/삭제 수, **기간 사각형**, **스크롤로 일/월/년 상세 전환**, **재생 버튼**, 그래프 선택과 양방향 하이라이트 ([Timeline 데모](https://www.yfiles.com/demos/application-features/timeline) · [Fraud Detection](https://www.yfiles.com/demos/showcase/frauddetection)).
- **줍**: 이슈 노드에 **발행 시각**이 이미 있다면 가장 임팩트 큰 개선. Cytoscape에서는 HTML 레이어 타임바 + `visibility` 방식이 G6 Timebar와 동일 효과를 낸다(§6).

### 3.6 레이아웃 전환

- G6: 19종(AntVDagre, Circular, **ComboCombined**, Concentric, D3Force/3D, Dagre, Fishbone, **ForceAtlas2**, Force, Fruchterman, Grid, MDS, Radial, Random, Snake, CompactBox/Dendrogram/Mindmap/Indented) + **Web Worker/WASM/GPU 가속 옵션**([layout overview](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/layout/overview.en.md)).
- CI: **organic / structural(리프를 부채꼴로 정리) / sequential(스태킹으로 격자 정렬)** — "starburst를 없앨 수 없을 때의 최후 수단"([starburst 글](https://cambridge-intelligence.com/blog/starburst-effect-in-graph-visualization/)).
- **줍**: 현재 fcose↔dagre 2종. 추가 후보 = **concentric(중심=내 종목)**, **시간 방사형**, 그리고 "고립 노드 격자 타일링"(fcose의 `tile`/`tilingPadding*`이 차수 0 노드를 격자로 배치하는 옵션을 이미 제공 — [fcose README](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose)).

### 3.7 미니맵 / 개요

- G6 `Minimap`(크기·위치·마스크·필터, React 노드와 비호환) · Tom Sawyer **Overview window**(선택 영역 이동=팬, 크기 변경=줌) · Cytoscape `navigator`(조망 위젯) · NVL 옵션의 **미니맵 컨테이너** · (기존 조사에서 다룬 Bloom 미니맵은 생략).
- **줍**: 수백 노드 전 단계에서 가장 저렴한 "탐색 안전망". Cytoscape navigator로 즉시 가능.

### 3.8 라벨 LOD

- Cytoscape `min-zoomed-font-size`(임계 이하 미표시) / Ogma `minVisibleSize`(엣지·텍스트·아웃라인 개별) / Tom Sawyer LOD UI / G6 `auto-adapt-label` 상호작용.
- **줍**: 이미 "LOD 단계 전환" 방식. 개선 여지 = **모드별 예산 분리**(예: 밀집 모드에서 기업 라벨만, 사건 라벨은 선택 시).

### 3.9 대규모(수백~수천) 성능

- Cytoscape 공식 성능 가이드: 라벨이 가장 비싸고, `haystack` 엣지, **solid 엣지**, 화살표 자제, 노드 배경 이미지 `no-repeat`+`background-clip: none`, **`hideEdgesOnViewport`**, **`textureOnViewport`**, `pixelRatio: 1`, 컴파운드/오버레이 자제, `cy.getElementById`, `cy.batch` ([performance.md](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/performance.md)).
- yFiles Large Graphs: **작은 줌에서는 WebGL, 임계 넘으면 SVG로 전환**해 "성능과 품질을 모두" 잡고, 임계값을 슬라이더로 바꿔 직접 비교 가능 ([데모](https://www.yfiles.com/demos/showcase/large-graphs)).
- Cosmograph: GPU force layout, "수십만 노드·엣지"를 제품 문구로 명시. G6: 레이아웃 worker/WASM/GPU 가속.
- **줍**: 목표 규모(수백)에서는 Cytoscape Canvas로 충분 `[추론]`. 단, **노드 수백 + 엣지 라벨 + 로고 이미지 동시 표시**는 위 옵션 조합으로 대비(특히 `textureOnViewport`는 이미 켜져 있음).

---

## 4. 금융·뉴스 맥락 특화 패턴

### 4.1 시간축 결합(사건 타임라인)

- yFiles **Event Timeline**: 사건(엣지)의 x좌표 = 발생 시각, 개체(노드)는 레인. 줌아웃 시 **자동 집계**, 동시각 이벤트는 **하이퍼엣지 → 클릭 시 상세**([데모](https://www.yfiles.com/demos/showcase/event-timeline)).
- yFiles **Fraud Detection**: 타임라인 히스토그램(생성/삭제 이벤트 수) + 기간 사각형 + 재생 + 상세 검사 패널.
- KronoGraph: 집계·줌·주석([제품](https://cambridge-intelligence.com/kronograph/)).
- **줍**: 이슈=사건이므로 "**이슈 레인 + 시각 x축**" 표현이 자연스럽다. `[추론]` 다만 줍의 주 화면은 관계 그래프이므로, 타임라인은 **보조 뷰(하단 바)** 로 두고 그래프와 양방향 하이라이트하는 구성이 yFiles Fraud Detection과 동형.

### 4.2 흐름/샹키(자금·공급 흐름)

- yFiles Sankey: "**엣지 두께 ∝ 흐름량**"(금융 자금 흐름 포함), 노드는 열로 배치, 노드 크기=부착 엣지 합, 레이어드 레이아웃으로 자동 배치, 대화형 필터/줌 결합 ([해설 페이지](https://www.yworks.com/pages/interactive-sankey-diagram-visualization)).
- Ogma **Supply chain**("/supply-chain"), yFiles **Supply Chain**(제품 흐름 클릭 → 해당 흐름 하이라이트) — 공급·생산 관계가 있는 줍의 `STRUCTURALLY_RELATED_TO`와 결부 가능.
- **주의**: 줍의 관계는 **방향·역할 요약**이 핵심이고 금액·물량 수치가 없다 → 지금은 샹키(두께) 표현에 필요한 데이터가 없다. `[추론]` 근거 인용 수를 두께로 쓰는 건 의미 왜곡 위험이 있어 비권장(NFR-08 취지).

### 4.3 사건 클러스터링

- yFiles KG: **Louvain 모듈러리티 클러스터 색 + PageRank 크기**, 클러스터 단위 필터/스포트라이트.
- Ogma: **Leiden 커뮤니티 검출** 예제, 클러스터 배경/도넛 오버레이.
- G6: `Hull`/`BubbleSets` 플러그인으로 노드 집합을 도형으로 감싸기.
- Cytoscape: compound nodes(구조적 그룹) + `bubblesets` 확장(시각 그룹).
- **줍**: "동일 뉴스 사건 클러스터(예: 실적·소송·규제)"를 **배경 헐 + 라벨**로 표시하면 고립 사건이 밀집한 구역이 자연스럽게 드러난다.

### 4.4 고립 노드(연결 없는 사건) 처리

- Graphistry: **Prune Isolated Nodes** 토글(차수 0 제외) ([UI Guide 20~25p](https://hub.graphistry.com/static/docs/ui/graphistry-ui-guide.pdf)).
- yFiles KG: 고립 노드를 **문제 목록에 넣고 일괄 제거**. CI: snowstorm(고립이 많아 아무것도 안 보이는 상태)은 **데이터 보강·그룹핑**으로 처방.
- fcose: `tile` + `tilingPaddingVertical/Horizontal`이 "**차수 0 멤버를 격자로 정리**"하는 옵션을 제공 — 줍은 이미 `tile: true`를 켜고 있다.
- **줍 적용 후보**
  1. **"연결 없음" 존**: 고립 사건을 화면 하단/우측에 **격자 타일 + 헐 배경 + '연결 없음 N'** 라벨로 분리(무작위 배치 방지).
  2. **요약 버킷**: 고립 사건 상위 N개만 개별 노드로, 나머지는 "기타 이슈 N" 콤보로.
  3. 필터: "연결된 것만 보기" 토글(차수 ≥1).

### 4.5 근거 문서 연결 표현

- **Kumu Profiles**: 모든 요소/연결에 **프로필**(설명·태그·이미지·커스텀 필드(카테고리 그룹))을 붙이고, 프로필 필드로 데코레이션/필터/지도를 구동. 위젯 프레임워크로 목록·임베드 콘텐츠를 프로필/개요에 붙인다 ([Profiles](https://docs.kumu.io/guides/profiles) · [Widgets](https://docs.kumu.io/guides/widgets)).
- **Tom Sawyer invokable view**: 드로잉·**인스펙터**·테이블·트리·타임라인·지도·차트를 **다이얼로그/패널로 호출** ([페이지](https://www.tomsawyer.com/graph-visualization)).
- **CI GraphRAG 실험**: 근거 사실을 그래프에서 강조 + **주석·챕터 애니메이션**, 노드 → **원문 데이터로 이동** ([글](https://cambridge-intelligence.com/blog/5-ways-graph-visualization-enhances-graphrag/)).
- Ogma **Annotations**(그래프 위 스티키 노트) · NVL `html`/캡션.
- **줍**: 이미 상세 패널에 근거 원문 인용이 있다(v3). 다음 단계 후보 = ① 노드/엣지에 **근거 N 앵커**(배지/오버레이) ② 패널에서 인용을 **그래프 하이라이트와 동기화**(문장 선택 → 해당 사건 노드 강조) ③ 인용에서 원문 URL로 바로 이동.

---

## 5. 모바일 그래프

### 5.1 제품 사례

- **Gephi Lite**: "Works on desktop, tablets and mobiles", **터치·멀티터치** 지원, UI 반응형 — 오픈소스 웹 앱이 모바일을 1급 타깃으로 명시한 드문 사례 ([제품 페이지](https://gephi.org/lite)).
- yFiles 데모: 공개 데모는 뷰포트에 맞춰 동작하지만 **모바일 전용 그래프 지침 문서는 찾지 못했다** `[미확인]`.
- (기존 조사에서 다룬 Obsidian 로컬 그래프, Bloom 모바일 부재 논의는 반복하지 않는다.)

### 5.2 연구

- **Brehmer, Lee, Stasko, Tominski (2021), "Interacting with Visualization on Mobile Devices"** (Mobile Data Visualization, Ch.3): ① **fat finger 문제**(마크가 작으면 선택 불가, 선택 가능하게 만들려면 마크가 커져야 함) ② 손가락 **가림(occlusion)** — 결과를 손을 떼야 알게 되는 문제 ③ **터치 오인**(핀치↔회전) ④ 터치 어휘가 작아 **메뉴·모드 전환에 의존** → 화면 점유·발견성 문제 ⑤ 대안: **모달 렌즈**(Kinetica/Tangere), **고정 크기 선택 영역**(사각형/부채꼴/동심 밴드), 무형의 큰 터치 타깃, 보로노이 분할 ⑥ 휴대폰 사례: **GraphTiles**(타일 노드 + 스와이프 이동 + 길게 눌러 선택→faceted search), **Orchard**(세로 리스트 + 가로 스와이프로 링크 범주 축 전환) ([PDF](https://vca.informatik.uni-rostock.de/~ct/publications/Brehmer21MobileVisInteraction.pdf)).
- **Schwab et al. 2019**(같은 장에서 인용): 팬/줌 제스처를 난이도별로 비교 — "연속 핀치가 대부분 최선"이나 난이도가 높을 때는 축 방향 브러시/직교 드래그가 효과적.
- **TADA (arXiv:2311.04502v3, 2024)**: 태블릿에서 **음악적 톤+음성**으로 노드-링크 다이어그램을 탐색하는 BLV(시각장애) 사용자용 시스템 ([arXiv](https://arxiv.org/abs/2311.04502)) — 그래프의 비시각 대안이 "리스트"보다 풍부할 수 있음을 보여주는 최신 근거.
- (기존 조사에 이미 있는 Orchard·Chunky Chains·Büschel 모바일 실험은 중복 회피.)

### 5.3 줍 적용 `[추론]`

1. **노드 최소 44px + 탭 타깃 확대**: fat finger 대응. 줍은 모바일에서 기업 원 72px / 사건 원 36px → **사건 노드는 탭 타깃만 44px로 확장**(G6는 히트 영역 확대 옵션 `increasedLineWidthForHitTesting`을 공식 제공).
2. **선택 영역은 고정 크기**: Brehmer et al. 2018처럼 "탭 → 고정 크기 사각형/원형 선택"을 쓰면 작은 사건 마크도 선택 가능(줍의 이웃 확대와 결합).
3. **제스처는 3개로 제한**: 탭(선택) / 드래그(팬) / 핀치(줌) + 더블탭(확대) — 추가 제스처는 발견성 비용이 크다.
4. **리스트 퍼스트 폴백 유지**: `RelationList`(이미 구현)가 1차 대안이며, 그래프는 "관계 탐색"에 집중.

---

## 6. Cytoscape.js 구현 가능성 표

기준: **줍 v3 스택(Cytoscape.js 3.x + fcose + dagre, Canvas)**. "확장"은 공식 문서의 서드파티 확장([확장 목록](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/extensions.md)).

| 패턴 | 기본 | 확장/우회 | 판정 | 근거·비고 |
|:--|:--:|:--|:--|:--|
| 로고/아바타 노드 | ✅ | — | 즉시 | `background-image`(+`background-fit`, 다중 이미지 레이어) · 이미 구현 |
| 노드 뱃지(4코너) | ❌ | 다중 `background-image` 레이어 · `cytoscape.js-layers`/`dom-node`/`node-html-label` | 우회 구현 | Ogma처럼 "고정 크기 vs 확대" 선택을 직접 구현해야 함 |
| 상태(선택/호버/디밍/핀) | ✅ | — | 즉시 | 클래스+스타일, `transition-property` · 이미 구현 |
| 도넛/파이 노드 | ❌ | 동적 SVG(data URI)를 `background-image`로 · `cytoscape.js-overlays`(바·스파크라인) · 레이어 오버레이 | 우회 구현 | 공식 문서가 "함수로 SVG 생성 후 background-image" 예시를 제공 |
| 그룹(구조적) | ✅ | `cytoscape.js-expand-collapse`(컴파운드 부모 접기/펴기) | 즉시~확장 | compound nodes는 코어 기능, 접힘 애니메이션은 확장 |
| 그룹 영역(헐/버블셋) | ❌ | `cytoscape.js-bubblesets` · `layers`로 캔버스에 직접 도형 | 확장 | G6 `hull`처럼 오목 폴리곤은 별도 계산 필요 |
| 노드 HTML/카드 | ❌ | `dom-node`, `node-html-label`, `layers` | 확장 | 모바일 성능 주의 |
| 간선 모양/곡률 | ✅ | — | 즉시 | `curve-style` 9종, bezier 자동 평행 번들, taxi/round-taxi, segments |
| 다중(평행) 간선 | ✅ | `haystack`(대량 평행에 유리, 루프·화살표 제약) | 즉시 | 이미 bezier 사용 |
| 간선 라벨(회전·배경·소스/타깃) | ✅ | — | 즉시 | `text-rotation: autorotate`, `source-label` 등 |
| 라벨 LOD(줌 임계) | ✅ | 자체 단계 스타일(이미 구현) | 즉시 | `min-zoomed-font-size` + 현행 `lodFor()` |
| 라벨 충돌 회피 | ❌ | 자체 계산(라벨 bbox 근사) 또는 외부 배치 로직 | 커스텀 | Cytoscape엔 라벨 배치 엔진이 없음(구현 비용 큼) |
| 간선 번들링(힘 기반) | ❌ | 없음(택시/세그먼트 근사·수동 제어점만) | **미지원** | 필요하면 G6 `EdgeBundling` 또는 사전 계산 좌표(외부 번들링 알고리즘) |
| 경로 하이라이트 | ✅ | `eles.dijkstra()`, `eles.aStar()` | 즉시 | 코어 알고리즘 + 클래스 강조 |
| 포커스+컨텍스트/검색 | ✅ | `cytoscape.js-view-utilities` | 즉시~확장 | `$id` 대신 `getElementById` 성능 권고 |
| 점진 확장(백엔드) | ✅ | `cy.add` + 레이아웃 재실행(증분 시작 위치) | 즉시 | 이미 구현(더블탭·모드 전환) |
| 미니맵 | ❌ | `cytoscape.js-navigator` · `layers` | 확장 | NVL 미니맵 옵션과 동일 개념 |
| 타임바/시간 필터 | ❌ | HTML 레이어 + `visibility`/클래스 토글(자체 구현) | 커스텀 | G6 Timebar와 동일 UX는 "데이터 제거 없이 visibility" 방식 |
| 레이아웃 전환 | ✅ | fcose/cola/klay/elk/dagre/euler/cise/spread/**cosmos-over-cytoscape(GPU)** | 즉시~확장 | `cy.layout()` 재실행 |
| 대규모(수백~수천) | ✅ | `textureOnViewport`, `hideEdgesOnViewport`, `pixelRatio`, haystack, `batch` | 즉시 | 수백 노드는 Canvas로 충분, 수천+에서 WebGL 이점 `[추론]` |
| 모바일 터치 | ✅ | — | 즉시 | tap/dbltap/pinch 내장, 히트 영역 확대는 자체 |
| 다크 테마 | ✅ | — | 즉시 | 스타일시트 전면 제어(값만 교체) |
| 접근성(키보드/스크린리더) | ❌ | DOM 병행(현행 `RelationList`) | 우회 | 캔버스는 DOM 접근성 없음 — 기존 조사 결론 유지 |
| Sigma.js 전환 필요? | — | — | **불필요** | WebGL 이점은 수천+ 노드 동시 표시에서 발생(기존 조사 §4.4) |
| G6 전환 필요? | — | — | **불필요(조건부)** | 필요해지는 유일한 조건: **힘 기반 간선 번들링**과 **도넛/뱃지/콤보를 기본 기능으로** 쓸 때. 그 외는 §7 후보들이 Cytoscape로 구현 가능 |

---

## 7. 줍에 추천하는 개선 후보 (12)

난이도: 하(1~2일) / 중(3~5일) / 상(1주+) `[추론]`. "필요 데이터"는 현재 스키마 기준.

| # | 후보 | 무엇을 바꾸나 | 효과 | 난이도 | 필요 데이터 | 레퍼런스 |
|:--:|:--|:--|:--|:--:|:--|:--|
| 1 | **미니맵(개요 위젯)** | 그래프 우하단에 전체 조망 + 현재 뷰포트 사각형 | 수백 노드 대비 "길잃기" 방지. 현재 그래프 컨트롤에 없는 마지막 조각 | 하 | 없음 | [Cytoscape navigator](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/extensions.md), [Tom Sawyer Overview](https://www.tomsawyer.com/graph-visualization) |
| 2 | **노드 뱃지(근거 N·검증 상태)** | 기업/사건 노드 코너에 근거 수·검증 상태 배지 | "왜 이 연결을 믿어야 하나"를 그래프에서 즉답. 상세 패널 열기 전 판단 가능 | 중 | 근거 수·검증 상태(있음) | [Ogma badge](https://doc.linkurious.com/ogma/latest/examples/node-badge.html), [G6 badges](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/element/node/BaseNode.en.md) |
| 3 | **도넛 링 노드(비율)** | 기업 노드 = 로고 + 얇은 링(이슈 영향 구성 또는 검증 상태 구성) | 기업을 "노드"에서 "요약 카드"로 승격. 다크/라이트 모두 성립 | 중 | 이슈 분류 집계(있음), 색각 대응 필요 | [G6 Donut](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/element/node/Donut.en.md), [Ogma 파이/도넛](https://doc.linkurious.com/ogma/latest/examples/layers-clusters.html) |
| 4 | **하단 타임바(이슈 발생 시각)** | x축=시각, 그래프는 `visibility` 필터로 양방향 연동(재생 포함) | 줍의 최대 미탐색 축 "언제"를 추가. 뉴스 기반 서비스에서 가장 이해도 높은 축 | 중~상 | 이슈 발생/수집 시각(확인 필요) | [G6 Timebar](https://g6.antv.antgroup.com/en/examples/plugin/timebar), [yFiles Timeline](https://www.yfiles.com/demos/application-features/timeline), [KronoGraph](https://cambridge-intelligence.com/kronograph/) |
| 5 | **"연결 없음" 존 + 요약 버킷** | 고립 사건을 격자/헐 배경으로 분리, 상위 N개만 개별 노드, 나머지는 "기타 이슈 N" | 현재 가장 큰 시각적 노이즈(고립 사건 多)를 정보로 전환 | 중 | 없음(차수 계산만) | [Graphistry Prune](https://hub.graphistry.com/static/docs/ui/graphistry-ui-guide.pdf), [fcose tiling](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose), [CI snowstorm 처방](https://cambridge-intelligence.com/blog/designing-intuitive-data-experiences-with-graph-visualizations/) |
| 6 | **클러스터 헐(주제 영역)** | 동일 주제/사건군을 배경 도형 + 라벨로 감싸기 | 그룹을 "노드"가 아니라 "영역"으로 보여 레이아웃 왜곡 없이 맥락 제공 | 중 | 토픽/클러스터 태깅(향후) | [G6 Hull](https://g6.antv.antgroup.com/en/manual/plugin/hull), [Cytoscape bubblesets](https://github.com/sgratzl/cytoscape.js-bubblesets) |
| 7 | **경로 찾기(두 기업 연결)** | 선택 2개 기업 간 최단 경로 하이라이트 + 경로를 목록 텍스트로 | "이 둘이 왜 엮였나"라는 핵심 질문에 대한 직답 | 중 | 없음 | [Cytoscape aStar/dijkstra](https://github.com/cytoscape/cytoscape.js/blob/master/index.d.ts), [yFiles Graph Analysis](https://www.yfiles.com/demos/showcase/graphanalysis) |
| 8 | **근거 앵커 + 동기 하이라이트** | 패널 인용 선택 시 해당 사건/간선 그래프 강조, 노드에 "근거 N" 앵커 | FR-44(인용 근거)를 화면 간 연결로 강화. 신뢰 UX의 핵심 | 중 | 근거 인용 매핑(있음) | [Kumu Profiles](https://docs.kumu.io/guides/profiles), [CI GraphRAG](https://cambridge-intelligence.com/blog/5-ways-graph-visualization-enhances-graphrag/), [Ogma annotations](https://doc.linkurious.com/ogma/latest/examples/) |
| 9 | **n홉 포커스("이 기업 기준만")** | 현재 포커스/격리 토글을 홉 수 제어(+방향 in/out)로 확장 | 기업 중심 탐색을 "지도"에서 "질문 도구"로 | 중 | 없음 | [Kumu focus(기존 조사)] + [yFiles 이웃 뷰](https://www.yfiles.com/demos/showcase/knowledge-graphs) |
| 10 | **간선 라벨 규율(길이·밀도 기반)** | 짧은 엣지 요약 자동 생략, 선택/호버 시 전문, 라벨 예산 상향 조정 | 엣지 요약 라벨은 줍의 강점이자 과밀 원인 — 규칙으로 정리 | 하 | 없음 | [Cytoscape style](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/style.md), [Ogma minVisibleSize](https://doc.linkurious.com/ogma/latest/api/types/edgeattributes.html) |
| 11 | **모바일 탭 타깃·선택 영역 정리** | 사건 노드 히트 영역 44px 확대, 고정 크기 선택 영역, 리스트 폴백 상시 노출 | 작은 화면에서 "선택 자체가 안 되는" 문제 제거 | 하 | 없음 | [Brehmer et al. 2021](https://vca.informatik.uni-rostock.de/~ct/publications/Brehmer21MobileVisInteraction.pdf), [Gephi Lite 모바일](https://gephi.org/lite) |
| 12 | **다크 배경 윤곽·대비 재점검** | 다크에서 노드 halo/테두리, 간선 대비, 라벨 배경 불투명도, 팔레트 값 재확인 | v3 다크 캡처의 실제 리스크(검은 로고색·어두운 상징색) 해소 | 하 | 없음 | [Ogma 다크 테마](https://github.com/Linkurious/ogma-styles), [G6 테마](https://github.com/antvis/G6/blob/v5/README.md), [GraSS](https://github.com/neo4j/neo4j-browser/blob/master/docs/modules/ROOT/pages/operations/browser-styling.adoc) |

**우선순위 제안 `[추론]`**: ① 즉시(1·2·10·11·12 — 데이터 추가 없이 화면 완성도 상승) → ② 중기(4·5·7·9 — "탐색 질문" 확장) → ③ 데이터 준비 후(3·6·8 — 분류/클러스터/근거 매핑 확장). 특히 **4(타임바)** 는 이슈 발생 시각만 확보되면 줍의 그래프를 "관계 사진"에서 "사건 흐름의 지도"로 바꾸는 최대 임팩트 후보다.

---

## 캡처 대상 (Main이 열어 저장)

- 저장 위치: `docs/research/graph-refs/img/` · 파일명은 아래 slug 그대로(`pattern-<slug>.png`)
- ★ = 우선 캡처. 한 페이지에서 1~2장(전체 뷰 + 핵심 부분 확대) 권장.
- 모든 URL은 로그인 없이 열리는 공개 페이지다(확인 시점 2026-09-30).
- 참고: G6 문서 페이지 URL은 문서 소스가 링크한 경로 규칙(`/en/manual/...`, 소문자)을 따랐고, `donut`은 공식 BaseNode 문서가 직접 링크한 주소다. `minimap`은 같은 규칙으로 유추한 경로이므로, 404면 문서 소스(`Minimap.en.md`)의 대응 페이지를 열면 된다.

| slug | 공개 URL | 보면 되는 화면 부분 |
|:--|:--|:--|
| ★ `pattern-ci-ux-guide` | https://cambridge-intelligence.com/blog/designing-intuitive-data-experiences-with-graph-visualizations/ | "wireframe vs styled" 비교 이미지, 색 Do/Don't 타임라인 비교, hairball/snowstorm/starburst 예시 이미지 |
| ★ `pattern-ci-starburst` | https://cambridge-intelligence.com/blog/starburst-effect-in-graph-visualization/ | 콤보로 리프 노드 묶은 아바타 예제(항공 사고), organic/structural 레이아웃 대조, 스태킹 격자 이미지 |
| `pattern-ci-hairball` | https://cambridge-intelligence.com/blog/hairball-effect-in-graph-visualization/ | 리모델링 전/후(사람 노드 + betweenness 크기) 이미지 |
| ★ `pattern-kronograph` | https://cambridge-intelligence.com/kronograph/ | 타임라인+엔티티 병렬 표시 스크린샷, event summaries 확장 이미지, 그래프·지도 연동 이미지 |
| ★ `pattern-g6-donut` | https://g6.antv.antgroup.com/en/manual/element/node/donut | 문서 상단 "Online Experience" 라이브 데모(도넛 + 상태/뱃지/할로가 함께 보이는 노드 9종) |
| ★ `pattern-g6-timebar` | https://g6.antv.antgroup.com/en/examples/plugin/timebar | Time 모드/Chart 모드 타임바 데모(재생 버튼·구간 선택) |
| `pattern-g6-minimap` | https://g6.antv.antgroup.com/en/manual/plugin/minimap | 우하단 미니맵 + 마스크 사각형, 미니맵 크기/위치 옵션 데모 |
| ★ `pattern-yworks-knowledge-graph` | https://live.yworks.com/demos/showcase/knowledge-graphs/ | 좌측 Ontology View(트리플 필터), "Problem Detection" 패널(고립 노드), 클러스터 색+PageRank 크기, 이웃 뷰 |
| ★ `pattern-yworks-event-timeline` | https://live.yworks.com/demos/showcase/event-timeline/ | 레인(노드) × 수직 이벤트선(시각) 뷰, 줌아웃 시 집계, 하이퍼엣지 확대 |
| ★ `pattern-yworks-fraud-detection` | https://live.yworks.com/demos/showcase/frauddetection/ | 하단 타임라인 히스토그램 + 기간 사각형 + 재생 버튼, 우측 검사 패널, 사기 링 하이라이트 |
| `pattern-yworks-sankey` | https://www.yworks.com/demos/layout/sankey/index.html | 두께=흐름량, 열 배치, 인터랙션(선택·필터) |
| `pattern-yworks-large-graphs` | https://www.yfiles.com/demos/showcase/large-graphs | SVG 임계 슬라이더 + FPS 미터(WebGL↔SVG 전환) |
| ★ `pattern-ogma-badge` | https://doc.linkurious.com/ogma/latest/examples/node-badge.html | 노드 4개 코너 배지(고정 크기/확대 옵션) |
| ★ `pattern-ogma-theme-dark` | https://doc.linkurious.com/ogma/latest/examples/set-theme.html | "Midsummer night" 다크 테마가 적용된 그래프(노드 halo/엣지 outline) |
| `pattern-ogma-aml` | https://doc.linkurious.com/ogma/latest/examples/anti-money-laundering.html | 노드/엣지 그룹핑으로 복잡도 축소(그룹 접기·펴기) |
| `pattern-ogma-cluster-donut` | https://doc.linkurious.com/ogma/latest/examples/layers-clusters.html | 클러스터 배경 도형 + 도넛 차트 오버레이 |
| `pattern-cytoscape-fcose` | https://ivis-at-bilkent.github.io/cytoscape.js-fcose/demo/demo-compound.html | 컴파운드(그룹) 배치 결과, 품질(draft/default/proof)·타일링 옵션 패널 |
| `pattern-graphistry-ui` | https://hub.graphistry.com/static/docs/ui/graphistry-ui-guide.pdf | 6~9p 툴바 4계열, 20~25p Scene Settings의 Prune Isolated Nodes, 32p~ 필터/히스토그램 |
| `pattern-cosmograph-app` | https://cosmograph.app/run/ | 대규모 GPU 그래프 뷰(상단 설정 + 캔버스) |
| `pattern-gephi-lite` | https://gephi.org/lite/ | 제품 페이지의 외관 패널·동적 캡션·모바일 반응형 스크린샷(또는 https://lite.gephi.org/ 에서 샘플 그래프 열기) |
| `pattern-tomsawyer` | https://www.tomsawyer.com/graph-visualization | LOD UI(확대/축소 노드 상세 변화), Overview window, 툴팁/선택 강조, 스와인레인 그래프 |

---

## 출처

**디자인 가이드·도구**
1. Cambridge Intelligence — [UX 가이드](https://cambridge-intelligence.com/blog/designing-intuitive-data-experiences-with-graph-visualizations/) · [hairball](https://cambridge-intelligence.com/blog/hairball-effect-in-graph-visualization/) · [starburst](https://cambridge-intelligence.com/blog/starburst-effect-in-graph-visualization/) · [Figma Design Kit](https://cambridge-intelligence.com/developers/figma-design-kit/) · [GraphRAG](https://cambridge-intelligence.com/blog/5-ways-graph-visualization-enhances-graphrag/) · [KronoGraph](https://cambridge-intelligence.com/kronograph/) · [학습 허브](https://cambridge-intelligence.com/learn/graph-visualization)
2. AntV G6 v5 — [README](https://github.com/antvis/G6/blob/v5/README.md) · [문서 소스](https://github.com/antvis/G6/tree/v5/packages/site/docs/manual) · [예제](https://g6.antv.antgroup.com/en/examples)
3. yWorks/yFiles — [데모 목록](https://www.yfiles.com/demos) · [Knowledge Graph](https://www.yfiles.com/demos/showcase/knowledge-graphs) · [Event Timeline](https://www.yfiles.com/demos/showcase/event-timeline) · [Fraud Detection](https://www.yfiles.com/demos/showcase/frauddetection) · [Large Graphs](https://www.yfiles.com/demos/showcase/large-graphs) · [Timeline](https://www.yfiles.com/demos/application-features/timeline) · [Space & Time](https://www.yfiles.com/demos/showcase/time-space) · [Graph Analysis](https://www.yfiles.com/demos/showcase/graphanalysis) · [Supply Chain](https://www.yfiles.com/demos/showcase/supply-chain) · [Sankey](https://www.yworks.com/pages/interactive-sankey-diagram-visualization)
4. Neo4j — [NVL Base library](https://neo4j.com/docs/nvl/current/base-library) · [NVL Node](https://neo4j.com/docs/api/nvl/current/interfaces/_neo4j_nvl_base.Node.html) · [Bloom Perspectives](https://neo4j.com/docs/bloom-user-guide/current/bloom-perspectives/bloom-perspectives/) · [Browser GraSS](https://github.com/neo4j/neo4j-browser/blob/master/docs/modules/ROOT/pages/operations/browser-styling.adoc)
5. Graphistry — [UI Guide PDF](https://hub.graphistry.com/static/docs/ui/graphistry-ui-guide.pdf) · [GPU](https://www.graphistry.com/gpu)
6. Tom Sawyer — [Graph Visualization](https://www.tomsawyer.com/graph-visualization)
7. Ogma/Linkurious — [예제 인덱스](https://doc.linkurious.com/ogma/latest/examples/) · [스타일 튜토리얼](https://doc.linkurious.com/ogma/latest/tutorials/getting-started/design.html) · [EdgeAttributes](https://doc.linkurious.com/ogma/latest/api/types/edgeattributes.html) · [ogma-styles](https://github.com/Linkurious/ogma-styles) · [관리자 스타일 규칙](https://doc.linkurious.com/admin-manual/latest/styles) · [AML 유즈케이스](https://linkurious.com/blog/anti-money-laundering-use-cases-graph-analytics/)
8. Cosmograph — [앱](https://cosmograph.app/run/) · [문서](https://cosmograph.app/docs-general) · [라이브러리](https://next.cosmograph.app/library) · [dev 갤러리](https://cosmograph.app/dev/)
9. Gephi Lite / Retina — [제품](https://gephi.org/lite/) · [앱](https://lite.gephi.org/) · [문서](https://docs.gephi.org/lite/user-manual/) · [GitHub](https://github.com/gephi/gephi-lite) · [Retina(GitLab)](https://gitlab.com/ouestware/retina) · [Retina 앱](https://ouestware.gitlab.io/retina/)
10. Kumu — [Profiles](https://docs.kumu.io/guides/profiles) · [Widgets](https://docs.kumu.io/guides/widgets)

**그래프 시각 언어·상호작용 근거**
11. Cytoscape.js — [스타일 문서(원문)](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/style.md) · [성능 가이드](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/performance.md) · [확장 목록](https://raw.githubusercontent.com/cytoscape/cytoscape.js/master/documentation/md/extensions.md) · [코어 알고리즘 타입 정의(aStar/dijkstra)](https://github.com/cytoscape/cytoscape.js/blob/master/index.d.ts) · [fCoSE](https://github.com/iVis-at-Bilkent/cytoscape.js-fcose)
12. G6 문서 원문(사이트가 JS 렌더링이라 GitHub 원문 사용) — [BaseNode](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/element/node/BaseNode.en.md) · [Donut](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/element/node/Donut.en.md) · [BaseEdge](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/element/edge/BaseEdge.en.md) · [BaseCombo](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/element/combo/BaseCombo.en.md) · [Timebar](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/plugin/Timebar.en.md) · [Minimap](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/plugin/Minimap.en.md) · [Layout](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/layout/overview.en.md) · [Palette(테마)](https://github.com/antvis/G6/blob/v5/packages/site/docs/manual/theme/palette.en.md)
13. 모바일 — [Brehmer et al. 2021 (PDF)](https://vca.informatik.uni-rostock.de/~ct/publications/Brehmer21MobileVisInteraction.pdf) · [TADA (arXiv 2311.04502)](https://arxiv.org/abs/2311.04502)
