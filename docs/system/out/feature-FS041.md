# FS041 · 동일 날짜 사건 구분

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 41 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv) — 동일 시점 이슈 구분: 같은 시간 버킷에 여러 이슈가 있으면 이슈 수를 표시하고, 사용자가 버킷을 선택했을 때 이슈별 카드를 펼쳐 선택할 수 있게 한다. 시간 버킷은 FS040에서 선택한 기간의 해상도를 따른다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:91 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-COM-01b](screen-D-COM-01b.md) · [D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md) · [D-GRP-02](screen-D-GRP-02.md) · [D-COM-04](screen-D-COM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listEvents](../../api/out/zoop-api-spec.md#listevents) | GET /api/v1/events | 6.1.2, 6.10.1, 6.6.3, 6.6.4, 6.4.3 | 공개 |
| [getEvent](../../api/out/zoop-api-spec.md#getevent) | GET /api/v1/events/{id} | 6.1.2, 6.10.1, 6.5.5, 6.6.4, 6.4.3 | 공개 |
| [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | 6.1.2, 6.6.3, 6.6.4, 6.4.2, 6.10.1 | 공개 |
