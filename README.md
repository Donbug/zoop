# 줍(Zoop)

LG CNS AM Inspire Camp 5기 2조 금융 도메인 프로젝트. 내 종목과 시장의 사건이 왜 연결되는지, 어떤 근거가 있는지를 보여 주는 금융 지도 서비스의 설계 문서와 동작하는 프로토타입입니다.

| 경로 | 내용 |
|---|---|
| [`prototype/`](prototype/README.md) | 실행 가이드. `web`(Vite + React), `bff`(FastAPI), `ai-worker`(독립 JSON CLI)로 구성한 현재 프로토타입 |
| [`docs/evidence/`](docs/evidence/README.md) | 원본·차이 근거. 현재 명세·WBS는 [10-10 고정본](docs/evidence/doc-delta-2026-10-10.md), 요구사항은 의미가 같은 10-06 고정본. 10-08 고정본과 [API v2 검토·채택/정정 목록](docs/evidence/api-v2-review-2026-10-08.md)은 역사·근거 기록 |
| `docs/design/` | 디자인 방향·토큰·화면 캡처·그래프 UX 결정 |
| `docs/research/` | UX·그래프 시각화 레퍼런스 조사 |
| [`docs/share/day-work-2026-10-10.md`](docs/share/day-work-2026-10-10.md) | 현재 작업 기준(10-10 피드백 동기화: 범위 예외·현행/이력 상세·AI 의미 이행·차트 해상도). 모든 명세/WBS 요구는 팀합의 설계대상이며 원문 상태·완료·실행 승인과 구분. 10-08 기준([`day-work-2026-10-08.md`](docs/share/day-work-2026-10-08.md))은 이어서 유효 |
| [`docs/development/release-verification.md`](docs/development/release-verification.md) · [`docs/share/seojin-work-plan-2026-10-12.md`](docs/share/seojin-work-plan-2026-10-12.md) | 배포·검증 증거 절차와 10/12 주 작업 계획. 작성 담당이 별도로 관리하며 이 문서들의 WBS 연결은 원본 WBS를 대체하지 않음 |
| [`docs/share/overnight-2026-10-08.md`](docs/share/overnight-2026-10-08.md) | 새벽 작업의 역사 기록. 현재 사용자 결정과 충돌하는 범위·디자인·일정 가정은 대체됨 |
| [`docs/share/system-architecture/`](docs/share/system-architecture/README.md) | 전체·프론트·백엔드 도식. 현재 실행 구조와 목표/클라우드 초안 구분 |
| [`프로토타입 설명서`](docs/share/prototype-guide.md) | 소개·10분 시연·실행·복구·개발 연동. [PDF](docs/share/prototype-guide.pdf) · [단독 HTML](docs/share/prototype-guide.html) |
| [`docs/system/`](docs/system/README.md) | 화면→명세→현재 WBS 역할→목표 API 연결. [팀용 추적표](docs/system/out/zoop-trace.xlsx), [내용 기반 WBS 이행](docs/system/out/wbs-migration.md), [경고/차이](docs/system/out/warnings.md) |
| [`docs/api/openapi.yaml`](docs/api/openapi.yaml) | 정식 서버 목표 계약의 정본. API v2의 프로필·사건 관계·최신 시세·회원 Google/카카오 의도를 반영하며 앱 구현 완료는 아님. 공통 규칙은 잠정 채택/시연 기준. [생성 API 명세서](docs/api/out/zoop-api-spec.md) |
| [`docs/screen-plan/`](docs/screen-plan/README.md) | 우리 프로토타입 기준 화면계획서. [팀 Figma 1:1 비교](docs/evidence/wireframe-delta-2026-10-08.md)는 별도 근거 |
| [`AI 실행 계약`](docs/design/ai-system.md) | 문서 요약·기업별 판정·의미 검증과 기존 회차 판정의 현재 구현, 이후 AI 단계의 설계 범위 |
| [`다음 작업 후보`](docs/share/next-work-2026-10-08.md) | S2 수집·문서 계보부터 S7 개인화까지의 순서, 선행조건, 실제 완료 장면 |
| [`마이그레이션 가이드`](docs/migration/README.md) | FE·앱 백엔드·AI 런타임의 독립 선택과 JSON·HTTP·근거·작업 상태 계약 이식 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 브랜치·커밋·PR·리뷰·생성물 규약. [`GitHub 설정 안내`](docs/development/github-setup.md)는 원격 등록 선행조건을 구분 |

현재 일정은 **WBS**를 따릅니다. 옛 Notion 일정은 비권위이고 갱신된 Notion 회의·API 결정은 사례별 증거입니다. 기존 UI 코드는 현재 구현이고 **Figma는 폰트를 제외한 최종 목표 디자인**입니다. SUIT를 유지하며 기능을 먼저 완성합니다. 프로토타입은 전권 범위로 끝까지 완성하되 본개발 채택은 담당자가 선택합니다. FS074~FS081을 포함한 모든 명세/WBS 내용은 구현 계획에 포함하며 `검토 전` 등 원문 표기는 별도로 보존합니다. 추천 종목·산업·테마는 활성 기능에서 제외하되 API 계약은 유보하고, 재무·실적 요구는 폐기하지 않았습니다.

마이그레이션은 언어·프레임워크에 독립적으로 준비합니다. 현재 React/Python 구현을 그대로 재사용해야 한다는 전제는 없으며 **Java/Spring 백엔드는 유력 후보이지 확정 스택이 아닙니다**. AI 기능은 설계부터 진행하고 live 예산·실행 승인은 별도로 남깁니다.

루트에서 `make help`, `make projects`, `make available-checks`로 앱별 명령과 필요한 도구를 확인합니다. CI와 검증된 커밋의 소스/웹 아티팩트 준비 workflow를 포함합니다. **파일 반영과 CI 통과는 별개**이며 커밋별 Actions 결과를 확인해야 합니다. 보호 규칙·private PoC 자격 증명 등록·클라우드 배포는 완료하지 않았습니다.

뉴스 → 사건 판정 로직(PoC)은 별도 비공개 저장소 [`Donbug/investmate-poc`](https://github.com/Donbug/investmate-poc)에 있고, BFF가 고정 커밋으로 의존합니다.
