# FS043 · 뉴스와 공시 조회

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 43 |
| 의미 기준 요구사항 | 43 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:53 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/06-기업-상세-타임라인.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/06-기업-상세-타임라인.csv) — 뉴스와 공시 조회: 시스템은 각 이슈에 연결된 근거 문서의 개수를 표시해야 한다. 사용자가 근거를 선택하면 문서 제목, 출처, 발행 시각, 관련 설명 및 원문 링크를 제공해야 한다. 원문 링크가 없는 경우 ‘원문을 제공하지 않는 자료입니다’라는 안내를 표시해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:100 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.7.6 | BE | (BE) 뉴스·공시 조회 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.9 | FE | (FE) D-COM-02 기업 문서 탭 및 뉴스·공시 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.7.13 | 공통/통합 | 기업 상세·타임라인 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. FS042 연결은 시점 관계 그래프 의미이며 기존 재무·실적을 이 작업으로 배정하지 않는다. |

## 화면·목표 API

[D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-GRP-05](screen-D-GRP-05.md) · [D-AI-01](screen-D-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.6, 6.7.9, 6.5.2, 6.5.6, 6.5.7 | 공개 |
| [getEvidence](../../api/out/zoop-api-spec.md#getevidence) | GET /api/v1/evidence/{id} | 6.1.2, 6.11.1, 6.6.9, 6.6.22, 6.6.24, 6.6.25, 6.6.26, 6.7.6, 6.7.9, 6.9.5, 6.9.14, 6.5.1 | 공개 |

## 확인 필요

- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A77:B89와 현행 상세 구획 제목 행 [91]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
