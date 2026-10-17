# 공개 브리핑 DB·HTTP·화면 연결

공개 브리핑 화면은 Spring API가 PostgreSQL에 보존된 회차 원문을 읽어 응답하는 구조다. 조회 시 뉴스·시세·AI를 다시 호출하거나 최신 결과로 발행 원문을 바꾸지 않는다. 현재 생성 시작 기준은 **09:20·17:30 KST**다.

## 공개 API

| GET | 동작 |
|---|---|
| `/api/v1/briefings?date=2026-10-15&edition=evening` | 지정 회차의 상태·저장된 내용·시장 지표·퇴근 비교·정정을 제공한다. 날짜를 생략하면 해당 구분의 최신 **DB 저장 회차**를 찾는다. 저장 회차가 없으면 `not_ready`를 반환하며 행을 만들지 않는다. |
| `/api/v1/briefings/rounds?limit=20` | 발행·제공 중단 회차의 메타데이터를 최신순으로 제공한다. `nextCursor`와 같은 `limit`으로 다음 페이지를 요청한다. 본문이나 원천 권한 파일을 읽지 않는다. |
| `/api/v1/briefings/{id}/graph` | 저장된 발행 버전과 데이터 기준 시각을 제공한다. 실제 고정 그래프 조회 담당이 아직 연결되지 않아 정상 발행본도 `unavailable`이며 두 ID 배열은 비어 있다. 최신 그래프로 대체하지 않는다. |

세 경로는 회원 세션 없이 읽을 수 있다. 잘못된 날짜·구분·범위는 `422 INVALID_REQUEST`, 잘못된 커서는 `422 INVALID_CURSOR`, 없는 그래프 기준 회차는 `404 RESOURCE_NOT_FOUND`다. DB 장애·저장 원문 불일치·현재 권한 확인 불가 시 `503 SOURCE_UNAVAILABLE`이며 공개 내용을 반환하지 않는다. 제공 중단 회차에는 실제 중단 사유와 상태만 제공한다.

API 실행 시 `ZOOP_SWAGGER_ENABLED=true`이면 `/swagger-ui.html`과 `/v3/api-docs`에서 세 operation과 응답 스키마를 확인할 수 있다. 기본 실행·인증 키·CORS 설정은 [API README](../README.md#로컬-http-브라우저-테스트)를 따른다.

## 저장·권한 계약

후속 migration `V20261017230000__create_briefing_read_storage.sql`이 `briefing_rounds`와 `briefing_changes`를 추가한다. 기존 적용 migration 및 공통 `artifacts`·문서 등록부를 변경하지 않는다.

- `published_payload`: 발행 당시 `BriefingPayload`. 회차·창·버전·이슈 최대 3개·필수 중첩 구조를 검증한다. 공개 후 원문·창·비교 결과는 불변이다.
- `public_snapshot.marketSummary`: 발행 당시 실제 시장 요약 또는 생산자가 없다는 `unavailable` 사유. 조회 시 생성하지 않는다.
- `public_snapshot.sourceBindings`: 내부 원천 연결 배열. 각 항목은 `documentId`, `documentVersion`, `grantId`, `grantRevision`, `recipients`를 가진다. 비어 있으면 공개할 수 없으며 이 배열은 공개 응답에 포함하지 않는다.
- `comparison_snapshot`: 퇴근 회차의 저장된 출근 대비 변화 또는 `unavailable` 사유. 현재 출근 내용을 다시 계산해 비교 결과를 바꾸지 않는다.
- `briefing_changes`: 원문과 분리한 추가 전용 정정·중단 이력. 중단 상태 변경은 해당 이력과 같은 트랜잭션으로 기록해야 한다.

`payload_sha256`은 **PostgreSQL의 `published_payload::text`를 UTF-8로 변환한 값의 SHA-256**이다. 생산자가 전송한 원래 JSON 바이트 해시와 다르다. SQL 계산은 다음과 같으며 등록·조회에서 일치 여부를 검사한다.

```sql
encode(sha256(convert_to(published_payload::text, 'UTF8')), 'hex')
```

`ZOOP_DOCUMENT_READ_GRANTS`는 기존 문서 읽기용 권한 파일의 정규화된 절대 경로다. 발행 내용 조회마다 현재 파일을 읽어 원천·버전·권한 revision·목적·수신자를 검증한다. 현재 문서가 비공개/삭제되거나 권한이 철회·만료되면 과거 발행 당시 허용값으로 우회하지 않는다. 퇴근 비교가 출근 원문을 노출하는 경우 그 출근 원문의 현재 권한도 검증한다.

AI 생성·발행 writer·관리자 변경 API·정시 실행은 아직 이 조회 경로에 연결하지 않았다. 그래프·관리자 정본 테이블의 실제 FK는 해당 담당 테이블이 준비된 후 후속 migration으로 연결한다. 브리핑 조회 화면이 동작하는 것과 전체 자동 발행·그래프·근거 상세 기능 완료를 구분한다.

## 합성 자료로 수동 연결 확인

저장소 루트에서 수행한다. 아래 파일은 직접 작성한 **합성 시험 자료**이며 실제 뉴스·공시·시세·AI 결과가 아니다. 자동 seed는 없고, 반드시 폐기 가능한 별도 DB를 사용한다. 상세 자료는 [시험 자료 안내](../src/test/resources/briefing/README.md)를 참고한다.

1. API README의 로컬 실행 환경을 준비하고 `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`를 폐기용 PostgreSQL에 지정한다. JDBC URL과 같은 DB를 가리키는 libpq URL을 별도 `ZOOP_BRIEFING_TEST_PG_URL`에 지정한다. 실제 비밀번호를 문서·Git에 기록하지 않는다.
2. 다음 값을 지정하고 API를 실행한다. 정상 Flyway 적용 및 서버 시작 후 다음 단계로 진행한다.

```sh
export SPRING_PROFILES_ACTIVE=local
export ZOOP_SWAGGER_ENABLED=true
export ZOOP_DOCUMENT_READ_GRANTS="$PWD/api/src/test/resources/briefing/grants.json"
export ZOOP_API_CORS_ALLOWED_ORIGINS=http://localhost:3000
./api/gradlew -p api bootRun
```

3. 별도 터미널에서 **같은 폐기용 DB**에 시험 자료를 한 번만 적용한다. 재실행은 불변 원문을 덮어쓰지 않고 실패하도록 되어 있다. 시험 권한 파일은 운영에서 사용하지 않는다.

```sh
psql "$ZOOP_BRIEFING_TEST_PG_URL" -v ON_ERROR_STOP=1 -f api/src/test/resources/briefing/fixture.sql
curl 'http://localhost:8080/api/v1/briefings?date=2026-10-15&edition=evening'
curl 'http://localhost:8080/api/v1/briefings/rounds?limit=2'
curl 'http://localhost:8080/api/v1/briefings/brf-test-2026-10-15-evening/graph'
```

4. 프론트 의존성을 설치한 환경에서 다음과 같이 실행하고 `http://localhost:3000/briefing?date=2026-10-15&edition=evening`을 연다. 기존 `web/src/apis/briefing/briefing.ts`가 API를 직접 호출하며 프론트 mock은 필요 없다.

```sh
VITE_API_BASE_URL=http://localhost:8080 pnpm --dir web dev --host localhost --port 3000
```

2026-10-15 출근·퇴근의 저장 요약·3지표·이슈와 퇴근 비교가 표시되는지 확인한다. 2026-10-14 출근은 빈 이슈, 같은 날 퇴근은 제공 중단, 2026-10-16 출근은 미발행 상태다. 날짜 선택·이력 추가 조회·재시도를 확인하고 브라우저 Network에서 실제 `/api/v1/briefings` 응답을 확인한다. 프론트는 `web/src/pages/briefing/BriefingPage.tsx`, 표시 컴포넌트는 `web/src/components/briefing/`에 있다.

## 자동 검증

DB 환경변수를 위 폐기용 DB로 지정한 상태에서 실행한다. HTTP 시험은 별도 임시 schema에 migration·합성 원천·권한·회차를 준비해 실제 Spring HTTP를 호출하고 정리한다. 외부 수집·유료 모델 호출은 없다.

```sh
./api/gradlew -p api test briefingIntegrationTest assemble
```

검증 범위는 DB 저장값 복원, 현재 권한 철회, 상태별 본문 숨김, 이력 커서, 잘못된 입력, 원문·해시 불변, 정정·중단 이력, Swagger·CORS 및 공통 요청 ID다. 실제 운영 자료·권한 승인과 정시 생성·자동 발행 완료를 증명하는 시험은 아니다.

## 미병합 개발 migration의 버전 충돌 정리

최신 main의 graph migration이 `20261016170000`을 사용하므로, 이 PR의 미병합 briefing migration은 `20261017230000`으로 배치했다. SQL 내용은 같다. main의 이미 반영된 migration을 수정하거나 Flyway repair/checksum 변경으로 우회하지 않는다. 이전 PR 버전을 적용한 폐기용 로컬 DB는 이력 보존용으로 유지하고, 새 버전 검증/서버는 새 개발 DB를 사용한다. 실제 공유 DB에 구 버전 briefing migration을 수동 적용한 경우에는 먼저 이력과 데이터를 확인한 별도 이행이 필요하며 자동 변경하지 않는다. 그래프·관리자 테이블이 최신 main에 추가됐지만, 이번 충돌 정리는 해당 FK/운영 그래프 연결을 새로 구현하는 작업이 아니다.
