# FS047 · 질문 해석과 되묻기

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 47 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:57 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv) — 질문 해석과 되묻기: 처음 질문을 받은 시점의 대화 내용·대상·기간·근거를 작업에 고정해야 한다. 최근·작년 같은 날짜 표현은 그 질문 시점의 실제 기간으로 해석해 기록해야 한다. 질문에 명시한 조건을 우선하며 대상이 불명확하면 확인 질문을 저장해 반환해야 한다. 보충 입력은 새 질문 작업으로 처리해야 한다.
- [docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv) — 근거·관계 그래프 맥락 조회: 시스템은 확정된 질문 범위에 맞는 검증 완료 그래프 관계와 뉴스·공시 근거를 조회한다. 개인 보유·관심 종목은 본인 권한이 있을 때만 질문 맥락에 포함한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:34 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.10.1, 6.5.9, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.5, 6.8.6, 6.4.7, 6.4.11 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
