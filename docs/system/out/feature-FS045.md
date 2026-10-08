# FS045 · AI 질문 진입과 전송

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 45 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:55 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv) — AI 질문 진입과 전송: 전역 AI 질문창 또는 그래프·기업 상세에서 전달받은 기업·이슈·관계·문서를 기준으로 질문할 수 있어야 한다. 전달받은 선택 대상·기간·근거를 질문에 포함하고 대화 및 질문 작업과 연결해야 한다. 빈 입력과 같은 대화에서 작업 처리 중인 추가 전송은 제한해야 한다. 비회원은 질문 자체를 제한한다.
- [docs/evidence/raw/functional-spec_2026-10-08/08-AI-챗봇-v2.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/08-AI-챗봇-v2.csv) — AI 질문 진입과 맥락 전달: 시스템은 전역 AI 패널과 기업·이슈·관계 패널의 AI에게 질문하기에서 질문을 시작할 수 있게 한다. 선택한 기업, 이슈, 관계, 기준 시점, 근거 문서는 질문 맥락으로 함께 전달한다. 전역 질문은 선택 맥락 없이도 시작할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:81 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.1 | BE | (BE) AI 질문 진입·맥락 전달 | 질문 진입·맥락 접수 시 FS046의 회원 권한·대화별 중복 작업 통제를 함께 적용한다. 원문 FS025/FS045와 편집 연결을 구분한다. |
| 6.9.11 | FE | (FE) D-AI-01 AI 챗봇 기본 화면 및 세션 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.12 | FE | (FE) D-AI-01b 기업·이슈·간선 선택 맥락 질문 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
