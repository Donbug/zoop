# FS021 · 이슈 노드 정보

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 21 |
| API 대응 | 기존 API로 지원 |
| 사유 | D-SEN-01은 디자인시스템의 판정 예시이며 실제 모델 호출이나 데모 판정값이 아니다. 문서×기업의 nullable 판정은 기존 문서/근거 API 계약으로 연결하고 예시 전용 API는 만들지 않는다. |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/market.py:66 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:31 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/03-메인-그래프.csv) — 이슈 노드 정보: 시스템은 이슈의 내용과 관련 기업을 이해할 수 있도록 이슈 정보 패널을 제공한다. 기업별 긍정·부정·혼재 등의 영향 해석과 불확실성을 근거와 함께 설명. 이를 주가 상승·하락 확률로 표현해서는 안 된다.
- [docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv:67 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/04-메인그래프-v2.csv) — 이슈 노드 정보: 사용자가 이슈 노드를 선택하면 이슈의 제목, 핵심 내용, 국내 / 국제 속성, 관련 기업, 뉴스 요약, 관련도가 높은 뉴스 및 근거 자료를 정보 패널에서 확인할 수 있다. 기업별 영향은 근거와 불확실성을 함께 표시한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:87 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-COM-02](screen-D-COM-02.md) · [M-COM-01](screen-M-COM-01.md) · [D-SEN-01](screen-D-SEN-01.md) · [D-GRP-02](screen-D-GRP-02.md) · [D-COM-05](screen-D-COM-05.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listCompanyDocuments](../../api/out/zoop-api-spec.md#listcompanydocuments) | GET /api/v1/companies/{id}/documents | 6.1.2, 6.10.1, 6.5.5, 6.6.6, 6.4.3, 6.4.10, 6.4.11 | 공개 |
| [getEvent](../../api/out/zoop-api-spec.md#getevent) | GET /api/v1/events/{id} | 6.1.2, 6.10.1, 6.5.5, 6.6.4, 6.4.3 | 공개 |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
