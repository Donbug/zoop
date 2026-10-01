# 줍(Zoop) 참고 조사 — TDS · 당근 SEED · 폰트 · 모바일 패턴

| 항목 | 내용 |
|:--|:--|
| 작성일 | 2026-09-29 |
| 목적 | 프론트엔드 프로토타입의 AI 슬롭 제거, UX 흐름 개선, 모바일 UI 추가를 위한 **원리 추출**용 레퍼런스. 디자인을 베끼는 것이 목적이 아니다. |
| 조사 방법 | 1차 출처(공식 문서, 공식 GitHub, 공식 기술 블로그)를 직접 열람해 인용. 2차 매체는 리드로만 사용. |
| 표기 | 사실(출처 확인) / `[추론]`(원문에 없는 해석) / `[미확인]`(근거 확보 실패) |
| 선행 문서 | `docs/design/archive/design-direction-v1.md`, `docs/research/design-ux-research.md`, `docs/design/tokens.json`(조사 시점 v1 토큰. 줄 번호는 v1 기준) |

## 0. 접근 실패·한계 (먼저 읽을 것)

| 대상 | 상태 | 처리 |
|:--|:--|:--|
| `m3.material.io` 컴포넌트 페이지(bottom sheets 등) | 본문이 JS 렌더링이라 텍스트 추출 실패(내비게이션만 반환) | Material은 **내비게이션 바 페이지만** 인용. 바텀시트 상세 스펙은 SEED·Apple로 대체 |
| `developer.apple.com` HIG 직접 열람 | 메타데이터만 반환 | `r.jina.ai` 프록시로 본문 확보(프록시 경유 사실 명시) |
| `tossmini-docs.toss.im` 표(typography 토큰 값, 컬러 값) | 기본 추출기(trafilatura)가 표를 삭제, `.md` 확장자 미지원(404) | `r.jina.ai` 프록시로 표 텍스트 확보 |
| TDS Mobile **radius 파운데이션 문서** | 순회에서 확인된 파운데이션 문서는 Colors·Typography이며 radius 문서는 발견하지 못함 | TDS는 컴포넌트 문서의 형태 값으로만 관찰, radius 스케일은 SEED를 근거로 사용 |
| IBM Plex Sans KR의 한글 글리프 수·`tnum` 지원 | 1차 문서에서 확인 실패 | `[미확인]`으로 표기, 후보 보류 |
| Spoqa Han Sans Neo의 커버리지·숫자 기능 | README에 없음 | `[미확인]`으로 표기 |
| Pretendard의 한글 글리프 수(11,172자) | README에서 확인 실패(동적 서브셋 제공만 확인) | `[미확인]`으로 표기 |
| 국내 증권 앱의 **그래프형 네트워크 탐색** 공식 사례 | 토스증권 뉴스룸·홈페이지에서 관련 기능 언급을 찾지 못함 | "없다"고 단정하지 않고, 학술·연구 사례로 대체(§4.5) |
| 앱인토스 규칙의 적용 범위 | 앱인토스 미니앱 전용 규칙(토스 앱 안에서 노출되는 앱) | 줍은 독립 웹 앱이므로 **법적·계약적 강제가 아님**. 같은 사용자 기대 형성 근거로만 사용 `[추론]` |

---

## 1. 토스 디자인 시스템(TDS)

### 1.1 무엇이고, 무엇을 가져올 수 없는가

- TDS는 "토스 커뮤니티 전반에서 쓰는 디자인 시스템"이며, 앱인토스 개발자센터는 핵심 컴포넌트 11종(**Badge, Border, BottomCTA, Button, Asset, ListRow, ListHeader, Navigation, Paragraph, Tab, Top**)을 공개한다. 같은 문서는 "커스텀 UI를 직접 만들 때보다 3~5배 빠르게 개발할 수 있다"고 설명한다 — [TDS — 앱인토스](https://developers-apps-in-toss.toss.im/design/components.md).
- **라이선스 제약(중요)**: "지식재산권은 모두 토스에 있고, 파트너사는 앱인토스 서비스를 이용하는 범위 안에서만 이 자료를 쓸 수 있어요. … 앱인토스 서비스를 제공하기 위한 제한적인 권한" — 즉 **줍은 TDS 자산·UI Kit을 그대로 가져다 쓸 수 없다**(같은 문서). 원리·수치·패턴만 추출한다.
- TDS가 지향하는 목표는 "제품의 최소 품질 보장 / 생산성 향상 / 일관된 인터랙션·애니메이션·일러스트레이션" — [TDS 소개](https://tossmini-docs.toss.im/tds-mobile/).

### 1.2 색 체계

**팔레트 구조** (TDS Mobile Colors, 2026-03-09 문서 스냅샷):

| 계열 | 단계 | 대표값 |
|:--|:--|:--|
| Grey | 50~900 (10단계, 100단위) | grey50 `#f9fafb` · grey100 `#f2f4f6` · grey500 `#8b95a1` · grey700 `#4e5968` · grey900 `#191f28` |
| Blue | 50~900 | blue500 `#3182f6` (브랜드 링크 기본색) |
| Red / Orange / Yellow / Green / Teal / Purple | 각 50~900 | — |
| Grey Opacity | 50~900 | 반투명 회색(오버레이·딤) |

출처: [Colors — TDS Mobile](https://tossmini-docs.toss.im/tds-mobile/foundation/colors/). 문서가 별도로 공개하는 **배경 색상 토큰은 4종**뿐이다: `background`(#FFFFFF), `greyBackground`(=lightThemeGrey100), `layeredBackground`, `floatedBackground`(모두 #FFFFFF) — 배경은 "역할 이름"으로 좁게 정의하고, 나머지는 컴포넌트가 갖는다.

**7년 만의 컬러 시스템 개편에서 드러난 원칙** ([Toss Tech, 2025-12-15](https://toss.tech/article/tds-color-system-update)) — 줍의 색 토큰 설계에 가장 직접적으로 쓸 수 있는 문서:

1. **단계 이름이 같으면 밝기도 같아야 한다**: 개편 전에는 같은 `100`이라도 Grey100 대비 1.1:1, Red100 1.34:1로 제각각이어서 "전부 100으로 통일해도 얼룩덜룩"했다.
2. **라이트/다크는 같은 색의 두 벌이 아니다**: 같은 Teal50이 라이트 1.06:1, 다크 1.36:1로 다크에서만 튀었다.
3. **해법은 OKLCH(인지적으로 균일한 색공간)**: 명도를 통일해 "UI에서 사용되는 주요 컬러 조합들이 접근성 기준을 충족"하도록 보장. 숫자로 균일해도 노랑은 시각보정이 필요했다("The Dark Yellow Problem") — **수치 일관성 다음에 시각 검수가 온다**.
4. **다크 모드는 별도 명도 기준**: "다크모드에서 적절한 명도를 찾아, 다크모드만의 명도 기준을 세우게 되었어요. 다크모드에서는 명도대비를 더 강하게 가지도록 설계했어요." (APCA류 최신 대비 메트릭의 착시 보정 논의를 근거로 제시)
5. **시맨틱 토큰 + 테마 시스템**: 컬러는 값이 아니라 의미로 정의하고, 테마는 "특정 규약에 따라 스타일을 적용하거나 변경하는 것". 코드 생성 예시에 다크 모드 전환이 `:root[data-tds-color-scheme="dark"]` **데이터 속성 + CSS 변수**로 구현되어 있다.
6. **계열사·제품별 오버라이드**: TDS WTS(트레이딩 화면)에서는 "일반적인 화면에서는 파란색이 긍정적이고 Primary인데, TDS WTS에서는 빨간색이 긍정" — 같은 파운데이션 위에서 시맨틱만 바꾼다. **줍의 상승 빨강/하락 파랑과 정확히 같은 구조적 문제.**

문서에서 실제로 쓰이는 형태: 컴포넌트 문서 예제가 `adaptive.grey800`, `adaptive.green600` 같은 **테마 적응형 객체**를 사용한다([ListHeader](https://tossmini-docs.toss.im/tds-mobile/components/list-header/), [Paragraph](https://tossmini-docs.toss.im/tds-mobile/components/paragraph/)). `[추론]` 값이 아니라 "역할 + 테마" 두 축으로 색을 잡는 방식이 TDS의 핵심이며, 줍의 `--color-up/down` + `dark.*` 이중 정의와 같은 계열이다.

**브랜드 색 사용 규칙(앱인토스)**: 브랜드 컬러가 대비 기준을 못 맞추면 "기존 색상을 최대한 유지하면서 자동으로 보정"된다([UI/UX 가이드](https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md)). `[추론]` 강조색은 브랜드 1색으로 좁히고, 나머지 상태 전달은 회색 단계 + 형태로 처리하는 골격.

### 1.3 타이포 스케일과 굵기 대비

- 원칙: "Typography 토큰은 계층 구조를 가지고 있어요. **사용하는 입장에서 구체적인 폰트 크기와 라인 높이를 외우거나 직접 계산할 필요는 없어요**", 그리고 "**표에 나온 값을 직접 하드코딩하지 않길 권장해요**"([Typography — TDS Mobile](https://tossmini-docs.toss.im/tds-mobile/foundation/typography/)).
- 숫자 스케일(표, 프록시 경유로 확보): `Typography 1` 30/40(매우 큰 제목) → `Typography 2` 26/35 → `Typography 3` 22/31 → `Typography 4` 20/29 → `Typography 5` **17/25.5(일반 본문)** → `Typography 6` 15/22.5 → `Typography 7` 13/19.5(**문서상 "안 읽어도 됨"**) + `sub 1~13`(29→11px, 13px은 "아예 안읽어도 됨"). 즉 토스는 13px 이하를 **"읽히지 않아도 되는 정보"**로 명시적으로 분류한다.
- 더 큰 텍스트: iOS/Android 접근성 텍스트 확대 설정에 맞춰 웹에서도 동일 비율이 되도록 규칙을 만든다(예: 110%·Typography 1 = `30 × NN × 0.01` = 33). **값 하드코딩 금지**의 실질적 이유가 이것이다.
- 굵기는 4단계: `regular(400) / medium(500) / semibold(600) / bold(700)`([Paragraph](https://tossmini-docs.toss.im/tds-mobile/components/paragraph/)). 크기 단계는 많지만 굵기 단계는 좁게 운용한다.
- 서체 자체의 근거는 [토스피드, 2021-10-08](https://toss.im/tossfeed/article/beginning-of-tps): 국문·숫자·영문이 "서로 균형을 이루는 지점"을 찾는 데 집중했고, **디지털/금융이라는 맥락에서 숫자와 기호(퍼센트·쉼표·더하기·빼기·화살표)를 "UI 요소(아이콘)로 해석해" 더 크고 넓게** 설계했다.

### 1.4 라운드 규칙 (문서에서 관찰되는 것)

TDS Mobile 문서에 radius 스케일 표는 없다(`[미확인]`, §0). 대신 관찰되는 것은 **"무엇에 둥글기를 주지 않는가"**다:

- 페이지·페이지 탭·내비게이션처럼 이미 시스템이 정의한 자산에는 **임의 형태 변경이 금지**된다. 앱인토스 브랜드 로고는 "600×600px의 **각진 정사각형**이어야 해요. 모서리가 둥근 형태는 사용할 수 없어요"([UI/UX 가이드](https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md)).
- 컴포넌트 형태는 **속성값으로 제한**된다: Button `size` 4종(small/medium/large/xlarge) + `display`(inline/block/full) ([Button](https://tossmini-docs.toss.im/tds-mobile/components/button/)), Badge `size` 4종 + `variant`(fill/weak), ListRow `verticalPadding`(8/12/16/24px)·`horizontalPadding`(20/24px) ([ListRow](https://tossmini-docs.toss.im/tds-mobile/components/ListRow/list-row-overview/)).
- 구분은 라운드가 아니라 **선으로** 한다: `Border` 컴포넌트가 `full`(전체 너비) / `padding24`(좌우 24px 여백) / `height16`(구간 구분 = 빈 높이) 3종을 제공하고, "주로 리스트나 섹션을 구분하는 데 사용"한다([Border](https://tossmini-docs.toss.im/tds-mobile/components/border/)).

`[추론]` TDS에서 둥글기는 "가치를 표현하는 도구"가 아니라 컴포넌트 스펙에 이미 결정되어 있는 값이다. 슬롭의 "모든 것을 둥근 사각형으로 감싸는" 성향에 대한 TDS식 반대 명제는 **"카드로 감싸지 말고 행과 선으로 자른다"**다. (둥글기 스케일 자체는 §2.4의 SEED 토큰을 근거로 삼는다.)

### 1.5 리스트·바텀시트·하단 CTA·탭·토스트 패턴

| 패턴 | TDS 문서상 사실 | 줍에 주는 시사점 |
|:--|:--|:--|
| **ListRow** | `left` / `contents` / `right` 3영역. `border`=`indented`(들여쓴 구분선) 기본·`none`(연결감). `verticalPadding` small/medium/large/xlarge = **8/12/16/24px**. `withArrow`로 "다음 화면이 있다" 예고. `disabled` 2종(연한/진한). `Loader`는 실제 행과 **동일 레이아웃 스켈레톤**([ListRow](https://tossmini-docs.toss.im/tds-mobile/components/ListRow/list-row-overview/)) | 기업/이슈 행은 "카드"가 아니라 **행 + 들여쓴 구분선**. 로딩은 스켈레톤을 행 형태로 |
| **ListHeader** | `title` + `description`(위/아래 선택) + `right`(텍스트 또는 화살표, 기본 `adaptive.grey700`). 제목/우측 비율 `titleWidthRatio` 기본 **0.66**([ListHeader](https://tossmini-docs.toss.im/tds-mobile/components/list-header/)) | 헤딩 위 작은 라벨 대신 **헤더 컴포넌트가 제목·설명·우측 액션의 3슬롯**을 갖는다 |
| **BottomCTA** | `FixedBottomCTA`는 항상 하단 고정, `BottomCTA`는 고정 여부 선택. `Single`(버튼 1) / `Double`(버튼 2)로만 분기. `Double`에서 `hasSafeAreaPadding`을 켜면 "기기 화면 하단 SafeArea 높이만큼 paddingBottom이 추가"([BottomCTA](https://tossmini-docs.toss.im/tds-mobile/components/BottomCTA/check-first/), [Double](https://tossmini-docs.toss.im/tds-mobile/components/BottomCTA/Double)) | 하단 CTA는 **버튼 1~2개, 세이프 에어리어 자동 반영**, 그 이상 변형을 만들지 않는다 |
| **Tab** | `size` small/large. `fluid=false`면 "최대 4개의 아이템 사용을 권장", 4개 초과 시 `fluid`로 가로 스크롤. `role="tablist"`/`role="tab"`/`aria-selected` 자동, 알림은 `redBean`(빨간 점) + 스크린리더 "(업데이트 있음)"([Tab](https://tossmini-docs.toss.im/tds-mobile/components/tab/)) | 요약/관계도 같은 화면 내 전환은 **4개 이하 세그먼트 탭** |
| **Toast** | 버튼 없으면 **3000ms**, 있으면 **5000ms** 후 사라짐. `SafeArea`·`BottomCTA` 높이를 자동 고려. 앱 환경 기본 위치가 OS별로 다름(Android 상단 26px / iOS 상단 46px), `higherThanCTA` 옵션([useToast](https://tossmini-docs.toss.im/tds-mobile/hooks/OverlayExtension/use-toast/)) | 토스트는 "확인용"이 아니라 **일시 피드백**. 하단 CTA와 겹침을 컴포넌트가 해결해야 한다 |
| **Navigation/구분** | 상단은 `Top`(title/subtitle/right/CTA 슬롯), 구분은 `Border` 3종 | 화면 크롬은 슬롯 구조로 고정 |

### 1.6 숫자·금액 표기

- TPS 제작기([토스피드](https://toss.im/tossfeed/article/beginning-of-tps)): "수가 커질수록 자릿수를 비교하기 어려워요. … 토스 서비스에는 실시간으로 변동되는 수치를 보여주는 화면이 많은데요. 대표적인 사례로 **토스증권의 실시간 시세 화면**이 있습니다. 이 화면에서 숫자가 고정폭이 아니라면 어지럽겠죠." → **가변폭과 고정폭 숫자를 모두 마련**해, "주식 수, 전체 매출액 등 큰 수와 실시간으로 반영되는 수치"는 고정폭, "주요 정보가 크게 표현되거나 하나만 활용되는 상황"은 가변폭을 쓴다.
- 퍼센트·쉼표·부호·화살표는 **UI 아이콘에 가깝게** 더 크고 넓게 설계(TPS). `[추론]` 등락률 표기에서 부호·화살표가 색만큼 중요한 정보라는 뜻이며, 줍의 "▲ +2.34%" 3중 병기 규칙과 정합한다.
- 아라비아 숫자 사용 같은 표기 규칙은 SEED에도 있다(§2.6).

### 1.7 토스 UX 라이팅 (원칙 + 앱인토스 실무 규칙)

**토스의 8가지 라이팅 원칙** ([Toss Tech, 2022-11-15](https://toss.tech/article/8-writing-principles-of-toss)) — 코어밸류 5(Clear·Concise·Casual·Respect·Emotional)를 문장 규칙으로 구체화한 것:

| 원칙 | 문서상 정의 |
|:--|:--|
| Predictable hint | "다음 화면을 예상할 수 있는 힌트가 있는가?" — 밸류 설명이 과하면 사용성을 해친다 |
| Weed cutting | "의미 없는 단어를 모두 제거했는가?" — 토스는 넣든 빼든 영향 없는 단어를 '잡초'라 부른다 |
| Remove empty sentences | "의미 없는 문장을 모두 제거했는가?" — "의미 없는 문구로 공간을 채우지 않는다" |
| Focus on key message | "정말 중요한 메시지만 전달하고 있는가?" — "사용자가 이미 알고 있는 정보는 과감하게 생략" |
| Easy to speak | "이해하기 어려운 용어를 사용하지 않았는가?" — 소리 내어 읽었을 때 어색하지 않아야 |
| Suggest over force | "특정 행동을 강요하거나 공포감을 주고 있지 않은가?" — 권유와 강요는 다르다 |
| Universal words | "모두가 이해할 수 있고 모두에게 무해한가?" |
| Find hidden emotion | "정보를 넘어 사용자의 감정에 공감했는가?" |

**좋은 에러 메시지 6원칙** ([Toss Tech, 2022-09-21](https://toss.tech/article/how-to-write-error-message)): ① 최고의 에러는 발생하지 않는 것 ② 적절한 컴포넌트 쓰기 ③ 스스로 해결할 수 있는 방법 알려주기 ④ 사용자 입장에서 이해할 수 있는 언어로 쓰기 ⑤ 쉽게 해결할 수 있게 도와주기 ⑥ 부정적인 감정 최소화하기. 문서는 "토스트는 3~5초 사이에 사라지는 컴포넌트인데, 너무 많은 내용이 담겨" 있는 실패 사례를 명시하고, 에러 메시지에 **상황 설명·이유·해결책**을 담으라고 요구한다.

**앱인토스 UI/UX 가이드의 실무 규칙** ([문서](https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md)):

- 해요체 **전면 적용**("상황, 맥락을 불문하고"), 능동형(`됐어요 → 했어요`, '~었' 빼기), 긍정형(`없어요 → 있어요`), 과도한 경어 제거(`~시겠어요?`, `계시다`, `여쭈다`, `께` 금지), `{명사}+{명사}` 회피(한자어 풀어쓰기), `되어요 → 돼요`.
- 다이얼로그 왼쪽 버튼은 **[닫기]**로 통일 — "**취소**는 사용자가 하고 있는 작업이 취소된다고 오해할 수 있어 쓰지 않아요."
- 다크패턴 5종은 **출시 불가** 사례: ① 진입 즉시 전면 바텀시트(알림 동의 포함) ② 뒤로가기 시 이전 화면을 막는 바텀시트 ③ 나갈 수 있는 선택지 없음 ④ 예상 밖 전면 광고 ⑤ CTA만 보고 다음 행동을 예상할 수 없음("화면에서 설명한 가치를 CTA에 똑같이 반복"하는 것 포함).
- 그래픽 규칙: "그래픽은 장식이 아니라, 사용자가 화면의 의미를 더 쉽게 이해하도록 돕는 역할", "**한 화면에 핵심적인 그래픽 하나만**", "장식적인 효과나 이펙트(파티클, 과한 그라데이션)는 사용하지 마세요", 아이콘은 24~40px, "아이콘이나 이모지를 **두 개 이상 병렬로 조합하는 방식은 지양**".
- 라이트/다크 동시 고려: "너무 밝거나 너무 어두운 색은 특정 모드에서 잘 보이지 않을 수 있으니, **중간 명도의 색감**을 사용".
- 탭바(필요 시): "최소 2개, 최대 5개", 토스 제공 **플로팅 형태 유지**(토스 메인 하단 탭과 형태가 겹치면 현재 위치 혼동).
- 해상도: 논리 해상도 하나를 기준으로 설계(세로형 360×640~420×740 권장), 에셋은 1x+2x로 충분, 실 트래픽의 70~80%가 viewport 가로 800~900·세로 360~420.

### 1.8 토스증권의 종목·뉴스·AI 요약 화면 구조 (1차: 토스증권 뉴스룸)

- **AI 어닝콜 개편** ([토스증권 뉴스룸, 2025-11-27](https://corp.tossinvest.com/ko/news-room/detail?id=43631)) — AI 요약이 들어간 실제 정보 구조:
  - **'관전포인트' 섹션**: "어닝콜 시작 전 투자자들이 주목해야 할 핵심 포인트를 **AI가 자동으로 요약**", 주요 기업은 리서치센터가 함께 참여. 이용자 투표로 기대치 확인.
  - **'챕터별 보기'**: 1시간 이상 진행되는 콜을 "실적발표·가이던스·Q&A 등 주요 구간으로 나눠" 필요한 부분만 청취 → **요약이 아니라 구조화**.
  - **'모아보기' 페이지**: 보유/관심 기업 일정 + 주요 글로벌 기업 현황 한눈에.
  - PIP(화면 분할)로 차트·커뮤니티 동시 확인.
  - 신뢰 장치: "수치 및 전문용어의 정합성을 검증하는 **후처리 모듈**".
  - 규제·고지: 기사 하단에 "준법감시인 심사필 제2026-291호"와 "토스증권에서 제공하는 투자 정보는 참고용이며, 특정 종목에 대한 투자 권유 또는 추천을 목적으로 하지 않습니다. 또한, 해당 정보는 투자의 결과에 대한 법적 근거로 사용할 수 없습니다."
- **PC(웹) 서비스** ([뉴스룸, 2024-07-16](https://corp.tossinvest.com/ko/news-room/detail?id=28975)): 사전 이용자 의견을 반영해 **다크 모드**와 **종목 상세 패널 커스텀**("원하는 정보를 원하는 위치에 배치")을 추가, 모바일↔PC 관심종목 연동, '주식 골라보기' 필터.
- `[추론]` 위 두 문서를 합치면 토스증권의 화면 골격은 **① 홈(시장·보유·관심) → ② 종목 상세(가격·차트 + AI 요약/관점 + 근거·챕터) → ③ 일정/이벤트(어닝콜 등)**이며, AI는 "결론"이 아니라 **"무엇을 봐야 하는가(관전포인트) + 구간 나누기(챕터) + 검증(후처리)"**로 배치된다. 줍의 "AI 요약 + 근거 3건" 구조와 동일한 위치에 있다.

### ▶ 줍에 가져올 TDS 원리 (요약)

1. 색은 **역할 + 테마** 두 축으로만 관리하고, 단계 이름이 같으면 밝기도 같게 유지한다(OKLCH 원리, 시각보정은 그다음).
2. 다크 모드는 라이트의 반전이 아니라 **별도 명도·대비 기준**을 갖는다.
3. 타이포는 **토큰 이름으로만** 쓰고 값을 하드코딩하지 않는다. 13px 이하는 "읽히지 않아도 되는 정보"로 취급한다.
4. 면(둥글기·카드)으로 정보를 나누지 말고 **행(row)과 선(border)**으로 나누고, 구분선은 3종으로 제한한다.
5. 문구는 "빼도 의미가 없는 것은 전부 제거"(Weed cutting / Remove empty sentences / Focus on key message)가 기본값이다.
6. 그래픽·아이콘은 **장식 금지, 한 화면 한 개**, 병렬 아이콘 조합 금지.

### 출처 (섹션 1)

- https://developers-apps-in-toss.toss.im/design/components.md
- https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md
- https://tossmini-docs.toss.im/tds-mobile/ , /foundation/colors/ , /foundation/typography/
- https://tossmini-docs.toss.im/tds-mobile/components/{ListRow/list-row-overview, list-header, BottomCTA/check-first, BottomCTA/Double, tab, badge, border, button, paragraph, top}
- https://tossmini-docs.toss.im/tds-mobile/hooks/OverlayExtension/use-toast/
- https://toss.tech/article/tds-color-system-update , https://toss.tech/article/rethinking-design-system
- https://toss.tech/article/8-writing-principles-of-toss , https://toss.tech/article/how-to-write-error-message
- https://toss.im/tossfeed/article/beginning-of-tps
- https://corp.tossinvest.com/ko/news-room/detail?id=43631 , ?id=28975

---

## 2. 당근 SEED 디자인 시스템

### 2.1 토큰 구조: Raw → Scale → Semantic

- SEED 자신의 정의: "**Scale Token**은 Raw value Scale 하나에 이름을 부여한 것", "**Semantic Token**은 Scale Token의 조합(Composition)으로 디자인 의도를 표현한 단위이며, 실제 디자인과 개발 과정에서 주요 빌딩블럭"([Design Token](https://seed-design.io/llms/foundations/design-token.txt)). 즉 foundation(값) → semantic(의도) 2계층이며, 뷰포트·플랫폼별 주입으로 스킴을 재정의한다.
- 색은 **Property × Role × Variant × State** 체계([Roles](https://seed-design.io/llms/foundations/color/color-role.txt)):
  - Property: `Foreground` / `Background` / `Stroke`
  - Role: `brand` / `neutral` / `positive` / `warning` / `critical` / `informative`
  - Variant: `-solid`(강조) / `-weak`(약) / `-pressed`(눌림)
  - 즉 이름 규칙 자체가 "무엇에(Property) 어떤 의미(Role)로 얼마나 강하게(Variant)"를 강제한다. 예: `$color.fg.brand`, `$color.bg.brand-weak`, `$color.stroke.focus-ring`.
- 팔레트는 **적응형(adaptive)**: 하나의 팔레트가 테마별 값 표를 갖는다([Palette](https://seed-design.io/llms/foundations/color/palette.txt)). 예: `gray-00` 라이트 `#ffffff` / 다크 `#000000`, `gray-100` `#f7f8f9` / `#16171b`, `gray-1000` `#1a1c20` / `#f3f4f5`, `carrot-600` `#ff6600` / `#e65200`. `static-*` 계열(불변 블랙/화이트/알파)은 테마와 무관하게 고정.
- 라이선스: **Apache-2.0**(문서·코드) — "상업적 목적을 포함해 자유롭게 사용·수정·배포"([Get Started](https://seed-design.io/get-started), [GitHub](https://github.com/daangn/seed-design)). TDS와 달리 **줍이 그대로 참고·이식하는 데 법적 제약이 없다**는 점이 결정적 차이.

### 2.2 색·다크 모드 원칙

- 역할 기반 색은 "의도된 전경/배경 모든 조합에서 **APCA 기준**을 충족하도록 설계"([Color](https://seed-design.io/llms/foundations/color.txt)). 구체 기준([Inclusive Design](https://seed-design.io/llms/foundations/inclusive-design.txt)):
  - 가독성 텍스트(2줄 이상 본문, 화면 제목, 헤드라인, 입력 필드, 툴팁)는 **최소 Lc 75, 권장 Lc 90**
  - 그 외 텍스트는 **최소 Lc 60**(단, 16px 미만이면 bold)
  - placeholder·disabled는 **최소 Lc 30**
- 팔레트 색은 "기기의 화면 모드(라이트/다크)에 따라 알맞은 명도의 색상이 배정"되므로 **한 모드만 보고 디자인해도 다른 모드에서 인지 가능**하다([Color](https://seed-design.io/llms/foundations/color.txt)).
- **표면 고도 규칙**: 레이어 토큰은 "다크 모드에서는 **고도가 높을수록 더 밝아지는 규칙**"을 따른다([Elevation](https://seed-design.io/llms/foundations/elevation.txt)). 예: `bg.layer-basement` 라이트=gray-200 / 다크=gray-00, `bg.layer-default` 라이트=gray-00 / 다크=gray-100, `bg.layer-floating` 라이트=gray-00 / 다크=gray-200.
- **그림자 의존 금지**: "Shadow의 경우 다크 모드에서 잘 보이지 않는다는 한계가 있습니다. shadow를 써야하는 영역(화면 전체에서 주목도가 높은 몇 안 되는 요소)에서만 사용합니다." — 고도 표현은 ① 표면색 ② 그림자 ③ 테두리 3가지 중 **하나를 골라** 쓴다(같은 문서).
- 접근성: "색상만으로 정보를 전달하지 않고, 텍스트·아이콘 등 다른 시각적 요소와 함께 제공"([Inclusive Design](https://seed-design.io/llms/foundations/inclusive-design.txt)).

### 2.3 타이포그래피

- **글꼴 선택**: "사용자의 디바이스 환경을 고려하여, **대부분의 경우 각 플랫폼의 시스템 폰트를 사용**합니다." 표로 정리된 권장은 iOS/Android/macOS=시스템 기본 글꼴, **Windows=Pretendard**(맑은 고딕·Segoe UI가 디자인 의도와 어긋나는 경우가 많아서)([Typography](https://seed-design.io/llms/foundations/typography.txt)).
  - 한계도 문서가 스스로 밝힌다: "시스템 폰트를 사용하기 때문에, 같은 medium(500)이라도 플랫폼마다 실제로 그려지는 글꼴이 다릅니다. 한글에서는 iOS(Apple SD Gothic Neo)보다 Android 쪽 획이 조금 더 두껍게 보일 수 있습니다."
- 스케일: 폰트 크기 `t1`=11px → `t14`=48px(각 단계에 `-static` px 변형 별도), 줄 높이 토큰이 1:1로 짝을 이룬다(t1 15px … t14 60px). 두께는 **3단계**(regular 400 / medium 500 / bold 700).
- 사용 지침: "일반적으로 **t1–t5는 본문 및 장식적인 텍스트**, **t6–t10은 제목 및 주요 텍스트**. **t11–t14는 sm breakpoint 이상**에서 사용 권장", "고정 단위(px) 대신 **rem**을 사용해 사용자의 폰트 크기 설정을 존중", "특정 역할이 요구되는 경우(화면 제목, 게시물 본문) **시맨틱 텍스트 스타일** 사용".
- 구성 방식: `t5Regular`, `t1Bold`처럼 **크기+두께를 축약한 스케일 스타일**과 `screenTitle`, `articleBody` 같은 **시맨틱 스타일**의 2종(같은 문서). `[추론]` 줍의 `text-*` 사이즈 토큰도 "스케일 + 역할" 2계층으로 나누면 화면별 예외를 줄일 수 있다.

### 2.4 Radius 스케일과 적용 대상

- 스케일([Radius](https://seed-design.io/llms/foundations/radius.txt)): `r0_5`=2, `r1`=4, `r1_5`=6, `r2`=8, `r2_5`=10, `r3`=12, `r3_5`=14, `r4`=16, `r5`=20, `r6`=24, `full`=9999(px).
- **동심원(Concentric) 규칙** — 가장 실무적인 규칙([List](https://seed-design.io/llms/components/list.txt)): "리스트가 R값을 가진 카드 컨테이너 안에 포함될 때, 컨테이너와 동일한 반경을 그대로 적용하면 시각적으로 반경이 맞지 않게 보일 수 있습니다. 이를 위해 **내부 요소의 Radius는 상위 컨테이너의 반경에서 내부 패딩 값만큼 빼서** 적용합니다. 예: 카드 컨테이너 Radius 16px, 카드 Padding 6px → 내부 리스트 Radius = 10px."
- 리스트 항목 내부 여백은 "**`{global-gutter=16px}`보다 좁아지지 않도록** 주의"하고, 한 List 안에서 항목 정렬이 달라지지 않게 한다(같은 문서).

### 2.5 모바일 내비게이션 · 바텀시트 · 리스트 · 배지

| 컴포넌트 | 문서상 규칙 | 출처 |
|:--|:--|:--|
| **Bottom Navigation** | "다섯 개의 상위 탭 간 이동". 항목 **5개 초과 금지**, 라벨은 "한글 5자, 영문 10자 이내", 내부 컨테이너 **최대 너비 480px**, "콘텐츠 영역 확보를 위해 **폰트 스케일링 미적용**", 아이콘은 **Fill만**(Line 혼용 금지), Notification Badge는 원칙적으로 한 탭, **3개 이상 탭에 표시하지 않기**, Large=숫자(1~99, 100 이상은 99+), Small=점 | [Bottom Navigation](https://seed-design.io/llms/components/bottom-navigation.txt) |
| **Top Navigation** | **Root**(루트 탭, 핵심 진입) / **Standard**(2-depth 이상, 뒤로가기·닫기·타이틀·보조 액션) 2종. 뒤로가기(`<`) vs 닫기(`X`) 의미 구분 표 제공. 우측 아이콘 버튼 **2개 권장(최대 3)**, 타이틀은 1줄·길면 말줄임, 스크롤 시 상단 고정 | [Top Navigation](https://seed-design.io/llms/components/top-navigation.txt) |
| **Bottom Sheet** | **최대 너비 480px**. 기본 닫기 = 아래로 드래그/바깥 터치. "실수하면 안 되는 중요한 작업이나 시트 안에서 화면이 바뀔 때는 **상단 닫기 버튼 + 핸들 제거**" 권장. **Snap point 기본 최대 90% / 중간 50% / 최소 10%**, 스냅을 쓰면 **핸들 필수**, 최대 높이 90% 초과 시 **페이지로 표현**. 닫기 버튼 터치 타깃 **40×40** | [Bottom Sheet](https://seed-design.io/llms/components/bottom-sheet.txt) |
| **List** | 슬롯 = Prefix / Title / **Detail** / Suffix. Align 기본 Center(한 줄), **Top**(여러 줄). Detail에 Tag Group 프리셋. "하나의 List Item에 **4개 이상 상호작용 요소는 지양**", Switch/Check/Radio 사용 시 **행 전체가 클릭 영역**이고 그 안에 별도 Action Button을 넣지 않음 | [List](https://seed-design.io/llms/components/list.txt) |
| **Badge** | **하나의 객체에 1~2개 이하**, 라벨은 **2~3단어(10글자 넘으면 말줄임)**, "**Brand 컬러는 꼭 필요한 곳에만**", 카테고리·부가정보에는 **Weak**, "**배경색이 있는 경우에는 Weak 스타일 사용을 권장하지 않습니다**", **클릭 가능한 요소로 사용 금지**(대신 Chip/Toggle/Action Button), Tone은 Neutral/Informative/Positive/Warning/Critical로 상태 의미 매핑 | [Badge](https://seed-design.io/llms/components/badge.txt) |
| **Snackbar** | 기본 **4초**, 터치 유지 시 타이머 일시정지, **한 번에 1개**(큐잉), Default/Positive/Critical 3종, 액션은 최대 1개·"되돌리기/목록보기"처럼 **구체 단어**. "낮은 심각도의 상태 공유"에만 쓰고, 결정이 필요한 선택·지속 경고·여러 단계 안내는 Bottom Sheet·Page Banner·Callout으로 보낸다. 문장 1개면 마침표 생략, 2개 이상이면 모두 붙임 | [Snackbar](https://seed-design.io/llms/components/snackbar.txt) |
| **Tabs** | Line(Fill/Hug) / Chip(Solid/Outline) 2계열, Fill은 "Tab Item이 많지 않을 때, **최대 5개**". 6개 이상이거나 라벨이 길면 Hug. **2 depth는 1차 Line + 2차 Chip** 조합, 같은 화면에 Chip 계열을 중복 사용 금지, Notification Badge는 "여러 탭에 동시 표시 지양" | [Tabs](https://seed-design.io/llms/components/tabs.txt) |
| **Result Section** | 성공/실패/**빈 상태** 템플릿. Large=전체 화면, Medium=카드·섹션. 버튼 위계는 **Bottom CTA(핵심 행동) vs Contained Button(보조)**로 구분. 실패 시 액션 4종을 의미로 분리: `<`(입력 오류처럼 수정 필요) / `X`(임시 레이어 닫기) / `돌아가기`(안전한 목적지) / `다시 시도` | [Result Section](https://seed-design.io/llms/components/result-section.txt) |

### 2.6 접근성 · 레이아웃 · 세이프 에어리어

- **터치 타깃**: "44×44px 이상이 이상적이며, … 어려운 경우 **최소 24×24px 이상**을 보장"([Inclusive Design](https://seed-design.io/llms/foundations/inclusive-design.txt)).
- **복잡 제스처 대체**: "핀치 줌, 드래그 같은 복잡한 제스처는 단순한 터치 동작으로도 수행 가능하도록 대체 방법을 제공"(같은 문서) — `[추론]` 줍의 그래프(팬·핀치)에 줌 버튼을 병행하는 근거.
- **오류 처리**: 시각 피드백 + `aria-live`, "오류 메시지는 입력 필드 근처에 배치", 구체적 해결 방법 제시(같은 문서).
- **모션**: `prefers-reduced-motion` 옵션 제공, 2초 이상 애니메이션 회피 또는 건너뛰기 제공, **초당 3회 이상 점멸 금지**, 자동 재생 기본 비활성(같은 문서).
- **Safe Area**([패턴 문서](https://seed-design.io/llms/patterns/safe-area.txt)) — 모바일 UI 추가 시 그대로 채택할 규칙:
  - 네 변의 inset은 **서로 독립**이고 상황(기기·회전·분할)마다 달라진다 → 고정값 금지, 항상 "현재의 안전 영역" 기준으로 배치.
  - **콘텐츠(누를 수 있는 요소 + 읽어야 하는 정보)는 안전 영역 안**, **배경·구분선·스크롤 영역은 화면 끝까지**.
  - **여백은 화면 끝이 아니라 안전 영역 경계부터** 잰다(예: `spacing-x.global-gutter` = 16px).
  - 끝까지 스크롤했을 때 **마지막 항목 전체가 안전 영역 안**에 보이도록 inset + 기본 여백 확보.
- **간격 스케일**([Spacing](https://seed-design.io/llms/foundations/spacing.txt)): `x0_5`=2 ~ `x16`=64px + 의미 토큰 `spacing-x.global-gutter`(16px), `spacing-y.component-default`(12px), `spacing-y.nav-to-title`(20px), `spacing-y.between-text`(6px), `spacing-y.screen-bottom`(56px).
- **문구 규칙**([Writing](https://seed-design.io/llms/foundations/writing.txt)): 기술 용어·한자어 지양, 존칭 최소화, **수는 아라비아 숫자**, 축약어·은어 지양, **긍정문**, 능동문, 데이터 변화가 아니라 **사용자 행위** 중심("거래 후기를 보냈어요" vs "작성 완료했어요"), 기능 이름보다 **목적**, 느낌표는 꼭 필요할 때만, 마침표는 평서문·명령문 끝에만(메인 타이틀·20pt 이상·버튼 라벨에는 미사용). 보이스·톤은 "**활기차고 친절한**"([Voice and Tone](https://seed-design.io/llms/foundations/voice-and-tone.txt)).

### ▶ 줍에 가져올 SEED 원리 (요약)

1. 토큰은 2계층(값 → 의도)으로 두고, 색 이름 규칙에 **속성·역할·변형**을 강제한다.
2. 다크 모드는 "고도가 높을수록 밝게", 그림자는 최소 사용, 고도 표현 수단은 **한 번에 하나만**.
3. 간격·반경은 스케일에서만 고르고, **중첩 반경은 (부모 반경 − 패딩)**으로 계산한다.
4. 리스트는 슬롯 구조(접두/제목/상세/접미)로 만들고, 한 행에 상호작용 요소를 4개 이상 넣지 않는다.
5. 배지는 객체당 1~2개, 2~3단어, Weak 기본, 클릭 요소로 쓰지 않는다.
6. 안전 영역은 "콘텐츠는 안, 배경은 끝까지", 여백은 경계부터.

### 출처 (섹션 2)

- https://seed-design.io/get-started , https://github.com/daangn/seed-design
- https://seed-design.io/llms/foundations/{color, color/color-role, color/palette, design-token, elevation, inclusive-design, radius, spacing, typography, writing, voice-and-tone}.txt
- https://seed-design.io/llms/patterns/safe-area.txt
- https://seed-design.io/llms/components/{list, badge, bottom-navigation, bottom-sheet, snackbar, tabs, top-navigation, result-section}.txt

---

## 3. 폰트 결정 자료 (Pretendard 단독 사용 탈피)

### 3.1 현재 상태 (우리 코드)

- `docs/design/tokens.json:662` — `"Pretendard Variable", Pretendard, -apple-system, …` 셀프호스팅, 설명에 "Pretendard OFL 1.1 셀프호스팅".
- `prototype/web/src/styles/tokens.css:173` — 동일 스택. `prototype/web/src/pages/design-system-page.tsx:403` — "Pretendard를 기본으로 쓰고, 숫자는 자릿수가 흔들리지 않게 tabular-nums를 켜요."
- `docs/design/tokens.json:767-770` — `typography.numeric.tabular = "tabular-nums"` 토큰이 이미 존재(가격·등락률용). 즉 **숫자 폭 문제는 이미 규칙으로 인식**되어 있다.

### 3.2 슬롭 관점의 전제 정리

사용자가 기준으로 삼는 `impeccable.style/slop`의 해당 규칙 두 개:

- **"Inter Everywhere"**: "Familiar defaults such as Inter and Geist can make unrelated products look alike. **Choose typography for the product's character and reading needs**, and keep established brand fonts when they fit."
- **"One font family"**: "One font family can work well across a whole page. **If everything feels flat, vary size, weight, and spacing before deciding whether a second family would help.**"

`[추론]` 즉 탐지 대상은 "Pretendard라는 이름"이 아니라 **모든 화면이 같은 크기·굵기·간격으로 평평해지는 사용 방식**이다. 따라서 해법은 (a) 서체 교체와 (b) **사용 방식(스케일·굵기 대비·숫자 처리)의 분리** 두 축을 함께 다뤄야 한다. TDS(§1.3)·SEED(§2.3) 모두 (b)를 문서 규칙으로 강제하고 있다.

### 3.3 후보 비교 (1차 문서 확인분)

| 후보 | 라이선스(웹 임베딩) | 한글 범위 | 고정폭 숫자(tnum) | 웹폰트/서브셋 | 굵기 | 목소리·비고 |
|:--|:--|:--|:--|:--|:--|:--|
| **Wanted Sans** | SIL OFL 1.1 — "글꼴 단독 판매 및 **글꼴 라이선스 변경을 제외한 모든 상업적 행위 및 수정, 재배포 가능**" ([repo](https://github.com/wanteddev/wanted-sans)) | 문서에 글리프 수 미기재 `[미확인]`. "한글은 본고딕 변형으로, **Pretendard와 같은 모양**"([concept](https://raw.githubusercontent.com/wanteddev/wanted-sans/main/documentation/concept/README.md)) | **지원** — `tnum: 고정폭 숫자` 명시([features](https://raw.githubusercontent.com/wanteddev/wanted-sans/main/documentation/features/README.md)) | jsDelivr **가변/일반 동적 서브셋**(사용 글자만 다운로드) + 완전판([webfonts](https://raw.githubusercontent.com/wanteddev/wanted-sans/main/packages/wanted-sans/documentation/webfonts/README.md)) | 7종 + 가변 | 지오메트릭 기반, `ss02`(일반 숫자)·`zero`(슬래시 0)·`ss05`(한국 현지화) 등 OpenType 다수 |
| **SUIT** | SIL OFL — "상업적인 목적을 포함하여 자유롭게 사용", "**향후 License 변경으로 인한 분쟁의 가능성이 없습니다**"([repo](https://github.com/sun-typeface/SUIT)) | **완성형 2,350자 + 외래어·신조어 318자**(11,172자 전체는 아님) ([sun.fo/suit](http://sun.fo/suit/)) | **지원** — "정확한 자릿수 표현을 위한 고정폭 숫자를 별도로 두었습니다. 고정폭 글자는 **모든 굵기에서 같은 자폭**" | woff2 **200KB 미만**(서브셋 전제로 제작), CDN CSS 제공 | 9종 + 가변 | "UI 본문용": 위·아래 여백 동일(수직 중앙 정렬 보정 불필요), 18/16/13/11px에서 **줄간격 기본값이 짝수**, 본고딕 대비 97% 크기 |
| **Spoqa Han Sans Neo** | SIL OFL — "개인 및 기업 사용자가 자유롭게 사용, 수정 및 재배포", "로고, BI, CI, 임베드 등의 상업적 사용 가능"([repo](https://github.com/spoqa/spoqa-han-sans)) | Subset/Original 배포 구조, **커버리지 수치 미기재** `[미확인]` | `[미확인]` | 자체 CDN CSS(`spoqa.github.io`) | 4종(Thin/Regular/Medium/Bold) | "국문, 영문, 일문, **숫자**, 글리프의 어울림이 훌륭" (README 문구) |
| **IBM Plex Sans KR** | SIL OFL([repo](https://github.com/IBM/plex), [IBM Design Language](https://www.ibm.com/design/language/typography/typeface)) | 한국어는 지원 스크립트 목록에 포함. **글리프 수 미공개** `[미확인]` | `[미확인]` — 공식 feature 안내는 ligatures/fractions/arrows/alternate glyphs/global currency | npm 패키지 `@ibm/plex-sans-kr`, 릴리스 zip | 8 weights × Roman/Italic(패밀리 전체 기준) | "UI 환경에 잘 동작하도록 설계", 기업 정체성이 강한 목소리 |
| **Pretendard** (현행) | SIL OFL 1.1([repo](https://github.com/orioncactus/pretendard)) | `[미확인]` — README에 글리프 수 미기재. 동적 서브셋 제공은 1차 근거 확인 | `[미확인]` (현행 코드는 `font-variant-numeric: tabular-nums` 사용, `docs/design/tokens.json:767-770`) | **동적 서브셋**(README가 "Google Fonts에서 제공하는 한글 글꼴과 동일한 방식"이라 명시) + 가변 | 9종 + 가변 | 사용자가 "과사용"으로 지목 |
| **시스템 폰트 스택** | OS 기본 라이선스(임베딩 불필요) | OS가 보유(완전) | OS·플랫폼 의존 `[미확인]` | **0KB** | OS 의존 | SEED가 실제로 채택: iOS/Android/macOS=시스템, **Windows=Pretendard**([SEED Typography](https://seed-design.io/llms/foundations/typography.txt)). 단, "같은 medium(500)이라도 플랫폼마다 다르게 보임"을 SEED가 명시 |

보조 서체(숫자 전용)에 대해: TPS는 **한 서체 안에서 가변폭/고정폭 숫자를 모두 제공**하는 방식으로 해결했다([토스피드](https://toss.im/tossfeed/article/beginning-of-tps)). 이미 우리 토큰에는 `JetBrains Mono`가 "코드, 해시, ID 표기용"으로 한정되어 있다(`docs/design/tokens.json:665-668`). `[추론]` 가격·등락률에 별도 모노 서체를 도입하는 것은 톤 불일치와 혼용 위험이 크다 — 본문 서체의 `tabular-nums`로 해결하는 편이 낫다.

### 3.4 추천

**1안(권고) — SUIT + `tabular-nums`**
- 근거: ① UI 본문용으로 **수직 메트릭·중앙 정렬·짝수 줄간격**까지 설계 목표가 명시되어 "디자이너·개발자 보정 비용"을 줄인다 — TPS 제작기(§1.3)가 토스가 겪은 것과 같은 문제의식. ② **tnum을 모든 굵기에서 동일 자폭**으로 제공(금융 수치 화면의 전제). ③ woff2 200KB 미만으로 서브셋 인프라 없이 즉시 도입 가능. ④ OFL, 라이선스 변경 리스크 없음.
- 리스크: **11,172자 전체 미지원(2,650여 자)** → 뉴스 원문 인용에서 KS X 1001 밖 음절이 나오면 그 글자만 폴백 서체로 렌더되어 한 줄 안에서 이질감이 생긴다. 완화: ① 폴백 스택을 `"SUIT", -apple-system, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif`로 고정, ② 승인 파이프라인/인용 데이터에서 커버리지 밖 코드포인트를 배포 전 계측(문서상 확인 불가한 부분은 실측 필요).

**대안 — Wanted Sans Variable + `tabular-nums`**
- 근거: ① OFL, ② `tnum` 1차 문서 확인, ③ **동적 서브셋**으로 페이지에 실제 쓰인 글자만 받아 용량이 가장 작고, ④ 가변 굵기로 스케일·굵기 대비를 세밀하게 만들 수 있다.
- 트레이드오프: 한글 형태가 **Pretendard와 같은 계열**(자체 문서)이라 "Pretendard 탈피"가 절반만 달성된다. 글리프 수가 문서에 없어 커버리지 보장이 `[미확인]`. → 선택한다면 **교체 근거는 "숫자·라틴·굵기 대비"**이지 "한글 모양"이 아님을 팀에 명시해야 한다.

**채택하지 않는 후보**
- **시스템 폰트 스택(SEED 방식)**: 무로딩·완전 커버리지가 장점이지만, SEED 스스로 "플랫폼마다 획 두께가 다르다"고 명시하고 `tnum` 보장이 없다. 가격·등락률이 흔들리면 곤란한 금융 화면에서 `[추론]` 부적합. (단, 성능이 최우선이거나 목업 단계라면 유효한 임시안.)
- **IBM Plex Sans KR / Spoqa Han Sans Neo**: 라이선스는 명확하나 `tnum`·한글 커버리지 1차 근거를 확보하지 못해 **보류**(§0).
- **Pretendard 유지**: 금지가 아니라, 유지 시 **스케일·굵기 대비·숫자 처리 규칙을 문서로 강제**(§1.3, §2.3)하는 것이 슬롭 회피의 최소 조건.

### 출처 (섹션 3)

- https://github.com/wanteddev/wanted-sans , .../documentation/concept/README.md , .../documentation/features/README.md , .../packages/wanted-sans/documentation/webfonts/README.md
- https://github.com/sun-typeface/SUIT , http://sun.fo/suit/
- https://github.com/spoqa/spoqa-han-sans
- https://github.com/IBM/plex , https://www.ibm.com/design/language/typography/typeface
- https://github.com/orioncactus/pretendard
- https://seed-design.io/llms/foundations/typography.txt (시스템 폰트 + Windows Pretendard)
- https://toss.im/tossfeed/article/beginning-of-tps (고정폭/가변폭 숫자, 기호 설계)
- https://developer.mozilla.org/en-US/docs/Web/CSS/font-variant-numeric (`tabular-nums` = OpenType `tnum`)
- https://impeccable.style/slop/ (Inter Everywhere / One font family 규칙)
- 로컬: `docs/design/tokens.json:662,665-668,767-770`, `prototype/web/src/styles/tokens.css:173`, `prototype/web/src/pages/design-system-page.tsx:403`

---

## 4. 모바일 금융 앱 UX 패턴

### 4.1 하단 탭 구성

| 출처 | 사실 |
|:--|:--|
| [SEED Bottom Navigation](https://seed-design.io/llms/components/bottom-navigation.txt) | **5개 초과 금지**, 라벨 한글 5자/영문 10자, 컨테이너 최대 480px, 폰트 스케일링 미적용, 아이콘 Fill 단일 스타일, Badge는 3개 이상 탭에 금지, 숫자 배지는 99+ |
| [Material 3 Navigation bar](https://m3.material.io/components/navigation-bar/overview) (프록시 열람) | "**3-5 destinations** of equal importance", "Destinations don't change. They should be consistent across app screens", 컴팩트(600dp 미만)·미디엄(600–839dp) 폭에서 사용, M3에서 **그림자 없음**(M2와의 차이) |
| [Apple HIG Tab bars](https://developer.apple.com/design/human-interface-guidelines/tab-bars) (프록시 열람) | 탭 바는 **내비게이션 전용, 액션 제공 금지**. "**Don't disable or hide tab bar buttons, even when their content is unavailable**"(대신 왜 비었는지 설명), **오버플로우 탭 회피**, 라벨 포함·가능하면 한 단어, **배지는 중요한 정보에만**(남용 금지), 아이콘은 Fill 계열 권장 |
| [앱인토스 UI/UX 가이드](https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md) | 탭바는 **필수 아님**. 쓸 경우 토스 제공 **플로팅 형태** 유지(토스 메인 하단 탭과 겹치면 위치 혼동), **2~5개** |

`[추론]` 줍의 모바일 하단 탭 후보: `지도(홈) / 브리핑 / 관심·보유 / 검색(또는 더보기)` 4개. 5개를 넘기지 않는다는 세 출처(SEED·Material·앱인토스)가 일치하므로 **4개 상한**을 팀 규칙으로 두는 것이 안전하다.

### 4.2 바텀시트 스냅·동작

- SEED: 최대 너비 480px, **Snap point 2~3개(기본 최대 90% / 중간 50% / 최소 10%)**, 스냅 사용 시 **핸들 필수**, **최대 높이 90% 초과 시 페이지로 표현**, 중요한 작업·상태 변경 시 닫기 버튼 + 핸들 제거, 닫기 버튼 타깃 40×40 ([문서](https://seed-design.io/llms/components/bottom-sheet.txt)).
- Apple HIG Sheets: iOS는 **detent** 체계 — 시스템 정의 `large`(전체 높이)/`medium`(약 절반) + **커스텀 detent 가능**, "**grabber**를 포함하라"(드래그 리사이즈 + VoiceOver 지원), 스와이프로 닫기, **한 번에 하나의 시트**, "Done 버튼만 두지 말고 Cancel/Back을 함께" ([HIG Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)).
- Material 3 바텀시트 상세 스펙: **문서 본문 열람 실패**(§0) → 인용하지 않음.
- `[추론]` 줍의 `NodePanel`(모바일)은 SEED 기본값(90/50/10)을 그대로 쓰고, "관계 탐색 중"이라는 맥락상 **핸들 유지 + 바깥 터치 닫기**가 맞다. 반면 원문 인용처럼 읽기 몰입이 필요한 시트는 Apple의 "스와이프 dismiss + 명시적 Close" 중 하나를 골라 일관되게 적용.

### 4.3 종목 상세 · 뉴스/근거 리스트 구조

- 토스증권 1차 자료에서 확인되는 것(§1.8): 홈/관심/보유 연동, **종목 상세 패널 커스텀**, **AI 요약 = '관전포인트' + '챕터별 보기' + '모아보기'**, PIP 병행, 수치·전문용어 검증 후처리, 하단 법정 고지([뉴스룸 2025-11-27](https://corp.tossinvest.com/ko/news-room/detail?id=43631), [2024-07-16](https://corp.tossinvest.com/ko/news-room/detail?id=28975)).
- 목록 UI 규격은 TDS `ListRow`(3영역, indented 구분선, 8/12/16/24px 세로 여백)와 SEED `List`(Prefix/Title/Detail/Suffix, 행 전체 클릭 규칙)가 사실상 동일한 골격을 제시한다([TDS ListRow](https://tossmini-docs.toss.im/tds-mobile/components/ListRow/list-row-overview/), [SEED List](https://seed-design.io/llms/components/list.txt)).
- `[추론]` 뉴스/근거 리스트는 (a) 출처·시각 같은 메타는 **Detail 슬롯**, (b) 검증 상태·영향 분류 같은 상태는 **Badge 1~2개**, (c) 원문 이동은 **행 전체 클릭**이 아니라 명시적 액션(외부 링크)으로 두는 편이 SEED의 "행 전체 클릭 + 하이퍼링크 분리" 규칙과 일치한다.

### 4.4 온보딩 · 빈 상태/오류 문구 · 세이프 에어리어 · 터치 타깃

- **온보딩**([Apple HIG Onboarding](https://developer.apple.com/design/human-interface-guidelines/onboarding)): ① 가능하면 온보딩 없이 경험으로 이해되게, ② **인터랙티브**하게 가르치기, ③ 단일 플로우보다 **상황별 팁** 우선, ④ 강제 플로우는 "**brief, enjoyable**, 외울 것 없는" 수준, ⑤ 별도 튜토리얼은 **선택 사항**으로 두고 "스킵하면 다음 실행에서 다시 띄우지 않되, 나중에 찾을 수 있게" 제공, ⑥ "**Postpone nonessential setup flows or customization steps**"(합리적 기본값 제공), ⑦ 평점·구매 요청은 경험 이후로.
- **다크패턴 금지**(앱인토스): 진입 즉시 전면 바텀시트(알림 동의 포함), 뒤로가기 차단 시트, 탈출 불가, 예상 밖 전면 광고, 다음 행동을 예측할 수 없는 CTA ([문서](https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md)).
- **빈 상태·오류**: SEED `Result Section`이 3상태(성공/실패/빈 상태) 템플릿과 실패 액션 4종(`<`/`X`/`돌아가기`/`다시 시도`) 및 버튼 위계를 규정한다([문서](https://seed-design.io/llms/components/result-section.txt)). 토스의 에러 6원칙은 "상황·이유·해결책"을 담고, 토스트로 긴 설명을 하지 말라고 못박는다([토스테크](https://toss.tech/article/how-to-write-error-message)). SEED writing은 에러 예시로 "죄송합니다. 일시적으로 서비스를 사용할 수 없어요. 잠시 후 다시 시도해주세요."처럼 **직접 해결 방법**을 함께 주는 것을 Do로 제시한다([Writing](https://seed-design.io/llms/foundations/writing.txt)).
- **세이프 에어리어**: SEED safe-area 패턴(§2.6) — 콘텐츠는 안, 배경·스크롤 영역은 화면 끝까지, 여백은 경계부터, 마지막 항목은 inset+여백 확보([문서](https://seed-design.io/llms/patterns/safe-area.txt)). Apple은 "safe area를 존중하고 **Dynamic Type**에 따라 레이아웃이 재배치되어야 한다"를 레이아웃 원칙으로 제시한다([HIG Layout](https://developer.apple.com/design/human-interface-guidelines/layout)).
- **터치 타깃**: SEED 44×44 권장/24×24 최소([Inclusive Design](https://seed-design.io/llms/foundations/inclusive-design.txt)), WCAG 2.2 **SC 2.5.8(Target Size, AA) 최소 24×24 CSS px** + 5가지 예외(간격·동등 수단·인라인·UA 컨트롤·본질적)와 "중요한 링크/컨트롤은 더 엄격한 2.5.5(Enhanced)를 고려"([W3C](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)). 줍의 그래프 노드는 데이터 시각화 특성상 "Essential" 예외에 해당할 수 있으나, **줌 버튼·목록 진입점은 예외가 아니므로 44×44**를 적용한다 `[추론]`.

### 4.5 그래프(네트워크) 탐색을 모바일에서 다루는 사례

- **사례가 드물다**: 국내 증권사 공식 자료(토스증권 뉴스룸·홈페이지 등)에서 "관계 그래프 탐색" 기능은 확인되지 않았다 — 없다고 단정하지 않고 `[미확인]`으로 둔다. 검색 결과에서 나온 것은 Neo4j Bloom(데스크톱 도구), Kumu(웹) 등 **비(非)모바일 전용 도구**다.
- 확인된 1차/학술 자료:
  - **Microsoft Research Orchard(2020)**: "faceted search와 인터랙티브 네트워크 탐색을 결합한 **모바일 애플리케이션**"이며, "탐색적 내비게이션 중 관심 facet을 수집"하는 시각 질의 언어를 제공한다([MSR](https://www.microsoft.com/en-us/research/video/orchard-exploring-multivariate-heterogeneous-networks-on-mobile-phones-2/)). `[추론]` 작은 화면에서는 "그래프를 그리는 것"보다 **필터/패싯으로 후보를 좁히는 절차**가 중심이라는 시사점.
  - **Chunky Chains(arXiv 2607.06029, 2026-07-07)**: "스마트폰처럼 작은 화면에서 **수직 스크롤이 지배적 상호작용**인 환경을 위한 그래프 드로잉 스타일". 화면을 **bucket**으로 나누고 각 bucket 안의 정점 수를 제한해 **drawing width를 유한하게** 만들며, bucket을 건너뛰는 간선(long edge)을 최소화하는 것이 목표. "실제 그래프 다수가 좋은 Chunky Chain 시각화를 가진다"([arXiv](https://arxiv.org/abs/2607.06029)).
- `[추론]` 두 자료가 공통으로 지지하는 결론: **모바일에서 그래프는 "캔버스를 축소해 보여주는 것"이 아니라 "폭이 제한된 목록/체인 + 필터"로 변환하는 것**이 정석이다. 이는 `docs/design/archive/design-direction-v1.md`의 원칙 2("그래프는 목적지가 아니라 경로 / 목록으로 1:1 대체 가능해야")와 같은 결론이며, 모바일에서는 **목록 뷰를 기본값으로 두고 그래프는 보조 뷰**로 두는 편이 근거가 있다.

### 출처 (섹션 4)

- https://seed-design.io/llms/components/{bottom-navigation, bottom-sheet, list, result-section}.txt , https://seed-design.io/llms/patterns/safe-area.txt , https://seed-design.io/llms/foundations/{inclusive-design, writing}.txt
- https://developer.apple.com/design/human-interface-guidelines/{tab-bars, sheets, onboarding, layout}
- https://m3.material.io/components/navigation-bar/overview (bottom sheets 페이지는 열람 실패)
- https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
- https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md
- https://toss.tech/article/how-to-write-error-message
- https://corp.tossinvest.com/ko/news-room/detail?id=43631 , ?id=28975
- https://www.microsoft.com/en-us/research/video/orchard-exploring-multivariate-heterogeneous-networks-on-mobile-phones-2/ , https://arxiv.org/abs/2607.06029

---

## 5. 줍에 적용할 결론

### 5.1 슬롭 패턴 ↔ TDS/SEED 대응 해법

`impeccable.style/slop` 규칙(사용자 기준)과 TDS·SEED의 실제 규정을 짝지은 표. **원리를 추출해 줍의 언어로 다시 쓴다**(디자인을 베끼지 않는다).

| 슬롭 패턴(탐지 규칙) | 왜 문제인가(원문 취지) | TDS/SEED 대응 | 줍에서의 규칙(권고) |
|:--|:--|:--|:--|
| **사이드 스트라이프**(카드 좌측 두꺼운 컬러 바) | "상태·경고를 전달할 대상이 없는데 일반 카드를 알림처럼 만든다" | TDS `Border` 3종(전체/24px 들여쓰기/구간)으로 구분, 상태는 Badge로 | 좌측 컬러 바 금지. 영향 분류는 텍스트 라벨 배지로 |
| **카드 중첩**(cards inside cards) | "간격·타이포·구분선으로 계층을 만들고 중첩 컨테이너를 제거하라" | TDS `ListRow`+`ListHeader`, SEED `List`(슬롯) + Elevation "Global/Local" 개념 | 카드 안 카드 금지. 그룹은 리스트 행 + 헤더 + 여백으로 |
| **테두리+그림자 이중** | "테두리와 그림자가 같은 카드를 두 번 정의한다" | SEED Elevation: **표면색·그림자·테두리 중 하나만** | 동시 사용 금지. 다크에서는 그림자 대신 표면색/보더 |
| **큰 라운드 남용** | "모든 카드가 같아 보이고 콘텐츠 공간을 잠식" | SEED Radius 스케일 + **Concentric Radius(부모−패딩)** | 반경은 스케일 6단계만, 중첩 시 동심원 계산 |
| **헤딩 위 작은 라벨/필** | "헤딩을 반복하는 한 줄이 추가된다" | TDS `ListHeader`(title/description/right) | 라벨이 제목을 반복하면 삭제. 정보는 제목에 흡수 |
| **아이콘 타일**(둥근 사각형 안 아이콘) | "장식이 기능보다 두드러진다" | 앱인토스 그래픽 규칙: "장식이 아니라 이해를 돕는 역할", "핵심 그래픽 하나만", 아이콘 24~40px, **병렬 아이콘 조합 지양** | 아이콘은 제목 옆 인라인. 컨테이너로 감싸지 않음 |
| **반복 아이콘-제목-본문 카드** | "모든 항목에 같은 무게를 준다" | SEED List 4슬롯(접두/제목/상세/접미), TDS ListRow 3영역 | 이슈·기업 목록은 행 기반. 카드는 "독립 단일 객체"에만 |
| **모든 문장의 대시 / 과장어 / 반복 슬로건** | "설명 없는 약속, 문장부호 습관" | 토스 8원칙(Weed cutting·Remove empty sentences·Focus on key message) + SEED Writing | 금지어 목록(과장·최상급) + 리뷰 체크리스트 |
| **저대비 텍스트** | "본문 4.5:1, 큰 텍스트 3:1 미달" | SEED APCA: 읽기 텍스트 **Lc 75+**(권장 90), 기타 Lc 60, 16px 미만은 bold / KWCAG 색 비의존 | 토큰 단계에서만 색 조합 허용, 임의 hex 금지 |
| **균일 간격**(equal gaps everywhere) | "무엇이 한 그룹인지 알 수 없다" | SEED Spacing 의미 토큰(`between-text` 6 / `component-default` 12 / `global-gutter` 16 / `screen-bottom` 56) | 간격은 의미 토큰으로만. 임의 12/16 혼용 금지 |
| **네온·글로우·그라데이션 텍스트 / 장식 그리드** | "배경 효과가 콘텐츠와 경쟁" | 앱인토스: "장식적인 효과나 이펙트(파티클, 과한 그라데이션) 금지" | 다크에서도 글로우 금지. 그리드는 캔버스에만(그래프 배경) |
| **Inter Everywhere / 기본 서체 전면 사용** | "무관한 제품들이 닮아 보인다" | TDS는 전용 서체(TPS), SEED는 시스템 폰트, 각자 **스케일·굵기로 위계**를 만든다 | 서체 교체(§3) **+ 스케일·굵기 대비 규칙**(같은 문서가 지적한 "평평함" 해법) |
| **사용자에게 불필요한 메타 문구**(예: "비회원 체험 시 … 브라우저를 닫으면 초기화될 수 있어요") | 제품 사정 설명은 사용자 부담 | 토스: Remove empty sentences / Focus on key message / Predictable hint | 화면에서 삭제. 상태는 **UI로 표현**(비회원 배지 + [로그인] 액션)하고, 꼭 필요하면 CTA 인접 1줄로 축약 |
| **다크 테마 색 배지 남발** | 상태 구분이 색만으로 폭발 | TDS Badge 6색×fill/weak, SEED Badge **1~2개·Weak 기본·Brand 컬러 절제·배경 위 Weak 비권장** | 한 행에 색 배지 최대 1개, 나머지는 텍스트/도형/보더 |

### 5.2 권장 라운드 스케일 (기존 토큰 유지 + 사용처 제한)

`docs/design/tokens.json:820-846`의 현행 스케일을 그대로 쓰되, **쓰이는 자리를 못 박는다**:

| 토큰 | 값 | 허용 대상 | 금지 |
|:--|:--|:--|:--|
| `radius.none` | 0px | 구분선, 표, 캔버스, 이미지 프레임 | — |
| `radius.sm` | 4px | 배지·태그·툴팁 | 카드·버튼 |
| `radius.md` | 8px | 버튼, 입력, 세그먼트, 리스트 행의 hover/선택 배경 | 카드 컨테이너 |
| `radius.lg` | 12px | 카드(독립 객체에만) | 리스트 행 |
| `radius.xl` | 16px | 바텀시트 상단, 다이얼로그/모달 | 일반 카드 |
| `radius.full` | 9999px | 필터 칩, 원형 노드/아바타 | 상태 배지(상태는 sm 사각형) |

추가 규칙(SEED 근거): ① 중첩 시 **내부 반경 = 부모 반경 − 패딩**(예: 16 − 6 = 10), ② 한 화면에 반경 3종 초과 금지 `[추론]`, ③ 필 형태는 **액션(필터·칩)** 전용, 상태는 각진 배지.

### 5.3 배지 사용 규칙 (5조)

1. 한 객체에 **1~2개 이하**(SEED Badge), 한 행에 색 배지 **최대 1개**.
2. 라벨은 **2~3단어**, 10자 초과 시 줄이거나 말줄임(SEED).
3. **기본은 weak**. 배경색이 있는 표면 위에서는 weak 금지 → 그때만 solid 또는 텍스트(SEED).
4. **클릭 가능한 요소로 쓰지 않는다**(SEED). 필터·정렬은 Chip/Toggle.
5. 색은 의미에만: `approved / synthetic / ai-요약 / 검증 상태 / 영향 방향`처럼 **상태 의미가 고정된 것만** 색을 쓰고, 브랜드 컬러는 배지에 남용하지 않는다(SEED "Brand 컬러는 꼭 필요한 곳에만").

### 5.4 타이포 스케일 정렬

현행(`docs/design/tokens.json:670-707`, 11→28px)을 유지하되, **TDS·SEED의 사용 구간을 근거로 운용을 조인다**:

| 구간 | 현행 토큰 | 권고 사용 | 근거 |
|:--|:--|:--|:--|
| 11–13px | `2xs`/`xs`/`sm` | **"읽히지 않아도 되는 정보"만**: 데이터셋 고지, 기준 시각, 표 보조 수치 | TDS가 13/12/11px을 "안 읽어도 됨/아예 안읽어도 됨"으로 표기 |
| 14–16px | `base`/`md` | 본문·리스트 제목·수치 | TDS 일반 본문 17/15, SEED t4/t5(14/16) |
| 18–24px | `lg`/`xl`/`2xl` | 화면 제목, 브리핑 헤더, 종목명+현재가 | TDS Typography 2~4(26/22/20), SEED t6~t9 |
| 28px+ | `3xl` | 화면당 1개 이하(디스플레이) | impeccable의 "긴 대형 헤드라인" 규칙 |

- 굵기는 4단계 유지하되 **의미 고정**: 400 본문 / 500 강조 본문·탭 / 600 카드·섹션 제목 / 700 화면 제목·수치. `[추론]` "제목-본문 대비"는 크기보다 **굵기+색+간격**으로 만드는 편이 표 밀도가 높은 금융 화면에 유리.
- 수치는 전부 `typography.numeric.tabular` + 부호/화살표 병기(§1.6).

### 5.5 다크 모드 원칙 (5조)

1. **역할 + 테마 2축**: 색은 `--color-{role}`로만 쓰고 값은 테마에서 주입(TDS 테마 시스템, `data-tds-color-scheme` 패턴 참고).
2. **단계 이름의 밝기 균일성**: 팔레트 단계(예: grey100/200)는 라이트·다크 모두에서 **같은 단계 = 같은 인지 밝기**(OKLCH 원리). 부분 수정 시 전체 단계 재검수(TDS 개편의 교훈).
3. **다크는 별도 기준**: 명도 대비를 라이트보다 강하게, 다크 전용 값으로 설계(TDS). APCA Lc 75/60/30(SEED)을 리뷰 기준으로 사용.
4. **고도는 밝기로, 그림자는 최소로**: 다크에서 위 레이어일수록 밝게(SEED), 그림자는 주목도 높은 소수 요소에만.
5. **그래픽·일러스트·아이콘은 중간 명도**(앱인토스): 한쪽 모드에서 사라지는 색 금지, 색만으로 상태 전달 금지.

### 5.6 모바일 내비게이션 초안

```
[하단 탭 4개 — SEED ≤5 / Material 3–5 / 앱인토스 2–5]
  지도(홈)   브리핑   관심·보유   검색
  · 라벨 한글 5자 이내, 아이콘 단일 스타일(Fill), 숫자 배지는 99+, 배지는 최대 1개 탭
  · 탭 바는 액션 금지(Apple), 항목은 화면마다 유지(Material)

[상단] 루트 화면 = Root 형태(제목 + 핵심 액션 1~2개)
       2단계 이상 = Standard 형태(뒤로가기 `<` + 제목 1줄 + 보조 액션 ≤2)
       모달/바텀시트 = 닫기 `X` (Back과 의미 분리 — SEED)

[시트] 노드/근거 상세 = Snap 90/50/10 + 핸들, 최대 90% 초과 콘텐츠는 페이지로 분리
       읽기 몰입형(원문 인용) = 닫기 버튼 명시 + 핸들 제거(실수 닫힘 방지)

[CTA] 하단 고정 1~2개, 세이프 에어리어 자동 반영(TDS BottomCTA)
      토스트/스낵바는 CTA 위로(3~5초, 한 번에 1개)

[온보딩] 최대 3단계, 모든 단계 스킵 가능, 스킵 시 재노출 금지(설정에서 재진입)
         진입 즉시 시트 금지(알림 동의 포함)

[안전영역] 콘텐츠는 안, 배경·스크롤은 화면 끝까지, 여백은 경계부터, 마지막 항목은 inset+여백
[터치] 목록 행·버튼·줌 컨트롤 44×44, 그래프 노드는 최소 24×24 + 줌 버튼 병행
```

### 5.7 UX 라이팅 규칙 10개 (팀 규칙 초안)

1. **해요체 통일**(앱인토스: 상황·맥락 불문).
2. **능동형**: `됐어요 → 했어요`, '~었' 빼기.
3. **긍정형**: `없어요 → 있어요`. 부정형은 정책상 불가·일부 기능 제한·민감 정보 안심 상황에만.
4. **잡초 제거**: 넣든 빼든 의미가 없는 단어·접속사 삭제(Weed cutting).
5. **빈 문장 금지**: 공간이 비어 보인다는 이유로 설명을 덧붙이지 않는다(Remove empty sentences).
6. **핵심 1개**: 사용자가 이미 아는 정보는 생략, 화면당 질문 하나(Focus on key message).
7. **다음 화면 예고**: CTA 라벨은 결과를 예측 가능하게(Predictable hint). "확인/클릭" 금지.
8. **강요 대신 제안**: 놓치면 손해라는 뉘앙스 금지(Suggest over force).
9. **오류는 3요소**: 상황 + 이유 + 해결책. 토스트에 긴 설명 금지(에러 6원칙·SEED Result Section).
10. **숫자 규칙**: 아라비아 숫자, `tabular-nums`, 부호·방향 기호 병기, 기준 시각 표기.

부록으로 다이얼로그 왼쪽 버튼 **`[닫기]` 통일**(‘취소’는 작업 취소로 오해)과 금지어 목록(과장·최상급·확률 표현)을 리뷰 체크리스트에 넣는다.

### 출처 (섹션 5)

- https://impeccable.style/slop/ (규칙 원문)
- https://tossmini-docs.toss.im/tds-mobile/foundation/{colors,typography}/ , /components/{badge, border, list-header, ListRow/list-row-overview, BottomCTA/check-first, tab}/
- https://toss.tech/article/tds-color-system-update , https://toss.tech/article/8-writing-principles-of-toss , https://toss.tech/article/how-to-write-error-message
- https://toss.im/tossfeed/article/beginning-of-tps
- https://seed-design.io/llms/foundations/{color, color/color-role, radius, spacing, elevation, inclusive-design, writing}.txt , https://seed-design.io/llms/components/{badge, list, bottom-sheet, snackbar, bottom-navigation, result-section}.txt , https://seed-design.io/llms/patterns/safe-area.txt
- https://developers-apps-in-toss.toss.im/design/consumer-ux-guide.md
- https://developer.apple.com/design/human-interface-guidelines/{tab-bars, sheets, onboarding, layout}
- https://m3.material.io/components/navigation-bar/overview , https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
- https://arxiv.org/abs/2607.06029 , https://www.microsoft.com/en-us/research/video/orchard-exploring-multivariate-heterogeneous-networks-on-mobile-phones-2/
- 로컬(조사 시점 v1 기준): `docs/design/tokens.json:662,670-707,767-770,820-846`, `prototype/web/src/styles/tokens.css:173`, `prototype/web/src/pages/design-system-page.tsx:403`, `docs/design/archive/design-direction-v1.md`(원칙 2·4)
