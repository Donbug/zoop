# FS031 · 주요 시장 지표 제공

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 미기재 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 31 |
| 의미 기준 요구사항 | 31 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/web/tests/briefing-market.test.tsx, prototype/bff/src/zoop_bff/routers/briefings.py:15 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:41 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/05-출퇴근-브리핑.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/05-출퇴근-브리핑.csv) — 주요 시장 지표 제공: 시스템은 각 브리핑에 시장이 어떻게 움직였는지 수치로 확인할 수 있도록 KOSPI, KOSDAQ, 원/달러 환율을 제공한다. 핵심 이슈의 영향 설명과 확인할 사항은 별도 영역으로 제공한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:89 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.8.4 | BE | (BE) 주요 시장 지표 제공 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.11 | FE | (FE) D-BRF-01 출근 브리핑 화면 및 브리핑 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.12 | FE | (FE) D-BRF-02 퇴근 브리핑 화면 및 브리핑 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.15 | 공통/통합 | 출퇴근 브리핑 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | 6.1.2, 6.11.1, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.6, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.5.3 | 공개 |

## 확인 필요

- REQUIREMENT_BINDING_BY_MEANING: 명세 '주요 시장 지표 제공' ↔ 원문 요구 번호 31 '시장 변수 제공'. 의미 기준 연결은 요구 ['31']이다(목차명 정합화): 시장 변수 제공→주요 시장 지표 제공. 상세 시트가 이미 가진 의미에 맞춘 이름 변경이다.
