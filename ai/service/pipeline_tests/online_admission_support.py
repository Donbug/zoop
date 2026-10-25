"""Private real-process online-admission fixtures, shared by smoke and integration tests.

All filesystem writes are under the supplied owned root/evidence directories. There
are no pipeline imports in this service-interpreter module and no inherited keys,
live gates, source registries, budgets or application state.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

from extraction_support import ExtractionService, ExtractionWorkspace, make_service, terminate_extraction
from relation_support import PIPELINE, PIPELINE_PYTHON, canonical, terminate_relation, tree, wait_for

BUILD = Path(__file__).with_name("build_online_admission_world.py")
POLICY_PATH = "/internal/v1/plan-admission-policy"
ADMISSION_PATH = "/internal/v1/plan-admissions"
DISABLED = {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": False}

# sitecustomize installs the same denial in every Python descendant, even when a
# pipeline fixture helper supplies its own minimal child environment.
GUARD = '''import os, subprocess, sys
ROOT = __ROOT__
GUARD_DIR = __GUARD_DIR__
def deny_network(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.bind", "socket.sendto"}:
        with open(os.path.join(ROOT, "network-attempt"), "a") as handle:
            handle.write(event + "\\n")
        raise RuntimeError("synthetic pipeline network denied")
sys.addaudithook(deny_network)
_original_init = subprocess.Popen.__init__
def guarded_init(self, *args, **kwargs):
    env = dict(kwargs.get("env") or os.environ)
    env["PYTHONPATH"] = GUARD_DIR
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    kwargs["env"] = env
    _original_init(self, *args, **kwargs)
subprocess.Popen.__init__ = guarded_init
'''

WRAPPER = '''#!__PYTHON__
import os, runpy, sys, time
sys.path.insert(0, __GUARD_DIR__)
import sitecustomize
ROOT = __ROOT__
command = sys.argv[1] if len(sys.argv) > 1 else ""
with open(os.path.join(ROOT, __COMMAND_LOG__), "a") as handle:
    handle.write(command + "\\n")
if command == "verify-plan" and os.path.exists(os.path.join(ROOT, "pause-verify")):
    open(os.path.join(ROOT, "verify-entered"), "w").close()
    deadline = time.monotonic() + 90
    while not os.path.exists(os.path.join(ROOT, "verify-go")):
        if time.monotonic() >= deadline:
            raise RuntimeError("test verifier release timed out")
        time.sleep(0.025)
if command == "resume":
    family = "s2" if __MODULE__.endswith("extraction_cli") else "s3"
    receipt = os.path.join(ROOT, "crash-" + family + "-receipt")
    unknown = os.path.join(ROOT, "crash-" + family + "-unknown")
    if os.path.exists(receipt) or os.path.exists(unknown):
        if family == "s2":
            from zoop_ai_pipeline.extraction import Extractor as Engine
        else:
            from zoop_ai_pipeline.relation import Engine
        if os.path.exists(unknown):
            os.unlink(unknown)
            Engine._receive = lambda *args: os._exit(75)
        else:
            os.unlink(receipt)
            actual_receive = Engine._receive
            def receive(self, *args, **kwargs):
                actual_receive(self, *args, **kwargs)
                os._exit(75)
            Engine._receive = receive
runpy.run_module(__MODULE__, run_name="__main__")
'''


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class OnlineScenario:
    def __init__(self, root: Path, evidence: Path):
        self.root, self.evidence = root.resolve(), evidence.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.guard = self.root / "network-guard"
        self.guard.mkdir()
        (self.guard / "sitecustomize.py").write_text(GUARD.replace("__ROOT__", repr(str(self.root))).replace("__GUARD_DIR__", repr(str(self.guard))))
        self.plan_root = self.root / "plans"
        self.services: list[ExtractionService] = []
        self.steps = []
        self.closed = False

    def record(self, label: str, result: dict):
        self.steps.append({"step": label, **result})
        (self.evidence / "steps.json").write_text(canonical(self.steps) + "\n")

    def prepare(self):
        env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(self.guard), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1",
               "ZOOP_STATE_DIR": str(self.root / "builder-app"), "ZOOP_AI_WORKER_STATE_DIR": str(self.root / "builder-worker")}
        done = subprocess.run([str(PIPELINE_PYTHON), str(BUILD), str(PIPELINE), str(self.root / "world"), str(self.plan_root)],
                              env=env, capture_output=True, timeout=600)
        (self.evidence / "fixture-build.stderr").write_bytes(done.stderr)
        check(done.returncode == 0 and not done.stderr, "synthetic fixture build failed; inspect retained fixture-build.stderr")
        self.info = json.loads(done.stdout)
        check(self.info["providerCalls"] == 0, "fixture builder used providers")
        self.references = self.info["references"]
        world = SimpleNamespace(root=Path(self.info["root"]), ingestion=Path(self.info["ingestion"]), extraction=Path(self.info["extraction"]),
                                registry=Path(self.info["registry"]), producer=Path(self.info["producer"]), verifier=Path(self.info["verifier"]),
                                s2_replay=Path(self.info["s2Replay"]), s2_topic=Path(self.info["s2Topic"]), s2_request=self.info["s2Request"],
                                s2_plain_request=self.info["s2Request"], upstream={"jobId": "unused", "inputDigest": "0" * 64}, source_texts=[])
        self.world = world
        self.workspace = ExtractionWorkspace(self.root / "workspace", world, chain=True, topic=False, requests=())
        credentials = self.workspace.credentials
        credentials.scopes["alpha"] += ["plan.admit", "plan.read"]
        credentials.scopes["beta"] += ["plan.admit", "plan.read"]
        credentials.tokens["operator"] = "t" + secrets.token_urlsafe(36)
        credentials.scopes["operator"] = ["plan.policy"]
        for module, attribute, log in (("extraction_cli", "s2_command", "s2-commands"), ("relation_cli", "command", "s3-commands")):
            path = self.workspace.root / ("extract-wrapper.py" if module == "extraction_cli" else "relation-wrapper.py")
            path.write_text(WRAPPER.replace("__PYTHON__", str(PIPELINE_PYTHON)).replace("__GUARD_DIR__", repr(str(self.guard)))
                            .replace("__ROOT__", repr(str(self.root))).replace("__COMMAND_LOG__", repr(log))
                            .replace("__MODULE__", repr("zoop_ai_pipeline." + module)))
            path.chmod(0o755)
            setattr(self.workspace, attribute, path)
        self.original_world = {"ingestion": tree(world.ingestion), "extraction": tree(world.extraction)}
        self.original_manual = (self.workspace.approvals.read_bytes(), self.workspace.upstreams.read_bytes())
        self.record("fresh-completed-rounds", {"rounds": len(self.references), "distinctPlans": len({r["planId"] for r in self.references}), "providerCalls": 0})
        return self

    def policy(self, *, max_plans=3, max_units=3):
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        return {**self.info["policy"], "expiresAt": expiry, "limits": {"maxPlans": max_plans, "maxUnits": max_units}}

    def env(self, *, online=True):
        env = self.workspace.env(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        if online:
            env.update(ZOOP_AI_SERVICE_PLAN_ADMISSION="1", ZOOP_AI_SERVICE_PLAN_ROOT=str(self.plan_root))
            env.pop("ZOOP_AI_SERVICE_EXTRACTION_APPROVALS", None)
            env.pop("ZOOP_AI_SERVICE_RELATION_UPSTREAMS", None)
        return env

    def start(self, *, online=True, hold=False, wait=True, fault=None):
        service = make_service(self.workspace, env=self.env(online=online), launcher=hold,
                               launcher_env={"ZOOP_TEST_EXTRACTION_HOLD_FILE": str(self.workspace.root / "extract-go")} if hold else None)
        service._runs = len(self.services)
        if fault is not None:
            service._argv = [sys.executable, str(Path(__file__).with_name("online_admission_launcher.py")), fault, str(self.root)]
        service.client.close()
        service.client = httpx.Client(base_url=f"http://127.0.0.1:{self.workspace.port}", timeout=60, trust_env=False)
        self.services.append(service)
        self.service = service.start(wait=wait)
        return self.service

    def admit(self, reference, *, as_="alpha"):
        return self.service.request("POST", ADMISSION_PATH, as_=as_, body=reference, key=reference["planId"])

    def status(self, reference, *, as_="alpha"):
        return self.service.request("GET", f'{ADMISSION_PATH}/{reference["planId"]}?planDigest={reference["planDigest"]}', as_=as_)

    def policy_status(self):
        return self.service.request("GET", POLICY_PATH, as_="operator")

    def put_policy(self, body, key, etag):
        return self.service.request("PUT", POLICY_PATH, as_="operator", body=body, key=key, headers={"If-Match": etag})

    def install_policy(self, policy, key="install-policy"):
        current = self.policy_status()
        check(current.status_code == 200, "operator policy read failed")
        response = self.put_policy(policy, key, current.headers["etag"])
        check(response.status_code == 200, "synthetic policy CAS failed")
        return response

    def usage(self):
        response = self.policy_status()
        check(response.status_code == 200, "policy usage unavailable")
        return response.json()["usage"]

    def dispatch_counts(self):
        result = {}
        for family in ("extraction", "relation"):
            path = self.workspace.state / f"{family}-jobs.sqlite3"
            if not path.exists():
                result[family] = []
                continue
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
                result[family] = db.execute(f"SELECT job_id, dispatch_count FROM {family}_dispatch ORDER BY job_id").fetchall()
        return result

    def pause_verify(self):
        for marker in ("verify-entered", "verify-go"):
            (self.root / marker).unlink(missing_ok=True)
        (self.root / "pause-verify").touch()

    def wait_verify(self):
        wait_for(lambda: (self.root / "verify-entered").exists(), 30, what="real installed verifier pause")

    def release_verify(self):
        (self.root / "verify-go").touch()
        (self.root / "pause-verify").unlink(missing_ok=True)

    def close(self):
        if self.closed:
            return
        if not hasattr(self, "workspace"):
            self.closed = True
            check(not (self.root / "network-attempt").exists(), "fixture pipeline attempted network")
            return
        try:
            self.release_verify()
            for service in self.services:
                service.close()
            terminate_extraction(self.workspace)
            terminate_relation(self.workspace)
            check({"ingestion": tree(self.world.ingestion), "extraction": tree(self.world.extraction)} == self.original_world,
                  "read-only synthetic operator ledgers changed")
            check((self.workspace.approvals.read_bytes(), self.workspace.upstreams.read_bytes()) == self.original_manual,
                  "online admission changed manual authority files")
            check(not (self.root / "network-attempt").exists(), "pipeline attempted network")
            self.record("cleanup", {"childrenStopped": True, "operatorLedgersUnchanged": True, "manualAuthoritiesUnchanged": True, "networkAttempts": 0})
        finally:
            for path in self.workspace.root.glob("service-*.*"):
                shutil.copyfile(path, self.evidence / path.name)
            for name in ("s2-commands", "s3-commands", "network-attempt"):
                if (self.root / name).exists():
                    shutil.copyfile(self.root / name, self.evidence / name)
            self.closed = True
