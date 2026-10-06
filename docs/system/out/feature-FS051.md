# FS051 · 새 대화 시작

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 51 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:62 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv:107 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv) — 새 대화 시작: 사용자가 이전 대화와 독립된 주제로 질문할 수 있도록 ‘새 대화’ 기능을 제공해야 한다. 새 대화를 시작하면 별도의 대화 ID를 부여하고 이전 대화의 질문·답변 및 선택 조건을 자동으로 이어받지 않아야 한다. 기존 대화 기록은 유지하며, 이전 대화에서 처리 중이던 답변이 새 대화 화면에 표시되지 않아야 한다.
- [docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv:94 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv) — AI 패널 상태 유지와 결과 재조회: 사용자가 AI 패널을 닫았다가 다시 열거나 네트워크 응답을 받지 못해도, 기존 질문 작업의 상태와 저장된 결과를 재조회할 수 있다. 패널 닫기·재열기는 질문 취소나 새 AI 생성으로 처리하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:39 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [createConversation](../../api/out/zoop-api-spec.md#createconversation) | PUT /api/v1/chat/sessions/{id} | 6.1.2, 6.10.1, 6.8.6, 6.8.7, 6.4.7 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
