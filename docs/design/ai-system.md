# AI 실행과 문서 공개 계약

## 현재 구현 범위와 설계 논의 적용

**현재 실행 단위는 S1 문서 요약·문서×기업 판정·별도 의미 검증이며, 기존 회차 outlook 생성 기능도 worker 경계로 보존·이행한다. 전체 AI 기능이나 FS074–081 전체의 완료를 뜻하지 않는다.** 설계 보고서 `local://ai-contract-design.md`의 §3–6과 §8/S1에서 합의한 worker 소유 경계, camelCase JSON, 불변 영수증, 현재 공개 gate, 무호출 저장 복구를 적용한다. 기존 outlook 생산자를 삭제하지 않는다는 추가 합의도 반영했다. 보고서는 설계 근거이며 실행 증거는 아니다.

| 실행 단위 | 현재 상태 | 소유 의미와 후속 범위 |
|---|---|---|
| S1 | 구현: 문서 세 stage + 기존 briefing-outlook 이행 + 실제 JSON CLI + BFF 수입 | 문서의 versioned claim/citation과 기업별 판정을 검증·저장하고, 기존 회차 판정의 생성·발행 고정을 유지한다. |
| S2 | 계획, 미구현 | 수집 회차·cursor·정제/raw 위치, 기존 PoC 추출/SAME 재사용, 별도 주제형 이슈 |
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

`resultVersion`은 공개 요약이 있으면 그 요약 버전, 요약 없이 판정만 있으면 판정 버전이다. summary citation의 document/version/resultVersion과 evidence 응답 문맥을 프론트엔드가 대조한다. JS/Java는 UTF-16 index를 그대로 쓰면 안 된다. `offsetUnit=unicode_code_point`, `end`는 exclusive이고, exact 검증 때 공백·NFC·따옴표를 임의 정규화하지 않는다. S1 합성 표본의 cleaner는 identity이며 raw locator도 명시한다. 실제 HTML/PDF 정제·복수 raw locator 복원 전체는 S2에 남아 있다.

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

| 기능 | S1에서 구현한 부분 | 아직 남은 부분 | 확인 코드/표본 |
|---|---|---|---|
| 문서 긍부정 / 뉴스 요약 | 기업별 독립 판정과 summary claim·근거·버전·실제 provider/replay→BFF GET | 실제 승인 모델/운영 품질·비용 결정 | `test_documents.py`, BFF `test_sentiment.py`, synthetic-document fixture |
| 기존 회차 outlook 보존 | 실제 worker provider/replay·정확 참조/금지 표현 정책·미발행 회차 생성·발행 고정·0이슈 무호출 | 새 기업/시장 요약과 강화된 별도 의미 검증은 S5 등 후속 범위 | `test_outlook.py`, `test_outlook_worker.py`, `replay_outlook_fixture.py` |
| FS075 | Unicode codepoint exact 인용, 동일입력 멱등, immutable 문서 version/citation 대조 | 실제 수집/HTML·PDF locator/cleaner 수정 전체 | emoji·한글 fixture 및 invalid span 시험 |
| FS080 | 호출 예약·received receipt·validated artifact·앱 import commit 분리, 같은 결과 수입 멱등 | GraphDB 양쪽 projection/readiness·manifest CAS 전체 | 저장 실패/수입 rollback 시험 |
| FS081 | 문서 두 consumer의 현재 deny/version/hash gate, 저장 복구 시 새 호출 없음 | 전체 dependency closure·옛 채팅/회차/pin 제외 | direct evidence deny·cache/model/effort/version 시험 |
| FS066/068 연동 | 문서 요약·기업판정·의미검증의 actual/replay 영수증을 관리자 사용량에 분리 연결 | S7 전체 평가·개인 결과 통합 | 관리자 ai-usage 수입 중복/토큰 null 시험 |
| FS074/076/077/078/079 | S1에서 완료 주장하지 않음 | S2–4의 수집·주제·관계·영향·검수 | 설계 scope 표 |

이 문서의 구현 설명은 위 source와 합성 계약을 가리킨다. 실제 운영 모델의 의미 품질, 출처 라이선스 최종 승인, 금액 상한, S2–7은 검증된 완료 항목이 아니다.

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
