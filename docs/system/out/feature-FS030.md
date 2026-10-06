# FS030 · 핵심 이슈 선정 및 제공

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 30 |
| API 대응 | 기존 API로 지원 |
| 사유 | D-SEN-02는 디자인시스템의 회차 판단 예시다. 데모 발행본에는 outlook 값이 없으며 기존 브리핑 API가 발행 시 고정할 판단과 근거 이슈를 제공하는 목표 계약이다. |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/briefings.py:15 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:40 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv) — 핵심 이슈 선정 및 제공: 시스템은 각 브리핑에 핵심 이슈를 최대 3개 제공한다. 정해진 선정 기준에 따라 이슈 제목, 요약, 중요하게 선정한 이유와 관련 기업을 표시해야 한다. 선정 기준을 충족하는 이슈가 부족하면 개수를 억지로 채우지 않아야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:200 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | 6.1.2, 6.10.1, 6.7.1, 6.7.2, 6.7.3, 6.7.4, 6.7.6, 6.7.7, 6.7.8, 6.4.4 | 공개 |
