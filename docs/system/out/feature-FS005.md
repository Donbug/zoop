# FS005 · 비회원 시작

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 5 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/auth.py:29 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:14 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/01-회원가입-로그인.csv) — 비회원 시작: 사용자가 회원가입과 로그인 없이 서비스를 시작한다. 개인 설정 절차를 거치지 않고 메인 그래프에 진입하며, 회원과 동일한 메인 그래프 튜토리얼을 제공받는다. 로그인 전에는 계좌 연결·관심종목 설정·AI 질문을 이용할 수 없다. 비회원의 튜토리얼 진행·완료·건너뛰기 상태는 저장하지 않으며, 메인 그래프에서 튜토리얼 다시 보기 기능을 통해 언제든 튜토리얼을 다시 실행할 수 있다

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:159 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AUT-01](screen-D-AUT-01.md) · [M-GRP-01](screen-M-GRP-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [startGuestSession](../../api/out/zoop-api-spec.md#startguestsession) | POST /api/v1/auth/guest | 6.1.2, 6.10.1, 6.2.5 | 공개 |
