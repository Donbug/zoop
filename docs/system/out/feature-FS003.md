# FS003 · 이메일 회원가입

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 3 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:12 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv) — 이메일 회원가입: 사용자가 가입 정보를 입력하고 필수 약관에 동의하여 계정을 생성한다. 필수 입력, 입력 형식, 필수 약관 동의, 이메일 중복 여부를 회원가입 기능 내부에서 검증한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:157 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AUT-02](screen-D-AUT-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listTerms](../../api/out/zoop-api-spec.md#listterms) | GET /api/v1/auth/terms | 6.1.2, 6.10.1, 6.2.3 | 공개 |
| [signUp](../../api/out/zoop-api-spec.md#signup) | POST /api/v1/auth/signup | 6.1.2, 6.10.1, 6.2.3 | 공개 |
