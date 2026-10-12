# FS021 · 이슈 노드 정보

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 21 |
| 의미 기준 요구사항 | 21 |
| API 대응 | 기존 API로 지원 |
| 사유 | D-SEN-01은 디자인시스템의 판정 예시이며 실제 모델 호출이나 데모 판정값이 아니다. 문서×기업의 nullable 판정은 기존 문서/근거 API 계약으로 연결하고 예시 전용 API는 만들지 않는다. |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv:31 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv)

- [이력 정의] [docs/evidence/raw/functional-spec_2026-10-12/03-메인-그래프.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/03-메인-그래프.csv) — 이슈 노드 정보: 시스템은 이슈의 내용과 관련 기업을 이해할 수 있도록 이슈 정보 패널을 제공한다. 기업별 긍정·부정·혼재 등의 영향 해석과 불확실성을 근거와 함께 설명. 이를 주가 상승·하락 확률로 표현해서는 안 된다.
- [docs/evidence/raw/functional-spec_2026-10-12/04-메인그래프-v2.csv:67 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/04-메인그래프-v2.csv) — 이슈 노드 정보: 사용자가 이슈 노드를 선택하면 이슈의 제목, 핵심 내용, 국내 / 국제 속성, 관련 기업, 뉴스 요약, 관련도가 높은 뉴스 및 근거 자료를 정보 패널에서 확인할 수 있다. 기업별 영향은 근거와 불확실성을 함께 표시한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:93 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.6.5 | BE | (BE) 이슈 노드 정보 API 구현 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.22 | FE | (FE) D-GRP-02 이슈 노드 상세 패널 및 이슈 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.6.27 | 공통/통합 | 메인 그래프 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-GRP-02](screen-D-GRP-02.md) · [D-COM-05](screen-D-COM-05.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.6, 6.7.9, 6.5.2, 6.5.6, 6.5.7 | 공개 |
| [getEvent](../../api/out/zoop-api-spec.md#getevent) | GET /api/v1/events/{id} | 6.1.2, 6.11.1, 6.6.5, 6.6.22, 6.7.4, 6.7.8, 6.7.12, 6.5.2 | 공개 |

## 확인 필요

- HISTORICAL_DETAIL_SUPERSEDED: 옛 시트 03-메인-그래프.csv의 정의는 이력으로 보존한다. 현행 상세는 04-메인그래프-v2.csv이며 같은 번호라도 의미가 다를 수 있어 번호 일치로 합치지 않는다.
- INDEX_DETAIL_RANGE_STALE: 목차 상세 위치 A63:B75와 현행 상세 구획 제목 행 [64]이 다르다. 원문 값을 보존하며 자동 정정하지 않는다.
