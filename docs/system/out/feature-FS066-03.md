# FS066-03 · 마스킹된 AI 대화록 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P2 · 미기재 |
| 요구사항 번호 | 78 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 충돌 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/app.py:88 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:79 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/11-AI-평가-관리자.csv) — 마스킹된 AI 대화록 조회: 별도 대화록 열람 권한을 가진 관리자가 허용된 목적·대상 범위 안에서 개인정보를 마스킹한 AI 대화록을 확인한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:263 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[A-ADM-02b](screen-A-ADM-02b.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listMaskedTranscripts](../../api/out/zoop-api-spec.md#listmaskedtranscripts) | GET /api/v1/admin/transcripts | 6.1.2, 6.10.1, 6.9.2 | 관리자 + transcript:read + 열람 목적 |
| [getMaskedTranscript](../../api/out/zoop-api-spec.md#getmaskedtranscript) | GET /api/v1/admin/transcripts/{session_id} | 6.1.2, 6.10.1, 6.9.2 | 관리자 + transcript:read + 열람 목적 |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '마스킹된 AI 대화록 조회' ↔ 요구사항 78 'AI 대화록, 뉴스 요약, 브리핑 등 수집 및 선호도 확인'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
