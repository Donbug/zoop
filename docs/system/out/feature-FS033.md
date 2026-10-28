# FS033 · 공통 브리핑 조회

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P2 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 33 |
| 의미 기준 요구사항 | 33 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/briefings.py:15 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:43 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/05-출퇴근-브리핑.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/05-출퇴근-브리핑.csv) — 공통 브리핑 조회: 사용자는 날짜와 출근·퇴근 구분을 선택하여 해당 회차의 공통 시장 브리핑을 조회할 수 있어야 한다. 같은 회차를 조회한 사용자에게는 동일하게 발행된 시장 요약, 주요 지표, 핵심 이슈, 관련 기업 및 주요 변수를 제공해야 한다. 화면에는 발행일, 출근·퇴근 구분과 데이터 기준 시점을 표시해야 한다. 해당 회차가 아직 준비되지 않았거나 생성에 실패한 경우에는 그 상태를 안내해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:90 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.8.6 | BE | (BE) 공통 브리핑 조회 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.11 | FE | (FE) D-BRF-01 출근 브리핑 화면 및 브리핑 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.12 | FE | (FE) D-BRF-02 퇴근 브리핑 화면 및 브리핑 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.13 | FE | (FE) D-BRF-04 브리핑 회차·이력 화면 및 조회 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.15 | 공통/통합 | 출퇴근 브리핑 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | 6.1.2, 6.11.1, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 | 공개 |
| [listBriefingRounds](../../api/out/zoop-api-spec.md#listbriefingrounds) | GET /api/v1/briefings/rounds | 6.1.2, 6.11.1, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 | 공개 |
| [getBriefingRecap](../../api/out/zoop-api-spec.md#getbriefingrecap) | GET /api/v1/briefings/{id}/recap | 6.1.2, 6.11.1 | 공개 |
| [getBriefingItemImpacts](../../api/out/zoop-api-spec.md#getbriefingitemimpacts) | GET /api/v1/briefings/{roundId}/items/{eventId}/impacts | 6.1.2, 6.11.1 | 공개 |
| [getBriefingItemImpactReviews](../../api/out/zoop-api-spec.md#getbriefingitemimpactreviews) | GET /api/v1/briefings/{roundId}/items/{eventId}/impact-reviews | 6.1.2, 6.11.1 | 공개 |
| [getBriefingItemDetail](../../api/out/zoop-api-spec.md#getbriefingitemdetail) | GET /api/v1/briefings/{roundId}/items/{eventId} | 6.1.2, 6.11.1, 6.8.3, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 | 공개 |
