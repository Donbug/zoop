# AI 런타임 준비 가이드 (S1 live 준비, 2026-10-15)

이 문서는 실제 AI 호출 **이전**의 준비만 다룬다. 어떤 예산·endpoint·데이터 범위도 승인하지 않으며, agent는 key를 읽거나 저장하지 않고 호출을 만들지 않는다. 사람이 §6의 setup CLI로 key를 `.env`에 직접 기록할 수는 있지만 그것이 호출·지출 승인은 아니다. 승인 전에는 아래 `config-check`, 합성 replay, 네트워크 없는 로컬 smoke(§7)만 실행한다. 선택한 프로필은 **생성·briefing-outlook은 LLM `gpt-6-luna` + reasoning effort `high`, 의미 검증(VERIFY)은 네이티브 Jev `jev-1.14.0`(옵트인, §8)** 이다. 사용자의 현재 `ai/worker/.env`는 사람이 감사되는 setup을 다시 실행해 갱신하기 전까지 **이전 프로필**(VERIFY도 `gpt-6-luna`)이며 이 구현은 그 파일을 읽거나 바꾸지 않았다. 설정 이름의 단일 출처는 [`ai/worker/.env.example`](../../ai/worker/.env.example)이고, 정책 배경은 [AI 시스템 설계](../design/ai-system.md)다.

## 1. 지금 실제로 실행되는 것

| 영역 | 상태 | 비고 |
|---|---|---|
| S1 문서 요약·감성 생성, 기존 outlook (`zoop-ai`) | live 가능 | **OpenAI-compatible `chat/completions`**. 요청당 정확히 한 번 송신, 재시도 없음, `json_schema` strict, effort는 비면 필드 생략 |
| S1 의미 검증 (`semantic-verification`) | live 가능 | 기본은 위 chat adapter. `ZOOP_AI_VERIFY_PROVIDER=typesafe-native`를 고르면 네이티브 Jev(아래 행) |
| S2 추출·비교·topic, S3 관계·impact·검증 (`zoop-ai-extract`, `zoop-ai-relation`) | 기본 replay. **live 경로 구현됨, 기본 꺼짐, 합성 데이터 1회 실측(§10.8)** | `ai/pipeline`의 `live_runtime` 기본 family(PIPELINE)가 일곱 stage의 실제 요청 빌더와 한 번만 보내는 transport를 가진다(§10). 호출은 승인된 별도 실행에서만 한다 |
| 이슈 요약 (`issue-summary`, `verify-issue-summary`) | **별도 family 구현됨(§10.9), 기본 꺼짐, 실제 유료 호출 없음** | 같은 `live_runtime`의 별도 `ISSUE_SUMMARY` family. 합성 단위 검사와 loopback CLI 검증 범위는 §10.9를 따른다 |
| 네이티브 TypeSafe Jev | **옵트인 검증 전용 live 경로**: S1 `semantic-verification`(`ZOOP_AI_VERIFY_PROVIDER`), S3 `verify-*`(§10.1), 이슈 요약 `verify-issue-summary`(§10.9) | `POST {TYPESAFE_BASE_URL}/systemone`, 검증 stage당 한 번, 재시도·redirect 없음. 생성·outlook은 Jev가 하지 않는다. Choice/Noul 임계치는 **잠정 공학값(미보정)** (§8) |
| Responses API / 도구 호출 | 미구현 | S1은 도구를 보내지 않는다 |

Jev를 OpenAI 호환 base URL이나 chat 모델 칸에 넣으면 동작하지 않는다. `config-check`는 이를 오류(`native_jev_model_on_openai_compatible_chat`, `native_jev_endpoint_not_openai_compatible`)로 보고한다. 가짜 Jev env를 OpenAI base에 두지 않는다. 기존 검증을 Jev로 자동 전환하지 않는다: `ZOOP_AI_VERIFY_PROVIDER`를 명시한 때만 바뀌고, 이미 저장된 job은 환경이 아니라 submit 때 고정한 설정을 따른다. S1 worker 설정(`ZOOP_AI_LIVE_ENABLED`, `ZOOP_AI_GLOBAL_MAX_CALLS`)과 S2/S3 파이프라인 live 설정(`ZOOP_AI_PIPELINE_LIVE_*`, §10)은 **별개**이며 한쪽을 켜도 다른 쪽이 켜지지 않는다. Jev 임계치는 두 경로 모두 미보정이다.

## 2. 오프라인 점검: `zoop-ai config-check`

```sh
ai/worker/.venv/bin/zoop-ai config-check --format text
ai/worker/.venv/bin/zoop-ai config-check [--require-live-prerequisites] [--profile native-jev]   # JSON(기본)
```

- 현재 프로세스 환경변수만 읽는다. `--state-dir`을 받지 않고(주면 거부), 원장 디렉터리·파일을 만들지 않으며, grant 파일·stdin을 읽지 않고, provider·소켓·job을 만들지 않는다. `.env`도 자동으로 읽지 않는다. 파일 등록과 프로세스 환경 주입은 별도이며 아래 setup 절을 따른다.
- stage 검증은 worker의 `stage_config`, endpoint 규칙은 provider의 `validate_base_url`을 그대로 쓴다. 일반 명령의 동작과 예외는 바뀌지 않는다.
- **마스킹**: API key는 존재 여부(`apiKeyPresent`)만, proxy URL·URL userinfo·잘못된 값은 값 없이 `{severity, field, code}`로만 나온다. `field`는 고정된 환경변수 이름이다. 유효한 model·effort·endpoint host는 그대로 보인다(비밀 형태의 model 문자열은 `stage_model_malformed`로 가리고 출력하지 않는다).
- 종료 코드: 설정 오류가 없으면 0, 있으면 2. `--require-live-prerequisites`는 live 필수 조건(blocker)이 하나라도 있어도 2.
- **프로필**: 기본 프로필은 모든 단계를 OpenAI 호환 adapter로 기대한다. `--profile native-jev`는 `ZOOP_AI_VERIFY_PROVIDER=typesafe-native`(VERIFY=Jev)를 기대하며, 둘이 어긋나면 조용히 바꾸지 않고 `native_verify_not_selected` / `native_verify_selected_use_native_jev_profile` 오류로 보고한다. 네이티브가 선택되면 보고서에 `verifyProvider`, `nativeEndpoint`(유효 여부·scheme·host·`providerRevision`: grant recipient `typesafe-native:<providerRevision>`를 만드는 값. OpenAI 쪽은 `endpoint.providerRevision`으로 `openai-compatible:<providerRevision>`), `liveGate.typesafeApiKeyPresent`, VERIFY stage(`provider=typesafe-native`, 모델은 `TYPESAFE_VALIDATION_MODEL`, effort 해당 없음)가 나온다. TYPESAFE key·URL은 존재 여부와 host만 보이고 값은 출력하지 않는다. key 형식 오류(`typesafe_api_key_malformed`), URL userinfo·query, base URL에 `/systemone` 포함(`native_base_url_includes_endpoint_path`), 별칭·다른 버전 모델(`native_model_unsupported`), 남은 chat VERIFY 설정(`native_verify_stale_model_setting` / `native_verify_stale_effort_setting`)은 오류다.

### 세 가지를 섞지 않는다

| 보고 필드 | 뜻 | 뜻하지 않는 것 |
|---|---|---|
| `configValid` | 설정이 파싱·정책 검증을 통과 | live 가능, 승인됨 |
| `liveEnvironmentReady` | live 환경 조건(`LIVE_ENABLED=1`, 양수 `GLOBAL_MAX_CALLS`, key 존재, 실행할 stage model)이 환경에 있음 | **지출 승인.** 승인은 환경변수에서 추론하지 않는다(`authorization.liveSpend=not_inferred_from_environment`) |
| `authorization.accountAndModelAvailability` | 항상 `unverified_no_request_sent` | 계정이 모델을 쓸 수 있다는 보장. 첫 승인된 호출 전에는 알 수 없다 |

`severity`: `error`(설정 오류, `configValid=false`), `blocker`(유효하지만 live 불가: `live_not_enabled`, `global_max_calls_not_positive`, `api_key_required`, `stage_model_required`, 네이티브 선택 시 `typesafe_api_key_required`), `warning`(`proxy_env_routes_endpoint`, `custom_ca_env_present`, `endpoint_not_default_openai_host`, `endpoint_not_default_typesafe_host`, `endpoint_loopback_plain_http`, `stage_model_not_in_reviewed_list`, `reasoning_effort_unset_provider_default_applies`, `openai_api_key_env_not_read_use_zoop_ai_api_key`, `typesafe_env_present_native_verify_not_selected`, `live_enabled_value_ignored_only_1_enables`).

주의할 점:

- worker의 HTTP client는 환경변수 proxy(`HTTPS_PROXY`, `ALL_PROXY` 등)와 `SSL_CERT_FILE`을 따른다. key와 문서 본문이 proxy를 지나갈 수 있으므로 `proxy_env_routes_endpoint` 경고가 나오면 승인된 proxy인지 확인한다(macOS 시스템 proxy 설정은 환경변수가 아니라 점검하지 못한다). 이 동작은 바꾸지 않았다.
- `ZOOP_AI_GLOBAL_MAX_CALLS`는 CLI와 같이 `int()`로 파싱한다. 비어 있거나 숫자가 아니면 모든 명령이 실패하므로 `global_max_calls_invalid` 오류다.
- model 별 effort: `gpt-6-luna`는 `none/low/medium/high/xhigh/max`만 지원한다(공식 문서, 2026-10-15 확인). `minimal`은 doctor가 `reasoning_effort_unsupported_for_model`로 거부한다. worker 전역 enum(`minimal` 포함)은 다른 모델을 위해 그대로다. 목록에 없는 모델은 거부하지 않고 경고만 한다.

## 3. 환경변수

| 이름 | 역할 | 기본 |
|---|---|---|
| `ZOOP_AI_LIVE_ENABLED` | 정확히 `1`일 때만 live | `0` |
| `ZOOP_AI_GLOBAL_MAX_CALLS` | 원장 하나의 총 호출 수 상한(양수여야 live) | `0` |
| `ZOOP_AI_PROVIDER` | `openai-compatible`만 | 그 값 |
| `ZOOP_AI_BASE_URL` | https(loopback만 http), userinfo·query 없음 | `https://api.openai.com/v1` |
| `ZOOP_AI_API_KEY` | worker 프로세스가 쓰는 key. `OPENAI_API_KEY`는 읽지 않는다 | 없음 |
| `ZOOP_AI_{DOCUMENT_SUMMARY,DOCUMENT_SENTIMENT,BRIEFING_OUTLOOK}_MODEL` | stage 모델(문서 작업은 생성 stage, outlook은 자기 것) | 선택 프로필: `gpt-6-luna` |
| 위 이름의 `_REASONING_EFFORT` | 비면 요청 필드 생략, provider 기본이 적용됨 | 선택 프로필: `high` |
| `ZOOP_AI_VERIFY_MODEL`, `ZOOP_AI_VERIFY_REASONING_EFFORT` | **chat 검증기(기본)일 때만** 쓰인다. 네이티브 검증을 고르면 **비워 둔다**: 남아 있으면 submit이 `native_verify_stale_model_setting` / `native_verify_stale_effort_setting`으로 실패하고 doctor가 오류로 보고한다 | 네이티브 프로필: 없음 |
| `ZOOP_AI_VERIFY_PROVIDER` | `openai-compatible`(기본, 비었거나 없음) 또는 `typesafe-native`. `semantic-verification` stage에만 적용되고 submit 때 job에 고정된다. 그 밖의 값은 `provider_unsupported` | 선택 프로필: `typesafe-native` |
| `TYPESAFE_API_KEY` | 네이티브 검증 client만 쓰는 key. 환경에서만 읽으며 아직 보낼 검증 stage가 있을 때만 필요하다 | 없음 |
| `TYPESAFE_BASE_URL` | https(loopback만 http), userinfo·query 없음, `/systemone`을 붙이지 않는다(adapter가 붙인다) | `https://api.typesafe.ai/v1` |
| `TYPESAFE_VALIDATION_MODEL` | 네이티브 검증 모델. 정확히 `jev-1.14.0`만 허용한다(`jev-latest`/`jev-preview`·다른 버전은 `native_model_unsupported`) | 선택 프로필: `jev-1.14.0` |

**S1 worker의 예산은 호출 횟수뿐이다**(`ZOOP_AI_GLOBAL_MAX_CALLS`). 호출 전에 원장에 예약(reservation)을 남기고, 상한은 줄일 수만 있으며(`budget_increase_requires_new_authorized_ledger`), 송신 결과가 불확실한 호출도 소비한 것으로 센다. S1에는 금액·토큰 상한이 없고(`budget.costCap=null`), 이 문서와 설정은 임의의 달러 예산이나 가격 상한을 만들지 않는다. S2/S3 파이프라인 live 런타임은 이와 별개로 USD와 호출 수를 함께 세는 공유 예산을 쓴다(§10.5).

## 4. 선택한 프로필 (호출 승인 아님)

- LLM 모델 `gpt-6-luna`, reasoning effort `high`를 세 단계(문서 요약·감성·briefing-outlook)에 쓰고, 의미 검증(VERIFY)은 네이티브 Jev `jev-1.14.0`으로 한다(사용자 결정, 2026-10-15; 검증을 Jev로 옮기는 것은 이 구현의 요청이며 호출 승인이 아니다). `minimal`은 쓰지 않는다. 범용 provider 코드는 다른 모델 ID를 막지 않으며 이 고정은 setup CLI와 `.env.example`의 값이다.
- Chat Completions는 `gpt-6-luna`에서 `reasoning_effort`가 `none`일 때만 함수 호출을 지원하고, 추론과 도구를 함께 쓰려면 Responses API가 필요하다. 지금 S1은 도구가 없으므로 chat이 유효하다. 이 간극은 `capabilityGaps.responses_api_not_implemented`로 표시되며, 도구가 필요해지면 chat에서 추론을 억지로 쓰지 않고 Responses adapter를 새로 구현해야 한다.
- 재현성: 벤치마크는 요청한 모델 ID를 고정하고 응답에 기록된 실제 모델을 함께 저장한다. `gpt-6-luna`의 공식 snapshot은 현재 같은 이름 하나이며, 이후 바뀌면 결과 비교 전에 다시 확인한다.

## 5. 운영과 벤치마크의 분리

- 운영과 벤치마크는 **서로 다른 `--state-dir`, 서로 다른 key, 서로 다른 예산 원장**을 쓴다. 원장 하나의 상한을 다른 용도와 공유하지 않는다.
- key의 크레딧·사용 한도·모델/endpoint 제한 지원 여부는 발급처(OpenAI 콘솔 등)에서 확인한다. Zoop 쪽에서 검증할 수 없다.
- 개인 TypeSafe Jev 계정과 비용은 OpenAI와 **별개**다. key를 복사해 공유하지 않고, 채팅에 붙여넣지 않는다. 호출자의 로그인(웹/CLI 세션)은 API 접근 권한이 아니다.
- 로컬 키는 아래 CLI로 Git에서 제외된 `ai/worker/.env`에 0600 권한으로 등록한다. 실행 시에는 필요한 변수만 해당 프로세스 환경에 주입하며, 키를 커밋·로그·이슈에 넣지 않는다. 같은 프로세스에 불필요한 다른 키를 함께 내보내지 않는다.

## 6. key 설정: 사람이 직접 실행하는 setup CLI (값은 이 문서에 쓰지 않는다)

```sh
python3 ai/worker/scripts/setup_ai_env.py            # 대화형 설정
python3 ai/worker/scripts/setup_ai_env.py --status   # 감사 기록만 읽어 완료 여부 보고(.env는 열지 않음)
```

1. 용도별 key를 발급처에서 발급한다(벤치마크용 / 운영용 분리, 한도 설정). key는 채팅·인수·로그에 붙여넣지 않는다.
2. 실제 터미널에서 위 명령을 직접 실행한다(stdlib만 사용, 파이프 입력 거부). 대상 `.env`와 감사 기록 경로를 보여 준 뒤 `[yes/N]` 동의를 받고, 그 **다음에야** `ZOOP_AI_API_KEY`, `TYPESAFE_API_KEY`를 숨김 입력으로 묻는다. Enter만 누르면 건너뛰고 기존 값은 그대로 둔다. 동의·입력 단계의 Ctrl-C/Ctrl-D/거절은 파일을 변경하지 않는다. 쓰기가 시작된 뒤에는 중단 신호로 완료 상태를 오인하지 않도록 커밋 결과를 보고한다.
3. 기록 내용: 고정 프로필(`gpt-6-luna`/`high` 세 단계, `ZOOP_AI_VERIFY_PROVIDER=typesafe-native`, `TYPESAFE_VALIDATION_MODEL=jev-1.14.0`, base URL들), 그리고 **`ZOOP_AI_LIVE_ENABLED=0`, `ZOOP_AI_GLOBAL_MAX_CALLS=0` 강제**(기존 값이 있어도 덮어씀). 더는 쓰이지 않는 `ZOOP_AI_VERIFY_MODEL`·`ZOOP_AI_VERIFY_REASONING_EFFORT` 줄이 `.env`에 있으면 **삭제**한다(동의 전에 이름만 알리고 값은 읽어도 출력·기록하지 않는다. 남겨 두면 worker가 거부한다). 삭제 대상이 중복·여러 줄이면 추측하지 않고 거부한다. key 등록은 지출을 승인하지 않으며, live와 호출 상한은 별도 승인 뒤에 사람이 따로 바꾼다. Enter만 누른 key는 건너뛰고 기존 값을 그대로 둔다.
4. 안전: 대상은 기본 `ai/worker/.env`(`--env-file`+`--audit-file`로만 재지정). 줄 단위 리터럴 병합이라 관련 없는 줄은 보존하고 쉘로 source하지 않는다. 관리 이름의 중복·여러 줄 값·줄 이음·CR/NUL, 심볼릭 링크·일반 파일 아님·타 소유자·group/other 쓰기 가능 디렉터리(상위 포함)는 거부한다. 같은 디렉터리의 다른 setup이나 입력 중 파일 변경도 거부한다. 같은 디렉터리 임시 파일(0600)에 쓴 뒤 원자적으로 교체하고 secret 백업은 만들지 않는다. key는 어떤 dotenv/쉘 소비자도 보간하지 않도록 영숫자와 `-_.~+/=:`만 허용하며(그 밖의 문자는 거부) `NAME='값'` 형태로 저장한다.
5. 감사 기록 `ai/worker/var/setup-audit.jsonl`(0600, git 무시; 재지정 시 `.env`와 같은 파일이면 거부): 시각·작업 ID·대상·변수 **이름**·삭제한 이름(`removedNames`)·고정 프로필·결과(`planned`→`committed`/`failed`)만 남기고 값·지문은 남기지 않는다. 이전 프로필(Jev 준비 전용)로 남은 기록도 유효한 기록으로 읽으며 `--status`가 그 사실을 알린다. 쓰기 전에 `planned`를 남기며, 쓰기 실패는 롤백 없이 보고하고 `failed`를 남긴다. `.env`는 갱신됐으나 `committed`를 못 남기면 종료 코드 4와 함께 "감사 완료 불확실"로 보고한다.
6. `--status`는 형식이 검증된 필드만 출력하며(종료 코드 0은 마지막 작업이 `committed`일 때만) **"감사된 setup 작업이 있었다"는 것만** 증명한다. 지금 key가 유효한지, 계정·모델을 쓸 수 있는지, `.env`가 그 뒤 바뀌지 않았는지는 알려 주지 않는다(`.env`를 열지 않는다).
7. 종료 코드: 0 완료, 1 취소/미완료 상태, 2 거부(`.env` 변경 없음), 3 쓰기 실패, 4 `.env` 갱신·감사 불확실.

**worker는 `.env`를 자동으로 읽지 않는다.** setup은 파일을 쓸 뿐 어떤 프로세스에도 export하지 않으며, 이 문서는 임의의 `.env`를 쉘로 source하라고 권하지 않는다(관련 없는 기존 줄이 보존되어 있고 그 내용은 이 도구가 보증하지 않는다). 값을 worker 프로세스 환경에 넣는 방법은 승인된 운영 절차가 정한다. 합성 환경의 `zoop-ai config-check --profile native-jev --format text`는 두 key의 존재 여부(`apiKeyPresent`, `typesafeApiKeyPresent`), VERIFY=`typesafe-native`/`jev-1.14.0`, 나머지 stage `gpt-6-luna`/`high`, `liveGate.enabled=False`만 보여 주며 key가 유효하다는 증거가 아니다.

검증(2026-10-15, 네이티브 검증 도입 전 프로필 기준): worker 테스트 146개와 생성 schema 일치 검사가 통과했다. 별도의 합성 PTY 실행에서도 동의 → 숨김 키 입력 → 0600 `.env` 쓰기 → 비밀 없는 `planned/committed` 감사 기록 → 감사 전용 상태 조회를 확인했다. 실제 키·계정·모델 호출은 검증하지 않았다.

## 7. 첫 smoke 계획 — 사용자가 예산·endpoint·데이터 범위를 승인하기 전에는 실행하지 않는다

대상은 repo가 작성한 합성 문서 하나(33자, 외부 데이터 없음, `grant-synthetic-s1`)이고, 호출은 정확히 2회다: `document-summary`(chat)와 `semantic-verification`(네이티브 Jev 또는 chat 검증기). **네이티브 검증 smoke는 네트워크 없는 로컬 smoke(아래)를 먼저 통과해야 한다.**

```sh
S=/tmp/zoop-ai-smoke-1                      # 운영/벤치마크 원장과 다른 새 디렉터리
mkdir -p "$S" && python3 - <<'PY' > "$S/submit.json"
import json
job = json.load(open("ai/worker/fixtures/contracts/synthetic-document/jobs.json", encoding="utf-8"))["jobs"][0]
job.update(jobId="smoke-live-1", mode="live",
           provenance={"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"})
print(json.dumps(job, ensure_ascii=False))
PY
# 승인 후에만: 이 한 프로세스에 smoke 전용 key와 ceiling 2
export ZOOP_AI_LIVE_ENABLED=1 ZOOP_AI_GLOBAL_MAX_CALLS=2   # + 승인된 ZOOP_AI_API_KEY, stage 모델/effort, 네이티브 검증이면 ZOOP_AI_VERIFY_PROVIDER=typesafe-native TYPESAFE_API_KEY TYPESAFE_VALIDATION_MODEL=jev-1.14.0
# G: 합성 grant의 사본. recipients에 config-check가 출력한 revision으로 만든 `openai-compatible:<rev>`와(네이티브면) `typesafe-native:<rev>`를 넣는다(원본 fixture의 protocol 이름만으로는 live 전송이 허가되지 않는다)
Z=ai/worker/.venv/bin/zoop-ai; G=ai/worker/fixtures/contracts/synthetic-document/grants.json
$Z config-check --format text --require-live-prerequisites --profile native-jev   # 네이티브 검증이 아니면 --profile 생략
$Z submit --state-dir "$S" --grants "$G" < "$S/submit.json"
echo '{"schemaVersion":"zoop-ai-s1-1","jobId":"smoke-live-1"}' | $Z run --state-dir "$S" --grants "$G"
echo '{"schemaVersion":"zoop-ai-s1-1","jobId":"smoke-live-1"}' | $Z get --state-dir "$S"
```

통과 기준: `get` 결과의 `calls`가 정확히 2건(`stage`가 `document-summary`, `semantic-verification`)이고 둘 다 `receivedAt`이 있으며, `usage.providerAttempts`가 2이고 job `state`가 `ready`이며 상한 2가 소진된다. 어느 한 단계가 실패해도 자동 재시도하지 않고 멈춘다. 상한을 올리려면 새 원장과 새 승인이 필요하다. smoke 결과는 합성 데이터라 모델 품질 근거가 아니다.

### 외부 네트워크 없는 로컬 smoke (합성 키·loopback 서버만 사용)

```sh
ai/worker/.venv/bin/python ai/worker/scripts/native_jev_smoke.py
```

로컬 가짜 provider 두 개(chat, `systemone`)와 **설치된 `zoop-ai` CLI**를 쓰며 환경을 상속하지 않는다. 각 key가 자기 서버에만 가는지, 네이티브 요청의 모델·질문 구성, 기록된 모델·usage·raw receipt, ready/hold/reject, 형식이 틀린 응답의 receipt 보존과 재실행 시 추가 송신 없음, 호출 상한 공유, Jev key 부재 시 생성 stage도 보내지 않음을 검사하고 모두 통과해야 종료 코드 0이다. 같은 내용을 `tests/test_native_jev.py`가 단위·통합으로 검사한다.

**실행 확인(2026-10-15, 로컬 작업 트리).** worker 252개, service 전체 654개, BFF 감성·권한 16개 테스트가 통과했다. Spring은 410개 중 14개를 건너뛰었고 실패·오류는 0이었다. 위 실제 CLI와 loopback 서버 smoke에서 통과·보류·거부·잘못된 모델/응답·HTTP 실패·키 부재·캐시·예산·무재송신 복구를 확인했다. worker schema와 replay fixture는 변경 없이 일치했고, public-check는 생성물 275개 drift 0·hard error 0·문서 테스트 21개 통과였다. 기존 Starlette deprecation 경고는 유지했다. 실제 키·외부 모델·운영 데이터는 사용하지 않았다.

검토 중 발견한 두 결함도 수정했다. 잘못된 native 응답의 원문 영수증과 오류 코드를 하나의 transaction으로 저장해 중단 후에도 원래 실패 사유를 보존한다(수정 전 실패·수정 후 통과). 서비스의 확정 설정 오류 세 종류는 409로 반환하고 작업 ID 예약을 해제해 수정 후 재접수할 수 있다. 초기 서비스 회귀는 이전 worker 복사본을 사용해 실패했으며, `uv sync --offline --project ai/service --frozen --group dev --reinstall-package zoop-ai-worker`로 로컬 패키지를 갱신한 뒤 전체 654개가 통과했다. 서비스 환경의 worker는 비편집 설치이므로 worker 소스 변경 뒤 이 재설치가 필요하다.

## 8. 네이티브 Jev 검증 (구현됨, 옵트인, 임계치 잠정)

`ZOOP_AI_VERIFY_PROVIDER=typesafe-native`를 고른 live 작업의 `semantic-verification` stage만 `POST {TYPESAFE_BASE_URL}/systemone`(공식 문서: `model`·`state`·`questions` → Choice/Noul/Score, 응답은 `model`·`answers`·`usage`)로 간다. 기본(변수 없음)은 기존 chat 검증기이며 기존 job·replay는 달라지지 않는다. 문서 요약·감성 생성과 briefing-outlook은 계속 chat adapter이고 Jev가 하지 않는다. 이 절은 **S1 worker 경로**만 다룬다. S2/S3(추출·관계·impact와 그 검증)의 live 경로는 별개의 네이티브 파이프라인 런타임이며 §10이 다룬다(S1 worker 설정·원장·예산과 공유하지 않는다).

- **요청**: 검증 stage당 정확히 한 번 POST, 재시도·redirect·SDK 없음, `Authorization: Bearer`만(장문·이미지 danger-zone 헤더 `TypeSafe-Danger-Zone-*`는 켜지 않는다). state는 문서 본문(`document.inputKind`·`text`), 기업 이름, 후보 claim(종류·문구·인용 구간)뿐이며 grant·key·설정·내부 식별자는 보내지 않는다. 질문은 claim마다 Choice 하나(`supported`/`contradicted`/`insufficient`)와 독립 Noul 둘(`prohibitedAdvice`, `unsupportedCausality`)이고 질문 문구마다 의미와 claim 참조(`candidate.claims[i]`)를 담는다. 모델은 정확히 `jev-1.14.0`(별칭·다른 버전 거부), reasoning effort는 해당 없다. 정확 검사(인용 위치·claim 커버리지)는 의미 검증보다 먼저이며 바뀌지 않았다.
- **판정(잠정 임계치, 미보정)**: Choice는 승리 확률 ≥ 0.90 **그리고** confidence ≥ 0.80일 때만 `supported`/`contradicted`로 받고, 아니면 `insufficient`다. Noul은 ≥ 0.90이면 예(거부), ≤ 0.10이면 아니오, 그 사이는 **불확실**이라 발견으로 만들지 않고 아직 `supported`인 claim을 `insufficient`로 내려 `hold`가 된다(`contradicted`는 그대로). 결과는 변경 없는 `VerificationAnswer`이고 gate는 기존 `reject > hold > supported` 그대로이며, 불확실한 것은 어떤 경우에도 자동 승인되지 않는다. 사유(`reason`)는 숫자와 규칙으로 코드가 만든 문장(`native_policy: ...`)이며 모델 문장이 아니다. 이 값들은 공학적 잠정값이며 Zoop 한국어 평가셋으로 보정·검증되지 않았고 승인 기준이 아니다. 바꾸면 `promptVersion`이 달라져 job 입력 digest·캐시 키가 달라진다.
- **엄격한 응답 검사**: 응답 `model`이 요청 모델과 같아야 하고, 답은 질문과 정확히 같은 키 집합·유형이어야 하며, Choice는 세 선택지가 모두 있고 확률이 [0,1]의 유한한 수·합 1±0.02·이름 붙은 선택이 최댓값이어야 하고 confidence와 Noul도 [0,1]의 수여야 한다. 어긋나면 **원문 응답을 receipt로 먼저 저장하고** 단계를 닫힌 채로 실패시킨다(`native_model_mismatch`, `native_response_invalid`, `native_answers_invalid`). 재시도·보정·fallback은 없고 `run`/`resume`/`get`을 다시 해도 아무것도 더 보내지 않는다.
- **오류**: 2xx가 아닌 상태는 확정 실패(`provider_http_<status>`, receipt 없음), 전송 오류·timeout은 결과 불명(`reconciling`, 자동 재송신 없음)이다. 기존 chat adapter와 같은 규칙이며 429·529도 자동 재시도하지 않는다.
- **receipt·사용량·예산**: 원문 Jev 응답(확률·confidence·실제 `model`·`usage`)이 worker 원장에 그대로 남고, 호출 기록의 `usage`에는 Jev가 보고한 입력·출력 토큰만 들어간다(cached/reasoning은 `null`). 호출은 chat과 **같은 하나의 호출 수 상한**에서 센다(실패·불명 호출도 소비).
- **고정과 identity**: submit 때 검증 stage 설정(provider `typesafe-native`, endpoint revision, `jev-1.14.0`, 질문 문구·state 모양·임계치에서 계산한 `promptVersion`, `policyVersion`은 기존 `zoop-document-gate-2`)이 job에 고정되어 입력 digest와 캐시 키에 들어간다. 실행은 환경이 아니라 **고정된 설정**을 따른다: 환경이 바뀌어 고정 설정과 맞지 않으면(`provider_configuration_changed`) 아무것도 보내기 전에, 생성 stage 비용을 쓰기 전에 실패하며 chat↔Jev로 갈아타지 않는다. 이미 받은 receipt는 key·provider 없이 그대로 복구되고, 필요한 key는 아직 보낼 stage의 provider 것뿐이다.
- **권한(recipient)**: 생성과 검증은 서로 다른 수신자다. grant의 `recipients`에 `openai-compatible:<revision>`(생성)과 `typesafe-native:<revision>`(검증)이 모두 있어야 하고 `purposes`에 두 stage 목적이 있어야 한다. worker는 각 stage를 자기 설정의 recipient로 따로 확인하고, 서비스·BFF(수정함)·Spring 앱(코드 변경 없음, `ResultAssessor`·`EvidenceService`가 이미 stage별 receipt로 확인)이 전달·읽기 시점에 각 단계를 그 단계의 호출이 증명한 수신자로 확인하므로 chat recipient가 Jev 전송을 허가하지 않는다. flat grant는 (목적, 수신자) 짝을 표현하지 못하므로 두 목록의 포함만 본다. 철회는 새 grant revision으로 하며 고정된 job은 `grant_revision_or_source_changed`로 닫힌다.
- **환경 전달**: 서비스 child 환경은 `TYPESAFE_API_KEY`·`TYPESAFE_BASE_URL`·`TYPESAFE_VALIDATION_MODEL`·`ZOOP_AI_VERIFY_PROVIDER`를 live가 열린 S1 child에만 넘기며 S2/S3/그래프 child에는 넘기지 않는다. BFF는 문서 분석을 live로 실행하지 않고(outlook만) 저장된 결과를 읽는다.
- **한계**: Jev는 claim과 두 Noul만 판정한다(감성 `label` 자체는 질문이 아니다). 임계치 미보정, 한국어 금융 평가셋 없음, 계정·모델 가용성과 응답 `usage`의 실제 모양은 첫 승인된 호출 전에 알 수 없다. 요청이 모델 한도(기본 64k)를 넘으면 `provider_http_400`으로 실패하고 자르지 않는다.
- **평가 scaffolding(보정 아님)**: 오프라인 한국어 금융 검증 벤치마크의 하네스(직접 쓴 합성 case 28개, 따로 쓴 gold, 설치된 CLI→loopback 가짜 서버→receipt export→엄격 채점)는 `ai/evaluation`과 `ai/worker/scripts/verification_bench.py`에 있다. 가짜 서버의 답은 저작된 control이고 gold는 단일 작성자·미합의라서 이 하네스는 위 임계치를 정하거나 바꾸지 않는다. 명령과 지표는 [AI 벤치마크 설계](../design/ai-benchmark.md)의 “한국어 금융 semantic-verification 벤치마크”를 따른다. CLI는 설치본을 실행하므로 worker 소스를 고친 뒤에는 `make worker-install`로 다시 설치한 다음 이 smoke를 돌린다.
- Jev 확률은 검증 판정의 분포일 뿐 감성·가격 변동 확률이나 LLM 생성 확률이 아니며 호출 비용(입력 토큰 단가)과도 무관하다. 근거와 조사 결과는 [AI 시스템 설계](../design/ai-system.md)를 따른다.

## 9. 사람이 정해야 하는 것 (미해결)

1. live 호출 승인: 총 호출 수 상한, 사용할 endpoint(기본 OpenAI)와 proxy 사용 여부, 전송 데이터 범위.
2. `gpt-6-luna` 사용 가능 여부(계정 접근). effort는 `high`로 확정되었다.
3. 운영/벤치마크 key 발급처 한도, 크레딧, 모델/endpoint 제한 지원 여부.
4. 개인 Jev 계정 키·비용 부담 주체, Choice/Noul 임계치의 보정 방식(한국어 평가셋)과 네이티브 검증을 켤 문서 종류·시점.
5. 도구/추론이 필요한 단계를 만들 때 Responses adapter를 구현할지 여부.

## 11. 챗봇 모델 단계 (`zoop-ai-chat`, 구현됨, 기본 꺼짐, 호출 승인 아님)

챗봇 오케스트레이터(`api` `com.zoop.chat.orchestrator`)의 모델 단계 셋을 한 번에 하나씩 실행하는 CLI다. S1·파이프라인과 계약·게이트·원장·grant를 공유하지 않는다(정책 6.3.2).

| stage | provider | 요청 | 시간 상한 |
| --- | --- | --- | --- |
| `chat-router` | 네이티브 Jev `/systemone`, `ZOOP_AI_CHAT_JEV_MODEL=jev-1.14.0` | 요구별 Q01~Q08·연결 기능·투자 판단 Noul | 4초 |
| `chat-answer` | OpenAI 호환 `chat/completions`, `ZOOP_AI_CHAT_ANSWER_MODEL`은 정확히 `gpt-6-luna`, `_REASONING_EFFORT`는 `high`(생략 시 `high`, 다른 값 거절) | 엄격 JSON 구간별 답변 | 25초 |
| `chat-verification` | 네이티브 Jev `/systemone` | 근거 구간 지지 Choice, 모든 구간 투자 판단 Noul | 6초 |
| `chat-agent` | OpenAI 호환 `responses`, `ZOOP_AI_CHAT_AGENT_MODEL`은 정확히 `gpt-6-luna`, `_REASONING_EFFORT`는 `medium`(생략 시 `medium`, 다른 값 거절), `store=true`, MCP 서버 URL은 운영자 설정 `ZOOP_AI_CHAT_MCP_SERVER_URL`만(HTTPS·기본 포트·userinfo/query/fragment 없음, 요청으로 지정 불가, 없으면 live 송신 안 함), grant는 MCP 도구의 `authorization`으로 매 단계 전송 | ZOOP MCP 도구(`require_approval=always`) 한 단계: 승인 요청에서 멈추거나 `chat-answer`와 같은 schema의 최종 답변. 승인은 앱이 결정하고 다음 단계(`continuation`)로 전달 | 30초 |

- **MCP preflight**: `zoop-ai-chat probe-mcp`는 모델 단계와 별개로 운영자 설정 URL에 grant 없는 JSON-RPC `ping`을 보낸다. endpoint 자체의 `401` Bearer challenge만 exit 0 `reachable`; timeout·연결 실패·앞단 gateway의 502/503/504(`mcp_unavailable`)·다른 응답은 exit 2 `unreachable`과 닫힌 reason이며 redirect를 따르지 않는다. URL 설정 오류는 exit 64다. 원장·모델·live 예산을 쓰지 않으며 ai/service의 `GET /internal/v1/chat-mcp-health`가 같은 `chat.invoke` scope로 노출한다. 이는 Java가 Responses 시작 전 경로를 선택하기 위한 관측이고 circuit 상태나 direct 전환을 자체 관리하지 않는다.
- **운영 readiness**: 운영 HTTPS·출발지 제한 선택, model-send grant, Responses `store=true` 보유 조건·외부 처리 고지, 키 회전·사고 대응·증거 보존 결정과 preflight, 같은 후보 commit의 live spike는 [챗봇 MCP 운영 readiness gate](chat-operations-readiness.md)로 함께 확인한다. 이 검사는 실제 endpoint·비밀을 받지 않고 배포·플래그 변경도 하지 않는다.
- **게이트·예산**: `ZOOP_AI_CHAT_LIVE_ENABLED=1`과 양수 `ZOOP_AI_CHAT_MAX_CALLS`가 모두 있어야 live 송신. 상한은 네 model stage가 공유하며 `chat.sqlite3`의 live 송신 건수로 센다. 없으면 `chat_live_disabled`로 아무것도 보내지 않는다. key는 생성 `ZOOP_AI_API_KEY`, Jev `TYPESAFE_API_KEY`이며 각 key는 자기 endpoint에만 간다.
- **원장 우선·멱등·응답 불명**: `invocationId`(작업·시도·stage)당 한 번만 보낸다.
  - 원장을 **가장 먼저** 읽는다. 이미 있는 invocation은 지금의 gate·key·모델 설정과 무관하게 기록된 결과를 돌려주고, 보낸 호출을 "안 보냄"으로 바꾸지 않는다. 같은 id에 다른 요청(stage·mode·입력)이 오면 `invocation_conflict`이다.
  - 성공했던 답의 인용 출처 grant가 그 뒤 철회되면 `source_grant_withdrawn`(`sent=true`, 영수증 유지, 재전송 없음)으로 본문을 숨긴다.
  - 새 invocation만 gate·grant·sender를 검사한 뒤, **한 IMMEDIATE 트랜잭션**에서 송신권을 잡는다. 행이 송신 전 영수증과 함께 `sent`로 기록되고, 아직 결과가 없는 행도 live 상한에 포함된다. 같은 id의 동시 요청은 한 프로세스만 보내고 나머지는 `unknown`을 받는다.
  - 송신권을 잡은 뒤의 중단, timeout·연결 끊김은 `provider_response_unknown`(`unknown=true`, 송신 전 영수증 포함)이며 다시 보내지 않는다.
  - 받은 원문은 해석 **전에** 원장에 저장한다. 그 뒤 usage·응답 모델·답을 해석하며, 실패하면 원문을 남긴 확정 실패가 된다(`provider_usage_invalid`, `provider_model_missing`/`_mismatch`, 형식·분포 코드, 그 밖의 예외는 `provider_response_invalid`). 재시도는 없다.
  - 응답 모델은 설정 모델과 같아야 한다(Luna는 `gpt-6-luna-…` snapshot 허용). 영수증에는 실제로 답한 모델을 기록한다.
- **grant**: 인용문(`Quote.sourceId`)이 있는 stage는 운영자 챗봇 grant registry(`zoop-ai-chat-1`, S1 registry와 별도)에서 같은 source의 활성·`rights=known`·`model-send`·해당 stage 목적·정확한 수신자(`openai-compatible:<rev>` 또는 `typesafe-native:<rev>`, replay는 `authored-replay`) grant가 있어야 한다. 없으면 보내지 않는다. `chat-agent` 단계의 도구 결과는 이 런타임을 거치지 않고 앱 `/mcp`에서 공급자로 바로 가므로, 앱이 **같은 레지스트리 파일**(`ZOOP_CHAT_MCP_SEND_GRANTS`)을 읽어 같은 규칙(목적 `chat-agent`, 수신자 `ZOOP_CHAT_MCP_SEND_RECIPIENT`)으로 결과마다 확인한다. 앱은 그 수신자를 단계 입력 `mcp.recipient`로 보내고, 이 런타임은 그것이 단계의 실제 수신자와 다르면 `mcp_recipient_mismatch`로 보내지 않는다(앱이 검사한 수신자와 받는 수신자가 어긋나지 않게). 이 목적은 Responses 저장(`store=true`)·continuation 재개를 포함하며, 사건 제목·관계·경로는 source `zoop-graph`로 등록한다([챗봇 MCP 엔드포인트](../../api/docs/chat-mcp.md) 3장).
- **잠정 결정(2026-10-22, 미보정)**: Jev 판정 임계치는 S1 잠정값(Choice ≥ 0.90·confidence ≥ 0.80, Noul ≥ 0.90 / ≤ 0.10)을 재사용하고 라우터 확률은 앱이 0.70/0.35·투자 판단 > 0.10으로 적용한다. 질문 집합·임계치는 실제 호출 전 챗봇 평가 세트로 보정해야 한다.
- **정책 적용 범위(명시)**: 이 CLI는 ZOOP-AIG-001 6.3.2의 단계 분리와 6.3.3의 질문 집합 중 **구간 단위** 판정을 구현한다. 근거 구간은 지지 Choice와 투자 판단 Noul, 일반 개념 구간은 투자 판단 Noul만 판정한다. 6.3.3과 구현 계획 5단계가 목표로 적은 **claim별 독립 판정(`unsupportedCausality` 포함)과 Luna 입력 24,000·출력 2,000 토큰 상한은 아직 적용하지 않는다.** 두 항목은 거버넌스상 '팀 검토와 책임자 승인 후 적용' 대상이고 별도 승인 근거가 없기 때문이다. 채택이 확정되면 다음을 함께 바꾼다: 질문 집합·정책 버전(`prompt_version`)을 올리고, `max_completion_tokens`와 입력 token guard 및 그 실패 코드를 추가하고, 앱의 `ChatSemanticVerdicts` 결과 신호를 연결한다.
- **replay**: `--replay`의 authored fixture(`recordingKind=authored-test`)를 요청 identity digest로 정확히 찾는다. 없으면 `replay_input_mismatch`이며 보낸 것으로 기록하지 않는다. replay 응답에도 `model`(`authored-synthetic-<stage>`)이 있어야 한다.

## 10. S2/S3 live 파이프라인 런타임 (구현됨, 기본 꺼짐, 호출 승인 아님)

`ai/pipeline/src/zoop_ai_pipeline/live_runtime.py`(+ `live_prompts.py`, `live_jev.py`, `live_budget.py`)가 S2/S3의 실제 모델 경로다. S1 worker 코드·설정·원장과 **공유하지 않으며** private PoC를 import하지 않는다(PoC 프롬프트는 읽기 전용 exemplar로만 참고했다). 단위 테스트는 가짜 HTTP(`httpx.MockTransport`와 loopback 서버)만 쓴다. 별도 승인을 받은 운영자가 합성 데이터로 실제 호출 한 번을 검증했다(§10.8). 지출은 승인된 별도 실행의 몫이며 환경변수가 채워진 것은 승인이 아니다.

### 10.1 stage와 provider

| stage | 소비자 | provider | 요청 |
|---|---|---|---|
| `extract`, `compare`, `topic` | S2 | OpenAI 호환 `chat/completions`, 모델 `gpt-6-luna` | strict `json_schema`, `reasoning_effort`, `max_completion_tokens`(추론 포함 출력 상한) |
| `relation`, `impact` | S3 | 위와 같음 | 위와 같음 |
| `verify-relation`, `verify-impact` | S3 | 네이티브 TypeSafe Jev `POST {TYPESAFE_BASE_URL}/systemone`, 모델 정확히 `jev-1.14.0` | 인용문 텍스트와 고정 사실만 보내는 Choice 질문(문서 본문·내부 id는 보내지 않는다) |

provider는 stage가 정한다. endpoint나 모델 이름에서 권한을 추론하지 않는다. 생성 JSON schema는 기존 Pydantic 계약에서 만들되 OpenAI strict 제약에 맞게(모든 속성 required, 추가 속성 금지, 검증 키워드 제거, 인용 `start`/`end`는 null 허용) 변환한다. 검증 키워드를 뺀 만큼 **디코딩 뒤 기존 native 계약 검증이 그대로 소유**하고 응답은 보정하지 않는다. 모델이 문자 위치를 세지 않도록 인용 offset은 null로 받고, 소유자가 `live_prompts.resolve_citations`(유일한 literal quote에서만 offset 채움)로 채운 뒤 기존 정확 인용 검사를 한다.

### 10.2 환경변수 (프로세스 환경만, dotenv 없음)

| 구분 | 이름 | 필수 시점 | 값 |
|---|---|---|---|
| gate | `ZOOP_AI_PIPELINE_LIVE_ENABLED` | 모든 live 동작 | 정확히 `1` (S1의 `ZOOP_AI_LIVE_ENABLED`와 별개) |
| 비밀 아님 | `ZOOP_AI_PIPELINE_LIVE_MODEL` | freeze 이상 | `gpt-6-luna`만(요금이 알려진 모델) |
| 비밀 아님 | `ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT` | freeze 이상 | `none/low/medium/high/xhigh/max`, 기본값 없음(승인된 값은 `high`) |
| 비밀 아님 | `TYPESAFE_VALIDATION_MODEL` | freeze 이상 | 정확히 `jev-1.14.0` |
| 비밀 아님, 선택 | `ZOOP_AI_BASE_URL`, `TYPESAFE_BASE_URL` | | https(loopback만 http), userinfo·query 없음, `/systemone` 붙이지 않음. 기본 `https://api.openai.com/v1`, `https://api.typesafe.ai/v1` |
| 비밀 아님, 선택 | `ZOOP_AI_PIPELINE_LIVE_MAX_OUTPUT_TOKENS`, `…_TIMEOUT_SECONDS` | | 기본 24000(1000–100000), 300초(10–900). 출력 상한은 binding에 고정된다 |
| 비밀 아님 | `ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR` | freeze 이상(binding에 hash로 고정) | 절대 경로. S2·S3·submit·resume이 **같은 값**을 쓴다. 바꾸면 고정된 job이 거절된다 |
| send 시점 | `ZOOP_AI_PIPELINE_LIVE_MAX_USD`, `…_MAX_CALLS` | 첫 실제 send | 양의 십진수 USD(소수 9자리까지), 양의 정수 |
| 비밀 | `ZOOP_AI_API_KEY`, `TYPESAFE_API_KEY` | 첫 실제 send(자기 provider 것만) | `OPENAI_API_KEY`는 읽지 않는다 |

- `LiveRuntime.from_env()`는 gate와 비밀 아님 설정만 검증하고 **`BUDGET_DIR`(절대 경로)를 freeze 때 필수로 고정**한다(어떤 디렉터리도 만들지 않고 realpath의 hash만 계산한다). **키와 상한(`MAX_USD`·`MAX_CALLS`)이 없어도** freeze, `binding()`, `accepts()`, `prepare()`, `answer()`가 되고 어떤 파일도 쓰지 않는다. 키·상한은 `send()`에서만 필요하며 없거나 형식이 틀리면 예약·소켓 전에 확정 실패한다(`live_api_key_required`, `live_typesafe_key_required`, `live_budget_config_invalid`). 값은 오류 문구에 나오지 않는다. 한 provider 키가 없어도 다른 provider stage는 자기 키로 동작한다.
- 서비스 child 환경은 submit/freeze child에는 gate와 비밀 아님 설정만, send할 수 있는 resume child에만 키·예산 변수를 넘긴다. replay·graph·handoff·dependency·ingestion child에는 넘기지 않는다(전달 목록은 서비스 문서가 정한다).
- HTTP client는 환경 proxy를 **따르지 않고**(`trust_env=False`) redirect를 따르지 않으며 재시도하지 않는다. 키는 해당 provider로 가는 요청의 `Authorization` 헤더에만 들어간다.

오프라인 점검(네트워크 없음, 파일 생성 없음, 키는 있음/없음만):

```sh
python -m zoop_ai_pipeline.live_runtime binding [pipeline|issue-summary]   # 비밀 아님 설정 검증 + binding·identity·stage별 recipient/purpose (family 생략 = pipeline)
python -m zoop_ai_pipeline.live_runtime check [pipeline|issue-summary]     # 위 + 예산 변수와 두 키 필요
```

### 10.3 고정(binding)과 권한

`binding()`은 비밀 없는 정규 JSON으로 `version`, `generation`(endpoint·`endpointRevision`·모델·effort·출력 상한), `verifier`(endpoint·revision·모델·질문/임계치 identity), `stages`(stage별 `purpose`·`recipient`·`promptVersion`·`schemaDigest` 또는 `questionsDigest`), `pricing`, `budget{scope:"directory",directoryIdentity,unit}`, `limits`, `identity`를 담는다. `budget.directoryIdentity`는 검증된 절대 `BUDGET_DIR`의 realpath hash이며 경로 문자열은 담지 않는다. **상한(USD·호출 수)과 timeout은 의도적으로 제외**한다(상한은 줄일 수만 있고 같은 디렉터리 안에서만 의미가 있다). 소유자(S2/S3)는 이 값을 job에 그대로 고정하고, 새 호출 전에 `accepts(frozen)`로 현재 설정(예산 디렉터리 포함)이 같음을 확인하며, 저장된 receipt 복구는 `LiveRuntime.from_binding(frozen)`(환경·키 없이 decode/prepare만, send는 `live_send_unavailable`)을 쓴다.

- `recipient(stage)`: 생성 stage `openai-compatible:<revision>`, 검증 stage `typesafe-native:<revision>`. revision은 S1과 같은 식(`sha256({"endpoint": url})`, 네이티브는 `{"api":"systemone","endpoint": url}`)이라 URL 끝 `/`만 정규화된다. `purpose(stage)`는 `pipeline:<stage>`다. 생성 recipient가 Jev 전송을 허가하지 않는다. 권한 판정(grant 현재 revision·read/quote-display/model-send·만료)은 소유자 S2의 Authority가 하며 이 런타임은 `authorize()` 콜백을 **소켓 직전**에 부를 뿐 권한을 추론하지 않는다.
- 바깥으로 나가는 생성 요청은 별도로 고정된 정제 projection이다. Article의 `url`·`publisher`·`origin_id`·`withdrawn`·`synthetic`·`allow_model_send`, job id·grant·키·검토 메모는 포함하지 않으며 `Article.allow_model_send`가 권한을 만들지도 않는다. 프롬프트·schema·질문 문구·임계치를 바꾸면 identity가 달라진다.

### 10.4 한 번의 호출과 receipt (소유자 순서)

`prepare`(순수) → 소유자가 권한·고정 설정 재확인 → 소유자가 자기 attempt를 **먼저 durable 예약** → `send(prepared, attempt_id, authorize)` → 소유자가 **파싱 전에** receipt를 저장 → `answer(stage, receipt)` → 소유자의 정확 인용·계약 검증 → 권한 재확인 후 저장. `send`는 공유 예산을 예약하고 `authorize()`를 부른 뒤 **정확히 한 번** 보낸다. 어떤 HTTP 응답이든(비 2xx·형식 불량 포함) receipt를 돌려주며, receipt는 JSON이고 `format`, `stage`, `attemptId`, `recipient`, `purpose`, `bindingIdentity`, `requestDigest`, `http{status,contentType,bodySha256,bodyText,truncated}`, `model{requested,reported}`, `usage`, `cost{currency,tier,usageKnown,settled,estimatedUsd,chargedUsd,reservedUsd}`, `expect`를 가진다. `answer`·`usage`는 **receipt만** 읽으므로 키·환경이 달라져도 복구된다. 응답 본문은 8 MiB까지만 읽고 넘으면 `truncated` receipt가 된다. 같은 `attempt_id`는 예산 DB에서 유일하다(S2·S3·모든 프로세스). 한 번 쓰인 id는 예약이 풀려도 다시 쓰이지 않는다.

| 코드 | 종류(`kind`) | uncertain | 시점·뜻 |
|---|---|---|---|
| `live_response_unknown` | unavailable | **true** | 전송 오류·timeout·끊김. 예약은 최악 비용으로 남고 재송신 없음 |
| `live_http_<status>` | unavailable | false | `answer`에서. 비 2xx(429·5xx 포함, 자동 재시도 없음) |
| `live_reply_not_json`, `live_answers_invalid`, `live_model_mismatch`, `live_output_truncated`, `live_response_oversize`, `live_receipt_invalid` | invalid | false | `answer`에서. 계약 위반·잘림. 보정·재요청 없음 |
| `live_model_refusal` | refused | false | 모델 거절·content filter |
| `live_budget_exhausted_usd/_calls`, `live_budget_attempt_duplicate`, `live_budget_ceiling_increase`, `live_budget_unavailable` | budget | false | 소켓 전 확정 실패 |
| `live_config_changed` | config | false | send 시점의 예산 경로 realpath가 binding에 고정된 것과 다름. 소켓 전 확정 실패 |
| `live_not_enabled`, `live_model_unsupported`, `live_reasoning_effort_invalid`, `live_jev_model_unsupported`, `live_endpoint_invalid`, `live_limit_invalid`, `live_budget_config_invalid`, `live_api_key_required`, `live_typesafe_key_required`, `live_stage_unsupported`, `live_payload_invalid`, `live_request_too_large`, `live_binding_mismatch`, `live_prepared_invalid`, `live_send_unavailable` | config | false | 소켓 전 확정 실패 |

`authorize()`가 예외를 내면 아무것도 보내지 않고 예산 예약을 풀며 **그 예외를 그대로** 올린다. 요청 크기 상한은 생성 300,000 B, Jev 150,000 B이며 넘으면 자르지 않고 `live_request_too_large`다.

### 10.5 예산 (USD와 호출 수, 전 stage 공유)

SQLite 한 파일(`<budget dir>/live-budget.sqlite3`, 디렉터리 0700·파일 0600)에 예약을 남긴다. 금액은 정수 nano-USD로만 다룬다(float 없음). 단가 출처(2026-10-21 확인): OpenAI `gpt-6-luna` 표준 입력 0.10/출력 0.50 USD per 1M(≤272k), 0.20/0.75(초과) — <https://developers.openai.com/api/docs/pricing>; Jev 1.14 입력 0.042 USD per 1M, 출력 무료 — <https://docs.typesafe.ai/models.md>.

- 예약은 **항상 보수적 long 단가(입력 0.20·출력 0.75)**, 캐시 할인 없음, 입력 상한 = 요청 바이트 수 + 1024 토큰(토큰은 최소 1바이트), 출력 상한 = 설정된 `max_completion_tokens`(추론 포함). **Jev**는 공유 `state`의 과금 횟수가 문서화되어 있지 않으므로 입력 상한을 `요청 바이트 × 질문 수 + 1024`로 잡아 질문마다 전체 요청이 과금되는 최악을 덮는다. 이 값은 청구서 보증이 아니라 **상한 추정**이다.
- 정산은 **2xx 응답에 유효한 usage가 있을 때만** 최악 비용을 실제값(같은 보수 단가)으로 낮춘다. usage는 `[0, 100,000,000]` 정수일 때만 유효하고(bool·float·음수·초과는 블록 전체가 unknown) 그 밖에는 **최악 비용을 유지한다**(조용한 0원 없음). **비 2xx는 본문이 `usage` 0이나 그럴듯한 값을 담아도 항상 최악 비용을 유지**하고, 보고된 값은 receipt에 관찰값으로만 남는다. **요청 상한을 넘는 usage도 측정값으로 쓰지 않는다**(제3자 응답 검증이며 비용 정책 변경이 아니다): 보고된 입력이 예약의 입력 상한(Jev는 질문별 보수 상한)을, 출력이 설정된 `max_completion_tokens`를, cached가 입력을, reasoning이 출력을 넘으면 정산하지 않고 최악 비용을 유지하며 receipt에 `cost.usageRejected`(`input_exceeds_bound` 등)를 표시한다. 보고된 원값은 `usage`와 원문 본문에 그대로 남고 소유자가 receipt를 저장한 **뒤** `answer`가 `live_receipt_invalid`를 낸다. 상한 이하의 유효한 usage는 그대로 더 낮게 정산된다. 정산 자체가 실패하면(DB·overflow 등) 최악 비용이 그대로 남고 receipt가 `cost.settled=false`로 표시되며 `answer`가 같은 방식으로 `live_receipt_invalid`를 낸다. 응답을 받은 뒤의 어떤 파싱·usage·정산 실패도 받은 본문을 잃게 하지 않는다(깊이 중첩 JSON도 `RecursionError` 없이 raw receipt가 되고 `answer`만 `live_reply_not_json`).
- 전송 오류·timeout·프로세스 사망은 `reserved` 상태로 최악 비용과 호출 1회를 영구히 센다. 예약을 재사용해 다시 보내지 않는다. 소켓 전에 거절된 예약만 해제(0원, 호출 수 미포함)된다.
- 예산은 **디렉터리 identity(검증된 절대 realpath의 hash)**로 binding에 고정된다. 상한(USD·호출 수)은 binding 밖이며 첫 사용 때 그 디렉터리에 묶이고 **줄이기만** 할 수 있다(`live_budget_ceiling_increase`). 거절된 예약이어도 **줄어든 상한은 저장된다**(트랜잭션이 거절에서도 commit). `BEGIN IMMEDIATE` 트랜잭션이라 여러 스레드·프로세스·S2/S3가 같은 상한을 넘기지 못하고, 경쟁하는 핸들은 가장 낮은 상한으로 수렴한다.
- **신뢰 경계(운영)**: 예산 DB 파일은 같은 호스트에서 그 디렉터리를 쓸 수 있는 소유자·특권 사용자가 지우거나 바꿀 수 있고, 이 런타임은 그것을 막지 못한다(변조 방지가 아니다). `BUDGET_DIR`를 바꾸면 identity가 달라져 고정된 job이 `accepts` 실패(또는 send의 `live_binding_mismatch`)로 막히고, 경로가 freeze 뒤 다른 곳(symlink 교체 등)을 가리키면 send가 `live_config_changed`로 소켓 전에 멈춘다. 파일 자체를 지우는 것은 별도의 운영 신뢰 경계다.

### 10.6 Jev 검증 정책 (잠정, 미보정)

S1과 같은 임계치(승리 확률 ≥ 0.90 **그리고** confidence ≥ 0.80)를 **잠정값**으로 쓴다. `verify-relation`은 요청된 claim마다 Choice 하나(`supported`/`contradicted`/`insufficient`, `direction`·`step:N`만 `reversed` 추가)를 묻고, 각 질문 문구가 claim의 전체 의미와 판단에 쓸 인용(Q1…)을 담는다. 이 adapter는 Jev에게 **인용 선택을 묻지 않는다**: 이는 Jev의 능력 한계가 아니라 설계 선택이다(알려진 허용 인용 id에 대한 typed 질문으로 선택을 물을 수도 있다). 그래서 `supported`는 그 claim의 허용 인용 **전체를 함께 판정한 결과**이고 `quoteIds`는 그 허용 집합 전체다. `verify-impact`는 target 하나(`supported`/`contradicted`/`insufficient`)와 인용별 효과 Choice(`positive`/`negative`/`neutral`/**`uncertain`**, 가격 예측 아님)를 묻는다. `uncertain`의 기준은 "효과가 섞여 있거나 판단할 수 없거나 이 회사에 대한 충분한 근거가 없음"이며 방향을 추측하지 말라고 질문에 명시한다. 확률·confidence가 낮으면 claim·target은 `insufficient`(HOLD)가 되고 **거부로 가지 않는다**. 인용 효과는 모델이 `uncertain`을 고르면 확률과 무관하게 항상 `uncertain`, `positive`/`negative`/`neutral`을 고르고도 임계치를 못 넘으면 역시 `uncertain`이다(검증된 `neutral`로 바꾸지 않는다). 소유자의 impact gate는 `uncertain` 인용이 하나라도 있으면 다른 인용이 확신 있는 positive/negative여도 라벨 없이 `undetermined`(`quote_effect_uncertain`)로 처리한다(target 판정 의미는 유지, `contradicted`는 그대로 reject). 분포와 생성된 정책 노트는 `runtime.audit(stage, receipt)`와 원문 receipt에 남는다. 합성 문서 실호출이 HOLD로 끝나는 것은 정상이며 임계치를 낮춰 통과시키지 않는다.

### 10.7 smoke 활성화와 안전한 실패

실호출 smoke는 Main이 승인한 예산(합성 문서, 총 USD 10, `gpt-6-luna`/`high`, `jev-1.14.0`)에서만 한 프로세스 환경에 아래를 넣고 실행한다. 키는 셸/secret store에서 주입하며 파일·로그·채팅에 쓰지 않는다.

```sh
export ZOOP_AI_PIPELINE_LIVE_ENABLED=1 ZOOP_AI_PIPELINE_LIVE_MODEL=gpt-6-luna ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT=high \
       TYPESAFE_VALIDATION_MODEL=jev-1.14.0 \
       ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR=/abs/new/budget-dir ZOOP_AI_PIPELINE_LIVE_MAX_USD=10 ZOOP_AI_PIPELINE_LIVE_MAX_CALLS=<modest cap>   # BUDGET_DIR는 submit(freeze) 때도 같은 값이어야 한다
# + ZOOP_AI_API_KEY, TYPESAFE_API_KEY (주입만, 여기에 값을 쓰지 않는다)
python -m zoop_ai_pipeline.live_runtime check      # 오프라인: 설정·키 존재만 확인, 어떤 요청도 보내지 않는다
```

- 하나라도 빠지면 `check`와 실제 send가 소켓 전에 위 코드로 멈춘다. gate가 `1`이 아니면 어떤 live 동작도 시작하지 않는다.
- 호출이 실패해도 자동 재시도·fallback·다른 모델 전환이 없다. 불확실 호출은 같은 attempt로 다시 보내지 않고 소유자의 reconciling 상태로 남는다. 예산 디렉터리를 새로 만들지 않으면 상한을 늘릴 수 없다.
- 알려진 한계: 보수 단가와 실제 청구의 차이, Jev의 `state` 과금 횟수, 계정 한도는 확인되지 않았다(§10.8의 한 번의 합성 실행은 estimated USD만 기록했다). OpenAI strict schema가 일부 구조를 거절하면 그 stage는 400(`live_http_400`)으로 끝난다(자동 보정 없음). 한국어 금융 평가셋으로 보정한 임계치가 아니다.

### 10.8 실제 호출 검증 기록과 `live_graph_smoke.py` (2026-10-21, Main 실행)

**실행 명령.** 운영자 smoke는 `ai/pipeline/scripts/live_graph_smoke.py`다. 스케줄러·수집기·게시기가 아니며, `--live`·환경 gate·**새** 출력 루트·유한한 예산(승인 총액 이하)이 모두 있어야만 지출한다. 키·gate가 필요하며 어느 것도 파일·출력에 쓰지 않는다. 출력 루트는 새 절대 실경로여야 하고 상위에 symlink가 없어야 한다(macOS는 `/tmp`가 아니라 `/private/tmp/...`).

```sh
# 지출 없음·파일 생성 없음·모델 호출 없음: 설정·endpoint·console script·Neo4j 대상(읽기 전용 preflight)을 검증하고 계획을 출력한다
.venv/bin/python scripts/live_graph_smoke.py --check --output-root /real/abs/new-dir --graph-uri bolt://127.0.0.1:7687 --usd-cap 10
# 유료 실행(승인된 총액 이하의 예산, 비어 있는 전용 Neo4j 5 database)
.venv/bin/python scripts/live_graph_smoke.py --live  --output-root /real/abs/new-dir --graph-uri bolt://127.0.0.1:7687 --usd-cap 10 [--exercise-manual-approval]
```

`--live` 없이(`--check`도 아니면) 실행은 `live_flag_required_for_a_paid_run`으로 거절된다. `--exercise-manual-approval`은 **진짜** Jev HOLD가 결정적 gate를 통과한 경우에만 합성 테스트 운영자의 `allow` 하나를 제출하고(모델 호출 추가 없음) 그렇지 않으면 coverage gap으로 보고한다.

**한 번의 실제 실행(`ai/pipeline/var/live-graph-2026-10-21-01/summary.json`에 보존, 이 문서는 그 요약의 사람이 읽는 사본이다).**

| 항목 | 관찰값 |
|---|---|
| 상태 | `passed`, 벽시계 135.2초 |
| 입력 | **합성** 문서 2건(카탈로그·이전 event snapshot은 운영자 seed, 모델 답이 아님) |
| 모델 | 실제 `gpt-6-luna`(reasoning `high`) 9회 + 실제 `jev-1.14.0` 5회 = 14회, endpoint는 `api.openai.com`·`api.typesafe.ai` |
| S2 | event 후보 5, topic 후보 1(비교 5건 모두 `DIFFERENT`) |
| S3 | 관계 후보 4: 자동 `eligible` 1 · `HOLD` 3 · `REJECT` 0(impact 후보 1개는 `undetermined`) |
| 수동 승인 | **합성 테스트 운영자**(사람 아님)가 실제 HOLD 하나를 `allow`, 모델 호출 추가 0, 승인 뒤 `eligible` 2 |
| 그래프 | 로컬 Neo4j(5.26 community, 빈 대상)에 append-only version 두 개를 투영: 자동 version(노드 2·edge 1, 자동 승인 1)과 수동 승인 version(노드 3·edge 2, 자동 1 + operator-final 1) |
| 비용 | 추정 USD **0.013323880**(보수 long 단가 기준 **상한 추정이며 청구서가 아니다**), 승인 상한 USD 10 · 호출 40, 14회 모두 `settled`, 미확인(unknown) 호출 없음 |

이 표의 수치는 보존된 `summary.json`의 값이다. 세부 수치는 `stages.graph`·`stages.s2`·`stages.s3`에서 읽는다.

**이 기록이 증명하는 것과 증명하지 않는 것.**

- 증명: 합성 문서에 대해 S2·S3 live 경로(`gpt-6-luna`/`high`, `jev-1.14.0`)가 한 번 끝까지 동작했고, receipt·공유 예산·수동 승인·Neo4j 투영이 이어졌다. 이 한 번의 실행에서 OpenAI strict schema와 Jev 질문 형식이 받아들여졌다.
- 증명하지 않음: 실제 뉴스·운영 데이터에서의 품질, Jev 임계치의 보정(여전히 잠정), 청구서와 보수 추정의 일치(계정 대시보드와 비교한 적 없음), Jev의 공유 `state` 과금 횟수, 반복 실행의 안정성. 수동 승인은 사람이 한 것이 아니다.
- **S1 worker의 유료 실행은 이 기록에 포함되지 않으며 검증되었다고 주장하지 않는다**(§7의 S1 smoke는 별개의 승인 대상이다).

### 10.9 이슈 요약 family (`ISSUE_SUMMARY`, 구현됨, 기본 꺼짐, 호출 승인 아님)

이슈 요약은 PIPELINE binding에 stage를 더하지 않고 **별도 family**로 둔다. 저장된 receipt를 decode할 때 `from_binding`이 binding 전체의 일치를 요구하므로 전역 stage 목록에 하나만 더해도 기존 live job을 복구할 수 없게 되기 때문이다. family는 `live_family.py`의 값 타입(`Family`, `Verifier`)이고 `LiveRuntime(..., family=PIPELINE)`가 기본값이다. `from_binding`은 binding의 `version`으로 family를 고르며 모르는 version은 `live_binding_mismatch`다.

| 항목 | 값 |
|---|---|
| binding `version` | `zoop-issue-summary-runtime-1` (PIPELINE은 `zoop-live-runtime-1` 그대로) |
| 생성 stage | `issue-summary`: OpenAI 호환 `chat/completions`, `gpt-6-luna`, strict `json_schema` `{"claims":[{"text","quoteIds"}]}`. 제목(검증되지 않은 라벨, 근거 아님)과 인용문만 `q1…qN` 라벨로 보내며 내부 evidence·기사·문서 id, mention 필드, 시간 값, verdict는 보내지 않는다 (`issue_summary_prompts.py`) |
| 검증 stage | `verify-issue-summary`: 네이티브 Jev `POST {TYPESAFE_BASE_URL}/systemone`, `jev-1.14.0`. 인용된 quote만 `context`(`report`/`background`)와 함께 보낸다. claim마다 Choice 하나(자기 인용문만으로 `supported`/`contradicted`/`insufficient`), 전체에 대해 투자 조언·근거 없는 인과·시간 틀(`background`만 있는 사건을 새것·현재로 제시했는가) Choice 셋(`absent`/`present`). 임계치는 §10.6과 같은 잠정값(미보정) (`issue_summary_jev.py`) |
| purpose | `pipeline:issue-summary`, `pipeline:verify-issue-summary` |
| recipient | 식이 PIPELINE과 같아 생성은 `openai-compatible:<revision>`, 검증은 `typesafe-native:<revision>` 문자열이 같다 |
| 환경 | **같은 변수·같은 `.env`**(§10.2). 새 변수 없음. family는 환경이 아니라 코드 인자(`from_env(family=ISSUE_SUMMARY)`)와 위 CLI 인자로 고른다 |

- **판정 매핑**: 모든 claim이 `supported`이고 세 검사(`prohibitedAdvice`, `unsupportedCausality`, `backgroundAsCurrent`)가 모두 `absent`일 때만 `available`. `contradicted` claim 또는 `present`는 `verifier-reject`(hold보다 우선), 그 밖은 `verifier-hold`다. 확률·confidence가 임계치 미만이면 claim은 `insufficient`, 세 검사는 `uncertain`이라 hold이며 reject가 되지 않는다. 생성 reply는 `issue_summary_prompts.claims_from`만이 claim으로 바꾸며(1~5개, claim당 280 code point 이하·한글 음절 포함·인용 1~5개), 어긋나면 보정 없이 `producer-invalid`다.
- **`background` 시간 틀**: 생성 prompt는 `background` 인용을 새 사건으로 쓰지 말라고 지시하고, 검증기는 각 인용의 context를 받아 `background`만으로는 사건이 새것·현재임을 보이지 못한다는 기준으로 claim과 시간 틀 검사(`framing`)를 묻는다. 시간 틀이 어긋난 것으로 판정되면(`present`) 게이트가 `verifier-reject`로 막는다. 이 판단은 Jev가 하며(결정적 규칙이 아님) 정확도는 보정되지 않았다. 합성 시험은 요청에 보이는 context로 저작한 판정을 내는 가짜 transport로 게이트 동작만 확인한다.
- **PIPELINE 불변 증거**: 기본 family의 binding 바이트·identity·stage별 digest와 일곱 stage의 `prepare` digest를 family 도입 **전** 코드에서 떠서 고정 리터럴로 `ai/pipeline/tests/test_live_families.py`에 넣었다(예산 identity를 고정한 생성자 기준이라 경로와 무관). 리팩터 후 같은 값이 나오는 것을 확인했다. 로컬에 보관된 실제 `live-20261021…` binding으로 `from_binding`을 해 본 것은 아니다.
- **증거 수준**: 요청 빌더·reply 매핑·판정·family 경계는 합성 `httpx.MockTransport` 시험으로 확인했다. `ai/pipeline/scripts/issue_summary_smoke.py`는 실제 CLI·원장·런타임과 loopback 모의 provider로 응답 유실·중단 복구·권한 철회·예산 소진을 확인한다. live 시험에서 원천 Planner만 대체하며, 실제 Planner 연결은 같은 스크립트의 replay 경로에서 검증한다. 이슈 요약의 **실제 유료 호출은 한 번도 하지 않았다**. 실제 모델 품질과 임계치 보정은 검증되지 않았다.
- **승인과 예산은 여전히 필요**: 2026-10-21의 USD 10 승인은 그 합성 시험 범위였고 이슈 요약으로 확장되지 않는다. 같은 변수를 쓴다고 승인된 것이 아니다. 실제 호출 전에는 새 명시 승인(대상, 이슈 수 N, 최대 호출 수 2N(생성 1·검증 1), `MAX_USD`)과 **새 예산 디렉터리**(상한은 같은 디렉터리 안에서 줄일 수만 있다, §10.5)가 필요하고, 소스 grant의 `purposes`에 위 두 purpose가 명시적으로 허용되어야 한다(이 문서는 grant를 바꾸지 않는다).
