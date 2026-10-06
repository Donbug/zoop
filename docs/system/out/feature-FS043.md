# FS043 · 뉴스와 공시 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 43 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:53 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv) — 뉴스와 공시 조회: 시스템은 각 이슈에 연결된 근거 문서의 개수를 표시해야 한다. 사용자가 근거를 선택하면 문서 제목, 출처, 발행 시각, 관련 설명 및 원문 링크를 제공해야 한다. 원문 링크가 없는 경우 ‘원문을 제공하지 않는 자료입니다’라는 안내를 표시해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:94 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-GRP-05](screen-D-GRP-05.md) · [D-AI-01](screen-D-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | 6.1.2, 6.10.1, 6.5.5, 6.6.6, 6.4.3, 6.4.10, 6.4.11 | 공개 |
| [getEvidence](../../api/out/zoop-api-spec.md#getevidence) | GET /api/v1/evidence/{id} | 6.1.2, 6.10.1, 6.5.8, 6.6.6, 6.8.5, 6.4.2 | 공개 |
