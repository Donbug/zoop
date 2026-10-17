# 그래프 조회 계약 결정 제안

작성: 2026-10-15 · 갱신: 2026-10-16 · 제안자: API 조회 측 · 상태: **사용자 결정, 원격 main 인수 문서, 서진님 1차 회신(2026-10-16) 반영, 날짜만 있는 값의 asOf 비교·발행 시각 없는 기사 처리는 앱 결정(2026-10-16). 인계 계약 v1은 서진님 작성 대기**

## 0. 확정 사항 (2026-10-16, 서진님 1차 회신 반영)

아래 표는 이 문서의 이전 제안과 다르게 확정된 내용을 우선한다. 본문의 다른 절과 충돌하면 이 절을 따른다. 정본 계약은 여전히 `openapi.yaml`이다.

| 주제 | 확정 내용 | 이전 제안과의 차이 |
| --- | --- | --- |
| 공개 모델 | 노드는 `company`·`issue`이고, 간선은 현행 OpenAPI의 `INVOLVES`·`STRUCTURALLY_RELATED_TO`·`FOLLOWS`와 파생 `SHARES_ISSUE`다. PoC·prototype 방식을 따른다. | 직접 기업 관계 enum(`SUPPLIES_TO` 등)을 다음 개정에 제안하던 것을 철회한다. 회사–회사 관계는 **현재 공개 API 표현 범위 밖**으로 기록하고 계약 개정 항목으로만 남긴다. |
| AI 내부 그래프와의 관계 | AI 내부 그래프(`company/event/topic`, `SUPPLIES` 등)와 공개 이슈 그래프는 **의미가 다르다.** focus 응답의 이름을 바꾸거나 enum을 치환해 공개 모델을 만들지 않는다. | 내부 focus를 스냅샷 입력 후보로 보던 표현을 삭제한다. |
| 인계 단위 | AI가 **버전 있는 별도 인계 계약**으로 인계 묶음을 제공한다. 묶음에는 여러 원천 작업의 ID·input digest·원천/검수 revision, canonical 매핑, 정책 버전을 고정한 manifest와 전체 내용, 그 digest가 들어간다. 같은 ID인데 내용이 다르면 덮어쓰지 않고 충돌로 처리한다. PoC `inspect`는 참고 형식일 뿐 계약이 아니다. | 인계 경로를 "확인 필요"로 두던 것을 AI 측 제공으로 확정한다. focus 반복 호출이나 앱 임의 병합은 쓰지 않는다. |
| 인계 ID와 공개 버전 | AI 인계 묶음 ID와 앱 `graphVersion`은 다르다. 흐름은 앱이 수입 → 문서·근거 검증 → 스냅샷 등록 → **별도 활성화**다. 인계 준비 완료는 공개 승인이 아니다. | — |
| 앱 스냅샷 형식 | 앱이 자체 스냅샷 형식을 소유한다. 인계 계약과 분리하며 수입기 하나가 변환한다. | — |
| 이슈 ID | 문서별 mention, 작업 내 event 후보, 여러 문서에 걸친 canonical issue를 구분한다. 공개 `issue.id`는 canonical issue ID이며 **명시적 대응표**로만 연결한다. | "event ID = 공개 이슈 ID 여부 확인"을 "같지 않음, 대응표 필요"로 확정한다. |
| topic | 공개 노드에서 제외한다. topic을 경유한 경로를 양 끝 직접 연결로 바꾸지 않는다. | — |
| 간선 투영 | `INVOLVES`는 검증된 event→issue 대응과 직접 참여 의미가 확인된 `PARTICIPATES_IN`만 방향을 맞춰 투영한다. `STRUCTURALLY_RELATED_TO`는 이슈→기업 구조 근거 경로와 그 적용 여부가 검증된 경우만 쓴다. `SUPPLIES`·`INVESTS_IN`·`COMPETES_WITH` 자체는 근거가 아니다. `FOLLOWS`는 검증된 사건 간 선후 관계가 따로 필요하다. 구체 규칙은 AI 인계 계약에서 정한다. | 단순 enum 매핑 표를 쓰지 않는다. |
| `SHARES_ISSUE` | 권한 제외, asOf 필터, 현재 공개 제외를 **모두 적용한 뒤 남은 이슈**로만 조회 시 파생한다. 스냅샷에 저장하지 않는다. | — |
| 표시 간선 ID | prototype 규칙대로 `edge-` + SHA-256(`relationType`, source, target)을 쓴다. 공개 간선은 항상 한 끝이 이슈이므로 사업/제품 scope를 키에 넣지 않는다. 원천 `relationId`는 `relationIds`로만 노출한다. | §4의 scope 포함 키 규칙을 철회한다. 회사–회사 관계가 공개 범위에 들어오는 계약 개정 때 다시 다룬다. |
| geography | AI가 이슈의 발생·영향 지역 근거와 판정 정책 버전을 함께 제공한다. 기사 언어·언론사 국적·상장 시장만으로 판정하지 않는다. 근거가 없거나 충돌하면 미판정이고 **공개에서 제외**한다. | "제공 가능 여부 확인"을 AI 제공으로 확정한다. |
| evidence ID | AI는 문서 ID·불변 버전·raw 버전·span·원문 위치를 제공한다. 앱 등록 단계가 이를 앱 article/version에 명시적으로 연결하고, **결정적 규칙으로 앱 `ev-`(64 hex) ID를 발급·보존**한다. 재수입해도 중복 생성하지 않는다. AI 쪽 `ev-` ID는 접두어·길이 변환으로 재사용하지 않고 매핑용으로만 둔다. 인용문은 앱의 불변 본문 span에서 검증하고, 제목·URL·발행 시각은 같은 article version에서 읽는다. | PostgreSQL `evidence.id` 공유 제안을 이 규칙으로 구체화한다. |
| 근거 조회 경로 | 현재 `getEvidence`는 S1 요약 근거 중심이다. **그래프 근거가 `getEvidence`로 실제로 열리는 것까지 연결돼야 인계 완료**로 본다(앱 작업, WBS 6.6.9). | — |
| asOf | 두 단계를 모두 적용한다. ① `graph_activations`로 asOf 시점의 공개 버전을 고른다(OpenAPI 공통 규칙). ② 그 버전 안에서 시각 기준으로 자료를 거른다(`getCompanyGraphAsOf`·prototype `as_of_dataset`). 시각은 기사 발행 시각, 관계 검증·유효 시각, 공개 시각을 구분한다. **날짜만 있는 값을 자정이나 하루 끝 같은 임의 시각으로 만들지 않고** 날짜 정밀도로 비교한다. 비교 규칙은 아래 "날짜만 있는 값의 asOf 비교" 행을 따른다. 이 기준은 인계 시험에 포함한다. | 버전 선택(전역)과 버전 안 필터(기업 시점)를 섞어 쓰던 표현을 분리한다. prototype의 `end_of_day` 변환은 가져오지 않는다. |
| 날짜만 있는 값의 asOf 비교 | 날짜 `D`(`YYYY-MM-DD`)는 **asOf를 UTC−12의 달력 날짜로 내린 값보다 앞설 때만** asOf 이전으로 본다(`D < date(asOf, UTC−12)`). asOf와 같은 날짜는 제외한다. 날짜 쪽에 시각을 붙이지 않고 asOf 쪽을 날짜로 내려 비교한다. "기사 발행 ≤ asOf"·"이슈 공개 ≤ asOf"처럼 asOf 이전인지 판정하는 모든 날짜 값에 같은 규칙을 쓴다. 예: asOf `2026-10-02T09:00+09:00`(UTC−12로 `2026-10-01`) → `2026-09-30`은 포함, `2026-10-01`·`2026-10-02`는 제외. 관계 유효기간(구조 근거 `validFrom` ≤ asOf < `validUntil`)도 날짜 정밀도로 보수적으로 읽는다: `validFrom`은 그날이 모든 시간대에서 시작된 뒤(`validFrom ≤ date(asOf, UTC−12)`)부터, `validUntil`은 그날이 어느 시간대에서든 시작되면(`date(asOf, UTC+14) ≥ validUntil`) 만료로 본다. | **앱 결정(10-16, AI 인계 측은 asOf 정책을 앱 몫으로 둠).** AI 인계 묶음은 날짜만 있는 값에 시간대를 붙이지 않으므로(`collection_contracts`: "no time or timezone claimed") KST·UTC 같은 특정 시간대를 가정하지 않는다. UTC−12는 지구에서 가장 늦게 날짜가 바뀌는 시간대라, 이 기준이면 어느 시간대에서 발행된 날짜든 asOf 이후 문서를 보여 주지 않는다(FS042·채팅 asOf의 "그 시점 이후 공개된 문서를 사용하지 않는다"). 대가로 날짜만 있는 기사는 최대 약 36시간 늦게 반영된다. |
| 발행 시각 없는 기사 | AI 인계 묶음의 `publishedAt = null`·`publicationPrecision = "unknown"` 기사(오프셋 없는 시각도 AI가 이렇게 넘김)를 **앱도 그대로 수입한다.** 스냅샷에는 `publishedAt = null`로 남긴다. **asOf 없는 현재 그래프에는 보이고, asOf를 준 조회에서는 어느 시점이든 제외한다.** 언제 공개됐는지 모르므로 어느 과거 시점에도 이미 있었다고 할 수 없기 때문이다. 이슈는 기존 규칙대로 근거 기사가 모두 asOf 이전으로 확인될 때만 asOf 조회에 남으므로, 날짜 없는 기사에 기대는 이슈와 그 관계도 asOf 조회에서 빠진다. 앱은 발행 시각을 추정하거나 수집 시각으로 채우지 않는다. | **앱 결정(10-16).** 기사 하나 때문에 버전 전체를 공개하지 못하는 일을 막고, 정본 OpenAPI의 `publishedAt` null 허용(`EvidenceArticle`·`CompanyDocument` 등)과 맞춘다. "asOf 이후 공개된 문서를 쓰지 않는다"는 원칙은 그대로 지켜진다. 날짜 없는 기사가 많아 asOf 조회가 비게 되면 인계 계약 v1에서 다시 본다. |
| depth | `getGraph.depth`는 OpenAPI 설명("Hops from the focus")과 prototype처럼 기업 → 이슈 → 기업을 1 hop으로 센다. 생략하면 FOLLOWS를 포함한 연결 성분 전체다. `getCompanyGraphAsOf.depth`(1·2)는 OpenAPI 설명대로 **실제 연결선 수**를 센다. `SHARES_ISSUE`는 두 경우 모두 탐색 단계에서 제외한다. | 두 operation의 정본 설명이 서로 달라 operation별로 따로 적는다. 하나로 통일하는 것은 OpenAPI 개정 항목이다. |
| limit | prototype 값(기본 500, 최대 1000)을 따른다. 기준 기업을 먼저 넣고, 최신 이슈 순으로 채우고, 넘치면 `truncated`를 표시한다. | 수치 미정을 prototype 값으로 확정한다. 실제 규모를 측정한 뒤 다시 본다. |
| 공개 제외 | 불변 스냅샷 위에 **현재** 제외 상태를 overlay로 적용한다. asOf 필터와는 별개 단계다. 과거 버전을 지정해도 현재 철회된 내용은 노출하지 않는다. | — |
| revision | 앱 관리자 결정 revision, AI 원천·검수 revision, writer 적용 결과를 **하나의 숫자로 합치지 않는다.** 대상·결정·기대 원천 버전·적용 결과를 연결해 저장한다. AI는 고정된 원천/검수 revision의 처리 결과를 주고, 앱은 그 결과가 제외/공개 조건을 충족했는지 확인한다. | §3의 단일 `exclusionRevision`/`appliedExclusionRevision` 제안을 대체한다. |
| 철회 신호 현황 | 내부 read가 원천이 바뀐 버전 전체를 withheld하는 기능만 있다. 전체 공개 제외 목록과 철회 완료 신호는 아직 없다. | — |
| status | `ready + current`는 활성화 전 검증 입력으로만 쓰고 `reflected`/active로 자동 변환하지 않는다. private graph의 노드·간선 수로 공개 이슈 수를 채우지 않는다. 검증 시각·대상 version·digest·실제 저장소 관측 상태와 공개 스냅샷 수치를 나눈다. 생산자가 없는 값은 정상값으로 꾸미거나 계약에서 바로 삭제하지 않고, nullable/미확인 표현과 필요한 생산자를 먼저 정리한다. | 공개 상태 필드를 "삭제할지 확인"하던 것을 nullable/미확인 유지로 확정한다. |
| 복구·멱등성 | 내부 Neo4j의 응답 유실이나 unknown commit은 기존 version ID로 상태를 확인한 뒤 명시적으로 recover한다. 새 ID로 재적재하지 않는다. 앱 스냅샷 수입과 활성화도 같은 요청의 재실행과 응답 유실을 구분하는 멱등 키와 동시성 검사(기대 활성 버전 비교)를 둔다. | — |

**남은 일(AI 측):** 인계 계약 v1(manifest·digest·충돌 규칙), event→issue 대응표, 간선 투영 검증 규칙, geography 근거·정책 버전, 원천/검수 revision 처리 결과, 철회 완료 신호.

**남은 일(앱 측):** 앱 스냅샷 형식과 수입기, 그래프 근거의 `getEvidence` 연결, `graph_versions`/`graph_activations` 기반 활성화와 asOf 두 단계, 제외 overlay와 revision 분리 저장, fixture 시나리오(정상·geography 미판정·근거 누락·철회).

이 문서는 [그래프 조회 계약 대조안](graph-read-contract-review.md)의 미결정 항목에 대한 **결정 기록과 남은 제안**이다. §0과 본문의 "확정" 표시는 결정된 방향이고, "제안·확인 필요"로 남은 것만 미결정이다. `openapi.yaml`, ERD, Neo4j writer, 앱 코드는 아직 이 결정대로 수정하지 않았다. 정본 계약은 [`openapi.yaml`](openapi.yaml)이다. 근거는 `investmate-poc/src/investmate/{domain,graph}.py`, `prototype/bff/src/zoop_bff/{dataset,graph,graph_versions}.py`, `docs/erd/zoop-core-erd-v6.md`다.

**2026-10-16 확인 근거:** 원격 `main`의 [`api/docs/GRAPH_READ_HANDOFF.md`](https://github.com/Donbug/zoop/blob/cb345f7744da43bfc29150ec2e1b768219f03390/api/docs/GRAPH_READ_HANDOFF.md)와 `docs/api/internal-ai-openapi.{json,yaml}`의 `graph-versions` 계약을 추가로 대조했다. 이는 **현재 구현된 AI 내부 읽기 계약**이다. 아래의 앱 공개 조회·스냅샷·활성화 제안과 같은 계약으로 취급하지 않는다. 인수 문서의 작성 당시 로컬 검증·커밋 상태 설명은 현재 원격 `main`에 반영된 사실과 시점이 다르므로, 기능 범위와 wire 형식만 근거로 삼는다.

**사용자 결정(2026-10-15):** 본개발의 공개 그래프 조회는 prototype처럼 버전별 불변 스냅샷을 사용한다. 현재 활성 버전과 이전 버전 모두 선택된 `graphVersion`의 스냅샷에서 읽는다. Neo4j writer의 비공개 적재·검증은 별도 단계이며, 공개 API가 과거 버전별 Neo4j 투영을 직접 조회하는 것을 필수 조건으로 두지 않는다. prototype에서는 BFF가 원장을 읽어 스냅샷을 생성하므로, 본개발에서도 앱이 스냅샷 생성·보관·검증·조회·활성화를 소유하는 방향으로 제안한다. 이는 앱/AI 간 데이터 인계 방식과 운영 책임까지 확정했다는 뜻은 아니다.

**용어 결정(사용자, 2026-10-15):** 이 작업의 공개 조회에서 `사건`과 `이슈`는 같은 대상을 가리킨다. API 이름의 `event`와 그래프 이름의 `issue`를 별개 도메인 객체로 분리하지 않는다. PoC의 `mention_id`는 문서 안의 개별 언급 ID로 유지하며 공개 사건/이슈 ID와 동일하다고 가정하지 않는다. 기존 FS 문서의 구분 문장은 정본 반영 단계에서 이 결정과 대조·정정해야 한다.

## 1. 결정 상태와 남은 합의 한 장 요약

`사용자 결정`은 이 문서의 작업 방향이며 정본 API·팀 계약 반영 완료를 뜻하지 않는다. `제안·확인 필요`는 서진님 또는 관련 담당자와 아직 확정하지 않은 항목이다.

| 항목 | 현재 방향 | 상태·남은 확인 |
| --- | --- | --- |
| 공개 조회 단위·버전 자료 | 한 요청에서 `graphVersion` 하나를 고정하고, 현재·이전 버전 모두 해당 불변 스냅샷을 읽는다. 공개 API가 과거 버전별 Neo4j 투영을 직접 읽을 필요는 없다. | **사용자 결정.** 스냅샷 읽기 방식의 정본 API·본개발 반영은 아직이다. |
| 현재 AI 그래프 읽기 | 운영자가 허용한 `versionId`의 상태와 특정 회사 주변 `focus`를 내부 HTTP에서 조회한다. `ready`와 `delivery.state=current`는 이번 요청의 검증 통과이며 공개 승인이 아니다. | **원격 main 구현 사실.** 앱 Java 소비자·공개 응답 변환은 아직 없다. |
| 스냅샷 생성·인계 | AI가 버전 있는 인계 계약으로 manifest(원천 작업 ID·input digest·원천/검수 revision·canonical 매핑·정책 버전) + 전체 내용 + digest를 제공한다. 앱이 수입·검증해 자체 형식의 불변 스냅샷을 등록하고 별도로 활성화한다. | **확정(10-16, §0).** 인계 계약 v1 세부 형식은 서진님 작성 대기. |
| AI 작업 인계 | ERD v6의 앱 `analysis_jobs.id`와 `checkpoint.aiUnits[].unitKey/aiJobId`, 호출 영수증의 `ai_attempt_id`를 구분해 사용한다. 공개 버전에는 채택한 AI 원천 revision과 앱 검수 revision을 별도로 고정한다. | **부분 확정(10-16).** 원천/검수 revision을 앱 revision과 분리해 고정하는 것은 확정이다(§0 revision). 작업 연결 키(`unitKey`·AI 작업 ID)는 회신이 없어 **제안·확인 필요**로 남는다. |
| 공개 전환 | writer 적재·검증, 앱 스냅샷/근거/상세 조회, 현재 공개 조건이 모두 통과할 때만 포인터를 전환한다. 실패하면 이전 활성 버전을 유지한다. | **사용자 결정(전환 기준), 운영 합의 필요.** 최종 전환 권한·실행 주체와 writer 완료/실패 상태값을 확인한다. |
| 중단·권리 변경 | 응답 유실 시 기존 작업/시도 ID로 상태를 조회·복구한다. 공개 제외는 앱 조회 차단과 writer의 Neo4j 반영을 별도 완료로 추적한다. | **부분 확정(10-16).** 기존 version ID로 확인한 뒤 명시적 recover(새 ID로 재적재 금지), 앱 수입·활성화의 멱등성·동시성 검사, 세 종류 revision 분리, asOf와 무관한 현재 제외 overlay는 확정이다. 철회 완료 신호와 writer 적용 결과의 형식은 AI 인계 계약 v1 대기다. |
| ID | `companies.id` = 그래프 `company_id`. 공개 `issue.id`는 canonical issue ID다. 문서별 mention·작업 내 event 후보와 구분하고 명시적 대응표로만 연결한다. | **확정(10-16, §0).** 사건=이슈(공개 용어)는 사용자 결정. 대응표는 AI 인계 계약에 포함. |
| 근거 ID | AI가 문서 ID·불변 버전·raw 버전·span을 주면 앱이 article/version에 연결해 결정적 규칙으로 `ev-`(64 hex)를 발급·보존한다. 그래프 근거가 `getEvidence`로 열려야 인계 완료다. | **확정(10-16, §0).** 생성 규칙 세부는 앱이 정하고 인계 시험에 고정. |
| 표시 간선 ID | prototype 규칙 `edge-` + SHA-256(유형, source, target). 공개 간선은 한 끝이 이슈라 scope를 키에 넣지 않는다. 원천 관계 ID는 `relationIds`. | **확정(10-16, §0).** scope 키는 회사–회사 관계가 공개 범위에 들어올 때 재검토. |
| 지리 속성 | AI가 발생·영향 지역 근거와 판정 정책 버전을 제공한다. 근거가 없거나 충돌하면 미판정으로 두고 공개에서 제외한다. | **확정(10-16, §0).** |
| `asOf` | ① `graph_activations`로 그 시점의 공개 버전을 고르고 ② 버전 안에서 기사 발행·관계 검증/유효·공개 시각을 구분해 거른다. 날짜만 있는 값은 날짜 정밀도로 비교한다(`D < date(asOf, UTC−12)`, 같은 날 제외). 발행 시각 없는 기사는 현재 그래프에만 보이고 asOf 조회에서는 제외한다. | **확정(10-16, §0).** 날짜 비교·발행 시각 없음은 앱 결정. 재활성화 시점의 처리는 인계 시험에서 확인. |
| 깊이 `depth` | `getGraph`는 기업→이슈→기업을 1 hop(prototype·OpenAPI 설명). `getCompanyGraphAsOf`(1·2)는 실제 연결선 수. 두 경우 모두 `SHARES_ISSUE`는 탐색에서 제외. | **operation별 정본 설명을 따름.** 통일은 OpenAPI 개정 항목. |

### 원격 main의 내부 그래프 읽기 계약과 앱의 처리안

| 내부 AI 호출·필드 | 확인된 의미 | 앱에서 사용할 때의 경계 |
| --- | --- | --- |
| `GET /internal/v1/graph-versions/{versionId}` | 한 버전의 내용 없는 상태. `state=frozen/reserved/unknown/ready/failed`, `publication=not-published`, `delivery=current/withheld`를 반환한다. `current`일 때만 `verification{graphDigest,payloadDigest,nodes,edges}`가 있다. | `state=ready`와 `delivery=current` 및 앱이 저장한 버전·digest의 일치를 **적재 조회 검증 입력**으로 쓴다. `current`를 공개 활성 또는 공개 `reflected`로 자동 변환하지 않는다. `nodes/edges`는 이슈 수가 아니다. |
| `GET /internal/v1/graph-versions/{versionId}/focus?companyId=&depth=` | 허용된 회사의 1~3홉 주변 그래프를 반환한다. `found=false`는 검증된 버전에 그 회사가 없다는 뜻이다. | 앱 공개 정책과 버전 선택 이후에만 소비한다. `withheld`는 빈 결과가 아니며 공개 응답이나 캐시에 저장하지 않는다. `found=false`와 장애를 구분한다. |
| `Authorization: Bearer`·`graph.read`·버전 allowlist | 내부 principal별 읽기 권한과 버전 pin을 검사한다. 버전은 운영자가 생성·허용한다. | 앱은 전용 읽기 자격을 사용한다. 현재 내부 API에 버전 생성·나열·활성화 기능은 없다. 자격·버전 전달 운영 절차가 필요하다. |
| `focus.graph.nodes/edges/evidence` | 노드 `company/event/topic`; 간선은 `relationId`, 유형·방향·범위·근거 ID 등; 근거는 문서 ID·버전·span 좌표만 제공한다. | 공개 `company/issue` 화면 노드 및 상세와 **직접 1:1 매핑하지 않는다**. **확정(10-16):** 공개 스냅샷의 입력으로 쓰지 않는다. `event`는 공개 issue와 같은 ID가 아니며 대응표로만 연결한다. `topic`은 공개 노드에서 빼고 경유 경로를 직접 연결로 바꾸지 않는다. 인용문·제목·URL·발행 시각은 앱 article version에서, 기업 표시값은 버전에 고정한 카탈로그 값에서 채운다. |
| `delivery.state=withheld` / HTTP 503 | `withheld`는 원천 권리·검수·canonical·graph digest 등의 현재 게이트 실패를 200과 내용 없는 응답으로 알린다. 503은 서비스/DB/동시성 장애다. | 둘 다 정상 0건으로 변환하지 않는다. 내부 사유·재시도 가능성을 구분해 앱의 공개 제외 또는 가용성 정책을 적용한다. |

**현재 구현 범위:** AI pipeline은 완료된 S3 관계 작업 **한 건**을 SQLite에 불변 `plan`으로 `freeze`하고 버전별 Neo4j 투영을 `project`·검증한다. 내부 서비스는 지정된 버전의 상태와 회사 주변만 읽는다. 이 `plan`은 앱 공개 응답의 불변 스냅샷과 다르다. 전체 공개 그래프 export, 다수 S3 작업의 공개 버전 합성, 공개 스냅샷 artifact 생성·등록, 앱 활성 포인터·`asOf` 활성화 이력, Java 클라이언트, 공개 그래프 API는 제공되지 않는다. 따라서 **내부 focus 응답만 반복 호출해 전체 공개 스냅샷을 만들 수 있다고 가정하지 않는다.** **확정(10-16):** 고정 원본은 AI 측이 버전 있는 인계 계약(manifest + 전체 내용 + digest)으로 제공한다. 세부 형식은 인계 계약 v1에서 정한다.

## 2. 공개 버전 선택·조회·오류

**버전 선택 순서 (10-16 확정, OpenAPI `publicationVersions` 기준)**

1. `round`가 있으면 해당 브리핑 발행 시 고정한 버전을 선택한다. 함께 온 `graphVersion`/`asOf`가 그 버전과 충돌하면 `422 INVALID_REQUEST`로 처리한다.
2. `asOf`가 있으면 `graph_activations`에서 `pointer_changed=true`, `activated_at <= asOf`인 마지막 행을 `(activated_at DESC, id DESC)`로 선택한다. 같은 시각의 순서를 ID로 고정한다. 선택된 버전과 명시된 `graphVersion`이 다르면 `422 INVALID_REQUEST`다.
3. `graphVersion`만 있으면 그 버전이 실제 공개된 적 있고 스냅샷이 검증 가능하며 현재 권리·공개 제외 조건을 만족하는 범위만 읽는다. 등록만 했거나 검증·활성화 이력이 없는 버전은 공개 조회 대상이 아니다.
4. 모두 생략하면 요청 시작 시 활성 포인터를 한 번 읽고 고정한다. 그 후 포인터가 바뀌어도 같은 요청 안에서 다른 버전을 섞지 않는다.

`metadata.graphVersion`은 항상 실제 선택된 ID다. `metadata.asOf`는 명시한 기준 시각, 없으면 요청 시작 시각이다. `round` 조회에서는 회차 발행 시각을 기준으로 한다. **사건 발생 시각(`eventTime`)과 공개 가능 시각을 혼동하지 않는다.** 기준 시각 이후에 처음 공개된 문서/근거가 선택된 버전 스냅샷 안에 있다면 해당 시점 응답에서 제외한다. 재활성화처럼 같은 스냅샷을 다른 시각에 다시 공개할 때의 시점 필터는 스냅샷 조회 단계에서 적용하는 방향으로 제안하며, 공개 가능 시각 필드와 검증 방법은 확인이 필요하다.

**확정(10-16):** 위 2번(버전 선택)과 버전 안 자료 필터는 **별개 단계로 둘 다 적용**한다. 버전 안 필터는 prototype `as_of_dataset` 방식이며 기사 발행 시각, 관계 검증·유효 시각, 공개 시각을 구분한다. 날짜만 있는 값은 자정이나 하루 끝 같은 시각으로 바꾸지 않고 날짜 정밀도로 비교한다. 날짜 `D`는 asOf를 UTC−12의 달력 날짜로 내린 값보다 앞설 때만 포함하고, 같은 날짜는 제외한다(§0). 발행 시각 없는 기사는 이 필터에서 항상 asOf 이후로 취급해 제외한다(asOf 없는 조회에는 남는다). prototype의 `end_of_day` 변환은 가져오지 않는다. 현재 공개 제외 overlay는 asOf와 무관하게 항상 적용한다.

요청 버전/해당 시점의 공개 버전이 없으면 `VERSION_UNAVAILABLE`이다. 버전은 존재하지만 스냅샷 파일이 없거나 읽기·해시 검증에 실패하면 `503 SOURCE_UNAVAILABLE`이다. 검증된 스냅샷에서 승인 관계가 0건인 경우에만 `200`과 빈 관계를 반환한다. 근거가 존재하되 현재 접근 권리가 사라진 경우는 해당 근거·의존 관계를 공개 제외하며, 필요한 응답을 안전하게 만들 수 없으면 명세의 근거 오류를 반환한다. 다른 최신 버전이나 현재 Neo4j 상태로 조용히 대체하지 않는다.

### 공개 활성 포인터 전환 조건 — 확정(전환 기준), 운영 절차는 합의 필요

전환 기준(아래 표를 모두 통과해야 전환, 실패하면 이전 버전 유지, 저장·검증과 활성화 분리)은 사용자 결정이며 10-16 회신과도 일치한다. 최종 전환 권한과 실행 주체만 미정이다. 아래 "적재 완료" 행의 내부 status는 활성화 전 검증 입력으로만 쓴다. 인계 묶음이 도입되면 인계 manifest·digest 검증이 함께 들어간다.

`v3`의 **저장 완료**와 **사용자 공개 가능**을 구분한다. 현재 활성 버전이 `v2`라면, 아래 조건이 모두 통과할 때만 앱이 활성 포인터를 `v2 → v3`로 원자적으로 전환하고 활성화 시각·이전/새 버전·전환 결과를 이력으로 남긴다. 하나라도 미완료·실패·확인 불가이면 `v2`를 유지하고 `v3`의 미반영 단계와 사유를 기록한다. 실패한 버전을 최신 버전으로 대체해 응답하거나 저장 성공만으로 공개 완료 처리하지 않는다.

prototype의 관리자 게시 동작은 스냅샷 저장과 즉시 활성화를 한 번에 수행한다. 본개발에서는 **저장·검증과 활성화를 분리**해 아래 통과 조건을 먼저 확인한다.

| 전환 전 확인 | 통과 기준 |
| --- | --- |
| 적재 완료 | 내부 status에서 `versionId=v3`, `state=ready`, `delivery.state=current`, pin된 `graphDigest`·`payloadDigest` 및 검증 개수 일치를 확인한다. 이는 **그 순간의 그래프 검증**일 뿐 공개 승인이나 앱 스냅샷 완료는 아니다. 여러 S3 작업을 한 공개 버전에 묶는 경우 각 입력의 완료·누락·실패 여부는 별도 인계 계약으로 확인한다. |
| 스냅샷 생성·검증 | 앱이 같은 `v3` 입력에서 공개용 불변 스냅샷을 만들고 artifact ID·SHA-256·크기·버전 메타데이터를 기록한다. 기업·사건/이슈·관계·근거 ID/문서 버전의 참조와 개수를 검사하고 재읽기·해시 검증이 통과한다. |
| 공개 적격 | FS079 자동 검증과 관리자 검수, 현재 권리·공개 제외 조건을 모두 만족한다. `allow` 결정만으로 검증을 우회하지 않는다. |
| 입력·원천 확인 | S2의 서버 승인 `approvedRequestDigest`와 S3의 별도 접근 권한이 확인된 결과만 수입한다. 선택한 관계의 AI `sourceVersion`/`sourceRevision`과 앱 검수 revision이 스냅샷 생성 시점에도 유효해야 한다. |
| 조회 준비 | 메인 그래프, 기업 상세 그래프, 연결선 상세, 사건/이슈 상세, 근거 상세를 모두 `v3` 기준으로 읽을 수 있고 응답 간 참조가 실제로 연결된다. 특히 그래프의 `evidenceIds`를 근거 상세 조회가 찾을 수 있어야 한다. |
| 버전 일치 | 위 조회의 버전·근거·공개 제외 상태가 서로 일치하며, 캐시도 `v3`와 현재 제외 revision으로 준비된다. 조회 중 다른 버전이 섞이지 않는다. |

**서진님(writer) → 세빈님(API) 인계 요청:** 현재 내부 status의 `versionId`, `state`, `delivery`, `verification{graphDigest,payloadDigest,nodes,edges}`와 focus의 관계·근거 좌표는 이미 받을 수 있다. 추가로 실제 완료 시각·실패 항목별 단계·사유, 공개 버전을 구성하는 전체 입력 목록과 원천/검수 revision, 근거 내용·기업/사건 상세를 결합할 **고정 원본 인계 경로**가 필요하다. 현재 focus는 회사 주변 조회일 뿐 전체 버전 export가 아니다. 앱은 이에 대응하는 앱 작업 ID·앱 검수 revision·규칙 revision을 별도로 고정한다. 서진님에게 앱의 공개 스냅샷 artifact ID·SHA-256을 생성·전달하라고 요구하지 않는다. 저장·검증·인계 상태를 구분하고 동일 작업/버전 재전송이 중복 반영되지 않도록 전달 형식과 상태값을 함께 확정한다.

**10-16 회신:** 이 요청은 수락됐다. AI 측이 여러 원천 작업의 ID·input digest·원천/검수 revision·canonical 매핑·정책 버전을 고정한 manifest와 전체 내용·digest를 제공하고, 같은 ID인데 내용이 다르면 충돌로 처리한다. 인계 묶음 ID는 앱 `graphVersion`과 다르다. 구체 필드는 인계 계약 v1에서 정한다.

**세빈님(API) 생성·확인·전환 (10-16 확정, 전환 권한·운영 절차만 미정):** 인계한 동일 버전의 결과와 앱의 공개 조건을 대조해 스냅샷을 생성·보관하고 artifact ID·SHA-256을 기록한다. 결과를 앱에 수입할 때와 스냅샷 생성·활성화 직전에 현재 권리·제외 상태를 다시 확인한다. 스냅샷 및 공개 API의 각 조회 경로가 모두 통과한 경우에만 활성 포인터를 전환한다. 포인터 전환 권한과 운영 절차는 팀과 최종 확정한다. `asOf`는 이 활성화 이력에서 요청 시각 이전의 마지막 전환을 선택하므로, 적재 시각이나 스냅샷 생성 시각을 공개 시각으로 사용하지 않는다. 선택한 버전 안의 자료 필터는 §2의 확정 문단을 따른다.

## 3. Neo4j 결과 인계와 스냅샷 읽기 경계

> **10-16:** 경계 자체(AI 인계 묶음 → 앱 수입·스냅샷 → 별도 활성화, 공개 조회는 스냅샷만)는 확정이다(§0). 아래 표의 "writer 인계" 행은 인계 계약 v1으로 대체된다. 아래 "인계 키·상태·제외 신호 초안" 표는 행마다 확정 여부를 덧붙였다.

서진님 writer는 비공개 Neo4j 적재·검증 결과를 인계한다. 앱은 그 결과와 앱이 관리하는 공개 적격 정보로 **버전별 불변 스냅샷**을 만들고 공개 API는 선택된 스냅샷만 읽는다. 아래 표는 공개 URI가 아니라 앱의 스냅샷 생성·조회에 필요한 논리 계약이다. 실제 내부 전달 방식은 확인이 필요하다.

| 단계·입력 | 확보하거나 반환해야 할 값 | 섞지 않을 값 |
| --- | --- | --- |
| writer 인계: `versionId` | 같은 버전의 기업·사건/이슈·관계, 안정 ID·방향·유형·scope·role·검증 상태, 근거 ID·문서 버전·공개 가능 시각, 개수·실패 사유·검증 결과 | 다른 버전의 관계, 미검증 후보를 공개 확정값으로 표시한 결과 |
| 앱 스냅샷 생성: 인계 결과 + 앱 공개 상태 | 같은 버전의 공개 그래프와 연결선/사건/근거 상세 참조, 기업 표시값, 검수·규칙 revision, artifact ID·해시·크기 | 회원별 `holding`/`watch`, 생성 시점의 임의 최신값, 근거 없는 `ALLOW` |
| 공개 조회: 선택한 스냅샷 + 현재 제외 상태 | `versionId`에 고정한 그래프·표시 간선 상세·회사별 중복 제거 이슈 수·사건/근거 상세 참조, 현재 공개 제외 적용 결과 | 현재 Neo4j 전체 DB의 이슈 수, 다른 버전의 상세·근거 |

### AI 작업 연동에서 스냅샷 입력까지의 선행 조건

- **ID와 revision을 분리한다.** 공개 앱 `jobId`는 내부 S2/S3 `jobId`와 별도로 저장·연결하고, 내부 `attemptId`가 있는 단계는 그 시도도 별도로 추적한다. AI `sourceVersion`(S3 입력 digest)과 `sourceRevision`(관계별 이력 revision), 앱 검수 대상/전역 revision, 공개 `graphVersion`을 같은 번호로 취급하지 않는다. 스냅샷 입력에는 실제로 채택한 AI 결과의 작업 ID·원천 revision과 앱 결정 revision을 추적할 수 있어야 한다. 각 필드의 최종 저장 위치와 인계 형식은 별도로 합의한다.
- **승인된 입력만 소비한다.** S2는 서버가 승인한 `approvedRequestDigest`로만 실행하고 호출자가 기업 목록·사건 snapshot·파일 경로를 지정하지 않는다. S2 완료만으로 S3 접근 권한이 생기지 않는다. 이는 AI 접수 계약의 책임이며, 그래프 쪽은 승인된 S2 입력과 별도로 허가된 S3 결과인지 확인한 후 스냅샷 입력으로 채택한다.
- **불명확한 응답은 기존 ID로 복구한다.** 접수·검수·writer 적재·스냅샷 생성의 응답이 유실되거나 중단되면 새로운 앱/AI 작업이나 버전을 먼저 만들지 않는다. 저장한 작업 ID·시도 ID·멱등 키로 상태를 조회하고 해당 단계의 복구 절차를 따른다. 이미 보존한 분석·검증 결과의 저장/반영 복구는 불필요한 모델 재호출 없이 진행한다.
- **현재 권리를 반복 확인한다.** AI 결과 반환 시점의 권리 검사는 그 순간만 유효하다. 앱 결과 수입·스냅샷 생성·활성화·공개 GET에서 현재 문서/인용 권리와 공개 제외 상태를 다시 확인한다. 권리 확인 불가나 철회 대상이 있으면 공개 가능으로 승격하지 않는다.
- **영향 조회는 실행 완료 신호가 아니다.** 문서·권리 변경의 읽기 전용 영향 조회가 반환한 대상 목록은 재검증 범위의 입력이다. 그 조회만으로 관계 철회, Neo4j 비활성화, 스냅샷 공개 제외 또는 캐시 무효화가 끝났다고 기록하지 않는다. 단계별 실제 완료·실패 결과와 제외 revision을 확인한다.

### 서진님에게 제시할 인계 키·상태·제외 완료 신호 초안

아래는 **앱이 이렇게 받기를 제안하는 값**이며 writer의 현재 응답 형식이나 구현 완료 상태가 아니다. ERD v6의 `analysis_jobs`, `checkpoint.aiUnits[]`, `ai_executions`, `graph_versions.graph_db_state`가 이미 정한 식별자·상태와 맞춰 최종 이름을 확정한다.

| 구분 | 앱 측 제안 | 완료·복구 해석 |
| --- | --- | --- |
| 작업 연결 키 | 앱 `analysisJobId`(`analysis_jobs.id`) + 작업 안에서 유일한 `unitKey` ↔ S2/S3 각각의 `aiJobId`; 해당 호출의 `aiAttemptId`는 영수증·시도 추적용으로 별도 기록. 공개 묶음은 `versionId`로 식별하고, 같은 버전의 writer 명령에는 앱이 저장한 `commandKey`를 재사용한다. | 같은 `analysisJobId/unitKey/commandKey`의 재전송은 같은 작업을 찾는다. 새 `aiJobId`나 `versionId`를 응답 유실만을 이유로 발급하지 않는다. `aiAttemptId`를 공개 버전 ID로 사용하지 않는다. **(제안·확인 필요: 10-16 회신 없음.)** |
| 원천·검수 고정 | 선택 관계마다 `relationCandidateId`, AI `sourceVersion`(입력 digest), AI `sourceRevision`(관계 이력), 앱 검수 대상 revision 및 발행 시 전역 `reviewRevision`·`ruleRevision`을 별도 기록한다. | 원천 revision이 바뀌면 이전 검증 결과·앱 allow를 새 원천에 그대로 적용하지 않는다. writer 인계와 스냅샷 생성 시 기대값을 다시 대조한다. **(확정 10-16: 원천/검수 revision을 앱 revision과 분리해 manifest에 고정한다. 필드 이름은 인계 계약 v1.)** |
| writer 상태 | **현재 wire:** `state=frozen/reserved/unknown/ready/failed`, `delivery=current/withheld`, `publication=not-published`. `ready + current`일 때 검증 digest·노드/간선 개수가 나온다. **앱 제안:** 접수·진행·반영·실패의 공개 운영 상태는 별도로 정의한다. 기존 제안의 `accepted/pending/reflected`를 AI wire 값으로 요구하지 않는다. | `ready + current`는 요청 순간의 내부 그래프 검증이며 앱 스냅샷/공개 준비 완료가 아니다. `withheld`·`unknown`·`failed`는 빈 그래프가 아니다. 현재 내부 읽기 API에는 `recover`·명령 접수 라우트가 없으므로 응답 유실 시 기존 버전/작업으로 확인하는 실제 경로는 writer 운영 계약으로 정한다. **(확정 10-16: `ready + current`를 `reflected`/active로 자동 변환하지 않는다. 노드·간선 수를 이슈 수로 쓰지 않는다. 응답 유실·unknown commit은 기존 version ID로 확인한 뒤 명시적으로 recover하고 새 ID로 재적재하지 않는다. 생산자가 없는 공개 상태 값은 nullable/미확인으로 둔다.)** |
| 앱 스냅샷·공개 상태 | writer 상태와 별도로 스냅샷 **미생성 / 생성 중 / 검증 완료 / 실패**, 공개 포인터 **기존 버전 유지 / 전환 완료**를 기록한다. 이 표기는 앱 내부 단계이며 새 공개 API enum으로 확정한 것이 아니다. | writer `reflected`만으로 앱 스냅샷 검증 또는 공개 포인터 전환을 완료 처리하지 않는다. 생성·조회·권리 검사가 통과한 뒤에만 전환한다. **(확정 10-16: 앱 수입과 활성화는 멱등 키와 기대 활성 버전 비교로 재실행·응답 유실을 구분한다.)** |
| 공개 제외 신호 | **(10-16 대체: §0 "revision" 행. 단일 `exclusionRevision`으로 합치지 않고 앱 결정 revision·AI 원천/검수 revision·writer 적용 결과를 대상·기대 원천 버전과 함께 따로 연결한다. 아래는 이전 초안이다.)** 변경 대상 ID·사유·단조 증가하는 `exclusionRevision`을 함께 전달하고, **앱 조회 차단 완료**와 **writer Neo4j 반영 완료**를 별도 상태/시각으로 받거나 기록한다. writer 응답에는 처리한 대상과 `appliedExclusionRevision` 및 실제 그래프 확인 결과를 요구한다. | 앱 완료는 직접 조회·과거 스냅샷·캐시에서 대상이 숨겨진 뒤, writer 완료는 동일 revision 이상의 제외가 Neo4j에서 확인된 뒤다. 전체 복구 완료는 둘 다 확인한 때만 표시한다. 어느 한쪽이 실패·불명이면 전체 완료로 표시하지 않는다. |

공개 제외가 발생하면 **앱 조회 차단을 먼저 적용**해 기존·과거 버전에서 재노출되지 않게 한다. writer 반영이 늦더라도 앱 조회는 차단 상태를 유지하고 writer 작업은 미완료로 남긴다. 반대로 writer가 관계를 비활성화했더라도 앱의 과거 스냅샷 조회·캐시에 남아 있으면 앱 완료가 아니다. 제외 revision의 발급자·저장 위치, writer 확인 API/결과 형식, 앱 캐시 무효화 범위는 서진님과 확정한다.

writer는 현재 S3 관계 작업 한 건의 불변 `plan`과 버전별 Neo4j 투영을 만들고 검증한다. 앱이 스냅샷에 사용할 전체 결과가 그 버전과 같은 원천·digest에 묶이는 인계 방식은 아직 없다. **(10-16) AI 측이 여러 원천 작업을 고정한 manifest + 전체 내용 + digest의 버전 있는 인계 계약을 만들기로 했다(§0). 내부 Neo4j의 응답 유실·unknown commit은 기존 version ID로 상태를 확인한 뒤 명시적으로 recover하며, 새 ID로 재적재하지 않는다.** 공개 이후 Neo4j의 과거 투영을 유지할지 여부는 writer의 복구/운영 설계 문제이며, **공개 API의 이전 버전 조회 선행조건은 아니다.** 앱은 저장한 스냅샷을 재읽고 해시·참조를 확인한 뒤 공개한다. 파일 누락·변조 시 Neo4j 최신값으로 자동 대체하지 않는다.

현재 권리 철회나 오연결은 불변 이력·스냅샷을 지우지 않고 **공개 제외 overlay**로 차단한다. API는 선택한 스냅샷과 현재 유효한 제외 목록을 함께 확인하고, 캐시는 `(versionId, 제외 revision, 조회 조건)`에 결합한다. 이 overlay의 저장소·원자적 갱신·writer 통지 책임은 FS081 담당자와 앱 공개 포인터 소유자가 함께 확정해야 한다. 조회 장애 시 과거 캐시에서 제외 항목이 재노출되지 않아야 한다.

## 4. 응답 필드별 구체적 매핑

| 공개 응답 | 권장 생성 방식 |
| --- | --- |
| `GraphNode.id/kind` | 공개 스냅샷에 고정된 `company_id`/`issue_id`. 공개 `issue.id`는 canonical issue ID이며, 내부 `event` ID와 같다고 보지 않고 인계 대응표로만 연결한다. `topic`은 공개 노드에서 제외하되 topic 경유 경로를 양 끝 직접 연결로 바꾸지 않는다(10-16 확정). 기사와 문서는 화면 노드가 아니다. |
| 기업 `label/brandColor/logoUrl` | 버전 snapshot에 고정된 기업 표시값. 현재 `companies`는 ID 존재·현재 접근 조건 확인에 사용한다. 회사가 현재 카탈로그에서 삭제되어도 과거 표시값을 현재 이름으로 덮어쓰지 않는다. |
| `isFocus` | 요청의 기준 기업 집합에서 결정. 관계가 없어도 그 기업 노드를 남긴다. |
| `holding/watch` | 인증 회원의 PostgreSQL 보유/관심 데이터. 개인화 모드에서만 참조하고 전체 모드에서는 둘 다 `false`다. 공개 스냅샷에 회원별 정보를 넣지 않는다. |
| 이슈 `label/eventTime/timePrecision/action/target/geography` | 해당 버전의 검증된 이슈 스냅샷 값. 날짜 정밀도를 임의로 높이지 않는다. 검증된 `geography`가 없으면 공개 버전 구성 단계에서 제외한다. |
| 이슈 `evidenceCount` | 같은 `versionId`의 `EventDetail.evidenceIds`를 중복 제거한 개수. 현재 권리 제외 후 남은 공개 가능한 근거 기준으로 계산한다. |
| `GraphEdge.relationType/source/target/role/assertionStatus` | 승인된 원천 관계를 표시 키로 묶는다. 공개 유형은 현행 `INVOLVES`·`STRUCTURALLY_RELATED_TO`·`FOLLOWS`·`SHARES_ISSUE`다. 내부 유형을 enum 치환으로 옮기지 않는다. `INVOLVES`·`STRUCTURALLY_RELATED_TO`·`FOLLOWS`는 각각 검증된 참여·구조 근거 경로·선후 관계가 있을 때만 투영하며, 규칙은 AI 인계 계약에서 정한다(10-16 확정). 회사–회사 관계는 공개 범위 밖이다. 내부 `relationId`를 공개 `edge.id`로 그대로 복사하지 않는다. `REPORTS`·`PROVIDES_BACKGROUND`는 근거 연결로만 사용한다. |
| `GraphEdge.summary` | 승인된 role·relationType에서 버전과 함께 고정한 한국어 짧은 문구. 조회 시 생성형 모델을 호출하지 않는다. |
| `GraphEdge.id` / `EdgeDetail.relationIds` | `edge.id`는 표시 그룹의 안정적 키, `relationIds`는 해당 버전에서 그 그룹을 구성한 원천 관계 ID 배열이다. 동일하게 취급하지 않는다. |
| `SHARES_ISSUE` | 두 회사가 같은 공개 이슈에 연결된 경우에만 파생. 권한 제외·asOf 필터·현재 공개 제외를 적용한 **뒤** 남은 이슈만 기준으로 조회 시 계산한다(10-16 확정). 회사 ID 두 개를 정렬해 대칭 키를 만들고, `via`는 공유 이슈 ID 배열이다. 그래프 간선 `evidenceIds=[]`; 상세의 각 `ViaIssue.evidenceIds`에서 양쪽 승인 연결의 근거를 확인한다. 공급/고객 관계로 이름 붙이지 않는다. |
| `EdgeDetail.verification` | 직접 간선은 해당 버전 검증 결과가 `ALLOW`인 경우에만 `ALLOW`. 파생 간선은 `not_applicable`. 보류·거절 결과를 성공 상세에 노출하지 않는다. |
| `GraphMetadata` | API가 선택한 스냅샷 버전·요청 조건·잘림·빈 결과·request ID를 조합한다. writer가 개인화나 HTTP 오류를 결정하지 않는다. |

**표시 간선 키 규칙 (10-16 확정):** prototype의 `edge-` + SHA-256(`relationType`, source, target)을 쓴다. 현재 공개 간선은 항상 한 끝이 이슈이므로 사업/제품 scope가 키에 필요 없다. 아래 scope 포함 규칙은 회사–회사 관계가 공개 범위에 들어오는 계약 개정 때 다시 검토하기 위한 **보류 초안**이다.

**(보류) 표시 간선 키 규칙 초안:** `keyVersion=1`인 canonical JSON의 `(relationType, 정규화한 source/target, scopeId)`를 SHA-256으로 해시해 `edge-`와 128비트 hex를 사용한다. 방향 관계는 양끝 순서를 유지하고, 대칭 관계만 ID순 정렬한다. `scopeId`는 사업/제품 범위가 있으면 반드시 포함하고, 없는 경우 명시적 `null`을 쓴다. 원천 `relationId`와 `versionId`는 해시 입력에서 제외한다. 충돌·중복 키는 버전 생성 시 실패시키며, 키 규칙이 바뀌면 `keyVersion`을 올리고 기존 링크의 해석/전환 정책을 정한다. 기존 prototype의 `(type, source, target)` 해시는 범위를 표현하지 못하므로 이식하지 않는다.

## 5. 직접 기업–기업 관계와 `depth` 변경안

> **10-16 확정으로 이 절의 성격이 바뀌었다.** 회사–회사 관계는 현재 공개 enum에 넣지 않고 **"현재 공개 API 표현 범위 밖, 계약 개정 항목"**으로만 기록한다. 아래 `SUPPLIES_TO` 등은 그 개정을 논의할 때 쓰는 보류 초안이다. depth는 §0의 operation별 규칙을 따른다. 노드 limit은 prototype 값(기본 500, 최대 1000)으로 시작하고 실제 규모를 측정한 뒤 다시 본다.

현재 PoC의 직접 관계 유형은 `INVOLVES`, `STRUCTURALLY_RELATED_TO`, `FOLLOWS`이고 prototype의 `SHARES_ISSUE`는 파생이다. **원격 main의 현재 AI focus**는 `SUPPLIES`, `INVESTS_IN`, `COMPETES_WITH`, `PARTICIPATES_IN`, `RELATES_TO_TOPIC`을 반환한다. 아래 `SUPPLIES_TO` 등은 공개 API용 **별도 제안명**이며 현재 AI wire 값이 아니다. FS078의 공급·고객·경쟁·투자 직접 관계를 `SHARES_ISSUE`에 넣는 것은 의미 오류다. 다음 OpenAPI 개정에서 검증된 직접 관계 유형과 변환 규칙을 제안한다.

| 제안 유형 | 방향 | 의미 |
| --- | --- | --- |
| `SUPPLIES_TO` | 공급 기업 → 고객 기업 | 공급과 고객은 같은 사실의 양끝 역할이다. 역방향 복제 간선을 만들지 않는다. |
| `INVESTS_IN` | 투자자 기업 → 투자 대상 기업 | 투자 관계의 방향을 고정한다. |
| `COMPETES_WITH` | 기업 ID 오름차순으로 정규화 | 대칭 경쟁 관계를 중복 저장하지 않는다. |

사업/제품 범위와 유효 시작·종료가 확인되지 않았다면 임의 값을 만들지 않고 별도 미상 상태를 보존한다. 직접 관계의 필수 근거·지원 유형은 FS055/FS078 담당자와 승인한 뒤 enum·필드에 반영한다. 이 승인이 있기 전 공개 API는 현행 네 유형만 반환한다.

**(10-16 확정이 이 문단보다 우선한다: depth는 operation별 규칙, limit은 기본 500·최대 1000. §0 참고.)** 탐색은 **실제 관계만** BFS로 세자는 공개 조회 제안이다. `SHARES_ISSUE`는 화면 표시용 파생 지름길이므로 탐색 단계 계산에서 제외한다. 다만 현재 내부 focus는 시작 회사에서 **무방향 BFS 1~3홉**이며, 간선의 한 끝점이 `depth-1` 이내면 표시한다. 내부 `depth=2` 응답을 공개 기업→사건/이슈→기업 2단계와 동등하다고 가정하지 않는다. `getGraph.depth` 생략은 기준 기업의 전체 연결 성분, `getCompanyGraphAsOf.depth`는 1 또는 2다. 내부 focus만으로는 무제한 전체 연결 성분 조회를 보장하지 않으므로 공개용 스냅샷 원본 인계와 별도 탐색이 필요하다. 노드 제한은 요청 시작 시 적용한 정책값을 `metadata.limit`에 기록하고, `(최근 승인 사건 시각 내림차순, ID 오름차순)`으로 안정 정렬한다. 기준 기업은 우선 보존하고, 노드/간선이 잘리면 `truncated=true`로 표시한다. 기본 제한 수치는 prototype 값(기본 500, 최대 1000)으로 시작한다. 실제 그래프 크기·지연을 측정한 뒤 OpenAPI 수치를 다시 본다.

## 6. 수정할 파일과 순서 — 이 문서에서는 실행하지 않음

> **10-16 상태:** 1번 서진님 검토는 1차 회신으로 끝났다. 남은 것은 인계 계약 v1이다. 4번의 Java 소비자는 status만 활성화 전 검증 입력으로 쓴다. focus는 스냅샷 입력으로 쓰지 않으므로, 앱의 다음 작업은 인계 묶음 수입기다. 5번의 "scope가 다른 직접 관계" 사례는 회사–회사 관계가 공개 범위 밖이 되어 계약 개정 때로 미룬다. 대신 geography 미판정·근거 누락 제외, 날짜만 있는 시각의 asOf 경계, 현재 철회 후 과거 버전 조회, 필터 뒤 `SHARES_ISSUE` 재계산을 추가한다.

1. **서진님 검토:** 이미 제공되는 status/focus 계약을 출발점으로 삼아, 스냅샷에 필요한 **전체 고정 결과 인계**, 여러 S3 작업의 공개 버전 합성, `company/event/topic`와 공개 `company/issue` 대응, 근거 상세 공급 경로, 앱/AI 작업 ID와 원천/검수 revision의 연결, geography 검증 가능성, 표시 간선 scope 키, 제외 overlay의 통지·복구 경계를 확인한다. 공개용 스냅샷 생성은 앱 분담안이며 과거 버전별 Neo4j 조회 제공 여부를 공개 API의 선행조건으로 묻지 않는다.
2. **목표 API:** `docs/api/openapi.yaml`의 `publicationVersions`, `getGraph`, `getCompanyGraphAsOf`, `getCompanyRelation`, `GraphNode`, `GraphEdge`, `EdgeDetail`, `GraphMetadata`, `EventDetail` 설명을 확정된 의미로 갱신한다. 직접 기업 관계 enum/필드는 FS055/FS078 승인 후 별도 계약 변경으로 반영한다.
3. **저장 설계:** `docs/erd/zoop-core-erd-v6.md`의 `graph_versions`, `graph_activations`, `artifacts`, `evidence`, 현재 권리/관계 제외 저장소와 API 매핑에 앱 생성 스냅샷·버전 선택·근거 ID·제외 revision을 반영한다. 이미 적용한 migration은 수정하지 않고 필요한 새 migration을 만든다.
4. **내부 연계:** 인수 문서의 read-only status/focus를 호출하는 Java 소비자를 먼저 설계한다. `ready/current`와 withheld/503을 구분하고 digest pin을 확인한다. AI 결과/GraphDB writer의 추가 고정 원본 인계에는 `versionId`, 정규 ID, 공개 근거 ID, scope, geography, 검증/제외 정보를 합의한다. 앱은 그 후 스냅샷 생성·검증·보관, 버전 선택, 스냅샷 읽기 경계를 구현하고 저장 모델을 HTTP DTO와 분리한다.
5. **계약 검증 사례:** 같은 요청 중 활성 버전 변경, `asOf` 전후 활성화·재활성화, 등록만 한 버전, 스냅샷 파일 누락·해시 불일치, 서로 다른 근거가 한 표시 간선으로 합쳐짐, scope가 다른 직접 관계, 미판정 geography, 근거 철회 후 과거 버전 조회, writer 적재 장애·스냅샷 생성 장애와 정상 0건, 앱/AI 작업 ID·revision 혼동, S2 완료 후 무권한 S3 요청, 응답 유실 뒤 동일 ID 복구, 결과 수입 직전 권리 철회, 읽기 전용 영향 조회만 완료된 상태, 개인화 정보의 전체 모드 누출, 기업→이슈→기업 2-hop을 fixture로 확인한다.

## 서진님에게 확인받을 최종 선택

> **10-16 1차 회신 반영 현황.** 아래 질문 대부분은 §0에서 방향이 확정됐다. 남은 것은 AI 측 인계 계약 v1의 구체 형식이다(manifest 필드, 충돌 규칙, event→issue 대응표, 간선 투영 검증 규칙, geography 근거·정책 버전, 원천/검수 revision 처리 결과, 철회 완료 신호, recover 경로). 작업 연결 키(`analysisJobId + unitKey ↔ aiJobId`, `aiAttemptId`, `commandKey`)와 최종 활성화 권한·운영 절차는 아직 회신이 없다.

- 앱이 불변 스냅샷을 만들 수 있도록 writer가 `versionId`에 고정된 기업·사건/이슈·관계·근거 데이터를 어떤 결과물 또는 조회 경로로 인계할지. 생성 도중 원천 버전이 바뀌지 않도록 무엇으로 보장할지 **→ 확정(10-16): AI가 manifest + 전체 내용 + digest로 인계. 형식은 인계 계약 v1.**
- **현재 `freeze`가 S3 작업 한 건을 버전 하나로 묶는 구조에서** 여러 작업의 공개 그래프를 어떻게 합성할지. 전체 공개 결과 export 또는 동등한 고정 인계가 가능한지. 내부 focus는 회사별 1~3홉이므로 전체 snapshot의 완전성 근거로 쓰지 않는다. **→ 확정(10-16): 여러 원천 작업을 manifest에 고정해 AI가 제공. 앱 임의 병합·focus 반복 호출 금지.**
- 현재 status가 주는 `ready/current`·`graphDigest`·`payloadDigest`·노드/간선 개수 이외에 근거 참조 수, 자동 검증 revision, 완료 시각, 항목별 실패 사유를 어떤 경로로 받을지. 부분 성공과 writer 명령 재전송을 어떻게 확인할지. 현재 내부 HTTP에는 recover/생성 라우트가 없다. **→ 부분 확정(10-16): 검증 시각·version·digest·저장소 관측 상태와 공개 수치는 분리. 세부 형식은 인계 계약 v1.**
- 위 `analysisJobId + unitKey ↔ aiJobId`, 별도 `aiAttemptId`, 버전별 `commandKey` 인계안을 사용할 수 있는지. `sourceVersion`/`sourceRevision`과 앱 검수 revision을 별도 필드로 보낼 수 있는지. 응답 유실 시 제안한 writer 상태의 실제 이름·조회/복구 방법은 무엇인지 **→ 부분 확정(10-16): revision 분리와 기존 ID recover는 확정. 작업 연결 키는 회신 없음(제안·확인 필요).**
- 스냅샷은 앱이 생성·검증·보관하고 공개 API가 스냅샷의 메인/기업 그래프·연결선·사건/이슈·근거 상세를 확인한 뒤 활성 포인터를 전환하는 분담안이 맞는지. 최종 전환 권한과 운영 절차는 누구에게 있는지 **→ 확정(10-16): 분담안 수락. 최종 전환 권한·운영 절차만 미정.**
- AI 결과의 공개 사건/이슈 ID와 앱 `evidence.id`를 어디서 확정하고 writer에 전달할지. `mentionId`는 문서별 언급 ID로 별도 유지할지 **→ 확정(10-16): canonical issue ID는 대응표로 연결, mention은 별도 유지, evidence ID는 앱이 article/version 연결 후 발급.**
- 내부 `event`가 공개 사건/이슈의 안정 ID와 같은지, 내부 `topic`을 공개 그래프에서 제외할 때 관계·경로 의미를 어떻게 보존할지. 내부 근거 좌표에 없는 인용문·기사 제목/URL·검수 정보는 어느 고정 자료에서 받을지 **→ 확정(10-16): event ≠ 공개 issue(대응표 필요), topic은 제외하되 경로를 직접 연결로 바꾸지 않음, 인용문·제목·URL은 앱 article version에서.**
- 내부 `SUPPLIES/INVESTS_IN/COMPETES_WITH/PARTICIPATES_IN/RELATES_TO_TOPIC`과 공개 관계 enum·role·표시 `edge.id`의 구체적인 대응, 무방향 BFS 깊이와 공개 탐색 규칙의 차이를 어떻게 처리할지 **→ 확정(10-16): enum 치환 금지, 검증된 경우에만 투영(규칙은 인계 계약 v1), 회사–회사 관계는 공개 범위 밖, 표시 edge.id는 prototype 규칙, depth는 operation별.**
- 검증된 geography와 직접 기업 관계의 scope/유형/방향을 어떤 결과 필드에서 보장할지 **→ 확정(10-16): geography는 AI가 근거·정책 버전과 함께 제공하고 미판정은 제외. 직접 기업 관계는 공개 범위 밖.**
- 현재 권리 철회·오연결에 대한 `exclusionRevision`은 누가 발급·저장·통지할지. writer가 대상별 `appliedExclusionRevision`과 실제 Neo4j 검증 결과를 제공할 수 있는지. 앱 조회 차단과 writer 반영이 모두 완료된 신호를 어떤 방식으로 확인할지 **→ 부분 확정(10-16): 단일 exclusionRevision 대신 세 revision 분리. 철회 완료 신호는 아직 미구현이며 인계 계약 v1 대기.**
- 읽기 전용 영향 조회로 찾은 대상의 실제 재검증·비활성화 실패를 어떤 단계 상태로 돌려줄지 **→ 미정: 인계 계약 v1 대기.**

검토 결과는 각 항목을 **수락 / 수정안 / 보류**로 표시해 반영한다. 서진님과 합의되기 전에는 이 문서의 권장안을 확정된 API 계약이나 구현 완료로 표시하지 않는다.
