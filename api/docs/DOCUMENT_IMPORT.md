# 문서 등록 import (S2-1 export → PostgreSQL)

FS056(WBS 6.5.2)의 **문서 쪽** 저장입니다. 설치된 `zoop-ai-ingest export`가 내보낸 정제 텍스트 한 건(문서 버전)을 앱 DB의 `artifacts`·`articles`·`article_versions`(ERD v6 §14–16)와 로컬 파일로 등록합니다. 운영자가 실행하는 **비웹 Spring 프로세스**이며 HTTP 경로는 없습니다. 목표 OpenAPI에도 문서 쓰기 경로가 없습니다.

**하지 않는 것:** 분석·요약·감성 결과 import(별도의 operator 실행인 [문서 분석](DOCUMENT_ANALYSIS.md)이 `document_analyses`·`evidence`·`ai_executions`에 저장하며 여기서는 쓰지 않음, `analysis_jobs`는 아직 없음), 그래프 반영, 공개·발행, 사건(event) 쪽 FS056 항목, 수집 실행·스케줄, 원문(raw) 바이트 저장(S2-1이 내보내지 않으므로 `raw_artifact_id`는 NULL), 문서를 읽는 API. 등록된 행은 **읽기 권한이 아니라 이력**입니다(아래 [접근](#접근과-권리)).

## 흐름

항목마다 순서대로, 항목 하나가 끝난 뒤 다음으로 갑니다.

1. **새 export.** `zoop-ai-ingest export --require-store`를 항목마다 새 하위 프로세스로 실행합니다. 미리 만든 JSON이나 이전 export를 받는 입력은 없습니다. CLI가 그 시점의 현재 source registry(`--sources`)로 권한을 확인합니다(grant 활성, `rights=known`, 근거 있음, **`read`·`store`·`quote-display` 모두 허용**, 미만료, 범위 설정 불변). 텍스트를 저장하는 소비자라서 `store`를 명시적으로 요구하며(`--require-store`는 export 전용이고 기본 export의 두 권리 계약은 그대로), export 문서에는 grant id·revision만 있어 Java는 권리를 직접 평가하지도 registry를 읽지도 않습니다.
2. **엄격 검증.** 키 집합이 정확히 일치하고, 선택자 7개 값이 요청과 같고, `textArtifactId == "text-" + documentVersion`이고, 텍스트가 `sourceHash`(= Python `sha256(json.dumps(text, ensure_ascii=False))`)와 일치해야 합니다. 시각은 ISO-8601 + offset, 마이크로초 이하만 받고 Python이 다르게 읽을 수 있는 형식은 추측하지 않고 거부합니다.
3. **파일.** `<artifact-root>/extracted_text/<textArtifactId>.txt`에 UTF-8 바이트를 한 번만 씁니다(0600, 임시 파일 → fsync → 덮어쓰기 없는 hard link → 파일·내용 디렉터리·루트 fsync). 같은 이름의 파일이 이미 있으면 **루트와 같은 소유자·정확히 0600·같은 바이트인 정규 파일만** 채택하며, 채택하기 전에 그 파일·내용 디렉터리·루트를 fsync합니다. 바이트가 다르거나 정규 파일이 아니면 `artifact_file_conflict`, 소유자·권한이 다르면 `artifact_store_unavailable`이고 어떤 경우에도 **덮어쓰거나 chmod로 고치지 않습니다.** 규칙 전체는 [파일 저장소 규칙](#파일-저장소-규칙)입니다.
4. **DB transaction 한 번**(외부 호출 없음). 아래 [트랜잭션](#트랜잭션)을 참고하세요. 실패하면 이 항목이 만든 행은 전부 롤백됩니다.

한 요청은 1~100개 항목이고 **첫 실패에서 멈춥니다.** 앞 항목은 이미 커밋돼 있고 결과 파일에 그렇게 적힙니다. 뒤 항목은 `not_attempted`입니다.

## 실행

기본은 비활성이고 평소 기동에는 아무 설정도 필요하지 않습니다. 활성화하면 모든 값을 시작 시 검증하고 하나라도 틀리면 기동이 닫힘 실패합니다(메시지에는 설정 이름만 있고 값은 없음).

| 환경 변수 | 용도 |
|---|---|
| `ZOOP_DOCUMENT_IMPORT_ENABLED` | `true`일 때만 동작(기본 `false`). **웹 서버와 함께는 시작을 거부**하므로 `--spring.main.web-application-type=none`이 필수 |
| `ZOOP_DOCUMENT_IMPORT_REQUEST` | 운영자 요청 JSON(존재하는 파일, 최대 1 MiB) |
| `ZOOP_DOCUMENT_IMPORT_RESULT` | 결과 파일. **없어야 하며** 실행 시작 시 배타적으로 만들어집니다 |
| `ZOOP_INGESTION_CLI` | 설치된 `zoop-ai-ingest` 실행 파일(예: `ai/pipeline/.venv/bin/zoop-ai-ingest`) |
| `ZOOP_INGESTION_STATE_DIR` | 기존 S2-1 ledger 디렉터리. CLI가 읽기 전용으로 엽니다(Java는 열지 않음) |
| `ZOOP_INGESTION_SOURCES` | 현재 운영자 source registry. **이것이 import 시점의 권한입니다** |
| `ZOOP_ARTIFACT_ROOT` | 앱 파일 저장소 루트. 존재하는 POSIX 디렉터리, symlink 성분 없는 실경로(macOS는 `/var/...`가 아니라 `/private/var/...`), 소유자 외 group·world 쓰기 불가, ingestion state와 서로 포함하지 않음. 이 중 하나라도 어기면 기동이 닫힘 실패하고 매 실행(락 취득 전)에도 다시 확인합니다 |
| `DB_URL` `DB_USERNAME` `DB_PASSWORD` | 기존 DB 연결. **하위 CLI에는 전달되지 않습니다** |
| `ZOOP_STATE_DIR` `ZOOP_AI_WORKER_STATE_DIR` | 설정돼 있으면 CLI에만 그대로 전달(설치형 S2-1 패키지의 상태 소유권 필수 값) |

모든 경로는 정규화된 절대 경로여야 합니다. 요청·결과 파일은 ingestion state 디렉터리 안에 둘 수 없습니다(CLI가 낯선 파일이 있는 state를 거부합니다).

```sh
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
./api/gradlew -p api assemble
env -i PATH=/usr/bin:/bin HOME="$HOME" \
  DB_URL=… DB_USERNAME=… DB_PASSWORD=… \
  ZOOP_DOCUMENT_IMPORT_ENABLED=true ZOOP_DOCUMENT_IMPORT_REQUEST=/abs/request.json ZOOP_DOCUMENT_IMPORT_RESULT=/abs/result.json \
  ZOOP_INGESTION_CLI=/abs/zoop-ai-ingest ZOOP_INGESTION_STATE_DIR=/abs/ingestion-state ZOOP_INGESTION_SOURCES=/abs/sources.json \
  ZOOP_ARTIFACT_ROOT=/abs/artifacts \
  "$JAVA_HOME/bin/java" -jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --spring.main.web-application-type=none
```

종료 코드는 모든 항목이 성공했을 때만 0입니다. 실패하면 결과 파일을 쓴 뒤 코드만 담은 예외로 끝나 JVM이 0이 아닌 값으로 종료합니다. 같은 JVM은 시작할 때 Flyway migration(`V20261014120000`)도 적용합니다.

## 요청 (`zoop-document-import-1`)

```json
{"schemaVersion": "zoop-document-import-1",
 "items": [
  {"kind": "news",
   "observation": {"roundId": "r1", "sourceId": "synthetic-source", "page": 0, "ordinal": 0,
                   "documentId": "doc-<64hex>", "rawVersion": "<64hex>", "documentVersion": "<64hex>"},
   "currentVersion": {"expected": null}}
 ]}
```

- 닫힌 스키마입니다. 모르는 키·중복 키·잘못된 타입·범위 밖 값은 `request_invalid`입니다. export, 텍스트, grant, 경로를 실어 보낼 키는 **없습니다.**
- `observation`은 S2-1 `Export` 선택자에서 `schemaVersion`을 뺀 것입니다. `zoop-ai-ingest run|resume|inspect`의 `documentRefs` 값을 그대로 옮깁니다. `roundId`·`sourceId`는 1~200 코드 포인트(Unicode 그대로, `U+0000`·짝 없는 surrogate 불가).
- `kind`는 `news` 또는 `disclosure`이며 운영자가 선언합니다(S2-1 source에 종류가 없습니다). 이미 있는 article의 kind와 다르면 `article_kind_conflict`입니다.
- `currentVersion`은 세 가지입니다. **없음** = 삽입만, 포인터는 건드리지 않음. `{"expected": null}` = 현재 버전이 없어야 함. `{"expected": "<64hex>"}` = 정확히 그 값이어야 함. 값이 있으면 포인터를 **이 항목의 `documentVersion`**으로 compare-and-set 합니다. `"currentVersion": null`이나 `expected`가 없는 객체는 `request_invalid`입니다.

## 결과 (`zoop-document-import-1`)

시작할 때 `O_EXCL`로 예약하는 0600 파일이며 텍스트·절대 경로·자격 증명이 없습니다. 프로세스가 중간에 죽으면 **빈 파일**로 남는데, 결과를 모른다는 뜻입니다(모든 단계가 멱등이므로 새 결과 경로로 다시 실행하면 됩니다).

```json
{"schemaVersion":"zoop-document-import-1","status":"succeeded|failed",
 "items":[{"index":0,"status":"imported","documentId":"…","documentVersion":"…","textArtifactId":"…",
           "article":"created|existing","artifact":"created|existing","artifactFile":"created|existing","version":"created|existing",
           "currentVersion":{"result":"unchanged|moved|already-current","value":"<version>|null"},
           "collectedAt":"2026-10-14T01:02:03.456789Z","grant":{"grantId":"…","revision":"…"}},
          {"index":1,"status":"failed","failure":{"code":"current_version_conflict","currentVersion":"…|null"}},
          {"index":2,"status":"not_attempted"}]}
```

요청 전체가 실패하면 `{"status":"failed","failure":{"code":"request_invalid"},"items":[]}`입니다. 락 때문에 시작하지 못하면 `failure.code`가 `import_busy`이고 모든 항목이 `not_attempted`입니다. 거부된 export는 `failure.ingestionCode`에 CLI의 코드(`source_unauthorized`, `ingestion_busy`, `ingestion_recovery_required`, `observation_not_found` 등 소문자 snake_case만)를 담습니다.

| 코드 | 의미 |
|---|---|
| `request_invalid` | 요청 파일이 스키마·크기·형식에 맞지 않음(예: export를 실어 보내려는 키) |
| `result_unavailable` | 결과 파일을 만들 수 없음(이미 존재 등). 아무 작업도 하지 않음 |
| `import_busy` | 다른 import가 `<artifact-root>/.document-import.lock`을 잡고 있음 |
| `ingestion_export_failed` | CLI가 export를 거부함(보통 grant 철회·만료·허용 작업 부족) |
| `ingestion_export_unavailable` | CLI를 실행하지 못했거나 시간(120초)·출력(16 MiB) 한도를 넘음, 또는 형식 불명 |
| `export_invalid` | export 키·선택자 echo·타입이 계약과 다름 |
| `identity_unsupported` | `textArtifactId`가 `text-<documentVersion>`이 아니거나 ID 모양이 다름 |
| `text_hash_mismatch` / `text_encoding_invalid` | 텍스트가 `sourceHash`와 다름 / UTF-8로 표현할 수 없음 |
| `published_at_unsupported` / `metadata_unsupported` | 시각 형식·정밀도 불가 / title·url이 비었거나 길거나 `U+0000` 포함 |
| `artifact_file_conflict` / `artifact_store_unavailable` | 같은 이름에 다른 파일이 있음(건드리지 않음) / 루트·디렉터리·파일시스템을 쓸 수 없음 |
| `article_provider_conflict` / `article_kind_conflict` | 기존 article의 provider·kind와 다름 |
| `article_access_unavailable` | article의 `access_status`가 `available`이 아님(private·deleted). 아무것도 쓰지 않고 상태를 되돌리지도 않음 |
| `artifact_conflict` / `version_conflict` | 기존 artifact·버전 행의 불변 값과 다름 |
| `current_version_conflict` | 포인터가 기대값과 다름. `currentVersion`에 실제 값(없으면 `null`) |
| `database_unavailable` | DB 오류. **결과가 불명확**할 수 있어 아래 파일 규칙이 달라짐 |
| `internal_error` | 예상 못 한 오류(메시지는 기록하지 않음) |

## DB 매핑

| 대상 | 값 |
|---|---|
| `articles.id` | `documentId` 그대로 (`doc-` + sha256, source 결속이라 전역 유일) |
| `articles.provider` / `kind` | `sourceId` / 요청의 `kind`. 처음 만들 때만 정함 |
| `articles.provider_key` / `lineage_key` | NULL (S2-1이 공급자 키를 내보내지 않으며 만들어 채우지 않음) |
| `articles.current_version` | 처음엔 NULL. **명시적 compare-and-set으로만** 이동(첫 import도 암묵적으로 지정하지 않음) |
| `articles.access_status` | 새로 만들 때만 `available`. 이후 변경하지 않음 |
| `article_versions.version` | `documentVersion` 그대로 |
| `title` / `url` | export의 `title`(빈 문자열 유지) / 정규화된 `url` |
| `published_at`, `published_date`, `publication_precision` | `publishedAt` 있음 → (그 시각, NULL, `datetime`), 없음 → (NULL, NULL, `unknown`). `day`는 만들지 않고 자정을 지어내지 않음 |
| `publisher`, `raw_artifact_id` | NULL (내보내지 않음) |
| `collected_at` | **처음 등록된 관찰**의 `observedAt`(원장 page 수신 시각). import·replay 시각이 아님 |
| `artifacts.id` | `textArtifactId` 그대로 (`text-<documentVersion>`) |
| `artifacts.kind` / `media_type` | `extracted_text` / `text/plain; charset=utf-8` |
| `artifacts.storage_uri` | `artifact-root:extracted_text/<textArtifactId>.txt` (상대 URI. 절대 경로 없음) |
| `artifacts.sha256` / `bytes` | Spring이 저장한 UTF-8 바이트로 계산(S2-1 `sourceHash`가 아님). 같은 바이트의 다른 문서는 별개 artifact로 같은 해시를 가질 수 있음 |

## 트랜잭션

`DocumentRegistrationService.register` 한 번이 한 transaction입니다.

1. `INSERT … ON CONFLICT (id) DO NOTHING`으로 article을 만들고 `SELECT … FOR UPDATE`로 잠급니다. provider·kind·`access_status`를 확인합니다.
2. artifact를 같은 방식으로 넣고 kind·URI·sha256·bytes·media type이 같은지 비교합니다. 다른 id가 같은 URI를 쓰려 하면 `artifact_conflict`입니다.
3. 버전을 같은 방식으로 넣고 title·publisher·published_at·published_date·precision·raw artifact·text artifact를 비교합니다(`version_conflict`). **`url`과 `collected_at`은 비교도 갱신도 하지 않고** 처음 값을 돌려줍니다.
4. 포인터 요청이 있으면: 현재 값이 이미 이 버전이면 `already-current`(쓰기 없음, 재실행이 멱등), 아니면 `UPDATE … WHERE current_version IS NOT DISTINCT FROM :expected`가 한 행을 바꾸면 `moved`, 아니면 `current_version_conflict`입니다. 버전은 해시라 순서가 없으므로 관찰 시각·발행 시각·replay 순서로 “최신”을 추론하지 않습니다. 오래된 버전으로 되돌리는 것도 명시적 결정이어야 합니다.

DB는 JPA `ddl-auto: validate`와 제약·트리거로 같은 불변식을 지킵니다. CHECK(kind·상태·발행 정밀도 3종·bytes·sha256), `UNIQUE(storage_uri)`, `(id, current_version)` → `article_versions` 복합 FK, RESTRICT 삭제, `artifacts`·`article_versions` UPDATE 거부 트리거, `articles`의 신원 열 UPDATE 거부 트리거(`access_status`·`current_version`만 변경 가능).

**롤백과 파일.** DB 트랜잭션이 실패(정의된 `DocumentImportException`)하면 이 항목이 **새로 만든** 파일만 지웁니다(내용 재확인 후). 이미 있던 파일은 지우지 않습니다. DB 결과가 불명확한 실패(연결·commit 오류, `database_unavailable`)와 예상 못 한 오류에서는 행이 커밋됐을 수 있으므로 파일을 남기고, 같은 항목을 다시 import하면 바이트 비교 후 채택합니다. 파일을 만든 뒤 트랜잭션 전에 프로세스가 죽어도 같은 바이트의 고아 파일이 남을 뿐이며 다음 import가 채택합니다. 같은 이름의 오래된 `.<name>.<random>.tmp`는 다음 쓰기가 정리합니다.

### 파일 저장소 규칙

- **루트 승인.** 루트는 절대·실경로이고 POSIX 디렉터리여야 하며 그룹·others 쓰기 권한이 없어야 합니다. 시작할 때 한 번, 그리고 매 실행에서 락을 잡기 전에 다시 확인하며, 첫 확인 때의 소유자와 달라지면 거부합니다. 이 저장소는 루트·권한을 고쳐 주지 않습니다.
- **같은 소유자와 정확한 모드.** 락 파일(`.document-import.lock`), 내용 디렉터리(`extracted_text` 등), 내용 파일과 임시 파일은 모두 루트의 소유자와 같아야 합니다. 락·내용 파일·임시 파일은 정확히 0600, 내용 디렉터리는 정확히 0700이어야 합니다. 이미 있는 항목이 다르면 chmod·chown 없이 `artifact_store_unavailable`로 거부하므로 운영자가 직접 고친 뒤 다시 실행합니다. 새로 만드는 항목은 0600·0700으로 만들며 소유자 비트를 지우는 umask(예: 0600이 0400이 되는 경우)는 이 정확한 모드 검사에 걸립니다.
- **고아 파일 채택.** 이전 실행이 파일을 만들고도 디렉터리 항목을 내구화하지 못한 채 죽었을 수 있으므로, 같은 바이트의 정상 고아 파일을 채택할 때는 데이터를 담은 파일, 내용 디렉터리, 루트 디렉터리를 모두 강제 fsync한 뒤에야 저장된 파일을 돌려줍니다. 새로 만든 파일도 반환 전에 같은 순서로 fsync합니다. fsync가 하나라도 실패하면 `artifact_store_unavailable`이고 저장된 파일을 돌려주지 않으며, 시험에서 주입한 fsync 실패로 이를 확인하고 기존 고아 파일이 바뀌지 않음도 확인합니다. 코드의 호출 순서상 파일 저장이 DB 트랜잭션보다 앞서므로 이 실패는 DB 트랜잭션 이전에 막힙니다(파일 실패와 DB를 함께 움직이는 시험은 없고 호출 순서에서 추론한 것입니다).
- **락과 읽기를 분석과 공유합니다.** 락 파일(`.document-import.lock`)은 [문서 분석](DOCUMENT_ANALYSIS.md)과 같은 하나라서 import와 분석은 같은 artifact root에서 동시에 실행되지 않으며 두 설정을 한 JVM에서 함께 켜면 기동이 거부됩니다. `Session.read(uri, sha256, bytes)`는 저장된 파일을 되읽을 때 정규 파일·같은 소유자·정확히 0600(디렉터리 0700)·등록된 크기·sha256을 모두 확인하고(없거나 다르면 `CONFLICT`, 안전하지 않으면 `UNAVAILABLE`) 한 번에 최대 16 MiB만 읽습니다. import 자체는 쓰기만 합니다.
- **보상 삭제.** 롤백 뒤 파일을 지울 때도 정규 파일·같은 소유자·0600·같은 크기와 해시를 다시 확인하고, 하나라도 다르면 건드리지 않습니다.
- **한계.** 실제 전원 손실은 지원하지 않으며 어떤 시험으로도 강제할 수 없습니다. 시험은 주입한 fsync 실패에서 저장된 파일을 돌려주지 않고 고아 파일을 보존하는지만 확인하며, 하드웨어와 파일시스템이 fsync를 지킨다는 것은 가정입니다. 파일과 DB 행은 한 트랜잭션이 아니므로 둘의 순서는 ‘파일을 먼저 만들고 DB를 커밋’하는 고정 순서와 고아 채택으로만 맞춥니다.

## 접근과 권리

- **쓰기:** 모든 쓰기(이미 있는 버전의 no-op 재실행과 포인터만 이동하는 경우 포함)는 같은 실행에서 그 선택자의 **새 export가 성공**해야 합니다. 철회된 grant로는 export가 거부되므로 어떤 쓰기도 일어나지 않습니다.
- **읽기(이 변경에는 없음):** 저장된 행과 `access_status='available'`은 읽기 권한이 아닙니다. 읽는 쪽은 `articles.provider`의 **현재** grant를 다시 확인하고 `available`을 요구해야 하며, `current_version IS NULL`을 “지정된 현재 버전 없음”으로 다루고 `MAX(collected_at)`이나 `published_at`으로 대체하면 안 됩니다(ERD v6).
- **철회 창:** export와 commit 사이에 grant가 철회될 수 있습니다. 트랜잭션 안에서 export를 다시 부르면 하위 프로세스를 잠금 안에서 기다리게 되므로 받아들인 한계이며, 읽기 시점의 grant 재확인이 독립적으로 필요합니다.
- **`store` 권리는 CLI가 확인합니다.** import는 항상 `--require-store`를 넘기므로 grant가 `read`·`quote-display`만 허용하면 `ingestion_export_failed`(`source_unauthorized`)이고 파일·행은 하나도 생기지 않습니다. 이 플래그를 모르는 이전 CLI는 구조화된 JSON 없이 실패하므로(`ingestion_export_unavailable`) 마찬가지로 거부됩니다.
- 범위(scope) 단위 철회는 앱 행에 round·scope가 없어 읽기 시점에 source 단위로만 확인할 수 있습니다.

## 하위 프로세스 규칙

고정 argv `[cli, export, --state-dir, …, --sources, …, --require-store]`, 선택자는 stdin의 UTF-8 JSON, cwd는 `java.io.tmpdir`. 환경은 비운 뒤 `PATH=/usr/bin:/bin`, `HOME`, `LANG=C.UTF-8`, Python UTF-8 설정과 위 `ZOOP_*_STATE_DIR` 둘만 넣습니다. stdout은 16 MiB, 120초 후 강제 종료, stderr는 버리고 기록하지 않습니다. `DB_*`는 전달되지 않습니다.

## 검증

```sh
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
./api/gradlew -p api --console=plain test assemble      # DB·Python·네트워크 없이 실행되는 단위·소비자 시험 + boot jar
```

실제 DB와 설치된 CLI를 쓰는 smoke는 **빈 전용 loopback DB**(합성 데이터, 정리하지 않음)가 필요합니다.

```sh
DB_URL=jdbc:postgresql://127.0.0.1:<port>/<db> DB_USERNAME=<user> DB_PASSWORD=<dummy> \
  ai/pipeline/.venv/bin/python api/scripts/document_import_smoke.py \
    --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --ingest-cli "$PWD/ai/pipeline/.venv/bin/zoop-ai-ingest" \
    --psql-container <container> --db-user <user> --db-name <db>
docker exec -i <container> psql -X -v ON_ERROR_STOP=1 -U <user> -d <db> < api/src/test/resources/sql/document-registry-verification.sql
```

smoke는 설치된 CLI로 합성 ledger(같은 문서의 4개 버전과 replay, 같은 바이트의 두 공급자·두 source)를 만들고, 빌드된 jar를 항목 단계마다 비웹 프로세스로 실행해 psql로 영속된 ID·행·해시·시각·파일 바이트를 CLI의 새 export와 비교합니다. 반복 실행, 새 버전, 오래된 버전 replay, 포인터 이동과 낡은 기대값, 롤백과 새 파일 정리, 고아 파일 채택, 기존 파일·artifact·version·provider·kind 충돌, private·deleted 거부, grant 철회·복원, 미리 만든 export 입력 거부, 파일시스템 실패, 작업 락, 웹 서버와의 동시 시작 거부와 평소 기동, ledger 불변을 확인합니다. 성공하면 마지막 줄이 `{"status": "passed", "steps": N, "providerCalls": 0, "modelCalls": 0, …}`입니다. SQL 증명은 `BEGIN … ROLLBACK`이라 데이터를 남기지 않습니다.

smoke는 grant에서 `read`·`store`·`quote-display` 중 **하나씩만** 뺀 세 경우에 이미 등록된 버전의 재실행·새 버전·포인터 이동이 모두 `source_unauthorized`로 거부되고 DB와 파일이 전혀 바뀌지 않는지도 확인합니다. DB 없는 JUnit 회귀(`DocumentImporterTest`)는 `read`·`quote-display`만 허용하는 파이프라인을 흉내 낸 CLI로 import가 항상 `--require-store`를 넘겨 아무것도 쓰지 못함을 확인합니다.

**업그레이드 확인:** 같은 smoke를 `--upgrade-from <버전>`(예: 팀의 최신 기업 migration `20261014102810`)과 함께 **빈 DB**에서 실행하면, 먼저 기존 `spring.flyway.target`(`SPRING_FLYWAY_TARGET`)로 그 버전까지만 적용해 문서 테이블이 아직 없음을 확인하고(이 제한 실행은 JPA 검증이 실패해도 무방하며 Flyway 기록만 봅니다), 이어서 전체 시나리오를 돌립니다. 마지막에 `V20261014120000`이 그 버전 뒤에 성공으로 적용돼 마지막 행인지 검사합니다. 로컬 문서 migration은 처음 `V20261014100000`으로 작성했으나 팀의 `V20261014102810`이 먼저 병합돼 `V20261014120000__create_document_registry.sql`로 이름을 바꿨습니다(공유·적용된 적 없는 파일이라 안전). 아래 ‘실행 결과’는 이름 변경 전 버전의 기록이며 변경 후 DB 적용·업그레이드는 새로 실행해야 합니다.

### 실행 결과 (2026-10-14, 로컬·미커밋)

- Java 시험 157개가 실패·skip 없이 통과했고 `assemble`이 성공했습니다. 설치된 `zoop-ai-ingest` 변경(`--require-store`)을 포함한 pipeline 시험 229개도 통과했습니다.
- 실제 Spring jar와 설치된 CLI, 임시 PostgreSQL **17.11** 컨테이너로 smoke를 실행해 16단계(JVM 36회)가 통과했습니다. 최종 행은 article 3·version 5·artifact 5였고 원본 S2-1 ledger는 실행 전후로 바뀌지 않았습니다(읽기 전용).
- `document-registry-verification.sql`(`BEGIN … ROLLBACK`)이 같은 DB에서 통과했습니다. 컨테이너는 정리했습니다.
- 합성 자료만 사용했고 실제 공급원·유료 모델 호출은 0입니다(`providerCalls`·`modelCalls` 0).

확인하지 않은 것: compose가 쓰는 PostgreSQL **16.13**에서의 실행, 원격 CI(이 기능의 DB smoke는 CI에 없음), 커밋·푸시·배포, 실제 전원 손실과 하드웨어·파일시스템의 fsync 준수(가정). 이 결과는 FS056의 **문서 쪽**만이며 분석 결과 import, `evidence`, 그래프, 공개 API를 포함하지 않습니다. 분석 결과 저장은 [문서 분석](DOCUMENT_ANALYSIS.md)이 맡고, 공개 관리자 작업 `analysis_jobs`의 소유 담당·migration은 아직 정해지지 않았습니다.

## 남은 결정과 한계

- 이 migration(`V20261014120000`)과 `artifacts`·`articles`·`article_versions`의 소유는 **로컬 제안**이며 담당 합의 전까지 확정이 아닙니다(소유 담당은 [migration 담당 경계](../../docs/development/api-migration-ownership.md)에서 확정). 다른 브랜치의 migration과 버전이 겹치면 병합 전에 이 파일의 이름만 바꿉니다. 첫 작성자는 이 경로이며 다른 기능은 `artifacts`를 다시 정의하지 말고 참조합니다.
- 문서를 읽는 기능(`listCompanyDocuments`, `getEvidence` 등)은 저장 행을 권한으로 쓰면 안 됩니다. 응답 때마다 `articles.provider`의 **현재** grant와 `access_status='available'`을 다시 확인해야 하고, `current_version IS NULL`을 “현재 버전 없음”으로 다루며 시각으로 대체하면 안 됩니다.
- `articles.provider_key`·`lineage_key`·`publisher`·`raw_artifact_id`와 `day` 정밀도는 S2-1이 값을 내보낼 때까지 비어 있습니다.
- `collected_at`·`url`은 가장 이른 관찰이 아니라 **처음 등록된** 관찰의 값입니다(행이 불변이라서).
- 파일 저장소는 로컬 파일시스템 한 곳입니다. 보존·삭제 정책(ERD가 정하지 않음)과 원격 저장소는 없습니다.
- 읽기 API, 분석·근거·공개 반영은 이 변경의 범위 밖입니다.
