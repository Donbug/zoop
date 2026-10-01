# 줍(Zoop) 그래프 중심 화면 레퍼런스 — 실제 제품 조사

| 항목 | 내용 |
|:--|:--|
| 작성일 | 2026-09-30 |
| 목적 | 관계 그래프를 **주 화면**으로 쓰는 실제 제품 20종(실질 근거 확보 18종)에서 줍 v3에 직접 이식 가능한 레이아웃·노드/간선 표현·탐색 상호작용·패널 구성·타임라인 결합·모바일 처리를 추출 |
| 선행 문서 | `../design-ux-research.md` §4(그래프 UX 일반론 — Bloom 씬 조작, Kumu focus, Obsidian 전역/로컬, Graphistry 성능), `../tds-seed-reference.md`, `../../design/design-direction.md` |
| 중복 회피 | 위 문서가 이미 다룬 **Bloom 씬 조작 목록·Kumu focus 문법·Obsidian 전역/로컬 분리·Cytoscape/Sigma/G6 라이브러리 비교**는 반복하지 않는다. 이 문서는 **실제 제품 화면에서 관찰되는 구체적 구성**에 집중 |
| 표기 | 사실(출처 확인) / `[추론]`(원문에 없는 해석) / `[미확인]`(근거 확보 실패) |

## 0. 방법과 한계 (먼저 읽을 것)

### 0.1 수집 방법

1차 출처(제품 공식 페이지, 공식 문서, 공식 문서에 첨부된 UI 스크린샷)를 직접 열람했다. 검색 결과 요약은 후보 발견용으로만 쓰고, **인용한 사실은 모두 해당 URL 본문에서 직접 확인**했다.

### 0.2 캡처에 대한 제약 (중요)

이 조사에 배정된 에이전트에는 **브라우저 도구가 마운트되어 있지 않다**. 확인한 사실:

- 마운트된 도구 장치는 `context7`·`github` MCP뿐이며, `xd://browser`·`xd://eval`·`xd://computer`·`xd://bash`는 모두 "No such tool"으로 거부된다.
- `read`의 `:img` 선택자는 **로컬 `.svg`만** 래스터화한다(`omp://tools/read.md`). 라이브 URL을 PNG로 렌더링하는 경로가 없다.
- `write`는 텍스트 전용이다. base64 PNG를 넘겨도 **96바이트 = base64 문자열 길이 그대로** 기록되는 것을 실측으로 확인했다(디코딩되지 않음).

따라서 **PNG 파일 생성은 이 에이전트의 작업 범위 밖**이다. 대신:

- 본문에 **공식 이미지 URL**을 그대로 기록하고,
- 그중 상당수는 `read <이미지URL>`로 **실제로 디코딩해 눈으로 확인**했다(아래 각 항목의 `공식 이미지 확인: 확인` 표시는 이 경로를 뜻한다 — 검색 스니펫이 아니라 이미지 자체를 본 것),
- Main이 저장할 파일명을 `img/<slug>.png`로 미리 적어 두고, 문서 끝 `## 캡처 대상` 표에 로그인 없이 열리는 URL과 봐야 할 화면 부분을 정리했다.

### 0.3 접근 실패 목록

| 대상 | 상태 | 처리 |
|:--|:--|:--|
| Bloomberg SPLC 공식 페이지 | HTTP 403 | `[미확인]` — §1.2에서 제품 존재·성격만 인용하고 UI는 서술하지 않음 |
| Crunchbase 관계 그래프 | 로그인/JS 렌더 | `[미확인]` — 엔티티 프로필만 공개, 그래프 뷰 근거 확보 실패 |
| Connected Papers | JS 렌더(본문 0줄) | `[미확인]` — §3.5에서 보류로만 기록 |
| Maltego 제품 페이지 | HTTP 404(마케팅 사이트) | 공식 **문서**(docs.maltego.com)로 대체 |
| OpenSanctions 홈 | RSS 피드로 리다이렉트 | 공식 **문서**(opensanctions.org/docs)로 대체 |
| Graph Commons 개별 그래프 뷰 | JS 렌더 | 커버 이미지(정적 PNG)로 시각 확인 |
| `aisupplychains.org/network_map` | HTTP 404 | `/search_actor`·`/project`로 대체 |

---

## 1. 금융·기업 관계 그래프

### 1.1 Sayari Graph — 소유·공급망 다단계 추적

- **무엇인가**: 제재·무역 리스크용 상업 인텔리전스. 공식 페이지는 **1.5B+ 엔티티 / 250+ 관할권 / 11년** 규모의 상업 인텔리전스를 표방하며, "1차 문서 petabytes"에서 구축했다고 밝힌다([sayari.com](https://sayari.com/)).
- **그래프를 중심에 두는 방식**: 제품의 핵심 오브젝트가 **ownership chain(소유 체인)** 이다. 공식 페이지의 대조 예시는 Sayari AI가 `3-hop ownership chain`을 표시하고 `OFAC SDN / RU Company Registry / MT Trade Filings / AT Registry (incomplete)` **출처를 노드 그래프 형태로 병기**한다. 같은 예시는 신뢰도를 `Roughly Even Chance to Likely`처럼 **구간 확률로 표현하고 한계를 명시**한다(`Confidence limited by incomplete filing data. Recommend manual review…`) (같은 URL).
- 공식 이미지 URL: `https://sayari.com/wp-content/uploads/2026/08/sayari-risk-management-AI-solution-open-graph.png` (og:image). **공식 이미지 확인: 확인** — 실제 이미지는 중앙 인물 노드에서 8개 기업 노드가 **점선 간선으로 방사형 연결**된 구조이고, 각 기업 노드에 `1`, `12`, `7` 같은 **작은 카운트 배지**가 붙어 있다. 노드 색은 리스크 등급(적/주황)으로 구분된다.

![Sayari 소유 관계 그래프](img/sayari.png)

- **줍에 가져올 요소**
  - **출처 스택을 그래프와 같은 화면에 둔다**: 줍의 모든 간선에 원문 인용 근거가 있으므로, Sayari처럼 "이 관계는 3단계 너머" 같은 **추적 깊이 표시**와 **근거 문서 출처 목록**을 같은 패널에 두면 FR-44(인용 근거)와 자연스럽게 결합한다.
  - **구간 확률 + 한계 문장**: `[추론]` 줍은 `일치/불일치/보류` 3종 배지를 쓰는데, Sayari의 "확신이 제한되는 이유를 함께 쓴다"는 서술 방식은 NFR-08(사실과 가설 구분)의 좋은 문장 모델이다. 단 줍은 확률을 쓰지 않으므로 **확률 표현은 채택하지 않고 "왜 보류인지" 서술만** 가져온다.
  - **노드 카운트 배지**: 기업 노드 옆 소형 숫자 배지(관계 수/문서 수)는 줍의 "고립 사건" 문제를 정면으로 다룬다 — 관계가 적은 노드도 **숫자로 상태를 말해준다**.
- **줍과 맞지 않는 점**: Sayari는 **유료·로그인 필수**라 공개 데모가 없다. 또 소유(ownership)라는 단일 관계 축이 중심이라, 사건·기업·사건-사건이 뒤섞인 줍의 이종(heterogeneous) 그래프보다 관계 의미가 단순하다. 두 노드를 잇는 간선이 항상 "소유"라 범례가 거의 필요 없다.

---

### 1.2 Bloomberg SPLC (Supply Chain) — `[미확인]`

- **무엇인가**: 블룸버그 터미널의 공급망 관계 데이터. **공식 페이지가 HTTP 403을 반환해 본문을 확인하지 못했다.**
- **처리**: 이 문서에서는 **제품이 존재한다는 사실과 조사 실패 사실만** 기록하고, UI·레이아웃·상호작용은 서술하지 않는다. 검색 스니펫 수준의 2차 서술로 화면을 추정하면 이 문서의 다른 항목과 신뢰도가 섞이므로 채택하지 않는다.
- **줍에 가져올 요소**: 확보 실패. `[미확인]`
- **대안**: 같은 문제 영역(기업 간 공급·소유 관계 + 뉴스 결합)은 §1.1 Sayari, §4.2 AI Supply Chain, §2.3 KeyLines의 supply chain 유즈케이스가 1차 근거로 커버한다.

---

### 1.3 LittleSis / Oligrapher — 무료 공개 권력 관계 지도

- **무엇인가**: "business and government에서 누가 누구를 아는가"를 담은 **무료·오픈소스** 데이터베이스. 공식 데이터 요약은 **관계 1,881,875건 / 인물 306,464 / 조직 136,865 / 인용 11,484,900건**([littlesis.org/database](https://littlesis.org/database)).
- **그래프가 주 화면인 지점**: 별도 제품 **Oligrapher**가 "networks of influence를 시각화하는 도구"로 제공되고, 공개 열람 가능한 지도들이 있다([littlesis.org/oligrapher](https://littlesis.org/oligrapher), 예: [Who's Banking on the Dakota Access Pipeline?](https://littlesis.org/oligrapher/1634-who-s-banking-on-the-dakota-access-pipeline)).
- **줍에 직접 쓸 수 있는 구조 — "관계를 문장으로 나열한 목록"**: `database` 페이지에서 각 엔티티 카드가
  `Key people [...] More »` / `Related orgs [...] More »` / `Key affiliations [...] More »` / `Related people [...] More »`
  형태로 **관계 유형별 묶음 + 5개 미리보기 + More »** 로 접혀 있다. `[추론]` 이는 줍의 "기업 → 직접 관련 사건 8건" 목록을 **관계 유형별로 그룹핑하고 5개만 보여준 뒤 More »** 로 접는 패턴의 직접 근거가 된다.
- **연혁·스케일 감각**: 11.4M 인용을 가진 DB를 **사용자 커뮤니티가 채우는** 구조이고, 데이터가 "정부 문서·뉴스 기사·기타 신뢰 출처"에서 온다고 명시한다(같은 URL). `[추론]` 줍도 근거(인용) 중심 모델이므로, **출처 유형을 데이터 모델 1급 시민으로 두는 설계**를 참고할 수 있다.
- **줍에 가져올 요소**: ① 관계 유형별 그룹 + `More »` 접기, ② 무료 공개 지도(로그인 없이 열람) 형태의 공유, ③ 인물/조직/위원회 같은 **엔티티 타입별 색·아이콘 분리**.
- **줍과 맞지 않는 점**: LittleSis의 관계는 **"누가 누구와 함께 일했는가"라는 정태적 소속·이해관계**다. 줍의 `INVOLVES`처럼 "이 사건에서 이 기업이 제출자였다"는 **사건 국면별 역할**과는 시간성·역할성이 다르다. 또 LittleSis에는 시세·주가 개념이 없고, 줍의 "내 종목" 같은 개인 맥락 축도 없다.

---

### 1.4 ICIJ Offshore Leaks Database — 공개 그래프의 표준 선례

- **무엇인가**: Pandora/Paradise/Panama Papers 등에서 나온 **810,000+ 역외 법인·재단·신탁**을 검색·탐색하는 공개 DB. 기록은 "80년 이상, 200개 이상 국가"를 아우른다([offshoreleaks.icij.org](https://offshoreleaks.icij.org/)).
- **결정적 사실 — 어떤 기술로 만들어졌는가**: 같은 페이지 하단이 **"Database powered by"로 Linkurious와 Neo4j 로고를 명시**한다. 즉 §2.1 Linkurious의 대표 공개 사례가 바로 이 DB이며, ICIJ CTO의 인용("가장 기술에 익숙하지 않은 조사자도 쓸 수 있을 만큼 직관적")도 Linkurious 페이지에 실려 있다([linkurious.com](https://linkurious.com/)).
- **줍에 가져올 요소**
  - **"검색 → 엔티티 → 관계 확장"의 3박자**: 대규모 그래프를 첫 화면에 통째로 그리지 않고 검색 진입으로 시작하는 구조. 줍도 고립 사건 31개를 한 번에 그리는 대신, **검색·선택을 진입점으로 삼는 것을 정당화**한다.
  - **국가·관할권 필터를 1급 축으로**: "British Virgin Islands | Entity Name LLC | Lima, Peru" 같은 조합 검색이 대표 예시로 제시된다. `[추론]` 줍의 "산업/관계유형/기간" 필터 축 설계에 대응.
  - **투명한 라이선스·인용 표기**: ODbL + CC BY-SA, "ICIJ를 인용할 것"을 명시. `[추론]` 줍이 외부 데이터를 붙일 때의 표기 관행 참고.
- **줍과 맞지 않는 점**: 역외 법인 그래프의 목적은 **은닉 구조 폭로**이므로, 기본값이 "의심스러운 것을 드러낸다"이다. 줍은 중립적 사건-기업 관계 지도이므로 **기본 강조색을 '의심'에 두면 안 된다**. 또 ICIJ는 조사자 대상 데스크톱 중심이고 모바일 그래프 UX는 이 문서에서 확인하지 못했다.

---

### 1.5 OpenSanctions / FollowTheMoney — 관계를 '엔티티'로 승격한 모델

- **무엇인가**: 제재·PEP 스크리닝용 개방 데이터 + 스키마. 데이터 모델로 **FollowTheMoney(FtM)** 를 쓴다([opensanctions.org/docs/entities/](https://www.opensanctions.org/docs/entities/)).
- **줍 데이터 모델에 직접 쓸 수 있는 핵심 — interstitial entity(간극 엔티티)**:
  공식 문서는 "두 엔티티 사이의 링크에는 그 자체의 속성이 있다"며, 사람이 회사를 소유하는 경우 **`Ownership` 엔티티를 별도로 만들어** `owner`, `asset`, `startDate`, `percentage`를 속성으로 갖게 한다고 설명한다. 그리고 명시적으로 경고한다: *"Thing에서 파생된 것은 노드, Interval에서 파생된 것은 간선이라고 단순화하면 **nasty bugs**가 생긴다."*
  `[추론]` **줍의 `INVOLVES`(사건→기업, 역할 요약)에 정확히 같은 문제가 있다.** "제출자/협력사"라는 역할과 "기술 제공"이라는 역할은 간선 속성이 아니라 **그 자체가 근거·시점·원문 인용을 가진 객체**다. 지금 간선에 역할 문자열을 넣고 있다면, 관계를 1급 엔티티로 승격하는 것을 검토할 근거가 1차 문서로 확보된다.
- **부가로 가져올 것**: ① `caption`(표시명)을 **알고리즘으로 하나 고르되 전체 이름 목록은 보존**하는 규칙(Latin 우선 → 다출처 우선 → Title-case 우선 → 편집거리 최소) — 같은 회사의 여러 표기 문제에 그대로 적용 가능. ② `first_seen` / `last_change` 타임스탬프를 엔티티 루트에 두어 **데이터 신선도를 UI에서 말할 수 있게** 한 구조.
- **줍과 맞지 않는 점**: FtM은 AML/제재 도메인 스키마이고, 그래프 **시각화 제품이 아니라 데이터 포맷**이다. 화면 레퍼런스가 아니라 모델 레퍼런스로만 쓴다. 또한 FtM은 "노드는 Thing, 간선은 Interval"로 단순화하면 안 된다고 스스로 경고할 만큼 학습 비용이 있다 — 줍 규모(수백 노드)에서 과잉 설계가 되지 않도록 **관계 엔티티가 필요한 유형만** 승격해야 한다.

---

## 2. 조사·인텔리전스 그래프

### 2.1 Linkurious Explorer — "좌측 필터 / 우측 레코드 / 중앙 그래프"의 완성형

- **무엇인가**: 그래프 기반 조사·탐지 플랫폼(2026년 기준 **Nuix가 인수 완료**). 자사 제품 페이지는 고객사로 ICIJ, Wells Fargo, Zurich, Airbus, NASA, Lockheed Martin, Cisco, Deloitte를 나열하고, 성과로 **"의심 사례 20% 더 탐지 / 조사 속도 최대 10x / 알림 처리 시간 평균 30% 감소"** 를 제시한다([linkurious.com](https://linkurious.com/)).
- **공식 이미지 확인: 확인** — `https://linkurious.com/images/uploads/2023/06/Product-Inage_Linkurious-Explorer_Header-e1687789496358.png` 를 디코딩해 실제 화면을 확인했다. 관찰한 구성:

![Linkurious Explorer 화면](img/linkurious.png)

| 영역 | 실제로 보이는 것 |
|:--|:--|
| **최좌측 아이콘 레일** | 세로 아이콘 바(레이어/목록/필터/정보) — 텍스트 없음 |
| **좌측 패널** | 상단 `FILTERS` 제목, `NODES` / `EDGES` **탭 분리**. 노드 타입별로 **`Address 4 / Bank account 4 / Organization …`처럼 항목명 + 개별 카운트**가 나열되고 각각 토글 가능 |
| **중앙 캔버스** | 이종 노드(사람·주소·계좌·회사)가 아이콘 원으로 배치. **선택된 노드는 파란 링 + 강조**, 나머지 경로는 하이라이트, 무관한 노드는 흐리게. 노드 아래 라벨은 **회색 라운드 박스**(길면 잘림) |
| **간선** | 곡선(곡률 있는 베지어)으로 그려져 **평행 간선이 겹치지 않음**. 방향 화살표 있음 |
| **우측 상단** | `Share…`, `Save`, 권한/아바타 — 협업·권한이 화면 크롬에 상시 노출 |

- **줍에 가져올 요소 (우선순위 높음)**
  1. **`NODES` / `EDGES` 탭 분리 필터 + 항목별 카운트**: 줍의 필터 칩(`기업 3`, `사건 31`, `직접 관련 17`, `사건 공유 1`)을 **노드/간선 두 탭**으로 나누고 각 항목에 **현재 그래프 기준 개수**를 붙이면, "무엇을 끄면 무엇이 사라지는지"가 즉시 예측된다. v3 캡처에서 칩에 숫자가 이미 있으므로 **탭 분리만 추가하면 되는 저비용 개선**이다.
  2. **곡선 간선**: 줍 v3 캡처는 기업↔사건 간선이 직선이고 간선 라벨이 **모든 간선에** 붙어 겹친다. Linkurious처럼 **곡률을 주고, 라벨은 선택된 간선/호버 시에만** 노출하는 것이 과밀 대응의 직접적 해법이다.
  3. **선택 노드 링 + 나머지 디밍**: 줍 v3는 이미 선택 시 이웃 강조를 한다(캡처에서 NVIDIA에 초록 헤일로 확인). Linkurious는 여기에 더해 **무관 노드를 완전히 죽이지 않고 회색으로 남겨 맥락을 유지**한다.
  4. **노드 라벨을 회색 박스로 통일**: 라벨 길이 편차로 레이아웃이 흔들리는 문제를 박스+말줄임으로 흡수.
- **줍과 맞지 않는 점**: Linkurious는 **엔터프라이즈 조사 도구**로 노드 타입이 10종 이상이고, 사용자가 그래프 스키마를 직접 이해해야 한다(필터에 `Address`, `Bank account`가 노출). 줍은 노드 2종(기업/사건)·간선 4종의 **의도적으로 좁은 스키마**이므로, 필터를 노드/간선 탭으로 나누되 **항목 수는 적게 유지**해야 한다. 또 좌측 아이콘 레일 + 우측 협업 크롬은 줍의 3단(목록|그래프|상세)과 충돌하므로 **패널 수를 늘리지 말고 기존 3단 안에서 흡수**해야 한다.

---

### 2.2 i2 Analyst's Notebook — 팔레트 기반 편집 + 좌측 패싯 + 우측 레코드

- **무엇인가**: 30년 이상 쓰인 링크 분석 표준. 공식 페이지는 **UK 경찰 100%, NATO 회원국 70%, 미국 상위 15개 경찰서 중 80%** 가 사용한다고 밝힌다([i2group.com](https://i2group.com/)). 제품 설명의 3기둥은 **"flexible data acquisition / pinpoint key insights(temporal, spatial and statistical views) / model supporting data"** — 즉 **시간·공간·통계 뷰를 그래프와 나란히** 둔다(같은 URL).
- **공식 이미지 확인: 확인** — `i2_ANB_Homepage_DarkMode 2.png` 를 디코딩해 실제 화면을 확인했다. 관찰한 것:

![i2 Analyst's Notebook 화면](img/i2-anb.png)

| 영역 | 실제로 보이는 것 |
|:--|:--|
| **상단 리본** | `Save / Export PDF / Chart setup / Undo / Redo / Quick Search / Visual Query / Expand / Expand with conditions / External searches / Import records / Paste from clipboard / Group / Ungroup / Packed layout / Export / Insert selection / Select all / Select attached / Refresh / Cut / Copy / Paste / Delete` — **동작을 평면 나열**, 계층 메뉴 최소화 |
| **좌측 패널 상단** | `Filter results by` — **`Entities 43/343` `Address 2/32` `Person 7/48` `Phone 25/145` `Vehicle ~/18` `Account …/18` `Organization …/7` `Event …/33` `Link type 502/1,445`** 형태의 **"현재 보이는 수 / 전체 수" 비율**. 상단에 **`5 active`** + `Choose` 링크 |
| **좌측 패널 하단** | `Palette` — `Entity types`를 **아이콘 + 라벨 그리드**(Address, Person, Phone, Armed, Charge, Financed, Vehicle, Cell, Call, Account, Service)로 제시. `Link types`는 *"Pick a link, select maybe two entities and click from the available link types"* 라는 **조작 안내 문장** |
| **우측 패널** | `Entities` / `chart` / `List` 탭. `Selected items only (31 items, 102 bytes)` 토글, 그 아래 **정렬 가능한 표**(Full Name, First Name, Last Name, Organization…)과 열별 필터 |
| **중앙 캔버스** | 짙은 남색 배경. **선택 노드에 파란 링 + `F`(focus) 배지**, 경로가 시안/파란색으로 밝게 살아나고 나머지는 어둡게. 노드 라벨은 작은 사각 박스 |

- **줍에 가져올 요소**
  1. **`n / N` 비율 필터** — 줍의 `기업 3` 같은 칩을 **`기업 3/3`, `사건 12/31`** 형태로 바꾸면 "필터로 몇 개가 숨겨졌는지"가 한눈에 보인다. **고립 사건이 많은 줍의 현재 데이터 상태를 정직하게 드러내는 가장 싼 방법.**
  2. **`Selected items only` 토글** — 그래프에서 선택한 것만 우측 표에 남기는 토글. 줍의 상세 패널에 `선택한 항목만` 토글을 두면 "기업 전체 목록 ↔ 현재 선택" 전환이 클릭 1회가 된다.
  3. **팔레트 + 조작 안내 문장** — 빈 캔버스나 첫 진입에서 `"노드를 고르고, 이웃을 클릭해 확장하세요"` 같은 **한 줄 조작 안내**를 캔버스 안에 둔다. i2는 이걸 `Link types` 영역에 상시 노출한다.
  4. **`Expand with conditions`** — "조건을 걸어 확장"이라는 개념을 줍의 "관계 1단계 펼치기"에 이식: 확장 시 **관계 유형·기간·최대 개수**를 함께 지정.
- **줍과 맞지 않는 점**: i2는 **전문 조사자가 수시간~수일 붙잡고 쓰는 도구**로, 상단 리본에 20개가 넘는 버튼이 평면 나열된다. 줍은 "출퇴근 5분" 소비를 목표로 하므로 **이 리본은 그대로 가져오면 실패**한다. 또 i2는 노드 타입이 매우 많아 팔레트가 필요하지만 줍은 2종이므로 팔레트 UI 자체가 불필요하다. **가져올 것은 필터 비율·선택 토글·조작 안내 문장·조건부 확장 4가지로 한정**해야 한다.

---

### 2.3 Cambridge Intelligence KeyLines — 콤보로 묶고, Figma 킷으로 먼저 설계

- **무엇인가**: JavaScript 그래프 시각화 SDK(라이선스: **애플리케이션 단위 유료**, 무료 평가판 제공). 백엔드 비종속으로 Neo4j·Neptune·Cosmos DB·TigerGraph·JanusGraph·Elastic·REST/GraphQL과 연동한다고 밝힌다([cambridge-intelligence.com/keylines](https://cambridge-intelligence.com/keylines/)).
- **과밀 대응 4기능(공식 페이지에 명시)**:
  1. **Combo decluttering** — "Group nodes to spot patterns without overwhelming the chart, then **drill down into underlying relationships**"
  2. **Insight-driven graph engine** — 중심성·순회 알고리즘으로 connectivity/data flow를 드러내고 **styling·sizing·foregrounding·filtering**으로 강조
  3. **Fully customizable styling** — 노드·콤보·링크·주석 전부 스타일 지정
  4. **Powerful layouts**
  (같은 URL)
- **디자인-개발 워크플로**: **Figma Design Kit**으로 "JavaScript를 한 줄도 쓰기 전에 그래프 인터페이스를 프로토타입"하고 디자이너-개발자를 조기에 정렬한다고 명시한다. 지원은 ISO 27001 프레임워크 하에 제공된다(같은 URL).
- **줍에 가져올 요소**
  - **콤보 = 줍의 "사건 클러스터"의 정확한 선례.** 요구사항의 "동일 이슈 사건 묶기"를 **드릴다운 가능한 그룹 노드**로 구현하는 방식이 상용 SDK에 표준 기능으로 존재한다는 근거가 된다. 줍은 `STRUCTURALLY_RELATED_TO`(공급·생산)로 이미 기업-기업 파생 관계가 있으므로, **클러스터 노드의 라벨을 관계 유형으로 명명**하면 의미가 자명해진다.
  - **`foregrounding` 개념**: 노드를 지우지 않고 **앞으로 끌어올리는** 강조. 줍의 디밍(opacity 0.25)보다 정보 손실이 적다.
- **줍과 맞지 않는 점**: **SDK(라이선스)** 이지 완성 제품 화면이 아니다. 줍은 Cytoscape.js를 이미 쓰고 있고, 콤보·포그라운딩은 Cytoscape 확장으로 상당 부분 구현 가능하다. `[추론]` 따라서 **기능 개념만 채택하고 도입은 하지 않는다.** 또 "Figma 킷으로 먼저" 방식은 팀에 Figma 라이선스와 핸드오프 규율을 요구한다 — 프로토타입 단계에서는 과하다.

---

### 2.4 Maltego Graph — 브라우저로 옮겨온 링크 분석, 지속적 그래프

- **무엇인가**: 엔티티 간 링크를 **transform**으로 확장해 나가는 조사 플랫폼. 제품군이 Maltego One 아래로 통합되어 있다(Graph(Browser) / Graph(Desktop) / Cases / Evidence / Monitor / Search / Data / Admin)([docs.maltego.com](https://docs.maltego.com/en/support/home)).
- **핵심 성격 변화**: 공식 문서는 Maltego Graph(Browser)를 *"**no need for installations, troubleshooting, or dealing with interruptions from unexpected updates**"* 라고 소개한다. 즉 **설치형 데스크톱 도구를 브라우저로 옮긴 것**이 제품의 셀링 포인트다([What is Maltego Graph (Browser)?](https://docs.maltego.com/en/support/solutions/articles/15000059530-what-is-maltego-graph-browser-)).
- **줍에 가져올 요소**
  - **"그래프는 세션 동안 계속 자라난다"는 전제**: Maltego의 사용 흐름은 노드를 놓고 → transform을 실행해 이웃을 붙이고 → 반복이다. `[추론]` 줍도 사건 노드를 선택해 "관련 기업 펼치기"를 반복하는 구조라면, **되돌리기(undo)와 '여기까지의 그래프 저장'** 이 1급 기능이어야 한다. Maltego가 **Cases / Evidence** 를 별도 제품으로 분리한 것은 이 요구의 방증이다.
  - **Browser 우선**: 설치 없이 링크로 공유되는 그래프라는 포지셔닝은 줍(웹 프로토타입)과 일치한다.
- **줍과 맞지 않는 점**: Maltego의 본질은 **transform(외부 데이터 소스 질의)** 이고, 그래프는 그 결과의 시각화다. 줍은 이미 서버가 관계를 계산해 주므로 **transform 개념이 필요 없다**. 또 Maltego는 엔티티가 도메인·이메일·IP·전화번호 등 수십 종이라 `Parts` 개념의 학습 곡선이 크고, 공개 데모 없이 무료 체험만 제공되어 화면을 1차 근거로 인용할 수 없다. 이 문서는 **문서 서술 범위에서만** 인용했다.

---

### 2.5 Palantir Foundry — 그래프 모드와 '의존성 뷰'라는 명시적 모드

- **무엇인가**: Foundry의 분석 앱. **Quiver**는 카드 기반 분석 도구이고 **canvas 모드 / graph 모드 2종**을 제공한다([Quiver Graph mode](https://palantir.com/docs/foundry/quiver/analysis-graph)).
- **줍에 가장 직접적으로 쓸 수 있는 문서화된 규칙 (전부 공식 문서에서 확인)**
  - **레이아웃 방향**: *"The graph uses a **left-to-right layout**, making it easy to follow the direction of your data."* — 방향성이 있는 그래프에 좌→우 레이아웃을 쓴다는 명시적 근거.
  - **컴팩트 노드**: 노드는 *title, identifier, type* 만 보여주는 compact 뷰. 이유를 문서가 밝힌다 — *"This compact layout **keeps the graph fast and responsive, even for large analyses**."*
  - **의존성 뷰(dependency view)**: *"In a large analysis, it can be difficult to trace how a specific card was created or which cards depend on it. A dependency view **narrows the graph to show only the selected card and its upstream and downstream dependencies**."* 진입은 노드 우클릭 → `View dependencies`, 복귀는 `Exit dependency view`.
  - **프리뷰 패널 + 핀**: 하단 전용 프리뷰 패널. **핀을 꽂아 다른 노드를 선택해도 유지**하고, **두 프리뷰를 좌우 분할로 나란히** 볼 수 있다.
  - **색 그룹**: *"assign colors to related nodes… **Color groups can be collapsed into a single node or hidden** to reduce clutter."*
  - **줌/팬 모드 분리**: `Panning mode` ↔ `Selection mode`를 토글, `Layout nodes`로 배치 리셋.
  - **그래프 네비게이션**: 좌하단에 **zoom in/out, zoom to fit all nodes, reset layout** 버튼.
- **줍에 가져올 요소 (매우 높음)**
  1. **`선택 노드 + 상·하류만 남기기` 모드** — 줍의 "선택 관계만 남기기"(v3 캡처 하단 컨트롤에 이미 존재)를 **명시적 모드 + 복귀 버튼**으로 격상. Palantir는 복귀 라벨을 `Exit dependency view`로 화면 좌상단에 상시 노출한다.
  2. **프리뷰 핀 + 2분할 비교** — 줍의 우측 패널(현재 선택 1개만)에 **핀 고정**과 **2개 나란히 비교**를 추가하면 "두 기업을 동시에 보기"가 가능해진다. 상세 패널 구조를 바꾸지 않고 얻을 수 있는 확장이다.
  3. **컴팩트 노드 + "성능"이라는 정당화** — 줍 v3 캡처의 사건 노드 라벨이 길게 잘리고 겹친다. Palantir는 **노드에 제목·식별자·타입만** 두고 상세는 프리뷰 패널로 보낸다. 줍의 사건 제목이 길면 **노드에는 짧은 라벨만, 전체 제목은 패널에서**.
  4. **좌하단 네비게이션 묶음** — v3 캡처는 좌하단에 `+ − ⤢ 홈로 순으로 정렬 선택 관계만 남기기`를 이미 배치했다. Palantir와 위치·구성이 사실상 동일하므로 **이 결정은 유지**하는 것이 좋다.
- **부가**: **Insight** 앱은 *"Build step-by-step analysis paths to filter objects, **traverse object links**, aggregate results"* 라는 **분석 경로(analysis path)** 를 제공하고, `Link` 단계로 "연결된 객체를 따라간다"고 설명한다([Insight overview](https://www.palantir.com/docs/foundry/insight/overview)). `[추론]` 줍의 "기업 A → 사건 → 기업 B" 경로 탐색에 **경로를 카드 리스트로 남기는** UI를 붙일 근거가 된다.
- **줍과 맞지 않는 점**: Quiver의 그래프는 **데이터 파이프라인 의존성 그래프**(카드 = 연산)로, 좌→우 DAG가 자연스럽다. 줍의 사건-기업 관계는 **방향은 있으나 순환이 가능**하므로 좌→우 강제 레이아웃은 부적합하다(`[추론]`). 또 Palantir 문서의 화면은 **Ontology·앱 빌더 지식 전제**가 깔려 있어, 줍 사용자(개인 투자자)에게 그대로 노출할 수 없다.

---

### 2.6 Neo4j Bloom — (선행 문서 보강) 이 문서에서 추가하는 것

- 선행 문서(`../design-ux-research.md` §4.1)가 Bloom의 **씬 조작**(Expand nodes, Select related, Dismiss, Reveal relationships, Group, Shortest Path, 레이아웃 5종, 미니맵, Presentation mode, 필터 회색 처리)을 이미 정리했다. **여기서는 그 목록에 없는 것만** 추가한다.
- Bloom의 UI 구성 요소가 공식 문서에서 **명시적 패널 목록**으로 제공된다: `Perspective drawer`, `Settings drawer`, **`Legend panel`**, `Search bar`, **`Card list`**, `Scene interactions` ([Visual tour](https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/)).
- **줍에 가져올 요소 (추가분)**
  - **`Card list`를 그래프와 병치**: Bloom은 그래프 씬과 **카드 리스트를 별도 패널**로 둔다. 줍 v3의 `그래프 / 목록` 토글과 같은 발상이며, Bloom은 이를 **토글이 아니라 두 패널의 병존**으로 처리한다. `[추론]` 넓은 화면에서는 토글보다 병치가 낫고, 좁은 화면에서만 토글.
  - **`Legend panel`을 독립 패널로**: 범례를 접이식이 아니라 **명시적 패널**로 승격. 줍 v3 캡처에는 범례가 보이지 않는데, 노드 2종 + 간선 4종이면 범례가 화면을 크게 잡지 않는다.
  - **패널을 `drawer`로 명명**: Bloom은 설정·퍼스펙티브를 "서랍"으로 부른다. 이름 자체가 "필요할 때 연다"를 규정한다.
- **줍과 맞지 않는 점**: Bloom은 **Perspective(스키마 기반 뷰 정의)** 를 사용자가 관리해야 하는 분석가 도구다. 줍은 관계 어휘가 4종으로 고정이므로 perspective 편집 UI가 불필요하다.

---

### 2.7 Arkham Intelligence — "네트워크 맵"을 제품의 1번 메시지로

- **무엇인가**: 블록체인 주소·엔티티를 실세계 인물/기관에 연결하는 인텔리전스 플랫폼. 공식 사이트의 4개 스크롤 섹션이 제품 주장을 순서대로 제시한다([info.arkm.com](https://info.arkm.com/)):
  1. **"See the people and companies behind blockchain activity"**
  2. **"Visualize anyone's blockchain activity — TRANSLATE RAW BLOCKCHAIN TRANSACTIONS INTO CLEAR NETWORK MAPS"**
  3. **"Get intelligence on the addresses, entities, or assets that are most important to you — ACCESS A SEARCHABLE DATABASE … AND FILTER THEIR TRANSACTIONS"**
  4. "Customize alerts for on chain activity"
- **marketplace 포지션**: 후원자로 Palantir 공동창업자 Joe Lonsdale(8VC), Tim Draper, Wintermute, GSR 등을 나열하고, 파트너로 CoinGecko·TradingView·Chainlink·Polygon·BNB Chain 등 거래소·체인을 배치한다(같은 URL).
- **줍에 가져올 요소**
  - **"원시 데이터 → 네트워크 맵"이라는 카피 구조**: Arkham은 **"raw transactions → clear network maps"** 라는 변환을 제품의 두 번째 메시지로 전면에 둔다. `[추론]` 줍의 대응 문장은 **"뉴스 문장 → 관계 지도"** 이며, 이 변환을 화면 진입부에서 한 번 말해주는 것이 그래프 해석 부담을 낮춘다. 특히 줍은 "모든 관계에 원문 인용 근거"라는 차별점이 있으므로 **"원시 뉴스 → 근거 있는 관계 지도"** 로 더 강하게 말할 수 있다.
  - **검색을 그래프의 전제로**: Arkham은 "searchable database + filter transactions"를 네트워크 맵과 **별개 섹션**으로 제시한다. 그래프를 탐색의 유일한 진입점으로 두지 않는다.
- **줍과 맞지 않는 점**: Arkham의 그래프는 **금액·흐름 방향·시간이 간선에 실린다**(트랜잭션). 줍의 간선에는 금액도 방향성 있는 흐름도 없고 "역할 요약 + 인용"만 있다. `[추론]` 따라서 **간선 굵기로 금액을 인코딩하는 Arkham식 표현은 줍에 의미가 없다.** 또 Arkham은 **로그인 필수 플랫폼**(platform.arkhamintelligence.com)이라 공개 화면 캡처 대상이 아니다.

---

## 3. 지식·탐색 그래프

### 3.1 Kumu — 클러스터링과 "서사 패널 + 캔버스" 레이아웃

- **무엇인가**: "관계 지도" 제작·공유 도구. 정체성을 *"organize complex data into relationship maps"* 로 규정하고, 유즈케이스로 **stakeholder mapping / systems mapping / social network mapping / community asset mapping / concept mapping** 을 제시한다([kumu.io](https://kumu.io/)).
- **공식 이미지 확인: 확인** — `first-look-madison-*.jpg` 를 디코딩해 실제 화면을 확인했다. 관찰한 것:

![Kumu 매디슨 이니셔티브 관계 지도](img/kumu.jpg)

| 영역 | 실제로 보이는 것 |
|:--|:--|
| **좌측 오버레이** | 흰 카드가 캔버스 **위에 겹쳐진 서사 패널**(제목 + 본문 단락). 그래프를 가리지 않고 나란히 읽힌다 |
| **캔버스** | 노드는 **원 + 라벨**, 크기가 중요도에 따라 다름. 간선은 **점선(역관계) / 실선(직접관계) 두 종류** |
| **범례(좌하단)** | 노드 유형 색 + **간선 스타일 2종의 의미**(`Inverse Relationship`=점선, `Direct Relationship`=실선)를 함께 표기 |
| **캔버스 컨트롤** | 좌상단 검색, 우상단 `+ − ⤢`(줌·핏), 하단 중앙 초록 `+`(추가), 우하단 아이콘 묶음(노트/채팅/공유/더보기) |
| **전체 톤** | 배경 흰색, 간선 저대비 회색, 노드만 채도 — **"그래프가 글보다 시끄럽지 않다"** |

- **클러스터링 규범(공식 문서, 줍에 매우 유용)**: Kumu 클러스터링은 **필드 값을 새 엘리먼트로 만들어 연결**한다([Cluster 가이드](https://docs.kumu.io/guides/clustering.md)). 문서가 제시하는 규칙:
  - `cluster: "Field"` — 해당 필드에 값이 있는 모든 엘리먼트를 클러스터
  - `cluster: selector by "Field" as "Type"` — **selector로 범위 제한**, **클러스터 노드의 타입 지정**
  - **여러 규칙을 쉼표로 결합**, 그리고 **타입을 같게 맞추면 Kumu가 기존 엘리먼트를 재사용**해 하나의 노드로 합친다 — 문서의 예: `Skills offered`와 `Skills needed`를 각각 클러스터하되 타입을 `Skill`로 통일하면 스킬당 노드가 1개만 생긴다.
  - **"Connect by" 드롭다운**으로 기본 편집기에서 선택, 필드별로 클러스터링 금지 토글도 가능.
- **줍에 가져올 요소 (최우선)**
  1. **"관계가 없는 데이터 → 관계 지도"라는 정확히 같은 문제 설정**: Kumu 문서는 클러스터링의 가치를 *"you probably have a spreadsheet full of contacts… If you imported this directly into Kumu, you'd end up with a map like this: *(관계 없는 노드가 흩어진 그림)* — **Not that eye opening, right?**"* 라고 설명한다. **줍의 v3 화면이 정확히 이 상태다** — 고립 사건 11개가 관계 없이 격자로 흩어져 있다. Kumu의 해법은 명확하다: **필드 값을 노드로 승격해 연결한다.**
  2. **줍에 그대로 적용**: 사건을 **`역할(제출자/협력사/기술 제공사)`·`산업`·`출처 매체`·`월`** 로 클러스터하면, 고립 사건들이 **클러스터 노드에 붙으면서 그래프에 편입**된다. Kumu의 "타입 통일로 노드 재사용" 규칙은 줍의 **"같은 산업" 노드가 여러 클러스터 규칙에서 중복 생성되지 않게** 하는 정확한 근거다.
  3. **서사 패널 오버레이**: 데스크톱에서 그래프 옆에 **긴 설명 텍스트를 카드로 겹쳐** 둔다. 줍의 좌측 "내 종목" 열을 로그인 전에는 **설명/온보딩 카드**로 쓰는 변형이 가능하다. (v3 캡처에서 좌측 열은 비회원 로그인 CTA만 있다.)
  4. **간선 스타일로 의미 구분**: 점선=파생/간접, 실선=직접. 줍의 `INVOLVES`(직접) vs `SHARES_ISSUE`/`STRUCTURALLY_RELATED_TO`(파생) 구분에 **색이 아닌 선 스타일**을 병용하면 KWCAG 2.2 5.4.1(색에 무관한 인식)과도 맞는다.
- **줍과 맞지 않는 점**: Kumu의 클러스터 노드는 **데이터 필드에서 기계적으로 생성**되므로 "A사와 B사가 같은 이슈를 공유한다" 같은 **의미 있는 파생 관계와 무관하게** 만들어질 수 있다. 줍은 `SHARES_ISSUE`처럼 **근거 있는 파생 관계**를 이미 계산하므로, 클러스터를 남발하면 근거 없는 노드가 생겨 "모든 관계에 원문 근거" 원칙이 흐려진다. `[추론]` **클러스터는 시각적 그룹핑(테두리/배경 영역)으로만 하고, 클러스터 노드를 실제 노드로 만들 때는 근거 유무를 검사**해야 한다. 또 Kumu의 코드 기반 설정(`@settings`)은 줍의 UI 조작 모델과 맞지 않는다.

---

### 3.2 Graph Commons — 공개 그래프 갤러리와 AI 생성

- **무엇인가**: "관계를 지도화"하는 도구. 2026년 기준 **그래프 생성 AI**가 전면에 있다. 공식 페이지는 *"Describe, paste, or upload → AI structures it into a live network"*, *"Every node and edge it creates is **fully editable**"* 라고 하고, 요금제는 Starter(무제한 public graphs + 100 AI 크레딧) / Professional / Organization으로 안내한다([graphcommons.com](https://graphcommons.com/)).
- **주목할 포지셔닝 문장**: 자사 비교표에서 경쟁자를 3분류한다 —
  - *AI assistants (ChatGPT·Claude·Gemini)*: "Fast answers and summaries. **Hard to trace, compare, or measure the relationships behind them**."
  - *Whiteboards (Miro·FigJam·Excalidraw)*: "Quick sketches … Hard to analyze, refine, or reuse"
  - *Graph tools (Kumu·Linkurious·Polinode)*: "Structured graph exploration. Powerful **once data is prepared**, but slower to iterate from raw ideas."
  (같은 URL)
- **공개 그래프 커버 확인: 확인** — `Network of Unicorns and Investors` 커버(`https://graphcommons.com/files/graphs/74626001-1af0-437a-84e0-271165125847/cover.png`)를 디코딩해 확인했다. **어두운 배경에 수백 노드가 방사형으로 뻗은 전형적 헤어볼(hairball)** 이며, 가장자리 라벨은 읽을 수 없다.

![Graph Commons 유니콘·투자자 네트워크(인터랙티브 뷰 캡처, 2026-09-30)](img/graphcommons-graph.png)

위 이미지는 커버가 아니라 같은 그래프의 공개 인터랙티브 뷰를 직접 캡처한 것이다. 밝은 배경이지만 수백 노드 헤어볼이라는 관찰은 같다.

- **줍에 가져올 요소**
  - **헤어볼의 반면교사**: 위 커버는 **줍이 되지 말아야 할 화면**의 실물 증거다. 노드 수가 늘 때 **라벨이 가장자리에서 읽히지 않고, 색이 의미를 전달하지 못한다**. `[추론]` 줍이 수백 노드로 갈 때 "전체를 한 화면에" 그리는 기본값을 유지하면 같은 결과가 된다 — 이 이미지를 리뷰 자료로 쓰는 것이 좋다.
  - **"Public / Private"을 인지된 제품 속성으로**: 요금제 설명이 곧 권한 설명이다("Starter graphs are public — anyone with the link can view them"). `[추론]` 줍이 공유 기능을 넣을 때 **공개 범위를 요금제가 아니라 노드/간선 단위로** 말할 수 있는지 검토.
  - **AI 생성물의 편집 가능성 명시**: *"Every node, edge, and attribute is fully editable… merge entities, rewrite relationships"*. `[추론]` 줍의 AI 요약도 "수정 불가한 판정"이 아니라 **사용자가 근거를 확인하고 되돌릴 수 있는 것**으로 제시하는 편이 NFR-08과 정합.
- **줍과 맞지 않는 점**: Graph Commons의 그래프는 **사용자가 만든 주관적 지도**이고 출처 검증 개념이 없다. 줍은 반대로 **모든 관계에 원문 근거**가 있는 것이 핵심이므로, "AI가 노드를 자유롭게 추가"하는 모델은 채택할 수 없다. 또 이 제품의 상업적 무게중심이 AI 그래프 생성으로 이동해, 기존 그래프 탐색 UX 관련 1차 문서는 상대적으로 얇다.

---

### 3.3 Cosmograph — 필터 히스토그램 + 하단 타임라인 브러시

- **무엇인가**: 대규모 네트워크·임베딩을 **서버 없이 로컬에서** 시각화·분석하는 도구. DuckDB 기반이며 React/TypeScript 라이브러리로 자기 앱에 내장 가능하다([cosmograph.app](https://cosmograph.app/)).
- **공식 이미지 확인: 확인** — `main-page-screen.47dae50f.png` 를 디코딩해 실제 화면을 확인했다. 관찰한 것:

![Cosmograph 화면](img/cosmograph.png)

| 영역 | 실제로 보이는 것 |
|:--|:--|
| **좌측 필터 패널** | `FILTERS` 아래 `POINTS` 섹션. `+ Add filter` 드롭다운, 그 아래 **`micro_cluster` 히스토그램(1 ~ 4.5K 축, 값 분포 막대)**, **`size (n_cits)` 히스토그램(300 ~ 138K)**, **`color (main_field)` 범례 = 범주명 + 개수** (`Biomedical and health sciences 165K`, `Physical sciences and engineering 78K`, `Social sciences and humanities 43K`, `Life and earth sciences 35K`, `Mathematics and computer science 32K`) |
| | 정렬 토글 `↑ABC ↓123`, `reset selection` 링크, 하단에 `LINKS` 섹션(접힘) |
| **상단 바** | `CG` 로고, `Clone`, `Share…`, 중앙에 문서명 `Research`, 우측에 노트 아이콘 + 파란 `Save` 버튼 |
| **캔버스 좌상단** | **`Fit view` / `Select area` 모드 토글** |
| **캔버스** | 어두운 배경 + 밝은 점 구름. **일부 노드만 라벨 표시**(예: `SARS-CoV-2 Cell Entry Depends on ACE2 and TMP…`, `Clinical features of patients infected with 2019 nove…`) — 전부 표시하지 않음 |
| **캔버스 우하단** | `308 [slider] 1.5K` 형태의 **n_cits 범위 컨트롤** + `and less / and more` 안내 + `visualized by Cosmograph.app` 워터마크 |
| **캔버스 하단 전체 폭** | **연도 축 타임라인 브러시**: `1999 2002 2005 2007 2010 2013 2015 2018 2021` 눈금 위에 선택 구간을 드래그하는 바. 좌측에 ▶ 재생 버튼 |

- **공식 페이지가 명시하는 기능 목록**: *Timeline("See your dataset evolving over time with the help of the Timeline")*, *Powerful filtering & search("Filter your data through **histograms**, strip away noise")*, *Time dimension*, *Collaboration*, *Graph sharing* (같은 URL).
- **줍에 가져올 요소 (우선순위 매우 높음)**
  1. **히스토그램 = 숫자 필터의 시각화.** 줍에서 "관련 사건 수", "근거 문서 수" 같은 **정량 축을 히스토그램으로 필터링**하면, "고립 사건만 보기"(관계 0) 같은 조건이 슬라이더 한 번이 된다. `[추론]` 이는 §3.1의 고립 노드 문제에 **그래프를 건드리지 않는 해법**을 준다.
  2. **하단 타임라인 브러시 + 재생**: Cosmograph는 타임라인을 **캔버스 하단 전체 폭에 고정**한다. 줍 v3에는 시간 축이 없고 상세 패널에 `발생 시각 미상`이라는 항목만 있다. **캔버스 하단에 기간 브러시를 두고, 재생 버튼으로 사건이 시간순으로 나타나게** 하는 것은 v3에 없는 가장 큰 기능 공백을 채운다.
  3. **라벨을 전부 그리지 않는다**: 화면에 보이는 노드 중 **일부만** 라벨을 달고, 나머지는 점으로 둔다.
  4. **범주 범례에 개수 표기**: `Biomedical and health sciences 165K` 처럼 **색 + 이름 + 개수**. 줍의 범례에 `사건 31 / 기업 3`을 붙이는 것과 같은 형태(§2.2의 `n/N` 규칙과 결합 가능).
  5. **`Fit view` / `Select area` 모드 토글**: 캔버스에서 "화면 맞추기"와 "영역 선택"이 **배타적 모드**임을 명시해, 드래그가 패닝인지 선택인지 혼동을 없앤다. (§2.5 Palantir의 `Panning mode`/`Selection mode`와 동일한 해법 — **두 상용 제품이 독립적으로 같은 해법을 쓴다는 것은 패턴의 강도**를 보여준다.)
- **줍과 맞지 않는 점**: Cosmograph의 대상은 **수십만 노드의 밀집 점 구름**이고, 개별 노드의 "이름"보다 **분포와 클러스터**가 정보다. 줍은 노드 수백 개 규모에서 **개별 사건·기업 이름이 읽히는 것**이 목표이므로, 점 구름 표현은 부적합하다. 또 Cosmograph의 워터마크·`Clone`·`Save` 같은 상단 크롬은 줍의 화면 구조와 무관하다. **가져올 것은 ① 히스토그램 필터 ② 하단 타임라인 브러시+재생 ③ 선택적 라벨 ④ 모드 토글 4가지**로 한정해야 한다.

---

### 3.4 Litmaps — 노드 배치 자체가 정보인 그래프 (날짜 × 인용)

- **무엇인가**: 문헌 리뷰 가속 도구. **270M+ 논문** 카탈로그에서 "citation과 reference를 사용해 연결 기반으로" 검색하고, 결과를 시각화한다([litmaps.com/features](https://www.litmaps.com/features)).
- **핵심 차별점 — 좌표가 데이터다**: 공식 사용자 인용에서 드러난다. 한 사용자는 *"having research articles laid out in the **date vs cite graph format** is much more approachable than looking at a standard database interface… giving me the connections between articles **spaced out visually**. This helps me orientate **where a paper is in the history of a field**"* 라고 말한다 — 여기서 *"date vs cite"* 라는 표현은 **그래프의 두 축이 날짜와 인용수**임을 시사한다([litmaps.com](https://www.litmaps.com/) 사용자 후기 섹션).
- **부가 사실**: 기능 페이지는 *"dynamically changing how papers are mapped using various traditional and unique measures"* 라고 하여 **여러 지표로 배치를 바꿀 수 있음**을 밝힌다. 검색·시각화·공유·모니터(신규 논문 자동 메일)의 4기능 구조이고, 150개국·350,000+ 연구자가 쓴다고 주장한다.
- **줍에 가져올 요소 (줍의 가장 큰 구조적 결손을 건드린다)**
  - **레이아웃을 힘(force)이 아니라 축으로**: 줍 v3는 fcose 힘 기반 레이아웃이라 **노드의 위치에 의미가 없다**. Litmaps처럼 **X축 = 시간, Y축 = 관계 수(또는 근거 문서 수)** 의 **결정적 좌표 배치**로 바꾸면, "언제 일어난 일인지"와 "얼마나 많이 연결됐는지"가 **위치만으로** 읽힌다. 이는 Cytoscape.js의 `preset` 레이아웃으로 구현 가능하다(선행 문서 §4.4에 preset 레이아웃이 이미 나열되어 있다).
  - **이 모드의 직접적 효과**: 줍의 고립 사건은 **아래쪽 띠에 시간순으로 늘어서고**, 활발한 사건은 **위쪽에 모인다** → §3.1 Kumu 클러스터링과 §3.3 히스토그램이 각각 다루던 문제를 **하나의 레이아웃 변경**으로 푼다. `[추론]` v3에서 고립 사건 11개가 격자로 흩어진 문제는 힘 레이아웃에서 상호작용이 없으면 필연적으로 발생하지만, **축 기반 배치에서는 애초에 발생하지 않는다.**
  - **"필드를 모른 채 보는" 사용자 배려**: 인용된 사용자(난독증 연구자)는 *"표준 데이터베이스 인터페이스보다 접근하기 쉽다"* 고 말한다. `[추론]` 줍의 초보 투자자 타깃과 같은 논리다.
- **줍과 맞지 않는 점**: Litmaps의 관계는 **인용(단방향, 시간상 과거로만)** 이라 DAG가 자연스럽고 좌표 배치가 안정적이다. 사건→기업 `INVOLVES`도 방향은 있지만 **기업↔기업 파생, 사건↔사건 `FOLLOWS`** 가 섞이면 시간 단조성이 깨진다. `[추론]` 따라서 **축 기반 배치는 "전체 그래프" 모드에만 적용하고, 선택 기업의 에고 네트워크에서는 힘 기반을 유지**하는 하이브리드가 필요하다. 또 시간 정보가 없는 노드(`발생 시각 미상`)의 x좌표 처리 규칙을 정해야 한다 — 미상 노드를 어디에 둘지가 곧 정보 설계다.

---

### 3.5 Connected Papers — `[미확인]`

- 공식 사이트(`https://www.connectedpapers.com/`)가 **JS 렌더링으로 본문 텍스트를 반환하지 않아**(메타 태그와 빈 본문만 수신) 화면 구조·상호작용을 1차 근거로 확인하지 못했다. og:image(`share-preview-img.png`)도 이미지 디코딩으로 확인하지 않았다.
- **처리**: `[미확인]`으로 두고 항목을 세우지 않는다. 문헌 그래프 영역은 §3.4 Litmaps와 §1.1 Sayari로 커버한다.
- **Main이 확인할 경우의 가설** `[추론]`: Connected Papers는 통상 **"prior works / derivative works"를 좌우로 배치한 2축 그래프**로 알려져 있어 §3.4와 같은 "좌표가 정보" 계열일 가능성이 높다. 캡처 대상에 넣어 확인할 가치가 있다.

---

## 4. 뉴스·이벤트 그래프

### 4.1 GDELT — 이벤트를 코드화하고 네트워크로 그리다

- **무엇인가**: *"a realtime **network diagram** and database of global human society"*. 전 세계 뉴스 미디어를 **100개 이상 언어**, **1979년 1월 1일부터**, **15분마다 갱신**으로 모니터링하고, "사람·장소·조직·테마·출처·감정·인용·이미지·이벤트"를 식별한다([gdeltproject.org](https://gdeltproject.org/)). 100% 무료·개방이다.
- **문장 → 구조화의 실제 예시 (공식 페이지가 직접 든 예)**: *"The United States criticized Russia yesterday for deploying its troops in Crimea…"* 라는 문장 하나가 **`US CRITICIZES RUSSIA` / `RUSSIA TROOP-DEPLOY UKRAINE (CRIMEA)` / `RUSSIA MATERIAL-CONFLICT CIVILIANS (CRIMEA)`** 3개 레코드로 변환된다. 각 이벤트는 약 **60개 속성**을 갖는다.
- **시각화 도구(공식 목록)**
  - **Network Visualizer** — GKG에서 네트워크 다이어그램을 생성하고 **`centrality`·`influencer` 랭킹**을 함께 제공 (예시: 나이지리아 석유·가스 산업 핵심 영향력자 네트워크)
  - **TimeMapper Visualizer** — 이벤트 DB를 검색해 **시간부호화된 KML**을 받아 **시간과 공간을 동시에** 탐색
  - **Word Cloud Visualizer**
  - **Global Conflict Dashboard** — 매일 갱신되는 전 세계 시위·소요의 인터랙티브 지도
  - 갱신 주기: 모든 스트림이 **15분마다**
  (모두 같은 URL)
- **줍에 가져올 요소 (매우 높음)**
  1. **"사건 → (행위자, 행위, 대상)" 삼항 구조**: GDELT는 사건을 **누가/무엇을/누구에게**로 분해한다. `[추론]` 줍의 `INVOLVES`는 이미 `사건 → 기업 + 역할`이므로 여기에 **행위(동사)를 별도 축으로** 두면("제출", "협력", "공급") **간선 라벨이 역할명이 아니라 문장 형태**가 되어 훨씬 읽힌다. v3 캡처의 간선 라벨(`제출자`, `협력사`, `기술 제공사`)이 명사형인 것과 대비된다.
  2. **중심성·영향력자 랭킹을 그래프와 병치**: GDELT의 Network Visualizer는 그래프와 함께 **`centrality`/`influencer` 순위**를 준다. `[추론]` 줍에서 "지금 가장 많이 연결된 기업/사건"을 **순위 리스트로 그래프 옆에** 두면, 그래프를 읽지 않아도 정보를 얻는 경로가 생긴다. 이는 §2.3 KeyLines의 `Insight-driven graph engine`(중심성으로 강조)과 같은 계열의 해법이다.
  3. **시간+공간 동시 탐색**: 타임라인은 §3.3 Cosmograph, 지도는 GDELT가 근거. 줍은 지도가 없어도 되지만 **"기간 필터 + 사건 목록"의 동시 갱신**은 가져올 수 있다.
  4. **이벤트를 코드로 표현하고 원문은 보존**: GDELT는 이벤트를 카테고리 코드(300+)로 정량화한다. `[추론]` 줍의 사건 범주색·아이콘이 이미 같은 발상이며, **범주를 300개까지 늘릴 필요는 없지만 "범주는 코드, 제목은 원문"이라는 분리**는 유지할 가치가 있다.
- **줍과 맞지 않는 점**: GDELT의 규모(2.5TB/년, 4억 레코드)는 줍(수백 노드)과 5~6자릿수 차이다. GDELT의 Network Visualizer는 **산업 단위 거시 네트워크**를 그리며 개별 사건 노드가 없다. 또 GDELT의 `tone`(감정) 축은 줍이 NFR-08에 따라 **채택하지 않기로 한** 바로 그 개념이다 — **참고하되 가져오면 안 되는 항목**으로 명시해 둔다.

---

### 4.2 AI Supply Chain (Stanford) — 뉴스에서 뽑은 기업 관계망 + 리스트/타임라인 토글

- **무엇인가**: **뉴스·보도자료에서 LLM으로 기업 간 관계를 추출해 공개한 연구 프로젝트의 인터랙티브 사이트**. 스탠퍼드 연구진(Cen, Gailmard, Bommasani, Ho, Liang)의 연구 산출물이며, 데이터는 **CC BY-NC 4.0**(비상업)이다. arXiv 선행연구(2504.20185)를 인용한다([aisupplychains.org/project](https://aisupplychains.org/project)).
- **줍과의 유사성이 가장 높은 지점** — 방법론이 거의 동일하다:
  - 시드 조직 30여 개(OpenAI, Anthropic, Microsoft, NVIDIA…)에 대해 **`"Organization" <search string>`** 형태의 검색을 수행하고, `partnership | collaboration | agreement | alliance`, `deal | investment | acquisition | merger | licensing` 키워드로 **관계를 수집**한다.
  - `techcrunch.com`, `venturebeat.com`, `finance.yahoo.com`으로 **도메인 제한 검색**을 병행한다.
  - 각 문서를 **LLM으로 구조화 추출**해 `참여 행위자 / 관계 유형과 속성 / 짧은 설명 / supporting evidence / AI 관련 여부`를 기록하고, **동일 문서에 대해 독립적으로 2회 추출**한다.
  - 데이터는 **2022년 11월부터 현재까지**, 주 단위 갱신.
  - 한계도 스스로 명시한다: 미국 기업 편중, 비공식 협력은 과소 대표, **검색 인덱스 편향**, "search-indexed documents are not audited in the manner of regulatory filings".
  (모두 같은 URL)
- **UI에서 확인한 것 (공식 페이지 텍스트 기준)**
  - 홈은 **"month-by-month" 애니메이션**으로 공급망 일부를 시간 순으로 보여준다(*"In the animation below, we show (a small part of) the AI supply chain, visualized month-by-month."*).
  - `Search Actor` 페이지: 액터명을 입력하면 **그 액터가 등장하는 모든 관계**를 보여주고, **`date range` 필터**, **`data source` 필터**, **fuzzy matching 토글**, 그리고 **`Toggle between the List and Timeline views`** 를 제공한다. 도구 설명에 *"You can filter results by date range, data source, and enable fuzzy matching… Toggle between the List and Timeline views for different formats."* 라고 명시되어 있다([Search Actor](https://aisupplychains.org/search_actor)).
  - `Search Relation`: **두 액터 사이의** 모든 관계를 별도 페이지로 조회(`/search_pair`).
  - 페이지 구성: `Home / Statistics / Search Actor / Search Relations / Network Graph / Time Series / Project` — **네트워크·시계열·검색·통계를 각각 독립 페이지**로 분리.
- **줍에 가져올 요소 (우선순위 최상위)**
  1. **`List ↔ Timeline` 토글**: 관계 목록을 **리스트와 타임라인 두 형식으로 같은 데이터로 전환**. `[추론]` 줍의 v3 우측 패널("직접 관련 사건 8건")에 **타임라인 토글을 추가하는 것이 가장 적은 비용으로 시간 축을 도입하는 방법**이다. 새 데이터가 필요 없다 — 이미 있는 사건에 시각만 붙이면 된다.
  2. **`검색 대상`과 `검색 쌍`을 분리**: `Search Actor`(한 기업의 모든 관계)와 `Search Relation`(두 기업 사이의 관계)을 **별도 화면**으로 둔다. `[추론]` 줍의 "기업 A ↔ 기업 B 경로/관계 찾기"를 별도 진입점으로 만들 근거. 선행 문서의 `Shortest Path`(Bloom)와 결합한다.
  3. **출처 필터(`data source`)를 1급 필터로**: 이 프로젝트는 출처를 `news coverage / press release / other`로 분류해 필터에 노출한다. `[추론]` 줍의 근거 문서도 **매체 유형(통신사/경제지/공시)** 으로 필터링할 수 있어야 한다(선행 문서의 Ground News 권고와 동일 방향).
  4. **월별 애니메이션**: 홈에서 **시간 순 애니메이션**으로 네트워크가 자라는 모습을 보여준다. `[추론]` §3.3 Cosmograph의 재생 버튼과 같은 기능이며, **두 독립 사례가 같은 해법을 쓴다**는 점에서 우선순위가 높다.
  5. **방법론·한계의 공개**: 검색 인덱스 편향, LLM 추출 오류 가능성, 비공식 관계 과소 대표를 **명시**한다. `[추론]` 줍이 "근거 N건"을 보여줄 때 **"이 관계는 보도된 것만 담긴다"** 는 한계를 어딘가에 적어야 한다. 이 프로젝트는 그 문장을 프로젝트 페이지에 두었다.
- **줍과 맞지 않는 점**: ① **비상업(CC BY-NC 4.0)** 라이선스이므로 데이터를 그대로 가져올 수 없다 — **방법론·UI 패턴만** 참고한다. ② 이 사이트의 관계는 **기업↔기업**뿐이고 **사건(뉴스 이벤트)이 노드로 존재하지 않는다**. 줍의 핵심인 "사건 노드"가 없으므로 **그래프 구조 자체는 참고 대상이 아니다.** ③ `Network Graph` 페이지는 브라우저에서 접근했을 때 본문이 렌더링되지 않아(HTTP 404 및 빈 응답) **화면을 1차 근거로 확인하지 못했다** — 캡처 대상에 넣되, 실패 시 이 문서의 서술 범위는 위 텍스트 근거까지다.

---

### 4.3 The Pudding — 네트워크 시각화를 서사에 종속시키기

- **무엇인가**: 데이터 저널리즘 매체. 예시 작품 *"How Sonic DNA Connects Generations of Music"* 는 **네트워크 시각화**를 사용한다 — 페이지 첫 이미지의 대체 텍스트가 *"An illustration of a **network visualization** showing album covers connected by lines."* 이고 본문은 *"This is a project about shared DNA in music."* 로 시작한다. 페이지는 `Loading visualization data...` 상태를 거친다([pudding.cool/2025/04/music-dna](https://pudding.cool/2025/04/music-dna/)).
- **줍에 가져올 요소**
  - **그래프를 스크롤 서사의 한 장면으로**: The Pudding의 네트워크는 독립 탐색 도구가 아니라 **이야기의 특정 지점에 등장하는 시각 자료**다. 대체 텍스트도 "이미지"로 선언되어 있다(`An illustration of a network visualization`). `[추론]` 이는 그래프 접근성의 좋은 선례다 — 캔버스에 `role="img"`와 서술적 `aria-label`을 주는 방식(선행 문서 §4.3 권고)과 정확히 같은 결론이며, **여기서는 실제 저널리즘 산출물이 그렇게 하고 있다는 증거**를 추가로 얻는다.
  - **"1,000명의 관계를 추적"** 같은 대규모 관계 서사: The Pudding 홈은 *"Tracking 1,000+ people through the ups and downs of their relationships"* 를 대표작으로 소개한다([pudding.cool](https://pudding.cool/)). `[추론]` 관계의 **변화(ups and downs)** 를 시간축으로 다루는 서사 형식은 줍의 "이 사건이 그 회사에 어떻게 이어졌는가" 스토리텔링에 참고할 만하다.
- **줍과 맞지 않는 점**: The Pudding은 **일회성 서사**이고 독자가 데이터를 탐색하지 않는다. 줍은 **사용자가 자기 종목을 중심으로 계속 탐색**하는 도구다. 따라서 "스크롤에 따라 그래프가 등장"하는 연출은 **온보딩·브리핑 화면에만** 제한적으로 적용해야 하고, 메인 지도 화면에는 적용하면 안 된다. 또 The Pudding 작품들은 **고정 데이터셋에 맞춘 수작업 레이아웃**이라 재사용 가능한 컴포넌트가 아니다.

---

## 5. 패턴별 묶음

각 패턴을 **독립적으로 1차 근거로 확인한 제품**과 함께 정리한다. 같은 패턴이 **서로 다른 제품에서 반복 확인될수록** 채택 근거가 강하다.

### 5.1 포커스 + 컨텍스트 (에고 네트워크 탐색)

| 제품 | 근거 |
|:--|:--|
| Linkurious | 선택 노드 파란 링 + 경로 하이라이트, 나머지 회색 유지 (공식 스크린샷 확인) |
| i2 ANB | 선택 노드 파란 링 + **`F`(focus) 배지**, 경로만 시안으로 밝아짐 (공식 스크린샷 확인) |
| Palantir Quiver | **`dependency view`**: 선택 카드의 **upstream/downstream만** 남기고, `Exit dependency view`로 복귀 |
| Kumu | focus + 차수(`out n`), `esc`로 전체 복귀 (선행 문서 §4.1) |
| Neo4j Bloom | `Select related nodes`, `Dismiss single nodes` (선행 문서 §4.1) |

**줍 적용**: v3는 이미 선택 시 이웃 강조 + "선택 관계만 남기기"를 갖고 있다. 부족한 것은 **① 명시적 복귀 버튼(Palantir `Exit dependency view`), ② 모드임을 알리는 라벨, ③ 나머지 노드를 완전히 지우지 않고 회색 맥락으로 남기기**다. → §6 추천 1.

### 5.2 좌측 필터 · 우측 인스펙터

| 제품 | 근거 |
|:--|:--|
| Linkurious | 좌 `FILTERS`(NODES/EDGES 탭 + 항목별 카운트) / 우 협업·권한 크롬 (스크린샷 확인) |
| i2 ANB | 좌 `Filter results by`(**`n/N` 비율**) + `Palette` / 우 `Entities`·`chart`·`List` 탭 + `Selected items only` 토글 (스크린샷 확인) |
| Cosmograph | 좌 `FILTERS` + **히스토그램** (스크린샷 확인) |
| Kumu | 좌측 **서사 카드 오버레이** (스크린샷 확인) — 필터가 아닌 "설명"이 좌측에 오는 변형 |

**줍 적용**: v3의 3단(내 종목 | 그래프 | 상세)은 이미 이 패턴이다. 개선점은 **① 필터에 `n/N` 비율 표기, ② 노드/간선 탭 분리, ③ 정량 축 히스토그램, ④ 상세 패널에 `선택한 항목만` 토글, ⑤ (비회원 시) 좌측 열을 Kumu식 설명 카드로 활용**이다. → §6 추천 2.

### 5.3 그래프 + 타임라인 이중 뷰

| 제품 | 근거 |
|:--|:--|
| Cosmograph | 캔버스 **하단 전체 폭 연도 브러시** + 재생 버튼 (스크린샷 확인) |
| AI Supply Chain | 액터별 관계를 **`List ↔ Timeline` 토글**로 전환 + `date range` 필터 |
| GDELT | **TimeMapper**: 이벤트를 시간부호화해 **시간·공간 동시** 탐색. 모든 스트림 15분 갱신 |
| i2 ANB | 제품 설명의 **"temporal, spatial and statistical views"** 3종 병기 |

**줍 적용**: **v3에 완전히 없는 유일한 축**이며, 네 제품이 서로 다른 방식으로 같은 결론에 도달했다. **① 캔버스 하단 기간 브러시, ② 우측 패널 리스트↔타임라인 토글** 중 하나를 먼저 넣는다. 후자가 더 싸다(새 데이터 불필요). → §6 추천 3.

### 5.4 클러스터 / 그룹 박스

| 제품 | 근거 |
|:--|:--|
| KeyLines | **`Combo decluttering`** — 그룹 노드로 묶고 **드릴다운** |
| Palantir Quiver | **`Color groups`** — 관련 노드에 색 부여, **`collapsed into a single node` 또는 `hidden`** |
| Kumu | **`cluster: selector by "Field" as "Type"`** — 타입 통일 시 기존 엘리먼트 재사용 |
| Neo4j Bloom | `Group nodes/relationships` (선행 문서 §4.1) |

**줍 적용**: 고립 사건 문제의 **구조적** 해법. 단 §3.1에서 본 대로 **근거 없는 클러스터 노드 생성은 "모든 관계에 원문 근거" 원칙과 충돌**하므로, `SHARES_ISSUE`·`STRUCTURALLY_RELATED_TO`처럼 **이미 근거가 있는 파생 관계만** 클러스터로 승격한다. 시각적 그룹핑(배경 영역/테두리)은 근거 없이도 허용. → §6 추천 4.

### 5.5 경로 탐색

| 제품 | 근거 |
|:--|:--|
| Palantir **Insight** | **분석 경로(analysis path)** 를 단계별로 쌓고 `Link` 단계로 연결 객체를 따라간다 |
| Neo4j Bloom | `Shortest Path`(최대 20 hops, 첫 경로만 표시) (선행 문서 §4.1) |
| AI Supply Chain | `Search Relation`으로 **두 액터 사이의 관계만** 별도 조회 |

**줍 적용**: "A사와 B사가 어떻게 연결되나"는 개인 투자자의 자연스러운 질문이고, 지금 v3에는 이 경로가 없다. Palantir식으로 **경로를 단계 카드 리스트로 남기면** 그래프를 읽지 않고도 답을 확인할 수 있다. → §6 추천 5.

### 5.6 미니맵 / 뷰포트 컨트롤

| 제품 | 근거 |
|:--|:--|
| Neo4j Bloom | 미니맵(전체 씬 + 현재 뷰포트, 드래그 팬), 줌 % 클릭 시 100% 리셋 (선행 문서 §4.1) |
| Palantir Quiver | 좌하단 **zoom in/out · zoom to fit all nodes · reset layout** 버튼 묶음 |
| Cosmograph | 캔버스 우측 `+ −` 및 좌상단 **`Fit view` / `Select area`** 모드 토글 |
| 줍 v3 | 좌하단 `+ − ⤢` + 컨트롤 바 (자체 캡처로 확인) |

**줍 적용**: v3의 컨트롤 묶음은 Palantir와 사실상 동일 위치·구성이다 — **유지**. 추가 검토는 **`팬/선택` 모드 명시**(Cosmograph·Palantir 두 곳에서 확인)와, 그래프가 커졌을 때의 **미니맵**이다. 단 노드 30~60개 규모에서는 미니맵 우선순위가 낮다.

### 5.7 노드/간선 과밀 대응

| 기법 | 근거 제품 |
|:--|:--|
| **간선 곡률**로 평행 간선 분리 | Linkurious (스크린샷 확인) |
| **라벨을 일부만** 표시 | Cosmograph (스크린샷 확인 — 일부 노드만 라벨) |
| **노드는 최소 정보만**(제목·ID·타입), 상세는 별도 패널 | Palantir Quiver (문서에 이유까지 명시: 성능) |
| 라벨을 **회색 라운드 박스 + 말줄임**으로 통일 | Linkurious (스크린샷 확인) |
| **`n / N` 비율**로 숨겨진 양을 정직하게 표시 | i2 ANB (스크린샷 확인) |
| **점선 vs 실선**으로 관계 종류 구분(색 의존 회피) | Kumu (스크린샷 확인 — 범례에 `Inverse`=점선, `Direct`=실선) |

**줍 적용**: v3 캡처의 최대 문제는 **① 모든 간선에 라벨, ② 사건 노드 라벨의 잘림·겹침**이다. 위 6기법이 모두 v3에 미적용 상태이므로 **여기가 가장 큰 즉시 개선 여지**다.

---

## 6. 상위 추천 5개 (이유 포함)

> 우선순위는 **"줍 v3의 확인된 결손을 직접 메우는가" × "새 데이터 없이 가능한가" × "근거 사례 수"** 로 정했다. v3 결손은 자체 캡처 3장(`reviewed-1440-light`, `reviewed-focus-1440-light`, `reviewed-390-dark`)에서 확인한 것만 셌다.

### 1위. Cosmograph — 하단 타임라인 브러시 + 히스토그램 필터

**이유**: 줍 v3에 **시간 축이 완전히 없다**(상세 패널 항목이 `발생 시각 미상`일 정도). Cosmograph는 타임라인을 **캔버스 하단 전체 폭에 고정**하고 **재생 버튼**까지 붙이는 구체적 해법을 공식 스크린샷으로 보여준다. 동시에 **히스토그램 필터**는 "고립 사건만 보기"처럼 줍의 데이터 상태 문제를 슬라이더 하나로 푼다. 같은 해법이 **AI Supply Chain(월별 애니메이션 + Timeline 토글)** 과 **GDELT(TimeMapper, 15분 갱신)** 에서도 독립적으로 확인되어, 패턴의 타당성이 3개 제품으로 교차 검증된다. 줍은 사건에 이미 날짜 필드가 있으므로 **새 데이터 수집 없이** 구현 가능하다.

**리스크**: Cosmograph의 대상 규모(수십만 점)와 줍(수백 노드)이 달라 밀집 점 구름 표현은 그대로 가져오면 안 된다. 가져올 것은 레이아웃이 아니라 **하단 브러시 + 히스토그램 + 선택적 라벨** 3가지다.

### 2위. Palantir Quiver — `dependency view` + 프리뷰 핀/2분할

**이유**: 줍 v3에 이미 있는 "선택 관계만 남기기"를 **명시적 모드 + 복귀 버튼**으로 격상하는 근거가 공식 문서에 문장 단위로 있다(*"narrows the graph to show only the selected card and its upstream and downstream dependencies"*, `Exit dependency view`). 여기에 **프리뷰 핀**(다른 노드를 선택해도 유지)과 **2분할 비교**는 상세 패널 구조를 바꾸지 않고 "두 기업 동시 비교"를 가능하게 한다. 컴팩트 노드 규칙은 **문서가 이유(성능)까지 밝혀** 줍의 긴 사건 제목 문제에 대한 정당화를 제공한다.

**리스크**: 좌→우 DAG 레이아웃은 줍의 순환 가능한 관계에 부적합하므로 **레이아웃만 제외**하고 모드·패널 기능만 가져온다.

### 3위. i2 Analyst's Notebook — `n / N` 비율 필터 + `Selected items only` + 조작 안내 문장

**이유**: 세 가지 모두 **v3의 필터 칩에 숫자가 이미 있다는 사실** 덕분에 저비용으로 바꿀 수 있다. `기업 3` → `기업 3/3`은 필터가 무엇을 숨기는지 정직하게 드러내며, 이는 **고립 사건이 많은 현재 데이터 상태를 사용자에게 설명하는 가장 싼 방법**이다. `Selected items only` 토글은 그래프 선택 ↔ 목록 보기의 왕복을 클릭 1회로 만든다. 조작 안내 문장(*"Pick a link, select maybe two entities…"*)은 **빈 캔버스·첫 진입 문제**를 해결한다 — v3 모바일 캡처에서 고립 노드 격자만 보이는 화면이 정확히 이 문제다.

**리스크**: i2의 상단 리본(20+ 버튼)과 팔레트는 **가져오면 안 된다**. "출퇴근 5분" 타깃 사용자에게 전문가용 크롬은 해롭다.

### 4위. Litmaps — 좌표가 정보인 레이아웃 (시간 × 관계 수)

**이유**: **줍의 fcose 힘 레이아웃에서 노드 위치에 의미가 없다**는 근본 문제를 건드리는 유일한 레퍼런스다. Litmaps는 *"date vs cite graph format"* 으로 배치 자체가 정보를 전달하며(*"spaced out visually… orientate where a paper is in the history of a field"*), 그 결과 **고립 노드가 하단 띠에 시간순으로 정렬**된다. `[추론]` 이는 §5.4 클러스터링과 §5.7 히스토그램이 각각 다루던 문제를 **레이아웃 하나로** 해소하며, Cytoscape.js `preset` 레이아웃으로 구현 가능해 **추가 라이브러리가 필요 없다**.

**리스크**: 기업↔기업 파생 관계와 `FOLLOWS`가 섞이면 시간 단조성이 깨진다. **전체 그래프 모드에만 적용하고 에고 네트워크에서는 힘 레이아웃을 유지**하는 하이브리드가 필요하다. 또한 `발생 시각 미상` 노드의 x좌표 규칙을 먼저 정해야 한다.

### 5위. Linkurious Explorer — 간선 곡률 + 라벨 절제 + `NODES`/`EDGES` 필터 탭

**이유**: v3 캡처에서 직접 확인된 **가장 눈에 띄는 결함**(모든 간선에 라벨이 붙어 겹치고, 사건 노드 라벨이 길게 잘림)에 대한 **상용 제품의 검증된 해법**이 공식 스크린샷에 그대로 담겨 있다: 곡선 간선으로 평행선 분리, 라벨은 회색 박스로 통일, 강조는 선택 노드에만. 여기에 **`NODES`/`EDGES` 탭 분리 + 항목별 카운트**는 줍의 필터 칩 구조와 거의 1:1로 대응해 이식 비용이 낮다. ICIJ가 이 제품으로 공개 DB를 운영한다는 사실이 실전 검증을 보강한다.

**리스크**: 노드 타입이 2종뿐인 줍에서 필터 탭은 **의미 없이 복잡해질 수 있다**. 항목 수를 늘리지 말고 탭 구조만 가져온다.

---

## 부록 A. 참고한 공식 이미지 URL 목록

| 제품 | 공식 이미지 URL | 이 문서에서 확인 |
|:--|:--|:--|
| Kumu | `https://assets.kumu.io/production/public/assets/marketing/screenshots/first-look-madison-1504edb5fcb0657c2f5d2dfb225a5489d68b24e4e08fd8298a367ab9bc73dc13.jpg` | 디코딩 확인 |
| Linkurious | `https://linkurious.com/images/uploads/2023/06/Product-Inage_Linkurious-Explorer_Header-e1687789496358.png` | 디코딩 확인 |
| Sayari | `https://sayari.com/wp-content/uploads/2026/08/sayari-risk-management-AI-solution-open-graph.png` | 디코딩 확인 |
| Cosmograph | `https://cosmograph.app/_next/static/media/main-page-screen.47dae50f.png` | 디코딩 확인 |
| i2 ANB | `https://i2group.com/hs-fs/hubfs/i2_ANB_Homepage_DarkMode%202.png` | 디코딩 확인 |
| Graph Commons | `https://graphcommons.com/files/graphs/74626001-1af0-437a-84e0-271165125847/cover.png` | 디코딩 확인 |
| LittleSis | `https://littlesis.org/oligrapher/1634-who-s-banking-on-the-dakota-access-pipeline/screenshot` | `[미확인]` (URL만 기록) |
| KeyLines | `https://cambridge-intelligence.com/wp-content/uploads/2026/04/KeyLines-page-Hero-image.png` | `[미확인]` (URL만 기록) |
| ICIJ | `https://offshoreleaks.icij.org/vite/assets/offshoreleaks_db-a0e39c24.jpg` | `[미확인]` (URL만 기록) |
| Palantir Quiver | `https://palantir.com/docs/resources/foundry/quiver/analysis-graph-compact-nodes.png` 외 (`analysis-graph-preview-panel.gif`, `howto-analysis-graph-zoom-buttons.png`, `analysis-graph-focus-mode.png`) | `[미확인]` (문서 HTML에 경로 확인) |
| Maltego | `https://s3-eu-central-1.amazonaws.com/euc-cdn.freshdesk.com/data/helpdesk/attachments/production/2015153882292/original/U3tZqPacGnNVQV7T-z7CaFxYlqx439r0rg.png` | `[미확인]` (URL만 기록) |
| Arkham | `https://cdn.prod.website-files.com/62879326fd745f7489b43224/62ebfa21a4f21f3f4499c5a7_SEO%20Banner.jpg` | `[미확인]` (URL만 기록) |
| The Pudding | `https://pudding.cool/2025/04/music-dna/assets/social.jpg` | `[미확인]` (URL만 기록) |

## 부록 B. 출처 전체 목록

- https://kumu.io/ · https://docs.kumu.io/ · https://docs.kumu.io/guides/clustering.md · https://docs.kumu.io/overview/user-interfaces.md
- https://linkurious.com/ · https://linkurious.com/decision-intelligence-platform-graph-visualization/
- https://sayari.com/
- https://littlesis.org/ · https://littlesis.org/database · https://littlesis.org/oligrapher · https://littlesis.org/oligrapher/1634-who-s-banking-on-the-dakota-access-pipeline
- https://offshoreleaks.icij.org/
- https://www.opensanctions.org/docs/ · https://www.opensanctions.org/docs/entities/ · https://followthemoney.tech
- https://i2group.com/
- https://cambridge-intelligence.com/keylines/
- https://docs.maltego.com/en/support/home · https://docs.maltego.com/en/support/solutions/articles/15000059530-what-is-maltego-graph-browser-
- https://palantir.com/docs/foundry/quiver/analysis-graph · https://www.palantir.com/docs/foundry/insight/overview
- https://neo4j.com/docs/bloom-user-guide/current/ · https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/
- https://info.arkm.com/
- https://graphcommons.com/
- https://cosmograph.app/ · https://run.cosmograph.app/public/f8868743-a624-4309-8f63-bf82c82fb61f
- https://www.litmaps.com/ · https://www.litmaps.com/features · https://app.litmaps.com/seed/1987150718
- https://www.connectedpapers.com/ (본문 미확보)
- https://gdeltproject.org/
- https://aisupplychains.org/ · https://aisupplychains.org/project · https://aisupplychains.org/search_actor
- https://pudding.cool/ · https://pudding.cool/2025/04/music-dna/
- https://www.bloomberg.com/professional/products/data/enterprise-data/supply-chain/ (HTTP 403 — `[미확인]`)

---

## 캡처 대상

로그인 없이 열리는 공개 페이지만 넣었다. `slug`는 문서 본문의 `img/<slug>.png` 링크와 일치한다. 저장 위치: `docs/research/graph-refs/img/`.

| slug | 로그인 없이 열리는 공개 URL | 보면 되는 화면 부분 |
|:--|:--|:--|
| `cosmograph` | https://run.cosmograph.app/public/f8868743-a624-4309-8f63-bf82c82fb61f | 캔버스 **하단 전체 폭 연도 브러시(1999~2021)** 와 재생 버튼, 좌측 히스토그램 필터(`micro_cluster`, `size (n_cits)`), `color (main_field)` 범례의 **범주명 + 개수**, 좌상단 `Fit view`/`Select area` 토글. 그래프 자체보다 **주변 크롬**이 목적 |
| `littlesis-oligrapher` | https://littlesis.org/oligrapher/1634-who-s-banking-on-the-dakota-access-pipeline | Oligrapher 캔버스: 노드 유형별 색/아이콘, 간선 라벨, 캔버스 컨트롤. **공개 지도 전체가 보이는 각도**로 1장 |
| `littlesis-database` | https://littlesis.org/database | 엔티티 카드의 **`Key affiliations` / `Related orgs` / `Key people` + `More »` 접기** 구조. 페이지 중단의 카드 캐러셀 |
| `kumu-gallery` | https://kumu.io/gallery | 공개 관계 지도 갤러리. 가능하면 **좌측 서사 카드 + 우측 캔버스 + 좌하단 범례**가 함께 보이는 프로젝트 1건 |
| `graphcommons-graph` | https://graphcommons.com/graphs/74626001-1af0-437a-84e0-271165125847 | `Network of Unicorns and Investors` 그래프 뷰(정적 커버가 아니라 **인터랙티브 뷰**). 노드 과밀 상태의 실물 |
| `icij-offshoreleaks` | https://offshoreleaks.icij.org/ | 검색 진입 화면 + 예시 조합(`British Virgin Islands \| Entity Name LLC \| Lima, Peru`). 하단 **"Database powered by Linkurious / Neo4j"** 영역 |
| `gdelt-analysis` | http://analysis.gdeltproject.org/ | Analysis Service 콘솔. **Network Visualizer** 항목이 보이는 화면 |
| `aisupplychain-actor` | https://aisupplychains.org/search_actor?actor=NVIDIA | 액터 검색 결과와 **`Toggle between the List and Timeline views`** 컨트롤, `date range` / `data source` 필터 |
| `aisupplychain-home` | https://aisupplychains.org/ | **month-by-month 애니메이션** 영역과 상단 내비게이션(`Statistics / Search Actor / Search Relations / Network Graph / Time Series`) |
| `litmaps-seed` | https://app.litmaps.com/seed/1987150718 | 공개 Seed Map 그래프. **두 축(날짜 × 인용)** 에 논문이 배치된 화면 |
| `keylines` | https://cambridge-intelligence.com/keylines/ | 히어로 이미지 + `Combo decluttering` / `Powerful layouts` 섹션의 데모 스크린샷 |
| `i2-anb` | https://i2group.com/solutions/i2-analysts-notebook | 제품 화면. 좌측 `Filter results by`, `Palette`, 우측 레코드 표가 함께 보이는 각도 |
| `maltego` | https://www.maltego.com/ | 제품 히어로/그래프 캔버스 스크린샷 (**RSS 리다이렉트 주의** — 실패 시 `https://docs.maltego.com/en/support/home`로 대체) |
| `opensanctions` | https://www.opensanctions.org/ | 홈의 엔티티/관계 예시 또는 `/datasets/` 목록 (**RSS 리다이렉트 주의**) |
| `palantir-quiver` | https://palantir.com/docs/foundry/quiver/analysis-graph | 문서 내 **compact nodes** 이미지와 **preview panel**(핀 고정) GIF, 하단 좌측 **줌 버튼 3종** 이미지 |
| `arkham` | https://info.arkm.com/ | "TRANSLATE RAW BLOCKCHAIN TRANSACTIONS INTO **CLEAR NETWORK MAPS**" 섹션의 네트워크 맵 영상/이미지 (플랫폼 본체는 로그인 필요) |
| `pudding-network` | https://pudding.cool/2025/04/music-dna/ | 네트워크 시각화가 등장하는 스크롤 구간. 로딩 후 **앨범 커버가 선으로 연결된** 화면 |
| `sayari` | https://sayari.com/ | 홈의 "Same query. Two very different answers…" 섹션 — **`3-hop ownership chain`이 표시된 그래프**. 그래프 자체가 목적 |
| `zoop-baseline-focus` | (로컬) `docs/design/v3/reviewed-focus-1440-light.png` | 비교 기준. NVIDIA 중심 에고 네트워크에 **모든 간선 라벨**이 붙고 사건 노드 라벨이 잘리는 상태 |

**캡처 실패 시 기록할 것**: 위 `## 부록 A`의 공식 이미지 URL로 대체하고, 실패 사유(로그인/차단/JS 미렌더)를 문서에 남긴다. 특히 `kumu-gallery`·`graphcommons-graph`·`litmaps-seed`·`pudding-network`는 **JS 렌더링**이므로 브라우저에서 네트워크가 그려질 때까지 기다린 뒤 캡처해야 한다.
