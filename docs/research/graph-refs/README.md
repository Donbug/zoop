# 그래프 중심 디자인 레퍼런스 — 요약 (2026-09-30)

줍의 핵심 화면인 관계 그래프를 기준으로 고른 레퍼런스 모음입니다. 정형화된 앱 UI(TDS 등)가 아니라 **그래프를 주 화면으로 쓰는 제품과 그래프 시각화 도구**만 다룹니다.

| 문서 | 내용 |
|---|---|
| [products.md](products.md) | 실제 제품 20종(근거 확보 18종): 금융·기업 관계, 조사·인텔리전스, 지식 탐색, 뉴스·이벤트 그래프 |
| [patterns.md](patterns.md) | 그래프 디자인 가이드·시각 언어·탐색 상호작용·모바일·Cytoscape.js 구현 가능성·개선 후보 12개 |
| `img/` | 공개 페이지 직접 캡처와 공식 이미지. 내부 참고용이며 각 출처는 본문에 있습니다. |

## 한눈에 보는 결론

두 조사가 독립적으로 같은 방향을 가리켰습니다.

1. **시간축을 붙인다.** 뉴스 서비스인데 지금 그래프에는 “언제”가 없습니다. Cosmograph·KronoGraph·yFiles·AI Supply Chain이 모두 **그래프 아래 타임바 + 재생**을 씁니다.
2. **고립 사건을 정리한다.** 현재 화면의 가장 큰 잡음은 연결 없는 사건 격자입니다. 별도 영역으로 모으거나 “연결 없는 사건 N건”으로 묶습니다.
3. **포커스 모드를 명시적으로 만든다.** 선택한 기업의 1~2홉만 남기고 “전체로 돌아가기”를 두는 방식(Palantir Quiver·Neo4j Bloom·Kumu)입니다. 지금의 “선택 관계만 남기기”를 제품 기능으로 끌어올리는 것입니다.
4. **근거를 그래프 위에 올린다.** 줍의 차별점은 모든 관계에 원문 근거가 있다는 점입니다. 노드 모서리 배지(근거 N건)와, 패널에서 인용을 고르면 해당 간선이 강조되는 연동(Ogma·Kumu)이 후보입니다.
5. **간선 라벨은 절제한다.** 상용 도구는 선택·확대했을 때만 라벨을 보여주고, 평행선은 곡선으로 분리합니다(Linkurious). 줍도 이미 확대 수준별로 숨기고 있어 규칙만 다듬으면 됩니다.

> **데이터 주의:** 현재 실제 기사 저장본의 사건 언급 32개 중 발생 시각이 있는 것은 11개이고, 모두 2026-09-14~17에 몰려 있습니다. 기사 발행 시각은 31건 모두 있습니다. 타임바를 넣으려면 “사건 발생 시각”과 “보도 시각” 중 무엇을 축으로 쓸지 먼저 정해야 합니다. 지금 데이터로는 4일치라 재생 효과가 약합니다.

## 그림으로 보기

### 1. 그래프 + 시간축

| | |
|---|---|
| ![AI Supply Chain: 월별 재생되는 공급망 그래프](img/aisupplychain-home.png) | ![yFiles Fraud Detection: 하단 히스토그램 타임라인과 기간 선택](img/pattern-yworks-fraud-detection.png) |
| **AI Supply Chain** — 하단 슬라이더로 월별 재생, 좌측 빠른 검색 | **yFiles Fraud Detection** — 하단 막대 타임라인으로 기간을 고르면 그래프가 바뀜 |
| ![Cosmograph: 좌측 히스토그램 필터와 하단 연도 브러시](img/cosmograph.png) | ![yFiles Event Timeline: 엔티티별 레인과 시각 축](img/pattern-yworks-event-timeline.png) |
| **Cosmograph**(공식 이미지) — 좌측 히스토그램 필터, 하단 전체 폭 연도 브러시 | **yFiles Event Timeline** — 기업을 레인, 사건을 시각 위치로 놓는 방식. 줍의 사건–기업 구조와 같은 모양 |
| ![KronoGraph](img/pattern-kronograph.png) | ![AI Supply Chain 액터 검색: 목록/타임라인 전환](img/aisupplychain-actor.png) |
| **KronoGraph** — 타임라인 전용 SDK | **AI Supply Chain 기업 검색** — 관계 목록과 월별 막대, 관계 유형 태그 |

### 2. 포커스·필터·인스펙터 배치

| | |
|---|---|
| ![Linkurious Explorer: 곡선 간선과 노드/간선 필터](img/linkurious.png) | ![i2 Analyst's Notebook](img/i2-anb.png) |
| **Linkurious**(공식 이미지) — 곡선 간선으로 평행선 분리, NODES/EDGES 필터와 개수 | **i2 Analyst's Notebook**(공식 이미지) — 그래프·표·타임라인을 한 화면에 |
| ![Palantir Quiver 의존 관계 보기](img/palantir-focus-mode.png) | ![Palantir Quiver 압축 노드](img/palantir-compact-nodes.png) |
| **Palantir Quiver** — 선택 노드의 위아래 연결만 남기는 모드와 “나가기” 버튼 | **Palantir Quiver** — 제목·식별자·유형만 담은 압축 노드 |
| ![yFiles Knowledge Graph](img/pattern-yworks-knowledge-graph.png) | ![Kumu 관계 지도](img/kumu.jpg) |
| **yFiles Knowledge Graph** — 클러스터 색, 이웃 뷰, 고립 노드 같은 문제 탐지 패널 | **Kumu**(공식 이미지) — 왼쪽 서사 패널, 오른쪽 지도. 간선은 흐리게, 노드만 채도 |

### 3. 노드 표현

| | |
|---|---|
| ![Ogma 노드 배지](img/pattern-ogma-badge.png) | ![Sayari 링 배지 노드](img/sayari.png) |
| **Ogma** — 노드 네 모서리 배지(고정·확대 크기) | **Sayari**(공식 이미지) — 중심 기업과 주변 기업, 개수 배지 |
| ![Ogma 클러스터 + 도넛](img/pattern-ogma-cluster-donut.png) | ![Ogma 다크 테마](img/pattern-ogma-theme-dark.png) |
| **Ogma** — 클러스터 배경 도형 + 비율 도넛 | **Ogma** 다크 테마 — 노드 테두리·간선 윤곽으로 대비 확보 |
| ![CI starburst: 리프 노드를 묶는 콤보](img/pattern-ci-starburst.png) | ![KeyLines 콤보](img/keylines.png) |
| **Cambridge Intelligence** — 허브에 매달린 리프를 묶어 과밀 해소 | **KeyLines**(공식 이미지) — 콤보로 묶은 두 무리 |

### 4. 서사·편집형

| | |
|---|---|
| ![LittleSis Oligrapher: 단계별 설명과 지도](img/littlesis-oligrapher.png) | ![The Pudding: 시간 순 계보 그래프](img/pudding-network.png) |
| **LittleSis Oligrapher** — 오른쪽 이야기 단계(이전/다음)에 맞춰 지도 강조가 바뀜. 브리핑과 결합할 만한 형식 | **The Pudding** — 연도 축을 따라 내려오는 계보. 사건 흐름(후속 사건) 표현 참고 |
| ![CI UX 가이드: 기본 스타일 vs 다듬은 스타일](img/pattern-ci-ux-guide.png) | ![G6 타임바 데모](img/pattern-g6-timebar.png) |
| **Cambridge Intelligence UX 가이드** — 같은 데이터의 기본 스타일과 다듬은 스타일 비교 | **AntV G6 Timebar** — 타임바 구현 예시(시간 모드) |

### 5. 피해야 할 모습

| | |
|---|---|
| ![Graph Commons 헤어볼](img/graphcommons-graph.png) | ![fcose 그룹 배치](img/pattern-cytoscape-fcose.png) |
| **Graph Commons** — 수백 노드를 한 화면에 그리면 라벨이 읽히지 않는 헤어볼이 됩니다. 줍이 노드 수백 개로 커질 때의 경고 사례 | **cytoscape-fcose 그룹 배치 데모** — 줍이 이미 쓰는 레이아웃에서 그룹(콤파운드) 노드가 가능하다는 참고 |

## 줍에 가져올 후보 (우선순위 제안)

`[추론]` 두 문서의 추천을 합쳐 현재 코드(Cytoscape.js)와 데이터 기준으로 정리했습니다. 난이도는 대략적인 추정입니다.

| 순서 | 후보 | 효과 | 난이도 | 필요한 것 |
|:--:|---|---|:--:|---|
| 1 | 고립 사건 영역 분리 + “연결 없는 사건 N건” 묶음 | 첫 화면 잡음 제거 | 중 | 없음(차수 계산) |
| 2 | 명시적 포커스 모드(1~2홉, 나가기 버튼) | 기업 중심 탐색을 질문 도구로 | 중 | 없음 |
| 3 | 노드 배지(근거 N건) + 인용↔간선 동기 강조 | 줍의 차별점(근거)을 그래프에서 바로 보임 | 중 | 없음(근거 매핑 있음) |
| 4 | 간선 라벨 규칙 정리, 평행선 곡선화 | 겹침 감소 | 하 | 없음 |
| 5 | 하단 타임바 + 재생 | “언제”라는 축 추가 | 중~상 | 시간 기준 결정, 데이터 기간 확대 |
| 6 | 두 기업 사이 경로 강조 | “왜 엮였나”에 직접 답함 | 중 | 없음(Cytoscape 내장 알고리즘) |
| 7 | 미니맵 | 수백 노드 대비 | 하 | 없음 |
| 8 | 브리핑을 단계별 서사 + 지도 강조로(LittleSis형) | 브리핑과 그래프 결합 | 중 | 브리핑 편성 규칙 |

라이브러리 교체는 필요 없다는 결론입니다. 위 후보는 모두 Cytoscape.js 기본 기능이나 확장(navigator·expand-collapse·bubblesets 등)으로 가능합니다. 간선 번들링만 Cytoscape에서 지원되지 않습니다(자세한 표: [patterns.md §6](patterns.md)).

## 한계

- 조사 담당 에이전트에게 브라우저가 없어 캡처는 별도로 직접 했습니다. 로그인·유료 제품(Bloomberg SPLC, Crunchbase, Maltego, Arkham 플랫폼 본체, Neo4j Bloom 등)은 화면을 보지 못했고 문서·공식 이미지로만 확인했습니다.
- 공식 이미지(표에 “공식 이미지” 표기)는 마케팅용이라 실제 제품 화면과 다를 수 있습니다.
- 공개 페이지 중 쿠키·면책 창이나 마케팅 상단만 찍혀 그래프가 보이지 않은 17곳(ICIJ, GDELT, Litmaps, Tom Sawyer, Gephi Lite 등)은 캡처를 버리고 본문 링크만 남겼습니다.
- `products.md`의 Cosmograph 공개 링크는 조사 시점과 다른 데이터(토론토 가로수 지도)를 보여줍니다. 문서의 타임라인·히스토그램 설명은 공식 이미지 기준입니다.
