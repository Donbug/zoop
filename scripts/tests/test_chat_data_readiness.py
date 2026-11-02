import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_data_readiness as readiness


class ChatDataReadinessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)
        (self.root / ".zoop-artifact-store-id").write_text("first47-store\n", encoding="utf-8")
        (self.root / "graph_snapshot").mkdir()
        (self.root / "verification_receipt").mkdir()
        self.snapshot = self.artifact("graph_snapshot/active.json", b'{"snapshot":1}')
        self.receipt = self.artifact("verification_receipt/active.json", b'{"receipt":1}', source=True)

    def tearDown(self):
        self.temp.cleanup()

    def artifact(self, relative, content, source=False):
        target = self.root / relative
        target.write_bytes(content)
        value = {"storageUri": "artifact-root:" + relative, "sha256": hashlib.sha256(content).hexdigest(),
                 "bytes": len(content)}
        if source:
            value.update(role="receipt", ordinal=0)
        return value

    def expected(self):
        return {"schemaVersion": readiness.EXPECTATION_SCHEMA, "datasetId": "first47",
                "activeGraphVersionId": "gv-first47", "requirePreviousNonFixture": False,
                "expectedArtifactStoreId": "first47-store", "minimumCounts": {"companies": 47, "evidence": 1},
                "minimumActiveGraphCounts": {"issueCount": 1, "articleCount": 1},
                "requiredCompanyIds": [f"company-{index:02d}" for index in range(47)]}

    def observed(self):
        counts = {key: 0 for key in readiness.COUNT_KEYS}
        counts.update(companies=47, articles=1, availableArticles=1, articleVersions=1, evidence=1,
                      verifiedEvidence=1, nonFixtureGraphVersions=1)
        return {"schemaVersion": readiness.INVENTORY_SCHEMA,
                "database": {"postgresVersion": "16.13", "latestMigration": "20261101000000"},
                "counts": counts, "companyIds": [f"company-{index:02d}" for index in range(47)],
                "activeGraph": {"id": "gv-first47", "sequence": 3, "kind": "snapshot", "active": True,
                                "publishedAt": "2026-11-02T00:00:00Z", "issueCount": 1, "relationCount": 0,
                                "articleCount": 1, "snapshot": self.snapshot, "sourceArtifacts": [self.receipt]},
                "previousNonFixtureGraph": None}

    def test_passes_first_native_dataset_and_verifies_registered_files(self):
        report = readiness.evaluate(self.expected(), self.observed(), self.root)
        self.assertEqual("passed", report["status"])
        self.assertEqual(2, report["artifactFilesChecked"])
        self.assertEqual([], report["failures"])

    def test_fails_fixture_missing_company_and_tampered_artifact(self):
        observed = self.observed()
        observed["activeGraph"]["kind"] = "fixture"
        observed["companyIds"].pop()
        (self.root / "graph_snapshot" / "active.json").write_bytes(b"tampered")
        report = readiness.evaluate(self.expected(), observed, self.root)
        checks = {failure["check"] for failure in report["failures"]}
        self.assertEqual("failed", report["status"])
        self.assertIn("active_graph_nonfixture", checks)
        self.assertIn("required_companies_missing", checks)
        self.assertIn("active_artifact:snapshot:artifact_size_mismatch", checks)

    def test_requires_previous_nonfixture_when_q05_gate_is_enabled(self):
        expected = self.expected()
        expected["requirePreviousNonFixture"] = True
        report = readiness.evaluate(expected, self.observed(), self.root)
        self.assertEqual([{"check": "previous_nonfixture_graph_missing"}], report["failures"])

    def test_rejects_unknown_manifest_fields(self):
        expected = self.expected()
        expected["token"] = "must-not-be-accepted"
        path = self.root / "expectation.json"
        path.write_text(json.dumps(expected), encoding="utf-8")
        with self.assertRaises(readiness.InvalidInput):
            readiness.expectation(path)


if __name__ == "__main__":
    unittest.main()
