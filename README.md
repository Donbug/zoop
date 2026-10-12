# 줍(Zoop)

LG CNS AM Inspire Camp 5기 2조 금융 도메인 프로젝트입니다. 내 종목과 시장의 사건이 왜 연결되는지, 어떤 근거가 있는지를 보여 주는 금융 지도 서비스를 만듭니다.

## 본개발 시작하기

**본개발 코드는 저장소 루트의 `web/`, `api/`, `ai/`, `contracts/`, `infra/`에 책임별로 구현합니다. `api/`에는 Spring Boot 실행 기반과 공통 오류 처리가 있으며 업무 API는 아직 없습니다. 현재 기능을 실행할 수 있는 앱은 `prototype/`에 있고 운영 배포는 없습니다.** 앱 백엔드는 Java 21/Spring Boot를 선택했으며 프론트엔드와 AI 런타임은 독립적으로 선택합니다.

| 본개발 예정 경로 | 책임 | 현재 참고 자료 |
|---|---|---|
| `web/` | 사용자·관리자 클라이언트 | [화면계획서](docs/screen-plan/README.md), `docs/design/`, 목표 HTTP 계약 |
| `api/` — 실행 기반 있음 | 인증·업무 규칙·앱 저장소·공개 HTTP API | [API 실행·개발 안내](api/README.md), [목표 OpenAPI](docs/api/openapi.yaml), [계약 인계](docs/migration/contract-handoff.md) |
| `ai/` | AI 실행·작업·산출물 저장소 | [AI 실행 계약](docs/design/ai-system.md), [이식 가이드](docs/migration/README.md) |
| `contracts/` | 필요한 언어 중립 생성물·합성 fixture의 향후 배포 경계 | **정본은 현재 `docs/api/`**입니다. 생성·검증 명령과 실제 consumer가 생길 때 만들며 두 번째 명세 원본으로 사용하지 않습니다. |
| `infra/` | 별도 승인된 배포·운영 설정 | [현재 구조와 목표/클라우드 초안](docs/share/system-architecture/README.md), [설정 선행조건](docs/development/github-setup.md) |
| `docs/` — 현재 존재 | 원문 근거·설계·계약·인계 | [근거 목록](docs/evidence/README.md), [추적 체계](docs/system/README.md) |

`api/`는 팀의 병렬 개발을 위한 최소 기반 PR로 먼저 생성했습니다. Java 21·Gradle Wrapper·PostgreSQL/JPA/Flyway와 공통 오류 처리를 로컬에서 검증했으며 업무 API는 각 담당자의 기능 PR에서 추가합니다. 다른 예정 경로는 실제 기능이 생길 때 생성합니다. 첫 API 업무 기능 PR 병합 전에는 API 실행기를 루트 명령과 CI에 연결해야 합니다. 팀원이 지금 할 일은 [본개발 시작 안내](docs/share/production-start-2026-10-12.md), 자세한 생성 조건과 이름 규칙은 [개발 참여 규약](CONTRIBUTING.md)에 있습니다.

1. [최신 원문 갱신 기록](docs/evidence/doc-delta-2026-10-12.md)과 [현재 작업 결정](docs/share/day-work-2026-10-10.md)을 읽고, 최신 명세·WBS의 **ID·업무명·출처**로 작업 범위를 정합니다.
2. 중복 이슈를 확인한 뒤 정상·실패·복구 조건의 완료 기준을 작성하고, [branch·commit·PR 규약](CONTRIBUTING.md#작업-범위와-이슈부터-pr까지)에 따라 브랜치를 만듭니다.
3. 계약이 바뀌면 `docs/api/` 원본과 영향을 받는 모든 consumer·생성물·시험을 함께 갱신합니다. 현재 BFF `/api`와 목표 `/api/v1`의 차이는 prefix 교체만으로 해소되지 않습니다.
4. 선택한 본개발 경로에 실제 기능을 구현하고 검증 결과를 PR에 남깁니다. **기존 CI는 프로토타입과 문서/계약을 검사하며, `api/` 검사기는 아직 연결하지 않았습니다.** API 첫 업무 기능 PR 병합 전 해당 runner·테스트를 루트 명령과 CI에 연결합니다. 다른 새 앱은 첫 기능 PR에서 연결합니다.

루트에서 기존 명령과 설치된 도구를 확인할 수 있습니다. API의 현재 로컬 빌드·테스트·실행 명령은 [api/README.md](api/README.md)에 있습니다. 이 루트 명령은 본개발 앱을 생성하거나 배포하지 않습니다.

```sh
make help projects available-checks
```

본개발은 `prototype/` 코드를 runtime dependency로 import하거나 프로토타입 DB를 공유하지 않습니다. 같은 스택의 코드를 채택하더라도 라이선스·계약을 확인하고 본개발 소유 경로와 테스트로 옮깁니다. 전환 시에는 모든 caller를 함께 이행하고 구 writer·임시 호환 경로를 제거합니다.

## 작업 기준과 주요 문서

| 문서 | 용도 |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | 본개발 경로, 언어별 이름 규칙, 작업→계약→검증→PR, 경로별 리뷰 책임 |
| [최신 근거](docs/evidence/README.md) · [10-12 원문 갱신](docs/evidence/doc-delta-2026-10-12.md) | 현재 명세·WBS는 10-12 고정본, 요구사항은 10-06 고정본입니다. 원문·작업자 판단·팀 미결정을 구분합니다. |
| [현재 작업 결정](docs/share/day-work-2026-10-10.md) · [10-08 결정](docs/share/day-work-2026-10-08.md) | 범위 예외, 현행/이력 정의, AI 번호 의미 이행, 차트 해상도와 기능 우선 원칙 |
| [목표 API 정본](docs/api/openapi.yaml) · [생성 API 명세서](docs/api/out/zoop-api-spec.md) | 84개 목표 operation의 계약입니다. 앱 구현 완료 보고가 아니며 공통 규칙은 잠정 채택/시연 기준입니다. |
| [추적 체계](docs/system/README.md) · [팀용 추적표](docs/system/out/zoop-trace.xlsx) · [내용 기반 WBS 이행](docs/system/out/wbs-migration.md) · [경고/차이](docs/system/out/warnings.md) | 화면→명세 정의→현재 WBS 역할→목표 API의 연결과 남은 충돌 |
| [마이그레이션 가이드](docs/migration/README.md) · [계약 인계](docs/migration/contract-handoff.md) | FE·앱 백엔드·AI의 독립 선택, HTTP/JSON·근거·작업 상태·저장소 경계와 전환 기준 |
| [화면계획서](docs/screen-plan/README.md) · [Figma 비교 근거](docs/evidence/wireframe-delta-2026-10-08.md) | Figma는 폰트 제외 최종 목표 디자인이며 SUIT를 유지합니다. `docs/design/`에는 토큰·그래프 UX 결정, `docs/research/`에는 조사 자료가 있습니다. |
| [검증·배포 증거 절차](docs/development/release-verification.md) · [10/12 주 작업 계획](docs/share/seojin-work-plan-2026-10-12.md) | 실행한 검증과 배포 승인을 구분합니다. 작업 계획은 원본 WBS를 대체하지 않습니다. |
| [GitHub 설정 안내](docs/development/github-setup.md) | 기존 CI, private PoC credential trust 승인, 보호 규칙의 수동 등록과 아티팩트 준비 범위 |

일정은 **WBS**를 따릅니다. 옛 Notion 일정은 비권위이고 갱신된 회의·API 결정은 사례별 증거입니다. FS074~FS081을 포함한 모든 명세/WBS 내용은 설계·구현 계획의 대상이며 오래된 `검토 전` 표기와 완료·실행 승인을 구분합니다. 추천 종목·산업·테마는 활성 기능에서 제외하되 `listRecommendations` 계약은 유보하고, 재무·실적 요구는 폐기하지 않았습니다.

CI 파일 반영, 검사 통과, 아티팩트 준비, 배포는 각각 다릅니다. 보호 규칙·private PoC 자격 증명 등록·운영 배포는 별도 선행조건을 충족해야 하며, 유료 모델 호출과 외부 데이터 사용 승인도 코드 구현과 별개입니다.

## 부록: 현재 프로토타입 실행·참고

`prototype/`은 시연·회귀 재현·구현 참고용 비운영 코드입니다. 현재 실행 경로와 명령은 그대로 유지합니다.

| 현재 경로 | 실행·참고 |
|---|---|
| `prototype/web/` | React/Vite 화면. `make web-install web-typecheck web-test web-build` |
| `prototype/bff/` | FastAPI BFF. `make bff-install bff-test`, `make bff-build` |
| `prototype/ai-worker/` | 독립 Python JSON CLI. `make worker-install`, `make worker-test WORKER_PYTHON=prototype/ai-worker/.venv/bin/python`, `make worker-build` |

서버 실행·환경·private 의존성 준비는 [프로토타입 README](prototype/README.md)를 따릅니다. [프로토타입 설명서](docs/share/prototype-guide.md)는 소개·시연·복구·연동 안내이며 [PDF](docs/share/prototype-guide.pdf)·[HTML](docs/share/prototype-guide.html)도 있습니다. 현재 실행과 목표 구성은 [구조도](docs/share/system-architecture/README.md)에서 구분합니다. [다음 작업 후보](docs/share/next-work-2026-10-08.md)와 [새벽 작업 기록](docs/share/overnight-2026-10-08.md)은 당시 기록이므로 최신 원문·결정과 대조합니다.

원천 뉴스→사건 판정 PoC는 별도 비공개 저장소 [Donbug/investmate-poc](https://github.com/Donbug/investmate-poc)입니다. 현재 BFF는 고정 커밋으로 의존합니다. 이 저장소로 vendoring하거나 원본을 수정하지 않으며 공개 port·권한·언어 독립 계약을 통해 채택합니다.
