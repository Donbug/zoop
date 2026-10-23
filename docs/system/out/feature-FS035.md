# FS035 · 브리핑 회차 저장 및 이력 보존

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · FS035: 미기재<br>FS057: 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 35, 69 |
| 의미 기준 요구사항 | 35, 69 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/README.md, prototype/bff/src/zoop_bff/routers/briefings.py:15 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:45 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/05-출퇴근-브리핑.csv:107 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/05-출퇴근-브리핑.csv) — 브리핑 회차 저장 및 이력 보존: 시스템은 출근·퇴근 브리핑의 회차별 내용·시간 정보·사용 이슈와 근거를 저장한다. 발행 이후 새 뉴스나 시장 데이터가 수집되어도 과거 발행 내용과 근거 참조를 자동으로 덮어쓰지 않고 보존한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:91 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.5.3 | BE | (BE) 브리핑 정보 저장(분석 결과와 생성 재료 제공) | 브리핑 재료/회차 저장 업무를 현 FS035로 연결한다. 원문 FS057은 새 번호를 추정 정정하지 않고 rawSpecIds에 남긴다. |
| 6.5.8 | 공통/통합 | 데이터 관리·외부 연동 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.8 | BE | (BE) 브리핑 이력 보존(회차·발행본·스냅샷 저장 및 조회) | 회차·발행본 보존과 중복 발행 방지의 저장 계약을 연결한다. 중복 발행 방지 업무 자체는 10-12 원문부터 6.8.7에 있으며 이 연결은 저장 계약 소비 관계로 유지한다. |
| 6.8.11 | FE | (FE) D-BRF-01 출근 브리핑 화면 및 브리핑 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.12 | FE | (FE) D-BRF-02 퇴근 브리핑 화면 및 브리핑 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.13 | FE | (FE) D-BRF-04 브리핑 회차·이력 화면 및 조회 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.15 | 공통/통합 | 출퇴근 브리핑 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md) · [D-BRF-04](screen-D-BRF-04.md) · [A-ADM-04](screen-A-ADM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | 6.1.2, 6.11.1, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 | 공개 |
| [listBriefingRounds](../../api/out/zoop-api-spec.md#listbriefingrounds) | GET /api/v1/briefings/rounds | 6.1.2, 6.11.1, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 | 공개 |
| [getBriefingRecap](../../api/out/zoop-api-spec.md#getbriefingrecap) | GET /api/v1/briefings/{id}/recap | 6.1.2, 6.11.1 | 공개 |
| [getBriefingItemDetail](../../api/out/zoop-api-spec.md#getbriefingitemdetail) | GET /api/v1/briefings/{roundId}/items/{eventId} | 6.1.2, 6.11.1, 6.8.3, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 | 공개 |
| [getBriefingGraphBasis](../../api/out/zoop-api-spec.md#getbriefinggraphbasis) | GET /api/v1/briefings/{id}/graph | 6.1.2, 6.11.1, 6.8.5, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.8.14, 6.5.3 | 공개 |
| [appendBriefingCorrection](../../api/out/zoop-api-spec.md#appendbriefingcorrection) | POST /api/v1/admin/briefings/{round_id}/corrections | 6.1.2, 6.11.1, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.10.10, 6.10.17, 6.5.3 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '브리핑 회차 저장 및 이력 보존' ↔ 요구사항 35 '브리핑 이력 보존'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
- REQUIREMENT_TITLE_REVIEW: 명세 '브리핑 회차 저장 및 이력 보존' ↔ 요구사항 69 '브리핑 정보 저장'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
