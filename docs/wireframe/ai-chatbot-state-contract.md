# AI 챗봇 화면 상태 계약

기준 화면: `D-AI-01`, `D-AI-01b`, `D-AI-02`, `D-AI-02b`

기준 API: [`docs/api/openapi.yaml`](../api/openapi.yaml)의 `createConversation`, `getConversation`, `getCurrentConversation`, `submitQuestion`, `getQuestionJob`, `retryQuestionJob`, `cancelQuestionJob`, `listConversations`, `deleteConversation`

상세 처리 정책: [`ZOOP AI 거버넌스 정책 v0.11`](../ZOOP_AI_거버넌스_정책.md), [`AI 챗봇 설계 요약`](../design/ai-chatbot-design-summary.md)

이 문서는 네 정적 와이어프레임이 증명하지 않는 로딩·오류·빈 상태·권한·복구 동작을 구현 계약으로 보완한다. 새 시각 디자인을 임의로 만들기보다 같은 드로어 안의 상태 변형으로 먼저 구현한다. 별도 화면 ID가 필요한 수준으로 구조가 바뀌면 manifest와 Figma 화면을 함께 갱신한다.

## 1. 공통 원칙

### 2026-10-28 목표 계약 (단계적 구현)

- 새 질문은 기존 대화에서도 재분류한다. 세션 고정 Q 유형을 강제하지 않는다. Q02/Q03/Q04 복합 요구는 한 답변으로 제공하며 별도 질문으로 강제하지 않는다.
- Q01은 웹 검색을 사용하지 않는다. Q02는 웹을 기본 보조로 시도하고 Q03~Q08은 내부 근거가 부족할 때 마지막 수단으로 사용한다. 웹 결과는 ‘외부 웹 보도 · ZOOP 내부 근거 아님’과 검색 시점을 표시하고 일반 지식·내부 evidence와 구분한다.
- `answerStatus`·`notices[]`는 2026-10-30 DTO·OpenAPI·클라이언트·저장·guard에 함께 구현됐다. `web_reported`·`web_result`·`uiActions[]`는 아직 현재 API 지원 필드가 아니다. 현재 `action=set_watchlist`를 임의 동작 실행기로 바꾸지 않는다.
- 보조 웹 검색 timeout·unavailable은 검증된 답을 숨기지 않는다. `notices.code=web_unavailable`을 표시하고, 외부 확인이 남은 요구만 “답하지 않은 부분”에 둔다. 웹 실패를 “관련 자료 없음”으로 바꾸지 않는다.
- direct 경로에서 독립 요구 일부의 내부 조회만 timeout·unavailable이면 그 요구는 `tool_unavailable` limitation으로 남기고 검증된 나머지 요구를 `partial`로 돌려준다. 답한 요구가 하나도 없거나 어댑터·권한·스키마 오류이면 job 실패를 부분 답변으로 숨기지 않는다.
- 기업 상세·간선/경로 포커스·근거·브리핑 동작은 서버가 실제 조회 결과로 만든 typed 버튼으로 제공한다. 클릭 시 실행하고 자동 이동하지 않으며 polling·복구·재열람으로 재실행하지 않는다.
- 클릭 시 권한·철회·버전 불일치를 확인한다. 열 수 없으면 안내하고 다른 간선으로 치환하지 않는다. 웹 보도만으로 내부 지도 간선 버튼을 만들지 않는다.
- 화면 ID·대상 계약은 [MCP·화면 동작 계약](../design/ai-chatbot-mcp-actions.md)을 따른다. 이번 개정은 Figma·화면 구현 수정이 아니다. 구현 시 개별 와이어프레임을 확인한다.

### 기존 공통 동작

- 챗봇은 회원 전용이다. 비회원은 질문 본문·선택 대상을 서버에 전송하지 않고 로그인 안내를 표시한다.
- 질문 접수 시 화면 선택 문맥을 `contextIds`, `evidenceIds`, `period`, `asOf`, `graphVersion`으로 전송한다. 질문에 명시된 대상·기간이 화면 문맥보다 우선한다.
- 생성 중인 미검증 본문은 스트리밍하지 않는다. `completed`이며 저장된 `result`만 사용자 답변으로 표시한다.
- 같은 대화의 활성 작업은 하나다. 전송 버튼은 접수 성공 뒤 비활성화하고 중복 전송으로 새 job을 만들지 않는다.
- 현행 API에는 `PARTIAL` job 상태나 별도 outcome이 없다. 검증된 부분 답변은 `answered.answerStatus=partial`로 표현한다. 실행 전에 범위를 줄일 수 있는 fan-out·스냅샷 문제는 계속 `clarification`으로 처리한다.
- 브라우저 새로고침이나 재접속은 `getCurrentConversation`과 `getQuestionJob`으로 저장된 상태를 회수한다. 회수는 새 모델 호출이 아니다.

## 2. 화면별 상태

### D-AI-01 · 질문 작성·대상 연결

| 상태 | 표시·동작 |
| --- | --- |
| 대상 있음 | 선택 대상의 종류·이름·기준 시점·근거 수를 표시하고 체크 해제할 수 있다. |
| 대상 없음 | 일반 개념 질문은 허용하되 지시어 질문은 서버에서 `clarification`될 수 있음을 짧게 안내한다. 대상을 억지로 필수 처리하지 않는다. |
| 입력 | 1~4,000자. 공백뿐인 입력은 전송하지 않는다. Enter 전송·Shift+Enter 줄바꿈을 제공한다. |
| 접수 중 | 동일 jobId와 멱등성 키로 한 번만 제출하고 전송 버튼에 진행 상태를 표시한다. |
| 세션 busy | 기존 활성 job을 회수하여 보여주고 새 질문을 별도로 생성하지 않는다. |

### D-AI-01b · 확인 질문

`outcome=clarification`을 일반 답변처럼 보이지 않게 표시한다. 원 질문과 확인 이유를 유지하고 `ChatChoice.kind`에 따라 기업·기간·범위·스냅샷 선택지를 버튼으로 제공한다. 선택지가 없으면 자유 입력을 허용한다.

답은 기존 job의 결과를 수정하지 않고 새 jobId로 접수한다.

| 답 방식 | `ChatJobRequest` |
| --- | --- |
| 선택지 버튼 | `question`=선택지 `label`, `resolves={jobId: 원 job, choiceId: 선택지 id}`, `context` 생략 |
| 자유 입력 | `question`=입력한 답, `resolves={jobId: 원 job, choiceId: null}`, `context` 생략 |

- `choiceId`는 받은 값을 그대로 돌려보낸다. 기업 ID 등으로 해석해 `contextIds`·`period`·`graphVersion`에 옮기지 않는다.
- 원 질문의 선택 문맥은 서버가 원 job에서 이어받으므로 다시 보내지 않는다. 화면에서 다른 대상을 고른 뒤 묻는 것은 `resolves` 없는 새 질문이다.
- 대화 목록에서 `ChatJob.resolves`가 있는 job은 원 확인 질문 아래에 이어진 답으로 표시한다. 답한 뒤에도 원 확인 질문의 선택지는 다시 고를 수 있으며 매번 새 job이다.
- 확인 질문 사슬은 최대 2회다. 두 번째 확인 질문에 답한 job은 다시 모호해도 확인 질문 대신 `guidance`로 끝나며, UI는 4절의 `guidance` 렌더링을 그대로 쓴다. UI가 깊이를 세거나 선택지를 숨기지 않는다.
- `422`(선택지가 원 결과에 없음 등)는 입력 오류로 표시하고 선택지를 다시 불러온다. 원 job을 찾을 수 없는 `404`는 새 질문을 안내한다.

### D-AI-02 · 작업 상태·복구

| API 상태 | UI 상태 |
| --- | --- |
| `queued` | “질문을 접수했어요”와 취소 동작 표시 |
| `running` | `phase`에 따라 진행 단계 표시(`planning` 질문 이해 → `retrieving` 자료 확인 → `writing` 답변 작성 → `verifying` 검증). 자료 조회가 없는 경로는 `retrieving`을 건너뛴다. 검증 전 답변 본문은 숨김 |
| `completed` | 저장된 `ChatResult` 렌더링. polling 중단 |
| `failed` | `ChatFailure.message`와 허용된 복구 동작만 표시 |
| `cancelled` | 취소됨을 표시하고 같은 질문을 자동 재접수하지 않음 |

`failure.retry=save_only`이면 “저장 다시 시도”, `rerun`이면 “질문 다시 처리”로 구분한다. `retry=null`이면 재시도 버튼을 만들지 않고 새 질문 또는 지원 안내만 제공한다. 작업당 실행이 3회에 도달하면 서버가 `retry=null`을 내려주므로 UI가 횟수를 따로 세지 않는다. 출력 검증 실패는 자동 재생성하지 않는다.

진행 단계는 `phase`만 사용하고 경과 시간으로 단계를 추정하지 않는다. 단계 표시는 `aria-live=polite`로 알리되 단계마다 포커스를 옮기지 않는다.

### D-AI-02 · 대화 기록 (와이어프레임 없음, 2026-10-27 임시 설계)

와이어프레임에는 대화 목록 화면이 없다(FS050은 목록·삭제를 P2로 미뤘다). 웹은 질문 창 머리글의 “대화 기록” 버튼으로 같은 드로어의 본문을 목록으로 바꾸고 “← 대화로 돌아가기”로 되돌린다. 화면 설계가 확정되면 이 절을 바꾼다.

| API 상태 | UI 상태 |
| --- | --- |
| `listConversations` 응답 전 | “대화 기록을 불러오고 있어요” |
| 실패 | “대화 기록을 불러오지 못했어요”와 “다시 시도”(목록 조회만 다시) |
| 빈 목록 | “아직 질문한 대화가 없어요”. 질문하지 않은 “새 대화”는 목록에 없다 |
| 항목 | 첫 질문(제목)·마지막 질문 시각(KST)·질문 수. 지금 대화는 `aria-current`와 “지금 대화” |
| `nextCursor` | “더 보기”로 다음 쪽을 잇는다. 커서가 만료되면 첫 쪽부터 다시 읽는다 |

- 항목을 고르면 `getConversation`으로 그 대화를 연다(모델 호출 없음). “새 대화”와 같은 조건(보내는 중·확인하지 못한 질문이 없을 때)에서만 바꾸고, 바꾼 뒤에는 이전 대화의 늦은 응답을 반영하지 않는다. 열지 못하면 지금 대화를 그대로 두고 안내한다.
- 삭제는 `deleteEnabled`가 참일 때만 보인다. 항목의 “삭제” → 확인(“되돌릴 수 없어요”) → `deleteConversation`. 처리 중인 질문이 있으면(`JOB_IN_PROGRESS`) 지우지 않고 취소한 뒤 삭제하라고 안내한다. 지금 대화를 지우면 질문 창을 빈 상태로 바꾸고 다음 질문이 새 대화를 만든다.
- `deleteEnabled`가 거짓이면(승인된 처리방침·약관은 개별 채팅 삭제 미제공) “대화 기록은 회원 탈퇴 시 모두 삭제돼요”만 안내한다. 개정 초안: [`docs/legal/drafts/revision-chat-deletion.md`](../legal/drafts/revision-chat-deletion.md).

### D-AI-02b · 대화 조회 오류

대화 회수 GET 실패와 AI 작업 실패를 구분한다. 이 상태의 “다시 확인”은 조회만 다시 수행하며 모델을 재호출하지 않는다. 연속 실패 시 오류 코드·요청 ID를 복사할 수 있게 하고 “새 대화”를 제공하되 기존 대화를 성공한 것처럼 비우지 않는다. 401/403이면 입력 내용을 전송하지 않고 로그인 또는 접근 안내로 전환한다.

## 3. 완료 결과 표시

`answerStatus`는 결과 배지다. `complete`는 모든 요구 처리, `partial`은 검증된 답과 미충족 limitation이 함께 있음, `guidance`는 확인·안내·근거 부족을 뜻한다. `notices`는 본문 아래의 비차단 알림으로 표시하며 limitation과 합치지 않는다. 두 필드는 서버가 정하며 UI가 본문이나 limitation 문구에서 추측하지 않는다.

서버는 결과를 돌려줄 때마다 현재 근거 접근 권한을 다시 확인한다. 인용한 자료가 철회·비공개로 바뀌었거나 확인할 수 없으면 `answer`에 고정 안내 문장만 오고 `sections`·`citations`가 비어 있으며 `answerBasis=none`이다. UI는 이를 근거 부족이나 장애로 바꿔 표시하지 않고 `answer`를 그대로 보여 주며, 예전에 받은 본문을 cache에서 되살리지 않는다. 선택 근거의 label이 '표시할 수 없는 근거'로 오면 그대로 표시한다.

`ChatResult.answerBasis`는 서버가 `sections`에서 계산하며 UI가 추측하지 않는다. 결과 상단 배지는 `answerBasis`, 본문은 `sections`를 순서대로 렌더링하고 각 구간에 아래 배지를 붙인다. `answer` 문자열을 잘라 구간을 추정하지 않는다.

| answerBasis·구간 basis | 사용자 표시 |
| --- | --- |
| `general_knowledge` | “일반 개념” 배지. 고정 안내 문장은 서버가 구간 text 맨 앞에 넣었으므로 UI가 다시 붙이지 않는다. 이 구간에는 인용·출처를 연결하지 않음 |
| `zoop_documented` | “ZOOP 안내” 배지와 사용한 도움말·정책의 제목·버전 표시(`citations`의 `sourceKind=zoop_doc` 항목의 `articleTitle`·`docVersion`) |
| `evidence_grounded` | “근거 확인됨” 배지, 기준 시점과 인용·원문 열기 제공 |
| `mixed` | 결과 배지만 해당한다. 본문은 구간별 배지로 일반 설명과 근거 기반 사실의 경계를 보여 주고, 인용은 각 구간의 `evidenceIds`에만 연결한다 |
| `none` | 확인 질문·안내·근거 부족 결과. 근거 검증 배지를 표시하지 않음 |

`sources`는 목록 식별용이고 실제 인용 표시는 `citations`의 `evidenceId`, 문서 버전, quote 범위를 사용한다. `sourceKind=article`이면 원문 기사·공시 열기를, `zoop_doc`이면 해당 도움말·정책 문서 열기를 제공한다. `applied`의 기업·이슈·기간·graphVersion·dataAsOf는 답변 상단의 “적용 범위”에서 확인할 수 있게 한다. `limitations`가 비어 있지 않으면 본문 아래·인용 위에 “답하지 않은 부분” 영역을 두고 항목마다 `label`과 `message`를 표시한다. 투자 판단 거절, 전제 불충족, 조회 상한, 요구별 근거 부족을 본문 문장에서 추측해 만들지 않고 이 배열만 사용한다. `kind`는 아이콘·스타일 구분에만 쓰고 문구는 `message`를 그대로 쓴다.

## 4. 결과·오류별 렌더링

| 결과 | 필수 UI |
| --- | --- |
| `answered` | 답변, answerBasis, 목표 answerStatus, 적용 범위, 해당 시 notices·답하지 않은 부분(`limitations`)·인용·그래프 대상, 피드백 |
| `clarification` | 확인 이유, choices 또는 자유 입력, 새 job 생성 안내 |
| `guidance` | 지원 범위와 가능한 다음 행동. action이 있을 때만 버튼 표시 |
| `insufficient_evidence` | 실제 조회 범위와 부족한 근거 설명. “사건이 없다”로 바꾸지 않음 |
| `validation_failed` | 결과 미표시, 자동 재생성 없음, 요청 ID와 허용된 복구 안내 |
| `budget_exceeded` | 부분 답변 미표시, 재시도 버튼 없음. `reason`이 `context_too_large`면 대상·기간을 줄이도록, `output_limit`이면 질문을 나누도록 안내하고 새 질문을 유도 |
| `transient` | 장애와 근거 부족을 구분하고 retry 값에 따른 동작만 제공. direct 경로의 독립 요구 하나만 `tool_timeout`·`tool_unavailable`이고 다른 요구를 검증해 답할 수 있으면 completed/partial의 `tool_unavailable` limitation으로 표시하지만, 답한 요구가 없으면 이 실패 상태를 유지한다. `deadline_guard`·`provider_error` 등은 “일시적으로 처리하지 못했어요” 계열 문구를 쓰고 “자료 없음”으로 표현하지 않음. `response_unknown`은 재시도 버튼 없이 처리 결과를 확인하지 못했다는 안내와 요청 ID를 보여 주고 새 질문을 유도 |
| `permission_denied` | 개인·원문 데이터 미표시, 로그인·권한 안내 |

## 5. 접근성·상태 보존

- 새 메시지·상태 변경은 `aria-live=polite`, 실패는 `role=alert`로 알린다.
- polling 동안 포커스를 이동하지 않고, 완료 뒤 첫 답변 제목으로 이동할 수 있는 제어를 제공한다.
- 선택 대상 제거·확인 선택·재시도 버튼은 키보드로 동작하며 아이콘만 있는 버튼에는 이름을 둔다.
- 질문 draft는 서버 결과와 분리한다. 로그아웃·회원 변경 시 대화 query cache, draft, 선택 문맥을 함께 폐기한다.
- 모바일에서는 드로어를 bottom sheet로 바꾸더라도 같은 상태·버튼·근거 정보를 숨기지 않는다.

## 6. 수용 시나리오

1. `D-AI-01`에서 선택 기업과 질문을 보내면 한 job만 생성되고 새로고침 뒤 `D-AI-02`가 같은 job을 회수한다.
2. 모호한 “그 기업은 언제?”는 `D-AI-01b`에서 기업 선택을 요구하고, 선택하면 `resolves.choiceId`를 담은 새 job을 만든다. 새 job의 `context`는 원 job과 같고 원 job은 바뀌지 않는다.
3. Q02 일반 개념만 물으면 `answerBasis=general_knowledge`와 구간 하나로 표시하고, 고정 안내 문구는 한 번만 보이며 sources/citations는 비어 있다.
4. 근거 기반 답변은 모든 인용이 공개 문서 버전과 연결되고 철회 뒤 다시 열 때 노출되지 않는다.
5. 대화 GET 503은 `D-AI-02b`로 표시되고 “다시 확인”이 새 AI 실행을 만들지 않는다.
6. 인증·권한·스키마·출력 검증 실패는 부분 답변으로 바뀌지 않는다. direct 경로에서 독립 요구 하나의 내부 조회만 timeout·unavailable이고 다른 요구를 검증해 답하면 `partial`과 `tool_unavailable` limitation을 유지하며, 모두 실패하면 `transient`다. 보조 웹 timeout만 발생하면 검증된 답과 `web_unavailable` notice를 유지한다.
7. 로그아웃 중 늦게 도착한 응답이 이전 회원 화면이나 cache에 남지 않는다.
8. “HBM 설명과 지금 살 주식”은 `answered`로 HBM 설명을 표시하고, 매수 판단은 “답하지 않은 부분”에 `investment_advice` 항목의 `label`·`message`로 표시한다.
9. “HBM이 뭐고 SK하이닉스 최근 HBM 뉴스는?”은 `answerBasis=mixed`로 “일반 개념” 구간(고정 안내 + 설명, 인용 없음)과 “근거 확인됨” 구간(뉴스, 인용 연결)을 나눠 표시한다.
10. 확인 질문에 두 번 답한 뒤에도 대상이 모호하면 세 번째 확인 질문 대신 `guidance`가 표시되고, 새 질문 입력으로 돌아간다.
