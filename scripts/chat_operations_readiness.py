#!/usr/bin/env python3
"""Fail closed until chatbot network, grant, retention and rollback decisions exist.

This checker consumes references and role names, never endpoint URLs, credentials,
grant bodies, questions or answers. It also re-validates the raw live-spike evidence so
the operational approvals and latency evidence are bound to the same candidate commit.
Passing this gate does not enable either chatbot feature flag.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import chat_live_spike_report as spike


SCHEMA = "zoop-chat-operations-readiness-1"
COMMIT = re.compile(r"[0-9a-f]{40}")
SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")
REFERENCE = re.compile(r"[A-Z][A-Z0-9_-]{1,63}(?:#[A-Za-z0-9._-]{1,64})?")

ROOT_KEYS = {
    "schemaVersion", "candidateCommit", "environment", "recordedAt", "decisions",
    "preflight", "rollout",
}
DECISION_KEYS = {"status", "selection", "decisionRef", "ownerRole", "approvedAt"}
PREFLIGHT_KEYS = {
    "status", "observedAt", "endpointRevision", "evidenceRef",
    "bearerChallengeObserved", "redirectFollowed",
}
ROLLOUT_KEYS = {
    "mcpEnabled", "agentEnabled", "enableChangeRef", "rollbackOwnerRole",
}

# The exact selections make a generic "approved" checkbox insufficient. Changes to
# these choices are policy changes and require a reviewed code revision of this gate.
DECISIONS: dict[str, set[str]] = {
    "httpsIngress": {"https-default-port-no-redirect"},
    "sourceRestriction": {
        "private-connectivity",
        "provider-ip-defense-in-depth",
        "no-ip-restriction",
    },
    "modelSendGrants": {"chat-agent-recipient-source-grants-approved"},
    "openaiRetention": {"responses-store-true-approved"},
    "privacyDisclosure": {"external-model-processing-approved"},
    "keyRotation": {"dual-key-rollover-approved"},
    "incidentResponse": {"disable-rollback-owners-assigned"},
    "evidenceRetention": {"raw-live-evidence-retention-approved"},
}


class ReadinessError(ValueError):
    pass


def _exact_keys(value: dict[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ReadinessError(f"{where} keys differ: missing={missing}, extra={extra}")


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReadinessError(f"{where} must be an object")
    return value


def _slug(value: Any, where: str) -> str:
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ReadinessError(f"{where} must be a lowercase operational slug")
    return value


def _reference(value: Any, where: str) -> str:
    if not isinstance(value, str) or not REFERENCE.fullmatch(value):
        raise ReadinessError(f"{where} must be a ticket or decision reference, not a URL or secret")
    return value


def _time(value: Any, where: str) -> datetime:
    if not isinstance(value, str):
        raise ReadinessError(f"{where} must be an ISO-8601 timestamp with an offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ReadinessError(f"{where} must be an ISO-8601 timestamp with an offset") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReadinessError(f"{where} must include an offset")
    return parsed


def load(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReadinessError(f"cannot read readiness manifest: {error}") from None
    root = _object(raw, "root")
    _exact_keys(root, ROOT_KEYS, "root")
    if root["schemaVersion"] != SCHEMA:
        raise ReadinessError(f"schemaVersion must be {SCHEMA}")
    candidate = root["candidateCommit"]
    if not isinstance(candidate, str) or not COMMIT.fullmatch(candidate):
        raise ReadinessError("candidateCommit must be a lowercase 40-character Git commit")
    environment = _slug(root["environment"], "environment")
    recorded_at = _time(root["recordedAt"], "recordedAt")

    raw_decisions = _object(root["decisions"], "decisions")
    _exact_keys(raw_decisions, set(DECISIONS), "decisions")
    decisions: dict[str, dict[str, str]] = {}
    for name, allowed in DECISIONS.items():
        value = _object(raw_decisions[name], f"decisions.{name}")
        _exact_keys(value, DECISION_KEYS, f"decisions.{name}")
        if value["status"] != "approved":
            raise ReadinessError(f"decisions.{name}.status must be approved")
        if not isinstance(value["selection"], str) or value["selection"] not in allowed:
            raise ReadinessError(f"decisions.{name}.selection must be one of {sorted(allowed)}")
        approved_at = _time(value["approvedAt"], f"decisions.{name}.approvedAt")
        if approved_at > recorded_at:
            raise ReadinessError(f"decisions.{name}.approvedAt is after recordedAt")
        decisions[name] = {
            "selection": value["selection"],
            "decisionRef": _reference(value["decisionRef"], f"decisions.{name}.decisionRef"),
            "ownerRole": _slug(value["ownerRole"], f"decisions.{name}.ownerRole"),
            "approvedAt": value["approvedAt"],
        }

    raw_preflight = _object(root["preflight"], "preflight")
    _exact_keys(raw_preflight, PREFLIGHT_KEYS, "preflight")
    if raw_preflight["status"] != "passed":
        raise ReadinessError("preflight.status must be passed")
    observed_at = _time(raw_preflight["observedAt"], "preflight.observedAt")
    if observed_at > recorded_at:
        raise ReadinessError("preflight.observedAt is after recordedAt")
    if raw_preflight["bearerChallengeObserved"] is not True:
        raise ReadinessError("preflight must observe the endpoint's 401 Bearer challenge")
    if raw_preflight["redirectFollowed"] is not False:
        raise ReadinessError("preflight must not follow a redirect")
    preflight = {
        "observedAt": raw_preflight["observedAt"],
        "endpointRevision": _slug(raw_preflight["endpointRevision"], "preflight.endpointRevision"),
        "evidenceRef": _reference(raw_preflight["evidenceRef"], "preflight.evidenceRef"),
    }

    raw_rollout = _object(root["rollout"], "rollout")
    _exact_keys(raw_rollout, ROLLOUT_KEYS, "rollout")
    if raw_rollout["mcpEnabled"] is not False or raw_rollout["agentEnabled"] is not False:
        raise ReadinessError("both feature flags must remain false while readiness is assessed")
    rollout = {
        "enableChangeRef": _reference(raw_rollout["enableChangeRef"], "rollout.enableChangeRef"),
        "rollbackOwnerRole": _slug(raw_rollout["rollbackOwnerRole"], "rollout.rollbackOwnerRole"),
    }
    return {
        "candidateCommit": candidate,
        "environment": environment,
        "recordedAt": root["recordedAt"],
        "decisions": decisions,
        "preflight": preflight,
        "rollout": rollout,
    }


def evaluate(manifest: dict[str, Any], live_evidence: Path) -> dict[str, Any]:
    try:
        spike_metadata, runs = spike.load(live_evidence)
        spike_report = spike.report(spike_metadata, runs, spike.DEFAULT_MIN_SAMPLES)
    except spike.EvidenceError as error:
        raise ReadinessError(f"live spike evidence is invalid: {error}") from None
    failures = list(spike_report["failures"])
    if spike_metadata["candidateCommit"] != manifest["candidateCommit"]:
        failures.append("live spike candidateCommit differs from readiness candidateCommit")
    return {
        "schemaVersion": SCHEMA,
        "candidateCommit": manifest["candidateCommit"],
        "environment": manifest["environment"],
        "recordedAt": manifest["recordedAt"],
        "gate": "passed" if not failures else "failed",
        "decisionRefs": {
            name: value["decisionRef"] for name, value in manifest["decisions"].items()
        },
        "preflightEvidenceRef": manifest["preflight"]["evidenceRef"],
        "enableChangeRef": manifest["rollout"]["enableChangeRef"],
        "liveSpike": {
            "gate": spike_report["gate"],
            "runs": spike_report["totals"]["runs"],
            "costUsd": spike_report["totals"]["costUsd"],
        },
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="content-free operations readiness manifest")
    parser.add_argument("live_evidence", type=Path, help="raw zoop-chat-live-spike-1 evidence")
    parser.add_argument("--output", type=Path, help="optional content-free JSON report path")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load(args.manifest), args.live_evidence)
    except ReadinessError as error:
        print(json.dumps({"schemaVersion": SCHEMA, "gate": "invalid", "error": str(error)}, ensure_ascii=False))
        return 64
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if result["gate"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
