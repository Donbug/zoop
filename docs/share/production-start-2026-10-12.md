# 본개발 시작 안내 · 2026-10-12

**본개발은 저장소 루트의 `web/`, `api/`, `ai/`, `contracts/`, `infra/`를 사용합니다.** `api/`에는 Spring Boot 실행·공통 오류 기반을 먼저 만들었습니다. 업무 API는 아직 없으며 실제 기능을 실행할 수 있는 코드는 `prototype/`에 있습니다. 다른 예정 경로는 첫 실제 기능이 필요할 때 생성합니다. 기존 코드의 자동 이전이나 운영 배포를 뜻하지 않습니다.

## 작업은 어디에 넣나요?

| 루트 예정 경로 | 담당할 내용 |
|---|---|
| `web/` | 사용자·관리자 화면, HTTP client, 화면 상태·접근성 |
| `api/` | 공개 HTTP API, 인증·업무 규칙, 앱 저장소, AI 작업 consumer |
| `ai/` | AI 실행·작업·receipt·artifact와 독립 저장소 |
| `contracts/` | 실제 consumer가 필요로 하는 언어 중립 생성물·합성 fixture의 향후 배포. 명세 원본이나 공용 업무 코드가 아닙니다. |
| `infra/` | 별도 승인된 배포·운영 설정. 현재 CI는 `.github/`, 로컬 도구는 `scripts/`에 있습니다. |

원문·설계·계약은 계속 `docs/`에 둡니다. 앱 BE는 Java 21·Spring Boot 4.1.1·Gradle 9.7.1 Wrapper를 선택했습니다. FE와 AI의 스택은 독립적으로 정합니다.

## `api/` 최소 기반과 첫 업무 기능

`api/`는 병렬 개발을 위해 Java 21·Gradle Wrapper·PostgreSQL/JPA/Flyway, 공통 오류·요청 ID 처리와 로컬 테스트를 먼저 갖춥니다. [API 실행·협업 안내](../../api/README.md)에 로컬 DB·서버 실행과 기능별 패키지·migration 규칙이 있습니다. 이 최소 기반 PR에는 업무 API나 API CI 연결을 요구하지 않습니다. 첫 API 업무 기능 PR 병합 전에는 루트 명령·CI job·required gate로 API 앱의 테스트·빌드를 연결해야 합니다. 담당자는 그 사이 각자 기능과 로컬 테스트를 병렬로 개발할 수 있습니다.

## 다른 새 앱은 첫 실제 기능 PR에서 폴더와 실행 기준을 함께 만듭니다

수직 기능은 사용자의 동작이나 API 요청 하나가 실제 진입점부터 결과까지 이어지는 작업입니다. 예를 들어 기업 문서 조회를 선택했다면 해당 범위의 조회·권한·정상 자료 부재·실패를 구현하고 검증합니다. 경로만 선점하는 빈 폴더, health 응답만 있는 앱, stub은 만들지 않습니다.

`web/`, `ai/` 등 다른 앱의 첫 PR에는 필요한 앱만 생성하고 다음을 함께 넣습니다.

1. **실제 동작과 실행 환경:** 선택한 스택·버전·소유 책임, manifest/lock 또는 해당 언어의 재현 가능한 의존성 설정, 실제 진입점, 앱 README의 설치·실행 방법을 기록합니다. Java를 선택하면 해당 앱의 wrapper를 연결하며 다른 앱의 도구를 바꾸지 않습니다.
2. **계약과 테스트:** 정상·실패·복구의 수용 기준과 합성 입력 기반 테스트를 구현합니다. 계약이 바뀌면 producer·consumer·생성 타입·fixture·테스트를 같은 PR에서 갱신합니다.
3. **루트 명령과 CI:** 새 앱의 실제 runner를 루트 명령·CI job·required gate에 연결하고 명령·입력·관측 결과를 PR에 남깁니다. 현재 루트 명령과 CI는 프로토타입·문서/계약 검사이므로 그 성공을 새 앱의 검증으로 대신하지 않습니다.

기존 branch protection이나 원격 CI가 설정됐다고 추정하지 않습니다. private PoC credential trust 승인, 유료 모델 호출, 외부 데이터 사용, 운영 배포는 각각 별도 조건이며 첫 앱 PR이 이를 자동 승인하지 않습니다. [설정 선행조건](../development/github-setup.md)을 따릅니다.

## 브랜치와 PR은 기존 규칙을 유지합니다

브랜치는 `feat|fix|docs|chore/<issue>-<slug>`, 커밋·PR 제목은 `type(scope): 설명`입니다. scope는 `web`, `api`, `ai`, `contracts`, `docs`, `infra`를 유지합니다. 아래 번호는 **예시이며 실제 이슈 번호로 바꿉니다.**

| 작업 | 브랜치 예 | 커밋·PR 제목 예 |
|---|---|---|
| 기업 문서 화면 | `feat/123-document-view` | `feat(web): 기업 문서 조회 구현` |
| 공급자 장애 처리 | `fix/124-source-unavailable` | `fix(api): 공급자 장애와 정상 자료 부재 구분` |
| AI 실행 기능 | `feat/127-document-analysis` | `feat(ai): 문서 분석 실행 구현` |
| 비호환 JSON 계약 변경 | `feat/126-document-contract` | `feat(contracts)!: 문서 응답 계약 전환` |

PR에는 이슈 연결, 실제 변경·제외 경로, FS/NFS의 기능명·정의 출처와 WBS의 현재 업무명·BE/FE 역할, 계약 영향, 실행 결과·미검증 사항·롤백 기준을 적습니다. ID 존재만으로 의미가 일치한다고 보지 않습니다. 제목은 현재 CI 검사 대상이며 브랜치명과 개별 커밋은 리뷰 규약입니다. [전체 이름 규칙과 리뷰 책임](../../CONTRIBUTING.md), [PR 양식](../../.github/pull_request_template.md)을 따릅니다.

## 계약 소유권과 프로토타입 사용 경계

- **목표 OpenAPI 정본은 [`docs/api/openapi.yaml`](../api/openapi.yaml)입니다.** worker JSON Schema도 `docs/api/` 정본을 유지합니다. 계약 담당과 영향을 받는 앱 담당이 함께 리뷰합니다. 루트 `contracts/`는 실제 consumer와 생성·검증 명령이 생긴 뒤 배포용으로만 만들며 생성물을 수동 편집하지 않습니다. 정본을 옮길 때는 생성기·검사기·문서·모든 consumer를 한 번에 이행하고 두 원본을 남기지 않습니다.
- 현재 BFF `/api`와 목표 `/api/v1`은 다릅니다. prefix 별칭만 붙여 이식을 완료하지 않습니다. [계약 인계](../migration/contract-handoff.md)와 [이식 가이드](../migration/README.md)를 기준으로 판단합니다.
- `prototype/web/`, `prototype/bff/`, `prototype/ai-worker/`는 시연·회귀 재현·구현 참고용입니다. 본개발이 runtime dependency로 import하거나 앱/worker DB를 공유하지 않습니다. 같은 스택의 코드를 채택해도 권리·의존성·계약을 확인하고 본개발 소유 경로에 독립 실행 설정과 테스트를 둡니다. 기존 코드는 이번 경로 결정으로 자동 복사·이동하지 않습니다.
- 앱 BE와 AI는 versioned JSON과 선택한 transport로 연결하고 서로의 DB에 직접 접근하지 않습니다. 별도 비공개 원천 PoC는 읽기 전용이며 이 저장소에 vendoring하지 않습니다.

## 팀원이 지금 할 일

1. 이번 변경이 `main`에 반영되면 최신 내용을 받고 [루트 README](../../README.md)와 [10-12 명세·WBS 갱신](../evidence/doc-delta-2026-10-12.md)을 읽습니다.
2. 본인 WBS의 현재 업무명·역할·출처를 확인하고 중복 이슈를 검색한 뒤, 첫 실제 기능의 변경 경로·스택 선택·정상/실패/복구 수용 기준을 이슈에 적습니다. 담당자와 reviewer는 팀에서 확인합니다.
3. 실제 이슈 번호로 브랜치를 만들고 필요한 경로만 구현합니다. `api/` 담당자는 [API 안내](../../api/README.md)의 로컬 실행·검증과 패키지·DB 규칙을 따릅니다. 첫 API 업무 기능 PR 병합 전에는 API CI를 연결하고, 다른 새 앱은 첫 기능 PR에 실행기·테스트·CI 연결을 포함합니다. 계약 변경은 영향을 받는 담당자와 함께 처리합니다.

나머지 예정 폴더를 미리 만들거나 프로토타입 전체를 옮기는 작업은 필요하지 않습니다. 문서 반영·로컬 검사·원격 CI·배포 완료는 각각 구분해 공유합니다.
