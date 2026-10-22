"""Server-owned literal quotes and past published-event history for simulation quality v2."""

import hashlib
import json


class QualityError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def quote_catalog(candidate):
    body, document = candidate["body"], candidate["documentId"]
    sha = hashlib.sha256(body.encode()).hexdigest()
    if candidate.get("bodySha256", sha) != sha:
        raise QualityError("quote_catalog_body_digest_mismatch")
    spans, start = [], 0
    while start < len(body):
        end = min(start + 1200, len(body))
        if end < len(body):
            boundary = body.rfind("\n", start + 600, end)
            if boundary > start:
                end = boundary + 1
        if len(body) - end < 20:
            end = len(body)
        if end - start >= 20:
            key = hashlib.sha256(canonical([document, sha, start, end])).hexdigest()[:28]
            spans.append({"quoteId": "quote-" + key, "documentId": document,
                          "bodySha256": sha, "start": start, "end": end, "text": body[start:end]})
        start = end
    return spans


def catalog_candidates(candidates):
    return [{**row, "quoteCatalog": quote_catalog(row)} for row in candidates]


def restore_selection(reply, candidates):
    for row in candidates:
        if row["quoteCatalog"] != quote_catalog(row):
            raise QualityError("quote_catalog_not_server_owned")
    by_document = {row["documentId"]: {q["quoteId"]: q for q in row["quoteCatalog"]} for row in candidates}
    result = json.loads(canonical(reply))
    for choice in result["selected"]:
        for source in choice["sources"]:
            document, ids = source["documentId"], source.pop("quoteIds")
            if document not in by_document or not ids or len(ids) != len(set(ids)):
                raise QualityError("invalid_quote_catalog_membership")
            if any(key not in by_document[document] for key in ids):
                raise QualityError("quote_id_does_not_belong_to_document")
            source["quotes"] = [by_document[document][key]["text"] for key in ids]
    return result


def published_history(rounds, cutoff):
    """Novelty memory is not the immediately previous outlook or proof of a source fact."""
    from datetime import datetime
    def stamp(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise QualityError("novelty_history_timestamp_naive")
        return parsed
    out = []
    for row in rounds:
        if stamp(row["window"]["to"]) > stamp(cutoff):
            raise QualityError("future_round_in_novelty_history")
        result = row.get("result") or {}
        if row.get("selectionStatus") != "SELECTED" or result.get("verification", {}).get("status") != "PASS":
            continue
        if hashlib.sha256(canonical(result)).hexdigest() != row.get("resultSha256"):
            raise QualityError("novelty_history_result_digest_mismatch")
        for selected in row["selected"]:
            generated = next((item for item in result["items"] if item["issueId"] == selected["issueId"]), None)
            if generated is None:
                raise QualityError("novelty_history_item_missing")
            out.append({"roundId": row["roundId"], "issueId": selected["issueId"],
                        "eventKey": selected.get("eventKey", ""), "title": generated["title"],
                        "companyNames": selected["companyNames"],
                        "claims": generated["claims"],
                        "sources": [{key: value for key, value in source.items()
                                     if key in {"documentId", "bodySha256", "quote", "evidenceId", "url"}}
                                    for source in selected["sources"]]})
    return out
