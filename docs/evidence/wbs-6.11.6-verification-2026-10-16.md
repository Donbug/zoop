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

동일 테스트를 네이티브 Windows에서 실행했을 때 다음 결과가 발생했다.

| 항목 | 결과 |
|---|---|
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
| NF-API-006 | DB 일시 장애 후 복구 | 전용 장애 주입 필요 | PENDING |
| NF-API-007 | 내부 자료원 장애 | `SOURCE_UNAVAILABLE`, HTTP 503, `retryable=true` 확인 | PASS |
| NF-API-008 | timeout 및 실제 재시도 | retryable 응답 계약만 확인, 실제 재시도는 미검증 | PARTIAL |
| NF-PERF-001 | 응답시간 p50/p95/max | 측정 harness 필요 | PENDING |
| NF-PERF-002 | 동시 요청 C=1/5/10 | 실행 가능한 API 확정 필요 | PENDING |
| NF-WEB-001 | 로딩·빈 데이터·실패 화면 | 프론트 연동 완료 후 검증 | BLOCKED |
| NF-E2E-001 | 실패 후 재시도 및 복구 | 프론트·백엔드 연동 완료 후 검증 | BLOCKED |

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

- 최신 커밋의 API 전체 테스트는 정상 통과했다.
- 네이티브 Windows 실패는 Linux 재검증 결과 환경 차이로 판정했다.
- 현재 코드 회귀 결함은 발견되지 않았다.
- 실제 성능 측정 도구는 아직 저장소에 존재하지 않는다.
- 프론트엔드 및 백엔드 연동과 배포가 완료되지 않아 E2E 및 운영 성능 판정은 보류한다.
- 다음 작업은 실행 가능한 API를 선정하여 장애·예외 case를 개별 검증하는 것이다.