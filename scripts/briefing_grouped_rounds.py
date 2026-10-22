#!/usr/bin/env python3
"""Reuse accepted issue groups for bounded, as-of briefing selection.

The archive remains a development snapshot: clustering and an accepted quote do
not grant operating publication rights or prove contemporary collection. No model
call occurs while building candidates or freezing a selection.
"""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("_grouped_round_simulation", Path(__file__).with_name("briefing_round_simulation.py"))
sim = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sim)
base, ReplayError = sim.base, sim.ReplayError
PROMPTS = Path(__file__).resolve().parents[1] / "api/src/main/resources/briefing/prompts/grouped-issues"
SELECTION_STAGE = "grouped_issue_selection"
# Official model documentation checked 2026-10-20; account-specific service
# availability is still determined by the recorded provider response.
MODEL_MAX_OUTPUT_TOKENS = 128000
MODEL_OUTPUT_LIMIT_SOURCE = "https://developers.openai.com/api/docs/models/gpt-6-luna"
# Only known completed output mistakes may receive one bounded correction. Input
# identity, source/clock integrity, provider failures and unknown usage never do.
CORRECTABLE_SELECTION_ERRORS = frozenset({
    "grouped_duplicate_selected_issue", "grouped_selected_issue_not_eligible",
    "importance_three_impact_proof_missing", "grouped_unknown_or_duplicate_citation",
    "grouped_selected_evidence_outside_current_round", "grouped_update_delta_not_current_round_evidence",
    "grouped_repeat_issue_without_supported_material_update", "grouped_material_update_without_delta",
    "grouped_unknown_or_duplicate_company", "grouped_company_without_selected_evidence",
    "one_source_cannot_create_multiple_headline_issues",
})


def require(condition, code):
    if not condition:
        raise ReplayError(code)


def copied(value):
    return base.strict_load(base.canonical(value))


def _identity(value):
    return type(value) is str and bool(value.strip())


def _indexed(values, key, code):
    result = {}
    require(type(values) is list, code)
    for value in values:
        require(type(value) is dict and _identity(value.get(key)) and value[key] not in result, code)
        result[value[key]] = value
    return result


def _document(document, mention):
    body = document.get("body")
    require(type(body) is str and base.digest(body.encode()) == document.get("bodySha256"), "grouped_document_body_digest_mismatch")
    require(mention.get("articleVersion") == document.get("documentVersion")
            and mention.get("bodySha256") == document.get("bodySha256"), "grouped_mention_document_version_mismatch")
    clock = document.get("clockRecord")
    require(type(clock) is dict and clock.get("status") == "verified_timestamp"
            and clock.get("documentId") == document["documentId"]
            and clock.get("bodySha256") == document["bodySha256"]
            and base.digest(base.canonical(clock)) == document.get("clockRecordSha256")
            and sim.aware(clock.get("publishedAt")) == sim.aware(mention["publishedAt"]), "grouped_mention_publication_clock_mismatch")
    require(type(document.get("dateContext")) is dict
            and sim.aware(document["dateContext"].get("publishedAt")) == sim.aware(mention["publishedAt"]),
            "grouped_document_date_context_mismatch")


def _evidence(value, document):
    require(type(value) is dict and _identity(value.get("evidenceId")), "grouped_evidence_identity_missing")
    start, end, quote = value.get("start"), value.get("end"), value.get("quote")
    require(value.get("articleId") == document["documentId"]
            and value.get("articleVersion") == document["documentVersion"], "grouped_evidence_document_version_mismatch")
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(document["body"])
            and type(quote) is str and bool(quote.strip()) and document["body"][start:end] == quote,
            "grouped_evidence_not_exact_original_span")
    require(value.get("offsetUnit", "unicode_code_point") == "unicode_code_point", "grouped_evidence_offset_unit_mismatch")
    return {"evidenceId": value["evidenceId"], "documentId": document["documentId"],
            "documentVersion": document["documentVersion"], "bodySha256": document["bodySha256"],
            "url": document.get("url"), "quote": quote, "start": start, "end": end,
            "offsetUnit": "unicode_code_point", "sourceMetadata": base.source_metadata(document),
            "dateContext": copied(document["dateContext"]), "publicationClock": copied(document["clockRecord"]),
            "clockRecordSha256": document["clockRecordSha256"]}


def build_grouped_candidates(archive, spec, identity_holds=None):
    """Return issues with a new (from,to] mention and only cutoff-available facts.

    A group's eventual title is deliberately ignored: a later article may have
    changed it. Each title, company link and background mention is rebuilt from
    documents published by this round's cutoff. The archive digest is provenance,
    never evidence that its future contents were available in the old round.
    """
    require(archive.get("schemaVersion") == "zoop-grouped-issues-v1", "grouped_archive_schema_invalid")
    company_policy = archive.get("identity", {}).get("companyProjectionVersion")
    require(company_policy in (None, "canonical-evidence-v1"), "grouped_company_projection_policy_unknown")
    documents = _indexed(archive.get("documents"), "documentId", "grouped_duplicate_or_invalid_document")
    issues = _indexed(archive.get("issues"), "issueId", "grouped_duplicate_or_invalid_issue")
    start, end = sim.aware(spec["window"]["from"]), sim.aware(spec["window"]["to"])
    require(start < end and spec["window"].get("openStart") is False, "grouped_round_window_invalid")
    result, seen_mentions, evidence_bindings = [], set(), {}
    for issue_id, issue in sorted(issues.items()):
        mentions = _indexed(issue.get("mentions"), "mentionId", "grouped_duplicate_or_invalid_mention")
        available, identity_held_mentions = [], []
        for mention_id, mention in sorted(mentions.items()):
            published = sim.aware(mention.get("publishedAt"))
            if published > end:
                continue
            projection = mention.get("companyProjection")
            if company_policy is not None:
                require(type(projection) is dict and projection.get("policy") == company_policy
                        and type(projection.get("briefingEligible")) is bool
                        and type(projection.get("audit")) is list,
                        "grouped_company_projection_missing_or_invalid")
                if not projection["briefingEligible"]:
                    identity_held_mentions.append(mention_id)
            else:
                require(projection is None, "grouped_company_projection_policy_missing")
            require(mention_id not in seen_mentions, "grouped_mention_in_multiple_issues")
            seen_mentions.add(mention_id)
            document = documents.get(mention.get("articleId"))
            require(document is not None, "grouped_mention_document_missing")
            _document(document, mention)
            evidence = {}
            companies = []
            for value in mention.get("evidence", []):
                citation = _evidence(value, document)
                require(citation["evidenceId"] not in evidence, "grouped_duplicate_mention_evidence")
                evidence[citation["evidenceId"]] = citation
            for company in mention.get("companies", []):
                require(type(company) is dict and _identity(company.get("companyId"))
                        and _identity(company.get("name")), "grouped_company_identity_missing")
                refs = []
                for value in company.get("evidence", []):
                    citation = _evidence(value, document)
                    if citation["evidenceId"] in evidence:
                        require(evidence[citation["evidenceId"]] == citation, "grouped_evidence_id_binding_conflict")
                    evidence[citation["evidenceId"]] = citation
                    refs.append(citation["evidenceId"])
                require(refs and len(set(refs)) == len(refs), "grouped_company_evidence_missing_or_duplicate")
                companies.append({"companyId": company["companyId"], "name": company["name"],
                                  "role": company.get("role"), "evidenceIds": refs})
            require(evidence, "grouped_mention_evidence_missing")
            for key, citation in evidence.items():
                if key in evidence_bindings:
                    require(evidence_bindings[key] == citation, "grouped_evidence_id_binding_conflict")
                evidence_bindings[key] = citation
            available.append({"mentionId": mention_id, "articleId": document["documentId"],
                "articleVersion": document["documentVersion"], "publishedAt": mention["publishedAt"],
                "bodySha256": document["bodySha256"], "title": mention.get("title") or document.get("title") or "",
                "action": mention.get("action"), "target": mention.get("target"), "eventTime": mention.get("eventTime"),
                "keywords": copied(mention.get("keywords", [])), "companies": companies,
                "evidence": list(evidence.values()), "newInRound": published > start})
        available.sort(key=lambda value: (sim.aware(value["publishedAt"]), value["mentionId"]))
        new = [value for value in available if value["newInRound"]]
        if not new:
            continue
        if identity_held_mentions:
            # The original model grouping may have used an unverified entity ID.
            # Retain that proposal in the archive but do not publish its whole
            # as-of group. A future uncertain member cannot suppress an old round.
            if identity_holds is not None:
                identity_holds.append({"issueId": issue_id, "mentionIds": identity_held_mentions,
                                       "reason": "unverified_company_link_in_asof_group"})
            continue
        value = {"issueId": issue_id, "title": available[0]["title"],
                 "newMentions": new, "backgroundMentions": [m for m in available if not m["newInRound"]],
                 "newEvidenceIds": sorted({e["evidenceId"] for m in new for e in m["evidence"]}),
                 "asOfEvidenceIds": sorted({e["evidenceId"] for m in available for e in m["evidence"]}),
                 "window": copied(spec["window"]), "sourceFileSha256": archive.get("sourceFileSha256"),
                 "historicalSimulation": not bool(spec.get("localCollection")), "operationalCollectionGate": False,
                 "historicalBodyUnchangedProven": False}
        value["asOfSnapshotSha256"] = base.digest(base.canonical(value))
        result.append(value)
    return result


def selection_schema(candidates, publication_company_ids=None):
    value = base.strict_load(base.regular(PROMPTS / "selection.schema.json"))
    template = value["properties"]["assessments"]["additionalProperties"]
    ids = sorted(c["issueId"] for c in candidates)
    value["properties"]["assessments"] = {"type": "object", "properties": {key: copied(template) for key in ids},
        "required": ids, "additionalProperties": False}
    selected_ids = ids
    if publication_company_ids is not None:
        registered = set(publication_company_ids)
        selected_ids = [c["issueId"] for c in candidates if
            (linked := {co["companyId"] for m in c["newMentions"] + c["backgroundMentions"] for co in m["companies"]})
            and linked <= registered]
        value["properties"]["selected"]["items"]["properties"]["companyIds"]["items"]["enum"] = sorted(registered)
    value["properties"]["selected"]["items"]["properties"]["issueId"]["enum"] = selected_ids or ["__no_candidate__"]
    return value


def selection_output_plan(candidates):
    """Deterministic allowance for exhaustive assessments, not a model limit.

    Prior same-model Korean assessment JSON used 0.4206-0.4908 visible tokens
    per character. The half-character estimate below, 4K reasoning allowance
    and 20% margin are planning heuristics, not an exact tokenizer or a proof
    that arbitrarily verbose schema-valid output fits. Actual provider/model
    output limit below is the documented model limit, not an account guarantee.
    """
    ids = sorted(_indexed(candidates, "issueId", "grouped_duplicate_candidate"))
    minimum = {"importance": 0, "priority": 0, "status": "HOLD", "reason": "a",
               "scope": "COMPANY", "affectedSectors": [], "transmission": ""}
    minimum_raw = base.canonical({"assessments": {key: minimum for key in ids}, "selected": []})
    minimum_characters = len(minimum_raw.decode("utf-8"))
    # Same seven fields in prior real responses had a median of 221 characters
    # per assessment before its ID/key. Add 96 characters above the structural
    # minimum per issue, plus 4K characters for up to three supported selections.
    realistic_characters = minimum_characters + 96 * len(ids) + 4096
    visible_tokens = (realistic_characters + 1) // 2
    reasoning_reserve = 4096
    with_margin = ((visible_tokens + reasoning_reserve) * 6 + 4) // 5
    cap = max(12000, ((with_margin + 1023) // 1024) * 1024)
    require(cap <= MODEL_MAX_OUTPUT_TOKENS, "grouped_selection_output_plan_exceeds_provider_limit")
    return {"policy": "exhaustive_grouped_assessment_output_v1", "candidateCount": len(ids),
            "minimumJsonCharacters": minimum_characters, "minimumJsonBytes": len(minimum_raw),
            "realisticJsonCharacters": realistic_characters, "estimatedVisibleTokens": visible_tokens,
            "reasoningTokenReserve": reasoning_reserve, "headroomPercent": 20,
            "maxOutputTokens": cap, "providerOutputLimitVerified": True,
            "providerMaxOutputTokens": MODEL_MAX_OUTPUT_TOKENS,
            "providerOutputLimitSource": MODEL_OUTPUT_LIMIT_SOURCE,
            "providerOutputLimitCheckedOn": "2026-10-20"}


def selection_output_cap(candidates):
    return selection_output_plan(candidates)["maxOutputTokens"]


def _catalog(candidate):
    evidence, companies = {}, {}
    for mention in candidate["backgroundMentions"] + candidate["newMentions"]:
        evidence.update({value["evidenceId"]: value for value in mention["evidence"]})
        for company in mention["companies"]:
            key = company["companyId"]
            if key not in companies:
                companies[key] = {**company, "evidenceIds": []}
            require(companies[key]["name"] == company["name"], "grouped_company_name_binding_conflict")
            companies[key]["evidenceIds"] = sorted(set(companies[key]["evidenceIds"]) | set(company["evidenceIds"]))
    return evidence, companies


def _prior_by_id(previous_selected):
    result = {}
    for previous in previous_selected:
        require(type(previous) is dict and _identity(previous.get("issueId")), "grouped_previous_issue_invalid")
        result.setdefault(previous["issueId"], []).append(previous)
    return result


def _frozen_candidate_inputs(candidates, previous_selected):
    allowed = _indexed(candidates, "issueId", "grouped_duplicate_candidate")
    previous = _prior_by_id(previous_selected)
    for candidate in candidates:
        snapshot = {key: value for key, value in candidate.items() if key != "asOfSnapshotSha256"}
        require(base.digest(base.canonical(snapshot)) == candidate.get("asOfSnapshotSha256"),
                "grouped_candidate_changed_after_input_freeze")
        for rows in previous.values():
            for row in rows:
                for source in row.get("sources", []):
                    published = source.get("publicationClock", {}).get("publishedAt") \
                        or source.get("dateContext", {}).get("publishedAt")
                    require(published is not None and sim.aware(published) <= sim.aware(candidate["window"]["from"]),
                            "grouped_future_or_undated_previous_source")
        _catalog(candidate)
    return allowed, previous


def freeze_grouped_selection(reply, candidates, identity_sha, previous_selected=()):
    """Validate model decisions and keep stable group IDs for existing generation."""
    base.validate_schema(reply, selection_schema(candidates))
    allowed, previous = _frozen_candidate_inputs(candidates, previous_selected)
    selected, selected_ids, used_documents = [], set(), set()
    choices = sorted(reply["selected"], key=lambda c: (-reply["assessments"][c["issueId"]]["importance"],
        -reply["assessments"][c["issueId"]]["priority"], c["issueId"]))
    for choice in choices:
        issue_id = choice["issueId"]
        require(issue_id not in selected_ids, "grouped_duplicate_selected_issue")
        selected_ids.add(issue_id)
        candidate, assessment = allowed[issue_id], reply["assessments"][issue_id]
        require(assessment["status"] == "SELECTABLE" and assessment["importance"] >= 2,
                "grouped_selected_issue_not_eligible")
        if assessment["importance"] == 3:
            require(assessment["scope"] in {"COMMON_POLICY", "BROAD_MARKET"}
                    and bool(assessment["transmission"].strip())
                    and (assessment["scope"] != "BROAD_MARKET" or len(set(assessment["affectedSectors"])) >= 2),
                    "importance_three_impact_proof_missing")
        evidence, companies = _catalog(candidate)
        ids, delta = choice["evidenceIds"], choice["deltaEvidenceIds"]
        require(len(set(ids)) == len(ids) and set(ids).issubset(evidence), "grouped_unknown_or_duplicate_citation")
        require(set(ids).issubset(candidate["newEvidenceIds"]), "grouped_selected_evidence_outside_current_round")
        require(len(set(delta)) == len(delta) and set(delta).issubset(set(ids) & set(candidate["newEvidenceIds"])),
                "grouped_update_delta_not_current_round_evidence")
        if issue_id in previous:
            old_quotes = {s["quote"] for row in previous[issue_id] for s in row.get("sources", [])}
            old_ids = {s["evidenceId"] for row in previous[issue_id] for s in row.get("sources", [])}
            require(choice["novelty"] == "MATERIAL_UPDATE" and delta
                    and any(key not in old_ids and evidence[key]["quote"] not in old_quotes for key in delta),
                    "grouped_repeat_issue_without_supported_material_update")
        elif choice["novelty"] == "MATERIAL_UPDATE":
            require(delta, "grouped_material_update_without_delta")
        require(len(set(choice["companyIds"])) == len(choice["companyIds"])
                and set(choice["companyIds"]).issubset(companies), "grouped_unknown_or_duplicate_company")
        links = []
        for key in choice["companyIds"]:
            link = companies[key]
            cited = sorted(set(link["evidenceIds"]) & set(ids))
            require(cited, "grouped_company_without_selected_evidence")
            links.append({**link, "evidenceIds": cited})
        sources = [copied(evidence[key]) for key in ids]
        docs = {source["documentId"] for source in sources}
        require(not docs & used_documents, "one_source_cannot_create_multiple_headline_issues")
        used_documents |= docs
        snapshot = copied(candidate)
        selected.append({"issueId": issue_id, "rank": len(selected) + 1, "eventKey": issue_id,
            "title": choice["title"], "reason": assessment["reason"], "companyNames": [link["name"] for link in links],
            "companyLinks": links, "score": assessment["priority"], "importance": assessment["importance"],
            "scope": assessment["scope"], "affectedSectors": assessment["affectedSectors"],
            "transmission": assessment["transmission"], "limitations": choice["limitations"], "sources": sources,
            "selectionInputSha256": identity_sha, "quoteBindingPolicy": "accepted_grouped_issue_exact_span_v1",
            "groupingMeaning": "Reused accepted issue archive identity; not an operating graph/publication approval.",
            "groupedIssueSnapshotSha256": candidate["asOfSnapshotSha256"], "frozenGroupedIssueSnapshot": snapshot,
            "novelty": [{"decision": choice["novelty"], "deltaEvidenceIds": delta,
                         "meaning": "Model editorial judgment; exact quotes remain the only fact evidence."}]})
    return selected


class HeldPaidRequest(ReplayError):
    """Explicitly withhold a reservation already unresolved at process start."""
    def __init__(self, request_digest, stage):
        super().__init__("operator_held_unresolved_paid_request")
        self.request_digest = request_digest
        self.stage = stage


class GroupedSimulationClient(sim.SimulationClient):
    """Keep original stages/schemas and add grouping-aware prompt semantics."""
    def __init__(self, output, transport, max_calls=base.MAX_CALLS, authorized_truncations=(),
                 hold_unresolved_requests=False):
        super().__init__(output, transport, max_calls, authorized_truncations)
        # Snapshot once. A failure created later in this process must continue to
        # trigger the base client's global stop, never this disposition path.
        self.held_at_start = frozenset(path.name.removesuffix(".pending.json")
            for path in self.calls.glob("*.pending.json")
            if not (self.calls / (path.name.removesuffix(".pending.json") + ".complete.json")).exists()) \
            if hold_unresolved_requests else frozenset()

    def call(self, stage, data, prompt_name, schema_name, max_output=8000, schema_override=None):
        raw, _, _ = self.request(stage, data, prompt_name, schema_name, max_output, schema_override)
        key = base.digest(raw)
        if key in self.held_at_start and not self.stopped.is_set():
            try:
                reservation = base.strict_load(base.regular(self.calls / (key + ".pending.json")))
                require(reservation.get("requestDigest") == key and reservation.get("model") == base.MODEL
                        and reservation.get("stage") == stage
                        and base.digest(base.regular(self.calls / (key + ".request.json"))) == key,
                        "held_paid_reservation_identity_mismatch")
            except Exception:
                self.stopped.set()
                raise
            if not (self.calls / (key + ".complete.json")).exists():
                # Outside ResponsesClient.call: preserve the unknown reservation
                # and usage exactly while allowing unrelated later rounds.
                raise HeldPaidRequest(key, stage)
        return super().call(stage, data, prompt_name, schema_name, max_output, schema_override)

    def request(self, stage, data, prompt_name, schema_name, max_output=12000, schema_override=None):
        schema_root = sim.PROMPTS
        if stage == SELECTION_STAGE:
            require(prompt_name == "selection.md" and schema_name == "selection.schema.json", "grouped_selection_prompt_name_invalid")
            resource_name, schema_root = prompt_name, PROMPTS
        elif stage in {"round_simulation_" + edition + "_" + phase
                       for edition in ("morning", "evening") for phase in ("generation", "verification")}:
            edition = data.get("edition")
            phase = "verification" if stage.endswith("_verification") else "generation"
            require(edition in {"morning", "evening"} and stage == "round_simulation_" + edition + "_" + phase,
                    "grouped_generation_stage_edition_mismatch")
            resource_name = "verification.md" if phase == "verification" else "generation-" + edition + ".md"
            allowed_names = {resource_name} if phase == "verification" else {resource_name, "generation-v2-" + edition + ".md"}
            require(prompt_name in allowed_names and schema_name == phase + ".schema.json", "grouped_generation_prompt_name_invalid")
        else:
            return super().request(stage, data, prompt_name, schema_name, max_output, schema_override)
        identity = data.get("context", {})
        prompt_root = PROMPTS.with_name("local-collection") if identity.get("mode") == "local_collection_validation" else PROMPTS
        instructions = base.regular(prompt_root / resource_name).decode("utf-8")
        expected = identity.get("promptArtifacts", {}).get("grouped-" + resource_name)
        if stage == SELECTION_STAGE:
            expected = identity.get("groupedPromptSha256") or expected
        require(expected is None or expected == base.digest(instructions.encode()), "grouped_prompt_changed_after_input_freeze")
        output_schema = copied(schema_override) if schema_override is not None else base.strict_load(base.regular(schema_root / schema_name))
        schema_artifact = ("grouped-" if stage == SELECTION_STAGE else "") + schema_name
        expected_schema = identity.get("promptArtifacts", {}).get(schema_artifact)
        require(expected_schema is None or expected_schema == base.digest(base.regular(schema_root / schema_name)),
                "grouped_schema_changed_after_input_freeze")
        request = {"model": base.MODEL, "store": False, "max_output_tokens": max_output, "instructions": instructions,
            "input": base.canonical(data).decode("utf-8"), "reasoning": {"effort": "low"},
            "text": {"format": {"type": "json_schema", "name": stage, "strict": True, "schema": output_schema}}}
        raw = base.canonical(request)
        require(len(raw) <= 2 * 1024 * 1024, "grouped_request_size_exceeded")
        return raw, output_schema, base.digest(instructions.encode())


def grouped_selection_data(candidates, context, previous_selected=()):
    return {**context, "issues": candidates, "maximumIssues": 3,
            "previousSelectedIssues": [{key: row.get(key) for key in ("issueId", "title", "sources")}
                                       for row in previous_selected],
            "operationalCollectionGate": False, "historicalBodyUnchangedProven": False}


def attempt_grouped_selection(client, candidates, context, identity_sha, previous_selected=()):
    """Select, allowing one correction of a known completed output mistake.

    The return value exposes the actual final request digest, including a
    correction's digest. It never retries HTTP/unknown/incomplete calls and uses
    the same client's existing write-ahead call budget for both attempts.
    """
    if not candidates:
        return {"selected": [], "requestDigest": None, "corrections": [], "failure": None}
    # Reject a changed snapshot/history before spending anything. Use one frozen
    # copy for both attempts so another caller cannot alter the correction basis.
    candidates, context, previous_selected = copied(candidates), copied(context), copied(list(previous_selected))
    _frozen_candidate_inputs(candidates, previous_selected)
    data, output_schema = grouped_selection_data(candidates, context, previous_selected), selection_schema(candidates, context.get("context", {}).get("publicationCompanyIds"))
    max_output = selection_output_cap(candidates)
    request_digest = client.request_digest(SELECTION_STAGE, data, "selection.md", "selection.schema.json",
                                           max_output=max_output, schema_override=output_schema)
    reply = client.call(SELECTION_STAGE, data, "selection.md", "selection.schema.json", max_output=max_output,
                        schema_override=output_schema)
    try:
        base.validate_schema(reply, output_schema)
        selected = freeze_grouped_selection(reply, candidates, identity_sha, previous_selected)
        return {"selected": selected, "requestDigest": request_digest, "corrections": [], "failure": None}
    except ReplayError as error:
        failure = str(error)
        if failure not in CORRECTABLE_SELECTION_ERRORS or client.stopped.is_set():
            raise
    # A parsed reply alone is insufficient: inspect the immutable original paid
    # receipt/response before authorizing any different request.
    receipt, response = client.inspect_recorded(request_digest)
    require(receipt.get("status") == "completed" and response.get("status") == "completed"
            and receipt.get("stage") == SELECTION_STAGE, "grouped_correction_requires_known_completed_response")
    correction = {"attempt": 1, "failure": failure, "previousReply": reply,
        "originalRequestDigest": request_digest, "originalResponseSha256": receipt["responseSha256"],
        "sameFrozenInputs": True,
        "instruction": "Correct the known output mistake once under the unchanged selection criteria. "
            "Use only the same frozen issues and evidence, company links, clock window and prior history. "
            "The previous reply and failure are repair hints, never fact evidence or approval. "
            "Recheck every selected issue, keep maximum three, and omit unsupported issues rather than invent facts."}
    corrected_data = {**data, "selectionCorrection": correction}
    corrected_digest = client.request_digest(SELECTION_STAGE, corrected_data, "selection.md", "selection.schema.json",
                                             max_output=max_output, schema_override=output_schema)
    corrected_reply = client.call(SELECTION_STAGE, corrected_data, "selection.md", "selection.schema.json",
                                  max_output=max_output, schema_override=output_schema)
    audit = {"attempt": 1, "reason": failure, "originalRequestDigest": request_digest,
             "originalResponseSha256": receipt["responseSha256"], "correctedRequestDigest": corrected_digest,
             "sameFrozenInputs": True, "status": "PASS"}
    try:
        base.validate_schema(corrected_reply, output_schema)
        selected = freeze_grouped_selection(corrected_reply, candidates, identity_sha, previous_selected)
        return {"selected": selected, "requestDigest": corrected_digest, "corrections": [audit], "failure": None}
    except ReplayError as error:
        if str(error) not in CORRECTABLE_SELECTION_ERRORS or client.stopped.is_set():
            raise
        audit.update(status="WITHHELD", validationError=str(error))
        return {"selected": [], "requestDigest": corrected_digest, "corrections": [audit], "failure": str(error)}


def choose_grouped_round(client, candidates, context, identity_sha, previous_selected=()):
    """Compatibility list API; use attempt_grouped_selection for request audit."""
    outcome = attempt_grouped_selection(client, candidates, context, identity_sha, previous_selected)
    require(outcome["failure"] is None, outcome["failure"])
    return outcome["selected"]
