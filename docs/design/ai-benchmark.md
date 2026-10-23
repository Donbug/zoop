# AI 그래프·검색·답변 벤치마크: 평가 하네스와 측정 계획

**이 문서가 다루는 것.** 기록된 출력과 trace를 별도로 작성한 gold와 결정적으로 비교하는 평가 하네스(`ai/evaluation`), 지표 정의, 데이터 분리·gold 검수 방법, baseline·경쟁 서비스의 비교 조건과 승인 경계를 정한다. gold의 작성 방식과 검수 수준은 각 corpus의 provenance를 따른다.

**현재 상태 (사실).**

- 순수 채점기는 모델·네트워크·DB를 호출하지 않는다. 실행 다리는 합성 loopback HTTP 검증과 별도 승인된 로컬 Neo4j 도구 측정을 지원한다. 아래 절에서 실제 실행 경계와 모의 응답을 구분한다.
- 이 하네스에는 전체 벡터 RAG·일반 채팅·agent 답변 실행을 연결한 측정 결과가 없다. 그래프 도구 baseline은 호출 비용·이웃 결과 정확성만, 네이티브 이슈 요약 검증 다리는 검증 하위 단계의 기록·채점 정합성만 확인했다. 다른 팀의 구현 유무나 전체 서비스 품질을 이 상태로 단정하지 않는다.
- 기존 합성 corpus의 gold는 **단일 작성자 초안**이며 두 사람의 독립 라벨링·합의(adjudication)를 거치지 않았다(`adjudicated=false`, `annotators=1`). 여기서 나온 점수는 실제 데이터에 대한 정확도 주장이 아니다. 별도로 수집한 공개 자료의 원래 annotation은 아래 “실제 자료와 gold 제작 프로토콜”에서 구분한다.
- 자유 서술 답변의 의미 품질은 정확 일치로 판정할 수 없다. 사람 또는 모델 평가가 필요하며 이 하네스는 그 지표를 만들지 않는다(`freeText.status = human_or_model_evaluation_required`).
- **2026-10-22 추가:** 본개발 `verify-issue-summary`의 요청·원문 응답·판정을 기록하고 독립 채점하는 네이티브 다리를 연결했다. 한국어 합성 24개 사례·30개 주장, 실제 로컬 HTTP 대조군, 중단 복구와 변조 거부를 검증했다. 실제 Jev 품질·생성 품질·전체 RAG 성능·임곗값 보정 결과는 아니다.
- **외부 자료 변환:** KLUE RE 20행과 TAT-QA 5개 context·30개 질문의 입력/gold를 분리한 개발용 자료를 저장했고, `materials-validate`·`materials-inputs`·`materials-gold` 읽기 전용 adapter를 구현했다. 대표 표본·held-out test가 아니며 모델 실행·외부 자료 채점·전체 benchmark는 이 변환의 범위가 아니다.

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
  "schema": "zoop-bench-run-1", "runId": "r-agent-high-001", "label": "optional",
  "provenance": {
    "kind": "real_measured",            // 또는 "authored_control"
    "executionMode": "live",            // real_measured: live|replay, authored_control: authored
    "recorder": "adapter name/version", "recordedAt": "2026-10-20T01:02:03+09:00"  // authored_control은 null + controlKind 필수
  },
  "corpus": { "corpusId": "zoop-bench-v1", "corpusRevision": "2026-10-14.1", "goldRevision": "2026-10-14.1",
              "inputsSha256": "(선택, validate가 출력하는 값)", "split": "dev", "tasks": ["graph", "qa"] },
  "system": {
    "systemId": "agent-graphrag-high", "family": "agent_graphrag",   // no_model_deterministic|vector_rag|fixed_graph_traversal|agent_graphrag|other
    "model": { "provider": "…", "name": "gpt-6-luna", "version": "…" }, // 실제 실행 시 고정 버전 기록; 모델이 없으면 null
    "config": { "reasoningEffort": "high", "maxToolCalls": 8, "maxHops": 3, "topK": 5, "timeoutMs": 120000 },  // 실험 제안 예시, 스칼라만
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
| test 캠페인 | dev에서 설정과 반복 계획을 동결한 뒤 test를 하나의 캠페인으로 실행한다. 사전에 정한 반복은 허용하지만 test 결과로 재튜닝하지 않는다. 수정하면 dev로 돌아가고 새 held-out test revision을 준비한다. | 절차 규칙. run 파일의 `recordedAt`·`runId`와 캠페인별 반복 계획으로 추적 |
| 다른 split 기록 거부 | dev run이 test case 기록을 가지면 `unmatched_case`. | `parse_run` |
| 재사용 금지 | gold를 사람이 본 뒤 프롬프트를 고치는 행위를 막을 수는 없으므로, 어느 revision을 보고 튜닝했는지 run 메타데이터에 적는다. | 절차 규칙 |

사례를 기존 PoC 코드·사설 저장소의 평가 내부 구조에서 복사하지 않았다. gold는 corpus 문장을 보고 새로 작성했다.

## gold 검수 절차 (제안, 아직 실행하지 않음)

1. **독립 작성**: 두 사람이 corpus와 시스템에 보이는 task를 읽고 서로의 라벨과 시스템 출력을 보지 않은 상태에서 entity 링크·사건·병합·방향/기간·질문 답·근거를 각각 작성한다.
2. **불일치 합의**: 불일치 항목을 목록화하고 제3자 또는 합의 회의에서 결정한다. 합의가 안 된 항목은 모호함을 기록하고 `UNDECIDABLE`/`null`/abstain 등 해당 계약으로 표현한다. 결정 가능한 항목의 정확도와 모호한 항목의 안전한 보류를 구분한다.
3. **평가자 분리**: Jev는 평가 대상인 운영 검증기다. Jev가 자기 평가에 쓸 gold를 결정하게 하지 않는다. 모델의 보조 제안이나 문서 일관성 검토를 사람의 독립 라벨링·합의로 표시하지 않는다.
4. **동결**: 입력과 gold revision·digest, 작성자 수, 합의 여부, 불일치율·해결 근거를 기록한다. 기존 형식은 `validate`의 `goldSha256`을 사용한다. 수집된 KLUE/TAT-QA는 아래 `materials-*`로 구조·무결성을 확인하고 `inputsSha256`으로 정규화 입력에 gold를 묶을 수 있다. 이 binding을 사람 합의나 scorer 연동으로 해석하지 않는다.
5. **규모와 상태**: 기존 합성 corpus는 여전히 `annotators=1, adjudicated=false`다. 거버넌스 문서 [`ZOOP_AI_거버넌스_정책.md`](../ZOOP_AI_거버넌스_정책.md) 11절의 일반 유형 20건 이상·복잡/예외 40건 이상은 제안이며, 아래 실제 자료 계획이나 의미 품질의 승인 임곗값을 대신하지 않는다.

## 실제 자료와 gold 제작 프로토콜

**한국어 실제 공시의 별도 gold가 주 평가 자료다.** 공개 데이터셋은 관계 판별·표/수치 QA·다중 근거 검색 등 하위 능력의 보조 평가로 사용한다. 아래 계획은 자료 수집·평가 설계이며 실제 모델 성능 결과가 아니다.

### 수집한 개발용 자료

[`external-pilot-v1/manifest.json`](../../ai/evaluation/corpus/external-pilot-v1/manifest.json)에 원출처·reader URL·라이선스·변경 내역·파일별 SHA256과 바이트 크기를 기록했다. 입력과 gold 두 쌍, 총 네 파일을 저장했으며 annotation은 다시 쓰거나 번역하지 않고 원자료에서 분리했다. 수집 과정에서 모델 호출·원저장소 코드 실행은 없었다.

- **KLUE RE:** HF train의 첫 20행이다. 고유 행 20개와 원래 inclusive 좌표의 entity span 40개가 일치했다. 관측한 HF metadata revision은 `349481ec73fff722f88e0453ca05c77a447d967c`이나 row 응답과 이 revision의 결합은 **미검증**이다. 로컬 해시는 저장 표본을 고정할 뿐 공식 배포본과의 동일성을 증명하지 않는다.
- **TAT-QA:** 공식 dev 파일의 첫 5개 context, 고유 질문 30개다. reader가 생략한 마지막 LF 하나를 복원한 원본은 1,637,431바이트이며 Git blob `48075c812af3fe6698b1d5cb50d9dbf358d52784`와 일치했다.
- **수집 무결성 확인:** 네 파일의 저장 해시·크기, 고유 ID, KLUE 좌표를 확인했다. 입력과 gold를 합치면 선택한 원래 행/질문과 정확히 같고, 시스템에 보이는 입력의 gold annotation 키는 0개였다. 이는 수집·분리 확인이지 기존 scorer로 채점한 결과가 아니다.
- **사용 한계:** 원자료 순서로 고른 표본이며 무작위·균형·대표 표본이 아니다. 이미 열람한 개발용 자료이므로 held-out test로 승격하지 않는다. `materials-*`는 자료 변환만 지원한다. 기존 `score`·`verify-score`·`summary-verify-score`는 원자료와 `zoop-eval-material-{inputs,gold,validation}-1`을 받지 않는다. 외부 자료 전용 run/채점 계약과 B1–B4 실행 연결은 별도 작업이다.

### Material adapter의 계약과 확인 범위

```bash
cd ai/evaluation
python3 -B -m zoop_eval materials-validate
python3 -B -m zoop_eval materials-inputs --dataset klue-re
python3 -B -m zoop_eval materials-inputs --dataset tatqa
python3 -B -m zoop_eval materials-gold --dataset klue-re
python3 -B -m zoop_eval materials-gold --dataset tatqa
python3 -B -m unittest discover -s tests -p 'test_materials.py'
python3 -B scripts/materials_smoke.py
```

기본 `--materials`는 `corpus/external-pilot-v1`이다. 세 명령은 stdout JSON만 출력하며 파일·네트워크·모델·provider 상태를 쓰거나 애플리케이션 환경/`.env`를 읽지 않는다. 성공은 종료 코드 0, 구조·무결성 거부는 기존 `Rejected` JSON과 종료 코드 2이며 부분 성공을 내지 않는다. 파일 역할·허용 basename·8 MiB 상한·regular file·SHA256·바이트 크기를 확인하고, symlink·경로 이탈·중복 JSON 키·비유한 상수·정수 자리에 온 bool·추가 annotation 키를 거부한다.

`materials-inputs`는 manifest와 선택한 입력만 열고 gold의 존재를 요구하지 않는다. `validationScope=manifest-and-selected-input-only`를 그대로 내므로 gold 검증과 혼동하지 않는다. `materials-gold`는 선택한 자료의 입력과 gold를 열어 정확한 ID/context 대응까지 확인한다. `materials-validate`만 네 파일 모두를 검사한다. schema별 닫힌 필드 정의는 `ai/evaluation/zoop_eval/contracts.py`에 있다.

- **KLUE 입력/정답:** guid·문장·source·entity 문자열/유형을 보존한다. substring을 먼저 확인하고 inclusive 좌표를 Unicode code point 기준 `[start,end)`로 바꾼다. 모델 선택지는 공개 30개 label을 코드에 고정해 gold 읽기와 분리했다. 정답은 원래 숫자 ID와 공개 label을 함께 보존하며 S3의 다섯 predicate로 바꾸지 않는다.
- **TAT-QA 입력/정답:** table UID/셀과 paragraph UID/order/text를 context로 유지하고 question UID/order/text가 이를 참조한다. 입력에서 정답·유형·출처·식·scale·support annotation 키를 배제하되 원래 문맥의 단어·숫자는 지우지 않는다. gold는 `answer`, `answer_type`, `answer_from`, `scale`, `derivation`, `req_comparison`, `rel_paragraphs`를 보존하고 paragraph order를 같은 context의 UID로 연결한다. 빈 값·null·알 수 없는 문자열 annotation을 추정하지 않고 table-cell gold도 만들지 않는다. 숫자는 Decimal로 읽고 내보내 정밀도와 음수·원래 단위를 유지한다. 번역·날짜 보충·식 실행·답 추론은 하지 않는다.
- **Binding과 출처:** `inputsSha256`은 `materials-inputs`의 키 정렬·공백 없는 UTF-8 JSON 전체(마지막 LF 제외)의 digest이며 원본 파일 SHA256과 구분한다. 배열은 원자료 순서를 유지한다. 원저자·라이선스·URL·수집/변경 provenance·파일 해시와 `development-intake` 상태를 유지한다. manifest의 `collectionExecution`은 수집 당시 기록이지 현재 adapter 구현 상태가 아니다. HF row/revision 결합은 여전히 미검증이고 upstream annotation은 Zoop 사람 합의 gold가 아니다. 해시 일치만으로 출판자 진위·법적 이용권·모델 전송 승인이 생기지 않는다.

smoke는 실제 수집 파일과 임시 invalid fixture를 실제 CLI로 처리하고 성공 시 관측된 20행·30문항과 proof scope를 출력한다. gold 부재/접근 금지, canonical binding, 잘못된 label·paragraph·annotation 거부를 다룬다. audit 범위는 Python import 이후 command seam의 파일 접근·쓰기·네트워크·자식 프로세스·애플리케이션 환경 조회다. Python 시작이나 argparse의 locale·화면 크기 조회까지 환경 읽기 0으로 주장하지 않는다. 이는 자료 변환 확인이지 정확도나 모델 품질 결과가 아니다. 사람 합의 한국어 gold, 무모델 어휘 검색·방향/시점 순회 baseline, 외부 자료 run/채점 연결과 승인된 live 측정은 남아 있다.


### 자료 후보 6종과 권리 경계

| 자료·1차 출처 | 평가 용도 | 현재 상태와 권리·한계 |
|---|---|---|
| [OpenDART](https://opendart.fss.or.kr/intro/main.do), [검색 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001), [원문 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003) | 한국어 기업·사건, 정정/철회, 방향·시점·인용 gold의 원천 | **조사 완료·수집 전 승인 필요.** [약관](https://opendart.fss.or.kr/intro/terms.do)에 따른 키·등록 이용 범위와 외부 모델 전송 권리를 확인한 뒤 40–60문서를 목표로 한다. 재배포까지 포괄 허용된 것으로 해석하지 않는다. |
| [KLUE RE](https://github.com/KLUE-benchmark/KLUE), [공식 스키마](https://github.com/KLUE-benchmark/KLUE/wiki/KLUE-RE-dataset-description) | 한국어 관계·무관계·방향·멘션 위치 | **20행 수집.** [CC BY-SA 4.0](https://github.com/KLUE-benchmark/KLUE/blob/main/License.md); 출처·변경 표시와 동일조건 준수. 일반 영역 관계 gold이지 금융 사건 병합·시계열 그래프 gold가 아니다. |
| [FinQA](https://github.com/czyssrs/FinQA), [공식 데이터 사이트](https://finqasite.github.io/) | 영어 금융 표/본문 근거와 계산 | **조사만 완료.** 데이터 CC BY 4.0, 코드 MIT. execution/program accuracy의 보조 후보이며 계산 단계 수를 그래프 hop 수로 세지 않는다. |
| [TAT-QA](https://github.com/NExTplusplus/TAT-QA), [공식 예시](https://nextplusplus.github.io/TAT-QA/) | 영어 금융 표+본문 QA, 단위·스케일 | **5개 context·30문항 수집.** 데이터 CC BY 4.0, 코드 MIT. 공식 EM/F1와 scale을 보조 평가에 쓰며 `dataset_tagop`의 휴리스틱 `facts/mapping`을 사람 gold로 취급하지 않는다. |
| [FinanceBench](https://github.com/patronus-ai/financebench), [공식 데이터 카드](https://huggingface.co/datasets/PatronusAI/financebench/blob/main/README.md) | 영어 공시 답변·페이지 근거 | **권리 확인 전 보류.** CC BY-NC 4.0. 평가 목적의 비상업성 또는 별도 허가를 확인해야 한다. 공개 150문항을 연구 전체 10,231문항과 혼동하지 않는다. |
| [MuSiQue](https://github.com/StonyBrookNLP/musique) | 2·3-hop 근거 연결, 근거 부족 시 abstain | **조사만 완료·동일성 확인 전 채택 보류.** 공식 CC BY 4.0. 실제 문단을 연결한 구성형 질문이며 금융 자료가 아니다. 열람한 비공식 미러와 공식 배포본의 동일성은 미검증이다. |

추가 후보인 [AI Hub 금융·법률 문서 기계독해](https://www.aihub.or.kr/aihubdata/data/view.do?currMenu=115&dataSetSn=71610&topMenu=100)는 [이용정책](https://www.aihub.or.kr/intrcn/guid/usagepolicy.do?currMenu=151&topMenu=105)상 평가 목적 사용과 외부 모델 API 전송·국외 반출 허용이 확인되지 않아 사용을 보류한다. 공개 접근이나 CC 표시만으로 모든 제3자 권리·전송·재배포가 승인되었다고 보지 않는다.

### 한국어 주 평가 자료와 split 제안

OpenDART 수집이 승인되면 실제 공시 40–60문서에서 **dev QA 30개·test QA 60개**, 짧은 브리핑 **dev 4개·test 8개**를 만드는 안을 사용한다. 이는 목표 규모이지 확보된 자료 수나 일정 약속이 아니다.

1. **원문과 시점 보존:** 접수일, 사건 발생일, 발행/수집 시각을 구분한다. 원문에 있는 날짜·시각의 정밀도와 정정 이력을 보존하고 날짜만 있는 값을 임의의 시각으로 늘리지 않는다. 원문 버전·해시·인용 위치를 고정하며 접수일을 사건 발생일로 대체하지 않는다. 기존 날짜 전용 scorer의 계약보다 정밀한 값은 adapter 설계에서 다루고 조용히 손실 변환하지 않는다.
2. **묶음 단위 분리:** 연결된 사건 계열, 정정본·첨부·중복/재보도, 재사용 표, 기업 간 연결 경로를 한 그룹으로 묶어 dev/test에 나눈다. 같은 경로의 기업을 회사명만으로 따로 분리하지 않는다. 보조 금융 자료끼리도 기업·연도·보고서·본문 중복을 확인한다.
3. **QA 구성:** 실제 근거가 있는 범위에서 split별 1·2·3-hop을 균형 배치한다. 연결 근거가 부족하면 부족한 수를 보고하고 관계나 경로를 만들어 채우지 않는다. 정정/철회, 계약 확정/예정, 날짜 미상, 기업 별칭·동명이인, 역방향, 공동 언급뿐인 문장, 증거 부족·상충을 포함한다.
4. **브리핑 gold:** 정답 문장 하나가 아니라 필수 사실·허용 사실·금지 추론과 주장별 인용을 정의한다. 두 사람의 독립 라벨링과 합의로 수치·시점·인과·투자 권유·중요 사실 누락을 평가한다.
5. **입력 은닉:** 원문은 검색할 수 있지만 정답·gold 근거 표시·도출 과정은 입력/색인에서 제외한다. 예를 들어 TAT-QA의 `answer/derivation/rel_paragraphs`, FinQA의 `program/gold_inds/exe_ans`, MuSiQue의 `question_decomposition/is_supporting/answerable`은 숨긴다. MuSiQue 채택 시 공식 원천 single-hop 누출 방지 목록도 적용한다.

영어 보조 평가는 한국어 원문 평가와 **점수를 합산하지 않는다**. 번역본도 별도 조건으로 표시한다. 오래된 공개 자료의 사전학습 오염을 배제할 수 없으므로, 이 자료의 점수를 최신 한국어 held-out 성능으로 대체하지 않는다.

## 공정한 baseline과 평가 트랙

### 네 가지 질문을 분리한다

| 트랙 | 입력 → 평가 대상 | 통제 조건과 해석 |
|---|---|---|
| G: 그래프 구성 | 원문 → entity·event·병합·방향/시간 그래프·인용 | 추출·병합·방향·기간·인용을 기존 지표별로 채점한다. 검색기가 좋아서 구성 오류가 가려지지 않게 한다. |
| R: 검색·선택 | 같은 원문 corpus와 동결된 **동일 시스템 그래프** → 근거·경로 선택 | 검색/순회 방식만 비교한다. gold 그래프는 별도 상한 진단이며 주 결과에 섞지 않는다. |
| A: 전체 답변 | 원문 → 그래프 구축을 포함한 QA·브리핑 | 구성부터 최종 답변까지 평가한다. 그래프 구축·색인 비용과 온라인 질의 비용을 분리한다. |
| J: 검증기 | 고정된 주장·인용 → 독립 검증 판정 | 사람이 합의한 gold로 `jev-1.14.0`을 별도 평가한다. J 점수를 생성기나 전체 A 성능으로 대체하지 않는다. |

### B0–B4 대조군

아래 시스템 대조군은 **구현·측정 제안**이다. 이미 측정한 무방향 `focus` 도구 control과 구분한다. 생성형 비교는 같은 corpus·청크·질문·생성 지침·문맥 상한·실행 환경을 쓰고, R에서는 그래프도 같아야 한다.

| ID | 구현 제안·family | 공정한 비교 조건 |
|---|---|---|
| B0 | 전부 abstain하는 authored 하네스 점검, `no_model_deterministic` | 경쟁 시스템이나 실측 하한이 아니다. 실제 측정과 같은 표에 넣지 않는다. |
| B1 | TF-IDF 또는 BM25 어휘 검색 + 동일 생성기, `other` | 임베딩 없음. 토큰화/문자 n-gram·선택 방식은 dev에서 고정한다. 검색 단계만 먼저 무모델로 측정할 수 있으나 전체 B1 답변에는 생성 호출이 필요하다. |
| B2 | 벡터 top-K RAG + 동일 생성기, `vector_rag` | B1과 같은 청크·topK·문맥 상한을 사용한다. 임베딩 모델은 미선정이며 승인 없이 ID를 정하지 않는다. |
| B3 | 고정 1–3-hop 순회 + 동일 생성기, `fixed_graph_traversal` | 동일 시스템 그래프에서 방향·predicate·`asOf`를 적용한다. 검색/순회 단계에는 모델을 쓰지 않는다. gold 그래프 결과는 별도 상한 진단이다. |
| B4 | 그래프·검색 도구를 선택하는 agent + 동일 생성기, `agent_graphrag` | B3와 같은 그래프·도구 계약을 쓰고 도구/문맥 예산을 고정한다. 경로 선택 효과와 그래프 구축 효과를 섞지 않는다. |

경로를 내지 않는 B1/B2에 경로 capability를 선언하지 않는다. 미지원 경로 점수를 0점으로 처리해 순위를 만들지 않는다. 현재 무방향 `focus`의 depth 지연은 B3의 방향·시점 추론 성능이나 B4의 3단계 agent 추론 지연이 아니다.

선택적 외부 참고 구현은 [Microsoft GraphRAG Local](https://microsoft.github.io/graphrag/query/local_search/)과 [LightRAG `naive`/`hybrid`/`mix`](https://github.com/HKUDS/LightRAG#selecting-query-modes)다. 코드는 각각 [MIT](https://github.com/microsoft/graphrag/blob/main/LICENSE), [MIT](https://github.com/HKUDS/LightRAG/blob/main/LICENSE)이며 **아직 설치·실행하지 않았다**. 채택 시 commit·설정·프롬프트·추출 모델·reranker·캐시를 고정한다. Local이나 `mix`를 자동으로 3단계 tool agent와 동등하다고 보지 않는다. [GraphRAG Global](https://microsoft.github.io/graphrag/query/overview/)의 community map-reduce는 별도 브리핑 과제로 평가한다. 공개 논문 점수를 가져와 자체 순위표를 만들지 않는다.

토스증권 AI·Google Finance·ChatGPT 금융 같은 외부 서비스는 별도 관찰 대상이다. 약관·계정·과금·데이터 전송 승인 전에 질의하지 않는다. trace·그래프·원문 corpus를 통제할 수 없으면 근거 표시·abstain·시점 표시 등 관찰 가능한 기능만 서술하고 자체 대조군과 정확도·지연 순위를 매기지 않는다.

## 첫 측정 프로토콜 (제안, live 실행은 별도 승인)

**기준 모델은 `gpt-6-luna High`와 `jev-1.14.0`을 유지한다.** 빠른 첫 대조군은 낮은 Luna effort가 아니라 **모델 없는 어휘 검색·고정 순회 단계**다. 약한 모델 비교는 모델명·버전·사용권·예산을 명시적으로 승인받은 뒤에만 한다. 그때도 먼저 planner만 바꾸고 생성기·검증기·도구 예산은 고정한다. 모델 전체를 교체하는 실험은 별도 요인으로 분리한다.

### dev 초기 설정과 test 동결

| 항목 | dev 제안값 | 동결·기록 규칙 |
|---|---|---|
| 순회·도구 한도 | `maxHops=3`, `maxToolCalls=8` | 질문의 실제 근거 hop과 실제 호출 수도 기록 |
| 검색·문맥 | `topK=5`, 문맥 8,000토큰 | 같은 청크와 토큰 계산 기준 사용; 임베딩 모델은 선정·승인 후 고정 |
| 제한 시간·동시성 | `timeoutMs=120000`, concurrency 1 | 같은 환경에서 측정; 운영 NFS나 서비스 SLA가 아닌 실험 제안 |
| 반복 | 설정당 3회 | 서로 다른 task 수와 반복 시도 수를 분리; test 반복 계획도 test 열람 전에 고정 |
| 모델·버전 | `gpt-6-luna High`, `jev-1.14.0` | 실제 버전·프롬프트·도구·schema·graph·corpus/gold revision 기록 |

dev에서 한 번에 한 요인만 바꾸어 선택한 뒤 모든 설정과 실패 처리·반복 계획을 동결한다. test는 그 설정의 단일 캠페인으로 실행하며 사전 계획한 반복을 재튜닝 기회로 사용하지 않는다. test 결과를 보고 바꾸면 새 held-out revision이 필요하다. 반복 평균만으로 서로 다른 질문 수가 늘어난 것처럼 보고하지 않는다.

### 보고할 지표와 구현 경계

- **정확도:** 1·2·3-hop별 최종 답 정확도·전체 근거 회수·경로 유효성·방향/시점 오류·abstain을 나눈다. J는 false approval과 안전한 답변의 수용률을 함께 보고한다. 브리핑은 사람이 주장별 의미적 지지와 필수 사실 누락을 판정한다. 기존 passage 집합 일치 지표를 의미적 지지로 부르지 않는다.
- **지연·비용:** 색인/그래프 구축과 온라인 질의를 분리하고 wall·LLM·도구·검색·검증 구간을 기록한다. cold/warm, 준비 실행, 답변/검색 캐시 적중 여부를 명시한다. 공급자가 보고한 실제 토큰·비용, 추정값, 미상 값을 구분하고 미상을 0으로 채우지 않는다.
- **실패와 표본:** 오류·timeout·미시도는 정확도 분모에서 빠지지 않는다. 서로 다른 task 수, 반복 수, 성공/실패 수를 별도로 낸다. 기존 공통 latency scorer는 `ok` 기록만 분포에 쓰고 `refused/error`는 제외하므로 그 분포를 전체 시도 지연으로 표시하지 않는다. 실패 지연·timeout은 별도 보고가 필요하다. 기존 graph-tool의 전체 시도 분포와도 계약이 다르다.
- **비교 해석:** 동일 사례의 paired 변화와 불확실성 구간을 보고하는 안을 사용한다. 반복을 독립 질문처럼 세지 않고 사건 그룹 구조를 고려해 구간 산출 방법을 test 전에 정한다. 이는 추가 보고 설계이며 현재 `compare`에 신뢰구간·통계 검정 도구가 구현되었다는 뜻이 아니다. 종합 승자나 가중 단일 점수는 만들지 않는다.
- **차단 조건과 의미 KPI:** 결정적으로 확인할 수 있는 권리 위반·유효하지 않은 인용·발행 규칙 위반은 정확도가 높아도 진행을 차단한다. 의미 품질의 숫자 임곗값은 충분한 사람 합의 표본과 별도 승인 전까지 제안이다. 거버넌스의 macro-F1 0.90·유형별 recall 0.85·false approval 0건, 로컬 p95 목표도 승인된 합격선으로 쓰지 않는다. 관측 오류 0건은 위험 0의 증명이 아니다.

### 실행 순서와 남은 승인

1. **자료 intake:** 수집한 개발용 두 자료의 manifest를 사용하고, 한국어 공시는 키·등록 이용 범위·외부 전송 권리를 확인한 뒤 수집한다.
2. **사람 gold:** 사건 그룹별 split과 실제 근거 경로를 정하고 두 사람의 독립 라벨링·합의를 마친다. 공개 annotation의 복사를 Zoop 한국어 gold 합의로 간주하지 않는다.
3. **Adapter:** 수집된 KLUE/TAT-QA의 읽기 전용 입력/gold 정규화·ID·좌표·단위 보존은 `materials-*`로 제공한다. 외부 실행 기록과 채점 계약은 별도로 구현해야 하며 material artifact를 기존 `score`에 넣지 않는다. 이 변환을 전체 benchmark 완료로 표시하지 않는다.
4. **오프라인 대조군:** B0 하네스 점검과 무모델 어휘 검색·방향/시점 고정 순회의 기록 경로를 먼저 확인한다. 이는 전체 생성형 B1/B3 품질 평가가 아니다.
5. **제한된 live 승인:** 대상 자료·전송 권리·모델/버전·endpoint·호출 수·금액 상한을 정해 실행별 승인을 받는다. 기존 설정·키 존재·과거 승인은 새 지출 승인이 아니다.
6. **동결 실행·보고:** dev 선택을 마친 뒤 승인된 test 캠페인과 계획된 반복만 실행하고, 트랙·언어·실패·비용 출처·표본 한계를 분리해 보고한다. 외부 공개는 별도 승인을 받는다.

## 그래프 도구 baseline (`zoop-ai-graph focus`, 결정적 도구 control)

**무엇을 재는가.** 비공개 version stage 도구 `zoop-ai-graph`의 `focus`·`read`·`inspect`를 호출 1회마다 실제 subprocess로 실행해 (1) 호출 전체의 단조 wall time, (2) 그 호출이 돌려준 이웃 결과의 정확성을 기록한다. 모델·embedding·provider 호출은 0이다(출력의 `usage`를 합산해 0이 아니면 점수를 내지 않는다). 이것은 B3(`fixed_graph_traversal`) 계열의 **도구 control**이다. B0–B4 시스템, RAG 답변, agent의 도구 선택, 빠른 모델의 성능과 같은 표에 올리지 않으며 순위도 매기지 않는다.

**`focus`의 실제 의미(소스 `graph_projection.focus_of`를 읽어 확인).**

- `focus`는 **무방향** 인접 리스트 위의 BFS다. 모든 node 종류(company·event·topic)와 모든 edge 종류를 같은 거리 규칙으로 센다. edge는 한 끝점의 거리가 `depth-1` 이하일 때 반환된다. 방향 edge의 `subject/object`와 `direction`은 **속성**으로 보존될 뿐 도달 가능성 계산에 쓰이지 않는다.
- BFS는 **Neo4j에서 순회하지 않는다.** 고정(freeze)된 plan(SQLite ledger에 저장)을 Python 프로세스 메모리에서 계산한다. Neo4j는 저장된 version 전체가 plan과 같은지 확인하는 데만 읽는다(전체 node·관계 수 COUNT, 외부 데이터 검사, 제한된 observe, digest 비교).
- 따라서 “1/2/3-hop”은 `depth` 1/2/3의 **이웃 집합 정확성**이며 방향 공급망 순회나 경로 추론이 아니다. depth 3이 depth 2와 같아지는 포화 case(`GT06`)가 일부러 들어 있다.
- 지연은 **호출 비용**이다: 파이썬 시작·import, ledger SQLite, S1/S2/S3 authority 재검증, Bolt 연결, 전체 version 검증, 메모리 BFS를 모두 **포함**한 값이다. 구성요소별 시간은 계측하지 않아 `null`로 남기며(합산해서 만들지 않는다) 어느 부분이 얼마나 기여하는지는 **측정하지 않았다**. command 간 차이(`inspect` = 시작+ledger만, `read`/`focus` = authority·Neo4j 검증 포함)는 구성요소 분해가 아니다. depth별 지연이 비슷하게 보이더라도 그것은 검증할 가설이지 입증된 비용 분해가 아니며, 확인하려면 구성요소 계측이 필요하다.

**세계(그래프 구성은 측정 대상이 아니다).** 합성 corpus의 authored replay다. `ai/pipeline/scripts/graph_projection_smoke.py`의 손으로 쓴 SYNTH world(기업 4, event 1, topic 1, edge 6)와 `prepare`가 추가하는 `rel-split`(서로 끊어진 두 성분)을 실제 ingestion·S2·S3 CLI로 만든 뒤 임시 Neo4j에 `init`·`freeze`·`project`한다. 측정 대상 구성요소는 CLI + 현재 authority + Neo4j read 검증 + focus이고, 추출·연결·검색은 측정하지 않는다. 기존 `gold.json`은 이 경로에서 열지 않으며 fixture 구성에도 쓰지 않는다.

**독립 gold.** `fixtures/graph-tool/queries.json`은 시스템에 보이는 dev 입력(어느 version의 어느 기업을 몇 depth로)만 담고, `expected.json`은 world의 사실(S3 proposal과 canonical 매핑)에서 손으로 계산한 정답이며 `score`만 연다. 시험은 `expected.json`을 문서화된 규칙을 독립 구현한 BFS와 대조한다(도구 출력에서 만든 값이 아니다). 같은 작성자가 world와 gold를 모두 썼으므로 단일 작성자 초안이다.

**case와 지표.** 13개 timing case(depth 1/2/3, 포화, 대칭 edge, 방향 edge의 양쪽 역할, unknown company, 끊어진 성분)와 4개 control(`read` 전체, `inspect` ledger)이 있다. 정확성은 독립된 판정으로 따로 센다: `found`, `nodeSet`, `distances`, `edgeSet`(방향 무시), `orientation`(방향 edge의 subject→object 순서), `attributes`(connection·validity·path·근거 유무), `full`. 대칭 edge의 끝점 순서는 방향 오류로 세지 않는다. 분모는 측정 시도 전체이며 실패(withheld·error·timeout·잘못된 출력)는 오답으로 센다.

**기록 규칙.** `measure`는 case마다 warm-up(기본 1, 통계 제외·전부 기록) 뒤 반복(기본 20, p95 의미 하한)을 case 간 round-robin으로 돌린다. 시도마다 `wallNs`(정수 ns, `perf_counter_ns` 차이, subprocess 생성부터 stdout 수집·종료까지)·종료 코드·outcome(`current|ledger|withheld|error|invalid_output|timeout|spawn_error`)·결과 digest를 남긴다. 기록은 계획된 slot(case별 warm-up·반복 번호, version별 실행 전·후 integrity 읽기 각 1회, 실행한 점검의 check와 recheck)과 **정확히** 일치해야 하며 빠지거나 더해지거나 번호가 바뀐 시도는 `attempt_slots_mismatch`로 거부한다(분모를 줄이거나 부풀리지 못한다). 실패·느린 시도를 통계에서 조용히 빼지 않는다: case·depth·command별로 `failureRate`와 성공 시도 분포(`successWallMs`)·전체 시도 분포(`allAttemptsWallMs`)를 함께 내고 실패 목록과 가장 느린 5개를 싣는다. 분포의 시도 수가 20 미만이면 `p95_insufficient_samples`(10 미만이면 `p50_insufficient_samples`)가 붙고, 보고서는 표에 성공 n과 전체 시도 수를 따로 싣고 “표본 주의” 절에 해당 표본 수와 caveat를 그대로 나열한다. 읽기 전용 증거는 실행 전·후 상태 fingerprint(ledger 행, 소스 상태 디렉터리, registry 파일의 digest만; 경로·자격 증명 없음)와, 실행 전·후에 각 version을 `read`한 결과의 전체 그래프 digest 동일 여부다(도구가 Neo4j 전체를 다시 검증한 값). 모델·provider 호출 관측값(`usage`)은 합산해 기록한다.

**authority·거부 점검(타이밍 아님).** `--authority-checks`는 runner가 만든 state에서만, registry 파일을 잠시 바꾼 뒤 정확한 원본 바이트로 되돌린다: grant 비활성(`source_unauthorized`), grant revision 변경(`grant_revision_changed`), canonical topic 결정 제거(`canonical_mapping_changed`)는 `withheld`여야 하고 복구 뒤 다시 `current`여야 한다. depth 4와 없는 version은 각각 `input_or_configuration_invalid`, `version_not_found` 오류여야 한다. 이 시도는 통계에 들어가지 않는다.

**명령(저장소 루트, 승인된 임시 Neo4j 필요).**

```bash
export ZOOP_GRAPH_SMOKE_URI=bolt://127.0.0.1:<port> ZOOP_GRAPH_AUTH=none   # basic이면 ZOOP_GRAPH_USER/PASSWORD
PY=ai/pipeline/.venv/bin/python
$PY ai/evaluation/scripts/graph_tool_bench.py prepare --root /tmp/zoop-gtb-root --manifest /tmp/zoop-gtb.manifest.json --environment-note "<컨테이너 제한>"
python3 -B ai/evaluation/scripts/graph_tool_bench.py measure --manifest /tmp/zoop-gtb.manifest.json --out /tmp/zoop-gtb.run.json --authority-checks
python3 -B ai/evaluation/scripts/graph_tool_bench.py score /tmp/zoop-gtb.run.json --out /tmp/zoop-gtb.score.json --markdown /tmp/zoop-gtb.report.md
$PY ai/evaluation/scripts/graph_tool_bench.py cleanup --manifest /tmp/zoop-gtb.manifest.json
```

`prepare`/`cleanup`만 `ai/pipeline`을 import한다(손으로 쓴 world 빌더 재사용; 프로젝션 smoke의 변조 단계는 호출하지 않는다). `measure`/`score`와 `zoop_eval`은 표준 라이브러리만 쓰고 `measure`는 설치된 CLI를 subprocess로만 호출한다. 기본 invoker는 같은 진입점(`zoop_ai_pipeline.graph_projection_cli`)을 소켓 audit hook으로 감싼다(loopback Neo4j 포트 외 연결·bind·다른 호스트 해석은 즉시 실패). `--invoker script`는 감싸지 않은 설치 콘솔 스크립트이며 두 invoker의 시간은 섞지 않는다. 동적 시간 결과(`run`·`score`·`report`)는 커밋하지 않는다.

**baseline 선택과 대안.** 이 도구 baseline을 먼저 고른 이유는 지금 저장소에서 실제로 실행되고 독립 정답을 쓸 수 있는 유일한 그래프 조회 경로이기 때문이다. 대안은 모두 **계획이며 구현·측정하지 않았다**: (a) 청크 벡터 top-K RAG(B2), (b) Microsoft GraphRAG 계열 Local/Global/DRIFT 검색을 참고한 구성, (c) LLM이 도구를 고르는 agent(B4), (d) Neo4j에서 직접 Cypher로 순회하는 질의 경로(현재 도구에는 없다; 임의 Cypher는 이 runner에서도 금지다). 이들은 같은 `queries.json` 형식으로 비교할 수 없으므로 별도 run 계약이 필요하다.

**공개 계약과의 차이(현재 상태의 기록이며 다른 팀의 결정이 틀렸다는 뜻이 아니다).** `docs/api/openapi.yaml` 기준, `GraphEdge.relationType` 열거(L11858 부근)는 `INVOLVES|STRUCTURALLY_RELATED_TO|FOLLOWS|SHARES_ISSUE`이고 projection의 edge type은 `SUPPLIES|INVESTS_IN|COMPETES_WITH|PARTICIPATES_IN|RELATES_TO_TOPIC`이다. `GraphNode.kind`(L11982 부근)는 `company|issue`이고 projection node는 `company|event|topic`이다. 회사 그래프의 `depth`는 `[1, 2]`(L7857 부근)이고 도구는 1..3이다. `GraphEdge.assertionStatus`(nullable string)에 대응하는 필드가 projection에는 없다. 이 차이를 메우는 전체 공개 스키마 이전은 이 작업의 범위가 아니며, 팀이 vocabulary를 정한 뒤에 다룬다.

### 그래프 도구 baseline: 시험 상태와 첫 측정(관측, 2026-10-15)

**시험 상태(Main 관측).** `ai/evaluation` 시험 158개와 CLI 점검이 통과했다. 소유권·cleanup 점검 5건의 지적은 모두 고쳤다: ① cleanup은 manifest에 적힌 **정확한 version ID 2개와 정확한 store marker만** 지운다(run id 접두사 삭제 없음), ② 환경의 Neo4j 대상이 manifest의 포트·database와 다르거나 저장된 binding과 맞지 않으면 아무것도 지우지 않고 소유 state도 남긴다, ③ registry 변조(`--authority-checks`)는 소유 marker가 같은 run인 `--root` 안의 일반 파일(심볼릭 링크 아님)일 때만 허용하고 그 전에는 파일을 열지 않는다, ④ 시도 slot은 계획과 정확히 일치해야 한다, ⑤ 보고서는 성공 표본 수와 전체 시도 수를 따로 싣고 표본 caveat를 보존한다. 실제 Neo4j 두 endpoint에서 도는 적대적 cleanup 점검(`scripts/graph_tool_cleanup_adversarial.py`)은 잘못된 대상(다른 포트·database, 같은 id가 있는 살아 있는 다른 인스턴스)에서 아무것도 지우지 않고 같은 접두사의 무관한 version이 살아남는 것까지 모두 통과했다.

**첫 측정(한 번의 실제 실행; 값은 이 환경·이 합성 world의 관측이며 일반화하지 않는다).**

- 환경: 로컬 임시 Neo4j 5.26 컨테이너(CPU 1, 메모리 1GiB, heap 256m, page cache 128m, tmpfs 데이터), 기본 audit invoker, repeats 20, warm-up 1, 모델·provider 호출 0. world는 `main`(node 6, edge 6)과 `split`(node 4, edge 2)이다.
- 기록은 총 369 시도다: 측정 340(17 case × 20), 나머지는 warm-up·integrity 읽기·authority/거부 점검이다(outcome 합계 current 322, ledger 42, withheld 3, 예상된 error 2 — **총합과 측정 340을 섞어 쓰지 않는다**). 측정 340시도는 실패 0, 완전 정답 340이다(timing case 13, control 4). 인증 변수가 빠진 첫 시도는 자격 증명 오류만 냈고 벤치마크가 아니다.
- depth별(unknown company 제외, 성공 시도 기준): depth 1 n=100 p50 277.171 ms p95 332.210 ms, depth 2 n=60 p50 280.293 ms p95 334.025 ms, depth 3 n=80 p50 278.461 ms p95 330.675 ms.
- 읽기 전용 증거와 authority 점검(17/17, 복구 확인)은 통과했고, repeats 1짜리 소유권 수정 뒤 실제 점검 실행도 17/17로 통과했다(표본이 적어 Markdown에 표본 caveat 경고가 그대로 남는다).

**해석과 한계.**

- 측정값은 **CLI 호출 전체 비용**(파이썬 시작, SQLite, authority 재검증, Bolt, 전체 version 검증, 메모리 BFS)과 **무방향 ego neighborhood**의 정확성이다. Neo4j 순회 속도, 방향 공급망 순회·경로 추론, AI/RAG/agent 답변, 모델 성능, 빠른 모델 시험이 아니다.
- depth 1/2/3의 p50이 서로 비슷한 것은 관측일 뿐이다. 구성요소별 시간을 계측하지 않았으므로 “고정 비용이 지배한다” 같은 원인 귀속은 입증하지 않았고, 확인하려면 구성요소 계측이 필요하다.
- 정확성 340/340은 같은 작성자가 쓴 합성 world·gold(기업 4곳)에서 도구가 문서화된 focus 규칙대로 동작함을 보인 것이지 일반 정확도가 아니다. 단일 머신·단일 컨테이너·한 번의 실행이라 실행 간 변동과 환경 차이는 보지 않았다.
- run·score·report 파일은 저장소에 복사하지 않았다(Main이 임시 경로에 보관). 필요하면 위 명령으로 같은 형식을 다시 만든다.

## 한국어 금융 semantic-verification 벤치마크 (오프라인, 하네스 정합성 단계)

**무엇인가.** 네이티브 Jev 검증 stage(S1 `semantic-verification`)가 후보 claim에 내린 판정을, 사람이 문서 본문만 보고 따로 쓴 gold와 결정적으로 비교한다. 두 가지를 분리해서 말한다.

- **하네스 정합성(지금 증명된 것).** 직접 쓴 한국어 합성 입력 → 실제 설치된 `zoop-ai` CLI → loopback 가짜 native 서버 → 원문 receipt → export → 엄격한 채점이 끝까지 이어지고, 변조·누락·출처 불일치·비용 불명 대 0을 거부한다는 것.
- **실제 한국어 품질(아직 0건).** 어떤 모델·Jev의 한국어 금융 판정 품질도 측정하지 않았다. loopback 서버의 답은 **저작된 script**(gold에 명시한 오답·실패를 섞은 control)이지 모델이 아니다. 따라서 이 절의 어떤 숫자도 모델 정확도로 인용하지 않는다.

```bash
cd ai/evaluation
python3 -B -m zoop_eval verify-validate                                   # cases·gold 무결성, gold 구성 요약
python3 -B -m zoop_eval verify-controls --out-dir fixtures/verification/controls   # authored control + loopback script 재생성
python3 -B -m zoop_eval verify-score fixtures/verification/controls/loopback-expected-dev.run.json --format text
python3 -B -m unittest discover -s tests -p 'test_verification.py'
# 저장소 루트, 설치된 worker 필요(make worker-install)
ai/worker/.venv/bin/python ai/worker/scripts/verification_bench.py smoke           # 실제 CLI + loopback + export + 엄격 채점 + 음성 control
ai/worker/.venv/bin/python ai/worker/scripts/verification_bench.py run --out /tmp/zoop-vk.run.json
python3 -B -m zoop_eval verify-score /tmp/zoop-vk.run.json --format text
ai/worker/.venv/bin/python -m pytest ai/worker/tests/test_verification_bench.py
```

### 구성과 경계

| 경로 | 역할 |
|---|---|
| `ai/evaluation/corpus/fin-verify-ko-v1/cases.json` | **producer가 볼 수 있는** 입력(`zoop-verify-cases-1`): 허구 기업 7곳의 한국어 문장 7개, 후보 case 28개(claim 55개, 인용 구간은 code point 오프셋). gold 키가 하나라도 있으면 거부한다(`gold_leak`) |
| `ai/evaluation/corpus/fin-verify-ko-v1/gold.json` | **숨기는** 정답(`zoop-verify-gold-1`): claim별 `supported`/`contradicted`/`insufficient`, 태그, 근거 메모, case별 `expectedGate`·`expectedAdvice`·`expectedCausality`. `inputsSha256`로 정확한 cases.json에 묶인다 |
| `ai/evaluation/zoop_eval/verification.py` | 검증·run 파싱·채점·authored control·loopback script(표준 라이브러리) |
| `ai/evaluation/fixtures/verification/controls/` | `oracle`, `degraded_all_supported`, `injected_errors`, `loopback_script_expected` run 4개와 `loopback-script.json`. 생성기와의 일치를 시험이 검사한다 |
| `ai/worker/scripts/verification_bench.py` | worker 쪽 다리: `build-jobs`, `run`, `export`, `smoke`. **producer 단계는 gold를 열지 않는다**: `cases.json`과 script만 읽고, 시험은 gold 없는 디렉터리에서도 동작함과 job 생성·가짜 서버 구성 중 `gold.json` open 시도가 0건임(audit hook)을 확인한다. smoke는 gold 없는 private 복사본으로 producer(CLI 실행·export)를 끝낸 **뒤에만** gold를 열어 채점한다 |

gold 작성: 문서 본문만 보고 한 사람이 썼고 어떤 모델 출력에서도 가져오지 않았다. `annotators=1`, `adjudicated=false`, `devOnly=true`다. 도출 숫자(예: 1,050/12,400=8.47%)는 gold 메모에 계산을 적었다. 제한(limitation) claim, 원인·예측 표현, 도출 숫자는 라벨 논쟁 여지가 있다. 구성은 gate `supported` 8·`hold` 5·`reject` 15, claim 35·10·10(supported·contradicted·insufficient)이며 부정·시점·주체 불일치, 숫자·방향 변조, 원인 과장(2), 금지된 조언·예측(3), 제한 claim(4)을 포함한다. test split은 없다.

### run 계약 (`zoop-verify-run-1`)

- 한 run은 한 corpus id·revision·`inputsSha256`·split(dev)에 묶인다. 모든 case에 기록이 **정확히 하나**여야 한다: 누락(`missing_record`), 중복(`duplicate_record`), 모르는 case(`unknown_case`)는 점수 없이 거부한다. 기록은 `caseSha256`(case 내용)과 `claimBinding`(claim id와 `claim-{i}` 질문 키)으로 정확히 묶이고 어긋나면 거부한다.
- 기록은 `ok` 또는 `error`다. `ok`는 정규화 결과(`result`: gate, claim별 decision, 두 flag), **원문 receipt**(`raw`), 호출 정보(`call`: 시도 id, 모델, endpoint revision, prompt/policy 버전, 토큰, 비용 `{usd, source}`), `latencyMs`를 낸다. 채점기는 선언된 `system.policy`로 `raw`에서 결과를 **다시 계산**해 worker가 쓴 정규화 결과와 다르면 `normalization_mismatch`, `raw`가 유효한 native 응답이 아니면 `raw_receipt_invalid`로 거부한다. `error`는 코드와 결과 확정 여부(`definite`/`unknown`)를 내고, native 검증 오류(`native_*`)는 receipt가 있고 그 receipt가 실제로 그 코드로 실패해야 한다(`error_not_reproducible`).
- 한 run은 모델·endpoint revision·prompt/policy 버전이 하나다(`mixed_versions`). 모델은 고정 버전이어야 하고 `latest`·`preview` 별칭은 거부한다(`model_not_pinned`). 토큰은 receipt의 `usage`와 같아야 하고 보고되지 않았으면 `null`이다(`usage_mismatch`).
- **비용: 불명은 0이 아니다.** `usd=null ⇔ source=unknown`. `0`은 `loopback_no_charge`(loopback control 한정, 가짜 서버가 청구하지 않았다는 뜻일 뿐 Jev 단가가 아님)로만, 실제 값은 `provider_reported`(real_measured 한정)로만 쓸 수 있다(`cost_unproven`). Jev는 비용을 보고하지 않으며 추정하지 않는다.
- **출처(provenance).** `real_measured`는 `executionMode=live`와 실제 provider endpoint, 기록 시각, raw receipt가 필요하고 `replay`는 받지 않는다(replay는 raw native receipt를 거치지 않는다). 승인 전에는 만들지 않는다. `authored_control`은 `controlKind`(`oracle`, `degraded_all_supported`, `injected_errors`, `loopback_script_expected`, `loopback_fake_native_server`)를 밝히고 `recordedAt=null`이다. 어느 쪽이든 endpoint 종류가 출처와 맞아야 한다(`provenance_invalid`). 채점 문서는 control에 `AUTHORED CONTROL … NOT a measurement` 라벨을 붙인다.

### 지표 (`zoop-verify-score-1`)

모든 비율은 `{num, den, value}`이고 분모 0이면 `value=null`이다. gold 쪽 분모(정확도, recall, 오류율)는 모든 case·claim을 포함하며 오류 case는 분자에 0을 낸다. precision은 `ok` 기록이 실제로 낸 것만 센다.

| 구역 | 내용 |
|---|---|
| `claims` | 3×3 confusion(오류 case의 claim은 `unscored`), 클래스별 precision·recall·F1, macro-F1(정의된 클래스 수 표기), `accuracy`, **`unsafeSupported`**(gold가 supported가 아닌 claim 중 `supported`로 받은 비율), 태그별(`negation`, `time`, `entity`, `numeric`, `numeric-derived`, `causal`, `advice`, `limitation`, …) 정확도·unsafeSupported |
| `gate` | gold gate 대 예측(`supported`/`hold`/`reject`/`error`) confusion. **`unsafeAccept`**(gold가 hold·reject인 case를 accept한 비율)와 **`coverage`**(`safeCasesAccepted`: gold supported 중 accept, `acceptedPrecision`)를 함께 읽는다. 모두 accept하는 control은 coverage 8/8이지만 unsafeAccept 20/20이다. `outcomes`의 accept·hold·reject·error 비율, reject/hold의 precision·recall, `heldInsteadOfRejected`(약한 모순이 hold로 내려간 것), `rejectedInsteadOfHeld`, `falseReject`, `falseHold` |
| `flags` | 금지된 조언·미근거 인과 flag의 precision·recall·오탐, 불확실 Noul 때문에 놓친 양성 수, 오류 case의 미채점 양성 수 |
| `errors` | 오류율, 코드별 개수, 결과 불명 대 확정 수. **오류는 hold도 reject도 accept도 아니다**: 모든 gold 분모에 남고 분자에 0이다 |
| `calibration` | `real_measured` live provider 기록의 유효한 원문 선택 분포에만 계산한다(Brier, log loss, ECE, 구간별 표). authored·loopback은 `not_evaluated`이며 이유를 쓴다. 합성 단일 작성자 dev gold로 임계치를 보정하지 않는다: 결과에 "임계치 보정이 아님" 주의를 항상 붙이고 임계치를 제안하지 않는다 |
| `timing`, `cost` | 기존 `timing` 모듈 재사용(wall = record 자신의 구간, 합산 안 함, 표본 부족 주의). loopback은 `loopback_fake_server_time_not_model_latency`, 비용은 known/unknown/total |

### 처음 확인한 것, 확인하지 않은 것

- Main 실행(2026-10-15): evaluation 전체 198개, worker benchmark 38개 테스트와 corpus 28건·claim 55건 검증이 통과했다. 실제 설치 CLI → loopback 합성 Jev 서버 → 영수증 export → 채점 smoke도 통과했다. 생산 단계의 gold 미열람, 채점 시 입력 digest 일치, 의도적으로 넣은 잘못된 통과·오류의 검출, 누락·중복·모델 별칭·변조·출처 위조·비용/usage 불일치 거절을 확인했다. 합성 확률에는 calibration을 계산하지 않았다. 초기 소스 문자열 검사 실패는 문자열 재고정 대신 실제 파일 접근·gold 없는 입력 디렉터리·생산 완료 후 gold 로딩으로 교체했다. 실제 모델 호출은 없으며 이 결과는 모델 정확도가 아니다.
- smoke는 case당 실제 CLI submit·run·get 서브프로세스를 쓰는 28개 job의 loopback 실행, 가짜 서버 요청 기록(case당 정확히 한 번의 `POST /systemone`, loopback key만, `TypeSafe-*` 헤더 없음), export가 script의 기대 결과(`loopback_script_expected`)와 같은 claim·gate·flag·오류 구역을 내는지, 그리고 음성 control(누락·중복·변조·출처·비용·버전·usage 불일치)의 거부를 확인한다.
- 측정하지 않은 것: 실제 모델·Jev의 한국어 판정 품질, 실제 계정의 확률 분포와 보정, 지연·비용, 임계치(0.90/0.80/0.90/0.10)의 타당성, 더 큰 corpus·test split, 두 사람 합의 gold. 임계치 결정은 이 작업의 범위가 아니다([런타임 설정 §9 4번](../development/ai-runtime-setup.md)).
- 승인 경계는 아래와 같다: 실제 Jev·모델 호출, 키 사용, 비용 지출, 한국어 실제 기사 사용은 별도 승인이다. 새 chat·RAG·유료 backend는 만들지 않았다.

### WBS 대응 (원문 행만 인용, 상태·일정을 새로 정하지 않음)

이 벤치마크는 독립 WBS 행이 없다. 가장 가까운 원문 행: **6.5.7** AI 분석 연동(FS064, P1), **6.6.18** FS079 검증 시험(원문 `6.6.15–6.6.18`은 FS076–FS079), **6.11.4–6.11.6** 통합 검증. 이슈 대응은 [`docs/share/seojin-issue-triage-2026-10-14.md`](../share/seojin-issue-triage-2026-10-14.md)의 표기(#58, #77)를 따르며 GitHub에서 다시 확인하지 않았다. 일정·담당은 바꾸지 않는다. 비기능 명세(문서·시점·인용 검증 실패를 검증된 것처럼 보이지 않는다)의 시험 방법인 "다른 시점의 문서·원문에 없는 인용"에 가장 가까운 합성 대응이 이 corpus의 시점 불일치(`VK-08`, `VK-22`)·부정(`VK-12`, `VK-15`) case이며, 실제 기사·실제 provider에 대한 검증은 아니다.

## 승인 경계와 WBS

다음은 사용자 승인 없이 하지 않는다: 실제 모델 호출·과금(공급자, 모델, 비용 상한, 데이터 전송 권리를 먼저 정함), 외부 서비스·경쟁 서비스 질의, Neo4j 등 그래프 DB 설치·기동, 새 의존성 설치, test split 사용·결과 공개, `ai-system.md`·루트 `Makefile`·CI 연결, 결과의 대외 공개. 승인 전에는 `provenance.kind=real_measured`인 run 파일을 만들지 않는다.

WBS는 변경하지 않았고 이 벤치마크는 독립 WBS 행·일정이 없다. 참고용 원문 행은 6.6.15–6.6.20(FS076–FS081, 2026-09-21–10-15), 6.11.4(윤서진, 10-12–10-27), 6.11.5(김도현, 10-12–10-27), 6.11.6(안재현, 10-19–10-23)이다. 담당·일정의 재배정은 이 작업의 범위가 아니다.

## 한계와 아직 측정하지 않는 것

- 전체 검색·채팅·RAG·agent 답변의 실행 adapter와 품질 측정은 이 하네스에 아직 연결하지 않았다. 그래프 도구와 검증 하위 단계의 control 결과를 전체 시스템 점수로 확대하지 않는다.
- gold는 단일 작성자 초안이며 합의를 거치지 않았다. 규모가 작아(split당 질문 9, 그래프 task 5, edge 13) 비율이 거칠다. 통계적 유의성 검정은 하지 않는다.
- 자유 서술 품질, 인용의 의미적 뒷받침, 사실별 인용 귀속, 사용자 체감 품질은 측정하지 않는다.
- 그래프/QA corpus는 영어 합성 문장이다. `fin-verify-ko-v1`과 `fin-summary-verify-ko-v1`은 한국어 합성 dev 자료이지만 단일 작성·미합의 자료이며 실제 기사나 모델 품질의 근거는 아니다. 특히 이슈 요약 corpus는 AI 보조 작성임을 명시한다.
- trace의 시계(단조 시계)와 span 의미는 adapter가 보장해야 한다. 하네스는 일관성만 검사하고 측정이 정확한지는 알 수 없다.
- replay 기록의 지연은 하네스 시간이며 모델·서비스 지연이 아니다.
- 이 하네스(`zoop_eval`, `score`, `measure`)는 `ai/evaluation`에서만 동작하며 BFF·S1·S2·S3 코드를 import하지 않는다. 예외는 그래프 도구 baseline의 `prepare`·`cleanup`뿐이며, 파이프라인 인터프리터에서 `ai/pipeline/scripts`의 손으로 쓴 world 빌더를 import한다.
- 그래프 도구 baseline은 합성 world 한 벌(기업 4)과 dev case 13+4개라 지연 분포는 호출 비용의 감각 이상이 아니며, 정확성은 도구가 문서화된 규칙대로 동작하는지의 확인이다. 모델·RAG·agent 품질, Neo4j 순회 성능, 방향 공급망 추론은 측정하지 않는다.

## 네이티브 이슈 요약 검증: 기록·채점 연결 (2026-10-22)

**목적과 범위.** `verify-issue-summary`가 각 주장과 세 검사 항목(advice·causality·framing)에 내린 판정을 기록하고 평가한다. 생성 모델은 호출하지 않으며 사건 추출·관계 생성·GraphDB 구성·검색·전체 RAG의 점수를 만들지 않는다. native runtime과 영수증 형식은 그대로 두고, S1의 `zoop-verify-*`와 구분되는 `zoop-summary-verify-{cases,gold,run,score}-1`을 사용한다.

### 자료와 기대 판정

`ai/evaluation/corpus/fin-summary-verify-ko-v1/cases.json`에는 전송 가능한 합성 인용문·주장만, `gold.json`에는 기대 판정·태그·근거 설명을 따로 둔다. 24개 사례·30개 주장으로 구성하며 기대 결과는 available 6개·hold 5개·reject 13개다. 주장은 supported 12개·insufficient 11개·contradicted 7개다.

이는 AI 보조 단일 작성자의 dev 자료이며 사람의 독립 라벨링·합의를 거치지 않았다. 별도 AI 문서 검토로 일관성을 점검한 사실을 사람의 검수나 실제 모델 평가로 표시하지 않는다. 임곗값 학습·보정용 정답으로 확정한 자료도 아니다.

미인용 구절이 있어도 유효한 입력이다. NS10·NS23은 그 구절에 필요한 사실이나 현재 보도가 있지만 해당 주장이 인용하지 않는 사례다. native 요청의 `state.quotes`에서는 미인용 구절이 빠져야 한다. 주장 자체가 그 구절과 같은 문장일 수 있으므로 전체 요청 문자열 검색이 아니라 구조로 검사한다. 다른 주장이 인용한 구절을 빌려 판단하는 오류도 별도 사례로 구분한다.

### 기록과 재검증

생산자 `ai/pipeline/scripts/summary_verify_bench.py`는 실제 `LiveRuntime`의 ISSUE_SUMMARY family를 사용한다. `prepare` → 전송 의도 기록 → `send` → 원문 receipt 저장 → `answer` 순서이며 사례당 한 번만 요청하고 자동 재시도하지 않는다. producer·assemble은 gold를 열지 않는다. 실제 loopback smoke도 생산 과정이 끝난 뒤에만 gold를 읽어 채점한다.

새 run 디렉터리와 파일은 비공개 권한으로 만들고, 파일 쓰기는 같은 디렉터리의 staging 파일을 fsync한 뒤 덮어쓰지 않는 원자적 게시로 완료한다. 중단된 staging 파일은 완성된 기록으로 읽지 않는다. 의도만 있고 결과가 없으면 `bench_outcome_unrecorded/unknown`, 뒤의 미시도 사례는 `bench_not_attempted/definite`로 남긴다. receipt가 온전히 저장됐다면 결과 기록이 없어도 키·전송 없이 다시 해석할 수 있다. 완성된 이름으로 게시됐는데 손상된 기록은 복구를 가장해 무시하지 않고 거절한다.

채점기 `summary_verification.py`는 pipeline을 import하지 않는 표준 라이브러리 구현이다. 보이는 입력으로 요청·인용 범위·질문을 다시 만들고 공개 adapter preimage·binding·원문 응답·usage·비용·정규화 판정을 대조한다. 누락·중복·변조·출처 위조가 있으면 부분 점수 없이 거절한다. 모든 body hash를 확인하므로 원래 잘못된 UTF-8 바이트가 capture에서 대체 문자로 바뀌어 복원되지 않는 기록은 `receipt_body_mismatch`로 채점할 수 없다. 해시는 내부 정합성 검사이지 실행이나 공급자 출처의 암호학적 인증은 아니다.

### 지표 해석

| 구역 | 의미와 분모 |
|---|---|
| 주장 | 세 판정의 confusion·정확도·precision/recall/F1·macro-F1, 근거가 부족하거나 모순인 주장을 supported로 통과시킨 비율. 오류 사례의 주장도 gold 쪽 분모에 남긴다. |
| 세 검사 | advice·causality·framing의 present/absent/uncertain/unscored 구분, present의 precision·recall, 오탐·불확실·미채점 수. |
| 검증 결과 | available/hold/reject/error의 정확도와 confusion, `unsafeAvailable`, 클래스별 recall. `availableCoverage`는 전체 사례 중 available 비율이며 안전한 사례만의 recall과 다르다. `availablePrecision`은 available 중 기대 결과도 available인 비율이다. |
| 오류 | 오류 코드·단계별 개수와 definite/unknown 구분. 통신·형식 오류를 hold/reject 또는 빈 성공으로 바꾸지 않는다. |
| 지연 | `perf_counter_ns`로 측정한 `send()` 구간이다. 예산 예약·전송 직전 확인·네트워크·정산을 포함하며 모델 추론 시간은 아니다. 오류 지연도 별도로 보존한다. |
| 비용 | 보수적 runtime 추정액, receipt로 확인한 예산 반영액, 결과 미상의 최대 예약 위험액, 실제 청구액을 분리한다. 실제 provider 청구는 `unknown/null`, 소유한 loopback 모의 서버만 `loopback_no_charge=0`이다. |

`authorizedOffsetNs`는 전송 직전 callback이 실행됐다는 뜻이지 provider 수신 증거가 아니다. HTTP 응답이 저장된 경우와 전송 결과 미상을 구분한다. 날짜 문자열의 차이로 지연을 만들지 않는다. 금액 추정은 청구서가 아니며 unknown을 0으로 채우지 않는다.

순위·우승 모델·합격 기준·calibration은 산출하지 않는다. `comparisonKey`는 corpus/gold·stage·adapter·정책·모델·실행 종류의 비교 조건을 식별할 뿐이다. 단일 합성 실행의 시간으로 모델이나 전체 서비스의 속도를 비교하지 않는다.

### 재현과 관측 증거

실행 명령과 파일 형식은 [evaluation README](../../ai/evaluation/README.md)의 네이티브 이슈 요약 검증 절과 [pipeline README](../../ai/pipeline/README.md)의 recorder 절을 따른다.

```sh
ai/pipeline/.venv/bin/python ai/pipeline/scripts/summary_verify_bench.py smoke
```

2026-10-22 로컬 검증에서 정상·의도적 오류 대조군 각각 24개 사례가 실제 native runtime과 loopback HTTP를 통과했다. 제어 요청 48회와 중단 시험 요청 3회가 관측됐고 외부 provider·모델 호출은 0이었다. 의도적 오류 대조군은 주장 22/30·검증 결과 14/24 일치, 오류 5건(결과 미상 1건)을 재현했다. 이는 넣어 둔 오답·실패를 도구가 제대로 검출했다는 증거이지 Jev의 정확도가 아니다.

전송 의도·receipt·결과 파일의 게시 전 중단을 포함한 5개 중단 경계, 변조 28종, live 실행 선행 조건 거부 7종을 확인했다. 영수증 쓰기를 중단하면 복구가 막히던 문제를 실패 3건으로 재현한 뒤 원자적 게시로 수정했다. usage 상한·오류 우선순위와 과대 지연 정수의 구조화된 거부도 회귀로 확인했다. evaluation 전체 213개, recorder 13개, pipeline 전체 1,982개가 통과했고 기존 S1 verification loopback 경로도 통과했다.

### 실제 모델 실험 전 조건

Live 경로는 구현했지만 이번 작업에서 실행하지 않았다. 실행마다 대상·자료·모델·호출 수·금액 상한의 별도 승인이 필요하다. CLI도 명시적인 live 모드, 저장소에 고정된 합성 corpus의 digest 확인, 기존 live gate·모델 설정, 새 예산 디렉터리와 지정된 provider endpoint를 요구한다. `.env`는 읽지 않으며 `--check`는 파일·전송 없이 설정과 키 존재 여부만 확인한다. 설정이나 `--check` 통과가 지출 승인은 아니다.

실제 기사·외부 서비스·경쟁 모델·test split·임곗값 보정·외부 결과 공개는 이 작업에 포함되지 않았다. 새 CI job·의존성·자격증명·서비스 배포를 추가하지 않았고 WBS 담당·일정·진척률도 변경하지 않았다.
