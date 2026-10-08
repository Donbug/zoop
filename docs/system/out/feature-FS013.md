# FS013 · 초기 설정 저장

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 미기재 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 13 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/02-온보딩-튜토리얼.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/02-온보딩-튜토리얼.csv) — 초기 설정 저장: 시스템은 회원의 투자 여부, 가상계좌 연결 상태, 관심종목 등 초기 설정 정보를 해당 회원 계정에 저장한다. 저장 실패 시 초기 설정 완료로 처리하지 않고 현재 선택 내용을 유지한 상태에서 다시 시도할 수 있도록 한다. 비회원의 개인 설정은 저장하지 않으며, 개인 설정 기능을 이용하려는 경우 로그인 및 회원 초기 설정 절차로 안내한다. 튜토리얼 완료·건너뛰기 여부는 초기 설정 완료 판정과 별도로 관리한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:187 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.3.1 | BE | (BE) 투자 여부 및 초기 설정 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.3.5 | BE | (BE) 초기 설정 저장 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.3.11 | 공통/통합 | 온보딩 전체 흐름 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-ONB-01](screen-D-ONB-01.md) · [D-WAT-01](screen-D-WAT-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-ONB-02](screen-D-ONB-02.md) · [D-WAT-01b](screen-D-WAT-01b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getMySettings](../../api/out/zoop-api-spec.md#getmysettings) | GET /api/v1/me/settings | 6.1.2, 6.11.1, 6.3.1, 6.3.4, 6.3.5, 6.3.8, 6.4.1, 6.4.3, 6.4.5, 6.4.6 | 회원(본인) |
| [updateMySettings](../../api/out/zoop-api-spec.md#updatemysettings) | PUT /api/v1/me/settings | 6.1.2, 6.11.1, 6.3.1, 6.3.2, 6.3.4, 6.3.5, 6.3.8, 6.3.9, 6.4.5 | 회원(본인) |
