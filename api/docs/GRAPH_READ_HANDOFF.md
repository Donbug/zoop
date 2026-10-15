# 그래프 읽기 인수 문서 (정세빈 · 앱 상태·공개 조회용)

Spring 백엔드에서 내부 AI 서비스의 그래프 조회 API 두 개를 연결할 때 참고하는 문서입니다. 요청·응답, 오류 처리, 현재 구현 범위와 백엔드 연결 시 확인할 사항을 정리했습니다. 기계 판독 계약은 [`internal-ai-openapi.json`](../../docs/api/internal-ai-openapi.json)의 `graph-versions` 태그이며, 서버 설정은 [AI 서비스 README](../../ai/service/README.md#그래프-버전-읽기-internalv1graph-versions)를 참고하세요.

## 지금 상태 (사실)

- **비공개·미게시·미활성입니다.** 내부 서비스(`127.0.0.1`, 앞단 TLS 프록시는 미배포)의 읽기 전용 API입니다. 공개 `/api/v1/graph`·`/api/v1/admin/graph/versions`는 구현하지 않으며 **활성 버전 포인터도 없습니다.** 응답의 `publication`은 항상 `not-published`입니다. `delivery.state=current`는 “이번 요청에서 검증됨”이지 “앱이 보여 주는 활성 버전”이 아닙니다. 게시·활성화(FS059)·전체 철회(FS081)는 이번 작업에 포함되지 않았습니다.
- **Java 클라이언트는 아직 없습니다**(`api/src`에 Neo4j·GraphDB 클라이언트·`CompanyIssueCountQuery` 구현 없음, `EvidenceService`는 `graphVersion` null·고정 읽기 `VERSION_UNAVAILABLE`). 이 문서는 클라이언트를 만들 때의 계약입니다. 기본 꺼져 있고 서버 설정 그룹이 있어야 켜집니다(꺼져 있으면 인증 뒤 409 `execution_unavailable`).
- 운영자가 버전을 만들고 서버 allowlist에 올립니다. 앱·이 서비스는 버전을 **만들거나 찾거나 나열하지 못합니다**(목록 라우트 없음).
- 실제 로컬 HTTP 서버 → 설치된 graph CLI → 격리된 Neo4j 5.26 경로의 smoke를 통과했습니다. 1~3홉·권한 분리·digest 불일치·원천 권한 철회·canonical 변경·그래프 변조·원장 잠금·시간 초과를 확인했습니다. 원천 원장 변경과 모델 호출은 없었습니다. **로컬 검증이며 커밋·원격 CI·배포는 아직 하지 않았습니다.**

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
- 앱 활성 포인터(`/api/v1/admin/graph/versions/{id}/activate`)·공개 `/api/v1/graph` 질의·`CompanyIssueCountQuery` 구현은 이 서비스가 제공하지 않습니다.
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
