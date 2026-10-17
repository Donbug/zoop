# GitHub·모노레포 준비와 수동 등록

이 문서는 CI·모노레포 준비와 원격 등록 절차를 설명합니다. **2026-10-12 사용자 승인으로 private PoC용 전용 App 생성·설치와 Actions 인증 등록을 완료했고, 아래 실행에서 전체 CI 통과를 확인했습니다.** branch protection·배포·production environment 등록은 별도 범위이며 수행하지 않았습니다. 현재 소스는 이동하지 않으며 본개발 스택을 확정하지 않습니다.

## 최신 인증 등록·실행 확인 — 2026-10-12

- 조직 소유 App: `Donbug Zoop CI Reader`, App ID `5281522`. 설치 대상은 `Donbug/investmate-poc` 한 곳이며 Contents·Metadata 읽기 전용입니다.
- `Donbug/zoop` Actions 변수 `POC_APP_ID`와 시크릿 `POC_APP_PRIVATE_KEY`의 등록을 확인했습니다. private key는 사용자가 직접 발급·입력했으며 작업자는 값·PEM·토큰을 읽거나 저장하지 않았습니다.
- 커밋 `a41aee625269b24dfa7d1183a072018bcc16496b`의 [CI 재실행](https://github.com/Donbug/zoop/actions/runs/38203426877)에서 **public-config / web / ai-worker / bff / required-ci 모두 success**를 확인했습니다.
- BFF의 App 토큰 발급, 고정 private PoC 의존성 설치, 오프라인 시험, worker 계약·BFF 생성 타입 drift 검사까지 실제 실행됐습니다. 이전의 자격 증명 미등록 차단은 해소됐습니다.
- 아래 과거 실행 기록의 미등록/실패는 당시 상태입니다. 이번 성공은 해당 커밋의 CI 증거이며 운영 배포·실공급자·유료 모델·새 본개발 앱의 완료를 뜻하지 않습니다. App 키 보관·회전 책임은 운영 인계에서 명시적으로 관리해야 합니다.

## 로컬 진입점

저장소 루트에서 실행합니다. `make help`, `make projects`, `make available-checks`는 설치나 실제 `.env` 조회 없이 현재 경계·명령·도구 가용성을 보여 줍니다.

```sh
make help projects available-checks
make tooling-test
make config-check
make contracts-check docs-check tokens-check
make secret-check

# 프로토타입 프론트엔드(prototype/web)만 설치·검사·빌드
make web-install web-typecheck web-test web-build
# 본개발 프론트엔드(루트 web/, pnpm 10.34.6)만 설치·lint·format·빌드·시험
make app-web-install app-web-lint app-web-format-check app-web-build app-web-test
# BFF만 설치·시험 또는 wheel 빌드
make bff-install bff-test
make bff-build
# S1 worker 자체 locked 환경 설치·시험·schema drift (공개 의존성만)
make worker-install worker-test worker-schema-check
make worker-build
# 수집·S2-1·S2-2·S3·S4·graph·handoff 전체 pipeline (네이티브 replay 전용, 공개 의존성만, private PoC·토큰 불필요)
make pipeline-install pipeline-test pipeline-smoke
make pipeline-build
# S1 내부 HTTP transport (loopback 전용, 공개 의존성만; 설치된 zoop-ai를 test 의존성으로 사용)
make service-install service-test service-smoke service-openapi-check
make service-build
# Spring Boot 앱 (JDK 21 필요: JAVA_HOME). api-ai-smoke는 위 service-install이 먼저 필요하며 모델·토큰 없이 replay만 쓴다
make api-test api-build api-ai-smoke
# BFF 소유 fixture exporter의 생성 drift (설치된 BFF 환경 + worker 설치 필요)
make worker-contracts-check BFF_PYTHON=prototype/bff/.venv/bin/python
```

웹에는 앱 자신의 `package.json`과 `pnpm-lock.yaml`, BFF에는 `pyproject.toml`과 고정 PoC revision을 가진 `uv.lock`, `ai/worker`와 `ai/pipeline`에는 각자의 `pyproject.toml`과 `uv.lock`이 있습니다. worker runtime과 pytest dev 도구는 manifest에서 exact version을 선언하고 CI에서 `uv sync --frozen --group dev`로 설치하며 `zoop-ai` 콘솔 명령까지 설치합니다. worker 시험은 worker 전용 `.venv`를 사용하며 private PoC가 필요하지 않습니다. `ai/pipeline`은 BFF와 같은 고정 PoC revision을 쓰므로 private 설치가 필요하고 worker는 dev 그룹의 테스트 의존성으로만 설치합니다(런타임 import 없음). BFF도 dev 그룹에 worker를 테스트 의존성으로 가지며 실제 호출은 설치된 `ai/worker/.venv/bin/zoop-ai`로만 합니다. BFF 시험은 `--no-sync`로 설치 단계와 분리하며 private 의존성을 못 받았을 때 검사를 건너뛰어 green으로 만들지 않습니다. wheel build는 배포나 운영 가동 검증이 아닙니다.

문서 도구는 기존 문서 체계의 PyYAML/openpyxl/OpenAPI validator를 사용합니다. manifest/lock에는 새 의존성을 추가하지 않습니다. CI bootstrap은 `uv run --no-project --with pyyaml --with openpyxl --with openapi-spec-validator …`로 runner에만 도구를 준비합니다. 기존 로컬 환경을 그대로 쓰려면 다음 override를 지정합니다. 아래 값은 자신의 이미 설치된 실행기 경로이며 새로 설치하는 명령이 아닙니다.

```sh
make config-check CONFIG_PYTHON="$EXISTING_DOC_PYTHON"
make docs-check DOC_PYTHON="$EXISTING_DOC_PYTHON"
make contracts-check CONTRACT_PYTHON="$EXISTING_VALIDATOR_PYTHON"
```

`docs-check`는 source fingerprints·catalog를 재추출하고 **임시 디렉터리**에서 생성기를 실행합니다. hard error 또는 XLSX readback 실패, catalog/Markdown/JSON/XLSX 셀 drift는 실패입니다. 원문 경고와 목표/BFF 차이는 보존합니다. XLSX ZIP 시간·문서 관측 timestamp만으로 항상 실패하지 않도록 XLSX는 셀 값, BFF는 저장된 관측본을 비교에 사용합니다. 새 서버를 켜거나 `/openapi.json`을 자동 조회하지 않습니다.

`make bff-types-check`는 별도 BFF/web 계약 seam입니다. 설치된 BFF Python과 web의 기존 `openapi-typescript`가 필요합니다. factory를 합성 snapshot, temp state, company catalog 없음, scheduler/quote/metrics off 설정으로 만들고 lifespan/HTTP 서버 없이 `.openapi()`를 export합니다. 상속된 모델/secret 환경은 전달하지 않습니다. temp `.d.ts`를 현재 web 타입과 비교하고 원본은 쓰지 않습니다. `schema.d.ts`는 목표 계약이 아니라 현재 BFF 관측에서 재생성합니다. 앱 단독 `bff-build`/`web-build`는 이 cross-app check와 독립입니다.

## CI 경계

runner는 `ubuntu-24.04`로 명시합니다. 공식 [runner image 도구 목록](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)의 Bash/Git/Go/Python/Node를 기준으로 하며 Node/Python/pnpm/uv는 고정 action으로 준비합니다. actionlint는 runner Go에서 bootstrap합니다. 로컬에 actionlint가 없거나 offline Go cache가 없으면 미검증으로 보고하며 CI gate는 제거하지 않습니다.

`.github/workflows/ci.yml`은 `main` push, PR, 수동 실행을 받습니다. 현재는 dependency 없는 증분 path selector를 도입하지 않고 **항상 전체 경계**를 검사합니다. 따라서 API 변경은 계약+BFF+web fixture+worker 시험 범위에 모두 들어갑니다.

| Job/check 이름 | 실제 동작 | private PoC token 필요 |
|---|---|---|
| `public-config` | actionlint, YAML/issue form/action inputs/Bash syntax, JSON/JSON Schema/OpenAPI와 합성 계약 표본의 표준 format 검증, 문서·토큰 생성 drift, 추적·비제외 신규 파일의 secret signature, tooling 시험, PR 제목 | 없음 |
| `web` | `prototype/web`의 frozen pnpm 설치, typecheck, Vitest, Vite build | 없음 |
| `app-web` | 루트 `web/`의 frozen pnpm 10.34.6 설치(`HUSKY=0`으로 git hook 설치 생략), ESLint, Prettier check, `tsc -b` + Vite build, Vitest | 없음 |
| `bff` | App 등록 preflight, private pinned PoC 설치, worker 설치(토큰 없음), offline pytest, worker portable fixture 및 BFF→web type 생성 drift | 필요 |
| `ai-pipeline` | 공개 의존성만 `make pipeline-install`(private Git 접근·App token 없음)로 설치한 환경에서 offline pytest 전체와 collection/ingestion/extraction/relation/dependents/handoff 실제 CLI smoke(`make pipeline-test pipeline-smoke`). 이 환경에는 `investmate`가 설치되지 않으며 시험은 PoC import를 막은 자식 프로세스에서도 모든 pipeline 모듈·명령이 동작함을 확인한다. 이 job의 success는 `required-ci`와 릴리스 게이트(`scripts/require_ci.py`의 `REQUIRED_JOBS`)가 요구하고, 브랜치 보호의 required status check 등록은 관리자의 수동 항목이다. 이전의 별도 `ai-pipeline-public` job과 `pipeline-public-*` target은 이 job으로 합쳐 제거했다 | 없음 |
| `ai-worker` | worker 자신의 manifest 설치, offline pytest, S1 schema drift, stdlib portable fixture validation | 없음 |
| `ai-service` | service 자신의 manifest 설치(worker는 test 의존성), offline pytest(실제 uvicorn+설치된 `zoop-ai`+authored replay), 실제 loopback smoke, 내부 OpenAPI drift. 로컬 준비 상태이며 배포 승인이 아니다 | 없음 |
| `api` | 러너의 JDK 21(`JAVA_HOME_21_X64`, 없으면 실패), `make api-test api-build`(foundation + AI 클라이언트 시험, DB·Python 불필요), `make service-install`, `make api-ai-smoke`(실제 Java→uvicorn ai/service→설치된 zoop-ai replay, 합성 인메모리 토큰, 모델 호출 0). 로컬 준비 상태이며 배포 승인이 아니다 | 없음 |
| `required-ci` | 위 여덟 job이 모두 success인지 확인; skipped/cancelled/failure도 실패 | 없음 |

2026-10-12 읽기 전용 원격 관측: [`6272d3c7a7f7128bb8260e54a98c488f4f44bca8`의 CI 실행](https://github.com/Donbug/zoop/actions/runs/38193448624)은 main push의 completed/failure입니다. **public-config / web / ai-worker는 success**, **bff / required-ci는 failure**였습니다. BFF의 private PoC 등록 preflight가 실패했고 App token 발급·의존성 설치·BFF 시험은 skipped였습니다. 같은 조회에서 repository Actions secrets와 variables는 각각 이름 목록이 비어 있었습니다. 조직에서 상속되는 항목은 조회하지 않았습니다. 따라서 **전체 CI 통과·배포 완료는 아닙니다**. 이 원격 실행은 해당 SHA의 증거이며 이후 미커밋 변경을 검증하지 않습니다. 자격 증명이나 저장소 규칙을 자동 등록하지 않았습니다.

기본 권한은 `contents: read`이고 checkout 인증을 남기지 않습니다. artifact job만 CI 증거 읽기를 위해 `actions: read`를 추가합니다. `pull_request_target`, untrusted privileged checkout, 모델 키, 자동 LLM 호출, 실제 외부 뉴스·시세·DB 조회를 사용하지 않습니다. 설치 도구·패키지·고정 private 의존성 fetch와 CI 증거 GitHub REST GET은 검증 bootstrap이며 데이터 분석 실행이 아닙니다. private token은 의존성 설치 step에만 전달하고 테스트 step에는 전달하지 않습니다. 캐시도 private dependency 공유를 피하려고 끕니다.

`worker-schema-check`는 worker 소유 `ai/worker/scripts/export_schema.py`를 임시 디렉터리에서 실행해 `docs/api/ai-contract.schema.json`을 바이트 비교하며 private PoC 없이 `ai-worker` job에서 돕니다. `worker-contracts-check`는 BFF 소유 `prototype/bff/scripts/export_contracts.py`를 임시 디렉터리에서 실행해 두 합성 fixture 그룹(`synthetic-document`, `synthetic-outlook`)의 `jobs.json`, `grants.json`, `replay.json`, `snapshot.json` **총 8개**를 바이트 비교합니다. 생성한 정확한 파일 경로 집합도 검사하므로 파일 수만 맞추거나 예상하지 않은 출력을 무시해 통과시키지 않습니다. exporter는 BFF의 `evidence_id`, private PoC의 Article 버전 규칙과 회차 입력 생성도 사용하므로 이 **fixture 생성 drift만 BFF job**에 둡니다. worker 실행·시험과 stdlib portable fixture validator는 private PoC 없이 독립 실행합니다. exporter에는 모델 키/설정을 상속하지 않으며 원본 fixture를 덮어쓰지 않습니다.

`contracts-check`는 별도로 표준 JSON Schema validator와 format checker를 사용해 worker 입력·grant·응답 표본 16개를 검증합니다. `*.schema.json`만 스키마 정의로 검사하고, 디자인 토큰처럼 `$schema`로 형식을 가리키는 데이터 문서를 스키마 정의로 오인하지 않습니다. worker의 무의존성 부분집합 검사와 전체 표준 검사를 구분합니다.

Fork PR은 private credential을 받을 수 없으므로 `bff` preflight가 명확히 실패합니다. `ai-pipeline`도 같은 이유로 실패합니다. 나머지 public-config/web/ai-worker는 독립 실행 가능합니다. fork 전체 CI가 통과했다고 표시하지 않습니다. 관리자가 기여 내용을 검토한 뒤 신뢰할 수 있는 same-repository branch/PR로 옮겨 전체 CI를 수행합니다. 승인 없는 fork 코드를 secret이 있는 trigger로 우회 실행하지 않습니다. 같은 저장소 PR도 secret 접근 가능한 trusted collaborator만 작성하도록 접근 권한을 관리합니다.

**필수 선행 결정:** same-repository PR 작성자는 PR의 workflow와 실행 스크립트를 바꿀 수 있으므로 현재 구조에서는 App installation token뿐 아니라 repository secret에 둔 App private key에도 접근할 수 있습니다. 위의 step별 환경 범위·token revoke·로그 마스킹은 정상 workflow의 노출을 줄이는 조치이며 악의적인 PR 작성자를 격리하는 장치가 아닙니다. `main`의 PR 승인, branch protection, CODEOWNERS 리뷰는 **PR workflow 실행 전 credential 접근을 차단하지 않습니다.**

### Private PoC 읽기 등록

자동화가 의존하는 저장소는 `Donbug/investmate-poc`이며 BFF manifest/lock에 고정된 revision을 사용합니다. 저장소의 기본 `GITHUB_TOKEN`은 다른 private 저장소 읽기를 자동으로 허용하지 않습니다. 값을 이슈나 로그에 붙이지 마세요.

**2026-10-12 사용자 trust 승인:** 사용자는 현재 `Donbug/zoop`의 same-repository PR 작성·설정 변경이 가능한 admin **`jhh6079`, `SJY051`, `sebinJeong`, `GgaGGa0302`, `limhyun0319`, `KIM-korea`, `david3123123` 전원**에게 private PoC 내용과 **CI App private key 및 installation token 접근을 명시적으로 허용**했습니다. 이 승인은 **Donbug 소유 CI 전용 App 준비**, 설치 대상 **`Donbug/investmate-poc` 하나**, **Contents/Metadata Read-only**, 등록 destination **`Donbug/zoop`의 `POC_APP_ID` Actions variable와 `POC_APP_PRIVATE_KEY` repository secret**에 연결합니다. 다른 저장소·권한·새 PR 작성자는 승인 범위에 포함하지 않습니다.

**준비 승인과 실제 등록은 구분합니다.** 위 사용자 답변은 trust 결정과 전용 App 준비를 승인했으며 실제 App 생성·설치·key 발급·secret/variable 등록·CI 재실행은 실행하지 않았고 별도 승인 전 수행하지 않습니다. App 등록·key 보관·접근 회수·회전 담당 GitHub handle은 남은 수동 입력 항목입니다. 담당 미지정은 로컬 구현을 막지 않지만 사람이 외부 등록할 때 지정해야 합니다. LLM/AWS 키·배포 권한은 CI App과 분리합니다.

관리자는 등록 직전 현재 handles가 승인 목록과 일치하는지 확인하고 변경된 사용자/팀은 재승인받습니다. 한 명이라도 trust 범위에 포함할 수 없다면 credential을 격리하는 별도 workflow 설계를 먼저 결정합니다. environment 이름만 붙였다고 격리가 성립하지 않으며 실제 protection·secret scope·승인 시점·checkout/실행 신뢰 경계를 검증해야 합니다. workflow의 token 범위 제한만 믿고 더 넓은 App의 key를 재사용하지 않습니다. private key 접근자는 App이 허용한 다른 설치/권한으로도 token을 발급할 수 있으므로 App 자체의 권한·설치를 제한합니다.

관리자가 직접 수행할 절차 — **각 대상의 실제 외부 쓰기와 CI 실행을 별도 승인받은 뒤에만** 진행합니다:

0. 위 일자·handles·trust 범위를 확인하고 App 등록·key 보관/회수·회전 담당을 지정합니다. main merge 승인이나 CODEOWNERS로 key 접근 trust를 대신하지 않습니다.
1. **Donbug 전용 App 생성 승인 후:** GitHub profile → Your organizations → Donbug **Settings → Developer settings → GitHub Apps → New GitHub App**으로 이동합니다. 고유한 CI 전용 이름과 공개 homepage URL을 지정하고 webhook **Active**를 끕니다. 사용자 OAuth/callback/device flow는 사용하지 않습니다. **Repository permissions → Contents: Read-only**, 필수 **Metadata: Read-only**만 허용하고 나머지 repository/organization/account 권한은 부여하지 않습니다. 설치 범위는 **Only on this account**, 이후 **Create GitHub App**입니다.
2. **설치 승인 후:** 해당 App의 **Edit → Install App → Donbug의 Install → Only select repositories → investmate-poc → Install**로 설치합니다. All repositories나 zoop는 선택하지 않습니다. 조직 정책의 승인 대기는 완료까지 기다립니다.
3. **Donbug/zoop variable 등록 승인 후:** App settings의 숫자 **App ID**를 확인합니다. Client ID나 installation ID가 아닙니다. `Donbug/zoop`의 **Settings → Secrets and variables → Actions → Variables → New repository variable**에서 Name `POC_APP_ID`, 해당 App ID를 입력하고 **Add variable**을 누릅니다.
4. **key 발급·Donbug/zoop secret 등록 승인 후:** 해당 App의 **Edit → Credentials → Key pairs → New key**에서 사람이 PEM을 발급합니다. `Donbug/zoop`의 **Settings → Secrets and variables → Actions → Secrets → New repository secret**에서 Name `POC_APP_PRIVATE_KEY`, PEM을 입력하고 **Add secret**을 누릅니다. 키는 agent/chat/이슈/저장소 파일/실제 `.env`/CI 출력으로 전달하지 않습니다. private key는 자동 만료되지 않으므로 승인된 보관·회전·폐기 방식을 기록합니다.
5. Actions 사용 정책에서 아래 고정 action들과 runner bootstrap 통신이 허용되는지 확인합니다. 정책 변경이 필요하면 별도 승인받으며 민감한 자격 증명을 전달하는 Actions debug 로그를 켜지 않습니다.
6. **CI 실행 승인 후:** 승인된 main의 **Actions → CI → Run workflow**를 사용하거나 해당 SHA의 실패 run을 재실행합니다. `bff` preflight 이후 App token 발급·private 고정 커밋 fetch·BFF 시험 진입을 확인하고 **public-config/web/app-web/bff/ai-pipeline/ai-worker/ai-service/api/required-ci 전부 success**를 같은 SHA/run/attempt로 기록합니다. 실패하면 설치 범위·Contents 권한·조직 승인·revision 존재를 확인하며 skip/continue-on-error로 성공 처리하지 않습니다.
7. fork PR과 App 미등록 상태의 전체 CI는 성공으로 주장하지 않습니다. 해당 실패 분기 검증도 별도 승인된 실행에서 확인하고 CI 링크를 팀에 기록합니다. 노출/회수 시 repository secret 삭제만으로 유출된 key가 무효화되지는 않으므로 담당자가 대상별 승인 후 App key 삭제/회전 및 필요한 installation 중단을 수행합니다.

`scripts/private_poc_sync.py`는 토큰을 command line/remote URL/git config에 넣지 않습니다. 임시 askpass helper는 환경에서만 읽고 preflight stderr/토큰을 출력하지 않으며 작업 종료 시 삭제합니다. App token은 action의 post step에서 revoke됩니다. 로컬 사용자는 기존 [프로토타입 실행 가이드](../../prototype/README.md)의 조직 인증 절차를 사용하며 이 CI용 secret을 개인 환경으로 복사하지 않습니다.

## main 보호 수동 등록

아래는 **추천 설정이며 미등록**입니다. 저장소 관리자와 실제 reviewer handles가 정해진 뒤 Settings에서 직접 적용합니다.

1. **Settings → General → Pull Requests**: Allow squash merging을 켜고 merge/rebase merge는 팀 규약에 맞춰 끕니다. squash 기본 제목은 PR title로 설정합니다. Automatically delete head branches는 팀 정책에 따라 켭니다.
2. **Settings → Rules → Rulesets → New branch ruleset**: 대상은 기본 branch 또는 `main`, enforcement는 Active로 설정합니다. GitHub 플랜/권한에 따라 같은 기능의 Branch protection을 사용합니다.
3. Require a pull request before merging, 최소 승인 1명, stale approvals dismiss, 모든 review conversation 해결을 요구합니다. 마지막 push에 대한 별도 승인 옵션도 권장합니다.
4. Require status checks before merging에 **`public-config`, `web`, `app-web`, `bff`, `ai-pipeline`, `ai-worker`, `ai-service`, `api`, `required-ci`**를 등록하고 branch 최신화 요구를 켭니다. 체크가 목록에 나타나려면 먼저 원격 CI를 한 번 실행해야 합니다. 명명 충돌 시 GitHub Actions 출처와 실제 관측한 context를 확인합니다.
5. Block force pushes, restrict deletions, require linear history를 설정합니다. 관리자 우회는 사고 대응 계정/역할만 승인하고 우회 사용을 기록합니다. 검증 우회를 일상 merge 절차로 사용하지 않습니다.
6. PR title 검사 실패·private preflight 실패·skipped job이 merge를 막는지 테스트 PR로 확인합니다. 규칙 등록만으로 효과를 주장하지 않습니다.
7. [CONTRIBUTING 경로별 리뷰 표](../../CONTRIBUTING.md#경로별-리뷰-책임-실제-handles-등록-전)에 실제 GitHub 팀/사용자를 매핑합니다. write 접근과 해당 경로 review 책임을 확인한 후 `.github/CODEOWNERS`를 만들고 Require review from Code Owners를 켭니다. 실제 handles 미정 상태에는 빈/가짜 파일을 만들지 않습니다.

브랜치 규약은 `feat|fix|docs|chore/<issue>-<slug>`, Conventional Commits scope는 `web/api/ai/contracts/docs/infra`입니다. 규약·issue/PR 수용 기준은 [CONTRIBUTING.md](../../CONTRIBUTING.md)에 있습니다. issue assignee/label/organization issue type은 팀이 실재 값을 등록한 뒤 지정합니다.

## release-artifacts는 배포가 아닙니다

배포 대상과 클라우드 권한이 미정이므로 CD deployment job, production 환경, 가짜 deploy 성공 step을 만들지 않습니다. `.github/workflows/release-artifacts.yml`은 `workflow_dispatch`만 받으며 **main만** 허용합니다.

1. dispatch 시 GitHub가 정한 `github.sha`를 checkout합니다. 사용자가 넘긴 임의 ref/쉘 입력을 받지 않습니다.
2. GitHub REST API에서 **동일 main SHA의 최신 CI push run**이 완료·success인지 확인합니다. 다른 커밋/PR run/다른 workflow, 과거 성공 뒤 최신 실패·진행 중 run은 인정하지 않습니다. 해당 attempt의 `public-config/web/app-web/bff/ai-pipeline/ai-worker/ai-service/api/required-ci`가 모두 success여야 합니다.
3. 동일 커밋의 web을 frozen install/build합니다. CI 증거가 없으면 source-only 아티팩트로 우회하지 않습니다.
4. allowlist로 prototype 소스·web dist·앱 manifest/lock·목표 OpenAPI·AI JSON Schema·토큰 원본만 ZIP에 담고 각 파일과 ZIP/manifest의 SHA-256을 생성합니다. `manifest.json`에 commit과 CI run ID를 기록합니다.
5. 해당 ZIP, `manifest.json`, `SHA256SUMS`만 Actions artifact에 14일 보관합니다. cloud upload/deploy, GitHub Release 발행, DB migration, runtime 가동은 수행하지 않습니다.

실제 릴리스 선택·F03/F05 API/UI 장애 사례·F06 설정 이행·F07 경로와 WBS 6.11.*의 인수 기준은 [배포·성능·장애 검증 계획](release-verification.md)에 있습니다. 현재 릴리스 후보나 운영 배포가 선택/완료됐다는 뜻은 아닙니다.

로컬 패키징도 실제 web build가 이미 있어야 하며 git SHA를 명시합니다. 패키징은 repo 외부 디렉터리에만 씁니다.

```sh
make package-artifacts COMMIT=<full-40-character-sha> ARTIFACT_DIR=/tmp/zoop-release-artifacts
```

allowlist는 `scripts/package_artifacts.py`의 `FILES/TREES/REQUIRED`입니다. 디렉터리 전체를 무조건 복사하지 않고 경로+확장자를 허용합니다. `.env` 및 `.env.*`(example 포함), dot directories, var/state DB, recordings/private, logs, node_modules/cache, symlinks, 키 파일, sourcemap은 제외합니다. fixture 데이터는 포함하지 않으며 운영 데이터·PoC 소스·venv도 담지 않습니다. 따라서 이것은 바로 기동하는 배포 패키지가 아닙니다. 실행에 필요한 데이터·설정·서비스는 배포 설계에서 별도로 승인·공급해야 합니다. 실제 출처 JSON을 합성 데이터라고 바꿔 담지 않습니다.

`make tooling-test`는 임시 fixture에서만 의도적인 합성 `.env`/DB/key/log/recording/cache 파일을 만들고 실제 ZIP entries·checksum·CI gate 실패 조건을 검사합니다. 실제 `.env`는 읽거나 복사하지 않습니다. 임시 fixture/artifact는 종료 시 삭제합니다.

### 배포 설계가 확정된 뒤 직접 등록할 항목

- [ ] 팀이 FE/BE/AI 확정 스택, 배포 대상 계정·지역·서비스, 도메인/TLS, 산출물 형태를 결정하고 기록합니다.
- [ ] 데이터/뉴스 사용 권한, 실제·합성 출처 표시, 모델 전송·예산 승인, 보존·파기 정책을 결정합니다.
- [ ] DB·상태 저장·migration·backup/restore, rollback 순서와 담당자, health/readiness 판정과 smoke 입력을 확정합니다.
- [ ] 배포용 GitHub App 또는 cloud OIDC trust에 저장소·branch·environment와 최소 권한을 명시합니다. CI private PoC App에 배포 권한을 추가하지 않습니다.
- [ ] **Settings → Environments → New environment → production**을 만든 뒤 실제 required reviewer, prevent self-review, 승인 branch/tag(main), environment-scoped secrets/variables를 등록합니다. 플랜의 protection 지원 여부도 확인합니다.
- [ ] 실재 대상에 동작하는 deployment workflow와 artifact SHA/checksum 검증, migration, health/smoke, 실패/rollback 처리를 구현하고 이슈/PR 수용 기준에 연결합니다. 환경 protection 승인 전 deployment 권한을 사용하지 않습니다.
- [ ] 승인된 테스트 대상에서 실패·복구까지 검증하고 원격 실행 URL과 배포 commit을 기록한 뒤 운영 승인합니다.

## Action pin과 1차 근거

2026-10-08에 공식 저장소 `git ls-remote`로 tag와 **annotated tag의 dereferenced commit**을 확인했습니다. workflow는 움직이는 tag/tag object가 아니라 다음 commit SHA를 사용합니다. 입력은 해당 revision의 `action.yml`로 확인했습니다.

| Action | Tag | 고정 commit / 공식 manifest |
|---|---|---|
| checkout | v5 | [fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09](https://github.com/actions/checkout/blob/fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09/action.yml) |
| setup-node | v4 | [49933ea5288caeca8642d1e84afbd3f7d6820020](https://github.com/actions/setup-node/blob/49933ea5288caeca8642d1e84afbd3f7d6820020/action.yml) |
| setup-python | v5 | [a26af69be951a213d495a4c3e4e4022e16d87065](https://github.com/actions/setup-python/blob/a26af69be951a213d495a4c3e4e4022e16d87065/action.yml) |
| upload-artifact | v4 | [ea165f8d65b6e75b540449e92b4886f43607fa02](https://github.com/actions/upload-artifact/blob/ea165f8d65b6e75b540449e92b4886f43607fa02/action.yml) |
| create-github-app-token | v2 | [fee1f7d63c2ff003460e3d139729b119787bc349](https://github.com/actions/create-github-app-token/blob/fee1f7d63c2ff003460e3d139729b119787bc349/action.yml) |
| setup-uv | v6 | [d0cc045d04ccac9d8b7881df0226f9e82c39688e](https://github.com/astral-sh/setup-uv/blob/d0cc045d04ccac9d8b7881df0226f9e82c39688e/action.yml) |
| pnpm/action-setup | v4 | [b906affcce14559ad1aafd4ab0e942779e9f58b1](https://github.com/pnpm/action-setup/blob/b906affcce14559ad1aafd4ab0e942779e9f58b1/action.yml) |

pin 갱신 시 공식 tag의 commit, 해당 manifest inputs/runtime, runner 호환성, 변경 내역을 다시 확인하고 workflow와 `scripts/repo_checks.py`의 curated pin/input 목록을 함께 바꿉니다. actionlint는 runner의 Go 도구로 **v1.7.7**을 실행하며 앱 의존성에 넣지 않습니다. 로컬 Go bootstrap은 팀 정책에 따라 허용될 때만 실행합니다.

- [GitHub issue form syntax](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)
- [GitHub App installation token](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)
- [GitHub App 등록](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app), [설치](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app), [private key 관리](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps): 위 수동 UI 경로는 2026-10-12 공식 문서 조회 기준입니다.
- [Actions repository secret 등록](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets), [repository variable 등록](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-variables)
- [GitHub workflow run REST API](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow)
- [GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [GitHub deployment environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)
- [actionlint installation](https://github.com/rhysd/actionlint/blob/v1.7.7/docs/install.md)
