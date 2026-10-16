# 발행시각 기준 회차별 과거 시뮬레이션

`scripts/briefing_round_simulation.py`는 2026-10-02~08 자료를 **각 회차의 확인된 publisher 발행시각 창으로 먼저 나눈 뒤**, 회차마다 중요도 평가·최대 세 이슈 선정·해당 형식 작성·별도 검증을 수행한다. 주간 전체 점수나 주간 세 이슈를 출근·퇴근에 재사용하지 않는다. 기존 주간 실행기의 실제 호출 차단도 유지한다.

모드는 `publication_clock_simulation`이다. 당시 수집본이 없으므로 현재 publisher 페이지에서 관찰한 발행 선언과 이후 확보한 본문을 사용한다. 이것은 당시 본문 불변성·당시 수집 완료를 증명하지 않는다. 실제 수집 시각과 원본 `allowModelSend`·권리 상태는 보존하고 `retrospectiveBodies=true`, `operationalCollectionGate=false`로 표시한다. 정상 운영 발행·운영 권한 승인이 아니다.

## 회차 입력

10월 2~8일의 매일 출근 09:20·퇴근 17:30 KST, 총 14회차를 시간순으로 처리한다. 회차 창은 **왼쪽 제외·오른쪽 포함 `(from,to]`** 이다.

| 구분 | 시작 제외 | 끝 포함 |
|---|---|---|
| 출근 | 전날 17:30 | 당일 09:20 |
| 퇴근 | 당일 09:20 | 당일 17:30 |

첫 창의 시작은 10월 1일 17:30으로 명시한다. 이것은 `simulation_baseline_not_service_first_round`이며 서비스 최초 회차의 하한 없음과 다르다. 동일 본문 중복 제거는 시간 창 분할 **이후**에 한다. 다른 창의 동일 본문 때문에 해당 창의 문서를 없애지 않는다.

입력은 원본 JSONL, `zoop-publication-clock-registry-v1` registry, 같은 폴더의 `html/<htmlSha256>.html`이다. 시작할 때 다음을 확인한다.

- JSONL 및 registry 원본 바이트의 SHA-256.
- 개별 clock의 sourceFileSha256·documentId·bodySha256·원 URL 일치.
- `status=verified_timestamp`, HTTP 200, timezone이 있는 publishedAt 및 실제 checkedAt.
- 저장된 원 HTML 또는 bounded prefix의 SHA-256. prefix 관찰도 당시 본문 증명이 아니다.

date-only·공급자 추정·충돌·접속 실패·미관찰 시각은 정확한 회차 시각으로 사용하지 않는다. 이런 문서는 전기간의 미확인 coverage로 남긴다. 후보가 0개이거나 AI가 실질 이슈를 선정하지 못했을 때 미확인 source가 하나라도 있으면 `HELD_SOURCE_COVERAGE`다. 근거 부족을 정상 빈 회차로 위장하지 않는다. 입력이 입증된 시뮬레이션 빈 결과와 실제 서비스의 빈 회차 발행도 구분한다.

## 회차별 AI 처리와 이전 출력

각 회차의 전체 입력을 기본 30건씩 최대 3개 병렬로 평가한다. 다른 회차 문서를 한 요청에 섞지 않는다. 문서 ID별 필수 object schema로 누락·발명·중복을 차단하고 코드에서도 집합을 확인한다. 중요도 3이 2보다 먼저이며, 같은 중요도 안에서 priority를 비교한다. 광범위 영향·공통 정책은 원문 근거가 있어야 하고 canonical ID·독립 출처 수·novelty를 만들지 않는다.

최종 원문 재검토 대상은 중요도 2 이상인 `ELIGIBLE`과 전체 본문이 확보된 `HOLD`를 함께 importance 우선으로 비교한 최대 12개다. 발췌문에 핵심 조건이 없어 HOLD된 후보도 전체 본문을 검토할 기회를 갖는다. HOLD는 선정 승인이 아니며 전체 본문에서 부족한 근거가 해소된 경우만 최종 이슈로 선택한다. 원문 자체 부족·정확한 시각 부재·권한 문제를 이 경로로 우회하지 않는다. 본문에도 근거가 없으면 선정하지 않으며 미확인 source가 있는 0건은 계속 `HELD_SOURCE_COVERAGE`다.

시간 의미 검증은 해당 회차의 확인된 publisher timestamp와 문장 속 사건일·계획 상태·조건을 대조한다. 늦게 수집한 본문과 당시 본문 동일성 미입증은 이 시뮬레이션의 고정된 한계이며, 그 사실만으로 문장의 시간 적합성을 실패시키지는 않는다. 이 한계는 metadata/UI에 표시하고 뉴스 claim에 인용된 사실처럼 끼워 넣지 않는다. 창 밖 미래 자료·사건일 왜곡·당시 운영 가용성 통과 주장은 계속 실패하며 원문·수치·인용 검증도 그대로 유지한다.

해당 회차의 원문에서 최대 세 이슈를 최종 선정하고 정확한 인용·Unicode offset·문서 버전을 고정한다. 출근 또는 퇴근 중 해당 형식만 작성한다. 모든 제목과 2~3개 문장을 별도 모델 호출로 검증하여 전부 `SUPPORTED` 및 상태·시간·숫자·투자 권유 검사를 통과해야 `PASS`다. 모델이 근거 부족을 `claims=[]`로 표시하면 생성 문장을 채우거나 검증 통과시키지 않고 `HELD_VALIDATION`으로 남긴다. 내용 보완은 같은 자료에서 최대 한 번이다.

`previous`는 바로 직전 회차의 **동일 시뮬레이션 PASS 결과**만 가리키며 `type=simulated_previous_output`, roundId·resultSha256을 연결한다. 직전 회차가 HELD·EMPTY이거나 첫 회차이면 unavailable이다. 더 오래된 성공본·임의 과거 전망으로 대체하지 않는다. 이전 AI 문장은 사실 근거나 실제 전망 적중의 증거가 아니다.

실제 시장 지표·주가·전망 평가 자료가 없어 시장 요약·시장 지표·출근 대비 가격/전망 비교는 unavailable이다. 오늘·내일·장마감·새 시장 방향을 생성하지 않는다. graphVersion은 null이며 가짜 그래프 버전을 만들지 않는다.

## 실행과 예산

기본은 publisher 증거·창 분할·중복·coverage·호출 계획만 확인하는 오프라인 감사다. 키를 읽거나 모델을 호출하지 않는다.

```sh
python3 scripts/briefing_round_simulation.py \
  --sources /absolute/private/source.jsonl \
  --clocks /absolute/private/clock/registry.json \
  --output /absolute/private/per-round-run \
  --user-inbox-ref inbox/publication-clock-simulation-approval.md \
  --max-calls 100
```

해당 시뮬레이션 전송 승인이 확보된 operator만 `--key-file /absolute/private/openai.env --execute-authorized-simulation`을 추가한다. 키는 0600, 출력 디렉터리는 0700이며 키·원문·원응답·번들은 공개 코드에 넣지 않는다. `--clock-html-root`로 HTML 폴더를 별도 지정할 수 있다.

batch 30으로 현재 고정 자료를 감사한 계획은 확인 시각 547건 중 14창에 492건, 창 안 본문 중복 3건을 제외한 489건이다. 미확인 source는 334건이다. 모든 비어 있지 않은 회차에서 이슈를 선정하면 평가 24 + 선정 14 + 작성·검증 28 = **66호출**, 모든 회차를 한 번씩 내용 보완하면 최대 **94호출**이다. 실제 선정/보류에 따라 줄어들 수 있다. `--max-calls`는 전체 실행의 실제 reservation 상한이며 기본 100이다. 기본 계획이 명시 예산을 넘으면 키·transport 생성 전에 중단한다.

## 고정 기록·번들 v2

새 프롬프트 9개는 `api/src/main/resources/briefing/prompts/round-simulation/`에 있다. `run-identity.json`에는 `shortlistPolicy=eligible_or_full_body_hold_importance_gte2_v2`를 명시하므로 ELIGIBLE만 검토했던 이전 실행과 캐시를 섞지 않는다. 원본 SHA·clock SHA·각 창·입력 문서 버전 집합·프롬프트/스키마 SHA·승인·직전 PASS hash를 round identity로 고정하고 **모든 실제 요청**에 identity와 그 SHA를 넣는다. 기존 주간 출력·프롬프트·request cache를 공유하지 않는다.

회차마다 private `identity.json`, `frozen-input.json`, 중요도·선정·생성 결과·round.json·바인딩을 저장한다. 완료된 request는 실제 request/response digest와 토큰 영수증을 확인하여 재사용하고, pending·실패·사용량 불명은 자동 재호출하지 않는다. 부분 round 기록을 복구할 때도 기존 실제 request context에서 영수증을 찾아 사용량을 누락하지 않는다.

최종 `bundle-v2.json`의 schemaVersion은 `zoop-briefing-round-simulation-v2`다.

| 필드 | 의미 |
|---|---|
| sourceFileSha256·clockFileSha256 | 원문과 publisher 증거 registry 고정 |
| rounds[].window·inputSources·clockRefs | 창별 전체 AI 입력 문서/본문 버전과 확인 시각 증거 |
| identity·identitySha256 | 실제 요청에 포함한 고정 문맥 |
| selectionStatus | SELECTED / HELD_SOURCE_COVERAGE / EMPTY_CONFIRMED / HELD_VALIDATION |
| selected·result | 실제 선정 이슈와 PASS 생성/검증 결과. 보류된 본문은 발행 결과로 넣지 않음 |
| previous·resultSha256 | 바로 직전 동일 시뮬레이션 PASS 연결 |
| result.usage | generationRequestDigest·verificationRequestDigest에 해당하는 최종 성공 두 호출 |
| round.receipts·top receipts | 중요도·선정·생성·검증·보완을 포함하는 전체 실제 사용량 원형 |

SHA는 UTF-8, 정렬된 JSON object key, 공백 없는 구분자, Unicode 원문 유지, 비유한수 금지로 계산한다. candidateInputSha256은 inputSources 배열, clockRecordSha256은 registry의 개별 원 record, resultSha256은 최종 result의 SHA다. DB importer는 시각 창·원 HTML hash·본문 인용·9개 실제 리소스 hash·직전 PASS 연결을 별도로 검증한다. 이 실행기는 직접 운영 DB 발행이나 배포를 하지 않는다.

오프라인 합성 시험:

```sh
python3 -m unittest discover -s scripts/tests -p test_briefing_round_simulation.py -v
```
