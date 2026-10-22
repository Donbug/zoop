# 회차별 과거 시뮬레이션: 시간과 입력 감사

사용자가 당시 수집 기록이 없다고 확인하고 2026-10-02~08 자료의 회차별 과거 시뮬레이션을 선택했다. 이 모드는 `publication_clock_simulation`이다. 정상 운영의 수집 마감 조건을 충족했다고 주장하지 않는다.

## 원본과 시각 확인

- 원본 881행, 본문 중복 제외 874건. 원본 JSONL의 발행 시각은 비어 있고 실제 본문 수집은 10월 16일이다. 원본과 수집 시각·권한 플래그는 변경하지 않는다.
- 별도 clock registry에 현재 publisher 페이지의 publication 메타데이터와 HTML SHA를 보존한다. 원문 URL·문서 ID·본문 SHA·원본 파일 SHA가 서로 일치해야 한다.
- timezone을 포함한 `datePublished` 또는 발행 메타데이터만 사용한다. 검색 날짜, 공급자의 추정 날짜, `dateModified`, 관련 기사의 날짜는 발행 시각 증거가 아니다.
- 날짜만 있거나 timezone이 없거나 발행 시각 선언이 서로 충돌하면 회차를 임의 배정하지 않는다. 같은 순간의 서로 다른 offset 표기는 동등하게 정규화한다.
- 현재 페이지의 발행 선언은 당시 본문이 같은 버전이었다는 증명이 아니다. 이 한계는 입력·결과·화면에 유지한다. HTML이 제한된 앞부분이면 그 범위도 기록한다.

이번 원본의 관찰 결과는 정확한 시각 확인 547건, 날짜만 확인 16건, 시각 미확인 134건, 페이지 미확보 177건, 충돌 7건이다. 정확한 시각 중 492건이 지정한 14개 창에 들어가며 55건은 창 밖이다. 492건은 회차 내 중복 제거 전 건수다. 실제 운영의 `collectedAt <= cutoff` 기준으로 이 과거 자료를 사용할 수 있는 건수는 0이다.

## 회차 분리

각 날짜의 출근은 전일 17:30부터 당일 09:20, 퇴근은 당일 09:20부터 17:30까지 한국 시각으로 계산한다. 구간은 `(from,to]`다. 10월 2일 출근의 하한 10월 1일 17:30은 시험의 시작점이며 서비스 최초 회차의 open start를 뜻하지 않는다. 거래일·장중 상태를 추정하지 않고 7개 달력 날짜의 14개 회차를 시험한다.

| 날짜 | 출근 입력 | 퇴근 입력 |
|---|---:|---:|
| 10-02 | 6 | 33 |
| 10-03 | 58 | 7 |
| 10-04 | 36 | 12 |
| 10-05 | 27 | 19 |
| 10-06 | 57 | 34 |
| 10-07 | 56 | 35 |
| 10-08 | 68 | 44 |

시간 창으로 먼저 분리한 뒤 각 창 안에서 본문 중복을 제거한다. 중요도 예비평가·최종 선정·작성·별도 검증을 회차마다 실행한다. 이전 주간 평가나 주간 선정 3개를 재사용하지 않는다. 예비평가에서 중요도 2 이상인 ELIGIBLE과 원문 재검토가 가능한 HOLD를 함께 검토한다. 발췌문 부족만으로 전체 원문 검토 기회를 없애지 않으며, 원문에서도 해소되지 않으면 선정하지 않는다. 최대 세 개이며 중요도 2 이상만 선정한다. 중요도 3에는 확정 공통 정책 또는 서로 다른 산업으로의 실제 전이 근거가 필요하다.

## 이전 결과와 보류

바로 앞 회차의 PASS 시뮬레이션 결과가 있을 때만 그 해시를 연결한다. 실제 과거 공개본이나 예측 적중 기록으로 부르지 않는다. 바로 앞 회차가 보류되면 이전 비교 입력은 unavailable이며 더 오래된 결과로 몰래 대체하지 않는다.

시각 미해소 자료가 존재하므로 입력·선정 0건은 정상적인 정보 부재로 단정할 수 없다. `HELD_SOURCE_COVERAGE`를 남긴다. 생성 문장의 근거 검증이 통과하지 않으면 `HELD_VALIDATION`이며 DB에 발행본을 만들지 않는다. 정상 발행 결과와 보류 상태를 따로 보존한다.

실제 시장 지표·시장 요약 생산자·당시 거래일 상태·가격 변화·이전 전망의 적중 평가 자료는 없다. 해당 응답은 unavailable로 유지한다. 새 모드는 `zoop-briefing-publication-clock-simulation`으로 표시하며 운영의 그래프 버전 필수 검증은 완화하지 않는다.

## 실행과 재사용

[실행기 안내](BRIEFING_ROUND_SIMULATION.md)를 따른다. 원본, clock registry, HTML, 프롬프트/스키마, 사용자 승인, 각 회차 창과 이전 결과의 해시를 고정한다. 완료 응답만 재사용하고 불명·실패 reservation은 자동 재전송하지 않는다. 모든 실제 시도와 토큰 사용량을 보존하며 기존 주간 결과·원본·DB는 덮어쓰지 않는다.

실제 결과·원문·HTML·자격 증명·DB·artifact는 Git 밖의 개인 폴더에 둔다. 저장소에는 코드와 합성 시험 자료만 넣는다. 실데이터 결과와 회차별 선정 사유는 별도 검토 보고서에서 제공한다.

## 로컬 DB·API·프론트 연결

새 DB는 이름에 `briefing_replay`가 포함된 별도 PostgreSQL DB이며 `local` profile만 사용한다. 아래 경로는 실제 개인 경로로 교체한다. 인증용 환경 설정은 API README를 따른다. OpenAI 키는 Java에 전달하지 않는다.

```sh
java -jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar \
  --spring.main.web-application-type=none \
  --zoop.briefing.replay.import-enabled=true \
  --zoop.briefing.replay.source=/absolute/private/source.jsonl \
  --zoop.briefing.replay.clocks=/absolute/private/clock/registry.json \
  --zoop.briefing.replay.bundle=/absolute/private/per-round-run/bundle-v2.json \
  --zoop.briefing.replay.artifact-root=/absolute/private/artifacts \
  --zoop.briefing.replay.grants=/absolute/private/grants.json \
  --zoop.briefing.replay.manifest=/absolute/private/manifest.json \
  --zoop.briefing.replay.expected-source-sha256=<source-sha256> \
  --zoop.briefing.replay.user-inbox-ref=inbox/publication-clock-simulation-approval.md
```

HTML은 clock registry 옆 `html/`에서 읽는다. 원 요청·응답은 번들 옆 `calls/`에서 실제 바이트 SHA를 검증해 등록한다. 각 회차의 고정 입력·PASS 결과·검증·전체 사용량을 기존 artifact 등록부에 보존한다. 보류 회차는 published payload 없이 상태와 원 호출 기록만 보존한다. DB commit 후에만 grant/manifest를 원자적으로 게시하며 같은 번들은 기존 불변 행·바이트를 재사용한다.

API는 같은 DB, `local` profile, loopback 주소, `zoop.briefing.replay.read-enabled=true`, 동일 manifest와 `ZOOP_DOCUMENT_READ_GRANTS`·`ZOOP_DOCUMENT_READ_ARTIFACT_ROOT` 설정으로 실행한다. 프론트 `VITE_API_BASE_URL`은 이 API를 가리킨다. `GET /api/v1/briefings?date=2026-10-02&edition=morning`과 이력·상세 API를 통해 DB 저장값을 조회한다. 브라우저가 모델을 호출하지 않는다. 화면은 해당 실제 날짜·형식을 선택하고 회차별 시뮬레이션 안내와 미수집 상태를 표시한다.

시간 적합성 검증은 이 시뮬레이션에서 확인한 발행시각 창과 인용 내용의 실제 사건 시점·계획 조건을 판단한다. 늦은 수집과 당시 본문 동일성 미입증은 별도 고정 한계로 표시하며, 그 사실만으로 모든 문장을 실패시키거나 정상 운영의 수집 마감 통과로 바꾸지 않는다. 해당 한계 자체를 뉴스의 사실 문장처럼 작성하지 않는다.
