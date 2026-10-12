# FS027 · 관심 종목 수정

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 27 |
| 의미 기준 요구사항 | 27 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [이력 정의] [docs/evidence/raw/functional-spec_2026-10-10/03-메인-그래프.csv:149 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/03-메인-그래프.csv) — 관심 종목 수정: 사용자는 사이드바 또는 기업 노드를 클릭하여 관심 종목을 선택 및 해제할 수 있다.
- [docs/evidence/raw/functional-spec_2026-10-10/04-메인그래프-v2.csv:154 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/04-메인그래프-v2.csv) — 관심 종목 수정: 사용자는 사이드바 또는 기업 노드를 클릭하여 관심 종목을 선택 및 해제할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:33 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.4.1 | BE | (BE) 내 관심종목 목록 조회 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.2 | BE | (BE) 관심종목 추가·삭제 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.6 | FE | (FE) D-MY-01 내 종목 관리 화면 및 종목·가상계좌 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.7 | FE | (FE) D-STK-01 종목 검색·사이드바 및 관심종목 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.8 | 공통/통합 | 내 종목 관리 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.12 | BE | (BE) 관심 종목 수정 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.23 | FE | (FE) D-GRP-03 기업 노드 상세 패널 및 기업 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.27 | 공통/통합 | 메인 그래프 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-MY-01](screen-D-MY-01.md) · [D-GRP-03](screen-D-GRP-03.md) · [D-STK-01](screen-D-STK-01.md) · [M-STK-01](screen-M-STK-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [setWatchlistCompany](../../api/out/zoop-api-spec.md#setwatchlistcompany) | PUT /api/v1/me/watchlist/{id} | 6.1.2, 6.11.1, 6.4.1, 6.4.2, 6.4.6, 6.4.7, 6.6.12, 6.6.23 | 회원(본인) |

## 확인 필요

- HISTORICAL_DETAIL_SUPERSEDED: 옛 시트 03-메인-그래프.csv의 정의는 이력으로 보존한다. 현행 상세는 04-메인그래프-v2.csv이며 같은 번호라도 의미가 다를 수 있어 번호 일치로 합치지 않는다.
- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A147:B159와 현행 상세 구획 제목 행 [152]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
