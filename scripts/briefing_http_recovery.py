"""Offline inspection for one explicitly authorized transient HTTP recovery.

This module never sends a request, sleeps, or alters paid-call evidence. A caller
must reserve its paid-call budget and preserve the returned lineage before send.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

POLICY = "explicit-inspected-transient-recovery-v1"
TRANSIENT_STATUSES = frozenset({500, 502, 503, 504})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class RecoveryError(ValueError):
    """Content-free, fail-closed inspection error."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RecoveryError("recovery_regular_evidence_file_required")
    try:
        return path.read_bytes()
    except OSError as error:
        raise RecoveryError("recovery_evidence_unreadable") from error


def _json(raw: bytes, *, raw_response: bool = False):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RecoveryError("recovery_duplicate_json_key")
            result[key] = value
        return result

    def constant(_):
        raise RecoveryError("recovery_non_finite_json_number")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, UnicodeError) as error:
        # Gateways may return HTML/plain text. Its exact bytes are still hashed.
        if raw_response:
            return {}
        raise RecoveryError("recovery_invalid_evidence_json") from error
    if type(value) is not dict:
        raise RecoveryError("recovery_evidence_object_required")
    return value


def _inbox_ref(value):
    if type(value) is not str or not value or "\\" in value:
        raise RecoveryError("recovery_operator_inbox_required")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) < 2 or path.parts[0] != "inbox" \
            or ".." in path.parts or path.suffix != ".md":
        raise RecoveryError("recovery_operator_inbox_required")


def _descriptor(value):
    if not isinstance(value, Mapping):
        raise RecoveryError("recovery_descriptor_required")
    for field in ("originalRequestDigest", "originalRequestSha256", "originalResponseSha256", "originalReceiptSha256"):
        if type(value.get(field)) is not str or not _SHA256.fullmatch(value[field]):
            raise RecoveryError("recovery_descriptor_digest_invalid")
    if value["originalRequestDigest"] != value["originalRequestSha256"]:
        raise RecoveryError("recovery_descriptor_request_digest_mismatch")
    if value.get("policy") != POLICY or type(value.get("attempt")) is not int or value["attempt"] != 1:
        raise RecoveryError("recovery_exactly_one_attempt_required")
    if type(value.get("originalHttpStatus")) is not int or value["originalHttpStatus"] not in TRANSIENT_STATUSES:
        raise RecoveryError("recovery_transient_http_status_required")
    if type(value.get("originalUsageKnown")) is not bool:
        raise RecoveryError("recovery_usage_identity_invalid")
    _inbox_ref(value.get("operatorInboxRef"))


def inspect_transient_failure(calls_path: Path, request_digest: str, operator_inbox_ref: str) -> dict:
    """Validate the immutable failed request and return a one-attempt descriptor.

    A pending reservation alone (including transport timeout) is unresolved and
    cannot qualify. Usage remains unknown unless BOTH recorded provider counts
    are valid integers matching the receipt; unknown is never converted to zero.
    """
    if type(request_digest) is not str or not _SHA256.fullmatch(request_digest):
        raise RecoveryError("recovery_request_digest_invalid")
    _inbox_ref(operator_inbox_ref)
    calls_path = Path(calls_path)
    if calls_path.is_symlink() or not calls_path.is_dir():
        raise RecoveryError("recovery_calls_directory_required")
    files = {kind: _read(calls_path / (request_digest + "." + kind + ".json"))
             for kind in ("request", "response", "complete", "pending")}
    if _sha(files["request"]) != request_digest:
        raise RecoveryError("recovery_request_digest_mismatch")
    request = _json(files["request"])
    receipt = _json(files["complete"])
    pending = _json(files["pending"])
    if receipt.get("responseSha256") != _sha(files["response"]):
        raise RecoveryError("recovery_response_digest_mismatch")
    if type(receipt.get("stage")) is not str or not receipt["stage"] \
            or type(receipt.get("model")) is not str or not receipt["model"]:
        raise RecoveryError("recovery_receipt_identity_invalid")
    for field in ("stage", "model", "requestDigest"):
        if pending.get(field) != receipt.get(field):
            raise RecoveryError("recovery_reservation_receipt_identity_mismatch")
    try:
        request_stage = request["text"]["format"]["name"]
    except (KeyError, TypeError) as error:
        raise RecoveryError("recovery_request_stage_required") from error
    if receipt.get("requestDigest") != request_digest or request.get("model") != receipt["model"] \
            or request_stage != receipt["stage"]:
        raise RecoveryError("recovery_request_receipt_identity_mismatch")
    if type(request.get("input")) is not str:
        raise RecoveryError("recovery_request_input_required")
    prior_data = _json(request["input"].encode("utf-8"))
    if "recoveryAttempt" in prior_data:
        raise RecoveryError("recovery_chain_forbidden")
    status = receipt.get("httpStatus")
    if type(status) is not int or status not in TRANSIENT_STATUSES:
        raise RecoveryError("recovery_transient_http_status_required")
    response = _json(files["response"], raw_response=True)
    if receipt.get("status") != response.get("status", "unknown"):
        raise RecoveryError("recovery_response_status_mismatch")
    usage = response.get("usage")
    if usage is None:
        usage = {}
    if type(usage) is not dict:
        raise RecoveryError("recovery_provider_usage_invalid")
    fields = (("inputTokens", "input_tokens"), ("outputTokens", "output_tokens"))
    known = all(type(usage.get(provider)) is int and usage[provider] >= 0 for _, provider in fields)
    if type(receipt.get("usageKnown")) is not bool or receipt["usageKnown"] is not known:
        raise RecoveryError("recovery_usage_known_mismatch")
    if known:
        if any(type(receipt.get(field)) is not int or receipt[field] != usage[provider] for field, provider in fields):
            raise RecoveryError("recovery_usage_counts_mismatch")
    elif any(receipt.get(field) is not None or field not in receipt for field, _ in fields):
        raise RecoveryError("recovery_unknown_usage_must_remain_null")
    return {"originalRequestDigest": request_digest, "originalRequestSha256": _sha(files["request"]),
            "originalResponseSha256": _sha(files["response"]), "originalReceiptSha256": _sha(files["complete"]),
            "originalHttpStatus": status, "originalUsageKnown": known,
            "operatorInboxRef": operator_inbox_ref, "attempt": 1, "policy": POLICY}


def recovery_data(data: dict, descriptor: Mapping) -> dict:
    """Return copied input with lineage, changing its canonical request identity."""
    _descriptor(descriptor)
    if type(data) is not dict or "recoveryAttempt" in data:
        raise RecoveryError("recovery_fresh_object_input_required")
    result = deepcopy(data)
    result["recoveryAttempt"] = deepcopy(dict(descriptor))
    return result


def validate_recovery_budget(descriptor: Mapping, previously_attempted: Iterable) -> None:
    """Reject another paid recovery of an original digest, including new prompts.

    History may contain original digest strings or recovery descriptors. Reusing
    an immutable completed replacement is the caller's responsibility and is
    not another paid attempt. The caller must reserve atomically before sending.
    """
    _descriptor(descriptor)
    if isinstance(previously_attempted, (str, bytes)) or not isinstance(previously_attempted, Iterable):
        raise RecoveryError("recovery_attempt_history_required")
    for previous in previously_attempted:
        if isinstance(previous, Mapping):
            _descriptor(previous)
            original = previous["originalRequestDigest"]
        elif type(previous) is str and _SHA256.fullmatch(previous):
            original = previous
        else:
            raise RecoveryError("recovery_attempt_history_invalid")
        if original == descriptor["originalRequestDigest"]:
            raise RecoveryError("recovery_original_already_attempted")
