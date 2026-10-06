# FS010 · 가상계좌 연결 재시도와 건너뛰기

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 10 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:19 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv) — 가상계좌 연결 재시도와 건너뛰기: 회원은 가상계좌 연결을 건너뛰고 관심종목을 선택할 수 있어야 한다. 연결 실패 시에는 실패 안내와 함께 다시 시도하거나 관심종목 선택으로 진행할 수 있어야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:169 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-ONB-01](screen-D-ONB-01.md) · [D-ONB-02](screen-D-ONB-02.md) · [D-WAT-01](screen-D-WAT-01.md) · [D-WAT-01b](screen-D-WAT-01b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [updateMySettings](../../api/out/zoop-api-spec.md#updatemysettings) | PUT /api/v1/me/settings | 6.1.2, 6.10.1, 6.3.1, 6.3.3, 6.3.5, 6.3.6 | 회원(본인) |
| [connectVirtualAccount](../../api/out/zoop-api-spec.md#connectvirtualaccount) | POST /api/v1/portfolio/connections | 6.1.2, 6.10.1, 6.3.2, 6.3.3, 6.4.9 | 회원(본인) |
