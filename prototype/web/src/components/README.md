# 컴포넌트 계약 (Foundation v3)

규칙 원문: `prototype/web/DESIGN.md`, `docs/design/design-direction.md`. 토큰 원천: `docs/design/tokens.json` → `pnpm tokens`.
색은 토큰 클래스만 쓴다: `bg-surface-{base,raised,overlay,sunken,selected}`, `text-text-{primary,secondary,tertiary}`, `border-border-{subtle,strong,control}`, `text-{up,down,warning,error}`, `bg-brand-primary`. 글자 크기는 `text-{sm,base,md,lg,xl,2xl}`(13/15/16/18/22/28)만, 반경은 `rounded-{none,sm,lg,full}`만.
테두리와 그림자를 한 요소에 같이 주지 않는다. 떠 있는 표면(Dialog·Sheet·Popover·Toast)만 그림자, 나머지는 행 + 구분선.

## ui/ (범용)

| 컴포넌트 | 언제 쓰나 |
|---|---|
| `Button` `variant: primary·secondary·ghost·link` `size: sm·md·lg·icon` `loading` `asChild` | primary는 화면당 주 행동 1개. 누르는 영역은 항상 44px 이상(sm도 투명 영역으로 확장). icon은 `aria-label` 필수. |
| `Input` `label` `hideLabel` `hint` `error` `variant: default·search` `onClear` | 모든 입력. 모바일 16px 글자. 라벨 필수. |
| `Select` | 5개 이상 선택지. 2~4개면 `Segmented`. |
| `Segmented` `value` `onValueChange` `options[{value,label,disabled,disabledReason}]` `aria-label` `fill` `onReselect?` | 모드·보기 전환(내용 영역 없음). 고른 항목을 다시 누르면 선택은 그대로 두고 `onReselect`만 부른다. |
| `Tabs` `TabsList` `TabsTrigger` `TabsContent` | 같은 대상의 내용 영역 전환(최대 4개, 폭 균등 분할). |
| `Dialog` / `Sheet` `open` `onOpenChange` `title` `description` `closeLabel` `footer` (`Sheet.mobileSnap`) | Dialog: 짧은 확인. Sheet: 데스크톱 오른쪽 패널, 모바일에서는 자동으로 BottomSheet. 닫기 문구는 [닫기]. |
| `BottomSheet` `snap`/`defaultSnap: half·full` `onSnapChange` + Dialog props | 모바일 노드·간선 상세처럼 지도를 반쯤 보이며 탐색할 때. 손잡이 끌기·Enter·↑/↓, Esc, 딤 누르기로 닫기. |
| `Popover` `trigger` `label` `open?` `onOpenChange?` | 눌러서 여는 짧은 설명·설정(터치 동작). 목록에서 고르면 닫혀야 하면 `open`으로 제어. `Tooltip`은 호버 전용 한 줄 보조 설명. |
| `IconHint` `icon` `label` `children` `tone` `size: sm·md` | 설명문·부제·메타 라벨 대신 아이콘 하나. 호버·포커스 툴팁(label) + 누르면 팝오버(label + children). aria-label = label. |
| `useToast()({title, description?, tone})` | 한 문장 결과 알림(3초, 경고 5초). 오류는 `ErrorState`. |
| `Skeleton` `SkeletonLines` `SkeletonRows` `LoadingBlock` | 로딩. 목록 자리는 `SkeletonRows`. |
| `EmptyState` `title` `description` `action` | 빈 상태: 문장 + 다음 행동. 아이콘 타일 없음. |
| `ErrorState` `error` `title` `onRetry` `showBack` `compact` `actions?` | 오류(0건으로 위장 금지). 코드는 [자세히] 안. `actions`는 다시 시도 옆의 다른 복구 동작(예: 시작 화면으로). |
| `Badge` `variant: neutral·warning·error` | 누를 수 없는 상태 표시, 행당 최대 1~2개. 필터·토글은 Button/Segmented. |
| `ListRow` `leading` `title` `description` `trailing` `selected` `divider: indented·full·none` + `to`(링크) 또는 `onClick`(버튼) | 카드 대신 쓰는 목록 행. `<li>` 안에. 행 안에 다른 버튼 중첩 금지. |
| `SectionHeader` `title` `icon` `action` `as` `id` | 목록 머리글. 앞에 종류 아이콘(기업 `Building2`, 사건 `Zap` …). 설명문은 두지 않고 필요하면 `action`에 `IconHint`. |
| `AppBar` `leading` `title` `trailing` | 모바일 48px 상단 바(앱 셸이 사용). |
| `BottomTabBar` `tabs[{to,label,icon,end}]` | 모바일 하단 탭(앱 셸이 사용). 본문은 `pb-tabbar` 여백. |

## domain/ (줍 전용)

| 컴포넌트 | 언제 쓰나 |
|---|---|
| `SourceIndicator` `kind` `offline` `size: sm·md` | datasetKind를 글자 없는 아이콘 버튼으로(`ShieldCheck`·`Archive`·`FlaskConical`, 툴팁·aria-label `데이터 출처: …`). **앱 헤더 + 근거 창 1곳만.** |
| `CompanyMark` `id` `name` `brandColor` `logoUrl` `size` | 지도 노드와 같은 기업 표지(상징색 원 + 로고, 없으면 이니셜, 상징색 없으면 폴백 팔레트). 목록 행 leading(24px)·머리글(40~48px). |
| `EventRow` `title` `eventTime` `timePrecision` `companies` `evidenceCount` `onShowEvidence` `onAsk` `onSelect` `relationType?` `meta` `divider` | 사건 1건 = 1행(IssueCard 대체). 날짜 줄에 아이콘 메타(`meta`, `IconCount`). `relationType`은 관계가 섞인 목록에서만(선 견본 아이콘 + 툴팁). |
| `IconCount` `icon` `label` `count` | 아이콘 + 숫자 메타(예: 보도 기사 3). 이름은 스크린리더·툴팁에만. |
| `ApprovalNote` `approval` / `RoleUnconfirmed` | 사건 상세에서 PoC 검증만으로 게시된 것이 아닐 때의 출처 한 줄(배지 `관리자 승인`·`자동 검수 규칙` + 눌러 보는 설명, `approval`이 없으면 그리지 않음). `RoleUnconfirmed`는 자동 검수 규칙이 역할 문구를 비운 자리(`roleUnconfirmed`)에 아이콘 + `역할 미확인`(다른 역할로 채우지 않음). 행 안(ListRow `description`)에서는 `RoleUnconfirmed`만 쓴다(버튼 중첩 금지). |
| `BriefingCard` `edition` `date` `scheduledAt` `publishedAt` `dataAsOf` `notice` `corrections` `totalEvidence` `summary` `relations` | 브리핑 1회분(바깥 경계 1개, 안은 EventRow). 머리에 발행일·예정 시각(07:40/18:10)·발행 시각·데이터 기준 시점. `notice`는 미준비·실패·제공 중단 안내 한 줄, `corrections`는 회차 전체 정정(발행 원문과 구분). 투자 고지·출처는 화면에서 한 번. |
| `CompanyHeader` `id` `name` `brandColor` `logoUrl` … | 기업 표지·기업명·업종·티커·보유/관심. 시세가 없으면 시세 자리를 두지 않는다. |
| `EvidenceList` / `EvidenceQuote` / `VerificationBadge` `mapLink` | 근거 원문 인용(좌측 강조선 없음). 인용 확인은 체크 아이콘(툴팁), 대조 필요만 경고 배지. `mapLink`(지도에서 연 근거 창)가 있으면 인용마다 [지도에서 보기] 토글(`aria-pressed`). |
| `DocumentItem` `title` `publisher` `url` `publishedAt` `relation` `quotes` `headingLevel` | 근거 문서(뉴스·공시) 1건: 출처·발행 시각 → 제목 → 관계(`documentRelationLabel`) → 저장한 인용 → 원문 링크. `url`이 없으면 `원문을 제공하지 않는 자료입니다`. 기업 상세 사건 상세·문서 탭에서 쓴다. |
| `GraphCanvas` `nodes` `edges` `selection` `onSelect` `ariaLabel` `groupIsolated` `focus` `hidden` `evidence` `path` | 지도(GraphDB식, design-direction §4): 색 원 노드, 간선 가운데 `summary`(12자 말줄임, 호버·선택 시 전체), fcose, 라벨 LOD. 노드를 고르면 최신 사건 순 6개 선에만 요약. 사건 노드 오른쪽 위 근거 수 배지(`evidenceCount`, 0.8배 미만 숨김). `groupIsolated`: 선 없는 사건을 묶음 노드 하나(`ISOLATED_BUNDLE_ID`, 화면 최소 48px, 캔버스 위 투명 버튼으로 키보드 선택)로. `focus`: n단계 이웃만 남기고 포커스 노드를 중심에 둔 방사형(1단계 첫 링, 2단계 둘째 링)으로 옮겨 맞춤, 나오면 전체 배치 위치로 복귀(재배치 없음). `hidden`: 범례에서 끈 종류 숨김(재배치 없음). `evidence`: 그 근거 id를 가진 선(`evidenceIds`)과 양 끝을 강조, 없으면 사건 노드. `path`(`lib/graph-path`의 `shortestPath` 결과, `focus`와 함께 주지 않음): 경로만 선명(나머지 흐림), 경로 선 요약 항상 표시, 카메라를 경로에 맞춤. 미니맵(G7): 데스크톱에서 보이는 노드 60개 초과일 때만 오른쪽 아래(`aria-hidden`, 썸네일은 화면 이동이 멈춘 뒤에만 갱신). 파일: `graph-canvas`(수명주기·도구 막대) · `graph-style`(스타일·LOD) · `graph-elements`(요소·묶음·배지) · `graph-layout`(배치·맞춤) · `graph-interaction`(보기 상태·이벤트·카메라) · `graph-minimap`(cytoscape-navigator), 표시 규칙 타입은 `lib/graph-view`. |
| `GraphLegend` `nodes` `edges` `hidden` `onToggle` | 범례 라벨 칩(표지·이름·개수). `onToggle`을 주면 노드 종류·관계 유형 칩이 표시 토글 버튼(`aria-pressed`): 꺼도 개수 유지, 칩만 흐려짐, 노드 종류는 최소 하나 켜 둠. 보유·관심 칩은 토글하지 않는다. |
| `FocusBar` `node` `hops` `onHopsChange` `onExit` `compact` | 포커스 모드 막대: [표지] 이름 중심 · 1단계/2단계 `Segmented` · [전체 보기](`compact`면 아이콘). 주소 `?focus=&hops=`는 부모(main-page)가 push로 관리해 뒤로 가기로 복귀. |
| `PathBar` `from` `to` `steps` `onExit` `onShowSteps` `compact` | 경로 모드 막대(G6): [표지] A ⇆ [표지] B · N단계 · [전체 보기](`compact`면 아이콘). `onShowSteps`가 있으면 `경로 단계 보기` 아이콘(모바일 단계 시트). 주소 `?path=A,B`는 main-page가 push로 관리. 두 번째 기업 고르기(`PathPicker`)와 단계 목록(`PathDetail`)은 `features/path-panel`. |
| `GraphModeSwitch` `value` `onValueChange` `lockedModes` / `MarkRing` `kind` / `RelationList` / `EdgeGlyph` | 전체(`all`)·개인화(`personal`) 모드 전환(비회원은 `lockedModes={["personal"]}`로 자물쇠, 지금 모드를 다시 누르면 같은 값으로 `onValueChange` — 진행 중인 전환 취소용), 보유(실선)·관심(점선) 고리 견본(범례·사이드바·디자인시스템), 지도와 같은 내용의 키보드용 목록(묶음 없이 모든 사건), 선 견본. 사건 공유(파생) 의미는 간선 패널에서 설명. |
| `AiBadge` / `AiNotice` / `AiDisclosure` | AI 생성 표시 1회 + 한 줄 고지, 생성 방식은 팝오버. |
| `PriceChange` / `SentimentLabel` / `DisclaimerNote` | 등락(색+부호+▲▼+스크린리더 `상승/하락/보합`). `change`+`currency`를 주면 `▲ +5,250원 (+1.96%)`(받은 통화 그대로, 기업 상세 시세·차트·평가 손익), 없으면 등락률만. 둘 다 `null`이면 렌더링 안 함. 감성 규격(디자인시스템 전용), 투자 권유 아님 고지(브리핑·기업 상세 하단). |

`QuietValue`·`RelationTypeTag`는 v3에서 삭제했다(없는 값은 자리 자체를 그리지 않고, 관계 유형은 선 견본·섹션 머리 IconHint로).

## 모션 유틸리티 (`src/styles/index.css`, 값은 tokens.json `motion` = SEED)

`pressable`(눌림 세로 2px 축소) · `motion-page`(화면 전환) · `motion-scrim`/`motion-sheet-bottom`/`motion-sheet-right`/`motion-dialog`(Radix `data-state` 진입·퇴장) · `motion-pop`(팝오버·메뉴·툴팁) · `motion-toast` · `stagger`(목록 첫 표시). `Segmented`·`TabsList`는 선택 표시가 미끄러진다. 동작 줄이기면 모두 즉시.
