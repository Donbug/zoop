from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_nonfixture_smoke as smoke


class ChatNonfixtureSmokeTest(unittest.TestCase):
    def probe(self):
        return {"schemaVersion": smoke.SCHEMA, "graphVersionId": "gv-first47", "companyId": "KRX:000660",
                "evidenceId": "ev-" + "a" * 64, "minimumDocuments": 1}

    def responses(self):
        version, company, evidence = "gv-first47", "KRX:000660", "ev-" + "a" * 64
        graph = {"metadata": {"graphVersion": version},
                 "nodes": [{"id": company, "kind": "company"}, {"id": "issue:one", "kind": "issue"}],
                 "edges": [{"id": "edge:one", "evidenceIds": [evidence]}]}
        documents = {"metadata": {"graphVersion": version},
                     "items": [{"id": "article:one", "quotes": [{"evidenceId": evidence}]}]}
        evidence_response = {"id": evidence, "metadata": {"graphVersion": version}, "quoteVerified": True,
                             "articleId": "article:one", "articleVersion": "v1", "eventIds": ["issue:one"]}
        return graph, documents, evidence_response

    def test_passes_same_version_public_chat_data_path(self):
        report = smoke.evaluate(self.probe(), *self.responses())
        self.assertEqual("passed", report["status"])
        self.assertEqual({"nodes": 2, "edges": 1, "documents": 1, "quotes": 1}, report["observed"])

    def test_fails_cross_version_and_missing_document_evidence(self):
        graph, documents, evidence = self.responses()
        documents["metadata"]["graphVersion"] = "gv-other"
        documents["items"][0]["quotes"] = []
        report = smoke.evaluate(self.probe(), graph, documents, evidence)
        self.assertEqual("failed", report["status"])
        self.assertEqual(["document_version_mismatch", "evidence_not_in_company_documents"], report["failures"])

    def test_external_base_url_requires_https(self):
        with self.assertRaises(smoke.SmokeError):
            smoke.base_url("http://api.example.test")
        self.assertEqual("http://127.0.0.1:8080", smoke.base_url("http://127.0.0.1:8080"))


if __name__ == "__main__":
    unittest.main()
