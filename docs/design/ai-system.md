# AI 실행과 문서 공개 계약

## 현재 구현 범위와 설계 논의 적용

**현재 실행 단위는 S1 문서 요약·문서×기업 판정·별도 의미 검증과 기존 회차 outlook이며, S2-1의 독립 오프라인 원문 준비·검사와 S2-2의 독립 오프라인 이벤트·SAME·주제 후보 준비도 구현했다. 전체 AI 기능이나 FS074–081 전체의 완료를 뜻하지 않는다.** 설계 보고서 `local://ai-contract-design.md`의 §3–6과 §8/S1에서 합의한 worker 소유 경계, camelCase JSON, 불변 영수증, 현재 공개 gate, 무호출 저장 복구를 적용한다. 기존 outlook 생산자를 삭제하지 않는다는 추가 합의도 반영했다. S2-1은 `local://s2-ingestion-contract.md`의 독립 저장소·현재 registry·정확한 원문 좌표 계약을 적용했다. 보고서는 설계 근거이며 실행 증거는 아래 별도로 기록한다.

| 실행 단위 | 현재 상태 | 소유 의미와 후속 범위 |
|---|---|---|
| S1 | 구현: 문서 세 stage + 기존 briefing-outlook 이행 + 실제 JSON CLI + BFF 수입 | 문서의 versioned claim/citation과 기업별 판정을 검증·저장하고, 기존 회차 판정의 생성·발행 고정을 유지한다. |
| S2 | S2-1 구현: 오프라인 회차·raw·정제/map·불변 문서 버전·재개·검사. S2-2 구현: 오프라인 이벤트·SAME·주제 후보 | 실제 공급원·정기 수집·앱 문서 등록은 미구현이다. S2-2는 authored replay만 실행하며 live 추출, retrieval, 승인·게시, 주제 승인은 후속이다. |
| S3 | 계획, 미구현 | 공급/경쟁/투자 관계와 영향, 관계 적격성, HOLD 검수 후 재검증 |
| S4 | 계획, 미구현 | 전체 의존성 철회, 과거 pin·채팅·회차·캐시까지 공개 barrier와 증분 복구 |
| S5 | 계획, 미구현 | 기업·시장 요약, 중요도 선정, 공통 출퇴근 브리핑 강화. 이미 있는 outlook 생산 능력은 S1 이행으로 보존한다. |
| S6 | 계획, 미구현 | 실제 AI 질문 해석·답변·되묻기와 채팅 작업 seam 이행 |
| S7 | 계획, 미구현 | 개인화 브리핑·소유권·평가·전체 사용량 끝단 |

전체 명세는 요구 범위다. 위 표는 구현 순서이며 S2–7을 요구에서 제외하는 결정이 아니다. 이후 기능을 실행되지 않는 클래스, echo 응답, 빈 디렉터리로 만들지 않는다. 기존 PoC의 추출, SAME, outbox, 원장을 S1 worker가 재작성하지 않는다. BFF의 기존 pinned `investmate-poc` 의존성(`fa446e7c72edfa06ec1a0e8e999199a21d31c695`)과 읽기 adapter는 유지한다. 원본 PoC는 수정하거나 vendoring하지 않았으며, private dependency의 접근·라이선스 조건은 그대로 적용된다. S1 worker의 런타임 의존성은 기존 환경에 있는 Pydantic과 HTTPX뿐이다.

## 저장소와 공개 seam

- `prototype/ai-worker/src/zoop_ai/contracts.py`가 S1 wire 타입을 소유한다. 생성한 `docs/api/ai-contract.schema.json`과 `fixtures/contracts/synthetic-document/`, `synthetic-outlook/`의 표본은 언어와 독립된 계약이다. 실제 kind는 문서 세 stage와 기존 `briefing-outlook` 네 가지다.
- `provider.py`의 OpenAI-compatible adapter는 실제 `POST chat/completions`를 전송한다. replay adapter는 fixture 순서와 정확한 stage/input/config digest를 대조한다. 불일치·소진은 실패이며 생성 대체값이나 자동 fallback이 없다.
- `store.py`/`runner.py`는 작업, 호출, 영수증, 불변 산출물, 전역 호출 예산 예약을 worker의 별도 SQLite에 저장한다. 앱 SQLite를 공유 쓰기하지 않는다.
- `zoop_bff.ai_worker.AiWorkerClient`는 기존 `LaunchSpec`·process-group 감독 패턴을 재사용하여 JSON CLI와 통신한다. 앱은 worker DB를 직접 읽거나 쓰지 않는다.
- `DocumentAnalysisStore.import_job()`은 현재 문서 version/hash·기업 연결·synthetic provenance·grant·생성/의미 검증 영수증·인용 ID와 span을 다시 확인한다. 수입과 앱 receipt/사용량 기록은 하나의 짧은 transaction이다.
- `GET /api/companies/{id}/documents`와 `GET /api/evidence/{id}?companyId=...`는 저장 결과만 읽는다. `documentSummary`, `analysisStatus`, `analysisProvenance`, `documentVersion`, `resultVersion`을 제공한다. 기존 `DocumentSentiment`의 모양은 변경하지 않는다.

새 BFF 필드는 항상 직렬화하되 결과가 없으면 nullable이다. 목표 OpenAPI에서는 단계적 소비자를 위해 새 필드를 optional·nullable로 명시한다. `analysisStatus.summary/sentiment`는 각각 `not_requested|pending|failed|withheld|available`이다. 실제 평가를 마쳤으나 방향 근거가 부족한 `sentiment.label=undetermined`와, 판정 산출물이 없는 `sentiment=null`은 다르다. 요약과 판정은 독립 작업이다. 요약의 HOLD/실패가 유효한 기업별 판정을 지우지 않는다. 외부 오류를 판단 보류로 바꾸지 않는다.

`resultVersion`은 공개 요약이 있으면 그 요약 버전, 요약 없이 판정만 있으면 판정 버전이다. summary citation의 document/version/resultVersion과 evidence 응답 문맥을 프론트엔드가 대조한다. JS/Java는 UTF-16 index를 그대로 쓰면 안 된다. `offsetUnit=unicode_code_point`, `end`는 exclusive이고, exact 검증 때 공백·NFC·따옴표를 임의 정규화하지 않는다. S1 합성 표본의 cleaner는 identity이며 raw locator도 명시한다. S2-1은 별도 ingestion 저장소에서 HTML/PDF 정제와 복수 locator를 복원한다. 이 내부 문서를 현재 앱 Dataset에 등록하거나 공개하는 경로는 아직 없다.

## 호출·상태·복구

| 명령/상태 | 실제 동작 | 재호출 규칙 |
|---|---|---|
| `submit` | stdin 요청과 stage 설정을 불변 digest로 저장한다. 같은 job+digest는 기존 작업, 다른 digest는 `job_input_conflict`다. | 모델 호출 0 |
| `run` | grant→durable budget reservation→`outgoingcall.started`→HTTP/replay→`receivedreceipt.saved`→exact→별도 semantic→`artifact.persisted` | 자동 provider retry 없음 |
| `get` | versioned 작업·영수증 메타데이터·산출물을 내부 JSON으로 조회한다. 사용자 API는 이 내부 출력 전체를 노출하지 않는다. | 모델 호출 0 |
| `resume` | 영수증이 저장된 단계는 다시 파싱/검증/저장한다. 아직 송신하지 않은 단계만 실행할 수 있다. | 완료·취소·reconciling은 새 호출 없음 |
| `cancel` | 작업 fence를 올려 늦은 결과의 산출물 저장을 막는다. 발생한 비용/응답 영수증은 보존한다. | 과금 취소를 보장하지 않음 |
| timeout/응답 불명/receipt 저장 전 종료 | `reconciling`, `resumeMode=reconcile_only`로 남는다. 프로세스 종료나 lock 해제는 미청구의 증명이 아니다. | 자동 재실행 금지 |
| receipt 저장 후 산출물 저장 실패 | `persisting`, `resumeMode=save_only`로 보존한다. HOLD/REJECT인 별도 검증 산출물도 작업·kind로 재사용한다. | 저장된 영수증·산출물만 재사용하고 provider는 다시 부르지 않음 |
| worker ready 후 BFF import 실패 | 기존 job `get` 후 import만 반복한다. 앱 transaction은 rollback된다. 동일 attempt는 고정 identity를 확인하고 `started→received→validated` 상태와 처음 확인된 usage만 전진한다. | 새 job/model call·중복 비용 없음 |

네트워크 동안 SQLite write lock은 보유하지 않는다. 모든 live attempt(생성과 의미 검증 포함)는 같은 durable global ledger에서 먼저 예약한다. CLI 재시작이나 두 프로세스 실행으로 ceiling을 초기화하지 않는다. 미확인/송신된 호출의 예약은 임의 해제하지 않는다. 이미 등록된 ceiling을 명령 재실행으로 증가시키지 않는다. Replay/cache는 유료 attempt와 분리한다. provider가 미보고한 input/output/cached/reasoning token과 timeout 비용은 `null`이다. 단가·금액 상한은 미정이며 0원으로 표시하지 않는다.

캐시 identity는 문서 내용/version/source hash, 기업, grant revision, provider/endpoint revision, model, effort, prompt 내용/version, schema 내용/version, policy를 포함한다. 제한 문장 검증을 강화한 현재 정책은 `zoop-document-gate-2`이며 이전 정책 산출물은 raw 이력으로 보존하되 cache hit나 BFF 공개 gate를 통과하지 않고 `document_policy_outdated`로 보류된다. 모델/effort/prompt/policy가 바뀌면 새 작업과 새 cache key다. 이미 제출한 같은 job의 설정을 조용히 바꾸지 않는다. 불변 산출물은 재사용하지만 반환·수입 때 현재 문서/권한/visibility를 대조한다.

## 권한과 공개 gate

source grant는 `enabled`와 `rights`, `allowedOperations`, `recipients`, `purposes`, `evidence`, `expiresAt`을 분리한다. 켜졌다는 사실은 모델 전송 승인이 아니다. read/store/model-send/quote-display 권한과 생성·검증 목적/수신자가 모두 필요하다. unknown·증거 없는 권한·만료는 fail closed다. 모델 전송 전과 회수 후 다시 확인한다. 운영자가 지정하는 `--grants`는 서버 소유 registry이며 job/model 입력이 권한을 발급하지 않는다. BFF도 server-owned registry snapshot 갱신과 worker artifact 수입을 분리한다. artifact에 실린 과거 grant는 실행 영수증일 뿐 현재 권한을 갱신하지 않으며 opaque revision 문자열을 정렬해 최신을 추측하지 않는다.

live 수신자는 단순한 `openai-compatible` 프로토콜 이름이 아니라 `openai-compatible:<providerRevision>`으로 등록한다. `providerRevision`은 승인된 base URL을 포함한 endpoint identity의 digest다. 제출 때 고정한 endpoint와 실제 client endpoint가 다르면 송신 전에 configuration failure로 끝낸다. 다른 업체/endpoint로 조용히 전송하거나 grant를 확대하지 않는다. replay 수신자는 네트워크 없는 `authored-replay`다.

기존 데모는 저장 source의 읽기 계약을 유지한다. 새 live grant를 자동 생성하지 않으며 실제 본문에 authored replay를 수입할 수 없다. [외부 API 조사](../evidence/external-api-candidates-2026-10-08.md)의 NAVER Developers Search 데이터는 AI 입력으로 금지하며 HUB의 별도 허가는 unknown이다. 공개 URL, 키 보유, 관리자 enable을 제3자 전송/요약 게시 권리로 해석하지 않는다.

모든 공개 사실/해석 claim에는 정확한 versioned citation이 필요하다. 공개 `limitations`의 각 문자열도 `assertionKind=limitation` claim과 정확히 대응해야 하며 별도 semantic stage가 사실·해석·제한 claim 전부를 `supported|contradicted|insufficient`로 판정한다. 생성기와 분리된 검증자는 투자 권유·미지원 인과도 검사한다. exact 또는 schema 실패는 공개하지 않는다. semantic HOLD/REJECT 산출물은 worker 내부에서만 보존하고 BFF는 이유와 null을 반환한다.

현재 S1 gate는 두 문서 consumer의 source/context에 적용한다. `document_analysis_visibility`의 explicit deny와 원문 withdrawn은 문서 목록과 direct evidence GET을 차단한다. 저장 raw/모델 영수증과 승인 이력은 worker-private으로 남는다. 공개 응답에는 사용자 디렉터리, key, raw provider reply, private 파일 경로가 없다. 이전 채팅/브리핑/그래프 전체에 대한 의존성 closure까지 구현했다고 주장하지 않는다(S4).

기존 `sentiment_results`와 이미 발행된 회차 payload는 불변 읽기를 유지한다. 예전 BFF provider/client와 `scripts/judge_sentiment.py`의 중복 live 분기는 제거하고, 문서와 기존 회차 생산을 worker로 이행했다. `scripts/judge_outlook.py`는 실제 worker CLI를 통해 비어 있지 않은 미발행 회차의 outlook을 생성하고 원래 발행 경로에 저장한다. 기존 issueIds 정확 참조·금지 표현 검증은 `legacy-outlook-exact-1` 정책이며 `validation.semantic=null`이다. worker의 새 생성 검사뿐 아니라 BFF importer도 미발행 ready/cache 산출물의 한국어 공백 정규화 예측어와 기존 영문·가격·인과 금지 표현을 다시 검사하므로, 이전 약한 검사로 저장된 금지 rationale은 발행되지 않는다. 이미 발행된 불변 payload를 소급 변경하지 않는다. 문서의 별도 의미 검증과 동급으로 검증됐다고 쓰지 않는다. 빈 회차는 모델 호출 없이 outlook null, 발행된 회차는 null까지 그대로 유지한다.

## 설정 이행과 재현 명령

실제 모델·effort·예산 운영값은 아직 결정하지 않았다. stage env는 `prototype/bff/.env.example`에 기록한다. 옛 `ZOOP_SENTIMENT_MODEL`/`ZOOP_SENTIMENT_REASONING_EFFORT`의 문서 설정은 `ZOOP_AI_DOCUMENT_SENTIMENT_MODEL`/`ZOOP_AI_DOCUMENT_SENTIMENT_REASONING_EFFORT`로, 회차 설정은 `ZOOP_AI_BRIEFING_OUTLOOK_MODEL`/`ZOOP_AI_BRIEFING_OUTLOOK_REASONING_EFFORT`로 명시적으로 옮긴 뒤 옛 export를 제거한다. 요약은 `ZOOP_AI_DOCUMENT_SUMMARY_*`, 검증은 `ZOOP_AI_VERIFY_*`로 별도 승인한다. 런타임 alias는 없다.

live에는 `ZOOP_AI_LIVE_ENABLED=1`, 양수 `ZOOP_AI_GLOBAL_MAX_CALLS`, 실행하는 stage model, 승인된 current grant와 API 설정이 모두 필요하다. 문서 작업은 생성과 VERIFY 양쪽 모델을 요구하고, 기존 outlook은 BRIEFING_OUTLOOK 모델을 사용한다. effort가 비면 요청 필드를 생략한다. 미지원 옵션은 configuration/provider failure로 남기며 조용히 제거하지 않는다. 예산 gate는 durable call ceiling이고 실제 단가·금액 상한과 전체 token ceiling의 운영값은 미정이다. 실제 모델/키/.env를 열거나 유료 live를 실행하지 않는다.

저장 상태를 분리한 네트워크 없는 합성 재현은 다음과 같다. 공유 `var`, 기본 8787/5173을 사용하지 않는다.

```sh
prototype/bff/.venv/bin/python prototype/ai-worker/scripts/replay_fixture.py \
  --worker-state /tmp/zoop-ai-doc-worker-demo \
  --bff-state /tmp/zoop-ai-doc-bff-demo

ZOOP_SNAPSHOT_PATH="$PWD/prototype/ai-worker/fixtures/contracts/synthetic-document/snapshot.json" \
ZOOP_COMPANY_CATALOG="$PWD/prototype/ai-worker/fixtures/contracts/synthetic-document/snapshot.json" \
ZOOP_STATE_DIR=/tmp/zoop-ai-doc-bff-demo ZOOP_QUOTE_PROVIDER=off ZOOP_METRICS_PROVIDER=off ZOOP_BRIEFING_SCHEDULER=0 \
PYTHONPATH=prototype/bff/src prototype/bff/.venv/bin/python -m uvicorn zoop_bff.main:app \
  --host 127.0.0.1 --port 8871
```

fixture driver는 실제 `submit/run/get` CLI를 순서대로 실행하고 기존 BFF import 명령에 연결한다. 두 기업은 `SYNTH-A`, `SYNTH-B`, 문서는 `doc-synthetic-s1`이다. 상태 조회 JSON은 `{"schemaVersion":"zoop-ai-s1-1","jobId":"..."}`이고 submit은 `jobs.json.jobs[]`의 해당 객체다. 개별 호출은 기존 interpreter로 `PYTHONPATH=prototype/ai-worker/src ... -m zoop_ai.cli <command> --state-dir <worker> [--grants <registry> --replay <fixture>]`를 실행하고 JSON을 stdin으로 보낸다. stdout은 typed JSON, 비밀/본문 진단은 출력하지 않는다.

BFF 수입 재시도와 source deny는 다음 명령을 사용한다. 두 명령 모두 모델 호출이 없다.

```sh
PYTHONPATH=prototype/bff/src prototype/bff/.venv/bin/python prototype/bff/scripts/document_analysis.py import \
  --state-dir /tmp/zoop-ai-doc-bff-demo --worker-state /tmp/zoop-ai-doc-worker-demo \
  --grants prototype/ai-worker/fixtures/contracts/synthetic-document/grants.json \
  --job-id synthetic-SYNTH-A-document-summary
PYTHONPATH=prototype/bff/src prototype/bff/.venv/bin/python prototype/bff/scripts/document_analysis.py deny \
  --state-dir /tmp/zoop-ai-doc-bff-demo --document-id doc-synthetic-s1 --reason '합성 문서 공개 철회'
```

import도 실행할 때 위와 동일한 synthetic `ZOOP_SNAPSHOT_PATH`/catalog를 지정한다. 일반 앱의 실제 source/state에 합성 응답을 섞지 않는다. 재생성은 `export_contracts.py`, 생성 schema/fixture 검증은 `validate_contracts.py`로 수행한다. export는 기존 BFF 환경의 pinned PoC Article.version/evidence ID 규칙을 fixture 생성에만 재사용하며 원본에 쓰지 않는다. worker만 배포할 때 fixture/schema는 별도 계약 파일로 함께 전달한다.

### 기존 outlook 생성·빈 회차·불변 발행 재현

```sh
prototype/bff/.venv/bin/python prototype/ai-worker/scripts/replay_outlook_fixture.py \
  --worker-state /tmp/zoop-ai-doc-outlook-worker \
  --bff-state /tmp/zoop-ai-doc-outlook-bff \
  --empty-bff-state /tmp/zoop-ai-doc-outlook-empty
```

driver는 실제 `scripts/judge_outlook.py --replay ... --grants ... --source-id ... --grant-id ... --grant-revision ... --round ...`를 실행한다. `--synthetic-now`는 합성 replay에서만 가능한 재현용 Clock hook이다. actual/live 자료의 clock을 바꾸지 않는다. 합성 2026-10-08 저녁 회차는 이슈 1개로 판정을 생성하고, 같은 회차 재실행은 발행값을 그대로 반환하며 새 worker 작업이 없다. 같은 문서가 아직 들어오지 않은 출근 회차는 0개·outlook null·worker 명령 0개다. 실제 BFF 조회는 해당 snapshot/state를 읽는 `/api/briefings?date=2026-10-08&edition=evening`으로 확인한다.

기존 admin 생성 권한·발행 후 409·immutable payload trigger를 유지한다. replay는 실제 자료에 적용하지 못하고, 현재 grant가 unknown/disabled/만료이거나 목적·수신자가 맞지 않으면 생성하지 않는다. 저장된 worker artifact를 가져온 뒤 원래 round에 commit하기 전에 graph/review/rule pin을 다시 확인한다. configured worker의 실패를 근거 부족의 undetermined나 정상 발행 null로 위장하지 않는다. 모델 전송 불명은 reconciling으로 보존한다.

### 잠금 파일과 독립 worker 환경

`prototype/ai-worker/uv.lock`은 기존 BFF와 같은 Pydantic 2.13.5·HTTPX 0.28.1과 dev pytest 9.1.1을 고정한다. 새로운 외부 패키지나 private PoC 의존성을 worker 런타임에 추가하지 않았다.

```sh
uv sync --project prototype/ai-worker --offline --frozen --group dev --no-install-project \
  --python prototype/bff/.venv/bin/python
PYTHONPATH=prototype/ai-worker/src prototype/ai-worker/.venv/bin/python -m pytest prototype/ai-worker/tests
prototype/ai-worker/.venv/bin/python prototype/ai-worker/scripts/validate_contracts.py
uv build --project prototype/ai-worker --offline --wheel --out-dir /tmp/zoop-ai-worker-wheel
```

`--no-install-project` 환경은 PYTHONPATH로 실행한다. wheel 배포는 manifest의 `zoop-ai` entrypoint를 제공한다. exporter는 기존 BFF 환경에서만 PoC의 공개 Article.version/evidence ID 규칙을 읽고 임시 상태에 합성 round preview를 계산한다. 외부 모델/시장 호출은 없다. 생성 대상은 schema 1개와 document/outlook 각 fixture 4개, 총 9개다.


## FS 구현 상태와 증거 위치

| 기능 | 현재 구현한 부분 | 아직 남은 부분 | 확인 코드/표본 |
|---|---|---|---|
| 문서 긍부정 / 뉴스 요약 | 기업별 독립 판정과 summary claim·근거·버전·실제 provider/replay→BFF GET | 실제 승인 모델/운영 품질·비용 결정 | `test_documents.py`, BFF `test_sentiment.py`, synthetic-document fixture |
| 기존 회차 outlook 보존 | 실제 worker provider/replay·정확 참조/금지 표현 정책·미발행 회차 생성·발행 고정·0이슈 무호출 | 새 기업/시장 요약과 강화된 별도 의미 검증은 S5 등 후속 범위 | `test_outlook.py`, `test_outlook_worker.py`, `replay_outlook_fixture.py` |
| FS075 | S1 exact 인용·불변 version 대조, S2-1 source-local identity·raw/text 버전·HTML node/PDF page 좌표·재개 | 실제 공급원 정책·앱 등록·공개 인용 연동·추가 cleaner 정책 | `test_ingestion.py`, `ingestion_smoke.py`, S1 exact 규칙 |
| FS080 | 호출 예약·received receipt·validated artifact·앱 import commit 분리, 같은 결과 수입 멱등 | GraphDB 양쪽 projection/readiness·manifest CAS 전체 | 저장 실패/수입 rollback 시험 |
| FS081 | 문서 두 consumer의 현재 deny/version/hash gate, 저장 복구 시 새 호출 없음 | 전체 dependency closure·옛 채팅/회차/pin 제외 | direct evidence deny·cache/model/effort/version 시험 |
| FS066/068 연동 | 문서 요약·기업판정·의미검증의 actual/replay 영수증을 관리자 사용량에 분리 연결 | S7 전체 평가·개인 결과 통합 | 관리자 ai-usage 수입 중복/토큰 null 시험 |
| FS074 | S2-1 합성 source-round·페이지 응답/raw 영속·연속 checkpoint·저장 복구 | 실제 공급원·05/35분 스케줄·지연 등록/조회 보장·앱 등록 | 독립 `ingestion_cli`, `test_ingestion.py`, `ingestion_smoke.py` |
| FS076/077/078/079 | S2-2: 오프라인 이벤트 추출·whole-event SAME/FOLLOWS/HOLD 후보와 별도 주제 후보(authored replay). 승인·게시·관계·영향·검수는 완료 주장 없음 | 실제 모델 품질·B0–B4 retrieval·S3–S4의 관계·영향·검수와 공개 | `extraction_cli`, `test_extraction.py`, `extraction_smoke.py` |

이 문서의 구현 설명은 위 source와 합성 계약을 가리킨다. 실제 운영 모델의 의미 품질, 출처 라이선스 최종 승인, 금액 상한, S2–7 전체는 검증된 완료 항목이 아니다.

## 실행으로 확인한 결과

2026-10-08의 최종 소스에서 다음을 실제 실행했다. 기존 기능 보존을 포함한 현재 S1 증거이며 전체 S2–7이나 운영 모델의 의미 품질을 검증한 결과는 아니다.

- worker 디렉터리의 `PYTHONPATH=src .venv/bin/python -m pytest tests -q`를 실행하여 **42 passed**를 확인했다. exact quote의 한글/non-BMP offset, limitation claim coverage, fake claim semantic HOLD, grant fail-closed와 standalone 응답 중 철회, model/effort/version cache miss, job conflict, 두 프로세스 전역 예산, timeout/receipt loss 무재호출, HOLD/REJECT artifact 저장 뒤 ready 실패의 무호출 복구, live MockTransport save-only, 취소 중 늦은 응답의 비용 영수증 보존과 추가 호출 차단을 포함한다.
- BFF 디렉터리의 `PYTHONPATH=src .venv/bin/python -m pytest tests -q` 최종 실행은 **310 passed, 1 warning**이었다. 경고는 기존 Starlette HTTPX TestClient deprecation이며 숨기거나 새 의존성을 설치하지 않았다. server-owned current grant 철회 뒤 지연 artifact 재수입, 공개 limitation 위조 거부, 같은 attempt의 received→validated/usage 전진과 중복 0, 실제 CLI A import→동일 input 새 job B cache hit import의 creator receipt 재사용·usage 무증가, 다른 call identity 충돌 거부, A→B→A 재수입 공개 순서, 이전 document policy 산출물 공개 보류, 이전 약한 outlook ready 결과의 발행 전 금지 표현 재검사, 문서 importer의 ready/cancel barrier와 기업 ID/이름 일치, HOLD와 독립 판정, 기존 outlook의 발행 고정·재시작·권한·원문 허가 gate, 실제 404/422 optional error.details 회귀도 포함한다.
- `validate_contracts.py`는 생성 schema와 document/outlook 표본 **16 records passed**를 확인했다. 이 도구는 생성된 키워드 부분집합의 의존성 없는 validator이며 임의 JSON Schema 전체 구현이라고 주장하지 않는다.
- 실제 `replay_fixture.py`는 문서 작업 **4 ready, replay 8, providerAttempts 0**과 BFF **4 available imports**를 반환했다. BFF importer는 같은 실행에서 server-owned `grants.json` snapshot을 artifact와 별도 등록했다. TestClient HTTP의 두 company-documents/evidence GET에서 SYNTH-A positive/SYNTH-B negative, 두 사실 claim과 검증된 limitation claim, 정확 citation을 읽었다.
- 실제 `replay_outlook_fixture.py`는 fresh 별도 상태에서 이슈 **1개인 저녁 회차를 published**로 만들었다. outlook은 undetermined였고 worker **1 ready, replayCalls 1, providerAttempts 0**이었다. 같은 회차 재실행은 동일 outlook과 workerJobs=[]를 반환했다. 출근 0이슈 회차는 published/outlook null/workerJobs=[]였다.
- document/outlook exact replay의 입력은 다르다. 이미 문서 판정이 있는 상태를 outlook의 빈 documentSentiments 표본에 재사용한 최초 driver 실행은 실패했고, worker 영수증에서 `replay_input_mismatch`를 확인했다. fresh 분리 상태로 위 실제 성공을 확인했다. 실제 자료/공유 `var`를 수정하거나 mismatch 응답을 맞는 것으로 간주하지 않았다.
- own 8871의 실제 OpenAPI에서 `pnpm exec openapi-typescript ... -o src/api/schema.d.ts`를 **한 번** 실행했다(7.13.0). 이후 outlook 이행은 기존 공개 DTO의 모양을 변경하지 않았다.
- `uv lock --offline` 및 `uv sync --offline --frozen --group dev --no-install-project`는 기존 캐시만 재사용했다. `uv build --offline --wheel`도 성공하여 `/tmp/zoop-ai-doc-backend-dist/zoop_ai_worker-0.1.0-py3-none-any.whl`을 만들었다. 실제 model HTTP는 0이며 HTTP adapter는 합성 MockTransport에서만 실행했다.

위 API smoke에 사용한 소유 서버는 모두 종료했다. 원본 PoC의 소스/DB에 쓰지 않았고, 실제 `.env`/키/개인정보나 공유 포트/상태는 읽거나 사용하지 않았다. 고정 PoC dependency의 읽기 규칙만 기존 환경에서 재사용했다.

## S2-1: 독립 오프라인 원문 준비와 검사

`prototype/bff/src/zoop_bff/ingestion_cli.py`는 설치된 BFF interpreter로 실행하는 **내부 JSON 프로세스**다. FastAPI route, admin job, S1 명령이나 앱 문서 등록 API가 아니다. 명시한 전용 `--state-dir`의 `ingestion.sqlite3`만 쓰며, 앱/S1 상태와 섞인 디렉터리는 거부한다. 디렉터리는 0700, DB·lock은 0600이고 SQLite WAL·FULL commit·foreign key와 OS 독점 잠금을 사용한다. 원본 응답과 문서 바이트는 같은 DB의 SHA-256 content-addressed BLOB에 저장하므로 checkpoint가 미게시 파일을 가리키는 문제가 없다. 원본 PoC checkout은 import하지 않고 기존 pinned 설치본의 URL 검증·HTML scope/noise/access 검사·PDF decoding/preflight helper만 한 adapter에서 재사용한다. 의존성이나 lock 변경은 없다.

### 명령과 권한

wire schema는 `zoop-ingestion-s2-1`이다. 알 수 없는 필드·버전은 거부하며, `ingestion_contracts.py`의 strict 모델이 실행 계약을 소유한다. stdout은 JSON 한 객체다. 등록 전 오류는 `{schemaVersion,error:{code}}`와 종료 코드 2를 반환하고, 등록 이후 운영 실패는 `state=incomplete`와 저장된 `failure.code`를 반환한다. `state=complete`는 원문 준비 회차의 완료이며 분석·게시 성공이 아니다.

| 명령 | stdin 필드 | 별도 파일 |
|---|---|---|
| `run` | `schemaVersion,roundId,sourceId,scopeId,window,checkpointRevision,fixtureManifestHash,cleanerVersion` | `--sources`, `--fixture-manifest` |
| `resume` | `schemaVersion,roundId,sourceId` | 새로 읽는 현재 `--sources` |
| `inspect` | `schemaVersion,roundId,sourceId`; 선택적으로 정확한 `documentId,documentVersion` | 현재 `--sources` |

`window`는 null 또는 timezone이 있는 `{from,through}`다. `cleanerVersion`은 현재 `exact-copy-1`만 지원한다. `inspect`의 메타데이터는 `offset,limit`(기본 50, 최대 100)으로 안정적인 페이지/후보 순서를 나누고, 본문은 정확한 문서·버전 하나를 선택한 경우에만 반환한다. 좌표 해석에는 추가로 `locatorId,start,end`를 보내며, clean interval과 겹치는 원문 span을 산술로 계산한다. 같은 문자열을 원문에서 검색해 위치를 추정하지 않는다.

registry는 `{schemaVersion,revision,sources}`의 **현재 완전한 snapshot**이다. source는 `sourceId,adapter="authored-files",inputRoot,allowedHosts,scopes,grant`를 가진다. scope는 `scopeId,selection,initialCursor,articleXPath,timestampLimitations`를 고정한다. grant는 기존 `grantId,revision,sourceId,enabled,rights,allowedOperations,recipients,purposes,evidence,expiresAt` 어휘를 보존한다. 수집/정제에는 read·store가 필요하고, 내부 본문 검사에는 read, 원문 인용 span 검사에는 read·quote-display가 필요하다. model-send를 요구하거나 저장 권한에서 추론하지 않는다. 누락·disabled·unknown·만료·권한 근거 부재는 거부한다. raw 접근·내용 commit·checkpoint·본문 반환 직전에 현재 파일을 다시 대조하며, 실행 중 atomic 교체가 일어나면 rollback/중단하고 명시적 resume에서 새 snapshot을 읽는다. 과거 실행의 registry hash/BLOB이 현재 권한을 복구하지 않는다.

fixture manifest는 권한 파일이 아니다. `{schemaVersion,sourceId,scopeId,pages,documents}`를 가지며 모든 응답은 `{file,sha256}`로 고정한다. page는 `pageId,cursor,response,status,nextCursor,terminal,coverageThrough`를 선언하고, 저장하는 discovery JSON은 `{items,more,nextCursor}`다. item은 supplier ID·원래 URL·본문 ref·media type·제목·published/modified/source revision을 구별한다. `documents`는 body ref에서 응답 파일로 연결한다. 입력은 source의 명시적 absolute namespace 안의 상대 파일만 읽는다. traversal·절대 경로·URL·symlink·device/FIFO·hash 불일치를 거부하며, 파일이 없어도 HTTP로 전환하지 않는다. JSON은 2 MB, raw 문서는 10 MB, 추출 text/source representation은 500,000 code point로 제한한다. node/segment 수에도 상한이 있다.

### 영속성과 좌표의 의미

- source-local supplier ID가 우선이며, 없으면 pinned PoC의 최소 canonical URL을 쓴다. query 순서를 바꾸거나 tracking parameter를 삭제하지 않는다. URL fallback 뒤 유일하고 충돌 없는 supplier ID가 확인되면 기존 document ID에 alias를 붙인다. 경쟁하는 URL identity는 조용히 합치지 않으며, supplier를 확정할 수 없는 후보는 raw를 보존하고 identity hold로 남긴다. 같은 이벤트·같은 본문이어도 다른 supplier/source 문서는 별개다.
- `rawHash`는 수신 바이트의 SHA-256이고, S1 `sourceHash`는 canonical JSON string의 digest다. raw revision에는 안정적인 문서 metadata를 포함하되 observed time·round·grant revision은 제외한다. parser/cleaner·text hash·mapping digest를 포함한 `documentVersion`과 locator는 불변이다. 같은 입력은 재사용하고 바이트만 바뀌어 정제 text가 같아도 raw/text lineage를 새로 보존한다.
- 현재 adapter의 동적 본문 선택 설정인 `articleXPath`도 `parserProfile`에 고정하고 preparation key·`documentVersion`에 포함한다. 서로 다른 selector는 정제 text가 같아도 별도 준비 버전이다. scope ID·grant revision 같은 권한 이력을 원문 identity/raw revision으로 섞지 않는다. selector가 바뀐 새 scope는 이전 scope의 text나 parse hold를 재사용하지 않으며, selector binding이 없는 옛 profile의 본문 조회는 `preparation_profile_unbound`로 거부한다.
- raw save·정제 결과/hold save·page/checkpoint commit은 독립적인 복구 경계다. 저장된 입력은 resume 때 파일 없이 재사용하고, 아직 저장하지 못한 응답만 원래 hash의 파일이 필요하다. 페이지의 모든 raw·text 결과 또는 reasoned hold가 durable해야 연속 cursor를 옮긴다. 부분 discovery·항목 오류·누락 body는 페이지를 끝내지 않는다. 유효한 zero와 비영(非零) discovery의 버전 재사용은 counts/completion으로 구별한다.
- 여러 supplier 후보가 같은 body hash를 가리키면, 현재 권한을 다시 확인한 뒤 **동일 source/round slice에서 실제로 저장한 문서 BLOB**을 재사용한다. 다른 source/round의 global BLOB을 hash만으로 가져오지 않는다. 첫 후보의 raw commit 뒤 입력 파일이 없어져도 다음 후보를 이어 준비하며, supplier별 document/raw/text identity는 별개로 유지한다.
- 성공한 조회 범위는 모든 페이지와 terminal coverage가 확인된 경우만 이동한다. `more=true`에서 fixture가 끝나면 incomplete다. 마지막 transaction에서도 checkpoint revision을 비교하므로 오래된 round가 새 checkpoint를 덮지 못한다. 완료된 과거 round는 현재 checkpoint 문맥과 자신의 완료 revision을 함께 반환한다.
- HTML 위치는 원래 parsed DOM의 절대 path·text/tail slot과 저장된 **decoded node string**의 Unicode `[start,end)`다. entity 확장·HTML repair 뒤의 위치이며 markup byte offset은 아니다. inline node를 잇는 인용은 각 원래 span을 보존하고, 제거한 noise의 surviving tail도 원래 slot을 유지한다. 삽입한 block/noise separator에는 좌표를 만들지 않는다.
- PDF는 최대 30초로 감독하는 disposable child에서 PoC의 raw/page/decoded/aggregate/filter 예산과 encrypted/external decoder 거부를 유지한다. 각 page의 수정하지 않은 추출 문자열·page hash·1-based page number를 저장한다. 모든 page가 비어 있어 `no_usable_body` hold가 된 경우에도 frozen page table을 private preparation에 보존하고, bounded 후보 metadata에 page/empty-page 수와 representation hash를 반환한다. output limit이면 hold하며 잘린 text를 성공으로 반환하지 않는다. 좌표는 page-extracted text의 code point이지 PDF byte·glyph·bounding box·OCR·시각적 읽기 순서 보장이 아니다.
- 내부 S1 `Document` projection은 최대 연속 mapped run만 `rawLocators`로 제공한다. 생성 separator나 PDF page 경계를 가로지르는 인용은 기존 `exact()`에서 거부된다. S1 schema·exact 규칙·권한 검사는 변경하지 않았다. 이것은 앱 Dataset 문서나 PoC `Article.version` 등록이 아니므로 기존 BFF importer를 우회하지 않는다. 기업 연결·현재 문서 소유권·public registration·publication·유료 semantic validation은 이 실행에 없다.

### 실제 재현 결과

저장소 루트에서 실행하는 재현 명령은 다음과 같다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=prototype/bff/src \
  prototype/bff/.venv/bin/python -m pytest prototype/bff/tests/test_ingestion.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 prototype/bff/.venv/bin/python prototype/bff/scripts/ingestion_smoke.py
```

2026-10-08에 BFF 디렉터리에서 첫 명령과 동등한 `PYTHONPATH=src .venv/bin/python -m pytest tests/test_ingestion.py -q -p no:cacheprovider --basetemp <소유 임시 디렉터리>`를 최종 실행하여 **43 passed, 1 warning**을 확인했다. warning은 기존 conftest의 Starlette HTTPX deprecation이다. 최초 실행은 XPath wire alias 불일치로 36 failed/3 passed였고 명시 alias로 고쳤다. 다음 실행의 1 failed/38 passed는 과거 문서 조회에서 현재 checkpoint도 고정돼야 한다는 잘못된 시험 기대였으며, 불변 document/map과 현재 checkpoint를 따로 대조하도록 수정했다. 초기 39개 시험에 아래 review 회귀 4개를 더했다. 최종 시험은 raw/clean save 복구, commit 안의 권한 변경 rollback, 최종 checkpoint CAS, identity 모호성, 권한·범위 누락, HTML entity/tail/emoji, PDF encrypted/page/output/external decoder hold와 scope별 준비 identity를 포함한다.

실제 `ingestion_smoke.py`는 합성 HTML/PDF 두 문서에서 `status=passed, preparedDocuments=2, providerCalls=0, modelCalls=0`을 반환했다. 같은 cursor replay·변경 body의 새 버전·서로 다른 supplier·zero/failed/partial/hold·registry 철회/누락·정확한 HTML/PDF span·기존 S1 exact의 separator 거부를 실제 JSON subprocess로 실행했다. page receipt/raw/version/checkpoint 각각의 commit 뒤 프로세스를 종료 코드 75로 중단한 뒤, 이미 저장한 입력 파일과 manifest를 없애고 새 프로세스 resume으로 복구했다. 별도 stale round는 새 revision을 유지하면서 `checkpoint_stale`을 반환했다. 앱/S1 sentinel 파일은 unchanged였으며 ingestion 전용 파일만 생겼다.

review에서 지적한 두 문제도 수정 전에 재현했다. A/B가 같은 source·supplier·raw·metadata에 서로 다른 XPath를 쓰고 A scope를 registry에서 제거했는데, B가 A의 text/hold를 재사용했다. 저장된 B version에서 실제 `이전 A😀`를 확인했다. 또 서로 다른 두 supplier가 같은 body ref를 쓰는 subprocess를 첫 raw commit 뒤 종료하고 원문 파일·page·manifest를 제거하니 resume이 incomplete였다. 세 재현 시험은 수정 전 모두 실패했다. selector profile binding과 같은 source/round의 저장 raw 재사용으로 고친 뒤, 동일 본문을 선택하는 서로 다른 XPath와 grant revision 변경의 무재준비까지 포함해 43개 시험이 통과했다. 중간 1 failed/42 passed는 기존 missing-body fixture가 이미 저장한 원문과 같은 hash를 썼기 때문이며, 정말 미저장인 다른 바이트의 body로 바꿔 checkpoint 미전진·복구 조건을 유지했다. 실제 smoke의 `reviewRegressions`도 A-ready/B, A-hold/B, 첫 raw commit 뒤 공유 body 복구 세 항목 모두 통과했다.

suite의 소유 임시 상태와 smoke의 모든 원문·DB·lock·sentinel은 실행 뒤 제거했다. `ingestion_smoke.py`는 매번 fresh `TemporaryDirectory`를 만들고 제거 여부를 출력한다. 남긴 것은 재현 가능한 authored helper와 behavioral tests뿐이다. 실제 공급원·네트워크·모델·새 서비스·원본 PoC 상태·앱/S1 상태에 연결하지 않았다. 실운영 공급원 pagination/late-registration 보장, 정기 수집, 회사/이슈 연결, 앱 등록·공개와 S2-2/S3/S4는 별도 범위다.

Main의 최종 통합 실행에서도 BFF 전체 **353 passed, 1 warning**과 위 실제 CLI smoke의 전체 항목·review 회귀 3개 통과를 확인했다. 두 review 지적은 수정 후 해당 경로의 독립 소스 재검토에서 resolved로 확인됐다. OpenAPI/기존 합성 계약 검사와 생성 문서 drift **274개**, XLSX **9시트·45,428셀** 비교도 통과했고 원문 경고·목표/BFF 차이333건은 보존했다. 공개 OpenAPI·의미 연결·웹 생성 타입·S1 contracts/CLI·BFF manifest/lock의 SHA-256은 작업 시작 때와 동일하다. 이는 기존 팀 검토본과 S1 경계를 보존한 증거이며 전체 운영 보안이나 실수집 품질 인증이 아니다. 커밋·푸시·배포는 수행하지 않았다.


## S2-2: 오프라인 이벤트·SAME·주제 후보 준비

`prototype/bff/src/zoop_bff/extraction_cli.py`는 설치된 BFF interpreter로 실행하는 **내부 JSON 프로세스**다. FastAPI route, S1 명령, 앱 문서 등록·게시, 스케줄러, GraphDB writer가 아니다. wire schema는 `zoop-extraction-s2-2`이며 S1 schema의 alias가 아니다. 결과는 후보일 뿐 ALLOW·승인·게시가 아니고, **authored replay는 독립 AI 추론이 아니다.** replay는 사람이 작성한 응답을 pinned PoC parser로 검증하는 방법이며 의미 품질을 증명하지 않는다. live mode는 `live_mode_unsupported`로 거부하고 fake fallback을 두지 않는다.

| 명령 | stdin | 파일 인자 |
|---|---|---|
| `run` | `{schemaVersion,jobId,provenance,promptVersion,incoming,catalogue,snapshot,topic}` | `--replay` 필수, `--topic-replay` 선택 |
| `resume` | `{schemaVersion,jobId}` | 선택적 같은 `--replay`/`--topic-replay` |
| `inspect`, `cancel` | `{schemaVersion,jobId}` | 없음 |

공통 인자는 `--state-dir`(전용 `extraction.sqlite3`·`extraction.lock`만 허용), `--ingestion-state-dir`(읽기 전용 입력), `--sources`(S2-1과 같은 현재 완전한 registry)다. 알 수 없는 필드·schema/format/ledger 버전, app·S1·ingestion·원본 PoC 디렉터리, 겹치거나 알 수 없는 파일이 있는 mixed root는 거부한다. `incoming`과 snapshot member는 정확한 관측 `{roundId,sourceId,page,ordinal,documentId,rawVersion,documentVersion}`이다. snapshot은 운영자가 얼린 **whole-event 목록**이며 각 member는 원본 PoC `Mention` JSON(이전 결과의 `mention`)이다.

### 정확한 입력 export와 binding

S2-1에 좁은 additive 명령 `ingestion_cli export`와 `Ingestor.export`를 추가했다. 정확한 관측(round/source/page/ordinal/document/rawVersion/documentVersion)만 받아 현재 read·quote-display 권한을 확인하고 기존 S1 `Document` projection과 별도로 서버 소유 URL·title·publishedAt·modifiedAt·sourceRevision·mediaType·page observedAt·grant ID/revision을 반환한다. 클라이언트가 보낸 metadata는 신뢰하지 않는다. 이 소비자 접근(`Store(existing=True)`)은 **실제 읽기 전용**이다. 디렉터리·파일 mode/소유권 보정(chmod), 생성, schema/PRAGMA/WAL 쓰기 없이 `immutable=1` 읽기 전용 SQLite로 열고, 시험이 일부러 0750/0640/0440으로 바꾼 mode·bytes·mtime·파일 목록이 export와 extraction 실행 전후 같음을 확인한다. lock 정책은 기존 `ingestion.lock`에 대한 **shared non-blocking flock**이다. reader끼리는 공존하고, 활성 writer가 있으면 reader가 `ingestion_busy`, reader가 있으면 새 writer도 `ingestion_busy`다. 비어 있지 않은 `-wal`(중단된 writer가 남긴 commit)은 reader가 무시하거나 복구할 수 없으므로 `ingestion_recovery_required`로 거부하고, 운영자가 ingestion `resume`으로 복구한 뒤 다시 읽는다. 없는 namespace는 만들지 않고 `ingestion_state_missing`이다. 기존 `inspect` 결과는 같은 helper로 옮겼지만 출력이 같고 `test_ingestion.py` 43개가 통과한다.

job은 replay 호출 전에 다음을 불변 binding으로 먼저 저장한다. 실제 `investmate.Article`(publisher는 알 수 없어 빈 값, origin_id null, language는 adapter 상수 `ko`)과 **진짜 계산된 `Article.version`**, 문서별 raw/representation/mapping/locator/metadata/parser digest, grant 이름·revision, pinned PoC commit `fa446e7c…`, 추출·비교 analysis contract fingerprint, replay 헤더와 파일 hash, 회사 catalogue digest, snapshot digest와 개별 event digest다. 같은 jobId에 다른 입력·replay bytes를 보내면 `job_input_conflict`, resume에서 다른 replay bytes를 보내면 `replay_fixture_changed`다. 누락된 extract/compare 응답은 실패이며 fixture를 고쳐 같은 job에 붙이지 않고 새 job을 만든다. `Article.version`은 documentVersion을 대체하지 않는다. raw만 바뀌어 `Article.version`이 같아도 documentVersion·mention/event candidate ID·job 입력이 달라진다. 같은 comparison에 같은 Article.version이 두 documentVersion으로 묶이면 SAME/FOLLOWS evidence는 최신/첫 항목을 고르지 않고 HOLD다.

### 추출·비교·주제 stage

- **추출/비교**: 설치된 `ReplayModel.extract/compare`와 도메인 parser만 호출한다. `Pipeline`, Repository, graph, B0–B4 retrieval은 import하지 않는다. whole-event 목록의 모든 event를 비교하며 이것이 retrieval 완전성이라고 주장하지 않는다. raw `PairDecision`은 보존하고, 별도 effective decision은 Pipeline의 guard를 다시 적용한다. SAME인데 member 하나라도 period/assertion/event_time이 알려진 값으로 충돌하면 DIFFERENT, SAME/FOLLOWS의 exact evidence 부재와 FOLLOWS의 incoming evidence 부재는 HOLD다. 알 수 없는 값은 날짜나 identity를 만들지 않는다. SAME 둘 이상이거나 HOLD/CONFLICT가 있으면 선택하지 않고 `held`이며 transitive union은 없다.
- **ID**: `mentionCandidateId`(`mc-`)는 정확한 문서 binding·extract request key·fingerprint·로컬 mention ID에서, `eventCandidateId`(`evc-`)는 mention candidate에서 파생한 별도 ID다. documentId, snapshot의 event ID, mention ID, topic ID(`tp-`)는 서로 다른 namespace이며 snapshot event ID가 `mc-`/`evc-`/`tp-`로 시작하면 거부한다.
- **인용**: PoC `Evidence.matches`만 믿지 않는다. 구간은 정확히 하나의 mapped locator run 안에 있어야 하고(S1 `exact`와 같은 규칙), ingestion inspect의 source resolver로 재구성한 원문 segment 합이 quote와 같아야 한다. 생성된 separator를 가로지르면 mention은 `rejected/raw_locator_mismatch`로 남고, 반복 quote에 정확한 span이 없으면 PoC parser가 응답을 거부한다. snapshot member의 모든 evidence도 job을 저장하기 전에 같은 규칙(mapped run + resolver)으로 검사하며 실패하면 `snapshot_member_unmapped`로 거부해 SAME 비교 입력이 되지 않는다. 비교 응답이 member 문서의 separator span을 인용하면 effective decision은 HOLD다. 시험은 실제 S1 `exact`로 accept/reject를 대조한다.
- **주제**: PoC에는 topic 호출이 없으므로 별도 prototype producer 계약 `zoop-topic-request-1`/`zoop-topic-response-1`/`zoop-topic-replay-1`을 둔다. 요청은 event candidate와 snapshot event, 문서 목록이며 응답은 label·criteria·rationale·명시적 membership·정확한 문서 citation이다. 모든 member와 citation을 frozen 요청과 대조하고 알 수 없는 member, 중복 member, 요청에 없는 문서, 부정확한 quote는 received 영수증에 거부 verdict를 남기고 topic을 만들지 않는다. 사건이 없으면 producer 호출도 빈 topic도 만들지 않는다. topic은 `status=candidate, approved=false`다.

### 영속성·복구·권한

stage의 후보와 완료 marker는 한 transaction에서 commit한다. provider 영수증은 `started→received`로 분리하고 응답/request digest/fixture hash는 변경할 수 없다. replay fixture는 호출 예약 전에 전체를 설치된 `ReplayModel`로 검증하며(중복 record·key 불일치는 `replay_fixture_invalid`), 잘못된 fixture는 receipt가 되지 않는다. 순수 parser가 통과한 응답만 `received`로 저장하고, 계약을 위반한 응답은 영수증을 보존한 채 거부 verdict를 붙여 영구히 사용할 수 없다. topic membership/citation 같은 후속 검증의 응답 결함도 같은 방식이며 권한·환경 실패는 유효한 receipt를 그대로 두어 다음 resume이 다시 검증한다. resume은 저장된 receipt를 새 호출 없이 production parser로 다시 검증한다. 응답 저장 뒤·후보 저장 전 프로세스가 죽어도, stage commit 뒤에 죽어도 replay 파일 없이 재개하며 추가 호출은 0이다. `started`만 있고 receipt가 없으면 replay라도 `reconciling/reconcile_only`로 남기고 자동 재전송하지 않는다. 모든 문서는 read 전, 응답 뒤, stage commit 직전, 결과 전달 직전에 현재 registry를 다시 읽어 read+quote-display, exact binding을 확인한다. 철회·만료·registry 제거·grant revision 변경 뒤에는 `delivery=withheld`와 종료 코드 2이고 후보·인용·본문이 출력되지 않으며 이전 결과가 권한을 복구하지 않는다. `model-send`·recipient·purpose는 offline replay가 외부로 전송하지 않으므로 검사하지 않으며, live 전송을 도입하면 별도 검사가 필요하다. 이 단계는 cross-job 결과 cache를 두지 않는다. 재사용은 같은 job의 영수증뿐이다.

### 실제 재현 결과

저장소 루트에서 다음 명령을 실행했다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=prototype/bff/src \
  prototype/bff/.venv/bin/python -m pytest prototype/bff/tests/test_extraction.py prototype/bff/tests/test_ingestion.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 prototype/bff/.venv/bin/python prototype/bff/scripts/extraction_smoke.py
```

첫 명령은 **89 passed, 1 warning**(`test_extraction.py` 46 + 기존 `test_ingestion.py` 43)이었다. warning은 기존 Starlette HTTPX deprecation이다. 실제 `extraction_smoke.py`는 `status=passed, providerCalls=0, modelCalls=0`을 반환했다. authored HTML을 실제 ingestion/extraction JSON subprocess로 실행해 두 문서 same event, 서로 다른 event·같은 topic, 충돌 계약과 누락 날짜, multi-SAME hold, 한글·emoji·entity exact 인용, separator/반복 quote, raw-only version 변경, 위조 snapshot/citation, 잘못된 topic membership, 철회 grant, receipt/stage 뒤 중단·무호출 resume, started-without-receipt를 확인했다. 리뷰에서 재현한 세 문제도 수정 전 실패(중복 extract record가 receipt 저장 뒤에야 fixture 오류가 되고 fixture 없는 resume이 ready로 바뀜, separator를 가로지르는 snapshot member가 SAME 입력이 됨, `existing=True` ingestion 접근이 chmod/RW open을 함)를 확인한 뒤 같은 회귀 시험과 smoke로 고정했다. 모든 subprocess에 socket audit hook을 걸어 네트워크 시도를 오류로 만들었으며 발생하지 않았다. 임시 입력·DB·lock은 실행 뒤 제거한다. 실제 공급원·모델·원본 PoC DB·Postgres/Neo4j·앱/S1 상태에는 연결하지 않았다.

남은 범위: 실제 모델 추출·SAME 품질, B0–B4 retrieval 연결과 현재 event/topic 저장소, 앱 등록·게시·GraphDB, S3 관계·영향, S4 전체 철회 closure, 사람 승인 topic은 구현·검증하지 않았다.