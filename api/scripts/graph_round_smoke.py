#!/usr/bin/env python3
"""Synthetic end-to-end round: real AI round service -> Spring round scheduler -> PostgreSQL -> inactive import.

Every hop is a real process: the installed AI service (round profile-2 with an authored business calendar, online plan
admission, S2/S3 replay, native freeze and observation export), the built Spring jar (round scheduler R1-R7, analyze_plan
worker, document import, admin round commands) and a dedicated PostgreSQL. Nothing is mocked. Authored replay only: no
keys, no provider, no network beyond loopback and the database host.

Two application rounds are started through the supported admin command (startGraphRound with an explicit slot):
  1. Friday 2026-10-16 09:05 (business day): R1 run -> R2 plan -> R3 analyze_plan job -> R4 S2/S3 -> R5 freeze with the
     app's own document bindings -> R6 ready -> R7 inactive import over HTTP. The active pointer is not touched.
  2. Saturday 2026-10-17 09:05 (non-business day): the AI answers no_new_material/non_business_day without a tick, the app
     requests a planless freeze, the AI re-selects the same ledger job so the content-derived handoff is Friday's, and the
     import ends `imported` with outcome `unchanged` on the same version. No ingestion tick runs.

Test seams (no product hooks): the AI service clock is injected with ai/service/pipeline_tests/calendar_round_launcher.py,
and a transparent HTTP proxy holds the app's plan admission until the authored S3 replay fixtures and the operator's
admission policy are in place (a human operator does that ahead of time in real operation).

Prerequisites, prepared once and never installed by this command (Linux; the AI ledgers need fcntl/POSIX modes):
  ai/pipeline/.venv, ai/service/.venv, ai/worker/.venv   (make pipeline-install service-install worker-install)
  api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar             (make api-build)
  a reachable empty PostgreSQL 16 server and psql on PATH; JDK >= 21

  ai/service/.venv/bin/python api/scripts/graph_round_smoke.py --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar \
    --java /path/to/java --pg-host <host> --pg-port 5432 --pg-user <superuser> --output /tmp/round-smoke-unique

A new database is created on that server for each run and dropped at the end (--keep-database keeps it). The output
directory must not exist; it keeps the report, logs and the owned working tree on failure.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "ai/service/pipeline_tests"))
from online_admission_support import GUARD, WRAPPER  # noqa: E402
from extraction_support import ExtractionWorkspace, make_service, terminate_extraction  # noqa: E402
from relation_support import PIPELINE, PIPELINE_PYTHON, terminate_relation  # noqa: E402
from calendar_round_support import calendar_inputs, configure_calendar  # noqa: E402
from analyze_plan_queue_support import HttpProxy, canonical, check, free_port, private_json, provision, stop, wait_for  # noqa: E402

BUILDER = ROOT / "ai/service/pipeline_tests/build_round_service_world.py"
LAUNCHER = ROOT / "ai/service/pipeline_tests/calendar_round_launcher.py"
ADMISSION = "/internal/v1/plan-admissions"
POLICY = "/internal/v1/plan-admission-policy"
ROUNDS = "/api/v1/admin/pipeline/rounds"
FRIDAY, SATURDAY = "2026-10-16", "2026-10-17"
STORE_ID = "round-smoke-artifacts-1"
ORIGIN = "http://127.0.0.1:5173"
TERMINAL = {"imported", "skipped", "failed"}
CATALOGUE = {"KRX:005930": "삼성전자", "KRX:000660": "SK하이닉스"}  # V20261014163000 seed


def slot_utc(day, hhmm="09:05"):
    local = datetime.fromisoformat(f"{day}T{hhmm}:00+09:00")
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def round_id(day, hhmm="09:05"):
    return "round-" + day.replace("-", "") + "T" + hhmm.replace(":", "")


class Postgres:
    """A fresh database on a dedicated server, read and asserted with psql; never used to seed positive state."""

    def __init__(self, host, port, user, password, keep):
        self.host, self.port, self.user, self.password, self.keep = host, str(port), user, password or "", keep
        self.name = "round_smoke_" + secrets.token_hex(5)
        self.created = False

    def _psql(self, sql, database):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PGPASSWORD": self.password, "PGCLIENTENCODING": "UTF8"}
        done = subprocess.run(["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-h", self.host, "-p", self.port, "-U", self.user,
                               "-d", database, "-c", sql], env=env, capture_output=True, timeout=60)
        check(done.returncode == 0, "psql failed: " + done.stderr.decode("utf-8", "replace")[-300:])
        return done.stdout.decode("utf-8").strip()

    def create(self):
        self._psql(f"CREATE DATABASE {self.name} TEMPLATE template0 ENCODING 'UTF8'", "postgres")
        self.created = True
        return self

    def scalar(self, sql):
        return json.loads(self._psql(f"SELECT to_json(({sql}))", self.name))

    def rows(self, sql):
        return json.loads(self._psql(f"SELECT coalesce(json_agg(t), '[]'::json) FROM ({sql}) t", self.name))

    @property
    def url(self):
        return f"jdbc:postgresql://{self.host}:{self.port}/{self.name}?sslmode=disable"

    def drop(self):
        if self.created and not self.keep:
            self._psql(f"DROP DATABASE IF EXISTS {self.name} WITH (FORCE)", "postgres")
            self.created = False


class AiRound:
    """The AI side exactly as ai/service/pipeline_tests/round_service_support.py prepares it, with the calendar profile."""

    def __init__(self, root):
        self.root = root
        self.services = []
        root.mkdir(mode=0o700)
        guard = root / "guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(GUARD.replace("__ROOT__", repr(str(root))).replace("__GUARD_DIR__", repr(str(guard))))
        with (guard / "sitecustomize.py").open("a") as hook:
            hook.write("\nimport sys\nsys.path.insert(0, " + repr(str(PIPELINE / "src")) + ")\n")
        self.guard = guard
        self.builder_env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(guard), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
                            "ZOOP_STATE_DIR": str(root / "builder-app"), "ZOOP_AI_WORKER_STATE_DIR": str(root / "builder-worker")}
        self.calendar = calendar_inputs("weekend")
        info = self.build("--calendar-fixture", FRIDAY, self.calendar["nextSlot"])
        self.info = info
        world = SimpleNamespace(root=Path(info["root"]), ingestion=Path(info["ingestion"]), extraction=Path(info["extraction"]),
            registry=Path(info["registry"]), producer=Path(info["producer"]), verifier=Path(info["verifier"]),
            s2_replay=Path(info["s2Replay"]), s2_topic=Path(info["s2Topic"]), s2_request=info["s2Request"],
            s2_plain_request=info["s2Request"], upstream={"jobId": "unused", "inputDigest": "0" * 64}, source_texts=[])
        self.world = world
        self.workspace = workspace = ExtractionWorkspace(root / "workspace", world, chain=True, topic=False, requests=())
        workspace.relation_state.mkdir()
        self.build("--initialize-ledgers", workspace.extraction_state, workspace.relation_state)
        self.plans, handoffs = root / "plans", root / "handoffs"
        self.plans.mkdir(mode=0o700)
        handoffs.mkdir(mode=0o700)
        credentials = workspace.credentials
        # One application principal for every client of the app (writer placement proposal): round, analysis, handoff, observation.
        wanted = ["plan.admit", "plan.read", "round.run", "round.read", "observation.read", "handoff.read"]
        credentials.scopes["alpha"] += [scope for scope in wanted if scope not in credentials.scopes["alpha"]]
        credentials.tokens["operator"] = "t" + secrets.token_urlsafe(36)
        credentials.scopes["operator"] = ["plan.policy"]
        commands = {}
        for module, log in (("extraction_cli", "s2"), ("relation_cli", "s3"), ("ingestion_cli", "ingestion"), ("handoff_cli", "handoff")):
            path = root / (module + ".py")
            script = WRAPPER.replace("__PYTHON__", str(PIPELINE_PYTHON)).replace("__GUARD_DIR__", repr(str(guard)))
            script = script.replace("__ROOT__", repr(str(root))).replace("__COMMAND_LOG__", repr(log + "-commands"))
            script = script.replace("__MODULE__", repr("zoop_ai_pipeline." + module))
            path.write_text(script)
            path.chmod(0o755)
            commands[module] = path
        workspace.s2_command, workspace.command = commands["extraction_cli"], commands["relation_cli"]
        self.canonical, self.decisions = root / "canonical.json", root / "decisions.json"
        bindings, exports = root / "bindings.json", root / "exports.json"
        self.canonical.write_text(canonical({"schemaVersion": "zoop-graph-canonical-1", "entries": []}))
        self.decisions.write_text(canonical({"schemaVersion": "zoop-public-decisions-4", "policyVersion": "zoop-public-projection-policy-2",
                                             "companies": [], "issues": [], "structural": [], "follows": [], "origins": []}))
        bindings.write_text(canonical(info["bindings"]))
        exports.write_text(canonical({"schemaVersion": "zoop-ai-handoff-exports-1", "handoffs": []}))
        profile = root / "profile.json"
        profile.write_text(canonical({"schemaVersion": "zoop-ai-round-profile-1", "sourceId": "synthetic-source", "scopeId": "body",
            "initialFrom": "2026-10-17T00:00:00+09:00", "fixtureManifest": info["fixtureManifest"], "descriptor": info["descriptor"],
            "selection": {"maxAgeSeconds": 315360000, "limit": 8, "cadenceMinutes": 30}}))
        configure_calendar(root, profile, self.calendar)  # -> zoop-ai-round-profile-2, through-next-business-day-close-1
        self.set_clock(FRIDAY + "T09:10:00+09:00")
        self.env = workspace.env(ZOOP_AI_SERVICE_PLAN_ADMISSION="1", ZOOP_AI_SERVICE_PLAN_ROOT=str(self.plans),
            ZOOP_AI_SERVICE_EXTRACTION_APPROVALS=None, ZOOP_AI_SERVICE_RELATION_UPSTREAMS=None,
            ZOOP_AI_SERVICE_INGESTION_COMMAND=str(commands["ingestion_cli"]), ZOOP_AI_SERVICE_ROUND_PROFILE=str(profile),
            ZOOP_AI_SERVICE_HANDOFF_COMMAND=str(commands["handoff_cli"]), ZOOP_AI_HANDOFF_STATE_DIR=str(handoffs),
            ZOOP_AI_HANDOFF_RELATION_STATE_DIR=str(workspace.relation_state), ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR=str(workspace.extraction_state),
            ZOOP_AI_HANDOFF_INGESTION_STATE_DIR=str(world.ingestion), ZOOP_AI_SERVICE_HANDOFF_SOURCES=str(workspace.sources),
            ZOOP_AI_SERVICE_HANDOFF_CANONICAL=str(self.canonical), ZOOP_AI_SERVICE_HANDOFF_DECISIONS=str(self.decisions),
            ZOOP_AI_SERVICE_HANDOFF_BINDINGS=str(bindings), ZOOP_AI_SERVICE_HANDOFF_EXPORTS=str(exports))
        self.env["PYTHONPATH"] = str(ROOT / "ai/service/src")

    def build(self, *args):
        done = subprocess.run([str(PIPELINE_PYTHON), str(BUILDER), str(PIPELINE), str(self.root / "world"), *map(str, args)],
                              env=self.builder_env, capture_output=True, timeout=600)
        (self.root / f"build-{len(list(self.root.glob('build-*.stderr'))):02d}.stderr").write_bytes(done.stderr)
        check(done.returncode == 0 and not done.stderr, "round fixture subprocess failed; inspect retained stderr")
        return json.loads(done.stdout)

    def set_clock(self, value):
        (self.root / "clock").write_text(value)

    def start(self):
        service = make_service(self.workspace, env=self.env)
        service._runs = len(self.services)
        service._argv = [sys.executable, str(LAUNCHER), str(self.root / "clock")]
        self.services.append(service)
        self.service = service.start()
        return self.service

    @property
    def url(self):
        return f"http://127.0.0.1:{self.workspace.port}"

    def token(self, principal="alpha"):
        return self.workspace.credentials.tokens[principal]

    def commands(self, family):
        path = self.root / (family + "-commands")
        return path.read_text().splitlines() if path.exists() else []

    def prepare_analysis(self, plan_id):
        """The operator's ahead-of-time part, done while the app's admission is held: authored S3 replay for this exact plan,
        the public mapping, and a bounded replay admission policy pinned to those fixture bytes."""
        authored = self.build(self.plans / plan_id / "approvals.json", self.workspace.s2_replay)
        self.workspace.use_fixtures(Path(authored["producer"]), Path(authored["verifier"]))
        self.canonical.write_text(canonical(authored["canonical"]))
        decisions = authored["decisions"]
        for company in decisions["companies"]:  # public labels must equal the seeded catalogue names (importer company check)
            company["label"] = CATALOGUE[company["publicId"]]
        self.decisions.write_text(canonical(decisions))
        descriptor = self.info["descriptor"]
        sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        digest = lambda value: hashlib.sha256(canonical(value).encode()).hexdigest()
        policy = {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": True, "principal": "alpha", "sourceIds": ["synthetic-source"],
            "sourceKind": "synthetic", "promptVersion": descriptor["promptVersion"], "catalogueDigest": digest(descriptor["catalogue"]),
            "snapshotDigest": digest(descriptor["snapshot"]), "topic": None, "expiresAt": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
            "limits": {"maxPlans": 2, "maxUnits": 8}, "runtime": {"kind": "replay", "producerReplayDigest": sha(self.workspace.s2_replay),
            "topicReplayDigest": None, "relationReplayDigest": sha(self.workspace.producer), "relationVerifierReplayDigest": sha(self.workspace.verifier)}}
        etag = self.service.request("GET", POLICY, as_="operator").headers["etag"]
        installed = self.service.request("PUT", POLICY, as_="operator", body=policy, key="round-smoke-policy", headers={"If-Match": etag})
        check(installed.status_code == 200, "bounded replay admission policy was not installed: " + installed.text)
        return authored

    def close(self):
        for service in self.services:
            service.close()
        terminate_extraction(self.workspace)
        terminate_relation(self.workspace)


class App:
    """The built jar: operator runs (non-web) and the web process with the round scheduler."""

    def __init__(self, args, root, db, ai, proxy_url, artifacts):
        self.args, self.root, self.db, self.ai, self.proxy_url, self.artifacts = args, root, db, ai, proxy_url, artifacts
        self.csrf_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        self.email = "round-" + secrets.token_hex(5) + "@example.test"
        self.password = "Round proof " + secrets.token_urlsafe(12)
        self.process = None
        self.client = None

    def base_env(self):
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.root), "LANG": "C.UTF-8",
                "DB_URL": self.db.url, "DB_USERNAME": self.db.user, "DB_PASSWORD": self.db.password,
                "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "round-proof", "ZOOP_AUTH_CSRF_KEYS": "round-proof=" + self.csrf_key,
                "SPRING_PROFILES_ACTIVE": "local", "ZOOP_AUTH_ALLOWED_ORIGINS": ORIGIN, "ZOOP_API_CORS_ALLOWED_ORIGINS": ORIGIN,
                "ZOOP_AUTH_SOCIAL_FRONTEND_ORIGIN": ORIGIN, "ZOOP_MARKET_QUOTE_PROVIDER": "off", "ZOOP_MARKET_METRICS_PROVIDER": "off",
                "ZOOP_SWAGGER_ENABLED": "false", "ZOOP_GRAPH_SNAPSHOT_SOURCE": "none", "ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED": "false"}

    def client_env(self, *families, base_url=None, timeout=None):
        """Each client keeps its own documented request timeout (observation export > 45 s child bound) unless one is given."""
        env = {}
        for family in families:
            prefix = f"ZOOP_AI_{family}_CLIENT_"
            env.update({prefix + "ENABLED": "true", prefix + "BASE_URL": base_url or self.proxy_url, prefix + "TOKEN": self.ai.token(),
                        prefix + "CONNECT_TIMEOUT": "2s"})
            if timeout:
                env[prefix + "REQUEST_TIMEOUT"] = timeout
        return env

    def provision(self):
        provision(self.args.java, self.args.jar, self.base_env(), self.root, self.email, self.password,
                  diagnostic_path=self.root / "provision-diagnostic.json")

    def operator(self, label, env):
        result = self.root / f"{label}-result.json"
        done = subprocess.run([self.args.java, "-XX:TieredStopAtLevel=1", "-jar", str(self.args.jar), "--spring.main.web-application-type=none"],
                              cwd=self.root, env={**self.base_env(), **env}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=420)
        (self.root / f"{label}.log").write_bytes(done.stdout)
        return done.returncode, json.loads(result.read_bytes()) if result.exists() and result.stat().st_size else None

    def import_documents(self, refs):
        request = self.root / "documents-request.json"
        private_json(request, {"schemaVersion": "zoop-document-import-1", "items": [
            {"kind": "news", "observation": {key: ref[key] for key in ("roundId", "sourceId", "page", "ordinal", "documentId",
                                                                         "rawVersion", "documentVersion")}} for ref in refs]})
        env = {**self.client_env("OBSERVATION_EXPORT", base_url=self.ai.url), "ZOOP_DOCUMENT_IMPORT_ENABLED": "true",
               "ZOOP_DOCUMENT_IMPORT_OBSERVATION_SOURCE": "http", "ZOOP_DOCUMENT_IMPORT_REQUEST": str(request),
               "ZOOP_DOCUMENT_IMPORT_RESULT": str(self.root / "documents-result.json"), "ZOOP_ARTIFACT_ROOT": str(self.artifacts)}
        return self.operator("documents", env)

    def start_web(self):
        port = free_port()
        env = {**self.base_env(), **self.client_env("ROUND", "HANDOFF_READ", "OBSERVATION_EXPORT", "EXTRACTION", "RELATION"),
               **self.client_env("PLAN_ADMISSION", timeout="120s"),
               "ZOOP_AI_ROUND_CLIENT_EXPECTED_PRINCIPAL": "alpha",
               "ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(self.artifacts),
               # One 09:05 slot and no freeze-only slot: the wall clock can open a round only by crossing 09:05 KST during a run
               # (checked below). Same calendar on every process of this run; startGraphRound needs 09:05 to be a slot.
               "ZOOP_GRAPH_ROUND_ENABLED": "true", "ZOOP_GRAPH_ROUND_INTERVAL": "PT1S", "ZOOP_GRAPH_ROUND_LOOKBACK": "PT0S",
               "ZOOP_GRAPH_ROUND_SLOT_COUNT": "1", "ZOOP_GRAPH_ROUND_FREEZE_ONLY": "",
               "ZOOP_GRAPH_ROUND_WAIT_RETRY_AFTER": "PT2S", "ZOOP_GRAPH_ROUND_BUSY_RETRY_AFTER": "PT2S",
               "ZOOP_GRAPH_ROUND_IMPORT_SOURCE": "http", "ZOOP_GRAPH_ROUND_ARTIFACT_STORE_ID": STORE_ID,
               "ZOOP_ANALYSIS_ANALYZE_PLAN_ENABLED": "true", "ZOOP_ANALYSIS_ANALYZE_PLAN_EXPECTED_PRINCIPAL": "alpha",
               "ZOOP_ANALYSIS_ANALYZE_PLAN_POLL_INTERVAL": "200ms", "ZOOP_ADMIN_REVIEW_RECONCILE_ENABLED": "false",
               "ZOOP_CHAT_EXECUTOR_ENABLED": "false"}
        self.url = f"http://127.0.0.1:{port}"
        self.log = self.root / "web.log"
        with self.log.open("wb") as log:
            self.process = subprocess.Popen([self.args.java, "-XX:TieredStopAtLevel=1", "-Xmx384m", "-jar", str(self.args.jar),
                                             "--server.address=127.0.0.1", f"--server.port={port}"],
                                            cwd=self.root, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.client = httpx.Client(base_url=self.url, timeout=30, trust_env=False)

        def ready():
            check(self.process.poll() is None, "Spring web exited before ready; see web.log")
            try:
                return self.client.get("/api/v1/admin/auth/session").status_code == 200
            except httpx.TransportError:
                return False
        wait_for(ready, 180, "Spring web readiness")
        response = self.client.post("/api/v1/admin/auth/login", headers={"Origin": ORIGIN},
                                    json={"email": self.email, "password": self.password})
        check(response.status_code == 200 and response.json()["authenticated"], "admin login failed: " + response.text[:200])
        self.csrf = response.json()["csrfToken"]

    def admin(self, method, path, body=None):
        headers = {"Origin": ORIGIN, "X-CSRF-Token": self.csrf, "X-Request-ID": "round-proof-" + secrets.token_hex(6)}
        if method == "POST":
            headers["Idempotency-Key"] = secrets.token_hex(16)
            headers["Content-Type"] = "application/json"
        return self.client.request(method, path, headers=headers, content=canonical(body).encode() if body is not None else None)

    def start_round(self, day):
        response = self.admin("POST", ROUNDS, {"slotAt": slot_utc(day)})
        check(response.status_code in (200, 201, 202), f"startGraphRound {day} refused: {response.status_code} {response.text[:300]}")
        return round_id(day)

    def detail(self, rid):
        response = self.admin("GET", ROUNDS + "/" + rid)
        check(response.status_code == 200, f"getGraphRound {rid}: {response.status_code}")
        return response.json()

    def close(self):
        if self.process is not None:
            stop(self.process)
        if self.client is not None:
            self.client.close()


def proxy_findings(proxy):
    """AI calls that lost the transport or answered 5xx, and the distinct 4xx answers (the app's status-first 404s are expected)."""
    lost = [e for e in proxy.events if not isinstance(e["status"], int) or e["status"] >= 500]
    refusals = sorted({(e["method"], e["path"], e["status"], e.get("errorCode")) for e in proxy.events
                       if isinstance(e["status"], int) and e["status"] >= 400})
    return lost, refusals


def stages(detail):
    return [(event["stage"], event["outcome"], event.get("code")) for event in detail["events"]]


def run(args):
    out = args.output.resolve()
    out.mkdir(mode=0o700, parents=True)
    checks, report = [], {"state": "failed"}

    def record(name, condition, detail=None):
        check(condition, name + (": " + canonical(detail) if detail is not None else ""))
        checks.append(name)

    db = Postgres(args.pg_host, args.pg_port, args.pg_user, os.environ.get("PGPASSWORD", ""), args.keep_database).create()
    ai, app, proxy = None, None, None
    try:
        ai = AiRound(out / "ai")
        ai.start()
        artifacts = out / "artifacts"
        artifacts.mkdir(mode=0o700)
        marker = artifacts / ".zoop-artifact-store-id"
        marker.write_text(STORE_ID)
        marker.chmod(0o600)
        proxy = HttpProxy(ai.url)
        app = App(args, out / "app", db, ai, proxy.url, artifacts)
        app.root.mkdir(mode=0o700)
        app.provision()
        record("migrated-and-admin-provisioned", db.scalar("SELECT count(*) FROM admins") == 1)
        before_versions = db.scalar("SELECT count(*) FROM graph_versions")
        before_active = db.scalar("SELECT count(*) FROM graph_versions WHERE active")
        incoming = ai.info["s2Request"]["incoming"]
        code, result = app.import_documents([incoming])
        record("document-registered-over-http", code == 0 and result and result["status"] == "succeeded", result)

        # Round 1: Friday business-day slot, held at the app's plan admission until the operator's part is ready.
        hold = proxy.arm("POST", ADMISSION, before=True)
        app.start_web()
        friday = app.start_round(FRIDAY)
        check(hold.entered.wait(240), "app never reached plan admission; see web.log and the round events: "
              + canonical(stages(app.detail(friday))))
        held_at = time.monotonic()
        planned = app.detail(friday)["round"]
        record("r1-r2-plan-from-ai", planned["plan"] is not None and planned["plan"]["planId"], planned)
        authored = ai.prepare_analysis(planned["plan"]["planId"])
        held = time.monotonic() - held_at
        # The proxy gives a held request up after 90 s; fail here with the real cause instead of a later transport error.
        record("operator-part-within-hold-budget", held < 80, {"heldSeconds": round(held, 1)})
        hold.release.set()

        def settled(rid):
            def done():
                detail = app.detail(rid)
                if detail["round"]["stage"] in TERMINAL:
                    return detail
                time.sleep(1)  # one admin read per second, not wait_for's 50 ms
                return None
            return done
        first = wait_for(settled(friday), 600, "Friday round terminal stage")
        (out / "friday-round.json").write_text(canonical(first) + "\n")
        row = first["round"]
        record("friday-imported", row["stage"] == "imported", {"stage": row["stage"], "failure": row["failureCode"], "events": stages(first)})
        record("friday-handoff-content-derived", row["handoff"]["handoffId"].startswith("hr-"))
        version = row["graphVersionId"]
        record("friday-inactive-version", db.scalar(f"SELECT active FROM graph_versions WHERE id='{version}'") is False)
        record("active-pointer-untouched", db.scalar("SELECT count(*) FROM graph_versions WHERE active") == before_active)
        record("one-new-version", db.scalar("SELECT count(*) FROM graph_versions") == before_versions + 1)
        job = db.rows(f"SELECT status, requested_by FROM analysis_jobs WHERE id='{row['analysisJobId']}'")
        record("system-analysis-job-succeeded", job and job[0]["status"] == "succeeded" and job[0]["requested_by"].startswith("system:"), job)
        stage_path = [stage for stage, outcome, _ in stages(first) if outcome == "advanced"]
        record("friday-full-stage-path", all(s in stage_path for s in ("run_requested", "plan_ready", "analysis_queued", "analysis_done",
                                                                          "freeze_requested", "handoff_ready", "imported")), stage_path)
        calls = {(e["method"], e["path"].split("/internal/v1/")[-1].split("/")[0]) for e in proxy.events}
        record("app-used-every-ai-route", {("POST", "round-runs"), ("POST", "plan-admissions"), ("POST", "extraction-jobs"),
                                          ("POST", "relation-jobs"), ("POST", "round-handoffs"), ("GET", "graph-handoffs"),
                                          ("POST", "observations")} <= calls, sorted(calls))
        ticks_after_friday = ai.commands("ingestion").count("tick")

        # Round 2: Saturday is not a business day in the AI calendar.
        ai.set_clock(SATURDAY + "T09:10:00+09:00")
        saturday = app.start_round(SATURDAY)
        second = wait_for(settled(saturday), 300, "Saturday round terminal stage")
        (out / "saturday-round.json").write_text(canonical(second) + "\n")
        row2 = second["round"]
        codes = [code for _, _, code in stages(second)]
        no_work = [e for e in second["events"] if e["stage"] == "analysis_done" and e["outcome"] == "advanced"
                   and e.get("code") == "no_new_material" and (e.get("detail") or {}).get("code") == "non_business_day"]
        record("saturday-non-business-day", len(no_work) == 1, stages(second))
        record("saturday-planless-freeze", row2["plan"] is None and row2["analysisJobId"] is None, {"stage": row2["stage"], "codes": codes})
        # The carry-only freeze re-selects the same ledger job; the content-derived handoff id is therefore Friday's and the import is a no-op.
        record("saturday-same-handoff-unchanged", row2["stage"] == "imported" and row2["handoff"] == row["handoff"]
               and row2["graphVersionId"] == version and "unchanged" in codes, {"stage": row2["stage"], "failure": row2["failureCode"], "codes": codes})
        record("still-one-new-version", db.scalar("SELECT count(*) FROM graph_versions") == before_versions + 1)
        record("saturday-no-ingestion-tick", ai.commands("ingestion").count("tick") == ticks_after_friday, ai.commands("ingestion"))
        record("active-pointer-still-untouched", db.scalar("SELECT count(*) FROM graph_versions WHERE active") == before_active)
        record("no-provider-or-network", not (ai.root / "network-attempt").exists())
        record("only-admin-started-rounds", db.scalar("SELECT count(*) FROM graph_rounds WHERE started_by NOT LIKE 'admin:%'") == 0
               and db.scalar("SELECT count(*) FROM graph_rounds") == 2)
        # Proxy checks cover every AI call of both rounds (Friday and Saturday), so a retried failure in either is not lost.
        lost, refusals = proxy_findings(proxy)
        record("no-proxy-errors", not proxy.errors, proxy.errors)
        record("no-ai-transport-loss-or-5xx", not lost, lost)
        report = {"state": "passed", "checks": checks, "fridayRound": friday, "saturdayRound": saturday, "graphVersionId": version,
                  "handoffId": row["handoff"]["handoffId"], "saturdayStage": row2["stage"], "planId": planned["plan"]["planId"],
                  "authoredProviderCalls": authored["providerCalls"], "providerCalls": 0, "heldSeconds": round(held, 1),
                  "aiRefusals": [list(item) for item in refusals],
                  "fixture": "authored synthetic world and calendar; replay only"}
        return report
    except BaseException as error:
        report = {"state": "failed", "checks": checks, "error": type(error).__name__, "message": str(error)[:2000]}
        if proxy is not None:
            lost, refusals = proxy_findings(proxy)
            report.update(proxyErrors=proxy.errors, aiTransportLossOr5xx=lost, aiRefusals=[list(item) for item in refusals])
        raise
    finally:
        (out / "report.json").write_text(canonical(report) + "\n")
        cleanup_failures = []
        for name, close in (("app", app and app.close), ("proxy", proxy and proxy.close), ("ai", ai and ai.close), ("database", db.drop)):
            if close:
                try:
                    close()
                except Exception as error:  # every owned resource is still released; the original failure stays the raised one
                    cleanup_failures.append(f"{name}: {type(error).__name__}")
        if cleanup_failures:
            (out / "cleanup-failures.json").write_text(canonical(cleanup_failures) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--java", default=shutil.which("java"))
    parser.add_argument("--output", required=True, type=Path, help="new directory; an existing path is refused")
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--pg-port", default=5432, type=int)
    parser.add_argument("--pg-user", default="postgres")
    parser.add_argument("--keep-database", action="store_true")
    args = parser.parse_args()
    args.jar = args.jar.resolve()
    check(args.jar.is_file(), "built jar missing: make api-build")
    check(args.java, "java executable required (JDK >= 21)")
    check(not args.output.exists(), "output must be a new path")
    check(PIPELINE_PYTHON.is_file(), "ai/pipeline/.venv missing: make pipeline-install")
    check(shutil.which("psql"), "psql required on PATH")
    print(canonical(run(args)))


if __name__ == "__main__":
    main()
