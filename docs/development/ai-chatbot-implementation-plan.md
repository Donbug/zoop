# ZOOP AI 챗봇 구현 준비·개발 계획

최초 기준일: 2026년 10월 21일 / 구현 상태 갱신: 2026년 10월 25일

기준 정책: `ZOOP-AIG-001 v0.11` / 목표 설계 갱신: 2026-10-28 (날짜별 구현 기록과 구분)

화면 추적: `D-AI-01`, `D-AI-01b`, `D-AI-02`, `D-AI-02b`

관련 문서:

- [AI 챗봇 설계 요약](../design/ai-chatbot-design-summary.md)
- [AI 챗봇 고정 평가 세트](ai-chatbot-eval-set.md)
- [AI 거버넌스 정책](../ZOOP_AI_거버넌스_정책.md)
- [공개 목표 API](../api/openapi.yaml)
- [ERD v6](../erd/zoop-core-erd-v6.md)
- [AI 챗봇 화면 상태 계약](../wireframe/ai-chatbot-state-contract.md)
- [현재 AI 내부 HTTP 계약](../api/internal-ai-openapi.yaml)

## 1. 현재 진행 상태

### 2026-10-28 승인된 개발 기준 (구현 예정)

이 절은 아래의 2026-10-27 목표와 충돌할 때 우선한다. 현재 코드는 Java 직접 어댑터와 Luna Chat Completions를 사용하므로, 다음 항목은 구현 완료 표시가 아니다.

2026-10-28 팀 결정이며 2026-10-25의 MCP 미사용 결정을 대체한다.

1. **실행 구조**: Jev Q01~Q08 multi-label → 서버 allowed_tools·scope·예산 → Luna Responses 원격 MCP 선택·연속 호출 → 서버 결정론 검사 → Jev 의미 검증으로 변경한다. 별도 Luna coverage-verifier는 구현하지 않는다.
2. **MCP 경계와 승인**: Java 앱의 HTTPS Streamable HTTP `/mcp`가 기존 Tool Service를 재사용한다. `require_approval=always`로 두고 ai/service가 approval request를 Java에 반환하면 Java가 예산·요구·scope·grant를 판단한 뒤 ai/service continuation을 다시 호출한다. ai/service는 독자 승인하지 않는다.
3. **웹 정책**: Q01 금지, Q02 기본 보조, Q03~Q08 내부 근거 뒤 마지막 수단이다. timeout·unavailable·0건은 전체 답변을 실패시키지 않고 `notices`와 실제 미충족 요구 limitation으로 구분한다.
4. **예산**: 총 8회·내부 6회·웹 2회, 동시 4개, 총 3라운드, fan-out 5, DB 3초·그래프 5초·웹 7초, Luna 35초·job 45초, 입력 24k·답변 2k를 서버가 원자적으로 예약·차감한다.
5. **중복 억제**: job/generation·논리 도구·정책/스키마 revision·정규화 인자·subject scope·version·asOf를 키로 요청 캐시와 single-flight를 둔다. 성공 0건도 저장하고 cache hit에서 권한·grant·철회를 다시 확인한다.
6. **direct 시작 경로**: Responses 시작 전 preflight 실패·circuit open이면 MCP를 노출하지 않고 처음부터 Java direct adapter로 조회한다. 실행 중 MCP 오류는 direct 결과로 바꿔 끼우지 않는다. 인증·권한·grant·스키마 거부와 결과 수신 여부 불명도 우회·재호출하지 않는다.
7. **결과 계약**: 기존 status/outcome에 새 상태를 추가하지 않고 목표 `answerStatus=complete|partial|guidance`, `notices[]`를 DTO·저장·OpenAPI·웹·guard와 동시에 구현한다.
8. **턴 문맥**: 새 질문마다 재분류하고 이전 완료 2턴의 검증된 대상 ID·기간만 후보로 승계한다. 이전 답변 본문은 모델에 넘기지 않는다.

상세 기준은 [Luna MCP 실행 계약](../design/ai-chatbot-mcp-actions.md), [웹 검색 계약](../design/ai-chatbot-web-search.md), [거버넌스 6장](../ZOOP_AI_거버넌스_정책.md#6-챗봇의-질의-분류-정책)을 따른다.

### 2026-10-27 이전 목표 기록 (v0.11로 대체)

당시의 서버 중심 MCP POC·독립 Luna coverage-verifier·웹 장애 전체 실패 목표는 v0.11에서 폐기했다. 과거 PR을 해석할 때만 참고하며 개발 기준은 바로 위 2026-10-28 절을 따른다.

### 기존 구현 상태

| 영역 | 현재 확인된 상태 | 구현 판단 |
| --- | --- | --- |
| 공개 챗봇 계약 | 목표 OpenAPI에 더해 Spring `ChatController`가 세션 생성·조회, 최신 대화 복원, 질문 job 접수·조회·재시도·취소를 구현함 | 공개 producer 구현됨. 배포 활성화는 별도 |
| ERD | `V20261021120000__create_chat_jobs.sql`이 `chat_sessions`, `chat_jobs`, `chat_tool_calls`와 `ai_executions.chat_job_id` FK를 생성함 | 저장·제약·동시성 시험 구현됨. 적용된 migration은 수정하지 않음 |
| 프로토타입 BFF | `prototype/bff`에 규칙 기반 질문 해석, 기간 처리, 세션·job·복구·save_only와 테스트가 있음 | 상태 머신·불변식의 참고 구현. 운영 AI 답변 엔진으로 승격하지 않음 |
| 본개발 Java API | controller/service/repository, 고정 문맥, 작업 executor, 오케스트레이터, 모델 단계 adapter와 읽기 도구 실행기가 있음 | 백엔드 수직 경로 구현됨. recovery artifact·`save_only` 저장 복구는 미구현 |
| 루트 웹 | `web/src/apis/chat`, `use-chat-conversation`, `AiChatDrawer`·`ChatJobCard`가 대화 생성·복원, 질문 접수·polling·취소·재시도와 답변·인용·확인 질문·실패 렌더링을 구현함(Vitest) | 구현됨. 타입은 손으로 쓴 `web/src/types/ai`이고 실제 백엔드·모델 종단 시험은 없음 |
| AI worker | `zoop-ai-chat`이 `chat-router`(Jev), `chat-answer`(Luna), `chat-verification`(Jev)을 별도 계약·원장·grant·live gate로 실행함 | 구현됨, 기본 비활성. 임계값 보정과 실제 승인 호출은 별도 |
| AI 내부 서비스 | `/internal/v1/chat-stages/{stage}`가 인증된 synchronous stage door로 구현되고 생성 OpenAPI에 포함됨 | 구현됨. 앱은 `HttpChatStageClient`로만 호출 |
| 데이터 기반 | 기업·문서·evidence·공개 그래프 버전과 현재 권리 재검사 경로가 있고 `company.read`·`issue.read`·`evidence.resolve`·`graph.path.read`·`zoopPolicy.read`가 연결됨(`company.read`는 기업 카탈로그 개요를 `company_profile` 인용으로, `zoopPolicy.read`는 승인 약관을 `zoop_doc` 인용으로 전달) | Q01(정책 문서만)·Q03/Q04 일부 구현. Q01 도움말·화면 명세, Q05·Q06·Q07·Q08 도구와 종단 공개 시험은 추가 필요 |
| 와이어프레임 | 네 정적 화면은 질문·되묻기·회수·조회 오류의 시각 기준을 제공하지만 동작 상태를 증명하지 않음 | 별도 상태 계약으로 로딩·오류·근거 수준·복구를 고정함 |

결론적으로 백엔드의 저장·공개 API·작업 실행기·라우터·오케스트레이터·도구 레지스트리·Luna 생성·Jev 검증과 웹 D-AI-01~02b 연결은 구현돼 있다. 다만 Luna Responses MCP, 서버 requirement coverage, claim 단위 `unsupportedCausality`, 24k/2k token guard, recovery artifact·`save_only`, 미연결 Q 유형 도구, 평가 보정과 출시 증명은 남아 있다. 기능 플래그와 live gate는 기본적으로 꺼져 있으므로 “코드가 있음”은 “출시됨”이나 “실제 모델 호출 승인됨”을 뜻하지 않는다.

### 구현된 도구 결정 기록 (현재 코드 기준)

아래는 이미 구현된 direct 경로(`chat-tools/v5`)의 사용자 승인 결정이다. MCP 전환 뒤에도 같은 Tool Service의 동작 기준으로 유지하며, 목표 변경(예: Q07 `portfolio.scope.read`의 Java server-only 실행)은 2026-10-28 절을 따른다.

Q05 기간 비교의 잠정 결정(2026-10-27, 사용자 승인, 평가 세트로 보정 전): (7) 비교 기준은 질문에 적힌 기간이다. 정해진 한국어 표현(오늘·어제·그제, 이번 주·지난주, 이번 달·지난달, N일·N주·N달 전, 최근 N일·N주, `YYYY-MM-DD`, `M월 D일`)만 서버가 KST로 결정론적으로 해석하고(`ChatPeriods`), 여러 표현은 가장 이른 시작부터 가장 늦은 끝까지 한 기간으로 묶는다. 기간 시작 시각(KST 자정)에 공개돼 있던 지도와 작업이 고정한 지도를 비교한다. 질문에 기간이 없으면 회원이 고른 기간, 그것도 없으면 고정 지도 직전에 공개됐던 지도와 비교한다. 해석한 기간은 결과의 `applied.period`(`basis=question`, `expression`)로 보인다. (8) `graph.version.diff`는 대상(기업·사건)을 지목하면 그와 관련된 변화만, 아니면 지도 전체 변화를 최대 40건 돌려주고, 추가된 항목만 지금 고정 지도의 근거를 싣는다. 비교할 이전 공개 지도가 없으면 "변화 없음"이 아니라 잘린 조회(`truncated`)다. 레지스트리는 `chat-tools/v3`다.

Q07 내 종목의 잠정 결정(2026-10-27, 사용자 승인, 평가 세트로 보정 전): (9) 범위는 연결된 모의 계좌의 보유 종목(계좌 표시 순) 다음 관심 종목(관심 목록 순)이며, 지도 "내 종목" 보기와 같은 원천(`PersonalCompanies`)이다. 회원은 작업의 인증 회원으로 서버가 조회 범위(`ChatToolScope.memberId`)에 넣고, `portfolio.scope.read`는 `member:self` 외의 대상을 받지 않는다. (10) 기업을 지목하지 않은 Q07 요구는 계획기가 서버 요구 `<id>-s`(`Origin.SCOPE`, 1단계 `portfolio.scope.read`)를 앞에 두고 원 요구를 `atLeast(1)` 의존 단계로 바꾼다. 범위 요구는 따로 답하지 않고 그 결과가 원 요구의 답변 입력에 함께 들어간다. 종목이 없으면 "없음"을 답하고(근거 없이 허용), 5개를 넘으면 앞 5개만 조회하고 `results_truncated` 안내를 답변 옆에 붙인다. 회원 본인 범위만 읽은 구간은 공개 근거가 없으므로 인용 없이 허용한다. 레지스트리는 `chat-tools/v4`다. (11) Q07 요구가 기업을 지목하면(2026-10-27, 사용자 승인) 그 기업이 묻는 대상인지 기준점인지를 라우터 유형으로 나눈다. Q04(관계)가 없으면 묻는 대상("내 종목인 삼성전자")이다. 범위 요구가 지목 기업을 대상으로 `portfolio.scope.read`를 부르고, 회원의 전체 보유·관심 종목(앞 5개로 자르지 않음)과 대조해 회원의 것만 돌려받는다. 원 요구는 그 기업만 읽는다. 일부만 회원의 것이면 답변 옆에 `not_in_member_scope` 안내를 붙이고, 하나도 아니면 그 요구를 `not_in_member_scope`로 제한한다. 남는 요구가 없으면 근거 부족 결과이고, 원인 문장이 "보유·관심 종목에 없음"을 말한다(모델 생성 호출 없음). "삼성전자 내 종목이야?"처럼 다른 조회가 없으면 범위 확인 자체가 답의 입력이다. Q04가 있으면 기준점("내 종목 중 삼성전자와 연결된 것")이다. 회원 종목 전체를 읽고 기준점은 원 요구가 첫 대상으로 함께 읽는다(`graph.path.read`는 첫 대상에서 경로를 찾는다). 기준점이 회원의 것이 아니면 안내만 붙인다. 질문의 사건은 원 요구의 대상으로 남는다. 의존 단계 요구는 `portfolio.scope.read`를 쓰지 않는다. 그래서 회원 범위 조회가 기업·사건 ID를 대상으로 받아 실패하는 일이 없다. 도구 입력의 의미가 바뀌었으므로 레지스트리는 `chat-tools/v5`다.

첫 도구 계층은 레지스트리 `chat-tools/v1`(2026-10-27부터 `chat-tools/v2`·`v3`·`v4`·`v5`, 결정 (6)·(8)·(10)·(11))에 `company.read`·`issue.read`·`evidence.resolve`를 앱 공개 그래프 읽기 경로(`PublicGraphReader`) 위의 내부 어댑터로 등록한다. 그래프 버전·asOf는 계획이 아니라 작업의 고정 문맥에서 주입하고, 근거 ID는 공개 근거 조회가 지금 읽을 수 있는 것만 상한(20개) 안에서 전달한다. 상한 때문에 읽지 않은 근거가 있으면 `truncated=true`이며, 근거 상태를 확인할 수 없으면 빈 결과가 아니라 호출 실패(`tool_unavailable`)다. 단계 실행기는 등록되지 않은 기능이 하나라도 있으면 아무것도 예약하지 않고, 시도당 12회·동시 4개·개별 3초·단계 10초(실행 기한 이내)를 강제한다.

## 2. 구현 경계와 소유권

```mermaid
flowchart LR
    web[Web D-AI-01~02b] --> app[Java 공개 API]
    app --> db[(PostgreSQL chat jobs/tool calls)]
    app --> orch[Chat Orchestrator]
    orch --> jev[Jev router]
    orch -. v0.11 목표·미구현 .-> luna1[Luna Responses MCP 실행]
    orch --> registry[서버 도구 registry]
    registry --> adapters[읽기 전용 adapters]
    adapters --> stores[(문서·그래프·브리핑·회원 범위)]
    orch --> luna2[Luna answer-generator]
    orch --> validate[1층 결정론적 출력 검증]
    validate --> jev2[2층 Jev semantic-verification]
    jev2 --> app
```

- 웹은 분류·도구 선택·인용 유효성을 결정하지 않는다.
- Java API는 인증·소유권·멱등성·상태 전이·내구 저장·공개 DTO의 권위자다.
- 챗봇 오케스트레이터는 typed 요구 분해·라우팅·계획·호출 조정·생성·검증을 담당하지만 회원 권한을 발급하지 않는다.
- 도구 레지스트리는 논리 기능을 실제 읽기 도구로 매핑한다. 모델 출력 문자열을 직접 실행하지 않는다.
- 문서·그래프·브리핑 서비스는 공개·철회·버전 경계를 자신의 조회 시점에도 검사한다.

## 3. 권장 구현 순서와 현재 상태

| 단계 | 2026-10-25 main 상태 | 남은 핵심 |
| --- | --- | --- |
| 0 계약·fixture | 부분 구현 | 목표 내부 schema 전체와 고정 평가 fixture 정리 |
| 1 저장·job 수명주기 | 부분 구현 | recovery artifact와 실제 `save_only` 복구 |
| 2 오케스트레이터 | 부분 구현 | 8/6/2·45초 deadline, 요청 cache·single-flight, 서버 requirement coverage |
| 3 router·Luna agent | 부분 구현 | Jev router는 구현, Luna Responses MCP 실행은 미구현 |
| 4 읽기 도구 | 부분 구현 | Q03 일부, Q04 경로, Q05 지도 버전 비교(`graph.version.diff`), Q07 내 종목(`portfolio.scope.read`) 구현, Q01 일부·Q06·Q08 미연결 |
| 5 생성·출력 검증 | 부분 구현 | 구간 단위 생성·검증은 구현, claim 단위 검증·token guard 미구현 |
| 6 웹 | 구현 | OpenAPI 타입 생성 seam, 실제 백엔드와의 종단 확인 |
| 7 평가·출시 | 부분 구현 | 고정 평가 세트 v1(대본 실행)만 있음. 실제 모델·데이터 평가와 임계값 보정, 보안·종단·배포 증명 |

### 단계 0 — 계약 고정과 fixture

1. `ChatResult.answerBasis`, `ChatChoice.kind`, 확인 질문 답 `resolves`(`ChatClarificationReply`), 답하지 않은 요구 `limitations`(`ChatLimitation`), 근거 수준별 `sections`, 진행 단계 `phase`, 입력·조회 상한과 `transient`·`budget_exceeded`의 `reason` 코드, `Citation.sourceKind`(`article`·`zoop_doc`)를 Java DTO·웹 타입·프로토타입 호환 fixture에 반영한다.
2. 내부 `ChatRouteSummary v1`, `ChatToolRequest v1`, `ChatToolResult v1` JSON Schema를 만든다.
3. Q01~Q08, 논리 capability, 도구 registry group을 코드 enum/registry로 한 곳에서 버전 관리한다.
4. 실제 모델 없이도 전체 상태 머신을 시험할 deterministic fake router·MCP tool·generator·server coverage를 만든다.

완료 조건: 공개 OpenAPI 검사 통과, schema fixture round-trip, 예전 BFF와 목표 API의 의도된 차이 목록 갱신.

### 단계 1 — 저장과 공개 job 수명주기

1. 새 Flyway migration으로 `chat_sessions`, `chat_jobs`, `chat_tool_calls` 및 부분 UNIQUE·CHECK·인덱스를 만든다.
2. Java에 chat controller/service/repository와 멱등성·소유권·대화당 활성 job 하나 제약을 구현한다. `resolves`가 있으면 원 작업의 같은 대화·clarification·choice 존재를 같은 트랜잭션에서 검사하고 원 고정 문맥을 복사한다. 확인 질문 사슬 깊이(`clarification_depth`, 원 작업 + 1, 최대 2)를 함께 고정한다.
3. `queued → running → completed|failed|cancelled`, lease/owner token(lease = 시작 시각 + 실행 기한 + 여유), 늦은 완료 차단, lease 만료 회수(모델 요청을 보낸 실행은 `response_unknown`·retry 없음, 보내기 전이면 `deadline_guard`·rerun 가능), recovery artifact와 `save_only`, 작업당 실행 3회 상한(`runs` ≤ 3, 이후 `retry=null`, 모델을 호출하지 않는 `save_only`는 횟수에서 제외)을 구현한다.
4. `getCurrentConversation`은 최신 저장 대화만 복원하고 모델을 호출하지 않게 한다. 대화 목록(`listConversations`)과 대화 삭제(`deleteConversation`)는 2026-10-27 구현했다. 삭제는 즉시 실제 삭제이고, 승인된 처리방침·약관이 개별 채팅 삭제 미제공이라 개정 시행 전까지 `zoop.chat.delete-enabled=false`로 꺼 둔다([개정 초안](../legal/drafts/revision-chat-deletion.md)). 같은 변경에서 모델 실행 원장이 대화·회원 삭제를 막던 FK를 고쳤다(`V20261027120000`).

완료 조건: 동시 접수 한 건만 성공, 다른 회원 접근 차단, 같은 jobId 같은 본문 재전송은 같은 작업 반환, 다른 본문은 409, save_only 모델 호출 0회, 깊이 2 작업의 clarification 저장 0건.

현재 상태: migration, 공개 API, 멱등성·소유권, 단일 활성 job, lease/owner fence, 취소·만료 회수와 최대 3회 rerun은 구현됐다. recovery artifact 저장소가 없어 `save_only` 시도는 현재 `result_lost`로 닫히므로 이 단계의 완료 조건 전체를 충족한 것은 아니다.

### 단계 2 — 오케스트레이터·예산·캐시

1. job의 frozen context와 서버 allowed_tools를 만들고 모든 호출 전에 권한·scope·버전·grant·예산을 검사한다.
2. 8/6/2 호출 상한, 총 3라운드, 동시 4개, fan-out 5와 개별 timeout을 원자 예약한다. failed·direct 시작 경로·cache hit도 논리 시도로 원장에 남긴다.
3. running 전이부터 최종 검증 결과와 영수증의 terminal-state DB commit 완료까지 45초 안에서 예약하고 Luna에 `min(35초, remaining-9초)`를 준다. 마지막 10초에는 새 도구를 시작하지 않는다.
4. 요청 캐시·single-flight와 중복 판단을 구현한다. 후속 호출은 대상·기간·페이지·근거 종류 등 정보 이득이 있을 때만 허용한다.
5. 명시 요구마다 answered/limited/clarify 상태를 추적하고 서버 커버리지 검사로 누락·중복을 막는다.
6. checkpoint·clarification·취소·lease·늦은 완료 거부는 현행 수명주기와 결합한다.

현재 오케스트레이터의 직접 도구 계획·호출, 0.70/0.35 잠정 임계값, 인용 서버 생성, Jev 의미 검증은 기준점으로 유지한다. 기존 12회·60초 상수와 별도 coverage 단계 가정은 새 StageLimits로 교체한다.

### 단계 3 — Jev router와 Luna Responses MCP

1. Jev router는 요구별 Q 유형·확률·명시 여부를 typed schema로 반환한다. 명시 요구는 확률만으로 제거하지 않는다.
2. 서버가 승인 capability를 실제 MCP 도구로 매핑하고 `allowed_tools`를 만든다. Q01에는 web.search를 노출하지 않는다.
3. ai/service의 Luna 호출을 Chat Completions에서 Responses(`reasoning.effort=medium`, `store=true`, `previous_response_id` continuation)로 옮기고 response ID를 영수증에 기록하며 원격 MCP URL, 짧은 서비스 토큰, allowed_tools, deadline·usage 수집을 구현한다.
4. ai/service가 `mcp_approval_request`를 받으면 response/request ID와 typed 호출 정보를 Java에 반환한다. Java가 승인 원장을 기록하고 같은 job에서 ai/service continuation endpoint를 다시 호출하며, ai/service는 Java 결정만 `mcp_approval_response`로 전달한다.
5. Luna는 승인된 도구 결과를 보고 후속 도구를 선택하고 최종 구조화 답변을 만든다. 독립 Luna coverage-verifier 호출은 두지 않는다.
6. route·approval request/decision·MCP call·continuation·generation·semantic-verification을 서로 다른 stage/receipt로 기록한다.
7. 이전 2턴 문맥은 서버가 검증된 대상 ID·기간만 정규화해 전달한다.

현재 상태(2026-10-28, AI 쪽): `zoop-ai-chat-1`에 새 단계 `chat-agent`를 추가했다(기존 `chat-answer`는 direct 시작 경로용으로 유지). 한 단계 = Luna Responses 요청 1회(`/responses`, `gpt-6-luna`·`medium`·`store=true`, ZOOP MCP 도구 하나·`require_approval=always`·`allowed_tools`, grant는 도구의 `authorization`으로 매 단계 전송, 서버 URL은 요청이 아닌 운영자 설정 `ZOOP_AI_CHAT_MCP_SERVER_URL`만, 답변 형식은 `chat-answer`와 같은 `ChatAnswer` strict schema)이며, 첫 단계는 turns·requirements를, 이어지는 단계는 `continuation.previousResponseId`와 Java의 승인 결정을 `mcp_approval_response`로만 전달한다. 결과는 `approval_required`(보류된 호출 목록, 답변 없음) 또는 `completed`(최종 답변과 그 단계의 MCP 호출 요약)다. AI runtime은 승인하지 않고, 다른 서버·허용 밖 도구·알 수 없는 출력 항목·`incomplete`는 확정 실패다. MCP grant 토큰은 공급자에만 전송하고 ledger 식별값·digest·저장 원응답에서 제외한다. 단계마다 Java가 새 invocation id를 쓰므로 기존 1회 전송·unknown 규칙이 단계별로 그대로 적용된다. 생성 OpenAPI(`docs/api/internal-ai-openapi.*`)를 갱신했다. 실제 Responses·MCP 응답 형태는 합성 replay로만 확인했으며 승인된 소량 live spike에서 확인한다.

현재 상태(2026-10-28, Java 쪽): agent 경로를 연결했다(`ZOOP_CHAT_AGENT_ENABLED` 기본 꺼짐, `/mcp`·모델 단계 필요, MCP 서버 URL은 AI 쪽 운영자 설정 `ZOOP_AI_CHAT_MCP_SERVER_URL`). 라우터·계획은 그대로이고, 읽기가 모두 독립 1단계이며 MCP로 노출된 계획만 agent 경로다(Q07 본인 범위·의존 단계·읽기 없는 계획은 direct). Java가 grant를 발급하고 `chat-agent` 단계를 부르며, 요구마다 planner가 해석한 대상 ID를 `targets`로 넘긴다. 승인 요청은 run의 허용 도구이면서 `ChatMcpTools.approve`가 예약에 성공한 것만 승인하고, 승인 라운드는 최대 3회이며 마지막·시간 부족 시 모두 거부해 다음 단계가 답을 쓰게 한다. `/mcp`는 성공 결과 봉투를 `chat_tool_calls.result`(migration `V20261028140000`)에 남기고, 오케스트레이터는 그 결과로 branch를 만들어 기존 결정론 검사·인용·Jev 검증·결과 생성을 그대로 거친다. 단계 대기 한도는 `min(35초, 남은 시간 − 검증·서버)`, 10초 미만이면 `deadline_guard`다. `/mcp` 결과는 원장 기록·반환 전에 운영자 챗봇 grant 레지스트리(AI runtime과 같은 파일)로 출처마다 `chat-agent` 목적·agent 수신자의 모델 전송 grant를 확인하고, 허용되지 않은 항목·근거 ID·경로는 통째로 빼고 개수만 `withheld`로 남긴다(판단할 수 없으면 호출 거부). 예산(2026-10-29): job 단위 호출 상한 6회(8/6/2의 내부 몫, 웹 2회는 웹 검색 도구와 함께, rerun 포함), agent 라운드당 승인 4건(job 동시 4), fan-out 5 초과 계획은 direct, agent run 45초(run 기한을 앞당겨 검증·저장까지 강제)·Luna 합산 35초(job 기한 60초는 direct 경로용으로 유지). 남은 것: 요청 캐시·single-flight·job당 결과 1 MiB, 승인 요청의 요구 매핑, live spike([챗봇 MCP 엔드포인트](../../api/docs/chat-mcp.md) 5절).

### 단계 4 — Tool Service, MCP 서버, 웹

1. 기존 공개 읽기 어댑터를 단일 Tool Service 뒤에 둔다. 직접 경로와 MCP 경로가 동일한 schema·scope·snapshot·결과 정규화를 사용하게 한다.
2. Java 앱에 인증된 HTTPS Streamable HTTP `/mcp`를 추가한다. request 64 KiB, 정규화 result 256 KiB/호출·1 MiB/job, token당 분당 30요청, job당 8회·동시 4회, 절대 deadline을 적용한다. 고정 출발지 범위가 계약으로 제공되기 전 IP allowlist를 유일한 인증으로 쓰지 않는다. Python은 앱 DB를 직접 읽지 않는다.
3. MCP 결과를 OpenAI에 반환하기 전 source/model-send grant를 확인한다. cache hit도 다시 확인한다.
4. Responses 시작 전 health preflight 실패·circuit open이면 direct 경로를 선택한다. 실행 중 MCP 오류는 direct 결과로 대체하지 않고 다음 job을 위한 circuit 통계만 갱신한다. 권한·grant·스키마 거부는 direct 우회 금지다.
5. Q02는 웹을 기본 보조로, Q03~Q08은 내부 근거가 부족한 마지막 단계로 둔다. Q01은 등록 자체를 거부한다.
6. 검색 0건·timeout·unavailable을 분리하며 웹 실패로 job을 실패시키지 않는다. 공급자·권리·보관·개인정보·일일 상한은 활성화 전에 고정한다.

Q07의 `portfolio.scope.read`는 Java server-only precondition으로 실행하며 MCP catalog에 등록하지 않는다. 전체 보유 목록·수량·보유 표시는 OpenAI에 보내지 않고 scope 안에서 일치한 공개 결과만 최대 5개로 최소화한다. 초기 MCP 도구 연결은 `company.read`, `issue.read`, `evidence.resolve`, 공개 그래프 경로/버전 차이, 브리핑 순으로 수직 구현한다. direct와 MCP fixture 동등성 시험을 각 도구에 붙인다.

현재 상태(2026-10-28, MCP 서버 단독 1단계): Java `POST /mcp`를 공식 MCP Java SDK 2.1.0의 stateless servlet transport로 구현했다(`com.zoop.chat.mcp`, 기능 플래그 `ZOOP_CHAT_MCP_ENABLED` 기본 꺼짐). job·attempt·graphVersion·asOf·subject scope·도구·deadline에 결속한 HMAC grant 토큰, 서버 승인 = `chat_tool_calls` 예약(정확한 요청 digest)과 일치하는 호출만 1회 실행, `Origin` 거부, request 64 KiB, result 256 KiB/호출, 토큰당 분당 30요청(인스턴스별)을 적용한다. 도구는 `portfolio.scope.read`를 뺀 레지스트리 바인딩이며 기존 `ChatToolRunner`·`chat_tool_calls`(`request_meta.via=mcp`)로 실행돼 direct 경로와 같은 읽기를 쓴다. 모델은 `targets`·`limit`만 정하고 버전·asOf·근거 선택 범위·비교 기간은 서버가 주입한다. 아직 없는 것(모델 전송 grant 검사는 이후 구현): job당 1 MiB·8/6/2·동시 4회(job 단위)·요청 캐시, 4번 preflight·circuit, ai/service Responses 연결. 그래서 로컬 합성 시험 밖에서는 켜지 않는다([챗봇 MCP 엔드포인트](../../api/docs/chat-mcp.md)).

### 단계 5 — 답변 생성·부분 결과·검증

1. Luna Responses 출력은 requirement별 section·claim·citation·limitation·uiAction 후보를 typed schema로 반환한다.
2. 서버가 schema, requirement coverage, citation 접근성, 수치·인과·금지 표현, 웹/내부 근거 분리를 결정론적으로 검사한다.
3. 별도 Jev semantic-verification은 근거 claim의 supported/hold/contradicted와 일반 구간 prohibitedAdvice를 검사한다.
4. 검증된 요구가 일부면 `answered + answerStatus=partial`, 전부면 complete, 답할 것이 없으면 기존 guidance/insufficient_evidence를 사용한다.
5. 웹 장애는 `notices.web_unavailable`로 남기고 외부 확인이 필요한 미충족 요구만 limitation으로 둔다.
6. 검증 실패·권한 거부·저장 실패는 기존 ChatFailure를 유지한다. 미검증 사실을 “항상 답변” 원칙으로 공개하지 않는다.

### 단계 6 — 공개 계약·웹 UI

1. answerStatus, notices, 새 limitation/error 원인을 DTO·migration·OpenAPI·생성 클라이언트·웹 타입에 동시에 추가한다.
2. graphTargets는 도메인 대상을, uiActions는 서버가 대상에서 파생한 표시 동작을 담당한다. 모델 생성 URL은 거부한다.
3. 클릭은 기존 대상 API의 권한·404·버전 검사를 사용한다. polling·재열람으로 action을 자동 실행하지 않는다.
4. D-AI-01/01b/02/02b 화면 계약과 manifest/Figma를 구현 PR에서 함께 확인한다.

### 단계 7 — 평가·관측·점진 출시

1. 일반 MCP 클라이언트로 `/mcp` 인증·스키마·크기·rate limit·grant를 서버 단독 시험한다.
2. 실제 모델 키 없이 합성 Responses replay로 approval request/response·continuation·오류·unknown 모양을 시험한다.
3. 명시 승인을 받은 소량 live tunnel에서 합성 데이터만 사용해 도구 1·4·8회와 approval 1·3라운드의 p50/p95·토큰·비용을 측정한다. CI는 앞의 두 계층만 필수로 실행한다.
4. `chat_tool_calls`와 `ai_executions`로 호출·승인·지연·오류·토큰·비용을 분리 집계한다.
5. Q01 문서 경로 → Q02 웹 보조 → Q03 사실 → Q04/Q07 → Q05/Q06/Q08 순으로 feature flag를 연다.
6. 고정 평가와 보안 시험을 통과한 registry/model/prompt/policy 조합만 활성화한다.

현재 상태: 모델·도구 호출 원장과 다수의 단위·PostgreSQL 시험은 있다. 고정 평가 세트 `chat-eval-v1`(45문항: Q01~Q08·복합·투자 판단·공격·확인 질문·장애)은 질문 문장부터 실제 요구 분해·이름 해석·계획·읽기 도구·검사를 거치고 모델 세 단계만 대본으로 바꿔 기본 `test`에서 돈다([고정 평가 세트](ai-chatbot-eval-set.md)). 흐름 회귀만 확인하며, 실제 모델·데이터로 잰 챗봇 한국어 금융 평가 보정과 실제 배포·종단 출시 증명은 없다. live gate와 질문 접수 플래그는 기본 비활성이다.

## 4. 내부 챗봇 계약에 필요한 최소 스키마

`internal-ai-openapi.yaml`은 서비스 코드에서 생성되는 구현 계약이므로 손으로 수정하지 않는다. 현재 구현 계약은 stage별 `StageRequest`/`StageResult`이고, 아래 표는 Luna MCP 실행·서버 coverage·claim 검증까지 포함한 목표 상위 계약이다. 표의 항목이 모두 현재 wire에 존재한다고 해석하지 않는다.

| 계약 | 필수 내용 |
| --- | --- |
| `ChatOrchestrationSubmit` | schemaVersion, jobId, attemptNo, question, frozenContext, requirements, policyVersion, registryVersion, budget, server-issued principal scope reference |
| `ChatRouteDecision` | requirementId별 Q type·probability·required, capability 후보, model/prompt version, typed validation result |
| `ChatRequirementCoverage` | 서버가 계산한 requirementId별 answered/limited/clarify/pending, 사용한 toolCallId, 남은 이유 |
| `ChatToolAllowance` | allowed capability·MCP tool, schema/policy revision, subject scope, version/asOf, 8/6/2 budget·deadline |
| `ChatCheckpointResult` | stage, observed count, truncated, decision(continue/clarify/limit/none_found/insufficient), 생성한 choice id |
| `ChatToolResult` | logicalCallId, transport(mcp/direct/cache), capabilityId, dataVersion, items, evidenceIds, coverageStatus, truncated, cachedFrom, error |
| `ChatGeneratedAnswer` | requirementId별 answer/limitation, sections·claims·citation refs·graphTargets·uiAction 후보. answerBasis·answerStatus·notices는 서버가 확정 |
| `ChatSemanticVerification` | schemaVersion, model, policyVersion, 근거 구간 claim별 claimId·sectionId·requirementId·Choice 분포·confidence·Noul 확률·판정(supported/contradicted/insufficient/hold), `general_knowledge` 구간별 sectionId·`prohibitedAdvice` 확률·판정, receipt artifact ID |
| `ChatValidationReport` | deterministic check IDs·pass/fail, failing requirement/claim/citation, semantic verification 요약(호출 여부·전체 판정·hold로 제외한 requirementId), requirementId별 answered/limited 판정과 limitation 결정 근거, final answerBasis, final limitations, policyVersion |

내부 응답에는 provider 원문 응답·비밀·자유 형식 추론을 넣지 않는다. 앱 completed는 AI 서비스가 ready를 반환한 시점이 아니라 Java가 artifact·영수증·도구 호출·검증 결과를 확인하고 DB에 원자 저장한 뒤에만 전이한다.

## 5. 다음 PR 범위

1. latency spike: MCP 서버 단독 시험, 합성 Responses replay, 승인된 소량 live 도구 1·4·8회 측정
2. StageLimits 8/6/2·45초, 요청 캐시·single-flight, 서버 requirement coverage
3. Java Tool Service 추출, 원격 MCP endpoint·서비스 인증·크기/rate limit·grant, preflight direct 시작·circuit breaker
4. ai/service Luna Responses 전환, allowed_tools·Java 승인 continuation·usage/deadline
5. answerStatus/notices·부분 결과·재열람 guard의 DTO·migration·OpenAPI·웹 동시 변경
6. Q01~Q08 수직 도구, 웹 공급자·권리·개인정보·일일 한도
7. 고정 fixture·live eval·부하·장애 시험과 기능 플래그 단계 활성화

각 PR은 현재 저장·멱등·권한·호출 원장을 유지한다. MCP 서버와 Responses 연결만 먼저 합쳐 공개 계약을 앞서 내보내지 않는다.

## 6. 필수 테스트 목록

아래는 목표 완료 matrix다. 기존 테스트가 일부 행을 다루더라도 행 전체가 통과했다고 자동 선언하지 않는다.

| 구분 | 필수 사례 |
| --- | --- |
| 인증 | 비회원 401/403, 타인 세션·job 접근 차단, Q07 서버 범위 주입 |
| 멱등성 | 같은 키·본문 재전송, 같은 키·다른 본문 충돌, 처리 중 재전송 |
| 동시성 | 대화당 활성 job 하나, 취소와 늦은 완료 경합, lease 만료 회수 |
| 라우팅 | 8유형 단일·복합, 명시 요구 보존, 4개 이상 유형, 낮은 확률 필수 요구 |
| 계획 | 미등록 도구, approval을 Java만 결정, 중복 제거, 의존·병렬 순서, 8회(내부 6·웹 2)·4동시·총 3라운드·fan-out 5 한도, 요청 cache·single-flight |
| 체크포인트 | `exactly(2)`에 0개(잘림 없음 → 없음 답변, 잘림 → 근거 부족, 도구 오류 → 개수 평가 없이 failed)·1개·2개·3개 이상, 조합 6개 초과 시 자유 입력, 초과 시 다음 단계·생성 호출 0회, 선택 후 새 job이 같은 asOf로 같은 결과 재현, fan-out 상한 초과 |
| 데이터 | graphVersion 고정, 문서 철회, citation offset, 브리핑 회차, 기간 경계 |
| 그래프 | 챗봇 경로가 같은 graphVersion의 `/api/v1/graph` 결과와 일치, 공개 제외 결정 반영 후 철회 간선 미노출, 공개 활성화 이력이 없는 버전·사용 불가 버전 거부, 이전 공개 버전은 현재 공개 제외 결정을 적용해 조회(Q05), 기업 간 hop 1·2·3과 4 거부, 노드·간선 50개 절단 시 `truncated`, graphTargets가 지도에서 열림, Neo4j·AI 내부 그래프 API 호출 0회 |
| 결과 | answerBasis를 sections에서 계산(단일·mixed·none), `zoop_documented` 구간의 `zoop_doc` 인용과 `evidence_grounded` 구간의 `article` 인용 교차 사용 거부, 이어 붙인 answer 12,000자 초과 거부, Q02 검색 성공은 web_reported, 검색 0건·장애는 제한된 general_knowledge와 notice, Q02+Q03은 mixed와 구간별 인용, 일반 개념 구간의 근거 연결·최신 사실 거부, 고정 안내 중복 없음, clarification 새 job, answerStatus complete/partial/guidance |
| 제한 | 투자 판단 혼합 질문의 `investment_advice`, 체크포인트 미달 `precondition_unmet`, 문서 20개 잘림 `results_truncated`, 한 요구만 근거 부족, 요구 누락·중복 소속·본문의 제한 요구 답변 시 `validation_failed`, 모델이 근거 없이 제안한 제한 거부, 내부 필수 도구 timeout은 failure, 보조 웹 timeout은 notice와 필요 시 limitation, answered 외 outcome 계약 |
| 확인 답 | 선택지 답·자유 입력 답, 없는 choiceId·clarification 아닌 원 작업·다른 대화 원 작업 422/404, resolves+context 422, 원 고정 문맥 복사, 원 작업 불변, 같은 확인 질문 재답변, 깊이 2 작업의 모호·체크포인트 초과는 `guidance`와 다음 단계·생성 호출 0회, 깊이 2에서 모호함이 해소되면 `answered`·도구 장애는 `failed`(guidance로 바꾸지 않음), 확인 답의 답이 루트 질문과 사슬의 답을 순서대로 합쳐 재실행 |
| 의미 검증 | 1층 실패 시 Jev 0회, 일반 개념 구간은 Choice 없이 `prohibitedAdvice`만 판정하고 예이면 전체 실패, 전부 supported 통과, contradicted·prohibitedAdvice 예 전체 실패, 한 요구 hold 시 그 구간·통합 구간 제외와 limitation 및 answer·answerBasis·citations 재계산, 모든 요구 hold 시 insufficient_evidence, 응답 형식 오류 시 영수증 저장 후 transient |
| 장애 | preflight direct 시작, 실행 중 MCP 오류 direct 대체 0회, auth/grant/schema 우회 0회, Jev/Luna timeout, unknown, 저장 실패 |
| 기한·한도 | terminal-state DB commit까지 job 45초, Luna min(35초, remaining-9초), 마지막 10초 신규 도구 금지, DB 3초·그래프 5초·웹 7초, 8/6/2 원자 예약, cache hit·direct 조회·실패 시도 집계, response_unknown 재호출 0회, 입력 24k·출력 2k, 실행 3회 뒤 retry null, lease 만료 뒤 늦은 완료 거부 |
| UI | 새로고침 복구, 조회 오류 재확인, late response 폐기, 접근성·모바일 |
| 관측 | 모델·도구 호출 중복 집계 없음, 미보고 비용 NULL, 요청 ID 연계 |
