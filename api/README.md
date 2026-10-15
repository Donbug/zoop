# Zoop API 실행 환경

Spring Boot 실행 기반, 공통 오류 처리, 내부 AI 분석 transport 클라이언트와 ERD v6에 맞춘 인증 DB 스키마가 있습니다. 공개 약관 조회·이메일 회원가입·로그인·회원 세션 조회가 구현됐습니다. 문서 저장(`artifacts`·`articles`·`article_versions`)과 operator 전용 비웹 import([문서 import](docs/DOCUMENT_IMPORT.md)), S1 문서 분석([문서 분석](docs/DOCUMENT_ANALYSIS.md))도 지원합니다. 루트 `make api-test`·`api-build`·`api-ai-smoke`와 CI job `api`가 연결돼 있습니다. 기존 프로토타입과 DB를 공유하지 않습니다.

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
set -a
. ./api/.env
set +a

docker compose --env-file api/.env -f api/compose.local.yaml up -d --wait
./api/gradlew -p api bootRun
```

Spring Boot는 `.env`를 자동으로 읽지 않습니다. 위 셸에서 환경변수를 내보낸 후 실행하거나 IDE Run Configuration에 아래 변수를 직접 등록하세요. Compose의 `--env-file`은 DB 컨테이너 설정에만 적용됩니다.

| 변수 | 용도 |
|---|---|
| `DB_PORT` | 로컬 PostgreSQL 호스트 포트 (Compose 기본값 5432) |
| `DB_NAME` | 로컬 PostgreSQL DB 이름 |
| `DB_URL` | 애플리케이션의 JDBC URL |
| `DB_USERNAME` | DB 계정 |
| `DB_PASSWORD` | DB 비밀번호 |
| `SERVER_PORT` | 애플리케이션 포트 (기본값 8080) |
| `ZOOP_AUTH_CSRF_ACTIVE_KEY_ID` | 새 회원 세션의 CSRF 서명 키 ID. 예: `local-v1` |
| `ZOOP_AUTH_CSRF_KEYS` | `키ID=base64url(32바이트 이상)` 목록. 키 회전 중에는 쉼표로 이전 키도 유지 |
| `ZOOP_AUTH_ALLOWED_ORIGINS` | 가입·로그인 및 회원 쿠키가 붙은 쓰기 요청을 허용할 정확한 HTTPS Origin 목록(쉼표 구분). 빈 값은 전부 거절 |
| `ZOOP_AUTH_TRUSTED_PROXIES` | `X-Forwarded-For`를 제공할 수 있는 프록시의 숫자 IP 목록(쉼표 구분). 빈 값은 전달 헤더 무시 |
| `ZOOP_AI_CLIENT_*` `ZOOP_AI_EXTRACTION_CLIENT_*` `ZOOP_AI_RELATION_CLIENT_*` | 선택. 내부 AI transport 클라이언트(S1/S2/S3 가족별, 기본 비활성, 설정 없이도 기동). 이름·규칙은 [AI 연동](docs/AI_INTEGRATION.md#설정)과 [S2·S3 절](docs/AI_INTEGRATION.md#s2-추출s3-관계-클라이언트) |
| `ZOOP_DOCUMENT_IMPORT_*` `ZOOP_INGESTION_*` `ZOOP_ARTIFACT_ROOT` | 선택. operator 전용 비웹 문서 import(기본 비활성, 설정 없이도 기동). 이름·규칙은 [문서 import](docs/DOCUMENT_IMPORT.md#실행) |
| `ZOOP_DOCUMENT_ANALYSIS_*` | 선택. operator 전용 비웹 문서 분석(기본 비활성, 설정 없이도 기동). S1 AI 클라이언트(`ZOOP_AI_CLIENT_*`)와 위 `ZOOP_INGESTION_*`·`ZOOP_ARTIFACT_ROOT`도 필요하고 문서 import와 한 프로세스에서 함께 켤 수 없습니다. 이름·규칙은 [문서 분석](docs/DOCUMENT_ANALYSIS.md#실행) |

`DB_PORT`나 `DB_NAME`을 바꾸면 `DB_URL`도 일치하게 수정하세요. `.env.example`의 비밀번호는 로컬 전용 예시이며 운영용이 아닙니다. 실제 `.env`는 Git에서 제외됩니다. 이미 초기화된 DB 볼륨의 계정·비밀번호는 환경변수만 바꿔도 변경되지 않습니다.

회원 세션용 키를 로컬에서 생성해 `api/.env`의 `ZOOP_AUTH_CSRF_KEYS`에 `local-v1=<출력값>` 형식으로 넣으세요. `python3 -c 'import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))'`로 생성할 수 있습니다. 키 설정이 없거나 32바이트 미만이면 서버 기동이 실패합니다. 운영에서는 비밀 저장소로 두 환경변수를 주입하고, 키를 교체할 때 아직 살아 있는 세션이 참조하는 이전 키를 목록에 보관합니다. 이 값과 세션 쿠키 원문은 로그나 저장소에 남기지 마세요.

`/`의 404는 정상입니다. 서버 로그의 `Started ZoopApplication`과 DB·Flyway 초기화를 확인하세요. 잘못된 DB 설정에서는 기동이 실패해야 합니다.

본개발 가입 화면은 공개 `GET /api/v1/auth/terms`로 현재 제공 가능한 약관을 조회해야 합니다. `limit`와 응답의 `nextCursor`로 다음 페이지를 요청할 수 있으며, `limit`을 생략하면 전체 목록을 반환합니다. 약관 시행 전에는 항목 자체는 조회되지만 `body`와 `version`이 `null`, `bodyAvailable`이 `false`입니다. 이번 승인 본문의 시행일은 2026-10-13 17:00 KST입니다. 가입 로직은 유효한 필수 약관 본문이 제공되기 전에는 완료되면 안 됩니다.

`POST /api/v1/auth/signup`은 현재 유효한 필수 약관 버전과 실제 동의를 확인한 뒤 회원·동의·세션을 한 트랜잭션에 저장하고 `201 SessionResponse`와 보안 쿠키를 반환합니다. `POST /api/v1/auth/login`은 이메일·비밀번호로 활성 회원을 인증해 `200 SessionResponse`와 새 보안 쿠키를 반환합니다. 잘못된 자격 증명은 `401 INVALID_CREDENTIALS`, 비밀번호가 맞는 차단 계정은 `403 MEMBER_BLOCKED`입니다. 가입·로그인 입력과 응답 형식은 [OpenAPI](../docs/api/openapi.yaml)를 따릅니다.

`GET /api/v1/auth/session`은 `zoop_session` 쿠키가 없으면 `anonymous`를 반환하고 새 세션을 만들지 않습니다. 유효한 회원 쿠키는 회원·설정 상태·만료 시각·세션 결합 CSRF 토큰을 반환합니다. 만료·폐기·무효 쿠키는 `Max-Age=0`으로 제거합니다. 세션 토큰 원문은 쿠키로만 전달하고 DB에는 SHA-256 해시만 저장합니다.

회원 쿠키가 붙은 `/api/v1/**` 쓰기 요청은 허용 Origin과 단일 `X-CSRF-Token` 헤더를 검사합니다. 토큰은 현재 활성 세션에 결합되어야 하며 누락·불일치·만료·폐기·중복 쿠키/헤더는 `403 ACCESS_DENIED`입니다. 가입·로그인은 세션 발급 전 Origin을 별도로 검사합니다. 쿠키가 없는 요청의 인증·권한은 각 업무 API에서 강제해야 합니다. 관리자 쿠키의 CSRF 검증은 관리자 인증 구현 범위입니다.

가입·로그인 POST는 Origin이 정확히 허용 목록에 있어야 합니다. 누락·`null`·불일치 Origin은 `403 ACCESS_DENIED`이며 `Referer`로 대체하지 않습니다. 클라이언트 IP는 기본적으로 직접 연결 주소를 사용하고, 명시한 프록시에서 온 요청만 `X-Forwarded-For`의 신뢰 체인을 해석합니다. 프록시는 외부에서 받은 전달 헤더를 제거하거나 덮어써야 합니다. 가입은 IP 10회/시간·이메일 비교키 5회/시간, 로그인은 IP 100회/15분·이메일 비교키 실패 20회/15분을 PostgreSQL의 이동 창 기록으로 제한합니다. 허용 Origin의 요청은 본문 파싱 전에 IP 시도를 기록하므로 잘못된 JSON·이메일 형식도 IP 제한에 포함됩니다. 유효한 이메일의 가입 시도는 이후 이메일 비교키에도 기록합니다. 거절된 요청은 `429 RATE_LIMITED`와 초 단위 `Retry-After`를 받습니다. 로그인 성공은 해당 이메일 실패 카운터를 초기화합니다. 기록은 1시간 후 정리됩니다.

## 빌드

```sh
./api/gradlew -p api --version
./api/gradlew -p api clean build
./api/gradlew -p api test
```

DB 환경변수가 없으면 단위·웹 계층 테스트만 실행되고 PostgreSQL 통합 테스트는 건너뜁니다. `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`를 설정한 뒤 `./api/gradlew -p api test`를 실행하면 가입·로그인·세션·제한 경계 통합 테스트도 실행됩니다. 결과 XML의 `skipped`가 0인지 확인하세요. 새 DB 경로는 별도 빈 데이터베이스를 만들고 같은 환경변수로 `test`를 실행해 Flyway 전체 적용을 검증합니다. 기존 DB 경로는 기존 로컬 DB URL로 다시 실행합니다. 실행 JAR은 `api/build/libs/`에 생성됩니다. 루트에서는 아래 이름을 씁니다(`prototype/bff`의 `bff-*`와 구분됩니다).

```sh
make api-test                        # ./api/gradlew -p api test
make api-build                       # ./api/gradlew -p api assemble
make service-install api-ai-smoke    # 실제 Java -> ai/service -> zoop-ai replay gate (./gradlew aiContractTest)
make pipeline-install service-install api-ai-pipeline-smoke   # 실제 Java -> ai/service -> zoop-ai-extract/-relation 종단 gate (./gradlew aiPipelineContractTest)
```

`aiContractTest`와 `aiPipelineContractTest`는 기본 `test`에서 제외되며 각각 `make api-ai-smoke`, `api/scripts/ai_pipeline_gate.py`(`make api-ai-pipeline-smoke`)가 서비스를 띄워 매니페스트를 넘길 때만 통과합니다. 매니페스트가 없으면 skip이 아니라 실패합니다. 후자는 새 합성 운영자 세계와 설치된 pipeline이 필요합니다(`make pipeline-install service-install`; 없으면 실패).

## 공통 오류 처리

`CustomException`에 명세의 `ErrorCode`를 전달하면 `GlobalExceptionHandler`가 `{ "error": { "code", "message", "requestId", "retryable" } }` 형식으로 반환합니다. 인증에는 `INVALID_CREDENTIALS`, `MEMBER_BLOCKED`, `ACCESS_DENIED`, `EMAIL_TAKEN`, `TERMS_REQUIRED`, `RATE_LIMITED`가 구현돼 있습니다. 제한 초과 응답에는 `Retry-After`도 포함됩니다. 성공 응답은 공통 래퍼로 감싸지 않습니다.

모든 요청의 `X-Request-ID`를 응답 헤더에 반환하며, 생략하면 서버가 새 ID를 생성합니다. 오류 본문의 `requestId`는 해당 응답 헤더와 같습니다. 요청 ID를 멱등성 키로 사용하지 마세요. Origin·CSRF 인터셉터의 오류도 같은 형식을 따릅니다.

## AI 분석 transport

`com.zoop.ai`는 `ai/service`의 internal operation을 호출하는 전송 클라이언트입니다. S1 분석 5개(submit/status/result/cancel/recover)에 더해 S2 추출 job(`ExtractionClient`, 서버 사전 승인 digest 참조) 5개와 S3 관계 job(`RelationClient`, 허용된 upstream과 AI 원천 version·revision을 거는 검수 `review`/`operation`/`recoverOperation` 포함) 8개를 별도 가족으로 호출하며, 가족마다 설정은 독립이고 기본 비활성입니다. 서비스 principal로 호출하며 앱 저장·사용자 격리·결과 import·공개 endpoint·공개 인증은 포함하지 않습니다. 설정, 의미(202≠완료, withheld, 결과 불명 복구), 요청 ID, 검증 범위와 인계 사항은 [AI 연동](docs/AI_INTEGRATION.md)에 있습니다.

## 문서 등록 import

`com.zoop.document`·`com.zoop.artifact`는 FS056의 문서 쪽 저장입니다. 설치된 `zoop-ai-ingest export`의 정제 텍스트를 `artifacts`·`articles`·`article_versions`와 로컬 파일로 등록하는 **operator 전용 비웹 실행**(`--spring.main.web-application-type=none`)이며 HTTP 경로가 없고 평소 기동은 달라지지 않습니다(`V20261014120000`이 세 테이블을 만듭니다). 분석·AI 결과 import·그래프·공개 반영은 이 실행이 하지 않습니다(분석은 아래 별도 실행). 입력 스키마, 결과 파일, 실패 코드, 접근 규칙과 실제 DB smoke(`api/scripts/document_import_smoke.py`)는 [문서 import](docs/DOCUMENT_IMPORT.md)에 있습니다.

## 문서 분석

`com.zoop.document.analysis`는 등록된 문서 버전 하나를 S1 AI 서비스로 요약·기업 판정하고 검증된 결과를 `document_analyses`·`evidence`·`ai_executions`와 artifact 파일에 저장하는 **operator 전용 비웹 실행**입니다(`V20261014130000`). `prepare`는 AI 서비스를 부르지 않고 새 AI jobId와 불변 `ai_submit`을 커밋하며, `advance`는 status를 먼저 읽고(submit·recover 직전에는 현재 grant·article을 다시 확인), 결과를 입력 결속·digest 재계산·검증자가 본 claim 대조·코드 포인트 인용 검사·현재 grant 재평가를 거쳐 한 transaction으로 정산하며, 그 transaction이 article·행 잠금을 얻은 뒤 grant를 한 번 더 평가합니다. HTTP 경로·`analysis_jobs`·공개 읽기·live 실행은 없습니다. 입력 스키마, 결과 파일, 실패 코드, 권리·크래시 규칙과 smoke(`api/scripts/document_analysis_smoke.py`)는 [문서 분석](docs/DOCUMENT_ANALYSIS.md)에 있습니다.

## 스키마와 DB 종료

JPA는 `ddl-auto: validate`, Flyway는 활성화되어 있습니다. 첫 migration은 당시 설계에 따라 `members`, `member_credentials`, `member_sessions`를 생성합니다. 이어지는 [`V20261013000000__align_auth_identity_with_erd_v6.sql`](src/main/resources/db/migration/V20261013000000__align_auth_identity_with_erd_v6.sql)이 비어 있는 인증 스키마를 [ERD v6](../docs/erd/zoop-core-erd-v6.md)에 맞춰 변경합니다. [`V20261013010000__allow_unselected_member_mode.sql`](src/main/resources/db/migration/V20261013010000__allow_unselected_member_mode.sql)은 가입 직후 온보딩 방식을 고르지 않은 회원을 `members.mode=NULL`로 저장할 수 있도록 합니다. [`V20261013020000__create_terms.sql`](src/main/resources/db/migration/V20261013020000__create_terms.sql)은 약관 항목·버전·동의 기록 테이블과 기간 중복 방지 제약을 만듭니다. [`V20261013030000__register_term_catalog.sql`](src/main/resources/db/migration/V20261013030000__register_term_catalog.sql)은 필수 `service`·`privacy` 마스터만 등록합니다. [`V20261013040000__register_approved_term_versions.sql`](src/main/resources/db/migration/V20261013040000__register_approved_term_versions.sql)은 [공개용 약관](../docs/legal/README.md)의 두 본문을 버전 `2026-10-13.1`로 등록하고 2026-10-13 17:00 KST부터 효력이 생기게 합니다. 적용 후 비밀번호 해시와 회원 설정은 `members`에 있고 `member_credentials`는 없습니다. 대응 Entity는 `com.zoop.auth.entity`에 있습니다. 소셜·관리자 테이블은 아직 없습니다. 후속 스키마 변경은 `src/main/resources/db/migration/`에 Flyway SQL을 추가합니다. 자동 테이블 생성이나 프로토타입 DB 재사용으로 대신하지 않습니다.

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
