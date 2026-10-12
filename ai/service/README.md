# ai/service — S1 내부 HTTP transport

앱 백엔드가 S1 분석(`document-summary`, `document-sentiment`, `semantic-verification`, `briefing-outlook`, 계약 `zoop-ai-s1-1`)을 제출·조회·취소·복구하는 **내부 전용 HTTP 서비스**입니다. FastAPI/uvicorn이며 **설치된 `zoop-ai` CLI만** 호출합니다. `zoop_ai`·`zoop_ai_pipeline`·BFF를 import하지 않고 worker의 `worker.sqlite3`를 열지 않습니다. 런타임 원장이 작업 상태의 유일한 출처이고 이 서비스는 소유자·멱등·dispatch 상태만 별도 `service.sqlite3`에 둡니다.

> **로컬 준비 상태입니다.** 배포·원격 CI 활성화·보안 그룹·TLS 프록시는 확인되지 않았고 승인되지 않았습니다. 실제 모델 호출, 외부 뉴스, 실제 토큰은 쓰지 않았습니다. S2-2/S3(`zoop-ai-extract`, `zoop-ai-relation`)는 등록 전용 `submit` 명령이 없어 이 서비스에 포함하지 않습니다. S2-1 수집은 운영자 파일 입력이므로 HTTP로 열지 않습니다.

```bash
make service-install           # uv sync --project ai/service --frozen --group dev (공개 의존성만, 토큰 없음)
make service-test              # 실제 uvicorn + 설치된 zoop-ai + authored replay
make service-smoke             # 실제 프로세스 smoke (replay 4종 + recover + loopback cancel/restart)
make service-openapi-check     # docs/api/internal-ai-openapi.{json,yaml} 생성 drift
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
| live 통과 | `ZOOP_AI_LIVE_ENABLED=1`과 양수 `ZOOP_AI_GLOBAL_MAX_CALLS`가 **모두 있을 때만** live가 열리고, 그렇지 않으면 `ZOOP_AI_LIVE_ENABLED/GLOBAL_MAX_CALLS/PROVIDER/BASE_URL/API_KEY`는 child에 전달되지 않는다. stage별 `ZOOP_AI_{DOCUMENT_SUMMARY,DOCUMENT_SENTIMENT,VERIFY,BRIEFING_OUTLOOK}_{MODEL,REASONING_EFFORT}`는 입력 digest에 영향을 주므로 항상 통과한다. |

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
