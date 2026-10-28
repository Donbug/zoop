# ai/evaluation: 기록된 출력의 결정적 채점 하네스

이미 기록된 그래프 구성·검색·답변 출력과 trace를, 따로 작성한 gold와 비교해 채점한다. 표준 라이브러리만 쓰며(Python 3.12 이상) 채점기는 모델·네트워크·그래프 DB를 호출하지 않는다(예외: 아래 그래프 도구 baseline의 `measure`가 설치된 `zoop-ai-graph` CLI를 subprocess로 호출하고, 그 CLI가 승인된 loopback Neo4j를 읽는다. 모델·provider 호출은 0이다). 지표 정의, 데이터 분리, gold 검수, baseline과 측정 계획, 승인 경계는 [`docs/design/ai-benchmark.md`](../../docs/design/ai-benchmark.md)에 있고 여기서 반복하지 않는다.

## 실제 자료 intake와 다음 평가

[`corpus/external-pilot-v1/manifest.json`](corpus/external-pilot-v1/manifest.json)에 KLUE RE train 첫 20행과 TAT-QA 공식 dev 첫 5개 context·30개 질문의 출처·권리·원본 식별·파일 해시를 기록했다. 입력/gold 네 파일을 분리해 저장했고 해시·크기·고유 ID·KLUE entity span 40개·원래 annotation 복원 일치·입력의 gold annotation 키 부재를 확인했다. 번역·모델 호출은 없었다.

이 자료는 **원자료 순서로 선택해 이미 열람한 개발용 표본**이며 대표 표본이나 held-out test가 아니다. KLUE row 응답과 관측한 HF revision의 결합은 미검증이다. `materials-validate`·`materials-inputs`·`materials-gold`는 읽기 전용 adapter이며, `materials-retrieve`·`materials-retrieval-score`는 TAT-QA의 주어진 context 안에서 문단을 선택하고 별도로 채점한다. 모델 runner나 답변 채점은 아니다. 기존 `score`·`verify-score`·`summary-verify-score`는 원자료·material artifact·새 retrieval run 모두 받지 않으며 0점으로 대신 처리하지 않는다.

한국어 실제 공시의 사람 합의 gold를 주 평가로 삼고 영어 QA는 별도 보조 평가로 둔다. 자료 후보·권리 조건, G/R/A/J 트랙, B0–B4 대조군, `gpt-6-luna High`·`jev-1.14.0` 고정, dev/test 동결과 실행 순서는 [설계 문서의 실제 자료·gold 제작 프로토콜](../../docs/design/ai-benchmark.md#실제-자료와-gold-제작-프로토콜)을 따른다. 현재 문단 검색은 **B1의 검색 단계 준비**다. 한국어 공시 수집 승인·사람 합의 gold·전체 문서 검색·방향/시점 고정 순회·생성기 연결·제한된 live 승인·동결 실행은 남아 있다. 이 구현을 전체 RAG/벤치마크 완성이나 한국어 금융·모델 품질 측정으로 표시하지 않는다.

### 읽기 전용 material 명령

`ai/evaluation`에서 실행한다. `--materials` 기본값은 `corpus/external-pilot-v1`이며 출력은 stdout JSON뿐이다. 파일을 생성하지 않고 네트워크·모델·provider·애플리케이션 환경 설정이나 `.env`를 읽지 않는다. `-B`는 Python의 bytecode 파일 생성을 막는다.

```bash
python3 -B -m zoop_eval materials-validate
python3 -B -m zoop_eval materials-inputs --dataset klue-re
python3 -B -m zoop_eval materials-inputs --dataset tatqa
python3 -B -m zoop_eval materials-gold --dataset klue-re
python3 -B -m zoop_eval materials-gold --dataset tatqa
python3 -B -m unittest discover -s tests -p 'test_materials.py'
python3 -B scripts/materials_smoke.py
```

| 명령·출력 schema | 확인하는 범위 |
|---|---|
| `materials-validate` · `zoop-eval-material-validation-1` | manifest의 파일·역할·SHA256·바이트 크기, 두 자료의 입력/gold 구조와 정확한 ID 대응을 모두 확인한다. KLUE 행/구간 수와 TAT-QA context/질문 수를 보고한다. |
| `materials-inputs` · `zoop-eval-material-inputs-1` | manifest와 **선택한 입력 파일만** 읽는다. gold의 존재·접근 가능 여부를 요구하지 않고 기존 기본 corpus의 gold도 열지 않는다. `validationScope=manifest-and-selected-input-only`이며 전체 gold 검증으로 표시하지 않는다. |
| `materials-gold` · `zoop-eval-material-gold-1` | 선택한 입력과 gold의 구조·ID·context closure를 확인한다. `inputsSha256`은 정확히 같은 `materials-inputs` JSON 바이트에 묶인다. |

세 schema의 닫힌 필드 정의는 `zoop_eval/contracts.py`에 있다. canonical JSON은 키 정렬·공백 없는 UTF-8이며 배열은 원자료 순서를 유지한다. `inputsSha256`은 stdout 마지막 LF를 제외한 전체 입력 artifact의 SHA256이다. 원본 파일 해시와는 다르며 출처 metadata도 binding에 포함한다. JSON 숫자는 `Decimal`로 읽어 이진 부동소수점 반올림 없이 내보내고, 음수·소수 정밀도·원래 단위를 유지한다.

- **KLUE:** guid·문장·source·entity 문자열/유형을 보존한다. 원문 substring을 확인한 뒤 inclusive 좌표를 `unit=unicode-codepoint`, `endExclusive=true`인 반열린 구간으로 바꾼다. `choices`는 코드에 고정한 공개 30개 label vocabulary이며 gold에서 읽어 만들지 않는다. gold는 원래 숫자 `labelId`와 같은 공개 label을 함께 낸다. S3의 다섯 predicate로 매핑하지 않는다.
- **TAT-QA:** table UID·셀 문자열·paragraph UID/order/text를 context에 두고 question UID/order/text가 `contextId`로 참조한다. 입력에는 answer/type/from/derivation/scale/support annotation 키를 허용하지 않는다. 본문·표에 원래 있는 답 단어나 숫자는 정상 입력이다. gold의 `rel_paragraphs` 문자열 순서를 해당 context의 안정된 paragraph UID로 연결해 `paragraphIds`에 담고 원래 annotation도 보존한다. table-cell 정답은 만들지 않는다. 문자열 annotation은 upstream 값 그대로 유지하며 null·빈 값·빈 answer 문자열을 추론해서 채우지 않는다.
- 파일은 정해진 네 basename으로 한정하고 symlink·비정규 파일·8 MiB 초과 파일·경로 이탈·역할 교환을 거부한다. 중복 JSON 키·비유한 상수·정수 자리에 온 bool·중복/고아 ID·잘못된 span/label·추가 annotation 키·해시/크기 불일치도 전체 거부한다. 성공은 0, 거부는 2이며 원문이나 비공개 경로를 오류 메시지에 넣지 않는다.
- 출력은 원저자·URL·라이선스·변경 내역·원본/로컬 해시와 `development-intake` 상태를 보존한다. manifest의 `collectionExecution`은 수집 당시 기록이므로 `adapterOrScorerImplemented=false`를 현재 adapter 상태로 해석하지 않는다. upstream annotation은 Zoop 사람 합의 gold가 아니다. 해시 일치는 출판자 진위·법적 이용 가능성·외부 모델 전송 승인을 증명하지 않는다.

smoke는 실제 저장 자료와 임시 디렉터리의 잘못된 fixture를 실제 CLI로 처리한다. 성공 시 관측한 20행·30문항과 검증 범위를 출력하며 정확도를 내지 않는다. command seam의 audit는 gold 접근·네트워크·자식 프로세스·파일 쓰기와 애플리케이션 환경 조회를 감시한다. Python 시작/import와 argparse의 locale·화면 크기 조회까지 환경 읽기 0으로 주장하지 않는다. 시험 fixture 변경은 임시 디렉터리에만 한정된다.

### TAT-QA 문단 검색과 별도 채점

`materials-retrieve`는 adapter가 정규화한 TAT-QA 입력만 사용한다. 후보는 **각 질문에 원래 주어진 context의 paragraph 전체**다. 다른 context의 문서나 표 셀을 검색하지 않으며 정답·도출식·support annotation은 열지 않는다. 표가 입력 digest에 포함되더라도 순위 계산에는 질문 문자열과 문단 텍스트만 쓴다. 후보가 없으면 빈 순위를 내고 답을 만들지 않는다.

```bash
python3 -B -m zoop_eval materials-retrieve --top-k 5
# 위 stdout을 호출자가 RUN.json으로 보관한 뒤 별도 실행한다.
python3 -B -m zoop_eval materials-retrieval-score RUN.json
python3 -B -m unittest discover -s tests -p 'test_material_retrieval.py'
python3 -B scripts/materials_retrieval_smoke.py
```

두 명령은 stdout canonical JSON만 내며 `--materials` 기본값은 기존 adapter와 같다. `--top-k`는 양의 정수이고 기본값은 5다. run 파일 보관은 호출자 책임이며 명령 자체는 파일을 쓰지 않는다. 잘못된 입력은 `Rejected` JSON과 종료 코드 2로 전체 거부한다.

run의 공통 크기 상한은 **8 MiB(8,388,608바이트)**다. producer는 canonical JSON의 UTF-8 바이트와 마지막 LF를 합쳐 이 상한 이하인지 성공 출력 전에 확인한다. scorer도 같은 상한으로 파일 전체 바이트를 제한하며 공백·LF를 포함한다. 초과하면 양쪽 모두 `materials_retrieval_run_size`로 거부한다. 이는 run 크기 계약이지 별도의 K 상한이 아니며, 질문·후보 수가 많아 결과가 커지면 작은 K로 새 실행을 요청해야 한다.

- **동결 알고리즘:** `stdlib-bm25-paired-paragraph-1`. `str.lower()` 뒤 ASCII `[a-z0-9]+`를 토큰으로 삼으며 stemming·stopword 제거는 없다. 중복 query token은 한 번만 쓰고 사전순으로 합산한다. context 안의 문단 수를 `N`, 해당 토큰이 있는 문단 수를 `df`로 하여 `IDF=ln(1+(N-df+0.5)/(df+0.5))`, `k1=1.2`, `b=0.75`인 BM25를 계산한다. 길이는 토큰 수, 평균 길이는 빈 문단을 포함한 전체 후보의 평균이다. 모든 문단이 비어 있으면 점수는 0이다. 점수 내림차순, 동점이면 paragraph UID의 Unicode code point 오름차순으로 최대 K개를 남긴다. 0점 후보도 남기므로 빈 query token은 UID 순으로 정렬된다.
- **run 계약:** `zoop-eval-material-retrieval-run-1`은 닫힌 필드와 `finalized=true`를 요구한다. exact normalized `inputsSha256`, 자료 ID·출처·정규화 정보·알고리즘·설정·전체 query ID·context별 candidate ID를 묶는다. 순위와 실측 `elapsedNs`는 별도 필드다. 시간은 `perf_counter_ns`로 질문마다 토큰화·로컬 색인·점수·정렬을 한 번 측정하며 입력 로딩·검증·digest·직렬화는 제외한다. warmup·색인 재사용·검색 cache는 없다. 시간은 순위의 결정성 비교에서 제외하며 모델 지연이 아니다.
- **scorer 계약:** `zoop-eval-material-retrieval-score-1`은 finalized run과 입력 binding·전체 ID·각 record를 확인한 뒤에만 gold를 연다. `ok` 순위는 동결 알고리즘으로 재계산해 확인한다(점수에는 `1e-12` 상대 오차만 허용). 중복·외부 ID, 다른 context의 후보, 추가 필드, 비유한 점수, 잘못된 상태·시간은 거부한다. 누락 record는 `missing`, 명시적 실패 record(`status=error`, 빈 ranking, `error=retrieval-error`)는 `error`로 세며 채점 가능한 질문의 분모에 남겨 0점을 준다. producer는 전체 질문 처리 후에만 run을 반환하고 예외를 가짜 성공이나 실패 record로 바꾸지 않는다. schema의 측정 표시는 서명이나 실행 진위의 증명이 아니며, 시험에서 편집한 run은 authored fixture다.
- **지표:** paragraph gold가 비어 있지 않은 비-table-only 질문마다 `Recall@K=회수한 support 수/전체 support 수`, `MRR@K=첫 support의 순위 역수`(미회수는 0), `exactSupportCoverageAtK=모든 support 회수 여부`를 계산한다. 마지막 지표는 추가 후보를 허용하는 전체 support 포함 여부이지 retrieved 집합과 gold 집합의 완전 일치는 아니다. 세 지표 모두 채점 가능한 질문의 macro 평균이며 numerator·denominator·value를 함께 낸다. table-only 또는 paragraph annotation 부재는 이유를 붙여 `notScorable`로 남기고 지표는 null이다. 원래 null support 수와 빈 배열의 0도 구분한다. 채점 가능한 질문이 0개면 분모 0·값 null이며, 전체 질문·기록·성공·실패·누락·채점 가능/불가 수와 모든 질문별 결과를 보존한다.

이 지표는 **공식 TAT-QA 답변 EM/F1가 아닌 custom paragraph-support 진단**이다. 답변·계산·그래프·경로·모델 품질 capability는 없다. CC BY 4.0 출처와 upstream annotation의 비합의 상태를 그대로 유지한다. smoke는 30개 저장 dev 질문의 실제 CLI retrieval→scoring을 실행하도록 구성되어 있다. gold 파일을 제거한 상태에서 검색하고, producer 종료와 run 보관 뒤 gold를 복원해 채점한다. 기존 command-seam audit를 재사용해 허용 파일 외 접근·네트워크·프로세스·파일 변경·애플리케이션 환경 조회를 차단하고 관측 counts·지표·시간을 출력한다. 이 문서는 실행 결과나 authored 기대값을 실측으로 제시하지 않는다.


## 명령

저장소 루트 기준이다.

```bash
cd ai/evaluation
python3 -B -m unittest discover -s tests          # 시험
python3 -B scripts/smoke.py                       # 일회성 smoke: 진입점, 전 명령, 거부 경로
python3 -B -m zoop_eval validate                  # corpus·gold 무결성과 dev/test 분리
python3 -B -m zoop_eval controls --out-dir fixtures/controls   # authored control 재생성
python3 -B -m zoop_eval score fixtures/controls/degraded-dev.run.json --format text
python3 -B -m zoop_eval score RUN.json [--format json|text] [--out score.json]
python3 -B -m zoop_eval compare RUN_A.json RUN_B.json [--format text]
```

종료 코드는 성공 0, 입력 거부 2이며 거부 시 stdout에 `{"ok": false, "error": {"code", "message"}}`를 낸다.

## 그래프 도구 baseline (`zoop-ai-graph`)

설치된 `zoop-ai-graph`의 `focus`·`read`·`inspect`를 호출마다 실제 subprocess로 실행해 wall time과 이웃 결과의 정확성을 기록하는 결정적 도구 baseline이다. `focus`는 고정된 plan 위의 **무방향** 메모리 BFS이고 Neo4j는 전체 version 검증에만 읽으므로, 지연은 호출 비용(파이썬 시작, SQLite ledger, authority 재검증, Bolt, 전체 검증, BFS)이다. RAG/agent 답변 품질, 방향 공급망 추론, Neo4j 순회 성능은 재지 않는다. 자세한 정의·한계·공개 계약 차이는 [`docs/design/ai-benchmark.md`](../../docs/design/ai-benchmark.md)의 “그래프 도구 baseline”에 있다.

```bash
# 승인된 임시 Neo4j 필요. 환경: ZOOP_GRAPH_SMOKE_URI=bolt://127.0.0.1:<port> ZOOP_GRAPH_AUTH=none|basic (+ZOOP_GRAPH_USER/PASSWORD)
PY=ai/pipeline/.venv/bin/python                       # prepare/cleanup만 파이프라인 인터프리터가 필요하다
$PY ai/evaluation/scripts/graph_tool_bench.py prepare --root /tmp/zoop-gtb-root --manifest /tmp/zoop-gtb.manifest.json
python3 -B ai/evaluation/scripts/graph_tool_bench.py measure --manifest /tmp/zoop-gtb.manifest.json --out /tmp/zoop-gtb.run.json --authority-checks
python3 -B ai/evaluation/scripts/graph_tool_bench.py score /tmp/zoop-gtb.run.json --out /tmp/zoop-gtb.score.json --markdown /tmp/zoop-gtb.report.md
$PY ai/evaluation/scripts/graph_tool_bench.py cleanup --manifest /tmp/zoop-gtb.manifest.json
```

- `prepare`는 비어 있는 Neo4j database에만 쓰고 직접 만든 소유 state(`--root`, 소유 marker 포함)만 만든다. `cleanup`은 manifest에 적힌 **정확한 version ID와 store marker만** 지우고, 환경의 Neo4j 대상이 manifest의 포트·database나 저장된 binding과 다르면 아무것도 지우지 않은 채 소유 state를 남긴다. database를 통째로 지우거나 접두사로 지우지 않는다. `--authority-checks`의 registry 변조도 같은 run의 소유 marker가 있는 `--root` 안의 일반 파일에만 허용한다.
- `measure`는 기대값 파일을 열지 않는다. `--repeats`(기본 20, 1..1000)·`--warmups`(기본 1)·`--timeout`·`--invoker audit|script`를 지원하고 `--out`을 덮어쓰지 않는다. `--authority-checks`는 소유 state에서만 grant·canonical 거부와 입력 거부를 점검한다(통계 제외).
- `score`는 `zoop-graph-tool-run-1` 측정 기록만 받는다. authored control·`zoop-bench-run-1`·모델/provider 호출이 관측된 기록은 `incompatible_run`/`unexpected_model_call`로 거부한다.
- 입력 fixture: `fixtures/graph-tool/queries.json`(보이는 dev case)과 `expected.json`(손으로 쓴 정답, `score`와 시험만 연다). 동적 시간이 든 run·score·report 파일은 커밋하지 않는다.
- 상태(2026-10-15, Main 관측): 시험 158개와 CLI 점검 통과, 실제 Neo4j 두 endpoint의 적대적 cleanup 점검(`scripts/graph_tool_cleanup_adversarial.py`) 통과. 첫 측정은 합성 world(main node 6·edge 6, split node 4·edge 2), 측정 340시도(17 case × 20)에서 실패 0·완전 정답 340이었고 depth 1/2/3 성공 p50은 각각 277.171·280.293·278.461 ms(n 100/60/80)이다. 이는 CLI 호출 전체 비용과 무방향 focus 이웃의 정확성이며 Neo4j 순회 속도·AI/RAG 품질·모델 성능이 아니다. depth 간 차이가 작은 원인은 구성요소 계측이 없어 입증하지 않았다. 한계와 해석은 설계 문서의 “그래프 도구 baseline” 절을 본다.

## 한국어 금융 semantic-verification 벤치마크

네이티브 Jev 검증 stage의 판정을 직접 쓴 한국어 합성 case 28개(claim 55개)와 따로 쓴 gold로 채점한다. 정의·지표·출처 규칙·WBS 대응은 [`docs/design/ai-benchmark.md`](../../docs/design/ai-benchmark.md)의 “한국어 금융 semantic-verification 벤치마크”에 있다. 이 절의 숫자·run은 **하네스 정합성**을 증명하는 것이고 실제 모델·Jev의 한국어 품질 측정이 아니다. loopback 서버의 답은 저작된 script(control)다.

설치된 worker 개발 환경에서는 저장소 루트에서 `make evaluation-verification-check` 한 명령으로 이 벤치마크를 점검한다. 이 명령은 의존성을 설치하지 않는다. Python 3.12 이상으로 준비한 `make worker-install` 환경이 필요하며, worker 소스가 바뀌었다면 먼저 설치본을 갱신한다. 기본 인터프리터는 `ai/worker/.venv/bin/python`이고 `WORKER_PYTHON=`으로 바꿀 수 있지만, smoke가 실행하는 CLI는 `ai/worker/.venv/bin/zoop-ai` 설치본이다.

```bash
# 저장소 루트, worker 개발 환경을 설치한 뒤
make evaluation-verification-check
```

루트 점검은 실제 설치 CLI를 실행하는 `verification_bench.py smoke`를 먼저 수행한 뒤 `verify-validate`와 `test_verification.py`만 실행한다. smoke는 producer가 gold를 열지 않았는지 확인하고 producer가 끝난 뒤에만 gold를 읽어 채점한다. 전체 evaluation unittest 모음을 중복 실행하지 않으며 worker 다리의 pytest는 기존 `make worker-test`가 담당한다. 자식 프로세스에 provider·proxy 환경을 전달하지 않고 loopback script만 사용하므로 실제 환경 파일, 외부 provider, 키, Neo4j가 필요하지 않다. run·ledger는 임시 디렉터리에만 생성된다.

기존 CI의 공개 의존성 전용 `ai-worker` job이 `make worker-install` 뒤에 같은 루트 점검을 실행한다. 이 workflow에는 경로 필터가 없으므로 corpus·gold·evaluation 코드·worker 다리·루트 도구·workflow 변경도 점검 대상이다. 새 job, 서비스, 의존성, credential은 추가하지 않는다. 아래는 개별 명령이다.

```bash
cd ai/evaluation
python3 -B -m zoop_eval verify-validate
python3 -B -m zoop_eval verify-controls --out-dir fixtures/verification/controls
python3 -B -m zoop_eval verify-score fixtures/verification/controls/degraded-dev.run.json --format text
python3 -B -m zoop_eval verify-score RUN.json [--format json|text] [--out score.json]
python3 -B -m unittest discover -s tests -p 'test_verification.py'
```

다음 worker 명령은 저장소 루트에서 실행한다. CLI가 설치본을 실행하므로 worker 수정 뒤에는 먼저 설치본을 갱신한다.

```bash
ai/worker/.venv/bin/python ai/worker/scripts/verification_bench.py smoke
ai/worker/.venv/bin/python ai/worker/scripts/verification_bench.py run --out /tmp/zoop-vk.run.json
```

- `corpus/fin-verify-ko-v1/cases.json`(producer가 보는 입력)과 `gold.json`(숨김)은 분리되어 있고 worker 다리(`ai/worker/scripts/verification_bench.py`)는 gold를 열지 않는다. `verify-validate`·`verify-controls`·`verify-score`만 gold를 연다.
- gold는 단일 작성자·미합의·합성·dev 전용이다. 비용 불명은 `null`이고 0으로 쓰지 않는다. 보정(calibration)은 기록된 live provider 분포에만 계산하며 authored·loopback에서는 `not_evaluated`다.
- 실제 Jev·모델 호출, 키, 비용 지출은 승인 전에는 하지 않는다. `real_measured` run은 만들지 않았다.

## 구성

| 경로 | 내용 |
|---|---|
| `corpus/zoop-bench-v1/` | 허구의 합성 corpus. `corpus.json`·`tasks.json`은 시스템에 보이는 입력, `gold.json`은 시스템에 숨기는 정답 |
| `zoop_eval/` | 검증, 채점, 비교, 보고 모듈과 CLI |
| `fixtures/controls/` | authored control 3개(`oracle-dev`, `oracle-test`, `degraded-dev`) |
| `fixtures/graph-tool/` | 그래프 도구 baseline의 보이는 dev case(`queries.json`)와 손으로 쓴 정답(`expected.json`) |
| `corpus/fin-verify-ko-v1/`, `zoop_eval/verification.py`, `fixtures/verification/controls/` | semantic-verification 벤치마크의 입력·gold, 검증·채점·control 코드, authored control과 loopback script |
| `zoop_eval/graph_tool.py`, `scripts/graph_tool_bench.py` | 도구 측정 기록·채점 핵심(표준 라이브러리)과 `prepare`/`measure`/`score`/`cleanup` 명령 |
| `tests/`, `scripts/smoke.py` | 시험과 smoke |

run 파일(`zoop-bench-run-1`) 형식은 위 설계 문서의 “입력 계약”을 따른다. 미래의 모델·도구 adapter는 이 파일만 만들면 된다.

## 한계

- 이 하네스에 전체 검색·답변 시스템을 연결한 측정 결과는 없다. `zoop-ai-graph` baseline은 합성 world에서 도구 호출 비용과 이웃 결과 정확성만 확인하며, 검증 다리의 loopback 결과도 하위 단계의 기록·채점 점검이다. 다른 팀의 실행 코드 유무를 이 상태로 단정하지 않는다. authored control은 실제 모델 결과와 섞어 순위를 매기지 않는다.
- 기존 합성 gold는 단일 작성자 초안이며 합의를 거치지 않았고(`adjudicated=false`) 규모가 작아 비율이 거칠다. 기존 그래프·QA corpus는 영어 합성 문장이므로 한국어 표현을 검증하지 않는다. 한국어 검증 corpus도 합성 dev 전용이며 실제 모델 품질 근거가 아니다. 별도 외부 intake의 원래 annotation은 Zoop 한국어 금융 gold를 대체하지 않는다.
- 자유 서술 품질과 인용의 의미적 뒷받침은 자동 지표가 없고 사람 또는 모델 평가가 필요하다.
- 실제 모델 호출, 외부·경쟁 서비스 질의, 그래프 DB 설치, 새 의존성, test split 사용은 사용자 승인 전에는 하지 않는다. WBS는 변경하지 않는다.
- 루트·CI 연결은 한국어 semantic-verification 점검에 한정된다. 기존 그래프·QA 하네스의 전체 시험과 Neo4j 도구 baseline은 위의 개별 명령으로 실행한다.

## 네이티브 이슈 요약 검증 벤치마크

`summary-verify-*` 명령은 production `verify-issue-summary` 판정을 별도 합성 corpus `fin-summary-verify-ko-v1`의 24개 사례·30개 주장과 비교한다. 기존 S1 `verify-*` 계약과 control은 바꾸지 않는다. 이 corpus는 **AI 보조 단일 작성자의 개발용 gold**이며 독립적인 사람의 합의·검수를 거치지 않았다. 실제 모델 품질, 생성 품질, RAG·그래프·전체 S2/S3 품질이나 임곗값 보정을 평가하지 않는다.

```bash
# ai/evaluation에서 실행: 표준 라이브러리만 필요
python3 -B -m zoop_eval summary-verify-validate
python3 -B -m zoop_eval summary-verify-controls --out-dir fixtures/summary-verification
python3 -B -m zoop_eval summary-verify-score fixtures/summary-verification/oracle.run.json --format text
python3 -B -m zoop_eval summary-verify-score RUN.json --out score.json
python3 -B -m unittest discover -s tests -p 'test_summary_verification.py'
```

`controls`는 gold에서 `oracle.script.json`과 `deviations.script.json`을 만들 뿐 native receipt를 합성하지 않는다. 독립 평가 시험의 `oracle.run.json`·`deviations.run.json`은 아래 실제 loopback HTTP 경로로 캡처한 fixture다. fixture가 없으면 시험을 건너뛰지 않고 실패한다. 파이프라인 개발 환경을 설치한 뒤 저장소 루트에서 다음과 같이 새 run을 만든다.

```bash
ai/pipeline/.venv/bin/python ai/pipeline/scripts/summary_verify_bench.py loopback \
  --script ai/evaluation/fixtures/summary-verification/oracle.script.json \
  --out /tmp/summary-oracle.run.json
ai/pipeline/.venv/bin/python ai/pipeline/scripts/summary_verify_bench.py loopback \
  --script ai/evaluation/fixtures/summary-verification/deviations.script.json \
  --out /tmp/summary-deviations.run.json
```

- Producer는 보이는 `cases.json`과 loopback script만 읽고, native runtime의 prepare/send/receipt/answer를 거친다. 채점기는 pipeline을 import하지 않고 표준 라이브러리로 요청·공개 question preimage·binding·원문 응답·usage·비용·판정을 다시 계산한다. 미인용 quote는 입력에 있어도 되지만 전송 요청의 `state.quotes`에서는 빠져야 한다.
- 오류가 있는 사례도 gold 쪽 분모에서 빼지 않는다. 주장별 confusion·precision/recall/F1, advice/causality/framing 검사, available/hold/reject gate, 태그별 정확도와 오류 수를 보고한다. 형식이나 해시·판정이 맞지 않는 run은 `Rejected`와 종료 코드 2로 거부하며 부분 점수를 내지 않는다. 순위·우승 모델·합격 임곗값은 산출하지 않는다.
- `authorizedMayHaveSentMs`는 전송 직전 승인 callback이 실행된 오류의 send 구간이다. **provider가 요청을 받았다는 증거가 아니다.** HTTP 응답이 저장된 사례는 따로 센다. send 시간에는 예산 예약·승인·네트워크·정산이 포함되고, loopback 시간은 모델 지연이 아니다.
- 보수적 runtime 추정액, 예산에 반영된 금액, 결과 미상의 예약 위험액을 구분한다. 소유한 가짜 loopback endpoint만 실제 청구액을 `loopback_no_charge=0`으로 표기한다. 실제 provider 청구액은 `unknown/null`이며 usage가 없다고 비용을 0으로 취급하지 않는다.
- 모든 receipt에서 `bodyText`의 UTF-8 바이트와 `bodySha256`을 비교한다. 정상 UTF-8의 U+FFFD 문자도 예외가 아니다. 원래 잘못된 UTF-8 바이트가 native capture에서 대체 문자로 바뀌어 복원되지 않는 경우에는 `receipt_body_mismatch`로 채점을 거부한다. production receipt 형식을 바꿔 이 한계를 숨기지 않는다.
- 해시는 내부 정합성을 확인할 뿐 실제 실행을 인증하지 않는다. 전송 중단 기록은 `bench_outcome_unrecorded/unknown`, 뒤의 미시도 사례는 `bench_not_attempted/definite`로 남긴다. assemble은 저장 기록만 다시 읽으며 자동 재전송하지 않는다.
- 실제 provider 호출은 이 문서의 명령에 포함되지 않는다. 향후 live 실험은 매번 별도 사용자 승인을 받아야 하며 명시적인 live 모드·고정 corpus digest·기존 live gate·고정 모델·새 예산·정확한 provider endpoint가 모두 필요하다. `--check` 통과나 환경 설정만으로 호출이 승인되지는 않는다. `.env`는 읽지 않는다.

원시 run에는 합성 입력·요청·응답이 들어 있지만 score의 사례별 결과에는 원문을 싣지 않는다. 지표 정의와 해석 범위는 [AI 벤치마크 설계](../../docs/design/ai-benchmark.md)를 참고한다.
