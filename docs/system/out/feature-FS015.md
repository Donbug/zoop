# FS015 · 관계 그래프 튜토리얼

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 15 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:25 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv:121 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv) — 관계 그래프 튜토리얼: 사용자는 튜토리얼에서 기본 조작 방법 및 기업·이슈 선택, 관계선 선택, 상세 정보와 근거 확인, AI 질문 방법을 안내받을 수 있어야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:25 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-GRP-T](screen-D-GRP-T.md) · [D-GRP-T2](screen-D-GRP-T2.md) · [D-GRP-T3](screen-D-GRP-T3.md) · [D-GRP-T4](screen-D-GRP-T4.md) · [D-GRP-T5](screen-D-GRP-T5.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [setTutorialState](../../api/out/zoop-api-spec.md#settutorialstate) | PUT /api/v1/auth/tutorial | 6.1.2, 6.10.1, 6.3.8, 6.3.9 | 회원 또는 비회원 세션 |
