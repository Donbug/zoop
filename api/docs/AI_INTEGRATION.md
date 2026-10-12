# AI 분석 transport 클라이언트 (api → ai/service)

앱 백엔드가 S1 분석(`document-summary`, `document-sentiment`, `semantic-verification`, `briefing-outlook`, 계약 `zoop-ai-s1-1`)을 제출·조회·취소·복구하는 **전송 계층 클라이언트**입니다. 서버 쪽 정본은 [`ai/service/README.md`](../../ai/service/README.md)와 [`docs/api/internal-ai-openapi.yaml`](../../docs/api/internal-ai-openapi.yaml), 작업 JSON 스키마는 [`docs/api/ai-contract.schema.json`](../../docs/api/ai-contract.schema.json)입니다. 이 문서는 그 계약을 복제하지 않고 Java 쪽 책임·설정·소비 규칙만 적습니다.

## 지금 있는 것과 없는 것

| 구현됨 (실제 서비스로 검증) | 아직 없음 (소유자가 정해지면 첫 소비 기능이 추가) |
|---|---|
| `AiAnalysisClient`의 `submit` / `status` / `result` / `cancel` / `recover` 5개 operation 전부 | 공개 인증·세션·회원/관리자 권한, 도메인 controller·entity·Flyway migration |
| 4개 kind의 요청 봉투(`schemaVersion=zoop-ai-s1-1`)·타입 있는 응답·AI 오류 해석 | 작업 저장소(DB)와 앱 쪽 jobId 생성·재시도 정책, 스케줄러 |
| 설정 기반 bean(기본 비활성), 닫힘 실패 검증 | 결과 가져오기(import): 앱 문서 버전·근거 인용 검증과 한 transaction 쓰기 |
| 실제 `ai/service` + 설치된 `zoop-ai` replay 종단 시험 | S2-2 추출/S3 관계(`zoop-ai-extract`, `zoop-ai-relation`)와 S2-1 수집: 서비스에 HTTP 명령이 **없어** 지원하지 않음 |

public `ErrorCode`, 인증 필터, `RequestIdFilter`, `GlobalExceptionHandler`는 수정하지 않았습니다. 클라이언트는 서비스 주체(service principal)로 호출하는 **앱**이며 최종 사용자를 모릅니다.

## 코드 위치

| 위치 | 책임 |
|---|---|
| `com.zoop.ai` | 공개 타입: `AiAnalysisClient`, `AnalysisSubmission`, `AnalysisJobStatus`, `AnalysisResult`, `AnalysisAcknowledgement`, `UntrustedAnalysisPayload`, 예외(`AiServiceErrorException`, `AiTransportException`, `AiClientConfigurationException`), `AiClientSettings` |
| `com.zoop.ai.http` | JDK 21 `java.net.http.HttpClient` 구현(`HttpAiAnalysisClient`)과 엄격한 JSON 해석. 새 라이브러리 없음 |
| `com.zoop.ai.config` | `@ConfigurationProperties("zoop.ai.client")`와 조건부 bean |

`HttpClient` 주입, 경로·명령·소유자 override 경로는 없습니다. 경로는 코드에 고정된 `/internal/v1/analysis-jobs[...]` 5개뿐입니다.

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

## 소유와 격리

AI 서비스의 소유자는 **인증된 principal 하나**(이 앱)이며 최종 사용자(tenant) 식별이 없습니다. 같은 principal의 작업은 모두 같은 소유자라서 **사용자 간 격리는 이 클라이언트가 하지 않습니다.** 앱이 jobId를 사용자·문서·회차에 결속해 저장하고 접근 시 직접 확인해야 합니다. 다른 principal의 작업은 404와 동일하게 보입니다.

결과를 앱 데이터로 쓰기 전(후속 소비 기능 책임)에 모두 필요합니다.

1. 최종 사용자·관리자 권한 확인(서비스가 하지 않음).
2. 앱의 **불변 문서 버전**과 `documentVersion`/근거 인용(`evidence`, quote 오프셋)이 지금도 같은지 검증. `UntrustedAnalysisPayload`의 어떤 필드도 신뢰하지 않습니다.
3. 현재 출처 권리 재확인. `result`의 AVAILABLE은 요청 시점의 서버 grant일 뿐입니다.
4. 가져오기·상태 변경·공개 반영을 **하나의 transaction**으로. `READY` ≠ 공개 `completed`.

## 검증

```sh
# Java 21 (JAVA_HOME) 필요. 첫 실행은 Gradle 9.7.1(래퍼 SHA-256 검증)과 선언된 의존성을 받습니다.
make api-test        # 기본 gradle test: foundation 6개 + 클라이언트 시험(in-process 가짜 서버). Python·DB·네트워크 서비스 불필요
make api-build       # gradle assemble
make service-install api-ai-smoke   # 실제 Java -> uvicorn ai/service -> 설치된 zoop-ai replay 종단 gate
```

- `api-test`(기본 `test`)는 JDK `HttpServer` 가짜 서버로 헤더·본문 바이트·상태 코드·타임아웃·리다이렉트·과대 응답·모순 응답·요청 수(POST 재시도 없음)를, `ApplicationContextRunner`로 실제 `application.yml` 이름과 닫힘 실패를 확인합니다.
- `api-ai-smoke`는 `api/scripts/ai_contract_gate.py`가 임시 네임스페이스에 실제 서비스 2개(합성 principal, 인메모리 토큰, replay 전용, 모델·외부 네트워크·PostgreSQL 없음)를 띄우고 `./gradlew aiContractTest`를 실행합니다. 4개 kind 제출·조회·결과, 중복/충돌/소유자/인증/scope, withheld(grant 철회·복구), cancel/recover(막힌 fixture), 요청 ID, 연결 실패를 확인하고, JUnit 보고서에서 **실행된 시험 수가 0이 아니고 skip이 없는지**, 서비스 로그·Gradle 출력에 자격 증명이 없는지를 검사한 뒤 서비스와 임시 상태를 지웁니다. 매니페스트 환경 변수 없이 `aiContractTest`를 직접 실행하면 skip이 아니라 **실패**합니다.
- 이 gate는 로컬 전용 가정(loopback HTTP)입니다. TLS 종단·SG·역프록시·운영 토큰은 관측한 사실이 없습니다([서비스 README 한계](../../ai/service/README.md#네트워크와-한계)).

## 호환성 보고 (2026-10-12)

- 해결: 서비스의 요청 ID 형식 검증(`[A-Za-z0-9._-]{1,128}`)과 foundation 필터의 무검증을 클라이언트에서 흡수(전달 전 검증/생성). 서비스의 소문자 오류 코드와 공개 대문자 `ErrorCode`를 섞지 않음.
- 격차: 인증·도메인 controller·entity·migration·작업 저장소 없음 → 클라이언트는 앱 DB 없이 동작하며 결과를 저장·공개하는 소비자가 아직 없음. 사용자 격리, 문서 버전·인용 검증, 단일 transaction import는 위 소유자 몫. S2-2/S3 HTTP 계약 없음.
- 최소 인계: (1) 첫 소비 기능 담당 — jobId↔사용자/문서/회차 결속, 위 4단계 import, AI 오류→공개 오류 매핑, 결과 불명 복구 절차. (2) 인증 담당 — `RequestIdFilter` 공개 경계 검증. (3) 운영 — 서비스 principal 토큰 발급·비밀 저장소 주입(`ZOOP_AI_CLIENT_TOKEN`)과 TLS 프록시 관측.
