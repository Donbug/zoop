---
title: Map detail panel completion
status: approved
created: 2026-10-24
owner: frontend
tags: [web, map, prototype-gaps]
---

# 지도 상세 패널 보강

## Context & problem

프로토타입 미구현 목록 24~31의 계약상 제공되는 정보를 D-GRP-02/03/04/05에 표시한다. 새 화면 구성이나 데이터 추론 없이 기존 상세 패널을 보강한다.

## Goals / non-goals

- **Goals:** 사건 순서, 승인 맥락, 독립 출처 수, 기업 이동, 관계 기준 문서, 저장된 문서 분석의 출처와 한계를 제공한다.
- **Non-goals:** 튜토리얼, 새 API/분석 실행, G6 배치·카메라·색상 변경.
- 사용자 결정: 작업 C 중 열린 #312와 겹치는 지도 통합은 #312 병합 뒤 후속 작업한다. MapPage/GraphCanvas/포커스/모바일 도구와 공용 스타일 가이드는 수정하지 않는다.

## Requirements

2026-10-24 공통 지시 수정 반영: 프로토타입의 구조·문구·상태·접근성을 출발점으로 옮기고 데이터/API, 스타일, 지도 엔진, 상태/경로만 main 방식으로 치환한다. 새로 설계하지 않는다. PR에는 파일 대응표와 계약 차이를 기록한다.

- **FR-001 (27):** getEvent.follows.previous/next로 앞선·이어진 사건을 구분하고 발생 시각 정밀도를 보존한다. 프로토타입과 같이 지도 노드 존재를 확인할 수 없으면 이동 동작을 만들지 않는다. 지도 선택 연결은 #312 병합 후 통합한다.
- **FR-002 (26,28):** getEvent.approval은 null일 때 표시하지 않는다. sourceSupport의 null을 0으로 바꾸지 않고 부분 실패를 빈 데이터로 표시하지 않는다.
- **FR-003 (29):** getEvent.companies의 직접·구조적 관련 구분을 유지하며 기업 상세로 이동할 수 있다.
- **FR-004 (30):** getCompanyRelation(요청서의 getGraphEdge)의 역할·보도 표현·검증·basis.sourceUrl을 표시한다. 링크는 http(s)만 허용하고 새 창을 알린다. 파생 관계에 실제 보도 판정을 만들지 않는다.
- **FR-005 (31):** getEvidence가 반환한 문서 분석만 표시한다. 문서·결과 버전과 제공 상태를 확인하고 해석/한계/인용/생성 출처를 구분한다. article:null이면 분석도 숨긴다. 실제 자료에 authored-test replay 분석을 노출하지 않는다.
- **FR-006 (25):** 사건 판정은 합성하지 않는다. listCompanyDocuments의 해당 사건·기업에 일치하는 문서 판정만 문서별로 표시한다.
- **FR-007:** 새 요청 중 이전 응답은 노출하지 않고 기존 조회·권한·재시도·모달 포커스 동작을 유지한다.

## User scenarios

### 사건과 근거 확인 (P1)

- **Given** 공개 지도에서 사건을 선택했을 때
- **When** 상세 및 근거 창을 열면
- **Then** 해당 스냅샷의 사건 순서와 제공된 분석만 읽으며, 미확인 출처 수·제공 불가 문서를 확인 완료 자료처럼 표현하지 않는다.

## Success criteria

- **SC-001:** 새 동작은 HTTP fakeServer 기반 회귀로 검사하고 요청한 tsc/lint/format/build/전체 Vitest 명령을 통과한다.
- **SC-002:** #312 및 다른 열린 PR과 겹치는 파일 수정이 없고 프로토타입 runtime import·새 의존성이 없다.

## Open questions / deferred

- 24의 기업 패널에 앞선·이어진 사건을 합친 간접 이슈는 getCompany 응답에 없다. 실제 지도 FOLLOWS 결합이 필요하므로 #312 병합 후 MapPage 데이터 전달과 함께 구현한다.
- 29의 사건 패널은 기존 직접/구조적 관련 묶음을 유지하고 기업 상세 링크를 추가한다. 지도 내 선택은 MapPage의 노드 목록·선택 콜백 전달이 필요하므로 #312 병합 후 통합한다.
- 15~18, 21의 지도 사건 수·기본 열림·선택 기억, 22~23은 #312 병합 뒤 통합한다. 19 및 21의 독립 컴포넌트는 별도 화면 묶음 PR로 작업한다.
- sourceSupport/approval/analysis의 서버 생산자가 값을 제공하지 않는 경우 UI가 값을 만들어 채우지 않는다.

## References

- docs/wireframe/README.md, manifest.json, boards/03-map-relationships-evidence.jpg 및 D-GRP-02/03/04/05 개별 화면
- docs/design/design-direction.md §4.3, §4.6, §5.4~5.5
- docs/api/openapi.yaml: getEvent, getCompanyRelation, getEvidence, getCompany, listCompanyDocuments
- prototype/web/src/features/node-panel.tsx 및 components/domain/{approval-note,company-summary,document-analysis,evidence,relation-list}.tsx

## Future expansion

#312 병합 후 지도 화면·사이드바·경로를 별도 PR로 통합한다.

## Prototype → main mapping

| 프로토타입 원본                                                | main 소유 경로                                            | 치환·계약 차이                                                                                                                                                                                  |
| -------------------------------------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| features/node-panel.tsx의 IssueDetailView                      | EventDetailPanel.tsx, EventLinkedDetails.tsx              | 기존 useEventData/getEvent를 사용. FOLLOWS 순서·시각 문구 유지. MapPage 연결이 필요한 지도 내 선택은 보류하고 기업 상세 링크만 제공                                                             |
| components/domain/approval-note.tsx                            | graph/ApprovalNote.tsx                                    | 승인 유무·관리자/규칙 분기와 문구 유지. 아이콘은 기존 GraphIcon, 설명은 native PanelDisclosure로 치환                                                                                           |
| components/domain/company-summary.tsx의 CompanyIssueSentiments | graph/IssueDocumentSentiments.tsx, CompanyDetailPanel.tsx | 기존 documents 응답에 있는 해당 사건·기업 문서 판정만 표시. 사건 판정 합산 없음                                                                                                                 |
| components/domain/status-labels.tsx의 SentimentLabel           | graph/DocumentSentiment.tsx, PanelDisclosure.tsx          | 판정·원문 인용·시각·모델·프롬프트 순서 유지. Radix 대신 native details와 Escape/바깥 클릭/초점 복귀 사용                                                                                        |
| features/node-panel.tsx의 EdgeDetailView                       | RelationDetailPanel.tsx                                   | 보도 표현·역할·검증·기준 문서 링크를 기존 useRelationData와 getCompanyRelation 필드로 연결                                                                                                      |
| components/domain/document-analysis.tsx, evidence.tsx          | evidence/EvidenceAnalysis.tsx, EvidenceDrawer.tsx         | 판정→요약 claims→미제공 상태 구조와 문구, 요약 출처 안내 유지. 문서·분석 버전 검사 추가. EvidenceArticle.synthetic 필드가 계약에 없어 authored replay는 명시된 로컬 MOCK 이외에는 표시하지 않음 |

재사용 가능한 설명 조각은 현재 지도 상세 범위에서만 사용한다. 공용 스타일 가이드가 #312/#313과 겹치므로 이번 PR에서는 변경하지 않는다. Radix의 떠 있는 포털 배치는 native 펼침 영역으로 치환했고, 조작·닫기·초점 복귀는 유지한다. 새 의존성 및 prototype runtime import는 없다.
