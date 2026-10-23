# 기업별 짧은 읽기와 회차 시세 (D-BRF-01·02)

간단히 보기는 전문을 잘라 붙이지 않습니다. 검증된 기업 전망을 입력으로 별도 생성한 `brief`(70자), `watch`(50자), `change`(60자)를 독립 검증합니다. 검증에 실패하면 전문을 짧은 요약 자리에 대신 표시하지 않고 자세히 보기를 안내합니다. 전체 보기·기존 조건·리스크·직접 인용·원문은 유지합니다.

## 저장·조회

`briefing_company_reading.py`는 기존 불변 번들을 다른 출력 폴더에 재사용하고 `presentationEnrichment.companyReadingLayer`를 추가합니다. 완료 호출과 미응답 기록은 재사용하며 새 실행에 최대 호출 수를 명시해야 합니다. 입력 번들·프롬프트·시세 등록부·실행 ID·권한 참조·호출 상한이 바뀌면 완료 캐시를 거부합니다. 모델은 기존 `gpt-6-luna`를 유지합니다.

Java importer는 원래 기업 결과 버전·입력·실제 요청/응답·프롬프트·검증 기록·토큰 사용량을 결속하고, 생성·검증의 `text.format` 전체(type/name/strict/schema)를 frozen 입력에서 독립 재구성해 대조합니다. `supported`가 true만 허용하도록 바뀐 기록은 수락하지 않으며, 원시 시세 파일의 SHA-256과 가격을 별도로 검증합니다. 새 표현은 불변 public snapshot의 `companyOutlooks.companies[].reading/price`에 저장됩니다. 시세 원본·읽기 입력·호출 영수증도 artifact로 등록합니다. 조회는 DB에 저장한 값만 복원하며 브라우저에서 최신 시세를 가져오지 않습니다. ERD·migration 변경은 없습니다.

## 가격의 의미

- `latest`는 회차 마감 이전에 끝난 정규장 5분봉 종가 또는 완료된 정규장 일별 종가입니다. 봉 시작 시각의 가격으로 종가를 선사용하지 않습니다.
- 출근은 해당 거래소의 이전 일별 종가 대비입니다. 같은 날의 일별 종가·고가·저가를 아침 회차에 넣지 않습니다.
- 퇴근은 **동일 기업의 같은 날 한국 시간 09:20 관측값 대비**입니다. 아침 브리핑에 선정되지 않은 기업도 시세 기준은 계산할 수 있습니다. 이것이 아침의 기업 전망이 있었다는 뜻은 아닙니다.
- 미국 기업은 한국 시간 아침과 퇴근 사이에 새 정규장 거래가 없을 수 있습니다. `no_new_session`으로 표시하며 변동률을 0%로 만들지 않습니다.
- 원시 응답에 섞인 현재 `regularMarketPrice`/미래 terminal row, 미완료 봉, 요청 구간 밖 값은 제외합니다. 다른 종목·통화·시간대·변조된 원본·미정의 분할 조정은 거부합니다.
- 적격 관측이 없는 경우 정상 HTTP 조회의 빈 이력(`eligible_price_missing`)과 공급자 HTTP 요청 실패(`provider_request_failed`)를 구분합니다. 요청 실패의 상태·원본은 영수증에 보존하며 화면은 시세 확인 실패로 표시합니다. 최신 값 대체나 자동 재시도는 하지 않습니다.
- 실제 가격 변화와 사업상 조건부 전망을 나란히 보여 줍니다. 주가 인과관계나 전망 적중률을 산출하지 않습니다.

## 개발 재생과 운영의 경계

현재 수집기는 Yahoo Finance 공개 과거 이력을 사용하는 **개발용 재생**입니다. 구 기록의 기본값은 2026-10-01~09이고, 새 연속 회차는 첫 마감 UTC 날짜 7일 전부터 마지막 마감 UTC 날짜 다음 날까지 명시적으로 요청합니다(최대 31일). 요청한 `period1`/`period2`·URL·원본 SHA를 함께 검증하며 다른 기간으로 같은 캐시를 재사용하지 않습니다. 선택 기업의 KRX 코스피 종목(`.KS`) 및 NASDAQ/NYSE 심볼만 지원합니다. 나중에 조회한 이력은 당시 수집본을 입증하지 않으며, 공급원 수정 이력·조정 정책·거래소 휴장/단축장 달력과 이용 권한을 운영 연결 전에 확정해야 합니다. 실패한 시세를 실시간 값으로 대체하지 않습니다. 주말을 제외하고, 수집된 봉이 존재하는 일반 정규장만 사용합니다.

거래 시간 기준: [KRX 현물 정규장](https://regulation.krx.co.kr/contents/RGL/03/03010100/RGL03010100T1.jsp), [NYSE core session](https://www.nyse.com/trade/trading-information). 미국 시각은 `America/New_York`로 변환합니다. 현재 예제의 10월 7~8일은 일반 정규장 기준입니다.

## 실행 순서

1. 공개 심볼별 5분/일별 이력을 `briefing_company_prices.collect`로 별도 폴더에 저장합니다. HTTP 결과·주소·조회 시각·원본 크기·SHA를 보존하며 저장된 원본을 자동 재조회하지 않습니다.
2. `briefing_company_reading.py --baseline <기존 결과 폴더> --output <새 폴더> --prices <시세 등록부 폴더> --authorization-ref <승인 참조> --run-id <새 ID> --max-calls <누적 상한>`으로 계획을 확인합니다. 실제 실행에는 `--execute --key-file <로컬 키 파일>`이 필요합니다.
3. 기존 replay의 로컬 전용 DB 가드·manifest·권한 검증을 그대로 사용해 새 DB에 import합니다. 운영 DB에 import하지 않습니다.
4. `/api/v1/briefings?date=...&edition=...`와 같은 React 화면에서 `reading=compact/full`을 확인합니다.

시험은 미완료 09:20 봉·같은 날 미래 종가·현재 terminal 값·다른 종목·원본 변조·미국 새 세션 부재, 짧은 읽기/전문 토글과 실제 4회차 DB→HTTP→화면을 포함합니다.

## 완료된 연속 회차에 시세만 추가하기

초기 `seriesCompanyReading`은 `pricePolicy=not_connected`로 저장되어 있어 짧은 읽기가 정상이어도 기업 시세가 없었습니다. 새 보완 경로는 해당 AI 결과를 수정하거나 재호출하지 않습니다. `seriesCompanyPrices`를 별도 layer로 추가하고 원본 bundle·기업 결과 버전·회차 마감·대상 기업과 결속합니다.

```sh
python3 scripts/briefing_series_prices.py \
  --baseline /absolute/private/completed-series \
  --output /absolute/private/new-series-with-prices \
  --authorization-ref '<기존 seriesCompanyOutlooks.authorizationRef>'
```

- 완료된 `seriesCompanyOutlooks`가 있는 명시 연속 회차 전용입니다. 출근·퇴근 1~14개를 지원하며 기업별 5분/일별 원본 각 1건을 조회합니다. 모델 키·유료 AI 호출은 필요 없습니다.
- 기존 입력·모델 요청/응답·사용량·회사 전망/짧은 읽기 버전·문안은 보존합니다. 시세는 새 `priceVersion`으로 구분하고 별도 DB에 import합니다. 현재 조회 서버나 옛 DB를 SQL UPDATE로 바꾸지 않습니다.
- 같은 출력의 재실행은 원본 SHA·요청 기간·저장 투영을 검사해 재사용합니다. 원래 실패 영수증을 성공값으로 덮어쓰거나 자동 재조회하지 않습니다. 네트워크 실패도 `httpStatus=0`으로 보존해 정상 빈 이력과 구분합니다.
- Java importer가 보존한 전체 기존 bundle 원본 바이트의 SHA, 원 기업 전망 버전·대상 집합·시점·가격 원본·정규장 종료 시점·비교 산식을 독립 검증합니다. 원시 시세와 보완 투영을 artifact로 저장하고 공개 응답은 `companyOutlooks.companies[].price`, `companyOutlooks.priceVersion`으로 복원합니다.
- 미국 기업의 한국 퇴근 회차는 마지막 미국 종가가 있어도 `comparisonStatus=no_new_session`일 수 있습니다. 화면은 종가·관측 시각과 “아침 이후 새 정규장 관측 없음”을 함께 표시하며 0%나 전망 적중률을 만들지 않습니다. 기존 `observedMovement=unavailable` 원문도 새 가격이 생겼다는 이유로 덮어쓰지 않습니다.
- 브리핑의 회차 고정 시세와 `/api/v1/companies/{id}/quote`의 최신 공급자 시세는 다른 경로입니다. 과거 브리핑을 오늘 가격으로 대체하지 않습니다. 휴장/단축장 달력·분할 조정·운영 이용 권한은 기존 개발 재생의 한계로 남습니다.
