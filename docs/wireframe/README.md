# ZOOP 와이어프레임 개발 참조

> 첨부된 `zoop-wireframe.pdf`의 8개 보드를 개발 중 검색·참조하기 쉬운 형태로 정리한 자료입니다.

## 사용 방법

- 화면을 구현하거나 수정하기 전에 화면 ID로 이 문서와 `manifest.json`을 검색합니다.
- 전체 흐름은 `boards/`, 실제 UI 디테일은 `screens/`의 개별 PNG를 기준으로 확인합니다.
- `manifest.json`의 `routes`는 기존 화면계획서의 기준 경로이며, 시각 이미지가 동작 완료를 증명하지는 않습니다.
- 화면에 명시되지 않은 오류·로딩·빈 상태나 상호작용은 임의로 확정하지 말고 관련 요구사항·화면계획서와 함께 확인합니다.

## 파일 구성

| 경로 | 용도 |
|---|---|
| `manifest.json` | 화면 ID, 섹션, 순서, 라우트, Figma node를 담은 기계 판독용 인덱스 |
| `boards/*.jpg` | PDF 페이지 전체 흐름을 빠르게 보는 보드 이미지 |
| `screens/*.png` | 구현 시 확대해 보는 개별 화면 원본 |

현재 범위: **8개 섹션 · 44개 프레임 · 41개 고유 화면 ID**

첨부본에 없는 디자인시스템(07)·모바일(08) 화면은 이 폴더의 범위에 포함하지 않았습니다.

## 01 · 회원가입·로그인·온보딩

[전체 보드 보기](boards/01-auth-onboarding.jpg)

| 순서 | 화면 ID | 화면명 | 기준 라우트 | 이미지 | 상세 문서 |
|---:|---|---|---|---|---|
| 1 | `D-AUT-01` | D-AUT-01 · 시작·이메일 로그인 | `/login` | [PNG](screens/D-AUT-01--node-619-1080.png) | [D-AUT-01](../system/out/screen-D-AUT-01.md) |
| 2 | `D-AUT-02` | D-AUT-02 · 이메일 회원가입 | `/signup` | [PNG](screens/D-AUT-02--node-619-1208.png) | [D-AUT-02](../system/out/screen-D-AUT-02.md) |
| 3 | `D-ONB-01` | D-ONB-01 · 투자 여부 선택 | `/onboarding` | [PNG](screens/D-ONB-01--node-619-1429.png) | [D-ONB-01](../system/out/screen-D-ONB-01.md) |
| 4 | `D-ONB-02` | D-ONB-02 · 가상 계좌 연결 | `/onboarding` | [PNG](screens/D-ONB-02--node-619-1509.png) | [D-ONB-02](../system/out/screen-D-ONB-02.md) |
| 5 | `D-WAT-01` | D-WAT-01 · 관심 종목 선택 | `/onboarding` | [PNG](screens/D-WAT-01--node-619-1615.png) | [D-WAT-01](../system/out/screen-D-WAT-01.md) |

## 02 · 지도 튜토리얼

[전체 보드 보기](boards/02-map-tutorial.jpg)

| 순서 | 화면 ID | 화면명 | 기준 라우트 | 이미지 | 상세 문서 |
|---:|---|---|---|---|---|
| 1 | `D-GRP-T` | D-GRP-T · 지도 튜토리얼 1/5 — 지도 움직이기 | `/?mode=all&tour=1` | [PNG](screens/D-GRP-T--node-619-3337.png) | [D-GRP-T](../system/out/screen-D-GRP-T.md) |
| 2 | `D-GRP-T2` | D-GRP-T2 · 지도 튜토리얼 2/5 — 기업·사건 선택 | `/?mode=all&tour=1` | [PNG](screens/D-GRP-T2--node-619-3920.png) | [D-GRP-T2](../system/out/screen-D-GRP-T2.md) |
| 3 | `D-GRP-T3` | D-GRP-T3 · 지도 튜토리얼 3/5 — 영향 경로 | `/?mode=all&tour=1` | [PNG](screens/D-GRP-T3--node-619-4508.png) | [D-GRP-T3](../system/out/screen-D-GRP-T3.md) |
| 4 | `D-GRP-T4` | D-GRP-T4 · 지도 튜토리얼 4/5 — 상세·근거 | `/?mode=all&tour=1` | [PNG](screens/D-GRP-T4--node-619-5095.png) | [D-GRP-T4](../system/out/screen-D-GRP-T4.md) |
| 5 | `D-GRP-T5` | D-GRP-T5 · 지도 튜토리얼 5/5 — AI 질문 | `/?mode=all&tour=1` | [PNG](screens/D-GRP-T5--node-619-5682.png) | [D-GRP-T5](../system/out/screen-D-GRP-T5.md) |

## 03 · 지도·관계·근거

[전체 보드 보기](boards/03-map-relationships-evidence.jpg)

| 순서 | 화면 ID | 화면명 | 기준 라우트 | 이미지 | 상세 문서 |
|---:|---|---|---|---|---|
| 1 | `D-GRP-01` | D-GRP-01 · 시장 전체 지도 | `/?mode=all` | [PNG](screens/D-GRP-01--node-619-1819.png) | [D-GRP-01](../system/out/screen-D-GRP-01.md) |
| 2 | `D-GRP-01b` | D-GRP-01b · 내 종목 지도·범위 필터 | `/?mode=personal` | [PNG](screens/D-GRP-01b--node-619-2374.png) | [D-GRP-01b](../system/out/screen-D-GRP-01b.md) |
| 3 | `D-GRP-01` | D-GRP-01 · 시장 전체 지도 — 확대 상태 | `/?mode=all` | [PNG](screens/D-GRP-01--node-619-2769.png) | [D-GRP-01](../system/out/screen-D-GRP-01.md) |
| 4 | `D-GRP-02` | D-GRP-02 · 사건 패널 | `/?mode=all&select=node%3Aissue-04153e2e4c2a1b58e40a0e57` | [PNG](screens/D-GRP-02--node-619-6269.png) | [D-GRP-02](../system/out/screen-D-GRP-02.md) |
| 5 | `D-GRP-03` | D-GRP-03 · 기업 패널·시세·1개월 추이 | `/?mode=all&select=node%3AKRX%3A005930` | [PNG](screens/D-GRP-03--node-619-6729.png) | [D-GRP-03](../system/out/screen-D-GRP-03.md) |
| 6 | `D-GRP-04` | D-GRP-04 · 연결선 상세 | `/?mode=all&select=edge%3Aedge-f53400022fc7c812` | [PNG](screens/D-GRP-04--node-619-7557.png) | [D-GRP-04](../system/out/screen-D-GRP-04.md) |
| 7 | `D-GRP-05` | D-GRP-05 · 근거 문서 창 | `/?mode=all&select=node%3AKRX%3A005930&impact=KRX%3A005930%2Cissue-25ac3f6d1288d2b7ffa5454d` | [PNG](screens/D-GRP-05--node-619-8225.png) | [D-GRP-05](../system/out/screen-D-GRP-05.md) |
| 8 | `D-GRP-06` | D-GRP-06 · 기업에서 여는 영향 경로 | `/?mode=all&select=node%3AKRX%3A005930&impact=KRX%3A005930%2Cissue-25ac3f6d1288d2b7ffa5454d` | [PNG](screens/D-GRP-06--node-619-8880.png) | [D-GRP-06](../system/out/screen-D-GRP-06.md) |
| 9 | `D-GRP-07` | D-GRP-07 · 두 기업 사이 경로 | `/?mode=all&path=KRX%3A005930%2CNASDAQ%3ANVDA` | [PNG](screens/D-GRP-07--node-619-9575.png) | [D-GRP-07](../system/out/screen-D-GRP-07.md) |
| 10 | `D-GRP-07b` | D-GRP-07b · 선택 기업 포커스 | `/?mode=all&select=node%3AKRX%3A005930&focus=KRX%3A005930&hops=1` | [PNG](screens/D-GRP-07b--node-619-10306.png) | [D-GRP-07b](../system/out/screen-D-GRP-07b.md) |
| 11 | `D-BRF-04` | D-BRF-04 · 회차 기준 지도 | `/?round=brf-2026-09-17-evening` | [PNG](screens/D-BRF-04--node-619-10871.png) | [D-BRF-04](../system/out/screen-D-BRF-04.md) |

## 03.5 · 종목 탐색

[전체 보드 보기](boards/03-5-stock-search.jpg)

| 순서 | 화면 ID | 화면명 | 기준 라우트 | 이미지 | 상세 문서 |
|---:|---|---|---|---|---|
| 1 | `D-STK-01` | D-STK-01 · 종목 탐색 | `/companies?q=%EC%82%BC%EC%84%B1` | [PNG](screens/D-STK-01--node-692-2.png) | [D-STK-01](../system/out/screen-D-STK-01.md) |

## 04 · 기업 상세·시점 탐색

[전체 보드 보기](boards/04-company-detail.jpg)

| 순서 | 화면 ID | 화면명 | 기준 라우트 | 이미지 | 상세 문서 |
|---:|---|---|---|---|---|
| 1 | `D-COM-01` | D-COM-01 · 기업 상세·시세·모의 보유 | `/companies/KRX%3A005930?asOf=2026-10-06T03%3A41%3A18.068Z` | [PNG](screens/D-COM-01--node-637-2222.png) | [D-COM-01](../system/out/screen-D-COM-01.md) |
| 2 | `D-COM-01b` | D-COM-01b · 차트·시간 버킷·인과관계 고지 | `/companies/KRX%3A005930?asOf=2026-10-06T03%3A41%3A18.068Z&tab=events` | [PNG](screens/D-COM-01b--node-637-6212.png) | [D-COM-01b](../system/out/screen-D-COM-01b.md) |
| 3 | `D-COM-02` | D-COM-02 · 문서 탭 전환 — 상태 확인 필요 | `/companies/KRX%3A005930?asOf=2026-10-06T03%3A41%3A18.068Z&tab=documents` | [PNG](screens/D-COM-02--node-658-7834.png) | [D-COM-02](../system/out/screen-D-COM-02.md) |
| 4 | `D-COM-05`, `D-COM-06` | D-COM-05/06 · 버킷·차트·그래프 연동·주가 그래프 시점 선택 | `/companies/KRX%3A005930?period=1m&asOf=2026-09-30T23%3A59%3A59%2B09%3A00&tab=events` | [PNG](screens/D-COM-05_D-COM-06--node-658-8442.png) | [D-COM-05](../system/out/screen-D-COM-05.md)<br>[D-COM-06](../system/out/screen-D-COM-06.md) |
| 5 | `D-COM-02` | 문서 탭 | `/companies/KRX%3A005930?asOf=2026-10-06T03%3A41%3A18.068Z&tab=documents` | [PNG](screens/D-COM-02--node-663-14180.png) | [D-COM-02](../system/out/screen-D-COM-02.md) |
| 6 | `D-COM-01` | 기업 정보 탭 | `/companies/KRX%3A005930?asOf=2026-10-06T03%3A41%3A18.068Z` | [PNG](screens/D-COM-01--node-663-13515.png) | [D-COM-01](../system/out/screen-D-COM-01.md) |

## 05 · 출퇴근 브리핑

[전체 보드 보기](boards/05-briefing.jpg)

| 순서 | 화면 ID | 화면명 | 기준 라우트 | 이미지 | 상세 문서 |
|---:|---|---|---|---|---|
| 1 | `D-BRF-01` | D-BRF-01 · 출근 브리핑 | `/briefing?date=2026-09-17&edition=morning` | [PNG](screens/D-BRF-01--node-620-948.png) | [D-BRF-01](../system/out/screen-D-BRF-01.md) |
| 2 | `D-BRF-02` | D-BRF-02 · 퇴근 브리핑·회차 비교 | `/briefing?date=2026-09-17&edition=evening` | [PNG](screens/D-BRF-02--node-620-1278.png) | [D-BRF-02](../system/out/screen-D-BRF-02.md) |
| 3 | `D-BRF-04` | D-BRF-04 · 회차 기준 지도 | `/?round=brf-2026-09-17-evening` | [PNG](screens/D-BRF-04--node-730-278.png) | [D-BRF-04](../system/out/screen-D-BRF-04.md) |

## 06 · AI 질문·대화 상태

[전체 보드 보기](boards/06-ai-chat.jpg)

| 순서 | 화면 ID | 화면명 | 기준 라우트 | 이미지 | 상세 문서 |
|---:|---|---|---|---|---|
| 1 | `D-AI-01` | D-AI-01 · AI 질문·대상 연결 | `/?mode=all&select=node%3AKRX%3A005930` | [PNG](screens/D-AI-01--node-620-1593.png) | [D-AI-01](../system/out/screen-D-AI-01.md) |
| 2 | `D-AI-01b` | D-AI-01b · AI 되묻기 | `/?mode=all&select=node%3AKRX%3A005930` | [PNG](screens/D-AI-01b--node-620-3770.png) | [D-AI-01b](../system/out/screen-D-AI-01b.md) |
| 3 | `D-AI-02` | D-AI-02 · AI 작업 복구·대화 회수 | `/?mode=all&select=node%3AKRX%3A005930` | [PNG](screens/D-AI-02--node-620-4314.png) | [D-AI-02](../system/out/screen-D-AI-02.md) |
| 4 | `D-AI-02b` | D-AI-02b · 대화 조회 오류 — 상태 확인 필요 | `/?mode=all&select=node%3AKRX%3A005930` | [PNG](screens/D-AI-02b--node-620-4859.png) | [D-AI-02b](../system/out/screen-D-AI-02b.md) |

## 09 · 관리자 운영

[전체 보드 보기](boards/09-admin.jpg)

| 순서 | 화면 ID | 화면명 | 기준 라우트 | 이미지 | 상세 문서 |
|---:|---|---|---|---|---|
| 1 | `A-ADM-05c` | A-ADM-05c · 관리자 로그인 | `/admin/login` | [PNG](screens/A-ADM-05c--node-620-8120.png) | [A-ADM-05c](../system/out/screen-A-ADM-05c.md) |
| 2 | `A-ADM-01` | A-ADM-01 · 운영 대시보드 | `/admin` | [PNG](screens/A-ADM-01--node-620-8166.png) | [A-ADM-01](../system/out/screen-A-ADM-01.md) |
| 3 | `A-ADM-02` | A-ADM-02 · 이용 통계·AI 품질 | `/admin/stats` | [PNG](screens/A-ADM-02--node-620-8616.png) | [A-ADM-02](../system/out/screen-A-ADM-02.md) |
| 4 | `A-ADM-02b` | A-ADM-02b · 선호도·대화록 | `/admin/feedback` | [PNG](screens/A-ADM-02b--node-620-8960.png) | [A-ADM-02b](../system/out/screen-A-ADM-02b.md) |
| 5 | `A-ADM-03` | A-ADM-03 · 그래프 관제·검수 | `/admin/pipeline` | [PNG](screens/A-ADM-03--node-620-9307.png) | [A-ADM-03](../system/out/screen-A-ADM-03.md) |
| 6 | `A-ADM-04` | A-ADM-04 · AI·브리핑 운영 | `/admin/briefings` | [PNG](screens/A-ADM-04--node-620-9769.png) | [A-ADM-04](../system/out/screen-A-ADM-04.md) |
| 7 | `A-ADM-04b` | A-ADM-04b · AI 사용량·오류 | `/admin/ai` | [PNG](screens/A-ADM-04b--node-620-10181.png) | [A-ADM-04b](../system/out/screen-A-ADM-04b.md) |
| 8 | `A-ADM-05` | A-ADM-05 · 회원·접근 관리 | `/admin/members` | [PNG](screens/A-ADM-05--node-620-10650.png) | [A-ADM-05](../system/out/screen-A-ADM-05.md) |
| 9 | `A-ADM-05b` | A-ADM-05b · 관리자 감사 로그 | `/admin/audit` | [PNG](screens/A-ADM-05b--node-620-10924.png) | [A-ADM-05b](../system/out/screen-A-ADM-05b.md) |

## 원본과 갱신

- 원본 파일: `zoop-wireframe.pdf`
- SHA-256: `f9fd2483d9a31b04ad904e05098b946f209f2cfb8219b94237d291eb6448efe3`
- 개별 화면은 `docs/evidence/raw/wireframe_2026-10-08/coverage.json`의 화면 ID·node 대응을 사용했습니다.
- 새 와이어프레임으로 교체할 때는 화면 ID를 유지하고, `manifest.json`과 이 인덱스를 함께 갱신합니다.

