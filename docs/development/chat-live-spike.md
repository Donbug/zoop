# 챗봇 MCP 승인 소량 live latency spike

기준: `ZOOP-AIG-001 v0.11`, `docs/design/ai-chatbot-mcp-actions.md` 3.2, 화면 추적 `D-AI-02`.

이 절차는 출시 승인 자료를 만드는 운영 절차다. 스크립트를 실행할 수 있다는 사실은 모델 호출, 운영 데이터 전송 또는 기능 플래그 활성화 승인이 아니다. 실제 호출 전에 AI·백엔드·보안 담당자가 격리 환경, 합성 대상, 비용 상한, 실행 시간과 승인자를 기록해야 한다.

## 순서

1. `/mcp`를 인터넷 전체가 아니라 승인된 HTTPS ingress로 노출하고 `zoop-ai-chat probe-mcp`가 endpoint의 `401 Bearer` challenge를 확인하는지 본다.
2. `chat-agent` 목적과 실제 recipient를 가진 model-send grant, `zoop-graph` source, 별도 MCP HMAC 키를 격리 환경에 등록한다. 키·grant·질문·답변·URL은 spike evidence에 쓰지 않는다.
3. 합성 기업·근거만 사용해 아래 네 시나리오를 각 5회 실행한다. 같은 실행을 자동 재전송하지 않으며 provider outcome이 unknown이면 그 run은 실패 증거로 남긴다.
4. job의 `running` 시각부터 terminal DB commit 시각, 실제 tool/approval/provider 호출 수, provider usage와 청구·추정 비용을 원장에서 추출해 `zoop-chat-live-spike-1` JSON을 만든다.
5. 보고서 gate를 실행한다. 모든 시나리오가 성공하고 각 job이 45초, 입력 24k, 출력 2k를 지켜야 한다.

필수 시나리오는 `tools-1-rounds-1`, `tools-4-rounds-1`, `tools-4-rounds-3`, `tools-8-rounds-3`이다. 현재 내부 도구 상한은 6이고 웹 도구가 없으므로 8-call 시나리오는 아직 통과시킬 수 없다. 이 사실을 우회해 6회를 8회로 기록하지 않는다. 웹 2회 도구와 총 8회 예산이 구현되거나, 별도 정책 revision이 승인되기 전까지 live gate는 닫힌 상태가 맞다.

```sh
python scripts/chat_live_spike_report.py /secure/operator/chat-live-spike.json \
  --output /secure/operator/chat-live-spike-report.json
```

기본 최소 표본은 시나리오당 5회다. 성공은 exit 0과 `gate: passed`, 미달은 exit 2와 구체적인 `failures`, 형식 오류는 exit 64와 `gate: invalid`다. p50/p95는 작은 표본에서도 관측값을 만들지 않는 nearest-rank 방식이다.

## Evidence 형식

root는 다음 필드만 허용한다.

- `schemaVersion`: `zoop-chat-live-spike-1`
- `candidateCommit`: 측정한 배포 후보의 소문자 40자리 Git commit
- `approvedBy`, `approvalRef`, `environment`
- `policyVersion`, `model`, `promptVersion`, `toolRegistryVersion`
- `runs`

각 run은 `runId`, `scenario`, `mode=live`, `status`, `startedAt`, `committedAt`, `toolCalls`, `approvalRounds`, `providerCalls`, `inputTokens`, `outputTokens`, `reasoningTokens`, `costUsd`, `failureCode`만 허용한다. 완료 run의 `providerCalls`는 초기 Responses 호출 1회와 각 승인 continuation의 합(`approvalRounds + 1`)이어야 한다. 질문, 답변, 인용문, 사용자·회원 ID, endpoint, grant, API key, 자유 형식 모델 원응답은 형식 자체가 거부한다.

보고서에는 revision과 집계만 보존한다. raw evidence의 보존 위치·기간과 접근자는 운영 승인 기록에서 정하고 저장소에는 커밋하지 않는다.
