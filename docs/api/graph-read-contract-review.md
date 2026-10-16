# 그래프 조회 계약 대조안

작성: 2026-10-15 · 상태: **PoC/프로토타입 대조 완료, 본개발 저장·조회 경계 팀 확인 필요**

> **10-16 갱신:** 이 문서의 질문 대부분은 사용자 결정과 서진님 1차 회신으로 방향이 정해졌다. 결정 내용은 [`graph-read-contract-proposal.md` §0](graph-read-contract-proposal.md)에 있다. 이 문서는 대조 기록이므로 원문을 남기고, 바뀐 곳에 "10-16 결정"을 덧붙였다. AI 측 인계 계약 v1의 구체 형식은 아직 남아 있다.

이 문서는 `investmate-poc`의 Neo4j 투영과 `prototype/bff`의 공개 응답 조합을 현재 목표 API와 대조한 인계 자료다. 공개 HTTP 계약의 정본은 [`openapi.yaml`](openapi.yaml)이다. 아래의 「확인 필요」 항목은 합의나 구현 완료를 뜻하지 않는다. 관련 업무는 FS017·FS018·FS023·FS024·FS042·FS055·FS059·FS078~081 및 WBS 6.6.1·6.6.2·6.7.5에 걸친다.

## 조회 경계

| 단계 | 관찰한 초안 | 본개발 조회 계약 |
| --- | --- | --- |
| 분석 원천 → Neo4j | `investmate-poc/src/investmate/graph.py`는 `InvestMateIssue`, `InvestMateCompany`, `InvestMateArticle`과 `relation_id`가 붙은 관계를 이슈 단위로 교체한다. `inspect(issue_id)`는 진단용 이슈 투영을 반환한다. | 이 투영을 공개 API 응답이나 버전별 공개 그래프로 직접 간주하지 않는다. 승인·검증·권리 조건을 통과한 데이터와 **요청에 고정된 공개 버전**만 조회 대상으로 삼는다. |
| 버전별 공개 자료 | `prototype/bff/src/zoop_bff/graph_versions.py`는 변경 불가 JSON 스냅샷과 활성 버전을 유지한다. | ERD v6의 `graph_versions`·`graph_activations`가 버전·활성화 이력을 관리한다. Neo4j 또는 불변 스냅샷에서 지정 버전의 과거 자료를 실제로 재현해야 한다. `graph_db_state`의 저장/투영 상태와 공개 활성화는 별개다. **10-16 결정:** 공개 조회는 앱이 소유한 버전별 불변 스냅샷만 읽는다. 과거 버전을 Neo4j에서 직접 읽는 것은 공개 조회의 조건이 아니다. |
| 응답 조합 | `prototype/bff/src/zoop_bff/dataset.py`, `graph.py`는 원천 관계를 화면 간선으로 묶고 기업 카탈로그·회원 정보를 노드에 결합한다. | 본개발 API가 버전을 먼저 고정하고 그래프 조회 결과에 PostgreSQL 기업 정보와 요청자 개인화 상태를 결합해 `GraphResponse`/`EdgeDetail`을 만든다. `prototype/`를 런타임 의존성으로 가져오지 않는다. |

## 공개 조회 요청과 응답

| OpenAPI operationId | 요청에서 고정할 것 | 응답과 조회 규칙 |
| --- | --- | --- |
| `getGraph` — `GET /api/v1/graph` | `mode`, `companyId`, `depth`, `round`, `graphVersion`, `asOf`, `personalFilter`; 개인화는 회원 본인 확인 | `GraphResponse`. 요청 시작에 공개 버전을 한 번 선택한다. 기준 기업은 관계가 0건이어도 유지한다. `round`는 발행 회차의 버전을 사용한다. 개인화 필터는 요청자 보유·관심 기업에서 구한다. |
| `getCompanyGraphAsOf` — `GET /api/v1/companies/{id}/graph` | 기업 ID, 오프셋이 있는 필수 `asOf`, 선택 `graphVersion`, `depth` 1 또는 2 | 같은 `GraphResponse`를 사용하며 선택 시점 이후에 공개된 자료를 섞지 않는다. |
| `getCompanyRelation` — `GET /api/v1/graph/edges/{id}` | 화면 간선 ID와 `round`/`graphVersion`/`asOf` | `EdgeDetail`. 기업 간 간선만 선택 가능하다. 간선 상세도 그래프와 **같은 공개 버전**에서 읽어야 하며, 이슈–기업 간선은 이 URI의 직접 선택 대상이 아니다. |

OpenAPI의 공통 `publicationVersions` 규칙대로 `graphVersion`과 `asOf`를 함께 주면 일치해야 한다. 요청한 버전이 없으면 `VERSION_UNAVAILABLE`로 응답하며 현재 최신 자료로 대체하지 않는다. 조회 원천 장애는 빈 그래프로 꾸미지 않고 `SOURCE_UNAVAILABLE`로 구분한다. 실제 0건이면 성공 응답의 `nodes`/`edges`와 `metadata.emptyReason`으로 설명한다.

## 필드 대조 및 조합 책임

| 공개 필드 | PoC/프로토타입의 대응 | 본개발에서 지킬 의미 |
| --- | --- | --- |
| `GraphNode.id`, `kind` | Neo4j `company_id`·`issue_id`; 프로토타입은 company/issue만 노출 | 기업 ID는 PostgreSQL `companies.id`와 같아야 한다. 기사 노드는 공개 그래프에 넣지 않는다. PoC의 `issue_id`, 공개 `eventId`, 사건 `mention_id`의 대응은 별도 확정이 필요하다. |
| `GraphNode.label`, `brandColor`, `logoUrl` | 이슈 제목은 분석 결과, 기업 이름·색·로고는 프로토타입 카탈로그에서 조합 | 기업 표시 정보는 버전에 고정된 카탈로그 값을 사용한다. 현재 PostgreSQL 값을 과거 버전 응답에 그대로 섞지 않는다. 이슈 표시 정보는 해당 버전의 승인 자료를 사용한다. |
| `GraphNode.isFocus`, `holding`, `watch` | `select_graph`가 기준 기업과 요청자 상태를 조합 | `isFocus`는 조회 범위, `holding`·`watch`는 인증된 요청자의 앱 데이터에서 산출한다. 이 값을 Neo4j의 전역 회사 속성으로 저장하지 않는다. 전체 모드에는 개인 정보를 노출하지 않는다. |
| `GraphNode.eventTime`, `timePrecision`, `action`, `target` | PoC mention/issue와 프로토타입 `IssueRec` | 이슈의 승인된 값과 시각 정밀도를 사용한다. 알 수 없는 날짜를 정확한 timestamp로 만들지 않는다. 기업 노드의 해당 값은 `null`이다. |
| `GraphNode.evidenceCount` | 프로토타입은 이슈의 중복 제거된 `evidence_ids` 길이 | 같은 버전의 이슈 상세 `evidenceIds` 개수와 일치해야 한다. 기업 노드는 `null`이다. |
| `GraphNode.geography` | PoC에는 mention의 `countries`가 있으나 프로토타입 `GraphNode`에는 필드가 없다 | 공개 이슈에는 검증된 `domestic`/`international` 값이 필요하다. 국가 목록만으로 임의 변환하지 않는다. 미판정 이슈는 공개 검증에서 제외하거나 보완한다. 기업 노드는 `null`이다. |
| `GraphEdge.id` 대 `relationIds` | PoC의 `relation_id`는 원천 관계 ID. 프로토타입은 `(relationType, source, target)`별로 원천 관계를 묶어 `edge-…` 표시 ID를 만든다 | 경로 `{id}`는 **표시 간선 ID**다. `EdgeDetail.relationIds`는 이를 구성하는 원천 관계 ID 목록이다. 둘을 동일 ID로 취급하지 않는다. 표시 ID와 버전별 상세의 안정성은 합의가 필요하다. |
| `GraphEdge.relationType`, `source`, `target`, `role`, `summary`, `assertionStatus` | `INVOLVES`, `STRUCTURALLY_RELATED_TO`, `FOLLOWS`를 승인 자료에서 화면 간선으로 만든다. `REPORTS`, `PROVIDES_BACKGROUND`는 기사 근거 연결이다 | OpenAPI의 사용자 그래프 enum은 위 세 유형과 `SHARES_ISSUE`다. 방향·역할·요약은 승인 자료에 근거한다. 기사→이슈 provenance를 화면 간선으로 내보내지 않는다. |
| `GraphEdge.derived`, `via`, `evidenceIds` | 프로토타입 `SHARES_ISSUE`는 같은 이슈를 공유한 두 기업에서 파생한다. `via`는 이슈 ID, 그래프 간선의 `evidenceIds`는 빈 배열이다 | `SHARES_ISSUE`를 실제 공급·고객·투자 관계로 표현하지 않는다. 상세 `ViaIssue.evidenceIds`로 양쪽 이슈 연결의 근거를 추적한다. 직접 간선의 `evidenceIds`는 승인 원천 관계의 근거 ID다. |
| `EdgeDetail.basis`, `verification`, `directed`, `roles`, `explanation` | 프로토타입이 묶인 관계의 근거/역할과 파생 경로를 조합 | 같은 버전의 원천 관계와 검증 결과에서 만든다. `verification=ALLOW`를 단순 저장 성공의 기본값으로 만들지 않는다. 파생 간선은 직접 검증된 관계와 구분한다. |
| `GraphMetadata.graphVersion`, `asOf`, `mode`, `focusCompanyIds`, `depth`, `limit`, `truncated`, `emptyReason`, `requestId`, `partial`, `failures`, `personalFilter` | 프로토타입은 버전 스냅샷과 필터 결과로 작성 | 공개 응답에 실제 사용한 버전 ID를 담는다. 버전/시점은 응답 전체에서 하나로 고정한다. 부분 실패는 성공한 영역만 유지할 수 있는 경우에만 표시하며 필수 그래프를 못 읽으면 503이다. `truncated`는 크기 제한으로 일부 노드/간선을 제외한 사실을 뜻한다. |

PoC `Evidence`는 `(article_id, article_version, start, end, quote)`이며 ID가 없다. 프로토타입은 `(article_id, version, start, end)` 해시로 `ev-…` ID를 만들지만 ERD v6에는 PostgreSQL `evidence.id`가 있다. **공개 `evidenceIds`는 실제 `GET /api/v1/evidence/{id}`로 찾을 수 있는 ID여야 한다.** 해시와 DB ID가 다르면 버전별 매핑이 필요하다.

**10-16 결정:** AI는 문서 ID·불변 버전·raw 버전·span·원문 위치를 제공한다. 앱 등록 단계에서 이를 앱 article/version에 명시적으로 연결하고, 결정적 규칙으로 앱 `ev-`(64 hex) ID를 발급·보존한다. 재수입해도 중복 생성하지 않는다. AI나 prototype의 `ev-` ID는 접두어·길이만 바꿔 재사용하지 않는다. 인용문은 앱의 불변 본문 span에서 검증하고, 제목·URL·발행 시각은 같은 article version에서 읽는다. 그래프 근거가 `getEvidence`로 실제로 열려야 인계 완료다.

## 서진님 writer ↔ 세빈님 API에서 맞출 최소 읽기 경계

1. **입력:** 공개 `graphVersion` ID와 그래프 범위(전체/기준 기업·깊이). writer가 제공하는 실제 저장 버전 ID, 투영 상태, 실패 사유를 앱의 `graph_versions`와 대조한다. 현재 Neo4j 내용이라는 암묵적 선택은 사용하지 않는다.
2. **출력:** 그 버전의 기업·이슈 ID/이슈 표시·시각·지리 속성, 방향이 있는 원천 관계 ID/유형/역할/근거 ID/검증 상태, 관계별 이력·제외 상태, 표시 간선과 원천 관계의 대응. 공개 API는 카탈로그·회원 데이터와 합쳐 OpenAPI 응답을 만든다.
3. **공개 준비:** 저장 성공, 버전 전체 조회 가능, 메인 그래프와 기업 상세의 같은 버전 조회, 현재 공개 조건·권리 확인을 각각 구분한다. 모두 확인되기 전 활성 포인터를 바꾸지 않는다. 무효 관계는 직접 조회·캐시·과거 버전에서도 재노출되지 않아야 한다.
4. **빈 결과/오류:** 승인된 이슈·관계 0건, 요청 버전 없음, Neo4j/스냅샷 장애, 근거 접근 불가를 서로 다른 상태로 반환한다. 실패를 0건, `graphVersion=null`, 임시 간선으로 바꾸지 않는다.

**10-16 결정 (위 1·2의 경계):** 공개 API는 조회할 때마다 writer를 부르지 않는다. AI가 **버전 있는 인계 계약**으로 인계 묶음을 제공한다. 묶음은 여러 원천 작업의 ID·input digest·원천/검수 revision·canonical 매핑·정책 버전을 고정한 manifest와 전체 내용, 그 digest로 구성된다. 앱은 이를 수입·검증해 자체 형식의 스냅샷으로 등록하고 별도로 활성화한다. 인계 묶음 ID와 앱 `graphVersion`은 다르고, 인계 준비 완료는 공개 승인이 아니다. 내부 focus를 반복 호출해 전체 자료를 모으지 않는다. 같은 ID인데 내용이 다르면 충돌로 처리한다.

## 합의가 필요한 차이

| 우선 | 질문 | 결정되면 반영할 곳 |
| --- | --- | --- |
| 1 | PoC의 이슈 `issue_id`와 공개 사건 `eventId`는 같은 ID인가? 아니라면 매핑의 소유자와 버전은? | AI 결과 계약, 그래프 조회 어댑터, 사건 상세 API |
| 1 | `evidence.id`를 writer가 받아 저장하는가, PoC 구간 해시를 앱이 같은 ID로 채택하는가? 삭제·수정된 문서의 과거 근거는 어떻게 조회하는가? | AI→앱/그래프 계약, ERD/근거 조회 |
| 1 | 지정한 `graphVersion`의 과거 상태를 Neo4j에서 버전별로 보존하는가, 불변 snapshot을 읽는가? Neo4j 투영 실패·상태 `pending`일 때 어떤 원천을 읽는가? | FS080 writer, 버전 활성화, 공개 조회 어댑터 |
| 1 | `geography`의 검증된 생성·저장 주체와 미판정 이슈의 공개 제외 규칙은? | FS079 검증, FS080 투영, `GraphNode` |
| 1 | 원천 `relation_id`가 여러 건 묶이거나 관계 속성이 바뀔 때 표시 `GraphEdge.id`와 상세 `{id}`를 어떻게 안정화하는가? | writer·API 간선 키, 캐시 키 |
| 2 | FS078의 직접 기업–기업 공급/고객/경쟁/투자 관계를 현행 `GraphEdge` enum에 어떻게 표현할 것인가? 현재 PoC 관계와 OpenAPI에는 전용 유형이 없다. | FS055/FS078 공통 간선 스키마와 OpenAPI 변경 제안 |
| 2 | `asOf`의 “공개 시각”은 버전 발행 시각인가 활성화 시각인가? 재활성화·시점 정밀도 처리 기준은? | ERD v6 `graph_activations`, OpenAPI `publicationVersions` |
| 2 | `depth`의 hop과 노드 수 제한·정렬·잘림 기준은? 프로토타입의 회사→이슈→회사 1단계 및 `FOLLOWS` 확장과 목표 `getCompanyGraphAsOf`의 “실제 연결선 hop” 설명이 다르다. | `getGraph`, `getCompanyGraphAsOf`, 조회 fixture |

### 10-16 결정 결과 (위 표의 질문별)

| 질문 | 결정 | 남은 일 |
| --- | --- | --- |
| `issue_id` ↔ 공개 `eventId` | 공개 용어에서 사건과 이슈는 같은 대상이다. 공개 `issue.id`는 canonical issue ID다. 문서별 mention, 작업 내 event 후보와 구분하고 **명시적 대응표**로만 연결한다. AI 내부 event ID가 곧 공개 ID라고 보지 않는다. | 대응표는 AI 인계 계약 v1에 포함(서진님) |
| `evidence.id` | 앱이 발급한다. 위 "10-16 결정" 문단 참고. | 앱 생성 규칙과 그래프 근거의 `getEvidence` 연결(WBS 6.6.9) |
| 과거 버전 원천, 투영 실패 시 | 앱 불변 스냅샷만 읽는다. Neo4j 투영 상태(`ready/current` 등)는 활성화 전 검증 입력일 뿐이며 `reflected`/active로 자동 변환하지 않는다. 내부 Neo4j 응답 유실은 기존 version ID로 확인한 뒤 recover한다. | 인계 계약 v1, 앱 수입·활성화 멱등성 |
| `geography` | AI가 이슈의 발생·영향 지역 근거와 판정 정책 버전을 제공한다. 기사 언어·언론사 국적·상장 시장만으로 판정하지 않는다. 근거가 없거나 충돌하면 미판정이고 공개에서 제외한다. | AI 제공 형식, 미판정·근거 누락 fixture |
| 표시 `GraphEdge.id` 안정화 | prototype 규칙 `edge-` + SHA-256(유형, source, target)을 쓰고 원천 ID는 `relationIds`로 노출한다. 공개 간선은 한 끝이 이슈이므로 scope를 키에 넣지 않는다. | 회사–회사 관계가 공개 범위에 들어오면 재검토 |
| FS078 직접 기업 관계 | 현행 enum에 넣지 않는다. **"현재 공개 API 표현 범위 밖, 계약 개정 항목"**으로 기록한다. `SUPPLIES`·`INVESTS_IN`·`COMPETES_WITH` 자체는 `STRUCTURALLY_RELATED_TO`의 근거가 아니다. 공개 간선 투영(참여 → `INVOLVES`, 구조 근거 경로 → `STRUCTURALLY_RELATED_TO`, 선후 → `FOLLOWS`)은 enum 치환이 아니라 검증된 경우에만 한다. topic은 공개 노드에서 빼되 topic 경유 경로를 직접 연결로 바꾸지 않는다. | 투영 검증 규칙(서진님), OpenAPI 개정 제안 |
| `asOf`의 공개 시각 | 두 단계를 모두 적용한다. ① `graph_activations`의 활성화 시각으로 그 시점의 공개 버전을 고른다. ② 그 버전 안에서 기사 발행·관계 검증/유효·공개 시각을 구분해 거른다. 날짜만 있는 값은 임의 시각으로 만들지 않고 날짜 정밀도로 비교한다. 현재 공개 제외는 asOf와 무관하게 항상 적용한다. | 재활성화 처리를 인계 시험에 포함 |
| `depth`·limit | operation별 정본 설명을 따른다. `getGraph`는 회사→이슈→회사를 1 hop으로 센다(prototype). `getCompanyGraphAsOf`(1·2)는 실제 연결선 수를 센다. `SHARES_ISSUE`는 탐색에서 제외하고, 권한·asOf·공개 제외 뒤 남은 이슈로만 파생한다. limit은 기본 500, 최대 1000이다. 기준 기업을 먼저 넣고, 최신 이슈 순으로 채우고, 넘치면 `truncated`를 표시한다. | 두 operation의 통일은 OpenAPI 개정 항목. 실제 규모 측정 후 limit 재검토 |

합의 후에는 **이 문서만 고쳐서 계약 완료로 처리하지 않는다.** 변경된 의미를 `openapi.yaml`, 필요한 ERD/AI 내부 계약, 양쪽 구현·계약 fixture에 같은 PR로 반영한다.

## 근거 위치

- 목표 API: `docs/api/openapi.yaml`의 `publicationVersions`, `getGraph`, `getCompanyRelation`, `getCompanyGraphAsOf`, `GraphNode`, `GraphEdge`, `GraphMetadata`, `EdgeDetail`
- 저장·버전 경계: `docs/erd/zoop-core-erd-v6.md`의 24절 `graph_versions`, 25절 `graph_activations`, API 매핑, 남은 결정 항목
- Neo4j 초안: `C:/work/project/zoop-proto/investmate-poc/src/investmate/domain.py`, `C:/work/project/zoop-proto/investmate-poc/src/investmate/graph.py` (별도 저장소)
- 응답 투영 초안: `prototype/bff/src/zoop_bff/dataset.py`, `graph.py`, `graph_versions.py`, `schemas.py`
