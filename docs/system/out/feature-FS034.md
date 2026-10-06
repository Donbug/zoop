# FS034 · 중복 발행 방지

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 미기재 |
| 요구사항 번호 | 34 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/briefings.py:15 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:44 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv) — 중복 발행 방지: 시스템은 발행일과 출근·퇴근 구분을 기준으로 공통 브리핑의 회차를 식별하고, 같은 회차를 중복 발행하지 않아야 한다. 동일 회차의 생성 요청이 반복되거나 실패 후 재시도하더라도 중복 발행하지 않아야 하며, 이미 발행된 브리핑을 재실행 결과로 임의 교체해서는 안 된다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:204 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md) · [A-ADM-04](screen-A-ADM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | 6.1.2, 6.10.1, 6.7.1, 6.7.2, 6.7.3, 6.7.4, 6.7.6, 6.7.7, 6.7.8, 6.4.4 | 공개 |
| [reprocessBriefingRound](../../api/out/zoop-api-spec.md#reprocessbriefinground) | POST /api/v1/admin/briefings/{round_id}/reprocess | 6.1.2, 6.10.1, 6.7.1, 6.7.2, 6.7.7, 6.9.6 | 관리자(작업별 권한) |
