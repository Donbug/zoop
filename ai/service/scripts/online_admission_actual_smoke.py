#!/usr/bin/env python3
"""Java -> running AI HTTP -> installed S2/S3, with bounded synthetic policy.

Prerequisites (run once before this command):
  make pipeline-install worker-install service-install
  ./api/gradlew -p api preparePlanAdmissionProof
Run with ai/service/.venv/bin/python and --java-classpath-file
api/build/plan-admission-proof-classpath.txt. No build is launched by this smoke.

Fresh complete authored ingestion rounds, exact plan directories and replay fixtures
are owned by this invocation. Every pipeline descendant denies network. Java and
Python clients use only the loopback AI service. Evidence survives state cleanup;
no policy/source grant/budget outside this synthetic workspace is opened or changed.
This is integration/authority proof, NOT model-quality evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline_tests"))

from online_admission_support import DISABLED, OnlineScenario, check
from relation_support import ROOT, canonical
from support import remove_tree
from test_online_admission import (admission_crash, controls, execution_crashes, mode_change_refused, no_operator_adoption,
                                   paused_verification, queued_policy_revocation, quota_contention, source_revocation, terminal_expiry)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def consumer(scenario, java, classpath):
    service = scenario.start()
    pid = service.process.pid
    check(scenario.policy_status().json()["status"] == "unconfigured", "actual consumer service started with policy")
    check(scenario.admit(scenario.references[0]).status_code == 409, "no-policy actual consumer admitted work")
    policy = scenario.policy(max_plans=2, max_units=2)
    scenario.install_policy(policy)
    config = scenario.root / "java-private-config.json"
    config.write_text(canonical({"baseUrl": f"http://127.0.0.1:{scenario.workspace.port}", "token": scenario.workspace.credentials.tokens["alpha"]}))
    config.chmod(0o600)
    observed = []

    def invoke(index, label):
        reference = scenario.references[index]
        selector = scenario.root / f"reference-{index}.json"
        selector.write_text(canonical(reference))
        destination = scenario.evidence / label
        destination.mkdir()
        done = subprocess.run([java, "-cp", classpath, "com.zoop.ai.PlanAdmissionProof", str(config), str(selector), str(destination)],
                              capture_output=True, timeout=600, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(scenario.root)})
        (destination / "runner.stdout").write_bytes(done.stdout)
        (destination / "runner.stderr").write_bytes(done.stderr)
        check(done.returncode == 0, f"Java consumer failed in {label}; retained runner.stderr")
        result = json.loads((destination / "result.json").read_bytes())
        check(result["planId"] == reference["planId"] and result["planDigest"] == reference["planDigest"], "Java returned another plan identity")
        check(result["providerCalls"] == 0 and len(result["units"]) == 1, "Java consumer did not consume exact zero-provider unit")
        for unit in result["units"]:
            check(unit["s2ProviderCalls"] == 0 and unit["s3ProviderCalls"] == 0
                  and unit["s2EventCandidates"] > 0 and unit["s3Candidates"] > 0,
                  "actual Java S2/S3 consumption omitted real candidate content or used providers")
        check(service.process.pid == pid and service.process.poll() is None, "service restarted during two-round consumer proof")
        scenario.record(label, {"planId": result["planId"], "admissionId": result["admissionId"], "manifestDigest": result["manifestDigest"],
                               "units": len(result["units"]), "providerCalls": 0, "sameServicePid": True})
        return result

    for index in range(2):
        observed.append(invoke(index, f"java-round-{index + 1}"))
    check(observed[0]["admissionId"] != observed[1]["admissionId"] and observed[0]["units"][0]["unitKey"] != observed[1]["units"][0]["unitKey"],
          "two distinct rounds reused admission or job identities")
    check(scenario.usage() == {"plans": 2, "units": 2}, "two-round usage did not equal two exact units")
    before = scenario.dispatch_counts()
    check(all(len(rows) == 2 and all(count == 1 for _, count in rows) for rows in before.values()), "initial S2/S3 execution counts were not exactly one")
    for index in range(2):
        repeated = invoke(index, f"java-round-{index + 1}-repeat")
        check(repeated["admissionId"] == observed[index]["admissionId"] and repeated["manifestDigest"] == observed[index]["manifestDigest"]
              and [(u["unitKey"], u["extractionJobId"], u["extractionInputDigest"], u["relationJobId"]) for u in repeated["units"]]
              == [(u["unitKey"], u["extractionJobId"], u["extractionInputDigest"], u["relationJobId"]) for u in observed[index]["units"]],
              "repeated Java round replaced durable identities")
    check(scenario.usage() == {"plans": 2, "units": 2} and scenario.dispatch_counts() == before, "repeated consumer debited quota or duplicated initial dispatch")
    response = scenario.status(scenario.references[0])
    check(response.status_code == 200, "consumed admission query failed")
    manifest = response.json()["manifest"]
    check(manifest["manifestDigest"] == sha({key: value for key, value in manifest.items() if key != "manifestDigest"}), "manifestDigest was not complete canonical public manifest")
    check(manifest["receiptSha256"] == hashlib.sha256((scenario.plan_root / manifest["planId"] / "receipt.json").read_bytes()).hexdigest(), "receipt-byte pin mismatch")
    unit = manifest["units"][0]
    relation = unit["relationSubmit"]
    arbitrary = {**relation, "jobId": "second-arbitrary-s3"}
    refused = service.request("POST", "/internal/v1/relation-jobs", body=arbitrary, key=arbitrary["jobId"])
    check(refused.status_code in (403, 409), "one admitted S2 authorized an arbitrary second S3 identity")
    scenario.workspace.revoke_source(False)
    for result in observed:
        for bound in result["units"]:
            for reply in (service.eresult(bound["extractionJobId"]), service.rresult(bound["relationJobId"])):
                check(reply.status_code == 200 and reply.json()["delivery"]["state"] == "withheld" and reply.json().get("job") is None,
                      "source revocation failed to withhold consumed S2/S3 content")
    scenario.workspace.revoke_source(True)
    scenario.install_policy(DISABLED, "disable-after-consumption")
    for result in observed:
        for bound in result["units"]:
            for reply in (service.eresult(bound["extractionJobId"]), service.rresult(bound["relationJobId"])):
                check(reply.status_code in (200, 403, 409) and (reply.status_code != 200 or reply.json()["delivery"]["state"] == "withheld"),
                      "policy disablement did not withhold content")
    scenario.install_policy(policy, "restore-after-consumption")
    for reference in scenario.references[:2]:
        record = scenario.status(reference).json()
        check(record["authority"]["state"] == "inactive", "identical policy restoration revived consumed admission")
    check(scenario.dispatch_counts() == before and scenario.usage() == {"plans": 2, "units": 2}, "revocation/replacement replayed work or reset usage")
    scenario.record("two-round-consumer-invariants", {"rounds": 2, "javaInvocations": 4, "providerCalls": 0, "distinctAdmissions": True,
                    "duplicateDispatches": 0, "quota": {"plans": 2, "units": 2}, "sourceDeliveryRevocation": True,
                    "terminalPolicyRevocation": True, "arbitrarySecondS3Refused": True})


def disabled_capability(scenario):
    scenario.start(online=False)
    response = scenario.admit(scenario.references[0])
    check(response.status_code == 409 and response.json()["error"]["code"] == "execution_unavailable", "default manual mode exposed online admission")
    check(not (scenario.workspace.state / "plan-authority.sqlite3").exists(), "disabled route constructed online state")
    scenario.record("default-disabled", {"executionUnavailable409": True, "onlineStateCreated": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java-classpath-file", required=True, type=Path)
    parser.add_argument("--java", default="java", help="Installed Java 25 executable; no build/download is performed")
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    classpath = args.java_classpath_file.resolve().read_text().strip()
    check(bool(classpath), "preparePlanAdmissionProof classpath file is empty")
    evidence = args.evidence_dir.resolve() if args.evidence_dir else Path(tempfile.mkdtemp(prefix="zoop-online-admission-evidence-")).resolve()
    check(not evidence.is_relative_to(ROOT), "retained evidence must be outside worktree")
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = Path(tempfile.mkdtemp(prefix="zoop-online-admission-smoke-")).resolve()
    owned, cases = [], []
    failure, outcome = None, "failed"
    try:
        flows = [("java-consumer", lambda scenario: consumer(scenario, args.java, classpath)), ("default-disabled", disabled_capability),
                 ("policy-controls", controls), ("paused-verifier", paused_verification), ("quota-contention", quota_contention),
                 ("source-revocation", source_revocation), ("operator-adoption", no_operator_adoption),
                 ("crash-before-commit", lambda scenario: admission_crash(scenario, "before-commit")),
                 ("crash-after-commit", lambda scenario: admission_crash(scenario, "after-commit")),
                 ("crash-receipts", execution_crashes),
                 ("crash-ambiguous", lambda scenario: execution_crashes(scenario, unknown=True)), ("terminal-expiry", terminal_expiry),
                 ("manual-to-online", lambda scenario: mode_change_refused(scenario, from_online=False)),
                 ("online-to-manual", lambda scenario: mode_change_refused(scenario, from_online=True)), ("queued-policy-revocation", queued_policy_revocation)]
        for name, flow in flows:
            scenario = OnlineScenario(root / name, evidence / name)
            owned.append(scenario)
            scenario.prepare()
            flow(scenario)
            scenario.close()
            cases.append({"case": name, "status": "passed"})
        outcome = "passed"
    except (AssertionError, OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, httpx.HTTPError) as error:
        failure = str(error)
    finally:
        for scenario in owned:
            try:
                scenario.close()
            except (AssertionError, OSError, RuntimeError, subprocess.SubprocessError) as error:
                outcome, failure = "failed", f"cleanup: {error}; prior failure: {failure}"
        remove_tree(root)
        cleaned = not root.exists()
        if not cleaned:
            outcome, failure = "failed", "owned workspace removal failed"
        summary = {"status": outcome, "cases": cases, "failure": failure, "evidenceDir": str(evidence),
                   "ownedStateRemoved": cleaned, "providerCalls": 0 if outcome == "passed" else None,
                   "evidenceLimit": "authored synthetic replay proves integration/authority, not model quality"}
        (evidence / "summary.json").write_text(canonical(summary) + "\n")
    print(canonical(summary))
    return 0 if outcome == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
