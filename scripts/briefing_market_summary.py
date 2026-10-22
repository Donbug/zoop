"""Operator-only, source-bound news/indicator summary with immutable paid receipts.

The caller freezes selected PASS news and normalized historical indicators. This
module neither fetches indicators nor treats their coincidence as market causality.
"""

from datetime import datetime, timezone, timedelta
import copy
import importlib.util
import math
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("_zoop_market_summary_replay", Path(__file__).with_name("briefing_replay.py"))
base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(base)
PROMPTS = Path(__file__).resolve().parents[1] / "api/src/main/resources/briefing/prompts/market-summary"
MODEL = "gpt-6-luna"
POLICY = "selected_news_normalized_indicators_v1"
KST = timezone(timedelta(hours=9))
INDICATOR_IDS = {"kospi", "kosdaq", "usdkrw"}


class MarketSummaryError(base.ReplayError):
    pass


class MarketSummaryClient(base.ResponsesClient):
    """Dedicated prompts; keep model/store/schema/immutable-call accounting explicit."""

    def __init__(self, *args, prompt_root=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.prompt_root = prompt_root

    def request(self, stage, data, prompt_name, schema_name, max_output=8000, schema_override=None):
        return prepare_market_request(self.prompt_root or PROMPTS, stage, data, prompt_name, schema_name,
                                      max_output=max_output, schema_override=schema_override)


def prepare_market_request(root, stage, data, prompt_name, schema_name, max_output=8000, schema_override=None):
    instructions = base.regular(root / prompt_name).decode("utf-8")
    schema = base.strict_load(base.canonical(schema_override)) if schema_override is not None \
        else base.strict_load(base.regular(root / schema_name))
    request = {"model": MODEL, "store": False, "max_output_tokens": max_output, "instructions": instructions,
               "input": base.canonical(data).decode("utf-8"), "reasoning": {"effort": "low"},
               "text": {"format": {"type": "json_schema", "name": stage, "strict": True, "schema": schema}}}
    encoded = base.canonical(request)
    if len(encoded) > 2 * 1024 * 1024:
        raise MarketSummaryError("market_summary_request_size_exceeded")
    return encoded, schema, base.digest(instructions.encode())


def _aware(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise MarketSummaryError("market_summary_timestamp_invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MarketSummaryError("market_summary_timestamp_naive")
    return parsed


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _prepare(data):
    if type(data) is not dict or type(data.get("context")) is not dict \
            or type(data.get("contextSha256")) is not str or len(data["contextSha256"]) != 64 \
            or any(c not in "0123456789abcdef" for c in data["contextSha256"]):
        raise MarketSummaryError("market_summary_context_binding_missing")
    frozen = base.strict_load(base.canonical(data))
    selected, news, snapshot = frozen.get("selected"), frozen.get("newsItems"), frozen.get("marketSnapshot")
    if type(selected) is not list or len(selected) > 3 or type(news) is not list or type(snapshot) is not dict \
            or snapshot.get("scope") != "historical_snapshot":
        raise MarketSummaryError("market_summary_frozen_input_invalid")
    snapshot_sha = base.digest(base.canonical(snapshot))
    if frozen["context"].get("marketSnapshotSha256", snapshot_sha) != snapshot_sha:
        raise MarketSummaryError("market_summary_snapshot_digest_mismatch")
    round_ = snapshot.get("round") or {}
    cutoff = _aware(round_.get("cutoff"))
    if round_.get("date") != cutoff.astimezone(KST).date().isoformat() \
            or round_.get("edition") not in {"morning", "evening"}:
        raise MarketSummaryError("market_summary_round_identity_mismatch")
    _aware(snapshot.get("fetchedAt"))
    evidence, issues = {}, set()
    for item in selected:
        if type(item) is not dict or type(item.get("issueId")) is not str or not item["issueId"] or item["issueId"] in issues \
                or type(item.get("sources")) is not list or not item["sources"]:
            raise MarketSummaryError("market_summary_selected_identity_invalid")
        issues.add(item["issueId"])
        for source in item["sources"]:
            if type(source) is not dict or type(source.get("evidenceId")) is not str or not source["evidenceId"] \
                    or type(source.get("quote")) is not str or not source["quote"].strip():
                raise MarketSummaryError("market_summary_selected_evidence_missing")
            key = source["evidenceId"]
            if key in evidence and evidence[key] != source:
                raise MarketSummaryError("market_summary_evidence_identity_conflict")
            evidence[key] = source
    news_ids = [item.get("issueId") for item in news if type(item) is dict]
    if len(news_ids) != len(news) or len(set(news_ids)) != len(news_ids) or set(news_ids) != issues:
        raise MarketSummaryError("market_summary_news_selected_coverage_mismatch")
    variables = snapshot.get("marketVariables")
    if type(variables) is not dict or variables.get("status") not in {"available", "unavailable"}:
        raise MarketSummaryError("market_summary_variables_status_invalid")
    if variables.get("referenceAt") is not None and _aware(variables["referenceAt"]) != cutoff:
        raise MarketSummaryError("market_summary_variables_cutoff_mismatch")
    if variables.get("rateCutoffAt") is not None and _aware(variables["rateCutoffAt"]) > cutoff:
        raise MarketSummaryError("market_summary_variables_cutoff_mismatch")
    all_indicators = variables.get("indicators", [])
    if type(all_indicators) is not list or len(all_indicators) > 3:
        raise MarketSummaryError("market_summary_indicator_population_invalid")
    indicators, seen = {}, set()
    for indicator in all_indicators:
        if type(indicator) is not dict or type(indicator.get("id")) is not str \
                or indicator["id"] not in INDICATOR_IDS or indicator["id"] in seen \
                or indicator.get("status") not in {"ok", "delayed", "unavailable", "failed"}:
            raise MarketSummaryError("market_summary_indicator_identity_invalid")
        seen.add(indicator["id"])
        if indicator["status"] in {"unavailable", "failed"}:
            if indicator.get("value") is not None:
                raise MarketSummaryError("market_summary_missing_indicator_has_value")
            continue
        if variables["status"] != "available" or not _finite(indicator.get("value")):
            raise MarketSummaryError("market_summary_indicator_value_invalid")
        if indicator.get("unit") != ("KRW" if indicator["id"] == "usdkrw" else "pt") \
                or indicator.get("valueKind") not in {"close", "latest", "reference"} \
                or (indicator.get("valueKind") == "reference" and indicator["id"] != "usdkrw"):
            raise MarketSummaryError("market_summary_indicator_unit_or_kind_invalid")
        try:
            observed_date = datetime.strptime(indicator["observedDate"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError) as error:
            raise MarketSummaryError("market_summary_indicator_observed_date_invalid") from error
        if observed_date > cutoff.astimezone(KST).date():
            raise MarketSummaryError("market_summary_future_indicator_not_allowed")
        if indicator.get("observedAt") is not None:
            observed = _aware(indicator["observedAt"])
            if observed > cutoff or observed.astimezone(KST).date() != observed_date:
                raise MarketSummaryError("market_summary_indicator_clock_mismatch")
        elif indicator["valueKind"] not in {"close", "reference"}:
            raise MarketSummaryError("market_summary_latest_indicator_time_missing")
        baseline = indicator.get("baseline")
        if baseline is not None:
            if type(baseline) is not dict or not _finite(baseline.get("value")):
                raise MarketSummaryError("market_summary_indicator_baseline_invalid")
        for field in ("change", "changeRate"):
            if indicator.get(field) is not None and (not _finite(indicator[field]) or baseline is None):
                raise MarketSummaryError("market_summary_indicator_change_without_baseline")
        indicators[indicator["id"]] = indicator
    raw_refs = snapshot.get("rawRefs", [])
    if type(raw_refs) is not list:
        raise MarketSummaryError("market_summary_raw_refs_invalid")
    for ref in raw_refs:
        if type(ref) is not dict or type(ref.get("source")) is not str or type(ref.get("url")) is not str \
                or type(ref.get("sha256")) is not str or len(ref["sha256"]) != 64 \
                or type(ref.get("bytes")) is not int or ref["bytes"] < 0:
            raise MarketSummaryError("market_summary_raw_ref_binding_missing")
    labels = {"kospi": "KOSPI", "kosdaq": "KOSDAQ", "usdkrw": "USD/KRW"}
    scope = "선정된 뉴스" if evidence else "제공된 지표"
    if evidence and indicators:
        scope += "와 제공된 " + "·".join(labels[key] for key in sorted(indicators)) + " 지표"
    elif not evidence and indicators:
        scope = "제공된 " + "·".join(labels[key] for key in sorted(indicators)) + " 지표"
    scope_note = scope + "만 요약합니다. 시장 전체를 대표하거나 뉴스와 지표의 인과관계·향후 전망을 입증하지 않습니다."
    if set(indicators) != INDICATOR_IDS:
        scope_note += " 미확보 지표는 제외했습니다."
    frozen.update({"summaryPolicy": POLICY, "scopeNote": scope_note,
                   "marketSnapshotSha256": snapshot_sha, "allowedEvidenceIds": sorted(evidence),
                   "allowedIndicatorIds": sorted(indicators)})
    return frozen, evidence, indicators, scope_note


def _generation_schema(evidence, indicators):
    schema = base.strict_load(base.regular(PROMPTS / "generation.schema.json"))
    fields = schema["properties"]["claims"]["items"]["properties"]
    for field, ids in (("evidenceIds", sorted(evidence)), ("indicatorIds", sorted(indicators))):
        if ids:
            fields[field]["items"]["enum"] = ids
        else:
            fields[field]["maxItems"] = 0
    return schema


def _verification_schema(claims):
    schema = base.strict_load(base.regular(PROMPTS / "verification.schema.json"))
    template = schema["properties"]["checks"]["items"]
    properties = {}
    for claim in claims:
        value = copy.deepcopy(template)
        value["properties"]["targetId"]["enum"] = [claim["claimId"]]
        properties[claim["claimId"]] = value
    schema["properties"]["checks"] = {"type": "object", "properties": properties,
        "required": list(properties), "additionalProperties": False}
    return schema


def _validate_draft(draft, evidence, indicators):
    if type(draft) is not dict or set(draft) != {"claims"} or type(draft["claims"]) is not list \
            or not 2 <= len(draft["claims"]) <= 4:
        raise MarketSummaryError("market_summary_claim_count_invalid")
    claims = []
    for index, claim in enumerate(draft["claims"]):
        if type(claim) is not dict or set(claim) != {"text", "evidenceIds", "indicatorIds"} \
                or type(claim["text"]) is not str or not 1 <= len(claim["text"].strip()) <= 250:
            raise MarketSummaryError("market_summary_claim_structure_invalid")
        for field, allowed in (("evidenceIds", evidence), ("indicatorIds", indicators)):
            ids = claim[field]
            if type(ids) is not list or any(type(key) is not str for key in ids) \
                    or len(ids) != len(set(ids)) or not set(ids).issubset(allowed):
                raise MarketSummaryError("market_summary_claim_reference_invalid")
        if not claim["evidenceIds"] and not claim["indicatorIds"]:
            raise MarketSummaryError("market_summary_claim_reference_missing")
        claims.append({"claimId": "market:claim:" + str(index), **claim})
    if not any(claim["evidenceIds"] for claim in claims):
        raise MarketSummaryError("market_summary_news_evidence_required")
    return claims


def _verify(decision, claims):
    if type(decision) is not dict or set(decision) != {"checks"} or type(decision["checks"]) is not dict \
            or set(decision["checks"]) != {claim["claimId"] for claim in claims}:
        raise MarketSummaryError("market_summary_verification_coverage_mismatch")
    passed = True
    checks = []
    fields = ("noUnsupportedNumbers", "noUnsupportedCausality", "temporalAppropriate", "noInvestmentAdvice")
    for claim in claims:
        check = decision["checks"][claim["claimId"]]
        if type(check) is not dict or set(check) != {"targetId", "verdict", "reason", *fields} \
                or check["targetId"] != claim["claimId"] \
                or type(check["verdict"]) is not str or check["verdict"] not in {"SUPPORTED", "UNSUPPORTED", "UNCERTAIN"} \
                or type(check["reason"]) is not str or not check["reason"].strip() \
                or any(type(check[field]) is not bool for field in fields):
            raise MarketSummaryError("market_summary_verification_structure_invalid")
        checks.append(check)
        passed = passed and check["verdict"] == "SUPPORTED" and all(check[field] for field in fields)
    return {"status": "PASS" if passed else "WITHHELD", "checks": checks,
            "meaning": "Separate model assessment against frozen news quotes and normalized indicators; no independent external fact verification."}


def generate_market_summary(client, data, max_repairs=1):
    if type(max_repairs) is not int or max_repairs not in (0, 1):
        raise MarketSummaryError("market_summary_repair_limit_invalid")
    frozen, evidence, indicators, scope_note = _prepare(data)
    frozen_sha = base.digest(base.canonical(frozen))
    last_draft, last_validation, attempts, claims = None, None, [], []
    generation_key, verification_key = None, None
    if not evidence:
        last_validation = {"status": "WITHHELD", "checks": [], "reason": "news_evidence_required_for_public_summary"}
    else:
        schema = _generation_schema(evidence, indicators)
        for attempt in range(max_repairs + 1):
            request = {**frozen, "frozenInputSha256": frozen_sha, "repairAttempt": attempt,
                       "priorDraft": last_draft, "priorValidation": last_validation}
            generation_key = client.request_digest("market_summary_generation", request,
                "generation.md", "generation.schema.json", max_output=4000, schema_override=schema)
            draft = client.call("market_summary_generation", request,
                "generation.md", "generation.schema.json", max_output=4000, schema_override=schema)
            last_draft = draft
            try:
                claims = _validate_draft(draft, evidence, indicators)
            except MarketSummaryError as error:
                # No final draft was structurally accepted in this attempt. Earlier paid attempts stay in attempts/usage.
                claims, verification_key = [], None
                last_validation = {"status": "WITHHELD", "checks": [], "reason": str(error)}
                attempts.append({"attempt": attempt, "generationRequestDigest": generation_key, "verification": last_validation})
                continue
            verification_data = {**frozen, "frozenInputSha256": frozen_sha, "draft": {"claims": claims}}
            verification_schema = _verification_schema(claims)
            verification_key = client.request_digest("market_summary_verification", verification_data,
                "verification.md", "verification.schema.json", max_output=6000, schema_override=verification_schema)
            decision = client.call("market_summary_verification", verification_data,
                "verification.md", "verification.schema.json", max_output=6000, schema_override=verification_schema)
            last_validation = _verify(decision, claims)
            attempts.append({"attempt": attempt, "generationRequestDigest": generation_key,
                             "verificationRequestDigest": verification_key, "verification": last_validation})
            if last_validation["status"] == "PASS":
                break
    keys = {attempt[key] for attempt in attempts for key in ("generationRequestDigest", "verificationRequestDigest") if key in attempt}
    receipts = [receipt for receipt in client.receipts() if receipt["requestDigest"] in keys]
    generated_at = max((receipt["finishedAt"] for receipt in receipts if receipt.get("stage") == "market_summary_generation"), default=base.now())
    passed = last_validation is not None and last_validation["status"] == "PASS"
    text = "\n".join([*(claim["text"] for claim in claims), scope_note]) if passed else None
    evidence_ids = sorted({key for claim in claims for key in claim["evidenceIds"]}) if passed else []
    version = "market-summary-" + base.digest(base.canonical({"frozenInputSha256": frozen_sha, "claims": claims,
               "scopeNote": scope_note, "generationRequestDigest": generation_key, "verificationRequestDigest": verification_key}))[:32] if passed else None
    summary = {"text": text, "generatedAt": generated_at, "resultVersion": version, "evidenceIds": evidence_ids} if passed else None
    return {"generatedAt": generated_at, "claims": claims, "scopeNote": scope_note, "text": text,
            "verification": last_validation, "generationRequestDigest": generation_key,
            "verificationRequestDigest": verification_key, "attempts": attempts, "summary": summary,
            "resultVersion": version, "evidenceIds": evidence_ids, "frozenInputSha256": frozen_sha,
            "marketSnapshotSha256": frozen["marketSnapshotSha256"], "contextSha256": frozen["contextSha256"],
            "usage": receipts, "policy": POLICY}
