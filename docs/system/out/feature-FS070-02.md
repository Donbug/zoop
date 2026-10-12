# FS070-02 · 미발행 브리핑 회차 재처리

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 미기재 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 82 |
| 의미 기준 요구사항 | 82 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv:83 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-12/11-AI-평가-관리자.csv:163 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-12/11-AI-평가-관리자.csv) — 미발행 브리핑 회차 재처리: 관리자가 지연 또는 실패한 미발행 브리핑 회차의 재처리를 요청하면 허용된 회차만 다시 처리한다. 중복 회차를 만들거나 이미 발행한 본문을 덮어쓰지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:285 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.10.9 | BE | (BE) 브리핑 회차·발행 상태 관리 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.17 | FE | (FE) A-ADM-04·04b 브리핑·AI 사용량 운영 화면 및 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.10.19 | 공통/통합 | 관리자 권한·운영 기능 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[A-ADM-04](screen-A-ADM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [reprocessBriefingRound](../../api/out/zoop-api-spec.md#reprocessbriefinground) | POST /api/v1/admin/briefings/{round_id}/reprocess | 6.1.2, 6.11.1, 6.8.1, 6.8.2, 6.8.8, 6.8.11, 6.8.12, 6.10.9, 6.10.17 | 관리자(작업별 권한) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '미발행 브리핑 회차 재처리' ↔ 요구사항 82 '회차별 생성·검증·발행 상태 조회'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
