# Zoop API 실행 환경

Spring Boot 실행 기반, 공통 오류 처리, 내부 AI 분석 transport 클라이언트와 ERD v6에 맞춘 인증 DB 스키마가 있습니다. 공개 약관 조회·이메일 회원가입·로그인·회원/비회원 세션 발급 및 조회가 구현됐습니다. 문서 저장(`artifacts`·`articles`·`article_versions`)과 operator 전용 비웹 import([문서 import](docs/DOCUMENT_IMPORT.md)), S1 문서 분석([문서 분석](docs/DOCUMENT_ANALYSIS.md))도 지원합니다. 루트 `make api-test`·`api-build`·`api-ai-smoke`와 CI job `api`가 연결돼 있습니다. 기존 프로토타입과 DB를 공유하지 않습니다.

## 도구

- Java 21
- Spring Boot 4.1.1
- Gradle 9.7.1 Wrapper (공식 배포 SHA-256 검증)
- Docker Compose v2와 PostgreSQL 16.13 Alpine

Java 21과 Gradle 버전은 프로젝트에 고정했습니다. `JAVA_HOME`을 설치된 JDK 21 경로로 설정하세요. macOS에서는 `export JAVA_HOME=$(/usr/libexec/java_home -v 21)`을 사용할 수 있습니다. IDE의 Project SDK와 Gradle JVM도 Java 21로 설정합니다.

## 로컬 실행

아래 명령은 저장소 루트에서 실행합니다. 최초 빌드에는 Gradle과 Maven 의존성을 받기 위한 인터넷 연결이 필요합니다.

```sh
cp api/.env.example api/.env
# api/.env에 필수 ZOOP_AUTH_CSRF_KEYS와 사용할 ZOOP_AUTH_ALLOWED_ORIGINS를 설정합니다.
# 필요하면 포트·DB 이름·계정 값도 수정합니다.

docker compose --env-file api/.env -f api/compose.local.yaml up -d --wait
cd api
SPRING_PROFILES_ACTIVE=local ./gradlew bootRun
```
```powershell
# 윈도우용
Copy-Item api/.env.example api/.env
# api/.env에 필수 값과 사용할 Origin을 설정합니다.
$env:SPRING_PROFILES_ACTIVE = "local"

docker compose --env-file api/.env -f api/compose.local.yaml up -d --wait
Set-Location api
.\gradlew.bat bootRun
```

필요한 로컬 프로필 설정은 `application-local.yml`에서 확인하세요.

`application.yml`의 `spring.config.import`가 실행 작업 디렉터리의 `.env`를 Spring 설정으로 읽습니다. 위 명령처럼 `api` 디렉터리에서 실행하면 `api/.env`가 적용되며, 셸에서 파일을 미리 내보낼 필요가 없습니다. IDE로 실행할 때도 작업 디렉터리를 `api`로 지정하세요. 실제 OS 환경변수가 있으면 `.env` 값보다 우선합니다.

이 import는 `System.getenv()` 값을 설정하지 않으므로, 자식 프로세스에 환경변수를 전달해야 하는 별도 작업에서는 셸에서 내보내야 합니다. Compose의 `--env-file`은 DB 컨테이너 설정에만 적용됩니다.

| 변수 | 용도 |
|---|---|
| `DB_PORT` | 로컬 PostgreSQL 호스트 포트 (Compose 기본값 5432) |
| `DB_NAME` | 로컬 PostgreSQL DB 이름 |
| `DB_URL` | 애플리케이션의 JDBC URL |
| `DB_USERNAME` | DB 계정 |
| `DB_PASSWORD` | DB 비밀번호 |
| `SERVER_PORT` | 애플리케이션 포트 (기본값 8080) |
| `ZOOP_AUTH_CSRF_ACTIVE_KEY_ID` | 새 회원·비회원 세션의 CSRF 서명 키 ID. 예: `local-v1` |
| `ZOOP_AUTH_CSRF_KEYS` | `키ID=base64url(32바이트 이상)` 목록. 키 회전 중에는 쉼표로 이전 키도 유지 |
| `ZOOP_AUTH_ALLOWED_ORIGINS` | 가입·로그인·비회원 시작 및 회원/비회원 쿠키가 붙은 쓰기 요청을 허용할 정확한 Origin 목록(쉼표 구분). 일반 프로필은 HTTPS만, 로컬 프로필은 loopback HTTP도 허용. 빈 값은 전부 거절 |
| `ZOOP_API_CORS_ALLOWED_ORIGINS` | `/api/**` 전체에 적용할 브라우저 CORS 허용 Origin 목록(쉼표 구분). 비어 있으면 CORS 매핑을 등록하지 않음 |
| `ZOOP_AUTH_TRUSTED_PROXIES` | `X-Forwarded-For`를 제공할 수 있는 프록시의 숫자 IP 목록(쉼표 구분). 빈 값은 전달 헤더 무시 |
| `ZOOP_CHAT_QUESTIONS_ENABLED` | 선택. AI 챗봇 질문·재시도 접수(기본 `false`). 꺼져 있으면 `submitQuestion`·`retryQuestionJob`이 503 `MODEL_UNAVAILABLE`을 반환해 실행되지 않을 작업을 만들지 않습니다. 대화 생성·조회·복원과 작업 조회·취소는 플래그와 무관하게 동작하며 모델을 호출하지 않습니다. 켜려면 `ChatEngine`(오케스트레이터)이 등록돼 있어야 하며(`ZOOP_AI_CHAT_CLIENT_ENABLED=true`가 등록) 없으면 기동을 거절합니다. `ZOOP_CHAT_EXECUTOR_ENABLED`(기본 `true`)·`ZOOP_CHAT_EXECUTOR_WORKERS`(기본 2)는 대기 작업을 집어 실행하고 만료된 lease를 회수하는 실행기이며, 엔진이 없으면 아무 작업도 집지 않습니다 |
| `ZOOP_CHAT_MCP_ENABLED` `ZOOP_CHAT_MCP_ACTIVE_KEY_ID` `ZOOP_CHAT_MCP_KEYS` `ZOOP_CHAT_MCP_SEND_GRANTS` `ZOOP_CHAT_MCP_SEND_RECIPIENT` | 선택. 챗봇 읽기 도구를 실행 중인 job 범위의 MCP로 여는 `POST /mcp`(기본 `false`, 꺼지면 경로 자체가 없음). 켜면 job 위임 토큰 서명 키(`id=base64url`, 32바이트 이상, 쉼표 구분)와, 결과를 모델로 보내기 전에 확인할 운영자 챗봇 grant 레지스트리(`zoop-ai-chat-1`, AI runtime `--grants`와 같은 파일의 절대 경로)·`chat-agent` 단계 수신자가 필요하며 없거나 레지스트리를 읽지 못하면 기동을 거절합니다. 모델 API 키·CSRF 키와 별개입니다. 상세와 켜기 전 조건은 [챗봇 MCP 엔드포인트](docs/chat-mcp.md) |
| `ZOOP_CHAT_AGENT_ENABLED` | 선택. agent 경로(Luna가 `/mcp` 도구를 고르고 서버가 호출마다 승인, 기본 `false`). `/mcp`와 챗봇 모델 단계가 있어야 하며 없으면 기동을 거절합니다. 공급자가 `/mcp`에 닿는 HTTPS URL은 AI runtime의 `ZOOP_AI_CHAT_MCP_SERVER_URL`로만 정합니다. 독립 1단계 읽기 계획만 이 경로를 타고 나머지는 기존 direct 경로입니다 |
| `ZOOP_AI_CLIENT_*` `ZOOP_AI_EXTRACTION_CLIENT_*` `ZOOP_AI_RELATION_CLIENT_*` `ZOOP_AI_CHAT_CLIENT_*` `ZOOP_AI_PLAN_ADMISSION_CLIENT_*` | 선택. 내부 AI transport 클라이언트는 가족별로 독립이며 기본 비활성입니다. 설정은 [AI 연동](docs/AI_INTEGRATION.md#설정), [S2·S3](docs/AI_INTEGRATION.md#s2-추출s3-관계-클라이언트), [챗봇](docs/AI_INTEGRATION.md#챗봇-모델-단계-클라이언트), [계획 접수](docs/AI_INTEGRATION.md#계획-접수-클라이언트)를 따릅니다. |
| `ZOOP_ADMIN_REVIEW_RECONCILE_ENABLED` `ZOOP_ADMIN_REVIEW_RECONCILE_*` | 선택, 기본 `true`이지만 **AI 관계 클라이언트(`ZOOP_AI_RELATION_CLIENT_ENABLED=true`)가 있을 때만** 동작합니다. 관리자 HOLD 검수 결정의 AI 응답을 잃었을 때(미확인·blocked) 웹 애플리케이션이 전용 스레드에서 AI 원장을 조회해 정리합니다(`ReviewDecisionService.reconcile`). 미확인 결정은 같은 operation으로 다시 보내며, 원천은 두 번 기록하지 않습니다. 주기 `INTERVAL`(기본 `PT1M`), 만든 지 `MIN_AGE`(기본 `PT2M`)가 지난 의도부터, 한 번에 `BATCH`(기본 50)건. 열린 의도가 남으면 수가 바뀔 때와 1시간마다 경고합니다. `false`로 끌 수 있고, 비웹 실행에서는 동작하지 않습니다. |
| `ZOOP_DOCUMENT_IMPORT_*` `ZOOP_INGESTION_*` `ZOOP_ARTIFACT_ROOT` | 선택. operator 전용 비웹 문서 import(기본 비활성, 설정 없이도 기동). `ZOOP_DOCUMENT_IMPORT_OBSERVATION_SOURCE`가 `cli`(기본)면 `ZOOP_INGESTION_*` 셋이 필요하고, `http`면 셋을 비우고 `ZOOP_AI_OBSERVATION_EXPORT_CLIENT_*`(아래 그래프 import 행과 같은 클라이언트)가 필요합니다. 이름·규칙은 [문서 import](docs/DOCUMENT_IMPORT.md#실행) |
| `ZOOP_DOCUMENT_ANALYSIS_*` | 선택. operator 전용 비웹 문서 분석(기본 비활성, 설정 없이도 기동). S1 AI 클라이언트(`ZOOP_AI_CLIENT_*`)와 위 `ZOOP_INGESTION_*`·`ZOOP_ARTIFACT_ROOT`도 필요하고 문서 import와 한 프로세스에서 함께 켤 수 없습니다. 이름·규칙은 [문서 분석](docs/DOCUMENT_ANALYSIS.md#실행) |
| `ZOOP_DOCUMENT_BINDINGS_*` | 선택. operator 전용 비웹 문서 bindings export(기본 비활성, 설정 없이도 기동). AI `zoop-ai-handoff freeze`의 `--bindings` 파일(`zoop-app-document-bindings-1`)을 앱 DB에서 만듭니다. DB 읽기만 하며 lock을 잡지 않습니다. 이름·규칙은 [문서 bindings](docs/DOCUMENT_BINDINGS.md#실행) |
| `ZOOP_DOCUMENT_READ_GRANTS` `ZOOP_DOCUMENT_READ_INGESTION_SOURCES` `ZOOP_DOCUMENT_READ_ARTIFACT_ROOT` | 선택. 공개 `GET /api/v1/evidence/{id}`(운영 플래그와 독립, 읽기 전용). `GRANTS`는 operator의 flat S1 grant registry 파일로 S1 요약 근거에만 쓰이고 요청마다 읽으며 미설정이면 그 읽기는 503입니다. `INGESTION_SOURCES`는 graph 본문 근거용 `zoop-ingestion-s2-1` registry 또는 exact grant tuple별 로컬 leaf를 지정하는 `zoop-source-authority-set-1` 파일입니다([여러 원장 읽기와 현재 권한](#여러-원장-읽기와-현재-권한)). 요청마다 현재 권한을 읽으며 미설정이면 graph 근거 읽기는 503입니다. `ARTIFACT_ROOT`는 캐시로 돌려준 요약의 exact receipt, 그리고 graph 근거의 선택된 버전 import receipt 한 건을 읽을 때만 필요합니다(미설정이면 그 경우만 503). 값이 있는데 정규화된 절대 경로가 아니거나 없으면 기동 실패. 이 권한 선택은 백엔드 소유자(정세빈) 확인 전까지 배포하지 않습니다. 규칙은 [문서 분석 § 근거 읽기](docs/DOCUMENT_ANALYSIS.md#근거-읽기-getevidence-부분-구현)와 [graph 본문 근거 경로](docs/GRAPH_READ_HANDOFF.md#2026-10-20-getevidence의-graph-본문-근거-경로) |
| `ZOOP_GRAPH_SNAPSHOT_SOURCE` `ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT` | 선택. 공개 그래프 스냅샷을 어디서 읽을지 정합니다. 기본 `none`: 등록된 버전이 있어도 스냅샷 읽기는 503 `SOURCE_UNAVAILABLE`이고, 버전이 없으면 409 `VERSION_UNAVAILABLE`입니다(빈 그래프로 대체하지 않음). `fixture`: **local/dev 전용**이며, 기동 시 `src/main/resources/graph-fixtures/`의 합성 스냅샷 2개를 `graph_versions`에 등록·활성화합니다(제목 `[합성]`, 실제 뉴스 아님). 이미 가져온(non-fixture) 버전이 있는 DB에서는 기동을 거절합니다. `artifact`: `ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT`(정규화된 절대 경로)의 스냅샷 파일을 레지스트리 hash·크기로 검증해 읽기 전용으로 읽고, 이미 등록된 fixture 버전(classpath 위치)은 기존 fixture 읽기 경로가 그대로 읽어 기존 읽기가 달라지지 않습니다(아래 [그래프 handoff 스테이징 import](#그래프-handoff-스테이징-import)). 어떤 버전을 공개로 보여 줄지는 여전히 선택기와 활성 포인터가 정하며 `artifact`가 등록·활성화하지 않습니다. 규칙은 [그래프 조회 계약 결정](../docs/api/graph-read-contract-proposal.md) §0 |
| `ZOOP_GRAPH_ACTIVATION_ALLOW_WITHOUT_EXCLUSION_STORE` | 선택, 기본 `false`. **이제 효과가 없습니다.** 공개 제외 저장소(FS081, 아래 "공개 제외 명령")가 생겨서 관리자 활성화(`activateGraphVersion`)는 항상 그 버전의 현재 제외를 적용해 사전 검사합니다. 저장소가 없는 reader(시험용)에서만, 수입한(non-fixture) 버전을 기본으로 503 `SOURCE_UNAVAILABLE`로 거절하고 `true`면 허용합니다. 이때도 활성화 직전의 권리·근거 검사(기사 접근 상태, 선택 버전 receipt의 grant, 현재 S2-1 원천 registry)는 그대로 적용됩니다. 합성 fixture 버전에는 영향이 없습니다. 대신 fixture 버전은 `ZOOP_GRAPH_SNAPSHOT_SOURCE=fixture`일 때만 활성화할 수 있고, `artifact`·`none`에서는 422로 거절합니다(운영 DB에 남은 `[합성]` 행이 공개 그래프가 되지 않도록). |
| `ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED` `ZOOP_GRAPH_AUTO_ACTIVATION_*` | 선택, 기본 `false`. 켜면 **웹 애플리케이션**이 실제 활성 포인터가 없거나 fixture일 때만 가장 최근의 원본 native snapshot을 관리자 활성화(`activateGraphVersion`)와 **같은 사전 검사**(권리·근거·공개 제외·snapshot 읽기)를 거쳐 system 주체로 활성화합니다(FS059, 활성화 이력 `actor_kind=system`). Legacy 입력과 누적 후보는 수동 활성화 대상입니다. 실데이터가 이미 활성화돼 있으면 새 원본 입력은 누적 구성과 수동 CAS 활성화를 거쳐야 하며, 후보 조회와 publication lock 안의 실행 단계에서 모두 이 조건을 확인합니다. 현재 공개 버전보다 앞선(`sequence`가 작은) 수입은 활성화하지 않고, 시작 시각에서 `LOOKBACK`(기본 `PT30M`, 한 회차)만큼 되돌아본 뒤에 수입된 버전만 대상입니다. 확인 주기 `INTERVAL`(기본 `PT15S`), 검사 거절 뒤 재시도 `RETRY_AFTER`(기본 `PT5M`), 소스 장애·그 밖의 실패 뒤 재시도 `UNAVAILABLE_RETRY_AFTER`(기본 `PT1M`). 전용 스레드에서 돌고, 수입·제외 명령 같은 비웹 실행에서는 동작하지 않습니다. 바꾸려면 재시작합니다. 관리자가 수동으로 활성화하면 그보다 먼저 수입돼 기다리던 버전은 자동으로 활성화하지 않습니다. |
| `ZOOP_GRAPH_HANDOFF_IMPORT_*` `ZOOP_HANDOFF_*` `ZOOP_RELATION_STATE_DIR` `ZOOP_EXTRACTION_STATE_DIR` | 선택. operator 전용 비웹 그래프 handoff 스테이징 import(기본 비활성, 설정 없이도 기동). `ZOOP_ARTIFACT_ROOT`가 필요하고, 위 `ZOOP_INGESTION_*`는 이 프로세스가 CLI를 실행하는 경우에만 필요합니다(아래 두 행). 문서 import·분석, `fixture` 소스와 한 프로세스에서 함께 켤 수 없습니다. 이름·규칙은 [그래프 handoff 스테이징 import](#그래프-handoff-스테이징-import) |
| `ZOOP_GRAPH_HANDOFF_IMPORT_HANDOFF_SOURCE` `ZOOP_AI_HANDOFF_READ_CLIENT_*` | 선택. 위 import가 handoff를 어디서 읽을지: `cli`(기본, 설치된 `zoop-ai-handoff export`) 또는 `http`(ai/service `GET /internal/v1/graph-handoffs/{id}/bundle`, scope `handoff.read`). `http`면 `ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED=true`·`_BASE_URL`·`_TOKEN`(다른 scope와 별도 token, 응답 상한 기본 16 MiB)이 필요하고 `ZOOP_HANDOFF_CLI`·`ZOOP_HANDOFF_STATE_DIR`·`ZOOP_RELATION_STATE_DIR`·`ZOOP_EXTRACTION_STATE_DIR`·`ZOOP_HANDOFF_CANONICAL`·`_DECISIONS`·`_BINDINGS`는 비워 둡니다(설정되어 있으면 기동 거절). [그래프 handoff 스테이징 import](#그래프-handoff-스테이징-import) |
| `ZOOP_GRAPH_HANDOFF_IMPORT_OBSERVATION_SOURCE` `ZOOP_AI_OBSERVATION_EXPORT_CLIENT_*` | 선택. 위 import가 관측마다 현재 권리를 어디서 재확인할지: `cli`(기본, 설치된 `zoop-ai-ingest export --require-store`) 또는 `http`(ai/service `POST /internal/v1/observations/export`, scope `observation.read`, 관측 1건 = 요청 1건 동기, AI PR #431). `http`면 `ZOOP_AI_OBSERVATION_EXPORT_CLIENT_ENABLED=true`·`_BASE_URL`·`_TOKEN`(요청 deadline 기본 50초 > AI child 45초, 응답 상한 기본 16 MiB)이 필요하고 `ZOOP_INGESTION_CLI`는 비워 둡니다. `ZOOP_INGESTION_STATE_DIR`·`ZOOP_INGESTION_SOURCES`는 이 프로세스가 CLI를 하나라도 실행할 때만 두고, handoff와 관측이 모두 `http`면 둘 다 비웁니다. `cli`는 켜진 export 클라이언트를 무시합니다(설정을 공유하는 웹 애플리케이션이 그 클라이언트를 가질 수 있습니다. 회차 bridge의 연결은 후속 PR). 응답은 CLI JSON 그대로라 같은 S2-1 파서가 검증하며, 4xx는 `ingestion_export_failed`(그 코드), 5xx·전송 실패는 `ingestion_export_unavailable`, 계약 밖 응답은 `export_invalid`입니다 |
| `ZOOP_GRAPH_ROUND_ENABLED` `ZOOP_GRAPH_ROUND_*` | 선택, 기본 `false`. #55 그래프 정기 회차의 앱 쪽 조각을 **웹 애플리케이션**에 등록합니다. 이 릴리스에는 회차 상태 테이블(`graph_rounds`·`graph_round_events`), 수입 bridge(운영자 명령과 같은 수입기를 웹 안에서 호출, handoff는 `ZOOP_AI_HANDOFF_READ_CLIENT_*`로 읽고 `ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT`에 씀), 관리자 회차 읽기(`listGraphRounds`·`getGraphRound`·overview `rounds`)가 있고 스케줄러 본체는 AI #387 뒤에 붙습니다. 켜면 `ZOOP_GRAPH_SNAPSHOT_SOURCE=artifact`와 읽기 클라이언트가 필수이고, `IMPORT_SOURCE=cli`(기본)면 `INGESTION_CLI`·`INGESTION_STATE_DIR`·`INGESTION_SOURCES`(관측 재확인용 `zoop-ai-ingest`)가 필요합니다(`http`는 `ZOOP_AI_OBSERVATION_EXPORT_CLIENT_*`로 관측 export를 읽는 연결이 후속 PR에서 들어오기 전까지 기동 거절). `OPERATOR`(수입 요청의 operator, 기본 `scheduler`), `WAIT_RETRY_AFTER`(`PT1M`), `BUSY_RETRY_AFTER`(`PT5M`), `MAX_ATTEMPTS_PER_STAGE`(20). 상세는 [그래프 정기 회차](docs/GRAPH_ROUND.md) |

`DB_PORT`나 `DB_NAME`을 바꾸면 `DB_URL`도 일치하게 수정하세요. `.env.example`의 비밀번호는 로컬 전용 예시이며 운영용이 아닙니다. 실제 `.env`는 Git에서 제외됩니다. 이미 초기화된 DB 볼륨의 계정·비밀번호는 설정값만 바꿔도 변경되지 않습니다.

### 프로세스 생존 확인

인증 없이 `GET /health`를 호출하면 HTTP 200과 `{"status":"UP"}`만 반환합니다. 쿠키·Authorization·CSRF 토큰은 필요하지 않으며, 응답 본문에 비밀 값이나 내부 오류·연결 정보를 포함하지 않습니다.

```sh
curl --fail-with-body -i http://localhost:8080/health
```

이 엔드포인트는 요청을 처리하는 프로세스의 생존(liveness)만 확인합니다. DB·AI·외부 서비스에 요청하거나 준비 상태(readiness)를 집계하지 않으므로, **정상 기동 후 DB 연결이 끊겨도 프로세스가 HTTP 요청을 처리하는 동안에는 200을 반환합니다.** 다른 API의 정상 동작이나 시작 작업의 완료를 보장하지 않습니다.

이는 **DB 없이 전체 애플리케이션이 기동한다는 뜻이 아닙니다.** 일반 기동에는 `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`, 접근 가능한 PostgreSQL, Flyway 마이그레이션·JPA 스키마 검증, 시작 시 기업 카탈로그 import가 필요합니다. 필수 CSRF 서명 키 설정도 그대로 필요합니다. AI 클라이언트는 기본 비활성입니다. DB 자동 설정을 제외하거나 별도 프로필로 웹 서버만 띄우는 우회 경로는 제공하지 않습니다.

메서드 처리는 기존 Spring MVC 설정을 유지합니다. `HEAD /health`는 200과 빈 본문, `OPTIONS /health`는 200과 `Allow: GET, HEAD, OPTIONS`를 반환합니다. `POST`·`PUT`·`PATCH`·`DELETE`는 405이며, 오류 본문은 기존 공통 오류 처리의 `INVALID_REQUEST` 형식입니다.

컨트롤러 테스트는 HTTP 응답 계약을 검증하며 전체 애플리케이션이나 컨테이너 기동의 증거는 아닙니다. 실제 이미지의 8080 포트와 기동 후 DB 중단 시나리오는 [API Dev 배포 절차의 로컬 컨테이너 검증](../docs/development/api-dev-deployment.md#51-로컬-컨테이너-생존-확인)을 따릅니다.

### 그래프 읽기 로컬 빠른 시작 (합성 fixture, 일회용)

백엔드 그래프 읽기(`GET /api/v1/graph`, `asOf`, `GET /api/v1/graph/edges/{id}`)를 AWS·Neo4j·AI 모델·`api/.env` 없이 개발할 때 쓰는 **명시적 옵트인** 런처입니다. 일회용 PostgreSQL 컨테이너 하나와 **빌드된 jar**를 띄우고, 앱의 기존 `ZOOP_GRAPH_SNAPSHOT_SOURCE=fixture`로 jar에 들어 있는 합성 스냅샷 2개(`fixture-2026-10-01`, `fixture-2026-10-08`, 제목 `[합성]`)를 등록·활성화합니다. 실제 뉴스나 AI handoff import가 아니라 **임시 개발용 합성 데이터**이며, 멈추면 DB째 사라집니다. 그래프 handoff import(`com.zoop.graph.importer`)와는 별개이고, `fixture` 소스는 import된 버전이 있는 DB를 거절하므로 이 런처는 매번 새 DB만 씁니다.

```sh
make api-build      # jar가 없을 때만. 런처는 빌드·pull을 하지 않습니다
make api-graph-dev  # 준비되면 URL을 출력하고 Ctrl-C까지 실행
```

준비 완료는 로그의 `Started`가 아니라 **실제 HTTP 읽기**로 판정합니다(fixture 등록은 `Started` 뒤에 끝납니다). 기본 그래프, `asOf=2026-10-05T00:00:00Z`(옛 버전 `fixture-2026-10-01`), 간선 상세가 모두 200이어야 `READY`와 URL을 출력합니다. 다른 터미널에서 바로 확인할 수 있습니다.

```sh
curl -s http://127.0.0.1:<출력된 포트>/api/v1/graph
curl -s 'http://127.0.0.1:<출력된 포트>/api/v1/graph?asOf=2026-10-05T00:00:00Z'
```

- 격리: DB는 고유 이름·`127.0.0.1`의 임의 포트·실행마다 새로 만든 합성 계정(tmpfs, 볼륨 없음)입니다. 앱은 상속 환경변수 없이 최소 환경과 빈 임시 작업 디렉터리에서 뜨므로 AWS·모델 키나 `api/.env`, 내 DB를 읽거나 쓰지 않고, CSRF 서명 키·DB 비밀번호는 실행마다 새로 만들어 출력하지 않습니다.
- 필요 조건: JDK 21(`JAVA_HOME`), 실행 중인 Docker, 로컬에 이미 있는 PostgreSQL 이미지(기본 `postgres:16.13-alpine`, `compose.local.yaml`·CI와 같음), 빌드된 jar. 없으면 이유를 밝히고 실패하며 자동으로 pull하지 않습니다.
- 옵션: `make api-graph-dev LOCAL_GRAPH_DEV_PORT=8080 LOCAL_GRAPH_DEV_IMAGE=<이미 받은 이미지>`. 포트 기본값 0은 빈 포트를 고릅니다. 프론트에서 고정 포트가 필요하면 지정하세요(로컬 프로필이라 `http://localhost:3000` CORS가 허용됩니다).
- 종료: Ctrl-C(SIGINT)나 SIGTERM/SIGHUP이면 앱을 멈추고 컨테이너(`docker rm -f -v`)와 임시 디렉터리를 지웁니다. 정상적인 Ctrl-C는 남는 자원이 없습니다. `make`로 실행했다면 Ctrl-C 뒤 make가 interrupt 오류(예: `Error 130`)와 non-zero 상태를 보고할 수 있으며, 이는 make 자신의 중단 상태이고 정리 실패가 아닙니다(런처는 이를 가리지 않습니다). 정리 결과는 런처의 `database container … removed` 로그와 `docker ps -a --filter label=com.zoop.local-graph-dev=1`(빈 출력)로 확인하세요. SIGKILL로 죽이면 정리하지 못하므로 같은 명령으로 찾아 `docker rm -f -v <이름>` 하세요.
- Windows PowerShell(make 없이): `python api\scripts\local_graph_dev.py [--server-port 8080] [--image <이미지>] [--jar <jar>] [--java <java.exe>]`. 도움말은 `python api/scripts/local_graph_dev.py --help`입니다.

### 로컬 HTTP 브라우저 테스트

`application-local.yml`은 로컬 프로필에서만 `http://localhost:5173` 프론트의 `/api/**` CORS 요청을 허용하고 세션 쿠키의 `Secure` 속성을 끕니다. 인증 Origin 검증에는 프론트와 API에서 직접 여는 Swagger UI의 Origin(`http://localhost:8080`)을 모두 허용합니다. 백엔드 포트를 바꾸면 API Origin도 같은 포트로 지정하세요. 일반 프로필의 HTTPS Origin 검증과 보안 쿠키 설정은 그대로 적용됩니다.

`api/.env.example`의 `ZOOP_AUTH_ALLOWED_ORIGINS`는 빈 값이므로, `api/.env`에 로컬 테스트 값을 넣거나 아래처럼 실행 시 환경변수로 지정해야 합니다. 다음 명령은 저장소 루트에서 시작합니다.

```sh
export SPRING_PROFILES_ACTIVE=local
export ZOOP_SWAGGER_ENABLED=true
export ZOOP_AUTH_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8080
export ZOOP_API_CORS_ALLOWED_ORIGINS=http://localhost:5173
docker compose --env-file api/.env -f api/compose.local.yaml up -d --wait
cd api
./gradlew bootRun
```

Swagger UI는 `http://localhost:8080/swagger-ui.html`에서 API와 같은 Origin으로 열리므로 CORS 허용 목록에 API 주소를 추가할 필요가 없습니다. 프론트에서 직접 호출할 때는 프론트 담당자가 API 주소를 `http://localhost:8080`으로 지정하고 쿠키 요청에 credentials를 포함해야 합니다. 다른 출처나 `/api/**` 바깥 경로가 필요하면 공통 설정인 `common/config/ApiCorsConfiguration.java`와 `zoop.api.cors.allowed-origins`를 검토하세요.

회원·비회원 세션용 키를 로컬에서 생성해 `api/.env`의 `ZOOP_AUTH_CSRF_KEYS`에 `local-v1=<출력값>` 형식으로 넣으세요. `python3 -c 'import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))'`로 생성할 수 있습니다. 키 설정이 없거나 32바이트 미만이면 서버 기동이 실패합니다. 운영에서는 비밀 저장소로 두 환경변수를 주입하고, 키를 교체할 때 아직 살아 있는 세션이 참조하는 이전 키를 목록에 보관합니다. 이 값과 세션 쿠키 원문은 로그나 저장소에 남기지 마세요.

`/`의 404는 정상입니다. 서버 로그의 `Started ZoopApplication`과 DB·Flyway 초기화를 확인하세요. 잘못된 DB 설정에서는 기동이 실패해야 합니다.

본개발 가입 화면은 공개 `GET /api/v1/auth/terms`로 현재 제공 가능한 약관을 조회해야 합니다. `limit`와 응답의 `nextCursor`로 다음 페이지를 요청할 수 있으며, `limit`을 생략하면 전체 목록을 반환합니다. 약관 시행 전에는 항목 자체는 조회되지만 `body`와 `version`이 `null`, `bodyAvailable`이 `false`입니다. 이번 승인 본문의 시행일은 2026-10-13 17:00 KST입니다. 가입 로직은 유효한 필수 약관 본문이 제공되기 전에는 완료되면 안 됩니다.

`POST /api/v1/auth/signup`은 현재 유효한 필수 약관 버전과 실제 동의를 확인한 뒤 회원·동의·세션을 한 트랜잭션에 저장하고 `201 SessionResponse`와 보안 쿠키를 반환합니다. 새 비밀번호는 8~32 Unicode code point이며, 제어 문자와 등록된 흔한 비밀번호는 거절합니다. `POST /api/v1/auth/login`은 이메일·비밀번호로 활성 회원을 인증해 `200 SessionResponse`와 새 보안 쿠키를 반환합니다. 잘못된 자격 증명은 `401 INVALID_CREDENTIALS`, 비밀번호가 맞는 차단 계정은 `403 MEMBER_BLOCKED`입니다. 가입·로그인 입력과 응답 형식은 [OpenAPI](../docs/api/openapi.yaml)를 따릅니다.

`POST /api/v1/auth/guest`는 허용 Origin을 확인한 뒤 비회원 세션을 발급하고 `200 SessionResponse`와 `zoop_session` 쿠키를 반환합니다. 회원가입이나 로그인이 필요하지 않습니다. 회원과 비회원 세션은 12시간 절대 만료를 사용합니다. guest 응답은 `kind=guest`, `authenticated=true`, `user=null`, `setup.completed=false`, `setup.tutorialCompleted=false`입니다. guest는 전체 그래프와 공개 기업·브리핑을 읽을 수 있지만 계좌 연결, 관심종목 저장, 개인화 조회, AI 질문·평가를 할 수 없습니다.

`GET /api/v1/auth/session`은 `zoop_session` 쿠키가 없으면 `anonymous`를 반환하고 새 세션을 만들지 않습니다. 유효한 회원 쿠키는 회원·설정 상태, 유효한 비회원 쿠키는 guest 상태와 함께 만료 시각·세션 결합 CSRF 토큰을 반환합니다. 만료·폐기·무효 쿠키는 `Max-Age=0`으로 제거합니다. 세션 토큰 원문은 쿠키로만 전달하고 DB에는 SHA-256 해시만 저장합니다. guest 튜토리얼 진행·완료·건너뛰기는 서버에 저장하지 않으며 응답의 `tutorialCompleted`는 항상 `false`입니다.

회원 전용 경계는 [이슈 #31 인계 문서](../docs/development/issue-31-guest-access-handoff.md)에 연결돼 있습니다. 개인 API는 세션에서 얻은 `MemberPrincipal`을 사용하고 리소스 소유자와 일치하는지 확인해야 합니다. `PUT /api/v1/auth/tutorial`은 회원의 튜토리얼 완료 목표 상태를 저장하고 최신 `SessionResponse`를 반환합니다. 같은 상태의 재요청은 버전을 다시 올리지 않으며, 상태가 바뀌면 회원 설정 버전이 한 번 증가합니다. guest는 저장 없이 `403 MEMBER_REQUIRED`, 세션이 없으면 `401 AUTH_REQUIRED`를 반환합니다.

회원 또는 비회원 쿠키가 붙은 `/api/v1/**` 쓰기 요청은 허용 Origin과 단일 `X-CSRF-Token` 헤더를 검사합니다. 토큰은 현재 활성 세션에 결합되어야 하며 누락·불일치·만료·폐기·중복 쿠키/헤더는 `403 ACCESS_DENIED`입니다. 가입·로그인·비회원 시작은 세션 발급 전 Origin을 별도로 검사합니다. 관리자 경로는 회원 CSRF 인터셉터에서 분리해 별도 `zoop_admin_session` 및 관리자 전용 세션 결합 CSRF 검증을 사용합니다. 관리자 세션은 30분 유휴/8시간 절대 만료이며 `ZOOP_ADMIN_IDLE_TIMEOUT`, `ZOOP_ADMIN_ABSOLUTE_TIMEOUT`으로 조정할 수 있습니다. 관리자 로그인은 IP 100회/15분 및 이메일 비교키 실패 20회/15분으로 제한합니다. 관리자 쿠키가 붙은 쓰기에는 허용 Origin도 필수입니다.

가입·로그인 POST는 Origin이 정확히 허용 목록에 있어야 합니다. 누락·`null`·불일치 Origin은 `403 ACCESS_DENIED`이며 `Referer`로 대체하지 않습니다. 클라이언트 IP는 기본적으로 직접 연결 주소를 사용하고, 명시한 프록시에서 온 요청만 `X-Forwarded-For`의 신뢰 체인을 해석합니다. 프록시는 외부에서 받은 전달 헤더를 제거하거나 덮어써야 합니다. 가입은 IP 10회/시간·이메일 비교키 5회/시간, 로그인은 IP 100회/15분·이메일 비교키 실패 20회/15분을 PostgreSQL의 이동 창 기록으로 제한합니다. 허용 Origin의 요청은 본문 파싱 전에 IP 시도를 기록하므로 잘못된 JSON·이메일 형식도 IP 제한에 포함됩니다. 유효한 이메일의 가입 시도는 이후 이메일 비교키에도 기록합니다. 거절된 요청은 `429 RATE_LIMITED`와 초 단위 `Retry-After`를 받습니다. 로그인 성공은 해당 이메일 실패 카운터를 초기화합니다. 기록은 1시간 후 정리됩니다.

## 관리자 계정 프로비저닝

관리자 계정은 migration이나 웹 API로 생성하지 않는다. DB 연결과 운영 CSRF 키 설정을 준비한 뒤,
웹 서버를 열지 않는 `admin-provision` 프로필을 패키징된 애플리케이션으로 실행한다.

```sh
./api/gradlew -p api bootJar
java -jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar \
  --spring.main.web-application-type=none \
  --spring.profiles.active=admin-provision \
  --zoop.admin.provision.email=admin@example.com \
  --zoop.admin.provision.display-name='운영 관리자'
```

비밀번호와 확인값은 터미널에서 화면에 표시되지 않게 입력한다. 비밀번호를 명령행 인자, 환경변수,
셸 기록 또는 `.env` 파일로 전달하는 방식은 지원하지 않는다. 대화형 터미널이 아니거나 두 입력이
다르면 계정을 만들지 않는다. 이메일이 이미 등록된 경우에도 덮어쓰지 않고 실패하며, 성공과 중복
거절은 `audit_logs`에 남는다. 생성되는 계정은 `role=admin`, `status=active`이고 관리자 API의 모든
작업 권한을 갖는다. 차단·재활성화와 비밀번호 교체는 이 생성 명령의 범위가 아니다.

## 빌드

```sh
./api/gradlew -p api --version
./api/gradlew -p api clean build
./api/gradlew -p api test
```

DB 환경변수가 없으면 단위·웹 계층 테스트만 실행되고 PostgreSQL 통합 테스트는 건너뜁니다. `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`를 설정한 뒤 `./api/gradlew -p api authIntegrationTest`를 실행하면 가입·로그인·세션·제한 경계 통합 테스트를 명시적으로 실행합니다. DB 설정이 없으면 이 전용 작업은 실패합니다. CI도 PostgreSQL 서비스에서 이 작업을 실행합니다. 새 DB 경로는 별도 빈 데이터베이스를 만들고 같은 환경변수로 전용 작업을 실행해 Flyway 전체 적용을 검증합니다. 기존 DB 경로는 기존 로컬 DB URL로 다시 실행합니다. 실행 JAR은 `api/build/libs/`에 생성됩니다. 루트에서는 아래 이름을 씁니다(`prototype/bff`의 `bff-*`와 구분됩니다).

```sh
make api-test                        # ./api/gradlew -p api test
make api-build                       # ./api/gradlew -p api assemble
make service-install api-ai-smoke    # 실제 Java -> ai/service -> zoop-ai replay gate (./gradlew aiContractTest)
make pipeline-install service-install api-ai-pipeline-smoke   # 실제 Java -> ai/service -> zoop-ai-extract/-relation 종단 gate (./gradlew aiPipelineContractTest)
make pipeline-install api-build api-graph-handoff-import-smoke   # 실제 CLI -> jar -> PostgreSQL 수입·공개 근거 HTTP 검증 (DB_URL·DB_USERNAME·DB_PASSWORD 필요)
```

`api-graph-handoff-import-smoke`는 합성 데이터만 쓰고 유료 모델·외부 호출은 하지 않습니다. **수입 명령은 활성화하지 않으며, 공개 읽기 검증을 위한 시험 준비 코드만 격리 DB의 합성 버전을 (근거 읽기 단계 1건, verdict 세계 그래프 읽기 1건) 두 번 활성화합니다.** 결과의 `importActivationsWritten`과 `harnessActivations`를 구분하세요. `DB_URL`(loopback)·`DB_USERNAME`·`DB_PASSWORD`로 **전용 빈 일회용 데이터베이스**를 지정해야 하며(기본값 없음, 문서·그래프 행이 이미 있으면 거절하고 정리하지 않음), 선택적으로 `GRAPH_IMPORT_PSQL_CONTAINER`(docker exec psql), `GRAPH_IMPORT_DB_USER`, `GRAPH_IMPORT_DB_NAME`을 지정합니다. `pipeline-install`·`api-build`는 자동 실행되지 않으며 없으면 실패합니다. 형식 3의 이슈·언급·구조 근거, 다문서의 동일 로컬 mentionId 구분과 멱등 재수입, 기존 fixture 읽기를 확인하고, 생산자가 만든 합성 verdict 세계(bundle `-4`)를 import해 보류·거절된 `eventTime`·`period`가 snapshot에서 `null`이고 receipt에는 원본 mention 값·verdict·정확한 근거가 남음을 확인합니다. 기본으로 공개 근거 읽기와 현재 권한·과거 시점·잘못된 registry·receipt 변조·원문 비공개 시나리오, 그리고 verdict 세계의 공개 그래프 읽기(보류·거절된 값이 어떤 공개 본문에도 없음)도 검증합니다(`--no-with-evidence-read`를 지정하면 이 단계들은 실행하지 않음). CI `api` 잡은 별도 빈 `zoop_graph_import_smoke` DB를 사용하며 기존 `companyIntegrationTest`의 공유 DB는 건드리지 않습니다.

`aiContractTest`와 `aiPipelineContractTest`는 기본 `test`에서 제외되며 각각 `make api-ai-smoke`, `api/scripts/ai_pipeline_gate.py`(`make api-ai-pipeline-smoke`)가 서비스를 띄워 매니페스트를 넘길 때만 통과합니다. 매니페스트가 없으면 skip이 아니라 실패합니다. 후자는 새 합성 운영자 세계와 설치된 pipeline이 필요합니다(`make pipeline-install service-install`; 없으면 실패).

## Swagger / OpenAPI

Swagger UI와 생성 OpenAPI 문서는 기본적으로 활성화되어 있습니다. 비활성화할 환경에서는 `ZOOP_SWAGGER_ENABLED=false`를 설정하세요. API가 8080 포트에서 실행 중이면 `http://localhost:8080/swagger-ui.html`에서 UI를, `http://localhost:8080/v3/api-docs`에서 생성된 OpenAPI JSON을 볼 수 있습니다. `SERVER_PORT`를 바꾸면 두 URL과 `ZOOP_AUTH_ALLOWED_ORIGINS`의 API Origin도 같은 포트로 바꾸세요. 운영에서는 애플리케이션 또는 프록시에서 두 경로의 공개 범위를 제한하거나 환경변수로 비활성화하세요.

`/v3/api-docs`는 **현재 Spring 컨트롤러에서 생성한 문서**입니다. 목표 계약의 정본은 [`docs/api/openapi.yaml`](../docs/api/openapi.yaml)이며, 아직 구현되지 않은 목표 경로는 생성 문서에 나타나지 않습니다. 다음 순서는 API에서 제공하는 Swagger UI를 같은 `localhost:8080` 주소로 열었을 때를 기준으로 합니다. 프론트 `localhost:3000`에서의 API 호출은 별도 Origin이므로 위 공통 CORS 설정을 사용합니다.

### 인증 API 시험 순서

1. `GET /api/v1/auth/terms`를 실행해 유효한 필수 약관의 `id`와 `version`을 확인합니다. 승인 본문이 없는 항목은 가입에 사용할 수 없습니다.
2. `POST /api/v1/auth/signup`에 새 이메일, 8~32 Unicode code point의 비밀번호와 필수 약관별 실제 동의를 보냅니다. 예시는 아래와 같으며 `version`은 바로 조회한 응답값으로 교체합니다. 이미 만든 계정이면 `POST /api/v1/auth/login`에 같은 이메일·비밀번호를 보내세요. 가입 성공은 201, 로그인 성공은 200과 `Set-Cookie: zoop_session=...`을 반환합니다.
3. `GET /api/v1/auth/session`을 실행해 `authenticated: true`, `kind: "member"`와 `csrfToken`을 확인합니다. `kind: "anonymous"`이면 브라우저 개발자 도구에서 쿠키 저장 여부와 요청에 쿠키가 실렸는지 확인합니다. 로그인 성공 응답만으로 후속 요청의 쿠키 전송을 확인한 것은 아닙니다.
4. 로그아웃은 아래 절차로 실행한 뒤 세션을 다시 조회해 `kind: "anonymous"`를 확인합니다. 활성 회원 쿠키 없이 받은 로그아웃 204는 회원 세션 폐기의 증거가 아닙니다.

```json
{
  "email": "swagger-local@example.test",
  "password": "<LOCAL_DEMO_PASSWORD>",
  "displayName": "Swagger Tester",
  "agreements": [
    {"id": "service", "version": "조회한 service 버전", "accepted": true},
    {"id": "privacy", "version": "조회한 privacy 버전", "accepted": true}
  ]
}
```

`Authorize`에 보이는 `zoop_session_cookie`와 `X-CSRF-Token`은 현재 **스키마 정의만 있으며 작업에 적용되지 않았습니다.** 여기에 값을 넣어도 Swagger의 로그아웃 요청에 CSRF 헤더가 붙지 않습니다. `zoop_session`은 HttpOnly 쿠키라 Swagger UI에서 직접 지정할 수 없고, 같은 호스트에서 로그인한 브라우저가 API 요청에 자동으로 보냅니다. 유효한 쿠키가 붙은 쓰기 요청은 허용 Origin과 그 세션의 `X-CSRF-Token`을 함께 요구합니다.

현재 생성된 Swagger의 로그아웃 작업에는 CSRF 헤더 입력란이 없습니다. 같은 Swagger 탭의 개발자 도구 Console에서 `GET /api/v1/auth/session` 응답의 `csrfToken`을 넣고 아래 요청을 보내세요. 브라우저가 `Origin`과 세션 쿠키를 전송하므로 `Origin` 또는 `Cookie` 헤더를 직접 입력하지 않습니다.

```js
const response = await fetch('/api/v1/auth/logout', {
  method: 'POST',
  headers: { 'X-CSRF-Token': '<세션 응답의 csrfToken>' },
  credentials: 'same-origin',
});
console.log(response.status); // 활성 회원 세션이 정상 폐기되면 204
```

개발자 도구 Network에서 로그아웃 요청의 `Origin`, `Cookie`, `X-CSRF-Token`과 응답의 쿠키 `Max-Age=0`을 확인한 뒤, Swagger에서 `GET /api/v1/auth/session`을 다시 실행합니다. 활성 세션에서 토큰이 누락되거나 틀리거나 Origin이 허용되지 않으면 403 `ACCESS_DENIED`가 예상됩니다. 목표 계약의 로그아웃에는 조건부 `X-CSRF-Token` 선택 헤더가 정의돼 있지만, 현재 생성 문서에 입력란을 추가하는 작업은 별도입니다.

## 공통 오류 처리

`CustomException`에 명세의 `ErrorCode`를 전달하면 `GlobalExceptionHandler`가 `{ "error": { "code", "message", "requestId", "retryable" } }` 형식으로 반환합니다. 인증에는 `INVALID_CREDENTIALS`, `MEMBER_BLOCKED`, `ACCESS_DENIED`, `EMAIL_TAKEN`, `TERMS_REQUIRED`, `RATE_LIMITED`가 구현돼 있습니다. 제한 초과 응답에는 `Retry-After`도 포함됩니다. 성공 응답은 공통 래퍼로 감싸지 않습니다.

모든 요청의 `X-Request-ID`를 응답 헤더에 반환하며, 생략하면 서버가 새 ID를 생성합니다. 오류 본문의 `requestId`는 해당 응답 헤더와 같습니다. 요청 ID를 멱등성 키로 사용하지 마세요. Origin·CSRF 인터셉터의 오류도 같은 형식을 따릅니다.

## 브리핑: DB조회와 로컬 생성·재생

`com.zoop.briefing`은 PostgreSQL에 고정한 발행본을 공개 HTTP로 복원하고, `web/src/pages/briefing/BriefingPage.tsx`가 이를 조회합니다. 조회할 때 AI·검색·최신 시세를 호출하지 않습니다. 생성 시작 기준은 **09:20·17:30 KST**이며, 회차 기준 구현이 운영 scheduler·AWS 자동 실행을 뜻하지는 않습니다.

| 공개 GET | 현재 구현 |
|---|---|
| `/api/v1/briefings?date=YYYY-MM-DD&edition=morning` | 저장된 상태·핵심 이슈·시장 요약·3지표·기업 전망·선택적 짧은 읽기/회차 시세·continuity·정정 복원. 퇴근은 `edition=evening` |
| `/api/v1/briefings/rounds?limit=20` | 공개/제공 중단 회차의 cursor 이력 |
| `/api/v1/briefings/{id}/items/{eventId}` | 해당 회차의 주장·선정 이유·고정 직접 인용·주변 본문·원문 URL/버전 |
| `/api/v1/briefings/{id}/graph` | 발행 당시 스냅샷 또는 명시적으로 등록한 재구성본의 기준. 없으면 unavailable이며 최신 그래프로 대체하지 않음 |
| `/api/v1/briefings/{id}/recap` | 새 핵심이 없는 정상 발행 회차의 고정된 과거 발행본 복기. 현재 권한·정정/중단 상태를 다시 확인 |

Swagger `/v3/api-docs`의 위 5개 operation과 목표 정본 [`docs/api/openapi.yaml`](../docs/api/openapi.yaml)을 구분합니다. 개인화·관리자 정정/중단 등 목표 경로 전체가 구현된 것은 아닙니다. 권한 파일·출처·저장 해시를 확인할 수 없으면 503으로 닫고, 빈 회차·수집 부족·검증 실패를 같은 상태로 바꾸지 않습니다.

| 시작할 작업 | 안내 |
|---|---|
| 키 없이 저장된 10/21 퇴근·10/22 출퇴근 3회차를 API·화면에서 보기 | [팀원용 재생 실행](docs/BRIEFING_TEAM_DEMO.md): 저장 결과 포함, 임시 Docker DB, AI·시세 재호출 없음 |
| DB·권한·공개 HTTP·합성 자료로 프론트 연결 | [BRIEFING_READ](docs/BRIEFING_READ.md) |
| 실제 수집부터 한 회차 생성·검증·DB·지도 실행 | [BRIEFING_LOCAL_ROUND](docs/BRIEFING_LOCAL_ROUND.md) |
| 지정 출퇴근 회차를 시간순으로 재생 | [BRIEFING_ROUND_SERIES](docs/BRIEFING_ROUND_SERIES.md) |
| 완료 AI 결과 재사용·시세 자동 수집·실패 단계부터 DB/지도/화면 재개 | [회차 자동 연결과 재개](docs/BRIEFING_ROUND_SERIES.md#완료-ai-결과부터-시세db지도화면까지-자동-연결) |
| 중요도·재보도/기업 연결 및 짧은 근거의 실제 의미 검증 | [BRIEFING_EDITORIAL_GUARDS](docs/BRIEFING_EDITORIAL_GUARDS.md), [BRIEFING_CORE_EVIDENCE](docs/BRIEFING_CORE_EVIDENCE.md) |
| 핵심 → 참고 소식 → 이전 발행본 복기·수집 부족 구분 | [BRIEFING_CONTINUITY](docs/BRIEFING_CONTINUITY.md), [BRIEFING_EMPTY_RECAP](docs/BRIEFING_EMPTY_RECAP.md) |
| 시장 맥락·이전 판단·기업별 조건부 전망 | [BRIEFING_MARKET_CONTEXT](docs/BRIEFING_MARKET_CONTEXT.md), [BRIEFING_COMPANY_OUTLOOK](docs/BRIEFING_COMPANY_OUTLOOK.md) |
| 모바일 짧은 읽기·회차 시세 연결(모델 재호출 없음) | [BRIEFING_SHORT_READING_AND_PRICES](docs/BRIEFING_SHORT_READING_AND_PRICES.md) |
| 회차 지도·과거 재구성/원래 저장본 구분 | [BRIEFING_ROUND_GRAPHS](docs/BRIEFING_ROUND_GRAPHS.md) |

일반 조회는 API 로컬 실행 설정과 실제 DB·현재 원천 권한이 필요합니다. 개인 개발 replay는 추가로 `ZOOP_BRIEFING_REPLAY_READ_ENABLED=true`, 고정 manifest·별도 artifact/grants를 사용합니다. 예전 결과를 새 정책으로 재검증할 때는 별도 DB에서 `ZOOP_BRIEFING_REPLAY_CONTINUITY_ENABLED=true`, `ZOOP_BRIEFING_REPLAY_CORE_SEMANTIC_ENABLED=true`를 명시합니다. 두 기본값은 false이며 기존 저장본을 갱신하는 스위치가 아닙니다. 실행기 전체 승인 호출 상한·결과 불명 재전송 금지·원본/이전 DB 보존은 그대로 적용합니다.

## AI 분석 transport

`zoop.ai.plan-admission-client`·S2/S3 전송 클라이언트와 별도로 `zoop.analysis.analyze-plan`은 관리자 계획 분석 큐를 제공합니다. 모두 기본 비활성이며 클라이언트나 큐 설정만으로 원천 사용·모델 비용·HOLD 승인·공개 권한이 생기지 않습니다. `POST /api/v1/admin/jobs`의 analyze_plan만 실제 계획 등록·PostgreSQL 단위 원장·worker에 연결됩니다. 성공은 고정 S2/S3 결과의 내용 없는 처리 인계(publicChanged=false)이며 수집·검수 동기화·발행을 하지 않습니다. 기존 ingest/revalidate/project 요청 형태와 이력은 유지하지만 새 접수와 retry는 실행기 미연결로 거절합니다. 설정 환경 변수, 재시작·취소·continuation 의미, 실제 합성 `make api-analyze-plan-smoke ANALYZE_PLAN_SMOKE_OUTPUT=/external/fresh-dir` 명령은 [AI 연동의 관리자 계획 분석 큐](docs/AI_INTEGRATION.md#관리자-계획-분석-큐)를 참고하세요.

## 문서 등록 import

`com.zoop.document`·`com.zoop.artifact`는 FS056의 문서 쪽 저장입니다. S2-1 export의 정제 텍스트를 `artifacts`·`articles`·`article_versions`와 로컬 파일로 등록하는 **operator 전용 비웹 실행**(`--spring.main.web-application-type=none`)이며 HTTP 경로가 없고 평소 기동은 달라지지 않습니다(`V20261014120000`이 세 테이블을 만듭니다). export는 설치된 `zoop-ai-ingest export`(`ZOOP_DOCUMENT_IMPORT_OBSERVATION_SOURCE=cli`, 기본) 또는 ai/service의 관측 export HTTP(`http`, 그래프 import와 같은 `ZOOP_AI_OBSERVATION_EXPORT_CLIENT_*`; AI CLI가 없는 ECS task에서 쓰는 경로)에서 받으며, 두 경로 모두 같은 파서가 같은 규칙으로 검증합니다. 분석·AI 결과 import·그래프·공개 반영은 이 실행이 하지 않습니다(분석은 아래 별도 실행). 입력 스키마, 결과 파일, 실패 코드, 접근 규칙과 실제 DB smoke(`api/scripts/document_import_smoke.py`)는 [문서 import](docs/DOCUMENT_IMPORT.md)에 있습니다.

## 문서 bindings export

`com.zoop.document.bindings`는 #55(WBS 6.5.4) 그래프 정기 회차의 앱 쪽 조각으로, AI `zoop-ai-handoff freeze`가 요구하는 운영자 파일 중 앱만 만들 수 있는 `zoop-app-document-bindings-1`(`--bindings`)을 등록된 기사 버전에서 생성하는 **operator 전용 비웹 실행**입니다. `articles.id`·`article_versions.version`·text artifact의 `sha256`을 그대로 투영한 결정적 canonical JSON이며, DB를 쓰지 않고 lock을 잡지 않습니다. AI Task로의 전달 경로와 회차 스케줄러 연결은 이 실행 밖입니다. 범위·출력·결과·실패 코드는 [문서 bindings](docs/DOCUMENT_BINDINGS.md)에 있습니다.

## 문서 분석

`com.zoop.document.analysis`는 등록된 문서 버전 하나를 S1 AI 서비스로 요약·기업 판정하고 검증된 결과를 `document_analyses`·`evidence`·`ai_executions`와 artifact 파일에 저장하는 **operator 전용 비웹 실행**입니다(`V20261014130000`). `prepare`는 AI 서비스를 부르지 않고 새 AI jobId와 불변 `ai_submit`을 커밋하며, `advance`는 status를 먼저 읽고(submit·recover 직전에는 현재 grant·article을 다시 확인), 결과를 입력 결속·digest 재계산·검증자가 본 claim 대조·코드 포인트 인용 검사·현재 grant 재평가를 거쳐 한 transaction으로 정산하며, 그 transaction이 article·행 잠금을 얻은 뒤 grant를 한 번 더 평가합니다. 이 실행에는 HTTP 경로·`analysis_jobs`·live 실행이 없습니다(저장된 요약의 인용을 읽는 공개 경로는 아래 `getEvidence` 한 건뿐). 입력 스키마, 결과 파일, 실패 코드, 권리·크래시 규칙과 smoke(`api/scripts/document_analysis_smoke.py`)는 [문서 분석](docs/DOCUMENT_ANALYSIS.md)에 있습니다.

`GET /api/v1/evidence/{id}`(`getEvidence`, 공개 `security: []`)는 저장된 S1 요약의 본문 인용 한 건을 읽는 **부분 구현**입니다(`com.zoop.document.evidence`). 모델·AI 서비스를 호출하지 않고 DB·파일을 쓰지 않으며 요청마다 현재 문서 상태와 현재 grant registry로 다시 판정합니다. 그래프가 없어 `eventIds`는 실패 구역·`graphVersion=null`·`sentiment=null`인 200 부분 응답이고 고정 `round`·`graphVersion`·`asOf`는 409입니다. 규칙·오류·캐시 적중 증명·한계는 [문서 분석 § 근거 읽기](docs/DOCUMENT_ANALYSIS.md#근거-읽기-getevidence-부분-구현)에 있고 `listCompanyDocuments`·GraphDB·승인은 아직 없습니다.

## 그래프 handoff 스테이징 import

`com.zoop.graph.importer`는 AI `zoop-ai-handoff`가 동결한 handoff 하나를 **비활성** 그래프 버전으로 올리는 **operator 전용 비웹 실행**입니다(`--spring.main.web-application-type=none`, `ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED=true`). import 자체에는 HTTP 경로가 없고 평소 기동은 달라지지 않으며, 문서 import·분석(같은 artifact 잠금)이나 활성화하는 `fixture` 소스와 한 프로세스에서 켜면 기동이 거절됩니다. 실행은 `graph_activations`를 쓰지 않고 `graph_versions.active`와 article의 `current_version`을 바꾸지 않으므로 아직 활성화하지 않은 버전을 공개 API로 읽을 수 없습니다(명시 `graphVersion`은 409 `VERSION_UNAVAILABLE`, 기본·asOf 읽기는 기존 활성 포인터 그대로). 별도의 관리자 `POST /api/v1/admin/graph/versions/{versionId}/activate`는 현재 권리·버전별 공개 제외·읽기 준비를 검사한 뒤 활성화하며, 공개 제외 저장소를 읽을 수 없으면 503 `SOURCE_UNAVAILABLE`로 거절합니다. import 결과의 `nextActivation=unsupported`는 import의 기존 스테이징 계약이며 관리자 경로의 부재를 뜻하지 않습니다.

요청(`zoop-graph-handoff-import-1`, 닫힌 스키마)은 `handoffId`, 운영자가 고정한 `expectedManifestDigest`·`expectedBundleDigest`(둘 다 필수), `operator`입니다(`created_by=operator:<operator>`, AI 검수 revision이 아닙니다). 실행은 ① 설치된 `zoop-ai-handoff export`의 **현재** 결과(저장 파일이 아님)를 받아 canonical hash 두 개를 직접 다시 계산해 핀과 대조하고, 생산자 `validate_bundle`의 Java 이식으로 bundle 전체(닫힌 스키마·참조 폐쇄·`ev-`/`edge-` 공식·개수·content digest)와 manifest 일치를 검증하며, ② bundle이 기록한 **모든 관측**마다 `zoop-ai-ingest export --require-store`를 새로 실행해(같은 registry·같은 S2-1 원장, `store` 권리 포함) 권리·grant·관측 시각·제목·URL·게시 시각을 대조하고, ③ 한 transaction에서 앱 쪽(article version의 제목·URL·게시 시각 정밀도, 앱 텍스트와 export 텍스트의 byte 일치, 회사 ID·이름)을 검증해 불변 스냅샷·receipt 파일, `artifacts`(`graph_snapshot`·`verification_receipt`), `evidence`, `graph_versions`(inactive, `review_revision` 0, `published_at` 없음)를 등록하고 **commit 직전에 ①②를 다시 실행**합니다(권리가 바뀌면 rollback). id는 `gv-`+SHA-256(handoffId)로 결정되며 같은 핀의 재실행은 `unchanged`, 같은 id의 다른 핀은 `version_conflict`입니다.

스냅샷은 앱의 현재 읽기 형식인 **`snapshotFormat 3`**(`PublicGraphSnapshot`)이며 읽기 투영일 뿐입니다. 이슈에는 생산자의 `period`·이슈 단위 `assertionStatus`(값 그대로, 없으면 null)·`mentions`(mention id와 article id·version)·`representativeMentionId`를, 구조 근거(basis)에는 `basisId`(생산자 `relationKey`)·사업 관계 유형(`SUPPLIES`)·`countries`·`articles`(출처 기사 버전 전부, 없을 수도 있음)·검증 시각·`validFrom`/`validUntil`을 담습니다. `validUntil`은 **마지막 유효일(그날 포함)**이고 `null`은 영구 유효가 아니라 미상이며, 원문 날짜에 자정이나 하루를 더하지 않고 일 단위가 아닌 값은 `temporal_unsupported`로 거절합니다. 공개 조회는 검증 시각이 asOf 이하인 구조 근거를 보이고, 끝난 근거도 지우지 않고 상태(`ended` 등, asOf 또는 요청 시각의 Asia/Seoul 날짜 비교)로 구분합니다. **mention 참조는 전체 source event 목록이 아닙니다.** source event는 그 문서 버전(documentId·documentVersion·rawVersion·관측 위치)이 이슈 자신의 근거가 인용하는 기사 버전일 때만 mention이 되며, 같은 기사 버전·같은 생산자 mentionId를 가진 여러 event(S2 후보와 S2 스냅샷이 함께 담는 경우)는 한 mention입니다. 생산자의 `mentionId`는 문서 버전 안에서만 유일해 서로 다른 문서가 같은 값을 합법적으로 쓰므로, 스냅샷의 mention id는 앱이 `mention-`+SHA-256(canonical JSON `{articleId, articleVersion, sourceMentionId}`, 키는 ASCII 정렬)로 정합니다. 같은 값이 다른 문서에 있어도 두 mention이 따로 남고 같은 입력은 언제나 같은 id를 냅니다. 대표 event도 자신이 속한 기사 버전으로 풀어 같은 식으로 바꾸며 그 mention이 스냅샷에 없으면 `representativeMentionId`는 null입니다. 한 문서 신원이 둘 이상의 bundle 기사와 맞는 경우만 추측하지 않고 `mention_article_ambiguous`로 import 전체를 거절합니다. 스냅샷에 둘 수 없는 source event, 결정, source ref 같은 생산자 필드와 생산자의 원래 mention id는 버리지 않고 `verification_receipt`(원본 manifest·bundle 전체와 앱이 검증한 항목)에 그대로 남습니다. 증거 id는 AI가 제안한 `ev-`+digest 공식을 앱 규칙으로 채택하고(충돌은 `evidence_collision`), 인용은 앱 텍스트의 **코드 포인트** 구간이며 그 UTF-8 SHA-256이 bundle의 `quoteSha256`과 같아야 합니다. `quote_verified`는 이 **인용 무결성**만 뜻하며(의미 검증 아님) 검증 artifact는 receipt입니다. 정밀도를 지키며 쓸 수 없는 시각은 만들어 내지 않고 `temporal_unsupported`로 거절합니다. `getEvidence`는 graph 근거를 읽지 않고(미등록 취급) 공개 제외 오버레이도 이 실행의 범위가 아닙니다. 스테이징된 버전이 있는 DB에서 `fixture` 소스는 기동을 거절합니다.

> **2026-10-20:** 위 "`getEvidence`는 graph 근거를 읽지 않고" 문장은 **이 import 실행**에 대한 것입니다. 공개 `GET /api/v1/evidence/{id}`는 이제 스테이징된 graph 본문 근거를 고정된 공개 snapshot·선택된 버전의 receipt·S2-1 source registry(`ZOOP_DOCUMENT_READ_INGESTION_SOURCES`)로 읽습니다([규칙](docs/GRAPH_READ_HANDOFF.md#2026-10-20-getevidence의-graph-본문-근거-경로-로컬-작업-트리-미게시)). import는 여전히 활성화하지 않으며, `api-graph-handoff-import-smoke`는 기본으로 evidence 읽기 단계를 포함합니다(끄려면 스크립트에 `--no-with-evidence-read`). 이 단계는 격리 DB에서 **시험 harness 전용** psql 활성화 1건을 수행하고, 이어서 생산자가 만든 합성 verdict 세계(bundle `-4`의 운영자 `eventTime`·`period` verdict)의 스테이징 버전을 공개 그래프·근거 읽기로 확인하려고 같은 방식의 활성화 1건을 더 수행합니다. 마지막 줄이 `importActivationsWritten: 0`과 `harnessActivations: 2`를 따로 보고합니다.

동시성·재시도 규칙: import의 transaction은 첫 문장으로 회사 카탈로그 테이블 잠금(`LOCK TABLE companies IN SHARE MODE`)을 잡고 commit까지 유지하므로, 한 번 읽은 회사 이름과 "이슈 ID가 카탈로그 회사 ID가 아님" 확인이 commit 시점에도 참입니다. 카탈로그 import도 같은 순서(테이블 잠금 다음 행 잠금)로 잡아 서로를 기다리며 교착하지 않고, 이 대기에는 자체 시간 제한이 없어 상대 transaction이 끝나거나 DB 오류(`database_unavailable`)로 끝납니다. import는 transaction 안에서 사용하는 article 행을 `FOR UPDATE`로 잠그고(`access_status`가 `private`·`deleted`이면 거절) commit 직전 재검사 뒤 같은 잠금 아래에서 상태를 다시 확인하므로, 동시에 들어온 공개 철회는 import의 commit을 기다린 뒤에 적용됩니다. 이미 있는 증거 행은 내용(article·version·텍스트 artifact·인용·구간·locator)과 의미(`input_kind=body`, `offset_unit=unicode_code_point`, 요약 연결 없음, `quote_verified=TRUE`이고 검증 artifact가 graph `verification_receipt`)가 모두 같을 때만 재사용하며 그 밖의 같은 id는 `evidence_collision`입니다(행을 UPDATE로 고치지 않음; 앞선 handoff의 receipt를 검증 artifact로 가진 행은 정상 재사용). 스냅샷의 회사 노드는 bundle이 말하는 `companyId`·`label`만 담고 `brandColor`·`logoUrl`은 선택 외형이므로 카탈로그에서 복사하지도 만들어 내지도 않습니다. 스냅샷 바이트는 검증된 bundle만으로 정해지므로 commit 결과가 불명확했던 시도 뒤의 같은 핀 재시도는 남은 파일을 그대로 채택합니다.

공개 규칙([규칙 문서](../docs/development/issue-133-publication-rules.md) 2-1): 카탈로그 잠금 바로 다음에 켜진 규칙과 `rule_revision`·`review_revision`을 **한 SQL 문장**으로 읽고, 판정 함수(`PublicationRuleEvaluator`)로 거른 snapshot을 저장합니다. 버전 행에는 두 revision과 거른 뒤의 이슈·관계·기사 수를, `graph_version_rules`에는 적용한 규칙을 남깁니다. receipt와 `evidence` 행은 bundle 전체를 그대로 둡니다. 수입은 정기 회차마다 돌므로 publication lock을 잡지 않으며, 읽은 뒤 커밋된 규칙 전환은 다음 회차 버전에 반영됩니다. 같은 핀을 다시 수입하면 지금 켜진 규칙이 아니라 그 버전의 적용 규칙으로 다시 계산해 `unchanged`를 판단합니다. 켜진 규칙(또는 버전의 적용 규칙)의 정의를 읽을 수 없으면 `rule_definition_invalid`로 아무것도 쓰지 않고 실패합니다. migration이 등록한 `single-source@1`·`speculative-issue@1`은 둘 다 꺼진 상태입니다. 결과 파일의 `counts`는 지금처럼 bundle의 수이고, `publicationRules`가 규칙이 한 일을 따로 알립니다: `ruleRevision`·`reviewRevision`, 적용한 규칙(`applied`), 저장된 snapshot의 수(`stored`), 연결 정리까지 포함해 숨긴 이슈·관계 수(`hidden`), 규칙마다 그 조건에 직접 걸린 수(`byRule`)입니다. id와 내용은 넣지 않습니다. `unchanged`이면 그 버전을 처음 수입할 때의 값이고(지금 켜진 규칙이 아님), 규칙 이전에 수입된 버전은 `ruleRevision`이 `null`입니다.

구성(#55 정기 회차, `V20261028170000`): 수입은 버전마다 **구성 행**(`graph_version_sources`: ordinal, handoffId, receipt artifact, 묶음 projection artifact)을 함께 쓰고, 규칙을 적용하기 **전**의 묶음 projection을 남깁니다. 켜진 규칙이 아무것도 숨기지 않았으면 저장한 snapshot이 곧 그 projection이므로 구성 행은 snapshot artifact(`artifact-<gv>`)를 가리키고 파일을 두 번 쓰지 않습니다. 무언가 숨겼을 때만 `graph_bundle_snapshot` artifact(`artifact-bundle-<gv>`, `graph_bundle/<gv>.json`)를 따로 씁니다. 지금은 버전 하나가 묶음 하나(ordinal 0)이며 공개 읽기·활성화·제외는 달라지지 않습니다. 이 행과 projection은 뒤 회차 묶음을 한 버전으로 조립할 때 "어느 묶음으로 이루어졌는지"와 "그날의 규칙으로 다시 거를 원본"이 됩니다. 구성 행은 버전과 함께만 지워지고(CASCADE, 버전 행이 사라진 뒤의 삭제만 통과) 고칠 수 없습니다. migration은 그때까지 수입된 버전마다 행 하나를 `source_label`에서 채우되 projection은 `NULL`로 둡니다(그 전에는 남기지 않았음). 같은 핀의 재수입은 구성이 그 묶음 하나인지와 projection 바이트가 같은지도 확인하며, projection이 없는(backfill) 버전은 `unchanged`에 `bundleSnapshot: null`로 답합니다. 결과 파일에는 `bundleSnapshot`과 `composition{sources, newSource}`(`newSource`는 `staged`일 때만, `unchanged`면 `null`)가 추가됐습니다([인계 문서](docs/GRAPH_READ_HANDOFF.md#2026-10-28-버전의-구성-행과-묶음-projection-55-정기-회차-앱-pr-1--v20261028170000)).

설정은 `application.yml`의 `zoop.graph-handoff-import.*`입니다. 요청·결과 파일, CLI, handoff 원장, canonical·decisions·bindings, artifact root를 지정하고, 원천은 단일 경로 묶음 또는 아래 SHA-256으로 고정한 context inventory로 지정합니다. 값이 틀리면 설정 이름만 알리고 기동을 거절합니다.

**handoff 읽기 경로 (2026-10-29).** `ZOOP_GRAPH_HANDOFF_IMPORT_HANDOFF_SOURCE`가 `cli`(기본)면 위 ①을 설치된 `zoop-ai-handoff export`로, `http`면 ai/service의 읽기 전용 handoff HTTP `GET /internal/v1/graph-handoffs/{handoffId}/bundle`(scope `handoff.read`, [계약](docs/GRAPH_READ_HANDOFF.md#2026-10-29-수입기의-handoff-읽기-http-전환))로 수행합니다. HTTP에서도 앱은 받은 manifest·bundle의 canonical hash 두 개를 직접 다시 계산해 요청의 핀과 대조하고, bundle 전체를 같은 Java 검증기로 검증하며, 서비스가 보고한 `verification`(digest·바이트·개수·provenance·source 수)이 재계산과 같은지 확인합니다. commit 직전 재확인은 내용 없는 상태 route `GET /internal/v1/graph-handoffs/{handoffId}`를 호출해 서비스가 지금 보고하는 두 digest가 첫 읽기와 같은지(핀·withheld 규칙은 같음) 보고, 관측 사실은 이미 검증한 bundle로 다시 모읍니다. 서비스의 `withheld`는 `handoff_withheld`(사유 코드 그대로), 503은 `handoff_export_unavailable`, 그 밖의 오류 envelope(403 `handoff_not_allowed`·404·409·422·500)은 `handoff_refused`(코드 그대로)입니다. receipt의 `producer`에는 CLI의 `receipt`·`attempts` 대신 서비스 답(`read`: 전달 상태·검증 값. 내용과 요청마다 바뀌는 관측 시각은 제외해 같은 핀의 재수입이 `unchanged`로 판정되게 함)이 남고, 그 밖의 receipt 필드와 스냅샷 바이트는 CLI 경로와 같습니다. `http`일 때 handoff CLI·세 원장 디렉터리·운영자 파일 세 개는 이 프로세스가 읽지 않으므로 비워 두어야 하고, 빈 값은 `cli`이고 `cli`는 켜진 읽기 클라이언트를 무시하며(같은 환경의 웹 애플리케이션 회차 bridge가 그것을 씀), 관측별 `zoop-ai-ingest export --require-store`는 그대로 실행합니다(관측 export HTTP는 AI 쪽 #387 ① 뒤). ECS처럼 AI 원장이 앱과 다른 Task에 있을 때 쓰는 경로이며, 어느 경로든 활성화하지 않습니다. 하위 CLI에는 DB 자격이 전달되지 않습니다. 결과 파일(`0600`, 이미 있으면 덮어쓰지 않음)에는 경로·본문·비밀이 없고 실패 시 프로세스는 0이 아닌 코드로 끝납니다. 스테이징된 스냅샷을 읽으려면 `ZOOP_GRAPH_SNAPSHOT_SOURCE=artifact`와 `ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT`(같은 root)를 씁니다. 실제 CLI·PostgreSQL smoke는 `api/scripts/graph_handoff_import_smoke.py`(파이프라인 venv의 Python으로 실행, 사용법은 파일 머리말)이고 PostgreSQL 통합 시험은 `companyIntegrationTest`에 포함됩니다.

### 여러 원장 읽기와 현재 권한

서로 다른 운영에서 만든 native job을 한 manifest로 읽을 때 `ZOOP_GRAPH_HANDOFF_IMPORT_SOURCE_CONTEXTS`와 `ZOOP_GRAPH_HANDOFF_IMPORT_SOURCE_CONTEXTS_SHA256`을 함께 설정합니다(`zoop.graph-handoff-import.source-contexts`, `source-contexts-sha256`). 이때 `ZOOP_RELATION_STATE_DIR`·`ZOOP_EXTRACTION_STATE_DIR`·`ZOOP_INGESTION_STATE_DIR`·`ZOOP_INGESTION_SOURCES`는 비웁니다. `ZOOP_INGESTION_CLI`는 계속 필요합니다. 단일 경로 입력도 지원합니다.

파일은 [pipeline context 계약](../ai/pipeline/README.md#여러-운영-원장의-native-handoff-읽기)의 `zoop-handoff-source-contexts-1`이며 최대 2,000,000바이트입니다. Java와 handoff CLI에 같은 파일·SHA-256을 전달합니다. Java는 선택한 native source pin을 대조하고, 전체 7필드 관측 selector로 해당 ingestion CLI 경로를 골라 실제 `export --require-store`를 다시 실행합니다. 기존 grant·시각·메타데이터·원문·locator·근거 동등성 검사를 그대로 수행하며, 모든 context 원장이 artifact·결과 경로의 금지 영역에 포함됩니다. 경로 inventory의 크기와 관계없이 선택한 manifest의 source job 상한은 전체 20개입니다.

설치·활성화·공개 근거의 `ZOOP_DOCUMENT_READ_INGESTION_SOURCES`는 다음 두 입력 형식을 받습니다.

- 기존 단일 `zoop-ingestion-s2-1` registry.
- 아래 닫힌 authority-set. 각 항목은 `(sourceId, grantId, revision)` 전체를 설치 호스트의 로컬 leaf registry 경로에 연결합니다.

```json
{
  "schemaVersion": "zoop-source-authority-set-1",
  "authorities": [
    {"sourceId": "example-source", "grantId": "grant-old", "revision": "r1", "sources": "/srv/zoop/authority/old.json"},
    {"sourceId": "example-source", "grantId": "grant-new", "revision": "r1", "sources": "/srv/zoop/authority/new.json"}
  ]
}
```

wrapper와 각 leaf는 최대 2,000,000바이트이며 운영자 소유의 일반 파일이어야 합니다. leaf는 기존 엄격한 S2-1 parser로 읽습니다. tuple 중복, 중첩 set, 읽을 수 없는 선택된 leaf는 권한 사용 불가입니다. leaf가 거절한 grant는 다른 leaf로 다시 찾지 않습니다. wrapper는 실행 중 바뀌면 실패하고, leaf 내용은 고정하지 않아 철회·만료·revision·operation 변경이 다음 현재 권한 검사에 반영됩니다. URL host 제한도 선택된 leaf를 따릅니다. 설치 호스트의 set에는 분석 원장 경로가 필요하지 않습니다.

AI와 API는 같은 현재 권한 leaf를 읽어야 합니다. UID/GID `999:999`, 디렉터리 `0700`·파일 `0600`인 canonical control은 API의 UID `100`/GID `101`이 일반 mount로 읽을 수 없으므로, 같은 control을 가리키며 POSIX identity `999:999`를 강제하는 읽기 전용 EFS access point 또는 승인된 동등 읽기 권한을 마련해야 합니다. 이 control mount는 API가 쓰는 `100:101` artifact root와 분리합니다. 선택한 이미지의 실행 계정과 실제 mount 권한은 배포 전에 확인합니다.

HTTP profile의 native archive는 AI task에 두고 API에는 필요한 control만 읽기 전용으로 연결합니다. 닫힌 저장소의 sidecar 보존, 비어 있지 않은 WAL 거절, 경로 이전 시 frozen registry `inputRoot` 보존과 inventory 재고정은 [AI archive 배치 지침](../ai/service/README.md#관측-export와-앱-수입용-읽기-profile)을 따릅니다.

로컬 전체 검증: `ai/pipeline/.venv/bin/python api/scripts/graph_delivery_smoke.py --multicontext --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --result /absolute/new-result.json`. 준비된 JAR·CLI와 캐시된 로컬 PostgreSQL 이미지를 사용하며, 기존 산출물은 덮어쓰지 않습니다.

### 원본 호스트 seal과 Java 전용 artifact 설치

`zoop.graph-delivery`는 **native handoff 버전 또는 앱에서 합성한 누적 publication**의 파일을 같은 PostgreSQL의 불변 `bytea` outbox로 전달합니다. native `seal`은 기존 importer의 CLI 또는 HTTP source로 수입하고 봉인합니다. `seal-publication`은 이미 스테이징한 누적 버전의 receipt와 원본 기여분을 검증한 뒤 봉인합니다. 설치 호스트는 같은 DB/schema, 별도로 배포한 현재 source registry, serving artifact root, 명시적인 버전·목적지·package digest를 사용합니다.

**초기 스테이징부터 설치가 끝날 때까지 operator와 serving 웹 앱 모두 `ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED=false`로 실행해야 합니다.** 이후 실제 활성 버전 ID를 조회하고 관리자 CAS·멱등 활성화 route로 수동 전환합니다. 실제 수입이 0건이어도 fixture가 활성일 수 있습니다. 실제 데이터가 활성인 경우에는 해당 버전을 base로 삼은 누적 publication을 준비합니다.

native 패키지는 기존 `zoop-graph-delivery-package-2` 바이트와 의미를 유지합니다. 정렬된 파일 목록은 공개 snapshot, 원본 receipt, receipt의 모든 기사 버전의 `extracted_text`, `graph_version_sources`가 가리키는 규칙 적용 전 projection을 포함합니다. native 구성은 ordinal 0인 source 하나여야 하고 receipt·handoff·projection 참조가 완전해야 합니다. `graph_bundle_snapshot`의 디렉터리는 `graph_bundle/`이며, 공개 snapshot과 같은 artifact를 참조하면 한 번만 보냅니다.

누적 패키지는 닫힌 `zoop-graph-delivery-package-3` 형식입니다. 루트 키는 `schemaVersion`, `versionId`, `destinationId`, `publicationId`, `publicationReceiptSha256`, `files`입니다. 파일 목록은 새 snapshot·receipt와 평탄화한 원본 receipt·규칙 적용 전 projection·본문 전체를 포함하며, 규칙에 숨겨진 기사도 전달합니다. 조상 누적 publication의 snapshot·receipt는 포함하지 않습니다. 설치기는 outbox의 실제 바이트로 `GraphPublicationReader`를 실행해 전체 파일 집합을 독립적으로 재계산하고 누락·초과·변조를 거절합니다. 현재 권한은 원본 `(sourceId, grantId, revision)` 전체와 legacy URL 제한으로 다시 확인합니다.

`seal-publication`의 요청은 다음 다섯 필드만 받으며 최대 64 KiB입니다. `expectedReceiptSha256`는 스테이징한 publication receipt 파일의 SHA-256이고, `destinationId`는 실행 설정과 같아야 합니다.

```json
{"schemaVersion":"zoop-graph-publication-seal-1","graphVersionId":"${STAGED_GV}","expectedReceiptSha256":"${RECEIPT_SHA256}","destinationId":"${DESTINATION}","operator":"${OPERATOR}"}
```

native `seal`은 **두 번 커밋**합니다. 첫 번째는 기존 importer의 비활성 버전 및 앱 artifact 등록이고, 두 번째는 현재 source·권한을 다시 확인한 뒤 전체 package/content를 함께 확정하는 outbox transaction입니다. 두 단계 동안 producer root 잠금을 유지합니다. `seal-publication`은 기존 스테이징을 읽고 outbox transaction만 실행합니다. 두 명령과 install 모두 활성 포인터를 바꾸지 않습니다. commit 응답을 잃으면 결과를 미확정으로 보존하고 같은 pin으로 대조합니다.

먼저 배포 담당자가 기존 migration과 `V20261031120000__create_graph_deliveries.sql`, `V20261031130000__record_cumulative_graph_publications.sql`, `V20261031140000__graph_publication_delivery.sql`을 적용해야 합니다. package 행은 native pin 세 개 또는 publication pin 두 개 중 한쪽만 가지며 DB CHECK로 강제합니다. seal/install/status JVM은 공통으로 다음 인자를 사용합니다.

```sh
java -jar "$API_JAR" --spring.main.web-application-type=none \
  --spring.flyway.enabled=false --spring.jpa.hibernate.ddl-auto=validate --spring.sql.init.mode=never
```

| 실행 | 추가 환경 변수 |
|---|---|
| 원본 호스트 seal | 기존 `ZOOP_GRAPH_HANDOFF_IMPORT_*`·CLI source 설정, `ZOOP_ARTIFACT_ROOT`, `ZOOP_GRAPH_DELIVERY_SEAL_ENABLED=true`, `ZOOP_GRAPH_DELIVERY_SEAL_COMMAND=seal`, `ZOOP_GRAPH_DELIVERY_SEAL_DESTINATION_ID`, 새 `ZOOP_GRAPH_DELIVERY_SEAL_RESULT` |
| 누적 publication 봉인 | `ZOOP_GRAPH_DELIVERY_SEAL_ENABLED=true`, `ZOOP_GRAPH_DELIVERY_SEAL_COMMAND=seal-publication`, `ZOOP_GRAPH_DELIVERY_SEAL_REQUEST`, `ZOOP_GRAPH_DELIVERY_SEAL_ARTIFACT_ROOT`, `ZOOP_GRAPH_DELIVERY_SEAL_DESTINATION_ID`, 새 `ZOOP_GRAPH_DELIVERY_SEAL_RESULT`, `ZOOP_DOCUMENT_READ_INGESTION_SOURCES`; handoff import/read-client는 끕니다 |
| 설치 호스트 install | `ZOOP_GRAPH_DELIVERY_INSTALL_ENABLED=true`, `ZOOP_GRAPH_DELIVERY_INSTALL_DESTINATION_ID`, `ZOOP_GRAPH_DELIVERY_INSTALL_VERSION_ID`, `ZOOP_GRAPH_DELIVERY_INSTALL_EXPECTED_PACKAGE_DIGEST`, `ZOOP_GRAPH_DELIVERY_INSTALL_ARTIFACT_ROOT`, 새 `ZOOP_GRAPH_DELIVERY_INSTALL_RESULT`, `ZOOP_DOCUMENT_READ_INGESTION_SOURCES` |
| 기록 조회 status | `ZOOP_GRAPH_DELIVERY_SEAL_ENABLED=true`, `ZOOP_GRAPH_DELIVERY_SEAL_COMMAND=status`, `ZOOP_GRAPH_DELIVERY_SEAL_DESTINATION_ID`, 새 `ZOOP_GRAPH_DELIVERY_SEAL_RESULT`; handoff import는 끕니다 |

모든 실행은 `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`로 **동일한 대상 DB/schema**에 연결하며 snapshot source는 `none` 또는 준비된 `artifact`여야 합니다. native seal은 결과 경로를 handoff importer에도 전달하므로 일반 import 결과 파일을 별도로 예약하지 않습니다. install과 seal-publication은 handoff import/read-client를 켜지 않으며, 문서 import·분석·bindings, legacy import, briefing replay, 제외 명령, compose와 함께 실행할 수 없습니다. status는 현재 권리와 물리적 설치 상태가 아니라 `sealed`·`installed`·현재 활성·활성 이력의 DB 기록을 보고합니다.

상한은 파일당 16 MiB, 파일 1,003개, package 256 MiB, 목적지별 미설치 package 합계 1 GiB입니다. 각각 `ZOOP_GRAPH_DELIVERY_{SEAL,INSTALL}_MAX_FILES`, `_MAX_PACKAGE_BYTES`, seal의 `_MAX_PENDING_BYTES`로 낮출 수 있으며 파일 수의 최대 허용값은 1,003입니다. 누적 원본 기여분 개수에는 별도의 20개 상한을 적용하지 않고 실제 전체 파일·바이트 상한을 적용합니다. 설치가 끝난 outbox content도 불변 데이터로 보관되므로 저장 용량 운영은 별도로 필요합니다.

producer와 serving root는 서로 다른 경로여도 됩니다. root는 기존 실경로이고 실행 계정 소유여야 하며 group/other 쓰기를 허용하면 안 됩니다. 하위 artifact 디렉터리는 정확히 `0700`, 파일·잠금은 `0600`이고 소유자가 같아야 합니다. 결과 파일은 root 밖의 새 경로를 씁니다. 설치는 root 잠금 아래 모든 blob·대상 파일·marker를 먼저 검사하고 현재 registry를 다시 읽은 뒤, no-overwrite hard link와 file/directory fsync로 저장합니다. 마지막 권한 확인 뒤에만 DB acknowledgement를 커밋합니다.

native `already_sealed`는 원본 CLI를 재호출하지 않는 기록 재확인이며 현재 권한 인증이 아닙니다. publication의 `already_sealed`와 모든 `already_installed`는 전체 파일과 현재 권리를 확인하고 파일·DB를 그대로 둡니다. 이미 설치된 파일이 없어졌다면 `target_conflict`로 거절합니다. 설치 중단은 durable marker/파일만 남길 수 있으므로 그대로 보존하고 **같은 명시적 pin과 새 결과 경로**로 재실행합니다. 안전한 동일 바이트 파일만 durability barrier를 거쳐 채택합니다. 빈 결과·잘린 결과·unknown commit은 미실행 증거가 아니므로 status와 같은 pin으로 대조해야 합니다.

배포 전에는 원본 호스트와 설치 호스트가 같은 DB에 연결할 승인된 경로·TLS·역할, 현재 registry 배포, 실제 EFS mount의 소유권·잠금·hard-link·fsync를 확인해야 합니다. 설치기와 웹 앱은 같은 serving mount를 사용하며 웹의 `ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT`와 `ZOOP_DOCUMENT_READ_ARTIFACT_ROOT`도 그 root를 가리킵니다. 배포 identity 계약은 UID 100:GID 101이며 선택한 이미지에서 별도로 확인해야 합니다. destination marker는 canonical root 경로를 고정하므로 같은 destination ID로 다른 root로 옮길 수 없습니다. 동일 경로의 다른 물리 파일시스템까지 구별하지는 않으므로 EFS filesystem/access point는 인프라에서 고정합니다.

로컬 합성 확인은 기존 boot jar·설치된 native-8 CLI·캐시된 OrbStack PostgreSQL로 실행합니다. 각 실행은 새 결과 경로를 쓰며 같은 이름의 `.artifacts` 디렉터리에 명령 결과와 로그를 보존합니다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python api/scripts/graph_delivery_smoke.py \
  --result /tmp/zoop-native-delivery-result.json
```

### 관리자 HTTP 활성화의 별도 합성 smoke

기존 `graph_handoff_import_smoke.py`의 SQL harness 활성화와 검사들은 그대로 유지합니다. 관리자 HTTP 경로는 다음 **별도 명령**으로 확인합니다. 설치된 pipeline, 기존 API boot jar, JDK 21 이상, OrbStack과 프로젝트의 캐시된 `postgres:16.13-alpine` 이미지가 필요하며, 이 명령은 빌드·설치·이미지 pull을 하지 않습니다.

```sh
ai/pipeline/.venv/bin/python -m unittest discover -s api/scripts -p test_graph_handoff_activation_smoke.py
ai/pipeline/.venv/bin/python api/scripts/graph_handoff_activation_smoke.py \
  --result /tmp/zoop-graph-activation-result.json
```

결과 경로는 매번 새 파일을 지정합니다. 명령은 자체 Docker bridge·tmpfs PostgreSQL·loopback JVM과 합성 CLI 원장만 만들고 종료 시 자신의 자원만 정리합니다. PostgreSQL 포트는 `127.0.0.1`에만 엽니다. DB 설정·provider 자격·Spring 설정은 상속하지 않으며 AI 클라이언트는 모두 끕니다. 실제 계정이나 로그인 대신 시험 DB의 합성 관리자·세션을 사용하고, 실제 세션 조회로 받은 CSRF 토큰과 관리자 쿠키·Origin으로 요청합니다. 비밀번호 로그인·OAuth·운영자 계정 발급은 이 시험의 증명 범위가 아닙니다.

bundle `-7` 스테이징 뒤, 공개 제외 저장소가 연결된 기본 설정의 JVM에서 현재 권리 철회에 따른 활성화 거절(409)과 활성 포인터·review revision·활성화 이력·감사·멱등 기록의 불변을 확인합니다. 권리를 복구한 뒤 같은 JVM에서 개발용 우회 플래그 없이 실제 관리자 HTTP 활성화, 같은 키 재전송·다른 본문 충돌·오래된 활성 포인터·새 키로 이미 활성인 버전 요청을 검사하고, 같은 버전의 공개 graph·event·정확한 evidence span 및 현재 권리 철회·복구를 확인합니다. 공개 제외 저장소를 읽지 못할 때의 fail-closed 계약은 Java 시험에서 별도로 확인합니다. SQL은 카탈로그·인증 fixture만 준비하며, 양성 HTTP 활성화를 대신하지 않습니다. 기존 fixture seeder의 활성화도 별도로 집계합니다.

마지막 JSON과 `--result`에는 단계별 상태 코드, `importActivationWrites: 0`, `sqlHarnessActivations: 0`, 실제 HTTP 포인터 변경 수, 현재 권리, `modelCalls: 0`, 소스 HEAD·jar hash와 소유 자원 정리 결과를 기록합니다. 실패는 0이 아닌 종료 코드와 실패 JSON으로 남습니다. 이 시험은 앱의 공개 제외 reader가 연결된 기본 설정을 사용하지만 제외 명령의 변경·해제, 실제 기사 권리, 운영 공개 준비 또는 외부 모델 실행을 증명하지 않습니다. `.env`와 운영 기본값은 바꾸지 않습니다.

**bundle 계약 수정 이력:** 최초 실행에서는 `EventDetailService`가 bundle `-5`만 읽어 `-7` 사건 상세가 503 `SOURCE_UNAVAILABLE`로 차단됐습니다. 이후 읽기 소비자가 정확한 `-5`·`-6`·`-7` receipt를 지원하도록 수정했고, 새 수입은 계속 `-7`만 허용합니다. 당시 수정 후 새 jar의 실제 HTTP 28단계가 통과했으며, 공개 제외 저장소 통합 후 위 기본 설정 경로의 재검증과는 별개입니다. 스크립트는 미지원 계약을 성공으로 처리하거나 bundle 버전을 낮추지 않으며, 향후 같은 불일치가 생기면 `blocked`·종료 코드 1로 기록합니다. 로컬 실행 증거와 운영·수령자 확인은 구분합니다.


## 그래프 정기 회차 (#55)

`com.zoop.graph.round`는 공개 그래프를 30분 회차마다 자동으로 갱신하는 작업의 앱 쪽 조각입니다(AI는 `round-runs`·`round-handoffs`·관측 export를 HTTP로 제공, 앱은 스케줄러·`analyze_plan` 접수·수입·활성화). 2026-10-29 현재 들어 있는 것은 **회차 상태 테이블**(슬롯당 1행 + append-only 이벤트, lease, 영구 보존), **수입 bridge**(`GraphRoundImportBridge`: 위 운영자 수입기와 같은 `GraphHandoffImporter`를 웹 애플리케이션 안에서 회차 행의 핀으로 호출하고 결과를 행·이벤트에 기록. 버전과 회차의 연결은 수입 트랜잭션 안에서 기록하고, 그 기록을 기준으로 수입이 commit된 최근 회차보다 오래된 슬롯은 `skipped_superseded`로 건너뛰어 자동 활성화가 옛 회차를 공개하지 않게 함. 모든 기록은 claim한 lease의 token으로 fencing), **관리자 읽기**(`GET /api/v1/admin/pipeline/rounds`, `/{roundId}`, overview의 `rounds` 섹션)입니다. 스케줄러 본체·retry·수동 시작은 AI #387 계약 뒤에 붙으며, 그 전까지 `ZOOP_GRAPH_ROUND_ENABLED=true`는 설정 검증 외에 아무것도 시작하지 않습니다. 설정·단계·제약·배포 제약(artifact store가 로컬 디스크 전용이라 단일 인스턴스)은 [그래프 정기 회차](docs/GRAPH_ROUND.md)에 있습니다.

## 공개 제외 명령 (FS081)

`com.zoop.graph.exclusion`은 공개 제외 저장소(`disclosure_exclusion_changes`·`disclosure_exclusion_targets`·`disclosure_exclusion_requests`, ERD 37–39절)에 쓰는 **operator 전용 비웹 실행**입니다(`--spring.main.web-application-type=none`, `ZOOP_DISCLOSURE_EXCLUSION_ENABLED=true`, `ZOOP_DISCLOSURE_EXCLUSION_REQUEST`·`ZOOP_DISCLOSURE_EXCLUSION_RESULT`, receipt를 읽을 `ZOOP_ARTIFACT_ROOT`). HTTP 경로가 없고, artifact 저장소는 읽기만 해서(`readVerified`, 잠금 없음) 정기 수입과 같은 시간에도 실행할 수 있습니다. 결과 파일(`0600`, 이미 있으면 덮어쓰지 않음)에는 결과·`replayed`·revision·버전별 개수만 남고 대상 ID는 남지 않습니다.

요청(`zoop-disclosure-exclusion-1`, 닫힌 스키마)은 아래 작업 중 하나이며, 모두 명령 ID `requestId`(`[A-Za-z0-9._:-]{1,200}`)를 가집니다.

- **`exclude`**: `requestId`, `operator`, `reason`, 그리고 `zoop-ai-handoff-exposure`가 출력한 보고서(`zoop-handoff-exposure-1`, 내부 계약 `ExposureReport`)를 `report`에 그대로 넣습니다. 선택한 원본 handoff마다 앱 버전과 receipt의 handoff·manifest·bundle·content pin을 대조하고, 보고서의 모든 대상을 하나의 트랜잭션에서 원본 범위에 기록합니다. 이 제외는 해당 원본을 사용하는 과거·현재·미래 구성본에도 적용됩니다. 이미 제외된 대상과 빈 보고서는 기존 상태를 유지합니다. 관계 오연결(`relation-retraction`)은 기사·근거를 제안할 수 없습니다.
- **`exclude-query`**: `requestId`, `operator`, `reason`, `changed`(내부 계약의 `DocumentChange`·`SourceChange`·`GrantChange`·`RelationChange`), `graphVersionIds`(0~20개)를 받습니다. 비어 있으면 활성 수입 버전과 그 뒤에 수입된 비활성 버전을 선택합니다. 복합 버전은 원본 native handoff로 펼친 뒤 중복을 제거하며, 선택 전체가 최대 20개일 때만 `POST /internal/v1/graph-handoffs/exposure`로 조회합니다. 더 많으면 `exposure_batch_required`, legacy 또는 현재 조회를 지원하지 않는 원본이 섞이면 `versions_invalid`로 전체를 거절합니다. 운영자는 원본 버전을 명시해 범위를 나눌 수 있으며 결과는 그 범위만 증명합니다. `ZOOP_AI_HANDOFF_EXPOSURE_CLIENT_ENABLED=true`, 별도 scope의 `BASE_URL`·`TOKEN` 설정을 사용하고, 받은 보고서는 요청한 변경·handoff와 정확히 일치해야 합니다.
- **`lift`**: `requestId`, `operator`, `reason`, 원본 `graphVersionId`, `expectedRevision`, `targets[{kind,id[,articleVersion]}]`을 받습니다. 대상이 결정 당시 revision 이후 변경됐으면 `revision_stale`로 거절합니다. 한 원본의 해제는 다른 원본의 제외를 해제하지 않습니다.
- **`exclude-legacy` / `exclude-publication`**: `requestId`, `operator`, `reason`, `graphVersionId`, `receiptSha256`, `targets`로 실제 receipt를 고정합니다. legacy 대상은 원본에서 직접 검사하고, 복합 대상은 모든 원본 소유자로 해석해 한 요청·revision으로 기록합니다. 소유자를 찾을 수 없는 표시용 파생 edge ID는 거절합니다.

**재실행.** 결과(`applied`·`unchanged`)에 이른 명령은 변경과 같은 트랜잭션에 `requestId`·요청 SHA-256·결과를 기록합니다. 같은 `requestId`로 다른 요청을 보내면 `request_conflict`이고, 새 결정에는 새 `requestId`를 씁니다.

- **확정 거절:** `request_invalid`, `report_invalid`, `versions_invalid`(빈 선택·지원하지 않는 원본), `exposure_batch_required`(해석한 native 원본이 20개 초과), `exposure_unavailable`, `exposure_refused`, `version_unknown`, `receipt_unavailable`, `receipt_mismatch`, `request_conflict`, `revision_stale`, `database_unavailable`은 이번 실행의 변경을 커밋하지 않습니다.
- **결과를 알 수 없는 경우:** `outcome_unknown`(커밋 여부 불명), `result_unavailable`, `internal_error`, 그리고 결과 파일이 없거나 비었거나 일부만 있거나 읽을 수 없는 경우. 결과 파일은 DB 커밋이 **끝난 뒤** 쓰므로, `result_unavailable`이나 불완전한 결과 파일은 변경이 이미 커밋됐을 수 있습니다. 이 경우에는 롤백이나 무기록을 가정하지 말고, **같은 `requestId`·같은 본문의 요청 파일**을 새 결과 경로로 다시 실행합니다. 이미 커밋됐으면 기록한 결과를 `replayed: true`로 돌려주고 아무것도 바꾸지 않으며, 커밋되지 않았으면 처음 실행처럼 처리합니다.
- **`exclude-query` 기본 선택의 예외:** 실제로 해석한 원본 버전 목록도 요청 hash에 포함됩니다. 이후 수입으로 목록이 바뀌면 같은 요청 ID는 `request_conflict`가 되며, 원본이 20개를 넘으면 기록 조회 전에 `exposure_batch_required`가 됩니다. 이전 실행의 커밋 여부는 `disclosure_exclusion_requests`의 같은 요청 ID와 결과를 먼저 확인합니다.

변경 하나는 공통 publication lock 아래 한 트랜잭션이며 `revision`은 MAX+1입니다. 공개 그래프·근거·챗봇·기업 문서와 브리핑 그래프 basis는 평탄한 원본 소유자를 따라 최신 제외와 현재 권한을 적용합니다. 기사 제외는 정확한 `(articleId,articleVersion)`을 가리키며, 같은 원본을 사용하는 모든 구성본에 전파됩니다. 저장소나 현재 권한을 읽을 수 없으면 `503 SOURCE_UNAVAILABLE`입니다. S1 분석은 별도의 현재 기사 접근 상태와 S1 grant를 계속 확인하고, 이미 발행한 브리핑 저장본은 불변으로 유지합니다. 브리핑 그래프의 필수 대상이 현재 제외되면 해당 graph basis는 사용할 수 없는 상태로 반환합니다. 캐시·Neo4j는 현재 앱 백엔드 제외 소비자 범위와 구분합니다. 실패 단계별 재실행 경계는 [FS067-03·FS081 복구 표](docs/GRAPH_READ_HANDOFF.md#실패-단계와-재실행-경계-fs067-03--fs081)를 따릅니다.

## 기본 기업 카탈로그 적재

`src/main/resources/company/demo-companies.json`은 팀이 확정한 24개 기업 목록입니다. `prototype/` 파일이나 DB를 실행 중에 읽지 않습니다. 종목 코드가 없는 OpenAI·Anthropic은 `ORG:OPENAI`, `ORG:ANTHROPIC` ID를 사용하며 `ticker`, `exchange_code`, `market`은 비워 둡니다. `brand_source`는 색상·로고 출처가 확인된 경우에만 넣고, 단순 홈페이지 주소는 `null`로 둡니다. 향후 GraphDB에서도 같은 회사 ID를 써야 합니다.

`DB_URL`·`DB_USERNAME`·`DB_PASSWORD`를 `api/.env` 또는 OS 환경변수로 설정하고 API를 시작하면 Flyway migration `V20261014163000__seed_confirmed_companies.sql`이 **최초 한 번** 24개 기업을 적재하고, `V20261015090000__add_company_brand_source.sql`이 내부 출처 컬럼을 추가합니다. 그 다음 앱 시작 시 번들 JSON을 읽어 같은 기업 ID의 값을 갱신합니다. 이후 JSON을 바꿔 다시 시작해도 ID 기준으로 변경된 행만 갱신하며 중복 삽입하지 않습니다. 다른 기업 및 이를 참조하는 분석 기록은 삭제하지 않습니다. PostgreSQL 컨테이너만 시작하면 Flyway와 JSON 적재가 실행되지 않으므로 API도 시작해야 합니다. `api/.env`를 사용한다면 `api` 디렉터리에서 앱을 실행하세요.

카탈로그 JSON을 수정해 로컬 DB에 다시 반영할 때에만 `api` 디렉터리에서 명시적 적재 명령을 사용합니다.

```powershell
.\gradlew.bat bootRun --args="--spring.profiles.active=catalog-import --spring.main.web-application-type=none --zoop.catalog.import-file=src/main/resources/company/demo-companies.json"
```

이 수동 명령은 입력 전체를 검증한 뒤 확정 목록을 `companies`에 삽입하거나 같은 ID의 이름·종목 코드·거래소·별칭·브랜드 색상·로고 경로·내부 출처(`brand_source`)를 갱신합니다. `brand_source`의 `null`은 기존 출처를 비우며, 생략하면 기존 값을 보존합니다. 다른 기업은 삭제하지 않습니다. 항목에 `market`(상장사만)이나 `profile`(`legalName`·`representative`·`foundedDate`·`websiteUrl`·`sector`·`businessSummary`만 허용, `foundedDate`는 `YYYY-MM-DD`, `websiteUrl`은 `https://`, `businessSummary`는 600자 이하이며 챗봇이 기업 개요 인용으로 쓴다)이 있으면 그 값으로 바꾸고, 키를 생략하면 기존 값을 보존합니다. `profile` 안의 `null`은 저장하지 않아 API에서 `null`로 나옵니다. `"profile": null`은 프로필 전체를 비웁니다(`market`·`brand_source`의 `null`과 같음). 값은 공식 자료(KIND 기업개요, SEC 연차보고서, 각 사 공식 사이트)로 확인된 것만 넣고 추정하지 않습니다. 해외 기업 설립일(15곳 중 13곳)의 출처와 창립·법인 설립 기준은 [설립일 근거](docs/company-founded-date-sources.md)에 기록했습니다. OpenAI·Anthropic의 `market`은 항상 NULL입니다. 재실행 시 동일한 행은 쓰지 않아 `company_catalog_revision`도 바뀌지 않습니다. 완료 로그의 `total`, `changed`, `unchanged`로 결과를 확인하세요. 기존 Flyway migration은 수정하지 않습니다. 일부 SVG는 프론트엔드가 같은 이름으로 `web/public/graph-assets`에 추가할 예정입니다.

```sql
SELECT count(*) FROM companies;
SELECT id, name, ticker, exchange_code FROM companies
WHERE id IN ('KRX:005930', 'ORG:OPENAI', 'ORG:ANTHROPIC') ORDER BY id;
```

이 파일은 현재 확정된 기본 목록입니다. 상장사 전체 수집·주기적 갱신 및 시세 데이터는 이 적재 절차의 범위가 아닙니다. 회사 검색 API 변경 사항이 합쳐진 뒤에도 GraphDB 이슈 수 snapshot이 준비되지 않으면 검색 요청은 `503 SOURCE_UNAVAILABLE`일 수 있으므로 SQL로 적재 결과를 먼저 확인합니다.

## 스키마와 DB 종료

JPA는 `ddl-auto: validate`, Flyway는 활성화되어 있습니다. 첫 migration은 당시 설계에 따라 `members`, `member_credentials`, `member_sessions`를 생성합니다. 이어지는 [`V20261013000000__align_auth_identity_with_erd_v6.sql`](src/main/resources/db/migration/V20261013000000__align_auth_identity_with_erd_v6.sql)이 비어 있는 인증 스키마를 [ERD v6](../docs/erd/zoop-core-erd-v6.md)에 맞춰 변경합니다. [`V20261013010000__allow_unselected_member_mode.sql`](src/main/resources/db/migration/V20261013010000__allow_unselected_member_mode.sql)은 가입 직후 온보딩 방식을 고르지 않은 회원을 `members.mode=NULL`로 저장할 수 있도록 합니다. [`V20261013020000__create_terms.sql`](src/main/resources/db/migration/V20261013020000__create_terms.sql)은 약관 항목·버전·동의 기록 테이블과 기간 중복 방지 제약을 만듭니다. [`V20261013030000__register_term_catalog.sql`](src/main/resources/db/migration/V20261013030000__register_term_catalog.sql)은 필수 `service`·`privacy` 마스터만 등록합니다. [`V20261013040000__register_approved_term_versions.sql`](src/main/resources/db/migration/V20261013040000__register_approved_term_versions.sql)은 [공개용 약관](../docs/legal/README.md)의 두 본문을 버전 `2026-10-13.1`로 등록하고 2026-10-13 17:00 KST부터 효력이 생기게 합니다. 적용 후 비밀번호 해시와 회원 설정은 `members`에 있고 `member_credentials`는 없습니다. 대응 Entity는 `com.zoop.auth.entity`에 있습니다. 관리자 인증 migration [`V20261017100000__create_admin_auth.sql`](src/main/resources/db/migration/V20261017100000__create_admin_auth.sql)은 `admins`, `admin_sessions`, `audit_logs`와 관리자 로그인 제한 scope를 추가하지만 계정은 생성하지 않습니다. 후속 스키마 변경은 `src/main/resources/db/migration/`에 Flyway SQL을 추가합니다. 자동 테이블 생성이나 프로토타입 DB 재사용으로 대신하지 않습니다.

DB를 종료하되 데이터를 유지하려면 다음을 실행합니다.

```sh
docker compose --env-file api/.env -f api/compose.local.yaml down
```

로컬 데이터를 **모두 삭제하고 초기화할 때만** 다음 명령을 사용합니다.

```sh
docker compose --env-file api/.env -f api/compose.local.yaml down --volumes
```

포트 충돌 시 `DB_PORT`와 `DB_URL`, 또는 `SERVER_PORT`를 함께 확인합니다. 동일 머신에서 여러 checkout을 실행하면 Compose의 `-p` 옵션으로 서로 다른 프로젝트명을 사용하고 DB 포트도 분리하세요.

목표 API 정본은 [OpenAPI](../docs/api/openapi.yaml)입니다.

## 기능 추가와 패키지

`com.zoop` 아래에 실제 기능을 맡은 사람이 필요한 패키지만 만듭니다. 예를 들어 기업 조회를 구현할 때 `company/controller`, `company/service`, `company/repository`, `company/entity`, `company/dto`를 필요한 만큼 생성합니다. 빈 기능 패키지는 미리 만들지 않습니다. `common`에는 여러 기능에서 실제로 쓰는 요청·오류 처리처럼 공유 책임만 둡니다.

- Controller는 요청·응답 DTO를 다루고 Service를 통해 업무를 실행합니다. JPA Entity를 HTTP 응답으로 직접 반환하지 않습니다.
- 다른 기능의 Repository나 Entity에 직접 의존해야 할 때는 먼저 소유 담당자와 Service 메서드 또는 인터페이스를 합의합니다. 합의 전에는 운영 코드에 성공을 흉내 내는 stub을 넣지 않습니다.
- Java 패키지는 소문자, 타입·파일은 PascalCase, 필드·메서드는 lowerCamelCase를 씁니다. HTTP 경로와 JSON 필드·nullable·상태 코드는 [목표 OpenAPI](../docs/api/openapi.yaml)를 따릅니다. 경로 prefix는 `/api/v1`입니다.
- 입력 DTO에 Bean Validation을 적용하고 정상·입력 오류·자료 부재·장애·복구를 해당 기능의 테스트에서 확인합니다. 현재 공통 테스트의 테스트 전용 Controller는 업무 API가 아닙니다.

예를 들어 없는 기업을 조회할 때는 `throw new CustomException(ErrorCode.RESOURCE_NOT_FOUND);`를 사용합니다. 새 오류 코드가 필요하면 명세의 코드·HTTP 상태·재시도 의미를 확인한 뒤 `ErrorCode`와 해당 기능 테스트를 함께 추가합니다. 인증 필터는 `GlobalExceptionHandler`를 거치지 않으므로 인증 담당자가 동일한 오류 형식과 요청 ID를 연결합니다.

기능 간 데이터 계약을 정할 때는 아래 항목만 먼저 합의하고 이슈 또는 PR에 기록합니다. 인증·공개 버전·AI 연동처럼 여러 기능이 쓰는 인터페이스도 최초 소비 기능이 시작될 때 합의합니다.

```text
제공 기능 / 소비 기능:
제공 담당자 / 소비 담당자:
메서드 또는 API와 입력·반환 DTO:
null·자료 없음·실패의 의미:
권한 확인 책임:
```

초기 담당 범위는 [10월 12일 WBS 원문](../docs/evidence/raw/wbs_2026-10-12/01-프로젝트-WBS.csv)의 업무명·역할을 따릅니다. 아래 패키지는 구현 위치 예시이며 빈 디렉터리를 미리 만들거나 새 담당자를 지정하는 표가 아닙니다. 여러 WBS에 걸친 기능은 작업을 시작할 때 제공·소비 책임을 정합니다.

| 담당 | 우선 구현 범위 | 관련 기능 패키지 예시 |
|---|---|---|
| 임현 | 인증·회원·관심종목·가상계좌·관리자 인증 | `auth`, `member`, `portfolio` |
| 정세빈 | 기업 검색·상세·그래프 조회·검수 API | `company`, `graph`, `pipeline` |
| 윤서진 | 근거·문서·수집·분석 연동·공개 반영 | `evidence`, `pipeline`, `publication` |
| 홍정현 | 브리핑·발행·정정·관련 평가 | `briefing`, `feedback` |
| 김도현 | 대화·질문 작업·대화록·관련 평가 | `chat`, `feedback` |
| 안재현 | AI 사용량·비용·오류 조회 | `analytics` |

`feedback`, `pipeline`처럼 두 담당 범위가 만나는 곳은 같은 Entity·migration·Service를 각각 만들지 않도록 해당 PR의 소유자를 먼저 정합니다. 재무·실적은 목표 계약이 남아 있지만 대응 WBS가 없어 이 표에서 임의로 배정하지 않습니다.

## DB 변경 규칙

개발자마다 별도 로컬 DB와 Compose 프로젝트·볼륨을 사용합니다. 신규 테이블·컬럼 이름은 [ERD v6](../docs/erd/zoop-core-erd-v6.md)에 명시된 이름을 우선하고, 새 이름은 소문자 `snake_case`로 작성하며 JPA 매핑에 명시합니다. 기능별 migration 범위와 소유권은 [API migration 담당 경계](../docs/development/api-migration-ownership.md)를 따릅니다. 업무별 테이블 소유자는 해당 기능 담당자입니다. 다른 기능의 테이블·제약·컬럼을 변경할 때는 소유 담당자와 변경 이유·호출 영향을 먼저 합의합니다. 기능 간 외래 키는 삭제 정책과 migration 순서를 함께 검토합니다.

공유 스키마는 `src/main/resources/db/migration/`의 Flyway SQL로 변경합니다. 예: `V20261012153000__create_members.sql`. 타임스탬프는 중복을 피하기 위한 버전 표기이며 이미 적용된 migration을 수정하지 않습니다. 같은 버전의 파일이 병합됐다면 **아직 공유되지 않은** 자신의 migration 이름을 조정하고 새 DB와 기존 DB 양쪽에서 순서대로 적용되는지 확인합니다. 테이블 자동 생성으로 migration을 대신하지 않습니다.

스키마가 바뀌는 PR에는 새 로컬 DB에서 기동되는지, 이전 스키마에 migration을 추가 적용해 기동되는지 적습니다. 기존 개발 데이터가 있는 DB를 테스트 전용 초기화 대상으로 사용하지 않습니다. `down --volumes`는 위의 로컬 개발 DB만 삭제할 때 사용합니다.

## Git 협업과 검증

작업은 [저장소 참여 규약](../CONTRIBUTING.md)의 실제 이슈 번호를 사용하는 기능 브랜치와 PR로 병합합니다. `main`에 직접 push하지 않습니다. 보호 규칙의 실제 활성화 여부는 [GitHub 설정 안내](../docs/development/github-setup.md)를 확인하세요.

본인 기능 패키지를 중심으로 변경하고, `common`, `build.gradle`, `application.yml`, Flyway migration 등 공유 파일의 변경은 PR에 이유와 영향을 적고 관련 담당자에게 알립니다. 계약 변경은 `docs/api/` 정본과 영향을 받는 consumer·fixture·시험을 함께 수정합니다. PR에는 실행한 `./api/gradlew -p api test` 및 `build` 결과와, DB가 필요한 기능이라면 적용 시험 결과를 기록합니다.

API 앱 검사기는 루트 Makefile(`api-test`/`api-build`/`api-ai-smoke`)과 CI job `api`(required gate 포함)에 연결돼 있습니다. 첫 업무 기능 PR은 이 job에서 자신의 시험이 실제로 실행되는지 확인합니다. 인증·CSRF, 커서, 멱등성, 공개 버전, AI 결과 import(전송 클라이언트는 `com.zoop.ai`), 감사 기록은 각각 필요한 기능의 완료 기준에 포함합니다. 공통 코드 구현을 모두 선행 조건으로 만들지는 않습니다.

| 후속 작업 | 책임 역할 | 완료 시점 |
|---|---|---|
| 회원·관리자 세션, 권한·Origin·CSRF 오류 처리 | 인증 담당 | 보호가 필요한 업무 API 완료 전 |
| 불투명 커서·공개 버전 고정 | 해당 조회 기능 담당 + 데이터 소유 담당 | 해당 조회 API 완료 전 |
| 쓰기 멱등성·AI 작업 계약·감사 기록 | 해당 쓰기·AI·관리자 기능 담당 | 해당 기능 완료 전 |

기업별 문안 품질 개선과 동일 입력 비교: [판단·새 사실·다음 확인 조건](docs/BRIEFING_COMPANY_READING_V2.md). 새 생성은 company-outlook-v4 / company-reading-v2를 사용하며 기존 발행본은 보존합니다.

### 비교 판단 갱신과 이전 기업 추적

선정 목록의 `previousComparison`/`sinceMorning`은 그대로 사건 포함 여부 비교입니다. 선택적 `judgmentUpdate`는 별도 저장 스냅샷으로, 실제 직전 회사 판단 → 전체 보존 원문 → 이번 해석 → 강화/약화 확인 조건을 제공합니다. `selected`는 현재 핵심 기업, `watch`는 직전 기업의 미해결 조건 추적이며 신규 선정으로 취급하지 않습니다. 이전 판단이 없으면 `initial/unassessable`, 추가 근거가 없는 watch는 `maintained/unassessable`만 허용합니다.

`scripts/briefing_judgment_update.py --baseline <완료 bundle 폴더> --sources <고정 sources.jsonl> --output <새 private 폴더> --round-id <현재 회차> --authorization-ref <기존 실행 승인 참조> --run-id <새 실행 ID> --max-calls <승인된 전체 상한>`으로 먼저 유료 호출 없는 입력 계획을 확인합니다. 명시적 `--execute --key-file <서버 전용 키 파일>` 실행은 생성1·독립검증1회이며 실패 시 초안은 공개하지 않고 자동 재호출하지 않습니다. 완료 실행은 요청 identity와 bundle SHA가 같을 때 0회 재사용합니다. 승인 call/비용 상한은 기존 전체 원장과 함께 관리해야 합니다.

짧은 인용만 모델에 전달하지 않습니다. 기존 인용과 동일한 문서 SHA의 전체 본문을 넣고 길이 초과를 묵시적으로 자르지 않습니다. 원문 조건 완전성·과거 판단 실재성·해석 범위·카드 일치를 사실 지지와 별도로 검증합니다. 원발행 시각으로 재생하는 자료는 늦은 수집/당시 본문 동일성 미입증 표시를 유지합니다. 기록된 요청/응답/스키마/프롬프트/토큰과 이전 판단·원문 SHA를 import 때 다시 대조합니다.

수동 편집은 원 AI 초안과 시도를 수정하지 않고 `editorialReview`에 전후 문장·근거 ID·검토자·시각·입력 SHA를 남깁니다. 편집 적용 문구를 독립 모델 검증 통과라고 표시하지 않습니다. 기존 발행본/ERD/migration은 덮어쓰지 않으며 개발 재생은 별도 DB에서 실행합니다.

### 출근 집중·퇴근 하루 평가 편집본

`editionReview`는 출근의 오늘 집중/조건, 퇴근의 오늘 장 평가/아침 기업 점검/다음 거래일 시나리오를 별도 스냅샷으로 제공합니다. `scripts/briefing_edition_review.py`는 네트워크·API 키·모델 호출 없이 `--baseline`, `--sources`, `--reviews`, `--output`, `--authorization-ref`의 원문 대조 편집 파일을 검사해 새 bundle을 만듭니다. `REVIEWED/editorial_source_review`이며 자동 생성·독립 모델 검증 통과라는 뜻이 아닙니다. 동일 입력/SHA의 완료 결과는 새 호출 없이 재사용합니다.

직전 편집본 버전과 모든 추적 기업·확인 조건을 결속합니다. 새 핵심 기업을 추가해도 아침의 기존 기업을 누락할 수 없습니다. 조건 실현/훼손에는 해당 기업의 아침 이후 근거가 필요하며, 가격 상승만으로 조건 확인이나 적중을 만들지 않습니다. 보존된 공급자 원시 시세를 각 새 마감 기준으로 다시 계산하고 Java에서 독립 재구성해 확인합니다. 미국 기업 등 아침 이후 새 정규장 관측이 없는 경우는 가격 평가를 유보합니다.

종가의 실제 날짜와 비교 기준 날짜를 표시합니다. 오늘 종가·전 거래일 기준이 부족하면 오늘 하루 강약을 확정하지 않고, 장중·업종·수급 미제공을 구분합니다. 미확인 거래 캘린더로 다음 거래일 날짜나 행사 일정을 만들지 않습니다. 전망은 사업 조건과 반대 시나리오이며 자료 부족을 매수 의견으로 바꾸지 않습니다. 기존 발행 전문·시세·시장 지표·원문·모델 이력과 ERD/migration은 보존하며 개발 재생은 별도 DB에서 확인합니다.

### 회차별 기업 가격 관측·기사 전후 문장

`companyPriceContext`는 기존 원문 대조 사업 판단과 별개인 토스 시세 관측 스냅샷입니다. `scripts/briefing_price_context.py --baseline <editionReview가 있는 폴더> --output <새 폴더> --api-base http://127.0.0.1:<API포트> --authorization-ref <기존 자료 권한 참조> --request-note <현재 실행 요청 참조>`로 완료 응답을 재사용하며 일봉·5분봉 입력을 고정합니다. 키를 인자로 받지 않고, 이미 인증된 로컬 종목 API의 과거 `to` 조회만 사용합니다. 새 bundle을 별도 DB에 기존 replay importer로 저장합니다. 독립 시장/업종 수급 수집이나 모델 호출은 하지 않습니다.

JVM은 보존 응답의 SHA·기업·통화·해상도·요청 마감·완료 봉을 검증하고 관측 문장을 직접 계산합니다. 봉 시작 시각이 아닌 종료 시각으로 미래 가격을 제외합니다. 마감 전 회차에는 나중에 완성된 당일 일봉을 쓰지 않고, 종가/거래량은 일봉과 마지막 분봉의 정의를 구분합니다. 기사 후 거래 없음과 공개 직전 가격 구간 미확보를 나눕니다. 동일 날짜 출근 관측과 비교하며 같은 시각의 가격 수정은 신규 거래로 계산하지 않습니다. 가격 변화율은 percent 단위 문자열입니다. 가격 반응으로 기존 사업 판단을 승급하거나 적중 처리하지 않습니다.

전망 본문에도 가격을 반영하려면 수집 CLI에 `--integrate-outlook`을 지정합니다. `--reuse <앞선 시세 수집 폴더>`로 일치하는 응답을 재사용할 수 있습니다. opt-in 입력에만 `outlookIntegrationVersion=zoop-company-price-outlook-v1`을 추가하고, 기존 입력·발행본은 유지합니다. 원문 대조 사업 판단/stance를 보존하면서 가격 관측·기사 전후 가능 범위·다음 확인 조건을 `companyPriceContext.companies[].outlook`으로 합성합니다. 새 AI 판단이나 독립 모델 검증 결과가 아닙니다. `marketReference`는 KOSPI/KOSDAQ/원달러 값과 정확한 관측일·비교일을 함께 제공합니다. 여러 날짜에 걸친 비교를 전일 대비로 바꾸지 않고, 해외기업의 직접 비교지수·뉴스 원인·초과성과로 사용하지 않습니다.

### 실제 가격을 입력한 AI 기업 전망 v5

기존 가격 관측/규칙 합성문과 구분되는 선택적 `aiPriceOutlooks`를 제공합니다. 원문·회차 가격·실제 이전 AI 판단으로 생성하고 별도 검증한 결과만 새 기업 전망에 표시하며, 실패/이전 판본은 보존합니다. [v5 준비·실행·DB/API 연결](docs/BRIEFING_COMPANY_PRICE_PROMPT_V5.md)을 참조하세요. 운영 기본 실행을 자동 변경하지 않으며 외부 유료 호출 한도 원장이 필요합니다.

### 브리핑 이슈별 S3 영향 평가

`GET /api/v1/briefings/{roundId}/items/{eventId}/impacts`는 발행 당시 고정 그래프의 S3 원장과 현재 조회 가능한 인용을 읽습니다. 기업별로 검증된 긍정·부정·혼재·판단 유보를 구분하며 미저장/검증 실패를 평가로 대체하지 않습니다. 과거 재구성 그래프에는 원래 없던 평가를 만들지 않습니다. 가격 전망과는 별도이며 신규 AI 호출·저장·발행을 하지 않습니다. 상세 계약과 권한/검증 경계는 [BRIEFING_S3_IMPACTS.md](docs/BRIEFING_S3_IMPACTS.md)를 참조하세요.


### S3 사후 재평가 조회

기존 발행본에 S3 평가가 없으면 별도로 승인·실행한 실제 인용 기반 결과를 `GET /api/v1/briefings/{roundId}/items/{eventId}/impact-reviews`로 읽을 수 있습니다. 기본 설정은 비활성이며 읽기용 manifest와 SHA-256을 명시해야 합니다. 원래 발행본·시세·근거를 변경하지 않고 사후 생성 시각과 입력 범위를 구분합니다. 조회는 AI를 호출하지 않습니다. 실행·예산·현재 권한 경계는 [S3 영향 평가](docs/BRIEFING_S3_IMPACTS.md)를 따릅니다. 키·실제 입력·결과 파일은 저장소에 포함하지 않습니다.

### 완료된 PoC/BFF 실자료 가져오기

`legacy-real`은 완료된 PoC/BFF 결과를 그래프와 문서 저장소에 옮기는 별도 운영자 경로입니다. [입력 패키지·권한·명령·활성화 계약](docs/GRAPH_READ_HANDOFF.md#완료된-pocbff-실자료-legacy-real)을 따릅니다. legacy2는 기사에 근거한 지리 분류를 갖춘 형식 3으로 등록합니다. legacy3는 고정된 `metadata-policy.json`에 따라 미확인 지역·날짜·기간을 명시적 null로 보류하는 형식 4를 사용하며, 원본 값과 판단은 receipt에 보존합니다. 두 경로 모두 사건·기업 연결 근거와 현재 source registry의 읽기·저장·인용 표시 권한을 충족한 이슈를 비활성 버전으로 등록하고, 공개는 관리자 활성화 API에서 별도로 처리합니다.

### 기존 자료를 보존하는 누적 그래프 발행

각 native/legacy 가져오기는 원본 비활성 버전으로 보존합니다. 운영자는 `zoop.graph-publication-compose.enabled=true`인 별도 nonweb 실행에서 실제 활성 버전과 새 원본 버전들을 합쳐 하나의 비활성 후보를 만듭니다. 필수 설정은 `request`, `result`, `decisions`, `artifact-root`이며, 현재 공개 권한은 기존 `zoop.document-read.ingestion-sources`에서 읽습니다. 요청과 결과 경로는 artifact root 밖에 두고 결과는 새 파일로 예약합니다.

요청 형식은 `zoop-graph-publication-compose-1`입니다. `baseVersionId`, `expectedActiveVersionId`, `expectedBaseReceiptSha256`은 필요한 null을 명시하고, 정렬한 `incomingVersionIds`와 같은 집합의 `incomingReceiptPins[{versionId,sha256}]`, 현재 `expectedRuleRevision`·`expectedReviewRevision`, 결정 파일 바이트의 `decisionsSha256`, `operator`를 모두 넣습니다. 첫 구성은 실제 활성 포인터가 null 또는 fixture일 때만 null base를 사용하며, fixture ID가 활성 상태이면 그 ID를 그대로 고정합니다.

새 입력은 명령당 1–20개입니다. 누적 원본 수에는 20개 제한을 적용하지 않습니다. 전체 보존 참조는 artifact당 16 MiB와 실제 전송 closure의 1,003개 파일·256 MiB 경계를 따릅니다. 기존 원본의 규칙 적용 전 projection을 합친 뒤 현재 공개 규칙을 한 번 적용하며, 입력에서 빠진 기존 이슈도 보존합니다. 충돌은 명시적 근거·필드 선택으로 해결하거나 후보 전체를 거절합니다.

`staged` 또는 `unchanged` 결과의 `graphVersionId`와 `receiptSha256`을 다음 전송·수동 활성화 단계에 사용합니다. 실패 코드가 `outcome_unknown`이면 같은 요청과 새 결과 경로로 상태를 대조합니다. 자세한 결정 파일·원본별 제외·권한 계약은 [누적 발행](docs/GRAPH_READ_HANDOFF.md#누적-발행과-원본별-현재-권한)을 따릅니다.
