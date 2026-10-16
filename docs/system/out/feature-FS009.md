# FS009 · 가상계좌 프로필 연결

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 보류 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 9 |
| 의미 기준 요구사항 | 9 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv:18 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-12/02-온보딩-튜토리얼.csv:23 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/02-온보딩-튜토리얼.csv) — 가상계좌 프로필 연결: 회원은 서비스에서 미리 준비한 가상계좌 프로필 중 하나를 선택하여 자신의 초기 설정에 연결할 수 있다. 시스템은 해당 데이터가 실제 증권계좌가 아닌 서비스 시연·체험용 모의 데이터임을 명확히 안내한다. 연결이 완료되면 해당 가상계좌의 보유종목을 개인화 그래프 구성에 사용할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:182 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.3.2 | BE | (BE) 가상계좌 프로필 연동 기능 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.3.9 | FE | (FE) D-ONB-02 가상계좌 연결 화면 및 프로필 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.3.11 | 공통/통합 | 온보딩 전체 흐름 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.4 | BE | (BE) 모의계좌 연결 상태·해제 기능 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-ONB-02](screen-D-ONB-02.md) · [D-COM-01](screen-D-COM-01.md) · [D-MY-01](screen-D-MY-01.md) · [M-COM-01](screen-M-COM-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listVirtualAccountProfiles](../../api/out/zoop-api-spec.md#listvirtualaccountprofiles) | GET /api/v1/portfolio/mock-portfolios | 6.1.2, 6.11.1, 6.3.2, 6.3.9, 6.4.4, 6.4.6 | 회원(본인) |
| [getVirtualAccountProfile](../../api/out/zoop-api-spec.md#getvirtualaccountprofile) | GET /api/v1/portfolio/mock-portfolios/{id} | 6.1.2, 6.11.1, 6.3.2, 6.3.9, 6.4.4, 6.4.6 | 회원(본인) |
| [connectVirtualAccount](../../api/out/zoop-api-spec.md#connectvirtualaccount) | POST /api/v1/portfolio/connections | 6.1.2, 6.11.1, 6.3.2, 6.3.9, 6.4.4, 6.4.6 | 회원(본인) |
| [getMyPortfolio](../../api/out/zoop-api-spec.md#getmyportfolio) | GET /api/v1/portfolio | 6.1.2, 6.11.1, 6.3.2, 6.4.1, 6.4.3, 6.4.4, 6.4.6, 6.7.8 | 회원(본인) |
| [disconnectVirtualAccount](../../api/out/zoop-api-spec.md#disconnectvirtualaccount) | DELETE /api/v1/portfolio/connections/{id} | 6.1.2, 6.11.1, 6.3.2, 6.3.9, 6.4.4, 6.4.6 | 회원(본인) |
