# FS035 · 브리핑 회차 저장 및 이력 보존

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · FS035: 미기재<br>FS057: 팀 검토 전 |
| 요구사항 번호 | 35, 69 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/README.md, prototype/bff/src/zoop_bff/routers/briefings.py:15 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:45 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv:107 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/05-출퇴근-브리핑.csv) — 브리핑 회차 저장 및 이력 보존: 시스템은 출근·퇴근 브리핑의 회차별 내용·시간 정보·사용 이슈와 근거를 저장한다. 발행 이후 새 뉴스나 시장 데이터가 수집되어도 과거 발행 내용과 근거 참조를 자동으로 덮어쓰지 않고 보존한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:85 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md) · [D-SEN-02](screen-D-SEN-02.md) · [D-BRF-04](screen-D-BRF-04.md) · [A-ADM-04](screen-A-ADM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getBriefing](../../api/out/zoop-api-spec.md#getbriefing) | GET /api/v1/briefings | 6.1.2, 6.10.1, 6.7.1, 6.7.2, 6.7.3, 6.7.4, 6.7.6, 6.7.7, 6.7.8, 6.4.4 | 공개 |
| [listBriefingRounds](../../api/out/zoop-api-spec.md#listbriefingrounds) | GET /api/v1/briefings/rounds | 6.1.2, 6.10.1, 6.7.6, 6.7.8, 6.4.4 | 공개 |
| [getBriefingGraphBasis](../../api/out/zoop-api-spec.md#getbriefinggraphbasis) | GET /api/v1/briefings/{id}/graph | 6.1.2, 6.10.1, 6.7.5, 6.7.8, 6.4.4 | 공개 |
| [appendBriefingCorrection](../../api/out/zoop-api-spec.md#appendbriefingcorrection) | POST /api/v1/admin/briefings/{round_id}/corrections | 6.1.2, 6.10.1, 6.7.8, 6.4.4, 6.9.7 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '브리핑 회차 저장 및 이력 보존' ↔ 요구사항 35 '브리핑 이력 보존'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
- REQUIREMENT_TITLE_REVIEW: 명세 '브리핑 회차 저장 및 이력 보존' ↔ 요구사항 69 '브리핑 정보 저장'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
