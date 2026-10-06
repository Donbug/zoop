# FS028 · 출근 브리핑 생성

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 28 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/briefings.py:15 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:38 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv) — 출근 브리핑 생성: 시스템은 매일 07:40에 출근 브리핑을 자동 생성한다. 직전 퇴근 브리핑의 데이터 기준 시점 이후부터 이번 회차의 데이터 마감 시점까지 확보한 미국 증시·국제정세·국내 주요 뉴스를 바탕으로 시장 요약, 핵심 이슈, 관련 기업과 주요 시장 변수를 제공.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:198 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md) · [A-ADM-04](screen-A-ADM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | 6.1.2, 6.10.1, 6.7.1, 6.7.2, 6.7.3, 6.7.4, 6.7.6, 6.7.7, 6.7.8, 6.4.4 | 공개 |
| [reprocessBriefingRound](../../api/out/zoop-api-spec.md#reprocessbriefinground) | POST /api/v1/admin/briefings/{round_id}/reprocess | 6.1.2, 6.10.1, 6.7.1, 6.7.2, 6.7.7, 6.9.6 | 관리자(작업별 권한) |
