# FS056 · 사건과 문서 구분

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 68 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:68 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/09-데이터-관리.csv:37 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/09-데이터-관리.csv) — 사건과 문서 구분: 사건과 그 사건을 다룬 뉴스·공시는 따로 관리해야 한다. 하나의 사건에 여러 문서를 연결할 수 있어야 하며, 사건이 일어난 날짜와 기사가 나온 날짜를 구분해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:256 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.5.2 | BE | (BE) 이슈와 근거 문서를 구분 관리 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.5.8 | 공통/통합 | 데이터 관리·외부 연동 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-COM-01b](screen-D-COM-01b.md) · [D-COM-05](screen-D-COM-05.md) · [D-COM-06](screen-D-COM-06.md) · [D-GRP-02](screen-D-GRP-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.6, 6.7.9, 6.5.2, 6.5.6, 6.5.7 | 공개 |
| [listEvents](../../api/out/zoop-api-spec.md#listevents) | GET /api/v1/events | 6.1.2, 6.11.1, 6.7.3, 6.7.4, 6.7.8, 6.7.11, 6.7.12, 6.5.2 | 공개 |
| [getEvent](../../api/out/zoop-api-spec.md#getevent) | GET /api/v1/events/{id} | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.4, 6.7.8, 6.7.12, 6.5.2 | 공개 |
