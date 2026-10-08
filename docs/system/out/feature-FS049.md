# FS049 · 답변 검증과 제공

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 49 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:59 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv) — 답변 검증과 제공: AI 답변의 형식, 인용이 가리키는 문서·원문 구간, 답변에 포함된 그래프 대상의 유효성을 확인해야 한다. 현재 유효한 실행의 검증된 결과를 저장한 후 답변을 제공해야 한다. 실제 적용 기업·이슈·기간을 표시하고 검증 실패 시 답변을 자동으로 다시 생성하지 않아야 한다.
- [docs/evidence/raw/functional-spec_2026-10-08/08-AI-챗봇-v2.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/08-AI-챗봇-v2.csv) — 답변 근거와 관련 그래프 탐색: 사용자는 답변의 근거 문서 또는 관련 기업·이슈·관계를 선택해 출처를 확인하거나 해당 대상을 그래프에서 강조해 탐색할 수 있다. AI 답변 자체는 새 관계를 생성하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:42 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.4 | BE | (BE) 근거 기반 답변 생성·안전 검증 | 근거 기반 답변 생성·안전 검증은 현재 FS049 답변 검증/제공 의미와 대응한다. |
| 6.9.13 | FE | (FE) D-AI-02 AI 비동기 작업 상태·결과·재시도 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02](screen-D-AI-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 | 회원(본인) |
| [getQuestionJob](../../api/out/zoop-api-spec.md#getquestionjob) | GET /api/v1/chat/jobs/{job_id} | 6.1.2, 6.11.1, 6.9.4, 6.9.5, 6.9.7, 6.9.9, 6.9.13, 6.9.14 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
