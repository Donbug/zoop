# 문서 bindings export (앱 → AI handoff freeze)

#55(WBS 6.5.4) 그래프 정기 회차 자동화의 앱 쪽 조각입니다. AI `zoop-ai-handoff freeze`가 요구하는 운영자 파일 셋 중 **앱이 만들어야 하는** `zoop-app-document-bindings-1`(`--bindings`)을 앱 DB에서 생성합니다. 운영자가 실행하는 **비웹 Spring 프로세스**이며 HTTP 경로가 없고, DB를 읽기만 합니다.

**하는 것:** 등록된 모든 기사 버전(`article_versions`)에 대해 "이 S2-1 문서 버전은 이 앱 기사 버전이고, 저장된 UTF-8 본문의 SHA-256은 이 값이며, 인용 위치는 code point다"를 적은 파일 하나와 결과 파일 하나를 만듭니다.

**하지 않는 것:** AI Task로의 전달(파일 복사·HTTP·공유 저장소는 Infra·AI와 별도 결정), 회차 스케줄러와의 연결, canonical·decisions 파일 생성(둘 다 AI·운영자 소유), 권리 판정(아래 [범위](#범위)), DB 쓰기.

## 왜 앱이 만드는가

freeze는 S3 결과의 문서 `(documentId, documentVersion)`을 bindings로 앱 `(articleId, articleVersion)`에 묶고, binding의 `textSha256`이 S2-1 export 본문의 `sha256(text.encode("utf-8"))`과 다르면 그 문서를 `app_binding_text_mismatch`로, binding이 없으면 `app_binding_missing`으로 뺍니다(`ai/pipeline/src/zoop_ai_pipeline/handoff.py`). 그래프 수입기는 반대 방향으로 bundle의 `article.textSha256`을 앱 text artifact의 `sha256`과 대조합니다(`GraphHandoffImporter`). 두 값은 같은 앱 행이므로, 이 파일은 앱만 정확히 만들 수 있습니다.

[문서 import](DOCUMENT_IMPORT.md)가 등록하는 값이 그대로 binding입니다.

| binding 필드 | 앱 값 |
|---|---|
| `documentId` · `articleId` | `articles.id` (= S2-1 `documentId`, `doc-` + sha256) |
| `documentVersion` · `articleVersion` | `article_versions.version` (= S2-1 `documentVersion`) |
| `textSha256` | `artifacts.sha256` of `article_versions.text_artifact_id` (`text-<documentVersion>`, `kind = extracted_text`): 저장된 UTF-8 본문의 SHA-256 |
| `offsetUnit` | 항상 `unicode_code_point` |

## 실행

기본은 비활성이고 평소 기동에는 아무 설정도 필요하지 않습니다. 활성화하면 모든 값을 시작 시 검증하고 하나라도 틀리면 기동이 닫힘 실패합니다(메시지에는 설정 이름만 있고 값은 없음).

| 환경 변수 | 용도 |
|---|---|
| `ZOOP_DOCUMENT_BINDINGS_ENABLED` | `true`일 때만 동작(기본 `false`). **웹 서버와 함께는 시작을 거부**하므로 `--spring.main.web-application-type=none`이 필수 |
| `ZOOP_DOCUMENT_BINDINGS_OUTPUT` | 만들 bindings 파일. **없어야 하며** export가 끝난 뒤 같은 디렉터리의 임시 파일(`<이름>.<난수>.tmp`, 0600)에 통째로 쓰고 디스크에 내린 뒤 이 이름으로 하드 링크해 게시합니다(이름이 이미 있으면 실패, 기존 파일은 바꾸지 않음) |
| `ZOOP_DOCUMENT_BINDINGS_RESULT` | 결과 파일. **없어야 하며** 실행 시작 시 배타적으로 만들어집니다(0600). output과 달라야 합니다 |
| `ZOOP_DOCUMENT_BINDINGS_SCOPE` | `available`(기본) 또는 `all`. 아래 [범위](#범위) |
| `ZOOP_DOCUMENT_BINDINGS_SELECTION` | 선택. 묶을 문서 버전을 명시한 파일(존재하는 파일, 최대 4,000,000바이트). 아래 [선택 파일](#선택-파일-zoop-document-bindings-selection-1) |
| `DB_URL` `DB_USERNAME` `DB_PASSWORD` | 기존 DB 연결 |
| `ZOOP_AUTH_CSRF_ACTIVE_KEY_ID` `ZOOP_AUTH_CSRF_KEYS` | 기존 인증 설정. 비웹 기동도 CSRF key ring을 검증하므로 없으면 `Invalid CSRF key configuration`으로 기동 실패. 값·형식은 [api/README.md](../README.md)의 환경 변수 표 |

모든 경로는 정규화된 절대 경로여야 하며, output과 result는 디렉터리의 symlink를 풀어도 서로 다른 파일이어야 합니다. 다른 운영자 명령(문서 import·분석, 그래프 수입, 공개 제외, 브리핑 replay)과 같은 프로세스에서 켜면 기동을 거절합니다. runner의 실행 순서가 정해져 있지 않고 먼저 실패한 runner가 JVM을 끝내므로, 종료 코드와 결과 파일이 이 실행의 것이려면 프로세스당 명령 하나여야 합니다. DB는 읽기만 하고 artifact store lock도 잡지 않습니다.

```sh
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
./api/gradlew -p api assemble
env -i PATH=/usr/bin:/bin HOME="$HOME" \
  DB_URL=… DB_USERNAME=… DB_PASSWORD=… \
  ZOOP_AUTH_CSRF_ACTIVE_KEY_ID=… ZOOP_AUTH_CSRF_KEYS=… \
  ZOOP_DOCUMENT_BINDINGS_ENABLED=true \
  ZOOP_DOCUMENT_BINDINGS_OUTPUT=/abs/round/bindings.json ZOOP_DOCUMENT_BINDINGS_RESULT=/abs/round/bindings-result.json \
  "$JAVA_HOME/bin/java" -jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --spring.main.web-application-type=none
```

종료 코드는 export가 성공했을 때만 0입니다. 실패하면 결과 파일을 쓴 뒤 코드만 담은 예외로 끝나 JVM이 0이 아닌 값으로 종료하며, **output 파일은 남기지 않습니다.** output은 bindings가 모두 만들어진 뒤 같은 디렉터리의 0600 임시 파일에 통째로 쓰고 디스크에 내린(force) 다음 하드 링크(`Files.createLink`)로 배타 게시하므로, 읽는 쪽은 빈 파일이나 일부만 쓰인 파일을 보지 않습니다. 링크는 그 이름이 이미 있으면 파일시스템이 원자적으로 거절하므로, 같은 output을 겨냥한 두 실행이 동시에 돌아도 한쪽만 성공하고 먼저 게시된 파일은 바뀌지 않습니다(`output_unavailable`). artifact store와 같은 방식이며, output 디렉터리의 파일시스템은 하드 링크를 지원해야 합니다. 쓰는 도중 실패하면 임시 파일을 지우고, output을 게시한 뒤 결과 파일을 쓰지 못하면(`result_unavailable`) 이 실행이 게시한 output을 지웁니다. 그래서 **output이 있으면 완전한 파일이고 결과 파일에 보고된 것이며, 종료 코드가 0이 아니면 output이 없습니다**(정리까지 실패한 경우만 예외이고 로그에 남습니다). 결과 파일이 비어 있으면 프로세스가 도중에 죽은 것이므로 새 경로로 다시 실행하고, output 옆에 남은 `<이름>.<난수>.tmp`는 지워도 됩니다. DB를 쓰지 않으므로 재실행은 언제나 안전합니다.

## 범위

binding은 **신원 매핑이지 권리가 아닙니다.** 이 파일을 읽는 쪽(AI freeze의 `--sources` 현재 권리 검사, 앱 수입의 `require-store` 재확인)이 권리를 다시 판정하므로 어떤 범위든 권리를 넓히지 않습니다.

- `available`(기본): `articles.access_status = 'available'`인 기사의 모든 버전. 철회된(`private`·`deleted`) 기사의 버전은 빼고 결과 파일 `excluded`에 상태별 건수를 적습니다. AI 런타임에 볼 이유가 없는 버전을 넘기지 않기 위한 기본값입니다. 범위는 SQL에서 걸러 묶을 행만 읽고, 제외 건수는 별도 집계문으로 세므로 문서 import가 동시에 돌면 두 수가 같은 순간을 보지 않을 수 있습니다(정보용 수치이며 파일 내용에는 영향이 없습니다).
- `all`: 모든 기사의 모든 버전.

선택 파일이 있으면 그 목록만 대상이고 범위는 그 위에 그대로 적용됩니다. 선택한 버전이 등록돼 있지 않으면 일부만 묶지 않고 전체를 `selection_unregistered`로 거절합니다.

## 출력 (`zoop-app-document-bindings-1`)

AI 계약(`handoff_contracts.py`의 `Bindings`·`Binding`) 그대로입니다. 키 집합은 정확히 아래와 같고 추가 키는 AI가 거절합니다.

```json
{"schemaVersion":"zoop-app-document-bindings-1",
 "bindings":[{"documentId":"doc-<64hex>","documentVersion":"<64hex>","articleId":"doc-<64hex>","articleVersion":"<64hex>",
              "textSha256":"<64hex>","offsetUnit":"unicode_code_point"}]}
```

- **결정적 바이트.** 앱의 canonical JSON(정렬된 키, 공백 없음, `Canonical.bytes`)으로 `(articleId, articleVersion)` 오름차순입니다. 같은 DB 상태면 같은 바이트, 같은 sha256입니다. freeze manifest는 파일 전체 sha256을 고정하므로(`files.bindings`), **freeze 뒤에 파일을 바꾸면 그 묶음의 export는 `bindings_changed`로 withheld**됩니다. 회차마다 새 파일을 만들고 freeze에 쓴 파일은 그대로 둡니다.
- **상한.** AI 계약의 항목 20,000건(`MAX_DECISIONS`)·파일 4,000,000바이트(`MAX_OPERATOR_FILE`)를 넘으면 `bindings_limit`로 거절합니다. binding 하나가 canonical JSON으로 약 452바이트라 **실제로는 바이트 상한이 먼저 걸리며 약 8,800건**이 한 파일의 한계입니다. 넘을 때는 선택 파일로 범위를 좁힙니다.
- **닫힘 검사.** 묶는 행마다 `articles.id`가 `doc-<64hex>`, 버전·해시가 `<64hex>`, `text_artifact_id`가 `text-` + 버전인지(`identity_invalid`), text artifact의 `kind`가 `extracted_text`인지(`artifact_kind_invalid`) 확인하고 하나라도 어긋나면 파일을 만들지 않습니다. 범위 밖이라 묶지 않는 행은 검사하지 않습니다.

## 결과 (`zoop-document-bindings-result-1`)

```json
{"schemaVersion":"zoop-document-bindings-result-1","status":"succeeded","scope":"available","selection":false,
 "count":3,"bytes":812,"sha256":"<64hex>","excluded":{"private":1}}
```

실패하면 `status: "failed"`와 `failure.code`만 있고 `count`·`bytes`·`sha256`·`excluded`는 없습니다. `sha256`은 manifest의 `files.bindings` 핀과 대조하는 값입니다. 경로·본문·비밀값은 결과·로그·예외에 없습니다.

| 코드 | 뜻 |
|---|---|
| `selection_invalid` | 선택 파일을 읽을 수 없거나 형식·상한·중복 규칙에 어긋남 |
| `selection_unregistered` | 선택한 문서 버전 중 등록되지 않은 것이 있음 |
| `result_unavailable` | 결과 파일을 배타적으로 만들거나 쓸 수 없음(이미 있음 포함). 아무 일도 하지 않음 |
| `output_unavailable` | bindings 파일을 배타적으로 만들거나 쓸 수 없음(이미 있음 포함). 기존 파일은 건드리지 않음 |
| `bindings_limit` | 항목 20,000건 또는 4,000,000바이트 초과 |
| `identity_invalid` | 묶을 행이 문서 import의 신원 규칙(`doc-` id, 64hex 버전·해시, `text-<버전>` artifact)에 어긋남 |
| `artifact_kind_invalid` | 묶을 행의 text artifact가 `extracted_text`가 아님 |
| `database_unavailable` | 조회 실패 |
| `internal_error` | 그 밖의 예외. 메시지는 남기지 않음 |

## 선택 파일 (`zoop-document-bindings-selection-1`)

```json
{"schemaVersion":"zoop-document-bindings-selection-1",
 "versions":[{"documentId":"doc-<64hex>","documentVersion":"<64hex>"}]}
```

1~20,000건, 같은 버전 두 번 금지, 키 집합 정확히 일치, 엄격한 UTF-8. 출력 순서는 파일 순서가 아니라 언제나 정렬 순서입니다.

## 검증

- `DocumentBindingsExporterTest`(투영·정렬·결정성·범위·선택·중복 선택·두 상한·신원·artifact kind·DB 실패), `BindingSelectionParserTest`, `DocumentBindingsSettingsTest`(symlink를 푼 같은 파일 거절 포함), `DocumentBindingsConfigurationTest`(기본 꺼짐·웹 거절·다른 운영자 명령과 동시 활성화 거절·설정 이름만 노출), `DocumentBindingsRunnerTest`(배타 생성·실패 시 output 없음·코드만 담은 종료). runner 시험과 symlink 시험은 POSIX 파일 시스템이 필요해 그 밖에서는 건너뜀으로 보고됩니다(CI와 Linux 컨테이너에서는 실행).
- `DocumentBindingsPostgresIntegrationTest`(`graph-postgres`, `./gradlew companyIntegrationTest`): 실제 migration·SQL 위에서 문서 import가 등록하는 그대로의 행을 묶고 해시가 저장 본문의 SHA-256과 같은지 확인합니다. DB 준비는 [기업 검색 검증](COMPANY_SEARCH_TESTING.md#postgresql-통합-테스트)과 같습니다.
- Java 시험은 `handoff_contracts.py`의 `Binding`·`Bindings` 규칙(키 집합·모양·유일성·상한)을 옮겨 적은 상수로 확인합니다. AI 쪽 계약이 바뀌어도 그 상수는 그대로이므로, 교차 검증 `api/scripts/document_bindings_gate.py`가 만들어진 파일을 **설치된 `ai/pipeline`의 실제 `Bindings` 모델**로 읽어 어긋남을 먼저 드러냅니다. 정렬 순서, 문서·기사 신원 일치, 결과 파일의 `count`·`bytes`·`sha256`도 대조합니다(`make pipeline-install` 뒤 `ai/pipeline/.venv/bin/python api/scripts/document_bindings_gate.py /abs/bindings.json --result /abs/bindings-result.json`, 종료 0이면 통과). 네트워크·DB·모델 호출은 없습니다.

## 남은 것 (이 명령 밖)

- AI Task로 파일을 전달하는 경로(AI 회신 6번). `ai/service`는 고정 경로 `ZOOP_AI_SERVICE_HANDOFF_BINDINGS`를 읽으므로 그 경로에 두는 방식·주체를 Infra·AI와 정합니다.
- 회차 스케줄러가 `DocumentBindingsExporter`를 직접 호출해 전달하는 연결.
