# 챗봇 보조 웹 검색 도구 (`web.search`)

설계: [보조 웹 검색 설계](../../docs/design/ai-chatbot-web-search.md). 이 문서는 지금 구현된 서버 도구만 다룬다. 화면 추적: D-AI-02.

## 1. 지금 있는 것과 없는 것

| 있음 (2026-10-30) | 아직 없음 |
| --- | --- |
| `web.search` 도구(`ChatWebSearchTool`), 공급자 포트(`ChatWebSearchProvider`), 합성 공급자 | 실제 공급자(미선정), 공급자 키·약관·처리 국가 결정 |
| 검색어 검사(`ChatWebQueryPolicy`), Q02만 있는 run의 기본 1회 검색 | 혼합 질문의 Q02 기본 검색, Q01이 섞인 질문의 다른 부분 웹 검색(승인 요청에 요구 ID가 없어 검색을 어느 요구에 묶을지 알 수 없음) |
| agent 경로의 MCP 도구 노출과 Java 승인 gate(5장), `web-search:<공급자>` 전송 grant 검사, 웹 장애·예산 → notice | 요구별 미충족 판단(승인 요청에 요구 ID가 없어 run 단위로 판단) |
| 호출당 7초, job당 웹 2회(내부 6회와 별도), 회원 하루 20회·프로젝트 하루 500회 원자 예약 | 답변 인용 계약(`web_reported` basis, `Citation.sourceKind=web_result`), AI 단계 계약, 화면 |
| `web_*` notice 문구(`ChatResults`) | snapshot 저장·재열람, Jev 후검증 쪽 전송 grant |

라우터·서버 계획은 이 도구를 고르지 않는다(`ChatToolRegistry.bound()`에서 빠짐). 등록되면 MCP 도구로 노출되고, agent 경로에서만 Luna가 요청하고 서버가 승인한다(5장). **인용 계약이 없는 동안 웹 도구와 agent 경로를 함께 켜면 기동을 거절한다**: 웹에서 읽은 내용이 검사할 인용 없이 답에 섞일 수 있기 때문이다. 그래서 지금은 어떤 질문도 웹을 쓰지 않으며, 연결은 시험으로만 확인한다.

## 2. 켜는 방법 (로컬·시험 전용)

```sh
ZOOP_CHAT_WEB_ENABLED=true ZOOP_CHAT_WEB_PROVIDER=synthetic
```

- 기본은 꺼짐이다. 켜고 공급자가 `synthetic`이 아니면 기동을 거절한다(실제 공급자가 없다).
- 합성 공급자는 `api/src/main/resources/chat-web-fixtures/synthetic-v1.json`의 고정 결과만 돌려준다. 모든 주소는 예약 도메인(`example.com`·`example.org`·`example.net`) 아래여야 하고, 아니면 기동을 거절한다. 외부로 나가는 호출은 없다.
- fixture에서 `unavailable`에 적힌 검색어는 공급자 장애(`tool_unavailable`)처럼 동작하고, 없는 검색어는 0건이다.

## 3. 도구 규칙

- **한 호출에 검색어 하나**(요청의 유일한 대상). 여러 검색어를 한 호출에 넣어 웹 예산을 우회하지 못한다.
- **검색어 검사**: NFKC 정규화와 공백 하나로 합친 뒤 2~80자. 이메일, 링크, 6자리 이상 숫자(날짜 `2026-10-29`·`2026.10` 제외), 제어 문자, 회원에 관한 말(내 종목, 보유, 매입, 평단, 수익률, 손익, 계좌, 잔고, 수량, 주문, 관심 종목 등)이 있으면 고치지 않고 거절한다. 거절된 검색어는 공급자에 닿지 않는다.
- **결과**: 검색어당 최대 5건. http(s)이고 계정 정보가 없는 주소, 비어 있지 않은 제목만 남긴다. 제목 300자, snippet 500자로 자른다. 같은 주소는 하나로 합친다. 결과 ID는 서버가 공급자와 주소로 만든 `web-<hash>`이다. 본문은 가져오지 않는다.
- 웹 결과는 ZOOP 근거가 아니다. `evidenceIds`가 없고 항목 종류는 `web_result`다. 데이터 버전은 `web:<공급자>`다.
- 공급자 장애는 `ChatToolUnavailable`이며 빈 결과로 바꾸지 않는다.

## 4. 예산

| 한도 | 값 | 어디서 |
| --- | --- | --- |
| 호출당 | 7초(단계 10초·run 기한으로 줄어듦) | `ChatToolRunner.WEB_CALL_LIMIT` |
| job당 | 웹 2회, 내부 6회와 따로 셈(재실행 포함) | `ChatRunControl.MAX_WEB_CALLS`, `chat_tool_calls.registry_group = 'web-search'` |
| 회원 하루 | 20회(KST 날짜) | `chat_web_search_quotas`, `ChatRunControl.MEMBER_DAILY_WEB_CALLS` |
| 프로젝트 하루 | 500회(KST 날짜) | `chat_web_search_quotas`, `ChatRunControl.PROJECT_DAILY_WEB_CALLS` |

- 웹 호출 예약(`reserveToolCalls`)과 같은 트랜잭션에서 프로젝트 행, 회원 행 순서로 조건부 증가한다. 하나라도 모자라면 `ChatWebBudgetExhausted`(`JOB`·`MEMBER`·`PROJECT`)를 던지고 아무것도 예약하거나 차감하지 않는다.
- 예약된 웹 호출은 성공·실패·timeout·미시작과 관계없이 일일 한도에서 센다.
- 이 예외는 job 실패가 아니다. 서버 웹 단계가 연결되면 `web_budget_exhausted` notice로 바꾸고 내부 답변을 계속한다.

## 5. agent 경로의 승인 (`ChatMcpAgent`)

1. **노출**: 개념(Q02, 일반 개념 요구) 또는 사실 질문(Q03~Q08) 요구가 있는 agent 계획에 허용 도구로 `web_search`를 더한다. 서비스 안내(Q01) 요구가 하나라도 있으면 넣지 않는다(Q01 답은 웹에 기댈 수 없고, 웹 결과를 요구별로 묶을 수 없다). 조회 없는 개념 질문(Q02만)도 웹이 등록돼 있으면 agent 경로로 가서 검색만 허용받는다. 그 run이 preflight·circuit 때문에 시작하지 못하면 direct 경로로 웹 없이 답하고 `web_unavailable` notice를 붙인다(`mcp_direct_start`가 아님).
2. **개념의 첫 검색·사실의 마지막 수단**: 웹 요청은 대상 ID가 아니라 검색어를 받으므로 도달 가능 ID 검사를 하지 않는다. 일반 개념 요구만 있는 run은 첫 라운드부터 웹 검색 1회를 승인받을 수 있다. 개념과 사실이 섞인 run은 검색을 어느 요구에 쓰는지 확인할 수 없으므로 이 예외를 주지 않고, 사실 run처럼 앞 라운드에서 승인·실행된 내부 조회 중 0건이거나 상한에 잘린 결과가 있을 때만 승인한다. 승인 요청에 요구 ID가 없어 이 판단은 run 단위다([chat-mcp.md](chat-mcp.md) 5장 4).
3. **검색어·형식**: 인자는 `targets`(검색어 정확히 1개, 2~80자)와 `limit`(1~5)뿐이다. `ChatWebQueryPolicy`를 통과한 정규화 검색어로 예약하므로, 승인과 `/mcp` 실행의 digest가 같다. 회원에 관한 검색어는 `invalid_arguments`로 거부된다.
4. **예산**: 승인 = 예약이며, job당 웹 2회와 회원·프로젝트의 그날 한도를 그때 차감한다. 모자라면 `web_budget_exhausted`로 거부하고 notice로 남긴다.
5. **전송**: 결과의 웹 hit은 `web-search:<공급자>` grant가 `chat-agent` 수신자에 허용될 때만 모델에 보낸다. 아니면 hit과 그 항목을 통째로 빼고 `withheld.webResults`에 개수만 적는다.
6. **notice**: 승인됐는데 결과가 남지 않은 검색은 `web_unavailable`, 0건은 `web_no_results`, 예산 거부는 `web_budget_exhausted`다. 답변을 막지 않으며 answered 결과의 `notices`에 붙는다(요구 표현 없음).

## 6. 시험

```sh
./api/gradlew -p api test --tests 'com.zoop.chat.tool.ChatWebSearch*' --tests 'com.zoop.chat.executor.ChatJobExecutorTest'
```

- `ChatWebSearchToolTest`: 검색어 허용·거절, 합성 결과의 형태, 0건·장애, 공급자에 닿지 않는 거절, 쓸 수 없는 결과 제거·자르기·중복 합치기, 예약 도메인 밖 fixture 거절, 레지스트리가 실행은 하되 계획에 내놓지 않음.
- `ChatWebSearchConfigurationTest`: 기본 꺼짐, 공급자 없이 켜면 기동 거절, 합성 공급자로 켜면 등록.
- `ChatJobExecutorTest`: job당 웹 2회와 내부 6회 분리, 회원·프로젝트 일일 한도의 전부 아니면 전무.
- `ChatExecutorPostgresTest`(PostgreSQL): 한도 행의 원자 증가, 회원 거절 시 프로젝트 몫 미차감, 회원 탈퇴 시 회원 행 삭제.
- `ChatMcpAgentTest`: 실제 MCP 도구 위에서 개념-only run의 첫 라운드 검색 1회, 혼합·사실 run의 첫 라운드 웹 거부, 내부 0건 뒤 승인, 회원에 관한 검색어 거부, 결과의 웹 hit이 원장에서 돌아옴, 0건·장애·job 예산 초과가 notice가 되고 답은 계속됨.
- `ChatMcpSendGateTest`: 웹 hit은 그 공급자의 grant가 있을 때만 전송.
- `ChatAgentPathEngineTest`: 사실 질문의 agent 실행에 웹 도구가 허용되고 웹 notice가 결과에 붙으며 complete를 유지. 개념 질문이 검색만 들고 agent로 가고, 시작하지 못하면 웹 없이 `web_unavailable`. Q01이 섞이면 웹 없음.
- `ChatMcpConfigurationTest`: 웹 도구와 agent 경로를 함께 켜면 기동 거절.
