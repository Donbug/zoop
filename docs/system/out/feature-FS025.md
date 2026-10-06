# FS025 · 선택한 노드로 AI 질문

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 25 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:35 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv:121 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv) — 선택한 노드로 AI 질문: 시스템은 그래프에서 선택한 노드에서 AI 질문을 선택하면 선택 대상, 적용 기간 및 근거 자료 정보를 질문에 연결하고, 사용자가 연결된 대상을 확인한 뒤 질문을 보낼 수 있어야 한다.  관계 탐색, 자료 요약 및 허용된 개인화 질문에 공통 챗봇 규칙을 적용해야 한다. 개인화 정보는 사용자의 조회 권한 범위에서만 활용해야 한다.
- [docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv:125 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv) — 선택한 노드로 AI 질문: 시스템은 그래프에서 선택한 노드에서 AI 질문을 선택하면 선택 대상, 적용 기간 및 근거 자료 정보를 질문에 연결하고, 사용자가 연결된 대상을 확인한 뒤 질문을 보낼 수 있어야 한다.  관계 탐색, 자료 요약 및 허용된 개인화 질문에 공통 챗봇 규칙을 적용해야 한다. 개인화 정보는 사용자의 조회 권한 범위에서만 활용해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:190 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.10.1, 6.5.9, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.5, 6.8.6, 6.4.7, 6.4.11 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
