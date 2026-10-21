"""Bounded across-round editorial novelty check against server-owned PASS history.

This module does not fetch news, trust a model-supplied source, or establish factual
truth. The caller supplies only earlier published/PASS events and owns chronology.
"""

import copy
import hashlib
import json
import unicodedata
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "api/src/main/resources/briefing/prompts/round-simulation"
POLICY = "pass_history_event_novelty_v2"
LIMITATION = "Separate proposal and verification model passes against supplied evidence; not independent external fact or novelty verification."


class NoveltyError(ValueError):
    """Malformed or unbound novelty data must never silently admit candidates."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def event_key(row):
    return row.get("eventKey") or (row.get("assessment") or {}).get("eventKey") or ""


def build_quote_catalog(candidate, maximum_characters=1000):
    """Return exact, contiguous code-point spans without AI text copying.

    Injected catalogs are preferred. The fallback covers the complete source in
    deterministic bounded spans, so a translated/model-generated quote is impossible.
    """
    body, document = candidate.get("body"), candidate.get("documentId")
    if type(body) is not str or not body.strip() or type(document) is not str or not document:
        raise NoveltyError("novelty_candidate_body_or_identity_missing")
    body_sha = digest(body.encode())
    if candidate.get("bodySha256") not in (None, body_sha):
        raise NoveltyError("novelty_candidate_body_digest_mismatch")
    injected = candidate.get("quoteCatalog")
    if injected is not None:
        if type(injected) is not list or not injected:
            raise NoveltyError("novelty_quote_catalog_missing")
        catalog = copy.deepcopy(injected)
    else:
        catalog = []
        for start in range(0, len(body), maximum_characters):
            end = min(start + maximum_characters, len(body))
            catalog.append({"quoteId": "quote-" + digest(canonical([document, body_sha, start, end]))[:24],
                            "documentId": document, "start": start, "end": end, "text": body[start:end]})
    seen = set()
    for quote in catalog:
        if type(quote) is not dict or type(quote.get("quoteId")) is not str or not quote["quoteId"] \
                or quote["quoteId"] in seen or quote.get("documentId") != document \
                or type(quote.get("start")) is not int or type(quote.get("end")) is not int \
                or not 0 <= quote["start"] < quote["end"] <= len(body) \
                or quote.get("text") != body[quote["start"]:quote["end"]]:
            raise NoveltyError("novelty_quote_catalog_binding_mismatch")
        seen.add(quote["quoteId"])
    return catalog


def _old_quotes(event):
    return [source["quote"] for source in event.get("sources", [])
            if type(source) is dict and type(source.get("quote")) is str]


def _history(history):
    if type(history) is not list:
        raise NoveltyError("novelty_history_not_list")
    by_id = {}
    for event in history:
        if type(event) is not dict or type(event.get("issueId")) is not str or not event["issueId"] \
                or event["issueId"] in by_id or type(event.get("roundId")) is not str \
                or not event["roundId"] or type(event.get("sources")) is not list or not event["sources"]:
            raise NoveltyError("novelty_history_identity_or_sources_invalid")
        for source in event["sources"]:
            if type(source) is not dict or type(source.get("documentId")) is not str \
                    or type(source.get("quote")) is not str or not source["quote"].strip() \
                    or type(source.get("bodySha256")) is not str or len(source["bodySha256"]) != 64:
                raise NoveltyError("novelty_history_source_binding_missing")
        by_id[event["issueId"]] = event
    return by_id


def _schema(candidates, history_ids):
    schema = json.loads((PROMPTS / "novelty.schema.json").read_text(encoding="utf-8"))
    original = schema["properties"]["decisions"]["items"]
    properties = {}
    for candidate in candidates:
        item = copy.deepcopy(original)
        item["properties"]["documentId"]["enum"] = [candidate["documentId"]]
        item["properties"]["matchedIssueId"]["enum"] = [None, *sorted(history_ids)]
        item["properties"]["quoteIds"]["items"]["enum"] = [q["quoteId"] for q in candidate["quoteCatalog"]]
        properties[candidate["documentId"]] = item
    schema["properties"]["decisions"] = {"type": "object", "properties": properties,
                                          "required": list(properties), "additionalProperties": False}
    return schema


def _validate_decision(decision, candidate, by_id):
    required = {"documentId", "decision", "matchedIssueId", "reason", "delta", "quoteIds"}
    if type(decision) is not dict or set(decision) != required \
            or decision["documentId"] != candidate["documentId"] \
            or type(decision["decision"]) is not str \
            or decision["decision"] not in {"NEW_EVENT", "MATERIAL_UPDATE", "REPEAT", "UNCERTAIN"} \
            or type(decision["reason"]) is not str or not 1 <= len(decision["reason"].strip()) <= 500 \
            or type(decision["delta"]) is not str or len(decision["delta"]) > 700 \
            or type(decision["quoteIds"]) is not list or len(decision["quoteIds"]) > 8 \
            or any(type(q) is not str for q in decision["quoteIds"]) \
            or len(set(decision["quoteIds"])) != len(decision["quoteIds"]):
        raise NoveltyError("novelty_decision_structure_invalid")
    match = decision["matchedIssueId"]
    if match is not None and (type(match) is not str or match not in by_id):
        raise NoveltyError("novelty_matched_issue_not_in_history")
    catalog = {q["quoteId"]: q for q in candidate["quoteCatalog"]}
    if not set(decision["quoteIds"]).issubset(catalog):
        raise NoveltyError("novelty_quote_not_in_candidate_catalog")
    status = decision["decision"]
    if status == "NEW_EVENT":
        if match is not None or not decision["quoteIds"]:
            raise NoveltyError("novelty_new_event_evidence_invalid")
        key = normalized(event_key(candidate))
        if key and any(key == normalized(event_key(old)) for old in by_id.values()):
            raise NoveltyError("novelty_old_event_requires_material_delta")
    elif status == "MATERIAL_UPDATE":
        if match is None or not decision["delta"].strip() or not decision["quoteIds"]:
            raise NoveltyError("novelty_update_delta_or_match_missing")
        prior_quotes = [normalized(q) for q in _old_quotes(by_id[match])]
        current_quotes = [normalized(catalog[q]["text"]) for q in decision["quoteIds"]]
        if not any(q and all(q not in old for old in prior_quotes) for q in current_quotes):
            raise NoveltyError("novelty_update_reuses_prior_quote")
    elif status == "REPEAT" and match is None:
        raise NoveltyError("novelty_repeat_requires_matched_issue")


def filter_candidates(client, candidates, history, context):
    """Keep distinct events/material updates; reject repeats and uncertainty.

    The raw model decisions, full history digest and input digest are returned for
    immutable caller-side recording. Errors raise rather than bypass the gate.
    """
    if type(candidates) is not list or len(candidates) > 30 or type(context) is not dict \
            or type(context.get("contextSha256")) is not str or not context["contextSha256"]:
        raise NoveltyError("novelty_context_or_candidates_invalid")
    by_id = _history(history)
    documents, seen = [], set()
    for candidate in candidates:
        if type(candidate) is not dict:
            raise NoveltyError("novelty_candidate_not_object")
        document = candidate.get("documentId")
        if type(document) is not str or not document or document in seen:
            raise NoveltyError("novelty_candidate_identity_invalid")
        seen.add(document)
        value = copy.deepcopy(candidate)
        value["quoteCatalog"] = build_quote_catalog(candidate)
        value["bodySha256"] = digest(candidate["body"].encode())
        documents.append(value)
    audit = {"policy": POLICY, "contextSha256": context["contextSha256"],
             "historySha256": digest(canonical(history)), "candidateInputSha256": digest(canonical(documents)),
             "historyIssueIds": list(by_id), "decisions": [], "rawModelResponse": None,
             "meaning": LIMITATION, "modelCalled": False, "verificationCalled": False, "rawVerificationResponse": None}
    decisions, pending = {}, []
    for candidate in documents:
        match = next((old for old in history if any(source["bodySha256"] == candidate["bodySha256"]
                                                     for source in old["sources"])), None)
        if match:
            decisions[candidate["documentId"]] = {"documentId": candidate["documentId"], "decision": "REPEAT",
                "matchedIssueId": match["issueId"], "reason": "Exact body SHA-256 already appeared in published PASS history.",
                "delta": "", "quoteIds": [], "method": "deterministic_body_digest"}
        elif not history:
            decisions[candidate["documentId"]] = {"documentId": candidate["documentId"], "decision": "NEW_EVENT",
                "matchedIssueId": None, "reason": "No previous published PASS event in caller-owned history.",
                "delta": "", "quoteIds": [], "method": "no_history_no_model"}
        else:
            pending.append(candidate)
    if pending:
        data = {**context, "documents": pending, "noveltyHistory": history,
                "noveltyHistorySha256": audit["historySha256"], "noveltyCandidateInputSha256": audit["candidateInputSha256"],
                "noveltyPolicy": POLICY, "noveltyAssessmentMeaning": LIMITATION}
        reply = client.call("round_simulation_novelty", data, "novelty.md", "novelty.schema.json",
                            max_output=8000, schema_override=_schema(pending, by_id))
        audit["modelCalled"], audit["rawModelResponse"] = True, copy.deepcopy(reply)
        if type(reply) is not dict or set(reply) != {"decisions"} or type(reply["decisions"]) is not dict \
                or set(reply["decisions"]) != {d["documentId"] for d in pending}:
            raise NoveltyError("novelty_document_coverage_mismatch")
        for candidate in pending:
            _validate_decision(reply["decisions"][candidate["documentId"]], candidate, by_id)
        verification_data = {**data, "priorNoveltyDecisions": copy.deepcopy(reply),
            "priorNoveltyDecisionsSha256": digest(canonical(reply)),
            "priorNoveltyDecisionsMeaning": "Untrusted proposal. Re-evaluate every candidate from source evidence; correct false matches.",
            "noveltyVerificationPolicy": "principal_event_object_action_time_v1"}
        verified = client.call("round_simulation_novelty_verification", verification_data,
                              "novelty-verification.md", "novelty.schema.json", max_output=8000,
                              schema_override=_schema(pending, by_id))
        audit["verificationCalled"], audit["rawVerificationResponse"] = True, copy.deepcopy(verified)
        if type(verified) is not dict or set(verified) != {"decisions"} or type(verified["decisions"]) is not dict \
                or set(verified["decisions"]) != {d["documentId"] for d in pending}:
            raise NoveltyError("novelty_verification_document_coverage_mismatch")
        for candidate in pending:
            decision = verified["decisions"][candidate["documentId"]]
            _validate_decision(decision, candidate, by_id)
            decisions[candidate["documentId"]] = {**decision, "method": "model_evidence_comparison"}
    audit["decisions"] = [decisions[d["documentId"]] for d in documents]
    allowed = {d["documentId"] for d in audit["decisions"] if d["decision"] in {"NEW_EVENT", "MATERIAL_UPDATE"}}
    audit["keptDocumentIds"] = [d["documentId"] for d in documents if d["documentId"] in allowed]
    audit["excludedDocumentIds"] = [d["documentId"] for d in documents if d["documentId"] not in allowed]
    return [d for d in documents if d["documentId"] in allowed], audit
