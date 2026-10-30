from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("chat_live_spike_extract", ROOT / "scripts" / "chat_live_spike_extract.py")
assert SPEC and SPEC.loader
extract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = extract
SPEC.loader.exec_module(extract)
spike = extract._report_module()


def stage(name: str = "chat-agent", input_tokens: int | None = 1_000, output: int | None = 500,
          reasoning: int | None = 300, send: str = "sent", model: str = "gpt-6-luna") -> dict:
    return {"stage": name, "status": "succeeded", "sendState": send, "mode": "live", "model": model,
            "promptVersion": "chat-agent-1", "inputTokens": input_tokens, "outputTokens": output,
            "reasoningTokens": reasoning}


def job(job_id: str = "job-1", rounds: int = 1, calls: int = 1, **changes) -> dict:
    row = {
        "job_id": job_id, "status": "completed", "failure_code": None, "attempts": 1, "attempt_mode": "run",
        "started_at": "2026-10-30T00:00:00Z", "finished_at": "2026-10-30T00:00:20.000000Z", "path": "agent",
        "tool_calls": calls, "web_calls": 0, "registry_versions": ["chat-tools/v8"],
        "stages": [stage("chat-router", 100, 10, None, model="jev")] + [stage() for _ in range(rounds + 1)]
        + [stage("chat-verification", 200, 20, None, model="jev")],
    }
    row.update(changes)
    return row


def manifest(*runs: tuple[str, str]) -> dict:
    return {
        "schemaVersion": extract.MANIFEST_SCHEMA, "candidateCommit": "a" * 40, "approvedBy": "ai-lead",
        "approvalRef": "AI-42", "environment": "isolated-1", "policyVersion": "v0.11",
        "pricing": {"gpt-6-luna": {"inputUsdPerMTok": "2", "outputUsdPerMTok": "8"},
                    "jev": {"inputUsdPerMTok": "1", "outputUsdPerMTok": "4"}},
        "runs": [{"jobId": job_id, "scenario": scenario} for job_id, scenario in runs],
    }


class ExtractTest(unittest.TestCase):
    def test_a_run_is_read_from_the_ledger_and_passes_the_gates_loader(self) -> None:
        evidence = extract.extract(manifest(("job-1", "tools-1-rounds-1")), [job()])
        run = evidence["runs"][0]

        self.assertEqual((1, 1, 2), (run["toolCalls"], run["approvalRounds"], run["providerCalls"]))
        self.assertEqual((2_000, 1_000, 600), (run["inputTokens"], run["outputTokens"], run["reasoningTokens"]))
        self.assertEqual(200, run["answerTokens"], "the last step's output less its reasoning")
        # Luna 2000 in, 1000 out at 2/8; Jev 300 in, 30 out at 1/4.
        self.assertEqual("0.01242", run["costUsd"])
        self.assertEqual("gpt-6-luna", evidence["model"])
        self.assertEqual("chat-tools/v8", evidence["toolRegistryVersion"])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            extract.write(evidence, output)
            metadata, runs = spike.load(output)
        self.assertEqual("a" * 40, metadata["candidateCommit"])
        self.assertEqual(20, runs[0].latency_seconds)

    def test_a_completed_run_of_another_shape_stops_the_extraction_and_is_named(self) -> None:
        with self.assertRaises(extract.ShapeMismatch) as raised:
            extract.extract(manifest(("job-1", "tools-4-rounds-1")), [job(calls=3)])
        self.assertIn("job-1: tools-4-rounds-1 expects 4 calls in 1 rounds, ran 3 in 1", raised.exception.mismatches)

    def test_a_failed_run_stays_in_the_evidence_with_what_it_reached(self) -> None:
        failed = job(status="failed", failure_code="response_unknown", calls=2,
                     stages=[stage(), stage(input_tokens=None, output=None, reasoning=None, send="unknown")])
        run = extract.extract(manifest(("job-1", "tools-4-rounds-3")), [failed])["runs"][0]

        self.assertEqual("response_unknown", run["failureCode"])
        self.assertEqual((2, 1, 2), (run["toolCalls"], run["approvalRounds"], run["providerCalls"]))
        self.assertEqual(0, run["answerTokens"])

    def test_what_is_not_evidence_is_refused(self) -> None:
        cases = {
            "not finished": job(status="running"),
            "rerun": job(attempts=2),
            "direct path": job(path="direct"),
            "not a live run": job(stages=[dict(stage(), mode="replay"), stage()]),
            "null is not evidence": job(stages=[stage(reasoning=None), stage()]),
            "no price": job(stages=[stage(model="other"), stage(model="other")]),
        }
        for message, row in cases.items():
            with self.subTest(message), self.assertRaisesRegex(extract.ExtractError, message):
                extract.extract(manifest(("job-1", "tools-1-rounds-1")), [row])

        with self.assertRaisesRegex(extract.ExtractError, "not in the ledger"):
            extract.extract(manifest(("job-2", "tools-1-rounds-1")), [job()])
        with self.assertRaisesRegex(extract.ExtractError, "named twice"):
            extract.extract(manifest(("job-1", "tools-1-rounds-1"), ("job-1", "tools-1-rounds-1")), [job()])
        with self.assertRaisesRegex(extract.ExtractError, "unknown scenario"):
            extract.extract(manifest(("job-1", "tools-2-rounds-1")), [job()])

    def test_runs_of_different_models_are_not_one_measurement(self) -> None:
        other = job("job-2", stages=[stage(model="jev"), stage(model="jev")])
        with self.assertRaisesRegex(extract.ExtractError, "one agent model"):
            extract.extract(manifest(("job-1", "tools-1-rounds-1"), ("job-2", "tools-1-rounds-1")), [job(), other])

    def test_the_command_exits_2_on_a_shape_mismatch_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps(manifest(("job-1", "tools-4-rounds-1"))), encoding="utf-8")
            (root / "ledger.json").write_text(json.dumps([job(calls=3)]), encoding="utf-8")
            code = extract.main([str(root / "manifest.json"), str(root / "ledger.json"), "--output", str(root / "out.json")])
            self.assertEqual(2, code)
            self.assertFalse((root / "out.json").exists())

    def test_the_scenarios_file_names_every_gate_scenario_within_the_call_limits(self) -> None:
        document = json.loads((ROOT / "scripts" / "chat_live_spike_scenarios.json").read_text(encoding="utf-8"))
        self.assertEqual(set(spike.SCENARIOS), set(document["scenarios"]))
        for name, scenario in document["scenarios"].items():
            rounds = scenario["intendedRounds"]
            calls = [call for round_ in rounds for call in round_]
            self.assertEqual(spike.SCENARIOS[name], (len(calls), len(rounds)), name)
            self.assertTrue(all(len(round_) <= 4 for round_ in rounds), name)
            self.assertLessEqual(calls.count("web_search"), 2, name)
            self.assertLessEqual(len(calls) - calls.count("web_search"), 6, name)


if __name__ == "__main__":
    unittest.main()
