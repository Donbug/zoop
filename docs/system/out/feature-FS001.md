# FS001 · 서비스 시작 방식 선택

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 1 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:10 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv) — 서비스 시작 방식 선택: 사용자가 서비스 시작 화면에서 이메일 로그인, 이메일 회원가입, 소셜 로그인, 비회원 시작 중 원하는 이용 방식을 선택한다. 선택한 방식에 해당하는 화면 또는 절차로 연결한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:50 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AUT-01](screen-D-AUT-01.md) · [D-ONB-01](screen-D-ONB-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getMemberSession](../../api/out/zoop-api-spec.md#getmembersession) | GET /api/v1/auth/session | 6.1.2, 6.10.1, 6.2.1, 6.2.6 | 공개 |
