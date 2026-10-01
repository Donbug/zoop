# 줍 프로토타입 슬롭·UX 감사

2026-09-29 기준. 대상은 실행 중인 `http://127.0.0.1:5173`과 `prototype/web/src/`이며 코드는 변경하지 않았다. 이하 `web/src/`는 `prototype/web/src/`, `audit/`는 `docs/design/audit/`의 약칭이다. 수동 규칙명은 [Impeccable의 61개 탐지 규칙과 6개 검토 패턴](https://impeccable.style/slop/)에 따른다. 자동 탐지 결과와 수동 판단을 혼동하지 않는다. 합성 기사·AI 생성·준비 중·투자권유 아님은 삭제 대상이 아니다(`docs/evidence/README.md:41-51`).

## 범위와 캡처 재현

데모 계정으로 로그인하여 ① 설정 ② 튜토리얼(목록에서 기업 선택 후 완료) ③ 지도 ④ 기업 상세·브리핑·디자인시스템으로 이동했고, 로그아웃 뒤 비회원 체험도 실행했다. 각 행의 접두사에 `-light-1440.png`, `-dark-1440.png`, `-light-390.png`, `-dark-390.png`를 붙인 **전체 페이지 스크린샷 4장**이 `audit/`에 있다. `1440/390`은 CSS 뷰포트 너비이며 높이 900px이다. 예: [`map-node-panel-dark-390.png`](audit/map-node-panel-dark-390.png). 브라우저의 전체 페이지 캡처이므로 모바일 시트 뒤의 문서도 이어서 보인다.

| 접두사 | 실제 URL/상태 | 관찰 |
|---|---|---|
| `login` | `/login`, 비로그인 | 데모 계정 입력 기본값, 비회원 진입 |
| `onboarding-setup`, `onboarding-tutorial` | `/onboarding`, 회원의 두 단계 | 모의 계좌 선택 후 기업 노드를 눌러 완료 |
| `map-market`, `map-watchlist` | `/?mode=market`, `/?mode=watchlist` | 시장은 기업 1·사건 3, **관심 모드는 계좌 경로로 등록한 회원의 실제 빈 상태**. 관심 데이터를 임의로 심지 않았다 |
| `map-node-panel`, `map-edge-panel` | `/?mode=market&select=node:SYNTH-ALPHA`, `...select=edge:edge-71030183917115d0` | 기업/승인 관계 패널 |
| `map-evidence`, `map-ai-question` | 기업 패널 위 근거 창/AI 질문 창 | 모달은 URL과 독립 상태이므로 새로고침 없이 테마·너비만 바꿔 캡처 |
| `company`, `briefing`, `design-system` | `/companies/SYNTH-ALPHA`, `/briefing`, `/design-system` | 회원 화면 |
| `guest-market`, `guest-briefing`, `guest-company` | 비회원 세션의 `/`, `/briefing`, `/companies/SYNTH-ALPHA` | 회원과 분리한 실제 비회원 세션 |

모바일 그래프 직접 전환 증거로 [`map-market-graph-light-390.png`](audit/map-market-graph-light-390.png), [`map-market-graph-dark-390.png`](audit/map-market-graph-dark-390.png)도 추가했다. 디자인시스템 긴 전체 페이지 이미지는 축소 미리보기로 판단하지 않고 부분을 확대해 보아야 한다. 온보딩은 완료되면 접근 가드가 `/`로 보내므로 단계별 캡처는 **완료 전**에 수집했다(`web/src/features/app-shell.tsx:154-163`).

## Impeccable 탐지기 집계

`prototype/web`에서 `pnpm dlx impeccable@4.1.0 detect <URL>` 및 `... detect src/` 실행. 탐지 결과가 있는 명령은 종료 코드 2이며 실행 실패가 아니다. URL 탐지기는 **별도 비인증 브라우저**를 열기 때문에 보호 URL 4개가 모두 `/login`으로 리다이렉트되었다. 따라서 아래 2건씩은 보호 화면의 결과가 아니라 **같은 로그인 화면의 중복 관측**이다. 회원 화면 판단은 위 인증 브라우저의 스크린샷·소스·수동 감사로 보완했다. URL 기본 뷰포트는 탐지기 기본 1280×800이며 모바일 폭은 별도 표기한다.

| 탐지 대상 | cramped-padding | skipped-heading | line-length | text-overflow | tiny-text | nested-cards | low-contrast | text-occlusion | 합계/해석 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `/login` | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 2, 로그인 실측 |
| `/onboarding`, `/`, `/companies/SYNTH-ALPHA`, `/briefing` | 각 1 | 각 1 | 0 | 0 | 0 | 0 | 0 | 0 | 각 2, **로그인 리다이렉트** |
| `/design-system` | 8 | 0 | 9 | 10 | 1 | 45 | 4 | 0 | 77, 공개 디자인 문서 실측 |
| `/design-system`, `--viewport 390x900` 추가 측정 | 8 | 0 | 0 | 0 | 1 | 45 | 4 | 4 | 62, 같은 문서 모바일 |
| `src/` 소스 탐지 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 별도 **side-tab 2건** (`evidence.tsx:45`, `chat-drawer.tsx:179`) |

각 행은 **탐지 건수**, 여러 URL·뷰포트를 합친 고유 결함 수가 아니다. 로그인 누락 헤딩은 `web/src/pages/login-page.tsx:34,39`의 h1→공통 CardTitle h3(`web/src/components/ui/card.tsx:22-23`)와 대응한다. 디자인시스템 `nested-cards` 45건은 실서비스 카드 45개를 뜻하지 않는다. 예제 카드가 예제 테두리 안에 들어가는 문서 구성(`web/src/pages/design-system-page.tsx:93`, `web/src/components/ui/card.tsx:9`)을 반복 탐지한 것이다. 반대로 실서비스 화면의 배지 과밀·모바일 가로 넘침은 보호 URL 리다이렉트 탓에 이 URL 결과에 나타나지 않는다.

## 수동 발견과 상위 15개 우선순위

심각도는 과업 방해·오인 위험 우선이다. 각 항목은 화면/스크린샷/소스/슬롭 규칙/수정 소유 층과 제안을 함께 적었다. 규칙명은 [카탈로그](https://impeccable.style/slop/)의 영어 이름 그대로다.

| 순위·심각도 | 발견과 영향, 근거 | 규칙 | 우선 수정 층·제안 |
|---|---|---|---|
| 1 높음 | 모바일 그래프 전환 시 문서 `scrollWidth=476` 대 뷰포트 390px. [`map-market-graph-dark-390.png`](audit/map-market-graph-dark-390.png), `web/src/components/domain/graph-canvas.tsx:312-356` | Text overflow | 개별 그래프: 5개 조작을 폭 안에서 접거나 이동, 캔버스만 국소 스크롤 |
| 2 높음 | `/design-system` 모바일도 `scrollWidth=514` 대 390px. [`design-system-dark-390.png`](audit/design-system-dark-390.png), `web/src/pages/design-system-page.tsx:345-353,364-365,837-838`; 탐지 text-overflow 10/모바일 text-occlusion 4 | Text overflow / Text occlusion | 문서 화면: 토큰명 래핑·표 국소 스크롤과 바깥 폭 제한 |
| 3 높음 | 관심 모드가 실제로 비어 있으나 설정 완료 뒤 관심 종목을 추가할 경로가 보이지 않는다. [`map-watchlist-dark-390.png`](audit/map-watchlist-dark-390.png), `web/src/pages/main-page.tsx:93-115,209-225`, `web/src/pages/onboarding-page.tsx:177-203` | Empty state / Dead-end navigation (UX) | 개별 화면: 빈 상태의 직접 `관심 종목 고르기` 행동과 수정 화면 제공. 없는 데이터를 채우지 말 것 |
| 4 높음 | 모바일 헤더·탭·배지의 실제 높이 28~36px(디자인시스템·로그아웃 아이콘 32×36, 지도·브리핑 탭 32, 합성 배지 28)로 44px 미달. [`map-node-panel-dark-390.png`](audit/map-node-panel-dark-390.png), `web/src/features/app-shell.tsx:65-105`, `web/src/components/domain/graph-legend.tsx:75`, `web/src/components/ui/tabs.tsx:21`; 모바일 44px 명세 `docs/design/archive/design-direction-v1.md:124` | Small navigation text / Cramped padding (UX) | 공통 버튼·탭·헤더: 외형 크기 아닌 클릭 영역 44×44px 확보 |
| 5 높음 | 기업 패널 390px 화면에 **배경과 겹쳐 동시에 렌더되는 유색 텍스트 칩 13개 + 합성 출처 버튼 2개=15개**. 직접 관련 태그가 목록 양 끝과 카드에 반복. [`map-node-panel-dark-390.png`](audit/map-node-panel-dark-390.png), `web/src/components/domain/issue-card.tsx:45-94`, `web/src/components/domain/relation-list.tsx:70-86`, `web/src/features/node-panel.tsx:100-159` | Redundant labels / Uniform card grid | 공통 도메인 태그·개별 패널: 출처/검증은 유지, 같은 관계 유형은 묶음 단위 한 번만 표기 |
| 6 높음 | 브리핑 표면·이슈 카드가 양쪽 다 둥근 테두리+그림자여서 같은 정보가 이중 카드로 보임. [`briefing-dark-1440.png`](audit/briefing-dark-1440.png), `web/src/components/domain/briefing-card.tsx:38`, `web/src/components/domain/issue-card.tsx:45` | Nested cards / Border plus shadow | 공통 카드·브리핑: 회차만 바깥 경계, 내부 사건은 행·구분선으로 평탄화 |
| 7 중간 | 로그인 작은 면책/비회원 저장소 설명이 CTA보다 먼저 읽힐 지면을 차지. [`login-dark-390.png`](audit/login-dark-390.png), `web/src/pages/login-page.tsx:47-49,82` | Redundant explanatory text / Tiny body text | 로그인: 저장소 설명 삭제, 투자권유 아님 고지는 짧게 유지 |
| 8 중간 | 시장 목록의 긴 키보드 단축키 문구와 범례 두 문단이 390px에서 사건보다 위·아래 지면을 잠식. [`map-market-dark-390.png`](audit/map-market-dark-390.png), `web/src/components/domain/relation-list.tsx:70`, `graph-legend.tsx:36-43` | Redundant explanatory text / Small body text | 목록·범례: 단축키는 키보드 도움말, 규모/인과 오인 주의는 짧게 **유지**, 파생 경로 설명은 해당 관계 도움말로 이동 |
| 9 중간 | 근거 창 푸터가 원문 확인보다 `창을 닫으면 … 그대로`라는 구현 설명을 더한다. [`map-evidence-dark-390.png`](audit/map-evidence-dark-390.png), `web/src/features/overlays.tsx:97-105` | Redundant explanatory text | 오버레이: 상태 보존 문장 삭제, 인용 원문·출처 안내만 축약 유지 |
| 10 중간 | AI 질문 창의 시연 안내와 답변 카드의 `AI 예시 답변`+`[예시 답변]`이 중복. [`map-ai-question-dark-390.png`](audit/map-ai-question-dark-390.png), `web/src/features/chat-drawer.tsx:101-107,167-173` | Redundant labels / Nested cards | AI 공통 고지: 생성·예시 답변 표시 **한 번은 반드시 유지**하고 카드 설명만 축약 |
| 11 중간 | 회원 신규 진입은 계좌 선택 후 노드 탭, 시트 닫기, 완료를 거쳐야 전체 지도. `everSelected`가 패널 **열기만** 해도 상세 확인을 완료로 표시. [`onboarding-tutorial-dark-390.png`](audit/onboarding-tutorial-dark-390.png), `web/src/pages/onboarding-page.tsx:318-325,355-363,380-383` | Redundant steps / False completion (UX) | 온보딩: 실제 근거 확인과 완료 조건 정렬, 먼저 샘플 가치 노출 후 개인화 단계 제시 |
| 12 중간 | 모드/선택 변경은 `replace:true`: 시장→관심 뒤 브라우저 뒤로가기는 이전 모드가 아니라 이전 페이지(실측 브리핑)로 이동. [`map-watchlist-light-390.png`](audit/map-watchlist-light-390.png), `web/src/pages/main-page.tsx:36-56` | Navigation predictability (UX) | 메인: 모드는 이력에 남길지 탭임을 명시하고 복귀 기대를 일관되게 설계; 선택 닫기는 유지 가능 |
| 13 중간 | 단순 시세 미제공 메시지가 기업 제목 아래 박스와 바닥 고지에서 반복. [`company-dark-390.png`](audit/company-dark-390.png), `web/src/pages/company-page.tsx:50-52,68-70`, `web/src/components/domain/company-header.tsx:63-65` | Redundant explanatory text / Cards around plain content | 기업 상세: 제목 근처 `시세 준비 중`만 유지, 바닥에는 짧은 투자 고지 유지 |
| 14 중간 | `PoC`, `BFF`, 원시 영문 상태 `announced`의 노출 위험: BFF는 온보딩 데이터 라벨, `announced`는 간선 패널에서 **실측**. PoC는 실데이터 배지 설명에서 해당 데이터일 때만 노출하며 `bff-rule-v0`은 **화면에 출력하지 않는 조건식**. [`onboarding-setup-dark-390.png`](audit/onboarding-setup-dark-390.png), [`map-edge-panel-dark-1440.png`](audit/map-edge-panel-dark-1440.png), `web/src/pages/onboarding-page.tsx:140-152`, `web/src/features/node-panel.tsx:373-376`, `web/src/lib/labels.ts:29-31`, `web/src/pages/briefing-page.tsx:20-30` | Implementation jargon / Copy clarity | BFF 데이터 라벨·공통 출처 설명·영문 상태: `가상 계좌 예시`, `근거 검증을 거친 실제 기사`, `보도에 언급`으로 번역; 출처 구분 유지 |
| 15 낮음 | 점 배경은 지도 캔버스에는 지도 은유가 있으나 정보 없는 영역에 시각적 잡음 가능; 인용문·AI 인용에 3px 좌선 두 곳. [`map-market-graph-dark-390.png`](audit/map-market-graph-dark-390.png), [`map-evidence-dark-390.png`](audit/map-evidence-dark-390.png), `web/src/components/domain/graph-canvas.tsx:303-307`, `evidence.tsx:45`, `web/src/features/chat-drawer.tsx:179` | Decorative grid / Side-tab accent border | 그래프·근거 공통: 지도에서는 격자 목적 확인 후 약화, 인용 좌선은 소스 구분 역할이 없다면 제거 |

`Pretendard Variable` 단일 UI 글꼴은 `docs/design/tokens.json:661-663`·`web/src/styles/tokens.css:173`에 명시되어 있다. 사용자가 지적한 **Inter Everywhere와 동종의 과사용 위험**이다. [추론] 단순 폰트 교체보다 제목·수치·본문의 크기/두께/밀도를 먼저 재설계하는 편이 안전하다. 실제 글자 크기는 `--text-2xs:11px`, `--text-xs:12px`(`web/src/styles/tokens.css:175-176`); 작은 캡션·보조 설명이 누적되어 위계가 평평하다. 헤딩 위 작은 라벨은 온보딩 `방식 1/2`와 단계 라벨(`onboarding-page.tsx:49,127,208`)이 대표적이다. 아이콘을 별도 타일에 넣는 전형적 3열 소개 카드나 과장어·모든 문장의 대시·네온 글로우·그라데이션 텍스트는 **검토한 실제 과업 화면에서 지배적 패턴으로 확인되지 않았다**. 빈 상태의 원형 아이콘 타일(`web/src/components/ui/feedback.tsx:60-63`)은 기능적 안내인지 평가 대상이고, 디자인시스템 색상 칩(`design-system-page.tsx:345-353`)은 샘플 자체라 서비스 카드와 구분한다.

### 상위 15개 밖의 확인·비발견 항목

| 심각도·화면·사진 | 수동 규칙/근거 | 판단·수정 층 |
|---|---|---|
| 낮음 · 온보딩 [`onboarding-setup-dark-390.png`](audit/onboarding-setup-dark-390.png) | Small label above heading; `web/src/pages/onboarding-page.tsx:49,127,208` | `온보딩 (1/2단계)`는 진행 상황이지만 `방식 1/2`는 제목과 중복. 화면 문구 축약 |
| 낮음 · 관심 빈 화면 [`map-watchlist-dark-390.png`](audit/map-watchlist-dark-390.png) | Icon tile above heading; `web/src/components/ui/feedback.tsx:60-64` | 원형 장식보다 다음 행동이 중요. 공통 빈 상태에서 아이콘 타일 재검토 |
| 중간 · 디자인시스템 [`design-system-dark-390.png`](audit/design-system-dark-390.png) | Low contrast: 탐지기 4건, `web/src/pages/design-system-page.tsx:648-650`; `web/src/components/ui/button.tsx:9` | 비활성 버튼 2개와 오류 코드 예제 2개에서 탐지. 공통 컴포넌트 점검; 실과업 대비 실패로 일반화 금지 |
| 낮음 · 브리핑 [`briefing-dark-1440.png`](audit/briefing-dark-1440.png) | Repeated icon-heading-text cards; `web/src/components/domain/issue-card.tsx:45-94`, `web/src/pages/briefing-page.tsx:66-86` | 사건별 같은 카드가 2건에서도 반복. 브리핑은 시간/근거 위주 사건 행으로 변형 |
| 비발견 · 검토한 실제 화면 | Dash in every sentence, hype words, neon glow, gradient text; [규칙 원문](https://impeccable.style/slop/) | 지배적 패턴으로 관찰되지 않음. 폰트 과사용·획일적 카드가 우선 |

## 문구 전수 분류표

범위: `web/src/**/*.tsx`에서 한국어가 포함된 줄을 `grep` 도구로 전수 조회하고 공통 데이터 라벨 `web/src/lib/labels.ts:8-99`도 포함. **분류 함수:** 아래 예외표에서 먼저 일치하는 문구를 적용하고, 나머지 모든 사용자에게 보이는 한국어 JSX 텍스트·속성·조건부 분기·토스트·상태 문구는 마지막 기본표의 `유지`로 분류한다. 따라서 `유지`는 목록에서 누락된 문구라는 뜻이 아니라 **해당 파일의 모든 나머지 문구**에 적용되는 명시적 결정이다. 소스 주석·타입 설명·`sr-only` 안내는 화면 본문이 아니지만 접근성 문자열은 유지 대상으로 포함한다. 런타임 데이터(BFF 기사 제목·본문·계좌 라벨)는 코드 리터럴이 아니어서 전수 원문 목록에 섞지 않는다. 분류는 현재 문구의 과업 역할 평가이지 문구를 지금 바로 수정하라는 뜻이 아니다.

| 화면·문구(동적 수치는 `{값}`) | 파일:줄 | 분류 | 이유/남길 정보 |
|---|---|---|---|
| 비회원 체험 시 기본 예시 지도…브라우저를 닫으면 관심 설정 초기화 | `pages/login-page.tsx:47-49` | **삭제** | 내부 저장소 수명, 첫 행동과 무관 |
| 가입 없이 둘러보거나 데모 계정으로… | `pages/login-page.tsx:39-45` | 축약 | 제목·CTA와 같은 설명 반복; 선택지 이름만 남김 |
| 데모 체험 시작하기 (로그인 없이 둘러보기) | `pages/login-page.tsx:43-45` | 축약 | 괄호를 별도 설명 대신 `로그인 없이 체험`으로 |
| 데모 계정: 이메일/비밀번호 힌트 | `pages/login-page.tsx:66-77` | 위치 이동 | 미리 채워진 값을 또 보여주며 비밀번호 노출; 도움말/개발 전용 위치로 |
| 투자 자문 아님·학습 데모 | `pages/login-page.tsx:82` | **축약** | 투자권유 아님 고지는 삭제 금지 |
| 온보딩 (1/2단계), 방식 1/2 | `pages/onboarding-page.tsx:49,127,208` | 축약 | 단계 수는 유지, 제목 위 방식 번호는 선택지 이름에 병합 |
| 실제 계좌가 아닌 가상(mock) 계좌… | `pages/onboarding-page.tsx:130-132` | **축약** | 모의 계좌임은 유지, `mock` 구현어는 제거 |
| 모의 투자 프로필 선택/가상 계좌 (BFF 기본 예시) | `pages/onboarding-page.tsx:140-152` | 축약 | BFF 계좌 라벨은 API 제공 동적 문구; 화면에는 `가상 계좌 예시` |
| 처음에는 집중적인 분석을 위해 최대 3개… | `pages/onboarding-page.tsx:190-194` | 삭제 | 같은 토스트 제목/선택 수 제한의 불필요한 이유 |
| 지도 사용법 문장·3개의 튜토리얼 세부 단계 | `pages/onboarding-page.tsx:51-56,320-324` | 축약 | `노드 선택→근거 보기` 한 행동만 분명히 |
| 지도에서 원/육각형…키보드라면 목록에서 Enter | `pages/onboarding-page.tsx:359-363` | 위치 이동 | 조작 힌트는 그 조작 근처/키보드 도움말로 |
| 지도 목록 ↑/↓, Enter, Esc 안내 | `components/domain/relation-list.tsx:69-70` | 위치 이동 | 키보드 사용자를 위한 도움말로, 모바일 본문 상시 노출은 제거 |
| 비회원은 시장 전체만…로그인하면… | `pages/main-page.tsx:189-193` | 축약 | 헤더의 `비회원 체험 중`과 중복; 개인화 잠금 옆 로그인 행동 |
| 종목을 누르면 지도에서 선택…없는 종목은 상세 | `pages/main-page.tsx:228-231` | 삭제 | 화면 전환 구현 설명, 직접 행동으로 알 수 있음 |
| 노드 크기·거리·선 굵기는 위험도/인과 크기 아님 | `components/domain/graph-legend.tsx:36-38` | **축약** | 금융 인과 오인 방지 핵심. 간결한 주의문으로 상시 유지 |
| 기업-기업 점선은 직접 거래 아님…선 누르면 실제 근거 | `components/domain/graph-legend.tsx:39-43` | 위치 이동 | 파생 관계 오인 방지는 해당 선 툴팁/패널에 유지, 전체 지도에는 압축 |
| 시세·감성 분석 데이터 연동을 준비… | `components/domain/status-labels.tsx:38-45` | **축약** | `시세 준비 중` 등 미제공 상태는 반드시 유지, 기술 사유는 도움말 |
| 현재 실시간 시세 연동 준비 중…사건 흐름 먼저… | `pages/company-page.tsx:50-52` | **축약** | 상단 `시세 준비 중`과 중복; 없는 시세는 표시 유지 |
| 바닥 시세/재무 차트 준비 중 + 투자권유 아님 | `pages/company-page.tsx:68-70` | **축약** | 준비 중·투자권유 아님 모두 유지, 상단 중복 제거 |
| 사건과 근거 문서의 시각을 함께 확인해 보세요 | `pages/briefing-page.tsx:27-30` | 삭제 | 브리핑의 기본 동작을 다시 설명 |
| 보관 승인 사건을 규칙으로 묶은 예시…실시간/당일 아님 | `pages/briefing-page.tsx:26-30` | **축약** | 브리핑 실제 발행 아님·시각 오인 방지는 유지 |
| 시장 사례를 표시해요 / 내 종목 사건을 먼저 골랐어요 | `pages/briefing-page.tsx:55-59,100-107` | 축약 | 선택 이유 1줄만 필요할 때 표시; `보관된 승인` 남발 제거 |
| 회차 날짜/예정 발행 시각/발행 시각 미확정 | `components/domain/briefing-card.tsx:43-51` | **축약** | 예정 시각의 불확실성은 유지, `미확정`만 한 번 |
| 참고 문서 총 {n}건과 투자 고지 | `components/domain/briefing-card.tsx:63-65` | **축약** | 출처 개수와 투자 고지는 유지, 위 사건별 수와 표현 간소화 |
| 인용구는 수집 원문…창 닫으면 지도·선택 그대로 | `features/overlays.tsx:103-105` | **삭제/축약** | 뒤 문장 삭제, 원문 인용 범위 설명만 간결하게 유지 |
| 원문 본문이 없어 자동 대조 못함… | `components/domain/evidence.tsx:48-49` | **축약** | 검증 불가 사실은 유지, 내부 자동 대조 과정 생략 |
| 원문 기사 링크 접근 불가…수집 당시 인용문 | `components/domain/evidence.tsx:62-65` | **축약** | 링크 불가·인용 제공 상태 유지, 한 문장으로 |
| AI가 기사/공시 바탕으로 답변 + 프로토타입 예시 답변 | `features/chat-drawer.tsx:103-107` | **축약** | AI 생성·예시 답변 출처를 명확하게 한 번, 삭제 금지 |
| AI 예시 답변 + [예시 답변] 본 기능은… | `features/chat-drawer.tsx:168-172` | **축약** | 한 가지 표지만 유지, 중복 설명 제거 |
| 근거 부족 답변 보류와 긴 추측 부인 | `features/chat-drawer.tsx:151-163` | **축약** | 근거 부족으로 보류된 상태는 유지, 이유 한 줄 |
| AI 브리핑/요약 긴 고지·①~④ 생성 설명 | `components/domain/ai.tsx:23-24,43-71` | **축약/위치 이동** | AI 생성 표시와 원문 대체 불가 고지는 유지, 제작 상세는 열어보는 도움말 |
| 사건 기사에 기업 직접 등장 / 같은 사건에 함께 다뤄짐 등 | `lib/labels.ts:15-19` | 축약 | 관계별 구별은 필요, 설명은 패널 첫 1회 |
| `PoC 검증 정책을 통과…` 데이터 설명 | `lib/labels.ts:22-31` | **축약** | 실기사 승인/저장 스냅샷/합성 **세 종류 구분 필수**, `PoC`만 쉬운 말로 |
| 서버가 알려준 사유: {reason} | `lib/labels.ts:77-99` | 축약 | 원인 불명일 때 원시 코드가 보일 수 있음; 사용자 조치만 표시 |
| BFF가 켜져 있는지/데이터 원천(PoC) 장애/오류 코드 | `components/ui/feedback.tsx:81-112` | 축약/위치 이동 | 실패·재시도는 유지, 서버 진단어·코드는 도움말/지원 정보로 |
| '보기/닫기' 같은 패널 상세와 반복된 관계 설명 | `features/node-panel.tsx:130-194,330-366` | 축약 | 승인/파생 차이는 유지, 동일 내용 두 문단이면 한 번 |
| 디자인시스템 `토큰 v`, 코드 경로, Tailwind/GraphCanvas/cose/dagre, 사양 문장 | `pages/design-system-page.tsx:50-136,286-930` | **위치 이동** | 개발/디자인 참고 자료로 유지하되 소비자 헤더에서 노출하지 않기; 공개 열람 시 `예시` 경계 유지 |
| 보도 표현 `announced` 등 원시 영문 값 | `features/node-panel.tsx:373-376` | 축약 | BFF 제공 분류값을 사용자 언어로 변환하고 검증 통과 여부는 유지 |

**기본 유지 규칙의 파일별 나머지 전수 분류**(윗표 우선 적용): `App.tsx:27-38`(404 복귀), `pages/login-page.tsx:33-84`(제목·인증·오류), `pages/onboarding-page.tsx:31-389`(검색·선택·빈 상태·오류·완료), `pages/main-page.tsx:58-233`(모드·빈 상태·목록), `pages/company-page.tsx:24-175`(기업·타임라인·필터·상태), `pages/briefing-page.tsx:23-182`(브리핑·관계도·빈 상태), `pages/design-system-page.tsx:50-954`(디자이너용 실물 예제·표준 문구), `features/app-shell.tsx:20-133`(헤더·접속·오류), `features/graph-explorer.tsx:26-88`(그래프/목록 전환·스크린리더 이름), `features/node-panel.tsx:35-437`(기업·사건·간선·근거·검증), `features/chat-drawer.tsx:28-199`(질문·추천·응답·투자 고지), `features/overlays.tsx:72-107`(근거 창·빈/오류), `components/domain/{ai,briefing-card,company-header,evidence,graph-canvas,graph-legend,issue-card,relation-list,relation-type-tag,status-labels}.tsx`(해당 파일의 나머지 상태/접근성 문자열), `components/ui/{button,badge,card,dialog,feedback,input,select,tabs,toast,tooltip}.tsx`(나머지 필수 레이블/상태), `lib/labels.ts:8-99`(나머지 모드·관계·날짜·빈 상태). **이유:** 행동명, 데이터 정체성, 인증·오류·빈 상태 복구, 출처와 법적 신뢰 제약, 접근성 이름 또는 개발자용 사양으로 기능이 있다. 사용자가 직접 보는 `BFF 기본 예시`는 BFF 동적 라벨이므로 소스 전수 범위 밖이지만 윗표에 별도로 포함했다. 같은 범위의 한국어 소스 주석·테스트가 없는 CSS 클래스는 사용자 노출 문구로 취급하지 않는다.

## 컨테이너·칩 인벤토리

| 위치·실제 사진 | 둥근/테두리 표면·그림자 | 필요한 역할과 감축 판단 |
|---|---|---|
| 로그인 [`login-light-1440.png`](audit/login-light-1440.png) | 로그인 `Card` 안에 입력 테두리·버튼, `card.tsx:9`, `login-page.tsx:37-81` | 폼 그룹은 필요하나 바깥 카드 테두리+그림자는 둘 다 불필요; 나머지는 입력 경계 필요 |
| 온보딩 [`onboarding-setup-dark-390.png`](audit/onboarding-setup-dark-390.png) | 선택지 카드 2개 각각 테두리+그림자, 내부 계좌 라디오·검색 결과 테두리, `onboarding-page.tsx:85-100,125-165,205-303` | 경쟁 대안 구분은 필요, 카드 안 라디오·검색 결과는 배경/분리선으로 위계 완화 |
| 튜토리얼 [`onboarding-tutorial-dark-390.png`](audit/onboarding-tutorial-dark-390.png) | 단계 띠 둥근 색 상자 + 단계 알약, 지도/목록 별도 경계, `onboarding-page.tsx:339-358` | 진행 상태는 유지, 알약 3개보다는 단계 문장 한 줄 |
| 메인 [`map-market-dark-390.png`](audit/map-market-dark-390.png) | 목록에서 **노드마다** 둥근 테두리 박스, 내부 간선 가지, 모드·보기 탭 각각 외곽, `relation-list.tsx:69-110`, `graph-legend.tsx:63-75` | 기업/사건 계층은 필요, 같은 종류 항목은 행/간격으로 병합 |
| 그래프 [`map-market-graph-dark-390.png`](audit/map-market-graph-dark-390.png) | 지도 테두리·점 배경 + 도구 막대 테두리/그림자, `graph-canvas.tsx:303-313` | 캔버스 구분 필요, 점은 지도 공간의 측량적 역할일 때만 유지 |
| 노드·간선 패널 [`map-node-panel-dark-390.png`](audit/map-node-panel-dark-390.png), [`map-edge-panel-dark-390.png`](audit/map-edge-panel-dark-390.png) | 패널 경계/그림자 안 이슈 카드 경계/그림자와 상태 박스, `graph-explorer.tsx:100-103`, `issue-card.tsx:45`, `node-panel.tsx:353-366` | 패널 표면은 필요, 내부 사건은 행으로 평탄화; 승인/파생 상태는 텍스트로 유지 |
| 근거·AI 창 [`map-evidence-dark-390.png`](audit/map-evidence-dark-390.png), [`map-ai-question-dark-390.png`](audit/map-ai-question-dark-390.png) | 시트·인용 박스·답변 카드·추천 질문 버튼이 중첩, `dialog.tsx:73-74`, `evidence.tsx:45`, `chat-drawer.tsx:101-179` | 모달과 인용 구분은 필요, AI 설명 박스/추천 알약은 위계 간소화 |
| 기업·브리핑 [`company-dark-390.png`](audit/company-dark-390.png), [`briefing-dark-1440.png`](audit/briefing-dark-1440.png) | 날짜별 카드, 바깥 브리핑 카드 속 이슈 카드, `company-page.tsx:121-144`, `briefing-card.tsx:38`, `issue-card.tsx:45` | 사건 단위 분리는 필요하지만 카드 안 카드는 제거 |
| 디자인시스템 [`design-system-dark-390.png`](audit/design-system-dark-390.png) | 색상 샘플·컴포넌트 예제·테이블 박스 중첩, `design-system-page.tsx:93,345-354,364-365` | 사양 예시에는 구분 필요하나 페이지가 소비자 내비와 섞이지 않게 |

유색 표지 분류(390px 다크, **한 화면 상태의 DOM 동시 표시**, 스크롤 없이 모두 시야에 있다는 뜻은 아님): 메인 노드 시트에서 배경 목록/시트에 보이는 유색 `span` 13개(시세 준비 2, 직접 관련 6, 보유 1, AI 요약 1, 요약 준비 1, 영향 준비 2) + 출처 버튼 2개로 **15개**; 브리핑은 브리핑 종류 1·발행 미확정 1·내 종목 관련 2·영향 준비 2 + 출처 버튼 2개로 **8개**. 측정 기준은 현재 보이는 DOM에서 투명하지 않은 배경을 가진 텍스트 `span`, 별도의 출처 버튼을 합산한 것이다. [`map-node-panel-dark-390.png`](audit/map-node-panel-dark-390.png), [`briefing-dark-390.png`](audit/briefing-dark-390.png); 출처/AI·검증/준비 중은 **의미 있는 필수 표지**, 동일 `직접 관련`의 반복·기업/보유의 연속 배지·같은 범위의 중복 출처 버튼은 축소 대상(`status-labels.tsx:8-49`, `company-header.tsx:38-52`, `issue-card.tsx:45-94`, `briefing-card.tsx:40-52`). 다크에서 보라 합성, 청록 보유/AI, 파랑 관계, 노랑 미확정이 동시에 경쟁한다. 색만으로 위험이나 가격 방향을 단정하지 않는다. 디자인시스템의 수십 개 컬러칩은 팔레트 샘플이라는 별도 목적(`design-system-page.tsx:334-354`).

## UX 흐름 관찰과 개선

| 장면 | 관찰/증거 | 개선 제안 |
|---|---|---|
| 첫 가치 확인 | 비회원 실측: `/login`에서 체험 **1클릭** → `/`의 시장 사건 목록. [추론: 동일한 지도 컴포넌트의 회원 클릭 경로 기준] 사건 상세까지 노드 1클릭 + 근거 1클릭 = **총 3클릭**. 회원 첫 설정 실측: 로그인 1 → 계좌 시작 1 → 튜토리얼 기업 노드 1 → 모바일 시트 닫기 1 → 완료 1 → 지도 노드 1 → 근거 1 = **7클릭**. `web/src/pages/login-page.tsx:24-27,43-45`, `web/src/pages/onboarding-page.tsx:307-388`, `web/src/features/node-panel.tsx:132-159`; 캡처 `onboarding-tutorial-dark-390.png`, `map-evidence-dark-390.png` | 첫 진입에서 시장 사건/근거 1건을 먼저 보여준 뒤 관심 설정을 선택적으로 유도. 클릭 수는 선택 경로마다 달라짐 |
| 온보딩 막힘 | 2개 화면 단계지만 튜토리얼 안 3개 체크박스형 소단계. 관심 경로는 **0개로 진행 금지**, 자산 경로에는 기본 모의 계좌 1개. `onboarding-page.tsx:21-28,190-203,318-325`; 사진 `onboarding-setup-dark-390.png` | 0개 제한은 데이터 필수 조건이므로 유지, 실제로 다음 행동이 무엇인지 오류와 선택 결과 옆에 표시; 계좌 경로는 목표와 결과를 미리 보여주기 |
| 빈약한 데이터 | 합성 시장 그래프는 기업 1·사건 3, 그중 사건 1은 연결 0. 계좌 모드는 연결 2, 관심 모드는 `고른 관심 종목이 없어요` 빈 화면. `main-page.tsx:93-115`, 사진 `map-market-dark-390.png`, `map-watchlist-dark-390.png` | 연결 0도 숨기지 말고 `아직 연결 근거 없음`으로 표시; 사건 3개를 반복 카드로 부풀리지 말고 날짜/출처 중심 행 목록 |
| 막다른 길 | 관심 비어 있음 화면의 `시장 전체 보기`는 탈출이지만 **관심 추가**가 없음; 비회원은 자산·관심 라디오 비활성이고 헤더 로그인 이동 가능. `main-page.tsx:93-115,189-225`, `graph-legend.tsx:63-76`, `app-shell.tsx:92-106` | 관심 모드는 추가 행동, 비회원 잠금 옆에는 명시적 로그인 CTA |
| 뒤로가기·모드 | 실제 실행: 브리핑→지도(기본 내 자산)→시장 전체 클릭→브라우저 Back은 브리핑으로 이동. `setMode`/`setSelection` 둘 다 `replace:true`, `main-page.tsx:36-56`. 기업 상세의 `지도로 돌아가기`는 `/` 고정 `company-page.tsx:24-34` | 모드 이력과 기업 상세 복귀 맥락을 정의하고, 명시적 복귀 링크가 선택 모드·스크롤을 유지할지 결정 |
| 모바일 내비·오버레이 | 390px 헤더가 두 줄(메뉴 두 번째 줄), 하단 내비 없음(`app-shell.tsx:55-111`); 노드 패널은 고정 아래 최대 75dvh, 선택·완료 CTA를 가릴 수 있어 시트를 먼저 닫아야 함(`graph-explorer.tsx:100-103`). 그래프 직접 전환은 가로 86px 넘침; 디자인시스템은 124px 넘침. 사진 `onboarding-tutorial-dark-390.png`, `map-market-graph-dark-390.png`, `design-system-dark-390.png` | 지도/브리핑으로 복귀 가능한 하단 내비 또는 명확한 상단 대안, 고정 시트와 CTA의 안전 영역 확보, 툴바 줄바꿈/접기 |
| 테마·신뢰 | 합성 출처는 상단과 패널/브리핑에 반복된다. `datasetKind` 표시 자체는 필수(`docs/evidence/README.md:45-49`), AI 질문이 막 열릴 때 입력창은 세션 준비 동안 비활성 상태(실측 `map-ai-question-dark-390.png`, `chat-drawer.tsx:30-112`) | 출처를 공통 헤더와 데이터 범위 경계에 한 번씩만, 세션 준비는 명확한 상태로 표기; 실제 기사와 합성의 차이는 절대 감추지 않기 |

추가 주의: 자동 대비 경고 4건은 디자인시스템의 비활성 예시·오류 코드 예시(`--viewport` 공통), 실서비스 배지의 대비 실패를 곧바로 뜻하지 않는다. 실제 390px 다크 화면의 보조 글자·원문 고지·회차 정보는 작은 글씨가 많아 육안 검토 대상으로 남으며 수치상 WCAG 실패를 주장하려면 별도 요소별 대비 측정이 필요하다. 디자인 명세는 본문/보조 대비 목표를 제시한다(`docs/design/archive/design-direction-v1.md:60-106`).
