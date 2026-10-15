# ai/evaluation: 기록된 출력의 결정적 채점 하네스

이미 기록된 그래프 구성·검색·답변 출력과 trace를, 따로 작성한 gold와 비교해 채점한다. 표준 라이브러리만 쓰며(Python 3.12 이상) 채점기는 모델·네트워크·그래프 DB를 호출하지 않는다(예외: 아래 그래프 도구 baseline의 `measure`가 설치된 `zoop-ai-graph` CLI를 subprocess로 호출하고, 그 CLI가 승인된 loopback Neo4j를 읽는다. 모델·provider 호출은 0이다). 지표 정의, 데이터 분리, gold 검수, baseline과 측정 계획, 승인 경계는 [`docs/design/ai-benchmark.md`](../../docs/design/ai-benchmark.md)에 있고 여기서 반복하지 않는다.

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

## 구성

| 경로 | 내용 |
|---|---|
| `corpus/zoop-bench-v1/` | 허구의 합성 corpus. `corpus.json`·`tasks.json`은 시스템에 보이는 입력, `gold.json`은 시스템에 숨기는 정답 |
| `zoop_eval/` | 검증, 채점, 비교, 보고 모듈과 CLI |
| `fixtures/controls/` | authored control 3개(`oracle-dev`, `oracle-test`, `degraded-dev`) |
| `fixtures/graph-tool/` | 그래프 도구 baseline의 보이는 dev case(`queries.json`)와 손으로 쓴 정답(`expected.json`) |
| `zoop_eval/graph_tool.py`, `scripts/graph_tool_bench.py` | 도구 측정 기록·채점 핵심(표준 라이브러리)과 `prepare`/`measure`/`score`/`cleanup` 명령 |
| `tests/`, `scripts/smoke.py` | 시험과 smoke |

run 파일(`zoop-bench-run-1`) 형식은 위 설계 문서의 “입력 계약”을 따른다. 미래의 모델·도구 adapter는 이 파일만 만들면 된다.

## 한계

- 측정한 검색·답변 시스템이 없다. 저장소에 검색기·채팅 실행 코드가 없고, `zoop-ai-graph`의 도구 baseline(위 절)은 합성 world에서 이 도구의 호출 비용과 이웃 결과 정확성만 잰다. 그 외 점수는 모두 채점기 점검용 authored control이다. control은 `real_measured` 결과와 같은 표에 올리거나 순위를 매기지 않는다(`compare`가 거부한다).
- gold는 단일 작성자 초안이며 합의를 거치지 않았고(`adjudicated=false`) 규모가 작아 비율이 거칠다. 영어 합성 문장이라 한국어 표현은 검증하지 않는다.
- 자유 서술 품질과 인용의 의미적 뒷받침은 자동 지표가 없고 사람 또는 모델 평가가 필요하다.
- 실제 모델 호출, 외부·경쟁 서비스 질의, 그래프 DB 설치, 새 의존성, test split 사용은 사용자 승인 전에는 하지 않는다. WBS는 변경하지 않는다.
- 루트 `Makefile`과 CI에는 아직 연결하지 않았다.
