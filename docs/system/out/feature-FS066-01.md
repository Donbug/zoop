# FS066-01 · AI 답변·뉴스 요약·브리핑 평가 등록

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | FS037: 미기재 / FS066: P2 · FS037: 미기재 / FS066: 미기재 |
| 요구사항 번호 | 37, 78 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:77 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — AI 답변·뉴스 요약·브리핑 평가 등록: 로그인 회원이 제공받은 AI 답변·뉴스 요약·브리핑 결과에 좋아요 또는 싫어요를 등록·변경·취소한다. 평가를 결과 종류와 해당 결과 버전에 연결한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:43 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-BRF-01](screen-D-BRF-01.md) · [D-COM-02](screen-D-COM-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getMyFeedback](../../api/out/zoop-api-spec.md#getmyfeedback) | GET /api/v1/feedback | 6.1.2, 6.10.1, 6.7.10, 6.9.2 | 회원(본인) |
| [setFeedback](../../api/out/zoop-api-spec.md#setfeedback) | PUT /api/v1/feedback | 6.1.2, 6.10.1, 6.7.10, 6.9.2 | 회원(본인) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 'AI 답변·뉴스 요약·브리핑 평가 등록' ↔ 요구사항 37 '좋아요/싫어요 만족도 조사'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
- REQUIREMENT_TITLE_REVIEW: 명세 'AI 답변·뉴스 요약·브리핑 평가 등록' ↔ 요구사항 78 'AI 대화록, 뉴스 요약, 브리핑 등 수집 및 선호도 확인'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
