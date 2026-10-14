# AI 그래프·검색·답변 벤치마크: 평가 하네스와 측정 계획

**이 문서가 다루는 것.** 이미 기록된 출력과 trace를 사람이 따로 작성한 gold와 결정적으로 비교하는 평가 하네스(`ai/evaluation`), 그 지표 정의, 데이터 분리·gold 검수 방법, 공정한 baseline·경쟁 서비스 구분, 처음 측정할 계획, 승인 경계를 정한다.

**현재 상태 (사실).**

- 하네스·합성 corpus·authored control·시험·smoke까지 구현했다. 모델·네트워크·그래프 DB 호출은 0이다.
- 저장소에는 벡터 RAG, 그래프 순회 검색, 일반 채팅, Neo4j 실행 코드가 **없다**. 따라서 실제 시스템에 대한 측정값은 **0건**이다. 지금 만들어지는 모든 점수는 하네스가 올바르게 채점하는지 확인하는 authored control의 값이며 벤치마크 결과가 아니다.
- gold는 합성 코퍼스에 대한 **단일 작성자 초안**이며 두 사람의 독립 라벨링·합의(adjudication)를 거치지 않았다(`adjudicated=false`, `annotators=1`). 여기서 나온 점수는 실제 데이터에 대한 정확도 주장이 아니다.
- 자유 서술 답변의 의미 품질은 정확 일치로 판정할 수 없다. 사람 또는 모델 평가가 필요하며 이 하네스는 그 지표를 만들지 않는다(`freeText.status = human_or_model_evaluation_required`).

## 실행 명령

Python 3.12 이상, 표준 라이브러리만 사용한다. 새 uv 패키지·의존성·lock이 없다. 아래 명령은 모두 저장소 루트에서 실행한다. 거부 규칙 수정 뒤 Main이 시험 88개 통과, 실제 CLI smoke(`measuredResults=0`, 모델·네트워크 호출 0)와 `validate` 통과를 확인했다.

```bash
cd ai/evaluation
python3 -B -m unittest discover -s tests                 # 시험 88개, 모델·네트워크 없음
python3 -B scripts/smoke.py                              # 실제 진입점 + 모든 명령 + 거부 경로. 네트워크 차단 audit hook
python3 -B -m zoop_eval validate                         # corpus·gold 무결성, dev/test 분리 검사
python3 -B -m zoop_eval controls --out-dir fixtures/controls   # authored control 재생성(체크인된 fixture와 smoke가 일치 검사)
python3 -B -m zoop_eval score  fixtures/controls/degraded-dev.run.json --format text
python3 -B -m zoop_eval score  RUN.json [--format json|text] [--out score.json]
python3 -B -m zoop_eval compare RUN_A.json RUN_B.json [--format text]
```

종료 코드는 성공 0, 입력 거부 2이며 거부 시 stdout에 `{"ok": false, "error": {"code", "message"}}`를 출력한다. `-B`는 `__pycache__`를 만들지 않기 위한 것이다. 루트 `Makefile`·`ci.yml` 연결은 이 작업에 포함하지 않았다(필요하면 `eval-test`=`unittest` 한 줄, `eval-smoke`=`scripts/smoke.py` 한 줄이 전부이고 토큰이 필요 없다).

## 구성

| 경로 | 역할 |
|---|---|
| `ai/evaluation/corpus/zoop-bench-v1/corpus.json` | **시스템이 볼 수 있는** 합성 기업 17곳·기사 27건·passage 31개 |
| `.../tasks.json` | **시스템이 볼 수 있는** 입력: predicate 레지스트리, 그래프 구성 task 10개(멘션·병합 후보), 질문 18개(`anchorEntity`, `asOf`) |
| `.../gold.json` | **시스템에 숨기는** 정답. entity 링크, 이벤트 속성, 병합 결정, 그래프 edge(방향·유효기간·status·근거), 질문별 outcome·답·경로·근거 passage |
| `zoop_eval/` | `contracts`(엄격 검증)·`bench`(corpus 적재·무결성)·`run`(기록 형식)·`graph`·`qa`·`timing`·`scoring`·`compare`·`report`·`controls`·`cli` |
| `fixtures/controls/*.run.json` | authored control 3개(`oracle-dev`, `oracle-test`, `degraded-dev`) |
| `tests/`, `scripts/smoke.py` | 시험과 일회성 smoke |

corpus의 기업·기사는 모두 허구다. 실제 발행사·기사·시장 데이터가 없다.

### 포함한 사례 종류

| 종류 | dev | test |
|---|---|---|
| 1-hop 직접 / 방향 질문 | QA-1, QA-2 | QB-1, QB-2 |
| 2-hop, 3-hop 경로 | QA-3, QA-4 | QB-3, QB-4 |
| 시점(temporal) 질문: 같은 투자 관계가 기간별로 다른 주체 | QA-5, QA-6 | QB-5, QB-6 |
| unknown: 종료일 미상 abstain, 증거 없음 abstain | QA-7, QA-9 | QB-7, QB-9 |
| conflict: 두 매체가 상충하는 공급 관계 | QA-8 | QB-8 |
| 동음이의 기업명, 맥락 없는 모호 멘션(gold `null`) | GT-A4 | GT-B4 |
| 같은 기업·같은 날 다른 사건, 같은 사건의 재보도, 날짜·장소가 없는 사건(`UNDECIDABLE`) | GT-A5 | GT-B5 |
| 역방향 서술 문장(“A는 B에서 구매”), 무관한 물류 관계(edge 아님), 무방향 경쟁 관계 | GT-A1, GT-A3 | GT-B1 |

질문 수와 task 수는 매우 작다(split당 질문 9, 그래프 task 5). 정확도 비교용이 아니라 **채점 규칙이 사례별로 의도대로 동작하는지 확인하는 크기**다.

## 입력 계약: 기록(run) 형식

미래의 모델·도구 adapter는 아래 한 파일(`zoop-bench-run-1`)만 만들면 된다. 모든 객체는 알 수 없는 키를 거부한다. JSON의 중복 키·`NaN`/`Infinity`도 거부한다.

```jsonc
{
  "schema": "zoop-bench-run-1", "runId": "r-agent-low-001", "label": "optional",
  "provenance": {
    "kind": "real_measured",            // 또는 "authored_control"
    "executionMode": "live",            // real_measured: live|replay, authored_control: authored
    "recorder": "adapter name/version", "recordedAt": "2026-10-20T01:02:03+09:00"  // authored_control은 null + controlKind 필수
  },
  "corpus": { "corpusId": "zoop-bench-v1", "corpusRevision": "2026-10-14.1", "goldRevision": "2026-10-14.1",
              "inputsSha256": "(선택, validate가 출력하는 값)", "split": "dev", "tasks": ["graph", "qa"] },
  "system": {
    "systemId": "agent-graphrag-low", "family": "agent_graphrag",   // no_model_deterministic|vector_rag|fixed_graph_traversal|agent_graphrag|other
    "model": { "provider": "…", "name": "…", "version": "…" },       // 모델이 없으면 null
    "config": { "reasoningEffort": "low", "maxToolCalls": 8, "maxHops": 3, "topK": null, "timeoutMs": 120000 },  // 스칼라만
    "promptRevision": "…", "toolRevision": "…", "schemaRevision": "…", "graphRevision": null,
    "capabilities": { "retrieval": true, "path": true, "citations": true }          // qa 채점 시 필수
  },
  "timingContext": { "concurrency": 1, "warmup": "warm", "environment": "…" },       // 선택. 지연 비교에 필요
  "records": [
    { "task": "qa", "caseId": "QA-4", "status": "ok",
      "output": { "outcome": "answered", "answerEntities": ["E-CRV"], "facts": [], "retrieved": ["D01-P1"],
                  "citations": ["D01-P1"], "path": [ {"subject":"E-ESK","predicate":"SUPPLIES","object":"E-ARC"} ], "answerText": null },
      "trace": { "startMs": 0, "endMs": 4210, "spans": [
        { "spanId": "s1", "kind": "llm",  "name": "plan", "startMs": 5, "endMs": 900, "tokens": {"input": 812, "output": 96}, "costUsd": 0.0011 },
        { "spanId": "s2", "kind": "tool", "name": "graph_lookup", "startMs": 900, "endMs": 1500, "parentSpanId": null, "costUsd": 0 } ] } },
    { "task": "qa", "caseId": "QA-5", "status": "refused", "detail": "policy refusal", "trace": { "startMs": 0, "endMs": 300 } }
  ]
}
```

- 그래프 task의 `output`은 선택 섹션 `entityLinks`, `events`, `mergeDecisions`, `edges`를 가진다. 섹션이 **없는 것**(답하지 않음)과 **빈 배열**(빈 답)은 다르게 센다. edge는 `subject,predicate,object` 필수, `validFrom/validTo/status/citations` 선택이며 날짜 `null`은 “문서에 없음/미상”이다.
- `status`는 `ok`(output 필수) · `refused` · `error`(둘 다 `detail` 필수, output 금지)다. 기록이 없는 case는 `missing`으로 따로 센다.
- 기록 시점에 `real_measured` 실행은 `toolRevision`을, 모델이 있으면 `promptRevision`을 반드시 남긴다. `no_model_deterministic`은 모델을 가질 수 없고 `agent_graphrag`는 반드시 가진다.
- `corpusId/corpusRevision/goldRevision`(`inputsSha256`이 있으면 그것도)이 적재한 corpus와 다르면 채점하지 않는다(`corpus_mismatch`). run은 split 하나와 task 종류를 선언하고, 그 split에 없는 case의 기록은 `unmatched_case`로 run 전체를 거부한다(test 기록이 dev run에 섞이는 누출 방지).
- 같은 `(task, caseId)` 기록이 둘이면 `duplicate_record`, output 안에서 같은 `mentionId/pairId/eventMentionId`나 같은 `spanId`가 중복되면 거부한다.
- 선언하지 않은 능력(`capabilities.path=false`)을 출력하면 `capability_contradiction`으로 거부한다.

### Adapter가 채워야 하는 것과 채우면 안 되는 것

- 자유 서술 `answerText`는 선택이며 점수에 들어가지 않는다. 구조화 필드(`answerEntities`, `facts`, `citations`, `path`)가 채점 대상이다.
- 토큰·비용을 모르면 키를 생략한다(`null`). **0으로 채우지 않는다.** span을 기록하지 않았으면 `spans` 자체를 생략한다. 빈 배열은 “호출이 정말 없었다”는 주장이다.
- gold, 이전 run의 정답 표시, `tasks.json` 밖의 정보를 입력으로 쓰지 않는다.

## 지표 정의

모든 비율은 `{num, den, value}`로 출력한다. **분모가 0이면 `value`는 `null`**이다(0도 1도 아니다). 출력 키 이름을 그대로 적는다.

### 분모 규칙

- **gold 쪽 분모(recall, 정확도, 오류율)** 는 선택한 split의 **모든** case를 포함한다. `missing`·`refused`·`error`는 분자에 0을 기여하고 분모에서 빠지지 않는다.
- **예측 쪽 분모(precision)** 는 `ok` 기록이 실제로 낸 항목만 센다. 아무것도 내지 않으면 `null`이다. 병합 결정(`mergeDecisions`)은 그 task의 후보 `pairId`로 닫혀 있어, 요청하지 않은 pair(다른 task의 id 포함)가 있으면 점수를 내지 않고 run을 `unmatched_item`으로 거부한다. 같은 canonical triple의 edge가 한 task 출력에 두 번 있으면 `duplicate_item`으로 거부한다(무방향 predicate는 끝점 순서를 바꿔도 같은 triple이다). 끝점이 같아도 predicate가 다르거나 방향 predicate의 방향이 다르면 별개의 edge이므로 허용되고 `notInGold`/`reversedDirection`으로 채점한다. 요청하지 않은 entity 링크 멘션(`entityLinking.unmatchedRefs`)은 거부하지 않고 precision 분모에 넣어 불이익을 준다.
- 오류율(예: `falseMerge`)은 gold 항목 전체가 분모이므로 기록이 빠진 case도 분모에 있다. 낮은 오류율을 읽을 때는 반드시 `coverage`(`ok/refused/error/missing`)와 `notAnswered`를 함께 본다.
- `refused`/`error`/`missing`은 별개 계수이며 서로 합치거나 “빈 답”으로 바꾸지 않는다.

### 그래프 구성 (`graph`, 분모 단위는 아래 설명)

| 지표 | 분자 | 분모 |
|---|---|---|
| `entityLinking.accuracy` | 예측 링크가 gold와 일치한 멘션(gold `null`↔예측 `null`도 일치) | gold 멘션 전체 |
| `entityLinking.linkPrecision` / `linkRecall` | 정확히 연결한 비-null 링크 | 예측한 비-null 링크 / gold 비-null 멘션 |
| `entityLinking.falseLinkOnUnknown` | gold가 `null`인 멘션을 비-null로 연결 | gold `null` 멘션 |
| `entityLinking.misLinkedToOtherEntity` | gold와 **다른** entity로 연결(동음이의 혼동) | gold 비-null 멘션 |
| `events.typeAccuracy` / `dateAccuracy` | 일치한 이벤트 멘션(날짜 `null` 일치 포함) | gold 이벤트 멘션 |
| `events.dateInvented` | gold 날짜가 `null`인데 날짜를 제시 | gold 날짜가 `null`인 이벤트 |
| `merges.{event,entity}.accuracy` | 결정이 gold와 같거나 gold `UNDECIDABLE`에 `HOLD` | gold 병합 쌍 |
| `…falseMerge` | gold `DIFFERENT`인데 `SAME` | gold `DIFFERENT` 쌍 |
| `…unsafeMergeOnUndecidable` | gold `UNDECIDABLE`인데 `SAME`(별도 계수, false merge에 합치지 않음) | gold `UNDECIDABLE` 쌍 |
| `…missedMerge` | gold `SAME`인데 `SAME`이 아님 | gold `SAME` 쌍 |
| `…holdOnUndecidable` / `overHold` | `UNDECIDABLE`에 `HOLD` / 결정 가능한 쌍에 `HOLD` | gold `UNDECIDABLE` / 결정 가능한 gold 쌍 |
| `…sameBinding.precision` / `recall` | 정확한 `SAME` | 예측 `SAME` / gold `SAME` |
| `edges.triplePrecision` / `tripleRecall` | (subject, predicate, object)가 gold edge와 같은 예측 | 예측 edge / gold edge. **방향이 있는 predicate는 방향이 틀리면 불일치**, 무방향 predicate는 끝점 순서 무관 |
| `edges.exactPrecision` / `exactRecall` / `exactF1` | triple에 더해 `validFrom`·`validTo`·`status`가 모두 일치 | 예측 edge / gold edge. F1은 둘 중 하나가 `null`이면 `null` |
| `edges.reversedDirection` | 방향 predicate의 역방향 edge를 예측(별도 오류) | 예측 edge |
| `edges.notInGold` | gold에도 역방향 gold에도 없는 예측(공동 언급, 지어낸 관계) | 예측 edge |
| `edges.temporalInvented` | 일치한 triple에서 gold 경계가 `null`인데 날짜를 제시 | 일치한 triple의 gold `null` 경계 |
| `edges.temporalBoundAccuracy` (+ `temporalWrong`, `temporalDropped`) | gold 경계가 있는 곳에서 같은 값 | 일치한 triple의 gold 비-null 경계 |
| `edges.statusAccuracy` | `asserted/disputed`가 일치 | 일치한 triple |
| `edges.citationSupportedOfMatched` | 인용이 있고, 모두 corpus에 있고, 하나 이상 gold 근거 passage | 일치한 triple |

병합 쌍과 entity 링크는 gold가 모호하면 `UNDECIDABLE`/`null`로 남기며, 정답이 모호한 곳을 정확 일치로 채점하지 않는다. 날짜·기간은 `YYYY-MM-DD`이고 `null`은 “미상”을 뜻한다. 추정해서 채우면 `temporalInvented`/`dateInvented`로 센다.

### 검색·답변 근거 (`qa`: `all`, `byHop`, `byKind` 조각)

| 지표 | 분자 | 분모 |
|---|---|---|
| `outcome.correct` | 예측 outcome(`answered/abstained/conflict`)이 gold와 같음 | 질문 전체 |
| `outcome.endToEndCorrect` | outcome이 같고, `answered`면 `answerEntities` 집합과 `facts` 집합이 정확히 같음 | 질문 전체 |
| `answer.entitySetExact` | answered 질문에서 entity 집합이 정확히 같음 | gold answered 질문 |
| `answer.entityPrecision` / `entityRecall` | 일치한 entity | 예측 entity / gold entity |
| `answer.factSetExact`, `factPrecision`, `factRecall` | (triple+validFrom+validTo+status) 정확 일치. `factsReversedDirection`은 역방향 사실 수 | gold fact가 있는 질문 / 예측 fact / gold fact |
| `abstention.precision` / `recall` | 정당한 abstain | 예측 abstain / gold abstain |
| `abstention.reasonMatchOfCorrect` | 사유(`end_unknown`, `no_evidence`)까지 일치 | 정당한 abstain |
| `abstention.overAbstention` | 답이 있는/상충인 질문에서 abstain | gold `answered`+`conflict` 질문 |
| `abstention.unsupportedAnswer` | gold abstain인데 abstain하지 않음 | gold abstain 질문 |
| `abstention.conflictPrecision` / `conflictRecall` | 정당한 `conflict` | 예측 conflict / gold conflict |
| `retrieval.supportPrecision` | 가져온 passage 중 gold 근거 | 가져온 passage 전체(corpus에 없는 id 포함) |
| `retrieval.supportRecall`, `supportRecallAt5` | 가져온 gold 근거(앞 5개) | gold 근거 passage 전체 |
| `retrieval.fullSupportCases` | gold 근거를 모두 가져온 질문 | gold 근거가 있는 질문 |
| `path.produced` / `path.validity` | 경로를 낸 기록 / 경로가 유효 | 질문 전체 / 경로를 낸 기록 |
| `path.exactMatch` / `reachesAnswer` | gold 경로와 같은 edge 순서 / 유효하고 답 entity에서 끝남 | gold 경로가 있는 질문 |
| `path.hopCoverage` | gold 경로 edge 중 예측 경로가 짚은 수(가장 잘 맞는 gold 경로 기준) | gold 경로 길이의 합 |
| `citations.precision` / `recall` | gold 근거 집합에 속한 인용 | 인용 전체 / gold 근거 전체 |
| `citations.uncitedAnswers` | 인용이 비어 있는 answered/conflict 답 | 인용을 낸 answered/conflict 기록 |

- **경로 유효성**은 앵커 entity에서 출발해 각 단계가 gold 그래프의 실제 edge이고(방향 predicate는 방향 일치) 서로 이어져 있음을 뜻한다. 앵커에서 edge를 **거슬러** 걷는 것(상류 질문 “누가 공급하나”)은 허용하지만, 방향 edge를 **뒤집어 선언**하면 `reversed_edge`로 무효다. 실패 사유는 `invalidReasons`에 `empty/edge_not_in_graph/reversed_edge/disconnected`로 나뉜다. 시점 질문에서 다른 기간의 edge를 쓴 경로는 `validity`는 통과해도 `exactMatch`·`reachesAnswer`에서 틀린다.
- **선언하지 않은 능력**(예: 벡터 RAG의 `path`)은 `{"status": "capability_not_declared"}`이며 0점이 아니다. 선언했는데 내지 않았으면 미달로 센다.
- 인용 지표는 **gold 근거 passage 집합에 속하는지**만 본다. 인용 문장이 주장을 의미상 뒷받침하는지는 사람·모델 평가가 필요하다. 사실별 인용 귀속(per-fact attribution)은 채점하지 않는다.
- 그래프 구성에서 방향·시점·unknown의 오류는 위 표처럼 각각 다른 지표다. 한 점수로 합치지 않는다.

### S3 `MAX_PATH=2`와 임의 3-hop 검색의 구분

S3 관계 생산 계약(`relation_contracts.MAX_PATH=2`)은 **관계 후보로 발행할 경로의 길이** 상한이다. 3단계 경로는 `path_too_long`으로 보류된다. 이 벤치마크의 `QA-4`, `QB-4`는 **검색·순회 시 임의 깊이** 질문이고, 하네스는 경로 길이를 제한하지 않는다(gold 경로 길이는 3까지이며 검증기가 길이에 상한을 두지 않는다). S3 상한 때문에 RAG·agent의 순회 깊이를 2로 자르지 않는다. 반대로 S3 후보 경로가 길이 3에서 보류되는지는 이 벤치마크가 아니라 `ai/pipeline`의 기존 시험 범위다.

## 지연·토큰·비용

- 시간은 **기록된 trace가 직접 준 구간**만 쓴다. 검증: 모든 시간은 유한한 0 이상 수이고, `endMs ≥ startMs`, span은 record 구간 안, 자식 span은 부모 구간 안이며, `spanId` 중복·알 수 없는 부모·순환·`llm`이 아닌 span의 `tokens`는 거부한다(`trace_invalid`로 run 전체 거부).
- `wallMs`는 record 자신의 `endMs-startMs`다. `llmMs`, `toolMs`는 해당 kind span 구간의 **합집합 길이**이고 `otherMs = wallMs - 전체 span 합집합`이다. 병렬 span을 더해 wall time으로 쓰지 않는다. 겹친 span이 있으면 `parallelSpans=true`로 표시한다. 여러 record의 지연도 합치지 않는다.
- 분포는 `ok` 기록만 쓰고 nearest-rank `p50=x[ceil(0.50n)]`, `p95=x[ceil(0.95n)]`, `max`다([`release-verification.md`](../development/release-verification.md)의 정의와 같다). 항상 표본 수 `n`을 함께 낸다. `n<10`이면 p50, `n<20`이면 p95에 “표본 부족” caveat를 붙인다(`n<20`에서 nearest-rank p95는 max와 같다). 이 임계는 보고 주의 문구용이며 합격 기준이 아니다. 표본 0이면 모든 값이 `null`이다.
- trace가 없는 `ok` 기록은 표본에서 빼고 `population.withoutTrace`로 센다(0 ms로 세지 않는다). span이 없으면 `llm/tool` 시간과 호출 수도 `null`이다. `refused`/`error` 기록은 지연 표본에 넣지 않는다.
- 토큰은 모든 `llm` span이 보고했을 때만 기록 단위 합이 있고, 하나라도 빠지면 그 기록은 `null`이다. 비용은 모든 span이 `costUsd`를 보고했을 때만 있다. 요약은 `{known, unknown, total}`이며 `known=0`이면 `total=null`이다. LLM span이 없다고 trace가 증명하는 경우에만 토큰 0이다.
- 지연의 의미는 `timing.*.semantics`에 표시한다: `recorded_live_trace`(live 기록), `replay_harness_time_not_model_latency`(replay), `authored_control_values_not_a_measurement`(control). hop별(`byHop`) 지연을 함께 낸다.
- 지연 비교는 `timingContext`(동시성·warmup·환경)가 같은 run끼리만 한다. 다르거나 없으면 `compare`가 지연 지표를 출력에서 뺀다.

## 비교 규칙 (`compare`)

- 같은 `corpusId/Revision/goldRevision/inputsSha256/split/tasks`, 같은 `provenance.kind`와 `executionMode`, 같은 scorer 버전만 비교한다. `runId`가 중복되면 거부한다.
- **authored control과 real_measured는 결코 같은 표에 올리지 않는다**(`mixed_provenance`). control끼리의 비교는 “채점기 점검”이라고 표시한다.
- 출력은 값·분자·분모·첫 run 대비 차이뿐이다. 순위·승자·합격/불합격 필드가 없다. `differingFactors`에 run 간에 다른 요인(`family`, `model`, 각 revision, `config.*`)이 나오고, 하나만 다르면 `oneFactorChange=true`다. `model`은 `provider/name@version` 한 묶음이므로 모델을 통째로 바꾸는 것은 요인 하나다. 같은 모델의 `version`만 바뀌어도 `model` 요인이 바뀐 것으로 보인다.

## 데이터 분리와 prompt 누출 방지

| 규칙 | 내용 | 강제 방법 |
|---|---|---|
| gold 은닉 | 시스템 입력은 `corpus.json`+`tasks.json`뿐이다. gold의 정답·근거·경로·결정 어휘를 프롬프트·few-shot·도구 설명·검색 색인에 넣지 않는다. | 시험이 시스템 가시 파일에 gold 어휘가 없는지 확인. `inputsSha256`로 시스템이 본 입력을 고정 |
| dev/test 분리 | 한 문서는 한 split의 한 task에만 속한다. 같은 `originFamily`(재보도 계열), 같은 entity가 양쪽 split의 gold edge에 쓰이지 않는다. 질문의 근거·경로·답은 자기 split 안에 있다. | `validate`가 위반 시 `split_leakage`로 거부 |
| dev 사용 | 프롬프트·도구·K·한도 선택은 dev에서만 한다. | 절차 규칙 |
| test 1회 | 설정을 동결하고 기록한 뒤 test는 설정당 한 번만 연다. test 결과를 보고 고치면 dev로 돌아가고 새 test 사례를 새 revision으로 추가해야 한다. | 절차 규칙. run 파일의 `recordedAt`·`runId`로 추적 |
| 다른 split 기록 거부 | dev run이 test case 기록을 가지면 `unmatched_case`. | `parse_run` |
| 재사용 금지 | gold를 사람이 본 뒤 프롬프트를 고치는 행위를 막을 수는 없으므로, 어느 revision을 보고 튜닝했는지 run 메타데이터에 적는다. | 절차 규칙 |

사례를 기존 PoC 코드·사설 저장소의 평가 내부 구조에서 복사하지 않았다. gold는 corpus 문장을 보고 새로 작성했다.

## gold 검수 절차 (제안, 아직 실행하지 않음)

1. **작성**: corpus 문장만 보고, 어떤 시스템의 출력도 보지 않은 상태에서 작성자 A가 gold를 쓴다. 근거 passage를 edge마다 적는다.
2. **독립 라벨링**: 작성자 B가 gold를 보지 않고 `tasks.json`만으로 entity 링크·병합·edge·질문 답을 라벨링한다.
3. **불일치 합의**: 불일치 항목을 목록화하고 제3자 또는 합의 회의에서 결정한다. 합의가 안 되면 모호한 항목은 `UNDECIDABLE`/`null`/abstain으로 남기고 정확 일치 채점 대상에서 제외한다. 모호함은 지우지 않고 기록한다.
4. **동결**: `goldRevision`을 올리고 `validate`의 `goldSha256`을 기록한다. 이후 gold 수정은 새 revision이며 이전 revision 결과와 비교하지 않는다.
5. **기록**: 작성자 수, 합의 여부(`adjudicated`), 불일치율을 `gold.json`의 `provenance`에 적는다. 지금은 `annotators=1, adjudicated=false`다.
6. **규모**: 거버넌스 문서 [`ZOOP_AI_거버넌스_정책_v0.1.md`](../ZOOP_AI_거버넌스_정책_v0.1.md) 11절은 일반 유형 20건 이상, 복잡·예외 40건 이상을 **제안**한다. 현재 split당 질문 9·그래프 task 5는 이에 한참 못 미친다. 사람 gold를 먼저 만들자는 팀 내 제안은 결정이 아니라 제안이다(`docs/evidence/raw/notion_2026-10-03` 0916 스크럼 기록).

## 공정한 baseline과 경쟁 서비스의 분리

**Baseline 후보(모두 `system.family`로 구분, 아직 구현·측정 전).** 비교는 같은 corpus·split·도구 예산·`timingContext`에서만 한다.

| ID | family | 설명 | 선언하는 capability | 모델 호출 |
|---|---|---|---|---|
| B0 | `no_model_deterministic` | 전부 abstain하는 control. 하한 점검용이며 시스템 결과가 아니다 | 없음 | 0 |
| B1 | `no_model_deterministic` | 결정적 도구(문자열·정규식·고정 규칙)만 쓰는 구성·검색 | 구현에 따름 | 0 |
| B2 | `vector_rag` | 청크 벡터 top-K 검색 후 답변. 임베딩·답변 모델이 필요하면 모델 호출 | `retrieval`, `citations` (경로 없음 → 경로 지표는 `null`) | 있음 |
| B3 | `fixed_graph_traversal` | 시스템이 구성한 그래프 위에서 앵커→고정 규칙 순회(LLM이 경로를 고르지 않음). gold 그래프 위의 순회는 **상한 control**로 따로 표시하고 시스템 결과와 섞지 않는다 | `retrieval`, `path`, `citations` | 0 또는 답변 생성 시 있음 |
| B4 | `agent_graphrag` | LLM이 도구(그래프 조회·검색)를 호출해 경로를 고른다. `reasoningEffort`·`maxToolCalls`·`maxHops` 변형을 격자로 비교 | 전부 | 있음 |

Microsoft GraphRAG 문서([Query Overview](https://microsoft.github.io/graphrag/query/overview/))는 **Basic Search**(벡터 RAG top-k baseline), **Local Search**(그래프+텍스트 청크로 특정 entity 질문), **Global Search**(커뮤니티 보고서 map-reduce로 데이터셋 전체 질문), **DRIFT Search**(커뮤니티 정보로 Local을 확장)를 구분한다. 위 B2·B3·B4의 구성을 정할 때 후보로 참고하며, 어느 쪽이 우월하다는 근거로 인용하지 않는다. 학술 논문의 성능 주장은 이 문서에서 인용하지 않았고, 필요하면 출처를 읽고 별도로 조사한다.

**경쟁·참고 서비스(조사 후보일 뿐, 선정·측정하지 않음).** `docs/evidence/notion-decisions.md`는 토스증권 AI, Google Finance, ChatGPT 금융을 조사자의 해석으로 기록하며 팀 검증을 받지 않았다. 이 서비스들은 trace·그래프·근거 passage가 비공개일 수 있어 같은 구조화 기록(`path`, `retrieved`, trace span)을 만들 수 없다. 따라서:

- 우리 하네스의 run과 **같은 표에 올리지 않는다**. 별도 참고 표에 “검토 방식, 날짜, 질문, 관찰 가능한 필드”만 기록한다.
- 접근 가능한 것은 같은 질문을 입력해 얻은 최종 답과 화면의 출처 표시뿐이다. 이 경우 `family=other`, `capabilities`를 관찰 가능한 것만 선언한 별도 run으로 기록하되, 사람이 수기로 입력·판독한 값은 recorder에 그렇게 표시하고 지연 비교 대상에서 뺀다.
- 서비스 이용 약관·계정·과금·개인정보 조건을 확인하기 전에는 질의하지 않는다(승인 경계 참조). 실제 시장 데이터가 포함된 질의는 합성 corpus와 비교 가능하지 않으므로 **정확도 순위로 쓰지 않는다**. 경쟁 비교는 기능 축(근거 표시 단위, abstain 상태, 시점 표시)의 서술에 한정한다.

## 첫 측정 계획 (제안, 승인 전 실행 금지)

원칙은 **한 번에 한 요인만 바꾸고 나머지는 고정**하는 것이다. 모든 단계의 점수는 dev에서만 보고, 요인 선택이 끝난 뒤 test를 설정당 1회 연다. LLM의 비결정성이 있으므로 같은 설정을 반복 실행해(제안: 3회) run을 각각 보고하고 평균으로 합치지 않는다.

| 단계 | 내용 | 비고 |
|---|---|---|
| 0 | 하네스·authored control 확인(완료) | 모델 호출 0 |
| 1 | B0, B1(결정적 도구) 기록을 하네스에 넣어 하한을 확인 | 모델 호출 0 |
| 2 | 기준 구성 고정: 가장 낮은 지연·노력 설정(낮은 `reasoningEffort`, 적은 `maxToolCalls`, 3 hop까지 허용). 모델은 “빠르고 저렴한 후보”를 승인 후 선정 | 후보 이름은 아직 정하지 않음 |
| 3 | 한 요인씩 변경(아래 격자) | 요인마다 별도 run |
| 4 | 동결한 구성으로 test 1회 | dev 결과를 본 뒤 수정 금지 |
| 5 | 지연은 정확도 run과 분리한 별도 run에서 동시성 `C=1→5→10`, warmup 제외, `timingContext` 기록 | 단계 구분은 [release-verification.md](../development/release-verification.md)의 제안과 같다(그 값도 작업자 제안) |

**요인 격자(제안값; `system.config` 키 이름 규약).** 값은 아직 어떤 사실로도 확정되지 않았다.

| 요인 | 키 | 시작 | 변경 값 |
|---|---|---|---|
| 추론 노력 | `reasoningEffort` | 제공자가 지원하는 가장 낮은 값 | 한 단계씩 높임(제공자별 문자열을 그대로 기록) |
| 도구 호출 한도 | `maxToolCalls` | 4 | 8, 16 |
| 순회 깊이 | `maxHops` | 3 | 1, 2 (3 초과는 4-hop gold를 만든 뒤) |
| 검색 폭(B2) | `topK` | 5 | 3, 10 (dev에서 선택) |
| 출력·시간 한도 | `maxOutputTokens`, `timeoutMs` | 제공자 기본값 기록 | 한 번에 하나 |
| 모델 | `system.model` | 기준 후보 1개 | 다른 후보(요인 하나로 취급) |

**합격 기준은 정하지 않는다.** 이 문서는 정확도·지연·비용 목표를 만들지 않는다. 참고로 거버넌스 문서의 매크로 F1 0.90, 유형별 recall 0.85, false approval 0건과 `release-verification.md`의 로컬 p95 제안은 모두 **확정되지 않은 제안**이며, 이 벤치마크 지표와 단위·정의가 다르다. 팀이 수용 기준을 승인하고 표본 수가 정해진 뒤에만 합격 판정을 한다. 승인값은 실행 전에 기록하고 결과를 본 뒤 바꾸지 않는다. 현재 표본으로는 p95를 대표값으로 쓸 수 없다(질문 9개).

## 승인 경계와 WBS

다음은 사용자 승인 없이 하지 않는다: 실제 모델 호출·과금(공급자, 모델, 비용 상한, 데이터 전송 권리를 먼저 정함), 외부 서비스·경쟁 서비스 질의, Neo4j 등 그래프 DB 설치·기동, 새 의존성 설치, test split 사용·결과 공개, `ai-system.md`·루트 `Makefile`·CI 연결, 결과의 대외 공개. 승인 전에는 `provenance.kind=real_measured`인 run 파일을 만들지 않는다.

WBS는 변경하지 않았고 이 벤치마크는 독립 WBS 행·일정이 없다. 참고용 원문 행은 6.6.15–6.6.20(FS076–FS081, 2026-09-21–10-15), 6.11.4(윤서진, 10-12–10-27), 6.11.5(김도현, 10-12–10-27), 6.11.6(안재현, 10-19–10-23)이다. 담당·일정의 재배정은 이 작업의 범위가 아니다.

## 한계와 아직 측정하지 않는 것

- 실제 검색기·채팅·그래프 DB가 없어 어떤 시스템의 점수도 없다. control은 채점기 점검이다.
- gold는 단일 작성자 초안이며 합의를 거치지 않았다. 규모가 작아(split당 질문 9, 그래프 task 5, edge 13) 비율이 거칠다. 통계적 유의성 검정은 하지 않는다.
- 자유 서술 품질, 인용의 의미적 뒷받침, 사실별 인용 귀속, 사용자 체감 품질은 측정하지 않는다.
- 한국어 기사 corpus가 아니라 영어 합성 문장이다. 한국어 개체·날짜 표현의 난점은 이 corpus가 검증하지 않는다.
- trace의 시계(단조 시계)와 span 의미는 adapter가 보장해야 한다. 하네스는 일관성만 검사하고 측정이 정확한지는 알 수 없다.
- replay 기록의 지연은 하네스 시간이며 모델·서비스 지연이 아니다.
- 이 하네스는 `ai/evaluation`에서만 동작하며 BFF·S1·S2·S3 코드를 import하지 않는다.
