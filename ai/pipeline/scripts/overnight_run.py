#!/usr/bin/env python3
"""Finite, private real-data overnight controller; never a public publisher.

Use the worktree interpreter and PYTHONPATH (copied console-script shebangs are not
trusted). --check prepares exact read-only corpus proofs, immutable funded runtime
pins and a retained, isolated local Neo4j. It never loads model keys or sends.
Main supplies control/greenlight.json AFTER reviewing CHECK.json. Version 3 uses
zoop-private-greenlight-2 with the exact frozen providerChain and verifier; the
old enabledProfiles shape is rejected. A direct-DeepSeek diagnostic must succeed
before the ordinary OpenAI-to-DeepSeek chain canary, and both precede --run.
Canary reports distinguish requested scope from observed physical providers.
Unknown attempts keep worst exposure and are never retried; restart exports
their immutable receipts before closing the admitted set as unknown.
Identical private verifier requests may reuse one settled sibling receipt within
the same admitted set; reuse is candidate-bound and never a new provider attempt.

Acquisition is a separate owner: this controller consumes only the selected INDEX.
All source/receipt/output/queue files and Neo4j data are retained. Admission closes
at the configured cutoff or first TERM/INT; SIGUSR1 pauses only the local batch.
Admitted sets drain within finishBy, reserving time for owned-child termination,
receipt reconciliation and graph shutdown. Unknown attempts are never resent.

Compatible inputs are ordinarily re-ingested into new private shared ledgers.
Fresh S2 jobs freeze at most eight prior ready provider-produced candidate events;
selection/exclusions and actual comparison outcomes are retained. No history is
fabricated for the first item, and NEW never means globally novel. Offline
loopback controls must use a separate verification root, never the live index.
The direct-DeepSeek diagnostic shares the money ledger but contributes neither
ordinary history nor graph versions; its completed units remain separate.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter, deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from overnight_inputs import (canonical_registry, catalogue, encoded, file_pin, raw_save,
                              bind_execution, indexed_items, load, observation_selector, prepare_input_metadata, prepare_item, save, sha, verify_item)
import overnight_history as history
from experiment_snapshots import identifier
from zoop_ai_pipeline.live_funding import FINISH_RESERVE_SECONDS, TERMINATION_GRACE_SECONDS, SEND_BEFORE_ENV

RUN_CONFIG = None
RUN_CONFIG_PATH = None
IMMUTABLE_OLD_ROOT = Path.home() / "zoop-overnight-20261027"
ROOT = IMMUTABLE_OLD_ROOT
REPO = Path(__file__).resolve().parents[3]
RUN_ID = "overnight-20261027"
ADMIT_UNTIL = "2026-10-27T20:30:00Z"
SEND_UNTIL = "2026-10-27T20:50:00Z"
DRAIN_UNTIL = "2026-10-27T20:58:00Z"
FINISH_UNTIL = "2026-10-27T21:00:00Z"
POLICY = "private-unmerged-candidate-1"
MAX_CALLS = 2000
MAX_UNITS = 2000
HISTORY_CHUNK_UNITS = 128
HISTORY_MAX_EVENTS, HISTORY_MAX_MEMBERS = 8, 20
TIMEOUT = 300
VERIFIER_FLOOR_NANO = 1_000_000
IMAGE = "neo4j:5.26.32"
GRAPH_PORT = 32810
GRAPH_STOP_GRACE, GRAPH_STOP_TIMEOUT = 45, 60
GRAPH_INSPECT = ('{"id":{{json .Id}},"runLabel":{{json (index .Config.Labels "zoop.overnight.run")}},'
                 '"image":{{json .Image}},"running":{{json .State.Running}},"exitCode":{{json .State.ExitCode}},'
                 '"oomKilled":{{json .State.OOMKilled}},"portBindings":{{json .HostConfig.PortBindings}},"mounts":{{json .Mounts}}}')
MODULES = {"extract": "extraction_cli", "relation": "relation_cli", "graph": "graph_projection_cli"}
PROVENANCE = {"sourceKind": "actual", "executionMode": "live", "recordingKind": "provider"}


class Refused(Exception):
    def __init__(self, code, *, unknown=False):
        self.code, self.unknown = code, unknown
        super().__init__(code)


def now():
    return datetime.now(UTC).isoformat()


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def remaining(deadline):
    return (instant(deadline) - datetime.now(UTC)).total_seconds()


def nano(value):
    return None if value is None else int(Decimal(str(value)) * 1_000_000_000)


def configure(args):
    """Select an explicit new-day configuration; never extend or adopt yesterday's ledger."""
    global RUN_CONFIG, RUN_CONFIG_PATH, ROOT, RUN_ID, ADMIT_UNTIL, GRAPH_PORT, MAX_CALLS
    from zoop_ai_pipeline.live_funding import run_policy
    path = args.run_config
    if path is None or path.is_symlink():
        raise Refused("explicit_run_config_required")
    config = load(path)
    try:
        run_policy(config)
    except ValueError:
        raise Refused("run_config_invalid") from None
    if (type(config["graphPort"]) is not int or not 1024 <= config["graphPort"] <= 65535
            or type(config["maxCalls"]) is not int or not 1 <= config["maxCalls"] <= 100_000):
        raise Refused("run_config_invalid")
    from zoop_ai_pipeline.live_funding import timestamp
    if not FINISH_RESERVE_SECONDS + TIMEOUT < (timestamp(config["finishBy"]) - timestamp(config["admitUntil"])).total_seconds() <= 3600:
        raise Refused("run_finish_window_invalid")
    from zoop_ai_pipeline.private_processing import Actor
    try:
        Actor.model_validate(config["processingActor"])
    except ValueError:
        raise Refused("processing_actor_invalid") from None
    root = Path(config["root"])
    if (not root.is_absolute() or root.is_symlink() or root.resolve() != root
            or root == IMMUTABLE_OLD_ROOT or root.is_relative_to(IMMUTABLE_OLD_ROOT)
            or config["runId"] == "overnight-20261027"):
        raise Refused("new_day_namespace_required")
    if args.root is not None and args.root.resolve() != root:
        raise Refused("authorized_runtime_root_required")
    args.root = root
    RUN_CONFIG, RUN_CONFIG_PATH = config, path.resolve()
    ROOT, RUN_ID, ADMIT_UNTIL = root, config["runId"], config["admitUntil"]
    GRAPH_PORT, MAX_CALLS = config["graphPort"], config["maxCalls"]


def child_controller_args():
    args = [str(Path(__file__).resolve())]
    if RUN_CONFIG_PATH is not None:
        args += ["--run-config", str(RUN_CONFIG_PATH), "--root", str(ROOT)]
    return args


def set_plan(unit):
    """Finite native contracts, not a document/source sampling quota."""
    from zoop_ai_pipeline.extraction_contracts import MAX_COMPARISONS
    from zoop_ai_pipeline.relation_contracts import MAX_RELATIONS
    from zoop_ai_pipeline.live_runtime import MAX_RESPONSE_BYTES
    # Extraction mentions have no independent list cap; response bytes and the
    # shared call ceiling bound downstream summaries even for a hostile response.
    summaries = min(MAX_CALLS, MAX_RESPONSE_BYTES)
    return {"extract": 2, "compare": 2 * MAX_COMPARISONS if unit["snapshot"]["events"] else 0, "topic": 2,
            "relation": 2, "verify-relation": MAX_RELATIONS, "impact": 2 * MAX_RELATIONS,
            "verify-impact": 2 * MAX_RELATIONS, "issue-summary": summaries, "verify-issue-summary": summaries}


def item_id(item):
    identity = item if "recordPath" in item else observation_selector(load(item["exportPath"])["observation"], item.get("observation"))
    return sha(encoded(identity))[:24]


def planned_set_id(unit, kind="ordinary"):
    return "set-" + sha(encoded({"unitId": unit["unitId"], "kind": kind}))


def source_identity(unit):
    return sha(encoded({key: value for key, value in unit.items()
                        if key not in {"privateProcessing", "privateProcessingSha256", "execution"}}))


def authority_args(unit):
    return ["--private-processing", unit["privateProcessing"]] if "privateProcessing" in unit else ["--sources", unit["registry"]]


def queue_totals(queue):
    """Work-purpose totals; diagnostic duplicates are never ordinary completed units."""
    result = {}
    for kind in ("ordinary", "deepseek-diagnostic"):
        entries = [entry for entry in queue.values() if entry.get("queueKind", "ordinary") == kind]
        result[kind] = {"states": dict(Counter(entry["state"] for entry in entries)),
                        "completed": sum(entry["state"] == "completed" for entry in entries),
                        "completedComparisons": sum(entry.get("comparison", {}).get("completedComparisons", 0) for entry in entries)}
    return result


def input_coverage(items, queue, excluded_unit_ids):
    """Describe current manifest coverage without rewriting historical queue states."""
    coverage = {"manifestItems": len(items), "excluded": 0, "prepared": {"native": 0, "retained": 0},
                "awaitingHistory": 0, "blocked": {}}
    blocked = Counter()
    for item in items:
        try:
            key = item_id(item)
        except (ValueError, KeyError, OSError):
            key = sha(encoded(item))[:24]
        entry = queue[key]
        if key in excluded_unit_ids:
            coverage["excluded"] += 1
        elif "consumerMetadataError" in entry:
            blocked[entry["consumerMetadataError"]["code"]] += 1
        elif entry["state"] in {"preparation-blocked", "rights-blocked"}:
            blocked[entry["code"]] += 1
        else:
            coverage["prepared"]["retained" if "recordPath" in item else "native"] += 1
            coverage["awaitingHistory"] += entry["state"] == "awaiting-check"
    coverage["blocked"] = dict(blocked)
    return coverage


def base_env():
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/opt/homebrew/bin"), "HOME": str(Path.home()),
            "LANG": "en_US.UTF-8", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": os.pathsep.join(str(REPO / part) for part in ("ai/pipeline/src", "ai/worker/src"))}


def profile_env(root, cohort):
    from zoop_ai_pipeline import live_runtime as lr
    prefix = "ZOOP_AI_PIPELINE_LIVE_"
    result = {**base_env(), lr.GATE: "1", lr.MODEL_VAR: "gpt-6-luna" if cohort == "luna" else "deepseek-v4.1-flash",
              lr.EFFORT_VAR: "high" if cohort == "luna" else "provider-default", lr.MAX_OUTPUT_VAR: "24000",
              lr.TIMEOUT_VAR: str(TIMEOUT), lr.BUDGET_DIR_VAR: str(root / "modelbudget"), lr.MAX_USD_VAR: "20",
              lr.MAX_CALLS_VAR: str(MAX_CALLS), lr.OPENAI_URL_VAR: "https://api.openai.com/v1" if cohort == "luna" else "https://opencode.ai/zen/go/v1",
              lr.JEV_URL_VAR: "https://api.typesafe.ai/v1", lr.JEV_MODEL_VAR: "jev-1.14.0",
              prefix + "PROFILE": "overnight-funded-v1", prefix + "RUN_ID": RUN_ID,
              prefix + "NOT_AFTER": SEND_UNTIL, prefix + "SHARED_MAX_USD": "10", prefix + "PERSONAL_MAX_USD": "10"}
    if RUN_CONFIG:
        result.pop(lr.NOT_AFTER_VAR)
        from zoop_ai_pipeline.live_funding import CAPPED_PROFILE, run_policy
        run_policy(RUN_CONFIG)
        result.update({lr.PROFILE_VAR: CAPPED_PROFILE, lr.ADMIT_FROM_VAR: RUN_CONFIG["admitFrom"],
                       lr.ADMIT_UNTIL_VAR: RUN_CONFIG["admitUntil"], lr.FINISH_BY_VAR: RUN_CONFIG["finishBy"],
                       lr.MAX_USD_VAR: RUN_CONFIG["funding"]["totalMaxUsd"],
                       lr.SHARED_MAX_VAR: RUN_CONFIG["funding"]["sharedMaxUsd"],
                       lr.PERSONAL_MAX_VAR: RUN_CONFIG["funding"]["personalMaxUsd"]})
        result[SEND_BEFORE_ENV] = (instant(RUN_CONFIG["finishBy"]) - timedelta(seconds=FINISH_RESERVE_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if cohort != "luna":
            from zoop_ai_pipeline import direct_deepseek
            result.update({lr.MODEL_VAR: direct_deepseek.MODEL, lr.OPENAI_URL_VAR: direct_deepseek.BASE_URL, lr.EFFORT_VAR: "high"})
    return result


@contextlib.contextmanager
def environment(values):
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def runtime_for(root, cohort, *, summary=False):
    from zoop_ai_pipeline.live_runtime import LiveRuntime, ISSUE_SUMMARY, PIPELINE
    with environment(profile_env(root, cohort)):
        return LiveRuntime.from_env(family=ISSUE_SUMMARY if summary else PIPELINE)


def read_named_env(path, names):
    """Parse only documented names as literal single-line values; no shell/interpolation."""
    result = {}
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            match = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if not match or match[1] not in names:
                continue
            name, value = match.groups()
            if name in result:
                raise Refused("duplicate_key_configuration")
            if value[:1] in ("'", '"'):
                if len(value) < 2 or value[-1] != value[0]:
                    raise Refused("key_configuration_literal_required")
                value = value[1:-1]
            if not value or "\n" in value or "\r" in value or "${" in value or "$(" in value:
                raise Refused("key_configuration_literal_required")
            result[name] = value
    if set(result) != set(names):
        raise Refused("documented_key_configuration_missing")
    return result


def live_env(root, cohort, *, credential_env=None):
    from zoop_ai_pipeline import live_runtime as lr
    if credential_env is None:
        raise Refused("explicit_credential_env_required")
    if RUN_CONFIG:
        from zoop_ai_pipeline.direct_deepseek import KEY_VAR
        keys = {lr.JEV_KEY_VAR, KEY_VAR, *([lr.OPENAI_KEY_VAR] if cohort == "luna" else [])}
    else:
        keys = {lr.OPENAI_KEY_VAR, lr.JEV_KEY_VAR}
    return {**profile_env(root, cohort), **read_named_env(credential_env, keys)}


def funding(root):
    from zoop_ai_pipeline.live_budget import Budget, nano_from_usd
    from zoop_ai_pipeline.live_funding import funding_policy, run_policy
    policy = run_policy(RUN_CONFIG) if RUN_CONFIG else funding_policy(RUN_ID, SEND_UNTIL)
    return Budget(root / "modelbudget", policy["totalMaxNanoUsd"] if RUN_CONFIG else nano_from_usd("20"), MAX_CALLS,
                  funding=policy, bucket_caps=policy["bucketMaxNanoUsd"],
                  finish_by=RUN_CONFIG["finishBy"] if RUN_CONFIG else None)


def code_pins():
    files = sorted((REPO / "ai/pipeline/src/zoop_ai_pipeline").glob("*.py"))
    files += sorted((REPO / "ai/worker/src").rglob("*.py"))
    files += [Path(__file__).resolve(), *(Path(__file__).with_name(name) for name in
              ("overnight_inputs.py", "overnight_metrics.py", "overnight_history.py", "overnight_receipts.py", "experiment_snapshots.py"))]
    return [{"path": str(p.relative_to(REPO)), "sha256": sha(p.read_bytes())} for p in files]


def identity_gate():
    from zoop_ai_pipeline import extraction_contracts as c, extraction_replay as r
    if c.ADAPTER_VERSION != "zoop-extraction-native-replay-3" or c.LIVE_ADAPTER_VERSION != "zoop-extraction-native-live-3":
        raise Refused("identity_patch_gate_failed")
    if not callable(getattr(r, "participants_valid", None)):
        raise Refused("identity_patch_gate_failed")


def frozen_provider_approval(pins):
    binding = pins["runtimeBindings"]["luna"]["pipeline"]
    primary = binding["generation"]
    chain = primary["fallback"]
    fallback = chain["binding"]["generation"]
    verifier = binding["verifier"]
    return {"providerChain": {
        "primary": {"provider": "openai", "model": primary["model"], "reasoningEffort": primary["reasoningEffort"],
                    "endpoint": primary["endpoint"], "accountRole": "shared-openai"},
        "fallback": {"provider": "deepseek-direct", "model": fallback["model"], "reasoningEffort": fallback["reasoningEffort"],
                     "endpoint": fallback["endpoint"], "accountRole": "personal-deepseek"},
        "failurePolicy": chain["version"], "maxPhysicalAttempts": chain["maxPhysicalAttempts"]},
        "verifier": {"provider": verifier["provider"], "model": verifier["model"], "endpoint": verifier["endpoint"],
                     "accountRole": "personal-typesafe"}}


def provider_approval_digest(pins):
    """Provider readiness is not approval of the changing input prefix."""
    return sha(encoded({"schemaVersion": "zoop-provider-readiness-1",
                        **{key: pins[key] for key in ("codePins", "runtimeBindings", "runConfig", "funding", "identityPolicy")},
                        **frozen_provider_approval(pins)}))


def pinned_json(pin, parent):
    path = Path(pin["path"])
    if path.is_symlink() or not path.resolve().is_relative_to(parent.resolve()) or file_pin(path)["sha256"] != pin["sha256"]:
        raise Refused("provider_readiness_evidence_changed")
    return load(path)


def seal_canary_report(root, report):
    """Retain every report, including failures; only completed evidence is reusable."""
    path = root / "control/provider-readiness" / (sha(encoded(report)) + ".json")
    save(path, report, immutable=True)
    return {**report, "readinessReceipt": file_pin(path)}


def v2_greenlight(check, mode, profile=None):
    result = {"schemaVersion": "zoop-private-greenlight-2", "checkDigest": check["checkDigest"],
              "mode": mode, "approvedBy": "Main", "identityPolicy": POLICY,
              "providerApprovalDigest": provider_approval_digest(check["pins"]), **frozen_provider_approval(check["pins"])}
    if mode == "canary":
        result["canaryProfile"] = profile
    return result


def require_v2_canaries(root, check, mode, profile):
    required = ["deepseek-diagnostic", "luna"] if mode == "run" else ([] if profile == "deepseek-diagnostic" else ["deepseek-diagnostic"])
    approval = frozen_provider_approval(check["pins"])
    readiness = provider_approval_digest(check["pins"])
    for name in required:
        path = root / "control" / ("CANARY-" + name + ".json")
        try:
            observed = load(path)
            receipt = pinned_json(observed["readinessReceipt"], root / "control/provider-readiness")
            if observed != {**receipt, "readinessReceipt": observed["readinessReceipt"]}:
                raise Refused("provider_readiness_evidence_changed")
            original = pinned_json(receipt["inputAuthorization"]["check"], root / "control/retained")
            if (receipt["status"] != "completed" or receipt.get("receiptCoverage") != "complete"
                    or receipt.get("mode") != "canary" or receipt.get("canaryProfile") != name
                    or receipt.get("completionScope") != ("deepseek-diagnostic" if name == "deepseek-diagnostic" else "ordinary")
                    or receipt.get("providerApprovalDigest") != readiness
                    or provider_approval_digest(original["pins"]) != readiness
                    or original["checkDigest"] != receipt["checkDigest"]
                    or sha(encoded(original["pins"])) != original["checkDigest"]
                    or receipt["inputAuthorization"]["checkDigest"] != original["checkDigest"]
                    or any(receipt.get(key) != value for key, value in approval.items())
                    or not receipt["canaryUnitPins"]):
                raise Refused("provider_readiness_evidence_changed")
            checked_units = {unit["unitId"]: unit for unit in original["pins"]["units"]}
            for pin in receipt["canaryUnitPins"]:
                unit = pinned_json(pin, root / "analysis")
                checked = checked_units[unit["unitId"]]
                if (pin["unitId"] != unit["unitId"] or pin["sourceIdentity"] != source_identity(unit)
                        or any(unit[key] != checked[key] for key in
                               ("sourceId", "observation", "registry", "registrySha256", "export", "exportSha256", "originalPins"))):
                    raise Refused("provider_readiness_evidence_changed")
                verify_item(unit)
            calls = receipt["physicalProviderCalls"]
            if (calls.get("personal-deepseek", 0) < 1 if name == "deepseek-diagnostic"
                    else calls.get("shared-openai", 0) + calls.get("personal-deepseek", 0) < 1):
                raise Refused("provider_readiness_evidence_changed")
        except (OSError, KeyError, TypeError, ValueError, Refused):
            raise Refused("successful_provider_chain_canary_required") from None


def reuse_summary_verifier(unit_dir, directory, candidate_id, unit, runtime, prepared, authorize):
    """Resolve only the ledger's exact same-set owner; never retry an unknown."""
    from zoop_ai_pipeline.live_runtime import SET_ID_VAR, LiveFailure

    stage = prepared["stage"]
    set_id = os.environ.get(SET_ID_VAR, "")
    if (not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", set_id)
            or unit["execution"]["setId"] != set_id):
        raise Refused("live_set_not_admitted")
    budget = funding(ROOT)
    holder = budget.set_request_holder(set_id, stage, prepared["requestDigest"])
    record_path = directory / (stage + "-reuse.json")
    if holder is None:
        if record_path.exists() or record_path.is_symlink():
            raise Refused("summary_verifier_reuse_mismatch")
        return None
    if holder["state"] != "settled":
        raise Refused("summary_verifier_reuse_source_unsettled")
    siblings = unit_dir / "candidate-summaries"
    matches = []
    if not siblings.is_symlink():
        for sibling in siblings.iterdir():
            intent_path = sibling / (stage + "-intent.json")
            if sibling == directory or sibling.is_symlink() or not sibling.is_dir() or intent_path.is_symlink():
                continue
            if intent_path.is_file():
                try:
                    intent = load(intent_path)
                    if intent.get("attemptId") == holder["attemptId"]:
                        matches.append((sibling, intent))
                except (OSError, ValueError, AttributeError):
                    raise Refused("summary_verifier_reuse_source_missing") from None
    if len(matches) != 1:
        raise Refused("summary_verifier_reuse_source_missing")
    sibling, intent = matches[0]
    receipt_path = sibling / (stage + "-receipt.json")
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise Refused("summary_verifier_reuse_source_missing")
    try:
        raw = receipt_path.read_bytes()
        receipt = json.loads(raw)
        exact = (receipt["attemptId"] == holder["attemptId"]
                 and all(receipt[key] == prepared[key] for key in
                         ("stage", "requestDigest", "expect", "bindingIdentity", "recipient", "purpose"))
                 and all(intent[key] == prepared[key] for key in ("stage", "requestDigest", "bindingIdentity"))
                 and receipt["recipient"] == holder["recipient"]
                 and receipt["admittedSet"] == {"setId": set_id}
                 and receipt["funding"]["accountRole"] == holder["accountRole"]
                 and receipt["funding"]["bucket"] == holder["bucket"]
                 and receipt["cost"]["settled"] is True
                 and Decimal(str(receipt["cost"]["chargedUsd"])) * 1_000_000_000 == holder["chargedNano"]
                 and sha(receipt["http"]["bodyText"].encode()) == receipt["http"]["bodySha256"])
    except (OSError, KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        raise Refused("summary_verifier_reuse_mismatch") from None
    if not exact:
        raise Refused("summary_verifier_reuse_mismatch")
    try:
        answer = runtime.answer(stage, receipt)
    except LiveFailure:
        raise Refused("summary_verifier_reuse_source_invalid") from None
    record = {"schemaVersion": "zoop-private-verifier-reuse-1", "kind": "same-set-receipt-reuse",
              "stage": stage, "candidateId": candidate_id, "setId": set_id,
              "requestDigest": prepared["requestDigest"], "preparedDigest": prepared["digest"],
              "bindingIdentity": prepared["bindingIdentity"], "recipient": prepared["recipient"], "purpose": prepared["purpose"],
              "source": {"candidateFolder": sibling.name, "attemptId": holder["attemptId"],
                         "receiptSha256": sha(raw), "ledgerState": "settled", "chargedNano": holder["chargedNano"]},
              "physicalProviderCalls": 0, "reservations": 0}
    if record_path.is_symlink():
        raise Refused("summary_verifier_reuse_mismatch")
    if record_path.exists() and record_path.read_bytes() != encoded(record) + b"\n":
        raise Refused("summary_verifier_reuse_mismatch")
    authorize(receipt["recipient"])
    if budget.set_request_holder(set_id, stage, prepared["requestDigest"]) != holder:
        raise Refused("summary_verifier_reuse_mismatch")
    save(record_path, record, immutable=True)
    return answer, {"kind": "same-set-receipt-reuse", "record": record_path.name,
                    "sourceAttemptId": holder["attemptId"], "sourceReceiptSha256": sha(raw)}


def private_summary_child(unit_dir, candidate_id):
    """Existing ISSUE_SUMMARY family; independent private journal, NEVER Planner output."""
    from zoop_ai_pipeline import issue_summary_prompts as prompts, issue_summary_jev as jev
    from zoop_ai_pipeline.extraction import Sources
    from zoop_ai_pipeline.extraction_contracts import ObservationRef
    from zoop_ai_pipeline.ingestion_contracts import Authority
    from zoop_ai_pipeline.live_runtime import LiveRuntime, ISSUE_SUMMARY, LiveFailure

    unit_dir = Path(unit_dir).resolve()
    if not unit_dir.is_relative_to(ROOT / "analysis") or (not RUN_CONFIG and remaining(SEND_UNTIL) <= 0):
        raise Refused("private_summary_execution_boundary")
    checked = load(ROOT / "control/CHECK.json")
    greenlight = load(ROOT / "control/greenlight.json")
    expected = {"checkDigest": checked["checkDigest"], "mode": greenlight.get("mode"), "approvedBy": "Main", "identityPolicy": POLICY}
    if RUN_CONFIG:
        profile = "deepseek-diagnostic" if unit_dir.parent.name == "deepseek-diagnostic" else "luna"
        expected = v2_greenlight(checked, greenlight.get("mode"), profile)
        if greenlight.get("mode") == "run" and unit_dir.parent.name != "luna":
            raise Refused("private_summary_profile_not_enabled")
        require_v2_canaries(ROOT, checked, expected["mode"], profile)
    elif expected["mode"] == "canary":
        expected["canaryProfile"] = "deepseek-diagnostic" if unit_dir.parent.name == "deepseek-diagnostic" else "luna"
    elif expected["mode"] == "run":
        enabled = greenlight.get("enabledProfiles")
        if enabled not in (["luna"], ["luna", "deepseek"]) or unit_dir.parent.name not in enabled:
            raise Refused("private_summary_profile_not_enabled")
        expected["enabledProfiles"] = enabled
    if (greenlight != expected or expected["mode"] not in {"canary", "run"}
            or code_pins() != checked["pins"]["codePins"]):
        raise Refused("private_summary_main_gate_missing")
    unit = load(unit_dir / "unit.json")
    verify_item(unit)
    s2 = load(unit_dir / "s2-result.json")
    candidate = next(c for c in s2["eventCandidates"] if c["eventCandidateId"] == candidate_id)
    directory = unit_dir / "candidate-summaries" / sha(candidate_id.encode())[:24]
    existing = load(directory / "result.json") if (directory / "result.json").exists() else None
    # Historical v1 results are read-only; v2 reuse must revalidate its source and rights.
    if existing and (existing["schemaVersion"] == "zoop-private-candidate-summary-1"
                     or existing["verifierSource"]["kind"] == "provider-receipt"):
        return {key: existing[key] for key in ("candidateSummaryStatus", "publication", "availablePublicSummary")}
    runtime = LiveRuntime.from_env(need_send=True, family=ISSUE_SUMMARY)
    expected_binding = load(unit_dir / "summary-runtime.json")
    if not runtime.accepts(expected_binding):
        raise Refused("summary_runtime_pin_changed")
    if RUN_CONFIG:
        profile = "luna" if unit_dir.parent.name == "luna" else "deepseek"
        if expected_binding != checked["pins"]["runtimeBindings"][profile]["summary"]:
            raise Refused("summary_runtime_pin_changed")
    elif expected["mode"] == "run":
        profile = "luna" if expected_binding["generation"]["model"] == "gpt-6-luna" else "deepseek"
        if profile not in expected["enabledProfiles"]:
            raise Refused("private_summary_profile_not_enabled")
    exported = load(unit["export"])
    text = exported["document"]["text"]
    quotes = []
    for citation in candidate["citations"]:
        if (citation.get("error") or citation["documentId"] != unit["observation"]["documentId"]
                or citation["documentVersion"] != unit["observation"]["documentVersion"]):
            raise Refused("summary_citation_not_exact")
        start, end = citation["start"], citation["end"]
        quote = text[start:end]
        if not quote or not 0 <= start < end <= len(text):
            raise Refused("summary_citation_not_exact")
        quotes.append({"quoteId": citation["evidenceId"], "context": "background" if candidate["mention"].get("background") is True else "report", "text": quote})
    quotes = list({q["quoteId"]: q for q in quotes}.values())
    payload = {"issueTitle": candidate["mention"]["title"], "quotes": quotes}
    save(directory / "input.json", {"candidateId": candidate_id, "s2InputDigest": s2["inputDigest"], "payload": payload,
                                    "publication": "not-published", "availablePublicSummary": False}, immutable=True)
    if "privateProcessing" in unit:
        from zoop_ai_pipeline.private_processing import PrivateAuthority
        authority = PrivateAuthority(Path(unit["privateProcessing"]))
        authority.check_runtime(runtime.binding())
    else:
        authority = Authority(Path(unit["registry"]))
    sources = Sources(Path(unit["ingestionStateDir"]), authority)
    ref = ObservationRef.model_validate(unit["observation"])
    verifier_source, reuse_lookup = None, False

    def exchange(stage, value):
        nonlocal verifier_source, reuse_lookup
        prepared = runtime.prepare(stage, value)
        intent_path, receipt_path = directory / (stage + "-intent.json"), directory / (stage + "-receipt.json")
        def authorize(recipient=None):
            verify_item(unit)
            sources.authorize_model_send(ref, runtime.purpose(stage), recipient or runtime.recipient(stage))
        if receipt_path.exists():
            receipt = load(receipt_path)
            if receipt["requestDigest"] != prepared["requestDigest"]:
                raise Refused("summary_receipt_request_changed")
            if stage == jev.STAGE:
                verifier_source = {"kind": "provider-receipt", "attemptId": receipt["attemptId"]}
            return runtime.answer(stage, receipt)
        if intent_path.exists():
            raise Refused("summary_previous_attempt_unknown", unknown=True)
        if RUN_CONFIG and stage == jev.STAGE:
            reuse_lookup = True
            reused = reuse_summary_verifier(unit_dir, directory, candidate_id, unit, runtime, prepared, authorize)
            if reused is not None:
                answer, verifier_source = reused
                return answer
            reuse_lookup = False
        attempt = "overnight-" + uuid.uuid4().hex
        if stage == jev.STAGE:
            verifier_source = {"kind": "provider-receipt", "attemptId": attempt}
        authorize()
        save(intent_path, {"attemptId": attempt, "stage": stage, "startedAt": now(), "requestDigest": prepared["requestDigest"],
                           "bindingIdentity": expected_binding["identity"], "reservation": prepared["reservation"]}, immutable=True)
        began = time.monotonic()
        try:
            alternate = runtime.fallback_recipient(stage)
            receipt = runtime.send(prepared, attempt_id=attempt, authorize=authorize,
                                   authorize_fallback=(lambda: authorize(alternate)) if alternate else None)
        except LiveFailure as exc:
            if exc.receipt is not None:
                save(receipt_path, exc.receipt, immutable=True)
            save(directory / (stage + "-failure.json"), {"code": exc.code, "uncertain": exc.uncertain, "finishedAt": now()}, immutable=True)
            raise
        # Receipt is durable BEFORE any parser or verdict is run.
        save(receipt_path, receipt, immutable=True)
        save(directory / (stage + "-timing.json"), {"receivedAt": now(), "durationMs": (time.monotonic() - began) * 1000}, immutable=True)
        from zoop_ai_pipeline.live_runtime import physical_attempts
        for physical in physical_attempts(receipt):
            if physical["state"] != "released":
                authorize((physical.get("receipt") or {}).get("recipient") or physical.get("recipient"))
        return runtime.answer(stage, receipt)

    headroom = funding(ROOT).snapshot()
    if headroom["verificationBlocked"]:
        raise Refused("live_budget_verification_blocked")
    if nano(headroom["buckets"]["personal"]["remainingUsd"]) < VERIFIER_FLOOR_NANO:
        raise Refused("verification_budget_cannot_admit")
    stage = "issue-summary"
    try:
        answer = exchange(stage, payload)
        claims = prompts.claims_from(answer, payload)
        verifier_payload = {"quotes": quotes, "claims": [{"claimId": c["claimId"], "text": c["text"], "quoteIds": c["evidenceIds"]} for c in claims]}
        stage = "verify-issue-summary"
        verified = exchange(stage, verifier_payload)
        outcome = jev.outcome(verified)
    except (LiveFailure, ValueError) as exc:
        if reuse_lookup:
            raise
        code = getattr(exc, "code", None) or str(exc)
        save(directory / (stage + "-verdict.json"), {"code": code,
             "status": "producer-invalid" if code == prompts.INVALID else "error", "finishedAt": now()}, immutable=True)
        raise
    result = {"schemaVersion": "zoop-private-candidate-summary-2", "candidateId": candidate_id,
              "publication": "not-published", "availablePublicSummary": False, "publicPath": "blocked-human-public-geography-field-gates",
              "candidateSummaryStatus": outcome, "claims": claims, "verdict": verified, "finishedAt": now(),
              "runtimeIdentity": expected_binding["identity"], "inputDigest": sha(encoded(payload)),
              "verifierSource": verifier_source}
    if existing:
        if {k: v for k, v in result.items() if k != "finishedAt"} != {k: v for k, v in existing.items() if k != "finishedAt"}:
            raise Refused("summary_verifier_reuse_mismatch")
    else:
        save(directory / "result.json", result, immutable=True)
    return {"candidateSummaryStatus": outcome, "publication": "not-published", "availablePublicSummary": False}


class Controller:
    def __init__(self, args):
        self.args, self.root = args, args.root.resolve()
        self.bin = Path(sys.executable)
        self.collection_index = args.collection_index
        self.pause_requested = False
        self.finish_requested = False
        self.child = None
        self.child_reaped = False
        self.force_requested = False
        self.signal_count = 0
        self.active_entry = None
        self.active_set = None
        self.stop_path = self.root / "control/stop-intent.json"
        self.stop_synced = None
        self.owner_lock_fd = None
        self.emitted_attempts = set()
        self.emitted_reuses = set()
        self.observed_attempts = set()
        self.physical_provider_calls = Counter()
        self.reported_models = Counter()
        events = self.root / "events.jsonl"
        if events.exists():
            with events.open() as stream:
                for line in stream:
                    record = json.loads(line)
                    if record.get("kind") == "attempt":
                        if record.get("attemptState") == "reused":
                            self.emitted_reuses.add((record["attemptId"], record["unitId"]))
                        else:
                            self.emitted_attempts.add(record["attemptId"])
        self.stop_requested = False
        self.queue_path = self.root / "control/queue.json"
        self.queue = load(self.queue_path) if self.queue_path.exists() else {}
        self.consumer_metadata = {key: entry["consumerMetadata"] for key, entry in self.queue.items() if "consumerMetadata" in entry}
        self.graph = None
        self.dispatch_code_pins = None
        self.active = None
        self.cohort = "luna"
        self.call_records = []
        self.started = now()
        self.started_monotonic = time.monotonic()
        if RUN_CONFIG and self.stop_path.exists():
            intent = load(self.stop_path)
            self.stop_requested = True
            self.force_requested = intent["forced"]

    def event(self, phase, status, *, unit=None, began=None, start=None, reason=None, counts=None, artifacts=None, **extras):
        """Project source labels only; original unit/source authority stays unchanged."""
        from overnight_metrics import record_event
        key = (unit or {}).get("unitId")
        view = self.consumer_metadata.get(key)
        if view is None and self.active and (unit or {}).get("sourceId") == self.active.get("sourceId"):
            key = self.active["unitId"]
            view = self.consumer_metadata.get(key)
        if self.queue.get(key, {}).get("consumerMetadataError"):
            view = {"freshness": "unknown"}
        value = {"schemaVersion": "zoop-overnight-event-1", "eventId": "event-" + uuid.uuid4().hex, "runId": RUN_ID,
                 "cohort": self.cohort, "phase": phase, "unitId": (unit or {}).get("unitId", "controller"),
                 "sourceId": identifier((unit or {}).get("sourceId")), "status": status, "reasonCode": reason,
                 "freshness": view["freshness"] if view else (unit or {}).get("freshness", "unknown"),
                 "startUtc": start, "endUtc": now(), "durationMs": None if began is None else (time.monotonic() - began) * 1000,
                 "durationProvenance": "unknown" if began is None else "cli_wall", "counts": counts or {},
                 "artifacts": artifacts or [], **extras}
        record_event(self.root / "events.jsonl", value)

    def input_metadata(self, item, key, mapping):
        view = prepare_input_metadata(item, key, mapping, self.root)
        if view is not None:
            self.consumer_metadata[key] = view
            if key in self.queue:
                self.queue[key]["consumerMetadata"] = view
                self.queue[key].pop("consumerMetadataError", None)
        return view

    def pause(self, *_):
        """Finish the current finite child/set without closing shared funding."""
        self.pause_requested = True

    def stop(self, *_):
        """Persist admission intent; only a second signal explicitly cancels a child."""
        self.signal_count += 1
        forced = self.signal_count > 1
        self.stop_requested, self.force_requested = True, forced or self.force_requested
        save(self.stop_path, {"reason": "emergency_signal" if forced else "soft_signal",
                              "requestedAt": now(), "forced": self.force_requested})
        if self.force_requested and self.child is not None:
            self.child.kill()

    def close_admission(self, reason):
        if not self.stop_requested:
            self.stop_requested = True
            save(self.stop_path, {"reason": reason, "requestedAt": now(), "forced": False})
        self.sync_stop()

    def sync_stop(self):
        if not RUN_CONFIG:
            return
        if remaining(RUN_CONFIG["finishBy"]) <= FINISH_RESERVE_SECONDS and not self.finish_requested:
            self.finish_requested = True
            save(self.root / "control/finish-intent.json", {"reason": "finish_deadline", "finishBy": RUN_CONFIG["finishBy"],
                 "requestedAt": now(), "cleanupReserveSeconds": FINISH_RESERVE_SECONDS,
                 "terminationGraceSeconds": TERMINATION_GRACE_SECONDS}, immutable=True)
            self.close_admission("finish_deadline")
        if remaining(ADMIT_UNTIL) <= 0 and not self.stop_requested:
            self.close_admission("admission_cutoff")
            return
        if self.stop_path.exists():
            intent = load(self.stop_path)
            self.stop_requested = True
            self.force_requested = self.force_requested or intent["forced"]
            if intent != self.stop_synced:
                funding(self.root).close_admission(intent["reason"], forced=self.force_requested)
                self.stop_synced = intent

    def ensure_prior_child_exited(self, entry):
        child = entry.get("child")
        if not child or child.get("reaped"):
            return
        try:
            os.kill(child["pid"], 0)
        except ProcessLookupError:
            child["reaped"] = True
            child["exitEvidence"] = "pid-absent-after-controller-restart"
            self.persist_queue()
        else:
            raise Refused("prior_child_still_running_reconcile_only", unknown=True)

    def persist_queue(self):
        save(self.queue_path, self.queue)

    def terminate_child(self):
        self.child.terminate()
        try:
            return self.child.communicate(timeout=TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self.child.kill()
            return self.child.communicate(timeout=TERMINATION_GRACE_SECONDS)

    def command(self, argv, *, env=None, payload=None, timeout=TIMEOUT, paid=False, finite_work=False, output=None, source_unit=None):
        self.sync_stop()
        if self.force_requested:
            raise Refused("controller_forced_stop", unknown=paid)
        if RUN_CONFIG and remaining(RUN_CONFIG["finishBy"]) <= FINISH_RESERVE_SECONDS + timeout:
            raise Refused("controller_finish_deadline")
        if RUN_CONFIG:
            if paid and self.active_set is None:
                raise Refused("live_set_not_admitted")
        elif self.stop_requested or remaining(DRAIN_UNTIL) <= 0:
            raise Refused("controller_drain_cutoff")
        if not RUN_CONFIG and paid and remaining(SEND_UNTIL) <= 0:
            raise Refused("controller_send_cutoff")
        if paid and source_unit is None:
            raise Refused("dispatch_source_pin_required")
        if RUN_CONFIG and paid and source_unit != self.active:
            raise Refused("live_set_identity_mismatch")
        if paid and self.dispatch_code_pins is None:
            raise Refused("dispatch_code_pin_required")
        if self.dispatch_code_pins is not None and code_pins() != self.dispatch_code_pins:
            self.stop_requested = True
            raise Refused("checked_code_changed")
        if source_unit is not None:
            try:
                verify_item(source_unit)
            except ValueError as exc:
                raise Refused(str(exc)) from None
        if paid:
            # Credentials are loaded only after the exact frozen source has passed.
            env = live_env(self.root, self.cohort, credential_env=getattr(self.args, "credential_env", None))
            if RUN_CONFIG:
                from zoop_ai_pipeline.live_runtime import SET_ID_VAR
                env[SET_ID_VAR] = self.active_set
            try:
                verify_item(source_unit)
            except ValueError as exc:
                raise Refused(str(exc)) from None
        execution = (source_unit or {}).get("execution")
        if execution:
            from zoop_ai_pipeline.live_runtime import SET_ID_VAR
            if paid and execution["setId"] != self.active_set:
                raise Refused("private_processing_set_mismatch")
            env = {**(env or base_env()), SET_ID_VAR: execution["setId"]}
        if self.dispatch_code_pins is not None and code_pins() != self.dispatch_code_pins:
            self.stop_requested = True
            raise Refused("checked_code_changed")
        seconds = timeout if RUN_CONFIG else min(timeout, max(0.1, remaining(DRAIN_UNTIL) - 5))
        # Seekable stdin delivers one exact payload and EOF independently of observation timeouts.
        with tempfile.TemporaryFile(dir=self.root) as request_input:
            request_input.write(b"" if payload is None else encoded(payload))
            request_input.seek(0)
            self.sync_stop()
            if self.force_requested:
                raise Refused("controller_forced_stop", unknown=paid)
            if RUN_CONFIG and remaining(RUN_CONFIG["finishBy"]) <= FINISH_RESERVE_SECONDS + timeout:
                raise Refused("controller_finish_deadline")
            self.child_reaped = False
            self.child = subprocess.Popen(argv, stdin=request_input, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          env=env or base_env(), cwd=self.root, start_new_session=True,
                                          pass_fds=() if self.owner_lock_fd is None else (self.owner_lock_fd,))
        try:
            if self.active_entry is not None:
                self.active_entry["child"] = {"pid": self.child.pid, "startedAt": now(), "reaped": False}
                self.persist_queue()
            if RUN_CONFIG and (paid or finite_work):
                # HTTP calls have individual deadlines; the whole finite child
                # is bounded by the explicitly approved finish/cleanup boundary.
                while True:
                    try:
                        stdout, stderr = self.child.communicate(timeout=0.25)
                        break
                    except subprocess.TimeoutExpired:
                        self.sync_stop()
                        if self.finish_requested:
                            raise
                        if self.force_requested:
                            self.child.kill()
            else:
                stdout, stderr = self.child.communicate(timeout=seconds)
            self.child_reaped = True
        except subprocess.TimeoutExpired:
            stdout, stderr = self.terminate_child()
            self.child_reaped = True
            code = "controller_finish_deadline" if self.finish_requested else "child_timeout"
            if output:
                save(output.with_suffix(".failure.json"), {"code": code, "stdoutBytes": len(stdout), "stderrBytes": len(stderr), "unknown": paid})
            raise Refused(code, unknown=paid) from None
        except BaseException:
            # Reap owned work even on observer failure, bounded by finishBy.
            if not self.child_reaped:
                try:
                    self.child.communicate(timeout=max(0.1, remaining(RUN_CONFIG["finishBy"]) - FINISH_RESERVE_SECONDS) if RUN_CONFIG else TIMEOUT)
                except subprocess.TimeoutExpired:
                    self.terminate_child()
                self.child_reaped = True
            raise
        finally:
            child, self.child = self.child, None
            if self.active_entry is not None and self.child_reaped:
                self.active_entry["child"].update(reaped=True, exitCode=child.returncode, finishedAt=now())
                self.persist_queue()
        if output:
            # CLI stdout may contain exact source text and receipts; retained only under 0700 root.
            try:
                parsed = json.loads(stdout)
            except ValueError:
                parsed = None
            if parsed is not None:
                save(output, parsed)
            save(output.with_suffix(".command.json"), {"exitCode": child.returncode, "stdoutBytes": len(stdout), "stderrBytes": len(stderr), "finishedAt": now()})
        else:
            parsed = None
        if child.returncode != 0:
            code = ((parsed or {}).get("error") or {}).get("code") if isinstance(parsed, dict) else None
            raise Refused(code if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_:-]+", code) else "child_nonzero_exit",
                          unknown=paid and (child.returncode < 0 or bool(isinstance(parsed, dict) and parsed.get("unknown"))))
        return parsed if output else stdout.decode().strip()

    def cli(self, label, module, arguments, payload, unit, directory, *, paid=False, env=None):
        start, began = now(), time.monotonic()
        output = directory / (label + ".json")
        try:
            result = self.command([str(self.bin), "-m", "zoop_ai_pipeline." + MODULES[module], *arguments],
                                  env=env, payload=payload, paid=paid, output=output, source_unit=unit)
            self.event(label, "ok", unit=unit, start=start, began=began, artifacts=[str(output.relative_to(self.root))])
            return result
        except Refused as exc:
            self.event(label, "unknown" if exc.unknown else "error", unit=unit, start=start, began=began, reason=exc.code)
            raise

    def retain_control(self, name, *, source_path: Path | None = None):
        """Archive exact bytes from the named control file or an explicit source path."""
        path = self.root / "control" / name if source_path is None else source_path
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise Refused("control_record_not_regular")
        raw = path.read_bytes()
        digest = sha(raw)
        target = self.root / "control/retained" / (path.stem + "-" + digest + path.suffix)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.exists():
            if target.is_symlink() or target.read_bytes() != raw:
                raise Refused("retained_control_conflict")
        else:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        return {"path": str(target), "sha256": digest}

    def provision_graph(self):
        descriptor = self.root / "control/neo4j-v2.json"
        pointer = self.root / "control/neo4j-current.json"
        legacy_path = self.root / "control/neo4j.json"
        name = "zoop-" + RUN_ID + "-private-fixed"
        docker = ["docker", "--context", "orbstack"]
        data, logs = self.root / "analysis/neo4j-data", self.root / "analysis/neo4j-logs"
        address = f"127.0.0.1:{GRAPH_PORT}"
        uri = "bolt://" + address
        expected_ports = {"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(GRAPH_PORT)}]}

        def facts(container):
            return json.loads(self.command([*docker, "inspect", "--format", GRAPH_INSPECT, container], timeout=20))

        def owned(observed, container, image):
            mounts = {m["Destination"]: m["Source"] for m in observed["mounts"] if m["Type"] == "bind"}
            if (observed["id"] != container or observed["runLabel"] != RUN_ID or observed["image"] != image
                    or mounts.get("/data") != str(data) or mounts.get("/logs") != str(logs)):
                raise Refused("graph_ownership_mismatch")

        if descriptor.exists():
            graph = load(descriptor)
            if (graph.get("format") != "zoop-overnight-graph-runtime-2" or graph["uri"] != uri
                    or graph["hostPort"] != GRAPH_PORT or graph["data"] != str(data) or graph["database"] != "neo4j"):
                raise Refused("graph_fixed_binding_mismatch")
            if pointer.exists() and load(pointer) != {"descriptor": descriptor.name, "sha256": sha(descriptor.read_bytes())}:
                raise Refused("graph_descriptor_pointer_mismatch")
            observed = facts(graph["containerId"])
            owned(observed, graph["containerId"], graph["imageId"])
            self.graph = graph
            if observed["portBindings"] != expected_ports:
                raise Refused("graph_fixed_port_required")
            self.command([*docker, "start", graph["containerId"]], timeout=30)
        else:
            image_id = self.command([*docker, "image", "inspect", "--format", "{{.Id}}", IMAGE], timeout=20)
            predecessor = None
            if legacy_path.exists():
                legacy = load(legacy_path)
                old = facts(legacy["containerId"])
                owned(old, legacy["containerId"], legacy["imageId"])
                if old["running"]:
                    raise Refused("graph_predecessor_must_be_stopped")
                if legacy["uri"] != uri or legacy["data"] != str(data) or legacy["imageId"] != image_id:
                    raise Refused("graph_predecessor_binding_mismatch")
                predecessor = {"descriptor": legacy_path.name, "sha256": sha(legacy_path.read_bytes()),
                               "containerId": legacy["containerId"], "uri": legacy["uri"], "retainedStopped": True,
                               "stopReceipt": self.retain_control("graph-stop.json")}
            data.mkdir(parents=True, exist_ok=True, mode=0o700)
            logs.mkdir(parents=True, exist_ok=True, mode=0o700)
            container = self.command([*docker, "run", "--pull=never", "--detach", "--name", name,
                "--label", "zoop.overnight.run=" + RUN_ID, "--restart=no", "--cpus=1", "--memory=1500m",
                "--user", f"{os.getuid()}:{os.getgid()}", "-p", f"{address}:7687", "-e", "NEO4J_AUTH=none",
                "-e", "NEO4J_server_http_enabled=false", "-e", "NEO4J_server_https_enabled=false",
                "-e", "NEO4J_server_memory_heap_initial__size=256m", "-e", "NEO4J_server_memory_heap_max__size=512m",
                "-e", "NEO4J_server_memory_pagecache_size=256m", "-v", str(data) + ":/data", "-v", str(logs) + ":/logs", image_id], timeout=60)
            self.graph = {"containerId": container, "containerName": name, "runId": RUN_ID}
            graph = {"format": "zoop-overnight-graph-runtime-2", "containerId": container, "containerName": name,
                     "imageId": image_id, "uri": uri, "hostPort": GRAPH_PORT, "database": "neo4j", "data": str(data),
                     "runId": RUN_ID, "retention": "persistent-private-no-delete", "predecessor": predecessor}
        actual_address = self.command([*docker, "port", graph["containerId"], "7687/tcp"], timeout=20)
        observed = facts(graph["containerId"])
        owned(observed, graph["containerId"], graph["imageId"])
        self.retain_control("graph-endpoint-observation.json")
        save(self.root / "control/graph-endpoint-observation.json",
             {"containerId": graph["containerId"], "expected": address, "actual": actual_address,
              "configured": observed["portBindings"], "observedAt": now()})
        if actual_address != address or observed["portBindings"] != expected_ports:
            raise Refused("graph_endpoint_mismatch")
        save(descriptor, graph, immutable=True)
        save(pointer, {"descriptor": descriptor.name, "sha256": sha(descriptor.read_bytes())}, immutable=True)
        self.graph = graph
        from neo4j import GraphDatabase
        deadline = time.monotonic() + 90
        ready = False
        with GraphDatabase.driver(uri, auth=None, connection_timeout=2) as driver:
            while time.monotonic() < deadline and not self.stop_requested:
                try:
                    driver.verify_connectivity()
                    ready = True
                    break
                except Exception:
                    time.sleep(1)
        if not ready:
            raise Refused("graph_start_not_ready")
        # The ordinary native init is idempotent and rechecks the SAME store/dbId/URI
        # after every restart; never edit or rebind the graph ledger ourselves.
        self.retain_control("graph-init.json")
        self.retain_control("graph-init.command.json")
        self.cli("graph-init", "graph", ["init", "--state-dir", str(self.root / "analysis/graph"), "--graph-uri", uri],
                 {"schemaVersion": "zoop-graph-projection-1", "storeId": RUN_ID + "-private", "database": "neo4j"}, None,
                 self.root / "control", env={**base_env(), "ZOOP_GRAPH_AUTH": "none"})
        return graph

    def prepare_history(self, items, units, runtimes):
        """Append content-pinned chunks without repacking previously checked inputs."""
        if not units:
            return []
        if len(items) != len(units):
            raise Refused("history_batch_identity_invalid")
        context = {"runtimeBindings": [runtime.binding() for runtime in runtimes],
                   "codePins": self.dispatch_code_pins, "actor": RUN_CONFIG["processingActor"]}
        pending = {unit["unitId"]: (item, unit) for item, unit in zip(items, units)}
        if len(pending) != len(units):
            raise Refused("history_batch_identity_invalid")
        chunks_root = self.root / "control/history-preparations/v2/chunks"
        chunks = []
        next_sequence = 0
        for path in sorted(chunks_root.glob("*/payload.json")):
            payload = load(path)
            if sha(encoded(payload)) != path.parent.name:
                raise Refused("history_checkpoint_changed")
            next_sequence = max(next_sequence, payload["sequence"] + 1)
            if any(payload[key] != value for key, value in context.items()):
                continue
            pairs = list(zip(payload["items"], payload["units"]))
            if all(pending.get(unit["unitId"]) == (item, unit) for item, unit in pairs):
                chunks.append(payload)
                for _, unit in pairs:
                    del pending[unit["unitId"]]
        by_source, ordered, served = {}, [], Counter()
        for item, unit in pending.values():
            day = self.consumer_metadata.get(unit["unitId"], {}).get("publicationDay") or unit.get("publication", {}).get("publishedAt")
            month = day[:7] if isinstance(day, str) else "unknown"
            by_source.setdefault(unit["sourceId"], {}).setdefault(month, deque()).append((item, unit))
        while by_source:
            for source in sorted(by_source):
                months = by_source[source]
                month = min(months, key=lambda value: (served[(source, value)], value))
                ordered.append(months[month].popleft())
                served[(source, month)] += 1
                if not months[month]:
                    del months[month]
                if not months:
                    del by_source[source]
        for offset in range(0, len(ordered), HISTORY_CHUNK_UNITS):
            batch = ordered[offset:offset + HISTORY_CHUNK_UNITS]
            payload = {"items": [pair[0] for pair in batch], "units": [pair[1] for pair in batch],
                       "sequence": next_sequence, **context}
            next_sequence += 1
            save(chunks_root / sha(encoded(payload)) / "payload.json", payload, immutable=True)
            chunks.append(payload)
        chunks.sort(key=lambda payload: payload["sequence"])
        plan = {"schemaVersion": "zoop-history-preparation-3", "runId": RUN_ID,
                "unitIds": sorted(unit["unitId"] for unit in units), "maxUnitsPerChunk": HISTORY_CHUNK_UNITS,
                "chunks": [sha(encoded(payload)) for payload in chunks]}
        plan_id = sha(encoded(plan))
        directory = self.root / "control/history-preparations/v2" / plan_id
        save(directory / "plan.json", plan, immutable=True)
        limit = self.args.preparation_chunks if self.args.check else None
        admitted_chunks = 0
        self.preparation_status = {"planId": plan_id, "plan": file_pin(directory / "plan.json"),
                                   "plannedUnits": len(units), "totalChunks": len(chunks),
                                   "preparedUnits": 0, "pendingUnits": len(units), "completedChunks": 0}
        results = []
        for payload in chunks:
            chunk_id = sha(encoded(payload))
            preparation_root = self.root / "preparation-v2" / chunk_id
            payload = {**payload, "preparationRoot": str(preparation_root), "planId": chunk_id}
            chunk_dir = chunks_root / chunk_id
            input_path, output_path = chunk_dir / "input.json", chunk_dir / "result.json"
            complete_path = chunk_dir / "complete.json"
            save(input_path, payload, immutable=True)
            if complete_path.exists():
                complete = load(complete_path)
                if (complete.get("childReaped") is not True or complete.get("inputSha256") != sha(input_path.read_bytes())
                        or complete.get("resultSha256") != sha(output_path.read_bytes())):
                    raise Refused("history_checkpoint_changed")
                result = load(output_path)
                for prepared in result["units"]:
                    verify_item(prepared)
            else:
                if limit is not None and admitted_chunks >= limit:
                    continue
                self.sync_stop()
                if self.stop_requested:
                    save(directory / "progress.json", {**self.preparation_status, "state": "stopped", "finishedAt": now()})
                    raise Refused("history_preparation_stopped")
                if self.pause_requested:
                    break
                if preparation_root.exists():
                    raise Refused("history_partial_checkpoint_reconcile_only")
                admitted_chunks += 1
                began, start = time.monotonic(), now()
                try:
                    result = self.command([str(self.bin), *child_controller_args(), "--prepare-history"],
                                          env=base_env(), payload=payload, output=output_path, finite_work=True)
                except Refused as exc:
                    self.event("history-prepare", "blocked", unit={"unitId": chunk_id},
                               began=began, start=start, reason=exc.code, cohort="input-preparation")
                    raise
                if not self.child_reaped or self.child is not None:
                    raise Refused("history_checkpoint_child_not_reaped")
                if [unit["unitId"] for unit in result["units"]] != [unit["unitId"] for unit in payload["units"]]:
                    raise Refused("history_checkpoint_units_changed")
                save(complete_path, {"inputSha256": sha(input_path.read_bytes()), "resultSha256": sha(output_path.read_bytes()),
                                     "childReaped": True, "finishedAt": now()}, immutable=True)
                self.event("history-prepare", "ok", unit={"unitId": chunk_id}, began=began, start=start,
                           counts={"prepared": len(result["units"])}, cohort="input-preparation",
                           artifacts=[str(complete_path.relative_to(self.root))])
            results.extend(result["units"])
            self.preparation_status.update(preparedUnits=len(results), pendingUnits=len(units) - len(results),
                                           completedChunks=self.preparation_status["completedChunks"] + 1)
            save(directory / "progress.json", {**self.preparation_status, "state": "preparing", "finishedAt": now()})
        save(directory / "progress.json", {**self.preparation_status,
             "state": "complete" if len(results) == len(units) else "paused", "finishedAt": now()})
        by_id = {unit["unitId"]: unit for unit in results}
        return [by_id[unit["unitId"]] for unit in units if unit["unitId"] in by_id]

    def check(self):
        self.dispatch_code_pins = code_pins()
        for name in ("CHECK.json", "greenlight.json"):
            self.retain_control(name)
        self.retain_control("MANIFEST.json", source_path=self.root / "MANIFEST.json")
        identity_gate()
        cat, cat_pin = catalogue(REPO)
        self.collection_events()
        runtimes = [runtime_for(self.root, cohort, summary=summary) for cohort in ("luna", "deepseek") for summary in (False, True)]
        units, selected_items, seen = [], [], set()
        index_bytes = self.collection_index.read_bytes()
        index_snapshot = self.root / "control/collection-indexes" / (sha(index_bytes) + ".json")
        raw_save(index_snapshot, index_bytes)
        indexed, metadata = indexed_items(index_snapshot, with_metadata=True)
        items = indexed
        manifest = {"schemaVersion": "zoop-input-manifest-1", "items": items,
                    "collectionIndex": file_pin(index_snapshot), "excludedUnitIds": sorted(set(self.args.exclude_unit))}
        manifest_path = self.root / "control/input-manifests" / (sha(encoded(manifest)) + ".json")
        save(manifest_path, manifest, immutable=True)
        preparation_context = {"codePins": self.dispatch_code_pins, "actor": RUN_CONFIG["processingActor"],
                               "runtimeBindings": [runtime.binding() for runtime in runtimes]}
        for item in items:
            # Refusals stay visible per input; one source cannot erase the rest
            # of the checked manifest or silently become a rights approval.
            key = sha(encoded(item))[:24]
            try:
                key = item_id(item)
                self.input_metadata(item, key, metadata)
                if key in seen:
                    continue
                seen.add(key)
                if key in self.args.exclude_unit:
                    self.queue.setdefault(key, {"state": "excluded", "reasonCode": "operator_preserved_unknown_no_retry", "inputRef": item})
                    continue
                cache = self.root / "control/input-preparations" / (sha(encoded([item, preparation_context])) + ".json")
                if cache.exists():
                    prepared = load(cache)
                    unit = prepared["unit"]
                    if sha(encoded(unit)) != prepared["unitSha256"]:
                        raise Refused("input_checkpoint_changed")
                    verify_item(unit)
                else:
                    if (self.root / "processing" / key).exists():
                        raise Refused("input_partial_checkpoint_reconcile_only")
                    unit = prepare_item(item, self.root, RUN_ID, runtimes, actor=RUN_CONFIG["processingActor"])
                    save(cache, {"unit": unit, "unitSha256": sha(encoded(unit))}, immutable=True)
            except Exception as exc:
                self.preparation_blocked(item, key, exc)
            else:
                if key in self.queue:
                    self.queue[key].pop("consumerMetadataError", None)
                units.append(unit)
                selected_items.append(item)
        planned_units = list(units)
        if not RUN_CONFIG and len(units) > MAX_UNITS:
            raise Refused("checked_unit_limit_exceeded")
        units = self.prepare_history(selected_items, units, runtimes)
        ready_ids = {unit["unitId"] for unit in units}
        for planned in planned_units:
            if planned["unitId"] not in ready_ids:
                entry = self.queue.setdefault(planned["unitId"], {})
                if not entry.get("setId"):
                    entry.update(state="awaiting-check", unit=planned, cohort=None)
        for unit in units:
            self.event("prepare", "ok", unit=unit, counts={"prepared": 1, "schemaValid": 1},
                       publication=unit["publication"],
                       artifacts=[str(Path(unit["proofPath"]).relative_to(self.root)),
                                  str(Path(unit["history"]["proofPath"]).relative_to(self.root))])
        for cohort in ("luna", "deepseek"):
            self.cohort = cohort
            for unit in units:
                if "privateProcessing" in unit:
                    unit = bind_execution(unit, {"setId": planned_set_id(unit), "fundingPolicy": runtimes[0].binding()["funding"]["version"]}, runtimes)
                namespace = sha(encoded([unit, preparation_context, cat]))
                directory = self.root / "analysis/preflight" / namespace / cohort / unit["unitId"]
                request = {"schemaVersion": "zoop-extraction-s2-2", "jobId": "check-" + cohort + "-" + unit["unitId"],
                           "provenance": PROVENANCE, "promptVersion": "zoop-overnight-native-1", "incoming": unit["observation"],
                           "catalogue": cat, "snapshot": unit["snapshot"], "topic": {"producerVersion": "zoop-topic-replay-producer-1"}}
                checkpoint = directory / "complete.json"
                if checkpoint.exists():
                    admitted = load(checkpoint)
                else:
                    if (directory / "extraction").exists():
                        raise Refused("preflight_partial_checkpoint_reconcile_only")
                    admitted = self.cli("native-admission", "extract", ["submit", "--state-dir", str(directory / "extraction"),
                        "--ingestion-state-dir", unit["ingestionStateDir"], *authority_args(unit)],
                        request, unit, directory, env=profile_env(self.root, cohort))
                if (admitted.get("state") != "queued" or admitted.get("delivery", {}).get("status") != "current"
                        or admitted.get("usage", {}).get("providerCalls") != 0):
                    raise Refused("offline_native_admission_failed")
                verify_item(unit)
                save(checkpoint, admitted, immutable=True)
        self.cohort = "luna"
        for unit in units:
            self.queue.setdefault(unit["unitId"], {"state": "queued", "unit": unit, "cohort": None})
            entry = self.queue[unit["unitId"]]
            if entry["state"] in {"queued", "awaiting-check", "preparation-blocked", "rights-blocked"} and not entry.get("setId"):
                entry.update(state="queued", unit=unit)
            if unit["unitId"] in self.consumer_metadata:
                self.queue[unit["unitId"]]["consumerMetadata"] = self.consumer_metadata[unit["unitId"]]
        self.persist_queue()
        graph = self.provision_graph()
        authority = funding(self.root)
        budget = authority.snapshot()
        policy = authority.funding
        if code_pins() != self.dispatch_code_pins:
            raise Refused("checked_code_changed")
        pins = {"schemaVersion": "zoop-overnight-check-1", "runId": RUN_ID, "root": str(self.root),
                "codePins": self.dispatch_code_pins, "catalogue": cat, "cataloguePin": cat_pin,
                "runtimeBindings": {cohort: {name: runtimes[i * 2 + j].binding() for j, name in enumerate(("pipeline", "summary"))}
                                    for i, cohort in enumerate(("luna", "deepseek"))},
                "units": units, "graph": graph,
                "funding": {"policyVersion": policy["version"], "policyIdentity": sha(encoded(policy)),
                            "totalMaxNanoUsd": authority.max_nano, "bucketMaxNanoUsd": authority.bucket_caps, "maxCalls": MAX_CALLS},
                "limits": {"admitUntil": ADMIT_UNTIL, "sendUntil": SEND_UNTIL, "drainUntil": DRAIN_UNTIL, "finishUntil": FINISH_UNTIL,
                           "stageTimeoutSeconds": TIMEOUT, "maxUnits": MAX_UNITS, "concurrency": 1, "verifierFloorNanoUsd": VERIFIER_FLOOR_NANO,
                           "historyMaxEvents": HISTORY_MAX_EVENTS, "historyMaxMembersTotal": HISTORY_MAX_MEMBERS,
                           "graphPort": GRAPH_PORT, "graphStopGraceSeconds": GRAPH_STOP_GRACE, "graphStopTimeoutSeconds": GRAPH_STOP_TIMEOUT},
                "identityPolicy": POLICY, "publicSummary": "blocked-human-public-geography-field-gates",
                "summaryMeasurement": "private-candidate-only-existing-ISSUE_SUMMARY-family", "history": history.POLICY,
                "keysLoaded": False, "paidCalls": 0}
        if RUN_CONFIG:
            pins.update(frozen_provider_approval(pins))
            pins["consumerMetadata"] = self.consumer_metadata
        if RUN_CONFIG:
            pins["runConfig"] = RUN_CONFIG
            coverage = input_coverage(items, self.queue, set(self.args.exclude_unit))
            pins["inputAuthorization"] = {
                "scope": "keyless-validated-ready-prefix", "inputManifest": file_pin(manifest_path),
                "collectionIndexPath": str(self.collection_index),
                "excludedUnitIds": sorted(set(self.args.exclude_unit)),
                "readyUnitIds": [unit["unitId"] for unit in units], "coverage": coverage,
                "preparation": getattr(self, "preparation_status", {"plannedUnits": 0, "preparedUnits": 0, "pendingUnits": 0})}
            pins["limits"] = {key: value for key, value in pins["limits"].items()
                              if key not in {"sendUntil", "drainUntil", "finishUntil", "stageTimeoutSeconds", "maxUnits"}}
            pins["limits"].update(admitFrom=RUN_CONFIG["admitFrom"], httpTimeoutSeconds=TIMEOUT,
                                  paidCliDeadline=RUN_CONFIG["finishBy"],
                                  unitScope=("prepared-subset-of-checked-input-manifest" if coverage["blocked"] or coverage["awaitingHistory"]
                                             else "whole-checked-input-manifest"),
                                  drain="admitted-finite-sets-with-finish-deadline", selection="least-served-source-then-month",
                                  finishBy=RUN_CONFIG["finishBy"], cleanupReserveSeconds=FINISH_RESERVE_SECONDS,
                                  terminationGraceSeconds=TERMINATION_GRACE_SECONDS)
        check = {"pins": pins, "checkDigest": sha(encoded(pins)), "checkedAt": now(), "budget": budget}
        if RUN_CONFIG:
            check["providerApprovalDigest"] = provider_approval_digest(pins)
        save(self.root / "control/checks" / (sha(encoded(check)) + ".json"), check, immutable=True)
        load1, load5, load15 = os.getloadavg()
        self.event("machine-context", "ok", kind="context",
                   context={"machine": platform.system().lower() + "-" + platform.machine(), "concurrency": 1,
                            "cpuCount": os.cpu_count(), "load1": load1, "load5": load5, "load15": load15,
                            "configDigest": check["checkDigest"]})
        save(self.root / "control/CHECK.json", check)
        save(self.root / "MANIFEST.json", {"schemaVersion": "zoop-overnight-manifest-1", "runId": RUN_ID, "status": "awaiting-main-greenlight",
            "checkDigest": check["checkDigest"], "pins": pins, "startedAt": self.started, "dataRetention": "all-real-artifacts-retained",
            "selectionBias": "Explicit operator-selected collection index; source/month-balanced finite checkpoints, not random or accuracy-labelled."})
        return {"status": "check-ready-for-main", "checkDigest": check["checkDigest"], "units": len(units), "paidCalls": 0,
                "providerApprovalDigest": check.get("providerApprovalDigest"),
                "inputAuthorization": pins.get("inputAuthorization")}

    def gate(self, mode):
        check = load(self.root / "control/CHECK.json")
        greenlight = load(self.root / "control/greenlight.json")
        expected = {"checkDigest": check["checkDigest"], "mode": mode, "approvedBy": "Main", "identityPolicy": POLICY}
        if RUN_CONFIG:
            if greenlight.get("schemaVersion") != "zoop-private-greenlight-2" or "enabledProfiles" in greenlight:
                raise Refused("explicit_provider_chain_required")
            expected = v2_greenlight(check, mode, self.args.canary_profile)
        elif mode == "canary":
            expected["canaryProfile"] = self.args.canary_profile
        else:
            enabled = greenlight.get("enabledProfiles")
            if enabled not in (["luna"], ["luna", "deepseek"]):
                raise Refused("explicit_enabled_profiles_required")
            expected["enabledProfiles"] = enabled
        self.enabled_profiles = (["deepseek"] if mode == "canary" and self.args.canary_profile == "deepseek-diagnostic" else ["luna", "deepseek"]) if RUN_CONFIG else (
            ["luna" if self.args.canary_profile == "luna" else "deepseek"] if mode == "canary" else greenlight["enabledProfiles"])
        if greenlight != expected or sha(encoded(check["pins"])) != check["checkDigest"]:
            raise Refused("main_greenlight_missing_or_changed")
        pins = check["pins"]
        if RUN_CONFIG and pins.get("runConfig") != RUN_CONFIG:
            raise Refused("run_config_pin_changed")
        if RUN_CONFIG and (pins["inputAuthorization"]["collectionIndexPath"] != str(self.collection_index)
                           or pins["inputAuthorization"]["excludedUnitIds"] != sorted(set(self.args.exclude_unit))):
            raise Refused("collection_index_requires_current_check")
        if code_pins() != pins["codePins"]:
            raise Refused("checked_code_changed")
        cat, cat_pin = catalogue(REPO)
        if cat != pins["catalogue"] or cat_pin != pins["cataloguePin"]:
            raise Refused("catalogue_pin_changed")
        for cohort in ("luna", "deepseek"):
            for summary, name in ((False, "pipeline"), (True, "summary")):
                if runtime_for(self.root, cohort, summary=summary).binding() != pins["runtimeBindings"][cohort][name]:
                    raise Refused("runtime_funding_pin_changed")
        for unit in pins["units"]:
            verify_item(unit)
        if RUN_CONFIG:
            require_v2_canaries(self.root, check, mode, self.args.canary_profile)
        elif mode == "run":
            for profile in (("luna", "deepseek-diagnostic") if "deepseek" in self.enabled_profiles else ("luna",)):
                canary = load(self.root / "control" / ("CANARY-" + profile + ".json"))
                if canary.get("status") != "completed" or canary.get("checkDigest") != check["checkDigest"]:
                    raise Refused("successful_enabled_profile_canary_required")
        if mode == "canary" and self.args.canary_profile == "deepseek-diagnostic":
            if self.args.canary_units != 1 or self.args.unit not in {u["unitId"] for u in pins["units"]}:
                raise Refused("diagnostic_canary_exact_single_checked_unit_required")
        if not RUN_CONFIG and remaining(ADMIT_UNTIL) <= 0:
            raise Refused("controller_admission_cutoff")
        self.pins, self.catalogue, self.check_digest = pins, cat, check["checkDigest"]
        self.dispatch_code_pins = pins["codePins"]
        self.authorized_units = {unit["unitId"]: unit for unit in pins["units"]}
        self.input_check_pin = self.retain_control("CHECK.json") if RUN_CONFIG else None
        if not (mode == "canary" and self.args.canary_profile == "deepseek-diagnostic"):
            self.provision_graph()
        return check

    def collect_calls(self, directory, state_name, job, unit):
        database = directory / state_name / ("extraction.sqlite3" if state_name == "extraction" else "relation.sqlite3")
        if not database.exists():
            return []
        from overnight_receipts import read_call_rows
        try:
            rows = read_call_rows(database, directory / "receipt-snapshots", job_id=job,
                                  state_name=state_name, child_exited=self.child_reaped and self.child is None)
        except (ValueError, OSError) as exc:
            self.event("receipt-read", "unknown", unit=unit, reason=str(exc))
            raise Refused("receipt_snapshot_incomplete", unknown=True) from None
        for row in rows:
            receipt = json.loads(row["response"]) if row.get("response") else None
            path = directory / "receipts" / (row["attempt_id"] + ".json")
            save(path, {**row, "response": receipt}, immutable=True)
            self.record_attempts(unit, row["attempt_id"], row["stage"], receipt, row["started_at"], row.get("received_at"),
                                 "released" if row["provenUnsent"] else ("received" if receipt else "unknown"), path, row.get("verdict"))
        self.call_records.extend(rows)
        return rows

    def record_attempts(self, unit, logical_id, stage, receipt, start, end, state, path, verdict=None):
        from zoop_ai_pipeline.live_runtime import CHAIN_RECEIPT, physical_attempts
        rows = physical_attempts(receipt) if receipt and receipt.get("format") == CHAIN_RECEIPT else []
        if not rows and RUN_CONFIG:
            rows = funding(self.root).provider_attempts(logical_id)
        if not rows:
            self.attempt_event(unit, logical_id, stage, receipt, start, end, state, path, verdict)
            return
        for row in rows:
            physical_path = path.parent / (row["attemptId"] + ".physical.json")
            save(physical_path, row, immutable=True)
            reason = (row.get("error") or {}).get("code")
            if receipt and row["attemptId"] == receipt.get("winnerAttemptId"):
                reason = verdict or reason
            self.attempt_event(unit, row["attemptId"], stage, row.get("receipt"), start, end, row["state"],
                               physical_path, reason, physical=row)

    def attempt_event(self, unit, attempt, stage, receipt, start, end, state, path, verdict=None, *, physical=None):
        receipt = receipt or {}
        cost = receipt.get("cost") or (physical or {}).get("cost") or {}
        bucket = "personal" if stage.startswith("verify-") or self.cohort != "luna" else "shared"
        role = "personal-typesafe" if stage.startswith("verify-") else (
            ("personal-deepseek" if RUN_CONFIG else "personal-opencode") if self.cohort != "luna" else "shared-openai")
        actual_funding = receipt.get("funding") or (physical or {}).get("funding")
        if RUN_CONFIG and actual_funding:
            role, bucket = actual_funding["accountRole"], actual_funding["bucket"]
            route = funding(self.root).funding["roles"].get(role)
            if route is None or route["bucket"] != bucket or stage not in route["stages"]:
                raise Refused("live_budget_policy_mismatch")
        elif receipt and (receipt.get("funding", {}).get("bucket") != bucket or receipt.get("funding", {}).get("accountRole") != role):
            raise Refused("live_budget_policy_mismatch")
        if attempt not in self.observed_attempts:
            self.observed_attempts.add(attempt)
            if state != "released":
                self.physical_provider_calls[role] += 1
                reported = receipt.get("model", {}).get("reported")
                if reported:
                    self.reported_models[reported] += 1
        if attempt in self.emitted_attempts:
            return
        timing = receipt.get("timing") or {}
        measured = timing.get("durationMs") if timing.get("provenance") == "http-transport-monotonic" else None
        duration = measured
        provenance = "http_request" if duration is not None else "unknown"
        if duration is None and start and end:
            duration = max(0, (instant(end) - instant(start)).total_seconds() * 1000)
            provenance = "stage_wall"
        self.event(stage, "refused" if state == "released" else ("unknown" if state == "unknown" else ("error" if verdict else "ok")),
            unit=unit, kind="attempt", start=start, attemptId=attempt, attemptState=state, endUtc=end,
            durationMs=duration, durationProvenance=provenance, fundingBucket=bucket, accountRole=role,
            requestedModel=receipt.get("model", {}).get("requested"), reportedModel=receipt.get("model", {}).get("reported"),
            usage=receipt.get("usage", {}), httpStatus=receipt.get("http", {}).get("status"), reason=verdict,
            cost={"estimatedNanoUsd": nano(cost.get("estimatedUsd")), "chargedNanoUsd": nano(cost.get("chargedUsd")),
                  "reservedNanoUsd": nano(cost.get("reservedUsd")), "basis": "opencode_allowance" if role == "personal-opencode" else "cash_estimate",
                  "allowanceNanoUsd": nano(cost.get("providerReported", {}).get("allowanceUsd")),
                  "providerBillableNanoUsd": nano(cost.get("providerReported", {}).get("billableUsd")),
                  "providerListNanoUsd": nano(cost.get("providerReported", {}).get("listUsd")),
                  "state": "released" if state == "released" else ("settled" if cost.get("settled") else "unknown")},
            artifacts=[str(path.relative_to(self.root))])
        self.emitted_attempts.add(attempt)

    def collect_summary_calls(self, unit, folder):
        for intent_path in sorted(folder.glob("*-intent.json")):
            intent = load(intent_path)
            receipt_path = folder / (intent["stage"] + "-receipt.json")
            receipt = load(receipt_path) if receipt_path.exists() else None
            failure_path = folder / (intent["stage"] + "-failure.json")
            failure = load(failure_path) if failure_path.exists() else {}
            verdict_path = folder / (intent["stage"] + "-verdict.json")
            verdict = load(verdict_path) if verdict_path.exists() else {}
            timing_path = folder / (intent["stage"] + "-timing.json")
            timing = load(timing_path) if timing_path.exists() else {}
            state = "received" if receipt else ("released" if failure.get("uncertain") is False else "unknown")
            self.record_attempts(unit, intent["attemptId"], intent["stage"], receipt, intent["startedAt"], timing.get("receivedAt"), state,
                                 receipt_path if receipt else intent_path, verdict.get("code") or failure.get("code"))
        reuse_path = folder / "verify-issue-summary-reuse.json"
        if reuse_path.exists():
            try:
                record = load(reuse_path)
                source = record["source"]
                name = source["candidateFolder"]
                if not re.fullmatch(r"[a-f0-9]{24}", name) or name == folder.name or reuse_path.is_symlink():
                    raise ValueError
                sibling = folder.parent / name
                receipt_path = sibling / "verify-issue-summary-receipt.json"
                raw = receipt_path.read_bytes()
                if sibling.is_symlink() or receipt_path.is_symlink() or sha(raw) != source["receiptSha256"]:
                    raise ValueError
                receipt = json.loads(raw)
                if receipt["attemptId"] != source["attemptId"]:
                    raise ValueError
            except (OSError, KeyError, TypeError, ValueError):
                raise Refused("receipt_snapshot_incomplete", unknown=True) from None
            consumer = {**unit, "unitId": unit["unitId"] + ":" + folder.name}
            key = (source["attemptId"], consumer["unitId"])
            if key not in self.emitted_reuses:
                self.event("verify-issue-summary", "reused", unit=consumer, kind="attempt",
                           attemptId=source["attemptId"], attemptState="reused",
                           requestedModel=receipt["model"]["requested"],
                           fundingBucket=receipt["funding"]["bucket"], accountRole=receipt["funding"]["accountRole"],
                           artifacts=[str(reuse_path.relative_to(self.root)), str(receipt_path.relative_to(self.root))])
                self.emitted_reuses.add(key)

    def export_set_receipts(self, entry):
        """Receipt-only restart path: never resumes a producer or releases money."""
        self.ensure_prior_child_exited(entry)
        if self.child is not None:
            raise Refused("receipt_child_not_exited", unknown=True)
        self.child_reaped = True
        unit = entry["unit"]
        cohort = entry.get("cohort") or "luna"
        directory = self.root / "analysis" / cohort / unit["unitId"]
        if entry.get("analysisDirectory") and Path(entry["analysisDirectory"]) != directory:
            raise Refused("receipt_directory_mismatch", unknown=True)
        self.cohort = cohort
        job = RUN_ID + "-" + cohort + "-" + unit["unitId"]
        jobs = entry.get("jobs", {"s2": {"jobId": job + "-s2", "stateName": "extraction"},
                                  "s3": {"jobId": job + "-s3", "stateName": "relation"}})
        try:
            rows = []
            for value in jobs.values():
                if value["stateName"] not in {"extraction", "relation"}:
                    raise Refused("receipt_state_invalid", unknown=True)
                rows.extend(self.collect_calls(directory, value["stateName"], value["jobId"], unit))
            for folder in sorted((directory / "candidate-summaries").glob("*")):
                if folder.is_dir():
                    self.collect_summary_calls(unit, folder)
            entry["receiptExport"] = {"status": "complete", "nativeLogicalRows": len(rows), "finishedAt": now()}
        except Exception:
            entry["receiptExport"] = {"status": "incomplete", "finishedAt": now()}
            self.persist_queue()
            raise
        self.persist_queue()

    def summaries(self, unit, directory, s2, env):
        candidates = [c for c in s2.get("eventCandidates", []) if c["state"] == "candidate"]
        save(directory / "summary-queue.json", [{"candidateId": c["eventCandidateId"], "status": "queued"} for c in candidates], immutable=True)
        outcomes = {}
        halt_unit = False
        profile = "luna" if self.cohort == "luna" else "deepseek"
        save(directory / "summary-runtime.json", self.pins["runtimeBindings"][profile]["summary"], immutable=True)
        for candidate in candidates:
            ident = candidate["eventCandidateId"]
            key = sha(ident.encode())[:24]
            folder = directory / "candidate-summaries" / key
            began, start = time.monotonic(), now()
            try:
                result = self.command([str(self.bin), *child_controller_args(), "--private-summary", str(directory), "--candidate", ident],
                                      env=env, paid=True, output=directory / ("summary-" + key + ".json"), source_unit=unit)
                available = result.get("candidateSummaryStatus") == "available"
                self.event("candidate-summary", "ok", unit={**unit, "unitId": unit["unitId"] + ":" + key}, began=began, start=start,
                           counts={"summaryEligible": 1, "summaryAvailable": int(available), "HOLD": int(result.get("candidateSummaryStatus") == "verifier-hold"),
                                   "REJECT": int(result.get("candidateSummaryStatus") == "verifier-reject")})
                outcomes[ident] = result.get("candidateSummaryStatus")
            except Refused as exc:
                self.event("candidate-summary", "unknown" if exc.unknown else "blocked", unit={**unit, "unitId": unit["unitId"] + ":" + key},
                           began=began, start=start, reason=exc.code, counts={"summaryEligible": 1, "summaryFailed": 1})
                outcomes[ident] = exc.code
                halt_unit = exc.unknown
                if exc.code in {"live_http_403", "live_http_429", "verification_budget_cannot_admit", "live_budget_verification_blocked",
                    "checked_code_changed", "live_budget_unavailable", "live_budget_policy_mismatch", "live_budget_deadline", "live_budget_deadline_increase",
                    "live_budget_exhausted_personal", "live_budget_exhausted_calls", "live_budget_exhausted_usd"}:
                    self.stop_requested = True
            finally:
                self.collect_summary_calls(unit, folder)
            if halt_unit or self.force_requested or (not RUN_CONFIG and (self.stop_requested or remaining(SEND_UNTIL) <= 0)):
                break
        save(directory / "summary-outcomes.json", outcomes)
        return {"candidates": len(candidates), "attempted": len(outcomes), "unknown": halt_unit,
                "technicalComplete": len(outcomes) == len(candidates) and all(v in {"available", "verifier-hold", "verifier-reject"} for v in outcomes.values()),
                "counts": dict(Counter(outcomes.values())), "availablePublicSummary": False}

    def record_history(self, entry, unit, s2, extraction_state_dir):
        if entry.get("queueKind") == "deepseek-diagnostic":
            return {"status": "not-recorded", "reasonCode": "diagnostic-history-excluded",
                    "candidateCount": len(s2["eventCandidates"]), "scope": "verification-only"}
        return {"status": "recorded", "scope": "ordinary",
                **history.record_ready(unit, s2, self.catalogue, extraction_state_dir)}

    def project_graph(self, entry, unit, s2, s3, directory):
        if entry.get("queueKind") == "deepseek-diagnostic":
            entry["graph"] = {"status": "not-exercised", "reasonCode": "diagnostic-graph-excluded",
                              "publication": "not-published", "scope": "verification-only"}
            self.event("private-graph", "blocked", unit=unit, reason="diagnostic-graph-excluded", counts={"stored": 0})
            return
        try:
            canonical = canonical_registry(s2, s3, self.catalogue, POLICY, unit["snapshotCanonicalMappings"])
            path = directory / "canonical.json"
            save(path, canonical, immutable=True)
            args = ["--state-dir", str(self.root / "analysis/graph"), "--relation-state-dir", str(directory / "relation"),
                    "--extraction-state-dir", str(directory / "extraction"), "--ingestion-state-dir", unit["ingestionStateDir"],
                    *authority_args(unit), "--canonical", str(path)]
            version = "night-" + self.cohort + "-" + unit["unitId"]
            graph_env = {**base_env(), "ZOOP_GRAPH_AUTH": "none"}
            self.cli("graph-freeze", "graph", ["freeze", *args], {"schemaVersion": "zoop-graph-projection-1", "versionId": version,
                     "relation": {"jobId": s3["jobId"], "inputDigest": s3["inputDigest"]}}, unit, directory, env=graph_env)
            selector = {"schemaVersion": "zoop-graph-projection-1", "versionId": version}
            projected = self.cli("graph-project", "graph", ["project", *args], selector, unit, directory, env=graph_env)
            readback = self.cli("graph-read", "graph", ["read", *args], selector, unit, directory, env=graph_env)
            if (projected.get("publication") != "not-published" or readback.get("publication") != "not-published"
                    or projected.get("state") != "ready" or readback.get("delivery", {}).get("status") != "current"
                    or readback.get("verification", {}).get("marker") != "matched"):
                raise Refused("private_graph_readback_invariant")
            entry["graph"] = {"status": "projected", "versionId": version, "publication": "not-published"}
            self.event("private-graph", "ok", unit=unit, counts={"stored": readback["verification"]["edges"]},
                       checks={"graphIntegrity": {"passed": 1, "total": 1}})
        except (Refused, ValueError) as exc:
            code = exc.code if isinstance(exc, Refused) else str(exc)
            entry["graph"] = {"status": "blocked", "code": code}
            self.event("private-graph", "blocked", unit=unit, reason=code)

    def process(self, entry):
        unit = entry["unit"]
        if RUN_CONFIG and not entry.get("setId") and unit != self.authorized_units.get(unit["unitId"]):
            raise Refused("input_not_in_current_check")
        self.active = unit
        if RUN_CONFIG and entry.get("setId"):
            self.ensure_prior_child_exited(entry)
            if funding(self.root).set_status(entry["setId"]) == "admitted":
                self.active_set, self.active_entry = entry["setId"], entry
        verify_item(unit)
        budget = funding(self.root).snapshot()
        if budget["verificationBlocked"]:
            raise Refused("live_budget_verification_blocked")
        if nano(budget["buckets"]["personal"]["remainingUsd"]) < VERIFIER_FLOOR_NANO:
            raise Refused("verification_budget_cannot_admit")
        routed = (self.root / "control/shared-refusal.json").exists()
        self.cohort = ("deepseek-diagnostic" if entry.get("queueKind") == "deepseek-diagnostic" else
                       ("deepseek" if not RUN_CONFIG and (routed or nano(budget["buckets"]["shared"]["remainingUsd"]) == 0) else "luna"))
        if self.cohort == "deepseek" and "deepseek" not in self.enabled_profiles and not (RUN_CONFIG and entry.get("setId")):
            raise Refused("live_budget_exhausted_shared")
        resuming = bool(RUN_CONFIG and entry.get("setId"))
        if resuming:
            self.ensure_prior_child_exited(entry)
            selected = {"snapshot": unit["snapshot"], "coverage": unit["comparisonCoverage"],
                        "canonicalMappings": unit["snapshotCanonicalMappings"]}
            self.cohort = entry["cohort"]
        else:
            selected = history.snapshot_for(unit, self.catalogue, max_events=HISTORY_MAX_EVENTS, max_members=HISTORY_MAX_MEMBERS)
            unit = selected.get("unit", unit)
            unit = {**unit, "snapshot": selected["snapshot"], "comparisonCoverage": selected["coverage"],
                    "snapshotCanonicalMappings": selected["canonicalMappings"]}
            entry["unit"] = unit
        self.active = unit
        if RUN_CONFIG:
            self.sync_stop()
            set_id = entry.get("setId") or planned_set_id(unit, entry.get("queueKind", "ordinary"))
            if not resuming and "privateProcessing" in unit:
                runtimes = [runtime_for(self.root, c, summary=s) for c in ("luna", "deepseek") for s in (False, True)]
                unit = bind_execution(unit, {"setId": set_id, "fundingPolicy": runtimes[0].binding()["funding"]["version"]}, runtimes)
                entry["unit"], self.active = unit, unit
            unit_digest = source_identity(unit)
            if resuming:
                try:
                    funding(self.root).resume_set(set_id, unit_digest)
                except Exception as exc:
                    if entry["state"] != "admitting" or getattr(exc, "code", None) != "live_set_not_admitted":
                        raise
                    funding(self.root).admit_set(set_id, unit_digest, set_plan(unit))
            else:
                # Persist identity first; a crash on either side of the atomic
                # admission never creates a replacement ID or resets counters.
                entry.update(setId=set_id, unitDigest=unit_digest, cohort=self.cohort, state="admitting")
                self.persist_queue()
                funding(self.root).admit_set(set_id, unit_digest, set_plan(unit))
            self.active_set, self.active_entry = set_id, entry
        load1, load5, load15 = os.getloadavg()
        self.event("machine-context", "ok", unit=unit, kind="context",
                   context={"machine": platform.system().lower() + "-" + platform.machine(), "concurrency": 1,
                            "cpuCount": os.cpu_count(), "load1": load1, "load5": load5, "load15": load15,
                            "concurrentWorkloads": True, "configDigest": self.check_digest})
        for cohort_attempt in range(1 if RUN_CONFIG else 2):
            entry.update(state="started", cohort=self.cohort, startedAt=now())
            self.persist_queue()
            directory = self.root / "analysis" / self.cohort / unit["unitId"]
            save(directory / "unit.json", unit, immutable=True)
            save(directory / "comparison-coverage.json", selected["coverage"], immutable=True)
            self.event("comparison-coverage", "ok" if selected["coverage"]["selectedEvents"] else "empty", unit=unit,
                       counts={"candidates": selected["coverage"]["eligibleBeforeDedupAndBounds"],
                               "prepared": selected["coverage"]["selectedEvents"], "excluded": sum(selected["coverage"]["excluded"].values())},
                       artifacts=[str((directory / "comparison-coverage.json").relative_to(self.root))])
            env = profile_env(self.root, self.cohort)
            job = RUN_ID + "-" + self.cohort + "-" + unit["unitId"]
            entry["analysisDirectory"] = str(directory)
            entry["jobs"] = {"s2": {"jobId": job + "-s2", "stateName": "extraction"},
                             "s3": {"jobId": job + "-s3", "stateName": "relation"}}
            self.persist_queue()
            request = {"schemaVersion": "zoop-extraction-s2-2", "jobId": job + "-s2", "provenance": PROVENANCE,
                       "promptVersion": "zoop-overnight-native-1", "incoming": unit["observation"], "catalogue": self.catalogue,
                       "snapshot": unit["snapshot"], "topic": {"producerVersion": "zoop-topic-replay-producer-1"}}
            s2_args = ["--state-dir", str(directory / "extraction"), "--ingestion-state-dir", unit["ingestionStateDir"], *authority_args(unit)]
            try:
                s2 = self.cli("s2-result", "extract", ["run", *s2_args, *([] if RUN_CONFIG else ["--initial-only"])],
                              request, unit, directory, paid=True, env=env)
            finally:
                calls = self.collect_calls(directory, "extraction", job + "-s2", unit)
            failure = (s2.get("failure") or {}).get("code")
            if failure == "live_budget_exhausted_shared" and any(c["provenUnsent"] for c in calls):
                self.shared_refusal(unit, s2["jobId"], calls)
            if (not RUN_CONFIG and failure == "live_budget_exhausted_shared" and self.cohort == "luna" and "deepseek" in self.enabled_profiles
                    and calls and all(c["provenUnsent"] for c in calls)):
                save(directory / "fallback-proof.json", {"reason": failure, "allCallsProvenUnsent": True, "newCohort": "deepseek"}, immutable=True)
                self.cohort = "deepseek"
                continue
            if s2.get("state") != "ready" or s2.get("delivery", {}).get("status") != "current":
                raise Refused(failure or "s2_not_ready", unknown=s2.get("state") == "reconciling")
            break
        if (s2.get("provenance") != PROVENANCE or s2.get("usage", {}).get("executionMode") != "live"
                or s2.get("usage", {}).get("replayCalls", 0) != 0):
            raise Refused("live_history_provider_provenance_required")
        recorded = self.record_history(entry, unit, s2, directory / "extraction")
        save(directory / "history-record.json", recorded, immutable=True)
        entry["comparison"] = {"cohort": self.cohort, "selectedPriorEvents": selected["coverage"]["selectedEvents"],
                               "completedComparisons": s2["counts"]["comparisons"], "outcomes": s2["counts"]["effectiveRelations"],
                               "scope": "bounded-prior-candidates-not-global-or-gold"}
        save(directory / "comparison-outcomes.json", entry["comparison"], immutable=True)
        self.event("compare", "ok" if s2["counts"]["comparisons"] else "empty", unit=unit,
                   counts={"requests": s2["counts"]["comparisons"], "SAME": s2["counts"]["effectiveRelations"].get("SAME", 0),
                           "HOLD": s2["counts"]["effectiveRelations"].get("HOLD", 0)},
                   artifacts=[str((directory / "comparison-coverage.json").relative_to(self.root)),
                              str((directory / "comparison-outcomes.json").relative_to(self.root))])
        self.persist_queue()
        dispositions = Counter((c.get("disposition") or {}).get("status", "unknown") for c in s2["eventCandidates"])
        self.event("s2", "ok" if s2["eventCandidates"] else "empty", unit=unit,
            counts={"documents": 1, "candidates": len(s2["eventCandidates"]), "SAME": dispositions["same-event-candidate"],
                    "NEW": dispositions["new-event-candidate"], "HOLD": dispositions["held"]})
        from zoop_ai_pipeline.extraction_contracts import Catalogue, Mention
        from zoop_ai_pipeline.extraction_replay import company_names, participants_valid
        names = company_names(Catalogue.model_validate(self.catalogue))
        for candidate in s2["eventCandidates"]:
            citations = candidate["citations"]
            participant_identity = participants_valid(Mention.model_validate(candidate["mention"]), names)
            decision = (candidate.get("disposition") or {}).get("status", candidate["state"])
            self.event("event-candidate", "ok" if candidate["state"] == "candidate" else "refused",
                unit={**unit, "unitId": candidate["eventCandidateId"]}, kind="record",
                sample={"recordId": candidate["eventCandidateId"], "recordType": "event-candidate", "decision": decision,
                        "artifact": str((directory / "s2-result.json").relative_to(self.root))},
                checks={"identity": {"passed": int(participant_identity), "total": 1},
                        "citationExact": {"passed": sum("error" not in c for c in citations), "total": len(citations)}})
        common = ["--state-dir", str(directory / "relation"), "--extraction-state-dir", str(directory / "extraction"),
                  "--ingestion-state-dir", unit["ingestionStateDir"], *authority_args(unit)]
        s3_request = {"schemaVersion": "zoop-relation-s3", "jobId": job + "-s3", "provenance": PROVENANCE,
                      "upstream": {"jobId": s2["jobId"], "inputDigest": s2["inputDigest"]}}
        self.cli("s3-submit", "relation", ["submit", *common], s3_request, unit, directory, env=profile_env(self.root, self.cohort))
        try:
            s3 = self.cli("s3-result", "relation", ["resume", *common, *([] if RUN_CONFIG else ["--initial-only"])],
                          {"schemaVersion": "zoop-relation-s3", "jobId": job + "-s3"}, unit, directory, paid=True, env=env)
        finally:
            s3_calls = self.collect_calls(directory, "relation", job + "-s3", unit)
        entry["stageProfiles"] = {"s2": self.cohort, "s3": self.cohort}
        s3_artifact = directory / "s3-result.json"
        if (s3.get("failure") or {}).get("code") == "live_budget_exhausted_shared" and any(c["provenUnsent"] for c in s3_calls):
            self.shared_refusal(unit, s3["jobId"], s3_calls)
        if (not RUN_CONFIG and (s3.get("failure") or {}).get("code") == "live_budget_exhausted_shared" and self.cohort == "luna"
                and "deepseek" in self.enabled_profiles and s3_calls and all(c["provenUnsent"] for c in s3_calls)):
            # S3 owns its runtime independently; preserve paid Luna S2 and freeze a NEW S3.
            save(directory / "s3-fallback-proof.json", {"allS3CallsProvenUnsent": True, "upstreamReused": s3_request["upstream"],
                 "oldJobId": s3_request["jobId"], "newProfile": "deepseek", "duplicateS2Calls": 0}, immutable=True)
            self.cohort = "mixed-luna-deepseek"
            env = profile_env(self.root, self.cohort)
            s3_request = {**s3_request, "jobId": job + "-s3-deepseek"}
            self.cli("s3-fallback-submit", "relation", ["submit", *common], s3_request, unit, directory,
                     env=profile_env(self.root, self.cohort))
            try:
                s3 = self.cli("s3-fallback-result", "relation", ["resume", *common, *([] if RUN_CONFIG else ["--initial-only"])],
                    {"schemaVersion": "zoop-relation-s3", "jobId": s3_request["jobId"]}, unit, directory, paid=True, env=env)
            finally:
                self.collect_calls(directory, "relation", s3_request["jobId"], unit)
            entry["stageProfiles"]["s3"] = "deepseek"
            s3_artifact = directory / "s3-fallback-result.json"
            self.persist_queue()
        if s3.get("state") != "ready" or s3.get("delivery", {}).get("status") != "current":
            raise Refused((s3.get("failure") or {}).get("code") or "s3_not_ready", unknown=s3.get("state") == "reconciling")
        statuses = Counter(r["eligibility"]["status"] for r in s3["relations"])
        self.event("s3", "ok" if s3["relations"] else "empty", unit=unit,
            counts={"candidates": len(s3["relations"]), "eligible": statuses["eligible"], "ALLOW": statuses["eligible"],
                    "HOLD": statuses["hold"], "REJECT": statuses["reject"], "pending": statuses["pending"]})
        for relation in s3["relations"]:
            verdicts = Counter(claim["verdict"] for event in relation["history"] if event["kind"] == "verdict"
                               for claim in (event.get("claims") or []))
            self.event("relation-candidate", "ok", unit={**unit, "unitId": relation["relationCandidateId"]}, kind="record",
                counts={key: value for key, value in verdicts.items() if key in {"supported", "insufficient", "contradicted"}},
                sample={"recordId": relation["relationCandidateId"], "recordType": "relation-candidate",
                        "decision": relation["eligibility"]["status"], "artifact": str(s3_artifact.relative_to(self.root))})
        self.project_graph(entry, unit, s2, s3, directory)
        self.persist_queue()
        entry["summaries"] = self.summaries(unit, directory, s2, env)
        graph_complete = entry.get("queueKind") == "deepseek-diagnostic" or entry.get("graph", {}).get("status") == "projected"
        complete = graph_complete and entry["summaries"]["technicalComplete"]
        entry.update(state="unknown" if entry["summaries"].get("unknown") else
                     "completed" if complete else "measured-with-blockers", finishedAt=now(), cohort=self.cohort)
        self.persist_queue()

    def shared_refusal(self, unit, job_id, calls):
        path = self.root / "control/shared-refusal.json"
        if not path.exists():
            save(path, {"unitId": unit["unitId"], "jobId": job_id, "reason": "live_budget_exhausted_shared",
                        "provenUnsentAttempts": [c["attempt_id"] for c in calls if c["provenUnsent"]],
                        "routingScope": "new-queued-units-only-no-repeat-paid-upstream", "observedAt": now()}, immutable=True)

    def collection_events(self):
        """Import bounded metadata, correlating original INDEX entries by event/unit ID."""
        from overnight_metrics import _read_events, normalize_event, record_event
        index = self.collection_index
        if not index.exists():
            return
        cursor = self.root / "control/collection-events.json"
        seen = load(cursor) if cursor.exists() else {}
        observations = load(index).get("observations", [])
        journal = self.root / "events.jsonl"
        recorded = {}
        if any(event["eventId"] not in seen for event in observations) and journal.exists():
            events, integrity = _read_events(journal)
            if integrity["status"] != "complete":
                raise Refused("collection_journal_incomplete")
            recorded = {event["eventId"]: event for event in events}
        changed = False
        try:
            for event in observations:
                event = {"schemaVersion": "zoop-overnight-event-1", **event}
                ident, digest = event["eventId"], sha(encoded(event))
                if ident in seen:
                    if seen[ident] != digest:
                        raise Refused("collection_event_changed")
                    continue
                projected = {**event, "sourceId": identifier(event.get("sourceId"))}
                if ident in recorded:
                    if recorded[ident] != normalize_event(projected):
                        raise Refused("collection_event_changed")
                else:
                    recorded[ident] = normalize_event(projected)
                    record_event(journal, projected)
                seen[ident] = digest
                changed = True
        finally:
            if changed:
                save(cursor, seen)

    def preparation_blocked(self, item, key, exc):
        code = getattr(exc, "code", None) or (str(exc) if isinstance(exc, ValueError) else "input_preparation_failed")
        rights = code in {"item_model_rights_unproven", "source_unauthorized", "source_operation_denied",
                          "source_purpose_or_recipient_denied", "naver_search_ai_prohibited"}
        freshness = item.get("freshness", "unknown")
        if freshness not in ("fresh", "backfill", "reused", "unknown"):
            freshness = "unknown"
        if key not in self.queue:
            self.queue[key] = {"state": "rights-blocked" if rights else "preparation-blocked",
                               "code": code, "sourceId": item.get("sourceId"), "freshness": freshness}
        else:
            self.queue[key]["consumerMetadataError"] = {"code": code, "observedAt": now()}
        if key in self.consumer_metadata:
            self.queue[key]["consumerMetadata"] = self.consumer_metadata[key]
        self.event("prepare", "blocked", unit={"unitId": key, "sourceId": item.get("sourceId"), "freshness": freshness},
                   reason=code, counts={"rightsBlocked": 1} if rights else {})

    def refresh(self):
        runtimes = [runtime_for(self.root, c, summary=s) for c in ("luna", "deepseek") for s in (False, True)]
        self.collection_events()
        items, units, selected_ids = [], [], set()
        indexed, metadata = indexed_items(self.collection_index, with_metadata=True)
        for item in indexed:
            key = sha(encoded(item))[:24]
            try:
                key = item_id(item)
                self.input_metadata(item, key, metadata)
                if key in self.queue or key in selected_ids or (not RUN_CONFIG and len(self.queue) + len(units) >= MAX_UNITS):
                    continue
                if RUN_CONFIG:
                    self.queue[key] = {"state": "awaiting-check", "inputRef": item, "sourceId": item["sourceId"], "cohort": None}
                    if key in self.consumer_metadata:
                        self.queue[key]["consumerMetadata"] = self.consumer_metadata[key]
                    continue
                units.append(prepare_item(item, self.root, RUN_ID, runtimes, actor=RUN_CONFIG["processingActor"]))
                items.append(item)
                selected_ids.add(key)
            except Exception as exc:
                self.preparation_blocked(item, key, exc)
        if units:
            try:
                prepared = self.prepare_history(items, units, runtimes)
            except Exception as exc:
                for item, unit in zip(items, units):
                    self.preparation_blocked(item, unit["unitId"], exc)
            else:
                for unit in prepared:
                    self.queue[unit["unitId"]] = {"state": "queued", "unit": unit, "cohort": None}
                    if unit["unitId"] in self.consumer_metadata:
                        self.queue[unit["unitId"]]["consumerMetadata"] = self.consumer_metadata[unit["unitId"]]
                    self.event("prepare", "ok", unit=unit, counts={"prepared": 1, "schemaValid": 1}, publication=unit["publication"],
                               artifacts=[str(Path(unit["history"]["proofPath"]).relative_to(self.root))])
        self.persist_queue()

    def fair_queue(self, queued):
        """Least-served source, then publication month; deterministic across restarts."""
        source_counts, month_counts = Counter(), Counter()
        def stratum(entry):
            unit = entry["unit"]
            published = entry.get("consumerMetadata", {}).get("publicationDay") or unit.get("publication", {}).get("publishedAt")
            month = published[:7] if isinstance(published, str) and re.match(r"^\d{4}-\d{2}", published) else "unknown"
            return unit["sourceId"], month
        for entry in self.queue.values():
            if "unit" in entry and entry.get("setId") and entry["state"] != "admitting":
                source, month = stratum(entry)
                source_counts[source] += 1
                month_counts[(source, month)] += 1
        return sorted(queued, key=lambda pair: (source_counts[stratum(pair[1])[0]],
                                               month_counts[stratum(pair[1])], *stratum(pair[1]), pair[0]))

    def run(self, mode):
        try:
            if RUN_CONFIG:
                for entry in self.queue.values():
                    self.ensure_prior_child_exited(entry)
                    if entry.get("setId") and entry["state"] not in {"admitting", "started", "queued"}:
                        self.export_set_receipts(entry)
                        if funding(self.root).set_status(entry["setId"]) == "admitted":
                            terminal = "completed" if entry["state"] == "completed" else "unknown" if entry["state"] == "unknown" else "blocked"
                            funding(self.root).finish_set(entry["setId"], terminal)
            self.gate(mode)
            if mode == "canary" and self.args.canary_profile == "deepseek-diagnostic":
                unit = next(u for u in self.pins["units"] if u["unitId"] == self.args.unit)
                self.queue.setdefault(unit["unitId"] + ":deepseek-diagnostic",
                                      {"state": "queued", "unit": unit, "cohort": None, "queueKind": "deepseek-diagnostic"})
            for entry in self.queue.values():
                if not RUN_CONFIG and entry["state"] == "started":
                    entry.update(state="unknown", reasonCode="prior_controller_interrupted_no_retry")
            self.persist_queue()
            execution_kind = "deepseek-diagnostic" if mode == "canary" and self.args.canary_profile == "deepseek-diagnostic" else "ordinary"
            initial = queue_totals(self.queue)[execution_kind]["completed"]
            admitted = 0
            batch_entries = []
            self.observed_attempts.clear()
            self.physical_provider_calls.clear()
            self.reported_models.clear()
        except BaseException:
            self.stop_owned_graph()
            raise
        try:
            while True:
                self.sync_stop()
                if self.force_requested or self.pause_requested:
                    break
                can_admit = not self.stop_requested and remaining(ADMIT_UNTIL) > 0
                if not RUN_CONFIG and not can_admit:
                    break
                kind = "deepseek-diagnostic" if mode == "canary" and self.args.canary_profile == "deepseek-diagnostic" else "ordinary"
                resumed = [(key, entry) for key, entry in self.queue.items()
                           if RUN_CONFIG and entry["state"] in {"admitting", "started"}
                           and entry.get("queueKind", "ordinary") == kind]
                if mode == "run" and can_admit and not resumed:
                    self.refresh()
                    self.sync_stop()
                    can_admit = not self.stop_requested and remaining(ADMIT_UNTIL) > 0
                queued = [(key, entry) for key, entry in self.queue.items()
                          if can_admit and entry["state"] == "queued" and entry.get("queueKind", "ordinary") == kind
                          and (not RUN_CONFIG or entry["unit"]["unitId"] in self.authorized_units)]
                if RUN_CONFIG:
                    queued = self.fair_queue(queued)
                queued = resumed + queued
                if self.args.unit:
                    queued = [(key, entry) for key, entry in queued if entry["unit"]["unitId"] == self.args.unit]
                if not queued:
                    if RUN_CONFIG or not can_admit or mode == "canary" or self.args.unit:
                        break
                    time.sleep(min(15, max(0.1, remaining(ADMIT_UNTIL))))
                    continue
                if ((mode == "canary" and admitted >= self.args.canary_units)
                        or (mode == "run" and self.args.batch_units is not None and len(batch_entries) >= self.args.batch_units)
                        or (not RUN_CONFIG and admitted >= MAX_UNITS)):
                    break
                key, entry = queued[0]
                if not RUN_CONFIG:
                    admitted += 1
                try:
                    batch_entries.append(entry)
                    self.process(entry)
                except Exception as exc:
                    code = getattr(exc, "code", None) or (str(exc) if isinstance(exc, ValueError) else "controller_internal_" + type(exc).__name__)
                    unknown = bool(getattr(exc, "unknown", False) or getattr(exc, "uncertain", False)
                                   or code == "live_set_reconcile_only")
                    entry.update(state="unknown" if unknown else "blocked", reasonCode=code, finishedAt=now())
                    self.event("unit", "unknown" if unknown else "blocked", unit=entry["unit"], reason=code)
                    self.persist_queue()
                    if (mode == "canary" or (code == "live_budget_exhausted_shared" and "deepseek" not in self.enabled_profiles)
                            or code in {"verification_budget_cannot_admit", "live_budget_verification_blocked",
                                "checked_code_changed", "live_budget_unavailable", "live_budget_policy_mismatch", "live_budget_deadline", "live_budget_deadline_increase",
                                "live_http_403", "live_http_429", "live_budget_exhausted_personal", "live_budget_exhausted_calls", "live_budget_exhausted_usd"}):
                        break
                finally:
                    if RUN_CONFIG and self.active_set and entry["state"] not in {"admitting", "started"}:
                        admitted += 1
                        try:
                            self.export_set_receipts(entry)
                        except Exception as export_error:
                            entry.update(state="unknown", reasonCode=getattr(export_error, "code", "receipt_export_incomplete"))
                            entry["receiptExport"] = {"status": "incomplete", "finishedAt": now(), "reasonCode": entry["reasonCode"]}
                            self.persist_queue()
                        terminal = ("unknown" if entry["state"] == "unknown" else
                                    "completed" if entry["state"] == "completed" else "blocked")
                        funding(self.root).finish_set(self.active_set, terminal)
                    self.active, self.active_set, self.active_entry = None, None, None
        finally:
            if RUN_CONFIG:
                self.sync_stop()
            self.stop_owned_graph()
        work_totals = queue_totals(self.queue)
        completed = work_totals[execution_kind]["completed"] - initial
        comparisons = {}
        ordinary_comparisons = work_totals["ordinary"]["completedComparisons"]
        for entry in self.queue.values():
            evidence = entry.get("comparison")
            if evidence is None:
                continue
            cohort = evidence["cohort"]
            totals = comparisons.setdefault(cohort, {"unitsCompared": 0, "completedComparisons": 0, "outcomes": {}})
            totals["unitsCompared"] += int(evidence["completedComparisons"] > 0)
            totals["completedComparisons"] += evidence["completedComparisons"]
            for outcome, count in evidence["outcomes"].items():
                totals["outcomes"][outcome] = totals["outcomes"].get(outcome, 0) + count
        if RUN_CONFIG and any(entry.get("setId") and funding(self.root).set_status(entry["setId"]) == "admitted"
                              for entry in self.queue.values()):
            raise Refused("owned_admitted_sets_not_terminal")
        result = {"schemaVersion": "zoop-overnight-result-1", "status": "completed" if admitted > 0 and completed == admitted else "blocked",
                  "mode": mode, "canaryProfile": self.args.canary_profile if mode == "canary" else None,
                  "checkDigest": self.check_digest, "admitted": admitted, "completed": completed, "completionScope": execution_kind,
                  "ordinaryCompletedUnits": work_totals["ordinary"]["completed"],
                  "diagnosticCompletedUnits": work_totals["deepseek-diagnostic"]["completed"],
                  "graphProjectionScope": "deliberately-not-exercised-diagnostic" if execution_kind == "deepseek-diagnostic" else "ordinary-private",
                  "enabledProfiles": self.enabled_profiles,
                  "fallbackStatus": ("diagnostic-only-no-production-authority" if execution_kind == "deepseek-diagnostic" else
                                     "enabled" if "deepseek" in self.enabled_profiles else "blocked-by-explicit-main-scope"),
                  "queue": work_totals["ordinary"]["states"], "queueScope": "ordinary",
                  "diagnosticQueue": work_totals["deepseek-diagnostic"]["states"], "finishedAt": now(), "budget": funding(self.root).snapshot(),
                  "comparisonCoverage": {"byCohort": comparisons, "ordinaryCompletedComparisons": ordinary_comparisons,
                                         "status": "measured-bounded-candidate-comparisons" if ordinary_comparisons else "not-exercised",
                                         "globallyComplete": False, "goldAccuracyMeasured": False},
                  "publicSummary": "blocked-human-public-geography-field-gates", "publication": "not-published"}
        if RUN_CONFIG:
            result.pop("enabledProfiles")
            result.pop("fallbackStatus")
            result.update(frozen_provider_approval(self.pins))
            result["providerApprovalDigest"] = provider_approval_digest(self.pins)
            result["readinessScope"] = "provider-and-runtime-only-not-input-authorization"
            result["batchEnd"] = "checkpoint-pause" if self.pause_requested else "global-stop" if self.stop_requested else "checked-batch-end"
            result["inputAuthorization"] = {"checkDigest": self.check_digest, "check": self.input_check_pin,
                                             "readyUnitIds": list(self.authorized_units)}
            result.update(physicalProviderCalls=dict(self.physical_provider_calls), reportedModels=dict(self.reported_models),
                          providerUsageScope="physical-attempts-of-sets-processed-in-this-batch",
                          canaryLabel=("direct-deepseek-diagnostic" if execution_kind == "deepseek-diagnostic" else
                                       "openai-primary-with-direct-deepseek-fallback") if mode == "canary" else None)
            result["finalization"] = {"scope": "controller-owned-sets",
                                      "outstandingSharedSets": result["budget"]["sets"].get("admitted", 0),
                                      "overallOwner": "Main"}
            result["receiptCoverage"] = "incomplete" if any(
                entry.get("receiptExport", {}).get("status") == "incomplete" for entry in self.queue.values()) else "complete"
        if mode == "run" and ordinary_comparisons == 0:
            result["status"] = "comparison-coverage-gap"
        if RUN_CONFIG and mode == "canary":
            result["canaryUnitPins"] = []
            for entry in batch_entries:
                if entry["state"] == "completed":
                    unit = entry["unit"]
                    path = Path(entry["analysisDirectory"]) / "unit.json"
                    result["canaryUnitPins"].append({**file_pin(path), "unitId": unit["unitId"], "sourceIdentity": source_identity(unit)})
            result = seal_canary_report(self.root, result)
        save(self.root / "control" / ("CANARY-" + self.args.canary_profile + ".json" if mode == "canary" else "RUN.json"), result)
        for bucket, totals in result["budget"]["buckets"].items():
            self.event("funding", "ok", kind="budget", fundingBucket=bucket,
                       budget={"maxNanoUsd": nano(totals["maxUsd"]), "chargedNanoUsd": nano(totals["chargedUsd"]),
                               "actualNanoUsd": nano(totals["actualUsd"]), "reservedNanoUsd": nano(totals["reservedUsd"]),
                               "unknownExposureNanoUsd": nano(totals["unknownUsd"]), "remainingNanoUsd": nano(totals["remainingUsd"]),
                               "calls": totals["calls"], "maxCalls": MAX_CALLS})
        self.collection_events()
        self.event("controller-batch", "ok" if result["status"] == "completed" else "blocked", kind="batch",
                   began=self.started_monotonic, start=self.started, durationProvenance="batch_wall",
                   counts={"documents": admitted, "prepared": completed})
        from overnight_metrics import summarize
        metrics = summarize(self.root)
        sample = metrics["sampleIndex"]
        sample["populationScope"] = "cohort-tagged-including-diagnostic-not-production-unique-events"
        sample["ordinaryPopulationN"] = sum(row["populationN"] for row in sample["strata"] if row["stratum"]["cohort"] != "deepseek-diagnostic")
        sample["diagnosticPopulationN"] = sum(row["populationN"] for row in sample["strata"] if row["stratum"]["cohort"] == "deepseek-diagnostic")
        save(self.root / "control/METRICS.json", metrics)
        manifest = load(self.root / "MANIFEST.json")
        manifest.update(status=result["status"], latest=result, queueFile="control/queue.json")
        save(self.root / "MANIFEST.json", manifest)
        return result

    def stop_owned_graph(self):
        if self.graph:
            container = self.graph["containerId"]
            began = now()
            timed_out = False
            try:
                child = subprocess.run(["docker", "--context", "orbstack", "stop", "--time", str(GRAPH_STOP_GRACE), container],
                                       env=base_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=GRAPH_STOP_TIMEOUT)
                exit_code = child.returncode
            except subprocess.TimeoutExpired:
                timed_out, exit_code = True, None
            observed = None
            try:
                inspection = subprocess.run(["docker", "--context", "orbstack", "inspect", "--format", GRAPH_INSPECT, container],
                                            env=base_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
                if inspection.returncode == 0:
                    observed = json.loads(inspection.stdout)
            except (subprocess.TimeoutExpired, ValueError):
                pass
            stopped = observed is not None and observed["id"] == container and observed["running"] is False
            container_exit = observed["exitCode"] if observed else None
            termination = ("forced-137" if stopped and container_exit == 137 else
                           "graceful-exit-0" if stopped and container_exit == 0 else
                           "stopped-nonzero" if stopped else "stop-unconfirmed")
            previous = self.retain_control("graph-stop.json")
            save(self.root / "control/graph-stop.json", {"containerId": container, "exitCode": exit_code,
                "stopStartedAt": began, "stoppedAt": now(), "graceSeconds": GRAPH_STOP_GRACE, "commandTimeoutSeconds": GRAPH_STOP_TIMEOUT,
                "commandTimedOut": timed_out, "containerStopped": stopped, "containerExitCode": container_exit,
                "oomKilled": observed["oomKilled"] if observed else None, "termination": termination,
                "previousReceipt": previous, "dataRetained": True})
            if not stopped:
                raise Refused("graph_stop_unconfirmed")


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--canary", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--private-summary", type=Path, help=argparse.SUPPRESS)
    group.add_argument("--prepare-history", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--candidate", help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--run-config", type=Path, help="Explicit zoop-private-run-4 JSON; new root, exact funding, admission window and finishBy")
    parser.add_argument("--collection-index", type=Path, help="Explicit current collection INDEX; revision roots are allowed")
    parser.add_argument("--batch-units", type=int, help="--run only: stop after this many checked units, without closing admission")
    parser.add_argument("--exclude-unit", action="append", default=[], help="Preserved unknown input unitId; pinned by CHECK, never retried")
    parser.add_argument("--credential-env", type=Path, help="Paid v2 only: Main-selected literal credential file; --check never opens it")
    parser.add_argument("--preparation-chunks", type=int, help="--check only: admit at most this many additional finite history chunks")
    parser.add_argument("--unit", help="Exact checked unitId; canary purposive selection is recorded")
    parser.add_argument("--canary-units", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--canary-profile", choices=("luna", "deepseek-diagnostic"), default="luna")
    return parser.parse_args(argv)


def main(argv=None):
    os.umask(0o077)
    args = parse(argv)
    try:
        configure(args)
        if args.preparation_chunks is not None and (not args.check or args.preparation_chunks < 1):
            raise Refused("preparation_chunk_limit_invalid")
        if args.batch_units is not None and (not args.run or args.batch_units < 1):
            raise Refused("batch_unit_limit_invalid")
        if any(not re.fullmatch(r"[a-f0-9]{24}", unit) for unit in args.exclude_unit):
            raise Refused("excluded_unit_invalid")
        if not (args.prepare_history or args.private_summary):
            if args.collection_index is None or args.collection_index.is_symlink() or not args.collection_index.is_file():
                raise Refused("explicit_collection_index_required")
            args.collection_index = args.collection_index.resolve()
        if args.private_summary:
            result = private_summary_child(args.private_summary, args.candidate)
            print(json.dumps(result))
            return 0
        if args.root.resolve() != ROOT or args.root.is_symlink():
            raise Refused("authorized_runtime_root_required")
        args.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.root.stat().st_mode & 0o077:
            raise Refused("runtime_root_not_private")
        control = args.root / "control"
        control.mkdir(exist_ok=True, mode=0o700)
        save(control / "run-config.json", RUN_CONFIG, immutable=True)
        if args.prepare_history:
            from zoop_ai_pipeline.live_runtime import LiveRuntime
            raw = sys.stdin.buffer.read(64 * 1024 * 1024 + 1)
            if len(raw) > 64 * 1024 * 1024:
                raise Refused("history_preparation_input_limit")
            payload = json.loads(raw)
            if code_pins() != payload["codePins"]:
                raise Refused("checked_code_changed")
            for unit in payload["units"]:
                verify_item(unit)
            runtimes = [LiveRuntime.from_binding(binding) for binding in payload["runtimeBindings"]]
            preparation_root = Path(payload["preparationRoot"])
            if (not re.fullmatch(r"[a-f0-9]{64}", payload["planId"])
                    or preparation_root != args.root / "preparation-v2" / payload["planId"] or preparation_root.is_symlink()):
                raise Refused("history_preparation_namespace_invalid")
            if preparation_root.exists():
                raise Refused("history_partial_checkpoint_reconcile_only")
            context_id = sha(encoded({key: payload[key] for key in ("runtimeBindings", "codePins", "actor")}))
            for started_path in (args.root / "preparation-v2").glob("*/started.json"):
                started = load(started_path)
                if started["contextId"] == context_id and not (
                        control / "history-preparations/v2/chunks" / started_path.parent.name / "complete.json").exists():
                    raise Refused("history_partial_checkpoint_reconcile_only")
            save(preparation_root / "started.json", {"contextId": context_id}, immutable=True)
            units = history.prepare_groups(payload["items"], payload["units"],
                                           args.root / "preparation-corpus" / context_id,
                                           RUN_ID, runtimes, actor=payload["actor"])
            print(json.dumps({"units": units}, sort_keys=True))
            return 0
        with (control / "controller.lock").open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused("controller_already_running") from None
            controller = Controller(args)
            # A child retains the same flock until exit even if its parent dies
            # between spawn and queue persistence; a restart cannot overlap it.
            controller.owner_lock_fd = lock.fileno()
            signal.signal(signal.SIGTERM, controller.stop)
            signal.signal(signal.SIGINT, controller.stop)
            signal.signal(signal.SIGUSR1, controller.pause)
            if args.check:
                try:
                    result = controller.check()
                finally:
                    controller.stop_owned_graph()
            else:
                result = controller.run("canary" if args.canary else "run")
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] in {"completed", "check-ready-for-main"} else 2
    except Exception as exc:
        code = getattr(exc, "code", None) or (str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"[a-zA-Z0-9_:-]+", str(exc)) else "controller_internal_" + type(exc).__name__)
        failure = {"status": "refused", "error": {"code": code},
                   "unknown": bool(getattr(exc, "unknown", False) or getattr(exc, "uncertain", False))}
        if RUN_CONFIG and args.root is not None and args.root.resolve() == ROOT and not args.root.is_symlink() and (ROOT / "control").is_dir():
            try:
                save(ROOT / "control/failures" / (uuid.uuid4().hex + ".json"), {**failure, "observedAt": now()}, immutable=True)
            except OSError:
                pass
        print(json.dumps(failure))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
