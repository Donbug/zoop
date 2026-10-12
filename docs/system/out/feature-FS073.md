# FS073 · 관리자 인증 및 접근 제어

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 미기재 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 85 |
| 의미 기준 요구사항 | 85 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:87 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-10/11-AI-평가-관리자.csv:219 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/11-AI-평가-관리자.csv) — 관리자 인증 및 접근 제어: 서버에서 유효한 인증과 현재 승인된 관리자 권한을 확인한 계정만 허용된 관리자 화면·조회·변경 기능에 접근한다. 인증 만료 또는 현재 권한 상실이 확인되면 보호 정보와 관리 조치를 차단한다. 실제 지원할 인증 방식·권한 등급은 별도 확정한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:289 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.10.1 | BE | (BE) 관리자 인증·권한 관리 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.13 | FE | (FE) A-ADM-05c 관리자 로그인·권한 화면 및 인증 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.19 | 공통/통합 | 관리자 권한·운영 기능 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[A-ADM-05c](screen-A-ADM-05c.md) · [A-ADM-01](screen-A-ADM-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getAdminSession](../../api/out/zoop-api-spec.md#getadminsession) | GET /api/v1/admin/auth/session | 6.1.2, 6.11.1, 6.10.1, 6.10.13 | 공개 |
| [logInAdmin](../../api/out/zoop-api-spec.md#loginadmin) | POST /api/v1/admin/auth/login | 6.1.2, 6.11.1, 6.10.1, 6.10.13 | 공개 |
| [logOutAdmin](../../api/out/zoop-api-spec.md#logoutadmin) | POST /api/v1/admin/auth/logout | 6.1.2, 6.11.1, 6.10.1, 6.10.13 | 공개 |

## 확인 필요

- REQUIREMENT_BINDING_BY_MEANING: 명세 '관리자 인증 및 접근 제어' ↔ 원문 요구 번호 85 '관리자 로그인(SSO, ID/PW)'. 의미 기준 연결은 요구 ['85']이다(목차명 정합화): 관리자 로그인(SSO, ID/PW)→관리자 인증 및 접근 제어. 요구 85를 유지한다.
