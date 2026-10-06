# FS045 · AI 질문 진입과 전송

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 45 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:55 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv) — AI 질문 진입과 전송: 전역 AI 질문창 또는 그래프·기업 상세에서 전달받은 기업·이슈·관계·문서를 기준으로 질문할 수 있어야 한다. 전달받은 선택 대상·기간·근거를 질문에 포함하고 대화 및 질문 작업과 연결해야 한다. 빈 입력과 같은 대화에서 작업 처리 중인 추가 전송은 제한해야 한다. 비회원은 질문 자체를 제한한다.
- [docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv) — AI 질문 진입과 맥락 전달: 시스템은 전역 AI 패널과 기업·이슈·관계 패널의 AI에게 질문하기에서 질문을 시작할 수 있게 한다. 선택한 기업, 이슈, 관계, 기준 시점, 근거 문서는 질문 맥락으로 함께 전달한다. 전역 질문은 선택 맥락 없이도 시작할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:75 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.10.1, 6.5.9, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.5, 6.8.6, 6.4.7, 6.4.11 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
