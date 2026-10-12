# FS054 · 사용자와 모의 보유

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 66 |
| 의미 기준 요구사항 | 66 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv:62 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-12/09-데이터-관리.csv:9 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/09-데이터-관리.csv) — 사용자와 모의 보유: 사용자별로 초기 설정, 관심종목, 모의 보유 정보의 현재 상태를 저장해야 한다. 보유 종목·수량·평균 매입가는 고정 Mock 데이터에서 가져오며, 서비스 내 매수·매도나 보유 수량·평균 매입가 변경은 제공하지 않는다. 보유 비중은 동일 기준 시점의 주가로 산출한 종목별 평가금액을 기준으로 서비스에서 계산하며, 계산 기준 시점을 함께 관리한다. Mock 정보 기준 시점과 계산 기준 시점은 구분한다. 정보가 없는 경우와 값이 0인 경우는 구분해야 한다. 주기적 보유 갱신·매매 이력·과거 비교·일별 이력은 요구하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:65 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.4.1 | BE | (BE) 내 관심종목 목록 조회 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.3 | BE | (BE) 모의 보유종목 조회 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.6 | FE | (FE) D-MY-01 내 종목 관리 화면 및 종목·가상계좌 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.8 | 공통/통합 | 내 종목 관리 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-ONB-01](screen-D-ONB-01.md) · [D-WAT-01](screen-D-WAT-01.md) · [D-MY-01](screen-D-MY-01.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getMySettings](../../api/out/zoop-api-spec.md#getmysettings) | GET /api/v1/me/settings | 6.1.2, 6.11.1, 6.3.1, 6.3.4, 6.3.5, 6.3.8, 6.4.1, 6.4.3, 6.4.5, 6.4.6 | 회원(본인) |
| [getMyPortfolio](../../api/out/zoop-api-spec.md#getmyportfolio) | GET /api/v1/portfolio | 6.1.2, 6.11.1, 6.4.1, 6.4.3, 6.4.6, 6.7.8 | 회원(본인) |
