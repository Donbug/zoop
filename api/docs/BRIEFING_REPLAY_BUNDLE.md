# 실제 자료의 브리핑 개발 재생

`scripts/briefing_replay.py`는 수집된 뉴스·공시 JSONL을 고정해 전체 후보 중요도 평가, 최대 세 이슈 선정, 출근·퇴근 형식 작성과 별도 의미 검증을 수행하는 명시적 operator 실행기다. 웹 요청·서버 시작·정시 작업으로 실행하지 않는다. 모델은 `gpt-6-luna`이며 [Responses structured output](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), `store=false`를 사용한다.

## 자료 범위와 승인

이번 입력은 2026-10-02~08 주간 수집 대상 자료를 10월 16일에 본문 확보한 역사 재생이다. 2026-10-09 09:20·17:30은 같은 주간 자료를 출근·퇴근 **형식**으로 편집하는 개발 회차다. 실제 전날 저녁 이후 아침 자료, 실제 장중·장마감 흐름을 의미하지 않는다. 시장 지표·이전 전망·실제 회차별 추가 정보가 없으므로 시장 요약·시장 지표·출근 대비 비교를 `unavailable`로 보존한다. 그래프 버전은 `null`이며 가짜 공개 그래프 버전을 만들지 않는다.

원본 `allowModelSend=false`와 `rightsStatus`, 원문·문서 버전·본문 범위·수집 시각·공급자 날짜 추정·원문 날짜 미검증·첨부 누락·수집 연관성은 감사 자료에 그대로 보존한다. 이번 사용자 지시의 개발용 모델 전송·로컬 표시 승인은 별도 `authorization`으로 연결한다. 원본 권한 필드를 바꾸거나 운영 수집·배포 권한으로 확대하지 않는다. 개발 재생은 화면에서도 실제 정시 브리핑과 구분해야 한다.

## 처리 순서

1. JSONL 전체의 SHA-256과 모든 행을 감사한다. 본문 미확보·불충분, 본문 해시 불일치, 문서/URL 식별 부재, 동일 본문 중복은 사유와 함께 제외한다. 공급자 추정 일자는 정확한 발행 시각으로 바꾸지 않는다. 최대 모집단은 1,000행이다.
2. 적격 문서 **전부**를 기본 30건씩 최대 3개 병렬로 AI 평가한다. 배치별 schema에서 각 실제 documentId를 **필수 object property**로 만들고 그 값의 documentId도 해당 ID 하나로 고정한다. 코드에서도 키/값 일치와 누락·발명·중복을 검증한다. 제목·수집 연관 기업·원천 종류·날짜 한계·실제 본문 시작/끝 일부를 제공한다. AI가 중요도 0~3, 비교 priority 0~100, 상태·사건 그룹·이유·한계를 작성한다. 사람이 중요도를 매기지 않는다.
3. AI 평가에서 실질 변화가 있는 적격 문서의 상위 사건 최대 12개를 점수순으로 원문 재검토한다. 최종 AI는 중복 사건을 묶고 최대 3개를 선택한다. 최초 평가의 점수는 사실 근거가 아니며 원문 검토로 낮추거나 보류할 수 있다. 자료 부족 시 세 개를 채우지 않는다.
4. 선정 인용이 실제 원문의 정확한 연속 부분문자열인지 코드가 확인한다. Unicode code point 기준 시작/끝, 본문 해시, 문서 버전과 결정적 evidence ID를 고정한다. 번역·공백 정규화·생략된 인용은 허용하지 않는다.
5. 같은 선정 입력을 출근·퇴근 프롬프트로 각각 작성한다. 이슈마다 제목과 2~3개 `fact`/`plan`/`outlook` 문장이 필요하다. 제목과 각 문장은 고정된 해당 이슈의 인용 ID를 가져야 한다.
6. 작성과 **분리된 호출**로 제목·모든 문장을 검증한다. 각 대상이 정확히 한 번 검증되고 모두 `SUPPORTED`, 상태·시간·숫자·투자 권유 검사도 모두 통과해야 `PASS`다. 내용 불합격은 같은 자료로 최대 1회만 보완한다. 별도 모델 호출의 평가는 독립적인 외부 사실 검증을 뜻하지 않는다.

35개 호출은 적격 874건을 batch 30으로 처리하는 예다: 평가 30 + 최종 선정 1 + 두 형식 작성/검증 4. 두 형식 모두 한 번 보완하면 최대 39개다. 적격 수·선정 수·검증 결과에 따라 실제 호출 수는 달라진다. 확정 청구액을 추정하지 않고 응답의 실제 입력·출력 토큰을 기록하며, 출력 토큰에 포함된 reasoning 토큰은 다시 합산하지 않는다.

기존 완료 응답의 문서 ID 전사/coverage 오류를 명시적으로 보완한 호출은 이 정상 흐름과 별도로 모두 합산한다. 예를 들어 완료 2건의 구조를 새 제약으로 보완하면 정상 37개, 두 형식 내용 보완까지 최대 41개가 된다. `--max-calls`는 기존 reservation과 보완 호출까지 포함한 전체 실행 한도다.

## CLI

원본·응답·감사·번들은 Git 밖의 개인 개발 자료다. 출력 폴더는 `0700`, 키 파일 및 출력 파일은 `0600`이어야 한다. 키 파일은 `OPENAI_API_KEY=...` 한 항목을 포함하며 실행기에서만 읽는다. 키·응답 본문·예외 원문을 콘솔에 출력하지 않는다.

다음은 유료 호출을 하지 않는 기본 감사다. 경로는 각 operator 환경의 실제 절대 경로로 지정한다.

```sh
python3 scripts/briefing_replay.py \
  --sources /absolute/private/source.jsonl \
  --output /absolute/private/replay-run \
  --user-inbox-ref inbox/approved-user-instruction.md
```

개발용 전송 승인이 확보된 동일 입력을 실제 실행하려면 다음 옵션을 추가한다.

```sh
python3 scripts/briefing_replay.py \
  --sources /absolute/private/source.jsonl \
  --output /absolute/private/replay-run \
  --user-inbox-ref inbox/approved-user-instruction.md \
  --key-file /absolute/private/openai.env \
  --execute-authorized-development
```

`--batch-size`는 20~30, `--workers`는 1~3, `--shortlist-size`는 3~15이며 기본값은 30·3·12다. `--max-repairs`는 0 또는 1, 기본 1이다. 출력 경로에 고정한 원본·승인 참조·모델·설정·프롬프트/스키마 SHA가 달라지면 기존 실행 결과를 덮어쓰지 않는다.

## 기록·재사용·중단

`identity.json`, `population-audit.json`, `assessments.json`, `shortlist.json`, `selected.json`, 두 형식 결과, `bundle.json`, 호출별 request/response/receipt를 비공개 출력에 보존한다. 실행 ID는 원본 SHA·승인 참조·모델·설정·전체 프롬프트/스키마 SHA와 연결된다. 형식별 결과도 별도 SHA 바인딩을 확인한다.

모든 유료 전송 전에 request digest별 pending reservation을 기록한다. 같은 완료 요청은 모델·입력·프롬프트·스키마를 포함한 request digest와 저장 응답 해시를 검사한 뒤 재사용한다. pending만 남았거나 실패/토큰 불명 상태이면 자동 재호출하지 않는다. 실행 중 실패·불명 결과가 생기면 아직 전송하지 않은 후속 호출도 멈추며, 이미 진행 중인 최대 세 호출의 결과·사용량은 보존한다. 실패·불명 사용량은 `null`이고 0으로 변환하지 않는다. `.run.lock`이 남으면 중단된 실행의 reservation을 먼저 조사해야 한다.

초기 정적 schema·배치 enum 배열로 끝난 응답은 사용량·성공 상태·coverage를 먼저 확인한다. 정확한 기존 배치는 그대로 재사용한다. 알려진 완료 응답에서 ID 누락/발명/중복이 확인되면 ID별 필수 object와 출력 한도 12,000의 **새 request digest**로 구조 보완하고 `coverage-repairs/`에 원 요청→보완 요청과 누락·발명·중복을 기록한다. 과거 배열 보완 감사도 당시의 실제 제약·출력 한도로 보존한다. 기존 유료 응답과 사용량은 삭제하지 않는다. 실패·불명 reservation을 새 schema로 우회하는 경로는 없다.

HTTP 200이고 실제 토큰이 확인되며 provider 상태가 `incomplete`, 사유가 정확히 `max_output_tokens`인 경우는 응답 유실과 다르다. 이때도 자동 재시도하지 않으며 operator가 `--complete-known-truncation <기존-request-SHA256>`로 **해당 요청만** 승인해야 새 object 요청으로 완성할 수 있다. 원 `incomplete` 상태·8,000 등 실제 소모 토큰은 보존하고 `coverageCorrections`에 승인 참조·원/대체 digest·조건을 기록한다. 후속 importer는 실제 성공 대체 receipt와 이 감사를 대조한다.

실행 프로세스의 신규/재사용 카운트는 고정 번들에 넣지 않는다. 같은 완료 입력의 재생은 신규 호출 0과 번들 바이트 동일성을 확인한다. 프롬프트를 바꾸고 다른 결과를 받으려면 별도 출력 경로와 검토 가능한 새 실행 기록이 필요하다.

## 발행 입력 번들 v1

| 필드 | 의미 |
|---|---|
| `schemaVersion` | `zoop-briefing-replay-v1` |
| `runId`, `sourceFileSha256` | 실행·원본 파일 고정 식별 |
| `authorization` | `scope=development_replay`, 원본 SHA, 사용자 inbox 참조, 운영 승인 없음 |
| `historicalReplay` | 주간 자료 범위·개발 회차일·이후 수집·동일 주간 모집단 사용·날짜 추정 한계 |
| `selected[]` | AI가 정한 issueId·순위·이유·수집 연관 기업명·점수·한계·원문 인용 |
| `selected[].sources[]` | documentId/documentVersion/bodySha256/url/quote/start/end/evidenceId와 출처 메타데이터 |
| `editions.morning/evening` | generatedAt, 고정 issueId·rank·title·titleEvidenceIds·claims, 검증 결과·보완 이력·사용량 |
| `verification.checks[]` | `issueId:title` 및 `issueId:claim:0` 형식의 모든 대상별 판정·조건 검사·이유 |
| `receipts[]` | stage/model/requestDigest/responseId/status와 실제 inputTokens/outputTokens, 사용량 확인 여부 |
| `coverageCorrections[]` | 구조 보완의 원/대체 request digest, 실제 원 상태·HTTP·사용량 확인·잘림 사유·승인 참조·당시 제약 |

사용량 stage는 `briefing_population_importance`, `briefing_global_selection`, `briefing_morning_generation`, `briefing_morning_verification`, `briefing_evening_generation`, `briefing_evening_verification`이다. 원응답과 원문은 이 비공개 기록에 남기며 공개 코드·CI fixture에는 합성 자료만 사용한다. 두 형식 모두 최종 `PASS`인 번들만 후속 개발 발행 importer에 전달한다. 이 실행기는 직접 DB 발행·운영 배포를 하지 않는다.

오프라인 검증:

```sh
python3 -m unittest discover -s scripts/tests -p test_briefing_replay.py -v
```
