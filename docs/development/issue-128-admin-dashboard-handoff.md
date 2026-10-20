# Issue #128 · 관리자 대시보드 구현 기준

## 범위

- WBS: `6.10.2` · FS: `FS072`
- 목표 API: `GET /api/v1/admin/dashboard` (`getAdminDashboard`)
- 화면 추적: `A-ADM-01` 운영 대시보드, `A-ADM-05b` 관리자 감사 로그 진입 요약
- A-ADM-05b의 감사 로그 목록 API 구현은 이 이슈 범위가 아니다.

## 확정한 계약 결정

1. 독립 조회 영역의 부분 실패는 `Dashboard.metadata`의 공통 `Metadata.partial/failures`로 표현한다. 성공 영역은 유지하고 실패 영역 값은 `null`로 반환한다. 정상적인 빈 결과는 `0` 또는 빈 목록이다.
2. `members.registered`는 차단 회원을 포함한 전체 가입 회원 수다. 접속 수는 별도 유효 세션 수다.
3. `ai.requests`는 최초 접수된 사용자 요청 수다. 모델 실행 시도와 재시도는 별도로 세지며, 한 요청의 재시도는 요청 수를 증가시키지 않는다.
4. 후보·작업·AI 사용자 요청·브리핑은 각각 실제 원천이 제공될 때 연결한다. 브리핑 회차 저장소/공개 reader는 main의 브리핑 읽기 변경(#207)에서 제공되지만, 대시보드의 `RoundOut` 투영 및 지연·실패 집계는 아직 연결되지 않았으므로 현재는 `SOURCE_UNAVAILABLE` 부분 실패로 표시하며 0건으로 가장하지 않는다.
5. Neo4j 상태는 별도 판단 로직을 만들지 않고 기존 pipeline 상태 reader를 재사용한다. 현재 그 reader는 프로토타입 BFF에만 있고 JVM `api/`에는 없다. BFF를 실서비스 내부 API처럼 호출하지 않으며, 실제 공통 상태 원천/읽기 인터페이스가 추가되기 전까지 `graph.graphDb`는 null과 `metadata.failures`로 표시한다.

`metadata.asOf`는 `generatedAt`과 같은 대시보드 집계 기준 시각이고, 비그래프 종합 응답이므로 `metadata.graphVersion`은 `null`이다. 기간 집계 구간은 `[generatedAt-window, generatedAt)`이다.

## 데이터·개인정보 경계

- 대시보드는 조회 전용이며 조회가 검수·차단·재처리·발행 작업을 실행하지 않는다.
- 합성 fixture만 테스트에 사용한다. 실제 이메일, 세션 쿠키/토큰, 비밀값은 응답·로그·fixture에 포함하지 않는다.
- `ai_executions`의 시도 수를 사용자 요청 수로 사용하지 않는다.
- 후보·작업·AI 사용자 요청 원천은 실제 저장소가 연결되기 전 unavailable 상태로 유지한다. 브리핑 저장소가 추가된 뒤에도 대시보드 projection이 독립 검증되기 전까지 해당 카드는 unavailable로 유지한다.

## 검증 및 화면 추적

- 단위 테스트는 `DashboardService`의 성공, 정상 빈 결과, 부분 실패, 기준시각 경계를 확인한다.
- PostgreSQL 통합 테스트는 회원·세션·감사·그래프 버전 집계를 합성 데이터로 검증한다.
- 관리자 세션 없음/만료는 401, 권한 없음은 403으로 검증한다.
- 관련 화면: `A-ADM-01`, `A-ADM-05b`. 정적 화면 이미지는 데이터·권한·실패 상태의 동작 증거로 취급하지 않는다.

## 롤백

API 변경은 해당 변경을 revert하여 되돌린다. OpenAPI, API 타입/DTO, 통합 테스트는 같은 변경 단위로 함께 되돌린다.

## 구현 상태

- 구현됨: 인증된 엔드포인트, 동일 `generatedAt` 기준 `metadata`, 회원/세션 집계, 24시간 감사 집계, PostgreSQL 그래프 버전 요약.
- 명시적 미제공: pipeline ledger/candidate, 작업, AI 사용자 요청, 대시보드용 브리핑 회차 projection, 현재 GraphDB 상태, 검수 rule/decision 요약. 브리핑 원본 저장소/공개 reader는 main에 존재하지만, 대시보드 projection은 아직 연결되지 않았다. 관련 응답 영역은 null이고 `metadata.failures`에 기록된다.
- 통합 확인 대기: PostgreSQL 테스트는 전용 `zoop_auth_check` 인스턴스가 실행되지 않아 이 checkout에서 연결 검증하지 못했다.
