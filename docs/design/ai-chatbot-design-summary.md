# ZOOP AI 챗봇 설계 요약

문서 버전: 1.7 / 기준 정책: ZOOP-AIG-001 v0.11 / 설계 갱신: 2026-10-28
상태: 2026-10-28 팀 결정 · 구현 예정 · 출시 검증 별도

이번 팀 결정은 2026-10-25의 MCP 미사용 결정을 대체한다. 기존 Java direct adapter는 Responses 시작 전 MCP 장애가 확인된 job의 시작 경로와 비교 기준으로 유지한다.

상세: [거버넌스](../ZOOP_AI_거버넌스_정책.md), [Luna MCP 실행·캐시·direct 시작 계약](ai-chatbot-mcp-actions.md), [웹 검색](ai-chatbot-web-search.md), [개발 계획](../development/ai-chatbot-implementation-plan.md), [평가](../development/ai-chatbot-eval-set.md), [화면 상태](../wireframe/ai-chatbot-state-contract.md).
[기존 FigJam](https://www.figma.com/board/n9faVm9OiLCKwD8OgnFQfX)은 이전 설계일 수 있으며 이번 문서 개정의 동기화 증거로 사용하지 않는다.

## 1. 핵심 요약

Jev가 Q01~Q08 유형과 기능 후보를 분류하면 서버가 허용 도구·대상·권한·예산을 고정한다. Luna는 Responses API에서 ZOOP MCP 도구를 선택하고 결과에 따라 추가 조회한 후 최종 답변 후보를 만든다. 서버의 결정론 검사와 별도 Jev 의미 검증을 통과한 내용만 사용자에게 제공한다.

- 한 질문에 여러 유형이 해당할 수 있다. Q02·Q03·Q04를 필요한 도구로 조합하고 유형 수를 top-3로 제한하지 않는다.
- 범용 용어 사전은 없다. Q02는 웹 보조 근거를 기본 시도하고 실패하면 제한된 일반 지식 설명을 제공한다.
- Q01은 웹 검색 금지. Q03~Q08은 내부 조회를 먼저 하고 부족한 요구에만 마지막 웹 검색을 사용한다.
- 웹 장애만으로 전체 답변을 실패시키지 않는다. 정상 근거 답변·부분 답변·확인 불가 안내를 제공한다.
- 요청 단위 cache/single-flight로 동일 조회를 재사용한다. 권한/철회는 cache hit에서도 재검사한다.
- MCP 연결 장애에는 공통 Tool Service의 Java direct adapter로 최대 1회 전환한다. 인증/권한/grant/스키마 거부를 우회하지 않는다.
- 개별 답변은 자동 검증한다. 공개 데이터 생성·관리자 검수와 구분한다.

## 2. 목표 처리 흐름

1. 회원·소유권·멱등성 검사, 대상·기간·asOf·graphVersion 고정.
2. 명시 요구를 requirementId로 나누고 모호한 대상은 clarification.
3. Jev의 multi-label 판정을 서버 필수/선택 capability 및 허용 도구로 변환.
4. ai/service가 Luna Responses API에 정제 입력·MCP 연결·허용 도구를 전달.
5. Luna가 필요한 도구와 인자를 선택. OpenAI 런타임이 MCP 요청을 전달.
6. Java MCP gate가 실행/모델 전송 권한·버전·중복·예산을 검사하고 공통 읽기 서비스를 실행.
7. Luna가 중간 결과를 받아 미해결 요구만 추가 조회. 서버 체크포인트·최대 3라운드·웹 gate 적용.
8. 최종 구조화 답변 후보 1개를 생성하고 결정론 검사 → 별도 Jev 의미 검증 → 저장·전달.
9. 자료·검색·모델 장애에는 원인을 보존하면서 검증된 내용 또는 고정 안내로 종료.

기존 독립 Luna coverage-verifier 최대 2회 목표는 실행 중 요구 추적과 서버 커버리지 검사로 대체한다. 이를 독립 사실 검증으로 취급하지 않으며 최종 Jev 검증은 유지한다.

## 3. 구성요소별 책임

| 구성요소 | 역할 |
| --- | --- |
| Jev router | 유형·capability 확률, 자유 도구명·실행 권한 생성 없음 |
| 서버 정책/작업 실행기 | 명시 요구, 허용 목록·대상·예산·체크포인트, 내구 원장, 결과/권한 검사 |
| Luna | 허용된 도구·인자·순서 선택, 중간 결과에 따른 보충, 최종 답변 후보 |
| OpenAI Responses | MCP 도구 목록과 호출 전송, 승인 요청/결과 반환 |
| Java MCP endpoint | 인증 경계의 HTTPS Streamable HTTP /mcp, 호출 gate·캐시·공통 Tool Service |
| Direct adapter | preflight 실패·circuit open이면 Responses 시작 전 선택하는 대체 시작 경로 |
| ai/service·worker | Responses 시작·중지·continuation. approval 요청을 Java에 반환하고 Java 결정만 전달 |
| 출력 검증기 | 요구/인용/버전 등 코드 검사 + 독립 Jev 의미 검증 |

앱→AI 모델 실행은 ai/service HTTP를 유지한다. OpenAI→Java /mcp callback은 새 목표 경계이며 구현 PR에서 CLAUDE.md·네트워크·인증·계약을 함께 갱신한다. 비공개 Neo4j나 AI 저장소를 앱 챗봇이 직접 읽지 않는다. 모델 API 키와 MCP 위임 토큰은 분리한다.

`require_approval=always`의 승인자는 Java 작업 실행기다. ai/service는 `mcp_approval_request`를 Java에 반환하고, Java가 예산·요구·scope·grant·기한을 판단한 뒤 continuation을 다시 호출한다. 실행 중 MCP 오류 결과를 direct 결과로 끼워 넣지 않는다.

## 4. Q01~Q08 질의 유형

| 유형 | 목적 | 주 원천 / 웹 규칙 |
| --- | --- | --- |
| Q01 | 서비스 안내 | 승인 도움말·화면·정책, 웹 금지 |
| Q02 | 금융·산업 개념 | 웹 보조 근거 기본 시도, 실패 시 Luna 일반 개념 |
| Q03 | 기업·사건 사실 | 기업·문서·이슈·근거, 부족 시 마지막 웹 |
| Q04 | 관계·경로 | PublicGraphReader의 공개 스냅샷과 간선 근거, 웹은 외부 배경만 |
| Q05 | 기간·버전 비교 | 공개 버전·활성 이력·서버 차이 계산, 웹은 배경만 |
| Q06 | 브리핑 | 발행 회차·dataAsOf·포함 이슈·근거, 웹으로 회차를 재작성하지 않음 |
| Q07 | 내 종목 | 서버에서 본인 범위 확인 후 공개 조회, 외부에는 개별 공개 기업 정보만 |
| Q08 | 선정 근거 | 실제 규칙 revision·선정 기록, 웹으로 이유를 추정하지 않음 |

원문 요청은 해당 유형의 evidence.resolve 등으로 해결하며 Q06으로 재분류하지 않는다. Q02는 최신 사실·가격·전망 답변의 우회 경로가 아니다. 웹에만 있는 관계는 내부 지도 간선이나 포커스 대상이 아니다.

## 5. 동적 도구 선택

명시적 요구는 확률로 버리지 않는다. Jev p≥0.70은 후보, 0.35≤p<0.70은 검토 후보로 Luna가 선택할 수 있게 하며 낮은 확률이어도 명시 요구에 필요한 등록 도구는 포함한다. 확률은 권한이나 정답률 보장이 아니다. 관련 없는 도구를 모두 노출하지 않는다.

필수 capability는 실제 결과로 충족해야 한다. 같은 근거가 이미 다른 도구 결과에 있으면 불필요한 중복 호출을 강제하지 않는다. 의미적 충분성은 인용 개수나 evidenceSufficient boolean으로 단정하지 않는다. 모델은 requirementId와 미해결 항목을 제시하고 서버는 실제 결과·예산·권한을 검사한다.

### 5.1 실행 상한과 요청 캐시

| 항목 | 초기 상한 |
| --- | --- |
| 도구 시도 | 총 8회, 내부 최대 6회·웹 최대 2회, cache hit·실패·direct 조회 포함 |
| 동시 / 의존 | 최대 4개 / 총 3라운드, 추가 4번째 보충 없음 |
| 대상 / 자료 | fan-out·batch 최대 5개, 문서 20개, 그래프 3-hop·노드/간선 각 50개 |
| 개별 timeout | DB 3초·그래프 경로 5초·웹 7초, 잔여 기한으로 축소 |
| Luna / job | MCP·Java 승인 continuation·생성 합산 35초 / running부터 terminal-state DB commit 완료까지 45초 |
| 단계 예약 | router 4초·후검증 6초·서버 3초 |
| Luna 토큰 | 누적 입력 24,000·최종 답변 2,000, reasoning 비용은 별도 포함 예약 |
| 요구 / 확인 | 명시 요구 6개 / 확인 사슬 최대 2회 |
| 웹 일 상한 | 회원 20회·프로젝트 500회, KST 기준, 확인 사슬·재실행 누적 |

실효 Luna 시간은 min(35초, job 잔여 − 후검증 6초 − 서버 3초)다. router가 4초를 쓰면 32초다. 최종 작성용 10초를 남기고 새 도구를 중단한다. 제한으로 중단한 자료를 전체 조회라고 표시하지 않는다. 최악 경로가 예산을 넘으면 범위를 확인하며 실행 중에는 확인된 결과/안내로 종료한다.

초기 Responses reasoning effort는 `medium`이다. 구현 전에 도구 1·4·8회와 승인 continuation의 합성 replay 및 승인된 소량 live 지연 spike를 수행한다. `high`는 품질 이득과 45초 준수를 함께 증명한 뒤 적용한다.

캐시 키에는 job·실행 세대·도구/스키마/정책 revision·정규화 인자·회원 scope·버전·asOf를 포함한다. 동일 요청의 실제 조회는 1회이고 동시 요청은 single-flight로 합친다. 성공·정상 0건만 캐시하며 실패는 실패 원장으로 별도 관리한다. hit에도 권한·철회·model-send grant를 확인하고 원 결과와 toolCallId를 그대로 연결한다. 상세는 [MCP 계약 3.3절](ai-chatbot-mcp-actions.md#33-요청-단위-캐시와-중복-억제).

### 5.2 의존 실행과 체크포인트

서버가 개수 조건 exactly/atLeast/atMost를 요구에서 정한다. 초과이면 실제 대상의 choices로 clarification, 미달이면 가능한 요구만 답하고 precondition_unmet, 정상 0건이면 조회 범위 내 찾지 못함, truncated이면 확인 한계를 표시한다. 오류를 0건으로 평가하지 않는다.

Q07의 `portfolio.scope.read`는 Java server-only precondition이며 MCP에 노출하지 않는다. 전체 보유 목록·수량·보유 표시는 모델로 보내지 않고, scope 안에서 실제로 일치한 공개 사건·관계 결과만 최대 5개로 최소화한다. 웹이 필요한 기업이 2개를 넘으면 임의 두 기업을 고르지 않고 범위를 확인한다. 같은 질문 사슬 최대 2회 이후에도 선택이 안 되면 guidance로 종료한다.

## 6. 복합 질문 예시

‘A와 B의 관계·관련 사건·HBM 개념’을 물으면 Luna가 공개 경로와 사건을 조회하고 필요한 원문을 보충한다. HBM에는 Q02 웹 보조 근거를 사용할 수 있다. 내부 사실 요구가 남으면 마지막 웹 검색을 사용하며 총 2회 안에서 공유한다. 웹이 실패해도 확보한 경로·사건과 제한된 개념 설명을 제공하고 외부 미확인 부분을 알린다.

‘HBM 설명과 지금 살 주식’은 개념만 답하고 investment_advice limitation으로 제한한다. 웹 snippet의 매수 의견·목표주가도 답변에 인용하지 않는다.

## 7. 결과와 장애 응답

현재 ChatJob은 queued/running/completed/failed/cancelled, ChatResult.outcome은 answered/clarification/guidance/insufficient_evidence다. 이번 목표는 새 job 상태 PARTIAL이 아니라 별도 **answerStatus=complete|partial|guidance**, **notices[]** 및 장애 limitation 확장이다. 아직 DTO/OpenAPI/웹에 구현되지 않았다.

| 상황 | 목표 표시 |
| --- | --- |
| 모든 요구를 검증된 내용으로 답함 | answered + complete |
| 일부만 답함 | answered + partial, 미충족 요구별 limitation |
| 웹 보완만 실패, 내부로 모두 답함 | answered + complete, web_unavailable notice |
| Q02 웹 실패 | 일반 개념 설명 + web_unavailable, 명시 출처 요구가 남으면 partial |
| 아무것도 답할 수 없음 | guidance 또는 조회 성공 후 insufficient_evidence, 확인 범위·다음 행동 |
| 대상/기간 모호·fan-out 초과 | clarification, answerStatus=guidance |
| 모델 unknown·검증 실패·권한 위반 | 실제 failed/권한 오류 유지, 기존 failure 기반 고정 안내 |
| 취소·저장/전달 장애 | 상태를 완료로 가장하지 않고 해당 안내 |

‘항상 답변’은 서비스가 응답 가능한 한 내용을 답하거나 확인 불가 이유를 안내하는 원칙이다. 없는 사실 생성, 검증 생략, DB/HTTP 전체 장애에서도 전달 보장을 의미하지 않는다.

notices는 답변을 막지 않은 장애/처리 정보, limitations는 미충족 요구다. 이 둘을 분리해 답한 요구와 limitation을 정확히 하나에 대응시키는 기존 규칙을 유지한다. 웹 오류를 evidence_insufficient나 ‘관련 뉴스 없음’으로 숨기지 않는다.

현재 공개 limitation kind는 `investment_advice`, `precondition_unmet`, `results_truncated`, `not_in_member_scope`(내 종목(Q07) 질문이 지목한 기업이 회원의 보유·관심 종목이 아님, 서버 `portfolio.scope.read` 판정), `evidence_insufficient`, `out_of_scope`다. 장애 원인 kind 확장은 목표 계약이다.

## 8. 검증과 복구

### 8.1 호출 전·실행 중 검사

서버는 허용 도구·스키마·대상·scope·고정 버전·기한·호출 수를 검사한다. MCP 결과를 OpenAI에 반환하기 전에 source grant와 모델 전송 범위를 검사한다. Luna의 자체 coverage 판단은 추가 조회 신호이며 최종 정답 판정이 아니다.

direct adapter는 Responses 시작 전 preflight 실패·circuit open일 때만 시작 경로로 선택하며 같은 결과/권한/cache/원장/예산을 사용한다. 실행 중 MCP 오류는 direct 결과로 바꿔 끼우지 않고 성공한 결과와 notice/limitation으로 종료한다. 권한·인증·grant·schema 거부는 direct로 우회하지 않는다. 결과 불명 모델 호출은 재전송하지 않는다. 최근 MCP 연결 5회 중 3회 실패하면 30초 차단 후 probe 1회로 복구 여부를 판단한다.

### 8.2 생성 후 출력 검증

| 검사 | 기준 |
| --- | --- |
| 스키마·요구 커버리지 | typed JSON, 명시 요구별 답변 또는 실제 사유 limitation, notice 별도 |
| 인용 실재·원문 | 이번 job의 실제 sourceId/evidenceId·고정 버전·인용 구간 일치 |
| basis | 일반 개념/ZOOP 문서/내부 근거/web_reported 구분, 인용 종류 일치 |
| 수치·그래프 | 원문·구조화 데이터 일치, 실제 endpoint·방향·hop·공개 버전 |
| 권한·범위 | 현재 공개/철회·Q07 본인 범위·개인정보·grant |
| 표현 | 투자 권유·목표주가·가격/수익 예측 금지, 웹 인용도 예외 없음 |

결정론 검사 통과 후 별도 Jev를 최대 1회 호출한다. 근거 주장마다 supported/contradicted/insufficient 및 prohibitedAdvice·unsupportedCausality를 확인한다. 일반 지식 구간은 사실 검증으로 표시하지 않고 prohibitedAdvice를 확인한다. 모든 정상 일반 개념 답변에도 이 정책 검사를 적용한다.

contradicted·금지 조언 또는 결정론적 검증 실패는 해당 정책에 따라 본문 차단, validation_failed 원장과 고정 안내다. hold는 해당 요구와 의존 통합 구간을 제외하고 limitation을 만든다. 남은 답이 없으면 insufficient_evidence다. 자동 재생성하지 않는다. 기존 개념 하위 요구의 결정론적 제외 예외는 [부분 답변 기록 3.1절](ai-chatbot-partial-answer.md#31-하위-요구-구간의-추가-검사)을 유지한다.

general_knowledge에는 서버 고정 안내 ‘일반 개념 설명입니다. 최신 기업·시장 사실은 별도 조회가 필요합니다.’를 붙이고 evidenceIds는 비운다. web_reported는 ‘웹 검색 결과 · ZOOP 미검증’으로 표시하고 실제 출처만 연결한다. answerBasis는 서버가 구간에서 계산한다.

## 9. 보안·UI·문맥

- 모델이 생성한 SQL·Cypher·임의 URL·스크립트를 실행하지 않는다. 도구는 읽기 전용이다.
- UI 제안은 유효 조회 ID에서 서버가 만들고 사용자 클릭 시 실행한다. graphTargets와 uiActions는 같은 도메인 결과에서 파생하며 충돌 시 동작을 차단한다.
- 재열람·polling은 검색·모델 호출·화면 동작을 재실행하지 않는다. 검증 전 본문은 숨긴다.
- 이전 일반 턴 문맥 승계는 별도 신규 기능이다. 직전 완료 2턴의 검증된 ID·기간만 사용하고 현재 권한을 재검사한다. 본문은 승계하지 않는다.

## 10. 현재 구현과 목표의 경계

| 영역 | 현재 코드 | 추가 구현 |
| --- | --- | --- |
| 공개 job | 회원 전용 저장·polling·멱등성·취소·lease·재시도 | answerStatus/notices·장애 limitation, 저장 복구 |
| 모델 | chat-router Jev·chat-answer Luna·chat-verification Jev, Luna는 chat/completions·high·도구 없음 | Luna Responses MCP·Java 승인 continuation·medium·사용량·deadline |
| 도구 | company.read, issue.read, evidence.resolve, graph.path.read, graph.version.diff, portfolio.scope.read, zoopPolicy.read | portfolio.scope.read는 server-only, 나머지 MCP 외피·공통 gate·cache·direct 시작 경로 |
| 근거·검증 | BranchContext·서버 citation·결정론 검사·section Jev | 웹 출처·claim 인과 검증·token guard·grant 선반환 검사 |
| 화면 | D-AI-01~02b API 연결·결과/인용/확인/실패 | 새 목표 필드·부분 안내·UI 동작, 와이어프레임 근거와 종단 시험 |

문서 개정으로 런타임·OpenAPI·DB·Figma를 변경하거나 실제 모델을 실행한 것은 아니다. 날짜별 구현 증거는 [개발 계획](../development/ai-chatbot-implementation-plan.md)에 보존한다.

## 11. 개발·출시 판단

1. MCP 서버 단독 클라이언트 시험과 합성 Responses replay로 typed 계약·승인/취소/unknown을 고정한다.
2. 도구 1·4·8회·승인 라운드의 승인된 소량 live latency spike로 45초 가능성을 측정한다.
3. 읽기 도구의 공통 gate·요청 cache/single-flight·budget·preflight direct 시작 경로를 구현한다.
4. Q02 기본 웹, Q03~Q08 최후 검색, 비치명적 웹 오류·snapshot·grant를 구현한다.
5. DTO/OpenAPI/저장/웹/guard와 화면 추적을 함께 갱신한다.
6. 같은 질문 세트에서 기존 서버 계획과 Luna MCP의 요구 충족·근거 지지·p95·비용을 비교하고 단계적으로 활성화한다.

MCP 자체가 정확도 향상을 보장하지 않는다. 중간 결과 기반 추가 조회의 이점과 비용·지연을 분리해 평가한다.
