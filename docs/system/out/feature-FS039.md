# FS039 · 가상 보유 정보 표시

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 39 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:49 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/06-기업-상세-타임라인.csv) — 가상 보유 정보 표시: 가상 계좌를 연결한 로그인 회원에게만 선택 기업의 모의 보유 수량, 평균 매입가, 평가 금액, 자산 비중을 제공한다. 이는 실제 계좌 정보가 아닌 프로젝트용 모의 데이터임을 표시한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:57 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-COM-01](screen-D-COM-01.md) · [D-MY-01](screen-D-MY-01.md) · [M-COM-01](screen-M-COM-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getMyPortfolio](../../api/out/zoop-api-spec.md#getmyportfolio) | GET /api/v1/portfolio | 6.1.2, 6.10.1, 6.6.2, 6.4.1 | 회원(본인) |
