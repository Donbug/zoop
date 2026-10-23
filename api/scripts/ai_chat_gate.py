#!/usr/bin/env python3
"""Real Java -> ai/service -> installed `zoop-ai-chat` replay gate for the chatbot model stages.

Authors the exact stage inputs the Java adapters (`com.zoop.chat.model.ChatModelStages`) must build for a fixed synthetic
scenario, and an authored replay answer for each, keyed by the worker's own request identity. A Java input that differs in
any field has no replay entry and is refused (`replay_input_mismatch`), so the gate proves the two sides agree on the
`zoop-ai-chat-1` inputs and answers, not only on the envelope. Before any process starts, the fixture is replayed in-process
through the worker runtime so an authoring mistake fails here and not as a Java mismatch.

Then starts one real `ai/service` (127.0.0.1, fresh temp state, replay only, live gate closed, synthetic in-memory principals,
no model call, no PostgreSQL) with the chat group, runs `./api/gradlew aiChatContractTest` against it, checks the JUnit report
(non-zero tests, none skipped or failed) and that no credential or private path reached the service log or the Gradle output.

Run with the ai/service environment (`make service-install` first): `make api-ai-chat-smoke`. `--check-fixture` only runs the
in-process fixture check. Needs JDK 21 (JAVA_HOME) like any api build.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai" / "service" / "tests"))

from support import ServiceProcess, Workspace, remove_tree, terminate_runtime  # noqa: E402

API = ROOT / "api"
RESULTS = API / "build" / "test-results" / "aiChatContractTest"
GRADLE_TIMEOUT_SECONDS = 900
SCHEMA = "zoop-ai-chat-1"

# ---- the synthetic scenario; AiChatContractTest builds the same through the production adapters ------------------------------
# The capability descriptions are ChatCapability's: changing one changes what the router is asked, so the fixture must follow.
SOURCE = "src-chat-synthetic"
EVIDENCE = "ev-" + "1" * 64
QUOTE = {"evidenceId": EVIDENCE, "sourceId": SOURCE, "quote": "삼성전자가 HBM 공급 계약을 맺었다.", "articleTitle": "합성 기사",
         "publishedAt": "2026-10-20T00:00:00Z"}
ROUTER_QUESTION = "PER이 뭐야? 삼성전자 관련 사건 알려줘"
ANSWER_QUESTION = "삼성전자 관련 사건 알려줘"
EVIDENCE_TEXT = "삼성전자는 HBM 공급 계약을 맺었습니다."
GENERAL_TEXT = "PER은 주가를 주당순이익으로 나눈 값입니다."

ROUTER_INPUT = {
    "turns": [{"text": ROUTER_QUESTION, "choiceLabel": None}],
    "requirements": [{"requirementId": "r1", "text": "PER이 뭐야", "explicit": True},
                     {"requirementId": "r2", "text": "삼성전자 관련 사건 알려줘", "explicit": True}],
    "capabilities": [{"capabilityId": "company.read", "description": "기업과 그 기업의 승인된 관계, 관계를 뒷받침하는 근거 읽기"},
                     {"capabilityId": "issue.read", "description": "사건(이슈)과 관련 기업, 사건 근거 읽기"}],
}
ANSWER_INPUT = {
    "turns": [{"text": ANSWER_QUESTION, "choiceLabel": None}],
    "branches": [{"requirementId": "r1", "label": ANSWER_QUESTION, "general": False, "noneFound": False,
                  "items": [{"id": "c-samsung", "kind": "company", "label": "삼성전자"}], "evidence": [QUOTE]}],
    "maxCitations": 20,
}
ANSWER = {"sections": [{"basis": "evidence_grounded", "text": EVIDENCE_TEXT, "requirementIds": ["r1"], "evidenceIds": [EVIDENCE]}],
          "insufficientRequirementIds": [], "graphTargetIds": ["c-samsung"]}
VERIFICATION_INPUT = {
    "sections": [{"basis": "evidence_grounded", "text": EVIDENCE_TEXT, "evidenceIds": [EVIDENCE]},
                 {"basis": "general_knowledge", "text": GENERAL_TEXT, "evidenceIds": []}],
    "citations": [QUOTE],
}


class GateFailure(Exception):
    pass


def _request(stage: str, payload: dict[str, Any]):
    from zoop_ai.chat_contracts import StageRequest
    return StageRequest.model_validate({"schemaVersion": SCHEMA, "invocationId": "gate-authoring", "stage": stage,
                                        "mode": "replay", "input": payload})


def _noul(p: float) -> dict[str, Any]:
    return {"type": "noul", "noul": p}


def author_replay() -> dict[str, Any]:
    """One authored answer per stage, in the provider's raw shape, keyed by the worker's request identity."""
    from zoop_ai import chat_jev
    from zoop_ai.chat_runtime import request_identity, stage_config

    entries = []

    def entry(stage: str, payload: dict[str, Any], response: dict[str, Any]) -> None:
        request = _request(stage, payload)
        entries.append({"stage": stage, "inputDigest": request_identity(request, stage_config(stage, "replay")),
                        "response": response})

    router = _request("chat-router", ROUTER_INPUT)
    questions = chat_jev.build_router_request(router.parsed(), "authored")["questions"]
    answers = {key: _noul(0.03) for key in questions}
    answers["r0-q02"] = _noul(0.93)   # r1: a concept
    answers["r1-q03"] = _noul(0.88)   # r2: company and issue facts
    answers["r1-cap0"] = _noul(0.91)  # r2 reads company.read
    answers["r1-cap1"] = _noul(0.84)  # and issue.read
    entry("chat-router", ROUTER_INPUT, {"model": "authored-synthetic-chat-router", "answers": answers})

    entry("chat-answer", ANSWER_INPUT, {"model": "authored-synthetic-chat-answer",
                                         "choices": [{"message": {"role": "assistant",
                                                                 "content": json.dumps(ANSWER, ensure_ascii=False)}}]})

    supported = {"type": "choice", "choice": "supported", "confidence": 0.93,
                 "probabilities": {"supported": 0.97, "contradicted": 0.015, "insufficient": 0.015}}
    entry("chat-verification", VERIFICATION_INPUT, {"model": "authored-synthetic-chat-verification",
                                                    "answers": {"s0-support": supported, "s0-advice": _noul(0.02),
                                                                "s1-advice": _noul(0.02)}})
    return {"schemaVersion": SCHEMA, "recordingKind": "authored-test", "responses": entries}


def grants() -> dict[str, Any]:
    """Only SOURCE may be quoted to the replay recipient; the scenario's second source is deliberately absent."""
    return {"schemaVersion": SCHEMA, "grants": [{
        "grantId": "g-chat-synthetic", "revision": "1", "sourceId": SOURCE, "enabled": True, "rights": "known",
        "allowedOperations": ["read", "model-send", "quote-display"], "recipients": ["authored-replay"],
        "purposes": ["chat-answer", "chat-verification"], "evidence": ["synthetic gate fixture"], "expiresAt": None}]}


def check_fixture(replay: dict[str, Any], registry: dict[str, Any], state: Path) -> None:
    """Replays every authored stage through the worker runtime in-process: each must succeed with the expected answer."""
    from zoop_ai.chat_contracts import ChatGrantRegistry
    from zoop_ai.chat_runtime import ReplaySender, invoke

    path = state / "replay.check.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    sender = ReplaySender(path)
    parsed = ChatGrantRegistry.model_validate(registry)
    for stage, payload in (("chat-router", ROUTER_INPUT), ("chat-answer", ANSWER_INPUT), ("chat-verification", VERIFICATION_INPUT)):
        result = invoke(_request(stage, payload).model_copy(update={"invocation_id": f"check-{stage}"}), state_dir=state,
                        registry=parsed, sender=sender, env={})
        if result.status != "succeeded":
            raise GateFailure(f"authored {stage} fixture does not replay: {result.failure.code if result.failure else '?'}")
    answer = invoke(_request("chat-answer", ANSWER_INPUT).model_copy(update={"invocation_id": "check-answer-again"}),
                    state_dir=state, registry=parsed, sender=sender, env={})
    if answer.answer != ANSWER:
        raise GateFailure("authored chat-answer fixture does not round-trip")


def run_gradle(manifest: Path, captured: list[str]) -> int:
    env = {**os.environ, "ZOOP_AI_CHAT_CONTRACT_MANIFEST": str(manifest)}
    process = subprocess.Popen([str(API / "gradlew"), "-p", str(API), "aiChatContractTest", "--console=plain"], env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               errors="replace")

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            captured.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        code = process.wait(GRADLE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise GateFailure(f"gradle aiChatContractTest exceeded {GRADLE_TIMEOUT_SECONDS}s") from None
    reader.join(10)
    return code


def verify_junit() -> tuple[int, int]:
    reports = sorted(RESULTS.glob("TEST-*.xml"))
    if not reports:
        raise GateFailure("aiChatContractTest produced no JUnit report: the contract tests did not run")
    tests = failures = 0
    for report in reports:
        suite = ET.parse(report).getroot()
        tests += int(suite.get("tests", "0"))
        failures += int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
        if int(suite.get("skipped", "0")):
            raise GateFailure("aiChatContractTest skipped tests: a skip is not a pass")
    if tests == 0:
        raise GateFailure("aiChatContractTest executed zero tests")
    return tests, failures


def main(argv: list[str]) -> int:
    root = Path(tempfile.mkdtemp(prefix="zoop-api-ai-chat-contract-")).resolve()
    root.chmod(0o700)
    service: ServiceProcess | None = None
    captured: list[str] = []
    try:
        replay, registry = author_replay(), grants()
        check_state = root / "fixture-check"
        check_state.mkdir()
        check_fixture(replay, registry, check_state)
        if "--check-fixture" in argv:
            print(f"api-ai-chat-smoke: fixture=passed, stages={len(replay['responses'])}, providerCalls=0")
            return 0

        workspace = Workspace(root / "main")
        chat = root / "main" / "chat"
        chat.mkdir()
        chat_replay, chat_grants = chat / "replay.json", chat / "grants.json"
        chat_replay.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
        chat_grants.write_text(json.dumps(registry), encoding="utf-8")
        command = Path(sys.executable).parent / "zoop-ai-chat"
        if not command.is_file():
            raise GateFailure("the installed zoop-ai-chat command is missing: run `make service-install`")
        env = workspace.env(ZOOP_AI_SERVICE_CHAT_COMMAND=str(command), ZOOP_AI_CHAT_STATE_DIR=str(chat / "state"),
                            ZOOP_AI_SERVICE_CHAT_GRANTS=str(chat_grants), ZOOP_AI_SERVICE_CHAT_REPLAY=str(chat_replay))
        service = ServiceProcess(workspace, env=env).start()

        tokens = workspace.credentials.tokens
        manifest = {"baseUrl": f"http://127.0.0.1:{workspace.port}", "chatToken": tokens["chatter"],
                    "readerToken": tokens["reader"]}
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_path.chmod(0o600)

        shutil.rmtree(RESULTS, ignore_errors=True)
        code = run_gradle(manifest_path, captured)
        if code != 0:
            raise GateFailure(f"gradle aiChatContractTest exited with {code}")
        tests, failures = verify_junit()
        if failures:
            raise GateFailure(f"{failures} chat contract test failures")
        if service.process is None or service.process.poll() is not None:
            raise GateFailure("the service process died during the run")
        output = "".join(captured)
        private = [*workspace.private_strings(), str(chat), str(command)]
        if any(s in output or s in service.logs() for s in private):
            raise GateFailure("a credential or private path reached the service log or the Gradle output")
        print(f"api-ai-chat-smoke: status=passed, javaTests={tests}, services=1, providerCalls=0")
        return 0
    except (GateFailure, AssertionError, OSError) as error:
        print(f"api-ai-chat-smoke: status=failed: {error}", file=sys.stderr)
        return 1
    finally:
        if service is not None:
            service.close()
            terminate_runtime(service.workspace.worker)
        remove_tree(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
