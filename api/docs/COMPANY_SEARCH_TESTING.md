# 기업 검색 API 검증 — 이슈 #39

기준: ERD v6 companies, OpenAPI searchCompanies.
PostgreSQL 기업 카탈로그 검색과 목표 `/api/v1/companies` HTTP 계약을 검증한다. `CompanyIssueCountQuery`는 버전 고정 그래프 이슈 수 경계다. 실제 GraphDB provider가 없으면 응답을 추정하지 않고 `503 SOURCE_UNAVAILABLE`을 반환한다.

## 기본 테스트

Java 21 환경에서 api/를 작업 디렉터리로 사용한다.

    .\gradlew.bat build

검색 단위/API 테스트는 커서 직렬화·조건 변경 거부·catalog revision 무효화,
그래프 snapshot cursor 고정, issueCount 매핑, 누락된 그래프 수 거부, 공통 응답과 요청 ID,
0/음수 limit 및 최대 정수 limit의 lookahead 오버플로 방지를 확인한다.

## PostgreSQL 통합 테스트

Docker Desktop이 실행 중이어야 한다. 아래 컨테이너는 테스트 전용이며 로컬 주소에만 포트를 공개한다.
company_test 사용자와 zoop_company_test_19 데이터베이스를 사용한다.
기존 개발용 .env를 읽지 않으며, 테스트는 이 전용 DB의 기업 데이터를 매 테스트마다 교체한다.

    docker run --rm -d --name zoop-company-test-19 -e POSTGRES_USER=company_test -e POSTGRES_DB=zoop_company_test_19 -e POSTGRES_HOST_AUTH_METHOD=trust -p 127.0.0.1::5432 postgres:16.13-alpine

컨테이너 시작이 성공한 뒤 PowerShell에서 준비 상태와 포트를 확인한다.

    docker exec zoop-company-test-19 pg_isready -U company_test -d zoop_company_test_19
    $companyTestPort = (docker port zoop-company-test-19 5432/tcp).Trim().Split(':')[-1]
    $env:ZOOP_COMPANY_TEST_DB_URL = "jdbc:postgresql://127.0.0.1:$companyTestPort/zoop_company_test_19"
    .\gradlew.bat companyIntegrationTest

테스트는 실제 애플리케이션을 웹 서버 없이 시작해 Flyway migration과 JPA validate도 수행한다.
연결 URL이 지정되지 않거나 전용 로컬 DB 경로가 아니면 실패한다. 테스트를 자동으로 건너뛰지 않는다.

- 빈 DB에 전체 migration 적용 및 검색 인덱스 확인
- 별도 schema에서 기존 인증 migration → 기업 migration 업그레이드, 재실행 무변경 확인
- NFKC·Unicode 양끝 공백 제거·소문자화, 내부 공백과 문장부호 보존
- ID/티커 정확 일치 → 이름 정확 일치 → 별칭/부분 일치, 이름/ID 정렬
- 1~2자 검색어, ID/티커 부분 일치, 검색 결과 없음
- %, _, 역슬래시의 리터럴 검색과 별칭 결합 경계 오탐 제거
- INSERT/UPDATE 시 검색 컬럼 trigger 갱신
- 거래소+티커 UNIQUE와 거래소가 다른 동일 티커
- 전체 목록과 검색 결과의 커서 페이지 누락·중복 방지
- 실제 PostgreSQL에서 최대 정수 limit 및 잘못된 커서 처리

모든 회사·버전 값은 합성 데이터다. GraphDB 데이터나 공개 API 응답을 검증한 결과로 해석하지 않는다.
통합 테스트는 별도 companyIntegrationTest 태스크이며 기본 build에는 포함되지 않는다.
GitHub Actions의 api job은 PostgreSQL 16.13 서비스의 준비 상태를 확인한 뒤 이 태스크를 실행한다.
서비스의 동적 포트를 ZOOP_COMPANY_TEST_DB_URL로 전달하며 실패하면 api job과 required-ci도 실패한다.
기업 migration의 적용 성공과 각 필수 인덱스의 키·방식·유일성·부분 조건·유효 상태를 검사한다.

확인 후 전용 컨테이너를 정리한다. --rm으로 실행했으므로 컨테이너 데이터도 제거된다.

    docker stop zoop-company-test-19
    Remove-Item Env:\ZOOP_COMPANY_TEST_DB_URL

결과는 build/reports/tests/test/index.html과
build/reports/tests/companyIntegrationTest/index.html에서 확인할 수 있다.

## 카탈로그 변경과 커서 재시작

커서는 PostgreSQL의 `company_catalog_revision.revision`에도 결합한다.
이 테이블은 페이지 일관성만을 위한 내부 메타데이터이며 GraphDB의 graphVersion/asOf와 독립적이다.
companies의 INSERT/UPDATE/DELETE/TRUNCATE 문장은 같은 트랜잭션에서 revision을 증가시킨다.
롤백된 변경은 revision도 되돌아간다. 행에 영향이 없는 쓰기 문장도 보수적으로 커서를 무효화한다.
메타데이터를 직접 수정하거나 trigger를 끄는 적재 방식은 지원하지 않는다.

검색 호출은 별도의 REPEATABLE READ 트랜잭션에서 revision과 결과를 함께 읽는다.
첫 스냅샷 읽기 전에 ACCESS SHARE 잠금을 잡아 PostgreSQL의 TRUNCATE와 충돌하도록 한다.
일반 INSERT/UPDATE/DELETE는 조회와 병행할 수 있다. 쓰기 트랜잭션들은 revision 행 갱신 시 직렬화된다.
외부 트랜잭션이 있으면 REQUIRES_NEW로 별도 연결을 사용하므로 연결 풀 용량을 고려해야 한다.

페이지 사이에 revision이 달라지면 `INVALID_CURSOR`로 거절하고 커서 없이 다시 검색한다.
revision이 없는 이전 형식의 커서도 같은 오류로 거절한다. HTTP 오류 본문은 OpenAPI 공통 오류 형식과
`X-Request-ID`를 사용한다. 그래프 count adapter가 없는 상태는 0건으로 위장하지 않고 `SOURCE_UNAVAILABLE`로 처리한다.
통합 테스트는 반환된/미반환 회사 이름 변경, 추가·삭제·전체 비우기, 별칭·티커 변경,
롤백, 다른 연결의 커밋 중 스냅샷 유지 및 재시작 후 전체 페이지 순회를 확인한다.

## 검색 DEBUG 로그 사용

PowerShell에서 아래 환경변수를 설정하면 기업 검색 시작과 정상 완료 로그가 출력된다.
시작 로그는 limit와 커서 존재 여부, 완료 로그는 반환 개수·다음 페이지 여부·소요 시간을 담는다.
검색어와 커서 원문은 기록하지 않는다. 실패한 호출에는 정상 완료 로그가 출력되지 않는다.

    $env:LOGGING_LEVEL_COM_ZOOP_COMPANY = 'DEBUG'

위 테스트 DB 연결 설정 후, Gradle이 테스트의 콘솔 출력도 표시하도록 실행한다.

    .\gradlew.bat companyIntegrationTest --info --console=plain

일반 애플리케이션도 같은 환경변수를 설정한 뒤 bootRun으로 실행하면 된다.
서버 시작만으로 검색 로그가 발생하지는 않으며 검색 서비스가 호출되어야 한다.
확인 후 아래 명령으로 해제하면 다음 실행부터 기본 로그 수준을 사용한다.

    Remove-Item Env:\LOGGING_LEVEL_COM_ZOOP_COMPANY
