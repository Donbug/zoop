# 문서 분석 (등록된 문서 → S1 AI 분석 → PostgreSQL)

[문서 import](DOCUMENT_IMPORT.md)가 등록한 문서 버전 한 건을 S1 AI 서비스(`ai/service`, 계약 `zoop-ai-s1-1`)로 요약(`document-summary`) 또는 기업 판정(`document-sentiment`)하고, 검증을 통과한 결과를 앱 DB의 `document_analyses`·`evidence`·`ai_executions`(ERD v6 §17·§18·§32)와 로컬 artifact 파일에 저장합니다. 분석 실행은 운영자가 실행하는 **비웹 Spring 프로세스**이며 HTTP 경로가 없습니다. 저장된 요약의 본문 인용을 읽는 공개 경로는 `getEvidence` 한 건만 있고([근거 읽기](#근거-읽기-getevidence-부분-구현), 부분 구현) 분석을 읽는 다른 공개 API는 없습니다.

**하지 않는 것:** `getEvidence` 외의 공개·관리자 경로(`listCompanyDocuments`, `getAiUsage` 등 읽기; `getEvidence`는 그래프 없이 부분 응답만), `analysis_jobs`(공개 관리자 작업)와 그 FK, 그래프(GraphDB) 반영, 취소·포기, 챗봇·브리핑 실행 기록, 요약 텍스트 artifact(`summary_text`)와 요약을 입력으로 하는 근거, 보존·삭제, **live 모드 실행**. `status=available`은 “생성·검증·수입이 끝난 이력”이지 **공개 허가가 아닙니다**([권리](#권리)).

## 흐름

명령은 둘이고, 한 요청은 한 명령의 1~100개 항목을 순서대로 처리하며 **첫 실패에서 멈춥니다**(앞 항목은 이미 커밋, 뒤 항목은 `not_attempted`). 대기(`pending`)는 성공이며 같은 항목을 다시 `advance` 하면 됩니다.

### `prepare` — 예약 (AI 서비스를 부르지 않습니다)

1. 문서 import와 같은 **새 S2-1 export**(`--require-store`)와 같은 엄격 검증. 추가로 `rawLocators`가 1개 이상이고, id가 유일하며, `0 <= start < end <= 텍스트의 코드 포인트 수`여야 합니다.
2. 등록된 article·버전과 `companies`를 잠금 없이 읽고, 운영자의 **flat S1 grant registry**를 새로 읽어 판정합니다([권리](#권리)).
3. 불변 요청(`Submit`)을 만듭니다. AI job id는 `s1-` + 랜덤 32 hex이며 **이때 한 번 발급**되고 바뀌지 않습니다. 같은 범위에 `available` 행이 있고 그 요청(jobId 제외)이 같으면 `analysis_unchanged`입니다(워커 캐시가 같은 `result_version`을 돌려주는데 ERD는 이를 한 번만 허용). 직렬화한 정준 JSON이 2,000,000바이트를 넘으면 `request_too_large`입니다.
4. `ai_submit` 파일을 씁니다(`<artifact-root>/ai_submit/submit-<aiJobId>.json`, 0600, 항상 새 이름).
5. **DB transaction 한 번**: article 잠금(`available`이어야 함) → 버전의 텍스트 artifact가 export 텍스트와 sha256·bytes가 같은지 → 기업 이름이 고정한 이름과 같은지 → 범위의 **최신 행 compare-and-set** → `ai_submit` artifact 행 → `document_analyses` pending 행. 어긋나면 전부 롤백하고 이 항목이 만든 파일을 지웁니다.

이 시점까지 AI 서비스 호출은 0건입니다. submit 바이트는 오직 이 artifact에서만 나옵니다.

### `advance` — 진행과 정산

1. 행을 읽습니다. pending이 아니면 `already_settled`(성공, HTTP 없음).
2. 저장된 `ai_submit`을 **검증된 읽기**(정규 파일·소유자·0600·크기·sha256)로 읽고 행과 결속되는지 확인합니다.
3. **status를 먼저** 읽습니다(읽기는 항상 허용). 서비스에 일을 시키는 요청은 둘뿐입니다: `404 job_not_found`일 때의 submit과 `/recover` 호출. 이 둘 **직전에 앱이 현재 권한을 다시 읽습니다**: article이 지금 `available`이고 operator의 flat registry(방금 읽은 현재 파일)가 prepare와 같은 규칙으로 이 사용을 허용해야 합니다. 거부면 `grant_denied`(`grantCode`)·`article_access_unavailable`로 실패하고 요청을 보내지 않으며 분석은 pending으로 남습니다(서비스가 읽는 사본이 아직 허용해도 같습니다). 허용되면 저장된 바이트를 **같은 jobId로** submit합니다. submit 응답이 불명이면(`requestMaybeProcessed`) `submit_outcome_unknown`이며 아무것도 쓰지 않고, 다음 `advance`가 status를 읽습니다. 한 번 status가 200이면 다시 submit하지 않습니다. 새 jobId는 만들지 않습니다.
4. 서비스의 `next`를 따릅니다: `wait` → pending. `recover` → 요청 항목에 `"recover": true`가 있을 때만 `/recover`를 호출(없으면 `recover_required`). `operator_reconcile` → `operator_reconcile_required`로 멈춤. `none`(실패·취소) 또는 `fetch_result`(준비 완료)에서 `unreceiptedAttempts > 0`이면 `receipts_incomplete`(pending), 아니면 result를 읽어 정산합니다.
5. 정산은 **짧은 transaction 한 번**(모델 호출 없음)입니다: article 잠금 → 분석 행 잠금을 **얻은 뒤** 앱이 현재 grant registry를 다시 읽어 `available` 후보를 재평가하고(거부면 같은 transaction에서 `withheld`로 낮춤), 행 업데이트, artifact 행(낮춘 경우 호출 영수증만), 호출 영수증별 `ai_executions`, (요약이면) `evidence`를 씁니다.

## 정산 결과

| 상태 | 언제 | 저장 |
|---|---|---|
| `available` | 서비스 delivery가 `available`이고 아래 [검증](#결과-검증)·앱 자체 grant 재평가·article 상태가 모두 통과 | 결과 DTO, 결과·검증자·exact 영수증 artifact, 호출 영수증, `ai_executions`, (요약) `evidence` |
| `withheld` | 서비스가 delivery를 막음(`reason` = 서비스 코드) · 앱 grant 재평가 거부(결과를 읽은 뒤, **그리고 article·행 잠금을 얻은 뒤 한 번 더**) · 검증자가 `hold`/`reject`(`semantic_hold`/`semantic_reject`) · 내용 게이트 실패(검증자가 본 claim ≠ 답의 claim 포함) · article이 더는 `available`이 아님 | **내용 artifact와 결과는 저장하지 않습니다.** 호출 영수증과 `ai_executions`는 저장 |
| `failed` | 서비스 job이 `failed`/`cancelled`(`reason` = `failure.code` 또는 `cancelled`), 또는 submit이 422·413으로 거부됨(아무것도 등록되지 않았으므로 영수증 없음) | 영수증·`ai_executions`(있을 때) |
| (쓰지 않음) | 결과가 이 분석의 답이라고 증명되지 않음: 되돌려 준 입력이 저장된 submit과 다름, artifact 생성자를 알 수 없음, 영수증이 payload와 다름, 이미 있는 행·artifact가 다름, `result_version` 충돌 | 아무것도 쓰지 않고 분석은 pending으로 남음. 운영자 조사 대상 |

한 번 terminal이 된 행은 `revoked_at`·`updated_at` 외에 바꿀 수 없습니다(트리거). 다시 분석하려면 **명시적 재요청**(새 `request_no`)입니다. 같은 입력의 재요청은 `withheld` 뒤라면 같은 grant revision에서 워커 캐시가 같은 결과를 돌려줍니다.

## 실행

기본은 비활성이고 평소 기동에는 아무 설정도 필요하지 않습니다. 활성화하면 값을 시작 시 검증하고 틀리면 기동이 닫힘 실패합니다(메시지에는 설정 이름만, 값은 없음). **웹 서버와 함께는 시작을 거부**하고, **문서 import와 같은 프로세스에서 함께 켜면 거부**하며, **S1 AI 클라이언트가 없으면 거부**합니다.

| 환경 변수 | 용도 |
|---|---|
| `ZOOP_DOCUMENT_ANALYSIS_ENABLED` | `true`일 때만 동작(기본 `false`). `--spring.main.web-application-type=none` 필수 |
| `ZOOP_DOCUMENT_ANALYSIS_REQUEST` | 운영자 요청 JSON(존재하는 파일, 최대 1 MiB) |
| `ZOOP_DOCUMENT_ANALYSIS_RESULT` | 결과 파일. **없어야 하며** 시작 때 배타적으로 만들어집니다 |
| `ZOOP_DOCUMENT_ANALYSIS_GRANTS` | 운영자의 **flat S1 grant registry**(`zoop-ai-s1-1`). AI 서비스가 `ZOOP_AI_SERVICE_GRANTS`로 읽는 파일과 같은 형식이며 **앱이 따로 명시**합니다. 서비스가 읽는 사본과 다른 파일을 써도 되지만 서로 어긋나면 더 엄격한 쪽이 이깁니다 |
| `ZOOP_AI_CLIENT_ENABLED` `ZOOP_AI_CLIENT_BASE_URL` `ZOOP_AI_CLIENT_TOKEN` … | S1 클라이언트([AI 연동](AI_INTEGRATION.md#설정)). 토큰은 `analysis.submit`·`analysis.read`(필요하면 `analysis.recover`) scope |
| `ZOOP_INGESTION_CLI` `ZOOP_INGESTION_STATE_DIR` `ZOOP_INGESTION_SOURCES` `ZOOP_ARTIFACT_ROOT` | 문서 import와 같은 값과 같은 규칙([문서 import](DOCUMENT_IMPORT.md#실행)). 같은 artifact root를 공유하며 락 파일(`.document-import.lock`)이 **하나**라서 import와 분석, 분석끼리 동시에 실행되지 않습니다 |
| `DB_URL` `DB_USERNAME` `DB_PASSWORD` | 기존 DB 연결. 하위 CLI에는 전달되지 않습니다 |

요청·결과·grants 파일은 ingestion state 디렉터리 안에 둘 수 없습니다. 같은 JVM이 시작할 때 Flyway migration(`V20261014130000`)도 적용합니다.

```sh
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
./api/gradlew -p api assemble
env -i PATH=/usr/bin:/bin HOME="$HOME" DB_URL=… DB_USERNAME=… DB_PASSWORD=… \
  ZOOP_DOCUMENT_ANALYSIS_ENABLED=true ZOOP_DOCUMENT_ANALYSIS_REQUEST=/abs/request.json ZOOP_DOCUMENT_ANALYSIS_RESULT=/abs/result.json \
  ZOOP_DOCUMENT_ANALYSIS_GRANTS=/abs/grants.json \
  ZOOP_AI_CLIENT_ENABLED=true ZOOP_AI_CLIENT_BASE_URL=http://127.0.0.1:<port> ZOOP_AI_CLIENT_TOKEN=<발급 토큰> \
  ZOOP_INGESTION_CLI=/abs/zoop-ai-ingest ZOOP_INGESTION_STATE_DIR=/abs/ingestion-state ZOOP_INGESTION_SOURCES=/abs/sources.json \
  ZOOP_ARTIFACT_ROOT=/abs/artifacts \
  "$JAVA_HOME/bin/java" -jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --spring.main.web-application-type=none
```

종료 코드는 모든 항목이 성공(대기 포함)했을 때만 0입니다.

## 요청 (`zoop-document-analysis-1`)

```json
{"schemaVersion": "zoop-document-analysis-1", "command": "prepare",
 "items": [
  {"observation": {"roundId": "r1", "sourceId": "synthetic-source", "page": 0, "ordinal": 0,
                   "documentId": "doc-<64hex>", "rawVersion": "<64hex>", "documentVersion": "<64hex>"},
   "kind": "document-summary", "companyId": "SYNTH-A",
   "grant": {"grantId": "…", "revision": "…"},
   "mode": "replay", "sourceKind": "synthetic",
   "latest": {"expected": null}}
 ]}

{"schemaVersion": "zoop-document-analysis-1", "command": "advance",
 "items": [{"analysisId": "da-<32hex>", "recover": false}]}
```

- 닫힌 스키마입니다. 모르는 키·중복 키·잘못된 타입·범위 밖 값은 `request_invalid`이고 문서 텍스트·export·grant·결과를 실어 보낼 키는 **없습니다.**
- `companyId`는 운영자가 선언한 **기업 문맥**입니다. 문서·그래프·source grant에서 추론하지 않습니다. 이 값과 문서 버전이 승인 튜플이며 `ai_submit`에 얼려 둡니다(기업 이름은 `companies`에서 읽어 함께 얼림).
- `grant`는 flat registry의 `{grantId, revision}`이며 revision이 **정확히** 같아야 합니다. S2-1 export의 grant에서 유도하지 않습니다.
- `mode=replay`는 `sourceKind=synthetic`만 허용합니다(워커 규칙). `recordingKind`는 replay → `authored-test`, live → `provider`로 정해집니다.
- `latest.expected`는 같은 범위(article·버전·단계, 기업 판정은 기업까지)의 **가장 최신 행에 대한 compare-and-set**입니다. 첫 요청은 `null`, 재요청은 직전 행의 `analysisId`입니다. 일치하지 않으면 `latest_conflict`, 최신 행이 pending이면 `analysis_pending`입니다.
- `recover`는 생략하면 `false`이며 `/recover`를 부르는 유일한 방법입니다.

## 결과 (`zoop-document-analysis-1`)

시작할 때 `O_EXCL`로 예약하는 0600 파일이며 텍스트·경로·자격 증명·모델 출력이 없습니다. 중간에 죽으면 **빈 파일**로 남는데 결과를 모른다는 뜻입니다(새 결과 경로로 다시 실행하면 됩니다).

```json
{"schemaVersion":"zoop-document-analysis-1","command":"advance","status":"succeeded|failed",
 "items":[{"index":0,"status":"prepared","analysisId":"da-…","aiJobId":"s1-…","requestNo":1,"stage":"summary"},
          {"index":1,"status":"pending","analysisId":"da-…","aiJobId":"s1-…","waiting":"wait|receipts_incomplete|recovering"},
          {"index":2,"status":"settled","analysisId":"da-…","outcome":"available|withheld|failed","reason":null,
           "executions":{"recorded":2,"existing":0},"evidence":2},
          {"index":3,"status":"already_settled","analysisId":"da-…","outcome":"available","reason":null},
          {"index":4,"status":"failed","failure":{"code":"latest_conflict","latestAnalysisId":"da-…","latestStatus":"pending"}},
          {"index":5,"status":"not_attempted"}]}
```

요청 전체가 실패하면 `failure`가 최상위에 있습니다(`request_invalid`, `analysis_busy`, `grant_registry_unavailable` 등). 실패 `failure`에는 코드와, 식별자 토큰인 상세(`aiCode`, `grantCode`, `ingestionCode`, `detail`, `analysisId` 등)만 들어갑니다.

| 코드 | 의미 |
|---|---|
| `request_invalid` / `result_unavailable` / `analysis_busy` | 요청 형식 / 결과 파일을 만들 수 없음 / 다른 import·분석이 락을 잡고 있음 |
| `ingestion_export_failed` `ingestion_export_unavailable` `export_invalid` `identity_unsupported` `text_hash_mismatch` `text_encoding_invalid` `published_at_unsupported` `metadata_unsupported` | 문서 import와 같은 export 단계 코드 |
| `document_not_registered` `article_provider_conflict` `article_access_unavailable` `document_version_mismatch` | 등록되지 않은 문서 / provider가 export의 source와 다름 / `access_status`가 `available`이 아님 / 등록된 텍스트가 export와 다름 |
| `company_unknown` `company_context_changed` | `companies`에 없음 / 고정한 이름이 바뀜 |
| `grant_denied` | `grantCode`에 거부 사유(`source_rights_unknown_or_denied`, `grant_revision_or_source_changed`, `naver_search_ai_prohibited`, `source_grant_expired`, `source_grant_expiry_invalid`, `source_operation_denied`, `source_purpose_or_recipient_denied`) |
| `grant_registry_unavailable` | `registry`에 `grant_registry_unreadable` / `_too_large` / `_schema_invalid` / `grant_revision_conflict` |
| `request_too_large` `analysis_unchanged` `latest_conflict` `analysis_pending` | [prepare](#prepare--예약-ai-서비스를-부르지-않습니다) 참고 |
| `artifact_conflict` `artifact_file_conflict` `artifact_store_unavailable` | 이미 있는 artifact 행·파일이 다름(건드리지 않음) / 같은 이름·내용 불일치 / 저장소를 쓸 수 없음 |
| `analysis_unknown` `analysis_not_pending` `submit_artifact_invalid` | 없는 분석 / 정산 도중 이미 terminal / 저장된 submit이 행과 결속되지 않음 |
| `status_unavailable` `status_binding_invalid` | status를 읽지 못함(`aiCode`) / 다른 job·kind·mode의 응답 |
| `submit_outcome_unknown` `submit_conflict` `submit_refused` | submit 결과 불명(쓰지 않음, 다음 advance가 status부터) / `idempotency_conflict` / 그 밖의 거절(`aiCode`) |
| `recover_required` `recover_refused` `operator_reconcile_required` | `recover:true` 필요 / 서비스가 recover 거절 / 운영자 조사 필요(새 jobId로 우회하지 않음) |
| `ai_result_unavailable` `result_binding_invalid` `result_payload_invalid` `receipts_invalid` `artifact_creator_unknown` `text_artifact_mismatch` | 결과를 읽지 못함 / 입력·artifact id·payload 결속 실패(`detail`) / 계약 밖 payload / 영수증 불일치 / 캐시로 돌려준 artifact의 생성자를 모름 / 저장된 텍스트가 submit과 다름 |
| `execution_conflict` `evidence_conflict` `result_version_collision` | 이미 있는 `ai_executions`·`evidence` 행이 다름 / 같은 `result_version`이 이미 있음 |
| `database_unavailable` | DB 오류, **결과가 불명확**할 수 있음(파일을 남김) |
| `internal_error` | 예상 못 한 오류(메시지는 기록하지 않음) |

## 결과 검증

서비스가 말하는 값은 믿지 않고 앱이 직접 다시 계산·대조합니다. 정준 JSON은 Python `json.dumps(sort_keys=True, ensure_ascii=False, separators=(",", ":"))`와 바이트 단위로 같게 구현했습니다(단위 시험의 기대값은 Python이 만든 값이고, smoke가 `available`에 도달하는 것 자체가 실제 워커 산출물의 한국어·이모지 텍스트에서 digest가 일치한다는 증거입니다). 부동소수는 정준 형식에서 받지 않습니다.

- **결속(어긋나면 아무것도 쓰지 않음):** payload의 `schemaVersion`·`jobId`·`state=ready`·`inputDigest`, 되돌려 준 `input`의 정준 형식이 저장된 submit과 같음, `artifactIds`가 유일하고 status와 같으며 한 job의 것임(캐시 적중이면 그 job이 이 앱의 분석이고 같은 질문의 submit을 가졌음), 타입 있는 영수증이 payload `calls`와 같음.
- **내용 게이트(어긋나면 `withheld`):** 생성 artifact 1개와 `semantic-verification` 1개이며 의존 관계가 맞음 · 정책 버전이 `zoop-document-gate-2`(아니면 `document_policy_outdated`) · 두 artifact의 문서·기업·grant·provenance가 submit과 같음 · `artifactId`·`resultVersion`·`modelConfigRevision`을 **재계산**해 같음 · 호출 영수증이 `validated`·같은 stage·mode·정책 · `validation.exact`가 참이고 `semantic`을 검증자의 verdict에서 재계산한 값과 `eligible`이 같음 · **저장된 텍스트에 대한 exact 검사**: 인용 id 유일, 문서·버전·텍스트 artifact 일치, `unicode_code_point`, `0 <= start < end <= 코드 포인트 수`, **코드 포인트 부분 문자열이 quote와 같음**(UTF-16 단위가 아님), 인용한 raw locator가 알려져 있고 어느 하나가 `[start, end)`를 포함, 모든 비-limitation claim이 인용을 가지며 `limitations`는 limitation claim의 텍스트와 같고 `text`/`rationale`은 비-limitation claim 텍스트를 `\n`으로 이은 값 · DB에 들어갈 문자열에 `U+0000`이 없음.
- **검증자가 본 claim은 답의 claim 그대로여야 합니다:** 검증자 artifact의 `claims`가 생성 artifact의 `claims`와 정준 JSON으로 같아야 하고(claimId·text·assertionKind·evidenceIds, 순서 포함) verdict의 claim id 집합이 그 id 집합과 같아야 합니다. 답의 claim과 `text`/`rationale`을 고치고 `resultVersion`까지 다시 계산해도 검증자의 verdict는 **옛 claim**에 대한 것이므로 `semantic_claim_coverage_invalid`로 withheld됩니다.
- 그 뒤 **앱 자체 grant 재평가**(방금 읽은 registry, 영수증에서 얻은 recipient: replay는 `authored-replay`, live는 `provider:providerRevision`)와 article 상태, 검증자 판정(`supported`만 통과)을 봅니다. 이 재평가는 정산 transaction이 article·행 잠금을 얻은 직후 **한 번 더** 수행됩니다([권리](#권리)).

## 권리

- **prepare:** 새 export가 S2-1 `read`·`store`·`quote-display`를 CLI에서 확인하고, 앱이 flat registry에서 `rights=known`·`enabled`·근거 있음·revision 일치·`sourceId == articles.provider`·NAVER 검색 source 아님·미만료·**네 작업 모두 허용**·`purposes`에 분석 종류와 `semantic-verification` 포함을 확인합니다. replay는 recipient `authored-replay`도 필요합니다. live의 recipient(공급자·endpoint revision)는 호출이 있기 전엔 알 수 없으므로 prepare가 확인하지 않고 워커·서비스·정산이 확인합니다. Java의 ISO 날짜 해석은 Python보다 엄격하며 읽지 못하면 그 grant를 거부합니다(닫힘).
- **advance(submit·recover 직전):** 서비스에 일을 시키기 전에 article이 지금 `available`이고 현재 flat registry가 허용하는지 다시 읽습니다. replay는 recipient `authored-replay`도 필요하고 live는 호출 전에 recipient를 알 수 없어 prepare와 같이 확인하지 않습니다. 거부면 서비스에 아무것도 보내지 않습니다. status·result 읽기는 권한 확인 없이 허용됩니다(모델을 호출하지 않음).
- **정산:** 서비스의 현재 delivery(`available`)와 **앱이 직접 읽은 현재 registry**가 둘 다 허용해야 하고 article이 `available`이어야 합니다. 결과를 읽은 뒤 한 번, 그리고 **정산 transaction이 article 잠금과 분석 행 잠금을 얻은 뒤** 한 번 더 registry 파일을 읽어 평가합니다(로컬 파일 읽기와 계산뿐, 모델 호출 없음). 잠금을 기다리는 동안 철회·비활성·revision 변경·만료가 생겼으면 같은 transaction에서 `available`을 **`withheld`(그 거부 코드)로 낮추고** 내용 artifact·결과·evidence 없이 호출 영수증과 `ai_executions`만 기록하며, 이 실행이 새로 만든 내용 파일은 지웁니다. registry 파일을 읽지 못하면 거부로 정산하지 않고 롤백합니다. 저장된 `grant_*`(`document_analyses`, `ai_executions`)는 실행 시점의 이력 스냅샷이며 현재 권한이 아닙니다. **남는 창:** registry 파일과 PostgreSQL은 하나의 원자 단위가 아니므로 마지막 재평가와 commit 사이의 철회는 막을 수 없습니다(문서화한 한계). 그래서 `available`은 공개 허가가 아니고 읽는 쪽이 현재 권한을 다시 확인해야 합니다.
- **읽는 쪽:** `available`은 공개 허가가 아닙니다. 읽을 때마다 현재 registry·`access_status`·현재 버전 정책을 다시 확인하고 요약을 기업으로 거르지 않습니다. 이 규칙을 구현한 읽기가 [근거 읽기](#근거-읽기-getevidence-부분-구현)입니다(`getEvidence`만; `listCompanyDocuments` 등 다른 읽기는 아직 없습니다).
- **live 선행 조건(이 변경은 실행·시험하지 않음):** 별도 live 지출 승인, 서비스 환경의 `ZOOP_AI_LIVE_ENABLED=1`·양수 `ZOOP_AI_GLOBAL_MAX_CALLS`·stage 모델(`ZOOP_AI_DOCUMENT_SUMMARY_MODEL` 등)·API 설정, grant의 `recipients`에 `<provider>:<endpoint revision>`, 서비스의 live 허용. 생성과 의미 검증이 서로 다른 provider(예: 생성 `openai-compatible`, 검증 네이티브 `typesafe-native`)이면 **각 stage의 호출이 증명한 수신자를 모두** grant가 가져야 하며(앱은 이미 stage별 receipt의 수신자로 확인하므로 이 때문에 앱 코드를 바꾸지 않았다) 한쪽 수신자만으로는 다른 쪽 전송이 허가되지 않습니다. 이 기능은 실제 공급자·모델을 호출하는 코드 경로를 시험하지 않았습니다.

## 근거 읽기 (`getEvidence`, 부분 구현)

`GET /api/v1/evidence/{id}`(OpenAPI `getEvidence`, `security: []` 공개)는 이미 저장된 **S1 요약의 본문 인용 한 건**을 돌려줍니다. 모델·AI 서비스를 호출하지 않고 **아무것도 쓰지 않습니다**: DB 쓰기 0, 파일 생성·잠금·정리·권한 변경 0. `GET`은 요청마다 **현재** 문서 상태와 **현재** grant registry를 다시 판정합니다(`status=available`은 허가가 아닙니다). OpenAPI에 필드를 더하지 않았고 모든 키가 항상 직렬화됩니다(값이 없으면 `null`).

**설정(운영 플래그와 독립, 기본 미설정).** `ZOOP_DOCUMENT_READ_GRANTS`(= `zoop.document-read.grants`)는 operator의 flat S1 registry 파일(`zoop-ai-s1-1`, 분석과 같은 파일)로 요청마다 새로 읽고 캐시하지 않습니다. 미설정이면 모든 `getEvidence`가 503 `SOURCE_UNAVAILABLE`이고, 설정했는데 정규화된 절대 경로가 아니거나 없는 파일이면 **기동이 실패**하며 메시지는 설정 이름만 말합니다. `ZOOP_DOCUMENT_READ_ARTIFACT_ROOT`(= `zoop.document-read.artifact-root`)는 **캐시로 돌려준 요약의 exact receipt 파일 한 건**을 읽을 때만 필요합니다. 미설정이면 그 경우만 503이고 나머지는 영향이 없으며, 설정은 `ArtifactFileStore.at`으로 루트만 검사하고 **아무것도 만들지 않습니다**. 웹 프로세스는 artifact 루트 소유자와 같은 OS 사용자·같은 호스트여야 합니다(파일이 0600).

**판정(앞에서부터, 하나라도 아니면 404 `EVIDENCE_UNAVAILABLE`이고 이유는 로그에만 남습니다; `request id`와 증거 id, 이유 토큰, 내용·경로 없음).**

1. 검증 쿼리: 빈 값이나 offset 없는 `asOf`는 422 `INVALID_REQUEST`. `round`·`graphVersion`·`asOf` 중 하나라도 있으면 **409 `VERSION_UNAVAILABLE`**(그래프·회차 스냅샷이 없어 최신으로 대체하지 않음, DB 접근 없음). id가 `ev-<64 hex>`가 아니거나 행이 없으면 404 `RESOURCE_NOT_FOUND`. registry를 읽지 못하면 503.
2. 한 개의 `REPEATABLE READ` 읽기 전용 transaction(문 timeout 5초; DB 오류·timeout은 503이지 빈 성공이 아님): `input_kind='body'`·`quote_verified`·`verification_artifact_id` 있음, 그 exact receipt id를 가진 분석이 **정확히 하나**이고(`LIMIT 2`) `summary`·`available`·기업 없음·같은 문서 버전·id가 `exact-<analysisId>`.
3. 문서: `articles.access_status='available'`이고 `current_version`이 증거의 버전과 **같음**(포인터가 NULL이면 현재 버전 없음, 시각으로 대체하지 않음); 증거의 text artifact가 그 버전의 것; 인용 오프셋은 Unicode 코드 포인트이고 `quote`의 코드 포인트 수가 `end-start`와 같음.
4. 저장 결과: 분석의 `result`를 엄격 JSON으로 읽어 `DocumentAnalysisSummary` 모양(키 집합 정확히 일치·`schemaVersion`·artifact/결과 버전/문서 일치)이어야 하고 그 결과가 **이 증거를 id·text artifact·오프셋·quote까지 같게 인용**해야 합니다. 모양이 틀린 저장 결과는 부분 본문 없이 500 `INTERNAL_ERROR`입니다.
5. 현재 권한: 분석이 정산된 grant 스냅샷(`grant_reference`·`grant_revision`)으로 `GrantRegistry.evaluate`(분석과 같은 규칙: `rights=known`·`enabled`·revision 정확 일치·`sourceId == articles.provider`·NAVER 아님·미만료·네 작업 모두·`document-summary`와 `semantic-verification` 목적·recipient). recipient는 **그 분석의 영수증이 증명한 값**(`ai_executions.grant_scope.requiredRecipients`, 두 단계 모두 한 건 이상)이고 현재 registry가 모두 허용해야 합니다. grant revision이 올라가거나 recipient·작업·목적이 줄거나 만료되면 다시 분석할 때까지 증거가 막힙니다(닫힘).
6. `companyId`는 증거 판정 뒤에만 봅니다: 없는 회사는 404 `RESOURCE_NOT_FOUND`.

**캐시로 돌려준 요약.** 한 분석의 호출 영수증과 집행은 그 호출을 **만든 job**(creator) 아래 기록되므로 캐시 적중 분석 자신의 `ai_job_id`로는 집행 행이 없습니다. 이 경우(자기 job의 `ai_executions`가 없을 때만) 그 분석의 **자기 exact receipt 한 건**을 `ArtifactFileStore.readVerified`로 읽습니다: 잠금·세션이 없는 읽기 전용이고(운영자 import·분석이 잠금을 쥐고 있어도 막지 않음) 등록된 hash·크기와 정확히 같고 0600·소유자 일치·일반 파일일 때만 받아들입니다. 그 receipt가 분석 id·AI job id·문서·버전·text artifact와 그 hash·결과 버전·정책 `zoop-document-gate-2`·이 증거(모델 증거 id에서 `ev-…`를 다시 계산, 오프셋)를 말하고, `creatorJobId`와 `inputDigest`로 다시 계산한 두 artifact id가 SQL의 `result_artifact_id`·`semantic_receipt_id`와 같아야 합니다(`ExactReceiptProof`, `ResultAssessor.artifactId`가 G3와 같은 규칙). creator는 같은 문서 버전의 **다른 요약 분석**이어야 하고(그 상태·결과는 읽지 않음, 권리 맥락일 뿐) 그 creator의 집행 중 같은 grant 스냅샷의 recipient를 씁니다. 파일 없음·크기·hash 불일치·receipt 불일치는 404 `EVIDENCE_UNAVAILABLE`, 루트 미설정·권한이 넓은 파일·I/O 오류는 503 `SOURCE_UNAVAILABLE`(재시도 가능)입니다.

**`documentSummary`.** 같은 문서 버전의 요약 요청 중 `request_no`가 가장 큰 행이 `available`이고 같은 판정(자기 grant 스냅샷·recipient, 캐시 적중이면 같은 증명)을 통과할 때만 그 저장 결과를 돌려주고 `resultVersion`·`analysisProvenance`를 함께 채웁니다. 최신이 pending·failed·withheld이면 **옛 available 요약으로 대체하지 않고** `null`입니다(증거 자체는 소유 분석이 유효하면 그대로 제공). `analysisStatus`와 `sentiment`는 항상 `null`입니다.

**부분 성공(그래프 없음).** 200이면서 `metadata.partial=true`, `graphVersion=null`, `eventIds=[]`이고 `failures`에 `eventIds`(`SOURCE_UNAVAILABLE`, `retryable=false`, `asOf=null`)가 들어갑니다. 그래프 저장소가 없어 사건 연결을 확인하지 못하기 때문이며 “사건 없음”이 아닙니다. 알려진 `companyId`는 승인된 연결을 확인할 수 없어 **`sentiment=null`이고 `sentiment` 실패 구역이 추가**됩니다(sentiment 행은 읽지도 않습니다). 기업을 생략하면 기업 문맥을 지어내지 않습니다. `metadata.source`는 `document-analysis`, `asOf`는 요청 처리 기준 시각입니다.

**한계(문서화한 것).** registry 파일은 요청 시작에 한 번 읽고 DB 스냅샷은 그 뒤에 열리므로 그 사이(짧은 구간)의 철회는 다음 요청부터 반영됩니다. 캐시는 없으므로 오래된 결과를 돌려주지는 않습니다. 구현하지 않은 것: GraphDB 사건·승인 연결·기업 판정 읽기, 고정 `round`·`graphVersion`·`asOf` 읽기, `listCompanyDocuments`, 승인·공개 반영. `EvidenceArticle.publishedAt`은 `publication_precision='datetime'`일 때만 채웁니다(날짜 정밀도를 자정으로 만들지 않음).

## DB 매핑

| 대상 | 값 |
|---|---|
| `document_analyses.id` | `da-` + 랜덤 32 hex |
| `article_id` / `article_version` / `stage` | 관찰의 `documentId` / `documentVersion` / `summary` 또는 `sentiment` |
| `company_id` | 요약 **NULL**(ERD), 기업 판정은 선언한 기업. 요약의 기업 문맥은 `ai_submit`과 결과 artifact의 `companyId`에 있음 |
| `request_no` | 범위의 최신 + 1(article 잠금 안에서) |
| `status` / `reason` | pending → `failed`·`withheld`(기계 코드)·`available`(reason NULL) |
| `result_version` / `result_artifact_id` / `produced_at` | AI `resultVersion` / 생성 artifact id / artifact의 `producedAt`(마이크로초) |
| `semantic_receipt_id` / `exact_receipt_id` | 검증자 artifact id / `exact-<analysisId>` |
| `result` | 공개 DTO(`DocumentAnalysisSummary` 또는 `DocumentSentiment`). 요약의 evidence id는 앱 id로 바뀜 |
| `model` `prompt_version` `reasoning_effort` | 생성 단계 호출 영수증의 설정(영수증이 있으면 withheld·failed에도) |
| `grant_reference` `grant_revision` `grant_checked_at` | prepare에서 확인한 grant와 그 시각 |
| `ai_job_id` | prepare가 한 번 발급(UNIQUE) |
| `analysis_job_id` `owner_token` `lease_until` `revoked_at` `summary_text_artifact_id` | **NULL**(다른 담당 또는 이후 작업) |
| `evidence`(요약만) | 인용마다 한 행. `id = 'ev-' + sha256(정준 {analysisId, evidenceId})`, 모델 id는 전역 유일하지 않아 앱 id로 바꿈(원래 id는 `analysis_result` artifact와 exact 영수증에 남음). `input_kind=body`, `summary_analysis_id` NULL, `quote_verified=true`, `verification_artifact_id`=exact 영수증 |
| `ai_executions` | 호출 영수증(`jobId`·`attemptId`) 한 건 = 한 행. `id='aix-'+sha256(creatorJobId, attemptId)`, 소유는 `document_analysis_id`. `feature`: `document-summary`·`semantic-verification`은 `news-analysis`, `document-sentiment`는 `document-sentiment`(ERD 문자 그대로). `grant_checked_at`·비용·통화·`attempt_no`는 NULL(관측하지 않음), `grant_scope`는 `{sourceId, 네 작업, [분석 종류, semantic-verification], [recipient]}` |

**artifact** (모두 `application/json`, 정준 바이트, 결정적 id, 있으면 비교 후 채택): `ai_submit`=`submit-<aiJobId>`, `ai_call_receipt`=`rcpt-<sha256(creatorJobId\nattemptId)>`(서비스 영수증의 모든 계약 필드와 `aiJobId`), `analysis_result`=생성 artifact(id는 워커의 `artifactId`), `semantic_receipt`=검증자 artifact, `exact_receipt`=`exact-<analysisId>`(`textSha256`·`resultVersion`·인용 오프셋과 앱·모델 evidence id, 시각 없음).

**캐시로 돌려준 결과의 사용량.** 같은 질문이 워커 캐시에서 나오면 서비스는 **만든 job의** artifact와 호출을 돌려줍니다. 앱은 그 job(`creatorJobId`)을 가진 자기 분석을 찾아(요청이 jobId를 뺀 뒤 같아야 함) 호출 영수증·`ai_executions`를 **그 job 기준**으로 기록합니다. 이미 기록돼 있으면 비교 후 그대로 두므로(`existing`) 같은 시도가 두 번 집계되지 않습니다. 캐시로 돌려준 결과를 서비스가 withheld하면 job을 알 수 없어 영수증을 기록하지 않습니다(이미 만든 쪽이 기록).

## 크래시와 재실행

| 시점 | 결과 |
|---|---|
| prepare: 파일만 쓰고 커밋 전 | 참조되지 않는 무작위 이름의 submit 파일만 남음. 다시 prepare하면 **새** jobId. 고아는 지우지 않음(보존 정책의 몫) |
| prepare: 커밋 후 | 재실행은 `latest_conflict`로 그 pending을 알려 줌. `advance`하면 됨. AI 호출 0 |
| advance: submit 후 응답 유실·5xx | 아무것도 쓰지 않음. 다음 advance가 status부터: 200이면 `next`, 404면 같은 id·바이트 재전송 |
| 정산: 파일만 쓰고 커밋 전 | 결정적 파일을 바이트 비교 후 채택하고 새로 만들지 않음. 재실행은 status·result 읽기(GET)뿐이고 GET은 모델을 호출하지 않음 |
| 정산: 커밋 결과 불명 | 파일을 남김. 재실행은 pending이면 다시 정산(채택), terminal이면 `already_settled` |
| 정의된 롤백(DB 충돌: 같은 id의 다른 내용 행·집계 충돌 등) | DB는 그대로. 이 실행이 **새로 만든** 파일만 내용 재확인 후 삭제, 이미 있던 파일은 지우지 않음 |
| 정산: 파일 하나가 이미 다른 내용으로 있음(`artifact_file_conflict`) | DB 변경 없음, 분석은 pending. 그 앞에서 이 실행이 **새로 만든** 파일은 모두 지우고, 이미 있어 채택한 파일과 충돌한 파일은 그대로 둠(DB 롤백과 별개의 정리) |
| 정산: 행 잠금 뒤 현재 grant 거부 | `withheld`로 커밋(영수증·집계만). 이 실행이 새로 만든 내용 파일은 삭제 |

## 검증

상태: 로컬·미커밋. 아래 시험·smoke·SQL 증명과 그 최종 실행 결과는 다음과 같습니다.

**최종 실행 증거(2026-10-14, 로컬 작업 트리·미커밋, Main 실행; 실제 모델·provider 호출 0, 원격 CI·배포·커밋·푸시 없음).** 전체 Java 시험 **301개 통과, 실패 0, skip 0**과 `assemble`. 실제 Spring jar(비웹)·HTTP·`ai/service`(replay)·worker·PostgreSQL 17.11을 쓰는 `document_analysis_smoke.py`는 **28단계, jar 65회 실행**을 통과했고 `document_analyses` 16건, `ai_executions` 27건 = 워커 호출 27건, `evidence` 10건, S2-1 원본 ledger 읽기 전용(불변), 모델·provider 호출 0을 확인했습니다. 잠금 대기 중 grant 철회·만료, 검증자가 본 claim을 바꾼 결과, 파일 충돌 단계도 통과했습니다. SQL 증명(`BEGIN…ROLLBACK`)은 smoke 뒤에 통과했습니다. 권한·무결성 경계 수정은 분석 코드에만 닿았으므로 문서 import smoke(16단계, jar 36회)는 수정 전에 통과한 기록이며 다시 실행하지 않았고, 기존 AI gate(9개·13개)는 전송 계층 변경이 없는 상태로 통과했다고 보고받았습니다. 실행하지 않은 것: PostgreSQL 16.13, live 모드, 원격 CI.

```sh
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
./api/gradlew -p api --console=plain test assemble      # DB·Python·네트워크 없이 도는 단위·소비자 시험 + boot jar
```

Java 시험은 실제 `HttpAiAnalysisClient`가 loopback 서비스의 응답을 해석하게 하고, 그 응답(`api/src/test/resources/document-analysis/worker-results.json`)은 **실제 워커와 실제 서비스 wire 모델**이 만든 것입니다. 재생성(계약이 바뀔 때만; id·시각이 매번 바뀜):

```sh
ai/service/.venv/bin/python api/scripts/export_document_analysis_fixtures.py
```

실제 JVM·PostgreSQL·`ai/service`(replay)·설치된 S2-1 CLI를 쓰는 smoke는 **빈 전용 loopback DB**가 필요합니다.

```sh
DB_URL=jdbc:postgresql://127.0.0.1:<port>/<db> DB_USERNAME=<user> DB_PASSWORD=<dummy> \
  ai/service/.venv/bin/python api/scripts/document_analysis_smoke.py \
    --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --ingest-cli "$PWD/ai/pipeline/.venv/bin/zoop-ai-ingest" \
    --psql-container <container> --db-user <user> --db-name <db>
docker exec -i <container> psql -X -v ON_ERROR_STOP=1 -U <user> -d <db> < api/src/test/resources/sql/document-analysis-verification.sql
```

smoke는 합성 문서 6건을 설치된 CLI로 만들어 jar의 import로 등록하고, 실제 `ai/service`(replay)와 flat grant registry를 띄운 뒤 jar를 비웹 프로세스로 항목 단계마다 실행합니다(jar를 수십 번 시작하고 잠금 대기·만료 대기가 있어 수 분 걸립니다). jar와 서비스 사이의 loopback 프록시는 submit 응답 하나를 잃게 하고 result 둘을 고치는 데만 쓰입니다(하나는 다른 입력, 하나는 생성 artifact의 claim을 고치고 `resultVersion`까지 다시 계산한 것). 확인하는 것: prepare(서비스에 job 없음)·`latest_conflict`·`analysis_pending`·`analysis_unchanged`, 상태 우선 submit과 단일 POST, 정산 결과(한국어·이모지 텍스트에서 워커와의 digest 일치, 워커 SQLite의 artifact와 **바이트 단위로 같은 저장 파일**, 인용 오프셋 = Python 코드 포인트 슬라이스, 앱 evidence id), 의미 검증 hold, 서비스 withheld와 복원 뒤 **캐시 적중**(새 워커 호출 0, 사용량 이중 집계 없음), 앱 registry만의 철회, submit 응답 유실, 정산 중 `kill -9`(파일은 남고 커밋 없음, 재실행이 같은 파일을 채택하고 집계는 한 번), prepare 중 `kill -9`(고아 submit), 결과 변조(pending 유지), 워커의 exact 검사 실패(`failed`), 충돌 행으로 인한 롤백과 파일 정리, 변경된 submit 파일 거부, 비웹 가드와 평소 기동, ledger 불변. 권한 경계의 단계(J11–J15): 생성 artifact의 claim을 고쳐 다시 해시한 결과는 검증자가 본 옛 claim과 달라 `semantic_claim_coverage_invalid`로 withheld(영수증 유지, 내용 없음) · 앱 grant 사본이 prepare와 advance 사이에 `model-send`를 잃거나 article이 private가 되면(서비스는 여전히 허용) **submit 0건**·서비스에 job 없음·DB 변경 없음, 복원하면 정확히 한 번 submit 후 `available` · 실제 PostgreSQL 행 잠금을 smoke가 쥐어 jar의 정산을 **잠금 대기에 세운 채**(내용 파일은 이미 쓴 상태) 앱 grant 사본을 철회(`source_operation_denied`)하거나 만료시킨 뒤(`source_grant_expired`, 만료 2초 전까지 jar의 판정이 끝났는지 확인) 잠금을 풀면 `withheld`이고 내용 artifact·결과·evidence·내용 파일은 없고 호출 영수증·집계는 남음 · 검증자 파일 자리에 다른 내용의 파일을 심으면 `artifact_file_conflict`로 DB 변경 없이 이 시도가 만든 파일은 모두 지워지고 심은 파일은 그대로이며, 치운 뒤 재시도하면 `available`. 기대값은 코드와 무관하게 smoke가 따로 계산합니다(위 최종 실행에서 일치): 끝 상태 `{available: 8, failed: 1, pending: 1, withheld: 6}`, 워커 호출 = `ai_executions` = 27(J1–J9가 17, J11–J15가 5×2), evidence 10. 성공하면 마지막 줄이 `{"status": "passed", "steps": N, "providerCalls": 0, "modelCalls": 0, …}`입니다.

문서 import smoke(`document_import_smoke.py`)도 다시 실행해야 합니다: `StrictJson`·`Text`가 공용 패키지(`com.zoop.common.json`)로 옮겨졌고 `ArtifactFileStore`에 검증된 읽기가 추가됐습니다.

**`getEvidence` 시험(2026-10-15).** Java: `EvidenceServiceTest`(판정·현재 grant 변경·캐시 증명·읽기 전용 확인), `EvidenceControllerTest`(키 전부 직렬화·`null`·헤더·오류 봉투), `ExactReceiptProofTest`, `DocumentReadPropertiesTest`, `ArtifactFileStoreTest`의 `readVerified`(잠금 없음, 아무것도 만들지 않음). `document_analysis_smoke.py`는 기본으로(`--no-with-evidence-read`로 끌 수 있음) J15 뒤에 **같은 jar를 loopback 웹 서버로** 띄워(`ZOOP_DOCUMENT_READ_*`만, AI client·운영 플래그 없음) 저장된 evidence 10건 **전부**를 실제 HTTP로 읽습니다. 기대값은 psql·내보낸 텍스트·읽기용 grant 파일에서 따로 계산합니다: 키 집합과 `null`, 인용 = Python 코드 포인트 슬라이스, `X-Request-ID`, 고정 쿼리 409/빈 값·offset 없는 `asOf` 422, 알 수 없는/잘못된 id 404, `companyId`의 부분 응답(없는 회사 404), **서버 실행 중 grant를 바꾸면(비활성·revision·만료·작업·목적·recipient·source) 다음 요청에서 전부 404 `EVIDENCE_UNAVAILABLE`이고 복원하면 200**, registry 손상·삭제 503, private·현재 버전 이동·더 새 pending 요청, 그리고 J4b(캐시 적중, J4의 집행 아래 기록): receipt 파일 이동·변조·0644·creator 집행 삭제·운영자 잠금 보유·artifact 루트 미설정·grant 미설정, 잘못된 설정의 기동 거부(설정 이름만 출력). **읽기가 AI 요청·워커 호출·DB 행·`pg_stat_user_tables` 쓰기 수·artifact 파일(잠금 파일 포함)을 바꾸지 않았음**을 단계 앞뒤로 비교합니다.

**`getEvidence` 최종 실행 증거(2026-10-15, 로컬 작업 트리·미커밋, Main 실행; 원격 CI·배포·커밋·푸시 없음, 실제 모델·provider 호출 0).** 저장된 claims의 닫힌 모양 검증 수정 뒤 전체 Java 시험 **341개 통과, 실패 0, skip 0**과 `assemble`(Main 보고). 실제 Spring jar(웹, loopback)·HTTP·`ai/service`(replay)·worker·PostgreSQL 17을 쓰는 `document_analysis_smoke.py`는 **41단계**를 통과했고 evidence GET **294건**으로 저장된 evidence 10건 전부(캐시 적중 J4b 포함)가 제공됐습니다. grant·registry 변경, 옛 버전, 최신 pending, 캐시 증명 불량, hash·파일 권한, 운영자 잠금 보유 단계도 통과했고 GET이 DB·파일·AI·모델에 쓴 것은 없으며 provider·모델 호출은 0입니다. 전체 smoke의 분석 16건, 집행 27건 = 워커 호출 27건, evidence 10건은 그대로입니다. 실행 전용 PostgreSQL 컨테이너는 정리했습니다. **구현하지 않은 것(위 한계 그대로):** `listCompanyDocuments`, GraphDB 사건·승인 연결·기업 판정 읽기, 고정 버전 읽기. PostgreSQL 16.13·live 모드·원격 CI는 실행하지 않았습니다.

제안(루트 Makefile은 수정하지 않음): `api-document-analysis-smoke` — `$(SERVICE_PYTHON) api/scripts/document_analysis_smoke.py --jar … --ingest-cli $(PIPELINE_PYTHON 옆 zoop-ai-ingest) …`. DB 접속 인자가 필요하므로 CI에는 연결하지 않았습니다.

## 남은 결정과 한계

- 이 migration(`V20261014130000`)과 `document_analyses`·`evidence`·`ai_executions`의 소유는 **로컬 제안**입니다([소유 경계](../../docs/development/api-migration-ownership.md)). 병합 순서상 이 파일이 최신 버전 뒤에 오도록 이름만 바꿉니다.
- **연기한 FK.** `analysis_jobs`·`chat_jobs`·`briefing_attempts` 테이블은 없습니다(다른 담당). `document_analyses.analysis_job_id`와 `ai_executions.chat_job_id`·`briefing_attempt_id`·`analysis_job_id`는 **일반 text 열**이고 이 코드는 쓰지 않습니다. FK는 해당 테이블을 만드는 migration이 추가합니다(브리핑의 `graph_version_id`와 같은 선례). `ai_executions.document_analysis_id`와 `ai_job_id` 일치는 코드와 트리거로, 다른 실행 소유가 문서 분석을 추가 문맥으로 가질 수 있어 복합 FK는 만들지 않았습니다.
- **evidence id 네임스페이스(ERD §8 항목 4 “원문/요약 인용 네임스페이스”)는 이 변경이 로컬로 정했습니다**: `ev-` + sha256(`{analysisId, 모델 evidenceId}`). 모델 id(`e1` 등)는 전역 유일하지 않고 `evidence.id`는 전역 PK이기 때문입니다. 확정은 소유자의 몫입니다.
- 분석 `replay`의 의미(ERD §32 “저장 산출물 재사용” vs 이 저장소의 authored replay)는 열린 항목이며, 캐시로 돌려준 결과는 별도 replay 실행으로 세지 않습니다.
- 잘못된 prepare는 그 범위를 terminal이 될 때까지 막습니다(취소·포기 경로 없음). 권리 때문에 withheld된 결과의 복구는 명시적 재요청이며 grant revision이 같을 때만 캐시 덕에 무료입니다. withheld 행은 내용 artifact가 없어 감사 근거가 이유 코드와 영수증입니다.
- 서비스가 withheld한 결과는 payload가 없어 앱이 job 입력을 검증할 수 없고(랜덤 jobId·principal 소유·status의 kind/mode 일치에 의존), prepare 크래시의 고아 submit 파일은 지우지 않습니다.
- `unknown`/미영수증 시도가 남은 job은 정산하지 않고 대기합니다. 취소·늦은 영수증, TLS, 실제 전원 손실, live 모드는 증명하지 않았습니다. SQL은 PostgreSQL 16·17에 모두 있는 기능(부분 UNIQUE, `num_nonnulls`, 트리거, `jsonb_path_exists`)만 쓰도록 썼으나 PostgreSQL 17.11에서 smoke와 SQL 증명을 실행했고 compose의 16.13에서는 실행하지 않았습니다. `evidence`의 `char_length(quote)` 검사는 UTF-8 데이터베이스를 전제합니다.
- **registry 파일과 DB의 비원자성.** 잠금 뒤 재평가와 commit 사이(짧은 구간)의 철회는 어떤 구현으로도 막을 수 없는 문서화된 창입니다. 잠금 대기 중의 철회·만료는 막으며 JUnit과 smoke(실제 PostgreSQL 행 잠금)가 그것을 확인했습니다([검증](#검증)). 파일 쓰기는 transaction 앞에서 일어나므로 DB 롤백과 파일 정리는 서로 다른 단계입니다(위 표).
