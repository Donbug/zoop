# FS011-02 · 추천 종목·산업·테마 조회

[전체 목록](index.md) · [검사 결과](warnings.md)

| 항목 | 원본/연결 |
| --- | --- |
| 우선순위·상태 | P1 · 확정 |
| 요구사항 번호 | 11 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv:21 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-06/02-온보딩-튜토리얼.csv) — 추천 종목·산업·테마 조회: 로그인 회원이 초기 설정 또는 관심종목 수정 화면을 열면 검색어 없이 살펴볼 수 있는 추천 종목·산업·테마 목록을 제공한다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:171 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 이번 생성기의 실행 검증은 아니다.

## 화면·목표 API

[D-WAT-01](screen-D-WAT-01.md)

| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listRecommendations](../../api/out/zoop-api-spec.md#listrecommendations) | GET /api/v1/me/recommendations | 6.1.2, 6.10.1, 6.3.4 | 회원(본인) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '추천 종목·산업·테마 조회' ↔ 요구사항 11 '관심종목 검색과 추천 조회'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
