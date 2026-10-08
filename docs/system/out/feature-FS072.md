# FS072 · 대시보드

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 미기재 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 84 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:90 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/11-AI-평가-관리자.csv:205 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/11-AI-평가-관리자.csv) — 대시보드: 관리자는 대시보드를 통해 시스템의 전체 상황, 통계 등에 대한 요약을 확인할 수 있어야 하며, 각 관리 기능에 빠르게 접근할 수 있어야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:288 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.10.2 | BE | (BE) 관리자 대시보드 통합 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.12 | BE | (BE) 관리자 주요 작업 감사기록 저장·조회 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.14 | FE | (FE) A-ADM-01 운영 대시보드 및 통합 현황 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.19 | 공통/통합 | 관리자 권한·운영 기능 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[A-ADM-01](screen-A-ADM-01.md) · [A-ADM-05b](screen-A-ADM-05b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getAdminDashboard](../../api/out/zoop-api-spec.md#getadmindashboard) | GET /api/v1/admin/dashboard | 6.1.2, 6.11.1, 6.10.2, 6.10.14 | 관리자(작업별 권한) |
| [listAuditRecords](../../api/out/zoop-api-spec.md#listauditrecords) | GET /api/v1/admin/audit-log | 6.1.2, 6.11.1, 6.10.12, 6.10.18 | 관리자(작업별 권한) |
