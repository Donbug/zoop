# FS002 · 이메일 로그인

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 2 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:11 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv) — 이메일 로그인: 사용자가 이메일과 비밀번호를 입력하여 로그인한다. 인증에 성공하면 초기 설정 완료 여부에 따라 초기 설정 화면 또는 메인 화면으로 이동한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:51 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AUT-01](screen-D-AUT-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [logIn](../../api/out/zoop-api-spec.md#login) | POST /api/v1/auth/login | 6.1.2, 6.10.1, 6.2.2, 6.2.6 | 공개 |
