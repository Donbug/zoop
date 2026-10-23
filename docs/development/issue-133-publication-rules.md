# Issue #132·#133 · 공개 규칙 v1

## 범위와 기준

- WBS `6.10.6`·`6.10.7`, FS059·FS067-01·FS067-02, 화면 `A-ADM-03`. 정본 HTTP 계약은 [`docs/api/openapi.yaml`](../api/openapi.yaml)의 `listPublicationRules`·`setPublicationRule`(`ReviewRuleOut`)이고, 저장 제약은 [ERD v6](../erd/zoop-core-erd-v6.md) 28·29절이다.
- 기준이 서로 다르면 AI 담당 답변(2026-10-22, 1·4·5-A번)과 API 계약을 먼저 따른다.
- 현재 구현: 규칙 저장·스위치·이력(`publication_rules`, `publication_rule_changes`)만 있다. 이 문서의 두 규칙은 아직 등록하지 않았고, 판정 함수와 수입 적용은 아직 없다(4절).
- 이 문서는 팀 검토용 설계다. 팀 승인 전에는 구현 완료나 확정 정책으로 보지 않는다.

## 0. 규칙이란

- 규칙은 **앱 공개 정책**입니다. AI가 통과시킨 관계와 관리자가 허용(allow)한 관계 중에서, 조건에 맞는 것을 공개 그래프에서 **숨기기만** 합니다.
- 규칙은 다음을 하지 않습니다(AI 5-A).
  - HOLD를 공개하지 않습니다.
  - HOLD를 승인이나 거절로 바꾸지 않습니다.
  - AI 판정 입력을 바꾸지 않습니다.
  - AI를 호출하지 않습니다.
- 규칙은 HOLD 검수의 판단 기준이 아닙니다. 관리자는 규칙을 켜고 끄기만 하고, 어떤 내용이 숨겨질지는 시스템이 조건대로 정합니다.
- 프로토타입 R1("역할만 빼고 HOLD 공개")은 가져오지 않습니다.

## 1. 규칙 목록

| id | 이름 | 대상 | 기본값(`default_enabled`) |
| --- | --- | --- | --- |
| `single-source@1` | 출처가 기사 1개뿐인 관계 숨기기 | 관계 | **켜짐** |
| `speculative-issue@1` | 취소·전망 이슈 숨기기 | 이슈(와 그 관계) | **꺼짐** |

- id는 `<ruleId>@<version>` 형식입니다. 조건이나 파라미터를 바꾸면 정의를 고치지 않고 새 버전(`@2`)을 등록합니다(테이블이 정의 변경을 막음).
- 초기 상태는 `default_enabled`입니다. 변경 이력(`publication_rule_changes`)은 관리자가 스위치를 바꿀 때만 쌓입니다.

### 규칙 1 — `single-source@1` 출처가 기사 1개뿐인 관계 숨기기

- **목적:** 기사 한 건에만 기대는 관계를 공개 그래프에서 빼서 신뢰도를 높입니다.
- **definition:**
  ```json
  {"kind": "single_source", "minSources": 2, "relationTypes": ["INVOLVES", "STRUCTURALLY_RELATED_TO"]}
  ```
- **조건:** `relationTypes`에 속한 관계의 출처 기사 수가 `minSources`보다 적으면 숨깁니다.
- **파라미터 범위:** `minSources`는 2~100입니다(1이면 아무것도 숨기지 않음). `relationTypes`는 `INVOLVES`·`STRUCTURALLY_RELATED_TO` 중 하나 이상이며 중복은 허용하지 않습니다. 범위를 벗어난 정의는 2-3의 fail closed 대상입니다.
- **출처 기사 수를 세는 방법**
  - 관계 `evidenceIds`가 가리키는 근거의 기사를 셉니다. `STRUCTURALLY_RELATED_TO`는 여기에 구조 `basis[].sourceArticles`도 더합니다.
  - 그 합집합에서 **서로 다른 기사(`articleId`) 수**를 셉니다. 같은 기사의 여러 버전은 1건입니다.
  - **수입 시점 기준**으로 셉니다. 수입 뒤 권리 변경으로 가려지는 기사는 다시 세지 않습니다. 조회할 때의 권리 필터는 지금처럼 따로 적용되고, 규칙 결과에 더해 내용을 더 가립니다.
- **대상에서 뺀 것:** `FOLLOWS`(이슈→이슈 순서 관계)는 출처가 두 이슈의 기사에서 오므로 이 규칙을 적용하지 않습니다.
- **기본값 켜짐의 의미:** 첫 규칙 적용 버전부터 단일 출처 관계가 공개 그래프에 나오지 않습니다. 막 생긴 이슈는 두 번째 기사가 들어온 뒤의 수입부터 보입니다.

### 규칙 2 — `speculative-issue@1` 취소·전망 이슈 숨기기

- **목적:** 그래프를 "실제로 일어났거나 발표된 일" 중심으로 보여 줍니다. 취소된 일이나 전망이 확정된 관계처럼 보이지 않게 합니다.
- **definition:**
  ```json
  {"kind": "assertion_status", "hide": ["cancelled", "forecast"]}
  ```
- **조건:** 이슈의 `assertionStatus`가 `hide`에 있으면 그 이슈를 숨깁니다. 이 값은 snapshot에 들어 있는 생산자 값 그대로입니다(`occurred|announced|planned|forecast|cancelled|unknown`).
- **함께 숨기는 것:** 그 이슈의 `INVOLVES`·`STRUCTURALLY_RELATED_TO`, 그리고 그 이슈가 한쪽 끝인 `FOLLOWS`.
- **기본값 꺼짐의 이유:** 전망 기사도 투자자에게 가치가 있어서, 필요할 때 관리자가 켭니다. `planned`까지 숨기려면 `speculative-issue@2`로 등록합니다.

## 2. 적용 방식

### 2-1. 적용 시점: 수입할 때

- 인계 묶음을 수입해 snapshot을 만들 때, 그 시점에 켜져 있는 규칙으로 걸러서 저장합니다. 공개 조회 경로는 지금처럼 버전 하나만 읽고, 조회할 때 규칙을 계산하지 않습니다.
- 버전마다 `rule_revision`을 고정합니다. 공용 publication lock 아래에서 `COALESCE(MAX(publication_rule_changes.log_revision), 0)`을 읽습니다. `review_revision`(`MAX(review_decisions.global_revision)`)도 같은 잠금 아래에서 고정합니다(ERD 24절, AI 4번: 수입 → 비활성 등록 → 명시적 활성화).
- 같은 인계 묶음과 같은 규칙 상태에서는 항상 같은 snapshot이 나옵니다.

### 2-2. 규칙을 바꾸면: 같은 원본으로 새 비활성 버전

- 스위치를 바꿔도 지금 활성 버전은 그대로입니다. 화면에 "다음 버전부터 반영"이라고 안내합니다.
- 관리자가 "규칙 적용 버전 만들기"를 실행하면, 현재 활성 버전의 인계 묶음(receipt)에 지금 규칙 상태를 적용해 **새 비활성 버전**을 만듭니다. 관리자는 미리보기로 확인한 뒤 활성화합니다(#275).
- 이 과정에는 AI 호출도, 운영자 freeze/export도 필요 없습니다. 승인 1건마다 자동 공개하지 않는다는 원칙(AI 4번)과 같이, 규칙 변경도 명시적 활성화를 거쳐야만 공개됩니다.

### 2-3. 조건 정의: 정해진 종류 + 파라미터

- `definition.kind`는 코드에 있는 조건 종류만 허용합니다. v1은 `single_source`, `assertion_status` 두 가지입니다. 자유 식(DSL)은 두지 않습니다.
- 알 수 없는 `kind`나 잘못된 파라미터를 가진 규칙이 **켜져 있으면** 수입과 재적용을 실패시킵니다(fail closed). 모르는 규칙을 건너뛰어 숨겨야 할 내용이 공개되는 일을 막기 위해서입니다.

### 2-4. 판정 함수 하나

- `PublicationRuleEvaluator.apply(snapshot, enabledRules)` → snapshot의 부분집합(`com.zoop.graph.rules`). 입력은 공개 적격 snapshot이고 출력은 그 부분집합이라, 함수 모양으로 "숨기기만" 하도록 강제합니다.
- 수입 거르기, 재적용, `published*` 집계, `eligible` 집계가 모두 이 함수를 씁니다.

### 2-5. 숨긴 뒤 연결 정리 (고정 순서)

1. 이슈 규칙(규칙 2)으로 이슈를 숨깁니다.
2. 숨긴 이슈의 관계를 모두 숨깁니다.
3. 관계 규칙(규칙 1)으로 남은 관계를 숨깁니다.
4. 원래 회사와 이어진 관계(`INVOLVES`·`STRUCTURALLY_RELATED_TO`)가 있었는데 1~3번으로 모두 숨겨진 이슈를 숨깁니다. 처음부터 회사 관계가 없던 이슈는 이 단계에서 숨기지 않습니다(규칙이 하나도 없으면 결과가 입력과 같아야 하기 때문).
5. 숨긴 이슈가 끝에 있는 `FOLLOWS`를 숨깁니다.
6. 보이는 이슈·관계가 하나도 인용하지 않는 근거와 기사 버전을 뺍니다. 회사 노드는 카탈로그라 그대로 둡니다.

4~5번을 한 번 거치면 더 숨길 것이 생기지 않습니다. `FOLLOWS`는 회사 연결 판정에 쓰지 않기 때문입니다.

관계를 숨기는 것은 그 관계 주장(이슈-회사 연결)을 숨기는 것이지 기사 원문을 숨기는 것이 아닙니다. 보이는 이슈가 스스로 인용하는 근거(`evidenceIds`, `geographyEvidenceIds`)는 숨긴 관계가 같은 근거를 인용했더라도 이슈와 함께 남습니다.

### 2-6. 숫자

| 값 | 기준 | 언제 계산 | 비고 |
| --- | --- | --- | --- |
| `publishedCandidates`·`publishedEvents` | 그 버전에서 규칙 범위 안에 있으면서 규칙 적용 후 공개로 남은 수 | 버전을 만들 때 고정 | AI 5-A의 "freeze 당시 통계" |
| `eligible` | 활성 버전이 참조하는 원천 job 범위에서 규칙에 해당하는 HOLD 수 | 조회 시점(`review_targets`·원천 revision) | 현재 대기 건수(정보용). 4단계 전에는 null |

- 규칙 1의 `eligible`은 출처 기사가 1개뿐인 HOLD 관계 후보 수입니다. 관리자가 "이 후보는 허용해도 규칙 때문에 숨겨진다"는 것을 미리 알 수 있습니다.
- 규칙 2의 `eligible`은 이슈 `assertionStatus`가 `cancelled`·`forecast`인 HOLD 후보 수입니다. 원천 결과에 그 값이 있어야 셀 수 있습니다(4단계에서 확인).
- 후보 API의 `rule.applied`도 같은 기준입니다. 규칙이 켜져 있고 조건에 맞으면 결정 전 HOLD도 `true`이고, `hiddenRelations`는 "공개되면 숨겨질 관계"입니다. 숨기지 않는 이유(`notAppliedReason`)는 `rule_disabled`(꺼짐)·`admin_decision`(관리자가 거절한 후보, HOLD 여부와 무관)뿐입니다. 관리자가 허용한 HOLD는 `applied=true`입니다. 공개될 수 없는 후보(AI REJECT, 새 작업으로 대체된 비활성 후보)는 숨길 것이 없어서 `rule=null`입니다. 프로토타입의 `not_published`는 두지 않습니다.

## 3. 정해야 할 것

| # | 내용 | 누가 |
| --- | --- | --- |
| 1 | 버전에 고정할 `published*`와 적용 규칙 목록을 어디에 둘지(`graph_versions` 열 또는 버전 metadata). `GraphVersionOut` 계약 변경 필요 여부 | BE |
| 2 | "규칙 적용 버전 만들기" API. `publishGraphVersion`을 "수입·재적용 실행"으로 재정의할지(#146), 새 operation을 둘지 | BE |
| 3 | 규칙 1 출처 수 기준(기사 ID, 수입 시점)과 `FOLLOWS` 제외 확정 | 팀 |
| 4 | AI 검증 기준에 이미 출처 수 조건이 있는지(규칙 1과 겹침 여부). 결정권은 앱에 있고 AI 담당에게는 공유 | AI 담당에게 공유 |
| 5 | 원천 결과(S3 result)에 HOLD 후보의 출처 기사·이슈 `assertionStatus`가 있는지(`eligible` 집계용) | AI 담당에게 확인 |

## 4. 구현 순서

1. **규칙 저장소**(3단계, `feat/133-publication-rules`): 규칙 저장·스위치·이력. 이 문서의 규칙 행은 넣지 않습니다. 적용 로직 없이 넣으면 스위치를 켜도 아무 일도 일어나지 않기 때문입니다.
2. **판정 함수**: `single_source`·`assertion_status`와 2-5의 연결 정리, 단위 테스트(합성 snapshot).
3. **수입 경로(#146)**:
   - 판정 함수를 적용합니다.
   - `review_revision`·`rule_revision`·`published*`를 고정합니다.
   - 같은 migration에 규칙 2개를 seed합니다(`single-source@1` 켜짐, `speculative-issue@1` 꺼짐).
4. **재적용 경로**: 같은 receipt로 새 비활성 버전을 만들고, 미리보기 → 활성화합니다.
5. **`eligible` 집계**: 4단계 `review_targets` 동기화 뒤에 붙입니다.

## 5. 시험할 것

- 규칙 1: 출처 기사 1개 관계는 숨김, 2개는 공개. 같은 기사 두 버전은 1건. 구조 basis의 기사도 셈. `FOLLOWS`는 대상 아님.
- 규칙 2: `cancelled`·`forecast` 이슈와 그 관계·`FOLLOWS`는 숨김. `planned`·`announced`·`occurred`·`unknown`은 공개. 꺼져 있으면 아무것도 숨기지 않음.
- 연결 정리: 관계가 모두 숨겨진 이슈는 숨김. 숨긴 이슈를 가리키는 `FOLLOWS`는 숨김. 고아 근거는 제거.
- 숨기기만: 출력은 항상 입력의 부분집합. HOLD는 어떤 규칙 조합에서도 공개되지 않음.
- 재현: 같은 receipt와 같은 `rule_revision`이면 같은 snapshot 바이트.
- fail closed: 켜진 규칙의 `kind`를 모르면 수입·재적용 실패.
