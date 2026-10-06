# FS054 · 사용자와 모의 보유

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 66 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:66 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/09-데이터-관리.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/09-데이터-관리.csv) — 사용자와 모의 보유: 사용자별로 초기 설정, 관심종목, 모의 보유 정보의 현재 상태를 저장해야 한다. 보유 종목·수량·평균 매입가는 고정 Mock 데이터에서 가져오며, 서비스 내 매수·매도나 보유 수량·평균 매입가 변경은 제공하지 않는다. 보유 비중은 동일 기준 시점의 주가로 산출한 종목별 평가금액을 기준으로 서비스에서 계산하며, 계산 기준 시점을 함께 관리한다. Mock 정보 기준 시점과 계산 기준 시점은 구분한다. 정보가 없는 경우와 값이 0인 경우는 구분해야 한다. 주기적 보유 갱신·매매 이력·과거 비교·일별 이력은 요구하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:59 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-ONB-01](screen-D-ONB-01.md) · [D-WAT-01](screen-D-WAT-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getMySettings](../../api/out/zoop-api-spec.md#getmysettings) | GET /api/v1/me/settings | 6.1.2, 6.10.1, 6.3.1, 6.3.5, 6.3.6, 6.4.1 | 회원(본인) |
| [getMyPortfolio](../../api/out/zoop-api-spec.md#getmyportfolio) | GET /api/v1/portfolio | 6.1.2, 6.10.1, 6.6.2, 6.4.1 | 회원(본인) |
