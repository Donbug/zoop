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
| NF-API-003 | 인증되지 않은 세션 조회 | anonymous 응답 계약 확인, 보호 API는 별도 검증 필요 | PARTIAL |
| NF-API-004 | 권한 없는 관리자 요청 | 관리자 인증 구현 상태 확인 필요 | BLOCKED |
| NF-API-005 | 잘못된 요청값 | 잘못된 `asOf`, 빈 `companyId`, 잘못된 cursor의 422 확인 | PASS |
| NF-API-006 | DB 일시 장애 후 복구 | PostgreSQL 중단 시 500 응답 확인, DB 재시작 후 API 재시작 없이 200 복구 | PARTIAL |
| NF-API-007 | 내부 자료원 장애 | `SOURCE_UNAVAILABLE`, HTTP 503, `retryable=true` 확인 | PASS |
| NF-API-008 | timeout 및 실제 재시도 | retryable 응답 계약만 확인, 실제 재시도는 미검증 | PARTIAL |
| NF-API-009 | DB 장애 응답 계약 | `INTERNAL_ERROR`, HTTP 500, `retryable=false`, 약 30초 응답 확인 | OBSERVED |
| NF-PERF-001 | 응답시간 p50/p95/max | 측정 harness 필요 | PENDING |
| NF-PERF-002 | 동시 요청 C=1/5/10 | 실행 가능한 API 확정 필요 | PENDING |
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

## 6. 성능 측정 준비 기준

운영 성능 기준은 아직 승인되지 않았다. 아래 값은 로컬 측정 준비를 위한 제안값이며 운영 SLO로 사용하지 않는다.

| 항목 | 로컬 준비값 |
|---|---|
| 동시 요청 | C=1, 5, 10 |
| 사용자별 in-flight | 1개 |
| warmup | 단계별 60초 |
| 측정 시간 | 단계별 300초 |
| 반복 | 동일 조건 2회 |
| 일반 HTTP timeout | 10초 |
| 결과값 | p50, p95, max |
| 추가 집계 | 성공, 실패, timeout, 누락 |
| 비AI 일반 읽기 제안 p95 | 1초 이하 |
| graph/timeline 제안 p95 | 2초 이하 |
| 비동기 작업 접수 제안 p95 | 1초 이하 |

실제 측정 전 다음 항목을 확정해야 한다.

- 측정 대상 API
- 합성 데이터 규모
- 캐시 cold/warm 조건
- 서버 worker 수
- CPU 및 RAM
- DB 상태와 인덱스
- 성공 응답의 정의
- 예상 실패 응답의 정의

## 7. 현재 결론

- 기준 커밋 `f28ff16bcb941657004fb646a9cedb87a3e40dee`의 API 전체 테스트는 정상 통과했다.
- 네이티브 Windows 실패는 Linux 재검증 결과 환경 차이로 판정했다.
- 현재 코드 회귀 결함은 발견되지 않았다.
- 실제 성능 측정 도구는 아직 저장소에 존재하지 않는다.
- 프론트엔드 및 백엔드 연동과 배포가 완료되지 않아 E2E 및 운영 성능 판정은 보류한다.
- PostgreSQL 중단 시 약관 조회 API는 약 30초 후 HTTP 500과 `retryable=false`를 반환했다.
- PostgreSQL 재시작 후 API를 재시작하지 않아도 동일 요청이 HTTP 200으로 자동 복구됐다.
- DB 장애 응답을 HTTP 503과 재시도 가능한 오류로 처리할지 팀 검토가 필요하다.
- 다음 작업은 DB 장애 응답 계약과 timeout 정책을 검토하고, 보호 API 및 실제 재시도 동작을 추가 검증하는 것이다.
