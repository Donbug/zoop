# ZOOP AI 챗봇 고정 평가 세트

기준일: 2026년 10월 27일 / 세트 버전: `chat-eval-v1`

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
| `appliedCompanies`, `appliedIssues`, `questionOverrodeContext`, `graphTargets`, `choices` | 결과의 `applied`, 지도 대상, 확인 질문 선택지 ID |

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

36개 사례: Q01 2, Q02 2, Q03 8, Q04 2, Q05~Q08 각 1, 복합 6, 투자 판단 4, 공격 3, 확인 질문 1, 장애 4. 2026-10-27 기준 모두 통과한다(대본 실행).

세트를 만들며 확인한 현재 공백(`gap` 표시 사례):

| 사례 | 공백 |
| --- | --- |
| `q03-catalog-only-company` | 카탈로그에만 있고 공개 그래프에 없는 기업은 `nothing_found`다. 실제 데이터에서 근거 부족의 주원인인지 잰다. |
| `q01-help-unbound`, `q05`~`q08` | 도구 미연결·미구현으로 `out_of_scope` 안내다. |

v1에서 찾은 공백 중 사건 이름 미해석과 기업 대상 `issue.read`의 빈 결과는 2026-10-27에 고쳤다(구현 계획 사건 지목 결정 (5)·(6)). `q03-issue-named`, `q03-issue-and-company-named`, `q03-company-issues-by-name`이 그 동작을 고정하고, `failure-graph-unreadable-concept`는 그래프를 읽을 수 없어도 순수 개념 질문은 답하는지(사건 이름을 필요할 때만 해석하는지) 확인한다. 같은 말에 맞는 사건이 여럿인 확인 질문은 fixture에 그런 사건이 없어 `IssueNameResolverTest`·`ChatModelStagesTest`가 다룬다.

세트에 넣지 못한 것:

- **체크포인트·의존 단계**: 라우터 wire(`zoop-ai-chat-1`)에 의존 관계 필드가 없어 `ChatModelStages`는 항상 `dependsOn: null`을 만든다. 질문에서 `exactly(2)` 같은 체크포인트를 만들 경로가 없으므로, 그 흐름은 `OrchestratedChatEngineTest`의 결정 대본으로만 확인된다. 라우터 계약에 의존 관계가 들어오면 이 세트에 사례를 추가한다.
- **확인 질문의 답(깊이 1·2)**, **선택 근거로 좁힌 질문(`evidencePool`)**, **시간 한도(`deadline_guard`)**: 실행기가 단일 턴·고정 시간만 다룬다. 필요하면 사례 형식에 `turns`와 남은 시간을 더한다.

## 6. 다음 단계

1. 사례 추가: 새 도구·유형을 연결하는 PR은 그 유형의 사례를 같은 변경에서 추가하거나 `gap` 사례의 기대값을 고친다.
2. 실제 모델 실행: 같은 세트에서 `script`를 무시하고 AI 서비스의 live 단계를 부르는 모드를 둔다. 그때 비교 대상은 `expect` 중 모델과 무관한 서버 결정과 outcome 분포다. 유료 호출이므로 실행마다 사용자 승인과 호출 상한이 필요하다.
3. 실제 데이터 측정: 담당자 로컬의 실제 그래프·근거로 실행해 근거 부족 비율과 `droppedGeneral` 비율을 잰다. 이 값과 사례별 기대 결과로 라우터 임계값(0.70/0.35)과 투자 판단 0.10을 보정한다.
