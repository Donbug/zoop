# FS071-02 · 발행 브리핑 제공 중단

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 미기재 |
| 요구사항 번호 | 83 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:89 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:191 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — 발행 브리핑 제공 중단: 관리자가 발행된 브리핑의 제공 중단을 요청하면 해당 회차의 중단 상태를 사용자 조회에 반영하고 기존 발행 이력을 보존한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:273 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-04](screen-A-ADM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [setBriefingSuspension](../../api/out/zoop-api-spec.md#setbriefingsuspension) | POST /api/v1/admin/briefings/{round_id}/suspension | 6.1.2, 6.10.1, 6.9.7 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '발행 브리핑 제공 중단' ↔ 요구사항 83 '발행 브리핑 정정 관리'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
