# ai/worker — S1 JSON CLI worker

`zoop-ai {submit,run,get,resume,cancel} --state-dir DIR [--grants FILE] [--replay FILE] [--initial-only]`. `--initial-only`는 `run`/`resume` 전용 내부 권한(자동 재dispatch용)이다: job lock 안에서 호출 기록이 없는 job만 시작하고, 기록이 하나라도 있으면 저장된 receipt 저장만 한다(reserve·송신·provider 생성 없음). 플래그가 없는 일반 호출의 의미는 바뀌지 않는다. 입력은 stdin JSON, 출력은 stdout canonical JSON입니다. 환경 변수(`ZOOP_AI_LIVE_ENABLED`, `ZOOP_AI_GLOBAL_MAX_CALLS`, `ZOOP_AI_BASE_URL`, `ZOOP_AI_API_KEY`, 단계별 model/effort)는 live opt-in에만 쓰이며 기본은 꺼져 있습니다.

```bash
make worker-install     # uv sync --project ai/worker --frozen --group dev (공개 의존성만, 토큰 없음)
make worker-test        # ai/worker/.venv/bin/python -m pytest ai/worker/tests
make worker-schema-check
python ai/worker/scripts/validate_contracts.py   # schema + portable fixture, stdlib only
make worker-build
```

- `src/zoop_ai/`: 계약(`contracts.py`), 영속 저장소, runner, provider(replay/OpenAI-compatible), CLI.
- `scripts/export_schema.py`: 계약에서 `docs/api/ai-contract.schema.json`을 생성합니다(순수 worker 도구).
- `fixtures/contracts/`: `synthetic-document`, `synthetic-outlook`(jobs/grants/replay/snapshot). BFF 소유 `prototype/bff/scripts/export_contracts.py`가 생성하고 `make worker-contracts-check`가 drift를 검사합니다.
- BFF 통합 driver(`prototype/bff/scripts/replay_fixture.py`, `replay_outlook_fixture.py`)는 BFF 소유입니다.
