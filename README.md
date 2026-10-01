# 줍(Zoop)

LG CNS AM Inspire Camp 5기 2조 금융 도메인 프로젝트. 내 종목과 시장의 사건이 왜 연결되는지, 어떤 근거가 있는지를 보여 주는 금융 지도 서비스의 설계 문서와 동작하는 프로토타입입니다.

| 경로 | 내용 |
|---|---|
| [`prototype/`](prototype/README.md) | 실행 가이드. `bff`(FastAPI BFF)와 `web`(Vite + React 사용자 앱·관리자 패널) |
| [`docs/evidence/`](docs/evidence/README.md) | 요구사항·회의록·PoC 근거. 기능 기준은 `raw/requirements-sheet_2026-10-01/`의 요구사항 정의서 고정본 |
| `docs/design/` | 디자인 방향·토큰·화면 캡처·그래프 UX 결정 |
| `docs/research/` | UX·그래프 시각화 레퍼런스 조사 |
| `docs/share/` | 팀 공유용 단일 HTML 문서 |

뉴스 → 사건 판정 로직(PoC)은 별도 비공개 저장소 [`Donbug/investmate-poc`](https://github.com/Donbug/investmate-poc)에 있고, BFF가 고정 커밋으로 의존합니다.
