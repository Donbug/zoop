# ai/worker — S1 JSON CLI worker

`zoop-ai {submit,run,get,resume,cancel} --state-dir DIR [--grants FILE] [--replay FILE] [--initial-only]`. `--initial-only`는 `run`/`resume` 전용 내부 권한(자동 재dispatch용)이다: job lock 안에서 호출 기록이 없는 job만 시작하고, 기록이 하나라도 있으면 저장된 receipt 저장만 한다(reserve·송신·provider 생성 없음). 플래그가 없는 일반 호출의 의미는 바뀌지 않는다. 입력은 stdin JSON, 출력은 stdout canonical JSON입니다. 환경 변수(`ZOOP_AI_LIVE_ENABLED`, `ZOOP_AI_GLOBAL_MAX_CALLS`, `ZOOP_AI_BASE_URL`, `ZOOP_AI_API_KEY`, 단계별 model/effort, 선택적 네이티브 검증 `ZOOP_AI_VERIFY_PROVIDER=typesafe-native`·`TYPESAFE_API_KEY`·`TYPESAFE_BASE_URL`·`TYPESAFE_VALIDATION_MODEL`)는 live opt-in에만 쓰이며 기본은 꺼져 있습니다. 저장된 job은 submit 때 고정한 stage 설정(provider·endpoint·model·정책)대로만 실행되고, 호출 client는 아직 보낼 stage의 provider 것만, 그 provider의 key로만 만든다.

```bash
make worker-install     # uv sync --project ai/worker --frozen --group dev (공개 의존성만, 토큰 없음)
make worker-test        # ai/worker/.venv/bin/python -m pytest ai/worker/tests
make worker-schema-check
python ai/worker/scripts/validate_contracts.py   # schema + portable fixture, stdlib only
make worker-build
```

- `src/zoop_ai/`: 계약(`contracts.py`), 영속 저장소, runner, provider(replay/OpenAI-compatible/네이티브 Jev), 네이티브 Jev 요청·판정 정책(`native_jev.py`, 순수 함수), CLI.
- `scripts/export_schema.py`: 계약에서 `docs/api/ai-contract.schema.json`을 생성합니다(순수 worker 도구).
- `fixtures/contracts/`: `synthetic-document`, `synthetic-outlook`(jobs/grants/replay/snapshot). BFF 소유 `prototype/bff/scripts/export_contracts.py`가 생성하고 `make worker-contracts-check`가 drift를 검사합니다.
- BFF 통합 driver(`prototype/bff/scripts/replay_fixture.py`, `replay_outlook_fixture.py`)는 BFF 소유입니다.
- `zoop-ai config-check [--format text] [--require-live-prerequisites] [--profile native-jev]`: 요청·상태·grant 읽기 없이 현재 환경만 점검하는 오프라인 doctor(`src/zoop_ai/doctor.py`). `--state-dir`은 받지 않고 key는 존재 여부만 보인다. 기본 프로필은 모든 단계를 OpenAI 호환 adapter로, `native-jev`는 `semantic-verification`을 네이티브 Jev로 기대하며 어긋나면 조용히 바꾸지 않고 오류로 보고한다. 설정 유효·live 환경 준비·지출 승인은 서로 다른 것이며 지출 승인은 환경에서 추론하지 않는다. 설정 이름 템플릿은 `.env.example`, 사용법과 smoke 계획은 [AI 런타임 준비](../../docs/development/ai-runtime-setup.md).
- `scripts/setup_ai_env.py`: 사람이 터미널에서 직접 실행하는 `.env` 설정 도구(stdlib, key는 숨김 프롬프트로만 입력, 고정 프로필: 문서 요약·감성·briefing-outlook `gpt-6-luna`/`high`, VERIFY 네이티브 `jev-1.14.0`, live 항상 꺼짐, 쓰이지 않는 `ZOOP_AI_VERIFY_MODEL`/`_REASONING_EFFORT` 줄은 삭제). `--status`는 감사 기록만 읽는다. 동작과 안전 규칙은 [AI 런타임 준비 §6](../../docs/development/ai-runtime-setup.md), 테스트는 `tests/test_setup_cli.py`.
- `zoop-ai-chat invoke --state-dir DIR [--grants FILE] [--replay FILE]`: 챗봇 모델 단계 하나(`chat-router` 네이티브 Jev, `chat-answer` Luna, `chat-verification` 네이티브 Jev, `chat-agent` Luna Responses 승인 루프 한 단계)를 실행한다. stdin `StageRequest` → stdout `StageResult`(성공 0, 실패 2, 잘못된 요청 64). S1과 별개의 단계 계약(`zoop-ai-chat-3`)·질문 집합·live 게이트(`ZOOP_AI_CHAT_LIVE_ENABLED`, `ZOOP_AI_CHAT_MAX_CALLS`)·원장(`chat.sqlite3`)을 쓴다. 같은 `invocationId`는 다시 보내지 않고, 보낸 뒤 결과를 모르면 `unknown`으로 남긴다. 검증은 현재 요청·구간·요구에 결속된 서버 조회 사실과 인용을 구분한다. 인용문은 별도 v1 챗봇 grant가 허락할 때만 보내며 조회 사실이 grant를 대신하지 않는다. 코드 `src/zoop_ai/chat_*.py`, 시험 `tests/test_chat_stages.py`와 `tests/test_chat_agent.py`. 자세한 규칙은 [AI 런타임 준비 §11](../../docs/development/ai-runtime-setup.md), 검증 문맥은 [챗봇 모델 단계 클라이언트](../../api/docs/AI_INTEGRATION.md#챗봇-모델-단계-클라이언트)를 따른다.
- `zoop-ai-chat probe-mcp`: `ZOOP_AI_CHAT_MCP_SERVER_URL`에 grant 없는 JSON-RPC `ping`을 보내 endpoint 자체의 `401` Bearer challenge를 확인한다. 모델·원장·live 예산을 쓰지 않으며 정상 도달은 exit 0 `reachable`, timeout·연결 실패·앞단 gateway의 502/503/504(`mcp_unavailable`)·예상 밖 응답은 exit 2 `unreachable`과 닫힌 reason, URL 설정 오류는 exit 64다. redirect는 따르지 않는다. 시험은 `tests/test_chat_probe.py`의 메모리 내 transport만 사용한다.
- `scripts/native_jev_smoke.py`: 로컬 가짜 provider 두 개(chat, systemone)와 **설치된 `zoop-ai` CLI**로 네이티브 검증 경로를 끝까지 돌리는 실제 프로세스 smoke. 실제 키·endpoint·모델 호출 없음, 환경을 상속하지 않는다. `ai/worker/.venv/bin/python ai/worker/scripts/native_jev_smoke.py`. 테스트는 `tests/test_native_jev.py`(공용 가짜 provider는 `tests/fake_providers.py`).
