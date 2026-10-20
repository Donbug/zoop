# FS006 · 로그인 후 화면 이동

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 6 |
| 의미 기준 요구사항 | 6 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:15 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/01-회원가입-로그인.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/01-회원가입-로그인.csv) — 로그인 후 화면 이동: 시스템은 로그인 성공 후 초기 설정 완료 여부를 확인해야 한다. 미완료 사용자는 초기 설정 화면으로, 완료 사용자는 기존 보유종목과 관심종목을 기준으로 메인 화면에 진입시켜야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:174 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.2.4 | BE | (BE) 로그인 상태 및 초기 진입 경로 처리 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.2.6 | FE | (FE) D-AUT-01 로그인 화면 구현 및 인증 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.2.7 | FE | (FE) D-AUT-02 회원가입 화면 구현 및 가입 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.2.8 | 공통/통합 | 인증 기능 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-AUT-01](screen-D-AUT-01.md) · [D-ONB-01](screen-D-ONB-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getMemberSession](../../api/out/zoop-api-spec.md#getmembersession) | GET /api/v1/auth/session | 6.1.2, 6.11.1, 6.2.4, 6.2.6, 6.2.7 | 공개 |
| [logIn](../../api/out/zoop-api-spec.md#login) | POST /api/v1/auth/login | 6.1.2, 6.11.1, 6.2.1, 6.2.4, 6.2.6, 6.2.7 | 공개 |
