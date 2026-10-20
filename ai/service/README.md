# ai/service — 내부 HTTP transport (S1 분석, S2 추출, S3 관계 job, 읽기 전용 그래프·handoff)

앱 백엔드가 S1 분석(`document-summary`, `document-sentiment`, `semantic-verification`, `briefing-outlook`, 계약 `zoop-ai-s1-1`)을 제출·조회·취소·복구하는 **내부 전용 HTTP 서비스**입니다. 같은 프로세스가 별도 리소스 가족으로 S2 이벤트·토픽 후보 job(`/internal/v1/extraction-jobs`, 기본 꺼짐)과 S3 관계·영향 후보 job(`/internal/v1/relation-jobs`, 기본 꺼짐)도 노출합니다. FastAPI/uvicorn이며 **설치된 `zoop-ai`(S2는 `zoop-ai-extract`, S3는 `zoop-ai-relation`) CLI만** 호출합니다. `zoop_ai`·`zoop_ai_pipeline`·BFF를 import하지 않고 worker의 `worker.sqlite3`와 pipeline의 `extraction.sqlite3`·`relation.sqlite3`·`ingestion.sqlite3`를 열지 않습니다. 런타임 원장이 작업 상태의 유일한 출처이고 이 서비스는 소유자·멱등·고정된 승인 신원·dispatch 상태만 별도 `service.sqlite3`(S1), `extraction-jobs.sqlite3`(S2), `relation-jobs.sqlite3`(S3)에 둡니다.

> **로컬 준비 상태입니다.** 배포·보안 그룹·TLS 프록시는 확인되지 않았고 승인되지 않았습니다. 원격 CI는 `5cf208e`의 [실행 38226220631](https://github.com/Donbug/zoop/actions/runs/38226220631)에서 8개 작업이 모두 통과했고 실제 Java 클라이언트 → 이 서비스 → 설치된 `zoop-ai` replay 종단 시험을 포함합니다. Spring 전송 클라이언트(`api/src/main/java/com/zoop/ai`)가 이 HTTP를 소비하고, S1 문서 요약·기업 판정은 operator 전용 비웹 실행([문서 분석](../../api/docs/DOCUMENT_ANALYSIS.md))이 결과를 앱 PostgreSQL에 저장합니다(로컬 구현·검증). 공개 인증, 분석을 읽는 공개 경로, S2·S3·`briefing-outlook` 결과의 앱 import, 배포는 아직 없습니다. 실제 모델 호출, 외부 뉴스, 실제 토큰은 쓰지 않았습니다. **S2 extraction job 라우트와 S3 relation job 라우트(아래 별도 절)는 이후 추가했고 원격 CI에서 실행된 결과는 아직 관측하지 않았습니다. 이 두 가족도 Spring 전송 클라이언트(`ExtractionClient`·`RelationClient`)가 로컬에서 소비하며 실제 서비스·설치된 pipeline replay 종단 gate(`api/scripts/ai_pipeline_gate.py`)로 검증했지만, S2·S3 결과의 앱 DB 저장·import와 사용자 격리·공개 endpoint는 없습니다.** S2-1 수집(`zoop-ai-ingest`)은 운영자 파일 입력이므로 HTTP로 열지 않습니다. S2-2 추출(`zoop-ai-extract`)은 호출자가 스냅샷·카탈로그·fixture를 보낼 수 없는 **서버 사전 승인 요청** 참조 모델로만 엽니다.

> **경계.** 이 서비스는 pipeline의 비공개 Neo4j 버전 projection(`zoop-ai-graph`, FS080 일부)을 **읽기 전용 두 라우트**(`/internal/v1/graph-versions`, 아래 별도 절)로만 감싸고, 별개로 AI handoff bundle의 **읽기 전용 두 라우트**(`/internal/v1/graph-handoffs`, 아래 절)를 제공합니다. 버전 생성(`init`·`freeze`·`project`·`recover`)·게시·활성화·FS081 철회·목록·호출자 Cypher는 없고, Neo4j write 자격과 쓰기 명령은 pipeline 운영자 프로세스만 갖습니다. 공개 API·Spring 클라이언트·활성 포인터는 없습니다([pipeline README](../pipeline/README.md), [AI 실행 계약](../../docs/design/ai-system.md), [백엔드 인수 문서](../../api/docs/GRAPH_READ_HANDOFF.md)).

```bash
make service-install           # uv sync --project ai/service --frozen --group dev (공개 의존성만, 토큰 없음)
make service-test              # 실제 uvicorn + 설치된 zoop-ai + authored replay
make service-smoke             # 실제 프로세스 smoke (replay 4종 + recover + loopback cancel/restart)
make service-openapi-check     # docs/api/internal-ai-openapi.{json,yaml} 생성 drift
make service-pipeline-test     # S2 extraction + S3 relation job: 실제 uvicorn + 설치된 zoop-ai-extract·zoop-ai-relation + 새 운영자 세계 (make pipeline-install 필요, 없으면 실패)
make service-pipeline-smoke    # 같은 조건의 실제 프로세스 smoke (S2 제출·조회·승인/fixture 회전·모호 child·재시작 → 명시적 S3 허용 → S3, S3 조회·격리·철회·모호 child·재시작, 검수 allow→재검증·reject·충돌·크래시 복구)
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

이 서비스는 같은 프로세스에서 **별도 리소스 가족**으로 S3 관계·영향 후보 job의 제출·상태·결과·취소·복구와 HOLD 후보의 검수(allow/reject)·재검증을 노출합니다(스키마 `zoop-ai-internal-relation-1`, scope `relation.submit|read|cancel|recover|review`). S1의 `zoop-ai-internal-1` 와이어·상태 기계와 섞이지 않고 S1 라우트·원장은 그대로입니다. 목록 라우트는 없고, `eligible`은 자동 증거 gate이지 승인·게시가 아닙니다. upstream은 운영자가 준비한 S2 job이거나 S2 가족(`/internal/v1/extraction-jobs`, 아래 별도 절: 서버 사전 승인 요청의 digest만 받는 별도 가족)이 만든 job이며, 어느 쪽이든 S3 upstream 허용은 운영자 allowlist가 따로 정합니다.

| 메서드·경로 | scope | 성공 | 의미 |
|---|---|---|---|
| `POST /internal/v1/relation-jobs` | `relation.submit` | 202 새로 접수 / 200 멱등 재전송 | 본문은 S3 `Submit`(`zoop-relation-s3`)과 정확히 같다. `Idempotency-Key`=`jobId`. |
| `GET …/{jobId}` | `relation.read` | 200 `RelationJobStatus` | 요청마다 `zoop-ai-relation inspect`로 읽은 상태. **내용 필드 없음.** |
| `GET …/{jobId}/result` | `relation.read` | 200 `RelationResultEnvelope` | ready이고 모든 전달 gate가 열려 있을 때만 `job`(후보), 아니면 `delivery.state=withheld`+사유 코드. |
| `POST …/{jobId}/cancel` | `relation.cancel` | 200 / 409 `job_already_terminal` | 취소된 job은 멱등. **ready는 409**: pipeline `cancel`은 ready job도 영구 withheld로 만들기 때문에 상태를 먼저 읽고 ready는 pipeline에 넘기지 않는다. |
| `POST …/{jobId}/recover` | `relation.recover` | 202 enqueue / 200 coalesced | 명시적 `resume`. `reconciling`은 409 `reconcile_required`, ready·cancelled는 409 `job_not_recoverable`. |
| `POST …/{jobId}/reviews` | `relation.review` | 202 allow 접수 / 200 reject 기록·멱등 재전송 | 본문은 정확히 `{relationCandidateId, expectedSourceVersion, expectedSourceRevision, decision}`. `Idempotency-Key`가 안정적인 operation id. reviewer는 인증된 principal이며 요청으로 보낼 수 없다. |
| `GET …/{jobId}/reviews/{operationId}` | `relation.read` | 200 `RelationOperationStatus` | key로 operation을 정확히 조회한다. 서비스 원장만 읽으므로 pipeline이 바빠도, 크래시 뒤에도 조회된다. |
| `POST …/{jobId}/reviews/{operationId}/recover` | `relation.recover` | 202 재큐 / 200 이미 확정·진행 중 | 체인을 먼저 읽고, 이미 증명되는 결과(verdict 또는 뒤이은 reject)가 있으면 확정하고, 없으면 재검증을 다시 큐에 넣는다. |

**설정(전부 있어야 켜지는 그룹).** `ZOOP_AI_SERVICE_RELATION_COMMAND`(설치된 `zoop-ai-relation` 절대 경로), `ZOOP_AI_RELATION_STATE_DIR`(서비스가 **유일한 writer**, 서비스 원장이 이 경로 해시에 묶임), `ZOOP_AI_EXTRACTION_STATE_DIR`·`ZOOP_AI_INGESTION_STATE_DIR`(운영자가 쓰고 서비스는 읽기 전용으로만 pipeline에 넘김), `ZOOP_AI_SERVICE_SOURCES`(pipeline source/grant registry), `ZOOP_AI_SERVICE_RELATION_REPLAY`·`ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY`(authored fixture), `ZOOP_AI_SERVICE_RELATION_UPSTREAMS`(아래 allowlist), 그리고 `ZOOP_STATE_DIR`. 하나도 없으면 기능이 꺼져 모든 relation 라우트가 인증 뒤 409 `execution_unavailable`이고, **일부만 있거나 하나라도 잘못되면 시작을 거부**(코드 78, 변수 이름과 이유 코드만)합니다. 여섯 상태 루트(서비스·worker·앱·relation·extraction·ingestion)는 서로 겹치면 안 됩니다. child 환경은 S1과 같은 최소 값에 `ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR`(설치된 pipeline의 소유권 설정)만 더합니다. 요청은 경로·registry·fixture·command·live를 고를 수 없고 본문 모델이 이를 거부합니다.

**upstream 허용 목록.** S2 job은 운영자 프로세스가 만들거나, S2 가족(`/internal/v1/extraction-jobs`, 아래 별도 절)이 서버 사전 승인으로 만들므로 어느 쪽이든 호출자가 `upstream {jobId, inputDigest}`를 적는다고 권한이 생기지 않습니다. `ZOOP_AI_SERVICE_RELATION_UPSTREAMS` 파일(`{"schemaVersion":"zoop-ai-relation-upstreams-1","upstreams":[{"principal","jobId","inputDigest"}]}`, 알 수 없는 키·중복·모르는 principal 거부)이 principal별 정확한 쌍만 허용하며, 목록에 없으면 존재 여부와 관계없이 같은 403 `upstream_not_allowed`를 ledger·child 이전에 돌려줍니다. 파일은 사용할 때마다 다시 읽으므로 항목을 빼면 다음 요청부터 반영되고, 읽을 수 없으면 닫힙니다(503 `service_configuration_invalid`).

**소유권.** job은 제출한 principal의 것입니다(S1과 같음). 다른 principal의 job, 예약만 된 job, 없는 job은 모두 같은 404이고 같은 jobId를 다른 principal이 제출하면 409 `job_id_unavailable`입니다. pipeline의 `submit`은 이미 있는 id에 대해 저장된 job을 그대로 보고하므로, 첫 시도는 먼저 `inspect`로 그 id가 pipeline 원장에 없음을 확인합니다. 있으면 예약을 풀고 409(운영자가 만든 job을 채택해 읽는 일을 막음).

**접수와 dispatch.** 인증→헤더→본문(엄격한 `Submit`)→(소유자·본문 digest 조회)→allowlist→**`reserved` 기록**→(첫 시도면 채택 검사)→`zoop-ai-relation submit`(fixture·호출 0, 등록만)→**`accepted`+초기 dispatch 1개를 한 transaction으로 기록**→202. `submit`이 결과를 못 주면(timeout·응답 유실) **같은 gate 안에서 `inspect`로** 등록 여부를 확인합니다. 등록돼 있으면 이어 가고, 없음이 증명되면 예약을 풀고, 판단할 수 없으면 예약을 유지해 소유자의 같은 재시도만 완료하게 합니다. 한 번에 하나의 relation child만 실행합니다. pipeline은 원장 락을 기다리지 않으므로(`relation_busy`) 서비스가 전역 gate로 직렬화하고, 요청은 gate를 최대 10초 기다린 뒤 503 `runtime_busy`(`Retry-After`)입니다. 점유 중에는 오래된 상태를 돌려주지 않습니다.

**재실행 정책(자동 재전송 없음).** 최초 dispatch는 pending 행을 **한 번** claim해 `resume`합니다. 이후는 모두 명시적 `recover`입니다. timeout·비정상 종료·읽을 수 없는 출력의 child와, 죽은 서비스가 in-flight로 남긴 행은 **모호**하므로 `idle`(`transport_unknown`, `service_restarted`, `next=recover`)로 끝나고 자동으로 다시 실행하지 않습니다(S1과 달리 pipeline에는 under-lock `--initial-only` 표지가 없다). 유일한 자동 재시도는 pipeline이 락을 여는 단계에서, 즉 어떤 효과도 일어나기 전에 내는 `relation_busy`이며 지수 backoff 최대 8회입니다. reserve됐으나 응답이 기록되지 않은 호출은 pipeline이 `reconciling`으로 만들고 다시 보내지 않으며 `recover`는 409 `reconcile_required`입니다. 이 정책은 pipeline이 replay 전용(`live_mode_unsupported`)이어서 반복이 비용을 만들 수 없다는 사실에 기대지 않지만, 실제 S3를 연다면 pipeline에 under-lock initial-only 표지가 먼저 필요합니다.

**결과 전달.** 내용은 아래가 **모두** 같은 응답 시점에 성립할 때만 나갑니다. 호출자가 소유자이고, pipeline이 `ready`이며 `delivery.status=current`(source registry·ingestion binding·정확한 S2 export를 매 호출 다시 읽음)이고, 서버 allowlist가 아직 그 소유자의 upstream을 허용하며, 본문이 허용 목록 투영을 엄격히 통과합니다. 아니면 `delivery.state=withheld`와 사유(`job_not_ready`, `source_unauthorized`, `upstream_not_allowed`, `job_cancelled`, `projection_invalid` …)만 돌려주고 receipt는 단계·상태·verdict 코드만 담습니다. 투영은 artifact·raw/mapping hash, fixture·요청·응답 digest, claim·quote 표, `creatorJobId`, 운영자 CLI 검수의 `reviewer`·`note` 자유 텍스트, 실패 `detail`을 버리고, 검증되지 않은 citation의 generator 문장은 전달하지 않습니다. **한계:** 이 확인들은 서로 다른 시각의 읽기이므로 확인과 응답 사이에 일어난 철회는 보이지 않고, 이미 받은 내용은 회수할 수 없습니다. 또한 `delivery.state=available`은 그 시점의 검사 결과일 뿐 앱 import의 권한 재확인을 대신하지 않습니다.

**검수(review)·재검증과 원천 버전·revision.** 팀의 개정 ERD·계약 분기(`fix/17-erd-v6-alignment` af2f0e3)는 main `91113ce`(PR #18)로 병합됐고, 병합된 ERD v6와 공개 OpenAPI(`docs/api/openapi.yaml`)가 정한 규칙, 즉 결정이 대상별 앱 `expectedRevision`과 별도로 AI 원천의 `expectedSourceVersion`·`expectedSourceRevision`을 함께 받는다는 규칙을 이 내부 계약의 근거로 씁니다. 이 서비스의 값은 둘 다 **런타임 원천 값**입니다. `sourceVersion`은 S3 job의 `inputDigest`(job마다 불변이고 S2 upstream의 `inputDigest`가 아니다)이고, `sourceRevision`은 해당 relation 후보의 pipeline 이벤트 체인 revision(이벤트 수)을 10진 문자열로 적은 값입니다. 둘은 `GET …/result`의 relation마다 나옵니다(`relations[].sourceVersion`·`sourceRevision`, 후자는 `eligibility.revision`과 항상 같은 수). **앱의 `review_targets.current_revision`·`review_decisions.global_revision` 같은 앱 revision은 이 서비스가 받지도 전달하지도 않으며, 이 값들을 서로 바꿔 쓰면 안 됩니다.**

검사는 둘 다 정확히 일치해야 하고 하나라도 다르면 **아무것도 기록하지 않습니다**. 새 결정의 `expectedSourceVersion`은 job의 불변 `inputDigest`와 비교하고(예약 전, 409 `source_version_conflict`), `expectedSourceRevision`은 pipeline `review`의 `expectedRevision`으로 넘겨 **pipeline의 append transaction 안에서** 비교합니다(409 `source_revision_conflict`). HOLD가 아닌 후보는 409 `review_target_not_hold`, 이미 allow가 대기 중이면 409 `review_already_pending`, 취소된 job은 409 `job_cancelled`, 없는 후보는 404 `relation_candidate_not_found`입니다. 이 거절들은 예약을 풀기 때문에 같은 key로 고친 요청을 다시 보낼 수 있습니다. 같은 key와 같은 본문은 그 사이 relation이 앞으로 갔어도 기존 operation을 돌려주고(200), 다른 본문이나 다른 job은 409 `idempotency_conflict`, 다른 principal의 key는 409 `operation_id_unavailable`이며 다른 principal의 job·operation은 404입니다.

**검수 순서와 모호한 append의 조정.** 인증·scope→헤더·엄격한 본문→소유한 job→(같은 key의 operation이 있으면 소유자·본문 digest 비교, 확정됐으면 200)→upstream이 지금 allowlist에 있는지(403)→`expectedSourceVersion`→**operation 예약을 원장에 영속(`reserved`)**→`zoop-ai-relation review`→체인에서 **정확한 이벤트를 증명**→**확정(`applied`)과, allow면 재검증 dispatch 1개를 한 transaction으로 기록**→202(allow)/200(reject). reviewer는 principal, `note`는 operation id에서 만든 marker(`zoop-ai-service-review:<operationId>`)라서 "내 append가 반영됐는가"가 추측이 아니라 체인 조회가 됩니다. child가 timeout·비정상 종료·읽을 수 없는 출력으로 끝나거나 이전 시도가 있었던 재시도에서는 **쓰기 전에 읽습니다**. 이벤트가 정확히 `seq=expected+1`·`reviewer`·`decision`·`expectedRevision`·`effect`·marker까지 모두 일치할 때만 채택하고(확정 시각은 pipeline이 적은 `createdAt`을 함께 기록), 일부만 맞으면 모순(500 `runtime_binding_mismatch`)이며 채택하지 않습니다. **이전 시도가 있었던 재시도에서는 pipeline의 거절도 부재의 증명이 아닙니다.** 서비스가 죽으면 그 서비스가 시작한 review child는 별도 세션이라 살아남을 수 있고, 아직 pipeline 원장 락을 잡기 전이면 재시도가 체인을 읽은 뒤에 이 child가 같은 operation의 정확한 이벤트를 append할 수 있습니다. 그러면 재시도의 child는 `review_revision_conflict`로 거절되지만 이벤트는 이미 있습니다. 그래서 첫 시도의 거절만 확정으로 보고, 재시도의 거절은 **체인을 다시 읽어** 정확한 이벤트가 있으면 채택(202)하며, 읽을 수 없거나 모순이면 예약을 유지하고(503 `review_unconfirmed`·500), 체인이 expected를 지났는데 marker 이벤트가 없으면(예: 운영자의 이벤트) 그때만 풀어서 키를 현재 revision으로 다시 쓸 수 있게 합니다. 체인과 job의 상태만으로 정해지는 거절(`review_target_not_hold`·`review_already_pending`·`job_cancelled`·`relation_candidate_not_found`)은 체인에 우리 이벤트가 없으면 풀고, `review_revision_conflict`는 체인이 움직였다는 말일 뿐이라 체인이 우리 이벤트 없이 움직였음을 보여 줄 때만 풉니다. 체인을 읽을 수 없으면(점유·권리 철회로 withheld·파싱 불가) 판단하지 않고 예약을 유지한 채 503 `review_unconfirmed`(재시도 가능, **같은 key·본문으로 다시 보내면** 위 순서가 이어집니다)를 돌려줍니다. 운영자 CLI가 직접 쓴 검수 이벤트는 marker가 없으므로 어떤 operation도 채택하지 않습니다.

**operation 상태는 세 가지를 따로 보여 줍니다.** `review`(결정이 런타임 원장에 기록됐는가: `applied`·`unconfirmed`, `resultingSourceRevision`=expected+1), `revalidation`(allow가 요청한 자동 재확인: `not_requested`·`queued`·`running`·`verified`+verdict의 eligibility와 `resultingSourceRevision`·`superseded`·`interrupted`·`failed`·`cancelled`, 실패 코드는 `lastRuntimeCode`), `publication`(항상 `not_published`: 이 서비스는 아무것도 게시하지 않고 `verified`·`eligible`도 승인이 아니다). 조회는 key 하나로 operation·후보·결정·reviewer·두 기대값을 그대로 돌려주고 서비스 원장만 읽습니다. `next`는 `wait`·`recover`·`retry_review`·`operator_reconcile`·`none`입니다.

**재검증은 같은 dispatcher의 큐입니다.** 확정된 allow는 재검증 dispatch 1개를 갖고 job의 `resume`과 같은 단일 gate·FIFO 순서·상한(1,000)·재시작 규칙을 따릅니다(상한은 아직 `reserved`인 allow도 센다). dispatch 직전에 소유자가 그 upstream에 아직 허용되는지 allowlist를 다시 읽고, 아니면 child 없이 `upstream_not_allowed`로 끝냅니다(`failed`, 소유자의 명시적 recover로만 이어 감). 재검증 child는 자동 재전송이 없습니다. 모호하게 끝난 child와 재시작한 서비스가 남긴 in-flight 행은 `interrupted`(`transport_unknown`·`service_restarted`)이고, pipeline은 한 attempt에 호출을 한 번만 만들고 시작된 호출을 다시 보내지 않으므로 반복되는 `revalidate`는 **저장된 receipt를 마무리하거나 아직 시작되지 않은 호출을 한 번 보내는 것**이 전부입니다. receipt가 저장된 채 verdict만 커밋되지 않은 경우 recover는 fixture 없이 receipt로 verdict를 붙입니다. 응답을 받지 못한 호출은 job이 `reconciling`이 되고 recover는 409 `reconcile_required`입니다. recover는 항상 **체인을 먼저 읽습니다**: 뒤따르는 verdict가 있으면 `verified`, 뒤따르는 reject가 있으면 `superseded`로 확정하고 아무것도 dispatch하지 않으며, relation이 review가 남긴 revision에서 아직 기다릴 때만 재큐합니다. 재검증이 도는 동안 job은 `running`이라 결과 전달은 `job_not_ready`로 withheld입니다.

**reject와 늦은 allow.** 대기 중인 allow 위에 reject를 올릴 수 있고(`expectedSourceRevision`은 allow가 남긴 revision), 그 뒤에 도는 allow의 재검증은 pipeline이 `review_revision_conflict`로 거절하며 서비스는 체인을 읽어 `superseded`로 확정합니다. reject보다 먼저 만든 오래된 allow가 reject를 덮어쓰는 일은 없고(추가된 verdict 없음), reject 뒤의 새 allow는 409입니다. 확정은 write-once인 종결 상태이므로 이 읽기(`inspect` probe)와 `revalidate` 결과는 다른 모든 pipeline 읽기와 똑같이 claim의 **job·`inputDigest`·upstream**에 묶인 뒤에만 쓰입니다. relation 후보 id는 같은 upstream을 쓰는 job들 사이에서 반복될 수 있어서, 다른 job이나 다른 입력·upstream의 유효한 사슬이 같은 verdict·reject를 보여 주더라도 이 operation을 확정하지 않고 `runtime_binding_mismatch`로 `failed`(확정 없음, recover로 다시 실행 가능)로 남깁니다. delivery가 current가 아닌 응답도 확정에 쓰지 않습니다.

**호환·마이그레이션 결정.** (1) 서비스 원장 `relation-jobs.sqlite3`의 스키마를 `zoop-ai-relation-jobs-ledger-1`→`-2`로 올립니다. `-2`는 `relation_operations` 테이블과 job·재검증이 공유하는 dispatch 순서(`CREATE TABLE IF NOT EXISTS`)만 더합니다. `-1` 원장은 열 때 제자리에서 앞으로만 이전되고(기존 행은 다시 쓰지 않음), 이후·외부 스키마는 거절합니다. (2) **pipeline은 바꾸지 않았습니다**(`ai/pipeline` 변경 없음, 새 의존성·필드·migration 없음). 필요한 marker·`expectedRevision`·이벤트 기록(`reviewer`·`note`·`createdAt`·`expectedRevision`)이 이미 pipeline의 `review`·`revalidate`·`inspect`에 있습니다. (3) S3 호출자에게 보이는 변경은 additive입니다: 새 scope `relation.review`(기존 principal 설정은 그대로 유효), 새 라우트 3개, result relation의 `sourceVersion`·`sourceRevision`, 오류 봉투의 선택 필드 `operation`. 기존 5개 라우트의 의미와 상태 코드는 같습니다. (4) 앱 쪽 영속화(`review_targets`·`review_decisions`)는 이 작업의 범위가 아니며 팀 분기가 main에 들어온 뒤에 이 계약에 맞춥니다. Spring 전송 클라이언트(`RelationClient`: `review`·`operation`·`recoverOperation`, AI 원천 `expectedSourceVersion`·`expectedSourceRevision`만 전달하고 앱 revision 필드는 없음)는 이후 로컬에서 구현했습니다([api AI 연동](../../api/docs/AI_INTEGRATION.md#s2-추출s3-관계-클라이언트)).

**한계.** 목록 라우트는 없습니다(S2 HTTP는 위 별도 가족으로 제공합니다). HOLD 후보의 allow/reject는 위 검수 라우트로 하고, 운영자 CLI가 직접 쓴 검수 이벤트는 체인에 남지만(전달 내용에서는 자유 텍스트 없이) 어떤 operation도 그것을 자기 것으로 채택하지 않습니다. 한 서비스 프로세스가 pipeline 원장의 유일한 writer라는 것은 배포 규칙이며 코드가 강제하지 않습니다(운영자 CLI가 같은 원장을 쓰면 `relation_busy`가 나거나, 그 사이 취소·채택의 TOCTOU가 남습니다). dispatcher는 직렬이고, pipeline의 `resume`·`revalidate`가 300초 deadline 안에 끝나는지는 실측하지 않았습니다. 재검증은 authored replay만 쓰며 원격 모델은 호출하지 않습니다. pipeline에는 검수 목적·수신자 검사가 없어 live S3를 열기 전에 먼저 필요합니다. S3 child와 S2 child는 같은 gate를 씁니다(S3가 읽는 S2 원장을 S2 child가 쓰기 때문).

## S2 추출 job (`/internal/v1/extraction-jobs`)

설치된 `zoop-ai-extract`(S2-2: 이벤트·토픽 후보, 계약 `zoop-extraction-s2-2`) 위의 **별도 가족**입니다. 응답 스키마는 `zoop-ai-internal-extraction-1`, scope는 `extraction.submit|read|cancel|recover`, 원장은 `extraction-jobs.sqlite3`(스키마 `zoop-ai-extraction-jobs-ledger-1`, 추출 상태 디렉터리 실경로 해시에 묶임)이며 S1·S3의 wire 계약·원장·상태 기계와 아무것도 공유하지 않습니다. replay 전용이고 모델·네트워크 경로가 없습니다.

| 라우트 | scope | 응답 | 의미 |
|---|---|---|---|
| `POST /internal/v1/extraction-jobs` | `extraction.submit` | 202 신규 / 200 멱등 재전송 | 본문은 **정확히** `{schemaVersion:"zoop-extraction-s2-2", jobId, approvedRequestDigest}`. `Idempotency-Key`는 `jobId`와 같아야 한다. |
| `GET …/{jobId}` | `extraction.read` | 200 `ExtractionJobStatus` | pipeline `inspect`를 이 요청 안에서 읽은 상태. 내용 필드(후보·인용·digest)는 절대 없음. |
| `GET …/{jobId}/result` | `extraction.read` | 200 `ExtractionResultEnvelope` | ready이고 모든 전달 gate가 열려 있을 때만 `job`(이벤트·토픽 후보), 아니면 `delivery.state=withheld`+사유 코드. |
| `POST …/{jobId}/cancel` | `extraction.cancel` | 200 / 409 `job_already_terminal` | queued·running·stopped·reconciling은 `cancelled`로 끝나고(대기 중 dispatch 종료, 이미 도는 child는 죽이지 않음), 취소된 job은 멱등. **ready는 409**: S2 pipeline `cancel`은 ready job을 건드리지 않으므로 그대로 ready로 남고 서비스가 그 사실을 알린다. |
| `POST …/{jobId}/recover` | `extraction.recover` | 202 enqueue / 200 coalesced | 명시적 `resume`. `reconciling`은 409 `reconcile_required`, ready·cancelled는 409 `job_not_recoverable`, 승인·fixture가 바뀌었으면 403 `request_not_approved`·409 `approval_changed`·409 `fixture_changed`. |

**설정(전부 있어야 켜지는 그룹, S3 그룹과 별개).** `ZOOP_AI_SERVICE_EXTRACTION_COMMAND`(설치된 `zoop-ai-extract` 절대 경로), `ZOOP_AI_SERVICE_EXTRACTION_REPLAY`(authored producer fixture), `ZOOP_AI_SERVICE_EXTRACTION_APPROVALS`(아래 사전 승인), 그리고 S3와 **공유하는 세 변수** `ZOOP_AI_EXTRACTION_STATE_DIR`(S2 원장; S2 child가 writer, S3는 같은 원장을 읽기 전용으로 엶), `ZOOP_AI_INGESTION_STATE_DIR`(운영자가 쓰고 pipeline은 읽기 전용), `ZOOP_AI_SERVICE_SOURCES`(pipeline source/grant registry), 그리고 `ZOOP_STATE_DIR`. 선택 변수는 `ZOOP_AI_SERVICE_EXTRACTION_TOPIC_REPLAY`(토픽 단계를 요청하는 승인에만 필요) 하나이며 이것만 있으면 불완전 그룹입니다. 하나도 없으면 기능이 꺼져 모든 extraction 라우트가 인증 뒤 409 `execution_unavailable`이고, **일부만 있거나 하나라도 잘못되면 시작을 거부합니다**(exit 78, 변수 이름과 사유 코드만 출력, `extraction_group_incomplete`). 공유 세 변수는 두 그룹이 같은 값을 읽으므로 S2와 S3의 루트·registry가 서로 어긋날 수 없고, S2 그룹이 켜져 있으면 공유 변수만으로 S3 그룹이 켜지지 않습니다(S3 자기 변수가 있으면 S3도 전부 있어야 함). 서비스·worker·앱·추출·ingestion 다섯 상태 루트는 서로 겹칠 수 없고 추출·ingestion 디렉터리는 먼저 존재해야 합니다. child 환경은 소유 루트 두 개뿐이며 provider 키·URL·모델·live 스위치는 환경에 있어도 복사하지 않습니다.

**서버 사전 승인(`ZOOP_AI_SERVICE_EXTRACTION_APPROVALS`).** 호출자는 pipeline의 S2 `Submit`을 보내지 못합니다. 운영자 파일(`{"schemaVersion":"zoop-ai-extraction-approvals-1","approvals":[{"principal","jobId","approvedRequestDigest","request","producerReplayDigest","topicReplayDigest"}]}`, 알 수 없는 키·중복 `(principal, jobId)`·모르는 principal 거부)이 principal+jobId+digest를 **정확한 S2 `Submit` 본문**(스냅샷·카탈로그·incoming 관측·토픽 요청)과 그것이 실행될 fixture 바이트의 SHA-256에 대응시킵니다. 서비스는 읽을 때마다 `request`의 정규 JSON digest가 `approvedRequestDigest`와 같은지, `request.jobId`가 항목의 `jobId`와 같은지, replay 전용 provenance인지, `topic` 요청과 `topicReplayDigest`가 정확히 짝인지(`topic`이 있으면 선택 fixture가 설정돼 있어야 함)를 검증하고, 하나라도 어긋나면 시작을 거부하거나 닫힙니다. 목록에 없으면 존재 여부와 관계없이 같은 403 `request_not_approved`를 ledger·child 이전에 돌려줍니다. **승인은 pipeline이 허용하는 것을 좁힐 뿐입니다.** pipeline은 내용을 다루는 모든 명령에서 운영자 source registry를 다시 읽으므로 승인이 있어도 registry가 막으면 읽히지 않습니다. 파일은 사용할 때마다 다시 읽고 읽을 수 없으면 닫힙니다(503 `service_configuration_invalid`).

**소유권·고정된 신원.** job은 제출한 principal의 것이고 다른 principal의 job·예약만 된 job·없는 job은 모두 같은 404, 같은 jobId를 다른 principal이 제출하면 409 `job_id_unavailable`입니다. pipeline의 `submit`은 이미 있는 id에 대해 저장된 job을 그대로 보고하므로 첫 시도는 먼저 `inspect`로 그 id가 pipeline 원장에 없음을 확인하고, 있으면 예약을 풀고 409(운영자가 만든 job을 채택해 읽는 일을 막음)입니다. **예약은 `submit` 전에 영속합니다**: 소유자·호출자 본문 digest와 함께 그 순간 승인이 고정한 값, 즉 승인된 요청 digest, producer fixture digest, (있으면) 토픽 fixture digest, 그리고 pipeline이 보고해야 하는 `inputDigest`(`digest({request, replayFixtureHash})`를 **서비스가 승인 바이트로 계산**, pipeline이 말한 값을 받아 적지 않음)를 원장에 씁니다. 고정 열은 불변입니다(DB trigger). 정확히 같은 본문의 재전송은 고정된 값을 그대로 쓰고(200), 같은 jobId에 다른 digest는 409 `idempotency_conflict`, 승인 항목이나 fixture 파일이 그사이 바뀌었으면 409 `approval_changed`·`fixture_changed`(또는 withheld)로 같은 job id를 새 바이트에 다시 묶지 않습니다. 고쳐 쓰려면 새 jobId를 승인해야 합니다.

**접수와 dispatch.** 인증→헤더→본문(엄격한 3개 필드)→(소유자·본문 digest 조회)→승인 조회→fixture digest 확인→**`reserved` 기록**→(첫 시도면 채택 검사)→`zoop-ai-extract submit`(replay fixture 이름, 등록만: 호출·후보 0)→**pipeline이 보고한 `inputDigest`가 서비스가 계산한 값과 같고 provenance·상태(`queued`·호출 없음)가 승인과 같은지 확인**→**`accepted`+초기 dispatch 1개를 한 transaction으로 기록**→202. `submit`이 결과를 못 주면 같은 gate 안에서 `inspect`로 등록 여부를 확인하고(등록돼 있으면 이어 가고, 없음이 증명되면 예약을 풀고, 판단할 수 없으면 예약을 유지), **어떤 경우에도 `submit`을 다시 보내지 않습니다.** 크래시가 등록 뒤·서비스 확인 전에 났다면 소유자의 같은 재시도가 같은 신원으로 이를 완료합니다. S2와 S3의 모든 child는 **단 하나의 gate** 뒤에서 한 번에 하나만 실행합니다(pipeline 원장 락은 기다리지 않고, S3는 S2가 쓰는 바로 그 원장을 읽는다).

**재실행 정책(자동 재전송 없음).** 최초 dispatch는 pending 행을 **한 번** claim해 `resume`합니다. 이후는 모두 명시적 `recover`입니다. timeout·비정상 종료·읽을 수 없는 출력의 child와 죽은 서비스가 in-flight로 남긴 행은 모호하므로 `idle`(`transport_unknown`, `service_restarted`, `next=recover`)로 끝나고 자동으로 다시 실행하지 않습니다. 유일한 자동 재시도는 pipeline이 락을 여는 단계에서, 즉 어떤 효과도 일어나기 전에 내는 `extraction_busy`·`ingestion_busy` **오류**이며 지수 backoff 최대 8회입니다. **실행 도중** ingestion reader가 바빠서 pipeline이 job을 `stopped`(`ingestion_busy`)로 기록하고 정상 결과를 돌려준 경우는 `exited`일 뿐이고 명시적 recover만 이어 갑니다(pipeline을 바꿔 재시도하게 하지 않았습니다). reserve됐으나 응답이 기록되지 않은 호출은 pipeline이 `reconciling`으로 만들고 다시 보내지 않으며 recover는 409 `reconcile_required`입니다. 저장된 receipt는 recover에서 재사용되고 다시 호출하지 않습니다.

**매 dispatch의 권한.** child를 띄우기 전에(최초 dispatch 포함) 소유자의 승인이 job이 예약된 때의 것과 정확히 같은지, fixture 파일이 고정된 바이트인지를 다시 읽고, 아니면 child 없이 `approval_revoked`·`approval_changed`·`fixture_changed`·`fixture_unavailable`로 `idle` 처리합니다(명시적 recover는 운영자가 복구한 뒤에만 이어 감).

**결과 전달.** 내용은 아래가 **모두** 같은 응답 시점에 성립할 때만 나갑니다. 호출자가 소유자이고, pipeline이 `ready`이며 `delivery.status=current`(source registry·ingestion binding·모든 문서의 권리를 매 호출 다시 읽음)이고, 승인이 아직 예약된 것과 같고, fixture 파일이 고정된 바이트이며 **모든 receipt가 그 바이트로 응답됐고**, 본문이 허용 목록 투영을 엄격히 통과합니다. 아니면 `delivery.state=withheld`와 사유(`job_not_ready`, `source_unauthorized`, `approval_revoked`, `approval_changed`, `fixture_changed`, `fixture_unavailable`, `job_cancelled`, `projection_invalid` …)만 돌려주고 receipt는 단계·상태·verdict 코드만 담습니다. 투영은 사건 후보(`approved:false`, 멘션, 검증된 인용, frozen 스냅샷과의 비교 `original`·`effective`·인용, disposition)와 토픽 후보(멤버·인용)를 보존하되 artifact·raw/locator·segment 표, fixture·요청·응답·그룹·스냅샷 digest, `creatorJobId`, 저장된 binding, 그리고 인용으로 뒷받침되지 않은 생성 텍스트(멘션·비교의 자체 evidence)는 이름을 적지 않아 내보내지 않으며, 필드가 없거나 타입이 다르면 `projection_invalid`로 닫힙니다. 검사는 서로 다른 시점의 별도 읽기이므로 그 사이의 철회와 이미 나간 내용의 회수는 다루지 못합니다. **S2 결과는 S3 권한을 자동으로 넓히지 않습니다**: S3 upstream 허용 목록은 별도의 서버 파일이고 운영자가 명시적으로 적어야 합니다.

**fixture 파일의 TOCTOU.** fixture는 child가 직접 읽는 서버 설정 파일이라 서비스의 digest 확인이 그 읽기와 원자적일 수 없습니다. 이 창은 사후에 닫습니다. pipeline의 `inputDigest`가 서비스가 승인 바이트와 고정 producer digest로 계산한 값과 다르면(등록 중 파일이 바뀜) 500 `runtime_binding_mismatch`로 예약이 `accepted`가 되지 않고(그 job id는 이후에도 새 입력으로 쓰이지 못하고 운영자가 정리해야 합니다), 모든 receipt의 fixture hash가 해당 단계의 고정 digest와 다르면(실행 중 파일이 바뀜) dispatch가 `fixture_changed`로 끝나고 이후 전달은 파일을 원래 바이트로 되돌려도 withheld입니다. 파일이 없거나 읽을 수 없으면 안전하게 `fixture_unavailable`이며, 어떤 경로에서도 네트워크 호출이 없습니다.

**호환·결정.** (1) pipeline은 바꾸지 않았습니다(`ai/pipeline` 소스 변경 없음, 새 의존성·필드 없음; 변경은 시험 세계 도우미가 S2 요청과 topic fixture를 내보내도록 `scripts/relation_smoke.py`에 두 속성을 더한 것뿐). (2) 서비스 원장은 새 파일 `extraction-jobs.sqlite3`라 S1·S3 원장과 스키마를 건드리지 않습니다. (3) 요청 본문의 `schemaVersion`은 S3와 같은 방식으로 런타임 계약 이름(`zoop-extraction-s2-2`)이고 응답은 `zoop-ai-internal-extraction-1`입니다. (4) S3 설정은 그대로이며 S2 그룹이 없을 때 모든 동작이 이전과 같습니다.

**한계.** 목록 라우트가 없고 `run`은 쓰지 않습니다(등록과 실행은 별도 명령·권한). 한 서비스 프로세스가 S2 원장의 유일한 writer라는 것은 배포 규칙이며 코드가 강제하지 않습니다(운영자 CLI가 같은 원장을 쓰면 `extraction_busy`가 나거나 그 사이 취소·채택의 TOCTOU가 남습니다). 승인 파일의 `request`는 서비스가 pipeline의 `Submit` 스키마 전체를 검증하지 않으므로(import 경계) 형식 오류는 첫 `submit`에서 pipeline이 거부하고 서비스는 503 `service_configuration_invalid`로 닫습니다. dispatcher는 직렬이고 `resume`이 300초 deadline 안에 끝나는지는 실측하지 않았습니다. live S2는 pipeline이 거부(`live_mode_unsupported`)하며, live를 열기 전에 pipeline의 under-lock initial-only 표지와 목적·수신자 검사가 필요합니다. Spring 전송 클라이언트(`ExtractionClient`)는 로컬에서 구현했고 S2 결과의 앱 쪽 영속화는 없습니다.

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
| `GET /internal/v1/graph-handoffs/{handoffId}/bundle` | `handoff.read` | 200 `HdBundle`: 위와 같은 형제 필드 + current이고 두 pin이 맞을 때만 `manifest`(freeze 때 원장에 동결된 manifest 본문, 닫힌 모델 `HandoffManifest`)와 `bundle`(`zoop-graph-handoff-bundle-2` 전체. 각 issue의 `mentions[]`는 닫힌 `BMention`/`BParticipant` 모델입니다). 백엔드는 이 한 응답으로 `sha256(canonical(manifest))`=`manifestDigest`와 `sha256(canonical(bundle))`=`bundleDigest`를 모두 재계산합니다. 서비스는 manifest 누락·미지 필드(500 `runtime_contract_mismatch`)와 digest·handoffId·선언·정책 버전·파일 해시·source 핀 불일치(500 `runtime_binding_mismatch`)를 거절하며 status·withheld에는 manifest가 없습니다 |

쿼리 파라미터는 **하나도 허용하지 않습니다**(422). 목록·생성·복구 route는 없습니다.

**설정(10개 모두 있어야 켜지는 그룹, S2/S3·graph와 별개).** `ZOOP_AI_SERVICE_HANDOFF_COMMAND`(설치된 `zoop-ai-handoff` 절대 경로), `ZOOP_AI_HANDOFF_STATE_DIR`(운영자가 `freeze`로 만든 handoff 원장 루트, 읽기 전용으로만 넘김), `ZOOP_AI_HANDOFF_RELATION_STATE_DIR`·`ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR`·`ZOOP_AI_HANDOFF_INGESTION_STATE_DIR`(존재하는 디렉터리), `ZOOP_AI_SERVICE_HANDOFF_SOURCES`, 매니페스트가 sha256으로 고정한 운영자 파일 `ZOOP_AI_SERVICE_HANDOFF_CANONICAL`·`ZOOP_AI_SERVICE_HANDOFF_DECISIONS`·`ZOOP_AI_SERVICE_HANDOFF_BINDINGS`, `ZOOP_AI_SERVICE_HANDOFF_EXPORTS`(아래 allowlist), 그리고 모든 그룹이 쓰는 `ZOOP_STATE_DIR`. 일부만 있거나 값이 잘못되면 필드 이름과 사유 코드만 내고 시작을 거부합니다(`handoff_group_incomplete`·`handoff_roots_overlap`·`handoff_source_inconsistent`). S2/S3 그룹이 같은 프로세스에 있으면 같은 루트·registry여야 하고(다르면 시작 거부) 같은 gate를 공유합니다. child 환경은 소유 환경(`ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR`)만이며 그래프 자격·provider 키·토큰 digest·모델 설정은 들어가지 않습니다.

**handoff allowlist(`ZOOP_AI_SERVICE_HANDOFF_EXPORTS`).** handoff id는 라벨일 뿐이므로 운영자가 principal별로 정확한 `{handoffId, manifestDigest, bundleDigest}`(둘 다 필수 sha256 pin: manifest 해시와 canonical bundle 바이트 해시)를 `{"schemaVersion":"zoop-ai-handoff-exports-1","handoffs":[…]}`로 적습니다. 알 수 없는 키·pin 누락·중복 `(principal, handoffId)`·모르는 principal은 시작을 거부합니다. 목록에 없으면(없는 id·다른 principal의 것 포함) 같은 403 `handoff_not_allowed`를 child 전에 돌려줍니다. 파일은 요청마다 다시 읽고 slot·gate 대기 뒤 child 시작 전, child 응답 직후 답의 어떤 부분이든 쓰기 전, 내용 조립 직전에 다시 읽어 바뀌었으면 403입니다.

**전달 규칙.** 내용은 아래가 **모두** 성립할 때만 나갑니다. (1) 생산자가 `ready`·`delivery.status=current`를 말하고(운영자 파일 3개의 매니페스트 pin, S3 권한·S2 upstream pin·grant, 사용한 검수 revision, 재구성한 content digest를 매 export마다 다시 검증), (2) 받은 bundle의 canonical 바이트 sha256이 생산자 receipt와 **운영자 `bundleDigest` pin** 둘 다와 같고 manifest digest가 `manifestDigest` pin과 같으며, (3) bundle이 모든 중첩 수준에서 **닫힌 모델**(`handoff_wire.Bundle`)을 통과하고 모델이 다시 내보낸 canonical 바이트가 해시한 바이트와 정확히 같을 때. 아니면 **200 + `delivery.state=withheld`**와 사유(`source_unauthorized`·`upstream_changed`·`canonical_mapping_changed`·`decisions_changed`·`bindings_changed`·`review_revision_changed`·`handoff_content_changed`·`handoff_not_ready`·`handoff_pin_mismatch`·`handoff_contract_changed` …)만 있고 `verification`·`bundle`은 null입니다(개수·source id도 없음). 생산자 receipt와 받은 바이트가 서로 어긋나면 500 `runtime_binding_mismatch`, 닫힌 모델이 거부하면(모르는 중첩 필드, 타입·범위 위반 — **digest와 pin을 새 내용에 맞춰 갱신했어도**) 500 `runtime_contract_mismatch`입니다. 둘 다 재시도해도 바뀌지 않으므로 retryable이 아닙니다. 검사들은 서로 다른 시각의 읽기라 그 사이의 철회는 잡지 못하고 이미 나간 내용은 회수되지 않습니다.

**bundle 스키마 `-2`와 이전 handoff.** 서비스의 닫힌 `Bundle` 모델과 receipt 투영(`RtReceipt.bundle_schema`)은 `zoop-graph-handoff-bundle-2`만 받습니다. `zoop-graph-handoff-bundle-1`로 freeze된 handoff는 생산자가 내용 없이 `handoff_contract_changed`로 withheld하며, 서비스는 그 사유 코드만 200 withheld로 그대로 전달하고 옛 receipt·bundle 내용은 어떤 것도 싣지 않습니다(운영자가 새 handoff id를 freeze합니다). `-1` 모양의 current 응답은 닫힌 모델이 아니라 receipt 투영에서 500 `runtime_contract_mismatch`로 거절되며 어떤 별칭·변환도 없습니다. issue의 `mentions[]`는 S2 원본 mention 값(문서·버전·S2 local id로 식별, `verification`은 항상 `none`, 참가자의 `role`은 S2 텍스트 그대로)이며 병합된 issue 필드에서 만들어지지 않습니다. 서비스는 이 값들의 의미(partition·참조 닫힘·시간 정밀도·회사 매핑)를 다시 판단하지 않고 구조만 고정합니다.

**bundle 바이트.** `bundle`은 생산자의 산출물 그대로이며 서비스가 추가·삭제·기본값 보정·정규화하는 것은 없습니다(`exclude_unset`로 입력 키만 되돌리고, 되돌린 canonical 문자열이 받은 것과 다르면 거부). `verification.bundleDigest`는 canonical JSON(키 정렬, `,`·`:` 구분자, 비ASCII 비이스케이프)의 UTF-8 바이트 sha256입니다. 숫자는 음이 아닌 정수뿐이고 키는 ASCII뿐이라 어떤 언어의 JSON 파서 + 같은 직렬화도 같은 digest를 냅니다(`pipeline_tests`와 smoke가 JavaScript로 다시 계산해 확인). 서비스 필드(`appImport`·`delivery`·`verification`·`observedAt`)는 `bundle` 밖의 형제입니다. 제목·URL·label·관측·grant 같은 source 유래 값은 데이터이며 권한의 근거가 아닙니다: 전달 여부는 현재 `delivery.state`와 운영자 pin만이 정합니다. 닫힌 모델은 키 집합·타입·패턴·크기 한도(구조)를 고정하고, 참조 닫힘·id 공식·개수·권한 같은 의미 규칙은 생산자가 쓰기 전과 매 export마다 검증하며 서비스는 반복하지 않습니다.

**한도와 오류.** 생산자의 bundle 상한은 canonical 6 MiB이고 서비스는 child stdout을 16 MiB까지 읽습니다(넘으면 잘라 보내지 않고 503 `runtime_unavailable`). child는 요청당 하나이고 자동 재시도는 없으며 동시 child는 2개(초과 시 503 `service_busy`), deadline 45초입니다. writer가 원장을 잡은 상태(`handoff_busy`·`relation_busy`·`extraction_busy`·`ingestion_busy`)는 503 `runtime_busy`, 손상·변경된 artifact·운영자 파일·소유 설정·복구 필요(`handoff_recovery_required`)는 503 `service_configuration_invalid`, 목록에 있으나 원장에 없는 id는 404 `handoff_not_found`입니다. 모든 503은 `Retry-After`를 갖고 빈 bundle로 답하지 않습니다.

**시험.** `tests/test_handoff_unit.py`(설정 닫힘·allowlist 엄격성·exit·canonical 줄 해석·닫힌 모델을 모든 노드에서 변조·전달 규칙·예시), `tests/test_handoff_http.py`(실제 uvicorn + 시험 소유 stand-in 명령: 고정 argv·최소 환경·pin·중첩 모르는 필드·바이트 동일 중계·JS digest·withheld·busy·deadline·동시성·로그), `pipeline_tests/test_handoff_real_cli.py`(실제 `zoop-ai-handoff`와 S3 job 두 개 세계: CLI export와 바이트 동일, 생산자 검증기 통과, 권한 철회·운영자 파일 변경 withheld→복원)는 기본 `service-test`/`service-pipeline-test`에 들어갑니다. 종단 smoke는 `make service-handoff-smoke`(`scripts/handoff_service_smoke.py`, Neo4j 불필요, pipeline 설치가 없으면 skip이 아니라 **실패**)입니다. 생성된 [내부 OpenAPI](../../docs/api/internal-ai-openapi.yaml)가 계약이며 백엔드 사용 주의는 [인수 문서](../../api/docs/GRAPH_READ_HANDOFF.md)에 있습니다.

## 네트워크와 한계

- 서비스는 `127.0.0.1`에만 묻습니다. 운영에서는 같은 호스트/네임스페이스의 HTTPS reverse proxy가 TLS, 본문 2,000,000B 상한, `Authorization` 비로깅을 맡고 App SG에서만 접근되게 해야 합니다. **이는 가정이며 관측·배포한 사실이 없습니다**(WBS 6.11.2/8의 실관측 과제).
- 동시 CLI 호출은 4개(초과 시 503 `service_busy`), pending dispatch는 1,000개(초과 시 503 `queue_full`)입니다. dispatcher는 직렬입니다(replay ordinal이 ledger 전체 순서이므로). 처리량 향상은 지연 측정 뒤 결정합니다.
- live 모드의 빈 회차 outlook job은 모델 호출이 없어 호출 기록이 없으므로 recipient를 증명할 수 없다. 그래서 `result`는 `recipient_unproven`으로 내용을 내보내지 않는다(실패 시 닫힘, 허용된 현재 동작이며 receipt/상태 조회는 영향이 없다).
- 재시작한 서비스는 이전 child의 pid를 모르므로 종료하지 않습니다. 매달린 child는 job lock을 잡은 채 `busy`로 폴링되며 운영자가 끝내야 합니다.
- 런타임의 `input_or_configuration_invalid`는 클라이언트 입력 오류와 서버 I/O 오류가 섞여 있습니다. 서버 입력(grant registry, worker 명령, worker state 접근)을 제출 전후로 확인해 깨끗할 때만 422이고, 그렇지 않으면 안정적인 503 `service_configuration_invalid`입니다. 런타임에 별도 코드가 생기면 이 보수적 분류를 좁힐 수 있습니다.
- 배포(이미지/호스트/프로세스 관리/프록시), 앱 백엔드 통합, 릴리스 artifact 포함은 **승인되지 않았습니다.** `scripts/package_artifacts.py`는 이 프로젝트를 포함하지 않습니다.

## 검증

`tests/`는 실제 uvicorn 프로세스(127.0.0.1)와 실제 설치된 `zoop-ai`를 쓰고 CLI를 흉내 내지 않습니다. 자격 증명은 시험마다 메모리에서 만든 합성 값이며 저장소에는 토큰도 digest도 없습니다. 모델은 호출하지 않습니다. 오직 live 경로 시험이 `127.0.0.1`의 loopback provider(표준 라이브러리 HTTP 서버, 요청 수만 센다)를 쓰고 외부 네트워크는 쓰지 않습니다. 프로세스 충돌 시험은 `tests/launcher.py`가 실제 컴포넌트를 감싸 정해진 경계에서 서비스를 SIGKILL하며 프로덕션 코드에는 그런 hook이 없습니다.

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
| `tests/test_relation_review_unit.py`(기본 `service-test`, pipeline 불필요) | 검수 결정 트리 전체: 모의 child로 거절·busy·timeout·비정상 종료·withheld 각각이 예약을 푸는지 유지하는지, 이전 시도가 있으면 쓰기 전에 체인을 읽는지, 이벤트 필드 하나라도 다르면 채택하지 않는지, 재생·충돌·다른 principal·allowlist·상한, recover가 체인을 먼저 읽고 확정·재큐·거절하는 경우 |
| `pipeline_tests/test_relation_review.py` | allow→재검증→verdict→새 source revision(검증 호출 1회, 재생성 없음, 게시 없음), reject, stale version·revision은 어디에도 기록하지 않음, 본문 엄격성·reviewer 위조 불가, 같은 key 동시 6회=1 operation, principal·scope 격리, 점유된 pipeline에서도 operation 조회, allowlist·source grant 철회, 대기 중 allowlist 철회 뒤 명시적 recover, 대기 중인 allow가 뒤의 reject를 덮지 못함, 취소된 job 거부, hold로 끝난 재검증과 두 번째 attempt |
| `pipeline_tests/test_relation_review_recovery.py` | review 반영 직후·record 직전 크래시(예약 직후/append 후/기록 후)에도 이벤트 1개와 재검증 1회, 운영자가 먼저 쓴 이벤트는 채택하지 않음, **실제 orphan**: 서비스를 SIGKILL해 락을 잡기 전에 멈춘 review child를 살려 두고 재시도의 읽기 뒤에 그 child가 정확한 이벤트를 append하게 하면(시험 소유 stand-in 명령만 사용, 서비스·pipeline에 hook 없음) 재시도의 child는 `review_revision_conflict`를 받아도 operation이 채택돼 202이고 재검증이 큐에 남으며 이벤트는 1개, 같은 순간 운영자의 이벤트가 들어오면 예약이 실제로 풀려(원장 0행, 조회 404) 키를 현재 revision(2)의 reject로 다시 쓸 수 있음, verifier receipt 저장 뒤 죽은 child는 fixture 없이 receipt로 마무리하고 추가 호출 0, 응답 없는 호출은 재전송 없이 `reconcile_required`, 재검증 child가 verdict를 쓰고 기록 전에 죽으면 recover가 체인으로 확정 |

관측(10/13, 로컬 작업 트리, Main 실행, 최종 실행): 검수·재검증 slice와 독립 검토가 찾은 두 지적(R1: 재시도의 거절 뒤 체인 재조회, R2: probe의 job·`inputDigest`·upstream 결속)을 반영한 뒤 `make service-test` **403 tests**, `make service-pipeline-test` **59 tests**(설치된 pipeline 통합), 실제 `make service-pipeline-smoke`가 통과했다. smoke는 검수 allow→재검증으로 `sourceRevision` 1→2→3(verifier 호출 1회, 게시 없음), 서비스를 SIGKILL한 뒤 락을 잡기 전에 살아남은 실제 orphan review child가 재시도의 읽기 뒤에 append한 정확한 이벤트의 marker 채택(이벤트 1개, 재검증 1회), 운영자 이벤트(foreign) 대조에서의 예약 해제와 revision 2에서의 키 재사용, verifier receipt 저장 뒤 크래시의 추가 호출 0을 확인했다. OpenAPI 재생성 뒤 drift는 0이었고 `make public-check`는 생성물 275개 차이 없음·하드 오류 0·문서 시스템 테스트 21개 통과였다. 이전 관측(Gateway 수정 뒤 `service-test` 291 tests, `service-pipeline-test` 24 passed)은 이 slice 이전이다.

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
