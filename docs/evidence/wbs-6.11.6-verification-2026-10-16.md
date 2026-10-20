# WBS 6.11.6 성능·장애·예외 처리 검증 결과

## 1. 기본 정보

| 항목 | 내용 |
|---|---|
| WBS | 6.11.6 |
| GitHub Issue | #151 |
| 담당자 | 안재현 |
| 검증일 | 2026-10-16 |
| 브랜치 | `test/151-nonfunctional-verification` |
| 검증 커밋 | `f28ff16bcb941657004fb646a9cedb87a3e40dee` |
| 현재 상태 | 진행 중 |
| 대상 | `api/` |
| 외부 유료 API 호출 | 없음 |
| 실제 사용자 데이터 사용 | 없음 |

이 문서는 로컬 합성 환경에서 수행한 비기능 검증 결과를 기록한다.
현재 프론트엔드와 백엔드 기능 및 실제 배포 환경이 완성되지 않았으므로
운영 성능과 운영 장애 복구의 최종 합격을 의미하지 않는다.

## 2. 검증 환경

| 항목 | 값 |
|---|---|
| Host OS | Windows 11 |
| 컨테이너 실행 환경 | Docker Desktop |
| 테스트 OS | Ubuntu Jammy 기반 Linux 컨테이너 |
| Java | Eclipse Temurin JDK 21 |
| 테스트 이미지 | `eclipse-temurin:21-jdk-jammy` |
| Gradle | 9.7.1 |
| Database | PostgreSQL 16.13 Alpine |
| DB 서비스 | `api/compose.local.yaml`의 `postgres` |
| DB 연결 | Docker 네트워크 내부 `postgres:5432` |
| 네트워크 | `zoop-api-local_default` |

## 3. API 전체 테스트 결과

### 실행 명령

```bash
bash ./gradlew test
```

환경변수는 다음과 같이 테스트 컨테이너에 주입했다.

```text
DB_URL=jdbc:postgresql://postgres:5432/zoop
DB_USERNAME=zoop
DB_PASSWORD=<local test value>
```

실제 비밀번호 값은 검증 문서와 로그에 기록하지 않는다.

### 실행 결과

| 항목 | 결과 |
|---|---|
| Gradle task | `test` |
| 결과 | PASS |
| 빌드 결과 | `BUILD SUCCESSFUL` |
| 실행 시간 | 2분 14초 |
| 실행 task | 5개 |
| PostgreSQL 연결 | 정상 |
| Flyway 및 JPA 초기화 | 정상 |
| HikariCP 종료 | 정상 |
| 코드 수정 후 통과 여부 | 코드 수정 없이 통과 |

### 판정

현재 커밋의 API 전체 단위·회귀 테스트는 Linux 컨테이너 및 로컬 PostgreSQL 환경에서 정상 통과했다.

이 결과는 API 테스트 회귀가 없다는 로컬 증거이며 다음 항목을 증명하지는 않는다.

- 실제 AWS 배포 환경의 성능
- 운영 데이터 규모의 처리량
- 프론트엔드와 API 간 E2E 동작
- 외부 공급자 또는 실제 AI 모델 장애 복구
- 운영 환경의 p50, p95, max 응답시간
- 운영 환경의 오류율과 timeout 비율

## 4. Windows 실행 실패 분석

이전 커밋 `71ff60214ab417c3e3deb7c41f958f96f4cc46a6`에서 동일 명령을 네이티브 Windows로 실행했을 때 다음 결과가 발생했다.

| 항목 | 결과 |
|---|---|
| 실행 커밋 | `71ff60214ab417c3e3deb7c41f958f96f4cc46a6` |
| 전체 테스트 | 427개 |
| 실패 | 210개 |
| 주요 예외 | `ConnectException` |
| 파일 관련 예외 | `UnsupportedOperationException` |
| 저장소 관련 예외 | `ArtifactStoreException` |

### 원인 분류

1. PostgreSQL이 실행되지 않은 상태에서 DB 기반 테스트가 실행되어 `ConnectException`이 발생했다.
2. Artifact 및 Document 관련 테스트가 POSIX 파일 권한과 실행 권한을 검사한다.
3. 네이티브 Windows 파일 시스템에서는 해당 POSIX 동작을 동일하게 지원하지 않아 연쇄 실패가 발생했다.
4. PostgreSQL을 실행하고 Linux 파일 시스템 내부로 소스를 복사하여 다시 실행한 결과 전체 테스트가 통과했다.

따라서 현재 확인된 Windows 실패는 애플리케이션 회귀 결함으로 분류하지 않고 테스트 실행 환경 차이로 기록한다.

## 5. 장애·예외 검증 현황

| Case ID | 검증 항목 | 검증 근거 | 상태 |
|---|---|---|---|
| NF-API-001 | API 전체 단위·회귀 테스트 | Linux에서 `./gradlew test` 전체 통과 | PASS |
| NF-ENV-001 | PostgreSQL 미기동 | `ConnectException` 발생 확인 | OBSERVED |
| NF-ENV-002 | Windows POSIX 권한 미지원 | 파일 관련 테스트 연쇄 실패 확인 | OBSERVED |
| NF-ENV-003 | Linux POSIX 환경 재검증 | 코드 수정 없이 전체 통과 | PASS |
| NF-API-002 | 빈 데이터·null 응답 | `SessionControllerTest`, `EvidenceControllerTest` | PASS |
| NF-API-003 | 인증되지 않은 사용자의 보호 API 접근 | `GET /api/v1/me/settings` 호출 시 HTTP 401, `AUTH_REQUIRED` 확인 | PASS |
| NF-API-004 | 권한 없는 관리자 요청 | 관리자 인증 구현 상태 확인 필요 | BLOCKED |
| NF-API-005 | 잘못된 요청값 | 잘못된 `asOf`, 빈 `companyId`, 잘못된 cursor의 422 확인 | PASS |
| NF-API-006 | DB 일시 장애 후 복구 | PostgreSQL 중단 시 500 응답 확인, DB 재시작 후 API 재시작 없이 200 복구 | PARTIAL |
| NF-API-007 | 내부 자료원 장애 | `SOURCE_UNAVAILABLE`, HTTP 503, `retryable=true` 확인 | PASS |
| NF-API-008 | timeout 및 재시도 정책 | retryable 응답과 Retry-After를 보존하고, POST 및 결과 불명 timeout을 자동 재시도하지 않음을 테스트로 확인 | PASS |
| NF-API-009 | DB 장애 응답 계약 | `INTERNAL_ERROR`, HTTP 500, `retryable=false`, 약 30초 응답 확인 | OBSERVED |
| NF-API-010 | 게스트의 회원 전용 API 접근 | 게스트 세션 생성 후 `GET /api/v1/me/settings` 호출 시 HTTP 403, `MEMBER_REQUIRED` 확인 | PASS |
| NF-PERF-001 | 응답시간 p50/p95/max | 로컬 k6 측정 결과 전체 회차 p95 27.14ms 이하, HTTP 실패 0건 | PASS |
| NF-PERF-002 | 동시 요청 C=1/5/10 | C=1·5·10에서 각각 300초씩 2회 측정 완료 | PASS |
| NF-WEB-001 | 로딩·빈 데이터·실패 화면 | 프론트 연동 완료 후 검증 | BLOCKED |
| NF-E2E-001 | 실패 후 재시도 및 복구 | 프론트·백엔드 연동 완료 후 검증 | BLOCKED |

### DB 일시 장애 및 자동 복구 검증

#### 검증 정보

| 항목 | 값 |
|---|---|
| 실행 브랜치 | `test/151-db-recovery` |
| 실행 커밋 | `fedec002a262ca26d7c0118ef71489eba9b6428b` |
| 대상 API | `GET /api/v1/auth/terms` |
| 애플리케이션 실행 환경 | 네이티브 Windows |
| Java | Eclipse Temurin JDK 21 |
| 데이터 접근 | `JdbcTermRepository`의 PostgreSQL 조회 |
| DB 연결 | `localhost:5432` |
| 장애 주입 | PostgreSQL 컨테이너 중단 |
| 복구 방법 | PostgreSQL 컨테이너 재시작 |
| API 재시작 | 하지 않음 |
| 데이터 변경 | 없음 |
| 외부 API 호출 | 없음 |

API 실행에 필요한 CSRF 키는 로컬 PowerShell 세션에서만 임시 생성해 주입했다.
키 값은 파일, 로그 및 Git 저장소에 기록하지 않았다.

#### 정상 상태

PostgreSQL이 정상인 상태에서 약관 조회 API를 호출했다.

| 항목 | 결과 |
|---|---|
| PostgreSQL 상태 | `healthy` |
| HTTP 상태 | 200 |
| 응답시간 | 864.29ms |
| 조회 결과 | 약관 2개 |
| `nextCursor` | `null` |
| 판정 | PASS |

첫 요청에서 측정된 43초대 값은 PowerShell 보안 확인 입력 대기 시간이 포함된 값이므로 측정 결과에서 제외했다.

#### 장애 주입 결과

실행 중인 API는 유지하고 PostgreSQL 컨테이너만 중단한 뒤 동일 API를 호출했다.

```powershell
docker compose --env-file api/.env.example -f api/compose.local.yaml stop postgres
```

| 항목 | 결과 |
|---|---|
| PostgreSQL 상태 | `Exited (0)` |
| HTTP 상태 | 500 |
| 응답시간 | 30.0564초 |
| 오류 코드 | `INTERNAL_ERROR` |
| `retryable` | `false` |
| request ID | `c9cb7f00-569e-486d-9f6f-2ed6918b0a76` |

DB 중단 시 요청 실패는 감지됐지만 약 30초 후 일반 내부 오류로 응답했다. 일시적인 DB 장애임에도 HTTP 503이 아닌 500이 반환됐고, 클라이언트가 재시도할 수 있는 상황임에도 `retryable=false`가 반환됐다.

#### 자동 복구 결과

API 프로세스를 종료하거나 재시작하지 않은 상태에서 PostgreSQL 컨테이너만 다시 시작했다.

```powershell
docker compose --env-file api/.env.example -f api/compose.local.yaml start postgres
```

| 항목 | 결과 |
|---|---|
| PostgreSQL 상태 | `healthy` |
| `healthy` 확인까지 측정값 | 약 10.01초 |
| API 재시작 | 하지 않음 |
| 복구 후 HTTP 상태 | 200 |
| 복구 후 응답시간 | 74.993ms |
| 복구 후 조회 결과 | 약관 2개 |
| 판정 | PASS |

`healthy` 확인 시간에는 수동 명령 실행 및 확인 전환 시간이 포함돼 있으므로 정밀한 DB 기동 성능 지표로 사용하지 않는다.

PostgreSQL 복구 후 애플리케이션을 재시작하지 않아도 HikariCP가 사용 가능한 연결을 다시 확보하고 동일 API가 정상 응답했다.

#### 판정

- DB 중단에 따른 요청 실패는 정상적으로 관찰됐다.
- PostgreSQL 재시작 후 API 재시작 없이 DB 연결이 자동 복구됐다.
- 데이터 손실이나 변경은 발생하지 않았다.
- DB 장애 중 응답이 HTTP 500과 `retryable=false`로 반환되는 점은 개선이 필요하다.
- 약 30초의 장애 응답시간은 timeout 정책과 함께 재검토해야 한다.
- 자동 복구는 PASS이지만 장애 응답 계약이 보완되지 않아 NF-API-006의 전체 상태는 PARTIAL로 판정한다.
### 보호 API 인증·회원 권한 검증

#### 검증 정보

| 항목 | 값 |
|---|---|
| 검증일 | 2026-10-17 |
| 실행 브랜치 | `main` |
| 실행 커밋 | `694ae4349e0914c3344f9a69ec942a3da1b7857d` |
| 대상 API | `GET /api/v1/me/settings` |
| 게스트 생성 API | `POST /api/v1/auth/guest` |
| 보호 방식 | `MemberAuthorizationInterceptor` |
| 보호 경로 | `/api/v1/me/**` |
| 데이터 | 로컬 합성 세션 |
| 실제 사용자 데이터 | 없음 |
| 외부 API 호출 | 없음 |

#### 기존 자동화 테스트

다음 인증 경계 테스트를 실행했다.

```powershell
.\api\gradlew.bat -p api test `
  --tests "com.zoop.auth.controller.MemberAuthorizationInterceptorTest" `
  --tests "com.zoop.auth.controller.AuthRequestBoundaryTest"
```

| 항목 | 결과 |
|---|---|
| 빌드 결과 | `BUILD SUCCESSFUL` |
| 실행 시간 | 41초 |
| 정상 회원 principal 부착 | PASS |
| 게스트 세션 거부 | PASS |
| 중복 세션 쿠키 거부 | PASS |
| 인증 요청 경계 검사 | PASS |

#### 익명 사용자 검증

세션 쿠키 없이 회원 설정 조회 API를 호출했다.

| 항목 | 결과 |
|---|---|
| HTTP 상태 | 401 |
| 오류 코드 | `AUTH_REQUIRED` |
| `retryable` | `false` |
| 응답시간 | 158.868ms |
| 판정 | PASS |

#### 게스트 사용자 검증

허용된 로컬 Origin에서 게스트 세션을 생성한 뒤 해당 세션으로 회원 설정 조회 API를 호출했다.

| 항목 | 결과 |
|---|---|
| 게스트 생성 HTTP 상태 | 200 |
| 게스트 생성 응답시간 | 248.573ms |
| 세션 종류 | `guest` |
| 보호 API HTTP 상태 | 403 |
| 오류 코드 | `MEMBER_REQUIRED` |
| `retryable` | `false` |
| 보호 API 응답시간 | 25.871ms |
| 판정 | PASS |

인증 관련 POST 요청은 `ZOOP_AUTH_ALLOWED_ORIGINS`가 비어 있으면
HTTP 403 `ACCESS_DENIED`로 거부됐다. 로컬 검증용 Origin을 명시적으로
허용한 후에만 게스트 세션이 정상 생성됐다. 이는 인증 요청의 Origin
경계가 기본 거부 방식으로 적용되고 있음을 보여준다.

이번 검증으로 익명 사용자와 게스트가 회원 전용 API에 접근할 수 없음을
확인했다. 차단 회원, 타 회원 자원 소유권 불일치 및 관리자 권한은 별도
검증 대상으로 유지한다.

### AI 요청 timeout 및 재시도 정책 검증

#### 검증 정보

| 항목 | 값 |
|---|---|
| 실행 브랜치 | `test/151-performance-retry-verification` |
| 실행 커밋 | `64e42ac67dde7492dc5e862ef2f352805ac3f0b0` |
| 검증 대상 | AI 분석 및 추출 HTTP 클라이언트 |
| 검증 방식 | 로컬 Stub AI 서버를 이용한 단위 테스트 |
| 외부 AI 호출 | 없음 |
| 실제 사용자 데이터 사용 | 없음 |
| 테스트 결과 | `BUILD SUCCESSFUL` |
| 실행 시간 | 23초 |

#### 검증한 테스트

| 테스트 | 검증 내용 | 결과 |
|---|---|---|
| `retryableRefusalKeepsRetryAfterAndRuntimeCodeAndFieldAndIsNeverRetried` | HTTP 503의 `retryable`, `Retry-After`, 오류 정보를 보존하고 요청 횟수가 1회인지 확인 | PASS |
| `timeoutIsBoundedExplicitUnknownAndNotRetried` | AI 분석 요청 timeout을 제한된 시간 안에 종료하고 자동 재시도하지 않는지 확인 | PASS |
| `aSlowServiceIsATimeoutThatMayHaveRegisteredTheJobAndIsNeverRetried` | 추출 요청이 서버에 등록됐을 가능성이 있는 timeout에서 중복 POST를 수행하지 않는지 확인 | PASS |

#### 판정

현재 AI HTTP 클라이언트에는 Spring Retry, Resilience4j, `RetryTemplate`, `@Retryable` 기반의 자동 재시도가 구현돼 있지 않다.

`retryable=true`는 요청을 즉시 반복한다는 의미가 아니라 호출자에게 전달되는 재시도 가능성 정보다. 특히 AI 작업 생성과 같은 POST 요청은 timeout이 발생해도 서버에 작업이 등록됐을 가능성이 있으므로 자동 재시도를 수행하면 중복 작업이 생성될 수 있다.

테스트에서는 retryable HTTP 503 및 결과가 불명확한 timeout 상황에서도 Stub 서버가 받은 요청이 1회임을 확인한다. 따라서 현재 계약은 오류 정보와 `Retry-After`를 보존하되 부작용 가능성이 있는 요청을 자동 재시도하지 않는 것이다.

이 검증은 자동 재시도가 발생하는지를 확인한 것이 아니라, 중복 작업 방지를 위해 자동 재시도를 하지 않는 정책이 지켜지는지를 확인한 결과다. 실제 외부 AI 서비스와의 운영 장애 복구 및 조회 요청의 호출자 측 backoff 재시도는 배포 환경에서 별도로 검증해야 한다.

### 기존 테스트 추적

- `SessionControllerTest`
  - 세션 쿠키가 없는 요청의 anonymous 응답을 확인한다.
  - `user`, `setup`, `csrfToken`이 `null`인지 확인한다.
  - 잘못된 세션 쿠키를 제거하는 응답을 확인한다.
- `EvidenceControllerTest`
  - 빈 `eventIds` 배열과 nullable 필드 직렬화를 확인한다.
  - 없는 근거와 기업에 대한 404 응답을 확인한다.
  - 지원하지 않는 버전 조건에 대한 409 응답을 확인한다.
  - 잘못된 날짜와 빈 기업 ID에 대한 422 응답을 확인한다.
  - 내부 자료원 장애에 대한 503 및 `retryable=true`를 확인한다.
- `TermControllerTest`
  - 잘못된 cursor와 범위를 벗어난 timestamp가 500이 아닌 422 오류로 처리되는지 확인한다.

## 6. 로컬 성능 측정 결과

### 검증 정보

| 항목 | 값 |
|---|---|
| 실행 브랜치 | `test/151-performance-retry-verification` |
| 실행 커밋 | `2df9e31740c8c954268aa0b8add379dfc7385f82` |
| 측정일 | 2026-10-17 |
| 대상 API | `GET /api/v1/auth/terms` |
| 부하 도구 | k6 2.2.0 |
| 실행 환경 | Windows 네이티브 k6 |
| API 주소 | `http://localhost:8080` |
| 데이터베이스 | 로컬 Docker PostgreSQL |
| 스크립트 | `api/scripts/performance/terms-paced-baseline.js` |
| 응답 본문 보관 | 하지 않음 |
| 외부 유료 API 호출 | 없음 |
| 실제 사용자 데이터 사용 | 없음 |

### 측정 조건

| 항목 | 조건 |
|---|---|
| 동시 사용자 | C=1, 5, 10 |
| 사용자별 동작 | 요청 완료 후 1초 대기 |
| 사용자별 in-flight 요청 | 최대 1개 |
| 사전 워밍업 | 단계별 60초 |
| 정식 측정 시간 | 단계별 300초 |
| 반복 횟수 | 각 동시 사용자 조건에서 2회 |
| 요청 timeout | 15초 |
| 성공 조건 | HTTP 200 |
| 오류 허용 기준 | HTTP 실패율 0% |
| 로컬 응답시간 기준 | p95 1초 이하 |

각 가상 사용자는 약관 조회 요청이 완료된 후 1초를 대기한다. 따라서 이 측정은 최대 처리량 시험이 아니라 일정한 사용자 요청 간격을 적용한 로컬 동시 사용자 기준선이다.

### 실행 명령

```powershell
$env:BASE_URL = "http://localhost:8080"
$env:VUS = "5"
$env:DURATION = "300s"

& "C:\Program Files\k6\k6.exe" run `
  api/scripts/performance/terms-paced-baseline.js
```

`VUS` 값을 `1`, `5`, `10`으로 변경하여 각 조건을 2회 측정했다.

## 7. 현재 결론

- 기준 커밋 `f28ff16bcb941657004fb646a9cedb87a3e40dee`의 API 전체 테스트는 정상 통과했다.
- 네이티브 Windows에서 발생한 테스트 실패는 Linux 컨테이너 재검증 결과 실행 환경 차이로 판정했다.
- 현재까지 애플리케이션 코드의 회귀 결함은 발견되지 않았다.
- PostgreSQL 중단 시 약관 조회 API는 약 30초 후 HTTP 500과 `retryable=false`를 반환했다.
- PostgreSQL 재시작 후에는 API를 재시작하지 않아도 동일 요청이 HTTP 200으로 자동 복구됐다.
- 인증되지 않은 사용자의 회원 전용 API 접근은 HTTP 401과 `AUTH_REQUIRED`로 차단됐다.
- 게스트 사용자의 회원 전용 API 접근은 HTTP 403과 `MEMBER_REQUIRED`로 차단됐다.
- 재현 가능한 k6 로컬 성능 측정 스크립트를 `api/scripts/performance/terms-paced-baseline.js`에 추가했다.
- `GET /api/v1/auth/terms`를 C=1·5·10에서 각각 300초씩 2회 측정했으며 전체 9,500건의 요청이 성공했다.
- 정식 성능 측정의 HTTP 실패율은 0%였으며 가장 높은 p95는 27.14ms였다.
- NF-PERF-001과 NF-PERF-002는 로컬 검증 범위에서 PASS로 판정한다.
- 프론트엔드와 백엔드 연동 및 실제 배포가 완료되지 않아 E2E와 AWS 운영 성능 판정은 보류한다.
- DB 장애 응답을 HTTP 503과 재시도 가능한 오류로 처리할지 팀 검토가 필요하다.
- 다음 작업은 DB 장애 응답의 HTTP 503·timeout 정책을 팀과 검토하고, 실제 배포 후 외부 서비스 장애 및 E2E 복구 동작을 검증하는 것이다.
- AI HTTP 클라이언트는 retryable 응답과 `Retry-After`를 보존하지만 부작용 가능성이 있는 POST와 결과 불명 timeout은 자동 재시도하지 않는다.
- 관련 단위 테스트 3개가 통과했으며 NF-API-008은 현재 재시도 정책 검증 범위에서 PASS로 판정한다.
