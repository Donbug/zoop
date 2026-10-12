# FS036 · 개인화 브리핑 조회

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P2 · 검토 중 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 팀합의요구/설계대상 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 36 |
| 의미 기준 요구사항 | 36 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 미구현 |
| 코드 위치(실행 증거 아님) |  |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv:46 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-10/05-출퇴근-브리핑.csv:121 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-10/05-출퇴근-브리핑.csv) — 개인화 브리핑 조회: 사용자는 선택한 출근·퇴근 회차에서 자신의 보유 종목과 관심 종목을 기준으로 개인화 브리핑을 요청할 수 있어야 한다.보유 비중이 확보된 경우 분석에 활용하고, 어떤 종목과 기준 시점으로 작성된 결과인지 표시해야 한다. 보유 종목이 없으면 관심 종목을 기준으로 제공하며, 둘 다 없으면 종목 설정 또는 공통 브리핑 조회를 안내해야 한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:220 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.8.9 | BE | (BE) 개인화 브리핑 조회 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.8.14 | FE | (FE) 브리핑 관계 그래프·개인화·평가 UI 및 API 연동 | 15:05 WBS 재수집의 E136에서 과거 평가 FS037이 FS066-01로 정정되어 원문과 편집 연결이 일치한다. 제목·FE 역할은 동일하며 현재 종목 검색 FS037과 혼동하지 않는다. docs/evidence/api-source-refresh-2026-10-08.md의 전셀/의미 비교를 따른다. |
| 6.8.15 | 공통/통합 | 출퇴근 브리핑 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API

[D-BRF-01](screen-D-BRF-01.md) · [D-BRF-02](screen-D-BRF-02.md) · [M-BRF-01](screen-M-BRF-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [getPersonalizedBriefing](../../api/out/zoop-api-spec.md#getpersonalizedbriefing) | GET /api/v1/briefings/{id}/personalized | 6.1.2, 6.11.1, 6.8.9, 6.8.14 | 회원(본인) |
