# FS047 · 질문 해석과 되묻기

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 47 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:57 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv) — 질문 해석과 되묻기: 처음 질문을 받은 시점의 대화 내용·대상·기간·근거를 작업에 고정해야 한다. 최근·작년 같은 날짜 표현은 그 질문 시점의 실제 기간으로 해석해 기록해야 한다. 질문에 명시한 조건을 우선하며 대상이 불명확하면 확인 질문을 저장해 반환해야 한다. 보충 입력은 새 질문 작업으로 처리해야 한다.
- [docs/evidence/raw/functional-spec_2026-10-08/08-AI-챗봇-v2.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/08-AI-챗봇-v2.csv) — 근거·관계 그래프 맥락 조회: 시스템은 확정된 질문 범위에 맞는 검증 완료 그래프 관계와 뉴스·공시 근거를 조회한다. 개인 보유·관심 종목은 본인 권한이 있을 때만 질문 맥락에 포함한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:40 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.2 | BE | (BE) 질문 대상·기간 해석·되묻기 | 질문 대상·기간 해석/되묻기는 현재 FS047 의미다. 옛 업무의 FS046 번호를 그대로 옮기지 않는다. |
| 6.9.12 | FE | (FE) D-AI-01b 기업·이슈·간선 선택 맥락 질문 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
