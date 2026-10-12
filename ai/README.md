# ai — 실행 가능한 AI 런타임

세 개의 독립 Python 프로젝트(각자 `pyproject.toml`·`uv.lock`·`.venv`)가 있습니다. workspace가 아니며 서로의 소스를 import하지 않습니다.

| 프로젝트 | 패키지 | 의존성 | 하는 일 | 실행 |
| --- | --- | --- | --- | --- |
| [`worker/`](worker/README.md) | `zoop_ai` | 공개 패키지만(pydantic, httpx). **토큰 불필요** | S1 문서 요약·감성·의미 검증·briefing-outlook의 영속 JSON CLI | `zoop-ai` |
| [`pipeline/`](pipeline/README.md) | `zoop_ai_pipeline` | 고정된 private PoC(`Donbug/investmate-poc`@`fa446e7`) + lxml/pypdf | S2-1 원문 준비, S2-2 이벤트·주제 후보, S3 관계·영향 후보(오프라인, replay 전용) | `zoop-ai-ingest`, `zoop-ai-extract`, `zoop-ai-relation` |
| [`service/`](service/README.md) | `zoop_ai_service` | 공개 패키지만(fastapi, uvicorn, pydantic — BFF·worker lock의 기존 정확한 버전). **토큰 불필요** | S1용 앱→AI **내부 HTTP transport**(loopback 전용, 제출·조회·결과·취소·복구). 설치된 `zoop-ai` CLI만 호출. 로컬 준비 상태이며 배포는 승인되지 않음 | `zoop-ai-service` |

공통 규칙
- worker·pipeline의 프로세스 경계는 stdin JSON → stdout canonical JSON(성공 0, 오류/보류 2)입니다. 이들 CLI는 HTTP 서버가 아니며 `.env`를 읽지 않습니다. HTTP는 별도 프로젝트 `service/`가 맡고 worker CLI를 감싸는 얇은 층일 뿐입니다. live 모델 호출은 S1에서만 명시 opt-in이고 S2/S3는 replay 전용입니다(S2/S3는 등록 전용 `submit`이 없어 HTTP 대상이 아닙니다).
- `--state-dir`는 항상 명시해야 하고, 앱(`prototype/bff/var`, 향후 `api/var`)·worker(`ai/worker/var`) 상태 루트와 겹치면 거부합니다. pipeline의 세 원장(ingestion/extraction/relation)은 서로 다른 디렉터리입니다. 설치된 pipeline 패키지는 저장소 위치를 추측하지 않으므로 `ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR`(절대 경로)를 명시해야 하고, 없으면 `state_ownership_unconfigured`로 닫힙니다.
- BFF는 worker를 설치된 CLI(`ai/worker/.venv/bin/zoop-ai`)로만 호출합니다. `service/`도 같은 설치된 CLI만 호출하고 worker 상태 DB를 열거나 `zoop_ai`를 import하지 않으며, 서비스 상태 루트(`ZOOP_AI_SERVICE_STATE_DIR`)는 worker·앱 상태 루트와 겹치면 시작을 거부합니다. BFF·pipeline·service는 서로의 런타임을 import하지 않습니다. pipeline과 service는 worker를 **test 의존성**으로만 설치합니다.
- 공개 계약은 `docs/api/ai-contract.schema.json`(worker `scripts/export_schema.py`가 생성)입니다. 포터블 fixture(`worker/fixtures/contracts`)는 BFF/PoC 입력이 필요해 BFF 소유 도구 `prototype/bff/scripts/export_contracts.py`가 생성합니다. 내부 HTTP 계약은 `docs/api/internal-ai-openapi.{json,yaml}`(service 소유 `scripts/export_openapi.py`가 생성)이며 위 schema를 **참조**하고 복제하지 않습니다.

명령(저장소 루트)
```bash
make worker-install worker-test worker-schema-check worker-build
make pipeline-install pipeline-test pipeline-smoke pipeline-build   # private PoC 접근 필요
make service-install service-test service-smoke service-openapi-check service-build   # 공개 의존성만, 토큰 없음
make worker-contracts-check                                          # 설치된 BFF 환경 필요
```
