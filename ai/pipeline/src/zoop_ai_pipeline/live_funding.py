"""Closed metered-operation authority, separate from the historical capped runtime."""
from __future__ import annotations

import json
from datetime import datetime, timezone

MODE = "operating-metered-v1"
SCHEMA = "zoop-operating-funding-1"
STAGES = ("extract", "compare", "topic", "relation", "impact", "verify-relation", "verify-impact")


def timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("operating_datetime_invalid")
    return parsed.astimezone(timezone.utc).timestamp()


def operating_policy(value: dict) -> dict:
    """Validate actual lifecycle, account references and finite per-request limits; contains no secrets."""
    keys = {"schemaVersion", "mode", "operationId", "accounts", "lifecycle", "requestTimeoutSeconds", "drainSeconds",
            "cleanupSeconds", "minIntervalMilliseconds"}
    if not isinstance(value, dict) or set(value) != keys or value["schemaVersion"] != SCHEMA or value["mode"] != MODE:
        raise ValueError("operating_policy_invalid")
    if not isinstance(value["operationId"], str) or not 1 <= len(value["operationId"]) <= 120:
        raise ValueError("operating_policy_invalid")
    accounts = value["accounts"]
    if not isinstance(accounts, dict) or set(accounts) != {"openai-compatible", "typesafe-native"}:
        raise ValueError("operating_accounts_invalid")
    if any(not isinstance(v, str) or not 1 <= len(v) <= 200 for v in accounts.values()):
        raise ValueError("operating_accounts_invalid")
    for key, low, high in (("requestTimeoutSeconds", 10, 300), ("drainSeconds", 1, 604800),
                           ("cleanupSeconds", 1, 60), ("minIntervalMilliseconds", 1, 86400000)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("operating_limit_invalid")
    lifecycle = value["lifecycle"]
    if not isinstance(lifecycle, dict):
        raise ValueError("operating_lifecycle_invalid")
    kind = lifecycle.get("kind")
    if kind == "explicit-stop" and set(lifecycle) == {"kind"}:
        pass
    elif kind == "deadline" and set(lifecycle) == {"kind", "until"}:
        timestamp(lifecycle["until"])
    elif kind == "frontier" and set(lifecycle) == {"kind", "setIds"}:
        ids = lifecycle["setIds"]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 100000
                or any(not isinstance(v, str) or not 1 <= len(v) <= 200 for v in ids) or len(set(ids)) != len(ids)):
            raise ValueError("operating_frontier_invalid")
    else:
        raise ValueError("operating_lifecycle_invalid")
    return json.loads(json.dumps(value))


def stage_allowances(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != set(STAGES)
            or any(type(n) is not int or not 0 <= n <= 100000 for n in value.values()) or not sum(value.values())):
        raise ValueError("operating_stage_allowance_invalid")
    return dict(value)
