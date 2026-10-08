# 개발 참여 규약

이 저장소는 **polyglot monorepo**입니다. 코드 위치와 앱별 빌드 도구를 유지합니다. 현재 프로토타입 스택은 본개발 언어 선택을 강제하지 않습니다. Java/Spring은 후보이며 아직 앱·설치 대상·빈 디렉터리·가짜 빌드 target을 만들지 않습니다.

## 프로젝트 경계와 루트 명령

| 경계 | 현재 위치 | 책임 | 루트 명령 |
|---|---|---|---|
| web | `prototype/web` | React/Vite 사용자·관리자 화면 | `make web-install web-typecheck web-test web-build` |
| api | `prototype/bff` | FastAPI 프로토타입 BFF, 읽기·세션·작업 consumer | `make bff-install bff-test`, `make bff-build` |
| ai | `prototype/ai-worker` | 별도 Python CLI JSON worker | `make worker-install worker-test WORKER_PYTHON=prototype/ai-worker/.venv/bin/python`, `make worker-build` |
| contracts | `docs/api` | **언어와 독립적인 목표 계약** | `make contracts-check docs-check worker-contracts-check` |
| infra | `.github`, `scripts`, `Makefile` | CI, 로컬 검사, 소스 아티팩트 준비 | `make config-check tooling-test` |

`make help`, `make projects`, `make available-checks`는 루트에서 명령·실제 도구 가용성을 보여 줍니다. 설치 target과 검사 target은 구분합니다. 앱 전체 검사는 각각 독립 실행하며 BFF 서버를 띄워야 웹 테스트가 실행되는 구조가 아닙니다. 루트 `package.json`이나 JS workspace로 Python/Java를 관리하지 않습니다. 추후 확정된 Java 앱이 들어오면 **그 앱의 Gradle/Maven wrapper**를 루트 target에 연결하고 해당 CI job만 이행합니다. 목표 계약과 다른 앱의 빌드를 바꾸지 않습니다. 자세한 준비·수동 등록은 [GitHub 설정 가이드](docs/development/github-setup.md)에 있습니다.

필수 도구는 Python 3.12 이상, Node.js 22.12 이상, pnpm 11.9.0, uv, make입니다. `make worker-test`의 기본 Python은 기존 BFF `.venv`이며 설치 없이 worker 코드를 `PYTHONPATH`로 읽습니다. 독립 worker 환경이 준비돼 있으면 `WORKER_PYTHON=prototype/ai-worker/.venv/bin/python`을 지정합니다. BFF의 private PoC 접근 권한은 별도로 필요합니다. 앱 manifest에 자동화용 의존성을 추가하지 않습니다.
`BFF_PYTHON`은 BFF→web 타입 및 worker portable contract 생성 drift에 쓰는 BFF 실행기이고 `WORKER_PYTHON`과 독립적으로 지정할 수 있습니다.

문서/validator 도구가 이미 설치돼 있으면 `CONFIG_PYTHON`, `DOC_PYTHON`, `CONTRACT_PYTHON`, `PUBLIC_PYTHON`에 해당 실행기를 지정합니다. 지정하지 않으면 기존 문서 가이드와 같은 `uv run --no-project --with …` bootstrap을 사용합니다. 개인 캐시 경로를 저장소나 CI에 넣지 않습니다. `make docs-check`와 `make tokens-check`는 임시 디렉터리에서 생성물을 비교하므로 작업 중인 원본을 덮어쓰지 않습니다.

## Issue → branch → PR → squash

1. 중복 이슈를 검색하고 Feature 또는 Bug 양식에 FS/NFS, **WBS ID와 현재 업무명**, screen ID, acceptance criteria를 적습니다. 번호 존재만으로 같은 업무라고 판단하지 않습니다. 관련 ID가 없으면 사유를 적습니다.
2. 브랜치는 `feat|fix|docs|chore/<issue>-<slug>` 형식으로 직접 만듭니다. 예: `feat/123-document-view`. 실제 이슈 번호를 사용하며 임의의 담당자를 자동 배정하지 않습니다.
3. 커밋과 PR 제목은 Conventional Commits를 사용합니다: `type(scope): 설명`, breaking change는 `type(scope)!: 설명`입니다. scope는 `web`, `api`, `ai`, `contracts`, `docs`, `infra`입니다. type은 `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci`, `perf`, `revert`입니다. 예: `feat(ai): 문서 요약 작업 consumer 추가`.
4. PR에는 이슈 연결, 변경 범위, 계약·consumer·생성물 영향, 실행한 명령과 실제 관측 결과, 미검증 사항을 적습니다. 실패·복구·회귀 시험도 포함합니다. 모든 이슈/PR 본문에서 실제 출처와 합성 fixture를 구분합니다.
5. 경로별 리뷰 담당자를 팀이 확인한 뒤 지정합니다. CI와 리뷰가 통과하면 `main`에 squash merge하며 PR 제목을 squash 커밋 제목으로 사용합니다. 실패 시 되돌릴 코드와 상태/데이터 복원 절차를 PR에 적습니다.

PR 제목 검사는 CI에서 수행합니다. 브랜치명/개별 커밋 규약은 리뷰 규약이며 자동 강제로 표시하지 않습니다. 추천 main 보호 설정은 [설정 가이드](docs/development/github-setup.md#main-보호-수동-등록)에 있습니다. 이 파일을 추가한 것만으로 GitHub 보호 규칙이 활성화되지는 않습니다.

## 계약·생성물·권한

- `docs/api/openapi.yaml`은 목표 계약 정본이고 현재 BFF `/openapi.json`은 구현 관측본입니다. `prototype/web/src/api/schema.d.ts`는 현재 BFF에서 생성하는 타입이며 목표 계약으로 무조건 대체하지 않습니다.
- BFF 생성 web 타입은 `make bff-types-check`로 검사합니다. 설치된 BFF Python과 web 도구가 필요한 cross-app seam이며 실제 서버·사용자 상태 없이 합성 snapshot과 temp state에서 비교합니다.
- API를 바꾸면 BFF consumer, web fixture/타입/시험, worker JSON 계약의 영향을 함께 검토합니다. CI는 현재 모든 앱을 검사하므로 변경 경로 selector가 계약 consumer를 누락시키지 않습니다.
- 토큰 원본은 `docs/design/tokens.json`입니다. `pnpm --dir prototype/web tokens`로 CSS/TS를 재생성합니다. 문서 생성 원본·명령은 [docs/system/README.md](docs/system/README.md)를 따릅니다.
- 문서 검사는 **hard error 0 + XLSX readback passed + 생성물 drift 없음**을 요구합니다. 원문 경고·팀 미결정·목표/BFF 차이는 숨기지 않으며 `build.py --check`의 종료 1을 무조건 구현 실패로 보지 않습니다.
- `.env`, 키, 인증 헤더, DB, 개인 기록, 사용자 로그는 커밋·이슈·PR·아티팩트에 넣지 않습니다. 실제 secret 파일을 검사 목적으로 열지 않습니다. 합성 최소 입력으로 재현합니다.
- 뉴스·문서·그림·폰트·패키지의 라이선스/사용 권한을 기록합니다. 판정 확률을 감성 또는 가격 예측으로 해석하지 않습니다. 모델 설정과 **실제 유료 호출 승인**은 별개입니다. CI는 모델 키나 실제 외부 데이터를 전달하지 않습니다.
- `make secret-check`는 추적 파일과 `.gitignore`에 제외되지 않은 새 파일의 민감한 파일명·알려진 credential signature를 검사합니다. 실제 `.env`·키·DB 파일은 이름에서 먼저 차단하고 내용을 읽지 않습니다. 값을 출력하지 않으며 전체 보안 감사·Git 이력 검사·모든 secret 탐지를 보장하지 않습니다. 유출 발견 시 값은 붙이지 말고 관리자의 비공개 채널로 알리고 폐기/회전합니다.
- CI의 App key/token은 same-repository PR 작성자로부터 격리되지 않습니다. main 승인/CODEOWNERS는 PR 실행 전 접근을 막지 않으므로 [credential trust 선행 승인](docs/development/github-setup.md#private-poc-읽기-등록) 없이 secrets를 등록하거나 해당 원격 CI를 활성화하지 않습니다.

## 경로별 리뷰 책임 (실제 handles 등록 전)

| 경로 | 확인할 리뷰 역할 | 필요한 검토 |
|---|---|---|
| `prototype/web/**` | 프론트엔드 담당 | 접근성, 실패·복구, fixture와 실제 데이터 구분 |
| `prototype/bff/**` | API/백엔드 담당 | 인증·상태·작업 consumer·private PoC 경계 |
| `prototype/ai-worker/**` | AI/파이프라인 담당 | CLI JSON 계약, 재실행·취소, 출처·호출 승인 |
| `docs/api/**`, `docs/system/**` | 계약 담당 + 영향을 받는 앱 담당 | 목표/관측 구분, 추적 ID 의미, 전체 consumer |
| `.github/**`, `scripts/**`, `Makefile` | 저장소 관리자/자동화 담당 | 권한·secret 범위·검사 gate·allowlist |
| `docs/**` | 해당 근거/명세 담당 | 출처, 권리, 현재 결정과 원문 충돌 |

실제 GitHub 사용자/팀 handles와 write 권한이 확정되지 않아 `CODEOWNERS`는 만들지 않습니다. 관리자가 위 역할에 실제 조직 팀/사용자를 매핑하고 팀 접근 권한을 확인한 뒤 파일과 “Require review from Code Owners”를 함께 등록합니다. 빈 파일이나 가짜 owner로 등록 완료를 대신하지 않습니다.
