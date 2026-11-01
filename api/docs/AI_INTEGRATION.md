# AI 분석 transport 클라이언트 (api → ai/service)

앱 백엔드가 S1 분석, S2 추출·S3 관계 job, 챗봇 모델 단계와 [실행 계획 접수](#계획-접수-클라이언트)를 호출하는 **전송 계층 클라이언트**와 [관리자 계획 분석 큐](#관리자-계획-분석-큐)를 설명합니다. 서버 쪽 정본은 [`ai/service/README.md`](../../ai/service/README.md)와 [`docs/api/internal-ai-openapi.yaml`](../../docs/api/internal-ai-openapi.yaml), 작업 JSON 스키마는 [`docs/api/ai-contract.schema.json`](../../docs/api/ai-contract.schema.json)입니다.

## 지금 있는 것과 없는 것

| 제공하는 기능 | 소비 기능·운영 경계 |
|---|---|
| `AiAnalysisClient`의 `submit` / `status` / `result` / `cancel` / `recover` | 최종 사용자 인증·세션·회원/관리자 권한은 앱 소유이며 이 클라이언트가 판정하지 않습니다. |
| S2 추출 5개·S3 관계 7개 operation과 실행 모드 기대값, 엄격한 응답 결속 | 별도 `analyze_plan` 큐가 고정 S2/S3를 진행시켜 내용 없는 처리 인계를 저장합니다. 수집·재검증·투영 실행기나 공개 발행 스케줄러는 구현하지 않습니다. |
| `PlanAdmissionClient`의 정확한 계획 접수·조회, 불변 manifest와 정책 권한 상태 검증 | 앱은 운영자 정책을 바꾸거나 허가 파일을 쓰지 않습니다. 접수 자체는 S2/S3 실행·예산 승인·공개 활성화가 아닙니다. |
| 가족별 독립 설정과 기본 비활성 bean | 결과의 앱 저장·사용자 격리·현재 권리 재확인·공개 여부는 소비 기능이 소유합니다. S1은 [문서 분석](DOCUMENT_ANALYSIS.md), 그래프는 [handoff 인계](GRAPH_READ_HANDOFF.md)를 참고합니다. |
| 실제 서비스·설치된 pipeline을 사용하는 합성 replay 연동 검사 | S2-1 수집 HTTP, 운영 정책·유료 실행·처리량별 정기 발행 보장은 이 전송 계층의 기능이 아닙니다. |

클라이언트는 서비스 주체(service principal)로 호출하는 **앱**이며 최종 사용자를 모릅니다. AI 오류를 공개 `ErrorCode`로 바꾸거나 앱의 인증·공개 권한을 대신하지 않습니다.

## 코드 위치

| 위치 | 책임 |
|---|---|
| `com.zoop.ai` | S1 공개 타입: `AiAnalysisClient`, `AnalysisSubmission`, `AnalysisJobStatus`, `AnalysisResult`, `AnalysisAcknowledgement`, `UntrustedAnalysisPayload`, `AiClientSettings`. 공통: `AiOperation`, `PipelineJob`(S2/S3 공통 상태·dispatch·delivery 어휘), 예외(`AiClientException` → `AiServiceRejectionException` → `AiServiceErrorException`/`ExtractionServiceErrorException`/`RelationServiceErrorException`, `AiTransportException`, `AiClientConfigurationException`). sealed 계층이라 예외는 한 패키지에 둡니다 |
| `com.zoop.ai.extraction`, `com.zoop.ai.relation` | S2 `ExtractionClient`·`ExtractionSubmission`·`ExtractionJobStatus`·`ExtractionResult`·`UntrustedExtractionPayload`, S3 `RelationClient`·`RelationSubmission`·`RelationJobStatus`·`RelationResult`·`UntrustedRelationPayload`·`RelationReviewRequest`·`RelationOperationStatus` 등 |
| `com.zoop.ai.plan` | `PlanAdmissionClient`, `PlanReference`, `PlanAdmission`, `PlanManifest`: 정확한 계획 참조·접수·현재 정책 권한과 단위별 S2/S3 실행 참조 |
| `com.zoop.ai.http` | JDK 21 `java.net.http.HttpClient` 공통 전송(`AiHttpTransport`)과 가족별 구현·엄격한 JSON 해석. 계획은 `HttpPlanAdmissionClient`·`PlanAdmissionWire`가 담당합니다. 새 라이브러리는 필요하지 않습니다. |
| `com.zoop.ai.config` | 가족별 `@ConfigurationProperties`와 조건부 bean. 계획 클라이언트의 prefix는 `zoop.ai.plan-admission-client`입니다. |

호출자가 경로·명령·소유자를 바꾸는 인터페이스는 없습니다. 각 클라이언트는 계약에 정해진 내부 HTTP 경로만 사용하며, 앱의 계획 클라이언트에는 운영자 정책 변경 메서드가 없습니다.

## 설정

기본은 **비활성**이며 AI 설정은 기동에 필요하지 않습니다(AI 때문에 필요한 선행 조건이 없다는 뜻입니다). `bootRun`에는 기존처럼 PostgreSQL 연결 설정(`DB_*`)과 DB가 여전히 필요하며, DB 서버를 띄운 기동은 이 작업에서 실행하지 않았습니다. 이름만 공개 파일(`application.yml`, `.env.example`)에 있고 값·토큰은 저장소에 없습니다.

| 환경 변수 | 기본값 | 규칙 |
|---|---|---|
| `ZOOP_AI_CLIENT_ENABLED` | `false` | `true`일 때만 bean 생성. 이때만 아래를 검증 |
| `ZOOP_AI_CLIENT_BASE_URL` | 없음 | 필수. 비-loopback은 `https`. `http`는 `localhost`/`127.0.0.1`/`[::1]`만. user info·query·fragment 불가. 역프록시 경로 prefix는 평범한 세그먼트만 |
| `ZOOP_AI_CLIENT_TOKEN` | 없음 | 필수. 운영자가 발급한 서비스 bearer 토큰(`[A-Za-z0-9._~+/-]{32,512}=*`). 서버는 SHA-256 digest만 저장 |
| `ZOOP_AI_CLIENT_CONNECT_TIMEOUT` | `3s` | 100ms–30s |
| `ZOOP_AI_CLIENT_REQUEST_TIMEOUT` | `30s` | 100ms–120s, 한 호출의 **전체** 마감 |
| `ZOOP_AI_CLIENT_MAX_RESPONSE_BYTES` | `8388608` | 65536–33554432 |

활성인데 URL·토큰·시간 값이 잘못되면 기동이 실패합니다. 메시지는 설정 이름만 말하고 값은 말하지 않으며(`AiClientSettings`, `AiClientProperties.toString()`은 토큰을 가림), 토큰은 예외·로그·`toString`에 나오지 않습니다. 요청 본문 상한은 서비스와 같은 2,000,000바이트로 고정입니다. 서버 쪽 principal·scope·토큰 digest 설정은 [서비스 README](../../ai/service/README.md#설정환경-변수-시작-때-한-번-읽고-실패-시-닫힘)에 있고 운영자가 서비스 밖에서 만듭니다. 이 저장소와 에이전트는 토큰을 만들지 않습니다.

HTTP/1.1, 프록시 없음, 쿠키 없음, **리다이렉트 안 따름**, 자동 재시도 없음, 호출당 요청 1개입니다. bearer 토큰은 설정한 base URI로만 가고 3xx를 받으면 `REDIRECT_REFUSED`로 끝납니다. 응답은 크기 상한에서 읽기를 멈춥니다.

## 호출 규칙

아래는 S1 작업의 호출 규칙입니다. S2/S3, 챗봇 단계와 계획 접수의 키·상태 의미는 각각의 절을 따르며, 모든 가족이 같은 전송 제한과 응답 무결성 검사를 공유합니다.

- `Idempotency-Key`는 항상 `jobId`입니다(`AnalysisSubmission`이 jobId만 받고 키를 따로 받지 않음). jobId는 서버 규칙 `[A-Za-z0-9_.-]{1,120}`에서 경로 세그먼트 `.`·`..`를 뺀 값이며 네트워크 호출 전에 검사합니다.
- `inputJson`/`provenanceJson`은 계약의 `Submit` 객체를 그대로 담은 JSON 객체이며 클라이언트는 **중복 키 없는 JSON 객체인지만** 확인하고 바이트를 바꾸지 않고 보냅니다. 내용 검증은 런타임이 합니다(422 `invalid_request`).
- 새 jobId는 새 생성(비용)입니다. 불확실한 submit을 **새 jobId로 재시도하지 않습니다.**
- 응답은 `X-Request-ID`를 되돌려야 하며 아니면 `RESPONSE_MALFORMED`입니다.

### 응답 해석

| 응답 | 클라이언트 결과 |
|---|---|
| submit 202 / 200 | `NEWLY_ACCEPTED` / `ALREADY_ACCEPTED`. **접수일 뿐 완료·승인·예산 확인이 아닙니다.** `status.next()`를 따릅니다 |
| recover 202 / 200 | `RECOVERY_ENQUEUED` / `RECOVERY_COALESCED` |
| `status.state=READY` | 런타임 내부 준비 완료이며 공개 `completed`가 **아닙니다**. 앱 import와 현재 권한 재확인이 먼저입니다 |
| result `delivery=AVAILABLE` | `payload`는 **신뢰하지 않는** 모델 출력(`UntrustedAnalysisPayload`)입니다. `readyPayload()`는 deliverable이면서 `READY`일 때만 값이 있습니다 |
| result `delivery=WITHHELD` | 현재 서버 grant가 전달을 막음. `payload` 없음, 이유 코드와 내용 없는 `receipts`(사용량 정산용)만 있습니다. 응답이 모순이면(예: withheld인데 job 있음) 닫힘 실패 |
| 그 밖의 2xx(예: 201, status의 202) | `UNEXPECTED_RESPONSE` |

필수 키·타입·열거값·`schemaVersion`·요청한 `jobId`(submit은 제출한 `kind`·`mode` 포함)·`inputDigest`·상태 교차 일치, receipt의 `promptVersion`/`schemaVersion`/`policyVersion` 포함 설정 필드(withheld 결과에서도 보존)를 모두 검사하고 하나라도 어긋나면 `RESPONSE_MALFORMED`입니다(중복 키, 비-UTF-8, 후행 토큰, 깊은 중첩 포함). 응답 본문·URL·토큰은 예외에 담지 않습니다.

### 취소와 비용

`cancel`은 진행 중 provider 호출을 죽이지 않습니다. 늦게 온 receipt는 저장되어 사용량이 되고 verify 송신만 막힙니다. 그래서 반환된 `AnalysisJobStatus`의 `usage`·`unreceiptedAttempts`는 런타임이 말한 그대로이며 **0이라는 증거가 아닙니다.** 클라이언트는 비용을 계산·보정하지 않고 `cost`가 없으면 null입니다. ready/failed 작업은 `job_already_terminal`(상태 포함)입니다.

### 오류

두 가지 예외만 있으며(`AiClientException` sealed) 모두 operation·HTTP 상태·안정 코드·요청 ID만 담습니다.

- **`AiServiceErrorException`**: 서비스의 오류 봉투를 해석한 결과입니다. **변경 operation에서 "아무 일도 일어나지 않았다"는 증거가 아닙니다**(서비스는 런타임에 커밋한 뒤에도 503 `runtime_unavailable` 같은 봉투를 돌려줄 수 있음). `code()`는 AI 서비스의 **소문자** 코드(`job_not_found`, `idempotency_conflict`, `runtime_unavailable`…), `retryable()`·`retryAfter()`·`runtimeCode()`·`field()`와 409 응답의 `status()`를 그대로 보존해 호출자가 결정합니다. 클라이언트는 `retryable`이어도 재시도하지 않습니다.
- **`AiTransportException`**: 쓸 수 있는 답이 없거나 믿을 수 없습니다(`CONNECT_FAILED`, `CONNECT_TIMEOUT`, `TIMEOUT`, `IO_ERROR`, `INTERRUPTED`, `RESPONSE_TOO_LARGE`, `RESPONSE_MALFORMED`, `REDIRECT_REFUSED`, `UNEXPECTED_RESPONSE`). 두 예외는 `requestMaybeProcessed()`에 **같은 변경 결과 규칙**을 씁니다. 이 값은 "변경이 일어났을 수 있는가"만 말하며, 읽기 응답을 받았다는 뜻이 아닙니다. 읽기(status/result)는 서비스 상태를 바꾸지 않으므로 타임아웃·오류에서도 항상 false이고 읽기는 그대로 다시 시도할 수 있습니다. 변경 operation(submit/cancel/recover)은 요청이 나가지 못한 연결 실패(`CONNECT_FAILED`, `CONNECT_TIMEOUT`)와 서비스의 확정된 4xx 답에서만 false이고, 그 밖의 모든 전송 실패와 **모든 5xx**에서 true(보수적)이며 **결과 불명**입니다.

공개 API의 `ErrorCode`(`INVALID_REQUEST`, `RESOURCE_NOT_FOUND`, `INTERNAL_ERROR` …, 대문자)와 AI 코드는 **다른 어휘**입니다. 서로 매핑하는 코드를 넣지 않았고 `GlobalExceptionHandler`도 바꾸지 않았습니다. 처리하지 않으면 지금은 `INTERNAL_ERROR`로 응답됩니다. AI 거절을 사용자에게 보여 주는 첫 기능이 서버 간 코드를 노출하지 않고 공개 코드로 옮기는 매핑을 직접 정해야 합니다.

### 결과 불명 시 복구 순서

전송 오류뿐 아니라 변경 operation의 **5xx 서비스 오류(503 포함)**에도 적용합니다.

1. 새 jobId를 만들거나 생성을 맹목적으로 다시 보내지 않습니다.
2. `status(jobId)`를 먼저 읽습니다.
   - 200: 작업이 있습니다. `next`를 따릅니다(`wait`/`fetch_result`/`recover`/`operator_reconcile`/`none`).
   - 404 `job_not_found`: 등록이 안 됐거나 서비스가 id를 예약만 한 상태입니다. 이때만 **같은 jobId·같은 본문**으로 submit을 되풀이합니다. 서비스가 멱등 처리하며 두 번째 작업을 만들지 않습니다.
   - 또 전송 오류: 중단하고 나중에 status 읽기를 다시 시도합니다.
3. cancel/recover도 status를 읽고 다시 결정합니다(둘 다 멱등).
4. `operator_reconcile`/`reconcile_required`는 provider 쪽 사용량 증거가 필요한 운영자 판단이며 새 jobId로 우회하면 그 비용을 받아들이는 것입니다.

### 요청 ID

클라이언트는 현재 요청의 MDC `requestId`가 AI 계약 형식 `[A-Za-z0-9._-]{1,128}`일 때만 `X-Request-ID`로 전달하고 아니면 새 UUID를 씁니다. 안전하지 않거나 너무 긴 inbound ID는 **전달하지 않고** 멱등 키로도 쓰지 않습니다. 예외의 `requestId()`는 실제로 보낸 값입니다.

팀 foundation의 `RequestIdFilter`는 비어 있지 않은 `X-Request-ID`를 길이·문자 검사 없이 그대로 수용·응답하고 MDC에 넣습니다. 따라서 공개 응답의 requestId와 AI 로그의 requestId가 다를 수 있습니다(AI 쪽은 형식이 틀리면 새 값을 만듭니다). 필터를 고치지 않았습니다. 최소 변경 제안: 공개 경계에서 같은 패턴으로 검증하고 맞지 않으면 UUID를 생성해 응답 헤더·오류 본문에 그 값을 쓰도록 하면 AI 호출까지 하나의 ID가 이어집니다. 이는 공개 API 계약(`X-Request-ID` 형식) 합의가 필요한 변경이라 필터 소유자가 정합니다.

## S2 추출·S3 관계 클라이언트

`ExtractionClient`(`com.zoop.ai.extraction`, 계약 `zoop-extraction-s2-2`/응답 `zoop-ai-internal-extraction-1`)와 `RelationClient`(`com.zoop.ai.relation`, `zoop-relation-s3`/`zoop-ai-internal-relation-1`)는 서비스의 별도 가족을 호출하는 **전송 계층**입니다. S1과 같은 `AiHttpTransport`(HTTP/1.1, 프록시·리다이렉트·쿠키·재시도 없음, 호출당 요청 1개, UTF-8 JSON만, 응답 크기 상한, 요청 ID 에코 필수)를 쓰고, 가족별 스키마·신원·오류 봉투는 가족별 해석기가 닫힘으로 검증합니다. 자유 형식 “그대로 전달” 클라이언트가 아니라 도메인 타입(요청·상태·결과·operation)입니다.

| 가족 | operation | 호출자가 보낼 수 있는 것 |
|---|---|---|
| S2 `ExtractionClient` | `submit`/`status`/`result`/`cancel`/`recover` | `jobId`와 **서버 운영자가 이 principal·jobId에 사전 승인한 요청의 digest**(`ExtractionSubmission`)뿐. 스냅샷·카탈로그·관측·토픽 요청·fixture·실행 모드는 보낼 수도 지정할 수도 없고, 승인에 없는 digest는 `403 request_not_approved` |
| S3 `RelationClient` | `submit`/`status`/`result`/`cancel`/`recover` + `review`/`operation` | `jobId`, 출처·실행 provenance, S2 upstream `{jobId, inputDigest}`를 전달합니다. 수동 모드에서는 운영자 허용 목록, 온라인 모드에서는 admission manifest의 정확한 S3 ID·provenance·upstream이 권한을 정합니다. live는 서버의 runtime pin·live gate·원천 권리·예산 조건이 별도로 필요하며, 호출자가 모드를 적는 것만으로 허용되지 않습니다. |

- **응답 결속.** 모든 응답은 요청한 `jobId`(검수는 `operationId`까지)에 묶입니다. submit 응답은 보낸 `approvedRequestDigest`(S2) 또는 출처·upstream(S3)을, review 응답은 보낸 후보·결정·`expectedSourceVersion`·`expectedSourceRevision`을 그대로 되돌려야 하고, 하나라도 어긋나면 `RESPONSE_MALFORMED`입니다. result의 `delivery`는 status의 `delivery`와 같아야 하고 내용은 `available`일 때만 있습니다. 후보 payload는 `UntrustedExtractionPayload`/`UntrustedRelationPayload`로만 나오며 `jobId`·`inputDigest` 일치만 확인된 **신뢰하지 않는** 모델 출력입니다(`approved=false`). S3 payload는 후보마다 `(relationCandidateId, sourceVersion, sourceRevision)`을 읽고 모든 `sourceVersion`이 job의 `inputDigest`와 같아야 합니다.
- **원천 version·revision.** 검수(`RelationReviewRequest`)는 AI **원천** 기대값 `expectedSourceVersion`(= S3 job의 `inputDigest`)과 `expectedSourceRevision`(후보의 런타임 이벤트 체인 revision, 십진 문자열, 1 이상)만 가집니다. 앱의 `expectedRevision`을 넣을 필드가 없습니다(전달 금지). 서버가 둘을 원자적으로 비교하고 어긋나면 `source_version_conflict`/`source_revision_conflict`로 **아무것도 기록하지 않으며** 같은 key를 다시 쓸 수 있습니다. `operationId`는 `Idempotency-Key`이며 reviewer는 인증된 principal입니다. operation 상태는 `review`(결정이 런타임 원장에 기록됐는가: `UNCONFIRMED`/`APPLIED`, 기록 후 revision = expected+1), `revalidation`(현재 계약에서는 항상 `not_requested`; 이전 계약의 allow 이력만 `verified`+verdict·`superseded`·`contract_changed`, 결과 revision = expected+2), 게시(항상 `not_published`), `limitation`(이전 계약 이력이면 `review_contract_changed`)을 따로 보여 주며 서로 모순되면 `RESPONSE_MALFORMED`입니다. 사람의 allow는 정확히 그 `approved` 이벤트를 채택하는 최종 승인이고 이 클라이언트는 그 위에 게시나 재검증을 더하지 않습니다.
- **현재 권한은 서버가 사용 시 다시 검사합니다.** 원천 권리 철회나 수동 파일의 승인·upstream 제거는 결과를 `WITHHELD`로 만듭니다. 온라인 모드는 해당 작업의 불변 admission origin도 검사하며, 정책 교체·비활성화·관측된 만료로 종료된 admission은 옛 정책을 다시 넣어도 되살아나지 않습니다. 원천 권리 복원과 admission 재승인은 다른 일입니다. 클라이언트는 권한을 저장하거나 캐시하지 않습니다.
- **수락 경계(변경 성공·phase·영수증).** `READY`가 아닌 job의 `delivery=available`은 모순이라 status·result 모두 `RESPONSE_MALFORMED`입니다(`READY`+`withheld`는 정상). 영수증은 런타임 호출마다 하나라서 개수 상한이 없고(응답 크기 상한만 적용) withheld 결과에서도 모두 보존됩니다. **사람의 `allow`는 최종 승인입니다.** 검수 성공 응답은 항상 HTTP 200이고 기록된(`APPLIED`) operation이어야 합니다. 재검증·dispatch·모델 호출이 없으므로 `revalidation.state`는 `not_requested`, `next`는 `none`, `limitation`은 없음입니다. **200이 아닌 성공 상태(202 포함)는 이 계약이 정하지 않은 상태라 `UNEXPECTED_RESPONSE`이고 요청이 처리됐을 수 있어 `requestMaybeProcessed()=true`**입니다. 상태가 200이어도 본문이 이 계약과 어긋나면(예: `QUEUED`/`RUNNING` 재검증, `next≠none`, `UNCONFIRMED`) `RESPONSE_MALFORMED`입니다. `UNCONFIRMED` operation은 읽기·오류 봉투에서만 유효하고(`next`는 `retry_review`) 검수 성공이 될 수 없어 모호성이 보존됩니다. 이전 계약(allow 뒤 재검증)으로 기록된 operation은 `limitation=review_contract_changed`인 **이력**으로만 읽히며(`revalidation.state`는 `verified`/`superseded`/`contract_changed`, `next=none`, 정착했다면 `expected+2` 결속은 그대로 검사) 승인으로 재해석하거나 다시 보내지 않습니다. 같은 key의 재전송은 `409 review_contract_changed`를 받을 수 있습니다.
- **오류.** 새 예외 두 개(`ExtractionServiceErrorException`, `RelationServiceErrorException`)는 `AiServiceRejectionException`(S1의 `AiServiceErrorException`과 같은 부모)을 상속하고 전송 실패는 `AiTransportException`을 그대로 씁니다. S2/S3 오류의 409가 싣는 `status`(S3는 `operationStatus()`도)는 도메인 타입으로 해석합니다. **변경 operation의 모호성은 S1과 같은 규칙으로 보존됩니다**: 연결 전 실패와 확정된 4xx만 `requestMaybeProcessed()=false`, 그 밖의 전송 실패와 모든 5xx는 `true`입니다. 복구: S2/S3는 `status(jobId)`를 먼저 읽고, 검수는 **같은 key로 `operation(jobId, operationId)`를 먼저 읽은 뒤** 같은 요청(같은 key·같은 본문)을 되풀이합니다. 새 jobId·operationId를 만들지 않습니다. 새 `AiOperation` 값은 `REVIEW`·`OPERATION`입니다(`recoverOperation`은 최종 승인 계약에서 제거). 새 검수 거절 코드는 `review_call_in_flight`·`review_candidate_ineligible`·`review_contract_changed`이고 `review_already_pending`은 없어졌습니다.
- **취소·복구.** ready 작업의 cancel은 `409 job_already_terminal`(작업은 ready로 남음), 취소된 작업의 recover는 `409 job_not_recoverable`(상태 포함), 중단·정지 작업은 **명시적 `recover`로만** 이어지며 서비스는 미응답 호출을 다시 보내지 않고(`reconcile_required`는 운영자 판단) 저장된 stage·영수증을 재사용합니다. 대기 중 dispatch가 있을 때 recover는 `RECOVERY_COALESCED`입니다.

설정은 S1과 독립이므로 `extraction.*`/`relation.*` scope만 가진 별도 principal·토큰을 쓸 수 있습니다. 모두 기본 비활성이고 값은 저장소에 없으며, 활성인데 값이 틀리면 설정 이름만(`zoop.ai.extraction-client.<setting>`/`zoop.ai.relation-client.<setting>`) 말하고 기동이 실패합니다.

| 환경 변수 | 기본값 | 규칙 |
|---|---|---|
| `ZOOP_AI_EXTRACTION_CLIENT_ENABLED` / `ZOOP_AI_RELATION_CLIENT_ENABLED` | `false` | `true`일 때만 해당 bean(`HttpExtractionClient`/`HttpRelationClient`) 생성 |
| `…_BASE_URL`, `…_TOKEN`, `…_CONNECT_TIMEOUT`, `…_REQUEST_TIMEOUT`, `…_MAX_RESPONSE_BYTES` | 없음, 없음, `3s`, `30s`, `8388608` | S1 표와 같은 규칙(`ZOOP_AI_EXTRACTION_CLIENT_*`, `ZOOP_AI_RELATION_CLIENT_*`) |

**소비 기능의 책임.** 이 클라이언트는 앱 DB, jobId/operationId의 사용자·문서·회차 결속, 후보의 앱 검증·저장, 공개 활성화나 스케줄러를 구현하지 않습니다. S3 검수와 앱의 검수 revision·공개 흐름 연결도 소비 기능이 맡습니다. 계획 접수는 아래의 별도 전송 기능이며, 앱의 `analysis_jobs` 큐 worker나 공개 `JobCreate` 구현을 대신하지 않습니다.

## 계획 접수 클라이언트

`PlanAdmissionClient`(`com.zoop.ai.plan`, 구현 `HttpPlanAdmissionClient`)는 `admit(PlanReference)`와 `status(PlanReference)`를 제공합니다. `PlanReference`에는 서버가 이미 보관한 `planId`·`planDigest`만 넣습니다. 접수의 `Idempotency-Key`는 `planId`이고 조회에도 정확한 digest가 필요합니다. 경로·원문·S2 요청 본문·정책·예산을 보낼 수 없으며, 앱 principal에는 `plan.admit`·`plan.read`와 필요한 S2/S3 scope만 부여합니다. **`plan.policy`는 별도 운영자 권한**입니다.

| 환경 변수 | 기본값 | 규칙 |
|---|---|---|
| `ZOOP_AI_PLAN_ADMISSION_CLIENT_ENABLED` | `false` | 명시적으로 켰을 때만 bean을 만듭니다. 다른 AI 클라이언트 설정과 독립입니다. |
| `…_BASE_URL`, `…_TOKEN` | 없음 | 활성화 시 필수이며 위의 TLS·토큰 규칙을 따릅니다. |
| `…_CONNECT_TIMEOUT`, `…_REQUEST_TIMEOUT` | `3s`, `30s` | 기존 공통 전송 제한을 사용하며 자동 재시도하지 않습니다. |
| `…_MAX_RESPONSE_BYTES` | `16000000` | 전체 응답의 바이트 상한입니다. 단위 목록을 잘라 성공으로 반환하지 않습니다. |

응답은 계획·receipt·manifest digest, admission ID, 단위별 S2 요청과 결정적 S3 ID를 함께 검증한 `PlanAdmission`입니다. `authority.state=ACTIVE`는 **현재 admission 정책이 이 작업을 허용한다는 뜻**이며, 현재 원천 권리·예산·작업 준비 완료를 증명하지 않습니다. `INACTIVE`인 과거 응답도 기록 조회에 사용할 수 있지만 실행해서는 안 됩니다.

소비자는 manifest의 S2/S3 참조를 사용하고 첫 호출 전에 계획·단위 ID를 앱 작업에 불변으로 저장해야 합니다. 응답 유실 시 같은 `PlanReference`로 조회하며, 새 plan/job ID를 만들어 재실행하지 않습니다. S2 결과를 소비할 때 실제 결과에 포함된 status의 승인·입력 digest와 provenance·사용량을 확인하고, S3는 정확한 upstream과 이미 관측한 S3 input digest까지 대조합니다. 이전 status가 맞았다는 이유로 다른 result를 받아들이면 안 됩니다.

`PlanAdmissionServiceErrorException`과 기존 `AiTransportException`은 확정 거절과 결과 불명을 구분합니다. 201/200 접수는 실행 시작이 아니며, 클라이언트가 임의로 정책을 갱신하거나 job을 submit하지 않습니다. 운영자 정책과 누적 quota·종료 규칙은 [서비스 안내](../../ai/service/README.md#온라인-plan-admission선택-기본-꺼짐)를 따릅니다. plan/unit 제한은 금액이나 모델 호출 수 제한이 아닙니다.

### 실제 Java 소비 검사

설치된 worker·pipeline·service와 JDK가 필요합니다. 다음 명령은 새 합성 상태에만 정책을 설정하며 실제 운영 파일·키·원문을 쓰지 않습니다.

```sh
./api/gradlew -p api preparePlanAdmissionProof
ai/service/.venv/bin/python ai/service/scripts/online_admission_actual_smoke.py \
  --java-classpath-file api/build/plan-admission-proof-classpath.txt \
  --evidence-dir /absolute/new-proof-evidence
```

이 검사는 서비스 재시작 없이 두 회차를 Java 클라이언트로 접수·소비하고, 정확한 재요청, 정책·quota·현재 권리·중단 복구를 확인합니다. 원본 상태는 보존하고 시험 소유 프로세스·상태를 정리합니다. authored replay이므로 실제 모델 품질이나 정기 발행 SLA 검증은 아닙니다.

## 챗봇 모델 단계 클라이언트

`com.zoop.ai.chat.ChatStageClient`(`HttpChatStageClient`)는 `POST /internal/v1/chat-stages/{stage}`(계약 `zoop-ai-chat-5`)로 챗봇 모델 단계 하나를 동기로 실행합니다. 단계는 `chat-router`(Jev), `chat-answer`(Luna), `chat-verification`(Jev), `chat-agent`(Luna Responses 승인 루프의 한 단계)입니다. 같은 전송 계층(`AiHttpTransport`: 재시도·redirect·proxy 없음, 응답 크기·마감 제한, `X-Request-ID` 대조)을 쓰고 오류 봉투는 S1(`zoop-ai-internal-1`)입니다. `Idempotency-Key`는 `invocationId`(`<chatJobId>.<attemptNo>.<router|answer|verify|agent-n>`)입니다. 같은 시도의 같은 단계는 AI 쪽에서 두 번 보내지지 않고, 재실행(rerun)은 새 시도 번호로 새 invocation이 됩니다.

`com.zoop.chat.model.ChatModelStages`가 오케스트레이터의 네 포트(`ChatModels.Router/Generator/Verifier/Agent`)를 구현합니다.

- **보내는 것.** 확인 질문 사슬(질문과 고른 선택지 이름), 서버가 나눈 요구사항, 바인딩된 논리 기능의 설명, 도구 결과 항목 중 ZOOP 그래프·카탈로그 데이터인 기업·사건·관계 항목(id·종류·이름. 이름이 기사 제목인 `evidence` 항목은 보내지 않음), 근거 인용 구간(근거 레코드에서 만든 `quote`와 그 기사의 `articles.provider`인 `sourceId`, 제목, 발행 시각), 아래의 서버 검증 문맥을 보냅니다. 회원 ID, 계정 정보, 기사 전문은 보내지 않습니다. 인용 전송 허용 여부는 AI 쪽 챗봇 grant registry가 `sourceId`로 판단하며 허용되지 않으면 단계가 거절됩니다(fail closed).
- **잠정 규칙(2026-10-22).** 요구사항 분해는 결정론적입니다(`ChatRequirementSplitter`: 물음표·줄바꿈·세미콜론·독립된 "그리고"/"또한"에서만 나누고, 나누지 못하면 질문 전체가 요구 하나). 기업명은 모델이 아니라 서버가 카탈로그 이름·별칭과 **정확히 일치**할 때만 해석하고, 겹치면 긴 이름이 이깁니다(`CompanyNameResolver`). 같은 이름이 여러 기업이면 모델을 호출하지 않고 `kind=company` 확인 질문을 만듭니다. 다음 실행에서는 회원이 고른 선택지 id 또는 자유 입력 답에 쓴 정확한 기업명으로 해석합니다. 확인 답 실행은 루트 질문과 답을 순서대로 반영한 뒤 제한·모호성을 판단합니다. 루트의 요구가 6개를 넘으면 자유 입력 답을 나눈 요구가 그 자리를 대신합니다.
- **실패 의미.** 단계 결과 `failed`는 `unknown`이면 `UNKNOWN`(재전송 금지), 보냈지만 확정 실패면 `NOT_SENT`(재실행 가능), 보내지 않았으면(설정·grant·live gate·호출 상한 거절) `REFUSED`(같은 실행은 다시 거절되므로 재실행하지 않음, 공개 실패 `internal`)입니다. HTTP 502/504 `stage_outcome_unknown`과 연결 이후 전송 실패는 `UNKNOWN`, 503은 시작되지 않았으므로 `NOT_SENT`, 그 밖의 4xx(409 `execution_unavailable` 등)는 `REFUSED`입니다. 형식이 맞지 않는 답은 `NOT_SENT`입니다. 클라이언트는 결과 불변식도 검사해서 어긋나면 `RESPONSE_MALFORMED`(결과 불명)로 처리하고 사용할 답으로 바꾸지 않습니다. 불변식: 성공에는 answer·receipt가 있고 failure가 없으며, 실패에는 answer가 없고, `unknown`이면 `sent`이며, receipt는 보냈을 때만 있고 요청 mode와 같아야 합니다.
- **기록.** 각 단계는 `ai_executions`에 `feature=chatbot`, `chat_job_id`, `stage`, `execution_mode`와 함께 호출 전 `running`으로 남고, 끝나면 `succeeded`/`failed`/`unknown`, 영수증의 provider·model·prompt version·토큰과 오류 코드로 갱신됩니다. 이 행은 `chat_jobs`를 `ON DELETE RESTRICT`로 참조하므로 기록이 있는 작업의 대화·회원은 이 행을 먼저 정리하지 않으면 삭제되지 않습니다(ERD v6 보존 정책).
- **검증 문맥.** 검증 입력은 `requestBinding`(호출 ID·고정 그래프 버전·asOf)과 구간별 `sectionId`·`requirementIds`·순서가 고정된 `claims[]`·`serverFacts`를 받습니다. 서버가 section 문장을 최대 20개 claim으로 결정론적으로 나누며, Jev는 claim별 support와 `unsupportedCausality`, section별 금지 투자 조언 여부를 판정합니다. 지원되지 않거나 인과가 확인되지 않은 claim만 제외하고 같은 section의 안전한 claim은 유지합니다. 서버는 성공한 현재 조회에서만 `portfolio_scope`(기업 ID·이름·보유/관심 구분·조회 범위·잘림 여부)와 `graph_comparison`(전후 버전·asOf·since·대상·상한·추가/제거 항목), Q08의 `publication_record`(고정 버전의 검수 revision 이하 마지막 검수 결정의 종류·시점·경로와 그 버전에 적용된 공개 규칙의 제목·요약. 결정한 관리자와 사유 문장은 보내지 않음)·`briefing_selection`(발행 회차가 그 이슈를 고른 순위와 기록된 선정 이유)을 만듭니다(2026-10-30). 기사 인용과 별개이며 회원 ID·계좌·수량·금액·기사 전문은 보내지 않습니다. 보유/관심 정보는 조회 당시의 상태이지 과거 asOf의 상태가 아닙니다. 잘린 목록은 전체나 부재의 근거가 될 수 없습니다. 문맥이 없으면 사실을 만들지 않으며 인용과 사실이 모두 없는 claim을 `supported`로 통과시키지 않습니다.
- **두 실행 경로의 같은 사실.** direct 경로는 서버가 읽은 결과에서, agent 경로는 성공한 `chat_tool_calls`의 결과와 예약 메타데이터에서 같은 규칙으로 사실을 만듭니다. agent 경로는 job·회원·시도·tool call·capability·고정 버전·asOf·입력 digest를 예약 기록과 대조하고, 하나라도 다르면 복원 없이 run을 `internal`로 끝냅니다. 회원 범위(`portfolio.scope.read`, Q07)는 서버 전용 조회라서 direct 경로에서만 나오고, agent 경로의 사실은 `graph_comparison`입니다. 모델 전송 gate가 항목을 뺀 결과는 잘린 목록처럼 `truncated`로 복원합니다. `cachedFrom`으로 이어진 보관 결과도 같은 요청·버전에 결속되어야 하며, 원본의 잘림과 항목 제외는 재사용 후에도 유지됩니다. 그래프 변경의 표시 이름이 코드 포인트 300개를 넘으면 끝에 `…`를 붙여 300개 이내로 줄이며, 항목 ID와 추가·제거 구분은 그대로 보존합니다. agent 경로의 결과는 run의 요구들이 공유하므로([chat-mcp.md](chat-mcp.md)) 각 사실은 자기 조회 대상(`targetIds`)과 범위를 그대로 지닙니다. 조회 사실은 서버의 조회 기록에서만 나옵니다. 단계 계약은 닫힌 v2이고 출처 grant registry는 v1 그대로입니다.

| 환경 변수 | 기본값 | 규칙 |
|---|---|---|
| `ZOOP_AI_CHAT_CLIENT_ENABLED` | `false` | `true`일 때만 클라이언트·어댑터·`OrchestratedChatEngine` bean을 등록합니다. 그래야 `ZOOP_CHAT_QUESTIONS_ENABLED=true`로 기동할 수 있습니다 |
| `ZOOP_AI_CHAT_CLIENT_MODE` | `replay` | `replay`(AI 쪽 고정 응답, 네트워크 없음) 또는 `live`(실제 Luna/Jev 호출. AI 서비스의 chat live gate·호출 상한이 따로 열려 있어야 하며 유료 호출은 별도 승인 필요). 다른 값은 기동 실패 |
| `…_BASE_URL`, `…_TOKEN`, `…_CONNECT_TIMEOUT`, `…_REQUEST_TIMEOUT`, `…_MAX_RESPONSE_BYTES` | 없음, 없음, `3s`, `35s`, `2097152` | S1 표와 같은 규칙. 토큰의 principal에는 `chat.invoke` scope가 필요합니다. 요청 마감은 가장 긴 단계(answer 25초)와 서비스 여유를 덮고, 단계별 상한은 오케스트레이터가 따로 끊습니다 |

**종단 replay gate.** `make service-install api-ai-chat-smoke`(`api/scripts/ai_chat_gate.py`, Gradle `aiChatContractTest`, CI에서 실행)는 합성 시나리오에 대해 Java 어댑터가 만들어야 할 단계 입력과 replay 응답을 Python 쪽에서 작성합니다. replay 응답은 worker의 request identity(입력·설정 digest)로 찾으므로, Java가 만든 입력이 한 필드라도 다르면 `replay_input_mismatch`로 거절됩니다. 작성한 fixture는 먼저 프로세스 안에서 worker runtime으로 재생해 확인합니다. 그다음 실제 `ai/service`(loopback, replay 전용, live gate 닫힘)를 띄우고, 실제 `ChatModelStages` → `HttpChatStageClient`로 다음을 검사합니다.

- 세 단계의 성공
- 같은 invocation 재전송 시 저장된 결과 반환(재발송 없음)
- grant 없는 인용 거절, 모르는 입력 거절, live 거절, `chat.invoke` 없는 principal 거절
- Q07/Q05 현재 조회 사실을 담은 Java 검증 입력, 실제 HTTP→CLI→Jev 요청 생성 경로, 교차 실행·구간·버전 위조 거절과 문맥 부재 시 HOLD

JUnit 보고서(0건·skip 금지)와 자격 증명 누출도 확인합니다. Java replay 검사 뒤 별도 서비스에서 합성 자격 증명과 loopback 가짜 Jev 수신자를 사용해 실제 요청 본문을 확인합니다. 외부 모델과 PostgreSQL은 쓰지 않습니다. 복제된 가상 환경이 다른 worktree를 가리키지 않도록 서비스와 실제 CLI 모듈의 소스 경로를 고정합니다. `ChatCapability` 설명이나 입력 구성을 바꾸면 gate의 시나리오도 함께 갱신해야 합니다. 합성 응답은 실제 모델의 판정 품질을 입증하지 않습니다.

## 소유와 격리

AI 서비스의 소유자는 **인증된 principal 하나**(이 앱)이며 최종 사용자(tenant) 식별이 없습니다. 같은 principal의 작업은 모두 같은 소유자라서 **사용자 간 격리는 이 클라이언트가 하지 않습니다.** 앱이 jobId를 사용자·문서·회차에 결속해 저장하고 접근 시 직접 확인해야 합니다. ERD v6의 공개 앱 job과 내부 AI job 구분을 따르며([아래](#erd-v6-설계와의-관계)), 다른 principal의 작업은 404와 동일하게 보입니다.

결과를 앱 데이터로 쓰기 전(소비 기능 책임)에 모두 필요합니다. S1 문서 분석([문서 분석](DOCUMENT_ANALYSIS.md))은 2–4를 구현했습니다(1은 최종 사용자가 없는 operator 실행이라 해당하지 않고, 4는 파일 쓰기가 transaction 앞에 있으며 DB 쓰기가 한 transaction입니다). 그 밖의 소비 기능은 각자 해야 합니다.

1. 최종 사용자·관리자 권한 확인(서비스가 하지 않음).
2. 앱의 **불변 문서 버전**과 `documentVersion`/근거 인용(`evidence`, quote 오프셋)이 지금도 같은지 검증. `UntrustedAnalysisPayload`의 어떤 필드도 신뢰하지 않습니다.
3. 현재 출처 권리 재확인. `result`의 AVAILABLE은 요청 시점의 서버 grant일 뿐입니다.
4. 가져오기·상태 변경·공개 반영을 **하나의 transaction**으로. `READY` ≠ 공개 `completed`.

## ERD v6 설계와의 관계

[ERD v6](../../docs/erd/zoop-core-erd-v6.md)는 공개 앱 작업 ID와 내부 AI job ID, 영수증과 검수 원천 버전을 구분합니다. 전송 클라이언트 자체는 앱 DB 없이 동작합니다. S1 결과의 영속화는 [문서 분석](DOCUMENT_ANALYSIS.md), 그래프 수입·공개 읽기는 [handoff 인계](GRAPH_READ_HANDOFF.md)를 따릅니다. 앱의 별도 `analyze_plan` 소비자는 아래의 정규화된 원장에 처리 관측만 저장합니다. 다음 날짜별 설계 근거와 현재 구현 범위를 구분합니다.

> **ERD 설계 근거(2026-10-13).** 내부 AI `jobId`는 공개 `analysis_jobs.id`와 별개이며 한 앱 작업에 여러 AI 작업이 대응할 수 있습니다. `analysis_jobs.checkpoint.aiUnits[]`(`{unitKey, aiJobId, submitArtifactId, runtimeInputDigest?}`)·`document_analyses.ai_job_id`·`briefing_attempts.stages`에는 submit 전에 ID와 불변 요청을 저장하는 방향이 정의돼 있습니다. 호출 영수증의 `jobId`·`attemptId`와 실행 당시 grant snapshot은 현재 접근권한을 대신하지 않습니다. 검수는 앱의 `expectedRevision`과 AI 원천의 `expectedSourceVersion`·`expectedSourceRevision`을 구분합니다. S3 내부 값은 `sourceVersion`=S3 input digest, `sourceRevision`=후보 이벤트 revision이며, Java 전송과 현재 정책 검사는 위 S2/S3·계획 접수 절을 따릅니다.

- **현재 같은 방향인 것:** GET은 모델을 호출하지 않고 저장된 available로 현재 권리를 대신하지 않습니다. S1 도메인 결과 저장은 [문서 분석](DOCUMENT_ANALYSIS.md#검증)의 실행 증거를 따릅니다. `analyze_plan`의 정규화된 원장은 S2/S3 input digest와 처리 관측만 고정하며 후보 도메인 결과 import는 하지 않습니다.
- **별도 소비 기능에 남은 것:** 검수 adapter·원천 동기화, 현재 grant registry의 도메인 import 적용, HTTP receipt와 안정적인 runtime attempt 회계 ID의 대응, 기능별 사용량 대시보드 통합은 이 큐에서 추정해 채우지 않습니다. `analysis_jobs`는 AI runtime job 자체가 아니며 S3 inputDigest·후보 이벤트 revision·앱 검수 revision은 독립적입니다.
- **남은 소비 기능:** 실제 검수 adapter·후보 mapping·review target 동기화·현재 권리 검증·공개 전환은 기존 소유자의 별도 작업입니다. `analyze_plan` 성공은 이 기능의 완료나 FS058/FS059/FS063/FS064/FS067 전체 구현을 뜻하지 않습니다.

## 관리자 계획 분석 큐

`POST /api/v1/admin/jobs`의 `kind=analyze_plan`은 관리자 세션·CSRF·Idempotency-Key로 정확한 `{reason,plan:{planId,planDigest}}`를 접수합니다. 새 요청 객체 두 개는 닫혀 있으며 UTF-8 64 KiB, 중복 키·후행 JSON·형변환 거절과 기존 감사 사유 정책을 적용합니다. `ingest/revalidate/project` 요청 형태는 그대로지만 아직 실행기가 없어 새 접수는 503 SOURCE_UNAVAILABLE(retryable=false), 재시도는 worker_unavailable로 거절합니다.

접수 transaction은 AI를 전혀 호출하지 않고 등록·root job·analysis.job.create 감사·정확한 202 멱등성 응답을 함께 커밋합니다. Location은 작업 상세 경로입니다. 같은 키/본문은 기능 비활성화 뒤에도 당시 응답을 재생합니다. 접수가 활성화된 상태에서 다른 키로 같은 계획을 접수하면 root job과 deduplicated=true를 반환하며 실패한 작업을 몰래 재시도하지 않습니다. 비활성화 상태의 새 키 요청은 기존 계획이라도 503으로 거절하며 새 기록을 만들지 않습니다. 다른 digest나 서비스 결속으로 같은 planId를 덮어쓰면 409입니다.

`zoop.analysis.analyze-plan` 설정은 기본 비활성입니다. 환경 변수는 다음과 같습니다.

| 환경 변수 | 기본값 | 의미 |
|---|---|---|
| `ZOOP_ANALYSIS_ANALYZE_PLAN_ENABLED` | `false` | 새 접수와 worker 활성화. 비활성화는 기존 이력·진행 의도를 보존하는 일시 정지입니다. |
| `ZOOP_ANALYSIS_ANALYZE_PLAN_EXPECTED_PRINCIPAL` | 빈 값 | 활성화 시 필수 서비스 principal |
| `ZOOP_ANALYSIS_ANALYZE_PLAN_POLL_INTERVAL` | `2s` | 유한 poll 간격 |
| `ZOOP_ANALYSIS_ANALYZE_PLAN_ATTEMPT_DEADLINE` | `30m` | 앱 시도 deadline. lease 회수로 연장하지 않습니다. |
| `ZOOP_ANALYSIS_ANALYZE_PLAN_LEASE` | `150s` | 가장 긴 단일 HTTP timeout보다 안전 여유를 두는 임대 |
| `ZOOP_ANALYSIS_ANALYZE_PLAN_MAX_CONSECUTIVE_FAILURES` | `5` | 연속 원격 관측 실패 상한 |
| `ZOOP_ANALYSIS_ANALYZE_PLAN_MAX_RECOVERY_DISPATCHES` | `3` | 단계별 앱 시도의 durable recover intent 상한 |
| `ZOOP_ANALYSIS_ANALYZE_PLAN_MAX_RECLAIMS` | `16` | 같은 앱 작업의 자동 임대 회수 상한 |

활성화에는 실제 PlanAdmissionClient·ExtractionClient·RelationClient bean, 공통 canonical base URL과 명시적 principal이 필요합니다. 누락·다른 endpoint·유한하지 않은 시간 설정은 시작 시 거절합니다. `ServiceBinding`은 정규화된 URL/principal의 공개 설정 identity를 SHA-256으로 고정하며 자격 증명은 저장하거나 해시하지 않습니다. 이 설정과 누적 AI 접수 quota는 통화·모델 호출 예산이나 운영 허가가 아닙니다.

`analysis_plans`는 불변 참조와 write-once 접수/manifest를, `analysis_plan_units`는 검증된 순서의 고정 S2/S3 submit·digest·내용 없는 typed 상태를 저장합니다. 접수와 전체 unit set을 한 transaction으로 고정한 뒤에만 단계를 시작합니다. `nextStage`는 단위 한 행을 읽으며 매 poll마다 전체 manifest를 job checkpoint로 복사하지 않습니다. 최초 S3 runtime input digest는 write-once입니다. 원문·후보 payload는 보관하지 않고 정확한 결과 문자열의 UTF-8 SHA-256·관측 시각·receipt만 남깁니다.

worker의 DB transaction은 짧고 HTTP 동안 잠금을 유지하지 않습니다. 실행 advisory lock → job → plan → unit 순서를 지키며 모든 쓰기는 현재 owner token·실제 미만료 lease·취소 상태로 fence합니다. 잠금 대기 뒤 시간을 다시 읽습니다. 전송 전 의도를 먼저 커밋하고 응답 유실·재시작은 같은 AI ID의 상태 조회로 조정합니다. 불명확한 실행은 outcome_unknown으로 남기며 새 ID·정책 재접수·숨은 nonce로 우회하지 않습니다.

queued 취소는 즉시 cancelled와 불변 planRun 요약을 저장합니다. running 취소는 요청만 기록하고 worker가 알려진 자식 상태를 조정합니다. provider 중단·환불을 약속하지 않습니다. retry는 같은 plan_id와 고정 S2/S3 ID를 사용하는 새 앱 작업이며 이미 완료된 단위를 보존합니다. 영구 비활성 접수·불변 결속 충돌·취소된 AI 단계는 plan_not_reusable, 미해결 실행은 outcome_unknown입니다.

이미 전송한 자식 작업의 상태 조회나 취소가 권한 거절로 끝나면, 그 응답만으로 자식 종료를 확정하지 않습니다. 미해결 전송이 남아 있는 앱 취소는 `cancelled/outcome_unknown`으로 기록하고 공개 재시도를 거절합니다. 전송 전 권한 거절은 이 경우와 구분합니다.

성공은 모든 쌍의 결과 envelope 자체가 READY·AVAILABLE이고 저장된 identity와 일치함을 관측한 **ai_processing_handoff**입니다. 새 종류에만 필수 planRun을 반환하며 publicChanged=false, report/ingest/flush/ledgerBefore/ledgerAfter는 NULL입니다. 종결 요약은 과거 관측으로 고정됩니다. `readyUnits(planId,afterOrdinal,limit)`은 계획/접수/manifest pins, ordinal/unitKey, S2/S3 ID와 input digest, provenance, 결과 관측 시각/해시만 내부 소비자에게 넘깁니다. 이것은 현재 권리나 앱 후보 검증의 증거가 아니며 후속 실제 결과 사용은 새 권리 검사를 요구합니다.

수집 baseline 쿼리(kind=ingest), review_targets/decisions, ai_executions, graph version, Neo4j, internal_projection과 공개 활성화는 변경하지 않습니다. HTTP receipt에는 안정적인 runtime attempt accounting ID가 없으므로 회계 행이나 가짜 토큰/비용 0을 만들지 않습니다.

관리자 대시보드의 작업 집계·최근 작업도 같은 `analysis_jobs`를 읽습니다. 관리자 범위의 앱 작업만 집계하고, 최근 5개와 실행 중 작업에는 목록·상세와 같은 JobOut 변환을 적용합니다. `failed24h`는 조회 기준 시각 직전 24시간이며 끝 경계는 포함하지 않습니다. DB를 읽지 못하면 jobs=null로 응답하고, 검수·AI 사용량·브리핑의 미연결 영역을 이 작업 수로 대신 채우지 않습니다.

### 실제 합성 큐 검사 실행

빌드된 jar, 이미 설치한 service/pipeline/worker 환경과 캐시된 PostgreSQL이 필요합니다. 전용 새 외부 디렉터리와 합성 replay 상태만 사용하며 운영 정책·실제 사용자 DB·모델·배포는 사용하지 않습니다. 아래는 실행 명령이며 그 자체가 통과 기록은 아닙니다.

```sh
make api-analyze-plan-smoke ANALYZE_PLAN_SMOKE_OUTPUT=/external/fresh-dir
# 같은 검사 직접 실행:
ai/service/.venv/bin/python api/scripts/analyze_plan_queue_smoke.py \
  --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --output /external/fresh-dir \
  --postgres-bin /cached/pg/bin
# Java 선택: --java /absolute/java
# 캐시된 컨테이너 사용 시 --postgres-bin 대신: --image postgres:16.13-alpine
```

실제 A-ADM-03 `/admin/pipeline` 브라우저 검사는 `--serve-ui --ui-origin http://127.0.0.1:<port> --ui-hold-stage s2`로 앱·서비스를 유지할 수 있습니다(admission/s3/none도 지원). bootstrap 정보는 출력 디렉터리의 private 0600 파일로만 제공합니다. 실제 브라우저 관측을 기록한 파일은 `--ui-proof`로 전달하며, 이 증거가 없으면 backend 검사가 통과해도 전체 결과는 inconclusive(exit 2)입니다. backend 단위/PostgreSQL 회귀와 실제 서비스·브라우저 검사는 서로 대체하지 않습니다. 공개 계약 생성은 저장소 루트에서 `uv run --with pyyaml --with openpyxl python docs/system/build.py`를 실행합니다.

## 검증

```sh
# Java 21 (JAVA_HOME) 필요. 첫 실행은 Gradle 9.7.1(래퍼 SHA-256 검증)과 선언된 의존성을 받습니다.
make api-test        # 기본 gradle test: foundation 6개 + 클라이언트 시험(in-process 가짜 서버). Python·DB·네트워크 서비스 불필요
make api-build       # gradle assemble
make service-install api-ai-smoke   # 실제 Java -> uvicorn ai/service -> 설치된 zoop-ai replay 종단 gate
make pipeline-install service-install api-ai-pipeline-smoke   # S2/S3 종단 gate. 같은 일: ai/service/.venv/bin/python api/scripts/ai_pipeline_gate.py
```

- `api-test`(기본 `test`)는 JDK `HttpServer` 가짜 서버로 헤더·본문 바이트·상태 코드·타임아웃·리다이렉트·과대 응답·모순 응답·요청 수(POST 재시도 없음)를, `ApplicationContextRunner`로 실제 `application.yml` 이름과 닫힘 실패를 확인합니다.
- `api-ai-smoke`는 `api/scripts/ai_contract_gate.py`가 임시 네임스페이스에 실제 서비스 2개(합성 principal, 인메모리 토큰, replay 전용, 모델·외부 네트워크·PostgreSQL 없음)를 띄우고 `./gradlew aiContractTest`를 실행합니다. 4개 kind 제출·조회·결과, 중복/충돌/소유자/인증/scope, withheld(grant 철회·복구), cancel/recover(막힌 fixture), 요청 ID, 연결 실패를 확인하고, JUnit 보고서에서 **실행된 시험 수가 0이 아니고 skip이 없는지**, 서비스 로그·Gradle 출력에 자격 증명이 없는지를 검사한 뒤 서비스와 임시 상태를 지웁니다. 매니페스트 환경 변수 없이 `aiContractTest`를 직접 실행하면 skip이 아니라 **실패**합니다.
- `api-ai-pipeline-smoke`는 `api/scripts/ai_pipeline_gate.py`가 **새** 합성 운영자 세계(실제 `zoop-ai-ingest` 수집 → 서버 사전 승인 S2 요청 → authored 고정물)를 만들고 실제 서비스 6개(주 체인 1개, 결함 주입 5개: S2 child 사망 후 stage 보존·호출 후 응답 없음, S2·S3 dispatch 보류 후 취소, S3 child 사망 후 stage 보존)를 띄운 뒤 `./gradlew aiPipelineContractTest`(`AiPipelineContractTest`, 태그 `ai-pipeline-contract`)를 실행합니다. 확인 내용: S2 제출(서버 승인 digest만)·조회·결과 → 운영자가 upstream을 등록하기 전 S3 `403 upstream_not_allowed`, 등록 뒤 S3 제출·결과·`sourceVersion`/`sourceRevision` 후보 → 오래된 version·revision 거절(아무것도 기록 안 됨)·not-HOLD·없는 후보·scope·타 principal → allow **최종 승인**(200, 재검증 없음, `revalidation.state=not_requested`, `next=none`)·같은 key 재전송 200·다른 본문 409·채택 뒤 이전 revision 거절 → 별도 job에서 reject와 job 간 operation 비침투 → 원천 철회·승인 제거·upstream 제거 시 즉시 withheld(내용 없음, 영수증 유지)와 복원 후 재전달 → child 사망·호출 후 응답 없음·보류 취소·명시적 recover(저장된 stage 재사용, 미응답 호출 재전송 없음, `reconcile_required` 409에 상태 포함) → 연결 실패. 이 gate는 replay만 실행하며 live 제출은 실제 gate에서 시험하지 않습니다(live는 서비스 쪽 시험과 `HttpRelationClientTest`/`HttpExtractionClientTest`의 전송 시험으로만 다룹니다). 끝난 뒤 실행된 시험 수가 소스에 선언된 수와 같고 skip·실패가 없는지, 서비스가 죽지 않았는지, 자격 증명·사설 경로·원문이 서비스 로그나 Gradle 출력에 없는지, 파이프라인 child의 네트워크 시도가 0인지, 운영자의 ingestion·extraction 상태가 바이트 단위로 같은지 검사합니다. 설치된 pipeline이 없으면 **skip이 아니라 실패**합니다. 매니페스트(`ZOOP_AI_PIPELINE_MANIFEST`) 없이 `aiPipelineContractTest`를 직접 실행해도 실패합니다.
- **관측한 실행(2026-10-14, 로컬 작업 트리, Main 실행; 이전 검수 계약 기준의 이력).** 전체 Java 시험 **187개 통과, 실패 0, skip 0**과 `assemble` 통과, 실제 `api-ai-pipeline-smoke` gate는 `AiPipelineContractTest` **13개 통과**(서비스 6개, provider 호출 0, 네트워크 시도 0, 운영자 ingestion·extraction 상태 변경 없음)였습니다. 이 실행은 allow 뒤 재검증(`202`, `recoverOperation`)을 포함하던 **이전 계약**의 것이고, 그 계약은 최종 승인 계약(allow는 200으로 정확한 `approved` 이벤트를 채택, 재검증·`recoverOperation`·202 없음)으로 대체되었습니다. 이 기록 자체는 현재 규칙을 증명하지 않으며, 현재 계약의 증거는 바로 아래 항목입니다. 기존 S1 gate(`api-ai-smoke`)는 **9개 통과**했고 그 뒤 공통 transport는 바뀌지 않았습니다. 커밋·푸시·원격 CI·배포는 하지 않았고 replay는 authored 응답이라 실제 모델 품질의 증거가 아닙니다. 루트 Makefile에는 `api-ai-pipeline-smoke` 대상이 추가돼 있습니다.
- **현재 최종 승인 계약의 관측(2026-10-21, 로컬 작업 트리, Main 실행).** 실제 `api-ai-pipeline-smoke` gate는 `AiPipelineContractTest` **13개 통과**(서비스 6개, provider 호출 0)이고, 이 실행은 allow=최종 승인(200, 재검증·`recoverOperation` 없음)과 호출자가 명시하는 `ExecutionMode`(replay)가 들어간 **현재** Java 클라이언트를 쓴 것입니다. 전체 Java 시험은 **845개 중 808개 통과, 37개 skip, 실패 0**이었습니다(wrong-202 helper 단언을 고친 뒤). 이 gate는 replay만 실행하며 **live 모드의 Java→HTTP 경로를 유료 호출로 실행한 적은 없습니다.** 별도로 Main이 실행한 실제 CLI 유료 pipeline+Neo4j 합성 실행(14회 호출, 추정 USD 0.013323880)은 서비스·Java 클라이언트를 거치지 않았으므로 **유료 HTTP 경로의 증거가 아닙니다.** live S3를 서비스 HTTP·설치된 CLI·loopback 시뮬레이터(OpenAI chat+native Jev)로 끝까지 도는 증거는 [서비스 README](../../ai/service/README.md)의 `test_live_flow.py` 행에 있고 provider는 실제가 아닙니다. S1 유료 호출 주장은 하지 않습니다.
- **문서 분석 소비자의 최종 실행(2026-10-14, 로컬 작업 트리, Main 실행).** 이 클라이언트(`AiAnalysisClient`)의 첫 소비자인 [문서 분석](DOCUMENT_ANALYSIS.md)은 전체 Java 시험 **301개 통과, 실패 0, skip 0**과 `assemble`, 그리고 실제 Spring jar·HTTP·`ai/service`(replay)·worker·PostgreSQL 17.11 smoke(28단계, jar 65회, `document_analyses` 16·`ai_executions` 27 = 워커 호출 27·`evidence` 10, 모델·provider 호출 0)로 확인했습니다. submit·recover 직전의 현재 권한 재확인, 정산 transaction의 잠금 뒤 grant 재평가(잠금 대기 중 철회·만료), 검증자가 본 claim 대조, 파일 충돌 정리가 모두 통과했습니다. 공통 전송 계층은 이 변경에서 바뀌지 않았고 위 gate 9개·13개는 통과했다고 보고받았습니다. 커밋·푸시·원격 CI·live는 하지 않았습니다.
- 이 gate는 로컬 전용 가정(loopback HTTP)입니다. TLS 종단·SG·역프록시·운영 토큰은 관측한 사실이 없습니다([서비스 README 한계](../../ai/service/README.md#네트워크와-한계)).

## 호환성 보고 (2026-10-12)

- 해결: 서비스의 요청 ID 형식 검증(`[A-Za-z0-9._-]{1,128}`)과 foundation 필터의 무검증을 클라이언트에서 흡수(전달 전 검증/생성). 서비스의 소문자 오류 코드와 공개 대문자 `ErrorCode`를 섞지 않음.
- 격차(2026-10-12 기준, 아래 갱신으로 일부 해소): 인증·도메인 controller·entity·migration·작업 저장소 없음 → 클라이언트 자체는 DB를 쓰지 않으며 결과를 저장·공개하는 소비자가 아직 없음. 사용자 격리, 문서 버전·인용 검증, 단일 transaction import는 위 소유자 몫. S2-2/S3 HTTP 계약 없음.
- 최소 인계: (1) 첫 소비 기능 담당 — jobId↔사용자/문서/회차 결속, 위 4단계 import, AI 오류→공개 오류 매핑, 결과 불명 복구 절차. (2) 인증 담당 — `RequestIdFilter` 공개 경계 검증. (3) 운영 — 서비스 principal 토큰 발급·비밀 저장소 주입(`ZOOP_AI_CLIENT_TOKEN`)과 TLS 프록시 관측.
- 2026-10-13 갱신: 위 ‘entity·migration 없음’은 이후 병합된 인증 저장 migration·Entity(첫 `V20261012210200`과 v6 정렬 `V20261013000000`)로 부분적으로 바뀌었습니다. AI 결과를 저장하는 소비자와 작업 저장소는 여전히 없고, 병합된 ERD v6도 grant registry·검증 영수증 형식 등 일부를 닫지 않았습니다([위 절](#erd-v6-설계와의-관계)).
- 2026-10-14 갱신(문서 분석): 위 ‘AI 결과를 저장하는 소비자와 작업 저장소는 여전히 없고’ 중 소비자는 이제 있습니다. [문서 분석](DOCUMENT_ANALYSIS.md)은 이 `AiAnalysisClient`로 S1 `document-summary`/`document-sentiment`를 제출·조회·정산하는 operator 전용 비웹 실행입니다. AI jobId는 prepare에서 한 번 발급해 불변 `ai_submit`과 함께 커밋한 뒤에만 보내고, status를 먼저 읽으며, 결과는 입력 결속·artifact id·`resultVersion`·모델 설정 digest의 재계산과 코드 포인트 인용 검사를 거쳐 한 transaction으로 저장합니다(submit·recover 직전에는 현재 grant·article을 다시 확인하고, 정산은 article·행 잠금을 얻은 뒤 grant를 한 번 더 평가합니다). 실행 증거는 위 검증 절과 [문서 분석](DOCUMENT_ANALYSIS.md#검증)에 있습니다. `analysis_jobs`와 오류 매핑은 여전히 없고, 공개 읽기는 이후 2026-10-15 갱신의 `getEvidence` 한 건(부분 구현)뿐입니다.
- 2026-10-14 갱신: 위 ‘S2-2/S3 HTTP 계약 없음’은 이후 서비스가 별도 가족(`/internal/v1/extraction-jobs`, `/internal/v1/relation-jobs`)으로 제공했고, Java 쪽 `ExtractionClient`·`RelationClient`가 이를 소비합니다([S2·S3 절](#s2-추출s3-관계-클라이언트)). 앱 쪽 저장·결과 import·공개 endpoint·사용자 격리는 여전히 없습니다.
- 2026-10-15 갱신(근거 읽기): 위 ‘공개 endpoint … 여전히 없습니다’ 중 `GET /api/v1/evidence/{id}`(`getEvidence`)만 이제 있습니다([문서 분석 § 근거 읽기](DOCUMENT_ANALYSIS.md#근거-읽기-getevidence-부분-구현), 부분 구현). 이 읽기는 이 AI 클라이언트를 쓰지 않고 모델·AI 서비스를 호출하지 않으며 아무것도 쓰지 않습니다. 저장된 S1 요약의 본문 인용을 현재 문서 상태와 현재 grant registry(`ZOOP_DOCUMENT_READ_GRANTS`, 요청마다 읽음)로 다시 판정하고, 캐시로 돌려준 요약만 exact receipt 파일 한 건을 읽기 전용으로 읽습니다(`ZOOP_DOCUMENT_READ_ARTIFACT_ROOT`). 그래프가 없어 `eventIds`는 실패 구역이고 `sentiment`는 `null`이며 고정 버전 읽기는 409입니다. 인증·사용자 격리·`listCompanyDocuments`·그래프·승인·공개 반영은 여전히 없습니다.
- 2026-10-20 갱신(graph 근거): 같은 `getEvidence`가 스테이징된 graph 본문 근거도 읽습니다(고정된 공개 snapshot·선택된 버전의 receipt·S2-1 source registry `ZOOP_DOCUMENT_READ_INGESTION_SOURCES`). 이 읽기도 AI 클라이언트·모델을 호출하지 않고 쓰지 않으며 활성화 기능은 없습니다. 위 "그래프가 없어 `eventIds`는 실패 구역" 서술은 S1 근거에만 해당합니다. [규칙](GRAPH_READ_HANDOFF.md#2026-10-20-getevidence의-graph-본문-근거-경로-로컬-작업-트리-미게시)
