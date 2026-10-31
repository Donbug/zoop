#!/usr/bin/env python3
"""Packaged legacy importer and real HTTP checks on one owned cached PostgreSQL container.

The authored fixture proves behavior. --actual-package separately exercises pinned
retained content with its actual registry and a supplied catalogue in an isolated DB.
Requires the built jar and macOS sandbox-exec; installs nothing.
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import document_import_smoke as database
import legacy_real_package as package
import local_graph_dev as local

REPO = Path(__file__).resolve().parents[2]
ORIGIN = "http://127.0.0.1:5173"
SANDBOX = '(version 1)(allow default)(deny network*)(allow network-inbound (local ip "localhost:*"))(allow network-outbound (remote ip "localhost:*"))'


def write(path, value):
    path.write_bytes(package.canonical(value))
    path.chmod(0o600)


def fixture(root):
    selection = json.loads((REPO / "api/src/test/resources/legacy-real/selection.json").read_bytes())
    article = selection["articles"][0]["record"]
    version = package.sha(package.canonical({k: v for k, v in article.items() if k != "collected_at"}))
    selection = json.loads(json.dumps(selection).replace("VERSION", version))
    selection["candidate_audit"][0]["original_mention"] = copy.deepcopy(selection["issues"][0]["mentions"][0])
    selection["origin"]["snapshot"]["reason"] = "other article: UNBOUND_PRIVATE_SMOKE_METADATA_58921"
    selection["candidate_audit"][0]["reasons"] = ["other article: UNBOUND_PRIVATE_SMOKE_METADATA_58921"]
    span = {**selection["issues"][0]["mentions"][0]["evidence"][0], "evidence_id": "geo-synthetic"}
    geo = {"schema": "zoop-legacy-geography-review/1", "records": [{"issue_id": "issue-synthetic-lab", "decision": "source_supported",
           "classification": "domestic", "review_policy_version": "legacy-source-geography-review/1", "reviewer": "synthetic fixture",
           "reason": "Exact quote names Seoul, South Korea.", "country_codes": ["KR"], "regions": [], "source_evidence_ids": ["geo-synthetic"]}], "evidence": [span]}
    unbound = copy.deepcopy(selection["articles"][0])
    unbound["record"]["article_id"] = "b" * 64
    unbound["record"]["body"] = "UNBOUND_PRIVATE_SMOKE_BODY_58921"
    unbound["record"]["title"] = "UNBOUND_PRIVATE_SMOKE_TITLE_58921"
    unbound["article_version"] = package.sha(package.canonical(
        {k: v for k, v in unbound["record"].items() if k != "collected_at"}))
    selection["articles"].append(unbound)
    root.mkdir(mode=0o700)
    source_provenance = {"schema": "zoop-legacy-source-provenance/1", "articles": [{
        "article_id": article["article_id"], "article_version": version,
        "body_sha256": package.sha(article["body"].encode()),
        "retained_acquisition_matches": [{"metadata": {"content_hash": package.sha(article["body"].encode()),
                                                       "notes": "other article: UNBOUND_PRIVATE_SMOKE_METADATA_58921"}}]}]}
    for name, value in (("LEGACY_SELECTION.json", selection), ("GEOGRAPHY_REVIEW.json", geo),
                        ("SOURCE_PINS.json", {}), ("SOURCE_PROVENANCE.json", source_provenance)):
        write(root / name, value)
    binding = {"originalArticleId": article["article_id"], "originalArticleVersion": version, "sourceId": "synthetic-source",
               "grantId": "synthetic-grant", "revision": "1", "kind": "news"}
    return selection, geo, [binding]

def company_bindings(selection):
    return [{"companyId": row["company_id"], "originalName": row["name"], "canonicalName": row["name"]}
            for row in selection["companies"]]



class Smoke:
    def __init__(self, args, scratch, env, db, report):
        self.args, self.scratch, self.env, self.db, self.report = args, scratch, env, db, report
        self.counter = 0
        self.artifacts = scratch / "artifacts"
        self.artifacts.mkdir(mode=0o700)
        self.sources = scratch / "sources.json"
        self.registry = {"schemaVersion": "zoop-ingestion-s2-1", "revision": "synthetic-1", "sources": [{"sourceId": "synthetic-source",
            "adapter": "authored-files", "inputRoot": str(scratch), "allowedHosts": ["example.invalid"],
            "scopes": [{"scopeId": "synthetic", "selection": "owned synthetic fixture", "initialCursor": None, "articleXPath": None,
                        "timestampLimitations": ["authored fixture"]}],
            "grant": {"grantId": "synthetic-grant", "revision": "1", "sourceId": "synthetic-source", "enabled": True, "rights": "known",
                      "allowedOperations": ["read", "store", "quote-display"], "recipients": [], "purposes": [],
                      "evidence": ["operator-owned authored synthetic fixture"], "expiresAt": None}}]}
        write(self.sources, self.registry)

    def check(self, condition, label, **facts):
        self.report["steps"].append({"step": label, "status": "passed" if condition else "failed", **facts})
        if not condition:
            raise AssertionError(label)

    def argv(self, *args):
        return ["/usr/bin/sandbox-exec", "-p", SANDBOX, self.args.java, "-XX:TieredStopAtLevel=1", "-jar", str(self.args.jar), *args]

    def cli(self, label, request=None, root=None, *, exclusion=False):
        self.counter += 1
        out = self.scratch / f"result-{self.counter}.json"
        flags = ["--spring.main.web-application-type=none"]
        if request is not None:
            request_path = self.scratch / f"request-{self.counter}.json"
            write(request_path, request)
            if exclusion:
                flags += ["--zoop.disclosure-exclusion.enabled=true", f"--zoop.disclosure-exclusion.request={request_path}",
                          f"--zoop.disclosure-exclusion.result={out}", f"--zoop.disclosure-exclusion.artifact-root={self.artifacts}"]
            else:
                flags += ["--zoop.legacy-real-import.enabled=true", f"--zoop.legacy-real-import.request={request_path}",
                          f"--zoop.legacy-real-import.result={out}", f"--zoop.legacy-real-import.package-root={root}",
                          f"--zoop.legacy-real-import.sources={self.sources}", f"--zoop.legacy-real-import.artifact-root={self.artifacts}"]
        result = subprocess.run(self.argv(*flags), cwd=self.scratch, env=self.env, capture_output=True, timeout=240)
        log = result.stdout + result.stderr
        (self.scratch / f"cli-{self.counter}.log").write_bytes(log.replace(self.env["DB_PASSWORD"].encode(), b"[redacted]"))
        answer = json.loads(out.read_bytes()) if out.is_file() and out.stat().st_size else None
        self.report["commands"].append({"label": label, "exitCode": result.returncode, "result": answer})
        return result.returncode, answer

    def stored(self):
        return self.db.rows("SELECT id, kind, active, snapshot_artifact_id FROM graph_versions ORDER BY id")

    def run_actual(self):
        code, _ = self.cli("actual-migrate")
        self.check(code == 0, "actual-empty-db-migration")
        self.sources = self.args.actual_sources.resolve()
        source_hash = package.sha(self.sources.read_bytes())
        current = json.loads(self.args.actual_catalogue.read_bytes())["items"]
        additions = json.loads(self.args.actual_additions.read_bytes())["companies"]
        current_rows = [{key: row[key] for key in ("id", "name", "aliases")} for row in current]
        missing_rows = [{"id": row["company_id"], "name": row["name"], "aliases": row["aliases"]} for row in additions]
        rows = current_rows + missing_rows
        self.check(len(current) == 24 and len(additions) == 3 and len({r["id"] for r in rows}) == 27,
                   "actual-current24-plus-only3-additions")
        catalogue_sql = "SELECT id,name,aliases FROM companies ORDER BY id"
        self.check(self.db.rows(catalogue_sql) == sorted(current_rows, key=lambda row: row["id"]),
                   "actual-migration-master-matches-observed24")
        encoded = package.canonical(missing_rows).decode().replace("'", "''")
        self.db.run("INSERT INTO companies(id,name,aliases,name_key,search_text) "
                    "SELECT id,name,ARRAY(SELECT jsonb_array_elements_text(aliases)),'','' "
                    f"FROM jsonb_to_recordset('{encoded}'::jsonb) AS c(id text,name text,aliases jsonb)")
        catalogue = self.db.rows(catalogue_sql)
        self.check(catalogue == sorted(rows, key=lambda row: row["id"]), "actual-master27-exact")
        root = self.args.actual_package.resolve()
        request = json.loads(self.args.actual_request.read_bytes())
        manifest = json.loads((root / "manifest.json").read_bytes())
        retained = json.loads((root / "bundle.json").read_bytes())
        self.report["actualInputs"] = {
            "registry": {"path": str(self.sources), "sha256": source_hash},
            "catalogue": {"path": str(self.args.actual_catalogue), "sha256": package.sha(self.args.actual_catalogue.read_bytes())},
            "additions": {"path": str(self.args.actual_additions), "sha256": package.sha(self.args.actual_additions.read_bytes())},
            "request": request, "companyBindings": manifest["companyBindings"]}
        code, result = self.cli("actual-stage", request, root)
        self.check(code == 0 and result and result.get("outcome") == "staged", "actual-staged-inactive", result=result)
        vid = result["graphVersionId"]
        self.check(result["validatedIssues"] == len(retained["issues"]) == 17
                   and self.db.scalar("SELECT count(*) FROM graph_activations") == 0, "actual17-inactive")
        stored_bytes = {p.relative_to(self.artifacts).as_posix(): p.read_bytes() for p in self.artifacts.rglob("*")
                        if p.name != ".document-import.lock" and p.is_file()}
        before = self.db.snapshot(), self.stored(), self.db.rows("SELECT * FROM graph_version_sources ORDER BY graph_version_id,ordinal")
        code, repeated = self.cli("actual-repeat", request, root)
        self.check(code == 0 and repeated["outcome"] == "unchanged" and result["artifacts"] == repeated["artifacts"]
                   and before == (self.db.snapshot(), self.stored(), self.db.rows("SELECT * FROM graph_version_sources ORDER BY graph_version_id,ordinal"))
                   and stored_bytes == {p.relative_to(self.artifacts).as_posix(): p.read_bytes() for p in self.artifacts.rglob("*")
                                        if p.name != ".document-import.lock" and p.is_file()}, "actual-repeat-byte-identity")
        receipt_row = next(row for row in result["artifacts"] if row["kind"] == "verification_receipt")
        snapshot_row = next(row for row in result["artifacts"] if row["kind"] == "graph_snapshot")
        receipt = json.loads((self.artifacts / receipt_row["storageUri"].split(":", 1)[1]).read_bytes())
        snapshot = json.loads((self.artifacts / snapshot_row["storageUri"].split(":", 1)[1]).read_bytes())
        names = {row["companyId"]: row["canonicalName"] for row in manifest["companyBindings"]}
        self.check(receipt["legacyProvenance"]["companies"] == retained["companies"]
                   and receipt["manifest"]["companyBindings"] == manifest["companyBindings"]
                   and {row["companyId"]: row["label"] for row in snapshot["companies"]} == names
                   and receipt["bundle"]["companies"] == snapshot["companies"], "actual-canonical-serving-original-provenance")
        issue_ids = {row["issueId"] for row in snapshot["issues"]}
        connected = {row["source"] for row in snapshot["relations"] if row["relationType"] == "INVOLVES" and row["target"] in names}
        self.check(issue_ids == connected and len(issue_ids) == 17, "actual-all17-company-connected")
        self.db.run("UPDATE companies SET name='Changed local canonical' WHERE id='KRX:018260'")
        code, rejected = self.cli("actual-renamed-repeat", request, root)
        self.check(code != 0 and rejected["code"] == "company_mismatch" and before[0] == self.db.snapshot()
                   and self.db.scalar("SELECT name FROM companies WHERE id='KRX:018260'") == "Changed local canonical"
                   and stored_bytes == {p.relative_to(self.artifacts).as_posix(): p.read_bytes() for p in self.artifacts.rglob("*")
                                        if p.name != ".document-import.lock" and p.is_file()}, "actual-renamed-repeat-preserves-bytes")
        self.db.run("UPDATE companies SET name='삼성SDS' WHERE id='KRX:018260'")
        self.check(self.db.rows(catalogue_sql) == catalogue, "actual-catalogue-restored-exactly")
        with Web(self) as web:
            token = secrets.token_urlsafe(32)
            token_hash = package.sha(token.encode())
            self.db.run("INSERT INTO admins(id,email,email_key,display_name,password_hash,role,status,created_at) VALUES "
                        "('local-proof-admin','proof@synthetic.invalid','proof@synthetic.invalid','Local proof','{argon2id-v1}synthetic','admin','active',now());"
                        "INSERT INTO admin_sessions(id,admin_id,token_hash,csrf_key_id,csrf_version,created_at,last_seen_at,idle_expires_at,expires_at) VALUES "
                        f"('local-proof-session','local-proof-admin','{token_hash}','synthetic-legacy',1,now(),now(),now()+interval '1 hour',now()+interval '8 hours')")
            auth = {"Cookie": "zoop_admin_session=" + token}
            session = web.expect("actual-admin-session", "/api/v1/admin/auth/session", 200, headers=auth)
            headers = {**auth, "Origin": ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrfToken"],
                       "Idempotency-Key": "actual-local-activation"}
            web.expect("actual-local-activate", f"/api/v1/admin/graph/versions/{vid}/activate", 200,
                       {"reason": "Isolated actual retained content proof", "expectedActiveVersionId": None}, headers)
            public = web.expect("actual-public-graph", f"/api/v1/graph?mode=all&graphVersion={vid}", 200)
            self.check(public["metadata"]["graphVersion"] == vid, "actual-public-version")
            context = urllib.parse.urlencode({"graphVersion": vid, "asOf": public["metadata"]["asOf"]})
            for issue in snapshot["issues"]:
                event = web.expect("actual-event", f"/api/v1/events/{issue['issueId']}?" + context, 200)
                self.check(bool(event["companies"]) and all(names[c["id"]] == c["name"] for c in event["companies"]),
                           "actual-event-canonical-company", issueId=issue["issueId"])
            for span in receipt["bundle"]["evidence"]:
                evidence = web.expect("actual-evidence", f"/api/v1/evidence/{span['id']}?" + context, 200)
                self.check(all(evidence[key] == span[key] for key in ("quote", "start", "end", "articleVersion")),
                           "actual-evidence-exact", evidenceId=span["id"])
            read_articles = set()
            expected_articles = {row["articleId"]: row for row in receipt["bundle"]["articles"]}
            for company_id in names:
                documents = web.expect("actual-company-documents",
                    "/api/v1/companies/" + urllib.parse.quote(company_id, safe="") + "/documents?limit=100&" + context, 200)
                for article in documents["items"]:
                    expected = expected_articles[article["id"]]
                    self.check(article["url"] == expected["url"] and article["documentVersion"] == expected["articleVersion"]
                               and article["title"] == expected["title"], "actual-article-current-rights", articleId=article["id"])
                    read_articles.add(article["id"])
            self.check(read_articles == set(expected_articles) and len(read_articles) == 10, "actual-all10-articles-readable")
        self.check(package.sha(self.sources.read_bytes()) == source_hash and self.db.rows(catalogue_sql) == catalogue,
                   "actual-authority-and-master-preserved")
        self.report["realData"] = {"selectedIssues": 17, "connectedIssues": len(connected), "selectedArticles": len(read_articles),
            "selectedCompanies": len(names), "localActivation": True, "remotePublication": False, "graphVersionId": vid,
            "migrationId": request["migrationId"], "manifestDigest": request["expectedManifestDigest"],
            "bundleDigest": request["expectedBundleDigest"], "contentDigest": result["contentDigest"], "artifacts": result["artifacts"],
            "artifactFiles": {name: {"sha256": package.sha(data), "bytes": len(data)} for name, data in stored_bytes.items()}}

    def run(self):
        code, _ = self.cli("migrate")
        self.check(code == 0, "empty-owned-db-migration")
        source = self.scratch / "synthetic-source"
        selection, geo, bindings = fixture(source)
        root = self.scratch / "synthetic-package"
        request, _ = package.prepare(source, root, bindings, company_bindings(selection), "synthetic-operator")
        self.db.run("INSERT INTO companies(id,name,name_key,search_text) VALUES('SYNTHETIC:ACME','Synthetic Acme','','')")
        code, result = self.cli("stage", request, root)
        self.check(code == 0 and result and result.get("outcome") == "staged", "staged-inactive", result=result)
        vid = result["graphVersionId"]
        self.check(self.db.scalar("SELECT count(*) FROM graph_activations") == 0 and not any(r["active"] for r in self.stored()), "staging-does-not-activate")
        self.check(self.db.scalar("SELECT count(*) FROM articles WHERE current_version IS NOT NULL") == 0, "article-pointer-preserved")
        before = self.db.snapshot(), self.stored(), self.db.rows("SELECT * FROM graph_version_sources ORDER BY graph_version_id,ordinal")
        code, repeated = self.cli("repeat", request, root)
        self.check(code == 0 and repeated["outcome"] == "unchanged" and before == (self.db.snapshot(), self.stored(), self.db.rows("SELECT * FROM graph_version_sources ORDER BY graph_version_id,ordinal")), "exact-reimport-unchanged")
        changed = {**request, "expectedBundleDigest": "0" * 64}
        code, result = self.cli("changed-pin", changed, root)
        self.check(code != 0 and result["code"] == "package_pin_conflict", "changed-pins-refused")
        for kind in ("quote", "reference", "geography", "company"):
            altered = self.scratch / ("fault-source-" + kind)
            data, geography, fault_bindings = fixture(altered)
            if kind == "quote":
                data["issues"][0]["mentions"][0]["evidence"][0]["quote"] = "forged"
                data["candidate_audit"][0]["original_mention"] = copy.deepcopy(data["issues"][0]["mentions"][0])
            elif kind == "reference":
                data["issues"][0]["relations"][0]["target"] = "SYNTHETIC:MISSING"
            elif kind == "company":
                data["companies"][0]["name"] = "Forged catalogue name"
            else:
                geography["records"][0].update(country_codes=["US"], classification="international")
            write(altered / "LEGACY_SELECTION.json", data); write(altered / "GEOGRAPHY_REVIEW.json", geography)
            fault_root = self.scratch / ("fault-package-" + kind)
            try:
                fault_request, _ = package.prepare(altered, fault_root, fault_bindings, company_bindings(data), "synthetic-operator")
            except ValueError as error:
                self.check(kind == "reference" and str(error) == "selected export reference closure incomplete",
                           kind + "-export-refused", reason=str(error))
                continue
            code, result = self.cli(kind + "-fault", fault_request, fault_root)
            self.check(code != 0 and result["status"] == "failed", kind + "-forgery-refused", code=result["code"])
        self.check(before[0] == self.db.snapshot() and before[1] == self.stored(), "faults-write-nothing")
        receipt_row = next(a for a in self.db.artifacts() if a["id"] == "artifact-receipt-" + vid)
        receipt = json.loads((self.artifacts / receipt_row["storage_uri"].split(":", 1)[1]).read_bytes())
        snapshot_row = next(a for a in self.db.artifacts() if a["id"] == "artifact-" + vid)
        snapshot = json.loads((self.artifacts / snapshot_row["storage_uri"].split(":", 1)[1]).read_bytes())
        self.check(receipt["schemaVersion"] == "zoop-legacy-real-import-receipt-2" and receipt["bundle"]["provenanceKind"] == "legacy-real", "truthful-receipt-kind")
        self.check("UNBOUND_PRIVATE_SMOKE_" not in json.dumps(receipt) and
                   all("UNBOUND_PRIVATE_SMOKE_" not in p.read_text() for p in root.iterdir()),
                   "unbound-body-absent-from-package-and-receipt")
        with Web(self) as web:
            token = secrets.token_urlsafe(32)
            token_hash = package.sha(token.encode())
            self.db.run("INSERT INTO admins(id,email,email_key,display_name,password_hash,role,status,created_at) VALUES "
                        "('synthetic-legacy-admin','legacy@synthetic.invalid','legacy@synthetic.invalid','Synthetic admin','{argon2id-v1}synthetic','admin','active',now());"
                        "INSERT INTO admin_sessions(id,admin_id,token_hash,csrf_key_id,csrf_version,created_at,last_seen_at,idle_expires_at,expires_at) VALUES "
                        f"('synthetic-legacy-session','synthetic-legacy-admin','{token_hash}','synthetic-legacy',1,now(),now(),now()+interval '1 hour',now()+interval '8 hours')")
            auth = {"Cookie": "zoop_admin_session=" + token}
            session = web.expect("session", "/api/v1/admin/auth/session", 200, headers=auth)
            headers = {**auth, "Origin": ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrfToken"]}
            path = f"/api/v1/admin/graph/versions/{vid}/activate"
            payload = {"reason": "Synthetic legacy importer behavior check", "expectedActiveVersionId": None}
            grant = self.registry["sources"][0]["grant"]
            grant["enabled"] = False; write(self.sources, self.registry)
            code, result = self.cli("grant-revoked-reimport", request, root)
            self.check(code != 0 and result["code"] == "current_grant_source_rights_unknown_or_denied", "reimport-current-grants-deny")
            web.expect("activation-current-grants-deny", path, 409, payload, {**headers, "Idempotency-Key": "denied"})
            web.expect("inactive-public-denied", f"/api/v1/graph?graphVersion={vid}", 409)
            grant["enabled"] = True; write(self.sources, self.registry)
            web.expect("activate-cas", path, 200, payload, {**headers, "Idempotency-Key": "activate"})
            web.expect("activate-replay", path, 200, payload, {**headers, "Idempotency-Key": "activate"})
            web.expect("activate-key-conflict", path, 409, {**payload, "reason": "changed"}, {**headers, "Idempotency-Key": "activate"})
            web.expect("activate-stale-cas", path, 409, payload, {**headers, "Idempotency-Key": "stale"})
            public = web.expect("public-graph", f"/api/v1/graph?mode=all&graphVersion={vid}", 200)
            self.check(public["metadata"]["graphVersion"] == vid, "graph-version-coherence")
            context = urllib.parse.urlencode({"graphVersion": vid, "asOf": public["metadata"]["asOf"]})
            issue = snapshot["issues"][0]["issueId"]
            event_path = "/api/v1/events/" + urllib.parse.quote(issue, safe="") + "?" + context
            event = web.expect("public-event", event_path, 200)
            self.check(event["metadata"]["graphVersion"] == vid and event["companies"][0]["id"] == "SYNTHETIC:ACME", "event-company-coherence")
            self.check(event["sourceSupport"]["independentSourceCount"] is None, "unknown-source-lineage-preserved")
            for span in snapshot["evidence"]:
                evidence_path = f"/api/v1/evidence/{span['evidenceId']}?" + context
                evidence = web.expect("public-evidence", evidence_path, 200)
                expected = next(e for e in receipt["bundle"]["evidence"] if e["id"] == span["evidenceId"])
                self.check(evidence["quote"] == expected["quote"] and evidence["start"] == 2 and evidence["end"] == 42
                           and evidence["articleVersion"] == span["articleVersion"] and evidence["metadata"]["graphVersion"] == vid, "evidence-span-version-coherence")
            edges = public["edges"]
            for edge in edges:
                web.expect("public-edge", "/api/v1/graph/edges/" + edge["id"] + "?" + context, 200)
            web.expect("company-graph", "/api/v1/companies/SYNTHETIC%3AACME/graph?" + context, 200)
            impact = web.expect("company-issue-impact", f"/api/v1/companies/SYNTHETIC%3AACME/issues/{issue}/impact?" + context, 200)
            self.check(impact["metadata"]["graphVersion"] == vid, "impact-version-coherence")
            rule_source = self.scratch / "rule-source"
            rule_data, _, rule_bindings = fixture(rule_source)
            audit = rule_data["candidate_audit"][0]
            audit["status"] = "HOLD"
            audit["original_mention"]["participants"][0]["role"] = "unconfirmed operator"
            rule_data["issues"][0]["mentions"][0]["participants"][0]["role_unconfirmed"] = True
            audit["validation"]["verdicts"][0].update(decision="HOLD", reason="Support or contradiction probability requires review: participant_role:0")
            audit["publication_resolution"] = {"type": "existing_enabled_publication_rule", "rule_id": "R1@2",
                                               "effect": {"participants": [0], "relations": ["relation-synthetic-lab"], "dropped": []}}
            rule_data["enabled_rules"] = [{"id": "R1@2"}]
            rule_data["issues"][0]["relations"][0]["role_unconfirmed"] = True
            audit["validation"]["verdicts"][1].update(decision="HOLD", reason="Support or contradiction probability requires review: role")
            confirmed = copy.deepcopy(rule_data["issues"][0]["relations"][0])
            confirmed.update(relation_id="relation-confirmed-role", role="retained confirmed role", role_unconfirmed=False)
            rule_data["issues"][0]["relations"].append(confirmed)
            audit["validation"]["verdicts"].append({"target": "relation-confirmed-role", "decision": "ALLOW", "reason": package.ALLOWED_REASON})
            write(rule_source / "LEGACY_SELECTION.json", rule_data)
            rule_root = self.scratch / "rule-package"
            rule_request, _ = package.prepare(rule_source, rule_root, rule_bindings, company_bindings(rule_data), "synthetic-operator")
            code, rule_result = self.cli("rule-stage", rule_request, rule_root)
            self.check(code == 0 and rule_result["outcome"] == "staged", "rule-version-staged")
            rule_vid = rule_result["graphVersionId"]
            web.expect("rule-activate", f"/api/v1/admin/graph/versions/{rule_vid}/activate", 200,
                       {**payload, "expectedActiveVersionId": vid}, {**headers, "Idempotency-Key": "rule-activate"})
            rule_event = web.expect("rule-event", f"/api/v1/events/{issue}?graphVersion={rule_vid}", 200)
            self.check(rule_event["approval"]["source"] == "review-rule" and rule_event["approval"]["ruleId"] == "R1@2"
                       and rule_event["mentions"][0]["participants"][0]["role"] is None
                       and rule_event["mentions"][0]["participants"][0]["roleUnconfirmed"], "rule-approval-and-role-mask")
            flags = {r["id"]: r["roleUnconfirmed"] for r in rule_event["relations"]}
            self.report["reviewObservations"] = {"R3": {"participant": rule_event["mentions"][0]["participants"][0]["roleUnconfirmed"],
                "relations": flags, "company": rule_event["companies"][0]["roleUnconfirmed"],
                "passed": flags["relation-synthetic-lab"] and not flags["relation-confirmed-role"]
                          and rule_event["companies"][0]["roleUnconfirmed"]}}
            web.expect("rollback-through-cas", path, 200, {**payload, "expectedActiveVersionId": rule_vid},
                       {**headers, "Idempotency-Key": "rollback"})
            grant["enabled"] = False; write(self.sources, self.registry)
            web.expect("revoked-evidence", evidence_path, 404)
            web.expect("revoked-event", event_path, 404)
            grant["enabled"] = True; write(self.sources, self.registry)
            article_id = snapshot["articles"][0]["articleId"]
            self.db.run(f"UPDATE articles SET access_status='private' WHERE id='{article_id}'")
            web.expect("withdrawn-evidence", evidence_path, 404)
            self.db.run(f"UPDATE articles SET access_status='available' WHERE id='{article_id}'")
            exclusion = {"schemaVersion": "zoop-disclosure-exclusion-1", "action": "exclude-legacy", "requestId": "synthetic-exclude",
                         "operator": "synthetic-operator", "reason": "Synthetic explicit legacy exclusion", "graphVersionId": vid,
                         "receiptSha256": receipt_row["sha256"], "targets": [{"kind": "issue", "id": issue}]}
            code, denied = self.cli("legacy-exclusion-pin-conflict", {**exclusion, "requestId": "synthetic-wrong-pin",
                                   "receiptSha256": "0" * 64}, exclusion=True)
            self.check(code != 0, "legacy-exclusion-pin-conflict")
            code, result = self.cli("legacy-exclusion", exclusion, exclusion=True)
            self.check(code == 0 and result["outcome"] == "applied", "legacy-exclusion-applied", result=result)
            web.expect("excluded-event", event_path, 404)
            web.expect("excluded-evidence", evidence_path, 404)
            excluded_graph = web.expect("excluded-graph", f"/api/v1/graph?mode=all&graphVersion={vid}", 200)
            self.check(not excluded_graph["edges"], "excluded-connections-removed")
            code, empty = self.cli("empty-exclusion", {**exclusion, "requestId": "synthetic-empty", "targets": []}, exclusion=True)
            self.check(code == 0 and empty["outcome"] == "unchanged", "empty-exclusion-preserves-state")
            code, replay = self.cli("exclusion-replay", exclusion, exclusion=True)
            self.check(code == 0, "exclusion-replay")
            lift = {"schemaVersion": "zoop-disclosure-exclusion-1", "action": "lift", "requestId": "synthetic-lift-stale", "operator": "synthetic-operator",
                    "reason": "Synthetic explicit restoration", "graphVersionId": vid, "expectedRevision": 0, "targets": exclusion["targets"]}
            code, _ = self.cli("stale-lift", lift, exclusion=True); self.check(code != 0, "stale-lift-refused")
            lift.update(requestId="synthetic-lift", expectedRevision=result["revision"])
            code, result = self.cli("lift", lift, exclusion=True); self.check(code == 0, "legacy-lift-applied")
            web.expect("restored-event", event_path, 200)
        self.report["syntheticData"] = {"issues": 1, "publishedThroughAdminHttp": True, "realPublicationEvidence": False}
        self.review_cases(auth)

    def review_cases(self, auth):
        observations = self.report["reviewObservations"]
        with Web(self) as web:
            session = web.expect("review-admin-session", "/api/v1/admin/auth/session", 200, headers=auth)
            headers = {**auth, "Origin": ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrfToken"]}

            def activate(version, label):
                expected = self.db.scalar("SELECT id FROM graph_versions WHERE active")
                code, body = web.request(f"/api/v1/admin/graph/versions/{version}/activate",
                    {"reason": "Synthetic shared-article review regression", "expectedActiveVersionId": expected},
                    {**headers, "Idempotency-Key": label})
                observations.setdefault("R1", {})[label] = {"statusCode": code, "error": body.get("error")}
                return code

            def shared(label):
                source = self.scratch / (label + "-source")
                data, geography, bindings = fixture(source)
                data["origin"]["fixtureCase"] = label
                article = data["articles"][0]["record"]
                old_version = data["articles"][0]["article_version"]
                extra_quote = "Acme forecasts another lab in Seoul, South Korea."
                start = len(article["body"]) + 1
                article["body"] += " " + extra_quote
                second = copy.deepcopy(data["issues"][0])
                second.update(issue_id="issue-synthetic-second", candidate_ids=["candidate-synthetic-second"])
                mention = second["mentions"][0]
                mention.update(mention_id="m2", title="Synthetic second lab", assertion_status="forecast")
                span = mention["evidence"][0]
                span.update(start=start, end=len(article["body"]), quote=extra_quote)
                relation = second["relations"][0]
                relation.update(relation_id="relation-synthetic-second", source=second["issue_id"],
                                assertion_status="forecast", candidate_ids=second["candidate_ids"], evidence=[copy.deepcopy(span)])
                data["issues"].append(second)
                audit = copy.deepcopy(data["candidate_audit"][0])
                audit.update(candidate_id="candidate-synthetic-second", issue_id=second["issue_id"], original_mention=copy.deepcopy(mention))
                audit["validation"]["candidate_id"] = audit["candidate_id"]
                audit["validation"]["verdicts"][1]["target"] = relation["relation_id"]
                data["candidate_audit"].append(audit)
                decision = copy.deepcopy(geography["records"][0])
                decision.update(issue_id=second["issue_id"], source_evidence_ids=["geo-second"])
                geography["records"].append(decision)
                geography["evidence"].append({**span, "evidence_id": "geo-second"})
                new_version = package.sha(package.canonical({k: v for k, v in article.items() if k != "collected_at"}))
                data = json.loads(json.dumps(data).replace(old_version, new_version))
                geography = json.loads(json.dumps(geography).replace(old_version, new_version))
                bindings[0]["originalArticleVersion"] = new_version
                provenance = json.loads((source / "SOURCE_PROVENANCE.json").read_bytes())
                provenance["articles"][0]["article_version"] = new_version
                provenance["articles"][0]["body_sha256"] = package.sha(article["body"].encode())
                provenance["articles"][0]["retained_acquisition_matches"][0]["metadata"]["content_hash"] = provenance["articles"][0]["body_sha256"]
                write(source / "SOURCE_PROVENANCE.json", provenance)
                write(source / "LEGACY_SELECTION.json", data); write(source / "GEOGRAPHY_REVIEW.json", geography)
                root = self.scratch / (label + "-package")
                request, _ = package.prepare(source, root, bindings, company_bindings(data), "synthetic-operator")
                code, result = self.cli(label, request, root)
                self.check(code == 0, label + "-staged", result=result)
                version = result["graphVersionId"]
                row = next(a for a in result["artifacts"] if a["kind"] == "verification_receipt")
                receipt = json.loads((self.artifacts / row["storageUri"].split(":", 1)[1]).read_bytes())
                hidden = next(e["id"] for e in receipt["bundle"]["evidence"] if e["quote"] == extra_quote)
                visible = next(e["id"] for e in receipt["bundle"]["evidence"] if e["start"] == 2)
                return version, row["sha256"], visible, hidden

            excluded, receipt_hash, visible, hidden = shared("shared-exclusion")
            exclusion = {"schemaVersion": "zoop-disclosure-exclusion-1", "action": "exclude-legacy",
                         "requestId": "shared-exclude", "operator": "synthetic-operator", "reason": "Hide second issue only",
                         "graphVersionId": excluded, "receiptSha256": receipt_hash,
                         "targets": [{"kind": "issue", "id": "issue-synthetic-second"}]}
            code, result = self.cli("shared-exclude", exclusion, exclusion=True)
            self.check(code == 0, "shared-exclusion-applied", result=result)
            excluded_status = activate(excluded, "excluded-version-activation")
            if excluded_status == 200:
                web.expect("shared-visible-evidence", f"/api/v1/evidence/{visible}?graphVersion={excluded}", 200)
                web.expect("shared-hidden-evidence", f"/api/v1/evidence/{hidden}?graphVersion={excluded}", 404)
                web.expect("shared-visible-event", f"/api/v1/events/issue-synthetic-lab?graphVersion={excluded}", 200)
                web.expect("shared-hidden-event", f"/api/v1/events/issue-synthetic-second?graphVersion={excluded}", 404)
            web.expect("enable-assertion-rule", "/api/v1/admin/pipeline/rules/speculative-issue%401", 200,
                       {"enabled": True, "reason": "Synthetic assertion-status subtraction"}, headers, method="PUT")
            ruled, _, rule_visible, rule_hidden = shared("shared-rule")
            web.expect("disable-assertion-rule", "/api/v1/admin/pipeline/rules/speculative-issue%401", 200,
                       {"enabled": False, "reason": "End synthetic assertion rule setup"}, headers, method="PUT")
            rule_status = activate(ruled, "rule-version-activation")
            rollback_status = None
            if rule_status == 200:
                web.expect("rule-visible-evidence", f"/api/v1/evidence/{rule_visible}?graphVersion={ruled}", 200)
                web.expect("rule-hidden-evidence", f"/api/v1/evidence/{rule_hidden}?graphVersion={ruled}", 404)
                rollback_status = activate(excluded, "shared-exclusion-rollback")
                if rollback_status == 200:
                    web.expect("rollback-hidden-evidence", f"/api/v1/evidence/{hidden}?graphVersion={excluded}", 404)
                    web.expect("rollback-visible-event", f"/api/v1/events/issue-synthetic-lab?graphVersion={excluded}", 200)
            observations["R1"]["passed"] = excluded_status == rule_status == rollback_status == 200
            auto_source = self.scratch / "auto-source"
            auto_data, _, auto_bindings = fixture(auto_source)
            auto_data["origin"]["fixtureCase"] = "automatic-activation-boundary"
            write(auto_source / "LEGACY_SELECTION.json", auto_data)
            auto_root = self.scratch / "auto-package"
            auto_request, _ = package.prepare(auto_source, auto_root, auto_bindings, company_bindings(auto_data), "synthetic-operator")
            code, result = self.cli("auto-legacy-stage", auto_request, auto_root)
            self.check(code == 0, "auto-legacy-staged")
            auto_version = result["graphVersionId"]
            previous = self.db.scalar("SELECT id FROM graph_versions WHERE active")
        with Web(self, auto_activation=True) as web:
            time.sleep(1.5)
            active = self.db.scalar("SELECT id FROM graph_versions WHERE active")
            observations["R2"] = {"stagedVersion": auto_version, "previous": previous, "afterScheduler": active,
                                  "passed": previous == active}
            session = web.expect("scheduler-admin-session", "/api/v1/admin/auth/session", 200, headers=auth)
            headers = {**auth, "Origin": ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrfToken"],
                       "Idempotency-Key": "explicit-auto-excluded-legacy"}
            web.expect("explicit-legacy-with-scheduler", f"/api/v1/admin/graph/versions/{auto_version}/activate", 200,
                       {"reason": "Explicit legacy publication with scheduler enabled", "expectedActiveVersionId": active}, headers)
        self.check(all(row["passed"] for row in observations.values()), "review-regressions", observations=observations)


class Web:
    def __init__(self, smoke, auto_activation=False):
        self.smoke = smoke
        env = {**smoke.env, "ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(smoke.artifacts),
               "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(smoke.artifacts), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(smoke.sources),
               "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "synthetic-legacy", "ZOOP_AUTH_CSRF_KEYS": "synthetic-legacy=" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="),
               "ZOOP_AUTH_ALLOWED_ORIGINS": ORIGIN, "ZOOP_API_CORS_ALLOWED_ORIGINS": ORIGIN, "SPRING_PROFILES_ACTIVE": "local"}
        env.update(ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED=str(auto_activation).lower(), ZOOP_GRAPH_AUTO_ACTIVATION_INTERVAL="PT0.2S")
        self.process = subprocess.Popen(smoke.argv("--server.port=0", "--server.address=127.0.0.1"), cwd=smoke.scratch, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.lines = []
        self.reader = threading.Thread(target=self.drain, daemon=True); self.reader.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.port = None

    def drain(self):
        for line in self.process.stdout:
            text = line.decode("utf-8", "replace")
            self.lines.append(text)
            found = re.search(r"Tomcat started on port (\d+)", text)
            if found:
                self.port = int(found.group(1))

    def __enter__(self):
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and self.process.poll() is None:
            if self.port and any("Started ZoopApplication" in line for line in self.lines):
                return self
            time.sleep(0.2)
        self.__exit__()
        raise AssertionError("owned web server startup")

    def __exit__(self, *args):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=10)
        self.reader.join(timeout=10)
        (self.smoke.scratch / "web.log").write_text("".join(self.lines).replace(self.smoke.env["DB_PASSWORD"], "[redacted]"))

    def request(self, path, payload=None, headers=None, method=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}" + path, data=None if payload is None else package.canonical(payload), headers=headers or {}, method=method)
        try:
            with self.opener.open(request, timeout=60) as response:
                code, body = response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            code, body = error.code, json.loads(error.read())
        return code, body

    def expect(self, label, path, status, payload=None, headers=None, method=None):
        code, body = self.request(path, payload, headers, method)
        self.smoke.check(code == status, label, statusCode=code, errorCode=body.get("error", {}).get("code"))
        return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=local.DEFAULT_JAR)
    parser.add_argument("--java")
    parser.add_argument("--actual-package", type=Path)
    parser.add_argument("--actual-request", type=Path)
    parser.add_argument("--actual-sources", type=Path)
    parser.add_argument("--actual-catalogue", type=Path)
    parser.add_argument("--actual-additions", type=Path)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--repository-check", action="store_true")
    args = parser.parse_args()
    args.jar = args.jar.resolve(); args.result = args.result.resolve()
    actual = (args.actual_package, args.actual_request, args.actual_sources, args.actual_catalogue, args.actual_additions)
    if any(actual) and not all(actual):
        parser.error("all five --actual-* paths must be provided together")
    if args.result.exists():
        parser.error("result must be new")
    clean = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "JAVA_HOME", "DOCKER_CONTEXT", "DOCKER_CONFIG", "TMPDIR") if k in os.environ}
    os.environ.clear(); os.environ.update(clean)
    args.java = local.find_java(args.java)
    if not Path("/usr/bin/sandbox-exec").is_file():
        parser.error("macOS sandbox-exec required for external network denial")
    scratch = Path(tempfile.mkdtemp(prefix="legacy-real-proof-", dir=REPO / "api/build")).resolve()
    owned = "zoop-legacy-real-smoke-" + secrets.token_hex(8)
    report = {"status": "failed", "steps": [], "commands": [], "providerCalls": 0, "modelCalls": 0, "paidEndpointDeny": "OS network sandbox: loopback only", "work": str(scratch)}
    created = False
    try:
        endpoint = local.docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
        database.check(endpoint.returncode == 0 and endpoint.stdout.strip().startswith("unix://"), "local Docker socket required")
        local.preflight_docker(local.DEFAULT_IMAGE)
        password = secrets.token_urlsafe(32)
        started = local.docker("run", "-d", "--pull", "never", "--name", owned, "--label", "com.zoop.legacy-real-smoke=1",
                               "--tmpfs", "/var/lib/postgresql/data", "-e", "POSTGRES_DB=" + local.DB_NAME, "-e", "POSTGRES_USER=" + local.DB_USER,
                               "-e", "POSTGRES_PASSWORD", "-p", "127.0.0.1::5432", local.DEFAULT_IMAGE, env={**clean, "POSTGRES_PASSWORD": password})
        database.check(started.returncode == 0, "owned cached PostgreSQL startup")
        created = True
        mapping = local.docker("port", owned, "5432/tcp").stdout.strip()
        database.check(mapping.startswith("127.0.0.1:") and "\n" not in mapping, "unique loopback PostgreSQL port")
        port = int(mapping.rsplit(":", 1)[1]); local.wait_database(owned, port)
        env = {**clean, "DB_URL": f"jdbc:postgresql://127.0.0.1:{port}/{local.DB_NAME}", "DB_USERNAME": local.DB_USER, "DB_PASSWORD": password,
               "ZOOP_METRICS_PROVIDER": "off", "ZOOP_GRAPH_SNAPSHOT_SOURCE": "none", "ZOOP_AI_CLIENT_ENABLED": "false",
               "ZOOP_AI_EXTRACTION_CLIENT_ENABLED": "false", "ZOOP_AI_RELATION_CLIENT_ENABLED": "false", "ZOOP_AI_CHAT_CLIENT_ENABLED": "false",
               "ZOOP_CHAT_QUESTIONS_ENABLED": "false", "ZOOP_CHAT_EXECUTOR_ENABLED": "false", "ZOOP_SWAGGER_ENABLED": "false",
               "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "synthetic-legacy",
               "ZOOP_AUTH_CSRF_KEYS": "synthetic-legacy=" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")}
        db = database.Database(env["DB_URL"], local.DB_USER, password, local.DB_NAME, owned, None)
        database.check(not db.tables_exist(), "owned database must be empty")
        if args.repository_check:
            db.run("CREATE ROLE company_test LOGIN PASSWORD 'synthetic-test-only'")
            db.run("CREATE DATABASE zoop_company_test_19 OWNER company_test")
            checked = subprocess.run(["/usr/bin/sandbox-exec", "-p", SANDBOX, str(REPO / "api/gradlew"),
                "--offline", "--no-daemon", "companyIntegrationTest", "--tests",
                "com.zoop.graph.GraphVersionPostgresIntegrationTest.legacySnapshotRequiresExplicitActivationWhileNativeCandidateRemainsEligible",
                "--max-workers=2"], cwd=REPO / "api", env={**clean,
                "ZOOP_COMPANY_TEST_DB_URL": f"jdbc:postgresql://127.0.0.1:{port}/zoop_company_test_19",
                "ZOOP_COMPANY_TEST_DB_PASSWORD": "synthetic-test-only"}, capture_output=True, timeout=240)
            (scratch / "repository-test.log").write_bytes(checked.stdout + checked.stderr)
            report["repositoryTestExitCode"] = checked.returncode
        smoke = Smoke(args, scratch, env, db, report)
        if args.actual_package:
            smoke.run_actual()
        else:
            smoke.run()
        database.check(not args.repository_check or report["repositoryTestExitCode"] == 0, "native/legacy automatic eligibility regression")
        report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        report["failure"] = {"type": type(error).__name__, "message": str(error)[:200]}
    finally:
        if created:
            local.docker("stop", "--time", "20", owned)
            removed = local.docker("rm", "-v", owned)
            report["ownedContainerRemoved"] = removed.returncode == 0
            if not report["ownedContainerRemoved"]:
                report["status"] = "failed"
        with args.result.open("x") as out:
            json.dump(report, out, ensure_ascii=False, indent=2)
        print(json.dumps({"status": report["status"], "steps": len(report["steps"]), "result": str(args.result), "failure": report.get("failure")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
