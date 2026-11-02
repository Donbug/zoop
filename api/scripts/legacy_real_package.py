#!/usr/bin/env python3
"""Package retained legacy-real files for the serving-side operator importer.

Bindings are current, separately authorized source/grant/revision facts, never inferred
from historical model-send flags. Without bindings the package is content-only and the
importer refuses publication at its current-grant gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

FILES = {"bundle.json": "LEGACY_SELECTION.json", "geography.json": "GEOGRAPHY_REVIEW.json",
         "source-pins.json": "SOURCE_PINS.json", "source-provenance.json": "SOURCE_PROVENANCE.json"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()

ALLOWED_REASON = "Every required check satisfies the configured probability policy."
HOLD_REASON = re.compile(r"Support or contradiction probability requires review: (?:participant_role:[0-9]+|country:[0-9]+|role)(?:, (?:participant_role:[0-9]+|country:[0-9]+|role))*")
HEX = re.compile(r"[0-9a-f]{64}")

def closed(value, required, optional=()):
    if not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError("unsupported selected metadata")


def review_reason(reason):
    if reason != ALLOWED_REASON and not HOLD_REASON.fullmatch(reason):
        raise ValueError("selected review reason unsupported")




def audit_projection(audit, metadata=False):
    validation = audit["validation"]
    resolution = audit["publication_resolution"]
    def verdict(row, key):
        closed(row, (key, "decision", "reason"))
        reason = row["reason"] if metadata else row["reason"].split(" Numerical diagnostics: ", 1)[0]
        if not metadata:
            review_reason(reason)
        return {key: row[key], "decision": row["decision"], "reason": reason}
    projected = {key: audit[key] for key in ("active", "candidate_id", "candidate_revision", "invalidation_reason",
                                             "issue_id", "original_mention", "policy_version", "status")}
    if resolution["type"] == "historical_allow":
        projected["publication_resolution"] = {"type": "historical_allow"}
    elif resolution["type"] == "existing_enabled_publication_rule" and resolution["rule_id"] == "R1@2":
        effect = resolution["effect"]
        closed(effect, ("participants", "relations", "dropped"))
        if (not all(type(index) is int and index >= 0 for index in effect["participants"])
                or not all(re.fullmatch(r"relation-[A-Za-z0-9-]{1,100}", rid)
                           for key in ("relations", "dropped") for rid in effect[key])):
            raise ValueError("selected review resolution unsupported")
        projected["publication_resolution"] = {"type": resolution["type"], "rule_id": "R1@2",
                                                "effect": {key: effect[key] for key in ("participants", "relations", "dropped")}}
    else:
        raise ValueError("selected review resolution unsupported")
    projected["validation"] = {key: validation[key] for key in ("candidate_id", "candidate_revision", "policy_version")}
    if (validation["candidate_id"] != audit["candidate_id"]
            or validation["candidate_revision"] != audit["candidate_revision"]
            or validation["policy_version"] != audit["policy_version"]):
        raise ValueError("selected review revision mismatch")
    projected["validation"]["verdicts"] = [verdict(v, "target") for v in validation["verdicts"]]
    if "field_verdicts" in validation:
        projected["validation"]["field_verdicts"] = [verdict(v, "field") for v in validation["field_verdicts"]]
    if metadata and "trace" in validation:
        projected["validation"]["trace"] = validation["trace"]
    if "source_audit_record_sha256" in audit:
        if not HEX.fullmatch(audit["source_audit_record_sha256"]):
            raise ValueError("selected provenance hash invalid")
        projected["source_audit_record_sha256"] = audit["source_audit_record_sha256"]
    for key in ("candidate_id", "issue_id", "candidate_revision", "policy_version"):
        if not re.fullmatch(r"[A-Za-z0-9:._@-]{1,200}", projected[key]):
            raise ValueError("selected review identifier invalid")
    return projected


def origin_projection(origin):
    snapshot = origin["snapshot"]
    if (type(origin["review_revision"]) is not int or origin["review_revision"] < 0
            or type(origin["rule_revision"]) is not int or origin["rule_revision"] < 0
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", snapshot["id"])
            or not all(HEX.fullmatch(snapshot[key]) for key in ("sha256", "content_digest", "seed_sha256"))):
        raise ValueError("source origin claims invalid")
    return {"review_revision": origin["review_revision"], "rule_revision": origin["rule_revision"],
            "snapshot": {key: snapshot[key] for key in ("id", "sha256", "content_digest", "seed_sha256")}}


def provenance_projection(article, source):
    record = article["record"]
    item = {"article_id": record["article_id"], "article_version": article["article_version"],
            "body_sha256": sha(record["body"].encode("utf-8")),
            "retained_input_record_hashes": [entry["record_sha256"] for entry in source.get("retained_input_matches", [])],
            "retained_acquisition_content_hashes": [entry["metadata"]["content_hash"] for entry in source.get("retained_acquisition_matches", [])]}
    if source and item["body_sha256"] != source["body_sha256"]:
        raise ValueError("selected provenance body hash mismatch")
    if not all(HEX.fullmatch(value) for value in (item["article_version"], item["body_sha256"],
            *item["retained_input_record_hashes"], *item["retained_acquisition_content_hashes"])):
        raise ValueError("selected provenance hash invalid")
    return item



def metadata_policies(policy, selection):
    closed(policy, ("schemaVersion", "policyVersion", "issues"))
    if policy["schemaVersion"] != "zoop-legacy-metadata-policy-1" or policy["policyVersion"] != "legacy-real-projection-3":
        raise ValueError("metadata policy version invalid")
    issues = {issue["issue_id"]: issue for issue in selection["issues"]}
    audits = {audit["candidate_id"]: audit for audit in selection["candidate_audit"]}
    rows = {}
    for row in policy["issues"]:
        closed(row, ("issueId", "sourceAuditDigests", "geography", "eventTime", "period", "decisionRef", "decisionVersion"))
        ident = row["issueId"]
        if ident not in issues or ident in rows or any(not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", row[key])
                                                       for key in ("decisionRef", "decisionVersion")):
            raise ValueError("metadata policy identity invalid")
        expected = sorted({audits[candidate]["source_audit_record_sha256"] for candidate in issues[ident]["candidate_ids"]})
        if not expected or row["sourceAuditDigests"] != expected or any(not HEX.fullmatch(value) for value in expected):
            raise ValueError("metadata policy audit pin mismatch")
        for key in ("geography", "eventTime", "period"):
            field = row[key]
            if field["mode"] == "preserve":
                closed(field, ("mode",))
            else:
                closed(field, ("mode", "reasonCode"))
                if field["mode"] != "unknown" or field["reasonCode"] not in ("not-stated", "not-supported", "conflicting"):
                    raise ValueError("metadata policy field invalid")
        rows[ident] = row
    return rows


def metadata_only_hold(issue, audit, policy):
    validation = audit["validation"]
    if policy is None or audit["status"] != "HOLD" or "trace" not in validation:
        return False
    trace = validation["trace"]
    closed(trace, ("contract_version", "decision_policy", "model", "observations", "provider"))
    thresholds = trace["decision_policy"]
    if thresholds != {"support_min": 0.65, "contradiction_max": 0.1, "reject_min": 0.9}:
        raise ValueError("historical core policy unsupported")
    mention = audit["original_mention"]
    required = {("issue", check) for check in ("concrete_event", "title", "event_type", "action", "assertion_status", "background")}
    if mention.get("target") is not None:
        required.add(("issue", "target"))
    for index in range(len(mention["participants"])):
        required.update({("issue", f"participant_identity:{index}"), ("issue", f"participant_role:{index}")})
    for relation in issue["relations"]:
        if audit["candidate_id"] not in relation["candidate_ids"]:
            continue
        target, kind = relation["relation_id"], relation["relation_type"]
        required.add((target, kind))
        if kind == "INVOLVES":
            required.add((target, "assertion_status"))
            if relation["role"] is not None:
                required.add((target, "role"))
    observed, field_failure = set(), False
    for observation in trace["observations"]:
        closed(observation, ("target", "check", "choice", "confidence", "probabilities", "question_id"))
        key = (observation["target"], observation["check"])
        if key in observed:
            raise ValueError("core proof duplicate")
        observed.add(key)
        probabilities = observation["probabilities"]
        closed(probabilities, ("SUPPORTED", "INSUFFICIENT", "CONTRADICTED"))
        if any(type(value) not in (int, float) or not 0 <= value <= 1 for value in (*probabilities.values(), observation["confidence"])):
            raise ValueError("core proof probability invalid")
        if (observation["choice"] == "SUPPORTED" and probabilities["SUPPORTED"] >= thresholds["support_min"]
                and probabilities["CONTRADICTED"] <= thresholds["contradiction_max"]):
            continue
        field = ({"field:event_time": "eventTime", "field:period": "period"}.get(key[0])
                 if key[1] in ("event_time", "period") else
                 "geography" if key[0] == "field:countries" and re.fullmatch(r"country:[0-9]+", key[1]) else None)
        if field is None or policy[field]["mode"] != "unknown":
            return False
        field_failure = True
    return (field_failure and required <= observed and all(
        row["decision"] == ("HOLD" if row["target"] == "issue" else "ALLOW") for row in validation["verdicts"]))


def prepare(source: Path, destination: Path, bindings: list[dict], company_bindings: list[dict], operator: str,
            metadata_policy: Path | None = None):
    if not bindings:
        raise ValueError("current article bindings required for content export")
    raw = {name: (source / original).read_bytes() for name, original in FILES.items()}
    selection = json.loads(raw["bundle.json"])
    geography = json.loads(raw["geography.json"])
    pins = json.loads(raw["source-pins.json"])
    provenance = json.loads(raw["source-provenance.json"])
    if selection["schema"] != "zoop-legacy-company-issues/1" or geography["schema"] != "zoop-legacy-geography-review/1":
        raise ValueError("unsupported retained package")
    metadata = metadata_policy is not None
    policies = {}
    if metadata:
        raw["metadata-policy.json"] = metadata_policy.read_bytes()
        policies = metadata_policies(json.loads(raw["metadata-policy.json"]), selection)
    audits = {audit["candidate_id"]: audit for audit in selection["candidate_audit"]}
    geo = {row["issue_id"]: row for row in geography["records"]}
    bound = {(b["originalArticleId"], b["originalArticleVersion"]) for b in bindings}
    selected, ledger = [], []
    for issue in selection["issues"]:
        reason = "selected"
        if not metadata and geo[issue["issue_id"]]["decision"] != "source_supported":
            reason = "geography_unresolved"
        elif not all((a["article_id"], a["article_version"]) in bound for a in issue["article_refs"]):
            reason = "current_grant_binding_missing"
        elif metadata:
            policy = policies.get(issue["issue_id"])
            if policy is None:
                raise ValueError("metadata policy missing for bound issue")
            if policy["geography"]["mode"] == "preserve" and geo[issue["issue_id"]]["decision"] != "source_supported":
                raise ValueError("preserved geography requires source support")
            for candidate in issue["candidate_ids"]:
                audit = audits[candidate]
                if audit["status"] == "ALLOW":
                    continue
                resolution = audit["publication_resolution"]
                if (audit["status"] == "HOLD" and resolution["type"] == "existing_enabled_publication_rule"
                        and resolution["rule_id"] == "R1@2"):
                    continue
                if not metadata_only_hold(issue, audit, policy):
                    reason = "core_review_required"
        if reason == "selected":
            selected.append(issue["issue_id"])
        ledger.append({"issueId": issue["issue_id"], "reason": reason})
    if not selected:
        raise ValueError("no policy-supported, binding-eligible issues")
    selected_ids = set(selected)
    if metadata and set(policies) != selected_ids:
        raise ValueError("metadata policy must cover exactly selected issues")
    retained_issues = [{key: value for key, value in issue.items() if key != "zoop_approval"}
                       for issue in selection["issues"] if issue["issue_id"] in selected_ids]
    needed = {(a["article_id"], a["article_version"]) for issue in retained_issues for a in issue["article_refs"]}
    for article in selection["articles"]:
        if (article["record"]["article_id"], article["article_version"]) not in needed:
            continue
        closed(article, ("record", "article_version"))
        record = article["record"]
        closed(record, ("article_id", "body", "title", "url", "publisher", "published_at", "collected_at",
                        "synthetic", "withdrawn", "input_kind", "allow_model_send"), ("language", "origin_id"))
        if ("origin_id" in record and record["origin_id"] is not None
                and not HEX.fullmatch(record["origin_id"])):
            raise ValueError("unsupported selected metadata")
        if not HEX.fullmatch(article["article_version"]):
            raise ValueError("selected article version invalid")
    for issue in retained_issues:
        closed(issue, ("article_refs", "candidate_ids", "field_decisions", "issue_id", "mentions", "relations", "source_support"))
        if not re.fullmatch(r"issue-[A-Za-z0-9-]{1,100}", issue["issue_id"]):
            raise ValueError("selected issue id invalid")
        for ref in issue["article_refs"]:
            closed(ref, ("article_id", "article_version"))
            if not all(HEX.fullmatch(ref[key]) for key in ("article_id", "article_version")):
                raise ValueError("selected article reference invalid")
        support = issue["source_support"]
        closed(support, ("article_count", "duplicate_groups", "independent_source_count",
                         "known_lineage_count", "unknown_lineage_articles"))
        if (not set(support["unknown_lineage_articles"]) <= {ref["article_id"] for ref in issue["article_refs"]}
                or any(not set(group) <= {ref["article_id"] for ref in issue["article_refs"]}
                       for group in support["duplicate_groups"])):
            raise ValueError("selected export reference closure incomplete")
        if (any(type(support[key]) is not int or support[key] < 0 for key in ("article_count", "known_lineage_count"))
                or support["independent_source_count"] is not None and
                (type(support["independent_source_count"]) is not int or support["independent_source_count"] < 0)):
            raise ValueError("unsupported selected metadata")
        issue_articles = {(a["article_id"], a["article_version"]) for a in issue["article_refs"]}
        issue_article_ids = {ref["article_id"] for ref in issue["article_refs"]}
        for mention in issue["mentions"]:
            closed(mention, ("article_id", "article_version", "mention_id", "title", "action", "assertion_status",
                             "background", "participants", "evidence"),
                   ("target", "period", "event_time", "countries", "event_type", "keywords"))
            if (mention["article_id"], mention["article_version"]) not in issue_articles:
                raise ValueError("selected export reference closure incomplete")
            for participant in mention["participants"]:
                closed(participant, ("company_id", "name", "role"), ("role_unconfirmed",))
            for span in mention["evidence"]:
                closed(span, ("article_id", "article_version", "start", "end", "quote"))
                if (span["article_id"], span["article_version"]) not in issue_articles:
                    raise ValueError("selected export reference closure incomplete")
        for relation in issue["relations"]:
            closed(relation, ("relation_id", "relation_type", "source", "target", "role", "assertion_status",
                              "basis", "candidate_ids", "evidence"), ("role_unconfirmed",))
            if "role_unconfirmed" in relation and type(relation["role_unconfirmed"]) is not bool:
                raise ValueError("unsupported selected metadata")
            if relation["relation_type"] in ("REPORTS", "PROVIDES_BACKGROUND"):
                if relation["source"] not in issue_article_ids or relation["target"] != issue["issue_id"]:
                    raise ValueError("selected export reference closure incomplete")
            elif relation["relation_type"] == "FOLLOWS":
                if relation["source"] != issue["issue_id"] or not re.fullmatch(r"issue-[A-Za-z0-9-]{1,100}", relation["target"]):
                    raise ValueError("selected export reference closure incomplete")
            elif relation["relation_type"] != "INVOLVES":
                raise ValueError("selected export reference closure incomplete")
            if relation["basis"] or not set(relation["candidate_ids"]) <= set(issue["candidate_ids"]):
                raise ValueError("selected export reference closure incomplete")
            for span in relation["evidence"]:
                closed(span, ("article_id", "article_version", "start", "end", "quote"))
                if (span["article_id"], span["article_version"]) not in issue_articles:
                    raise ValueError("selected export reference closure incomplete")
        for field in issue["field_decisions"]:
            closed(field, ("candidate_id", "mention_id", "outcomes"))
            for outcome in field["outcomes"]:
                closed(outcome, ("decision", "field", "reason"))
                if not metadata:
                    review_reason(outcome["reason"])
    candidate_ids = {candidate for issue in retained_issues for candidate in issue["candidate_ids"]}
    relation_ids = {relation["relation_id"] for issue in retained_issues for relation in issue["relations"]}
    company_ids = {relation["target"] for issue in retained_issues for relation in issue["relations"]
                   if relation["relation_type"] == "INVOLVES"}
    for company in selection["companies"]:
        if company["company_id"] in company_ids and not re.fullmatch(r"[A-Za-z0-9:_-]{1,100}", company["company_id"]):
            raise ValueError("selected company id invalid")
    for review in selection["effective_review_decisions"]:
        if review["target_id"] in selected_ids | candidate_ids | relation_ids and (
                type(review["id"]) is not int or review["id"] < 0
                or review["target_type"] not in ("issue", "candidate", "relation")
                or review["decision"] not in ("allow", "reject")):
            raise ValueError("unsupported selected review metadata")
    for exclusion in selection["review_exclusions"]:
        if exclusion["issue_id"] in selected_ids and (
                not re.fullmatch(r"relation-[A-Za-z0-9-]{1,100}", exclusion["relation_id"])
                or not set(exclusion["candidate_ids"]) <= candidate_ids
                or exclusion["authority_decision"] not in ("ALLOW", "HOLD")
                or exclusion["publication_decision"] != "EXCLUDED_AFTER_MANUAL_REVIEW"):
            raise ValueError("unsupported selected review metadata")
    exported_articles = [article for article in selection["articles"] if
                         (article["record"]["article_id"], article["article_version"]) in needed]
    retained = {"schema": selection["schema"], "format": selection["format"],
                "origin": origin_projection(selection["origin"]),
                "selection_basis": "selected-bound-article-and-metadata-policy" if metadata else "selected-bound-article-and-geography",
                "issues": retained_issues, "articles": exported_articles,
                "companies": [{"company_id": company["company_id"], "name": company["name"]}
                              for company in selection["companies"] if company["company_id"] in company_ids],
                "candidate_audit": [audit_projection(audit, metadata) for audit in selection["candidate_audit"] if audit["candidate_id"] in candidate_ids],
                "effective_review_decisions": [{key: review[key] for key in ("id", "target_id", "target_type", "decision")}
                                               for review in selection["effective_review_decisions"] if
                                               review["target_id"] in selected_ids | candidate_ids | relation_ids],
                "enabled_rules": [{"id": rule["id"]} for rule in selection["enabled_rules"]],
                "review_exclusions": [{key: exclusion[key] for key in ("issue_id", "relation_id", "candidate_ids",
                                                                        "authority_decision", "publication_decision")}
                                      for exclusion in selection["review_exclusions"] if exclusion["issue_id"] in selected_ids]}
    geo_ids = {evidence_id for row in geography["records"] if row["issue_id"] in selected_ids
               for evidence_id in row["source_evidence_ids"]}
    exported_geo = {"schema": geography["schema"], "policy_version": geography.get("policy_version"),
                    "review_date": geography.get("review_date"),
                    "records": [{**{key: row[key] for key in ("issue_id", "decision", "classification",
                                                             "review_policy_version", "source_evidence_ids",
                                                             "country_codes", "regions")},
                                 **({"decision_id": row["decision_id"]} if "decision_id" in row else {}),
                                 "reviewer": "local-source-review", "reason": "selected_source_evidence"}
                                for row in geography["records"] if row["issue_id"] in selected_ids],
                    "evidence": [span for span in geography["evidence"] if span["evidence_id"] in geo_ids]}
    if (exported_geo["policy_version"] is not None
            and exported_geo["policy_version"] != "legacy-source-geography-review/1"
            or exported_geo["review_date"] is not None
            and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", exported_geo["review_date"])):
        raise ValueError("unsupported geography metadata")
    for row in exported_geo["records"]:
        if "decision_id" in row and not re.fullmatch(r"legacy-geography-[0-9a-f]{64}", row["decision_id"]):
            raise ValueError("unsupported geography metadata")
    for span in exported_geo["evidence"]:
        closed(span, ("article_id", "article_version", "start", "end", "quote", "evidence_id"))
    original_provenance = {(article["article_id"], article["article_version"]): article
                           for article in provenance.get("articles", [])}
    if original_provenance and not needed <= set(original_provenance):
        raise ValueError("selected article provenance incomplete")
    provenance = {"schema": "zoop-legacy-export-provenance/1",
                  "articles": [provenance_projection(article, original_provenance.get(
                      (article["record"]["article_id"], article["article_version"]), {})) for article in exported_articles]}
    if ({(article["record"]["article_id"], article["article_version"]) for article in retained["articles"]} != needed
            or {audit["candidate_id"] for audit in retained["candidate_audit"]} != candidate_ids
            or {company["company_id"] for company in retained["companies"]} != company_ids
            or {row["issue_id"] for row in exported_geo["records"]} != selected_ids
            or {span["evidence_id"] for span in exported_geo["evidence"]} != geo_ids):
        raise ValueError("selected export reference closure incomplete")
    if not isinstance(company_bindings, list):
        raise ValueError("company bindings must be an array")
    originals = {company["company_id"]: company["name"] for company in retained["companies"]}
    seen = set()
    for binding in company_bindings:
        if (not isinstance(binding, dict)
                or set(binding) != {"companyId", "originalName", "canonicalName"}
                or not all(isinstance(value, str) and value.strip() for value in binding.values())
                or binding["companyId"] in seen
                or originals.get(binding["companyId"]) != binding["originalName"]):
            raise ValueError("company binding invalid")
        seen.add(binding["companyId"])
    if seen != company_ids or len(originals) != len(retained["companies"]):
        raise ValueError("company binding closure incomplete")
    exported_pins = ({"schema": "zoop-legacy-export-source-pins/1",
                      "originalDigest": sha(raw["source-pins.json"]),
                      "upstreamInputClaims": [{"bytes": file["bytes"], "sha256": file["sha256"]}
                                              for file in pins["files"]]} if "files" in pins else pins)
    for claim in exported_pins.get("upstreamInputClaims", []):
        if type(claim["bytes"]) is not int or claim["bytes"] < 0 or not HEX.fullmatch(claim["sha256"]):
            raise ValueError("source pin claim invalid")
    transfer = {"bundle.json": canonical(retained), "geography.json": canonical(exported_geo),
                "source-pins.json": canonical(exported_pins), "source-provenance.json": canonical(provenance)}
    if metadata:
        transfer["metadata-policy.json"] = raw["metadata-policy.json"]
    used_bindings = [b for b in bindings if (b["originalArticleId"], b["originalArticleVersion"]) in needed]
    manifest = {"schemaVersion": "zoop-legacy-real-manifest-3" if metadata else "zoop-legacy-real-manifest-2",
                "sourceInputDigests": {name: sha(data) for name, data in raw.items()},
                "bundleDigest": sha(transfer["bundle.json"]), "geographyDigest": sha(transfer["geography.json"]),
                "sourcePinsDigest": sha(transfer["source-pins.json"]), "provenanceDigest": sha(transfer["source-provenance.json"]),
                "catalogueDigest": sha(canonical(retained["companies"])),
                "legacyOrigin": retained["origin"], "ruleDefinitionsDigest": sha(canonical(retained["enabled_rules"])),
                "selectedIssueIds": selected, "grantBindings": used_bindings,
                "companyBindings": sorted(company_bindings, key=lambda row: row["companyId"]), "selectionLedger": ledger}
    if metadata:
        manifest["metadataPolicyDigest"] = sha(transfer["metadata-policy.json"])
    digest = sha(canonical(manifest))
    request = {"schemaVersion": "zoop-legacy-real-import-1", "migrationId": "legacy-real:" + digest,
               "expectedManifestDigest": digest, "expectedBundleDigest": manifest["bundleDigest"], "operator": operator}
    destination.mkdir(mode=0o700)
    for name, content in {**transfer, "manifest.json": canonical(manifest)}.items():
        target = destination / name
        with target.open("xb") as out:
            out.write(content)
        target.chmod(0o600)
    return request, {"selectedIssues": len(selected), "retainedIssues": len(ledger), "boundArticles": len(used_bindings),
                     "publicationGate": "current-registry-required", "selectionLedger": ledger}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--company-bindings", type=Path, required=True)
    parser.add_argument("--metadata-policy", type=Path)
    parser.add_argument("--operator", required=True)
    args = parser.parse_args()
    if args.request.exists() or args.output.exists():
        parser.error("output and request must be new paths")
    bindings = json.loads(args.bindings.read_bytes())
    company_bindings = json.loads(args.company_bindings.read_bytes())
    request, summary = prepare(args.source.resolve(), args.output.resolve(), bindings, company_bindings, args.operator, args.metadata_policy)
    with args.request.open("xb") as output:
        output.write(canonical(request))
    args.request.chmod(0o600)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
