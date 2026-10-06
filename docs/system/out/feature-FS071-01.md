# FS071-01 · 발행 브리핑 정정 등록

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

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:88 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:177 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — 발행 브리핑 정정 등록: 관리자가 발행된 브리핑의 오류에 대해 정정을 등록하면 원래 발행 내용과 정정 내용·사유·시점을 구분하여 보존한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:272 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-04](screen-A-ADM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [appendBriefingCorrection](../../api/out/zoop-api-spec.md#appendbriefingcorrection) | POST /api/v1/admin/briefings/{round_id}/corrections | 6.1.2, 6.10.1, 6.7.8, 6.4.4, 6.9.7 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '발행 브리핑 정정 등록' ↔ 요구사항 83 '발행 브리핑 정정 관리'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
