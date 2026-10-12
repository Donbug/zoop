# FS041 · 동일 시점 이슈 구분

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 41 |
| 의미 기준 요구사항 | 41 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-10/06-기업-상세-타임라인.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/06-기업-상세-타임라인.csv) — 동일 시점 이슈 구분: 같은 시간 버킷에 여러 이슈가 있으면 이슈 수를 표시하고, 사용자가 버킷을 선택했을 때 이슈별 카드를 펼쳐 선택할 수 있게 한다. 시간 버킷은 FS040에서 선택한 기간의 해상도를 따른다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:97 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.7.4 | BE | (BE) 동일 시점 이슈 조회 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.8 | FE | (FE) D-COM-01·01b 기업 상세·차트 화면 및 기업·시세 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.12 | FE | (FE) D-COM-05·06 사건 타임라인·차트·그래프 선택 동기화 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |
| 6.7.13 | 공통/통합 | 기업 상세·타임라인 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |

## 화면·목표 API

[D-COM-01b](screen-D-COM-01b.md) · [D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md) · [D-GRP-02](screen-D-GRP-02.md) · [D-COM-04](screen-D-COM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listEvents](../../api/out/zoop-api-spec.md#listevents) | GET /api/v1/events | 6.1.2, 6.11.1, 6.7.3, 6.7.4, 6.7.8, 6.7.11, 6.7.12, 6.5.2, 6.5.1 | 공개 |
| [getEvent](../../api/out/zoop-api-spec.md#getevent) | GET /api/v1/events/{id} | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.4, 6.7.8, 6.7.12, 6.5.2 | 공개 |
| [getCompanyGraphAsOf](../../api/out/zoop-api-spec.md#getcompanygraphasof) | GET /api/v1/companies/{id}/graph | 6.1.2, 6.11.1, 6.7.2, 6.7.3, 6.7.4, 6.7.5, 6.7.8, 6.7.10, 6.7.11, 6.7.12, 6.5.1 | 공개 |

## 확인 필요

- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A49:B61와 현행 상세 구획 제목 행 [63]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
- REQUIREMENT_BINDING_BY_MEANING: 명세 '동일 시점 이슈 구분' ↔ 원문 요구 번호 41 '동일 날짜 사건 구분'. 의미 기준 연결은 요구 ['41']이다(목차명 정합화): 동일 날짜 사건 구분→동일 시점 이슈 구분. 요구 41의 `동일 시점` 서술과 같은 기능이다.
