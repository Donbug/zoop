# FS044 · 기업 상세와 관계 그래프 이동·상태 복원

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 44 |
| 의미 기준 요구사항 | 44 |
| API 대응 | 기존 API로 지원 |
| 사유 | 카메라·선택·탭·스크롤 복원은 클라이언트 상태다. 기업/그래프 API가 필요한 조회 조건과 버전을 제공하며 복원 전용 서버 API는 만들지 않는다. |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:54 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-10/06-기업-상세-타임라인.csv:107 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/06-기업-상세-타임라인.csv) — 기업 상세와 관계 그래프 이동·상태 복원: 사용자가 기업 상세와 관계 그래프를 오갈 때 선택 기업, 차트 기간, 기준 시점, 선택 탭, 선택 이슈를 유지한다. 사건에서 그래프로 이동하면 해당 기업·이슈의 실제 영향 경로만 강조한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:101 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.7.7 | BE | (BE) 기업 상세·관계 그래프 이동 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.8 | FE | (FE) D-COM-01·01b 기업 상세·차트 화면 및 기업·시세 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.10 | FE | (FE) D-COM-03 기업 정보 탭 및 기업 기준정보 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.11 | FE | (FE) D-COM-04 기업 중심 관계 그래프 및 시점 조회 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |
| 6.7.12 | FE | (FE) D-COM-05·06 사건 타임라인·차트·그래프 선택 동기화 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |
| 6.7.13 | 공통/통합 | 기업 상세·타임라인 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |

## 화면·목표 API

[D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-COM-04](screen-D-COM-04.md) · [D-GRP-03](screen-D-GRP-03.md) · [D-COM-01](screen-D-COM-01.md) · [M-COM-01](screen-M-COM-01.md) · [D-COM-03](screen-D-COM-03.md) · [M-COM-02](screen-M-COM-02.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | 6.1.2, 6.11.1, 6.3.6, 6.4.7, 6.6.1, 6.6.2, 6.6.3, 6.6.11, 6.6.21, 6.6.23, 6.7.3, 6.7.7, 6.7.8, 6.7.10, 6.7.11, 6.7.12, 6.8.5, 6.8.14, 6.5.1 | 공개(all) / 회원 본인(personal) |
| [getCompany](../../api/out/zoop-api-spec.md#getcompany) | GET /api/v1/companies/{id} | 6.1.2, 6.11.1, 6.6.4, 6.6.23, 6.6.26, 6.7.2, 6.7.7, 6.7.8, 6.7.10, 6.7.11, 6.7.12 | 공개 |

## 확인 필요

- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A91:B103와 현행 상세 구획 제목 행 [105]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
- REQUIREMENT_TITLE_REVIEW: 명세 '기업 상세와 관계 그래프 이동·상태 복원' ↔ 요구사항 44 '상세 화면 상태와 이동'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
