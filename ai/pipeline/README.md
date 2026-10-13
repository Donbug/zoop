# ai/pipeline — S2-1 / S2-2 / S3 오프라인 프로세스와 S4 읽기 전용 의존 대상 조회

| 명령 | 모듈 | wire schema | 상태 파일 |
| --- | --- | --- | --- |
| `zoop-ai-ingest {run,resume,inspect,export}` | `zoop_ai_pipeline.ingestion_cli` | `zoop-ingestion-s2-1` | `ingestion.sqlite3` |
| `zoop-ai-extract {run,submit,resume,inspect,cancel}` | `zoop_ai_pipeline.extraction_cli` | `zoop-extraction-s2-2` | `extraction.sqlite3` |
| `zoop-ai-relation {run,submit,inspect,resume,review,revalidate,cancel}` | `zoop_ai_pipeline.relation_cli` | `zoop-relation-s3` | `relation.sqlite3` |
| `zoop-ai-dependents` (하위 명령 없음, stdin 변경 1건) | `zoop_ai_pipeline.dependency_cli` | `zoop-dependency-s4` | 위 세 원장을 읽기 전용으로만 연다(쓰는 상태 파일 없음) |

세 원장은 서로의 디렉터리를 `--ingestion-state-dir`/`--extraction-state-dir` 경로로 읽기 전용으로 엽니다(그래서 한 프로젝트입니다). 모두 authored replay 전용이며 live/네트워크 경로가 없습니다. 공개 route, 앱 문서 등록·게시, S1 DB 쓰기는 하지 않습니다. `zoop-ai-dependents`는 세 원장을 읽기만 하는 S4의 일부(영향 대상 조회)이며 철회·재생성은 하지 않습니다.

private PoC(`Donbug/investmate-poc` commit `fa446e7c72edfa06ec1a0e8e999199a21d31c695`)가 필요합니다. 로컬에서는 `gh auth setup-git` 등 git 인증, CI에서는 `ai-pipeline` job의 GitHub App 읽기 토큰(`scripts/private_poc_sync.py --project ai/pipeline`)으로 설치합니다. lxml 6.1.3·pypdf 6.19.0·pydantic 2.13.5·httpx 0.28.1은 BFF lock과 같은 버전입니다.

```bash
make pipeline-install   # uv sync --project ai/pipeline --frozen --group dev
make pipeline-test      # ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests
make pipeline-smoke     # ingestion/extraction/relation/dependents 실제 CLI 프로세스 smoke, 모델·네트워크 호출 0
make pipeline-build
```

`ai/worker`는 dev 그룹에서만 설치됩니다(S1 `exact()` 인용 동등성 시험). 런타임은 `zoop_ai`를 import하지 않습니다. 상태 루트가 `prototype/bff/var`, `ai/worker/var`, `api/var`, 이전 `prototype/ai-worker/var`, `ZOOP_STATE_DIR`/`ZOOP_AI_WORKER_STATE_DIR`와 겹치면 `state_namespace_conflict`로 거부합니다.

**설치된 패키지(wheel)의 소유권 설정:** 저장소 checkout 안에서 실행할 때만 위 저장소 경로를 파일 위치에서 알 수 있습니다. 설치본은 저장소를 추측하지 않으므로 **`ZOOP_STATE_DIR`(앱 상태 루트)과 `ZOOP_AI_WORKER_STATE_DIR`(S1 worker 상태 루트)를 둘 다 절대 경로로** 지정해야 하며, 없거나 상대 경로이면 `state_ownership_unconfigured`로 닫힙니다. 지정한 두 루트와 겹치는 `--state-dir`은 `state_namespace_conflict`입니다. smoke(`ai/pipeline/scripts/*_smoke.py`)는 값이 없으면 임시 디렉터리를 대신 지정하며 PYTHONPATH 없이 설치된 패키지로 자식 프로세스를 실행합니다.

**10/13 추가 검증 — 등록과 실행 분리:** S2/S3의 `submit`을 추가한 로컬 작업 트리에서 pipeline 전체 **228개 시험**과 `make pipeline-smoke`의 ingestion·extraction·relation·dependents 실제 CLI 검사가 모두 통과했다. 접수 시 호출 0건, 같은 요청의 재접수, 충돌 거부, 실행 전 권한 변경, 실행 전 취소, 이후 명시적 실행을 확인했다. 외부 모델·네트워크 호출은 없었다. 아래 절의 이전 시험 수치는 각 기능 도입 당시 기록이며, 이번 변경은 아직 원격 CI에서 검증하지 않았다.

# 상세 계약과 실행 증거

아래 절은 BFF README에서 옮겼으며, 시험 수치와 pass/fail 기록은 이동 전(BFF 환경) 당시 값입니다. 이동 후 `ai/pipeline` 독립 환경의 전체 시험은 142 passed이고 세 smoke가 설치 환경과 패키지 전용 격리 환경에서 모두 `status=passed`였습니다.

## 독립 오프라인 원문 준비 (S2-1, FS074·FS075 일부)

`zoop_ai_pipeline.ingestion_cli`의 `run/resume/inspect`는 BFF의 admin `ingest-run`과 **다른 내부 실행 경계**다. 설치된 `ai/pipeline` 환경의 pinned PoC parser만 재사용하고 네트워크·모델·PoC 원장·앱/S1 DB에는 연결하지 않는다. 명시한 전용 `--state-dir`의 private `ingestion.sqlite3`에 원래 response/raw BLOB, source-local 문서 ID, raw/text version, HTML node/PDF page span과 연속 checkpoint를 저장한다. 현재 operator `--sources`는 매번 완전한 snapshot으로 읽고, fixture manifest는 hash-pinned 파일 입력일 뿐 권한을 발급하지 않는다.

저장소 루트에서 다음 명령으로 합성 HTML/PDF와 실제 subprocess CLI를 재현한다. driver는 fresh 임시 입력/상태를 만들고 검사 후 모두 제거한다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/ingestion_smoke.py
```

실제 결과는 `status=passed, preparedDocuments=2, providerCalls=0, modelCalls=0`이었다. receipt/raw/version/checkpoint 저장 뒤 프로세스 중단·resume, 같은 cursor replay, 변경 body의 새 버전, zero/failure/partial/parse hold, stale checkpoint, registry 철회/누락, entity·tail·반복 한글/emoji와 PDF page 좌표, S1 exact의 생성 separator 거부를 확인했다. review 회귀까지 포함한 focused `tests/test_ingestion.py`는 **43 passed, 기존 Starlette warning 1개**였다. 실제 scope A 철회 뒤 scope B의 XPath에 맞는 text/hold 분리와, 첫 supplier의 raw commit 뒤 파일이 없어도 공유 body로 둘째 supplier를 준비하는 복구도 통과했다.

wire schema는 `zoop-ingestion-s2-1`이며 공용 OpenAPI나 S1 schema를 바꾸지 않았다. 정확한 문서/version을 고른 `inspect`만 현재 read 권한으로 내부 S1 `Document` projection을 반환한다. 원문 span 해석에는 quote-display도 요구한다. S2-2가 쓰도록 정확한 관측(round/source/page/ordinal/document/rawVersion/documentVersion)의 서버 소유 URL·title·publishedAt과 grant를 반환하는 읽기 전용 `ingestion_cli export`를 추가했다. HTML 위치는 decoded DOM text/tail 좌표이고 PDF 위치는 frozen page-extracted text 좌표이지 raw byte·glyph geometry가 아니다. 이 문서는 앱 Dataset에 등록되거나 게시되지 않는다. 실제 공급원/정기 수집·기업/이슈 연결·공개 등록/게시·유료 의미 검증은 구현 완료로 주장하지 않는다. 명령·registry·manifest·한계와 실행 증거는 [AI 실행 계약의 S2-1 절](../../docs/design/ai-system.md#s2-1-독립-오프라인-원문-준비와-검사)을 따른다.

## 독립 오프라인 이벤트·SAME·주제 후보 (S2-2)

`zoop_ai_pipeline.extraction_cli`의 `run/submit/resume/inspect/cancel`은 S2-1 ingestion 상태를 **읽기 전용**으로 소비하고 전용 `--state-dir`의 `extraction.sqlite3`에만 쓴다. 설치된 pinned PoC의 `Article`·`ReplayModel.extract/compare`·`incompatible` 순수 계약만 쓰며 Postgres·Neo4j·Pipeline·네트워크·모델·앱/S1 상태에는 연결하지 않는다. authored replay는 독립 AI 추론이 아니고, 결과는 승인·게시가 아닌 event/topic **후보**다. 이벤트 후보는 정확한 인용(S1 exact와 같은 mapped-run 규칙 + ingestion resolver), whole-event 비교(all-member 충돌·근거 부재·multi-SAME hold), 문서/mention/event 별도 ID를 갖고 topic 후보는 별도 `zoop-topic-*` 계약·영수증으로 만든다. 저장소 루트에서 재현한다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_extraction.py ai/pipeline/tests/test_ingestion.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/extraction_smoke.py
```

**등록 전용 `submit`(CLI 명령이다. HTTP는 `ai/service`의 별도 `/internal/v1/extraction-jobs` 가족이 서버 사전 승인 요청으로만 호출하며 호출자가 본문·fixture를 고르지 못한다).** `extraction_cli submit`은 `run`에서 등록 절반만 분리한 명령이다. 같은 stdin 요청과 필수 `--replay`로 입력과 replay 파일 hash를 불변 binding으로 먼저 저장해 `queued` job을 만들고 `inspect`와 같은 결과를 돌려준다. replay 모델 구성·stage 실행·호출 예약·후보 쓰기·네트워크는 없고(`calls=[]`, `usage.replayCalls=0`) 등록 때 ingestion과 `--sources`는 읽는다. replay 파일 hash가 job 입력 digest에 들어가므로 `--replay`가 필요하고(없으면 `replay_fixture_required`), job에 고정되지 않는 `--topic-replay`는 `fixture_not_allowed`이며 topic stage의 fixture는 이후 `resume`/`run`에서만 지정한다. live provenance는 `live_mode_unsupported`다. 같은 `jobId`와 같은 입력의 재제출은 저장된 job을 `inspect`처럼 보고만 한다. queued·stopped·ready·cancelled 어느 상태에서도 resume·재고정·상태 초기화·호출을 하지 않으며 현재 권한은 반환 결과의 `delivery`에만 적용된다(철회·grant revision 변경이면 `withheld`와 종료 코드 2이지만 고정된 binding은 바뀌지 않는다). 다른 입력이나 다른 replay bytes는 아무것도 쓰지 않고 `job_input_conflict`이며, 잘못된 fixture를 고정한 job은 같은 jobId로 고칠 수 없어 새 jobId를 쓴다. 실행은 이후 `resume`(필요한 같은 `--replay`)이 하고 권한·binding은 그때 다시 검사하므로 submit 뒤 철회·grant revision 변경은 호출 없이 `stopped`다. queued job은 `cancel`로 호출 전에 취소할 수 있다. `run`은 같은 등록 경로(`Extractor.freeze`) 뒤 `resume`하는 기존 편의 명령이며 동작은 그대로다. 아래 시험·smoke 수치는 submit 추가 이전 기록이고, submit 회귀 시험(`test_extraction.py`의 submit 절)과 smoke 12단계의 통과는 최종 실행 결과로만 기록한다.

실제 결과는 **90 passed, 1 warning**(extraction 47 + ingestion 43, 기존 Starlette warning)과 smoke `status=passed, providerCalls=0, modelCalls=0`이었다. smoke는 실제 ingestion/extraction subprocess에 socket audit hook을 걸고 same/distinct event·topic, 충돌·누락 날짜, multi-SAME, 한글/emoji/separator/반복 quote, raw-only 변경, 위조 입력, 철회 grant, receipt/stage 중단 복구, 잘못된 fixture의 receipt 미생성, separator snapshot member 거부, ingestion 읽기 쪽 mode/bytes/파일 불변을 검사한다. ingestion `export`와 extraction의 ingestion 접근은 shared flock과 `immutable=1` 읽기 전용 열기이며 중단된 writer가 남긴 비어 있지 않은 WAL은 `ingestion_recovery_required`로 거부한다. S3 소비자용 `Store(existing=True)`/`Extractor.export`도 같은 읽기 전용 정책이다. live 전송·retrieval·cross-job cache·앱 등록·승인 topic은 구현하지 않았다. wire/binding/복구 규칙은 [AI 실행 계약의 S2-2 절](../../docs/design/ai-system.md#s2-2-오프라인-이벤트same주제-후보-준비)을 따른다.

## 독립 오프라인 관계·영향 후보와 HOLD 재검증 (S3, FS078·FS079)

`zoop_ai_pipeline.relation_cli`의 `run/submit/resume/inspect/review/revalidate/cancel`은 **완료된 S2 job 하나**(`upstream:{jobId,inputDigest}`)를 extraction·ingestion의 읽기 전용 snapshot으로만 소비하고 전용 `--state-dir`의 `relation.sqlite3`에만 쓴다. 호출자가 후보 JSON을 보낼 수 없고 event/topic 후보·catalogue·문서는 서버 소유 registry로 다시 검증한 S2 결과에서만 온다. producer replay(`--replay`)와 **독립된** verifier replay(`--verifier-replay`)는 별도 파일·영수증이며 둘 다 authored 응답일 뿐 AI 의미 품질 주장이 아니다. 후보는 `approved=false`이며 `eligible`은 자동 증거 gate 통과이지 승인·게시가 아니다. 공개 OpenAPI·HTTP·UI·GraphDB·앱 등록·관리자 화면은 없다. 관계 유형(`SUPPLIES`·`INVESTS_IN`·`COMPETES_WITH`·`PARTICIPATES_IN`·`RELATES_TO_TOPIC`)은 FS055 공통 계약 확정 전의 보수적 임시 어휘다. 저장소 루트에서 재현한다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_relation.py ai/pipeline/tests/test_extraction.py ai/pipeline/tests/test_ingestion.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/relation_smoke.py
```

**등록 전용 `submit`(CLI 전용, HTTP 아님).** `relation_cli submit`은 `run`의 등록 절반이다. 완료(ready)되고 현재 권한·binding이 검증되는 S2 job이 있어야 하며 아니면 `upstream_not_ready`(또는 S2의 withheld 코드)로 거부되고 job은 만들어지지 않는다. 성공하면 upstream identity와 `upstream.digest`를 불변 binding으로 고정한 `queued` job을 만들고 `inspect`와 같은 결과를 돌려준다(`calls=[]`, `usage.replayCalls=0`). **S3 submit은 fixture를 받지 않는다.** `--replay`와 `--verifier-replay`는 `fixture_not_allowed`다. S2와 달리 producer·verifier fixture는 job binding이나 입력 digest에 들어가지 않고 호출별 영수증(`calls.fixture_hash`)에만 기록되는 입력이어서 이후 `resume`/`run`/`revalidate`가 단계마다 지정한다. live provenance는 `live_mode_unsupported`다. 같은 `jobId`와 같은 입력의 재제출은 저장된 job을 `inspect`처럼 보고만 한다. queued·stopped·ready·cancelled 어느 상태에서도 resume·재고정·상태 초기화·호출·HOLD 검토 반영(재검증)을 하지 않으며 현재 권한은 반환 결과의 `delivery`에만 적용된다. 다른 입력(다른 upstream 포함)은 `job_input_conflict`다. 실행 때 현재 upstream·권한·binding을 다시 확인하므로 submit 뒤 S2의 권한·grant revision이 바뀌면 호출 없이 `stopped`다. queued job은 `cancel`로 호출 전에 취소할 수 있다. `run`은 같은 등록 경로(`Engine.freeze`) 뒤 `resume`하는 기존 편의 명령이며 동작은 그대로다. 아래 시험·smoke 수치는 submit 추가 이전 기록이고, submit 회귀 시험(`test_relation.py`의 submit 절)과 smoke 13단계의 통과는 최종 실행 결과로만 기록한다.

실제 결과는 **142 passed, 1 warning**(relation 52 + extraction 47 + ingestion 43)과 smoke `status=passed, providerCalls=0, modelCalls=0`이었다. smoke는 실제 ingestion·S2 extraction으로 만든 upstream을 relation subprocess(socket audit hook)로 읽어 방향 뒤집힘 hold, 경쟁 쌍 정규화, 같은 쌍의 다른 유형·범위 보존, 경로 단계 누락·알 수 없는 endpoint hold, 직접 대 2단계, mixed/positive/undetermined와 eligibility 분리, HOLD allow→재검증과 재검증 receipt 뒤 중단 복구(fixture·추가 호출 없이 verdict append), receipt 뒤 중단 복구, 위조 upstream·fixture, 철회 권한, upstream bytes/mode 불변을 검사한다. 명령·wire·gate·한계는 [AI 실행 계약의 S3 절](../../docs/design/ai-system.md#s3-오프라인-관계영향-후보와-hold-재검증)을 따른다.

## 읽기 전용 의존 대상 조회 (S4 일부, FS081 일부)

`zoop_ai_pipeline.dependency_cli`(설치 명령 `zoop-ai-dependents`)는 변경된 **문서(선택: raw/문서 version)·source·grant(선택: revision) 하나**를 받아 ingestion·extraction(·선택적 relation) 원장에 이미 고정된 기록에서 그 변경에 기대는 S2 job·snapshot event·event 후보·비교·주제와 S3 job·관계·영향 후보를 나열한다. `Store(existing=True)`로만 열고 shared lock을 출력이 끝날 때까지 모두 유지하며, 현재 registry·권한·delivery를 판정하거나 어떤 것도 쓰지·철회하지·재생성하지·게시하지 않는다. 변경 모양의 null은 묶인 모든 값(과거 포함)이지 "최신"이 아니고, 일치 기준은 job을 만들 때 고정한 관측과 grant(현재 registry 아님)다. 출력은 ID·digest·좌표·상태·reason 코드뿐(원문·quote·제목·URL·경로 없음)이며 `notCovered`에 스캔하지 않은 범위가 항상 명시된다. 완전성은 스캔한 원장에 한정되고 전체 철회 closure가 아니다.

```sh
zoop-ai-dependents --ingestion-state-dir DIR --extraction-state-dir DIR [--relation-state-dir DIR] < query.json
# query.json: {"schemaVersion":"zoop-dependency-s4","changed":{"kind":"document","documentId":"…","documentVersion":null,"rawVersion":null}}
#             {"kind":"source","sourceId":"…"}  |  {"kind":"grant","grantId":"…","revision":null}   (null 키도 생략 불가)
```

`--relation-state-dir`를 생략하면 `relation`은 `null`이다(빈 목록이 아니다). 없는 디렉터리·손상·hot WAL·활성 writer·알 수 없는 원장 버전·파싱되지 않는 저장 행·배열이 아닌 의존 container(citations·path·topic members 등)·ingestion 원장에도 없는 변경 ID는 부분 출력 없이 exit 2의 오류 코드로 닫힌다(성공-빈 결과가 되지 않는다). 항목이 10,000개를 넘으면 자르지 않고 `dependency_report_limit`로 거부한다. relation job은 S3가 고정한 upstream으로만 스캔한 extraction job과 연결한다. `(jobId, inputDigest)`는 요청·replay만 덮고 고정된 grant는 덮지 않으므로, 추가로 S3 binding의 `upstream.digest`(고정된 binding·grant와 전달 후보)를 저장 행에서 다시 계산해 비교한다. upstream이 스캔한 원장에 없거나(`upstream_not_in_scanned_ledger`), 입력 digest가 다르거나(`upstream_input_mismatch`), ready가 아니거나 digest가 다른 경우(`upstream_binding_mismatch`, 예: 같은 job·입력이 다른 grant revision으로 고정된 원장)는 영향 여부를 판단하기 전에 버리지 않고 `unresolved`로 나열한다. 각 job의 `jobScope`는 job 전체 개수이고 직접 항목은 그 부분집합이다. 이 명령은 CLI 전용이며 HTTP·OpenAPI·앱 DB에 연결하지 않았다. relation 원장에도 `Store(root, *upstream_roots, existing=True)` 읽기 전용 모드를 추가했고 기존 호출은 그대로다. 명령·wire·reason 코드·한계 상세는 [AI 실행 계약의 S4 절](../../docs/design/ai-system.md#s4-일부-s2s3-의존-대상-조회-읽기-전용)을 따른다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_dependency.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/dependency_smoke.py
```

10/13 최종 로컬 작업 트리에서 전체 pipeline 시험 **208 passed**, `dependency_smoke.py`는 **status=passed, providerCalls=0, modelCalls=0**이었다. 실제 CLI에서 권한 철회 후 메타데이터 조회, 같은 job·입력이라도 다른 grant에 고정된 upstream의 불일치, 잘못된 원장·입력의 거부, 원문 미노출과 원장 무변경을 확인했다. 검토 후 추가한 회귀 15건도 모두 통과했다. 실행 조건·수정 전 재현 범위·남은 기능은 위 S4 계약을 따른다. 이번 변경의 원격 CI·운영 배포는 실행하지 않았다.
