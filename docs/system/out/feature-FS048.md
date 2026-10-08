# FS048 · 개인화 조건과 근거 확보

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 팀 검토 전 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-08-day · docs/share/day-work-2026-10-08.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호 | 48 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/chat.py:17 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv:58 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/07-AI-챗봇.csv) — 개인화 조건과 근거 확보: 현재 접근 권한으로 사용할 수 있는 개인화 정보와 질문 작업에 고정된 근거 문서를 조회해야 한다. 로그인·종목 설정 등 조건 부족, 근거 부족, 기술 오류를 구분해야 한다. 선택한 문서나 버전을 사용할 수 없다고 최신 자료로 몰래 바꿔서는 안 된다.
- [docs/evidence/raw/functional-spec_2026-10-08/08-AI-챗봇-v2.csv:51 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-08/08-AI-챗봇-v2.csv) — 근거 기반 답변 생성 및 안전 검증: 시스템은 조회된 근거·관계·시장 데이터만 바탕으로 답변을 생성한다. 답변에는 적용 대상·기간, 핵심 설명, 연결 근거, 한계 또는 추가 확인 사항을 포함한다. 매수·매도 권유나 수익·가격 예측은 제공하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:41 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.9.3 | BE | (BE) 근거·관계 그래프 맥락 조회 | 근거·관계 그래프 맥락 조회는 현재 FS048의 개인화 조건/근거 확보 의미와 대응한다. |
| 6.9.15 | 공통/통합 | AI 챗봇 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-AI-01](screen-D-AI-01.md) · [D-AI-01b](screen-D-AI-01b.md) · [M-AI-01](screen-M-AI-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [submitQuestion](../../api/out/zoop-api-spec.md#submitquestion) | POST /api/v1/chat/sessions/{id}/jobs | 6.1.2, 6.11.1, 6.6.10, 6.9.1, 6.9.2, 6.9.3, 6.9.4, 6.9.5, 6.9.6, 6.9.10, 6.9.11, 6.9.12, 6.9.13, 6.9.14, 6.5.7 | 회원(본인) |

## 확인 필요

- MULTIPLE_SPEC_DEFINITIONS: 동일 ID의 여러 상세 정의가 공존한다. 우선 문서를 자동 선택하지 않는다.
