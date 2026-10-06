# FS048 · 개인화 조건과 근거 확보

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 팀 검토 전 |
| 요구사항 번호 | 48 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:58 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/07-AI-챗봇.csv) — 개인화 조건과 근거 확보: 현재 접근 권한으로 사용할 수 있는 개인화 정보와 질문 작업에 고정된 근거 문서를 조회해야 한다. 로그인·종목 설정 등 조건 부족, 근거 부족, 기술 오류를 구분해야 한다. 선택한 문서나 버전을 사용할 수 없다고 최신 자료로 몰래 바꿔서는 안 된다.
- [docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/08-AI-챗봇-v2.csv) — 근거 기반 답변 생성 및 안전 검증: 시스템은 조회된 근거·관계·시장 데이터만 바탕으로 답변을 생성한다. 답변에는 적용 대상·기간, 핵심 설명, 연결 근거, 한계 또는 추가 확인 사항을 포함한다. 매수·매도 권유나 수익·가격 예측은 제공하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:35 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.10.1, 6.5.9, 6.8.1, 6.8.2, 6.8.3, 6.8.4, 6.8.5, 6.8.6, 6.4.7, 6.4.11 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
