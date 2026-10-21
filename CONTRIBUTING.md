# 개발 참여 규약

이 저장소는 언어별 앱 도구를 독립적으로 사용하는 **polyglot monorepo**입니다. 본개발과 프로토타입의 책임을 분리하되 현재 실행 경로는 유지합니다. 앱 백엔드는 Java 21·Spring Boot 4.1.1·Gradle 9.7.1 Wrapper와 `com.zoop` 패키지를 선택했습니다. 프론트엔드와 AI 런타임의 스택은 각 앱에서 독립적으로 정합니다.

## 본개발 경로와 생성 조건

아래는 **2026-10-12에 정한 본개발 작업 경로**와 현재 상태입니다. 루트에 책임별 경로를 두고 앱별 manifest/lock과 실행기를 유지하며, 루트 JS workspace로 Python/Java를 관리하지 않는 기존 방식을 이어받습니다. 첫 작업 절차는 [본개발 시작 안내](docs/share/production-start-2026-10-12.md)를 참고합니다.

| 본개발 예정 경로 | 소유 책임 | 현재 상태 |
|---|---|---|
| `web/` | 사용자·관리자 화면, HTTP client, 화면 상태·접근성 | 미생성. React를 포함해 FE 스택은 실제 기능 구현 시 선택합니다. |
| `api/` | 공개 HTTP API, 인증·업무 규칙, 앱 저장소, AI transport consumer | Spring Boot 실행·DB·공통 오류 기반과 내부 AI transport 클라이언트. 업무 API·인증은 미완료, CI job `api` 연결됨. [로컬 실행 안내](api/README.md) |
| `ai/` | AI 실행, 작업·receipt·artifact와 자체 저장소 | 미생성. 앱 BE와 별도 실행 책임을 유지합니다. |
| `contracts/` | 필요한 언어 중립 생성물·합성 fixture의 향후 배포 | 미생성. 실제 consumer와 생성/검증 명령이 생길 때만 만듭니다. |
| `infra/` | 승인된 배포·운영 설정 | 미생성. CI 파일은 현재 `.github/`, 로컬 도구는 `scripts/`에 있습니다. |
| `docs/` | 원문 근거, 설계, API 정본과 추적 자료 | 현재 사용 중입니다. |

루트의 `web/`, `api/`, `ai/`는 각각의 실행·배포·저장 책임을 유지합니다. `contracts/`는 언어 중립 생성물·합성 fixture의 배포용이며 공용 업무 서비스나 DB entity를 담는 곳이 아닙니다. **계약 정본은 계속 `docs/api/`입니다.** 배포 생성물을 수동 수정해 두 번째 원본으로 만들지 않습니다. 정본을 옮기려면 생성기·검사기·문서 링크·모든 consumer를 한 번에 옮기는 명시적 변경으로 처리하고, 두 원본이나 호환 re-export를 남기지 않습니다.

**`api/`는 병렬 개발을 위한 최소 기반 PR에서 먼저 생성할 수 있습니다.** 해당 PR에는 Java 21·Gradle Wrapper, 로컬 PostgreSQL/JPA/Flyway 설정, 공통 오류·요청 ID, 로컬 테스트, 앱 README와 실행 확인을 포함합니다. 업무 API는 이 기반 PR의 병합 조건이 아니었습니다. API 실행기는 루트 명령(`api-test`·`api-build`·`api-ai-smoke`)·CI job `api`·required gate에 연결돼 있으며 첫 API 업무 기능 PR은 그 job에서 자신의 시험이 실제로 실행되는지 확인합니다. 기존 프로토타입 CI 성공으로 API 앱 검증을 대신하지 않습니다.

`web/`, `ai/` 등 아직 없는 앱은 첫 실제 수직 기능의 PR에서 생성합니다. 그 PR은 다음 조건을 충족해야 합니다.

- 이슈의 사용자/API 동작을 실제 진입점에서 실행할 수 있고 필요한 manifest/lock·앱 README·테스트가 함께 있습니다. 빈 폴더, health 응답만 있는 가짜 앱, 구현 예정 stub으로 경로를 선점하지 않습니다.
- 선택한 스택·앱 소유 경계·실행 방법을 기록하고 해당 앱의 실제 실행기를 루트 명령과 CI job/gate에 연결합니다. Java를 선택하면 그 앱의 wrapper를 연결하며 다른 앱 빌드 도구를 바꾸지 않습니다.
- 계약·정상·실패·복구의 완료 기준과 실행 결과를 PR에 남깁니다. 기존 프로토타입 CI만 통과한 것으로 본개발 앱 검증을 대신하지 않습니다.
- 본개발 runtime은 `prototype/`를 dependency로 import하거나 해당 앱/worker DB를 공유하지 않습니다. 코드 채택은 권리·의존성·계약 확인 후 본개발 소유 경로에 구현하고 독립 테스트를 붙입니다.

앱 BE와 AI는 versioned JSON/선택한 transport로 제출·조회·회수하고 서로의 DB를 직접 읽거나 쓰지 않습니다. 비공개 원천 PoC는 독립·읽기 전용으로 유지하며 vendoring하지 않습니다. 이식·writer 전환·롤백은 [마이그레이션 가이드](docs/migration/README.md)를 따릅니다.

## 현재 실행 경로와 루트 명령

이 절의 명령과 도구 버전은 **현재 프로토타입/문서 검사**에 해당하며 미래 앱의 스택을 고정하지 않습니다.

| 경계 | 현재 위치 | 책임 | 루트 명령 |
|---|---|---|---|
| web | `prototype/web` | React/Vite 사용자·관리자 화면 | `make web-install web-typecheck web-test web-build` |
| web 본개발 | `web/` | React 19/Vite 사용자 화면(pnpm 10.34.6, `packageManager` 기준) | `make app-web-install app-web-lint app-web-format-check app-web-build app-web-test` (CI `app-web`) |
| api | `prototype/bff` | FastAPI 프로토타입 BFF, 읽기·세션·작업 consumer | `make bff-install bff-test`, `make bff-build` |
| api 본개발 | `api/` | Spring Boot 실행·공통 오류 기반, 내부 AI transport 클라이언트, 업무 API는 후속 (JDK 21 필요) | `make api-test api-build`, `make service-install api-ai-smoke` (실제 Java→ai/service→zoop-ai replay gate) |
| ai | `ai/worker` | S1 Python CLI JSON worker(공개 의존성만) | `make worker-install worker-test worker-schema-check`, `make worker-build` |
| ai | `ai/pipeline` | 일회성 문서 URL 수집(`zoop-ai-collect`)·S2-1 원문 준비와 네이티브 replay 전용 S2-2/S3/S4·graph·handoff CLI(공개 의존성만, private PoC·토큰 불필요) | `make pipeline-install pipeline-test pipeline-smoke`, `make pipeline-build` |
| ai | `ai/service` | 내부 HTTP transport: S1 분석과 별도 가족의 S2 추출·S3 관계 job(loopback 전용, 공개 의존성만, 설치된 `zoop-ai`·`zoop-ai-extract`·`zoop-ai-relation` CLI만 호출) | `make service-install service-test service-smoke service-openapi-check`, `make service-build`. S2·S3는 설치된 pipeline이 필요한 `make service-pipeline-test service-pipeline-smoke`(없으면 실패) |
| contracts | `docs/api` | **언어와 독립적인 목표 계약** | `make contracts-check docs-check worker-schema-check worker-contracts-check` |
| infra | `.github`, `scripts`, `Makefile` | CI, 로컬 검사, 소스 아티팩트 준비 | `make config-check tooling-test` |

`make help`, `make projects`, `make available-checks`는 루트에서 기존 명령·실제 도구 가용성을 보여 줍니다. 설치 target과 검사 target은 구분합니다. 앱 전체 검사는 각각 독립 실행하며 BFF 서버를 띄워야 웹 테스트가 실행되는 구조가 아닙니다. 본개발 API 실행·환경 준비는 [api/README.md](api/README.md), 프로토타입은 [prototype/README.md](prototype/README.md), 자동화 선행조건은 [GitHub 설정 가이드](docs/development/github-setup.md)에 있습니다.

필수 도구는 Python 3.12 이상, Node.js 22.12 이상, pnpm 11.9.0(`prototype/web`), uv, make입니다. 루트 `web/`은 `web/package.json`의 `packageManager`에 고정된 pnpm 10.34.6을 사용합니다(예: `corepack pnpm@10.34.6`이나 `make app-web-* PNPM="corepack pnpm@10.34.6"`). 본개발 API는 Java 21과 로컬 DB 실행 시 Docker Compose가 필요합니다. `ai/worker`, `ai/pipeline`, `ai/service`는 각자 `uv.lock`과 `.venv`를 가진 독립 프로젝트입니다(`make worker-install`, `make pipeline-install`, `make service-install`; 기본 실행기는 각 `.venv`, `WORKER_PYTHON`/`PIPELINE_PYTHON`/`SERVICE_PYTHON`으로 바꿉니다). BFF가 worker CLI를 호출하므로 `make bff-test` 전에 `make worker-install`이 필요합니다. `ai/service` 시험은 worker를 test 의존성으로 설치하므로 `make service-install`만으로 충분합니다. private PoC 접근 권한이 필요한 것은 BFF뿐이며 `ai/worker`·`ai/pipeline`·`ai/service`는 토큰이 필요 없습니다. 앱 manifest에 자동화용 의존성을 추가하지 않습니다.
`BFF_PYTHON`은 BFF→web 타입 및 worker portable fixture 생성 drift(`worker-contracts-check`, BFF 소유 exporter)에 쓰는 BFF 실행기이고 `WORKER_PYTHON`·`PIPELINE_PYTHON`과 독립적으로 지정할 수 있습니다.

문서/validator 도구가 이미 설치돼 있으면 `CONFIG_PYTHON`, `DOC_PYTHON`, `CONTRACT_PYTHON`, `PUBLIC_PYTHON`에 해당 실행기를 지정합니다. 지정하지 않으면 기존 문서 가이드와 같은 `uv run --no-project --with …` bootstrap을 사용합니다. 개인 캐시 경로를 저장소나 CI에 넣지 않습니다. `make docs-check`와 `make tokens-check`는 임시 디렉터리에서 생성물을 비교하므로 작업 중인 원본을 덮어쓰지 않습니다.

## 작업 범위와 이슈부터 PR까지

1. **범위·출처·이슈:** 본개발/프로토타입/계약/문서 중 어느 작업인지와 실제 변경 경로를 정합니다. [최신 근거](docs/evidence/README.md), [10-12 명세·WBS 갱신](docs/evidence/doc-delta-2026-10-12.md), [현재 결정](docs/share/day-work-2026-10-10.md)을 대조하고 중복 이슈를 검색합니다. Feature/Bug 양식에는 정상·실패·복구 수용 기준과 제외 범위를 적습니다. FS/NFS는 ID·기능명·정의 출처(고정본 파일/시트/행), WBS는 ID·현재 업무명·BE/FE 역할·고정본 출처를 함께 적습니다. 관련 ID가 없으면 사유를 적습니다.
2. **브랜치:** 기존 `feat|fix|docs|chore/<issue>-<slug>` 규칙을 사용합니다. 예를 들어 실제 이슈 #123이 문서 조회 작업일 때 `feat/123-document-view`를 만듭니다. slug는 소문자 kebab-case이며 실제 이슈 번호를 사용합니다. 담당자를 자동 배정하지 않습니다.
3. **계약 변경:** 구현보다 먼저 영향받는 operationId·HTTP/worker schema·권한·오류·저장소 경계를 확인합니다. `docs/api/` 정본을 바꾸고 모든 producer/consumer·생성 타입·fixture·시험을 같은 변경에서 갱신합니다. 현재 `/api`를 목표 `/api/v1`로 별칭만 붙여 완료 처리하지 않습니다.
4. **코드와 검증:** 해당 작업 경로에 실제 동작을 구현합니다. 아래 현재 명령 중 영향받는 검사를 수행합니다. `api/` 기능은 `make api-test api-build`(필요 시 `api-ai-smoke`)를 실행하고 CI job `api`에서 자신의 시험이 실제로 도는지 확인합니다. 다른 본개발 새 앱은 첫 기능 PR에서 runner와 테스트를 추가합니다. 명령·입력·관측 결과·미실행 사유를 기록하며 실제 출처와 합성 fixture, 실제 모델 출력과 replay를 구분합니다.
5. **커밋과 PR:** 아래 제목 형식을 사용하고 PR에 이슈 연결, 변경/제외 범위, 계약·consumer·생성물 영향, 실패·복구·회귀 증거, 미검증 사항과 롤백 절차를 적습니다. 경로별 리뷰 역할을 팀이 확인한 뒤 실제 reviewer를 지정합니다.
6. **merge:** 요구한 CI와 리뷰가 통과하면 `main`에 squash merge하며 PR 제목을 squash 커밋 제목으로 사용합니다. `api/` 최소 기반 PR에서는 로컬 Gradle 테스트·빌드 결과를 별도로 확인하고 기존 CI의 적용 범위를 PR에 명시합니다. 첫 API 업무 기능 PR과 다른 새 앱의 첫 기능 PR에는 해당 앱 runner·테스트·CI 연결이 필요합니다. 필요한 credential trust 승인 없이 기존 검사 성공으로 조건을 대신하지 않습니다. merge와 배포는 별개입니다.

**ID의 숫자는 의미를 보장하지 않습니다.** 10-12 WBS의 AI BE 산출물은 현행 AI v2 번호로 바뀌었지만 일부 FE 산출물에는 옛 번호가 남아 있습니다. 옛 FS046 권한·중복 통제와 현행 FS046 질문 해석을 같은 기능으로 연결하지 않습니다. [상세 정의 권위](docs/system/out/detail-authority.md), [내용 기반 WBS 이행](docs/system/out/wbs-migration.md), [정정 요청](docs/system/out/source-corrections.md)을 확인하고 충돌은 원문을 보존해 설명합니다.

### 브랜치·커밋·PR 제목

기존 Conventional Commits 형식은 `type(scope): 설명`, breaking change는 `type(scope)!: 설명`입니다. scope는 `web`, `api`, `ai`, `contracts`, `docs`, `infra`이고 type은 `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `ci`, `perf`, `revert`입니다. 본개발에서도 현재 검사기와 같은 scope를 사용합니다.

| 작업 예 | 브랜치 예 — 해당 이슈가 실제로 존재할 때 | 커밋·PR 제목 예 |
|---|---|---|
| 문서 조회 | `feat/123-document-view` | `feat(web): 기업 문서 조회 구현` |
| API 부재/장애 구분 | `fix/124-source-unavailable` | `fix(api): 공급자 장애와 정상 자료 부재 구분` |
| 본개발 참여 문서 | `docs/125-production-layout` | `docs(docs): 본개발 경로와 참여 절차 정리` |
| JSON 계약의 비호환 변경 | `feat/126-document-contract` | `feat(contracts)!: 문서 응답 계약 전환` |

PR 제목은 `scripts/repo_checks.py`의 regex로 CI에서 검사합니다. 브랜치명/개별 커밋은 리뷰 규약이며 자동 강제로 표시하지 않습니다. 로컬에서 제목 하나를 확인하려면 아래 기존 검사기를 사용합니다.

```sh
PR_TITLE='docs(docs): 본개발 경로와 참여 절차 정리' python3 scripts/repo_checks.py pr-title
```

추천 main 보호 설정은 [설정 가이드](docs/development/github-setup.md#main-보호-수동-등록)에 있습니다. 문서나 CI 파일이 있다는 사실만으로 GitHub 보호 규칙이 활성화되지는 않습니다.

## 폴더·파일·심볼 이름

기존 파일을 이름 규칙만 맞추려고 일괄 변경하지 않습니다. **아래 본개발 이름은 이번 문서에서 정한 새 기본값**이며 기존 코드는 각 앱의 현재 관례를 우선합니다. 설정·생성물·framework 고정 파일명은 해당 도구 규칙을 따릅니다.

| 대상 | 기존 관례와 본개발 기본값 | 예시 — 실제 파일 생성 선언 아님 |
|---|---|---|
| 일반 기능 폴더·문서 | 소문자 kebab-case. Python/Java package 디렉터리는 언어 규칙을 적용합니다. | `document-analysis/`, `contract-handoff.md` |
| Java | package segment는 소문자, class/interface/record·파일은 PascalCase, method/field는 lowerCamelCase, 상수는 UPPER_SNAKE_CASE입니다. 본개발 API의 조직 prefix는 `com.zoop`, JDK는 21입니다. | `CompanyDocumentResponse.java`, `listCompanyDocuments`, `MAX_BATCH_SIZE` |
| Python | package/module·함수·변수는 snake_case, class는 PascalCase, 상수는 UPPER_SNAKE_CASE입니다. | 현재 `ingestion_contracts.py`, 새 파일 예 `document_analysis.py`, 함수 `list_company_documents` |
| React/TypeScript — 선택할 때 | 컴포넌트·type/interface는 PascalCase, 함수·변수는 lowerCamelCase, hook은 `use` prefix입니다. 현재 프로토타입 파일은 `company-page.tsx`처럼 kebab-case입니다. 새 본개발 컴포넌트 파일 기본값은 PascalCase, hook/일반 모듈 파일은 kebab-case이며 기존 파일을 억지로 바꾸지 않습니다. | `CompanyDocuments.tsx`, `use-company-documents.ts`, `useCompanyDocuments` |
| HTTP 경로 | 정본의 소문자 resource 경로·복수형·kebab-case를 우선하며 목표 prefix는 `/api/v1`입니다. 기존 명시적 action 경로와 path parameter 이름은 계약 변경 없이 고치지 않습니다. | 목표 `GET /api/v1/companies/{id}/documents` |
| DTO·wire | schema 이름은 PascalCase, JSON 필드는 현재 계약의 camelCase를 유지합니다. Python 내부 snake_case와 JSON wire를 혼동하지 않고 DTO와 DB entity를 분리합니다. enum·nullable·ID 의미도 정본을 따릅니다. | `EventSummary`, `relationTypes`, `documentVersion` |
| operationId | 기존 정본의 stable lowerCamelCase 식별자를 유지합니다. 언어별 method 이름이나 framework 자동 생성 이름에 맞춰 바꾸지 않습니다. | `listCompanyDocuments`, `listEvents`, `getEvent` |
| 테스트·생성물 | 선택한 앱의 기존 테스트 탐색·생성기 규칙을 따릅니다. 생성 파일을 수동 이름 변경하거나 확장자 우회로 검사 대상에서 빼지 않습니다. | Python `test_*.py`, web의 기존 `*.test.ts`/`*.test.tsx` |

도메인 `event`(사건), PoC의 `issue`(사건 묶음), `topic`(주제), `document`(원문 자료)는 동의어가 아닙니다. 개발 업무 추적은 “GitHub 이슈”로 구분합니다. 기존 graph `kind=issue`나 `issueId`를 `topicId`로 이름만 바꾸지 않으며, 의미가 바뀌면 schema version·모든 caller·fixture를 함께 이행합니다. 근거와 상세 차이는 [계약 인계](docs/migration/contract-handoff.md#1-언어-독립-불변식)를 따릅니다.

## 계약·생성물·권한

- `docs/api/openapi.yaml`은 목표 계약 정본이고 현재 BFF `/openapi.json`은 구현 관측본입니다. `prototype/web/src/api/schema.d.ts`는 현재 BFF에서 생성하는 타입이며 목표 계약으로 무조건 대체하지 않습니다.
- BFF 생성 web 타입은 `make bff-types-check`로 검사합니다. 설치된 BFF Python과 web 도구가 필요한 cross-app seam이며 실제 서버·사용자 상태 없이 합성 snapshot과 temp state에서 비교합니다.
- API를 바꾸면 BFF consumer, web fixture/타입/시험, worker JSON 계약의 영향을 함께 검토합니다. 현재 CI는 프로토타입 앱, 문서/계약, `ai/`, `api/`(CI `api`·`api-postgres`·`api-ai-smoke`·`api-graph-smoke`, 토큰 없음, JDK 21), 루트 `web/`(CI `app-web`, 토큰 없음: frozen 설치·lint·format check·build·Vitest)을 검사하며 `contracts/`의 본개발 runner는 아직 구성하지 않았습니다. `ai/`는 `ai/worker`(CI `ai-worker`, 토큰 없음), `ai/pipeline`(CI `ai-pipeline`: 공개 의존성만, 토큰 없음), `ai/service`(CI `ai-service`, 토큰 없음, 로컬 준비 상태)로 구성돼 있습니다. 내부 HTTP 계약 `docs/api/internal-ai-openapi.{json,yaml}`은 `make service-openapi-check`가 생성 drift를 막으므로 손으로 고치지 않습니다. 다른 새 앱도 첫 기능 PR에서 runner를 연결합니다. 기존 `web`/`bff` CI job은 `prototype/`만 검사하므로 그 성공은 루트 `web/`이나 새 앱의 성공이 아닙니다.
- 토큰 원본은 `docs/design/tokens.json`입니다. `pnpm --dir prototype/web tokens`로 CSS/TS를 재생성합니다. 문서 생성 원본·명령은 [docs/system/README.md](docs/system/README.md)를 따릅니다.
- 문서 검사는 **hard error 0 + XLSX readback passed + 생성물 drift 없음**을 요구합니다. 원문 경고·팀 미결정·목표/BFF 차이는 숨기지 않으며 `build.py --check`의 종료 1을 무조건 구현 실패로 보지 않습니다.
- `.env`, 키, 인증 헤더, DB, 개인 기록, 사용자 로그는 커밋·이슈·PR·아티팩트에 넣지 않습니다. 실제 secret 파일을 검사 목적으로 열지 않습니다. 합성 최소 입력으로 재현합니다.
- 뉴스·문서·그림·폰트·패키지의 라이선스/사용 권한을 기록합니다. 판정 확률을 감성 또는 가격 예측으로 해석하지 않습니다. 모델 설정과 **실제 유료 호출 승인**은 별개입니다. CI는 모델 키나 실제 외부 데이터를 전달하지 않습니다.
- `make secret-check`는 추적 파일과 `.gitignore`에 제외되지 않은 새 파일의 민감한 파일명·알려진 credential signature를 검사합니다. 실제 `.env`·키·DB 파일은 이름에서 먼저 차단하고 내용을 읽지 않습니다. 값을 출력하지 않으며 전체 보안 감사·Git 이력 검사·모든 secret 탐지를 보장하지 않습니다. 유출 발견 시 값은 붙이지 말고 관리자의 비공개 채널로 알리고 폐기/회전합니다.
- CI의 App key/token은 same-repository PR 작성자로부터 격리되지 않습니다. main 승인/CODEOWNERS는 PR 실행 전 접근을 막지 않으므로 [credential trust 선행 승인](docs/development/github-setup.md#private-poc-읽기-등록) 없이 secrets를 등록하거나 해당 원격 CI를 활성화하지 않습니다.

## 경로별 리뷰 책임 (실제 handles 등록 전)

| 경로 | 확인할 리뷰 역할 | 필요한 검토 |
|---|---|---|
| `web/**` — 생성 시, `prototype/web/**` | 프론트엔드 담당 | 접근성, 실패·복구, fixture와 실제 데이터 구분, 새 앱 runner |
| `api/**` — 생성 시, `prototype/bff/**` | API/백엔드 담당 | 인증·상태·작업 consumer·private PoC 경계, 앱 저장소 독립성 |
| `ai/**` | AI/파이프라인 담당 | versioned JSON 계약, 재실행·취소, 출처·호출 승인, 자체 저장소 |
| `docs/api/**`, `docs/system/**`, `contracts/**` — 생성 시 | 계약 담당 + 영향을 받는 앱 담당 | 단일 정본, 생성물 소유권, 목표/관측 구분, 추적 ID 의미, 전체 consumer |
| `.github/**`, `scripts/**`, `Makefile`, `infra/**` — 생성 시 | 저장소 관리자/자동화·인프라 담당 | 실제 runner·권한·secret 범위·검사 gate·allowlist, 별도 배포 승인 |
| `docs/**` | 해당 근거/명세 담당 | 출처, 권리, 현재 결정과 원문 충돌 |

실제 GitHub 사용자/팀 handles와 write 권한이 확정되지 않아 `CODEOWNERS`는 만들지 않습니다. 관리자가 위 역할에 실제 조직 팀/사용자를 매핑하고 팀 접근 권한을 확인한 뒤 파일과 “Require review from Code Owners”를 함께 등록합니다. 빈 파일이나 가짜 owner로 등록 완료를 대신하지 않습니다.
