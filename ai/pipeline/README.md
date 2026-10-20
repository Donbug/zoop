# ai/pipeline — 일회성 문서 수집·S2-1 원문 준비(공개 의존성만)와 S2-2 / S3 오프라인 프로세스, S4 읽기 전용 의존 대상 조회

| 명령 | 모듈 | wire schema | 상태 파일 |
| --- | --- | --- | --- |
| `zoop-ai-collect run` | `zoop_ai_pipeline.collection_cli` | `zoop-collection-1` (policy `zoop-collection-policy-1`) | 상태 DB 없음. source `inputRoot/collections/<collectionId>/`에만 원본 bytes·receipt·manifest를 쓴다 |
| `zoop-ai-ingest {run,resume,inspect,export}` | `zoop_ai_pipeline.ingestion_cli` | `zoop-ingestion-s2-1` | `ingestion.sqlite3` |
| `zoop-ai-extract {run,submit,resume,inspect,cancel}` | `zoop_ai_pipeline.extraction_cli` | `zoop-extraction-s2-2` | `extraction.sqlite3` |
| `zoop-ai-relation {run,submit,inspect,resume,review,revalidate,cancel}` | `zoop_ai_pipeline.relation_cli` | `zoop-relation-s3` | `relation.sqlite3` |
| `zoop-ai-dependents` (하위 명령 없음, stdin 변경 1건) | `zoop_ai_pipeline.dependency_cli` | `zoop-dependency-s4` | 위 세 원장을 읽기 전용으로만 연다(쓰는 상태 파일 없음) |
| `zoop-ai-graph {init,freeze,project,recover,inspect,read,focus}` | `zoop_ai_pipeline.graph_projection_cli` | `zoop-graph-projection-1` | `graph.sqlite3` + 이 원장 하나에 묶인 별도 Neo4j 5 database의 **비공개** version(공개 아님) |
| `zoop-ai-handoff {freeze,recover,inspect,export}` | `zoop_ai_pipeline.handoff_cli` | `zoop-ai-handoff-1` (bundle `zoop-graph-handoff-bundle-2`) | `handoff.sqlite3` + `bundles/<sha256>.json`; 위 세 원장을 읽기 전용으로만 열고 Neo4j는 쓰지 않음 |

세 원장(ingestion/extraction/relation)은 서로의 디렉터리를 `--ingestion-state-dir`/`--extraction-state-dir` 경로로 읽기 전용으로 엽니다(그래서 한 프로젝트입니다). 이 세 프로세스는 authored replay 전용이며 live/네트워크 경로가 없습니다. 공개 route, 앱 문서 등록·게시, S1 DB 쓰기는 하지 않습니다. `zoop-ai-dependents`는 세 원장을 읽기만 하는 S4의 일부(영향 대상 조회)이며 철회·재생성은 하지 않습니다. `zoop-ai-graph`는 이들 위에서 **완료된 S3 job 하나**를 읽기 전용으로만 소비해 `graph.sqlite3`와 원장에 묶인 Neo4j 한 곳에만 쓰며(아래 절), 그 밖의 네트워크·모델·provider 호출은 없습니다. `zoop-ai-ingest export`는 기본으로 `read`·`quote-display`만 요구하며, 앱 문서 import처럼 내보낸 텍스트를 **저장**하는 소비자는 `--require-store`(export 전용)로 현재 grant의 `store`까지 요구합니다. 이 확인도 호출마다 현재 registry로 CLI 안에서 하며 소비자가 registry를 읽지 않습니다.

`zoop-ai-handoff`는 여러 S3 job과 S2 upstream을 운영자 manifest로 고정해 **공개 이슈 중심 handoff bundle**을 만듭니다. 앱 버전·활성화·공개 준비 완료가 아니며, export 직전에 모든 원천과 운영자 파일의 현재 권한·고정 hash를 다시 검사합니다. member 식별은 문서 ID·버전·정확한 관측까지 포함하고, 구조 basis의 유효기간 근거와 동일 문서의 모든 관측도 보존·대조합니다. 원장 소유권은 변경 전에 읽기 전용으로 검사합니다. 현재 CLI와 `ai/service`의 인증된 전체 bundle HTTP는 **frozen manifest 본문과 bundle을 함께** 반환하여 두 digest를 독립 검증할 수 있습니다. 계약·소유·앱 import·공개 수용의 잔여 조건은 [그래프 인수 문서](../../api/docs/GRAPH_READ_HANDOFF.md)를 따릅니다.

**원본 mention(bundle `-2`).** 각 이슈의 `mentions[]`는 그 이슈의 source event가 가리키는 S2 mention을 있는 그대로 담습니다. 신원은 (문서 ID, 문서 버전, 로컬 mention ID)이며(로컬 ID는 문서 버전 안에서만 유일), 앱 article·version은 운영자 binding에서 옵니다. 한 mention을 두 upstream(event candidate와 snapshot member)이 싣더라도 기록은 하나입니다. `title`·`action`·`target`·`eventTime`·`period`·`assertionStatus`·`background`와 참여자의 `sourceCompanyId`·`name`·`role`은 S2 후보/snapshot 값 그대로(순서 포함)이고 `verification`은 항상 `"none"`입니다. `timePrecision`은 형식으로만 계산하며 넓히지 않습니다. 참여자의 `companyId`는 이 mention을 싣는 **모든** upstream이 같은 공개 회사로 매핑하고 그 회사를 bundle이 `companies`로 게시할 때만 채우며, 아니면 null입니다(참여자 자체는 항상 보존; 역할은 확인된 역할도 `INVOLVES`도 아닙니다). mention의 `evidenceIds`는 그 mention 자신의 정확한 인용 근거이고 이슈의 `evidenceIds`는 mention 근거와 geography 근거의 합집합입니다. 같은 신원을 싣는 member들이 값을 다르게 말하면 `mention_values_conflict`, mention 시각을 추측 없이 분류할 수 없으면 `mention_event_time_unsupported`로 **이슈 전체**를 보이게 제외합니다(병합·마지막 값 우선 없음; `-1`이면 공개됐을 수 있는 이슈입니다). field decision·support·approval·publisher·impact 값은 만들지 않으며, source event·counts·digest 공식·`policy`는 `-1`과 같아 운영자 attestation digest가 그대로 유효합니다.

**이전 bundle의 이력.** 저장된 receipt의 `bundleSchema`가 현재 스키마가 아닌 행(`-1`)은 이력입니다. 운영자 파일·원천 원장·grant·artifact·쓰기 가능한 ledger에 손대기 **전에** 원장만 읽어 판별하고(각 `Handoff` 메서드가 잠금 아래에서 다시 확인), `inspect`는 저장된 상태·receipt·attempt와 `next: null`·`delivery: withheld/handoff_contract_changed`(artifact는 읽지 않음), `export`는 내용 없는 withheld, `recover`와 같은 ID의 `freeze`는 `handoff_contract_changed` 오류입니다. 행·attempt·artifact의 바이트와 권한은 바뀌지 않고 `recover`가 이 행을 `failed`로 만들지도 않으므로, 다시 만들려면 새 `handoffId`로 freeze합니다. 새 ID는 같은 원장에서 정상 동작합니다. 이전 빌드를 이 원장에 실행하지 마십시오(옛 `recover`가 `-2` 행을 invalid로 판정합니다). 손으로 쓴 기대값과 설치된 CLI 확인은 `ai/pipeline/scripts/graph_handoff_smoke.py`가 맡으며, `--write-fixture`는 mention 기대값(`expected-mentions.json`)과 이전 schema의 withheld 봉투(`export-withheld-legacy.json`)도 새 디렉터리에 씁니다.

판별은 세 갈래입니다. **증명된 없음/현재**(디렉터리·원장 파일이 없거나 행이 없거나 현재 스키마)일 때만 기존 쓰기 경로로 넘어가고, **이력**이면 읽기 전용 보기를 쓰며, **판단 불가**(writer 사용 중 `handoff_busy`, 낯선·손상된 namespace/원장, receipt에 schema 없음 `handoff_state_invalid`, 과대 파일)는 그 오류를 그대로 내고 쓰기 가능한 open으로 넘어가지 않습니다(쓰기 open은 권한 재설정·WAL checkpoint·DDL을 하므로 이력 원장을 바꿀 수 있습니다). writer가 죽어 비어 있지 않은 WAL에만 커밋된 행은 읽기 전용 immutable open에 보이지 않으므로, 소유를 먼저 증명한 뒤 shared lock 아래에서 원장 파일과 WAL을 128 MiB 한도로 임시 0700 디렉터리에 **복사**해 그 복사본만 SQLite로 엽니다(원본 파일·`-shm`·WAL·권한·mtime 불변, 임시 디렉터리는 닫을 때 삭제). 현재 스키마 행의 hot WAL 복구(`recover`)는 그대로 쓰기 경로이고 읽기 명령은 `handoff_recovery_required`를 냅니다.

복사 한도는 파일마다 **128 MiB**이며 원본이 일반 파일이 아니거나(심볼릭 링크 포함) 한도를 넘으면 잘라 읽지 않고 `handoff_state_invalid` 오류로 닫힙니다. 임시 디렉터리는 `mkdtemp`로 만든 0700 비공개 위치이고, 정상·오류 어느 경로에서도 보기를 닫을 때 삭제하며 원장 디렉터리 안에는 아무것도 만들지 않습니다.

**의존성.** 전체 패키지(`zoop-ai-pipeline`)는 공개 패키지(pydantic 2.13.5·httpx 0.28.1·lxml 6.1.3·pypdf 6.19.0·neo4j 6.3.1)만 쓰며 collect·ingest·extract·relation·dependents·graph·handoff 일곱 명령 모두 **private PoC·git 인증·토큰 없이** 설치·실행됩니다. 원본 PoC(`investmate`)는 이 프로젝트의 어떤 소스·스크립트·시험에서도 import하지 않고 manifest·lock에도 없습니다(옛 `poc` extra, `poc_guard`, `pinned_poc_unavailable` 코드 제거). `prototype/bff`만 별도로 private PoC를 고정해 쓰며, CI에서 그 token을 쓰는 job은 `bff` 하나뿐입니다.

```bash
make pipeline-install   # uv sync --project ai/pipeline --frozen --group dev  (공개 의존성만, 토큰 불필요)
make pipeline-test      # ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests
make pipeline-smoke     # ingestion/collection/extraction/relation/dependents/handoff 실제 CLI 프로세스 smoke, 모델·외부 네트워크 호출 0
make pipeline-build
```

### 2026-10-16 전체 네이티브 이행 검증

정확한 lock 동기화로 pipeline 환경에서 `investmate-poc`와 관련 패키지 23개를 제거한 뒤 전체 **627개 테스트**와 수집·원문 준비·추출·관계·의존 조회·handoff의 실제 CLI smoke가 통과했습니다. 서비스 **886개**, 실제 pipeline 통합 **115개**, S2→S3 HTTP·검수/복구·전체 bundle HTTP smoke도 통과했습니다. 별도 Neo4j 5.26 시험에서는 native S2/S3로 만든 버전의 실제 적재·조회·중단 복구·변조 거절을 확인했습니다. 시험 컨테이너는 정리했습니다.

고정 PoC의 순수 합성 입력에서 **이행 전에 한 번 캡처한** golden 값으로 Article.version·Mention 기본값·요청 preimage를 대조합니다. 네이티브 adapter identity는 별도 값이며 PoC fingerprint를 수행했다고 주장하지 않습니다. legacy 작업은 원천 registry와 fixture를 읽기 전에 원장만 읽어 판별합니다. 이력 조회·거절된 run/submit/resume는 bytes·스키마·권한·updated_at을 바꾸지 않고, 명시적 cancel만 허용된 상태를 변경합니다. 두 이행 결함은 **45개 실패 사례와 통과한 대조군**을 확인한 뒤 수정했고 최종 627개에 포함해 통과했습니다.

위 결과는 로컬·합성 검증이며 실제 S2/S3 모델 품질, 외부 사이트 수집, 공개 활성화나 원격 CI 통과를 뜻하지 않습니다. `prototype/bff`의 별도 PoC 의존성은 이번 범위 밖입니다.

`ai/worker`는 dev 그룹에서만 설치됩니다(S1 `exact()` 인용 동등성 시험). 런타임은 `zoop_ai`를 import하지 않습니다. 상태 루트가 `prototype/bff/var`, `ai/worker/var`, `api/var`, 이전 `prototype/ai-worker/var`, `ZOOP_STATE_DIR`/`ZOOP_AI_WORKER_STATE_DIR`와 겹치면 `state_namespace_conflict`로 거부합니다.

**설치된 패키지(wheel)의 소유권 설정:** 저장소 checkout 안에서 실행할 때만 위 저장소 경로를 파일 위치에서 알 수 있습니다. 설치본은 저장소를 추측하지 않으므로 **`ZOOP_STATE_DIR`(앱 상태 루트)과 `ZOOP_AI_WORKER_STATE_DIR`(S1 worker 상태 루트)를 둘 다 절대 경로로** 지정해야 하며, 없거나 상대 경로이면 `state_ownership_unconfigured`로 닫힙니다. 지정한 두 루트와 겹치는 `--state-dir`은 `state_namespace_conflict`입니다. smoke(`ai/pipeline/scripts/*_smoke.py`)는 값이 없으면 임시 디렉터리를 대신 지정하며 PYTHONPATH 없이 설치된 패키지로 자식 프로세스를 실행합니다.

**10/13 추가 검증 — 등록과 실행 분리:** S2/S3의 `submit`을 추가한 로컬 작업 트리에서 pipeline 전체 **228개 시험**과 `make pipeline-smoke`의 ingestion·extraction·relation·dependents 실제 CLI 검사가 모두 통과했다. 접수 시 호출 0건, 같은 요청의 재접수, 충돌 거부, 실행 전 권한 변경, 실행 전 취소, 이후 명시적 실행을 확인했다. 외부 모델·네트워크 호출은 없었다. 아래 절의 이전 시험 수치는 각 기능 도입 당시 기록이며, 이번 변경은 아직 원격 CI에서 검증하지 않았다.

# 상세 계약과 실행 증거

아래 절은 BFF README에서 옮겼으며, 시험 수치와 pass/fail 기록은 이동 전(BFF 환경) 당시 값입니다. 이동 후 `ai/pipeline` 독립 환경의 전체 시험은 142 passed이고 세 smoke가 설치 환경과 패키지 전용 격리 환경에서 모두 `status=passed`였습니다.

## 일회성 HTTP 문서 수집 (`zoop-ai-collect`, 네이티브)

**하는 일.** 운영자가 요청에 **명시한 문서 URL 목록**(최대 50개)만 HTTP GET으로 받아 hash로 묶인 원본 bytes와 receipt, 그리고 `zoop-ai-ingest run --fixture-manifest`가 그대로 소비하는 manifest로 남깁니다. **하지 않는 일:** 자동 크롤링·링크 따라가기·검색/AI 검색·RSS/DART 등 API 조회와 키·쿠키·로그인 인증·스케줄러·자동 재시도·모델 호출(ingestion은 결정적 검사만 하며 의미 판정은 다음 단계 S1 native Jev의 몫입니다). `.env`와 OpenAI/TypeSafe/DART 키는 읽지 않습니다.

```bash
zoop-ai-collect run --sources registry.json --policy policy.json < request.json    # 종료 0은 모든 URL 수집 완료일 때만, 부분·실패·거부는 2
zoop-ai-ingest run --state-dir STATE --sources registry.json --fixture-manifest <출력의 manifestPath> < ingest-run.json  # fixtureManifestHash = 출력의 manifest.sha256
```

- **권한은 registry가 가진다.** source는 `adapter: "collected-http"`, `rights: "known"`+증거, `allowedOperations`에 `read`·`store`, 정확한 `allowedHosts`가 필요합니다. URL이 공개돼 있거나 robots.txt가 허용한다는 사실은 license가 아닙니다. registry는 시작 시, 각 실제 GET 직전(robots.txt·리다이렉트 포함), 응답 수신 뒤 원문/receipt 저장 전, 최종 확정 직전과 저장된 결과의 재전달 직전에 다시 읽습니다. 최종 rename 뒤 반환 전에도 재확인하고, 그 사이 권한이 바뀌면 소유한 디렉터리임을 확인해 비공개 임시 위치로 되돌려 제거합니다. grant의 철회·변경은 URL별 실패로 낮추지 않고 수집 전체를 중단합니다. 저장된 수집도 현재 권한이 없으면 본문 없이 `source_unauthorized` 또는 `registry_changed`만 반환합니다. 마지막 확인과 실제 반환 사이의 권한 변경을 원자적으로 막는 계약은 아닙니다.
- **policy 파일**(읽기 전용, 모든 값 필수, 기본값 없음): `userAgent`(운영자가 정한 식별 문자열, 브라우저 흉내 금지), `timeoutSeconds`·`maxTotalSeconds`·`maxRedirects`·`maxRequests`(robots 포함)·`maxResponseBytes`·`maxTotalBytes`·`minIntervalSeconds`·`allowedMediaTypes`(`text/html`,`application/pdf`) 그리고 시험 전용 `syntheticLoopback`(기본 false).
- **요청**: `{"schemaVersion":"zoop-collection-1","collectionId","sourceId","scopeId","targets":[{"candidateId","url","title","documentKind":"news"|"disclosure","supplierDocumentId"?,"publishedAt"?,"modifiedAt"?,"sourceRevision"?}]}`. 설명 메타데이터(제목·시각·종류)는 **요청에 선언된 값만** 쓰며 페이지에서 긁어 오지 않습니다. `publishedAt`은 날짜(`YYYY-MM-DD`)면 `day` 정밀도로 남고 자정으로 바뀌지 않으며, 오프셋이 있는 시각만 `instant`, 오프셋 없는 시각은 `unresolved`(시간대를 가정하지 않음), 없으면 `unknown`입니다. 원문 표기·정밀도·근거는 `collection.published`에, `Item.publishedAt`에는 `instant`만 들어갑니다.
- **네트워크 방어(요청·robots·리다이렉트 hop마다 반복)**: URL 정규화(자격 증명·제어문자·모호한 인코딩·기본이 아닌 포트 거부), 정확한 호스트 목록, HTTPS만(루프백 http는 `syntheticLoopback`이 켜졌고 호스트가 `localhost`/`127.0.0.1`일 때만), robots.txt 선확인(최장 일치 RFC 9309, 404만 허용·그 외 오류는 거부), DNS 결과의 모든 주소가 전역 라우팅 가능해야 하며(IPv4-mapped/NAT64 포함) **검증한 그 주소로 직접 연결하면서** Host 헤더와 TLS SNI·인증서 이름은 요청 호스트를 유지합니다(DNS rebinding 방지, 요청마다 새 해석·새 연결). 프록시 환경변수는 무시(`trust_env=False`), TLS 검증은 끄지 않고, 쿠키·인증·Referer는 보내지 않으며, 압축 응답 거부, 401/403/429는 그 호스트를 실행 동안 차단, 자동 재시도 없음, 요청 수·바이트·시간·콘텐츠 타입 제한. 시스템 DNS 조회는 제한 시간에 중단·회수되는 별도 자식 프로세스에서 실행하고 비동기 HTTP 연결·TLS·헤더·본문 전체는 절대 deadline에서 취소합니다(조금씩 전송되는 헤더/본문도 제한). 동기 CLI/API이므로 같은 스레드에 이미 실행 중인 asyncio event loop가 있는 호출은 지원하지 않으며 `collector_async_context_unsupported`로 거부합니다. 오류는 URL·헤더 없는 안정적인 코드뿐입니다.
- **산출물과 출처 구분**: `<source.inputRoot>/collections/<collectionId>/`에 `bodies/<sha256>.bin`(내용 주소), `receipts/<sha256>.json`(최종 URL·리다이렉트·HTTP 상태·콘텐츠 타입·ETag/Last-Modified/Date·robots 상태·본문 sha256·실제 수집 시각(UTC)·grant id/revision·`network`), `page-0.json`, `manifest.json`, `collection.json`. 모든 item은 `collection.provenance = "collected_http"`(획득 경로를 뜻함)이며 `collection.network`는 `external` 또는 `synthetic_loopback`(정책의 `syntheticLoopback`으로 로컬 시험 서버에서 받은 바이트, 외부 문서가 아님)입니다. receipt는 manifest/item이 hash로 고정합니다. `adapter: "collected-http"` source는 이 기록이 없는 item을 거부(`discovery_item_invalid`)하고, `authored-files` source는 이 기록이 있는 item을 거부해 **authored fixture를 actual로 바꿔 부를 수 없습니다.** ingestion은 receipt가 이 source·scope·candidate·현재 grant revision·실제 bytes와 일치하는지 검사합니다(`collection_receipt_invalid`). receipt는 서명되지 않은 운영자 로컬 파일이므로 입력 디렉터리를 쥔 사람은 위조할 수 있습니다. 이는 일관성 증거이지 네트워크 증명이 아닙니다.
- **불변·멱등**: `collectionId`는 불변입니다. 같은 id와 같은 입력(요청·source 설정·grant·policy)은 저장된 결과를 다시 보여 줄 뿐 재요청하지 않고(`replayed: true`), 다른 입력이면 `collection_input_conflict`입니다. 부분/실패 수집도 그대로 재현되며 숨은 재시도는 없습니다(다시 하려면 새 id).
- **부분·빈 결과·오류 구분**: 모든 URL 성공 `complete`, 일부 성공 `partial`(manifest page `partial`), 전부 실패 `failed`(manifest page `failed`, 빈 items). 요청 자체의 거부(`target_invalid`, 인증·어댑터·네임스페이스 오류)는 `error`이며 어느 쪽도 "성공한 0건"이 아닙니다. ingestion은 partial/failed page를 `incomplete`로 둡니다.
- **디렉터리 안전**: `inputRoot`와 `collections/`는 심볼릭 링크를 따르지 않고(디렉터리 fd, `O_NOFOLLOW`) 열며, `.lock`으로 배타 잠금하고, 낯선 파일(예: 외부 SQLite)이나 같은 id의 낯선 디렉터리는 채택하지 않고(`collection_namespace_conflict`) 앱/S1/PoC 상태 루트와 겹치면 거부합니다. 기존 `collection.json`도 descriptor-relative `O_NONBLOCK|O_NOFOLLOW`로 열고 regular file/크기 한도를 확인한 뒤 제한된 길이만 읽습니다(FIFO 등은 즉시 거부·미수정). 자신이 만든 `.tmp-<id>-…`에만 쓰고 한 번의 rename으로 공개하며, 실패 시 자신이 만든 이름만 지웁니다(이전 프로세스가 남긴 임시 디렉터리는 채택도 삭제도 하지 않음).
- **지원/미지원**: 지원은 명시된 `text/html`·`application/pdf` URL의 단발 수집뿐입니다(`text/plain` 등은 없음). 검색·RSS·DART/OpenDART 같은 API·인증·스케줄링·주기 갱신·시간 창 coverage 주장은 구현하지 않았으며 수집은 `coverageThrough`를 비웁니다. 실제 사이트에 대한 수집은 이 변경에서 실행하지 않았습니다.
- **HTTPS 인증서 검증**은 끌 수 없고, 연결 IP가 아니라 원래 요청 호스트를 Host·SNI·인증서 이름으로 사용합니다. 공개 회귀 시험의 HTTP 루프백만으로 TLS의 신뢰 체인과 이름 검증까지 증명할 수 없으므로, TLS 변경 시 별도 신뢰된 로컬 테스트 CA/잘못된 이름/신뢰되지 않은 CA 검증이 필요합니다.

### 수령자용 최단 레시피: 명시한 URL → 준비된 문서 export (모델·PoC·DB 서버·클라우드 없음)

필요한 것은 `make pipeline-install`로 만든 `ai/pipeline/.venv`뿐이다. Neo4j·PostgreSQL·OpenAI/TypeSafe 키·네트워크 계정은 필요 없다(네트워크는 `zoop-ai-collect`가 **요청에 적은 URL**에만 연다). 저장소 checkout 안의 `.venv`를 쓰면 앱/S1 상태 루트가 자동 파악된다. checkout 밖에 설치한 패키지는 `ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR`(절대 경로)를 지정해야 하고 없으면 거부한다. 두 모드는 **같은 명령, 다른 입력**이다. 합성 시연이 외부 문서가 아님은 export의 `observation.collection.network`가 `synthetic_loopback`인지로 구분하며, 실제 모드의 값은 `external`이다.

**A. 합성 시연(외부 접속 없음, 바로 실행).** 임시 `127.0.0.1` 서버가 합성 HTML 1건·PDF 1건을 내주고 실제 CLI 세 개(collect → ingest run → ingest export)를 subprocess로 돌린 뒤 파일을 **남긴다**(기본 smoke는 모두 지운다). 출력 디렉터리는 없거나 비어 있어야 한다.

```sh
ai/pipeline/.venv/bin/python ai/pipeline/scripts/collection_smoke.py --output-dir /tmp/zoop-collection-demo
# 남는 파일: sources.json, policy.json, collect-request.json, ingest-run-request.json (이 시연의 전체 유효 설정/요청),
#            inputs/collections/demo-collect-1/ (원본 bytes·receipt·manifest), state/ingestion.sqlite3, exports/n1.json, exports/d1.json
```

서버는 종료됐으므로 남은 URL·포트는 재실행용이 아니라 형식 참고용이다. 이 파일들은 합성 문서이며 근거 자료나 실제 수집물이 아니다. 아래 B의 JSON은 같은 스키마의 실제 모드 버전이다.

**B. 실제 모드: 사용자가 권리를 확인한 URL만.** 아래 `news.example.com`, `evidence`, `userAgent`, `targets`는 반드시 자기 값으로 바꾼다. `evidence`에는 이 URL들의 수집·저장·인용 표시를 허락한다는 **실제 근거**(계약·약관·서면 허락)를 적는다. 공개 URL이라는 사실이나 robots 허용은 근거가 아니다. 근거 없이 임의의 사이트를 넣지 않는다. 한 번에 최대 50건이며 모든 값이 필수라 기본값이 없다.

```sh
BIN="$PWD/ai/pipeline/.venv/bin"
WORK="$HOME/zoop-collection-work"      # 새 디렉터리. 저장소 안이나 앱/S1/worker 상태 디렉터리 안에 두지 않는다
mkdir -p "$WORK/inputs"

cat > "$WORK/sources.json" <<EOF
{"schemaVersion":"zoop-ingestion-s2-1","revision":"operator-1","sources":[{
  "sourceId":"my-source","adapter":"collected-http","inputRoot":"$WORK/inputs","allowedHosts":["news.example.com"],
  "scopes":[{"scopeId":"body","selection":"operator-listed URLs, one-off","initialCursor":null,"articleXPath":null,
             "timestampLimitations":["one-off explicit URL list; no discovery or time-window coverage"]}],
  "grant":{"grantId":"my-grant","revision":"rights-1","sourceId":"my-source","enabled":true,"rights":"known",
           "allowedOperations":["read","store","quote-display"],"recipients":[],"purposes":[],
           "evidence":["<수집·저장·인용 표시를 허락한 계약/약관/서면 근거를 여기에 적는다>"],"expiresAt":null}}]}
EOF

cat > "$WORK/policy.json" <<'EOF'
{"schemaVersion":"zoop-collection-policy-1","userAgent":"ZoopCollector/1.0 (+mailto:operator@example.com)","timeoutSeconds":20,
 "maxTotalSeconds":300,"maxRedirects":3,"maxRequests":20,"maxResponseBytes":5000000,"maxTotalBytes":50000000,"minIntervalSeconds":1,
 "allowedMediaTypes":["text/html","application/pdf"],"syntheticLoopback":false}
EOF

cat > "$WORK/collect-request.json" <<'EOF'
{"schemaVersion":"zoop-collection-1","collectionId":"my-collect-1","sourceId":"my-source","scopeId":"body","targets":[
  {"candidateId":"n1","url":"https://news.example.com/articles/1","title":"기사 제목(운영자가 선언)","documentKind":"news",
   "publishedAt":"2026-10-14","supplierDocumentId":null,"modifiedAt":null,"sourceRevision":null},
  {"candidateId":"d1","url":"https://news.example.com/filings/2.pdf","title":"공시 제목","documentKind":"disclosure",
   "publishedAt":"2026-10-14T09:00:00+09:00","supplierDocumentId":"filing-2","modifiedAt":null,"sourceRevision":null}]}
EOF

# 1) 수집. 종료 0은 모든 URL 수집 완료일 때만이다. 2면 collect-result.json의 targets[].code와 error.code를 읽는다.
"$BIN/zoop-ai-collect" run --sources "$WORK/sources.json" --policy "$WORK/policy.json" < "$WORK/collect-request.json" > "$WORK/collect-result.json"

# 2) 수집 manifest를 ingestion 요청으로 연결한다(fixtureManifestHash = collect-result.json의 manifest.sha256).
"$BIN/python" - "$WORK" <<'PY'
import json, sys
work = sys.argv[1]
result = json.load(open(f"{work}/collect-result.json"))
json.dump({"schemaVersion": "zoop-ingestion-s2-1", "roundId": "my-round-1", "sourceId": result["sourceId"], "scopeId": result["scopeId"], "window": None,
           "checkpointRevision": 0, "fixtureManifestHash": result["manifest"]["sha256"], "cleanerVersion": "exact-copy-1"}, open(f"{work}/ingest-run.json", "w"))
open(f"{work}/manifest-path.txt", "w").write(result["manifestPath"])
PY
"$BIN/zoop-ai-ingest" run --state-dir "$WORK/state" --sources "$WORK/sources.json" --fixture-manifest "$(cat "$WORK/manifest-path.txt")" < "$WORK/ingest-run.json" > "$WORK/ingest-result.json"

# 3) 준비된 문서 하나당 export 하나. state는 읽기 전용으로 열리며 --require-store는 export 순간 grant에 `store`까지 있어야 통과시킨다.
mkdir -p "$WORK/selectors" "$WORK/exports"
"$BIN/python" - "$WORK" <<'PY'
import json, sys
work = sys.argv[1]
result = json.load(open(f"{work}/ingest-result.json"))
assert result["state"] == "complete", result   # incomplete는 부분·실패 수집이다. 성공한 0건으로 취급하지 않는다
for ref in result["documentRefs"]:
    if ref["documentVersion"] is None:         # hold/error 문서는 export 대상이 아니다(ingest-result.json의 hold/error를 읽는다)
        continue
    selector = {"schemaVersion": "zoop-ingestion-s2-1", "roundId": result["roundId"], "sourceId": result["sourceId"],
                **{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
    json.dump(selector, open(f"{work}/selectors/{ref['page']}-{ref['ordinal']}.json", "w"))
PY
for selector in "$WORK"/selectors/*.json; do
  "$BIN/zoop-ai-ingest" export --state-dir "$WORK/state" --sources "$WORK/sources.json" --require-store < "$selector" > "$WORK/exports/$(basename "$selector")"
done
```

`collectionId`·`roundId`는 불변이다. 같은 id로 입력이 다르면 `collection_input_conflict`/`round_input_conflict`이므로 다시 돌릴 때는 새 id를 쓴다. `$WORK/exports/*.json`이 수령자가 읽는 산출물이다.

**export가 담는 것과 담지 않는 것(인수 시 읽을 출처·한계).**

| 수령자가 보존할 값 | 위치 | 비고 |
| --- | --- | --- |
| 문서·버전 식별 | `observation.documentId`·`rawVersion`·`documentVersion` | source-local ID다. 같은 URL의 본문이 바뀌면 `documentVersion`이 새로 생기고 문서 ID는 유지된다 |
| 실제 수집 시각 | `observation.collection.fetchedAt`(UTC offset 포함 instant), 원본은 `receipts/<sha256>.json` | 페이지 `Date`·발행 시각이 아니라 이 프로세스가 받은 시각이다 |
| 게시 시각과 정밀도 | `observation.collection.published{raw,precision,date,basis}` | 운영자가 요청에 선언한 값뿐이다(페이지에서 긁지 않음). `day`는 날짜만 남고 자정으로 바뀌지 않으며, 오프셋 없는 시각은 `unresolved`, 미선언은 `unknown`. `observation.publishedAt`은 `instant`일 때만 채워진다 |
| 수집 경로·분류 | `observation.provenance`(`collected_http`), `collection.network`, `collection.documentKind`, `finalUrl`, `httpStatus`, `contentType`, `bodySha256` | `network`가 `synthetic_loopback`이면 시험 서버 bytes이지 외부 문서가 아니다 |
| 권리 | `grant.grantId`·`grant.revision` | export에는 권리 **내용**(rights·evidence·operations)이 없다. 내용은 `sources.json`의 grant가 정본이며 수령자는 grant id/revision과 함께 보관해야 한다 |
| 본문 | `document.text`(준비된 텍스트), `document.rawLocators`, `locatorMetadata.rawHash` | 텍스트는 정리된 사본이고 원본 bytes가 아니다. HTML은 DOM text 좌표, PDF는 page 추출 텍스트 좌표다 |

- **원본 bytes는 export에 들어 있지 않다.** 원본은 `inputRoot/collections/<collectionId>/bodies/<sha256>.bin`과 `ingestion.sqlite3`의 raw BLOB에 있다. 수령자에게 원본이 필요하면 `locatorMetadata.rawHash`·`collection.bodySha256`과 일치하는 파일을 별도로 전달하고, 그 전달도 `read`·`store` 권리가 있는 경우에만 한다.
- **export는 그 순간의 권한 확인 결과**다. 이후 grant가 철회·만료되면 같은 export 명령은 본문 없이 `source_unauthorized`만 낸다. 이미 파일로 복사된 export는 이 CLI가 회수하지 못한다.
- title·kind·게시/수정 시각은 운영자 선언이며 검증된 사실이 아니다. 공개·게시 승인, 요약·감성·기업 연결, 앱 Dataset 등록, 완전성·커버리지 주장은 이 출력에 없다.
- 합성 시연(A)과 실제 모드(B)는 같은 형식이지만 A의 파일을 실제 수집 결과로 인용하면 안 된다. 이 절의 B 명령은 외부 사이트를 대상으로 실행되지 않았다.


`zoop_ai_pipeline.ingestion_cli`의 `run/resume/inspect`는 BFF의 admin `ingest-run`과 **다른 내부 실행 경계**다. 네이티브 URL/HTML/PDF 준비(`ingestion_url`·`ingestion_parsers`·`ingestion_pdf`, lxml·pypdf, 같은 공개 의존성)만 쓰며 private PoC를 import하지 않고 네트워크·모델·PoC 원장·앱/S1 DB에는 연결하지 않는다(네트워크는 위 `zoop-ai-collect`만 연다). 이전 pinned-PoC parser 프로필(`pocCommit`)로 만든 round는 새 프로필(`parser: zoop-native-parsers-1`)과 달라 `resume`이 `parser_profile_changed`로 거부하며, 그 round의 저장된 version과 export는 그대로 읽힌다(재해석하지 않음). 새 프로필의 version은 같은 raw bytes여도 새 preparation key/version id를 가진다. 명시한 전용 `--state-dir`의 private `ingestion.sqlite3`에 원래 response/raw BLOB, source-local 문서 ID, raw/text version, HTML node/PDF page span과 연속 checkpoint를 저장한다. 현재 operator `--sources`는 매번 완전한 snapshot으로 읽고, fixture manifest는 hash-pinned 파일 입력일 뿐 권한을 발급하지 않는다. 수집한 관찰의 `export`는 `observation`에 `provenance: "collected_http"`와 `collection`(실제 수집 시각, 최종 URL, HTTP 상태, 본문 sha256, 문서 종류, `network`, 선언된 게시 시각의 원문·정밀도)을 **추가로** 돌려주며 license를 주장하지 않는다. authored 관찰의 export는 이전과 같은 닫힌 키 집합 그대로다(Java `IngestionExportParser`가 두 형태의 정확한 키 집합을 고정하며, 같은 집합을 `tests/test_collection.py`가 고정한다). run/inspect 결과의 최상위 `provenance`는 두 경우 모두 있다.

저장소 루트에서 다음 명령으로 합성 HTML/PDF와 실제 subprocess CLI를 재현한다. driver는 fresh 임시 입력/상태를 만들고 검사 후 모두 제거한다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/ingestion_smoke.py
```

실제 결과는 `status=passed, preparedDocuments=2, providerCalls=0, modelCalls=0`이었다. receipt/raw/version/checkpoint 저장 뒤 프로세스 중단·resume, 같은 cursor replay, 변경 body의 새 버전, zero/failure/partial/parse hold, stale checkpoint, registry 철회/누락, entity·tail·반복 한글/emoji와 PDF page 좌표, S1 exact의 생성 separator 거부를 확인했다. review 회귀까지 포함한 focused `tests/test_ingestion.py`는 **43 passed, 기존 Starlette warning 1개**였다. 실제 scope A 철회 뒤 scope B의 XPath에 맞는 text/hold 분리와, 첫 supplier의 raw commit 뒤 파일이 없어도 공유 body로 둘째 supplier를 준비하는 복구도 통과했다.

wire schema는 `zoop-ingestion-s2-1`이며 공용 OpenAPI나 S1 schema를 바꾸지 않았다. 정확한 문서/version을 고른 `inspect`만 현재 read 권한으로 내부 S1 `Document` projection을 반환한다. 원문 span 해석에는 quote-display도 요구한다. S2-2가 쓰도록 정확한 관측(round/source/page/ordinal/document/rawVersion/documentVersion)의 서버 소유 URL·title·publishedAt과 grant를 반환하는 읽기 전용 `ingestion_cli export`를 추가했다. HTML 위치는 decoded DOM text/tail 좌표이고 PDF 위치는 frozen page-extracted text 좌표이지 raw byte·glyph geometry가 아니다. 이 문서는 앱 Dataset에 등록되거나 게시되지 않는다. 실제 공급원/정기 수집·기업/이슈 연결·공개 등록/게시·유료 의미 검증은 구현 완료로 주장하지 않는다. 명령·registry·manifest·한계와 실행 증거는 [AI 실행 계약의 S2-1 절](../../docs/design/ai-system.md#s2-1-독립-오프라인-원문-준비와-검사)을 따른다.

## 독립 오프라인 이벤트·SAME·주제 후보 (S2-2)

`zoop_ai_pipeline.extraction_cli`의 `run/submit/resume/inspect/cancel`은 S2-1 ingestion 상태를 **읽기 전용**으로 소비하고 전용 `--state-dir`의 `extraction.sqlite3`에만 쓴다. 분석 규칙(기사 projection, 요청 preimage·digest, 인용 해석, 엄격한 응답 검증, SAME 규칙, 후보 ID)은 `extraction_replay.py`와 `extraction_contracts.py`의 **네이티브·replay 전용** 계약이며 Postgres·Neo4j·네트워크·모델·앱/S1 상태, 원본 PoC 코드·프롬프트에는 연결하지 않는다. authored replay는 독립 AI 추론이 아니고 이 변경으로 생긴 AI 능력도 없다(라이브 S2/S3는 계속 미지원). 결과는 승인·게시가 아닌 event/topic **후보**다. 이벤트 후보는 정확한 인용(S1 exact와 같은 mapped-run 규칙 + ingestion resolver), whole-event 비교(all-member 충돌·근거 부재·multi-SAME hold), 문서/mention/event 별도 ID를 갖고 topic 후보는 별도 `zoop-topic-*` 계약·영수증으로 만든다. 저장소 루트에서 재현한다.

**네이티브 replay 형식 `zoop-analysis-replay-1`.** fixture는 `{format, synthetic, recordingKind:"authored-test", promptVersion, analysisVersion, records:[{stage:"extract"|"compare", requestDigest, response}]}`이며 응답은 그 응답이 답하는 **요청의 정확한 digest**(`sha256`(canonical JSON `{stage, input, version: analysisVersion}`))로 찾는다. 요청 본문(원문)은 fixture에 복사하지 않는다. `promptVersion`·`analysisVersion`은 운영자가 붙이는 **authored 라벨**이며 모델·프롬프트 지문이 아니다. 헤더(형식·synthetic·recordingKind·promptVersion·analysisVersion)만 접수 때 읽고(`replay_fixture_invalid`/`replay_provenance_conflict`/`replay_prompt_version_conflict`), 레코드 전체(단계·digest 형식·중복·추가 키)는 첫 조회에서 호출 예약 전에 검증한다(`replay_fixture_invalid`로 호출 0건 중단). 응답이 없으면 `replay_response_missing`이다. 옛 `investmate-replay-v2` 파일과 변환기는 지원하지 않는다. 숫자 offset은 인용이 정확히 선택하는 정수일 때만 유지되고, 아니면 본문에서 **유일한** 인용으로 다시 구하며 없거나 반복되면 영구 `*_reply_invalid`다. 후보 ID의 fingerprint는 어댑터 버전(`zoop-extraction-native-replay-1`)·후보 버전·두 라벨·catalogue digest에서 나오므로 라벨이나 catalogue가 다르면 같은 문서도 다른 ID를 갖는다. 분석 규칙을 바꾸면 어댑터 버전을 올려야 한다. `Article.version`·요청 preimage·mention JSON 모양은 원본 PoC가 한 번 계산한 literal(`tests/data/native_analysis_golden.json`)과 일치하도록 시험한다.

**이 변경 이전에 저장된 S2 job(원본 PoC 어댑터 binding).** 원장 `zoop-extraction-ledger-1` 스키마는 그대로이고 job마다 저장된 `binding.adapter.version`으로 구분한다. 옛 job은 **읽기용 기록**으로만 남는다: `inspect`는 저장된 상태·binding·호출 요약을 그대로 보여 주되 `delivery`를 `withheld/analysis_contract_changed`로 막고 후보 내용(eventCandidates/topicCandidates)을 싣지 않으며 원천·권한을 읽지 않는다. `run`/`resume`은 어떤 상태(queued·stopped·reconciling·ready)에서도 원천 읽기·호출·상태 쓰기 **전에** `analysis_contract_changed`로 거부하고 재분석·복사·자동 변환을 하지 않는다. S3 submit·graph·handoff가 그 job을 upstream으로 삼으면 같은 코드로 거부·withheld된다. `cancel`은 옛 job에도 기존 의미대로 쓸 수 있는 명시적 정리 수단이고, 새 native job은 같은 원장에 함께 둘 수 있다. 다시 분석하려면 운영자가 native fixture와 **새 job id**(또는 새 상태 디렉터리)로 명시 재제출한다(후보 ID도 달라진다). 이 저장소 밖 운영자 상태는 확인하지 못했다. native job을 쓴 원장에 이 변경 이전 build(PoC 어댑터)를 돌리지 마라.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_extraction.py ai/pipeline/tests/test_extraction_replay.py ai/pipeline/tests/test_ingestion.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/extraction_smoke.py
```

**등록 전용 `submit`(CLI 명령이다. HTTP는 `ai/service`의 별도 `/internal/v1/extraction-jobs` 가족이 서버 사전 승인 요청으로만 호출하며 호출자가 본문·fixture를 고르지 못한다).** `extraction_cli submit`은 `run`에서 등록 절반만 분리한 명령이다. 같은 stdin 요청과 필수 `--replay`로 입력과 replay 파일 hash를 불변 binding으로 먼저 저장해 `queued` job을 만들고 `inspect`와 같은 결과를 돌려준다. replay 모델 구성·stage 실행·호출 예약·후보 쓰기·네트워크는 없고(`calls=[]`, `usage.replayCalls=0`) 등록 때 ingestion과 `--sources`는 읽는다. replay 파일 hash가 job 입력 digest에 들어가므로 `--replay`가 필요하고(없으면 `replay_fixture_required`), job에 고정되지 않는 `--topic-replay`는 `fixture_not_allowed`이며 topic stage의 fixture는 이후 `resume`/`run`에서만 지정한다. live provenance는 `live_mode_unsupported`다. 같은 `jobId`와 같은 입력의 재제출은 저장된 job을 `inspect`처럼 보고만 한다. queued·stopped·ready·cancelled 어느 상태에서도 resume·재고정·상태 초기화·호출을 하지 않으며 현재 권한은 반환 결과의 `delivery`에만 적용된다(철회·grant revision 변경이면 `withheld`와 종료 코드 2이지만 고정된 binding은 바뀌지 않는다). 다른 입력이나 다른 replay bytes는 아무것도 쓰지 않고 `job_input_conflict`이며, 잘못된 fixture를 고정한 job은 같은 jobId로 고칠 수 없어 새 jobId를 쓴다. 실행은 이후 `resume`(필요한 같은 `--replay`)이 하고 권한·binding은 그때 다시 검사하므로 submit 뒤 철회·grant revision 변경은 호출 없이 `stopped`다. queued job은 `cancel`로 호출 전에 취소할 수 있다. `run`은 같은 등록 경로(`Extractor.freeze`) 뒤 `resume`하는 기존 편의 명령이며 동작은 그대로다. 아래 시험·smoke 수치는 submit 추가 이전 기록이고, submit 회귀 시험(`test_extraction.py`의 submit 절)과 smoke 12단계의 통과는 최종 실행 결과로만 기록한다.

실제 결과는 **90 passed, 1 warning**(extraction 47 + ingestion 43, 기존 Starlette warning)과 smoke `status=passed, providerCalls=0, modelCalls=0`이었다. smoke는 실제 ingestion/extraction subprocess에 socket audit hook을 걸고 same/distinct event·topic, 충돌·누락 날짜, multi-SAME, 한글/emoji/separator/반복 quote, raw-only 변경, 위조 입력, 철회 grant, receipt/stage 중단 복구, 잘못된 fixture의 receipt 미생성, separator snapshot member 거부, ingestion 읽기 쪽 mode/bytes/파일 불변을 검사한다. ingestion `export`와 extraction의 ingestion 접근은 shared flock과 `immutable=1` 읽기 전용 열기이며 중단된 writer가 남긴 비어 있지 않은 WAL은 `ingestion_recovery_required`로 거부한다. S3 소비자용 `Store(existing=True)`/`Extractor.export`도 같은 읽기 전용 정책이다. live 전송·retrieval·cross-job cache·앱 등록·승인 topic은 구현하지 않았다. wire/binding/복구 규칙은 [AI 실행 계약의 S2-2 절](../../docs/design/ai-system.md#s2-2-오프라인-이벤트same주제-후보-준비)을 따른다.

## 독립 오프라인 관계·영향 후보와 HOLD 재검증 (S3, FS078·FS079)

`zoop_ai_pipeline.relation_cli`의 `run/submit/resume/inspect/review/revalidate/cancel`은 **완료된 S2 job 하나**(`upstream:{jobId,inputDigest}`)를 extraction·ingestion의 읽기 전용 snapshot으로만 소비하고 전용 `--state-dir`의 `relation.sqlite3`에만 쓴다. 호출자가 후보 JSON을 보낼 수 없고 event/topic 후보·catalogue·문서는 서버 소유 registry로 다시 검증한 S2 결과에서만 온다. producer replay(`--replay`)와 **독립된** verifier replay(`--verifier-replay`)는 별도 파일·영수증이며 둘 다 authored 응답일 뿐 AI 의미 품질 주장이 아니다. 후보는 `approved=false`이며 `eligible`은 자동 증거 gate 통과이지 승인·게시가 아니다. 공개 OpenAPI·HTTP·UI·앱 등록·관리자 화면은 없고 이 CLI 자체는 그래프를 쓰지 않는다(완료된 job 하나의 **비공개** Neo4j stage는 별도 명령 `zoop-ai-graph`이며 아래 절, 활성 공개 상태 없음). 관계 유형(`SUPPLIES`·`INVESTS_IN`·`COMPETES_WITH`·`PARTICIPATES_IN`·`RELATES_TO_TOPIC`)은 FS055 공통 계약 확정 전의 보수적 임시 어휘다. 저장소 루트에서 재현한다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_relation.py ai/pipeline/tests/test_extraction.py ai/pipeline/tests/test_ingestion.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/relation_smoke.py
```

**등록 전용 `submit`(CLI 전용, HTTP 아님).** `relation_cli submit`은 `run`의 등록 절반이다. 완료(ready)되고 현재 권한·binding이 검증되는 S2 job이 있어야 하며 아니면 `upstream_not_ready`(또는 S2의 withheld 코드)로 거부되고 job은 만들어지지 않는다. 성공하면 upstream identity와 `upstream.digest`를 불변 binding으로 고정한 `queued` job을 만들고 `inspect`와 같은 결과를 돌려준다(`calls=[]`, `usage.replayCalls=0`). **S3 submit은 fixture를 받지 않는다.** `--replay`와 `--verifier-replay`는 `fixture_not_allowed`다. S2와 달리 producer·verifier fixture는 job binding이나 입력 digest에 들어가지 않고 호출별 영수증(`calls.fixture_hash`)에만 기록되는 입력이어서 이후 `resume`/`run`/`revalidate`가 단계마다 지정한다. live provenance는 `live_mode_unsupported`다. 같은 `jobId`와 같은 입력의 재제출은 저장된 job을 `inspect`처럼 보고만 한다. queued·stopped·ready·cancelled 어느 상태에서도 resume·재고정·상태 초기화·호출·HOLD 검토 반영(재검증)을 하지 않으며 현재 권한은 반환 결과의 `delivery`에만 적용된다. 다른 입력(다른 upstream 포함)은 `job_input_conflict`다. 실행 때 현재 upstream·권한·binding을 다시 확인하므로 submit 뒤 S2의 권한·grant revision이 바뀌면 호출 없이 `stopped`다. queued job은 `cancel`로 호출 전에 취소할 수 있다. `run`은 같은 등록 경로(`Engine.freeze`) 뒤 `resume`하는 기존 편의 명령이며 동작은 그대로다. 아래 시험·smoke 수치는 submit 추가 이전 기록이고, submit 회귀 시험(`test_relation.py`의 submit 절)과 smoke 13단계의 통과는 최종 실행 결과로만 기록한다.

실제 결과는 **142 passed, 1 warning**(relation 52 + extraction 47 + ingestion 43)과 smoke `status=passed, providerCalls=0, modelCalls=0`이었다. smoke는 실제 ingestion·S2 extraction으로 만든 upstream을 relation subprocess(socket audit hook)로 읽어 방향 뒤집힘 hold, 경쟁 쌍 정규화, 같은 쌍의 다른 유형·범위 보존, 경로 단계 누락·알 수 없는 endpoint hold, 직접 대 2단계, mixed/positive/undetermined와 eligibility 분리, HOLD allow→재검증과 재검증 receipt 뒤 중단 복구(fixture·추가 호출 없이 verdict append), receipt 뒤 중단 복구, 위조 upstream·fixture, 철회 권한, upstream bytes/mode 불변을 검사한다. 명령·wire·gate·한계는 [AI 실행 계약의 S3 절](../../docs/design/ai-system.md#s3-오프라인-관계영향-후보와-hold-재검증)을 따른다.

## 읽기 전용 의존 대상 조회 (S4 일부, FS081 일부)

`zoop_ai_pipeline.dependency_cli`(설치 명령 `zoop-ai-dependents`)는 변경된 **문서(선택: raw/문서 version)·source·grant(선택: revision) 하나**를 받아 ingestion·extraction(·선택적 relation) 원장에 이미 고정된 기록에서 그 변경에 기대는 S2 job·snapshot event·event 후보·비교·주제와 S3 job·관계·영향 후보를 나열한다. `Store(existing=True)`로만 열고 shared lock을 출력이 끝날 때까지 모두 유지하며, 현재 registry·권한·delivery를 판정하거나 어떤 것도 쓰지·철회하지·재생성하지·게시하지 않는다. 변경 모양의 null은 묶인 모든 값(과거 포함)이지 "최신"이 아니고, 일치 기준은 job을 만들 때 고정한 관측과 grant(현재 registry 아님)다. 출력은 ID·digest·좌표·상태·reason 코드뿐(원문·quote·제목·URL·경로 없음)이며 `notCovered`에 스캔하지 않은 범위가 항상 명시된다. 완전성은 스캔한 원장에 한정되고 전체 철회 closure가 아니다.

```sh
zoop-ai-dependents --ingestion-state-dir DIR --extraction-state-dir DIR [--relation-state-dir DIR] < query.json
# query.json: {"schemaVersion":"zoop-dependency-s4","changed":{"kind":"document","documentId":"…","documentVersion":null,"rawVersion":null}}
#             {"kind":"source","sourceId":"…"}  |  {"kind":"grant","grantId":"…","revision":null}   (null 키도 생략 불가)
```

`--relation-state-dir`를 생략하면 `relation`은 `null`이다(빈 목록이 아니다). 없는 디렉터리·손상·hot WAL·활성 writer·알 수 없는 원장 버전·파싱되지 않는 저장 행·배열이 아닌 의존 container(citations·path·topic members 등)·ingestion 원장에도 없는 변경 ID는 부분 출력 없이 exit 2의 오류 코드로 닫힌다(성공-빈 결과가 되지 않는다). 항목이 10,000개를 넘으면 자르지 않고 `dependency_report_limit`로 거부한다. relation job은 S3가 고정한 upstream으로만 스캔한 extraction job과 연결한다. `(jobId, inputDigest)`는 요청·replay만 덮고 고정된 grant는 덮지 않으므로, 추가로 S3 binding의 `upstream.digest`(고정된 binding·grant와 전달 후보)를 저장 행에서 다시 계산해 비교한다. upstream이 스캔한 원장에 없거나(`upstream_not_in_scanned_ledger`), 입력 digest가 다르거나(`upstream_input_mismatch`), ready가 아니거나 digest가 다른 경우(`upstream_binding_mismatch`, 예: 같은 job·입력이 다른 grant revision으로 고정된 원장)는 영향 여부를 판단하기 전에 버리지 않고 `unresolved`로 나열한다. 각 job의 `jobScope`는 job 전체 개수이고 직접 항목은 그 부분집합이다. 이 명령은 CLI 전용이며 HTTP·OpenAPI·앱 DB에 연결하지 않았다. relation 원장에도 `Store(root, *upstream_roots, existing=True)` 읽기 전용 모드를 추가했고 기존 호출은 그대로다. 명령·wire·reason 코드·한계 상세는 [AI 실행 계약의 S4 절](../../docs/design/ai-system.md#s4-일부-s2s3-의존-대상-조회-읽기-전용)을 따른다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_dependency.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/dependency_smoke.py
```

10/13 최종 로컬 작업 트리에서 전체 pipeline 시험 **208 passed**, `dependency_smoke.py`는 **status=passed, providerCalls=0, modelCalls=0**이었다. 실제 CLI에서 권한 철회 후 메타데이터 조회, 같은 job·입력이라도 다른 grant에 고정된 upstream의 불일치, 잘못된 원장·입력의 거부, 원문 미노출과 원장 무변경을 확인했다. 검토 후 추가한 회귀 15건도 모두 통과했다. 실행 조건·수정 전 재현 범위·남은 기능은 위 S4 계약을 따른다. 이번 변경의 원격 CI·운영 배포는 실행하지 않았다.

## 비공개 S3 → Neo4j 버전 projection (FS080 일부, 게시·FS081 철회 아님)

`zoop_ai_pipeline.graph_projection_cli`(설치 명령 `zoop-ai-graph`)는 완료되어 현재 전달 가능한 S3 job **하나**를 읽기 전용 seam(`relation.Store(existing=True)` + `Engine.inspect`)으로만 읽어 `versionId` 하나의 **불변 Neo4j version**으로 stage한다. 공개 활성화(FS059)·앱 등록·HTTP·증분 갱신·철회(FS081)·영향 라벨·두 기업 사이 경로는 없다. `ready`는 "stage되고 전체 검증됨"이며 출력의 `publication`은 항상 `not-published`다. canonical 매핑 파일은 운영자의 canonicalization **결정**이며 공개 승인·S2 SAME·topic 승인이 아니다.

```sh
# stdin은 JSON 한 개(<= 65,536B)다. init·preflight만 --graph-uri bolt://127.0.0.1:<port> 또는 bolt+s://<host>:<port> 를 받고 자격은 환경 ZOOP_GRAPH_AUTH=none|basic, ZOOP_GRAPH_USER, ZOOP_GRAPH_PASSWORD 에서만 읽는다(비루프백 TLS는 basic 필수). 사설 CA의 bolt+s 대상은 그 명령에만 SSL_CERT_FILE=<공개 CA pem>을 준다.
zoop-ai-graph init    --state-dir DIR --graph-uri bolt://127.0.0.1:7687      # stdin {"schemaVersion":"zoop-graph-projection-1","storeId":"…","database":"neo4j"}; 비어 있는 별도 database 하나에 이 원장을 한 번 묶는다
zoop-ai-graph preflight --state-dir DIR --graph-uri bolt+s://neo4j.dev.zoop.internal:7687   # init과 같은 stdin. 원장·디렉터리·잠금 없음, DDL·쓰기 없음, 닫힌 읽기 문장만. 후보 확인이지 init 성공 보장이 아니다(DDL 권한 미검증)
# 아래 freeze/project/read/focus는 --relation-state-dir --extraction-state-dir --ingestion-state-dir --sources --canonical이 모두 필요하다
zoop-ai-graph freeze  --state-dir DIR …    # stdin {"schemaVersion":…,"versionId":"…","relation":{"jobId":"…","inputDigest":"<64hex>"}}   SQLite만, Neo4j 접촉 없음
zoop-ai-graph project --state-dir DIR …    # stdin {"schemaVersion":…,"versionId":"…"}    단일 explicit transaction
zoop-ai-graph read    --state-dir DIR …    # stdin {"schemaVersion":…,"versionId":"…"}    현재 gate + 전체 그래프 검증
zoop-ai-graph focus   --state-dir DIR …    # stdin {"schemaVersion":…,"versionId":"…","companyId":"…","depth":1}   depth 1|2|3
# 원천 flag가 없는 명령: recover(읽기만, unknown commit 정리, Neo4j 필요), inspect(원장만, Neo4j 호출 없음)
```

원장 `graph.sqlite3`는 자기 디렉터리(app·S1·세 원천 원장과 겹치면 `state_namespace_conflict`)에만 쓰며 읽기 전용 명령(`inspect`/`read`/`focus`)은 원장이 없을 때 상태를 만들지 않고 `graph_state_missing`으로 닫힌다. canonical 결정은 `--canonical` 파일(`zoop-graph-canonical-1`, 정확한 S2 upstream `(jobId, inputDigest)`·`kind`·S3 endpoint `ref`별 `canonicalId`·`decisionRef`)이 유일한 출처이고 매 명령이 새로 읽는다. 필수 endpoint 결정이 없거나 별칭 합침이 자기 관계·경로 붕괴를 만들면 **전체 freeze가 실패**한다. 자세한 wire·저장 형태·트랜잭션·복구·읽기 검증·오류 코드·한계는 [AI 실행 계약의 해당 절](../../docs/design/ai-system.md#s3--비공개-neo4j-버전-projection-fs080-일부게시fs081-철회-아님)을 따른다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_graph_projection.py -q -p no:cacheprovider        # Neo4j 불필요
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_graph_preflight.py -q -p no:cacheprovider        # Neo4j 불필요: 드라이버 경계의 메모리 내 서버가 닫힌 읽기 문장에만 답한다(TLS·인증의 실제 증명은 아래 graph_tls_smoke.py)
# 실제 Neo4j 5의 격리된 빈 database가 필요하다(없으면 실패, skip 아님). 실행마다 --run-id의 version 접두로만 쓰고 전체 삭제를 하지 않는다.
ZOOP_GRAPH_SMOKE_URI=bolt://127.0.0.1:<port> ZOOP_GRAPH_AUTH=none PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_projection_smoke.py   # make pipeline-graph-smoke도 같은 스크립트
ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_projection_smoke.py --cleanup <runId>   # 실패한 실행의 version·store 마커를 이름으로만 제거
# 독립 검토 R1–R4의 실제 Neo4j 회귀 11개: 비어 있는 별도 database가 필요하고 사례마다 자기 run id를 쓰며 정확한 이름으로만 정리한다.
ZOOP_GRAPH_REGRESSION_URI=bolt://127.0.0.1:<port> ZOOP_GRAPH_AUTH=none PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_projection_regression.py [--cases r1a,r3c,...]
# 로컬 전용 실제 TLS 증명(bolt+s + basic 인증, Community 5.26.32 digest 고정 이미지, 명시 옵트인): 자기 PKI·자기 컨테이너를 만들고 정확히 만든 것만 지운다. 이미지는 미리 pull되어 있어야 하며 스크립트는 pull하지 않는다.
ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_tls_smoke.py --manage-containers [--stages cases,smoke,regression]    # make pipeline-graph-tls-smoke
# 이미 가진 TLS 서버(bolt+s://localhost:<port>, SAN은 DNS:localhost만)와 공개 CA pem이 있으면: ZOOP_GRAPH_TLS_SMOKE_URI/_CA/_WRONG_CA + ZOOP_GRAPH_AUTH=basic ZOOP_GRAPH_USER ZOOP_GRAPH_PASSWORD 후 --stage cases|smoke|regression
```

**2026-10-16 `preflight`·로컬 TLS 실행 기록(로컬 작업 트리·미커밋, Main 실행. 원격 CI·AWS 없음).** `ai/pipeline` 시험 전체 **665개 통과**(`preflight` 시험 포함). `graph_tls_smoke.py --manage-containers`(실행 id `dd2cfee7`)는 digest 고정 공식 `neo4j@sha256:f1e52d4dc6da122468c4a3c1050a4f5e117f6d3268625237c34d49166f0d6082`(5.26.32 Community)로 `cases`·`smoke`·`regression` **3단계가 모두 통과**했다. 단계마다 새 빈 컨테이너를 썼고 `bolt+s`·기본 인증으로 실행했으며, CLI 명령 출력 JSON 34개를 검사했다(비밀번호·자격 필드·대상 호스트·경로 없음). 컨테이너와 임시 PKI는 모두 제거됐다. 이 실행의 N8 하위 사례 `state_ownership_unconfigured`는 소스 체크아웃이라 smoke에서는 실행되지 않았고(출력에 명시), 아래 별도 검사로 완료했다. **설치된(비편집) wheel 검사**(Main 실행, 임시 venv·오프라인 설치): 소유권 변수 6가지(없음·하나만·빈 값·상대 경로)는 `state_ownership_unconfigured`이며 소켓 이벤트 0·생성된 상태 0, 올바른 변수로 예약 루트 안을 가리키면 `state_namespace_conflict`(소켓 0), 올바른 변수와 닫힌 포트는 이유가 바뀌어 `graph_unavailable`이며 소켓 이벤트 3개가 모두 `localhost`·그 포트뿐이고 상태·디렉터리가 생기지 않았다. 이 검증은 **로컬 Community 5.26 TLS·기본 인증과 `preflight`/`init`에 한정**되며 AWS·Fargate·RBAC·DNS·SSM·`GraphDbStatus` 준비의 증명이 아니다. 실제 DDL 권한은 `preflight`가 증명하지 않으며 `init` 성공은 별개로 확인된다. 성능·부하는 측정하지 않았다.

**2026-10-15 최종 실행(로컬 작업 트리·미커밋, Main 실행. 커밋·푸시·원격 CI 없음).** `ai/pipeline` 시험 전체 265개가 통과했다. 실제 Neo4j 5.26 Community(격리된 `--rm` tmpfs 임시 컨테이너, 종료·정리 완료)에서 R1–R4 회귀 11개는 수정 전 11개 모두 RED로 재현됐고 수정 뒤 모두 통과했다. 새 빈 database의 정상 smoke는 다섯 관계 유형 전부, 노드 6·간선 6의 `v1`, 노드를 공유하지 않는 `v2`(`v1` 원본 바이트 불변), 깊이 1·2·3 focus, 반복 `init` 멱등, 권한 철회 withheld, unknown commit·SIGKILL 뒤 rollback·변조 fail-closed를 모두 통과했다. provider·모델 호출은 0이었고 원천 원장은 읽기 전용이었다. 활성 공개 상태는 없다(FS080 일부, FS081 철회 아님). **성능·지연·부하는 측정하지 않았고** 이 검증은 기능에 한정된다. 자세한 기록과 남은 범위는 위 AI 실행 계약의 시험 절을 따른다.
