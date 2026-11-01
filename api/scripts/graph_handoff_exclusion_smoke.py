#!/usr/bin/env python3
"""Installed exposure CLI -> real operator exclusion runner -> public HTTP, synthetic only.

Run from the repository root with the installed pipeline Python:
  ai/pipeline/.venv/bin/python api/scripts/graph_handoff_exclusion_smoke.py \
    --result /tmp/zoop-graph-exclusion-result.json

Requires an existing current API boot jar, JDK 21+, installed pipeline console
scripts and the cached project PostgreSQL image on local OrbStack. Never builds,
installs, pulls, borrows a database, acquires articles or calls a provider/model.
Uses the activation smoke's owned DB, isolated environment and cleanup lifecycle.
SQL seeds only synthetic catalog/auth fixtures; activation is real admin HTTP and
all exclusion/lift writes go through the non-web operator runner. Synthetic rights
stay unchanged: a hypothetical source-change report is not a rights withdrawal,
and lifting an exclusion does not grant permission to disclose withdrawn text.
"""
from __future__ import annotations

import base64
from datetime import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import urllib.parse

sys.dont_write_bytecode = True

import graph_handoff_activation_smoke as activation

handoff = activation.handoff
hs, base, check = handoff.hs, handoff.base, handoff.check
from scripts import handoff_exposure_smoke as exposure  # noqa: E402

SCHEMA = "zoop-disclosure-exclusion-1"
HANDOFFS = ("handoff-exclusion-1", "handoff-exclusion-control-1")


def tree_pin(root):
    return hs.digest({str(path.relative_to(root)): handoff.sha256(path.read_bytes())
                      for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts})


def provenance(args, evidence):
    """Pin actual installed package bytes, not just a checkout HEAD beside an unrelated venv."""
    from zoop_ai_pipeline import ingestion_contracts

    expected = tree_pin(handoff.PIPELINE / "src/zoop_ai_pipeline")
    package = Path(ingestion_contracts.__file__).resolve().parent
    check(tree_pin(package) == expected, "pipeline interpreter package differs from current source")
    installed = {"name": "zoop-ai-pipeline", "version": importlib.metadata.version("zoop-ai-pipeline"),
                 "sourceSha256": expected, "consoleScripts": {}}
    # Each console script may have a different shebang/venv. Inspect that interpreter too.
    program = '''import hashlib, importlib.metadata, json
from pathlib import Path
from zoop_ai_pipeline import ingestion_contracts
root = Path(ingestion_contracts.__file__).resolve().parent
files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts}
raw = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
print(json.dumps({"sourceSha256": hashlib.sha256(raw).hexdigest(),
                  "version": importlib.metadata.version("zoop-ai-pipeline")}))
'''
    for cli in (args.handoff_cli, args.ingest_cli, handoff.PIPELINE / ".venv/bin/zoop-ai-handoff-exposure"):
        check(cli.is_file() and os.access(cli, os.X_OK), "installed pipeline console script required")
        first = cli.read_text().splitlines()[0]
        check(first.startswith("#!/") and " " not in first[2:], "console script needs an absolute Python shebang")
        done = subprocess.run([first[2:], "-c", program], env={**activation.START_ENV, **hs.CUSTOM},
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        check(done.returncode == 0, "console script interpreter provenance unavailable")
        pin = json.loads(done.stdout)
        check(pin == {"sourceSha256": expected, "version": installed["version"]},
              "console script package differs from current source")
        installed["consoleScripts"][cli.name] = {**pin, "scriptSha256": handoff.sha256(cli.read_bytes())}
    evidence["pipelinePackage"] = installed
    evidence["sourceFiles"] = {str(path.relative_to(activation.REPO)): handoff.sha256(path.read_bytes()) for path in (
        Path(__file__).resolve(), Path(activation.__file__).resolve(), Path(handoff.__file__).resolve(),
        Path(base.__file__).resolve(), Path(hs.__file__).resolve(), Path(exposure.__file__).resolve(),
        Path(activation.local.__file__).resolve(),
        handoff.PIPELINE / "pyproject.toml", handoff.PIPELINE / "uv.lock")}


def exclusion_state(db):
    """Inspect append-only operator state; never seed or repair an exclusion with SQL."""
    return {"revision": db.scalar("SELECT coalesce(max(revision), 0) FROM disclosure_exclusion_changes"),
            "changes": db.rows("SELECT * FROM disclosure_exclusion_changes ORDER BY revision"),
            "targets": db.rows("SELECT * FROM disclosure_exclusion_targets ORDER BY revision, graph_version_id, target_kind, target_id, article_version"),
            "requests": db.rows("SELECT * FROM disclosure_exclusion_requests ORDER BY request_id")}


def targets(report):
    """Translate producer identities to the operator's explicit typed lift input, without inferring scope."""
    row, = report["handoffs"]
    return ([{"kind": "article", "id": a["articleId"], "articleVersion": a["articleVersion"]} for a in row["articles"]]
            + [{"kind": kind, "id": item["id"]} for key, kind in (("issues", "issue"), ("relations", "relation")) for item in row[key]]
            + [{"kind": "evidence", "id": eid} for eid in row["evidenceIds"]])


class Operator:
    def __init__(self, smoke, evidence):
        self.smoke, self.evidence, self.runs = smoke, evidence, 0

    def run(self, label, request, *, outcome=None, failure=None, replay=False):
        self.evidence["phase"] = label
        entry = {"step": label, "status": "failed", "requestSha256": hs.digest(request)}
        self.evidence["steps"].append(entry)
        self.runs += 1
        request_path = self.smoke.layout.requests / f"exclusion-{self.runs}-request.json"
        result_path = self.smoke.layout.requests / f"exclusion-{self.runs}-result.json"
        request_path.write_bytes(hs.json_bytes(request))
        request_path.chmod(0o600)
        env = {**self.smoke.jar.base_env(), "ZOOP_DISCLOSURE_EXCLUSION_ENABLED": "true",
               "ZOOP_DISCLOSURE_EXCLUSION_REQUEST": str(request_path),
               "ZOOP_DISCLOSURE_EXCLUSION_RESULT": str(result_path),
               "ZOOP_ARTIFACT_ROOT": str(self.smoke.layout.artifacts)}
        done = subprocess.run(self.smoke.jar.argv("--spring.main.web-application-type=none"), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
        entry["exitCode"] = done.returncode
        check(result_path.is_file() and stat.S_IMODE(result_path.stat().st_mode) == 0o600,
              label + ": missing or non-owner-only operator result")
        raw = result_path.read_bytes()
        result = json.loads(raw)
        entry.update({"result": result, "resultSha256": handoff.sha256(raw)})
        check(result.get("schemaVersion") == SCHEMA, label + ": unexpected operator schema")
        if failure:
            check(done.returncode != 0 and result.get("status") == "failed"
                  and result.get("failure", {}).get("code") == failure, label + ": expected refusal missing")
        else:
            check(done.returncode == 0 and result.get("status") == "succeeded"
                  and result.get("outcome") == outcome and result.get("replayed") is replay,
                  label + ": unexpected operator outcome")
        entry["status"] = "passed"
        return result


def scenario(args, db, scratch, evidence, layouts):
    def check(condition, message):
        evidence.setdefault("checks", []).append({"failureMessage": message, "status": "passed" if condition else "failed"})
        handoff.check(condition, message)

    evidence["phase"] = "source-package-pins"
    provenance(args, evidence)
    evidence["phase"] = "synthetic-cli-world"
    # Historical version-pinned reads require an authored publication time for the factory article.
    b_published_at = "2026-10-08T00:00:00+00:00"
    world = hs.build_world(scratch / "world", b_published_at=b_published_at)
    # Reuse the exposure smoke's genuine recorded-but-unbound document, not an edited empty report.
    extra = world.kit.ingest("extra", [{"supplier": "supplier-extra", "html": exposure.page(exposure.EXTRA_TEXT)}])[0]
    check(extra["documentId"] not in {ref["documentId"] for ref in world.refs.values()}, "empty report identity must be independent")
    decisions = hs.decisions_doc(world)
    for company in decisions["companies"]:
        company["publicId"] = handoff.PUBLIC_IDS[company["publicId"]]
    hs.write_operator(world, decisions=decisions)
    producer = hs.Operator(world)
    exports, manifests = {}, {}
    for hid in HANDOFFS:
        manifest = hs.manifest_doc(world, hid, hs.file_hashes(world.root))
        check(producer.cli("freeze", manifest)["state"] == "ready", "synthetic CLI freeze failed")
        manifests[hid] = manifest
        exports[hid] = producer.cli("export", producer.sel(hid))
        check(exports[hid]["bundle"]["schemaVersion"] == "zoop-graph-handoff-bundle-8", "expected bundle8")
        factory_article, = (article for article in exports[hid]["bundle"]["articles"]
                            if (article["documentId"], article["documentVersion"])
                            == (world.refs["b"]["documentId"], world.refs["b"]["documentVersion"]))
        check(factory_article["publicationPrecision"] == "datetime"
              and datetime.fromisoformat(factory_article["publishedAt"]) == datetime.fromisoformat(b_published_at),
              "factory article publication differs from the authored timestamp")
    evidence["steps"].append({"step": "synthetic-cli-handoffs", "status": "passed", "handoffs": list(HANDOFFS),
                              "bundle": "zoop-graph-handoff-bundle-8", "factoryPublishedAt": b_published_at})
    layout = handoff.Layout(world, args.ingest_cli)
    layouts.append(layout.work)
    smoke = handoff.Smoke(args, db, layout)
    smoke.jar = activation.FixtureJar(args.java, args.jar, db, layout)
    before_ledgers = {name: handoff.fingerprint(path) for name, path in layout.ledgers.items()}
    registry = layout.registry_path.read_bytes()
    evidence["phase"] = "spring-document-import"
    code, result, _ = smoke.jar.run("documents", [base.item(ref) for ref in world.refs.values()], artifact_root=layout.artifacts)
    check(code == 0 and result and result["status"] == "succeeded", "document staging failed")
    db.run("INSERT INTO companies (id, name, name_key, search_text) VALUES "
           + ", ".join(f"('{cid}', '{name}', '', '')" for cid, name in handoff.COMPANIES))
    with activation.Web(smoke.jar, {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture"}, ready="Graph fixture fixture-2026-10-08 "):
        pass
    before_import = activation.publication_state(db)
    for hid in HANDOFFS:
        evidence["phase"] = "spring-handoff-import"
        out = exports[hid]
        code, result, _ = smoke.graph_import("exclusion-stage", smoke.request(hid, hs.digest(manifests[hid]), hs.digest(out["bundle"])))
        check(code == 0 and result and result["outcome"] == "staged" and result["active"] is False,
              "handoff staging failed")
    after_import = activation.publication_state(db)
    check(before_import["active"] == after_import["active"] and before_import["activations"] == after_import["activations"],
          "staging changed activation")
    evidence.update({"importActivationWrites": 0, "sqlHarnessActivations": 0,
                     "fixtureSeedActivations": len(before_import["activations"]), "producerReports": {}})

    def report(label, changed, selected):
        evidence["phase"] = label
        entry = {"step": label, "status": "failed"}
        evidence["steps"].append(entry)
        run = exposure.expose(world.root, exposure.q(selected, changed), state=world.root / "handoff",
                              ledgers={name: world.root / name for name in ("ingestion", "extraction")})
        out = run.out
        check(out["usage"] == {"providerCalls": 0, "modelCalls": 0}, "exposure reported external calls")
        for row in out["handoffs"]:
            receipt = exports[row["handoffId"]]["receipt"]
            check(all(row[key] == receipt[key] for key in ("manifestDigest", "bundleDigest", "contentDigest")),
                  "producer exposure differs from frozen receipt")
        evidence["producerReports"][label] = {"report": out, "rawSha256": handoff.sha256(run.text.encode()),
                                              "auditViolations": run.audit["violations"]}
        entry["status"] = "passed"
        return out

    hid, control_hid = HANDOFFS
    source_vid, control_vid = map(handoff.version_id, HANDOFFS)
    public_bundles = {control_vid: exports[control_hid]["bundle"]}
    full = report("producer-source-report", exposure.source_change(world.refs["a"]["sourceId"]), [hid])
    smaller = report("producer-smaller-document-report", exposure.doc_change(world.refs["a2"]), [hid])
    empty = report("producer-recorded-unbound-empty-report", exposure.doc_change(extra), [hid])
    both = report("producer-two-version-report", exposure.source_change(world.refs["a"]["sourceId"]), list(HANDOFFS))
    target_keys = lambda doc: {hs.canonical(t) for t in targets(doc)}
    check(target_keys(smaller) < target_keys(full) and target_keys(smaller), "document report must be a genuine nonempty strict subset")
    check(empty["identity"] == {"boundInSelection": False, "recordedInIngestion": True}
          and not targets(empty) and not empty["handoffs"][0]["exposed"], "producer empty identity is not legitimately recorded/unbound")
    check(hs.SUPPLY in {item["id"] for item in full["handoffs"][0]["issues"]}, "source report misses authored supply issue")
    eid = hs.evidence_id(world, "a", hs.EVT_A)
    check(eid in full["handoffs"][0]["evidenceIds"], "source report misses authored quote")
    operator = Operator(smoke, evidence)

    def exclude(request_id, doc):
        return {"schemaVersion": SCHEMA, "requestId": request_id, "action": "exclude", "operator": "synthetic-operator",
                "reason": "Synthetic exclusion review; no real source or rights withdrawal", "report": doc}

    auth = activation.bootstrap_session(db)
    key = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts),
           "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(layout.artifacts), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(layout.registry_path),
           "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "activation-test", "ZOOP_AUTH_CSRF_KEYS": "activation-test=" + key,
           "SPRING_PROFILES_ACTIVE": "local", "ZOOP_AUTH_ALLOWED_ORIGINS": activation.ORIGIN,
           "ZOOP_API_CORS_ALLOWED_ORIGINS": activation.ORIGIN}

    def http(web, label, path, status=200, *, payload=None, headers=None, error=None):
        evidence["phase"] = label
        entry = {"step": label, "status": "failed", "expectedStatusCode": status}
        evidence["steps"].append(entry)
        code, raw, _ = web.request(path, payload=payload, headers=headers)
        entry.update({"statusCode": code, "responseSha256": handoff.sha256(raw)})
        body = json.loads(raw)
        observed = (body.get("error") or {}).get("code")
        if observed:
            entry["errorCode"] = observed
        check(code == status and (error is None or observed == error), label + ": unexpected public HTTP result")
        entry["status"] = "passed"
        return body

    def reads(web, label, version, *, hidden):
        query = "?" + urllib.parse.urlencode({"graphVersion": version})
        graph = http(web, label + "-graph", "/api/v1/graph" + query)
        check(graph["metadata"]["graphVersion"] == version, "graph read selected another version")
        issue_ids = {item["id"] for item in full["handoffs"][0]["issues"]}
        relation_ids = {item["id"] for item in full["handoffs"][0]["relations"]}
        bundle = public_bundles[version]
        selected_relations = [row for row in bundle["relations"] if row["id"] in relation_ids]
        check({row["id"] for row in selected_relations} == relation_ids, "report relations are not mapped by the selected bundle")
        # Producer relation IDs identify snapshot rows. Public display edges group those
        # rows by (type, source, target) and have different, shortened IDs (DisplayGraph).
        # Compare that public identity without copying the display-edge hash algorithm.
        expected_relations = {(row["type"], row["source"], row["target"]) for row in selected_relations}
        observed_relations = {(edge["relationType"], edge["source"], edge["target"])
                              for edge in graph["edges"] if not edge["derived"]}
        nodes = {node["id"] for node in graph["nodes"]}
        evidence["steps"][-1]["graphProjection"] = {
            "issueIds": sorted(node["id"] for node in graph["nodes"] if node["kind"] == "issue"),
            "edges": [{key: edge[key] for key in ("id", "relationType", "source", "target", "derived", "via")}
                      for edge in graph["edges"]],
            "expectedRelations": [list(row) for row in sorted(expected_relations)]}
        check((not issue_ids & nodes and not expected_relations & observed_relations)
              if hidden else (issue_ids <= nodes and expected_relations <= observed_relations),
              label + ": graph exclusion projection differs")
        if hidden:
            check(all(not issue_ids.intersection(edge["via"]) for edge in graph["edges"] if edge["derived"]),
                  label + ": excluded issues leaked through derived edges")
        event = http(web, label + "-event", "/api/v1/events/" + urllib.parse.quote(hs.SUPPLY, safe="") + query,
                     404 if hidden else 200, error="RESOURCE_NOT_FOUND" if hidden else None)
        quote = http(web, label + "-evidence", f"/api/v1/evidence/{eid}" + query,
                     404 if hidden else 200, error="EVIDENCE_UNAVAILABLE" if hidden else None)
        if not hidden:
            span = hs.span(world, "a", hs.EVT_A)
            check(event["metadata"]["graphVersion"] == version and event["id"] == hs.SUPPLY, "event version mismatch")
            check(quote["metadata"]["graphVersion"] == version and quote["quote"] == hs.EVT_A and quote["quoteVerified"] is True
                  and quote["start"] == span["start"] and quote["end"] == span["end"]
                  and quote["articleId"] == span["documentId"] and quote["articleVersion"] == span["documentVersion"],
                  "evidence exact span/version mismatch")

    def activate(web, headers, version, expected):
        observed = db.scalar("SELECT id FROM graph_versions WHERE active")
        check(observed == expected, "activation setup pointer changed")
        body = http(web, "admin-http-activation-" + version, f"/api/v1/admin/graph/versions/{version}/activate",
                    payload={"reason": "Synthetic exclusion roundtrip", "expectedActiveVersionId": observed, "mode": "forward"},
                    headers={**headers, "Idempotency-Key": "activate-" + version})
        check(body == {"activeVersionId": version, "previousActiveVersionId": observed, "idempotent": False},
              "admin activation contract mismatch")

    with activation.Web(smoke.jar, env) as web:
        session = http(web, "synthetic-admin-session", "/api/v1/admin/auth/session", headers=auth)
        check(session.get("authenticated") is True and session.get("csrfToken"), "synthetic session unavailable")
        headers = {**auth, "Origin": activation.ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrfToken"]}
        activate(web, headers, control_vid, after_import["active"])
        # Once an original is public, forward activation requires a composed candidate based on it.
        evidence["phase"] = "compose-public-target"
        before_compose = activation.publication_state(db)
        check(before_compose["active"] == control_vid, "composition base is not the published control")
        decisions_path = layout.requests / "compose-decisions.json"
        decisions_bytes = hs.json_bytes({"schemaVersion": "zoop-graph-publication-decisions-1",
                                        "issueMappings": [], "fieldSelections": [], "relationSelections": []})
        decisions_path.write_bytes(decisions_bytes)
        decisions_path.chmod(0o600)
        receipt_pins = {version: db.scalar(
            f"SELECT sha256 FROM artifacts WHERE id = 'artifact-receipt-{version}'")
            for version in (control_vid, source_vid)}
        compose_request = {
            "schemaVersion": "zoop-graph-publication-compose-1", "baseVersionId": control_vid,
            "incomingVersionIds": [source_vid], "expectedActiveVersionId": before_compose["active"],
            "expectedBaseReceiptSha256": receipt_pins[control_vid],
            "incomingReceiptPins": [{"versionId": source_vid, "sha256": receipt_pins[source_vid]}],
            "expectedRuleRevision": db.scalar("SELECT COALESCE(MAX(log_revision), 0) FROM publication_rule_changes"),
            "expectedReviewRevision": db.scalar("SELECT COALESCE(MAX(global_revision), 0) FROM review_decisions"),
            "decisionsSha256": handoff.sha256(decisions_bytes), "operator": "synthetic-operator"}
        request_path = layout.requests / "compose-request.json"
        result_path = layout.requests / "compose-result.json"
        request_path.write_bytes(hs.json_bytes(compose_request))
        request_path.chmod(0o600)
        entry = {"step": "compose-public-target", "status": "failed", "request": compose_request,
                 "requestSha256": hs.digest(compose_request)}
        evidence["steps"].append(entry)
        compose_env = {**smoke.jar.base_env(), "ZOOP_GRAPH_PUBLICATION_COMPOSE_ENABLED": "true",
                       "ZOOP_GRAPH_PUBLICATION_COMPOSE_REQUEST": str(request_path),
                       "ZOOP_GRAPH_PUBLICATION_COMPOSE_RESULT": str(result_path),
                       "ZOOP_GRAPH_PUBLICATION_COMPOSE_DECISIONS": str(decisions_path),
                       "ZOOP_GRAPH_PUBLICATION_COMPOSE_ARTIFACT_ROOT": str(layout.artifacts),
                       "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(layout.registry_path)}
        done = subprocess.run(smoke.jar.argv("--spring.main.web-application-type=none"), env=compose_env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=420)
        entry["exitCode"] = done.returncode
        check(result_path.is_file() and stat.S_IMODE(result_path.stat().st_mode) == 0o600,
              "missing or non-owner-only composition result")
        raw = result_path.read_bytes()
        composed = json.loads(raw)
        entry.update({"result": composed, "resultSha256": handoff.sha256(raw)})
        check(done.returncode == 0 and composed["schemaVersion"] == "zoop-graph-publication-compose-result-1"
              and composed["status"] == "succeeded" and composed["outcome"] == "staged"
              and composed["activation"] == "not-activated" and composed["baseVersionId"] == control_vid
              and composed["expectedActiveVersionId"] == control_vid and composed["incomingVersionIds"] == [source_vid],
              "public target composition failed")
        after_compose = activation.publication_state(db)
        check(all(after_compose[key] == before_compose[key] for key in ("active", "activations", "audit", "idempotency"))
              and all(row in after_compose["versions"] for row in before_compose["versions"]),
              "composition changed existing publication state")
        vid = composed["graphVersionId"]
        check(composed["receiptSha256"] == db.scalar(
            f"SELECT sha256 FROM artifacts WHERE id = 'artifact-receipt-{vid}'"),
            "composed target receipt pin mismatch")
        public_bundles[vid] = exports[hid]["bundle"]
        entry["status"] = "passed"
        activate(web, headers, vid, control_vid)
        published = activation.publication_state(db)
        check(published["active"] == vid and len(published["activations"]) == len(after_import["activations"]) + 2,
              "admin activation history mismatch")
        evidence.update({"graphVersion": vid, "sourceGraphVersion": source_vid, "unaffectedGraphVersion": control_vid,
                         "compositionRuns": 1, "adminHttpActivations": 2, "httpPointerChanges": 2})
        reads(web, "baseline", vid, hidden=False)
        reads(web, "control-baseline", control_vid, hidden=False)
        artifact_before = handoff.fingerprint(layout.artifacts)
        initial = exclusion_state(db)
        check(initial["revision"] == 0 and not initial["requests"], "fresh exclusion store is not empty")
        # Deliberately corrupt ONE pin in the second selected receipt, not producer proof.
        check([row["handoffId"] for row in both["handoffs"]] == list(HANDOFFS), "two-version report order changed")
        for pin in ("manifestDigest", "bundleDigest", "contentDigest"):
            invalid = json.loads(hs.canonical(both))
            row = invalid["handoffs"][1]
            row[pin] = "0" * 64 if row[pin] != "0" * 64 else "1" * 64
            operator.run("mismatched-" + pin, exclude("bad-" + pin, invalid), failure="receipt_mismatch")
            check(exclusion_state(db) == initial, "receipt mismatch partially wrote exclusions/requests or advanced revision")
        request = exclude("exclude-initial", full)
        applied = operator.run("exclude-source-report", request, outcome="applied")
        excluded = exclusion_state(db)
        check(applied["revision"] == excluded["revision"] == 1 and len(excluded["requests"]) == 1,
              "first exclusion revision/request mismatch")
        reads(web, "excluded", vid, hidden=True)
        reads(web, "control-after-exclusion", control_vid, hidden=False)
        replay = operator.run("same-request-replay", request, outcome="applied", replay=True)
        check(replay == {**applied, "replayed": True} and exclusion_state(db) == excluded, "exclude replay changed state")
        for label, doc in (("empty-report-no-clear", empty), ("smaller-report-no-clear", smaller)):
            before = exclusion_state(db)
            result = operator.run(label, exclude(label, doc), outcome="unchanged")
            after = exclusion_state(db)
            check(result["revision"] == after["revision"] == before["revision"]
                  and after["changes"] == before["changes"] and after["targets"] == before["targets"]
                  and len(after["requests"]) == len(before["requests"]) + 1, "empty/smaller report changed prior exclusions")
            reads(web, label, vid, hidden=True)
        observed = exclusion_state(db)["revision"]
        lift = {"schemaVersion": SCHEMA, "requestId": "lift-observed", "action": "lift", "operator": "synthetic-operator",
                "reason": "Explicit synthetic restoration decision; source rights remain unchanged", "graphVersionId": source_vid,
                "expectedRevision": observed, "targets": targets(full)}
        lifted = operator.run("explicit-lift-observed-revision", lift, outcome="applied")
        check(lifted["revision"] == observed + 1 == exclusion_state(db)["revision"], "lift did not advance one revision")
        reads(web, "explicitly-restored", vid, hidden=False)
        reads(web, "control-after-lift", control_vid, hidden=False)
        reapplied = operator.run("re-exclude-new-decision", exclude("exclude-new-decision", full), outcome="applied")
        reexcluded = exclusion_state(db)
        check(reapplied["revision"] == lifted["revision"] + 1 == reexcluded["revision"], "re-exclusion revision mismatch")
        reads(web, "reexcluded", vid, hidden=True)
        old = operator.run("old-successful-lift-replay", lift, outcome="applied", replay=True)
        check(old == {**lifted, "replayed": True} and exclusion_state(db) == reexcluded,
              "old successful lift replay undid the new exclusion")
        reads(web, "old-lift-replay-still-hidden", vid, hidden=True)
        stale = {**lift, "requestId": "lift-stale-new-decision"}
        operator.run("new-lift-stale-revision", stale, failure="revision_stale")
        check(exclusion_state(db) == reexcluded, "stale lift changed state")
        reads(web, "control-final", control_vid, hidden=False)
        check(activation.publication_state(db) == published, "exclusion/lift or reads changed publication state")
        check(handoff.fingerprint(layout.artifacts) == artifact_before, "exclusion/lift changed immutable artifact store")
        evidence.update({"finalExclusionRevision": reexcluded["revision"], "oldLiftReplayRevision": old["revision"],
                         "receiptMismatchAtomic": True, "emptyAndSmallerNeverClear": True,
                         "differentVersionUnaffected": True, "publicationUnchanged": True, "artifactsUnchanged": True,
                         "operatorRuns": operator.runs})
    check(layout.registry_path.read_bytes() == registry, "source rights registry changed")
    check({name: handoff.fingerprint(path) for name, path in layout.ledgers.items()} == before_ledgers, "source ledgers changed")
    evidence.update({"ledgerReadOnly": True, "sourceRights": "unchanged; exclusion lift is not rights restoration",
                     "producerAudit": {"runs": exposure.STATS["runs"], "violations": exposure.STATS["auditViolations"]}})


if __name__ == "__main__":
    sys.exit(activation.run_smoke(scenario, smoke_name="exclusion", description=__doc__, not_proven=[
        "real-source rights or restoration policy", "production publication readiness", "internal exposure HTTP transport",
        "password login/OAuth/operator provisioning", "articles/S1/briefings/chat/caches/Neo4j exclusion", "external AI/model path"]))
