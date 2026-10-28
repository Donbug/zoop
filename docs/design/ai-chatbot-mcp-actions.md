# AI 챗봇 Luna MCP 실행·복합 질의·화면 동작 계약

기준일: 2026-10-28 / 상태: 2026-10-28 팀 결정 · 구현 예정 · 출시 검증 별도

상위 정책: [AI 거버넌스 v0.11](../ZOOP_AI_거버넌스_정책.md) / [설계 요약](ai-chatbot-design-summary.md) / [보조 웹 검색](ai-chatbot-web-search.md)

이번 팀 결정은 2026-10-25의 ‘MCP 미사용·Java 직접 어댑터만 사용’ 결정을 대체한다. direct adapter는 사전 장애 시 시작 경로와 비교 기준으로 유지한다.

## 1. 하나의 질문, 필요한 도구 조합

Q01~Q08은 multi-label로 유지한다. Q02·Q03·Q04가 함께 필요한 질문에는 필요한 도구를 조합해 한 답변을 만든다. 각 유형의 모든 도구를 의무 호출하거나 top-3로 자르지 않는다.

| 질문 예시 | 목표 실행 |
| --- | --- |
| HBM이 뭐야? | Q02. 웹 검색으로 개념 근거를 보완하고, 검색 실패·0건 시 제한된 일반 지식 설명 |
| A기업의 최근 사건 알려줘 | Q03. 내부 기업·이슈·근거 우선, 부족한 요구에만 마지막 웹 검색 |
| A와 B의 관계와 관련 사건, HBM 의미를 설명해줘 | Q02+Q03+Q04. Luna가 결과에 따라 조회를 조합하고 근거 수준별로 통합 |
| 지도에서 A와 B 경로를 보여줘 | Q04. 공개 스냅샷 경로 조회, 실제 존재하는 경로에만 typed UI 제안 |

MCP 도입 목적은 **Luna가 조회 결과를 보고 다음 도구·인자를 선택하는 제한된 agent 실행**과 표준 도구 인터페이스 재사용이다. 외부 Codex·Claude 연결은 가능한 후속 활용이며 이 설계의 필수 조건이 아니다. 정확도 개선은 가설이며 기존 서버 계획 방식과 동일 평가 세트로 비교한다.

## 2. 턴별 분류와 문맥

- 새 질문/job마다 요구와 Q 유형을 다시 분류한다. 세션에 분류를 고정하지 않는다.
- 기존 구현은 확인 질문 사슬만 모델 입력에 포함한다. 일반 이전 턴 문맥 승계는 별도 미구현 기능이다. 도입 시 같은 대화의 직전 완료 2턴에서 서버가 검증한 대상 ID·기간·선택 정보만 후보로 전달한다. 답변 본문·원문·숨겨진 추론은 승계하지 않고 현재 권한을 재확인한다.
- 명시된 새 대상·기간이 우선이다. ‘그 회사’ 후보가 여럿이면 clarification한다.
- job 안의 graphVersion·asOf·선택 evidence 범위는 고정한다. 기술 재시도와 resolves 확인 답은 기존 고정 문맥을 승계한다. 독립된 ‘최신’ 새 질문에서만 새 시점을 정한다.
- polling·재열람·저장 복구는 새 분류·도구 호출을 만들지 않는다. 이전 답변은 새로운 사실의 근거가 아니다.

## 3. 실행 책임과 배포 경계

현재는 Java가 도구를 조회하고 Luna는 Chat Completions의 BranchContext로 답변만 생성한다. 목표는 **Jev 분류 → 서버 허용 목록 → Luna Responses API의 MCP 도구 선택·연속 호출 → 최종 생성 → 서버 검사·Jev 의미 검증**이다.

| 구성요소 | 목표 책임 |
| --- | --- |
| Jev router | Q 유형·기능 후보 확률 제공. 실제 도구 인자·실행 권한 발급 안 함 |
| Java 정책/작업 실행기 | 요구·권한·버전·예산 고정, 허용 도구·체크포인트, 모든 mcp_approval_request 승인/거부, 실행 원장·결과 저장 |
| ai/service 및 worker | Luna Responses 시작·중지·continuation. 승인 요청을 Java에 반환하고 Java 결정만 전달하며 독자 승인하지 않음 |
| Luna | 허용 도구 중 필요한 도구와 인자·순서 선택, 조회 결과에 따라 추가 조회, 최종 답변 후보 생성 |
| OpenAI Responses 런타임 | MCP 도구 목록 조회와 원격 호출 전달. 모델 선택과 실제 통신 주체를 구분 |
| ZOOP MCP 서버 | 모든 호출의 인증·권한·스키마·중복·예산 검사, 조회 및 모델 전송 가능한 최소 결과 반환 |
| 출력 검증 | 결정론 검사 후 별도 Jev 의미 검증. 모델의 자기평가는 사실 검증의 대체물이 아님 |

**배포 결정:** ZOOP MCP endpoint는 앱 데이터 소유자인 Java API JVM 안에 별도 인증 경계의 `/mcp`로 제공하고 Streamable HTTP over HTTPS를 사용한다. 기존 읽기 어댑터의 공통 Tool Service를 재사용한다. Java가 자기 자신에게 MCP로 요청하지 않는다. 앱의 모델 호출 진입은 계속 `ai/service` HTTP이며, OpenAI 런타임에서 Java `/mcp`로 들어오는 역방향 도구 요청은 새 경계다. 이는 기존 CLAUDE.md의 BE↔AI HTTP 경계에 대한 **목표 확장**으로, 구현 PR에서 해당 지침·네트워크·인증·내부 계약을 함께 갱신해야 한다. Python이 앱 DB를 직접 읽는 경로는 만들지 않는다.

**외부 endpoint 방어:** `/mcp`는 공개 인터넷에서 도달할 수 있어도 익명 공개 API가 아니다. HTTPS, job/세대/subject/도구/만료에 결속된 단기 bearer token, host·Origin 비신뢰, 허용 method/content-type, request body 64 KiB, 정규화 tool result 256 KiB/호출·1 MiB/job, 연결·읽기 절대 deadline을 적용한다. token+job 기준 총 8회와 동시 4회 외에 token 기준 분당 30요청의 초기 WAF/application rate limit을 두고 초과는 429로 닫는다. OpenAI의 고정 출발지 범위를 계약으로 보장할 수 있기 전에는 IP allowlist를 유일한 인증으로 사용하지 않으며, 공식 범위가 제공되면 보조 방어로 추가한다. 로컬 tunnel은 합성 데이터·단기 secret·명시 승인에만 사용하고 운영 데이터와 상시 URL을 쓰지 않는다.

MCP 자격 증명은 OpenAI 모델 API 키와 별개다. job·실행 세대·subject·도구 목록·대상·만료·graphVersion·asOf에 결속한 단기 위임 토큰을 서버가 발급한다. 모델이 만든 userId·jobId·권한으로 범위를 정하지 않는다. Q07의 `portfolio.scope.read`는 Java가 Responses 시작 전에 실행하는 서버 전용 precondition이며 MCP 도구 목록에 노출하지 않는다. 전체 보유 목록·수량·보유 표시는 모델에 보내지 않는다. 서버가 scope 안에서 실제로 일치한 공개 사건·관계 결과만 최대 5개 대상으로 최소화하고, 답변에 필요한 공개 기업명/ID는 별도 model-send grant가 있을 때만 전송한다. 인증 토큰은 프롬프트·로그에 쓰지 않는다.

**모델 전송 gate:** hosted MCP 결과는 Java 생성 직전 gate를 우회해 OpenAI로 바로 들어간다. 따라서 MCP 서버가 반환 **전에** 공개·철회·source grant의 model-send 목적/수신자·최소화·크기 제한을 검사한다. 캐시 hit와 사전 direct 시작 경로에도 동일 규칙을 적용한다. 별도 Jev 검증 전송 grant도 유지한다.

### 3.1 후보·필수 요구와 중단 조건

- 명시적 요구는 required=true로 고정한다. Jev p≥0.70 후보, 0.35≤p<0.70 검토 후보를 허용 목록에 넣되 실행은 Luna가 선택한다. p<0.35여도 명시 요구에 필요한 등록 도구는 포함한다. 확률로 권한을 넓히지 않는다.
- 최소 공통 읽기 기능도 해당 대상·요구와 관련된 것만 노출한다. 낮은 확률 후보가 필요하면 Luna는 capability 검토를 요청할 수 있으나 서버 검토 없이 도구 목록을 확장하지 않는다.
- 기존 독립 Luna coverage-verifier 2회 목표는 **Luna 실행 중 요구 추적 + 서버 커버리지 검사**로 대체한다. 별도 사전 coverage LLM 호출을 추가하지 않는다. 서버는 모든 명시 요구가 답변·제한·확인 중 하나에 연결되는지 검사하고, Jev는 최종 주장의 의미를 검증한다.
- ‘관계 경로’에는 graph.path.read, ‘원문 근거’에는 evidence.resolve 등 필요한 능력을 요구에 결속한다. 이미 다른 도구가 동일한 유효 근거를 반환했다면 중복 호출은 필요 없다. Q06은 브리핑 유형이며 단순 원문 요청을 Q06으로 바꾸지 않는다.
- 각 호출은 requirementIds와 미해결 항목을 지목한다. 단순 ‘더 자세하게’는 추가 조회 사유가 아니다. schema 적합성·근거 존재·시점·대상은 코드로 검사하고 주장 지지 여부는 후검증한다. 도구가 반환한 evidenceSufficient=true나 근거 개수만으로 사실 충족을 확정하지 않는다.
- 조회 완료/0건/잘림/장애를 구분한다. 도구 결과에는 coverageStatus·truncated·hasMore·근거 ID·오류 코드·cachedFrom을 넣으며 다음 조회는 새 대상·기간·페이지·필요 근거 등 실질적 정보 이득이 있을 때만 허용한다.
- 개수 체크포인트는 서버가 평가한다. 대상이 모호하거나 fan-out>5면 최종 생성 전에 clarification하고 최대 확인 사슬 2회를 유지한다. 제한에 도달하면 새 호출을 막고 확보한 자료로 종료한다.

### 3.2 호출·시간 초기 상한

아래는 2026-10-28 팀 결정의 잠정 차단선이며 실측 성능 약속이 아니다. 정책 revision을 고정하고 평가 후 변경한다.

| 항목 | 상한 |
| --- | --- |
| 한 job의 도구 호출 시도 | 총 8회, 그 안에서 내부 최대 6회·웹 최대 2회 |
| 동시 실행 | 최대 4개 |
| 의존 라운드 | 총 3라운드, 추가 4번째 보충 라운드 없음 |
| fan-out / 배치 대상 | 최대 5개, company.batch_read·issue.batch_read는 구현 예정 |
| 동일 정규화 요청의 실제 조회 | 1회, 캐시·single-flight로 재사용 |
| 개별 도구 | 일반 DB 3초·그래프 경로 5초·웹 7초 |
| Luna 실행 | MCP 왕복·Java 승인 continuation·도구 실행·최종 생성 합산 최대 35초 |
| 전체 ChatJob | running 전이부터 검증 결과의 DB terminal-state commit 완료까지 최대 45초 |
| 기타 단계 | Jev router 4초·후검증 Jev 6초·서버 처리/저장 3초 |
| 자료·토큰 | 문서 합계 20개, 그래프 3-hop·노드/간선 각 50개, Luna 누적 입력 24,000·최종 답변 출력 2,000 토큰 |
| 요구·확인 | 명시 요구 6개, 확인 질문 사슬 최대 2회 |

**시간 합산:** 45초에는 후검증과 결과·영수증의 DB commit 3초가 포함되며 클라이언트로 응답을 전송하는 시간만 제외한다. Luna에 항상 35초를 더 주지 않는다. 실효 Luna 예산은 min(35초, 전체 잔여 시간 − 후검증 6초 − 서버 3초)다. router가 4초를 쓰면 최대 32초다. Luna 구간 종료 전 최종 작성용 10초를 확보해 새 도구 시작을 중단하고, 모든 개별 timeout도 잔여 기한으로 줄인다. 기한 내 모델 결과가 없으면 고정 안내로 종료하며 늦은 호출은 실행 세대 fence로 차단한다. 기한 종료가 공급자 실행/과금 취소를 보장하지는 않는다.

라운드 예시는 내부 핵심 조회 → 내부 보충 → 필요 웹 검색이다. Q02는 첫 라운드 검색 가능하다. 내부 의존성이 3라운드를 모두 쓰면 웹을 위해 4라운드를 만들지 않고 미확인 부분을 알린다. 라운드는 모델 API 요청 횟수가 아닌 결과 의존성 깊이다.

캐시 hit·중복 시도·실패·direct 시작 경로의 조회도 총 8회와 내부/웹 상한에 포함한다. 동시 예약은 원자적으로 차감한다. 배치 내부 조회는 최대 5개 대상의 1회 도구 호출로 세되 결과·DB 부하 상한을 별도로 지킨다. 웹은 검색어 하나의 공급자 요청을 1회로 세며 배치 봉투로 2회 상한을 우회하지 않는다. 무조건 자동 재시도는 하지 않는다.

초기 Responses의 `reasoning.effort`는 `medium`으로 고정한다. 구현 첫 단계에서 도구 1·4·8회와 승인 continuation 1·3라운드의 합성 replay 및 승인된 소량 live latency spike를 수행해 p50/p95·토큰·비용을 기록한다. `high`는 같은 평가 세트에서 품질 이득과 45초 준수를 모두 증명한 뒤 정책 revision으로 올린다.

모델 측 요청 1건에도 여러 추론·도구 왕복이 있을 수 있다. 모델/도구 토큰·continuation·reasoning 사용량을 실제 영수증으로 합산하고, 서버가 예약하는 모델 출력 비용은 reasoning도 포함한다. 2,000은 최종 답변 길이 상한이며 reasoning 비용까지 그 안이라고 가정하지 않는다. 모델이 초과 호출을 시도하면 gate가 거부하고 실행기가 신규 실행을 종료한다.

### 3.3 요청 단위 캐시와 중복 억제

캐시 키는 `jobId + executionGeneration + logicalToolId + schema/policyRevision + canonicalArguments + subject/scopeDigest + graphVersion + asOf`다. 기본 인자·기간·집합 순서를 정규화하되 의미 있는 순서·페이지 cursor·선택 evidence 범위는 보존한다. requirementId만 다른 동일 조회는 한 결과에 요구 매핑을 합친다. 서로 다른 회원·작업·버전의 캐시는 공유하지 않는다.

1. 같은 키가 실행 중이면 single-flight로 합류해 원 조회를 기다린다. 합류 요청도 남은 기한·시도 상한을 따른다.
2. 성공 결과 및 성공한 0건을 job 종료까지 캐시한다. 같은 키 재요청은 실제 결과와 cached=true·원 toolCallId를 반환한다. 빈 result로 성공을 흉내 내지 않는다.
3. timeout·권한 거부·invalid schema를 성공/0건 캐시로 넣지 않는다. 실패 원장으로 동일 실패의 무한 재호출을 막는다.
4. 캐시 반환 직전에 현재 권한·철회·grant를 다시 검사한다. 과거 허용 결과로 현재 차단을 우회하지 않는다.
5. 대상·기간·페이지·hop 등 의미 있는 인자가 바뀌면 다른 키다. 같은 정보를 얻는 단순 재표현은 새 조회로 인정하지 않는다.
6. 작업 종료 시 실행 캐시를 폐기한다. 재열람은 별도 권리·보유 기간이 적용된 저장 snapshot을 사용하며 캐시 TTL을 재열람 보관 정책으로 쓰지 않는다.

예: 두 요구가 company.read(A, 동일 버전)를 요청하면 실제 조회 1회, 두 요구에 결과 매핑. graph.path.read(A,B,hop=1) 후 hop=3은 새 탐색 범위가 필요한 경우 다른 요청이다.

### 3.4 승인 continuation과 MCP 장애 시 direct 시작 경로

MCP endpoint와 direct adapter는 같은 Tool Service·스키마·scope·버전·grant·캐시·원장을 사용한다. 업무 로직을 복제하지 않는다. 초기 범위에서는 **실행 전에 경로를 한 번 선택**하며, Responses 실행 중 MCP 오류를 direct 결과로 바꿔 끼우지 않는다.

#### 승인 주체와 continuation

초기 MCP 도구는 `require_approval=always`다. 승인은 회원에게 매번 묻는 UI 동작이 아니라 Java 정책/작업 실행기의 서버 판단이다.

1. ai/service가 Luna Responses를 시작한다.
2. Responses가 `mcp_approval_request`를 반환하면 ai/service는 response ID, approval request ID, 도구·정규화 인자, 요구 매핑을 Java에 반환하고 실행을 일시 중지한다.
3. Java가 남은 8/6/2 예산, requirementIds, subject scope, 버전/asOf, grant, 중복/cache와 deadline을 검사해 approve/reject를 결정하고 원장에 기록한다.
4. Java가 ai/service의 continuation endpoint를 다시 호출한다. ai/service는 Java 결정만 `mcp_approval_response`로 전달하고 `previous_response_id`로 같은 Responses 실행을 재개한다. ai/service가 정적 목록만 보고 독자 승인하지 않는다.
5. 거부된 도구가 있어도 Java는 continuation에 임의의 MCP 결과나 direct 결과를 위조하지 않는다. Luna는 승인된 다른 결과로 답하거나 해당 요구를 limitation/guidance로 남긴다.

각 continuation은 Luna 35초·job 45초 안에 포함된다. Java→ai/service 호출이 여러 번 생기므로 승인 request/response ID, 동일 response chain, 예산 예약과 취소를 replay·소량 live 시험에서 검증한다.

**미결정(구현 PR에서 확정):** `previous_response_id` 재개는 이전 응답이 공급자 쪽에 저장(`store=true`)돼 있어야 하므로 MCP 결과·대화 입력이 공급자 보관 대상이 된다. 구현 전에 공식 문서로 저장 조건을 재확인하고 (a) `store=true`를 허용해 공급자 보유 기간을 model-send grant·보유 정책에 기록하거나 (b) `store=false`로 이전 출력 항목(암호화된 reasoning 포함)을 매 continuation에 다시 전달하고 24k 입력 예산 영향을 측정하는 방식 중 하나를 정한다. 결정 전에는 live 실행을 열지 않는다.

#### direct 경로 선택

| 상황 | 초기 처리 |
| --- | --- |
| Responses 시작 전 health preflight 실패 / circuit open | MCP를 노출하지 않고 Java의 기존 계획·direct adapter로 조회한 뒤, 정규화된 BranchContext를 Luna 생성 입력으로 전달 |
| Responses 실행 중 MCP 연결·transport 실패 | 같은 실행에서 direct 전환하지 않음. 성공한 결과는 유지하고 `tool_unavailable` notice와 실제 미충족 limitation으로 종료. circuit 통계는 다음 job에 반영 |
| 인증·권한·grant 거부 / invalid schema | direct 우회 금지, 자료 차단·원인 유지 |
| DB·공개 snapshot 장애 | direct도 같은 원천이므로 우회 금지. 독립된 정상 근거만 사용하거나 고정 안내 |
| 웹 실패 | 다른 공급자·direct 경로로 자동 재검색하지 않음. `web_unavailable` 후 답변 지속 |
| OpenAI 송신 후 결과 불명 | 동일 요청 재전송 금지, `response_unknown/reconcile_only`, 미검증 본문 미노출 |
| 모델/후검증 실패 | 실패 원장 유지, 검증되지 않은 사실 대신 고정 안내 |

direct 경로의 자료는 MCP call receipt가 아니라 direct tool receipt와 evidence ID로 연결하고, 모델 입력에는 서버가 정규화·grant 검사한 BranchContext로 넣는다. 이 동등성은 별도 fixture로 검증한다. 실행 중 MCP 실패 자료를 일반 메시지나 `function_call_output`으로 넣는 방식은 spike로 API 계약과 인용·영수증 연결이 증명되기 전까지 채택하지 않는다.

Circuit breaker 초기값은 endpoint별 최근 5회 **연결** 시도 중 3회 실패 시 30초 open, 이후 half-open health probe 1회다. 401/403·정책 거부·DB 오류는 연결 실패 통계에서 제외한다. probe는 내용 없는 health 확인으로 제한한다. direct 시작도 8/6/2·45초와 권한·grant를 초기화하거나 우회하지 않는다.

### 3.5 사용자 응답과 내부 실패의 구분

‘항상 답변’은 시스템이 정상적으로 응답을 전달할 수 있는 한 검증된 내용 또는 확인 불가 안내를 제공한다는 뜻이다. 웹 실패만으로 전체 job을 failed로 만들지 않는다. 다른 기술 장애·권한 거부·검증 실패·저장 실패의 사실을 성공 원장으로 덮지 않는다.

목표 공개 필드는 `answerStatus=complete|partial|guidance`(신규, 미구현)이며 job.status·outcome과 별개다. answered에서 미충족 요구가 있으면 partial, 모두 답했으면 complete, clarification/guidance/insufficient_evidence는 guidance다. 보완 웹만 실패하고 모든 요구를 답했다면 complete일 수 있다.

새 `notices[]`에는 requirementIds와 code·message를 담아 web_unavailable·web_no_results·web_budget_exhausted·web_not_configured·mcp_direct_start·tool_unavailable·tool_budget_exhausted를 원인대로 표시한다. 기존 limitations는 답하지 못한 요구만 담으며 필요한 장애 kind를 함께 확장한다. 예를 들어 내부 근거로 요구를 완결하면 web_unavailable notice만 붙이고, 최신 소식 요구가 남으면 partial과 해당 limitation을 함께 표시한다. 모델은 제한 여부를 자의로 확정하지 못한다.

답할 근거가 전혀 없으면 guidance 또는 조회 성공 시 insufficient_evidence의 고정 안내다. Q02 웹 실패는 general_knowledge로 개념 설명 가능하지만 최신 기업 사실·수치·전망을 만들어내지 않는다. 모델 결과 불명/검증 실패 등 failed job에는 기존 ChatFailure 기반 고정 안내를 표시한다. cancelled·미인증·저장/전달 시스템 장애는 completed로 가장하지 않는다. 안전 안내 자체에 다시 모델 검증을 호출할 필요는 없다.

현재 공개 API에는 answerStatus·notices 및 추가 limitation kind가 없다. UI가 임의로 새 필드를 추측하지 않으며 구현 PR에서 DTO·저장·OpenAPI·웹 타입·재열람 guard를 동시에 변경한다.

## 4. 유형별 도구와 UI 동작

아래는 목표 매핑이다. 모든 도구·화면 동작이 구현됐다는 뜻이 아니다. Q02는 웹 보조 근거를 기본 시도하고 Q03~Q08은 내부 근거가 부족한 요구에만 마지막 웹 검색을 허용한다.

| 유형 | 주 도구/처리 | 연결할 수 있는 동작 |
| --- | --- | --- |
| Q01 | help.search, screenSpec.read, zoopPolicy.read | 승인된 서비스 화면·도움말 열기 |
| Q02 | 웹 보조 근거 + Luna 설명, 실패 시 제한된 일반 지식 | 기본 화면 이동 없음, 검색한 경우 외부 출처 링크 |
| Q03 | company.read, issue.read, document.search, evidence.resolve | 기업 상세, 이슈·근거 열기 |
| Q04 | graph.path.read, evidence.resolve | 실제 간선·경로 포커스, 관계 상세·근거 열기 |
| Q05 | graph.version.diff, period.compare | 실제 지원되는 버전/기간 비교 화면 열기 |
| Q06 | briefing.read, briefing.evidence | 해당 회차 브리핑·근거 열기 |
| Q07 | Java server-only portfolio.scope.read 후, scope 안에서 일치한 공개 사건·관계 MCP 조회 | 내 종목 관련 결과와 허용된 기업 상세 열기 |
| Q08 | selectionRule.read, evidence.resolve | 기록된 선정 설명·근거 열기 |

UI 동작은 DB 읽기 도구와 분리한다. 조회 결과의 유효한 ID를 서버가 typed UI 제안으로 만들고 브라우저가 사용자 클릭 후 실행한다. 조회했다고 자동 페이지 이동·자동 지도 변경을 하지 않는다. 임의 JavaScript·모델 생성 URL·자유 형식 라우트는 실행하지 않는다.

## 5. UI 계약 확장안

이번 개정에서는 기존 typed UI 제안 범위를 유지한다. 현재 `ChatResult.action`은 `set_watchlist` 안내 용도이며 새 동작들을 이미 수용하지 않는다. `graphTargets`만으로 간선·경로 UI가 완성됐다고 간주하지 않는다. 목표는 별도 `uiActions[]` 추가이며 기존 필드와 하위 호환을 유지한다. `graphTargets`는 조회된 도메인 대상의 정본이고 `uiActions[]`는 동일 검증 대상에서 파생하는 표시용 제안이다. 둘이 충돌하면 동작을 제공하지 않는다.

각 제안은 서버 발급 actionId, 허용 kind, label, requirementIds, typed target, 필요 시 graphVersion/asOf를 가진다. 초기 kind는 `open_company`, `focus_relation`, `focus_path`, `open_evidence`, `open_briefing`, `open_watchlist`로 제한한다. 실제 필드·enum은 구현 PR에서 DTO·OpenAPI·클라이언트와 함께 확정한다. Q01 도움말 및 Q05 비교 화면은 실제 지원 route가 확인된 경우만 확장한다.

- 대상 ID가 도구 결과에 존재하고 공개·권한·버전 검사를 통과해야 동작을 만든다. 외부 보도만으로 내부 관계 ID를 만들지 않는다.
- 클릭 후 대상 화면의 기존 API·권한·404 처리로 현재 공개 상태·권한을 다시 확인한다. 버튼 확인 전용 API는 추가하지 않으며 경로 포커스에 기존 API로 부족한 버전 확인은 구현 PR에서 계약화한다. 삭제·철회·버전 불일치는 ‘현재 열 수 없음’으로 안내하고 다른 간선으로 치환하지 않는다.
- polling·복구·재열람으로 동작을 재실행하지 않는다. 외부 출처는 서버가 검증한 http(s) URL만 사용한다.
- 화면 추적: `D-AI-01/02`, 기업 `D-GRP-03`·`D-COM-01`, 관계 `D-GRP-04`, 근거 `D-GRP-05`, 경로 `D-GRP-07/07b`, 브리핑 `D-BRF-01/02`, 내 종목 `D-GRP-01b`. UI 구현 전 wireframe README·manifest·개별 이미지를 확인한다.

## 6. 계약·저장·검증 변경 경계

범용 용어 사전이나 웹 결과를 정식 evidence로 적재하는 파이프라인을 만들지 않는다. 웹 결과는 권리·보유 기간이 정해진 job 근거 snapshot으로 분리한다. 기존 JSON 저장으로 충분한지 migration이 필요한지는 구현 시 확인한다. 미검토 migration이나 API 변경을 완료로 표기하지 않는다.

동시 변경 대상은 planner capability·실행 봉투, Responses MCP 연결·서버 바인딩·승인 continuation, ChatResult·answerStatus/notices·citation/basis·UI action 계약, 감사 기록, 응답 검사·재열람 guard, 생성 명세·클라이언트, 화면·테스트다. 공개 job 접수·polling·resolves 수명주기는 유지한다. 미구현 계약을 OpenAPI 출력에만 먼저 추가하지 않는다.

평가는 [고정 평가 세트의 다음 버전 항목](../development/ai-chatbot-eval-set.md)을 따른다. 독립 Luna coverage-verifier 계획은 3.1절로 대체한다. Responses MCP 실행·Java 승인 continuation·cache·direct 시작 경로·부분 응답은 모두 구현 예정이다. 공식 API 근거: [Luna 모델](https://developers.openai.com/api/docs/models/gpt-6-luna), [Responses MCP](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)(2026-10-28 확인). 기존 Figma 보드는 이전 설계일 수 있으며 구현 전에 별도로 동기화한다.
