# #134(FS068) 담당자 인계 — 브리핑 사용량 producer

브리핑 생성/기업 전망을 기존 생성기로 실행하면서 PostgreSQL 원장에 기록하는 경로를 추가했습니다. 관리자 getAiUsage 조회 API는 #134에서 연결해 주세요. 기존 브리핑·개발 DB·재생 수입기는 수정하거나 과거 호출로 소급 적재하지 않았습니다. [실행·상태·복구 상세](../../api/docs/BRIEFING_USAGE_LEDGER.md)를 기준으로 적용해 주세요.

## 읽을 테이블과 컬럼

`briefing_attempts`는 같은 DB/schema의 회차별 접수 이력입니다. round_id/attempt_no, started_at/finished_at, status/failure_reason/stages.failureStage, trigger/admin 스냅샷, owner_token/lease_until, input_artifact_id를 저장합니다. 추가 request_key는 멱등 키, purpose는 generation 또는 outlook입니다. 회차별 활성 시도는 하나이며 재처리는 새 시도 번호입니다. completed는 처리 종료이고 `stages.outcome=available|withheld`를 봐야 합니다. 실제 발행 여부는 briefing_rounds.published_at입니다.

`ai_executions.briefing_attempt_id`는 실제 FK입니다. 생성·생성 검증은 feature=briefing, 전망 생성·전망 검증은 feature=briefing-outlook으로 한 번만 귀속합니다. 모드는 live/replay/save_only입니다. provider/model/stage/prompt_version/reasoning_effort, started_at/finished_at, 입력·출력 토큰, 안전한 error_code, 영수증 artifact를 저장합니다. 추가 transmission_confirmed가 true/false/NULL로 전송 확인/미전송 확인/불명확을 구분합니다. retry_unit_id는 같은 수선 시도의 생성·검증을 한 번만 세기 위한 키입니다. 추정 비용의 통화·가격 근거는 currency/cost_basis이며 actual_cost는 청구 자료가 없어 NULL입니다.

## 집계 시 주의할 기준

- briefing.requests는 기간 내 briefing_attempts 접수 수, briefing-outlook.requests는 stages.outlook 접수 수입니다. 후자는 모델 호출 수가 아닙니다. 두 기능의 요청을 합산해 전체 요청 수로 사용하지 않습니다.
- 모델 호출은 live이면서 transmission_confirmed=true인 행입니다. 구간 안에 전송 불명확인 live 행이 있으면 modelCalls는 NULL과 설명을 반환합니다. replay/save_only는 모델 호출·재시도에서 제외합니다.
- retry_unit_id를 DISTINCT로 셉니다. 재선정/검증 수선에 생성+검증 두 호출이 있어도 한 단위입니다. 같은 purpose의 기존 live 이력이 있는 회차를 재처리해 새 live 호출이 있으면 새 시도도 재시도 단위입니다. 이전 시도가 local 재사용뿐이면 첫 live 호출을 재시도로 만들지 않습니다. 단순 재전송·조회·영수증 재수집·저장 복구는 제외합니다.
- 알려진 토큰 한쪽은 보존합니다. 합계 모집단에 해당 토큰이 NULL인 live 행이 있으면 그 합계는 NULL입니다. 미보고를 COALESCE(...,0)로 채우지 않습니다.
- 일별 사용량은 **ai_executions.started_at의 KST 날짜**입니다. 종료·영수증 수집 시각 또는 회차 날짜를 쓰지 않습니다. 요청 일자는 각 요청 접수 시각입니다.
- quality withheld는 모델 실패가 아닙니다. stages.outcome을 기준으로 결과를 구분해 주세요. unknown은 과금 불명확 상태이며 실패/0으로 바꾸지 않습니다. 지연은 시작·종료 시각이 둘 다 유효한 호출만 계산합니다.
- live 행은 job/AI attempt UNIQUE로 중복을 막습니다. 늦은 영수증은 원래 실행의 같은 행에 반영되므로 중복 집계하거나 오늘 수집량으로 옮기지 않습니다. app-direct ID를 AI 서비스의 ID로 해석하지 마세요.

아래는 집계 규칙 확인용 SQL이며 관리자 권한·window/asOf·빈 기간 표현 등 API 처리는 #134 구현에서 적용합니다.

```sql
-- :from <= started_at <= :as_of. daily는 started_at을 KST로 변환한다.
SELECT feature, (started_at AT TIME ZONE 'Asia/Seoul')::date AS kst_day,
  CASE WHEN count(*) FILTER (WHERE execution_mode='live' AND transmission_confirmed IS NULL)>0
       THEN NULL ELSE count(*) FILTER (WHERE execution_mode='live' AND transmission_confirmed) END AS model_calls,
  count(*) FILTER (WHERE execution_mode='replay') AS replay_calls,
  count(DISTINCT retry_unit_id) FILTER (WHERE execution_mode='live') AS retries,
  CASE WHEN count(*) FILTER (WHERE execution_mode='live' AND input_tokens IS NULL)>0
       THEN NULL ELSE sum(input_tokens) FILTER (WHERE execution_mode='live') END AS input_tokens,
  CASE WHEN count(*) FILTER (WHERE execution_mode='live' AND output_tokens IS NULL)>0
       THEN NULL ELSE sum(output_tokens) FILTER (WHERE execution_mode='live') END AS output_tokens
FROM ai_executions
WHERE briefing_attempt_id IS NOT NULL AND started_at>=:from AND started_at<=:as_of
GROUP BY feature, (started_at AT TIME ZONE 'Asia/Seoul')::date;

SELECT count(*) AS briefing_requests FROM briefing_attempts
WHERE started_at>=:from AND started_at<=:as_of;
SELECT count(*) AS outlook_requests FROM briefing_attempts
WHERE stages ? 'outlook'
  AND (stages->'outlook'->>'requestedAt')::timestamptz>=:from
  AND (stages->'outlook'->>'requestedAt')::timestamptz<=:as_of;
```

비용 합계도 live별 누락과 통화를 확인해 NULL/추정/실청구를 구분해야 합니다. 통화를 섞거나 실제 청구 금액을 estimated_cost로 대신하지 않습니다. 사용량 원장/영수증에는 프롬프트·응답 본문이 없습니다.

## 검증과 적용 범위

합성 provider를 기존 회차 생성기·기업 전망 생성기에 주입하고 실제 Python→Java JSONL→PostgreSQL 저장을 검증했습니다. 대표 통합 시나리오는 **도메인 시도 5건, 합성 live 시도 7건(그중 unknown 1), replay 4건, save_only 1건, DISTINCT 수선 재시도 1건, actual_cost 전부 NULL**입니다. 동일 결과 재실행과 4개 영수증 재수집으로 live 행은 늘지 않았습니다. 전송 불명확이 있으므로 이 모집단 전체의 modelCalls 합계는 7로 단정하지 않고 NULL입니다. 실제 외부 모델 호출은 0회입니다.

DB 검사는 멱등 키·입력 결속, 동시 claim 한 명, 임대 만료/이전 worker 차단/지연 비용 보존, 부분 토큰/unknown→동일 행 조정, 중복 영수증 거부, 재생·저장 복구 제외, 수선 단위, 보류, 비용 근거·본문 제외, FK·기능 귀속, 기존 발행본 불변 전망, 발행 원자성, 시계 차·KST 시작일을 포함합니다. CI와 전체 회귀 결과는 PR 검증 항목을 확인해 주세요.

마이그레이션 후 명시적 recorded producer 경로로 생성해야 새 기록이 생깁니다. 현재 운영 스케줄러 자동 연결은 없으며 CLI는 검증 결과 파일까지 생성하고 자동 발행하지 않습니다. 향후 운영 발행 worker는 활성 generation 시도에서 BriefingUsageLedger.publish를 사용해야 합니다. 이 PR을 병합·배포하거나 기존 DB에 적용하지 않았습니다. #134 조회 API를 이 컬럼·상태 기준으로 연결한 뒤 합성 데이터 집계를 함께 대조해 주세요.
