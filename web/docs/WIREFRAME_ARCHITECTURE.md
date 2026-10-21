# 와이어프레임 기반 프론트엔드 구조

작성일: 2026-10-12

## 1. 근거와 범위

입력: 「돈벌레 최종 프로젝트-와이어프레임.pdf」, 실제 PDF 8페이지. 보드에 적힌 문서 버전은 화면계획서 v2.1 / 2026-10-06이다.

| 실제 PDF 페이지 | 내용                               | 주의                                                       |
| --------------- | ---------------------------------- | ---------------------------------------------------------- |
| 1               | 로그인·회원가입·초기 설정          | 원본 화면 16~22쪽 참조                                     |
| 2               | 지도 튜토리얼 5단계                | 페이지 5개가 아닌 지도 안 안내 상태                        |
| 3               | 지도·선택 패널·근거·경로·회차 지도 | 확대는 같은 화면의 상태                                    |
| 4               | 종목 검색 화면                     | 화면 ID/주소 주석 없음, /stocks는 구현 제안                |
| 5               | 기업 상세·시점·문서·기업 정보      | 주석의 문서 탭 미표시 설명과 하단 실제 문서 탭 캡처가 공존 |
| 6               | 출근/퇴근 브리핑                   | 공개 조회, 날짜와 회차 공유                                |
| 7               | AI 질문·되묻기·복구                | 지도 위 서랍, 독립 /ai 페이지 없음                         |
| 8               | 관리자 9개 화면                    | 보드 제목은 09, 원본 61~69쪽 참조                          |

PDF 주석의 원본 페이지 번호와 이 파일의 실제 페이지를 혼동하지 않는다. 모바일 M-*와 D-MY-01은 다른 화면에서 참조되지만 독립 모바일/내 종목 화면은 이 PDF에 없다. 실제 4페이지에는 종목 화면이 있으므로 앞쪽의 “D-STK-01 미수록” 주석보다 실제 캡처를 우선 근거로 삼았다.

문서의 편집자 지시 문구는 원본 설명으로 취급했다. 이번 사용자 요청에 따라 개발 구조를 제안하며, 원본 화면 자체를 수정하거나 미확인 백엔드 동작을 구현 완료로 취급하지 않는다.

## 2. 분리 원칙과 현재 결과

- 라우트 진입점은 `pages/`, 화면 내부 UI는 `components/`에 둔다.
- 기존 초기 설정의 복수형 폴더 이름 유지.
- 사용자 페이지 10개 + 관리자 페이지 9개 = 총 19개 TSX 페이지.
- 지도 확대/포커스/선택/튜토리얼, 기업 탭, 브리핑 회차, AI 복구는 상태나 컴포넌트로 분리.
- 모바일과 데스크톱은 같은 라우트와 상태를 공유. 반응형 표현만 분기.
- 기본 섹션은 제목과 준비 상태를 표시하는 골조다. TODO에 화면 ID와 구현 책임을 명시했다.
- 실제 UI 완성이나 API 연동보다 파일 구조와 상태 책임을 확정하는 단계다.

### 타입 폴더 구조

화면과 store에서 공유하는 타입은 `src/types/<domain>/index.ts`에 둔다.

| 폴더       | 주요 타입                                          | 사용 영역                 |
| ---------- | -------------------------------------------------- | ------------------------- |
| common     | PageShellProps, EmptyStateProps, QueryChanges      | 공통 컴포넌트·URL 쿼리 훅 |
| auth       | Member, AuthState, LoginLocationState              | 사용자 인증·로그인        |
| onboarding | InvestmentStatus, OnboardingDraft, OnboardingState | 온보딩 단계와 초안 store  |
| map        | GraphTarget, MapMode, PersonalScope, GraphUiState  | 지도 URL·패널·튜토리얼    |
| stocks     | Item, ItemListParams, CreateItemRequest            | 종목 예시 API             |
| company    | CompanyTab, CompanyTabOption, ChartPeriod          | 기업 상세 탭·기간         |
| briefing   | BriefingEdition                                    | 브리핑 회차               |
| ai         | RecoveryStatus, AiChatState                        | AI 서랍과 대화 복구       |
| admin      | AdminSession, AdminSessionState                    | 관리자 인증 가드          |

각 페이지 파일에는 렌더링과 동작만 남기고 공유 타입 선언을 두지 않는다. 아직 데이터 계약이 없는 `my` 등은 추측성 모델이나 빈 타입 파일을 만들지 않으며, 실제 API·UI 계약이 생길 때 같은 규칙으로 추가한다. `ApiResponse<T>` 같은 API 전용 래퍼와 한 구현 파일에서만 쓰는 비공개 타입은 `src/apis/`가 소유한다.

## 3. 페이지 및 라우트

아래 경로는 `src/pages/` 기준이다.

| 화면                | 경로                                            | 페이지 파일                                    | 접근                                    | 근거                         |
| ------------------- | ----------------------------------------------- | ---------------------------------------------- | --------------------------------------- | ---------------------------- |
| 로그인              | /login                                          | auth/login/LoginPage.tsx                       | 공개                                    | D-AUT-01                     |
| 회원가입            | /signup                                         | auth/signup/SignupPage.tsx                     | 공개                                    | D-AUT-02                     |
| 투자 여부           | /onboarding                                     | onboarding/investment/InvestmentStatusPage.tsx | 회원                                    | D-ONB-01                     |
| 모의 계좌 연결      | /onboarding/account                             | onboarding/account/VirtualAccountPage.tsx      | 회원                                    | D-ONB-02                     |
| 관심 종목 설정      | /onboarding/watchlist                           | onboarding/watchlist/WatchlistSetupPage.tsx    | 회원                                    | D-WAT-01                     |
| 시장/개인/회차 지도 | /?mode=all 또는 personal, round=...             | map/MapPage.tsx                                | 공개, personal은 회원                   | D-GRP-01/01b, D-BRF-04       |
| 종목 탐색           | /stocks                                         | stocks/StocksPage.tsx                          | 공개                                    | 실제 4페이지, 주소는 제안    |
| 기업 상세           | /companies/:id                                  | company/CompanyDetailPage.tsx                  | 공개, 개인 데이터는 회원 한정 연결 예정 | D-COM-01~06                  |
| 브리핑              | /briefing?date=...&edition=morning 또는 evening | briefing/BriefingPage.tsx                      | 공개                                    | D-BRF-01/02                  |
| 내 종목             | /my                                             | my/MyStocksPage.tsx                            | 회원                                    | D-MY-01 참조, 세부 UI 미수록 |
| 관리자 로그인       | /admin/login                                    | admin/login/AdminLoginPage.tsx                 | 공개 진입                               | A-ADM-05c                    |
| 운영 대시보드       | /admin                                          | admin/dashboard/AdminDashboardPage.tsx         | 관리자                                  | A-ADM-01                     |
| 이용 통계           | /admin/stats                                    | admin/stats/AdminStatsPage.tsx                 | 관리자                                  | A-ADM-02                     |
| 기업별 통계         | /admin/stats/companies/:companyId               | admin/stats/AdminCompanyStatsPage.tsx          | 관리자                                  | A-ADM-02                     |
| 선호도·대화록       | /admin/feedback                                 | admin/feedback/AdminFeedbackPage.tsx           | 관리자                                  | A-ADM-02b                    |
| AI 대화록 상세      | /admin/feedback/transcripts/:sessionId          | admin/feedback/AdminTranscriptPage.tsx         | 관리자(대화록 열람 권한·목적)           | A-ADM-02b                    |
| 그래프 관제·검수    | /admin/pipeline                                 | admin/pipeline/AdminPipelinePage.tsx           | 관리자                                  | A-ADM-03                     |
| 브리핑 운영         | /admin/briefings                                | admin/briefings/AdminBriefingsPage.tsx         | 관리자                                  | A-ADM-04                     |
| AI 운영             | /admin/ai                                       | admin/ai/AdminAiPage.tsx                       | 관리자                                  | A-ADM-04b                    |
| 회원 관리           | /admin/members                                  | admin/members/AdminMembersPage.tsx             | 관리자                                  | A-ADM-05                     |
| 회원 상세           | /admin/members/:memberId                        | admin/members/AdminMemberDetailPage.tsx        | 관리자                                  | A-ADM-05                     |
| 감사 로그           | /admin/audit                                    | admin/audit/AdminAuditPage.tsx                 | 관리자                                  | A-ADM-05b                    |

온보딩은 원본에서 모두 /onboarding이다. 이번 구조에서는 직접 진입·뒤로 가기·단계 분리를 위해 하위 경로를 제안했다. 가입 성공/투자 여부에 따른 자동 분기와 완료 저장은 API 연결 시 구현한다. 현재 단계 내비게이션은 파일 골조를 확인하는 링크다.

루트 /는 공개 지도다. 기존 /home은 /로, /search는 /stocks로, /detail/:id는 /companies/:id로 리다이렉트한다. 관리자 보호 주소는 서버 관리자 세션을 확인한 뒤, 세션이 없거나 만료되면 /admin/login으로 안내된다(A-ADM-05c). 회원 세션으로는 들어갈 수 없다.

## 4. 페이지 내부 컴포넌트 파일

아래 경로는 `src/` 기준이다. 대부분 준비 상태를 반환하는 TSX 골조이며 실제 렌더러/API 구현은 후속 작업이다.

| 파일                                                | 담당 영역         | 화면 근거                   | 후속 책임                                                                                                                                                     |
| --------------------------------------------------- | ----------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `components/auth/SignupForm.tsx`                    | 회원가입          | D-AUT-02                    | 이메일·비밀번호·표시 이름·필수 약관 입력과 가입 API를 연결한다.                                                                                               |
| `components/auth/SocialLoginButtons.tsx`            | 간편 로그인       | D-AUT-01                    | Google·카카오 인증 공급자 연동이 확정되면 활성화한다.                                                                                                         |
| `components/onboarding/InvestmentChoice.tsx`        | 투자 여부         | D-ONB-01                    | 투자 중/미투자 선택을 온보딩 초안에 반영한다.                                                                                                                 |
| `components/portfolio/PortfolioConnect.tsx`         | 가상 계좌 연결    | D-ONB-02 / D-MY-01b         | 초기 설정·내 종목이 함께 쓰는 연결 기능. 진입 출처로 연결 후 이동을 구분한다.                                                                                 |
| `components/onboarding/WatchlistSelector.tsx`       | 관심 종목 선택    | D-WAT-01                    | 종목 검색·추가·제거와 저장을 연결한다. 0개 선택을 허용한다.                                                                                                   |
| `components/stocks/StockSearchForm.tsx`             | 종목 검색         | PDF 실제 4페이지            | 기업명·영문명·티커 검색을 연결한다.                                                                                                                           |
| `components/stocks/StockList.tsx`                   | 종목 목록         | PDF 실제 4페이지            | 목록 결과와 기업 상세·지도 이동을 연결한다.                                                                                                                   |
| `components/my/HoldingsSection.tsx`                 | 보유 종목         | D-MY-01 / 01b               | 연결 상태·모의 보유 표시, 확인 창을 거친 연결 끊기와 실패 시 다시 시도                                                                                        |
| `components/my/WatchlistSection.tsx`                | 관심 종목         | D-MY-01 / 01b               | 서버 관심 목록, 추가·빼기 즉시 저장, 실패 시 되돌림과 다시 시도                                                                                               |
| `components/graph/GraphCanvas.tsx`                  | 관계 지도         | D-GRP-01 / 01b              | 시장·개인·회차 지도와 확대 상태를 하나의 캔버스로 처리한다. 그래프 엔진은 추후 연결한다.                                                                      |
| `components/graph/EventDetailPanel.tsx`             | 사건 상세         | D-GRP-02                    | 사건·직접 관련 기업·근거와 AI 진입 동작을 연결한다.                                                                                                           |
| `components/graph/CompanyDetailPanel.tsx`           | 기업 요약         | D-GRP-03                    | 시세·1개월 추이·모의 보유·직접 이슈·기업 상세 이동을 연결한다.                                                                                                |
| `components/graph/RelationDetailPanel.tsx`          | 연결선 상세       | D-GRP-04                    | 관계 유형·방향 유무·공유 사건·근거를 표시한다.                                                                                                                |
| `components/graph/ImpactPathPanel.tsx`              | 영향 경로         | D-GRP-06                    | 기업-사건 경로와 단계별 근거를 연결한다.                                                                                                                      |
| `components/graph/CompanyPathPanel.tsx`             | 두 기업 사이 경로 | D-GRP-07                    | 두 번째 기업 선택·최단 무방향 경로·경로 없음을 구분한다.                                                                                                      |
| `components/graph/GraphFocusControls.tsx`           | 기업 포커스       | D-GRP-07b                   | focus/hops URL을 사용한다. 패널 닫기와 포커스 해제를 구분한다.                                                                                                |
| `components/graph/GraphTutorial.tsx`                | 지도 사용 안내    | D-GRP-T / T2 / T3 / T4 / T5 | 5개 안내 단계를 데이터로 구성하고 이전·다음·건너뛰기·완료를 연결한다.                                                                                         |
| `components/graph/BriefingSnapshotBanner.tsx`       | 회차 기준 지도    | D-BRF-04                    | round 식별자로 고정 스냅샷을 조회하고 원래 브리핑으로 돌아간다.                                                                                               |
| `components/company/CompanySidebar.tsx`             | 기업 선택         | D-COM-03 내부 요소          | 기업 전환 시 period/asOf/tab은 유지하고 사건·버킷 선택만 초기화한다.                                                                                          |
| `components/company/CompanyOverview.tsx`            | 기업 시세·보유    | D-COM-01                    | 시세·지표·모의 보유를 독립적으로 조회하고 실패를 분리한다.                                                                                                    |
| `components/company/CompanyEventsTab.tsx`           | 사건·시점 탐색    | D-COM-01b / 05 / 06         | 기간·차트·시간 버킷·asOf를 연동한다. 가격과 사건의 시간 겹침을 인과로 표시하지 않는다.                                                                        |
| `components/company/CompanyDocumentsTab.tsx`        | 관련 문서         | D-COM-02                    | 출처·발행 시각·인용을 제공한다. 문서 탭 설명과 일부 프레임이 불일치한다.                                                                                      |
| `components/company/CompanyInfoTab.tsx`             | 기업 정보         | PDF 실제 5페이지 하단       | 정식 명칭·시장·업종·설립·홈페이지를 표시한다.                                                                                                                 |
| `components/company/CompanyRelationGraph.tsx`       | 기업 관계 그래프  | D-COM-04 내부 요소          | 기업 상세와 같은 asOf를 사용하고 전체 지도 진입을 연결한다.                                                                                                   |
| `components/briefing/PublishedBriefing.tsx`         | 발행 회차 조회    | D-BRF-01 / 02               | 날짜·회차 API 조회, 상태·재시도·정정 이력과 불변 발행 데이터를 표시한다.                                                                                      |
| `components/briefing/MarketIndicators.tsx`          | 주요 시장 지표    | D-BRF-01 / 02               | 회차 시각과 지표 관측 시각을 구분하고 정상·지연·사용 불가·실패를 분리한다.                                                                                    |
| `components/briefing/BriefingIssueList.tsx`         | 핵심 이슈         | D-BRF-01 / 02               | 핵심 이슈·선정 이유·근거·회차 지도·피드백을 연결한다.                                                                                                         |
| `components/briefing/BriefingComparison.tsx`        | 아침 대비 변화    | D-BRF-02                    | 동일 날짜 출근 회차 대비 신규·이어짐·빠짐을 비교한다.                                                                                                         |
| `components/admin/dashboard/DashboardSummary.tsx`   | 운영 현황         | A-ADM-01                    | getAdminDashboard로 검수·그래프·GraphDB·작업·AI·브리핑·이용 현황을 요약하고 각 관리 화면으로 연결한다.                                                        |
| `components/admin/stats/UsageStatistics.tsx`        | 이용·AI 품질 통계 | A-ADM-02                    | 기간(7일·30일·전체)별 지표·산식·일별 추이·회차별 조회와 종목 순위(커서)를 보여 주고, 표본이 작으면 비율을 숨긴다.                                             |
| `components/admin/feedback/FeedbackReview.tsx`      | 선호도·대화록     | A-ADM-02b                   | 유효 평가 집계·싫어요 사유(커서)·가린 대화록을 보여 준다. 대화록은 열람 목적을 받은 뒤에만 요청한다.                                                          |
| `components/admin/pipeline/PipelineReview.tsx`      | 그래프 관제·검수  | A-ADM-03                    | 후보·공개 버전·작업 상태를 연결한다. 검수 권한과 R1 정책은 확정 필요하다.                                                                                     |
| `components/admin/briefings/BriefingOperations.tsx` | 브리핑 회차·이력  | A-ADM-04                    | 회차별 데이터 기준 시점·단계 상태·실패 사유(커서)와 발행 원문·정정·처리 기록을 보여 주고, 사유를 받아 재처리·정정·제공 중단/재개를 요청한다(Idempotency-Key). |
| `components/admin/ai/AiUsageOverview.tsx`           | AI 사용량·오류    | A-ADM-04b                   | 기능별 요청·실제 모델 호출·재사용·재시도·처리 시간·토큰과 실제/추정 비용을 구분한다. 모르는 값은 0으로 채우지 않는다.                                         |
| `components/admin/members/MemberManagement.tsx`     | 회원·접근 관리    | A-ADM-05                    | 가명 ID·가린 이메일·활동 요약과 정상/차단 필터·검색(커서)을 보여 준다. 회원 상세에서 사유를 받아 차단·해제한다(Idempotency-Key).                              |
| `components/admin/audit/AuditLogTable.tsx`          | 관리자 감사 로그  | A-ADM-05b                   | 감사 기록의 시각·주체·동작·대상·결과·사유를 동작 필터·검색(커서)으로 조회한다. 기록은 만들거나 고치지 않는다.                                                 |
| `components/evidence/EvidenceDrawer.tsx`            | 근거 창           | D-GRP-05                    | 대상별 출처·인용·발행/검증 시각, 성공 근거 유지 및 실패 부분 재시도                                                                                           |
| `components/ai/AiChatDrawer.tsx`                    | AI 서랍           | D-AI-01/01b/02/02b          | 연결 대상·초안·대화 회수·새 요청, 닫기 후 맥락 유지                                                                                                           |

`OnboardingLayout`, `AdminLayout`, `AdminProtectedRoute`도 생성했다. `SocialLoginButtons`는 파일만 준비했으며 인증 공급자 미확정 상태에서 동작하는 로그인 버튼으로 노출하지 않았다.

## 5. 공통 컴포넌트 후보

### 이미 재사용하는 골조

| 컴포넌트                              | 재사용 위치                   | 현재 수준                      |
| ------------------------------------- | ----------------------------- | ------------------------------ |
| AppLayout / DesktopHeader / BottomNav | 지도·종목·기업·브리핑·내 종목 | 공통 레이아웃 및 768px 반응형  |
| PageShell                             | 페이지 진입점                 | 제목·세로 간격                 |
| PageSection                           | 기능 컴포넌트                 | 섹션 제목·테두리               |
| EmptyState                            | 기능 컴포넌트                 | 준비 안내                      |
| ProtectedRoute                        | 온보딩·내 종목                | 회원 인증 상태 구독            |
| AdminProtectedRoute                   | 관리자 하위 페이지            | 독립 세션 확인 및 만료 시 이동 |

### 디자인/API 합의 후 추출할 후보

아래는 설계 후보이며 아직 별도 파일을 생성하지 않았다.

| 후보                                 | 재사용 화면                              | 주요 props / 책임                                          |
| ------------------------------------ | ---------------------------------------- | ---------------------------------------------------------- |
| Button / IconButton / FormField      | 로그인·검색·필터·관리자                  | variant, disabled, pending, label, error, aria-label       |
| SearchInput                          | 종목·관심 선택·기업 사이드바·관리자 목록 | value, onChange, onSubmit                                  |
| SegmentedControl                     | 지도 모드·범위·기간·브리핑 회차          | options, value, onChange                                   |
| StockRow / CompanyAvatar             | 종목·관심 선택·내 종목·기업 사이드바     | company, quote, selected, onSelect                         |
| WatchlistButton                      | 종목·지도 기업 패널·기업 상세            | companyId, isSaved, isPending; 저장은 서버 기준            |
| QuoteSummary / PriceChange           | 종목·기업 패널·기업 상세                 | 가격, 통화, 기준 시각, 출처, 지연 상태                     |
| HoldingsSummary                      | 내 종목·기업 패널·기업 상세              | 모의 보유, 평가 기준, 통화 불일치 처리                     |
| DataTimestamp / SourceLabel          | 시세·브리핑·근거·관계                    | observedAt/publishedAt/verifiedAt 구분                     |
| EventCard / EvidenceCard             | 지도·기업 상세·브리핑·AI                 | event/evidence, onOpen, source                             |
| FeedbackButtons                      | 브리핑 회차·이슈·AI 답변                 | targetType, targetId, vote, pending                        |
| AsyncBoundary                        | 각 데이터 섹션                           | loading / empty / error / unavailable 구분; 부분 실패 유지 |
| ResponsivePanel                      | 사건·기업·근거·AI                        | 데스크톱 패널 / 모바일 시트, 초점 관리·닫기·복원           |
| DataTable / Pagination / StatusBadge | 관리자 목록·통계·이력                    | columns, rows, status, sort, paging                        |

한 화면에서만 쓰는 부품을 무조건 common으로 올리지 않는다. 그래프 캔버스와 회사 그래프는 데이터·상호작용 계약을 확인한 뒤 렌더러를 공유한다.

## 6. 전역 상태 정의

`src/stores/`에 아래 Zustand store를 실제 생성했다. persist는 쓰지 않는다(인증은 서버 세션 쿠키).

| Store                | 변수와 초기값                                                                       | 공유 이유 / 생명주기                                                                                     | 현재 연결                                                                                 |
| -------------------- | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| useAuthStore         | status: 'checking'; session: null; member: null; onboardingCompleted: null          | 가드·헤더·개인 기능에서 인증 참조. `SessionResponse`의 회원·비회원·없음과 초기 설정 완료 여부, CSRF 토큰 | session API·loadSession, 로그아웃, useAuth, ProtectedRoute                                |
| useAdminSessionStore | status: 'checking'; session: null; admin: null; revision: 0                         | 회원과 독립된 관리자 세션(`AdminSession`: 관리자·만료·CSRF). 메모리만 사용                               | `apis/admin/auth.ts`(session·login·logout·adminCall), AdminProtectedRoute, AdminLoginPage |
| useOnboardingStore   | investmentStatus: null; virtualAccountId: null; watchlistIds: []                    | 여러 단계에서 공유하는 저장 전 초안                                                                      | 타입·setter·toggle·reset 정의, 입력/저장 UI 후속 연결                                     |
| useGraphUiStore      | evidenceTarget: null; tutorialStep: null                                            | 지도 패널과 근거 창·튜토리얼 간 공유                                                                     | 근거 창 열림/닫힘, 튜토리얼 setter는 후속 단계 UI 연결                                    |
| useAiChatStore       | isOpen: false; context: null; conversationId: null; draft: ''; recoveryStatus: idle | 지도 선택과 AI 서랍 공유, 닫아도 초안/맥락 유지                                                          | 지도에서 열기·닫기·초안, 대화 조회/전송은 미연결                                          |

`GraphTarget`은 company/issue/edge/path + id의 판별 유니온이다. 문자열 ID만 저장하며 문서·시세·응답 본문을 전역 상태에 복제하지 않는다.

인증 정보 제거 시 온보딩·지도 UI·AI store도 reset한다. 관리자 세션은 회원 로그아웃과 독립적이다. 관리자 화면은 진입 시 `GET /api/v1/admin/auth/session`으로 서버 세션을 회수하고, 만료 시각에 다시 확인한다. 관리자 API는 `adminCall`로 호출해 관리자 CSRF를 붙이고, 401이면 관리자 세션만 비운다.

### URL이 소유할 상태

| 영역        | 변수                                                            | 이유 / 현재 적용                                                                     |
| ----------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 지도        | mode, scope, select, id, focus, hops, impact, path, round, tour | 링크 공유·뒤로 가기. useGraphQuery에서 mode/scope/target/hops 파싱, 패널 조건 렌더링 |
| 종목 검색   | q, scope, page                                                  | 검색 결과 재현. 후속 검색 UI 구현 시 연결                                            |
| 기업 상세   | :id, tab, period, asOf                                          | 기업 전환에도 기간·시점·탭 유지. tab 전환은 구현, 기간/시점 데이터 후속 연결         |
| 브리핑      | date, edition                                                   | 같은 날짜의 출근/퇴근 전환. 날짜·회차 컨트롤 연결                                    |
| 관리자 목록 | 검색·기간·상태·page                                             | 필터 복원. 각 API 계약 이후 연결                                                     |

원본의 `select=company` 등은 선택 유형 예시로만 쓰인다. 실제 개체 식별은 별도 `id`를 사용하도록 제안했다. URL 상태를 같은 이름의 Zustand 필드로 중복 관리하지 않는다.

### 서버 상태 / 로컬 상태

- 서버 상태: 저장된 관심 목록, 모의 보유, 기업/사건/관계/근거, 시세, 브리핑 발행 회차, 저장 대화/작업, 관리자 통계/감사 로그.
- 서버 상태는 기능 API와 조회 훅에서 관리한다. 조회 캐시 도구 도입은 미결정이며 TanStack Query를 임의 추가하지 않았다.
- 로컬 상태: 비밀번호·이메일 등 폼 입력, 제출 중/필드 오류, 컴포넌트 한 곳의 펼침 상태, 차트 hover, DOM/canvas 참조.
- 기업 상세의 선택 사건/버킷은 기업 변경 시 초기화한다. 현재 기업별 본문에 key를 두었으며 실제 차트 구현에서 적용한다.
- 그래프 드래그·줌의 고빈도 좌표는 렌더러/ref가 소유한다. 화면 간 복원이 필요해지면 직렬화 가능한 스냅샷만 별도로 설계한다.

## 7. 공통 훅 후보

### 생성한 훅

| 파일                 | 책임                                                                    | 사용/상태                             |
| -------------------- | ----------------------------------------------------------------------- | ------------------------------------- |
| useAuth.ts           | 인증 구독, 프로필/온보딩 완료 여부, logout, 다른 탭 storage 변경 동기화 | ProtectedRoute, MapPage, AiChatDrawer |
| useRouteQuery.ts     | 기존 쿼리를 보존하면서 지정 키 갱신/삭제                                | 지도·기업 탭·브리핑                   |
| useGraphQuery.ts     | 지도 mode/scope/selection/round/focus/hops 파싱                         | MapPage                               |
| useDisclosure.ts     | 열기·닫기·토글                                                          | 범용 후보, 사용처 연결 예정           |
| useDebouncedValue.ts | 검색 입력 지연 반영, timeout 정리                                       | 종목/관심 검색 후보, 사용처 연결 예정 |

### API/UX 연결 시 만들 훅

| 후보               | 입력·결과 및 책임                                                           |
| ------------------ | --------------------------------------------------------------------------- |
| useStockSearch     | keyword/scope/page → 결과, 로딩, 오류; debounce와 이전 요청 취소            |
| useWatchlist       | 서버 관심 목록 및 추가/해제, pending/실패 복구; 0개 정상                    |
| useVirtualAccount  | 모의 계좌 연결 상태와 보유 목록; 실제 계좌 아님                             |
| useOnboarding      | 단계 분기·초안 저장·완료 반영; 계좌 건너뛰기 지원                           |
| useCompanyDetail   | companyId/period/asOf → 시세/사건/문서/관계; 섹션별 실패 분리               |
| useGraphSelection  | URL 대상 선택 및 이전 선택 복귀; focus/round 유지                           |
| useGraphViewport   | 확대·축소·맞춤·키보드 조작; 고빈도 좌표는 ref 사용                          |
| useEvidence        | target → 근거 목록; 403/404 unavailable, 일시 실패 부분만 재시도            |
| useBriefing        | date/edition → 불변 회차 조회; 생성 상태와 지표 상태 분리                   |
| useAiConversation  | conversationId → 기존 대화 회수; 재조회와 새 질문 전송 분리, 중복 전송 방지 |
| useFeedback        | target + 투표 상태; 취소된 투표 제외                                        |
| useAdminSession    | 별도 세션 확인·회수·만료·logout; 회원 토큰 미사용                           |
| useAdminTableQuery | 기간/검색/상태/page URL + 조회; 0건과 실패 분리                             |
| useFocusReturn     | 서랍 열림/닫힘 시 초점 이동·복원; 실제 modal semantics와 함께 구현          |
| useMediaQuery      | 캔버스 동작 등 JS 분기가 필요한 경우만. 표시 여부는 Tailwind md 우선        |

구현되지 않은 훅에 가짜 성공 값을 반환하는 함수를 추가하지 않았다.

## 8. 원본에서 확정이 필요한 사항

- D-COM-02: 주석은 문서 탭 미표시라고 적지만 실제 5페이지 하단에는 문서/기업 정보 탭이 있다. 구조는 세 탭으로 준비하고 최종 상호작용은 합의 필요.
- D-COM-05/06: 과거 기준 시점과 화면 날짜가 불일치. period/asOf의 API 계약과 버킷 규칙 확정 필요.
- D-AI-02/02b: 정적 그림은 대화 회수 성공/실패를 입증하지 않음. 모델 실행과 회수 API를 분리할 것.
- D-MY-01 및 모바일 화면: 독립 캡처 없음. 내 종목은 보유/관심 섹션 후보만 생성.
- D-AUT-03 모의 provider 동의, D-WAT-01b 4개 선택: 별도 페이지로 만들지 않음. 소셜 연동/선택 상태로 처리.
- 시세·근거·브리핑 출처와 각 기준 시각, 환율/지연/보관 정책은 백엔드와 합의 필요.
- 관리자 권한·R1 검수·마스킹·회수 정책은 서버 계약이 필요. 현재 파일은 운영 API를 호출하지 않음.

## 9. 이번 작업 확인 범위

- 19개 페이지를 라우트별 lazy import로 연결.
- 공개 지도/종목/기업/브리핑과 회원 전용 온보딩/내 종목 분리.
- 개인 지도는 로그인으로 복귀 경로(search/hash 포함)를 보존.
- 관리자 별도 세션 가드와 레이아웃 준비.
- 기존 일반 예시 페이지 4개를 도메인 페이지로 대체하고 로그인은 폴더 이동.
- 린트·포맷·TypeScript/프로덕션 빌드 검사.
- 실제 서버 인증, 브라우저 반응형 시각 검증, 그래프/차트 동작, API 오류/재시도/상태 복원 end-to-end 검증은 후속 기능 구현 단계에서 수행.

초기 환경의 상세 구성은 [초기 설정 정리](./FRONTEND_SETUP.md)를 참고한다.
