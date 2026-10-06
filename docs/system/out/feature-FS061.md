# FS061 · 소셜 인증 연동

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 73 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:72 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/10-외부-연동.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/10-외부-연동.csv) — 소셜 인증 연동: 시스템은 소셜 인증 결과를 서버에서 검증한 뒤 가입 또는 로그인을 처리한다. 이미 연결된 소셜 계정은 연결된 회원으로 로그인한다. 처음 연결하는 계정은 사용 가능한 이메일로 기존 회원을 확인하고, 같은 이메일의 회원이 있으면 기존 서비스 계정의 본인 여부와 연결 권한을 확인한 뒤 연결하고 없으면 가입한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:251 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AUT-01](screen-D-AUT-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listSocialProviders](../../api/out/zoop-api-spec.md#listsocialproviders) | GET /api/v1/auth/social/providers | 6.1.2, 6.10.1, 6.2.4, 6.4.8 | 공개 |
| [authorizeSocialLogin](../../api/out/zoop-api-spec.md#authorizesociallogin) | GET /api/v1/auth/social/{provider}/authorize | 6.1.2, 6.10.1, 6.2.4, 6.4.8 | 공개 |
| [completeSocialLogin](../../api/out/zoop-api-spec.md#completesociallogin) | GET /api/v1/auth/social/{provider}/callback | 6.1.2, 6.10.1, 6.2.4, 6.4.8 | 공개 |
