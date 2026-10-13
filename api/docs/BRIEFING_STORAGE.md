# 브리핑 저장·조회 첫 단위 (#20)

기준 main 91113ce / ERD v6 / 목표 OpenAPI getBriefing·listBriefingRounds.
Codex 저장·조회, Muse workflow(생성·발행·정정), Green acceptance 독립 검증으로 분리한다.

## 현재 동작

- `GET /api/v1/briefings?date=YYYY-MM-DD&edition=morning|evening`: KST09:20/17:30 예정 시작 회차 선택. GET은 DB를 만들거나 AI를 호출하지 않는다. 회차 없음은 not_ready, 내부 상태는 ERD 공개 상태로 매핑한다.
- `GET /api/v1/briefings/rounds?limit=20&cursor=…`: 발행 이력과 중단 회차를 scheduled_at DESC/id DESC로 조회한다. 커서는 해당 limit에 결합하며 새 회차 삽입에도 offset 중복이 없다. 로컬 페이지 크기 기본20/상한100은 최초 구현 선택이고 전체 이력 제한이 아니다. 정본의 운영 정책은 미정이므로 팀 검토 대상이다.
- `BriefingRoundRepository.schedule`은 내부 저장 진입점이다. 같은 회차/같은 입력은 재사용, 다른 입력은 거절한다. 공개 쓰기 endpoint·자동 스케줄러는 아직 없다.
- JDBC projection은 불변 JSON을 읽는다. JPA managed entity의 save/merge로 원문을 덮어쓰지 않는다. ddl-auto는 기존 validate 유지, 테이블은 Flyway만 생성한다.
- snapshot 복원은 저장된 marketSummary·marketVariables·sinceMorning을 사용한다. 최신 데이터 재생성/최신 그래프 fallback 없음. metadata.requestId만 현재 요청의 값으로 바꾼다. 시장 지표가 없는 과거 발행본은 unavailable이다.
- 공개 전과 중단 회차는 items/references/시장값/outlook/비교 내용을 노출하지 않는다. 내부 failure_reason은 반환하지 않는다.

## 실제 생산 연결 전 필수

현재 main에 graph_versions·검수·권리 registry와 briefing_attempts/changes가 없다. 다른 담당자의 가짜 테이블이나 인증을 만들지 않는다.

1. Muse workflow가 현재 임대/토큰·active attempt·revision 검증 및 publication_state 공통 잠금을 연계한 발행 경로를 제공해야 한다. 이 첫 단위에는 발행 writer 자체가 없다. DB의 JSON 기본 구조·항목/rank/불변 보호가 전체 발행 승인 검증을 대체하지 않는다.
2. 그래프 담당 테이블 제공 후 후속 migration에서 graph_version_id FK를 추가한다. 현재 컬럼은 nullable text이고 graph 테이블 존재 검증·참조 FK는 아직 없다. 정상 최초 발행은 trigger에서 nonnull을 요구한다. source/entity/evidence 실재성·권리·full JSON schema 검증은 workflow의 선행 조건이다.
3. 데이터 소유자가 `BriefingContentAccess` 구현 bean을 제공해 현재 grant/철회 검사를 연결해야 한다. 없으면 published 조회는 503 SOURCE_UNAVAILABLE로 차단된다. 테스트의 허용 bean은 합성 fixture 전용이며 운영 우회 설정은 없다.
4. Muse의 정정/중단 이력이 연결되면 corrections와 notice.reason/at를 그 저장소에서 합성한다. 현재 첫 단위는 corrections=[]·중단 notice.reason/at=null이며 관리자 수정 endpoint는 없다.
5. 개인화/feedback/graph 조회/실제 생성/AI jobId·revision·영수증/운영 스케줄은 이번 첫 단위 완료로 간주하지 않는다. 김도현 소유 공통 feedback와 인증/관심·보유 목록 인터페이스는 별도 합의한다.

API 정본에는 옛07:40/18:10 설명이 남아 있다. 사용자 최신 결정09:20/17:30을 구현하며, 이번 변경은 wire schema를 바꾸지 않는다. Google 원문 변경 이력과 계약 설명 동기화는 통합 검토 때 확인한다. 기존 발행 snapshot의 schedule은 소급 바꾸지 않는다.

## 검증

`./api/gradlew -p api test build` (DB 없는 query/controller 시험).
실제 PostgreSQL16 독립 DB에 `ZOOP_BRIEFING_TEST_DB_URL`, `ZOOP_BRIEFING_TEST_DB_USERNAME`, `ZOOP_BRIEFING_TEST_DB_PASSWORD`를 전달하고 `./api/gradlew -p api briefingStorageTest` 실행. 루트 명령은 `make api-briefing-test`이며 CI api job도 독립 PostgreSQL service에서 같은 시험을 실행한다. 해당 task는 DB 설정이 없으면 실패하며 skip하지 않는다. 외부 원문/유료 AI 호출 없음.
