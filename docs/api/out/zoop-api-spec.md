# 줍 정식 서버 목표 API 명세서

생성물이다. 정본은 [openapi.yaml](../openapi.yaml)이다. WBS **6.1.2 API 명세 최종 검토·구현 기준 확정**, **6.11.1 API·스키마 계약 통합 점검**에 연결한다. API 공통 규칙은 사용자 **잠정 채택/시연 기준**이며 정식 구현 완료가 아니다. 전체 명세/WBS(FS074~081 포함)의 현재 범위는 팀합의요구/설계대상이며 원문 승인 표기·구현 증거·유료 실행 승인은 별개다. 추천 종목·산업·테마(FS011-02)는 활성 사용자 기능에서 제외하되 작업을 유보하며 요구 42의 재무·실적은 폐기되지 않았다(기록된 예외). 프로토타입 관측과 구현 목표를 구분한다.

[현재 사용자 결정(10-10)](../../share/day-work-2026-10-10.md) · [이전 결정(10-08)](../../share/day-work-2026-10-08.md) · [API v2 검토·채택/정정 목록](../../evidence/api-v2-review-2026-10-08.md) · [10-12 원문 갱신 기록](../../evidence/doc-delta-2026-10-12.md) · [10-10 원문 갱신 근거](../../evidence/doc-delta-2026-10-10.md) · [유효 기준 JSON](../../system/out/effective-authority.json) · [범위 예외·상세 권한](../../system/out/detail-authority.md) · [추적표](../../system/out/index.md) · [현재 검사 결과](../../system/out/warnings.md) · [WBS 내용 기반 이행](../../system/out/wbs-migration.md) · [BFF 차이](../../system/out/api-differences.md)

## 공통 규칙

### versioning

모든 정식 HTTP 경로는 /api/v1로 시작한다. 호환되지 않는 변경은 새 경로 버전으로 분리한다. operationId는 문서·추적표의 안정된 식별자다.

### authentication

회원과 관리자 세션은 별도 HttpOnly·Secure 쿠키(zoop_session, zoop_admin_session)로 구분한다. 세션 쿠키는 서버에서 검증한다. 개인 리소스는 매번 소유권을 검증한다. 비회원은 전체 그래프·공개 기업·공개 브리핑을 읽을 수 있지만 개인화·질문·평가는 불가하다. 쿠키 인증 쓰기는 Origin 검증과 세션에 결합된 X-CSRF-Token을 요구한다. 로그인·가입·비회원 시작·외부 인증 콜백에는 세션 생성 전 Origin/state 검증을 적용한다. 회원/관리자 로그아웃에서 해당 활성 세션이 있으면 같은 쿠키·Origin·세션 결합 CSRF를 반드시 검증하며 실패는 403 ACCESS_DENIED다. CSRF가 없거나 틀렸다고 무세션 분기로 우회하지 않는다. 해당 세션이 없거나 무효/만료이면 다른 세션을 변경하지 않고 204와 해당 쿠키만 제거한다. OpenAPI의 선택 인증/선택 헤더는 이 조건부 런타임 검증을 자동 강제하지 않는다.

### sessionLifecycle

로그아웃과 차단은 서버 세션을 폐기한다. 회원 세션 수명·관리자 유휴/절대 만료·SSO 제공자·CSRF 토큰 발급 형식은 팀 확인 필요이며 계약에 수치를 고정하지 않는다. 세션 응답의 expiresAt 및 csrfToken으로 실제 적용값을 전달한다.

### errors

오류는 application/json의 {error:{code,message,requestId,retryable,details?}}다. HTTP 상태와 안정된 대문자 오류 코드를 함께 사용한다. 빈 자료·근거 부족은 성공 결과이고 외부 장애와 구분한다. 보유량·분모 없음·시세 미제공을 0으로 대체하지 않는다.

### requestIds

모든 요청은 선택 X-Request-ID를 받는다. 없으면 서버가 생성하고 모든 응답의 X-Request-ID에 실제 ID를 반환한다. 서로 다른 전송은 별도 요청 ID를 사용한다. 로그와 작업 ID를 연결하되 요청 ID를 멱등성 키로 사용하지 않는다.

### idempotency

부작용을 발생시키는 POST는 필수 Idempotency-Key를 받는다(세션 생성·소셜 인증·회원/관리자 로그아웃은 제외). 로그아웃은 같은 세션의 반복 폐기가 같은 상태에 도달하는 자연 멱등 작업이며 추가 키 저장 계약 없이 반복 204를 반환한다. 같은 주체·메서드·경로·키·본문은 기존 저장 결과 또는 같은 진행 작업을 반환한다. 내용 불일치는 409 IDEMPOTENCY_CONFLICT다. PUT/DELETE는 목표 상태·리소스 ID로 멱등 처리하며 추가 키 없이 재전송할 수 있다. 키 보존 기간은 팀 확인 필요다. 응답 미수신은 기존 작업/상태 조회가 우선이며 새로운 키로 재실행하지 않는다.

### pagination

목록은 cursor·limit와 nextCursor를 사용한다. nextCursor=null은 마지막 페이지다. 커서는 불투명하며 정렬 키·필터·주체·고정 버전에 결합한다. 필터/버전을 바꾸면 첫 페이지부터 읽는다. 검색은 사용자가 명시적으로 실행하며 코드 정확 일치→이름 정확 일치→부분 일치 정렬을 유지한다. 고정 페이지 크기·상한·보존 기간은 실측/팀 확인 전 확정하지 않는다. 사용자가 전체를 순회할 수 있으며 임의 결과 상한으로 검색 결과를 버리지 않는다.

### timeAndAsOf

정확한 시각은 RFC 3339 date-time으로 UTC Z 또는 명시적 오프셋을 쓴다. 오프셋 없는 시각은 거절한다. 날짜는 YYYY-MM-DD이고 날짜 경계는 Asia/Seoul이다. asOf는 자료 기준 시점이며 응답 생성 시각과 다르다. 사건의 year/month/day/unknown 정밀도는 timePrecision과 함께 제공하고 미상 날짜를 정확한 시각으로 만들지 않는다. 차트와 타임라인에는 같은 from/to를 전달하고 재무 기간은 별도다.

### chartResolution

가격 차트의 봉 해상도는 기간별로 고정한다: 1d=5m, 1w=1h, 1m=1d, 1y=1wk(주봉). PriceSeries.interval은 공급된 해상도를 그대로 담으며 목표 해상도를 제공하지 못하면 다른 해상도의 값을 이름만 바꾸거나 집계·보간해 채우지 않고 200 unavailable(no_data)로 정상 자료 부재를 표현한다. 공급자 인증·네트워크·형식 장애는 503 SOURCE_UNAVAILABLE이다. 이 값은 목표 계약이며 공급자 출력을 만들어내지 않는다. 기계 판독용 매핑은 x-zoop-approvals.chartResolution이다.

### publicationVersions

그래프·사건·관계·근거 조회는 선택 graphVersion 또는 asOf를 받는다. 생략하면 한 요청 시작 시 활성 공개 버전을 고정하고 응답 metadata.graphVersion/asOf에 반환한다. 둘을 함께 지정하면 일치해야 한다. asOf는 그 시점 이전 공개 버전을 선택하며 이후 공개 자료는 사용하지 않는다. round는 발행 회차가 고정한 버전을 뜻한다. 고정 버전 부재는 VERSION_UNAVAILABLE이며 최신 자료로 대체하지 않는다. 브리핑은 그래프 버전·자료·시장 지표·긍부정을 발행 시 고정한다. 정정은 원문 밖에 덧붙인다.

### partialFailures

영역별 API는 독립 조회한다. 집계 결과의 일부 영역만 실패하면 200과 metadata.partial=true/failures를 반환하고 성공 영역을 유지한다. 자료 미제공은 unavailable, 실제 장애는 failed 또는 failures로 표현한다. 요청 전체를 처리하지 못한 경우에만 비2xx 오류다. 재시도는 실패 조회만 하며 저장/분석 재실행을 암묵적으로 수행하지 않는다.

### aiJobs

질문은 대화 ID·작업 ID·질문·대상·기간·asOf·graphVersion을 최초 접수 시 고정한다. 202는 접수, completed는 검증 및 결과 저장 완료다. queued/running/completed/failed/cancelled와 실패 종류·retryable·저장 결과를 회수한다. 되묻기·조건 부족·근거 부족은 기술 오류와 다르다. 생성 중 대화당 추가 질문을 거절한다. 검증 실패는 재생성하지 않고, 보존된 검증 결과의 저장 실패는 저장만 복구한다. 창 닫기는 취소가 아니다. AI v2 FS045~051이 현재 상세이며 옛 FS046(권한·중복 작업 통제)에는 대응하는 단일 신규 FS가 없다. 로그인·대화 소유·근거 접근 권한은 접수·상태 조회·결과 회수마다 재검증하고, 같은 작업 ID의 내용 불일치는 409로 거절하며, 서로 다른 작업 ID가 동시에 와도 같은 대화에는 처리 중 신규 작업을 하나만 접수한다. 상태 조회·결과 회수는 신규 접수와 구분한다(FS045·FS047·FS051·FS060과 NFS001/003의 공통 서버 의무).

### sentiment

DocumentSentiment는 문서×기업, BriefingOutlook은 발행 회차 판정이다. label은 positive/negative/mixed/undetermined(긍정/부정/혼재/판단 보류)이며 확률·점수를 제공하지 않는다. null은 아직 판정하지 않음이고 undetermined와 다르다. 원문 인용과 이유·판정 시각·모델·프롬프트 버전을 보존한다. 브리핑의 documentSentiments/outlook은 발행 시점에 고정한다. 이슈 자체의 종합 방향이나 투자 수익률로 확장하지 않는다.

### approvalBoundary

명세/WBS의 모든 내용은 현재 사용자 결정에 따라 팀합의요구/설계대상이며 FS074~081도 포함한다. 원문의 검토 전 표기는 갱신되지 않은 상태로 보존한다. 요구 범위 포함과 구현 완료·유료 모델 실행 승인·본개발 채택은 별개다. API 공통 규칙은 기존 잠정 채택/시연 기준이고 원본 충돌·운영 수치·정식 배포 인증 선택은 teamQuestions와 추적표에 보존한다.

### scopeExceptions

2026-10-10 사용자 결정으로 추천 종목·산업·테마(FS011-02)는 활성 사용자 기능에서 제외하되 GET /me/recommendations 계약은 유보한다. 삭제·무동작·가짜 응답으로 바꾸지 않으며 제외는 활성 사용 허용이 아님을 뜻한다. 요구 42의 재무·실적은 폐기되지 않았고 전용 FS/WBS 없이 getCompanyFinancials로만 출처 한정 연결한다. 정본은 docs/system/links.yaml authority.implementationScope.exceptions다.

### modelConfiguration

LLM 모델·추론 수준은 .env에서 stage별로 명시 설정한다. 문서 판정은 ZOOP_AI_DOCUMENT_SENTIMENT_MODEL/ZOOP_AI_DOCUMENT_SENTIMENT_REASONING_EFFORT, 회차 판정은 ZOOP_AI_BRIEFING_OUTLOOK_MODEL/ZOOP_AI_BRIEFING_OUTLOOK_REASONING_EFFORT를 사용한다. 요약은 ZOOP_AI_DOCUMENT_SUMMARY_*, 의미 검증은 ZOOP_AI_VERIFY_*로 분리한다. docs/design/ai-system.md의 설정 이행을 따르며 옛 ZOOP_SENTIMENT_* 런타임 alias는 없다. 설정 위치 결정과 실제 모델/공급자 선택·실행 승인은 구분하며 예산은 미정이다. 외부 PoC의 미지원 추론 전송 경계를 구분하고 공개 API에서 비밀 설정값을 반환하지 않는다.

### conflictPermission

프로토타입은 전권 범위로 끝까지 완성하며 본개발 채택은 담당자가 선택한다. 원본 충돌은 근거 있는 작업자 안과 정정 요청을 남겨 팀이 정정한다. 확정 일정은 WBS이며 옛 Notion 일정은 비권위다. 갱신된 Notion 회의·API 결정은 사례별 증거로만 쓴다. 원문 날짜·우선순위·승인 상태를 덮어쓰지 않는다.

## 오류 코드

| 코드 | HTTP | 의미 | 복구 규칙 |
| --- | --- | --- | --- |
| INVALID_REQUEST | 422 | 필수 입력·형식·범위 오류 | 필드 오류를 수정한다 |
| INVALID_CREDENTIALS | 401 | 로그인 인증 실패 | 입력을 다시 확인한다 |
| AUTH_REQUIRED | 401 | 유효 세션 없음 | 로그인한다 |
| MEMBER_REQUIRED | 403 | 회원 전용 기능에 비회원 접근 | 회원 로그인 후 요청한다 |
| ACCESS_DENIED | 403 | 소유권·관리자 권한 없음 또는 Origin/CSRF 검증 실패 | 보호 내용 없이 거절한다 |
| MEMBER_BLOCKED | 403 | 차단 회원 | 차단 상태를 안내한다 |
| EMAIL_TAKEN | 409 | 이미 등록된 이메일 | 다른 이메일 또는 로그인 선택 |
| TERMS_REQUIRED | 422 | 필수 약관 미동의 | 동의 항목을 확인한다 |
| RESOURCE_NOT_FOUND | 404 | 존재하지 않는 리소스 | 미등록 작업과 조회 장애를 구분한다 |
| EVIDENCE_UNAVAILABLE | 404 | 삭제·비공개 근거 | 원문 내용을 반환하지 않는다 |
| VERSION_UNAVAILABLE | 409 | 고정 그래프 버전을 조회할 수 없음 | 최신 버전으로 조용히 대체하지 않는다 |
| REVISION_CONFLICT | 409 | 낙관적 동시성 버전 충돌 | 현재 상태 조회 후 사용자 판단으로 변경한다 |
| IDEMPOTENCY_CONFLICT | 409 | 같은 키에 다른 요청 내용 | 기존 작업을 조회한다 |
| JOB_IN_PROGRESS | 409 | 동일 대화 또는 대상의 진행 중 작업 | 기존 작업을 조회한다 |
| JOB_NOT_RETRYABLE | 409 | 재실행이 허용되지 않는 실패 | 새 질문 또는 운영자 확인 |
| ALREADY_PUBLISHED | 409 | 이미 발행한 회차 변경 시도 | 정정으로 별도 등록한다 |
| VALIDATION_FAILED | 422 | 자동 검증 또는 필수 근거 검증 실패 | 공개하지 않는다 |
| SOCIAL_AUTH_CANCELLED | 400 | 소셜 인증 취소 | 시작 화면에서 다시 선택한다 |
| SOCIAL_AUTH_FAILED | 401 | 소셜 인증 state·코드 검증 실패 | 기존 세션 성공으로 처리하지 않는다 |
| INVALID_CURSOR | 422 | 만료 또는 조건 불일치 커서 | 첫 페이지부터 조회한다 |
| RATE_LIMITED | 429 | 확정된 운영 정책의 요청 한도 초과 | Retry-After 이후 확인한다 |
| SOURCE_UNAVAILABLE | 503 | 외부 자료 조회 장애 | 해당 영역 조회만 재시도한다 |
| MODEL_UNAVAILABLE | 503 | 분석 제공자 장애 | 저장된 작업 상태를 먼저 확인한다 |
| AUDIT_UNAVAILABLE | 503 | 필수 감사 기록 저장 실패 | 대화록·검수 변경을 차단한다 |
| MASKING_FAILED | 503 | 대화록 마스킹 실패 | 원문을 반환하지 않는다 |
| INTERNAL_ERROR | 500 | 분류되지 않은 기술 장애 | 자동 재실행하지 않고 요청 ID로 확인한다 |

## 작업 목록

| 작업 | 메서드 | 목표 경로 | 권한 | 우선순위 |
| --- | --- | --- | --- | --- |
| [getMemberSession](#getmembersession) | GET | /api/v1/auth/session | 공개 | P1 |
| [listTerms](#listterms) | GET | /api/v1/auth/terms | 공개 | P1 |
| [signUp](#signup) | POST | /api/v1/auth/signup | 공개 | P1 |
| [logIn](#login) | POST | /api/v1/auth/login | 공개 | P1 |
| [startGuestSession](#startguestsession) | POST | /api/v1/auth/guest | 공개 | P1 |
| [logOut](#logout) | POST | /api/v1/auth/logout | 공개 | P1 |
| [setTutorialState](#settutorialstate) | PUT | /api/v1/auth/tutorial | 회원 또는 비회원 세션 | P1 |
| [listSocialProviders](#listsocialproviders) | GET | /api/v1/auth/social/providers | 공개 | P1 |
| [authorizeSocialLogin](#authorizesociallogin) | GET | /api/v1/auth/social/{provider}/authorize | 공개 | P1 |
| [completeSocialLogin](#completesociallogin) | GET | /api/v1/auth/social/{provider}/callback | 공개 | P1 |
| [getMySettings](#getmysettings) | GET | /api/v1/me/settings | 회원(본인) | P1 |
| [updateMySettings](#updatemysettings) | PUT | /api/v1/me/settings | 회원(본인) | P1 |
| [setWatchlistCompany](#setwatchlistcompany) | PUT | /api/v1/me/watchlist/{id} | 회원(본인) | P1 |
| [listRecommendations](#listrecommendations) | GET | /api/v1/me/recommendations | 회원(본인) | P1 |
| [listVirtualAccountProfiles](#listvirtualaccountprofiles) | GET | /api/v1/portfolio/mock-portfolios | 회원(본인) | P1 |
| [getVirtualAccountProfile](#getvirtualaccountprofile) | GET | /api/v1/portfolio/mock-portfolios/{id} | 회원(본인) | P1 |
| [connectVirtualAccount](#connectvirtualaccount) | POST | /api/v1/portfolio/connections | 회원(본인) | P1 |
| [getMyPortfolio](#getmyportfolio) | GET | /api/v1/portfolio | 회원(본인) | P1 |
| [disconnectVirtualAccount](#disconnectvirtualaccount) | DELETE | /api/v1/portfolio/connections/{id} | 회원(본인) | P1 |
| [getGraph](#getgraph) | GET | /api/v1/graph | 공개(all) / 회원 본인(personal) | P1 |
| [getCompanyRelation](#getcompanyrelation) | GET | /api/v1/graph/edges/{id} | 공개 | P1 |
| [searchCompanies](#searchcompanies) | GET | /api/v1/companies | 공개 | P1 |
| [getCompany](#getcompany) | GET | /api/v1/companies/{id} | 공개 | P1 |
| [getCompanyQuote](#getcompanyquote) | GET | /api/v1/companies/{id}/quote | 공개 | P1 |
| [getCompanyMetrics](#getcompanymetrics) | GET | /api/v1/companies/{id}/metrics | 공개 | P1 |
| [getCompanyPrices](#getcompanyprices) | GET | /api/v1/companies/{id}/prices | 공개 | P1 |
| [listCompanyDocuments](#listcompanydocuments) | GET | /api/v1/companies/{id}/documents | 공개 | P1 |
| [listEvents](#listevents) | GET | /api/v1/events | 공개 | P1 |
| [getEvent](#getevent) | GET | /api/v1/events/{id} | 공개 | P1 |
| [getEvidence](#getevidence) | GET | /api/v1/evidence/{id} | 공개 | P1 |
| [getBriefing](#getbriefing) | GET | /api/v1/briefings | 공개 | P1 |
| [listBriefingRounds](#listbriefingrounds) | GET | /api/v1/briefings/rounds | 공개 | P1 |
| [getBriefingGraphBasis](#getbriefinggraphbasis) | GET | /api/v1/briefings/{id}/graph | 공개 | P1 |
| [createConversation](#createconversation) | PUT | /api/v1/chat/sessions/{id} | 회원(본인) | P1 |
| [getConversation](#getconversation) | GET | /api/v1/chat/sessions/{id} | 회원(본인) | P1 |
| [getCurrentConversation](#getcurrentconversation) | GET | /api/v1/chat/sessions/current | 회원(본인) | P1 |
| [submitQuestion](#submitquestion) | POST | /api/v1/chat/sessions/{id}/jobs | 회원(본인) | P1 |
| [getQuestionJob](#getquestionjob) | GET | /api/v1/chat/jobs/{job_id} | 회원(본인) | P1 |
| [retryQuestionJob](#retryquestionjob) | POST | /api/v1/chat/jobs/{job_id}/retry | 회원(본인) | P1 |
| [cancelQuestionJob](#cancelquestionjob) | POST | /api/v1/chat/jobs/{job_id}/cancel | 회원(본인) | P1 |
| [getAdminSession](#getadminsession) | GET | /api/v1/admin/auth/session | 공개 | P1 |
| [logInAdmin](#loginadmin) | POST | /api/v1/admin/auth/login | 공개 | P1 |
| [logOutAdmin](#logoutadmin) | POST | /api/v1/admin/auth/logout | 공개 | P1 |
| [getAdminDashboard](#getadmindashboard) | GET | /api/v1/admin/dashboard | 관리자(작업별 권한) | P1 |
| [listAuditRecords](#listauditrecords) | GET | /api/v1/admin/audit-log | 관리자(작업별 권한) | P1 |
| [getPipelineOverview](#getpipelineoverview) | GET | /api/v1/admin/pipeline/overview | 관리자(작업별 권한) | P1 |
| [listAnalysisCandidates](#listanalysiscandidates) | GET | /api/v1/admin/pipeline/candidates | 관리자(작업별 권한) | P1 |
| [getAnalysisCandidate](#getanalysiscandidate) | GET | /api/v1/admin/pipeline/candidates/{candidate_id} | 관리자(작업별 권한) | P1 |
| [decideAnalysisCandidate](#decideanalysiscandidate) | POST | /api/v1/admin/pipeline/candidates/{candidate_id}/decision | 관리자(작업별 권한) | P1 |
| [listPublicationRules](#listpublicationrules) | GET | /api/v1/admin/pipeline/rules | 관리자(작업별 권한) | P1 |
| [setPublicationRule](#setpublicationrule) | PUT | /api/v1/admin/pipeline/rules/{rule_id} | 관리자(작업별 권한) | P1 |
| [listGraphVersions](#listgraphversions) | GET | /api/v1/admin/graph/versions | 관리자(작업별 권한) | P1 |
| [publishGraphVersion](#publishgraphversion) | POST | /api/v1/admin/graph/versions | 관리자(작업별 권한) | P1 |
| [activateGraphVersion](#activategraphversion) | POST | /api/v1/admin/graph/versions/{version_id}/activate | 관리자(작업별 권한) | P1 |
| [listAnalysisJobs](#listanalysisjobs) | GET | /api/v1/admin/jobs | 관리자(작업별 권한) | P1 |
| [createAnalysisJob](#createanalysisjob) | POST | /api/v1/admin/jobs | 관리자(작업별 권한) | P1 |
| [getAnalysisJob](#getanalysisjob) | GET | /api/v1/admin/jobs/{job_id} | 관리자(작업별 권한) | P1 |
| [retryAnalysisJob](#retryanalysisjob) | POST | /api/v1/admin/jobs/{job_id}/retry | 관리자(작업별 권한) | P1 |
| [cancelAnalysisJob](#cancelanalysisjob) | POST | /api/v1/admin/jobs/{job_id}/cancel | 관리자(작업별 권한) | P1 |
| [getAiUsage](#getaiusage) | GET | /api/v1/admin/ai-usage | 관리자(작업별 권한) | P1 |
| [listAdminBriefingRounds](#listadminbriefingrounds) | GET | /api/v1/admin/briefings | 관리자(작업별 권한) | P1 |
| [getAdminBriefingRound](#getadminbriefinground) | GET | /api/v1/admin/briefings/{round_id} | 관리자(작업별 권한) | P1 |
| [reprocessBriefingRound](#reprocessbriefinground) | POST | /api/v1/admin/briefings/{round_id}/reprocess | 관리자(작업별 권한) | P1 |
| [appendBriefingCorrection](#appendbriefingcorrection) | POST | /api/v1/admin/briefings/{round_id}/corrections | 관리자(작업별 권한) | P1 |
| [setBriefingSuspension](#setbriefingsuspension) | POST | /api/v1/admin/briefings/{round_id}/suspension | 관리자(작업별 권한) | P1 |
| [recordInteractionEvents](#recordinteractionevents) | POST | /api/v1/telemetry | 회원 또는 비회원 세션 | P2 |
| [getMyFeedback](#getmyfeedback) | GET | /api/v1/feedback | 회원(본인) | P2 |
| [setFeedback](#setfeedback) | PUT | /api/v1/feedback | 회원(본인) | P2 |
| [getInsightsOverview](#getinsightsoverview) | GET | /api/v1/admin/insights/overview | 관리자(작업별 권한) | P2 |
| [getInsightsSummary](#getinsightssummary) | GET | /api/v1/admin/insights/summary | 관리자(작업별 권한) | P2 |
| [listCompanyInsights](#listcompanyinsights) | GET | /api/v1/admin/insights/companies | 관리자(작업별 권한) | P2 |
| [getCompanyInsights](#getcompanyinsights) | GET | /api/v1/admin/insights/companies/{company_id} | 관리자(작업별 권한) | P2 |
| [getFeedbackSummary](#getfeedbacksummary) | GET | /api/v1/admin/feedback/summary | 관리자(작업별 권한) | P2 |
| [listDislikedResults](#listdislikedresults) | GET | /api/v1/admin/feedback/dislikes | 관리자(작업별 권한) | P2 |
| [listMaskedTranscripts](#listmaskedtranscripts) | GET | /api/v1/admin/transcripts | 관리자 + transcript:read + 열람 목적 | P2 |
| [getMaskedTranscript](#getmaskedtranscript) | GET | /api/v1/admin/transcripts/{session_id} | 관리자 + transcript:read + 열람 목적 | P2 |
| [listMembers](#listmembers) | GET | /api/v1/admin/members | 관리자(작업별 권한) | P2 |
| [getMemberActivity](#getmemberactivity) | GET | /api/v1/admin/members/{member_id} | 관리자(작업별 권한) | P2 |
| [blockMember](#blockmember) | POST | /api/v1/admin/members/{member_id}/block | 관리자(작업별 권한) | P2 |
| [unblockMember](#unblockmember) | POST | /api/v1/admin/members/{member_id}/unblock | 관리자(작업별 권한) | P2 |
| [getCompanyFinancials](#getcompanyfinancials) | GET | /api/v1/companies/{id}/financials | 공개 | P1 |
| [getCompanyIssueImpact](#getcompanyissueimpact) | GET | /api/v1/companies/{id}/issues/{issueId}/impact | 공개 | P1 |
| [getPersonalizedBriefing](#getpersonalizedbriefing) | GET | /api/v1/briefings/{id}/personalized | 회원(본인) | P2 |
| [getCompanyGraphAsOf](#getcompanygraphasof) | GET | /api/v1/companies/{id}/graph | 공개 | P1 |

<a id="getmembersession"></a>

## getMemberSession · 회원 세션과 초기 설정 조회

회원 세션과 초기 설정 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/auth/session` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [SessionResponse](#schema-sessionresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR |
| FS/NFS | [FS001](../../system/out/feature-FS001.md) · [FS006](../../system/out/feature-FS006.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-AUT-01](../../system/out/screen-D-AUT-01.md) · [D-ONB-01](../../system/out/screen-D-ONB-01.md) |
| WBS | 6.1.2, 6.11.1, 6.2.4, 6.2.6, 6.2.7 |
| 프로토타입 대응 | /api/auth/session |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="listterms"></a>

## listTerms · 가입 약관 조회

가입 약관 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/auth/terms` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [TermsResponse](#schema-termsresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, INVALID_CURSOR |
| FS/NFS | [FS003](../../system/out/feature-FS003.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-AUT-02](../../system/out/screen-D-AUT-02.md) |
| WBS | 6.1.2, 6.11.1, 6.2.1, 6.2.7 |
| 프로토타입 대응 | /api/auth/terms |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 반복 실패 제한·가입 필드·비밀번호 정책·약관 본문과 버전을 팀이 확정해야 한다. 가입 직후 세션 생성은 현재 BFF 출발점이며 정식 정책 확인이 필요하다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="signup"></a>

## signUp · 이메일 회원가입

이메일 회원가입.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/auth/signup` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | [SignupRequest](#schema-signuprequest) |
| 응답 | 201: [SessionResponse](#schema-sessionresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, EMAIL_TAKEN, TERMS_REQUIRED |
| FS/NFS | [FS003](../../system/out/feature-FS003.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-AUT-02](../../system/out/screen-D-AUT-02.md) |
| WBS | 6.1.2, 6.11.1, 6.2.1, 6.2.7 |
| 프로토타입 대응 | /api/auth/signup |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| 팀 확인 필요 | 반복 실패 제한·가입 필드·비밀번호 정책·약관 본문과 버전을 팀이 확정해야 한다. 가입 직후 세션 생성은 현재 BFF 출발점이며 정식 정책 확인이 필요하다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

본문 스키마: [SignupRequest](#schema-signuprequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="login"></a>

## logIn · 이메일 로그인

이메일 로그인.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/auth/login` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | [LoginRequest](#schema-loginrequest) |
| 응답 | 200: [SessionResponse](#schema-sessionresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, INVALID_CREDENTIALS, MEMBER_BLOCKED |
| FS/NFS | [FS002](../../system/out/feature-FS002.md) · [FS006](../../system/out/feature-FS006.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-AUT-01](../../system/out/screen-D-AUT-01.md) |
| WBS | 6.1.2, 6.11.1, 6.2.1, 6.2.4, 6.2.6, 6.2.7 |
| 프로토타입 대응 | /api/auth/login |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| 팀 확인 필요 | 반복 실패 제한·가입 필드·비밀번호 정책·약관 본문과 버전을 팀이 확정해야 한다. 가입 직후 세션 생성은 현재 BFF 출발점이며 정식 정책 확인이 필요하다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

본문 스키마: [LoginRequest](#schema-loginrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="startguestsession"></a>

## startGuestSession · 비회원 시작

비회원 시작.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/auth/guest` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [SessionResponse](#schema-sessionresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS005](../../system/out/feature-FS005.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-AUT-01](../../system/out/screen-D-AUT-01.md) · [M-GRP-01](../../system/out/screen-M-GRP-01.md) |
| WBS | 6.1.2, 6.11.1, 6.2.3, 6.2.6 |
| 프로토타입 대응 | /api/auth/guest |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="logout"></a>

## logOut · 회원 로그아웃

회원 로그아웃은 자연 멱등 세션 폐기이며 Idempotency-Key를 요구하지 않는다. 활성 zoop_session이 있으면 동일 쿠키·Origin·세션 결합 X-CSRF-Token을 반드시 검증하고 해당 세션만 폐기한다. Origin/CSRF 실패는 403 ACCESS_DENIED이며 무세션 분기로 우회하지 않는다. 세션 없음·무효·만료이면 다른 세션을 변경하지 않고 204를 반환한다. zoop_session 쿠키만 제거하며 관리자 세션/쿠키에는 영향을 주지 않는다. 선택 인증·선택 헤더 표기는 조건부 런타임 검증을 자동 강제하지 않는다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/auth/logout` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 204: 본문 없음, 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, ACCESS_DENIED, RATE_LIMITED |
| FS/NFS | [FS007](../../system/out/feature-FS007.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-MY-01](../../system/out/screen-D-MY-01.md) |
| WBS | 6.1.2, 6.11.1, 6.2.5 |
| 프로토타입 대응 | /api/auth/logout |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다., 목표는 활성 회원 세션의 Origin/조건부 CSRF 검증, 무세션 반복204 및 회원/관리자 쿠키 분리를 요구한다. 현재 BFF의 목표 보안 구현 완료를 뜻하지 않는다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 선택 | string | 활성 zoop_session이 있으면 필수이며 해당 세션에 결합된 토큰이어야 한다. 누락/불일치는 403 ACCESS_DENIED이고 무세션 분기로 우회하지 않는다. 세션 없음·무효·만료이면 필요하지 않다. Origin도 검증한다. |

<a id="settutorialstate"></a>

## setTutorialState · 튜토리얼 진행 결과 저장

튜토리얼 진행 결과 저장.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `PUT /api/v1/auth/tutorial` |
| 권한·우선순위 | 회원 또는 비회원 세션 · P1 |
| 요청 본문 | [TutorialUpdate](#schema-tutorialupdate) |
| 응답 | 200: [SessionResponse](#schema-sessionresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS015](../../system/out/feature-FS015.md) · [FS016](../../system/out/feature-FS016.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-GRP-T](../../system/out/screen-D-GRP-T.md) · [D-GRP-T2](../../system/out/screen-D-GRP-T2.md) · [D-GRP-T3](../../system/out/screen-D-GRP-T3.md) · [D-GRP-T4](../../system/out/screen-D-GRP-T4.md) · [D-GRP-T5](../../system/out/screen-D-GRP-T5.md) |
| WBS | 6.1.2, 6.11.1, 6.3.7, 6.3.10 |
| 프로토타입 대응 | /api/auth/tutorial |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |

본문 스키마: [TutorialUpdate](#schema-tutorialupdate). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="listsocialproviders"></a>

## listSocialProviders · 소셜 인증 제공자 조회

회원 소셜 인증 제공자는 google과 kakao다. 커서 전체를 순회한 결과에 두 제공자가 ID별로 한 번씩 포함되며 개별 페이지에는 limit에 맞는 일부만 있을 수 있다. 관리자 SSO 선택과 실제 OAuth 연동 완료를 뜻하지 않는다. 공통 인증·페이지 규칙을 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/auth/social/providers` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [SocialProvidersResponse](#schema-socialprovidersresponse), 400: [ErrorResponse](#schema-errorresponse), 401: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, INVALID_CURSOR, SOCIAL_AUTH_CANCELLED, SOCIAL_AUTH_FAILED |
| FS/NFS | [FS004](../../system/out/feature-FS004.md) · [FS061](../../system/out/feature-FS061.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-AUT-01](../../system/out/screen-D-AUT-01.md) |
| WBS | 6.1.2, 6.11.1, 6.2.2 |
| 프로토타입 대응 | /api/auth/social/providers |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 회원 제공자는 Google/카카오로 채택한다. 실제 OAuth 등록·연동, 기존 계정 본인/연결권한 확인 정책은 별도이며 관리자 SSO·권한 등급/회수 정책은 미정이다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="authorizesociallogin"></a>

## authorizeSocialLogin · 소셜 인증 시작

google 또는 kakao 회원 소셜 인증을 시작한다. 지원하지 않는 provider는 거절한다. 공통 Origin/state·허용 복귀 경로 검증과 기존 계정 연결 권한 확인을 유지한다. 실제 OAuth 등록·연동 완료는 별도다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/auth/social/{provider}/authorize` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 302: 본문 없음, 400: [ErrorResponse](#schema-errorresponse), 401: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, SOCIAL_AUTH_CANCELLED, SOCIAL_AUTH_FAILED |
| FS/NFS | [FS004](../../system/out/feature-FS004.md) · [FS061](../../system/out/feature-FS061.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-AUT-01](../../system/out/screen-D-AUT-01.md) |
| WBS | 6.1.2, 6.11.1, 6.2.2 |
| 프로토타입 대응 | /api/auth/social/{provider}/authorize |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| 팀 확인 필요 | 회원 제공자는 Google/카카오로 채택한다. 실제 OAuth 등록·연동, 기존 계정 본인/연결권한 확인 정책은 별도이며 관리자 SSO·권한 등급/회수 정책은 미정이다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| provider | path | 필수 | string {google, kakao} |  |
| returnTo | query | 선택 | string / null |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="completesociallogin"></a>

## completeSocialLogin · 소셜 인증 콜백

google 또는 kakao 회원 소셜 인증 콜백을 처리한다. 지원하지 않는 provider와 유효하지 않은 state는 거절한다. 공통 Origin/state·허용 복귀 경로 검증과 기존 계정 본인/연결권한 확인 없이 계정 연결을 완료하지 않는 보안 경계를 유지한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/auth/social/{provider}/callback` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 302: 본문 없음, 400: [ErrorResponse](#schema-errorresponse), 401: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, SOCIAL_AUTH_CANCELLED, SOCIAL_AUTH_FAILED |
| FS/NFS | [FS004](../../system/out/feature-FS004.md) · [FS061](../../system/out/feature-FS061.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-AUT-01](../../system/out/screen-D-AUT-01.md) |
| WBS | 6.1.2, 6.11.1, 6.2.2 |
| 프로토타입 대응 | /api/auth/social/{provider}/callback |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| 팀 확인 필요 | 회원 제공자는 Google/카카오로 채택한다. 실제 OAuth 등록·연동, 기존 계정 본인/연결권한 확인 정책은 별도이며 관리자 SSO·권한 등급/회수 정책은 미정이다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| provider | path | 필수 | string {google, kakao} |  |
| state | query | 선택 | string / null |  |
| code | query | 선택 | string / null |  |
| error | query | 선택 | string / null |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="getmysettings"></a>

## getMySettings · 회원 설정 조회

회원 설정 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/me/settings` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [SettingsResponse](#schema-settingsresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS008](../../system/out/feature-FS008.md) · [FS012](../../system/out/feature-FS012.md) · [FS013](../../system/out/feature-FS013.md) · [FS054](../../system/out/feature-FS054.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-ONB-01](../../system/out/screen-D-ONB-01.md) · [D-WAT-01](../../system/out/screen-D-WAT-01.md) · [D-MY-01](../../system/out/screen-D-MY-01.md) |
| WBS | 6.1.2, 6.11.1, 6.3.1, 6.3.4, 6.3.5, 6.3.8, 6.4.1, 6.4.3, 6.4.5, 6.4.6 |
| 프로토타입 대응 | /api/me/settings |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="updatemysettings"></a>

## updateMySettings · 초기 설정과 관심 종목 저장

초기 설정과 관심 종목 저장.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `PUT /api/v1/me/settings` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | [SettingsUpdate](#schema-settingsupdate) |
| 응답 | 200: [SettingsResponse](#schema-settingsresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS008](../../system/out/feature-FS008.md) · [FS010](../../system/out/feature-FS010.md) · [FS012](../../system/out/feature-FS012.md) · [FS013](../../system/out/feature-FS013.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-ONB-01](../../system/out/screen-D-ONB-01.md) · [D-ONB-02](../../system/out/screen-D-ONB-02.md) · [D-WAT-01](../../system/out/screen-D-WAT-01.md) · [D-WAT-01b](../../system/out/screen-D-WAT-01b.md) |
| WBS | 6.1.2, 6.11.1, 6.3.1, 6.3.2, 6.3.4, 6.3.5, 6.3.8, 6.3.9, 6.4.5 |
| 프로토타입 대응 | /api/me/settings |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |

본문 스키마: [SettingsUpdate](#schema-settingsupdate). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="setwatchlistcompany"></a>

## setWatchlistCompany · 관심 종목 목표 상태 설정

관심 종목 목표 상태 설정.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `PUT /api/v1/me/watchlist/{id}` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | [WatchUpdate](#schema-watchupdate) |
| 응답 | 200: [SettingsResponse](#schema-settingsresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS027](../../system/out/feature-FS027.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-MY-01](../../system/out/screen-D-MY-01.md) · [D-GRP-03](../../system/out/screen-D-GRP-03.md) · [D-STK-01](../../system/out/screen-D-STK-01.md) · [M-STK-01](../../system/out/screen-M-STK-01.md) |
| WBS | 6.1.2, 6.11.1, 6.4.1, 6.4.2, 6.4.6, 6.4.7, 6.6.12, 6.6.23 |
| 프로토타입 대응 | /api/me/watchlist/{id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |

본문 스키마: [WatchUpdate](#schema-watchupdate). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="listrecommendations"></a>

## listRecommendations · 추천 종목·산업·테마 조회

추천 종목·산업·테마 조회. 2026-10-10 사용자 결정으로 활성 사용자 기능·여정·수용 범위에서 제외했고 이 계약은 이후 다시 반환할 수 있도록 유보한다. 삭제·무동작·가짜 응답으로 바꾸지 않으며 현재 BFF는 기존 동작(승인 이슈 수 기준 기업 순위)을 그대로 제공한다. 제외는 활성 사용 허용이 아니다. 공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/me/recommendations` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [RecommendationResponse](#schema-recommendationresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS011-02](../../system/out/feature-FS011-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 |  |
| WBS | 6.1.2, 6.11.1, 6.3.3, 6.4.5 |
| 프로토타입 대응 | /api/me/recommendations |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다., 추천 종목·산업·테마는 활성 사용자 기능에서 제외됐다. 작업은 삭제하지 않고 현재 BFF 동작을 유지한다. 산업·테마 추천의 생산자는 BFF에 없다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

기능 상태: `excluded-user-facing-endpoint-retained` · user-2026-10-10-feedback · FS011-02는 활성 기능에서 제외하고 이 목표 작업은 유보한다. 현재 활성 화면은 이 작업을 호출하지 않으므로 screenIds는 비어 있다. formerScreenIds는 과거 연결의 이력일 뿐 현행 화면→API 추적이 아니다.

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="listvirtualaccountprofiles"></a>

## listVirtualAccountProfiles · 가상 계좌 프로필 목록

가상 계좌 프로필 목록.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/portfolio/mock-portfolios` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [MockPortfolioListResponse](#schema-mockportfoliolistresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS009](../../system/out/feature-FS009.md) · [FS062](../../system/out/feature-FS062.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-ONB-02](../../system/out/screen-D-ONB-02.md) |
| WBS | 6.1.2, 6.11.1, 6.3.2, 6.3.9, 6.4.4, 6.4.6 |
| 프로토타입 대응 | /api/portfolio/mock-portfolios |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="getvirtualaccountprofile"></a>

## getVirtualAccountProfile · 가상 계좌 프로필 조회

가상 계좌 프로필 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/portfolio/mock-portfolios/{id}` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [MockProfileResponse](#schema-mockprofileresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS009](../../system/out/feature-FS009.md) · [FS062](../../system/out/feature-FS062.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-ONB-02](../../system/out/screen-D-ONB-02.md) |
| WBS | 6.1.2, 6.11.1, 6.3.2, 6.3.9, 6.4.4, 6.4.6 |
| 프로토타입 대응 | /api/portfolio/mock-portfolios/{id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="connectvirtualaccount"></a>

## connectVirtualAccount · 가상 계좌 연결

가상 계좌 연결.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/portfolio/connections` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | [PortfolioConnectRequest](#schema-portfolioconnectrequest) |
| 응답 | 201: [ConnectionResponse](#schema-connectionresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS009](../../system/out/feature-FS009.md) · [FS010](../../system/out/feature-FS010.md) · [FS062](../../system/out/feature-FS062.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-ONB-02](../../system/out/screen-D-ONB-02.md) |
| WBS | 6.1.2, 6.11.1, 6.3.2, 6.3.9, 6.4.4, 6.4.6 |
| 프로토타입 대응 | /api/portfolio/connections |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [PortfolioConnectRequest](#schema-portfolioconnectrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="getmyportfolio"></a>

## getMyPortfolio · 모의 보유 정보 조회

모의 보유 정보 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/portfolio` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [PortfolioResponse](#schema-portfolioresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS039](../../system/out/feature-FS039.md) · [FS054](../../system/out/feature-FS054.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-COM-01](../../system/out/screen-D-COM-01.md) · [D-MY-01](../../system/out/screen-D-MY-01.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) |
| WBS | 6.1.2, 6.11.1, 6.4.1, 6.4.3, 6.4.6, 6.7.8 |
| 프로토타입 대응 | /api/portfolio |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="disconnectvirtualaccount"></a>

## disconnectVirtualAccount · 가상 계좌 연결 해제

가상 계좌 연결 해제.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `DELETE /api/v1/portfolio/connections/{id}` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 204: 본문 없음, 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS009](../../system/out/feature-FS009.md) · [FS062](../../system/out/feature-FS062.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-MY-01](../../system/out/screen-D-MY-01.md) |
| WBS | 6.1.2, 6.11.1, 6.3.2, 6.3.9, 6.4.4, 6.4.6 |
| 프로토타입 대응 | /api/portfolio/connections/{id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |

<a id="getgraph"></a>

## getGraph · 전체·개인화·시점별 관계 그래프 조회

기업/이슈 노드만 제공한다. 전체 모드에는 개인 정보가 없고 개인화 모드는 회원 본인만 허용한다. 필터 결과의 기준 기업은 관계 0건이어도 유지한다. 국내/국제 속성이 없는 이슈는 공개 검증에서 제외/보완하며 임의로 값을 만들지 않는다. asOf/graphVersion/round를 고정하고 관계 0건·기준 기업 0개·장애를 구분한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/graph` |
| 권한·우선순위 | 공개(all) / 회원 본인(personal) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [GraphResponse](#schema-graphresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, VERSION_UNAVAILABLE, EVIDENCE_UNAVAILABLE, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS014](../../system/out/feature-FS014.md) · [FS017](../../system/out/feature-FS017.md) · [FS018](../../system/out/feature-FS018.md) · [FS019](../../system/out/feature-FS019.md) · [FS026](../../system/out/feature-FS026.md) · [FS032](../../system/out/feature-FS032.md) · [FS040](../../system/out/feature-FS040.md) · [FS044](../../system/out/feature-FS044.md) · [FS055](../../system/out/feature-FS055.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-GRP-01](../../system/out/screen-D-GRP-01.md) · [D-GRP-01b](../../system/out/screen-D-GRP-01b.md) · [D-GRP-07](../../system/out/screen-D-GRP-07.md) · [D-GRP-07b](../../system/out/screen-D-GRP-07b.md) · [D-BRF-04](../../system/out/screen-D-BRF-04.md) · [M-GRP-01](../../system/out/screen-M-GRP-01.md) · [D-COM-04](../../system/out/screen-D-COM-04.md) |
| WBS | 6.1.2, 6.11.1, 6.3.6, 6.4.7, 6.6.1, 6.6.2, 6.6.3, 6.6.11, 6.6.21, 6.6.23, 6.7.3, 6.7.7, 6.7.8, 6.7.10, 6.7.11, 6.7.12, 6.8.5, 6.8.14, 6.5.1 |
| 프로토타입 대응 | /api/graph |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF의 개인화 범위 필터는 화면 처리다. 목표는 personalFilter·asOf·graphVersion과 검증된 국내/국제 속성을 서버에서 제공한다. |
| 팀 확인 필요 | 메인그래프 v2(04 시트)가 현행 상세이고 옛 메인 그래프 탭(03)은 이력으로 보존한다. 목차 FS019~027의 상세 위치(range)와 v2 시트의 실제 구획 행 불일치는 명세 담당자가 정정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| mode | query | 선택 | string {all, personal} |  |
| companyId | query | 선택 | string / null |  |
| depth | query | 선택 | integer / null | Hops from the focus; omit for the whole connected component. |
| round | query | 선택 | string / null | Briefing round id (e.g. brf-2026-09-17-morning): read the graph as it stood when that round was published. Never falls back to the newest graph; see GET /api/v1/briefings/{id}/graph. |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |
| personalFilter | query | 선택 | string {all, holdings, watchlist} | 개인화 모드의 기준 기업 범위. 전체 모드에서는 적용하지 않는다. |

<a id="getcompanyrelation"></a>

## getCompanyRelation · 기업 간 관계와 근거 조회

기업 간 관계만 선택 가능한 조회다. 이슈–기업 간선은 직접 클릭 대상으로 사용하지 않는다. 단지 같은 이슈를 공유하는 파생 관계는 실제 공급/고객 관계로 표현하지 않는다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/graph/edges/{id}` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [EdgeDetail](#schema-edgedetail), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, VERSION_UNAVAILABLE, EVIDENCE_UNAVAILABLE |
| FS/NFS | [FS023](../../system/out/feature-FS023.md) · [FS024](../../system/out/feature-FS024.md) · [FS055](../../system/out/feature-FS055.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-GRP-04](../../system/out/screen-D-GRP-04.md) |
| WBS | 6.1.2, 6.11.1, 6.6.8, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.5.1 |
| 프로토타입 대응 | /api/graph/edges/{id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| round | query | 선택 | string / null | Briefing round id (e.g. brf-2026-09-17-morning): read the graph as it stood when that round was published. Never falls back to the newest graph; see GET /api/v1/briefings/{id}/graph. |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |

<a id="searchcompanies"></a>

## searchCompanies · 기업 목록과 명시적 검색

기업 목록과 명시적 검색.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/companies` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [CompanyListResponse](#schema-companylistresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, INVALID_CURSOR |
| FS/NFS | [FS011-01](../../system/out/feature-FS011-01.md) · [FS026](../../system/out/feature-FS026.md) · [FS037](../../system/out/feature-FS037.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-WAT-01](../../system/out/screen-D-WAT-01.md) · [D-MY-01](../../system/out/screen-D-MY-01.md) · [D-COM-01](../../system/out/screen-D-COM-01.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) · [D-STK-01](../../system/out/screen-D-STK-01.md) · [M-STK-01](../../system/out/screen-M-STK-01.md) · [D-COM-03](../../system/out/screen-D-COM-03.md) · [M-COM-02](../../system/out/screen-M-COM-02.md) |
| WBS | 6.1.2, 6.11.1, 6.3.3, 6.4.5, 6.4.7, 6.6.11, 6.6.21, 6.6.23, 6.7.1 |
| 프로토타입 대응 | /api/companies |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| q | query | 선택 | string / null | Name, alias, ticker or id; empty lists every company by name |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |

<a id="getcompany"></a>

## getCompany · 기업 기본 정보·관계·요약 조회

기업 기본 정보·관계·요약을 조회한다. 표시용 name과 정식 법인명 legalName을 구분한다. legalName·market·sector·representative·foundedDate·websiteUrl 여섯 프로필 키는 항상 반환하고 확인되지 않은 값은 null이다. 공식 기업 마스터 자료를 확보하기 전 표시명 복사·날짜/URL 추정·빈 문자열로 보충하지 않는다. 관계/요약의 공개 시점과 기업 마스터의 자료 시점은 별개다. 공통 규칙을 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/companies/{id}` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [CompanyDetail](#schema-companydetail), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, VERSION_UNAVAILABLE |
| FS/NFS | [FS020](../../system/out/feature-FS020.md) · [FS038](../../system/out/feature-FS038.md) · [FS044](../../system/out/feature-FS044.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-GRP-03](../../system/out/screen-D-GRP-03.md) · [D-COM-01](../../system/out/screen-D-COM-01.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) · [D-COM-03](../../system/out/screen-D-COM-03.md) · [D-COM-04](../../system/out/screen-D-COM-04.md) · [M-COM-02](../../system/out/screen-M-COM-02.md) |
| WBS | 6.1.2, 6.11.1, 6.6.4, 6.6.23, 6.6.26, 6.7.2, 6.7.7, 6.7.8, 6.7.10, 6.7.11, 6.7.12 |
| 프로토타입 대응 | /api/companies/{id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표의 필수 nullable 프로필 legalName/market/representative/foundedDate/websiteUrl은 현재 BFF CompanyDetail에 없다. sector는 기존 필드를 유지한다. 공식 기업 마스터 공급원·자료 기준 확인과 DTO 이행이 필요하다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| round | query | 선택 | string / null | Briefing round id (e.g. brf-2026-09-17-morning): read the graph as it stood when that round was published. Never falls back to the newest graph; see GET /api/v1/briefings/{id}/graph. |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |

<a id="getcompanyquote"></a>

## getCompanyQuote · 기업 시세 조회

차트 기간·조회 asOf·graphVersion과 독립적으로 공급자가 가장 최근 제공한 기업 시세를 조회한다. latest는 실시간·당일 보장이 아니다. 요청에 asOf/graphVersion이 제공되면 422 INVALID_REQUEST로 거절하며 역사 조회처럼 보이는 요청을 조용히 최신값으로 처리하지 않는다. quote.asOf는 공급자의 가격 관측시각 또는 null을 유지한다. 출처·가격 종류·통화·단위·지연을 보존하고 과거 차트값을 최신 시세로 대신하지 않는다. 활성 그래프 부재만으로 VERSION_UNAVAILABLE을 반환하지 않는다. 정상 자료 부재는 200 unavailable이고 공급자 인증·네트워크·형식 장애는 503 SOURCE_UNAVAILABLE이며 retryable은 원인에 맞춘다. 공통 오류·요청 ID 규칙을 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/companies/{id}/quote` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [CompanyQuote](#schema-companyquote) / [CompanyQuoteUnavailable](#schema-companyquoteunavailable), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR |
| FS/NFS | [FS020](../../system/out/feature-FS020.md) · [FS038](../../system/out/feature-FS038.md) · [FS063](../../system/out/feature-FS063.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-GRP-03](../../system/out/screen-D-GRP-03.md) · [D-COM-01](../../system/out/screen-D-COM-01.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) · [D-STK-01](../../system/out/screen-D-STK-01.md) · [M-STK-01](../../system/out/screen-M-STK-01.md) · [D-COM-03](../../system/out/screen-D-COM-03.md) · [M-COM-02](../../system/out/screen-M-COM-02.md) |
| WBS | 6.1.2, 6.11.1, 6.6.4, 6.6.23, 6.6.26, 6.7.2, 6.7.8, 6.7.10, 6.7.11, 6.5.6 |
| 프로토타입 대응 | /api/companies/{id}/quote |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표의 최신 시세는 차트/타임라인 및 공개 그래프 선택과 독립적이다. 현재 BFF의 기업 존재 확인·출처 조회와 그래프 상태 의존 여부를 별도로 확인하고 공급자 관측시각을 보존해야 한다., 목표는 asOf/graphVersion 전달을 422 INVALID_REQUEST로 거절하고 정상 자료 부재200(not_connected/unsupported_symbol/no_data)과 실제 공급자 장애503 SOURCE_UNAVAILABLE을 구분하며 quote.asOf는 공급자 관측시각 또는 null을 유지한다. 10-10 로컬 BFF는 같은 경계를 구현했다(가짜 공급자 HTTP 40건 정확성 스모크, 성능 시험 아님). 남은 차이는 기존 소문자 snake_case 오류 코드(source_unavailable/validation_error)와 details.retryable·requestId 위치이며 저장된 BFF OpenAPI 관측본은 아직 갱신하지 않았다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="getcompanymetrics"></a>

## getCompanyMetrics · 기업 주요 지표 조회

기업 주요 지표 조회. 공급자가 제공한 값과 기준 시각만 반환하며 시세·재무 수치를 추정·0으로 대체하지 않는다. 정상 자료 부재(not_connected/unsupported_symbol/no_data)는 200 unavailable이고 공급자 인증·네트워크·timeout/429/5xx·형식 장애는 503 SOURCE_UNAVAILABLE이다. retryable은 일시 장애에만 true다. 공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/companies/{id}/metrics` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [CompanyMetrics](#schema-companymetrics) / [CompanyMetricsUnavailable](#schema-companymetricsunavailable), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR |
| FS/NFS | [FS020](../../system/out/feature-FS020.md) · [FS038](../../system/out/feature-FS038.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-GRP-03](../../system/out/screen-D-GRP-03.md) · [D-COM-01](../../system/out/screen-D-COM-01.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) |
| WBS | 6.1.2, 6.11.1, 6.6.4, 6.6.23, 6.7.2, 6.7.10 |
| 프로토타입 대응 | /api/companies/{id}/metrics |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 정상 자료 부재 200 unavailable의 reasonCode를 not_connected/unsupported_symbol/no_data로 제한하고 공급자 인증·네트워크·형식 장애는 503 SOURCE_UNAVAILABLE로 구분한다. status 값(available/unavailable)은 변경하지 않는다. 10-10 로컬 BFF는 부분 지표를 있는 값만 반환하고 값이 없으면 200 no_data, 읽을 수 없는 응답은 503으로 구분한다. 남은 차이는 기존 소문자 snake_case 오류 코드와 details.retryable·requestId 위치이며 저장된 BFF OpenAPI 관측본은 아직 갱신하지 않았다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |

<a id="getcompanyprices"></a>

## getCompanyPrices · 기간별 가격 차트 조회

기간별 가격 차트 조회. period는 1d/1w/1m/1y이며 봉 해상도는 기간별로 고정한다: 1d=5m, 1w=1h, 1m=1d, 1y=1wk(주봉). 공급자가 해당 해상도를 제공하지 않으면 다른 해상도의 값을 이름만 바꾸거나 집계·보간해 채우지 않고 200 unavailable(no_data)로 정상 자료 부재를 표현한다. 공급자 인증·네트워크·형식 장애는 503 SOURCE_UNAVAILABLE이며 retryable은 일시 장애에만 true다. 공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/companies/{id}/prices` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [PriceSeries](#schema-priceseries) / [PriceSeriesUnavailable](#schema-priceseriesunavailable), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR |
| FS/NFS | [FS038](../../system/out/feature-FS038.md) · [FS040](../../system/out/feature-FS040.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-COM-01b](../../system/out/screen-D-COM-01b.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) · [D-COM-05](../../system/out/screen-D-COM-05.md) · [D-COM-06](../../system/out/screen-D-COM-06.md) |
| WBS | 6.1.2, 6.11.1, 6.7.2, 6.7.3, 6.7.8, 6.7.10, 6.7.11, 6.7.12 |
| 프로토타입 대응 | /api/companies/{id}/prices |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 기간별 봉 해상도를 1d=5m, 1w=1h, 1m=1d, 1y=1wk로 고정하고 해상도를 제공하지 못하면 가짜 봉 없이 200 unavailable(no_data)로 표현한다. 정상 자료 부재 reasonCode는 3개로 제한하고 공급자 장애는 503 SOURCE_UNAVAILABLE로 구분한다. 10-10 로컬 BFF는 Yahoo 가짜 공급자에서 5m/1h/1d/1wk를 확인했고 Toss 1d/1w는 5분·시간 봉이 없어 200 no_data로 둔다. 남은 차이는 기존 소문자 snake_case 오류 코드와 details.retryable·requestId 위치이며 저장된 BFF OpenAPI 관측본은 아직 갱신하지 않았다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| period | query | 선택 | string {1d, 1w, 1m, 1y} |  |
| from | query | 선택 | string (date) / string (date-time) | KST 날짜 또는 오프셋을 포함한 정확한 시각. from/to는 동일 기준을 사용한다. |
| to | query | 선택 | string (date) / string (date-time) | KST 날짜 또는 오프셋을 포함한 정확한 시각. from/to는 동일 기준을 사용한다. |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |

<a id="listcompanydocuments"></a>

## listCompanyDocuments · 기업 맥락 뉴스·공시와 긍부정 조회

기업 맥락 뉴스·공시와 긍부정 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/companies/{id}/documents` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [CompanyDocumentsResponse](#schema-companydocumentsresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, INVALID_CURSOR |
| FS/NFS | [FS021](../../system/out/feature-FS021.md) · [FS043](../../system/out/feature-FS043.md) · [FS056](../../system/out/feature-FS056.md) · [FS063](../../system/out/feature-FS063.md) · [FS064](../../system/out/feature-FS064.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS006](../../system/out/feature-NFS006.md) |
| 화면 | [D-COM-02](../../system/out/screen-D-COM-02.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) · [D-SEN-01](../../system/out/screen-D-SEN-01.md) |
| WBS | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.6, 6.7.9, 6.5.2, 6.5.6, 6.5.7 |
| 프로토타입 대응 | /api/companies/{id}/documents |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 긍정/부정 명칭은 사용자 결정 완료이며 혼재/판단 보류도 유지한다. 모델·추론 수준은 .env 설정, 예산/실행 승인·재판정/운영 정책·이슈 수준 종합 방향과 퍼센트 충돌은 별도 팀 최종 결정 대상이다. 실제 판정 없으면 null을 반환한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |
| kind | query | 선택 | string {news, disclosure} |  |
| round | query | 선택 | string | 브리핑 회차 ID. 회차의 문서와 기업별 긍부정 발행본을 함께 고정한다. |
| from | query | 선택 | string (date) / string (date-time) | 차트·타임라인과 같은 조회 시작 조건. 날짜 또는 오프셋을 포함한 시각이다. |
| to | query | 선택 | string (date) / string (date-time) | 같은 조회 종료 조건이며 이 시각 이후 공개된 문서는 제외한다. |

<a id="listevents"></a>

## listEvents · 기업·기간별 사건 타임라인 조회

기업·기간·탐색 깊이에 맞는 사건 타임라인을 조회한다. depth는 기업 시점별 관계 그래프와 같은 1-hop/2-hop 범위로 적용하여 지도에서 고른 간접 사건도 해당 타임라인 카드로 연결되게 한다. from/to·asOf·graphVersion은 조회 조건과 공개 자료 기준을 고정하며 미래 공개 문서를 섞지 않는다. items와 unknownTimeItems의 relationTypes는 같은 공개 버전/asOf에서 요청 companyId와 각 사건 사이의 직접 승인 간선 INVOLVES/STRUCTURALLY_RELATED_TO만 중복 없이 반환한다. companyId가 없거나 직접 간선이 없으면 []이며 2-hop으로만 도달한 사건도 []다. 다른 회사의 간선, 감성·공급/경쟁 관계를 대신 넣지 않는다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/events` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [EventListResponse](#schema-eventlistresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, INVALID_CURSOR, VERSION_UNAVAILABLE |
| FS/NFS | [FS040](../../system/out/feature-FS040.md) · [FS041](../../system/out/feature-FS041.md) · [FS056](../../system/out/feature-FS056.md) · [FS055](../../system/out/feature-FS055.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-COM-01b](../../system/out/screen-D-COM-01b.md) · [D-COM-02](../../system/out/screen-D-COM-02.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) · [D-COM-05](../../system/out/screen-D-COM-05.md) · [D-COM-06](../../system/out/screen-D-COM-06.md) |
| WBS | 6.1.2, 6.11.1, 6.7.3, 6.7.4, 6.7.8, 6.7.11, 6.7.12, 6.5.2, 6.5.1 |
| 프로토타입 대응 | /api/events |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다., 현재 BFF EventSummary에는 요청 companyId 맥락의 relationTypes가 없다. items/unknownTimeItems 양쪽을 같은 승인 간선·공개 버전/asOf로 변환해야 하며 간접 2-hop을 직접 관계로 승격하지 않는다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| companyId | query | 선택 | string / null |  |
| depth | query | 선택 | integer {1, 2} | 기업 상세 관계 그래프와 같은 탐색 깊이. 회사 맥락이 없는 전체 사건 조회에는 적용하지 않는다. 명세의 허용 범위는 1-hop 또는 2-hop이다. |
| from | query | 선택 | string (date) / string (date-time) | KST 날짜 또는 오프셋을 포함한 정확한 시각. from/to는 동일 기준을 사용한다. |
| to | query | 선택 | string (date) / string (date-time) | KST 날짜 또는 오프셋을 포함한 정확한 시각. from/to는 동일 기준을 사용한다. |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |

<a id="getevent"></a>

## getEvent · 사건 상세와 근거 참조 조회

사건 상세와 근거 참조 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/events/{id}` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [EventDetail](#schema-eventdetail), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, VERSION_UNAVAILABLE, EVIDENCE_UNAVAILABLE |
| FS/NFS | [FS021](../../system/out/feature-FS021.md) · [FS041](../../system/out/feature-FS041.md) · [FS056](../../system/out/feature-FS056.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-GRP-02](../../system/out/screen-D-GRP-02.md) · [D-COM-02](../../system/out/screen-D-COM-02.md) · [D-COM-05](../../system/out/screen-D-COM-05.md) |
| WBS | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.4, 6.7.8, 6.7.12, 6.5.2 |
| 프로토타입 대응 | /api/events/{id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 긍정/부정 명칭은 사용자 결정 완료이며 혼재/판단 보류도 유지한다. 모델·추론 수준은 .env 설정, 예산/실행 승인·재판정/운영 정책·이슈 수준 종합 방향과 퍼센트 충돌은 별도 팀 최종 결정 대상이다. 실제 판정 없으면 null을 반환한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| round | query | 선택 | string / null | Briefing round id (e.g. brf-2026-09-17-morning): read the graph as it stood when that round was published. Never falls back to the newest graph; see GET /api/v1/briefings/{id}/graph. |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |

<a id="getevidence"></a>

## getEvidence · 원문 인용과 기업별 긍부정 조회

원문 인용과 기업별 긍부정 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/evidence/{id}` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [EvidenceResponse](#schema-evidenceresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, VERSION_UNAVAILABLE, EVIDENCE_UNAVAILABLE |
| FS/NFS | [FS024](../../system/out/feature-FS024.md) · [FS043](../../system/out/feature-FS043.md) · [FS049](../../system/out/feature-FS049.md) · [FS055](../../system/out/feature-FS055.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-GRP-05](../../system/out/screen-D-GRP-05.md) · [D-COM-02](../../system/out/screen-D-COM-02.md) · [D-AI-01](../../system/out/screen-D-AI-01.md) · [D-SEN-01](../../system/out/screen-D-SEN-01.md) |
| WBS | 6.1.2, 6.11.1, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.7.6, 6.7.9, 6.9.5, 6.9.14, 6.5.1 |
| 프로토타입 대응 | /api/evidence/{id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 긍정/부정 명칭은 사용자 결정 완료이며 혼재/판단 보류도 유지한다. 모델·추론 수준은 .env 설정, 예산/실행 승인·재판정/운영 정책·이슈 수준 종합 방향과 퍼센트 충돌은 별도 팀 최종 결정 대상이다. 실제 판정 없으면 null을 반환한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| round | query | 선택 | string / null | Briefing round id (e.g. brf-2026-09-17-morning): read the graph as it stood when that round was published. Never falls back to the newest graph; see GET /api/v1/briefings/{id}/graph. |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |
| companyId | query | 선택 | string | 기업 맥락을 지정하면 승인 연결을 검증하고 해당 기업 판정만 반환한다. 생략하면 sentiment=null이다. |

<a id="getbriefing"></a>

## getBriefing · 공개 브리핑 회차 조회

발행 당시 자료와 그래프 버전·시장 지표·outlook·문서별 기업 판정을 읽는다. 발행 후 재판정하거나 최신 값으로 대체하지 않는다. 출근 07:40/퇴근 18:10 KST, 핵심 이슈 최대 3개는 기존 요구사항 확정값이며 부족하면 채우지 않는다. 시장 요약은 근거와 검증을 갖춘 실제 생성 결과만 제공한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/briefings` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [BriefingResponse](#schema-briefingresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR |
| FS/NFS | [FS028](../../system/out/feature-FS028.md) · [FS029](../../system/out/feature-FS029.md) · [FS030](../../system/out/feature-FS030.md) · [FS031](../../system/out/feature-FS031.md) · [FS033](../../system/out/feature-FS033.md) · [FS034](../../system/out/feature-FS034.md) · [FS035](../../system/out/feature-FS035.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS006](../../system/out/feature-NFS006.md) |
| 화면 | [D-BRF-01](../../system/out/screen-D-BRF-01.md) · [D-BRF-02](../../system/out/screen-D-BRF-02.md) · [M-BRF-01](../../system/out/screen-M-BRF-01.md) · [D-SEN-02](../../system/out/screen-D-SEN-02.md) |
| WBS | 6.1.2, 6.11.1, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 |
| 프로토타입 대응 | /api/briefings |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다., 긍정/부정 명칭은 사용자 결정 완료이며 혼재/판단 보류도 유지한다. 모델·추론 수준은 .env 설정, 예산/실행 승인·재판정/운영 정책·이슈 수준 종합 방향과 퍼센트 충돌은 별도 팀 최종 결정 대상이다. 실제 판정 없으면 null을 반환한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| date | query | 선택 | string (date) / null | Publication date (KST). Default: the latest round |
| edition | query | 선택 | string {morning, evening} / null |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="listbriefingrounds"></a>

## listBriefingRounds · 공개 브리핑 이력 조회

공개 브리핑 이력 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/briefings/rounds` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [BriefingRoundsResponse](#schema-briefingroundsresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, INVALID_CURSOR |
| FS/NFS | [FS033](../../system/out/feature-FS033.md) · [FS035](../../system/out/feature-FS035.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-BRF-01](../../system/out/screen-D-BRF-01.md) · [D-BRF-02](../../system/out/screen-D-BRF-02.md) · [M-BRF-01](../../system/out/screen-M-BRF-01.md) |
| WBS | 6.1.2, 6.11.1, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 |
| 프로토타입 대응 | /api/briefings/rounds |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="getbriefinggraphbasis"></a>

## getBriefingGraphBasis · 발행 당시 그래프 기준 조회

발행 당시 그래프 기준 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/briefings/{id}/graph` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [BriefingGraphBasis](#schema-briefinggraphbasis), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, VERSION_UNAVAILABLE, EVIDENCE_UNAVAILABLE |
| FS/NFS | [FS032](../../system/out/feature-FS032.md) · [FS035](../../system/out/feature-FS035.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-BRF-04](../../system/out/screen-D-BRF-04.md) |
| WBS | 6.1.2, 6.11.1, 6.8.5, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.8.14, 6.5.3 |
| 프로토타입 대응 | /api/briefings/{id}/graph |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="createconversation"></a>

## createConversation · 새 대화 생성

새 대화 생성.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `PUT /api/v1/chat/sessions/{id}` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 201: [ChatSessionResponse](#schema-chatsessionresponse), 200: [ChatSessionResponse](#schema-chatsessionresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS050](../../system/out/feature-FS050.md) · [FS060](../../system/out/feature-FS060.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS006](../../system/out/feature-NFS006.md) |
| 화면 | [D-AI-01](../../system/out/screen-D-AI-01.md) · [M-AI-01](../../system/out/screen-M-AI-01.md) |
| WBS | 6.1.2, 6.11.1, 6.9.6, 6.9.10, 6.9.11, 6.9.14 |
| 프로토타입 대응 | /api/chat/sessions/{id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다., AI v2(08 시트)가 현행 상세다. 옛 FS046 권한·중복 작업 통제는 현 목차에 단일 FS가 없어 aiJobs 공통 규칙과 NFS001/003으로 보존했다. v2 상세가 대화 소유·동시 접수 하나·최초 요청 고정을 명시할지 AI 명세 담당자가 확인해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string | Conversation id made by the client |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |

<a id="getconversation"></a>

## getConversation · 대화와 질문 작업 조회

대화와 질문 작업 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/chat/sessions/{id}` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [ChatConversation](#schema-chatconversation), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS050](../../system/out/feature-FS050.md) · [FS051](../../system/out/feature-FS051.md) · [FS060](../../system/out/feature-FS060.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS006](../../system/out/feature-NFS006.md) |
| 화면 | [D-AI-01](../../system/out/screen-D-AI-01.md) · [D-AI-02b](../../system/out/screen-D-AI-02b.md) · [M-AI-01](../../system/out/screen-M-AI-01.md) |
| WBS | 6.1.2, 6.11.1, 6.9.6, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 |
| 프로토타입 대응 | /api/chat/sessions/{id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string | Conversation id made by the client |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="getcurrentconversation"></a>

## getCurrentConversation · 최신 대화 복원

최신 대화 복원.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/chat/sessions/current` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [ChatCurrentResponse](#schema-chatcurrentresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS051](../../system/out/feature-FS051.md) · [FS060](../../system/out/feature-FS060.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS006](../../system/out/feature-NFS006.md) |
| 화면 | [D-AI-02b](../../system/out/screen-D-AI-02b.md) · [M-AI-01](../../system/out/screen-M-AI-01.md) |
| WBS | 6.1.2, 6.11.1, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 |
| 프로토타입 대응 | /api/chat/sessions/current |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="submitquestion"></a>

## submitQuestion · 질문 접수·맥락 고정·비동기 분석

최초 접수에서 질문·시각·대화·작업 ID·기업/이슈/기업 간 관계·문서·기간·asOf·graphVersion을 고정한다. 같은 jobId/멱등성 키는 저장된 같은 작업을 반환하고 내용 불일치는 409다. 질문의 명시 조건을 화면 맥락보다 우선한다. 검증과 저장이 완료된 결과만 completed다. 유효한 근거 없음을 기술 장애로 위장하지 않는다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/chat/sessions/{id}/jobs` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | [ChatJobRequest](#schema-chatjobrequest) |
| 응답 | 202: [ChatJob](#schema-chatjob), 200: [ChatJob](#schema-chatjob), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, VERSION_UNAVAILABLE, EVIDENCE_UNAVAILABLE, JOB_IN_PROGRESS, JOB_NOT_RETRYABLE, MODEL_UNAVAILABLE, VALIDATION_FAILED |
| FS/NFS | [FS025](../../system/out/feature-FS025.md) · [FS045](../../system/out/feature-FS045.md) · [FS046](../../system/out/feature-FS046.md) · [FS047](../../system/out/feature-FS047.md) · [FS048](../../system/out/feature-FS048.md) · [FS049](../../system/out/feature-FS049.md) · [FS050](../../system/out/feature-FS050.md) · [FS051](../../system/out/feature-FS051.md) · [FS060](../../system/out/feature-FS060.md) · [FS064](../../system/out/feature-FS064.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS006](../../system/out/feature-NFS006.md) |
| 화면 | [D-AI-01](../../system/out/screen-D-AI-01.md) · [D-AI-01b](../../system/out/screen-D-AI-01b.md) · [M-AI-01](../../system/out/screen-M-AI-01.md) |
| WBS | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 |
| 프로토타입 대응 | /api/chat/sessions/{id}/jobs |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다., AI v2(08 시트)가 현행 상세다. 옛 FS046 권한·중복 작업 통제는 현 목차에 단일 FS가 없어 aiJobs 공통 규칙과 NFS001/003으로 보존했다. v2 상세가 대화 소유·동시 접수 하나·최초 요청 고정을 명시할지 AI 명세 담당자가 확인해야 한다., 긍정/부정 명칭은 사용자 결정 완료이며 혼재/판단 보류도 유지한다. 모델·추론 수준은 .env 설정, 예산/실행 승인·재판정/운영 정책·이슈 수준 종합 방향과 퍼센트 충돌은 별도 팀 최종 결정 대상이다. 실제 판정 없으면 null을 반환한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string | Conversation id made by the client |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [ChatJobRequest](#schema-chatjobrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="getquestionjob"></a>

## getQuestionJob · 질문 작업 상태·저장 결과 회수

질문 작업 상태·저장 결과 회수.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/chat/jobs/{job_id}` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [ChatJob](#schema-chatjob), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, JOB_IN_PROGRESS, JOB_NOT_RETRYABLE, MODEL_UNAVAILABLE, VALIDATION_FAILED |
| FS/NFS | [FS048](../../system/out/feature-FS048.md) · [FS049](../../system/out/feature-FS049.md) · [FS051](../../system/out/feature-FS051.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS006](../../system/out/feature-NFS006.md) |
| 화면 | [D-AI-02](../../system/out/screen-D-AI-02.md) · [M-AI-01](../../system/out/screen-M-AI-01.md) |
| WBS | 6.1.2, 6.11.1, 6.9.4, 6.9.5, 6.9.7, 6.9.9, 6.9.13, 6.9.14 |
| 프로토타입 대응 | /api/chat/jobs/{job_id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다., AI v2(08 시트)가 현행 상세다. 옛 FS046 권한·중복 작업 통제는 현 목차에 단일 FS가 없어 aiJobs 공통 규칙과 NFS001/003으로 보존했다. v2 상세가 대화 소유·동시 접수 하나·최초 요청 고정을 명시할지 AI 명세 담당자가 확인해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| job_id | path | 필수 | string | Job id made by the client (idempotency key) |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="retryquestionjob"></a>

## retryQuestionJob · 허용된 실패만 같은 질문 작업 재시도

허용된 실패만 같은 질문 작업 재시도.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/chat/jobs/{job_id}/retry` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 202: [ChatJob](#schema-chatjob), 200: [ChatJob](#schema-chatjob), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, JOB_IN_PROGRESS, JOB_NOT_RETRYABLE, MODEL_UNAVAILABLE, VALIDATION_FAILED |
| FS/NFS | [FS051](../../system/out/feature-FS051.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS006](../../system/out/feature-NFS006.md) |
| 화면 | [D-AI-02](../../system/out/screen-D-AI-02.md) · [M-AI-01](../../system/out/screen-M-AI-01.md) |
| WBS | 6.1.2, 6.11.1, 6.9.7, 6.9.9, 6.9.13, 6.9.14 |
| 프로토타입 대응 | /api/chat/jobs/{job_id}/retry |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| job_id | path | 필수 | string | Job id made by the client (idempotency key) |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

<a id="cancelquestionjob"></a>

## cancelQuestionJob · 질문 작업 명시적 취소

질문 작업 명시적 취소.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/chat/jobs/{job_id}/cancel` |
| 권한·우선순위 | 회원(본인) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [ChatJob](#schema-chatjob), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, JOB_IN_PROGRESS, JOB_NOT_RETRYABLE, MODEL_UNAVAILABLE, VALIDATION_FAILED |
| FS/NFS | [FS051](../../system/out/feature-FS051.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS006](../../system/out/feature-NFS006.md) |
| 화면 | [D-AI-02](../../system/out/screen-D-AI-02.md) · [M-AI-01](../../system/out/screen-M-AI-01.md) |
| WBS | 6.1.2, 6.11.1, 6.9.7, 6.9.9, 6.9.13, 6.9.14 |
| 프로토타입 대응 | /api/chat/jobs/{job_id}/cancel |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다., AI v2(08 시트)가 현행 상세다. 옛 FS046 권한·중복 작업 통제는 현 목차에 단일 FS가 없어 aiJobs 공통 규칙과 NFS001/003으로 보존했다. v2 상세가 대화 소유·동시 접수 하나·최초 요청 고정을 명시할지 AI 명세 담당자가 확인해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| job_id | path | 필수 | string | Job id made by the client (idempotency key) |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

<a id="getadminsession"></a>

## getAdminSession · 관리자 세션 조회

관리자 세션 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/auth/session` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [AdminSession](#schema-adminsession), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR |
| FS/NFS | [FS073](../../system/out/feature-FS073.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-05c](../../system/out/screen-A-ADM-05c.md) |
| WBS | 6.1.2, 6.11.1, 6.10.1, 6.10.13 |
| 프로토타입 대응 | /api/admin/auth/session |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| 팀 확인 필요 | 정식 소셜/SSO 제공자와 계정 연결 정책, 관리자 권한 등급·회수 정책을 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="loginadmin"></a>

## logInAdmin · 관리자 로그인

관리자 로그인.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/auth/login` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | [AdminLoginRequest](#schema-adminloginrequest) |
| 응답 | 200: [AdminSession](#schema-adminsession), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, INVALID_CREDENTIALS, MEMBER_BLOCKED |
| FS/NFS | [FS073](../../system/out/feature-FS073.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [A-ADM-05c](../../system/out/screen-A-ADM-05c.md) |
| WBS | 6.1.2, 6.11.1, 6.10.1, 6.10.13 |
| 프로토타입 대응 | /api/admin/auth/login |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| 팀 확인 필요 | 정식 소셜/SSO 제공자와 계정 연결 정책, 관리자 권한 등급·회수 정책을 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

본문 스키마: [AdminLoginRequest](#schema-adminloginrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="logoutadmin"></a>

## logOutAdmin · 관리자 로그아웃

관리자 로그아웃은 자연 멱등 세션 폐기이며 Idempotency-Key를 요구하지 않는다. 활성 zoop_admin_session이 있으면 동일 쿠키·Origin·세션 결합 X-CSRF-Token을 반드시 검증하고 해당 세션만 폐기한다. Origin/CSRF 실패는 403 ACCESS_DENIED이며 무세션 분기로 우회하지 않는다. 세션 없음·무효·만료이면 다른 세션을 변경하지 않고 204를 반환한다. zoop_admin_session 쿠키만 제거하며 회원 세션/쿠키에는 영향을 주지 않는다. 선택 인증·선택 헤더 표기는 조건부 런타임 검증을 자동 강제하지 않는다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/auth/logout` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 204: 본문 없음, 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, ACCESS_DENIED, RATE_LIMITED |
| FS/NFS | [FS073](../../system/out/feature-FS073.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [A-ADM-05c](../../system/out/screen-A-ADM-05c.md) · [A-ADM-01](../../system/out/screen-A-ADM-01.md) |
| WBS | 6.1.2, 6.11.1, 6.10.1, 6.10.13 |
| 프로토타입 대응 | /api/admin/auth/logout |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다., 목표는 활성 관리자 세션의 Origin/조건부 CSRF 검증, 무세션 반복204 및 관리자/회원 쿠키 분리를 요구한다. 현재 BFF의 목표 보안 구현 완료를 뜻하지 않는다. |
| 팀 확인 필요 | 정식 소셜/SSO 제공자와 계정 연결 정책, 관리자 권한 등급·회수 정책을 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 선택 | string | 활성 zoop_admin_session이 있으면 필수이며 해당 세션에 결합된 토큰이어야 한다. 누락/불일치는 403 ACCESS_DENIED이고 무세션 분기로 우회하지 않는다. 세션 없음·무효·만료이면 필요하지 않다. Origin도 검증한다. |

<a id="getadmindashboard"></a>

## getAdminDashboard · 운영 대시보드 조회

운영 대시보드 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/dashboard` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [Dashboard](#schema-dashboard), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS072](../../system/out/feature-FS072.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-01](../../system/out/screen-A-ADM-01.md) |
| WBS | 6.1.2, 6.11.1, 6.10.2, 6.10.14 |
| 프로토타입 대응 | /api/admin/dashboard |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="listauditrecords"></a>

## listAuditRecords · 운영 감사 기록 조회

운영 감사 기록 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/audit-log` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [AuditPage](#schema-auditpage), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS072](../../system/out/feature-FS072.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-05b](../../system/out/screen-A-ADM-05b.md) |
| WBS | 6.1.2, 6.11.1, 6.10.12, 6.10.18 |
| 프로토타입 대응 | /api/admin/audit-log |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| action | query | 선택 | string / null |  |
| actor | query | 선택 | string / null |  |
| targetType | query | 선택 | string / null |  |
| q | query | 선택 | string / null |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="getpipelineoverview"></a>

## getPipelineOverview · 수집·분석·공개 반영 상태 조회

수집·분석·공개 반영 상태 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/pipeline/overview` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [Overview](#schema-overview), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS058](../../system/out/feature-FS058.md) · [FS059](../../system/out/feature-FS059.md) · [FS063](../../system/out/feature-FS063.md) · [FS067-01](../../system/out/feature-FS067-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4, 6.5.5, 6.5.6 |
| 프로토타입 대응 | /api/admin/pipeline/overview |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="listanalysiscandidates"></a>

## listAnalysisCandidates · 검수 후보 목록 조회

검수 후보 목록 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/pipeline/candidates` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [CandidateList](#schema-candidatelist), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS067-01](../../system/out/feature-FS067-01.md) · [FS067-02](../../system/out/feature-FS067-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.6, 6.10.7, 6.10.16 |
| 프로토타입 대응 | /api/admin/pipeline/candidates |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 대화록 열람/검수 권한, 마스킹 목록, 감사 기록 보존기간과 자동 검증 정책의 지위를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| status | query | 선택 | string {ALLOW, HOLD, REJECT} / null |  |
| decision | query | 선택 | string {none, allow, reject} / null |  |
| active | query | 선택 | boolean / null |  |
| published | query | 선택 | boolean / null |  |
| rule | query | 선택 | boolean / null |  |
| q | query | 선택 | string / null |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="getanalysiscandidate"></a>

## getAnalysisCandidate · 후보 근거와 검증 결과 조회

후보 근거와 검증 결과 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/pipeline/candidates/{candidate_id}` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [CandidateDetail](#schema-candidatedetail), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS067-01](../../system/out/feature-FS067-01.md) · [FS067-02](../../system/out/feature-FS067-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.6, 6.10.7, 6.10.16 |
| 프로토타입 대응 | /api/admin/pipeline/candidates/{candidate_id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 대화록 열람/검수 권한, 마스킹 목록, 감사 기록 보존기간과 자동 검증 정책의 지위를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| candidate_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="decideanalysiscandidate"></a>

## decideAnalysisCandidate · 후보 거부 또는 재검증 대상으로 전환

관리자는 후보 상세에서 확인한 대상별 revision과 AI 원천 sourceVersion/sourceRevision을 expectedRevision/expectedSourceVersion/expectedSourceRevision으로 보낸다. relationId가 있으면 세 기대값은 해당 relation의 값이다. 서버는 대상·현재 AI 원천을 다시 확인하고 하나라도 다르면 REVISION_CONFLICT/409로 거절하며 결정·재검증 작업·감사를 성공으로 기록하지 않는다. allow는 재검증 대상으로만 전환한다. 필수 근거 확인 및 자동 검증 통과 전에 공개할 수 없다. 결정·재검증·공개는 별도 기록이다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/pipeline/candidates/{candidate_id}/decision` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [DecisionRequest](#schema-decisionrequest) |
| 응답 | 200: [DecisionResponse](#schema-decisionresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, VALIDATION_FAILED, AUDIT_UNAVAILABLE |
| FS/NFS | [FS059](../../system/out/feature-FS059.md) · [FS067-02](../../system/out/feature-FS067-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 |
| 프로토타입 대응 | /api/admin/pipeline/candidates/{candidate_id}/decision |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF allow 처리와 목표의 재검증 접수·expectedRevision·expectedSourceVersion·expectedSourceRevision·비공개 유지 규칙을 대조한다. |
| 팀 확인 필요 | 대화록 열람/검수 권한, 마스킹 목록, 감사 기록 보존기간과 자동 검증 정책의 지위를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| candidate_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [DecisionRequest](#schema-decisionrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="listpublicationrules"></a>

## listPublicationRules · 공개 검증 규칙 조회

공개 검증 규칙 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/pipeline/rules` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [RuleList](#schema-rulelist), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS059](../../system/out/feature-FS059.md) · [FS067-01](../../system/out/feature-FS067-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.5 |
| 프로토타입 대응 | /api/admin/pipeline/rules |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="setpublicationrule"></a>

## setPublicationRule · 검증 규칙 목표 상태 설정

검증 규칙 목표 상태 설정.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `PUT /api/v1/admin/pipeline/rules/{rule_id}` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [RuleSwitchRequest](#schema-ruleswitchrequest) |
| 응답 | 200: [RuleSwitchResponse](#schema-ruleswitchresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS059](../../system/out/feature-FS059.md) · [FS067-02](../../system/out/feature-FS067-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 |
| 프로토타입 대응 | /api/admin/pipeline/rules/{rule_id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 대화록 열람/검수 권한, 마스킹 목록, 감사 기록 보존기간과 자동 검증 정책의 지위를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| rule_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |

본문 스키마: [RuleSwitchRequest](#schema-ruleswitchrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="listgraphversions"></a>

## listGraphVersions · 공개 그래프 버전 목록 조회

공개 그래프 버전 목록 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/graph/versions` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [GraphVersionList](#schema-graphversionlist), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS059](../../system/out/feature-FS059.md) · [FS067-01](../../system/out/feature-FS067-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.5 |
| 프로토타입 대응 | /api/admin/graph/versions |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="publishgraphversion"></a>

## publishGraphVersion · 검증 통과 결과의 새 공개 버전 발행

검증 통과 결과의 새 공개 버전 발행.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/graph/versions` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [ReasonRequest](#schema-reasonrequest) |
| 응답 | 201: [PublishResponse](#schema-publishresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS059](../../system/out/feature-FS059.md) · [FS067-02](../../system/out/feature-FS067-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 |
| 프로토타입 대응 | /api/admin/graph/versions |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 대화록 열람/검수 권한, 마스킹 목록, 감사 기록 보존기간과 자동 검증 정책의 지위를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [ReasonRequest](#schema-reasonrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="activategraphversion"></a>

## activateGraphVersion · 기존 공개 버전 활성화

기존 공개 버전 활성화.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/graph/versions/{version_id}/activate` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [ReasonRequest](#schema-reasonrequest) |
| 응답 | 200: [ActivateResponse](#schema-activateresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS059](../../system/out/feature-FS059.md) · [FS067-02](../../system/out/feature-FS067-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.7, 6.10.16, 6.5.5 |
| 프로토타입 대응 | /api/admin/graph/versions/{version_id}/activate |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 대화록 열람/검수 권한, 마스킹 목록, 감사 기록 보존기간과 자동 검증 정책의 지위를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| version_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [ReasonRequest](#schema-reasonrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="listanalysisjobs"></a>

## listAnalysisJobs · 수집·분석 작업 목록 조회

수집·분석 작업 목록 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/jobs` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [JobList](#schema-joblist), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS058](../../system/out/feature-FS058.md) · [FS067-01](../../system/out/feature-FS067-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4 |
| 프로토타입 대응 | /api/admin/jobs |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다., 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| status | query | 선택 | string {queued, running, succeeded, failed, cancelled} / null |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="createanalysisjob"></a>

## createAnalysisJob · 수집·재검증·투영 작업 접수

수집·재검증·투영 작업 접수.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/jobs` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [JobCreate](#schema-jobcreate) |
| 응답 | 202: [JobCreated](#schema-jobcreated), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS058](../../system/out/feature-FS058.md) · [FS059](../../system/out/feature-FS059.md) · [FS063](../../system/out/feature-FS063.md) · [FS064](../../system/out/feature-FS064.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.5.4, 6.5.5, 6.5.6, 6.5.7 |
| 프로토타입 대응 | /api/admin/jobs |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| 팀 확인 필요 | 긍정/부정 명칭은 사용자 결정 완료이며 혼재/판단 보류도 유지한다. 모델·추론 수준은 .env 설정, 예산/실행 승인·재판정/운영 정책·이슈 수준 종합 방향과 퍼센트 충돌은 별도 팀 최종 결정 대상이다. 실제 판정 없으면 null을 반환한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [JobCreate](#schema-jobcreate). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="getanalysisjob"></a>

## getAnalysisJob · 분석 작업 상태 조회

분석 작업 상태 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/jobs/{job_id}` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [JobOut](#schema-jobout), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS067-01](../../system/out/feature-FS067-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.6, 6.10.16 |
| 프로토타입 대응 | /api/admin/jobs/{job_id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| job_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="retryanalysisjob"></a>

## retryAnalysisJob · 허용된 분석 작업 재시도

허용된 분석 작업 재시도.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/jobs/{job_id}/retry` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [JobRetry](#schema-jobretry) |
| 응답 | 202: [JobCreated](#schema-jobcreated), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS067-03](../../system/out/feature-FS067-03.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.7, 6.10.16 |
| 프로토타입 대응 | /api/admin/jobs/{job_id}/retry |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| job_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [JobRetry](#schema-jobretry). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="cancelanalysisjob"></a>

## cancelAnalysisJob · 분석 작업 명시적 취소

분석 작업 명시적 취소.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/jobs/{job_id}/cancel` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [ReasonRequest](#schema-reasonrequest) |
| 응답 | 200: [JobOut](#schema-jobout), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS067-03](../../system/out/feature-FS067-03.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) · [NFS012](../../system/out/feature-NFS012.md) |
| 화면 | [A-ADM-03](../../system/out/screen-A-ADM-03.md) |
| WBS | 6.1.2, 6.11.1, 6.10.7, 6.10.16 |
| 프로토타입 대응 | /api/admin/jobs/{job_id}/cancel |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| job_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [ReasonRequest](#schema-reasonrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="getaiusage"></a>

## getAiUsage · AI 사용량·비용·오류 조회

기능별 접수 요청과 실제 외부 모델 시도·저장 결과 재사용·재시도를 구분한다. requests는 기능별 도메인 작업 수이며 관리자 analysis_jobs 전체 행 수가 아니다. document-summary와 semantic-verification의 모델 호출은 news-analysis, 기업 문서 판정은 document-sentiment, 브리핑 전망은 briefing-outlook에 귀속하고 동일 호출을 briefing에도 중복 집계하지 않는다. 결과 보류 후에도 내용 없는 사용량 영수증은 집계하며, 전송·토큰·비용이 불명확하면 0으로 채우지 않고 nullable 값과 note로 표시한다. 공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/ai-usage` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [AiUsageResponse](#schema-aiusageresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS068](../../system/out/feature-FS068.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-04b](../../system/out/screen-A-ADM-04b.md) |
| WBS | 6.1.2, 6.11.1, 6.10.8, 6.10.17 |
| 프로토타입 대응 | /api/admin/ai-usage |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| window | query | 선택 | string {24h, 7d, 30d, all} |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="listadminbriefingrounds"></a>

## listAdminBriefingRounds · 브리핑 회차 운영 상태 목록

브리핑 회차 운영 상태 목록.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/briefings` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [RoundList](#schema-roundlist), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS070-01](../../system/out/feature-FS070-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-04](../../system/out/screen-A-ADM-04.md) |
| WBS | 6.1.2, 6.11.1, 6.10.9, 6.10.17 |
| 프로토타입 대응 | /api/admin/briefings |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| from | query | 선택 | string (date) / string (date-time) | KST 날짜 또는 오프셋을 포함한 정확한 시각. from/to는 동일 기준을 사용한다. |
| to | query | 선택 | string (date) / string (date-time) | KST 날짜 또는 오프셋을 포함한 정확한 시각. from/to는 동일 기준을 사용한다. |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="getadminbriefinground"></a>

## getAdminBriefingRound · 브리핑 생성·검증·발행 상태 조회

브리핑 생성·검증·발행 상태 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/briefings/{round_id}` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [RoundDetail](#schema-rounddetail), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS070-01](../../system/out/feature-FS070-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-04](../../system/out/screen-A-ADM-04.md) |
| WBS | 6.1.2, 6.11.1, 6.10.9, 6.10.17 |
| 프로토타입 대응 | /api/admin/briefings/{round_id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| round_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="reprocessbriefinground"></a>

## reprocessBriefingRound · 미발행 회차 재처리

미발행 회차 재처리.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/briefings/{round_id}/reprocess` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [ReasonRequest](#schema-reasonrequest) |
| 응답 | 202: [RoundOut](#schema-roundout), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, ALREADY_PUBLISHED, AUDIT_UNAVAILABLE |
| FS/NFS | [FS028](../../system/out/feature-FS028.md) · [FS029](../../system/out/feature-FS029.md) · [FS034](../../system/out/feature-FS034.md) · [FS070-02](../../system/out/feature-FS070-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [A-ADM-04](../../system/out/screen-A-ADM-04.md) |
| WBS | 6.1.2, 6.11.1, 6.8.1, 6.8.2, 6.8.8, 6.8.11, 6.8.12, 6.10.9, 6.10.17 |
| 프로토타입 대응 | /api/admin/briefings/{round_id}/reprocess |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 긍정/부정 명칭은 사용자 결정 완료이며 혼재/판단 보류도 유지한다. 모델·추론 수준은 .env 설정, 예산/실행 승인·재판정/운영 정책·이슈 수준 종합 방향과 퍼센트 충돌은 별도 팀 최종 결정 대상이다. 실제 판정 없으면 null을 반환한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| round_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [ReasonRequest](#schema-reasonrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="appendbriefingcorrection"></a>

## appendBriefingCorrection · 발행 원문을 유지하는 정정 등록

발행 원문을 유지하는 정정 등록.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/briefings/{round_id}/corrections` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [CorrectionRequest](#schema-correctionrequest) |
| 응답 | 201: [CorrectionOut](#schema-correctionout), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, ALREADY_PUBLISHED, AUDIT_UNAVAILABLE |
| FS/NFS | [FS035](../../system/out/feature-FS035.md) · [FS071-01](../../system/out/feature-FS071-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [A-ADM-04](../../system/out/screen-A-ADM-04.md) |
| WBS | 6.1.2, 6.11.1, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.10.10, 6.10.17, 6.5.3 |
| 프로토타입 대응 | /api/admin/briefings/{round_id}/corrections |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 핵심 이슈 선정·동점 규칙, 자료/대화/작업/멱등성 키 보존 기간, 오류별 재시도 범위와 판정 수치를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| round_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [CorrectionRequest](#schema-correctionrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="setbriefingsuspension"></a>

## setBriefingSuspension · 브리핑 제공 중단·재개

브리핑 제공 중단·재개.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/briefings/{round_id}/suspension` |
| 권한·우선순위 | 관리자(작업별 권한) · P1 |
| 요청 본문 | [SuspensionRequest](#schema-suspensionrequest) |
| 응답 | 200: [RoundOut](#schema-roundout), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED, ALREADY_PUBLISHED, AUDIT_UNAVAILABLE |
| FS/NFS | [FS071-02](../../system/out/feature-FS071-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [A-ADM-04](../../system/out/screen-A-ADM-04.md) |
| WBS | 6.1.2, 6.11.1, 6.10.10, 6.10.17 |
| 프로토타입 대응 | /api/admin/briefings/{round_id}/suspension |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| round_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [SuspensionRequest](#schema-suspensionrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="recordinteractionevents"></a>

## recordInteractionEvents · 허용된 사용 이벤트 접수

허용된 사용 이벤트 접수.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/telemetry` |
| 권한·우선순위 | 회원 또는 비회원 세션 · P2 |
| 요청 본문 | [TelemetryBatch](#schema-telemetrybatch) |
| 응답 | 202: [TelemetryAccepted](#schema-telemetryaccepted), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS065](../../system/out/feature-FS065.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [M-GRP-01](../../system/out/screen-M-GRP-01.md) · [D-GRP-01](../../system/out/screen-D-GRP-01.md) |
| WBS | 6.1.2, 6.11.1, 6.10.4, 6.10.15 |
| 프로토타입 대응 | /api/telemetry |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [TelemetryBatch](#schema-telemetrybatch). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="getmyfeedback"></a>

## getMyFeedback · 본인의 유효 평가 상태 조회

본인의 유효 평가 상태 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/feedback` |
| 권한·우선순위 | 회원(본인) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [FeedbackList](#schema-feedbacklist), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS066-01](../../system/out/feature-FS066-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-AI-01](../../system/out/screen-D-AI-01.md) · [D-BRF-01](../../system/out/screen-D-BRF-01.md) · [D-COM-02](../../system/out/screen-D-COM-02.md) |
| WBS | 6.1.2, 6.11.1, 6.8.10, 6.8.14, 6.10.5 |
| 프로토타입 대응 | /api/feedback |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| feature | query | 필수 | string {chatbot_answer, briefing_round, briefing_issue} |  |
| targetIds | query | 필수 | string | Comma separated |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="setfeedback"></a>

## setFeedback · AI 결과 평가 목표 상태 설정

AI 결과 평가 목표 상태 설정.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `PUT /api/v1/feedback` |
| 권한·우선순위 | 회원(본인) · P2 |
| 요청 본문 | [FeedbackVote](#schema-feedbackvote) |
| 응답 | 200: [FeedbackItem](#schema-feedbackitem), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS066-01](../../system/out/feature-FS066-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [D-AI-01](../../system/out/screen-D-AI-01.md) · [D-BRF-01](../../system/out/screen-D-BRF-01.md) · [D-COM-02](../../system/out/screen-D-COM-02.md) |
| WBS | 6.1.2, 6.11.1, 6.8.10, 6.8.14, 6.10.5 |
| 프로토타입 대응 | /api/feedback |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |

본문 스키마: [FeedbackVote](#schema-feedbackvote). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="getinsightsoverview"></a>

## getInsightsOverview · 사용 통계 개요 조회

사용 통계 개요 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/insights/overview` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [InsightsOverview](#schema-insightsoverview), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS065](../../system/out/feature-FS065.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-02](../../system/out/screen-A-ADM-02.md) |
| WBS | 6.1.2, 6.11.1, 6.10.4, 6.10.15 |
| 프로토타입 대응 | /api/admin/insights/overview |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="getinsightssummary"></a>

## getInsightsSummary · 사용 통계와 산식 조회

사용 통계와 산식 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/insights/summary` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [StatsSummary](#schema-statssummary), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS065](../../system/out/feature-FS065.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-02](../../system/out/screen-A-ADM-02.md) |
| WBS | 6.1.2, 6.11.1, 6.10.4, 6.10.15 |
| 프로토타입 대응 | /api/admin/insights/summary |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| window | query | 선택 | string {7d, 30d, all} |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="listcompanyinsights"></a>

## listCompanyInsights · 기업별 활동 집계 조회

기업별 활동 집계 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/insights/companies` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [InsightCompanyRanking](#schema-insightcompanyranking), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS065](../../system/out/feature-FS065.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-02](../../system/out/screen-A-ADM-02.md) |
| WBS | 6.1.2, 6.11.1, 6.10.4, 6.10.15 |
| 프로토타입 대응 | /api/admin/insights/companies |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| window | query | 선택 | string {7d, 30d, all} |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="getcompanyinsights"></a>

## getCompanyInsights · 기업별 일별 활동 조회

기업별 일별 활동 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/insights/companies/{company_id}` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [InsightCompanyDetail](#schema-insightcompanydetail), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS065](../../system/out/feature-FS065.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-02](../../system/out/screen-A-ADM-02.md) |
| WBS | 6.1.2, 6.11.1, 6.10.4, 6.10.15 |
| 프로토타입 대응 | /api/admin/insights/companies/{company_id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| company_id | path | 필수 | string |  |
| window | query | 선택 | string {7d, 30d, all} |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="getfeedbacksummary"></a>

## getFeedbackSummary · AI 기능별 유효 평가 집계

AI 기능별 유효 평가 집계.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/feedback/summary` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [FeedbackSummary](#schema-feedbacksummary), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS066-02](../../system/out/feature-FS066-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-02b](../../system/out/screen-A-ADM-02b.md) |
| WBS | 6.1.2, 6.11.1, 6.10.5, 6.10.15 |
| 프로토타입 대응 | /api/admin/feedback/summary |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| window | query | 선택 | string {7d, 30d, all} |  |
| start | query | 선택 | string (date) / null | KST day (inclusive) of the rating's last valid change; overrides window |
| end | query | 선택 | string (date) / null | KST day (inclusive) of the rating's last valid change; overrides window |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="listdislikedresults"></a>

## listDislikedResults · 현재 부정 평가 결과 조회

현재 부정 평가 결과 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/feedback/dislikes` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [DislikePage](#schema-dislikepage), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS066-02](../../system/out/feature-FS066-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-02b](../../system/out/screen-A-ADM-02b.md) |
| WBS | 6.1.2, 6.11.1, 6.10.5, 6.10.15 |
| 프로토타입 대응 | /api/admin/feedback/dislikes |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| window | query | 선택 | string {7d, 30d, all} |  |
| start | query | 선택 | string (date) / null | KST day (inclusive) of the rating's last valid change; overrides window |
| end | query | 선택 | string (date) / null | KST day (inclusive) of the rating's last valid change; overrides window |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="listmaskedtranscripts"></a>

## listMaskedTranscripts · 마스킹 대화록 목록 조회

대화록 열람은 일반 관리자 권한과 별개다. 마스킹 또는 필수 열람 기록 저장 실패 시 원문/목록을 반환하지 않는다. 반환 정보·마스킹 목록·목적 사전·보존 기간은 팀 확인 필요다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/transcripts` |
| 권한·우선순위 | 관리자 + transcript:read + 열람 목적 · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [TranscriptPage](#schema-transcriptpage), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, AUDIT_UNAVAILABLE, MASKING_FAILED, INVALID_CURSOR |
| FS/NFS | [FS066-03](../../system/out/feature-FS066-03.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-02b](../../system/out/screen-A-ADM-02b.md) |
| WBS | 6.1.2, 6.11.1, 6.10.11, 6.10.15 |
| 프로토타입 대응 | /api/admin/transcripts |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다., BFF에 별도 열람 권한·purpose 필수·기록 실패 차단 계약이 부족하다. |
| 팀 확인 필요 | 대화록 열람/검수 권한, 마스킹 목록, 감사 기록 보존기간과 자동 검증 정책의 지위를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| only | query | 선택 | string {all, disliked} | disliked: conversations with a disliked answer |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |
| purpose | query | 필수 | string | 승인된 열람 목적. 별도 transcript:read 권한과 마스킹 및 필수 감사 저장이 모두 성공해야 반환한다. |

<a id="getmaskedtranscript"></a>

## getMaskedTranscript · 목적·권한·감사 기록이 충족된 대화록 조회

대화록 열람은 일반 관리자 권한과 별개다. 마스킹 또는 필수 열람 기록 저장 실패 시 원문/목록을 반환하지 않는다. 반환 정보·마스킹 목록·목적 사전·보존 기간은 팀 확인 필요다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/transcripts/{session_id}` |
| 권한·우선순위 | 관리자 + transcript:read + 열람 목적 · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [TranscriptDetail](#schema-transcriptdetail), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, AUDIT_UNAVAILABLE, MASKING_FAILED |
| FS/NFS | [FS066-03](../../system/out/feature-FS066-03.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-02b](../../system/out/screen-A-ADM-02b.md) |
| WBS | 6.1.2, 6.11.1, 6.10.11, 6.10.15 |
| 프로토타입 대응 | /api/admin/transcripts/{session_id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., BFF에 별도 열람 권한·purpose 필수·기록 실패 차단 계약이 부족하다. |
| 팀 확인 필요 | 대화록 열람/검수 권한, 마스킹 목록, 감사 기록 보존기간과 자동 검증 정책의 지위를 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| session_id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| purpose | query | 필수 | string | 승인된 열람 목적. 별도 transcript:read 권한과 마스킹 및 필수 감사 저장이 모두 성공해야 반환한다. |

<a id="listmembers"></a>

## listMembers · 회원 활동 목록 조회

회원 활동 목록 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/members` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [MemberList](#schema-memberlist), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, INVALID_CURSOR |
| FS/NFS | [FS069-01](../../system/out/feature-FS069-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-05](../../system/out/screen-A-ADM-05.md) |
| WBS | 6.1.2, 6.11.1, 6.10.3, 6.10.18 |
| 프로토타입 대응 | /api/admin/members |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용., 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| status | query | 선택 | string {active, blocked} / null |  |
| q | query | 선택 | string / null | Matches the pseudonymous id or the masked e-mail |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| cursor | query | 선택 | string | 이전 페이지의 불투명 nextCursor. 조회 조건에 결합한다. |
| limit | query | 선택 | integer | 요청 페이지 크기. 기본값/상한은 운영 정책 미정이며 임의 전체 결과 상한이 아니다. |

<a id="getmemberactivity"></a>

## getMemberActivity · 회원 활동 상세 조회

회원 활동 상세 조회.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/admin/members/{member_id}` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [MemberDetail](#schema-memberdetail), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED |
| FS/NFS | [FS069-01](../../system/out/feature-FS069-01.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [A-ADM-05](../../system/out/screen-A-ADM-05.md) |
| WBS | 6.1.2, 6.11.1, 6.10.3, 6.10.18 |
| 프로토타입 대응 | /api/admin/members/{member_id} |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| member_id | path | 필수 | string | Pseudonymous member id, e.g. M-3FA9C2D1 |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="blockmember"></a>

## blockMember · 회원 차단 및 세션 회수

회원 차단 및 세션 회수.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/members/{member_id}/block` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | [ReasonRequest](#schema-reasonrequest) |
| 응답 | 200: [MemberStatusResult](#schema-memberstatusresult), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS069-02](../../system/out/feature-FS069-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [A-ADM-05](../../system/out/screen-A-ADM-05.md) |
| WBS | 6.1.2, 6.11.1, 6.10.3, 6.10.18 |
| 프로토타입 대응 | /api/admin/members/{member_id}/block |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| member_id | path | 필수 | string | Pseudonymous member id, e.g. M-3FA9C2D1 |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [ReasonRequest](#schema-reasonrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="unblockmember"></a>

## unblockMember · 회원 차단 해제

회원 차단 해제.  공통 규칙 및 x-zoop의 팀 확인 필요 사항을 함께 적용한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `POST /api/v1/admin/members/{member_id}/unblock` |
| 권한·우선순위 | 관리자(작업별 권한) · P2 |
| 요청 본문 | [ReasonRequest](#schema-reasonrequest) |
| 응답 | 200: [MemberStatusResult](#schema-memberstatusresult), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 429: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, SOURCE_UNAVAILABLE, INTERNAL_ERROR, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, RATE_LIMITED |
| FS/NFS | [FS069-02](../../system/out/feature-FS069-02.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS008](../../system/out/feature-NFS008.md) · [NFS003](../../system/out/feature-NFS003.md) · [NFS009](../../system/out/feature-NFS009.md) |
| 화면 | [A-ADM-05](../../system/out/screen-A-ADM-05.md) |
| WBS | 6.1.2, 6.11.1, 6.10.3, 6.10.18 |
| 프로토타입 대응 | /api/admin/members/{member_id}/unblock |
| 목표와 차이 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| 팀 확인 필요 | 해당 작업의 별도 항목 없음. 공통 미결정은 별도로 남는다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| member_id | path | 필수 | string | Pseudonymous member id, e.g. M-3FA9C2D1 |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| X-CSRF-Token | header | 필수 | string | 현재 인증 세션에 결합된 CSRF 토큰. Origin도 검증한다. |
| Idempotency-Key | header | 필수 | string | 같은 주체·작업의 중복 실행 방지 키. 보존 기간은 팀 확인 필요다. |

본문 스키마: [ReasonRequest](#schema-reasonrequest). 중첩 필드와 nullable/enum은 아래 공통 스키마를 확인한다.

<a id="getcompanyfinancials"></a>

## getCompanyFinancials · 재무·실적 기간 조회

재무 기간은 차트 기간과 별개다. 미제공·계산 불가 값은 null이고 사유를 제공한다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/companies/{id}/financials` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [FinancialResponse](#schema-financialresponse), 409: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, VERSION_UNAVAILABLE, SOURCE_UNAVAILABLE |
| FS/NFS | [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-COM-01](../../system/out/screen-D-COM-01.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) |
| WBS | 6.1.2, 6.11.1 |
| 프로토타입 대응 | 없음 |
| 목표와 차이 | 직접 대응 API 없음. 재무는 기업 지표와 구분한다. |
| 팀 확인 필요 | 재무 제공 항목·회계 기간·개인화 브리핑 생성 조건/재사용/대상 수 또는 영향 경로 데이터 모델은 해당 명세의 확인 필요 사항을 팀이 확정해야 한다., 요구 42의 재무·실적은 폐기되지 않았고 목차 FS042(시점 그래프)와 번호만 겹친다. 전용 FS ID·담당 WBS·공급자·허용 기간/항목·회계 기준은 팀 최종 결정 대상이며 API는 기존 목표만 보존한다. |

요구사항 번호 연결(FS 없음): 42: 요구사항 정의서 42(기준일 재무·실적)의 목표다. 10-10 목차 FS042는 시점 기반 관계 그래프이며 번호만 같다. 새 FS 번호·도메인 WBS를 만들지 않았고 폐기·구현·배정 완료가 아니다. 현재 WBS에는 대응 재무 업무가 없어 공통 계약 점검만 연결한다.

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| period | query | 필수 | string | 회계 기간. 허용 기간·항목·회계 기준·공급자를 팀이 확정해야 한다. 차트 기간과 독립이다. |

<a id="getcompanyissueimpact"></a>

## getCompanyIssueImpact · 기업 맥락 이슈 영향 경로 조회

기업 패널에서 여는 영향 경로다. 데이터에 없는 산업·제품 단계나 관계 유형을 만들지 않는다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/companies/{id}/issues/{issueId}/impact` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [ImpactPath](#schema-impactpath), 409: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, VERSION_UNAVAILABLE, SOURCE_UNAVAILABLE |
| FS/NFS | [FS022](../../system/out/feature-FS022.md) · [FS024](../../system/out/feature-FS024.md) · [FS055](../../system/out/feature-FS055.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-GRP-06](../../system/out/screen-D-GRP-06.md) · [D-GRP-05](../../system/out/screen-D-GRP-05.md) |
| WBS | 6.1.2, 6.11.1, 6.6.6, 6.6.7, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.5.1 |
| 프로토타입 대응 | 없음 |
| 목표와 차이 | 직접 대응 API 없음. 기업 패널/공개 회차의 현재 UI 동작은 목표 seam의 구현을 뜻하지 않는다. |
| 팀 확인 필요 | 재무 제공 항목·회계 기간·개인화 브리핑 생성 조건/재사용/대상 수 또는 영향 경로 데이터 모델은 해당 명세의 확인 필요 사항을 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| issueId | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| asOf | query | 선택 | string (date-time) | 이 시각 이전의 공개 자료만 사용한다. 오프셋 필수. |

<a id="getpersonalizedbriefing"></a>

## getPersonalizedBriefing · 고정 회차의 개인화 브리핑 조회

고정 회차의 개인화 브리핑 조회

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/briefings/{id}/personalized` |
| 권한·우선순위 | 회원(본인) · P2 |
| 요청 본문 | 없음 |
| 응답 | 200: [BriefingResponse](#schema-briefingresponse), 409: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse), 401: [ErrorResponse](#schema-errorresponse), 403: [ErrorResponse](#schema-errorresponse), 404: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, VERSION_UNAVAILABLE, SOURCE_UNAVAILABLE |
| FS/NFS | [FS036](../../system/out/feature-FS036.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-BRF-01](../../system/out/screen-D-BRF-01.md) · [D-BRF-02](../../system/out/screen-D-BRF-02.md) · [M-BRF-01](../../system/out/screen-M-BRF-01.md) |
| WBS | 6.1.2, 6.11.1, 6.8.9, 6.8.14 |
| 프로토타입 대응 | 없음 |
| 목표와 차이 | 직접 대응 API 없음. 기업 패널/공개 회차의 현재 UI 동작은 목표 seam의 구현을 뜻하지 않는다. |
| 팀 확인 필요 | 재무 제공 항목·회계 기간·개인화 브리핑 생성 조건/재사용/대상 수 또는 영향 경로 데이터 모델은 해당 명세의 확인 필요 사항을 팀이 확정해야 한다. |

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

<a id="getcompanygraphasof"></a>

## getCompanyGraphAsOf · 기업·기준 시점 중심 관계 그래프 조회

타임라인에서 고른 시각을 asOf로 명시하고 그 시점 이전에 공개된 기업·이슈 관계만 조회한다. 응답은 실제 사용한 공개 버전을 고정한다. 이후 공개된 문서나 관계를 섞지 않으며 자료 미상·미제공·조회 장애를 구분한다. depth는 실제 연결선의 hop 수다.

| 항목 | 계약 |
| --- | --- |
| 메서드·경로 | `GET /api/v1/companies/{id}/graph` |
| 권한·우선순위 | 공개 · P1 |
| 요청 본문 | 없음 |
| 응답 | 200: [GraphResponse](#schema-graphresponse), 404: [ErrorResponse](#schema-errorresponse), 409: [ErrorResponse](#schema-errorresponse), 422: [ErrorResponse](#schema-errorresponse), 500: [ErrorResponse](#schema-errorresponse), 503: [ErrorResponse](#schema-errorresponse) |
| 오류 코드 | INVALID_REQUEST, RESOURCE_NOT_FOUND, VERSION_UNAVAILABLE, SOURCE_UNAVAILABLE, INTERNAL_ERROR |
| FS/NFS | [FS038](../../system/out/feature-FS038.md) · [FS040](../../system/out/feature-FS040.md) · [FS041](../../system/out/feature-FS041.md) · [FS042](../../system/out/feature-FS042.md) · [FS055](../../system/out/feature-FS055.md) · [NFS001](../../system/out/feature-NFS001.md) · [NFS002](../../system/out/feature-NFS002.md) · [NFS004](../../system/out/feature-NFS004.md) · [NFS005](../../system/out/feature-NFS005.md) · [NFS008](../../system/out/feature-NFS008.md) |
| 화면 | [D-COM-01b](../../system/out/screen-D-COM-01b.md) · [D-COM-02](../../system/out/screen-D-COM-02.md) · [M-COM-01](../../system/out/screen-M-COM-01.md) · [D-COM-04](../../system/out/screen-D-COM-04.md) · [D-COM-05](../../system/out/screen-D-COM-05.md) · [D-COM-06](../../system/out/screen-D-COM-06.md) |
| WBS | 6.1.2, 6.11.1, 6.7.2, 6.7.3, 6.7.4, 6.7.5, 6.7.8, 6.7.10, 6.7.11, 6.7.12, 6.5.1 |
| 프로토타입 대응 | /api/companies/{id}/graph |
| 목표와 차이 | /api → /api/v1 경로 버전 및 공통 오류·요청 ID 적용., BFF는 현재 저장된 승인 자료를 문서 공개 시각으로 거른다. 목표는 asOf와 실제 사용한 불변 공개 버전을 함께 고정한다. |
| 팀 확인 필요 | 목차의 요구 번호 42는 기준일 재무·실적(요구 42)이며 FS042 시점 그래프와 의미가 다르다. 재무 폐기 선언이 없어 별도 유보하며 시점 그래프 의미의 승인 범위는 팀 최종 확인이 필요하다., 날짜 정밀도만 있는 사건을 정확한 조회 asOf로 바꾸는 기준과 이력 보존 기간을 팀이 확인해야 한다. |

명세 의미 구분: FS042: 목차·상세 FS042의 시점 기반 관계 그래프 의미다. 요구 42의 재무·실적 공급을 뜻하지 않으며 그 요구는 getCompanyFinancials에 요구 번호로만 연결한다.

### 요청 필드

| 이름 | 위치 | 필수 | 형식 | 설명 |
| --- | --- | --- | --- | --- |
| id | path | 필수 | string |  |
| asOf | query | 필수 | string (date-time) | 사건 선택에 따라 조회할 정확한 기준 시각. RFC 3339 오프셋이 필수다. |
| depth | query | 선택 | integer {1, 2} | 명세의 시점별 그래프 범위 1-hop 또는 2-hop. 운영상의 임의 페이지 상한과 구분한다. |
| graphVersion | query | 선택 | string | 조회할 불변 공개 버전 ID. round/asOf와 일치해야 한다. |
| X-Request-ID | header | 선택 | string | 전송별 추적 ID. 생략하면 서버가 생성한다. |

## 공통 스키마

nullable은 미제공/미판정이고 숫자 0 또는 빈 문자열로 대신하지 않는다. 필수 필드는 null 허용 여부와 별개다. JSON 필드 이름·중첩 참조의 정본은 OpenAPI다.

<a id="schema-activateresponse"></a>

### ActivateResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| activeVersionId | 필수 | string |  |
| previousActiveVersionId | 필수 | string / null |  |
| idempotent | 필수 | boolean |  |

<a id="schema-activationout"></a>

### ActivationOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| versionId | 필수 | string |  |
| previousVersionId | 필수 | string / null |  |
| at | 필수 | string |  |
| adminEmail | 필수 | string |  |
| reason | 필수 | string / null |  |
| action | 필수 | string {publish, activate, seed} |  |

<a id="schema-admininfo"></a>

### AdminInfo



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| email | 필수 | string |  |
| displayName | 필수 | string |  |
| role | 필수 | string |  |

<a id="schema-adminloginrequest"></a>

### AdminLoginRequest



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| email | 필수 | string |  |
| password | 필수 | string |  |

<a id="schema-adminsession"></a>

### AdminSession



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| authenticated | 필수 | boolean |  |
| expired | 필수 | boolean |  |
| expiredReason | 필수 | string {idle, absolute} / null |  |
| admin | 필수 | [AdminInfo](#schema-admininfo) / null |  |
| expiresAt | 필수 | string, null (date-time) |  |
| idleExpiresAt | 필수 | string (date-time) / null |  |
| idleTimeoutSeconds | 필수 | integer |  |
| absoluteTimeoutSeconds | 필수 | integer |  |
| csrfToken | 필수 | string, null | 인증 세션 쓰기에 사용하는 세션 결합 토큰. 무세션은 null. |

<a id="schema-aifeature"></a>

### AiFeature



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| feature | 필수 | string {chatbot, news-analysis, briefing, document-sentiment, briefing-outlook} | 내부 document-summary/semantic-verification은 news-analysis, 문서 기업 판정은 document-sentiment, 전망 판정은 briefing-outlook. 브리핑의 다른 생성 단계만 briefing에 집계한다. |
| label | 필수 | string |  |
| engine | 필수 | string |  |
| modelBacked | 필수 | boolean |  |
| requests | 필수 | integer | 기능별 접수 단위. chatbot=chat_jobs, news-analysis=summary document_analyses, document-sentiment=sentiment document_analyses, briefing=briefing_attempts, briefing-outlook=해당 시도의 outlook 단계. 멱등 재전송은 제외하며 기능 간 합산은 전체 요청 수가 아니다. |
| succeeded | 필수 | integer | 해당 기능 requests 모집단에서 성공으로 종결한 수. 권리 보류와 진행 중 요청을 임의로 포함하지 않는다. |
| failed | 필수 | integer | 해당 기능 requests 모집단에서 실패로 종결한 수. 권리 보류와 결과 불명확 호출을 모델 실패로 단정하지 않는다. |
| latencyMs | 필수 | [LatencyOut](#schema-latencyout) / null |  |
| usage | 필수 | [FeatureUsage](#schema-featureusage) |  |
| cost | 필수 | [FeatureCost](#schema-featurecost) |  |
| source | 필수 | string {measured, job-runner, ledger-db, document} |  |
| recentErrors | 필수 | [RecentError](#schema-recenterror)[] |  |
| note | 필수 | string |  |

<a id="schema-aiusageresponse"></a>

### AiUsageResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| asOf | 필수 | string (date-time) |  |
| window | 필수 | string {24h, 7d, 30d, all} |  |
| features | 필수 | [AiFeature](#schema-aifeature)[] |  |
| pastRuns | 필수 | [PastRun](#schema-pastrun)[] |  |
| cost | 필수 | [FeatureCost](#schema-featurecost) |  |

<a id="schema-approvalout"></a>

### ApprovalOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| source | 필수 | string {admin-review, review-rule} |  |
| label | 필수 | string |  |
| scope | 필수 | string |  |
| ruleId | 필수 | string / null | Publication rule that put content on the graph (e.g. 'R1@2'); also set when an admin approval and a rule meet in one event |

<a id="schema-articleout"></a>

### ArticleOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string, null |  |
| id | 필수 | string |  |
| publisher | 필수 | string / null |  |
| url | 필수 | string / null |  |
| publishedAt | 필수 | string (date-time) / null |  |
| relationType | 필수 | string {REPORTS, PROVIDES_BACKGROUND} / null |  |

<a id="schema-attemptout"></a>

### AttemptOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| n | 필수 | integer |  |
| trigger | 필수 | string {scheduler, admin} |  |
| startedAt | 필수 | string (date-time) |  |
| finishedAt | 필수 | string (date-time) / null |  |
| status | 필수 | string |  |
| failureReason | 필수 | string / null |  |
| adminEmail | 필수 | string / null |  |

<a id="schema-auditentry"></a>

### AuditEntry



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | integer |  |
| at | 필수 | string |  |
| actorKind | 필수 | string {admin, system} |  |
| actorId | 필수 | string |  |
| actorEmail | 필수 | string / null |  |
| action | 필수 | string |  |
| targetType | 필수 | string |  |
| targetId | 필수 | string / null |  |
| reason | 필수 | string / null |  |
| outcome | 필수 | string {ok, denied, failed} |  |
| detail | 필수 | object |  |

<a id="schema-auditpage"></a>

### AuditPage



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [AuditEntry](#schema-auditentry)[] |  |
| nextCursor | 필수 | string / null |  |

<a id="schema-basisout"></a>

### BasisOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| edgeId | 필수 | string |  |
| relationType | 필수 | string |  |
| sourceUrl | 필수 | string / null |  |
| verifiedAt | 필수 | string (date-time) / null |  |
| validFrom | 필수 | string / null |  |
| validUntil | 필수 | string / null |  |
| countries | 필수 | string[] |  |

<a id="schema-briefingcorrection"></a>

### BriefingCorrection



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | integer |  |
| eventId | 필수 | string / null |  |
| original | 필수 | string / null | The published text of the corrected item, kept as published |
| corrected | 필수 | string |  |
| reason | 필수 | string |  |
| createdAt | 필수 | string (date-time) |  |

<a id="schema-briefinggraphbasis"></a>

### BriefingGraphBasis

What a briefing's relationship graph is anchored to (FS032): the graph as it stood when the round was published.

``/api/graph?round=<id>`` and the node, edge, event, evidence and company reads that take the same ``round``
answer from that state, never from the newest graph. Any status but ``available`` has no graph to read.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| roundId | 필수 | string |  |
| date | 필수 | string (date) |  |
| edition | 필수 | string {morning, evening} |  |
| status | 필수 | string {available, suspended, unavailable, not_published} |  |
| message | 필수 | string / null | User-facing notice for every status but available |
| reason | 필수 | string / null | Admin-written reason, only for suspended rounds |
| publishedAt | 필수 | string (date-time) / null |  |
| dataAsOf | 필수 | string (date-time) / null | End of the round's data window (KST): the reference time of the relations and evidence shown |
| graphVersion | 필수 | string / null | Graph version the round was published from |
| keyIssueIds | 필수 | string[] | The round's key issues in rank order; empty unless available |
| companyIds | 필수 | string[] | Companies related to those issues; empty unless available |
| correctionCount | 필수 | integer | Corrections registered beside the published original |

<a id="schema-briefingitem"></a>

### BriefingItem



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| eventId | 필수 | string |  |
| eventTime | 필수 | string / null |  |
| timePrecision | 필수 | string {year, month, day, datetime, unknown} |  |
| companies | 필수 | [CompanyLink](#schema-companylink)[] |  |
| evidenceCount | 필수 | integer |  |
| sourceSupport | 필수 | [SourceSupportOut](#schema-sourcesupportout) |  |
| matchedCompanyIds | 필수 | string[] | 공통 회차에서는 빈 배열이다. 개인화 조회는 같은 발행본 중 본인의 기준 기업과 겹치는 기업 ID를 제공하며 새 사건이나 판정을 만들지 않는다. |
| rank | 필수 | integer | 1-based position inside the round |
| reason | 필수 | string | 핵심 이슈를 선정한 실제 근거를 설명한다. 중요도·동점 정책은 팀 확인 필요이며 투자 권유·가격 예측은 하지 않는다. |
| evidenceIds | 필수 | string[] |  |
| summary | 필수 | [AnalysisSummary](#schema-analysissummary) / [Unavailable](#schema-unavailable) |  |
| reportedAt | 필수 | string (date-time) / null | KST time of the newest article behind the issue (the time it entered the round's data window); only the date (YYYY-MM-DD) when the article carries no time. null on rounds published before it was stored. |
| documentSentiments | 필수 | object[] |  |
| documentSentiments[].articleId | 필수 | string |  |
| documentSentiments[].sentiment | 필수 | [DocumentSentiment](#schema-documentsentiment) |  |

<a id="schema-briefingmetadata"></a>

### BriefingMetadata



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| source | 필수 | string |  |
| asOf | 필수 | string (date-time) |  |
| graphVersion | 필수 | string, null | 공개 데이터는 반드시 실제 사용한 버전 ID를 제공한다. 개인 설정 등 비그래프 리소스만 null이다. |
| schedule | 필수 | [BriefingSchedule](#schema-briefingschedule) |  |
| selection | 필수 | [BriefingSelection](#schema-briefingselection) |  |
| requestId | 필수 | string |  |
| partial | 필수 | boolean |  |
| failures | 필수 | [SectionFailure](#schema-sectionfailure)[] |  |

<a id="schema-briefingnotice"></a>

### BriefingNotice



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| kind | 필수 | string {not_ready, failed, suspended} |  |
| message | 필수 | string |  |
| reason | 필수 | string / null | Admin-written reason, only for suspended rounds |
| at | 필수 | string / null |  |

<a id="schema-briefingpayload"></a>

### BriefingPayload

The immutable published original of a round (what users saw before any correction).

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| date | 필수 | string (date) |  |
| edition | 필수 | string {morning, evening} |  |
| scheduledAt | 필수 | string (date-time) |  |
| generatedAt | 필수 | string (date-time) |  |
| dataWindow | 필수 | [BriefingWindow](#schema-briefingwindow) |  |
| graphVersion | 필수 | string / null |  |
| reviewRevision | 필수 | integer |  |
| ruleRevision | 필수 | integer / null | Publication-rule log revision at publication; null for rounds published before it was recorded |
| items | 필수 | [BriefingItem](#schema-briefingitem)[] |  |
| references | 필수 | [BriefingReferences](#schema-briefingreferences) |  |
| emptyReason | 필수 | string / null |  |
| selectedFrom | 필수 | integer |  |
| marketVariables | 필수 | [MarketVariables](#schema-marketvariables) / null | Market indicators stored at generation (FS031); null on rounds published before they were collected |
| metadata | 필수 | [BriefingMetadata](#schema-briefingmetadata) |  |
| outlook | 필수 | [BriefingOutlook](#schema-briefingoutlook) / null |  |

<a id="schema-briefingreferences"></a>

### BriefingReferences



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| eventIds | 필수 | string[] |  |
| evidenceIds | 필수 | string[] |  |
| companyIds | 필수 | string[] |  |

<a id="schema-briefingresponse"></a>

### BriefingResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| date | 필수 | string (date) |  |
| edition | 필수 | string {morning, evening} |  |
| status | 필수 | string {published, not_ready, generating, failed, suspended} |  |
| scheduledAt | 필수 | string (date-time) |  |
| publishedAt | 필수 | string (date-time) / null |  |
| generatedAt | 필수 | string (date-time) / null |  |
| dataWindow | 필수 | [BriefingWindow](#schema-briefingwindow) / null |  |
| dataAsOf | 필수 | string (date-time) / null |  |
| graphVersion | 필수 | string / null |  |
| items | 필수 | [BriefingItem](#schema-briefingitem)[] |  |
| marketSummary | 필수 | [AnalysisSummary](#schema-analysissummary) / [Unavailable](#schema-unavailable) |  |
| marketVariables | 필수 | [MarketVariables](#schema-marketvariables) / [Unavailable](#schema-unavailable) | KOSPI, KOSDAQ and USD/KRW stored with the published round; unavailable (with the reason) when the round has none |
| sinceMorning | 필수 | [SinceMorning](#schema-sincemorning) / [Unavailable](#schema-unavailable) / null | Evening rounds only: key issues compared with the same day's published morning round; null for morning rounds |
| emptyReason | 필수 | string / null |  |
| corrections | 필수 | [BriefingCorrection](#schema-briefingcorrection)[] |  |
| notice | 필수 | [BriefingNotice](#schema-briefingnotice) / null |  |
| references | 필수 | [BriefingReferences](#schema-briefingreferences) |  |
| metadata | 필수 | [BriefingMetadata](#schema-briefingmetadata) |  |
| outlook | 필수 | [BriefingOutlook](#schema-briefingoutlook) / null |  |

<a id="schema-briefingroundref"></a>

### BriefingRoundRef



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| date | 필수 | string (date) |  |
| edition | 필수 | string {morning, evening} |  |
| status | 필수 | string {published, suspended} |  |
| publishedAt | 필수 | string (date-time) / null |  |

<a id="schema-briefingroundsresponse"></a>

### BriefingRoundsResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [BriefingRoundRef](#schema-briefingroundref)[] |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-briefingschedule"></a>

### BriefingSchedule



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| morning | 필수 | string |  |
| evening | 필수 | string |  |
| confirmed | 필수 | boolean |  |

<a id="schema-briefingselection"></a>

### BriefingSelection



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| basis | 필수 | string |  |
| reason | 필수 | string / null |  |

<a id="schema-briefingwindow"></a>

### BriefingWindow



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| start | 필수 | string / null | null = the first round of the service (no lower bound) |
| end | 필수 | string | Data cut-off = the round's scheduled time (KST) |
| openStart | 필수 | boolean |  |

<a id="schema-candidatearticle"></a>

### CandidateArticle



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string, null |  |
| articleId | 필수 | string |  |
| publisher | 필수 | string / null |  |
| url | 필수 | string / null |  |
| publishedAt | 필수 | string (date-time) / null |  |

<a id="schema-candidatecompany"></a>

### CandidateCompany



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| companyId | 필수 | string / null |  |
| name | 필수 | string |  |
| role | 필수 | string |  |

<a id="schema-candidatecounts"></a>

### CandidateCounts



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| total | 필수 | integer |  |
| active | 필수 | integer |  |
| inactive | 필수 | integer |  |
| allow | 필수 | integer |  |
| hold | 필수 | integer |  |
| reject | 필수 | integer |  |

<a id="schema-candidatedetail"></a>

### CandidateDetail



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| candidateId | 필수 | string |  |
| sourceVersion | 필수 | string | 이 상세 응답의 후보 AI 원천 버전. 결정 요청의 expectedSourceVersion으로 보낸다. |
| sourceRevision | 필수 | string | 이 상세 응답의 후보 AI 원천 revision. 결정 요청의 expectedSourceRevision으로 보낸다. |
| issueId | 필수 | string |  |
| status | 필수 | string {ALLOW, HOLD, REJECT} |  |
| active | 필수 | boolean |  |
| policyVersion | 필수 | string |  |
| action | 필수 | string |  |
| target | 필수 | string / null |  |
| eventTime | 필수 | string / null |  |
| companies | 필수 | [CandidateCompany](#schema-candidatecompany)[] |  |
| relationTypes | 필수 | string[] |  |
| evidenceCount | 필수 | integer |  |
| reasons | 필수 | string[] |  |
| onUserGraph | 필수 | boolean |  |
| decision | 필수 | [ReviewDecisionOut](#schema-reviewdecisionout) / null |  |
| rule | 필수 | [CandidateRule](#schema-candidaterule) / null |  |
| mention | 필수 | [CandidateMention](#schema-candidatemention) |  |
| articles | 필수 | [CandidateArticle](#schema-candidatearticle)[] |  |
| evidence | 필수 | [CandidateEvidence](#schema-candidateevidence)[] |  |
| relations | 필수 | [CandidateRelation](#schema-candidaterelation)[] |  |
| verification | 필수 | [VerificationOut](#schema-verificationout) |  |
| invalidationReason | 필수 | string / null |  |
| history | 필수 | [ReviewDecisionOut](#schema-reviewdecisionout)[] |  |
| graphDb | 필수 | string {reflected, pending, not_stored, unknown} |  |

<a id="schema-candidateevidence"></a>

### CandidateEvidence



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| articleId | 필수 | string |  |
| articleVersion | 필수 | string |  |
| start | 필수 | integer |  |
| end | 필수 | integer |  |
| quote | 필수 | string |  |
| articleTitle | 필수 | string / null |  |
| url | 필수 | string / null |  |

<a id="schema-candidatelist"></a>

### CandidateList



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [CandidateRow](#schema-candidaterow)[] |  |
| nextCursor | 필수 | string / null |  |
| counts | 필수 | object |  |
| asOf | 필수 | string (date-time) |  |

<a id="schema-candidatemention"></a>

### CandidateMention



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| mentionId | 필수 | string |  |
| action | 필수 | string |  |
| target | 필수 | string / null |  |
| eventTime | 필수 | string / null |  |
| period | 필수 | string / null |  |
| assertionStatus | 필수 | string / null |  |
| background | 필수 | boolean |  |
| countries | 필수 | string[] |  |
| keywords | 필수 | string[] |  |
| participants | 필수 | [CandidateCompany](#schema-candidatecompany)[] |  |

<a id="schema-candidaterelation"></a>

### CandidateRelation



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| relationId | 필수 | string |  |
| sourceVersion | 필수 | string | 이 relation AI 원천 버전. relation 결정 요청에 사용한다. |
| sourceRevision | 필수 | string | 이 relation AI 원천 revision. relation 결정 요청에 사용한다. |
| relationType | 필수 | string |  |
| source | 필수 | string |  |
| target | 필수 | string |  |
| role | 필수 | string / null |  |
| assertionStatus | 필수 | string / null |  |
| evidenceCount | 필수 | integer |  |
| onUserGraph | 필수 | boolean |  |
| decision | 필수 | [ReviewDecisionOut](#schema-reviewdecisionout) / null |  |

<a id="schema-candidaterow"></a>

### CandidateRow



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| candidateId | 필수 | string |  |
| issueId | 필수 | string |  |
| status | 필수 | string {ALLOW, HOLD, REJECT} |  |
| active | 필수 | boolean |  |
| policyVersion | 필수 | string |  |
| action | 필수 | string |  |
| target | 필수 | string / null |  |
| eventTime | 필수 | string / null |  |
| companies | 필수 | [CandidateCompany](#schema-candidatecompany)[] |  |
| relationTypes | 필수 | string[] |  |
| evidenceCount | 필수 | integer |  |
| reasons | 필수 | string[] |  |
| onUserGraph | 필수 | boolean |  |
| decision | 필수 | [ReviewDecisionOut](#schema-reviewdecisionout) / null |  |
| rule | 필수 | [CandidateRule](#schema-candidaterule) / null |  |

<a id="schema-candidaterule"></a>

### CandidateRule

A candidate a publication rule covers: whether it is on the user graph through the rule, and what it leaves out.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| ruleId | 필수 | string |  |
| applied | 필수 | boolean |  |
| notAppliedReason | 필수 | string {admin_decision, rule_disabled, not_published} / null |  |
| withheldParticipants | 필수 | integer[] | Indexes into the candidate's mention participants whose role is left out |
| withheldRelations | 필수 | string[] | Relation ids whose role is left out |
| droppedRelations | 필수 | string[] | Relation ids the rule does not publish at all (a FOLLOWS whose follow-side event did not occur yet) |

<a id="schema-chataction"></a>

### ChatAction



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| kind | 필수 | string |  |
| label | 필수 | string |  |

<a id="schema-chatapplied"></a>

### ChatApplied

What the answer was actually built on.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| companies | 필수 | [ChatAppliedItem](#schema-chatapplieditem)[] |  |
| issues | 필수 | [ChatAppliedItem](#schema-chatapplieditem)[] |  |
| period | 필수 | [ChatAppliedPeriod](#schema-chatappliedperiod) / null |  |
| graphVersion | 필수 | string / null |  |
| dataAsOf | 필수 | string (date-time) |  |
| questionOverrodeContext | 필수 | boolean | The question named other targets than the selection, so the question won |

<a id="schema-chatapplieditem"></a>

### ChatAppliedItem



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| label | 필수 | string |  |

<a id="schema-chatappliedperiod"></a>

### ChatAppliedPeriod



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| start | 필수 | string |  |
| end | 필수 | string |  |
| basis | 필수 | string {question, context, evidence} | question/context: asked for; evidence: no period asked, this is the publication span of the cited articles |
| expression | 필수 | string / null | The words of the question the period came from |

<a id="schema-chatchoice"></a>

### ChatChoice



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| label | 필수 | string |  |

<a id="schema-chatcontextitem"></a>

### ChatContextItem



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| kind | 필수 | string {company, issue, edge, evidence} |  |
| label | 필수 | string |  |

<a id="schema-chatcontextrequest"></a>

### ChatContextRequest

What the member had selected when asking: graph targets, optional evidence references and period.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| contextIds | 선택 | string[] | Company, issue, edge or evidence ids |
| evidenceIds | 선택 | string[] | Narrows the evidence to these references |
| period | 선택 | [ChatPeriod](#schema-chatperiod) / null | Explicit period of the selection; the question's own period wins |
| asOf | 선택 | string, null (date-time) |  |
| graphVersion | 선택 | string, null |  |

<a id="schema-chatconversation"></a>

### ChatConversation



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| session | 필수 | [ChatSessionResponse](#schema-chatsessionresponse) |  |
| jobs | 필수 | [ChatJob](#schema-chatjob)[] |  |

<a id="schema-chatcurrentresponse"></a>

### ChatCurrentResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| conversation | 필수 | [ChatConversation](#schema-chatconversation) / null |  |

<a id="schema-chatfailure"></a>

### ChatFailure



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| kind | 필수 | string {validation_failed, save_failed, result_lost, transient, permission_denied, internal} |  |
| reason | 필수 | string / null |  |
| message | 필수 | string |  |
| retry | 필수 | string {rerun, save_only} / null | What 'retry' would do: rerun the same job with its frozen context, or only save the kept verified result. null = not allowed. |

<a id="schema-chatfrozencontext"></a>

### ChatFrozenContext

The selection frozen when the question was first received.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [ChatContextItem](#schema-chatcontextitem)[] |  |
| evidenceCount | 필수 | integer |  |
| period | 필수 | [ChatPeriod](#schema-chatperiod) / null |  |
| asOf | 필수 | string, null (date-time) |  |
| graphVersion | 필수 | string, null |  |

<a id="schema-chatjob"></a>

### ChatJob



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| sessionId | 필수 | string |  |
| seq | 필수 | integer |  |
| question | 필수 | string |  |
| status | 필수 | string {queued, running, completed, failed, cancelled} |  |
| outcome | 필수 | string {answered, clarification, guidance, insufficient_evidence} / null |  |
| askedAt | 필수 | string (date-time) | UTC time the question was first received; relative dates are read against its KST day |
| context | 필수 | [ChatFrozenContext](#schema-chatfrozencontext) |  |
| failure | 필수 | [ChatFailure](#schema-chatfailure) / null |  |
| result | 필수 | [ChatResult](#schema-chatresult) / null | Only a saved result; null until the job is completed |
| runs | 필수 | integer | Executions started so far (a retry starts another) |
| createdAt | 필수 | string (date-time) |  |
| updatedAt | 필수 | string (date-time) |  |
| finishedAt | 필수 | string (date-time) / null |  |

<a id="schema-chatjobrequest"></a>

### ChatJobRequest



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| jobId | 필수 | string | Client-made idempotency key of this question (not a request-trace id). Resending it never asks twice. |
| question | 필수 | string |  |
| context | 선택 | [ChatContextRequest](#schema-chatcontextrequest) |  |

<a id="schema-chatperiod"></a>

### ChatPeriod



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| start | 필수 | string | Inclusive KST calendar day (ISO date) |
| end | 필수 | string |  |

<a id="schema-chatresult"></a>

### ChatResult



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| outcome | 필수 | string {answered, clarification, guidance, insufficient_evidence} |  |
| messageId | 필수 | string |  |
| answer | 필수 | string |  |
| reason | 필수 | string / null |  |
| sources | 필수 | string[] |  |
| citations | 필수 | [Citation](#schema-citation)[] |  |
| graphTargets | 필수 | [GraphTarget](#schema-graphtarget)[] |  |
| applied | 필수 | [ChatApplied](#schema-chatapplied) |  |
| choices | 필수 | [ChatChoice](#schema-chatchoice)[] | clarification: companies the member can pick (each becomes a new question) |
| action | 필수 | [ChatAction](#schema-chataction) / null | guidance: what the member can do to meet the missing condition |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-chatsessionresponse"></a>

### ChatSessionResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| createdAt | 필수 | string (date-time) |  |
| jobs | 필수 | integer |  |

<a id="schema-citation"></a>

### Citation



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| evidenceId | 필수 | string |  |
| quote | 필수 | string |  |
| articleId | 필수 | string |  |
| articleVersion | 필수 | string |  |
| start | 필수 | integer |  |
| end | 필수 | integer |  |
| articleTitle | 필수 | string / null |  |
| publisher | 필수 | string / null |  |
| publishedAt | 필수 | string (date-time) / null |  |
| url | 필수 | string / null |  |

<a id="schema-companydetail"></a>

### CompanyDetail



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| name | 필수 | string | 화면 표시용 기업명이다. 확인된 정식 법인명 legalName을 대신하지 않는다. |
| legalName | 필수 | string, null | 확인된 정식 법인명. 자료가 없으면 null이며 표시용 name을 복사하지 않는다. |
| market | 필수 | string, null | 확인된 상장 시장. 자료가 없으면 null이다. |
| representative | 필수 | string, null | 공식 기업 기준 자료에서 확인한 대표자명. 자료가 없으면 null이다. |
| foundedDate | 필수 | string, null (date) | 확인된 설립일(YYYY-MM-DD). 연도/월만 알려진 자료를 정확한 날짜로 추정하지 않으며 미확인 값은 null이다. |
| websiteUrl | 필수 | string, null (uri) | 확인된 공식 웹사이트의 절대 URI. 자료가 없으면 null이며 검색 결과 URL을 공식 주소로 추정하지 않는다. |
| ticker | 필수 | string / null |  |
| aliases | 필수 | string[] |  |
| sector | 필수 | string / null | 확인된 업종. 기존 sector 필드를 여섯 프로필 키 중 하나로 유지하며 자료가 없으면 null이다. |
| brandColor | 필수 | string / null | Company brand color `#RRGGBB`; null when the catalog has none. |
| logoUrl | 필수 | string / null | Same-origin logo path (`/logos/<file>`); null when the catalog has none. |
| directIssues | 필수 | [CompanyIssueRef](#schema-companyissueref)[] |  |
| structuralIssues | 필수 | [CompanyIssueRef](#schema-companyissueref)[] |  |
| summary | 필수 | [AnalysisSummary](#schema-analysissummary) / [Unavailable](#schema-unavailable) |  |
| holding | 필수 | boolean / null | null unless a member session is present |
| watch | 필수 | boolean / null | null unless a member session is present |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-companydocument"></a>

### CompanyDocument



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string, null |  |
| id | 필수 | string | Article id |
| publisher | 필수 | string / null |  |
| url | 필수 | string / null | Original article link; null when the source gives none |
| publishedAt | 필수 | string (date-time) / null |  |
| events | 필수 | [DocumentEventRef](#schema-documenteventref)[] | This company's approved events the article supports |
| quotes | 필수 | [DocumentQuote](#schema-documentquote)[] | Stored evidence quotes from this article for those events |
| sentiment | 필수 | [DocumentSentiment](#schema-documentsentiment) / null |  |
| documentVersion | 선택 | string, null |  |
| documentSummary | 선택 | [DocumentAnalysisSummary](#schema-documentanalysissummary) / null |  |
| analysisStatus | 선택 | [DocumentAnalysisStatus](#schema-documentanalysisstatus) / null |  |
| analysisProvenance | 선택 | [AnalysisProvenance](#schema-analysisprovenance) / null |  |
| resultVersion | 선택 | string, null | 요약이 있으면 요약 버전, 요약 없이 판정만 있으면 판정 버전. 미공개는 null. |
| kind | 필수 | string {news, disclosure} |  |

<a id="schema-companydocumentsresponse"></a>

### CompanyDocumentsResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [CompanyDocument](#schema-companydocument)[] | Distinct articles, newest publication first; undated last |
| metadata | 필수 | [Metadata](#schema-metadata) |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-companyissueref"></a>

### CompanyIssueRef



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| issueId | 필수 | string |  |
| eventTime | 필수 | string / null |  |
| timePrecision | 필수 | string {year, month, day, datetime, unknown} |  |
| role | 필수 | string / null |  |
| assertionStatus | 필수 | string / null |  |
| evidenceCount | 필수 | integer |  |
| basis | 필수 | [BasisOut](#schema-basisout)[] |  |

<a id="schema-companylink"></a>

### CompanyLink



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| name | 필수 | string |  |
| role | 필수 | string / null |  |
| roleUnconfirmed | 필수 | boolean |  |
| relationType | 필수 | string {INVOLVES, STRUCTURALLY_RELATED_TO} |  |

<a id="schema-companylistresponse"></a>

### CompanyListResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [CompanySummary](#schema-companysummary)[] |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-companymetrics"></a>

### CompanyMetrics



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| companyId | 필수 | string |  |
| source | 필수 | [QuoteSourceOut](#schema-quotesourceout) |  |
| asOf | 필수 | string (date-time) / null | Source time of the page the values came from; null when not given. |
| items | 필수 | [MetricOut](#schema-metricout)[] |  |

<a id="schema-companymetricsunavailable"></a>

### CompanyMetricsUnavailable



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| companyId | 필수 | string |  |
| reasonCode | 필수 | string {not_connected, unsupported_symbol, no_data} | 정상 자료 부재만 표현한다. 실제 인증·네트워크·형식 장애는 503 SOURCE_UNAVAILABLE이며 unavailable 성공으로 숨기지 않는다. |
| reason | 필수 | string |  |

<a id="schema-companyquote"></a>

### CompanyQuote



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| companyId | 필수 | string |  |
| source | 필수 | [QuoteSourceOut](#schema-quotesourceout) |  |
| quote | 필수 | [QuoteValues](#schema-quotevalues) |  |

<a id="schema-companyquoteunavailable"></a>

### CompanyQuoteUnavailable



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| companyId | 필수 | string |  |
| reasonCode | 필수 | string {not_connected, unsupported_symbol, no_data} | 정상 자료 부재만 표현한다. not_connected: 공급자가 의도적으로 비활성/미설정됨; unsupported_symbol: 지원하지 않는 종목; no_data: 공급자에 관측값 없음. 실제 인증·네트워크·형식 장애는 503 SOURCE_UNAVAILABLE이며 unavailable 성공으로 숨기지 않는다. |
| reason | 필수 | string |  |

<a id="schema-companyseriespoint"></a>

### CompanySeriesPoint



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| date | 필수 | string (date) |  |
| nodeViews | 필수 | integer |  |
| edgeSelections | 필수 | integer |  |
| issueSelections | 필수 | integer |  |
| aiQuestions | 필수 | integer |  |

<a id="schema-companystatrow"></a>

### CompanyStatRow



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| companyId | 필수 | string |  |
| name | 필수 | string |  |
| ticker | 필수 | string / null |  |
| watchlistMembers | 필수 | integer |  |
| holdingMembers | 필수 | integer |  |
| nodeViews | 필수 | integer |  |
| edgeSelections | 필수 | integer |  |
| aiQuestions | 필수 | integer |  |

<a id="schema-companysummary"></a>

### CompanySummary



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| name | 필수 | string |  |
| ticker | 필수 | string / null |  |
| aliases | 필수 | string[] |  |
| sector | 필수 | string / null |  |
| brandColor | 필수 | string / null | Company brand color `#RRGGBB`; null when the catalog has none. |
| logoUrl | 필수 | string / null | Same-origin logo path (`/logos/<file>`); null when the catalog has none. |
| issueCount | 필수 | integer |  |

<a id="schema-connectioninfo"></a>

### ConnectionInfo



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| mockPortfolioId | 필수 | string |  |
| label | 필수 | string |  |
| connectedAt | 필수 | string (date-time) |  |
| accountId | 필수 | string / null | null for connections stored before the account id was recorded |
| cash | 필수 | [MockCash](#schema-mockcash) / null | null when not provided; 0 is a real 0 |
| status | 필수 | string |  |

<a id="schema-connectionresponse"></a>

### ConnectionResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| mockPortfolioId | 필수 | string |  |
| label | 필수 | string |  |
| connectedAt | 필수 | string (date-time) |  |
| accountId | 필수 | string / null | null for connections stored before the account id was recorded |
| cash | 필수 | [MockCash](#schema-mockcash) / null | null when not provided; 0 is a real 0 |
| status | 필수 | string |  |
| holdingsCount | 필수 | integer |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-correctionout"></a>

### CorrectionOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | integer |  |
| seq | 필수 | integer |  |
| eventId | 필수 | string / null |  |
| original | 필수 | string / null |  |
| corrected | 필수 | string |  |
| reason | 필수 | string |  |
| createdAt | 필수 | string (date-time) |  |
| adminEmail | 필수 | string |  |

<a id="schema-correctionrequest"></a>

### CorrectionRequest



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| eventId | 선택 | string / null |  |
| correctedText | 필수 | string |  |
| reason | 필수 | string |  |

<a id="schema-dailyactivity"></a>

### DailyActivity



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| date | 필수 | string (date) | KST calendar day |
| activeUsers | 필수 | integer |  |
| nodeSelections | 필수 | integer |  |
| edgeSelections | 필수 | integer |  |
| briefingViews | 필수 | integer |  |
| aiQuestions | 필수 | integer |  |

<a id="schema-dashboard"></a>

### Dashboard



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| generatedAt | 필수 | string (date-time) |  |
| ledger | 필수 | [DashboardLedger](#schema-dashboardledger) |  |
| graph | 필수 | [DashboardGraph](#schema-dashboardgraph) |  |
| candidates | 필수 | [DashboardCandidates](#schema-dashboardcandidates) / null |  |
| jobs | 필수 | [DashboardJobs](#schema-dashboardjobs) |  |
| ai | 필수 | [DashboardAi](#schema-dashboardai) |  |
| briefings | 필수 | [DashboardBriefings](#schema-dashboardbriefings) |  |
| members | 필수 | [DashboardMembers](#schema-dashboardmembers) |  |
| audit | 필수 | [DashboardAudit](#schema-dashboardaudit) |  |

<a id="schema-dashboardai"></a>

### DashboardAi



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| window | 필수 | string |  |
| requests | 필수 | integer |  |
| succeeded | 필수 | integer |  |
| failed | 필수 | integer |  |
| features | 필수 | [DashboardAiFeature](#schema-dashboardaifeature)[] |  |

<a id="schema-dashboardaifeature"></a>

### DashboardAiFeature



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| feature | 필수 | string |  |
| label | 필수 | string |  |
| requests | 필수 | integer |  |
| failed | 필수 | integer |  |

<a id="schema-dashboardaudit"></a>

### DashboardAudit



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| last24h | 필수 | integer |  |

<a id="schema-dashboardbriefings"></a>

### DashboardBriefings



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| latest | 필수 | [RoundOut](#schema-roundout)[] |  |
| delayedOrFailed | 필수 | integer |  |

<a id="schema-dashboardcandidates"></a>

### DashboardCandidates



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| allow | 필수 | integer |  |
| hold | 필수 | integer |  |
| reject | 필수 | integer |  |
| inactive | 필수 | integer |  |
| holdPendingReview | 필수 | integer |  |

<a id="schema-dashboardgraph"></a>

### DashboardGraph



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| activeVersionId | 필수 | string / null |  |
| activatedAt | 필수 | string (date-time) / null |  |
| versionCount | 필수 | integer |  |
| activeVersion | 필수 | [GraphVersionOut](#schema-graphversionout) / null |  |
| reviewRevision | 필수 | integer |  |
| reviewDecisions | 필수 | integer |  |
| rules | 필수 | [ReviewRuleOut](#schema-reviewruleout)[] |  |
| graphDb | 필수 | [GraphDbStatus](#schema-graphdbstatus) / null |  |

<a id="schema-dashboardjobs"></a>

### DashboardJobs



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| running | 필수 | integer |  |
| queued | 필수 | integer |  |
| failed24h | 필수 | integer |  |
| active | 필수 | [JobOut](#schema-jobout) / null |  |
| recent | 필수 | [JobOut](#schema-jobout)[] |  |

<a id="schema-dashboardledger"></a>

### DashboardLedger



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string {connected, unavailable} |  |
| error | 필수 | [ErrorInfo](#schema-errorinfo) / null |  |

<a id="schema-dashboardmembers"></a>

### DashboardMembers



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| registered | 필수 | integer |  |
| activeMemberSessions | 필수 | integer |  |
| activeGuestSessions | 필수 | integer |  |
| source | 필수 | string |  |

<a id="schema-datawindow"></a>

### DataWindow



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| start | 필수 | string / null |  |
| end | 필수 | string |  |
| openStart | 필수 | boolean |  |

<a id="schema-decisionrequest"></a>

### DecisionRequest



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| decision | 필수 | string {allow, reject} |  |
| reason | 필수 | string |  |
| relationId | 선택 | string / null |  |
| expectedRevision | 필수 | integer | 상세 응답에서 확인한 결정 대상(candidate 또는 relation)의 앱 검수 revision. |
| expectedSourceVersion | 필수 | string | 상세 응답에서 확인한 결정 대상의 AI 원천 버전. 현재 값과 다르면 REVISION_CONFLICT/409. |
| expectedSourceRevision | 필수 | string | 상세 응답에서 확인한 결정 대상의 AI 원천 revision. 현재 값과 다르면 REVISION_CONFLICT/409. |

<a id="schema-decisionresponse"></a>

### DecisionResponse

허용은 재검증 접수다. 결정 요청 자체로 공개 상태를 바꾸지 않는다.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| candidateId | 필수 | string |  |
| decision | 필수 | string {revalidation_requested, rejected} |  |
| revision | 필수 | integer |  |
| jobId | 필수 | string, null |  |
| publicChanged | 필수 | boolean |  |

<a id="schema-dislikepage"></a>

### DislikePage



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [DislikeRow](#schema-dislikerow)[] |  |
| nextCursor | 필수 | string / null |  |
| total | 필수 | integer |  |

<a id="schema-dislikerow"></a>

### DislikeRow



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| at | 필수 | string |  |
| feature | 필수 | string {chatbot_answer, briefing_round, briefing_issue} |  |
| featureLabel | 필수 | string |  |
| targetId | 필수 | string |  |
| targetLabel | 필수 | string |  |
| reason | 필수 | string / null |  |
| voter | 필수 | string | Pseudonymous id |
| sessionId | 필수 | string / null | Chat session of a chatbot answer, for opening its transcript |

<a id="schema-documenteventref"></a>

### DocumentEventRef



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| eventId | 필수 | string |  |
| relationType | 필수 | string {REPORTS, PROVIDES_BACKGROUND} / null |  |

<a id="schema-documentquote"></a>

### DocumentQuote



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| evidenceId | 필수 | string |  |
| quote | 필수 | string |  |
| quoteVerified | 필수 | boolean / null |  |

<a id="schema-edgedetail"></a>

### EdgeDetail



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| relationType | 필수 | string {INVOLVES, STRUCTURALLY_RELATED_TO, FOLLOWS, SHARES_ISSUE} |  |
| derived | 필수 | boolean |  |
| directed | 필수 | boolean |  |
| source | 필수 | [EndpointRef](#schema-endpointref) |  |
| target | 필수 | [EndpointRef](#schema-endpointref) |  |
| role | 필수 | string / null |  |
| summary | 필수 | string | Same short Korean noun phrase as the graph edge label. |
| roles | 필수 | string[] |  |
| assertionStatus | 필수 | string / null |  |
| evidenceIds | 필수 | string[] |  |
| basis | 필수 | [BasisOut](#schema-basisout)[] |  |
| relationIds | 필수 | string[] |  |
| verification | 필수 | [Verification](#schema-verification) |  |
| via | 필수 | [ViaIssue](#schema-viaissue)[] |  |
| explanation | 필수 | string / null |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-endpointref"></a>

### EndpointRef



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| kind | 필수 | string {company, issue} |  |
| label | 필수 | string |  |

<a id="schema-errorbody"></a>

### ErrorBody

details에는 승인된 검증 정보만 제공한다. 스택·원문·개인정보·내부 파일 경로를 넣지 않는다.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| code | 필수 | [ErrorCode](#schema-errorcode) |  |
| message | 필수 | string |  |
| requestId | 필수 | string |  |
| retryable | 필수 | boolean |  |
| details | 선택 | object |  |
| details.fields | 선택 | object[] |  |
| details.fields[].field | 필수 | string |  |
| details.fields[].reason | 필수 | string |  |
| details.resourceId | 선택 | string |  |
| details.currentRevision | 선택 | integer |  |

<a id="schema-errorinfo"></a>

### ErrorInfo



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| code | 필수 | string |  |
| message | 필수 | string |  |

<a id="schema-errorresponse"></a>

### ErrorResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| error | 필수 | [ErrorBody](#schema-errorbody) |  |

<a id="schema-eventdetail"></a>

### EventDetail



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| id | 필수 | string |  |
| eventTime | 필수 | string / null |  |
| timePrecision | 필수 | string {year, month, day, datetime, unknown} |  |
| period | 필수 | string / null |  |
| mentions | 필수 | [MentionOut](#schema-mentionout)[] |  |
| articles | 필수 | [ArticleOut](#schema-articleout)[] |  |
| relations | 필수 | [RelationOut](#schema-relationout)[] |  |
| companies | 필수 | [CompanyLink](#schema-companylink)[] |  |
| sourceSupport | 필수 | [SourceSupportOut](#schema-sourcesupportout) |  |
| fieldDecisions | 필수 | [FieldDecisionOut](#schema-fielddecisionout)[] |  |
| evidenceIds | 필수 | string[] |  |
| follows | 필수 | [Follows](#schema-follows) |  |
| approval | 필수 | [ApprovalOut](#schema-approvalout) / null |  |
| summary | 필수 | [AnalysisSummary](#schema-analysissummary) / [Unavailable](#schema-unavailable) |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-eventlistmetadata"></a>

### EventListMetadata



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| source | 필수 | string |  |
| asOf | 필수 | string (date-time) |  |
| graphVersion | 필수 | string / null |  |
| total | 필수 | integer |  |
| excludedUnknownTime | 필수 | integer | Events without an approved event time left out of `items` by from/to |
| latestEventTime | 필수 | string / null | Newest approved event time in the company/all scope, ignoring from/to |
| latestReportedAt | 필수 | string (date-time) / null | Newest article publication in the same scope, ignoring from/to |

<a id="schema-eventlistresponse"></a>

### EventListResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [EventSummary](#schema-eventsummary)[] |  |
| unknownTimeItems | 필수 | [EventSummary](#schema-eventsummary)[] | With from/to: events without an approved event time whose reportedAt (KST date) falls in the range, newest report first. Without from/to they are in `items` and this is empty. |
| metadata | 필수 | [EventListMetadata](#schema-eventlistmetadata) |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-eventsummary"></a>

### EventSummary



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| id | 필수 | string |  |
| action | 필수 | string / null |  |
| target | 필수 | string / null |  |
| eventTime | 필수 | string / null |  |
| timePrecision | 필수 | string {year, month, day, datetime, unknown} |  |
| period | 필수 | string / null |  |
| companyIds | 필수 | string[] |  |
| relationTypes | 필수 | string {INVOLVES, STRUCTURALLY_RELATED_TO}[] (uniqueItems) | 이 응답의 요청 companyId와 사건 사이의 직접 승인 간선 유형만 포함한다. items/unknownTimeItems 모두 같은 공개 graphVersion/asOf를 사용한다. 두 유형이 함께 있으면 각각 한 번 포함한다. companyId 없음·직접 승인 간선 없음·간접 2-hop 전용 사건은 []다. companyIds 전체의 관계 합집합, 감성/영향 방향, 기업 간 공급/경쟁 유형이 아니다. |
| articleCount | 필수 | integer |  |
| reportedAt | 필수 | string (date-time) / null | Latest publication time among the event's articles; never used as the event time |

<a id="schema-evidencearticle"></a>

### EvidenceArticle



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string, null |  |
| publisher | 필수 | string / null |  |
| url | 필수 | string / null |  |
| publishedAt | 필수 | string (date-time) / null |  |

<a id="schema-evidenceresponse"></a>

### EvidenceResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| quote | 필수 | string |  |
| start | 필수 | integer |  |
| end | 필수 | integer |  |
| articleId | 필수 | string |  |
| articleVersion | 필수 | string |  |
| article | 필수 | [EvidenceArticle](#schema-evidencearticle) / null |  |
| quoteVerified | 필수 | boolean / null |  |
| eventIds | 필수 | string[] |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |
| sentiment | 필수 | [DocumentSentiment](#schema-documentsentiment) / null |  |
| documentVersion | 선택 | string, null |  |
| documentSummary | 선택 | [DocumentAnalysisSummary](#schema-documentanalysissummary) / null |  |
| analysisStatus | 선택 | [DocumentAnalysisStatus](#schema-documentanalysisstatus) / null |  |
| analysisProvenance | 선택 | [AnalysisProvenance](#schema-analysisprovenance) / null |  |
| resultVersion | 선택 | string, null |  |

<a id="schema-featurecost"></a>

### FeatureCost



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string {unavailable, estimated} | 기존 계약의 추정 가능 상태. 실제 청구액 확인 여부는 actual의 null 여부로 별도 판단한다. |
| actual | 필수 | number / null | 청구 내역 등으로 확인된 실제 비용만 기록한다. 미보고·불명확 시 null이며 추정액을 복사하지 않는다. |
| estimated | 필수 | number / null | 확인 가능한 토큰·단가로 계산한 추정 비용. 실제 청구액과 별도로 유지하며 계산할 수 없으면 null. |
| currency | 필수 | string / null |  |
| reason | 필수 | string |  |

<a id="schema-featureusage"></a>

### FeatureUsage



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| modelCalls | 필수 | integer / null | 실제 외부 모델 전송이 확인된 live 시도 수. 미영수증·결과 불명확 시도로 전체 수를 확정할 수 없으면 null. replay/save_only 제외. |
| inputTokens | 필수 | integer / null | 확인된 입력 토큰 합계. 일부 시도에서 미보고되어 합계를 확정할 수 없으면 null. |
| outputTokens | 필수 | integer / null | 확인된 출력 토큰 합계. 일부 시도에서 미보고되어 합계를 확정할 수 없으면 null. |
| replayCalls | 필수 | integer | 저장된 판정 재사용 횟수. 모델 호출 횟수와 구분한다. |
| retries | 필수 | integer | 최초 실행 뒤 새 앱/도메인 시도 또는 추가 모델 호출을 동반한 재시도 수. 같은 키 재전송·poll·모델 재호출 없는 recover·save_only는 제외하고 한 재시도 단위는 한 번만 센다. |

<a id="schema-feedbackday"></a>

### FeedbackDay



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| date | 필수 | string (date) |  |
| up | 필수 | integer |  |
| down | 필수 | integer |  |
| rate | 필수 | number / null |  |

<a id="schema-feedbackfeaturestat"></a>

### FeedbackFeatureStat



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| feature | 필수 | string {chatbot_answer, briefing_round, briefing_issue} |  |
| label | 필수 | string |  |
| up | 필수 | integer |  |
| down | 필수 | integer |  |
| total | 필수 | integer |  |
| rate | 필수 | number / null |  |
| sampleHidden | 필수 | boolean |  |
| days | 필수 | [FeedbackDay](#schema-feedbackday)[] |  |

<a id="schema-feedbackitem"></a>

### FeedbackItem



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| feature | 필수 | string {chatbot_answer, briefing_round, briefing_issue} |  |
| targetId | 필수 | string |  |
| targetVersion | 필수 | string / null | Result version the rating is linked to; null for chatbot answers (an answer never changes) |
| value | 필수 | string {up, down, none} |  |
| reason | 필수 | string / null |  |

<a id="schema-feedbacklist"></a>

### FeedbackList



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [FeedbackItem](#schema-feedbackitem)[] |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-feedbacksummary"></a>

### FeedbackSummary



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| window | 필수 | string {7d, 30d, all} |  |
| start | 필수 | string / null | Applied KST start day (inclusive); overrides window when start or end is set |
| end | 필수 | string / null | Applied KST end day (inclusive) |
| asOf | 필수 | string (date-time) |  |
| minSample | 필수 | integer |  |
| features | 필수 | [FeedbackFeatureStat](#schema-feedbackfeaturestat)[] |  |
| unsupported | 필수 | [UnsupportedFeedbackFeature](#schema-unsupportedfeedbackfeature)[] |  |
| basis | 필수 | string |  |

<a id="schema-feedbackvote"></a>

### FeedbackVote

The rating the voter wants to end up with (FS066-01, D08). ``none`` takes the rating back, so sending the
same request again never toggles anything.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| feature | 필수 | string {chatbot_answer, briefing_round, briefing_issue} |  |
| targetId | 필수 | string |  |
| value | 필수 | string {up, down, none} |  |
| targetVersion | 선택 | string / null | Result version the voter saw (a briefing's graphVersion). A different current version is 409. |
| reason | 선택 | string / null | Optional, only with a dislike |

<a id="schema-fielddecisionout"></a>

### FieldDecisionOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| candidateId | 필수 | string / null |  |
| mentionId | 필수 | string / null |  |
| outcomes | 필수 | [FieldOutcomeOut](#schema-fieldoutcomeout)[] |  |

<a id="schema-fieldoutcomeout"></a>

### FieldOutcomeOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| field | 필수 | string |  |
| decision | 필수 | string |  |
| reason | 필수 | string / null |  |

<a id="schema-fieldverdictout"></a>

### FieldVerdictOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| field | 필수 | string |  |
| decision | 필수 | string |  |
| reason | 필수 | string |  |

<a id="schema-flushresult"></a>

### FlushResult



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| completedProjectionJobs | 필수 | integer |  |

<a id="schema-followref"></a>

### FollowRef



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| id | 필수 | string |  |
| eventTime | 필수 | string / null |  |
| timePrecision | 필수 | string {year, month, day, datetime, unknown} |  |

<a id="schema-follows"></a>

### Follows



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| previous | 필수 | [FollowRef](#schema-followref)[] |  |
| next | 필수 | [FollowRef](#schema-followref)[] |  |

<a id="schema-graphdbstatus"></a>

### GraphDbStatus



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string {reflected, pending, mismatch, unavailable} |  |
| pendingJobs | 필수 | integer / null |  |
| oldestPendingAt | 필수 | string (date-time) / null |  |
| lastCompletedAt | 필수 | string (date-time) / null |  |
| neo4j | 필수 | [Neo4jStatus](#schema-neo4jstatus) / null |  |
| checkedAt | 필수 | string (date-time) |  |

<a id="schema-graphdbversionstate"></a>

### GraphDbVersionState



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string {reflected, pending, unknown} |  |
| pendingJobsAtCreation | 필수 | integer / null |  |
| note | 필수 | string / null |  |

<a id="schema-graphedge"></a>

### GraphEdge



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| source | 필수 | string |  |
| target | 필수 | string |  |
| relationType | 필수 | string {INVOLVES, STRUCTURALLY_RELATED_TO, FOLLOWS, SHARES_ISSUE} |  |
| role | 필수 | string / null |  |
| summary | 필수 | string | Short Korean noun phrase for the edge label, derived from approved data only. |
| assertionStatus | 필수 | string / null |  |
| derived | 필수 | boolean |  |
| via | 필수 | string[] | Shared issue ids; derived edges only |
| evidenceIds | 필수 | string[] | Evidence ids of the approved relations behind the edge (same as `GET /api/graph/edges/{id}` evidenceIds); empty for derived edges. |

<a id="schema-graphmetadata"></a>

### GraphMetadata



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| source | 필수 | string |  |
| asOf | 필수 | string (date-time) |  |
| graphVersion | 필수 | string, null | 공개 데이터는 반드시 실제 사용한 버전 ID를 제공한다. 개인 설정 등 비그래프 리소스만 null이다. |
| mode | 필수 | string {all, personal} |  |
| truncated | 필수 | boolean |  |
| emptyReason | 필수 | string / null |  |
| focusCompanyIds | 필수 | string[] |  |
| depth | 필수 | integer / null | Requested hop count; null when omitted (whole connected component). |
| limit | 필수 | integer |  |
| requestId | 필수 | string |  |
| partial | 필수 | boolean |  |
| failures | 필수 | [SectionFailure](#schema-sectionfailure)[] |  |
| personalFilter | 필수 | string, null {all, holdings, watchlist, None} |  |

<a id="schema-graphnode"></a>

### GraphNode



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| kind | 필수 | string {company, issue} |  |
| label | 필수 | string |  |
| isFocus | 필수 | boolean |  |
| holding | 필수 | boolean |  |
| watch | 필수 | boolean |  |
| brandColor | 필수 | string / null | Company brand color `#RRGGBB` from the catalog; null for issues or when unset. |
| logoUrl | 필수 | string / null | Same-origin path of the company logo (`/logos/<file>`); null for issues or when unset. |
| eventTime | 필수 | string / null |  |
| timePrecision | 필수 | string {year, month, day, datetime, unknown} / null |  |
| action | 필수 | string / null |  |
| target | 필수 | string / null |  |
| evidenceCount | 필수 | integer / null | Issue nodes: number of evidence ids of the issue (length of `GET /api/events/{id}` evidenceIds); null for companies. |
| geography | 필수 | string, null {domestic, international, None} | 이슈에는 검증된 국내/국제 값이 필수다. 기업은 null이다. 미판정 이슈를 임의 분류하지 않고 공개 검증 단계에서 제외하거나 보완한다. |

<a id="schema-graphresponse"></a>

### GraphResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| nodes | 필수 | [GraphNode](#schema-graphnode)[] |  |
| edges | 필수 | [GraphEdge](#schema-graphedge)[] |  |
| metadata | 필수 | [GraphMetadata](#schema-graphmetadata) |  |

<a id="schema-graphtarget"></a>

### GraphTarget



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| kind | 필수 | string {company, issue, edge} |  |

<a id="schema-graphversionlist"></a>

### GraphVersionList



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| activeVersionId | 필수 | string / null |  |
| items | 필수 | [GraphVersionOut](#schema-graphversionout)[] |  |
| activations | 필수 | [ActivationOut](#schema-activationout)[] |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-graphversionout"></a>

### GraphVersionOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| sequence | 필수 | integer |  |
| kind | 필수 | string {seed, ledger} |  |
| createdAt | 필수 | string (date-time) |  |
| createdBy | 필수 | string |  |
| reason | 필수 | string / null |  |
| sourceLabel | 필수 | string |  |
| policyVersion | 필수 | string / null |  |
| issueCount | 필수 | integer |  |
| relationCount | 필수 | integer |  |
| articleCount | 필수 | integer |  |
| candidateCount | 필수 | integer / null |  |
| sha256 | 필수 | string |  |
| bytes | 필수 | integer |  |
| active | 필수 | boolean |  |
| activatedAt | 필수 | string (date-time) / null |  |
| graphDb | 필수 | [GraphDbVersionState](#schema-graphdbversionstate) |  |

<a id="schema-holdingout"></a>

### HoldingOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| companyId | 필수 | string |  |
| name | 필수 | string |  |
| ticker | 필수 | string / null |  |
| quantity | 필수 | number | Mock quantity |
| avgPrice | 필수 | number | Mock average purchase price |
| avgPriceCurrency | 필수 | string / null | Currency of avgPrice; null when unknown (connections stored before it was recorded). |
| quote | 필수 | [HoldingQuote](#schema-holdingquote) / [Unavailable](#schema-unavailable) | Price read at valuation.calculatedAt |
| marketValue | 필수 | number / null | quantity x quote.price in quote.currency; null when the price is unavailable (never 0) |
| weight | 필수 | number / null | marketValue / total stock market value (cash excluded), 0..1; null when it cannot be calculated (see valuation.weightUnavailableCode) |

<a id="schema-holdingquote"></a>

### HoldingQuote



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| price | 필수 | number |  |
| currency | 필수 | string |  |
| asOf | 필수 | string (date-time) / null | Provider time of the price |
| sourceName | 필수 | string |  |

<a id="schema-indicatorbaseline"></a>

### IndicatorBaseline



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| value | 필수 | number |  |
| date | 필수 | string (date) | KST date of the previous trading day the change is measured against |
| at | 필수 | string / null | Exact observation time when the baseline is an intraday value (the rate); null for a daily close |

<a id="schema-ingestbaseline"></a>

### IngestBaseline

The checkpoint the next article-processing run starts from: the start time of the latest run that
finished normally, also when it found nothing new. Failed and cancelled runs never move it.
``unresolved_failures`` counts article files whose latest run failed or was cancelled.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| at | 필수 | string / null |  |
| jobId | 필수 | string / null |  |
| outcome | 필수 | string {collected, empty} / null |  |
| newArticles | 필수 | integer / null |  |
| unresolvedFailures | 필수 | integer |  |

<a id="schema-ingestoutcome"></a>

### IngestOutcome

What one ``ingest-run`` established (FS058). ``outcome`` is None while the run is queued or running.
``collected``: new articles were processed. ``empty``: the run finished normally and found nothing new
(a success, not a failure). ``failed``/``cancelled``: nothing is confirmed, so no count is recorded
and the baseline stays where it was.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| outcome | 필수 | string {collected, empty, failed, cancelled} / null |  |
| newArticles | 필수 | integer / null |  |
| duplicateArticles | 필수 | integer / null |  |
| baselineBefore | 필수 | string / null |  |
| baselineAfter | 필수 | string / null |  |
| baselineAdvanced | 필수 | boolean |  |

<a id="schema-insightcompanydetail"></a>

### InsightCompanyDetail



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| window | 필수 | string {7d, 30d, all} |  |
| asOf | 필수 | string (date-time) |  |
| companyId | 필수 | string |  |
| name | 필수 | string |  |
| ticker | 필수 | string / null |  |
| inCatalog | 필수 | boolean |  |
| watchlistMembers | 필수 | integer |  |
| holdingMembers | 필수 | integer |  |
| nodeViews | 필수 | integer |  |
| edgeSelections | 필수 | integer |  |
| issueSelections | 필수 | integer |  |
| aiQuestions | 필수 | integer |  |
| viewers | 필수 | integer |  |
| minSample | 필수 | integer |  |
| series | 필수 | [CompanySeriesPoint](#schema-companyseriespoint)[] |  |
| note | 필수 | string |  |

<a id="schema-insightcompanyranking"></a>

### InsightCompanyRanking



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| window | 필수 | string {7d, 30d, all} |  |
| asOf | 필수 | string (date-time) |  |
| totalCompanies | 필수 | integer |  |
| items | 필수 | [CompanyStatRow](#schema-companystatrow)[] |  |
| holdingsNote | 필수 | string |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-insightsoverview"></a>

### InsightsOverview



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| window | 필수 | string |  |
| asOf | 필수 | string (date-time) |  |
| minSample | 필수 | integer |  |
| metrics | 필수 | [StatsMetric](#schema-statsmetric)[] |  |
| feedback | 필수 | [OverviewFeedback](#schema-overviewfeedback) |  |
| members | 필수 | [OverviewMembers](#schema-overviewmembers) |  |

<a id="schema-issuecounts"></a>

### IssueCounts



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| approved | 필수 | integer |  |
| relations | 필수 | integer |  |
| articles | 필수 | integer |  |

<a id="schema-jobcreate"></a>

### JobCreate



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| kind | 필수 | string {ingest, revalidate, project} |  |
| reason | 필수 | string |  |
| sourceId | 선택 | string, null |  |
| candidateIds | 선택 | string[] |  |

<a id="schema-jobcreated"></a>

### JobCreated



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| job | 필수 | [JobOut](#schema-jobout) |  |
| deduplicated | 필수 | boolean |  |

<a id="schema-joberror"></a>

### JobError



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| code | 필수 | string |  |
| message | 필수 | string |  |

<a id="schema-jobfailure"></a>

### JobFailure



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| jobId | 필수 | string |  |
| label | 필수 | string |  |
| finishedAt | 필수 | string (date-time) / null |  |
| code | 필수 | string / null |  |
| message | 필수 | string / null |  |

<a id="schema-joblist"></a>

### JobList



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [JobOut](#schema-jobout)[] |  |
| active | 필수 | [JobOut](#schema-jobout) / null |  |
| lock | 필수 | [JobLock](#schema-joblock) |  |
| ingest | 필수 | [IngestBaseline](#schema-ingestbaseline) |  |
| retryRule | 필수 | string |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-joblock"></a>

### JobLock



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| locked | 필수 | boolean |  |
| jobId | 필수 | string / null |  |
| reason | 필수 | string / null |  |

<a id="schema-jobout"></a>

### JobOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| kind | 필수 | string {ingest, revalidate, project} |  |
| label | 필수 | string |  |
| status | 필수 | string {queued, running, succeeded, failed, cancelled} |  |
| reason | 필수 | string |  |
| requestedBy | 필수 | string |  |
| requestedAt | 필수 | string (date-time) |  |
| startedAt | 필수 | string (date-time) / null |  |
| finishedAt | 필수 | string (date-time) / null |  |
| durationSeconds | 필수 | number / null |  |
| retryOf | 필수 | string / null |  |
| cancelRequested | 필수 | boolean |  |
| recovered | 필수 | boolean |  |
| retry | 필수 | [RetryState](#schema-retrystate) |  |
| ingest | 필수 | [IngestOutcome](#schema-ingestoutcome) / null |  |
| report | 필수 | [RunReport](#schema-runreport) / null |  |
| flush | 필수 | [FlushResult](#schema-flushresult) / null |  |
| error | 필수 | [JobError](#schema-joberror) / null |  |
| ledgerBefore | 필수 | [LedgerCounts](#schema-ledgercounts) / null |  |
| ledgerAfter | 필수 | [LedgerCounts](#schema-ledgercounts) / null |  |

<a id="schema-jobretry"></a>

### JobRetry



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| reason | 필수 | string |  |

<a id="schema-latencyout"></a>

### LatencyOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| avg | 필수 | number |  |
| p95 | 필수 | number |  |
| max | 필수 | number |  |

<a id="schema-ledgercounts"></a>

### LedgerCounts



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| capturedAt | 필수 | string (date-time) |  |
| candidates | 필수 | object |  |
| issues | 필수 | integer |  |
| relations | 필수 | integer |  |
| pendingProjections | 필수 | integer / null |  |

<a id="schema-ledgerref"></a>

### LedgerRef



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| database | 필수 | string |  |
| checkedAt | 필수 | string (date-time) |  |

<a id="schema-loginrequest"></a>

### LoginRequest



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| email | 선택 | string |  |
| password | 선택 | string |  |

<a id="schema-marketindicator"></a>

### MarketIndicator

One indicator as it stood when the round was generated. ``status`` separates what each card may claim:
``ok`` and ``delayed`` carry a value (``delayed`` = the newest value the source had is older than the round expects),
``unavailable`` = the source answered but has no value for this point in time (or is not connected),
``failed`` = the request itself failed (network, rate limit, unknown format).

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string {kospi, kosdaq, usdkrw} |  |
| label | 필수 | string |  |
| unit | 필수 | string {pt, KRW} |  |
| status | 필수 | string {ok, delayed, unavailable, failed} |  |
| value | 필수 | number / null |  |
| valueKind | 필수 | string {close, latest} / null | close = the session's closing value; latest = the last observation before the cut-off |
| observedDate | 필수 | string / null | KST date of the value actually used |
| observedAt | 필수 | string (date-time) / null | KST time of the value actually used; null for a daily close |
| baseline | 필수 | [IndicatorBaseline](#schema-indicatorbaseline) / null |  |
| change | 필수 | number / null |  |
| changeRate | 필수 | number / null | change / baseline.value as a fraction (0.0123 = +1.23%) |
| source | 필수 | [QuoteSourceOut](#schema-quotesourceout) / null |  |
| reasonCode | 필수 | string {not_connected, unsupported_symbol, no_data, auth_failed, temporary_failure, format_changed, internal} / null |  |
| reason | 필수 | string / null |  |

<a id="schema-marketvariables"></a>

### MarketVariables

The three market indicators stored with a published round; never changed after publication.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| referenceAt | 필수 | string (date-time) | The round's scheduled time (KST) |
| rateCutoffAt | 필수 | string (date-time) | Latest time an observation could have (morning 07:40, evening 18:05, KST) |
| collectedAt | 필수 | string (date-time) |  |
| indicators | 필수 | [MarketIndicator](#schema-marketindicator)[] |  |

<a id="schema-maskingreport"></a>

### MaskingReport



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| rules | 필수 | string[] |  |
| counts | 필수 | object | Replacements made in this response, per kind |

<a id="schema-memberaction"></a>

### MemberAction



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| at | 필수 | string |  |
| action | 필수 | string {member.block, member.unblock} |  |
| reason | 필수 | string / null |  |
| adminEmail | 필수 | string / null |  |

<a id="schema-memberactivity"></a>

### MemberActivity



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| sessions | 필수 | integer |  |
| graphSelections | 필수 | integer |  |
| aiQuestions | 필수 | integer |  |
| briefingViews | 필수 | integer |  |

<a id="schema-membercounts"></a>

### MemberCounts



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| all | 필수 | integer |  |
| active | 필수 | integer |  |
| blocked | 필수 | integer |  |

<a id="schema-memberdetail"></a>

### MemberDetail



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| member | 필수 | [MemberRow](#schema-memberrow) |  |
| onboardingCompleted | 필수 | boolean |  |
| tutorialCompleted | 필수 | boolean |  |
| watchlistCount | 필수 | integer |  |
| holdingCount | 필수 | integer |  |
| accountConnected | 필수 | boolean |  |
| feedbackUp | 필수 | integer |  |
| feedbackDown | 필수 | integer |  |
| history | 필수 | [MemberAction](#schema-memberaction)[] |  |

<a id="schema-memberlist"></a>

### MemberList



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [MemberRow](#schema-memberrow)[] |  |
| nextCursor | 필수 | string / null |  |
| counts | 필수 | [MemberCounts](#schema-membercounts) |  |

<a id="schema-memberrow"></a>

### MemberRow



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string | Pseudonymous id |
| emailMasked | 필수 | string |  |
| signupMethod | 필수 | string |  |
| createdAt | 필수 | string (date-time) |  |
| lastActiveAt | 필수 | string (date-time) / null |  |
| status | 필수 | string {active, blocked} |  |
| activity | 필수 | [MemberActivity](#schema-memberactivity) |  |

<a id="schema-memberstatusresult"></a>

### MemberStatusResult



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| changed | 필수 | boolean | False when the member already had that status (the call is idempotent) |
| detail | 필수 | [MemberDetail](#schema-memberdetail) |  |

<a id="schema-mentionout"></a>

### MentionOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| mentionId | 필수 | string |  |
| articleId | 필수 | string |  |
| action | 필수 | string |  |
| target | 필수 | string / null |  |
| eventTime | 필수 | string / null |  |
| timePrecision | 필수 | string {year, month, day, datetime, unknown} |  |
| period | 필수 | string / null |  |
| assertionStatus | 필수 | string |  |
| participants | 필수 | [ParticipantOut](#schema-participantout)[] |  |
| evidenceIds | 필수 | string[] |  |
| background | 필수 | boolean |  |

<a id="schema-metadata"></a>

### Metadata



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| source | 필수 | string |  |
| asOf | 필수 | string (date-time) |  |
| graphVersion | 필수 | string, null | 공개 데이터는 반드시 실제 사용한 버전 ID를 제공한다. 개인 설정 등 비그래프 리소스만 null이다. |
| requestId | 필수 | string |  |
| partial | 필수 | boolean |  |
| failures | 필수 | [SectionFailure](#schema-sectionfailure)[] |  |

<a id="schema-metricout"></a>

### MetricOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| code | 필수 | string {marketValue, per, eps, pbr, bps, dividendYieldRatio, dividend, foreignRate} |  |
| label | 필수 | string |  |
| value | 필수 | string | As the source formats it (e.g. `1,609조 1,882억`, `12.35배`); never computed here. |
| basis | 필수 | string / null | The source's reference period for this value (e.g. `2026.06.`), when given. |

<a id="schema-mockcash"></a>

### MockCash

예수금 of a mock profile. The field holding it is null when the mock does not provide it (not 0).

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| amount | 필수 | number |  |
| currency | 필수 | string |  |

<a id="schema-mockholdingout"></a>

### MockHoldingOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| companyId | 필수 | string |  |
| name | 필수 | string |  |
| quantity | 필수 | number |  |
| avgPrice | 필수 | number |  |
| avgPriceCurrency | 필수 | string / null |  |

<a id="schema-mockportfoliolistresponse"></a>

### MockPortfolioListResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [MockPortfolioOption](#schema-mockportfoliooption)[] |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-mockportfoliooption"></a>

### MockPortfolioOption



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| label | 필수 | string |  |
| accountId | 필수 | string |  |
| holdingsCount | 필수 | integer |  |

<a id="schema-mockprofileresponse"></a>

### MockProfileResponse

FS062: one project mock profile with its account id, cash and holdings (no real brokerage account).

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| label | 필수 | string |  |
| accountId | 필수 | string |  |
| cash | 필수 | [MockCash](#schema-mockcash) / null | null when the mock does not provide cash; 0 is a real 0 |
| asOf | 필수 | string (date-time) / null | As-of time of the mock values when the mock gives one |
| holdings | 필수 | [MockHoldingOut](#schema-mockholdingout)[] |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-neo4jstatus"></a>

### Neo4jStatus



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string {reachable, unreachable} |  |
| issuesInLedger | 필수 | integer |  |
| issuesProjected | 필수 | integer / null |  |
| missingIssueIds | 필수 | string[] |  |
| staleIssueIds | 필수 | string[] |  |
| error | 필수 | [ErrorInfo](#schema-errorinfo) / null |  |

<a id="schema-observationout"></a>

### ObservationOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| target | 필수 | string |  |
| check | 필수 | string |  |
| choice | 필수 | string |  |

<a id="schema-overview"></a>

### Overview



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| asOf | 필수 | string (date-time) |  |
| ledger | 필수 | [LedgerRef](#schema-ledgerref) |  |
| policy | 필수 | [PolicyInfo](#schema-policyinfo) |  |
| candidates | 필수 | [CandidateCounts](#schema-candidatecounts) |  |
| issues | 필수 | [IssueCounts](#schema-issuecounts) |  |
| review | 필수 | [ReviewCounts](#schema-reviewcounts) |  |
| projection | 필수 | [GraphDbStatus](#schema-graphdbstatus) |  |
| publication | 필수 | [PublicationState](#schema-publicationstate) |  |
| jobs | 필수 | [OverviewJobs](#schema-overviewjobs) |  |
| runs | 필수 | [PastRun](#schema-pastrun)[] |  |

<a id="schema-overviewfeedback"></a>

### OverviewFeedback



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| up | 필수 | integer |  |
| down | 필수 | integer |  |
| rate | 필수 | number / null |  |
| sampleHidden | 필수 | boolean |  |

<a id="schema-overviewjobs"></a>

### OverviewJobs

Analysis jobs next to the ledger state: what is in progress and what failed (details: jobs tab).

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| running | 필수 | integer |  |
| queued | 필수 | integer |  |
| failed24h | 필수 | integer |  |
| lastFailure | 필수 | [JobFailure](#schema-jobfailure) / null |  |
| ingest | 필수 | [IngestBaseline](#schema-ingestbaseline) |  |

<a id="schema-overviewmembers"></a>

### OverviewMembers



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| registered | 필수 | integer |  |
| active | 필수 | integer |  |
| blocked | 필수 | integer |  |

<a id="schema-participantout"></a>

### ParticipantOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| companyId | 필수 | string / null |  |
| name | 필수 | string |  |
| role | 필수 | string / null |  |
| roleUnconfirmed | 필수 | boolean |  |

<a id="schema-pastrun"></a>

### PastRun



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| runId | 필수 | string / null |  |
| label | 필수 | string |  |
| policyGroup | 필수 | string {strict-web, relaxed-no-web, admin-job} |  |
| source | 필수 | string {ledger-db, document, job-runner} |  |
| processed | 필수 | integer / null |  |
| approved | 필수 | integer / null |  |
| held | 필수 | integer / null |  |
| rejected | 필수 | integer / null |  |
| pending | 필수 | integer / null |  |
| errorCount | 필수 | integer / null |  |
| usage | 필수 | [UsageOut](#schema-usageout) |  |

<a id="schema-policyinfo"></a>

### PolicyInfo



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| version | 필수 | string / null |  |
| decisionPolicy | 필수 | object / null |  |
| webVerification | 필수 | boolean |  |
| validationModel | 필수 | string / null |  |

<a id="schema-portfolioconnectrequest"></a>

### PortfolioConnectRequest



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| mockPortfolioId | 필수 | string |  |

<a id="schema-portfolioresponse"></a>

### PortfolioResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| connected | 필수 | boolean |  |
| connection | 필수 | [ConnectionInfo](#schema-connectioninfo) / null |  |
| holdings | 필수 | [HoldingOut](#schema-holdingout)[] |  |
| mockAsOf | 필수 | string / null | As-of time of the mock quantities, prices and cash |
| valuation | 필수 | [PortfolioValuation](#schema-portfoliovaluation) / null | null when no account is connected |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-portfoliovaluation"></a>

### PortfolioValuation



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| calculatedAt | 필수 | string (date-time) | Calculation time (when the prices were read); distinct from mockAsOf |
| currency | 필수 | string / null | Currency of totalMarketValue; null when it cannot be summed |
| totalMarketValue | 필수 | number / null | Sum of holding market values, cash excluded |
| weightStatus | 필수 | string {available, unavailable} |  |
| weightUnavailableCode | 필수 | string {missing_price, mixed_currency, zero_total} / null |  |
| weightUnavailableReason | 필수 | string / null |  |

<a id="schema-pricepoint"></a>

### PricePoint



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| time | 필수 | string | Bar time (ISO 8601 with the exchange offset). |
| open | 필수 | number |  |
| high | 필수 | number |  |
| low | 필수 | number |  |
| close | 필수 | number |  |
| volume | 필수 | number / null |  |

<a id="schema-priceseries"></a>

### PriceSeries



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| companyId | 필수 | string |  |
| period | 필수 | string {1d, 1w, 1m, 1y} |  |
| source | 필수 | [QuoteSourceOut](#schema-quotesourceout) |  |
| currency | 필수 | string |  |
| interval | 필수 | string {5m, 1h, 1d, 1wk} | 공급된 가격 봉 해상도다. 기간별로 고정이며 1d=5m, 1w=1h, 1m=1d, 1y=1wk(주봉)다. 조회 기간과 구분하고 from/to 및 자료 기준 시각을 함께 표시한다. 목표 해상도를 제공하지 못하면 다른 해상도를 이 필드로 위장하지 않고 unavailable을 반환한다. |
| points | 필수 | [PricePoint](#schema-pricepoint)[] | Oldest first. |

<a id="schema-priceseriesunavailable"></a>

### PriceSeriesUnavailable



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| companyId | 필수 | string |  |
| period | 필수 | string {1d, 1w, 1m, 1y} |  |
| reasonCode | 필수 | string {not_connected, unsupported_symbol, no_data} | 정상 자료 부재만 표현한다. no_data는 목표 봉 해상도(1d=5m, 1w=1h, 1m=1d, 1y=1wk)의 관측값이 공급자에 없는 경우를 포함한다. 실제 인증·네트워크·형식 장애는 503 SOURCE_UNAVAILABLE이며 unavailable 성공으로 숨기지 않는다. |
| reason | 필수 | string |  |

<a id="schema-publicationstate"></a>

### PublicationState



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| activeVersionId | 필수 | string / null |  |
| ledgerMatchesActive | 필수 | boolean |  |
| issuesOnlyInLedger | 필수 | string[] |  |
| issuesOnlyInActive | 필수 | string[] |  |

<a id="schema-publishresponse"></a>

### PublishResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| version | 필수 | [GraphVersionOut](#schema-graphversionout) |  |
| previousActiveVersionId | 필수 | string / null |  |

<a id="schema-quotesourceout"></a>

### QuoteSourceOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| provider | 필수 | string {toss, yahoo, naver} |  |
| name | 필수 | string |  |
| official | 필수 | boolean | false for the unofficial keyless public endpoint |
| delayNote | 필수 | string / null | Set when quotes from this source may be delayed. |
| symbol | 필수 | string | Provider symbol the values were fetched with (e.g. `005930.KS`). |
| url | 필수 | string / null | Provider page for the symbol to cross-check, when known. |

<a id="schema-quotevalues"></a>

### QuoteValues



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| currency | 필수 | string |  |
| price | 필수 | number |  |
| asOf | 필수 | string (date-time) / null | Provider time of the price (ISO 8601 with offset); null when not given. |
| previousClose | 필수 | number / null |  |
| change | 필수 | number / null | price - previousClose |
| changeRate | 필수 | number / null | (price - previousClose) / previousClose, a fraction |
| dayHigh | 필수 | number / null |  |
| dayLow | 필수 | number / null |  |
| volume | 필수 | number / null |  |
| fiftyTwoWeekHigh | 필수 | number / null |  |
| fiftyTwoWeekLow | 필수 | number / null |  |
| marketCap | 필수 | number / null | Only when computable from the provider (price x sharesOutstanding). |
| sharesOutstanding | 필수 | number / null |  |
| derived | 필수 | string[] |  |

<a id="schema-reasonrequest"></a>

### ReasonRequest



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| reason | 필수 | string |  |

<a id="schema-recenterror"></a>

### RecentError



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| at | 필수 | string |  |
| code | 필수 | string / null |  |
| message | 필수 | string / null |  |

<a id="schema-recommendationresponse"></a>

### RecommendationResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| basis | 필수 | string | 추천의 실제 근거 기준. 이슈 수·분류 등의 선정 규칙은 팀 확인 필요하며 매수 권유나 수익률 예상이 아니다. |
| items | 필수 | [RecommendedCompany](#schema-recommendedcompany)[] |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |
| groups | 필수 | object[] | 산업·테마 추천은 실제 제공 데이터가 있을 때만 구성한다. 없으면 해당 그룹 status=unavailable과 사유를 제공한다. |
| groups[].kind | 필수 | string {industry, theme} |  |
| groups[].status | 필수 | string {available, unavailable, failed} |  |
| groups[].reason | 필수 | string, null |  |
| groups[].items | 필수 | object[] |  |
| groups[].items[].id | 필수 | string |  |
| groups[].items[].name | 필수 | string |  |
| groups[].items[].companyIds | 필수 | string[] |  |
| groups[].items[].evidenceIds | 필수 | string[] |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-recommendedcompany"></a>

### RecommendedCompany



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| company | 필수 | [CompanySummary](#schema-companysummary) |  |
| reason | 필수 | string |  |

<a id="schema-relationout"></a>

### RelationOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| edgeId | 필수 | string / null | Graph edge id; null for article-to-issue relations |
| relationType | 필수 | string |  |
| source | 필수 | string |  |
| target | 필수 | string |  |
| role | 필수 | string / null |  |
| roleUnconfirmed | 필수 | boolean |  |
| assertionStatus | 필수 | string / null |  |
| evidenceIds | 필수 | string[] |  |

<a id="schema-retrystate"></a>

### RetryState



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| allowed | 필수 | boolean |  |
| code | 필수 | string {allowed, succeeded, in_progress, superseded, newer_attempt, duplicate_running, other_running, dataset_missing} |  |
| reason | 필수 | string |  |
| blockedBy | 필수 | string / null |  |

<a id="schema-reviewcounts"></a>

### ReviewCounts



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| revision | 필수 | integer |  |
| decisions | 필수 | integer |  |
| allowed | 필수 | integer |  |
| rejected | 필수 | integer |  |
| holdPendingReview | 필수 | integer |  |
| ruleCandidates | 필수 | integer | Candidates on the user graph through a publication rule right now |
| ruleEvents | 필수 | integer | Events on the user graph that exist only because of a publication rule |

<a id="schema-reviewdecisionout"></a>

### ReviewDecisionOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | integer |  |
| targetType | 필수 | string {candidate, relation} |  |
| targetId | 필수 | string |  |
| decision | 필수 | string {allow, reject} |  |
| reason | 필수 | string |  |
| adminEmail | 필수 | string |  |
| decidedAt | 필수 | string (date-time) |  |
| revision | 필수 | integer |  |
| origin | 필수 | string {admin, snapshot-migration} |  |

<a id="schema-reviewruleout"></a>

### ReviewRuleOut

A publication rule (``review_rules.py``); the id carries its version, e.g. ``R1@2``.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| id | 필수 | string |  |
| summary | 필수 | string |  |
| enabled | 필수 | boolean |  |
| defaultEnabled | 필수 | boolean |  |
| changedAt | 필수 | string (date-time) / null |  |
| changedBy | 필수 | string / null |  |
| reason | 필수 | string / null |  |
| eligible | 필수 | integer | HOLD candidates of the active version the rule covers (ignoring the switch and admin decisions) |
| publishedCandidates | 필수 | integer |  |
| publishedEvents | 필수 | integer |  |
| history | 필수 | [RuleChangeOut](#schema-rulechangeout)[] |  |

<a id="schema-rounddetail"></a>

### RoundDetail



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| date | 필수 | string (date) |  |
| edition | 필수 | string {morning, evening} |  |
| scheduledAt | 필수 | string (date-time) |  |
| dataWindow | 필수 | [DataWindow](#schema-datawindow) |  |
| status | 필수 | string {scheduled, missing, generating, verifying, published, failed, suspended} |  |
| stages | 필수 | [StagesOut](#schema-stagesout) |  |
| failureReason | 필수 | string / null |  |
| generatedAt | 필수 | string (date-time) / null |  |
| publishedAt | 필수 | string (date-time) / null |  |
| graphVersion | 필수 | string / null |  |
| reviewRevision | 필수 | integer / null |  |
| itemCount | 필수 | integer / null |  |
| trigger | 필수 | string {scheduler, admin} / null |  |
| attempts | 필수 | integer |  |
| delayed | 필수 | boolean |  |
| correctionCount | 필수 | integer |  |
| suspension | 필수 | [SuspensionOut](#schema-suspensionout) / null |  |
| reprocessable | 필수 | boolean |  |
| blockedReason | 필수 | string / null |  |
| published | 필수 | [BriefingPayload](#schema-briefingpayload) / null |  |
| corrections | 필수 | [CorrectionOut](#schema-correctionout)[] |  |
| attemptsLog | 필수 | [AttemptOut](#schema-attemptout)[] |  |

<a id="schema-roundlist"></a>

### RoundList



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [RoundOut](#schema-roundout)[] |  |
| schedule | 필수 | [RoundSchedule](#schema-roundschedule) |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-roundout"></a>

### RoundOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| date | 필수 | string (date) |  |
| edition | 필수 | string {morning, evening} |  |
| scheduledAt | 필수 | string (date-time) |  |
| dataWindow | 필수 | [DataWindow](#schema-datawindow) |  |
| status | 필수 | string {scheduled, missing, generating, verifying, published, failed, suspended} |  |
| stages | 필수 | [StagesOut](#schema-stagesout) |  |
| failureReason | 필수 | string / null |  |
| generatedAt | 필수 | string (date-time) / null |  |
| publishedAt | 필수 | string (date-time) / null |  |
| graphVersion | 필수 | string / null |  |
| reviewRevision | 필수 | integer / null |  |
| itemCount | 필수 | integer / null |  |
| trigger | 필수 | string {scheduler, admin} / null |  |
| attempts | 필수 | integer |  |
| delayed | 필수 | boolean |  |
| correctionCount | 필수 | integer |  |
| suspension | 필수 | [SuspensionOut](#schema-suspensionout) / null |  |
| reprocessable | 필수 | boolean |  |
| blockedReason | 필수 | string / null |  |

<a id="schema-roundschedule"></a>

### RoundSchedule



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| morning | 필수 | string |  |
| evening | 필수 | string |  |
| timezone | 필수 | string |  |

<a id="schema-roundstat"></a>

### RoundStat



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| roundId | 필수 | string |  |
| date | 필수 | string (date) |  |
| edition | 필수 | string {morning, evening} |  |
| views | 필수 | integer |  |
| viewers | 필수 | integer |  |
| issueOpens | 필수 | integer |  |
| likes | 필수 | integer |  |
| dislikes | 필수 | integer |  |

<a id="schema-rulechangeout"></a>

### RuleChangeOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | integer |  |
| enabled | 필수 | boolean |  |
| reason | 필수 | string |  |
| adminEmail | 필수 | string |  |
| changedAt | 필수 | string (date-time) |  |

<a id="schema-rulelist"></a>

### RuleList



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [ReviewRuleOut](#schema-reviewruleout)[] |  |
| asOf | 필수 | string (date-time) |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-ruleswitchrequest"></a>

### RuleSwitchRequest



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| enabled | 필수 | boolean |  |
| reason | 필수 | string |  |

<a id="schema-ruleswitchresponse"></a>

### RuleSwitchResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| rule | 필수 | [ReviewRuleOut](#schema-reviewruleout) |  |
| idempotent | 필수 | boolean |  |
| reviewRevision | 필수 | integer |  |

<a id="schema-runreport"></a>

### RunReport



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| runId | 필수 | string / null |  |
| processed | 필수 | integer |  |
| skipped | 필수 | integer |  |
| approved | 필수 | integer |  |
| held | 필수 | integer |  |
| rejected | 필수 | integer |  |
| pending | 필수 | integer |  |
| errorCount | 필수 | integer |  |
| errors | 필수 | object[] |  |
| collectionErrorCount | 필수 | integer |  |
| collectionErrors | 필수 | object[] |  |
| elapsedSeconds | 필수 | number |  |
| executionMode | 필수 | string / null |  |
| usage | 필수 | [UsageOut](#schema-usageout) |  |

<a id="schema-sessionresponse"></a>

### SessionResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| authenticated | 필수 | boolean |  |
| kind | 필수 | string {anonymous, guest, member} |  |
| user | 필수 | [UserInfo](#schema-userinfo) / null |  |
| setup | 필수 | [SetupState](#schema-setupstate) / null |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |
| csrfToken | 필수 | string, null | 인증 세션 쓰기에 사용하는 세션 결합 토큰. 무세션은 null. |
| expiresAt | 필수 | string, null (date-time) |  |

<a id="schema-settingsresponse"></a>

### SettingsResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| mode | 필수 | string {assets, watchlist} |  |
| watchlistIds | 필수 | string[] |  |
| tutorialCompleted | 필수 | boolean |  |
| completed | 필수 | boolean |  |
| investor | 필수 | boolean / null | null until the member answers the onboarding question. |
| version | 필수 | integer |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-settingsupdate"></a>

### SettingsUpdate

Unset fields keep their stored value; ``version`` must equal the stored version unless the request
changes nothing (a resent request is answered with the stored settings).

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| version | 필수 | integer |  |
| mode | 선택 | string {assets, watchlist} / null |  |
| watchlistIds | 선택 | string[] / null |  |
| tutorialCompleted | 선택 | boolean / null |  |
| completed | 선택 | boolean / null |  |
| investor | 선택 | boolean / null | Answer to 'do you invest in stocks now?' |

<a id="schema-setupstate"></a>

### SetupState

Guests: ``completed`` is always false (they have no settings); ``tutorialCompleted`` is kept on the
guest session only.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| completed | 필수 | boolean |  |
| tutorialCompleted | 필수 | boolean |  |

<a id="schema-signuprequest"></a>

### SignupRequest

필수 입력·이메일 중복·필수 약관·승인 버전·실제 동의 여부는 서버에서 검증한다. 이름/비밀번호 정책과 가입 직후 인증 상태는 팀 확인 필요다.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| email | 필수 | string |  |
| password | 필수 | string |  |
| displayName | 선택 | string |  |
| agreements | 필수 | object[] | 조회한 승인 약관의 ID·버전별 실제 동의 상태. 필요한 동의를 서버에서 다시 검증한다. |
| agreements[].id | 필수 | string |  |
| agreements[].version | 필수 | string |  |
| agreements[].accepted | 필수 | boolean |  |

<a id="schema-sincemorning"></a>

### SinceMorning

Key issues of an evening round compared with the same day's published morning round, oldest first.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| morningRoundId | 필수 | string |  |
| morningPublishedAt | 필수 | string (date-time) / null |  |
| morningDataAsOf | 필수 | string |  |
| items | 필수 | [SinceMorningItem](#schema-sincemorningitem)[] |  |

<a id="schema-sincemorningitem"></a>

### SinceMorningItem



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| eventId | 필수 | string |  |
| eventTime | 필수 | string / null |  |
| timePrecision | 필수 | string {year, month, day, datetime, unknown} |  |
| reportedAt | 필수 | string (date-time) / null | As on the key issue: KST time, only the date when the article has no time, null when not stored |
| companyNames | 필수 | string[] | Names of the companies linked to the issue when its round was published (from the stored key issue) |
| change | 필수 | string {new, continuing, dropped} | new = not among the morning round's key issues; continuing = in both rounds (new evidence since the morning put it in this round's window); dropped = only in the morning round |
| rank | 필수 | integer / null | Rank in this round; null when dropped |
| morningRank | 필수 | integer / null | Rank in the morning round; null when new |
| evidenceCount | 필수 | integer / null | Evidence in this round; null when dropped |
| morningEvidenceCount | 필수 | integer / null | Evidence in the morning round; null when new |

<a id="schema-socialprovidersresponse"></a>

### SocialProvidersResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [SocialProvider](#schema-socialprovider)[] | 개별 페이지의 회원 인증 제공자 목록이다. 전체 커서 순회 결과는 google/kakao 각각 한 번이며 페이지마다 두 항목 모두를 강제하지 않는다. |
| nextCursor | 필수 | string, null |  |

<a id="schema-sourcesupportout"></a>

### SourceSupportOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| articleCount | 필수 | integer |  |
| knownLineageCount | 필수 | integer / null |  |
| unknownLineageArticles | 필수 | string[] |  |
| independentSourceCount | 필수 | integer / null |  |
| duplicateGroups | 필수 | string[][] |  |

<a id="schema-stageout"></a>

### StageOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string {pending, running, done, failed, skipped} |  |
| at | 필수 | string / null |  |

<a id="schema-stagesout"></a>

### StagesOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| generate | 필수 | [StageOut](#schema-stageout) |  |
| verify | 필수 | [StageOut](#schema-stageout) |  |
| publish | 필수 | [StageOut](#schema-stageout) |  |

<a id="schema-statsmetric"></a>

### StatsMetric



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| key | 필수 | string |  |
| group | 필수 | string {usage, interest, ai} |  |
| label | 필수 | string |  |
| kind | 필수 | string {count, ratio} |  |
| unit | 필수 | string | Unit of the count, or of numerator and denominator |
| definition | 필수 | string | How the figure is computed, shown next to it |
| count | 필수 | integer / null | kind=count |
| numerator | 필수 | integer / null | kind=ratio |
| denominator | 필수 | integer / null | kind=ratio |
| rate | 필수 | number / null | 0..1; null for counts and for ratios below the sample threshold |
| sampleHidden | 필수 | boolean | True when the denominator is below minSample, so only counts are shown |

<a id="schema-statssummary"></a>

### StatsSummary



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| window | 필수 | string {7d, 30d, all} |  |
| asOf | 필수 | string (date-time) |  |
| since | 필수 | string / null |  |
| minSample | 필수 | integer |  |
| membersScope | 필수 | string | Which members the onboarding figure covers |
| metrics | 필수 | [StatsMetric](#schema-statsmetric)[] |  |
| trend | 필수 | [DailyActivity](#schema-dailyactivity)[] |  |
| rounds | 필수 | [RoundStat](#schema-roundstat)[] |  |

<a id="schema-suspensionout"></a>

### SuspensionOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| reason | 필수 | string |  |
| at | 필수 | string |  |
| adminEmail | 필수 | string |  |

<a id="schema-suspensionrequest"></a>

### SuspensionRequest



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| action | 필수 | string {suspend, resume} |  |
| reason | 필수 | string |  |

<a id="schema-telemetryaccepted"></a>

### TelemetryAccepted



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| accepted | 필수 | integer |  |

<a id="schema-telemetrybatch"></a>

### TelemetryBatch



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| events | 필수 | [TelemetryEvent](#schema-telemetryevent)[] |  |

<a id="schema-telemetryevent"></a>

### TelemetryEvent

One user action. Only these fields exist; anything else (e-mail, free text) is rejected.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| type | 필수 | string {screen_view, graph_node_select, graph_edge_select, briefing_view, briefing_issue_open} |  |
| screen | 선택 | string {main, briefing} / null |  |
| targetId | 선택 | string / null |  |
| roundId | 선택 | string / null |  |
| viewId | 선택 | string / null |  |

<a id="schema-termout"></a>

### TermOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| body | 필수 | string, null | 팀이 승인한 약관 본문. 미승인 본문을 만들어 제공하지 않으며 필수 약관 미제공이면 가입을 완료하지 않는다. |
| version | 필수 | string, null | 사용자가 동의한 본문을 식별하는 약관 버전. 승인된 버전만 가입 요청에 사용한다. |
| id | 필수 | string |  |
| required | 필수 | boolean |  |
| bodyAvailable | 필수 | boolean | 승인한 본문·버전이 실제 제공되었는지 나타낸다. |

<a id="schema-termsresponse"></a>

### TermsResponse



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [TermOut](#schema-termout)[] |  |
| nextCursor | 필수 | string, null |  |

<a id="schema-transcriptdetail"></a>

### TranscriptDetail



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| user | 필수 | string |  |
| userKind | 필수 | string {member, guest} |  |
| startedAt | 필수 | string (date-time) |  |
| messages | 필수 | [TranscriptMessage](#schema-transcriptmessage)[] |  |
| masking | 필수 | [MaskingReport](#schema-maskingreport) |  |

<a id="schema-transcriptfeedback"></a>

### TranscriptFeedback



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| up | 필수 | integer |  |
| down | 필수 | integer |  |
| reasons | 필수 | string[] |  |

<a id="schema-transcriptmessage"></a>

### TranscriptMessage



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| seq | 필수 | integer |  |
| at | 필수 | string |  |
| question | 필수 | string |  |
| answer | 필수 | string |  |
| status | 필수 | string |  |
| reason | 필수 | string / null |  |
| contextLabels | 필수 | string[] |  |
| citationCount | 필수 | integer |  |
| feedback | 필수 | [TranscriptFeedback](#schema-transcriptfeedback) |  |

<a id="schema-transcriptpage"></a>

### TranscriptPage



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| items | 필수 | [TranscriptSummary](#schema-transcriptsummary)[] |  |
| nextCursor | 필수 | string / null |  |
| total | 필수 | integer |  |

<a id="schema-transcriptsummary"></a>

### TranscriptSummary



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| user | 필수 | string | Pseudonymous id |
| userKind | 필수 | string {member, guest} |  |
| startedAt | 필수 | string (date-time) |  |
| lastAt | 필수 | string (date-time) |  |
| messages | 필수 | integer |  |
| preview | 필수 | string | First question, masked |
| up | 필수 | integer |  |
| down | 필수 | integer |  |

<a id="schema-tutorialupdate"></a>

### TutorialUpdate



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| completed | 필수 | boolean |  |

<a id="schema-unavailable"></a>

### Unavailable



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string |  |
| reason | 필수 | string |  |

<a id="schema-unsupportedfeedbackfeature"></a>

### UnsupportedFeedbackFeature



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| feature | 필수 | string |  |
| label | 필수 | string |  |
| reason | 필수 | string |  |

<a id="schema-usageout"></a>

### UsageOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| calls | 필수 | integer |  |
| replayCalls | 필수 | integer |  |
| inputTokens | 필수 | integer |  |
| outputTokens | 필수 | integer |  |
| elapsedSeconds | 필수 | number |  |
| estimatedCost | 필수 | number / null |  |

<a id="schema-userinfo"></a>

### UserInfo



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string |  |
| email | 필수 | string |  |
| displayName | 필수 | string |  |

<a id="schema-verdictout"></a>

### VerdictOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| target | 필수 | string |  |
| decision | 필수 | string |  |
| reason | 필수 | string |  |

<a id="schema-verification"></a>

### Verification



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string {ALLOW, not_applicable} |  |
| note | 필수 | string / null |  |

<a id="schema-verificationout"></a>

### VerificationOut



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| provider | 필수 | string / null |  |
| model | 필수 | string / null |  |
| verifierVersion | 필수 | string / null |  |
| decisionPolicy | 필수 | object / null |  |
| verdicts | 필수 | [VerdictOut](#schema-verdictout)[] |  |
| fieldVerdicts | 필수 | [FieldVerdictOut](#schema-fieldverdictout)[] |  |
| observations | 필수 | [ObservationOut](#schema-observationout)[] |  |

<a id="schema-viaissue"></a>

### ViaIssue



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| title | 필수 | string |  |
| id | 필수 | string |  |
| eventTime | 필수 | string / null |  |
| timePrecision | 필수 | string {year, month, day, datetime, unknown} |  |
| evidenceIds | 필수 | string[] |  |

<a id="schema-watchupdate"></a>

### WatchUpdate

FS027 single toggle: whether the company should end up in the watchlist (a resend changes nothing).

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| watched | 필수 | boolean |  |

<a id="schema-sectionfailure"></a>

### SectionFailure

200 부분 성공에서 실패 영역만 명시한다. 자료 없음은 실패가 아니다.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| section | 필수 | string |  |
| code | 필수 | string |  |
| message | 필수 | string |  |
| retryable | 필수 | boolean |  |
| asOf | 필수 | string, null (date-time) |  |

<a id="schema-sentimentlabel"></a>

### SentimentLabel

긍정·부정·혼재·판단 보류. 투자 권유, 가격 예측 또는 확률을 뜻하지 않는다.

string {positive, negative, mixed, undetermined}

<a id="schema-documentsentiment"></a>

### DocumentSentiment

문서 × 기업 맥락의 판정이다. companyId가 조회 맥락과 일치해야 한다. quotes는 확보한 원문 인용이다.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| label | 필수 | [SentimentLabel](#schema-sentimentlabel) |  |
| companyId | 필수 | string |  |
| rationale | 필수 | string |  |
| quotes | 필수 | string[] |  |
| judgedAt | 필수 | string (date-time) |  |
| model | 필수 | string |  |
| promptVersion | 필수 | string |  |

<a id="schema-briefingoutlook"></a>

### BriefingOutlook

브리핑 발행 당시 고정하는 회차 종합 판정이다. 공개 후 변경하거나 최신 판정으로 바꾸지 않는다.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| label | 필수 | [SentimentLabel](#schema-sentimentlabel) |  |
| rationale | 필수 | string |  |
| issueIds | 필수 | string[] |  |
| judgedAt | 필수 | string (date-time) |  |
| model | 필수 | string |  |
| promptVersion | 필수 | string |  |

<a id="schema-analysisprovenance"></a>

### AnalysisProvenance



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| sourceKind | 필수 | string {synthetic, actual} |  |
| executionMode | 필수 | string {replay, live} |  |
| recordingKind | 필수 | string {authored-test, provider} |  |

<a id="schema-analysiscitation"></a>

### AnalysisCitation



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| evidenceId | 필수 | string |  |
| documentId | 필수 | string |  |
| documentVersion | 필수 | string |  |
| textArtifactId | 필수 | string |  |
| offsetUnit | 필수 | string |  |
| start | 필수 | integer |  |
| end | 필수 | integer | Exclusive Unicode code point offset, not JavaScript/Java UTF-16. |
| quote | 필수 | string |  |
| inputKind | 필수 | string {body, summary} |  |
| rawLocatorIds | 필수 | string[] |  |

<a id="schema-analysisclaim"></a>

### AnalysisClaim



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| claimId | 필수 | string |  |
| text | 필수 | string |  |
| assertionKind | 필수 | string {fact, interpretation, limitation} |  |
| evidenceIds | 필수 | string[] |  |

<a id="schema-analysisstagestatus"></a>

### AnalysisStageStatus

undetermined는 유효한 판정 label. null 판정의 실패/미요청/보류를 별도 status로 구분.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| status | 필수 | string {not_requested, pending, failed, withheld, available} |  |
| reason | 필수 | string, null |  |

<a id="schema-documentanalysisstatus"></a>

### DocumentAnalysisStatus



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| summary | 필수 | [AnalysisStageStatus](#schema-analysisstagestatus) |  |
| sentiment | 필수 | [AnalysisStageStatus](#schema-analysisstagestatus) |  |

<a id="schema-documentanalysissummary"></a>

### DocumentAnalysisSummary

S1 실제 문서 요약. exact citation+별도 semantic supported 영수증을 앱이 수입한 후만 제공. GET은 모델 호출 0. 현재 버전·철회·grant gate 실패는 null.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| schemaVersion | 필수 | string |  |
| artifactId | 필수 | string |  |
| documentId | 필수 | string |  |
| documentVersion | 필수 | string |  |
| resultVersion | 필수 | string |  |
| text | 필수 | string |  |
| claims | 필수 | [AnalysisClaim](#schema-analysisclaim)[] |  |
| citations | 필수 | [AnalysisCitation](#schema-analysiscitation)[] |  |
| limitations | 필수 | string[] |  |
| producedAt | 필수 | string (date-time) |  |
| provenance | 필수 | [AnalysisProvenance](#schema-analysisprovenance) |  |

<a id="schema-analysissummary"></a>

### AnalysisSummary

검증된 근거와 결과 버전을 함께 제공하는 해석이다. 근거가 없으면 작성하지 않는다.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| text | 필수 | string |  |
| evidenceIds | 필수 | string[] |  |
| generatedAt | 필수 | string (date-time) |  |
| resultVersion | 필수 | string |  |

<a id="schema-socialprovider"></a>

### SocialProvider



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| id | 필수 | string {google, kakao} |  |
| name | 필수 | string |  |

<a id="schema-financialvalue"></a>

### FinancialValue



| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| name | 필수 | string |  |
| value | 필수 | number, null |  |
| unit | 필수 | string |  |
| period | 필수 | string |  |
| accountingBasis | 필수 | string, null |  |
| source | 필수 | string |  |
| asOf | 필수 | string (date-time) |  |

<a id="schema-financialresponse"></a>

### FinancialResponse

재무 기간은 차트 기간과 별개다. 미제공·계산 불가 값은 null이고 사유를 제공한다.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| companyId | 필수 | string |  |
| period | 필수 | string |  |
| status | 필수 | string {available, unavailable, failed} |  |
| items | 필수 | [FinancialValue](#schema-financialvalue)[] |  |
| reason | 필수 | string, null |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-impactpath"></a>

### ImpactPath

기업 패널에서 여는 영향 경로다. 데이터에 없는 산업·제품 단계나 관계 유형을 만들지 않는다.

| 필드 | 필수 | 형식/참조 | 설명 |
| --- | --- | --- | --- |
| companyId | 필수 | string |  |
| issueId | 필수 | string |  |
| steps | 필수 | object[] |  |
| steps[].id | 필수 | string |  |
| steps[].kind | 필수 | string {company, issue, industry, product} |  |
| steps[].reason | 필수 | string |  |
| steps[].evidenceIds | 필수 | string[] |  |
| metadata | 필수 | [Metadata](#schema-metadata) |  |

<a id="schema-errorcode"></a>

### ErrorCode



string {INVALID_REQUEST, INVALID_CREDENTIALS, AUTH_REQUIRED, MEMBER_REQUIRED, ACCESS_DENIED, MEMBER_BLOCKED, EMAIL_TAKEN, TERMS_REQUIRED, RESOURCE_NOT_FOUND, EVIDENCE_UNAVAILABLE, VERSION_UNAVAILABLE, REVISION_CONFLICT, IDEMPOTENCY_CONFLICT, JOB_IN_PROGRESS, JOB_NOT_RETRYABLE, ALREADY_PUBLISHED, VALIDATION_FAILED, SOCIAL_AUTH_CANCELLED, SOCIAL_AUTH_FAILED, INVALID_CURSOR, RATE_LIMITED, SOURCE_UNAVAILABLE, MODEL_UNAVAILABLE, AUDIT_UNAVAILABLE, MASKING_FAILED, INTERNAL_ERROR}
