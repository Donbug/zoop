# FS004 · 소셜 로그인과 회원가입

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 4 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:13 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv) — 소셜 로그인과 회원가입: 이미 연동된 소셜 계정이면 해당 회원 계정으로 로그인한다. 처음 이용하는 소셜 계정인 경우 소셜 제공자로부터 수집한 이메일을 기준으로 기존 회원 계정을 확인한다. 동일한 이메일로 가입된 기존 계정이 존재하면 신규 계정을 생성하지 않고 해당 기존 계정에 소셜 계정 정보를 추가하여 연동한 후 로그인한다. 동일 이메일의 기존 계정이 없으면 새로운 회원 계정을 생성하고 소셜 계정을 연결한다. 서로 다른 이메일을 사용하는 경우 동일 사용자라 하더라도 별도 계정으로 가입할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:158 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AUT-01](screen-D-AUT-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listSocialProviders](../../api/out/zoop-api-spec.md#listsocialproviders) | GET /api/v1/auth/social/providers | 6.1.2, 6.10.1, 6.2.4, 6.4.8 | 공개 |
| [authorizeSocialLogin](../../api/out/zoop-api-spec.md#authorizesociallogin) | GET /api/v1/auth/social/{provider}/authorize | 6.1.2, 6.10.1, 6.2.4, 6.4.8 | 공개 |
| [completeSocialLogin](../../api/out/zoop-api-spec.md#completesociallogin) | GET /api/v1/auth/social/{provider}/callback | 6.1.2, 6.10.1, 6.2.4, 6.4.8 | 공개 |
