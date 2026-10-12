# FS032 · 브리핑 관계 그래프 조회

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 32 |
| 의미 기준 요구사항 | 32 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 구현 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/briefings.py:15 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:42 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-10/05-출퇴근-브리핑.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/05-출퇴근-브리핑.csv) — 브리핑 관계 그래프 조회: 사용자가 브리핑의 관계 그래프를 열면 해당 회차 기준의 핵심 이슈와 기업 경로를 확인한다. 이슈 노드, 기업 패널의 관련 이슈, 기업 간 간선에서 설명과 근거를 확인한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:34 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.8.5 | BE | (BE) 브리핑 관계 그래프 조회 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.14 | FE | (FE) 브리핑 관계 그래프·개인화·평가 UI 및 API 연동 | 15:05 WBS 재수집의 E136에서 과거 평가 FS037이 FS066-01로 정정되어 원문과 편집 연결이 일치한다. 제목·FE 역할은 동일하며 현재 종목 검색 FS037과 혼동하지 않는다. docs/evidence/api-source-refresh-2026-10-08.md의 전셀/의미 비교를 따른다. |
| 6.8.15 | 공통/통합 | 출퇴근 브리핑 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-GRP-01](screen-D-GRP-01.md) · [D-GRP-01b](screen-D-GRP-01b.md) · [D-GRP-07](screen-D-GRP-07.md) · [D-GRP-07b](screen-D-GRP-07b.md) · [D-BRF-04](screen-D-BRF-04.md) · [M-GRP-01](screen-M-GRP-01.md) · [D-COM-04](screen-D-COM-04.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getGraph](../../api/out/zoop-api-spec.md#getgraph) | GET /api/v1/graph | 6.1.2, 6.11.1, 6.3.6, 6.4.7, 6.6.1, 6.6.2, 6.6.3, 6.6.11, 6.6.21, 6.6.23, 6.7.3, 6.7.7, 6.7.8, 6.7.10, 6.7.11, 6.7.12, 6.8.5, 6.8.14, 6.5.1 | 공개(all) / 회원 본인(personal) |
| [getBriefingGraphBasis](../../api/out/zoop-api-spec.md#getbriefinggraphbasis) | GET /api/v1/briefings/{id}/graph | 6.1.2, 6.11.1, 6.8.5, 6.8.8, 6.8.11, 6.8.12, 6.8.13, 6.8.14, 6.5.3 | 공개 |

## 확인 필요

- REQUIREMENT_BINDING_BY_MEANING: 명세 '브리핑 관계 그래프 조회' ↔ 원문 요구 번호 32 '관계 그래프 조회'. 의미 기준 연결은 요구 ['32']이다(목차명 정합화): 관계 그래프 조회→브리핑 관계 그래프 조회. 상세 시트의 의미와 같다.
