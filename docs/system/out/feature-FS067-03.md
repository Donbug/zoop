# FS067-03 · 실패한 이슈 분석·반영 작업 재시도

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 미기재 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 79 |
| 의미 기준 요구사항 | 79 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:78 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/11-AI-평가-관리자.csv:93 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/11-AI-평가-관리자.csv) — 실패한 이슈 분석·반영 작업 재시도: 관리자가 실패한 이슈 분석·저장·공개 반영 작업의 재시도를 요청하면 현재 상태·실패 단계·재시도 허용 여부를 확인하고 허용된 실패 단계만 복구한다. 상태 조회나 중복 요청을 새 분석·공개 실행으로 처리하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:69 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.10.7 | BE | (BE) 보류 이슈 검수·분석 재처리 기능 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.16 | FE | (FE) A-ADM-03 그래프 파이프라인·검수 화면 및 재처리 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.19 | 공통/통합 | 관리자 권한·운영 기능 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[A-ADM-03](screen-A-ADM-03.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [retryAnalysisJob](../../api/out/zoop-api-spec.md#retryanalysisjob) | POST /api/v1/admin/jobs/{job_id}/retry | 6.1.2, 6.11.1, 6.10.7, 6.10.16 | 관리자(작업별 권한) |
| [cancelAnalysisJob](../../api/out/zoop-api-spec.md#cancelanalysisjob) | POST /api/v1/admin/jobs/{job_id}/cancel | 6.1.2, 6.11.1, 6.10.7, 6.10.16 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '실패한 이슈 분석·반영 작업 재시도' ↔ 요구사항 79 'AI 기반 이슈 판단의 진행 상태, 이슈 각각의 통과/보류/폐기 상태 등 확인 및 보류된 이슈의 검수 후 허용/거부 선택'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
