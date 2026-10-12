# Zoop API 실행 환경

Spring Boot 실행 기반과 최소 공통 오류 처리가 있습니다. 업무 API·인증·CI는 아직 구현하지 않았습니다. 기존 프로토타입과 DB를 공유하지 않습니다.

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
# 필요하면 api/.env의 포트·DB 이름·계정 값을 수정합니다.
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

`DB_PORT`나 `DB_NAME`을 바꾸면 `DB_URL`도 일치하게 수정하세요. `.env.example`의 비밀번호는 로컬 전용 예시이며 운영용이 아닙니다. 실제 `.env`는 Git에서 제외됩니다. 이미 초기화된 DB 볼륨의 계정·비밀번호는 환경변수만 바꿔도 변경되지 않습니다.

업무 endpoint는 없으므로 `/`의 404는 정상입니다. 서버 로그의 `Started ZoopApplication`과 DB·Flyway 초기화를 확인하세요. 잘못된 DB 설정에서는 기동이 실패해야 합니다.

## 빌드

```sh
./api/gradlew -p api --version
./api/gradlew -p api clean build
./api/gradlew -p api test
```

현재 빌드와 공통 오류 테스트는 DB 없이 실행할 수 있습니다. 실행 JAR은 `api/build/libs/`에 생성됩니다.

## 공통 오류 처리

`CustomException`에 명세의 `ErrorCode`를 전달하면 `GlobalExceptionHandler`가 `{ "error": { "code", "message", "requestId", "retryable" } }` 형식으로 반환합니다. 현재는 `INVALID_REQUEST`, `RESOURCE_NOT_FOUND`, `INTERNAL_ERROR`만 구현되어 있습니다. 나머지 오류 코드는 해당 기능 구현 시 [목표 OpenAPI](../docs/api/openapi.yaml)에 맞춰 추가합니다. 성공 응답은 공통 래퍼로 감싸지 않습니다.

모든 요청의 `X-Request-ID`를 응답 헤더에 반환하며, 생략하면 서버가 새 ID를 생성합니다. 오류 본문의 `requestId`는 해당 응답 헤더와 같습니다. 요청 ID를 멱등성 키로 사용하지 마세요. 인증 필터의 오류는 추후 인증 구현 시 같은 형식으로 연결해야 합니다.

## 스키마와 DB 종료

JPA는 `ddl-auto: validate`, Flyway는 활성화되어 있습니다. 업무 Entity와 migration은 아직 없습니다. 첫 실제 스키마 변경부터 `src/main/resources/db/migration/`에 Flyway SQL을 추가합니다. 자동 테이블 생성이나 프로토타입 DB 재사용으로 대신하지 않습니다.

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

개발자마다 별도 로컬 DB와 Compose 프로젝트·볼륨을 사용합니다. 테이블과 컬럼은 소문자 `snake_case`, 테이블은 단수형으로 작성하고 JPA 매핑에 이름을 명시합니다. 업무별 테이블 소유자는 해당 기능 담당자입니다. 다른 기능의 테이블·제약·컬럼을 변경할 때는 소유 담당자와 변경 이유·호출 영향을 먼저 합의합니다. 기능 간 외래 키는 삭제 정책과 migration 순서를 함께 검토합니다.

공유 스키마는 `src/main/resources/db/migration/`의 Flyway SQL로 변경합니다. 예: `V20261012153000__create_company.sql`. 타임스탬프는 중복을 피하기 위한 버전 표기이며 이미 적용된 migration을 수정하지 않습니다. 같은 버전의 파일이 병합됐다면 **아직 공유되지 않은** 자신의 migration 이름을 조정하고 새 DB와 기존 DB 양쪽에서 순서대로 적용되는지 확인합니다. 테이블 자동 생성으로 migration을 대신하지 않습니다.

스키마가 바뀌는 PR에는 새 로컬 DB에서 기동되는지, 이전 스키마에 migration을 추가 적용해 기동되는지 적습니다. 기존 개발 데이터가 있는 DB를 테스트 전용 초기화 대상으로 사용하지 않습니다. `down --volumes`는 위의 로컬 개발 DB만 삭제할 때 사용합니다.

## Git 협업과 검증

작업은 [저장소 참여 규약](../CONTRIBUTING.md)의 실제 이슈 번호를 사용하는 기능 브랜치와 PR로 병합합니다. `main`에 직접 push하지 않습니다. 보호 규칙의 실제 활성화 여부는 [GitHub 설정 안내](../docs/development/github-setup.md)를 확인하세요.

본인 기능 패키지를 중심으로 변경하고, `common`, `build.gradle`, `application.yml`, Flyway migration 등 공유 파일의 변경은 PR에 이유와 영향을 적고 관련 담당자에게 알립니다. 계약 변경은 `docs/api/` 정본과 영향을 받는 consumer·fixture·시험을 함께 수정합니다. PR에는 실행한 `./api/gradlew -p api test` 및 `build` 결과와, DB가 필요한 기능이라면 적용 시험 결과를 기록합니다.

현재 API 앱 검사기는 CI·루트 Makefile에 연결되지 않았습니다. 이 연결은 **첫 업무 기능 PR 병합 전**에 완료할 후속 작업이며, 기능 담당자는 기다리지 않고 각자 구현과 로컬 검증을 진행합니다. 인증·CSRF, 커서, 멱등성, 공개 버전, AI 연동, 감사 기록은 각각 필요한 기능의 완료 기준에 포함합니다. 공통 코드 구현을 모두 선행 조건으로 만들지는 않습니다.

| 후속 작업 | 책임 역할 | 완료 시점 |
|---|---|---|
| Gradle 검사 명령을 루트 Makefile·CI job·required gate에 연결 | API 담당 + 저장소 자동화 담당 | 첫 업무 기능 PR 병합 전 |
| 회원·관리자 세션, 권한·Origin·CSRF 오류 처리 | 인증 담당 | 보호가 필요한 업무 API 완료 전 |
| 불투명 커서·공개 버전 고정 | 해당 조회 기능 담당 + 데이터 소유 담당 | 해당 조회 API 완료 전 |
| 쓰기 멱등성·AI 작업 계약·감사 기록 | 해당 쓰기·AI·관리자 기능 담당 | 해당 기능 완료 전 |
