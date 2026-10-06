# FS066-02 · AI 기능별 선호도 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P2 · 미기재 |
| 요구사항 번호 | 78 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:78 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — AI 기능별 선호도 조회: 관리자가 AI 답변·뉴스 요약·브리핑별로 현재 유효한 좋아요·싫어요 건수와 좋아요 비율을 조회한다. 결과는 평가에 참여한 회원의 해당 결과 버전별 선호도이며, 전체 이용자의 의견이나 모델의 사실 정확도·성능을 직접 나타내는 수치로 해석하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:44 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-02b](screen-A-ADM-02b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getFeedbackSummary](../../api/out/zoop-api-spec.md#getfeedbacksummary) | GET /api/v1/admin/feedback/summary | 6.1.2, 6.10.1, 6.9.2 | 관리자(작업별 권한) |
| [listDislikedResults](../../api/out/zoop-api-spec.md#listdislikedresults) | GET /api/v1/admin/feedback/dislikes | 6.1.2, 6.10.1, 6.9.2 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 'AI 기능별 선호도 조회' ↔ 요구사항 78 'AI 대화록, 뉴스 요약, 브리핑 등 수집 및 선호도 확인'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
