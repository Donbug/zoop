# FS033 · 공통 브리핑 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P2 · 확정 |
| 요구사항 번호 | 33 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/briefings.py:15 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:43 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv) — 공통 브리핑 조회: 사용자는 날짜와 출근·퇴근 구분을 선택하여 해당 회차의 공통 시장 브리핑을 조회할 수 있어야 한다. 같은 회차를 조회한 사용자에게는 동일하게 발행된 시장 요약, 주요 지표, 핵심 이슈, 관련 기업 및 주요 변수를 제공해야 한다. 화면에는 발행일, 출근·퇴근 구분과 데이터 기준 시점을 표시해야 한다. 해당 회차가 아직 준비되지 않았거나 생성에 실패한 경우에는 그 상태를 안내해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:84 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | 6.1.2, 6.10.1, 6.7.1, 6.7.2, 6.7.3, 6.7.4, 6.7.6, 6.7.7, 6.7.8, 6.4.4 | 공개 |
| [listBriefingRounds](../../api/out/zoop-api-spec.md#listbriefingrounds) | GET /api/v1/briefings/rounds | 6.1.2, 6.10.1, 6.7.6, 6.7.8, 6.4.4 | 공개 |
