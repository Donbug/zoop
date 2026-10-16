#!/usr/bin/env python3
"""Explicit operator-only historical replay. Default is an offline population audit; never a web/cron entry point."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import urllib.error
import urllib.request

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/responses"
PROMPTS = Path(__file__).resolve().parents[1] / "api/src/main/resources/briefing/prompts/replay"
MAX_DOCUMENTS = 1000
MAX_CALLS = 64
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
ROUND_DATE = "2026-10-09"


class ReplayError(Exception):
    """Only content-free error codes may escape to the operator console."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def strict_load(value):
    def pairs(items):
        out = {}
        for key, item in items:
            if key in out:
                raise ReplayError("duplicate_json_key")
            out[key] = item
        return out

    def constant(_):
        raise ReplayError("non_finite_json_number")

    try:
        return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError) as error:
        raise ReplayError("invalid_json") from error


def private_dir(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise ReplayError("private_0700_output_required")


def regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ReplayError("regular_file_required")
    return path.read_bytes()


def write_once(path: Path, value: bytes):
    if path.exists():
        if regular(path) != value or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise ReplayError("immutable_private_file_conflict")
        return
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def save_json(path: Path, value):
    write_once(path, canonical(value))


def read_key(path: Path) -> str:
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ReplayError("private_0600_key_file_required")
    assignments = []
    for raw in regular(path).decode("utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if line.startswith("OPENAI_API_KEY="):
            value = line.split("=", 1)[1].strip()
            if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            assignments.append(value)
    if len(assignments) != 1 or not assignments[0] or re.search(r"\s", assignments[0]):
        raise ReplayError("one_valid_openai_key_assignment_required")
    return assignments[0]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def authenticated_transport(key_file: Path):
    key = read_key(key_file)
    opener = urllib.request.build_opener(NoRedirect())

    def send(body: bytes):
        request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=180) as reply:
                value = reply.read(MAX_RESPONSE_BYTES + 1)
                if len(value) > MAX_RESPONSE_BYTES:
                    raise ReplayError("provider_response_too_large_unknown_usage")
                return reply.status, value
        except urllib.error.HTTPError as error:
            return error.code, error.read(MAX_RESPONSE_BYTES + 1)

    return send


def output_of(response):
    if response.get("status") != "completed":
        raise ReplayError("incomplete_provider_result_no_automatic_retry")
    pieces = []
    for message in response.get("output", []):
        if message.get("type") != "message":
            continue
        for part in message.get("content", []):
            if part.get("type") == "refusal":
                raise ReplayError("provider_refusal_no_automatic_retry")
            if part.get("type") == "output_text":
                pieces.append(part.get("text", ""))
    if len(pieces) != 1:
        raise ReplayError("exactly_one_structured_output_required")
    return strict_load(pieces[0])


class ResponsesClient:
    """Write-ahead immutable receipts: completed responses reuse; pending/failed calls never blindly retry."""

    def __init__(self, output: Path, transport, max_calls=MAX_CALLS, authorized_truncations=()):
        self.calls = output / "calls"
        private_dir(self.calls)
        self.transport = transport
        self.max_calls = max_calls
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.new_calls = set()
        self.reused_calls = set()
        self.authorized_truncations = set(authorized_truncations)

    def call(self, stage, data, prompt_name, schema_name, max_output=8000, schema_override=None):
        try:
            return self._call(stage, data, prompt_name, schema_name, max_output, schema_override)
        except Exception:
            # Already in-flight siblings may finish and must retain their receipts; queued work cannot spend more.
            self.stopped.set()
            raise

    def request(self, stage, data, prompt_name, schema_name, max_output=8000, schema_override=None):
        instructions = regular(PROMPTS / prompt_name).decode("utf-8")
        schema = strict_load(canonical(schema_override)) if schema_override is not None else strict_load(regular(PROMPTS / schema_name))
        request = {"model": MODEL, "store": False, "max_output_tokens": max_output,
                   "instructions": instructions, "input": canonical(data).decode("utf-8"),
                   "reasoning": {"effort": "low"},
                   "text": {"format": {"type": "json_schema", "name": stage, "strict": True, "schema": schema}}}
        encoded = canonical(request)
        if len(encoded) > 2 * 1024 * 1024:
            raise ReplayError("bounded_request_size_exceeded")
        return encoded, schema, digest(instructions.encode())

    def request_digest(self, stage, data, prompt_name, schema_name, max_output=8000, schema_override=None):
        return digest(self.request(stage, data, prompt_name, schema_name, max_output, schema_override)[0])

    def has_recorded(self, request_digest):
        return any((self.calls / (request_digest + suffix)).exists() for suffix in (".pending.json", ".complete.json"))

    def inspect_recorded(self, key):
        """Inspect immutable paid evidence without parsing a truncated output or creating another reservation."""
        try:
            return self._inspect_recorded(key)
        except Exception:
            self.stopped.set()
            raise

    def _inspect_recorded(self, key):
        complete = self.calls / (key + ".complete.json")
        if not complete.exists():
            raise ReplayError("unresolved_paid_reservation_no_automatic_retry")
        receipt = strict_load(regular(complete))
        raw = regular(self.calls / (key + ".response.json"))
        if receipt.get("requestDigest") != key or digest(regular(self.calls / (key + ".request.json"))) != key \
                or digest(raw) != receipt.get("responseSha256") or receipt.get("model") != MODEL:
            raise ReplayError("cached_paid_evidence_digest_mismatch")
        response = strict_load(raw)
        if receipt.get("httpStatus") != 200 or receipt.get("usageKnown") is not True \
                or response.get("status") != receipt.get("status"):
            raise ReplayError("cached_failed_or_unknown_call_requires_inspection")
        usage = response.get("usage") or {}
        if any(type(receipt.get(field)) is not int or receipt[field] < 0 or receipt[field] != usage.get(provider)
               for field, provider in (("inputTokens", "input_tokens"), ("outputTokens", "output_tokens"))):
            raise ReplayError("cached_paid_usage_mismatch")
        return receipt, response

    def _call(self, stage, data, prompt_name, schema_name, max_output, schema_override):
        encoded, schema, prompt_sha = self.request(stage, data, prompt_name, schema_name, max_output, schema_override)
        key = digest(encoded)
        pending = self.calls / (key + ".pending.json")
        complete = self.calls / (key + ".complete.json")
        body_path = self.calls / (key + ".response.json")
        with self.lock:
            if self.stopped.is_set():
                raise ReplayError("run_stopped_after_failed_or_unknown_call")
            if complete.exists():
                receipt = strict_load(regular(complete))
                if receipt.get("requestDigest") != key or receipt.get("httpStatus") != 200 or not receipt.get("usageKnown"):
                    raise ReplayError("cached_failed_or_unknown_call_requires_inspection")
                raw = regular(body_path)
                if digest(raw) != receipt.get("responseSha256"):
                    raise ReplayError("cached_response_digest_mismatch")
                self.reused_calls.add(key)
                result = output_of(strict_load(raw))
                validate_schema(result, schema)
                return result
            if pending.exists():
                raise ReplayError("unresolved_paid_reservation_no_automatic_retry")
            if len(list(self.calls.glob("*.pending.json"))) >= self.max_calls:
                raise ReplayError("paid_call_budget_exhausted")
            write_once(self.calls / (key + ".request.json"), encoded)
            save_json(pending, {"stage": stage, "requestDigest": key, "model": MODEL, "createdAt": now(),
                                "reservedInputTokenBound": 2 * len(encoded) + 4096, "maxOutputTokens": max_output,
                                "promptSha256": prompt_sha, "schemaSha256": digest(canonical(schema))})
            self.new_calls.add(key)
        # A transport exception intentionally leaves the reservation unresolved. Never automatically resend it.
        try:
            status, raw = self.transport(encoded)
        except Exception as error:
            raise ReplayError("transport_unknown_usage_no_automatic_retry") from error
        write_once(body_path, raw)
        try:
            response = strict_load(raw)
        except ReplayError:
            response = {}
        usage = response.get("usage") or {}
        known = all(type(usage.get(name)) is int and usage[name] >= 0 for name in ("input_tokens", "output_tokens"))
        receipt = {"stage": stage, "model": MODEL, "requestDigest": key, "responseSha256": digest(raw),
                   "responseId": response.get("id"), "status": response.get("status", "unknown"), "httpStatus": status,
                   "inputTokens": usage.get("input_tokens") if known else None,
                   "outputTokens": usage.get("output_tokens") if known else None,
                   "reasoningTokensSubset": (usage.get("output_tokens_details") or {}).get("reasoning_tokens") if known else None,
                   "usageKnown": known, "actualCostKnown": False, "actualCost": None, "finishedAt": now()}
        save_json(complete, receipt)
        if status != 200 or not known:
            raise ReplayError("provider_failed_or_usage_unknown_no_automatic_retry")
        result = output_of(response)
        validate_schema(result, schema)
        return result

    def receipts(self):
        out = []
        for pending in sorted(self.calls.glob("*.pending.json")):
            reservation = strict_load(regular(pending))
            key = reservation["requestDigest"]
            complete = self.calls / (key + ".complete.json")
            if complete.exists():
                value = strict_load(regular(complete))
            else:
                value = {"stage": reservation["stage"], "model": MODEL, "requestDigest": key,
                         "responseId": None, "status": "unknown", "usageKnown": False,
                         "inputTokens": None, "outputTokens": None, "actualCost": None, "actualCostKnown": False}
            # Persisted accounting must be independent of which process sent/reused a completed call.
            out.append(value)
        return out


def validate_schema(value, schema):
    expected = schema.get("type")
    allowed = expected if isinstance(expected, list) else [expected]
    types = {"object": lambda x: type(x) is dict, "array": lambda x: type(x) is list,
             "string": lambda x: type(x) is str, "integer": lambda x: type(x) is int,
             "boolean": lambda x: type(x) is bool, "null": lambda x: x is None}
    if expected and not any(types[k](value) for k in allowed):
        raise ReplayError("structured_output_type_mismatch")
    if "enum" in schema and value not in schema["enum"]:
        raise ReplayError("structured_output_enum_mismatch")
    if type(value) is dict:
        props = schema.get("properties", {})
        if not set(schema.get("required", [])).issubset(value) or (schema.get("additionalProperties") is False and set(value) - set(props)):
            raise ReplayError("structured_output_membership_mismatch")
        for key, item in value.items():
            if key in props:
                validate_schema(item, props[key])
    elif type(value) is list:
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 100000):
            raise ReplayError("structured_output_array_bounds")
        for item in value:
            validate_schema(item, schema.get("items", {}))
    elif type(value) is str:
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 1000000):
            raise ReplayError("structured_output_text_bounds")
    elif type(value) is int:
        if value < schema.get("minimum", -10**18) or value > schema.get("maximum", 10**18):
            raise ReplayError("structured_output_number_bounds")


def source_metadata(row):
    # Preserve the original permission/date/version/source observations, separately from development authorization.
    return {key: value for key, value in row.items() if key != "body"}


def company_names(row):
    names = [entry.get("companyName") for entry in row.get("companyAssociations", []) if type(entry) is dict]
    if row.get("companyName"):
        names.append(row["companyName"])
    return sorted({name for name in names if type(name) is str and name.strip()})


def date_context(row):
    if row.get("sourceKind") == "disclosure" and re.fullmatch(r"\d{8}", str(row.get("receptionDate", ""))):
        raw = row["receptionDate"]
        return {"date": f"{raw[:4]}-{raw[4:6]}-{raw[6:]}", "precision": "day", "meaning": row.get("dateMeaning"),
                "originalPublicationVerified": False, "reason": "DART reception date, not an exact original publication time"}
    estimates = row.get("providerEstimatedCalendarDatesKST", [])
    return {"date": estimates[0] if len(estimates) == 1 else None, "precision": "provider_estimated_date",
            "estimatedDatesKST": estimates, "originalPublicationVerified": row.get("originalPublicationVerified", False),
            "reason": "provider date estimate; cannot establish an exact historical publication cutoff"}


def population(path: Path, excerpt_chars=1400):
    raw = regular(path)
    rows = []
    seen = {}
    audit = []
    total = 0
    for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        total += 1
        if total > MAX_DOCUMENTS:
            raise ReplayError("population_exceeds_1000_document_bound")
        row = strict_load(line)
        if type(row) is not dict:
            raise ReplayError("source_record_must_be_object")
        body = row.get("body")
        actual = digest(body.encode("utf-8")) if type(body) is str else None
        reason = None
        if not row.get("documentId") or not re.match(r"^https?://", str(row.get("url", ""))):
            reason = "missing_document_identity_or_source_url"
        elif not body or len(body.strip()) < 80:
            reason = "body_not_acquired_or_insufficient"
        elif row.get("bodySha256") != actual:
            reason = "body_hash_mismatch"
        elif actual in seen:
            reason = "duplicate_exact_body"
        item = {"line": number, "documentId": row.get("documentId"), "sourceMetadata": source_metadata(row),
                "bodySha256Computed": actual, "eligible": reason is None, "exclusionReason": reason}
        if reason == "duplicate_exact_body":
            item["duplicateOf"] = seen[actual]
        audit.append(item)
        if reason:
            continue
        seen[actual] = row["documentId"]
        normalized = {**row, "documentVersion": "sha256-" + actual, "dateContext": date_context(row),
                      "companyNames": company_names(row)}
        if len(body) <= excerpt_chars:
            ranges = [[0, len(body)]]
        else:
            prefix = excerpt_chars * 3 // 4
            tail = excerpt_chars - prefix
            ranges = [[0, prefix], [len(body) - tail, len(body)]]
        normalized["assessmentExcerpts"] = [{"start": start, "end": end, "text": body[start:end]} for start, end in ranges]
        rows.append(normalized)
    return rows, {"schemaVersion": "zoop-briefing-population-audit-v1", "sourceFileSha256": digest(raw),
                  "totalRecords": total, "eligibleRecords": len(rows), "excludedRecords": total - len(rows),
                  "dateUncertaintyIsPreserved": True, "records": audit}


def assessment_input(rows, authorization):
    return {"scope": "development_replay", "authorization": authorization, "historicalReplay": True,
            "marketInputsAvailable": False, "previousOutlookAvailable": False,
            "documents": [{"documentId": row["documentId"], "title": row.get("title") or row.get("providerBodyTitle") or "",
                           "companyNames": row["companyNames"], "sourceKind": row.get("sourceKind"),
                           "dateContext": row["dateContext"], "bodyScope": row.get("bodyScope"),
                           "bodySha256": row["bodySha256"], "bodyCharacters": len(row["body"]),
                           "excerpts": row["assessmentExcerpts"], "originalRights": {
                               "allowModelSend": row.get("allowModelSend"), "rightsStatus": row.get("rightsStatus")}}
                          for row in rows]}


def assess_all(client, rows, authorization, batch_size=30, workers=3):
    batches = [rows[index:index + batch_size] for index in range(0, len(rows), batch_size)]

    def assess(batch):
        data = assessment_input(batch, authorization)
        expected = {row["documentId"] for row in batch}
        array_schema, object_schema = importance_batch_schemas(expected)
        variants = [(None, 8000), (array_schema, 8000), (object_schema, 12000)]
        recorded = []
        for schema, max_output in variants:
            key = client.request_digest("briefing_population_importance", data, "importance.md", "importance.schema.json",
                                        max_output=max_output, schema_override=schema)
            if not client.has_recorded(key):
                continue
            receipt, response = client.inspect_recorded(key)
            if receipt["status"] == "incomplete":
                if key not in client.authorized_truncations or (response.get("incomplete_details") or {}).get("reason") != "max_output_tokens":
                    client.stopped.set()
                    raise ReplayError("known_truncation_requires_digest_specific_operator_authorization")
                problem = {"missingDocumentIds": None, "inventedDocumentIds": None, "duplicateDocumentIds": None,
                           "expectedCount": len(expected), "actualCount": None}
                recorded.append((key, receipt, response, None, problem))
            elif receipt["status"] == "completed":
                prior = client.call("briefing_population_importance", data, "importance.md", "importance.schema.json",
                                    max_output=max_output, schema_override=schema)
                values = normalize_assessments(prior["assessments"])
                recorded.append((key, receipt, response, values, assessment_coverage(values, expected)))
            else:
                client.stopped.set()
                raise ReplayError("cached_noncomplete_provider_result_cannot_be_bypassed")
        # Inspect every existing request before choosing a good cache: an unknown sibling is never hidden by it.
        for _, _, _, values, problem in recorded:
            if problem is None:
                return values
        object_key = client.request_digest("briefing_population_importance", data, "importance.md", "importance.schema.json",
                                           max_output=12000, schema_override=object_schema)
        for key, receipt, response, _, problem in recorded:
            if key == object_key:
                client.stopped.set()
                raise ReplayError("required_document_object_result_invalid_no_blind_retry")
            repairs = client.calls.parent / "coverage-repairs"
            private_dir(repairs)
            save_json(repairs / (key + "-to-" + object_key + ".json"), {
                "schemaVersion": "zoop-assessment-coverage-correction-v2", "originalRequestDigest": key,
                "correctedRequestDigest": object_key,
                "reason": "operator_authorized_known_output_truncation" if receipt["status"] == "incomplete" else "completed_response_document_coverage_error",
                "originalStatus": receipt["status"], "originalHttpStatus": receipt["httpStatus"],
                "originalUsageKnown": receipt["usageKnown"],
                "originalIncompleteReason": (response.get("incomplete_details") or {}).get("reason"),
                "operatorAuthorized": True, "operatorInboxRef": authorization.get("userInboxRef"),
                "sourceSha256": authorization.get("sourceSha256"), "expectedDocumentIds": sorted(expected), **problem,
                "correctionPolicy": "required-document-id-object-v2", "maxOutputTokens": 12000})
        output = client.call("briefing_population_importance", data, "importance.md", "importance.schema.json",
                             max_output=12000, schema_override=object_schema)
        values = normalize_assessments(output["assessments"])
        if assessment_coverage(values, expected) is not None:
            client.stopped.set()
            raise ReplayError("population_assessment_omitted_or_invented_document")
        return values

    with ThreadPoolExecutor(max_workers=min(3, workers)) as executor:
        assessments = [value for batch in executor.map(assess, batches) for value in batch]
    return assessments


def importance_batch_schemas(expected):
    array_schema = strict_load(regular(PROMPTS / "importance.schema.json"))
    array_schema["properties"]["assessments"]["minItems"] = len(expected)
    array_schema["properties"]["assessments"]["maxItems"] = len(expected)
    item = array_schema["properties"]["assessments"]["items"]
    item["properties"]["documentId"]["enum"] = sorted(expected)
    properties = {}
    for document_id in sorted(expected):
        per_document = strict_load(canonical(item))
        per_document["properties"]["documentId"]["enum"] = [document_id]
        properties[document_id] = per_document
    object_schema = {"type": "object", "properties": {"assessments": {
        "type": "object", "properties": properties, "required": sorted(expected), "additionalProperties": False}},
        "required": ["assessments"], "additionalProperties": False}
    return array_schema, object_schema


def normalize_assessments(value):
    if type(value) is list:
        return value
    if type(value) is not dict or any(type(item) is not dict or item.get("documentId") != key for key, item in value.items()):
        raise ReplayError("assessment_required_key_and_document_id_mismatch")
    return [value[key] for key in sorted(value)]


def coverage_corrections(client, authorization):
    rows = []
    for path in sorted((client.calls.parent / "coverage-repairs").glob("*.json")):
        value = strict_load(regular(path))
        # Older completion-only audit files remain byte-identical; enrich their bundle projection in memory.
        if value.get("schemaVersion") == "zoop-assessment-coverage-correction-v1":
            receipt, _ = client.inspect_recorded(value["originalRequestDigest"])
            value = {**value, "schemaVersion": "zoop-assessment-coverage-correction-v2",
                     "reason": "completed_response_document_coverage_error", "originalStatus": receipt["status"],
                     "originalHttpStatus": receipt["httpStatus"], "originalUsageKnown": receipt["usageKnown"],
                     "originalIncompleteReason": None, "operatorAuthorized": True,
                     "operatorInboxRef": authorization.get("userInboxRef"), "sourceSha256": authorization.get("sourceSha256"),
                     "originalAuditSha256": digest(regular(path)), "correctionPolicy": "input-id-array-v1", "maxOutputTokens": 8000}
        rows.append(value)
    return rows


def assessment_coverage(values, expected):
    ids = [value["documentId"] for value in values]
    if len(ids) == len(set(ids)) and set(ids) == expected:
        return None
    return {"missingDocumentIds": sorted(expected - set(ids)), "inventedDocumentIds": sorted(set(ids) - expected),
            "duplicateDocumentIds": sorted({value for value in ids if ids.count(value) > 1}),
            "actualCount": len(ids), "expectedCount": len(expected)}


def shortlist(assessments, rows, maximum=12):
    by_id = {row["documentId"]: row for row in rows}
    ranked = sorted((value for value in assessments if value["status"] == "ELIGIBLE" and value["importance"] >= 2),
                    key=lambda value: (-value["priority"], -value["importance"], value["documentId"]))
    chosen = []
    events = set()
    for assessment in ranked:
        event = re.sub(r"\s+", " ", assessment["eventKey"].casefold()).strip()
        if not event or event in events:
            continue
        events.add(event)
        row = by_id[assessment["documentId"]]
        chosen.append({"documentId": row["documentId"], "title": row.get("title") or row.get("providerBodyTitle") or "",
                       "sourceKind": row.get("sourceKind"), "url": row["url"], "companyNames": row["companyNames"],
                       "dateContext": row["dateContext"], "bodyScope": row.get("bodyScope"),
                       "body": row["body"], "assessment": assessment})
        if len(chosen) >= maximum:
            break
    return chosen


def freeze_selection(output, candidates, rows, source_sha):
    choices = output["selected"]
    if len(choices) > 3:
        raise ReplayError("selected_more_than_three_issues")
    allowed = {value["documentId"]: value for value in candidates}
    raw = {row["documentId"]: row for row in rows}
    events = set()
    selected = []
    used_documents = set()
    for rank, choice in enumerate(choices, 1):
        event = choice["eventKey"].strip().casefold()
        if not event or event in events or choice["importance"] < 2:
            raise ReplayError("invalid_or_duplicate_selected_event")
        events.add(event)
        sources = []
        allowed_names = set()
        for citation in choice["sources"]:
            document_id = citation["documentId"]
            if document_id not in allowed:
                raise ReplayError("selected_source_not_in_ai_shortlist")
            if document_id in used_documents:
                raise ReplayError("one_source_cannot_create_multiple_headline_issues")
            row = raw[document_id]
            allowed_names.update(row["companyNames"])
            seen_quotes = set()
            for quote in citation["quotes"]:
                if len(quote.strip()) < 20 or quote in seen_quotes:
                    raise ReplayError("citation_too_short_or_duplicate")
                start = row["body"].find(quote)
                if start < 0:
                    raise ReplayError("citation_is_not_exact_original_substring")
                seen_quotes.add(quote)
                evidence_id = "evidence-replay-" + digest(canonical([document_id, row["bodySha256"], start, start + len(quote)]))[:28]
                sources.append({"documentId": document_id, "documentVersion": row["documentVersion"],
                                "bodySha256": row["bodySha256"], "url": row["url"], "quote": quote,
                                "start": start, "end": start + len(quote), "offsetUnit": "unicode_code_point",
                                "evidenceId": evidence_id, "sourceMetadata": source_metadata(row),
                                "dateContext": row["dateContext"]})
        if not sources or not set(choice["companyNames"]).issubset(allowed_names):
            raise ReplayError("selected_company_or_evidence_not_from_input")
        used_documents.update(source["documentId"] for source in sources)
        issue_id = "issue-replay-" + digest(canonical([source_sha, sorted({source["documentId"] for source in sources})]))[:24]
        selected.append({"issueId": issue_id, "rank": rank, "title": choice["title"], "reason": choice["reason"],
                         "companyNames": choice["companyNames"], "score": choice["priority"], "importance": choice["importance"],
                         "limitations": choice["limitations"], "sources": sources})
    return selected


def generation_input(selected, edition, authorization):
    return {"edition": edition, "roundDate": ROUND_DATE, "scheduledAtKST": "09:20" if edition == "morning" else "17:30",
            "scope": "historical_development_replay", "sameWeeklyPoolForBothEditions": True,
            "authorization": authorization, "marketInputsAvailable": False, "previousOutlookAvailable": False,
            "collectedAfterHistoricalRound": True, "selected": selected}


def validate_generated(draft, selected):
    expected = [(value["issueId"], value["rank"]) for value in selected]
    actual = [(value["issueId"], value["rank"]) for value in draft["items"]]
    if expected != actual:
        raise ReplayError("generation_changed_selected_order_or_membership")
    for item, source in zip(draft["items"], selected):
        allowed = {value["evidenceId"] for value in source["sources"]}
        if not 1 <= len(item["title"].strip()) <= 80 or not 2 <= len(item["claims"]) <= 3:
            raise ReplayError("generation_title_or_claim_count_invalid")
        for ids in [item["titleEvidenceIds"], *(claim["evidenceIds"] for claim in item["claims"])]:
            if not ids or len(set(ids)) != len(ids) or not set(ids).issubset(allowed):
                raise ReplayError("generation_foreign_or_missing_citations")
        for text in [item["title"], *(claim["text"] for claim in item["claims"])]:
            if re.search(r"매수|매도|목표가|수익.{0,3}보장|오늘|내일|금일|종가|장\s*마감|환율\s*마감", text):
                raise ReplayError("generation_unsupported_market_time_or_investment_advice")
    return draft


def semantic_passed(draft, verification):
    expected = set()
    for item in draft["items"]:
        expected.add(item["issueId"] + ":title")
        expected.update(item["issueId"] + ":claim:" + str(index) for index in range(len(item["claims"])))
    seen = set()
    passed = True
    for check in verification["checks"]:
        target = check["targetId"]
        if target not in expected or target in seen:
            raise ReplayError("semantic_verification_unknown_or_duplicate_target")
        seen.add(target)
        passed = passed and check["verdict"] == "SUPPORTED" and all(check[field] for field in (
            "typeAppropriate", "temporalAppropriate", "noUnsupportedNumbers", "noInvestmentAdvice"))
    if seen != expected:
        raise ReplayError("semantic_verification_omitted_title_or_claim")
    return passed


def generate_edition(client, selected, edition, authorization, repairs=1):
    data = generation_input(selected, edition, authorization)
    last_draft = None
    last_validation = None
    prompt = "generation-" + edition + ".md"
    stages = []
    for attempt in range(repairs + 1):
        request = {**data, "repairAttempt": attempt, "priorDraft": last_draft, "priorValidation": last_validation}
        draft = client.call("briefing_" + edition + "_generation", request, prompt, "generation.schema.json", 6000)
        try:
            validate_generated(draft, selected)
        except ReplayError as error:
            last_draft, last_validation = draft, {"status": "STRUCTURE_FAILED", "reason": str(error)}
            stages.append({"attempt": attempt, "verification": last_validation})
            continue
        verification = client.call("briefing_" + edition + "_verification", {**data, "draft": draft},
                                   "verification.md", "verification.schema.json", 8000)
        passed = semantic_passed(draft, verification)
        last_validation = {"status": "PASS" if passed else "WITHHELD", **verification,
                           "meaning": "Separate model assessment against fixed quotes; not independent external fact verification."}
        stages.append({"attempt": attempt, "verification": last_validation})
        last_draft = draft
        if passed:
            break
    return {"generatedAt": now(), "items": (last_draft or {}).get("items", []),
            "verification": last_validation or {"status": "WITHHELD", "checks": []}, "attempts": stages,
            "usage": [receipt for receipt in client.receipts() if receipt["stage"].startswith("briefing_" + edition + "_")]}


def run(args, transport=None):
    output = Path(args.output).resolve()
    private_dir(output)
    rows, audit = population(Path(args.sources), args.excerpt_chars)
    source_sha = audit["sourceFileSha256"]
    authorization = {"scope": "development_replay", "sourceSha256": source_sha, "userInboxRef": args.user_inbox_ref,
                     "originalSourcePermissionsUnchanged": True, "productionAuthorized": False}
    prompt_digests = {path.name: digest(regular(path)) for path in sorted(PROMPTS.iterdir()) if path.is_file()}
    identity = {"sourceFileSha256": source_sha, "authorization": authorization, "batchSize": args.batch_size,
                "excerptCharacters": args.excerpt_chars, "shortlistSize": args.shortlist_size, "roundDate": ROUND_DATE,
                "maxRepairs": args.max_repairs, "promptArtifacts": prompt_digests,
                "model": MODEL, "schemaVersion": "zoop-briefing-replay-v1"}
    run_id = "brf-replay-" + digest(canonical(identity))[:24]
    save_json(output / "identity.json", {**identity, "runId": run_id})
    save_json(output / "population-audit.json", audit)
    stages = (len(rows) + args.batch_size - 1) // args.batch_size
    plan = {"runId": run_id, "sourceFileSha256": source_sha, "total": audit["totalRecords"], "eligible": len(rows),
            "excluded": audit["excludedRecords"], "populationAssessmentCalls": stages,
            "plannedCallsWithoutRepair": stages + 5, "maximumCallsWithOneRepairPerEdition": stages + 9,
            "batchSize": args.batch_size, "concurrency": args.workers, "paidCallsMade": False,
            "model": MODEL, "productionAuthorized": False, "sourceCollectedAfterRound": True}
    if not args.execute_authorized_development:
        return {**plan, "status": "OFFLINE_AUDIT_ONLY"}
    if not args.user_inbox_ref or not (args.key_file or transport):
        raise ReplayError("development_authorization_reference_and_key_required")
    if stages + 9 > args.max_calls:
        raise ReplayError("planned_population_exceeds_paid_call_budget")
    lock_path = output / ".run.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ReplayError("another_or_interrupted_operator_run_requires_inspection") from error
    os.close(lock_fd)
    client = None
    try:
        client = ResponsesClient(output, transport or authenticated_transport(Path(args.key_file)), args.max_calls,
                                 args.complete_known_truncation)
        assessments = assess_all(client, rows, authorization, args.batch_size, args.workers)
        save_json(output / "assessments.json", assessments)
        candidates = shortlist(assessments, rows, args.shortlist_size)
        save_json(output / "shortlist.json", candidates)
        if not candidates:
            save_json(output / "receipts.json", client.receipts())
            return {**plan, "status": "HOLD_NO_SUPPORTED_MATERIAL_CANDIDATES", "newPaidCalls": len(client.new_calls),
                    "paidCallsMade": bool(client.new_calls)}
        selection = client.call("briefing_global_selection", {"scope": "development_replay", "authorization": authorization,
                                "documents": candidates, "maximumIssues": 3, "marketInputsAvailable": False,
                                "previousOutlookAvailable": False}, "selection.md", "selection.schema.json", 8000)
        selected = freeze_selection(selection, candidates, rows, source_sha)
        save_json(output / "selected.json", selected)
        if not selected:
            save_json(output / "receipts.json", client.receipts())
            return {**plan, "status": "HOLD_FINAL_SELECTION_INSUFFICIENT_EVIDENCE", "newPaidCalls": len(client.new_calls),
                    "paidCallsMade": bool(client.new_calls)}
        editions = {}
        for edition in ("morning", "evening"):
            edition_file = output / (edition + ".json")
            if edition_file.exists():
                binding = strict_load(regular(output / (edition + ".binding.json")))
                if binding != {"runId": run_id, "recordingSha256": digest(regular(edition_file)), "promptArtifacts": prompt_digests}:
                    raise ReplayError("cached_edition_source_prompt_or_content_binding_changed")
                editions[edition] = strict_load(regular(edition_file))
                validate_generated({"items": editions[edition]["items"]}, selected)
                if not semantic_passed({"items": editions[edition]["items"]}, editions[edition]["verification"]):
                    raise ReplayError("cached_edition_is_not_verified")
            else:
                editions[edition] = generate_edition(client, selected, edition, authorization, args.max_repairs)
                save_json(edition_file, editions[edition])
                save_json(output / (edition + ".binding.json"), {"runId": run_id, "recordingSha256": digest(regular(edition_file)),
                                                              "promptArtifacts": prompt_digests})
        receipts = client.receipts()
        bundle = {"schemaVersion": "zoop-briefing-replay-v1", "runId": run_id, "sourceFileSha256": source_sha,
                  "authorization": authorization, "graphVersion": None,
                  "historicalReplay": {"sourcePeriod": {"start": "2026-10-02", "end": "2026-10-08"},
                                       "roundDate": ROUND_DATE, "sameSourcePoolForBothEditions": True,
                                       "collectionAfterRound": True, "sourceDatesMayBeProviderEstimates": True,
                                       "meaning": "Both formats replay the same weekly pool collected later, not real AM/PM windows."},
                  "selected": selected, "editions": editions, "receipts": receipts,
                  "coverageCorrections": coverage_corrections(client, authorization),
                  "marketSummary": {"status": "unavailable", "reason": "No market-summary producer in this replay."},
                  "marketVariables": {"status": "unavailable", "reason": "No market indicators were collected for this replay."},
                  "sinceMorning": {"status": "unavailable", "reason": "Same weekly input in both formats; not a real intra-day comparison."}}
        save_json(output / "bundle.json", bundle)
        save_json(output / "receipts.json", receipts)
        return {**plan, "status": "PASS" if all(value["verification"]["status"] == "PASS" for value in editions.values()) else "WITHHELD",
                "selectedCount": len(selected), "selected": [{key: value[key] for key in ("issueId", "rank", "title", "reason", "score")} for value in selected],
                "newPaidCalls": len(client.new_calls), "reusedCalls": len(client.reused_calls),
                "paidCallsMade": bool(client.new_calls),
                "coverageCorrections": len(list((output / "coverage-repairs").glob("*.json"))),
                "inputTokens": sum(value["inputTokens"] for value in receipts) if all(value["usageKnown"] for value in receipts) else None,
                "outputTokens": sum(value["outputTokens"] for value in receipts) if all(value["usageKnown"] for value in receipts) else None,
                "bundlePath": str(output / "bundle.json")}
    finally:
        if client is not None:
            # Receipt snapshots are immutable content-addressed, including failed/unknown attempts.
            accounting = canonical(client.receipts())
            write_once(output / ("accounting-" + digest(accounting) + ".json"), accounting)
        lock_path.unlink(missing_ok=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--sources", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--key-file")
    result.add_argument("--user-inbox-ref", required=True)
    result.add_argument("--execute-authorized-development", action="store_true")
    result.add_argument("--batch-size", type=bounded(20, 30), default=30, metavar="20..30")
    result.add_argument("--workers", type=bounded(1, 3), default=3, metavar="1..3")
    result.add_argument("--excerpt-chars", type=bounded(600, 3000), default=1400, metavar="600..3000")
    result.add_argument("--shortlist-size", type=bounded(3, 15), default=12, metavar="3..15")
    result.add_argument("--max-repairs", type=int, default=1, choices=(0, 1))
    result.add_argument("--max-calls", type=bounded(9, MAX_CALLS), default=MAX_CALLS, metavar="9..64")
    result.add_argument("--complete-known-truncation", action="append", default=[], type=sha256_argument, metavar="SHA256",
                        help="explicitly authorize a new constrained request for this known HTTP200/max_output_tokens/usage-known result")
    return result


def bounded(minimum, maximum):
    def convert(value):
        number = int(value)
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"integer in {minimum}..{maximum} required")
        return number
    return convert


def sha256_argument(value):
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise argparse.ArgumentTypeError("lowercase SHA-256 required")
    return value


def main():
    try:
        summary = run(parser().parse_args())
        print(canonical(summary).decode("utf-8"))
        return 0 if summary["status"] in ("OFFLINE_AUDIT_ONLY", "PASS") else 2
    except ReplayError as error:
        print(json.dumps({"status": "STOPPED", "reason": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as error:
        # Never print transport bodies, credentials, raw input or exception text to shared logs.
        print(json.dumps({"status": "STOPPED", "reason": "operator_error", "errorClass": type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
