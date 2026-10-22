"""v2.6 source-bound fact planning, followed by a separate analytical draft.

These guards establish identity/extractive provenance, not semantic truth. The
independent verifier must still approve every fact and every analytical clause.
"""
import copy
import re

VERSION = "market-context-v3-grounded"
EXTRACTIVE_VERSIONS = {"market-context-v2.9-outlook", VERSION}
SEMANTIC_VERSIONS = {"market-context-v2.8-outlook", *EXTRACTIVE_VERSIONS}
STRICT_VERSIONS = {"market-context-v2.7-outlook", *SEMANTIC_VERSIONS}
VERSIONS = {"market-context-v2.6-outlook", *STRICT_VERSIONS}
FLAGS = ("factPlanCoverage", "scopePreserved", "koreanOnly")


def fact_schema(evidence, translated=False, extractive=False):
    if extractive:
        fields = {"text": {"type":"string","minLength":1,"maxLength":250},
            "sourceIds":{"type":"array","items":{"type":"string","enum":sorted(evidence)},"minItems":1,"maxItems":2},
            "factType":{"type":"string","enum":["revenue","operating_profit","net_profit","launch","plan","other"]}}
        return {"type":"object","properties":{"facts":{"type":"array","minItems":1,"maxItems":3,"items":{"type":"object","properties":fields,"required":list(fields),"additionalProperties":False}}},"required":["facts"],"additionalProperties":False}

    fields = {"text": {"type": "string", "minLength": 1, "maxLength": 250},
              "evidenceId": {"type": "string", "enum": sorted(evidence)},
              "sourceQuote": {"type": "string", "minLength": 12, "maxLength": 350},
              "subject": {"type": "string", "minLength": 1},
              "metric": {"type": "string", "minLength": 1},
              "period": {"type": "string"},
              "qualifiers": {"type": "array", "items": {"type": "string"}, "maxItems": 6}}
    if translated:
        fields["qualifiers"]["items"] = {"type": "object", "properties": {"sourceText": {"type": "string", "minLength": 1}, "renderedText": {"type": "string", "minLength": 1}}, "required": ["sourceText", "renderedText"], "additionalProperties": False}
    return {"type": "object", "properties": {"facts": {"type": "array", "minItems": 1, "maxItems": 3,
        "items": {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}}},
        "required": ["facts"], "additionalProperties": False}


def validate_facts(plan, evidence, require, translated=False, extractive=False):
    require(type(plan) is dict and set(plan) == {"facts"} and type(plan["facts"]) is list
            and 1 <= len(plan["facts"]) <= 3, "market_fact_plan_shape")
    if extractive:
        for index, fact in enumerate(plan["facts"]):
            require(set(fact) == {"text","sourceIds","factType"} and fact["factType"] in {"revenue","operating_profit","net_profit","launch","plan","other"}, "market_fact_fields")
            ids = fact["sourceIds"]
            require(type(ids) is list and 1 <= len(ids) <= 2 and len(set(ids)) == len(ids) and all(i in evidence for i in ids), "market_fact_source_identity")
            owners = {evidence[i].get("documentId") for i in ids}
            require(len(owners) == 1 and None not in owners and "" not in owners, "market_fact_source_owner")
            require(sum(word in fact["text"] for word in ("매출","영업이익","순이익")) <= 1, "market_fact_multiple_metrics")
            language(fact["text"], require)
        return
    seen, errors = set(), []
    for index, f in enumerate(plan["facts"]):
        def check(condition, reason):
            if not condition:
                errors.append("fact:" + str(index) + " " + reason)

        check(set(f) == {"text", "evidenceId", "sourceQuote", "subject", "metric", "period", "qualifiers"}, "market_fact_fields")
        check(f["evidenceId"] in evidence and 12 <= len(f["sourceQuote"]) <= 350
                and f["sourceQuote"] in evidence[f["evidenceId"]]["quote"], "market_fact_exact_quote")
        check(f["subject"].strip() and f["metric"].strip() and f["subject"] in f["sourceQuote"]
                and f["metric"] in f["sourceQuote"], "market_fact_subject_metric: subject=" + f["subject"] + ", metric=" + f["metric"] + "; both must occur literally inside sourceQuote; choose a complete identity-bearing quote/evidence from the frozen document")
        # Independent financial metrics cannot hide in a single fact even when
        # the same source sentence reports them together. Other semantics are verified.
        check(sum(word in f["text"] for word in ("매출", "영업이익", "순이익")) <= 1, "market_fact_multiple_metrics")
        for q in f["qualifiers"]:
            source, rendered = (q["sourceText"], q["renderedText"]) if translated else (q, q)
            check(source and rendered and source in f["sourceQuote"] and rendered in f["text"], "market_fact_qualifier: original=" + str(source) + ", rendered=" + str(rendered) + "; original must be in sourceQuote AND rendered must be in text; do not add an absent qualifier")
        check((f["evidenceId"], f["text"]) not in seen, "market_fact_duplicate")
        seen.add((f["evidenceId"], f["text"]))
        language(f["text"], check)
    require(not errors, "; ".join(errors))


def language(text, require):
    require(not re.search(r"[\u3040-\u30ff]", text), "market_grounding_foreign_language")


def sources(fact):
    return fact["sourceIds"] if "sourceIds" in fact else [fact["evidenceId"]]


def fact_claims(plan):
    return [{"kind": "fact", "text": f["text"], "evidenceIds": sources(f), "indicatorIds": [],
             "previousForecastIds": [], "previousPublicationIds": [], "evaluationIds": [],
             "targetId": None, "direction": None, "conditions": [], "counterFactors": [], "updateAction": None,
             "basisFactIds": ["fact:" + str(i)]} for i, f in enumerate(plan["facts"])]


def analysis_schema(schema, plan, unique=False):
    schema = copy.deepcopy(schema)
    count = len(plan["facts"])
    ids = ["fact:" + str(i) for i in range(count)]
    items = [schema["properties"]["claims"]["items"], *schema["properties"]["requiredClaims"]["properties"].values()]
    refs = sorted({e for f in plan["facts"] for e in sources(f)})
    for item in items:
        props = item["properties"]
        props["basisFactIds"] = {"type": "array", "items": {"type": "string", "enum": ids}, "minItems": 1, "maxItems": count}
        item["required"].append("basisFactIds")
        props["kind"]["enum"] = [k for k in props["kind"]["enum"] if k != "fact"]
        props["evidenceIds"] = {"type": "array", "items": {"type": "string", "enum": refs}, "minItems": 1, "maxItems": len(refs)}
    if unique:
        schema["properties"]["claims"]["items"]["properties"]["kind"]["enum"] = ["interpretation"]
    schema["properties"]["claims"].update(minItems=1,
        maxItems=1 if unique else 8-count-len(schema["properties"]["requiredClaims"]["required"]))
    return schema


def project(draft, plan, require, unique=False):
    facts = fact_claims(plan)
    for c in draft["claims"]:
        require(c["kind"] != "fact", "market_fact_rewrite_forbidden")
        ids = c.get("basisFactIds")
        require(type(ids) is list and ids and len(set(ids)) == len(ids)
                and all(i in {"fact:" + str(n) for n in range(len(facts))} for i in ids), "market_analysis_foreign_fact")
        refs = {e for i in ids for e in sources(plan["facts"][int(i.split(":")[1])])}
        require(set(c["evidenceIds"]) == refs, "market_analysis_fact_evidence")
        for text in [c["text"], *c["counterFactors"]]:
            language(text, require)
    claims = [*facts, *draft["claims"]]
    if unique:
        require(len({c["text"] for c in claims}) == len(claims), "market_grounding_duplicate_claim")
        targets = [c["targetId"] for c in claims if c["kind"] == "forecast"]
        require(len(set(targets)) == len(targets), "market_grounding_duplicate_target")
    return {"claims": claims}


def model_view(frozen, plan):
    context = frozen["marketContext"]
    previous = copy.deepcopy(context["previousPublication"])
    if previous["status"] == "available":
        previous["summary"] = {k:previous["summary"][k] for k in ("text","resultVersion","forecasts") if k in previous["summary"]}
    evidence = {s["evidenceId"]:s for item in frozen["selected"] for s in item["sources"]}
    evidence.update({s["evidenceId"]:s for doc in context["documents"] for s in doc["sources"]})
    ids = sorted({e for f in plan["facts"] for e in sources(f)})
    return {"round":{k:context[k] for k in ("roundId","date","edition","window")},
        "coverage":context["coverage"],"sources":{e:evidence[e] for e in ids},
        "marketSnapshot":frozen["marketSnapshot"],"forecastTargets":context["forecastTargets"],
        "forecastEvaluations":context["forecastEvaluations"],"previousPublication":previous,
        "claimRequirements":frozen["claimRequirements"],"scopeNote":frozen["scopeNote"]}


def model_input(request):
    if request["context"].get("summaryPromptVersion") != VERSION or request.get("phase") == "facts":
        return request
    fields = ("context","contextSha256","frozenInputSha256","phase","factPlan","factPlanRequestDigest",
              "repairAttempt","priorDraft","priorValidation","draft")
    return {**{k:request[k] for k in fields if k in request},"modelView":model_view(request,request["factPlan"])}
