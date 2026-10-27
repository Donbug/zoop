# 실제 가격을 읽는 기업 전망 프롬프트 v5

상태: 오프라인 준비기와 별도 opt-in v5 실행·저장·조회 경로가 있다. 기존 v4/발행본과 기본 실행 경로는 보존한다. `briefing_price_outlook_execute.run`은 외부 한도/자격증명 transport를 주입받으며 자동 실행하지 않는다.

`src/main/resources/briefing/prompts/company-outlook-v5/{generation,verification}.md`는 원 사업 근거와 실제 가격·등락을 함께 읽도록 지시한다. 전망 본문에는 사업 판단·관측 가격·기사 시각의 해석 범위·다음 확인 조건을 연결한다. 상승/하락만으로 사업 등급·뉴스 인과·예측 적중을 결론 내리지 않는다. 가격이 없어도 사업 전망을 유지하며 누락 범위만 밝힌다.

출근은 전날 퇴근 판단을 새 사업 사실과 현재 관측으로 갱신하고, 퇴근은 아침 판단의 사업 근거와 실제 가격을 분리해 비교한다. 새 미국 정규장 없음, 동일 시각 공급자 수정, 기사 후 완료 봉 없음, 공개 직전 구간 부재를 각각 구분한다. 시장 참고 지표는 정확한 두 비교일·지연/고시값 의미를 보존한다. 국내 지수를 해외기업의 직접 비교지수로 쓰지 않는다.

## 오프라인 입력 확인

```sh
python3 scripts/briefing_price_aware_prompt.py \
  --responses <검증된 editionReview/companyPriceContext 회차 응답 폴더> \
  --output <새 비공개 준비 폴더>
```

이 명령에는 키나 실행 옵션이 없다. 기존 공개 API 응답의 사업 원문·이전 판단과 회차 가격을 읽어 생성 요청 JSON만 준비한다. 응답별 SHA, 입력 SHA, 프롬프트 SHA를 기록하고 같은 출력 폴더의 기존 파일은 덮어쓰지 않는다. `observedMovement`에 실제 숫자·시간·완료 봉 상태를 넣되, 앞서 규칙으로 합성한 outlook/interpretation/observation 문장은 제외한다.

- `sources`: 원문·공시·기사의 근거. 해당 기업 sourceIds와 마감 전 발행 시각을 검사한다.
- `targets[].observedMovement`: 기업별 회차 가격·기준일·일봉/완료 봉·기사 전후/출근 이후 관측·원본 응답 SHA.
- `targets[].previous`: 실제 직전 편집 판단. `preserved_editorial_review`를 새 AI 생성 결과로 바꾸어 부르지 않는다.
- `marketReference`: 지수·환율의 정확한 관측일·비교일과 출처. 뉴스와 가격의 원인 관계를 입증하지 않는다.

요청은 기존 `gpt-6-luna`·`store=false`·strict JSON Schema 포맷을 유지한다. 구조화된 출력 방식은 [OpenAI 공식 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)를 따른다. 준비기는 실제 초안이 없으므로 검증 요청을 만들지 않는다. 실행기는 새 초안을 받은 후 별도 검증 요청을 만든다. 원생성/검증 프롬프트를 함께 보존한다.

## opt-in 실행·저장·조회

`python scripts/briefing_price_aware_prompt.py`는 계속 준비만 수행한다. 실제 실행은 `scripts/briefing_price_outlook_execute.py`의 `run(prepared, output, transport, maximum_calls=16)`을 호출한다. transport는 승인된 호출 수·비용 한도를 적용한 뒤 키를 사용해야 한다. 실행기의 16회 제한은 다른 실행의 누적 사용량을 대신하지 않으므로 외부 예산 원장이 필수다. 완료 응답은 재사용하고 미응답 예약을 자동 재전송하지 않는다.

출근에는 전날 퇴근, 퇴근에는 같은 날 출근의 동일 기업 PASS 결과만 `verified_ai_price_outlook`으로 넘긴다. 앞 회차가 보류됐으면 그 문안을 이전 판단으로 사용하지 않는다. 신규 회차 결과와 실패·보완 시도, raw 요청/응답, 사용량을 새 폴더에 보존한다.

Replay bundle의 선택적 `presentationEnrichment.aiPriceOutlookLayer`는 4회차 `rounds`, 호출 `receipts`, 선택적 `amendments`를 담는다. importer가 원문/실가격/이전 결과/실제 요청·응답 바이트/모델/프롬프트/독립 검증을 대조한 후 새 DB의 `public_snapshot.aiPriceOutlooks` 및 사용량 artifact에 저장한다. 기존 테이블/발행본은 수정하지 않는다.

후속 보완은 원 frozen 입력을 유지한 별도 판본으로 보존할 수 있다. 기존 round/실패 영수증을 대체하거나 소급 수정하지 않는다. 후속 회차 비교는 실제 생성 당시의 이전 AI 판본을 유지하며 `historyNote`로 이를 표시한다. 후속 회차까지 새 보완판으로 다시 비교하려면 별도의 재생성과 검증이 필요하다.

API `aiPriceOutlooks`는 선택 필드다. PASS일 때 새 AI 전망·사업 의미·비교·조건·위험을 사용한다. WITHHELD/필드 부재/버전 불일치이면 새 초안은 노출하지 않고 기존 검토본·시세·근거를 제공한다. D-BRF-01/02의 짧은 제목과 요약은 기존 검증본을 유지하며, 새 v5 전망은 기업 카드의 자세히에 표시한다. 전체 시장 장중/업종/수급 수집 및 운영 스케줄러 연결은 이 경로의 범위가 아니다.

4회차는 최소 8회, 각 회차 한 번 보완 시 최대 16회이다. 이 수치는 기본 실행 계획이며 호출 승인이나 실제 사용량은 아니다. 호출/비용 한도는 사용자 승인과 외부 원장으로 확인한다.
