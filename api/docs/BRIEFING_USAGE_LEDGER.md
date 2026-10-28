# 브리핑 producer 사용량 원장 (FS068 / #134)

기존 회차 생성기와 기업 전망 생성기를 PostgreSQL `briefing_attempts` 및 `ai_executions`에 연결하는 명시적 실행 경로다. `scripts/briefing_usage_run.py`가 기존 프롬프트·독립 검증기를 호출하고, Java `BriefingUsageCommand` JSONL 파이프가 DB 쓰기를 담당한다. 기본 실행은 오프라인 계획만 반환한다. 운영 스케줄러 설치, 관리자 조회 API, 기존 브리핑 재생 수입기의 과거 자료 소급 적재는 포함하지 않는다.

## 저장 위치와 적용

- 마이그레이션: `api/src/main/resources/db/migration/V20261028113000__record_briefing_attempts_and_usage.sql`.
- 저장 경계: `api/src/main/java/com/zoop/briefing/usage/BriefingUsageLedger.java`.
- 시도: PostgreSQL의 `briefing_attempts`; 실행: 같은 DB/schema의 `ai_executions`. `briefing_attempt_id`는 FK다.
- 내용 없는 영수증: `BRIEFING_USAGE_ARTIFACT_ROOT/briefing_usage/<sha256>.json`; `artifacts.kind=ai_call_receipt`, `storage_uri=artifact-root:briefing_usage/...`로 등록한다.
- producer의 기존 응답·산출물은 별도의 비공개 `--output`에 남는다. `output/usage/`의 소유권·복구 영수증은 0600이고 디렉터리는 0700이다. 원장과 영수증에는 프롬프트, 응답 본문, 원시 오류 메시지, API 키를 복사하지 않는다.

Flyway는 기존 배포 절차로 먼저 적용한다. 파이프는 스키마를 임의 변경하지 않는다. 기존 non-NULL `ai_executions.briefing_attempt_id`의 참조 시도가 없으면 FK 추가가 실패하므로 적용 전 확인하고 원래 시도 증거로 조정한다. 가짜 시도나 호출을 만들지 않는다. 기존 활성 회차가 있다면 중지·소유권 이관 절차를 완료한 뒤 새 producer를 활성화한다. 이 PR은 실제 운영 DB에 적용하지 않았다. 롤백은 producer 진입을 중지하되 비용·시도 이력을 보존하고, 적용한 migration을 삭제하거나 과거 호출을 재발행하지 않는다.

## 실제 실행 경로

JDK 21과 기존 Python 표준 라이브러리를 사용한다. 기존 API jar를 빌드한 후 다음 JSON 배열을 비공개 `ledger-command.json`에 저장한다. jar 경로는 실행 환경의 절대 경로를 사용한다.

```json
["java","-Dloader.main=com.zoop.briefing.usage.BriefingUsageCommand","-cp","/absolute/path/api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar","org.springframework.boot.loader.launch.PropertiesLauncher","--stdio"]
```

DB 접속은 `DB_URL`(JDBC PostgreSQL), `DB_USERNAME`, `DB_PASSWORD`, 영수증 루트는 `BRIEFING_USAGE_ARTIFACT_ROOT` 환경변수로 전달한다. 자격 증명을 명령 배열이나 job 파일에 넣지 않는다. 임대는 기본 120초이며 `BRIEFING_USAGE_LEASE_SECONDS`로 30~900초를 지정할 수 있다. Python은 30초 간격으로 heartbeat한다. 파이프 응답 상한은 60초이며 기록 실패 뒤 다음 모델 전송을 중단한다.

job 파일의 모든 필드는 다음과 같으며 추가 필드는 거부한다. 입력 파일은 job과 같은 디렉터리 아래에 두고 실제 바이트 SHA-256을 기입한다. 모델 실행 승인은 운영자가 별도로 확보해야 하며 `authorizationRef`는 그 승인 참조다.

```json
{
  "schemaVersion":"briefing-recorded-producer-v1",
  "operation":"generation",
  "round":{"id":"example-round","date":"2026-10-28","edition":"morning","scheduledAt":"2026-10-28T00:20:00Z","windowFrom":null,"windowTo":"2026-10-28T00:20:00Z"},
  "requestKey":"example-generation-1",
  "trigger":"scheduler",
  "adminId":null,
  "inputArtifactId":null,
  "inputFile":"frozen-input.json",
  "inputSha256":"<actual SHA-256 of frozen-input.json>",
  "maxCalls":4,
  "authorizationRef":"<operator authorization reference>"
}
```

`generation` 입력은 `{selected, context, maxRepairs}`다. `context`는 기존 `briefing_round_simulation`의 고정 문맥 `{context, contextSha256, ...}`이며 회차 날짜·edition·window와 digest를 검사한다. `maxRepairs`는 0 또는 1이다. `outlook` 입력은 기존 `briefing_company_outlook.assess`의 고정 문맥이고 roundId/date/edition/cutoff가 job과 같아야 한다. maxCalls는 0~16이며 기존 write-ahead 호출 예산도 적용한다. 기사 수집·이슈 선정·권리 허가는 이 원장이 새로 부여하지 않는다. 기존 검증·공개 경계를 거친 입력만 전달한다.

```sh
# 계획 확인: DB/모델 호출 없음
python3 scripts/briefing_usage_run.py --job /private/job/job.json --output /private/job/output

# 운영자가 승인한 실제 실행에만 사용
python3 scripts/briefing_usage_run.py --job /private/job/job.json --output /private/job/output \
  --execute --ledger-command-file /private/ledger-command.json --key-file /private/provider-key
```

같은 job·output의 완료 결과는 `ledger-finished.json`으로 확인해 그대로 재사용한다. 모델을 다시 생성하려면 새 requestKey와 output을 사용한다. 같은 키의 입력/purpose/관리자/회차 변경은 충돌로 거부한다. 별도 output이 실행 중인 시도를 인계받지 못하며, 같은 output도 `.owner.lock`으로 중복 실행을 막는다. 강제 종료로 남은 lock은 작업자가 실제 종료했는지 확인한 뒤 운영자가 처리해야 한다.

## 시도 상태·단계

| 값 | 의미 |
| --- | --- |
| queued | 스키마상 접수 대기; 현재 명시적 producer는 claim 시 running으로 시작 |
| running | 실행권 획득, 생성 또는 저장 처리 중 |
| verifying | 검증 단계 실행 중; 재생성 단계에 들어가면 running으로 복귀 |
| completed | producer 처리가 끝남. stages.outcome=available 또는 withheld로 구분 |
| failed | producer 오류 또는 임대 만료; failure_reason과 stages.failureStage 보존 |
| cancelled | 명시적 중단(현재 CLI KeyboardInterrupt) |

`started_at`은 DB에서 claim한 시각, `finished_at`은 DB에서 종료한 시각이다. historical 회차를 지금 실행해도 실제 시각을 기록한다. `stages`는 purpose/inputSha256, 실제 생성기의 단계명(예: round_generation/round_verification, company_outlook_generation/company_outlook_verification), status/feature/aiJobId, 최종 outcome/failureStage를 보존한다. `stages.outlook.requestedAt/outcome`은 전망 단계 접수 모집단이며 호출마다 추가하지 않는다. 중간 단계명은 기존 생성기의 실제 이름을 따른다.

claim은 회차 행 잠금·새 owner_token·증가 attempt_no·임대 및 시도 INSERT를 한 트랜잭션으로 처리한다. partial UNIQUE가 회차당 활성 시도를 하나로 제한한다. provider 전송 중 DB 잠금은 유지하지 않는다. 임대 회수는 기존 시도를 failed/lease_expired로 끝내고 미완료 AI 행을 unknown으로 남긴 후 새 시도를 만든다. 만료된 작업자는 heartbeat/새 호출/발행을 못 하지만 자기 영수증을 같은 AI 행에 늦게 반영할 수 있다. 종료 시도의 신원·단계 이력은 변경하지 않는다.

모델 호출 전 준비 중 오류는 `failureStage=prepare`로 남긴다. 모델 전송 예약이 없으면 AI 호출 행을 만들지 않는다.

## 모델 관측과 복구

전송 직전 `model_start`를 독립 커밋하고 실제 응답/오류 후 `model_finish`를 독립 커밋한다. job ID는 `briefing-direct:<attemptId>`, AI attempt ID는 기존 제공자 요청 바이트의 SHA-256이다. 직접 호출의 앱 소유 ID이며 AI 서비스의 ID나 제공자 응답 ID가 아니다. DB의 UNIQUE(job,attempt)와 결정적 실행 ID로 중복 영수증을 막는다. 이미 시작된 호출을 발견하면 무조건 재전송하지 않고 운영자 조정 대상으로 중단한다.

| 실행 모드·상태 | 기록과 집계 |
| --- | --- |
| live / running | 전송 예약. transmission_confirmed와 사용량은 아직 NULL |
| live / succeeded | 제공자 completed 응답. 보고된 model·입력/출력 토큰을 각각 보존 |
| live / failed·cancelled | 제공자 실패·중단 응답. 보고된 사용량도 보존 |
| live / unknown | 전송 예외, 결과 불명확 또는 소유 작업자 유실. 전송/토큰/과금을 추정하지 않음 |
| replay | 기존 검증된 호출 결과의 캐시 재사용. AI ID·토큰·비용·재시도 없음 |
| save_only | 모델 재호출 없는 결과 저장 복구. AI ID·토큰·비용·재시도 없음 |

한쪽 토큰만 보고되면 알려진 쪽은 남기고 다른 쪽만 NULL이다. provider 모델명이 없으면 전송 전 요청 모델명을 보존한다. reasoning effort는 실제 요청 값(현 생성기는 low)을 기록하고 미지정은 NULL로 둔다. 응답 시각이 DB 시작보다 최대 60초 빠른 경우 원래 값을 영수증에 보존하고 행의 finished_at은 NULL로 남겨 지연 시간을 만들지 않는다. 60초보다 큰 시계 오차는 영수증 저장을 거부하므로 운영자 조정이 필요하다.

provider 응답은 기존 비공개 calls 파일에, 내용 없는 model_finish 명령은 usage/*.receipt.json에 먼저 보존한다. DB 응답만 유실됐으면 다음 명령으로 **동일 원본 시도**에 재수집한다. claim/model_start/finish/모델 전송을 하지 않는다. 최종 영수증의 다른 바이트는 거부하며 unknown 관측은 나중에 확인된 영수증으로 같은 행에서 조정한다.

```sh
python3 scripts/briefing_usage_reconcile.py --usage-directory /private/job/output/usage \
  --ledger-command-file /private/ledger-command.json
```

이미 저장된 `result.json`은 있지만 종료 확인만 없으면 동일 job을 재실행해 모델 없이 종료를 복구한다. 다른 저장 결과를 복원할 때는 operation을 `save_only_generation` 또는 `save_only_outlook`으로 하고 inputFile에 기존 `briefing-recorded-result-v1` 봉투를 지정한다. roundId/purpose/outcome를 검증한다. 이때 새 저장 시도는 생기지만 실제 호출·재시도는 0이다. pending 모델 결과를 임의 성공으로 바꾸거나 본문만 보고 새 영수증을 만들지 않는다.

## 발행 연결 경계

`BriefingUsageLedger.publish(attemptId, ownerToken, validatedPublisher)`는 현재 generation 소유권·임대·모델 미해결 여부를 검사하고, 기존 검증된 발행 저장을 같은 트랜잭션 안에서 실행한다. callback은 같은 DataSource/트랜잭션을 사용해 발행 payload·published_at을 저장하고 회차 token/lease를 해제해야 한다. 예외가 나면 발행과 시도 종료가 함께 롤백된다. DB publication fence도 만료 토큰의 UPDATE 발행을 거부한다.

현 main에는 자동 운영 발행 worker가 없으며, 새 CLI는 검증된 결과 파일까지 생성한다. CLI의 generation available 종료는 회차를 scheduled로 돌려 발행 전 상태로 남기고 임대를 해제한다. completed 시도를 publish()에 재사용하지 않는다. 향후 worker가 생성과 발행을 한 시도로 처리하려면 `UsageSession`의 자동 finish 이전, 활성 시도 안에서 위 publisher 경계를 호출해야 한다. 기존 개발용 replay importer는 변경하지 않았고 live 사용량을 새로 만들지 않는다. `completed`를 발행 성공으로 해석하지 말고 `published_at`을 읽는다.

## #134 집계 인계

요청 수와 호출 수, 보류와 모델 실패를 섞지 않는다. [팀원 전달 문서](../../docs/development/briefing-usage-handoff.md)에 읽기 SQL 예시·검증 결과를 정리했다. 이 producer는 실제 청구 자료를 받지 않으므로 `actual_cost=NULL`만 기록한다. 추정치는 선택적으로 `UsageSession(estimate={currency,priceVersion,inputPerMillion,outputPerMillion})`에 승인된 가격 근거를 주었을 때만 계산하며 `estimated_cost/currency/cost_basis`에 분리 저장한다. 기본 CLI는 가격을 가정하지 않는다.

## 합성 검증 재현

전용 PostgreSQL 테스트 DB의 DB_*를 지정한다. 각 usage 테스트는 독립 UUID schema를 만들고 자기 schema만 삭제한다. 외부 모델 호출 없이 기존 생성기와 실제 Java 파이프·Flyway·JDBC를 실행한다.

```sh
./api/gradlew -p api briefingIntegrationTest --tests '*BriefingUsagePostgresTest'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -p test_briefing_usage.py -v
```
