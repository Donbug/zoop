# AI 챗봇 화면 상태 계약

기준 화면: `D-AI-01`, `D-AI-01b`, `D-AI-02`, `D-AI-02b`

기준 API: [`docs/api/openapi.yaml`](../api/openapi.yaml)의 `createConversation`, `getConversation`, `getCurrentConversation`, `submitQuestion`, `getQuestionJob`, `retryQuestionJob`, `cancelQuestionJob`

상세 처리 정책: [`ZOOP AI 거버넌스 정책 v0.8`](../ZOOP_AI_거버넌스_정책_v0.1.md), [`AI 챗봇 설계 요약`](../design/ai-chatbot-design-summary.md)

이 문서는 네 정적 와이어프레임이 증명하지 않는 로딩·오류·빈 상태·권한·복구 동작을 구현 계약으로 보완한다. 새 시각 디자인을 임의로 만들기보다 같은 드로어 안의 상태 변형으로 먼저 구현한다. 별도 화면 ID가 필요한 수준으로 구조가 바뀌면 manifest와 Figma 화면을 함께 갱신한다.

## 1. 공통 원칙

- 챗봇은 회원 전용이다. 비회원은 질문 본문·선택 대상을 서버에 전송하지 않고 로그인 안내를 표시한다.
- 질문 접수 시 화면 선택 문맥을 `contextIds`, `evidenceIds`, `period`, `asOf`, `graphVersion`으로 전송한다. 질문에 명시된 대상·기간이 화면 문맥보다 우선한다.
- 생성 중인 미검증 본문은 스트리밍하지 않는다. `completed`이며 저장된 `result`만 사용자 답변으로 표시한다.
- 같은 대화의 활성 작업은 하나다. 전송 버튼은 접수 성공 뒤 비활성화하고 중복 전송으로 새 job을 만들지 않는다.
- `PARTIAL` 상태를 만들지 않는다. 필요한 범위가 예산을 넘거나 서로 다른 스냅샷을 동시에 요구하면 `clarification`을 보여준다. 조회 결과로 대상이 정해지는 질문(예: 오늘 뉴스가 있는 내 종목이 셋 이상)은 서버가 실제 조회된 대상으로 선택지를 만들어 답변 생성 전에 되묻는다. UI는 두 경우를 같은 D-AI-01b로 표시한다.
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
- `422`(선택지가 원 결과에 없음 등)는 입력 오류로 표시하고 선택지를 다시 불러온다. 원 job을 찾을 수 없는 `404`는 새 질문을 안내한다.

### D-AI-02 · 작업 상태·복구

| API 상태 | UI 상태 |
| --- | --- |
| `queued` | “질문을 접수했어요”와 취소 동작 표시 |
| `running` | “자료를 확인하고 있어요” 표시. 검증 전 답변 본문은 숨김 |
| `completed` | 저장된 `ChatResult` 렌더링. polling 중단 |
| `failed` | `ChatFailure.message`와 허용된 복구 동작만 표시 |
| `cancelled` | 취소됨을 표시하고 같은 질문을 자동 재접수하지 않음 |

`failure.retry=save_only`이면 “저장 다시 시도”, `rerun`이면 “질문 다시 처리”로 구분한다. `retry=null`이면 재시도 버튼을 만들지 않고 새 질문 또는 지원 안내만 제공한다. 출력 검증 실패는 자동 재생성하지 않는다.

### D-AI-02b · 대화 조회 오류

대화 회수 GET 실패와 AI 작업 실패를 구분한다. 이 상태의 “다시 확인”은 조회만 다시 수행하며 모델을 재호출하지 않는다. 연속 실패 시 오류 코드·요청 ID를 복사할 수 있게 하고 “새 대화”를 제공하되 기존 대화를 성공한 것처럼 비우지 않는다. 401/403이면 입력 내용을 전송하지 않고 로그인 또는 접근 안내로 전환한다.

## 3. 완료 결과 표시

`ChatResult.answerBasis`는 서버가 `sections`에서 계산하며 UI가 추측하지 않는다. 결과 상단 배지는 `answerBasis`, 본문은 `sections`를 순서대로 렌더링하고 각 구간에 아래 배지를 붙인다. `answer` 문자열을 잘라 구간을 추정하지 않는다.

| answerBasis·구간 basis | 사용자 표시 |
| --- | --- |
| `general_knowledge` | “일반 개념” 배지. 고정 안내 문장은 서버가 구간 text 맨 앞에 넣었으므로 UI가 다시 붙이지 않는다. 이 구간에는 인용·출처를 연결하지 않음 |
| `zoop_documented` | “ZOOP 안내” 배지와 사용한 도움말·정책 버전 표시 |
| `evidence_grounded` | “근거 확인됨” 배지, 기준 시점과 인용·원문 열기 제공 |
| `mixed` | 결과 배지만 해당한다. 본문은 구간별 배지로 일반 설명과 근거 기반 사실의 경계를 보여 주고, 인용은 각 구간의 `evidenceIds`에만 연결한다 |
| `none` | 확인 질문·안내·근거 부족 결과. 근거 검증 배지를 표시하지 않음 |

`sources`는 목록 식별용이고 실제 인용 표시는 `citations`의 `evidenceId`, 문서 버전, quote 범위를 사용한다. `applied`의 기업·이슈·기간·graphVersion·dataAsOf는 답변 상단의 “적용 범위”에서 확인할 수 있게 한다. `limitations`가 비어 있지 않으면 본문 아래·인용 위에 “답하지 않은 부분” 영역을 두고 항목마다 `label`과 `message`를 표시한다. 투자 판단 거절, 전제 불충족, 조회 상한, 요구별 근거 부족을 본문 문장에서 추측해 만들지 않고 이 배열만 사용한다. `kind`는 아이콘·스타일 구분에만 쓰고 문구는 `message`를 그대로 쓴다.

## 4. 결과·오류별 렌더링

| 결과 | 필수 UI |
| --- | --- |
| `answered` | 답변, answerBasis, 적용 범위, 해당 시 답하지 않은 부분(`limitations`)·인용·그래프 대상, 피드백 |
| `clarification` | 확인 이유, choices 또는 자유 입력, 새 job 생성 안내 |
| `guidance` | 지원 범위와 가능한 다음 행동. action이 있을 때만 버튼 표시 |
| `insufficient_evidence` | 실제 조회 범위와 부족한 근거 설명. “사건이 없다”로 바꾸지 않음 |
| `validation_failed` | 결과 미표시, 자동 재생성 없음, 요청 ID와 허용된 복구 안내 |
| `budget_exceeded` | 부분 답변 미표시, 범위를 줄여 새 질문하도록 안내 |
| `transient` | 장애와 근거 부족을 구분하고 retry 값에 따른 동작만 제공 |
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
6. 검증 실패·예산 초과·도구 timeout은 부분 답변으로 바뀌지 않는다.
7. 로그아웃 중 늦게 도착한 응답이 이전 회원 화면이나 cache에 남지 않는다.
8. “HBM 설명과 지금 살 주식”은 `answered`로 HBM 설명을 표시하고, 매수 판단은 “답하지 않은 부분”에 `investment_advice` 항목의 `label`·`message`로 표시한다.
9. “HBM이 뭐고 SK하이닉스 최근 HBM 뉴스는?”은 `answerBasis=mixed`로 “일반 개념” 구간(고정 안내 + 설명, 인용 없음)과 “근거 확인됨” 구간(뉴스, 인용 연결)을 나눠 표시한다.
