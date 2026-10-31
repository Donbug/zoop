# 챗봇 MCP 승인 소량 live latency spike

기준: `ZOOP-AIG-001 v0.11`, `docs/design/ai-chatbot-mcp-actions.md` 3.2, 화면 추적 `D-AI-02`.

이 절차는 출시 승인 자료를 만드는 운영 절차다. 스크립트를 실행할 수 있다는 사실은 모델 호출, 운영 데이터 전송 또는 기능 플래그 활성화 승인이 아니다. 실제 호출 전에 AI·백엔드·보안 담당자가 격리 환경, 합성 대상, 비용 상한, 실행 시간과 승인자를 기록해야 한다.

## 순서

1. `/mcp`를 인터넷 전체가 아니라 승인된 HTTPS ingress로 노출하고 `zoop-ai-chat probe-mcp`가 endpoint의 `401 Bearer` challenge를 확인하는지 본다.
2. `chat-agent` 목적과 실제 recipient를 가진 model-send grant, `zoop-graph` source, 별도 MCP HMAC 키를 격리 환경에 등록한다. 8-call 시나리오에는 `ZOOP_CHAT_WEB_ENABLED=true`, `ZOOP_CHAT_WEB_PROVIDER=synthetic`과 `web-search:<공급자>` source grant도 필요하다. 키·grant·질문·답변·URL은 spike evidence에 쓰지 않는다.
3. 승인된 대상 데이터로 아래 네 시나리오를 각 5회 실행한다(아래 "실행"). 같은 실행을 자동 재전송하지 않으며 provider outcome이 unknown이면 그 run은 실패 증거로 남긴다.
4. job의 `running` 시각부터 terminal DB commit 시각, 실제 tool/approval/provider 호출 수, provider usage와 추정 비용을 원장에서 추출해 `zoop-chat-live-spike-1` JSON을 만든다(아래 "Evidence 추출").
5. 보고서 gate를 실행한다. 모든 시나리오가 성공하고 각 job이 45초, 입력 24k, 최종 답변 2k(reasoning 제외)를 지켜야 한다.

질문은 [`scripts/chat_live_spike_scenarios.json`](../../scripts/chat_live_spike_scenarios.json)에 고정했다. 합성 그래프 `fixture-2026-10-08`이나 승인된 실제 데이터로 실행할 수 있고 웹은 합성 공급자를 쓴다. 8-call이 쓰는 카카오는 카탈로그에만 있어야 한다(그래프에 없어 내부 조회가 비어야 웹이 승인된다). 실제 데이터에서 이 전제가 깨지면 preflight가 알리고, 시나리오의 기업을 바꿔야 한다. 바꾼 뒤에는 `ChatLiveSpikeScenariosTest`를 돌린다.

필수 시나리오는 `tools-1-rounds-1`, `tools-4-rounds-1`, `tools-4-rounds-3`, `tools-8-rounds-3`이다. 8-call은 내부 6회와 웹 2회로 채운다. 예산과 웹 도구는 구현됐지만(2026-10-30) 이 시나리오를 실행해 확인하지는 않았다. 웹 검색은 개념만 있는 run이 아니면 앞 라운드의 승인된 내부 조회가 0건이거나 잘렸을 때만 승인되므로, 합성 대상과 질문을 그 조건에 맞춰야 한다. 호출 수는 Luna가 고르므로 정확히 8회가 된다는 보장이 없고, 완료 run은 시나리오와 정확히 같아야 한다. 실제 웹 공급자가 없어 합성 공급자로만 측정하며, 공급자가 정해지면 지연을 다시 잰다. 6회를 8회로 기록하지 않으며, 이 시나리오가 통과하거나 별도 정책 revision이 승인되기 전까지 live gate는 닫힌 상태가 맞다.

```sh
python scripts/chat_live_spike_report.py /secure/operator/chat-live-spike.json \
  --output /secure/operator/chat-live-spike-report.json
```

기본 최소 표본은 시나리오당 5회다. 성공은 exit 0과 `gate: passed`, 미달은 exit 2와 구체적인 `failures`, 형식 오류는 exit 64와 `gate: invalid`다. p50/p95는 작은 표본에서도 관측값을 만들지 않는 nearest-rank 방식이다.

## 실행

`scripts/chat_live_spike_run.py`가 환경을 점검하고 질문을 보낸다. 자격 증명은 환경 변수 `ZOOP_SPIKE_EMAIL`, `ZOOP_SPIKE_PASSWORD`로만 받고, 질문·답변·토큰을 출력하지 않는다. 회원은 초기 설정을 마쳐야 한다.

```sh
# 모델을 부르지 않는다. 그래프의 기업 전제, /mcp의 401 Bearer, 회원 로그인을 확인한다.
python scripts/chat_live_spike_run.py --base-url "$API" --origin "$WEB_ORIGIN" preflight --mcp-url "$API/mcp"

# 유료 호출이다. 승인 뒤에만 실행한다.
python scripts/chat_live_spike_run.py --base-url "$API" --origin "$WEB_ORIGIN" run \
  --base-manifest /secure/operator/chat-live-spike-base.json \
  --manifest /secure/operator/chat-live-spike-manifest.json \
  --max-runs 20 --i-approved-paid-calls
```

- `--base-manifest`는 `schemaVersion`, `candidateCommit`, `approvedBy`, `approvalRef`, `environment`, `policyVersion`, `pricing`만 담는다. `runs`는 실행기가 job마다 저장한다.
- `--max-runs`는 승인한 전체 상한이고 manifest에 이미 있는 run도 센다. 먼저 `--scenario tools-1-rounds-1 --repeat 1`처럼 한 건만 돌려 경로를 확인할 수 있다.
- 같은 manifest로 다시 실행하면 모자란 만큼만 보낸다. 실패한 job은 run으로 남고 다시 보내지 않는다.
- exit 0은 완료, 2는 점검 실패나 상한 도달, 3은 접수 여부가 불명이라 중단한 경우다. 3이면 원장을 먼저 확인하고 그대로 다시 실행하지 않는다.
- 기본 대기는 job당 120초다.

## 시나리오 재현성

`ChatMcpAgentTest`가 scripted Luna로 네 모양이 서버 승인 규칙 안에서 거부 없이 가능한지 확인한다(합성 replay, 8-call은 라운드별 4·3·1회). 이것은 규칙이 막지 않는다는 뜻이지 실제 Luna가 그렇게 고른다는 뜻이 아니다. live에서 달라질 수 있는 지점은 다음과 같다.

- **호출 수**: Luna가 대상 여러 개를 한 호출로 묶거나(한 호출에 5개까지) 호출을 줄이면 완료 run이 시나리오와 달라진다. 추출기가 exit 2로 알린다.
- **입력 예산**: 세 번째 라운드를 승인하려면 단계 입력 a, b, c가 `a + b + 3c ≤ 24k`여야 한다(다음 단계가 이번 입력만큼 더 든다고 보고 남겨 둠). 예를 들어 3k·5k·7k면 세 번째 라운드가 거부되고 run은 2라운드로 끝난다. `tools-4-rounds-3`과 `tools-8-rounds-3`은 도구 결과가 작아야 하며, 추론이 많은 실제 run에서 이 한도에 먼저 닿을 수 있다.
- **시간**: Luna 합산 35초 안에서 남은 시간이 20초 미만이면 새 도구를 승인하지 않으므로, 네 단계가 느리면 라운드가 줄어든다.

실행 전에 승인자가 정할 것: 시나리오와 다른 완료 run의 처리, 재시도를 포함한 총 run 수 상한(기본 표본 20회)이다.

## Evidence 추출

```sh
psql "$SPIKE_DB" -At -v ON_ERROR_STOP=1 -v jobs='job-a,job-b' \
  -f scripts/chat_live_spike_ledger.sql > /secure/operator/chat-live-spike-ledger.json
python scripts/chat_live_spike_extract.py /secure/operator/chat-live-spike-manifest.json \
  /secure/operator/chat-live-spike-ledger.json --output /secure/operator/chat-live-spike.json
```

SQL은 상태·시각·개수·revision만 읽는다. 질문, 결과, grant, owner token, 자유 형식 메시지는 선택하지 않는다.

manifest(`zoop-chat-live-spike-manifest-1`)는 다음 필드만 허용한다.

- `schemaVersion`, `candidateCommit`, `approvedBy`, `approvalRef`, `environment`, `policyVersion`
- `pricing`: 모델 이름별 `{inputUsdPerMTok, outputUsdPerMTok}`. 실행한 모든 모델이 있어야 한다.
- `runs`: `{jobId, scenario}` 목록

측정값은 모두 원장에서 온다.

| Evidence | 원장 |
| --- | --- |
| `startedAt`, `committedAt` | job의 시도 `startedAt`, `chat_jobs.finished_at` |
| `toolCalls` | 그 시도의 `chat_tool_calls` 중 `cancelled`가 아닌 호출(웹 포함). 완료 run은 `route_summary.approvedCalls`와 같아야 하고 `deniedCalls`는 0이어야 한다 |
| `providerCalls`, `approvalRounds` | 보낸 `chat-agent` 단계 수, 그 수 − 1 |
| `inputTokens`, `outputTokens`, `reasoningTokens` | `chat-agent` 단계 합 |
| `answerTokens` | 완료 run의 마지막 단계 출력 − reasoning, 실패 run은 0 |
| `model`, `promptVersion`, `toolRegistryVersion` | 원장 값. 여러 값이 섞이면 거부 |
| `costUsd` | 그 시도의 모든 모델 단계 토큰 × `pricing` |

`costUsd`는 청구액이 아니라 추정값이다. 원장에 cached token이 없어 입력 전체를 비캐시 가격으로 계산하므로 실제보다 크게 나온다. 완료 run은 보낸 모든 단계의 입력·출력 usage가 있어야 한다. 실패 run은 실패 증거로 남기되, usage를 보고하지 않은 단계가 있으면 비용이 하한값이며 추출기가 `costUnknownRuns`로 알린다. 실패 run이 있으면 gate는 어차피 실패하므로 낮은 비용이 통과로 이어지지 않는다.

| 종료 | 뜻 |
| --- | --- |
| 0 | evidence를 썼다. 보고서 gate의 로더가 받아들인 뒤에만 쓴다. |
| 2 | 완료 run의 호출 수나 라운드가 시나리오와 다르거나, 거부된 호출 또는 승인되고 실행되지 않은 호출이 있다(`mismatches`). 아무것도 쓰지 않으며 run을 빼거나 다른 시나리오로 바꾸지 않는다. 처리는 승인자가 정한다. |
| 64 | 입력 오류이거나 증거가 될 수 없는 run이다(미완료, 재실행, direct 경로, live 아님, 완료 run의 usage 미보고, 가격 없음). |

## Evidence 형식

root는 다음 필드만 허용한다.

- `schemaVersion`: `zoop-chat-live-spike-1`
- `candidateCommit`: 측정한 배포 후보의 소문자 40자리 Git commit
- `approvedBy`, `approvalRef`, `environment`
- `policyVersion`, `model`, `promptVersion`, `toolRegistryVersion`
- `runs`

각 run은 `runId`, `scenario`, `mode=live`, `status`, `startedAt`, `committedAt`, `toolCalls`, `approvalRounds`, `providerCalls`, `inputTokens`, `outputTokens`, `reasoningTokens`, `answerTokens`, `costUsd`, `failureCode`만 허용한다.

- 완료 run은 시나리오와 정확히 같아야 한다(`toolCalls`·`approvalRounds`, `providerCalls`는 초기 Responses 호출 1회와 각 승인 continuation의 합 `approvalRounds + 1`).
- 실패 run은 멈춘 지점까지 실제로 한 값을 적는다. 시나리오 값(`providerCalls`는 `approvalRounds + 1`)을 넘으면 형식 오류다. 실패 run은 형식 오류가 아니라 gate 실패로 집계되므로, 실패를 빼고 성공만 남기지 않는다.
- `outputTokens`는 공급자가 보고한 출력 합계(reasoning 포함), `reasoningTokens`는 그중 reasoning, `answerTokens`는 최종 단계 답변만(마지막 단계의 출력 − 그 단계의 reasoning)이다. `reasoningTokens ≤ outputTokens`, `answerTokens ≤ outputTokens − reasoningTokens`여야 한다. 2k 상한은 `answerTokens`에만 적용한다(MCP 실행 계약 3.2: reasoning은 2,000 안이라고 가정하지 않음). 답을 쓰지 못한 실패 run은 `answerTokens=0`이다. 질문, 답변, 인용문, 사용자·회원 ID, endpoint, grant, API key, 자유 형식 모델 원응답은 형식 자체가 거부한다.

보고서에는 revision과 집계만 보존한다. raw evidence의 보존 위치·기간과 접근자는 운영 승인 기록에서 정하고 저장소에는 커밋하지 않는다.
