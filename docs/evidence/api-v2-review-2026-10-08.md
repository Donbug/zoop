# API v2 검토·채택/정정 목록 (2026-10-08)

**팀원 Markdown을 통째로 교체하지 않고 네 변경 의도만 현재 OpenAPI로 번역했다.** 아래 ID는 이후 사용자 발견 사항과 비교할 때 유지한다. 이 문서는 목표 계약·원문 의미 연결의 검토이며 앱 구현, 실제 OAuth/공급원 연결, 전체 수용 기준 통과 보고가 아니다. 이번 변경은 로컬에만 두며 staging·commit·push하지 않는다.

## 고정 근거와 범위

- [팀원 불변 사본](raw/api-spec-v2_2026-10-08/zoop-api-spec-v2.md), [수신 기록](raw/api-spec-v2_2026-10-08/source.json): 327,701 bytes, SHA-256 `458a51bbdf7dfa3b417ad9c41882208be88d6e91eaec3d7ad3d1973969b9667a`. 원본 YAML은 제공되지 않았다. 아래 `T:행`은 이 사본의 텍스트 줄이다.
- [15:05 원문 재확인](api-source-refresh-2026-10-08.md): 최신 WBS3탭·173ID의 값11셀/수식34셀 변화, 명세15탭 전셀 동일. 현재 입력은 `wbs_2026-10-08-api-review`, `functional-spec_2026-10-08`, `requirements-sheet_2026-10-06`이다. CSV 출처의 `row`는 물리적 줄이 아니라 XLSX 행이다.
- [정본 OpenAPI](../api/openapi.yaml), [사람의 의미 연결](../system/links.yaml), [생성 API](../api/out/zoop-api-spec.md), [현재 원문 정정 요청](../system/out/source-corrections.md), [WBS 이행](../system/out/wbs-migration.md)을 함께 읽는다. 원문의 오래된 상태와 [현재 사용자 결정](../share/day-work-2026-10-08.md)은 별개다.
- 비교 기준은 전달 당시 현재 생성 API와 팀원 사본의 내용 차이다. 파일명 v2는 `/api/v2` 도입을 뜻하지 않는다. 84개 operationId·메서드·경로를 유지하고 S1·현재 권한/범위 결정도 유지한다. Notion/WBS가 이 정확한 Markdown을 직접 링크·승인했다는 근거는 확인하지 못했다.
- 독립 심층 검토자의 84개 의미 연결 검토와 원문 재확인 증거를 받아 통합했다. 검토는 FS 목차/상세 의미, WBS 제목·BE/FE 역할·raw FS/편집 연결을 대조한 것이며 각 endpoint의 모든 수용 기준 실행 합격 판정은 아니다.

## 채택한 네 의도

| 안정 ID | 원문 위치·정본 심볼 | 채택 결과와 영향 | 상태 |
|---|---|---|---|
| A01 | T:808–834,3450–3475; `getCompany`, `CompanyDetail` | 기존 `sector`를 포함한 여섯 프로필 키가 required·nullable다. 새 키는 `legalName`, `market`, `representative`, `foundedDate(date)`, `websiteUrl(uri)` 다섯 개다. `name`은 표시명이고 정식 명칭을 대신하지 않는다. 정확한 날짜·공식 주소·대표자 등 미확인 값은 null이며 가짜 기본값을 넣지 않는다. | 채택. 기업 마스터 공급원/자료 시점 및 실제 BFF DTO 이행은 미완료다. |
| A02 | T:961–993,4077–4106; `listEvents`, `EventSummary` | required `relationTypes`는 uniqueItems 배열이며 `INVOLVES`/`STRUCTURALLY_RELATED_TO`만 허용한다. 요청 `companyId`와 사건 사이의 직접 승인 간선을 같은 graphVersion/asOf에서 읽는다. 둘 다 있으면 모두 보존한다. 회사 맥락 없음·직접 간선 없음·2-hop 전용은 []다. 공통 스키마로 items/unknownTimeItems 양쪽에 적용한다. | 채택. `FS055`/저장 WBS6.5.1을 조회 근거로 추가하되 FS078 관계 생산을 HTTP API/구현 완료로 승격하지 않는다. |
| A03 | T:838–861,5305–5324; `getCompanyQuote`, `QuoteValues` | quote 요청의 asOf/graphVersion만 제거한다. 공급자의 가장 최근 제공 시세는 차트 기간·조회 pin과 독립적이며 실시간/당일 보장은 아니다. `quote.asOf`는 공급자 관측시각 또는 null이다. `QuoteSourceOut`·지연/가격 종류·통화/단위·X-Request-ID를 유지한다. | 채택. 역사 selector 전달은422 INVALID_REQUEST로 거절한다. 그래프 부재만으로 VERSION_UNAVAILABLE을 반환하지 않는다. 별도 역사 차트 조건은 유지한다. |
| A04 | T:376–458,5753–5763,6188–6196; 회원 소셜3작업, `SocialProvider` | provider ID와 authorize/callback 경로 enum을 google/kakao로 맞춘다. 전체 커서 순회에 각각 한 번 포함되며 개별 페이지에 두 항목을 강제하지 않는다. Origin/state·허용 복귀 경로·기존 계정 본인/연결권한 확인을 유지한다. | 채택. mock은 실제 OAuth가 아니며 관리자 SSO·운영 등록/권한은 미정이다. |

## 발견 사항과 처리

`F01–F07`은 독립 심층 검토의 번호를 유지한다. 현재 계약에 이미 있던 오류도 새 변경으로 만들어진 결함과 구분한다. F03–F07 및 역사 quote selector 거절은 검토를 바탕으로 Main이 선택한 **작업자 계약 정정안**이며 새 팀 회의 합의가 확인됐다는 주장이 아니다.

| 안정 ID | 근거 위치 | 영향·최소 처리 | 상태 |
|---|---|---|---|
| F01 | T:3479–3494 `CompanyDocument`,4123–4139 `EvidenceResponse`,6171 뒤 스키마 목록; 정본 S1 6개 스키마 | 통째 교체하면 두 응답에서 `documentVersion/documentSummary/analysisStatus/analysisProvenance/resultVersion` 각5필드와 S1 6스키마가 사라진다. 상태·인용/버전·synthetic/actual 출처와 현재 공개 gate 표현을 잃는다. | 회귀 불채택. 현재 필드와 `AnalysisProvenance/AnalysisCitation/AnalysisClaim/AnalysisStageStatus/DocumentAnalysisStatus/DocumentAnalysisSummary`를 보존했다. |
| F02 | T:5,389,417,445,876,2515–2518,2598–2603,59–61; 최신 WBS 본문37/43/113/136/156/175행 | 구 번호로 소셜·시세·기업·API 통합을 연결하고 FS042 지표/재무/시점그래프 의미와 현재 범위 결정을 되돌린다. 번호 존재만으로 담당을 배정하면 다른 업무에 책임을 붙인다. | 회귀 불채택. 소셜6.2.2, 관리자 인증6.10.1, API 통합6.11.1과 현재84 연결을 유지한다. metrics=FS020/038, FS042는 재무/시점그래프 의미별 qualification을 보존한다. |
| F03 | 정본 `logOut`, `logOutAdmin`의 security/parameters; common authentication/idempotency | 두 작업이 security=[]·RequestId만 선언해 쿠키 쓰기의 Origin/CSRF 및 POST 멱등 정책과 충돌했다. 실제 취약점을 실행 증명한 것은 아니다. | 정정. 해당 쿠키 또는 무세션 인증 대안과 선택 X-CSRF-Token을 선언했다. 활성 해당 세션은 cookie+Origin+세션 결합 CSRF 필수이며 실패403 ACCESS_DENIED, 익명 분기 우회 금지다. 없음/무효/만료는 타 세션 변경 없이 해당 쿠키만 제거하고 반복204다. 자연 멱등 폐기이므로 공통 Idempotency-Key에서 명시 제외하고 불필요한409/충돌 코드를 제거했다. 조건부 검증은 서버 책임이며 OpenAPI의 자동 강제를 주장하지 않는다. |
| F04 | 정본 `getCompany`, `listEvents` responses/errorCodes; common publicationVersions | pin 부재는409 VERSION_UNAVAILABLE 규칙인데 두 작업의 응답/오류 목록에 빠져 있었다. | 정정. 기존 Error409/코드를 추가했다. 최신 자료 fallback은 없다. |
| F05 | T:847,3592–3601; 정본 `CompanyQuoteUnavailable`, common partialFailures | 200 unavailable에 공급자 auth/network/format 장애가 섞여 정상 자료 부재와 실패가 구분되지 않았다. | 정정. 200의 정상 부재는 not_connected/unsupported_symbol/no_data만 허용한다. 실제 인증·네트워크·형식 장애는 기존503 SOURCE_UNAVAILABLE이며 retryable은 원인에 맞춘다. 기존 BFF 성공 분기는 이행 대상이며 앱은 변경하지 않았다. |
| F06 | 정본 common modelConfiguration; [AI 설정](../design/ai-system.md)65–67행 | 현재 worker가 읽지 않는 옛 ZOOP_SENTIMENT 설정 안내가 남아 있었다. | 정정. DOCUMENT_SUMMARY/DOCUMENT_SENTIMENT/VERIFY/BRIEFING_OUTLOOK의 `ZOOP_AI_*` stage env로 안내를 맞췄다. alias·유료 실행·비밀 설정값 노출은 없다. |
| F07 | 정본 getGraph/getCompanyRelation/getCompany/getEvent/getEvidence의 round helper; T:739,770,831,1020,1050 | 목표 설명이 BFF `/api/briefings/{id}/graph`를 가리켜 버전 경계가 어긋났다. | 정정. 다섯 작업의 중복 helper10곳을 `/api/v1/briefings/{id}/graph`로 고쳤다. prototype 대응 경로는 `/api`로 유지한다. |
| C01 | 최신 WBS `프로젝트 WBS` E136(6.8.14); [mapping delta](raw/refresh_2026-10-08-api-review/_mapping-relevant-delta.json) | raw의 과거 평가 FS037이 FS066-01로 정정됐다. 이전 편집 연결은 이미 FS066-01이었다. | 해소. 새 catalog의 raw/편집 연결을 일치시켰다. 현재6.8.14의 과거 경고를 미해결로 유지하지 않는다. 다른 FS037 목차/이력 충돌은 별개다. |
| C02 | `import_sources.py` 기본값, system README·catalog sources, `repo_checks.py::docs` | 재생성이 새벽 WBS로 돌아가면 오후의 진척/일정·E136 정정이 유실된다. | 정정. 기본값/재현 명령을 최신 조합으로 맞춘다. docs 검사는 catalog sources를 명시 전달하는 기존 방식을 유지한다. |

## 남은 원문 정정·운영 결정

| 안정 ID | 원문 위치·근거 | 유지할 경계 / 결정 대상 | 상태 |
|---|---|---|---|
| H01 | FS042 목차52행=재무·실적, 기업상세79행=시점그래프; WBS6.7.5 | 고유 ID·목차/요구 연결 및 재무 담당/일정을 정정한다. 재무 endpoint와 시점그래프를 둘 다 유지하며 재무 삭제나 그래프 업무의 재무 완료를 추정하지 않는다. | 원문 정정 요청 |
| H02 | 회원 FS004 51행, 외부 FS061 9행; [재확인](api-source-refresh-2026-10-08.md)67행 | 동일 이메일 자동 연결과 별도 본인/연결권한 확인 조건이 충돌한다. 권한 확인 전 기존 계정 연결/로그인 완료를 금지하는 fail-closed 경계를 유지한다. 제공자 선택이 계정 병합 허가가 아니다. | 확인/실패 흐름 결정 필요 |
| H03 | FS050 AIv2 79행·FS??? 브리핑134행, 다중 상세17ID | 구/v2 폐기 선언 없이 번호 근접으로 통합하지 않는다. 상세 정의를 각각 보존하고 FS050/050-01/-02/051/052·FS???/066-01 관계를 정정한다. | 원문 정정 요청 |
| H04 | WBS6.5.3 raw FS057,6.8.7 업무 공란; 표지/요약6.5.13~20 vs 본문6.6.13~20 | 저장 의미 FS035 편집 연결과 원문 이력을 분리한다. 공란 업무를 발명하지 않는다. FS074~081은 현재 설계·구현 범위이며 오프라인 생산/BE저장조회 역할·일정/가중치를 원문에서 일치시킨다. | 원문 정정 요청 |
| H05 | 본문5/6/34/174행, 요약19–21/28행,6.9.15의 시작10/28·종료10/24 | 수행·동결·검증·인수/상위 일정·담당 안내·역전 날짜를 원문 담당자가 정정한다. Notion 날짜·임의 날짜/담당으로 덮지 않는다. | 원문 정정 요청 |
| H06 | [공급원 조사](external-api-candidates-2026-10-08.md), [S1](../design/ai-system.md) | 프로필 마스터·OAuth 등록/scopes·자료 권리·모델/effort/예산·관리자 SSO/session 운영값은 별도 승인/결정이다. 이번 계약 채택으로 새 서비스·키·유료 호출을 열지 않는다. S2–S7·실 OAuth·일반 AI 채팅 구현 완료로 쓰지 않는다. | 운영/권한 선행조건 |
| H07 | 워크북 hyperlink inventory0; 공개 Notion shell; 원본 YAML 미제공 | 이 v2의 Notion/WBS 직접 합의 연결은 미확인이다. 링크 부재를 전체 Notion에 합의가 없다는 증거로 확대하지 않는다. | 증거 미확인 |

## 84개 operationId 의미 검토 범위

모든 작업을 검토했다. 아래는 주요 의미/현재 WBS 요약이고 공통6.1.2/6.11.1 및 전체 FE·저장 의존 목록은 [생성 API 작업별 표](../api/out/zoop-api-spec.md), `openapi.yaml.x-zoop`, [추적 xlsx](../system/out/zoop-trace.xlsx)에 있다. ‘유지’는 이 연결 수준의 판단이지 모든 runtime/수용 기준의 통과가 아니다. 원문 제안8개는 오프라인 설계대상이며 새 HTTP endpoint로 억지 연결하지 않는다.

| # | operationId | 주요 의미·현재 WBS | 판정 |
|---:|---|---|---|
| 1 | getMemberSession | FS001/006 ·6.2.4 | 유지 |
| 2 | listTerms | FS003 ·6.2.1 | 유지 |
| 3 | signUp | FS003 ·6.2.1 | 유지 |
| 4 | logIn | FS002/006 ·6.2.1/4 | 유지 |
| 5 | startGuestSession | FS005 ·6.2.3 | 유지 |
| 6 | logOut | FS007 ·6.2.5 | 연결 유지/F03 |
| 7 | setTutorialState | FS015/016 ·6.3.7/10 | 유지 |
| 8 | listSocialProviders | FS004/061 ·6.2.2 | A04/H02 |
| 9 | authorizeSocialLogin | FS004/061 ·6.2.2 | A04/H02 |
| 10 | completeSocialLogin | FS004/061 ·6.2.2 | A04/H02 |
| 11 | getMySettings | FS008/012/013/054 ·6.3.1/4/5,6.4.1/3 | 유지 |
| 12 | updateMySettings | FS008/010/012/013 ·6.3.1/2/4/5 | 유지 |
| 13 | setWatchlistCompany | FS027 ·6.4.2,6.6.12 | 유지 |
| 14 | listRecommendations | FS011-02 ·6.3.3/FE6.4.5 | 검색 업무 재사용이며 별도 추천 작업 완료는 아님 |
| 15 | listVirtualAccountProfiles | FS009/062 ·6.3.2,6.4.4 | 유지 |
| 16 | getVirtualAccountProfile | FS009/062 ·6.3.2,6.4.4 | 유지 |
| 17 | connectVirtualAccount | FS009/010/062 ·6.3.2,6.4.4 | 유지 |
| 18 | getMyPortfolio | FS039/054 ·6.4.3/6,6.7.8 | 유지 |
| 19 | disconnectVirtualAccount | FS009/062 ·6.4.4 | 유지 |
| 20 | getGraph | FS014/017–019/026/032/040/044/055 ·6.3.6,6.6.1–3/11,6.5.1 | 구/v2 상세 구분/F07 |
| 21 | getCompanyRelation | FS023/024/055 ·6.6.8/9,6.5.1 | 기업 간 관계 의미 유지/F07 |
| 22 | searchCompanies | FS011-01/026/037 ·6.3.3,6.6.11,6.7.1 | 현재FS037 검색 |
| 23 | getCompany | FS020/038/044 ·6.6.4,6.7.2/7 | A01/F04/F07 |
| 24 | getCompanyQuote | FS020/038/063 ·6.6.4,6.7.2,6.5.6 | A03/F05 |
| 25 | getCompanyMetrics | FS020/038 ·6.6.4,6.7.2 | FS042 되돌림 불채택 |
| 26 | getCompanyPrices | FS038/040 ·6.7.2/3 | 역사 차트 유지 |
| 27 | listCompanyDocuments | FS021/043/056/063/064 ·6.6.5,6.7.6,6.5.2/6/7 | S1 유지 |
| 28 | listEvents | FS040/041/056/055 ·6.7.3/4,6.5.2/1 | A02/F04 |
| 29 | getEvent | FS021/041/056 ·6.6.5,6.7.4,6.5.2 | 상세 맥락 필드 확장 없음/F07 |
| 30 | getEvidence | FS024/043/050-01/055 ·6.6.9,6.7.6,6.9.5,6.5.1 | S1 유지/F07 |
| 31 | getBriefing | FS028–031/033–035 ·6.8.1–4/6/8,6.5.3 | 불변 회차/rawFS057 구분 |
| 32 | listBriefingRounds | FS033/035 ·6.8.6/8,6.5.3 | 저장 의미 구분 |
| 33 | getBriefingGraphBasis | FS032/035 ·6.8.5/8,6.5.3 | C01/고정 버전 유지 |
| 34 | createConversation | FS051/060 ·6.9.6/10 | 구/v2 상세 구분 |
| 35 | getConversation | FS052-01/-02/060 ·6.9.6/7/8/10 | 유지 |
| 36 | getCurrentConversation | FS052-02/060 ·6.9.7/8/10 | 유지 |
| 37 | submitQuestion | FS025/045–049/050-02/052-01/060/064 ·6.6.10,6.9.1–6/10,6.5.7 | 구/v2 구분/S1 채팅 완료 아님 |
| 38 | getQuestionJob | FS046/049/050-01/-02/053 ·6.9.4/5/7/9 | 구/v2 구분 |
| 39 | retryQuestionJob | FS053 ·6.9.7/9 | 유지 |
| 40 | cancelQuestionJob | FS046/053 ·6.9.7/9 | 구/v2 구분 |
| 41 | getAdminSession | FS073 ·6.10.1/13 | 관리자SSO 미정 |
| 42 | logInAdmin | FS073 ·6.10.1/13 | 관리자SSO 미정 |
| 43 | logOutAdmin | FS073 ·6.10.1/13 | 연결 유지/F03 |
| 44 | getAdminDashboard | FS072 ·6.10.2/14 | 유지 |
| 45 | listAuditRecords | FS072/NFS008 ·6.10.12/18 | 감사 의미 유지 |
| 46 | getPipelineOverview | FS058/059/063/067-01 ·6.10.6,6.5.4/5/6 | 유지 |
| 47 | listAnalysisCandidates | FS067-01/-02 ·6.10.6/7 | 유지 |
| 48 | getAnalysisCandidate | FS067-01/-02 ·6.10.6/7 | 유지 |
| 49 | decideAnalysisCandidate | FS059/067-02 ·6.10.7,6.5.5 | 허용→재검증/발행 구분 |
| 50 | listPublicationRules | FS059/067-01 ·6.10.6,6.5.5 | 유지 |
| 51 | setPublicationRule | FS059/067-02 ·6.10.7,6.5.5 | 유지 |
| 52 | listGraphVersions | FS059/067-01 ·6.10.6,6.5.5 | 유지 |
| 53 | publishGraphVersion | FS059/067-02 ·6.10.7,6.5.5 | 승인/발행 구분 |
| 54 | activateGraphVersion | FS059/067-02 ·6.10.7,6.5.5 | 유지 |
| 55 | listAnalysisJobs | FS058/067-01 ·6.10.6,6.5.4 | 유지 |
| 56 | createAnalysisJob | FS058/059/063/064 ·6.5.4–7 | 생산 의존 연결/S1 CLI를 HTTP로 포장하지 않음 |
| 57 | getAnalysisJob | FS067-01 ·6.10.6 | 유지 |
| 58 | retryAnalysisJob | FS067-03 ·6.10.7 | 유지 |
| 59 | cancelAnalysisJob | FS067-03 ·6.10.7 | 유지 |
| 60 | getAiUsage | FS068 ·6.10.8/17 | 유지 |
| 61 | listAdminBriefingRounds | FS070-01 ·6.10.9 | 유지 |
| 62 | getAdminBriefingRound | FS070-01 ·6.10.9 | 유지 |
| 63 | reprocessBriefingRound | FS028/029/034/070-02 ·6.8.1/2/8,6.10.9 | 미발행본만 재처리 |
| 64 | appendBriefingCorrection | FS035/071-01 ·6.8.8,6.10.10,6.5.3 | 불변 원문+정정 |
| 65 | setBriefingSuspension | FS071-02 ·6.10.10 | 유지 |
| 66 | recordInteractionEvents | FS065 ·6.10.4 | 계측 생산/집계 소비 구분 |
| 67 | getMyFeedback | FS066-01 ·6.8.10/14,6.10.5 | C01 현재 평가 의미 |
| 68 | setFeedback | FS066-01 ·6.8.10/14,6.10.5 | C01 현재 평가 의미 |
| 69 | getInsightsOverview | FS065 ·6.10.4/15 | 유지 |
| 70 | getInsightsSummary | FS065 ·6.10.4/15 | 유지 |
| 71 | listCompanyInsights | FS065 ·6.10.4/15 | 유지 |
| 72 | getCompanyInsights | FS065 ·6.10.4/15 | 유지 |
| 73 | getFeedbackSummary | FS066-02 ·6.10.5/15 | 유지 |
| 74 | listDislikedResults | FS066-02 ·6.10.5/15 | 유지 |
| 75 | listMaskedTranscripts | FS066-03 ·6.10.11/15 | 목적/권한/감사 경계 |
| 76 | getMaskedTranscript | FS066-03 ·6.10.11/15 | 목적/권한/감사 경계 |
| 77 | listMembers | FS069-01 ·6.10.3/18 | 유지 |
| 78 | getMemberActivity | FS069-01 ·6.10.3/18 | 유지 |
| 79 | blockMember | FS069-02 ·6.10.3/18 | 유지 |
| 80 | unblockMember | FS069-02 ·6.10.3/18 | 유지 |
| 81 | getCompanyFinancials | FS042 재무 ·공통6.1.2/6.11.1만 | H01/도메인 일정 미배정 |
| 82 | getCompanyIssueImpact | FS022/024/055 ·6.6.6/7/9,6.5.1 | 경로 소비/FS079 생산 구분 |
| 83 | getPersonalizedBriefing | FS036 ·6.8.9/14 | 목표 유지/이번에 구현하지 않음 |
| 84 | getCompanyGraphAsOf | FS038/040/041/042시점/055 ·6.7.2/3/4/5,6.5.1 | H01 의미별qualification 유지 |

## 생성과 후속 확인 경계

생성물 MD/XLSX를 직접 고치지 않는다. 기존 설치 환경으로 다음 순서로 생성하고 Main이 최종 gate를 수행한다. 새 의존성·앱 source/BFF schema·private .env·외부 쓰기는 없다.

```sh
/Users/asqi/.cache/uv/archive-v0/xPQgf6_g_qGV2_f6/bin/python docs/system/import_sources.py \
  --spec-dir docs/evidence/raw/functional-spec_2026-10-08 \
  --wbs-dir docs/evidence/raw/wbs_2026-10-08-api-review \
  --requirements-dir docs/evidence/raw/requirements-sheet_2026-10-06
/Users/asqi/.cache/uv/archive-v0/xPQgf6_g_qGV2_f6/bin/python docs/system/build.py
```

기존 `bff-openapi.json`/관측시각을 재사용하며 현재 서버를 다시 관측한 것으로 쓰지 않는다. 생성기의 `--check` 종료1은 경고/의도된 BFF 차이에도 발생한다. 최종 판정은 hard error0, XLSX 되읽기, OpenAPI 및 format-aware schema 소비자 검사와 생성 drift 확인으로 구분한다. 실제 시험 결과는 Main이 별도로 기록한다.

위 두 생성 명령은 설치 없이 실행했다. 가져오기 결과는 명세104·요구85·WBS173·슬라이드77이며 생성 API는84개다. 생성기에 내장된 XLSX 독립 되읽기는 **9시트·45,428셀 passed**였다. 수용 기준121행·원문 WBS173행·원문 제안/유효 기준8행을 생성했고 경고/의도된 목표-BFF 차이333건은 보존했다. `--check`·OpenAPI validator·docs drift·schema 소비자 smoke·프로젝트 build/test/lint/formatter는 이 담당자가 실행하지 않았으며 Main의 최종 gate와 구분한다.

권장 focused smoke는 다음과 같다. 이 문서 작성자는 실행하지 않았다.

- **프로필:** 모든 키 null 허용/키 누락 거절, name/legalName 구분, 유효 date/uri, `2026-02-30`·부분 날짜·상대 URL 거절(FormatChecker 등 형식 검사를 활성화한다).
- **관계:** []·단일·두 유형 허용, 중복·문자열 대신 배열 아닌 값·미지원 enum 거절. items/unknownTimeItems 모두 적용, companyId 변경/없음·2-hop 전용·과거 pin에서 직접 간선 없음·버전 부재409를 확인한다.
- **소셜:** 두 경로와 응답 provider enum 일치, unsupported 거절, limit1의 전체 순회에 두 제공자 각각 한 번, 마지막 nextCursor=null. 실제 OAuth/state/code 재사용/계정 연결권한 smoke는 향후 구현과 별개다.
- **최신 시세:** 요청 정의에 asOf/graphVersion이 없고 전달 시422 INVALID_REQUEST다. 가격 관측시각/null·source/delay·요청ID를 유지한다. 그래프 pin/차트 기간 변경이 최신 시세를 역사값으로 바꾸지 않아야 한다. 정상 부재3종은200, auth/network/format 장애는503 SOURCE_UNAVAILABLE이며 retryable을 검증한다.
- **로그아웃:** 두 작업의 대응 cookie/익명 OR·선택 CSRF·403/ACCESS_DENIED·Idempotency-Key 명시 제외를 구조 검사한다. 향후 runtime smoke는 활성 세션에서 CSRF 누락/불일치·잘못된 Origin이403이고 익명 fallback이 없으며, 무세션/만료/반복은204와 해당 cookie만 제거하는지 확인한다. 회원/관리자 session을 서로 폐기하지 않아야 한다.
- **보존:** 84개 operationId 및 메서드/경로, S1 두 응답의5필드/6스키마·required/nullable/const/enum/code-point 인용 규칙, FS042 의미별qualification과 유효 사용자 결정은 유지돼야 한다. 앱/UI consumer 구현 합격은 이번 계약-only 결과로 주장하지 않는다.

## Main의 최종 실행 확인

통합 뒤 다음을 실제 실행했다. 목표 계약의 유효성과 생성·소비 가능성에 대한 증거이며 `/api/v1` 서버 구현이나 실제 공급자/OAuth 실행 증거가 아니다.

- `make contracts-check`: OpenAPI, JSON 문서/스키마 4개, 기존 AI 합성 계약 16레코드의 형식 포함 검증과 앱 TOML 검사가 통과했다.
- `make docs-check`: 최신 오후 WBS 입력으로 다시 생성한 **274개 산출물 drift 없음**, hard error **0**, XLSX **9시트·45,428셀 일치**를 확인했다. 경고·목표/BFF 차이 **333건**은 남아 있으며 원문 충돌이 모두 해소됐다는 뜻이 아니다.
- `make secret-check`: 추적·비제외 신규 텍스트 파일 **1,308개**의 제한된 credential signature 검사가 통과했다. 전체 보안 감사나 Git 이력 검사는 아니다.
- 저장소 밖의 임시 소비자 smoke에서 **JSON Schema 30개 사례**가 기대대로 허용/거절됐다. 프로필 null/필수 키/잘못된 날짜, 관계 배열 없음·단일·두 유형·중복·잘못된 타입, 날짜 유무의 두 사건 목록, 회원 제공자, 시세의 정상 부재와 장애 enum 분리를 포함한다. 두 소셜 경로의 제공자 입력 **6개 사례**도 확인했다.
- 기존 검증 환경의 `FormatChecker`에는 선택 의존성인 URI checker가 없었다. 첫 smoke의 잘못된 URI 거절 기대는 이 환경 제약 때문에 실패했다. 이를 스키마 통과로 숨기지 않고, 기존 Node의 WHATWG URL parser로 **절대 웹 URL 허용 / 잘못된 문자열 거절 / 상대 경로 거절 3개 사례**를 별도 실행했다. 전체 RFC URI 검증 완료나 웹 화면의 scheme allowlist 구현을 주장하지 않는다. 새 의존성은 설치하지 않았다.
- 변경 전후 객체를 직접 대조해 **84개 operationId·메서드·경로 동일**, S1 지원 6스키마와 `DocumentSentiment`, `BriefingOutlook`, `CompanyDocument`, `EvidenceResponse` **총 10스키마의 정확한 보존**을 확인했다. 최신 시세의 역사 요청 파라미터 제거, 두 고정 조회의409, 두 로그아웃의 쿠키 대안/조건부 헤더/403 선언도 구조 검사했다.

이번 계약·원문 동기화는 **로컬 변경**이다. 앞선 `69cc006` 원격 CI의 공개 검사·웹·worker 성공과 BFF 자격 증명 미등록 실패는 [GitHub 관측 기록](../development/github-setup.md#ci-경계)에 별도로 있다. 이번 API 변경을 원격 CI가 검사했다고 보고하지 않는다. 사용자 발견 목록이 도착하면 위 A/F/C/H ID와 근거를 기준으로 대조한다.
