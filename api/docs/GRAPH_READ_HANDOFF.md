# 그래프 읽기 인수 문서 (정세빈 · 앱 상태·공개 조회용)

Spring 백엔드에서 내부 AI 서비스의 그래프 조회 API 두 개를 연결할 때 참고하는 문서입니다. 요청·응답, 오류 처리, 현재 구현 범위와 백엔드 연결 시 확인할 사항을 정리했습니다. 기계 판독 계약은 [`internal-ai-openapi.json`](../../docs/api/internal-ai-openapi.json)의 `graph-versions` 태그이며, 서버 설정은 [AI 서비스 README](../../ai/service/README.md#그래프-버전-읽기-internalv1graph-versions)를 참고하세요.

## 지금 상태 (사실)


> **구현과 공개 운영을 구분합니다.** 비활성 스냅샷 수입은 PR #229로 병합됐습니다. 본 문서의 추가 구현은 bundle-2 원본 언급 인계와 현재 권한을 검사하는 graph 근거 읽기입니다. 근거 읽기의 계약·운영 조건은 [문서 끝의 해당 절](#2026-10-20-getevidence의-graph-본문-근거-경로-로컬-작업-트리-미게시)을 따르며, 공개 활성화·전체 철회·AWS 배포 완료를 뜻하지 않습니다.
- **이 AI 서비스는 비공개·미게시·미활성입니다.** 내부 서비스(`127.0.0.1`, 앞단 TLS 프록시는 미배포)의 읽기 전용 API이며 활성 버전 포인터도 없습니다. 응답의 `publication`은 항상 `not-published`입니다. `delivery.state=current`는 “이번 요청에서 검증됨”이지 “앱이 보여 주는 활성 버전”이 아닙니다. 게시·활성화(FS059)·전체 철회(FS081)는 이 서비스에 포함되지 않았습니다.
- **Spring 구현 기준.** 공개 `GET /api/v1/graph`, 기업·관계·시점 조회, `graph_versions`·`graph_activations`, 버전 선택기와 `PublicGraphReader`가 있습니다. 스냅샷 source는 기본 `none`, local/dev용 `fixture`, 수입된 불변 파일을 검증해 읽는 `artifact`로 구분합니다. Spring은 Neo4j에 직접 접속하지 않고 Neo4j 자격을 받지 않습니다. 공개 활성화·관리 route와 전체 공개 제외 저장소는 별도 후속 범위입니다.
- **운영자 스테이징 수입.** `com.zoop.graph.importer`는 설치된 handoff·ingestion CLI의 현재 결과와 앱 DB·본문을 대조해 근거 및 비활성 버전을 등록하며, 활성 포인터를 변경하지 않습니다. 스냅샷 형식 3은 읽기용 투영이고 원본 manifest·bundle 전체는 영수증에 보존됩니다. 앱 mention ID는 문서·버전·원천 ID로 결정해 문서 간 같은 로컬 ID를 구분합니다. bundle-2의 원래 언급 값은 `verification: none`이며, `quote_verified`도 인용 무결성이지 의미 검증·공개 승인 자체가 아닙니다. [API 실행 안내](../README.md#그래프-handoff-스테이징-import)의 명령과 설정을 사용하세요.
- 운영자가 AI 버전을 만들고 서버 allowlist에 올립니다. 이 AI 읽기 서비스는 버전을 **만들거나 찾거나 나열하지 못합니다**(목록 라우트 없음). 앱의 operator 스테이징 명령은 전달받은 handoff를 별도의 비활성 앱 버전으로 등록합니다.
- 실제 로컬 HTTP 서버 → 설치된 graph CLI → 격리된 Neo4j 5.26 경로의 smoke를 통과했습니다(2026-10-15 로컬 실행 기록이며 현재 `main`의 재검증이 아닙니다). 1~3홉·권한 분리·digest 불일치·원천 권한 철회·canonical 변경·그래프 변조·원장 잠금·시간 초과를 확인했습니다. 원천 원장 변경과 모델 호출은 없었습니다. 이 서비스 구현은 이후 PR #213에서 `main`에 병합됐지만, 배포·실제 데이터 운영은 하지 않았습니다.

## 호출

헤더 `Authorization: Bearer <토큰>`(운영자 발급, principal에 scope `graph.read` 필요). 선택 `X-Request-ID`(`^[A-Za-z0-9._-]{1,128}$`, 응답에 그대로 반환). 모든 응답은 `Cache-Control: no-store`.

| 요청 | 의미 |
|---|---|
| `GET /internal/v1/graph-versions/{versionId}` | 한 버전의 검증된, 내용 없는 상태 |
| `GET /internal/v1/graph-versions/{versionId}/focus?companyId=&depth=` | 한 회사의 이웃(깊이 1~3) |

- `versionId`: `^[A-Za-z0-9._:-]{1,120}$`. **운영자 allowlist에 principal별로 올라 있는 버전만** 읽힙니다.
- 쿼리는 **정확히** `companyId`(`^[A-Za-z0-9._:-]{1,200}$`)와 `depth`(정확히 `1`·`2`·`3`) 하나씩. 모르는 키·중복·`01`·`4`·빈 값·status 라우트의 쿼리는 422 `invalid_request`(`error.field`에 이름).
- `companyId`는 운영자가 확정한 회사 ID입니다. 본개발에서는 합의된 대로 `companies.id`와 일치시켜야 합니다. 합성 시험의 `kr-000100` 등은 예시일 뿐이며, S2/S3 후보 ID를 그대로 넣지 않습니다. 운영자 canonical 결정 registry가 후보 ID를 회사 ID에 연결합니다.

## 응답 `GraphVersionStatus` (status)

```json
{"schemaVersion":"zoop-ai-internal-graph-1","versionId":"…","state":"ready","publication":"not-published",
 "delivery":{"state":"current","reason":null},
 "verification":{"graphDigest":"<64hex>","payloadDigest":"<64hex>","nodes":6,"edges":6},"observedAt":"2026-10-15T00:00:00Z"}
```

| 필드 | 의미 |
|---|---|
| `state` | 운영자 원장의 버전 상태 `frozen\|reserved\|unknown\|ready\|failed` (`ready`만 읽기 대상) |
| `delivery.state` | `current`(지금 검증됨) 또는 `withheld` |
| `delivery.reason` | withheld일 때 사유 코드(아래), current면 `null` |
| `verification` | **current일 때만.** 저장된 그래프 전체가 동결된 digest와 일치함을 이 요청에서 확인한 결과: `graphDigest`·`payloadDigest`(allowlist와 같은 값)·`nodes`·`edges`(그래프의 노드·간선 수) |
| `observedAt` | 서버 시각(UTC, 초) |

status는 노드·간선·증거를 담지 않습니다. **Issue 수는 없습니다**: 이 그래프는 S3 관계(company/event/topic 노드, 관계 간선)이며 공개 `Neo4jStatus`의 `issuesInLedger·issuesProjected·missingIssueIds·staleIssueIds`와 다른 모델입니다(아래 "하지 말 것").

## 응답 `GraphFocusResult` (focus)

공통 필드는 status와 같고 추가로:

| 필드 | current | withheld |
|---|---|---|
| `focus` | `{companyId, depth, found}` (`found=false`면 검증된 버전에 그 회사가 없음; 오류 아님, `graph.nodes/edges`·`evidence`는 빈 배열) | `{companyId, depth, found:null}` (요청 에코) |
| `verification` | 위와 동일 | `null` |
| `graph.nodes[]` | `{kind: company\|event\|topic, id, distance}` — 시작 회사 0, 무방향 BFS 거리 | `null` |
| `graph.edges[]` | 아래 | `null` |
| `evidence[]` | 보이는 간선이 참조하는 근거 좌표만 | `null` |

간선(`graph.edges[]`): `relationId`(`rel-…`)·`type`(`SUPPLIES\|INVESTS_IN\|COMPETES_WITH\|PARTICIPATES_IN\|RELATES_TO_TOPIC`, 어휘는 pipeline이 정하며 늘 수 있음)·`direction`(`directed\|symmetric`)·`connection`(`direct\|indirect`)·`subject{kind,id}`·`object{kind,id}`·`businessScope`·`productScope`(문자열|null)·`validity{from,until}`(날짜 문자열|null)·`countries[]`·`path{companyIds[]}`(`indirect`일 때 3사 경로)·`evidence{relation[],validity[],steps[[],[]]}`(근거 id)·`sourceRelationCandidateIds[]`(S3 후보 id).
근거(`evidence[]`): `evidenceId`·`documentId`·`documentVersion`·`rawVersion`·`start`·`end`(문서 span 좌표). **인용문·제목·URL·모델 근거·검수 메모는 그래프에도 응답에도 없습니다.**

깊이 의미: 시작 회사에서 무방향 BFS, 간선은 한 끝점이 `depth-1` 이내일 때 표시(깊이 1은 회사 자신의 간선). 깊이 3은 S3 경로 길이와 무관한 읽기 한계입니다.

## withheld 사유 (200, 내용 없음)

`delivery.state=withheld`는 **오류가 아니며 빈 그래프도 아닙니다.** 앱은 이를 "지금 표시 불가"로 처리해야 합니다.

| `delivery.reason` | 뜻 |
|---|---|
| `source_unauthorized` 등 S3/S2 권한 코드 | source grant/권리·S2 export 철회·변경 |
| `canonical_mapping_changed` | 운영자 canonical 결정이 달라지거나 빠짐 |
| `review_revision_changed` | 투영된 관계의 S3 검수 상태가 동결 시점과 다름 |
| `upstream_changed`·`relation_input_mismatch`·`relation_not_ready` | S3/S2 원천이 동결된 것과 다름 |
| `graph_version_corrupt` | Neo4j에 저장된 그래프가 동결 digest와 다름(추가·삭제·변조) |
| `graph_store_identity_mismatch`·`graph_store_foreign_data`·`graph_store_schema_mismatch` | Neo4j 데이터베이스가 묶인 store가 아님 |
| `version_not_ready` | 상태가 `ready`가 아님(`state`가 `frozen`·`reserved`·`unknown`·`failed`) |
| `version_pin_mismatch` | pipeline이 보고한 digest가 allowlist의 `graphDigest`/`payloadDigest`와 다름 |
| `source_pin_mismatch` | 동결된 S3 relation job이 allowlist의 `sourceRelation`과 다름 |

사유 문자열은 짧은 기계 코드이거나 `redacted`입니다. 새 코드가 생길 수 있으니 모르는 값은 "withheld(원인 불명)"로 처리하세요.

## HTTP 오류 (`{schemaVersion, error:{code, retryable, requestId, runtimeCode, field}}`, 메시지·경로·URI·stderr 없음)

| 상태 | `error.code` | 재시도 | 뜻과 조치 |
|---|---|---|---|
| 401 | `authentication_required` | 아니오 | 토큰 없음·형식 오류·모름 |
| 403 | `scope_denied` | 아니오 | principal에 `graph.read` 없음 |
| 403 | `version_not_allowed` | 아니오 | allowlist에 없음. **버전이 존재하든 없든 같은 응답**. 요청 중 항목이 빠지거나 바뀌어도 같은 403(아무 내용도 안 나감) |
| 404 | `version_not_found` | 아니오 | 운영자가 allowlist에 올렸지만 그래프 원장에 없음(운영 설정 누락). `route_not_found`도 404 |
| 409 | `execution_unavailable` | 아니오 | 서비스의 graph 설정 그룹이 꺼져 있음 |
| 422 | `invalid_request` | 아니오 | 경로·쿼리·헤더 검증(`field`에 이름) |
| 500 | `runtime_binding_mismatch`·`internal_error` | 아니오 | 응답이 요청에 묶이지 않음·예기치 않은 pipeline 코드(`runtimeCode`) — 에스컬레이션 |
| 503 | `runtime_busy` | **예** | 운영자 writer가 원장을 쥠(`runtimeCode` `graph_busy`·`relation_busy`·`extraction_busy`·`ingestion_busy`). `Retry-After`. **빈 그래프로 답하지 않음** |
| 503 | `runtime_unavailable` | **예** | Neo4j 무응답·child 비정상 종료·deadline(45초)·읽을 수 없는 출력 |
| 503 | `service_configuration_invalid` | 예(운영 조치 필요) | 서버 설정·상태 결함(자격 증명·store 미결속·원장 손상·allowlist 읽기 불가) |
| 503 | `service_busy` | **예** | 동시 child 4개 초과 |

503은 모두 `Retry-After`가 있습니다. 5xx를 "그래프에 데이터가 없음"으로 해석하면 안 됩니다.

## 백엔드 연결 시 확인할 사항

1. **인증·권한**: 전용 principal(예: `app-graph`)과 토큰, scope는 `graph.read`만. 토큰은 운영자가 발급하고 서비스는 SHA-256 digest만 보관합니다. 토큰·URL을 로그에 남기지 마세요.
2. **버전 ID와 활성화 구분**: 운영자가 전달한 버전 ID를 사용합니다. 어느 버전을 공개할지는 앱의 별도 활성화 절차가 결정하며, 이 서비스에는 활성 포인터가 없습니다. 활성화 UI·FS059는 후속 연동 범위입니다.
3. **withheld·503을 데이터로 캐시·표시하지 않기**: `current`도 "그 순간 검증됨"일 뿐입니다. 확인과 응답 사이의 철회(TOCTOU)는 보이지 않고, 이미 받은 내용은 서비스가 회수하지 못합니다. 앱이 보관(캐시·DB 복제)한다면 **앱의 권한 재확인·철회 절차**가 필요합니다. 철회(FS081)는 이 서비스의 기능이 아닙니다.
4. **공개 상태 모델 매핑은 미정**(아래). 임의로 `GraphDbStatus`/`Neo4jStatus`/`GraphDbVersionState` 값을 만들어 채우지 마세요.
5. **동시성·재시도**: 동시 호출은 4 이하로 제한하세요. 503에는 `Retry-After`와 `retryable`이 있으나, 이 서비스 자체는 자동 재시도하지 않습니다. 백엔드에서 재시도를 도입한다면 횟수·총 대기시간 상한을 정하고, 설정 오류는 운영 조치와 구분해야 합니다. 요청마다 child 프로세스가 Neo4j 전체 그래프를 검증하므로 **조회 비용은 버전 크기에 비례**합니다. 합성 6노드 시험의 CLI focus p50은 약 280ms였으며, HTTP 경로와 실제 데이터 규모의 성능은 별도 측정 대상입니다.
6. **계약 소비**: 응답 모델은 `extra` 금지(`additionalProperties:false`)이지만 서비스는 pipeline이 새 키를 더해도 그것을 전달하지 않습니다. 새 필드는 이 문서·OpenAPI 갱신으로만 늘어납니다. 알 수 없는 enum 값(`type`·`reason`)은 실패시키지 말고 보존·무시하세요.

## 하지 말 것 / 아직 없는 것 (공개 상태 매핑)

- 공개 `GraphDbStatus`(`neo4j`, `lastCompletedAt`, `checkedAt`), `Neo4jStatus`(`reachable\|unreachable`, `issuesInLedger`, `issuesProjected`, `missingIssueIds`, `staleIssueIds`, `error`), `GraphDbVersionState`(`reflected\|pending\|unknown`)에 **대응하는 생산자가 없습니다.** 현재 투영은 S3 관계 그래프이고 Neo4j 상태 모델은 Issue 기준이라 **서로 다른 모델**입니다. 이 서비스의 `state`/`delivery`를 `reflected` 등으로 대응시킬지는 윤서진(그래프 writer·canonical 스키마)과 정세빈이 정할 사항이며 이 slice는 결정하지 않았고, **Issue 수는 추정하지 않습니다.** `reachable`을 흉내 내려면 별도의 상태 명령이 pipeline에 필요합니다(요청 사항).
- 앱 활성 포인터를 바꾸는 관리 route(`/api/v1/admin/graph/versions/{id}/activate`)와 이 AI 서비스 기반 공개 그래프 질의는 이 서비스가 제공하지 않습니다. 공개 `/api/v1/graph`와 `CompanyIssueCountQuery` 구현은 Spring 쪽에 있으며(위 "Spring 쪽 현재 상태") 이 서비스의 응답에 의존하지 않습니다.
- 목록·검색·임의 Cypher·버전 생성·`recover`·삭제는 없습니다.

## 역할 (사용자 확정)

- 안재현: Neo4j 인프라·**읽기 전용 role**(현재 서비스의 child는 `none` 또는 `basic` 자격으로 읽기만 하지만 전용 reader role·비밀 경로·비루프백 TLS(`bolt+s`)는 안재현이 정해야 합니다. 루프백 `none`은 개발용).
- 윤서진: 스키마·writer·recovery(`init`/`freeze`/`project`/`recover`, canonical 결정 registry, 회사 id 질의 조율). 이 slice는 pipeline을 바꾸지 않았습니다.
- 정세빈: 공개 읽기·상태(위 의무, Java 클라이언트, 공개 상태 매핑).

## 운영자가 서버에 넣는 것 (참고)

`ZOOP_AI_SERVICE_GRAPH_VERSIONS`는 다음 구조의 서버 소유 파일입니다. digest는 운영자가 `zoop-ai-graph read`로 확인한 `digests.graph`·`digests.payload`를 사용합니다. 아래 값은 구조를 설명하기 위한 예시이며 실제 버전과 digest로 바꿔야 합니다.

```json
{
  "schemaVersion": "zoop-ai-graph-versions-1",
  "versions": [
    {
      "principal": "app-graph",
      "versionId": "operator-supplied-version",
      "graphDigest": "<64자리 SHA-256>",
      "payloadDigest": "<64자리 SHA-256>"
    }
  ]
}
```

필요하면 각 항목에 `sourceRelation: {"jobId": "...", "inputDigest": "<64자리 SHA-256>"}`를 추가해 원천 작업도 고정할 수 있습니다. 요청 시작·실행 직전·결과 수신 시 허용 목록을 다시 읽습니다. 항목이 제거되거나 바뀌면 403으로 거절합니다. 최종 확인 이후 응답 전달 사이에 발생하는 변경까지 원자적으로 막지는 못합니다.

## 재현 명령과 검증 범위

`make service-test`, `make service-pipeline-test`, `make service-openapi-check`로 서비스 계약과 설치된 CLI 연동을 검사합니다. 실제 Neo4j 검증은 **다른 데이터가 없는 격리된 시험 DB**에 대해 다음 명령으로 실행합니다.

```sh
ZOOP_GRAPH_SMOKE_URI=bolt://127.0.0.1:<시험포트> \
ZOOP_GRAPH_AUTH=none make service-graph-smoke
```

2026-10-15 Main 실행: 실제 HTTP smoke의 9개 점검 묶음이 통과했습니다. 처음에는 smoke가 요청한 `companyId`의 정상 에코를 내용 유출로 오판했습니다. 응답의 허용 필드·정확한 에코·내용 null을 각각 검사하도록 시험을 수정한 뒤 같은 시나리오가 통과했습니다. 서비스 동작을 느슨하게 바꾸지 않았습니다. 운영 인증·TLS·실제 규모의 부하·Spring 공개 API는 이 시험으로 검증되지 않았습니다.

## 개발 환경 Neo4j 운영자 실행 (Infra 질문 5개 답변 · 제안 · 코드는 PR #213으로 main 병합 · 인프라는 미배포)

이 절의 이름·경로·명령은 **제안**입니다. `neo4j.dev.zoop.internal`은 지금 존재하는 DNS 레코드가 아니며, AWS 배포·IAM·SSM 승인은 보류입니다. 아래 `preflight`와 TLS smoke는 로컬 Community 5.26 TLS + 기본 인증 증명이지 AWS·Fargate·RBAC·`GraphDbStatus` 준비 증명이 아닙니다(사실 근거: `ai/pipeline`의 `graph_projection*.py`, `graph_neo4j.py`, `scripts/graph_tls_smoke.py`).

1. **누가 쓰는가.** 개발 단계에서는 **사람 운영자가 영구 로컬 POSIX 디스크의 작업 디렉터리에서** `zoop-ai-graph init/freeze/project/recover`를 직접 실행합니다. AI ECS 서비스·BFF·Spring·Fargate가 아닙니다. 원장(SQLite+WAL+`flock`)은 한 호스트의 로컬 파일시스템이 필요해 EFS 공유나 임시 Fargate 저장소에 둘 수 없습니다. 이 단계에서 `graph.read` HTTP는 꺼 둡니다(`GRAPH_SWITCH` 변수를 하나도 설정하지 않음). handoff HTTP는 Neo4j 자격은 필요 없지만 S2/S3/ingestion 원장과 원천 registry를 같은 호스트에서 읽으므로 원장이 운영자 작업 디렉터리에 있는 동안 Fargate에서 서빙할 수 없습니다. 나중의 별도 Worker는 저장소·소유권 설계가 먼저이며 자동 프로비저닝은 없습니다.
2. **TLS.** 원격 개발 대상은 `bolt+s`가 필수입니다(`bolt+ssc`·인증서 검증 끄기·평문 터널 우회 없음). Neo4j 서버는 `server.bolt.tls_level=REQUIRED`(Docker: `NEO4J_server_bolt_tls__level=REQUIRED`), `dbms.ssl.policy.bolt.enabled=true`, `base_directory`(`private.key`는 PKCS#8, `public.crt`, 비어 있어도 `trusted/`·`revoked/` 디렉터리 필요), `client_auth=NONE`으로 설정합니다. REQUIRED여야 터널을 통해 와도 서버가 평문 Bolt를 거절합니다. 사설 CA의 **공개 PEM만** 그래프 명령마다 `SSL_CERT_FILE=<pem>`으로 줍니다(드라이버 `bolt+s`는 `load_default_certs()`를 쓰며 OpenSSL이 이 변수를 읽습니다). `SSL_CERT_FILE`은 기본 CA 파일을 **대체**하므로 프로필에 export하지 말고 해당 명령의 subshell에만 두세요(`zoop-ai-collect`의 공개 HTTPS가 닫힙니다). macOS 키체인·hosts·시스템 CA 저장소는 바꾸지 않습니다. 서버 TLS 설정 변경은 EC2 `user_data`를 바꾸는 **AWS 변경**이며 `user_data_replace_on_change=true`이면 인스턴스가 교체되어 사설 IP가 바뀝니다. TLS 적용은 `preflight`·`init`보다 먼저 합니다. 지금까지 이 경로의 실제 TLS 동작은 `scripts/graph_tls_smoke.py`로만 증명합니다(아래).
3. **내부 DNS.** `neo4j.dev.zoop.internal:7687`은 **제안한 안정 논리 FQDN**입니다. 원장에 묶이는 URI 문자열은 `bolt+s://neo4j.dev.zoop.internal:7687`로 영구 고정이어야 하고(다른 URI는 `graph_store_already_bound`), 포트도 URI의 일부입니다. 운영자만 접속하는 동안 Route53은 필요 없습니다: 운영자 로컬 hosts에서 이름을 `127.0.0.1`로 매핑하고 로컬 7687을 SSM 포트 포워딩으로 인스턴스 7687에 잇습니다(TLS는 여전히 서버 이름을 종단 검증). 이 경로는 별도 IAM 승인(`ssm:StartSession`, `AWS-StartPortForwardingSession`)이 필요하고 승인 전에는 실행하지 않습니다. 7474(Browser)는 포워딩하지 않습니다. VPC 안에 클라이언트가 생기면 같은 FQDN의 private hosted zone이 필요합니다(새 리소스·비용).
4. **init.** 빈 인스턴스에 대한 일회성 운영자 명령이며 **통과한 `preflight`와 같은 stdin·같은 URI 뒤에만** 실행합니다. `preflight`는 `init`과 같은 순수 규칙으로 비어 있는 Neo4j 5 database인지 읽기만 하며(원장·디렉터리·잠금 없음, DDL·쓰기 없음) `eligible-empty-target`과 `ddlPermission:"unverified"`를 냅니다. **DDL 권한이나 확인 이후 상태 불변은 증명하지 못하므로 `init` 성공 보장이 아닙니다.** 이미 원장이 있으면 `graph_store_already_bound`로 거절합니다(바인딩 재확인은 멱등한 `init` 재실행: DDL·store 쓰기 없음). 설치된(비편집) wheel은 `ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR`(둘 다 절대 경로)가 없으면 `state_ownership_unconfigured`로 닫힙니다.
5. **database·storeId·비밀.** `database=neo4j`, `storeId=zoop-dev-graph`(`^[A-Za-z0-9._:-]{1,200}$`), 전용 빈 Community 인스턴스입니다. Community는 표준 database가 하나뿐이어서 **인스턴스 전체가 이 projection의 것**이고, `Zg*` 외 라벨·관계 유형이 보이면 읽기가 `graph_store_foreign_data`로 withheld되므로 다른 앱은 이 인스턴스에 쓸 수 없습니다. 비밀 `zoop-dev/neo4j/auth`는 EC2 부트스트랩과 전용 운영자만 쓰며 환경변수로만 주고(argv·파일·셸 이력 금지) API·BFF·일반 AI 작업에는 주지 않습니다.

**Community 한계.** Community에는 역할이 없고 모든 사용자가 암묵적 관리자 권한을 가집니다([Neo4j 문서](https://neo4j.com/docs/operations-manual/5/authentication-authorization/manage-users/)). 사용자 이름은 `neo4j`로 바꿀 수 없고 두 번째 사용자를 만들어도 권한은 같습니다. 따라서 **reader role이 있다고 주장하지 않으며** 이 자격은 사실상 관리자 자격입니다. `graph.read` HTTP는 Enterprise RBAC reader role(라이선스 결정) 또는 문서화된 위험 수용 전까지 켜지 않습니다. 이 자격이 AI 작업 정의의 `secrets`에 들어가는 것은 별개의 미래 결정이며 ECS 주입은 실행 역할의 정확한 ARN 범위로만, 현재 IAM 변경은 없습니다.

**EBS ↔ 원장 백업 짝.** 원장(`graph.sqlite3`, 운영자 호스트)과 Neo4j 데이터(별도 EBS `/opt/neo4j`)는 **하나의 단위**입니다. `init`이 `dbId`·owner를 원장에 묶으며 rebind 경로가 없습니다: 원장을 잃으면 DB에 남은 store 마커가 고아가 되어 `init`이 `graph_store_not_empty`로 거절하고, DB를 새로 만들면 `dbId`가 달라져 읽기가 `graph_store_identity_mismatch`입니다. 두 백업은 **같은 정지 시점**(어떤 `zoop-ai-graph` 프로세스도 실행 중이 아닐 때)에 같이 만들고 같이 복원하며 원장을 두 번째 writer에 복사하지 않습니다. Community의 오프라인 dump/load가 `db.info().id`를 보존하는지는 **미검증**입니다(로컬에서 dump→load→`db.info()` 비교→멱등 `init`이 `bound`를 돌려주는지로 먼저 관측). 인스턴스가 교체돼도 별도 EBS의 `dbId`가 유지될 것으로 [INFERENCE] 보지만 교체 전후 `db.info().id`를 확인해야 합니다.

**운영자 실행 순서(제안, 승인 전 미실행).**

```sh
WS=<운영자 로컬 영구 POSIX 디스크 경로>   # NFS·EFS·iCloud/Dropbox 동기화 폴더·심볼릭 상위 경로·macOS의 /tmp·/var 금지. $WS/graph는 init 전에 없어야 한다
# 고정된 커밋에서 빌드한 wheel을 전용 venv에 설치(편집 설치 금지). $WS/requests/init.json:
#   {"schemaVersion":"zoop-graph-projection-1","storeId":"zoop-dev-graph","database":"neo4j"}   $WS/trust/zoop-dev-graph-ca.pem: 공개 CA 인증서만
run() { ( read -rs ZOOP_GRAPH_PASSWORD </dev/tty; export ZOOP_GRAPH_PASSWORD
          export ZOOP_GRAPH_AUTH=basic ZOOP_GRAPH_USER=neo4j SSL_CERT_FILE="$WS/trust/zoop-dev-graph-ca.pem" \
                 ZOOP_STATE_DIR="$WS/reserved/app-state" ZOOP_AI_WORKER_STATE_DIR="$WS/reserved/worker-state"
          exec "$WS/venv/bin/zoop-ai-graph" "$1" --state-dir "$WS/graph" --graph-uri bolt+s://neo4j.dev.zoop.internal:7687 < "$WS/requests/init.json" ) }
run preflight   # exit 0, {"preflight":{"result":"eligible-empty-target","ddlPermission":"unverified","tls":"verified","ledger":"absent",…}}
run init        # 같은 stdin·같은 URI. 성공 store: {state:"bound", schemaObjects:{constraints:10, indexes:13}}
run init        # 멱등 재확인(원장·Neo4j 불변)
```

`preflight`·`init`의 오류는 모두 기존 안정 코드(exit 2, 자동 재시도 없음)입니다. TLS 실패 원인(CA 불신·이름 불일치·평문 Bolt)은 모두 `graph_unavailable{driver:"ServiceUnavailable"}` 하나로 모이므로 진단은 한 번에 변수 하나만 바꿔 건강한 서버와 비교합니다. `ZOOP_GRAPH_AUTH=none`은 루프백 평문에서만 허용됩니다.

**로컬 TLS 증명(실제 Neo4j, 명시 옵트인, `make pipeline-graph-tls-smoke`).** `ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_tls_smoke.py --manage-containers`는 임시 PKI와 자기 컨테이너(공식 `neo4j@sha256:f1e52d4dc6da122468c4a3c1050a4f5e117f6d3268625237c34d49166f0d6082` = 5.26.32, pull하지 않음, `127.0.0.1`만 게시, 사용 통계 보고 끔)로 `preflight`(좋은 CA·이름·인증)와 7개 부정 사례(CA 변수 없음·다른 CA·이름 불일치·TLS REQUIRED 서버에 평문 Bolt·잘못된 비밀번호 한 번·TLS에 `auth=none`·안전하지 않은 URI)와 `init`/반복/`preflight` 거절을 확인하고, 이어서 기존 전체 graph smoke와 회귀를 **새 빈 컨테이너마다** TLS로 실행한 뒤 만든 컨테이너와 키를 모두 지웁니다. 이미 가진 서버에는 `ZOOP_GRAPH_TLS_SMOKE_URI/_CA/_WRONG_CA`와 `--stage`를 씁니다(스크립트 도움말 참조).

**Fargate·배포 게이트(사실 근거, 새 기능 아님).** 현재 AI 서비스는 `127.0.0.1:8797`에만 바인딩하고(Infra 정의는 8000), `/health`가 없으며, `ai`용 Dockerfile이 없고, 원장이 영구 로컬 SQLite를 요구하며, graph child는 `SSL_CERT_FILE`을 받지 않아(컨테이너라면 이미지의 OS 신뢰 저장소에 CA가 있거나 변수 전달을 검토된 코드로 추가해야 함) 지금은 Fargate에 올릴 수 없습니다. API의 7687 보안그룹 ingress는 Spring이 Neo4j 비밀을 갖지 않으므로 불필요해 보입니다(Infra 권고). 이전에 게이트였던 private-PoC 의존성은 AI pipeline의 로컬 cutover가 PR #213(`main`)으로 병합되면서 해소됐고 기본 설치는 공개 의존성만 씁니다. **AWS 배포는 보류입니다.**

**실행 기록(2026-10-16, 당시 로컬 작업 트리 시점의 Main 실행 이력이며 현재 `main` HEAD의 재검증이 아님).** `ai/pipeline` 시험 665개가 통과했고, 로컬 TLS smoke(`--manage-containers`, 실행 `dd2cfee7`, digest 고정 `neo4j@sha256:f1e52d4d…` 5.26.32 Community)는 `cases`·`smoke`·`regression` 3단계를 모두 통과했습니다(`bolt+s`, 기본 인증, 단계마다 새 빈 컨테이너, 명령 출력 JSON 34개에서 비밀·자격 필드·대상·경로 노출 없음, 컨테이너와 임시 PKI 제거). `preflight`는 올바른 CA·이름·인증에서 `eligible-empty-target`이었고 CA 변수 없음·다른 CA·이름 불일치·평문 Bolt·잘못된 비밀번호·`auth=none`·안전하지 않은 URI는 각각 기존 안정 코드로 거절됐으며 ledger·상태·Neo4j 변경은 없었습니다. 설치된(비편집) wheel에서 소유권 변수가 없거나 비었거나 상대 경로이면 `state_ownership_unconfigured`(소켓 이벤트 0, 상태 0)였고, 올바른 변수와 닫힌 포트는 `graph_unavailable`로 이유가 바뀌었습니다. **이는 로컬 Community 5.26 TLS·기본 인증 증명이며 AWS·Fargate·RBAC·SSM·실제 DNS·`GraphDbStatus` 준비 증명이 아닙니다.** AWS 배포는 보류입니다.

**남은 인프라 선행 조건.** (a) CA 방식·키 보관자·서버 키를 EC2에 두는 방법·회전·만료 담당(오프라인 CA 또는 AWS Private CA), (b) 운영자 IAM의 SSM 포트 포워딩 승인과 비밀을 가져오는 방법, SSM 에이전트 등록 확인, (c) Community 수용 또는 Enterprise 결정, (d) dump/load의 `dbId` 보존 관측, (e) 운영자 호스트의 디스크 암호화·접근·백업(원장에 원천 유래 데이터), (f) 이미지 digest 기록(`sha256:f1e52d4d…`는 5.26.32 태그와 같은 다이제스트로 Main이 로컬에서 확인).

---

# 공개 그래프 handoff bundle (AI 생산물 → 백엔드 import) — 현재와 계획

위의 비공개 S3 그래프 읽기와 **별개**입니다. 앱이 공개 그래프(`company`/`issue` 노드, `INVOLVES`·`STRUCTURALLY_RELATED_TO`·`FOLLOWS`)를 만들 때 소비하는 **AI 측 산출물**입니다. 설계·근거 규칙 전문은 [AI 설계 문서의 해당 절](../../docs/design/ai-system.md#s2s3--공개-그래프-handoff-bundle-ai-측-생산물-앱-importㆍ활성화는-백엔드-소유)입니다.

| | 현재(AI 구현. PR #213으로 `main` 병합 완료. 아래 시험·smoke 수치는 당시 이력이며 현재 HEAD 재검증이 아님) | 계획/미결정(백엔드·계약 소유) |
|---|---|---|
| 생산 | 설치 명령 `zoop-ai-handoff {freeze,inspect,recover,export}`가 둘 이상의 S3 job을 고정해 불변 bundle 생성 | bundle을 앱 `graph_versions`의 실제 스냅샷 행으로 **비활성 등록**하는 operator 비웹 스테이징 import는 로컬 작업 트리에 구현(미게시·최종 검증 대기, [api README](../README.md#그래프-handoff-스테이징-import)). **활성화**는 미결정·미구현(공개 `GET /api/v1/graph`와 fixture 기반 `graph_versions`는 main에 이미 있음) |
| 상태 | `publication=not-published`, `readiness={app:"import-pending", evidenceRegistration:"not-registered", publicActivation:"none", graphDb:"none"}` | `GraphDbStatus`/`Neo4jStatus`/`GraphDbVersionState` 대응 생산자 없음(**만들어 채우지 마세요**) |
| 근거 | 앱 호환 evidence id를 **제안**하고 좌표·`quoteSha256`·locator를 제공 | 앱 텍스트 기준 인용 해시 검증과 `evidence` 행 등록은 위 로컬 스테이징 import가 수행(인용 무결성만, 의미 검증 아님; 미게시). `getEvidence`의 graph evidence 경로와 공개 제외 오버레이는 없음(현재는 graph 근거를 미등록 취급) |
| 시각 | `publishedAt`/`observedAt`/`eventTime`/`verifiedAt`을 따로 보존 | `asOf` 정책(버전 선택 vs 고정 버전 안 disclosure 필터) |

## 소유 경계

- **AI(pipeline):** 원천(S2/S3) 읽기·권한 재검증·projection·bundle·`recover`. 앱 DB, 공개 route, Neo4j 상태를 쓰지 않습니다.
- **백엔드(정세빈):** bundle 소비, 앱 article/company 대조, evidence 등록, 그래프 버전 행·활성화, 공개 읽기·상태. 앱에 **가변 후보 사본을 두지 않습니다**(ERD 원천 소유: 후보는 원천에서 읽음). bundle은 import 입력일 뿐 앱의 활성 버전이 아닙니다. 이 중 대조·evidence 등록·**비활성** 버전 행 등록은 로컬 작업 트리(미게시)의 operator 스테이징 import가 담당하고, 활성화·공개 route·`getEvidence` graph 경로·상태 모델은 아직 백엔드 몫으로 남아 있습니다.
- **운영자(서버 소유):** canonical registry, 공개 결정 파일, 앱 문서 바인딩 파일. 호출자(HTTP/UI)가 고를 수 없습니다.

## 하위 프로세스 계약

```sh
zoop-ai-handoff export --state-dir DIR --relation-state-dir DIR --extraction-state-dir DIR --ingestion-state-dir DIR \
  --sources FILE --canonical FILE --decisions FILE --bindings FILE   < {"schemaVersion":"zoop-ai-handoff-1","handoffId":"…"}
zoop-ai-handoff inspect --state-dir DIR < {"schemaVersion":"zoop-ai-handoff-1","handoffId":"…"}      # 내용 없음: 상태·receipt·시도
```

- stdin JSON 하나(≤65,536B), stdout canonical JSON 한 줄. 설치형은 `ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR` 절대 경로가 필요합니다(없으면 `state_ownership_unconfigured`). 네트워크·모델 호출 0, 원천 원장 쓰기 0.
- exit 0: 현재 export(`delivery.status="current"`, `bundle`) 또는 원장 결과. exit 2: 오류 `{schemaVersion,error:{code[,detail]}}` 또는 **withheld**(`delivery.status="withheld"`, `bundle`·개수·id 없음). 백엔드는 withheld·오류를 "그래프에 데이터 없음"으로 해석하면 안 됩니다. 응답 크기는 ≤6 MiB(bundle 상한)이며 클라이언트 읽기 상한은 8 MiB 이상으로 두세요.
- 재시도 가능: `handoff_busy`, `relation_busy`, `extraction_busy`, `ingestion_busy`(writer가 잡음), `handoff_recovery_required`(강제 종료된 writer 뒤 — 운영자가 `recover`/writer 명령으로 정리). 운영 조치: `handoff_artifact_missing|invalid`(저장 bundle 이상 → 새 handoffId), `operator_file_changed`, `*_invalid`. withheld 코드 예: `canonical_mapping_changed`, `decisions_changed`, `bindings_changed`, `review_revision_changed`, `upstream_changed`, `source_unauthorized`, `grant_revision_changed`, `handoff_content_changed`, `source_pin_missing`. 모르는 코드는 "withheld(원인 불명)"로 처리하세요.
- 무결성 검증: `receipt.bundleDigest`는 `canonical(bundle)`(Python `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)`, 앱 `Canonical.write`와 같은 형식)의 UTF-8 바이트 sha256입니다. 받은 bundle을 다시 canonical화해 같은지 확인할 수 있습니다.

## bundle `zoop-graph-handoff-bundle-2` (닫힌 스키마, 모르는 키 거부)

| 키 | 내용 |
|---|---|
| `handoffId`, `manifestDigest`, `provenance` | ID, manifest sha256, `{declaredSourceKind, observedSourceKind, executionMode, recordingKind}` (선언≠관측이면 생산 거부) |
| `policy` | 정책 버전 `zoop-public-projection-policy-1`, 운영자 파일 3개의 sha256, evidence id 종류 `graph-body-span`, 좌표 단위 `unicode_code_point` |
| `sources[]` | S3 job·S2 upstream(grant revision 포함 digest)·review digest·닫힌 정책 버전과 감사 개수·**사용한 relation의 review revision** |
| `companies[]` | `{id=companies.id, canonicalId, label, decisionRef}` — import 시 앱 카탈로그에 존재하고 label이 같아야 함 |
| `issues[]` | `{id, canonicalId, title, action, target, eventTime, timePrecision(year|month|day|datetime|unknown), period, assertionStatus, geography{value domestic|international, decisionRef, decisionVersion, policyVersion, countries, verification:"operator-field-verdict", evidenceIds, basis[]}, evidenceIds, sourceEvents[], mentions[], decisionRef, representative}`. `sourceEvents[]`는 각각 `{upstream,kind,ref,mentionId,documentId,documentVersion,observation}`이며 `observation`은 정확한 `{roundId,sourceId,page,ordinal,documentId,rawVersion,documentVersion}`입니다. geography의 `basis[]`에도 동일한 원천 식별자와 국가 집합을 기록합니다. 대표 mention을 선택할 때도 이 전체 식별자를 지정해야 합니다. 이슈의 `evidenceIds`는 모든 `mentions[].evidenceIds`와 `geography.evidenceIds`의 합집합과 정확히 같습니다. |
| `issues[].mentions[]` | 닫힌 배열(최대 1000개). 각 항목은 S2 원본 mention 하나이며 `{documentId, documentVersion, mentionId, articleId, articleVersion, verification:"none", title, action, target, eventTime, timePrecision, period, assertionStatus(occurred|announced|planned|forecast|cancelled|unknown), background(JSON bool), participants[{sourceCompanyId, companyId, name, role}], evidenceIds[]}`입니다. `(documentId, documentVersion, mentionId)`가 식별자이며 S2 local `mentionId`는 한 문서 버전 안에서만 유일합니다(다른 문서가 같은 값을 써도 별개 mention). 이 식별자 집합은 이슈 `sourceEvents[]`의 식별자 집합과 정확히 같고 정규 JSON 오름차순 유일입니다. 각 mention은 같은 문서 버전을 가진 **정확히 하나의** bundle article(`articleId`/`articleVersion`)에 닫히고, `evidenceIds`는 그 기사의 근거만 담습니다(최소 1개, 오름차순). `verification`은 항상 `none`입니다: 값은 S2 후보/snapshot의 **원본**이며 병합된 이슈 필드에서 만들어지지 않고 검증·결정·승인된 값이 아닙니다. `title`·`action`은 S2 문자열 그대로, `target`·`eventTime`·`period`는 S2 값 그대로(null 가능, 문자열은 다시 쓰지 않음)이며 `timePrecision`은 `eventTime`의 형식에서 넓히지 않고 정해집니다. `eventTime` 문법(생산자 `mention_time_precision`과 앱 `HandoffTime.mentionEventTime`이 손으로 같게 구현, 공유 vector `src/test/resources/graph-handoff/mention-time-vectors.json`): ASCII `YYYY`·`YYYY-MM`·`YYYY-MM-DD`·`YYYY-MM-DDTHH:MM[:SS[.f{1,9}]](Z|±HH:MM)`(대문자 `T`·`Z`, offset 필수). 양쪽이 이미 받던 집합이며, 한쪽(Python stdlib)만 받고 앱이 bundle 전체를 거절하던 형식(ISO 주 날짜 `2026-W40-3`, 서수·압축 형식, 쉼표 소수, 콜론 없는/초 있는 offset)과 라이브러리 범위(offset 시간 18 초과, 달력 날짜의 0000년)만 지원하지 않습니다. 지원하지 않는 형식은 생산자가 freeze 전에 이슈를 `mention_event_time_unsupported`로 제외하고 앱은 `temporal_unsupported`로 거절합니다. `participants[]`는 S2 순서이고 `sourceCompanyId`·`name`·`role`은 S2 텍스트 그대로입니다(`role`은 확인된 역할이 아니며 `INVOLVES`도 아님). `companyId`는 모든 운반 upstream이 같은 공개 회사로 매핑하고 그 회사가 이 bundle `companies[]`에 있을 때만 값이 있고, 아니면 null입니다(null이 아니면 `sourceCompanyId`도 null이 아니어야 함). 같은 식별자를 운반하는 upstream끼리 값이 다르면 생산자는 그 이슈를 `mention_values_conflict`로 제외합니다. |
| `relations[]` | `{id, type INVOLVES|STRUCTURALLY_RELATED_TO|FOLLOWS, source, target, role, assertionStatus, evidenceIds, basis[], provenance{…}, decisionRef, sourceRefs[]}` — INVOLVES/STRUCTURAL은 issue→company, FOLLOWS는 뒤 이슈→앞 이슈. 구조 `basis[]`의 각 항목은 `{sourceRelation{jobId,relationCandidateId},relationKey,relationType,validFrom,validUntil,countries,verifiedAt,sourceArticles[],evidenceIds[]}`이며 직접 관계 인용과 별도 유효기간 인용을 모두 포함합니다. `SHARES_ISSUE`는 **없음**(소비자가 권한·시간 필터 뒤 파생). |
| `evidence[]` | `{id, kind:"graph-body-span", articleId, articleVersion, start, end, offsetUnit, quoteSha256, rawLocatorIds[], source{documentId, documentVersion, rawVersion, textArtifactId, sourceEvidenceId(S2 ev-…32hex), inputKind:"body"}}` — 인용문·본문 없음 |
| `articles[]` | `{articleId, articleVersion, documentId, documentVersion, rawVersion, title, url, publishedAt, publicationPrecision(datetime|day|unknown; `day`는 수집 시 날짜만 선언된 문서이며 `publishedAt`이 `YYYY-MM-DD` 날짜이고 자정으로 바꾸지 않는다. 오프셋 없는 선언 시각은 `unknown`), observations[{roundId, sourceId, page, ordinal, observedAt, grant}]}` — 같은 문서 버전의 **모든 서로 다른 관측**을 보존합니다. 관측별 제목·URL·발행 시각이 다르면 freeze를 거부합니다. |
| `exclusions` | `{counts{code:n}, items[{kind, id, jobId, code[, detail]}]}` — id·코드만(내용 없음), current export에서만 노출 |
| `counts`, `checks`, `readiness`, `digests.content` | 개수, `producerConfirmed`/`appImportPending`, 위 상태, 내용 digest |

**관계 출처 표시를 소비자는 보존해야 합니다.** `STRUCTURALLY_RELATED_TO.provenance`는 `origin:"manual-operator-review"`, `s3SemanticValidation:"none"`, `status:"operator-asserted"`, `reviewer`, `decisionVersion`, `bindingDigest`입니다 — S3가 자동으로 의미를 검증한 것이 **아닙니다**(공개 표기·수용 여부는 미결정). `FOLLOWS`는 S2 replay 비교+운영자 결정(`s3SemanticValidation:"none"`), `INVOLVES`만 S3 독립 verifier가 모든 claim을 지지한 관계입니다. geography도 AI 자동 검증이 아니라 운영자 field verdict이며 모든 source mention의 국가 필드와 같을 때만 나옵니다.

검증기는 source·감사·정책·source event·대표 선택·관계별 provenance/sourceRefs·구조 basis·제외 상세의 중첩 필드까지 닫힌 형식으로 확인합니다. sourceRefs와 upstream·기사 근거의 참조 관계, 관계 ID(`edge-`+정규 JSON preimage의 SHA-256)도 검증합니다. `STRUCTURALLY_RELATED_TO` ID의 preimage는 `{type,source,target,basis:[relationKey,…]}`이며 다른 두 유형은 `{type,source,target}`입니다. 문서와 앱의 실제 텍스트 일치는 앱이 import 때 별도로 확인해야 합니다.

기존 `handoff.sqlite3`가 있는 네임스페이스는 어떤 파일이나 권한을 변경하기 전에 읽기 전용으로 소유 표식과 원장 구조를 검사합니다. 다른 DB나 일부만 존재하는 디렉터리는 채택하지 않습니다. 새 원장만 초기화할 수 있습니다. `export`의 마지막 확인과 응답 직렬화는 S3 읽기 잠금을 유지한 채 수행하지만, 잠금이 보호하지 않는 원천 권한·운영자 파일은 확인 직후에도 바뀔 수 있습니다. 앱 import 직전의 별도 재확인은 여전히 필요합니다.

## 앱 import가 해야 할 것 (AI가 확인하지 않은 것 = `appImportPending`)

**현재 상태(로컬 작업 트리, 미게시·최종 검증 대기).** 아래 1·2·4와 3의 `evidence` 행 삽입은 operator 스테이징 import가 수행하며(대조 항목은 article version의 제목·URL·게시 시각 정밀도, 앱 텍스트와 export 텍스트의 byte 일치·인용 코드 포인트 해시, 회사 ID·이름; 정확한 규칙은 [api README](../README.md#그래프-handoff-스테이징-import)) 결과는 **비활성** 버전입니다. 5(활성화·`asOf` 정책·상태 모델)와 3의 `getEvidence` graph 경로는 구현되지 않았습니다. AI가 확인하지 않은 항목이라는 아래 구분은 AI 산출물 기준이며 그대로입니다.

1. `articles[]`의 `(articleId, articleVersion)`이 앱 `articles`/`article_versions`에 있고 `title`·`url`·`publishedAt`(+정밀도)이 **그 버전의** 값과 같은지(현재 최신 버전이 아님). 문서 import 매핑: `articles.id=documentId`, `article_versions.version=documentVersion`([문서 import](DOCUMENT_IMPORT.md)).
2. 각 evidence의 `[start,end)`를 **앱이 저장한 본문**에서 코드 포인트로 잘라 sha256이 `quoteSha256`과 같은지, 바인딩의 `textSha256`(앱 `artifacts.sha256`과 같아야 함)이 앱 저장 텍스트와 같은지. AI는 **원천** 텍스트만 검증했고 앱 텍스트는 보지 않았습니다.
3. `evidence` 행 등록(불변, `input_kind=body`, `quote_verified`, `raw_locator_ids`)은 이 id로 **import가 직접 삽입하거나 동일성 검증**해야 합니다. 이 id는 "준비됨"이며 등록·공개된 것이 아닙니다. 현재 `getEvidence`는 `ev-`+64hex라도 S1 summary 인용만 제공하므로 graph evidence를 제공하려면 pinned 경로(버전 소속·권한 overlay·인용 표시 grant)가 별도로 필요합니다(**남은 작업**).
4. `companies[]` id·label을 앱 카탈로그와 대조, issue id가 `companies.id`와 겹치지 않는지 확인.
5. 그래프 버전 행·활성화·`asOf` 정책·상태 모델. 이 bundle의 `readiness`를 `reflected`/`active`로 바꾸지 마세요.

## 제안 fixture 경로와 명령

생성기: `ai/pipeline/scripts/graph_handoff_smoke.py --write-fixture DIR`. 2026-10-16 Main이 보수 후 실제 subprocess smoke와 생성 fixture를 검증했습니다. 확인한 패키지는 `/tmp/zoop-graph-handoff-20261016-verified/`이며, 백엔드 테스트에 넣을 때의 제안 위치는 `api/src/test/resources/graph-handoff/`입니다(AI는 해당 경로를 쓰지 않았습니다). 시각(`observedAt`)과 digest가 실행마다 달라 **고정 fixture가 아니라 생성 시점의 스냅샷**입니다.

```sh
ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_handoff_smoke.py --write-fixture /abs/new-dir   # 새 디렉터리만: 이미 있으면 거절하고 아무것도 덮어쓰지 않음
```

| 파일 | 기대 결과 |
|---|---|
| `export-valid.json` | 유효한 current export 전체(이슈 2·관계 4·evidence 6·기사 3·제외 3 코드) — import가 모두 수용해야 함 |
| `export-withheld.json` | bundle 없는 withheld — 어떤 것도 import하면 안 됨 |
| `bundle-forged-evidence-id.json` | evidence id가 좌표 공식과 다름 — 거부 |
| `bundle-missing-geography.json` | 이슈 geography 없음 — 거부 |
| `bundle-dangling-endpoint.json` | 관계 끝점이 노드에 없음 — 거부 |
| `bundle-wrong-article-version.json` | evidence의 articleVersion이 articles와 불일치 — 거부 |
| `bundle-shares-issue-edge.json` | 저장 `SHARES_ISSUE` 간선 — 거부 |

**검증 결과(2026-10-16, 병합 전 로컬 작업 트리 이력).** pipeline 전체 365개 테스트와 두 S2/S3 작업을 사용하는 실제 CLI smoke가 통과했습니다. 독립 검토의 6개 결함은 15개 실패 시나리오로 먼저 재현한 뒤 수정했으며, 중첩 스키마 변조는 19개 독립 사례로 검사했습니다. export 중 권한/운영자 파일 변경, 문서 간 동일 mention ID, 유효기간만 증명하는 별도 근거, 중복 관측의 URL 충돌, 외부 원장 채택·변경을 거절합니다. 생성한 유효 export는 검증기를 통과했고 위 잘못된 bundle 5종은 모두 거절됐습니다. source 원장의 bytes·권한·mtime은 유지됐고 provider/model 호출은 0이었습니다. `public-check`는 생성물 275개 drift 0·hard error 0·문서 테스트 21개 통과이며 기존 경고는 보존했습니다.

이 결과는 AI 생산자 경로의 검증입니다. 앱 import·`getEvidence` 소비·공개 활성화·운영자 수동 단언의 공개 수용 정책·실제 데이터 품질은 완료된 것으로 처리하지 않습니다. 관련 #52/#53/#75/#78/#79의 전체 종료 근거도 아닙니다. 이 변경은 이후 PR #213(`main`)에 병합됐습니다.

이후 앱 쪽 **비활성 스테이징 import**가 로컬 작업 트리에 별도로 구현됐지만(위 "지금 상태"), 이 절의 병합 전 검증 이력이나 AI 생산자 검증에 포함되지 않으며 공개 활성화·`getEvidence` 소비를 완료로 바꾸지 않습니다.

## 재현 가능한 operator handoff package (`--write-package` / `--verify-package`)

위 `--write-fixture`는 임시 세계를 만들고 **지웁니다**: 남는 것은 JSON 봉투뿐이라 받는 쪽이 같은 handoff를 다시 export하거나 문서 입력을 맞춰 볼 수 없습니다(원장·운영자 파일·source registry가 임시 디렉터리와 함께 삭제됨). 같은 생산자 세계(실제 ingestion + S2 두 개 + S3 두 개, authored replay)를 **명시한 새 디렉터리에 그대로 남기는** 명령이 별도로 있습니다. 새 프레임워크가 아니라 같은 스크립트의 두 옵션입니다.

```sh
# 선행: make pipeline-install (설치된 zoop-ai-handoff·zoop-ai-ingest가 같은 venv에 있어야 함)
PY=ai/pipeline/.venv/bin/python
$PY ai/pipeline/scripts/graph_handoff_smoke.py --write-package /abs/real/new-dir   # 생성: 한 handoff를 설치된 CLI로 freeze·export, 손으로 쓴 기대값과 비교, 세계 보존
$PY ai/pipeline/scripts/graph_handoff_smoke.py --verify-package /abs/real/new-dir [--export-out /abs/new-file.json]   # 새 프로세스로 재 export, PACKAGE.json의 핀과 비교
```

- `DIR`은 **없어야** 합니다(이미 있으면 빈 디렉터리여도 거절, `--export-out`도 새 파일만). 부모는 symlink 성분이 없는 실경로여야 합니다(macOS `/tmp`는 `/private/tmp`로). 생성이 실패하면 이번 실행이 만든 `DIR`만 지웁니다(PACKAGE.json은 마지막에 쓰므로 PACKAGE.json이 있으면 완성본).
- 합성 데이터뿐입니다: 실제 뉴스·라이선스 주장·API 키·AWS·PoC·Neo4j·유료 모델 호출이 없고(`providerCalls=0`, `modelCalls=0`, CLI는 소켓 감사 훅 아래 실행) 결과는 `not-published`·활성화 없음입니다. 공개 회사 ID는 앱 카탈로그의 시드 ID와 겹치지 않도록 `SYNTH:000001`(합성기업)·`SYNTH:000002`(합성부품)입니다(`--write-fixture`의 `KRX:*`와 다름). importer 대상 DB에는 이 두 회사를 같은 id·label로 넣어야 합니다(PACKAGE.json `companies`).

기대 파일 트리(경로·본문·비밀 없는 값은 PACKAGE.json, 아래 모두 `DIR` 직하):

```
PACKAGE.json                      핀(manifestDigest·bundleDigest·contentDigest)·운영자 파일 sha256·개수·회사·`locationBound:true`. 절대 경로 없음
export-request.json               zoop-ai-handoff export의 stdin ({"schemaVersion":"zoop-ai-handoff-1","handoffId":"synthetic-handoff-1"})
export-valid.json                 생성 시점의 current export 봉투(manifest+bundle). 시각·digest는 생성마다 다름
document-import-request.json      zoop-document-import-1: 세 문서의 관측 3개(kind=news), Java 문서 import의 요청 그대로
graph-handoff-import-request.json zoop-graph-handoff-import-1: 위 핀을 담은 요청(operator=package-operator)
sources.json                      source registry (S2-1/S3/handoff가 읽는 권한 원천)
canonical.json decisions.json bindings.json   freeze에 쓴 운영자 파일(manifest가 sha256으로 고정)
ingestion/ extraction/ relation/  S2-1·S2·S3 원천 원장 (export·importer가 읽기 전용으로 엶)
handoff/                          handoff 원장 + bundles/<bundleDigest>.json
inputs/ *.replay.json *-manifest.json …   authored 입력과 replay (원장이 참조하는 재료, export는 필요 없음)
```

**위치 결속(중요).** S2-1 원장은 `sources.json`의 source `inputRoot`(절대 경로)를 scope 설정으로 고정하고 읽을 때마다 현재 registry와 대조합니다(소스: `ingestion.py`의 `authority.check(..., config=저장된 config)`). 그래서 패키지는 **만들어진 그 절대 경로에서만** export되는 것으로 설계돼 있습니다: 복사·이동하면 원천 설정 불일치로 거절될 것이며([INFERENCE] 이동 실행은 하지 않았고 정확한 오류 코드는 확인하지 않음), `--verify-package`는 이를 "moved or copied"로 먼저 알려 줍니다. 다른 위치로 전달하려면 파일을 옮기지 말고 그 위치에서 `--write-package`를 다시 실행하세요(세계는 생성마다 시각·digest가 달라 **핀도 새로 나옵니다**; 받는 쪽은 자기 생성의 PACKAGE.json·핀만 쓰세요). 전달 뒤 낡은 경로를 가리키는 파일은 없습니다(PACKAGE.json·요청 파일에 경로 없음; 경로는 `sources.json`과 원장 안에서만 이 위치를 가리킴).

`--verify-package`가 하는 일: PACKAGE.json의 운영자 파일 sha256 대조 → 설치된 `zoop-ai-handoff export`를 새 프로세스로 실행(`delivery.status=current`) → manifest·bundle을 canonical로 다시 해시해 PACKAGE.json과 receipt의 세 핀과 비교 → 문서 요청의 관측마다 설치된 `zoop-ai-ingest export --require-store` 실행(rc 0) → 세 source 원장의 bytes·mode·mtime 불변 확인. 하나라도 다르면 0이 아닌 코드로 끝납니다. 같은 명령은 셸에서 직접도 됩니다(ZOOP_STATE_DIR·ZOOP_AI_WORKER_STATE_DIR은 패키지 **밖**의 비어 있는 절대 경로 디렉터리):

```sh
D=/abs/real/new-dir; W=ai/pipeline/.venv/bin
ZOOP_STATE_DIR=$(mktemp -d) ZOOP_AI_WORKER_STATE_DIR=$(mktemp -d) $W/zoop-ai-handoff export --state-dir $D/handoff \
  --relation-state-dir $D/relation --extraction-state-dir $D/extraction --ingestion-state-dir $D/ingestion \
  --sources $D/sources.json --canonical $D/canonical.json --decisions $D/decisions.json --bindings $D/bindings.json < $D/export-request.json
```

Java 스테이징 import에 쓰는 법(기존 계약 그대로, 변경 없음): ① `document-import-request.json`을 `ZOOP_DOCUMENT_IMPORT_REQUEST`로 문서 import를 먼저 실행하고([문서 import](DOCUMENT_IMPORT.md#실행)), ② 위 두 회사를 카탈로그에 넣은 뒤, ③ `graph-handoff-import-request.json`을 `ZOOP_GRAPH_HANDOFF_IMPORT_REQUEST`로 실행합니다. 설정은 `ZOOP_HANDOFF_CLI`=`.venv/bin/zoop-ai-handoff`, `ZOOP_INGESTION_CLI`=`.venv/bin/zoop-ai-ingest`, `ZOOP_HANDOFF_STATE_DIR=$D/handoff`, `ZOOP_RELATION_STATE_DIR=$D/relation`, `ZOOP_EXTRACTION_STATE_DIR=$D/extraction`, `ZOOP_INGESTION_STATE_DIR=$D/ingestion`, `ZOOP_INGESTION_SOURCES=$D/sources.json`, `ZOOP_HANDOFF_CANONICAL/_DECISIONS/_BINDINGS=$D/<name>.json`이고 `ZOOP_ARTIFACT_ROOT`와 결과 파일은 `DIR` 밖(원장 안은 거절)에 둡니다([api README](../README.md#그래프-handoff-스테이징-import)). 결과는 **비활성** 버전이며 활성화·공개·`getEvidence`는 이 패키지가 증명하지 않습니다.

현재 브랜치(`feat/78-handoff-current-contract`)의 게시 경계: 이 두 옵션과 문서는 로컬 작업 트리이며 PR #229 갱신으로 게시되기 전에는 원격에 없습니다. Neo4j는 필요 없습니다(handoff는 비공개 graph를 읽지 않음). 이 패키지는 AI 생산자 쪽 재현 경로이고 앱 import·공개 활성화·실제 데이터 품질·실제 뉴스 권리는 증명하지 않습니다.

## 아직 결정되지 않은 공개 계약 (AI가 정하지 않음)

`STRUCTURALLY_RELATED_TO`의 수동 단언 수용과 이슈별 적용성 verifier, geography verdict의 성격, `asOf` 의미, company–company 구조 간선의 공개 유형, graph evidence의 `getEvidence` 경로와 인용 표시 grant, 활성화 전제와 `graphDb` 상태 모델, `FOLLOWS`의 independent verifier 필요 여부.

**유효기간 끝 경계(2026-10-20 확정: 끝 포함).** 생산자의 사건 적용성 판정은 `validFrom <= eventTime의 날짜 <= validUntil`입니다. `validFrom`은 첫 유효일, `validUntil`은 마지막 유효일이며 그날도 유효합니다(공개 FS042와 백엔드 `RelationValidity`의 방향과 같음). `eventTime`은 쓰인 달력 날짜로 비교하며 소스 정책 없이 시간대를 옮기지 않고, 공개 조회의 상태는 asOf(없으면 요청 시각)의 Asia/Seoul 날짜와 비교하므로 두 기준은 서로를 대체하지 않습니다. 날짜는 원래 `YYYY-MM-DD`를 보존하고 자정이나 다음 날을 추정하지 않으며, 원천의 “D일까지”는 그대로 `validUntil = D`이고 null은 종료 시점 미상이지 영구 유효의 보장이 아닙니다. 공개 조회에서 구조 근거는 검증 시각(`verifiedAt`)이 asOf 이하이면 보이며, 유효기간은 표시 여부를 정하지 않고 끝난 근거도 `ended` 상태로 남습니다. 2026-10-17 로컬 수정이 잠시 끝 제외로 바꿨던 규칙은 이 변경으로 되돌렸습니다.

동결된 묶음은 원본을 고치지 않습니다. 정책 버전(`zoop-public-projection-policy-1`)은 올리지 않았고, 현재 규칙으로 다시 만든 내용이 저장된 내용과 다르면(예: 끝 제외 규칙으로 동결해 종료일 당일 끝나는 근거를 뺀 묶음) export가 `handoff_content_changed`로 내용을 차단하며 새 `handoffId`로 다시 동결해야 합니다. 내용이 같은 묶음은 그대로 전달됩니다. 경계 회귀(`ai/pipeline/tests/test_handoff.py`)는 종료일 당일 포함, 전날 종료 제외, 끝 제외 규칙으로 동결된 묶음의 withheld와 보존을 확인하고, 설치된 CLI smoke(`ai/pipeline/scripts/graph_handoff_smoke.py`)도 같은 세 경계를 확인합니다.

---

# handoff bundle 내부 HTTP 읽기 (AI 소유, 읽기 전용) — 현재 구현과 백엔드 사용 주의

2026-10-16 AI 측이 위의 하위 프로세스 계약을 **읽기 전용 내부 HTTP**로 감싸 두었고 PR #213으로 `main`에 병합됐습니다(배포 없음; 앞단 TLS 프록시는 미배포). 이는 백엔드 [PR #189](https://github.com/Donbug/zoop/pull/189)(`docs/api/graph-read-contract-proposal.md`)가 "AI 측 인계 묶음"으로 합의한 단위를 **AI가 소유한 읽기 경로로 제공**한 것입니다. **백엔드의 Java 수입기·앱 스냅샷 등록·활성화·관리 API를 대신하지 않으며**, 위 "앱 import가 해야 할 것"은 그대로 백엔드 몫입니다. 이 HTTP는 Neo4j 자격이 필요 없고 `graph.read`는 선택·기본 꺼짐입니다. 기존 비공개 그래프 읽기(`graph-versions`, scope `graph.read`)와는 **별개 가족**입니다(변수·scope·allowlist 공유 없음).

**업데이트(로컬 작업 트리, 미게시).** 위 문단은 그대로 유효합니다. 백엔드의 비활성 스테이징 import(`com.zoop.graph.importer`)는 이 HTTP 읽기를 호출하지 않고 설치된 CLI를 직접 실행하며, 이 HTTP는 변경되지 않았습니다. 활성화·관리 API는 여전히 없습니다.

| 요청 | scope | 의미 |
|---|---|---|
| `GET /internal/v1/graph-handoffs/{handoffId}` | `handoff.read` | 이번 요청에서 검증한 **내용 없는** 상태: 신원·`state`·`delivery`·(current일 때만) `verification{manifestDigest,bundleDigest,contentDigest,bundleBytes,counts,sources,provenance}` |
| `GET /internal/v1/graph-handoffs/{handoffId}/bundle` | `handoff.read` | 위 필드 + 두 pin이 맞는 current일 때만 **`manifest`(동결된 manifest 본문)와 `bundle` 전체**. withheld·status에는 `manifest`가 없습니다. 쿼리 파라미터는 허용되지 않음(422) |

- `handoffId`: `^[A-Za-z0-9._:-]{1,200}$`. 정본은 생성된 [`docs/api/internal-ai-openapi.yaml`](../../docs/api/internal-ai-openapi.yaml)(`.json`)이며 예시는 생산자의 id 공식·digest를 실제로 계산한 완전한 합성 bundle입니다. 서비스 설명은 [ai/service README](../../ai/service/README.md#ai-handoff-bundle-읽기-internalv1graph-handoffs).
- 응답은 항상 `publication:"not-published"`, `appImport:"pending"`이며 bundle의 `readiness`는 그대로 `import-pending`입니다. `current`는 "이번 요청 순간의 AI 측 검증"이지 앱의 활성·공개 근거가 아닙니다.

## 인증·설정 파일 (선택한 이름)

| 대상 | 이름 | 설명 |
|---|---|---|
| 요청 | `Authorization: Bearer <토큰>` | 운영자 발급. principal에 scope **`handoff.read`**(다른 scope로는 불가, 반대로 `graph.read`로 이 경로 불가). 서비스는 토큰의 sha256만 `ZOOP_AI_SERVICE_PRINCIPALS`에 보관 |
| 서버 allowlist | `ZOOP_AI_SERVICE_HANDOFF_EXPORTS` → 예: `handoff-exports.json` | `{"schemaVersion":"zoop-ai-handoff-exports-1","handoffs":[{"principal":"app-backend","handoffId":"…","manifestDigest":"<64hex>","bundleDigest":"<64hex>"}]}`. **두 pin 모두 필수**. 운영자가 새 handoff마다 갱신(요청마다 다시 읽음) |
| 운영자 파일(매니페스트가 sha256으로 고정) | `ZOOP_AI_SERVICE_HANDOFF_CANONICAL`/`_DECISIONS`/`_BINDINGS` → 예: `canonical.json`·`decisions.json`·`bindings.json` | 호출자가 고를 수 없음. 바뀌면 withheld(`canonical_mapping_changed`·`decisions_changed`·`bindings_changed`) |
| 원장·원천 | `ZOOP_AI_HANDOFF_STATE_DIR`·`ZOOP_AI_HANDOFF_{RELATION,EXTRACTION,INGESTION}_STATE_DIR`·`ZOOP_AI_SERVICE_HANDOFF_SOURCES`·`ZOOP_AI_SERVICE_HANDOFF_COMMAND` | 10개 모두 있어야 켜짐(일부만 있으면 시작 거부). 없으면 두 route 모두 409 `execution_unavailable` |

pin을 얻는 방법: 운영자가 `zoop-ai-handoff freeze` 뒤 receipt의 `manifestDigest`·`bundleDigest`를 위 allowlist에 적습니다. 백엔드는 handoff id를 **조회·나열할 수 없습니다**(목록 route 없음): id와 pin은 운영 절차로 전달받습니다.

**한 응답으로 manifest+bundle 검증.** `/bundle`의 current 응답은 `manifest`와 `bundle`을 함께 줍니다. 백엔드는 응답만으로 다음을 재계산합니다(Python `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)`와 같은 정규 JSON, JS도 동일 결과):

1. `sha256(canonical(manifest)) == verification.manifestDigest == bundle.manifestDigest == allowlist의 manifestDigest`
2. `sha256(canonical(bundle)) == verification.bundleDigest == allowlist의 bundleDigest`
3. `manifest.handoffId == bundle.handoffId`, `manifest.sourceKind == bundle.provenance.declaredSourceKind`, `manifest.policyVersion == bundle.policy.version`, `manifest.files == bundle.policy.files`, `manifest.sources[]` 핀 집합 == `bundle.sources[]`의 `{relation, upstream, reviewDigest}` 집합.

`manifest`는 **freeze 때 원장에 저장된 원래 요청**(`{schemaVersion, handoffId, sourceKind, policyVersion, sources[{relation{jobId,inputDigest}, upstream{jobId,inputDigest,digest}, reviewDigest}], files{canonical,decisions,bindings}}`)이며 오늘의 설정·파일로 다시 만들지 않습니다. 서버가 만든 sha256 핀만 있고 파일 경로·비밀은 없습니다. 서비스는 digest·handoffId·선언·정책 버전·파일 해시·source 핀 중 하나라도 어긋나면 500 `runtime_binding_mismatch`, manifest 누락·알 수 없는 필드는 500 `runtime_contract_mismatch`로 거절하고 내용은 주지 않습니다. 생산자도 export마다 저장된 manifest가 저장 digest와 bundle의 `manifestDigest`에 맞는지 확인하며, 손상되면 `handoff_artifact_invalid`입니다. bundle 바이트는 변하지 않습니다(manifest는 응답의 별도 형제 필드).

## 백엔드가 알아야 할 것 (caveat)

1. **withheld·오류는 "데이터 없음"이 아닙니다.** `delivery.state="withheld"`(200, `verification`·`bundle`=null, 사유 코드만), 503, 500, 404, 403을 빈 그래프·빈 import로 해석하거나 캐시하지 마세요. 사유 코드는 모르는 값이 올 수 있으며 모르면 "withheld(원인 불명)"입니다.
2. **오류 매핑:** 403 `handoff_not_allowed`(없는 id·다른 principal·pin 미등록 모두 같은 답), 404 `handoff_not_found`(allowlist에는 있으나 원장에 없음: 운영 설정 오류), 409 `execution_unavailable`(그룹 꺼짐), 422(쿼리·id 형식), 503 `runtime_busy`/`runtime_unavailable`/`service_busy`/`service_configuration_invalid`(`Retry-After`, 같은 요청 재시도 가능), 500 `runtime_contract_mismatch`/`runtime_binding_mismatch`(재시도해도 같음: 운영자·계약 확인). 동시 child는 2개이고 child당 deadline 45초이므로 클라이언트 타임아웃은 그 이상으로, 재시도는 backoff로 하세요.
3. **digest를 직접 확인하세요.** `verification.bundleDigest`는 `bundle`의 canonical JSON(키 정렬, `,`·`:` 구분자, 비ASCII 비이스케이프) UTF-8 바이트 sha256이며 운영자 pin과 같습니다. 숫자는 음이 아닌 정수뿐, 키는 ASCII뿐이라 **JSON 파서로 읽은 뒤 같은 규칙으로 다시 직렬화해도 같은 digest**입니다(JavaScript로 재계산해 확인). 필드를 정규화·삭제·추가한 뒤에 해시하지 말고, 서비스가 추가한 키(`appImport`·`delivery`·`verification`·`observedAt`)는 `bundle` 안에 없습니다.
4. **모르는 필드는 거부됩니다.** 서비스는 bundle을 모든 수준에서 닫힌 모델로 검증하므로 생산자가 키를 추가하면 서비스·OpenAPI·이 문서가 함께 바뀌기 전까지 500 `runtime_contract_mismatch`입니다(digest와 pin을 새 내용에 맞춰도 마찬가지). Java DTO도 모르는 필드를 허용하지 않는 쪽(`FAIL_ON_UNKNOWN_PROPERTIES`)을 권합니다.
5. **크기.** bundle 상한은 canonical 6 MiB입니다. 응답은 약 7 MiB까지 가능하므로 클라이언트 읽기 상한은 8 MiB 이상(권장 16 MiB)으로 두세요. 서비스는 잘라 보내지 않습니다.
6. **검사 시각.** 권한·운영자 파일·pin 검사는 서로 다른 순간의 읽기이고 이미 나간 내용은 회수되지 않습니다. 앱 import·스냅샷 생성·활성화 직전에 이 상태 route(또는 bundle route)를 **다시 호출**해 `current`와 같은 digest를 확인하세요.
7. **source 유래 값은 데이터입니다.** 제목·URL·label·관측·grant 메타데이터·`sourceKind` 선언은 권한·공개 가능의 근거가 아닙니다(`declaredSourceKind`는 생산자가 관측한 값과 같을 때만 생산됩니다). `actual` 선언도 앱의 공개 정책을 대체하지 않습니다.
8. **`provenance`·`readiness`를 보존하세요.** `STRUCTURALLY_RELATED_TO`는 `manual-operator-review`/`operator-asserted`(AI_ALLOW가 **아님**), geography는 `operator-field-verdict`, `FOLLOWS`는 S2 비교+운영자 결정입니다. 공개 표기·수용은 백엔드 결정 사항입니다.
9. **구조 검증만 서비스가 확인합니다.** 키 집합·타입·패턴·크기 한도는 서비스가, 참조 닫힘·id 공식·개수·권한 같은 의미 규칙은 생산자가 쓰기 전과 매 export마다 확인합니다. 앱 텍스트·카탈로그와의 일치는 여전히 백엔드 몫(`appImportPending`)입니다.

## PR #189 계약과의 차이 (AI 구현 기준)

PR #189의 확정 사항(§0)은 방향이 같습니다: AI 인계 ID≠앱 `graphVersion`, 앱 수입 → 검증 → 등록 → **별도 활성화**, 인계 묶음은 manifest 고정·digest·충돌은 덮어쓰지 않음. 아래는 **문서와 AI 구현이 다른 부분**이며 어느 쪽도 조용히 바꾸지 않았습니다.

| 주제 | PR #189 | AI handoff 구현 | 결정 필요 |
|---|---|---|---|
| 인계 경로 | "인계 계약 v1은 서진님 작성 대기", 현재 전체 export 없음(§1 구현 범위) | `zoop-ai-handoff` + 위 HTTP로 manifest 고정·전체 내용·digest 제공(`main` 병합, 배포 없음) | 백엔드가 이 읽기 HTTP를 수입 경로로 채택할지, 파일 전달로 할지(로컬 스테이징 import는 HTTP가 아니라 설치된 CLI를 직접 실행하므로 이 결정과 별개) |
| manifest | manifest(원천 작업·input digest·원천/검수 revision·canonical 매핑·정책 버전) + 내용 | **`/bundle` 응답의 `manifest`가 동결된 manifest 본문**(위 형식)이며 `sha256(canonical(manifest))`가 `manifestDigest`와 같습니다. bundle에도 `manifestDigest`, `sources[]`, `policy.files`, `policy.version`이 그대로 있습니다 | 없음(스키마는 생성된 OpenAPI의 `HandoffManifest`) |
| 표시 ID와 AI ID | 앱이 공개 표시 ID(간선·evidence·graph version)를 결정 | bundle의 `issues[].id`·`companies[].id`·`relations[].id`·`evidence[].id`는 **AI handoff 계약의 ID**(원천 ID 보존)이며 **앱 표시 ID와 같다고 주장하지 않습니다**. 앱 importer는 `(type, source, target)`으로 묶고 `basis`·`evidenceIds`·`sourceRefs`를 합집합하되 사실을 조용히 버리지 않습니다. 실제 공개 ID의 바이트 정의는 백엔드 계약이며 여기서 바꾸지 않습니다 | 백엔드의 공개 ID 계산·매핑 |
| 표시 간선 ID | `edge-`+SHA-256(`relationType`,source,target) (§0) | `INVOLVES`·`FOLLOWS`는 `edge-`+digest(`{type,source,target}`), **`STRUCTURALLY_RELATED_TO`는 preimage에 `basis`(관계 키 목록)가 포함**됨. 동일한 구성요소라도 정규 JSON·키 이름 등 바이트 정의가 합의되기 전에는 공개 표시 ID와 같다고 보장하지 않음. 원천 관계 id는 `sourceRefs[]`/`basis[].sourceRelation`(`rc-…`) | 앱의 표시 간선 ID 계산·그룹핑과 AI 인계 관계 ID를 구분하고, 통일하려면 preimage까지 함께 확정 |
| evidence ID | 앱이 결정적 규칙으로 `ev-`(64hex) 발급, AI id는 매핑용 | AI는 `ev-`+digest(`{kind:"graph-body-span",articleId,articleVersion,start,end}`)를 **제안**하고 `source.sourceEvidenceId`(S2 `ev-`+32hex)를 매핑용으로 따로 둠 | 앱이 제안 id를 그대로 채택할지 별도 발급할지 |
| geography | "AI가 근거와 판정 정책 버전 제공" | **운영자 field verdict**(`verification:"operator-field-verdict"`, 국가 집합과 근거 span에 결속)이며 AI가 자동 검증하지 않음. 근거 없거나 충돌하면 `exclusions`(`geography_unproven`) | 공개 수용 정책 |
| 구조 간선 | "구조 근거 경로와 적용 여부가 **검증된** 경우만" | 적용성은 **운영자 수동 단언**(`operator-asserted`, `s3SemanticValidation:"none"`). S3 결과·verifier가 만든 것이 아니며 AI_ALLOW로 표기하지 않음 | 수동 단언의 공개 수용·표기 |
| `FOLLOWS` | 검증된 선후 관계 | S2 replay 비교 + 운영자 결정 + 증거 게이트(`exact-source-citation-in-incoming-article`), independent verifier 없음 | verifier 필요 여부 |
| revision | 앱 revision·AI 원천/검수 revision·writer 적용 결과를 합치지 않음 | bundle은 AI 쪽만 담음: 원천별 `reviewDigest`·사용한 `reviewUsed[(relationCandidateId, revision)]`. 앱 revision·writer 결과 없음 | 필드 이름 합의(PR #189는 "필드 이름은 인계 계약 v1") |
| 작업 연결 키 | `analysisJobId+unitKey ↔ aiJobId`, `aiAttemptId`, `commandKey`(회신 없음) | **제공하지 않음.** bundle은 AI job id만 가짐 | 키 전달 방식 |
| asOf | 두 단계(버전 선택 + 버전 안 필터) | 시각을 따로 보존(`publishedAt`·`observations[].observedAt`·`eventTime`+`timePrecision`·`validFrom/Until`·`verifiedAt`). 공개 시각·활성화 이력 없음 | 정책은 백엔드(AI는 제안만, 현재 공개 구현 없음) |
| 철회 신호 | 전체 공개 제외 목록·철회 완료 신호 없음 | 여전히 없음. 현재 권한 철회는 export가 **withheld**로 돌려줄 뿐(전달 차단), 앱이 받은 내용은 회수되지 않음 | 철회 완료 신호 형식 |
| 상태 | `ready+current`를 `reflected`/active로 자동 변환 금지 | `appImport:"pending"`·`readiness.app:"import-pending"`·`graphDb:"none"`. `GraphDb*` 값은 생산자 없음 | — |

PR #189의 사용자 결정은 팀 설계 기록으로 읽었고, 원격 문서·공개 OpenAPI·백엔드 코드를 이 작업에서 수정하지 않았습니다.

## 시험·명령 (로컬)

```sh
make service-test                                  # 시험 소유 stand-in 명령: tests/test_handoff_{unit,http}.py
make service-pipeline-test                         # 실제 zoop-ai-handoff + 두 S3 job 세계: pipeline_tests/test_handoff_real_cli.py
make service-handoff-smoke                         # 종단 smoke (Neo4j 불필요, pipeline 설치 없으면 실패)
ai/service/.venv/bin/python ai/service/scripts/export_openapi.py [--check]   # docs/api/internal-ai-openapi.{json,yaml} 재생성/확인
```

2026-10-16 Main 실행: 서비스 전체 870개 중 최초 869개가 통과했고, 나머지 1개는 두 번째 handoff의 응답·digest가 첫 번째 것을 가리키던 시험 fixture를 고친 뒤 단독 재실행해 통과했습니다(서비스의 결속 검사는 유지). 설치된 실제 pipeline 통합 시험 115개, 내부 OpenAPI 재생성 일치 검사, 실제 HTTP→CLI handoff smoke도 통과했습니다. smoke는 두 원천 작업의 bundle이 CLI·생산자 검증기·JS canonical digest와 일치함을 확인했고, 권한 철회·pin 불일치·busy·동시 호출 제한·deadline·중첩 필드 위조·정보 노출을 검사했습니다. 원천 원장은 변경되지 않았고 provider/model 호출은 0이었습니다. `public-check`는 생성물 275개 drift 0·hard error 0·문서 시험 21개 통과이며 기존 경고는 보존했습니다. 운영 인증·TLS·실제 데이터 규모·Spring 소비자·앱 import는 검증되지 않았습니다.

후속 manifest 본문 인계 검증: producer handoff 시험은 최초 101개 통과 후 손상 주입 fixture의 보호 trigger를 시험용 DB에서만 해제해 나머지 1개도 통과했습니다. HTTP handoff 단위·실제 HTTP·실제 CLI 통합 시험 238개와 OpenAPI 일치 검사, 전체 HTTP smoke가 통과했습니다. 응답 하나에서 frozen manifest와 bundle의 digest를 각각 재계산하고 source/file pin이 맞는지 확인하며, 바뀐 pin·빠진 manifest는 내용을 반환하지 않습니다. 기존 bundle artifact bytes는 바꾸지 않았습니다.

## 2026-10-17 로컬 스테이징 검증

- Java `test assemble`: 전체 640개 중 606개 통과·34개 제외, 실패 0. 별도 PostgreSQL importer 통합 시험 9개 통과.
- 실제 설치된 AI CLI → Spring 실행 jar → 임시 PostgreSQL → 공개 그래프 HTTP 경로의 smoke 13단계 통과: 원문 3건, 근거 6개, handoff 2개를 비활성 버전 2개로 등록했습니다. 활성화 쓰기는 0건이며 기존 기본·asOf 그래프는 계속 조회되고, 새 비활성 버전 직접 조회는 409 `VERSION_UNAVAILABLE`입니다.
- 동일 입력 재실행은 행·파일을 바꾸지 않았고, 잘못된 pin·저장 권리 누락·원천 권한 철회는 거절됐습니다. AI 원장의 바이트·권한·수정 시각은 유지됐습니다.
- 검토에서 발견한 앱 문서 상태 변경 경합, 미검증 근거 재사용, 응답 유실 후 재시도 시 가변 기업 표시값에 따른 파일 충돌은 회귀 3개가 실패하는 것을 확인한 뒤 수정했습니다. PostgreSQL 시험은 문서 행 잠금과 동시 철회 직렬화도 확인했습니다.
- 공급자·모델 호출 0건. 임시 DB 컨테이너는 제거했습니다. 실제 뉴스·운영 권한·AWS·공개 활성화·PR #217의 스냅샷 형식 3 연동은 이 결과에 포함되지 않습니다.

## 2026-10-18 마감: CI 검증 경로 연결(로컬, 미게시)

`make api-graph-handoff-import-smoke`를 추가하고 기존 CI `api` job에 연결했습니다. 기존 PostgreSQL 서비스 안에 전용 빈 `zoop_graph_import_smoke` DB를 만들며, 회사·인증 통합 시험의 DB와 분리합니다. 새 job·외부 서비스·모델 키는 추가하지 않았고, 기존 `companyIntegrationTest`의 graph-postgres 시험도 유지합니다. 설치·빌드는 smoke가 자동으로 수행하지 않으므로 [api README](../README.md)의 선행 명령과 환경변수를 사용하세요.

새 Make 명령으로 실제 CLI·jar·PostgreSQL·HTTP smoke 13단계를 다시 통과했습니다. workflow YAML·고정 action 입력·Bash 문법 검사와 저장소 도구 시험 42개도 통과했습니다. 임시 컨테이너는 제거했습니다. 로컬 DB는 PostgreSQL 17이며 CI의 PostgreSQL 16.13 및 GitHub runner에서의 실행은 아직 확인하지 않았습니다. 원격 CI 통과나 배포 완료를 뜻하지 않습니다.

2026-10-20: PR #217 병합 후 main의 스냅샷 형식 3과 FS042 유효기간(끝 포함)에 맞춰 수입기와 smoke를 갱신했습니다(로컬 작업 트리, 미게시). 문서가 같은 로컬 mentionId를 쓰는 정상 입력은 기사 id·버전·원천 mentionId로 결정적 앱 ID를 만들어 구분하고, 원래 ID는 receipt에 보존합니다. 카탈로그 변경과 수입의 경합은 트랜잭션 시작 시 companies SHARE 잠금으로 직렬화합니다.

검증 결과: pipeline 674개 통과, Java 681개 중 647개 통과·34개 제외 및 빌드 성공, 새 PostgreSQL DB의 통합 시험 40개 통과. 실제 CLI→Spring→PostgreSQL→HTTP smoke 14단계에서 비활성 버전 3개 등록, 다문서 로컬 ID 중복의 정상 수입·대표 언급 선택·동일 바이트 재시도, 기존 공개 조회 유지와 비활성 버전 409를 확인했습니다. AI CLI·handoff HTTP smoke도 통과했고 원장 불변·모델/공급자 호출 0을 확인했습니다. 종료일 포함 회귀 2개, 카탈로그 경합 3개, 언급 ID 회귀 6개는 수정 전 실패를 관측했습니다. 사용했던 DB로 전체 통합 시험을 다시 실행했을 때 기존 카탈로그 건수 기대치가 실패했으며, 새 전용 DB에서 40개가 통과했습니다. 임시 DB 컨테이너는 제거했습니다.

PR #229의 이전 커밋 b593226은 원격 CI 9개를 통과했습니다([실행 기록](https://github.com/Donbug/zoop/actions/runs/39044477309)). 위 최신 main 통합 변경은 아직 원격에 게시하지 않았습니다. 2026-10-17·10-18의 검증 기록은 형식 1·끝 제외 규칙 시점의 이력이며, 공개 활성화·graph 근거 조회·철회 처리는 여전히 후속 범위입니다.

## 2026-10-20: bundle `-2`의 원본 mention (로컬 작업 트리, 미게시)

bundle 스키마만 `zoop-graph-handoff-bundle-1` → `-2`로 한 번에 바꿨습니다(manifest·runtime `zoop-ai-handoff-1`, 원장, 정책 `zoop-public-projection-policy-1`, 서비스 `zoop-ai-internal-handoff-1`, import 요청·receipt `zoop-graph-handoff-import-1`/`-receipt-1`, snapshot 형식 3은 그대로). 각 issue에 닫힌 `mentions[]`가 추가되었고(위 표) 앱 verifier는 생산자 검증을 그대로 이식합니다: 식별자 partition(`mentions` = `sourceEvents`), 문서 버전의 기사 하나에 닫힘, mention 근거는 자기 기사의 근거 행, 이슈 `evidenceIds` = mention 근거 ∪ geography 근거, `verification:"none"`, `background`는 실제 bool, 회사 참조는 bundle `companies[]`와 `sourceCompanyId`, 시간은 `HandoffTime.mentionEventTime`(위 문법, `temporal_unsupported`).

**BE가 지금 받는 값.** mention별 원본 S2 값(제목·행위·대상·시각과 정밀도·기간·assertion 상태·background), 참가자의 원본 `sourceCompanyId`·`name`·`role` 텍스트와 (조건부) 공개 `companyId`, mention 자신의 인용 근거 id, mention이 속한 기사 `articleId`/`articleVersion`. 이 값들은 receipt의 완전한 bundle에만 남고 snapshot(형식 3)·공개 읽기는 그대로입니다: snapshot의 mention 참조는 여전히 `{mentionId(앱 id), articleId, articleVersion}`이며 `-2`에서는 모든 mention의 기사가 이슈 근거로 인용되므로 참조가 모든 mention을 덮습니다. 앱 mention id `mention-sha256({articleId, articleVersion, sourceMentionId})`와 같은 local id의 두 문서 매핑은 변하지 않았습니다.

**아직 생산되지 않는 값(없는 것을 만들어 채우지 않습니다).** 어떤 필드도 검증·결정·승인되지 않았습니다. `publisher`, `fieldDecisions`, `sourceSupport`, `approval`, impact·lineage 계열, 확인된 참가자 역할(`roleUnconfirmed` 같은 필드도 없고 `role`을 어떻게 쓸지는 백엔드 소유자가 정합니다), S3가 검증한 참가 관계는 `INVOLVES` relation에만 있습니다. 공개 `EventDetail` endpoint와 OpenAPI 대상 계약은 바뀌지 않았습니다. 이 변경은 `getEvidence`의 graph 본문 근거 경로도 바꾸지 않습니다.

**이전 산출물.** `-1` export는 `BUNDLE_INVALID`로 거절되고(아무것도 쓰지 않음), 생산자가 `handoff_contract_changed`로 withheld한 이전 handoff는 `HANDOFF_WITHHELD`로 응답합니다(새 handoff id를 freeze해야 함). 이미 import된 버전은 건드리지 않습니다: snapshot 형식 3은 그대로 읽히고 receipt reader(`GraphReceiptGrants`)는 스키마와 무관하게 `bundle.articles[]`만 읽으므로 `-1` receipt의 `getEvidence` 읽기도 유지됩니다(receipt를 새 검증기로 다시 검증하지 않음). 이후 receipt의 mention을 읽는 코드는 `receipt.bundle.schemaVersion`을 먼저 확인해야 하며 `-1`의 mention 값은 **없음**입니다(빈 값도, 이슈 필드 복사도 아님).

**검증(이 절 작성 시점).** Java 시험·smoke는 이 변경에서 실행하지 않았습니다. 시험 fixture와 `src/test/resources/graph-handoff/*.json`은 생산자 변경 뒤 `graph_handoff_smoke.py --write-fixture`로 다시 만들어야 하며(이전 fixture는 `-1` 모양이라 새 verifier가 거절합니다), 그 전의 실패는 이 때문입니다.

## 2026-10-20: `getEvidence`의 graph 본문 근거 경로 (로컬 작업 트리, 미게시)

공개 `GET /api/v1/evidence/{id}`가 스테이징된 graph 본문 근거를 **기존 경로·기존 응답 스키마 그대로** 읽습니다. 위의 "getEvidence graph 경로 없음"·"미등록 취급" 서술(지금 상태, 근거 표, 소유 경계, 앱 import 3번, 미결정 계약)은 이 절로 대체됩니다. OpenAPI·DB 스키마·snapshot 형식은 바뀌지 않았고, 이 경로는 활성화·쓰기·잠금·Neo4j·AI CLI 호출을 하지 않습니다.

**권한 선택(정세빈 확인 대기).** 이 읽기의 권한은 operator의 S2-1 source registry(`zoop-ingestion-s2-1`, handoff import가 `zoop-ai-ingest export --require-store`로 확인하는 바로 그 파일)이며, 요청마다 새로 읽는 엄격한 Java reader(`SourceRegistry`)로 판정합니다. 이 선택은 사용자가 로컬 구현으로 승인한 것이고 `GRAPH_READ_HANDOFF.md`가 이 경로를 백엔드(정세빈) 몫으로 둔 만큼 **백엔드 소유자 확인 전에는 배포하지 않습니다**(승인된 것으로 쓰지 않았습니다). S1 grant registry(`zoop-ai-s1-1`)는 이 경로에서 읽지도 쓰지도 않으며 purpose·recipient 인자도 없습니다.

**분기.** 저장된 evidence 행의 검증 artifact가 graph import `verification_receipt`이면 graph 경로, 그 외는 S1 경로입니다. 요청 파라미터로 고르지 않습니다. S1 행은 이전과 같고(`graphVersion`·`asOf`는 S1 registry를 읽기 전 409, 핀 없는 읽기는 S1 grant 필요) 달라지는 순서는 둘입니다. (1) 행 조회가 S1 registry 읽기보다 먼저라 모르는 id는 S1 grant가 없어도 404 `RESOURCE_NOT_FOUND`입니다. (2) `graphVersion`·`asOf`가 있어도 id 형식이 잘못되었거나 행이 없으면 409 대신 404입니다(`round`는 여전히 DB 조회 전 409). 전면 호환을 주장하지 않습니다.

**graph 경로 순서.**

1. 공개 `PublicGraphReader.read(null, graphVersion, asOf)`로 버전을 고정합니다(selector의 409/422, snapshot 저장소의 503은 그대로). staged(한 번도 활성화되지 않은) 버전은 409이고 fallback도 활성화도 없습니다.
2. 가시성: 필터된 snapshot의 evidence 목록에 있고 **보이는 issue(`evidenceIds`·`geographyEvidenceIds`) 또는 보이는 relation이 인용**해야 합니다. 아니면 404 `EVIDENCE_UNAVAILABLE`. `eventIds`는 그 id를 인용하는 보이는 issue입니다.
3. span `(articleId, articleVersion, start, end)`가 행과 같아야 하고, 현재 article이 `available`이며, 그 버전 행·텍스트 artifact가 행과 맞고, 인용 문자열의 코드 포인트 수가 offset과 맞아야 합니다. 버전은 snapshot이 고정하므로 `current_version`은 요구하지 않습니다.
4. **선택된 버전의** receipt(`artifact-receipt-<versionId>`, 행 자신의 receipt가 아님: 행을 공유한 뒤의 import는 첫 import의 receipt를 가리킵니다)를 등록된 해시·크기로 검증해 읽습니다. 파일 불일치·등록 없음·종류 오류는 404, artifact root 미설정·I/O 실패는 503입니다. 스키마 `zoop-graph-handoff-import-receipt-1`, `"gv-"+sha256(handoffId)==versionId`, 해당 article 버전이 `bundle.articles[]`에 정확히 하나, 각 observation의 `sourceId`가 `articles.provider`와 같음을 요구하고 `(sourceId, grantId, revision)` pin을 얻습니다. 형식이 맞지 않으면 fail closed(404)입니다. receipt는 pin만 줄 뿐 권한을 주지 않습니다.
5. **현재** source registry에서 모든 pin이 통과해야 합니다: source 존재, grant id·revision 일치, enabled, rights=known, 비어 있지 않은 evidence, `read`·`store`·`quote-display` 허용, **지금** 만료되지 않음(`asOf`는 권한 시계를 옮기지 않음). `model-send`는 요구하지 않습니다(인용 표시는 모델에 보내지 않음). registry 미설정·읽기 불가·검증 실패는 503, 거절은 404이며 사유는 로그에만 남습니다.
6. `companyId`는 증거 판정 뒤 확인합니다(모르는 id 404 `RESOURCE_NOT_FOUND`, 알면 `partial=true`와 sentiment 실패 구역·`sentiment=null`).

**200 응답.** `metadata.source=public_graph_snapshot`, `asOf`·`graphVersion`은 실제 선택 결과, `partial`은 `companyId`가 있을 때만 true, `quoteVerified=true`, `documentVersion=articleVersion`. `documentSummary`·`analysisStatus`·`analysisProvenance`·`resultVersion`은 `null`입니다(S1 요약은 S1 권한이 필요해 지어내지 않습니다). 이 경로는 EventDetail의 mentions·fieldDecisions·sourceSupport·publisher 계열(#64)이나 impact 경로(#65·#66)를 만들거나 열었다고 주장하지 않습니다.

**설정.** `ZOOP_DOCUMENT_READ_INGESTION_SOURCES`(= `zoop.document-read.ingestion-sources`)는 operator가 import와 **같은 파일**(`ZOOP_INGESTION_SOURCES`)로 지정합니다. 기본값·S1 fallback·운영 플래그 의존이 없고 미설정이면 graph 근거 읽기는 503입니다. 정규화된 절대 경로의 기존 파일이 아니면 기동 실패(값은 메시지에 없음). receipt를 읽으려면 `ZOOP_DOCUMENT_READ_ARTIFACT_ROOT`도 필요합니다.

**source registry 파일 경계.** 운영자만 `ZOOP_DOCUMENT_READ_INGESTION_SOURCES`의 파일과 상위 디렉터리를 바꿀 수 있어야 하고, 웹 프로세스에는 파일 읽기 권한만 부여합니다. 운영자는 쓰기 가능한 전용 디렉터리에서 완성된 일반 파일을 만든 뒤 같은 디렉터리의 `sources.json`으로 원자적으로 교체합니다. 기존 파일을 FIFO·장치로 바꾸거나 symlink를 끼워 넣지 않습니다. reader는 매 요청에 경로의 symlink·파일 종류·크기를 확인하고, POSIX 파일 속성이 있으면 그룹/기타 쓰기 권한도 거절합니다. 지원하는 파일시스템에서는 디렉터리 핸들에 상대적인 `NOFOLLOW_LINKS` 순회를 사용하지만, 현재 macOS JDK는 이를 제공하지 않아 일반 경로 검사 후 다시 엽니다. Java의 이 파일 읽기에는 원자적인 비차단 열기·열린 파일 종류 확인이 없어, 파일이나 상위 디렉터리를 동시에 교체할 수 있는 권한 있는 로컬 공격자까지 막는다고 주장하지 않습니다. POSIX 속성을 제공하지 않는 환경이나 공유 임시 디렉터리 아래에 놓는 경우에도 운영자가 상위 경로의 소유권과 교체 권한을 통제해야 합니다(스티키 디렉터리는 그 아래 운영자 소유 항목을 다른 사용자가 교체할 수 없어야 함). reader는 권한을 수정하지 않고, 읽기·검증 실패는 파일 내용이나 경로를 응답에 담지 않고 503으로 처리합니다.

**한계.** source registry의 scope만 제거하는 철회는 이미 노출된 근거를 막지 못합니다(scope pin이 handoff에 없음): grant를 disable하거나 revision을 바꾸거나 operation을 빼야 합니다. 공개 제외 overlay는 아직 `NONE`(FS081)이고 공개 활성화 기능이 없어 운영 환경에서는 어떤 버전도 읽히지 않습니다. 요청마다 registry·snapshot·receipt를 읽고 캐시하지 않습니다.

**검증.** `EvidenceServiceTest`·`GraphEvidenceServiceTest`·`GraphEvidenceSnapshotReaderTest`·`SourceRegistryTest`·`DocumentReadPropertiesTest`(단위), `make api-graph-handoff-import-smoke`(실제 jar·PostgreSQL·HTTP; 기본으로 evidence 읽기 단계 포함, `--no-with-evidence-read`로 끔). 이 smoke는 **시험 harness 전용** psql 활성화 1건(`harnessActivations: 1`; import의 `importActivationsWritten: 0`과 별개, production 게시 아님)을 격리 DB에서 수행한 뒤 공유 행·나중 receipt, 권한 변경별 CLI parity(`read`/`store`/`quote-display` 제거, disabled, rights, 빈 evidence, 만료, revision·grant id 변경, `model-send` 대조), 과거 `asOf`+현재 권한, registry 변조·삭제 503, receipt 변조·비공개 article 404, 읽기 전용(표·artifact 트리 불변)을 확인합니다.
