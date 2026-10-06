# FS007 · 로그아웃

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 7 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:16 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv) — 로그아웃: 사용자는 로그아웃할 수 있어야 한다. 로그아웃이 완료되면 현재 인증 상태를 해제하고 이전 회원의 보유종목, 관심종목, 대화 등 개인화 정보가 화면에 표시되지 않도록 해야 한다. 로그아웃 완료 후에는 이메일 로그인, 소셜 로그인 등 로그인을 다시 수행할 수 있는 로그인 화면으로 이동한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:52 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-MY-01](screen-D-MY-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [logOut](../../api/out/zoop-api-spec.md#logout) | POST /api/v1/auth/logout | 6.1.2, 6.10.1, 6.2.7 | 공개 |
