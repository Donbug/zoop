# FS070-01 · 브리핑 회차별 생성·검증·발행 상태 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 미기재 |
| 요구사항 번호 | 82 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:86 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:149 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — 브리핑 회차별 생성·검증·발행 상태 조회: 관리자가 출근·퇴근 브리핑의 회차·결과 버전별 데이터 기준 시점, 생성·검증·저장·실제 발행 상태 및 실패 사유를 구분해 확인한다. 상태 조회는 재처리나 발행을 수행하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:270 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-04](screen-A-ADM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listAdminBriefingRounds](../../api/out/zoop-api-spec.md#listadminbriefingrounds) | GET /api/v1/admin/briefings | 6.1.2, 6.10.1, 6.9.6 | 관리자(작업별 권한) |
| [getAdminBriefingRound](../../api/out/zoop-api-spec.md#getadminbriefinground) | GET /api/v1/admin/briefings/{round_id} | 6.1.2, 6.10.1, 6.9.6 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '브리핑 회차별 생성·검증·발행 상태 조회' ↔ 요구사항 82 '회차별 생성·검증·발행 상태 조회'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
