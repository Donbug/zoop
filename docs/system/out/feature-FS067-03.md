# FS067-03 · 실패한 이슈 분석·반영 작업 재시도

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 미기재 |
| 요구사항 번호 | 79 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:82 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — 실패한 이슈 분석·반영 작업 재시도: 관리자가 실패한 이슈 분석·저장·공개 반영 작업의 재시도를 요청하면 현재 상태·실패 단계·재시도 허용 여부를 확인하고 허용된 실패 단계만 복구한다. 상태 조회나 중복 요청을 새 분석·공개 실행으로 처리하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:63 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [retryAnalysisJob](../../api/out/zoop-api-spec.md#retryanalysisjob) | POST /api/v1/admin/jobs/{job_id}/retry | 6.1.2, 6.10.1, 6.9.3 | 관리자(작업별 권한) |
| [cancelAnalysisJob](../../api/out/zoop-api-spec.md#cancelanalysisjob) | POST /api/v1/admin/jobs/{job_id}/cancel | 6.1.2, 6.10.1, 6.9.3 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '실패한 이슈 분석·반영 작업 재시도' ↔ 요구사항 79 'AI 기반 이슈 판단의 진행 상태, 이슈 각각의 통과/보류/폐기 상태 등 확인 및 보류된 이슈의 검수 후 허용/거부 선택'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
