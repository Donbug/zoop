# FS009 · 가상계좌 프로필 연결

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 보류 |
| 요구사항 번호 | 9 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:18 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv) — 가상계좌 프로필 연결: 회원은 서비스에서 미리 준비한 가상계좌 프로필 중 하나를 선택하여 자신의 초기 설정에 연결할 수 있다. 시스템은 해당 데이터가 실제 증권계좌가 아닌 서비스 시연·체험용 모의 데이터임을 명확히 안내한다. 연결이 완료되면 해당 가상계좌의 보유종목을 개인화 그래프 구성에 사용할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:168 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-ONB-02](screen-D-ONB-02.md) · [D-MY-01](screen-D-MY-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listVirtualAccountProfiles](../../api/out/zoop-api-spec.md#listvirtualaccountprofiles) | GET /api/v1/portfolio/mock-portfolios | 6.1.2, 6.10.1, 6.3.2, 6.4.9 | 회원(본인) |
| [getVirtualAccountProfile](../../api/out/zoop-api-spec.md#getvirtualaccountprofile) | GET /api/v1/portfolio/mock-portfolios/{id} | 6.1.2, 6.10.1, 6.3.2, 6.4.9 | 회원(본인) |
| [connectVirtualAccount](../../api/out/zoop-api-spec.md#connectvirtualaccount) | POST /api/v1/portfolio/connections | 6.1.2, 6.10.1, 6.3.2, 6.3.3, 6.4.9 | 회원(본인) |
| [disconnectVirtualAccount](../../api/out/zoop-api-spec.md#disconnectvirtualaccount) | DELETE /api/v1/portfolio/connections/{id} | 6.1.2, 6.10.1, 6.3.2, 6.4.9 | 회원(본인) |
