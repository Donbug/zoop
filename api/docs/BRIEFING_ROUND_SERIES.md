# 지정 출퇴근 회차의 순차 로컬 재생

`briefing_round_series.py`의 명시 입력으로 1~14개 연속 회차를 선택한다. 기본 과거 14회차 및 실제 수집 단일 회차 경로는 유지한다. 모든 회차는 KST 09:20/17:30이며 첫 회차의 시작부터 마지막 마감까지 빈틈·겹침·미래 시각을 거절한다. 지금 수집한 본문을 과거에 수집한 것처럼 바꾸지 않는다.

1. 실제 원문 응답과 publisher 발행 시각을 확보하고 sources/clocks/HTML SHA를 고정한다. 검색 날짜만으로 시각을 확정하지 않는다.
2. `briefing_issue_pipeline.py --round-series <series.json>`으로 기존 PoC 추출·근거검증·사건 묶음을 재사용한다. PoC 원본은 수정하지 않는다.
3. `briefing_grouped_run.py --round-series ... --publication-catalog ...`로 각 회차에 새로 나온 근거를 평가하고 최대3개를 선정·작성·검증한다. 이전 결과의 정확한 해시와 실제 신규 근거만 연결한다. 등록 기업 카탈로그와 원문을 임의로 변경하지 않는다.
4. `briefing_market_enrichment.py --round-series ... --include-market-context --prompt-version market-context-v3-grounded`로 전체 적격 기업 자료·이전 검증 요약·회차 지표를 묶는다. 지표 요청 구간도 이번 날짜에 맞춘다. 오전에 당일 종가를 넣지 않으며 은행 일별 고시값은 실시간 환율과 구분한다. 공식 세션 달력·관측이 없으면 적중 평가를 만들지 않는다.
5. `briefing_series_company.py --execute`로 동일 기업의 이전 판단과 회차 이전 근거를 연결한다. 기존 기업 전망 프롬프트와 별도 검증을 사용하고 원문 밖 인과·가격을 만들지 않는다. 회사별 전망이 실패해도 검증된 원래 뉴스·지표를 지우지 않는다.
6. 선택적으로 `briefing_company_reading.py`로 기업별 짧은 읽기를 별도 생성·검증한다. 완료 결과가 있다면 재사용하고, 전문을 잘라 짧은 요약으로 위장하지 않는다.
7. `briefing_series_prices.py --baseline <완료 폴더> --output <새 폴더> --authorization-ref <기존 참조>`로 해당 회차의 기업 시세를 연결한다. 첫 마감 7일 전~마지막 마감 다음 UTC 날의 원본을 보존하며 AI 호출은 없다. [가격·관측/비교 기준](BRIEFING_SHORT_READING_AND_PRICES.md#완료된-연속-회차에-시세만-추가하기)을 따른다.
8. 새 빈 로컬 replay DB에 최종 bundle을 import한 뒤 저장 근거에서 재구성 지도를 등록한다. 기존 DB·발행 결과·공개 graph 활성화는 변경하지 않는다.

`series.json`은 `schemaVersion=zoop-briefing-round-series-v1`, `sourceFileSha256`, `retrospectiveBodies=true`, `productionAuthorized=false`, 시간순 `rounds[{date,edition,window:{from,to,openStart:false}}]`를 포함한다. 전체 명세·SHA가 각 모델 입력에 결속되고 Java도 저장 전 독립 검증한다.

완료 요청은 원문 응답·모델 requestDigest·사용량을 재사용한다. 미응답 요청은 자동 재전송하지 않는다. 기존 기사·지표·AI 모델 요청은 실행기별 최대치와 별도로 작업 전체 예산에서도 합산해야 한다. 단계별 출력은 별도 폴더에 보존하고 실패 초안을 통과본으로 바꾸지 않는다.

화면 확인은 D-BRF-01/02의 날짜·출퇴근 선택, 회사별 전망·시장 요약·3지표·근거와 회차 지도다. 과거 자료의 당시 본문 동일성/실제 예측 성과·운영 공개 승인을 입증하지 않는다.
