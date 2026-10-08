# 최종 Figma 전환 계획과 컴포넌트 상태 계약

**상태: 설계 보고 완료 · 앱 전환 미실행.** 이 문서는 후속 프론트엔드 구현의 근거와 수용 기준이다. 앱 마크업·CSS·토큰·설정·API를 변경하지 않았다. 기능 S1의 문서 요약·문서×기업 판정 consumer 완성을 먼저 진행하고, 전면 스타일 전환은 이후 Main이 별도로 배정한다. 보고서 완료를 실제 UI 완료나 기능 수용 기준 통과로 표현하지 않는다.

## 1. 권한, 관찰 범위와 결정 상태

### 적용 기준

1. 접근성, 실제 데이터의 의미, 공개권한과 저장 산출물의 정직한 표시는 보존한다.
2. 사용자가 확정한 최종 시각 목표는 **10-08 고정 Figma이며 폰트만 SUIT를 유지**한다. 흰 기업원·검은 마름모·캡슐 라벨·흑백 버튼을 이전 틸 계약 때문에 거절하지 않는다. [현재 사용자 기준](../share/day-work-2026-10-08.md)의 디자인 행이 이전 `DESIGN.md`의 해당 시각 규칙과 [wireframe-delta](../evidence/wireframe-delta-2026-10-08.md)의 ‘승인 없는 스타일 제안’ 표현을 대체한다. 과거 기록 자체는 고치지 않았다.
3. Main의 이번 추가 확정: **탐색 목록의 CompanyMark는 상징색/이니셜을 유지하고, 그래프·기업 헤더는 흰 로고 원 역할로 구분**한다. 공용 `companyFill`을 전역 흰색으로 치환하지 않는다. `kind=issue`의 의미 변경은 data/AI S2 범위이며 이번 시각 전환에서 ID·타입의 뜻을 바꾸지 않는다.
4. 본개발의 FE/BE 스택은 미정이다. 아래 React 파일은 현재 구현의 주소이지 본개발 채택 강제가 아니다. 시각 역할·상태·키보드·근거 연결 계약을 다른 FE에서도 옮길 수 있어야 한다.

| 표기 | 뜻 | 이 보고서의 해당 결정 |
|---|---|---|
| 사용자 확정 | 사용자 또는 Main이 전달한 채택 결정 | Figma 최종 목표, SUIT 유지, 기능 먼저, 목록/그래프/헤더 표지 역할 분리, 이번 전환에서 ID 의미 불변 |
| 원본 관찰 | 실제 고정 PNG에서 보인 정적 표현 | 흰 기업원, 검은 마름모, 흰 캡슐 라벨, 검은 CTA, 탭 밑줄, 3열 기업 상세, 행 구분선 |
| 작업자 도출 | 정적 원본에 없는 동작·접근성·상태를 보수적으로 보완한 안 | 아래 토큰 역할, dark derivation, 상태 페이지 IA, 충돌 정리·44px·포커스 수용 기준 |
| 미정 | 이미지나 현재 데이터로 확정할 수 없는 항목 | Figma 변수의 정확한 값, 활동 산식, 전체/지역 집계 범위, 모바일 빈 지도의 의도, 신규 기업 메타데이터 공급 |

### 직접 읽은 시각 증거

원본 파일: [돈벌레 최종 프로젝트](https://www.figma.com/design/B1nkTuCLKWMohgXNdEB6un/돈벌레-최종-프로젝트?node-id=620-617). 아래 개별 PNG를 직접 열람했다. `F`는 `docs/evidence/raw/wireframe_2026-10-08/`의 약칭이다. 표의 node ID는 수집본 파일명과 같은 Figma URL 표기이며, API식 표기는 하이픈 대신 콜론이다.

| 증거 ID | Figma node / 상태 | 실제 source capture |
|---|---|---|
| F01 | 619-1819 / D-GRP-01 시장 전체 | [frame-619-1819.png](../evidence/raw/wireframe_2026-10-08/frame-619-1819.png) |
| F02 | 619-2769 / 같은 지도 210% 확대 | [frame-619-2769.png](../evidence/raw/wireframe_2026-10-08/frame-619-2769.png) |
| F03 | 619-6729 / D-GRP-03 기업 패널 | [frame-619-6729.png](../evidence/raw/wireframe_2026-10-08/frame-619-6729.png) |
| F04 | 637-2222 / D-COM-01 기업 개요·사건 탭 | [frame-637-2222.png](../evidence/raw/wireframe_2026-10-08/frame-637-2222.png) |
| F05 | 637-6212 / D-COM-01b 차트·시간 버킷 | [frame-637-6212.png](../evidence/raw/wireframe_2026-10-08/frame-637-6212.png) |
| F06 | 663-14180 / 기업 문서 탭 | [frame-663-14180.png](../evidence/raw/wireframe_2026-10-08/frame-663-14180.png) |
| F07 | 663-13515 / 기업 정보 탭 | [frame-663-13515.png](../evidence/raw/wireframe_2026-10-08/frame-663-13515.png) |
| F08 | 619-1080 / D-AUT-01 로그인 | [frame-619-1080.png](../evidence/raw/wireframe_2026-10-08/frame-619-1080.png) |
| F09 | 692-2 / 종목 목록·삼성 검색 | [frame-692-2.png](../evidence/raw/wireframe_2026-10-08/frame-692-2.png) |
| F10 | 620-5405 / D-SEN-01 등락·판정 예시 | [frame-620-5405.png](../evidence/raw/wireframe_2026-10-08/frame-620-5405.png) |
| F11 | 620-5691 / D-SEN-02 회차 판단·CompanyMark 예시 | [frame-620-5691.png](../evidence/raw/wireframe_2026-10-08/frame-620-5691.png) |
| F12 | 620-5928 / M-GRP-01 지도·기업 바텀시트 | [frame-620-5928.png](../evidence/raw/wireframe_2026-10-08/frame-620-5928.png) |
| F13 | 619-8225 / D-GRP-05 근거 문서 창 | [frame-619-8225.png](../evidence/raw/wireframe_2026-10-08/frame-619-8225.png) |

현재 앱의 비교 시각 증거는 [v9 라이트 전체 지도](v9/label-1440-light-market.png)와 [현재 화면계획서 D-SEN-01](../screen-plan/captures/D-SEN-01.png)을 직접 열람했다. 전자는 상징색 기업원·작은 사건원·하단 조작·우측 미니맵, 후자는 틸 선택 목차와 이미 존재하는 등락/판정 예시를 보여 준다. 이는 저장된 당시 렌더이며 진행 중인 S1 변경을 포함한 현재 런타임 검증이 아니다.

수집본의 원래 viewport는 1440×1000 CSS px, PNG는 1800×1250 px이며 Figma chrome·맞춤 배율이 포함된다. 원본 제품 프레임의 1280×820/1359×820 표기나 PNG 픽셀을 앱 CSS 치수로 환산하지 않는다. 정확한 색·반경·폰트 크기·hit area·responsive breakpoint·hover/focus 상태는 이미지로 확정하지 않는다. [acquisition.md](../evidence/raw/wireframe_2026-10-08/acquisition.md), [captures.json](../evidence/raw/wireframe_2026-10-08/captures.json), [figma-public-layers.json](../evidence/raw/wireframe_2026-10-08/figma-public-layers.json)이 provenance를 보존한다.

이번 범위는 새로운 시각 정체성을 고르는 일이 아니라 채택된 Figma를 기존 기능·상태에 투영하는 일이다. 다른 폰트나 경쟁 디자인 방향을 연구하지 않았다. Lapis/lps-system/design-distinctiveness의 근거·역할·상태·권한 분리 지침을 적용했지만 CLI 계획 파일·브라우저·프로세스·렌더 검사는 실행하지 않았다. 승인된 쓰기 범위는 이 보고서 하나다.

## 2. Figma → 현재 토큰/컴포넌트 → 변경 요구 1:1

경로 약칭: `W = prototype/web/src/`, `T = docs/design/tokens.json`. ‘보존’도 후속 구현 수용 조건이다. 각 행의 정적 관찰과 작업자 도출은 구분하며, 코드 위치는 실행 증거가 아니다.

| 결정 | Figma 근거 | 현재 토큰·컴포넌트/규칙 | 후속 변경 요구와 작동 영향 경계 |
|---|---|---|---|
| D01 그래프 전용 바탕 | F01·F02·F04·F06의 회색 캔버스 | `T color.neutral.surface-base`; `domain/graph-canvas.tsx`는 `bg-surface-base`, `graph-elements.ts`도 surface-base를 읽음 | **원본 관찰+도출:** 그래프 캔버스 역할 `color.graph.canvas`를 분리한다. 앱 전체 배경을 회색 지도색으로 바꾸지 않는다. 전체/기업/회차 그래프가 같은 역할을 사용한다. |
| D02 기업 로고 원 | F01·F02·F04의 흰 원과 실제 브랜드색 로고 | `lib/graph-visuals.ts companyFill/companyGlyph/logoGlyph`, `domain/graph-elements.ts visualOf`, `graph-canvas.tsx`의 비동기 glyph; 기존은 상징색 채움+단색 실루엣 | **사용자 확정:** 그래프는 흰 원+보존된 로고 색/도형을 쓴다. `source-in` 단색 칠하기를 이 역할에 적용하지 않는다. asset 미제공/실패는 이니셜이며 다른 회사 로고를 대입하지 않는다. ID·연결·선택은 바꾸지 않는다. |
| D03 목록과 헤더 역할 분리 | F09 목록·F11 DS는 상징색 원; F04 기업 헤더·F03 패널은 흰 표지 계열 | `domain/company-mark.tsx`의 동일 mask 표지가 `company-header.tsx`, `companies-page.tsx`, `company-switcher.tsx`, 범례·관계 목록 등에 재사용됨 | **Main 확정:** 탐색 목록 CompanyMark의 상징색/이니셜은 유지한다. 그래프·기업 헤더는 흰 로고 역할을 사용한다. 동일 `companyFill` 값 전역 교체 금지. 재사용 구현 방식은 프론트 작성자가 기존 seam에 맞추되 시각 역할 원천은 하나다. |
| D04 검은 마름모 | F01·F02·F04의 작은 검은 diamond | `T color.graph.node-issue/node-glyph`; `graph-style.ts` 모든 노드 ellipse, 사건 32/36px+Zap; `graph-elements.ts issueGlyph`; 범례의 번개 원 | **사용자 목표:** 라이트에서 중성 검은 마름모로 바꾼다. 사건 라벨·범례 견본도 맞춘다. glyph 제거와 노드 shape 변경은 표현만이다. 기존 `kind=issue` 데이터가 주제 이슈로 바뀌었다고 주장하거나 event ID를 재해석하지 않는다. |
| D05 캡슐 제목 라벨 | F01·F02·F06의 흰 pill title | `graph-style.ts labelBackground`는 surface-base 92%, roundrectangle·2px padding; `graph-elements.ts issueCaption`은 target/label 두 줄 축약 | **사용자 목표+도출:** 그래프 라벨에 전용 surface/text/border/padding/shape 역할을 둔다. 수평 캡슐은 그래프 제목에 한정하고 모든 버튼·배지를 pill로 바꾸지 않는다. 실제 target/label을 사용하고 전체 제목은 패널/목록에 보존한다. Figma 뉴스 제목을 fixture가 아닌 실제 데이터처럼 삽입하지 않는다. |
| D06 선택·보유·관심 | F02의 중심 이중 윤곽·주변 dim, F03 선택 기업, F09 강조 행 | `graph-focus-ring`, `graph-node-mark`, `surface-selected`; graph-style의 focused/mark/watch/both, WatchToggle·ListRow | **도출:** 선택은 대비 있는 윤곽+굵기/상태 이름으로, 보유·관심은 서로 다른 고리 모양+접근성 이름으로 보존한다. 선택·keyboard focus·보유/관심을 하나의 검은 링으로 합치지 않는다. 틸은 필요 조건이 아니다. |
| D07 선 문법 | F01·F02·F13의 실선·점선과 선택 선 강조 | `graph-edge-involves/structurally-related/follows/shares-issue/label`; `graph-style.ts`와 `relation-type-tag.tsx EdgeGlyph` | **목표+보존:** monochrome 계열로 역할을 재매핑하되 관계 타입별 선 모양·방향과 요약/근거 연결을 유지한다. 원본에서 잘 안 보이는 화살표를 없앤 것으로 추정하지 않는다. SHARES_ISSUE를 공급·인과 관계로 이름만 바꾸지 않는다. |
| D08 라벨 충돌·line padding | F02는 라벨끼리, 라벨과 범례가 겹치는 정적 사례가 실제로 보임; F06 작은 그래프 오른쪽 제목 일부가 경계에 걸림 | `graph-declutter.ts` 실제 label bounds·2px GAP·선/노드 공통 culling; `graph-layout.ts` label tiers/overhang; `graph-canvas.tsx fitInsets/focusInsets/visibleViewport` | **접근성 보완:** 정적 겹침을 모방하지 않는다. pill의 padding·border·줄바꿈을 포함한 bounds로 다시 판단한다. 보호 대상 충돌은 제목이 읽히는 상세/목록을 제공하고 필요시 배치 여유를 조정한다. culling이 node/edge·카운터·근거를 삭제하지 않게 한다. |
| D09 흑백 행동 버튼 | F08 검은 로그인 CTA, F04 검색·hop 선택, F09 검색 | `T color.brand.primary/hover/active/foreground`; `ui/button.tsx buttonVariants` | **사용자 목표:** 주 행동을 흑백으로 전환한다. primary/default/hover/pressed/disabled/loading은 한 공용 variant에서 관리한다. 기존 brand-primary를 통째 치환하기 전에 행동·선택·상태 용도를 분리한다. provider API/요청/권한은 변경하지 않는다. |
| D10 내비게이션·탭 | F01 상단 활성 지도 밑줄, F04–F07 사건/문서/기업 정보 밑줄, F12 하단 5탭 | `ui/tabs.tsx`, `ui/segmented.tsx`, `ui/bottom-tab-bar.tsx`, `features/app-shell.tsx`; 활성 표시 brand-primary | **목표+보존:** 활성 표시는 중성 밑줄/면+굵기를 사용한다. Tabs는 내용 영역, Segmented는 모드 선택, 링크 내비는 경로 이동이라는 의미를 유지한다. 모바일 AI는 기존 창 동작이며 새 route가 아니다. 탭 키보드 이동·aria-selected/pressed/expanded는 유지한다. |
| D11 폼과 검색 | F08 이메일/비밀번호 라벨, F09 명시적 검색·clear, F04 좌측 검색 | `ui/input.tsx fieldBase`, `border-control/focus/error`; `login-page.tsx`, `companies-page.tsx` | **보존+도출:** 라벨·오류 연결·44px 높이·모바일 text-md 16px를 유지한다. Figma의 연한 외곽이 필드 식별 대비를 못 내면 border-control 역할이 우선이다. 외곽의 검은 선택 표시를 permanent focus로 구현하지 않는다. 검색 제출/Enter·clear 동작은 기존 기능을 재사용한다. |
| D12 간격·읽기 폭 | F09 중앙의 좁은 목록, F04–F07 좌측 전환/중앙 본문/우측 그래프 | `T spacing 1/2/3/4/6/8`=4/8/12/16/24/32px; `companies-page.tsx max-w-5xl`; `company-page.tsx Page`=272px sidebar, 1400px부터 360px graph | **도출:** 목록 읽기 폭은 더 좁게 조정할 수 있지만 원본 PNG에서 정확한 CSS 폭을 추출하지 않는다. 1440에서는 3열 역할, 390에서는 전환 시트+단일 본문+관계 요약을 유지한다. 현재 1280의 그래프 하단 배치를 원본 3열처럼 억지 압축하지 않는다. |
| D13 타이포 계층 | F03 대표 가격, F04 기업명/가격·보조 메타, F10 DS | `T typography.fontFamily.sans/fontSize/fontWeight/lineHeight`; `DESIGN.md` 6단계 | **사용자 확정+보존:** SUIT와 한글 폴백을 유지한다. 대표 제목 28px bold, 패널 제목/가격 22px semibold/bold, 섹션 18px semibold, 본문 15px·모바일 16px, 메타 13px의 기존 스케일로 매핑한다. 이는 Figma 실측값이 아닌 접근성 보존 매핑이다. 수치 tnum 유지, 한국어 본문 기본 자간을 우선한다. |
| D14 모서리 역할 | F08 작은 버튼/필드 모서리, F01 pill 라벨·원, F13 직선 패널, F12 시트 상단 | `T radius.none/sm/lg/full`=0/8/16/9999px; `DESIGN.md` full은 원만 허용 | **목표+도출:** full 허용 범위에 그래프 제목 캡슐을 명시한다. 평탄한 행/섹션은 유지하고 floating sheet/overlay와 control의 반경을 구분한다. 선택 행 테두리는 상태 경계이며 모든 행을 카드로 감쌀 이유가 아니다. 정확한 원본 반경은 미확인이다. |
| D15 기업 패널의 정보계층 | F03 기업명→표지/코드→상세 이동→가격/시점→1개월 차트→접힌 지표→모의 보유 | `features/node-panel.tsx`, `domain/company-summary.tsx`, `features/company-quote.tsx/company-metrics.tsx/company-holding.tsx` | **보존:** 각 정상 영역과 독립 조회 실패를 유지하며 흑백 표지/구분선으로 정리한다. 값 미제공을 0·예시 가격으로 채우지 않는다. 시세 시각·문서 발행·관계 확인 시각을 혼용하지 않는다. |
| D16 기업 탭의 데이터 경계 | F06 문서 10건, F07 정식 명칭/시장 세부구분/업종/대표/설립/홈페이지 | `company-page.tsx Tabs/CompanyInfo`, `features/company-documents.tsx`; 현재 info는 ticker/id 접두사/aliases/sector | **보존+미정:** 기존 탭을 재사용한다. 10건·대표명·설립일을 하드코딩하지 않는다. 공급이 확정된 필드만 표시하며 원천 추가는 backend/API 과제다. 기업 변경 시 기간/asOf/tab 유지·issue/bucket/open 초기화 계약을 스타일 수정으로 훼손하지 않는다. |
| D17 근거 overlay | F13 우측 창·scrim·출처/발행·인용·원문/지도 행동, F12 모바일 시트 | `ui/dialog.tsx/bottom-sheet.tsx/overlay-parts.tsx`, `features/overlays.tsx`, `domain/evidence.tsx` | **목표+접근성:** 출처→제목→저장 인용→원문/지도 행동의 읽기 순서를 유지한다. modal focus trap·Esc·닫기·호출자 복귀·손잡이 키보드 조작·배경 스크롤 억제를 보존한다. Figma의 우측 스타일을 모든 패널의 modality 변경으로 확대하지 않는다. |
| D18 금융 3중 표시 | F10의 빨강 ▲ +, 파랑 ▼ -, 보합; F04 가격/모의손익 | `T color.semantic.up/down`; `domain/status-labels.tsx PriceChange` | **접근성 보존:** 관측 등락만 색+부호+방향 아이콘+수치/상승·하락·보합 이름으로 표시한다. monochrome 버튼 목표는 up/down 제거 요구가 아니다. 통화·퍼센트 변환을 유지하고 null을 0%로 바꾸지 않는다. |
| D19 AI 판정과 문서 요약 | F10 긍정/부정/혼재/판단 보류의 중성 아이콘; F11 회차 판단; F06 문서 목록에는 실제 요약 증거 없음 | `domain/status-labels.tsx SentimentLabel`, `document-analysis.tsx`, `document-item.tsx`, `evidence.tsx`, `features/company-documents.tsx` | **S1 기능 우선+도출:** 같은 저장 산출물을 두 consumer에서 재사용한다. 판정은 중성 글자+서로 다른 아이콘+AI 표시이며 등락색/▲▼를 쓰지 않는다. 요약 주장별 근거·해석/한계·원문 비대체 고지는 별도 상태 예시로 확장한다. Figma 예시를 실제 AI 실행 결과로 주장하지 않는다. |
| D20 missing·error | F01 원문 설명 652-54 로딩/관계 없음/실패 구분, F12에는 그래프 노드가 보이지 않음, F10 null은 그리지 않음 | `ui/feedback.tsx` EmptyState/ErrorState/SkeletonRows, `domain/evidence.tsx` UnavailableEvidenceNote, `document-analysis.tsx` 상태 분기 | **도출:** 정상 0건·미제공·조회 중·실패·withheld를 구분한다. 이미지에 없는 오류 상태를 Figma 완료 증거로 세지 않는다. `없으면 숨김`은 failed/권한 철회/0건 안내까지 삭제하는 규칙이 아니다. |
| D21 기존 상태 페이지 확장 | F10·F11은 실제 DS 목차와 컴포넌트 예시 | `App.tsx`에 `/design-system` 존재; `pages/design-system-page.tsx` toc·Demo·StateRow·ColorTable·GraphCanvas | **확정 범위:** 기존 route/실제 컴포넌트를 확장한다. 새 DS route·가짜 div 그래프·별도 샘플 버튼 라이브러리를 만들지 않는다. 아래 IA는 앱 기능 상태를 실제 primitive와 합성 표본으로 설명하는 문서 surface다. |

## 3. 공용 토큰 역할과 재사용 규칙

### 단일 원천

현재 단일 값 owner는 `docs/design/tokens.json`이다. `prototype/web/scripts/build-tokens.mjs`가 `src/styles/tokens.css`와 `tokens.generated.ts`를 생성한다. 생성 파일을 손으로 수정하지 않는다. `DESIGN.md`, `components/README.md`, DS 페이지의 수동 설명은 계약을 설명하는 자료이며 별도 값 원천이 아니다. 현재 DESIGN dialect는 프로젝트 자유형 Markdown+토큰 경로 참조이며, DTCG 원천을 다른 규격으로 변환할 이유는 없다.

아래 **신규 경로는 아직 존재하지 않는 제안**이다. 정확한 HEX/OKLCH는 Figma 변수 export 없이 ‘원본 값’이라고 선언하지 않는다. 동일 의미/테마의 값은 T 한 곳에만 둔다. 기존 생성기는 DTCG alias 해석기를 갖는다고 확인하지 못했으므로 `{color...}` 문자열을 무작정 넣지 않는다. 다음 작성자는 현재 생성 패턴에 맞는 실제 값 기록을 우선하고 역할의 관계를 description/문서로 보존한다.

| 역할 | 현행 경로 → 후속 owner 역할 | 라이트 매핑 원칙 | 다크 매핑 원칙·출처 상태 |
|---|---|---|---|
| 앱 바탕/읽기 면/overlay | `color.neutral.surface-base/raised/overlay/sunken` | 중성 앱 바탕, 흰 읽기 면, 구분선으로 계층 분리 | 현재 저채도 중성 면 계층을 출발점으로 유지. Figma dark 원본은 없음: **derivation** |
| 주 행동 | `color.brand.primary*`의 행동 소비 → 신규 `color.interaction.action-primary`, `action-primary-hover`, `action-primary-active`, `action-primary-foreground` | 중성 검은 면+밝은 글자, hover/pressed도 중성 단계. 흑백이라는 방향은 확정, 정확한 값은 도출 | 밝은 중성 면+어두운 글자 권장. disabled는 전용 면/글자. **derivation** |
| 링크 | brand-primary의 링크 소비 → 신규 `color.interaction.link` | 중성 글자+underline/명시적 링크 문맥. 색만으로 링크를 구별하지 않음 | 밝은 중성 글자+underline. **derivation** |
| 활성 표시/선택 면 | `color.neutral.surface-selected` + 신규 `color.interaction.selection-indicator` | 틸 면 대신 중성 선택 면, 검은 밑줄/외곽·굵기 | raised보다 구분되는 중성 면+밝은 indicator. **derivation** |
| 키보드 포커스 | `color.neutral.border-focus` | 대비 있는 중성 focus, 기존 2px+2px offset 유지 | 주변 면과 3:1을 내는 밝은 중성 focus. 선택과 동일 상태로 합치지 않음. **derivation** |
| 성공/진행 | brand-primary의 toast/admin 성공·진행 소비 | 행동색에 묶지 말고 상태의 텍스트/체크/진행 길이로 의미 유지 | 중성 전경·상태 문구로 유지. 원본 상태 값은 없음: **derivation** |
| 그래프 바탕 | surface-base → 신규 `color.graph.canvas` | F01 회색 캔버스 방향. 페이지 바탕과 독립 | 앱의 어두운 canvas 계층. **derivation** |
| 그래프·헤더 기업원 | 신규 `color.graph.company-surface/company-border/company-fallback-text` | 흰 surface+필요한 윤곽, 로고 자체 색은 UI 토큰으로 치환하지 않음 | 흰 로고 island 유지, 바깥 어두운 캔버스와 윤곽/선택 링 구분. **derivation** |
| 탐색 목록 기업 표지 | 기존 `color.graph.company-fallback.1..8`·받은 brandColor | 원본 F09/F11의 상징색/이니셜 유지 | 기존 대비 보완 유지. brandColor와 up/down/AI 색을 혼용하지 않음. **derivation** |
| 마름모 | 기존 `color.graph.node-issue`를 표현 역할로 갱신 | 중성 검은 diamond; 번개 glyph를 계속 얹지 않음 | diamond 형태를 유지한 밝은 중성 mark 권장. 검은 mark를 어두운 canvas에 묻히게 하지 않음. **derivation** |
| 그래프 라벨 | 신규 `color.graph.label-surface/label-text/label-border` | 흰 캡슐+어두운 글자+필요한 border | 밝은 label island+어두운 글자 권장. **derivation** |
| 그래프 선택/보유/관심 | `color.graph.focus-ring/node-mark` | 흑백 윤곽과 서로 다른 고리 모양 | 흰 기업 island 밖 canvas와 island 양쪽에서 분리되도록 이중 대비 검토. **derivation** |
| 관계선 | 기존 `color.graph.edge.*` | monochrome 계열 값으로 교체하되 타입별 dash/arrow 보존 | 각 선/화살표가 canvas 위에서 식별되는 중성 단계. **derivation** |
| 관측 등락 | 기존 `color.semantic.up/down` | 기존 빨강/파랑 역할 유지, 부호/아이콘 병기 | 기존 dark up/down 역할을 출발점으로 실제 resolved 대비 측정 |
| 경고·오류 | 기존 `color.semantic.warning/error` | 상태 아이콘+문장, 폼 오류 연결 유지 | 현재 dark 역할을 출발점으로 실제 resolved 대비 측정 |
| AI 판정 | 기존 `text-primary/secondary`, AI 표지 | positive/negative/mixed/undetermined는 중성 글자와 아이콘 | 같은 의미 규칙 유지. 금융 등락 역할을 재사용하지 않음 |

`brand-primary`가 현재 행동뿐 아니라 내비·미니맵·체크박스·튜토리얼·성공 상태까지 담당한다. 따라서 ‘검은색 하나로 값만 교체’하면 상태 의미까지 우발적으로 바뀐다. 위 역할 분리 후 모든 소비자를 옮기고 더 이상 의미가 없는 brand-primary UI 경로/설명은 제거한다. 목록 회사 상징색은 독립 데이터/폴백 역할이므로 남는다. 구 이름 alias/re-export를 영구 호환 계층으로 남기는 안은 제안하지 않는다.

### 치수와 재사용

- **타입:** 기존 SUIT sans stack과 13/15/16/18/22/28px 스케일, 400/500/600/700 weight를 사용한다. 본문 `leading-normal` 1.5, 긴 인용 `leading-relaxed` 1.625를 출발점으로 삼는다. 폼은 390에서 16px, 메타·그래프 라벨은 화면에서 최소 13px를 유지한다. `tracking-tight`의 현행 ‘한글 본문 보정’ 설명은 원본 실측 근거가 없으므로 후속 계약에서는 본문 기본 tracking을 우선하고 제목의 국소적 적용만 구분한다.
- **간격:** 역할 매핑의 기본안은 inline 8px(`spacing.2`), 행 요소 사이 12px(`3`), 패널 inset/모바일 gutter 16px(`4`), 데스크톱 reading inset/영역 사이 24px(`6`), 큰 섹션 사이 32px(`8`)다. 모두 작업자 도출이며 Figma 실측값이 아니다. 행 높이는 내용·44px hit area에 따라 늘어나야 한다.
- **shape:** `radius.none`은 행·읽기 섹션, `sm`은 컨트롤, `lg`는 떠 있는 면, `full`은 원/그래프 캡슐에 한정한다. graph label padding/마름모 크기/선 폭/카메라 occlusion은 그래프 표현 역할로 기록한다. 노드 크기를 데이터 중요도 산식으로 토큰화하지 않는다.
- **표지:** 흰 기업원은 같은 표지를 쓰는 그래프/헤더 범위에 공통 적용한다. 탐색 목록의 상징색 표지를 같은 함수 값 교체로 침범하지 않는다. 두 역할의 차이는 승인된 원본 차이다. 로고 파일 자체를 흰색·검은색으로 재작성하지 않는다.
- **행:** 기업/사건/문서 1건의 읽기 그룹은 행+divider+여백을 사용한다. 동일 행의 상세 링크·지도·관심 저장은 각각 독립 control이며 버튼/링크를 중첩하지 않는다. F09의 선택 외곽은 persistent selected 또는 focus 중 무엇인지 불명확하므로 실제 상태에 연결하고 둘을 서로 다른 신호로 만든다.
- **AI/근거:** `DocumentAnalysis`, `SentimentLabel`, `EvidenceQuote`를 실제 consumer에서도 재사용한다. DS만 다른 성공/실패 라벨을 만들지 않는다. 공통 의미/예외는 가장 작은 기존 공용 primitive에 반영한다.
- **모션:** 정적 Figma는 timing을 확정하지 않는다. 기존 motion duration/easing·카메라 취소/재타게팅을 유지하는 것이 기본이며 reduced motion에서는 즉시 전환한다. 시각 전환 때문에 노드가 매번 새로 퍼지거나 decorative entrance가 늘어나면 안 된다.

### 접근성 수용 기준 — 실제 측정은 후속 Main 검증

일반 글자/메타/가격 보조 표시는 resolved fg/bg 4.5:1 이상, 큰 글자와 조작 식별에 필요한 비텍스트 경계/선택/포커스는 해당 조건에서 3:1 이상을 요구한다. 단순 장식 divider에 동일 기준을 강제하지 않는다. 로고 자체의 상표색과 대체 이름을 구분하고, 기업원의 조작 윤곽·이니셜은 읽혀야 한다. 선택·흐림 상태의 합성 opacity 이후 대비도 확인한다. 이 보고서에는 새로운 contrast pass 수치가 없다.

터치 가능한 모든 버튼·탭·아이콘·시트 손잡이·그래프 직접 선택 대상은 **44×44 CSS px 이상**의 실제 hit area를 확보하고 인접 영역이 겹치지 않게 한다. 작은 검은 마름모의 painted size를 44px로 키워 정적 디자인을 훼손할 필요는 없지만 hit slop/대체 목록을 제공한다. 현재 기업원의 축소 화면 최소 28px 규칙과 사건 32/36px 모델 크기는 이 목표를 자동 충족하지 않는다. 다중 후보가 겹칠 때 임의로 가까운 대상을 확정하지 않고 선택 가능한 목록으로 이어지는 경로를 둔다. 키보드 대체만 있다는 이유로 터치 기준을 면제하지 않는다.

## 4. 활동·중심·카운터·실데이터 결합 원칙

F01에는 `NVIDIA / 중심 관계`, 상단 `기업 26 · 사건 138 · 사건 공유 38`, 내부 `24 COMPANIES · 18 SHARED EVENTS`가 동시에 보인다. 원본 설명 node **652-54 및 652-50**은 ‘크기=활동’과 비인과/비중요도 원칙의 정합성을 확인 대상으로 기록한다. F02 확대 상태의 설명 **652-62**도 크기·거리로 인과/중요도를 판단하지 말라고 적는다. 이 사실은 시각 방향을 거절하는 이유가 아니라 **데이터 의미를 발명하지 않을 이유**다.

| 미정 의미 | 보수적 결합 원칙 | 금지 사항 |
|---|---|---|
| 크기=활동 | 활동 정의·시간창·집계 단위·결측 처리·크기 scale이 명시되기 전에는 종류/선택/줌/읽기 확보에 필요한 고정 표현 크기만 쓴다. 범례는 크기가 활동/중요도/인과를 뜻한다고 주장하지 않는다. 정확한 Figma 크기 비율은 값 명세 후 반영한다. | degree·기사 수·evidenceCount를 임의로 활동점수나 중요도에 대응시키는 산식 |
| 중심 표제 | 선택 또는 명시적 focus가 있는 경우 그 기업명과 실제 탐색 범위를 표시한다. 미선택 시장 전체는 시장 전체 맥락으로 읽히게 한다. 원본의 NVIDIA는 예시 위치에만 남긴다. | 시장 전체 진입마다 NVIDIA를 자동 중심으로 정하거나 사용자 선택 없이 focus 상태를 생성 |
| 전역/지역 count | 기존 GraphLegend의 입력 graph 노드/간선 집계를 보존한다. local count는 실제 focus subset/범위 계약이 확정됐을 때 별도 이름·범위 설명을 붙인다. 화면 밖으로 pan하거나 라벨을 cull해도 데이터 개수는 바뀌지 않는다. | 26/138/38 또는 24/18을 고정값으로 넣거나 viewport 안 요소 수를 ‘전체’로 표현 |
| 연결 없는 묶음 | 실제 isolatedIssues 결과를 사용한다. 묶음은 사건을 숨겨 버리는 삭제가 아니며 내용 목록과 개수 접근성을 제공한다. | 원본의 41을 임의로 표시, 묶음을 새 업무 노드 종류로 API에 추가 |
| 관계 라벨 | 받은 summary/target/label과 근거를 사용한다. 전체 문장은 패널·목록에서 확인한다. | ‘HBM4 공급 계약’ 등 원본 제목을 실제 저장 기사에 덧붙이는 보정 |
| 기업 정보 | 공급 계약이 확보된 기업 데이터만 표시한다. 필드별 누락과 영역 조회 실패를 분리한다. | 캡처의 대표명·설립일·홈페이지를 실제 catalog 값인 것처럼 사용 |

정적 디자인과 진짜 데이터의 수가 다르면 노드/행을 Figma 개수에 맞춰 늘리거나 삭제하지 않는다. 목적은 원본의 **정보계층과 시각 문법**을 유지하면서 실제 graphVersion/asOf/회사/근거 참조를 그대로 전달하는 것이다. schema/enum/AI S2 변경은 Main의 별도 데이터 계약이 선행하며 이 보고서가 승인하지 않는다.

## 5. 기존 `/design-system`의 전체 컴포넌트 상태 페이지 IA

`W/App.tsx`에 공개 `/design-system`이 이미 등록되어 있고 `W/pages/design-system-page.tsx`는 toc 12개, `Demo`, `StateRow`, `ColorTable`, 실제 GraphCanvas와 overlay 상태를 갖는다. F10/F11도 이 구조를 보여 준다. **새 route를 만들지 않고 같은 페이지의 목차/앵커와 실제 컴포넌트 예시를 확장**한다. 아래는 후속 구현 IA이며 구현됐다는 뜻이 아니다.

공통 예시 단위: `컴포넌트명 → 쓰는 상황 → 실제 상태 표본 → 사용 예/공용 파일 → 값의 출처·확정 상태`. 콘텐츠는 명백한 합성 예시이며 production API·AI worker·외부 원문 요청을 실행하는 버튼을 상태 페이지에 달지 않는다. 실제 컴포넌트를 합성 입력과 국소 UI callback으로 보여주는 것은 허용하지만 이를 실제 저장/분석 성공 증거로 세지 않는다. 제품 consumer의 통합 검증은 별도다.

| IA/기존 anchor 연결 | 반드시 보여 줄 상태/표본 | 재사용 owner와 범위 |
|---|---|---|
| 원칙 `principles` | 사용자 확정/원본/도출/미정, 예시 데이터 안내, 라이트/다크 derivation 구분 | 현재 Section 틀·기존 안내를 재사용 |
| 색 `colors` | 앱 면/행 면/overlay/행동/선택/focus/그래프/등락/경고·오류의 실제 resolved fg/bg 쌍; 라이트·다크·hover/pressed/disabled | `tokens.generated.ts` 표, ColorTable. 정확한 값의 owner는 T |
| 타입 `typography` | 6단계·4굵기·본문/인용 leading·한국어 긴 기업명·희귀 음절 폴백·통화/등락/KST tnum·200% 글자 확대 | 기존 SUIT만. 새 font specimen/다운로드 불필요 |
| 간격 `spacing` | inset/inline/stack/section 역할, dense/long row, 44px painted와 hit area 차이, 인접 버튼 간 충돌 | 기존 spacing scale·Button hitArea를 보여 줌 |
| 형태 `shape` | 직선 행, 작은 control, floating 면, 원/마름모/캡슐; selected와 focus를 별도로 | 기존 반경과 graph shape 역할. pill=기본 버튼이라는 일반화 금지 |
| 행동 `components#c-button` | primary/secondary/ghost/link × default/hover/focus-visible/pressed/disabled/loading, icon name, 긴 라벨 | `ui/button.tsx`. hover/focus는 실제 입력으로 관찰 가능한 상태이며 가짜 정적 클래스만으로 검증하지 않음 |
| 폼 `components#c-input`, `#c-select` | 입력 없음/입력 중/값 있음/clear/disabled/error/submitting; checkbox checked/unchecked/invalid/disabled; 선택 열림/닫힘/키보드 | `Input`, `Select`, 현재 checkbox 소비자 패턴. label/description/error 연결 유지 |
| 모드·내비 `components#c-tabs`, `#c-appbar` | Tabs와 Segmented 구분, selected/unselected/focus/disabled/locked, 상단 현재 route, 하단 지도·종목·브리핑·AI·내 종목; AI 창 열림/닫힘 | `tabs.tsx`, `segmented.tsx`, `bottom-tab-bar.tsx`, app-shell 계약. AI 버튼을 링크처럼 바꾸지 않음 |
| overlay `components#c-dialog`, `#c-popover`, `#c-toast` | Dialog/Sheet/BottomSheet open/closed, 모바일 half/full, keyboard 손잡이, 긴 내용 스크롤, focus 복귀, Popover/Tooltip의 터치 차이, 결과 알림 | 기존 Radix primitive와 overlay-parts. 선택 패널과 modal의 의미 구분 |
| 목록 `components#c-listrow` | 기본/hover/selected/focus, 상징색 CompanyMark/미제공 logo/이니셜, 긴 한글/영문명, quote 없음, 보유+관심, 상세/지도/관심 독립 control | 실제 ListRow/CompanyRow/CompanySwitcher 표본. 작은 캔버스 목록은 실제 node 선택에 연결 |
| 그래프 `graph` | 기업/마름모/묶음, white logo vs colored list 역할, 선 타입·방향, 평소/hover/selected/keyboard-selected/focus1/focus2/path/evidence, 필터 숨김, zoom out/210%/pan/fit, labels cull·복원, 좁은 summary graph | 실제 GraphCanvas·GraphLegend·FocusBar·PathBar. 예시 graph 데이터로 실행하되 실제 기사로 오인하지 않음 |
| 근거 `domain#c-evidence` 확장 | verified/unverified/null verification, 원문 링크 있음/없음, 발행 시각 미상, 동일 문서 여러 인용, 일부 unavailable(403/404), 일부 network/5xx 실패, map toggle, 긴 인용 | EvidenceQuote/List/UnavailableEvidenceNote; 내용 접근 실패의 보호 규칙 그대로 |
| 문서 AI `domain` 아래 신규 문서 분석 anchor | summary available·sentiment available·한쪽만 available; positive/negative/mixed/undetermined; not_requested/pending/failed/withheld; null과 undetermined 차이; 원문 주장·해석·한계·근거별 이동; authored replay 합성 안내; version mismatch/철회로 결과 비공개 | 진행 중 S1 `DocumentAnalysis`/DocumentItem/SentimentLabel를 재사용. version/gate 오류는 서버 응답 상태를 소비하고 DS에서 새로운 정책을 만들지 않음 |
| 회차 판단 `domain` 기존 BriefingCard 예시 | 발행본 outlook 있음/null, mixed, 사유·근거 이슈, 주가 전망 아님 고지 | `BriefingOutlook`, `BriefingCard`. 문서 판정을 회차로 복사하지 않음 |
| missing/loading/error `components#c-skeleton/#c-empty/#c-error`와 domain 상태 교차 링크 | 정상 0건, 개인화 기준 종목 0개, 연결 없음, source unavailable, 일시 실패/재조회, invalid target, 부분 성공, 권한 필요, 분석 failed/withheld | EmptyState/ErrorState/SkeletonRows와 domain별 상태 owner. 0건을 오류로, 오류를 빈 목록으로 처리하지 않음 |
| 모션/아이콘/라이팅/체크리스트 `motion/icons/writing/slop` | 기본/reduced motion, interrupt/재타게팅, 같은 의미의 lucide, 이름/tooltip/popover, 금융·AI 혼동 방지 | 기존 절을 유지. Figma가 확정한 graph pill/검은 버튼을 이전 slop 금지로 차단하지 않도록 해당 범위의 설명을 정정 |

390에서는 목차를 페이지 폭 안에서 선택 가능한 control로 전환하고 하나의 읽기 열을 유지한다. 1440에서는 sticky 목차와 읽기 열을 유지한다. 기존 anchor 링크를 의도 없이 깨지 않는다. 표의 국소 가로 스크롤은 제목/접근성 이름/keyboard 접근을 갖추고 페이지 자체의 가로 넘침과 구분한다. 모든 실제 상태는 해당 컴포넌트에서 지원하는 의미만 보여 주고, 버튼에 의미 없는 error variant를 새로 만들지 않는다.

현재 예시의 `Input error="관심 종목을 1개 이상 골라 주세요."`는 0개 허용 기준과 맞지 않는다. 후속 DS 정리 시 실제로 유효한 입력 오류 예시로 교체한다. 이 관찰은 코드 읽기 근거이며 이번 보고서에서 UI를 고친 것은 아니다.

### 문서 AI missing/error의 표시 원칙

현재 진행 중 S1 코드 읽기 시 `DocumentAnalysis`는 미요청·결과 없음에 빈 자리를 만들지 않고, available 산출물·failed·withheld를 구분하며 authored replay를 합성 문서에 한정한다. 이 동작을 외형 전환에서 유지한다. pending은 유효 결과가 아니라는 뜻이며 상태 영역이 있는 문맥에서만 짧게 읽힐 수 있다. API 조회 중에는 기존 SkeletonRows, API 실패에는 ErrorState와 **조회 재시도**를 사용한다. 요약/판정 failed 문구에 사용자용 ‘분석 다시 실행’ 행동을 자동으로 추가하지 않는다. S1 소비자 조회·근거 열기·팝오버는 새 분석/유료 모델 호출을 트리거하지 않는다.

`null`은 유효 산출물 없음이고 `undetermined`는 평가됐으나 방향을 판단하기 어렵다는 뜻이다. `withheld`는 결과 본문을 표시하지 않는 별도 상태다. 원문을 못 열어도 서버가 공개한 저장 인용/메타를 유지할 수 있지만 403/404로 접근 불가한 근거의 본문은 보여 주지 않는다. 합성 예시 판정을 실제 기사에 붙여 설명하는 fallback을 만들지 않는다.

## 6. 후속 변경 순서와 파일 영향 경계

아래는 Main이 배정할 구현 순서 제안이다. 이번 보고서는 코드 변경 권한이나 배정을 대신하지 않는다.

1. **S1 consumer 완성:** `features/company-documents.tsx`, `domain/document-item.tsx/document-analysis.tsx/evidence.tsx`, `features/overlays.tsx`에서 저장 요약·문서×기업 판정·근거 이동을 완성한다. 공용 틸 토큰을 이 단계에서 바꾸지 않는다. backend 계약·worker·wire schema는 해당 owner가 유지한다.
2. **공용 owner 한 명 지정:** Figma 전환 시 T, build-tokens generator, DESIGN.md, components README의 계약 변경은 하나의 공용 디자인 시스템 owner가 묶어서 맡는다. 페이지 작성자가 임의 HEX·별도 CSS 변수로 동일 역할을 복제하지 않는다. 기존 사용자 변경과 S1 owner 변경은 보존한다.
3. **역할 분리 후 값 이동:** 행동/링크/선택/focus/성공/그래프를 분류하고 새 역할을 canonical T에 기록한다. 변경 단계에서 모든 관련 caller를 같이 옮기고 생성물을 갱신한다. 반쪽 전환용 전역 alias나 오래된 brand UI 경로를 영구 유지하지 않는다. Figma 값 export가 없는 부분은 도출 값이라고 기록한다.
4. **UI primitive 일괄 전환:** Button/Input/Select/Tabs/Segmented/BottomTabBar/ListRow/overlay를 같은 역할로 맞춘다. size·disabled/loading·aria·focus 동작은 보존한다. 먼저 단일 `/design-system`에서 상태를 드러내고 제품 route별 임시 스타일을 만들지 않는다.
5. **표지·그래프 함께 전환:** `lib/graph-visuals.ts`와 `domain/company-mark.tsx/company-header.tsx`, `graph-elements/style/legend`를 역할 범위대로 조정한다. GraphCanvas의 비동기 logo 로딩·cache·theme 갱신과 연결하고 node shape에 맞게 label/line bounds·layout/padding/culling을 같이 다룬다. 전체 지도·기업 그래프·회차 그래프는 동일 GraphCanvas 표현을 소비한다.
6. **제품 레이아웃 반영:** companies/login/company panel/company tabs/app shell을 원본 계층에 맞추되 조회·기간/asOf·뒤로 가기·권한·근거를 유지한다. 기업 metadata와 소셜 provider의 실제 연결은 별도 데이터/인증 계약이며 스타일 완료로 승격하지 않는다.
7. **문서와 화면계획서 동기화:** 후속 구현 완료 시 DESIGN.md와 components README의 ‘모든 노드는 원’·‘틸 주 행동’·‘full은 원만’ 및 DS의 GraphDB 설명을 실제 목표로 갱신한다. `design-direction.md`의 과거 값/현재 규칙을 혼동하지 않도록 적용 절을 표시한다. 영향 화면을 재캡처하고 기존 화면계획서 index/deck에 반영한다. 새 공식 화면 ID를 임의로 늘리지 않는다.
8. **Main의 한 번 통합 검증:** 모든 owner 변경이 합쳐진 뒤 아래 행렬을 검증한다. 이 보고서를 작성한 design worker는 build/test/lint/formatter/browser를 실행하지 않았다.

### token caller 분류 — 전역 문자열 치환 금지

`W` 아래 현재 `brand-primary|border-focus|surface-selected|graph-focus-ring` 텍스트 검색의 영향 주소를 역할별로 정리했다. symbol-resolved 전체 호출 그래프 증명은 아니며, 후속 owner는 작업 시점의 변경분까지 확인해야 한다. generated CSS/TS는 소비자 수정 대상이 아니라 재생성 대상이다.

| 역할 | 확인된 파일군 |
|---|---|
| 행동/링크 | `ui/button.tsx`, `domain/document-item.tsx/evidence.tsx/feedback-buttons.tsx`, `features/chat-job-view.tsx/company-quote.tsx/node-panel.tsx/company-price-chart.tsx`, `App.tsx`; 관리자 `admin-root.tsx`, pages의 feedback/members/member-detail/stats/stats-company/transcript, pipeline/candidates |
| 내비/선택/체크 | `features/app-shell.tsx/chat-drawer.tsx/company-graph.tsx/company-timeline.tsx`, `ui/tabs.tsx/segmented.tsx/bottom-tab-bar.tsx/list-row.tsx/select.tsx`, `domain/company-search.tsx/watch-toggle.tsx/relation-list.tsx/feedback-buttons.tsx`, `pages/onboarding-page.tsx/signup-page.tsx/briefing-page.tsx/design-system-page.tsx`, `admin/layout.tsx/pipeline/versions.tsx/paid-run-dialog.tsx` |
| keyboard focus/튜토리얼 | `styles/index.css`, `ui/input.tsx/select.tsx`, `admin/reason-dialog.tsx`, `features/graph-tutorial.tsx` |
| 그래프 선택/미니맵/도구 | `domain/graph-style.ts`, `domain/graph-canvas.tsx`; 미니맵 viewport의 기존 brand-primary/10 채움도 별도 선택 역할로 이동 |
| 성공·진행·설명 | `ui/toast.tsx/icon-hint.tsx`, `admin/ui.tsx/insights-ui.tsx`, `features/graph-tutorial.tsx` |

관리자와 튜토리얼에도 공용 토큰 영향이 있다는 이유로 새로운 기능·운영 행위를 구현하지 않는다. 단지 같은 의미의 색을 사용하는 caller가 전환에서 누락되지 않도록 경계를 표시한 것이다.

## 7. 1440/390 상태 캡처와 그래프 회귀 수용 목록

**모두 후속 Main/프론트가 확보할 증거 목록이며 이번 실행 결과가 아니다.** 기준은 데스크톱 **1440×900**, 모바일 **390×844 CSS px**다. 고정 Figma 수집 viewport와 혼용하지 않는다. 기본적으로 라이트와 다크를 각각 캡처하고 dark는 ‘Figma 원본 없음·derivation’이라고 기록한다. 캡처 metadata에는 route/query, viewport, theme, 데이터 출처, graphVersion/asOf 또는 합성 fixture ID, 상태, 입력 방식, 구현 revision을 남긴다. 비밀값·개인정보는 제외한다.

| 캡처 묶음 | 1440 상태 | 390 상태 | 원본/결정 연결 |
|---|---|---|---|
| 로그인 | default, 입력 focus, 필드 error, submitting/disabled, provider 실패·취소 안내(지원 contract 안에서) | 같은 상태, 입력 16px·44px·키보드 화면 | F08 / D09·11·13 |
| 종목 목록 | default 검색, 0건, 실패, selected와 keyboard focus 분리, 보유+관심, 긴 이름, quote null | 독립 상세/지도/관심 대상이 겹치지 않는 행, 로그인 안내, 검색 clear | F09 / D03·06·11·12 |
| 전체 지도 | fit/default, zoom out, 210%, pan, hovered/selected company·diamond·edge, filtered types, isolated bundle | 같은 데이터의 fit/zoom/pan, 직접 44px 선택과 목록 대안, toolbar와 tabbar 안전 여백 | F01·02 / D01–08 |
| focus/path/evidence | focus1/focus2, exit 위치 복귀, 두 기업 path 있음/없음, 근거 선택·해제, 미니맵 있음 | sheet half 상태에서 focus/path fit, 단계 목록, sheet full, exit/뒤로 가기 | D06–08·17; 상세 경로 동작은 기존 계약 유지 |
| 기업 패널 | 정상, 지표 접힘/펼침, 시세 null/실패·문서 정상, 긴 기업명, 닫기·복귀 | half/full/닫힘, 손잡이 focus, 키보드 닫기와 호출자 복귀 | F03·12 / D15·17·20 |
| 기업 상세 | events/documents/info 각각; 1일/1주/1개월/1년·과거 asOf·버킷 선택·기업 전환·graph 1/2hop | 기업 전환 시트, 본문 후 관계 요약, 3개 tabs 균등·긴 정보값·지표 부분 실패 | F04–07 / D12·15·16 |
| S1 문서·근거 | stored summary+판정+claim 근거, 한쪽 available, failed/withheld, null/undetermined, 동일 artifact 여러 인용, 부분 근거 실패 | 같은 상태의 긴 인용·popover·근거 창, 비공개 내용 없음, 입력/창 닫기 뒤 복귀 | F06·10·13 + S1 도출 / D17·19·20 |
| DS 상태 페이지 | 색 쌍·타입·spacing·shape, 모든 primitive 상태, 그래프 표본, AI/missing/error; 실제 focus·hover 동작 | 목차·표 국소 스크롤·overlay·long content·44px | F10·11 / D21 |
| 접근성/모션 | 200% 글자 확대, keyboard-only journey, reduced motion, 필요시 forced colors | text resize·screen keyboard 안전영역·터치·reduced motion | 원본에 없는 접근성 도출 |

### 그래프 전환의 필수 회귀 항목

- **모양/표지:** 전체·기업·회차 그래프에서 기업은 흰 원/보존 로고, 두 번째 노드 종류는 라이트 검은 diamond다. 목록 CompanyMark가 흰색으로 오염되지 않는다. logo 없음/404/느린 로드/희귀 기업명은 이니셜/실제 이름으로 식별되며 blank logo mask에 갇히지 않는다. dark 로고 island·mark·선택 윤곽의 경계가 읽힌다.
- **선과 데이터:** INVOLVES·STRUCTURALLY_RELATED_TO·FOLLOWS·SHARES_ISSUE의 선 모양/방향, 병렬선, 화살표 끝, hover/selected/path summary와 실제 근거 참조를 확인한다. diamond 변경 뒤 선이 노드 내부를 지나거나 floating label에 잘못 붙지 않는다. ID/type·node/edge 수·근거 수·회원 범위가 스타일 변경 전후 같은 데이터 기준으로 보존된다.
- **line padding과 fit:** pill 여백·border·회사 이름·보유/관심 캡션·근거 배지·묶음을 포함하여 fit이 클리핑하지 않는다. 범례/중심 표제/도구/미니맵/우측 패널 occludeRight/모바일 half sheet/tabbar가 차지하는 실제 영역을 reserve한다. 중심 표제가 붙어도 전체 기본 지도에 강제로 focus를 주지 않는다.
- **culling:** `graph-declutter.ts`의 실제 renderer bounds가 새 캡슐 padding·shape·stroke·줄바꿈·회전·zoom을 포함하는지 확인한다. 현재 issue body는 obstacle에서 제외되어 있으므로 diamond와 읽기 라벨의 충돌 영향을 재평가한다. culling은 낮은 우선순위 라벨만 숨기고 실제 node/edge/count를 바꾸지 않는다. 선택/hover/focus-root는 보호하고 보호 라벨끼리 충돌하면 readable detail을 제공한다. 시각적으로 라벨이 없어도 목록에서는 전체 제목을 읽는다.
- **복원:** hovered/selected/evidence/path와 `.label-cull` 우선순위를 함께 확인한다. zoom/pan 후 정지, theme 변경, 로고 로드, 필터 토글, 목록→그래프 reveal, 창 resize 뒤 culling이 갱신되고 숨김 해제가 부당하게 모든 라벨을 다시 켜지 않는다. 테마 전환만으로 layout cache가 데이터 의미를 바꾸지 않는다.
- **안정성:** fit/selection/focus 진입·해제/뒤로 가기에 기존 layout memory와 주소 상태를 보존한다. 픽셀 마름모/캡슐을 맞추려고 force layout을 매번 다시 시작하지 않는다. 0개·일부 실패·truncated metadata를 실제 정상값과 구별한다.
- **접근성:** 44px target의 겹침/오선택, keyboard 관계 목록 선택, focus 표시/복귀, 이름과 현재 선택 live announcement, tooltip 터치 대체, reduced-motion 즉시 카메라·탭·시트 전환을 확인한다. canvas `role=img`만을 키보드 탐색 완료 증거로 세지 않는다.

현재 후속 검증의 시작점으로 `prototype/web/tests/graph-declutter.test.ts`, `company-graph-layout.test.ts`, `company-event-selection.test.tsx`, `company-detail-state.test.tsx`, `company-stale-responses.test.tsx`, `companies-menu.test.tsx`, `evidence-access-states.test.tsx`를 확인할 수 있다. 실제 test 범위 확장은 구현 owner가 새 shape/44px/산출물 상태의 invariants에 맞춰 정한다. build/typecheck·기능 테스트·접근성·시각 비교·console 확인·화면계획서 재캡처는 Main이 최종 통합 뒤 실행한다. 과거 pass 수치를 이번 전환의 pass로 재사용하지 않는다.

## 8. 제3자 asset의 출처·권리와 남은 결정

| 자산 | 확인한 출처/라이선스 | 전환/본개발 반영 규칙 |
|---|---|---|
| SUIT Variable 2.0.5 | `prototype/web/package.json`, 설치된 `@sun-typeface/suit/LICENSE`: SUNN 2022, Reserved Font Name SUIT, SIL OFL 1.1. [공식 출처](https://sun.fo/suit), [OFL](https://scripts.sil.org/OFL) | 기존 자체 호스팅 파일/폰트 stack 유지. 본개발 bundle에도 라이선스·copyright를 보존한다. 새로운 font research/download는 하지 않았다. |
| lucide-react | 설치된 `lucide-react/LICENSE`: ISC, 일부 Feather 유래 icon은 MIT notice도 포함. [프로젝트](https://github.com/lucide-icons/lucide), [라이선스](https://github.com/lucide-icons/lucide/blob/main/LICENSE) | 실제 설치 패키지의 notice를 보존한다. ‘모든 아이콘 MIT’로 단순화하지 않는다. 이벤트 Zap가 graph에서 빠져도 다른 의미의 UI icon을 무근거로 전면 교체하지 않는다. |
| 기존 기업 SVG | [public/logos/LICENSE.md](../../prototype/web/public/logos/LICENSE.md): Simple Icons 16.33.0에서 수정 없이 복사, CC0 1.0 도형, 브랜드별 source는 BFF fixture `brand_source`. [Simple Icons](https://github.com/simple-icons/simple-icons), [라이선스](https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md) | 저장 SVG의 원래 도형을 사용한다. 현재 기록은 **시연 목적**이며 CC0가 상표권 허가를 뜻하지 않는다. production 배포 전 회사별 brand guideline/표시 용도·권리 검토는 별도 인수 조건이다. |
| Figma 화면 속 추가 기업 로고 | F01–F07에 보이지만 개별 파일·license·출처 export는 미확인 | screenshot에서 로고를 잘라 앱 asset으로 배포하지 않는다. 기존 권리 기록이 있는 로고만 재사용하고 미확보 회사는 실제 이름/이니셜을 쓴다. 흰 원 방향 채택이 모든 원본 로고 사용허가를 뜻하지 않는다. |
| Google·카카오 sign-in 자산 | F08에는 generic 사용자 아이콘·문구가 보이며 실제 provider brand asset/production 연결은 미확인 | 실제 provider가 결정되면 그 제공자의 공식 sign-in 가이드/권리와 인증 계약을 따른다. 일반 monochrome 규칙으로 공식 provider 로고를 임의 재색칠하거나 연결되지 않은 버튼을 실제 login 완료로 주장하지 않는다. |
| SEED 모션 참조 | 현재 T/DS/README가 [SEED motion](https://seed-design.io/foundations/motion) 값을 참조한다고 기록 | 이번 보고서는 모션 파일/코드를 새로 수입하지 않았다. 별도 SEED 코드·asset을 도입할 때는 그 실제 원본 라이선스를 확인한다. 정적 Figma가 새 timing을 증명하지 않는다. |
| 고정 Figma PNG | 팀 화면 근거 수집본, acquisition 기록의 공개 읽기 | 로컬 설계/비교 evidence로 사용한다. 공개 접근이 외부 재게시·asset 재배포·댓글/편집 권한은 아니다. |

라이선스 표는 읽은 로컬 notice와 공개 출처 링크의 근거이며 이번에 외부 페이지를 재검증하거나 새로운 사용허가를 받았다는 뜻이 아니다. 별도 자산 다운로드·설치·외부 쓰기는 하지 않았다.

### 미정 항목과 영향

- **정확한 Figma 변수값:** 색·radius·line width·padding의 master export가 없다. final 방향은 이미 확정이며 이 때문에 흰 원/diamond/흑백 행동을 보류하지 않는다. 값은 도출로 표시하고 후속 실제 resolved 대비·시각 비교에서 인수한다.
- **활동 크기 산식/전체·지역 count:** Main/기획·데이터 owner가 의미를 확정할 때까지 §4의 무산식 원칙을 쓴다. 기존 카운터와 고정 크기/선택 크기를 사용하며 하드코딩하지 않는다.
- **모바일 빈 graph:** F12는 기업 시트 위 노드가 보이지 않는다. 빈 캔버스가 의도된 최종 UX라는 증거는 없다. desktop 시각 문법을 실제 모바일 graph 데이터에 적용하고 최종 mobile capture로 Main이 인수해야 한다. 장식 휴대폰 외곽·status bar는 웹 앱 요구가 아니다.
- **기업 metadata/실제 소셜 공급:** F07/F08은 필드/버튼의 목표이며 공급/인증 완료가 아니다. API owner의 실제 계약을 소비하고 미제공 상태를 정직하게 표시한다.
- **주제 이슈 S2:** graph의 diamond 목표와 도메인 전환은 별개다. Main이 확정한 대로 이번 문서/시각 전환에서 기존 kind/ID 뜻은 유지한다. S2 계약 채택 시 label/범례/시점/근거 consumer를 그 별도 계약과 다시 대조한다.

**인수 경계:** 이 보고서의 추천·근거·IA·후속 캡처 목록은 완료했다. 실제 스타일 cutover, dark theme의 새 resolved 대비, 키보드/터치·graph culling 회귀, S1 live/consumer 통합 성공, 본개발 채택·production asset 권리 확보는 이 보고서의 실행 완료가 아니다.
