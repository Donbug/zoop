# FS011-02 · 추천 종목·산업·테마 조회

[전체 목록](index.md) · [검사 결과](warnings.md) · [범위 예외·상세 권한](detail-authority.md)

| 항목 | 원본/연결 |
| --- | --- |
| 원본 우선순위·상태 | P1 · 확정 |
| 원문 범위 분류 | existing |
| 유효 구현 범위 | 사용자 기능 제외 · API 유보 |
| 유효 기준 | user-2026-10-10-feedback · docs/share/day-work-2026-10-10.md |
| 완료·실행 경계 | 요구 범위 포함은 구현 완료·유료 실행 승인·본개발 채택이 아님 |
| 요구사항 번호(원문) | 11 |
| 의미 기준 요구사항 | 11 |
| API 대응 | 연결됨 |
| 사유 |  |
| 프로토타입 문서 판정 | 부분 |
| 코드 위치(실행 증거 아님) | prototype/bff/src/zoop_bff/routers/me.py:39 |

## 원본과 의미

[docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv:21 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/00-명세-목차.csv)

- [docs/evidence/raw/functional-spec_2026-10-18/02-온보딩-튜토리얼.csv:65 (xlsx-row)](../../../docs/evidence/raw/functional-spec_2026-10-18/02-온보딩-튜토리얼.csv) — 추천 종목·산업·테마 조회: 로그인 회원이 초기 설정 또는 관심종목 수정 화면을 열면 검색어 없이 살펴볼 수 있는 추천 종목·산업·테마 목록을 제공한다.

## 상세 권한과 의미 이행

- 사용자 기능 제외 · API 유보: 추천 종목·산업·테마는 활성 기능·사용자 여정·수용 범위에서 제외한다. GET /me/recommendations 계약과 현재 BFF 동작은 삭제·무동작 대체·가짜 응답 없이 유보하며 이후 다시 반환할 수 있다. 유보는 활성 사용 허용을 뜻하지 않는다.

문서 판정 출처: [docs/evidence/spec-v1.2-gap.md:185 (text-line)](../../../docs/evidence/spec-v1.2-gap.md). 기준선에 반영 현황의 마지막 행을 적용한 판정이며 번호가 재사용된 AI ID는 의미 이행표가 정한 곳에만 적용한다. 이번 생성기의 실행 검증은 아니다.

## WBS 편집 연결

| WBS | 역할 | 현재 업무 | 연결 근거 |
| --- | --- | --- | --- |
| 6.3.3 | BE | (BE) 관심종목 검색 API 개발 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.3.11 | 공통/통합 | 온보딩 전체 흐름 통합 테스트 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |
| 6.4.5 | FE | (FE) D-WAT-01b 초기 관심종목 선택 화면 및 검색·등록 API 연동 | 현재 업무명·역할·FS 내용을 대조한 편집 연결이다. 원문 산출물의 ID/의존 참조는 rawSpecIds와 분리한다. |

## 화면·목표 API



| 작업 | 메서드·목표 경로 | WBS | 권한 |
| --- | --- | --- | --- |
| [listRecommendations](../../api/out/zoop-api-spec.md#listrecommendations) | GET /api/v1/me/recommendations | 6.1.2, 6.11.1, 6.3.3, 6.4.5 | 회원(본인) |

## 확인 필요

- REQUIREMENT_TITLE_REVIEW: 명세 '추천 종목·산업·테마 조회' ↔ 요구사항 11 '관심종목 검색과 추천 조회'. 분리·통합/번호 이동인지 확인 필요(자동 재연결하지 않음).
