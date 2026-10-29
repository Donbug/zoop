# 브리핑 회원 평가와 관리자 선호도

FS066-01/02, D-BRF-01, A-ADM-02b. 도움 됨·안 됨과 선택 사유를 실제 회원 세션으로 저장한다. 기존 발행 원문·AI 결과·시세·근거는 변경하지 않는다.

## 저장·조회

- `PUT /api/v1/feedback`: `feature`는 `briefing_round` 또는 `briefing_issue`. 회차는 `targetId=roundId`, 이슈는 `targetId=roundId/eventId`. 서버가 현재 공개 가능한 회차·발행 항목·권한·해시를 다시 확인한다.
- `targetVersion`은 `BriefingResponse.feedbackVersion`을 그대로 사용한다. 기존 graphVersion이 있으면 같은 값이다. graphVersion이 없는 **허용된 로컬 과거 재생본**에는 `publication:<published_payload SHA256>`를 사용한다. 그래프를 만들거나 운영 발행의 그래프 검증을 우회하지 않는다.
- `GET /api/v1/feedback?feature=briefing_round&targetIds=<id>`는 본인 평가만 반환한다. 필터 생략 시 본인 전체를 커서 조회할 수 있다. 현재 결과 버전과 다른 과거 평가는 반환하지 않는다.
- `up/down/none`은 원하는 최종 상태다. 중복 요청은 수를 늘리거나 값을 뒤집지 않는다. `none`은 삭제가 아닌 취소로 보존하며 사유를 비운다. `down` 사유는 선택·최대 200자이며 재조회·수정할 수 있다.
- 실제 회원 쿠키, 허용 Origin, 세션 결속 CSRF가 필요하다. 익명/guest 및 관리자 쿠키만으로 회원 평가를 저장할 수 없다. 버전 불일치/중단 회차 신규 평가는 409. 기존 평가는 제공 중단 후에도 본인 취소가 가능하다.

## 관리자

`/admin/feedback`의 선호도 요약과 싫어요 사유 탭이 아래 API를 사용한다.

- `GET /api/v1/admin/feedback/summary?window=7d|30d|all&start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET /api/v1/admin/feedback/dislikes?...&limit=50&cursor=...`

현재 제공 중이며 버전이 일치하는 각 회원·대상의 마지막 up/down만 집계한다. 취소·중단·과거 버전은 제외한다. 기간·일별 추이는 KST 마지막 변경일 기준이며 start/end는 양끝 날짜를 포함한다. 명시 날짜가 window보다 우선한다. 도움 됨 비율은 `up/(up+down)`이며 **평가 5건 미만은 비율을 숨긴다**. 동일 회원이 서로 다른 대상을 평가하면 각각 세므로 순 사용자 비율이 아니다. 챗봇 저장 원장은 이번 범위에 포함하지 않으며 `unsupported`로 표시한다.

부정 사유 목록은 회차·이슈 이름과 사유, HMAC 익명 회원 식별자만 반환한다. 이메일·실제 회원 ID·세션 토큰을 노출하지 않는다. 커서는 회원/관리자·필터·기간·페이지 크기에 결속된다. 커서의 asOf 이후 수정한 평가는 해당 페이지 탐색에서 제외되므로 최신 결과는 처음부터 조회한다.

## 보존과 실행

새 Flyway `V20261029160000__create_briefing_member_feedback.sql`이 `briefing_feedback`을 추가한다. `UNIQUE(member_id,feature,target_id)`와 회차 FK, 값/사유/대상 CHECK를 적용한다. 기존 migration이나 발행 payload를 수정하지 않는다.

개발 미리보기의 SQLite 평가는 브라우저 단위 익명 기록이다. 회원 ID가 없어 자동 이관하거나 관리자 회원 집계에 합치지 않는다. 기존 파일과 기록은 그대로 보존하고 기존 미리보기 실행에서 조회할 수 있다. 이 구분은 운영 회원 평가 유실을 뜻하지 않는다.

새 키·AI 호출은 필요 없다. 기존 DB 연결과 회원/관리자 세션·CSRF 설정으로 실행한다. 관리자 계정은 프로젝트의 공식 provision 절차를 사용한다.

검증: `DB_URL=jdbc:postgresql://.../<disposable-db> DB_USERNAME=... DB_PASSWORD=... ./api/gradlew -p api authIntegrationTest --tests com.zoop.feedback.FeedbackPostgresTest`. 실제 HTTP·PostgreSQL로 소유권, CSRF, 버전, 중복 요청, 취소, 회차별 이슈, 집계·사유·KST 기간·서명 커서를 검증한다. 프론트는 `web/tests/briefing/briefingPersonalFeedback.test.tsx` 및 `web/tests/admin/adminInsights.test.tsx`를 사용한다.
