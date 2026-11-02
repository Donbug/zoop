#!/usr/bin/env python3
"""Check transferred legacy files against retained local inputs without exporting source text."""
import argparse
import hashlib
import json
from pathlib import Path

import legacy_real_package as package


def verify(source: Path, transfer: Path, metadata_policy: Path | None = None):
    originals = {name: (source / filename).read_bytes() for name, filename in package.FILES.items()}
    files = {name: (transfer / name).read_bytes() for name in (*package.FILES, "manifest.json")}
    manifest = json.loads(files["manifest.json"])
    metadata = manifest["schemaVersion"] == "zoop-legacy-real-manifest-3"
    assert metadata or manifest["schemaVersion"] == "zoop-legacy-real-manifest-2"
    if metadata:
        assert metadata_policy is not None
        originals["metadata-policy.json"] = metadata_policy.read_bytes()
        files["metadata-policy.json"] = (transfer / "metadata-policy.json").read_bytes()
        assert files["metadata-policy.json"] == originals["metadata-policy.json"]
        assert manifest["metadataPolicyDigest"] == package.sha(files["metadata-policy.json"])
    assert manifest["sourceInputDigests"] == {name: package.sha(data) for name, data in originals.items()}
    for name, key in (("bundle.json", "bundleDigest"), ("geography.json", "geographyDigest"),
                      ("source-pins.json", "sourcePinsDigest"), ("source-provenance.json", "provenanceDigest")):
        assert manifest[key] == package.sha(files[name]), name
    assert {p.name for p in transfer.iterdir()} == set(files)
    raw = json.loads(originals["bundle.json"])
    original_geo = json.loads(originals["geography.json"])
    bundle = json.loads(files["bundle.json"])
    geo = json.loads(files["geography.json"])
    provenance = json.loads(files["source-provenance.json"])
    selected = set(manifest["selectedIssueIds"])
    if metadata:
        policy = json.loads(files["metadata-policy.json"])
        assert set(package.metadata_policies(policy, raw)) == selected
    issues = [{key: value for key, value in row.items() if key != "zoop_approval"}
              for row in raw["issues"] if row["issue_id"] in selected]
    assert bundle["issues"] == issues and len(issues) == len(selected)
    needed = {(a["article_id"], a["article_version"]) for issue in issues for a in issue["article_refs"]}
    assert bundle["articles"] == [a for a in raw["articles"] if (a["record"]["article_id"], a["article_version"]) in needed]
    candidate_ids = {id for issue in issues for id in issue["candidate_ids"]}
    source_audits = [a for a in raw["candidate_audit"] if a["candidate_id"] in candidate_ids]
    audits = bundle["candidate_audit"]
    assert len(audits) == len(source_audits)
    for actual, original in zip(audits, source_audits):
        allowed = {"active", "candidate_id", "candidate_revision", "invalidation_reason", "issue_id",
                   "original_mention", "policy_version", "publication_resolution", "status", "validation", "source_audit_record_sha256"}
        assert set(actual) == set(original) & allowed
        assert all(actual[key] == original[key] for key in allowed - {"validation"} if key in actual)
        assert set(actual["validation"]) <= {"candidate_id", "candidate_revision", "policy_version", "verdicts", "field_verdicts", *({"trace"} if metadata else set())}
        assert actual["validation"]["verdicts"] == [
            {**v, "reason": v["reason"] if metadata else v["reason"].split(" Numerical diagnostics: ", 1)[0]}
            for v in original["validation"]["verdicts"]]
        if metadata and "trace" in original["validation"]:
            assert actual["validation"]["trace"] == original["validation"]["trace"]
        if "field_verdicts" in actual["validation"]:
            assert actual["validation"]["field_verdicts"] == [
                {**v, "reason": v["reason"] if metadata else v["reason"].split(" Numerical diagnostics: ", 1)[0]}
                for v in original["validation"]["field_verdicts"]]
    company_ids = {r["target"] for issue in issues for r in issue["relations"] if r["relation_type"] == "INVOLVES"}
    relation_ids = {r["relation_id"] for issue in issues for r in issue["relations"]}
    assert bundle["effective_review_decisions"] == [
        {k: r[k] for k in ("id", "target_id", "target_type", "decision")} for r in raw["effective_review_decisions"]
        if r["target_id"] in selected | candidate_ids | relation_ids]
    assert bundle["review_exclusions"] == [
        {k: r[k] for k in ("issue_id", "relation_id", "candidate_ids", "authority_decision", "publication_decision")}
        for r in raw["review_exclusions"] if r["issue_id"] in selected]
    assert bundle["enabled_rules"] == [{"id": r["id"]} for r in raw["enabled_rules"]]
    assert bundle["companies"] == [{"company_id": c["company_id"], "name": c["name"]}
                                  for c in raw["companies"] if c["company_id"] in company_ids]
    bindings = manifest["companyBindings"]
    assert isinstance(bindings, list)
    original_companies = {row["company_id"]: row["name"] for row in bundle["companies"]}
    assert len(original_companies) == len(bundle["companies"])
    seen = set()
    for binding in bindings:
        assert isinstance(binding, dict) and set(binding) == {"companyId", "originalName", "canonicalName"}
        assert all(isinstance(value, str) and value.strip() for value in binding.values())
        assert binding["companyId"] not in seen
        assert original_companies.get(binding["companyId"]) == binding["originalName"]
        seen.add(binding["companyId"])
    assert seen == company_ids == set(original_companies)
    assert [row["companyId"] for row in bindings] == sorted(seen)
    origin = raw["origin"]
    expected_origin = {"review_revision": origin["review_revision"], "rule_revision": origin["rule_revision"],
                       "snapshot": {k: origin["snapshot"][k] for k in ("id", "sha256", "content_digest", "seed_sha256")}}
    assert bundle["origin"] == manifest["legacyOrigin"] == expected_origin
    assert bundle["selection_basis"] == ("selected-bound-article-and-metadata-policy" if metadata else "selected-bound-article-and-geography")
    geo_rows = [row for row in original_geo["records"] if row["issue_id"] in selected]
    ids = {id for row in geo_rows for id in row["source_evidence_ids"]}
    assert geo["records"] == [{**{k: r[k] for k in ("issue_id", "decision", "classification",
                                                "review_policy_version", "source_evidence_ids", "country_codes", "regions")},
                              **({"decision_id": r["decision_id"]} if "decision_id" in r else {}),
                              "reviewer": "local-source-review", "reason": "selected_source_evidence"} for r in geo_rows]
    assert set(geo) == {"schema", "policy_version", "review_date", "records", "evidence"}
    assert geo["evidence"] == [e for e in original_geo["evidence"] if e["evidence_id"] in ids]
    source_provenance = json.loads(originals["source-provenance.json"])
    original_articles = {(a["article_id"], a["article_version"]): a for a in source_provenance.get("articles", [])}
    assert set(provenance) == {"schema", "articles"} and provenance["schema"] == "zoop-legacy-export-provenance/1"
    expected_articles = []
    for article in bundle["articles"]:
        record = article["record"]
        original = original_articles.get((record["article_id"], article["article_version"]), {})
        expected_articles.append({"article_id": record["article_id"], "article_version": article["article_version"],
                                  "body_sha256": package.sha(record["body"].encode()),
                                  "retained_input_record_hashes": [a["record_sha256"] for a in original.get("retained_input_matches", [])],
                                  "retained_acquisition_content_hashes": [a["metadata"]["content_hash"] for a in original.get("retained_acquisition_matches", [])]})
    assert provenance["articles"] == expected_articles
    ledger = manifest["selectionLedger"]
    assert len(ledger) == len(raw["issues"]) and {r["issueId"] for r in ledger} == {r["issue_id"] for r in raw["issues"]}
    assert {r["issueId"] for r in ledger if r["reason"] == "selected"} == selected
    assert all(set(r) == {"issueId", "reason"} for r in ledger)
    original_pins = json.loads(originals["source-pins.json"])
    expected_pins = ({"schema": "zoop-legacy-export-source-pins/1",
                      "originalDigest": package.sha(originals["source-pins.json"]),
                      "upstreamInputClaims": [{"bytes": f["bytes"], "sha256": f["sha256"]} for f in original_pins["files"]]}
                     if "files" in original_pins else original_pins)
    assert json.loads(files["source-pins.json"]) == expected_pins
    hidden = [a for a in raw["articles"] if (a["record"]["article_id"], a["article_version"]) not in needed]
    strings = set()
    def visit(value):
        if isinstance(value, dict):
            for child in value.values(): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
        elif isinstance(value, str): strings.add(value)
    for data in files.values(): visit(json.loads(data))
    hidden_ids = {a["record"]["article_id"] for a in hidden}
    hidden_text = {a["record"][key] for a in hidden for key in ("body", "title")}
    for issue in raw["issues"]:
        if issue["issue_id"] in selected: continue
        for item in (*issue["mentions"], *issue["relations"]):
            hidden_text.update(e["quote"] for e in item.get("evidence", []) if e["article_id"] in hidden_ids)
    hidden_text.update(e["quote"] for e in original_geo["evidence"] if e["article_id"] in hidden_ids)
    assert not hidden_ids.intersection(strings), "unselected article ID escaped"
    assert all(not value or all(value not in exposed for exposed in strings)
               for value in hidden_text), "unselected source text embedded in transfer"
    return {"status": "passed", "selectedIssues": len(issues), "selectedArticles": len(needed),
            "selectedCompanies": len(company_ids), "retainedIssues": len(raw["issues"]),
            "unselectedArticles": len(hidden), "unselectedBodiesOrQuotesExported": 0,
            "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in files.items()},
            "sourceInputDigests": manifest["sourceInputDigests"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--metadata-policy", type=Path)
    args = parser.parse_args()
    with args.result.open("xb") as out:
        out.write(package.canonical(verify(args.source, args.package, args.metadata_policy)))
    args.result.chmod(0o600)
