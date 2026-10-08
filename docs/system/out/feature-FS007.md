# FS007 · 로그아웃

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 7 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:16 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/01-회원가입-로그인.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/01-회원가입-로그인.csv) — 로그아웃: 사용자는 로그아웃할 수 있어야 한다. 로그아웃이 완료되면 현재 인증 상태를 해제하고 이전 회원의 보유종목, 관심종목, 대화 등 개인화 정보가 화면에 표시되지 않도록 해야 한다. 로그아웃 완료 후에는 이메일 로그인, 소셜 로그인 등 로그인을 다시 수행할 수 있는 로그인 화면으로 이동한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:58 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.2.5 | BE | (BE) 로그아웃 및 세션 무효화 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.2.8 | 공통/통합 | 인증 기능 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-MY-01](screen-D-MY-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [logOut](../../api/out/zoop-api-spec.md#logout) | POST /api/v1/auth/logout | 6.1.2, 6.11.1, 6.2.5 | 공개 |
