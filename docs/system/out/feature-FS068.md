# FS068 · AI 사용량·비용·오류 통계

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 미기재 |
| 요구사항 번호 | 80 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:83 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:107 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — AI 사용량·비용·오류 통계: 관리자가 챗봇·뉴스 분석·브리핑별 요청 작업, 실제 AI 호출·재시도, 성공·실패와 처리 시간·사용량을 구분해 운영 현황을 확인한다. 비용을 제공할 경우 실제 확인 비용과 추정 비용을 구분하고 자료가 없는 값을 0으로 대체하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:267 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-04b](screen-A-ADM-04b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getAiUsage](../../api/out/zoop-api-spec.md#getaiusage) | GET /api/v1/admin/ai-usage | 6.1.2, 6.10.1, 6.9.4 | 관리자(작업별 권한) |
