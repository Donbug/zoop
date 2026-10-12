# 계약·표본·차이 인계

[이식 가이드](README.md)의 공통 계약 부록이다. **현재 관측**, **목표 설계**, **이식 제안**을 구분한다. 아래 JSON은 모두 작성한 합성 표본이며 실제 기사·회원·모델 출력·HTTP 실행 기록이 아니다. 세션 쿠키/CSRF 값, 비밀키, 개인정보는 포함하지 않는다.

## 1. 언어 독립 불변식

| 계약 | 유지할 의미 | 현재 근거 / 목표와의 차이 |
|---|---|---|
| HTTP/JSON/OpenAPI | 경로 버전·method·상태·headers·camelCase DTO·required/nullable를 명시한다. operationId로 current-target 차이를 추적한다. | 현재 저장 관측 [`bff-openapi.json`](../system/out/bff-openapi.json)은 `/api`; 목표 [`openapi.yaml`](../api/openapi.yaml) §`x-zoop-common-rules`는 `/api/v1`. prefix 교체만으로 완료되지 않는다. |
| session/CSRF | 회원/관리자 cookie 분리, HttpOnly/Secure, 서버 세션과 ownership. 쿠키 인증 쓰기는 Origin+세션 결합 `X-CSRF-Token`; 로그인 전은 Origin/state 검사. logout/차단과 늦은 FE 응답 차단. | 현재 `routers/auth.py::_set_session_cookie`는 HttpOnly/SameSite=lax와 설정 기반 Secure다. 현재 `app.py` CORS 허용 header는 Content-Type이며 현재 세션 schema에는 csrfToken/expiresAt이 없다. 목표 CSRF가 구현됐다는 근거가 아니다. TTL/SSO/토큰 발급 형식은 미정이다. |
| 오류 | 상태와 안정 code를 함께 전달. empty/insufficient_evidence는 기술 장애와 다르다. requestId는 전송 추적, retryable은 승인된 복구 가능성이다. | `errors.py`는 소문자 code/message/details?이고 requestId/retryable 없음. 목표는 대문자 code와 requestId/retryable 필수다. 저장 관측에는 details required drift가 남지만 최신 `schemas.py::ErrorBody`는 serialization override로 optional을 명시하고 생성 `schema.d.ts`도 details?다. backend의 좁은 404/422 시험 2 passed 보고를 별도 기록하며 목표 오류 구현 완료로 확대하지 않는다. |
| 멱등성 | 같은 주체·method·path·key·동일 내용은 기존 결과/작업. 다른 내용은 409. requestId와 jobId/idempotency key를 섞지 않는다. | 현재 chat은 body.jobId로 202 최초/200 재접수, 다른 body는 `chat_job_conflict`, 진행 중 새 job은 `chat_session_busy`. 목표 부작용 POST는 Idempotency-Key 필수(세션 생성/소셜/회원·관리자 로그아웃 제외), PUT/DELETE는 목표 상태로 멱등이다. 로그아웃은 자연 멱등 폐기로 반복204며 새 key 저장 계약은 없다. 나머지 key 관계·저장 기간은 구현/담당 결정 필요다. |
| async job | 최초 접수시 대상·기간·asOf·graphVersion·질문·소유자를 고정한다. 202는 접수, completed는 검증 후 앱 저장 완료다. 창 닫기는 취소가 아니다. | 현재 `ChatJob` enum `queued/running/completed/failed/cancelled`, nullable result/failure, `askedAt` UTC 설명. worker ready는 artifact 보존이며 앱 공개 완료와 다르다. provider 실행 불명은 무조건 재시도하지 않는다. |
| UTC/KST·정밀도 | 정확한 시각은 RFC3339 offset 필수. 같은 instant의 Z/+09:00은 동등하다. 업무 날짜와 07:40/18:10 회차는 Asia/Seoul. year/month/day/unknown은 보존한다. | 목표 common timeAndAsOf. 현재 schema의 일부 timestamp는 단순 string이다. `2026-04-10` 사건을 UTC 자정으로 바꾸지 않는다. asOf, producedAt, observedAt, publishedAt은 서로 다른 뜻이다. |
| decimal money | 금액은 통화·단위·소수 정밀도·반올림 정책과 함께 보존하며 binary float 계산으로 의미를 바꾸지 않는다. Java라면 BigDecimal 등 정확 decimal을 적용한다. | 현재 및 목표 `HoldingOut/QuoteValues/PricePoint`는 JSON number다. **decimal-string wire는 아직 채택/구현되지 않은 이식 제안**이다. DTO 표현·scale/rounding/허용범위를 결정하고 golden을 만든 뒤 writer를 연다. JSON number 유지 시도 decimal parser/serializer와 FE 표시 정밀도를 검증한다. |
| null/0/missing | null은 미제공/미산출, 0은 관측한 실제 0, missing은 선택 필드 미전달이다. null을 0·false·빈 문자열로 바꾸지 않는다. | `HoldingOut.marketValue/weight`, `QuoteValues.asOf/change`, `EvidenceResponse.quoteVerified`, `ChatJob.result` nullable. 판정 null은 유효 산출물 없음, undetermined는 평가했으나 방향 근거 부족이다. reason/status를 함께 유지한다. |
| Unicode evidence | 고정 정제 textArtifact/documentVersion에 Unicode code point `[start,end)`로 정확 인용을 적용한다. normalization을 검증 순간에 하지 않는다. raw locator/cleanerVersion도 보존한다. | 현재 `EvidenceResponse`는 articleId/articleVersion/quote/start/end; `quoteVerified=null`은 본문이 없어 미검증이다. worker `EvidenceRef`는 offsetUnit=`unicode_code_point`, textArtifactId/rawLocatorIds 명시. JS/Java UTF-16 index를 그대로 사용하지 않는다. |
| opaque IDs | company/document/event/issue/relation/artifact/job/attempt/request/version의 identity와 namespace를 보존한다. 문자열 패턴이 내용 의미가 아니다. | PoC issue_id는 사건 묶음이다. topic issueId로 이름만 바꾸지 않는다. 현재 graph kind=issue의 뜻 변경은 schemaVersion+caller cutover 대상이다. 티커가 같아도 회사/거래소를 자동 병합하지 않는다. |
| publication/visibility | 불변 artifact pin ∩ 현재 access ∩ 현재 visibility로 반환한다. ready/eligible/검수 allow는 published와 다르다. HOLD/REJECT와 철회 자료는 직접 ID·옛회차·cache에도 노출하지 않는다. | 목표 설계 및 AI 설계 §6. 현재 `GraphStore.publish`의 expectedVersion CAS나 옛 pin 철회 전파를 완료로 단정하지 않는다. 후보 projection+양쪽 read 준비 후 active pointer 전환, save_only/project_only/publish_only는 모델 재호출과 분리한다. |

## 2. 현재 `/api`와 목표 `/api/v1` 차이 추적

전체 행의 정본은 [`docs/system/out/api-differences/`](../system/out/api-differences/)다. 이 표는 이식 실패 위험이 큰 대표 항목이다. 생성 차이 파일은 **저장 관측 기준**이므로 병행 구현 이후 새 schema와 대조해야 한다. 파일을 수동으로 완료 표시하거나 생성물을 직접 고치지 않는다.

| 차이 | 현재 → 목표 | 근거와 전환 책임 |
|---|---|---|
| 경로/operation | `/api/...` → `/api/v1/...`, 목표 operationId를 추적 키로 유지 | 모든 caller/client/type 갱신. `[operationId].json`의 targetPath/bffPath |
| 세션 응답/보안 | csrfToken·expiresAt 없음 → 명시 전달, Origin/CSRF/Secure 요구 | [`getMemberSession.json`](../system/out/api-differences/getMemberSession.json); 앱 BE 보안 adapter + FE client |
| 공통 오류/응답 헤더 | lower-case code, requestId/retryable 없음 → 목표 envelope+X-Request-ID | `errors.py`, 목표 ErrorBody/common requestIds; 모든 오류 consumer |
| job 제출 | body.jobId → body 유지와 필수 Idempotency-Key/CSRF, frozen asOf/graphVersion | [`submitQuestion.json`](../system/out/api-differences/submitQuestion.json); key 불일치 정책 확정과 transaction 검증 |
| 읽기 목록 | 현재 endpoint별 응답/필터 → cursor/limit/nextCursor, pin과 metadata.partial/failures/requestId | [`listCompanyDocuments.json`](../system/out/api-differences/listCompanyDocuments.json), [`searchCompanies.json`](../system/out/api-differences/searchCompanies.json) |
| 근거/공개 버전 | 현행 근거 DTO → version/asOf/current visibility gate, S1 wire의 문서/텍스트 버전 매핑 | [`getEvidence.json`](../system/out/api-differences/getEvidence.json), [`getGraph.json`](../system/out/api-differences/getGraph.json); pinned/latest 일관성 |
| 시각/금액 | 현행 사건 from/to의 offset 생략은 KST 해석, 일부 plain string/JSON number → 목표 offset 필수·precision 엄격화와 정확 decimal 계산 | `prototype/bff/README.md` §시간, 목표 timeAndAsOf 및 HoldingOut. decimal wire 형태는 아직 계약 미정이며 바꿀 경우 producer/consumer/fixture 모두 함께 전환 |
| 그래프 identity/관계 의미 | 현행 PoC issue_id 사건 묶음과 파생 SHARES_ISSUE → 별도 event/topic namespace와 검증된 유형 관계 설계 | `prototype/bff/README.md` §그래프, AI 설계 §3. 공동 사건 참여를 SUPPLIES/COMPETES_WITH/INVESTS_IN으로 이름만 바꾸지 않는다. DTO 의미 변경은 schemaVersion과 모든 caller 전환이 필요하다. |
| 새 생산자/프로토타입 제외 | 저장 관측에는 document summary 생산자 없음; mock IdP·snapshot 경로·sandbox는 현행 구현 세부 | S1은 아래 범위. 소셜 실 제공자/재무/새 AI stage/운영 연결이 이미 있다는 뜻이 아니다. |
| 기업 프로필 | 기존 sector 유지 + legalName/market/representative/foundedDate/websiteUrl required·nullable. 날짜=date, 공식 주소=uri. name은 표시명이다. | [`getCompany.json`](../system/out/api-differences/getCompany.json); 기업 마스터 공급원 확인과 앱 BE/FE DTO 전환이 필요하다. 자료 없는 값은 null이며 표시명·추정 날짜/URL로 채우지 않는다. |
| 사건 관계 맥락 | EventSummary.relationTypes는 요청 companyId의 직접 승인 INVOLVES/STRUCTURALLY_RELATED_TO만 uniqueItems로 전달한다. companyId 없음·직접 간선 없음·2-hop 전용은 []다. | [`listEvents.json`](../system/out/api-differences/listEvents.json); items/unknownTimeItems 양쪽에 같은 asOf/graphVersion을 적용한다. 감성·공급/경쟁 유형과 별개다. |
| 최신 시세 | getCompanyQuote의 asOf/graphVersion 요청 제거. 전달 시422 INVALID_REQUEST로 거절한다. 차트 기간과 무관하게 공급자의 가장 최근 관측값을 읽고 quote.asOf·출처·지연을 유지한다. 정상 부재3종은200, 실제 인증/네트워크/형식 장애는503 SOURCE_UNAVAILABLE이다. | [`getCompanyQuote.json`](../system/out/api-differences/getCompanyQuote.json); 활성 그래프가 없어도 회사 마스터/시세 조회가 가능한 독립 경계를 마련한다. latest는 실시간 보장이 아니다. retryable은 원인에 맞추며 현재 BFF 장애 성공 분기는 별도 이행한다. |
| 회원 소셜 제공자 | SocialProvider.id 및 authorize/callback 경로 enum은 google/kakao다. 전체 커서 순회에 각각 한 번이며 개별 페이지에 둘 다 있을 필요는 없다. | [`listSocialProviders.json`](../system/out/api-differences/listSocialProviders.json), [API v2 검토](../evidence/api-v2-review-2026-10-08.md); mock IdP는 실 OAuth가 아니다. Origin/state·본인/계정 연결 권한 검증을 유지하며 관리자 SSO는 미정이다. |
| 로그아웃 조건부 보안 | 활성 해당 쿠키에는 Origin/세션 결합 CSRF 필수, 실패403 ACCESS_DENIED이며 익명 분기로 우회하지 않는다. 해당 세션 없음/무효/만료이면 타 세션을 변경하지 않고 해당 cookie만 제거·반복204다. | [`logOut.json`](../system/out/api-differences/logOut.json), [`logOutAdmin.json`](../system/out/api-differences/logOutAdmin.json); 선택 cookie/CSRF 표현은 런타임 조건을 자동 강제하지 않는다. 작업자 목표 계약 정정안이며 현재 BFF 구현 완료를 뜻하지 않는다. |

목표 API 공통 규칙은 사용자 잠정 채택/시연 기준이다. teamQuestions, FS042 재무/시점그래프 충돌, 키 보존 기간·세션 만료·성능 한도는 원문 정정/담당 결정으로 남긴다.

## 3. 합성 contract 표본과 읽기 대조

### 현재 HTTP request/error 표본

아래 요청 body는 **관측 ChatJobRequest**의 필수 필드·패턴과 맞추어 작성했다. cookie/header/서버 응답을 실행하지 않았다. target도 같은 body를 쓸 수 있지만 새로운 header 요구를 충족한 전체 요청은 아니다.

```json
{"jobId":"job_syn_001","question":"합성 기업의 확보된 근거를 설명해 주세요."}
```

현재 관측 ErrorBody와 맞는 합성 409 body는 다음과 같다. `details:null`은 관측 required 필드에 맞춘 것이며 handler가 언제나 이를 출력한다고 주장하지 않는다.

```json
{"error":{"code":"chat_job_conflict","message":"같은 작업 ID에 다른 요청 내용이 있습니다.","details":null}}
```

목표 설계 409 표본은 별도로 둔다. 이 응답이 현재 BFF에서 출력됐다는 뜻이 아니다.

```json
{"error":{"code":"IDEMPOTENCY_CONFLICT","message":"같은 키에 다른 요청 내용이 있습니다.","requestId":"request_syn_002","retryable":false}}
```

### 숫자·시간·근거 이식 vector (전체 endpoint DTO가 아님)

이 표본은 정밀도/offset 차이를 드러내는 합성 contract fixture다. decimal 문자열 두 개는 **이식 제안의 계산 입력**이지 현행 money DTO 타입이 아니다. 개인정보나 실제 모델 결과는 없다.

```json
{
  "fixtureKind":"synthetic-migration-vector",
  "provenance":{"sourceKind":"synthetic","executionMode":"replay","recordingKind":"authored-test"},
  "instantUtc":"2026-10-07T22:40:00Z",
  "instantKst":"2026-10-08T07:40:00+09:00",
  "businessDateKst":"2026-10-08",
  "unknownEventTime":{"value":null,"timePrecision":"unknown"},
  "decimalOperands":["0.10","0.20"],
  "expectedDecimalSum":"0.30",
  "currency":"KRW",
  "unavailableMarketValue":null,
  "observedZero":0,
  "unjudgedSentiment":null,
  "evaluatedLabel":"undetermined",
  "textArtifactId":"text_syn_unicode_1",
  "documentVersion":"dv_syn_unicode_1",
  "text":"A📈가 B",
  "evidence":{"offsetUnit":"unicode_code_point","start":1,"end":3,"quote":"📈가"},
  "publicJobStatus":"completed",
  "workerState":"ready",
  "publicationState":"withheld"
}
```

이 vector의 핵심 기대값은 다음과 같다.

- 두 시각은 같은 instant지만 KST 업무 날짜는 10-08이다. unknownEventTime은 정확한 자정으로 채우지 않는다.
- decimal `0.10+0.20=0.30`; 통화/scale는 별도 정책이며 이 예제가 모든 KRW 금액의 소수 자릿수를 정하지 않는다.
- code point slice `[1,3)`은 `📈가`다. JS/Java 문자열 index의 `[1,3)`은 같은 구간이 아니다. code point 배열이나 명시적 index 변환을 사용한다.
- null 시장가치는 0이 아니고 null 판정은 undetermined가 아니다. worker ready와 public job completed만으로 withheld artifact를 공개하지 않는다.

기존 합성 fixture [`prototype/bff/fixtures/poc-synthetic-inspect.json`](../../prototype/bff/fixtures/poc-synthetic-inspect.json)도 읽었다. 첫 issue에는 두 기사/mention이 있고 두 quote는 각각 `[0,39)`, `[0,45)`다. `event_time=2026-04-10`, `published_at=2026-09-16T00:00:00+00:00`, `allow_model_send=false`를 보존한다. 사건 날짜와 문서 공개시각을 혼동하거나 합성이라는 이유로 모델 전송을 허용하지 않는다. PoC snake_case 저장 DTO는 앱/worker camelCase로 **명시적 adapter**를 거쳐야 한다.

**확인 종류:** 관측 OpenAPI와 JSON 표본을 읽어 필수값·오류·offset·시간·decimal 기대값을 대조했다. 새 서버·Java·브라우저·provider를 실행한 결과가 아니며 전체 JSON Schema 검증이나 cutover acceptance 통과를 뜻하지 않는다. 구체적 자동 대조 결과는 아래 확인 기록에 남긴다.

## 4. S1 worker 인계 범위

S1 구현 소유자 AiDocumentBackend가 최종 계약과 실행 결과를 전달했다. [`ai-system.md`](../design/ai-system.md)의 현재 범위는 `schemaVersion=zoop-ai-s1-1`, strict camelCase, 문서 `document-summary`/`document-sentiment`/`semantic-verification` 세 stage와 기존 생성 능력을 보존한 `briefing-outlook`이다. 생성 schema의 네 kind와 OutlookInput/OutlookAnswer를 직접 읽었다. backend 실행 보고와 이 담당자의 정적 확인을 구분하며 전체 AI·운영 품질 완료로 표시하지 않는다.

**기존 기능 보존:** 기존 `briefing-outlook`의 provider/replay 생성 기능은 폐기하지 않고 worker로 이행했다. OutlookInput은 roundId/scheduledAt/graphVersion/reviewRevision/ruleRevision/issues/documentSentiments/marketVariables/sourceId/grantId/grantRevision을 고정하며, OutlookAnswer는 label/rationale/issueIds를 반환한다. 이식 시 선택 kind에 맞는 입력 DTO를 사용하고 문서 입력으로 회차를 대체하지 않는다. 회차 검증은 `legacy-outlook-exact-1`의 정확 이슈 참조·금지 표현 정책이고 `validation.semantic=null`이다. 이를 문서의 별도 의미 검증과 동급이거나 supported로 간주하지 않는다. 강화된 의미 검증과 신규 기업/시장 요약은 여전히 후속 설계 범위다.

| 자료/경계 | 현재 확인 상태 | 후속 인계 기준 |
|---|---|---|
| `prototype/ai-worker/src/zoop_ai/contracts.py` | 소스 검사. `EvidenceRef`의 code point, provenance mode 일치, grant expiry timezone, immutable text digest/raw locator 검사 정의를 읽었다. | wire schema는 이 구현과 일치해야 한다. sourceHash는 canonical JSON UTF-8 SHA256이므로 raw text hash나 Java 기본 직렬화 hash로 바꾸지 않는다. |
| [`docs/api/ai-contract.schema.json`](../api/ai-contract.schema.json) | JSON Schema 2020-12 생성 파일을 읽었다. Submit의 네 kind, EvidenceRef/Provenance/Failure와 OutlookInput/OutlookAnswer, nullable Validation.semantic을 확인했다. | backend는 최종 `validate_contracts.py` 16 records passed를 보고했다. 생성 keyword 부분집합 validator이며 임의 JSON Schema 전체 구현이 아니다. 이 담당자는 재실행하지 않았다. |
| [`synthetic-document/`](../../prototype/ai-worker/fixtures/contracts/synthetic-document/)의 `jobs.json`, `replay.json`, `snapshot.json`, `grants.json` | 확정 경로를 전달받고 jobs/replay/grants를 읽었다. snapshot은 실행 입력 경로로 인계하며 이번에 내용을 다시 검증하지 않았다. | authored synthetic/replay provenance와 explicit grant를 유지한다. 정상 provider 품질이나 실제 기사 라이선스 근거로 사용하지 않는다. |
| [`synthetic-outlook/`](../../prototype/ai-worker/fixtures/contracts/synthetic-outlook/)의 `jobs.json`, `replay.json`, `snapshot.json`, `grants.json` | 확정 네 파일 경로와 첫 job/replay 응답을 읽었다. 문서 네 fixture와 schema 하나를 합쳐 총 9개 계약 파일이다. | documentSentiments를 포함한 정확 입력/pin/config digest를 보존한다. 문서 판정이 추가된 상태를 빈 documentSentiments 표본에 재사용하면 replay_input_mismatch이며 fixture를 임의 완화하지 않는다. |
| BFF document/evidence consumer | `ai-system.md`와 backend 보고: 네 결과 import가 available, CLI 네 작업 ready, replay 8회/live 0회. `documentSummary`, `analysisStatus`, `analysisProvenance`, `resultVersion`, `documentVersion`을 저장 결과 GET에 제공한다. 이번 담당자가 서버/consumer를 재실행한 관측은 아니다. | 기존 sentiment DTO 유지. S1은 문서 두 consumer의 deny/version/hash gate이며 전체 과거 채팅/회차/pin 의존성 closure는 S4 계획이다. |
| 후속 S2–S7 | 설계 범위다. | 수집/주제/관계/영향/챗봇/기업·시장 요약/개인화 전체 완료로 확대 해석하지 않는다. |

worker 오류의 code/state/resumeMode는 worker JSON 정본을 그대로 대조하고 앱 목표 HTTP 오류로 mapping한다. HTTP 409·worker failure·semantic HOLD를 동일한 문자열로 합치지 않는다. 원본 PoC를 변경하거나 worker DB를 Spring에서 공유할 필요는 없다.

**gate-2 수정 뒤 권한·캐시·공개·receipt 이식 계약:** 현재 `zoop-document-gate-2`/`zoop-document-2026-10-08-2`는 공개 limitations와 `assertionKind=limitation` claim을 순서까지 1:1로 묶어 의미 검증 coverage에 넣으며, 본문·rationale은 non-limitation claim으로만 조립한다. gate-1 raw 이력은 삭제하지 않지만 `document_policy_outdated`로 cache/publication을 보류하므로 새 gate-2 job이 필요하다. BFF current grant는 서버 소유 **전체 registry snapshot**으로 별도 갱신하고, artifact의 과거 grant는 실행 영수증일 뿐 현재 authority를 쓰거나 철회를 되돌릴 수 없다. 부분 registry는 누락 grant를 fail-closed로 제거하며 opaque revision을 정렬해 최신을 추측하지 않는다. live grant recipient/cache identity는 승인 endpoint의 `providerRevision`에 결합하고 제출 endpoint와 실제 endpoint가 다르면 송신하지 않는다. 동일 attempt는 고정 identity·불변값을 보존한 채 `started→received→validated`와 처음 알려진 usage만 전진하며, terminal job 재수입은 no-op여서 A→B→A 재수입이 B의 공개 선택을 바꾸지 않는다. standalone semantic 응답 뒤에도 current grant를 다시 확인하고 철회 시 receipt만 보존하며 artifact/cache는 만들지 않는다. HOLD/REJECT artifact 저장 뒤 ready 저장 실패는 current grant·fence 아래 같은 artifact를 재사용하는 save_only 복구이며 provider를 다시 호출하지 않는다. 기존 outlook의 한국어 금지 예측어는 공백 정규화 후 검사하지만 여전히 legacy exact 정책이고 `semantic=null`이다. 근거는 [`ai-system.md` §호출/권한/공개 gate](../design/ai-system.md), `zoop_bff/ai_worker.py::replace_current_grants`, `document_analysis.py`의 필수 `--grants`다. 공개 wire DTO 모양은 바뀌지 않았으며 독립 review 재확인 완료를 주장하지 않는다.

수입 CLI는 `--grants`가 필수다. 다음은 `replay_fixture.py`로 이미 만든 격리 합성 상태에 결과를 **수입만** 하는 예시이며 이 담당자가 새로 실행하지 않았다. 실제 출처에 합성 grant를 적용하지 않는다.

```sh
ZOOP_SNAPSHOT_PATH="$PWD/prototype/ai-worker/fixtures/contracts/synthetic-document/snapshot.json" \
ZOOP_COMPANY_CATALOG="$PWD/prototype/ai-worker/fixtures/contracts/synthetic-document/snapshot.json" \
PYTHONPATH=prototype/bff/src prototype/bff/.venv/bin/python prototype/bff/scripts/document_analysis.py import \
  --state-dir /tmp/zoop-ai-doc-bff-demo --worker-state /tmp/zoop-ai-doc-worker-demo \
  --grants prototype/ai-worker/fixtures/contracts/synthetic-document/grants.json \
  --job-id synthetic-SYNTH-A-document-summary
```

현재 S1 예시는 `jobs.json.jobs[0]`의 `jobId=synthetic-SYNTH-A-document-summary`, `documentId=doc-synthetic-s1`, `mode=replay`, `candidate=null`이다. 문서 version은 `dbb0e5cf12a24caba42c041b32a27744bbc7f972ba1f493db4b87d2bb4a26b0d`, sourceHash는 `5fae8474f64dceae744f30e943a81d248a53e6b355d8fc18cd00b6ebb8b66548`이며 두 값은 역할이 다르므로 서로 대체하지 않는다. 본문 `🚀 합성 알파의 매출이 늘었다. 합성 베타의 비용이 늘었다.`의 summary citation은 `[0,17)`과 `[18,33)`으로 각각 `🚀 합성 알파의 매출이 늘었다.`와 `합성 베타의 비용이 늘었다.`를 가리킨다. 직접 정적 계산으로 required/schemaVersion, canonical JSON sourceHash, documentVersion 일치와 두 exact quote를 확인했다. replay의 기업별 판정 표본은 positive/negative이고 별도 semantic 응답은 supported다. 이 authored 결과를 실제 모델의 판정으로 표시하지 않는다.

회차 표본 `synthetic-outlook/jobs.json.jobs[0]`은 `roundId=brf-2026-10-08-evening`, `scheduledAt=2026-10-08T18:10:00+09:00`, `graphVersion=v1`, `reviewRevision=0`, `ruleRevision=0`과 이슈 `event-synthetic-s1` 하나를 고정한다. `documentSentiments=[]`이며 세 시장 지표는 unavailable/value=null이므로 0으로 채우지 않는다. replay 응답의 `label=undetermined`, `issueIds=[event-synthetic-s1]`는 입력 이슈를 정확히 참조한다. backend 최종 보고에서는 실제 CLI로 이 회차가 published, worker 1 ready/replayCalls 1/providerAttempts 0이었고, 반복 실행은 동일 발행값/workerJobs=[], 0이슈 출근 회차는 published/outlook null/workerJobs=[]였다. 실제 `/api/briefings?date=2026-10-08&edition=evening` GET도 동일 발행값을 확인했다. 재현 명령과 실패→fresh 분리 상태 처리 근거는 [`ai-system.md` §기존 outlook 재현·§실행 결과](../design/ai-system.md)에 있으며 이번 이식 담당자가 실행을 반복하지 않았다.

## 5. RepoPrep에 전달할 CI target 기준

**이 문서는 CI를 만들거나 실행하지 않는다.** 선택되지 않은 언어의 빈 build target, Java app scaffold, 설치 step을 추가하지 않는다. RepoPrep는 스택 결정 후 실제 디렉터리·명령·입출력·side effect를 등록한다. 지금의 명령은 확인한 script 이름이지 이번 실행 결과가 아니다.

| target 책임 | 현재 이용 가능한 입력 | 스택 결정 후 연결할 검증 |
|---|---|---|
| 공통 HTTP contract | 목표 OpenAPI, cached observation, operationId별 차이, 위 synthetic request/error/vector | schema/ref 검사, current-target gap, HTTP golden producer/consumer 대조. 생성기가 문서를 갱신하는 side effect를 명시한다. |
| FE React 유지 | `prototype/web/package.json`의 `tokens`, `typecheck`, `test`, `build`; `api:types`는 현재 서버 URL 입력 | 타입·상태·접근성·HTTP consumer·빌드. tokens/build/typecheck는 생성 파일에 쓰므로 순서/작업 디렉터리를 고정한다. api:types를 무조건 target 계약 생성으로 사용하지 않는다. |
| FE 다른 framework | 같은 HTTP golden·토큰·화면 상태·Figma 목표 | 해당 framework의 실제 타입/단위/consumer/브라우저 target. framework 이름·명령·버전을 지금 추정하지 않는다. |
| FastAPI 유지 | `prototype/bff/pyproject.toml`의 pytest testpaths=`tests`, 기존 합성 fixture | 인증/CSRF·오류·owner·idempotency·job·read/write/version 검증. 공유 var/실데이터/외부 API가 아닌 격리 상태 사용. |
| Java/Spring 선택 | 같은 OpenAPI/HTTP golden/worker JSON/불변식 | 실제 선택 build tool로 compile/test 및 HTTP contract/transaction/concurrency 검증. Gradle/Maven·JDK/Spring 버전을 미리 강제하지 않는다. |
| Python worker 유지 | `prototype/ai-worker/pyproject.toml`, `uv.lock`, 문서/outlook schema·fixture, `zoop-ai` CLI entrypoint | 고정 lock의 offline/frozen 환경과 실제 tests/validator/wheel target을 사용한다. 문서 semantic gate와 기존 outlook exact policy를 구분하고 published 반복/0이슈 무호출을 포함한다. 합성 provenance·disabled live를 유지한다. |
| worker 다른 runtime | 동일 schema/fixtures/recovery 시나리오 | 해당 runtime의 schema/parser/runner/provider-adapter contract 검증. 원장/DB 공유 없이 producer 비교. |
| 통합·rollback | schema/manifest/receipt/frozen artifact + identity/job/write migration 결정 | README의 1→6 게이트. 새 쓰기 보존·구 decoder·권한/visibility의 복구 결과를 인수 증거로 남긴다. |

이 이식 담당자는 의존성·lockfile·workspace·GitHub workflow를 변경하지 않았다. 현재 worker lock은 backend가 확정한 `prototype/ai-worker/uv.lock`이다. manifest는 Python >=3.12, Pydantic 2.13.5·HTTPX 0.28.1과 dev pytest 9.1.1, `zoop-ai` entrypoint 및 tests 경로를 명시한다. RepoPrep는 이미 있는 lock/manifest와 [`ai-system.md` §잠금 파일](../design/ai-system.md)의 offline/frozen 검증 명령을 기준으로 CI를 연결한다. 이 관측 버전을 Java/Spring 등 미선택 스택의 버전으로 일반화하지 않는다. 실제 `.env`, secret, 실회원 데이터, 원본 PoC의 읽기 전용 상태를 CI input으로 수집하지 않는다. paid/provider integration target은 명시적 별도 승인 없이는 실행하지 않는다.

## 6. 확인 기록

- 읽기 대조: 저장된 current OpenAPI의 ChatJobRequest, ChatJob, ErrorBody, EvidenceResponse, QuoteValues, SessionResponse와 target common rules/HoldingOut을 샘플로 확인했다.
- 자동 대조(2026-10-08): Python 표준 라이브러리로 이 문서의 JSON 4개, 저장 관측 OpenAPI, 기존 합성 fixture 첫 issue만 읽었다. request의 required/pattern/length와 현재 error required 필드가 일치했다. 두 시각의 instant/KST 날짜, Decimal 합계 `0.30`, code point quote `📈가`, null/0 구분과 두 mention의 정확 인용 `[0,39)`, `[0,45)`을 확인했다. 관측 경로는 79개, `/api/v1/`은 0개였다. 전체 schema validator·테스트 suite·서버·브라우저·provider는 실행하지 않았으며 파일 쓰기나 설치도 없었다.
- S1 확정 후 정적 대조: 생성 schema의 Submit/EvidenceRef required/const와 실제 첫 합성 job을 비교했고, canonical JSON UTF-8 SHA256 sourceHash 및 `[0,17)`, `[18,33)` quote/documentVersion 일치를 확인했다. 전체 schema validator·CLI·provider·서버를 재실행하지 않았다.
- 오류 수정 당시 증거: `schemas.py::ErrorBody`의 `json_schema_serialization_defaults_required=False`와 생성 `schema.d.ts`의 `details?`를 직접 읽었다. backend는 실제 404 omission/422 details의 schema 시험 2 passed, 최신 8871 OpenAPI에서 타입 1회 export 성공을 보고했다. 422 입력은 `prices?period=invalid`이며 `from=bad`의 custom ApiError는 details를 생략한다. 이 시점 BFF baseline은 304 passed/기존 deprecation warning 1개였다. 이후 7개 수정 증거와 구분하며 옛 저장 관측 JSON도 역사 기준선으로 보존한다.
- 7개 finding 수정 전 backend 인계 증거: 당시 AiDocumentBackend 보고는 worker 37 passed, BFF 304 passed, contract validator 16 records passed, offline frozen sync/wheel 성공 및 문서·회차 실제 CLI/GET 관측이었다. 이 수치는 그 뒤 발견된 7개 finding 해결 증거가 아니다. 이 담당자는 해당 실행을 재검증하지 않았고 schema·표본·manifest 검사만 수행했다.
- gate-2 최종 통합 증거: [`ai-system.md` §실행으로 확인한 결과](../design/ai-system.md)는 worker 42 passed, BFF 310 passed/기존 warning 1개, validator 16 records passed 및 synthetic document/outlook CLI 재현을 기록한다. 독립 소스 리뷰의 7개 finding과 후속 회귀 수정은 완료됐으며 마지막 리뷰의 잔여 finding은 0개였다. 이는 전체 보안 감사나 운영 품질 인증이 아니다. 이식 문서 담당자는 source/fixture 대조만 했으며 해당 실행 증거를 문서 수정 자체의 시험으로 주장하지 않는다. 실제 model HTTP는 0이고 라이선스·예산 승인은 별도다.
- 최초 이식 문서 변경은 `docs/migration/README.md`와 이 문서에 한정됐다. 이후 통합 기록과 원격 반영 승인은 [현재 작업 기준](../share/day-work-2026-10-08.md)을 따른다. 본개발 스택 선택이나 원본 PoC 수정까지 허용하는 승인이 아니다.
