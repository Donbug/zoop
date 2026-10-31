# ai/service — 내부 HTTP transport (S1 분석, S2 추출, S3 관계 job, 챗봇 모델 단계, 읽기 전용 그래프·handoff)

앱 백엔드가 S1 분석(`document-summary`, `document-sentiment`, `semantic-verification`, `briefing-outlook`, 계약 `zoop-ai-s1-1`)을 제출·조회·취소·복구하는 **내부 전용 HTTP 서비스**입니다. 같은 프로세스가 별도 리소스 가족으로 S2 이벤트·토픽 후보 job(`/internal/v1/extraction-jobs`, 기본 꺼짐)과 S3 관계·영향 후보 job(`/internal/v1/relation-jobs`, 기본 꺼짐)도 노출합니다. FastAPI/uvicorn이며 **설치된 `zoop-ai`(S2는 `zoop-ai-extract`, S3는 `zoop-ai-relation`) CLI만** 호출합니다. `zoop_ai`·`zoop_ai_pipeline`·BFF를 import하지 않고 worker의 `worker.sqlite3`와 pipeline의 `extraction.sqlite3`·`relation.sqlite3`·`ingestion.sqlite3`를 열지 않습니다. 런타임 원장이 작업 상태의 유일한 출처이고 이 서비스는 소유자·멱등·고정된 승인 신원·dispatch 상태만 별도 `service.sqlite3`(S1), `extraction-jobs.sqlite3`(S2), `relation-jobs.sqlite3`(S3)에 둡니다.

> **로컬 준비 상태입니다.** 배포·보안 그룹·TLS 프록시는 확인되지 않았고 승인되지 않았습니다. 원격 CI는 `5cf208e`의 [실행 38226220631](https://github.com/Donbug/zoop/actions/runs/38226220631)에서 8개 작업이 모두 통과했고 실제 Java 클라이언트 → 이 서비스 → 설치된 `zoop-ai` replay 종단 시험을 포함합니다. Spring 전송 클라이언트(`api/src/main/java/com/zoop/ai`)가 이 HTTP를 소비하고, S1 문서 요약·기업 판정은 operator 전용 비웹 실행([문서 분석](../../api/docs/DOCUMENT_ANALYSIS.md))이 결과를 앱 PostgreSQL에 저장합니다(로컬 구현·검증). 공개 인증, 분석을 읽는 공개 경로, S2·S3·`briefing-outlook` 결과의 앱 import, 배포는 아직 없습니다. 실제 모델 호출, 외부 뉴스, 실제 토큰은 쓰지 않았습니다. **S2 extraction job 라우트와 S3 relation job 라우트(아래 별도 절)는 이후 추가했고 원격 CI에서 실행된 결과는 아직 관측하지 않았습니다. 이 두 가족도 Spring 전송 클라이언트(`ExtractionClient`·`RelationClient`)가 로컬에서 소비하며 실제 서비스·설치된 pipeline replay 종단 gate(`api/scripts/ai_pipeline_gate.py`)로 검증했지만, S2·S3 결과의 앱 DB 저장·import와 사용자 격리·공개 endpoint는 없습니다.** S2-1 수집(`zoop-ai-ingest`)은 운영자 파일 입력이므로 HTTP로 열지 않습니다. S2-2 추출(`zoop-ai-extract`)은 호출자가 스냅샷·카탈로그·fixture를 보낼 수 없는 **서버 사전 승인 요청** 참조 모델로만 엽니다.

> **경계.** 이 서비스는 pipeline의 비공개 Neo4j 버전 projection(`zoop-ai-graph`, FS080 일부)을 **읽기 전용 두 라우트**(`/internal/v1/graph-versions`, 아래 별도 절)로만 감싸고, 별개로 AI handoff bundle의 **읽기 전용 두 라우트**(`/internal/v1/graph-handoffs`, 아래 절)를 제공합니다. 버전 생성(`init`·`freeze`·`project`·`recover`)·게시·활성화·FS081 철회·목록·호출자 Cypher는 없고, Neo4j write 자격과 쓰기 명령은 pipeline 운영자 프로세스만 갖습니다. 공개 API·Spring 클라이언트·활성 포인터는 없습니다([pipeline README](../pipeline/README.md), [AI 실행 계약](../../docs/design/ai-system.md), [백엔드 인수 문서](../../api/docs/GRAPH_READ_HANDOFF.md)).

> **관측 export(#387의 세 번째 작업만).** `POST /internal/v1/observations/export`는 설치된 `zoop-ai-ingest export --require-store`를 동기 호출합니다. 현재 권한이 허용하는 문서 본문을 200 응답에 포함하며, 수집 실행·회차 job·freeze·스케줄러는 추가하지 않습니다. 설정과 운영 경계는 아래 「관측 export」 절을 따릅니다.

```bash
make service-install           # uv sync --project ai/service --frozen --group dev (공개 의존성만, 토큰 없음)
make service-test              # 실제 uvicorn + 설치된 zoop-ai + authored replay (4-worker 병렬, 느린 테스트 30개 시간 출력)
make service-smoke             # 실제 프로세스 smoke (replay 4종 + recover + loopback cancel/restart)
make service-openapi-check     # docs/api/internal-ai-openapi.{json,yaml} 생성 drift
make service-pipeline-test     # S2 extraction + S3 relation job: 실제 uvicorn + 설치된 zoop-ai-extract·zoop-ai-relation + 새 운영자 세계 (make pipeline-install 필요, 없으면 실패)
make service-pipeline-smoke    # 같은 조건의 실제 프로세스 smoke (S2 제출·조회·승인/fixture 회전·모호 child·재시작 → 명시적 S3 허용 → S3, S3 조회·격리·철회·모호 child·재시작, 검수 allow=최종 승인·reject·충돌·크래시 복구·이전 원장 보존)
make service-handoff-smoke     # 읽기 전용 handoff 두 route: 실제 uvicorn + 설치된 zoop-ai-handoff + S3 job 두 개 세계(Neo4j 불필요, pipeline 설치 없으면 실패)
make service-build             # wheel/sdist
ai/service/.venv/bin/python -m zoop_ai_service.main   # 또는 zoop-ai-service (아래 환경 설정 필요)
```

의존성은 BFF·worker lock에 이미 있던 정확한 버전(`fastapi 0.141.1`, `uvicorn 0.54.0`, `pydantic 2.13.5`, 테스트 `httpx 0.28.1`·`pytest 9.1.1`)만 사용합니다. `zoop-ai-worker`는 **테스트 전용**으로 설치되어 실제 `zoop-ai` 콘솔 명령과 공개 fixture를 제공합니다.

## 계약

기계 판독 계약은 [`docs/api/internal-ai-openapi.json`](../../docs/api/internal-ai-openapi.json)(같은 문서의 [YAML](../../docs/api/internal-ai-openapi.yaml))입니다. 서비스의 라우트·모델에서 `ai/service/scripts/export_openapi.py`가 생성하며 요청/복구 예시를 포함합니다. `Submit`/`JobResult`는 [`ai-contract.schema.json`](../../docs/api/ai-contract.schema.json)을 **참조**할 뿐 복제하지 않습니다. 공개 `docs/api/openapi.yaml`(`/api/v1`)은 바꾸지 않았습니다.

| 메서드·경로 | scope | 성공 | 의미 |
|---|---|---|---|
| `POST /internal/v1/analysis-jobs` | `analysis.submit` | 202 새로 접수 / 200 멱등 재전송 | `Idempotency-Key`는 필수이며 `body.jobId`와 같아야 한다. |
| `GET /internal/v1/analysis-jobs/{jobId}` | `analysis.read` | 200 `JobStatus` | 요청마다 `zoop-ai get`을 실행해 읽은 실제 상태. 내용 필드 없음. |
| `GET …/{jobId}/result` | `analysis.read` | 200 `ResultEnvelope` | 서버의 **현재** grant가 허용할 때만 `job`(=`get` 출력), 아니면 `delivery.state=withheld`. |
| `POST …/{jobId}/cancel` | `analysis.cancel` | 200 `JobStatus` | 멱등. 진행 중 child는 죽이지 않는다. |
| `POST …/{jobId}/recover` | `analysis.recover` | 202 enqueue / 200 coalesced | 명시적 재-dispatch. 유일한 미송신 단계 재개 경로. |

`next`는 순수 규칙입니다: dispatch가 pending/in_flight이면 `wait` → ready `fetch_result` → reconciling `operator_reconcile` → cancelled 또는 `resumeMode=none`인 failed `none` → 나머지 `recover`. 내부 `ready`는 공개 `completed`가 아닙니다. 앱 import와 현재 권한 재확인이 먼저입니다. 오류 envelope는 코드·`retryable`·`requestId`·`runtimeCode`·`field`만 갖고 message/stack/stderr/argv/경로가 없습니다.

## 설정(환경 변수, 시작 때 한 번 읽고 실패 시 닫힘)

| 변수 | 규칙 |
|---|---|
| `ZOOP_AI_SERVICE_PRINCIPALS` | 필수. `[{"principal":"^[a-z][a-z0-9-]{0,62}$","tokenSha256":["<64 hex>",…1–2개],"scopes":[…]}]`. **토큰 평문이 아니라 SHA-256 digest만.** principal·digest 중복과 알 수 없는 키를 거부한다. |
| `ZOOP_AI_SERVICE_STATE_DIR` | 필수 절대 경로(symlink 구성요소 없음, 0700). `service.lock`, `service.sqlite3`, `transport/`. worker·`ZOOP_STATE_DIR`과 겹치면 거부. |
| `ZOOP_AI_WORKER_STATE_DIR` | 필수. 런타임 원장 위치. 서비스는 `--state-dir`로만 넘기며 `service.sqlite3`에 이 경로의 해시를 묶어 **다른 원장으로 바뀌면 시작을 거부**한다. |
| `ZOOP_AI_SERVICE_WORKER_COMMAND` | 필수. 설치된 `zoop-ai`의 절대 경로. |
| `ZOOP_AI_SERVICE_GRANTS` | 필수. 운영자 소유 현재 grant registry. 제출·실행 때 `--grants`로, 결과 전달 때 서비스가 직접 다시 읽는다. |
| `ZOOP_AI_SERVICE_REPLAY` | 선택. authored replay fixture. 없으면 `mode=replay`는 409 `execution_unavailable`. |
| `ZOOP_AI_SERVICE_PORT` | 선택, 기본 8797(1024–65535). **호스트는 항상 `127.0.0.1`**이며 설정이 없다. |
| live 통과 | `ZOOP_AI_LIVE_ENABLED=1`과 양수 `ZOOP_AI_GLOBAL_MAX_CALLS`가 **모두 있을 때만** live가 열리고, 그렇지 않으면 `ZOOP_AI_LIVE_ENABLED/GLOBAL_MAX_CALLS/PROVIDER/BASE_URL/API_KEY`와 네이티브 검증용 `ZOOP_AI_VERIFY_PROVIDER`·`TYPESAFE_API_KEY/BASE_URL/VALIDATION_MODEL`은 child에 전달되지 않는다(Jev key는 live가 열린 S1 child에만 가고 S2/S3/그래프 child에는 가지 않는다). stage별 `ZOOP_AI_{DOCUMENT_SUMMARY,DOCUMENT_SENTIMENT,VERIFY,BRIEFING_OUTLOOK}_{MODEL,REASONING_EFFORT}`는 입력 digest에 영향을 주므로 항상 통과한다. |

잘못된 설정은 종료 코드 78과 `{"error":"service_config_invalid","field":"<VAR>","reason":"<code>"}`만 출력합니다(값 출력 없음). child 환경은 `PATH=/usr/bin:/bin`, `LANG=C.UTF-8`, `PYTHON*` 몇 개와 위 통과 값뿐입니다. 요청이 경로·명령·환경·provider URL·모델·fixture·grant registry를 고를 수는 없습니다.

### 관측 export(선택, 기본 꺼짐)

`POST /internal/v1/observations/export`에는 `observation.read`가 필요합니다. 이 scope는 운영자가 지정한 내부 문서 수입 principal에만 명시적으로 부여하며, 기존 principal에 자동으로 추가하지 않습니다. 저장소에 관측별 소유자 정보가 없으므로 이 scope는 **서버가 설정한 공용 ingestion 저장소 전체의 정확한 관측 조회 권한**입니다. 다른 principal에도 운영자가 같은 scope를 명시적으로 부여하면 동일한 현재 source 권리 검사를 거쳐 조회할 수 있습니다. Scope가 없는 인증된 principal은 403, 알 수 없는 토큰은 401입니다.

| 설정 | 규칙 |
|---|---|
| `ZOOP_AI_SERVICE_INGESTION_COMMAND` | 설치된 `zoop-ai-ingest` 실행 파일의 절대 경로입니다. 이 설정이 관측 export 그룹을 켭니다. |
| `ZOOP_AI_INGESTION_STATE_DIR` | 기존 ingestion 저장소의 절대 경로입니다. 새 저장소를 만들거나 복구하지 않습니다. |
| `ZOOP_AI_SERVICE_SOURCES` | 현재 운영자 source registry 파일입니다. CLI가 요청마다 다시 읽습니다. |
| `ZOOP_STATE_DIR` | 기존 pipeline 소유권 검사에 필요한 앱 상태 경로입니다. 서비스·worker·ingestion 상태 경로와 겹칠 수 없습니다. |

기존 서비스 필수 설정도 필요합니다. S2·S3와 함께 사용할 때 ingestion·sources 설정을 그대로 공유하며, graph·handoff가 함께 설정되어 있으면 같은 ingestion·registry를 가리켜야 합니다. Command 설정이 없으면 인증 후 503 `execution_unavailable`, command만 있고 필수 설정이 빠졌으면 시작을 거부합니다. 수집 설정만으로 S2·S3 실행 그룹을 켜지 않습니다.

요청은 닫힌 native selector입니다. `schemaVersion`은 필수이며 값은 `zoop-ingestion-s2-1`입니다. 나머지 필드는 정확히 `roundId`, `sourceId`, `page`, `ordinal`, `documentId`, `rawVersion`, `documentVersion`입니다. `observationId`, 클라이언트 경로·CLI 인자·registry·`requireStore` 옵션과 query parameter는 받지 않습니다. `Idempotency-Key`는 필요하지 않고 권한이나 캐시 신원을 만들지 않습니다.

서버는 항상 `export --require-store`만 실행합니다. CLI가 현재 `read`·`store`·`quote-display`, 고정된 source 설정과 관측 버전을 검사하며, 서비스는 응답의 selector 일치, 본문의 `sourceHash`, document version과 locator hash를 검증합니다. 성공 응답은 **CLI의 정확한 JSON**이며 `document.text`, locator와 선택적 publisher·language·collection 필드를 보존합니다. `language`는 native가 선언한 2~35자 문자열만 받고, 미지정 필드는 추가하지 않습니다. 별도 wrapper나 상태 조회 경로는 없습니다. 한 요청은 관측 하나를 동기 200으로 돌려주며, 묶음 조회와 비동기(202) 전달은 #407에서 정할 열린 항목입니다. 요청은 2,000,000바이트, stdout·응답은 16 MiB, child 실행은 45초, 동시 export는 2개로 제한합니다. 모든 응답에 `Cache-Control: no-store`가 붙습니다.

| 결과 | HTTP |
|---|---|
| 허용된 native export | 200 |
| `source_unauthorized` | 403 |
| `round_not_found`, `observation_not_found`, `document_version_not_in_round` | 404 |
| `registry_changed`, `scope_configuration_conflict`, `preparation_profile_unbound` | 409 |
| writer lock의 `ingestion_busy` | 503 `runtime_busy`, `runtimeCode=ingestion_busy`, `Retry-After: 2` |
| hot WAL·손상된 설정 등 native 상태 거부 | 503 `service_configuration_invalid`와 안전한 `runtimeCode` |
| stdout 계약·본문 hash·응답 신원 불일치 | 500 `runtime_contract_mismatch` 또는 `runtime_binding_mismatch` |

오류와 로그에는 본문·운영자 경로·키·raw stderr를 넣지 않습니다. 요청마다 권리를 새로 확인하며, 캐시·ingestion 쓰기·자동 재시도·복구·job 등록은 하지 않습니다. 권리 검사와 HTTP 전달은 별개 시점이므로 이미 전달한 본문을 회수하거나 원자적 철회를 보장하지 않습니다. 이 조회는 모델 송신·grant 발급·게시·활성화를 허가하지 않습니다.

**기존 온라인 profile에 scope만 추가해 재시작하면 안 됩니다.** Plan authority binding은 모든 principal 이름과 scope를 고정하므로 `observation.read` 추가도 기존 binding을 바꾸며 시작이 거부됩니다. 이 변경은 기존 profile·binding·quota·영수증을 수정하거나 초기화하지 않습니다. 운영자는 기존 이력을 보존한 별도 읽기 전용 서비스 profile을 사용하거나, 별도 승인된 migration 절차를 준비해야 합니다. 새 profile은 기존 실행 예산이나 admission 한도를 초기화하는 수단이 아닙니다.

배포에는 pipeline CLI 설치, 내구성 있는 동일 ingestion 저장소·현재 registry, 명시적 importer scope와 기존 loopback/TLS proxy 구성이 필요합니다. 기본 개발 컨테이너는 pipeline 설치를 포함하지 않습니다. 앱의 `IngestionExporter.export(Observation)`와 selector·응답은 호환되지만 기존 `ProcessIngestionExporter`는 여전히 로컬 CLI를 호출하며, HTTP 전송 구현은 앱의 별도 작업입니다. 비공개 처리 권한·retained provenance를 공개 권한으로 바꾸지 않으며, 공개 OpenAPI·AWS 설정은 그대로입니다.

오프라인 실제 HTTP→CLI smoke: `ai/service/.venv/bin/python ai/service/scripts/observation_export_smoke.py`. 합성 HTML로 만든 native 저장소만 사용하며 네트워크는 loopback으로 제한하고 `.env` 읽기를 거부합니다. 설치된 pipeline 환경이 필요하며 의존성을 자동으로 설치하지 않습니다.

### 온라인 plan admission(선택, 기본 꺼짐)

`ZOOP_AI_SERVICE_PLAN_ADMISSION=1`과 운영자 소유 절대 디렉터리 `ZOOP_AI_SERVICE_PLAN_ROOT`를 함께 설정하면, 실행 중인 서비스가 이미 생성된 정확한 S2 plan을 받아 S2 승인과 단위별 S3 ID를 한 트랜잭션으로 등록합니다. S2·S3 실행 설정 그룹이 모두 필요하지만 온라인 모드에서는 `ZOOP_AI_SERVICE_EXTRACTION_APPROVALS`와 `ZOOP_AI_SERVICE_RELATION_UPSTREAMS`를 읽거나 요구하지 않습니다. 두 설정이 없으면 기존 수동 파일 모드를 유지하며, 일부만 설정하면 시작을 거부합니다.

권한의 유일한 저장소는 서비스 상태 디렉터리의 `plan-authority.sqlite3`(스키마 `zoop-ai-plan-authority-1`)입니다. 현재 정책과 불변 정책 이력, 운영자 CAS 작업 영수증, 누적 사용량, admission manifest, 짝을 이룬 S2·S3 권한을 함께 보관합니다. 새 저장소의 정책 revision은 0이고 정책은 없습니다. 정책 파일 자동 로드나 기본 허용 정책은 없으며, 앱의 admission 요청은 정책을 설치하지 못합니다.

| 경로 | scope | 동작 |
|---|---|---|
| `POST /internal/v1/plan-admissions` | `plan.admit` | `planId`·`planDigest`만 받습니다. `Idempotency-Key=planId`가 필수이며 최초 등록은 201, 정확한 재요청은 200입니다. |
| `GET /internal/v1/plan-admissions/{planId}?planDigest=…` | `plan.read` | 저장된 불변 manifest와 현재 admission-policy 권한 상태를 반환합니다. 목록·검색은 없습니다. |
| `GET /internal/v1/plan-admission-policy` | `plan.policy` | 현재 revision·정책 digest·정책·상태·누적 사용량과 정확한 ETag를 반환합니다. |
| `PUT /internal/v1/plan-admission-policy` | `plan.policy` | 별도 운영자가 닫힌 정책 문서, 작업 `Idempotency-Key`, 정확한 `If-Match`로 정책을 변경합니다. 앱 실행 principal에는 이 scope를 함께 부여할 수 없습니다. |

정책은 principal, 모든 입력·snapshot 문서의 source ID, synthetic/actual 구분, 만료 시각, prompt·catalogue·snapshot·topic과 replay fixture 또는 공개 live runtime 신원을 정확히 제한합니다. `maxPlans`·`maxUnits`는 모든 revision에 걸친 누적 admission 수와 S2 단위 수입니다. 취소·실패·만료·정책 변경은 사용량을 환불하지 않습니다. **이 수량 제한은 provider 호출 수나 금액 예산이 아닙니다.** 기존 source rights, live gate와 송신 시점의 독립적인 dollar/call cap이 그대로 필요합니다.

정책 PUT의 같은 운영자·키·문서 digest·If-Match 재요청은 이후 정책이 바뀌었어도 원래 영수증을 반환합니다. 같은 키로 문서나 If-Match를 바꾸면 409 `idempotency_conflict`, 새로운 작업의 오래된 If-Match는 412 `policy_conflict`입니다. 같은 문서를 새 작업으로 다시 제출해도 revision·만료·사용량은 갱신하지 않습니다. 실제 정책 변경은 이전 admission을 모두 영구 비활성화합니다. 만료를 한 번 관측하면 해당 revision과 admission은 시계를 되돌리거나 예전 정책 바이트를 복원해도 살아나지 않습니다.

운영자 정책 작업의 신원과 과거 영수증은 키를 퇴출하거나 재사용하지 않고 계속 보존합니다. Admission 수량 제한 때문에 정책 비활성화나 교체를 막지 않으며, 개별 요청 크기 제한과 admission 저장량 제한은 별도로 유지합니다.

Admission은 `<plan-root>/<planId>`의 네 plan 파일만 읽고 receipt를 내부에서 고정한 뒤, 수동 installer와 공유하는 제한된 실제 `zoop-ai-extract verify-plan` subprocess로 전체 내용을 재구성·검증합니다. 자격 증명·송신 cap은 verifier에 전달하지 않습니다. 검증은 쓰기 트랜잭션 밖에서 수행하며, commit 직전에 정책 revision·만료·설정/디렉터리 신원·plan/registry/fixture pin·충돌·quota를 다시 확인합니다. 검증 중 정책이 바뀌면 409 `policy_changed`로 거부하며, 다른 revision으로 자동 재평가하지 않습니다. Admission과 조회는 실행을 enqueue하거나 dispatch하지 않습니다.

반환 manifest의 각 S2 단위에는 정확히 하나의 결정적 S3 ID가 들어갑니다. S3는 그 ID·provenance·upstream·runtime만 허용하며, 같은 admission origin으로 서비스가 수락한 S2 row가 먼저 있어야 합니다. 운영자가 pipeline에 따로 만든 S2 job은 채택하지 않습니다. S2·S3 예약과 dispatch claim은 불변 `authority_ref`를 보관하며, 제출 후 gate 대기 직후·replay를 포함한 모든 dispatch·명시적 recover·내용 전달·S3 검수 시 현재 권한을 다시 확인합니다. 내용 없는 상태·안전한 취소·과거 작업 영수증 조회는 권한을 갱신하지 않습니다. 이미 실행 중인 child를 정책 만료 순간에 회수하거나 이미 전달한 내용을 취소하는 기능은 아닙니다.

서비스는 process lock을 먼저 잡고, 모든 서비스 원장 복구·중단 처리보다 앞서 모드와 저장소를 확인합니다. 사용 중인 수동 profile을 온라인으로 전환하거나 온라인 flag를 제거해 수동 권한으로 바꾸면 `authority_mode_mismatch`로 시작을 거부합니다. **별도의 서비스 상태 profile을 사용해야 합니다.** 온라인 marker가 있는데 authority DB나 필수 control DB가 사라졌거나 손상되면 닫힌 상태로 거부하며 quota·이력을 재생성하지 않습니다. 온라인 상태에서 offline installer를 실행할 수도 없습니다. S2 서비스 원장은 `zoop-ai-extraction-jobs-ledger-3`, S3는 `zoop-ai-relation-jobs-ledger-4`로 전진하며, 기존 수동 row의 origin은 null로 남고 온라인 origin으로 재해석하지 않습니다.

온라인 profile의 최초 lock 파일은 새 profile에서만 생성합니다. 이후 시작에서는 기존 `service.lock`이 반드시 있어야 하며, authority binding에 원래 lock의 device/inode를 고정합니다. 파일이 사라졌거나 다른 inode로 바뀌면 새 lock으로 대체하거나 원장을 복구하지 않고 시작을 거부합니다.

최초 온라인 시작은 네 DB와 최종 marker를 `.authority-prepare-*` 비공개 디렉터리에 완성한 뒤, WAL을 checkpoint하고 DELETE journal 모드로 봉인합니다. 모든 정책·작업·dispatch·검수 이력이 비어 있고 누적 수량이 0인지 확인한 후, 파일의 바이트·device/inode·크기와 원래 디렉터리·lock·설정 binding을 불변 manifest에 고정합니다. 준비 디렉터리를 `authority-initialization`으로 덮어쓰기 없이 원자적으로 게시한 시점부터 자동 재시작 복구가 가능합니다. 복구는 고정된 네 DB inode를 기존 서비스 경로로 옮기고, 준비된 `authority-mode.json` inode를 **마지막에** 옮깁니다. 이 marker(`zoop-ai-authority-mode-2`)가 게시되기 전에는 일반 원장 생성자·작업 복구·dispatch·HTTP 처리를 시작하지 않습니다.

중단된 초기화는 각 고정 파일이 준비 경로와 최종 경로 중 정확히 한 곳에 남아 있고, 아직 사용되지 않은 봉인 상태일 때만 이어 갑니다. 파일 누락·교체·중복·hardlink·journal sidecar·binding 변경·사용 이력은 자동 채택하거나 정리하지 않고 거부합니다. **`authority-initialization` 게시 전의 중단으로 `.authority-prepare-*`만 남았다면 자동 복구 대상이 아닙니다.** 운영자가 상태를 확인해야 하며, 서비스는 잔여 디렉터리를 삭제하거나 새 DB로 덮어쓰지 않습니다. 파일시스템의 전원 장애로 소유권 증거가 모호해진 경우에도 복구를 보장하지 않고 닫힌 상태로 거부합니다.

완료된 v2 profile은 manifest와 원래 marker·DB inode를 계속 보존해야 합니다. 이후 정상 사용으로 바뀐 DB 바이트나 이력을 초기화 당시 해시·빈 상태와 다시 비교하지는 않습니다. 기존 v1 marker와 네 DB가 모두 있는 profile은 기존 검증을 유지하지만, v1 marker만 있는 불완전한 상태는 새 초기화로 해석하지 않습니다. 초기화 대기 상태에서도 수동 시작과 offline installer는 허용하지 않습니다. 이 복구는 정책 설치·grant 부활·quota 환불이나 사용한 원장의 재생성 기능이 아닙니다.

오류는 안정적인 코드만 반환합니다. 정책·quota·ID 거부는 자동 재시도 대상으로 표시하지 않으며, 검증의 실질적 거부(`plan_verification_failed`)와 verifier 전송 불능(`plan_verifier_unavailable`)을 구분합니다. 실제 정책·source grant·예산 설치, 유료 호출, 공개 JobCreate/queue/scheduler, HOLD 승인·게시·활성화는 이 기능의 범위가 아닙니다.

Verifier가 종료 코드 2와 닫힌 `zoop-extraction-s2-2` 오류 envelope를 함께 반환할 때만 409 `plan_verification_failed`로 분류합니다. 비정상 종료·signal·비JSON/빈/불일치 응답·출력 초과·deadline은 503 `plan_verifier_unavailable`이며, raw child 출력 없이 재시도 가능한 전송 불능으로 구분합니다. 출력 크기·deadline·kill/reap 한도는 그대로 유지하고 자동 재시도는 하지 않습니다.


### 운영자 토큰 절차(수동, 에이전트가 실행하지 않음)

서비스와 이 저장소는 비밀을 생성하지 않습니다. 운영자가 서비스 밖에서 토큰을 만들어 비밀 저장소에 보관하고 **digest만** 설정에 넣습니다.

```bash
# 운영자가 직접: 출력되는 digest만 ZOOP_AI_SERVICE_PRINCIPALS의 tokenSha256에 넣는다. 토큰은 앱 백엔드의 비밀 저장소로만 전달한다.
python3 -c 'import hashlib,secrets;t=secrets.token_urlsafe(48);print(hashlib.sha256(t.encode()).hexdigest())'
```

토큰은 `^[A-Za-z0-9._~+/-]{32,512}=*$` 형식이어야 합니다. 교체는 principal을 유지한 채 digest를 2개까지 겹쳐 둡니다. principal id가 소유 단위이므로 바꾸지 않습니다. 소유자는 인증된 principal이며 v1에는 최종 사용자(tenant) 식별이 없습니다.

## 접수·dispatch·복구

1. **접수 순서.** 인증→헤더→본문 검증→(소유자·본문 digest 조회)→**`reserved`로 소유 의도를 durable하게 기록**→`zoop-ai submit`(모델 호출 0, 실제 등록)→**`accepted`+dispatch 의도를 한 transaction으로 기록**→202. 요청 본문은 서비스 원장에 저장하지 않는다.
2. **고아 소유권 차단.** 런타임에는 등록됐지만 서비스가 응답 전에 죽었다면 `reserved` 행이 소유자를 이미 묶고 있어 다른 principal은 같은 jobId를 가질 수 없다(409 `job_id_unavailable`). 소유자가 같은 key·본문으로 다시 보내면 완료된다. 예약은 **시간으로 청소하지 않는다.** 런타임이 첫 시도에서 명확히 거절한 경우(입력 검증, `job_input_conflict`, 모델/effort/provider 설정 코드, grant registry 코드)에만 지운다.
3. **dispatcher.** 한 스레드·한 child. 오래된 pending부터 `in_flight`로 확정한 뒤 `zoop-ai run|resume`을 고정 argv로 실행한다. 요청 데이터는 이름 없는 임시 파일 stdin으로만 넘기고 stderr는 버린다. child는 자기 세션이며 데드라인(30초/300초) 초과 시 process group을 종료한다. 살아 있는 child를 서비스가 종료 시 기다리거나 죽이지 않는다.
4. **정책.** 처음 접수된 dispatch와 명시적 `recover`는 그대로(제한 없이) `run`/`resume`을 실행한다. **자동 재dispatch**(서비스 재시작, 비정상·데드라인 child, busy 폴링)는 worker CLI의 내부 권한 `--initial-only`로 실행한다. 이 제한은 먼저 읽어 둔 스냅샷이 아니라 **런타임 job lock 안에서** 판정된다. 호출 기록이 하나도 없는 job(원래 접수 의도)만 시작할 수 있고, 호출 기록이 하나라도 있으면 이미 저장된 receipt를 저장만 하며 어떤 단계도 reserve하거나 보내지 않는다(provider도 만들지 않는다). started/unknown 시도는 기존처럼 `reconciling`이 된다. 따라서 어떤 단계의 receipt는 저장됐는데 필요한 다른 단계는 아직 보내지 않은 job(예: 생성 receipt 뒤, 검증 reserve 전에 orphan이 죽음)은 `get`과 `run` 사이에 상태가 바뀌어도 자동으로 이어지지 않고, 서비스는 `idle`+`lastOutcome=needs_recover`(`next=recover`)로 기록한다. 이어 가는 것은 제한 없는 명시적 `recover`뿐이다. 런타임이 `queued/running`을 돌려주면 다른 프로세스가 잡고 있다는 뜻이므로 지수 backoff(≤60초). 자동 `resume`은 **필요한 모든 단계의 receipt가 이미 저장된 `save_only`**에서만 한다. 그 밖의 `persisting`, `failed`(`unsent_only` 포함)는 자동 재개하지 않고 `next=recover`다. 데드라인/signal/비정상 종료는 `transport_unknown`으로 기록하고 최대 3번 같은 job을 런타임에 다시 맡길 뿐이며 결과를 서비스가 판정하지 않는다. child가 끝난 뒤 dispatch 결과를 원장에 쓰는 일이 일시적으로 실패하면 서비스는 **그 결과를 보관하고 그 쓰기만 재시도**한다(worker를 다시 실행하지 않고 그동안 다른 행도 claim하지 않는다).
5. **재시작.** 이전 프로세스가 `in_flight`로 남긴 행은 `pending`으로 돌아간다. 같은 상태 디렉터리의 두 번째 인스턴스는 `service_state_busy`로 거부된다.
6. **취소.** 런타임 fence를 올리고 pending dispatch를 끝낸다. 진행 중 child는 죽이지 않으므로 늦게 온 응답은 receipt로 저장되고(사용량 보존) artifact 저장과 verify 송신만 막힌다. 취소는 환불 보장이 아니다.
7. **`reconciling`.** 어떤 명령도 미확인 provider 결과를 정산하지 못한다. `recover`는 409 `reconcile_required`이고 운영자 판단(공급자 측 사용량 증거)이 필요하다.

## 결과 전달과 개인정보

`result`는 런타임 `get` 출력을 **허용 목록 View**로 파싱해 다시 직렬화합니다(알 수 없는 키 제거, 누락은 실패, `phase`/`failure.code`/`calls[].error`는 짧은 기계 코드가 아니면 `redacted`). 원본 receipt·응답 content·fence·fixture digest·경로·환경은 런타임이 내지 않거나 View가 버립니다. `input`·`artifacts`·`calls`는 계약 타입(`Submit`, 네 종류의 artifact 결과, grant, call)의 **잎까지** 필드 단위로 투영하며 계약에 없는 필드는 버리고 필수 필드가 없거나 타입이 틀리면 닫힙니다(worker 계약과의 필드 일치는 시험으로 비교하고 `zoop_ai`는 import하지 않습니다). 그 위에서 서버가 **현재** grant registry를 직접 읽어(런타임이 echo한 grant 스냅샷이 아니라) 권리·revision·source·만료·operation·purpose·recipient를 확인하고, 막히면 내용 없이 `receipts`(호출 계정 메타데이터)만 돌려줍니다. live job은 필요한 **모든 단계의 호출 기록**이 있어야 recipient(provider+endpoint revision)를 증명할 수 있으므로 그 전(대기 중·미송신)에는 `delivery.reason=recipient_unproven`으로 내용을 내보내지 않습니다. grant registry를 읽을 수 없으면 내용을 내보내지 않고 503입니다.

stdout 로그는 요청마다 JSON 한 줄(requestId, principal, 라우트 템플릿, jobId, status, 런타임 exit/code, 소요 시간)이며 헤더·본문·환경·stderr·예외 문자열은 기록하지 않습니다. 문서·`/docs`·`/openapi.json`·CORS·proxy 헤더·server 헤더는 꺼져 있습니다.

## S3 관계 job (`/internal/v1/relation-jobs`)

이 서비스는 같은 프로세스에서 **별도 리소스 가족**으로 S3 관계·영향 후보 job의 제출·상태·결과·취소·복구와 HOLD 후보의 검수(allow/reject, **allow는 최종 승인**)를 노출합니다(스키마 `zoop-ai-internal-relation-1`, scope `relation.submit|read|cancel|recover|review`). S1의 `zoop-ai-internal-1` 와이어·상태 기계와 섞이지 않고 S1 라우트·원장은 그대로입니다. 목록 라우트는 없고, `eligible`은 자동 증거 gate이지 승인·게시가 아닙니다. upstream은 운영자가 준비한 S2 job이거나 S2 가족(`/internal/v1/extraction-jobs`, 아래 별도 절: 서버 사전 승인 요청의 digest만 받는 별도 가족)이 만든 job이며, 어느 쪽이든 S3 upstream 허용은 운영자 allowlist가 따로 정합니다. 요청의 `provenance`는 `(replay, authored-test)` 또는 `(live, provider)` 쌍만 유효하고 live는 아래 [live 실행](#live-실행-s2s3) 조건을 모두 만족해야만 열립니다.

| 메서드·경로 | scope | 성공 | 의미 |
|---|---|---|---|
| `POST /internal/v1/relation-jobs` | `relation.submit` | 202 새로 접수 / 200 멱등 재전송 | 본문은 S3 `Submit`(`zoop-relation-s3`)과 정확히 같다. `Idempotency-Key`=`jobId`. |
| `GET …/{jobId}` | `relation.read` | 200 `RelationJobStatus` | 요청마다 `zoop-ai-relation inspect`로 읽은 상태. **내용 필드 없음.** |
| `GET …/{jobId}/result` | `relation.read` | 200 `RelationResultEnvelope` | ready이고 모든 전달 gate가 열려 있을 때만 `job`(후보), 아니면 `delivery.state=withheld`+사유 코드. |
| `POST …/{jobId}/cancel` | `relation.cancel` | 200 / 409 `job_already_terminal` | 취소된 job은 멱등. **ready는 409**: pipeline `cancel`은 ready job도 영구 withheld로 만들기 때문에 상태를 먼저 읽고 ready는 pipeline에 넘기지 않는다. |
| `POST …/{jobId}/recover` | `relation.recover` | 202 enqueue / 200 coalesced | 명시적 `resume`. `reconciling`은 409 `reconcile_required`, ready·cancelled는 409 `job_not_recoverable`. |
| `POST …/{jobId}/reviews` | `relation.review` | 200 (allow·reject 기록 / 멱등 재전송) | 본문은 정확히 `{relationCandidateId, expectedSourceVersion, expectedSourceRevision, decision}`. `Idempotency-Key`가 안정적인 operation id. reviewer는 인증된 principal이며 요청으로 보낼 수 없다. **allow는 최종 승인**이다(정확한 `approved` 이벤트를 채택하고 재검증·dispatch·모델 호출이 없다). |
| `GET …/{jobId}/reviews/{operationId}` | `relation.read` | 200 `RelationOperationStatus` | key로 operation을 정확히 조회한다. 서비스 원장만 읽으므로 pipeline이 바빠도, 크래시 뒤에도 조회된다. |

**설정(전부 있어야 켜지는 그룹).** `ZOOP_AI_SERVICE_RELATION_COMMAND`(설치된 `zoop-ai-relation` 절대 경로), `ZOOP_AI_RELATION_STATE_DIR`(서비스가 **유일한 writer**, 서비스 원장이 이 경로 해시에 묶임), `ZOOP_AI_EXTRACTION_STATE_DIR`·`ZOOP_AI_INGESTION_STATE_DIR`(운영자가 쓰고 서비스는 읽기 전용으로만 pipeline에 넘김), `ZOOP_AI_SERVICE_SOURCES`(pipeline source/grant registry), `ZOOP_AI_SERVICE_RELATION_REPLAY`·`ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY`(authored fixture), `ZOOP_AI_SERVICE_RELATION_UPSTREAMS`(아래 allowlist), 그리고 `ZOOP_STATE_DIR`. 하나도 없으면 기능이 꺼져 모든 relation 라우트가 인증 뒤 409 `execution_unavailable`이고, **일부만 있거나 하나라도 잘못되면 시작을 거부**(코드 78, 변수 이름과 이유 코드만)합니다. 여섯 상태 루트(서비스·worker·앱·relation·extraction·ingestion)는 서로 겹치면 안 됩니다. child 환경은 S1과 같은 최소 값에 `ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR`(설치된 pipeline의 소유권 설정)만 더합니다. 요청은 경로·registry·fixture·command·live를 고를 수 없고 본문 모델이 이를 거부합니다.

**upstream 허용 목록.** S2 job은 운영자 프로세스가 만들거나, S2 가족(`/internal/v1/extraction-jobs`, 아래 별도 절)이 서버 사전 승인으로 만들므로 어느 쪽이든 호출자가 `upstream {jobId, inputDigest}`를 적는다고 권한이 생기지 않습니다. `ZOOP_AI_SERVICE_RELATION_UPSTREAMS` 파일(`{"schemaVersion":"zoop-ai-relation-upstreams-1","upstreams":[{"principal","jobId","inputDigest"}]}`, 알 수 없는 키·중복·모르는 principal 거부)이 principal별 정확한 쌍만 허용하며, 목록에 없으면 존재 여부와 관계없이 같은 403 `upstream_not_allowed`를 ledger·child 이전에 돌려줍니다. 파일은 사용할 때마다 다시 읽으므로 항목을 빼면 다음 요청부터 반영되고, 읽을 수 없으면 닫힙니다(503 `service_configuration_invalid`).

**소유권.** job은 제출한 principal의 것입니다(S1과 같음). 다른 principal의 job, 예약만 된 job, 없는 job은 모두 같은 404이고 같은 jobId를 다른 principal이 제출하면 409 `job_id_unavailable`입니다. pipeline의 `submit`은 이미 있는 id에 대해 저장된 job을 그대로 보고하므로, 첫 시도는 먼저 `inspect`로 그 id가 pipeline 원장에 없음을 확인합니다. 있으면 예약을 풀고 409(운영자가 만든 job을 채택해 읽는 일을 막음).

**접수와 dispatch.** 인증→헤더→본문(엄격한 `Submit`)→(소유자·본문 digest 조회)→allowlist→**`reserved` 기록**→(첫 시도면 채택 검사)→`zoop-ai-relation submit`(fixture·호출 0, 등록만)→**`accepted`+초기 dispatch 1개를 한 transaction으로 기록**→202. `submit`이 결과를 못 주면(timeout·응답 유실) **같은 gate 안에서 `inspect`로** 등록 여부를 확인합니다. 등록돼 있으면 이어 가고, 없음이 증명되면 예약을 풀고, 판단할 수 없으면 예약을 유지해 소유자의 같은 재시도만 완료하게 합니다. 한 번에 하나의 relation child만 실행합니다. pipeline은 원장 락을 기다리지 않으므로(`relation_busy`) 서비스가 전역 gate로 직렬화하고, 요청은 gate를 최대 10초 기다린 뒤 503 `runtime_busy`(`Retry-After`)입니다. 점유 중에는 오래된 상태를 돌려주지 않습니다.

**재실행 정책(자동 재전송 없음).** 최초 dispatch는 pending 행을 **한 번** claim해 `resume --initial-only`로 실행하고(pipeline이 **런타임 job lock 안에서** 판정하며, 호출 기록이 하나라도 있으면 `initial_dispatch_taken`으로 효과 없이 거절), 이후는 모두 명시적 `recover`(`explicit`, 제한 없는 `resume`)입니다. timeout·비정상 종료·읽을 수 없는 출력의 child와, 죽은 서비스가 in-flight로 남긴 행은 **모호**하므로 `idle`(`transport_unknown`, `service_restarted`, `next=recover`)로 끝나고 자동으로 다시 실행하지 않습니다. 유일한 자동 재시도는 pipeline이 락을 여는 단계에서, 즉 어떤 효과도 일어나기 전에 내는 `relation_busy`이며 지수 backoff 최대 8회입니다. 응답이 기록되지 않은 호출은 pipeline이 `reconciling`으로 만들고(`replay_response_unknown`/`live_response_unknown`) 다시 보내지 않으며 `recover`는 409 `reconcile_required`입니다. 알 수 없는 결과의 live 호출은 어떤 경로로도 재전송되지 않습니다(운영자 조정 전용).

### live 실행 (S2/S3)

live S2/S3 job은 **서버 운영자가 고정한 것만** 돌아갑니다. 호출자가 `executionMode: live`를 보내거나 digest를 안다고 해서 열리지 않습니다.

- **스위치와 설정.** `ZOOP_AI_SERVICE_PIPELINE_LIVE=1`이 있고 relation 또는 extraction 그룹이 켜져 있을 때만 live 그룹이 만들어집니다(`pipeline_live_gate_missing`·`pipeline_live_incomplete`·`pipeline_live_invalid`·`pipeline_live_budget_overlaps_state`·`pipeline_live_without_group`으로 시작 거부). 필요한 이름은 `ZOOP_AI_PIPELINE_LIVE_ENABLED=1`, `ZOOP_AI_PIPELINE_LIVE_MODEL`·`_REASONING_EFFORT`·`TYPESAFE_VALIDATION_MODEL`, 예산 `ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR`(상태 루트와 겹치면 안 됨)·`_MAX_USD`·`_MAX_CALLS`, 비밀 `ZOOP_AI_API_KEY`·`TYPESAFE_API_KEY`이고 `_MAX_OUTPUT_TOKENS`·`_TIMEOUT_SECONDS`·`ZOOP_AI_BASE_URL`·`TYPESAFE_BASE_URL`은 선택입니다.
- **환경 분리.** live **submit(등록) child**는 gate·모델·endpoint 설정과 예산 **디렉터리**만 받고(런타임 binding이 그 실경로를 고정하며 아무것도 만들지 않음) 키·상한은 받지 않습니다. 모델을 보낼 수 있는 **resume child**만 상한과 두 키를 추가로 받습니다. `inspect`·`cancel`·`review`·replay·graph·handoff·의존성·S1 child는 모델 키·live 변수를 받지 않습니다.
- **승인과 핀.** S2는 승인 파일 항목의 `liveRuntimeIdentity`(요청이 `executionMode: live`, `recordingKind: provider`일 때, fixture digest 없음)로, S3는 upstream 허용 항목의 `liveRuntimeIdentity`로 고정합니다. 서비스는 live 입력 digest를 `digest({request, liveBindingDigest})`로 계산해 pipeline이 보고한 값과 비교하고(S2 불일치는 500 `runtime_binding_mismatch`) S3는 pipeline이 동결한 `binding.runtime.identity`와 핀을 비교합니다. 거절: 409 `live_unavailable`(live 그룹 없음), 403 `live_not_approved`(핀 없음), 409 `live_binding_mismatch`. 핀은 원장에 불변으로 저장되고 dispatch·결과 전달·recover 직전에 다시 읽습니다(바뀌면 withheld `live_binding_changed`/`live_not_approved`, dispatch `live_binding_unpinned`).
- **자동 재전송 없음.** 자동 dispatch는 항상 `--initial-only`이고 알 수 없는 live 결과는 `live_response_unknown`으로 `reconciling`(recover 409)입니다. S3 live verifier의 기술적 실패는 `verification_unavailable`로 job이 `stopped`일 뿐 HOLD나 판정으로 바뀌지 않으며 서비스는 `failure.code`만 전달합니다.
- **한계.** 이 저장소의 시험은 loopback 시뮬레이터(`pipeline_tests/build_live_world.py`)를 쓰고 실제 provider·Jev를 부르지 않습니다. live S3의 resume·verify를 서비스 경로로 끝까지 도는 시험은 없고(핀·gate·등록만 확인), 실제 모델 품질·비용은 관측한 적이 없습니다.

**결과 전달.** 내용은 아래가 **모두** 같은 응답 시점에 성립할 때만 나갑니다. 호출자가 소유자이고, pipeline이 `ready`이며 `delivery.status=current`(source registry·ingestion binding·정확한 S2 export를 매 호출 다시 읽음)이고, 서버 allowlist가 아직 그 소유자의 upstream을 허용하며, 본문이 허용 목록 투영을 엄격히 통과합니다. 아니면 `delivery.state=withheld`와 사유(`job_not_ready`, `source_unauthorized`, `upstream_not_allowed`, `job_cancelled`, `projection_invalid` …)만 돌려주고 receipt는 단계·상태·verdict 코드만 담습니다. 투영은 artifact·raw/mapping hash, fixture·요청·응답 digest, claim·quote 표, `creatorJobId`, 운영자 CLI 검수의 `reviewer`·`note` 자유 텍스트, 실패 `detail`을 버리고, 검증되지 않은 citation의 generator 문장은 전달하지 않습니다. **한계:** 이 확인들은 서로 다른 시각의 읽기이므로 확인과 응답 사이에 일어난 철회는 보이지 않고, 이미 받은 내용은 회수할 수 없습니다. 또한 `delivery.state=available`은 그 시점의 검사 결과일 뿐 앱 import의 권한 재확인을 대신하지 않습니다.

**검수(review)와 원천 버전·revision.** 팀의 개정 ERD·계약 분기(`fix/17-erd-v6-alignment` af2f0e3)는 main `91113ce`(PR #18)로 병합됐고, 병합된 ERD v6와 공개 OpenAPI(`docs/api/openapi.yaml`)가 정한 규칙, 즉 결정이 대상별 앱 `expectedRevision`과 별도로 AI 원천의 `expectedSourceVersion`·`expectedSourceRevision`을 함께 받는다는 규칙을 이 내부 계약의 근거로 씁니다. 이 서비스의 값은 둘 다 **런타임 원천 값**입니다. `sourceVersion`은 S3 job의 `inputDigest`(job마다 불변이고 S2 upstream의 `inputDigest`가 아니다)이고, `sourceRevision`은 해당 relation 후보의 pipeline 이벤트 체인 revision(이벤트 수)을 10진 문자열로 적은 값입니다. 둘은 `GET …/result`의 relation마다 나옵니다(`relations[].sourceVersion`·`sourceRevision`, 후자는 `eligibility.revision`과 항상 같은 수). **앱의 `review_targets.current_revision`·`review_decisions.global_revision` 같은 앱 revision은 이 서비스가 받지도 전달하지도 않으며, 이 값들을 서로 바꿔 쓰면 안 됩니다.**

검사는 둘 다 정확히 일치해야 하고 하나라도 다르면 **아무것도 기록하지 않습니다**. 새 결정의 `expectedSourceVersion`은 job의 불변 `inputDigest`와 비교하고(예약 전, 409 `source_version_conflict`), `expectedSourceRevision`은 pipeline `review`의 `expectedRevision`으로 넘겨 **pipeline의 append transaction 안에서** 비교합니다(409 `source_revision_conflict`). 이 거절들은 예약을 풀기 때문에 같은 key로 고친 요청을 다시 보낼 수 있습니다. 풀리는 거절은 HOLD가 아닌 후보 409 `review_target_not_hold`, 호출이 진행 중인 후보 409 `review_call_in_flight`, 승인 근거가 될 수 없는 후보 409 `review_candidate_ineligible`, 취소된 job 409 `job_cancelled`, 없는 후보 404 `relation_candidate_not_found`입니다(`review_already_pending`은 대기 중인 allow가 없으므로 사라졌습니다). 같은 key와 같은 본문은 그 사이 relation이 앞으로 갔어도 기존 operation을 돌려주고(200), 다른 본문이나 다른 job은 409 `idempotency_conflict`, 다른 principal의 key는 409 `operation_id_unavailable`이며 다른 principal의 job·operation은 404입니다.

**사람의 allow는 최종 승인입니다.** 순서는 인증·scope→헤더·엄격한 본문→소유한 job→(같은 key의 operation이 있으면 소유자·본문 digest 비교, 확정됐으면 200)→upstream이 지금 allowlist에 있는지(403)→`expectedSourceVersion`→**operation 예약을 원장에 영속(`reserved`, 상한 없음, `contract=final-approval`)**→`zoop-ai-relation review`→체인에서 **정확한 이벤트를 증명**→**확정(`applied`)**→200(allow·reject 모두). allow는 `approved`, reject는 `excluded` 효과의 이벤트를 하나 추가할 뿐이고 서비스는 이를 **재검증 없이, dispatch 없이, 모델 호출 없이** 그대로 채택합니다. reviewer는 principal, `note`는 operation id에서 만든 marker(`zoop-ai-service-review:<operationId>`)라서 "내 append가 반영됐는가"가 추측이 아니라 체인 조회가 됩니다. child가 timeout·비정상 종료·읽을 수 없는 출력으로 끝나거나 이전 시도가 있었던 재시도에서는 **쓰기 전에 읽습니다**. 이벤트가 정확히 `seq=expected+1`·`reviewer`·`decision`·`expectedRevision`·`effect`·marker까지 모두 일치할 때만 채택하고(확정 시각은 pipeline이 적은 `createdAt`), 일부만 맞으면 모순(500 `runtime_binding_mismatch`)이며 채택하지 않습니다. **이전 시도가 있었던 재시도에서는 pipeline의 거절도 부재의 증명이 아닙니다**(서비스가 죽어도 그 review child는 별도 세션이라 살아남아 같은 operation의 정확한 이벤트를 append할 수 있음). 그래서 첫 시도의 거절만 확정으로 보고, 재시도의 거절은 **체인을 다시 읽어** 정확한 이벤트가 있으면 채택하며, 읽을 수 없거나 모순이면 예약을 유지하고(503 `review_unconfirmed`·500), 체인이 expected를 지났는데 marker 이벤트가 없으면 그때만 풀어 키를 현재 revision으로 다시 쓸 수 있게 합니다. 운영자 CLI가 직접 쓴 검수 이벤트는 marker가 없으므로 어떤 operation도 채택하지 않습니다.

**operation 상태.** `review`(결정이 런타임 원장에 기록됐는가: `applied`·`unconfirmed`, `resultingSourceRevision`=expected+1), `revalidation`(현재 계약에서는 항상 `not_requested`이고 이전 계약 행만 `verified`·`superseded`·`contract_changed`), `publication`(항상 `not_published`: 이 서비스는 아무것도 게시하지 않습니다), `limitation`(이전 계약 행이면 `review_contract_changed`, 아니면 없음). 조회는 key 하나로 operation·후보·결정·reviewer·두 기대값을 그대로 돌려주고 서비스 원장만 읽습니다. `next`는 `retry_review`(예약만 있고 기록이 확인되지 않음, 같은 key·본문으로 다시 보냄)와 `none`뿐입니다. 승인된 relation의 `eligibility.approvalBasis`는 `{kind, revision, reviewer, decidedAt}`이고 `impact.status`는 `not-applicable`입니다.

**이전 검수 계약의 행.** `zoop-ai-relation-jobs-ledger-3`로 올릴 때 `relation_operations`는 제자리에서 다시 만들어지고, 이전 행은 `contract='legacy-revalidation'`으로 **이력으로만** 남습니다. 서비스는 그 행을 dispatch하지도, 다시 보내지도, 승인으로 해석하지도 않습니다(이전 allow가 승인으로 읽히는 일은 없음). 조회는 `limitation=review_contract_changed`와, 이전에 정착한 경우 그 `revalidation`(`verified`/`superseded`)을, 정착하지 못했다면 `contract_changed`를 돌려주고 `next=none`입니다. 같은 key를 `reserved` 상태의 이전 행에 다시 보내면 409 `review_contract_changed`이며 새 operation id로만 다시 결정할 수 있습니다. 재검증 dispatch·`revalidate` child·operation `recover` 라우트(`recoverRelationReviewOperation`)는 제거되었습니다(clean cutover).

**reject와 stale 요청.** reject는 `excluded` 이벤트를 추가하고, 그 뒤의 allow(또는 이전 revision의 요청)는 409 `source_revision_conflict`/`review_target_not_hold`입니다. 확정은 write-once인 종결 상태이므로 체인 읽기(`inspect` probe) 결과는 claim의 **job·`inputDigest`·upstream**에 묶인 뒤에만 쓰입니다. relation 후보 id는 같은 upstream을 쓰는 job들 사이에서 반복될 수 있어서 다른 job의 유효한 사슬이 같은 이벤트를 보여 주더라도 이 operation을 확정하지 않고 `runtime_binding_mismatch`로 남깁니다. delivery가 current가 아닌 응답도 확정에 쓰지 않습니다.

**호환·마이그레이션 결정.** (1) 서비스 원장 `relation-jobs.sqlite3`는 `zoop-ai-relation-jobs-ledger-1`·`-2`에서 **제자리에서 앞으로만** `-3`으로 이전됩니다(`-3`은 `relation_operations.contract`, `relation_jobs.live_binding`·`execution_mode`, `relation_dispatch.explicit` 열을 더합니다). 이전 행은 다시 쓰지 않고 위 이력으로 남으며, 이후·외부 스키마는 거절합니다. 이전 빌드로 `-3` 원장을 여는 것은 지원하지 않습니다. (2) 호출자에게 보이는 변경: 검수 POST는 항상 200, `RelationOperationStatus.limitation`과 `revalidation.state=contract_changed`, `next ∈ {retry_review, none}`, operation recover 라우트 제거, 새 409 코드(`review_call_in_flight`·`review_candidate_ineligible`·`review_contract_changed`), `RcEligibility.approvalBasis`, relation `provenance`의 live 쌍. (3) 앱 쪽 영속화(`review_targets`·`review_decisions`)는 이 작업의 범위가 아닙니다. Spring 전송 클라이언트(`RelationClient`: `review`·`operation`, AI 원천 `expectedSourceVersion`·`expectedSourceRevision`만 전달하고 앱 revision 필드는 없음)는 같은 계약으로 갱신했습니다([api AI 연동](../../api/docs/AI_INTEGRATION.md#s2-추출s3-관계-클라이언트)).

**한계.** 목록 라우트는 없습니다(S2 HTTP는 위 별도 가족으로 제공합니다). 운영자 CLI가 직접 쓴 검수 이벤트는 체인에 남지만(전달 내용에서는 자유 텍스트 없이) 어떤 operation도 그것을 자기 것으로 채택하지 않습니다. 한 서비스 프로세스가 pipeline 원장의 유일한 writer라는 것은 배포 규칙이며 코드가 강제하지 않습니다(운영자 CLI가 같은 원장을 쓰면 `relation_busy`가 나거나, 그 사이 취소·채택의 TOCTOU가 남습니다). dispatcher는 직렬이고 pipeline의 `resume`이 300초 deadline 안에 끝나는지는 실측하지 않았습니다. S3 child와 S2 child는 같은 gate를 씁니다(S3가 읽는 S2 원장을 S2 child가 쓰기 때문).

## S2 추출 job (`/internal/v1/extraction-jobs`)

설치된 `zoop-ai-extract`(S2-2: 이벤트·토픽 후보, 계약 `zoop-extraction-s2-2`) 위의 **별도 가족**입니다. 응답 스키마는 `zoop-ai-internal-extraction-1`, scope는 `extraction.submit|read|cancel|recover`, 원장은 `extraction-jobs.sqlite3`(스키마 `zoop-ai-extraction-jobs-ledger-2`, `-1`에서 앞으로만 이전되며 `live_binding`·`explicit` 열을 더함, 추출 상태 디렉터리 실경로 해시에 묶임)이며 S1·S3의 wire 계약·원장·상태 기계와 아무것도 공유하지 않습니다. 기본은 replay이고 모델·네트워크 경로가 없으며, 서버 승인 항목이 `liveRuntimeIdentity`로 고정한 요청만 [live 실행](#live-실행-s2s3)으로 돌 수 있습니다(`ExtractionUsage`는 `receivedCalls`·`unsentCalls`·토큰·`estimatedUsd`·`chargedUsd`를 더하고 live provenance는 `(live, provider)`).

| 라우트 | scope | 응답 | 의미 |
|---|---|---|---|
| `POST /internal/v1/extraction-jobs` | `extraction.submit` | 202 신규 / 200 멱등 재전송 | 본문은 **정확히** `{schemaVersion:"zoop-extraction-s2-2", jobId, approvedRequestDigest}`. `Idempotency-Key`는 `jobId`와 같아야 한다. |
| `GET …/{jobId}` | `extraction.read` | 200 `ExtractionJobStatus` | pipeline `inspect`를 이 요청 안에서 읽은 상태. 내용 필드(후보·인용·digest)는 절대 없음. |
| `GET …/{jobId}/result` | `extraction.read` | 200 `ExtractionResultEnvelope` | ready이고 모든 전달 gate가 열려 있을 때만 `job`(이벤트·토픽 후보), 아니면 `delivery.state=withheld`+사유 코드. |
| `POST …/{jobId}/cancel` | `extraction.cancel` | 200 / 409 `job_already_terminal` | queued·running·stopped·reconciling은 `cancelled`로 끝나고(대기 중 dispatch 종료, 이미 도는 child는 죽이지 않음), 취소된 job은 멱등. **ready는 409**: S2 pipeline `cancel`은 ready job을 건드리지 않으므로 그대로 ready로 남고 서비스가 그 사실을 알린다. |
| `POST …/{jobId}/recover` | `extraction.recover` | 202 enqueue / 200 coalesced | 명시적 `resume`. `reconciling`은 409 `reconcile_required`, ready·cancelled는 409 `job_not_recoverable`, 승인·fixture가 바뀌었으면 403 `request_not_approved`·409 `approval_changed`·409 `fixture_changed`. |

**설정(전부 있어야 켜지는 그룹, S3 그룹과 별개).** `ZOOP_AI_SERVICE_EXTRACTION_COMMAND`(설치된 `zoop-ai-extract` 절대 경로), `ZOOP_AI_SERVICE_EXTRACTION_REPLAY`(authored producer fixture), `ZOOP_AI_SERVICE_EXTRACTION_APPROVALS`(아래 사전 승인), 그리고 S3와 **공유하는 세 변수** `ZOOP_AI_EXTRACTION_STATE_DIR`(S2 원장; S2 child가 writer, S3는 같은 원장을 읽기 전용으로 엶), `ZOOP_AI_INGESTION_STATE_DIR`(운영자가 쓰고 pipeline은 읽기 전용), `ZOOP_AI_SERVICE_SOURCES`(pipeline source/grant registry), 그리고 `ZOOP_STATE_DIR`. 선택 변수는 `ZOOP_AI_SERVICE_EXTRACTION_TOPIC_REPLAY`(토픽 단계를 요청하는 승인에만 필요) 하나이며 이것만 있으면 불완전 그룹입니다. 하나도 없으면 기능이 꺼져 모든 extraction 라우트가 인증 뒤 409 `execution_unavailable`이고, **일부만 있거나 하나라도 잘못되면 시작을 거부합니다**(exit 78, 변수 이름과 사유 코드만 출력, `extraction_group_incomplete`). 공유 세 변수는 두 그룹이 같은 값을 읽으므로 S2와 S3의 루트·registry가 서로 어긋날 수 없고, S2 그룹이 켜져 있으면 공유 변수만으로 S3 그룹이 켜지지 않습니다(S3 자기 변수가 있으면 S3도 전부 있어야 함). 서비스·worker·앱·추출·ingestion 다섯 상태 루트는 서로 겹칠 수 없고 추출·ingestion 디렉터리는 먼저 존재해야 합니다. child 환경은 소유 루트 두 개뿐이며, provider 키·URL·모델·live 스위치는 환경에 있어도 **replay 명령에는 복사하지 않습니다.** [live 실행](#live-실행-s2s3)이 켜져 있을 때만 live 등록·재개 child에 명시된 이름이 구분되어 전달됩니다.

**서버 사전 승인(`ZOOP_AI_SERVICE_EXTRACTION_APPROVALS`).** 호출자는 pipeline의 S2 `Submit`을 보내지 못합니다. 운영자 파일(`{"schemaVersion":"zoop-ai-extraction-approvals-1","approvals":[{"principal","jobId","approvedRequestDigest","request","producerReplayDigest","topicReplayDigest"}]}`, live 항목은 `producerReplayDigest`·`topicReplayDigest` 대신 `liveRuntimeIdentity`, 알 수 없는 키·중복 `(principal, jobId)`·모르는 principal 거부)이 principal+jobId+digest를 **정확한 S2 `Submit` 본문**(스냅샷·카탈로그·incoming 관측·토픽 요청)과, replay 항목이면 그것이 실행될 fixture 바이트의 SHA-256에, live 항목이면 그 요청이 비용을 쓸 수 있는 런타임 binding 신원에 대응시킵니다. 서비스는 읽을 때마다 `request`의 정규 JSON digest가 `approvedRequestDigest`와 같은지, `request.jobId`가 항목의 `jobId`와 같은지, provenance 쌍이 `(replay, authored-test)`(fixture digest 필수) 또는 `(live, provider)`(fixture 없음, `liveRuntimeIdentity` 필수)인지, `topic` 요청과 `topicReplayDigest`가 정확히 짝인지(replay에서 `topic`이 있으면 선택 fixture가 설정돼 있어야 함)를 검증하고, 하나라도 어긋나면 시작을 거부하거나 닫힙니다. 목록에 없으면 존재 여부와 관계없이 같은 403 `request_not_approved`를 ledger·child 이전에 돌려줍니다. live 항목은 live 그룹이 없으면 409 `live_unavailable`입니다. **승인은 pipeline이 허용하는 것을 좁힐 뿐입니다.** pipeline은 내용을 다루는 모든 명령에서 운영자 source registry를 다시 읽으므로 승인이 있어도 registry가 막으면 읽히지 않습니다. 파일은 사용할 때마다 다시 읽고 읽을 수 없으면 닫힙니다(503 `service_configuration_invalid`).

**회차 계획 파일(`zoop-ai-extract plan-round`).** pipeline의 [오프라인 계획 명령](../pipeline/README.md#이벤트same주제-후보-s2-2-authored-replay-또는-live-provider)은 완료 회차에서 `approvals.json`, `relation-upstreams.json`, `manifest.json`, `receipt.json`을 만듭니다. 계획 생성은 설치·유료 호출·예산 설정과 별개입니다. 앱용 manifest에는 계획 ID·digest·단위별 S2 제출 필드만 있으며, 승인 항목의 분석 입력·스냅샷·카탈로그·비밀·원문은 없습니다. 계획 작업은 `s2p-` ID를 사용하며 기존 CLI 작업을 HTTP 작업으로 재사용하지 않습니다. 검토한 계획은 아래 운영자 전용 명령으로 설치합니다. 앱의 계획 등록과 `JobCreate.planId` 처리는 BE에 제안한 후속 작업이며 아직 구현되지 않았습니다.

**검토한 계획을 오프라인으로 설치합니다.** 먼저 서비스를 중지하고 서비스와 같은 운영자 환경을 사용합니다. 서비스 상태 디렉터리는 미리 존재하는 현재 사용자 소유의 `0700` 디렉터리여야 합니다. S2·S3 설정 그룹, 알려진 principal, 기존 두 registry가 필요합니다. 처음에는 기존 형식의 빈 `approvals`·`upstreams` 배열을 운영자가 준비합니다. registry와 fixture·명령 파일은 서비스·앱·worker·ingestion·extraction·relation 상태 루트 밖에 두고, symlink와 겹치는 경로는 사용하지 않습니다. 한 destination 쌍을 다른 서비스 상태 디렉터리나 관리되지 않는 reader/writer와 공유하면 안 됩니다.

```bash
# 서비스 가상환경의 python을 사용합니다. inspect/status는 설치 파일이나 상태 디렉터리를 만들지 않습니다.
ai/service/.venv/bin/python -m zoop_ai_service.plan_install_cli inspect --plan-dir /absolute/reviewed-plan
# 출력의 currentDigest, reviewDigest와 정확한 변경 내용을 사람이 검토한 뒤에만 실행합니다.
ai/service/.venv/bin/python -m zoop_ai_service.plan_install_cli install \
  --plan-dir /absolute/reviewed-plan \
  --expected-current-digest CURRENT_DIGEST --expected-review-digest REVIEW_DIGEST
ai/service/.venv/bin/python -m zoop_ai_service.plan_install_cli status \
  --installation-id plan-install-REVIEW_DIGEST
# status의 transactionDigest를 확인한 뒤, 중단된 설치만 명시적으로 복구합니다.
ai/service/.venv/bin/python -m zoop_ai_service.plan_install_cli recover \
  --installation-id plan-install-REVIEW_DIGEST --expected-transaction-digest TRANSACTION_DIGEST
```

`inspect`는 bounded·duplicate-free JSON, receipt의 정확한 파일 hash/길이, manifest digest, 기존 서비스 로더의 principal·요청 digest·fixture/runtime pin을 검사합니다. 설치된 `zoop-ai-extract verify-plan`을 읽기 전용으로 호출해 전체 `Submit` 스키마와 현재 회차로 계획을 재생성하고, incoming·snapshot 문서의 현재 source-read/export 권한과 source binding도 확인합니다. plan 파일·현재 registry 바이트·설정·source registry/binding·병합 결과를 모두 `reviewDigest`에 묶습니다. digest는 검토 대상의 무결성 식별자이지 사람의 승인 증명이나 인증 토큰이 아닙니다. 설치 권한은 보호된 운영자 실행 환경과 파일 권한에 있습니다.

검토 대상에는 서비스 상태 디렉터리와 각 target의 부모 디렉터리의 device/inode도 포함됩니다. 같은 경로에 같은 바이트를 복사했어도 디렉터리 자체가 교체되면 기존 검토·journal로 설치하거나 복구하지 않습니다. 설치·복구는 확인한 디렉터리 FD를 유지하고 파일 생성·교체·journal 게시를 그 FD에 상대적으로 수행합니다. 디렉터리의 mtime·크기나 target 파일의 교체 전 inode는 고정하지 않으므로, 무관한 형제 파일 작업이나 정상적인 원자 교체 때문에 검토가 무효가 되지는 않습니다.

`install`은 서비스와 같은 `ProcessLock`을 잡고 현재 바이트와 검토 digest를 다시 검사합니다. `(principal, jobId)` 승인과 `(principal, jobId, inputDigest)` upstream은 동일하면 유지하고 새 항목만 추가합니다. 같은 키의 다른 내용은 전체 거부하며, 다른 principal·이전 회차·standalone S3 항목을 제거하지 않습니다. 병합 뒤에도 기존 크기 제한과 replay fixture pin을 만족해야 합니다. fixture 회전이나 기존 승인 정리는 이 명령의 기능이 아닙니다.

설치 journal은 `$ZOOP_AI_SERVICE_STATE_DIR/plan-install/`의 `binding.json`, `pending.json`, `transactions/<installationId>/`에 저장합니다. transaction에는 보호된 before/after 이미지·`intent.json`·최종 `receipt.json`이 남습니다. 파일과 디렉터리를 fsync하고 **두 target 중 하나라도 바꾸기 전에** pending marker를 영속합니다. 두 파일 교체 자체는 물리적으로 원자적이지 않습니다. 서비스는 lock 직후, 어떤 원장 생성·중단 작업 복구·dispatch보다 먼저 미해결·손상 journal을 검사해 `plan_install_unresolved`로 시작을 거부합니다. 이 보장은 동일한 상태 소유자의 lock과 시작 차단에 의존합니다.

미완료 transaction의 `recover`는 각 target이 기록된 before 또는 after 바이트일 때만 before 쌍으로 돌리고 `aborted` receipt를 남깁니다. committed receipt와 남은 pending marker가 있으면 정확한 after 쌍을 확인한 뒤 marker만 정리합니다. 수동 철회나 다른 세 번째 바이트, 손상 journal, 바뀐 destination은 덮어쓰지 않습니다. `status`·`recover`는 전체 `config.load()`를 호출하지 않으며 source registry·fixture·원문·provider key·budget이 없어도 저장된 transaction의 경로와 이미지로 판단합니다.

정상 설치와 재호출의 출력은 `schemaVersion`, `installationId`, `transactionDigest`, `outcome`, `appliedNow`, `installationCurrent`입니다. 최초 commit만 `appliedNow:true`이며, committed·aborted ID를 재사용해 새 승인을 만들 수 없습니다. 이후 계획이 추가되어도 기존 receipt 재호출은 registry를 다시 쓰지 않습니다. 따로 철회된 항목이 있으면 과거 receipt metadata와 `appliedNow:false`, `installationCurrent:false`, `error.code:installation_not_current`를 함께 반환하고 exit 78로 끝납니다. 이 상태의 `installationCurrent`는 **기록된 정확한 항목이 현재 registry에 남아 있는지**만 뜻하며 현재 원천 권한이나 실행 가능성을 보증하지 않습니다. 일반 성공은 exit 0, 거부는 exit 78, 잘못된 CLI 인자는 argparse의 exit 2입니다. 주요 거부 코드는 `stale_current`, `stale_review`, `service_state_busy`, `plan_conflict`, `fixture_changed`, `installation_pending`, `journal_target_drift`, `journal_binding_changed`입니다.

설치는 source 권한·model-send 권한·예산·HOLD allow·앱 공개 권한을 만들지 않고, job을 submit/resume/cancel하거나 서비스를 시작하지도 않습니다. snapshot mention grounding과 실제 freeze 가능성은 submit에서, 현재 source/model-send 권한은 실제 사용과 dispatch에서 다시 검사합니다. 검증과 파일 게시 사이의 권한 변경은 하나의 transaction이 아니므로 이 재검사를 유지해야 합니다. 이 운영자 도구는 상시 자동 승인 정책이나 05/35 수집·10/40 확인 보장의 구현이 아닙니다. 단위 transaction 검사는 `tests/test_plan_install.py`, 실제 CLI·HTTP 흐름과 중단 복구는 `scripts/plan_install_service_smoke.py`에서 다룹니다.

**소유권·고정된 신원.** job은 제출한 principal의 것이고 다른 principal의 job·예약만 된 job·없는 job은 모두 같은 404, 같은 jobId를 다른 principal이 제출하면 409 `job_id_unavailable`입니다. pipeline의 `submit`은 이미 있는 id에 대해 저장된 job을 그대로 보고하므로 첫 시도는 먼저 `inspect`로 그 id가 pipeline 원장에 없음을 확인하고, 있으면 예약을 풀고 409(운영자가 만든 job을 채택해 읽는 일을 막음)입니다. **예약은 `submit` 전에 영속합니다**: 소유자·호출자 본문 digest와 함께 그 순간 승인이 고정한 값, 즉 승인된 요청 digest, producer fixture digest, (있으면) 토픽 fixture digest, 그리고 pipeline이 보고해야 하는 `inputDigest`(`digest({request, replayFixtureHash})`를 **서비스가 승인 바이트로 계산**, pipeline이 말한 값을 받아 적지 않음)를 원장에 씁니다. 고정 열은 불변입니다(DB trigger). 정확히 같은 본문의 재전송은 고정된 값을 그대로 쓰고(200), 같은 jobId에 다른 digest는 409 `idempotency_conflict`, 승인 항목이나 fixture 파일이 그사이 바뀌었으면 409 `approval_changed`·`fixture_changed`(또는 withheld)로 같은 job id를 새 바이트에 다시 묶지 않습니다. 고쳐 쓰려면 새 jobId를 승인해야 합니다.

**접수와 dispatch.** 인증→헤더→본문(엄격한 3개 필드)→(소유자·본문 digest 조회)→승인 조회→fixture digest 확인→**`reserved` 기록**→(첫 시도면 채택 검사)→`zoop-ai-extract submit`(replay fixture 이름, 등록만: 호출·후보 0)→**pipeline이 보고한 `inputDigest`가 서비스가 계산한 값과 같고 provenance·상태(`queued`·호출 없음)가 승인과 같은지 확인**→**`accepted`+초기 dispatch 1개를 한 transaction으로 기록**→202. `submit`이 결과를 못 주면 같은 gate 안에서 `inspect`로 등록 여부를 확인하고(등록돼 있으면 이어 가고, 없음이 증명되면 예약을 풀고, 판단할 수 없으면 예약을 유지), **어떤 경우에도 `submit`을 다시 보내지 않습니다.** 크래시가 등록 뒤·서비스 확인 전에 났다면 소유자의 같은 재시도가 같은 신원으로 이를 완료합니다. S2와 S3의 모든 child는 **단 하나의 gate** 뒤에서 한 번에 하나만 실행합니다(pipeline 원장 락은 기다리지 않고, S3는 S2가 쓰는 바로 그 원장을 읽는다).

**재실행 정책(자동 재전송 없음).** 최초 dispatch는 pending 행을 **한 번** claim해 `resume`합니다. 이후는 모두 명시적 `recover`입니다. timeout·비정상 종료·읽을 수 없는 출력의 child와 죽은 서비스가 in-flight로 남긴 행은 모호하므로 `idle`(`transport_unknown`, `service_restarted`, `next=recover`)로 끝나고 자동으로 다시 실행하지 않습니다. 유일한 자동 재시도는 pipeline이 락을 여는 단계에서, 즉 어떤 효과도 일어나기 전에 내는 `extraction_busy`·`ingestion_busy` **오류**이며 지수 backoff 최대 8회입니다. **실행 도중** ingestion reader가 바빠서 pipeline이 job을 `stopped`(`ingestion_busy`)로 기록하고 정상 결과를 돌려준 경우는 `exited`일 뿐이고 명시적 recover만 이어 갑니다(pipeline을 바꿔 재시도하게 하지 않았습니다). reserve됐으나 응답이 기록되지 않은 호출은 pipeline이 `reconciling`으로 만들고 다시 보내지 않으며 recover는 409 `reconcile_required`입니다. 저장된 receipt는 recover에서 재사용되고 다시 호출하지 않습니다.

**매 dispatch의 권한.** child를 띄우기 전에(최초 dispatch 포함) 소유자의 승인이 job이 예약된 때의 것과 정확히 같은지, fixture 파일이 고정된 바이트인지를 다시 읽고, 아니면 child 없이 `approval_revoked`·`approval_changed`·`fixture_changed`·`fixture_unavailable`로 `idle` 처리합니다(명시적 recover는 운영자가 복구한 뒤에만 이어 감).

**결과 전달.** 내용은 아래가 **모두** 같은 응답 시점에 성립할 때만 나갑니다. 호출자가 소유자이고, pipeline이 `ready`이며 `delivery.status=current`(source registry·ingestion binding·모든 문서의 권리를 매 호출 다시 읽음)이고, 승인이 아직 예약된 것과 같고, fixture 파일이 고정된 바이트이며 **모든 receipt가 그 바이트로 응답됐고**, 본문이 허용 목록 투영을 엄격히 통과합니다. 아니면 `delivery.state=withheld`와 사유(`job_not_ready`, `source_unauthorized`, `approval_revoked`, `approval_changed`, `fixture_changed`, `fixture_unavailable`, `job_cancelled`, `projection_invalid` …)만 돌려주고 receipt는 단계·상태·verdict 코드만 담습니다. 투영은 사건 후보(`approved:false`, 멘션, 검증된 인용, frozen 스냅샷과의 비교 `original`·`effective`·인용, disposition)와 토픽 후보(멤버·인용)를 보존하되 artifact·raw/locator·segment 표, fixture·요청·응답·그룹·스냅샷 digest, `creatorJobId`, 저장된 binding, 그리고 인용으로 뒷받침되지 않은 생성 텍스트(멘션·비교의 자체 evidence)는 이름을 적지 않아 내보내지 않으며, 필드가 없거나 타입이 다르면 `projection_invalid`로 닫힙니다. 검사는 서로 다른 시점의 별도 읽기이므로 그 사이의 철회와 이미 나간 내용의 회수는 다루지 못합니다. **S2 결과는 S3 권한을 자동으로 넓히지 않습니다**: S3 upstream 허용 목록은 별도의 서버 파일이고 운영자가 명시적으로 적어야 합니다.

**fixture 파일의 TOCTOU.** fixture는 child가 직접 읽는 서버 설정 파일이라 서비스의 digest 확인이 그 읽기와 원자적일 수 없습니다. 이 창은 사후에 닫습니다. pipeline의 `inputDigest`가 서비스가 승인 바이트와 고정 producer digest로 계산한 값과 다르면(등록 중 파일이 바뀜) 500 `runtime_binding_mismatch`로 예약이 `accepted`가 되지 않고(그 job id는 이후에도 새 입력으로 쓰이지 못하고 운영자가 정리해야 합니다), 모든 receipt의 fixture hash가 해당 단계의 고정 digest와 다르면(실행 중 파일이 바뀜) dispatch가 `fixture_changed`로 끝나고 이후 전달은 파일을 원래 바이트로 되돌려도 withheld입니다. 파일이 없거나 읽을 수 없으면 안전하게 `fixture_unavailable`이며, 어떤 경로에서도 네트워크 호출이 없습니다.

**호환·결정.** (1) pipeline은 바꾸지 않았습니다(`ai/pipeline` 소스 변경 없음, 새 의존성·필드 없음; 변경은 시험 세계 도우미가 S2 요청과 topic fixture를 내보내도록 `scripts/relation_smoke.py`에 두 속성을 더한 것뿐). (2) 서비스 원장은 새 파일 `extraction-jobs.sqlite3`라 S1·S3 원장과 스키마를 건드리지 않습니다. (3) 요청 본문의 `schemaVersion`은 S3와 같은 방식으로 런타임 계약 이름(`zoop-extraction-s2-2`)이고 응답은 `zoop-ai-internal-extraction-1`입니다. (4) S3 설정은 그대로이며 S2 그룹이 없을 때 모든 동작이 이전과 같습니다.

**한계.** 목록 라우트가 없고 `run`은 쓰지 않습니다(등록과 실행은 별도 명령·권한). 한 서비스 프로세스가 S2 원장의 유일한 writer라는 것은 배포 규칙이며 코드가 강제하지 않습니다(운영자 CLI가 같은 원장을 쓰면 `extraction_busy`가 나거나 그 사이 취소·채택의 TOCTOU가 남습니다). 승인 파일의 `request`는 서비스가 pipeline의 `Submit` 스키마 전체를 검증하지 않으므로(import 경계) 형식 오류는 첫 `submit`에서 pipeline이 거부하고 서비스는 503 `service_configuration_invalid`로 닫습니다. dispatcher는 직렬이고 `resume`이 300초 deadline 안에 끝나는지는 실측하지 않았습니다. live S2는 서비스 경로의 실제 provider 호출을 이 저장소에서 관측한 적이 없고(loopback 시뮬레이터만) 비용·품질 증거가 없습니다. Spring 전송 클라이언트(`ExtractionClient`)는 로컬에서 구현했고 호출자가 실행 모드를 명시하지만 그 모드는 서버 승인의 결과를 확인할 뿐 바꾸지 못하며, S2 결과의 앱 쪽 영속화는 없습니다.

## 그래프 버전 읽기 (`/internal/v1/graph-versions`)

설치된 `zoop-ai-graph read|focus` 위의 **세 번째 별도 가족**입니다(스키마 `zoop-ai-internal-graph-1`, scope `graph.read` 하나). 기본은 꺼져 있고 **공개 경로가 아닙니다**. 서비스는 어떤 것도 쓰지 않습니다(그래프 원장·Neo4j·source 원장 쓰기, 새 버전, 포인터, 모델 호출 없음). 자기 원장도 만들지 않으며 `zoop_ai_pipeline`·`neo4j`·SQLite 파일을 import하거나 열지 않고 설치된 CLI를 고정 argv로 실행할 뿐입니다.

| 라우트 | scope | 응답 |
|---|---|---|
| `GET /internal/v1/graph-versions/{versionId}` | `graph.read` | 200 `GraphVersionStatus`: 신원·`state`·`delivery`와, current일 때만 `verification`(그래프·payload digest, 노드·간선 수). 노드·간선·증거·Issue 수 없음 |
| `GET /internal/v1/graph-versions/{versionId}/focus?companyId=&depth=` | `graph.read` | 200 `GraphFocusResult`: current일 때만 `graph`(노드·간선)·`evidence`(보이는 간선이 참조하는 좌표만)·`verification` |

쿼리는 정확히 `companyId`와 `depth` 하나씩이고 `depth`는 정확히 1·2·3입니다(`01`·`4`·중복·모르는 키는 422). `focus.found=false`는 검증된 버전에 그 회사가 없다는 뜻이며 오류가 아닙니다.

**설정(전부 있어야 켜지는 그룹, S2/S3와 별개).** `ZOOP_AI_SERVICE_GRAPH_COMMAND`(설치된 `zoop-ai-graph` 절대 경로), `ZOOP_AI_GRAPH_STATE_DIR`(운영자가 `init`으로 만든 그래프 원장 루트, 서비스는 읽기 전용으로만 넘김), 자기 소유의 `ZOOP_AI_GRAPH_RELATION_STATE_DIR`·`ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR`·`ZOOP_AI_GRAPH_INGESTION_STATE_DIR`(모두 존재하는 디렉터리)·`ZOOP_AI_SERVICE_GRAPH_SOURCES`, `ZOOP_AI_SERVICE_GRAPH_CANONICAL`(서버 소유 canonical 결정 registry, pipeline이 매 호출 다시 읽음), `ZOOP_AI_SERVICE_GRAPH_VERSIONS`(아래 allowlist), `ZOOP_GRAPH_AUTH=none|basic`(`basic`이면 `ZOOP_GRAPH_USER`·`ZOOP_GRAPH_PASSWORD` 필수, `none`이면 금지), 그리고 `ZOOP_STATE_DIR`. 하나도 없으면 모든 graph 라우트가 인증 뒤 409 `execution_unavailable`이고 **일부만 있거나 하나라도 잘못되면 시작을 거부**합니다(exit 78, 변수 이름과 사유 코드만; `graph_group_incomplete`). `ZOOP_GRAPH_AUTH` 하나만으로는 그룹이 켜지지 않습니다(운영자 셸이 pipeline CLI용으로 export했을 수 있음). graph 루트는 서비스·worker·앱 루트와 그래프 자신의 source 루트들과 겹칠 수 없습니다. S2/S3 그룹이 같은 프로세스에 설정돼 있으면 그래프가 읽는 원장이 그 그룹이 쓰는 원장이므로 **같은 경로여야 하고**(`graph_source_inconsistent`), 그때만 그래프 child가 S2/S3의 단일 gate 뒤에서 실행됩니다(정적 결정). 없으면 child가 서로 기다리지 않고 4개까지 동시에 돌며 초과는 503 `service_busy`입니다. Neo4j 대상(URI·database)은 `init`이 원장에 묶어 둔 값이며 argv·환경·요청 어디에도 없고, 자격 증명은 그래프 child 환경에만 들어가 S1·S2·S3 child와 로그·응답에는 나타나지 않습니다.

**버전 allowlist(`ZOOP_AI_SERVICE_GRAPH_VERSIONS`).** 버전 id는 라벨일 뿐이므로 운영자가 principal별로 정확한 `{versionId, graphDigest, payloadDigest}`(선택: `sourceRelation {jobId, inputDigest}` = 동결된 S3 relation job)를 `{"schemaVersion":"zoop-ai-graph-versions-1","versions":[…]}`로 적습니다. 알 수 없는 키·중복 `(principal, versionId)`·모르는 principal은 시작을 거부합니다. 목록에 없으면 존재 여부와 관계없이 같은 403 `version_not_allowed`를 child 이전에 돌려주고 서비스는 원장에 있는 버전을 **채택하지 않습니다**. 파일은 요청마다 다시 읽습니다: slot·gate를 기다린 뒤 child 시작 전, child가 답한 직후 **어떤 결과(current·withheld·`version_not_ready`·404·busy 포함)를 해석하기 전**, 내용을 조립하기 직전에 항목이 그대로여야 하고, 빠지거나 바뀌면 403입니다. 읽을 수 없으면 503 `service_configuration_invalid`. Neo4j store id는 pipeline이 `read`/`focus`에 싣지 않아 고정할 수 없습니다(store 결속은 pipeline 안에서 검증되어 불일치는 withheld).

**전달 규칙.** 내용은 아래가 **모두** 성립할 때만 나갑니다. 버전이 `ready`이고 pipeline이 `delivery.status=current`를 말하며(S3/S2 권한·source grant, 사용된 canonical 결정, S3 검수 상태, Neo4j store 결속, **저장된 전체 그래프**의 동결 digest 일치를 매 호출 다시 검증), 보고된 digest가 allowlist와 같고(선택 source pin도 같음), 허용 목록 투영을 엄격히 통과하며, allowlist 항목이 그대로입니다. 아니면 **200 + `delivery.state=withheld`**와 사유 코드(`source_unauthorized`·`canonical_mapping_changed`·`graph_version_corrupt`·`version_not_ready`·`version_pin_mismatch` …), `verification`·`graph`·`evidence`는 null입니다. `publication`은 항상 `not-published`이고 `current`는 "지금 검증됨"이지 활성 버전이 아닙니다(활성 포인터 없음). 확인과 응답 사이의 철회는 보이지 않고(TOCTOU) 이미 나간 내용은 회수할 수 없습니다. 쓰기 락을 쥔 운영자 writer(`graph_busy`·`relation_busy`·`extraction_busy`·`ingestion_busy`)는 503 `runtime_busy`, DB 무응답은 503 `runtime_unavailable`, 서버 설정·상태 결함은 503 `service_configuration_invalid`이며 모두 `Retry-After`가 붙고 **빈 그래프로 답하지 않습니다**. child deadline은 45초(Neo4j 연결 5초·읽기 트랜잭션 30초 상한 + 원장)이고 실제 대규모 그래프 지연은 측정하지 않았습니다(합성 6노드 world에서 CLI focus p50 약 280ms).

**시험.** `tests/test_graph_unit.py`(설정 닫힘·allowlist 엄격성·exit 해석·투영·전달 규칙·신선도 순서·예시), `tests/test_graph_http.py`(실제 uvicorn + 시험 소유 stand-in 명령: 고정 argv·최소 환경·쿼리 검증·withheld·busy·deadline·동시성·로그), `pipeline_tests/test_graph_real_cli.py`(실제 `zoop-ai-graph`, Neo4j 없이 가능한 거절 경로)는 기본 `service-test`/`service-pipeline-test`에 들어갑니다. 실제 Neo4j 종단은 `scripts/graph_service_smoke.py`(환경이 없으면 skip이 아니라 **실패**)입니다: 운영자 세계를 `graph_tool_bench.py prepare`로 만들고, 서비스 HTTP 응답을 직접 실행한 CLI(oracle)와 손으로 쓴 기대값에 대조하며, principal 격리·digest 불일치·focus 1~3·없는 회사·source 철회·canonical 변경·심은 손상(fail closed)·쓰기 락 busy·실제 deadline·비밀 비노출·원장 불변을 확인합니다.

## AI handoff bundle 읽기 (`/internal/v1/graph-handoffs`)

설치된 `zoop-ai-handoff export` 위의 **네 번째 별도 가족**입니다(스키마 `zoop-ai-internal-handoff-1`, scope `handoff.read` 하나). `graph.read` 가족과 변수·scope·allowlist를 공유하지 않으며 기본은 꺼져 있고 **공개 경로가 아닙니다**. 서비스는 어떤 것도 쓰지 않고(handoff·원장·캐시·source 쓰기, 모델·네트워크 호출 없음) `freeze`·`recover`·`inspect`를 호출할 수 없으며(고정 argv는 `export`뿐), `zoop_ai_pipeline`·SQLite를 import하거나 열지 않습니다. 앱 import·활성화·공개는 하지 않고 응답의 `publication`은 항상 `not-published`, `appImport`는 항상 `pending`입니다.

| 라우트 | scope | 응답 |
|---|---|---|
| `GET /internal/v1/graph-handoffs/{handoffId}` | `handoff.read` | 200 `HdStatus`: 신원·`state`·`delivery`와, current일 때만 `verification`(manifest·bundle·content digest, 바이트 수, bundle 자신의 개수, source job 수, provenance 선언). 노드·source id·제목·본문 없음 |
| `GET /internal/v1/graph-handoffs/{handoffId}/bundle` | `handoff.read` | 200 `HdBundle`: 위와 같은 형제 필드 + current이고 두 pin이 맞을 때만 `manifest`(freeze 때 원장에 동결된 manifest 본문, 닫힌 모델 `HandoffManifest`)와 `bundle`(`zoop-graph-handoff-bundle-7` 전체. 각 issue의 `mentions[]`는 닫힌 `BMention`/`BParticipant` 모델, `fieldProvenance`는 닫힌 `BFieldProvenance`/`BSameValueMentions`/`BMentionRef` 모델, `fieldVerdicts[]`는 닫힌 `BFieldVerdict` 모델, 최상위 비공개 `pathCompanies[]`와 relation의 `structuralPath`·basis의 `businessScope`/`productScope`는 아래 `-5` 문단, 최상위 비공개 `impacts[]`는 `-6` 문단, 각 issue의 `summary`와 `policy.issueSummary`는 `-7` 문단의 닫힌 모델입니다). 백엔드는 이 한 응답으로 `sha256(canonical(manifest))`=`manifestDigest`와 `sha256(canonical(bundle))`=`bundleDigest`를 모두 재계산합니다. 서비스는 manifest 누락·미지 필드(500 `runtime_contract_mismatch`)와 digest·handoffId·선언·정책 버전·파일 해시·source 핀 불일치(500 `runtime_binding_mismatch`)를 거절하며 status·withheld에는 manifest가 없습니다 |

쿼리 파라미터는 **하나도 허용하지 않습니다**(422). 목록·생성·복구 route는 없습니다.

**설정(10개 모두 있어야 켜지는 그룹, S2/S3·graph와 별개).** `ZOOP_AI_SERVICE_HANDOFF_COMMAND`(설치된 `zoop-ai-handoff` 절대 경로), `ZOOP_AI_HANDOFF_STATE_DIR`(운영자가 `freeze`로 만든 handoff 원장 루트, 읽기 전용으로만 넘김), `ZOOP_AI_HANDOFF_RELATION_STATE_DIR`·`ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR`·`ZOOP_AI_HANDOFF_INGESTION_STATE_DIR`(존재하는 디렉터리), `ZOOP_AI_SERVICE_HANDOFF_SOURCES`, 매니페스트가 sha256으로 고정한 운영자 파일 `ZOOP_AI_SERVICE_HANDOFF_CANONICAL`·`ZOOP_AI_SERVICE_HANDOFF_DECISIONS`·`ZOOP_AI_SERVICE_HANDOFF_BINDINGS`, `ZOOP_AI_SERVICE_HANDOFF_EXPORTS`(아래 allowlist), 그리고 모든 그룹이 쓰는 `ZOOP_STATE_DIR`. 일부만 있거나 값이 잘못되면 필드 이름과 사유 코드만 내고 시작을 거부합니다(`handoff_group_incomplete`·`handoff_roots_overlap`·`handoff_source_inconsistent`). S2/S3 그룹이 같은 프로세스에 있으면 같은 루트·registry여야 하고(다르면 시작 거부) 같은 gate를 공유합니다. child 환경은 소유 환경(`ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR`)만이며 그래프 자격·provider 키·토큰 digest·모델 설정은 들어가지 않습니다.

**handoff allowlist(`ZOOP_AI_SERVICE_HANDOFF_EXPORTS`).** handoff id는 라벨일 뿐이므로 운영자가 principal별로 정확한 `{handoffId, manifestDigest, bundleDigest}`(둘 다 필수 sha256 pin: manifest 해시와 canonical bundle 바이트 해시)를 `{"schemaVersion":"zoop-ai-handoff-exports-1","handoffs":[…]}`로 적습니다. 알 수 없는 키·pin 누락·중복 `(principal, handoffId)`·모르는 principal은 시작을 거부합니다. 목록에 없으면(없는 id·다른 principal의 것 포함) 같은 403 `handoff_not_allowed`를 child 전에 돌려줍니다. 파일은 요청마다 다시 읽고 slot·gate 대기 뒤 child 시작 전, child 응답 직후 답의 어떤 부분이든 쓰기 전, 내용 조립 직전에 다시 읽어 바뀌었으면 403입니다.

**전달 규칙.** 내용은 아래가 **모두** 성립할 때만 나갑니다. (1) 생산자가 `ready`·`delivery.status=current`를 말하고(운영자 파일 3개의 매니페스트 pin, S3 권한·S2 upstream pin·grant, 사용한 검수 revision, 재구성한 content digest를 매 export마다 다시 검증), (2) 받은 bundle의 canonical 바이트 sha256이 생산자 receipt와 **운영자 `bundleDigest` pin** 둘 다와 같고 manifest digest가 `manifestDigest` pin과 같으며, (3) bundle이 모든 중첩 수준에서 **닫힌 모델**(`handoff_wire.Bundle`)을 통과하고 모델이 다시 내보낸 canonical 바이트가 해시한 바이트와 정확히 같을 때. 아니면 **200 + `delivery.state=withheld`**와 사유(`source_unauthorized`·`upstream_changed`·`canonical_mapping_changed`·`decisions_changed`·`bindings_changed`·`review_revision_changed`·`handoff_content_changed`·`handoff_not_ready`·`handoff_pin_mismatch`·`handoff_contract_changed`, 요약 pin·basis가 바뀐 `issue_summary_pin_mismatch`·`issue_summary_basis_changed`·`issue_summary_issue_not_public`·`issue_summary_temporal_review_pending`·`issue_summary_input_too_large` …)만 있고 `verification`·`bundle`은 null입니다(개수·source id도 없음). 생산자 receipt와 받은 바이트가 서로 어긋나면 500 `runtime_binding_mismatch`, 닫힌 모델이 거부하면(모르는 중첩 필드, 타입·범위 위반, basis·digest·검증 규칙을 따르지 않는 summary — **digest와 pin을 새 내용에 맞춰 갱신했어도**) 500 `runtime_contract_mismatch`입니다. 둘 다 재시도해도 바뀌지 않으므로 retryable이 아닙니다. 검사들은 서로 다른 시각의 읽기라 그 사이의 철회는 잡지 못하고 이미 나간 내용은 회수되지 않습니다.

**bundle 스키마 `-7`와 이전 handoff.** 서비스의 닫힌 `Bundle` 모델과 receipt 투영(`RtReceipt.bundle_schema`)은 `zoop-graph-handoff-bundle-7`만 받습니다. `zoop-graph-handoff-bundle-1`~`-6`으로 freeze된 handoff는 생산자가 내용 없이 `handoff_contract_changed`로 withheld하며, 서비스는 그 사유 코드만 200 withheld로 그대로 전달하고 옛 receipt·bundle 내용은 어떤 것도 싣지 않습니다(운영자가 새 handoff id를 freeze합니다). `-1`~`-6` 모양의 current 응답(`-4`는 `pathCompanies`·`structuralPath`·basis scope가 없는 모양, `-5`는 `impacts`·`counts.impacts`·`policy.impacts`가 없고 content digest가 여섯 목록 위에 있는 모양, `-6`은 issue `summary`와 `policy.issueSummary`가 없는 모양)은 닫힌 모델이 아니라 receipt 투영에서 500 `runtime_contract_mismatch`로 거절되며 어떤 별칭·변환·보정도 없습니다. issue의 `mentions[]`는 S2 원본 mention 값(문서·버전·S2 local id로 식별, `verification`은 항상 `none`, 참가자의 `role`은 S2 텍스트 그대로)이며 병합된 issue 필드에서 만들어지지 않고 verdict가 있어도 바뀌지 않습니다. 서비스는 이 값들의 의미(partition·시간 정밀도·회사 매핑)를 다시 판단하지 않고 구조만 고정합니다.

`sources[].policies`는 `policy` 값으로 구분하는 닫힌 두 모양입니다. 현재 `zoop-relation-policy-2`에는 기존 일곱 키와 정확한 `countryContext: "zoop-country-context-1"`이 필수입니다. 보존된 `zoop-relation-policy-1`은 원래 일곱 키만 받으며 새 pin을 허용하지 않습니다. 누락·null·빈 문자열·알 수 없는 policy/context 버전이나 두 모양을 섞은 응답은 거부합니다. 이전 모양을 읽더라도 필드나 기본값을 추가하지 않으며, 이전 작업을 실행·재검증하거나 withheld를 current로 바꾸지 않습니다.

**비공개 `pathCompanies`와 `structuralPath`(`-5`).** 최상위 `pathCompanies[]`는 `companies[]`와 같은 닫힌 `{id, canonicalId, label, decisionRef}` 모양이며 id 정렬·유일·최대 20000개이고 `companies`·issue id와 겹치지 않습니다. 완전한 경로의 "매핑된 중간 회사 중 공개 `companies`가 아닌 것" 집합과 정확히 같아야 하며(고아·누락 모두 거절) `counts.pathCompanies`는 그 길이입니다. 공개 노드가 아니라 백엔드가 카탈로그와 경로를 닫기 위한 비공개 지원 참조입니다. 모든 relation은 `structuralPath`(INVOLVES·FOLLOWS는 명시적 `null`)를 가지며, `STRUCTURALLY_RELATED_TO`는 `{status:"complete", companyIds:[P,C]|[P,M,C], links:[{supplierCompanyId, customerCompanyId}]}`(basis마다 링크 하나, 링크 양 끝은 인접 `companyIds`와 같은 쌍, 모두 서로 다름, P는 같은 issue의 INVOLVES 참가자·C는 relation target이자 비참가자) 또는 basis가 2개일 때만 가능한 `{status:"unavailable", reason:"intermediate_company_unmapped"}`입니다. 각 basis는 S3 값을 그대로 복사한 `businessScope`·`productScope`(null 가능, 500 코드포인트 이하 텍스트이며 엔티티 id가 아님)를 가집니다. 이는 운영자가 매핑한 basis 연결일 뿐 인과·가격 방향이나 독립 출처 증명이 아니며, 서비스는 이 구조·연결·닫힘·개수만 검사합니다.

**issue `fieldProvenance`(`-4`).** 각 issue는 닫힌 `fieldProvenance`를 가집니다: `selection`(`unanimous` | `operator-representative`), `verification`(항상 `none`), `withheld`(`eventTime`·`period` 순서의 0~2개: 운영자 HOLD/REJECT 때문에 생산자가 headline을 null로 만든 필드), `sameValueMentions`(`title`·`action`·`target`·`eventTime`·`period`·`assertionStatus` 여섯 키마다 1~1000개의 `{documentId, documentVersion, mentionId}` 참조, 비교 값은 redacted null이 아니라 **선택된 원본 값**). 생산자가 headline 값을 실제로 어떻게 골랐는지만 적으며 **사실 검증·근거 지지·승인이 아니고** 공개 `fieldDecisions`도 아닙니다(`fieldDecisions`는 issue·mention·provenance 어디에도 키로 허용되지 않습니다).

**issue `fieldVerdicts`(`-4`).** 운영자가 원본 mention 하나의 `eventTime` 또는 `period` 값에 내린 판정만 담는 필수 목록(0~2000개, 없으면 `[]` = "판정 없음"이지 "검증됨"이 아닙니다)입니다. 각 항목은 닫힌 키 `documentId`·`documentVersion`·`mentionId`·`field`·`value`(검토한 정확한 값)·`decision`(ALLOW|HOLD|REJECT)·`reasonCode`(stated|unstated|ambiguous|contradicted)·`evidenceIds`(0~20개, 같은 문서의 app evidence 참조)·`verification`(항상 `operator-field-verdict`)·`reviewer`·`decisionRef`·`decisionVersion`입니다. 자유 서술 note·원문 span·AI 판정은 없습니다. 서비스는 키·타입·패턴·한도와 결정/사유/span 개수 조합(ALLOW+stated ≥1, HOLD+unstated 0, HOLD+ambiguous ≥1, REJECT+contradicted ≥1)만 검사하고, mention 결속·value 일치·evidence 닫힘·정렬·withheld 재계산·선택 기준은 생산자와 Java importer가 판단하며 서비스는 판정을 만들거나 선택에서 유추하거나 고치지 않습니다. 공개 `getEvent`/`FieldDecisionOut`으로의 매핑(예: mention별 `fieldDecisions`, `candidateId: null`)은 백엔드 담당의 **권고일 뿐 합의·구현되지 않았고**, 이 서비스는 그 매핑을 하지 않습니다.

**비공개 `impacts`(`-6`).** 최상위 `impacts[]`는 방출된 모든 `INVOLVES` edge의 `sourceRefs`(s3-relation) 하나당 정확히 한 행이며 `(edgeId, sourceRelation.jobId, sourceRelation.relationCandidateId)` 순으로 정렬됩니다. 같은 edge의 서로 다른 source relation은 합치지 않고 따로 남습니다. 행은 닫힌 13개 키(`edgeId`·`issueId`·`companyId`·`sourceRelation`·`impactCandidateId`·`status`·`code`·`label`·`targetVerdict`·`effects`·`verifier`·`verifierRequestDigest`·`proposal`)입니다. `status`는 `not-applicable`(운영자 최종 승인 source: 후보 없음)·`not-proposed`·`no-evidence`·`technical-reject`·`verifier-reject`·`verified`·`withheld`이고 `code`는 technical-reject(`producer_reply_invalid`·`impact_precheck_rejected`·`verifier_reply_invalid`)와 withheld(`impact_evidence_outside_relation_documents`·`impact_quote_ambiguous`)에만 있습니다. `effects`(`positive`·`negative`·`neutral`·`uncertain`: 정렬·유일·서로소·합쳐 1~40개의 app `ev-` id, 모두 번들 evidence이며 edge가 인용한 article version, 한 행 안에서 `source.sourceEvidenceId`는 서로 다름)와 `label`(`uncertain` 또는 target `insufficient`면 `undetermined`, 양쪽이면 `mixed`, 한쪽이면 그쪽, 중립뿐이면 `undetermined`)은 `verified`에만 있습니다. `proposal`은 검증되지 않은 비공개 제안(`verification:"none"`, reason 1~2000·limitations ≤1000 **Unicode code point**)이며 검증된 근거가 아닙니다. label은 한 source relation의 quote 근거가 회사에 미친 효과이지 이벤트의 공개 집계 label도, 인과·가격 확률도 아닙니다. 서비스의 닫힌 모델은 행 단위 상태표와 보이는 전역 닫힘(coverage·정렬·endpoint·source 승인 종류·evidence id·article version·`counts.impacts`·`policy.impacts`·label)을 모두 강제하고, 의미 판단은 생산자와 Java importer가 맡습니다. `-5` 이하 handoff에는 `impacts`가 없으며 그 부재는 "제안 없음"이 아니라 "사용 불가"입니다. content digest는 `companies`·`pathCompanies`·`issues`·`relations`·`impacts`·`evidence`·`articles` 일곱 목록의 canonical sha256입니다.

**issue `summary`(`-7`).** 각 issue는 닫힌 `summary`를 필수로 가집니다(키가 없거나 `null`이면 거절합니다: 옛 모양이나 떨어진 summary는 현재로 읽히지 않습니다). `policy.issueSummary`는 `zoop-issue-summary-policy-1`입니다. 값은 `available`(1~5개 `claims[{claimId c1..cn, text(한 줄, 1~280 code point, 한글 음절 1자 이상), evidenceIds(1~5개, 정렬·유일)}]`, 그 문장을 줄바꿈으로 이은 `text`, claim 근거의 정렬된 합집합 `evidenceIds`, 닫힌 문법 `YYYY-MM-DDTHH:MM:SS[.1~9자리](Z|+HH:MM|-HH:MM)`의 `generatedAt`(ASCII 숫자·대문자 `T`/`Z`, offset 필수·18:00 이하, 실제 달력 날짜·연 0001~9999, 윤초와 compact·공백·주차·ordinal 형 거절. 생산자·앱 verifier와 같은 규칙이며 Python `fromisoformat`이 아니고 이 필드에만 적용), `isr-`+digest({basisDigest, claims})인 `resultVersion`, `language:"ko"`, `source{jobId, inputDigest, resultDigest, basisDigest}`, `producer`·`verifier` 신원) 또는 `unavailable`+`code`입니다. `not-requested`·`temporal-review-pending`·`input-too-large`는 뒤에 job이 없어 `source:null`이고 `producer-invalid`·`verifier-hold`·`verifier-reject`는 실패한 job의 고정된 결과를 `source`로 가리킵니다. 서비스는 생산자의 `issue_summary_contracts`를 이식해 bundle 안의 값만으로 **다시 계산**합니다. (1) 입력 basis는 issue `title`과 모든 `mentions[].evidenceIds`의 합집합(evidence id 순, 각 인용은 article version·offset·`quoteSha256`에 고정, 그 인용을 단 mention이 **모두** background일 때만 `context:"background"`)이며 geography 전용·verdict 전용 근거는 들어가지 않습니다. 그 digest가 `source.basisDigest`와 같아야 합니다. (2) 이슈에 HOLD/REJECT 필드 verdict가 하나라도 있으면(어느 mention이든) 정확히 `unavailable/temporal-review-pending`이어야 하고 `available`을 포함한 다른 값은 bundle 전체를 거절합니다. 해당 조건이 없는데 deterministic 코드가 오는 것도 거절이고 입력 인용이 60개를 넘으면 `input-too-large`입니다. (3) claim 근거는 basis 인용의 부분집합이어야 하고 `resultVersion`과 `source.resultDigest`는 다시 계산한 값과 같아야 합니다. (4) replay bundle의 producer·verifier는 둘 다 `authored-replay`(모델명·reasoning effort 없음, 독립 모델의 판정이 아님)이고 live bundle만 `provider`+`independent-verifier`(모델명·effort 필수)입니다. 위반은 pin·digest를 새 내용에 맞춰 갱신했어도 500 `runtime_contract_mismatch`입니다. 이 값은 verifier가 인용에 대조한 문장이지 사실·투자 조언·인과·가격 확률이 아닙니다. `-6` 이하 handoff에는 summary가 없고 그 부재는 `not-requested`가 아니라 "사용 불가"입니다. 읽기 전용 중계는 summary job을 실행하지도 summary 원장을 열지도 않으며(고정 argv는 `export`뿐) export는 freeze된 불변 artifact의 summary를 쓰고 모델·provider를 부르지 않습니다.

**앱 suppression gate(필수, 구현은 백엔드 소유).** summary의 입력은 claim이 인용한 근거만이 아니라 **basis의 모든 evidence id와 그 article version 전부**입니다. 앱이 asOf 시점·현재 source 권리·읽을 수 있는 article version으로 summary를 보일지 정할 때는 (1) receipt의 issue에서 **필터 전** `mentions[].evidenceIds`의 합집합(= basis 인용 전체)을 구하고 (2) 그 전부가 가시 evidence이며 그 모든 article version이 현재 읽을 수 있을 때만 `AnalysisSummary`를 내고 (3) 하나라도 가려졌으면 요약 전체를 숨깁니다(일부 claim만 남기지 않습니다). snapshot에 보이는 mention만 남긴 집합이나 생산자가 고른 인용만으로 검사하면 가려진 입력이 빠진 채 통과하므로 허용되지 않습니다. `temporal-review-pending`·`input-too-large`·job 쪽 `unavailable`은 요약 문장을 내지 않습니다. 이 서비스는 게이트를 구현하지 않고 계약만 고정하며, 앱 import와 공개 `getEvent` 매핑은 BE 소유입니다.

**bundle 바이트.** `bundle`은 생산자의 산출물 그대로이며 서비스가 추가·삭제·기본값 보정·정규화하는 것은 없습니다(`exclude_unset`로 입력 키만 되돌리고, 되돌린 canonical 문자열이 받은 것과 다르면 거부). `verification.bundleDigest`는 canonical JSON(키 정렬, `,`·`:` 구분자, 비ASCII 비이스케이프)의 UTF-8 바이트 sha256입니다. 숫자는 음이 아닌 정수뿐이고 키는 ASCII뿐이라 어떤 언어의 JSON 파서 + 같은 직렬화도 같은 digest를 냅니다(`pipeline_tests`와 smoke가 JavaScript로 다시 계산해 확인). 서비스 필드(`appImport`·`delivery`·`verification`·`observedAt`)는 `bundle` 밖의 형제입니다. 제목·URL·label·관측·grant 같은 source 유래 값은 데이터이며 권한의 근거가 아닙니다: 전달 여부는 현재 `delivery.state`와 운영자 pin만이 정합니다. 닫힌 모델은 키 집합·타입·패턴·크기 한도(구조)를 고정하고, 참조 닫힘·id 공식·개수·권한 같은 의미 규칙은 생산자가 쓰기 전과 매 export마다 검증하며 서비스는 반복하지 않습니다(예외는 둘: `impacts` 행 상태표와 닫힘, 그리고 바로 위 issue `summary`의 의사결정표).

**한도와 오류.** 생산자의 bundle 상한은 canonical 6 MiB이고 서비스는 child stdout을 16 MiB까지 읽습니다(넘으면 잘라 보내지 않고 503 `runtime_unavailable`). child는 요청당 하나이고 자동 재시도는 없으며 동시 child는 2개(초과 시 503 `service_busy`), deadline 45초입니다. writer가 원장을 잡은 상태(`handoff_busy`·`relation_busy`·`extraction_busy`·`ingestion_busy`)는 503 `runtime_busy`, 손상·변경된 artifact·운영자 파일·소유 설정·복구 필요(`handoff_recovery_required`)는 503 `service_configuration_invalid`, 목록에 있으나 원장에 없는 id는 404 `handoff_not_found`입니다. 모든 503은 `Retry-After`를 갖고 빈 bundle로 답하지 않습니다.

**시험.** `tests/test_handoff_unit.py`(설정 닫힘·allowlist 엄격성·exit·canonical 줄 해석·닫힌 모델을 모든 노드에서 변조·`fieldProvenance`/`withheld`/`fieldVerdicts` 모양 거절과 의미 비판단·결정/사유/span 조합·전달 규칙·예시), `tests/test_handoff_summary_unit.py`(issue `summary`: 손으로 쓴 basis·digest 기대, 여섯 결과 전부와 live 신원, 55가지 내용 변조·hidden id(geography/verdict 전용 근거 포함)·잘못된 basis·잘못된 provenance 거절, 같은 변경을 다시 pin하면 받아들여짐, 60/61 인용 경계, HOLD/REJECT 우선순위, claim 길이·한글 경계, 그리고 `generatedAt` 문법: 생산자·앱 verifier와 **같은 공유 vector 파일** `api/src/test/resources/graph-handoff/summary-time-vectors.json`의 accept·reject 전부와 Python 라이브러리 파서가 받는데 문법이 거절하는 형태), `tests/test_handoff_http.py`(실제 uvicorn + 시험 소유 stand-in 명령: 고정 argv·최소 환경·pin·중첩 모르는 필드와 verdict 자유 서술 note·원문 span 키 거절·`fieldProvenance`/verdict 모양 변조·`-1`~`-6` 모양 거절·`impacts` 행 상태표·coverage·정렬·label·effects·source 승인 위조·길이(Unicode code point)·count/policy/digest를 digest를 다시 봉인한 채 변조·같은 edge의 상반 행 보존·summary 결과별 바이트 동일 중계와 status에 summary 없음과 운영자 상태 무변경·digest·pin을 다시 맞춘 summary 변조(내용·hidden id·basis·provenance)의 500 거절·JS digest·withheld·busy·deadline·동시성·로그), `pipeline_tests/test_handoff_real_cli.py`(실제 `zoop-ai-handoff`와 S3 job 두 개 세계: CLI export와 바이트 동일, 생산자 검증기 통과, issue별 `fieldProvenance`의 동치·닫힘과 verdict의 모양·결속·withheld 재계산을 독립적으로 재확인, 생산자 세계의 손으로 쓴 `impacts`·`summary` 기대와 일치, status에 impact 내용 없음, 권한 철회·운영자 파일 변경 withheld→복원, 그리고 **서비스 모델과 설치된 생산자 `validate_bundle`이 summary 156개 fixture·변조(시간 문법 포함)에 같은 판정을 내는지의 차분 시험**)는 기본 `service-test`/`service-pipeline-test`에 들어갑니다. 서비스 시험·smoke는 판정을 만들거나 선택에서 유추하지 않으며 실제 verdict 입력은 생산자 fixture가 제공하고, 없으면 빈 `fieldVerdicts`·빈 `withheld`만 확인합니다. 종단 smoke는 `make service-handoff-smoke`(`scripts/handoff_service_smoke.py`, Neo4j 불필요, pipeline 설치가 없으면 skip이 아니라 **실패**)입니다. 생성된 [내부 OpenAPI](../../docs/api/internal-ai-openapi.yaml)가 계약이며 백엔드 사용 주의는 [인수 문서](../../api/docs/GRAPH_READ_HANDOFF.md)에 있습니다.

## Handoff 영향 ID 조회 (`POST /internal/v1/graph-handoffs/exposure`)

`queryGraphHandoffExposure`는 일반 export를 먼저 호출하지 않고 설치된 `zoop-ai-handoff-exposure`를 한 번 실행합니다. 별도 scope `handoff.exposure`가 필요하며 `handoff.read`와 어느 방향으로도 권한을 포함하지 않습니다. 현재 source 권리가 철회되어 bundle 전달이 withheld인 뒤에도 고정 기록의 영향 ID를 조회할 수 있지만, handoff allowlist의 허용이 철회되면 조회도 거절합니다.

**독립 설정.** 다음 다섯 변수는 전부 없으면 비활성화이고, 일부만 있거나 값이 잘못되면 시작을 거절합니다. 기존 서비스 기본 설정과 소유 경계용 `ZOOP_STATE_DIR`는 그대로 필요합니다. 실제 환경 파일은 자동으로 수정하지 않습니다.

| 변수 | 값 |
|---|---|
| `ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_COMMAND` | 설치된 `zoop-ai-handoff-exposure` 실행 파일의 절대 경로 |
| `ZOOP_AI_HANDOFF_EXPOSURE_STATE_DIR` | 기존 handoff 원장 루트 |
| `ZOOP_AI_HANDOFF_EXPOSURE_EXTRACTION_STATE_DIR` | 기존 S2 원장 루트 |
| `ZOOP_AI_HANDOFF_EXPOSURE_INGESTION_STATE_DIR` | 기존 ingestion 원장 루트 |
| `ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_EXPORTS` | 기존 `zoop-ai-handoff-exports-1` 형식의 principal별 manifest/bundle pin allowlist |

세 루트는 서로 및 앱·서비스·S1 상태와 겹칠 수 없고 symlink를 허용하지 않습니다. 함께 설정된 S2/S3·graph·일반 handoff 그룹과 원천 루트가 같아야 하며, 일반 handoff가 있으면 handoff 루트와 allowlist 파일도 같아야 합니다. exposure만 켤 때는 source registry·canonical·decisions·bindings·S3 원장·모델/graph 자격 증명이 필요하지 않으며 다른 그룹도 켜지지 않습니다.

챗봇을 함께 켜면 `ZOOP_AI_CHAT_STATE_DIR`도 이 세 원장 루트와 같거나 그 상위·하위 경로일 수 없습니다(`chat_roots_overlap`). 일반 handoff가 꺼져 있어도 이 검사는 적용됩니다. 챗봇이나 S2/S3의 live 설정·키가 있어도 exposure child에는 전달되지 않습니다.

**입출력.** 요청은 기존 닫힌 `zoop-handoff-exposure-1` 계약입니다. `handoffIds`는 중복 없는 명시적 ID 1~20개이고, `changed`는 문서·source·grant 또는 `(jobId, relationCandidateId)` 쌍의 `s3-relation`입니다. 문서의 `documentVersion`·`rawVersion`, grant의 `revision`은 필수 nullable 필드입니다. null은 그 신원의 모든 고정 버전/리비전을 뜻하며 handoff 선택의 wildcard는 아닙니다. 인증·scope 확인 뒤 JSON/UTF-8, 중복 키·비유한 숫자·알 수 없는 필드를 검사하고 선언/스트리밍 본문 모두 65,536바이트로 제한합니다. query parameter·job 등록·idempotency 요구·캐시·자동 재시도·부분 성공은 없습니다.

성공은 `200 {"schemaVersion":"zoop-ai-internal-handoff-1","report":…}`입니다. report는 생산자 출력 그대로이며 닫힌 중첩 모델로 키·타입·신원·선택 전체·정렬/중복·개수·고정 한계 문구·모델/공급자 호출 0을 검증합니다. 정규화가 생기거나 canonical JSON 한 줄이 아니거나 newline 포함 6 MiB를 넘으면 전달하지 않습니다. 서비스는 영향 전파를 다시 계산하지 않으며, **report의 manifest/bundle pin과 allowlist를 비교할 뿐 받지 않은 bundle 바이트의 해시를 계산했다고 주장하지 않습니다.** 기사·이슈·관계·근거 식별자 외에 제목·label·URL·본문·인용문·자유 진단을 추가할 수 없습니다.

**실행과 철회.** 전체 선택을 한 allowlist snapshot으로 허가한 뒤 두 reader slot 및 같은 프로세스 S2/S3 writer의 `RelationGate`를 사용합니다(gate 대기 10초, child deadline 45초). 대기 뒤·child 종료 뒤 오류 해석 전·응답 직전에 전체 선택의 같은 항목을 다시 확인합니다. 중간 철회는 성공과 오류를 모두 숨깁니다. 이들은 별도 시점의 읽기이며 최종 확인 직후 철회를 원자적으로 막는 보장은 아닙니다. source 계열은 ingestion/extraction 경로를 넘기고 S3 관계 철회는 handoff 경로만 넘깁니다. child는 자격 증명 없는 환경·익명 stdin·서버 소유 cwd·폐기되는 stderr를 사용합니다. 공통 runner의 16 MiB stdout 파일 크기 확인은 종료 후 검사이지 실시간 디스크 quota가 아닙니다.

| 상황 | HTTP / code |
|---|---|
| 미인증 / scope 없음 / 선택 중 미허용·변경 항목 | 401 `authentication_required` / 403 `scope_denied` / 403 `handoff_not_allowed` |
| 비활성 / 선택 중 누락·history·손상·미준비 / pin 불일치 | 409 `execution_unavailable` / `handoff_selection_unmappable` / `handoff_pin_mismatch` |
| 잘못된 요청 / 모르는 신원 / 미사용 관계 / 생산자 보고서 상한 | 422 `invalid_request` / `changed_identity_unknown` / `changed_relation_unused` / `exposure_report_limit` |
| 본문 상한 / media type | 413 `request_too_large` / 415 `unsupported_media_type` |
| slot·gate·원장 경합 / 실행 불가·timeout / 운영자 설정·원장 오류 | 503 `service_busy`·`runtime_busy` / `runtime_unavailable` / `service_configuration_invalid` |
| 잘못된 report / 요청 결속 불일치 / 알 수 없는 생산자 오류 | 500 `runtime_contract_mismatch` / `runtime_binding_mismatch` / `internal_error` |

오류는 기존 `HdErrorEnvelope`만 쓰며 영향 ID·부분 report·CLI detail을 싣지 않습니다. 기록은 있으나 선택된 handoff에 연결되지 않은 신원은 완전한 빈 report가 될 수 있지만 모르는 신원은 오류입니다. 앱은 네 receipt 신원을 대조하고 버전별 제외·정정·복구·revision·활성화를 별도로 처리합니다. 빈 결과나 더 작은 결과가 기존 제외를 해제하지 않습니다.

공통 runner가 child 시작 뒤 출력 상한 초과나 I/O 오류를 보고해도 읽기 전용 exposure는 503 `runtime_unavailable`로 응답하며 자동 재시도하지 않습니다. 호출자가 다시 조회할 수 있다는 뜻이지 이전 요청을 서비스가 재실행한다는 뜻은 아닙니다. 같은 상황에서 챗봇은 모델 요청을 보냈을 수 있으므로 502 `stage_outcome_unknown`으로 응답하고 재송신을 허용하지 않습니다.

**검증 명령(별도 실행).** `ai/service/.venv/bin/python -m pytest ai/service/tests`와 `ai/service/.venv/bin/python -m pytest ai/service/pipeline_tests`는 서로 다른 프로세스로 실행합니다. 새 실제 HTTP/CLI smoke는 `ai/service/.venv/bin/python ai/service/scripts/handoff_exposure_service_smoke.py`입니다. 설치된 CLI, 실제 loopback HTTP, 기존 synthetic replay world와 손으로 작성된 영향 기대값을 사용하며 source 철회 뒤 조회·일반 export withheld·기록된 빈 결과와 모르는 신원·선택 전체 실패·원장 경합·원장/앱 무변경을 검사합니다. 이는 실기사 품질·모델 성능·배포 검증이 아닙니다.

## 챗봇 모델 단계 (`/internal/v1/chat-stages/{stage}`)

챗봇 오케스트레이터가 모델 단계 하나(`chat-router` 네이티브 Jev, `chat-answer` Luna, `chat-verification` 네이티브 Jev, `chat-agent` Luna Responses + ZOOP MCP 한 단계)를 **동기**로 실행하는 다섯 번째 가족이다. scope는 `chat.invoke`이며 설치된 `zoop-ai-chat invoke`만 고정 argv로 실행한다(단계 계약 `zoop-ai-chat-4`, 규칙은 [AI 런타임 준비 §11](../../docs/development/ai-runtime-setup.md)). 검증의 `requestBinding.invocationId`가 호출 ID와 다르면 child 실행 전에 거절한다. worker는 구간·요구·버전에 결속된 서버 조회 사실을 검증하며 출처 grant v1 계약은 그대로 유지한다. 아래 그룹이 없으면 인증 뒤 409 `execution_unavailable`이다.

| 변수 | 규칙 |
|---|---|
| `ZOOP_AI_SERVICE_CHAT_COMMAND` | 설치된 `zoop-ai-chat`의 절대 경로(실행 가능) |
| `ZOOP_AI_CHAT_STATE_DIR` | 호출 원장(`chat.sqlite3`) 디렉터리. 없으면 0700으로 만든다(부모는 있어야 함). 이미 있으면 이 사용자 소유의 실제 디렉터리(symlink 아님)이고 group·world 권한이 없어야 하며, 그 안의 원장 파일(`chat.sqlite3`, `-wal`, `-shm`)도 이 사용자 소유의 일반 파일이고 비공개여야 한다. 아니면 기동을 거부한다(`state_dir_not_private`, `ledger_not_private`). 기존 경로를 chmod로 고치지 않는다. 서비스·worker·앱 상태와 겹쳐도 거부 |
| `ZOOP_AI_SERVICE_CHAT_GRANTS` | 운영자 챗봇 grant registry(`schemaVersion: zoop-ai-chat-1`). S1 registry와 별도 |
| `ZOOP_AI_SERVICE_CHAT_REPLAY` | 선택. authored replay fixture. 없으면 `mode=replay`는 409 `execution_unavailable` |
| 챗봇 live | `ZOOP_AI_CHAT_LIVE_ENABLED=1`과 양수 `ZOOP_AI_CHAT_MAX_CALLS`가 모두 있을 때만 이 둘과 `ZOOP_AI_API_KEY`·`TYPESAFE_API_KEY`가 **챗봇 child에만** 전달된다. 모델·endpoint 이름(`ZOOP_AI_CHAT_ANSWER_MODEL`·`_REASONING_EFFORT`, `ZOOP_AI_CHAT_AGENT_MODEL`·`_REASONING_EFFORT`, `ZOOP_AI_CHAT_MCP_SERVER_URL`(chat-agent grant가 갈 수 있는 유일한 MCP 서버), `ZOOP_AI_CHAT_JEV_MODEL`, `ZOOP_AI_BASE_URL`, `TYPESAFE_BASE_URL`)은 항상 전달된다. S1·파이프라인 게이트는 이 child를 열지 않는다 |

- 챗봇 원장은 함께 설정된 S2/S3·graph·handoff·exposure의 모든 원장 루트와도 분리한다(`chat_roots_overlap`). S2/S3와 exposure는 같은 `RelationGate`로 직렬화하지만, 별도 원장을 쓰는 챗봇은 이 gate를 공유하지 않는다.

- 본문은 `StageRequest`(`schemaVersion`, `invocationId`, `stage`, `mode`, `input`)이고 `Idempotency-Key`는 `invocationId`와 같아야 하며 경로의 stage와 본문 stage가 같아야 한다. child는 `<principal>:<invocationId>`를 받으므로 principal끼리 원장 행을 공유하지 않는다.
- **200**은 stage 결과다. `status=failed`도 200이며 `failure.sent`·`failure.unknown`이 송신 여부와 결과 불명을 말한다. **502/504 `stage_outcome_unknown`**은 child가 보냈을 수 있다는 뜻이므로 그 invocation을 다시 보내지 않는다. **503**(`runtime_unavailable`, `service_busy`, `service_configuration_invalid`)은 보내지 않았다는 뜻이다. `runtime_unavailable`은 child가 **시작조차 못 한** 경우에만 쓰고, 시작한 뒤의 출력 상한 초과나 출력 읽기 오류는 502 `stage_outcome_unknown`이다.
- child 결과는 **고치기 전에** 검사한다. 다음을 모두 만족해야 200이고, 하나라도 어긋나면 caller id로 바꿔 200으로 정규화하지 않고 502 `stage_outcome_unknown`이다.
  - `invocationId`가 정확히 `<principal>:<invocationId>`이고, stage가 경로와 같으며, receipt의 `executionMode`가 요청 mode와 같다.
  - answer가 그 stage의 닫힌 모델(`RouterAnswer`/`ChatAnswer`/`VerificationAnswer`, 모르는 키 거절)을 따른다.
  - 성공에는 answer·receipt가 있고 failure가 없다. 실패에는 failure가 있고 answer가 없다. `unknown`이면 `sent`이고, receipt는 `sent`일 때만 있다.
- 동시 child 4개, 슬롯을 1초 안에 얻지 못하면 503 `service_busy`. child 기한은 stage 상한 + 3초(라우터 7초, 답변 28초, 검증 9초).
- 시험: `tests/test_chat_unit.py`(child 없음), `tests/test_chat_http.py`(실제 uvicorn + 기록용 stand-in CLI). 실제 worker CLI는 `ai/worker/tests/test_chat_stages.py`.

### MCP 연결 preflight (`GET /internal/v1/chat-mcp-health`)

같은 `chat.invoke` scope와 chat 설정 그룹 아래에서 `zoop-ai-chat probe-mcp`를 실행한다. 본문·Idempotency-Key·grant·모델 호출·원장 행은 없고 live 호출 예산도 쓰지 않는다. child가 운영자 설정 URL에 내용 없는 MCP `ping`을 보내며 endpoint 자체의 `401` Bearer challenge만 `mcp=reachable`로 인정한다. timeout·연결 실패·앞단 gateway의 502/503/504·그 밖의 예상 밖 status/challenge는 **200** `mcp=unreachable`과 각각 `mcp_timeout`·`mcp_connect_failed`·`mcp_unavailable`·`mcp_status_unexpected` reason이다. URL 누락·형식 오류는 503 `service_configuration_invalid`, 비정상/계약 밖 child 출력은 502 `probe_failed`, 5초 service deadline 초과는 504 `probe_failed`다.

이 route는 실행 전 경로 선택에 필요한 관측만 제공한다. Java의 endpoint별 circuit breaker와 direct adapter 선택은 애플리케이션 책임이며, probe 자체가 circuit을 저장하거나 실행 중 MCP 실패를 direct 결과로 교체하지 않는다. stage child의 4개 슬롯과 별도인 probe 전용 2개 슬롯을 쓴다. agent 단계가 stage 슬롯을 모두 잡고 있어도 probe가 `service_busy`로 막혀 정상 MCP를 미확인으로 만들지 않는다.

## 네트워크와 한계

- 서비스는 `127.0.0.1`에만 묻습니다. 운영에서는 같은 호스트/네임스페이스의 HTTPS reverse proxy가 TLS, 본문 2,000,000B 상한, `Authorization` 비로깅을 맡고 App SG에서만 접근되게 해야 합니다. **이는 가정이며 관측·배포한 사실이 없습니다**(WBS 6.11.2/8의 실관측 과제).
- 동시 CLI 호출은 4개(초과 시 503 `service_busy`), pending dispatch는 1,000개(초과 시 503 `queue_full`)입니다. dispatcher는 직렬입니다(replay ordinal이 ledger 전체 순서이므로). 처리량 향상은 지연 측정 뒤 결정합니다.
- live 모드의 빈 회차 outlook job은 모델 호출이 없어 호출 기록이 없으므로 recipient를 증명할 수 없다. 그래서 `result`는 `recipient_unproven`으로 내용을 내보내지 않는다(실패 시 닫힘, 허용된 현재 동작이며 receipt/상태 조회는 영향이 없다).
- 재시작한 서비스는 이전 child의 pid를 모르므로 종료하지 않습니다. 매달린 child는 job lock을 잡은 채 `busy`로 폴링되며 운영자가 끝내야 합니다.
- 런타임의 `input_or_configuration_invalid`는 클라이언트 입력 오류와 서버 I/O 오류가 섞여 있습니다. 서버 입력(grant registry, worker 명령, worker state 접근)을 제출 전후로 확인해 깨끗할 때만 422이고, 그렇지 않으면 안정적인 503 `service_configuration_invalid`입니다. 런타임에 별도 코드가 생기면 이 보수적 분류를 좁힐 수 있습니다.
- 배포(이미지/호스트/프로세스 관리/프록시), 앱 백엔드 통합, 릴리스 artifact 포함은 **승인되지 않았습니다.** `scripts/package_artifacts.py`는 이 프로젝트를 포함하지 않습니다.

## 검증

`tests/`는 실제 uvicorn 프로세스(127.0.0.1)에서 HTTP 경계를 검사하며, 목적에 따라 설치된 `zoop-ai` 또는 시험 소유의 CLI 대역을 사용합니다. 대역 시험은 잘못된 출력·시간 초과·권한 변경 등 전송 경계만 증명하며, 실제 pipeline 실행은 `pipeline_tests/`와 각 설치 CLI smoke로 별도 확인합니다. 자격 증명은 시험마다 메모리에서 만든 합성 값이며 저장소에는 토큰도 digest도 없습니다. 모델은 호출하지 않습니다. live 경로 시험은 `127.0.0.1`의 loopback provider를 사용하고 외부 네트워크는 쓰지 않습니다. 프로세스 충돌 시험은 `tests/launcher.py`가 실제 컴포넌트를 감싸 정해진 경계에서 서비스를 SIGKILL하며 프로덕션 코드에는 그런 hook이 없습니다.

CI의 `ai-service` 작업은 4-worker 병렬 전체 시험(느린 테스트 30개 시간 출력)·loopback smoke·내부 OpenAPI drift 검사를 모두 유지하며 전체 실행 제한은 25분이다. 이는 개별 HTTP 요청이나 CLI child의 timeout을 늘리는 설정이 아니다.

| 파일 | 증명 |
|---|---|
| `test_config.py` | 설정 실패 닫힘(exit 78, 값 미출력, listener 없음), 중복 인스턴스, worker 원장 binding |
| `test_auth_owner.py` | 401 동일 응답, 403, `/docs` 404, 타 소유자 404/409와 런타임 무변경 |
| `test_submit_idempotency.py` | 멱등 202/200, key·본문 불일치, 크기·형식 한도, live/replay 불가, 동시 중복 요청 |
| `test_flow_replay.py` | 4종 replay, `result.job`이 `zoop-ai get`과 동일, cache hit, 실패는 job 데이터 |
| `test_recovery.py` | 소유 의도·등록·응답 전·claim 후 크래시, 차단된 replay 보고, loopback 호출 수로 재송신 없음 |
| `test_interrupted.py` | 단계 사이 중단·재시작·비정상 child 뒤 새 모델 요청이 자동으로 나가지 않음(`needs_recover`), 명시적 recover만 이어 감, 원장 결과 쓰기 1회 실패 뒤 쓰기만 재시도 |
| `test_cancel_cost.py` | 취소 중 receipt 보존, verify 미송신, 대기 job 취소 |
| `test_privacy.py` | 현재 grant 철회 시 withheld, 허용 목록 View, 응답·헤더·로그의 비밀 부재, stderr 비중계 |
| `test_dispatch_policy.py`, `test_ledger.py` | 정책 표 전체, `next` 순서, receipt 증명, 원장 불변·release 규칙 |
| `test_boundary.py`, `test_openapi.py` | import 경계, argv·이름 있는 파일 부재, 남은 orphan worker 정리 증명(`pgrep` 오류와 no-match 구분), OpenAPI 최신성·scope 일치·예시 실동작 |

### S3 relation job 시험 (설치된 pipeline 필요, `make service-pipeline-test` / `service-pipeline-smoke`)

`pipeline_tests/`는 **기본 `service-test`와 분리**돼 있습니다(서비스 lock에 pipeline이 없기 때문). `ai/pipeline/.venv`(`make pipeline-install`, 공개 의존성만·토큰 불필요)가 없으면 **skip이 아니라 실패**합니다. 시험은 pipeline 인터프리터로 `build_world.py`를 실행해 실제 `zoop-ai-ingest` subprocess와 READY S2 job, 실제 저장 후보에서 도출한 authored producer/verifier fixture로 **새 운영자 세계**를 만들고, 서비스는 설치된 `zoop-ai-relation`으로만 연결합니다. 서비스 코드는 `zoop_ai_pipeline`을 import하지 않습니다. 운영자의 ingestion·extraction 디렉터리는 모든 시험 뒤 바이트·mode·크기가 같아야 합니다.

| 파일 | 증명 |
|---|---|
| `tests/test_relation_unit.py`(기본 `service-test`, pipeline 불필요) | all-or-nothing 설정 닫힘, upstream allowlist 엄격성·즉시 반영, 정책 표, 원장 불변·in-flight 처리, 허용 목록 투영(해시·claim·자유 텍스트 history 제거, 무효 citation 문장 미전달), exit 2 해석, 비활성 라우트 409, 예시 검증 |
| `pipeline_tests/test_relation_flow.py` | submit→status→result가 pipeline `inspect`와 일치, 멱등 202/200·충돌, 경로·fixture·live 지정 거부, 동시 중복 제출은 1회 실행, 상태·오류·로그에 원문 없음 |
| `pipeline_tests/test_relation_authority.py` | principal 격리, 비허용 upstream 403(존재 여부 비노출, 저장·child 0), 운영자 job 채택 거부, allowlist·source grant 철회 시 withheld, 읽을 수 없는 allowlist 닫힘 |
| `pipeline_tests/test_relation_recovery.py` | 최초 dispatch 1회(재시작 포함), claim·child 종료 뒤 자동 재실행 없음, submit 구간별 충돌, reserve된 호출 무응답 child는 재전송 없이 `reconciling`, 저장된 receipt 재사용, deadline 초과, stopped의 명시적 recover 반복, 점유된 원장 busy 재시도 |
| `pipeline_tests/test_relation_cancel.py` | queued 취소, ready 취소 409(pipeline이 영구 withheld로 만드는 취소를 막음), recover coalesce·409 |
| `tests/test_relation_review_unit.py`(기본 `service-test`, pipeline 불필요) | 최종 승인 결정 트리 전체: 모의 child로 거절·busy·timeout·비정상 종료·withheld 각각이 예약을 푸는지 유지하는지, 이전 시도가 있으면 쓰기 전에 체인을 읽는지, 이벤트 필드 하나라도 다르면 채택하지 않는지, 재생·충돌·다른 principal·allowlist, 이전 계약 행이 dispatch·채택·승인 해석을 받지 않고 `review_contract_changed`로만 남는지 |
| `pipeline_tests/test_relation_review.py` | allow=최종 승인(200, 새 source revision=expected+1, 재검증·verifier·모델 호출 0, `approvalBasis`), reject, stale version·revision은 어디에도 기록하지 않음, 본문 엄격성·reviewer 위조 불가, 같은 key 동시 호출=1 operation, principal·scope 격리, 점유된 pipeline에서도 operation 조회, allowlist·source grant 철회 |
| `pipeline_tests/test_relation_review_recovery.py` | review 반영 직후·record 직전 크래시에도 이벤트 1개, 운영자가 먼저 쓴 이벤트는 채택하지 않음, 서비스를 SIGKILL한 뒤 살아남은 review child의 정확한 이벤트 채택, 이전 계약 원장을 다시 연 서비스가 그 행을 바꾸지 않음 |
| `pipeline_tests/test_live_flow.py` | 실제 uvicorn 서비스 + 설치된 `zoop-ai-extract`·`zoop-ai-relation` + 실제 `LiveRuntime`이 loopback 시뮬레이터 두 개(OpenAI chat, native Jev `POST /v1/systemone`; `build_live_world.py`가 호스트, 실제 provider 아님)와 통신하는 종단 시험. live S2(등록·`initial-only` 1회·결과·정확한 계정), live S3의 gate·핀·등록(`live_unavailable`·`live_not_approved`·`live_binding_mismatch`), **실제 live S3 resume**(`ready`, 받은 영수증 수 = provider가 받은 요청 수, 각 키는 자기 provider에만 감), **유효한 simulated Jev HOLD → HTTP allow 한 번이 최종 승인**(provider 요청 추가 0, `dispatchCount` 1 유지, 멱등 재생도 호출 0), **응답 없는 live 호출은 `reconciling`/`reconcile_only`/`operator_reconcile`이며 자동·recover 재전송 없음**, **live 그룹 없이 재시작한 pending live S3 dispatch가 `live_unavailable`로 idle, child·키·recover 없음**, 키가 live 외 child에 가지 않음 |

> 위 `test_live_flow.py`의 provider는 결정적 loopback 시뮬레이터이므로 실제 모델 품질·비용의 증거가 아니고, 이 저장소에서 **유료 HTTP 경로를 실행한 적은 없습니다.** Main의 실제 CLI 유료 pipeline+Neo4j 실행(14회 호출, 추정 USD 0.013323880)은 서비스를 거치지 않았고 S1 유료 호출 주장도 하지 않습니다.
> 아래 관측(10/13)은 allow 뒤 재검증을 포함하던 **이전 검수 계약**의 이력입니다. 현재 계약의 관측: `pytest ai/service/pipeline_tests/test_live_flow.py ai/service/tests/test_relation_review_unit.py` **57 passed**(2026-10-21, 유료 호출 0), Main의 실제 `api-ai-pipeline-smoke` 13개 통과(서비스 6개, provider 호출 0)와 Java 전체 845개(808 통과, 37 skip). 전체 `make service-test`/`service-pipeline-test`의 최종 실행은 Main의 몫입니다.

관측(10/13, 로컬 작업 트리, Main 실행, 이전 계약): 이전 검수·재검증 slice 뒤 `make service-test` 403 tests, `make service-pipeline-test` 59 tests, 실제 `make service-pipeline-smoke`가 통과했다. 이 수치와 재검증 smoke 내용은 현재 계약의 증거가 아니다.

### S2 extraction job 시험 (설치된 pipeline 필요, `make service-pipeline-test` / `service-pipeline-smoke`)

시험은 같은 새 운영자 세계(실제 ingestion + authored fixture)를 쓰되 서비스 쪽 S2 원장은 **비어 있는 상태**에서 시작하고, 서비스가 만든 job은 운영자가 만든 job과 `inputDigest`까지 같은 요청·fixture에서 나옵니다. 모든 S2 child는 시험 소유 stand-in 명령(실제 `extraction_cli` 앞에 네트워크 audit hook을 걸고, 필요하면 엔진 안에서 child를 한 번 죽이거나 fixture를 child 직전에 회전시킴)으로 실행하며 서비스·pipeline에는 hook이 없습니다. 서비스 크래시는 `tests/launcher.py`의 `ZOOP_TEST_EXTRACTION_CRASH_AT`·`ZOOP_TEST_EXTRACTION_HOLD_FILE`로 정해진 경계에서 SIGKILL합니다(실제 컴포넌트를 감쌀 뿐). 모델과 네트워크는 쓰지 않으며 audit hook이 시도 자체를 기록·거부합니다.

| 파일 | 증명 |
|---|---|
| `tests/test_extraction_unit.py`(기본 `service-test`, pipeline 불필요) | all-or-nothing 설정 닫힘(선택 topic 변수 단독도 불완전), S3와의 공유 루트·S3 단독 그룹 동작 유지, provider 키가 child 환경에 없음, 승인 파일 엄격성(digest 검증·topic pin 짝·중복·모르는 principal), Authority 표(`approval_revoked`·`approval_changed`·fixture 코드·읽을 수 없는 파일 닫힘), 원장 고정 열 불변·release·dispatch 규칙·루트 binding, S2 busy 코드만 재시도, 두 문이 서로의 스키마를 거부, 호출자 본문은 3필드뿐, 상태·내용 투영(알려지지 않은 필드 제거, 필수 필드 누락 닫힘), 비활성 라우트 409 |
| `pipeline_tests/test_extraction_flow.py` | submit→status→result가 pipeline `inspect`와 일치하고 `inputDigest`가 운영자 job과 같음, 의미 있는 후보·비교·disposition·토픽 보존, 위조 스냅샷·카탈로그·경로·fixture 본문 422(ledger·child 0), 미승인 digest·다른 principal·없는 job은 같은 403, principal 격리, 정확한 재전송의 고정 신원과 변경된 요청 충돌, 동시 4중 제출=1 job, 운영자 job 채택 거부, cancel 의미, 오류 경로에도 네트워크 시도 0 |
| `pipeline_tests/test_extraction_authority.py` | 승인 철회·변경·digest 변경·source 철회·읽을 수 없는 승인 파일의 withheld(내용 0), fixture 회전·분실·승인 재고정이 job을 다시 묶지 못함, child 직전 회전은 사후에 닫힘(receipt hash), 등록 중 producer 교체는 `runtime_binding_mismatch`, 회전된 fixture·승인으로는 신규 제출·dispatch·recover가 child 없이 거절, 예약된 신원은 회전된 승인에 다시 묶이지 않음 |
| `pipeline_tests/test_extraction_recovery.py` | 최초 dispatch 1회(재시작 포함), claim·child 종료 뒤 자동 재실행 없음, submit 구간별 크래시(등록 뒤·확인 전 포함)에도 job 1개, reserve된 호출 무응답 child는 재전송 없이 `reconciling`, 저장된 receipt 재사용, deadline 초과, stopped의 명시적 recover 반복과 고정 fixture 교체로는 복구 불가, 점유된 원장 busy 재시도, 실행 도중 busy는 `stopped`이고 서비스가 재시도하지 않음 |
| `pipeline_tests/test_extraction_chain.py` | **S2 HTTP ready → 운영자의 명시적 S3 upstream 허용 → S3 HTTP ready**를 같은 서비스·같은 gate에서 실행(허용 전 S3는 403), 두 가족이 각자의 권한에 답함(S2 승인 철회는 S3 허용 목록을 건드리지 않고 그 반대도 같음, 공유 registry 철회는 둘 다 withheld), S2·S3 child가 같은 원장에서 충돌하지 않음 |

`scripts/extraction_service_smoke.py`(`make service-pipeline-smoke`의 첫 줄)는 같은 흐름을 실제 프로세스로 한 번씩 확인하고 마지막에 체인을 실행하며 운영자의 ingestion 디렉터리가 바이트 단위로 같은지 증명합니다.

**범위와 상태.** S3 검수·재검증 HTTP slice와 S2 extraction job HTTP slice(제출·조회·결과·취소·복구, S2→S3 체인)는 로컬에서 완료했다. 이 두 가족의 Spring 전송 클라이언트(`ExtractionClient`·`RelationClient`, [api AI 연동](../../api/docs/AI_INTEGRATION.md#s2-추출s3-관계-클라이언트))는 로컬에서 구현했고 실제 서비스·설치된 pipeline replay 종단 gate(`api/scripts/ai_pipeline_gate.py`)로 검증했다(원격 CI에서는 실행되지 않았다). 목록 라우트, S2·S3 결과의 앱 쪽 영속화·import, 사용자 격리·공개 endpoint, 승인 항목의 운영 절차는 아직 없다(S1 문서 요약·기업 판정의 앱 DB 저장은 [문서 분석](../../api/docs/DOCUMENT_ANALYSIS.md)에 있다).

Spring 클라이언트 종단 관측(2026-10-14, 로컬 작업 트리, Main 실행): 전체 Java 시험 187개 통과(실패 0, skip 0)와 `assemble`, 이 서비스를 실제로 띄우는 `api/scripts/ai_pipeline_gate.py`(`make api-ai-pipeline-smoke`)는 Java 13개 통과·서비스 6개·provider 호출 0·네트워크 시도 0·운영자 ingestion·extraction 상태 변경 없음이었고, S1 gate는 9개 통과했다. 이 실행에서 서비스 코드는 바뀌지 않았고 서비스 시험(`service-test`, `service-pipeline-test`)은 다시 실행하지 않았다. 커밋·푸시·원격 CI·배포는 하지 않았다.

관측(10/13, 로컬 작업 트리, Main 실행): `make service-test` 461 tests, `make service-pipeline-test` 96 tests(설치된 pipeline 통합), 실제 `make service-pipeline-smoke`(S2 → S3)가 통과했다. smoke는 저장된 receipt가 stage 완료 전에 남은 경우의 재사용(추가 호출 0), 승인·source 철회와 fixture 회전의 withheld, 크래시 뒤 중복·유실 없음, 그리고 S2 HTTP ready → 운영자의 명시적 S3 upstream 허용 → S3 HTTP ready(관계 2개, S2 replay 3회, S3 replay 5회, provider 호출 0, 자동 권한 상승 없음)를 확인했다. OpenAPI 재생성 뒤 drift 0, `make public-check`는 생성물 275개 차이 없음·하드 오류 0·문서 검사 21개 통과였다. 이 관측 당시에는 커밋·푸시·원격 CI·배포를 하지 않았고 replay는 authored 응답이라 실제 모델 품질의 증거가 아니다. 당시 팀 분기 `fix/17-erd-v6-alignment`(`af2f0e3`)는 병합 전이었고 이후 main `91113ce`(PR #18)로 병합됐다. 병합은 `ai/`를 바꾸지 않았고 이 시험들은 병합 뒤 다시 실행하지 않았다.
