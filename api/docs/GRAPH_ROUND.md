# 그래프 정기 회차 (#55, WBS 6.5.4) — 앱 쪽 상태·수입 bridge·관리자 읽기

공개 그래프를 30분 회차마다 자동으로 갱신하는 작업의 **앱(api) 쪽 첫 조각**입니다. 이 문서는 2026-10-29 PR-R1 범위를 설명합니다: 회차 상태 테이블, 웹 애플리케이션 안의 수입 bridge, 관리자 회차 읽기. 회차 스케줄러 본체(AI `round-runs`·`round-handoffs` 호출, `analyze_plan` 접수, 단계 전진)와 retry·수동 시작은 AI 쪽 #387 ①②③이 나온 뒤 PR-R2에서 붙습니다. 그 전까지 이 조각은 **기본 꺼짐**이고 켜도 스스로 아무것도 시작하지 않습니다.

전제(바뀌지 않는 것): API와 AI는 별도 Task이고 공유 디스크가 없으며 Spring은 AI CLI를 실행하지 않습니다. 회차 스케줄러는 앱 쪽 하나입니다. 묶음 1개 = 비활성 버전 1개이고, 활성화는 자동 활성화 스케줄러(FS059)나 관리자가 합니다. 수입은 publication lock을 잡지 않습니다.

## 회차 한 바퀴

```
slot 도래 → R1 round-run 요청 → R2 계획 조회 → R3 analyze_plan 접수 → R4 분석 완료 대기
         → R5 freeze 요청 → R6 handoff 조회 → R7 수입(이 문서의 bridge) → R8 활성화(자동 활성화 스케줄러)
```

행의 `stage`는 `scheduled → run_requested → plan_ready → analysis_queued → analysis_done → freeze_requested → handoff_ready → imported` 순으로 전진하고, `skipped`(새 자료 없음, 또는 더 새로운 회차가 이미 수입됨)와 `failed`(사유 코드)로 끝날 수 있습니다. 같은 핀의 재수입(`unchanged`)은 `imported`입니다. **실패한 회차는 roundId를 유지한 채 멈춘 단계부터 재시도**합니다. AI 쪽 멱등 키가 roundId에 묶여 있고, AI는 "결과 불명 상태를 지우고 다음 회차에서 재전송하는 방식"을 받지 않기 때문입니다. 다음 슬롯은 실패와 무관하게 새 회차로 시작합니다(결정 D-R4).

## 상태 저장 (`V20261029170000__create_graph_rounds.sql`)

| 테이블 | 내용 |
|---|---|
| `graph_rounds` | 슬롯당 1행(`round_id = round-yyyyMMdd'T'HHmm` KST, `slot_at` UNIQUE). 단계, 계획(`plan_id`·`plan_digest`), `analysis_job_id`(FK `analysis_jobs`), handoff(`handoff_id`·두 digest), `graph_version_id`·`activated_version_id`(FK `graph_versions`, **ON DELETE SET NULL**: 보존 정책이 옛 버전을 지워도 회차 행은 남는다), `failure_code`(failed일 때만, CHECK), `attempts`·`next_attempt_at`(대기 단계의 backoff), `lease_owner`·`lease_until`(인스턴스 둘일 때의 lease, 둘 다 있거나 둘 다 없음), `started_by`(`system:scheduler` 또는 `admin:<id>`) |
| `graph_round_events` | 회차의 시도마다 1행(append-only): `stage`, `outcome`(advanced·waiting·failed·retried·skipped), `code`, `request_id`(외부 호출의 `X-Request-ID`), `detail` jsonb(코드·digest만, 8 KiB 이내) |

trigger로 `graph_rounds`는 DELETE와 식별 열(`round_id`·`slot_at`·`started_by`·`created_at`) 변경을 거절하고, `graph_round_events`는 UPDATE·DELETE를 거절합니다. 두 표는 영구 보존입니다(회차 단위 감사 이력). 시험은 TRUNCATE로 정리합니다.

`JdbcGraphRoundRepository`(`com.zoop.graph.round`)는 짧은 트랜잭션만 씁니다: `claim`(lease를 잡아야 외부 호출을 한다. 같은 owner는 갱신, 다른 owner는 lease 만료 뒤에만), `advance`(행 변경 + 이벤트 추가를 한 트랜잭션에), `due`(미완료·다음 시도 시각이 지난 회차, 오래된 슬롯부터), `page`(관리자 목록, 최신 슬롯부터), `newestImported`(수입 순서 보호의 기준).

## 수입 bridge (R7, `GraphRoundImportBridge`)

운영자 명령(`GraphHandoffRunner`, 비웹)이 쓰는 **같은** `GraphHandoffImporter`를 웹 애플리케이션 안에서 호출합니다(결정 D-R1 a안). 바뀌는 것은 입력·출력뿐입니다.

- 입력: 회차 행의 `handoff_id`·`manifest_digest`·`bundle_digest`가 요청의 핀이 되고, `operator`는 `zoop.graph.round.operator`(기본 `scheduler`, 운영자 요청과 같은 알파벳 → `created_by=operator:scheduler`)입니다. 회차 행의 `started_by`는 이와 별개로 `system:scheduler`입니다. handoff는 ai/service의 읽기 전용 HTTP(`zoop.ai.handoff-read-client`, `handoff-source=http`와 같은 `HttpHandoffSource`)로 받습니다.
- 출력: 결과 파일 대신 회차 행과 이벤트에 기록합니다. `staged`/`unchanged` → `imported`(+`graph_version_id`, 이벤트 code `staged`|`unchanged`). 활성화는 자동 활성화 스케줄러가 다음 tick에 가져갑니다.
- **수입 순서 보호** (`skipped_superseded`): 가장 최근 `imported` 회차보다 **오래된** 슬롯은 읽지도 않고 `skipped`로 끝냅니다. 자동 활성화가 commit 순(`sequence`)으로 고르므로 뒤늦게 수입된 옛 회차가 공개되는 일을 막습니다. 누적 묶음 계약(A안)에서는 최신 회차가 이전 내용을 포함하므로 손실이 없습니다.
- 일시 실패는 기다립니다: `import_busy`(다른 수입·운영자 명령이 artifact store lock 보유) → `busy-retry-after`(기본 5분), `handoff_export_unavailable`·`ingestion_export_unavailable`·`database_unavailable`·`artifact_store_unavailable` → `wait-retry-after`(기본 1분). `max-attempts-per-stage`(기본 20)에 이르면 `failed(import_timeout)`.
- 그 밖의 실패(`handoff_withheld`·`handoff_refused`·`pin_mismatch`·`bundle_invalid`·`rights_changed`·`version_conflict` 등)는 `failed(import:<code>)`이고 이벤트 `detail`에 생산자 코드·관측 번호만 남깁니다.
- 호출 스레드에서 동기로 돕니다(스케줄러 전용 스레드, 요청 스레드 아님). 수입 트랜잭션은 `companies` SHARE lock과 묶음 기사 행 lock을 commit 직전 재확인(관측별 `require-store`)까지 잡으므로, 그 기사에 닿는 활성화·철회는 수입이 끝날 때까지 기다립니다.

## 설정 (`zoop.graph.round.*`, 웹 애플리케이션 전용, 기본 꺼짐)

| 환경 변수 | 뜻 |
|---|---|
| `ZOOP_GRAPH_ROUND_ENABLED` | `true`면 bridge를 등록합니다(이 릴리스에서는 호출자가 없으므로 설정 검증만 효과가 있습니다). 비웹 실행에서는 무시 |
| `ZOOP_GRAPH_ROUND_OPERATOR` | 수입 요청의 `operator`(기본 `scheduler`, 운영자 요청 알파벳 `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`). 회차의 `started_by`와는 별개 |
| `ZOOP_GRAPH_ROUND_WAIT_RETRY_AFTER` / `BUSY_RETRY_AFTER` | 대기 단계 재시도 간격(기본 `PT1M` / `PT5M`) |
| `ZOOP_GRAPH_ROUND_MAX_ATTEMPTS_PER_STAGE` | 단계당 시도 상한(기본 20) |
| `ZOOP_GRAPH_ROUND_IMPORT_SOURCE` | 관측 재확인 방식. `cli`(기본): 설치된 `zoop-ai-ingest export --require-store`를 실행(로컬·단일 인스턴스 운영만 가능. API 컨테이너 이미지에는 CLI가 없음). `http`는 AI 쪽 관측 export route(#387 ③)가 생길 때까지 **기동 거절** |
| `ZOOP_GRAPH_ROUND_INGESTION_CLI` / `INGESTION_STATE_DIR` / `INGESTION_SOURCES` | `import-source=cli`일 때 필수(실행 파일·디렉터리·파일, 정규화된 절대 경로) |

켜면 다음도 요구합니다(아니면 설정 이름을 담은 메시지로 기동 거절): `ZOOP_GRAPH_SNAPSHOT_SOURCE=artifact`와 존재하는 `ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT`(bridge가 올린 버전을 같은 프로세스의 자동 활성화가 읽어야 하므로 **같은 root**에 씁니다. `fixture`는 seeder가 활성화하므로 거절), `ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED=true`. 운영자 명령의 `ZOOP_GRAPH_HANDOFF_IMPORT_*`·`ZOOP_ARTIFACT_ROOT`와는 별개 설정이며, 둘이 같은 root를 가리키면 lock으로 서로 `import_busy`가 됩니다.

**배포 제약.** artifact store는 로컬 POSIX 디스크 전용(0600/0700, 단일 소유자)이라 웹 인스턴스가 둘 이상이면 한쪽이 쓴 스냅샷을 다른 쪽이 읽지 못합니다. 단일 인스턴스, 공유 POSIX 디스크(uid 매핑), 객체 저장소 전환 중 하나를 Infra가 정해야 합니다(결정 D-I1). ECS에서 bridge를 켜려면 관측 export HTTP(A-5)가 먼저 필요합니다.

## 관리자 읽기 (A-ADM-03)

| operation | 경로 | 내용 |
|---|---|---|
| `getPipelineOverview` 확장 | `GET /api/v1/admin/pipeline/overview` | `rounds` 섹션 추가(additive): `enabled`·`nextSlotAt`·`lastTickAt`(스케줄러 없으면 false·null), `openRounds`, 최근 회차 10개 |
| `listGraphRounds` | `GET /api/v1/admin/pipeline/rounds?stage&cursor&limit` | 최신 슬롯부터, `stage` 필터(단계 wire 값), 불투명 커서(마지막 슬롯), limit 1~100(기본 20) |
| `getGraphRound` | `GET /api/v1/admin/pipeline/rounds/{roundId}` | 행 전체 + 이벤트 타임라인(코드·요청 ID·시각·detail). 모르는 id·형식 밖 id는 404 |

응답에는 경로·본문·비밀이 없습니다(행에 애초에 없습니다). `retryGraphRound`·`startGraphRound`는 OpenAPI에 함께 명세하되 구현은 PR-R2입니다(미구현 호출은 404).

## 시험

- `GraphRoundRepositoryPostgresTest`(`graph-postgres`): migration·제약·guard trigger, lease, advance+이벤트, due·page·newestImported.
- `GraphRoundImportBridgeTest`: staged→imported, unchanged, `skipped_superseded`, withheld→failed, busy→waiting→`import_timeout`, 준비 안 된 회차 거절.
- `GraphRoundImportConfigurationTest`: 꺼짐·웹 전용·설정 닫힘(snapshot source, read client, CLI 경로, import-source, operator).
- `GraphRoundAdminServiceTest`: 목록 순서·필터·커서, 상세·타임라인·404, overview 섹션.
- `PipelineOverviewPostgresTest`(`auth-postgres`): 기존 검사 + `rounds` 섹션이 직렬화됨.

## 다음 (PR-R2, AI #387 뒤)

`RoundRunClient`·`RoundHandoffClient`(HTTP), 관측 export HTTP(`import-source=http`), `GraphRoundScheduler`·`GraphRoundWorker`(lease·backoff·기동 검사, system 감사 메서드로 `analyze_plan` 접수, 실패 회차 재개, 큐 대기 지표), `retryGraphRound`·`startGraphRound`, bindings 전달. 버전 보존·정리 명령은 PR-R3.
