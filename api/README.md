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
| `ZOOP_AUTH_CSRF_ACTIVE_KEY_ID` | 새 회원·비회원 세션의 CSRF 서명 키 ID. 예: `local-v1` |
| `ZOOP_AUTH_CSRF_KEYS` | `키ID=base64url(32바이트 이상)` 목록. 키 회전 중에는 쉼표로 이전 키도 유지 |
| `ZOOP_AUTH_ALLOWED_ORIGINS` | 가입·로그인·비회원 시작 및 회원/비회원 쿠키가 붙은 쓰기 요청을 허용할 정확한 Origin 목록(쉼표 구분). 일반 프로필은 HTTPS만, 로컬 프로필은 loopback HTTP도 허용. 빈 값은 전부 거절 |
| `ZOOP_API_CORS_ALLOWED_ORIGINS` | `/api/**` 전체에 적용할 브라우저 CORS 허용 Origin 목록(쉼표 구분). 비어 있으면 CORS 매핑을 등록하지 않음 |
| `ZOOP_AUTH_TRUSTED_PROXIES` | `X-Forwarded-For`를 제공할 수 있는 프록시의 숫자 IP 목록(쉼표 구분). 빈 값은 전달 헤더 무시 |
| `ZOOP_AI_CLIENT_*` `ZOOP_AI_EXTRACTION_CLIENT_*` `ZOOP_AI_RELATION_CLIENT_*` | 선택. 내부 AI transport 클라이언트(S1/S2/S3 가족별, 기본 비활성, 설정 없이도 기동). 이름·규칙은 [AI 연동](docs/AI_INTEGRATION.md#설정)과 [S2·S3 절](docs/AI_INTEGRATION.md#s2-추출s3-관계-클라이언트) |
| `ZOOP_DOCUMENT_IMPORT_*` `ZOOP_INGESTION_*` `ZOOP_ARTIFACT_ROOT` | 선택. operator 전용 비웹 문서 import(기본 비활성, 설정 없이도 기동). 이름·규칙은 [문서 import](docs/DOCUMENT_IMPORT.md#실행) |
| `ZOOP_DOCUMENT_ANALYSIS_*` | 선택. operator 전용 비웹 문서 분석(기본 비활성, 설정 없이도 기동). S1 AI 클라이언트(`ZOOP_AI_CLIENT_*`)와 위 `ZOOP_INGESTION_*`·`ZOOP_ARTIFACT_ROOT`도 필요하고 문서 import와 한 프로세스에서 함께 켤 수 없습니다. 이름·규칙은 [문서 분석](docs/DOCUMENT_ANALYSIS.md#실행) |
| `ZOOP_DOCUMENT_READ_GRANTS` `ZOOP_DOCUMENT_READ_ARTIFACT_ROOT` | 선택. 공개 `GET /api/v1/evidence/{id}`(운영 플래그와 독립, 읽기 전용). `GRANTS`는 operator의 flat S1 grant registry 파일로 요청마다 읽으며 미설정이면 그 읽기는 503, `ARTIFACT_ROOT`는 캐시로 돌려준 요약의 exact receipt 한 건을 읽을 때만 필요합니다(미설정이면 그 경우만 503). 값이 있는데 정규화된 절대 경로가 아니거나 없으면 기동 실패. 규칙은 [문서 분석 § 근거 읽기](docs/DOCUMENT_ANALYSIS.md#근거-읽기-getevidence-부분-구현) |
| `ZOOP_GRAPH_SNAPSHOT_SOURCE` `ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT` | 선택. 공개 그래프 스냅샷을 어디서 읽을지 정합니다. 기본 `none`: 등록된 버전이 있어도 스냅샷 읽기는 503 `SOURCE_UNAVAILABLE`이고, 버전이 없으면 409 `VERSION_UNAVAILABLE`입니다(빈 그래프로 대체하지 않음). `fixture`: **local/dev 전용**이며, 기동 시 `src/main/resources/graph-fixtures/`의 합성 스냅샷 2개를 `graph_versions`에 등록·활성화합니다(제목 `[합성]`, 실제 뉴스 아님). 이미 가져온(non-fixture) 버전이 있는 DB에서는 기동을 거절합니다. `artifact`: `ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT`(정규화된 절대 경로)의 스냅샷 파일을 레지스트리 hash·크기로 검증해 읽기 전용으로 읽고, 이미 등록된 fixture 버전(classpath 위치)은 기존 fixture 읽기 경로가 그대로 읽어 기존 읽기가 달라지지 않습니다(아래 [그래프 handoff 스테이징 import](#그래프-handoff-스테이징-import)). 어떤 버전을 공개로 보여 줄지는 여전히 선택기와 활성 포인터가 정하며 `artifact`가 등록·활성화하지 않습니다. 규칙은 [그래프 조회 계약 결정](../docs/api/graph-read-contract-proposal.md) §0 |
| `ZOOP_GRAPH_HANDOFF_IMPORT_*` `ZOOP_HANDOFF_*` `ZOOP_RELATION_STATE_DIR` `ZOOP_EXTRACTION_STATE_DIR` | 선택. operator 전용 비웹 그래프 handoff 스테이징 import(기본 비활성, 설정 없이도 기동). 위 `ZOOP_INGESTION_*`·`ZOOP_ARTIFACT_ROOT`도 필요하고 문서 import·분석, `fixture` 소스와 한 프로세스에서 함께 켤 수 없습니다. 이름·규칙은 [그래프 handoff 스테이징 import](#그래프-handoff-스테이징-import) |

`DB_PORT`나 `DB_NAME`을 바꾸면 `DB_URL`도 일치하게 수정하세요. `.env.example`의 비밀번호는 로컬 전용 예시이며 운영용이 아닙니다. 실제 `.env`는 Git에서 제외됩니다. 이미 초기화된 DB 볼륨의 계정·비밀번호는 환경변수만 바꿔도 변경되지 않습니다.

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

`application-local.yml`은 로컬 프로필에서만 `http://localhost:3000` 프론트의 `/api/**` CORS 요청을 허용하고 세션 쿠키의 `Secure` 속성을 끕니다. 인증 Origin 검증에는 프론트와 API에서 직접 여는 Swagger UI의 Origin(`http://localhost:8080`)을 모두 허용합니다. 백엔드 포트를 바꾸면 API Origin도 같은 포트로 지정하세요. 일반 프로필의 HTTPS Origin 검증과 보안 쿠키 설정은 그대로 적용됩니다.

`api/.env.example`의 `ZOOP_AUTH_ALLOWED_ORIGINS`는 빈 값이므로, `.env`를 불러온 **뒤** 로컬 테스트 값을 지정해야 합니다. 다음 명령은 저장소 루트에서 실행합니다.

```sh
set -a
. ./api/.env
set +a
export SPRING_PROFILES_ACTIVE=local
export ZOOP_SWAGGER_ENABLED=true
export ZOOP_AUTH_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080
export ZOOP_API_CORS_ALLOWED_ORIGINS=http://localhost:3000
docker compose --env-file api/.env -f api/compose.local.yaml up -d --wait
./api/gradlew -p api bootRun
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
make pipeline-install api-build api-graph-handoff-import-smoke   # 실제 zoop-ai-handoff/-ingest -> 빌드된 jar -> PostgreSQL 그래프 handoff import smoke (14단계; DB_URL·DB_USERNAME·DB_PASSWORD 필요)
```

`api-graph-handoff-import-smoke`는 합성 데이터만 쓰고 유료 모델·외부 호출과 그래프 활성화(activation)를 하지 않습니다. `DB_URL`(loopback)·`DB_USERNAME`·`DB_PASSWORD`로 **전용 빈 일회용 데이터베이스**를 지정해야 하며(기본값 없음, 문서·그래프 행이 이미 있으면 거절하고 정리하지 않음), 선택적으로 `GRAPH_IMPORT_PSQL_CONTAINER`(docker exec psql), `GRAPH_IMPORT_DB_USER`, `GRAPH_IMPORT_DB_NAME`을 지정합니다. `pipeline-install`·`api-build`는 자동 실행되지 않으며 없으면 실패합니다. 저장된 스냅샷이 형식 3인지와 이슈 period·assertionStatus·mention 참조·대표 mention, 구조 근거의 `basisId`·유형·국가·출처 기사, 미상 유효기간이 `null`로 남는지를 합성 세계에서 손으로 쓴 값과 대조하고, 두 문서가 같은 로컬 mentionId를 쓰는 합법적 생산자 세계(별도 handoff)가 서로 다른 앱 mention id와 올바른 대표 mention으로 등록되고 재시도에도 같은 id·바이트인지 확인하며, 기존 fixture 읽기의 현재 구조 근거(시작 있음·끝 미상)가 `active`로 읽히는지도 확인합니다. 스냅샷 형식이 바뀌면 함께 갱신해야 합니다. CI `api` 잡은 같은 PostgreSQL 서비스에 별도 빈 `zoop_graph_import_smoke` DB를 만들어 실행하며, 기존 `companyIntegrationTest`의 공유 DB는 건드리지 않습니다.

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
  "password": "LocalDemo#2026",
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

## AI 분석 transport

`com.zoop.ai`는 `ai/service`의 internal operation을 호출하는 전송 클라이언트입니다. S1 분석 5개(submit/status/result/cancel/recover)에 더해 S2 추출 job(`ExtractionClient`, 서버 사전 승인 digest 참조) 5개와 S3 관계 job(`RelationClient`, 허용된 upstream과 AI 원천 version·revision을 거는 검수 `review`/`operation`/`recoverOperation` 포함) 8개를 별도 가족으로 호출하며, 가족마다 설정은 독립이고 기본 비활성입니다. 서비스 principal로 호출하며 앱 저장·사용자 격리·결과 import·공개 endpoint·공개 인증은 포함하지 않습니다. 설정, 의미(202≠완료, withheld, 결과 불명 복구), 요청 ID, 검증 범위와 인계 사항은 [AI 연동](docs/AI_INTEGRATION.md)에 있습니다.

## 문서 등록 import

`com.zoop.document`·`com.zoop.artifact`는 FS056의 문서 쪽 저장입니다. 설치된 `zoop-ai-ingest export`의 정제 텍스트를 `artifacts`·`articles`·`article_versions`와 로컬 파일로 등록하는 **operator 전용 비웹 실행**(`--spring.main.web-application-type=none`)이며 HTTP 경로가 없고 평소 기동은 달라지지 않습니다(`V20261014120000`이 세 테이블을 만듭니다). 분석·AI 결과 import·그래프·공개 반영은 이 실행이 하지 않습니다(분석은 아래 별도 실행). 입력 스키마, 결과 파일, 실패 코드, 접근 규칙과 실제 DB smoke(`api/scripts/document_import_smoke.py`)는 [문서 import](docs/DOCUMENT_IMPORT.md)에 있습니다.

## 문서 분석

`com.zoop.document.analysis`는 등록된 문서 버전 하나를 S1 AI 서비스로 요약·기업 판정하고 검증된 결과를 `document_analyses`·`evidence`·`ai_executions`와 artifact 파일에 저장하는 **operator 전용 비웹 실행**입니다(`V20261014130000`). `prepare`는 AI 서비스를 부르지 않고 새 AI jobId와 불변 `ai_submit`을 커밋하며, `advance`는 status를 먼저 읽고(submit·recover 직전에는 현재 grant·article을 다시 확인), 결과를 입력 결속·digest 재계산·검증자가 본 claim 대조·코드 포인트 인용 검사·현재 grant 재평가를 거쳐 한 transaction으로 정산하며, 그 transaction이 article·행 잠금을 얻은 뒤 grant를 한 번 더 평가합니다. 이 실행에는 HTTP 경로·`analysis_jobs`·live 실행이 없습니다(저장된 요약의 인용을 읽는 공개 경로는 아래 `getEvidence` 한 건뿐). 입력 스키마, 결과 파일, 실패 코드, 권리·크래시 규칙과 smoke(`api/scripts/document_analysis_smoke.py`)는 [문서 분석](docs/DOCUMENT_ANALYSIS.md)에 있습니다.

`GET /api/v1/evidence/{id}`(`getEvidence`, 공개 `security: []`)는 저장된 S1 요약의 본문 인용 한 건을 읽는 **부분 구현**입니다(`com.zoop.document.evidence`). 모델·AI 서비스를 호출하지 않고 DB·파일을 쓰지 않으며 요청마다 현재 문서 상태와 현재 grant registry로 다시 판정합니다. 그래프가 없어 `eventIds`는 실패 구역·`graphVersion=null`·`sentiment=null`인 200 부분 응답이고 고정 `round`·`graphVersion`·`asOf`는 409입니다. 규칙·오류·캐시 적중 증명·한계는 [문서 분석 § 근거 읽기](docs/DOCUMENT_ANALYSIS.md#근거-읽기-getevidence-부분-구현)에 있고 `listCompanyDocuments`·GraphDB·승인은 아직 없습니다.

## 그래프 handoff 스테이징 import

`com.zoop.graph.importer`는 AI `zoop-ai-handoff`가 동결한 handoff 하나를 **비활성** 그래프 버전으로 올리는 **operator 전용 비웹 실행**입니다(`--spring.main.web-application-type=none`, `ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED=true`). HTTP 경로가 없고 평소 기동은 달라지지 않으며, 문서 import·분석(같은 artifact 잠금)이나 활성화하는 `fixture` 소스와 한 프로세스에서 켜면 기동이 거절됩니다. 실행은 `graph_activations`를 쓰지 않고 `graph_versions.active`와 article의 `current_version`을 바꾸지 않으므로 공개 API는 이 버전을 읽을 수 없습니다(명시 `graphVersion`은 409 `VERSION_UNAVAILABLE`, 기본·asOf 읽기는 기존 활성 포인터 그대로). **활성화 경로는 아직 없습니다**(결과의 `nextActivation=unsupported`).

요청(`zoop-graph-handoff-import-1`, 닫힌 스키마)은 `handoffId`, 운영자가 고정한 `expectedManifestDigest`·`expectedBundleDigest`(둘 다 필수), `operator`입니다(`created_by=operator:<operator>`, AI 검수 revision이 아닙니다). 실행은 ① 설치된 `zoop-ai-handoff export`의 **현재** 결과(저장 파일이 아님)를 받아 canonical hash 두 개를 직접 다시 계산해 핀과 대조하고, 생산자 `validate_bundle`의 Java 이식으로 bundle 전체(닫힌 스키마·참조 폐쇄·`ev-`/`edge-` 공식·개수·content digest)와 manifest 일치를 검증하며, ② bundle이 기록한 **모든 관측**마다 `zoop-ai-ingest export --require-store`를 새로 실행해(같은 registry·같은 S2-1 원장, `store` 권리 포함) 권리·grant·관측 시각·제목·URL·게시 시각을 대조하고, ③ 한 transaction에서 앱 쪽(article version의 제목·URL·게시 시각 정밀도, 앱 텍스트와 export 텍스트의 byte 일치, 회사 ID·이름)을 검증해 불변 스냅샷·receipt 파일, `artifacts`(`graph_snapshot`·`verification_receipt`), `evidence`, `graph_versions`(inactive, `review_revision` 0, `published_at` 없음)를 등록하고 **commit 직전에 ①②를 다시 실행**합니다(권리가 바뀌면 rollback). id는 `gv-`+SHA-256(handoffId)로 결정되며 같은 핀의 재실행은 `unchanged`, 같은 id의 다른 핀은 `version_conflict`입니다.

스냅샷은 앱의 현재 읽기 형식인 **`snapshotFormat 3`**(`PublicGraphSnapshot`)이며 읽기 투영일 뿐입니다. 이슈에는 생산자의 `period`·이슈 단위 `assertionStatus`(값 그대로, 없으면 null)·`mentions`(mention id와 article id·version)·`representativeMentionId`를, 구조 근거(basis)에는 `basisId`(생산자 `relationKey`)·사업 관계 유형(`SUPPLIES`)·`countries`·`articles`(출처 기사 버전 전부, 없을 수도 있음)·검증 시각·`validFrom`/`validUntil`을 담습니다. `validUntil`은 **마지막 유효일(그날 포함)**이고 `null`은 영구 유효가 아니라 미상이며, 원문 날짜에 자정이나 하루를 더하지 않고 일 단위가 아닌 값은 `temporal_unsupported`로 거절합니다. 공개 조회는 검증 시각이 asOf 이하인 구조 근거를 보이고, 끝난 근거도 지우지 않고 상태(`ended` 등, asOf 또는 요청 시각의 Asia/Seoul 날짜 비교)로 구분합니다. **mention 참조는 전체 source event 목록이 아닙니다.** source event는 그 문서 버전(documentId·documentVersion·rawVersion·관측 위치)이 이슈 자신의 근거가 인용하는 기사 버전일 때만 mention이 되며, 같은 기사 버전·같은 생산자 mentionId를 가진 여러 event(S2 후보와 S2 스냅샷이 함께 담는 경우)는 한 mention입니다. 생산자의 `mentionId`는 문서 버전 안에서만 유일해 서로 다른 문서가 같은 값을 합법적으로 쓰므로, 스냅샷의 mention id는 앱이 `mention-`+SHA-256(canonical JSON `{articleId, articleVersion, sourceMentionId}`, 키는 ASCII 정렬)로 정합니다. 같은 값이 다른 문서에 있어도 두 mention이 따로 남고 같은 입력은 언제나 같은 id를 냅니다. 대표 event도 자신이 속한 기사 버전으로 풀어 같은 식으로 바꾸며 그 mention이 스냅샷에 없으면 `representativeMentionId`는 null입니다. 한 문서 신원이 둘 이상의 bundle 기사와 맞는 경우만 추측하지 않고 `mention_article_ambiguous`로 import 전체를 거절합니다. 스냅샷에 둘 수 없는 source event, 결정, source ref 같은 생산자 필드와 생산자의 원래 mention id는 버리지 않고 `verification_receipt`(원본 manifest·bundle 전체와 앱이 검증한 항목)에 그대로 남습니다. 증거 id는 AI가 제안한 `ev-`+digest 공식을 앱 규칙으로 채택하고(충돌은 `evidence_collision`), 인용은 앱 텍스트의 **코드 포인트** 구간이며 그 UTF-8 SHA-256이 bundle의 `quoteSha256`과 같아야 합니다. `quote_verified`는 이 **인용 무결성**만 뜻하며(의미 검증 아님) 검증 artifact는 receipt입니다. 정밀도를 지키며 쓸 수 없는 시각은 만들어 내지 않고 `temporal_unsupported`로 거절합니다. `getEvidence`는 graph 근거를 읽지 않고(미등록 취급) 공개 제외 오버레이도 이 실행의 범위가 아닙니다. 스테이징된 버전이 있는 DB에서 `fixture` 소스는 기동을 거절합니다.

동시성·재시도 규칙: import의 transaction은 첫 문장으로 회사 카탈로그 테이블 잠금(`LOCK TABLE companies IN SHARE MODE`)을 잡고 commit까지 유지하므로, 한 번 읽은 회사 이름과 "이슈 ID가 카탈로그 회사 ID가 아님" 확인이 commit 시점에도 참입니다. 카탈로그 import도 같은 순서(테이블 잠금 다음 행 잠금)로 잡아 서로를 기다리며 교착하지 않고, 이 대기에는 자체 시간 제한이 없어 상대 transaction이 끝나거나 DB 오류(`database_unavailable`)로 끝납니다. import는 transaction 안에서 사용하는 article 행을 `FOR UPDATE`로 잠그고(`access_status`가 `private`·`deleted`이면 거절) commit 직전 재검사 뒤 같은 잠금 아래에서 상태를 다시 확인하므로, 동시에 들어온 공개 철회는 import의 commit을 기다린 뒤에 적용됩니다. 이미 있는 증거 행은 내용(article·version·텍스트 artifact·인용·구간·locator)과 의미(`input_kind=body`, `offset_unit=unicode_code_point`, 요약 연결 없음, `quote_verified=TRUE`이고 검증 artifact가 graph `verification_receipt`)가 모두 같을 때만 재사용하며 그 밖의 같은 id는 `evidence_collision`입니다(행을 UPDATE로 고치지 않음; 앞선 handoff의 receipt를 검증 artifact로 가진 행은 정상 재사용). 스냅샷의 회사 노드는 bundle이 말하는 `companyId`·`label`만 담고 `brandColor`·`logoUrl`은 선택 외형이므로 카탈로그에서 복사하지도 만들어 내지도 않습니다. 스냅샷 바이트는 검증된 bundle만으로 정해지므로 commit 결과가 불명확했던 시도 뒤의 같은 핀 재시도는 남은 파일을 그대로 채택합니다.

설정은 `application.yml`의 `zoop.graph-handoff-import.*`(요청·결과 파일, `zoop-ai-handoff`·`zoop-ai-ingest` 실행 파일, handoff·relation·extraction·S2-1 상태 디렉터리, **하나의** source registry, 동결에 쓴 canonical·decisions·bindings 파일, artifact root)이며 값이 틀리면 설정 이름만 알리고 기동을 거절합니다. 하위 CLI에는 DB 자격이 전달되지 않습니다. 결과 파일(`0600`, 이미 있으면 덮어쓰지 않음)에는 경로·본문·비밀이 없고 실패 시 프로세스는 0이 아닌 코드로 끝납니다. 스테이징된 스냅샷을 읽으려면 `ZOOP_GRAPH_SNAPSHOT_SOURCE=artifact`와 `ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT`(같은 root)를 씁니다. 실제 CLI·PostgreSQL smoke는 `api/scripts/graph_handoff_import_smoke.py`(파이프라인 venv의 Python으로 실행, 사용법은 파일 머리말)이고 PostgreSQL 통합 시험은 `companyIntegrationTest`에 포함됩니다.

## 기본 기업 카탈로그 적재

`src/main/resources/company/demo-companies.json`은 팀이 확정한 24개 기업 목록입니다. `prototype/` 파일이나 DB를 실행 중에 읽지 않습니다. 종목 코드가 없는 OpenAI·Anthropic은 `ORG:OPENAI`, `ORG:ANTHROPIC` ID를 사용하며 `ticker`, `exchange_code`, `market`은 비워 둡니다. `brand_source`는 색상·로고 출처가 확인된 경우에만 넣고, 단순 홈페이지 주소는 `null`로 둡니다. 향후 GraphDB에서도 같은 회사 ID를 써야 합니다.

DB 환경변수(`DB_URL`, `DB_USERNAME`, `DB_PASSWORD`)를 설정하고 API를 시작하면 Flyway migration `V20261014163000__seed_confirmed_companies.sql`이 **최초 한 번** 24개 기업을 적재하고, `V20261015090000__add_company_brand_source.sql`이 내부 출처 컬럼을 추가합니다. 그 다음 앱 시작 시 번들 JSON을 읽어 같은 기업 ID의 값을 갱신합니다. 이후 JSON을 바꿔 다시 시작해도 ID 기준으로 변경된 행만 갱신하며 중복 삽입하지 않습니다. 다른 기업 및 이를 참조하는 분석 기록은 삭제하지 않습니다. PostgreSQL 컨테이너만 시작하면 Flyway와 JSON 적재가 실행되지 않으므로 API도 시작해야 합니다. Spring Boot는 `.env` 파일을 자동으로 읽지 않습니다.

카탈로그 JSON을 수정해 로컬 DB에 다시 반영할 때에만 `api` 디렉터리에서 명시적 적재 명령을 사용합니다.

```powershell
.\gradlew.bat bootRun --args="--spring.profiles.active=catalog-import --spring.main.web-application-type=none --zoop.catalog.import-file=src/main/resources/company/demo-companies.json"
```

이 수동 명령은 입력 전체를 검증한 뒤 확정 목록을 `companies`에 삽입하거나 같은 ID의 이름·종목 코드·거래소·별칭·브랜드 색상·로고 경로·내부 출처(`brand_source`)를 갱신합니다. `brand_source`의 `null`은 기존 출처를 비우며, 생략하면 기존 값을 보존합니다. 다른 기업은 삭제하지 않습니다. OpenAI·Anthropic의 `market`은 NULL로 바로잡고 다른 기업의 `market`과 `profile`은 보존합니다. 재실행 시 동일한 행은 쓰지 않아 `company_catalog_revision`도 바뀌지 않습니다. 완료 로그의 `total`, `changed`, `unchanged`로 결과를 확인하세요. 기존 Flyway migration은 수정하지 않습니다. 일부 SVG는 프론트엔드가 같은 이름으로 `web/public/graph-assets`에 추가할 예정입니다.

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
