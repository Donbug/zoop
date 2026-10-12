# FS050 · 새 대화와 후속 질문

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 50 |
| 의미 기준 요구사항 | 51, 52 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 옛 FS051: 구현 / 옛 FS052-01: 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv:60 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-12/08-AI-챗봇-v2.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/08-AI-챗봇-v2.csv) — 새 대화와 후속 질문: 사용자는 기존 답변에 이어 후속 질문을 하거나, 이전 맥락을 이어받지 않는 새 대화를 시작할 수 있다. 후속 질문은 동일 대화에 새 질문으로 저장되며, 새 대화는 별도 대화 ID로 생성된다.

## 상세 권한과 의미 이행

- 옛 FS051 새 대화 시작에서 이행됨(병합·번호 이동(현 FS051은 다른 의미)). 보존: 새 대화는 별도 ID·빈 맥락, 기존 대화·작업 삭제·취소 아님, 생성 실패 시 기존 대화와 입력 유지.
- 옛 FS052-01 같은 대화에서 후속 질문 전송에서 이행됨(병합·번호 이동). 보존: 후속 질문은 같은 대화의 새 질문 작업, 명시 조건 우선, 늦은 응답은 원래 대화에만 연결.

문서 판정 출처: 옛 FS051 [docs/evidence/spec-v1.2-gap.md:45 (text-line)](../../../docs/evidence/spec-v1.2-gap.md) / 옛 FS052-01 [docs/evidence/spec-v1.2-gap.md:46 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.6 | BE | (BE) 새 대화·후속 질문 | 새 대화·후속 질문은 AI v2 FS050 의미다. 원문 산출물은 10-10까지 옛 FS051(새 대화)+FS052-01(후속 질문)이었고 10-12 공유 시트에서 FS050 하나로 정정됐다. |
| 6.9.11 | FE | (FE) D-AI-01 AI 챗봇 기본 화면 및 세션 API 연동 | 기본 화면·세션 연동은 질문 진입(FS045)과 새 대화·후속 질문(FS050, 옛 FS051)을 소비한다. 원문 산출물의 번호는 옛 체계다. |
| 6.9.14 | FE | (FE) D-AI-02b 대화 이력·후속 질문·답변 재조회 API 연동 | 대화 이력·후속 질문·재조회는 근거 탐색(FS049)·새 대화/후속 질문(FS050)·결과 재조회(FS051)·질문 기록(FS060)을 소비한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | AI v2 FS045~051과 질문 기록, 권한·작업 일관성 공통 의무를 통합 시험 대상으로 연결한다. 원문 종료일이 시작일보다 앞서는 오류는 별도 경고로 보존한다. |

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [M-AI-01](screen-M-AI-01.md) · [D-AI-02b](screen-D-AI-02b.md) · [D-AI-01b](screen-D-AI-01b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [createConversation](../../api/out/zoop-api-spec.md#createconversation) | PUT /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.6, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [getConversation](../../api/out/zoop-api-spec.md#getconversation) | GET /api/v1/chat/sessions/{id} | 6.1.2, 6.11.1, 6.9.6, 6.9.7, 6.9.8, 6.9.10, 6.9.11, 6.9.14 | 회원(본인) |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 | 회원(본인) |

## 확인 필요

- REQUIREMENT_BINDING_BY_MEANING: 명세 '새 대화와 후속 질문' ↔ 원문 요구 번호 50 '답변 근거와 그래프 탐색'. 의미 기준 연결은 요구 ['51', '52']이다(의미 기준 재연결): 현 FS050(새 대화와 후속 질문)은 요구 51(새 대화)과 52의 후속 질문 부분이다. 목차와 상세 메타는 50이며 옛 요구 50(답변 근거)와 다르다.
