# 회차별 시장 요약·일별 지표 연결

`briefing_market_enrichment.py`는 완료된 원발행 시각 시뮬레이션의 뉴스 결과를 보존한 채 시장 입력과 요약을 별도 결과에 고정한다. 운영 수집기·AWS 정시 실행이 아닌 로컬 과거 시뮬레이션 도구다. 기존 bundle·DB를 덮어쓰지 않고 새 output/DB/manifest를 사용한다.

## 입력과 시각

- 기존 source/clock/bundle SHA와 SELECTED/PASS 뉴스 결과를 확인한다. 기존 보류 회차는 계속 미발행이며 이번 레이어로 승격하지 않는다.
- KOSPI·KOSDAQ은 Yahoo Finance의 일별 종가 원응답을 보존한다. 09:20 회차에는 당일 종가를 넣지 않는다. 17:30 회차는 표준 정규장 마감 15:30 이전으로 간주한 일별 값 중 가장 최근 확인 가능한 값을 사용한다. 날짜별 원천 행을 사용하며 단순 평일 판정으로 거래일을 만들어내지 않는다. 특별장·정확한 과거 거래 캘린더 검증은 별도이며 장중 관측 시각을 꾸미지 않는다.
- 원/달러는 네이버의 하나은행 일별 고시 기준환율 이력이다. 날짜만 제공되므로 다음 날 00:00 KST를 보수적인 가용 상한으로 사용한다. 당일 17:30 이전 값인지 입증할 수 없으므로 같은 날 값은 제외한다. API는 **valueKind=reference**로 은행 고시 기준환율임을 구분하고 화면에는 **일별 고시값·지연·실제 기준일**을 표시한다. 지수의 일별 종가는 close, 마감 전 관측값은 latest다. 외환시장 종가·실시간 환율로 사용하지 않는다.
- 수치는 원문을 보존하면서 Decimal HALF_UP 두 자리로 정규화한다. 변동값과 등락률은 정규화된 현재값과 직전 확인값으로 계산한다. 없는 값·실패·기준일은 0이나 임의 시각으로 채우지 않는다.
- 원응답 URL/시각/SHA/bytes, 현재 행·비교 행, 회차 cutoff, 수집 한계를 스냅샷에 함께 기록한다. 당시 수집 가용성·당시 본문 동일성을 입증하는 기록은 아니다.

## 시장 요약과 검증

`market-summary/`의 작성·검증 프롬프트와 strict JSON schema를 고정한다. 모델은 `gpt-6-luna`, Responses `store=false`를 사용한다. 입력은 해당 회차의 고정된 선정 뉴스·검증된 인용·뉴스 문장·3개 지표 스냅샷이며 추가 검색이나 조회 시 재생성은 없다.

2~4개 원자적 문장에 뉴스 evidenceId와 지표 ID를 구분해 연결한다. 적어도 하나의 뉴스 근거를 요구한다. 모든 선정 뉴스를 각각 열거해야 하는 형식은 아니다. 지표는 뉴스의 주가 영향 인과관계나 다음 장 전망을 입증하지 않는다. 제한된 입력만 요약한다는 범위 문구는 서버에서 붙인다.

별도 검증 호출이 문장별 수치·인과·시점·투자 권유 여부를 확인한다. 모든 문장이 SUPPORTED이고 각 검증 플래그가 참일 때만 PASS다. 동일 고정 입력으로 보완은 최대 1회다. AI 검증은 입력과의 일치 평가이며 독립적인 경제 사실 검증을 뜻하지 않는다.

## 저장과 조회

새 bundle의 `marketEnrichment`는 원 bundle SHA와 회차/뉴스 결과/시장 스냅샷/프롬프트/AI 결과/receipt를 묶는다. Java importer는 실제 원응답을 독립 파싱해 안전한 기준일·현재값·기준값·변동값을 재검증한다. artifact의 raw JSON bytes SHA를 확인하며 숫자 표현을 다른 canonical 형식으로 재직렬화하지 않는다.

- `briefing_rounds.published_payload.marketVariables`: 해당 회차 지표.
- `briefing_rounds.public_snapshot.marketSummary`: PASS 요약·근거·생성 시각·resultVersion.
- `public_snapshot.marketEnrichment`: 보강 입력·결과 lineage.
- `artifacts`: 원응답·스냅샷·요약 결과·검증 응답·요청/응답·AI 호출 receipt.

이 개발 재생 경로의 AI 사용량은 `ai_call_receipt` artifact로 보존한다. 운영 `ai_executions` writer 연결까지 완료한 것으로 해석하지 않는다. 실패·보완 시도의 실제 토큰도 보존하며 사용량 불명은 NULL로 유지한다.

`GET /api/v1/briefings`는 DB 저장값만 복원한다. 공개 DTO와 정본 OpenAPI의 valueKind enum에는 reference를 추가했다. ERD·적용 migration은 변경하지 않는다. 그래프가 미연결이면 unavailable을 유지한다. 기존 local profile/loopback/manifest/현재 권한/원문 SHA 가드도 유지한다. 같은 결과를 재실행하면 새 HTTP·AI 호출·DB 행을 만들지 않는다.

기존 발행 스냅샷의 은행 일별 고시값이 close로 저장된 경우, 조회 응답 복사본에서만 reference로 표현한다. usdkrw·naver·FX_USDKRW·정확한 네이버 일별 prices URL·observedAt=NULL인 알려진 원천에 한정한다. 지수 종가, 출처가 다른 FX 종가, latest는 변환하지 않는다. 저장 원문·가격·기준일·요약·AI 입력/응답·해시·영수증은 바꾸지 않으며 시세 재조회·AI 재생성을 하지 않는다. 새 producer는 처음부터 reference로 기록하고 importer는 기존 close 원장도 재생할 수 있다.

## 실행

기본은 offline이다. 아래 명시 플래그와 private key·사용자 inbox·호출 상한이 있어야 수집·유료 실행한다. 실제 자료와 키, DB 및 실행 결과는 Git에 올리지 않는다.

```sh
python3 scripts/briefing_market_enrichment.py \
  --baseline /absolute/private/completed-round-run \
  --output /absolute/private/new-market-run \
  --sources /absolute/private/source.jsonl \
  --clocks /absolute/private/clock-registry.json \
  --user-inbox-ref inbox/YYYY-MM-DD-HHMM-market.md \
  --key-file /absolute/private/openai.env \
  --max-calls 44 --workers 3 --execute-authorized-enrichment
```

새 bundle은 기존 `BriefingReplayImporter`로 **새** `briefing_replay` 테스트 DB에 넣고 새 artifact-root/grants/manifest로 조회한다. 기존 발행 결과에 덮어쓰면 거절된다.

검증: `python3 -m unittest discover -s scripts/tests`, API `test`/`briefingReplayIntegrationTest`, React 브리핑 시험·lint·build. D-BRF-01·02의 주요 시장 지표는 일별 기준일과 은행 고시값을 표시한다.

## 생성 Swagger의 union 스키마

`BriefingResponse`의 JSON 스냅샷 필드에는 oneOf 참조가 사용된다. 실제 Springdoc 문서가 이 참조만 만들고 AnalysisSummary/MarketVariables/SinceMorning 본문을 누락하는 경우를 방지하기 위해 `BriefingOpenApiConfiguration`에서 문서용 모델과 하위 스키마를 명시적으로 등록한다. Swagger 활성화 정책은 변경하지 않는다. 통합 시험은 실제 `/v3/api-docs`의 reference enum과 모든 로컬 스키마 참조의 해소까지 검사한다.


### 보완안의 구조 거절

앞선 초안이 의미 검증에 실패하고 마지막 보완안도 구조 검증에서 거절되면, 최종 claims/checks는 비우고 최종 verificationRequestDigest는 null로 보존한다. 이전 초안·검증과 모든 실제 호출은 attempts/usage 및 원 요청/응답에 남는다. 실패한 마지막 생성안과 앞선 verifier를 하나의 최종 결과로 섞지 않으며, importer는 요약을 unavailable로 제공하고 정상 뉴스까지 보류시키지 않는다. 실제 offline producer→enrichment→PostgreSQL/HTTP 회귀가 이 전이를 검사한다.
