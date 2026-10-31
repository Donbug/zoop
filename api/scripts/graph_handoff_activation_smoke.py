#!/usr/bin/env python3
"""Synthetic CLI -> Spring staging -> authenticated admin HTTP activation.

Run with the installed pipeline Python from the repository root:
  ai/pipeline/.venv/bin/python api/scripts/graph_handoff_activation_smoke.py \
    --result /tmp/zoop-graph-activation-result.json

Requires the existing API boot jar, JDK 21+, installed pipeline and cached project
PostgreSQL image. Never builds, installs, pulls, borrows a DB or calls a provider.
Creates only an owned Docker bridge, tmpfs DB, loopback JVMs and temporary
synthetic ledgers. Default activation checks the app-owned exclusion store and
current rights. SQL seeds synthetic auth and catalog ONLY, never activation.
The auth fixture does not prove password login, OAuth or operator provisioning.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import graph_handoff_import_smoke as handoff
import local_graph_dev as local

REPO = Path(__file__).resolve().parents[2]
LABEL = "com.zoop.graph-activation-smoke"
ORIGIN = "http://127.0.0.1:5173"
DISABLED = {key: "false" for key in (
    "ZOOP_AI_CLIENT_ENABLED", "ZOOP_AI_EXTRACTION_CLIENT_ENABLED",
    "ZOOP_AI_RELATION_CLIENT_ENABLED", "ZOOP_AI_CHAT_CLIENT_ENABLED",
    "ZOOP_CHAT_QUESTIONS_ENABLED", "ZOOP_CHAT_EXECUTOR_ENABLED",
    "ZOOP_SWAGGER_ENABLED",
)}


def isolated_environment(source: dict) -> dict:
    """Allowlist, not a credential-name denylist; Spring/DB/provider flags cannot leak in."""
    return {key: source[key] for key in (
        "PATH", "HOME", "LANG", "JAVA_HOME", "DOCKER_CONTEXT",
        "DOCKER_CONFIG", "TMPDIR", "ZOOP_AI_REQUIRE_SAME_OWNER",
    ) if key in source}


class FixtureJar(handoff.base.Jar):
    def base_env(self):
        return {**super().base_env(), **DISABLED, "ZOOP_METRICS_PROVIDER": "off"}


class Web(handoff.WebRun):
    """Keep existing startup/drain conventions, also reap failed startup and killed children."""
    instances = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instances.append(self)

    def __enter__(self):
        try:
            return super().__enter__()
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *exc):
        super().__exit__(*exc)
        self.process.wait(timeout=30)

    def request(self, path, *, payload=None, headers=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=None if payload is None else json.dumps(payload).encode(),
            headers=headers or {}, method="GET" if payload is None else "POST")
        try:
            with self.opener.open(request, timeout=60) as response:
                return response.status, response.read(), response.headers.get("Content-Type")
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers.get("Content-Type")


def publication_state(db):
    """Auth session touches are excluded; publication revisions/history/audit/idempotency are not."""
    return {
        "active": db.scalar("SELECT id FROM graph_versions WHERE active"),
        "versions": db.rows("SELECT id, active, review_revision, published_at FROM graph_versions ORDER BY id"),
        "activations": db.rows("SELECT * FROM graph_activations ORDER BY id"),
        "audit": db.rows("SELECT * FROM audit_logs WHERE action = 'graph.version.activate' ORDER BY id"),
        "idempotency": db.rows("SELECT * FROM idempotency_records WHERE resource_type = 'graph_version' ORDER BY id"),
    }


def bootstrap_session(db):
    """Synthetic rows follow AdminAuthMigrationPostgresTest, never provision real accounts."""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    db.run(f"""INSERT INTO admins
        (id, email, email_key, display_name, password_hash, role, status, created_at)
        VALUES ('synthetic-activation-admin', 'activation@synthetic.invalid', 'activation@synthetic.invalid',
                'Synthetic Activation Admin', '{{argon2id-v1}}synthetic-test-hash', 'admin', 'active', now());
        INSERT INTO admin_sessions
        (id, admin_id, token_hash, csrf_key_id, csrf_version, created_at, last_seen_at,
         idle_expires_at, expires_at, revoked_at)
        VALUES ('synthetic-activation-session', 'synthetic-activation-admin', '{token_hash}',
                'activation-test', 1, now(), now(), now() + interval '30 minutes', now() + interval '8 hours', NULL)""")
    return {"Cookie": "zoop_admin_session=" + token}


def scenario(args, db, scratch, evidence, layouts):
    hs, base, check = handoff.hs, handoff.base, handoff.check
    evidence["phase"] = "synthetic-cli-world"
    if args.unknown_fields:
        from scripts.public_unknown_fields_smoke import build
        world, exported = build(scratch / "world", handoff.PUBLIC_IDS)
        manifest = exported["manifest"]
        hid = exported["handoffId"]
        evidence["fieldRefusals"] = world.unknown_refusals
        evidence["receiptPins"] = {k: exported["receipt"][k] for k in ("manifestDigest", "bundleDigest", "contentDigest")}
    else:
        world = hs.build_world(scratch / "world")
        decisions = hs.decisions_doc(world)
        for company in decisions["companies"]:
            company["publicId"] = handoff.PUBLIC_IDS[company["publicId"]]
        hs.write_operator(world, decisions=decisions)
        operator = hs.Operator(world)
        hid = "handoff-http-activation-1"
        manifest = hs.manifest_doc(world, hid, hs.file_hashes(world.root))
        frozen = operator.cli("freeze", manifest)
        check(frozen["state"] == "ready", "synthetic CLI freeze failed")
        exported = operator.cli("export", operator.sel(hid))
    check(exported["bundle"]["schemaVersion"] == "zoop-graph-handoff-bundle-8", "expected bundle8")
    evidence["steps"].append({"step": "cli-handoff", "status": "passed", "bundle": "zoop-graph-handoff-bundle-8"})
    layout = handoff.Layout(world, args.ingest_cli)
    layouts.append(layout.work)
    smoke = handoff.Smoke(args, db, layout)
    smoke.jar = FixtureJar(args.java, args.jar, db, layout)
    ledgers_before = {name: handoff.fingerprint(path) for name, path in layout.ledgers.items()}
    evidence["phase"] = "spring-document-import"
    status, result, _ = smoke.jar.run("documents", [base.item(ref) for ref in world.refs.values()], artifact_root=layout.artifacts)
    check(status == 0 and result and result["status"] == "succeeded", "document staging failed")
    db.run("INSERT INTO companies (id, name, name_key, search_text) VALUES "
           + ", ".join(f"('{cid}', '{name}', '', '')" for cid, name in handoff.COMPANIES))
    evidence["phase"] = "fixture-pointer-seed"
    with Web(smoke.jar, {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture"}, ready="Graph fixture fixture-2026-10-08 "):
        pass
    before = publication_state(db)
    check(before["active"] == "fixture-2026-10-08", "fixture seeder did not establish active pointer")
    manifest_digest = hs.digest(manifest)
    bundle_digest = handoff.sha256(hs.canonical(exported["bundle"]).encode())
    status, result, _ = smoke.graph_import("http-stage", smoke.request(hid, manifest_digest, bundle_digest))
    vid = handoff.version_id(hid)
    check(status == 0 and result and result["outcome"] == "staged" and result["graphVersionId"] == vid
          and result["activation"] == "not-activated" and result["active"] is False, "handoff staging failed")
    staged = publication_state(db)
    check(staged["active"] == before["active"] and staged["activations"] == before["activations"], "import activated a version")
    check(next(row for row in staged["versions"] if row["id"] == vid)["review_revision"] == 0, "import changed review revision")
    evidence.update({"graphVersion": vid, "importActivationWrites": len(staged["activations"]) - len(before["activations"]),
                     "fixtureSeedActivations": len(before["activations"]), "sqlHarnessActivations": 0})
    evidence["steps"].append({"step": "spring-staging-import", "status": "passed", "outcome": result["outcome"],
                              "activePointerUnchanged": True, "reviewRevision": 0, "activationWrites": 0})
    auth = bootstrap_session(db)
    key = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts),
           "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(layout.artifacts),
           "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(layout.registry_path),
           "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "activation-test", "ZOOP_AUTH_CSRF_KEYS": "activation-test=" + key,
           "SPRING_PROFILES_ACTIVE": "local", "ZOOP_AUTH_ALLOWED_ORIGINS": ORIGIN,
           "ZOOP_API_CORS_ALLOWED_ORIGINS": ORIGIN}
    activation_path = f"/api/v1/admin/graph/versions/{vid}/activate"
    payload = {"reason": "Synthetic local activation check", "expectedActiveVersionId": before["active"]}

    def expect(web, label, path, status, error=None, *, payload=None, headers=None):
        evidence["phase"] = label
        code, raw, content_type = web.request(path, payload=payload, headers=headers)
        entry = {"step": label, "statusCode": code, "status": "failed"}
        evidence["steps"].append(entry)
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            entry.update({"contentType": content_type, "responseBytes": len(raw),
                          "responseSha256": handoff.sha256(raw)})
            raise AssertionError(f"{label}: HTTP {code} returned a non-JSON response")
        observed_error = (body.get("error") or {}).get("code")
        if observed_error:
            entry["errorCode"] = observed_error
        check(code == status and (error is None or observed_error == error),
              f"{label}: expected {status}/{error}, observed {code}/{observed_error}")
        entry["status"] = "passed"
        return body

    def admin_headers(web):
        session = expect(web, "synthetic-admin-session", "/api/v1/admin/auth/session", 200, headers=auth)
        check(session.get("authenticated") is True and session.get("csrfToken"), "synthetic admin session unavailable")
        return {**auth, "Origin": ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrfToken"]}

    def activate(web, headers, label, key, body, status, error=None):
        return expect(web, label, activation_path, status, error, payload=body,
                      headers={**headers, "Idempotency-Key": key})

    registry = layout.registry_path.read_bytes()
    issue = "issue:supply-2026q3"
    eid = hs.evidence_id(world, "a", hs.EVT_A)
    event_path = "/api/v1/events/" + urllib.parse.quote(issue, safe="") + "?" + urllib.parse.urlencode({"graphVersion": vid})
    evidence_path = f"/api/v1/evidence/{eid}?graphVersion={vid}"
    with Web(smoke.jar, env) as web:
        headers = admin_headers(web)
        unchanged = publication_state(db)
        # The app's real exclusion store is present; default activation still rechecks current rights.
        smoke.set_registry(lambda grant: grant.update({"enabled": False}))
        try:
            activate(web, headers, "default-current-rights-refusal", "rights-refusal", payload, 409, "REVISION_CONFLICT")
            check(publication_state(db) == unchanged, "default rights refusal changed publication state/revision")
            evidence["defaultRefusalUnchanged"] = True
            expect(web, "staged-public-graph-refused", f"/api/v1/graph?graphVersion={vid}", 409, "VERSION_UNAVAILABLE")
        finally:
            layout.registry_path.write_bytes(registry)
        activated = activate(web, headers, "default-admin-http-activation", "activate-success", payload, 200)
        check(activated == {"activeVersionId": vid, "previousActiveVersionId": before["active"], "idempotent": False},
              "activation response differs from contract")
        after = publication_state(db)
        check(after["active"] == vid and len(after["activations"]) == len(unchanged["activations"]) + 1,
              "admin HTTP activation did not move pointer once")
        last = after["activations"][-1]
        check(last["actor_kind"] == "admin" and last["pointer_changed"] is True
              and last["admin_id"] == "synthetic-activation-admin", "activation is not attributed to fixture admin")
        check([r["review_revision"] for r in after["versions"]] == [r["review_revision"] for r in unchanged["versions"]],
              "activation unexpectedly changed review revision")
        replay = activate(web, headers, "same-key-replay", "activate-success", payload, 200)
        check(replay == activated and publication_state(db) == after, "same-key replay wrote publication state")
        activate(web, headers, "same-key-different-body", "activate-success", {**payload, "reason": "Different synthetic reason"},
                 409, "IDEMPOTENCY_CONFLICT")
        check(publication_state(db) == after, "idempotency conflict changed publication state")
        activate(web, headers, "stale-active-pointer", "stale-pointer", payload, 409, "REVISION_CONFLICT")
        check(publication_state(db) == after, "stale request changed publication state")
        # A NEW key against the already-active version is a successful audited no-op, not a replay.
        noop = activate(web, headers, "already-active-new-key", "already-active", {**payload, "expectedActiveVersionId": vid}, 200)
        check(noop == {"activeVersionId": vid, "previousActiveVersionId": vid, "idempotent": True}, "new-key no-op contract mismatch")
        public_state = publication_state(db)
        check(public_state["active"] == vid and len(public_state["activations"]) == len(after["activations"]) + 1
              and public_state["activations"][-1]["pointer_changed"] is False, "new-key no-op did not write exactly one unchanged-pointer history row")
        check(public_state["versions"] == after["versions"] and len(public_state["audit"]) == len(after["audit"]) + 1,
              "already-active request changed version/revision or omitted its audit")
        for query in ("", "?graphVersion=" + vid):
            graph = expect(web, "public-graph" + ("-pinned" if query else "-current"), "/api/v1/graph" + query, 200)
            check(graph["metadata"]["graphVersion"] == vid and issue in {n["id"] for n in graph["nodes"]}, "graph version/content mismatch")
        quote = expect(web, "public-evidence-pinned", evidence_path, 200)
        span = hs.span(world, "a", hs.EVT_A)
        check(quote["metadata"]["graphVersion"] == vid and quote["quote"] == hs.EVT_A and quote["quoteVerified"] is True
              and quote["start"] == span["start"] and quote["end"] == span["end"]
              and quote["articleId"] == span["documentId"] and quote["articleVersion"] == span["documentVersion"], "evidence span/version mismatch")
        for label, change in (
            ("disabled", lambda g: g.update({"enabled": False})),
            ("quote-display-revoked", lambda g: g.update({"allowedOperations": [op for op in g["allowedOperations"] if op != "quote-display"]})),
            ("revision-changed", lambda g: g.update({"revision": g["revision"] + "-changed"})),
        ):
            smoke.set_registry(change)
            try:
                expect(web, "current-rights-evidence-" + label, evidence_path, 404, "EVIDENCE_UNAVAILABLE")
            finally:
                layout.registry_path.write_bytes(registry)
            expect(web, "restored-evidence-" + label, evidence_path, 200)
        check(publication_state(db) == public_state, "public reads/current-rights changes wrote publication state")
        evidence.update({"adminHttpActivations": 2, "httpPointerChanges": 1,
                         "currentRights": {"activation": "passed", "evidence": "passed", "event": "unverified"},
                         "publicReads": {"graph": "same-version", "event": "unverified",
                                         "evidence": "same-version-exact-span-current-rights"},
                         "idempotency": "replay-no-write; changed-body-conflict; new-key-active-audited-noop",
                         "stalePointer": "409 REVISION_CONFLICT; unchanged publication state"})
        check({name: handoff.fingerprint(path) for name, path in layout.ledgers.items()} == ledgers_before, "source ledgers changed")
        evidence["ledgerReadOnly"] = True
        # Keep independent proof even when a production event-reader schema gate blocks this last seam.
        # A blocked event is still a failed acceptance criterion and a nonzero exit, never an expected-success fallback.
        try:
            event = expect(web, "public-event-pinned", event_path, 200)
        except AssertionError:
            last_step = evidence["steps"][-1]
            if last_step.get("statusCode") == 503 and last_step.get("errorCode") == "SOURCE_UNAVAILABLE":
                evidence["blockers"] = [{
                    "category": "production-contract",
                    "seam": "GET /api/v1/events/{id} for imported bundle7",
                    "observed": "503 SOURCE_UNAVAILABLE",
                    "source": "api/src/main/java/com/zoop/graph/read/EventDetailService.java",
                    "requiredContract": "supportedBundle must accept exact bundle-5, bundle-6 and bundle-7 receipts",
                    "remaining": "event same-version read and event current-rights revocation/restoration",
                }]
            raise
        check(event["metadata"]["graphVersion"] == vid and event["id"] == issue, "event version/content mismatch")
        if args.unknown_fields:
            check(event["eventTime"] is None and event["timePrecision"] == "unknown", "unresolved headline was exposed")
            check(len(event["mentions"]) == 2 and all(m["eventTime"] is None and m["timePrecision"] == "unknown"
                                                     for m in event["mentions"]), "unresolved mention was exposed")
            check("10.19일" not in json.dumps(event, ensure_ascii=False) and "'25.8월" not in json.dumps(event, ensure_ascii=False),
                  "raw receipt time leaked through public event detail")
            receipt_path = layout.artifacts / "verification_receipt" / f"{vid}.json"
            receipt = json.loads(receipt_path.read_bytes())
            check(receipt["bundle"] == exported["bundle"], "import receipt changed original source values")
            evidence["unknownFields"] = {"sourceCountries": "preserved-empty", "publicCountries": ["KR"],
                                         "rawTimes": ["10.19일", "'25.8월"], "receiptPrecision": "unresolved",
                                         "publicHeadline": [None, "unknown"], "publicMentions": "null/unknown",
                                         "summary": "temporal-review-pending", "structural": "basis_validity_unprovable"}
        for label, change in (
            ("disabled", lambda g: g.update({"enabled": False})),
            ("quote-display-revoked", lambda g: g.update({"allowedOperations": [op for op in g["allowedOperations"] if op != "quote-display"]})),
            ("revision-changed", lambda g: g.update({"revision": g["revision"] + "-changed"})),
        ):
            smoke.set_registry(change)
            try:
                expect(web, "current-rights-event-" + label, event_path, 404)
            finally:
                layout.registry_path.write_bytes(registry)
            expect(web, "restored-event-" + label, event_path, 200)
        check(publication_state(db) == public_state, "event/current-rights reads wrote publication state")
        evidence["currentRights"]["event"] = "passed"
        evidence["publicReads"]["event"] = "same-version-current-rights"
    check({name: handoff.fingerprint(path) for name, path in layout.ledgers.items()} == ledgers_before, "source ledgers changed")
    evidence["ledgerReadOnly"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jar", type=Path, default=local.DEFAULT_JAR)
    parser.add_argument("--java")
    parser.add_argument("--result", type=Path, help="new JSON evidence file; existing files are never overwritten")
    parser.add_argument("--unknown-fields", action="store_true", help="exercise grounded unknown geography and explicitly held raw times")
    args = parser.parse_args()
    args.jar = args.jar.resolve()
    args.result = args.result.resolve() if args.result else None
    if args.result and args.result.exists():
        parser.error("--result already exists; use a new evidence filename")
    args.handoff_cli = REPO / "ai/pipeline/.venv/bin/zoop-ai-handoff"
    args.ingest_cli = REPO / "ai/pipeline/.venv/bin/zoop-ai-ingest"
    os.environ.clear()
    os.environ.update(START_ENV)
    args.java = local.find_java(args.java)
    # No user .env / Spring config or borrowed database can be read from the child cwd.
    scratch = Path(tempfile.mkdtemp(prefix="zoop-http-activation-")).resolve()
    original_cwd = Path.cwd()
    layouts = []
    owned = "zoop-activation-smoke-" + secrets.token_hex(8)
    network_created = container_created = False
    evidence = {"status": "failed", "steps": [], "providerCalls": 0, "modelCalls": 0,
                "exclusionStoreAuthoritative": True, "developmentOptInOnly": False,
                "notProven": ["production publication readiness", "exclusion command mutations", "real-source rights",
                              "password login/OAuth/operator provisioning", "external AI/model path"],
                "cleanup": {"container": False, "network": False, "processes": False, "temporaryState": False}}
    def stop(signum, frame):
        raise InterruptedError("smoke interrupted")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        evidence["phase"] = "preflight"
        handoff.check(args.jar.is_file(), "existing API boot jar required; this smoke does not build")
        for cli in (args.handoff_cli, args.ingest_cli):
            handoff.check(cli.is_file() and os.access(cli, os.X_OK), "installed pipeline CLI required")
        evidence["sourceBaseline"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
        evidence["jarSha256"] = handoff.sha256(args.jar.read_bytes())
        context = local.docker("context", "show")
        handoff.check(context.returncode == 0 and context.stdout.strip() == "orbstack", "expected selected local orbstack Docker context")
        endpoint = local.docker("context", "inspect", "orbstack", "--format", "{{.Endpoints.docker.Host}}")
        handoff.check(endpoint.returncode == 0 and endpoint.stdout.strip().startswith("unix://"),
                      "refusing a non-local Docker endpoint")
        local.preflight_docker(local.DEFAULT_IMAGE)
        image = local.docker("image", "inspect", local.DEFAULT_IMAGE, "--format", "{{.Id}}")
        handoff.check(image.returncode == 0, "cached project image unavailable")
        evidence["postgresImage"] = {"name": local.DEFAULT_IMAGE, "id": image.stdout.strip()}
        created = local.docker("network", "create", "--label", LABEL + "=1", owned)
        handoff.check(created.returncode == 0, "owned bridge network creation failed")
        network_created = True
        password = secrets.token_urlsafe(32)
        started = local.docker("run", "-d", "--pull", "never", "--name", owned, "--label", LABEL + "=1",
                               "--network", owned, "--tmpfs", "/var/lib/postgresql/data",
                               "-e", "POSTGRES_DB=" + local.DB_NAME, "-e", "POSTGRES_USER=" + local.DB_USER,
                               "-e", "POSTGRES_PASSWORD", "-p", "127.0.0.1::5432", local.DEFAULT_IMAGE,
                               env={**os.environ, "POSTGRES_PASSWORD": password})
        handoff.check(started.returncode == 0, "owned tmpfs PostgreSQL container creation failed")
        container_created = True
        ports = local.docker("port", owned, "5432/tcp")
        evidence["phase"] = "owned-db-loopback-port"
        mapping = ports.stdout.strip()
        handoff.check(ports.returncode == 0 and mapping.startswith("127.0.0.1:") and "\n" not in mapping, "DB must expose one loopback port")
        port = int(mapping.rsplit(":", 1)[1])
        local.wait_database(owned, port)
        os.environ.update({"DB_URL": f"jdbc:postgresql://127.0.0.1:{port}/{local.DB_NAME}",
                           "DB_USERNAME": local.DB_USER, "DB_PASSWORD": password})
        db = handoff.base.Database(os.environ["DB_URL"], local.DB_USER, password, local.DB_NAME, owned, None)
        handoff.check(not db.tables_exist(), "owned database is unexpectedly nonempty")
        os.chdir(scratch)
        scenario(args, db, scratch, evidence, layouts)
        evidence["phase"] = "complete"
        evidence["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        # Assertion labels/statuses are safe; do not include process output, SQL, source text or secrets.
        evidence["failure"] = {"type": type(error).__name__, "phase": evidence.get("phase"),
                               "message": "scenario did not complete; see failed/last step"}
        if evidence.get("blockers"):
            evidence["status"] = "blocked"
        print("activation smoke failed: " + type(error).__name__, file=sys.stderr)
        if isinstance(error, AssertionError):
            # Helpers can contain raw process output; retain only our short assertion labels.
            print(str(error).split("\n", 1)[0][:160].replace(os.environ.get("DB_PASSWORD") or "\0", "***"), file=sys.stderr)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        for web in Web.instances:
            if web.process.poll() is None:
                web.__exit__()
        evidence["cleanup"]["processes"] = all(web.process.poll() is not None for web in Web.instances)
        if container_created:
            local.docker("stop", "--time", "20", owned)
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
            shutil.rmtree(path, ignore_errors=True)
        evidence["cleanup"]["temporaryState"] = not any(path.exists() for path in [*layouts, scratch])
        if not all(evidence["cleanup"].values()):
            evidence["status"] = "failed"
        text = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        if args.result:
            with args.result.open("x") as result_file:
                result_file.write(text + "\n")
        print(text)
    return 0 if evidence["status"] == "passed" else 1


START_ENV = isolated_environment(dict(os.environ))

if __name__ == "__main__":
    sys.exit(main())
