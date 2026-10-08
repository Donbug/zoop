# 목표 계약 ↔ BFF 관측본

경로·요청/응답 필드·필수 여부·형식·권한을 비교한다. 각 작업의 전체 필드 차이는 `api-differences/<operationId>.json`에 있다. 실제 동작 시험이 아니며 현재 서버 조회 시각은 `bff-observation.json`에 있다.

| operationId | 목표 경로 | BFF 경로 | 필드 차이 | 설계 차이 |
| --- | --- | --- | --- | --- |
| getMemberSession | /api/v1/auth/session | /api/auth/session | 목표만 102 · BFF만 50 · 형식/필수/권한 변경 4 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| listTerms | /api/v1/auth/terms | /api/auth/terms | 목표만 90 · BFF만 39 · 형식/필수/권한 변경 3 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| signUp | /api/v1/auth/signup | /api/auth/signup | 목표만 152 · BFF만 41 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| logIn | /api/v1/auth/login | /api/auth/login | 목표만 180 · BFF만 23 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| startGuestSession | /api/v1/auth/guest | /api/auth/guest | 목표만 146 · BFF만 41 · 형식/필수/권한 변경 5 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| logOut | /api/v1/auth/logout | /api/auth/logout | 목표만 124 · BFF만 30 · 형식/필수/권한 변경 4 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| setTutorialState | /api/v1/auth/tutorial | /api/auth/tutorial | 목표만 182 · BFF만 23 · 형식/필수/권한 변경 8 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| listSocialProviders | /api/v1/auth/social/providers | /api/auth/social/providers | 목표만 131 · BFF만 34 · 형식/필수/권한 변경 4 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| authorizeSocialLogin | /api/v1/auth/social/{provider}/authorize | /api/auth/social/{provider}/authorize | 목표만 124 · BFF만 30 · 형식/필수/권한 변경 4 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| completeSocialLogin | /api/v1/auth/social/{provider}/callback | /api/auth/social/{provider}/callback | 목표만 124 · BFF만 30 · 형식/필수/권한 변경 4 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| getMySettings | /api/v1/me/settings | /api/me/settings | 목표만 132 · BFF만 32 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| updateMySettings | /api/v1/me/settings | /api/me/settings | 목표만 178 · BFF만 23 · 형식/필수/권한 변경 8 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| setWatchlistCompany | /api/v1/me/watchlist/{id} | /api/me/watchlist/{id} | 목표만 178 · BFF만 23 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listRecommendations | /api/v1/me/recommendations | /api/me/recommendations | 목표만 158 · BFF만 32 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| listVirtualAccountProfiles | /api/v1/portfolio/mock-portfolios | /api/portfolio/mock-portfolios | 목표만 138 · BFF만 32 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| getVirtualAccountProfile | /api/v1/portfolio/mock-portfolios/{id} | /api/portfolio/mock-portfolios/{id} | 목표만 132 · BFF만 32 · 형식/필수/권한 변경 8 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| connectVirtualAccount | /api/v1/portfolio/connections | /api/portfolio/connections | 목표만 180 · BFF만 23 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getMyPortfolio | /api/v1/portfolio | /api/portfolio | 목표만 132 · BFF만 32 · 형식/필수/권한 변경 10 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| disconnectVirtualAccount | /api/v1/portfolio/connections/{id} | /api/portfolio/connections/{id} | 목표만 160 · BFF만 12 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getGraph | /api/v1/graph | /api/graph | 목표만 158 · BFF만 27 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF의 개인화 범위 필터는 화면 처리다. 목표는 personalFilter·asOf·graphVersion과 검증된 국내/국제 속성을 서버에서 제공한다. |
| getCompanyRelation | /api/v1/graph/edges/{id} | /api/graph/edges/{id} | 목표만 118 · BFF만 43 · 형식/필수/권한 변경 6 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| searchCompanies | /api/v1/companies | /api/companies | 목표만 108 · BFF만 50 · 형식/필수/권한 변경 4 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| getCompany | /api/v1/companies/{id} | /api/companies/{id} | 목표만 116 · BFF만 57 · 형식/필수/권한 변경 6 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getCompanyQuote | /api/v1/companies/{id}/quote | /api/companies/{id}/quote | 목표만 84 · BFF만 39 · 형식/필수/권한 변경 4 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getCompanyMetrics | /api/v1/companies/{id}/metrics | /api/companies/{id}/metrics | 목표만 84 · BFF만 39 · 형식/필수/권한 변경 4 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getCompanyPrices | /api/v1/companies/{id}/prices | /api/companies/{id}/prices | 목표만 84 · BFF만 39 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listCompanyDocuments | /api/v1/companies/{id}/documents | /api/companies/{id}/documents | 목표만 118 · BFF만 64 · 형식/필수/권한 변경 19 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| listEvents | /api/v1/events | /api/events | 목표만 90 · BFF만 48 · 형식/필수/권한 변경 12 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| getEvent | /api/v1/events/{id} | /api/events/{id} | 목표만 134 · BFF만 52 · 형식/필수/권한 변경 6 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getEvidence | /api/v1/evidence/{id} | /api/evidence/{id} | 목표만 125 · BFF만 55 · 형식/필수/권한 변경 16 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getBriefing | /api/v1/briefings | /api/briefings | 목표만 128 · BFF만 60 · 형식/필수/권한 변경 20 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listBriefingRounds | /api/v1/briefings/rounds | /api/briefings/rounds | 목표만 84 · BFF만 39 · 형식/필수/권한 변경 6 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| getBriefingGraphBasis | /api/v1/briefings/{id}/graph | /api/briefings/{id}/graph | 목표만 97 · BFF만 30 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| createConversation | /api/v1/chat/sessions/{id} | /api/chat/sessions/{id} | 목표만 161 · BFF만 12 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| getConversation | /api/v1/chat/sessions/{id} | /api/chat/sessions/{id} | 목표만 136 · BFF만 32 · 형식/필수/권한 변경 14 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| getCurrentConversation | /api/v1/chat/sessions/current | /api/chat/sessions/current | 목표만 136 · BFF만 32 · 형식/필수/권한 변경 14 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| submitQuestion | /api/v1/chat/sessions/{id}/jobs | /api/chat/sessions/{id}/jobs | 목표만 211 · BFF만 34 · 형식/필수/권한 변경 24 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| getQuestionJob | /api/v1/chat/jobs/{job_id} | /api/chat/jobs/{job_id} | 목표만 153 · BFF만 23 · 형식/필수/권한 변경 14 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| retryQuestionJob | /api/v1/chat/jobs/{job_id}/retry | /api/chat/jobs/{job_id}/retry | 목표만 207 · BFF만 34 · 형식/필수/권한 변경 21 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| cancelQuestionJob | /api/v1/chat/jobs/{job_id}/cancel | /api/chat/jobs/{job_id}/cancel | 목표만 184 · BFF만 23 · 형식/필수/권한 변경 14 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF는 규칙 기반/예시 엔진이다. 목표는 실제 근거 기반 분석·검증·저장 및 asOf/graphVersion을 고정한다. |
| getAdminSession | /api/v1/admin/auth/session | /api/admin/auth/session | 목표만 110 · BFF만 2 · 형식/필수/권한 변경 1 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| logInAdmin | /api/v1/admin/auth/login | /api/admin/auth/login | 목표만 197 · BFF만 6 · 형식/필수/권한 변경 5 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| logOutAdmin | /api/v1/admin/auth/logout | /api/admin/auth/logout | 목표만 160 · BFF만 0 · 형식/필수/권한 변경 0 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 모의 인증 제공자/개발용 동의 경로는 목표 계약에서 제외한다. 실제 제공자 검증이 필요하다. |
| getAdminDashboard | /api/v1/admin/dashboard | /api/admin/dashboard | 목표만 114 · BFF만 59 · 형식/필수/권한 변경 31 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listAuditRecords | /api/v1/admin/audit-log | /api/admin/audit-log | 목표만 115 · BFF만 23 · 형식/필수/권한 변경 11 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| getPipelineOverview | /api/v1/admin/pipeline/overview | /api/admin/pipeline/overview | 목표만 114 · BFF만 21 · 형식/필수/권한 변경 12 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listAnalysisCandidates | /api/v1/admin/pipeline/candidates | /api/admin/pipeline/candidates | 목표만 115 · BFF만 23 · 형식/필수/권한 변경 10 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| getAnalysisCandidate | /api/v1/admin/pipeline/candidates/{candidate_id} | /api/admin/pipeline/candidates/{candidate_id} | 목표만 115 · BFF만 30 · 형식/필수/권한 변경 11 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| decideAnalysisCandidate | /api/v1/admin/pipeline/candidates/{candidate_id}/decision | /api/admin/pipeline/candidates/{candidate_id}/decision | 목표만 172 · BFF만 38 · 형식/필수/권한 변경 11 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF allow 처리와 목표의 재검증 접수·expectedRevision·비공개 유지 규칙을 대조한다. |
| listPublicationRules | /api/v1/admin/pipeline/rules | /api/admin/pipeline/rules | 목표만 120 · BFF만 21 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| setPublicationRule | /api/v1/admin/pipeline/rules/{rule_id} | /api/admin/pipeline/rules/{rule_id} | 목표만 160 · BFF만 12 · 형식/필수/권한 변경 11 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listGraphVersions | /api/v1/admin/graph/versions | /api/admin/graph/versions | 목표만 120 · BFF만 23 · 형식/필수/권한 변경 8 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| publishGraphVersion | /api/v1/admin/graph/versions | /api/admin/graph/versions | 목표만 162 · BFF만 14 · 형식/필수/권한 변경 10 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| activateGraphVersion | /api/v1/admin/graph/versions/{version_id}/activate | /api/admin/graph/versions/{version_id}/activate | 목표만 162 · BFF만 12 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listAnalysisJobs | /api/v1/admin/jobs | /api/admin/jobs | 목표만 118 · BFF만 92 · 형식/필수/권한 변경 19 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. / 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| createAnalysisJob | /api/v1/admin/jobs | /api/admin/jobs | 목표만 167 · BFF만 39 · 형식/필수/권한 변경 15 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| getAnalysisJob | /api/v1/admin/jobs/{job_id} | /api/admin/jobs/{job_id} | 목표만 114 · BFF만 39 · 형식/필수/권한 변경 13 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| retryAnalysisJob | /api/v1/admin/jobs/{job_id}/retry | /api/admin/jobs/{job_id}/retry | 목표만 162 · BFF만 36 · 형식/필수/권한 변경 15 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| cancelAnalysisJob | /api/v1/admin/jobs/{job_id}/cancel | /api/admin/jobs/{job_id}/cancel | 목표만 162 · BFF만 30 · 형식/필수/권한 변경 15 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 로컬 PoC 명령·샌드박스·호출 예산 필드는 정식 서버 계약에서 제외한다. |
| getAiUsage | /api/v1/admin/ai-usage | /api/admin/ai-usage | 목표만 114 · BFF만 21 · 형식/필수/권한 변경 10 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listAdminBriefingRounds | /api/v1/admin/briefings | /api/admin/briefings | 목표만 120 · BFF만 21 · 형식/필수/권한 변경 12 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| getAdminBriefingRound | /api/v1/admin/briefings/{round_id} | /api/admin/briefings/{round_id} | 목표만 147 · BFF만 37 · 형식/필수/권한 변경 26 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| reprocessBriefingRound | /api/v1/admin/briefings/{round_id}/reprocess | /api/admin/briefings/{round_id}/reprocess | 목표만 162 · BFF만 12 · 형식/필수/권한 변경 13 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| appendBriefingCorrection | /api/v1/admin/briefings/{round_id}/corrections | /api/admin/briefings/{round_id}/corrections | 목표만 162 · BFF만 12 · 형식/필수/권한 변경 12 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| setBriefingSuspension | /api/v1/admin/briefings/{round_id}/suspension | /api/admin/briefings/{round_id}/suspension | 목표만 162 · BFF만 12 · 형식/필수/권한 변경 13 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| recordInteractionEvents | /api/v1/telemetry | /api/telemetry | 목표만 161 · BFF만 13 · 형식/필수/권한 변경 10 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getMyFeedback | /api/v1/feedback | /api/feedback | 목표만 120 · BFF만 21 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| setFeedback | /api/v1/feedback | /api/feedback | 목표만 160 · BFF만 12 · 형식/필수/권한 변경 10 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getInsightsOverview | /api/v1/admin/insights/overview | /api/admin/insights/overview | 목표만 114 · BFF만 21 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getInsightsSummary | /api/v1/admin/insights/summary | /api/admin/insights/summary | 목표만 114 · BFF만 21 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listCompanyInsights | /api/v1/admin/insights/companies | /api/admin/insights/companies | 목표만 120 · BFF만 21 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| getCompanyInsights | /api/v1/admin/insights/companies/{company_id} | /api/admin/insights/companies/{company_id} | 목표만 114 · BFF만 21 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getFeedbackSummary | /api/v1/admin/feedback/summary | /api/admin/feedback/summary | 목표만 114 · BFF만 21 · 형식/필수/권한 변경 8 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| listDislikedResults | /api/v1/admin/feedback/dislikes | /api/admin/feedback/dislikes | 목표만 115 · BFF만 23 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| listMaskedTranscripts | /api/v1/admin/transcripts | /api/admin/transcripts | 목표만 117 · BFF만 23 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. / BFF에 별도 열람 권한·purpose 필수·기록 실패 차단 계약이 부족하다. |
| getMaskedTranscript | /api/v1/admin/transcripts/{session_id} | /api/admin/transcripts/{session_id} | 목표만 116 · BFF만 21 · 형식/필수/권한 변경 8 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / BFF에 별도 열람 권한·purpose 필수·기록 실패 차단 계약이 부족하다. |
| listMembers | /api/v1/admin/members | /api/admin/members | 목표만 115 · BFF만 23 · 형식/필수/권한 변경 10 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. / 목표는 불투명 커서·limit/nextCursor. BFF의 전체 목록·정수 offset/limit와 다를 수 있다. |
| getMemberActivity | /api/v1/admin/members/{member_id} | /api/admin/members/{member_id} | 목표만 114 · BFF만 21 · 형식/필수/권한 변경 9 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| blockMember | /api/v1/admin/members/{member_id}/block | /api/admin/members/{member_id}/block | 목표만 162 · BFF만 12 · 형식/필수/권한 변경 11 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| unblockMember | /api/v1/admin/members/{member_id}/unblock | /api/admin/members/{member_id}/unblock | 목표만 162 · BFF만 12 · 형식/필수/권한 변경 11 | /api → /api/v1 경로 버전, 공통 오류 코드·요청 ID·세션 보안 규칙 적용. |
| getCompanyFinancials | /api/v1/companies/{id}/financials | 없음 | 직접 대응 BFF 작업 없음 | 목표 API만 있음 |
| getCompanyIssueImpact | /api/v1/companies/{id}/issues/{issueId}/impact | 없음 | 직접 대응 BFF 작업 없음 | 목표 API만 있음 |
| getPersonalizedBriefing | /api/v1/briefings/{id}/personalized | 없음 | 직접 대응 BFF 작업 없음 | 목표 API만 있음 |
| getCompanyGraphAsOf | /api/v1/companies/{id}/graph | /api/companies/{id}/graph | 목표만 121 · BFF만 41 · 형식/필수/권한 변경 7 | /api → /api/v1 경로 버전 및 공통 오류·요청 ID 적용. / BFF는 현재 저장된 승인 자료를 문서 공개 시각으로 거른다. 목표는 asOf와 실제 사용한 불변 공개 버전을 함께 고정한다. |
