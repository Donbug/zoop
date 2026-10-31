#!/usr/bin/env python3
"""Real Java -> ai/service -> installed `zoop-ai-chat` replay gate for the chatbot model stages.

Authors the exact stage inputs the Java adapters (`com.zoop.chat.model.ChatModelStages`) must build for a fixed synthetic
scenario, and an authored replay answer for each, keyed by the worker's own request identity. A Java input that differs in
any field has no replay entry and is refused (`replay_input_mismatch`), so the gate proves the two sides agree on the
`zoop-ai-chat-4` inputs and answers, not only on the envelope. Before any process starts, the fixture is replayed in-process
through the worker runtime so an authoring mistake fails here and not as a Java mismatch.

Then starts one real `ai/service` (127.0.0.1, fresh temp state, replay only, live gate closed: a supported Jev model name so
a live request reaches the gate, but no live enable, budget or provider key; synthetic in-memory principals, no model call,
no PostgreSQL) with the chat group, runs `./api/gradlew aiChatContractTest` against it, checks the JUnit report
(every contract test named in CONTRACT_TESTS ran, none skipped or failed) and that no credential or private path reached the
service log or the Gradle output.
Then checks the native verifier request through a second service and a loopback fake Jev provider. Both services use fresh
synthetic state; no external provider, real credential or PostgreSQL is involved.

Run with the ai/service environment (`make service-install` first): `make api-ai-chat-smoke`. `--check-fixture` only runs the
in-process fixture check. Needs JDK 21 (JAVA_HOME) like any api build.
"""
from __future__ import annotations

import copy
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai" / "service" / "tests"))
sys.path.insert(0, str(ROOT / "ai" / "worker" / "tests"))

from support import PGREP, ServiceProcess, Workspace, remove_tree, terminate_runtime  # noqa: E402

API = ROOT / "api"
RESULTS = API / "build" / "test-results" / "aiChatContractTest"
GRADLE_TIMEOUT_SECONDS = 900
SCHEMA = "zoop-ai-chat-4"
# Not a secret: the one Jev model the worker supports. Set so a live request passes the stage configuration and is refused
# by the closed live gate itself; live enable, budget and provider keys stay unset.
LIVE_JEV_MODEL = "jev-1.14.0"
# One test per contract boundary: a boundary whose test went missing fails the gate even when every remaining test passes.
CONTRACT_TESTS = frozenset({
    "theRouterAnswersTheServerSplitRequirementsWithTypedProbabilities",
    "theRouterCarriesADependentRequirementCheckpoint",
    "theAnswerIsGeneratedFromTheGrantedQuote",
    "theVerifierJudgesEachSection",
    "theOrchestratorSendsBoundMemberAndComparisonFacts",
    "theSameInvocationIsAnsweredFromTheLedgerAndNeverSentAgain",
    "aQuoteWithoutAChatGrantIsRefusedBeforeSending",
    "anInputTheFixtureDoesNotKnowIsRefusedNotGuessed",
    "liveModeIsRefusedWhileTheServiceGateIsClosed",
    "aPrincipalWithoutChatInvokeIsRefused",
})

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
DEPENDENCY_QUESTION = "내 종목과 연결된 회사를 찾아줘? 정확히 두 곳이면 그 회사 최근 사건을 알려줘"
DEPENDENCY_ROUTER_INPUT = {
    "turns": [{"text": DEPENDENCY_QUESTION, "choiceLabel": None}],
    "requirements": [{"requirementId": "r1", "text": "내 종목과 연결된 회사를 찾아줘", "explicit": True},
                     {"requirementId": "r2", "text": "정확히 두 곳이면 그 회사 최근 사건을 알려줘", "explicit": True}],
    "capabilities": ROUTER_INPUT["capabilities"],
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
    "requestBinding": {"invocationId": "chat-verify-gate.1.verify", "graphVersionId": "gv-synthetic",
                       "asOf": "2026-10-21T00:00:00Z"},
    "sections": [{"sectionId": "s0", "requirementIds": ["r1"], "serverFacts": [],
                  "basis": "evidence_grounded", "text": EVIDENCE_TEXT, "evidenceIds": [EVIDENCE]},
                 {"sectionId": "s1", "requirementIds": ["r2"], "serverFacts": [],
                  "basis": "general_knowledge", "text": GENERAL_TEXT, "evidenceIds": []}],
    "citations": [QUOTE],
}
FACT_VERIFICATION_INPUT = {
    "requestBinding": {"invocationId": "chat-facts-gate.1.verify", "graphVersionId": "gv-synthetic",
                       "asOf": "2026-10-21T00:00:00Z"},
    "sections": [{"sectionId": "s0", "requirementIds": ["r1"], "basis": "evidence_grounded",
                  "text": "보유 종목 삼성전자와 관심 종목 NVIDIA의 조회된 지도 변경입니다.",
                  "evidenceIds": [EVIDENCE], "serverFacts": [
        {"kind": "portfolio_scope", "requirementId": "r1", "timing": "current_request_read",
         "queryScope": "current_member", "companyIds": [], "companyLimit": 5, "truncated": True,
         "companies": [{"companyId": "KRX:005930", "name": "삼성전자", "held": True, "watched": False},
                       {"companyId": "NASDAQ:NVDA", "name": "NVIDIA", "held": False, "watched": True}]},
        {"kind": "graph_comparison", "requirementId": "r1", "fromVersion": "gv-earlier", "toVersion": "gv-synthetic",
         "asOf": "2026-10-21T00:00:00Z", "since": None, "queryScope": "targets",
         "targetIds": ["KRX:005930", "NASDAQ:NVDA"], "evidenceLimit": 20, "changeLimit": 40,
         "evidenceRestricted": False, "truncated": True,
         "changes": [{"id": "iss-new", "kind": "issue", "name": "공급 계약", "change": "added"},
                     {"id": "iss-old", "kind": "issue", "name": "이전 사건", "change": "removed"},
                     {"id": "edge-stable", "kind": "edge", "name": "가" * 298 + "\U00020000…", "change": "added"}]}]}],
    "citations": [QUOTE],
}


class GateFailure(Exception):
    pass


def _request(stage: str, payload: dict[str, Any]):
    from zoop_ai.chat_contracts import StageRequest
    invocation = payload.get("requestBinding", {}).get("invocationId", "gate-authoring")
    return StageRequest.model_validate({"schemaVersion": SCHEMA, "invocationId": invocation, "stage": stage,
                                        "mode": "replay", "input": payload})


def _noul(p: float) -> dict[str, Any]:
    return {"type": "noul", "noul": p}


def _choice(name: str, names: list[str], p: float = 0.97) -> dict[str, Any]:
    rest = (1 - p) / (len(names) - 1)
    return {"type": "choice", "choice": name, "confidence": 0.93,
            "probabilities": {candidate: (p if candidate == name else rest) for candidate in names}}


def _router_answers(questions: dict[str, Any]) -> dict[str, Any]:
    answers = {}
    for key, question in questions.items():
        if question["type"] == "noul":
            answers[key] = _noul(0.03)
        else:
            names = list(question["criteria"])
            answers[key] = _choice("none" if "none" in names else names[0], names)
    return answers


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
    answers = _router_answers(questions)
    answers["r0-q02"] = _noul(0.93)   # r1: a concept
    answers["r1-q03"] = _noul(0.88)   # r2: company and issue facts
    answers["r1-cap0"] = _noul(0.91)  # r2 reads company.read
    answers["r1-cap1"] = _noul(0.84)  # and issue.read
    entry("chat-router", ROUTER_INPUT, {"model": "authored-synthetic-chat-router", "answers": answers})

    dependency_router = _request("chat-router", DEPENDENCY_ROUTER_INPUT)
    dependency_questions = chat_jev.build_router_request(dependency_router.parsed(), "authored")["questions"]
    dependency_answers = _router_answers(dependency_questions)
    dependency_answers["r0-q07"] = _noul(0.93)
    dependency_answers["r0-cap0"] = _noul(0.91)
    dependency_answers["r1-q03"] = _noul(0.93)
    dependency_answers["r1-cap0"] = _noul(0.91)
    dependency_answers["r1-dependency-source"] = _choice("r0", ["none", "r0"])
    dependency_answers["r1-dependency-cardinality"] = _choice("exactly", ["exactly", "atLeast", "atMost"])
    dependency_answers["r1-dependency-count"] = _choice("count2", [f"count{count}" for count in range(1, 6)])
    entry("chat-router", DEPENDENCY_ROUTER_INPUT,
          {"model": "authored-synthetic-chat-router", "answers": dependency_answers})

    entry("chat-answer", ANSWER_INPUT, {"model": "authored-synthetic-chat-answer",
                                         "choices": [{"message": {"role": "assistant",
                                                                 "content": json.dumps(ANSWER, ensure_ascii=False)}}]})

    supported = {"type": "choice", "choice": "supported", "confidence": 0.93,
                 "probabilities": {"supported": 0.97, "contradicted": 0.015, "insufficient": 0.015}}
    entry("chat-verification", VERIFICATION_INPUT, {"model": "authored-synthetic-chat-verification",
                                                    "answers": {"s0-support": supported, "s0-advice": _noul(0.02),
                                                                "s1-advice": _noul(0.02)}})
    entry("chat-verification", FACT_VERIFICATION_INPUT, {"model": "authored-synthetic-chat-verification",
                                                        "answers": {"s0-support": supported, "s0-advice": _noul(0.02)}})
    return {"schemaVersion": SCHEMA, "recordingKind": "authored-test", "responses": entries}


def grants() -> dict[str, Any]:
    """Only SOURCE may be quoted to the replay recipient; the scenario's second source is deliberately absent."""
    return {"schemaVersion": "zoop-ai-chat-1", "grants": [{
        "grantId": "g-chat-synthetic", "revision": "1", "sourceId": SOURCE, "enabled": True, "rights": "known",
        "allowedOperations": ["read", "model-send", "quote-display"], "recipients": ["authored-replay"],
        "purposes": ["chat-answer", "chat-verification"], "evidence": ["synthetic gate fixture"], "expiresAt": None}]}


def check_fixture(replay: dict[str, Any], registry: dict[str, Any], state: Path) -> None:
    """Replays every authored stage through the worker runtime in-process: each must succeed with the expected answer."""
    from zoop_ai.chat_contracts import ChatGrantRegistry
    from zoop_ai.chat_runtime import ReplaySender, invoke, provider_body, stage_config

    path = state / "replay.check.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
    sender = ReplaySender(path)
    parsed = ChatGrantRegistry.model_validate(registry)
    for index, (stage, payload) in enumerate((("chat-router", ROUTER_INPUT), ("chat-router", DEPENDENCY_ROUTER_INPUT),
                                              ("chat-answer", ANSWER_INPUT),
                                              ("chat-verification", VERIFICATION_INPUT),
                                              ("chat-verification", FACT_VERIFICATION_INPUT))):
        request = _request(stage, payload)
        if stage != "chat-verification":
            request = request.model_copy(update={"invocation_id": f"check-{index}-{stage}"})
        if stage == "chat-verification":
            _, outbound = provider_body(request, stage_config(stage, "replay"))
            assert outbound["state"]["requestBinding"] == payload["requestBinding"]
            for sent, expected in zip(outbound["state"]["sections"], payload["sections"], strict=True):
                assert sent["serverFacts"] == expected["serverFacts"]
        result = invoke(request, state_dir=state, registry=parsed, sender=sender, env={})
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
    names: set[str] = set()
    for report in reports:
        suite = ET.parse(report).getroot()
        tests += int(suite.get("tests", "0"))
        failures += int(suite.get("failures", "0")) + int(suite.get("errors", "0"))
        if int(suite.get("skipped", "0")):
            raise GateFailure("aiChatContractTest skipped tests: a skip is not a pass")
        names.update(case.get("name", "").removesuffix("()") for case in suite.iter("testcase"))
    if tests == 0:
        raise GateFailure("aiChatContractTest executed zero tests")
    missing = sorted(CONTRACT_TESTS - names)
    if missing:
        raise GateFailure(f"contract tests did not run: {', '.join(missing)}")
    return tests, failures


def chat_processes(command: Path, state: Path) -> list[int]:
    """Pids of live `zoop-ai-chat invoke` children of this run: its own command bound to its own chat state, nothing broader.

    pgrep exit 1 means "no match"; any other failure is an error, never silently "no processes".
    """
    pattern = re.escape(str(command)) + r" invoke --state-dir " + re.escape(str(state)) + r"( |$)"
    found = subprocess.run([PGREP, "-f", "--", pattern], capture_output=True, text=True)
    if found.returncode == 1:
        return []
    if found.returncode != 0:
        raise RuntimeError(f"pgrep failed with exit {found.returncode}")
    return [int(pid) for pid in found.stdout.split() if int(pid) != os.getpid()]


def terminate_chat(command: Path, state: Path, timeout: float = 10.0) -> None:
    """Kill the chat children a killed service left behind and prove they are gone, before their state is removed."""
    end = time.monotonic() + timeout
    while True:
        pids = chat_processes(command, state)
        if not pids:
            return
        if time.monotonic() >= end:
            raise AssertionError(f"chat processes still alive: {pids}")
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.1)


def check_native_http(root: Path, command: Path) -> None:
    """Real service HTTP -> CLI decoder -> Jev builder -> loopback native provider, with synthetic credentials only."""
    from fake_providers import FakeServer, jev_respond
    from zoop_ai.chat_runtime import stage_config

    provider = FakeServer(jev_respond())
    service = None
    state = root / "native-chat-state"
    try:
        workspace = Workspace(root / "native")
        settings = {"ZOOP_AI_CHAT_LIVE_ENABLED": "1", "ZOOP_AI_CHAT_MAX_CALLS": "2",
                    "ZOOP_AI_CHAT_JEV_MODEL": LIVE_JEV_MODEL, "TYPESAFE_BASE_URL": provider.base,
                    "TYPESAFE_API_KEY": "synthetic-loopback-only"}
        registry = grants()
        registry["grants"][0]["recipients"] = [
            "typesafe-native:" + stage_config("chat-verification", "live", settings).provider_revision]
        grant_path = root / "native-grants.json"
        grant_path.write_text(json.dumps(registry), encoding="utf-8")
        env = workspace.env(**settings, ZOOP_AI_SERVICE_CHAT_COMMAND=str(command), ZOOP_AI_CHAT_STATE_DIR=str(state),
                            ZOOP_AI_SERVICE_CHAT_GRANTS=str(grant_path))
        service = ServiceProcess(workspace, env=env).start()
        body = _request("chat-verification", FACT_VERIFICATION_INPUT).wire()
        body["mode"] = "live"

        def send(value):
            return service.request("POST", "/internal/v1/chat-stages/chat-verification", as_="chatter",
                                   body=value, key=value["invocationId"])

        response = send(body)
        assert response.status_code == 200, response.text
        assert response.json()["answer"]["sections"] == [{"support": "supported", "prohibitedAdvice": "no"}]
        assert len(provider.requests) == 1
        observed = provider.requests[0]
        assert observed["path"] == "/v1/systemone"
        state_sent = observed["body"]["state"]
        assert state_sent["requestBinding"] == FACT_VERIFICATION_INPUT["requestBinding"]
        assert state_sent["sections"][0]["serverFacts"] == FACT_VERIFICATION_INPUT["sections"][0]["serverFacts"]
        assert state_sent["sections"][0]["citedQuotes"] == [{"quote": QUOTE["quote"]}]
        assert set(observed["body"]["questions"]) == {"s0-support", "s0-advice"}

        for change in (
                lambda v: v.update(invocationId="foreign-job.1.verify"),
                lambda v: v["input"]["sections"][0]["serverFacts"][0].update(requirementId="other"),
                lambda v: v["input"]["sections"][0]["serverFacts"][1].update(toVersion="stale"),
                lambda v: v["input"]["sections"][0].update(sectionId="s1"),
                lambda v: v.update(schemaVersion="zoop-ai-chat-1")):
            forged = copy.deepcopy(body)
            change(forged)
            assert send(forged).status_code == 422
        assert len(provider.requests) == 1, "invalid context must not reach a provider"

        absent = copy.deepcopy(body)
        absent["invocationId"] = absent["input"]["requestBinding"]["invocationId"] = "no-facts.1.verify"
        absent["input"]["sections"][0].update(serverFacts=[], evidenceIds=[])
        absent["input"]["citations"] = []
        response = send(absent)
        assert response.status_code == 200, response.text
        assert response.json()["answer"]["sections"] == [{"support": "hold", "prohibitedAdvice": "no"}]
        assert len(provider.requests) == 2
        assert provider.requests[1]["body"]["state"]["sections"][0]["serverFacts"] == []
        print("chat-native-loopback: context=bound, forgeryRejections=5, absentContext=hold, localProviderCalls=2, externalCalls=0")
    finally:
        if service is not None:
            service.close()
        terminate_chat(command, state)
        provider.close()


def main(argv: list[str]) -> int:
    root = Path(tempfile.mkdtemp(prefix="zoop-api-ai-chat-contract-")).resolve()
    root.chmod(0o700)
    service: ServiceProcess | None = None
    chat_child: tuple[Path, Path] | None = None
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
                            ZOOP_AI_SERVICE_CHAT_GRANTS=str(chat_grants), ZOOP_AI_SERVICE_CHAT_REPLAY=str(chat_replay),
                            ZOOP_AI_CHAT_JEV_MODEL=LIVE_JEV_MODEL)
        chat_child = (command, chat / "state")
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
        service.close()
        service = None
        check_native_http(root, command)
        print(f"api-ai-chat-smoke: status=passed, javaTests={tests}, services=2, localProviderCalls=2, externalCalls=0")
        return 0
    except (GateFailure, AssertionError, OSError) as error:
        print(f"api-ai-chat-smoke: status=failed: {error}", file=sys.stderr)
        return 1
    finally:
        if service is not None:
            service.close()
            terminate_runtime(service.workspace.worker)
        if chat_child is not None:
            terminate_chat(*chat_child)
        remove_tree(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
