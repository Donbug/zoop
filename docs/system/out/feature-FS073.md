# FS073 · 관리자 로그인(SSO, ID/PW)

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 미기재 |
| 요구사항 번호 | 85 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:91 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:219 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — 관리자 인증 및 접근 제어: 서버에서 유효한 인증과 현재 승인된 관리자 권한을 확인한 계정만 허용된 관리자 화면·조회·변경 기능에 접근한다. 인증 만료 또는 현재 권한 상실이 확인되면 보호 정보와 관리 조치를 차단한다. 실제 지원할 인증 방식·권한 등급은 별도 확정한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:275 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-05c](screen-A-ADM-05c.md) · [A-ADM-01](screen-A-ADM-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getAdminSession](../../api/out/zoop-api-spec.md#getadminsession) | GET /api/v1/admin/auth/session | 6.1.2, 6.10.1, 6.9.9 | 공개 |
| [logInAdmin](../../api/out/zoop-api-spec.md#loginadmin) | POST /api/v1/admin/auth/login | 6.1.2, 6.10.1, 6.9.9 | 공개 |
| [logOutAdmin](../../api/out/zoop-api-spec.md#logoutadmin) | POST /api/v1/admin/auth/logout | 6.1.2, 6.10.1, 6.9.9 | 공개 |
