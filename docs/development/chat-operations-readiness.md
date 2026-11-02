# 챗봇 MCP 운영 readiness gate

기준: `ZOOP-AIG-001 v0.11` D04·D06·D12·D15, 화면 추적 `D-AI-02`.

이 gate는 운영 승인과 실측 증거가 같은 배포 후보에 묶였는지 확인한다. 통과 결과는 배포·외부 전송·기능 플래그 활성화 명령이 아니며, 실제 값이나 비밀을 대신 보관하지 않는다. `ZOOP_CHAT_MCP_ENABLED`, `ZOOP_CHAT_AGENT_ENABLED`, `ZOOP_CHAT_WEB_ENABLED`는 검증 시점에 모두 꺼져 있어야 한다.

## 필요한 결정

manifest의 `decisions`에는 다음 열네 항목이 정확히 있어야 한다.

| 항목 | 고정 선택 또는 허용 선택 | 확인하는 것 |
| --- | --- | --- |
| `httpsIngress` | `https-default-port-no-redirect` | 기본 HTTPS 포트, redirect 없는 MCP ingress |
| `sourceRestriction` | `private-connectivity`, `provider-ip-defense-in-depth`, `no-ip-restriction` 중 하나 | 공급자 출발지 제한 선택. IP 제한은 Bearer grant 인증을 대체하지 않음 |
| `modelSendGrants` | `chat-agent-recipient-source-grants-approved` | 실제 recipient와 출처별 model-send 권리·목적 |
| `openaiRetention` | `responses-store-true-approved` | Responses `store=true` 보유 조건과 목적 승인 |
| `privacyDisclosure` | `external-model-processing-approved` | 외부 모델 처리 고지·법적 검토 |
| `keyRotation` | `dual-key-rollover-approved` | 별도 MCP HMAC 키의 이중 키 회전 절차 |
| `incidentResponse` | `disable-rollback-owners-assigned` | 중단·롤백·재개 역할 지정 |
| `evidenceRetention` | `raw-live-evidence-retention-approved` | raw spike 증거 위치·기간·접근자 승인 |
| `webProvider` | `naver-api-hub-webkr-approved` | 운영 웹 검색 공급자 선택 |
| `webUsageRights` | `title-snippet-link-redisplay-approved` | 제목·snippet·링크의 답변 표시와 재열람 권리 |
| `webRetention` | `request-cache-and-chat-citation-retention-approved` | 짧은 요청 캐시와 저장된 채팅 인용의 보관 범위·기간 |
| `webPrivacy` | `public-query-no-member-data-approved` | 공개 검색어만 전송하고 회원·포트폴리오 데이터를 제외하는 경계 |
| `webProcessingRegion` | `provider-processing-region-approved` | 공급자 처리 지역·국가 검토 |
| `webCostControl` | `request-caps-and-billing-alerts-approved` | 회원·프로젝트 요청 상한과 공급자 과금 경보 |

각 항목은 `status=approved`, 고정 `selection`, 티켓·결정 참조(`decisionRef`), 개인 이름이 아닌 책임 역할 slug(`ownerRole`), offset을 포함한 `approvedAt`만 담는다. 참조는 `AI-42`, `RUN-1242#probe`처럼 쓰며 URL, endpoint, key, token, grant 본문을 넣지 않는다.

## preflight와 rollout

`preflight`는 승인된 후보 ingress에서 `zoop-ai-chat probe-mcp`가 redirect 없이 endpoint 자체의 `401 Bearer` challenge를 관측한 증거만 기록한다. URL 대신 설정 revision slug와 증거 참조를 쓴다.

`webPreflight`는 같은 후보에서 `naver-api-hub-webkr`로 승인된 최소 검색을 실행해 제한된 응답 계약을 관측한 별도 evidence를 참조한다. manifest에는 provider, credential revision slug, 증거 참조만 둔다. 실제 검색어·응답·endpoint·credential은 운영 manifest와 evidence 파일에 넣지 않는다. redirect를 따라간 실행, 합성 공급자 실행, 응답 계약을 확인하지 못한 실행은 통과할 수 없다.

승인된 1회 공급자 호출은 아래처럼 실행한다. credential은 환경변수로만 읽고 `--i-approved-provider-call` 없이는 네트워크를 열지 않는다. 결과 파일에는 후보 commit, 관측 시각, 응답 크기·건수와 계약 통과 여부만 남는다.

```sh
ZOOP_CHAT_WEB_NAVER_API_HUB_CLIENT_ID=... \
ZOOP_CHAT_WEB_NAVER_API_HUB_CLIENT_SECRET=... \
python scripts/chat_web_provider_preflight.py \
  --candidate-commit <40자리-commit> \
  --credential-revision naver-search-key-v1 \
  --output /secure/operator/chat-web-preflight.json \
  --i-approved-provider-call
```

`rollout`은 검증 당시 세 기능 플래그가 모두 `false`였음을 기록하고, 이후 별도의 활성화 변경 참조와 rollback 책임 역할을 요구한다. gate가 통과해도 스크립트가 환경변수나 배포 상태를 바꾸지는 않는다.

운영 manifest와 [live spike evidence](chat-live-spike.md)는 같은 소문자 40자리 `candidateCommit`이어야 한다. readiness 명령은 live evidence를 다시 엄격하게 읽어 네 필수 시나리오, 표본 수, 45초·입력 24k·최종 답변 2k(`answerTokens`, reasoning 제외), 비용을 재검증한다.

```sh
python scripts/chat_operations_readiness.py \
  /secure/operator/chat-readiness.json \
  /secure/operator/chat-live-spike.json \
  /secure/operator/chat-web-preflight.json \
  --output /secure/operator/chat-readiness-report.json
```

성공은 exit 0과 `gate: passed`, live 실측·후보 commit 불일치는 exit 2, manifest·evidence 형식 오류나 필수 승인 누락은 exit 64다. raw manifest와 evidence는 승인된 운영 저장소에 두며 Git 저장소에 커밋하지 않는다.
