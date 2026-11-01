"""Versioned metered and capped funding authorities with distinct lifecycle contracts."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .relation_contracts import digest
from . import direct_deepseek

MODE = "operating-metered-v1"
SCHEMA = "zoop-operating-funding-1"
STAGES = ("extract", "compare", "topic", "relation", "impact", "verify-relation", "verify-impact")


def operating_timestamp(value: str) -> float:
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
        operating_timestamp(lifecycle["until"])
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


PROFILE = "overnight-funded-v1"
POLICY_VERSION = "zoop-overnight-funding-1"
NOT_AFTER = "2026-10-27T21:00:00Z"
SET_PROFILE = "admitted-set-funded-v2"
SET_POLICY_VERSION = "zoop-set-funding-2"
FINISH_PROFILE = "admitted-set-funded-v3"
CAPPED_PROFILE = "admitted-set-capped-v4"
CAPPED_POLICY_VERSION = "zoop-set-funding-3"
RUN_CONFIG_SCHEMA = "zoop-private-run-4"
RUN_CONFIG_KEYS = {"schemaVersion", "runId", "root", "admitFrom", "admitUntil", "finishBy",
                   "graphPort", "maxCalls", "processingActor", "funding"}
FINISH_BY_ENV = "ZOOP_AI_PIPELINE_LIVE_FINISH_BY"
OPENAI_URL = "https://api.openai.com/v1"
GO_URL = "https://opencode.ai/zen/go/v1"
JEV_URL = "https://api.typesafe.ai/v1"
GO_MODEL = "deepseek-v4.1-flash"
USER_AGENT = "zoop-data-pipeline/1.0"
GENERATION_STAGES = ("extract", "compare", "topic", "relation", "impact", "issue-summary")
VERIFY_STAGES = ("verify-relation", "verify-impact", "verify-issue-summary")
ACQUISITION_STAGES = ("fetch", "search")
BUCKET_MAX_NANO = 10_000_000_000
SEND_BEFORE_ENV = "ZOOP_AI_PIPELINE_LIVE_SEND_BEFORE"
FINISH_RESERVE_SECONDS = 180
TERMINATION_GRACE_SECONDS = 5


def require_send_window(timeout: float, send_before: str | None) -> None:
    """Refuse a new request unless its full transport allowance fits before cleanup."""
    if send_before is not None and (timestamp(send_before) - datetime.now(timezone.utc)).total_seconds() <= timeout:
        raise ValueError("live_finish_deadline")


def timestamp(text: str) -> datetime:
    if not isinstance(text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", text):
        raise ValueError("live_funding_config_invalid")
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def finish_policy(finish_by: str) -> dict:
    finish = timestamp(finish_by)
    return {"version": "zoop-finish-authority-1", "finishBy": finish_by,
            "sendBefore": (finish - timedelta(seconds=FINISH_RESERVE_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "maxHttpTimeoutSeconds": 300, "cleanupReserveSeconds": FINISH_RESERVE_SECONDS}


def deadline(text: str) -> datetime:
    value = timestamp(text)
    if value > datetime(2026, 10, 27, 21, tzinfo=timezone.utc):
        raise ValueError("live_funding_config_invalid")
    return value


def funding_policy(run_id: str, not_after: str = NOT_AFTER) -> dict:
    """Pure canonical policy, common to both generation cohorts and all live families."""
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", run_id):
        raise ValueError("live_funding_config_invalid")
    deadline(not_after)
    roles = {}
    for role, bucket, endpoint, model, stages in (
        ("shared-openai", "shared", OPENAI_URL, "gpt-6-luna", GENERATION_STAGES),
        ("personal-opencode", "personal", GO_URL, GO_MODEL, GENERATION_STAGES),
        ("personal-typesafe", "personal", JEV_URL, "jev-1.14.0", VERIFY_STAGES),
    ):
        verifier = role == "personal-typesafe"
        recipient = ("typesafe-native:" + digest({"api": "systemone", "endpoint": endpoint}) if verifier
                     else "openai-compatible:" + digest({"endpoint": endpoint}))
        roles[role] = {"bucket": bucket, "endpoint": endpoint, "model": model, "recipient": recipient, "stages": list(stages)}
    return {"version": POLICY_VERSION, "runId": run_id, "notAfter": not_after, "minimumVerifierReserveNanoUsd": 1_000_000,
            "bucketMaxNanoUsd": {"shared": BUCKET_MAX_NANO, "personal": BUCKET_MAX_NANO}, "roles": roles}


def set_funding_policy(run_id: str, admit_from: str, admit_until: str) -> dict:
    """A new ledger admits finite sets in [start,end); only those sets may drain after end."""
    start, end = timestamp(admit_from), timestamp(admit_until)
    if not 0 < (end - start).total_seconds() <= 86400:
        raise ValueError("live_funding_config_invalid")
    historical = funding_policy(run_id)
    roles = {key: value for key, value in historical["roles"].items() if key != "personal-opencode"}
    roles["personal-deepseek"] = {
        "bucket": "personal", "endpoint": direct_deepseek.BASE_URL, "model": direct_deepseek.MODEL,
        "recipient": "openai-compatible:" + digest({"endpoint": direct_deepseek.BASE_URL}),
        "stages": list(GENERATION_STAGES + ACQUISITION_STAGES),
        "stageRecipients": {"fetch": "deepseek-fetch", "search": "deepseek-search"}}
    return {**{key: value for key, value in historical.items() if key not in {"version", "notAfter"}},
            "version": SET_POLICY_VERSION, "admitFrom": admit_from, "admitUntil": admit_until,
            "drain": "admitted-finite-sets", "roles": roles}


def capped_set_funding_policy(run_id: str, admit_from: str, admit_until: str,
                              total_nano: int, shared_nano: int, personal_nano: int) -> dict:
    """Pin an exact partition of the run ceiling without changing historical policy bytes."""
    policy = set_funding_policy(run_id, admit_from, admit_until)
    if (any(type(value) is not int for value in (total_nano, shared_nano, personal_nano))
            or shared_nano + personal_nano != total_nano or not 0 < total_nano <= 2 * BUCKET_MAX_NANO
            or not 0 <= shared_nano <= BUCKET_MAX_NANO
            or not policy["minimumVerifierReserveNanoUsd"] < personal_nano <= BUCKET_MAX_NANO):
        raise ValueError("live_funding_config_invalid")
    return {**policy, "version": CAPPED_POLICY_VERSION, "totalMaxNanoUsd": total_nano,
            "bucketMaxNanoUsd": {"shared": shared_nano, "personal": personal_nano}}


def funding_amounts(value: Any) -> tuple[int, int, int]:
    """Parse the three explicit decimal amounts once for run files and environment bindings."""
    from .live_budget import nano_from_usd
    keys = ("totalMaxUsd", "sharedMaxUsd", "personalMaxUsd")
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("live_funding_config_invalid")
    amounts = []
    for key in keys:
        text = value[key]
        if not isinstance(text, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,9})?", text):
            raise ValueError("live_funding_config_invalid")
        amounts.append(0 if key == "sharedMaxUsd" and Decimal(text) == 0 else nano_from_usd(text))
    return tuple(amounts)


def run_policy(config: Any) -> dict:
    """Decode only the closed current run contract; historical configs are not executable."""
    try:
        if not isinstance(config, dict) or set(config) != RUN_CONFIG_KEYS or config["schemaVersion"] != RUN_CONFIG_SCHEMA:
            raise ValueError
        return capped_set_funding_policy(config["runId"], config["admitFrom"], config["admitUntil"],
                                         *funding_amounts(config["funding"]))
    except (KeyError, TypeError, ValueError):
        raise ValueError("live_funding_config_invalid") from None


def is_set_policy(policy: dict | None) -> bool:
    return bool(policy and policy.get("version") in (SET_POLICY_VERSION, CAPPED_POLICY_VERSION))


def validate_policy(value: Any) -> dict:
    try:
        if value["version"] == CAPPED_POLICY_VERSION:
            expected = capped_set_funding_policy(value["runId"], value["admitFrom"], value["admitUntil"],
                                                 value["totalMaxNanoUsd"], value["bucketMaxNanoUsd"]["shared"],
                                                 value["bucketMaxNanoUsd"]["personal"])
        elif value["version"] == SET_POLICY_VERSION:
            expected = set_funding_policy(value["runId"], value["admitFrom"], value["admitUntil"])
        else:
            expected = funding_policy(value["runId"], value["notAfter"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("live_funding_config_invalid") from None
    if value != expected:
        raise ValueError("live_funding_config_invalid")
    return expected


def schema_matches(value: Any, schema: dict, root: dict | None = None) -> bool:
    """Validate exactly the structural subset emitted by live_prompts.strict_schema, without coercion.

    Native owners still resolve null quote offsets and enforce their richer Pydantic/domain contracts afterwards.
    Unknown schema keywords fail closed instead of quietly weakening a future schema.
    """
    root = schema if root is None else root
    supported = {"$ref", "$defs", "type", "properties", "required", "additionalProperties", "items", "enum",
                 "anyOf", "allOf", "oneOf", "description", "minItems", "maxItems", "minLength", "maxLength"}
    if set(schema) - supported:
        return False
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/") or not schema_matches(value, root["$defs"][ref[8:]], root):
            return False
    for key in ("anyOf", "allOf", "oneOf"):
        if key in schema:
            matches = sum(schema_matches(value, option, root) for option in schema[key])
            if (key == "anyOf" and not matches) or (key == "allOf" and matches != len(schema[key])) or (key == "oneOf" and matches != 1):
                return False
    if "enum" in schema and not any(type(value) is type(item) and value == item for item in schema["enum"]):
        return False
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
    kind = schema.get("type")
    if kind == "number":
        if type(value) not in (int, float) or not math.isfinite(value):
            return False
    elif kind is not None and (kind not in types or type(value) is not types[kind]):
        return False
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if not set(schema.get("required", [])) <= value.keys():
            return False
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            return False
        if any(not schema_matches(item, props[key], root) for key, item in value.items() if key in props):
            return False
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", len(value)):
            return False
        if "items" in schema and any(not schema_matches(item, schema["items"], root) for item in value):
            return False
    if isinstance(value, str) and not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value)):
        return False
    return True


def provider_cost(raw: Any) -> dict:
    """Allowlisted provider observations, never an invoice or an input to the conservative budget."""
    usage = raw.get("usage") if isinstance(raw, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    block = usage.get("opencode")
    block = block if isinstance(block, dict) else {}

    def amount(value: Any) -> str | None:
        if type(value) not in (int, float, str) or len(str(value)) > 80:
            return None
        try:
            number = Decimal(str(value))
            return (format(number, "f") if number.is_finite() and 0 <= number <= 1_000_000
                    and number.as_tuple().exponent >= -12 else None)
        except InvalidOperation:
            return None

    source = block.get("billing_source")
    return {"billingSource": source if source in ("free", "balance", "go", "go-plus", "byok") else None,
            "billableUsd": amount(usage.get("cost")), "allowanceUsd": amount(block.get("allowance")),
            "listUsd": amount(block.get("list_cost"))}
