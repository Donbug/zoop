# 기업·업종 맥락과 이전 브리핑을 사용하는 시장 분석

이 문서는 opt-in `market_context_prior_briefing_v2` 구현을 설명한다. 공개 API 필드와 ERD/migration은 바꾸지 않는다. 기존 `market-summary` 프롬프트와 이미 저장한 발행본은 유지하고, 새 결과는 별도 출력 디렉터리와 replay DB로 가져온다. 이 어댑터는 **원발행 시각 기준 과거 시뮬레이션**이다. 당시 실제 수집·권한·발행이 있었다는 증거가 아니다.

## 입력 범위

- 화면 핵심 이슈는 기존 선정 결과 최대 3개다. 시장 분석 입력은 이에 한정하지 않는다.
- 원문 SHA와 발행시각 검증 기록이 있는 모든 자료 중 `publishedAt <= cutoff`를 사용한다. `(window.from, cutoff]`는 `new`, 그 이전은 `background`다. 같은 본문은 각 역할 안에서 중복 제거한다. 과거 복사본 때문에 새 회차 문서를 없애지 않는다.
- 모든 적격 문서를 카드로 전달한다. 카드는 원문의 첫 600자와, 본문이 900자를 넘으면 마지막 300자의 **정확 인용**이다. 문자 위치는 Unicode code point 기준이다. 본문 전체를 모델이 읽었다고 주장하지 않는다. 나머지 본문은 원천 저장소에 남는다.
- 기업명은 수집 자료의 연결 정보를 보존한다. 업종 관계는 실제 인용에 있을 때만 해석한다. 업종 시세·수급·해외장·금리·미수집 공시를 추가 수집한 구현은 아니다. `sectorPriceFeedAvailable=false`, `marketRepresentative=false`를 명시한다.
- 문서 1,000개 또는 생성 요청 2 MiB를 넘으면 중단한다. 기업을 조용히 잘라내지 않는다. 많은 배경 자료를 매 회차 읽으므로 토큰 사용량은 기존 3개 이슈 전용 입력보다 커질 수 있다.

## 이전 브리핑과 출퇴근 차이

즉시 이전 반대 회차의 cutoff가 이번 `window.from`과 일치하고, 저장된 요약이 검증 PASS일 때만 사용한다. 없거나 보류됐다면 오래된 결과로 대체하지 않는다. 이전 결과·해시·종류(`simulated_previous_output`)를 고정한다. 새 실행은 시간 순서대로 진행해 이번에 만든 이전 결과를 다음 회차에 전달한다.

| 회차 | 작성 내용 | 기계 검증 |
|---|---|---|
| 출근 | 직전 퇴근 이후 새 정보, 기업·업종 공통 요인, 이전 전망의 유지/강화/약화/철회, 당일 확인할 변수 | 실제 이전 forecastId와 새 근거가 필요한 `forecast_update`; 09:20을 장전으로 표현하지 않음 |
| 퇴근 | 실제 제공된 관측값과 출근 전망 비교, 확인된 다음 거래일의 조건부 전망 | `result_comparison`의 이전 전망·평가 ID와 서버 평가 결과 일치; 일별 종가만으로 장중 흐름을 만들지 않음 |

이전 요약에 구조화 전망이 없으면 `previousPublicationIds`로 문안·새 정보의 차이는 비교할 수 있다. 기존 감성이나 요약 텍스트를 가격 전망·적중 기록으로 변환하지 않는다. 현재 사실은 이번에 연결한 원문/관측값으로 별도 입증한다.

## 전망과 결과 평가

새 가격 방향 전망에는 명시적인 as-of 거래 세션 달력, 기준값, 대상 거래일, 종료 시각이 필요하다. 달력 형식은 다음과 같다. 아래는 형식 예시이며 실제 거래일 정보가 아니다.

```json
{
  "schemaVersion": "zoop-market-session-calendar-v1",
  "sessions": [{
    "date": "2026-10-08",
    "tradingDay": true,
    "nextTradingDate": "2026-10-12",
    "closeAt": "2026-10-08T15:30:00+09:00",
    "availableAt": "2026-10-01T00:00:00+09:00",
    "sourceRef": "https://example.invalid/authored-calendar"
  }]
}
```

대상 날짜의 별도 세션 행도 필요하다. 달력 각 행은 회차 마감 이전에 알려진 기록이어야 한다. 달력 공급원과 실제 운영 세션 검증은 후속 연결 사항이다. 코드가 신뢰할 수 있는 달력을 자동 수집하거나 HTTP 주소의 진위를 인증하는 것은 아니다.

- 출근은 당일, 퇴근은 달력에 지정된 다음 거래일 종가를 기준값과 비교한다. 현재는 KOSPI/KOSDAQ만 대상이다. 은행 고시 USD/KRW 기준환율은 시장 종가 전망·평가로 바꾸지 않는다.
- 새 전망은 `targetId`, 방향, 정확한 근거, 반대 요인, 조건을 보존하고 서버가 불변 `forecastId`를 만든다.
- 기간 종료 + 정확한 대상일/값 종류의 실제 관측 + 판정 가능한 방향 + 미해소 조건 없음이 모두 충족돼야 방향 일치 여부를 계산한다.
- 기간 미완료, 관측 누락, 조건 충족 여부 미관측, 불확실 방향은 `unavailable`이다. 틀린 전망으로 계산하지 않는다. 조건 관측 생산자는 아직 없다.
- 달력이 없으면 새로운 가격 전망은 만들지 않는다. 기업 맥락·새 정보·이전 요약의 서술 비교와 확인할 변수는 제공할 수 있다.

## 생성·검증·저장·조회

`market-context/generation.md`와 `verification.md`를 사용한다. 사실/해석/전망/전망 갱신/결과 비교를 구분한 2~8개 문장을 생성하고 독립 검증 요청으로 전 문장을 확인한다. 기존 숫자·인과·시점·투자 조언 검사에 비교·전망 적합성 검사를 추가한다. 최대 1회 보완하며, 거절/미완료/불명 사용량을 성공으로 바꾸지 않는다.

Structured Outputs는 형태 검증이며 사실 검증을 대체하지 않는다. [공식 지침](https://developers.openai.com/api/docs/guides/structured-outputs)에 맞춰 strict 스키마를 쓰고 서버에서 근거 ID, 시점, 원문 위치, 이전 결과, 평가 결과를 다시 검사한다.

입력/프롬프트/요약/요청·응답·사용량을 SHA로 묶는다. 부동소수점이 포함된 JSON artifact는 저장한 **원본 바이트**로 검증한다. 전망·평가 ID의 숫자는 Python/Java 간 렌더링 차이를 피하도록 정규화한 10진 문자열로 바꾼 뒤 canonical SHA를 계산한다. 기존 공통 canonical 규칙과 과거 ID는 바꾸지 않는다.

Java importer는 모델 기록만 믿지 않고 원천·발행시각 등록부로 적격 모집단과 정확 인용을 재구성한다. 모든 넓은 입력을 `articles`/`evidence`/`sourceBindings`에 연결하며, 결과·이전 맥락·전망/평가는 `public_snapshot.marketEnrichment`에 저장한다. 기존 `marketSummary.text/evidenceIds`로 공개 투영하므로 기존 프론트가 표시할 수 있다. 미선정 근거의 현재 열람 권한이 철회된 경우에도 조회를 차단한다. 동일 재가져오기는 기존 payload/스냅샷/manifest를 바꾸지 않는다.

## 실행

저장된 실제 자료로 **호출 없이 입력만 고정**:

```sh
python3 scripts/briefing_market_context_preview.py \
  --market-bundle /absolute/prior-market/bundle-v2.json \
  --sources /absolute/sources.jsonl --clocks /absolute/registry.json \
  --user-inbox-ref inbox/user-message.md \
  --output /absolute/new-private-inputs --write-inputs
```

`--write-inputs`가 없으면 디렉터리도 생성하지 않는다. 저장한 입력은 검토용이며 결과 생성·발행이 아니다. 실행 시 즉시 이전의 새 결과가 들어가므로 preview의 seed 요약과 실행 결과에 따라 후속 입력 SHA는 달라질 수 있다.

별도 실제 생성 실행:

```sh
python3 scripts/briefing_market_enrichment.py \
  --baseline /absolute/original-news --output /absolute/new-private-market \
  --sources /absolute/sources.jsonl --clocks /absolute/registry.json \
  --user-inbox-ref inbox/user-message.md --include-market-context \
  --key-file /absolute/private-key-file --max-calls 44 \
  --execute-authorized-enrichment
```

기존 뉴스 baseline은 `marketEnrichment`가 없는 원본이어야 한다. 선택적으로 `--session-calendar`, 같은 뉴스 baseline의 `--previous-market-bundle`을 받는다. 실행 플래그가 없으면 OFFLINE 계획만 반환한다. 모델은 기존 `gpt-6-luna`를 유지한다. 생성+검증 최소 2회/회차, 1회 보완 포함 최대 4회/회차이며 설정된 호출 한도가 적용된다. 새 결과는 기존 opt-in importer의 별도 DB 경로로 연결한다. 기존 발행 DB를 덮어쓰지 않는다.

## 검증 경계

Python 테스트는 미래자료 제외, 전체 입력 범위, 실제 인용, 이전 회차 보류, 출근 갱신, 퇴근 비교, 거래일·평가 조건, 입력 변조/재실행을 다룬다. `BriefingMarketContextPostgresTest`는 명시적으로 작성한 합성 원문·달력·모델 응답으로 실제 PostgreSQL과 Spring HTTP 저장/복원·재가져오기·변조·권한 철회를 검증한다. 이 테스트는 유료 AI 결과나 실제 예측 적중률 검증이 아니다.

## 이미 고정한 요청을 그대로 실행

`briefing_market_context_run.py`는 preview가 저장한 첫 생성 요청의 **바이트/SHA를 그대로** 사용한다. 위의 순차 생성 경로와 달리, 입력에 들어 있던 기존 이전 브리핑 버전을 새 결과로 교체하지 않는다. 따라서 이 실행의 퇴근 비교가 새로 생성한 출근 문안을 자동으로 비교한 것이라고 설명하면 안 된다. 비교 대상 roundId와 실제 요약 결과 SHA를 함께 확인한다.

```sh
python3 scripts/briefing_market_context_run.py \
  --inputs /absolute/private/frozen-preview \
  --market-bundle /absolute/private/prior-market/bundle-v2.json \
  --sources /absolute/private/sources.jsonl --clocks /absolute/private/registry.json \
  --output /absolute/private/new-fixed-run \
  --user-inbox-ref inbox/execution-authorization.md \
  --key-file /absolute/private/openai.env --workers 3 --max-calls 44 \
  --execute-authorized-generation
```

실행 플래그가 없으면 전체 입력을 대조한 뒤 OFFLINE 계획만 반환한다. 준비 당시 inbox와 이번 실행 승인 inbox는 별도 보존한다. 생성·검증의 고정 근거는 동일하고, 검증 실패 시 같은 근거 내 1회 보완까지만 허용한다. 최종 실패는 시장 요약 unavailable이며 기존 뉴스 발행 상태를 임의로 성공/실패로 바꾸지 않는다. 완료 호출은 재사용하고 실패·사용량 불명 호출은 자동으로 재전송하지 않는다.

`marketEnrichment.comparisonBaselineSha256/frozenPreviewSha256`와 회차별 `frozenExecution`이 원래 비교 bundle, 준비 manifest, 최초 요청 SHA와 실행 승인 기록을 묶는다. Java는 별도 보존한 기존 비교 bundle의 실제 요청/응답·검증·토큰 기록까지 검증한 뒤 그 버전과 비교한다. 비교 원본·preview·기존 영수증도 불변 artifact로 저장한다. 운영 발행이나 신규 공급원 수집을 승인하는 경로는 아니다.
