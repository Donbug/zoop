# 관리자 브리핑 정정·중단·재개 (A-ADM-04 / FS071)

관리자 회차 조회(#418)에 이어 저장된 발행본에 대한 변경 작업을 연결한다. 별도 생성·모델 호출이나 migration은 없다.

## API와 저장

- `POST /api/v1/admin/briefings/{round_id}/corrections`: `{eventId?: string|null, correctedText: string, reason: string}`. 201 CorrectionOut. 회차 전체 또는 원문에 실제 포함된 이슈를 정정한다. 등록된 정정은 기존 공개 브리핑 조회의 `corrections`에도 나타난다.
- `POST /api/v1/admin/briefings/{round_id}/suspension`: `{action: suspend|resume, reason: string}`. 200 RoundOut. 중단하면 공개 조회에 중단 상태·사유가 표시되고, 재개하면 같은 원문을 다시 제공한다. 재생성하거나 최신 결과로 교체하지 않는다.
- 관리자 세션·허용 Origin·세션 결합 CSRF·단일 Idempotency-Key가 모두 필요하다. 키는 기존 관리자 규칙과 같이 비어 있지 않은 200자 이하 값이다. 사유 500자, 정정 내용 2000자까지 받고, 공백뿐인 입력·사유에 내부 인증 정보/URL/이메일 등이 있는 입력은 거절한다.
- 미발행 회차는409, 없는 회차404, 잘못된 이슈/본문422. 재처리 API는 후속 범위이며 기본 UI에서 비활성화한다.

`briefing_rounds` 행 잠금 아래 `briefing_changes` 번호를 부여한다. 정정은 원문을 수정하지 않고 append한다. 중단/재개는 status와 revision만 갱신하며 이력·감사 로그·멱등 응답을 같은 transaction에 기록한다. payload/public_snapshot/schema/version/생성·발행 시각/SHA는 보존한다. 감사 저장을 포함해 하나라도 실패하면 모두 rollback한다.

같은 관리자·작업 경로·키·내용은 최초 저장 응답을 재전송하고, 같은 키에 다른 내용이면409다. 최초 중단 후 재개된 상태에서 과거 중단 요청을 같은 키로 재전송하면 과거 응답만 돌려주며 다시 중단하지 않는다. 클라이언트는 작업 완료 후 목록·상세를 다시 조회한다. 다른 키로 이미 같은 상태를 요청해도 중복 이력/감사는 만들지 않는다. 서로 다른 정상 정정은 각각 이력을 남기며 원문은 변하지 않는다.

변경 이력의 관리자 이메일은 실행 당시 snapshot이다. 정정은 기존 관리자 상세에, 중단은 현재 중단 상태에 표시되고, 모든 전이는 briefing_changes와 audit_logs에 남는다. 원문의 직접 UPDATE/DELETE는 기존 DB 보호 규칙으로 막는다.

## 확인

읽기 연결 문서의 DB/계정/실행 설정을 사용해 `/admin/briefings`에서 발행 회차를 선택한다. 정정→상세 새로 읽기→제공 중단→공개 중단 확인→재개 순으로 확인한다. 확인은 원본 DB와 분리된 복사본에서 수행한다.

회귀 테스트: PostgreSQL 환경변수 설정 후 `./api/gradlew -p api authIntegrationTest`. `AdminBriefingChangePostgresTest`는 HTTP/CSRF·멱등성·미발행 거절을, `AdminBriefingChangeConcurrencyTest`는 실제 별도 connection의 같은 키/다른 키 동시 정정·중단과 감사 실패 rollback을 검증한다. 실제 모델 호출은 없다.
