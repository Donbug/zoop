# 챗봇 MCP 엔드포인트 (`POST /mcp`)

기준: [Luna MCP 실행 계약](../../docs/design/ai-chatbot-mcp-actions.md) 3장, [개발 계획](../../docs/development/ai-chatbot-implementation-plan.md) 단계 4 · 화면 추적 `D-AI-02`

상태: 1단계(MCP 서버 단독) 구현. 기능 플래그 기본 꺼짐. ai/service의 Luna Responses 연결과 승인 continuation은 아직 없으므로 지금은 어떤 모델도 이 경로를 호출하지 않는다.

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

`zmcp1.<keyId>.<payload>.<mac>`. payload는 정규화 JSON `{job, attempt, tools, graphVersion, asOf, exp}`이고 mac은 전용 purpose의 HMAC-SHA256이다(둘 다 base64url).

- 서버만 발급한다. `exp`는 run deadline이며 job·attempt·graphVersion·asOf에 결속된다. 회원 ID는 담지 않는다.
- `portfolio.scope.read`는 발급 단계에서 거부한다(Q07 본인 범위는 Java가 먼저 고정, 모델 비노출).
- 키: `ZOOP_CHAT_MCP_ACTIVE_KEY_ID`, `ZOOP_CHAT_MCP_KEYS`(`id=base64url`, 32바이트 이상, 쉼표 구분). 활성 키가 서명하고 나열된 키는 모두 검증하므로 회전할 수 있다. 토큰이 외부(모델 공급자)로 나가므로 CSRF 키와 분리한다. 모델 API 키와도 별개다.
- 토큰·키는 로그에 쓰지 않는다. rate window는 토큰 digest로 센다.

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

### 결과와 오류

성공은 `structuredContent`와 같은 JSON의 text content로 `chat-tool/v1` 봉투(`toolCallId`, `dataVersion`, `items`, `evidenceIds`, `truncated`, `nextAllowed`, 경로 읽기의 `paths`)를 돌려준다. 실패는 빈 성공이 아니라 `isError=true`와 코드다.

| 코드 | 뜻 |
| --- | --- |
| `tool_not_granted` | grant에 없는 도구 |
| `run_not_active` | job이 끝났거나 취소·만료·다른 attempt |
| `grant_mismatch` | grant의 graphVersion·asOf가 job과 다름 |
| `invalid_arguments` | 인자 규칙 위반(아무것도 읽지 않음, 원장 기록 없음) |
| `tool_budget_exhausted` | attempt의 호출 상한(현재 12회) 도달 |
| `result_too_large` | 직렬화 결과 256 KiB 초과 |
| `tool_timeout` `tool_unavailable` `tool_failed` | 기존 runner 실패 코드(원장에 `failed`) |

등록되지 않은 이름(`portfolio_scope_read`, 점 포함 ID)은 SDK가 JSON-RPC `-32602 Unknown tool`로 답한다.

### 원장

MCP 호출도 `chat_tool_calls`에 기존 호출과 같은 방식으로 예약·시작·종료된다. `plan_revision`은 1이고 `request_meta.via = "mcp"`로 경로를 구분한다. 스키마 변경(migration)은 없다.

## 4. 켜기 전에 남은 조건

이 PR은 서버 단독 단계다. 아래가 끝나기 전에는 로컬 합성 시험 밖에서 `ZOOP_CHAT_MCP_ENABLED=true`로 두지 않는다.

1. **model-send grant 검사.** hosted MCP 결과는 ai/service의 전송 gate를 거치지 않고 OpenAI로 간다. 결과 반환 전에 source/model-send grant(OpenAI Luna 수신자, `store=true` 목적 포함)를 검사해야 한다. 현재 챗봇 grant는 ai/service 쪽에만 있다.
2. **ai/service Responses 연결과 Java 승인 continuation**(단계 3): grant 발급·`require_approval=always`·승인 원장. 지금은 `ChatMcpGrants.issue`를 부르는 실행 경로가 없다.
3. **예산 8/6/2·동시 4개(job 단위)·요청 캐시·job당 결과 1 MiB**(단계 2). 현재는 기존 attempt당 12회와 runner의 호출 3초·단계 10초만 적용된다. rate limit은 인스턴스별이다.
4. **네트워크·운영**: HTTPS 인바운드 노출 범위, 공급자 출발지 제한 여부(IP allowlist만으로 인증하지 않음), 승인된 소량 live latency spike.

## 5. 시험

```sh
./api/gradlew -p api test --tests 'com.zoop.chat.mcp.*'
```

- `ChatMcpGrantsTest`: 발급·검증, 변조·잘림·다른 키, deadline 만료, 키 회전, `portfolio.scope.read` 거부, 키 설정 오류(값 비노출).
- `ChatMcpEndpointTest`: 실제 SDK servlet transport·server와 메모리 job 저장소로 401/403/413/429, `initialize`, grant별 `tools/list`, 성공 호출의 runner·원장 기록(`via=mcp`), 거부 인자·미허용 도구·종료된 run의 무조회, attempt 호출 상한.
- `ChatMcpConfigurationTest`: 기본 꺼짐이면 bean·경로 없음, 켜고 키가 없으면 기동 거절, 키가 있으면 `/mcp` 등록.

모두 합성 job·합성 도구이며 모델·네트워크·실제 데이터를 쓰지 않는다. 실제 OpenAI 런타임과의 상호 운용은 단계 3의 합성 replay와 승인된 소량 live 시험에서 확인한다.
