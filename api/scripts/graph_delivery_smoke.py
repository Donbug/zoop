#!/usr/bin/env python3
"""Synthetic current native CLI -> Java seal -> PostgreSQL -> isolated Java install -> admin HTTP.

Adapted from the historical delivery smoke. Uses existing native-8 helpers and cached local tools, an owned disposable
PostgreSQL container/network, independent producer/serving roots and a separately deployed serving registry. Keeps redacted
command logs/results beside the exclusive result file; removes only its own runtime resources. Never builds or installs.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse

sys.dont_write_bytecode = True
import graph_handoff_activation_smoke as activation
import graph_handoff_import_smoke as handoff
import local_graph_dev as local

REPO = Path(__file__).resolve().parents[2]
LABEL = "com.zoop.native-delivery-smoke"
DESTINATION = "synthetic-serving"
START_ENV = activation.isolated_environment(dict(os.environ))
check = handoff.check


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def files(root):
    found = {}
    for item in sorted(root.rglob("*")):
        relative = str(item.relative_to(root))
        # Closing any descriptor for this inode can release this process's POSIX lock.
        if relative == ".document-import.lock":
            continue
        if item.is_file():
            info = item.stat()
            found[relative] = (stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid, info.st_size,
                               info.st_mtime_ns, handoff.sha256(item.read_bytes()))
    return found


def delivery_state(db):
    return {table: db.rows(f"SELECT * FROM {table} ORDER BY 1, 2") for table in
            ("graph_delivery_packages", "graph_delivery_destinations", "graph_delivery_installs")} | {
        "contents": db.rows("SELECT artifact_id, sha256, bytes, md5(content) AS actual, stored_at FROM graph_delivery_contents ORDER BY artifact_id")}


def wait_until(condition, message, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(message)


def sandbox(world, producer):
    return ["/usr/bin/sandbox-exec", "-p", '(version 1) (allow default) '
            + f'(deny file-read* (subpath {json.dumps(str(world))}) (subpath {json.dumps(str(producer))})) '
            + '(deny process-exec (regex #".*/(python[^/]*|zoop-ai-[^/]*)$"))']


class ServingJar(activation.FixtureJar):
    def argv(self, *extra):
        return sandbox(self.world.world.root, self.world.artifacts) + super().argv(*extra)


class Delivery:
    def __init__(self, smoke, root, registry, evidence, retained):
        self.smoke, self.root, self.registry, self.evidence, self.retained = smoke, root, registry, evidence, retained
        self.count, self.processes = 0, []

    def start(self, label, command, *, request=None, version=None, digest=None, root=None, destination=DESTINATION, extra=None):
        self.count += 1
        result = self.smoke.layout.requests / f"delivery-{self.count:03d}-{label}.json"
        env = self.smoke.jar.base_env()
        if command in ("seal", "seal-publication"):
            request_path = result.with_suffix(".request.json")
            request_path.write_bytes(handoff.hs.json_bytes(request))
            if command == "seal":
                env = self.smoke.graph_env(request_path, result)
            else:
                env.update({"ZOOP_GRAPH_HANDOFF_IMPORT_ENABLED": "false", "ZOOP_AI_HANDOFF_READ_CLIENT_ENABLED": "false",
                            "ZOOP_GRAPH_DELIVERY_SEAL_REQUEST": str(request_path),
                            "ZOOP_GRAPH_DELIVERY_SEAL_ARTIFACT_ROOT": str(self.smoke.layout.artifacts),
                            "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(self.registry)})
        if command in ("seal", "seal-publication", "status"):
            env.update({"ZOOP_GRAPH_DELIVERY_SEAL_ENABLED": "true", "ZOOP_GRAPH_DELIVERY_SEAL_COMMAND": command,
                        "ZOOP_GRAPH_DELIVERY_SEAL_DESTINATION_ID": destination, "ZOOP_GRAPH_DELIVERY_SEAL_RESULT": str(result)})
        else:
            env.update({"ZOOP_GRAPH_DELIVERY_INSTALL_ENABLED": "true", "ZOOP_GRAPH_DELIVERY_INSTALL_DESTINATION_ID": destination,
                        "ZOOP_GRAPH_DELIVERY_INSTALL_VERSION_ID": version, "ZOOP_GRAPH_DELIVERY_INSTALL_EXPECTED_PACKAGE_DIGEST": digest,
                        "ZOOP_GRAPH_DELIVERY_INSTALL_ARTIFACT_ROOT": str(root or self.root),
                        "ZOOP_GRAPH_DELIVERY_INSTALL_RESULT": str(result), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(self.registry)})
        env.update({"ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED": "false", **(extra or {})})
        argv = self.smoke.jar.argv("--spring.main.web-application-type=none", "--spring.flyway.enabled=false",
                                  "--spring.jpa.hibernate.ddl-auto=validate", "--spring.sql.init.mode=never")
        if command == "install":
            argv = sandbox(self.smoke.world.root, self.smoke.layout.artifacts) + argv
        with result.with_suffix(".log").open("xb") as output:
            process = subprocess.Popen(argv, env=env, stdout=output, stderr=subprocess.STDOUT)
        self.processes.append(process)
        return process, result, label

    def finish(self, run, *, unknown_allowed=False):
        process, path, label = run
        try:
            code = process.wait(timeout=420)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=30)
            raise AssertionError(label + ": operator JVM did not exit")
        value = None
        if path.exists():
            check(stat.S_IMODE(path.stat().st_mode) == 0o600, label + ": result permissions")
            raw = path.read_bytes()
            (self.retained / path.name).write_bytes(raw)
            if raw:
                value = json.loads(raw)
                for private in (str(self.smoke.layout.work), str(self.smoke.world.root), *handoff.hs.PRIVATE):
                    check(private.encode() not in raw, label + ": result leaked private data")
        log = path.with_suffix(".log")
        (self.retained / log.name).write_text(log.read_text(errors="replace").replace(self.smoke.db.password, "[redacted]"))
        check(value is not None or unknown_allowed, label + ": missing/empty result is UNKNOWN")
        entry = {"step": label, "exitCode": code, "status": "observed", "resultPresent": value is not None}
        if value:
            entry.update({"outcome": value.get("outcome"), "failure": (value.get("failure") or {}).get("code"), "outcomeKnown": value.get("outcomeKnown")})
        self.evidence["steps"].append(entry)
        return code, value

    def succeeded(self, label, command, outcome, **kwargs):
        code, result = self.finish(self.start(label, command, **kwargs))
        check(code == 0 and result["status"] == "succeeded" and result["outcome"] == outcome, label + ": unexpected outcome")
        self.evidence["steps"][-1]["status"] = "passed"
        return result

    def refused(self, label, code, *, root=None, command="install", **kwargs):
        root = root or self.root
        before_files, before_db = files(root), delivery_state(self.smoke.db)
        exit_code, result = self.finish(self.start(label, command, root=root, **kwargs))
        check(exit_code != 0 and result["status"] == "failed" and result["failure"]["code"] == code, label + ": wrong refusal")
        check(files(root) == before_files and delivery_state(self.smoke.db) == before_db, label + ": refusal mutated delivery content")
        self.evidence["steps"][-1].update({"status": "passed", "contentUnchanged": True})


def scenario(args, db, scratch, evidence, layouts, runs):
    hs, base = handoff.hs, handoff.base
    evidence["phase"] = "synthetic-native-eight"
    world = hs.build_world(scratch / "world")
    decisions = hs.decisions_doc(world)
    for company in decisions["companies"]:
        company["publicId"] = handoff.PUBLIC_IDS[company["publicId"]]
    hs.write_operator(world, decisions=decisions)
    operator = hs.Operator(world)
    requests = {}
    for name in ("delivery-main", "delivery-unpackaged"):
        manifest = hs.manifest_doc(world, name, hs.file_hashes(world.root))
        check(operator.cli("freeze", manifest)["state"] == "ready", "producer freeze failed")
        exported = operator.cli("export", operator.sel(name))
        check(exported["bundle"]["schemaVersion"] == "zoop-graph-handoff-bundle-8", "current native bundle required")
        requests[name] = handoff.Smoke.request(name, hs.digest(manifest), handoff.sha256(hs.canonical(exported["bundle"]).encode()))
    layout = handoff.Layout(world, args.ingest_cli)
    layouts.append(layout.work)
    smoke = handoff.Smoke(args, db, layout)
    smoke.jar = activation.FixtureJar(args.java, args.jar, db, layout)
    ledgers_before = {name: handoff.fingerprint(path) for name, path in layout.ledgers.items()}
    status, result, _ = smoke.jar.run("delivery-documents", [base.item(ref) for ref in world.refs.values()], artifact_root=layout.artifacts)
    check(status == 0 and result["status"] == "succeeded", "native document import failed")
    db.run("INSERT INTO companies (id, name, name_key, search_text) VALUES "
           + ", ".join(f"({literal(cid)}, {literal(name)}, '', '')" for cid, name in handoff.COMPANIES))
    with activation.Web(smoke.jar, {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture", "ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED": "false"},
                        ready="Graph fixture fixture-2026-10-08 "):
        pass
    active_before = db.scalar("SELECT id FROM graph_versions WHERE active")
    activations_before = db.scalar("SELECT count(*) FROM graph_activations")
    db.run("UPDATE publication_rules SET enabled=true, revision=revision+1 WHERE id='single-source@1'")
    serving = scratch / "serving"
    serving.mkdir(mode=0o700)
    authority = scratch / "serving-sources.json"
    authority.write_bytes(layout.registry_path.read_bytes())
    delivery = Delivery(smoke, serving, authority, evidence, args.retained)
    runs.append(delivery)
    request, vid = requests["delivery-main"], handoff.version_id("delivery-main")
    evidence["phase"] = "seal-full-composition"
    sealed = delivery.succeeded("seal-full-filtered-closure", "seal", "sealed", request=request)
    digest = sealed["packageDigest"]
    install_args = {"version": vid, "digest": digest}
    package = db.rows(f"SELECT manifest FROM graph_delivery_packages WHERE version_id={literal(vid)}")[0]["manifest"]
    manifest = json.loads(package)
    pins = manifest["files"]
    check(manifest["schemaVersion"] == "zoop-graph-delivery-package-2", "package schema")
    read_pin = lambda pin: (layout.artifacts / pin["storageUri"].split(":", 1)[1]).read_bytes()
    receipt = json.loads(read_pin(next(pin for pin in pins if pin["kind"] == "verification_receipt")))
    snapshot = json.loads(read_pin(next(pin for pin in pins if pin["kind"] == "graph_snapshot")))
    projection = next(pin for pin in pins if pin["kind"] == "graph_bundle_snapshot")
    check(projection["storageUri"].startswith("artifact-root:graph_bundle/"), "projection directory")
    check(read_pin(projection) != read_pin(next(pin for pin in pins if pin["kind"] == "graph_snapshot")), "projection must differ")
    hidden = {article["articleId"] for article in receipt["bundle"]["articles"]} - {article["articleId"] for article in snapshot["articles"]}
    check(hidden, "publication rule must hide an article")
    text_ids = {pin["artifactId"] for pin in pins if pin["kind"] == "extracted_text"}
    expected_texts = {db.scalar("SELECT text_artifact_id FROM article_versions WHERE article_id=" + literal(article["articleId"])
                               + " AND version=" + literal(article["articleVersion"])) for article in receipt["bundle"]["articles"]}
    check(text_ids == expected_texts, "full receipt text closure")
    source = db.rows(f"SELECT ordinal,handoff_id,receipt_artifact_id,bundle_snapshot_artifact_id FROM graph_version_sources WHERE graph_version_id={literal(vid)}")
    check(len(source) == 1 and source[0]["ordinal"] == 0 and source[0]["bundle_snapshot_artifact_id"] == projection["artifactId"], "composition source closure")
    evidence["closure"] = {"fileCount": len(pins), "textCount": len(text_ids), "filteredArticleCount": len(hidden), "separateRuleFreeProjection": True}
    unchanged = delivery_state(db), files(layout.artifacts)
    # A sealed receipt still reconciles after current producer authority is revoked.
    original = layout.registry_path.read_bytes()
    revoked = json.loads(original)
    revoked["sources"][0]["grant"]["enabled"] = False
    layout.registry_path.write_bytes(hs.json_bytes(revoked))
    try:
        delivery.succeeded("already-sealed-is-not-fresh-admission", "seal", "already_sealed", request=request)
        report = delivery.succeeded("status-with-withdrawn-origin-authority", "status", "status")
        check(set(report["packages"][0]) == {"versionId", "sealed", "packageDigest", "installed", "active", "wasActive"}, "status freshness claim")
    finally:
        layout.registry_path.write_bytes(original)
    check((delivery_state(db), files(layout.artifacts)) == unchanged, "read-only reconciliation mutated state")
    rc, imported, _ = smoke.graph_import("ordinary", requests["delivery-unpackaged"])
    check(rc == 0 and imported["outcome"] == "staged", "ordinary CLI import compatibility")

    evidence["phase"] = "independent-preflight-refusals"
    delivery.refused("wrong-package-digest", "package_conflict", version=vid, digest="0" * 64)
    for key in ("expectedManifestDigest", "expectedBundleDigest"):
        delivery.refused("wrong-" + key, "package_conflict", command="seal", root=layout.artifacts, request={**request, key: "0" * 64})
    delivery.refused("missing-package", "package_missing", version=handoff.version_id("missing"), digest=digest)
    delivery.refused("missing-registry", "source_authority_unavailable", extra={"ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(scratch / "absent.json")}, **install_args)
    original = authority.read_bytes()
    revoked = json.loads(original)
    revoked["sources"][0]["grant"]["enabled"] = False
    authority.write_bytes(hs.json_bytes(revoked))
    try:
        delivery.refused("current-rights-revoked", "rights_denied", **install_args)
    finally:
        authority.write_bytes(original)
    hidden_id = literal(sorted(hidden)[0])
    db.run(f"UPDATE articles SET access_status='private' WHERE id={hidden_id}")
    try:
        delivery.refused("filtered-article-unavailable", "rights_denied", **install_args)
    finally:
        db.run(f"UPDATE articles SET access_status='available' WHERE id={hidden_id}")
    for label, prop, code in (("install-file-bound", "ZOOP_GRAPH_DELIVERY_INSTALL_MAX_FILES", "package_too_large"),
                              ("install-byte-bound", "ZOOP_GRAPH_DELIVERY_INSTALL_MAX_PACKAGE_BYTES", "package_too_large")):
        delivery.refused(label, code, extra={prop: "2"}, **install_args)
    for label, prop, code in (("seal-byte-bound", "ZOOP_GRAPH_DELIVERY_SEAL_MAX_PACKAGE_BYTES", "package_too_large"),
                              ("seal-pending-bound", "ZOOP_GRAPH_DELIVERY_SEAL_MAX_PENDING_BYTES", "outbox_full")):
        delivery.refused(label, code, command="seal", root=layout.artifacts, request=request, destination=label, extra={prop: "1"})
    text_pin = next(pin for pin in pins if pin["kind"] == "extracted_text")
    text_id = literal(text_pin["artifactId"])
    first_byte = db.scalar(f"SELECT get_byte(content,0) FROM graph_delivery_contents WHERE artifact_id={text_id}")
    db.run(f"SET session_replication_role=replica; UPDATE graph_delivery_contents SET content=set_byte(content,0,{first_byte ^ 1}) WHERE artifact_id={text_id}")
    try:
        delivery.refused("corrupt-content", "package_invalid", **install_args)
    finally:
        db.run(f"SET session_replication_role=replica; UPDATE graph_delivery_contents SET content=set_byte(content,0,{first_byte}) WHERE artifact_id={text_id}")
    db.run(f"SET session_replication_role=replica; UPDATE artifacts SET sha256={'0' * 64!r} WHERE id={text_id}")
    try:
        delivery.refused("artifact-db-pin-mismatch", "package_invalid", **install_args)
    finally:
        db.run(f"SET session_replication_role=replica; UPDATE artifacts SET sha256={literal(text_pin['sha256'])} WHERE id={text_id}")
    # Re-pin deliberately altered packages to distinguish closure validation from the caller's digest check.
    for label, kind in (("omitted-projection", "graph_bundle_snapshot"), ("omitted-full-receipt-text", "extracted_text")):
        changed = {**manifest, "files": [pin for pin in pins if pin["kind"] != kind]}
        body = hs.canonical(changed)
        changed_digest = handoff.sha256(body.encode())
        db.run(f"SET session_replication_role=replica; UPDATE graph_delivery_packages SET manifest={literal(body)},package_digest={literal(changed_digest)},"
               f"file_count={len(changed['files'])},total_bytes={sum(p['bytes'] for p in changed['files'])} WHERE version_id={literal(vid)}")
        try:
            delivery.refused(label, "package_invalid", version=vid, digest=changed_digest)
        finally:
            db.run(f"SET session_replication_role=replica; UPDATE graph_delivery_packages SET manifest={literal(package)},package_digest={literal(digest)},"
                   f"file_count={len(pins)},total_bytes={sum(p['bytes'] for p in pins)} WHERE version_id={literal(vid)}")
    conflict_root = scratch / "conflict-root"
    conflict_root.mkdir(mode=0o700)
    conflict = conflict_root / pins[-1]["storageUri"].split(":", 1)[1]
    conflict.parent.mkdir(mode=0o700)
    conflict.write_bytes(b"different existing target")
    conflict.chmod(0o600)
    delivery.refused("last-target-conflict", "target_conflict", root=conflict_root, **install_args)
    migration = "20261031160000"
    checksum = db.scalar(f"SELECT checksum FROM flyway_schema_history WHERE version={literal(migration)}")
    db.run(f"UPDATE flyway_schema_history SET checksum={checksum + 1} WHERE version={literal(migration)}")
    try:
        delivery.refused("schema-checksum-mismatch", "schema_mismatch", **install_args)
    finally:
        db.run(f"UPDATE flyway_schema_history SET checksum={checksum} WHERE version={literal(migration)}")
    for target, command, expected, arguments in ((layout.artifacts, "seal", "import_busy", {"request": request, "destination": "busy-origin"}),
                                                (serving, "install", "install_busy", install_args)):
        descriptor = os.open(target / ".document-import.lock", os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            delivery.refused("busy-" + command, expected, root=target, command=command, **arguments)
        finally:
            os.close(descriptor)

    evidence["phase"] = "interrupted-install-and-same-pin-recovery"
    db.run("CREATE FUNCTION smoke_ack_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(120); RETURN NEW; END $$; "
           "CREATE TRIGGER smoke_ack_barrier BEFORE INSERT ON graph_delivery_installs FOR EACH ROW EXECUTE FUNCTION smoke_ack_barrier()")
    interrupted = delivery.start("interrupted-install", "install", **install_args)
    wait_until(lambda: db.scalar("SELECT count(*) FROM pg_stat_activity WHERE wait_event='PgSleep' AND query LIKE 'INSERT INTO graph_delivery_installs%'") == 1,
               "installer did not reach acknowledgement after durable files")
    interrupted[0].kill()
    delivery.finish(interrupted, unknown_allowed=True)
    db.run("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE wait_event='PgSleep' AND query LIKE 'INSERT INTO graph_delivery_installs%'")
    db.run("DROP TRIGGER smoke_ack_barrier ON graph_delivery_installs; DROP FUNCTION smoke_ack_barrier()")
    check(db.scalar("SELECT count(*) FROM graph_delivery_installs") == 0 and db.scalar("SELECT count(*) FROM graph_delivery_destinations") == 0, "interrupted acknowledgement committed")
    for pin in pins:
        check(handoff.sha256((serving / pin["storageUri"].split(":", 1)[1]).read_bytes()) == pin["sha256"], "interruption did not leave verified durable file")
    before = files(serving)
    # Hold acknowledgement long enough that the second real JVM must meet the first root lock.
    db.run("CREATE FUNCTION smoke_ack_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(15); RETURN NEW; END $$; "
           "CREATE TRIGGER smoke_ack_barrier BEFORE INSERT ON graph_delivery_installs FOR EACH ROW EXECUTE FUNCTION smoke_ack_barrier()")
    left = delivery.start("same-pin-recovery", "install", **install_args)
    wait_until(lambda: db.scalar("SELECT count(*) FROM pg_stat_activity WHERE wait_event='PgSleep' AND query LIKE 'INSERT INTO graph_delivery_installs%'") == 1, "recovery ack barrier")
    delivery.refused("competing-install-busy", "install_busy", **install_args)
    code, recovered = delivery.finish(left)
    check(code == 0 and recovered["outcome"] == "installed", "same-pin recovery failed")
    evidence["steps"][-1]["status"] = "passed"
    db.run("DROP TRIGGER smoke_ack_barrier ON graph_delivery_installs; DROP FUNCTION smoke_ack_barrier()")
    check(files(serving) == before and db.scalar("SELECT count(*) FROM graph_delivery_installs") == 1, "recovery changed bytes or duplicated ack")
    immutable = files(serving), delivery_state(db)
    delivery.succeeded("installed-readonly-replay", "install", "already_installed", **install_args)
    check((files(serving), delivery_state(db)) == immutable, "installed replay mutated durable state")
    other = scratch / "wrong-root"
    other.mkdir(mode=0o700)
    delivery.refused("registered-destination-wrong-root", "destination_root_mismatch", root=other, **install_args)
    missing = serving / text_pin["storageUri"].split(":", 1)[1]
    retained_text = missing.read_bytes()
    missing.unlink()
    try:
        delivery.refused("installed-missing-text-refuses-repair", "target_conflict", **install_args)
    finally:
        missing.write_bytes(retained_text)
        missing.chmod(0o600)
    check(db.scalar("SELECT id FROM graph_versions WHERE active") == active_before
          and db.scalar("SELECT count(*) FROM graph_activations") == activations_before, "delivery autoactivated")
    for pin in pins:
        path = serving / pin["storageUri"].split(":", 1)[1]
        check(stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700, "exact install modes")
        check(path.stat().st_uid == serving.stat().st_uid, "install owner")

    evidence["phase"] = "java-only-public-http"
    auth = activation.bootstrap_session(db)
    key = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    web_env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(serving),
               "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(serving), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(authority),
               "ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED": "false", "SPRING_PROFILES_ACTIVE": "local",
               "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "activation-test", "ZOOP_AUTH_CSRF_KEYS": "activation-test=" + key,
               "ZOOP_AUTH_ALLOWED_ORIGINS": activation.ORIGIN, "ZOOP_API_CORS_ALLOWED_ORIGINS": activation.ORIGIN}
    serving_jar = ServingJar(args.java, args.jar, db, layout)
    def expect(web, label, path, status, **kwargs):
        code, raw, _ = web.request(path, **kwargs)
        evidence["steps"].append({"step": label, "statusCode": code, "status": "passed" if code == status else "failed"})
        check(code == status, label + ": unexpected HTTP status")
        return json.loads(raw)
    with activation.Web(serving_jar, web_env) as web:
        session = expect(web, "admin-session", "/api/v1/admin/auth/session", 200, headers=auth)
        headers = {**auth, "Origin": activation.ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrfToken"], "Idempotency-Key": "native-delivery-activation"}
        before = activation.publication_state(db)
        response = expect(web, "explicit-admin-activation", f"/api/v1/admin/graph/versions/{vid}/activate", 200,
                          payload={"reason": "Synthetic native delivery", "expectedActiveVersionId": active_before}, headers=headers)
        check(response["activeVersionId"] == vid, "explicit active pointer")
        issue = "issue:supply-2026q3"
        graph = expect(web, "installed-public-graph", "/api/v1/graph?graphVersion=" + vid, 200)
        check(issue in {node["id"] for node in graph["nodes"]}, "installed graph missing supply issue")
        eid = hs.evidence_id(world, "a", hs.EVT_A)
        quote = expect(web, "installed-exact-evidence", f"/api/v1/evidence/{eid}?graphVersion={vid}", 200)
        check(quote["quote"] == hs.EVT_A and quote["quoteVerified"] is True, "exact installed quote")
        expect(web, "installed-public-event", "/api/v1/events/" + urllib.parse.quote(issue, safe="") + "?graphVersion=" + vid, 200)
        check(len(activation.publication_state(db)["activations"]) == len(before["activations"]) + 1, "manual activation count")
    status = delivery.succeeded("status-after-manual-activation", "status", "status")
    check(status["packages"][0]["installed"] and status["packages"][0]["active"] and status["packages"][0]["wasActive"], "recorded final status")
    check({name: handoff.fingerprint(path) for name, path in layout.ledgers.items()} == ledgers_before, "source ledgers changed")
    evidence.update({"ledgerReadOnly": True, "deliveryActivationWrites": 0, "adminHttpActivations": 1,
                     "independentRootsAndRegistry": True, "installerAndWebSandboxDeniedSourceReads": True,
                     "installerAndWebPythonExecDenied": True, "readonlyReplay": True, "samePinInterruptedInstallRecovery": True,
                     "oneInstalledOneBusy": True, "ordinaryCliImportCompatible": True})


def context_scenario(args, db, scratch, evidence, layouts, runs):
    hs, base = handoff.hs, handoff.base
    world = hs.build_context_world(scratch / "world", count=20)
    decisions = json.loads((world.root / "decisions.json").read_bytes())
    decisions["companies"][0]["publicId"] = handoff.PUBLIC_IDS["KRX:005930"]
    (world.root / "decisions.json").write_bytes(hs.json_bytes(decisions))
    operator = hs.Operator(world)
    manifest = hs.manifest_doc(world, "multicontext-delivery", hs.file_hashes(world.root))
    check(operator.cli("freeze", manifest)["state"] == "ready", "twenty native jobs did not freeze")
    exported = operator.cli("export", operator.sel(manifest["handoffId"]))
    bundle = exported["bundle"]
    check(len(bundle["sources"]) == 20 and {issue["id"] for issue in bundle["issues"]} == {"issue:context-0", "issue:context-1"},
          "selected native composition differs")
    over = json.loads(json.dumps(manifest))
    over["handoffId"] = "twenty-one-refused"
    over["sources"].append({**over["sources"][0], "relation": {**over["sources"][0]["relation"], "jobId": "twenty-first"}})
    check(operator.cli("freeze", over, expected=2)["error"]["code"] == "input_or_configuration_invalid", "producer twenty-one admission")
    request = handoff.Smoke.request(manifest["handoffId"], hs.digest(manifest), handoff.sha256(hs.canonical(bundle).encode()))
    layout = handoff.Layout(world, args.ingest_cli)
    layouts.append(layout.work)
    smoke = handoff.Smoke(args, db, layout)
    smoke.jar = activation.FixtureJar(args.java, args.jar, db, layout)
    before = {name: handoff.fingerprint(path) for name, path in layout.ledgers.items()}
    for i, context in enumerate(world.native_contexts):
        layout.state, layout.registry_path = context.paths.ingestion, context.paths.sources
        status, result, _ = smoke.jar.run(f"context-documents-{i}", [base.item(ref) for ref in context.refs], artifact_root=layout.artifacts)
        check(status == 0 and result["status"] == "succeeded", "context document import failed")
    db.run("INSERT INTO companies (id, name, name_key, search_text) VALUES "
           + ", ".join(f"({literal(cid)}, {literal(name)}, '', '')" for cid, name in handoff.COMPANIES))
    with activation.Web(smoke.jar, {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture", "ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED": "false"},
                        ready="Graph fixture fixture-2026-10-08 "):
        pass
    active = db.scalar("SELECT id FROM graph_versions WHERE active")
    serving = scratch / "serving"
    serving.mkdir(mode=0o700)
    authority = scratch / "serving-authorities.json"
    leaves, routes = [], []
    for i, context in enumerate(world.native_contexts):
        leaf = scratch / f"serving-source-{i}.json"
        leaf.write_bytes(context.paths.sources.read_bytes())
        leaves.append(leaf)
        grant = json.loads(leaf.read_bytes())["sources"][0]["grant"]
        routes.append({"sourceId": grant["sourceId"], "grantId": grant["grantId"], "revision": grant["revision"], "sources": str(leaf)})
    authority.write_bytes(hs.json_bytes({"schemaVersion": "zoop-source-authority-set-1", "authorities": routes}))
    delivery = Delivery(smoke, serving, authority, evidence, args.retained)
    runs.append(delivery)

    def exposure(changed):
        program = hs.GUARD + "runpy.run_module('zoop_ai_pipeline.handoff_exposure_cli', run_name='__main__')"
        env = {"PATH": os.defpath, "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1", **hs.ownership_env()}
        child = subprocess.run([sys.executable, "-c", program, "--state-dir", str(world.root / "handoff"),
                                "--source-contexts", str(world.context_file), "--source-contexts-sha256", world.context_sha],
                               input=hs.json_bytes({"schemaVersion": "zoop-handoff-exposure-1", "handoffIds": [manifest["handoffId"]], "changed": changed}),
                               capture_output=True, env=env, timeout=120)
        check(child.returncode == 0, "context exposure failed")
        return json.loads(child.stdout)

    source_report = exposure({"kind": "source", "sourceId": "synthetic-source"})
    check({issue["id"] for issue in source_report["handoffs"][0]["issues"]} == {"issue:context-0", "issue:context-1"}, "source exposure incomplete")
    for i, context in enumerate(world.native_contexts):
        raw = context.paths.sources.read_bytes()
        revoked = json.loads(raw)
        revoked["sources"][0]["grant"]["enabled"] = False
        context.paths.sources.write_bytes(hs.json_bytes(revoked))
        try:
            check(operator.cli("export", operator.sel(manifest["handoffId"]), expected=2)["delivery"]["status"] == "withheld", "revoked context exported")
            code, refused, _ = smoke.graph_import(f"revoked-context-{i}", request)
            check(code != 0 and refused["status"] == "failed", "Java admitted revoked context")
            check(exposure({"kind": "source", "sourceId": "synthetic-source"}) == source_report, "revocation changed exposure")
            scoped = exposure({"kind": "grant", "grantId": routes[i]["grantId"], "revision": routes[i]["revision"]})
            check({issue["id"] for issue in scoped["handoffs"][0]["issues"]} == {f"issue:context-{i}"}, "grant exposure crossed contexts")
        finally:
            context.paths.sources.write_bytes(raw)
    sealed = delivery.succeeded("twenty-native-contexts-sealed", "seal", "sealed", request=request)
    vid = handoff.version_id(manifest["handoffId"])
    install = {"version": vid, "digest": sealed["packageDigest"]}
    for i, leaf in enumerate(leaves):
        raw = leaf.read_bytes()
        revoked = json.loads(raw)
        revoked["sources"][0]["grant"]["enabled"] = False
        leaf.write_bytes(hs.json_bytes(revoked))
        try:
            delivery.refused(f"context-{i}-revoked-after-seal", "rights_denied", **install)
        finally:
            leaf.write_bytes(raw)
    delivery.succeeded("java-only-context-install", "install", "installed", **install)
    auth = activation.bootstrap_session(db)
    key = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    web_env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(serving),
               "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(serving), "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(authority),
               "ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED": "false", "SPRING_PROFILES_ACTIVE": "local",
               "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "activation-test", "ZOOP_AUTH_CSRF_KEYS": "activation-test=" + key,
               "ZOOP_AUTH_ALLOWED_ORIGINS": activation.ORIGIN, "ZOOP_API_CORS_ALLOWED_ORIGINS": activation.ORIGIN}
    def expect(web, label, path, status, **kwargs):
        code, raw, _ = web.request(path, **kwargs)
        evidence["steps"].append({"step": label, "statusCode": code, "status": "passed" if code == status else "failed"})
        check(code == status, label + ": unexpected HTTP status")
        return json.loads(raw)
    with activation.Web(ServingJar(args.java, args.jar, db, layout), web_env) as web:
        session = expect(web, "context-admin-session", "/api/v1/admin/auth/session", 200, headers=auth)
        headers = {**auth, "Origin": activation.ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrfToken"]}
        for i, leaf in enumerate(leaves):
            raw = leaf.read_bytes()
            revoked = json.loads(raw)
            revoked["sources"][0]["grant"]["enabled"] = False
            leaf.write_bytes(hs.json_bytes(revoked))
            try:
                expect(web, f"context-{i}-activation-revoked", f"/api/v1/admin/graph/versions/{vid}/activate", 409,
                       payload={"reason": "Synthetic context revocation", "expectedActiveVersionId": active},
                       headers={**headers, "Idempotency-Key": f"context-revoked-{i}"})
            finally:
                leaf.write_bytes(raw)
        expect(web, "context-manual-activation", f"/api/v1/admin/graph/versions/{vid}/activate", 200,
               payload={"reason": "Synthetic native contexts", "expectedActiveVersionId": active},
               headers={**headers, "Idempotency-Key": "context-activate"})
        graph = expect(web, "context-public-graph", "/api/v1/graph?graphVersion=" + vid, 200)
        check({"issue:context-0", "issue:context-1"} <= {node["id"] for node in graph["nodes"]}, "public context issue loss")
        cited = {}
        for i in range(2):
            document = world.native_contexts[i].refs[0]["documentId"]
            cited[i] = next(item["id"] for item in bundle["evidence"] if item["articleId"] == document)
            quote = expect(web, f"context-{i}-exact-evidence", f"/api/v1/evidence/{cited[i]}?graphVersion={vid}", 200)
            check(quote["quoteVerified"] is True, "fresh Java evidence was not exact")
        for i, leaf in enumerate(leaves):
            raw = leaf.read_bytes()
            revoked = json.loads(raw)
            revoked["sources"][0]["grant"]["enabled"] = False
            leaf.write_bytes(hs.json_bytes(revoked))
            try:
                expect(web, f"context-{i}-evidence-revoked", f"/api/v1/evidence/{cited[i]}?graphVersion={vid}", 404)
                expect(web, f"context-{1-i}-evidence-still-current", f"/api/v1/evidence/{cited[1-i]}?graphVersion={vid}", 200)
            finally:
                leaf.write_bytes(raw)
    check({name: handoff.fingerprint(path) for name, path in layout.ledgers.items()} == before, "native or monetary ledger changed during consumption")
    check(len({binding["live"]["runtime"]["identity"] for binding in world.runtime_bindings}) == 2, "runtime identities were replaced")
    evidence.update({"selectedSourceJobs": 20, "operatingContexts": 2, "runtimeIdentities": 2, "ledgerReadOnly": True,
                     "syntheticLoopbackRequests": world.fixture_requests, "externalProviderCalls": 0,
                     "sourceExposureBothContexts": True, "grantExposureScoped": True, "revocationBothDirections": True,
                     "installerAndWebSandboxDeniedSourceReads": True, "installerAndWebPythonExecDenied": True})



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, default=local.DEFAULT_JAR)
    parser.add_argument("--java")
    parser.add_argument("--handoff-cli", type=Path, default=REPO / "ai/pipeline/.venv/bin/zoop-ai-handoff")
    parser.add_argument("--ingest-cli", type=Path, default=REPO / "ai/pipeline/.venv/bin/zoop-ai-ingest")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--multicontext", action="store_true", help="two independent loopback operations, twenty native jobs, routed Java delivery")
    args = parser.parse_args()
    args.jar, args.result = args.jar.resolve(), args.result.resolve()
    args.handoff_cli, args.ingest_cli = args.handoff_cli.resolve(), args.ingest_cli.resolve()
    args.retained = args.result.with_suffix(".artifacts")
    if args.result.exists() or args.retained.exists():
        parser.error("result and artifact paths must be new")
    os.environ.clear()
    os.environ.update({**START_ENV, "PYTHONDONTWRITEBYTECODE": "1"})
    args.java = local.find_java(args.java)
    scratch = Path(tempfile.mkdtemp(prefix="zoop-native-delivery-smoke-")).resolve()
    original_cwd = Path.cwd()
    layouts, runs = [], []
    owned = "zoop-native-delivery-" + secrets.token_hex(8)
    container_created = network_created = False
    evidence = {"status": "failed", "steps": [], "providerCalls": 0, "modelCalls": 0, "provenance": "synthetic",
                "notProven": ["actual native reader window", "cloud database route/TLS/roles", "EFS owner/lock/fsync semantics", "published image identity"],
                "cleanup": {"container": False, "network": False, "processes": False, "temporaryState": False}}
    def stop(signum, frame):
        raise InterruptedError("smoke interrupted")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    result_file = None
    try:
        result_file = args.result.open("x")
        args.retained.mkdir(mode=0o700)
        evidence["phase"] = "preflight"
        check(args.jar.is_file(), "existing boot jar required")
        check(Path("/usr/bin/sandbox-exec").is_file(), "macOS sandbox-exec required for installer isolation proof")
        for cli in (args.handoff_cli, args.ingest_cli):
            check(cli.is_file() and os.access(cli, os.X_OK), "cached installed producer CLI required")
        evidence["jarSha256"] = handoff.sha256(args.jar.read_bytes())
        context = local.docker("context", "show")
        check(context.returncode == 0 and context.stdout.strip() == "orbstack", "expected local orbstack context")
        endpoint = local.docker("context", "inspect", "orbstack", "--format", "{{.Endpoints.docker.Host}}")
        check(endpoint.returncode == 0 and endpoint.stdout.strip().startswith("unix://"), "refusing remote Docker endpoint")
        local.preflight_docker(local.DEFAULT_IMAGE)
        image = local.docker("image", "inspect", local.DEFAULT_IMAGE, "--format", "{{.Id}}")
        check(image.returncode == 0, "cached PostgreSQL image required")
        evidence["postgresImage"] = {"name": local.DEFAULT_IMAGE, "id": image.stdout.strip()}
        check(local.docker("network", "create", "--label", LABEL + "=1", owned).returncode == 0, "network creation failed")
        network_created = True
        password = secrets.token_urlsafe(32)
        started = local.docker("run", "-d", "--pull", "never", "--name", owned, "--label", LABEL + "=1", "--network", owned,
                               "-e", "POSTGRES_DB=" + local.DB_NAME, "-e", "POSTGRES_USER=" + local.DB_USER, "-e", "POSTGRES_PASSWORD",
                               "-p", "127.0.0.1::5432", local.DEFAULT_IMAGE, env={**os.environ, "POSTGRES_PASSWORD": password})
        check(started.returncode == 0, "owned PostgreSQL start failed")
        container_created = True
        mapping = local.docker("port", owned, "5432/tcp")
        check(mapping.returncode == 0 and mapping.stdout.strip().startswith("127.0.0.1:") and "\n" not in mapping.stdout.strip(), "loopback PostgreSQL port")
        port = int(mapping.stdout.strip().rsplit(":", 1)[1])
        local.wait_database(owned, port)
        os.environ.update({"DB_URL": f"jdbc:postgresql://127.0.0.1:{port}/{local.DB_NAME}", "DB_USERNAME": local.DB_USER, "DB_PASSWORD": password})
        db = handoff.base.Database(os.environ["DB_URL"], local.DB_USER, password, local.DB_NAME, owned, None)
        check(not db.tables_exist(), "owned database unexpectedly nonempty")
        os.chdir(scratch)
        (context_scenario if args.multicontext else scenario)(args, db, scratch, evidence, layouts, runs)
        evidence.update({"phase": "complete", "status": "passed"})
    except (Exception, KeyboardInterrupt) as error:
        message = str(error).split("\n", 1)[0][:240].replace(os.environ.get("DB_PASSWORD") or "\0", "[redacted]")
        evidence["failure"] = {"type": type(error).__name__, "phase": evidence.get("phase"), "message": message}
        print("delivery smoke failed: " + type(error).__name__ + ": " + message, file=sys.stderr)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        processes = [process for delivery in runs for process in delivery.processes]
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=30)
        for web in activation.Web.instances:
            if web.process.poll() is None:
                web.__exit__()
        evidence["cleanup"]["processes"] = all(p.poll() is not None for p in processes) and all(w.process.poll() is not None for w in activation.Web.instances)
        if args.retained.exists():
            logs = "\n".join(handoff.base.OUTPUT + ["".join(web.lines) for web in activation.Web.instances])
            (args.retained / "setup-and-web.log").write_text(logs.replace(os.environ.get("DB_PASSWORD") or "\0", "[redacted]"))
        if container_created:
            local.docker("stop", "--time", "10", owned)
            removed = local.docker("rm", "-v", owned)
            evidence["cleanup"]["container"] = removed.returncode == 0 and local.docker("container", "inspect", owned).returncode != 0
        else:
            evidence["cleanup"]["container"] = True
        if network_created:
            removed = local.docker("network", "rm", owned)
            evidence["cleanup"]["network"] = removed.returncode == 0 and local.docker("network", "inspect", owned).returncode != 0
        else:
            evidence["cleanup"]["network"] = True
        os.chdir(original_cwd)
        for path in [*layouts, scratch]:
            shutil.rmtree(path)
        evidence["cleanup"]["temporaryState"] = not any(path.exists() for path in [*layouts, scratch])
        if not all(evidence["cleanup"].values()):
            evidence["status"] = "failed"
        text = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        if result_file:
            with result_file:
                result_file.write(text + "\n")
                result_file.flush()
                os.fsync(result_file.fileno())
        print(text)
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
