# 관리자 브리핑 회차 조회 (A-ADM-04 / FS070-01)

`/admin/briefings`는 Spring의 관리자 세션으로 기존 PostgreSQL 회차를 조회한다. 회차 조회 자체는 생성·모델 호출·발행·상태 변경을 수행하지 않는다. 정정·제공 중단/재개를 연결한 후속 구현은 [관리자 브리핑 변경](admin-briefing-changes.md)을 따른다. 재처리는 비활성화한다.

## 읽기 API

- `GET /api/v1/admin/briefings`: `scheduled_at DESC, id DESC` 목록. `from`, `to`는 생략 가능하며 둘을 제공하면 동일한 날짜 또는 offset date-time 형식이어야 한다. 날짜는 한국 시간 해당 일 전체를 포함하고, date-time은 경계 시각까지 포함한다.
- `limit=1..100` (기본 50). `nextCursor`는 관리자 ID·필터·페이지 크기에 결합된 서명 커서다. 다음 페이지에서도 같은 필터를 전달한다. 같은 예정 시각의 회차도 ID로 안정적으로 구분한다.
- `GET /api/v1/admin/briefings/{round_id}`: 회차 상태·발행 원문·정정 이력·생성 시도 기록. 존재하지 않는 회차는 404, DB 조회 실패/원문 digest 불일치는 503이며 빈 목록으로 가장하지 않는다.
- 관리자 인증 없이 401. 일반 사용자 세션을 관리자 세션으로 인정하지 않는다. 정정·중단/재개 POST API는 후속 변경 문서를 따른다.

## 저장 의미

`briefing_rounds`, `briefing_changes`, `briefing_attempts`를 같은 읽기 전용 repeatable-read transaction에서 조회한다. 새 migration이나 기존 결과 backfill은 없다. 발행 원문은 기존 PostgreSQL JSONB SHA-256 검사를 통과한 내용만 반환한다. 중단된 회차도 관리자는 원문과 중단 이유를 볼 수 있고, 정정은 원문 덮어쓰기 없이 별도 이력으로 제공한다.

- 발행·생성 완료는 저장된 시각으로 표시한다. `verify` 기록이 없는 과거 회차를 임의로 완료 처리하지 않고 `StageOut.status=unknown`(기록 없음)을 반환한다.
- `attempts`, `trigger`, `attemptsLog`는 `purpose=generation` 원장만 사용한다. 별도 `outlook` 호출을 생성 재시도로 중복 집계하지 않는다. 과거 원장이 없으면 기록된 시도 0, trigger null이며 실제 AI 호출이 없었다는 의미가 아니다.
- 운영 예정 시각은 09:20 / 17:30 Asia/Seoul. 저장된 회차의 실제 예정/생성/발행 시각은 그대로 표시한다.
- 토큰·임대·요청 본문은 응답에 넣지 않는다. 실패 사유는 안전한 코드만 노출하며 자유 형식의 내부 오류는 일반 안내로 대체한다.

## 로컬 확인

1. `api/README.md`에 따라 PostgreSQL과 API 환경을 설정하고 migration을 적용한다. 기존 DB는 먼저 백업한다.
2. 같은 README의 `admin-provision` 명령으로 관리자 계정을 만든다. 일반 회원 로그인과 별도 계정이다.
3. 로컬 HTTP만 사용하는 경우 `SPRING_PROFILES_ACTIVE=local`, `ZOOP_AUTH_ALLOWED_ORIGINS`를 실제 프론트 주소로 설정한다.
4. `web/.env.local`에 `ZOOP_DEV_API_TARGET=http://localhost:<API 포트>`를 설정하고 `pnpm dev`를 실행한다.
5. `/admin/login`에서 로그인한 뒤 `/admin/briefings`에서 회차를 선택한다. 저장된 회차가 없으면 빈 상태가 정상이며 임의 회차나 AI 결과를 생성하지 않는다.

검증: `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`를 분리된 시험 DB로 설정하고 `./api/gradlew -p api authIntegrationTest --tests com.zoop.admin.briefings.AdminBriefingPostgresTest`; 화면은 `cd web && pnpm test tests/admin/adminBriefings.test.tsx`.
