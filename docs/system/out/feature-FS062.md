# FS062 · 가상계좌 데이터 연동

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 74 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:73 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/10-외부-연동.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/10-외부-연동.csv) — 가상계좌 데이터 연동: 프로젝트용 고정 Mock 데이터에서 모의 프로필·계좌 식별자·예수금·보유종목을 조회한다. 각 프로필의 보유 종목·수량·평균 매입가는 변경하지 않으며 매수·매도나 실계좌 연동을 제공하지 않는다. 실제 증권사 비밀번호·인증서 등 자격 증명을 요구하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:61 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-ONB-02](screen-D-ONB-02.md) · [D-MY-01](screen-D-MY-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listVirtualAccountProfiles](../../api/out/zoop-api-spec.md#listvirtualaccountprofiles) | GET /api/v1/portfolio/mock-portfolios | 6.1.2, 6.10.1, 6.3.2, 6.4.9 | 회원(본인) |
| [getVirtualAccountProfile](../../api/out/zoop-api-spec.md#getvirtualaccountprofile) | GET /api/v1/portfolio/mock-portfolios/{id} | 6.1.2, 6.10.1, 6.3.2, 6.4.9 | 회원(본인) |
| [connectVirtualAccount](../../api/out/zoop-api-spec.md#connectvirtualaccount) | POST /api/v1/portfolio/connections | 6.1.2, 6.10.1, 6.3.2, 6.3.3, 6.4.9 | 회원(본인) |
| [disconnectVirtualAccount](../../api/out/zoop-api-spec.md#disconnectvirtualaccount) | DELETE /api/v1/portfolio/connections/{id} | 6.1.2, 6.10.1, 6.3.2, 6.4.9 | 회원(본인) |
