# FS052-02 · AI 내부 패널 닫기·재열기와 대화 유지

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 52 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:64 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv:135 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv) — AI 내부 패널 닫기·재열기와 대화 유지: 회원이 상세페이지의 AI 내부 패널을 닫아도 상세 상태·대화 기록·서버 작업을 유지한다. 새 대화로 바꾸지 않았다면 다시 열 때 같은 대화의 상태와 완료 결과를 회수한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:41 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-02b](screen-D-AI-02b.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getConversation](../../api/out/zoop-api-spec.md#getconversation) | GET /api/v1/chat/sessions/{id} | 6.1.2, 6.10.1, 6.8.6, 6.8.8, 6.4.7 | 회원(본인) |
| [getCurrentConversation](../../api/out/zoop-api-spec.md#getcurrentconversation) | GET /api/v1/chat/sessions/current | 6.1.2, 6.10.1, 6.8.8, 6.4.7 | 회원(본인) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 'AI 내부 패널 닫기·재열기와 대화 유지' ↔ 요구사항 52 '대화와 내부 패널 유지'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
