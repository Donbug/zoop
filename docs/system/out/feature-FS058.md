# FS058 · 신규 경제뉴스 정기 수집 및 이슈 분석

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 70 |
| 의미 기준 요구사항 | 70 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-10/09-데이터-관리.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/09-데이터-관리.csv) — 신규 경제뉴스 정기 수집 및 이슈 분석: 분석시스템은 한국 시간 매시 05분과 35분에 신규 경제뉴스 수집을 시작한다. 공급원의 등록·수정 정보 등으로 신규·지연 등록·수정 문서를 확인하고 동일 내용의 중복을 제외한다. 발견 가능한 범위는 실제 공급원의 지원과 검증된 조회 방식에 따른다. 뉴스·공시 같은 문서에서 개별 사건을 추출하고 관련 이슈에 연결하거나 신규 이슈를 만든 뒤 기업·영향 경로·근거를 분석한다. 이슈는 관련 사건을 연결해 관리하는 분석 주제이며 사건 하나부터 구성할 수 있다. 핵심 이슈는 이슈 중 중요하게 선정해 보여 주는 대상이며 별도의 사건 유형이 아니다. 자동 검증을 통과한 결과만 공개 대상으로 지정한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:66 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.5.4 | BE | (BE) 신규 경제뉴스 정기 수집 및 이슈 분석 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.5.8 | 공통/통합 | 데이터 관리·외부 연동 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getPipelineOverview](../../api/out/zoop-api-spec.md#getpipelineoverview) | GET /api/v1/admin/pipeline/overview | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4, 6.5.5, 6.5.6 | 관리자(작업별 권한) |
| [listAnalysisJobs](../../api/out/zoop-api-spec.md#listanalysisjobs) | GET /api/v1/admin/jobs | 6.1.2, 6.11.1, 6.10.6, 6.10.16, 6.5.4 | 관리자(작업별 권한) |
| [createAnalysisJob](../../api/out/zoop-api-spec.md#createanalysisjob) | POST /api/v1/admin/jobs | 6.1.2, 6.11.1, 6.5.4, 6.5.5, 6.5.6, 6.5.7 | 관리자(작업별 권한) |
