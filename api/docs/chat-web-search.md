# 챗봇 보조 웹 검색 도구 (`web.search`)

설계: [보조 웹 검색 설계](../../docs/design/ai-chatbot-web-search.md). 이 문서는 지금 구현된 서버 도구만 다룬다. 화면 추적: D-AI-02.

## 1. 지금 있는 것과 없는 것

| 있음 (2026-10-30) | 아직 없음 |
| --- | --- |
| `web.search` 도구(`ChatWebSearchTool`), 공급자 포트(`ChatWebSearchProvider`), 합성 공급자 | 실제 공급자(미선정), 공급자 키·약관·처리 국가 결정 |
| 검색어 검사(`ChatWebQueryPolicy`), 요구별 웹 gate(개념 요구의 기본 1회 검색, 사실 요구의 내부 미충족 뒤 검색, Q01 요구 제외. 2026-10-31) | 질문 기간·세부 사실 기준의 "질문이 요구한 범위" 미충족(조회 결과에 날짜·필드 판단이 없어, 내부 0건·잘림과 외부 출처 명시만 미충족으로 봄) |
| agent 경로의 MCP 도구 노출과 Java 승인 gate(5장), `web-search:<공급자>` 전송 grant 검사, 웹 장애·예산 → notice | direct 경로의 Q07 2개 초과 기업 선택 확인(design 3장) |
| 호출당 7초, job당 웹 2회(내부 6회와 별도), 회원 하루 20회·프로젝트 하루 500회 원자 예약 | 실제 공급자의 재열람 권리(저장·보유 기간): 정해지기 전에는 합성 공급자 인용만 다시 보여 줌 |
| `web_*` notice 문구(`ChatResults`), 답변 인용 계약(6장: `web_reported` basis, `Citation.sourceKind=web_result`, AI 단계 계약, 화면) | snapshot 저장 |

라우터·서버 계획은 이 도구를 고르지 않는다(`ChatToolRegistry.bound()`에서 빠짐). 등록되면 MCP 도구로 노출되고, agent 경로에서만 Luna가 요청하고 서버가 승인한다(5장). 웹 결과는 `web_reported` 구간에서 `web_result`로 인용되고 Jev가 snippet과 대조하므로(6장), 웹 도구와 agent 경로를 함께 켤 수 있다(2026-10-30). 실제 공급자가 없어 합성 공급자로만 동작한다.

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

1. **노출**: 개념(Q02, 일반 개념 요구) 또는 사실 질문(Q03~Q08) 요구가 있는 agent 계획에 허용 도구로 `web_search`를 더한다. Q01 요구는 웹을 쓸 수 없지만(`AgentRequirement.web=false`, 서버만 아는 값) 같은 질문의 다른 요구는 쓸 수 있으므로, 쓸 수 있는 요구가 하나라도 있으면 노출한다. 조회 없는 개념 질문(Q02만)도 웹이 등록돼 있으면 agent 경로로 가서 검색만 허용받는다. 그 run이 preflight·circuit 때문에 시작하지 못하면 direct 경로로 웹 없이 답하고 `web_unavailable` notice를 붙인다(`mcp_direct_start`가 아님).
2. **개념의 첫 검색·사실의 마지막 수단**: 웹 요청은 대상 ID가 아니라 검색어를 받으므로 도달 가능 ID 검사를 하지 않는다. 지목한 요구 **모두**에 웹이 열려 있어야 승인한다. 일반 개념 요구는 혼합 질문에서도 첫 라운드부터 자기 검색 1회가 열린다. 사실 요구는 앞 라운드에서 그 요구를 지목해 승인·실행된 내부 조회가 0건이거나 상한에 잘렸을 때, 또는 요구 문구가 외부 출처를 명시했을 때(`ChatWebDemand`: 외신, 외부 기사, 해외 언론, 웹에서 등 고정 표현. 부정 표현과 구글·네이버 같은 기업명은 제외) 그 내부 조회가 끝난 뒤에만 열린다. 다른 요구의 미충족으로는 열리지 않는다. 모델 전송 grant 때문에 일부가 빠진 조회(`withheld`)는 미충족이 아니며, 그 요구는 외부 출처를 명시해도 열리지 않는다(거부된 자료를 찾는 대체 검색 금지). Q01 요구는 열리지 않으며, Q01 요구를 함께 지목한 검색도 거부한다. 결과는 지목한 요구에만 묶이므로 개념 검색의 결과를 사실 구간이 인용할 수 없다.
3. **검색어·형식**: 인자는 `targets`(검색어 정확히 1개, 2~80자)와 `limit`(1~5)뿐이다. `ChatWebQueryPolicy`를 통과한 정규화 검색어로 예약하므로, 승인과 `/mcp` 실행의 digest가 같다. 회원에 관한 검색어는 `invalid_arguments`로 거부된다.
4. **예산**: 승인 = 예약이며, job당 웹 2회와 회원·프로젝트의 그날 한도를 그때 차감한다. 모자라면 `web_budget_exhausted`로 거부하고 notice로 남긴다.
5. **전송**: 결과의 웹 hit은 `web-search:<공급자>` grant가 `chat-agent` 수신자에 허용될 때만 모델에 보낸다. 아니면 hit과 그 항목을 통째로 빼고 `withheld.webResults`에 개수만 적는다.
6. **notice**: 승인됐는데 호출이 실패했거나 전송 grant 때문에 hit이 모두 빠진 검색은 `web_unavailable`, 공급자가 성공적으로 0건을 돌려준 검색은 `web_no_results`, 예산 거부는 `web_budget_exhausted`다. 답변을 막지 않으며 answered 결과의 `notices`에 붙는다(요구 표현 없음).

### direct 계획의 내부 조회 뒤 검색

agent가 읽을 수 없어 서버가 읽은 계획(기간이 있는 Q05, Q06, Q07, Q08, 의존 단계)은 조회가 끝난 뒤 `OrchestratedChatEngine.webAfterReads`가 Luna에 `web_search`만 허용한 agent 실행을 한 번 시작한다. 승인 gate·검색어 검사·예산·전송 grant·notice는 위와 같다. 검색어를 고르려고 부르는 것이며, Luna가 마무리로 쓴 답은 버리고 결과의 웹 hit만 받아 생성 단계(`chat-answer`)가 내부 자료와 함께 쓴다.

- **대상**(`webGaps`): 자기 조회가 모두 성공했고 회원이 고른 근거로 좁히지 않은 요구. Q03·Q04·Q07은 0건·잘림이면, Q05·Q06·Q08은 외부 출처를 명시했을 때만 대상이다. 비교 결과·발행 회차·선정 기록은 웹으로 대신하지 않기 때문이다.
- **회원 범위**: 이 실행의 요구에는 서버가 해석한 대상 ID를 넣지 않는다(`searchOnly`). 보유·관심 종목이 대상 ID로 나가지 않으며, 검색어는 요구 문구에서만 나온다. "내 종목" 같은 말은 검색어 검사가 거절하므로 기업을 적지 않은 Q07은 검색되지 않는다.
- **시간**: `min(20초, 남은 시간 − 생성 최소 10초 − 검증 최소 6초 − 서버 3초)`이며 10초가 안 되면 시작하지 않고 `web_budget_exhausted`다. direct와 agent 모두 job 기한은 45초다.
- **실패**: 단계 실패·시간 부족은 `web_unavailable` notice이고 내부 결과로 답을 계속한다. preflight가 막아도 같다.
- **전송 grant**: 웹 snippet이 생성 단계로 가므로 `web-search:<공급자>` grant에 `chat-answer` 목적이 있어야 한다. 없으면 AI runtime이 `source_grant_denied`로 생성 단계를 거절해 job이 실패한다. 켜기 전에 등록한다.
- **기록**: route 요약의 `webAfterReads`(`searched`, `no_time`, `unavailable`, `failed`)와 `webSteps`, `webApproved`, `webDenied`.

## 6. 답변 인용 (`web_reported`·`web_result`)

- **구간**: 웹 결과로 답한 부분은 `web_reported` 구간이다. 그 구간의 요구가 실제로 받은 웹 결과의 ID(`web-<hash>`)만, 하나 이상 인용한다. 근거 구간·ZOOP 문서 구간은 웹 결과를 인용할 수 없고, 웹 구간은 줍 근거를 인용할 수 없다(`validation_failed`). 개념(일반 개념) 요구도 자기 요구를 지목한 웹 결과로 답할 수 있다(내부 조회 결과는 받지 않음).
- **인용**: `Citation.sourceKind=web_result`, `evidenceId`=결과 ID, `quote`=snippet, `articleTitle`=제목, `publisher`=도메인, `docId`=공급자, `url`·`publishedAt`. 줍의 근거로 승격하지 않는다. `answerBasis`에 `web_reported`가 더해진다(여러 수준이면 `mixed`).
- **검증**: Jev는 웹 구간을 인용한 snippet만으로 판정한다. snippet에 없는 내용이나 확인된 사실처럼 쓴 주장은 지지되지 않는다. snippet은 `web-search:<공급자>`의 `chat-verification` 전송 grant로 보낸다.
- **재열람**: 다시 검색하지 않는다. 실제 공급자의 저장·재열람 권리가 정해지기 전까지 합성 공급자 인용만 다시 보여 주고, 그 밖의 웹 인용이 있으면 본문을 고정 안내로 바꾼다(`ChatResponseGuard`).

## 7. 시험

```sh
./api/gradlew -p api test --tests 'com.zoop.chat.tool.ChatWebSearch*' --tests 'com.zoop.chat.executor.ChatJobExecutorTest'
```

- `ChatWebSearchToolTest`: 검색어 허용·거절, 합성 결과의 형태, 0건·장애, 공급자에 닿지 않는 거절, 쓸 수 없는 결과 제거·자르기·중복 합치기, 예약 도메인 밖 fixture 거절, 레지스트리가 실행은 하되 계획에 내놓지 않음.
- `ChatWebSearchConfigurationTest`: 기본 꺼짐, 공급자 없이 켜면 기동 거절, 합성 공급자로 켜면 등록.
- `ChatJobExecutorTest`: job당 웹 2회와 내부 6회 분리, 회원·프로젝트 일일 한도의 전부 아니면 전무.
- `ChatExecutorPostgresTest`(PostgreSQL): 한도 행의 원자 증가, 회원 거절 시 프로젝트 몫 미차감, 회원 탈퇴 시 회원 행 삭제.
- `ChatMcpAgentTest`: 실제 MCP 도구 위에서 개념 요구의 첫 라운드 검색 1회(혼합 질문 포함), 사실 요구의 첫 라운드 웹 거부, 그 요구의 내부 0건 뒤 승인, 다른 요구의 미충족으로 열리지 않음, Q01 요구 제외, 회원에 관한 검색어 거부, 결과의 웹 hit이 원장에서 돌아옴, 0건·장애·job 예산 초과가 notice가 되고 답은 계속됨.
- `ChatMcpSendGateTest`: 웹 hit은 그 공급자의 grant가 있을 때만 전송.
- `ChatAgentPathEngineTest`: 사실 질문의 agent 실행에 웹 도구가 허용되고 웹 notice가 결과에 붙으며 complete를 유지. 개념 질문이 검색만 들고 agent로 가고, 시작하지 못하면 웹 없이 `web_unavailable`. Q01 요구에는 웹이 닫히고 같은 질문의 사실 요구에는 열림.
- `ChatMcpConfigurationTest`: 웹 도구와 agent 경로를 함께 켤 수 있음.
- `ChatAgentPathEngineTest`(인용): 웹 보도 구간이 `web_result` 인용과 함께 답이 되고 Jev가 그 snippet을 받음, 근거 구간의 웹 인용·웹 구간의 근거 인용은 `validation_failed`, 개념(Q02) 요구가 run의 웹 결과로 답함.
- `ChatResponseGuardTest`: 합성 공급자 웹 인용은 다시 보여 주고 다른 공급자 인용은 본문을 고정 안내로 바꿈.
- `ChatModelStagesTest`: 웹 인용은 `web-search:<공급자>` grant로 검증 단계에 감.
- worker `test_chat_stages.py`: 웹 구간은 웹 인용만(하나 이상), 웹 인용은 `web-search:` 출처로만, 섞이면 거절.
