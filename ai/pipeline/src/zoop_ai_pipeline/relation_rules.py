"""Pure S3 rules: normalization, deterministic prechecks, verifier requests and fail-closed gate decisions.

No I/O. Exact quote/locator resolution is injected (`View.cite`). A relation reaches `eligible` only when every deterministic check
passes AND an independent verifier supports every claim; direction, confidence and admin input are never a substitute.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from .country_context import VERSION as COUNTRY_CONTEXT_VERSION
from .country_context import CountryContext
from .relation_contracts import (CANDIDATE_VERSION, IMPACT_POLICY, IMPACT_PRODUCER, IMPACT_REQUEST, IMPACT_VERIFIER, IMPACT_VERIFY_REQUEST,
    INDIRECT_TYPES, MAX_PATH, NON_PROOF, TYPES, VERIFIER, VERIFY_REQUEST, CitationFailure, ImpactResponse, ImpactVerifierResponse, RelationResponse, ReplyInvalid,
    VerifierResponse, digest)


@dataclass
class View:
    """Frozen upstream facts the rules may consult. Everything here comes from the owner seam, never from caller JSON."""
    companies: dict[str, list[str]]  # companyId -> display names
    events: dict[str, dict]          # ref -> {"origin", "names", "docs": {(documentId, documentVersion)}}
    topics: dict[str, dict]          # ref -> {"names", "docs"}
    countries: CountryContext      # canonical codes plus verbatim/unresolved S2 geography
    cite: Callable[[dict], dict]     # camelCase citation -> exact resolved citation; raises CitationFailure

    def names(self, endpoint: dict) -> list[str]:
        table = {"company": self.companies, "event": self.events, "topic": self.topics}[endpoint["kind"]]
        found = table.get(endpoint["ref"])
        if found is None:
            return []
        return found if isinstance(found, list) else found["names"]


def parse(model: type[BaseModel], raw: Any, code: str):
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ReplyInvalid(code) from exc


def parse_relations(raw: Any) -> RelationResponse:
    return parse(RelationResponse, raw, "relation_reply_invalid")


def parse_impacts(raw: Any) -> ImpactResponse:
    return parse(ImpactResponse, raw, "impact_reply_invalid")


# ---------------------------------------------------------------- normalization -----------------------------------------

def direction(relation_type: str) -> str | None:
    return TYPES[relation_type][2] if relation_type in TYPES else None


def _order(a: dict, b: dict, symmetric: bool) -> list[dict]:
    return sorted([a, b], key=lambda e: (e["kind"], e["ref"])) if symmetric else [a, b]


def _ep(e: dict) -> dict:
    return {"kind": e["kind"], "ref": e["ref"]}


def _citation_key(c: dict) -> tuple:
    return (c["documentId"], c["documentVersion"], c["start"], c["end"], c["quote"])


def _union(*groups: list[dict]) -> list[dict]:
    seen, result = set(), []
    for group in groups:
        for c in group:
            if _citation_key(c) not in seen:
                seen.add(_citation_key(c))
                result.append({k: c[k] for k in ("documentId", "documentVersion", "start", "end", "quote")})
    return result


def normalize(p: dict) -> dict:
    """Canonical orientation: directed types keep subject->object as stated; symmetric types sort the pair. Scope/type/validity stay."""
    symmetric = direction(p["type"]) == "symmetric"
    subject, obj = _order(_ep(p["subject"]), _ep(p["object"]), symmetric)
    path = []
    for s in p["path"]:
        a, b = _order(_ep(s["subject"]), _ep(s["object"]), direction(s["type"]) == "symmetric")
        path.append({"type": s["type"], "subject": a, "object": b, "citations": _union(s["citations"])})
    return {"type": p["type"], "subject": subject, "object": obj, "reordered": (subject, obj) != (_ep(p["subject"]), _ep(p["object"])),
            "connection": p["connection"], "businessScope": p["businessScope"], "productScope": p["productScope"],
            "validity": {"from": p["validity"]["from"], "until": p["validity"]["until"], "citations": _union(p["validity"]["citations"])},
            "countries": sorted(set(p["countries"])), "reasons": [p["reason"]], "citations": _union(p["citations"]), "path": path, "proposalCount": 1}


def relation_key(n: dict) -> str:
    """Identity of the claimed relation, independent of upstream, wording and evidence. Type/scope/validity/path differences never merge."""
    return digest({"version": CANDIDATE_VERSION, "type": n["type"], "subject": n["subject"], "object": n["object"],
                   "businessScope": n["businessScope"], "productScope": n["productScope"],
                   "validity": {"from": n["validity"]["from"], "until": n["validity"]["until"]}, "connection": n["connection"],
                   "countries": n["countries"], "path": [{"type": s["type"], "subject": s["subject"], "object": s["object"]} for s in n["path"]]})


def merge(proposals: list[dict]) -> list[dict]:
    """Equal keys (e.g. a symmetric pair stated in both orders) become one candidate whose evidence is the union; nothing else merges."""
    merged: dict[str, dict] = {}
    for proposal in proposals:
        n = normalize(proposal)
        key = relation_key(n)
        if key not in merged:
            merged[key] = {**n, "relationKey": key}
            continue
        m = merged[key]
        m["proposalCount"] += 1
        m["reordered"] = m["reordered"] or n["reordered"]
        m["reasons"] += [r for r in n["reasons"] if r not in m["reasons"]]
        m["citations"] = _union(m["citations"], n["citations"])
        m["validity"]["citations"] = _union(m["validity"]["citations"], n["validity"]["citations"])
        for step, other in zip(m["path"], n["path"]):
            step["citations"] = _union(step["citations"], other["citations"])
    return sorted(merged.values(), key=lambda m: m["relationKey"])


# ---------------------------------------------------------------- deterministic precheck ---------------------------------

def _reason(code: str, at: str | None = None, detail: str | None = None) -> dict:
    return {"code": code, **({"at": at} if at else {}), **({"detail": detail} if detail else {})}


def evaluate(n: dict, view: View) -> dict:
    """Candidate payload with a deterministic precheck: pending (needs the independent verifier) | hold | reject."""
    holds: list[dict] = []
    rejects: list[dict] = []
    relation_type = n["type"]
    spec = TYPES.get(relation_type)
    if relation_type in NON_PROOF:
        holds.append(_reason("non_relationship_basis"))
    elif spec is None:
        holds.append(_reason("relation_type_unsupported"))

    def endpoint(e: dict, expected: str | None, at: str) -> bool:
        if expected is not None and e["kind"] != expected:
            rejects.append(_reason("endpoint_kind_invalid", at))
            return False
        known = {"company": view.companies, "event": view.events, "topic": view.topics}[e["kind"]]
        if e["ref"] in known:
            return True
        if e["kind"] == "topic" and e["ref"] in view.events:
            rejects.append(_reason("event_id_not_topic", at))
        else:
            holds.append(_reason("target_unknown", at))
        return False

    endpoint(n["subject"], spec[0] if spec else None, "subject")
    endpoint(n["object"], spec[1] if spec else None, "object")
    if n["subject"] == n["object"]:
        rejects.append(_reason("self_relation"))

    steps = n["path"]
    if n["connection"] == "direct":
        if steps:
            rejects.append(_reason("path_not_allowed_for_direct"))
        if not n["citations"]:
            holds.append(_reason("evidence_missing"))
    elif relation_type not in INDIRECT_TYPES:
        holds.append(_reason("indirect_unsupported_for_type"))
    else:
        if len(steps) < MAX_PATH:
            holds.append(_reason("path_incomplete"))
        elif len(steps) > MAX_PATH:
            holds.append(_reason("path_too_long"))
        for index, step in enumerate(steps, 1):
            at = f"step:{index}"
            if step["type"] != relation_type:
                holds.append(_reason("path_step_type_mismatch", at))
            for role in ("subject", "object"):
                if step[role]["kind"] != "company" or step[role]["ref"] not in view.companies:
                    holds.append(_reason("target_unknown", f"{at}:{role}"))
            if not step["citations"]:
                holds.append(_reason("path_step_uncited", at))
        chain = [steps[0]["subject"]] + [s["object"] for s in steps] if steps else []
        linked = all(a["object"] == b["subject"] for a, b in zip(steps, steps[1:]))
        if len(steps) == MAX_PATH and (chain[0] != n["subject"] or chain[-1] != n["object"] or not linked):
            holds.append(_reason("path_disconnected"))

    validity = n["validity"]
    if (validity["from"] or validity["until"]) and not validity["citations"]:
        holds.append(_reason("validity_uncited"))
    if validity["from"] and validity["until"] and validity["from"] > validity["until"]:
        rejects.append(_reason("validity_order_invalid"))

    declared, geography = n["countries"], view.countries
    known = geography.known
    market = "unknown" if not declared else "domestic" if declared == ["KR"] else "international"
    if not declared:
        country_check = "unknown"
    elif set(declared) <= known:
        country_check = "pass"
    elif not known or geography.unresolved:
        # Missing/ambiguous geography is not a proven mismatch. The independent context claim still needs cited support.
        country_check = "unverified"
    else:
        country_check = "conflict"
        holds.append(_reason("country_context_conflict"))

    target_docs = None
    for role in ("subject", "object"):
        e = n[role]
        if e["kind"] in ("event", "topic") and e["ref"] in (view.events if e["kind"] == "event" else view.topics):
            target_docs = (view.events if e["kind"] == "event" else view.topics)[e["ref"]]["docs"]

    def resolve(citations: list[dict], at: str, scoped: bool) -> list[dict]:
        out = []
        for index, c in enumerate(citations, 1):
            try:
                found = view.cite(c)
                if scoped and target_docs is not None and (c["documentId"], c["documentVersion"]) not in target_docs:
                    raise CitationFailure("citation_not_target_evidence")
                out.append(found)
            except CitationFailure as exc:
                rejects.append(_reason("citation_invalid", f"{at}:{index}", exc.code))
                out.append({**c, "error": exc.code})
        return out

    citations = resolve(n["citations"], "citations", True)
    validity_citations = resolve(validity["citations"], "validity", True)
    path = [{**s, "citations": resolve(s["citations"], f"step:{i}", False)} for i, s in enumerate(steps, 1)]
    state = "reject" if rejects else "hold" if holds else "pending"
    payload = {"relationKey": n["relationKey"], "type": relation_type, "direction": direction(relation_type),
               "subject": n["subject"], "object": n["object"], "reordered": n["reordered"], "connection": n["connection"],
               "businessScope": n["businessScope"], "productScope": n["productScope"],
               "validity": {"from": validity["from"], "until": validity["until"],
                            "fromStatus": "known" if validity["from"] else "unknown", "untilStatus": "known" if validity["until"] else "unknown",
                            "citations": validity_citations},
               "countries": declared, "context": {"market": market, "check": country_check, "knownCountries": sorted(known),
                   "normalizationVersion": COUNTRY_CONTEXT_VERSION, "rawGeography": list(geography.raw),
                   "unresolvedGeography": list(geography.unresolved)},
               "citations": citations, "path": path, "generatorReasons": n["reasons"], "proposalCount": n["proposalCount"],
               "precheck": {"state": state, "reasons": [*rejects, *holds]}, "approved": False,
               "facts": None, "quotes": None, "claims": None}
    if state == "pending":
        payload["facts"] = facts(payload, view)
        payload["quotes"] = quotes(payload)
        payload["claims"] = claims(payload)
    return payload


def reevaluate(stored: dict, view: View) -> dict:
    """The deterministic precheck re-run over an already stored candidate against the CURRENT frozen view and exact sources. Final human approval
    uses it: the result is the candidate as it would be generated today, so any difference (schema, endpoint, citation, rights drift) is visible."""
    n = {key: stored[key] for key in ("relationKey", "type", "subject", "object", "reordered", "connection", "businessScope", "productScope",
                                      "countries", "citations", "path", "proposalCount")}
    n["validity"] = {"from": stored["validity"]["from"], "until": stored["validity"]["until"], "citations": stored["validity"]["citations"]}
    n["reasons"] = stored["generatorReasons"]
    return evaluate(n, view)


def facts(c: dict, view: View) -> dict:
    """Fixed, reasoning-free statement the verifier judges. Contains no generator reasoning, ID, confidence or sibling output."""
    def ep(e: dict) -> dict:
        return {"kind": e["kind"], "ref": e["ref"], "names": view.names(e)}

    return {"type": c["type"], "direction": c["direction"], "subject": ep(c["subject"]), "object": ep(c["object"]), "connection": c["connection"],
            "businessScope": c["businessScope"], "productScope": c["productScope"],
            "validity": {"from": c["validity"]["from"], "until": c["validity"]["until"]}, "countries": c["countries"],
            "path": [{"type": s["type"], "subject": ep(s["subject"]), "object": ep(s["object"])} for s in c["path"]]}


def quote_entry(c: dict) -> dict:
    return {"quoteId": c["evidenceId"], "documentId": c["documentId"], "documentVersion": c["documentVersion"],
            "start": c["start"], "end": c["end"], "text": c["quote"]}


def _unique_quotes(groups: list[list[dict]]) -> list[dict]:
    found = {c["evidenceId"]: quote_entry(c) for group in groups for c in group}
    return [found[k] for k in sorted(found)]


def quotes(c: dict) -> list[dict]:
    return _unique_quotes([c["citations"], c["validity"]["citations"], *(s["citations"] for s in c["path"])])


def _ids(*groups: list[dict]) -> list[str]:
    return sorted({x["evidenceId"] for g in groups for x in g})


def claims(c: dict) -> list[dict]:
    """Every fact the gate needs, each with the quotes it may rely on. Unverified claims keep the relation out of `eligible`."""
    direct = _ids(c["citations"])
    everything = _ids(c["citations"], c["validity"]["citations"], *(s["citations"] for s in c["path"]))
    base = direct if c["connection"] == "direct" else everything
    out = [{"claimId": "subject", "quoteIds": base}, {"claimId": "object", "quoteIds": base}]
    if c["connection"] == "direct":
        out.append({"claimId": "type", "quoteIds": direct})
        if c["direction"] == "directed":
            out.append({"claimId": "direction", "quoteIds": direct})
    else:
        out += [{"claimId": f"step:{i}", "quoteIds": _ids(s["citations"])} for i, s in enumerate(c["path"], 1)]
        out.append({"claimId": "connection", "quoteIds": base})
    if c["businessScope"] is not None or c["productScope"] is not None:
        out.append({"claimId": "scope", "quoteIds": base})
    if c["validity"]["from"] or c["validity"]["until"]:
        out.append({"claimId": "validity", "quoteIds": _ids(c["validity"]["citations"])})
    if c["countries"]:
        out.append({"claimId": "context", "quoteIds": base})
    return out


# ---------------------------------------------------------------- relation verification gate ----------------------------

def attempt_wire(kind: str, seq: int, policy: str, prior: str | None) -> dict:
    return {"kind": kind, "seq": seq, "policyVersion": policy, "priorVerdictDigest": prior}


def verifier_request(c: dict, attempt: dict) -> dict:
    return {"schemaVersion": VERIFY_REQUEST, "stage": "verify-relation", "verifierVersion": VERIFIER, "policyVersion": attempt["policyVersion"],
            "attempt": attempt, "relation": c["facts"], "quotes": c["quotes"], "claims": c["claims"]}


def decide_relation(c: dict, raw: Any) -> dict:
    """Fail closed: contradicted -> reject; reversed direction / insufficient -> hold; eligible only if every claim is supported."""
    response = parse(VerifierResponse, raw, "verifier_reply_invalid")
    allowed = {x["claimId"]: set(x["quoteIds"]) for x in c["claims"]}
    seen: dict[str, Any] = {}
    for claim in response.claims:
        if claim.claim_id in seen:
            raise ReplyInvalid("verifier_claim_duplicate")
        if claim.claim_id not in allowed:
            raise ReplyInvalid("verifier_claim_unknown")
        if claim.verdict == "reversed" and not (claim.claim_id == "direction" or claim.claim_id.startswith("step:")):
            raise ReplyInvalid("verifier_verdict_invalid")
        if len(set(claim.quote_ids)) != len(claim.quote_ids) or not set(claim.quote_ids) <= allowed[claim.claim_id]:
            raise ReplyInvalid("verifier_quote_unbound")
        if claim.verdict == "supported" and not claim.quote_ids:
            raise ReplyInvalid("verifier_support_uncited")
        seen[claim.claim_id] = claim
    if set(seen) != set(allowed):
        raise ReplyInvalid("verifier_claim_missing")
    rejects, holds = [], []
    for item in c["claims"]:
        verdict = seen[item["claimId"]].verdict
        if verdict == "contradicted":
            rejects.append(_reason("claim_contradicted", item["claimId"]))
        elif verdict == "reversed":
            holds.append(_reason("direction_reversed", item["claimId"]))
        elif verdict == "insufficient":
            holds.append(_reason("claim_insufficient", item["claimId"]))
    status = "reject" if rejects else "hold" if holds else "eligible"
    return {"eligibility": status, "reasons": [*rejects, *holds],
            "claims": [{"claimId": i["claimId"], "verdict": seen[i["claimId"]].verdict, "quoteIds": seen[i["claimId"]].quote_ids} for i in c["claims"]]}


# ---------------------------------------------------------------- impact -----------------------------------------------

def impact_request(relation: dict, documents: list[dict]) -> dict:
    return {"schemaVersion": IMPACT_REQUEST, "stage": "impact", "producerVersion": IMPACT_PRODUCER, "policyVersion": IMPACT_POLICY,
            "relation": relation["facts"], "relationQuotes": relation["quotes"],
            "companies": [e for e in (relation["facts"]["subject"], relation["facts"]["object"]) if e["kind"] == "company"],
            "documents": documents}


def evaluate_impacts(response: ImpactResponse, relation: dict, allowed: set[tuple], cite: Callable[[dict], dict]) -> list[dict]:
    companies = {e["ref"] for e in (relation["subject"], relation["object"]) if e["kind"] == "company"}
    seen: set[str] = set()
    out = []
    for p in response.impacts:
        if p.impacted_company_id in seen:
            raise ReplyInvalid("impact_duplicate_target")
        seen.add(p.impacted_company_id)
        wire = p.wire()
        rejects: list[dict] = []
        if p.impacted_company_id not in companies:
            rejects.append(_reason("impact_target_invalid"))

        def resolve(items: list[dict], at: str) -> list[dict]:
            found = []
            for index, c in enumerate(items, 1):
                try:
                    if (c["documentId"], c["documentVersion"]) not in allowed:
                        raise CitationFailure("citation_document_unbound")
                    found.append(cite(c))
                except CitationFailure as exc:
                    rejects.append(_reason("citation_invalid", f"{at}:{index}", exc.code))
                    found.append({**c, "error": exc.code})
            return found

        supporting, opposing = resolve(wire["supporting"], "supporting"), resolve(wire["opposing"], "opposing")
        valid = [c for c in (*supporting, *opposing) if "error" not in c]
        state = "reject" if rejects else "pending" if valid else "no-evidence"
        target = next((e for e in (relation["facts"]["subject"], relation["facts"]["object"]) if e["ref"] == p.impacted_company_id and e["kind"] == "company"), None)
        out.append({"impactedCompanyId": p.impacted_company_id, "target": target, "relationFacts": relation["facts"],
                    "proposal": {"direction": p.direction, "reason": p.reason, "limitations": p.limitations, "supporting": supporting, "opposing": opposing},
                    "precheck": {"state": state, "reasons": rejects}, "quotes": _unique_quotes([valid]) if state == "pending" else [], "approved": False})
    return sorted(out, key=lambda x: x["impactedCompanyId"])


def impact_verifier_request(c: dict, attempt: dict) -> dict:
    return {"schemaVersion": IMPACT_VERIFY_REQUEST, "stage": "verify-impact", "verifierVersion": IMPACT_VERIFIER, "policyVersion": attempt["policyVersion"],
            "attempt": attempt, "relation": c["relationFacts"], "target": c["target"], "quotes": c["quotes"]}


def label_from(positive: list[str], negative: list[str]) -> str:
    """Both sides cited and verifier-mapped -> mixed; one side -> that side; nothing mapped -> undetermined. Never a price probability."""
    return "mixed" if positive and negative else "positive" if positive else "negative" if negative else "undetermined"


def decide_impact(c: dict, raw: Any) -> dict:
    response = parse(ImpactVerifierResponse, raw, "verifier_reply_invalid")
    ids = [q.quote_id for q in response.quotes]
    expected = {q["quoteId"] for q in c["quotes"]}
    if len(set(ids)) != len(ids):
        raise ReplyInvalid("verifier_quote_duplicate")
    if not set(ids) <= expected:
        raise ReplyInvalid("verifier_quote_unbound")
    if set(ids) != expected:
        raise ReplyInvalid("verifier_quote_missing")
    effect = {q.quote_id: q.effect for q in response.quotes}
    mapped = {side: [i for i in sorted(effect) if effect[i] == key] for side, key in (("positive", "positive"), ("negative", "negative"), ("neutral", "neutral"))}
    uncertain = [i for i in sorted(effect) if effect[i] == "uncertain"]
    if uncertain:
        mapped["uncertain"] = uncertain  # only present when a (live) verifier was not confident about a quote, so replay verdicts keep their exact shape
    if response.target == "contradicted":
        return {"status": "reject", "label": None, "reasons": [_reason("impact_target_contradicted")], "targetVerdict": response.target, "mapped": mapped}
    if uncertain:
        # One unconfident quote effect means the cited evidence is not a confident reading: no label may come from the other quotes.
        reasons = [_reason("quote_effect_uncertain"), *([_reason("impact_target_insufficient")] if response.target == "insufficient" else [])]
        return {"status": "verified", "label": "undetermined", "reasons": reasons, "targetVerdict": response.target, "mapped": mapped}
    if response.target == "insufficient":
        return {"status": "verified", "label": "undetermined", "reasons": [_reason("impact_target_insufficient")], "targetVerdict": response.target, "mapped": mapped}
    label = label_from(mapped["positive"], mapped["negative"])
    return {"status": "verified", "label": label, "reasons": [] if label != "undetermined" else [_reason("direction_insufficient")],
            "targetVerdict": response.target, "mapped": mapped}
