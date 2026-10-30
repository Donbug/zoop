# ZOOP AI 챗봇 고정 평가 세트

기준일: 2026년 10월 28일 / 실행 세트 버전: `chat-eval-v1` / 다음 목표: `chat-eval-v2`

관련 문서:

- [AI 챗봇 구현 준비·개발 계획](ai-chatbot-implementation-plan.md) — 단계 7(평가·관측·점진 출시)
- [AI 챗봇 설계 요약](../design/ai-chatbot-design-summary.md) — 10장(남은 일: 고정 평가 세트와 임계값 보정)
- [AI 챗봇 부분 답변 설계](../design/ai-chatbot-partial-answer.md) — 개념 하위 요구와 `droppedGeneral`

## 1. 목적과 범위

질문 유형(Q01~Q08), 복합 질문, 투자 판단, 공격 입력, 확인 질문, 장애를 한 세트로 고정하고 질문마다 서버가 내야 할 결과를 적어 둔다. 실행기는 `./api/gradlew -p api test`에 포함되어 CI에서 흐름 회귀를 잡는다.

| 무엇을 확인하나 | 무엇을 확인하지 않나 |
| --- | --- |
| 질문 문장의 실제 요구 분해(`ChatRequirementSplitter`)와 카탈로그 이름 해석(`CompanyNameResolver`) | 모델이 질문을 맞게 분류하는지(라우터 확률은 대본 값) |
| 계획(임계값·제한·기본 조회·개념 하위 요구), 도구 호출, 체크포인트 밖의 서버 결정 | 생성 답변의 품질·사실성(생성·검증 응답도 대본 값) |
| 결정론 검사, 인용 구성, `answerBasis`, outcome·사유 코드, 제한 종류와 문구 원인 | 임계값(0.70/0.35, 투자 판단 0.10)의 적정성 |
| 모델 세 단계 wire 형식(`ChatModelStages`)의 왕복 | 실제 기사·근거 분포에서의 근거 부족 비율 |

대본 응답과 합성 fixture로 얻은 수치는 **흐름 검증용**이다. 품질 튜닝이나 임계값 보정에 쓰지 않는다. 실제 데이터와 모델로 같은 세트를 돌리는 방법은 6장에 적었다.

## 2. 구성

- 세트: `api/src/test/resources/chat-eval/chat-eval-v1.json`
- 실행기: `api/src/test/java/com/zoop/chat/model/ChatEvalSetTest.java` (사례마다 JUnit 동적 시험 하나)
- 결과: `api/build/reports/chat-eval/chat-eval-v1.json`(사례별 관측값), `chat-eval-v1.md`(요약 표)
  - 실행이나 관측 중 예외로 끝난 사례도 실패로 보고한다. `observed.outcome=error`이고, `error`에 던져진 예외, `observed.stages`에 도달한 단계를 남긴 뒤 예외를 다시 던진다. 예: 대본에 없는 생성 단계가 호출된 경우.
  - 요약의 `setCases`는 세트 전체 사례 수, `cases`는 보고된 사례 수, `errors`는 예외로 끝난 사례 수다. 세트에는 있는데 보고되지 않은 사례 ID는 `notReported`에 적고 표 위에 따로 표시한다. 필터로 일부만 돌렸거나 시작하지 못한 사례이며 통과로 세지 않는다.

실행 경로는 운영과 같다. 질문 → `ChatModelStages`(요구 분해·이름 해석, 모델 단계 wire) → `OrchestratedChatEngine`(계획·조회·검사·결과) → 실제 읽기 도구(`company.read`, `issue.read`, `evidence.resolve`, `graph.path.read`, `zoopPolicy.read`). 다른 점은 세 가지뿐이다.

1. AI 서비스 대신 대본 클라이언트가 라우터·생성·검증 단계에 답한다.
2. 그래프는 합성 fixture `fixture-2026-10-08`(기업 7개, 사건 4개)을 고정 버전으로 읽는다. 모든 근거는 읽을 수 있다.
3. 카탈로그 이름, 기업 개요 2건, 약관·개인정보 처리방침 각 2구간은 세트 파일의 합성 값이다. 카탈로그에는 그래프에 없는 기업(한미약품, 카카오)과 같은 별칭을 가진 두 기업(`한미`)을 일부러 넣었다.

## 3. 사례 형식

```json
{
  "id": "compound-concept-and-fact",
  "group": "compound",
  "question": "HBM이 뭐고 SK하이닉스는 HBM을 어디에 공급해",
  "selection": {"contextIds": ["iss-fixture-hbm-supply"]},
  "graphVersion": "fixture-2026-10-08",
  "script": {
    "router": {"r1": {"types": {"Q02": 0.9, "Q03": 0.9}, "capabilities": {"company.read": 0.9}, "prohibitedAdvice": 0.0}},
    "answer": {"sections": [{"basis": "evidence_grounded", "text": "…", "requirementIds": ["r1"], "evidenceIds": ["$branch"]}],
               "insufficientRequirementIds": [], "graphTargetIds": []},
    "verify": [{"support": "supported", "prohibitedAdvice": "no"}]
  },
  "expect": {"outcome": "answered", "planned": ["r1:tools", "r1-c:general"]},
  "gap": "알려진 공백이 있으면 그 설명"
}
```

- `group`: `Q01`~`Q08`, `compound`, `advice`, `attack`, `clarification`, `failure`.
- `selection`, `graphVersion`: 생략하면 선택 없음과 `fixture-2026-10-08`. `graphVersion: null`은 고정된 공개 그래프가 없는 질문이고, 없는 버전 이름은 읽을 수 없는 그래프다.
- `memberScope`: Q07에서 회원의 보유·관심 종목 `[{id, name, held, watched}]`. 생략하면 없음이다. 실제 회원 데이터 대신 `portfolio.scope.read`가 이 목록을 읽는다.
- `script.router`: 분해된 요구 ID(`r1`, `r2`…)마다 라우터 답. `{"fail": "unknown" | "sent" | "refused"}`는 단계 실패다. 라우터가 호출되지 않는 사례(요구 7개 이상, 공유 이름)는 `script`를 비운다.
- `script.answer`의 `evidenceIds`에서 `$branch`는 그 구간의 첫 요구에 실제로 보낸 인용 전부, `$branch:N`은 앞에서 N개다. 그 밖의 값은 그대로 보낸다(지어낸 근거 ID 공격).
- `script.verify`를 생략하면 모든 구간이 통과한다(일반 구간은 `support: null`).
- 대본에 없는 단계가 호출되면 그 사례는 실패한다. 기대하지 않은 모델 호출도 회귀로 본다.
- `gap`: 현재 동작을 기대값으로 고정하되, 목표와 다른 점을 적는다. 기능이 들어오면 기대값과 함께 고친다.

### 기대값

적은 항목만 비교한다. 모르는 키는 오타로 보고 실패한다.

| 키 | 의미 |
| --- | --- |
| `requirements` | 분해된 요구 문장(순서대로) |
| `targets` | 요구별로 해석된 기업 ID |
| `stages` | 호출된 모델 단계(`router`, `answer`, `verify`) |
| `tools` | 예약된 도구 capability(중복 제거, 정렬) |
| `outcome`, `reason` | 결과와 서버 사유 코드(`out_of_scope`, `nothing_found` 등). `failed`면 `failure: {kind, reason, rerunnable}` |
| `deterministicCheck` | 1층 검사에서 처음 실패한 검사 ID |
| `answerBasis`, `citationKinds` | 답변 근거 수준, 인용 종류 집합 |
| `limitations` | `{kind, label, cause}` 목록. `cause`(`evidence_held`, `nothing_found`)는 문구에 원인이 드러나는지 본다 |
| `planned` | 계획된 요구와 방식(`r1:tools`, `r1-c:general` 등). 개념 하위 요구 유무를 여기서 본다 |
| `droppedGeneral`, `heldRequirements` | 1층 검사로 뺀 개념 구간, 의미 검증이 보류한 요구 |
| `appliedCompanies`, `appliedIssues`, `appliedPeriod`, `questionOverrodeContext`, `graphTargets`, `choices` | 결과의 `applied`, 지도 대상, 확인 질문 선택지 ID |

## 4. 실행

```sh
export JAVA_HOME=<JDK 21>
./api/gradlew -p api test --tests 'com.zoop.chat.model.ChatEvalSetTest'
```

사례 하나가 실패하면 시험 이름이 사례 ID이고, 메시지에 어긋난 기대값이 모두 나온다. 결과 파일은 실패가 있어도 쓴다.

요약에는 두 비율이 있다. 실제 데이터에서 추적하려는 값이며, 대본 실행에서는 집계가 동작하는지만 보여 준다.

- 근거 부족: 도구를 호출한 사례 중 outcome이 `insufficient_evidence`이거나 `evidence_insufficient` 제한이 붙은 사례
- 개념 하위 요구 제외: 개념 하위 요구(`-c`)가 계획된 사례 중 `droppedGeneral`이 있는 사례

## 5. v1 사례와 드러난 공백

45개 사례: Q01 2, Q02 2, Q03 8, Q04 2, Q05 3, Q06 1, Q07 8, Q08 1, 복합 6, 투자 판단 4, 공격 3, 확인 질문 1, 장애 4. 2026-10-27 기준 모두 통과한다(대본 실행).

세트를 만들며 확인한 현재 공백(`gap` 표시 사례):

| 사례 | 공백 |
| --- | --- |
| `q03-catalog-only-company` | 카탈로그에만 있고 공개 그래프에 없는 기업은 `nothing_found`다. 실제 데이터에서 근거 부족의 주원인인지 잰다. |
| `q01-help-unbound`, `q06`, `q08` | 도구 미연결·미구현으로 `out_of_scope` 안내다. |

v1에서 찾은 공백 중 사건 이름 미해석과 기업 대상 `issue.read`의 빈 결과는 2026-10-27에 고쳤다(구현 계획 사건 지목 결정 (5)·(6)). `q03-issue-named`, `q03-issue-and-company-named`, `q03-company-issues-by-name`이 그 동작을 고정하고, `failure-graph-unreadable-concept`는 그래프를 읽을 수 없어도 순수 개념 질문은 답하는지(사건 이름을 필요할 때만 해석하는지) 확인한다. 같은 말에 맞는 사건이 여럿인 확인 질문은 fixture에 그런 사건이 없어 `IssueNameResolverTest`·`ChatModelStagesTest`가 다룬다.

Q07에서 질문이 기업을 지목하는 경우(구현 계획 결정 (11))는 `q07-named-in-scope`, `q07-named-partly-outside`, `q07-named-outside`, `q07-anchor-outside`가 고정한다.

세트에 넣지 못한 것:

- **체크포인트·의존 단계**: 라우터 wire(`zoop-ai-chat-2`)에 의존 관계 필드가 없어 `ChatModelStages`는 항상 `dependsOn: null`을 만든다. 질문에서 `exactly(2)` 같은 체크포인트를 만들 경로가 없으므로, 그 흐름은 `OrchestratedChatEngineTest`의 결정 대본으로만 확인된다. 라우터 계약에 의존 관계가 들어오면 이 세트에 사례를 추가한다.
- **확인 질문의 답(깊이 1·2)**, **선택 근거로 좁힌 질문(`evidencePool`)**, **시간 한도(`deadline_guard`)**: 실행기가 단일 턴·고정 시간만 다룬다. 필요하면 사례 형식에 `turns`와 남은 시간을 더한다.

## 6. 다음 단계

### 2026-10-28 v0.11 수용 사례 (chat-eval-v2 추가 예정)

현재 `chat-eval-v1` 실행 증거와 구분한다. 아래는 구현 후 고정 fixture·기대 호출·결과를 추가할 항목이며 이번 개정으로 테스트가 추가되거나 통과한 것은 아니다.

| 사례 | 기대 결과 |
| --- | --- |
| Q02 단독 안정적 개념 | 웹 보조 최대 1회, 성공 시 web_reported; 0건·장애면 제한된 일반 지식과 notice, 불필요한 Q03/Q04 없음 |
| Q02+Q03+Q04 복합 요구 | 필요한 조회 조합·중복 제거, 명시 요구 누락 없음, 최종 생성 1회 |
| 네 유형 이상 필수 요구 | top-3로 자르지 않음, 예산 초과 시 clarification |
| Q01 단독 / Q01+Q03 | Q01 검색·웹 근거 차용 없음, 복합 질문의 Q03에만 필요 검색 |
| Q02~Q08 각각 검색 필요/불필요 쌍 | 필요한 경우만 검색, 내부 0건이 아니어도 외부 보완 가능 |
| 웹에만 있고 내부 그래프에 없는 관계 | 외부 보도와 내부 경로 구분, 간선·포커스 대상 생성 금지 |
| Q05/Q06/Q08 외부 정보 불일치 | 실제 차이·발행 회차·기록된 선정 이유를 웹으로 덮지 않음 |
| Q07 보조 검색 | 본인 범위 먼저 확인, 원문·식별자·수량·전체 포트폴리오 전송 없음 |
| 다음 턴 Q04→Q02 / 그 회사·최신 | 재분류, 검증된 문맥 승계, 명시 조건 우선·모호성 확인 |
| polling·재열람 | 새 분류·검색·모델 호출·UI 동작 실행 없음 |
| Q03~Q08 내부 근거 충분/부족 쌍 | 충분하면 웹 0회, 부족·최신성·출처 요청이면 마지막 라운드에서만 웹 |
| 검색 0건 / timeout / unavailable | 전체 답변 유지, web_unavailable notice와 실제 미충족 limitation 분리 |
| 배치 검색·재시도·기한 초과 | 총 8·내부 6·웹 2, job 45초, Luna 잔여 기한·마지막 10초 작성 예약 준수 |
| 동일 logical call 동시·순차 중복 | single-flight 1회, 성공 0건 포함 요청 cache hit, 권한·grant 재검사 |
| cache key의 scope·version·asOf 차이 | 서로 합치지 않음, job 종료 뒤 재사용 없음 |
| MCP/direct 동일 fixture | 같은 Tool Service의 결과·권한·버전·evidence 정규화 동등 |
| Responses 시작 전 preflight 실패·circuit open | MCP 미노출, 처음부터 direct adapter·BranchContext 경로, 같은 예산·grant |
| Responses 실행 중 MCP transport 실패 | direct 결과 끼워 넣기 0회, 성공 결과 유지·notice/limitation, 다음 job circuit 반영 |
| 인증·권한·grant·스키마 거부 | direct 우회 0회, 거부 원인 유지 |
| MCP 결과 수신 여부 불명 | 자동·수동 중복 호출 0회, response_unknown/reconciliation |
| 최근 5회 중 연결 3회 실패 | 30초 circuit open, half-open probe 1회; 인증·DB 오류는 집계 제외 |
| mcp_approval_request 1·3라운드 | ai/service 독자 승인 0회, Java의 예산·요구·scope·grant 결정만 continuation에 사용 |
| approval 거부 | 위조 MCP/function 결과·direct 대체 메시지 0회, 다른 정상 근거 또는 limitation/guidance |
| Q07 portfolio scope | portfolio.scope.read MCP catalog 미등록, 전체 목록·수량·보유 표시 모델 전송 0건, 일치 공개 결과 최대 5개 |
| /mcp 외부 경계 | 64 KiB request·256 KiB call result·1 MiB job·분당 30·동시 4 위반 거부 |
| 도구 1·4·8회 latency | server-only client, 합성 Responses replay, 승인된 소량 live를 분리 기록; terminal DB commit까지 45초 |
| 인용 위조·snippet 미지지·프롬프트 주입 | 출처·요구 매핑 및 의미 검사, 외부 지시 무시 |
| MCP 미등록 도구·위조 subject·스키마 변경 | 차단, allowlist 자동 확장 없음 |
| Luna allowed_tools·연속 호출 | 허용 도구만 선택, 새 정보 이득 없는 반복 거부, 명시 요구별 서버 coverage |
| 부분 결과 | answerStatus complete/partial/guidance, notices와 limitations 중복 없음 |
| UI 대상 철회·버전 변경·외부 보도 ID 위조 | 클릭 시 재검사·안내, 임의 경로 실행 없음 |
| snapshot 만료·grant 부재 | 재현 불가 구간 가림·모델 전송 차단, 거짓 최신성 표시 없음 |

상세 기준: [보조 웹 검색](../design/ai-chatbot-web-search.md), [Luna MCP 실행·화면 동작](../design/ai-chatbot-mcp-actions.md).

### 평가 운영 작업

1. 사례 추가: 새 도구·유형을 연결하는 PR은 그 유형의 사례를 같은 변경에서 추가하거나 `gap` 사례의 기대값을 고친다.
2. 실제 모델 실행: 같은 세트에서 `script`를 무시하고 AI 서비스의 live 단계를 부르는 모드를 둔다. 그때 비교 대상은 `expect` 중 모델과 무관한 서버 결정과 outcome 분포다. 유료 호출이므로 실행마다 사용자 승인과 호출 상한이 필요하다.
3. 실제 데이터 측정: 담당자 로컬의 실제 그래프·근거로 실행해 근거 부족 비율과 `droppedGeneral` 비율을 잰다. 이 값과 사례별 기대 결과로 라우터 임계값(0.70/0.35)과 투자 판단 0.10을 보정한다.
