# Issue #130 · FS065 통계 API 계약 결정안

상태: **백엔드 계약안 작성 및 Task 2~5 구현 완료 · 프런트엔드 계약 확인 대기**
담당: 백엔드 · WBS `6.10.4`
추적 화면: `M-GRP-01`, `D-GRP-01`, `A-ADM-02`

이 문서는 이슈 #130 Task 1의 데이터 원천 조사와 계약 결정, Task 2~5 백엔드 구현 내용을 기록한다. 기준 계약은 `docs/api/openapi.yaml`이다. 프런트엔드 확인은 병행 가능한 후속 확인으로 남아 있다.

## 데이터 원천 조사

| 지표 | 원천 | 제공 가능 범위 |
|---|---|---|
| 온보딩 완료 | `members.created_at`, `members.completed` | 기간 내 가입 회원 코호트의 현재 완료 상태. 과거 시점별 완료 상태는 보존되지 않음 |
| 관심 종목 | `member_watchlist` | `asOf` 시점의 현재 회원별 관심 목록. 기간별 과거 상태는 보존되지 않음 |
| Mock 보유 종목 | `member_portfolio_connections` 및 Mock portfolio catalog | `asOf` 시점의 연결 회원 및 고정 카탈로그 보유 종목. 과거 상태는 보존되지 않음 |
| 지도·브리핑 상호작용 | FS065 telemetry로 새로 수집 | 승인된 이벤트만 수집하며 이벤트 시각 및 화면/대상 식별자만 저장 |
| AI 질문 | 현재 앱 DB에는 일반 챗봇 질문 제출 이력이 집계 가능한 형태로 기록되지 않음. `ai_executions`는 실행 시도 기록이지만 질문·기업 맥락의 완전한 연결 원천은 아님 | telemetry에 `ai_question` 이벤트를 추가해 제출 건수와 화면 이용률을 수집. 회사 ID는 질문에 단일 기업 맥락이 명시된 경우만 선택적으로 전달 |
| 기업별 사건 열기 | `briefing_issue_open`은 사건 ID와 회차 ID만 식별하며, 사건과 기업의 관계가 하나로 확정되지 않을 수 있음 | 단일 기업으로 매핑할 수 있을 때만 집계하고, 그 연결 원천이 없거나 모호하면 기업별 `issueSelections=null` |
| 브리핑 좋아요·싫어요 | FS066 feedback 집계 경로에 속하며 FS065 telemetry로 수집하지 않음 | 원천 연결 전에는 `null`과 unavailable 상태로 표현 |

수집되지 않았거나 읽을 수 없는 값을 실제 `0`으로 표현하지 않는다. `0`은 원천을 정상적으로 읽었고 해당 활동이 없을 때만 사용한다.

## 지표 정의

- **기간:** `7d`는 `asOf`가 속한 KST 날짜와 그 전 6일, `30d`는 KST 날짜 30개, `all`은 원천의 첫 기록부터 `asOf`까지다. 일별 추이는 KST 달력일 기준이다. 기간 구간은 시작일 00:00 KST 포함, `asOf` 미포함으로 계산한다.
- **활성 사용자:** 기간 내 허용 telemetry 이벤트를 하나 이상 발생시킨 회원 또는 게스트의 distinct analytics principal 수. 집계 응답에는 principal을 반환하지 않는다.
- **온보딩 완료율:** 선택 기간 안에 생성된 회원 계정 중 `asOf` 시점에 `members.completed=true`인 계정 비율. 분모는 해당 기간 가입 회원 전체이며 계정 상태와 무관하다. 화면의 `membersScope`에 이 기준을 설명한다.
- **노드·간선 클릭률:** 각각 `screen_view(screen=main)`의 고유 `(principal, viewId)` 중 해당 view에서 노드 또는 간선 선택이 한 번 이상 발생한 비율. 선택 건수는 별도로 이벤트 수로 집계한다.
- **브리핑 조회율:** `screen_view(screen=briefing)`의 고유 `(principal, viewId)` 중 `briefing_view`가 발생한 비율. `briefing_view.targetId`는 회차 ID다.
- **브리핑 관심도:** 회차별 조회 수, 조회자 수, `briefing_issue_open` 건수를 제공한다. 같은 `(principal, roundId, viewId)`의 반복 view 이벤트는 1회로 센다. 좋아요·싫어요는 FS066 원천을 연결하기 전까지 null이다.
- **AI 질문 이용률:** `screen_view(screen=ai)`의 고유 `(principal, viewId)` 중 `ai_question` 제출 이벤트가 발생한 비율. 질문 텍스트와 답변은 telemetry로 보내지 않는다. `targetId`는 단일 기업 맥락을 식별할 수 있을 때만 기업 ID로 설정한다.
- **표본 보호:** 비율 분모가 5 미만이면 `rate=null`, `sampleHidden=true`로 응답하고 건수는 유지한다. 원천이 unavailable인 경우에는 `availability=unavailable`, 값 필드는 null, `sampleHidden=false`로 응답한다.
- **기업별 관심·보유 회원:** 선택 기간의 시계열이 아니라 `asOf` 시점의 현재 목록/연결 상태를 센다. 응답 설명과 `holdingsNote`에서 이 기준을 알린다.

## API 계약 변경

`docs/api/openapi.yaml`에 다음을 반영했다.

- telemetry 이벤트를 이벤트별 `oneOf` 스키마로 나눠 타입별 필수 필드를 고정하고, 배치 크기를 1–20개로 제한한다.
- `screen_view`에 `ai` 화면을 추가하고, 질문 본문 없이 `ai_question` 이벤트를 받을 수 있도록 정의한다.
- 그래프 클릭과 브리핑 상세 조회율 계산에 필요한 `viewId`를 이벤트별 필수 필드로 정한다.
- `StatsMetric`에 `availability`와 `unavailableReason`을 추가해 원천 미연결·조회 실패·기간 자료 부족과 실제 0건을 구분한다.
- AI 질문 집계 필드와 FS066 평가 집계 필드는 nullable로 바꿔 원천이 없을 때 0으로 오인하지 않게 한다.
- `membersScope`, 회원 수, 관심·보유 회원 수의 집계 기준을 명시한다.

## 프런트엔드 확인 항목

- 이벤트 타입 추가: `screen_view(screen=ai)`, `ai_question`; 그래프·브리핑 이벤트의 `viewId` 필수화.
- `StatsMetric.availability`, `unavailableReason` 렌더링과 표본 부족 상태 구분.
- 통계 응답의 AI 질문 및 브리핑 평가 필드에서 null을 unavailable로 처리.
- 관심·보유 종목은 현재 시점 스냅샷으로 표시.

확인 화면은 `A-ADM-02`이며 계측 발생 위치는 `M-GRP-01`, `D-GRP-01` 및 AI 화면이다. 화면 변경은 이 Task 범위에 포함하지 않는다.

## Task 2~5 백엔드 구현

- **Task 2 · 이벤트 저장소:** `telemetry_events`와 `telemetry_batches` 마이그레이션을 추가했다. principal은 회원/게스트 세션의 analytics key를 사용하며 이벤트에는 실명, 이메일, 질문 본문을 저장하지 않는다.
- **Task 3 · 수집 API:** `POST /api/v1/telemetry`를 구현했다. 허용 이벤트/필드를 검증하고 1~20건 배치를 저장한다. 같은 principal과 `Idempotency-Key`의 같은 payload는 기존 접수 건수를 반환하고, 다른 payload는 `IDEMPOTENCY_CONFLICT`로 거절한다.
- **Task 4 · 전체 통계:** 관리자 전용 overview/summary API에서 기간별 지표, KST 일별 추이, 브리핑 회차별 조회 집계를 제공한다. 비율은 distinct `(principal, viewId)` 기준이며 분모가 5 미만이면 비율을 숨긴다. 브리핑 평가 원천은 아직 연결되지 않아 unavailable/null로 응답한다.
- **Task 5 · 기업 통계:** 관리자 전용 기업 목록/상세 API에서 카탈로그 기업별 관심 회원, 고정 모의 포트폴리오의 현재 보유 회원, 귀속 가능한 이벤트 집계를 제공한다. 기업별 사건 열기는 사건-기업 매핑이 모호하고 간선 선택은 간선-기업 매핑 원천이 없어 null이다. 목록 커서는 window/limit/offset/asOf를 담은 Base64 URL-safe 값이며, 다음 페이지에서도 집계 기준 시각을 유지한다.

구현 파일은 `api/src/main/java/com/zoop/telemetry/`, `api/src/main/java/com/zoop/admin/insights/` 및 `api/src/main/resources/db/migration/V20261021100000__create_telemetry_events.sql`이다. `InsightsPostgresTest` 2개, 기존 `MemberSessionPostgresTest` 5개, `MemberSessionServiceTest` 및 `SessionControllerTest` 단위 테스트, `./gradlew compileJava`가 통과했다. 통합 테스트는 로컬 15432의 기존 `zoop` DB 대신 테스트 전용 임시 DB에서 실행했다.
