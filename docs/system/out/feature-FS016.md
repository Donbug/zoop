# FS016 · 튜토리얼 완료와 건너뛰기

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 미기재 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 16 |
| 의미 기준 요구사항 | 16 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:26 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/02-온보딩-튜토리얼.csv:135 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/02-온보딩-튜토리얼.csv) — 튜토리얼 완료와 건너뛰기: 사용자는 튜토리얼을 끝까지 완료하거나 진행 중 건너뛰어 메인 그래프로 이동할 수 있다. API는 `completed` boolean 하나로 결과를 저장한다. `true`는 완료, `false`는 미완료를 뜻하며 중간 건너뛰기도 `false`로 처리한다. 회원의 `tutorialCompleted`는 계정에 저장하고 비회원의 값은 게스트 세션에만 보관한다. 일반 진입 시 값이 `true`이면 자동 노출하지 않고, `false`이면 튜토리얼을 표시한다. 회원과 비회원 모두 메인 그래프에서 다시 보기를 실행할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:190 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.3.7 | BE | (BE) 그래프 튜토리얼 및 완료 상태 처리 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.3.10 | FE | (FE) D-GRP-T2~T5 관계 그래프 튜토리얼 및 완료 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.3.11 | 공통/통합 | 온보딩 전체 흐름 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-GRP-T](screen-D-GRP-T.md) · [D-GRP-T2](screen-D-GRP-T2.md) · [D-GRP-T3](screen-D-GRP-T3.md) · [D-GRP-T4](screen-D-GRP-T4.md) · [D-GRP-T5](screen-D-GRP-T5.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [setTutorialState](../../api/out/zoop-api-spec.md#settutorialstate) | PUT /api/v1/auth/tutorial | 6.1.2, 6.11.1, 6.3.7, 6.3.10 | 회원 |
