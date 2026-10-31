# ai/pipeline — 일회성 문서 수집·S2-1 원문 준비(공개 의존성만)와 S2-2 / S3 오프라인 프로세스, S4 읽기 전용 의존 대상 조회

| 명령 | 모듈 | wire schema | 상태 파일 |
| --- | --- | --- | --- |
| `zoop-ai-collect run` | `zoop_ai_pipeline.collection_cli` | `zoop-collection-1` (policy `zoop-collection-policy-1`) | 상태 DB 없음. source `inputRoot/collections/<collectionId>/`에만 원본 bytes·receipt·manifest를 쓴다 |
| `zoop-ai-collector {run,checkpoint,restore,status}` | `zoop_ai_pipeline.collector_cli` | checkpoint manifest `zoop-collector-checkpoint-1` | 컨테이너 수집 entry. 아래 비공개 뉴스·Korea 코퍼스·official source 수집을 한 controller로 돌리고 `/var/lib/zoop-collector/{private,korea,official}` 상태를 S3 checkpoint로 보존한다. 계약·환경변수·종료 코드·SIGTERM 시간은 [`docs/development/collector-container.md`](../../docs/development/collector-container.md) |
| `zoop-ai-ingest {run,tick,resume,inspect,export}` | `zoop_ai_pipeline.ingestion_cli` | `zoop-ingestion-s2-1` | `ingestion.sqlite3` |
| `zoop-ai-extract {run,submit,enqueue-round,plan-round,resume,inspect,cancel}` | `zoop_ai_pipeline.extraction_cli` | `zoop-extraction-s2-2` | `extraction.sqlite3` (`plan-round`는 원장을 열지 않고 새 계획 디렉터리 하나만 씀) |
| `zoop-ai-relation {run,submit,inspect,resume,review,cancel,live-binding}` | `zoop_ai_pipeline.relation_cli` | `zoop-relation-s3` | `relation.sqlite3` |
| `zoop-ai-dependents` (하위 명령 없음, stdin 변경 1건) | `zoop_ai_pipeline.dependency_cli` | `zoop-dependency-s4` | 위 세 원장을 읽기 전용으로만 연다(쓰는 상태 파일 없음) |
| `zoop-ai-graph {init,freeze,project,recover,inspect,read,focus}` | `zoop_ai_pipeline.graph_projection_cli` | `zoop-graph-projection-1` (plan `zoop-graph-plan-2`) | `graph.sqlite3` + 이 원장 하나에 묶인 별도 Neo4j 5 database의 **비공개** version(공개 아님) |
| `zoop-ai-issue-summary {submit,run,resume,inspect,export,cancel,live-binding}` | `zoop_ai_pipeline.issue_summary_cli` | `zoop-issue-summary-1` (policy `zoop-issue-summary-policy-1`) | `issue-summary.sqlite3`; 위 세 원장과 운영자 파일을 읽기 전용으로만 열고 handoff·Neo4j·app은 쓰지 않음 |
| `zoop-ai-handoff {freeze,freeze-round,recover,inspect,export}` | `zoop_ai_pipeline.handoff_cli` | `zoop-ai-handoff-1` (bundle `zoop-graph-handoff-bundle-7`, 운영자 decisions `zoop-public-decisions-3`) | `handoff.sqlite3` + `bundles/<sha256>.json`; 위 세 원장을 읽기 전용으로만 열고(요약을 고정한 freeze만 `--issue-summary-state-dir`의 요약 원장도 읽기 전용) Neo4j는 쓰지 않음. `freeze-round`는 window로 좁힌 운영자 파일 두 개를 `--files-dir`에 설치 |
| `zoop-ai-handoff-exposure` | `zoop_ai_pipeline.handoff_exposure_cli` | `zoop-handoff-exposure-1` | handoff 원장·고정 artifact를 읽기만 함. 원천 변경 조회는 ingestion·extraction 원장도 읽으며 relation·Neo4j·앱 원장은 열지 않음 |

세 원장(ingestion/extraction/relation)은 서로의 디렉터리를 `--ingestion-state-dir`/`--extraction-state-dir` 경로로 읽기 전용으로 엽니다(그래서 한 프로젝트입니다). ingestion과 handoff·graph·dependents는 모델·provider 호출이 없고, S2·S3는 기본이 authored replay이며 명시적 live 게이트(`ZOOP_AI_PIPELINE_LIVE_ENABLED`, S1의 `ZOOP_AI_LIVE_ENABLED`와 별개)와 허용된 단계에서만 provider를 한 번씩 호출합니다. live 설정·예산·receipt·실패 코드는 [`docs/development/ai-runtime-setup.md`](../../docs/development/ai-runtime-setup.md)(§10)를 따르고, 모듈은 `live_runtime.py`(전송·binding·예산 gate; 오프라인 `python -m zoop_ai_pipeline.live_runtime binding|check`)·`live_prompts.py`·`live_jev.py`·`live_budget.py`입니다. 공개 route, 앱 문서 등록·게시, S1 DB 쓰기는 하지 않습니다. `zoop-ai-dependents`는 세 원장을 읽기만 하는 S4의 일부(영향 대상 조회)이며 철회·재생성은 하지 않습니다. `zoop-ai-graph`는 이들 위에서 **완료된 S3 job 하나**를 읽기 전용으로만 소비해 `graph.sqlite3`와 원장에 묶인 Neo4j 한 곳에만 쓰며(아래 절), 그 밖의 네트워크·모델·provider 호출은 없습니다. `zoop-ai-ingest export`는 기본으로 `read`·`quote-display`만 요구하며, 앱 문서 import처럼 내보낸 텍스트를 **저장**하는 소비자는 `--require-store`(export 전용)로 현재 grant의 `store`까지 요구합니다. 이 확인도 호출마다 현재 registry로 CLI 안에서 하며 소비자가 registry를 읽지 않습니다.

`zoop-ai-handoff`는 여러 S3 job과 S2 upstream을 운영자 manifest로 고정해 **공개 이슈 중심 handoff bundle**을 만듭니다. 앱 버전·활성화·공개 준비 완료가 아니며, export 직전에 모든 원천과 운영자 파일의 현재 권한·고정 hash를 다시 검사합니다. member 식별은 문서 ID·버전·정확한 관측까지 포함하고, 구조 basis의 유효기간 근거와 동일 문서의 모든 관측도 보존·대조합니다. 원장 소유권은 변경 전에 읽기 전용으로 검사합니다. 현재 CLI와 `ai/service`의 인증된 전체 bundle HTTP는 **frozen manifest 본문과 bundle을 함께** 반환하여 두 digest를 독립 검증할 수 있습니다. 계약·소유·앱 import·공개 수용의 잔여 조건은 [그래프 인수 문서](../../api/docs/GRAPH_READ_HANDOFF.md)를 따릅니다.

**원본 mention(bundle `-2`부터).** 각 이슈의 `mentions[]`는 그 이슈의 source event가 가리키는 S2 mention을 있는 그대로 담습니다. 신원은 (문서 ID, 문서 버전, 로컬 mention ID)이며(로컬 ID는 문서 버전 안에서만 유일), 앱 article·version은 운영자 binding에서 옵니다. 한 mention을 두 upstream(event candidate와 snapshot member)이 싣더라도 기록은 하나입니다. `title`·`action`·`target`·`eventTime`·`period`·`assertionStatus`·`background`와 참여자의 `sourceCompanyId`·`name`·`role`은 S2 후보/snapshot 값 그대로(순서 포함)이고 `verification`은 항상 `"none"`입니다. `timePrecision`은 형식으로만 계산하며 넓히지 않습니다. 참여자의 `companyId`는 이 mention을 싣는 **모든** upstream이 같은 공개 회사로 매핑하고 그 회사를 bundle이 `companies`로 게시할 때만 채우며, 아니면 null입니다(참여자 자체는 항상 보존; 역할은 확인된 역할도 `INVOLVES`도 아닙니다). mention의 `evidenceIds`는 그 mention 자신의 정확한 인용 근거이고 이슈의 `evidenceIds`는 mention 근거와 geography 근거의 합집합입니다. 같은 신원을 싣는 member들이 값을 다르게 말하면 `mention_values_conflict`, mention 시각을 추측 없이 분류할 수 없으면 `mention_event_time_unsupported`로 **이슈 전체**를 보이게 제외합니다(병합·마지막 값 우선 없음; `-1`이면 공개됐을 수 있는 이슈입니다). field decision·support·approval·publisher·impact 값은 만들지 않으며, source event·counts·digest 공식·`policy`는 `-1`과 같아 운영자 attestation digest가 그대로 유효합니다.

**이슈 필드 선택 근거(`fieldProvenance`, bundle `-3`에서 추가, `-4`에서 `withheld` 추가).** 각 이슈는 닫힌 `fieldProvenance`를 가집니다: `selection`, `verification`(항상 `"none"`), `withheld`(아래 verdict 문단), 그리고 여섯 머리 필드 `title`·`action`·`target`·`eventTime`·`period`·`assertionStatus`마다 `{documentId, documentVersion, mentionId}` 배열인 `sameValueMentions`. `selection`은 **이슈당 하나**이며, 운영자가 대표 mention(`representative`)을 골랐으면 `operator-representative`(모든 mention의 값이 같아도 마찬가지), 아니면 `unanimous`(모든 member가 같은 값)입니다. 운영자 결정이 대표 하나로 여섯 필드를 한꺼번에 정하므로 필드별 선택은 존재하지 않는 결정을 만들어 내기 때문입니다. 각 배열은 그 필드 값이 **선택된 원래 값**(대표의 값 또는 unanimous의 공통 값; verdict가 이슈 값을 null로 보류해도 가려진 null이 아님)과 **JSON으로 정확히 같은** 원본 mention을 `mentions[]`와 같은 순서로 모두 담습니다. `null`은 `null`하고만 같고, 공백 제거·대소문자 변환·시각 정규화가 없으며(`"2026-09-30"`과 `"2026-09-30T00:00+09:00"`은 다른 값), 같은 신원은 한 번만 나옵니다. 그래서 누락·중복·mention이 아닌 참조·순서 위반이 모두 거절됩니다. 배열은 비어 있을 수 없고(어느 mention도 진술하지 않는 값은 거절), `unanimous`이면 모든 배열이 모든 mention이며, `operator-representative`이면 대표 mention이 모든 배열에 있습니다. 이것은 **실제로 한 선택의 기록**이며 사실 확인·근거 지지·승인이 아닙니다. 목록에 오른 mention은 같은 문자열을 말한다는 뜻일 뿐이고(선택은 `fieldDecisions`로 매핑하지 않음), `timePrecision`은 `eventTime`에서 계산되는 값이고 geography는 이미 별도 `operator-field-verdict`가 있어 제외합니다. 생산자가 목록을 직접 만들기 때문에 위반은 새 제외 코드가 아니라 freeze 때의 `handoff_bundle_invalid`입니다. 독립 validator(`validate_bundle`)가 mention·verdict와 이슈 값만으로 같은 규칙을 다시 계산합니다. 바뀐 것은 bundle 스키마 문자열과 이 필드뿐입니다: manifest·runtime `zoop-ai-handoff-1`, 원장, `policy`, digest 공식(이미 `issues` 전체를 덮음), source event·counts는 그대로입니다.

**운영자 필드 verdict(bundle `-4`, decisions `zoop-public-decisions-2`).** S2/S3는 mention의 `eventTime`·`period`를 검증하지 않습니다. 그래서 선택(`fieldProvenance`)을 검증으로 읽지 않고, 운영자가 **원본 mention 하나의 값**에 내린 판정만 `fieldVerdicts`로 싣습니다. 운영자 파일의 `IssueDecision.fieldVerdicts`(필수, 비어도 됨, 최대 2000)는 항목마다 정확히 `documentId`·`documentVersion`·`mentionId`·`field`(`eventTime`|`period`)·`value`(검토한 정확한 문자열, null 불가)·`decision`(`ALLOW`|`HOLD`|`REJECT`)·`reasonCode`·`evidence`(span 0~20)·`reviewer`·`decisionRef`·`decisionVersion`입니다. 허용 조합은 `ALLOW/stated`(span ≥1), `HOLD/unstated`(span 0), `HOLD/ambiguous`(≥1), `REJECT/contradicted`(≥1)뿐이며 자유 서술 메모 키는 없습니다. 같은 (mention, field)의 중복이나 위 규칙 위반은 파일 전체가 `decisions_invalid`입니다(조용히 일부만 버리지 않음). 생산자는 verdict를 이슈에 묶을 때 그 mention이 이 이슈의 것인지(`field_verdict_unbound`), `value`가 mention의 현재 값과 **정확히** 같은지(`field_verdict_stale`, null 필드는 판정할 것이 없음), span이 그 mention 자신의 문서 버전에 있는지(`field_verdict_evidence_unbound`)와 오프셋·`quoteSha256`이 본문과 맞는지(`field_verdict_evidence_mismatch`)를 검사하고, 하나라도 어긋나면 **그 이슈만** 보이게 제외합니다(기존 geography와 같은 `Resolver.cite` 기구와 현재 권리 검사 사용). bundle에서는 `issues[].fieldVerdicts[]`가 `evidence` 대신 app 근거 `evidenceIds`(그 mention 자신의 article)와 `verification:"operator-field-verdict"`를 가지며 mention 식별자, 이어서 `eventTime`·`period` 순으로 정렬됩니다. 선택 근거(대표 mention, 또는 `unanimous`이면 모든 mention)에 있는 mention의 `HOLD`/`REJECT`는 이슈 머리 값을 **null로 보류**합니다(`eventTime`이면 `timePrecision:"unknown"`, 다른 mention 값으로 대체하지 않음). `fieldProvenance.withheld`가 그 필드를 정렬해 나열하고, `sameValueMentions`는 가려진 null이 아니라 **선택된 원래 값**과 비교합니다. 원본 mention 값은 그대로 남고, 대표가 아닌 mention의 `HOLD`/`REJECT`는 아무것도 보류하지 않으며, verdict가 없으면 값은 기존 그대로이며 검증됐다고 말하지 않습니다. 이슈 `evidenceIds`는 mention·geography·verdict 근거의 합집합입니다. 보류된 `eventTime`은 구조 관계의 입력이므로 기존 attestation은 `applicability_binding_mismatch`(상세의 `expectedBindingDigest`로 다시 검토)나 `basis_validity_unprovable`로 닫힙니다(`FOLLOWS`는 영향 없음). verdict는 해시로 고정되는 decisions 파일 안에 있으므로 바꾸면 `decisions_changed`로 기존 handoff가 withheld되고 새 handoffId·bundle이 필요합니다. 공개 `EventDetail`·`FieldDecisionOut` 모양은 바뀌지 않았고, 백엔드 매핑은 **권고**일 뿐 합의·구현되지 않았습니다(`candidateId: null`, `mentionId`는 앱 mention id, `outcomes[{field,decision,reason}]`, verdict가 없으면 `[]`는 "검증됨"이 아니라 "필드 verdict 없음"). 시연용 운영자 입력은 아래 합성 예시이며 실제 검토 결과가 아닙니다.

```json
{"canonicalId": "issue:supply", "publicId": "issue:supply-2026q3", "decisionRef": "issue-2026-10-16:supply", "geography": {"…": "…"}, "representative": {"…": "…"},
 "fieldVerdicts": [
  {"documentId": "doc-<64hex>", "documentVersion": "<64hex>", "mentionId": "m-a", "field": "period", "value": "2026Q3", "decision": "ALLOW", "reasonCode": "stated",
   "evidence": [{"documentId": "doc-<64hex>", "documentVersion": "<64hex>", "start": 8, "end": 16, "quoteSha256": "<64hex of the quoted text>"}],
   "reviewer": "reviewer-a", "decisionRef": "fverdict-2026-10-21:a-m-a-period", "decisionVersion": "fv1"},
  {"documentId": "doc-<64hex>", "documentVersion": "<64hex>", "mentionId": "m-a", "field": "eventTime", "value": "2026-09-30", "decision": "HOLD", "reasonCode": "unstated",
   "evidence": [], "reviewer": "reviewer-a", "decisionRef": "fverdict-2026-10-21:a-m-a-eventTime", "decisionVersion": "fv1"}]}
```

위는 **합성 예시**입니다(실제 값은 `graph_handoff_smoke.py`의 `verdict_cases`가 만드는 hand-authored 검토를 보십시오). 실제 검토 입력을 만드는 도구나 자동 생성 경로는 없으며 verdict를 선택·geography·모델 출력에서 유도하지 않습니다.

**승인 근거·실행 모드·출처 지원(bundle `-4`에서 같은 스키마 문자열로 확장, 현재 `-5`도 그대로 포함).** (1) **S3 승인 근거.** 각 `sources[].reviewUsed[]`는 `{relationCandidateId, revision, approvalBasis{kind, revision, reviewer, decidedAt}}`입니다(relation ID 오름차순). `kind`는 `automatic-verifier`(독립 verifier verdict, `reviewer=null`) 또는 `operator-final-approval`(HOLD에 대한 운영자 최종 승인, `reviewer`는 S3 review의 자유 문자열 1~200자)이고 `decidedAt`은 그 결정 이벤트의 `createdAt`(offset이 있는 ISO 시각, 정규화 없이 그대로)입니다. 생산자는 S3가 보고한 값을 믿지 않고 이력의 **마지막 이벤트**(자동은 eligible로 만든 verdict, 수동은 `approved` effect의 review `allow`, seq=revision)로 다시 증명하며 맞지 않으면 `relation_payload_invalid`입니다(자동으로 대체하거나 추정하지 않음). 이 값이 사본의 유일한 근거이고 edge는 `(jobId, relationCandidateId)`로 찾아봅니다. `INVOLVES.provenance.s3SemanticValidation`은 그 edge 뒤의 **모든** S3 relation이 자동일 때만 `independent-verifier-supported-all-claims`이고, 운영자 최종 승인이 **하나라도** 기여하면 `manual-operator-final-approval`입니다(모두 수동이라는 뜻이 아님). 구조 edge는 `origin: manual-operator-review`(운영자 적용성 주장)를 그대로 두고 `basisEligibility`만 같은 규칙으로 `s3-independent-verifier-supported-all-claims` | `s3-operator-final-approval`이 되며 `basis[].verifiedAt`은 그 basis relation의 `decidedAt`입니다. 사람의 승인은 자동 verifier의 모든 claim 지지를 주장하지 않습니다. export는 사용한 relation이 여전히 같은 eligible·revision·approvalBasis(종류·reviewer·시각)인지 매번 다시 증명하며 바뀌면 `review_revision_changed` withheld입니다. (2) **실행 모드.** `provenance.executionMode/recordingKind`는 `(replay, authored-test)` 또는 `(live, provider)` 둘뿐이고 `sources[].provenance{sourceKind, executionMode, recordingKind}`가 모두 같아야 합니다. S3 job과 그 S2 upstream, 그리고 bundle 안의 모든 source가 한 쌍이어야 하며 섞이면 첫 source의 값을 복사하지 않고 `provenance_mode_conflict`로 거절합니다. 자료 종류(`synthetic`/`actual`)는 모드와 독립이며 `observedSourceKind`가 선언과 같아야 합니다. (3) **출처 지원.** 운영자 decisions의 필수 `origins[]`(비어도 됨)는 `{documentId, documentVersion, originId, reviewer, decisionRef, decisionVersion}`를 문서 버전마다 하나 선언합니다(중복은 `decisions_invalid`, 쓰이지 않는 선언은 무시). origin은 **이것으로만** 정해지며 publisher·URL·호스트·`sourceId`·제목·raw hash에서 추정하지 않고, 선언이 없는 버전은 `unknown`입니다. `articles[]`는 `textSha256`(앱 binding이 증명한 정확한 본문 hash)과 `origin`(null 또는 `{originId, reviewer, decisionRef, decisionVersion, verification:"operator-declared-origin"}`)을 갖고, 각 이슈는 PoC `_source_support`를 순수 함수(`source_support.py`, PoC import 없음)로 옮긴 `sourceSupport{articleCount, knownLineageCount, unknownLineageArticles, independentSourceCount, duplicateGroups}`를 가집니다. 같은 origin이거나 본문이 **정확히 같은** 기사는 한 계보 그룹으로 합치고, `knownLineageCount`는 origin이 있는 그룹의 수(기사 수가 아님), `independentSourceCount`는 origin이 없는 기사가 있거나 한 그룹에 서로 다른 origin이 둘 이상이면 `null`, 아니면 `knownLineageCount`이며, `duplicateGroups`는 본문이 정확히 같은 기사 묶음(≥2, 연결 요소가 아님)입니다. 이슈가 같은 기사의 **두 버전 이상**을 인용하면 공개 기사 읽기에 버전이 없어 구분할 수 없으므로 `issue_article_versions_multiple`(상세 없음)로 그 이슈만 제외합니다. 앱 import는 `textSha256`이 실제 본문과 다르면 `TEXT_MISMATCH`로 거절하고 두 검증기가 `sourceSupport`를 다시 계산해 같아야 합니다. policy에 `sourceSupport: "origin-or-exact-text-union"`이 추가됐고 앱 snapshot 3·공개 API는 그대로입니다. 이 확장은 `-4`에 들어 있었고, `-4` 이하로 만든 handoff 원장 행은 현재(`-5`) 스키마가 아니므로 아래 ‘이전 bundle의 이력’ 규칙을 따릅니다.

**구조 경로(bundle `-5`, 운영자 decisions는 그대로 `zoop-public-decisions-2`).** 모든 relation에 `structuralPath`가 있습니다. `INVOLVES`·`FOLLOWS`는 항상 `null`이고, `STRUCTURALLY_RELATED_TO`는 운영자가 attest한 basis relation의 **순서 있는 회사 체인**입니다. 완전한 경로는 `{status: "complete", companyIds: [P, C] 또는 [P, M, C], links: [{supplierCompanyId, customerCompanyId}, …]}`입니다. P는 같은 이슈의 `INVOLVES` 참여자, C는 edge 대상(참여자가 아님)이고 모든 ID가 서로 다르며, `links`는 basis와 같은 순서로 basis 하나당 하나이고 각 link의 두 끝점은 `companyIds`의 인접한 둘입니다. 방향은 S3 `SUPPLIES`의 공급자→고객 방향 그대로이며(체인을 찾는 걷기만 무방향), 생산자는 `connected()`가 아니라 `chain()`이 돌려주는 정규(canonical) 체인을 보존해 회사 확정 뒤에 공개 ID로 바꿉니다. 중간 회사 M을 운영자가 `companies` 결정으로 매핑했는데 이 bundle이 `companies`로 게시하지 않으면, M은 최상위 `pathCompanies`에 **비공개 지원 참조**로만 실립니다(`companies`와 같은 닫힌 `{id, canonicalId, label, decisionRef}`, id 오름차순·유일, `companies`·`issues`와 서로소, 최대 20,000). 그래프 노드도, relation의 target도, mention 참여자의 `companyId`도 되지 않으며(참여자는 여전히 `companies`로만 풀립니다) `pathCompanies`는 완전한 2단계 경로의 중간 회사에서 `companies`를 뺀 집합과 **정확히** 같고 `counts.pathCompanies`와 content digest에 포함됩니다. 운영자가 매핑하지 않은 중간 회사는 공개 ID를 만들지 않고 `{status: "unavailable", reason: "intermediate_company_unmapped"}`이며 basis가 2개인 edge에만 허용됩니다(1단계 경로는 항상 완전). 경로를 자르거나 지어내지 않고, 기존 제외 코드와 edge ID 공식도 그대로입니다(`structuralPath`는 ID 입력이 아닙니다). 각 basis에는 `businessScope`·`productScope`(S3 값을 그대로 복사, null 가능, 최대 500 코드포인트)가 더해집니다. 둘은 엔티티 ID가 아니라 텍스트입니다. 이 경로는 **운영자가 매핑한 basis 체인**이지 인과나 가격 방향이 아니며, 매핑과 방향은 운영자가 attest한 값이고 export가 고정된 원천을 다시 확인할 뿐 독립 출처 증명이 아닙니다. 닫힌 validator(Python `validate_bundle`, Java verifier)가 모양·연결·참여자 시작·대상 비참여·카탈로그 폐쇄·개수를 강제합니다.

**이전 bundle의 이력.** 저장된 receipt의 `bundleSchema`가 현재 스키마가 아닌 행(`-1`: mention 이전, `-2`: `fieldProvenance` 이전, `-3`: 필드 verdict 이전, `-4`: 구조 경로 이전, `-5`: impact 행 이전, `-6`: 이슈 요약 이전)은 이력입니다. 운영자 파일·원천 원장·grant·artifact·쓰기 가능한 ledger에 손대기 **전에** 원장만 읽어 판별하고(각 `Handoff` 메서드가 잠금 아래에서 다시 확인), `inspect`는 저장된 상태·receipt·attempt와 `next: null`·`delivery: withheld/handoff_contract_changed`(artifact는 읽지 않음), `export`는 내용 없는 withheld, `recover`와 같은 ID의 `freeze`는 `handoff_contract_changed` 오류입니다. 행·attempt·artifact의 바이트와 권한은 바뀌지 않고 `recover`가 이 행을 `failed`로 만들지도 않으므로, 다시 만들려면 새 `handoffId`로 freeze합니다. 이미 받은 `-6` 이하 bundle 파일이나 `--verify-package`용 package도 같은 이유로 이력이 되므로 `make pipeline-handoff-package`로 새 package를 만듭니다. 이미 게시된 `-6` bundle과 그 이력의 모양은 바뀌지 않았고(`-6`을 조용히 고쳐 쓰지 않음) 이번 변경은 **새로 만드는 bundle만** `-7`로 올립니다. 운영자 decisions 파일도 `zoop-public-decisions-1`·`-2`는 `decisions_invalid`이므로 `-3`(이슈마다 `fieldVerdicts`와 `summary`, 둘 다 비어 있어도 필수이고 `summary`는 고정한 결과가 없으면 `null`)로 옮겨야 합니다. 새 ID는 같은 원장에서 정상 동작합니다. 이전 빌드를 이 원장에 실행하지 마십시오(옛 `recover`가 `-7` 행을 invalid로 판정합니다). 손으로 쓴 기대값과 설치된 CLI 확인은 `ai/pipeline/scripts/graph_handoff_smoke.py`가 맡습니다. 이 smoke는 `-6` ready·reserved 행, `-5` ready·reserved 행, `-4` ready·reserved·failed 행, `-3` ready·reserved 행, `-2` 행 셋(ready·reserved·failed)과 `-1` ready 행 하나를 실제 원장에 심어 위 이력 응답과 바이트·권한·mtime 불변을 확인하고, 구조 경로는 rel-a가 SYNTH-4→SYNTH-3 `SUPPLIES`도 갖는 `chain` 세계에서 게시된 중간(`known`)·비공개 중간(`private`)·매핑 없는 중간(`unmapped`)을 실제 CLI로 내보내 손으로 쓴 기대값과 대조합니다. `--write-fixture`는 mention·선택 근거·verdict·머리 값 기대값(`expected-mentions.json`·`expected-field-provenance.json`·`expected-field-verdicts.json`·`expected-headline-values.json`), verdict가 든 실제 export(`export-field-verdicts.json`, `export-field-verdicts-time.json`), verdict 규칙만 깨는 음성 bundle(`bundle-verdict-*.json`), 구조 경로의 실제 export(`export-path-known.json`·`export-path-private.json`·`export-path-unmapped.json`)와 규칙 하나만 깨는 음성 bundle(`bundle-path-NN.json`, 깨진 규칙·validator 위치는 `expected-structural-paths.json`), impact 세계의 실제 export(`export-impacts.json`·`export-approved.json`·astral 문자 길이 경계의 유효 export `export-impacts-unicode.json`), 모든 export의 impact 행 기대값과 규칙 하나만 깨는 음성 bundle 35개(`bundle-impact-NN.json`, 깨진 규칙·validator 위치는 `expected-impacts.json`), 이슈 요약 세계의 실제 export(`export-summary.json`: available 요약과 `temporal-review-pending`, `export-summary-withheld.json`: `verifier-hold`와 `not-requested`), 모든 export의 요약 기대값(`expected-summaries.json`)과 규칙 하나만 깨는 음성 bundle(`bundle-summary-NN.json`)과 이전 schema의 withheld 봉투(`export-withheld-legacy.json`)도 새 디렉터리에 씁니다. 기존 `export-valid.json`·`export-collision.json`은 verdict가 비어 있고 impact 행이 모두 `not-proposed`이며 요약이 모두 `not-requested`인 `-7`입니다.

**영향 행(`impacts`, bundle `-6`에서 추가, receipt 전용).** 방출된 모든 INVOLVES 간선의 `sourceRefs`마다 **정확히 한 행**(`(edgeId, jobId, relationCandidateId)` 정렬, 최대 10,000)을 둡니다. 같은 간선 뒤의 두 S3 relation은 한 행으로 합치지 않으며 긍정·부정이 함께 남고 간선 단위 라벨도 없습니다. 행은 S3 결과의 impact 단계가 말한 것 그대로의 13개 닫힌 키(`edgeId`·`issueId`·`companyId`·`sourceRelation`·`impactCandidateId`·`status`·`code`·`label`·`targetVerdict`·`effects`·`verifier`·`verifierRequestDigest`·`proposal`)이고 상태는 `not-applicable`(운영자 최종 승인 relation: S3가 호출하지 않았고 후보도 없음)·`not-proposed`(자동 relation에 대상 후보 없음)·`no-evidence`(인용 없음: 검증기를 부르지 않았으므로 라벨 없음)·`technical-reject`(`producer_reply_invalid`·`impact_precheck_rejected`·재생(replay) 전용 `verifier_reply_invalid`)·`verifier-reject`(대상 `contradicted`)·`verified`·`withheld`(`impact_evidence_outside_relation_documents`·`impact_quote_ambiguous`: 증거를 정확히 실을 수 없으면 일부로 라벨을 다시 계산하지 않고 비움)입니다. `verified` 행만 `label`·`targetVerdict`·`effects{positive,negative,neutral,uncertain}`(앱 `ev-` ID)를 갖고, 라벨은 검증기가 매핑한 효과에서만 결정적으로 계산됩니다(uncertain이 있거나 대상이 insufficient이면 `undetermined`, 아니면 positive만·negative만·둘 다=`mixed`). 호출된 verdict는 `impact_verifier_request`의 digest와 job에 묶인 impact policy 버전, 라벨을 다시 계산해 일치할 때만 받고, 어긋나거나 자동 relation의 마커 없음·verdict 없는 후보·대상 후보 중복·후보가 있는 수동 relation은 `relation_payload_invalid`로 freeze 전체가 실패합니다. S2 quote ID는 문서 version과 구간만의 hash라 한 문서로만 풀리는 인용에서만 쓰며(둘 이상이면 `impact_quote_ambiguous`), relation 자신의 인용 문서 밖이면 `impact_evidence_outside_relation_documents`입니다. 앱 evidence는 한 행의 증거가 모두 증명된 **뒤에만** bundle에 더해져 거절된 행이 임시 참조를 남기지 않습니다. 대상이 아닌 후보(모델이 만든 회사 ID)는 내보내지 않고 생산자의 `supporting`/`opposing` 묶음도 내보내지 않으며, `proposal`(방향·이유·한계)은 `verification: "none"`인 **검증되지 않은** 비공개 영수증 내용입니다(이유 ≤2000, 한계 ≤1000 **Unicode code point**). 검증기는 대상 회사 지지 여부와 인용문의 텍스트 효과만 증명하며 가격·확률·인과·근거 완전성은 증명하지 않고, replay 실행의 `verifier: called`는 작성된 fixture의 응답이지 독립 추론이 아닙니다. S3에는 영향 검증 시각이 없어 시각을 만들어 넣지 않습니다. 공개 집계 라벨이나 공개 영향 경로는 없습니다.

**이슈 요약(`issues[].summary`, bundle `-7`에서 추가, receipt 전용, decisions `zoop-public-decisions-3`).** 여러 기사에 걸친 이슈 요약 문장은 handoff가 만들지 않습니다. **별도 명령 `zoop-ai-issue-summary`**(자기 원장·자기 live binding family)가 이슈 하나의 입력 인용을 모델에 한 번 보내 생성하고 독립 verifier로 한 번 확인하며, 그 **불변 결과**를 operator decisions가 `IssueDecision.summary: {jobId, inputDigest, resultDigest}`로 이슈마다 고정합니다(`null`이면 고정 없음). `freeze`는 고정한 결과를 요약 원장에서 **읽기 전용**으로 가져와 bundle에 옮기고(`--issue-summary-state-dir`는 **freeze 전용이며 decisions가 요약을 고정했을 때만** 줍니다: 고정이 있는데 없으면 `issue_summary_state_missing`, 고정이 없는데 주면 `issue_summary_state_unused`), `export`는 freeze된 artifact에서 꺼내 현재 원천으로 입력 basis를 다시 계산해 비교합니다. 그래서 **freeze와 export는 모델·provider를 한 번도 부르지 않고**, export는 요약 원장·새 인자·요약 job 모듈 없이 동작하며 Java·`ai/service` export 인자도 그대로입니다. 원장의 `failed`(provider 결과 불명 등)는 고정할 수 없고, 실패한 job을 빈 요약으로 바꾸지 않습니다.

*이슈별 결정 순서(생산자 Planner가 정하고 Python validator와 Java verifier가 bundle만 보고 다시 계산).* ① 이슈의 `fieldVerdicts`에 `HOLD`/`REJECT`가 하나라도 있으면(대표 mention이 아니어도) 정확히 `{"status":"unavailable","code":"temporal-review-pending","source":null}`이고 **bundle 어디에도 그 이슈의 요약 문장이 없습니다**(`available`도 거절). ② 입력 인용이 60개(`MAX_QUOTES`, policy 문자열 `zoop-issue-summary-policy-1`의 일부)를 넘으면 `input-too-large`. ③ 그 밖에 decisions가 결과를 고정했으면 그 결과. ④ 아니면 `not-requested`. ①②④는 `source: null`이고 호출이 없습니다. 작업 쪽 unavailable은 `producer-invalid`·`verifier-hold`·`verifier-reject` 셋뿐이며 `source: {jobId, inputDigest, resultDigest, basisDigest}`로 결과를 가리킵니다(한글 음절이 없는 출력은 `producer-invalid`). 고정이 있는데 ①이나 ②가 해당되면 freeze 전체를 `issue_summary_temporal_review_pending`/`issue_summary_input_too_large`로 거절하고 조용히 무시하지 않습니다.

*basis(요약 입력의 고정).* `{policy, issueId, title, quotes:[{evidenceId, articleId, articleVersion, start, end, quoteSha256, context}], articles:[{articleId, articleVersion, documentId, documentVersion, textSha256}]}`. `quotes`는 이슈 `mentions[].evidenceIds`의 **합집합만**(evidenceId 순)이며 geography 근거나 verdict 근거만 있는 span은 넣지 않습니다. `context`는 그 인용을 단 mention이 **모두** `background: true`일 때만 `background`이고 아니면 `report`입니다. 기사 버전과 `quoteSha256`·`textSha256`이 정확히 고정되므로 이 모든 입력(인용되지 않은 것 포함)이 앱의 current-rights/asOf 가림 판단 입력입니다.

*available 객체(닫힌 키).* `{status, text, claims:[{claimId:"c1".., text, evidenceIds}], evidenceIds, generatedAt, resultVersion, language:"ko", source, producer{kind, model, reasoningEffort, promptVersion, schemaDigest, runtimeIdentity}, verifier{kind, model, adapterIdentity, requestDigest}}`. claim은 1~5개, 각 1~280 code point·줄바꿈 없음·한글 음절 1개 이상이고 `evidenceIds`는 1~5개의 정렬·유일 id이며 모두 basis 인용 안에 있어야 합니다. **claim이 인용하지 않은 basis 인용도 이 요약이 의존하는 입력입니다**(모델은 둘 다 봤고 `source.basisDigest`가 모두를 고정합니다). `text`는 claim 문장을 `"\n"`으로 이은 것, `evidenceIds`는 claim 근거의 정렬된 합집합, `resultVersion`은 `"isr-"+digest({basisDigest, claims})`(내용만의 함수, 시각·job id 아님), `generatedAt`은 요약 작업 시각이며 문법은 **하나**입니다: 대문자 `T`·`Z`, 초 필수, 소수 1~9자리(뒤의 0 허용), `Z` 또는 `±HH:MM`(시 ≤18, 18은 `:00`만), 실제 그레고리력 날짜, 윤초 없음. 생산자 `issue_summary_contracts.validate_generated_at`과 앱 Java `HandoffIssueSummary.generatedAt`이 공유 벡터 `api/src/test/resources/graph-handoff/summary-time-vectors.json`으로 같은 문자열을 받고 거절하며 라이브러리 파서(`fromisoformat`·`OffsetDateTime.parse`)는 기준이 아닙니다. 엔진은 `datetime.now(UTC).isoformat()` 모양(`YYYY-MM-DDTHH:MM:SS[.ffffff]+00:00`)만 만듭니다. `source.resultDigest`는 job 신원과 basis, `source`를 뺀 본문의 digest라서 문장·id·신원 어느 하나를 바꿔도 맞지 않습니다. `producer.kind`/`verifier.kind`는 bundle 실행 모드와 짝입니다: replay는 둘 다 `authored-replay`(model·reasoningEffort는 null, 작성된 fixture의 응답이지 독립 모델의 판단이 아님), live는 `provider`와 `independent-verifier`(모델 이름 필수). Python `validate_bundle`과 Java `HandoffBundleVerifier`가 같은 순수 규칙(`issue_summary_contracts.py` ↔ `HandoffIssueSummary.java`)으로 각각 다시 계산하며 위조된 문장·id·basis·시간 결과는 bundle 전체가 `handoff_bundle_invalid`/`BUNDLE_INVALID`입니다.

*freeze가 고정을 받아들이는 조건(모두 엄격 거절, 아무것도 쓰지 않음).* 요약 원장 행이 `ready`이고 핀의 (jobId, inputDigest, resultDigest)와 같음(`issue_summary_pin_mismatch`), 그 job이 이 **공개** 이슈를 요약했음, 이슈가 이번 freeze에서 공개됨(`issue_summary_issue_not_public`), 지금 다시 계산한 basis digest가 job의 것과 같음(`issue_summary_basis_changed`), job의 실행 모드·sourceKind가 bundle과 같음(`provenance_mode_conflict`/`provenance_conflict`). 권리는 새로 만들지 않고 기존 경로가 지킵니다: freeze·export 모두 모든 원천 문서를 현재 grant로 다시 읽고(`current()`), export는 freeze된 요약이 여전히 고정 결과이고 같은 basis에 의존하는지(`issue_summary_pin_mismatch`/`issue_summary_basis_changed` withheld)와 content digest가 같은지(`handoff_content_changed`)를 확인합니다.

*권리는 두 시점으로 나뉩니다.* 요약 입력의 **모델 전송 권리**(live)는 요약 job이 전송 직전·응답 수신 후·최종 완료 때만 확인합니다(그 뒤에 철회돼도 이미 끝난 결과를 소급해 모델 전송 위반으로 만들지 않으며 이 명령들도 다시 확인하지 않습니다). **이후의 전달**은 기존 S2/S3 결과와 같은 규칙으로 **현재 read·quote-display 권리**를 요구하고(앱 import의 store는 기존 import 규칙), 소급 모델 전송 검사가 아닙니다. 그래서 공개 CLI `zoop-ai-issue-summary inspect`·`export`는 `submit`·`run`·`resume`과 **같은 일곱 원천·운영자 파일 인자**(`--relation-state-dir`·`--extraction-state-dir`·`--ingestion-state-dir`·`--sources`·`--canonical`·`--decisions`·`--bindings`)가 필요하고, 원래 요청의 manifest를 지금 다시 읽어 원천·현재 권리·같은 basis가 더는 성립하지 않으면 요약 본문을 내지 않고 `delivery: {status: "withheld", code}`(종료 코드 2)와 job 메타데이터(신원·상태·사용량)만 남깁니다. 요약을 decisions에 고정하면 그 파일이 job manifest가 고정한 파일과 달라지므로 이후 그 job의 공개 `export`는 withheld입니다(고정할 pin 필드는 고정 **전**에 읽습니다). 내부 `issue_summary.load_result`는 원장만 읽는 handoff용 함수로 원천·권리를 보지 않으며(원천 독립), handoff `freeze`는 요약 job의 옛 manifest가 아니라 **자기 새 manifest**로 원천과 현재 권리를 다시 증명하고 **같은 basis digest**일 때만 고정을 받습니다.

*취소.* `zoop-ai-issue-summary cancel --state-dir D …`(기존 원장이 있어야 하며 원장을 만들지 않음)는 `queued`·`stopped` job만 `failed`(`job_cancelled`, 종료)로 만들어 그 입력이 차지하던 자리를 비우므로 현재 manifest로 같은 입력의 새 job을 낼 수 있습니다. 원천·키·모델은 건드리지 않고 저장된 receipt는 감사 기록으로 남으며, `ready`나 이미 `failed`인 job은 `job_already_terminal`로 거절합니다(고정할 결과를 지우는 취소는 없습니다).

*앱.* Java importer는 `-7`만 받아(`-6`은 `BUNDLE_INVALID`) 요약을 같은 규칙으로 다시 검증하고 **retained receipt에 그 객체 그대로** 보관합니다. 공개 graph snapshot(format 3)에는 싣지 않으며 공개 `getEvent`의 `summary` 매핑·asOf·현재 grant 가림은 BE 소유입니다(입력 basis **전체**가 보이고 읽을 수 있을 때만 `AnalysisSummary`, `temporal-review-pending`·작업 쪽 unavailable은 문장 없음, `-6` 이하 receipt는 요약이 생산된 적 없음). 이 문서는 PR #278의 소스를 바꾸지 않습니다. replay 실행은 작성된 fixture이며 실제 provider 호출·품질·임계값 보정은 검증하지 않았습니다.

판별은 세 갈래입니다. **증명된 없음/현재**(디렉터리·원장 파일이 없거나 행이 없거나 현재 스키마)일 때만 기존 쓰기 경로로 넘어가고, **이력**이면 읽기 전용 보기를 쓰며, **판단 불가**(writer 사용 중 `handoff_busy`, 낯선·손상된 namespace/원장, receipt에 schema 없음 `handoff_state_invalid`, 과대 파일)는 그 오류를 그대로 내고 쓰기 가능한 open으로 넘어가지 않습니다(쓰기 open은 권한 재설정·WAL checkpoint·DDL을 하므로 이력 원장을 바꿀 수 있습니다). writer가 죽어 비어 있지 않은 WAL에만 커밋된 행은 읽기 전용 immutable open에 보이지 않으므로, 소유를 먼저 증명한 뒤 shared lock 아래에서 원장 파일과 WAL을 128 MiB 한도로 임시 0700 디렉터리에 **복사**해 그 복사본만 SQLite로 엽니다(원본 파일·`-shm`·WAL·권한·mtime 불변, 임시 디렉터리는 닫을 때 삭제). 현재 스키마 행의 hot WAL 복구(`recover`)는 그대로 쓰기 경로이고 읽기 명령은 `handoff_recovery_required`를 냅니다.

복사 한도는 파일마다 **128 MiB**이며 원본이 일반 파일이 아니거나(심볼릭 링크 포함) 한도를 넘으면 잘라 읽지 않고 `handoff_state_invalid` 오류로 닫힙니다. 임시 디렉터리는 `mkdtemp`로 만든 0700 비공개 위치이고, 정상·오류 어느 경로에서도 보기를 닫을 때 삭제하며 원장 디렉터리 안에는 아무것도 만들지 않습니다.

**누적 window freeze (`zoop-ai-handoff freeze-round`, #407 A 방향: 번들 하나 = 비활성 앱 버전 하나).** 매 freeze마다 AI 원장에서 **S3 job window를 새로 계산**하고(직전 번들의 `sources[]`를 이어받지 않습니다), 운영자 master 파일을 그 window로 좁힌 뒤 기존 엄격한 `freeze`(재검증 전부 그대로)를 실행합니다. stdin은 읽지 않습니다.

```bash
zoop-ai-handoff freeze-round --state-dir HANDOFF --relation-state-dir … --extraction-state-dir … --ingestion-state-dir … --sources … \
  --canonical MASTER_CANONICAL --decisions MASTER_DECISIONS --bindings BINDINGS \
  --round-id ROUND [--plan-id s2plan-… --plan-root PLAN_ROOT] --files-dir INSTALLED [--issue-summary-state-dir SUMMARY] [--recovery-attempt-id ATTEMPT]
```

`--canonical`·`--decisions`는 이 명령에서 **운영자 master 파일(읽기 전용)**이고, window로 좁힌 파일은 `--files-dir`의 `canonical.json`·`decisions.json`으로 설치됩니다(이후 `export`에 주는 경로). **handoff가 `ready`일 때만** 각 파일을 원자적으로 교체하며, `reserved`·`failed` 결과나 거절에서는 이전 설치본을 유지합니다. `--files-dir`은 handoff 원장 디렉터리와 분리해야 하고, 두 설치 대상은 어느 master 파일과도 같을 수 없습니다. 경로 충돌과 설치 대상의 심볼릭 링크·일반 파일 여부는 **원장을 쓰기 모드로 열기 전에** 검사합니다. 새 설치본이 놓이면 직전 handoff의 `export`는 `decisions_changed` 등으로 withheld가 되고 새 번들이 그것을 대체합니다. 출력은 JSON 한 줄 `{schemaVersion, roundId, handoffId, freeze(기존 freeze 결과), selection, files, narrowing}`이며 오류 때는 기존 `{error:{code,detail}}`입니다. `--round-id`는 관측 회차(ingestion `roundId`), `--plan-id`/`--plan-root`는 그 회차의 `plan-round` 산출물(불변 plan 디렉터리)입니다. 새 plan이 없는 slot은 둘 다 생략해 **carry-only freeze**로 합니다. 경로 검사를 통과한 첫 호출은 빈 handoff 원장을 만들 수 있습니다. freeze가 예약 뒤 중단되면 `reserved` 행이 남으며 기존 `recover` 명령으로 정리합니다.

*선택 규칙(`handoff_round.py`, 원장 세 개·master registry·현재 전달 권한을 매번 다시 확인).*

| 단계 | 규칙 |
|---|---|
| 후보 | 상태 `ready`인 S3 job이면서 그 S2 upstream(`jobId`+`inputDigest`)에 master canonical 항목이 **하나 이상** 있고 round slot이 있는 것. `ready`이나 매핑 항목이 없으면 `awaiting_mapping`(window 자리를 쓰지 않음), 다른 상태는 `not_ready`(코드=상태), `cancelled`는 `cancelled` |
| 순서 | 그 S2 incoming 관측의 ingestion round의 slot(`window.through`) **내림차순**, 그다음 `sourceId`·`page`·`ordinal` 오름차순, 그다음 S3 `jobId`. 이 순서로 현재 delivery를 확인해 **전달 가능한 20개**(`MAX_SOURCES`)를 `selected`로 채웁니다. 20개를 채운 뒤 남은 후보는 `out_of_window`(`window_full`) |
| `neverFrozen` | `out_of_window`로 밀린 job이 이 원장의 어떤 `ready` handoff에도 고정된 적이 없으면 `true` |
| 자기 회차 gate | `--round-id`에 허용된 모든 S3 job(그 회차에서 관측한 S2 upstream을 쓴 job + plan의 모든 unit)이 `ready` 또는 `cancelled`일 때만 진행합니다. 아니면 `analysis_incomplete`(`detail.jobs[]`에 `{jobId, upstreamJobId, code}`; S3 job이 아직 없는 unit은 `relation_job_missing`)이고 아무것도 쓰지 않습니다. 이전 회차의 미완료 job은 기다리지 않고 `not_ready`로 보고하며, 완료된 뒤의 첫 freeze에서 window 안이면 들어옵니다 |
| slot 없음 | 매핑된 `ready` job의 round에 `window`가 없으면 그 job을 `unavailable`+`round_slot_unavailable`로 보고하고 제외합니다. 해당 job은 window 자리를 쓰지 않으며 나머지 후보를 계속 선택합니다 |
| `withheld` | 선택을 위해 확인한 job의 현재 delivery가 withheld(예: grant revision 변경)이면 그 job을 `withheld`와 원래 사유 코드로 보고하고 제외합니다. 해당 job은 window 자리를 쓰지 않으며, 다음 후보에서 전달 가능한 job을 채웁니다 |
| 그 밖의 거절 | 제외 후 전달 가능한 job이 0개면 `window_empty`(`detail.selection`에 job별 상태·사유 포함, 이전 번들·설치본 유지), plan이 다른 회차의 것이면 `plan_round_mismatch` |

`selection` 보고서(`zoop-ai-handoff-selection-1`)는 고려한 **모든** S3 job을 `{jobId, status(selected|not_ready|awaiting_mapping|withheld|unavailable|out_of_window|cancelled), code, roundId, sourceId, slot, page, ordinal, upstreamJobId[, neverFrozen]}`로 나열합니다(조용히 빠지는 job 없음). 기본 `handoffId`는 정렬한 manifest 내용(`sources`·좁힌 파일 hash·bindings hash)의 digest(`hr-<sha256>`)라서, window와 운영자 파일이 같으면 새 slot이어도 **같은 handoffId**이고 이미 있는 행을 그대로 돌려줍니다(window 밖의 미매핑 job이 늘어도 같음). 공개 ID(이슈 ID·`INVOLVES` 간선 ID·`ev-` ID)는 운영자 결정·앱 article binding·span에서만 나오므로 번들마다 같은 항목은 같은 ID입니다.

예약 뒤 중단된 handoff는 먼저 `zoop-ai-handoff recover --state-dir HANDOFF`의 stdin에 `{"schemaVersion":"zoop-ai-handoff-1","handoffId":"…"}`를 전달해 정리합니다. artifact가 없어 `failed`로 확정되면 운영자가 `freeze-round`에 **`--recovery-attempt-id ATTEMPT`를 명시**해 같은 입력으로 새 handoff를 만들 수 있습니다. 값은 `[A-Za-z0-9._:-]`의 1~200자이며, manifest 내용과 이 값을 함께 hash하여 새 ID를 정합니다. 같은 입력·같은 값으로 반복하면 회차가 바뀌어도 같은 행을 돌려줍니다. 옵션을 생략하면 원래 ID와 그 상태를 돌려주며, 기존 실패 행과 시도 기록은 그대로 보존합니다.

*운영자 파일 좁히기(기계적 선택만).* master의 항목을 **원문 그대로** 고릅니다(항목을 만들거나 고치지 않고, 선택된 항목의 바이트·공백·escape가 master 그대로입니다). registry는 window upstream의 항목만 남깁니다. decisions는 회사 결정 전부, window 안에 member가 하나라도 있는 이슈 결정(없는 이슈는 뺌), 그 이슈의 구조·FOLLOWS 결정(FOLLOWS는 두 이슈가 모두 남을 때), window 안 문서의 origin만 남깁니다. 남은 이슈의 `fieldVerdicts`에서는 window 밖 mention의 verdict를 빼고(안 그러면 그 이슈가 `field_verdict_unbound`로 제외됩니다), 다음 중 하나에 해당하는 이슈의 요약 고정(`summary`)은 `null`로 바꿉니다: 이슈가 이번 window에서 공개되지 않음(`issue_not_public`), 결정적 규칙(`temporal-review-pending`·`input-too-large`)이 요약을 정함, 요약의 basis가 바뀜(`issue_summary_basis_changed`). basis가 그대로인 고정은 얼려진 결과 그대로 유지합니다. 요약 고정이 모두 사라지면 `--issue-summary-state-dir`는 쓰이지 않고(`issue_summary_state_unused` 없이), 남아 있으면 기존대로 필요합니다. 그 밖의 불일치(잘못된 고정, 다른 mode 등)는 좁히지 않고 엄격한 freeze가 거절합니다. 요약 상태는 번들 `-7` 규칙 그대로입니다: 고정이 빠진 이슈는 `not-requested`, 결정적 규칙이 정하는 이슈는 `unavailable`+`temporal-review-pending`/`input-too-large`(스키마·verifier 변경 없음). 결과의 `narrowing`은 남긴 registry 항목 수, 남은·뺀 이슈, 뺀 verdict 수, 뺀 요약 고정(`{issueId, code}`)을 보고합니다. window가 바뀐 뒤 사람이 다시 확인해야 하는 것(대표 mention 재고정 `issue_representative_invalid`, 지리 근거 `geography_evidence_unbound`, 구조 적용성 `applicability_binding_mismatch`, FOLLOWS 근거 `follows_source_unpinned`)은 기존 규칙대로 번들 `exclusions`에 코드로 보이며 자동으로 고치지 않습니다. 새 job의 canonical 항목·이슈 결정은 운영자가 master에 넣어야 하고, 항목이 없는 job은 공개되지 않습니다.

*손실 없이 건너뛸 수 있는 조건.* 더 새 slot이 먼저 import된 뒤 옛 slot의 번들을 건너뛰어도 최종 공개 상태를 잃지 않는 것은 **세 조건이 모두 성립할 때만**입니다. **C1** 선택은 매 freeze마다 위 규칙으로 원장·master registry·현재 전달 권한을 다시 확인합니다(직전 번들에서 잇지 않음: 이어 받으면 새 slot이 먼저 얼 때 옛 job이 영영 빠집니다). **C2** 앱이 slot마다, 계획할 단위가 없는 slot에도 freeze를 요청합니다(늦게 끝난 job과 매핑·결정 변경이 한 slot 안에 반영되도록). **C3** 아직 어떤 `ready` handoff에도 들어가지 못한 job이 있는 가장 오래된 회차부터 지금까지의 **slot이 있고 매핑·현재 전달 권한을 충족하는 job이 20개 이하**입니다. 넘으면 가장 오래된 job이 공개된 적 없이 밀려나며 `out_of_window`+`neverFrozen`으로 **보고**됩니다(조용한 손실 없음). slot이 없거나 현재 전달이 withheld인 job은 각 사유가 해소된 뒤의 freeze에서 다시 선택 대상이 됩니다. 세 조건 밖에서는 중간 버전을 건너뛴 결과가 최종 공개 상태에서 달라질 수 있습니다.

이 명령은 HTTP `round-handoffs` 조정(#387: 앱이 roundId·planId만 넘기고, 자기 회차 gate·설치 순서·권한 allowlist를 서버가 수행)을 구현하지 않고 그 아래의 라이브러리·CLI 계층입니다. 모델·provider·네트워크 호출은 없습니다. 검증은 `tests/test_handoff_round.py`(실제 ingestion→S2→S3 authored-replay 원장).

**의존성.** 전체 패키지(`zoop-ai-pipeline`)는 공개 패키지(pydantic 2.13.5·httpx 0.28.1·lxml 6.1.3·pypdf 6.19.0·neo4j 6.3.1)만 쓰며 collect·ingest·extract·relation·dependents·graph·issue-summary·handoff 명령 모두 **private PoC·git 인증·토큰 없이** 설치·실행됩니다. 원본 PoC(`investmate`)는 이 프로젝트의 어떤 소스·스크립트·시험에서도 import하지 않고 manifest·lock에도 없습니다(옛 `poc` extra, `poc_guard`, `pinned_poc_unavailable` 코드 제거). `prototype/bff`만 별도로 private PoC를 고정해 쓰며, CI에서 그 token을 쓰는 job은 `bff` 하나뿐입니다.

```bash
make pipeline-install   # uv sync --project ai/pipeline --frozen --group dev  (공개 의존성만, 토큰 불필요)
make pipeline-test      # ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests
make pipeline-smoke     # 수집·회차·추출·등록·관계·의존 조회·인계·이슈 요약 CLI 검사. 외부 모델 호출 없음; 요약 live 경로는 loopback 모의 서버만 사용
make pipeline-build
```

### Hacker News 외부 링크 발견 메타데이터

`zoop_ai_pipeline.hn_discovery_cli`는 **기사 본문이 아닌 링크 후보 메타데이터**만 저장하는 독립 명령입니다. [공식 HN API](https://github.com/HackerNews/API)의 고정 호스트 `https://hacker-news.firebaseio.com`에서 `newstories`·`topstories`·`beststories` 중 하나와 선택한 `item/<id>.json`만 읽습니다. 기사 링크, 댓글·사용자·프로필 API는 열지 않으며 native collection receipt, ingestion manifest, 그래프 import를 만들지 않습니다. API 소스 코드의 MIT 라이선스는 제출 제목이나 연결된 기사에 대한 포괄적 이용 허락이 아닙니다.

운영자 설정은 `zoop-hn-discovery-config-1`입니다. 아래 예시는 **외부 실행용 설정 형식**이며 실행 승인이나 수집 결과가 아닙니다. `feed`는 `new|top|best`, `limit`은 1~50이고 나머지 예산 필드도 모두 필수입니다. 요청은 1~52회, 응답은 최대 1 MB, 전체 응답은 최대 10 MB, 요청별 시간은 최대 300초, 전체 시간은 최대 3,600초로 제한됩니다. `minIntervalSeconds`는 최소 1초입니다. 요청 수·바이트에는 robots 조회도 포함되고, 바이트는 native fetcher가 읽은 응답 본문 기준입니다. `env`, 임의 endpoint, proxy, backend 키는 허용하지 않습니다.

전송 예산은 다음 요청과 응답 읽기를 중단하는 한도입니다. 길이 헤더가 없는 응답은 마지막 수신 chunk에서 한도를 넘을 수 있으므로 `sourceBytes`에는 한도로 잘라낸 값이 아니라 실제 읽은 바이트 수를 기록합니다. 이때도 `byte_budget`으로 중단하고 1 MB snapshot 파일 한도는 유지합니다.

```json
{
  "schemaVersion": "zoop-hn-discovery-config-1",
  "feed": "new",
  "limit": 20,
  "userAgent": "ZoopDiscovery/1.0",
  "timeoutSeconds": 15,
  "maxTotalSeconds": 120,
  "maxRequests": 22,
  "maxResponseBytes": 100000,
  "maxTotalBytes": 1000000,
  "minIntervalSeconds": 1.0
}
```

```bash
# 저장소 루트에서 실행합니다. output의 부모는 있어야 하며 output 자체는 새 외부 디렉터리여야 합니다.
ai/pipeline/.venv/bin/python -m zoop_ai_pipeline.hn_discovery_cli run \
  --config /absolute/path/hn-config.json --output /absolute/external/path/hn-discovery
ai/pipeline/.venv/bin/python -m zoop_ai_pipeline.hn_discovery_cli status \
  --config /absolute/path/hn-config.json --output /absolute/external/path/hn-discovery

# 아래 두 검사는 작성된 합성 자료와 loopback HTTP만 사용합니다.
ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_hn_discovery.py
ai/pipeline/.venv/bin/python ai/pipeline/scripts/hn_discovery_smoke.py
```

새 디렉터리에는 잠금 파일과 hash로 묶인 불변 `SNAPSHOT.json`만 남습니다. snapshot 스키마는 `zoop-hn-discovery-1`이며 stdout에는 상태·사용량·개수만 나옵니다. 동일 설정의 `run` 재실행과 `status`는 네트워크 없이 저장 결과를 반환하고 파일 바이트도 바꾸지 않습니다. 설정 충돌, 낯선 파일, 손상·미완료 출력, symlink는 거절합니다. 실패 후 자동 재시도나 같은 디렉터리의 재전송은 없으며 새 시도에는 새 디렉터리가 필요합니다.

외부 링크가 있는 `story`만 후보가 됩니다. 동일 canonical URL의 여러 제출은 하나의 후보에 `storyRefs`로 묶지만 독립 언론사나 독립 근거로 세지 않습니다. 의미 있는 query와 원래 HTTP/HTTPS scheme을 유지하고 fragment만 제거합니다. credential-bearing·비 HTTP(S) 링크는 값을 출력하지 않고 거절하며 링크 대상의 DNS도 조회하지 않습니다. `hnSubmittedTitleHtml`은 HN 제출 제목이므로 HTML로 실행하지 않아야 하고, `storyCreatedAt`은 HN 생성 시각입니다. `observedAt`은 별도 관측 시각이며 기사 `articlePublishedAt`과 `publisher`는 항상 null입니다. 누락된 점수·댓글 수는 null로 남기고, 존재하는 수치는 관심도 관측일 뿐 진실성·독립성·감정·주가 예측이 아닙니다. 모든 후보는 `articleAccess=not-assessed`, `license=not-assessed`, `modelSend=not-authorized`입니다.

URL의 percent-encoded 경로와 query는 디코딩해 다시 만들지 않습니다. 따라서 `/a%2Fb`와 `/a/b`, encoded dot segment가 있는 경로는 서로 다른 후보 신원을 유지합니다. HN 내부 호스트 여부를 비교할 때만 마지막 DNS dot을 제거하므로 `news.ycombinator.com.` 같은 자기 링크도 외부 후보가 되지 않으며, 이 비교에는 DNS 조회가 없습니다.

삭제·dead·비 story·알 수 없는 유형·null·링크 없음·잘못된 ID/타입·HTTP 오류는 후보가 아니라 `dispositions`에 남습니다. 401/403/429, robots 거절·오류, 전체 예산·시간 중단은 `stopped`와 미요청 disposition으로 종료하고 이후 항목은 보내지 않습니다. 나머지 항목 오류도 재시도하지 않습니다. `by`, `text`, `kids`, 사용자·프로필·댓글과 추가 upstream 필드는 파일로 복사하지 않고 전체 원본 JSON도 저장하지 않습니다. raw response SHA-256은 출처 확인용 hash일 뿐 native 문서 수집 receipt가 아닙니다.

전송은 기존 Fetcher의 DNS 고정·HTTPS 인증서/SNI·robots·deadline·환경 proxy 무시·쿠키 미사용·blocked-host 처리를 그대로 사용합니다. JSON 허용 정책은 이 모듈 내부에만 있고 기존 HTML/PDF collection policy는 변하지 않습니다. redirect는 따르지 않습니다. 합성 실행은 `syntheticLoopback: true`와 `syntheticBaseUrl: "http://127.0.0.1:<port>"`를 **함께** 지정해야 하며 결과는 `synthetic-loopback-metadata`로 표시됩니다. 이는 외부 API 실행 증거가 아닙니다.

### 이슈 요약 검증기 벤치마크

아래 명령은 저장소 루트에서 실행합니다. `loopback`은 작성된 응답을 돌려주는 로컬 HTTP 서버와 실제 native verifier 경로를 연결하며, 실제 모델의 품질·지연 시간을 측정하지 않습니다. 입력·정답·점수 계약과 한계는 [평가 패키지](../evaluation/README.md)와 [벤치마크 설계](../../docs/design/ai-benchmark.md)를 따릅니다.

```bash
ai/pipeline/.venv/bin/python ai/pipeline/scripts/summary_verify_bench.py loopback \
  --script ai/evaluation/fixtures/summary-verification/oracle.script.json --out /tmp/summary-oracle.run.json
ai/pipeline/.venv/bin/python ai/pipeline/scripts/summary_verify_bench.py assemble \
  --out-dir /tmp/summary-oracle.run.json.journal --out /tmp/summary-assembled.run.json
ai/pipeline/.venv/bin/python ai/pipeline/scripts/summary_verify_bench.py smoke
ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_summary_verify_bench.py
```

출력과 journal은 새 경로여야 합니다. 중단된 journal은 `assemble`로 읽기만 하며 재전송하지 않습니다. `run --mode live --confirm-inputs-sha256 <bundled-inputs-sha256> --check --out-dir NEW --run-id ID`는 기존 live 환경 설정·고정 모델·새 예산·명시적 실제 endpoint를 검사할 뿐 파일이나 요청을 만들지 않습니다. **플래그는 승인 자체가 아니며 실제 호출마다 별도 실험 승인이 필요합니다.** `--check`를 뺀 실제 provider 경로는 이 로컬 검사로 검증되지 않습니다. 보수적 예산 추정은 청구액이 아니며, native receipt의 비정상 UTF-8 원본을 `bodyText`에서 복원할 수 없으면 점수를 내지 않고 `receipt_body_mismatch`로 거절합니다.

Journal 파일은 비공개 임시 파일에 완전히 기록·동기화한 뒤, 기존 경로를 덮어쓰지 않고 최종 파일 이름으로 원자적으로 확정합니다. 중단으로 남은 `.pending` 파일은 `assemble`이 읽지 않지만, 확정된 파일이 손상되었으면 오류를 그대로 반환합니다. 웹 공개나 앱 버전 활성화를 뜻하지 않습니다.

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
- **policy 파일**(읽기 전용): `userAgent`(운영자가 정한 식별 문자열, 브라우저 흉내 금지), `timeoutSeconds`·`maxTotalSeconds`·`maxRedirects`·`maxRequests`(robots 포함)·`maxResponseBytes`·`maxTotalBytes`·`minIntervalSeconds`·`allowedMediaTypes`(`text/html`,`application/pdf`)는 필수입니다. 시험 전용 `syntheticLoopback`은 기본 false이고, 선택 항목 `contactUrl`은 아래 연락처 규칙을 따릅니다.
- **요청**: `{"schemaVersion":"zoop-collection-1","collectionId","sourceId","scopeId","targets":[{"candidateId","url","title","documentKind":"news"|"disclosure","supplierDocumentId"?,"publishedAt"?,"modifiedAt"?,"sourceRevision"?,"publisher"?}]}`. 설명 메타데이터(제목·시각·종류·발행 매체)는 **요청에 선언된 값만** 쓰며 페이지에서 긁어 오지 않습니다. `publishedAt`은 날짜(`YYYY-MM-DD`)면 `day` 정밀도로 남고 자정으로 바뀌지 않으며, 오프셋이 있는 시각만 `instant`, 오프셋 없는 시각은 `unresolved`(시간대를 가정하지 않음), 없으면 `unknown`입니다. 원문 표기·정밀도·근거는 `collection.published`에, `Item.publishedAt`에는 `instant`만 들어갑니다. `publisher`(선택)는 운영자가 선언한 발행 매체 이름이며 `null`·생략이 모두 미지정으로 같은 요청 digest를 만들고 지정하면 요청 identity가 달라집니다(같은 `collectionId`로 바꾸면 `collection_input_conflict`). 값 규칙과 identity 영향은 아래 ‘운영자 선언 발행 매체’ 문단을 따릅니다.
- **네트워크 방어(요청·robots·리다이렉트 hop마다 반복)**: URL 정규화(자격 증명·제어문자·모호한 인코딩·기본이 아닌 포트 거부), 정확한 호스트 목록, HTTPS만(루프백 http는 `syntheticLoopback`이 켜졌고 호스트가 `localhost`/`127.0.0.1`일 때만), robots.txt 선확인(최장 일치 RFC 9309, 404만 허용·그 외 오류는 거부), DNS 결과의 모든 주소가 전역 라우팅 가능해야 하며(IPv4-mapped/NAT64 포함) **검증한 그 주소로 직접 연결하면서** Host 헤더와 TLS SNI·인증서 이름은 요청 호스트를 유지합니다(DNS rebinding 방지, 요청마다 새 해석·새 연결). 프록시 환경변수는 무시(`trust_env=False`), TLS 검증은 끄지 않고, 쿠키·인증·Referer는 보내지 않으며, 압축 응답 거부, 401/403/429는 그 호스트를 실행 동안 차단, 자동 재시도 없음, 요청 수·바이트·시간·콘텐츠 타입 제한. 시스템 DNS 조회는 제한 시간에 중단·회수되는 별도 자식 프로세스에서 실행하고 비동기 HTTP 연결·TLS·헤더·본문 전체는 절대 deadline에서 취소합니다(조금씩 전송되는 헤더/본문도 제한). 동기 CLI/API이므로 같은 스레드에 이미 실행 중인 asyncio event loop가 있는 호출은 지원하지 않으며 `collector_async_context_unsupported`로 거부합니다. 오류는 URL·헤더 없는 안정적인 코드뿐입니다.
- **robots 그룹 선택**: `userAgent`의 제품 토큰과 대소문자 구분 없이 일치하는 그룹들을 합치고, 일치하는 그룹이 없을 때만 `*` 그룹들을 적용합니다. 기존에 지원하던 `User-agent: 제품/버전` 형식도 그대로 지원합니다. `Allow`·`Disallow` 경로와 `Crawl-delay` 값은 선택한 그룹에서만 검증하므로 다른 봇 전용 그룹의 잘못된 값은 수집을 막지 않습니다. 콜론이 있는 `User-agent`의 전체 값이 지원하지 않는 형식일 때는 선두 identity를 기존 agent 이름 문법으로 읽어 적용 가능성만 검사합니다. 그 전체 이름이 실제 제품 토큰 또는 `*`와 대소문자 구분 없이 같으면, 적용될 수 있는 제한을 버리고 wildcard 허용으로 넘어가지 않도록 `robots_malformed`로 거부합니다. 이는 [RFC 9309 §2.3.1.5](https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.1.5)가 특정한 해석을 의무화해서가 아니라 이 수집기가 추가로 채택한 보수적 거부 정책입니다. 다른 이름의 비표준 헤더는 일치하지 않는 별도 그룹의 경계로 처리하며, 그 규칙을 앞뒤의 유효한 그룹으로 넘기지 않습니다. 잘못된 값을 정규화해 적용 그룹으로 선택하거나 이름 안의 임의 부분 문자열로 발행자의 의도를 추정하지 않습니다. 콜론이 없는 행·그룹 밖 규칙·잘못된 UTF-8 등 파일 구조 오류와 적용 그룹의 잘못된 값도 여전히 `robots_malformed`로 본문 요청 전에 거부합니다. 절대 URL 규칙을 경로로 바꾸지 않습니다. 선택한 규칙은 경로·쿼리에 최장 일치를 적용하고 같은 길이에서는 `Allow`가 우선하며, 지연은 선택한 그룹들의 최댓값을 따릅니다. 유효한 금지 규칙은 `robots_denied`로 본문 요청을 막습니다.
- **산출물과 출처 구분**: `<source.inputRoot>/collections/<collectionId>/`에 `bodies/<sha256>.bin`(내용 주소), `receipts/<sha256>.json`(최종 URL·리다이렉트·HTTP 상태·콘텐츠 타입·ETag/Last-Modified/Date·robots 상태·본문 sha256·실제 수집 시각(UTC)·grant id/revision·`network`), `page-0.json`, `manifest.json`, `collection.json`. 모든 item은 `collection.provenance = "collected_http"`(획득 경로를 뜻함)이며 `collection.network`는 `external` 또는 `synthetic_loopback`(정책의 `syntheticLoopback`으로 로컬 시험 서버에서 받은 바이트, 외부 문서가 아님)입니다. receipt는 manifest/item이 hash로 고정합니다. `adapter: "collected-http"` source는 이 기록이 없는 item을 거부(`discovery_item_invalid`)하고, `authored-files` source는 이 기록이 있는 item을 거부해 **authored fixture를 actual로 바꿔 부를 수 없습니다.** ingestion은 receipt가 이 source·scope·candidate·현재 grant revision·실제 bytes와 일치하는지 검사합니다(`collection_receipt_invalid`). receipt는 서명되지 않은 운영자 로컬 파일이므로 입력 디렉터리를 쥔 사람은 위조할 수 있습니다. 이는 일관성 증거이지 네트워크 증명이 아닙니다.
- **불변·멱등**: `collectionId`는 불변입니다. 같은 id와 같은 입력(요청·source 설정·grant·policy)은 저장된 결과를 다시 보여 줄 뿐 재요청하지 않고(`replayed: true`), 다른 입력이면 `collection_input_conflict`입니다. 부분/실패 수집도 그대로 재현되며 숨은 재시도는 없습니다(다시 하려면 새 id).
- **부분·빈 결과·오류 구분**: 모든 URL 성공 `complete`, 일부 성공 `partial`(manifest page `partial`), 전부 실패 `failed`(manifest page `failed`, 빈 items). 요청 자체의 거부(`target_invalid`, 인증·어댑터·네임스페이스 오류)는 `error`이며 어느 쪽도 "성공한 0건"이 아닙니다. ingestion은 partial/failed page를 `incomplete`로 둡니다.
- **디렉터리 안전**: `inputRoot`와 `collections/`는 심볼릭 링크를 따르지 않고(디렉터리 fd, `O_NOFOLLOW`) 열며, `.lock`으로 배타 잠금하고, 낯선 파일(예: 외부 SQLite)이나 같은 id의 낯선 디렉터리는 채택하지 않고(`collection_namespace_conflict`) 앱/S1/PoC 상태 루트와 겹치면 거부합니다. 기존 `collection.json`도 descriptor-relative `O_NONBLOCK|O_NOFOLLOW`로 열고 regular file/크기 한도를 확인한 뒤 제한된 길이만 읽습니다(FIFO 등은 즉시 거부·미수정). 자신이 만든 `.tmp-<id>-…`에만 쓰고 한 번의 rename으로 공개하며, 실패 시 자신이 만든 이름만 지웁니다(이전 프로세스가 남긴 임시 디렉터리는 채택도 삭제도 하지 않음).
- **지원/미지원**: 지원은 명시된 `text/html`·`application/pdf` URL의 단발 수집뿐입니다(`text/plain` 등은 없음). 검색·RSS·DART/OpenDART 같은 API·인증·스케줄링·주기 갱신·시간 창 coverage 주장은 구현하지 않았으며 수집은 `coverageThrough`를 비웁니다. 실제 사이트에 대한 수집은 이 변경에서 실행하지 않았습니다.
- **HTTPS 인증서 검증**은 끌 수 없고, 연결 IP가 아니라 원래 요청 호스트를 Host·SNI·인증서 이름으로 사용합니다. 공개 회귀 시험의 HTTP 루프백만으로 TLS의 신뢰 체인과 이름 검증까지 증명할 수 없으므로, TLS 변경 시 별도 신뢰된 로컬 테스트 CA/잘못된 이름/신뢰되지 않은 CA 검증이 필요합니다.

**별도 비공개 뉴스 수집 경로(`zoop-ai-private-news`).** 이 경로는 위의 네이티브 수집과 달리 기사에 명시된 게시 메타데이터를 읽습니다. 날짜만 있으면 `day`, 시간대가 없으면 `unresolved`, 게시일이 없으면 `unknown`으로 보존하며 URL 날짜나 수정 시각으로 대신하지 않습니다. `±HH:MM`뿐 아니라 CNBC가 사용하는 `±HHMM` 오프셋도 해석하되 원래 표기와 정밀도를 유지합니다. Amazon 뉴스룸은 같은 기사의 `parsely-pub-date`를 먼저 읽고 OG 게시 시각과 schema `datePublished`를 대조합니다. 서로 모순되면 `article_date_conflict`로 거부하며, 날짜나 시간대를 추정해 채우지 않습니다.

비공개 뉴스 정책의 선택 항목 `maxDiscoveryResponseBytes`는 발견 목록 응답에만 적용되며, `1`부터 기존 파서 한도인 `10,000,000` bytes까지 지정할 수 있습니다. `maxTotalBytes`보다 클 수 없고, 생략하거나 `null`이면 기존 `maxResponseBytes`를 그대로 쓰며 저장 정책에도 새 키를 넣지 않습니다. 큰 사이트맵이 필요한 **새 계획**에서만 명시하고, 고정된 과거 계획은 수정하지 않습니다. 기사와 robots 응답 한도, 누적 바이트·요청·시간 예산, 호스트·경로·robots 검사는 그대로 유지합니다. 한도를 넘긴 마지막 수신 chunk도 실제 사용량에 포함하며, 목록 한도를 높인 사실을 전체 출처 수집 완료나 수집 권한으로 간주하지 않습니다.

**Versioned collection cutover (`scripts/collection_revision.py`).** `prepare` accepts the original `<day>/collection` or a drained, pinned predecessor under `<day>/collection-revisions/<id>`. Every revision must lead back to the same original collection; the new manifest preserves each ancestor's PLAN/LEDGER/INDEX pins, the same funding configuration and unresolved reservations, and the original `<day>/collection/fetch-pacing` directory. `check` validates new child configurations offline. `run` still requires explicit operator approval, a successful matching check, no shared admission stop, and time before the original admission cutoff. It does not extend the window, reset funding, promote the consumer index, or resume previously attempted plans.

Only provably untouched plans are rebound to the successor namespace. New FN plans explicitly use a 10,000,000-byte discovery limit while retaining the 2,000,000-byte article limit, 160,000,000-byte total and existing pacing. Amazon publication-field repair applies only to new eligible configs. The 879 old Actor-related `fallback_admission_mismatch` candidates remain pending reconciliation; this revision does not retry them, rewrite their reason, or repeat their native GETs. Existing unknown outcomes and committed records remain inherited evidence. Publication measurements accept basic ISO offsets and normalize them to UTC, without rewriting old UTC event bytes or relaxing UTC-only event start/end clocks.

`SIGUSR1` requests a **local checkpoint drain**: stop this controller's next admission, finish admitted finite children, and leave shared funding open. `SIGTERM`, `SIGINT`, `STOP`, and the configured cutoff remain global admission stops. A successor cannot erase them. Older frozen collectors may lack the local-pause handler; never signal one as though it had this implementation.

### Private finite-batch experiment setup

`scripts/overnight_run.py`, `overnight_collect.py`, and `collection_revision.py` are **operator-run local experiment orchestration**, not cloud deployment entry points; the container entry is `zoop-ai-collector` ([`docs/development/collector-container.md`](../../docs/development/collector-container.md)). They call the production `zoop_ai_pipeline.*_cli` modules. The analysis controller owns a private local Neo4j container through the existing `orbstack` Docker context; `--check` needs the already installed image `neo4j:5.26.32` and an unused loopback port. It does not install dependencies, pull an image, load credentials, or call a model.

Create a new private root and a new `runId` for each separately approved window. Keep previous roots, acquisition receipts, unknown requests, and closed money ledgers unchanged. The shared run configuration is a closed `zoop-private-run-4` object; old v2/v3 configurations are historical, not execution-compatible:

Keep the operator input configuration outside `<root>/control/run-config.json`. The controller owns that immutable mirror and writes sorted, compact UTF-8 JSON with a final newline; pre-creating it with pretty-printed JSON causes `immutable_artifact_conflict` before CHECK, even when the parsed values match.

```json
{
  "schemaVersion": "zoop-private-run-4",
  "runId": "day-20261029",
  "root": "/absolute/new-private-day-root",
  "admitFrom": "2026-10-29T00:00:00Z",
  "admitUntil": "2026-10-29T08:05:00Z",
  "finishBy": "2026-10-29T08:30:00Z",
  "graphPort": 32829,
  "maxCalls": 100000,
  "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"},
  "processingActor": {
    "kind": "user-private-experiment",
    "acceptedBy": "Main",
    "decidedAt": "2026-10-29T00:00:00Z",
    "statement": "Record the actual authorization for this private input and execution window."
  }
}
```

The example illustrates a USD 4 run (USD 3.50 shared OpenAI and USD 0.50 combined personal). Use the actual approval; a configuration does not authorize launch or acquisition. `admitUntil` stops new sets at 17:05 KST, while `finishBy` ends the drain at 17:30 KST. Funding amounts are required plain decimal strings with at most nine fractional digits, never floats. Shared plus personal must equal total exactly; shared may be zero, personal must exceed the USD 0.001 verifier reserve, each bucket is at most USD 10 and total at most USD 20. The actual configured caps, not these outer bounds, are frozen in `zoop-set-funding-3`, runtime bindings, CHECK and the ledger. No old ledger is upgraded and no balance rolls over. Unknown requests retain their worst-case charge; genuinely reported costs are never clipped to hide an overage. `maxCalls` is an additional finite ceiling. Collectors and analysis use the same approved root/configuration and ledger, never another personal bucket.

Select the exact collection index explicitly. It may be a retained revision index outside the new root; no implicit canary corpus is added and no old index is overwritten. Supply every preserved unknown unit with repeatable `--exclude-unit`; these exclusions are CHECK-pinned and remain visible in the full input manifest. Do not copy an old queue or adopt an unfinished database.

Native preparation byte-copies a quiescent `ingestion.sqlite3` into a run-owned per-unit directory before either SQLite read. It refuses symlinks, nonregular files, unexpected namespace entries, files over 128 MiB, and any WAL/SHM/journal sidecar, including empty ones. Every source hash/copy pass reads at most the initially pinned size plus one EOF sentinel, so a growing producer cannot cause an unbounded capture. Capture also checks stable metadata and hashes before and after; it never opens the original `ingestion.lock`, acquires its lock, opens the original database in SQLite, or recovers it. A refused capture leaves no unit checkpoint. The installed copy is read-only, has a new empty run-owned lock, and is pinned in `ingestionStateCopy`; acquisition artifacts retain their separate `originalPins`. Native export must equal the acquisition export except its current private grant, and all current rights checks remain mandatory.

CHECK reports `inputAuthorization.coverage`: manifest items, exclusions, prepared native/retained counts, awaiting-history items and preparation refusal codes. Exclusions count only current manifest inputs matching the current `--exclude-unit` set, even after a prior CHECK; they do not count as prepared, awaiting-history or blocked, and historical queue states remain unchanged. `limits.unitScope` is `whole-checked-input-manifest` only when every non-excluded item is prepared and history-ready; otherwise it is `prepared-subset-of-checked-input-manifest`. Cite these counts when reporting results, rather than presenting a retained-only or ready-only subset as the whole population.

In set-funded runs, only `verify-issue-summary` can reuse a settled receipt from a different candidate in the **same unit and admitted set**. The ledger's unique request owner, exact request/expect/runtime/recipient/funding/charge, strict answer decode, current source rights, and execution deadline must all agree. Unknown, released, missing, ambiguous, or changed sources refuse without a new verifier intent, reservation, or send; existing own intents/receipts keep their original resume semantics. Each consumer retains a timestamp-free `verify-issue-summary-reuse.json` (`zoop-private-verifier-reuse-1`). New private results use `zoop-private-candidate-summary-2`, whose `verifierSource` distinguishes an own provider receipt from a reused source attempt and receipt hash. Historical v1 results remain read-only. Journal `reused` observations carry the source attempt identity but no usage or charge, and never suppress that attempt's physical receipt row. Producer duplicates and the ledger uniqueness fence are unchanged. These new code pins require a new CHECK, greenlight, and separately authorized fresh run root; they do not authorize another window or repair historical failed folders.

```sh
# From the selected current worktree. Values are operator-selected absolute paths.
export PYTHONPATH="$PWD/ai/pipeline/src:$PWD/ai/worker/src"
PY="$PWD/ai/pipeline/.venv/bin/python"
CTL="$PWD/ai/pipeline/scripts/overnight_run.py"

# RUN_CONFIG, COLLECTION_INDEX and UNKNOWN_UNIT name the reviewed inputs.
# This is preparation + current grant/schema/source validation, without keys.
"$PY" -B "$CTL" --run-config "$RUN_CONFIG" --collection-index "$COLLECTION_INDEX" \
  --exclude-unit "$UNKNOWN_UNIT" --check --preparation-chunks 1

# Main reviews control/CHECK.json and writes the exact zoop-private-greenlight-2
# for its checkDigest, providerApprovalDigest, providerChain, verifier and mode.
# Initial paid readiness order: deepseek-diagnostic (one explicit --unit),
# then luna, then run. Each mode needs its own explicit Main greenlight.
"$PY" -B "$CTL" --run-config "$RUN_CONFIG" --collection-index "$COLLECTION_INDEX" \
  --exclude-unit "$UNKNOWN_UNIT" --canary --canary-profile deepseek-diagnostic \
  --unit "$CHECKED_UNIT" --credential-env "$AUTHORIZED_CREDENTIAL_FILE"
"$PY" -B "$CTL" --run-config "$RUN_CONFIG" --collection-index "$COLLECTION_INDEX" \
  --exclude-unit "$UNKNOWN_UNIT" --canary --canary-profile luna \
  --unit "$CHECKED_UNIT" --credential-env "$AUTHORIZED_CREDENTIAL_FILE"
"$PY" -B "$CTL" --run-config "$RUN_CONFIG" --collection-index "$COLLECTION_INDEX" \
  --exclude-unit "$UNKNOWN_UNIT" --run --batch-units 16 \
  --credential-env "$AUTHORIZED_CREDENTIAL_FILE"
```

These are separate approved commands, not a shell sequence to launch blindly. The primary is `gpt-6-luna` / high; the physical fallback is direct `deepseek-flash`, not the old proxy route; verification is `jev-1.14.0`. Readiness can be reused only with identical approved code, runtime, funding and original readiness evidence. It never authorizes newly appended inputs. Changing the index path or exclusions requires a new CHECK; newly discovered inputs remain `awaiting-check`. Credential setup, when separately authorized, uses `ai/worker/scripts/setup_ai_env.py --prepare-deepseek` (only add the absent empty key) or `--deepseek` (hidden interactive entry); neither changes OpenAI/Jev keys or the selected profile.

Each CHECK freezes the complete selected index and full manifest, plus the exact ready unit membership. Chunks contain at most 128 units; **128 is not a corpus cap**. Completed content-pinned chunks, unit proofs and successful keyless native admission checkpoints survive index appends. Only unseen inputs/chunks are prepared; reused proofs still undergo current source checks. Compatible history remains cumulative across chunks. An interrupted, unsealed preparation is refused rather than adopted. New chunks and each paid batch preserve least-served-source/publication-month selection.

Child stdin uses a private seekable temporary file containing the exact encoded request bytes. Observation timeouts never resend input or leave a partially written pipe awaiting EOF; the finish/forced-stop gate is checked again after spooling and before spawn. Failed input, output and checkpoint artifacts remain retained. A source change also changes preparation-cache pins: do not overwrite proofs or adopt an unsealed database to force a retry. Main must preserve the failed root and choose an authorized fresh namespace when the existing cache cannot be reused, without resetting or duplicating any monetary authority.

`--run` exits when its checked work is exhausted; `--batch-units` may stop sooner. Neither closes global admission. `SIGUSR1` finishes the current child/set and pauses locally; TERM/INT and the real cutoff still close shared admission. Main can then select the current index, repeat `--check --preparation-chunks 1`, review a new greenlight, and run another finite batch within the same approved window and remaining budget. Unknown paid outcomes remain reserved and are never automatically resent.

`finishBy` is pinned in the configuration, CHECK and readiness digest. New configurations require a drain interval longer than 480 seconds and at most one hour. The analysis controller reserves the final 180 seconds for reconciliation, graph shutdown and state flush: each model request must fit its full configured HTTP timeout (300 seconds here) before that reserve, and an overrun child receives TERM at `finishBy - 180s`, then KILL after at most five seconds, with at most another five seconds to reap. The collector additionally reserves ten seconds per configured concurrent child before that boundary, refuses a new child unless its whole finite allowance fits, and passes the earlier request deadline to native and paid Fetch guards. A 30-minute collection child admitted just before 06:00 normally ends by 06:30; exceptional overruns follow the explicit owned-child termination policy instead of draining indefinitely. Terminated work is unknown/incomplete, with reservations and raw state retained; it is never marked complete or automatically resent. Graph shutdown has its existing 60-second command timeout plus a ten-second inspection timeout. OS/process or filesystem failures that prevent reaping or flushing remain explicit failures, not a claim of completion by the deadline. No sleep-setting changes or keep-awake service are part of this workflow.

The controller selects `admitted-set-capped-v4`, which requires all three funding amounts and `ZOOP_AI_PIPELINE_LIVE_FINISH_BY` before a native binding can be frozen. New environment runs reject the old admitted-set v2/v3 profiles. Historical bindings and receipts still decode without reinterpretation. The exact finish authority remains part of the primary and direct-fallback runtime identities (`-funded-3`), and therefore of prepared requests. The shared SQLite ledger stores `zoop-finish-authority-1` once, only when fresh. Every reservation and send checks that persisted authority and reserves the full 300-second transport allowance before cleanup. Omitting or extending `SEND_BEFORE` cannot weaken it; an earlier override only tightens it.

Every collector plan in a funded run, including native, official and discovery work, obtains an atomic admission in that same ledger. Non-provider plans have an empty paid-stage allowance: they create no monetary reservation, call charge or additional cap. The collector observes shared TERM/INT/cutoff closure while running and repeats the check atomically at admission, so a concurrent analysis stop fences its next child. Already admitted work may drain; finite-batch completion and SIGUSR1 remain local and do not close or reopen shared admission.

New private Markdown records use `zoop-private-news-record-3`. Publication evidence binds the exact source/document and frozen source descriptor to independent native-response, provider-response and Markdown hashes. Only valid native HTTP 200 publication metadata or an unambiguous publication header can supply the date; challenge pages, URL dates, sitemap modification times and collection times cannot. The verifier recomputes the evidence. Missing evidence remains unknown/not retained, and historical v1/v2 records remain unchanged.

For a new collection window, repeat `--prior-collection` for every selected predecessor collection root. Preparation freezes its plan, ledger, index and state references, reuses retained inputs and preserves attempted/unknown URL exclusions. `--known-unsent-proof` admits only provenance-bound `fallback_admission_mismatch` entries whose original Actor validation failed before any provider attempt or reservation, including reservations in other sets for that URL. It seeds their existing native response without another article GET. Later attempts and unknown URLs cannot be exempted; current source, robots and funding checks still apply.

`scripts/retained_news_replay.py replay-markdown` can reprocess retained provider responses into a separate immutable record package without network calls. Pass each package's absolute `INDEX.json` to collector `prepare` with repeatable `--replay-package`; it is not a drained collection and must not be passed as `--prior-collection`. Use a fresh approved collection namespace rather than replacing an already frozen plan. The funded collection path remains `<run-root>/collection`; this input option does not extend the funding namespace, budget or deadline.

Preparation verifies the closed replay schema, original quiescent state/queue pins, current v3 records, frozen source descriptors, original provider/native bytes and publication evidence. `evidence/REPLAY_PACKAGES.json`, pinned by the new plan, binds every package index and consumed record/evidence file; CHECK and subsequent index publication refuse changed pins. The combined ordinary collection INDEX contains all native/private references, with exact retained-record identity deduplication and conflicting-record refusal—not URL or cross-source event merging. Replay references are `reused`, never new network acquisition; their original observation times remain intact. Empty and unrecovered package counts remain explicit, and the controller's 128-unit chunk bound is not a corpus limit.

A repaired parser does not make every retained response recoverable. None of these paths grants public use, publishes a graph, changes an old receipt or authorizes retrying an uncertain request.

### 수집기 연락처 설정

`--policy`로 읽는 정책에 선택 항목 `contactUrl`을 지정하면 기존 `userAgent` 뒤에 ` (+<contactUrl>)`만 붙입니다. 별도 User-Agent 재정의 CLI 옵션은 없습니다. 연락처를 지정할 때 `userAgent`는 기존 제품 이름과 버전을 유지한 `제품/버전` 형식이어야 하며, 브라우저 문자열이나 다른 주석을 함께 넣을 수 없습니다. 최종 헤더는 최대 200자의 ASCII입니다. URL은 공개 HTTPS 도메인을 사용해야 하고, 자격 증명·공백·제어문자·비ASCII 문자·괄호·HTML 구분자·역슬래시를 허용하지 않습니다. URL의 공개 접근 가능 여부와 내용의 진실성은 운영자가 별도로 확인해야 하며 수집기가 연락처 페이지를 가져오지는 않습니다.

robots.txt와 모든 리다이렉트 요청에 같은 최종 식별 문자열을 보내고 receipt의 기존 `userAgent`에 그대로 남깁니다. 연락처를 지정한 새 수집은 전부 실패해 receipt가 없어도 `collection.json`과 CLI 결과의 `userAgent`에 이를 기록합니다. `contactUrl`을 생략하거나 null로 두면 그 필드만 직렬화에서 빠지므로 기존 정책과 중첩된 corpus 설정의 canonical bytes, 요청 digest 계산 방식과 receipt 형식은 바뀌지 않습니다. 다른 nullable 필드는 그대로 유지합니다. 같은 `collectionId`의 연락처를 추가·변경하면 `collection_input_conflict`이며, 기존 수집을 다시 읽을 때 새 식별 필드를 만들어 넣거나 이전 실패를 재시도하지 않습니다.

[ONS의 봇 안내](https://developer.ons.gov.uk/bots/)는 운영 주체·목적·연락 방법을 설명하는 공개 URL을 권장합니다. 이 저장소의 아래 `Collector contact` 절을 공개 브랜치나 커밋에서 읽을 수 있게 게시한 뒤, 그 절을 가리키는 고정 URL을 사용할 수 있습니다. 이 문서를 로컬에서 수정한 것만으로 공개된 연락처가 되지는 않습니다. 개인 이름·사용자명·개인 이메일·가상의 회사 이메일을 헤더에 넣지 않습니다. 식별 연락처는 수집 권한을 대신하지 않으며, 실제 수집에는 별도로 확인한 이용 조건·권리 근거와 운영자 grant·예산·실행 승인이 필요합니다.

### Collector contact

**Owner:** the Zoop project. **Purpose:** bounded, operator-approved research into company-related public documents for the Zoop project, subject to source permissions, robots rules and request budgets. The collector does not log in or bypass access controls.

**Contact:** [Zoop project GitHub Issues](https://github.com/Donbug/zoop/issues). Site owners can report collector access concerns through this project channel. Please do not post credentials or other private information. This channel does not promise a response time or continuous monitoring.


### 정책브리핑의 날짜·채널별 유한 수집 (`korea_corpus_cli`)

`zoop-ai-collect`의 단발 계약은 그대로 유지됩니다. 별도 운영자 runner는 정책뉴스·보도자료·사실은 이렇습니다의 **공식 날짜별 목록**을 순서대로 읽고, 항목별 권리를 확인한 뒤 native collect → ingest → export를 호출합니다. RSS는 사용하지 않습니다. 실제 수집을 자동 시작하거나 cron·launchd·서비스·백그라운드 일정을 설치하지 않습니다.

```sh
# 기존 pipeline 가상환경으로 실행하므로 의존성 추가나 재설치가 필요하지 않습니다.
ai/pipeline/.venv/bin/python -m zoop_ai_pipeline.korea_corpus_cli run --config /absolute/operator/config.json
# 같은 config / stateDir로 실행하면 완료 항목은 재수집하지 않고 중단된 로컬 처리를 이어갑니다.
ai/pipeline/.venv/bin/python -m zoop_ai_pipeline.korea_corpus_cli run --config /absolute/operator/config.json
# 네트워크·파일 쓰기 없이 현재 STATE.json을 요약합니다.
ai/pipeline/.venv/bin/python -m zoop_ai_pipeline.korea_corpus_cli status --config /absolute/operator/config.json
# 실제 로컬 HTTP + CLI + native 수집/ingestion/export 양성·음성 시험. 실제 자료가 아닙니다.
ai/pipeline/.venv/bin/python ai/pipeline/scripts/korea_corpus_smoke.py
```

설정은 `zoop-korea-corpus-1` JSON입니다. 모든 예산은 필수이며 실제 호스트 간격은 2초 이상입니다. 아래 예는 **상한 400건, 채널당 20페이지, 전체 60페이지·800후보**의 운영자 설정 예이며 무제한 기본값이 아닙니다. 먼저 별도 pilot plan/stateDir에서 `maxDocuments: 3`, 채널별 `maxDocuments: 1`, `maxListingPages: 3`으로 실행하고 결과와 거부 사유를 확인합니다. pilot이 끝난 뒤 같은 plan의 상한을 바꾸지 말고 새 plan을 만듭니다. 새 plan의 제외 manifest에는 기존 50건과 pilot 성공 ID를 명시합니다.

```json
{
  "schemaVersion": "zoop-korea-corpus-1",
  "planId": "korea-20261001-23-bounded",
  "stateDir": "/absolute/operator/korea-20261001-23-bounded",
  "fromDay": "2026-10-01",
  "throughDay": "2026-10-23",
  "listingOrigin": "https://www.korea.kr",
  "articleOrigin": "https://m.korea.kr",
  "exactHosts": ["www.korea.kr", "m.korea.kr"],
  "channels": [
    {"name": "policy-news", "maxPages": 20, "maxDocuments": 140},
    {"name": "press-release", "maxPages": 20, "maxDocuments": 130},
    {"name": "clarifications", "maxPages": 20, "maxDocuments": 130}
  ],
  "maxListingPages": 60,
  "maxCandidates": 800,
  "maxDocuments": 400,
  "policy": {
    "schemaVersion": "zoop-collection-policy-1",
    "userAgent": "ZoopTextCorpus/1.0",
    "timeoutSeconds": 30,
    "maxTotalSeconds": 3600,
    "maxRedirects": 0,
    "maxRequests": 1700,
    "maxResponseBytes": 5000000,
    "maxTotalBytes": 200000000,
    "minIntervalSeconds": 2.0,
    "allowedMediaTypes": ["text/html"],
    "syntheticLoopback": false
  },
  "grant": {
    "grantId": "korea-plan-kogl1-text",
    "revision": "operator-reviewed-1",
    "sourceId": "korea-portal",
    "enabled": true,
    "rights": "known",
    "allowedOperations": ["read", "store", "quote-display"],
    "recipients": [],
    "purposes": [],
    "evidence": ["https://www.korea.kr/guide/copyRight.do; each item additionally requires its own exact KOGL1 badge and text-only notice"],
    "expiresAt": null
  },
  "rightsEvidence": {"path": "/absolute/operator/rights-evidence.json", "sha256": "<actual sha256 of that file>"},
  "exclusionManifest": {"path": "/absolute/operator/exclusions.json", "sha256": "<actual sha256 of that file>"}
}
```

`rightsEvidence`는 운영자가 확인한 저작권 정책·출처 표시 의무·항목별 KOGL1 확인 조건·텍스트만 허용한다는 범위·모델 전송 금지를 기록한 **새 plan의 외부 파일**입니다. 기존 50건의 registry·권리 범위·state를 확대하거나 덮어쓰지 않습니다. 제외 파일 형식은 `{"schemaVersion":"zoop-korea-exclusions-1","newsIds":["148974200", "..."]}`이며 실제 9자리 ID만 허용합니다. ID는 기존 PACKAGE의 `documents[].exportFile`을 읽어 각 export의 `observation.url`에서 얻습니다. 기존 파일은 읽기만 합니다. 제외 파일과 권리 증거의 실제 SHA-256을 config에 고정합니다. 제외 manifest가 비어 있어도 파일과 해시를 명시해야 합니다.

- **권리·본문 gate:** 목록의 실제 링크에 있는 `newsId`만 사용합니다. 날짜·채널·경로·쿼리·호스트를 제한하고 실제 목록의 건수·현재 페이지·유한한 `pageLink(n)` 링크를 대조합니다. 0건은 목록 안에 단일 `li.no_data`와 `등록된 정보가 없습니다.`라는 문구가 있고 다른 결과나 이동 링크가 없을 때만 확인합니다. 목록이나 페이지 표시가 없거나 건수와 이동 링크가 모순되면 해당 채널을 부분 결과로 중단합니다. 목록 밖의 추천 기사는 결과로 세지 않습니다. 페이지당 10건으로 가정하지 않으며, 첫 페이지에서 관측한 행 수를 후속 페이지의 종료 판단에 사용합니다. 항목의 canonical ID와 제목·발행 기관·보이는 날짜를 목록과 정확히 대조합니다. 발행 기관은 기사 머리의 두 번째 직접 `span`에 있는 텍스트로 읽으며 링크가 없어도 됩니다. 해당 `.article_body .view_cont` 안의 `.law_copy_wrap .kogl .guide > .type` 한 곳에 정확한 KOGL1 이미지·대체 텍스트와 텍스트 한정 고지가 함께 있어야 합니다. 같은 guide의 `.info`는 별도의 매체 제한·정책·연락처 안내이므로 고지 문구 비교에 포함하지 않습니다. footer의 일반 배지는 권리 근거로 인정하지 않습니다. type4·무표시·첨부/iframe만 있는 항목·연락처뿐인 짧은 응답은 거부합니다. 외부 iframe·첨부·이미지·동영상은 요청하지 않습니다.
- **실제 native 응답만 검증:** 별도 검사 GET은 하지 않습니다. 수집기가 받은 응답의 신원·메타데이터·항목별 권리·실질 본문을 원문/receipt 기록 전에 검사하고, 같은 응답의 권리 사실과 원본 해시를 먼저 불변으로 남깁니다. 페이지 주변부의 변동 때문에 두 요청의 전체 HTML이 같아야 한다고 가정하지 않습니다. 복구할 때는 이미 게시된 native collection의 receipt·본문 해시를 확인하고 저장된 본문에 동일한 gate를 다시 적용해 **모든 권리 사실**을 대조한 뒤 로컬 처리만 수행합니다. 게시된 수집이 없거나 권리 사실·본문·receipt의 일치를 증명할 수 없다면 `unknown`으로 남기고 재요청하지 않습니다. 목록·native 수집·robots의 모든 요청과 bytes가 하나의 누적 예산을 사용하며 배치마다 pacing·차단 호스트를 초기화하지 않습니다. corpus 전용 정책의 누적 `maxRequests` 상한은 5,000이고 기존 단발 CLI의 200회 상한은 바뀌지 않습니다.
- **현재 권리의 재검사:** 고정한 권리 증거·제외 파일 및 grant 만료를 네트워크 요청 때뿐 아니라 저장된 collection의 복구, 로컬 ingestion/export 전후, export 파일 게시 직전과 직후에도 확인합니다. 철회가 확인되면 새 export를 게시하지 않으며, 이미 승인된 시점에 게시된 native 원문과 receipt는 삭제하지 않습니다.
- **상태와 중단:** 저장소 밖의 전용 빈/새 `stateDir`만 사용합니다. `PLAN.json`은 config·증거 해시·gate 버전을 불변으로 묶고 변경 충돌은 기존 state를 수정하기 전에 거부합니다. 이전 gate 버전의 실패 plan은 이력으로 남기고 새 planId와 stateDir를 사용해야 합니다. `.lock`으로 한 프로세스만 쓰고, JSON은 비공개 staging → fsync → 원자적 게시를 거칩니다. symlink/외부 state를 채택하거나 남은 임시 파일을 임의로 지우지 않습니다. `STATE.json`은 요청 직전 intent와 항목별 결과를 기록합니다. 요청 중 강제 종료되어 실제 결과를 알 수 없으면 `unknownRequests`와 보수적 `unknownByteUpperBound`를 별도로 남기고 호스트를 차단합니다. 이를 실제 관측 요청/byte 수로 위장하지 않습니다. native 수집이 게시된 항목은 로컬 ingestion/export만 복구하며, native 기록이 없는 중단 항목은 `unknown`으로 남기고 재요청하지 않습니다. terminal 실패/거부/unknown은 자동 재시도하지 않습니다. 재시도가 필요하면 **새 planId·새 stateDir**을 명시하고 성공 항목을 제외합니다.
- **품질·출처 한계:** 날짜는 `day`이며 자정·시간대를 추정하지 않습니다. canonical native text/mapping을 바꾸지 않으므로 export에 권리 안내·담당자 연락처 등 boilerplate가 남을 수 있습니다. gate는 별도 DOM 사본에서만 이를 제외해 실질적 inline 본문을 확인하고, 항목별 `qualityWarnings`/`contactPresent`로 한계를 표시합니다. 이 안내 문구나 연락처를 의미 근거·gold로 취급하지 않습니다. 의미 품질 검사·경제 뉴스 필터·DART 공시·완전한 기간 coverage·model-send 권한은 제공하지 않습니다.
- **실행 수명:** runner는 현재 터미널에서만 동작합니다. 노트북 절전·재부팅·네트워크 단절로 중단될 수 있으며 숨은 예약 작업은 없습니다. 실행 전체 시간 상한은 최초 시작부터의 벽시계 시간으로 고정되므로 절전/재부팅 시간도 소모합니다. 시간이 만료된 plan은 예산을 초기화하지 않습니다. 다음 날 수집은 날짜·planId·stateDir·제외 manifest를 새로 정한 **새 daily plan**이고, 같은 plan의 재실행은 이미 정한 날짜와 예산 안의 복구일 뿐입니다.


### 로컬 사람 검토용 휴대 패키지 (`corpus_review_cli`)

기존 native export **전체를 현재 권한으로 다시 확인해** 저장소 밖의 새 전용 디렉터리에 복사하고, 그중 유한한 사람 검토 배치와 빈 주석 템플릿을 분리합니다. 모델·채점기·수집기가 아니며 네트워크, 모델 전송, 업로드, 공개 게시를 하지 않습니다. 정책브리핑 자료는 DART 공시나 사람 합의 gold가 아닙니다.

```sh
# 파일 경로는 모두 정규화된 절대 경로입니다. 출력의 부모 디렉터리는 미리 존재해야 합니다.
ai/pipeline/.venv/bin/python -m zoop_ai_pipeline.corpus_review_cli prepare \
  --bindings /absolute/operator/review-bindings.json --output /absolute/handoff/review-pack
ai/pipeline/.venv/bin/python -m zoop_ai_pipeline.corpus_review_cli verify \
  --pack /absolute/handoff/review-pack
# 템플릿을 패키지 밖에 복사한 뒤 사람이 이 파일만 편집합니다.
cp /absolute/handoff/review-pack/annotations.template.json /absolute/operator/review-annotations.json
ai/pipeline/.venv/bin/python -m zoop_ai_pipeline.corpus_review_cli annotations-check \
  --pack /absolute/handoff/review-pack --annotations /absolute/operator/review-annotations.json
# 실제 native 합성 원장과 CLI만 사용하는 집중 회귀 / smoke입니다.
ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_corpus_review.py -q
ai/pipeline/.venv/bin/python ai/pipeline/scripts/corpus_review_smoke.py
```

**운영자 binding.** 최상위 형식은 `{"schemaVersion":"zoop-corpus-review-bindings-1","selectionPolicy":{"perStratumQuota":3,"maxReviewDocuments":36,"allowUnknownDate":true},"documents":[...]}`입니다. 각 문서의 필수 필드는 다음과 같습니다. 생략 가능한 필드는 없으며, 해당하지 않는 두 plan pin은 명시적으로 `null`로 둡니다. 모든 객체는 추가 필드를 거부합니다.

| 필드 | 값 |
|---|---|
| `originalExport` | `{"path":"/absolute/source/exports/document.json","sha256":"<실제 파일 bytes의 SHA-256 64자리 소문자 hex>"}` |
| `nativeExport` | `{"schemaVersion":"zoop-ingestion-s2-1","roundId":"...","sourceId":"...","page":0,"ordinal":0,"documentId":"...","rawVersion":"...","documentVersion":"..."}` — 정확한 기존 observation selector |
| `sourceRegistryFile` | 현재 registry의 `{path,sha256}` pin. registry 내용은 패키지로 복사하지 않습니다. |
| `ingestionStateDir` | 기존 원장의 절대 경로. 옛 공유 원장과 새 항목별 원장을 문서마다 명시하며 디렉터리 구조로 추측하지 않습니다. |
| `authorityEvidence` | 기존 자료는 `{"kind":"legacy-operator-evidence","rightsEvidence":{"path":"...","sha256":"..."},"planFile":null,"exclusionManifest":null}`. 새 corpus는 `kind:"native-corpus-plan"`과 세 파일의 실제 pin을 모두 지정합니다. |
| `selection` | `{"channel":"policy-news","channelBasis":"portal-path","channelProvenance":"native observation URL 경로","publicationDay":"2026-10-23","dayProvenance":"native collection.published.date"}`. 채널명은 소문자 영문자로 시작하는 영문자·숫자·하이픈 80자 이내입니다. |

`native-corpus-plan`은 정확히 알려진 `korea-portal-static-2` 또는 `korea-portal-static-3`의 `PLAN.json` 자체, 그 `config.rightsEvidence`, `config.exclusionManifest`의 **외부 파일**을 고정합니다. 두 외부 pin과 `PLAN.rightsSha256` 및 현재 source grant가 plan과 일치해야 합니다. gate 버전 문자열만으로는 승인하지 않습니다. 두 버전 모두 현재 native export에 묶인 실제 저장 body·receipt의 SHA-256과 크기·source/scope/candidate/grant·URL·collection 사실을 읽기 전용으로 대조하고, 현재 `korea_portal.validate_article`로 그 body의 신원·게시 메타데이터·항목별 KOGL1·본문 조건을 다시 확인합니다. `PLAN.config.stateDir` 아래 해당 항목의 `rights.json`에 저장된 **모든 권리 사실**이 현재 parser 결과와 canonical JSON으로 같아야 합니다. proof 누락·변경·미지의 gate는 전체를 거부합니다. native 획득·runner·복구 명령을 부르거나 원장·원문·과거 plan을 수정하지 않습니다. `korea-portal`의 `item-` 회차는 legacy로 낮출 수 없습니다. 기존 자료도 운영자가 확인한 권리 증거 파일 pin을 요구합니다. 이 로컬 재검사는 현재 원격 페이지나 권리 증거의 법적 의미를 새로 판정하지 않습니다.

`channelBasis`는 알려진 정책브리핑 article 경로에 맞는 `portal-path`, 또는 근거를 적은 `operator-classification`입니다. 공식 호스트의 알려진 경로는 어느 방식이든 해당 채널과 일치해야 하며 collection 종류는 `news`여야 합니다. 임의 채널의 의미적 관련성을 주장하지 않습니다. `publicationDay`는 native의 day/instant 날짜 또는 기존 오프셋 시각의 달력 날짜와 정확히 같아야 합니다. 미상·시간대 미해결은 `null`로 보존하며 `allowUnknownDate:false`이면 전체 생성을 거부합니다. 날짜만 있는 값을 자정으로 바꾸지 않습니다.

**권한·파일·게시 경계.** `Store(existing=True)`와 `Ingestor.export(require_store=True)`로 현재 `read`·`store`·`quote-display`를 승인받은 **뒤에만** 원본 export bytes를 엽니다. 그 bytes의 pin·정확한 selector·native export의 canonical equality를 검사합니다. 원장 생성·복구·WAL 변경은 하지 않으며 한 번에 원장 하나만 엽니다. 입력 bytes·registry·외부 증거와 native 권한을 복사 시, 최종 게시 직전과 직후에 재검사합니다. 한 건이라도 철회·불일치하면 전체를 거부하며, 직후 검사에 실패하면 자신이 게시한 패키지만 회수합니다. 회수는 열린 출력 부모 디렉터리를 기준으로 no-replace 이동한 **실제** 디렉터리의 신원을 다시 확인한 뒤 자기 것만 삭제합니다. 다른 디렉터리가 끼어들면 내용을 지우지 않고 가능한 경우 제자리로 복원하며, 이름 충돌로 복원이 불가능한 경우에만 별도 격리 이름으로 보존합니다. 마지막 검사 이후의 철회까지 원자적으로 막지는 못합니다. 기존 경로는 빈 디렉터리도 채택하지 않고 symlink·소스/출력 namespace 중첩·저장소 안 출력도 거부합니다. 비공개 staging을 fsync한 뒤 macOS/Linux의 no-replace rename으로 한 번에 게시하며 강제 종료 때 남은 staging은 채택하거나 자동 삭제하지 않습니다.

**패키지와 선정.** `documents/<원본 bytes SHA-256>.json`에 정확한 export bytes를 보존합니다. `inputs.json`에는 전체 문서의 observation·selector·grant revision, 상대 파일 경로·해시·크기, 경로 없는 source pin 해시 및 선정 기록이 있습니다. `manifest.json`은 생성 시각, 원본 binding 파일 bytes의 `sourceInputSha256`, LF를 포함한 `inputs.json` 실제 bytes의 `immutableInputsSha256`, 건수와 한계를 기록합니다. SQLite·raw HTML·키·registry 전체·호스트 원장 경로를 복사하지 않습니다.

검토 배치는 `(channel, ISO publication week)` 층을 정렬하고, 각 층 안에서 `(roundId,sourceId,page,ordinal,documentId,rawVersion,documentVersion)` 순서로 한 건씩 round-robin 선택합니다. 층별 quota와 전체 최대치를 함께 적용합니다. 미상 날짜는 별도 `unknown` 층이며 각 층의 available/selected case ID와 건수를 기록합니다. `caseId`는 canonical native selector의 SHA-256으로 안정적으로 묶습니다. 모든 승인 문서를 복사하는 작업과 검토 배치 선정은 별개이며 대표 표본·held-out·test split·중요도 선정을 뜻하지 않습니다.

**주석.** `annotations.template.json`은 선택된 case ID와 `inputsSha256`만 결합하고, 모든 행을 `status:"unreviewed"` 및 `reviewerId`·`reviewedAt`·`graphNotes`·`ragQuestions`·`exclusionReason`·`evidenceSpans`의 `null`로 시작합니다. `reviewed`는 식별 가능한 reviewer, 오프셋이 있는 검토 시각, 비어 있지 않은 graph notes와 명시적 RAG 질문 목록을 요구합니다(질문이 없으면 `[]`). 불확실성도 notes에 그대로 기록합니다. `excluded`는 reviewer·시각·사람이 적은 제외 이유를 요구합니다. 선택적 `evidenceSpans`는 `[{documentId,documentVersion,start,end,quote}]`이며 Unicode code point의 `[start,end)`와 정확한 문자열 및 한 native locator 안의 범위를 확인합니다. foreign/누락/중복 case와 추가 필드도 거부합니다. 미검토는 오답·거절로 세지 않으며 출력은 상태별 건수뿐입니다. 완성된 주석도 운영자 주장이지 검증된 사람 합의나 품질 점수가 아닙니다.

**휴대 검증과 상한.** `verify`는 원래 원장·환경 설정·네트워크 없이 옮긴 패키지의 닫힌 구조·파일 해시·입력 binding·locator 범위와 선정 재현성을 확인합니다. mutable template는 열거나 stat하지 않으며 없어도 됩니다. `prepare` 역시 주석/gold를 읽지 않습니다. `annotations-check`만 명시한 패키지 밖 주석 파일을 읽으며 패키지를 수정하지 않습니다. 휴대 검증은 현재 권리나 발행자 진위를 증명하지 않습니다. 상한은 문서 2,000건, binding/export 각 8,000,000 bytes, inputs/annotations 각 16,000,000 bytes, export 합계 512,000,000 bytes, 층 quota 1–50, 검토 최대 1–200건입니다. stdout은 본문 없는 상태·건수·digest만 내며 성공 0, 거부 2입니다. 실제 본문과 작성된 주석은 Git 밖에 유지합니다.

### 수령자용 최단 레시피: 명시한 URL → 준비된 문서 export (모델·PoC·DB 서버·클라우드 없음)

필요한 것은 `make pipeline-install`로 만든 `ai/pipeline/.venv`뿐이다. Neo4j·PostgreSQL·OpenAI/TypeSafe 키·네트워크 계정은 필요 없다(네트워크는 `zoop-ai-collect`가 **요청에 적은 URL**에만 연다). 저장소 checkout 안의 `.venv`를 쓰면 앱/S1 상태 루트가 자동 파악된다. checkout 밖에 설치한 패키지는 `ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR`(절대 경로)를 지정해야 하고 없으면 거부한다. 두 모드는 **같은 명령, 다른 입력**이다. 합성 시연이 외부 문서가 아님은 export의 `observation.collection.network`가 `synthetic_loopback`인지로 구분하며, 실제 모드의 값은 `external`이다.

**A. 합성 시연(외부 접속 없음, 바로 실행).** 임시 `127.0.0.1` 서버가 합성 HTML 1건·PDF 1건을 내주고 실제 CLI 세 개(collect → ingest run → ingest export)를 subprocess로 돌린 뒤 파일을 **남긴다**(기본 smoke는 모두 지운다). 출력 디렉터리는 없거나 비어 있어야 한다.

```sh
ai/pipeline/.venv/bin/python ai/pipeline/scripts/collection_smoke.py --output-dir /tmp/zoop-collection-demo
# 남는 파일: sources.json, policy.json, collect-request.json, ingest-run-request.json (이 시연의 전체 유효 설정/요청),
#            inputs/collections/demo-collect-1/ (원본 bytes·receipt·manifest), state/ingestion.sqlite3, exports/n1.json, exports/d1.json
```

서버는 종료됐으므로 남은 URL·포트는 재실행용이 아니라 형식 참고용이다. 이 파일들은 합성 문서이며 근거 자료나 실제 수집물이 아니다. 아래 B의 JSON은 같은 스키마의 실제 모드 버전이다.

**B. 실제 모드: 사용자가 권리를 확인한 URL만.** 아래 `news.example.com`, `evidence`, `userAgent`, `targets`는 반드시 자기 값으로 바꾼다. `evidence`에는 이 URL들의 수집·저장·인용 표시를 허락한다는 **실제 근거**(계약·약관·서면 허락)를 적는다. 공개 URL이라는 사실이나 robots 허용은 근거가 아니다. 근거 없이 임의의 사이트를 넣지 않는다. 한 번에 최대 50건이며 필수 정책 값에는 기본값이 없다. 연락처를 요구하는 사이트에는 위 연락처 설정에 따라 실제로 공개된 페이지의 `contactUrl`도 지정한다.

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
{"schemaVersion":"zoop-collection-policy-1","userAgent":"ZoopCollector/1.0","timeoutSeconds":20,
 "maxTotalSeconds":300,"maxRedirects":3,"maxRequests":20,"maxResponseBytes":5000000,"maxTotalBytes":50000000,"minIntervalSeconds":1,
 "allowedMediaTypes":["text/html","application/pdf"],"syntheticLoopback":false}
EOF

cat > "$WORK/collect-request.json" <<'EOF'
{"schemaVersion":"zoop-collection-1","collectionId":"my-collect-1","sourceId":"my-source","scopeId":"body","targets":[
  {"candidateId":"n1","url":"https://news.example.com/articles/1","title":"기사 제목(운영자가 선언)","documentKind":"news",
   "publishedAt":"2026-10-14","supplierDocumentId":null,"modifiedAt":null,"sourceRevision":null,"publisher":"<운영자가 확인한 발행 매체 이름. 모르면 이 키를 생략>"},
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
| 발행 매체(선택) | `observation.publisher` | 운영자가 target/item에 선언했을 때만 있는 키다. 미선언은 `null`이 아니라 키 없음이며 호스트·페이지에서 추정하지 않는다. 공급 경로가 아니라 발행 매체이고 매체 간 독립성·계보 판정은 아니다 |
| 수집 경로·분류 | `observation.provenance`(`collected_http`), `collection.network`, `collection.documentKind`, `finalUrl`, `httpStatus`, `contentType`, `bodySha256` | `network`가 `synthetic_loopback`이면 시험 서버 bytes이지 외부 문서가 아니다 |
| 권리 | `grant.grantId`·`grant.revision` | export에는 권리 **내용**(rights·evidence·operations)이 없다. 내용은 `sources.json`의 grant가 정본이며 수령자는 grant id/revision과 함께 보관해야 한다 |
| 본문 | `document.text`(준비된 텍스트), `document.rawLocators`, `locatorMetadata.rawHash` | 텍스트는 정리된 사본이고 원본 bytes가 아니다. HTML은 DOM text 좌표, PDF는 page 추출 텍스트 좌표다 |

- **원본 bytes는 export에 들어 있지 않다.** 원본은 `inputRoot/collections/<collectionId>/bodies/<sha256>.bin`과 `ingestion.sqlite3`의 raw BLOB에 있다. 수령자에게 원본이 필요하면 `locatorMetadata.rawHash`·`collection.bodySha256`과 일치하는 파일을 별도로 전달하고, 그 전달도 `read`·`store` 권리가 있는 경우에만 한다.
- **export는 그 순간의 권한 확인 결과**다. 이후 grant가 철회·만료되면 같은 export 명령은 본문 없이 `source_unauthorized`만 낸다. 이미 파일로 복사된 export는 이 CLI가 회수하지 못한다.
- title·kind·publisher·게시/수정 시각은 운영자 선언이며 검증된 사실이 아니다. 공개·게시 승인, 요약·감성·기업 연결, 앱 Dataset 등록, 완전성·커버리지 주장은 이 출력에 없다.
- 합성 시연(A)과 실제 모드(B)는 같은 형식이지만 A의 파일을 실제 수집 결과로 인용하면 안 된다. 이 절의 B 명령은 외부 사이트를 대상으로 실행되지 않았다.


`zoop_ai_pipeline.ingestion_cli`의 `run/resume/inspect`는 BFF의 admin `ingest-run`과 **다른 내부 실행 경계**다. 네이티브 URL/HTML/PDF 준비(`ingestion_url`·`ingestion_parsers`·`ingestion_pdf`, lxml·pypdf, 같은 공개 의존성)만 쓰며 private PoC를 import하지 않고 네트워크·모델·PoC 원장·앱/S1 DB에는 연결하지 않는다(네트워크는 위 `zoop-ai-collect`만 연다). 이전 pinned-PoC parser 프로필(`pocCommit`)로 만든 round는 새 프로필(`parser: zoop-native-parsers-1`)과 달라 `resume`이 `parser_profile_changed`로 거부하며, 그 round의 저장된 version과 export는 그대로 읽힌다(재해석하지 않음). 새 프로필의 version은 같은 raw bytes여도 새 preparation key/version id를 가진다. 명시한 전용 `--state-dir`의 private `ingestion.sqlite3`에 원래 response/raw BLOB, source-local 문서 ID, raw/text version, HTML node/PDF page span과 연속 checkpoint를 저장한다. 현재 operator `--sources`는 매번 완전한 snapshot으로 읽고, fixture manifest는 hash-pinned 파일 입력일 뿐 권한을 발급하지 않는다. 수집한 관찰의 `export`는 `observation`에 `provenance: "collected_http"`와 `collection`(실제 수집 시각, 최종 URL, HTTP 상태, 본문 sha256, 문서 종류, `network`, 선언된 게시 시각의 원문·정밀도)을 **추가로** 돌려주며 license를 주장하지 않는다. authored 관찰의 export는 이전과 같은 닫힌 키 집합 그대로다(Java `IngestionExportParser`가 두 형태의 정확한 키 집합을 고정하며, 같은 집합을 `tests/test_collection.py`가 고정한다). run/inspect 결과의 최상위 `provenance`는 두 경우 모두 있다.

**파서 실행 환경의 신원 확인.** 지원 환경은 frozen lock에 고정된 의존성을 사용한다. 새 round를 만들거나 미완료 후보를 준비할 때 `importlib.metadata.version()`으로 얻은 `lxml`·`pypdf` 버전이 없거나(`PackageNotFoundError`·`null`), 문자열이 아니거나, 비어 있거나 공백뿐이거나, 200자를 넘으면 `input_or_configuration_invalid`로 거부한다. 새 `run`은 이 오류를 JSON으로 반환하고 종료 코드 2로 끝나며 round나 준비된 version을 등록하지 않는다. 기존 미완료 round의 `resume`은 같은 코드를 `failure.code`에 기록하고 `incomplete`로 남는다. 이미 저장한 raw bytes는 보존하지만 새 준비 결과나 영구 parse hold는 만들지 않는다. 정상 버전 문자열은 그대로 사용하므로 기존 canonical bytes와 문서 신원은 바뀌지 않는다.

이 오류가 나면 frozen lock에 맞는 실행 환경과 설치된 distribution metadata를 복구한 뒤 준비 작업을 다시 실행한다. 모듈의 `__version__`, 추정값, 문자열 변환으로 빈 신원을 대신하지 않는다. 현재 실행 환경의 metadata가 손상돼도 유효하게 저장된 과거 version의 `inspect`·읽기 전용 `export`는 현재 권한 검사에 따라 계속 사용할 수 있다. 이미 기록된 원본·receipt·export는 고치거나 덮어쓰지 않으며, 잘못 기록된 버전 정보도 소급해서 채우지 않는다.

저장소 루트에서 다음 명령으로 합성 HTML/PDF와 실제 subprocess CLI를 재현한다. driver는 fresh 임시 입력/상태를 만들고 검사 후 모두 제거한다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/ingestion_smoke.py
```

실제 결과는 `status=passed, preparedDocuments=2, providerCalls=0, modelCalls=0`이었다. receipt/raw/version/checkpoint 저장 뒤 프로세스 중단·resume, 같은 cursor replay, 변경 body의 새 버전, zero/failure/partial/parse hold, stale checkpoint, registry 철회/누락, entity·tail·반복 한글/emoji와 PDF page 좌표, S1 exact의 생성 separator 거부를 확인했다. review 회귀까지 포함한 focused `tests/test_ingestion.py`는 **43 passed, 기존 Starlette warning 1개**였다. 실제 scope A 철회 뒤 scope B의 XPath에 맞는 text/hold 분리와, 첫 supplier의 raw commit 뒤 파일이 없어도 공유 body로 둘째 supplier를 준비하는 복구도 통과했다.

**운영자 선언 발행 매체(`publisher`).** authored fixture item과 수집 target은 선택 키 `publisher`(발행 매체 이름)를 가질 수 있고 export `observation.publisher`로만 나간다. 값은 운영자가 입력에 선언한 문자열뿐이며 `sourceId`·공급 경로·호스트·`finalUrl`·페이지 HTML에서 추정하지 않고, 계보(lineage)나 독립 매체 판정도 하지 않는다. 생략과 명시적 `null`은 둘 다 **미지정**이며 그때는 키 자체가 요청 wire·저장 metadata·export에서 빠진다. 이미 `null`로 직렬화되던 키(`publishedAt` 등)는 그대로라서 발행 매체가 없는 입력의 요청 digest·페이지 bytes·`rawVersion`·`documentVersion`·export 키 집합은 이전과 byte 단위로 같다(옛 값 pin은 `tests/test_ingestion.py`·`tests/test_collection.py`·`scripts/ingestion_smoke.py`에 있고, publisher 도입 전 커밋의 코드를 한 번 돌려 얻은 literal이며 새 구현으로 만든 값이 아니다). 지정하면 metadata 해시에 들어가므로 같은 `documentId`의 **새** `rawVersion`/`documentVersion`이 되고 옛 version은 바뀌지 않는다(같은 매체를 다시 선언하면 이미 있는 version). 값 규칙은 1~200 code point, 제어 문자(Cc, 탭·줄바꿈 포함)·lone surrogate·구분자(Z*)로만 된 값은 거부하고 공백 정리나 유니코드 정규화는 하지 않는다. 이 값은 S2 분석 `Article`(`publisher=""`)·`Article.version`·handoff bundle로 들어가지 않는다. 앱은 export의 값을 이미 있는 `article_versions.publisher` 열에 저장하므로 **소비자(앱 importer)를 먼저 배포한 뒤** publisher를 선언한 export를 만들어야 한다(옛 importer는 알 수 없는 키를 `EXPORT_INVALID`로 거부한다).

`ingestion_smoke.py`는 `publisherRegressions`(authored 입력의 선언·비선언·`null`·공백만 거부·재생 멱등)를, `collection_smoke.py`는 합성 loopback에서 target 하나만 선언한 collect → ingest → export 전파와 `null`=생략 replay·변경 시 `collection_input_conflict`를 검사하도록 확장했다(결과 수치는 이 문서에 적지 않았다. 확장 뒤 실행 결과는 별도로 기록한다).

wire schema는 `zoop-ingestion-s2-1`이며 공용 OpenAPI나 S1 schema를 바꾸지 않았다. 정확한 문서/version을 고른 `inspect`만 현재 read 권한으로 내부 S1 `Document` projection을 반환한다. 원문 span 해석에는 quote-display도 요구한다. S2-2가 쓰도록 정확한 관측(round/source/page/ordinal/document/rawVersion/documentVersion)의 서버 소유 URL·title·publishedAt과 grant를 반환하는 읽기 전용 `ingestion_cli export`를 추가했다. HTML 위치는 decoded DOM text/tail 좌표이고 PDF 위치는 frozen page-extracted text 좌표이지 raw byte·glyph geometry가 아니다. 이 문서는 앱 Dataset에 등록되거나 게시되지 않는다. 실제 공급원/정기 수집·기업/이슈 연결·공개 등록/게시·유료 의미 검증은 구현 완료로 주장하지 않는다. 명령·registry·manifest·한계와 실행 증거는 [AI 실행 계약의 S2-1 절](../../docs/design/ai-system.md#s2-1-독립-오프라인-원문-준비와-검사)을 따른다.

## 정기 회차 컨트롤러 (S2-1 `tick`, FS058·요구 70의 오프라인 일부)

`zoop-ai-ingest tick`은 시계 한 번의 읽기를 **가장 최근에 도래한 slot 하나**로 바꾸고, 그 slot의 회차를 기존 engine으로 **최대 한 번** 진행한다. 새 DB·table·column·migration·console script가 없고 기존 engine 동작도 바꾸지 않으며 새 서비스·모델·provider·네트워크·cron·AWS도 없다. **이 명령은 trigger를 배포하지 않는다.** 누가 언제 `tick`을 부를지(cron·AWS 등)는 이 저장소에 없고 FS058은 완료되지 않았다(아래 "하지 않는 일").

| 규칙 | 값 |
| --- | --- |
| slot | KST 고정 UTC+09의 09:05, 09:35, … 17:35(하루 18개). **요일·공휴일 구분 없이 매일**이다(스펙에 요일·휴일 규칙이 없다: FS058 `09-데이터-관리.csv` 109–143행, NFS012 377·392행, 요구 70) |
| 선택 | 같은 날의 가장 늦게 도래한 slot, 단 `09:00 <= now < 18:00`. 09:00:00–09:04:59.999999는 `before_first_slot`, 그 밖은 `outside_operating_window`로 **not-due**다. 09:20→09:05, 10:04:59→09:35, 17:59:59.999999→17:35, 18:00→not-due. 늦게 도착한 trigger도 도래한 slot을 놓치지 않는다 |
| window | `from` = 저장된 마지막 **성공** 경계(`through_time`)의 문자열 그대로, `through` = slot(`YYYY-MM-DDTHH:MM:00+09:00`). 겹침·lookback을 만들지 않는다. fixture manifest 마지막 page의 `coverageThrough`가 이 slot 문자열과 **정확히 같아야** 완료이고, 아니면 `coverage_incomplete`다 |
| roundId | `slot-` + sha256(canonical JSON `{sourceId, scopeId, slot}`). 길이가 고정이라 200자 scope도 쓴다. 읽을 수 있는 slot은 출력의 `tick.slot`이다 |
| catchUp | 저장된 window의 `from`이 slot보다 **30분을 넘게** 앞일 때만 `true`다(전날 17:35 경계에서 시작한 09:05 slot은 true, 명시한 5분 창과 정확히 30분은 false). 컨트롤러가 요청한 창의 길이 표지일 뿐 공급원의 coverage나 "놓친 뉴스 없음"의 주장이 아니다. 재실행은 저장된 창으로 같은 값을 낸다 |

입력은 stdin JSON `{schemaVersion:"zoop-ingestion-s2-1", sourceId, scopeId, initialFrom?, now?}`(strict, 알 수 없는 키 거부)이고 `initialFrom`·`now`는 timezone이 있어야 한다. 명령은 `zoop-ai-ingest tick --state-dir DIR --sources REG [--fixture-manifest M]`이며 `--require-store`는 여전히 `export` 전용이다.

**`now`는 sandbox가 아니다.** 시험·시연용 결정적 시계 override이며 실제 시계보다 미래이면 `clock_in_future`다. 과거로 주입한 `now`와 유효한 manifest가 있으면 `--state-dir`로 지정한 **그 밖에 유효한 ledger에는 실제로 기록된다**(주입 시계를 위한 격리·표지·marker는 없다). 그래서 시연과 시험은 항상 **새 격리 `--state-dir`**를 쓴다. grant `expiresAt`은 주입한 `now`가 아니라 **실제 UTC 시계**로 판정한다(주입 시계에서는 유효해도 실제로 만료됐으면 `source_unauthorized`).

**한 번의 tick이 하는 일(순서).**

1. stdin 해석 → 시계(`clock_in_future`) → due 판정을 **registry·manifest·state에 손대기 전에** 한다. not-due는 아무것도 읽거나 만들지 않고 exit 0이며, 넘긴 manifest 경로는 무시한다.
2. due이면 ledger 독점 lock(tick 내내 유지)을 잡고 registry의 현재 grant·scope 권한을 확인한다(`source_unauthorized`).
3. 그 slot의 round가 이미 있으면 저장된 request와 `window.through`가 이 slot과 같은지, manifest를 줬다면 SHA-256이 frozen hash와, `initialFrom`을 줬다면 저장된 `from`과 같은 시각인지 확인한다(불일치는 `slot_input_conflict`, 아무것도 쓰지 않음). 현재 registry 설정이 저장된 설정과 같은지도 먼저 확인한다(`scope_configuration_conflict`). 그다음 `running`이면 `resume`을 **한 번**(`recovered`; 독점 lock이 이전 프로세스가 죽었음을 증명), `complete`·`incomplete`이면 저장된 결과만 돌려준다(`replayed`). **숨은 재시도는 없다.** 복구 가능한 incomplete(예: 없던 body 파일이 복원됨)도 같은 slot의 tick은 계속 incomplete로 replay하고, 완료는 명시적 `zoop-ai-ingest resume`만 한다.
4. 새 slot이면 baseline은 저장된 `through_time`이고, 없을 때만 `initialFrom`을 쓴다. 둘 다 있으면 `initial_baseline_conflict`, 둘 다 없으면 `initial_baseline_required`, baseline이 slot 이후이면 `slot_not_after_baseline`, manifest가 없으면 `fixture_manifest_required`다. 통과하면 `run`을 **한 번** 한다(`started`).
5. 오래된 unfinished slot은 자동으로 resume하지 않는다. 새 slot은 마지막 성공 경계에서 시작하고 이전 round의 checkpoint는 기존 engine 규칙대로 stale이 되며, 명시적 `resume`이 `checkpoint_stale`을 기록하거나(아직 현재면) 완료한다.

출력은 canonical JSON이다.

```json
{"schemaVersion":"zoop-ingestion-s2-1",
 "tick":{"action":"<not-due|started|recovered|replayed>","at":"<now를 KST로>","slot":"<slot|null>","roundId":"<id|null>",
         "reason":"<outside_operating_window|before_first_slot|null>","catchUp":"<true|false|null>"},
 "round":"<기존 run/resume 출력 그대로|null>"}
```

| 종료 코드 | 뜻 |
| --- | --- |
| 0 | not-due, 또는 round가 `complete` |
| 3 | round가 기록됐지만 `complete`가 아니다. `run`은 incomplete도 0이지만 scheduler가 실패한 회차를 성공으로 보지 않도록 tick만 다르게 둔다 |
| 2 | 오류. 기존 `{schemaVersion,error:{code}}`이며 새 코드는 `clock_in_future`·`initial_baseline_required`·`initial_baseline_conflict`·`slot_not_after_baseline`·`slot_input_conflict`뿐이다 |

실패·partial page는 `through_time`을 옮기지 않는다(page를 끝낸 round의 revision·cursor는 기존 engine대로 움직일 수 있다). 선언된 coverage가 있는 0건 round는 유효한 성공이라 경계를 옮기고, coverage 없는 0건은 `coverage_incomplete`·exit 3으로 경계를 옮기지 않는다. `collected-http` source는 수집기가 `coverageThrough`를 항상 null로 쓰므로 tick은 정직하게 incomplete(exit 3)이며 어댑터별 우회는 없다.

**CLI 절차 — 첫 tick, 그다음 정규 tick(합성 authored fixture, 외부 접속 없음).** 아래는 새 격리 디렉터리에서 그대로 실행하는 절차다. 실제 운영 시계를 쓸 때는 JSON에서 `now`를 뺀다.

```sh
BIN="$PWD/ai/pipeline/.venv/bin"
WORK="$(cd "$(mktemp -d /tmp/zoop-round-demo.XXXXXX)" && pwd -P)"   # 항상 새 디렉터리(ledger도 여기에 생긴다). state 경로에 symlink가 있으면 거부하므로 pwd -P로 실제 경로를 쓴다(macOS의 /tmp). 저장소나 앱/S1/worker 상태 디렉터리 안에 두지 않는다
mkdir -p "$WORK/inputs"

cat > "$WORK/sources.json" <<EOF
{"schemaVersion":"zoop-ingestion-s2-1","revision":"operator-1","sources":[{
  "sourceId":"synthetic-source","adapter":"authored-files","inputRoot":"$WORK/inputs","allowedHosts":["example.invalid"],
  "scopes":[{"scopeId":"body","selection":"authored source slice","initialCursor":null,"articleXPath":null,
             "timestampLimitations":["authored fixtures; no real provider late-registration guarantee"]}],
  "grant":{"grantId":"operator-grant","revision":"rights-1","sourceId":"synthetic-source","enabled":true,"rights":"known",
           "allowedOperations":["read","store","quote-display"],"recipients":[],"purposes":[],
           "evidence":["operator-owned authored synthetic fixtures"],"expiresAt":null}}]}
EOF

# slot마다 manifest 하나: 마지막 page의 coverageThrough가 그 slot 문자열과 정확히 같아야 한다. 아래는 첫 slot에 기사 1건, 다음 slot은 0건(coverage 선언)이다.
"$BIN/python" - "$WORK" <<'PY'
import hashlib, json, sys
from pathlib import Path
work = Path(sys.argv[1])
def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
def put(name, raw):
    (work / "inputs" / name).write_bytes(raw)
    return {"file": name, "sha256": hashlib.sha256(raw).hexdigest()}
def manifest(name, slot, items=(), bodies=None):
    documents = {key: put(f"{name}-{key}.html", body) for key, body in (bodies or {}).items()}
    response = put(f"{name}-page.json", dump({"items": list(items), "more": False, "nextCursor": None}))
    page = {"pageId": "page-0", "cursor": None, "response": response, "status": "ok", "nextCursor": None, "terminal": True, "coverageThrough": slot}
    (work / f"{name}-manifest.json").write_bytes(dump({"schemaVersion": "zoop-ingestion-s2-1", "sourceId": "synthetic-source", "scopeId": "body", "pages": [page], "documents": documents}))
article = {"candidateId": "a", "supplierDocumentId": "supplier-a", "url": "https://example.invalid/a", "bodyRef": "a", "mediaType": "text/html",
           "title": "합성 기사", "publishedAt": "2026-10-17T09:00:00+09:00", "modifiedAt": None, "sourceRevision": None}
manifest("m-0905", "2026-10-17T09:05:00+09:00", [article], {"a": "<html><body><article><p>합성 본문</p></article></body></html>".encode()})
manifest("m-0935", "2026-10-17T09:35:00+09:00")
PY

TICK() { "$BIN/zoop-ai-ingest" tick --state-dir "$WORK/state" --sources "$WORK/sources.json" "$@"; }

# 1) 첫 tick(토요일 09:05:30 KST). 저장된 성공 경계가 아직 없으므로 initialFrom으로 시작 경계를 명시한다(없으면 initial_baseline_required).
#    기대: 종료 0, tick.action=started, tick.slot=2026-10-17T09:05:00+09:00, catchUp=false(5분 창), round.state=complete, round.counts.newTextVersions=1
TICK --fixture-manifest "$WORK/m-0905-manifest.json" <<'EOF'
{"schemaVersion":"zoop-ingestion-s2-1","sourceId":"synthetic-source","scopeId":"body","initialFrom":"2026-10-17T09:00:00+09:00","now":"2026-10-17T09:05:30+09:00"}
EOF

# 2) 같은 slot의 두 번째 trigger(09:20). 재실행이 아니라 저장된 결과의 replay다. 기대: 종료 0, tick.action=replayed, round는 1)과 같다.
TICK <<'EOF'
{"schemaVersion":"zoop-ingestion-s2-1","sourceId":"synthetic-source","scopeId":"body","now":"2026-10-17T09:20:00+09:00"}
EOF

# 3) 정규 tick(09:35). initialFrom 없음: 저장된 성공 경계(2026-10-17T09:05:00+09:00)가 window.from이다.
#    기대: 종료 0, tick.action=started, catchUp=false(정확히 30분), round.completion=source-zero, round.checkpoint.through=2026-10-17T09:35:00+09:00
TICK --fixture-manifest "$WORK/m-0935-manifest.json" <<'EOF'
{"schemaVersion":"zoop-ingestion-s2-1","sourceId":"synthetic-source","scopeId":"body","now":"2026-10-17T09:35:00+09:00"}
EOF

# 4) 운영 시간 밖(18:00). 기대: 종료 0, tick.action=not-due, reason=outside_operating_window. registry·manifest·state를 읽거나 만들지 않으므로 manifest 인자가 필요 없다.
TICK <<'EOF'
{"schemaVersion":"zoop-ingestion-s2-1","sourceId":"synthetic-source","scopeId":"body","now":"2026-10-17T18:00:00+09:00"}
EOF
```

기대값은 이 절차의 설계값이다. 위 **복사용 셸 명령 자체는 실행해 확인하지 않았다**(같은 흐름을 아래 smoke가 실제 CLI로 검증한다). 모든 slot의 정규 trigger는 같은 모양의 한 줄이고 manifest 경로만 해당 slot의 것으로 바뀐다.

**검증(`ai/pipeline/scripts/round_smoke.py`, `make pipeline-smoke`에 포함).** 모두 실제 `zoop-ai-ingest` subprocess이고 시계는 토요일 2026-10-17·일요일 2026-10-18의 주입 `now`다. 기대 slot·window·roundId는 스펙과 계약의 authored literal이며 schedule 구현을 import하지 않는다. 모든 자식은 소켓·DNS를 거부하는 audit hook 아래 실행되고, 충돌·정지·"엔진 호출 금지"는 throwaway wrapper의 monkeypatch일 뿐 production hook이 아니다.

- **slot 경계:** 11개 not-due 시각(초 단위, 자정, 일요일, UTC·-05:00 표기)은 exit 0이고 실제 registry·manifest·ledger를 열지 않으며(관찰 hook이 `sqlite3.connect`·`flock`·`mkdir`·해당 파일 open을 막는다) state 디렉터리를 만들지 않는다. 읽을 수 없는 registry도 not-due에는 무관하다. 10개 due 시각은 literal slot·catchUp(29:59·30:00 false, 30:01 true)로 대응된다.
- **기준선과 시계:** `initial_baseline_required`·`initial_baseline_conflict`·`slot_not_after_baseline`(baseline 이전의 시계, 되돌려진 시계 포함)·`fixture_manifest_required`·`clock_in_future`(2099와 실제보다 1분 앞)·timezone 없는 시각·알 수 없는 키·`--require-store`는 쓰기 전에 거부된다.
- **같은 slot 반복:** 저장된 결과의 replay이며 engine 진입점을 막아도 바이트가 같다(다르게 표기한 같은 baseline 포함). 다른 baseline·다른 manifest는 `slot_input_conflict`이고 ledger는 변하지 않는다.
- **교차 round 중복·수정:** 다음 slot은 정확한 저장 경계에서 시작하고 같은 기사는 같은 버전을 재사용하며 다른 기사는 별개 ID다. 본문이 바뀐 기사는 같은 `documentId`의 새 version이다(자정을 넘겨도).
- **실패·partial·zero:** failed·partial page는 exit 3이고 경계가 그대로이며 중복 trigger가 재시도하지 않는다. coverage가 있는 0건은 경계를 옮기고 없는 0건은 옮기지 않는다. 다음 slot은 공백을 덮고 partial round가 준비한 text는 재사용된다.
- **숨은 재시도 없음(복구 가능한 incomplete):** 두 번째 page의 body 파일이 없어 incomplete가 된 round에서 파일을 복원해도 같은 slot tick(manifest 유무 무관)은 engine을 막은 채 `incomplete`를 replay하고 ledger가 변하지 않으며, 명시적 `resume`만 완료한다.
- **늦은 trigger·주말:** 13:05–14:35가 비어도 15:20은 15:05 한 round를, 17:59:59.999999는 17:35를 시작한다. 18:00·자정은 ledger 바이트를 바꾸지 않고, 일요일 09:05는 토요일 17:35 경계에서 시작하며 slot 12개는 정확히 12개 round다.
- **crash:** round 등록 전 종료(ledger 비어 있음, 같은 slot 정상 시작), 첫 page commit 뒤 종료(page 입력 파일을 지운 뒤 `recovered` 한 번, 중복 page·후보 없음, 이후 replay), page 저장 직후 종료한 오래된 slot은 다음 slot이 자동 resume하지 않고 명시적 `resume`은 `checkpoint_stale`이다. 종료된 `running` round는 변경된 scope 설정이나 철회된 grant에서 거부되고 `running`으로 남는다.
- **동시성:** 한 tick이 ledger lock을 쥔 채 멈춘 동안 같은 slot의 두 tick은 기다리거나 쓰지 않고 `ingestion_busy`이며, 쥔 tick만 한 번 시작하고 다음 tick은 replay한다.
- **권리:** 철회·제거·실제 시계 기준 만료 grant에서 due tick과 replay 모두 본문 없이 `source_unauthorized`이고 ledger는 변하지 않는다. not-due는 registry를 열지 않고 exit 0이며 권리를 되살리면 같은 ledger가 정상 동작한다.

**실행 결과(2026-10-21, 로컬 작업 트리·미커밋).** `tests/test_ingestion_schedule.py` **37 passed**, pipeline 전체 시험 **1461 passed**, `make pipeline-smoke`의 모든 명령이 통과했다. 새 `round_smoke.py`는 자식 프로세스 **94개**(tick 92·resume 2), 검사 묶음 **20개**, not-due 시각 **11개**·due 시각 **10개**를 실행했고 네트워크 audit 거부 아래에서 `providerCalls=0`·`modelCalls=0`, 임시 상태 정리 `true`였다. 합성 입력·격리 상태에서 검증했으며, 시간 경계는 주입한 시계로 재현했다. 실제 공급원, 원격 CI, trigger 배포, 성능, 운영 지연 보장을 뜻하지 않는다.

**하지 않는 일(FS058·#55·#72는 이것으로 완료되지 않는다).** 실제 공급원 탐색·변경 cursor·검증된 겹침 범위(권리 확인 대기), trigger 배포(cron·AWS 보류), round마다 분석(S2-2/S3 dispatch) 실행, 05분 회차 10분·35분 회차 40분까지의 조회 반영 기한(정기 갱신 반영 시간, `12-비기능-상세.csv` 356–392행), 18:00 종료 때 사유 기록(NFS009 7번), 재시도 정책(스펙의 열린 질문)은 구현하지 않았다. provider coverage·누락 없음·운영 지연 보장도 주장하지 않는다.

**`enqueue-round`와의 관계(추가).** `tick`은 여전히 round를 등록하거나 분석하지 않는다. 완료된 회차를 S2-2 job으로 등록하는 별도 operator 명령 `zoop-ai-extract enqueue-round`가 생겼지만(아래 S2-2 절의 "완료된 회차의 S2-2 등록") `tick`은 그것을 부르지 않고, 자동 주기 실행·trigger 배포(cron·AWS)·교차 회차 중복 제거는 여전히 없다.

## 이벤트·SAME·주제 후보 (S2-2: authored replay 또는 live provider)

`zoop_ai_pipeline.extraction_cli`의 `run/submit/resume/inspect/cancel`(`--initial-only`는 `run`·`resume` 전용)은 S2-1 ingestion 상태를 **읽기 전용**으로 소비하고 전용 `--state-dir`의 `extraction.sqlite3`에만 쓴다. 분석 규칙(기사 projection, 요청 preimage·digest, 인용 해석, 엄격한 응답 검증, SAME 규칙, 후보 ID)은 네이티브 계약(`extraction_replay.py`, `extraction_contracts.py`)이며 replay와 live가 **같은 규칙**을 쓴다(`ADAPTER_VERSION`=`zoop-extraction-native-replay-2`, `LIVE_ADAPTER_VERSION`=`zoop-extraction-native-live-2`; 공유 규칙을 바꾸면 둘 다 올린다). Postgres·Neo4j·앱/S1 상태, 원본 PoC 코드·프롬프트에는 연결하지 않는다. authored replay는 독립 AI 추론이 아니다. live job(`provenance.executionMode:"live"`, `recordingKind:"provider"`)만 명시적 게이트 뒤에서 provider를 부르며 아래 live 절을 따른다. `live-binding` 하위 명령은 S2에 없다(S3의 `zoop-ai-relation live-binding`이나 `python -m zoop_ai_pipeline.live_runtime binding`이 같은 binding을 출력하며 S2·S3 binding은 동일하다). 결과는 승인·게시가 아닌 event/topic **후보**다. 이벤트 후보는 정확한 인용(S1 exact와 같은 mapped-run 규칙 + ingestion resolver), whole-event 비교(all-member 충돌·근거 부재·multi-SAME hold), 문서/mention/event 별도 ID를 갖고 topic 후보는 별도 `zoop-topic-*` 계약·영수증으로 만든다. 저장소 루트에서 재현한다.

**네이티브 replay 형식 `zoop-analysis-replay-1`.** fixture는 `{format, synthetic, recordingKind:"authored-test", promptVersion, analysisVersion, records:[{stage:"extract"|"compare", requestDigest, response}]}`이며 응답은 그 응답이 답하는 **요청의 정확한 digest**(`sha256`(canonical JSON `{stage, input, version: analysisVersion}`))로 찾는다. 요청 본문(원문)은 fixture에 복사하지 않는다. `promptVersion`·`analysisVersion`은 운영자가 붙이는 **authored 라벨**이며 모델·프롬프트 지문이 아니다. 헤더(형식·synthetic·recordingKind·promptVersion·analysisVersion)만 접수 때 읽고(`replay_fixture_invalid`/`replay_provenance_conflict`/`replay_prompt_version_conflict`), 레코드 전체(단계·digest 형식·중복·추가 키)는 첫 조회에서 호출 예약 전에 검증한다(`replay_fixture_invalid`로 호출 0건 중단). 응답이 없으면 `replay_response_missing`이다. 옛 `investmate-replay-v2` 파일과 변환기는 지원하지 않는다. 숫자 offset은 인용이 정확히 선택하는 정수일 때만 유지되고, 아니면 본문에서 **유일한** 인용으로 다시 구하며 없거나 반복되면 영구 `*_reply_invalid`다. 후보 ID의 fingerprint는 어댑터 버전(`zoop-extraction-native-replay-2`)·후보 버전·두 라벨·catalogue digest에서 나오므로 라벨이나 catalogue가 다르면 같은 문서도 다른 ID를 갖는다. 분석 규칙을 바꾸면 어댑터 버전을 올려야 한다. `Article.version`·요청 preimage·mention JSON 모양은 원본 PoC가 한 번 계산한 literal(`tests/data/native_analysis_golden.json`)과 일치하도록 시험한다.

**이전 어댑터로 저장된 S2 job.** 기업 ID 검증을 추가한 `native-replay-2`·`native-live-2`는 이전 native `-1` 및 PoC 어댑터 job을 다시 해석하지 않는다. 원장 `zoop-extraction-ledger-1` 스키마는 그대로이고 job마다 저장된 `binding.adapter.version`으로 구분한다. 옛 job은 **읽기용 기록**으로만 남는다: `inspect`는 저장된 상태·binding·호출 요약을 그대로 보여 주되 `delivery`를 `withheld/analysis_contract_changed`로 막고 후보 내용(eventCandidates/topicCandidates)을 싣지 않으며 원천·권한을 읽지 않는다. 저장된 raw receipt·후보·기존 연결 판정은 수정하거나 삭제하지 않는다. `run`/`resume`은 어떤 상태(queued·stopped·reconciling·ready)에서도 원천 읽기·호출·상태 쓰기 **전에** `analysis_contract_changed`로 거부하고 재분석·복사·자동 변환을 하지 않는다. S3 submit·graph·handoff가 그 job을 upstream으로 삼으면 같은 코드로 거부·withheld된다. `cancel`은 옛 job에도 기존 의미대로 쓸 수 있는 명시적 정리 수단이고, 새 native job은 같은 원장에 함께 둘 수 있다. 다시 분석하려면 운영자가 현재 fixture와 **새 job id**(또는 새 상태 디렉터리)로 명시 재제출한다(후보 ID도 달라진다). 새 원장에 이전 build를 돌리지 마라.

**기업 표기 → 마스터 ID 검증(FS077, WBS 6.6.16).** AI가 선택한 `participant.company_id`는 고정 catalogue의 `name` 또는 명시 `aliases`에 표기가 유일하게 대응할 때만 통과한다. 비교는 `casefold`와 공백 축약만 하며 문장부호·법인 접미사는 유지한다. ticker·유사 문자열·외부 지식으로 별칭을 만들지 않는다. 원래 표기는 바꾸지 않고 `null`은 유일한 별칭이 있어도 채우지 않는다. 알 수 없는 ID, 다른 기업 ID, 중복 이름·별칭에 대한 nonnull 선택은 raw 응답을 먼저 저장한 뒤 `extraction_reply_invalid`로 중단한다(후보 저장·자동 재전송 없음). 이것은 **동일성/응답 계약 실패**이지 의미 판단의 `REJECT`가 아니다. snapshot member도 같은 규칙으로 접수하며 위반하면 호출 전에 `snapshot_member_invalid`다. live 추출 프롬프트도 이 규칙을 명시하고 prompt digest가 새 runtime identity에 반영된다.

**오프라인 동일성 roundtrip.** `extraction_smoke.py --identity-only --keep --report /절대/경로/identity.json`은 설치된 ingestion/extraction CLI와 실제 SQLite 원장으로 이름·별칭·동명·미등록·위조 ID, SAME/NEW/HOLD, 다중 SAME, 반복 입력, catalogue·raw version 경계를 검사한다. 네트워크/DNS는 CLI audit hook으로 거부하고 provider 환경은 전달하지 않는다. `--keep`은 새 합성 상태만 보존하며 `--report`는 JSON 결과를 저장한다. 이 증거는 자동 마스터 생성, 실제 AI의 이름 추출 정확도, 동명이인 구분 품질, 검색 목록의 완전성, 앱 canonical ID 등록이나 전체 #75 인수 완료를 뜻하지 않는다. SAME/NEW는 여전히 승인 전 후보이며 주제 승인은 별도다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_extraction.py ai/pipeline/tests/test_extraction_replay.py ai/pipeline/tests/test_ingestion.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/extraction_smoke.py
```

**등록 전용 `submit`(CLI 명령이다. HTTP는 `ai/service`의 별도 `/internal/v1/extraction-jobs` 가족이 서버 사전 승인 요청으로만 호출하며 호출자가 본문·fixture를 고르지 못한다).** `extraction_cli submit`은 `run`에서 등록 절반만 분리한 명령이다. replay job은 같은 stdin 요청과 필수 `--replay`로 입력과 replay 파일 hash를 불변 binding으로 먼저 저장해 `queued` job을 만들고 `inspect`와 같은 결과를 돌려준다. 모델 구성·stage 실행·호출 예약·후보 쓰기·네트워크는 없고(`calls=[]`, `usage.replayCalls=0`) 등록 때 ingestion과 `--sources`는 읽는다. replay 파일 hash가 job 입력 digest에 들어가므로 `--replay`가 필요하고(없으면 `replay_fixture_required`), job에 고정되지 않는 `--topic-replay`는 `fixture_not_allowed`이며 topic stage의 fixture는 이후 `resume`/`run`에서만 지정한다. **live job은 fixture를 받지 않는다**(`--replay`/`--topic-replay`는 `fixture_not_allowed`). 같은 `jobId`와 같은 입력의 재제출은 저장된 job을 `inspect`처럼 보고만 한다. queued·stopped·ready·cancelled 어느 상태에서도 resume·재고정·상태 초기화·호출을 하지 않으며 현재 권한은 반환 결과의 `delivery`에만 적용된다(철회·grant revision 변경이면 `withheld`와 종료 코드 2이지만 고정된 binding은 바뀌지 않는다). 다른 입력이나 다른 replay bytes는 아무것도 쓰지 않고 `job_input_conflict`이며, 잘못된 fixture를 고정한 job은 같은 jobId로 고칠 수 없어 새 jobId를 쓴다. 실행은 이후 `resume`(replay는 필요한 같은 `--replay`)이 하고 권한·binding은 그때 다시 검사하므로 submit 뒤 철회·grant revision 변경은 호출 없이 `stopped`다. queued job은 `cancel`로 호출 전에 취소할 수 있다. `run`은 같은 등록 경로(`Extractor.freeze`) 뒤 `resume`하는 기존 편의 명령이다. 아래 시험·smoke 수치는 live 도입 이전 기록이며 현재 값은 통합 실행 결과로만 기록한다.

이전 기록의 결과는 **90 passed, 1 warning**(extraction 47 + ingestion 43)과 smoke `status=passed, providerCalls=0, modelCalls=0`이었다(현재 값이 아님). smoke는 실제 ingestion/extraction subprocess에 socket audit hook을 걸고 same/distinct event·topic, 충돌·누락 날짜, multi-SAME, 한글/emoji/separator/반복 quote, raw-only 변경, 위조 입력, 철회 grant, receipt/stage 중단 복구, 잘못된 fixture의 receipt 미생성, separator snapshot member 거부, ingestion 읽기 쪽 mode/bytes/파일 불변을 검사한다. ingestion `export`와 extraction의 ingestion 접근은 shared flock과 `immutable=1` 읽기 전용 열기이며 중단된 writer가 남긴 비어 있지 않은 WAL은 `ingestion_recovery_required`로 거부한다. S3 소비자용 `Store(existing=True)`/`Extractor.export`도 같은 읽기 전용 정책이다. retrieval·cross-job cache·앱 등록·승인 topic은 구현하지 않았다. wire/binding/복구 규칙은 [AI 실행 계약의 S2-2 절](../../docs/design/ai-system.md#s2-2-오프라인-이벤트same주제-후보-준비)을 따른다.

**live provider 경로(S2-2).** `provenance`의 `(executionMode, recordingKind)`는 `(replay, authored-test)` 또는 `(live, provider)` 한 쌍뿐이다(섞이면 입력 검증 오류). 두 모드는 같은 wire·Article hash 규칙을 쓰지만 어댑터와 runtime binding이 달라 후보 ID는 구분된다. `Article.allow_model_send`는 여전히 false, publisher는 `""`다. `sourceKind`(synthetic|actual)는 문서 사실로 독립이다. live 여부는 별도 플래그가 아니라 submit/run의 provenance로 정해지고 resume·inspect·cancel은 저장된 binding의 `live` 키로 판별한다. 게이트(`ZOOP_AI_PIPELINE_LIVE_ENABLED`)·모델·endpoint·키·예산은 `live_runtime`이 읽고(환경 이름과 예산·실패 코드는 [`docs/development/ai-runtime-setup.md`](../../docs/development/ai-runtime-setup.md) §10), **submit/freeze는 게이트와 비밀 아닌 설정만, 실제 전송만 키·예산 디렉터리·한도가 필요**하다. replay job·inspect·cancel·export·저장된 receipt 복구는 환경도 키도 읽지 않는다. 동결은 `binding.adapter.version="zoop-extraction-native-live-2"`과 `binding.live={runtime(LiveRuntime.binding() 그대로), bindingDigest, analysisVersion:"live-"+identity, promptVersion}`이고(`replay` 키와 함께 존재하지 않음) `inputDigest = digest({request: wire, liveBindingDigest})`다. 같은 jobId에서 환경이 바뀐 재제출은 `job_input_conflict`, 바뀐 환경으로 resume하면 호출 전에 `live_config_changed`다. 호출 순서(job·stage·ref당 시도 하나)는 순수 `prepare` → 설정 일치 확인 → 보내는 **모든 문서**의 현재 권한(read·quote-display·**model-send**, 그 stage의 purpose·recipient, 동결 grant revision) → `calls` 행 내구 예약(`started`) → 예산 예약·authorize(설정·fence·권한 재확인) 뒤 소켓 직전 → **HTTP 응답은 2xx 여부와 무관하게 raw receipt를 먼저 저장**(`received`) → strict decode → 기존 파서·정확한 인용 → 수신 후 권한 재확인 → stage 저장이다. 예약 이후 전송 직전까지의 거부(권한·설정·예산·fence)는 그 슬롯을 `state=unsent, verdict=<code>`로 **종결**한다(재시도 없음, 새 jobId). 전송 오류·시간 초과는 `live_response_unknown`으로 `started`·응답 없음, job은 `reconciling/reconcile_only`, 사용량은 0이 아닌 null이고 예산은 최악값을 유지하며 **자동 재전송은 없다**(이후 resume도 같은 코드, cancel만 가능). 받은 응답을 쓸 수 없으면(`live_http_<n>`, `live_reply_not_json`, `live_output_truncated`, `live_model_refusal`, 파서·인용 실패) receipt와 `verdict=<code>`만 남고 stage가 멈추며 다른 호출로 고치지 않는다. 저장된 receipt의 복구는 동결 binding(`LiveRuntime.from_binding`)으로 환경·키 없이 한다. 모델이 보는 것은 extract=incoming 문서, compare=incoming+해당 snapshot event의 모든 문서, topic=이벤트 문서 전부이고 snapshot member의 원천에도 model-send가 필요하다. 모델이 null로 둔 인용 offset은 정확한 단일 literal quote에서만 채운다. `Authority.check(…, purpose, recipient)`는 둘을 함께 받을 때만 `model-send`·`naver-search` 금지(`naver_search_ai_prohibited`)·purpose/recipient 허용 목록(빈 목록은 허용 아님, `source_purpose_or_recipient_denied`)을 확인하며 replay·ingestion 호출은 그대로다. `run|resume --initial-only`는 writer lock 아래에서 dispatch 표지·`calls` 행·`queued` 아님 중 하나라도 있으면 아무것도 쓰지 않고 `initial_dispatch_taken`(exit 2)이며 운영자 복구는 plain `resume`이다. live 결과의 `usage`는 `{executionMode:"live", replayCalls:0, providerCalls, receivedCalls, startedWithoutReceipt, unsentCalls, paidModelCalls, inputTokens, outputTokens, reasoningTokens, estimatedUsd, chargedUsd(미보고 값이나 receipt 없는 전송이 있으면 null), creatorJobId}`이고 `calls[]`는 replay의 기존 6개 키에 더해 `attemptId, recipient, purpose, httpStatus, model, usage, cost`를 갖는다. 시험·smoke 명령은 아래와 같고 결과는 통합 실행 뒤에만 기록한다(`--live`는 유료이며 Main만 실행한다).

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_extraction_live.py ai/pipeline/tests/test_extraction.py ai/pipeline/tests/test_extraction_replay.py -q -p no:cacheprovider
ai/pipeline/.venv/bin/python ai/pipeline/scripts/extraction_smoke.py                  # replay smoke(socket audit hook)
ai/pipeline/.venv/bin/python ai/pipeline/scripts/extraction_smoke.py --live-loopback   # live 경로 전체를 실제 CLI subprocess로, 127.0.0.1 결정적 시뮬레이터·가짜 키, 유료 호출 0
```

**완료된 회차의 S2-2 등록 `enqueue-round`(CLI 전용, S2-1 회차와 S2-2 job을 잇는 등록 절반. 실행·주기 실행·교차 회차 중복 제거가 아니다).** `zoop-ai-extract enqueue-round --state-dir X --ingestion-state-dir I --sources R [--replay F]`는 **완료된** ingestion 회차 하나를 읽어 준비된 관측마다 `submit`과 **같은 `Extractor.freeze`**로 `queued` job 하나를 등록한다. 실행(`resume`)·호출 예약·후보 쓰기·네트워크·새 ledger·table·column·migration은 없다. stdin은 모든 키가 필수인 `{schemaVersion:"zoop-extraction-s2-2", enqueueId, roundId, sourceId, provenance, promptVersion, catalogue, snapshot, topic}`(`topic`만 `null` 가능)이고 `enqueueId`는 `^[A-Za-z0-9._-]{1,120}$`다. catalogue와 snapshot은 **호출자가 명시**하며 자동으로 만들거나 비워 두지 않는다. `--replay`는 replay provenance에 필수(`replay_fixture_required`), live에는 금지(`fixture_not_allowed`)이고 `--topic-replay`(`fixture_not_allowed`)와 `--initial-only`(`initial_only_not_allowed`)는 받지 않는다. 기존 `run/submit/resume/inspect/cancel`의 동작은 바뀌지 않는다.

**job ID와 멱등.** `"s2r-" + digest({format:"zoop-round-enqueue-1", enqueueId, observation:{roundId, sourceId, page, ordinal, documentId, rawVersion, documentVersion}})`(68자)이다. `enqueueId`는 (sourceId, roundId) 안에서만 뜻이 있고 전역 batch가 아니다. 설명자(prompt·catalogue·snapshot·topic·provenance)와 replay/live 입력은 ID에 들어가지 않는다. 그래서 같은 `enqueueId`와 같은 관측에 다른 설명자·replay bytes·live runtime을 주면 새 job이 아니라 `job_input_conflict`이고(걸러질 관측이어도 같다) 다른 분석은 새 `enqueueId`로 명시한다. 같은 documentVersion이 다른 회차에서 다시 나오면 **다른 job**이다. 교차 회차 중복 제거나 분석·유료 호출 재사용은 없고 주장하지도 않는다.

**순서.** (1) 순수 검증: stdin·플래그와 replay면 헤더(`replay_fixture_*`), live면 비밀 아닌 runtime 설정(`live_*`)을 **관측이 0건이어도** 먼저 검증한다(키·네트워크 없음). (2) `--sources` registry를 한 번 고정하고 ingestion을 공유 읽기 전용(`Store(existing=True)`)으로 열어 `Ingestor.authorize_round`로 저장된 회차의 원래 source·scope·설정을 현재 registry와 대조한다(`round_not_found`가 권한 오류보다 먼저이고, `source_unauthorized`·`scope_configuration_conflict`·`registry_changed`, 만료는 실제 UTC 시계). `read`+`store`는 **요약·참조를 읽기 전에** 확인하고 참조를 100개씩 끝까지 읽은 뒤 준비된 문서가 하나라도 있으면 `quote-display`도 확인한다. 권한 오류는 0건·전부 held인 회차에도 회차·skip 메타데이터를 드러내지 않는다. ingestion은 extraction 락을 잡기 전에 닫는다(`ingestion_busy`·`ingestion_recovery_required`). (3) 회차가 `complete`가 아니면 `round_not_complete`, 참조 수·순서·상태가 모순이면 `round_refs_inconsistent`다. (4) 준비된 모든 관측(모호·snapshot·중복으로 걸러질 것 포함)의 ID를 필터보다 먼저 만들고 `(page, ordinal)` 순서로 **첫 일치 규칙**을 적용한다: `held`(detail=hold 코드, documentVersion null), `ambiguous`(detail=ambiguity 코드), `in_snapshot`(documentVersion이 어느 snapshot member의 것, detail null), `duplicate_in_round`(같은 documentId·documentVersion이 앞서 계획된 것, detail=그 jobId). ID·근거·catalogue를 만들어 내지 않는다. (5) 원장 선점검: 계획된 job이 있으면 extraction 쓰기 원장을 열고, 계획은 없고 준비된 관측만 있으면 **읽기 전용**으로 연다. extraction 상태가 **완전히 없을 때**, 곧 디렉터리가 없거나 빈 디렉터리일 때만 "이전 job 없음"이며 아무것도 만들지 않는다. 쓰는 중이면 `extraction_busy`, 중단된 writer의 비어 있지 않은 WAL이면 `extraction_recovery_required`이고, 잠금이나 DB 중 하나만 있는 디렉터리·외부 파일·symlink 같은 **불완전하거나 외부의 상태는 "이전 job 없음"으로 읽지 않고 닫힌다**(`extraction_state_missing`·`state_namespace_conflict`·`state_namespace_invalid`). 준비된 관측이 없으면 extraction 원장에 접근하지 않는다. 준비된 모든 ID를 조회해 같은 입력이면 `existing`, 다른 입력이면 필터된 관측이어도 `job_input_conflict`(snapshot을 바꿔 이전 binding을 가리는 우회 차단), 옛 어댑터 binding이면 `analysis_contract_changed`, 필터된 관측의 ID가 같은 입력으로 이미 있으면(손으로 만든 `submit`만 가능) `enqueue_plan_conflict`다. 새 계획 job은 원천 context와 snapshot member의 정확한 인용을 쓰기 전에 검사한다. (6) 새 job을 순서대로 `freeze`한다. 각 job은 자기 transaction이고 첫 실패에서 멈추며 이후는 `not-attempted`다. 이미 있는 job은 resume하지 않고 상태(ready·cancelled·stopped)도 바꾸지 않는다. 원장을 닫다가 실패하면(commit 뒤여도) 실제 등록 개수는 그대로 둔 채 그 코드(정제된 `persistence_failed` 등)가 이 batch의 `error`가 되어 `incomplete`로 보고되며, 쓰기 전 거부는 닫기 오류로 가려지지 않는다. (7) **어떤 보고도(complete·incomplete·0건) 내기 직전에** 현재 registry로 권한을 다시 확인한다. 실패하면 `{schemaVersion, error:{code, partialRegistration}}`만 내고 exit 2이며 `partialRegistration`은 **이번 호출이 commit한** job이 있는지만 말하고(이미 있던 job은 세지 않는다) ID·회차 데이터는 담지 않는다. 닫기 실패가 있었어도 이 재확인이 보고보다 먼저 적용된다.

**출력과 종료 코드.** 정규 JSON `{schemaVersion, enqueueId, round:{roundId, sourceId, inputDigest, provenance, completion}, outcome:"complete"|"incomplete", jobs:[{jobId,page,ordinal,documentId,rawVersion,documentVersion,registration:"registered"|"existing"|"failed"|"not-attempted"}], skipped:[{page,ordinal,documentId,documentVersion,code,detail}], counts:{refs,jobs,registered,existing,failed,notAttempted,skipped}, error:null|{code}}`이다(`round`의 값은 ingestion 결과의 것). exit 0은 complete(0건·전부 existing 포함)이고 exit 2는 (a) 쓰기 전 거부의 일반 `{schemaVersion,error:{code}}`, (b) 일부만 등록된 incomplete의 **전체 보고**, (c) 마지막 권한 재확인 실패의 위 오류다. `existing`은 "이 입력의 job이 이미 저장돼 있다"는 보고일 뿐 queued 상태를 꾸며 말하지 않는다.

**일부 등록은 정직하게 남는다(전부-아니면-전무가 아니다).** 선점검을 통과해도 등록 중에 권한이나 원천이 바뀌면 일부만 durable할 수 있다. 롤백·cancel·자동 재시도는 없고 같은 명령을 다시 실행하면 이미 등록된 prefix는 `existing`, 나머지는 `registered`로 보고된다. 이 저장소 밖에서 같은 ID를 손으로 `submit`한 job이 있으면 엄격한 prefix도 보장하지 않는다. 쓰기 원장을 연 호출은 SQLite 파일(WAL 생성·삭제)을 건드릴 수 있으므로 약속은 job 행·호출 수 불변이지 쓰기 원장 파일의 byte 불변이 아니며, ingestion은 언제나 byte·mode·mtime이 그대로다. 첫 freeze가 실패해 행이 하나도 없으면 빈 원장만 남고 같은 `enqueueId`에 다른 설정이 허용된다. 이 명령은 ingestion checkpoint를 움직이지 않는다.

**live.** live provenance의 등록은 게이트(`ZOOP_AI_PIPELINE_LIVE_ENABLED=1`)와 비밀 아닌 runtime 설정(절대 경로의 예산 디렉터리 포함, 만들지 않는다)만 필요하고 키·한도·네트워크는 필요 없다. 등록은 model-send 권한·예산을 쓰지 않으며 실제 전송(`resume`)에서 기존 규칙(권한·키·예산·`live_config_changed`)이 그대로 적용된다.

**HTTP 비채택.** 이 명령으로 만든 job은 CLI job이며 `ai/service`의 `/internal/v1/extraction-jobs`가 채택하지 않는다. 같은 id를 서버 승인 파일에 적어도 첫 `submit`이 pipeline에 이미 있는 id를 보고 409 `job_id_unavailable`(승인 항목이 없으면 403 `request_not_approved`)이고, 읽기는 서비스 원장에 accepted 행이 없어 404 `job_not_found`이며, dispatcher는 서비스 원장의 pending 행만 claim하므로 이 job을 실행하지 않는다. 소스 근거는 `ai/service/src/zoop_ai_service/extraction_jobs.py`의 `_refuse_adoption`·`_owned`와 `extraction_ledger.py`의 `claim_next`이며 이 smoke는 HTTP를 실행하지 않는다.

**하지 않는 일.** `tick`이 이 명령을 부르거나 회차 완료 뒤 자동으로 등록·실행하지 않는다(trigger·cron·AWS 없음, 주기 실행이 아니다). 이 명령은 job을 `queued`로만 만들며 `resume`은 운영자가 따로 한다. 교차 회차 중복 제거, 분석·유료 호출 재사용, snapshot·catalogue 자동 구성이나 retrieval 완전성은 주장하지 않는다(catalogue와 snapshot은 호출자가 얼린 입력이다). 실제 공급원·실제 모델 품질·S3/graph/handoff 자동 연결·앱 등록·공개는 이 범위가 아니며 FS058·FS074·FS076 전체는 이것으로 완료되지 않았다.

**검증 결과(2026-10-22, 로컬).** `tests/test_round_enqueue.py` 75개와 pipeline 전체 1,537개가 통과했다. 기존 서비스→pipeline 통합 시험 125개도 통과했다. 손상된 원장을 없는 원장으로 처리하던 경우와 등록 후 close 오류가 결과를 가리던 경우는 실패를 재현한 뒤 수정해 회귀 검사를 통과시켰다.

**종단 검사.** `scripts/round_enqueue_smoke.py`와 이를 포함한 `make pipeline-smoke`가 통과했다. 실제 자식 프로세스 141개에서 230개 참조·3페이지를 읽어 219개 작업과 11개 제외 항목을 확인했다. 최초 등록은 모두 `queued`·호출 0건이고 재접수는 219개 `existing`이었다. 입력 충돌·현재 권한·손상 상태·중단 복구·부분 등록·등록 후 close 실패의 결과 보존을 확인했으며, live 설정도 키·네트워크·예산 파일 생성 없이 3개 작업을 등록했다. 별도 명시적 replay 실행으로 두 작업을 `ready`로 만들고 취소·중단된 작업과 함께 재접수해도 상태·호출 수가 바뀌지 않음을 확인했다. 수집 원장의 바이트·권한·수정 시각은 유지됐고 다음 `tick`은 정상 진행했다. 모델·공급자 호출은 0건이며 실제 모델 품질이나 운영 스케줄 검증은 아니다.

**완료 회차의 서비스 실행 계획 `plan-round`(CLI 전용, 오프라인).** `zoop-ai-extract plan-round --ingestion-state-dir I --sources R --principal P --output DIR [--replay F [--topic-replay T]]`는 완료된 회차를 `enqueue-round`와 같은 계획기로 읽어 새 디렉터리에 계획 파일만 만듭니다. `--state-dir`은 받지 않으며 extraction 원장·작업 등록·모델·네트워크를 사용하지 않습니다. 출력은 `approvals.json`(S2 승인 항목), `relation-upstreams.json`(S3 입력 쌍), `manifest.json`(계획 ID·digest·S2 제출 필드), `receipt.json`(앞 세 파일의 digest)입니다. manifest에는 분석 입력 본문·비밀·원문을 싣지 않습니다. 수동 모드에서는 사람이 계획을 검토해 오프라인 설치하고, 별도 온라인 모드에서는 사람이 미리 정한 정책 안에서 같은 계획을 접수합니다([서비스 안내](../service/README.md)). 계획 생성 자체는 설치·배포·유료 호출을 승인하지 않습니다.

작업 ID는 계획 ID와 정확한 관측에서 유도한 `s2p-` 접두를 사용하여 `enqueue-round`의 `s2r-` 작업과 구분합니다. 서비스는 기존 CLI 작업을 HTTP 작업으로 재사용하지 않습니다. replay 계획은 분석 fixture와 필요한 topic fixture의 해시를, live 계획은 런타임 identity를 고정합니다(live에 fixture를 주면 `fixture_not_allowed`). 같은 입력을 같은 출력 경로에 다시 주면 기존 파일을 바꾸지 않고, 다른 입력은 거절합니다. 기존 경로를 덮어쓰지 않는 원자적 이름 변경을 지원하지 않는 플랫폼도 거절합니다. 계획 생성 시에는 구문·현재 원천 권한을 확인하며, snapshot 근거와 실행 문맥은 실제 dispatch에서 검사합니다.

**하지 않는 일.** 설치된 approvals를 자동으로 만들거나 바꾸지 않고, 유료 호출 승인·예산도 내지 않는다. 공개 `JobCreate`의 `planId` 처리는 구현했다고 주장하지 않는다(BE 대기). 실제 공급원·모델 품질·자동 주기 실행은 이 범위가 아니다.

**검증(2026-10-22, 로컬, 모델 호출 0).** 단위 시험 6개와 설치된 `plan-round`를 쓰는 실제 HTTP 시험 2개(주제 단계와 S3 `ready` 포함)가 통과했다.

**기존 계획의 읽기 전용 검사 `verify-plan`.** 서비스의 오프라인 설치와 온라인 접수가 함께 사용하는 내부 CLI이며 HTTP API가 아닙니다. stdin은 정확히 `{}`이고 `--state-dir`·출력 디렉터리·계획 생성 옵션을 받지 않습니다.

```sh
printf '%s\n' '{}' | zoop-ai-extract verify-plan \
  --plan-dir /absolute/reviewed-plan --expected-receipt-sha256 RECEIPT_SHA256 \
  --ingestion-state-dir /absolute/ingestion --sources /absolute/sources.json \
  --replay /absolute/extraction-replay.json
# 주제 replay 계획에는 --topic-replay가 필요합니다. live 계획에는 fixture를 전달하지 않습니다.
```

검사는 네 파일의 정확한 바이트·hash·길이·schema를 확인하고 현재 완료 회차와 같은 계획기로 다시 계산해 비교합니다. incoming과 snapshot의 모든 고유 관측도 현재 source-read/export 권한으로 다시 읽습니다. 성공 응답 `zoop-extraction-service-plan-verification-1`은 계획 ID·digest, receipt hash, principal·mode·pins·파일별 hash/크기·counts, 현재 source registry hash와 source binding digest만 반환합니다. 원문·요청 본문·비밀을 응답하지 않으며, 임시 계획·extraction 원장·job·예산을 만들거나 모델·네트워크를 호출하지 않습니다. live 검사는 공개 런타임 설정과 예산 디렉터리 신원만 고정하며 키·호출 상한을 요구하지 않습니다.

이 검사는 현재 읽기 권한과 계획 일치의 증거이지 model-send·비용·HOLD 최종 승인·앱 공개 허가가 아닙니다. snapshot 언급의 근거 일치와 실제 freeze 가능성은 기존 submit에서, 현재 원천 및 모델 전송 권한은 실제 사용 시 다시 검사합니다. 온라인 접수는 별도의 정책·누적 quota·불변 admission origin을 서비스 SQLite에 함께 기록하며 설치 파일을 실행 중에 교체하지 않습니다. 수동/온라인 권한은 섞이지 않습니다. 정책에 맞는 계획의 접수 구현과 실제 정책 설치·05/35 주기 실행·공개 반영은 구분합니다. 앱/AI의 역할과 10/40 새 조회 목표는 [공개 스케줄 책임](../../api/docs/GRAPH_READ_HANDOFF.md#수집분석-실행과-공개-스케줄의-책임)을 따릅니다.

## 관계·영향 후보와 HOLD 최종 승인 (S3, FS078·FS079)

`zoop_ai_pipeline.relation_cli`의 `run/submit/resume/inspect/review/cancel/live-binding`은 **완료된 S2 job 하나**(`upstream:{jobId,inputDigest}`)를 extraction·ingestion의 읽기 전용 snapshot으로만 소비하고 전용 `--state-dir`의 `relation.sqlite3`에만 쓴다. 호출자가 후보 JSON을 보낼 수 없고 event/topic 후보·catalogue·문서는 서버 소유 registry로 다시 검증한 S2 결과에서만 온다. replay job에서는 producer replay(`--replay`)와 **독립된** verifier replay(`--verifier-replay`)가 별도 파일·영수증이며 둘 다 authored 응답일 뿐 AI 의미 품질 주장이 아니다(live job에 주면 `fixture_not_allowed`). 후보의 `approved`는 항상 `false`이고(내부 감사 표지이며 앱 공개 승인이 아님) `eligible`은 **자동 verifier** 또는 **운영자 최종 승인** 가운데 한쪽이 현재 revision에서 결정했다는 뜻이다. 어느 쪽인지는 `eligibility.approvalBasis`가 말한다. 공개 OpenAPI·HTTP·UI·앱 등록·관리자 화면은 없고 이 CLI 자체는 그래프를 쓰지 않는다(완료된 job 하나의 **비공개** Neo4j stage는 별도 명령 `zoop-ai-graph`이며 아래 절, 활성 공개 상태 없음). 관계 유형(`SUPPLIES`·`INVESTS_IN`·`COMPETES_WITH`·`PARTICIPATES_IN`·`RELATES_TO_TOPIC`)은 FS055 공통 계약 확정 전의 보수적 임시 어휘다. 저장소 루트에서 재현한다.

```sh
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python -m pytest ai/pipeline/tests/test_relation.py ai/pipeline/tests/test_extraction.py ai/pipeline/tests/test_ingestion.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 ai/pipeline/.venv/bin/python ai/pipeline/scripts/relation_smoke.py
```

**국가 표기 비교(`zoop-relation-policy-2`, `zoop-country-context-1`).** S2의 `countries`는 기사에 적힌 지리 표기이며 원본 그대로 보존한다. S3 context를 만들 때만 [명시적 별칭 목록](src/zoop_ai_pipeline/country_context.py)과 ISO alpha-2 코드를 비교용 코드로 바꾼다. 영문 대소문자와 공백 차이만 정리하며 `Saudi Arabia`·`사우디아라비아`·`SA`, `한국`·`대한민국`·`South Korea`·`KR`는 각각 같은 국가로 비교한다. 목록에 없는 표기, `Korea` 같은 모호한 이름, `북미`·`유럽` 같은 지역은 추측하지 않고 `context.unresolvedGeography`에 원문으로 남긴다. `rawGeography`는 전체 원본 표기, `knownCountries`는 해석된 코드, `normalizationVersion`은 이 해석의 버전이다. 언어·URL·발행사·기업 본사로 국가를 채우지 않는다.

국가 선언이 없으면 `check=unknown`이다. 선언한 코드가 모두 해석된 국가 안에 있으면 `pass`이고, 알려진 국가가 없거나 미해결 표기가 남아 있어 불일치를 확정할 수 없으면 `unverified`다. 미해결 표기가 없는 명시적 국가끼리 다르면 기존 `country_context_conflict` HOLD를 유지한다. `pass`·`unverified`는 승인이 아니라 독립 verifier에 넘길 수 있다는 뜻이며, 국가 선언이 있으면 기존 context claim과 인용 검증을 그대로 거친다. 별칭 목록은 모든 국가명의 번역 목록이 아니며, 표기·해석 규칙이 바뀌면 context 버전도 바꿔야 한다.

새 S3 job은 policy와 country-context 버전을 불변 binding에 고정한다. 이전 binding은 기존 `job_binding_changed` 경로로 전달·검수·미완료 작업 실행이 차단되며 기존 후보·ID·영수증을 고치거나 다시 해석하지 않는다. 기존 결과 JSON은 당시 실행의 기록이다. 새 정책을 쓰려면 별도로 승인된 새 job이 필요하며, 이 변경만으로 과거 HOLD를 다시 실행하거나 승인하지 않는다.

Handoff bundle `zoop-graph-handoff-bundle-7`의 `sources[].policies.policy`도 버전을 구분한다. `zoop-relation-policy-2`는 기존 일곱 키에 `countryContext: "zoop-country-context-1"`이 반드시 있어야 한다. 보존된 `zoop-relation-policy-1`은 원래 일곱 키만 허용하며 새 pin을 붙일 수 없다. 누락·잘못된 context 버전·알 수 없는 policy·두 모양의 혼합은 생산자, 내부 HTTP, Java importer가 모두 거부한다. 이는 이전 bundle을 바이트 그대로 읽기 위한 계약이며, 이전 S3 job의 실행·재검증이나 권한 갱신을 허용하지 않는다. 외부 bundle 버전과 전달 artifact 종류는 그대로다.

**HOLD `allow`는 최종 의미 승인이다(`revalidate` 명령·재검증 예약은 제거됐다).** `review`의 wire(`{schemaVersion,jobId,relationCandidateId,expectedRevision,decision:allow|reject,reviewer,note}`)는 그대로이고 이벤트 종류도 `review`다. 새 `allow`의 effect는 `approved`, `reject`는 `excluded`이며 과거 원장에만 있는 `revalidation-requested`는 **이력**(재검증 요청이지 승인이 아님)으로 남고 새로 만들어지지 않는다. `allow`는 hold인 relation에 현재 revision에서만 받는다(`review_revision_conflict`·`review_target_not_hold`). 게다가 그 relation에 알 수 없는 provider 호출이 없어야 하고(`review_call_in_flight`), 저장된 후보가 결정적 precheck를 통과한 후보여야 하며 현재 정확한 원천·upstream으로 다시 계산한 후보와 같아야 하고(스키마·endpoint·정확한 인용·현재 권한. `review_candidate_ineligible`·`candidate_changed`), 현재 권한·binding·fence가 맞아야 한다(`source_unauthorized`·`upstream_changed` 등). 사람의 의견으로 이 gate는 우회되지 않는다. 이 승인은 **모델·verifier·impact 호출을 하지 않고** 키·환경도 읽지 않으며, 이전 자동 HOLD verdict와 claim 분포는 이력으로 불변이다. 승인된 relation은 `status=eligible, reasons=[], reviewPending=false, revision+1`이 되고 impact 단계는 받지 않는다(`not-applicable`). `reject`는 hold를 제외한다(`admin_rejected`). 이미 eligible이거나 reject된 것에 대한 결정·최종 reject 번복은 지원하지 않는다. 이전 `revalidation-requested`가 남은 hold(`reviewPending=true`)도 새 결정을 현재 revision에서 받으며 이전 의도는 소급 승인되지 않는다.

**`approvalBasis`.** `relations[i].eligibility = {status, reasons, revision, reviewPending, approvalBasis}`이고 `approvalBasis`는 eligible일 때만 `{kind:"automatic-verifier"|"operator-final-approval", revision, reviewer, decidedAt}`(revision은 결정 이벤트의 seq이자 `eligibility.revision`, 자동은 `reviewer=null`, `decidedAt`은 그 이벤트의 `createdAt`)이며 아니면 `null`이다. graph·handoff는 이 값을 믿지 않고 이력의 마지막 이벤트로 다시 증명한다(아래 두 절).

**live 경로(같은 원장·같은 후보 계약).** `Submit.provenance`가 `{executionMode:"live", recordingKind:"provider"}`이면 같은 provenance의 live S2 job을 요구한다(`provenance_conflict`). `inputDigest`는 요청 wire의 digest 그대로이고, 동결 시점의 `LiveRuntime.binding()`이 job binding `runtime`에 고정되며 환경이 바뀌면 `live_config_changed`로 호출 전에 멈춘다(replay binding은 바이트 동일). 호출 순서는 순수 prepare → 보내는 **모든 문서**의 현재 model-send 권한 → 내구 reservation → 예산 예약·authorize 뒤 한 번만 전송 → **원문 receipt를 파싱 전에 저장** → 엄격 decode → 정확한 인용 → 권한 재확인 → stage 저장이다. 알 수 없는 결과(`live_response_unknown`)는 `reconciling`이며 어떤 재전송·복구 호출도 없다. live verifier의 **기술적 실패**(전송·HTTP·형식·스키마 위반)는 verdict를 쓰지 않으므로 relation은 `pending`으로 남고(사람이 승인할 수 있는 HOLD가 아니다) job은 `stopped`, `failure={code:"verification_unavailable", detail:{calls:[{stage,ref,code}]}}`다. 유효하게 해석된 판정만 verdict를 만든다(supported→eligible, 지지되지 않은 insufficient/불확실→HOLD, contradicted→reject). 새 `resume --initial-only`는 `queued`이고 호출·dispatch 표지가 없을 때만 실행하며 아니면 `initial_dispatch_taken`이다. `live-binding`은 네트워크·키·예산 없이 비밀 없는 binding과 `bindingDigest`만 출력한다. 환경 이름·예산·receipt·실패 코드 표는 [`docs/development/ai-runtime-setup.md`](../../docs/development/ai-runtime-setup.md)(§10)가 권위 있는 문서다.

**등록 전용 `submit`(CLI 전용, HTTP 아님).** `relation_cli submit`은 `run`의 등록 절반이다. 완료(ready)되고 현재 권한·binding이 검증되는 S2 job이 있어야 하며 아니면 `upstream_not_ready`(또는 S2의 withheld 코드)로 거부되고 job은 만들어지지 않는다. 성공하면 upstream identity와 `upstream.digest`를 불변 binding으로 고정한 `queued` job을 만들고 `inspect`와 같은 결과를 돌려준다(`calls=[]`, `usage.replayCalls=0`). replay job의 **S3 submit은 fixture를 받지 않는다**(`fixture_not_allowed`). producer·verifier fixture는 job binding이나 입력 digest에 들어가지 않고 호출별 영수증(`calls.fixture_hash`)에만 기록되는 입력이어서 이후 `resume`/`run`이 단계마다 지정한다. 같은 `jobId`와 같은 입력의 재제출은 저장된 job을 `inspect`처럼 보고만 한다. queued·stopped·ready·cancelled 어느 상태에서도 resume·재고정·상태 초기화·호출을 하지 않으며 현재 권한은 반환 결과의 `delivery`에만 적용된다. 다른 입력(다른 upstream 포함)은 `job_input_conflict`다. 실행 때 현재 upstream·권한·binding을 다시 확인하므로 submit 뒤 S2의 권한·grant revision이 바뀌면 호출 없이 `stopped`다. queued job은 `cancel`로 호출 전에 취소할 수 있다. `run`은 같은 등록 경로(`Engine.freeze`) 뒤 `resume`하는 기존 편의 명령이다.

이 절의 시험·smoke 수치는 최종 승인 도입 이전의 기록이므로 현재 값으로 읽지 않는다. 통합 실행 뒤의 결과는 Main이 별도로 기록한다. smoke(`scripts/relation_smoke.py`)는 실제 ingestion·S2 extraction으로 만든 upstream을 relation subprocess(socket audit hook)로 읽어 방향 뒤집힘 hold, 경쟁 쌍 정규화, 같은 쌍의 다른 유형·범위 보존, 경로 단계 누락·알 수 없는 endpoint hold, 직접 대 2단계, mixed/positive/undetermined와 eligibility 분리, HOLD 최종 승인(호출 없음, 결정적 gate, 낡은 revision·이중 결정 거절), 위조 upstream·fixture, 철회 권한, upstream bytes/mode 불변을 검사한다. 명령·wire·gate·한계는 [AI 실행 계약의 S3 절](../../docs/design/ai-system.md#s3-관계영향-후보와-hold-최종-승인)을 따른다.

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

**승인 근거와 plan 계약 `zoop-graph-plan-2`.** 투영 대상은 여전히 `eligible`이고 review 대기가 아닌 relation뿐이며(HOLD·reject·pending·review 대기는 제외하고 개수만 셈), 이제 각 relation의 **유효 승인 근거**를 동결 plan에 함께 고정합니다. `source.review.projected[]`는 `{relationCandidateId, revision, approvalBasis{kind, revision, reviewer, decidedAt}}`이고 `audit.approvals`는 `{automatic, operatorFinal}` 개수입니다. 근거는 S3가 보고한 값을 믿지 않고 이력의 **마지막 이벤트**로 다시 증명합니다(자동: eligible로 만든 verdict, 운영자: `approved` effect의 review `allow`; `decidedAt`은 offset이 있는 ISO 시각). 증명되지 않으면(옛 `revalidation-requested`, 어긋난 revision·reviewer·시각) `relation_payload_invalid`로 freeze 전체가 실패하고 자동 승인으로 추정하지 않습니다. plan의 각 edge는 Neo4j 속성이 아닌 `approvals[{relationCandidateId, kind}]`를 따로 갖고(별칭 병합으로 자동·수동이 한 edge에 섞일 수 있음) `read`/`focus` 출력 edge에는 `sourceApprovals`로만 나옵니다. reviewer 신원은 plan(SQLite)에만 있고 어떤 명령 출력에도 없습니다. Neo4j 쪽 데이터(`vk`·`v`·`id`+`EDGE_KEYS`)와 graph digest는 바뀌지 않으며 version CREATE는 계속 추가 전용입니다. `read`는 사용 relation이 같은 eligible·revision·**approvalBasis**인지 다시 증명하고(아니면 `review_revision_changed` withheld), `project`는 기존대로 전체 review digest가 동결값과 같아야 쓰며(승인·reject 같은 새 검토는 revision을 바꾸므로 `review_revision_changed`), 이후의 새 검토는 기존 ready version을 바꾸지 않고 새 `versionId`로만 반영됩니다(`s3ReviewDigestMatches=false`로 알림). `zoop-graph-plan-1`로 동결된 행은 **이력**입니다. plan 스키마만 읽어(권한·registry·Neo4j를 건드리기 전에) 판별하며 `inspect`는 저장된 상태와 `next: null`·`delivery: withheld/graph_contract_changed`, `read`/`focus`는 내용 없는 withheld, `project`·`recover`·같은 ID의 `freeze`는 `graph_contract_changed` 오류이고 행·attempt는 바뀌지 않습니다(근거 없는 plan이 새 근거 아래에서 해석·적재·복구되지 않음). 새 승인 상태를 반영하려면 새 `versionId`로 freeze합니다.

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

**2026-10-21 실제 provider 합성 종단 실행(로컬 작업 트리·미커밋, 호출 승인을 받은 운영자 실행; 커밋·푸시·원격 CI·AWS·공개 활성화 없음).** 합성 문서 2건·운영자 seed 카탈로그·prior(snapshot) 사건을 입력으로 native ingestion → **live S2** → **live S3** → (선택) 최종 승인 → 비공개 Neo4j를 한 번에 돈다. 실제 호출은 `gpt-6-luna`(reasoning high) 9회와 `jev-1.14.0` 5회이며 공유 예산 USD 10·40회 상한 안에서 한 번씩만 보냈다(재시도·재전송 없음). 결과: S2 사건 후보 5·주제 후보 1, S3 관계 4(승인 **전** 자동 판정: eligible 1·HOLD 3·reject 0). 승인 경로는 **합성 시험 운영자가 스크립트로 낸 `allow` 1건**(진짜 Jev HOLD 하나에 대해, 새 모델 호출 0)이었고 Neo4j에는 자동 eligible만의 버전(노드 2·간선 1)과 수동 승인을 포함한 새 버전(노드 3·간선 2)이 각각 생겼다. 스크립트 승인 **후** S3 집계는 eligible 2·HOLD 2다(위 자동 판정과 모순이 아니라 전/후 시점의 차이). 소요 135.2초, 추정 비용 USD 0.013323880은 **보수적 long 단가의 상한 추정이며 청구액도 벤치마크도 아니다**. 점검 54개가 모두 통과했다. 이 값들은 아래를 전제로 읽어야 한다: (1) 문서·회사·카탈로그는 **합성**이며 실제 뉴스·매체·인물·기업이 아니다. (2) 수동 승인은 **스크립트가 낸 합성 시험 결정**이지 사람의 편집 판단이 아니다. (3) canonical 결정도 실제로 나온 후보에서만 만든 합성 시험 운영자의 것이다. (4) 모델이 낸 HOLD는 그대로 보고하며 억지로 통과시키거나 만들어 내지 않는다. (5) 실제 모델 품질·정확도의 증거가 아니다. (6) AWS 배포와 공개 활성화는 하지 않았다. PoC에서는 구조·순수 알고리즘만 참고해 다시 구현했고 런타임 import는 없다. 같은 날 기존 실제 Neo4j `graph_projection_smoke.py`도 통과했다(rollback·commit unknown·프로세스 종료·recover·변조 거절·읽기 전용·현재 수동 승인 projection 점검 전부). 직접 실행(요약은 `<output-root>/summary.json`과 stdout 한 개, 원문·키·모델 응답·검수 메모는 출력에 없고 원본 receipt는 `private/` 0700/0600; 출력 루트는 실경로의 **새** 디렉터리여야 하며 macOS에서는 `/private/tmp/...`를 쓴다):

```sh
cd ai/pipeline
# 설정·endpoint·콘솔 스크립트·Neo4j 대상(읽기 전용 preflight)만 점검하고 계획을 출력한다. 파일·예산 기록·모델 호출 없음.
.venv/bin/python scripts/live_graph_smoke.py --check --output-root /real/abs/new-dir --graph-uri bolt://127.0.0.1:7687 --usd-cap 10
# 유료. 환경 게이트·키·유한 예산이 모두 필요하며 별도 호출 승인을 받은 운영자만 실행한다. --exercise-manual-approval은 진짜 HOLD가 있을 때만 합성 최종 승인을 낸다.
.venv/bin/python scripts/live_graph_smoke.py --live  --output-root /real/abs/new-dir --graph-uri bolt://127.0.0.1:7687 --usd-cap 10 [--exercise-manual-approval]
```

**2026-10-15 최종 실행(로컬 작업 트리·미커밋, Main 실행. 커밋·푸시·원격 CI 없음).** `ai/pipeline` 시험 전체 265개가 통과했다. 실제 Neo4j 5.26 Community(격리된 `--rm` tmpfs 임시 컨테이너, 종료·정리 완료)에서 R1–R4 회귀 11개는 수정 전 11개 모두 RED로 재현됐고 수정 뒤 모두 통과했다. 새 빈 database의 정상 smoke는 다섯 관계 유형 전부, 노드 6·간선 6의 `v1`, 노드를 공유하지 않는 `v2`(`v1` 원본 바이트 불변), 깊이 1·2·3 focus, 반복 `init` 멱등, 권한 철회 withheld, unknown commit·SIGKILL 뒤 rollback·변조 fail-closed를 모두 통과했다. provider·모델 호출은 0이었고 원천 원장은 읽기 전용이었다. 활성 공개 상태는 없다(FS080 일부, FS081 철회 아님). **성능·지연·부하는 측정하지 않았고** 이 검증은 기능에 한정된다. 자세한 기록과 남은 범위는 위 AI 실행 계약의 시험 절을 따른다.

## 공개 영향 대상 조회 (handoff exposure, FS081 일부)

`zoop-ai-handoff-exposure`는 문서·출처·권한 변경이나 S3 관계의 오연결이 **지정한 handoff의 어느 공개 항목에 영향을 주는지** ID만 반환합니다. 권한 철회로 일반 `zoop-ai-handoff export`가 막힌 뒤에도 운영자가 고정 기록을 조사할 수 있습니다. 현재 읽기 권한을 승인하거나 원문·제목·인용문을 반환하는 명령은 아닙니다.

```sh
# document/source/grant 변경: 세 원장을 모두 명시합니다.
zoop-ai-handoff-exposure --state-dir HANDOFF \
  --ingestion-state-dir INGESTION --extraction-state-dir EXTRACTION < change.json

# S3 관계 오연결: handoff 원장만 사용하며 위 두 source 원장 인자는 거절합니다.
zoop-ai-handoff-exposure --state-dir HANDOFF < relation-change.json
```

입력은 65,536바이트 이하의 닫힌 JSON입니다. `handoffIds`는 중복 없는 1~20개이며 자동으로 전체 원장이나 최신 활성 버전을 선택하지 않습니다.

```json
{
  "schemaVersion": "zoop-handoff-exposure-1",
  "handoffIds": ["handoff-summary-1"],
  "changed": {"kind": "source", "sourceId": "synthetic-source-uncited"}
}
```

`changed`는 아래 네 형식 중 하나입니다. `null`을 허용하는 키도 생략하지 않습니다.

| kind | 추가 필드 | 의미 |
|---|---|---|
| `document` | `documentId`, `documentVersion`, `rawVersion` | 버전이 `null`이면 해당 ID에 고정된 모든 버전입니다. 최신 버전을 뜻하지 않습니다. |
| `source` | `sourceId` | 해당 출처로 고정된 입력입니다. |
| `grant` | `grantId`, `revision` | revision이 `null`이면 고정된 모든 revision입니다. 현재 registry를 읽어 대체하지 않습니다. |
| `s3-relation` | `jobId`, `relationCandidateId` | 지정한 작업의 관계 후보 하나입니다. 후보 ID만으로 조회할 수 없습니다. |

**결과와 영향 범위.** 각 handoff의 manifest·bundle·content digest, 영향받는 기사 버전·이슈·간선·근거 ID와 사유를 반환합니다. 원천 변경은 S2의 고정 입력을 따라가며, 영향을 받은 upstream을 사용한 S3 작업의 공개 관계 전체에 `upstream-input` 사유를 붙입니다. 모델은 인용하지 않은 문서의 사건·주제 정보도 읽었으므로 직접 인용만 추적하지 않습니다. 이슈 요약 역시 실제로 인용한 부분이 아니라 입력 전체를 보호합니다. 구조 근거와 impact-only 근거도 포함하며, 원문 근거 ID는 직접 영향받은 기사 버전의 것만 반환합니다.

관계 오연결은 지정한 `(jobId, relationCandidateId)`만 추적하고 `articles`·`evidenceIds`는 비워 둡니다. 관계를 취소한다고 원문 인용까지 철회하는 것은 아닙니다. 마지막 참여 관계가 사라지는 이슈와 연결된 FOLLOWS·구조 경로를 함께 찾고, 시작 기업을 확정할 수 없는 경로는 `anchor-undetermined`로 보수적으로 포함합니다.

**완전성과 실패.** `bound`는 선택된 입력에 연결됐는지, `exposed`는 공개 항목에 영향이 있는지를 구분합니다. 알 수 없는 원천 신원은 `changed_identity_unknown`이며, ingestion에만 기록되고 선택된 handoff에는 연결되지 않은 신원은 명시적인 빈 결과가 됩니다. 선택 중 하나라도 누락·미완료·손상·해석 불가이면 전체를 `handoff_selection_unmappable`로 거절하고 영향 목록 일부를 성공으로 내보내지 않습니다. 현재 bundle `-7`만 지원하며 `-1`~`-6`은 artifact를 열지 않고 `handoff_contract_changed`로 분류합니다. 원천 조회는 고정된 S2 입력 digest·결과 digest·ready 상태까지 대조합니다. 현재 영수증의 필드·digest·source pin·정수 타입도 검사합니다.

**적용 효과는 없습니다.** 출력은 선택한 handoff에 한정된 제안입니다. `effect`와 `scope.notCovered`가 그 한계를 명시하며, 앱 exclusion revision·`graphVersion`·활성 버전·전체 합집합을 만들지 않습니다. 빈 결과나 이전보다 작은 목록을 기존 제외 해제로 사용하면 안 됩니다. 앱 목록·S1·브리핑·채팅·캐시·Neo4j, 이전 schema와 선택하지 않은 handoff, 운영자 canonical/decisions/bindings 변경은 이 명령의 적용 대상이 아닙니다. 실제 제외 저장·현재 조회 반영·복구는 앱 담당 범위입니다.

공유 잠금은 결과 출력이 끝날 때까지 유지합니다. 원장·artifact를 변경하지 않고 모델·네트워크도 호출하지 않습니다. 결과는 시각 없는 정렬된 canonical JSON 한 줄이며 6 MiB를 넘으면 `exposure_report_limit`로 거절합니다. 자르거나 부분 보고하지 않습니다. 실행 검증은 `scripts/handoff_exposure_smoke.py`이며 `make pipeline-smoke`에도 포함됩니다. 앱 소비 시 주의사항은 [그래프 인수 문서](../../api/docs/GRAPH_READ_HANDOFF.md)를 따릅니다.

같은 질의를 인증된 내부 HTTP로 전달하려면 [service README의 Handoff 영향 ID 조회](../service/README.md#handoff-영향-id-조회-post-internalv1graph-handoffsexposure)를 따릅니다. 전용 scope·서버 설정·선택 전체의 허용 검사는 서비스가 담당하며, CLI의 원장 읽기와 앱의 실제 제외 적용 경계는 유지됩니다.
