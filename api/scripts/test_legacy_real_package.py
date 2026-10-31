"""Export-boundary regression for authorized legacy article projection."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import legacy_real_package as package
from legacy_real_import_smoke import company_bindings, fixture, write
from legacy_real_verify_closure import verify


class LegacyRealExportTest(unittest.TestCase):
    def test_unselected_body_quote_and_audit_stay_local(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            selection, geography, bindings = fixture(source)
            sentinel = "UNBOUND_BODY_AND_QUOTE_NEVER_EXPORT_59278"
            foreign = copy.deepcopy(selection["articles"][0])
            record = foreign["record"]
            record["article_id"] = "b" * 64
            record["body"] = "xx" + sentinel
            record["title"] = sentinel
            record["url"] = "https://unbound.invalid/" + sentinel
            foreign["article_version"] = package.sha(package.canonical({k: v for k, v in record.items() if k != "collected_at"}))
            selection["articles"].append(foreign)
            hidden = copy.deepcopy(selection["issues"][0])
            hidden["issue_id"] = "issue-unselected"
            hidden["candidate_ids"] = ["candidate-unselected"]
            hidden["article_refs"] = [{"article_id": record["article_id"], "article_version": foreign["article_version"]}]
            hidden["mentions"][0].update(article_id=record["article_id"], article_version=foreign["article_version"], title=sentinel)
            hidden["mentions"][0]["evidence"] = [{"article_id": record["article_id"], "article_version": foreign["article_version"], "start": 2, "end": len(record["body"]), "quote": sentinel}]
            hidden["relations"][0]["evidence"] = copy.deepcopy(hidden["mentions"][0]["evidence"])
            selection["issues"].append(hidden)
            audit = copy.deepcopy(selection["candidate_audit"][0])
            audit.update(candidate_id="candidate-unselected", issue_id="issue-unselected", reasons=[sentinel])
            audit["original_mention"] = copy.deepcopy(hidden["mentions"][0])
            selection["candidate_audit"].append(audit)
            selection["effective_review_decisions"].append({"target_id": "candidate-unselected", "decision": "reject",
                                                             "reason": sentinel})
            selection["review_exclusions"].append({"issue_id": "issue-unselected", "reason": sentinel})
            geography["records"].append({"issue_id": "issue-unselected", "decision": "source_supported", "reason": sentinel,
                                         "source_evidence_ids": ["geo-unselected"]})
            geography["evidence"].append({**hidden["mentions"][0]["evidence"][0], "evidence_id": "geo-unselected"})
            write(source / "LEGACY_SELECTION.json", selection)
            write(source / "GEOGRAPHY_REVIEW.json", geography)
            write(source / "SOURCE_PROVENANCE.json", {"schema": "zoop-legacy-source-provenance/1", "articles": [
                {"article_id": selection["articles"][0]["record"]["article_id"], "article_version": selection["articles"][0]["article_version"],
                 "body_sha256": package.sha(selection["articles"][0]["record"]["body"].encode())},
                {"article_id": record["article_id"], "article_version": foreign["article_version"], "title": sentinel, "quote": sentinel}]})
            output = root / "export"
            request, summary = package.prepare(source, output, bindings, company_bindings(selection), "synthetic-operator")
            self.assertEqual(1, summary["selectedIssues"])
            self.assertEqual(2, summary["retainedIssues"])
            exported = [p for p in output.iterdir() if p.is_file()]
            self.assertEqual({"manifest.json", "bundle.json", "geography.json", "source-pins.json", "source-provenance.json"}, {p.name for p in exported})
            for path in exported:
                self.assertNotIn(sentinel.encode(), path.read_bytes(), path.name)
                self.assertNotIn(record["article_id"].encode(), path.read_bytes(), path.name)
            bundle = json.loads((output / "bundle.json").read_bytes())
            self.assertEqual(["issue-synthetic-lab"], [r["issue_id"] for r in bundle["issues"]])
            self.assertEqual(1, len(bundle["candidate_audit"]))
            self.assertEqual(1, len(bundle["articles"]))
            manifest = json.loads((output / "manifest.json").read_bytes())
            self.assertEqual(package.sha((output / "bundle.json").read_bytes()), request["expectedBundleDigest"])
            self.assertEqual(package.sha((source / "LEGACY_SELECTION.json").read_bytes()), manifest["sourceInputDigests"]["bundle.json"])
            self.assertNotEqual(manifest["sourceInputDigests"]["bundle.json"], manifest["bundleDigest"])
            second = root / "repeat"
            repeated, _ = package.prepare(source, second, bindings, company_bindings(selection), "synthetic-operator")
            self.assertEqual(request, repeated)
            self.assertEqual({p.name: p.read_bytes() for p in exported}, {p.name: p.read_bytes() for p in second.iterdir()})

    def test_nested_selected_metadata_cannot_export_unbound_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            selection, _, bindings = fixture(source)
            sentinel = "UNBOUND_METADATA_QUOTE_37192"
            selection["origin"].setdefault("snapshot", {})["reason"] = "unrelated review: " + sentinel
            selection["selection_basis"] = "unrelated review: " + sentinel
            selection["candidate_audit"][0]["reasons"] = ["unrelated review: " + sentinel]
            selection["enabled_rules"] = [{"id": "R1@2", "summary": "unrelated review: " + sentinel}]
            selection["issues"][0]["zoop_approval"] = {"label": "unrelated review: " + sentinel}
            selected = selection["articles"][0]
            write(source / "LEGACY_SELECTION.json", selection)
            write(source / "SOURCE_PROVENANCE.json", {"schema": "zoop-legacy-source-provenance/1",
                  "articles": [{"article_id": selected["record"]["article_id"], "article_version": selected["article_version"],
                                "body_sha256": package.sha(selected["record"]["body"].encode()),
                                "retained_acquisition_matches": [{"metadata": {"content_hash": package.sha(selected["record"]["body"].encode()),
                                                                              "notes": "unrelated review: " + sentinel}}]}]})
            output = root / "package"
            package.prepare(source, output, bindings, company_bindings(selection), "synthetic-operator")
            for path in output.iterdir():
                self.assertNotIn(sentinel.encode(), path.read_bytes(), path.name)

    def test_graph_skipped_relation_evidence_must_have_selected_article(self):
        for relation_type in ("REPORTS", "PROVIDES_BACKGROUND", "FOLLOWS"):
            with self.subTest(relation_type=relation_type), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source"
                selection, _, bindings = fixture(source)
                issue = selection["issues"][0]
                foreign = selection["articles"][1]
                relation = copy.deepcopy(issue["relations"][0])
                relation.update(relation_id="relation-unbound", relation_type=relation_type,
                                source=issue["issue_id"] if relation_type == "FOLLOWS" else selection["articles"][0]["record"]["article_id"],
                                target="issue-unselected" if relation_type == "FOLLOWS" else issue["issue_id"])
                relation["evidence"] = [{"article_id": foreign["record"]["article_id"], "article_version": foreign["article_version"],
                                        "start": 0, "end": 7, "quote": "UNBOUND"}]
                issue["relations"].append(relation)
                write(source / "LEGACY_SELECTION.json", selection)
                output = root / "package"
                with self.assertRaisesRegex(ValueError, "selected export reference closure incomplete"):
                    package.prepare(source, output, bindings, company_bindings(selection), "synthetic-operator")
                self.assertFalse(output.exists())

    def test_missing_bindings_never_create_content_package(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            fixture(source)
            output = Path(directory) / "not-exported"
            with self.assertRaisesRegex(ValueError, "current article bindings required"):
                package.prepare(source, output, [], [], "synthetic-operator")
            self.assertFalse(output.exists())

    def test_company_mapping_pins_canonical_name_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            selection, _, grants = fixture(source)
            bindings = company_bindings(selection)
            bindings[0]["canonicalName"] = "Canonical Acme"
            first = root / "first"
            request, _ = package.prepare(source, first, grants, bindings, "synthetic-operator")
            self.assertEqual(selection["companies"], json.loads((first / "bundle.json").read_bytes())["companies"])
            self.assertEqual(bindings, json.loads((first / "manifest.json").read_bytes())["companyBindings"])
            self.assertEqual("passed", verify(source, first)["status"])
            second = root / "second"
            repeated, _ = package.prepare(source, second, grants, bindings, "synthetic-operator")
            self.assertEqual(request, repeated)
            self.assertEqual({p.name: p.read_bytes() for p in first.iterdir()},
                             {p.name: p.read_bytes() for p in second.iterdir()})
            bindings[0]["canonicalName"] = "New canonical"
            changed, _ = package.prepare(source, root / "changed", grants, bindings, "synthetic-operator")
            self.assertNotEqual(request["migrationId"], changed["migrationId"])

    def test_company_mapping_closure_is_independently_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            selection, _, grants = fixture(source)
            bindings = company_bindings(selection)
            output = root / "valid"
            package.prepare(source, output, grants, bindings, "synthetic-operator")
            manifest = json.loads((output / "manifest.json").read_bytes())
            cases = [[], bindings * 2, bindings + [{"companyId": "OTHER", "originalName": "Other", "canonicalName": "Other"}],
                     [{**bindings[0], "originalName": "Wrong"}], [{**bindings[0], "canonicalName": " "}],
                     [{**bindings[0], "aliases": ["Incoming"]}], {}]
            for index, invalid in enumerate(cases):
                with self.subTest(binding=invalid):
                    destination = root / str(index)
                    with self.assertRaisesRegex(ValueError, "company binding"):
                        package.prepare(source, destination, grants, invalid, "synthetic-operator")
                    self.assertFalse(destination.exists())
                    write(output / "manifest.json", {**manifest, "companyBindings": invalid})
                    with self.assertRaises(AssertionError):
                        verify(source, output)

    def test_legacy3_unknown_policy_is_pinned_and_preserves_original_country(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            selection, geography, bindings = fixture(source)
            audit = selection["candidate_audit"][0]
            audit["source_audit_record_sha256"] = package.sha(package.canonical(audit))
            write(source / "LEGACY_SELECTION.json", selection)
            geography["records"][0].update(decision="unresolved", classification=None, source_evidence_ids=[])
            geography["evidence"] = []
            write(source / "GEOGRAPHY_REVIEW.json", geography)
            policy = {"schemaVersion": "zoop-legacy-metadata-policy-1", "policyVersion": "legacy-real-projection-3", "issues": [{
                "issueId": "issue-synthetic-lab", "sourceAuditDigests": [audit["source_audit_record_sha256"]],
                "geography": {"mode": "unknown", "reasonCode": "not-supported"}, "eventTime": {"mode": "unknown", "reasonCode": "not-supported"},
                "period": {"mode": "preserve"}, "decisionRef": "synthetic-policy", "decisionVersion": "1"}]}
            policy_path = root / "policy.json"
            write(policy_path, policy)
            output = root / "package3"
            _, result = package.prepare(source, output, bindings, company_bindings(selection), "synthetic-operator", policy_path)
            self.assertEqual(1, result["selectedIssues"])
            manifest = json.loads((output / "manifest.json").read_bytes())
            self.assertEqual("zoop-legacy-real-manifest-3", manifest["schemaVersion"])
            self.assertEqual(policy_path.read_bytes(), (output / "metadata-policy.json").read_bytes())
            self.assertEqual(package.sha(policy_path.read_bytes()), manifest["metadataPolicyDigest"])
            self.assertEqual(manifest["metadataPolicyDigest"], manifest["sourceInputDigests"]["metadata-policy.json"])
            self.assertEqual(["KR"], json.loads((output / "bundle.json").read_bytes())["candidate_audit"][0]["original_mention"]["countries"])
            self.assertEqual("passed", verify(source, output, policy_path)["status"])
            policy["issues"][0]["geography"] = {"mode": "preserve"}
            write(policy_path, policy)
            with self.assertRaisesRegex(ValueError, "preserved geography requires source support"):
                package.prepare(source, root / "malformed-known", bindings, company_bindings(selection), "synthetic-operator", policy_path)
            with self.assertRaisesRegex(ValueError, "no policy-supported"):
                package.prepare(source, root / "old2", bindings, company_bindings(selection), "synthetic-operator")


if __name__ == "__main__":
    unittest.main()
