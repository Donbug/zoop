# FS050-01 · AI 답변 근거·원문 확인

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

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:60 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv) — AI 답변 근거·원문 확인: 회원이 AI 답변에서 근거 또는 원문을 선택하면 해당 답변에 연결된 출처·확보된 인용·외부 원문을 확인할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:77 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-05](screen-D-GRP-05.md) · [D-COM-02](screen-D-COM-02.md) · [D-AI-01](screen-D-AI-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-AI-02](screen-D-AI-02.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getEvidence](../../api/out/zoop-api-spec.md#getevidence) | GET /api/v1/evidence/{id} | 6.1.2, 6.10.1, 6.5.8, 6.6.6, 6.8.5, 6.4.2 | 공개 |
| [getQuestionJob](../../api/out/zoop-api-spec.md#getquestionjob) | GET /api/v1/chat/jobs/{job_id} | 6.1.2, 6.10.1, 6.8.2, 6.8.5, 6.8.9 | 회원(본인) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 'AI 답변 근거·원문 확인' ↔ 요구사항 50 '답변 근거와 그래프 탐색'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
