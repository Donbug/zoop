from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "chat_operations_readiness", ROOT / "scripts" / "chat_operations_readiness.py"
)
assert SPEC and SPEC.loader
readiness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = readiness
SPEC.loader.exec_module(readiness)
spike = readiness.spike


def live_evidence(candidate: str = "a" * 40, samples: int = 5) -> dict:
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
                # The provider total (reasoning included), its reasoning part and the final answer alone.
                "outputTokens": 4_000,
                "reasoningTokens": 3_000,
                "answerTokens": 1_000,
                "costUsd": "0.0123",
                "failureCode": None,
            })
    return {
        "schemaVersion": spike.SCHEMA,
        "candidateCommit": candidate,
        "approvedBy": "security-reviewer",
        "approvalRef": "AI-100",
        "environment": "isolated-live-spike",
        "policyVersion": "ZOOP-AIG-001-v0.11",
        "model": "gpt-6-luna",
        "promptVersion": "chat-agent-test",
        "toolRegistryVersion": "chat-tools-test",
        "runs": runs,
    }


def manifest(candidate: str = "a" * 40) -> dict:
    approved_at = "2026-10-29T00:00:00+00:00"
    selections = {name: next(iter(values)) for name, values in readiness.DECISIONS.items()}
    decisions = {
        name: {
            "status": "approved",
            "selection": selection,
            "decisionRef": f"AI-{index + 1}",
            "ownerRole": "platform-owner",
            "approvedAt": approved_at,
        }
        for index, (name, selection) in enumerate(selections.items())
    }
    return {
        "schemaVersion": readiness.SCHEMA,
        "candidateCommit": candidate,
        "environment": "production-candidate",
        "recordedAt": "2026-10-29T01:00:00+00:00",
        "decisions": decisions,
        "preflight": {
            "status": "passed",
            "observedAt": "2026-10-29T00:30:00+00:00",
            "endpointRevision": "mcp-ingress-v1",
            "evidenceRef": "RUN-1242#probe",
            "bearerChallengeObserved": True,
            "redirectFollowed": False,
        },
        "rollout": {
            "mcpEnabled": False,
            "agentEnabled": False,
            "enableChangeRef": "OPS-42",
            "rollbackOwnerRole": "platform-oncall",
        },
    }


class ChatOperationsReadinessTest(unittest.TestCase):
    def _files(self, manifest_value: dict, evidence_value: dict):
        directory = tempfile.TemporaryDirectory(dir=ROOT)
        root = Path(directory.name)
        manifest_path = root / "readiness.json"
        evidence_path = root / "live.json"
        manifest_path.write_text(json.dumps(manifest_value), encoding="utf-8")
        evidence_path.write_text(json.dumps(evidence_value), encoding="utf-8")
        return directory, manifest_path, evidence_path

    def test_complete_manifest_and_matching_live_gate_pass(self):
        directory, manifest_path, evidence_path = self._files(manifest(), live_evidence())
        with directory:
            result = readiness.evaluate(readiness.load(manifest_path), evidence_path)
        self.assertEqual("passed", result["gate"])
        self.assertEqual(20, result["liveSpike"]["runs"])

    def test_missing_decision_and_unapproved_retention_are_rejected(self):
        value = manifest()
        del value["decisions"]["privacyDisclosure"]
        directory, manifest_path, _ = self._files(value, live_evidence())
        with directory, self.assertRaisesRegex(readiness.ReadinessError, "privacyDisclosure"):
            readiness.load(manifest_path)
        value = manifest()
        value["decisions"]["openaiRetention"]["selection"] = "store-false"
        directory, manifest_path, _ = self._files(value, live_evidence())
        with directory, self.assertRaisesRegex(readiness.ReadinessError, "responses-store-true-approved"):
            readiness.load(manifest_path)
        value = manifest()
        value["decisions"]["openaiRetention"]["selection"] = ["responses-store-true-approved"]
        directory, manifest_path, _ = self._files(value, live_evidence())
        with directory, self.assertRaisesRegex(readiness.ReadinessError, "responses-store-true-approved"):
            readiness.load(manifest_path)

    def test_urls_and_enabled_flags_are_rejected(self):
        value = manifest()
        value["decisions"]["httpsIngress"]["decisionRef"] = "https://tickets.example/42"
        directory, manifest_path, _ = self._files(value, live_evidence())
        with directory, self.assertRaisesRegex(readiness.ReadinessError, "not a URL or secret"):
            readiness.load(manifest_path)
        value = manifest()
        value["rollout"]["mcpEnabled"] = True
        directory, manifest_path, _ = self._files(value, live_evidence())
        with directory, self.assertRaisesRegex(readiness.ReadinessError, "feature flags"):
            readiness.load(manifest_path)

    def test_preflight_must_observe_bearer_without_redirect(self):
        value = manifest()
        value["preflight"]["bearerChallengeObserved"] = False
        directory, manifest_path, _ = self._files(value, live_evidence())
        with directory, self.assertRaisesRegex(readiness.ReadinessError, "401 Bearer"):
            readiness.load(manifest_path)
        value = manifest()
        value["preflight"]["redirectFollowed"] = True
        directory, manifest_path, _ = self._files(value, live_evidence())
        with directory, self.assertRaisesRegex(readiness.ReadinessError, "must not follow"):
            readiness.load(manifest_path)

    def test_commit_mismatch_and_incomplete_live_matrix_fail_closed(self):
        directory, manifest_path, evidence_path = self._files(manifest(), live_evidence("b" * 40))
        with directory:
            result = readiness.evaluate(readiness.load(manifest_path), evidence_path)
        self.assertEqual("failed", result["gate"])
        self.assertIn("candidateCommit differs", result["failures"][-1])

        evidence = live_evidence()
        evidence["runs"] = [run for run in evidence["runs"] if run["scenario"] != "tools-8-rounds-3"]
        directory, manifest_path, evidence_path = self._files(manifest(), evidence)
        with directory:
            result = readiness.evaluate(readiness.load(manifest_path), evidence_path)
        self.assertEqual("failed", result["gate"])
        self.assertTrue(any("tools-8-rounds-3" in failure for failure in result["failures"]))

    def test_the_checker_runs_isolated_without_its_directory_on_sys_path(self):
        # python -I (and -P) leave the script's directory off sys.path; the spike checker beside it still loads.
        for flag in ("-I", "-P"):
            done = subprocess.run([sys.executable, flag, str(ROOT / "scripts" / "chat_operations_readiness.py"), "--help"],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(0, done.returncode, flag + ": " + done.stderr)


if __name__ == "__main__":
    unittest.main()
