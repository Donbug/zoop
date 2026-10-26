# ZOOP AI 챗봇 부분 답변 분기와 일반 지식 대체 경로 설계 (초안)

문서 상태: 설계 초안 · 구현 전 · 2부(일반 지식 대체 경로)는 거버넌스 정책 개정과 팀 승인 필요

기준일: 2026년 10월 26일 / 기준 코드: main `3eba73af` / 기준 정책: [ZOOP-AIG-001 v0.9](../ZOOP_AI_거버넌스_정책.md) / 설계 요약: [AI 챗봇 설계 요약](ai-chatbot-design-summary.md)

화면 추적: `D-AI-01`, `D-AI-02`

## 1. 목적

근거가 일부만 있는 질문에서 답변 전체가 "근거 부족"으로 끝나는 일을 줄인다. 원칙은 바꾸지 않는다.

- 기업·사건·시장의 **사실은 근거가 있을 때만** 말한다.
- 근거 없는 설명은 `general_knowledge` 구간에만 쓰고, 화면에서 근거 있는 구간과 구분한다.
- 도구 장애·timeout은 지금처럼 `failed`다. 일반 지식 답변으로 덮지 않는다.

두 부분으로 나눈다.

| 부분 | 내용 | 정책 |
| --- | --- | --- |
| 1부: 부분 답변 분기(A안) | 한 요구 안에 개념(Q02)과 사실(Q03 등)이 섞이면 서버가 개념 하위 요구를 따로 만든다 | 현재 정책 안. Q02 개념 답변은 이미 허용된다 |
| 2부: 일반 지식 대체 경로 | Q03 요구가 조회에 성공했지만 근거가 0개면, 서버가 일반 배경 하위 요구를 붙인다. 사실 부분은 계속 근거 부족으로 표시한다 | 정책 개정 필요. 라우터가 Q02로 분류하지 않은 질문에 일반 지식 구간을 붙이기 때문이다 |

검토한 다른 안:

- **근거가 없으면 일반 LLM에게 사실까지 답하게 하는 전면 대체:** 채택하지 않는다. 근거가 없을 때 Luna에 넘길 context도 비어 있으므로, 모델은 학습 시점 기억으로 최신 사실·수치·사건을 말하게 된다. 검증 단계(Jev)도 대조할 근거가 없다. 최신 사실이 필요한 경우는 출처를 붙일 수 있는 [웹 검색 대체 경로](ai-chatbot-web-search.md)가 맡는다.
- **B안(한 요구 안에서 일반 지식 구간과 근거 부족을 함께 허용):** 채택하지 않는다. "필수 요구마다 본문 답변 또는 limitation 중 정확히 하나"라는 규칙(설계 요약 7장)과 결정론 검사의 `coverage` 규칙을 다시 써야 한다.

## 2. 지금 동작 (main `3eba73af`)

| 상황 | 지금 결과 | 코드 |
| --- | --- | --- |
| 라우터가 개념과 사실을 **요구 2개**로 나눔 | 개념은 `general_knowledge`, 사실은 근거가 있으면 `evidence_grounded`, 없으면 `evidence_insufficient` limitation. `answered`·`mixed` | `OrchestratedChatEngine.java:220-240` |
| 라우터가 개념과 사실을 **요구 1개**로 묶음(Q02+Q03) | 도구 조회 요구가 된다. 일반 지식 구간은 쓸 수 없다(`general_section` 실패). 근거가 0개면 개념 설명도 없이 `insufficient_evidence` | `ChatPlanner.java:137-144`, `ChatAnswerCheck.java:96` |
| Q02만 분류됐지만 기업을 지목했고 Q03이 0.35 이상 | Q03을 더해 위와 같아진다 | `ChatPlanner.java:137-140` |
| 개념+사실 요구인데 사실 쪽에 허용된 도구가 없음 | 개념 설명 없이 요구 전체가 `out_of_scope` | `ChatPlanner.java:167-168` |
| Q03 조회 성공, 찾은 것 없음(`noneFound`) | Luna가 "조회 범위에서 찾지 못했다"는 근거 구간(인용 없음)을 쓴다 | `ChatAnswerCheck.java:110-113` |
| Q03 조회 성공, 항목은 있지만 인용할 evidence 0개 | Luna가 요구를 `insufficientRequirementIds`에 넣는다. 다른 답이 없으면 `insufficient_evidence` | `OrchestratedChatEngine.java:222-228` |

두 경우 모두 Luna 생성과 Jev 검증은 이미 한 번씩 호출된다. 모델 호출 없이 끝나는 것은 모든 요구가 limitation(투자 판단·범위 밖·선행 조건 미충족)일 때뿐이다(`OrchestratedChatEngine.java:178-183`).

## 3. 공통 장치: 서버 하위 요구

1부와 2부 모두 같은 장치를 쓴다. 계획 단계가 원래 요구 옆에 **서버가 만든 `GENERAL` 하위 요구**를 하나 더 둔다.

- ID: 원래 요구 ID + 접미사. 개념은 `-c`, 배경은 `-b`(예: `r1-c`).
  - 워커 계약의 요구 ID 형식(`^[A-Za-z0-9_-]{1,32}$`)을 지킨다. 원래 ID가 30자를 넘거나 같은 ID가 이미 있으면 하위 요구를 만들지 않는다.
- `explicit=false`로 다룬다. 그래서 Luna가 이 하위 요구를 답하지 않아도(`insufficientRequirementIds`) limitation이 생기지 않는다(`OrchestratedChatEngine.explicit`).
- 라벨은 서버가 쓴다.
  - 개념: `<원 라벨> — 개념 설명`
  - 배경: `<원 라벨> — 일반 배경(특정 기업·사건의 사실 제외)`
- 공개 `ChatResult.sections`에는 요구 ID가 나가지 않는다(`ChatResults.answered`). 그래서 **공개 OpenAPI는 바뀌지 않는다.** limitation 종류도 기존 것만 쓴다.
- 워커 계약 `zoop-ai-chat-1`도 바뀌지 않는다. 하위 요구는 기존 `general=true` branch로 간다.
- route 요약(`chat_jobs.route`)의 요구 항목에 `origin`(`router` / `concept` / `background`)과 `parent`를 남겨 감사할 수 있게 한다.
- 상한:
  - 하위 요구는 원래 요구마다 최대 1개다. 명시 요구 상한 6개(`MAX_REQUIREMENTS`)에는 세지 않는다.
  - 생성 branch가 구간 상한 12개(`ChatAnswerCheck.MAX_SECTIONS`)를 넘게 되면, 배경 하위 요구를 뒤에서부터 빼고 그다음 개념 하위 요구를 뺀다.

### 3.1 하위 요구 구간의 추가 검사

`general_knowledge` 구간의 기존 검사(`general_section`: 인용 없음, 순수 일반 요구만, 금액·비율·연도·날짜·"최근" 같은 최신 사실 표지 금지)와 고정 안내 문장, Jev `prohibitedAdvice` 판정은 그대로 적용한다. 하위 요구 구간에는 다음을 더한다.

- **대상 이름 금지(새 검사 `general_names`):** 하위 요구 구간에는 원래 요구가 지목한 기업·사건의 표시 이름이 들어가면 안 된다.
  - 이름의 출처는 원래 요구의 도구 결과 `items`(company·issue)의 label이고, 없으면 기업 카탈로그 이름이다.
  - 숫자가 없는 특정 기업 사실(예: "OO는 HBM을 주로 △△에 공급한다")은 최신 사실 표지 검사로는 걸러지지 않는다. 그래서 이름 자체를 막는다.
- **실패 처리:** 하위 요구 구간이 `general_section`이나 `general_names`에 걸리면, 실행 전체를 `validation_failed`로 끝내지 않고 **그 구간만 뺀다.** 빠진 하위 요구는 limitation을 만들지 않고, route 요약에 `droppedGeneral`로 남긴다.
  - 하위 요구는 회원이 직접 요구한 것이 아니라 서버가 덧붙인 보조 설명이기 때문이다. 원래 요구 구간의 검사 실패는 지금처럼 실행 전체 실패다.
  - 투자 권유 문구(`investment_wording`)와 Jev `prohibitedAdvice=yes`는 하위 요구 구간이어도 지금처럼 실행 전체 실패다.
- **Jev hold:** 하위 요구 구간이 hold되면 기존 규칙대로 그 구간만 빠진다. `explicit=false`라 limitation은 생기지 않는다.

### 3.2 Luna 프롬프트

계약은 그대로 두고 시스템 프롬프트에 두 문장을 더한다. 프롬프트 개정이므로 `PROMPT_REVISION`을 올리고 replay fixture를 함께 갱신한다.

- "일반 branch의 구간에는 다른 branch의 기업·사건 이름을 쓰지 않는다."
- "라벨이 '일반 배경'인 branch는 특정 기업·사건의 사실을 쓰지 않고, 그 질문을 이해하는 데 필요한 개념과 일반적인 구조만 설명한다. 쓸 내용이 없으면 insufficientRequirementIds에 넣는다."

## 4. 1부: 부분 답변 분기(A안)

### 4.1 언제 나누나

`ChatPlanner.serve`가 요구를 `TOOLS`나 `LIMITED`로 정한 뒤, 다음을 모두 만족하면 개념 하위 요구(`-c`)를 더한다.

1. 요구 유형에 Q02가 있다(`types[Q02] ≥ 0.70`, 또는 지금처럼 Q02만 분류됐다가 기업 지목 때문에 Q03이 더해진 경우).
2. Q02 말고 다른 유형도 있다(그렇지 않으면 원래부터 순수 `GENERAL` 요구다).
3. 요구가 투자 판단으로 제한되지 않았다(`prohibitedAdvice > 0.35`면 하위 요구도 만들지 않는다).
4. 원래 요구의 결과가 `TOOLS`이거나 `LIMITED`(`out_of_scope`, `precondition_unmet`)다.
   - `out_of_scope`인 경우: 지금은 개념 설명까지 사라지지만, 이제 개념 하위 요구는 답한다. 원래 요구는 `out_of_scope` limitation으로 남는다.

원래 요구는 하위 요구가 생겨도 지금과 똑같이 계획·조회·검사된다.

### 4.2 결과 예

질문(라우터가 요구 1개로 묶은 경우): "HBM이 뭐고 SK하이닉스 최근 HBM 뉴스는?"

| 조회 결과 | 구간 | limitation | outcome · answerBasis |
| --- | --- | --- | --- |
| 뉴스 근거 있음 | `general_knowledge`(HBM 설명) + `evidence_grounded`(뉴스, 인용) | 없음 | `answered` · `mixed` |
| 조회 성공, 찾은 것 없음 | `general_knowledge` + `evidence_grounded`("조회 범위에서 찾지 못했어요", 인용 없음) | 없음 | `answered` · `mixed` |
| 항목은 있지만 인용할 근거 0개 | `general_knowledge` | `evidence_insufficient`(원래 요구) | `answered` · `general_knowledge` |
| 사실 쪽 허용 도구 없음 | `general_knowledge` | `out_of_scope`(원래 요구) | `answered` · `general_knowledge` |
| 도구 장애 | 없음 | 없음 | `failed`(지금과 같음) |

## 5. 2부: 일반 지식 대체 경로

### 5.1 언제 붙이나

조회가 끝난 뒤(`ChatRetrieval` 결과를 본 뒤) 생성 전에, 서버가 다음을 모두 만족하는 요구에 배경 하위 요구(`-b`)를 더한다.

1. 기능이 켜져 있다(`zoop.chat.general-fallback.enabled`, 기본 `false`).
2. 원래 요구의 유형이 **Q03**이다. 아래 유형에는 붙이지 않는다.
   - Q01: ZOOP 고유 규칙은 승인 문서로만 답한다(거버넌스 15.1). 일반 LLM이 서비스 규칙을 만들면 안 된다.
   - Q04~Q08: 답이 ZOOP 내부 데이터(지도 관계, 기간 비교, 브리핑, 내 종목, 선정 근거) 그 자체다. 일반 배경이 그 답처럼 읽히면 안 된다.
3. 조회가 **성공했고 잘리지 않았으며**, 도구 결과가 넘긴 evidence ID가 0개다(`noneFound`, 또는 항목은 있지만 evidence 없음).
   - 도구 실패는 지금처럼 실행 전체 `failed`다.
   - `truncated` 결과는 근거가 더 있을 수 있으므로 붙이지 않는다(`results_truncated` 그대로).
4. 원래 요구가 의존 단계(`dependsOn`)가 아니다. 선행 조건 미충족(`precondition_unmet`)이나 체크포인트 결과에는 붙이지 않는다.
5. 회원이 근거를 골라 좁힌 실행(`evidenceScope` 있음)이 아니다. 고른 근거에 대해 물은 질문에 일반 설명을 붙이면 질문을 벗어난다.
6. 같은 요구에 개념 하위 요구(1부)가 이미 없다. 있으면 그것으로 충분하다.
7. 웹 검색 대체 경로가 켜져 있으면 웹 검색이 먼저 돈다. 웹 결과가 있으면 배경을 붙이지 않고, 웹 검색도 아무것도 찾지 못했을 때만 붙인다.

생성 뒤에 근거 부족으로 판정된 요구(Luna가 `insufficientRequirementIds`에 넣거나 Jev가 hold한 요구)에는 붙이지 않는다. 생성은 실행당 1회이고 다시 생성하지 않기 때문이다(설계 요약 7장).

### 5.2 결과 예

질문: "삼성전자 최근 실적 어때?"(공개 근거 없음)

- 구간: `general_knowledge`. 서버 고정 안내("일반 개념 설명입니다. 최신 기업·시장 사실은 별도 조회가 필요합니다.") 뒤에, 반도체 기업 실적을 볼 때 보는 지표와 일반적인 업황 구조를 설명한다. 기업 이름, 수치, 시점 표현은 쓰지 않는다.
- 원래 요구:
  - 찾은 것이 없으면(`noneFound`) "조회 범위에서 찾지 못했어요" 근거 구간이 남는다.
  - 항목은 있지만 근거가 없으면 `evidence_insufficient` limitation이 남는다.
- outcome: `answered`, answerBasis: `general_knowledge` 또는 `mixed`.

Luna가 배경으로 쓸 내용이 없다고 판단하면 배경 하위 요구를 `insufficientRequirementIds`에 넣는다. 그러면 결과는 지금과 같다.

### 5.3 outcome 규칙 개정

지금 규칙(설계 요약 7장): "답한 요구가 없으면 `guidance` 또는 `insufficient_evidence`."

개정안: 회원이 요구한 모든 요구가 limitation이고 **서버 하위 요구의 일반 지식 구간만** 남은 경우도 `answered`로 둔다. answerBasis는 `general_knowledge`이고, limitation 목록이 무엇을 답하지 못했는지 알려 준다.

- 근거: 공개 계약상 `insufficient_evidence`는 본문 구간을 가질 수 없다(`ChatResult.sections`: "answered가 아니면 빈 배열"). 배경 설명을 보여 주려면 `answered`여야 한다.
- 계약 문구와 맞는다: `ChatResult.limitations`는 "모든 필수 요구는 본문에서 답했거나 이 배열의 항목 중 정확히 하나에 속한다"이므로, 필수 요구가 모두 limitation인 `answered`도 허용된다. OpenAPI 문구를 고칠 필요는 없다.
- 화면: D-AI-02 답변 카드가 이미 `general_knowledge` 배지와 limitation 목록을 그린다(`ChatJobCard`). 새 화면 상태는 없다.
- 반대 의견: "근거 부족인데 `answered`"가 운영 통계에서 근거 부족 비율을 가린다. 그래서 route 요약에 `fallback=background`를 남겨 평가·대시보드에서 따로 센다(8장).

## 6. 시간과 비용

- **추가 모델 호출은 없다.** 2장 표처럼 이 경우들은 이미 Luna 생성과 Jev 검증을 한 번씩 부른다. 하위 요구는 같은 생성 호출의 branch가 하나 늘어나는 것뿐이다.
  - 예외: 1부에서 원래 요구가 `out_of_scope`라 지금은 모델 호출 없이 끝나던 실행. 개념 하위 요구가 생기면 생성 1회와 검증 1회를 부른다. 순수 Q02 질문과 같은 비용이다.
- 늘어나는 것: Luna 입력·출력 토큰(구간 하나), Jev 검증 대상 구간 하나.
- 시간 상한(`StageLimits`)과 `deadline_guard` 조건은 바꾸지 않는다. 조회 단계도 늘지 않는다.

## 7. 바뀌는 곳

| 영역 | 변경 | 1부 | 2부 |
| --- | --- | :---: | :---: |
| `ChatPlan.Planned` | 하위 요구 출처(`origin`, `parent`) 필드 | ○ | ○ |
| `ChatPlanner.serve` | 개념 하위 요구 생성(4.1) | ○ | |
| `OrchestratedChatEngine` | 조회 뒤 배경 하위 요구 추가(5.1), 하위 요구 구간 실패 시 구간만 제외(3.1), route 기록 | ○ | ○ |
| `ChatAnswerCheck` | `general_names` 검사, 하위 요구 구간 실패를 구간 단위로 돌려줌 | ○ | ○ |
| `ChatResults` / outcome | 5.3 규칙(하위 요구 구간만 남아도 `answered`) | ○ | ○ |
| 설정 | `zoop.chat.general-fallback.enabled`(기본 `false`) | | ○ |
| `ai/worker` `chat_luna.py` | 프롬프트 두 문장(3.2), `PROMPT_REVISION` 올림, replay fixture 갱신 | ○ | ○ |
| 공개 OpenAPI, 워커 계약, 웹 | 변경 없음 | | |
| 문서 | 설계 요약 5·7·8장, 구현 계획, 거버넌스(2부만) | ○ | ○ |

1부는 현재 정책 안이라 먼저 구현할 수 있다. 2부는 거버넌스 개정(9장)이 승인된 뒤 기능 플래그를 켠다.

## 8. 시험

모두 단위 시험과 replay로 한다. 유료 모델 호출과 실제 데이터는 쓰지 않는다.

- `ChatPlannerTest`
  - Q02+Q03 요구 하나 → 원래 TOOLS 요구와 `-c` GENERAL 하위 요구
  - Q02만 분류됐지만 기업을 지목함 → 같음
  - 사실 쪽 도구 없음 → `out_of_scope` 원래 요구 + `-c` 하위 요구
  - 투자 판단 요구 → 하위 요구 없음
  - ID가 30자를 넘거나 충돌함 → 하위 요구 없음
- `OrchestratedChatEngineTest`
  - 4.2 표의 다섯 행 각각
  - 2부 조건 1~7을 하나씩 어긴 경우 배경 하위 요구가 생기지 않음
  - 기능 플래그가 꺼져 있으면 지금과 같은 결과
  - 하위 요구 구간이 최신 사실 표지나 대상 이름에 걸리면 그 구간만 빠지고 실행은 `answered` 또는 `insufficient_evidence`
  - 원래 요구 구간이 같은 검사에 걸리면 지금처럼 `validation_failed`
  - 하위 요구 구간에 투자 권유 문구가 있으면 `validation_failed`
- `ChatAnswerCheckTest`: `general_names`가 company·issue label과 카탈로그 이름을 잡고, 대상과 무관한 일반 명사는 통과시킴
- `ai/worker` `test_chat_stages.py`: 새 프롬프트 개정의 replay fixture
- 평가 세트(구현 계획 우선순위 5): 질문별로 `fallback` 종류와 하위 요구 구간이 빠진 비율을 기록한다. 실제 데이터가 오면 근거 부족 비율을 대체 경로 전후로 비교한다.

## 9. 거버넌스 개정안(2부, 팀 승인 필요)

v0.10 후보로 아래를 제안한다. 승인 전에는 정책 본문을 바꾸지 않는다.

- 6.1 또는 15.1에 추가: "Q03 요구의 내부 조회가 성공했지만 인용할 근거가 없을 때, 서버는 특정 기업·사건의 사실을 포함하지 않는 일반 배경 설명을 `general_knowledge` 구간으로 덧붙일 수 있다. 이 구간은 Q02와 같은 표시·검사 기준을 따르고, 대상 기업·사건의 이름을 쓰지 않으며, 원래 요구의 근거 부족 표시를 대신하지 않는다."
- 설계 요약 7장의 outcome 규칙을 5.3대로 바꾼다.
- 바꾸지 않는 것: "Q02는 최신 사실을 대신하지 않는다", "장애를 근거 부족이나 성공 결과로 바꾸지 않는다", 투자 판단 gate.

## 10. 결정이 필요한 것

| ID | 결정 | 권장 |
| --- | --- | --- |
| P1 | 1부(A안)를 기능 플래그 없이 바로 켤지 | 플래그 없이 켬. 현재 정책 안의 Q02 답변이고 공개 계약이 같다 |
| P2 | 2부를 도입할지와 거버넌스 개정안(9장) | 팀 검토 후 승인. 승인 전에는 플래그 기본 꺼짐 |
| P3 | 하위 요구 구간만 남은 결과의 outcome(5.3) | `answered` + limitation. 통계는 route의 `fallback`으로 분리 |
| P4 | 하위 요구 구간 검사 실패 시 구간만 뺄지(3.1) | 구간만 뺌. 투자 권유와 Jev `prohibitedAdvice=yes`는 실행 전체 실패 유지 |
| P5 | 2부 적용 유형 | Q03만. 데이터가 오고 평가한 뒤 넓힐지 다시 정함 |

## 11. 범위 밖(별도 작업)

- 사건(issue)을 지목한 질문의 `issue.read` 기본 조회. 기업 지목 때의 `company.read` 기본 조회(`ChatPlanner.java:158-167`)와 같은 규칙으로 따로 낸다.
- 분리된 Luna `coverage-verifier`와 보충 라운드. 웹 검색 설계가 보충 라운드를 쓰고, 이 설계는 보충 라운드 없이 동작한다.
