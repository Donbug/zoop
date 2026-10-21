"""Frozen broad evidence and explicit prior-publication comparisons for market summaries.

The current adapter is retrospective: publisher clocks establish window membership,
not historical collection rights or the existence of a publication at that time.
"""

import copy
from datetime import timedelta
from decimal import Decimal
import importlib.util
from pathlib import Path


def helper(name):
    spec = importlib.util.spec_from_file_location("_context_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


legacy = helper("briefing_market_summary")
simulation = helper("briefing_round_simulation")
base = legacy.base
PROMPTS = legacy.PROMPTS.with_name("market-context")
POLICY = "market_context_prior_briefing_v2"
SCHEMA = "zoop-briefing-market-context-v1"


class ContextError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise ContextError(reason)


def identity_digest(value):
    """Cross-language identities use normalized decimal strings, never float renderings."""
    def normalize(item):
        if type(item) is dict:
            return {key: normalize(child) for key, child in item.items()}
        if type(item) is list:
            return [normalize(child) for child in item]
        if type(item) in (int, float):
            number = Decimal(str(item))
            require(number.is_finite(), "market_identity_nonfinite_number")
            return "0" if number == 0 else format(number.normalize(), "f")
        return item
    return base.digest(base.canonical(normalize(value)))


def context_evidence(context):
    return {source["evidenceId"]: source for card in context["documents"] for source in card["sources"]}


def calendar_targets(calendar, round_, snapshot):
    """No calendar, no invented trading day or price evaluation target."""
    if calendar is None:
        return [], "verified_session_calendar_missing"
    require(calendar.get("schemaVersion") == "zoop-market-session-calendar-v1", "market_calendar_schema")
    days = calendar.get("sessions")
    require(type(days) is list, "market_calendar_sessions")
    by_date = {}
    cutoff = legacy._aware(round_["window"]["to"])
    for day in days:
        require(type(day) is dict and day.get("date") not in by_date, "market_calendar_duplicate")
        require(type(day.get("sourceRef")) is str and day["sourceRef"].strip(), "market_calendar_source")
        require(legacy._aware(day.get("availableAt")) <= cutoff, "market_calendar_future_information")
        require(type(day.get("tradingDay")) is bool, "market_calendar_status")
        by_date[day["date"]] = day
    day = by_date.get(round_["date"])
    if day is None or not day["tradingDay"]:
        return [], "trading_session_unconfirmed_or_closed"
    target_date = round_["date"] if round_["edition"] == "morning" else day.get("nextTradingDate")
    target = by_date.get(target_date)
    if target is None or not target["tradingDay"]:
        return [], "target_trading_session_missing"
    end = legacy._aware(target.get("closeAt"))
    require(end.astimezone(legacy.KST).date().isoformat() == target_date and end > cutoff,
            "market_forecast_target_clock")
    targets = []
    for indicator in snapshot["marketVariables"].get("indicators", []):
        # Bank reference FX is deliberately not a stock-market closing-price target.
        if indicator.get("id") not in {"kospi", "kosdaq"} or indicator.get("status") not in {"ok", "delayed"}:
            continue
        if indicator.get("valueKind") != "close" or indicator.get("observedDate", "") >= target_date:
            continue
        require(legacy._finite(indicator.get("value")), "market_forecast_baseline")
        value = {"indicatorId": indicator["id"], "valueKind": "close", "baselineDate": indicator["observedDate"],
                 "baselineValue": indicator["value"], "targetDate": target_date, "targetEnd": target["closeAt"],
                 "calendarRef": target["sourceRef"], "rule": "close_vs_baseline_v1"}
        targets.append({"targetId": "market-target-" + identity_digest(value)[:32], **value})
    return targets, None if targets else "closing_baseline_unavailable"


def previous_publication(round_, records):
    expected = "evening" if round_["edition"] == "morning" else "morning"
    matches = [r for r in records if r.get("cutoff") == round_["window"]["from"] and r.get("edition") == expected]
    require(len(matches) <= 1, "market_previous_publication_ambiguous")
    if not matches:
        return {"status": "unavailable", "reason": "immediate_previous_edition_missing",
                "kind": "simulated_previous_output"}
    record = matches[0]
    result = record.get("summaryResult")
    if not result or result.get("verification", {}).get("status") != "PASS":
        return {"status": "unavailable", "reason": "immediate_previous_summary_withheld",
                "kind": "simulated_previous_output"}
    require(record["summaryResultSha256"] == base.digest(base.canonical(result)), "market_previous_result_digest")
    require(legacy._aware(record["cutoff"]) < legacy._aware(round_["window"]["to"]), "market_previous_future")
    return {"status": "available", "kind": "simulated_previous_output", "roundId": record["roundId"],
            "date": record["date"], "edition": record["edition"], "cutoff": record["cutoff"],
            "summaryResultSha256": record["summaryResultSha256"], "summary": copy.deepcopy(result)}


def evaluate_forecasts(previous, snapshot):
    if previous["status"] != "available":
        return []
    observations = {i["id"]: i for i in snapshot["marketVariables"].get("indicators", [])}
    cutoff = legacy._aware(snapshot["round"]["cutoff"])
    evaluations = []
    for forecast in previous["summary"].get("forecasts", []):
        target = forecast["target"]
        observation = observations.get(target["indicatorId"])
        reason = None
        if forecast["conditions"]:
            reason = "condition_outcomes_not_observed"
        elif forecast["direction"] == "uncertain":
            reason = "direction_not_testable"
        elif legacy._aware(target["targetEnd"]) > cutoff:
            reason = "target_period_not_finished"
        elif not observation or observation.get("status") not in {"ok", "delayed"} \
                or observation.get("valueKind") != target["valueKind"] \
                or observation.get("observedDate") != target["targetDate"]:
            reason = "exact_target_observation_missing"
        actual = None if reason else observation["value"]
        direction = None
        if reason is None:
            require(legacy._finite(actual) and legacy._finite(target["baselineValue"]), "market_evaluation_number")
            difference = Decimal(str(actual)) - Decimal(str(target["baselineValue"]))
            direction = "up" if difference > 0 else "down" if difference < 0 else "flat"
        record = {"forecastId": forecast["forecastId"], "rule": target["rule"], "target": target,
                  "status": "unavailable" if reason else "evaluated", "reason": reason,
                  "actualValue": actual, "actualDirection": direction,
                  "directionMatched": None if reason else direction == forecast["direction"]}
        evaluations.append({"evaluationId": "market-evaluation-" + identity_digest(record)[:32], **record})
    return evaluations


def build_context(rows, round_, snapshot, records=(), calendar=None, unconfirmed_total=0):
    cutoff, start = legacy._aware(round_["window"]["to"]), legacy._aware(round_["window"]["from"])
    require(snapshot["round"]["date"] == round_["date"] and snapshot["round"]["edition"] == round_["edition"]
            and legacy._aware(snapshot["round"]["cutoff"]) == cutoff, "market_context_round_binding")
    # Every verified source up to this cutoff is represented. No importance/top-three filter.
    documents = []
    seen, ids = set(), set()
    for row in sorted(rows, key=lambda r: r["documentId"]):
        if row["clockTime"] > cutoff:
            continue
        require(row["documentId"] not in ids, "market_context_duplicate_document")
        ids.add(row["documentId"])
        role = "new" if row["clockTime"] > start else "background"
        if (role, row["bodySha256"]) in seen:
            continue
        seen.add((role, row["bodySha256"]))
        body = row["body"]
        require(base.digest(body.encode()) == row["bodySha256"], "market_context_body_digest")
        # Exact extractive spans, not a fabricated factual card. Omitted body stays in source storage.
        spans = [(0, min(600, len(body)))]
        if len(body) > 900:
            spans.append((len(body) - 300, len(body)))
        sources = []
        for left, right in spans:
            identity = {"documentId": row["documentId"], "bodySha256": row["bodySha256"], "start": left, "end": right}
            sources.append({"evidenceId": "market-evidence-" + base.digest(base.canonical(identity))[:32],
                            **identity, "documentVersion": row["documentVersion"], "quote": body[left:right],
                            "offsetUnit": "unicode_code_point", "publishedAt": row["clockRecord"]["publishedAt"]})
        documents.append({"documentId": row["documentId"], "documentVersion": row["documentVersion"],
                          "bodySha256": row["bodySha256"], "companyNames": row["companyNames"],
                          "role": role, "sources": sources})
    previous = previous_publication(round_, records)
    targets, target_reason = calendar_targets(calendar, round_, snapshot)
    companies = sorted({name for doc in documents for name in doc["companyNames"]})
    context = {"schemaVersion": SCHEMA, "scope": "publication_clock_simulation", "operationalCollectionGate": False,
               "roundId": round_["roundId"], "date": round_["date"], "edition": round_["edition"],
               "window": round_["window"], "documents": documents, "previousPublication": previous,
               "forecastTargets": targets, "forecastUnavailableReason": target_reason, "sessionCalendar": calendar,
               "forecastEvaluations": evaluate_forecasts(previous, snapshot),
               "coverage": {"documents": len(documents), "newDocuments": sum(d["role"] == "new" for d in documents),
                            "backgroundDocuments": sum(d["role"] == "background" for d in documents),
                            "companyNames": companies, "unconfirmedTotal": unconfirmed_total,
                            "sectorPriceFeedAvailable": False, "universe": "available_verified_sources",
                            "bodyScope": "exact_prefix600_suffix300", "marketRepresentative": False,
                            "historicalBodyUnchangedProven": False}}
    require(len(documents) <= 1000, "market_context_population_limit")
    return context


def _prepare(data):
    require(base.digest(base.canonical(data["context"])) == data.get("contextSha256"), "market_context_request_digest")
    frozen, selected_evidence, indicators, _ = legacy._prepare(data)
    context = copy.deepcopy(data.get("marketContext"))
    require(type(context) is dict and context.get("schemaVersion") == SCHEMA, "market_context_missing")
    require(base.digest(base.canonical(context)) == data["context"].get("marketContextSha256"), "market_context_digest")
    require(context["roundId"] == data["context"]["roundId"] and context["edition"] == data["marketSnapshot"]["round"]["edition"],
            "market_context_identity")
    evidence = {**selected_evidence, **context_evidence(context)}
    previous = context["previousPublication"]
    forecasts = previous["summary"].get("forecasts", []) if previous["status"] == "available" else []
    prior = {f["forecastId"]: f for f in forecasts}
    evaluations = {e["evaluationId"]: e for e in context["forecastEvaluations"]}
    note = "확인된 전체 기업 자료와 제공 지표를 이용한 과거 회차 분석입니다. 미수집 자료·업종 시세·당시 수집 가용성 및 시장 전체 대표성은 입증하지 않습니다."
    if not context["forecastTargets"]:
        note += " 거래 세션·평가 기준이 없어 새로운 가격 전망은 제공하지 않습니다."
    frozen.update({"marketContext": context, "summaryPolicy": POLICY, "scopeNote": note,
                   "allowedEvidenceIds": sorted(evidence), "allowedPreviousForecastIds": sorted(prior),
                   "allowedEvaluationIds": sorted(evaluations),
                   "allowedPreviousPublicationIds": [previous["roundId"]] if previous["status"] == "available" else []})
    if data["context"].get("summaryPromptVersion") == ROLE_VERSION:
        frozen["claimRequirements"] = {"version": ROLE_VERSION, "requiredKinds": required_kinds(frozen),
            "factUnit": "one independently verifiable subject-predicate-time-scope assertion; qualifiers belong to that assertion",
            "comparisonUnit": "prior simulated judgment + current observation or missingness + server evaluation status",
            "repair": "return every required slot on every attempt; retain supported roles and correct only rejected content; never invent a missing outlook"}
    return frozen, evidence, indicators, prior, evaluations, note


def _schema(frozen, evidence, indicators, prior, evaluations):
    schema = base.strict_load(base.regular(PROMPTS / "generation.schema.json"))
    props = schema["properties"]["claims"]["items"]["properties"]
    for field, allowed in (("evidenceIds", evidence), ("indicatorIds", indicators),
                           ("previousForecastIds", prior), ("evaluationIds", evaluations)):
        if allowed:
            props[field]["items"]["enum"] = sorted(allowed)
        else:
            props[field]["maxItems"] = 0
    if frozen["allowedPreviousPublicationIds"]:
        props["previousPublicationIds"]["items"]["enum"] = frozen["allowedPreviousPublicationIds"]
    else:
        props["previousPublicationIds"]["maxItems"] = 0
    targets = frozen["marketContext"]["forecastTargets"]
    props["targetId"]["enum"] = [None, *(t["targetId"] for t in targets)]
    if not targets:
        props["kind"]["enum"].remove("forecast")
    if frozen["context"].get("summaryPromptVersion") == ROLE_VERSION:
        # Required roles are separate, mandatory schema fields on the first AND repair call.
        slots = {}
        for kind in required_kinds(frozen):
            slot = copy.deepcopy(schema["properties"]["claims"]["items"])
            slot["properties"]["kind"]["enum"] = [kind]
            slots[kind] = slot
        props["kind"]["enum"] = [k for k in props["kind"]["enum"]
            if k not in {"forecast_update", "result_comparison"} or k in slots]
        schema["properties"]["claims"].update(minItems=max(0, 2-len(slots)), maxItems=8-len(slots))
        schema["properties"]["requiredClaims"] = {"type": "object", "properties": slots,
            "required": list(slots), "additionalProperties": False}
    return schema


QUALITY_VERSION = "market-context-v2.3-outlook"
QUALITY_FLAGS = ("atomicClaim", "evidenceClauseCoverage", "qualifiersPreserved", "observableConditionsOnly")
ROLE_VERSION = "market-context-v2.4-outlook"
ROLE_FLAGS = ("factUnitAppropriate", "comparisonElementsComplete", "evidenceClauseCoverage", "qualifiersPreserved", "observableConditionsOnly")
QUALITY_VERSIONS = {QUALITY_VERSION, ROLE_VERSION}


def required_kinds(frozen):
    context = frozen["marketContext"]
    kinds = ["forecast"] if context["forecastTargets"] else []
    previous = context["previousPublication"]
    if previous["status"] == "available":
        if context["edition"] == "morning" and previous["summary"].get("forecasts"):
            kinds.append("forecast_update")
        if context["edition"] == "evening":
            kinds.append("result_comparison")
    return kinds


def draft_claims(draft, frozen):
    """Lossless projection, never an insertion/restoration of an omitted model claim."""
    if frozen["context"].get("summaryPromptVersion") != ROLE_VERSION:
        return draft
    require(type(draft) is dict and set(draft) == {"claims", "requiredClaims"}
            and type(draft["claims"]) is list and type(draft["requiredClaims"]) is dict,
            "market_role_draft_structure")
    roles = required_kinds(frozen)
    require(set(draft["requiredClaims"]) == set(roles), "market_role_required_slots")
    for role in roles:
        slot = draft["requiredClaims"][role]
        require(type(slot) is dict and slot.get("kind") == role, "market_role_slot_kind")
    require(all(c.get("kind") not in {"forecast_update", "result_comparison"} or c.get("kind") in roles for c in draft["claims"]),
            "market_role_comparison_slot_required")
    return {"claims": [*draft["claims"], *(draft["requiredClaims"][role] for role in roles)]}


def quality_claims(claims, evidence):
    """Deterministic anchor/condition guard; semantic coverage still needs a verifier."""
    for c in claims:
        if c["kind"] == "fact":
            owners = {evidence[e].get("documentId") for e in c["evidenceIds"]}
            require(None not in owners and "" not in owners and len(owners) + len(c["indicatorIds"]) == 1
                    and not c["previousForecastIds"] and not c["previousPublicationIds"] and not c["evaluationIds"],
                    "market_quality_fact_anchor")
        if c["kind"] == "forecast":
            require(c.get("conditions") == [], "market_quality_condition_observations_missing")


def _claims(draft, frozen, evidence, indicators, prior, evaluations):
    draft = draft_claims(draft, frozen)
    require(type(draft) is dict and set(draft) == {"claims"} and type(draft["claims"]) is list
            and 2 <= len(draft["claims"]) <= 8, "market_context_claim_count")
    targets = {t["targetId"]: t for t in frozen["marketContext"]["forecastTargets"]}
    claims = []
    for index, c in enumerate(draft["claims"]):
        for field, allowed in (("evidenceIds", evidence), ("indicatorIds", indicators),
                               ("previousForecastIds", prior), ("evaluationIds", evaluations),
                               ("previousPublicationIds", frozen["allowedPreviousPublicationIds"])):
            require(type(c.get(field)) is list and all(type(x) is str for x in c[field])
                    and len(set(c[field])) == len(c[field]) and set(c[field]) <= set(allowed), "market_context_foreign_reference")
        require(type(c.get("text")) is str and 0 < len(c["text"].strip()) <= 350, "market_context_claim_text")
        kind = c.get("kind")
        require(kind in {"fact", "interpretation", "forecast", "forecast_update", "result_comparison"}, "market_context_claim_kind")
        require(c["evidenceIds"] or c["indicatorIds"] or c["previousForecastIds"] or c["evaluationIds"] or c["previousPublicationIds"], "market_context_claim_without_basis")
        if kind == "forecast":
            require(c.get("targetId") in targets and c.get("direction") in {"up", "down", "flat", "uncertain"}
                    and c["evidenceIds"] and c["counterFactors"], "market_context_forecast_basis")
        else:
            require(c.get("targetId") is None and c.get("direction") is None
                    and c.get("conditions") == [] and c.get("counterFactors") == [], "market_context_nonforecast_target")
        if kind == "forecast_update":
            require(frozen["marketContext"]["edition"] == "morning" and c["previousForecastIds"]
                    and (c["evidenceIds"] or c["indicatorIds"]) and c.get("updateAction") in {"maintain", "strengthen", "weaken", "withdraw"},
                    "market_context_update_basis")
        else:
            require(c.get("updateAction") is None, "market_context_foreign_update")
        if kind == "result_comparison":
            require(frozen["marketContext"]["edition"] == "evening" and (c["previousForecastIds"] or c["previousPublicationIds"]), "market_context_comparison_basis")
            if frozen["context"].get("summaryPromptVersion") == ROLE_VERSION:
                expected = {key for key, value in evaluations.items() if value["forecastId"] in c["previousForecastIds"]}
                require(set(c["evaluationIds"]) == expected and (expected or not c["previousForecastIds"]),
                        "market_role_comparison_evaluations")
                require(c["previousForecastIds"] or c["evidenceIds"] or c["indicatorIds"], "market_role_comparison_current_basis")
        # Evaluation IDs must concern precisely the forecasts named by this claim.
        require(all(evaluations[e]["forecastId"] in c["previousForecastIds"] for e in c["evaluationIds"]), "market_context_evaluation_owner")
        claims.append({"claimId": "market:claim:" + str(index), **c})
    require(any(c["evidenceIds"] for c in claims), "market_context_news_required")
    if frozen["context"].get("summaryPromptVersion") in {"market-context-v2.1-outlook", "market-context-v2.2-outlook", *QUALITY_VERSIONS}:
        kinds = {c["kind"] for c in claims}
        if targets:
            require("forecast" in kinds, "market_outlook_forecast_required")
        if frozen["marketContext"]["previousPublication"]["status"] == "available":
            if frozen["marketContext"]["edition"] == "morning" and prior:
                require("forecast_update" in kinds, "market_outlook_update_required")
            if frozen["marketContext"]["edition"] == "evening":
                require("result_comparison" in kinds, "market_outlook_comparison_required")
    if frozen["context"].get("summaryPromptVersion") in QUALITY_VERSIONS:
        quality_claims(claims, evidence)
    return claims


def generate_market_summary(client, data, max_repairs=1):
    require(type(max_repairs) is int and max_repairs in (0, 1), "market_context_repair_limit")
    frozen, evidence, indicators, prior, evaluations, note = _prepare(data)
    frozen_sha = base.digest(base.canonical(frozen))
    schema = _schema(frozen, evidence, indicators, prior, evaluations)
    last_draft, last_validation, attempts, claims = None, None, [], []
    generation_key = verification_key = None
    for attempt in range(max_repairs + 1):
        request = {**frozen, "frozenInputSha256": frozen_sha, "repairAttempt": attempt,
                   "priorDraft": last_draft, "priorValidation": last_validation}
        generation_key = client.request_digest("market_summary_generation", request,
            "generation.md", "generation.schema.json", max_output=8000, schema_override=schema)
        last_draft = client.call("market_summary_generation", request,
            "generation.md", "generation.schema.json", max_output=8000, schema_override=schema)
        try:
            claims = _claims(last_draft, frozen, evidence, indicators, prior, evaluations)
        except ContextError as error:
            claims, verification_key = [], None
            last_validation = {"status": "WITHHELD", "checks": [], "reason": str(error)}
            attempts.append({"attempt": attempt, "generationRequestDigest": generation_key, "verification": last_validation})
            continue
        template = base.strict_load(base.regular(PROMPTS / "verification.schema.json"))
        item = template["properties"]["checks"]["items"]
        props = {}
        for c in claims:
            check = copy.deepcopy(item)
            check["properties"]["targetId"]["enum"] = [c["claimId"]]
            props[c["claimId"]] = check
        template["properties"]["checks"] = {"type": "object", "properties": props,
                                            "required": list(props), "additionalProperties": False}
        verify_data = {**frozen, "frozenInputSha256": frozen_sha, "draft": {"claims": claims}}
        verification_key = client.request_digest("market_summary_verification", verify_data,
            "verification.md", "verification.schema.json", max_output=8000, schema_override=template)
        decision = client.call("market_summary_verification", verify_data,
            "verification.md", "verification.schema.json", max_output=8000, schema_override=template)
        require(set(decision.get("checks", {})) == {c["claimId"] for c in claims}, "market_context_verification_coverage")
        checks = list(decision["checks"].values())
        flags = ("noUnsupportedNumbers", "noUnsupportedCausality", "temporalAppropriate", "noInvestmentAdvice",
                 "comparisonAppropriate", "forecastAppropriate")
        if frozen["context"].get("summaryPromptVersion") in QUALITY_VERSIONS:
            flags += ROLE_FLAGS if frozen["context"]["summaryPromptVersion"] == ROLE_VERSION else QUALITY_FLAGS
        passed = all(check["verdict"] == "SUPPORTED" and all(check[k] is True for k in flags) for check in checks)
        last_validation = {"status": "PASS" if passed else "WITHHELD", "checks": checks,
                           "meaning": "Independent model assessment of frozen inputs; no external fact certification."}
        attempts.append({"attempt": attempt, "generationRequestDigest": generation_key,
                         "verificationRequestDigest": verification_key, "verification": last_validation})
        if passed:
            break
    keys = {a[k] for a in attempts for k in ("generationRequestDigest", "verificationRequestDigest") if k in a}
    receipts = [r for r in client.receipts() if r["requestDigest"] in keys]
    generated = max((r["finishedAt"] for r in receipts if r.get("stage") == "market_summary_generation"), default=base.now())
    passed = last_validation["status"] == "PASS"
    text = "\n".join([*(c["text"] for c in claims), note]) if passed else None
    version = "market-summary-" + base.digest(base.canonical({"input": frozen_sha, "claims": claims,
                        "generation": generation_key, "verification": verification_key}))[:32] if passed else None
    evidence_ids = sorted({e for c in claims for e in c["evidenceIds"]}) if passed else []
    forecasts = []
    if passed:
        for c in claims:
            if c["kind"] == "forecast":
                value = {"target": next(t for t in frozen["marketContext"]["forecastTargets"] if t["targetId"] == c["targetId"]),
                         "text": c["text"], "direction": c["direction"], "conditions": c["conditions"],
                         "counterFactors": c["counterFactors"], "evidenceIds": c["evidenceIds"], "indicatorIds": c["indicatorIds"]}
                forecasts.append({"forecastId": "market-forecast-" + identity_digest({"value": value, "version": version})[:32], **value})
    return {"generatedAt": generated, "policy": POLICY, "claims": claims, "text": text, "scopeNote": note,
            "summary": {"text": text, "generatedAt": generated, "resultVersion": version, "evidenceIds": evidence_ids} if passed else None,
            "verification": last_validation, "resultVersion": version, "evidenceIds": evidence_ids,
            "generationRequestDigest": generation_key, "verificationRequestDigest": verification_key,
            "contextSha256": data["contextSha256"], "marketContextSha256": data["context"]["marketContextSha256"],
            "marketSnapshotSha256": frozen["marketSnapshotSha256"], "frozenInputSha256": frozen_sha,
            "forecasts": forecasts, "forecastEvaluations": frozen["marketContext"]["forecastEvaluations"],
            "attempts": attempts, "usage": receipts}
