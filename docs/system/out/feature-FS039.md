# FS039 · 가상 보유 정보 표시

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 39 |
| 의미 기준 요구사항 | 39 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:49 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-10/06-기업-상세-타임라인.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/06-기업-상세-타임라인.csv) — 가상 보유 정보 표시: 가상 계좌를 연결한 로그인 회원에게만 선택 기업의 모의 보유 수량, 평균 매입가, 평가 금액, 자산 비중을 제공한다. 이는 실제 계좌 정보가 아닌 프로젝트용 모의 데이터임을 표시한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:63 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.4.3 | BE | (BE) 모의 보유종목 조회 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.6 | FE | (FE) D-MY-01 내 종목 관리 화면 및 종목·가상계좌 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.8 | 공통/통합 | 내 종목 관리 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.8 | FE | (FE) D-COM-01·01b 기업 상세·차트 화면 및 기업·시세 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.13 | 공통/통합 | 기업 상세·타임라인 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |

## 화면·목표 API

[D-COM-01](screen-D-COM-01.md) · [D-MY-01](screen-D-MY-01.md) · [M-COM-01](screen-M-COM-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getMyPortfolio](../../api/out/zoop-api-spec.md#getmyportfolio) | GET /api/v1/portfolio | 6.1.2, 6.11.1, 6.4.1, 6.4.3, 6.4.6, 6.7.8 | 회원(본인) |

## 확인 필요

- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A21:B33와 현행 상세 구획 제목 행 [35]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
