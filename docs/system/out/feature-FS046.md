# FS046 · AI 권한과 중복 작업 통제

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 46 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:56 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv) — AI 권한과 중복 작업 통제: 서버는 로그인·접근 권한, 대화 소유자, 근거 문서 접근 권한과 같은 작업의 질문 내용 일치 여부를 확인해야 한다. 처리 중인 질문 작업을 중복 실행하지 않고, 완료한 작업은 현재 권한을 확인해 저장된 결과를 반환해야 한다. 동시에 요청되어도 유효한 실행 하나만 처리해야 한다.
- [docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv) — 질문 대상·기간 해석 및 되묻기: 시스템은 질문과 전달된 맥락에서 분석 대상·기간을 해석한다. 대상 또는 기간을 하나로 정할 수 없으면 임의로 분석하지 않고 확인 질문을 제공한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:33 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02](screen-D-AI-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.10.1, 6.5.9, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.5, 6.8.6, 6.4.7, 6.4.11 | 회원(본인) |
| [getQuestionJob](../../api/out/zoop-api-spec.md#getquestionjob) | GET /api/v1/chat/jobs/{job_id} | 6.1.2, 6.10.1, 6.8.2, 6.8.5, 6.8.9 | 회원(본인) |
| [cancelQuestionJob](../../api/out/zoop-api-spec.md#cancelquestionjob) | POST /api/v1/chat/jobs/{job_id}/cancel | 6.1.2, 6.10.1, 6.8.2, 6.8.9 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
