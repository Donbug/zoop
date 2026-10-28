#!/usr/bin/env python3
"""Explicit per-round publication-clock simulation; default is offline, never an operating publication path."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
import argparse
import importlib.util
import os
from pathlib import Path
import sys

_SPEC = importlib.util.spec_from_file_location("_zoop_replay_primitives", Path(__file__).with_name("briefing_replay.py"))
base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(base)
PROMPTS = Path(__file__).resolve().parents[1] / "api/src/main/resources/briefing/prompts/round-simulation"
MODE = "publication_clock_simulation"
SHORTLIST_POLICY = "eligible_or_full_body_hold_importance_gte2_v2"
KST = timezone(timedelta(hours=9))
BASELINE = "2026-10-01T17:30:00+09:00"
canonical, digest, ReplayError = base.canonical, base.digest, base.ReplayError
QUALITY_V2 = "novelty-recovery-v2"


def helper(name):
    spec = importlib.util.spec_from_file_location("_zoop_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def aware(value):
    if type(value) is not str:
        raise ReplayError("publisher_timestamp_missing_or_naive")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReplayError("publisher_timestamp_invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReplayError("publisher_timestamp_missing_or_naive")
    return parsed


def windows():
    out = []
    for offset in range(7):
        day = date(2026, 10, 2) + timedelta(days=offset)
        for edition in ("morning", "evening"):
            start = datetime.combine(day - timedelta(days=1), time(17, 30), KST) if edition == "morning" \
                    else datetime.combine(day, time(9, 20), KST)
            end = datetime.combine(day, time(9, 20) if edition == "morning" else time(17, 30), KST)
            out.append({"date": day.isoformat(), "edition": edition,
                        "window": {"from": start.isoformat(), "to": end.isoformat(), "openStart": False}})
    return out


def load_inputs(sources_path, clocks_path, html_root=None):
    source_bytes, clock_bytes = base.regular(sources_path), base.regular(clocks_path)
    source_sha, clock_sha = digest(source_bytes), digest(clock_bytes)
    registry = base.strict_load(clock_bytes)
    if registry.get("schemaVersion") != "zoop-publication-clock-registry-v1" or registry.get("sourceFileSha256") != source_sha:
        raise ReplayError("publication_clock_registry_source_mismatch")
    records = {}
    for record in registry.get("records", []):
        if type(record) is not dict or record.get("documentId") in records:
            raise ReplayError("duplicate_or_invalid_publication_clock_record")
        records[record.get("documentId")] = record
    rows, ids, unknown = [], set(), []
    root = html_root or clocks_path.parent / "html"
    for line in source_bytes.decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = base.strict_load(line)
        document = row.get("documentId")
        if not document or document in ids or len(ids) >= 1000:
            raise ReplayError("source_document_identity_or_population_invalid")
        ids.add(document)
        body = row.get("body")
        reason = None
        if type(body) is not str or len(body.strip()) < 80:
            reason = "body_missing_or_insufficient"
        elif digest(body.encode()) != row.get("bodySha256"):
            reason = "body_sha256_mismatch"
        clock = records.get(document)
        if clock is None:
            reason = reason or "clock_not_observed"
        elif clock.get("status") != "verified_timestamp":
            reason = reason or ("clock_" + str(clock.get("status", "unverified")))
        else:
            if clock.get("schemaVersion") != "zoop-publication-clock-v1" \
                    or clock.get("sourceFileSha256") != source_sha or clock.get("bodySha256") != row.get("bodySha256") \
                    or clock.get("url") != row.get("url") or clock.get("httpStatus") != 200:
                raise ReplayError("verified_clock_source_binding_mismatch")
            stamp = aware(clock.get("publishedAt"))
            aware(clock.get("checkedAt"))
            html_sha = clock.get("htmlSha256")
            if type(html_sha) is not str or len(html_sha) != 64 or any(c not in "0123456789abcdef" for c in html_sha):
                raise ReplayError("verified_clock_html_digest_missing")
            if digest(base.regular(root / (html_sha + ".html"))) != html_sha:
                raise ReplayError("verified_clock_html_digest_mismatch")
            if reason is None:
                rows.append({**row, "documentVersion": "sha256-" + row["bodySha256"],
                             "companyNames": base.company_names(row),
                             "dateContext": {"precision": "publisher_declared_timestamp", "publishedAt": clock["publishedAt"],
                                             "checkedAt": clock["checkedAt"], "historicalBodyUnchangedProven": False},
                             "clockRecord": clock, "clockRecordSha256": digest(canonical(clock)), "clockTime": stamp})
        if reason:
            unknown.append({"documentId": document, "bodySha256": row.get("bodySha256"), "reason": reason,
                            "sourceMetadata": base.source_metadata(row), "clockRecord": clock})
    if set(records) - ids:
        raise ReplayError("clock_registry_contains_unknown_source_document")
    return rows, unknown, {"sourceFileSha256": source_sha, "clockFileSha256": clock_sha,
                           "totalRecords": len(ids), "verifiedTimestampRecords": len(rows), "unconfirmedTotal": len(unknown)}


def pool_for_round(rows, spec, unconfirmed_total):
    start, end = aware(spec["window"]["from"]), aware(spec["window"]["to"])
    in_window = [row for row in rows if start < row["clockTime"] <= end]
    pool, duplicates, seen = [], [], {}
    # Dedupe only AFTER selecting the round's clock window. A copy outside the window cannot remove this one.
    for row in sorted(in_window, key=lambda item: item["documentId"]):
        sha = row["bodySha256"]
        if sha in seen:
            duplicates.append({"documentId": row["documentId"], "duplicateOf": seen[sha], "bodySha256": sha,
                               "publishedAt": row["clockRecord"]["publishedAt"]})
        else:
            seen[sha] = row["documentId"]
            pool.append(row)
    input_sources = [{"documentId": row["documentId"], "documentVersion": row["documentVersion"],
                      "bodySha256": row["bodySha256"]} for row in pool]
    clock_refs = [{"documentId": row["documentId"], "bodySha256": row["bodySha256"],
                   "publishedAt": row["clockRecord"]["publishedAt"], "clockRecordSha256": row["clockRecordSha256"],
                   "htmlSha256": row["clockRecord"]["htmlSha256"]} for row in pool]
    late, missing = 0, 0
    for row in pool:
        value = row.get("bodyAcquiredAt") or row.get("collectedAt")
        if value is None:
            missing += 1
        else:
            try:
                late += aware(value) > end
            except ReplayError:
                missing += 1
    coverage = {"confirmedInWindow": len(in_window), "uniqueInputCount": len(pool),
                "excludedDuplicateCount": len(duplicates), "unconfirmedTotal": unconfirmed_total,
                "operationalCollectionGate": False, "lateCollectionCount": late, "collectionTimestampMissingCount": missing,
                "historicalBodyUnchangedProven": False, "partialSourceCoverage": unconfirmed_total > 0}
    return pool, input_sources, clock_refs, duplicates, coverage


class SimulationClient(base.ResponsesClient):
    """Uses only new simulation resources/output; no weekly prompts or recording lookup."""
    def request(self, stage, data, prompt_name, schema_name, max_output=12000, schema_override=None):
        instructions = base.regular(PROMPTS / prompt_name).decode("utf-8")
        expected_prompt = data.get("context", {}).get("promptArtifacts", {}).get(prompt_name)
        if expected_prompt is not None and digest(instructions.encode()) != expected_prompt:
            raise ReplayError("simulation_prompt_changed_after_input_freeze")
        schema = base.strict_load(canonical(schema_override)) if schema_override is not None \
                 else base.strict_load(base.regular(PROMPTS / schema_name))
        request = {"model": base.MODEL, "store": False, "max_output_tokens": max_output, "instructions": instructions,
                   "input": canonical(data).decode("utf-8"), "reasoning": {"effort": "low"},
                   "text": {"format": {"type": "json_schema", "name": stage, "strict": True, "schema": schema}}}
        encoded = canonical(request)
        if len(encoded) > 2 * 1024 * 1024:
            raise ReplayError("round_request_size_exceeded")
        return encoded, schema, digest(instructions.encode())


def schema(name):
    return base.strict_load(base.regular(PROMPTS / (name + ".schema.json")))


def keyed_schema(name, field, keys, id_field, ranks=None):
    item = schema(name)["properties"][field]["items"]
    properties = {}
    for key in keys:
        value = base.strict_load(canonical(item))
        value["properties"][id_field]["enum"] = [key]
        if ranks is not None:
            value["properties"]["rank"]["enum"] = [ranks[key]]
        properties[key] = value
    return {"type": "object", "properties": {field: {"type": "object", "properties": properties,
            "required": list(keys), "additionalProperties": False}}, "required": [field], "additionalProperties": False}


def context_receipts(client, *context_hashes):
    values = []
    for receipt in client.receipts():
        request = base.strict_load(base.regular(client.calls / (receipt["requestDigest"] + ".request.json")))
        data = base.strict_load(request["input"])
        if data.get("contextSha256") in context_hashes:
            values.append(receipt)
    return values


def assessment_schema(ids):
    original = schema("importance")["properties"]["assessments"]["items"]
    properties = {}
    for key in sorted(ids):
        value = base.strict_load(canonical(original))
        value["properties"]["documentId"]["enum"] = [key]
        properties[key] = value
    return {"type": "object", "properties": {"assessments": {"type": "object", "properties": properties,
            "required": sorted(ids), "additionalProperties": False}}, "required": ["assessments"], "additionalProperties": False}


def model_context(identity, identity_sha, previous_result):
    return {"context": identity, "contextSha256": identity_sha,
            "simulatedPreviousOutput": previous_result, "marketInputsAvailable": False,
            "priceForecastEvaluationAvailable": False, "operationalCollectionGate": False}


def assess_round(client, pool, context, batch_size, workers):
    batches = [pool[i:i + batch_size] for i in range(0, len(pool), batch_size)]
    def assess(batch):
        documents = []
        for row in batch:
            body = row["body"]
            prefix = body[:1050]
            suffix = body[-350:] if len(body) > 1400 else body[1050:]
            documents.append({"documentId": row["documentId"], "title": row.get("title") or row.get("providerBodyTitle") or "",
                              "companyNames": row["companyNames"], "sourceKind": row.get("sourceKind"),
                              "url": row["url"], "dateContext": row["dateContext"], "bodyScope": row.get("bodyScope"),
                              "excerpts": [prefix, suffix], "bodySha256": row["bodySha256"],
                              "sourceMetadata": base.source_metadata({k: v for k, v in row.items() if k != "clockTime"})})
        ids = {row["documentId"] for row in batch}
        reply = client.call("round_simulation_importance", {**context, "documents": documents},
                            "importance.md", "importance.schema.json", max_output=12000, schema_override=assessment_schema(ids))
        values = base.normalize_assessments(reply["assessments"])
        if base.assessment_coverage(values, ids) is not None:
            client.stopped.set()
            raise ReplayError("round_assessment_document_coverage_mismatch")
        return values
    with ThreadPoolExecutor(max_workers=min(3, workers)) as executor:
        return [item for values in executor.map(assess, batches) for item in values]


def shortlist_round(assessments, pool, maximum=12):
    rows = {row["documentId"]: row for row in pool}
    values = sorted((a for a in assessments if a["status"] in {"ELIGIBLE", "HOLD"} and a["importance"] >= 2
                     and type(rows[a["documentId"]].get("body")) is str and len(rows[a["documentId"]]["body"].strip()) >= 80),
                    key=lambda a: (-a["importance"], -a["priority"], a["documentId"]))
    output, seen = [], set()
    for assessment in values:
        event = " ".join(assessment["eventKey"].casefold().split())
        if not event or event in seen:
            continue
        seen.add(event)
        row = rows[assessment["documentId"]]
        output.append({"documentId": row["documentId"], "body": row["body"], "title": row.get("title") or row.get("providerBodyTitle") or "",
                       "companyNames": row["companyNames"], "sourceKind": row.get("sourceKind"), "url": row["url"],
                       "dateContext": row["dateContext"], "bodyScope": row.get("bodyScope"), "assessment": assessment})
        if len(output) >= maximum:
            break
    return output


def freeze_round_selection(reply, candidates, pool, identity_sha):
    choices = sorted(reply["selected"], key=lambda value: (-value["importance"], -value["priority"], value["eventKey"]))
    for value in choices:
        if value["importance"] == 3 and (value["scope"] not in {"COMMON_POLICY", "BROAD_MARKET"}
                or not value["transmission"].strip() or (value["scope"] == "BROAD_MARKET" and len(set(value["affectedSectors"])) < 2)):
            raise ReplayError("importance_three_impact_proof_missing")
    selected = base.freeze_selection({"selected": choices}, candidates,
                                     [{key: value for key, value in row.items() if key != "clockTime"} for row in pool], identity_sha)
    by_id = {row["documentId"]: row for row in pool}
    for item, choice in zip(selected, choices):
        item["issueId"] = item["issueId"].replace("issue-replay-", "issue-simulation-", 1)
        item["scope"], item["affectedSectors"], item["transmission"] = choice["scope"], choice["affectedSectors"], choice["transmission"]
        item["groupingMeaning"] = "AI editorial grouping, not canonical graph identity or source independence."
        for citation in item["sources"]:
            row = by_id[citation["documentId"]]
            citation["publicationClock"] = row["clockRecord"]
            citation["clockRecordSha256"] = row["clockRecordSha256"]
    return selected


def choose_round(client, candidates, pool, context, identity_sha):
    if context.get("qualityPolicy") == QUALITY_V2:
        return choose_round_v2(client, candidates, pool, context, identity_sha), [], False
    selection_schema = schema("selection")
    selection_schema["properties"]["selected"]["items"]["properties"]["sources"]["items"]["properties"]["documentId"]["enum"] = sorted({row["documentId"] for row in candidates})
    stage = "round_simulation_selection"
    data = {**context, "documents": candidates, "maximumIssues": 3}
    original_key = client.request_digest(stage, data, "selection.md", "selection.schema.json",
                                         max_output=12000, schema_override=selection_schema)
    reply = client.call(stage, data, "selection.md", "selection.schema.json",
                        max_output=12000, schema_override=selection_schema)
    try:
        return freeze_round_selection(reply, candidates, pool, identity_sha), [], False
    except ReplayError as error:
        if str(error) != "citation_is_not_exact_original_substring":
            raise
    receipt, provider_response = client.inspect_recorded(original_key)
    if receipt.get("status") != "completed" or provider_response.get("status") != "completed" \
            or receipt.get("stage") != stage:
        raise ReplayError("selection_correction_requires_known_completed_response")
    correction = {"attempt": 1, "reason": "citation_is_not_exact_original_substring",
                  "originalRequestDigest": original_key, "originalResponseSha256": receipt["responseSha256"],
                  "priorSelection": reply, "sameFrozenBodies": True,
                  "instruction": "Correct only with exact literal continuous substrings copied from the same documents.body. "
                      "Never translate, normalize whitespace, paraphrase, invent facts, or relax selection criteria. "
                      "Recheck the complete selection under the unchanged criteria. If exact supporting quotes cannot be copied, "
                      "omit that issue and explain it in held. This is the only structural correction attempt."}
    corrected_data = {**data, "selectionStructuralCorrection": correction}
    corrected_key = client.request_digest(stage, corrected_data, "selection.md", "selection.schema.json",
                                          max_output=12000, schema_override=selection_schema)
    corrected = client.call(stage, corrected_data, "selection.md", "selection.schema.json",
                            max_output=12000, schema_override=selection_schema)
    audit = {key: correction[key] for key in ("attempt", "reason", "originalRequestDigest", "originalResponseSha256")}
    audit.update({"correctedRequestDigest": corrected_key, "sameFrozenBodies": True, "status": "PASS"})
    try:
        selected = freeze_round_selection(corrected, candidates, pool, identity_sha)
    except ReplayError as error:
        audit.update({"status": "WITHHELD", "validationError": str(error)})
        return [], [audit], True
    if not selected:
        audit.update({"status": "WITHHELD", "validationError": "selection_correction_has_no_supported_issue"})
        return [], [audit], True
    return selected, [audit], False


def choose_round_v2(client, candidates, pool, context, identity_sha):
    quality = helper("briefing_quality")
    candidates = quality.catalog_candidates(candidates)
    selection_schema = schema("selection-v2")
    source_properties = selection_schema["properties"]["selected"]["items"]["properties"]["sources"]["items"]["properties"]
    source_properties["documentId"]["enum"] = sorted(row["documentId"] for row in candidates)
    source_properties["quoteIds"]["items"]["enum"] = sorted(q["quoteId"] for row in candidates for q in row["quoteCatalog"])
    data = {**context, "documents": candidates, "maximumIssues": 3}
    if context.get("operatorRecovery"):
        recovery = helper("briefing_http_recovery")
        data = recovery.recovery_data(data, context["operatorRecovery"])
        key = client.request_digest("round_simulation_selection", data, "selection-v2.md", "selection-v2.schema.json",
                                    max_output=12000, schema_override=selection_schema)
        ledger = client.calls.parent.parent / "recovery-ledger"
        base.private_dir(ledger)
        marker = ledger / (context["operatorRecovery"]["originalRequestDigest"] + ".json")
        reservation = {"recovery": context["operatorRecovery"], "replacementRequestDigest": key,
                       "outputDirectory": str(client.calls.parent)}
        if marker.exists() and base.strict_load(base.regular(marker)) != reservation:
            raise ReplayError("recovery_original_already_attempted")
        base.save_json(marker, reservation)
    reply = client.call("round_simulation_selection", data,
                        "selection-v2.md", "selection-v2.schema.json", max_output=12000, schema_override=selection_schema)
    decisions = {d["documentId"]: d for d in context.get("noveltyAudit", {}).get("decisions", [])}
    for choice in reply["selected"]:
        for source in choice["sources"]:
            decision = decisions.get(source["documentId"], {})
            if decision.get("decision") in {"REPEAT", "UNCERTAIN"}:
                raise ReplayError("repeat_or_uncertain_source_selected")
            if decision.get("decision") == "MATERIAL_UPDATE" and not set(source["quoteIds"]) & set(decision["quoteIds"]):
                raise ReplayError("selected_update_missing_delta_quote")
    try:
        restored = quality.restore_selection(reply, candidates)
    except quality.QualityError as error:
        raise ReplayError(str(error)) from error
    selected = freeze_round_selection(restored, candidates, pool, identity_sha)
    choices = sorted(restored["selected"], key=lambda value: (-value["importance"], -value["priority"], value["eventKey"]))
    for item, choice in zip(selected, choices):
        item["eventKey"] = choice["eventKey"]
        item["quoteBindingPolicy"] = "server_literal_catalog_v2"
        item["novelty"] = [decisions[source["documentId"]] for source in choice["sources"] if source["documentId"] in decisions]
    return selected


def generate_round(client, selected, edition, context, max_repairs):
    last_draft, last_validation, attempts = None, None, []
    generation_key, verification_key = None, None
    for attempt in range(max_repairs + 1):
        if getattr(client, 'usage', None) is not None: client.usage.retry(attempt)
        data = {**context, "selected": selected, "edition": edition, "repairAttempt": attempt,
                "priorDraft": last_draft, "priorValidation": last_validation}
        generation_schema = keyed_schema("generation", "items", [row["issueId"] for row in selected], "issueId",
                                          {row["issueId"]: row["rank"] for row in selected})
        generation_prompt = "generation-" + edition + ".md"
        if context.get("qualityPolicy") == QUALITY_V2:
            generation_prompt = "generation-v2-" + edition + ".md"
            for row in selected:
                properties = generation_schema["properties"]["items"]["properties"][row["issueId"]]["properties"]
                ids = sorted({source["evidenceId"] for source in row["sources"]})
                properties["titleEvidenceIds"]["items"]["enum"] = ids
                properties["claims"]["items"]["properties"]["evidenceIds"]["items"]["enum"] = ids
        generation_key = client.request_digest("round_simulation_" + edition + "_generation", data,
            generation_prompt, "generation.schema.json", max_output=8000, schema_override=generation_schema)
        draft = client.call("round_simulation_" + edition + "_generation", data,
                            generation_prompt, "generation.schema.json", max_output=8000,
                            schema_override=generation_schema)
        if type(draft.get("items")) is dict:
            draft = {"items": [draft["items"][row["issueId"]] for row in selected]}
        if any(not item.get("claims") for item in draft["items"]):
            last_draft, last_validation = draft, {"status": "WITHHELD", "checks": [], "reason": "insufficient_quote_evidence"}
            attempts.append({"attempt": attempt, "verification": last_validation})
            break
        try:
            base.validate_generated(draft, selected)
        except ReplayError as error:
            last_draft, last_validation = draft, {"status": "STRUCTURE_FAILED", "reason": str(error)}
            attempts.append({"attempt": attempt, "verification": last_validation})
            continue
        targets = [target for item in draft["items"] for target in [item["issueId"] + ":title",
                   *(item["issueId"] + ":claim:" + str(index) for index in range(len(item["claims"])))] ]
        verification_data = {**context, "selected": selected, "edition": edition, "draft": draft}
        verification_schema = keyed_schema("verification", "checks", targets, "targetId")
        verification_key = client.request_digest("round_simulation_" + edition + "_verification", verification_data,
            "verification.md", "verification.schema.json", max_output=12000, schema_override=verification_schema)
        decision = client.call("round_simulation_" + edition + "_verification", verification_data,
            "verification.md", "verification.schema.json", max_output=12000, schema_override=verification_schema)
        if type(decision.get("checks")) is dict:
            decision = {"checks": [decision["checks"][target] for target in targets]}
        passed = base.semantic_passed(draft, decision)
        last_draft, last_validation = draft, {"status": "PASS" if passed else "WITHHELD", **decision,
            "meaning": "Separate model assessment against frozen quotes; retrospective simulation, not independent fact verification."}
        attempts.append({"attempt": attempt, "verification": last_validation})
        if passed:
            break
    generation_receipts = [receipt for receipt in context_receipts(client, context["contextSha256"])
                           if receipt["stage"].endswith("_generation")]
    generated_at = max(receipt["finishedAt"] for receipt in generation_receipts)
    return {"generatedAt": generated_at, "items": (last_draft or {}).get("items", []),
            "verification": last_validation or {"status": "WITHHELD", "checks": []}, "attempts": attempts,
            "generationRequestDigest": generation_key, "verificationRequestDigest": verification_key}


def previous_context(prior):
    if prior and prior.get("selectionStatus") == "SELECTED" and (prior.get("result") or {}).get("verification", {}).get("status") == "PASS":
        return {"status": "available", "type": "simulated_previous_output", "roundId": prior["roundId"],
                "resultSha256": prior["resultSha256"]}, prior["result"]
    return {"status": "unavailable", "type": "simulated_previous_output",
            "reason": "No immediately preceding PASS in this simulation; never substitute an older success."}, None


def run(args, transport=None):
    rows, unknown, source = load_inputs(Path(args.sources), Path(args.clocks), Path(args.clock_html_root) if args.clock_html_root else None)
    quality_v2 = args.quality_policy == QUALITY_V2
    legacy_prompts = {"importance.md", "importance.schema.json", "selection.md", "selection.schema.json",
                      "generation-morning.md", "generation-evening.md", "generation.schema.json", "verification.md", "verification.schema.json"}
    prompt_names = legacy_prompts | ({"selection-v2.md", "selection-v2.schema.json", "novelty.md", "novelty.schema.json",
                                     "generation-v2-morning.md", "generation-v2-evening.md", "novelty-verification.md"} if quality_v2 else set())
    prompt_artifacts = {name: digest(base.regular(PROMPTS / name)) for name in sorted(prompt_names)}
    authorization = {"scope": MODE, "sourceSha256": source["sourceFileSha256"], "userInboxRef": args.user_inbox_ref,
                     "productionAuthorized": False}
    run_identity = {"mode": MODE, **source, "authorization": authorization, "promptArtifacts": prompt_artifacts,
                    "batchSize": args.batch_size, "maxRepairs": args.max_repairs, "shortlistPolicy": SHORTLIST_POLICY,
                    "windows": windows()}
    if quality_v2:
        run_identity["qualityPolicy"] = QUALITY_V2
    run_id = "brf-round-simulation-" + digest(canonical(run_identity))[:20]
    plan_rounds, prepared = [], []
    for spec in windows():
        pool, input_sources, clock_refs, duplicates, coverage = pool_for_round(rows, spec, len(unknown))
        calls = (len(pool) + args.batch_size - 1) // args.batch_size + 3 + (2 if quality_v2 else 0) if pool else 0
        plan_rounds.append({**spec, "sourceCoverage": coverage, "plannedCallsIfSelected": calls,
                            "maximumCallsWithOneRepair": calls + 2 if pool and args.max_repairs else calls,
                            "maximumSelectionStructuralCorrections": 1 if pool and not quality_v2 else 0})
        prepared.append((spec, pool, input_sources, clock_refs, duplicates, coverage))
    plan = {"mode": MODE, "runId": run_id, **source, "rounds": plan_rounds,
            "plannedCallsIfSelected": sum(row["plannedCallsIfSelected"] for row in plan_rounds),
            "maximumCallsWithOneRepair": sum(row["maximumCallsWithOneRepair"] for row in plan_rounds),
            "maximumSelectionStructuralCorrections": sum(row["maximumSelectionStructuralCorrections"] for row in plan_rounds),
            "theoreticalMaximumCallsIncludingSelectionCorrections": sum(row["maximumCallsWithOneRepair"] +
                row["maximumSelectionStructuralCorrections"] for row in plan_rounds),
            "maxCalls": args.max_calls, "operationalCollectionGate": False, "retrospectiveBodies": True}
    output = Path(args.output).resolve()
    base.private_dir(output)
    base.save_json(output / "run-identity.json", {**run_identity, "runId": run_id})
    base.save_json(output / "source-coverage-audit.json", {**source, "unconfirmed": unknown})
    if not args.execute_authorized_simulation:
        return {**plan, "status": "OFFLINE_PUBLICATION_CLOCK_AUDIT", "newPaidCalls": 0}
    if plan["plannedCallsIfSelected"] > args.max_calls:
        raise ReplayError("round_simulation_planned_calls_exceed_explicit_budget")
    if not args.user_inbox_ref or not (args.key_file or transport):
        raise ReplayError("simulation_authorization_reference_and_key_required")
    lock = output / ".simulation.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ReplayError("interrupted_or_active_simulation_requires_inspection") from error
    os.close(fd)
    client, rounds = None, []
    try:
        client = SimulationClient(output, transport or base.authenticated_transport(Path(args.key_file)), args.max_calls)
        for spec, pool, input_sources, clock_refs, duplicates, coverage in prepared:
            previous, previous_result = previous_context(rounds[-1] if rounds else None)
            history = helper("briefing_quality").published_history(rounds, spec["window"]["from"]) if quality_v2 else []
            identity = {"mode": MODE, "runId": run_id, "sourceFileSha256": source["sourceFileSha256"],
                        "clockFileSha256": source["clockFileSha256"], **spec, "contextVersion": "round-simulation-v1",
                        "candidateInputSha256": digest(canonical(input_sources)), "promptArtifacts": prompt_artifacts,
                        "previous": previous, "operationalCollectionGate": False, "authorization": authorization,
                        "baseline": {"from": BASELINE, "meaning": "simulation_baseline_not_service_first_round"}}
            if quality_v2:
                identity.update({"qualityPolicy": QUALITY_V2, "noveltyHistorySha256": digest(canonical(history))})
            identity_sha = digest(canonical(identity))
            round_id = "sim-" + spec["date"] + "-" + spec["edition"] + "-" + identity_sha[:12]
            directory = output / (spec["date"] + "-" + spec["edition"])
            base.private_dir(directory)
            base.save_json(directory / "identity.json", identity)
            path = directory / "round.json"
            if path.exists():
                saved_bytes = base.regular(path)
                binding = base.strict_load(base.regular(directory / "round.binding.json"))
                if binding != {"identitySha256": identity_sha, "roundSha256": digest(saved_bytes)}:
                    raise ReplayError("cached_round_identity_or_content_mismatch")
                saved = base.strict_load(saved_bytes)
                if saved.get("result") and digest(canonical(saved["result"])) != saved.get("resultSha256"):
                    raise ReplayError("cached_round_result_digest_mismatch")
                rounds.append(saved)
                continue
            context = model_context(identity, identity_sha, previous_result)
            if quality_v2:
                context.update({"qualityPolicy": QUALITY_V2, "noveltyHistory": history})
            frozen_pool = [{key: value for key, value in row.items() if key != "clockTime"} for row in pool]
            base.save_json(directory / "frozen-input.json", {**context, "documents": frozen_pool})
            record = {"roundId": round_id, **spec, "identity": identity, "identitySha256": identity_sha,
                      "inputSources": input_sources, "clockRefs": clock_refs, "sourceCoverage": coverage,
                      "discardedDuplicateBodies": duplicates, "previous": previous, "selected": [],
                      "result": None, "resultSha256": None, "receipts": []}
            if not pool:
                record["selectionStatus"] = "HELD_SOURCE_COVERAGE" if unknown else "EMPTY_CONFIRMED"
            else:
                assessments = assess_round(client, pool, context, args.batch_size, args.workers)
                base.save_json(directory / "assessments.json", assessments)
                candidates = shortlist_round(assessments, pool)
                if quality_v2 and candidates:
                    candidates = helper("briefing_quality").catalog_candidates(candidates)
                    try:
                        candidates, novelty_audit = helper("briefing_novelty").filter_candidates(client, candidates, history, context)
                    except ValueError as error:
                        raise ReplayError(str(error)) from error
                    record["noveltyAudit"] = novelty_audit
                    base.save_json(directory / "novelty-audit.json", novelty_audit)
                    context["noveltyAudit"] = novelty_audit
                base.save_json(directory / "shortlist.json", candidates)
                selected, selection_corrections, selection_failed = choose_round(client, candidates, pool, context, identity_sha) \
                    if candidates else ([], [], False)
                if selection_corrections:
                    record["selectionCorrections"] = selection_corrections
                base.save_json(directory / "selected.json", selected)
                if selection_failed:
                    record["selectionStatus"] = "HELD_VALIDATION"
                elif not selected:
                    record["selectionStatus"] = "HELD_SOURCE_COVERAGE" if unknown else "EMPTY_CONFIRMED"
                else:
                    result = generate_round(client, selected, spec["edition"], context, args.max_repairs)
                    base.save_json(directory / "generation-result.json", result)
                    if result["verification"]["status"] == "PASS":
                        record["selectionStatus"], record["selected"], record["result"] = "SELECTED", selected, result
                    else:
                        record["selectionStatus"] = "HELD_VALIDATION"
            record["receipts"] = context_receipts(client, identity_sha)
            if record["result"] is not None:
                final_keys = {record["result"]["generationRequestDigest"], record["result"]["verificationRequestDigest"]}
                record["result"]["usage"] = [receipt for receipt in record["receipts"] if receipt["requestDigest"] in final_keys]
                record["resultSha256"] = digest(canonical(record["result"]))
            base.save_json(path, record)
            base.save_json(directory / "round.binding.json", {"identitySha256": identity_sha, "roundSha256": digest(base.regular(path))})
            rounds.append(record)
        bundle = {"schemaVersion": "zoop-briefing-round-simulation-v2", "mode": MODE, "runId": run_id,
                  "sourceFileSha256": source["sourceFileSha256"], "clockFileSha256": source["clockFileSha256"],
                  "authorization": authorization, "retrospectiveBodies": True, "operationalCollectionGate": False,
                  "graphVersion": None, "rounds": rounds, "receipts": client.receipts(),
                  "marketSummary": {"status": "unavailable", "reason": "No market-summary producer for this simulation."},
                  "marketVariables": {"status": "unavailable", "reason": "Historical market indicators were not collected."},
                  "sinceMorning": {"status": "unavailable", "reason": "No real price or forecast evaluation data; previous is simulated output only."}}
        base.save_json(output / "bundle-v2.json", bundle)
        return {**plan, "status": "COMPLETE_WITH_HELD" if any(row["selectionStatus"] != "SELECTED" for row in rounds) else "COMPLETE",
                "newPaidCalls": len(client.new_calls), "selectedRounds": sum(row["selectionStatus"] == "SELECTED" for row in rounds),
                "heldSourceCoverageRounds": sum(row["selectionStatus"] == "HELD_SOURCE_COVERAGE" for row in rounds),
                "heldValidationRounds": sum(row["selectionStatus"] == "HELD_VALIDATION" for row in rounds),
                "bundlePath": str(output / "bundle-v2.json")}
    finally:
        if client is not None:
            accounting = canonical(client.receipts())
            base.write_once(output / ("accounting-" + digest(accounting) + ".json"), accounting)
        lock.unlink(missing_ok=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--sources", required=True)
    result.add_argument("--clocks", required=True)
    result.add_argument("--clock-html-root")
    result.add_argument("--output", required=True)
    result.add_argument("--user-inbox-ref", required=True)
    result.add_argument("--key-file")
    result.add_argument("--execute-authorized-simulation", action="store_true")
    result.add_argument("--batch-size", type=base.bounded(20, 30), default=30, metavar="20..30")
    result.add_argument("--workers", type=base.bounded(1, 3), default=3, metavar="1..3")
    result.add_argument("--max-repairs", type=int, default=1, choices=(0, 1))
    result.add_argument("--max-calls", type=base.bounded(1, 100), default=100, metavar="1..100")
    result.add_argument("--quality-policy", choices=("legacy-v1", QUALITY_V2), default=QUALITY_V2)
    return result


def main():
    try:
        summary = run(parser().parse_args())
        print(canonical(summary).decode())
        return 0
    except ReplayError as error:
        print(canonical({"status": "STOPPED", "reason": str(error)}).decode(), file=sys.stderr)
        return 2
    except Exception as error:
        print(canonical({"status": "STOPPED", "reason": "operator_error", "errorClass": type(error).__name__}).decode(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
