# FS019 · 그래프 모드 전환

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 19 |
| 의미 기준 요구사항 | 19 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:29 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [이력 정의] [docs/evidence/raw/functional-spec_2026-10-10/03-메인-그래프.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/03-메인-그래프.csv) — 그래프 모드 전환: 사용자는 전체 관계 그래프와 개인화 관계 그래프를 전환할 수 있어야 한다. 시스템은 현재 선택한 모드를 표시해야 한다.
- [docs/evidence/raw/functional-spec_2026-10-10/04-메인그래프-v2.csv:39 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/04-메인그래프-v2.csv) — 그래프 모드 전환: 사용자는 전체 관계 그래프와 개인화 관계 그래프를 전환할 수 있다. 개인화 관계 그래프에서는 별도로 전체 / 보유 / 관심 필터를 사용할 수 있다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:87 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.6.3 | BE | (BE) 그래프 모드 전환 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.21 | FE | (FE) D-GRP-01·01b 전체·개인화 관계 그래프 화면 및 조회 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.27 | 공통/통합 | 메인 그래프 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-COM-04](screen-D-COM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | 6.1.2, 6.11.1, 6.3.6, 6.4.7, 6.6.1, 6.6.2, 6.6.3, 6.6.11, 6.6.21, 6.6.23, 6.7.3, 6.7.7, 6.7.8, 6.7.10, 6.7.11, 6.7.12, 6.8.5, 6.8.14, 6.5.1 | 공개(all) / 회원 본인(personal) |

## 확인 필요

- HISTORICAL_DETAIL_SUPERSEDED: 옛 시트 03-메인-그래프.csv의 정의는 이력으로 보존한다. 현행 상세는 04-메인그래프-v2.csv이며 같은 번호라도 의미가 다를 수 있어 번호 일치로 합치지 않는다.
- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A35:B47와 현행 상세 구획 제목 행 [36]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
