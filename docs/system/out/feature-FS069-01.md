# FS069-01 · 회원 활동 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P2 · 미기재 |
| 요구사항 번호 | 81 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:84 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:121 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — 회원 활동 조회: 관리자가 승인된 목적·대상·표시 항목 범위에서 선택한 회원의 활동 통계를 조회한다. 통계 조회만으로 회원 상태를 변경하거나 보호된 대화·개인화 결과 원문을 열람하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:268 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-05](screen-A-ADM-05.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listMembers](../../api/out/zoop-api-spec.md#listmembers) | GET /api/v1/admin/members | 6.1.2, 6.10.1, 6.9.5 | 관리자(작업별 권한) |
| [getMemberActivity](../../api/out/zoop-api-spec.md#getmemberactivity) | GET /api/v1/admin/members/{member_id} | 6.1.2, 6.10.1, 6.9.5 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '회원 활동 조회' ↔ 요구사항 81 '회원 관리'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
