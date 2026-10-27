# AI 챗봇 복합 질의·MCP·화면 동작 계약

기준일: 2026-10-27 / 상태: 합의된 목표 설계 · 구현 예정

상위 정책: [AI 거버넌스 v0.10](../ZOOP_AI_거버넌스_정책.md) / [설계 요약](ai-chatbot-design-summary.md) / [보조 웹 검색](ai-chatbot-web-search.md)

## 1. 하나의 기능, 필요한 도구 조합

Q02·Q03·Q04를 하나의 배타적 분류로 합치거나 매번 세 유형의 도구를 모두 실행하지 않는다. multi-label 분류를 유지하고 **한 질문에서 필요한 조회를 조합하여 한 답변으로 통합**한다. 개념·기업·관계 탐색을 하나의 사용자 기능으로 제공한다.

| 질문 예시 | 필요한 유형과 계획 |
| --- | --- |
| HBM이 뭐야? | Q02. 안정적 일반 설명은 도구 없이 최종 Luna 생성 |
| A기업의 최근 사건 알려줘 | Q03. 기업·이슈 조회, 필요 시 보조 웹 검색 |
| A와 B의 관계와 관련 사건, HBM 의미를 설명해줘 | Q02+Q03+Q04. 관계·사건·근거 조회를 조합하고 최종 Luna 생성에서 개념 설명과 통합 |
| 지도에서 A와 B 경로를 보여줘 | Q04. 공개 버전 경로 조회 후 유효한 경로 포커스 동작 제안 |

웹 검색은 Q02~Q08의 선택적 보조 도구이며 Q01에는 허용하지 않는다. 질의 유형·논리 기능·실제 도구는 1:1이 아니다. 동일 조회를 중복 제거하고 결과를 여러 requirementId에 연결한다. 고정 top-3 선택은 하지 않으며 필수 요구가 예산을 넘으면 범위를 확인한다. 최종 Luna 생성은 1회다.

## 2. 턴별 분류와 문맥

- 새 사용자 질문마다 새 job에서 요구 분해·Q 분류·실행 계획을 다시 만든다. 세션은 문맥을 보관할 뿐 유형을 고정하지 않는다.
- ‘그 회사’ 같은 후속 지시는 검증된 이전 대상·기간을 문맥 후보로 사용한다. 명시된 새 대상·기간이 우선하며 후보가 여럿이면 clarification한다.
- 소유권, 현재 공개 상태, 개인 범위는 매 job마다 서버가 확인한다. 과거 답변 자체는 새로운 사실의 근거가 아니다.
- 각 job 안에서는 확정된 graphVersion·asOf를 고정한다. ‘지금/최신’ 요청은 새 job에서 시점을 결정한다. 기존 job polling·재열람·복구는 재분류나 추가 도구 호출을 유발하지 않는다.
- clarification의 답은 `resolves`로 부모 요구와 연결하지만 새로운 job이다. 보완된 대상·기간과 현재 권한으로 계획을 검증한다. 기술적 재시도의 버전 고정 규칙은 기존 정책을 유지한다.

## 3. MCP 도입과 책임

현재 구현은 Java 내부 읽기 어댑터를 레지스트리로 호출한다. **목표는 기존 어댑터를 재사용하는 읽기 전용 MCP 서버 POC**다. 함수 호출 이름만 MCP로 바꾸지 않는다. ZOOP 서버가 MCP 클라이언트·오케스트레이터 역할을 맡고 모델은 승인된 논리 기능 후보만 제안한다.

- 논리 ID(`company.read`, `graph.path.read`, `web.search` 등)는 유지한다. 서버 관리 바인딩이 MCP 서버 ID·도구명·입출력 스키마 revision을 결정한다. `web.search`를 MCP 도구명 `web_search`에 연결할 수 있으며 이는 프로젝트 도구이지 MCP 표준 내장 검색 기능이 아니다.
- MCP 도구 목록을 읽어도 운영 allowlist가 자동 확장되지 않는다. 등록·검토·버전 고정 후에만 모델 후보와 실행 레지스트리에 반영한다.
- 서버가 검증한 subject·job·requirementIds·공개 버전·기한·권한 범위를 위조 방지된 실행 문맥으로 전달한다. 모델 인자의 userId로 개인 범위를 결정하지 않는다. MCP 서버도 호출자와 위임 범위를 검사한다.
- 최소 POC는 `company.read`, `issue.read`, `evidence.resolve`, `graph.path.read`, `web.search`를 우선 노출한다. 미구현 도구는 가짜 성공을 만들지 않고 unavailable capability로 남긴다.
- 그래프는 `PublicGraphReader`의 공개 스냅샷 경로를 재사용한다. 비공개 Neo4j나 AI 내부 그래프 API를 우회 공개하지 않는다.
- 포트폴리오 조회를 외부 공개 MCP 서버에 위임하지 않는다. 검색은 [보조 검색 계약](ai-chatbot-web-search.md)의 전송·grant·출처 규칙을 따른다.
- 로컬 POC 연결과 운영 transport·인증은 배포 환경에 맞게 확정·검증한다. 브라우저는 검색 공급자 키나 내부 MCP 자격 증명을 받지 않는다.
- MCP 왕복·서버 실행·공급자 호출을 기존 기한·실제 호출 예산에 포함한다. timeout·unavailable·잘못된 결과 스키마는 기존 실패 계약을 따른다.

## 4. 유형별 도구와 UI 동작

아래는 목표 매핑이다. 모든 도구·화면 동작이 구현됐다는 뜻이 아니다. Q02~Q08의 `web.search`는 공통 선택적 보조 도구다.

| 유형 | 주 도구/처리 | 연결할 수 있는 동작 |
| --- | --- | --- |
| Q01 | help.search, screenSpec.read, zoopPolicy.read | 승인된 서비스 화면·도움말 열기 |
| Q02 | Luna 일반 설명, 필요 시 zoopPolicy.read | 기본 화면 이동 없음, 검색한 경우 외부 출처 링크 |
| Q03 | company.read, issue.read, document.search, evidence.resolve | 기업 상세, 이슈·근거 열기 |
| Q04 | graph.path.read, evidence.resolve | 실제 간선·경로 포커스, 관계 상세·근거 열기 |
| Q05 | graph.version.diff, period.compare | 실제 지원되는 버전/기간 비교 화면 열기 |
| Q06 | briefing.read, briefing.evidence | 해당 회차 브리핑·근거 열기 |
| Q07 | portfolio.scope.read 후 공개 조회 | 내 종목 및 허용된 기업 상세 열기 |
| Q08 | selectionRule.read, evidence.resolve | 기록된 선정 설명·근거 열기 |

UI 동작은 DB 읽기 도구와 분리한다. 조회 결과의 유효한 ID를 서버가 typed UI 제안으로 만들고 브라우저가 사용자 클릭 후 실행한다. 조회했다고 자동 페이지 이동·자동 지도 변경을 하지 않는다. 임의 JavaScript·모델 생성 URL·자유 형식 라우트는 실행하지 않는다.

## 5. UI 계약 확장안

현재 `ChatResult.action`은 `set_watchlist` 안내 용도이며 새 동작들을 이미 수용하지 않는다. `graphTargets`만으로 간선·경로 UI가 완성됐다고 간주하지 않는다. 목표는 별도 `uiActions[]` 추가이며 기존 필드와 하위 호환을 유지한다.

각 제안은 서버 발급 actionId, 허용 kind, label, requirementIds, typed target, 필요 시 graphVersion/asOf를 가진다. 초기 kind는 `open_company`, `focus_relation`, `focus_path`, `open_evidence`, `open_briefing`, `open_watchlist`로 제한한다. 실제 필드·enum은 구현 PR에서 DTO·OpenAPI·클라이언트와 함께 확정한다. Q01 도움말 및 Q05 비교 화면은 실제 지원 route가 확인된 경우만 확장한다.

- 대상 ID가 도구 결과에 존재하고 공개·권한·버전 검사를 통과해야 동작을 만든다. 외부 보도만으로 내부 관계 ID를 만들지 않는다.
- 클릭 시 현재 공개 상태·권한을 다시 확인한다. 삭제·철회·버전 불일치는 ‘현재 열 수 없음’으로 안내하고 다른 간선으로 치환하지 않는다.
- polling·복구·재열람으로 동작을 재실행하지 않는다. 외부 출처는 서버가 검증한 http(s) URL만 사용한다.
- 화면 추적: `D-AI-01/02`, 기업 `D-GRP-03`·`D-COM-01`, 관계 `D-GRP-04`, 근거 `D-GRP-05`, 경로 `D-GRP-07/07b`, 브리핑 `D-BRF-01/02`, 내 종목 `D-GRP-01b`. UI 구현 전 wireframe README·manifest·개별 이미지를 확인한다.

## 6. 계약·저장·검증 변경 경계

범용 용어 사전이나 웹 결과를 정식 evidence로 적재하는 파이프라인을 만들지 않는다. 웹 결과는 권리·보유 기간이 정해진 job 근거 snapshot으로 분리한다. 기존 JSON 저장으로 충분한지 migration이 필요한지는 구현 시 확인한다. 미검토 migration이나 API 변경을 완료로 표기하지 않는다.

동시 변경 대상은 planner capability·실행 봉투, MCP client/server 바인딩, ChatResult·citation/basis·UI action 계약, 감사 기록, 응답 검사·재열람 guard, 생성 명세·클라이언트, 화면·테스트다. 공개 job 접수·polling·resolves 수명주기는 유지한다. 미구현 계약을 OpenAPI 출력에만 먼저 추가하지 않는다.

평가는 [고정 평가 세트의 다음 버전 항목](../development/ai-chatbot-eval-set.md)을 따른다. 독립 Luna coverage-verifier와 보충 라운드는 기존 미구현 과제이며 문서 반영만으로 완료 처리하지 않는다.
