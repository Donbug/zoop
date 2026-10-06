# FS050-02 · AI 답변 관련 그래프 탐색

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 50 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:61 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv) — AI 답변 관련 그래프 탐색: 회원이 AI 답변의 관련 기업·이슈·관계를 선택하면 실제 존재하고 조회 권한이 있는 대상을 그래프에서 강조하여 탐색할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:38 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02](screen-D-AI-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.10.1, 6.5.9, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.5, 6.8.6, 6.4.7, 6.4.11 | 회원(본인) |
| [getQuestionJob](../../api/out/zoop-api-spec.md#getquestionjob) | GET /api/v1/chat/jobs/{job_id} | 6.1.2, 6.10.1, 6.8.2, 6.8.5, 6.8.9 | 회원(본인) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 'AI 답변 관련 그래프 탐색' ↔ 요구사항 50 '답변 근거와 그래프 탐색'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
