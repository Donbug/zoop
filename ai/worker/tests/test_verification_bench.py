"""Worker side of the semantic-verification benchmark: the bridge builds valid jobs from the visible inputs only, the evaluation
harness reads a native-Jev body exactly as the worker policy does, and the fake server recognizes every case.

Everything is offline; the loopback answers are an authored script (a control), never a model."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

from zoop_ai import native_jev
from zoop_ai.contracts import SCHEMA_VERSION, Submit
from zoop_ai.runner import Runner

WORKER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER / "tests"))
sys.path.insert(0, str(WORKER.parent / "evaluation"))
_spec = importlib.util.spec_from_file_location("verification_bench", WORKER / "scripts" / "verification_bench.py")
bench = importlib.util.module_from_spec(_spec)
sys.modules["verification_bench"] = bench
_spec.loader.exec_module(bench)

from zoop_eval.verification import (  # noqa: E402
    REFERENCE_POLICY, build_control, derive, load_inputs, load_verify_corpus, parse_loopback_script, scenario_response,
)

INPUTS = load_inputs(bench.DEFAULT_CASES)
SCRIPT = parse_loopback_script(json.loads(bench.DEFAULT_SCRIPT.read_text("utf-8")), INPUTS)


def test_the_harness_reference_policy_is_the_worker_policy():
    assert REFERENCE_POLICY == bench.policy()
    assert bench.policy() == {"choiceProbability": native_jev.CHOICE_PROBABILITY, "choiceConfidence": native_jev.CHOICE_CONFIDENCE,
                              "noulTrue": native_jev.NOUL_TRUE, "noulFalse": native_jev.NOUL_FALSE,
                              "distributionTolerance": native_jev.DISTRIBUTION_TOLERANCE}


def test_every_visible_case_becomes_a_valid_verification_only_job():
    jobs = bench.build_jobs(INPUTS)
    assert list(jobs) == list(INPUTS.cases)
    for case_id, job in jobs.items():
        submit = Submit.model_validate(job)  # also raised inside build_job together with exact(): quotes, locators, limitation coverage
        assert submit.kind == "semantic-verification" and submit.input.candidate is not None
        assert [c.claim_id for c in submit.input.candidate.claims] == INPUTS.claim_ids(case_id)
    assert len({j["jobId"] for j in jobs.values()}) == len(jobs)


def test_jobs_carry_no_gold_and_building_them_never_opens_it():
    with bench.watching_gold() as opened:
        jobs = json.dumps(bench.build_jobs(load_inputs(bench.DEFAULT_CASES)), ensure_ascii=False)
        bench.Loopback(INPUTS, SCRIPT).close()
    assert opened == []
    for key in ("expectedGate", "expectedAdvice", "expectedCausality", "expectedDecision", "tags"):
        assert key not in jobs


def test_the_watch_actually_sees_an_attempt_to_open_a_gold_file():
    with bench.watching_gold() as opened:
        load_verify_corpus()  # the evaluation side legitimately opens it: the watch must notice
    assert [Path(p).name for p in opened] == ["gold.json"]


def test_the_bridge_works_with_a_corpus_directory_that_has_no_gold(tmp_path):
    (tmp_path / "cases.json").write_bytes(bench.DEFAULT_CASES.read_bytes())
    assert list(bench.build_jobs(load_inputs(tmp_path / "cases.json"))) == list(INPUTS.cases)
    assert not (tmp_path / "gold.json").exists()


@pytest.mark.parametrize("case_id", list(INPUTS.cases))
def test_the_harness_reads_every_scripted_body_exactly_as_the_worker_policy_does(case_id):
    ids = INPUTS.claim_ids(case_id)
    status, payload = scenario_response(SCRIPT[case_id], len(ids), native_jev.MODEL)
    if status != 200:
        assert SCRIPT[case_id]["scenario"] == "http_error"  # the worker refuses the status before any body is read
        return
    body = payload if isinstance(payload, dict) else {"responseText": payload.decode(), "httpStatus": 200}  # the provider's wrapping
    try:
        expected = native_jev.interpret(body, ids, native_jev.MODEL)
    except ValueError as exc:
        with pytest.raises(ValueError, match=str(exc)):
            derive(body, len(ids), native_jev.MODEL, bench.policy())
        return
    got = derive(body, len(ids), native_jev.MODEL, bench.policy())
    assert got["decisions"] == [v.decision for v in expected.claims]
    assert (got["advice"], got["causality"]) == (expected.prohibited_advice, expected.unsupported_causality)


def test_the_fake_server_recognizes_every_case_from_the_request_the_worker_builds():
    server = bench.Loopback(INPUTS, SCRIPT)
    try:
        for case_id, job in bench.build_jobs(INPUTS).items():
            request = Submit.model_validate(job)
            payload = Runner._payload(None, request, request.input.candidate)
            sent = native_jev.build_request(payload, native_jev.MODEL)
            state = sent["state"]
            key = bench._request_key(state["document"]["text"], state["company"]["name"], [c["text"] for c in state["candidate"]["claims"]])
            assert server.by_request[key] == case_id
    finally:
        server.close()


def test_the_scripted_control_is_what_the_exported_pipeline_must_reproduce():
    corpus = load_verify_corpus()
    expected = build_control(corpus, "loopback_script_expected")
    assert [r["caseId"] for r in expected["records"]] == list(INPUTS.cases)
    assert {r["status"] for r in expected["records"]} == {"ok", "error"}


def test_a_provider_export_is_not_implemented_and_never_guessed(tmp_path):
    with pytest.raises(bench.BridgeError, match="only loopback_fake"):
        bench.export_run(INPUTS, tmp_path, {}, run_id="x", endpoint_kind="provider")


def test_the_child_environment_is_built_from_nothing():
    env = bench.child_env("http://127.0.0.1:1/v1", "loopback-k", 28, Path("/tmp/x"))
    assert set(env) == {"PATH", "HOME", "LANG", "PYTHONDONTWRITEBYTECODE", "ZOOP_AI_LIVE_ENABLED", "ZOOP_AI_GLOBAL_MAX_CALLS",
                        "ZOOP_AI_VERIFY_PROVIDER", "TYPESAFE_VALIDATION_MODEL", "TYPESAFE_BASE_URL", "TYPESAFE_API_KEY"}
    assert env["TYPESAFE_BASE_URL"].startswith("http://127.0.0.1:") and env["ZOOP_AI_GLOBAL_MAX_CALLS"] == "28"


@pytest.mark.skipif(not bench.CLI.exists(), reason="installed zoop-ai CLI missing (make worker-install)")
def test_three_scripted_cases_round_trip_through_the_installed_cli_and_export():
    """ok, definite HTTP error and kept-receipt model mismatch: the exported record equals what the script must yield."""
    expected = {r["caseId"]: r for r in build_control(load_verify_corpus(), "loopback_script_expected")["records"]}
    server = bench.Loopback(INPUTS, SCRIPT)
    try:
        with tempfile.TemporaryDirectory(prefix="zoop-vk-test-") as tmp:
            work = Path(tmp)
            grant = {**bench.fixture("grants")["grants"][0], "recipients": ["typesafe-native:" + bench.native_revision(server.base)],
                     "purposes": [bench.VERIFY]}
            grants = work / "grants.json"
            grants.write_text(json.dumps({"schemaVersion": SCHEMA_VERSION, "grants": [grant]}))
            env = bench.child_env(server.base, "loopback-test-key", 3, work)
            jobs = bench.build_jobs(INPUTS)
            for case_id in ("VK-01", "VK-23", "VK-17"):
                assert bench.cli("submit", jobs[case_id], work / "ledger", env, grants)[0] == 0
                bench.cli("run", {"schemaVersion": SCHEMA_VERSION, "jobId": jobs[case_id]["jobId"]}, work / "ledger", env, grants)
                _, result = bench.cli("get", {"schemaVersion": SCHEMA_VERSION, "jobId": jobs[case_id]["jobId"]}, work / "ledger", env)
                record = bench._record(INPUTS, case_id, result, bench._receipt(work / "ledger", jobs[case_id]["jobId"]))
                want = expected[case_id]
                assert record["status"] == want["status"], case_id
                assert record["claimBinding"] == want["claimBinding"] and record["caseSha256"] == want["caseSha256"]
                if want["status"] == "ok":
                    assert record["result"] == want["result"] and record["raw"] == want["raw"]
                    assert record["call"]["cost"] == {"usd": 0, "source": "loopback_no_charge"}
                else:
                    assert record["error"] == want["error"]
                    assert ("raw" in record) == ("raw" in want)
            assert len(server.requests) == 3 and all(c for c in server.matched)
    finally:
        server.close()
