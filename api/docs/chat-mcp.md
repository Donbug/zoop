# 챗봇 MCP 엔드포인트 (`POST /mcp`)

기준: [Luna MCP 실행 계약](../../docs/design/ai-chatbot-mcp-actions.md) 3장, [개발 계획](../../docs/development/ai-chatbot-implementation-plan.md) 단계 4 · 화면 추적 `D-AI-02`

상태: MCP 서버(1단계), agent 경로(단계 3: Luna Responses `chat-agent` + Java 승인 루프), 결과의 모델 전송 grant 검사 구현. 두 기능 플래그 모두 기본 꺼짐. live 호출은 아직 하지 않았다(합성 replay·fake로만 시험).

## 1. 무엇을 하는가

실행 중인 챗봇 job 한 attempt의 읽기 도구를 MCP(Streamable HTTP) 도구로 연다. 목표 흐름에서 OpenAI Responses 런타임이 Luna가 고른 도구를 이 경로로 호출한다. 이는 기존 "앱 BE ↔ AI는 ai/service HTTP로만" 경계에 **모델 공급자 런타임 → 앱 `/mcp` 인바운드**를 더하는 변경이다(ZOOP-AIG-001 v0.11 6.3.2).

- 위치: 앱 데이터 소유자인 Java API JVM 안. Python(ai/service·worker)은 이 경로로 앱 DB를 읽지 않는다.
- 구현: 공식 MCP Java SDK 2.1.0(`mcp-core`, `mcp-json-jackson3`)의 서블릿 stateless transport(`HttpServletStatelessServerTransport`)와 `McpStatelessSyncServer`. 2.0.x에는 grant별 도구 목록 필터(`McpSyncListFilter`)가 없어 2.1.0을 쓴다.
- 프로토콜: `POST /mcp`, 요청마다 JSON 응답. 세션·SSE 스트림 없음(GET은 405). 메서드는 `initialize`, `ping`, `tools/list`, `tools/call`. 서버 기능은 tools뿐이다.
- 같은 읽기: 도구는 `ChatToolRegistry`의 바인딩을 그대로 `ChatToolRunner`로 실행한다. 업무 로직을 복제하지 않으며 결과는 기존 `chat-tool/v1` 봉투다.

## 2. 접근 gate (`ChatMcpAccessFilter`)

MCP 메시지를 읽기 전에 순서대로 검사한다.

| 조건 | 응답 |
| --- | --- |
| `Origin` 헤더가 있음(브라우저) | 403 |
| `Authorization: Bearer <grant>`가 없거나 검증 실패·만료 | 401, `WWW-Authenticate: Bearer` |
| 같은 토큰이 이 인스턴스에서 1분에 30회 초과 | 429, `Retry-After: 60` |
| 본문 64 KiB 초과 | 413 (SDK transport) |

### grant 토큰 (`ChatMcpGrants`)

`zmcp1.<keyId>.<payload>.<mac>`. payload는 정규화 JSON `{job, attempt, tools, graphVersion, asOf, scope, exp}`이고 mac은 전용 purpose의 HMAC-SHA256이다(둘 다 base64url).

- 서버만 발급한다. `exp`는 run deadline이며 job·attempt·graphVersion·asOf에 결속된다.
- `scope`는 subject 범위 digest(회원 + 서버가 주입하는 근거 선택 범위·선택 기간)다. 회원 ID를 평문으로 담지 않으며, 호출 시 run에서 다시 계산한 값과 다르면 `grant_mismatch`다.
- grant는 문을 여는 것까지다. 실제 호출은 아래 "호출 승인"에서 서버가 승인한 정확한 호출과 일치해야 실행된다.
- `portfolio.scope.read`는 발급 단계에서 거부한다(Q07 본인 범위는 Java가 먼저 고정, 모델 비노출).
- 키: `ZOOP_CHAT_MCP_ACTIVE_KEY_ID`, `ZOOP_CHAT_MCP_KEYS`(`id=base64url`, 32바이트 이상, 쉼표 구분). 활성 키가 서명하고 나열된 키는 모두 검증하므로 회전할 수 있다. 토큰이 외부(모델 공급자)로 나가므로 CSRF 키와 분리한다. 모델 API 키와도 별개다.
- 토큰·키는 로그에 쓰지 않는다. rate window는 검증에 쓴 토큰 문자열의 digest로 세므로 `Authorization` 헤더의 공백 변형도 같은 창을 쓴다.

호출마다 토큰의 job·attempt가 **지금 실행 중인 attempt**인지 DB에서 다시 확인한다(`ChatJobExecutor.attach`). 원장 쓰기는 run과 같은 owner-token·lease fence를 쓰므로 취소·만료·새 attempt 뒤의 호출은 아무것도 기록하지 않는다. owner token은 서버 밖으로 나가지 않는다.

## 3. 도구 (`ChatMcpTools`)

노출: 레지스트리에 바인딩된 기능 중 `portfolio.scope.read`를 뺀 전부. MCP 이름은 기능 ID의 `.`을 `_`로 바꾼 것(`company.read` → `company_read`)이며 `tools/list`는 grant가 허용한 도구만 보여 준다. 모든 도구는 `readOnlyHint=true`다.

모델이 정하는 인자는 둘뿐이고 나머지는 서버가 job의 고정 문맥에서 넣는다.

| 인자 | 규칙 |
| --- | --- |
| `targets` | 1~5개 서로 다른 ID 문자열(각 128자 이하). 고정 문서 읽기(`zoopPolicy_read`)에는 없음, `graph_version_diff`는 생략 시 공개 그래프 전체 |
| `limit` | 정수 1~20, 기본 20 |
| 그 밖의 키 | 거부(`additionalProperties: false`, 서버 재검사) |

서버 주입: graphVersion·asOf(job 고정), 회원이 좁힌 근거 선택 범위(`evidenceIds`가 있으면 `evidencePool`), `graph.version.diff`의 비교 시작 시각(job의 선택 기간), 고정 ZOOP 문서.

### 호출 승인 (승인 = 원장 예약)

`require_approval=always`에서 Java가 모델의 `mcp_approval_request`를 승인할 때 `ChatMcpTools.approve(attached, 도구, 인자)`를 부른다. 승인은 그 정확한 호출(도구 + 정규화 요청: targets·limit·서버 주입값)을 `chat_tool_calls`에 `reserved`로 예약하고 `input_digest`로 식별한다.

- `/mcp`의 `tools/call`은 같은 attempt에 같은 기능·같은 digest로 **아직 시작되지 않은 예약**이 있을 때만 실행하며, 예약을 고르는 것과 `running`으로 바꾸는 것을 한 문장(`UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED) RETURNING`, owner fence)으로 해서 한 번만 소비한다(`ChatRunControl.claimToolCall`). 같은 요청이 동시에 와도 각자 다른 예약을 잡는다. 없으면 `call_not_approved`이고 아무것도 읽지 않는다. 승인받지 않은 target, 다른 limit, 이미 쓴 승인은 모두 여기서 막힌다.
- 승인 시점에 예약되므로 job 호출 상한(6회, 아래 "예산")을 원자적으로 차감한다. 상한은 job 단위라 재실행(rerun)한 attempt도 이전 attempt가 실제로 한 호출(실행되지 않고 `cancelled`로 닫힌 예약 제외)을 뺀 나머지만 쓴다. 상한 초과 승인은 `tool_budget_exhausted`다.
- 승인됐지만 호출되지 않은 예약은 job이 끝날 때 기존 규칙대로 `cancelled`로 닫힌다.
- 이번 PR에는 `approve`를 부르는 실행 경로(ai/service의 approval request 전달)가 아직 없다. 계약과 강제 지점만 먼저 고정했다.

### 결과와 오류

성공은 `structuredContent`와 같은 JSON의 text content로 `chat-tool/v1` 봉투(`toolCallId`, `dataVersion`, `items`, `evidenceIds`, `truncated`, `nextAllowed`, 경로 읽기의 `paths`)를 돌려준다. 실패는 빈 성공이 아니라 `isError=true`와 코드다.

| 코드 | 뜻 |
| --- | --- |
| `tool_not_granted` | grant에 없는 도구 |
| `run_not_active` | job이 끝났거나 취소·만료·다른 attempt |
| `grant_mismatch` | grant의 graphVersion·asOf·subject scope가 job과 다름 |
| `invalid_arguments` | 인자 규칙 위반(아무것도 읽지 않음, 원장 기록 없음) |
| `call_not_approved` | 서버가 승인(예약)한 호출과 정확히 일치하지 않거나 이미 사용됨 |
| `tool_budget_exhausted` | (승인 시) job의 호출 상한(6회, 이전 attempt 포함) 도달 |
| `result_too_large` | 결과 256 KiB 초과. 직렬화 크기로 먼저 거르고, 기록할 때 **저장된 JSON 텍스트**(`jsonb::text`, 공백 정규화 후) 크기로 다시 검사한다. 어느 쪽이든 `failed`/`result_too_large`로 남기며 근거·dataVersion·결과는 기록하지 않음(컬럼 제약 위반으로 run이 멈추지 않음) |
| `job_results_too_large` | 이 결과를 남기면 job이 모델에 보낸 결과 합계가 1 MiB를 넘음. 기록 트랜잭션에서 job 행을 잠그고 검사해 `failed`로 남기며 결과는 보내지 않음 |
| `send_grants_unavailable` | 아래 모델 전송 gate가 판단할 수 없음(grant 레지스트리를 읽지 못함·형식 위반, 근거 출처를 읽지 못함). 읽기는 실행됐지만 결과를 보내지 않고 `failed`로 남김 |
| `tool_timeout` `tool_unavailable` `tool_failed` | 기존 runner 실패 코드(원장에 `failed`) |

등록되지 않은 이름(`portfolio_scope_read`, 점 포함 ID)은 SDK가 JSON-RPC `-32602 Unknown tool`로 답한다.

### 모델 전송 gate (`ChatMcpSendGate`, `ChatSendGrants`)

hosted MCP 결과는 ai/service의 전송 gate를 거치지 않고 이 엔드포인트에서 OpenAI로 바로 간다. 그래서 `/mcp`는 성공 결과를 원장에 기록하고 돌려주기 **전에** 출처마다 모델 전송 grant를 확인하고, 허용되지 않은 부분은 결과에서 뺀다.

- **grant 원본**: AI runtime이 `--grants`로 읽는 운영자 챗봇 grant 레지스트리(`zoop-ai-chat-1`) **같은 파일**을 `ZOOP_CHAT_MCP_SEND_GRANTS`(절대·정규화 경로)로 읽는다. 결과마다 다시 읽으므로 철회는 다음 결과부터 적용된다. 형식은 worker의 `ChatGrantRegistry`와 같이 엄격하게 본다(필드 누락·추가·중복 키, 모르는 rights·operation·목적, offset 없는 만료는 레지스트리 전체 거부).
- **규칙**: worker의 `chat-agent` 단계 규칙과 같다. 같은 source의 grant가 `enabled`, `rights=known`, `model-send`, 목적에 `chat-agent`, 수신자에 `ZOOP_CHAT_MCP_SEND_RECIPIENT`(AI runtime이 `chat-agent` 단계에 쓰는 수신자, live `openai-compatible:<revision>`)가 있고 만료 전이어야 한다. `chat-agent` 목적은 그 단계의 Responses 저장(`store=true`)·continuation 재개를 포함하는 목적으로 등록한다.
- **수신자 결속**: Java가 검사한 수신자와 결과를 실제로 받는 수신자가 같아야 한다. Java는 agent 단계마다 `mcp.recipient`에 `ZOOP_CHAT_MCP_SEND_RECIPIENT`를 넣고, worker는 새 invocation을 보내기 전에 그 값이 그 단계의 실제 수신자(설정된 endpoint로 계산한 `openai-compatible:<revision>`, replay `authored-replay`)와 정확히 같은지 확인한다. 다르면 `mcp_recipient_mismatch`로 아무것도 보내지 않는다(Java에서는 거절된 모델 단계). 이 값은 공급자로 보내지 않는다.
- **출처 대응**: 기업 항목(이름) = `zoop-company-catalog`, 사건 제목·경로 단계(ID·관계 유형·역할, 이름 없음) = `zoop-graph`(새 source ID), 관계(엣지) 항목은 label이 양 끝 이름(기업명 포함)과 관계로 이루어진 복합 label이라 `zoop-graph`와 `zoop-company-catalog`가 **모두** 있어야 함, ZOOP 문서 제목 = `zoop-docs`, 근거(근거 항목의 label은 기사 제목) = direct 경로의 인용과 같은 규칙. 근거는 run의 고정 버전·asOf로 인용 읽기를 해서 기업 개요면 카탈로그, ZOOP 문서 구간이면 `zoop-docs`, 기사면 `articles.provider`(`CitedMcpSources`)이며 지금 인용할 수 없는 근거는 출처가 없어 보내지 않는다. 그 밖의 항목 종류도 보내지 않는다.
- **뺀 부분**: 허용되지 않은 항목·경로는 **통째로**, 근거 ID는 결과와 항목·경로 단계의 목록에서 모두 뺀다. 맨 ID도 보내지 않는다. 결과에는 `withheld: {reason: "source_grant_denied", items, evidenceIds, paths}`로 개수만 남는다(아무것도 빼지 않았으면 없음). 원장의 `evidence_ids`와 `chat_tool_calls.result`도 보낸 것만 담으므로, 최종 답 검사와 다음 라운드의 도달 가능한 ID에도 뺀 것은 들어가지 않는다.
- **시간**: 검사(레지스트리·근거 출처 읽기)는 읽기와 같은 스레드에서 그 호출의 시간 한도(3초, 그래프 계산 5초)와 runner 전체 슬롯 안에서 돈다. 느린 검사는 느린 읽기처럼 `tool_timeout`이 되고, 호출 기록 스레드를 붙잡지 않는다.
- **판단 불가**: 레지스트리를 읽지 못하거나 근거 출처를 읽지 못하면 빈 허용이 아니라 호출 거부(`send_grants_unavailable`)다. 설정이 없거나 기동 때 레지스트리를 읽지 못하면 `/mcp`를 켠 기동 자체가 실패한다.

### 같은 요청의 재사용 (요청 캐시·single-flight)

같은 attempt에서 **정확히 같은 정규화 요청**(기능 + 요청 digest: targets·limit·서버 주입 버전·asOf·근거 범위·비교 시작)은 한 번만 읽는다(MCP 실행 계약 3.3).

- 다시 오면 처음 성공해 남긴 결과(`chat_tool_calls.result`)를 재사용한다. 결과에는 자기 `toolCallId`와 함께 `cachedFrom`(처음 읽은 호출)을 붙인다. 재사용도 승인·예약된 호출 하나로 원장과 예산에 들어간다.
- 재사용 결과도 지금의 모델 전송 gate를 다시 거친다(grant 철회, 지금 인용할 수 없는 근거). 과거에 허용된 결과로 현재 차단을 우회하지 않는다.
- 요청은 먼저 자기 예약을 잡은 뒤(위 "호출 승인") 같은 요청이 읽는 중이면 그 읽기가 끝나길 기다렸다가(최대 12초, run 기한 안) 남긴 결과를 재사용한다. 첫 읽기가 실패했거나 기다림이 끝나면 직접 읽는다. 실패·timeout은 재사용하지 않는다.
- 기다림은 **같은 인스턴스 안에서만** 합류한다. 다른 인스턴스로 동시에 온 같은 요청은 각자 읽을 수 있다(나중에 오는 반복은 DB의 남긴 결과로 재사용).
- direct 경로는 서버가 한 단계의 같은 호출을 미리 합치므로(`ChatRetrieval`) 이 재사용을 쓰지 않는다. attempt가 바뀌면(rerun) 새로 읽는다.

### job당 결과 1 MiB

job의 호출이 모델용으로 남긴 결과(`chat_tool_calls.result`, 저장된 JSON 텍스트 기준)의 합은 attempt를 합쳐 1 MiB 이하다. 결과를 남기는 기록 트랜잭션에서 job 행을 잠근 뒤, 새 결과의 크기도 DB가 저장할 표현(`octet_length(CAST(:result AS jsonb)::text)`)으로 재서 합계를 검사하고 쓰므로 동시 호출에도, 표현 차이로도 넘지 않는다. 넘을 결과는 `failed`/`job_results_too_large`로 기록되고 보내지 않는다.

### 원장

MCP 호출도 `chat_tool_calls`에 기존 호출과 같은 상태(예약 → 실행 → 종료)로 남는다. 예약은 승인 때, 실행·종료는 `/mcp` 호출 때다. `plan_revision`은 1이고 `request_meta.via = "mcp"`로 경로를 구분한다. 스키마 변경(migration)은 없다.

## 4. agent 경로 (단계 3)

`zoop.chat.mcp.agent-enabled=true`(`ZOOP_CHAT_AGENT_ENABLED`)이고 `/mcp`, 챗봇 모델 단계(`zoop.ai.chat-client.enabled`)가 모두 있을 때만 `ChatMcpAgent`가 등록된다. 하나라도 없으면 기동을 거절한다(`/mcp`가 꺼진 채 agent만 켜도 `ChatAgentFlagCheck`가 거절해 direct 경로로 조용히 떨어지지 않는다). 공급자가 이 엔드포인트에 닿는 HTTPS 주소는 Java가 보내지 않고 AI runtime 운영자 설정 `ZOOP_AI_CHAT_MCP_SERVER_URL`로만 정한다(요청으로 지정 불가: grant가 다른 호스트로 가지 않게).

**어느 run이 타는가.** 라우터·계획은 그대로다. 계획의 읽기가 모두 **독립 1단계 읽기**이고 그 기능이 모두 MCP로 노출될 때만 agent 경로다. Q07 본인 범위(server-only `portfolio.scope.read` 선행), Q06 브리핑·Q08 선정 기록(`briefing.read`·`selectionRule.read`는 회차를 요구 문구에서 서버가 정하므로 MCP에 노출하지 않음), 의존 단계·체크포인트가 있는 계획, 읽기가 없는 계획(일반 개념·제한만)은 기존 direct 경로(서버가 읽고 Luna는 쓰기만)다.

**preflight·circuit.** agent에 맞는 계획은 첫 `chat-agent` 단계 전에 Java가 AI service의 `GET /internal/v1/chat-mcp-health`를 한 번 호출한다. `reachable`일 때만 agent를 시작하고, `unreachable` 또는 probe/service 오류면 그 run은 처음부터 기존 direct 조회·생성 경로를 쓴다. `reachable` probe는 circuit이 닫혀 있고 그 뒤 연결 실패가 없는 동안 10초 재사용한다(연속 run마다 worker 프로세스와 공개 URL 왕복을 반복하지 않음). replay 모드 run은 MCP endpoint에 닿지 않으므로 preflight를 하지 않는다. 최근 연결 관측 5회 중 timeout·connect 실패·앞단 gateway의 502/503/504(`mcp_unavailable`)/실행 중 `mcp_unreachable`가 3회면 endpoint별 인스턴스 circuit을 30초 열며, 그동안 probe 없이 direct로 시작한다. 30초 뒤에는 동시 요청 중 하나만 half-open probe를 보내고 나머지는 direct로 시작한다. 성공하면 창을 비우고 닫고, 실패·probe 오류면 다시 30초 연다. 그 밖의 예상 밖 HTTP 상태(401/403 포함), 정책·grant·schema 거부, DB 오류, AI service probe 오류는 연결 실패 창에 넣지 않는다. route 요약은 읽기가 있는 run마다 `path`(`agent`·`direct`)를 남기고, agent 후보였지만 preflight가 막은 run에는 `agentPreflight=unavailable`을 더한다.

agent 단계가 하나라도 시작된 뒤의 `mcp_unreachable`는 **같은 run에서 direct 결과로 대체하지 않는다**. 해당 run은 기존 모델 실패 규칙으로 끝나고 이 관측만 다음 run의 circuit 선택에 반영한다. 따라서 direct 선택은 Responses 시작 전 한 곳에서만 일어난다.

**흐름.**
1. Java가 run의 grant 토큰을 발급하고 `chat-agent` 1단계를 부른다. 요구마다 planner가 해석한 대상 ID(`targets`)를 넘기고, 허용 도구는 계획의 기능만이다.
2. 단계가 `approval_required`로 멈추면 Java가 요청마다 결정한다. **run의 허용 도구이고, `targets`의 모든 ID가 도달 가능하며, `ChatMcpTools.approve`가 예약에 성공한 호출만 승인**하고 나머지는 거부한다. 도달 가능한 ID는 첫 라운드엔 요구의 해석된 `targets`, 다음 라운드부터는 거기에 이전에 승인·실행된 결과의 항목·기업·경로 양끝·단계·근거 ID를 더한 서버 소유 목록이다. `targets`가 없는 호출(고정 문서, 버전 비교 전체 그래프)은 인자 검사만 거친다. 웹 검색(`web_search`)은 ID 대신 검색어를 받으므로 도달 가능 ID 대신 "앞 라운드의 내부 조회가 0건이거나 잘렸을 때만"과 검색어 검사·웹 예산으로 판단한다([챗봇 보조 웹 검색 도구](chat-web-search.md) 5장). 프롬프트의 "ID를 추측하지 않는다"와 공급자의 `allowed_tools`는 서버 검사를 대신하지 않는다. 결정을 continuation(`previous_response_id`)으로 보내면 공급자가 승인된 호출만 `/mcp`로 실행한다.
3. 승인 라운드는 최대 3회이고, 한 라운드에 최대 4건만 승인한다(나머지는 거부, Luna는 다음 라운드에 다시 요청 가능). 공급자는 라운드의 승인 호출을 마친 뒤 단계를 답하므로 job의 동시 실행이 4개를 넘지 않는다. 다음 단계 하나만 할 시간이 남거나 라운드를 다 쓰면 남은 요청을 모두 거부해 그 단계가 답을 쓰게 한다. 그 뒤에도 묻는 run은 실패한 모델 단계다.
4. 최종 답은 **실행된 호출의 결과로** 검사한다. `/mcp`는 성공 호출의 결과 봉투를 모델에 보낸 것과 같은 JSON으로 `chat_tool_calls.result`(jsonb, 256 KiB 이하, migration `V20261028140000`)에 남기고, Java는 그 결과로 branch를 만들어 기존 결정론 검사·인용·Jev 검증·결과 생성을 그대로 거친다. 어느 인스턴스가 `/mcp` 호출을 받았든 같은 PostgreSQL에서 읽는다. 읽은 결과는 `ChatToolRunner.restore`가 job·회원·시도·tool call·capability·고정 버전·asOf·입력 digest를 예약 기록과 대조한 뒤에만 이 run의 조회로 되살리고(다르면 run은 `internal`로 끝난다), 모델 전송 gate가 항목을 뺀 결과는 잘린 결과로 되살린다. 같은 결과가 Jev 검증의 서버 사실(`graph_comparison`)이 된다([AI 연동](AI_INTEGRATION.md#챗봇-모델-단계-클라이언트)). 결과는 run의 요구들이 공유한다(승인 요청에 요구 ID가 아직 없다).

**시간.** agent run은 job 시작부터 **45초** 안에 검증·저장까지 끝낸다. agent 경로가 시작되면 run의 기한 자체를 시작 + 45초로 앞당긴다(`ChatRunControl.shortenDeadline`, DB `deadline_at`도 owner fence로 함께, 늦추지는 않음). 그래서 남은 시간 계산, 기록 대기, `/mcp`로 붙는 요청, 최종 저장의 지연 판정이 모두 45초를 따르며, 45초를 넘긴 결과는 60초 안이어도 완료로 저장하지 않는다(`deadline_guard`, 모델을 부른 뒤면 `response_unknown`). Luna 단계 전체(MCP 왕복·승인 continuation·도구·최종 답)는 `min(35초, 45초 중 남은 시간 − 검증·서버 예약 14초)`이고, 각 단계는 그 남은 예산까지만 기다린다. 예산이 답 작성용 10초보다 작으면 시작하지 않고 `deadline_guard`, 남은 예산이 20초 미만이면 마지막 단계로 보고 새 도구를 승인하지 않는다(마지막 10초 신규 도구 금지). direct 경로는 router·도구·답 작성·검증 단계 한도(합 63초)가 45초에 들어가지 않아, 실측으로 다시 정할 때까지 job 기한 60초를 그대로 쓴다.

**fan-out.** 대상이 5개(한 호출의 `targets` 상한)를 넘는 요구가 있는 계획은 agent 경로를 타지 않고 direct 경로에서 서버가 5개씩 나눠 읽는다. route 요약에 `path=agent`, `agentSteps`, `approvedCalls`, `deniedCalls`를 남긴다.

## 5. 켜기 전에 남은 조건

아래가 끝나기 전에는 로컬 합성 시험 밖에서 `ZOOP_CHAT_MCP_ENABLED`·`ZOOP_CHAT_AGENT_ENABLED`를 켜지 않는다.

1. ~~**model-send grant 검사.**~~ 구현(3장 "모델 전송 gate"). 켜기 전에 운영자가 레지스트리에 `chat-agent` 목적·agent 수신자 grant와 `zoop-graph` source를 등록하고, OpenAI 보유 조건을 거버넌스 10장에 기록해야 한다.
2. **예산**(단계 2): job 단위 호출 상한 6회(내부 몫, 웹 2회는 웹 검색 도구와 함께. rerun은 남은 호출만 쓰고, 계획에 모자라면 `budget_exceeded`로 재실행 불가), agent 라운드당 승인 4건(동시 4개), fan-out 5, agent run 45초(검증·저장까지)·Luna 35초는 구현했다. 요청 캐시·single-flight(인스턴스 안)·재사용 시 gate 재검사·job당 결과 1 MiB도 구현했다(3장). 도구별 시간은 일반 읽기 3초·그래프 계산(`zoop-graph-read`: `graph.path.read`·`graph.version.diff`) 5초로 구현했다(단계 10초와 run 기한으로 줄어듦). 웹 검색 도구의 호출당 7초, job당 웹 2회(내부 6회와 별도), 회원 하루 20회·프로젝트 하루 500회 원자 예약도 구현했다([챗봇 보조 웹 검색 도구](chat-web-search.md), 서버 웹 단계 연결 전). 남은 것: direct 경로 45초(단계 한도 실측 후), 인스턴스를 넘는 single-flight(필요하면). rate limit은 인스턴스별이다.
3. ~~**preflight·circuit breaker.**~~ 구현. AI runtime의 무과금 health probe와 Java의 5회/3실패·30초·단일 half-open probe, 시작 전 direct 선택, 실행 중 무대체를 적용했다.
4. **승인 요청의 요구 매핑**: 지금은 결과를 run의 요구들이 공유한다. 요구별 인용 결속이 필요하면 승인 요청에 requirementIds를 받도록 계약을 넓힌다.
5. **네트워크·운영**: HTTPS 인바운드 노출 범위, 공급자 출발지 제한 여부(IP allowlist만으로 인증하지 않음), 승인된 소량 live latency spike(실제 Responses·MCP 응답 형태 확인 포함). Spike의 승인·합성 데이터·무내용 증거·통과 gate는 [챗봇 MCP live latency spike](../../docs/development/chat-live-spike.md)에 고정했다. HTTPS·출발지 제한 선택, model-send grant, `store=true` 보유 조건·외부 처리 고지, 키 회전, 사고·증거 보존 책임은 [운영 readiness gate](../../docs/development/chat-operations-readiness.md)가 같은 후보 commit의 통과한 spike와 함께 검사한다. 이 검사는 배포나 플래그 변경을 하지 않는다. 웹 도구는 있지만 아직 어떤 계획도 웹을 쓰지 않아 총 8회 시나리오는 실행할 수 없으므로, 서버 웹 단계가 연결되기 전에는 gate를 통과로 기록하지 않는다.

## 6. 시험

```sh
./api/gradlew -p api test --tests 'com.zoop.chat.mcp.*'
```

- `ChatMcpGrantsTest`: 발급·검증, 변조·잘림·다른 키, deadline 만료, 키 회전, subject scope(회원별 차이, 평문 회원 ID 없음), `portfolio.scope.read` 거부, 키 설정 오류(값 비노출).
- `ChatMcpEndpointTest`: 실제 SDK servlet transport·server와 메모리 job 저장소로 401/403/413/429(헤더 공백 변형도 같은 창), `initialize`, grant별 `tools/list`, 승인된 호출 1회 실행과 원장 기록(`via=mcp`), 미승인·다른 target·다른 limit·재사용 거부, 다른 attempt·다른 subject·종료된 run 무조회, 승인 시 호출 상한, `result_too_large`의 원장 실패 기록, grant 없는 출처의 근거를 결과·원장에서 빼고 `withheld`로 표시, 레지스트리를 읽지 못하면 `send_grants_unavailable`.
- `ChatSendGrantsTest`: `chat-agent` 규칙(비활성·rights·`model-send` 없음·목적·수신자·만료 거부), 매번 다시 읽어 철회 즉시 적용, 없음·형식 위반·추가 필드·중복 키·크기 초과 레지스트리는 전부 거부, 설정 검증.
- `ChatMcpSendGateTest`: 출처별 항목·경로·근거 ID 제외와 개수, 그래프 grant 없으면 사건·관계·경로 제외, 실제 `graph.version.diff`(합성 fixture)에서 카탈로그 grant가 없으면 기업과 함께 관계 label도 제외(기업명 우회 없음), 모르는 항목 종류 제외, 레지스트리 판단 불가.
- `CitedMcpSourcesTest`: 인용 종류별 출처(기사 공급자·카탈로그·ZOOP 문서), 인용할 수 없는 근거는 출처 없음, DB 오류는 판단 불가.
- `ChatExecutorPostgresTest`(PostgreSQL): `attach`와 fence, 예약 호출 조회(`findReservedToolCall`)의 기능·digest·attempt 일치와 시작 뒤 소멸, `chat_tool_calls.result` 보관(성공만)과 크기·상태 제약, 보관된 결과가 예약 기록·회원과 함께 읽히고 jsonb 왕복 뒤에도 자기 run으로 복원됨.
- `ChatMcpAgentTest`(서버 사실): 같은 조회가 direct·agent 경로에서 같은 `graph_comparison`이 됨, 장부에서 복원한 결과가 다른 job·회원·attempt·tool call·버전·대상이면 복원 거부, 모델 전송 gate가 항목을 뺀 결과는 잘린 결과로 복원됨.
- `ChatMcpConfigurationTest`: 기본 꺼짐이면 bean·경로 없음, 켜고 키나 읽을 수 있는 grant 레지스트리가 없으면 기동 거절(경로 비노출), 둘 다 있으면 `/mcp` 등록, agent 경로의 모델 단계 요구, `/mcp` 없이 agent만 켜면 기동 거절.
- `ChatToolRunnerTest`(tool): 결과 검사가 멈추면 그 호출이 시간 한도로 끝나고 기록 스레드는 비어 다른 job의 direct 호출이 기록됨.
- worker `test_chat_agent.py`: 단계의 `mcp.recipient`가 실제 수신자와 다르면(live 다른 endpoint·replay 이름, replay에 live 이름) `mcp_recipient_mismatch`로 보내지 않음, 수신자는 공급자 요청에 없음.
- `ChatMcpAgentTest`: 실제 MCP 도구 위의 승인 루프. 승인된 호출만 실행되고 결과가 원장에서 돌아옴, 예약 불가·허용 밖 도구 거부, 해석되지도 승인 결과에 나오지도 않은 target·섞인 target·잘못된 모양 거부와 승인 결과로 도달한 target 승인, 3라운드 뒤 마무리 거부와 끝없이 묻는 run의 실패, 시간 부족 시 마무리, 종료된 run에서 중단, grant의 도구·만료.
- `ChatAgentPathEngineTest`(orchestrator): agent 경로를 타는 계획과 direct에 남는 계획(의존 단계·일반 개념·노출 안 된 도구), 실행 결과에 없는 근거 인용의 `validation_failed`, 단계 시간 부족의 `deadline_guard`.

모두 합성 job·합성 도구·scripted 모델이며 모델·네트워크·실제 데이터를 쓰지 않는다. 실제 OpenAI 런타임과의 상호 운용은 승인된 소량 live 시험에서 확인한다.
