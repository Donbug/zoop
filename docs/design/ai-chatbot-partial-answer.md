# ZOOP AI 챗봇 부분 답변 분기와 근거 부족 안내 설계

2026-10-28 목표 계약: 이 문서의 main `3eba73af` 분석과 미채택 대안은 당시 기록으로 보존한다. 최신 목표는 [Luna MCP 실행 계약](ai-chatbot-mcp-actions.md)의 `answerStatus=complete|partial|guidance`와 `notices[]`다. 보조 웹 검색의 timeout·unavailable·0건만으로 전체 job을 실패시키지 않으며, 검증된 답을 유지하고 웹 장애 notice와 실제 미충족 요구 limitation을 구분한다. 인증·권한·grant·스키마·출력 검증 실패는 이 예외에 포함하지 않는다.

이 문서에서 “PARTIAL 미지원”, “도구 실패는 전체 failed”, “독립 coverage-verifier”라고 적힌 부분은 현행 코드 또는 과거 설계 설명이며 v0.11 목표로 사용하지 않는다. 구현 전까지 공개 API에 새 필드를 먼저 추가하지 않는다.

문서 상태: 1부 구현됨 · 2부(일반 지식 대체 경로) 검토 후 미채택 · 근거 부족 안내 개선(12장) 구현됨 — 2026-10-26, 브랜치 `feat/chat-partial-answer-fallback`

기준일: 2026년 10월 26일 / 기준 코드: main `3eba73af` / 기준 정책: [ZOOP-AIG-001 v0.9](../ZOOP_AI_거버넌스_정책.md) / 설계 요약: [AI 챗봇 설계 요약](ai-chatbot-design-summary.md)

화면 추적: `D-AI-01`, `D-AI-02`

## 1. 목적

근거가 일부만 있는 질문에서 답변 전체가 "근거 부족"으로 끝나는 일을 줄인다. 원칙은 바꾸지 않는다.

- 기업·사건·시장의 **사실은 근거가 있을 때만** 말한다.
- 근거 없는 설명은 `general_knowledge` 구간에만 쓰고, 화면에서 근거 있는 구간과 구분한다.
- 도구 장애·timeout은 지금처럼 `failed`다. 일반 지식 답변으로 덮지 않는다.

처음에는 두 부분으로 나눴고, 2부는 검토 뒤 채택하지 않았다. 대신 근거 부족 안내를 고쳤다(12장).

| 부분 | 내용 | 정책 |
| --- | --- | --- |
| 1부: 부분 답변 분기(A안) | 한 요구 안에 개념(Q02)과 사실(Q03 등)이 섞이면 서버가 개념 하위 요구를 따로 만든다 | 현재 정책 안. Q02 개념 답변은 이미 허용된다 |
| 2부: 일반 지식 대체 경로 (**미채택**) | Q03 요구가 조회에 성공했지만 근거가 0개면, 서버가 일반 배경 하위 요구를 붙인다. 사실 부분은 계속 근거 부족으로 표시한다 | 동문서답 위험으로 채택하지 않음(5장 머리말) |
| 근거 부족 안내 개선 | 답할 것이 없을 때 서버 문장으로 원인과 다음에 해 볼 일을 알리고, 실제로 확인한 대상을 적용 범위에 보인다 | 현재 정책 안. 모델 호출 없음(12장) |

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
  - 워커 계약 `Branch.label`은 4,000자(code point) 이하다. 접미사를 붙여 넘치면 원래 라벨이 아니라 **하위 요구 라벨의 앞부분만** code point 단위로 잘라 접미사 자리를 만든다(`ChatPlan.Planned.MAX_LABEL`). 원래 요구는 그대로 둔다.
- 공개 `ChatResult.sections`에는 요구 ID가 나가지 않는다(`ChatResults.answered`). 그래서 **공개 OpenAPI는 바뀌지 않는다.** limitation 종류도 기존 것만 쓴다.
- 워커 계약 `zoop-ai-chat-1`도 바뀌지 않는다. 하위 요구는 기존 `general=true` branch로 간다.
- route 요약(`chat_jobs.route`)의 요구 항목에 `origin`(`router` / `concept` / `background`)과 `parent`를 남겨 감사할 수 있게 한다.
- 상한:
  - 하위 요구는 원래 요구마다 최대 1개다. 명시 요구 상한 6개(`MAX_REQUIREMENTS`)에는 세지 않는다.
  - 생성 단계는 branch를 최대 6개 받는다(워커 계약 `zoop-ai-chat-1`의 `branches` 상한, `ChatPlanner.MAX_BRANCHES`). 그래서 limitation이 아닌 라우터 요구와 하위 요구를 합쳐 6개가 될 때까지만, 앞 요구부터 하위 요구를 만든다. 남는 자리가 없으면 만들지 않는다. 2부의 배경 하위 요구는 개념 하위 요구 뒤에 같은 자리를 나눠 쓴다.

### 3.1 하위 요구 구간의 추가 검사

`general_knowledge` 구간의 기존 검사(`general_section`: 인용 없음, 순수 일반 요구만, 금액·비율·연도·날짜·"최근" 같은 최신 사실 표지 금지)와 고정 안내 문장, Jev `prohibitedAdvice` 판정은 그대로 적용한다. 하위 요구 구간에는 다음을 더한다.

- **대상 이름 금지(새 검사 `general_names`):** 하위 요구 구간에는 원래 요구가 지목한 기업·사건의 표시 이름이 들어가면 안 된다.
  - 이름의 출처는 원래 요구의 도구 결과 `items`(company·issue)의 label이다. 띄어쓰기는 무시하고 비교한다.
  - 알려진 빈틈(1부 구현): 원래 요구가 limitation(`out_of_scope` 등)이라 조회를 하지 않았으면 막을 이름이 없다. 이 경우는 프롬프트 규칙(3.2)과 최신 사실 표지 검사에만 기댄다. 카탈로그 이름까지 막으려면 엔진에 기업 이름 조회를 연결해야 한다.
  - 숫자가 없는 특정 기업 사실(예: "OO는 HBM을 주로 △△에 공급한다")은 최신 사실 표지 검사로는 걸러지지 않는다. 그래서 이름 자체를 막는다.
- **실패 처리:** 하위 요구 구간이 `general_section`이나 `general_names`에 걸리면, 실행 전체를 `validation_failed`로 끝내지 않고 **그 구간만 뺀다.** 빠진 하위 요구는 limitation을 만들지 않고, route 요약에 `droppedGeneral`로 남긴다.
  - 하위 요구는 회원이 직접 요구한 것이 아니라 서버가 덧붙인 보조 설명이기 때문이다. 원래 요구 구간의 검사 실패는 지금처럼 실행 전체 실패다.
  - 이름 검사와 구간 삭제 조건은 따로 본다. 하위 요구를 하나라도 맡은 일반 구간은 그 부모의 이름을 검사한다. 하위 요구만 맡은 구간이 걸리면 구간만 뺀다. 라우터 요구(예: 순수 Q02 `r2`)를 함께 맡은 구간(`["r1-c","r2"]`)이 걸리면 조용히 빼지 않고 `validation_failed`로 끝낸다. 빼면 회원이 직접 물은 `r2`까지 사라지기 때문이다.
  - 투자 권유 문구(`investment_wording`)와 Jev `prohibitedAdvice=yes`는 하위 요구 구간이어도 지금처럼 실행 전체 실패다.
- **Jev hold:** 하위 요구 구간이 hold되면 기존 규칙대로 그 구간만 빠진다. `explicit=false`라 limitation은 생기지 않는다.

### 3.2 Luna 프롬프트

계약은 그대로 두고 시스템 프롬프트에 문장을 더한다. 프롬프트 개정이므로 `PROMPT_REVISION`을 올린다. authored replay는 프롬프트 문장에 묶인 고정 fixture가 없어 갱신할 fixture가 없다.

- 1부(구현됨, `zoop-chat-answer-2026-10-26-1`): "label이 '— 개념 설명'으로 끝나는 branch는 서버가 같은 질문의 다른 요구에서 떼어 낸 개념 부분이다. 그 구간에는 기업·사건 이름을 쓰지 않고 개념만 설명하며, 쓸 내용이 없으면 insufficientRequirementIds에 넣는다."
  - 라우터가 따로 나눈 순수 개념 요구에는 이 규칙을 걸지 않는다. 지금 동작을 바꾸지 않기 위해서다.
- 2부(구현 전): "라벨이 '일반 배경'인 branch는 특정 기업·사건의 사실을 쓰지 않고, 그 질문을 이해하는 데 필요한 개념과 일반적인 구조만 설명한다. 쓸 내용이 없으면 insufficientRequirementIds에 넣는다."

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

## 5. 2부: 일반 지식 대체 경로 (미채택)

**결정(2026-10-26, 사용자): 채택하지 않는다.** 아래 5.1·5.2는 검토 기록으로 남긴다.

- 이유: "삼성전자 최근 실적 어때?"에 "반도체 기업 실적은 보통 …" 같은 일반론이 돌아오면 회원에게는 질문을 피해 가는 답(동문서답)으로 보인다. 일반론이 그 기업 이야기처럼 읽혀 오해를 부를 수도 있다.
- 이름·수치·시점 금지 검사는 틀린 사실은 막지만 질문과 상관없는 답은 막지 못한다. 모델은 쓸 내용이 없어도 무언가를 쓰려는 경향이 있다.
- 회원이 개념을 직접 물은 경우는 1부가 이미 답한다. 근거가 없는 사실 질문에는 일반론 대신, 왜 답할 수 없는지와 다음에 해 볼 일을 서버 문장으로 알린다(12장).
- 그래서 `Origin.BACKGROUND`, 기능 플래그 `zoop.chat.general-fallback.enabled`, "일반 배경" 프롬프트 문장은 만들지 않았다.

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

2부는 미채택이지만 이 규칙은 1부에 적용된다. 사실 쪽이 limitation이고 개념 하위 요구 구간만 남는 경우(4.2 표의 셋째·넷째 행)가 1부에서도 생기기 때문이다. 구현된 동작이 이 개정안과 같다.

이전 규칙(설계 요약 7장): "답한 요구가 없으면 `guidance` 또는 `insufficient_evidence`."

개정안: 회원이 요구한 모든 요구가 limitation이고 **서버 하위 요구의 일반 지식 구간만** 남은 경우도 `answered`로 둔다. answerBasis는 `general_knowledge`이고, limitation 목록이 무엇을 답하지 못했는지 알려 준다.

- 근거: 공개 계약상 `insufficient_evidence`는 본문 구간을 가질 수 없다(`ChatResult.sections`: "answered가 아니면 빈 배열"). 배경 설명을 보여 주려면 `answered`여야 한다.
- 계약 문구와 맞는다: `ChatResult.limitations`는 "모든 필수 요구는 본문에서 답했거나 이 배열의 항목 중 정확히 하나에 속한다"이므로, 필수 요구가 모두 limitation인 `answered`도 허용된다. OpenAPI 문구를 고칠 필요는 없다.
- 화면: D-AI-02 답변 카드가 이미 `general_knowledge` 배지와 limitation 목록을 그린다(`ChatJobCard`). 새 화면 상태는 없다.
- 반대 의견: "근거 부족인데 `answered`"가 운영 통계에서 근거 부족 비율을 가린다. 1부에서는 route 요약의 요구 항목 `origin=concept`과 limitation 목록으로 따로 셀 수 있다.

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
| `ai/worker` `chat_luna.py` | 프롬프트 문장(3.2), `PROMPT_REVISION` 올림 | ○ | ○ |
| 공개 OpenAPI, 워커 계약, 웹 | 변경 없음 | | |
| 문서 | 설계 요약 5·7·8장, 구현 계획, 거버넌스(2부만) | ○ | ○ |

1부는 현재 정책 안이라 기능 플래그 없이 항상 켠다(P1 결정). 2부 열은 미채택이라 구현하지 않는다. 근거 부족 안내 개선의 변경은 12장에 있다.

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
- `ChatAnswerCheckTest`: `general_names`가 company·issue label을 띄어쓰기와 무관하게 잡고, 대상과 무관한 일반 명사는 통과시킴. 라우터의 순수 개념 요구에는 이름 검사를 하지 않음. 하위 요구와 라우터 요구를 함께 맡은 구간이 이름이나 최신 사실 표지에 걸리면 빼지 않고 실패함
- `ai/worker` `test_chat_stages.py`: 새 프롬프트 개정의 replay fixture
- 평가 세트(구현 계획 우선순위 5): 질문별로 `fallback` 종류와 하위 요구 구간이 빠진 비율을 기록한다. 실제 데이터가 오면 근거 부족 비율을 대체 경로 전후로 비교한다.

## 9. 거버넌스 개정안(2부, 미채택으로 불필요)

2부를 채택하지 않아 아래 개정안은 팀에 올리지 않는다. 검토 기록으로만 남긴다. 1부와 12장은 현재 정책 안이다.

- 6.1 또는 15.1에 추가: "Q03 요구의 내부 조회가 성공했지만 인용할 근거가 없을 때, 서버는 특정 기업·사건의 사실을 포함하지 않는 일반 배경 설명을 `general_knowledge` 구간으로 덧붙일 수 있다. 이 구간은 Q02와 같은 표시·검사 기준을 따르고, 대상 기업·사건의 이름을 쓰지 않으며, 원래 요구의 근거 부족 표시를 대신하지 않는다."
- 설계 요약 7장의 outcome 규칙을 5.3대로 바꾼다.
- 바꾸지 않는 것: "Q02는 최신 사실을 대신하지 않는다", "장애를 근거 부족이나 성공 결과로 바꾸지 않는다", 투자 판단 gate.

## 10. 결정

| ID | 결정 | 권장 |
| --- | --- | --- |
| P1 | 1부(A안)를 기능 플래그 없이 바로 켤지 | **결정(2026-10-26, 사용자): 플래그 없이 켬.** 현재 정책 안의 Q02 답변이고 공개 계약이 같다 |
| P2 | 2부를 도입할지와 거버넌스 개정안(9장) | **결정(2026-10-26, 사용자): 미채택.** 동문서답 위험. 근거 부족 안내 개선(12장)으로 대신함 |
| P3 | 하위 요구 구간만 남은 결과의 outcome(5.3) | 1부에 적용해 구현: `answered` + limitation |
| P4 | 하위 요구 구간 검사 실패 시 구간만 뺄지(3.1) | 권장대로 구현: 구간만 뺌. 투자 권유와 Jev `prohibitedAdvice=yes`는 실행 전체 실패 유지 |
| P5 | 2부 적용 유형 | 해당 없음(2부 미채택) |

## 11. 당시 범위 밖(현재 v0.11에서 재설계)

- 사건(issue)을 지목한 질문의 `issue.read` 기본 조회. 기업 지목 때의 `company.read` 기본 조회(`ChatPlanner.java:158-167`)와 같은 규칙으로 따로 낸다. → 2026-10-27 별도 작업으로 구현([구현 계획](../development/ai-chatbot-implementation-plan.md) 사건 지목 결정 (5)·(6)).
- 분리된 Luna `coverage-verifier`는 채택하지 않는다. Luna Responses 실행 중 요구 추적과 서버 결정론 커버리지 검사로 대체한다.

## 12. 근거 부족 안내 개선 (구현됨)

답할 것이 없는 `insufficient_evidence` 결과와, 답한 결과 안의 `evidence_insufficient` limitation을 서버 문장으로 더 구체적으로 만든다. 모델은 이 문장을 쓰지 않으며 추가 호출도 없다. 공개 계약의 구조는 바뀌지 않는다.

### 12.1 이전 문제

- `reason`이 원인과 상관없이 한 문장이었다: "조회한 범위에서 답에 쓸 공개 근거가 부족해요. 대상이나 기간을 바꿔 다시 물어봐 주세요."
- D-AI-02 카드는 근거 부족 결과에도 "적용 범위"를 그린다(`ChatJobCard`의 `Applied`). 그런데 서버가 `applied.companies·issues`를 비워 보내 "대상: 없음"으로 보였다. 실제로는 조회한 기업이 있었다.

### 12.2 원인 (`ChatResults.InsufficientCause`)

엔진이 아는 가장 구체적인 원인을 다음 순서로 고른다. route 요약의 `reason`에 코드를 남긴다.

| 순서 | 코드 | 조건 | reason 첫 문장 |
| ---: | --- | --- | --- |
| 1 | `results_truncated` | 어떤 요구가 조회 상한에 걸림 | 조회 상한 때문에 일부 자료만 확인해 답을 단정할 수 없었어요. |
| 2 | `evidence_held` | 답하지 못한 요구 중 Jev가 hold한 것이 있음 | 근거는 찾았지만 답변 내용이 근거와 맞는지 충분히 확인하지 못해 보여 드리지 않았어요. |
| 3 | `nothing_found` | 답하지 못한 요구가 모두 조회 성공·결과 0건(`noneFound`) | 조회한 범위에서 관련된 공개 자료를 찾지 못했어요. |
| 4 | `precondition_unmet` | 앞 단계 결과가 체크포인트에 못 미침 | 앞 단계에서 찾은 대상이 질문의 조건에 맞지 않아 이어서 확인하지 못했어요. |
| 5 | `evidence_insufficient` | 그 밖(항목은 찾았지만 인용할 근거가 없음 등) | 관련 항목은 찾았지만 답에 쓸 수 있는 공개 근거가 부족했어요. |

- 서버가 떼어 낸 개념 하위 요구(1부)는 원인 판단에 넣지 않는다.

### 12.3 다음에 해 볼 일 (reason 둘째 문장)

실행의 고정 문맥과 실제로 실행한 조회의 범위만 보고 고른다.

| 조건(위가 먼저) | 문장 |
| --- | --- |
| 실행한 조회가 모두 선택한 근거로 좁혀짐(`evidenceScope` 있음) | 선택한 근거 안에서만 확인했어요. 선택을 해제하고 다시 물으면 더 넓게 찾아볼 수 있어요. |
| 원인이 `results_truncated` | 대상이나 기간을 좁혀 다시 물어봐 주세요. |
| 기간이 정해져 있음 | 기간을 넓히거나 다른 기업·사건을 지목해 다시 물어봐 주세요. |
| 그 밖 | 다른 기업이나 사건을 지목하거나, 지도에서 대상을 고른 뒤 다시 물어봐 주세요. |

- 근거를 선택했다는 사실만으로 첫 줄을 고르지 않는다. 질문이 다른 기업을 직접 지목하면 그 조회는 선택 범위를 쓰지 않는다(`TargetSource.QUESTION`, `evidenceScope=null`). 이때 선택을 해제하라는 안내는 효과가 없다. 좁힌 조회와 넓은 조회가 섞여도 첫 줄을 쓰지 않는다(`OrchestratedChatEngine.narrowed`).

### 12.4 적용 범위

`insufficient_evidence` 결과의 `applied.companies·issues`에 이번 실행의 조회가 돌려준 기업·사건을 넣는다(답한 요구가 없으므로 모든 요구의 조회 결과). `questionOverrodeContext`도 같은 기준으로 계산한다. `answered`에서는 지금처럼 답한 요구의 조회 결과만 넣는다. OpenAPI `ChatApplied` 설명에 이 뜻을 적었다.

- 근거 부족 결과는 인용이 없어 기존 응답 가드의 근거 재확인에 걸리지 않는다. 그래서 저장 결과를 돌려줄 때마다(작업·대화 조회, 최신 대화 복원 등) `ChatResponseGuard`가 `applied`의 기업·사건도 다시 확인한다. 고정한 `graphVersion`·asOf에 현재 공개 제외를 적용한 공개 그래프에서 지금 보이지 않는 대상은 응답에서 뺀다. 그래프를 읽지 못해 확인할 수 없으면 모두 뺀다(`ChatTargetAccess`, `GraphTargetAccess`). `answered` 결과에도 같은 규칙을 쓰고, 지도 이동 대상(`graphTargets`)도 같은 확인 결과로 거른다. 저장된 결과는 바꾸지 않는다.
  - 예: 두 기업 사이 경로 조회(`graph.path.read`)가 중간 사건을 돌려주고 답이 근거 부족으로 끝났다. 그 뒤 그 사건이 공개 제외되면, 대화를 복원해도 그 사건 이름은 다시 나오지 않는다.
  - 예: 사건이 실행 뒤 제외됐지만, 그 근거를 다른 공개 관계도 인용해 지금도 읽을 수 있다. 인용 검사는 통과하므로 답변은 그대로지만, 제외된 사건은 `graphTargets`에서 빠져 지도 이동 대상으로 나오지 않는다.

### 12.5 limitation 문장

`answered` 안의 `evidence_insufficient` limitation은 kind를 그대로 두고 문장만 원인별로 고른다.

- Jev hold: "이 부분은 답변 내용이 근거와 맞는지 충분히 확인하지 못해 뺐어요."
- 찾은 것 없음: "이 부분은 조회한 범위에서 관련 자료를 찾지 못했어요."
- 그 밖: 기존 문장 "이 부분은 답에 쓸 공개 근거가 부족했어요."

### 12.6 시험

- `ChatResultsTest`: 둘째 문장 선택 순서(좁힌 선택 > 상한 > 기간 > 그 밖), 모든 원인 문장이 500자 이하, limitation 문장 선택
- `OrchestratedChatEngineTest`: 항목은 찾았지만 근거 없음 → `evidence_insufficient` + 적용 범위에 SK하이닉스, 찾은 것 없음 → `nothing_found`, 좁힌 선택 → 선택 해제 안내, 모두 hold → `evidence_held`, hold된 요구 limitation 문장
