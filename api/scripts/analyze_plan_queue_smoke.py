#!/usr/bin/env python3
"""Actual admin POST -> PostgreSQL intent/units -> Spring worker -> real AI S2/S3.

Prerequisites prepared ONCE by Main, never built/installed by this command:
  ai/service/.venv/bin/python (frozen service + worker dependencies)
  ai/pipeline/.venv/bin/{python,zoop-ai-ingest,zoop-ai-extract,zoop-ai-relation}
  api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar (current production sources/migrations)
  cached postgres:16.13-alpine + running Docker, OR --postgres-bin /cached/pg/bin
  JDK >=21 (--java /absolute/path/to/java)

From this worktree, with an EXTERNAL fresh output directory:
  ai/service/.venv/bin/python api/scripts/analyze_plan_queue_smoke.py \
    --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --output /tmp/queue-proof-unique
  ai/service/.venv/bin/python api/scripts/analyze_plan_queue_smoke.py \
    --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --output /tmp/queue-ui-unique \
    --serve-ui --ui-origin http://127.0.0.1:5173 --ui-hold-stage s2

--serve-ui is a long-running fixture, NOT a browser/web frontend launcher. Its
private 0600 bootstrap.json contains login/config/reference paths. Readiness only
prints API URL, bootstrap FILE path, PID and control paths; never credentials.
Main owns browser scenario 15; --ui-proof accepts its content-free evidence file.
Absent that file, scenarios 1-14 run but final status is INCONCLUSIVE (exit 2), not
an invented all-15 pass. SIGTERM/SIGINT/SIGHUP always enter bounded owned cleanup.

Only authored replay, no keys/live gates/model budget/operating registry. SQL is
assertion/fault control and explicitly named legacy migration fixtures, never the
positive create entrypoint. No PlanAdmissionProof/client-only substitute.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version as distribution_version
from pathlib import Path
from urllib.parse import urlsplit

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "ai/service/pipeline_tests"))
from online_admission_support import DISABLED, OnlineScenario
import online_admission_support as online
from extraction_support import make_service
from analyze_plan_queue_support import Database, HttpProxy, PgProxy, canonical, check, free_port, legacy_history_matches, private_json, provision, stop, wait_for

JOBS = "/api/v1/admin/jobs"
S2 = "/internal/v1/extraction-jobs"
S3 = "/internal/v1/relation-jobs"
ADMISSION = "/internal/v1/plan-admissions"
OLD_MIGRATION = "20261024120000"
NEW_MIGRATION = "20261025120000"
# Sole source of this lock is JdbcAnalyzePlanRepository.claim. A mismatch fails
# the paused-claim assertions; no application hook or alternate claimant exists.
CLAIM_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended('zoop-analysis-admin-execution-v1',0))"
TERMINAL = {"succeeded", "failed", "cancelled"}


def quoted(value):
    return "'" + str(value).replace("'", "''") + "'"


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def expect(response, status, code=None):
    check(response.status_code == status, f"HTTP expectation failed: expected {status}, observed {response.status_code}; response content withheld")
    if code:
        check(response.json().get("error", {}).get("code") == code, f"expected public error {code}; actual content withheld")
    return response.json() if response.content else None


class Interrupted(BaseException):
    pass


class App:
    def __init__(self, stack, name, *, enabled=True, deadline="3m", max_failures=3,
                 request_timeout="3s", lease="35s", binding_url=None, port=None):
        self.stack, self.name = stack, name
        self.port = port if port is not None else free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.log = stack.root / f"{name}.log"
        self.env = stack.app_env(self.port)
        for family in ("EXTRACTION", "RELATION", "PLAN_ADMISSION"):
            self.env[f"ZOOP_AI_{family}_CLIENT_REQUEST_TIMEOUT"] = request_timeout
            if binding_url:
                self.env[f"ZOOP_AI_{family}_CLIENT_BASE_URL"] = binding_url
        args = [stack.args.java, "-XX:TieredStopAtLevel=1", "-Xmx256m", "-jar", str(stack.args.jar),
                "--server.address=127.0.0.1", f"--server.port={self.port}",
                f"--zoop.analysis.analyze-plan.enabled={str(enabled).lower()}",
                "--zoop.analysis.analyze-plan.expected-principal=alpha", "--zoop.analysis.analyze-plan.poll-interval=100ms",
                f"--zoop.analysis.analyze-plan.lease={lease}", f"--zoop.analysis.analyze-plan.attempt-deadline={deadline}",
                f"--zoop.analysis.analyze-plan.max-consecutive-failures={max_failures}",
                "--zoop.analysis.analyze-plan.max-recovery-dispatches=2", "--zoop.analysis.analyze-plan.max-reclaims=8"]
        with self.log.open("wb") as log:
            self.process = subprocess.Popen(args, cwd=stack.root, env=self.env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.client = httpx.Client(base_url=self.url, timeout=10, trust_env=False)
        self.csrf = None
        self.admin_id = None
        try:
            self.ready()
            self.login()
        except BaseException:
            self.close(kill=True)
            raise

    def ready(self):
        def ready():
            check(self.process.poll() is None, f"Spring {self.name} exited before ready; private owned log retained until cleanup")
            try:
                return self.client.get("/api/v1/admin/auth/session").status_code == 200
            except httpx.TransportError:
                return False
        wait_for(ready, 120, "real Spring HTTP/admin session readiness")

    def login(self):
        response = self.client.post("/api/v1/admin/auth/login", headers={"Origin": self.stack.origin},
                                    json={"email": self.stack.email, "password": self.stack.password})
        body = expect(response, 200)
        check(body["authenticated"], "supported admin login did not authenticate")
        self.csrf, self.admin_id = body["csrfToken"], body["admin"]["id"]

    def request(self, method, path, *, body=None, raw=None, key=None, csrf=True, authenticated=True):
        headers = {"Origin": self.stack.origin, "X-Request-ID": "queue-proof-" + secrets.token_hex(8)}
        if csrf:
            headers["X-CSRF-Token"] = self.csrf
        if key:
            headers["Idempotency-Key"] = key
        if body is not None:
            raw = canonical(body).encode()
        if raw is not None:
            headers["Content-Type"] = "application/json"
        if authenticated:
            return self.client.request(method, path, headers=headers, content=raw)
        with httpx.Client(base_url=self.url, timeout=10, trust_env=False) as anonymous:
            return anonymous.request(method, path, headers=headers, content=raw)

    def get(self, job):
        return expect(self.request("GET", JOBS + "/" + job), 200)

    def list(self):
        return expect(self.request("GET", JOBS), 200)

    def create(self, index=0, *, key=None, reason="Authored synthetic analysis queue proof"):
        response = self.request("POST", JOBS, body=self.stack.body(index, reason), key=key or secrets.token_hex(16))
        if response.status_code == 202:
            check(response.headers.get("Location") == JOBS + "/" + response.json()["job"]["id"], "202 create omitted exact public Location")
        return response

    def cancel(self, job, key=None):
        return self.request("POST", JOBS + "/" + job + "/cancel", body={"reason": "Stop authored synthetic test"}, key=key or secrets.token_hex(16))

    def retry(self, job, key=None):
        return self.request("POST", JOBS + "/" + job + "/retry", body={"reason": "Continue exact authored synthetic plan"}, key=key or secrets.token_hex(16))

    def wait(self, job, status="succeeded", timeout=240):
        def settled():
            body = self.get(job)
            if body["status"] in TERMINAL:
                check(body["status"] == status, f"job ended {body['status']} instead of {status}; jobId={job}; errorCode={(body.get('error') or {}).get('code')}")
                return body
            return None
        return wait_for(settled, timeout, f"{job} terminal {status}")

    def close(self, kill=False):
        stop(self.process, kill)
        self.client.close()


class Stack:
    def __init__(self, args, label, *, legacy=False, fault_service=None, hold_pipeline=False):
        self.args, self.label, self.legacy = args, label, legacy
        self.evidence = args.output / label
        self.evidence.mkdir(mode=0o700)
        self.root = Path(tempfile.mkdtemp(prefix="zoop-analyze-plan-"))
        self.root.chmod(0o700)
        self.apps, self.barriers = [], []
        self.scenario = OnlineScenario(self.root / "online", self.root / "ai-evidence")
        self.db, self.http, self.pg = None, None, None
        self.fault_service, self.hold_pipeline = fault_service, hold_pipeline
        self.email = "queue-" + secrets.token_hex(5) + "@example.test"
        self.password = "Queue proof " + secrets.token_urlsafe(12)
        self.csrf_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        self.origin = args.ui_origin or "http://127.0.0.1:5173"
        self.call_evidence = []
        self.protected = None
        self.closed = False

    def prepare(self):
        online.BUILD = HERE / "analyze_plan_queue_world.py"
        self.scenario.prepare()
        credentials = self.scenario.workspace.credentials
        credentials.tokens = {key: value for key, value in credentials.tokens.items() if key in ("alpha", "operator")}
        credentials.scopes = {"alpha": ["plan.admit", "plan.read", "extraction.submit", "extraction.read", "extraction.cancel", "extraction.recover",
                                         "relation.submit", "relation.read", "relation.cancel", "relation.recover"], "operator": ["plan.policy"]}
        check(not any(scope.endswith("review") or scope == "plan.policy" for scope in credentials.scopes["alpha"]), "app principal has forbidden scope")
        self.start_ai()
        self.scenario.install_policy(self.scenario.policy(max_plans=3, max_units=6))
        check(self.scenario.service.request("GET", "/internal/v1/plan-admission-policy").status_code == 403, "app principal can read policy")
        self.db = Database(self.root, postgres_bin=self.args.postgres_bin, image=self.args.image).start()
        (self.evidence / "environment.json").write_text(canonical({
            "postgresVersion": self.db.sql("SELECT version()"),
            "servicePython": sys.executable, "serviceVersion": distribution_version("zoop-ai-service"),
            "workerVersion": distribution_version("zoop-ai-worker"),
            "pipelinePython": self.scenario.info["pipelinePython"], "pipelineVersion": self.scenario.info["pipelineVersion"],
            "fixtureBuilder": str(HERE / "analyze_plan_queue_world.py"), "sourceRoot": str(ROOT),
            "appScopes": credentials.scopes["alpha"], "operatorScopes": credentials.scopes["operator"],
            "initialQuota": self.scenario.usage(), "initialDispatch": self.scenario.dispatch_counts()
        }) + "\n")
        self.pg = PgProxy(self.db.port)
        self.http = HttpProxy(f"http://127.0.0.1:{self.scenario.workspace.port}", self.before_upstream)
        env = self.app_env(0)
        env["SPRING_FLYWAY_TARGET"] = OLD_MIGRATION
        provision(self.args.java, self.args.jar, env, self.root, self.email, self.password,
                  diagnostic_path=self.evidence / "provision-diagnostic.json")
        if self.legacy:
            self.seed_legacy_migration_fixture()
        return self

    def start_ai(self, fault=None):
        fault = fault or self.fault_service
        if fault in ("reserved", "extraction-claim"):
            service = make_service(self.scenario.workspace, env=self.scenario.env(),
                                   launcher=fault == "extraction-claim",
                                   launcher_env={"ZOOP_TEST_EXTRACTION_CRASH_AT": "after_claim"} if fault == "extraction-claim" else None)
            if fault == "reserved":
                service._argv = [sys.executable, str(HERE / "analyze_plan_queue_service.py"), str(self.scenario.root)]
            service._runs = len(self.scenario.services)
            self.scenario.services.append(service)
            self.scenario.service = service.start()
        else:
            self.scenario.start(hold=self.hold_pipeline, fault=fault)
        return self.scenario.service

    def app_env(self, port):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.root), "LANG": "C.UTF-8",
               "DB_URL": f"jdbc:postgresql://127.0.0.1:{self.pg.port}/postgres?sslmode=disable&preferQueryMode=simple",
               "DB_USERNAME": self.db.user, "DB_PASSWORD": self.db.password,
               "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "queue-proof", "ZOOP_AUTH_CSRF_KEYS": "queue-proof=" + self.csrf_key,
               "SPRING_PROFILES_ACTIVE": "local", "ZOOP_AUTH_ALLOWED_ORIGINS": self.origin,
               "ZOOP_API_CORS_ALLOWED_ORIGINS": self.origin, "ZOOP_AUTH_SOCIAL_FRONTEND_ORIGIN": self.origin,
               "ZOOP_MARKET_QUOTE_PROVIDER": "off", "ZOOP_MARKET_METRICS_PROVIDER": "off", "ZOOP_GRAPH_SNAPSHOT_SOURCE": "none",
               "ZOOP_SWAGGER_ENABLED": "false"}
        for family in ("EXTRACTION", "RELATION", "PLAN_ADMISSION"):
            prefix = f"ZOOP_AI_{family}_CLIENT_"
            env.update({prefix + "ENABLED": "true", prefix + "BASE_URL": self.http.url,
                        prefix + "TOKEN": self.scenario.workspace.credentials.tokens["alpha"],
                        prefix + "CONNECT_TIMEOUT": "1s", prefix + "REQUEST_TIMEOUT": "3s"})
        return env

    def start(self, **kwargs):
        app = App(self, f"app-{len(self.apps)}", **kwargs)
        self.apps.append(app)
        self.app = app
        if self.protected is None:
            self.protected = self.protected_snapshot()
        return app

    def body(self, index, reason="Authored synthetic analysis queue proof"):
        ref = self.scenario.references[index]
        return {"kind": "analyze_plan", "reason": reason, "plan": {key: ref[key] for key in ("planId", "planDigest")}}

    def plan(self, index=0):
        return self.scenario.references[index]["planId"]

    def units(self, index=0):
        return self.db.json("SELECT coalesce(jsonb_agg(to_jsonb(u) ORDER BY ordinal),'[]') FROM analysis_plan_units u WHERE plan_id=" + quoted(self.plan(index)))

    def job_row(self, job):
        return self.db.json("SELECT to_jsonb(j) FROM analysis_jobs j WHERE id=" + quoted(job))

    def counts(self):
        return self.db.json("SELECT jsonb_build_object('jobs',(SELECT count(*) FROM analysis_jobs),'plans',(SELECT count(*) FROM analysis_plans),"
                            "'units',(SELECT count(*) FROM analysis_plan_units),'idempotency',(SELECT count(*) FROM idempotency_records),"
                            "'createAudit',(SELECT count(*) FROM audit_logs WHERE action='analysis.job.create'))")

    def before_upstream(self, method, path, raw):
        if method != "POST":
            return
        if path == ADMISSION:
            ref = json.loads(raw)
            row = self.db.json("SELECT to_jsonb(p) FROM analysis_plans p WHERE plan_id=" + quoted(ref["planId"]))
            check(row and row["admission_intent_at"] is not None, "AI admission reached before durable app intent")
            jobs = self.db.json("SELECT jsonb_agg(to_jsonb(j)) FROM analysis_jobs j WHERE plan_id=" + quoted(ref["planId"]))
            check(jobs and all(j["input"]["planDigest"] == ref["planDigest"] for j in jobs), "AI admission has no exact committed job")
            self.call_evidence.append({"boundary": "admission", "planId": ref["planId"], "committedJobIds": [j["id"] for j in jobs]})
        elif path in (S2, S3):
            body = json.loads(raw)
            family = "s2" if path == S2 else "s3"
            row = self.db.json(f"SELECT to_jsonb(u) FROM analysis_plan_units u WHERE {family}_job_id=" + quoted(body["jobId"]))
            check(row and row[family + "_submit"] == body, "AI submit differs from durable exact command")
            check(row[family + "_checkpoint"]["state"] == "submit_pending", "AI submit lacks durable pending intent")
            plan = self.db.json("SELECT to_jsonb(p) FROM analysis_plans p WHERE plan_id=" + quoted(row["plan_id"]))
            count = int(self.db.sql("SELECT count(*) FROM analysis_plan_units WHERE plan_id=" + quoted(row["plan_id"])))
            check(count == len(plan["manifest"]["units"]) >= 2, "partial unit transaction dispatched")
            if family == "s3":
                check(row["s2_checkpoint"]["state"] == "result_observed", "S3 submitted before its durable S2 result observation")
            self.call_evidence.append({"boundary": family, "planId": row["plan_id"], "ordinal": row["ordinal"], "jobId": body["jobId"], "allUnitsCommitted": count})

    def claim_barrier(self):
        barrier = self.db.hold(CLAIM_LOCK_SQL)
        self.barriers.append(barrier)
        return barrier

    def release(self, barrier):
        self.db.release(barrier)

    def protected_snapshot(self):
        excluded = ("analysis_jobs", "analysis_plans", "analysis_plan_units", "audit_logs", "idempotency_records", "admin_sessions", "auth_rate_events", "flyway_schema_history")
        tables = self.db.json("SELECT jsonb_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname='public'")
        result = {}
        for table in tables:
            if table not in excluded:
                result[table] = self.db.sql(f'SELECT md5(coalesce(string_agg(to_jsonb(t)::text,\'\' ORDER BY to_jsonb(t)::text),\'\')) FROM "{table}" t')
        return result

    def seed_legacy_migration_fixture(self):
        """ONLY permitted app SQL seed: clearly named pre-upgrade legacy/history rows."""
        self.db.sql("""
          INSERT INTO analysis_jobs(id,kind,scope,label,status,reason,requested_by,requested_at,started_at,finished_at,command_key,input,checkpoint,attempts)
          VALUES ('job-legacy-ingest','ingest','admin','Synthetic legacy ingest','succeeded','legacy migration fixture','legacy-admin',
                  clock_timestamp()-interval '3 hours',clock_timestamp()-interval '2 hours',clock_timestamp()-interval '1 hour',
                  'legacy-fixture-ingest','{"sourceId":"synthetic-source","candidateIds":[]}', '{"legacy":true}', '[{"legacy":true}]'),
                 ('job-legacy-failed','revalidate','admin','Synthetic legacy failed','failed','legacy migration fixture','legacy-admin',
                  clock_timestamp()-interval '3 hours',clock_timestamp()-interval '2 hours',clock_timestamp()-interval '1 hour',
                  'legacy-fixture-failed','{"candidateIds":["legacy-candidate"]}', '{"legacy":true}', '[]'),
                 ('job-legacy-internal','project','internal_projection','Synthetic internal projection','queued','legacy migration fixture','legacy-system',
                  clock_timestamp()-interval '3 hours',NULL,NULL,'legacy-fixture-internal','{"legacy":true}',NULL,'[]');
          INSERT INTO review_targets(id,target_type,source_job_id,external_id,source_version,candidate_id,status,source_revision,updated_at)
          VALUES ('legacy-review-fixture','candidate','legacy-ai-job','legacy-candidate','legacy-version','legacy-candidate','HOLD','0',clock_timestamp());
        """)
        self.legacy_before = self.db.json("SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM analysis_jobs j")
        self.review_before = self.db.json("SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM review_targets t")

    def assert_legacy_history_unchanged(self, message):
        after = self.db.json("SELECT jsonb_agg(to_jsonb(j) ORDER BY id) FROM analysis_jobs j WHERE id LIKE 'job-legacy-%'")
        # Keep the pre-migration snapshot intact. Compare every original column
        # and separately require the new binding column to exist and remain NULL.
        changes = []
        for old, new in zip(self.legacy_before, after):
            columns = (set(old) | set(new)) - {"plan_id"}
            changed = sorted(key for key in columns if key not in old or key not in new or old[key] != new[key])
            if changed:
                changes.append({"expectedId": old["id"], "actualId": new["id"], "changedColumns": changed})
        (self.evidence / "legacy-history-comparison.json").write_text(canonical({
            "beforeRowIds": [row["id"] for row in self.legacy_before],
            "afterRowIds": [row["id"] for row in after],
            "newPlanBindingNull": all("plan_id" in row and row["plan_id"] is None for row in after),
            "originalColumnChanges": changes,
        }) + "\n")
        check(legacy_history_matches(self.legacy_before, after), message)

    def assert_handoff(self, job, index=0):
        check(job["kind"] == "analyze_plan" and job["status"] == "succeeded", "wrong successful queue kind")
        summary = job["planRun"]
        check(summary["phase"] == "ready" and summary["totalUnits"] == summary["readyUnits"] == 2,
              "not every real pair completed")
        check(summary["completion"] == "ai_processing_handoff" and summary["publicChanged"] is False, "handoff claims publication")
        check(all(job.get(key) is None for key in ("report", "ingest", "flush", "ledgerBefore", "ledgerAfter")), "analysis fabricated legacy report")
        rows = self.units(index)
        admission = self.scenario.status(self.scenario.references[index]).json()
        saved_plan = self.db.json("SELECT to_jsonb(p) FROM analysis_plans p WHERE plan_id=" + quoted(self.plan(index)))
        check(saved_plan["manifest"] == admission["manifest"], "durable manifest differs from complete verified admission")
        check(saved_plan["plan_digest"] == self.scenario.references[index]["planDigest"]
              and saved_plan["expected_principal"] == "alpha", "registered reference/principal rebound")
        for column, field in (("admission_id", "admissionId"), ("policy_revision", "policyRevision"), ("policy_digest", "policyDigest")):
            check(saved_plan[column] == admission[field], "durable admission/policy pin mismatch")
        check(saved_plan["receipt_sha256"] == admission["manifest"]["receiptSha256"]
              and saved_plan["manifest_digest"] == admission["manifest"]["manifestDigest"], "durable receipt/manifest pin mismatch")
        check(saved_plan["manifest_digest"] == digest({key: value for key, value in admission["manifest"].items() if key != "manifestDigest"}),
              "manifest digest is not the complete canonical public manifest")
        check(len(rows) == len(admission["manifest"]["units"]) == 2, "wrong manifest cardinality")
        for row, unit in zip(rows, admission["manifest"]["units"], strict=True):
            check(row["s2_submit"] == unit["extractionSubmit"] and row["s3_submit"] == unit["relationSubmit"], "durable submits changed immutable admission")
            check(row["s2_input_digest"] == unit["extractionInputDigest"]
                  and row["s2_approved_request_digest"] == unit["extractionSubmit"]["approvedRequestDigest"], "durable S2 pins differ")
            check(row["s3_input_digest"] and len(row["s3_input_digest"]) == 64, "S3 runtime digest not pinned")
            for family in ("s2", "s3"):
                checkpoint = row[family + "_checkpoint"]
                check(checkpoint["state"] == "result_observed" and checkpoint["resultObservedAt"] and checkpoint["resultContentSha256"], "missing result-envelope observation")
                typed = checkpoint["lastStatus"]["extraction" if family == "s2" else "relation"]
                check(typed["usage"]["providerCalls"] == 0, "runtime used provider")
                check(typed["state"] == "READY" and typed["delivery"]["state"] == "AVAILABLE", "stored result observation lacks READY/AVAILABLE")
                result = self.scenario.service.eresult(row["s2_job_id"]) if family == "s2" else self.scenario.service.rresult(row["s3_job_id"])
                check(result.status_code == 200 and result.json()["delivery"]["state"] == "available",
                      "synthetic successful handoff is not actually deliverable")
                check(checkpoint["receipts"] == result.json()["receipts"], "durable receipts duplicated, omitted, or changed")
        return {"jobId": job["id"], "planId": summary["planId"], "admissionId": summary["admissionId"],
                "manifestDigest": summary["manifestDigest"], "units": [{key: row[key] for key in ("ordinal", "s2_job_id", "s2_input_digest", "s3_job_id", "s3_input_digest")} for row in rows]}

    def record(self, value):
        (self.evidence / "observations.json").write_text(canonical(value) + "\n")

    def close(self):
        if self.closed:
            return
        self.closed = True
        errors = []
        try:
            for barrier in self.barriers:
                self.db.release(barrier)
            for app in self.apps:
                if app.process.poll() is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(app.process.pid, signal.SIGCONT)
                app.close()
            if self.http:
                self.http.close()
                check(not self.http.errors, "test HTTP proxy failed; no proof may pass")
            if self.protected is not None:
                check(self.protected_snapshot() == self.protected, "worker modified non-queue domain/review/graph/accounting state")
            for app in self.apps:
                text = app.log.read_text(errors="replace")
                for secret in (self.password, self.csrf_key, self.db.password, *self.scenario.workspace.credentials.tokens.values()):
                    check(secret not in text, "secret appeared in application log; retained report excludes it")
                for source_text in ("합성 큐 표본", "배터리 부품을 공급한다", "authored producer reason"):
                    check(source_text not in text, "source/model text appeared in application log")
        except BaseException as error:
            errors.append(error)
        finally:
            try:
                self.scenario.close()
                if hasattr(self.scenario, "workspace"):
                    # Service support checks network and immutable upstreams but
                    # its raw debug logs are NOT copied into public evidence.
                    for service in self.scenario.services:
                        text = service.logs()
                        for secret in self.scenario.workspace.credentials.tokens.values():
                            check(secret not in text, "secret appeared in AI log")
            except BaseException as error:
                errors.append(error)
            if self.pg:
                self.pg.close()
            if self.db:
                self.db.close()
            (self.evidence / "precall-intents.json").write_text(canonical(self.call_evidence) + "\n")
            (self.evidence / "transport-events.json").write_text(canonical(self.http.events if self.http else []) + "\n")
            (self.evidence / "proxy-errors.json").write_text(canonical(self.http.errors if self.http else []) + "\n")
            shutil.rmtree(self.root)
        if errors:
            raise errors[0]


@contextlib.contextmanager
def stack(args, label, **kwargs):
    instance = Stack(args, label, **kwargs)
    try:
        instance.prepare()
        yield instance
    finally:
        instance.close()


def durable_two_plans(args):
    with stack(args, "01-02-durable-two-plans", legacy=True) as s:
        service_pid = s.scenario.service.process.pid
        # Migrate first with worker disabled, then use the real claim lock while
        # enabling its production scheduler in a new JVM.
        initial = s.start(enabled=False)
        baseline = initial.list()["ingest"]
        initial.close()
        barrier = s.claim_barrier()
        app = s.start()
        before = s.counts()
        first = expect(app.create(key="durable-create-0"), 202)
        check(not first["deduplicated"] and first["job"]["status"] == "queued", "claim barrier did not leave a queued public acceptance")
        root = first["job"]["id"]
        row = s.job_row(root)
        check(row["input"] == {"schemaVersion": "zoop-app-analyze-plan-1", **s.body(0)["plan"]}, "durable immutable input differs")
        now = s.counts()
        check(now["jobs"] == before["jobs"] + 1 and now["plans"] == 1 and now["units"] == 0 and now["createAudit"] == 1,
              "202 did not atomically register job, plan and audit")
        idem = s.db.json("SELECT jsonb_build_object('status',status,'http',response_status,'body',response_body) FROM idempotency_records WHERE idem_key='durable-create-0'")
        check(idem == {"status": "completed", "http": 202, "body": first}, "202 response not durable under exact key")
        check(not s.http.events and s.scenario.usage() == {"plans": 0, "units": 0}, "public create/claim barrier made AI call")
        app.close(kill=True)
        s.release(barrier)
        app = s.start()
        observed = [s.assert_handoff(app.wait(root), 0)]
        second = expect(app.create(1), 202)["job"]["id"]
        observed.append(s.assert_handoff(app.wait(second), 1))
        check(s.scenario.service.process.pid == service_pid and s.scenario.service.process.poll() is None,
              "AI service restarted between the two independently completed plans")
        check(s.scenario.usage() == {"plans": 2, "units": 4}, "two-plan cumulative admission quota wrong")
        counts = s.scenario.dispatch_counts()
        check(all(len(rows) == 4 and all(count == 1 for _, count in rows) for rows in counts.values()), "two plans did not dispatch four exact S2/S3 pairs once")
        listing = app.list()
        check({root, second} <= {j["id"] for j in listing["items"]}, "GET/list lost completed public jobs")
        check(listing["ingest"] == baseline, "successful analysis changed legacy collection baseline")
        s.record({"status": "passed", "scenarios": [1, 2], "publicAcceptedBeforeAI": True, "jobs": observed,
                  "sameAiServicePid": service_pid, "quota": s.scenario.usage(), "dispatch": counts, "providerCalls": 0})


def dedup_and_validation(args):
    with stack(args, "03-04-dedup-validation") as s:
        s.start(enabled=False).close()
        barrier = s.claim_barrier()
        app = s.start()
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda _: app.create(key="concurrent-create"), range(4)))
        bodies = [expect(reply, 202) for reply in replies]
        check(all(body == bodies[0] for body in bodies) and not bodies[0]["deduplicated"], "historical same-key replies differ")
        root = bodies[0]["job"]["id"]
        check(s.counts()["jobs"] == s.counts()["plans"] == s.counts()["createAudit"] == 1, "same-key concurrency duplicated durable records")
        changed = s.body(0, "Changed audit reason")
        expect(app.request("POST", JOBS, body=changed, key="concurrent-create"), 409, "IDEMPOTENCY_CONFLICT")
        changed = s.body(0)
        changed["plan"]["planDigest"] = "0" * 64
        expect(app.request("POST", JOBS, body=changed, key="concurrent-create"), 409, "IDEMPOTENCY_CONFLICT")
        expect(app.request("POST", JOBS, body=changed, key="different-key-wrong-digest"), 409, "REVISION_CONFLICT")
        dedup = expect(app.create(key="different-key-same-plan"), 202)
        check(dedup["deduplicated"] and dedup["job"]["id"] == root, "different key did not return root")
        base = s.counts()
        malformed = [dict(s.body(1), sourceId="synthetic-source"), dict(s.body(1), extra=True), dict(s.body(1), candidateIds=[]),
                     {"kind": "analyze_plan", "reason": "valid reason", "plan": {"planId": s.plan(1), "planDigest": "bad"}},
                     {"kind": "analyze_plan", "reason": "valid reason", "plan": dict(s.body(1)["plan"], extra=True)}]
        for body in malformed:
            expect(app.request("POST", JOBS, body=body, key=secrets.token_hex(12)), 422, "INVALID_REQUEST")
        raw = canonical(s.body(1)).encode()
        duplicate = raw.replace(b'"kind":"analyze_plan"', b'"kind":"analyze_plan","kind":"analyze_plan"')
        for body in (duplicate, raw + b"{}", raw.replace(b"Authored", b"\xff"), raw.replace(b'"reason":"', b'"reason":42,"unused":"', 1)):
            expect(app.request("POST", JOBS, raw=body, key=secrets.token_hex(12)), 422, "INVALID_REQUEST")
        expect(app.request("POST", JOBS, body=s.body(1), key="no-csrf", csrf=False), 403, "ACCESS_DENIED")
        expect(app.request("POST", JOBS, body=s.body(1), key="no-session", authenticated=False), 401, "AUTH_REQUIRED")
        for kind in ("ingest", "revalidate", "project"):
            for optional in ({}, {"sourceId": "synthetic-source", "candidateIds": ["candidate-old"]}, {"sourceId": None, "candidateIds": []}):
                body = {"kind": kind, "reason": "Original legacy request shape", **optional}
                result = expect(app.request("POST", JOBS, body=body, key=secrets.token_hex(12)), 503, "SOURCE_UNAVAILABLE")
                check(result["error"]["retryable"] is False, "unimplemented legacy executor advertised retry")
        check(s.counts() == base and not s.http.events, "refused shape/auth/unsupported requests inserted state or called AI")
        s.release(barrier)
        app.wait(root)
        counts, quota = s.scenario.dispatch_counts(), s.scenario.usage()
        repeated = expect(app.create(key="after-success-new-key"), 202)
        check(repeated["job"]["id"] == root and repeated["deduplicated"], "success duplicate silently created retry")
        check(expect(app.create(key="concurrent-create"), 202) == bodies[0], "historical response changed after success")
        check(s.scenario.dispatch_counts() == counts and s.scenario.usage() == quota, "dedup consumed quota or dispatched")
        app.close()
        disabled = s.start(enabled=False)
        before = s.counts()
        check(expect(disabled.create(key="concurrent-create"), 202) == bodies[0], "disabled capability hid completed historical key")
        expect(disabled.create(1, key="fresh-disabled"), 503, "SOURCE_UNAVAILABLE")
        check(s.counts() == before, "fresh disabled create inserted rows")
        disabled.close()
        alternate = HttpProxy(f"http://127.0.0.1:{s.scenario.workspace.port}", s.before_upstream)
        try:
            changed_service = s.start(binding_url=alternate.url)
            snapshot = s.counts()
            expect(changed_service.create(key="different-service-binding"), 409, "REVISION_CONFLICT")
            check(s.counts() == snapshot and not alternate.events, "service binding rebind inserted state or called another service")
            changed_service.close()
        finally:
            alternate.close()
        s.record({"status": "passed", "scenarios": [3, 4], "rootJobId": root, "sameKeyReplies": 4, "quota": quota, "dispatch": counts})


def expire_owned_lease(s, job):
    """Explicit fault control on an existing publicly created row, never job creation."""
    s.db.sql("UPDATE analysis_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id="
             + quoted(job) + " AND status='running' AND owner_token IS NOT NULL")


def admission_hold(s, app):
    rule = s.http.arm("POST", ADMISSION)
    created = expect(app.create(), 202)["job"]["id"]
    check(rule.entered.wait(45), "real admission did not reach response barrier")
    admission = s.scenario.status(s.scenario.references[0]).json()
    check(admission["authority"]["state"] == "active", "actual admission is not active at test barrier")
    return created, rule, admission["manifest"]


def reply_losses(args):
    for family, suffix in (("admission", ADMISSION), ("s2", S2), ("s3", S3)):
        with stack(args, "05-06-reply-loss-" + family) as s:
            app = s.start()
            fault = s.http.arm("POST", suffix, drop=True)
            try:
                job = expect(app.create(), 202)["job"]["id"]
                check(fault.entered.wait(60), "selected actual accepted reply never reached drop boundary")
                check(s.scenario.usage() == {"plans": 1, "units": 2}, "real admission did not debit exact quota once")
                if family == "admission":
                    check(s.units() == [], "manifest settled before its lost response")
                app.close(kill=True)
            finally:
                fault.release.set()
            admitted_before = s.scenario.status(s.scenario.references[0]).json()
            expire_owned_lease(s, job)
            app = s.start()
            final = s.assert_handoff(app.wait(job))
            admitted_after = s.scenario.status(s.scenario.references[0]).json()
            check(admitted_before["manifest"] == admitted_after["manifest"]
                  and admitted_before["policyRevision"] == admitted_after["policyRevision"], "lost reply recovery rebound admission")
            counts = s.scenario.dispatch_counts()
            check(all(len(rows) == 2 and all(count == 1 for _, count in rows) for rows in counts.values()), "lost submit reply duplicated initial dispatch")
            check(s.scenario.usage() == {"plans": 1, "units": 2}, "response recovery debited quota again")
            s.record({"status": "passed", "scenarios": [5 if family == "admission" else 6], "fault": "drop-after-real-upstream-" + family,
                      "handoff": final, "quota": s.scenario.usage(), "dispatch": counts})
    with stack(args, "06-real-reserved-only-404", fault_service="reserved") as s:
        app = s.start()
        (s.scenario.root / "reserve-arm").touch()
        job = expect(app.create(), 202)["job"]["id"]
        wait_for(lambda: (s.scenario.root / "reserve-committed").exists(), 45, "real AI reserve commit")
        app.close(kill=True)
        s.scenario.service.exited()
        s.fault_service = None
        service = s.start_ai()
        unit = s.units()[0]
        expect(service.estatus(unit["s2_job_id"]), 404)
        checkpoint = unit["s2_checkpoint"]
        check(checkpoint["state"] == "submit_pending" and checkpoint["acceptedObservedAt"] is None, "reserved-only lost durable submit intent")
        expire_owned_lease(s, job)
        app = s.start()
        final = s.assert_handoff(app.wait(job))
        posts = [event for event in s.http.events if event["method"] == "POST" and event["path"] == S2]
        check(len({event["requestSha256"] for event in posts}) == 2, "reserved-only recovery changed exact commands or added IDs")
        check(all(count == 1 for rows in s.scenario.dispatch_counts().values() for _, count in rows), "reservation replay duplicated execution")
        s.record({"status": "passed", "scenarios": [6], "reservedStatus404": True, "sameStoredPostOnly": True, "handoff": final})


def commit_boundaries(args):
    for boundary in ("before", "after"):
        with stack(args, "07-result-commit-" + boundary) as s:
            app = s.start()
            fault = s.pg.arm(boundary)
            job = expect(app.create(), 202)["job"]["id"]
            try:
                check(fault.entered.wait(60), "actual JDBC result observation COMMIT barrier was not reached")
                rows = s.units()
                observed = sum(row["s2_checkpoint"]["state"] == "result_observed" for row in rows)
                check(observed == int(boundary == "after"), "result observation durability disagrees with actual COMMIT boundary")
                check(not any(event["method"] == "POST" and event["path"] == S3 for event in s.http.events),
                      "S3 escaped while S2 observation COMMIT was uncertain")
                before = [{"s2": row["s2_checkpoint"], "s3": row["s3_checkpoint"]} for row in rows]
                app.close(kill=True)
            finally:
                fault.release.set()
            expire_owned_lease(s, job)
            app = s.start()
            final = s.assert_handoff(app.wait(job))
            after = s.units()
            if boundary == "after":
                check(after[0]["s2_checkpoint"] == before[0]["s2"], "committed observation/receipts were counted or overwritten on restart")
            check(all(count == 1 for rows in s.scenario.dispatch_counts().values() for _, count in rows), "commit ambiguity duplicated initial execution")
            s.record({"status": "passed", "scenarios": [7], "actualJdbcCommitBoundary": boundary, "handoff": final})


def stale_owner(args):
    with stack(args, "08-two-jvm-stale-owner", legacy=True) as s:
        a = s.start()
        job, held, manifest = admission_hold(s, a)
        owner_a = s.job_row(job)["owner_token"]
        check(owner_a, "first JVM has no owner token")
        os.kill(a.process.pid, signal.SIGSTOP)
        expire_owned_lease(s, job)
        reclaimed = s.http.arm("GET", "/" + s.plan(), before=True)
        b = s.start()
        try:
            check(reclaimed.entered.wait(15), "second JVM did not reach real status boundary")
            wait_for(lambda: s.job_row(job)["owner_token"] not in (None, owner_a), 30, "second JVM lease reclamation")
            owner_b = s.job_row(job)["owner_token"]
            check(int(s.db.sql("SELECT count(*) FROM analysis_jobs WHERE scope='admin' AND status='running'")) == 1, "two JVMs occupied more than one admin slot")
            # A resumes with a real already-processed admission reply and an obsolete fence.
            held.release.set()
            os.kill(a.process.pid, signal.SIGCONT)
            reclaimed.release.set()
            final = s.assert_handoff(b.wait(job))
            terminal_before = s.job_row(job)
            time.sleep(.5)
            check(s.job_row(job) == terminal_before, "stale owner rewrote terminal state")
            s.assert_legacy_history_unchanged("worker claimed internal_projection or changed legacy history")
            expect(b.request("GET", JOBS + "/job-legacy-internal"), 404)
            check(all(item["id"] != "job-legacy-internal" for item in b.list()["items"]), "internal projection is admin visible")
            check(all(count == 1 for rows in s.scenario.dispatch_counts().values() for _, count in rows), "stale owner issued replacement/repeated execution")
            s.record({"status": "passed", "scenarios": [8], "ownerA": owner_a, "ownerB": owner_b,
                      "attempts": terminal_before["attempts"], "handoff": final})
        finally:
            held.release.set()
            reclaimed.release.set()
            with contextlib.suppress(ProcessLookupError):
                os.kill(a.process.pid, signal.SIGCONT)
    # Lock wait crosses the real lease deadline. It cannot use transaction-start
    # now() or a pre-wait Java Instant to settle an expired owner.
    with stack(args, "08-lock-wait-past-real-lease") as s:
        app = s.start()
        job, held, _ = admission_hold(s, app)
        lock = s.db.hold("SELECT id FROM analysis_jobs WHERE id=" + quoted(job) + " FOR UPDATE")
        no_reclaim = s.claim_barrier()
        locked_before = s.job_row(job)
        try:
            held.release.set()
            # Read the actual persisted deadline, not a guessed scheduler interval.
            wait_for(lambda: s.db.sql("SELECT (clock_timestamp()>lease_until)::text FROM analysis_jobs WHERE id=" + quoted(job)) == "true",
                     45, "real lease expires while repository lock waits")
            check(s.units() == [], "locked owner settled admission despite lock barrier")
            s.release(lock)
            time.sleep(.5)
            after_wait = s.job_row(job)
            check(after_wait["owner_token"] == locked_before["owner_token"]
                  and after_wait["lease_until"] == locked_before["lease_until"]
                  and after_wait["checkpoint"] == locked_before["checkpoint"] and not s.units(),
                  "expired owner renewed or settled after row-lock wait")
            app.close(kill=True)
            s.release(no_reclaim)
            # Restart ownership may now accept the same immutable admission.
            app = s.start()
            final = s.assert_handoff(app.wait(job))
            s.record({"status": "passed", "scenarios": [8], "waitedPastActualLease": True, "handoff": final})
        finally:
            held.release.set()
            s.release(lock)
            s.release(no_reclaim)


def runtime_restarts(args):
    for mode in ("receipt", "unknown"):
        with stack(args, "09-real-runtime-" + mode) as s:
            # Existing transparent CLI wrapper kills the REAL pipeline at _receive:
            # after answered receipt vs before answered receipt, never fake statuses.
            (s.scenario.root / ("crash-s2-" + mode)).touch()
            if mode == "receipt":
                (s.scenario.root / "crash-s3-receipt").touch()
            app = s.start()
            job = expect(app.create(), 202)["job"]["id"]
            if mode == "receipt":
                final = s.assert_handoff(app.wait(job))
                counts = s.scenario.dispatch_counts()
                check(any(count > 1 for _, count in counts["extraction"]), "actual answered receipt crash never caused bounded same-ID recovery")
                check(any(count > 1 for _, count in counts["relation"]), "actual S3 receipt crash never caused same-ID recovery")
                check(all(count <= 3 for rows in counts.values() for _, count in rows), "runtime recovery exceeded configured bound")
                s.record({"status": "passed", "scenarios": [9], "boundary": "after-real-receipt", "dispatch": counts, "handoff": final})
            else:
                failed = app.wait(job, "failed")
                check(failed["error"]["code"] == "outcome_unknown", "unanswered dispatch was not outcome_unknown")
                check(not any(event["path"].endswith("/recover") for event in s.http.events), "unknown model outcome was automatically recovered")
                expect(app.retry(job), 409)
                check(all(count == 1 for rows in s.scenario.dispatch_counts().values() for _, count in rows), "unknown outcome redispatched")
                s.record({"status": "passed", "scenarios": [9], "boundary": "before-real-receipt", "jobId": job, "errorCode": failed["error"]["code"], "adminRetryRefused": True})
    with stack(args, "09-ai-service-restart", fault_service="extraction-claim") as s:
        app = s.start()
        job = expect(app.create(), 202)["job"]["id"]
        wait_for(lambda: s.scenario.service.process.poll() is not None, 45, "AI service killed after actual in-flight dispatch claim")
        check(s.scenario.service.process.returncode < 0, "service did not die at actual in-flight boundary")
        app.close(kill=True)
        counts_before = s.scenario.dispatch_counts()
        check(len(counts_before["extraction"]) == 1 and counts_before["extraction"][0][1] == 1, "service crash missed first actual dispatch")
        s.fault_service = None
        service = s.start_ai()
        unit = s.units()[0]
        restarted = service.estatus(unit["s2_job_id"]).json()
        check(restarted["dispatch"]["lastOutcome"] == "service_restarted", "actual AI startup did not reconcile in-flight dispatch")
        expire_owned_lease(s, job)
        app = s.start()
        final = s.assert_handoff(app.wait(job))
        check(all(count <= 3 for rows in s.scenario.dispatch_counts().values() for _, count in rows), "AI restart caused unbounded dispatch")
        s.record({"status": "passed", "scenarios": [9], "actualInFlightServiceRestart": True, "dispatchBefore": counts_before, "handoff": final})


def cancellations(args):
    with stack(args, "10-queued-cancel") as s:
        s.start(enabled=False).close()
        barrier = s.claim_barrier()
        app = s.start()
        job = expect(app.create(), 202)["job"]["id"]
        cancelled = expect(app.cancel(job, "cancel-queued"), 200)
        check(cancelled["status"] == "cancelled", "queued cancel did not settle synchronously")
        check(expect(app.cancel(job, "cancel-queued"), 200) == cancelled, "cancel historical response changed")
        s.release(barrier)
        time.sleep(.3)
        check(not s.http.events and s.scenario.usage() == {"plans": 0, "units": 0}, "queued cancellation sent AI request")
        s.record({"status": "passed", "scenarios": [10], "queuedCancelZeroAI": True, "jobId": job})
    with stack(args, "10-running-cancel-response-loss", hold_pipeline=True) as s:
        app = s.start()
        job = expect(app.create(), 202)["job"]["id"]
        wait_for(lambda: bool(s.units()) and s.units()[0]["s2_checkpoint"]["acceptedObservedAt"], 45, "real S2 acceptance before running cancellation")
        unit = s.units()[0]
        lost = s.http.arm("POST", "/" + unit["s2_job_id"] + "/cancel", drop=True)
        try:
            requested = expect(app.cancel(job), 200)
            check(requested["status"] == "running" and requested["cancelRequested"], "running cancel did not remain a worker request")
            check(lost.entered.wait(30), "real child cancel reply never reached loss barrier")
            app.close(kill=True)
        finally:
            lost.release.set()
        expire_owned_lease(s, job)
        app = s.start()
        cancelled = app.wait(job, "cancelled")
        expect(app.retry(job), 409)
        check(not any(event["method"] == "POST" and event["path"] == S3 for event in s.http.events), "cancellation dispatched new S3")
        check(len(s.scenario.dispatch_counts()["extraction"]) == 1, "cancellation dispatched later units")
        check(s.scenario.service.estatus(unit["s2_job_id"]).json()["state"] == "cancelled", "terminal child cancel not reconciled")
        s.record({"status": "passed", "scenarios": [10], "cancelReplyLostAfterRealProcessing": True, "jobId": job,
                  "retryCode": cancelled["retry"]["code"], "providerStoppedClaimed": False})
    with stack(args, "10-ready-child-not-withdrawn") as s:
        app = s.start()
        job, admitted, manifest = admission_hold(s, app)
        unit = manifest["units"][0]
        result = s.http.arm("GET", "/" + unit["extractionSubmit"]["jobId"] + "/result")
        admitted.release.set()
        try:
            check(result.entered.wait(45), "ready S2 result barrier not reached")
            os.kill(app.process.pid, signal.SIGSTOP)
            other = s.start(enabled=False)
            expect(other.cancel(job), 200)
            other.close()
            expire_owned_lease(s, job)
            other = s.start()
            other.wait(job, "cancelled")
            frozen = s.job_row(job)
            result.release.set()
            os.kill(app.process.pid, signal.SIGCONT)
            time.sleep(.5)
            check(s.job_row(job) == frozen, "late stale result overwrote cancelled terminal summary")
        finally:
            result.release.set()
            with contextlib.suppress(ProcessLookupError):
                os.kill(app.process.pid, signal.SIGCONT)
        status = s.scenario.service.estatus(unit["extractionSubmit"]["jobId"]).json()
        check(status["state"] == "ready", "cancel withdrew already READY child")
        check(not any(event["method"] == "POST" and event["path"] == S3 for event in s.http.events), "cancel after READY sent new S3")
        s.record({"status": "passed", "scenarios": [10], "readyChildPreserved": True, "jobId": job})
    with stack(args, "10-unresolved-cancel", hold_pipeline=True) as s:
        app = s.start(deadline="15s", max_failures=2)
        job = expect(app.create(), 202)["job"]["id"]
        wait_for(lambda: bool(s.units()) and s.units()[0]["s2_checkpoint"]["acceptedObservedAt"], 45, "S2 acceptance")
        unit = s.units()[0]
        lost = s.http.arm("POST", "/" + unit["s2_job_id"] + "/cancel", drop=True)
        # The real cancel commits first; all later observations become unavailable.
        # That is an issued mutation with an unresolved response, not a no-send read.
        try:
            expect(app.cancel(job), 200)
            check(lost.entered.wait(15), "unresolved-cancel fault missed actual upstream cancellation")
            s.scenario.service.process.send_signal(signal.SIGSTOP)
            lost.release.set()
            cancelled = app.wait(job, "cancelled", 45)
            check(cancelled["error"]["code"] == "outcome_unknown", "unresolved cancellation falsely claimed definite stop")
            expect(app.retry(job), 409)
        finally:
            lost.release.set()
            s.scenario.service.process.send_signal(signal.SIGCONT)
        s.record({"status": "passed", "scenarios": [10], "jobId": job, "unresolvedCancellation": "outcome_unknown", "providerStoppedClaimed": False})


def retry_continuation(args):
    with stack(args, "11-retry-fixed-plan-continuation") as s:
        app = s.start(max_failures=2)
        job, admitted, manifest = admission_hold(s, app)
        second_id = manifest["units"][1]["extractionSubmit"]["jobId"]
        second = s.http.arm("GET", "/" + second_id, before=True)
        admitted.release.set()
        try:
            check(second.entered.wait(60), "second-unit read barrier not reached")
            first_before = s.units()[0]
            check(first_before["s2_checkpoint"]["state"] == first_before["s3_checkpoint"]["state"] == "result_observed", "first unit was not durably completed")
            s.scenario.service.kill()
        finally:
            second.release.set()
        failed = app.wait(job, "failed")
        check(failed["retry"]["allowed"], "known read/no-send transient did not allow app continuation")
        old_summary = failed["planRun"]
        units_before = s.units()
        quota_before = {"plans": 1, "units": 2}
        s.start_ai()
        check(s.scenario.usage() == quota_before, "AI restart changed cumulative quota")
        retried = expect(app.retry(job, "continuation-retry"), 202)
        continuation = retried["job"]["id"]
        check(continuation != job and retried["job"]["retryOf"] == job and retried["job"]["kind"] == "analyze_plan",
              "retry did not create a bound new app attempt")
        final = s.assert_handoff(app.wait(continuation))
        check(s.units()[0] == first_before, "retry changed completed unit observations")
        check([(u["s2_job_id"], u["s3_job_id"], u["s2_submit"], u["s3_submit"]) for u in s.units()]
              == [(u["s2_job_id"], u["s3_job_id"], u["s2_submit"], u["s3_submit"]) for u in units_before], "retry minted replacement AI identity")
        check(app.get(job)["planRun"] == old_summary, "retry rewrote old terminal summary")
        check(expect(app.retry(job, "continuation-retry"), 202) == retried, "historical retry receipt changed after continuation")
        check(s.scenario.usage() == quota_before and all(count == 1 for rows in s.scenario.dispatch_counts().values() for _, count in rows),
              "continuation debited quota or repeated initial execution")
        fresh = expect(app.create(1), 202)["job"]["id"]
        s.assert_handoff(app.wait(fresh), 1)
        check(s.scenario.usage() == {"plans": 2, "units": 4}, "independently produced second plan did not create distinct execution")
        s.record({"status": "passed", "scenarios": [11], "priorJobId": job, "continuation": final, "newIndependentJobId": fresh})


def authority_revocation(args):
    with stack(args, "12-terminal-policy-retirement") as s:
        app = s.start()
        job, admitted, manifest = admission_hold(s, app)
        s3 = s.http.arm("POST", S3, before=True)
        admitted.release.set()
        try:
            check(s3.entered.wait(60), "between-S2/S3 policy barrier not reached")
            check(s.units()[0]["s2_checkpoint"]["state"] == "result_observed", "policy retirement was not between stages")
            policy = s.scenario.policy(max_plans=3, max_units=6)
            s.scenario.install_policy(DISABLED, "retire-synthetic-policy")
        finally:
            s3.release.set()
        failed = app.wait(job, "failed")
        check(not s.scenario.dispatch_counts()["relation"], "retired policy dispatched S3")
        s.scenario.install_policy(policy, "restore-identical-policy")
        historical = s.scenario.status(s.scenario.references[0]).json()
        check(historical["authority"]["state"] == "inactive", "old policy bytes revived admission")
        saved_before_retry = s.db.json(
            "SELECT jsonb_build_object('admissionId',admission_id,'manifestDigest',manifest_digest,"
            "'lastAuthorityState',last_authority_state,'lastAuthorityReason',last_authority_reason,"
            "'lastAdmissionCode',last_admission_code) FROM analysis_plans WHERE plan_id=" + quoted(s.plan()))
        units_before_retry = s.units()
        retry = app.retry(job)
        retry_body = retry.json()
        (s.evidence / "authority-retry-boundary.json").write_text(canonical({
            "jobId": job,
            "failedJobStatus": failed["status"],
            "failedJobErrorCode": (failed.get("error") or {}).get("code"),
            "failedJobRetry": {key: failed["retry"].get(key) for key in ("allowed", "code", "blockedBy")},
            "appAdmissionBeforeRetry": saved_before_retry,
            "directAiHistoricalAuthority": historical["authority"],
            "directAiAdmissionId": historical["admissionId"],
            "directAiPolicyRevision": historical["policyRevision"],
            "retryHttpStatus": retry.status_code,
            "retryErrorCode": (retry_body.get("error") or {}).get("code"),
            "retryAcceptedJobId": (retry_body.get("job") or {}).get("id"),
            "unitStatesBeforeRetry": [{"ordinal": unit["ordinal"], "s2": unit["s2_checkpoint"]["state"],
                            "s3": unit["s3_checkpoint"]["state"],
                            "s3FailureCategory": unit["s3_checkpoint"]["failureCategory"],
                            "s3FailureCode": unit["s3_checkpoint"]["failureCode"]} for unit in units_before_retry],
        }) + "\n")
        expect(retry, 409)
        check(s.scenario.usage() == {"plans": 1, "units": 2}, "policy replacement regranted or reset quota")
        s.record({"status": "passed", "scenarios": [12], "jobId": job, "retiredAdmissionRemainsInactive": True})
    for boundary in ("admission", "dispatch", "result"):
        with stack(args, "12-source-rights-" + boundary, hold_pipeline=boundary == "dispatch") as s:
            app = s.start()
            if boundary == "admission":
                s.scenario.workspace.revoke_source(False)
                job = expect(app.create(), 202)["job"]["id"]
            elif boundary == "dispatch":
                job = expect(app.create(), 202)["job"]["id"]
                wait_for(lambda: bool(s.units()) and s.units()[0]["s2_checkpoint"]["acceptedObservedAt"], 45, "accepted S2 prior to source dispatch revocation")
                s.scenario.workspace.revoke_source(False)
                s.scenario.workspace.go()
            else:
                job, admitted, manifest = admission_hold(s, app)
                result = s.http.arm("GET", "/" + manifest["units"][0]["extractionSubmit"]["jobId"] + "/result", before=True)
                admitted.release.set()
                try:
                    check(result.entered.wait(45), "result-delivery rights boundary not reached")
                    s.scenario.workspace.revoke_source(False)
                finally:
                    result.release.set()
            failed = app.wait(job, "failed")
            check(all(row["s2_checkpoint"]["state"] != "result_observed" for row in s.units()), "revoked source fabricated deliverable observation")
            if boundary == "admission":
                check(s.scenario.usage() == {"plans": 0, "units": 0}, "source-refused admission charged quota")
            else:
                unit = s.units()[0]
                status = s.scenario.service.estatus(unit["s2_job_id"])
                check(status.status_code == 200 and status.json()["delivery"]["state"] == "withheld", "revocation hid content-free status or exposed content")
                cancel = s.scenario.service.ecancel(unit["s2_job_id"])
                check(cancel.status_code in (200, 409), "content-free cancel unavailable after rights revocation")
            s.scenario.workspace.revoke_source(True)
            s.record({"status": "passed", "scenarios": [12], "sourceRevokedAt": boundary, "jobId": job, "errorCode": failed["error"]["code"]})


def binding_negatives(args):
    cases = ("s2-input", "s2-approval", "s3-upstream", "s3-provenance", "s3-pinned-result", "malformed-success")
    for case in cases:
        with stack(args, "13-altered-response-" + case) as s:
            app = s.start()
            job, admitted, manifest = admission_hold(s, app)
            first = manifest["units"][0]
            s2_id, s3_id = first["extractionSubmit"]["jobId"], first["relationSubmit"]["jobId"]

            def transform(body):
                target = body["status"] if "status" in body else body
                if case == "s2-input":
                    target["inputDigest"] = "0" * 64
                elif case == "s2-approval":
                    target["approval"]["approvedRequestDigest"] = "0" * 64
                elif case == "s3-upstream":
                    target["upstream"]["inputDigest"] = "0" * 64
                elif case == "s3-provenance":
                    target["provenance"]["executionMode"] = "live"
                    target["provenance"]["recordingKind"] = "provider"
                elif case == "s3-pinned-result":
                    target["inputDigest"] = "0" * 64
                    body["job"]["inputDigest"] = "0" * 64
                    for relation in body["job"]["relations"]:
                        relation["sourceVersion"] = "0" * 64
                else:
                    target.pop("inputDigest")
                return body

            family = S2 if case.startswith("s2-") or case == "malformed-success" else S3
            suffix = "/" + s3_id + "/result" if case == "s3-pinned-result" else family
            method = "GET" if case == "s3-pinned-result" else "POST"
            fault = s.http.arm(method, suffix, transform=transform, repeat=True)
            fault.release.set()
            if case != "s3-pinned-result":
                status_id = s2_id if family == S2 else s3_id
                status_fault = s.http.arm("GET", "/" + status_id, transform=transform, repeat=True)
                status_fault.release.set()
            admitted.release.set()
            failed = app.wait(job, "failed")
            check(fault.transformed > 0, "altered-response case did not transform its selected real successful envelope")
            units = s.units()
            check(units[0]["s3_checkpoint"]["state"] != "result_observed", "altered binding settled a handoff")
            if family == S2:
                check(not s.scenario.dispatch_counts()["relation"], "S2 binding fault dispatched downstream S3")
            check(len(s.scenario.dispatch_counts()["extraction"]) == 1, "binding failure advanced to later unit")
            s.record({"status": "passed", "scenarios": [13], "caseKind": "altered-real-transport-response", "fault": case,
                      "jobId": job, "errorCode": failed["error"]["code"], "notUnmodifiedServiceSuccess": True})


def history_and_storage(args):
    with stack(args, "14-forward-migration-history", legacy=True) as s:
        app = s.start()
        check(s.db.sql("SELECT count(*) FROM flyway_schema_history WHERE version=" + quoted(NEW_MIGRATION) + " AND success") == "1",
              "new forward migration not applied by real Spring jar")
        before = app.list()
        job = expect(app.create(), 202)["job"]["id"]
        final = s.assert_handoff(app.wait(job))
        s.assert_legacy_history_unchanged("forward migration/worker changed legacy job rows")
        check(s.db.json("SELECT jsonb_agg(to_jsonb(t) ORDER BY id) FROM review_targets t") == s.review_before, "migration/worker rewrote legacy review")
        legacy = app.get("job-legacy-ingest")
        check("planRun" not in legacy and legacy["kind"] == "ingest", "legacy output gained analysis meaning")
        check(app.list()["ingest"] == before["ingest"] and before["ingest"]["jobId"] == "job-legacy-ingest", "analysis advanced collection baseline")
        counts = s.counts()
        expect(app.retry("job-legacy-failed"), 409)
        check(s.counts() == counts, "unsupported retry inserted inert job/idempotency/audit")
        # Existing synthetic rows are used only to exercise DB guards inside
        # ROLLBACK transactions; positive queue entry remains the HTTP POST above.
        guards = [
            "UPDATE analysis_jobs SET plan_id=" + quoted(s.plan()) + " WHERE id='job-legacy-ingest'",
            "UPDATE analysis_jobs SET kind='analyze_plan' WHERE id='job-legacy-internal'",
            "UPDATE analysis_jobs SET status='running',finished_at=NULL WHERE id=" + quoted(job),
            "UPDATE analysis_plans SET plan_digest=repeat('0',64) WHERE plan_id=" + quoted(s.plan()),
            "DELETE FROM analysis_plan_units WHERE plan_id=" + quoted(s.plan()),
            "UPDATE analysis_plan_units SET s3_input_digest=repeat('0',64) WHERE plan_id=" + quoted(s.plan()),
        ]
        for statement in guards:
            check(s.db.sql("BEGIN;" + statement + ";ROLLBACK;", tolerate=True) is None, "immutable identity/terminal/schema guard accepted invalid mutation")
        rows = s.db.json("SELECT jsonb_build_object('plans',(SELECT jsonb_agg(to_jsonb(p)) FROM analysis_plans p),"
                         "'units',(SELECT jsonb_agg(to_jsonb(u)) FROM analysis_plan_units u),"
                         "'jobs',(SELECT jsonb_agg(to_jsonb(j)) FROM analysis_jobs j WHERE kind='analyze_plan'))")
        serialized = canonical(rows)
        for marker in ("합성 큐 표본", "배터리 부품을 공급한다", "authored producer reason", '"quotes":', '"eventCandidates":', '"relations":'):
            check(marker not in serialized, "app queue persisted raw source/model payload")
        check(s.protected_snapshot() == s.protected, "review/graph/accounting/publication domain mutated")
        s.record({"status": "passed", "scenarios": [14], "oldMigration": OLD_MIGRATION, "newMigration": NEW_MIGRATION,
                  "legacyFixturesPreserved": True, "noPayloadOrDomainWrites": True, "handoff": final})


def serve_ui(args):
    bootstrap = args.output / "bootstrap.json"
    controls = args.output / "controls"
    controls.mkdir(mode=0o700)
    try:
        with stack(args, "15-ui-fixture") as s:
            # The first JVM performs real forward migrations only. No legacy SQL
            # fixture and no public create is performed by this serving mode.
            s.start(enabled=False).close()
            barrier = s.claim_barrier()
            stage = None
            suffixes = {"admission": ADMISSION, "s2": S2, "s3": S3}
            if args.ui_hold_stage != "none":
                stage = s.http.arm("POST", suffixes[args.ui_hold_stage], before=True)
            app = s.start(deadline="10m", request_timeout="30s", lease="65s")
            check(s.counts() == {"jobs": 0, "plans": 0, "units": 0, "idempotency": 0, "createAudit": 0},
                  "UI fixture created queue rows before browser public POST")
            check(not s.http.events, "UI fixture called AI before browser public POST")
            references = []
            for index, ref in enumerate(s.scenario.references):
                path = args.output / f"synthetic-plan-reference-{index}.json"
                private_json(path, {key: ref[key] for key in ("planId", "planDigest")})
                references.append(str(path))
            private_json(bootstrap, {
                "schemaVersion": "zoop-analyze-plan-ui-fixture-1",
                "syntheticOnly": True, "apiUrl": app.url, "uiOrigin": s.origin,
                "webEnv": {"ZOOP_DEV_API_TARGET": app.url},
                "login": {"email": s.email, "password": s.password},
                "planReferenceFiles": references, "pid": os.getpid(),
                "stop": {"signal": "SIGTERM", "pid": os.getpid()},
                "controls": {"releaseClaimFile": str(controls / "release-claim"),
                             "releaseStageFile": str(controls / "release-stage"),
                             "holdStageFile": str(controls / "hold-stage.json"),
                             "restartBackendFile": str(controls / "restart-backend"),
                             "statusFile": str(controls / "status.json"),
                             "initialStage": args.ui_hold_stage, "maxStageHoldSeconds": 90},
                "notes": ["No plan/job exists until browser public POST.",
                          "Create release-claim to let the real scheduler claim queued work.",
                          "Create release-stage to forward the blocked actual AI request.",
                          "To arm another stage write {stage:admission|s2|s3} to hold-stage.json before the request.",
                          "Create restart-backend to kill/restart the actual JVM on the same API port; DB/AI IDs persist.",
                          "Cancellation does not promise provider stop/refund; no publication occurs."]})
            print(canonical({"status": "ready", "mode": "actual-ui-fixture", "apiUrl": app.url,
                             "bootstrapFile": str(bootstrap), "controlDirectory": str(controls), "pid": os.getpid(),
                             "queueRowsBeforeBrowserPost": 0}), flush=True)
            deadline = time.monotonic() + args.ui_timeout
            restarts = 0
            while time.monotonic() < deadline:
                check(app.process.poll() is None, "owned UI Spring backend exited")
                check(s.scenario.service.process.poll() is None, "owned UI AI service exited")
                if (controls / "release-claim").exists() and barrier:
                    s.release(barrier)
                    barrier = None
                if (controls / "release-stage").exists():
                    if stage:
                        stage.release.set()
                    (controls / "release-stage").unlink()
                arm = controls / "hold-stage.json"
                if arm.exists():
                    request = json.loads(arm.read_bytes())
                    check(set(request) == {"stage"} and request["stage"] in suffixes, "invalid test-owned stage control")
                    check(stage is None or stage.release.is_set(), "prior held stage must be released before arming another")
                    stage = s.http.arm("POST", suffixes[request["stage"]], before=True)
                    arm.unlink()
                restart = controls / "restart-backend"
                if restart.exists():
                    port = app.port
                    app.close(kill=True)
                    running = s.db.json("SELECT coalesce(jsonb_agg(id),'[]') FROM analysis_jobs WHERE scope='admin' AND status='running'")
                    for job in running:
                        expire_owned_lease(s, job)
                    app = s.start(deadline="10m", request_timeout="30s", lease="65s", port=port)
                    restarts += 1
                    restart.unlink()
                status = {"claimHeld": barrier is not None, "stageEntered": bool(stage and stage.entered.is_set()),
                          "stageReleased": bool(stage and stage.release.is_set()),
                          "queue": s.counts(), "quota": s.scenario.usage(), "backendRestarts": restarts, "providerCalls": 0}
                temporary = controls / "status.tmp"
                temporary.write_text(canonical(status) + "\n")
                temporary.replace(controls / "status.json")
                time.sleep(.2)
            raise TimeoutError("UI fixture reached its explicit maximum lifetime")
    except Interrupted:
        return 0
    finally:
        bootstrap.unlink(missing_ok=True)


SCENARIOS = [
    ("durable-two-plans", durable_two_plans),
    ("dedup-validation", dedup_and_validation),
    ("reply-losses", reply_losses),
    ("commit-boundaries", commit_boundaries),
    ("stale-owner", stale_owner),
    ("runtime-restarts", runtime_restarts),
    ("cancellations", cancellations),
    ("retry-continuation", retry_continuation),
    ("authority-revocation", authority_revocation),
    ("binding-negatives", binding_negatives),
    ("history-storage", history_and_storage),
]
BROWSER_CHECKS = {"publicCreate", "acceptedAnalysisHandoff", "refresh", "appRestart", "duplicate",
                  "blockedRetry", "noPublicationMeaning", "dashboardLabel", "legacyCollectionBaseline"}


def browser_evidence(path):
    evidence = json.loads(path.read_bytes())
    check(evidence.get("schemaVersion") == "zoop-analyze-plan-browser-proof-1" and evidence.get("status") == "passed",
          "Main browser evidence is not a completed actual UI proof")
    check(BROWSER_CHECKS <= {key for key, value in evidence.get("checks", {}).items() if value is True},
          "Main browser evidence omits a required scenario15 observation")
    artifacts = evidence.get("artifactPaths", [])
    check(artifacts and all(Path(item).is_file() for item in artifacts), "Main browser evidence artifacts are missing")
    return {"scenario": 15, "status": "passed", "owner": "Main", "evidencePath": str(path),
            "evidenceSha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jar", type=Path, default=ROOT / "api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar")
    parser.add_argument("--output", type=Path, required=True, help="fresh external evidence directory (must not exist)")
    parser.add_argument("--java", default=shutil.which("java"), help="JDK21+ java executable")
    parser.add_argument("--postgres-bin", type=Path, help="cached local PostgreSQL bin directory; default uses cached Docker image")
    parser.add_argument("--image", default="postgres:16.13-alpine")
    parser.add_argument("--serve-ui", action="store_true")
    parser.add_argument("--ui-origin", help="exact http(s) loopback web origin; required for --serve-ui")
    parser.add_argument("--ui-hold-stage", choices=("none", "admission", "s2", "s3"), default="s2")
    parser.add_argument("--ui-timeout", type=float, default=1800, help="bounded fixture lifetime in seconds, 60..14400")
    parser.add_argument("--ui-proof", type=Path, help="Main's already-observed content-free scenario15 browser evidence")
    parser.add_argument("--only", choices=[name for name, _ in SCENARIOS], help="focused rerun; explicitly incomplete, never all-scenario pass")
    args = parser.parse_args()
    args.jar = args.jar.resolve()
    args.output = args.output.resolve()
    check(args.jar.is_file(), "prerequisite bootJar is absent; Main must build current source first")
    check(args.java and Path(args.java).is_file(), "prerequisite JDK java executable is absent")
    check(not args.output.exists() and not args.output.is_relative_to(ROOT), "output must be fresh and outside the worktree")
    check(60 <= args.ui_timeout <= 14400, "UI fixture lifetime must be finite, 60..14400 seconds")
    if args.serve_ui:
        check(args.ui_origin, "--serve-ui requires Main's exact --ui-origin")
    if args.ui_origin:
        origin = urlsplit(args.ui_origin)
        check(origin.scheme in ("http", "https") and origin.hostname in ("127.0.0.1", "localhost", "::1")
              and origin.port and origin.username is None and origin.password is None and origin.path in ("", "/")
              and not origin.query and not origin.fragment, "UI origin must be an exact loopback origin with explicit port")
        args.ui_origin = args.ui_origin.rstrip("/")
    for path in (ROOT / "ai/pipeline/.venv/bin/python", ROOT / "ai/pipeline/.venv/bin/zoop-ai-extract",
                 ROOT / "ai/pipeline/.venv/bin/zoop-ai-relation", ROOT / "ai/pipeline/.venv/bin/zoop-ai-ingest"):
        check(path.is_file() and os.access(path, os.X_OK), "missing installed owned pipeline prerequisite: " + str(path))
    args.output.mkdir(mode=0o700)
    return args


def main():
    os.umask(0o077)
    args = arguments()
    def interrupted(*_):
        raise Interrupted()
    for name in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(name, interrupted)
    if args.serve_ui:
        return serve_ui(args)
    results = []
    report = {"schemaVersion": "zoop-analyze-plan-queue-proof-1", "status": "running", "providerCalls": None,
              "sourceRoot": str(ROOT), "jar": str(args.jar), "jarSha256": hashlib.sha256(args.jar.read_bytes()).hexdigest(),
              "servicePython": sys.executable, "pipelinePython": str(ROOT / "ai/pipeline/.venv/bin/python"),
              "pythonVersion": sys.version.split()[0], "results": results, "executedBy": "Main-assigned CLI"}
    version = subprocess.run([args.java, "-version"], capture_output=True, timeout=15)
    check(version.returncode == 0, "JDK prerequisite failed to start")
    report["javaVersion"] = (version.stdout + version.stderr).decode().splitlines()[0]
    destination = args.output / "report.json"
    try:
        for name, scenario in SCENARIOS:
            if args.only and name != args.only:
                continue
            scenario(args)
            results.append({"group": name, "status": "passed"})
            destination.write_text(canonical(report) + "\n")
        covered = set()
        for path in args.output.glob("*/observations.json"):
            covered.update(json.loads(path.read_bytes()).get("scenarios", []))
        report["providerCalls"] = 0
        report["observedScenarios"] = sorted(covered)
        if args.ui_proof:
            results.append(browser_evidence(args.ui_proof.resolve()))
            covered.add(15)
        else:
            results.append({"scenario": 15, "status": "external_required", "owner": "Main",
                            "reason": "Actual browser consumer proof must be run separately with --serve-ui; no fake pass."})
        report["observedScenarios"] = sorted(covered)
        if covered == set(range(1, 16)) and not args.only:
            report["status"] = "passed"
            code = 0
        else:
            report["status"] = "inconclusive"
            report["unobservedScenarios"] = sorted(set(range(1, 16)) - covered)
            code = 2
    except Interrupted:
        report["status"] = "interrupted"
        code = 130
    except BaseException as error:
        report["status"] = "failed"
        # All assertion messages above are content-free. Unexpected exception text
        # can contain subprocess environments/response text and is never emitted.
        report["failure"] = {"type": type(error).__name__}
        if isinstance(error, (AssertionError, TimeoutError)):
            report["failure"]["message"] = str(error)
        code = 1
    destination.write_text(canonical(report) + "\n")
    print(canonical({"status": report["status"], "report": str(destination), "observedScenarios": report.get("observedScenarios", []),
                     "providerCalls": 0 if report["status"] in ("passed", "inconclusive") else None}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
