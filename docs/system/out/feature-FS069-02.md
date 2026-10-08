# FS069-02 · 회원 차단·차단 해제

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P2 · 미기재 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 81 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:85 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/11-AI-평가-관리자.csv:135 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/11-AI-평가-관리자.csv) — 회원 차단·차단 해제: 관리자가 특정 회원의 차단 또는 차단 해제를 요청하면 시스템은 관리자 권한과 대상 회원을 확인하여 허용된 관리 조치를 적용한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:283 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.10.3 | BE | (BE) 회원 활동 조회·차단 관리 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.18 | FE | (FE) A-ADM-05·05b 회원·감사 로그 화면 및 관리 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.19 | 공통/통합 | 관리자 권한·운영 기능 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[A-ADM-05](screen-A-ADM-05.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [blockMember](../../api/out/zoop-api-spec.md#blockmember) | POST /api/v1/admin/members/{member_id}/block | 6.1.2, 6.11.1, 6.10.3, 6.10.18 | 관리자(작업별 권한) |
| [unblockMember](../../api/out/zoop-api-spec.md#unblockmember) | POST /api/v1/admin/members/{member_id}/unblock | 6.1.2, 6.11.1, 6.10.3, 6.10.18 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '회원 차단·차단 해제' ↔ 요구사항 81 '회원 관리'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
