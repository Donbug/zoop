# 지정 출퇴근 회차의 순차 로컬 재생

`briefing_round_series.py`의 명시 입력으로 1~14개 연속 회차를 선택한다. 기본 과거 14회차 및 실제 수집 단일 회차 경로는 유지한다. 모든 회차는 KST 09:20/17:30이며 첫 회차의 시작부터 마지막 마감까지 빈틈·겹침·미래 시각을 거절한다. 지금 수집한 본문을 과거에 수집한 것처럼 바꾸지 않는다.

1. 실제 원문 응답과 publisher 발행 시각을 확보하고 sources/clocks/HTML SHA를 고정한다. 검색 날짜만으로 시각을 확정하지 않는다.
2. `briefing_issue_pipeline.py --round-series <series.json>`으로 기존 PoC 추출·근거검증·사건 묶음을 재사용한다. PoC 원본은 수정하지 않는다.
3. `briefing_grouped_run.py --round-series ... --publication-catalog ...`로 각 회차에 새로 나온 근거를 평가하고 최대3개를 선정·작성·검증한다. 이전 결과의 정확한 해시와 실제 신규 근거만 연결한다. 등록 기업 카탈로그와 원문을 임의로 변경하지 않는다.
4. `briefing_market_enrichment.py --round-series ... --include-market-context --prompt-version market-context-v3-grounded`로 전체 적격 기업 자료·이전 검증 요약·회차 지표를 묶는다. 지표 요청 구간도 이번 날짜에 맞춘다. 오전에 당일 종가를 넣지 않으며 은행 일별 고시값은 실시간 환율과 구분한다. 공식 세션 달력·관측이 없으면 적중 평가를 만들지 않는다.
5. `briefing_series_company.py --prompt-version company-outlook-v4 --execute`로 동일 기업의 이전 판단과 회차 이전 근거를 연결한다. 새 기업별 구체성 프롬프트와 별도 검증을 사용하고 원문 밖 인과·가격을 만들지 않는다. CLI는 완료 후 시세 수집까지 자동 연결하며 `finalBundle`로 가격 포함 결과를 반환한다. 원 AI 출력 폴더는 그대로 두고 인접한 `<output>-flow/prices/`에 기록한다. 기존 회사 전망만 생성하는 경로는 `--without-prices`로 명시한다. 회사별 전망이 실패해도 검증된 원래 뉴스·지표를 지우지 않는다.
6. 선택적으로 `briefing_company_reading.py`로 기업별 짧은 읽기를 별도 생성·검증한다. 완료 결과가 있다면 재사용하고, 전문을 잘라 짧은 요약으로 위장하지 않는다.
7. `briefing_series_prices.py --baseline <완료 폴더> --output <새 폴더> --authorization-ref <기존 참조>`로 해당 회차의 기업 시세를 연결한다. 첫 마감 7일 전~마지막 마감 다음 UTC 날의 원본을 보존하며 AI 호출은 없다. [가격·관측/비교 기준](BRIEFING_SHORT_READING_AND_PRICES.md#완료된-연속-회차에-시세만-추가하기)을 따른다.
8. 새 빈 로컬 replay DB에 최종 bundle을 import한 뒤 저장 근거에서 재구성 지도를 등록한다. 기존 DB·발행 결과·공개 graph 활성화는 변경하지 않는다.

`series.json`은 `schemaVersion=zoop-briefing-round-series-v1`, `sourceFileSha256`, `retrospectiveBodies=true`, `productionAuthorized=false`, 시간순 `rounds[{date,edition,window:{from,to,openStart:false}}]`를 포함한다. 전체 명세·SHA가 각 모델 입력에 결속되고 Java도 저장 전 독립 검증한다.

완료 요청은 원문 응답·모델 requestDigest·사용량을 재사용한다. 미응답 요청은 자동 재전송하지 않는다. 기존 기사·지표·AI 모델 요청은 실행기별 최대치와 별도로 작업 전체 예산에서도 합산해야 한다. 단계별 출력은 별도 폴더에 보존하고 실패 초안을 통과본으로 바꾸지 않는다.

화면 확인은 D-BRF-01/02의 날짜·출퇴근 선택, 회사별 전망·시장 요약·3지표·근거와 회차 지도다. 과거 자료의 당시 본문 동일성/실제 예측 성과·운영 공개 승인을 입증하지 않는다.

## 완료 AI 결과부터 시세·DB·지도·화면까지 자동 연결

`briefing_round_flow.py`는 완료된 명시 연속 회차에 대해 `완료 결과 확인 → 회차 시세 → DB import → 재구성 지도 등록 → API → 회차/근거 HTTP 검증 → 선택적 화면 실행`을 순서대로 수행한다. AI 생성·선정기를 다시 부르지 않는다. 새 수집·AI 단계는 앞의 실행기에서 완료해야 하며, 운영 scheduler/AWS 자동화는 이 명령에 포함되지 않는다.

```sh
python3 scripts/briefing_round_flow.py \
  --baseline /absolute/private/completed-ai-series \
  --output /absolute/private/new-round-flow \
  --sources /absolute/private/sources.jsonl \
  --clocks /absolute/private/clocks.json \
  --jar /absolute/api/build/libs/zoop-api.jar \
  --java-home /absolute/jdk-21 \
  --authorization-ref '<기존 승인 참조>' \
  --database zoop_briefing_replay_local_example --pg-port 55496 \
  --max-calls 94 --continuity --core-semantic \
  --api-port 18132 --web-port 13136 \
  --node-modules /absolute/installed/web/node_modules \
  --execute --serve --keep-alive
```

- `--execute`가 없으면 입력 파일·키·네트워크에 접근하지 않고 단계만 표시한다. 실행에는 Python `psycopg`, JDK 21, 로컬 PostgreSQL과 기존 설치된 웹 의존성이 필요하다. `--max-calls`는 기존 전체 호출 기록을 검증하는 누적 상한이며 이번 명령의 새 AI 호출은 0회다.
- baseline은 기업 전망/선택적 짧은 읽기가 완료되고 아직 `seriesCompanyPrices`가 없는 원본이다. 기존 가격 보완 완료 폴더가 **동일 baseline**에 결속돼 있다면 `--price-cache /absolute/completed-price-archive`로 원본 응답까지 재사용한다.
- 실패 후 **같은 인자로 같은 output**을 다시 실행한다. `stages/<단계>/0001.started.json`, `0001.result.json`에 시작·완료/실패를 추가 기록한다. 완료 단계는 해시·원시 가격·DB 저장본·지도·현재 HTTP 응답을 재검증하고 건너뛴다. 실패한 단계부터 이어지며 실행 결과의 `executedStages`/`reusedStages`로 구분한다.
- 가격 요청은 종목별 5분/일별로 나눈다. 한쪽이 성공하고 다른 쪽이 실패하면 다음 실행은 성공 응답을 복사해 재사용하고 실패 요청만 다시 수행한다. 네트워크 실패/HTTP 오류 영수증은 이전 `prices/0001`에 남고 새 시도는 `0002`로 저장한다. 정상 HTTP의 빈 이력은 재시도 대상이 아니다. 한 실행 안에서 무제한 자동 재시도하지 않는다.
- 원본·승인 참조·소스/clock/JAR·DB·옵션이 달라지면 기존 output의 완료 기록을 재활용하지 않는다. 새 output·별도 DB로 실행한다. 변경된 완료 기록이나 DB를 자동 덮어쓰기하지 않는다.
- 전용 `zoop_briefing_replay_local_*` DB만 허용한다. 동일 실행의 중복 실행은 커널 잠금으로 거절한다. API/화면 PID를 먼저 기록하므로 중단 뒤 해당 프로세스가 살아 있으면 재사용한다. 이미 다른 프로세스가 점유한 포트는 종료하지 않고 실패로 남긴다.
