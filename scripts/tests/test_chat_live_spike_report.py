from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("chat_live_spike_report", ROOT / "scripts" / "chat_live_spike_report.py")
assert SPEC and SPEC.loader
spike = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = spike
SPEC.loader.exec_module(spike)


def evidence(samples: int = 5) -> dict:
    started = datetime(2026, 10, 29, tzinfo=timezone.utc)
    runs = []
    for scenario, (calls, rounds) in spike.SCENARIOS.items():
        for index in range(samples):
            runs.append({
                "runId": f"{scenario}-{index}",
                "scenario": scenario,
                "mode": "live",
                "status": "completed",
                "startedAt": started.isoformat(),
                "committedAt": (started + timedelta(seconds=20 + index)).isoformat(),
                "toolCalls": calls,
                "approvalRounds": rounds,
                "providerCalls": rounds + 1,
                "inputTokens": 10_000,
                "outputTokens": 1_000,
                "reasoningTokens": 3_000,
                "costUsd": "0.0123",
                "failureCode": None,
            })
    return {
        "schemaVersion": spike.SCHEMA,
        "candidateCommit": "a" * 40,
        "approvedBy": "synthetic-approver",
        "approvalRef": "TEST-1",
        "environment": "isolated-live-spike",
        "policyVersion": "ZOOP-AIG-001-v0.11",
        "model": "gpt-6-luna",
        "promptVersion": "chat-agent-test",
        "toolRegistryVersion": "chat-tools-test",
        "runs": runs,
    }


class ChatLiveSpikeReportTest(unittest.TestCase):
    def _load(self, value: dict):
        # Keep test artifacts under the checkout so restricted local runners and CI use
        # the same writable boundary; the directory is removed before the test returns.
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return spike.load(path)

    def test_complete_content_free_matrix_passes_and_reports_nearest_rank_percentiles(self):
        metadata, runs = self._load(evidence())
        result = spike.report(metadata, runs, 5)
        self.assertEqual("passed", result["gate"])
        self.assertEqual(22.0, result["scenarios"]["tools-1-rounds-1"]["p50Seconds"])
        self.assertEqual(24.0, result["scenarios"]["tools-8-rounds-3"]["p95Seconds"])
        self.assertEqual("0.2460", result["totals"]["costUsd"])

    def test_missing_eight_call_case_keeps_the_release_gate_closed(self):
        value = evidence()
        value["runs"] = [run for run in value["runs"] if run["scenario"] != "tools-8-rounds-3"]
        metadata, runs = self._load(value)
        result = spike.report(metadata, runs, 5)
        self.assertEqual("failed", result["gate"])
        self.assertIn("tools-8-rounds-3: needs 5 samples, found 0", result["failures"])

    def test_late_commit_and_unknown_provider_outcome_fail(self):
        value = evidence()
        value["runs"][0]["committedAt"] = "2026-10-29T00:00:46+00:00"
        value["runs"][1]["status"] = "failed"
        value["runs"][1]["failureCode"] = "response_unknown"
        metadata, runs = self._load(value)
        result = spike.report(metadata, runs, 5)
        self.assertTrue(any("exceeded 45" in failure for failure in result["failures"]))
        self.assertTrue(any("provider outcome is unknown" in failure for failure in result["failures"]))

    def test_content_fields_and_unknown_cost_are_rejected(self):
        value = evidence()
        value["runs"][0]["question"] = "must never be retained"
        with self.assertRaisesRegex(spike.EvidenceError, "extra=.*question"):
            self._load(value)
        value = evidence()
        value["runs"][0]["costUsd"] = None
        with self.assertRaisesRegex(spike.EvidenceError, "null is not evidence"):
            self._load(value)

    def test_candidate_commit_and_completed_provider_call_count_are_fixed(self):
        value = evidence()
        value["candidateCommit"] = "main"
        with self.assertRaisesRegex(spike.EvidenceError, "40-character Git commit"):
            self._load(value)
        value = evidence()
        value["runs"][0]["providerCalls"] += 1
        with self.assertRaisesRegex(spike.EvidenceError, r"approvalRounds \+ 1"):
            self._load(value)


if __name__ == "__main__":
    unittest.main()
