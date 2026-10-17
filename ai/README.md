# ai — 실행 가능한 AI 런타임

세 개의 독립 Python 프로젝트(각자 `pyproject.toml`·`uv.lock`·`.venv`)가 있습니다. workspace가 아니며 서로의 소스를 import하지 않습니다.

| 프로젝트 | 패키지 | 의존성 | 하는 일 | 실행 |
| --- | --- | --- | --- | --- |
| [`worker/`](worker/README.md) | `zoop_ai` | 공개 패키지만(pydantic, httpx). **토큰 불필요** | S1 문서 요약·감성·의미 검증·briefing-outlook의 영속 JSON CLI | `zoop-ai` |
| [`pipeline/`](pipeline/README.md) | `zoop_ai_pipeline` | 공개 패키지만(pydantic, httpx, lxml, pypdf, `neo4j==6.3.1`(graph 전용 직접 의존성)). **토큰·private PoC 불필요** | S2-1 원문 준비, S2-2 이벤트·주제 후보, S3 관계·영향 후보(네이티브 오프라인, replay 전용), S4 일부: S2/S3 읽기 전용 의존 대상 조회(변경된 문서·source·grant → 영향 job·후보 나열, 철회 아님), FS080 일부: 완료된 S3 job 하나를 **비공개** 불변 Neo4j version으로 stage(`zoop-ai-graph`, 서버 소유 canonical 결정·단일 explicit transaction·복구·매 read 전체 검증. 공개·활성화·FS081 철회 아님) | `zoop-ai-collect`, `zoop-ai-ingest`, `zoop-ai-extract`, `zoop-ai-relation`, `zoop-ai-dependents`, `zoop-ai-graph`, `zoop-ai-handoff` |
| [`service/`](service/README.md) | `zoop_ai_service` | 공개 패키지만(fastapi, uvicorn, pydantic — BFF·worker lock의 기존 정확한 버전). **토큰 불필요**. S2·S3 시험·smoke만 설치된 `ai/pipeline/.venv`를 요구한다(lock에는 넣지 않음) | S1용 앱→AI **내부 HTTP transport**(loopback 전용, 제출·조회·결과·취소·복구)와 별도 가족의 S2 추출 job·S3 관계 job(둘 다 기본 꺼짐). 설치된 `zoop-ai`·`zoop-ai-extract`·`zoop-ai-relation` CLI만 호출. 로컬 준비 상태이며 배포는 승인되지 않음 | `zoop-ai-service` |

공통 규칙
- worker·pipeline의 프로세스 경계는 stdin JSON → stdout canonical JSON(성공 0, 오류/보류 2)입니다. 이들 CLI는 HTTP 서버가 아니며 `.env`를 읽지 않습니다. HTTP는 별도 프로젝트 `service/`가 맡고 worker CLI와 S2 `zoop-ai-extract`·S3 `zoop-ai-relation` CLI를 감싸는 얇은 층일 뿐입니다(S2는 `/internal/v1/extraction-jobs` 별도 가족, 기본 꺼짐, 제출·상태·결과·취소·복구, 호출자는 서버가 사전 승인한 요청의 digest만 참조하며 스냅샷·카탈로그·fixture를 보낼 수 없음. S3는 `/internal/v1/relation-jobs` 별도 가족, 기본 꺼짐, 제출·상태·결과·취소·복구와 HOLD 검수(allow/reject)·큐에 넣는 재검증·operation 조회·복구, 목록 없음. 검수 값 `sourceVersion`·`sourceRevision`은 런타임 원천 값이며 앱 revision이 아닙니다). live 모델 호출은 S1에서만 명시 opt-in이고 S2/S3는 replay 전용입니다. S2-2의 `submit`은 운영자 소유 `--replay` 파일을 요구하므로 서버 소유 승인 파일이 정확한 요청과 fixture digest를 고정한 경우에만 HTTP로 열고, S2-1 수집은 운영자 파일 입력이라 열지 않습니다. S3 HTTP는 운영자가 준비한 S2 job을 서버 소유 allowlist로 principal별로 허용한 upstream으로만 씁니다. `zoop-ai-dependents`는 세 원장을 읽기 전용으로만 여는 조회 명령이며 HTTP·앱 상태와 연결하지 않았습니다.
- `--state-dir`는 항상 명시해야 하고, 앱(`prototype/bff/var`, 향후 `api/var`)·worker(`ai/worker/var`) 상태 루트와 겹치면 거부합니다. pipeline의 세 원장(ingestion/extraction/relation)은 서로 다른 디렉터리이고, `zoop-ai-graph`의 `graph.sqlite3`도 별도 디렉터리여야 하며 세 원천 원장과 겹치면 거부합니다. 설치된 pipeline 패키지는 저장소 위치를 추측하지 않으므로 `ZOOP_STATE_DIR`·`ZOOP_AI_WORKER_STATE_DIR`(절대 경로)를 명시해야 하고, 없으면 `state_ownership_unconfigured`로 닫힙니다.
- pipeline 명령 중 `zoop-ai-graph`만 네트워크를 연다: 한 원장에 묶인 loopback(또는 인증서 검증 TLS) Neo4j 한 곳이며 pipeline이 그 유일한 writer입니다. 쓰는 것은 완료된 S3 job 하나의 **비공개** 불변 version stage뿐입니다(FS080 일부. 출력 `publication`은 항상 `not-published`이고 활성 공개 상태·앱 등록·HTTP·FS081 철회·영향 라벨 projection은 없습니다). `ai/service`는 이 CLI를 감싸지 않고(HTTP 없음) Spring도 Neo4j write 자격을 갖지 않으며, PoC Neo4j와 PoC의 변경 writer는 쓰지 않습니다. 자격은 환경에서만 읽고 출력에 싣지 않습니다.
- BFF는 worker를 설치된 CLI(`ai/worker/.venv/bin/zoop-ai`)로만 호출합니다. `service/`도 같은 설치된 CLI만 호출하고 worker 상태 DB를 열거나 `zoop_ai`를 import하지 않으며, 서비스 상태 루트(`ZOOP_AI_SERVICE_STATE_DIR`)는 worker·앱 상태 루트와 겹치면 시작을 거부합니다. BFF·pipeline·service는 서로의 런타임을 import하지 않습니다. pipeline과 service는 worker를 **test 의존성**으로만 설치합니다.
- 공개 계약은 `docs/api/ai-contract.schema.json`(worker `scripts/export_schema.py`가 생성)입니다. 포터블 fixture(`worker/fixtures/contracts`)는 BFF/PoC 입력이 필요해 BFF 소유 도구 `prototype/bff/scripts/export_contracts.py`가 생성합니다. 내부 HTTP 계약은 `docs/api/internal-ai-openapi.{json,yaml}`(service 소유 `scripts/export_openapi.py`가 생성)이며 위 schema를 **참조**하고 복제하지 않습니다.

명령(저장소 루트)
```bash
make worker-install worker-test worker-schema-check worker-build
make pipeline-install pipeline-test pipeline-smoke pipeline-build   # 공개 의존성만, private PoC·토큰 불필요(수집·원문 준비·S2/S3/S4·graph·handoff 전부, replay 전용)
make pipeline-graph-smoke                                           # 격리된 빈 Neo4j 5 database 필요(ZOOP_GRAPH_SMOKE_URI·ZOOP_GRAPH_AUTH), 없으면 실패
make service-install service-test service-smoke service-openapi-check service-build   # 공개 의존성만, 토큰 없음
make service-pipeline-test service-pipeline-smoke                    # S3 relation job: 설치된 pipeline(make pipeline-install)이 있어야 하며 없으면 실패
make worker-contracts-check                                          # 설치된 BFF 환경 필요
```

## 평가 도구

[`evaluation/`](evaluation/README.md)은 위 실행 서비스와 분리된 표준 라이브러리 기반 평가 CLI입니다. Graph 생성 결과와 RAG의 기록된 답변·근거·탐색 경로·시간을 독립 정답 세트와 비교합니다. 현재 포함된 결과는 **합성 채점 대조군**이며 실모델·검색 시스템의 측정 결과가 아닙니다. KPI 정의, 비교 기준선과 WBS 연결은 [AI 벤치마크 계획](../docs/design/ai-benchmark.md)을 따릅니다.

