#!/usr/bin/env python3
"""Item-scoped briefing recovery; never mutates a source, group or old response."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import importlib.util
from pathlib import Path
import re

_SPEC = importlib.util.spec_from_file_location("_item_recovery_base", Path(__file__).with_name("briefing_replay.py"))
base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(base)
ReplayError = base.ReplayError
PROMPTS = Path(__file__).resolve().parents[1] / "api/src/main/resources/briefing/prompts/item-recovery"
VERSION = "zoop-briefing-item-recovery-v1"
STAGES = {"generation": "briefing_item_recovery_generation", "verification": "briefing_item_recovery_verification",
          "novelty": "briefing_item_recovery_novelty"}
OUTPUT_CAPS = {"generation": 8000, "verification": 10000, "novelty": 8000}
FLAGS = ("typeAppropriate", "temporalAppropriate", "noUnsupportedNumbers", "noInvestmentAdvice", "conditionsPreserved", "atomicClaim")


def require(value, code):
    if not value:
        raise ReplayError(code)


def copied(value):
    return base.strict_load(base.canonical(value))


def _text(value):
    return type(value) is str and bool(value.strip())


def _stamp(value):
    require(type(value) is str, "recovery_timestamp_missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReplayError("recovery_timestamp_invalid") from error
    require(result.tzinfo is not None and result.utcoffset() is not None, "recovery_timestamp_naive")
    return result


def minimal_context(context):
    """Construct an allowlist; do not recursively copy old model context."""
    require(type(context) is dict, "recovery_context_invalid")
    identity = context.get("context", context)
    require(type(identity) is dict and identity.get("edition") in {"morning", "evening"}, "recovery_edition_invalid")
    try:
        date.fromisoformat(identity.get("date", ""))
    except (TypeError, ValueError) as error:
        raise ReplayError("recovery_round_date_invalid") from error
    window = identity.get("window")
    require(type(window) is dict and window.get("openStart") is False
            and _stamp(window.get("from")) < _stamp(window.get("to")), "recovery_window_invalid")
    result = {"date": identity["date"], "edition": identity["edition"],
        "window": {key: window[key] for key in ("from", "to", "openStart")},
        "mode": "publication_clock_simulation", "historicalBodyUnchangedProven": False,
        "operationalCollectionGate": False}
    for key in ("roundId", "sourceFileSha256", "groupArchiveSha256", "contextSha256",
                "recoveryRunId", "policyVersion", "baseBundleSha256", "clockFileSha256"):
        value = context.get(key, identity.get(key))
        if value is not None:
            require(_text(value), "recovery_context_identity_invalid")
            result[key] = value
    return result


def _source(source, window=None, history=False):
    require(type(source) is dict, "recovery_source_invalid")
    for key in ("evidenceId", "documentId", "documentVersion", "bodySha256", "quote"):
        require(_text(source.get(key)), "recovery_source_identity_missing")
    require(re.fullmatch(r"[0-9a-f]{64}", source["bodySha256"]) is not None,
            "recovery_source_digest_invalid")
    require(source["documentVersion"] == "sha256-" + source["bodySha256"], "recovery_source_version_mismatch")
    start, end = source.get("start"), source.get("end")
    require(type(start) is int and type(end) is int and 0 <= start < end
            and end - start == len(source["quote"]) and source.get("offsetUnit", "unicode_code_point") == "unicode_code_point",
            "recovery_source_span_invalid")
    clock = source.get("publicationClock")
    published = (clock or {}).get("publishedAt") or source.get("publishedAt") \
        or source.get("dateContext", {}).get("publishedAt")
    stamp = _stamp(published)
    if clock is not None:
        require(type(clock) is dict and clock.get("documentId") == source["documentId"]
                and clock.get("bodySha256") == source["bodySha256"]
                and base.digest(base.canonical(clock)) == source.get("clockRecordSha256"), "recovery_source_clock_binding_mismatch")
    if window is not None:
        require(stamp <= _stamp(window["from"]) if history else _stamp(window["from"]) < stamp <= _stamp(window["to"]),
                "recovery_source_outside_round_window")
    result = {key: source[key] for key in ("evidenceId", "documentId", "documentVersion", "bodySha256", "quote", "start", "end")}
    result.update(offsetUnit="unicode_code_point", publishedAt=published)
    if source.get("clockRecordSha256") is not None:
        result["clockRecordSha256"] = source["clockRecordSha256"]
    return copied(result)


def prepare_selections(selections, context=None):
    """Project selected issue/evidence identity without editorial model claims."""
    require(type(selections) is list and len(selections) <= 3, "recovery_selection_population_invalid")
    safe_context = minimal_context(context) if context is not None else None
    result, seen = [], set()
    for selection in selections:
        require(type(selection) is dict and _text(selection.get("issueId")) and selection["issueId"] not in seen,
                "recovery_duplicate_or_unknown_issue")
        seen.add(selection["issueId"])
        require(type(selection.get("sources")) is list and selection["sources"], "recovery_selection_evidence_missing")
        sources = [_source(source, safe_context["window"] if safe_context else None) for source in selection["sources"]]
        by_id = {source["evidenceId"]: source for source in sources}
        require(len(by_id) == len(sources), "recovery_duplicate_evidence_id")
        snapshot = selection.get("frozenGroupedIssueSnapshot")
        if snapshot is not None:
            require(type(snapshot) is dict and snapshot.get("issueId") == selection["issueId"], "recovery_snapshot_identity_mismatch")
            raw = {key: value for key, value in snapshot.items() if key != "asOfSnapshotSha256"}
            expected = base.digest(base.canonical(raw))
            require(snapshot.get("asOfSnapshotSha256") == expected
                    and selection.get("groupedIssueSnapshotSha256") == expected, "recovery_snapshot_changed")
            catalog = {proof["evidenceId"]: proof for mention in snapshot.get("newMentions", []) for proof in mention.get("evidence", [])}
            for key, source in by_id.items():
                require(key in catalog and _source(catalog[key], safe_context["window"] if safe_context else None) == source,
                        "recovery_snapshot_source_mismatch")
        links = []
        for link in selection.get("companyLinks", []):
            require(type(link) is dict and _text(link.get("companyId")) and _text(link.get("name"))
                    and type(link.get("evidenceIds")) is list and link["evidenceIds"]
                    and set(link["evidenceIds"]).issubset(by_id), "recovery_company_evidence_mismatch")
            links.append({key: copied(link.get(key)) for key in ("companyId", "name", "role", "evidenceIds")})
        result.append({"issueId": selection["issueId"], "rank": 1, "sources": sources, "companyLinks": links})
    return result


def prompt_artifacts():
    return {path.name: base.digest(base.regular(path)) for path in sorted(PROMPTS.iterdir()) if path.suffix in {".md", ".json"}}


def _schema(phase):
    return base.strict_load(base.regular(PROMPTS / (phase + ".schema.json")))


def _keyed_schema(phase, field, rows, key_field):
    value = _schema(phase)
    template = value["properties"][field]["items"]
    properties = {}
    for key, enums in rows:
        item = copied(template)
        item["properties"][key_field]["enum"] = [key]
        for path, values in enums.items():
            target = item
            for component in path:
                target = target[component]
            target["enum"] = values
        properties[key] = item
    value["properties"][field] = {"type": "object", "properties": properties,
        "required": list(properties), "additionalProperties": False}
    return value


class RecoveryClient(base.ResponsesClient):
    """Same immutable ledger and global 400-slot budget, new request identities."""
    def __init__(self, output, transport, max_calls=400, authorized_truncations=()):
        require(type(max_calls) is int and 1 <= max_calls <= 400, "recovery_shared_call_budget_invalid")
        super().__init__(output, transport, max_calls, authorized_truncations)
        self.frozen_prompts = prompt_artifacts()

    def call(self, stage, data, prompt_name, schema_name, max_output=None, schema_override=None):
        phase = next((key for key, value in STAGES.items() if value == stage), None)
        return super().call(stage, data, prompt_name, schema_name,
            max_output if max_output is not None else OUTPUT_CAPS.get(phase, 8000), schema_override)

    def request_digest(self, stage, data, prompt_name, schema_name, max_output=None, schema_override=None):
        return base.digest(self.request(stage, data, prompt_name, schema_name, max_output, schema_override)[0])

    def request(self, stage, data, prompt_name, schema_name, max_output=None, schema_override=None):
        phase = next((key for key, value in STAGES.items() if value == stage), None)
        require(phase is not None and prompt_name == phase + ".md" and schema_name == phase + ".schema.json",
                "recovery_stage_resource_mismatch")
        for name in (prompt_name, schema_name):
            require(base.digest(base.regular(PROMPTS / name)) == self.frozen_prompts.get(name)
                    and data.get("promptArtifacts", {}).get(name) == self.frozen_prompts.get(name),
                    "recovery_prompt_changed_after_freeze")
        instructions = base.regular(PROMPTS / prompt_name).decode()
        schema = copied(schema_override) if schema_override is not None else _schema(phase)
        request = {"model": base.MODEL, "store": False, "max_output_tokens": max_output or OUTPUT_CAPS[phase],
            "instructions": instructions, "input": base.canonical(data).decode(), "reasoning": {"effort": "low"},
            "text": {"format": {"type": "json_schema", "name": stage, "strict": True, "schema": schema}}}
        raw = base.canonical(request)
        require(len(raw) <= 2 * 1024 * 1024, "recovery_request_size_exceeded")
        return raw, schema, base.digest(instructions.encode())


def _envelope(context):
    return {"schemaVersion": VERSION, "context": minimal_context(context), "promptArtifacts": prompt_artifacts()}


def _call(client, phase, data, schema):
    kwargs = {"max_output": OUTPUT_CAPS[phase], "schema_override": schema}
    digest = client.request_digest(STAGES[phase], data, phase + ".md", phase + ".schema.json", **kwargs)
    reply = client.call(STAGES[phase], data, phase + ".md", phase + ".schema.json", **kwargs)
    return digest, reply


def _normalized_rows(reply, field, expected):
    value = reply.get(field)
    if type(value) is dict:
        require(set(value) == set(expected) and all(type(v) is dict and v.get("issueId", v.get("targetId")) == k
                for k, v in value.items()), "recovery_output_coverage_mismatch")
        return [copied(value[key]) for key in expected]
    require(type(value) is list, "recovery_output_array_missing")
    keys = [row.get("issueId", row.get("targetId")) for row in value]
    require(len(keys) == len(set(keys)) and set(keys) == set(expected), "recovery_output_coverage_mismatch")
    by_id = dict(zip(keys, value))
    return [copied(by_id[key]) for key in expected]


def _preserve_conditions(text, quotes, kind=None):
    for quote in quotes:
        # Negative guards only. Translated units, unrelated facts in the same
        # paragraph and semantic scope remain the independent verifier's job.
        families = ((r"약|대략|approximately|about|around", r"약|대략|가량|내외|안팎|정도|approximately|about|around"),
                    (r"최대|up\s+to|at\s+most", r"최대|이하|상한|이내|up\s+to|at\s+most"),
                    (r"최소|at\s+least", r"최소|이상|하한|적어도|at\s+least"))
        for markers, translations in families:
            for match in re.finditer(r"(?:" + markers + r")\s*(?:US\$|\$|USD\s*)?([\d][\d,.]*)\s*(%|억|조|원|달러|명|개|건|billion|million)?", quote, re.I):
                number, unit = match.groups()
                numeric = re.escape(number.replace(",", ""))
                same_quantity = re.search(r"(?<![\d.])" + numeric + r"(?![\d.])\s*" + (re.escape(unit) if unit else ""),
                                          text.replace(",", ""), re.I)
                if same_quantity:
                    require(re.search(translations, text, re.I) is not None, "recovery_quantified_condition_omitted")
        text_is_future = re.search(r"예정|계획|추진|검토|목표|plans?\s+to|scheduled|expects?\s+to|intends?\s+to", text, re.I)
        completed = re.search(r"완료했|체결했|출시했|착공했|준공했|공급했|시작했|완료됐|체결됐|출시됐|준공됐", text)
        if completed and not text_is_future:
            # Do not mechanically compare English plans elsewhere in a quote
            # with a translated Korean completed fact. Reject only the same
            # literal Korean action explicitly marked as future in its source.
            completion_root = completed.group()[:2]
            source_future = re.search(re.escape(completion_root) + r"(?:을|를)?\s*(?:할|될|하기로|되는|하는)?\s*(?:예정|계획)", quote)
            source_completed = re.search(re.escape(completion_root) + r"(?:했|됐)", quote)
            require(not source_future or source_completed is not None, "recovery_plan_changed_to_completed_fact")


_MONEY_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MONEY_KOREAN = _MONEY_NUMBER + r"\s*[조억만천](?:\s*" + _MONEY_NUMBER + r"\s*[조억만천])*"
_MONEY_AMOUNT = r"(?:" + _MONEY_KOREAN + r"|" + _MONEY_NUMBER + r"(?:\s*(?:trillion|billion|million|thousand|bn))?)"
_MONEY_PREFIX = r"(?:US\$|U\.S\.\$|NT\$|USD(?![A-Za-z])|KRW(?![A-Za-z])|EUR(?![A-Za-z])|TWD(?![A-Za-z])|\$|€)"
_MONEY_SUFFIX = (r"(?:New\s+Taiwan(?:ese)?\s+dollars?|Taiwan(?:ese)?\s+dollars?|신\s*타이완\s*달러|"
    r"대만\s*달러|타이완\s*달러|U\.?S\.?\s*dollars?|미국\s*달러|미\s*달러|"
    r"South\s+Korean\s+won|Korean\s+won|won|원|euros?|유로|USD|KRW|EUR|TWD|dollars?|달러)(?![A-Za-z])")
_MONEY_SCALES = {"trillion": Decimal(10) ** 12, "billion": Decimal(10) ** 9,
    "bn": Decimal(10) ** 9, "million": Decimal(10) ** 6, "thousand": Decimal(10) ** 3,
    "조": Decimal(10) ** 12, "억": Decimal(10) ** 8, "만": Decimal(10) ** 4, "천": Decimal(10) ** 3}


def _money_currency(label):
    label = re.sub(r"\s+|\.", "", label).casefold()
    if label in {"nt$", "twd"} or "taiwan" in label or "타이완" in label or "대만" in label:
        return "TWD"
    if label in {"us$", "usd", "us$dollars", "usdollars"} or "미국" in label or label == "미달러":
        return "USD"
    if label in {"krw", "원", "won", "koreanwon", "southkoreanwon"}:
        return "KRW"
    if label in {"eur", "€", "euro", "euros", "유로"}:
        return "EUR"
    # Unqualified dollars do not establish USD versus TWD or another dollar.
    return "DOLLAR" if label in {"$", "dollar", "dollars", "달러"} else None


def _money_amount(value):
    value = value.strip()
    try:
        if re.search(r"[조억만천]", value):
            parts = list(re.finditer(r"(" + _MONEY_NUMBER + r")\s*([조억만천])", value))
            if not parts or re.sub(r"\s+", "", re.sub(r"(" + _MONEY_NUMBER + r")\s*([조억만천])", "", value)):
                return None
            scales = [_MONEY_SCALES[p.group(2)] for p in parts]
            if any(left <= right for left, right in zip(scales, scales[1:])):
                return None
            return sum((Decimal(p.group(1).replace(",", "")) * scale for p, scale in zip(parts, scales)), Decimal(0))
        match = re.fullmatch(r"(" + _MONEY_NUMBER + r")(?:\s*(trillion|billion|million|thousand|bn))?", value, re.I)
        if match:
            return Decimal(match.group(1).replace(",", "")) * _MONEY_SCALES.get((match.group(2) or "").lower(), Decimal(1))
    except InvalidOperation:
        pass
    return None


def _money_ambiguous(text, start, end):
    before, after = text[max(0, start - 60):start], text[end:end + 40]
    # Ranges, exchange-rate denominators, percentages and dates are not silently
    # converted into a single exact monetary amount. Their semantics stay with
    # the independent fact verifier.
    range_before = r"(?:\d[\d,.]*\s*(?:조|억|만|천|trillion|billion|million)?\s*(?:~|–|—|-|to|and|에서)\s*)$"
    return bool(re.search(range_before, before, re.I) or re.search(r"\bbetween\s*$", before, re.I)
        or re.match(r"\s*(?:~|–|—|-|to\b|and\b|에서)\s*\d", after, re.I)
        or re.search(r"(?:/|당|\bper)\s*$", before, re.I)
        or re.match(r"\s*(?:/|당|per\b|[%％]|년|월|일)", after, re.I)
        or re.search(r"[-−]\s*$", before))


def currency_quantities(text):
    """Recognize explicit supported-currency amounts using exact Decimal math.

    This is a negative guard, not an FX converter or a complete natural-language
    parser. Unsupported/ambiguous forms are omitted rather than guessed.
    """
    result, covered = [], []
    patterns = (
        re.compile(r"(?<![\w.,])(?P<prefix>" + _MONEY_PREFIX + r")\s*(?P<amount>" + _MONEY_AMOUNT
            + r")(?!\s*(?:[조억만천백십\d]|trillion|billion|million|thousand|bn|[%％]|년|월|일))"
            + r"(?:\s*(?P<suffix>" + _MONEY_SUFFIX + r"))?(?![A-Za-z\d]|[.,]\d)", re.I),
        re.compile(r"(?<![\d.,])(?P<amount>" + _MONEY_AMOUNT + r")\s*(?P<suffix>" + _MONEY_SUFFIX + r")", re.I))
    for pattern in patterns:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < right and end > left for left, right in covered):
                continue
            covered.append((start, end))
            if _money_ambiguous(text, start, end):
                continue
            prefix, suffix = match.groupdict().get("prefix"), match.groupdict().get("suffix")
            first = _money_currency(prefix) if prefix else None
            second = _money_currency(suffix) if suffix else None
            if first and second and first != second and "DOLLAR" not in {first, second}:
                continue
            currency = second if first in {None, "DOLLAR"} else first
            amount = _money_amount(match.group("amount"))
            if currency is not None and amount is not None:
                result.append({"currency": currency, "value": amount, "start": start, "end": end})
    return sorted(result, key=lambda value: value["start"])


def _preserve_currency_quantities(text, quotes):
    wanted = currency_quantities(text)
    observed = [amount for quote in quotes for amount in currency_quantities(quote)]
    if not wanted or not observed:
        return
    dollars = {"USD", "TWD", "DOLLAR"}
    for amount in wanted:
        def compatible(other):
            return amount["currency"] == other["currency"] or ("DOLLAR" in {amount["currency"], other["currency"]}
                and amount["currency"] in dollars and other["currency"] in dollars)
        require(any(compatible(other) and amount["value"] == other["value"] for other in observed),
                "recovery_currency_quantity_not_supported")


def validate_item(draft, selection):
    """Validate without rewriting the provider's words; one claim is sufficient."""
    source = prepare_selections([selection])[0]
    template = _schema("generation")["properties"]["items"]["items"]
    base.validate_schema(draft, template)
    require(draft["issueId"] == source["issueId"] and draft["rank"] == 1, "recovery_item_identity_or_rank_changed")
    require(1 <= len(draft["claims"]) <= 3, "recovery_item_claim_count_invalid")
    by_id = {s["evidenceId"]: s for s in source["sources"]}
    checks = [(draft["title"], draft["titleEvidenceIds"], None)] + [(c["text"], c["evidenceIds"], c["type"]) for c in draft["claims"]]
    for text, ids, kind in checks:
        require(ids and len(ids) == len(set(ids)) and set(ids).issubset(by_id), "recovery_foreign_or_missing_citation")
        require("\n" not in text and not re.search(r"(?:다[.!?]|요[.!?]|[。！？])\s+\S", text), "recovery_multiple_sentences_in_claim")
        require(not re.search(r"매수|매도|목표가|수익.{0,3}보장|오늘|내일|금일|종가|장\s*마감|환율\s*마감", text),
                "recovery_unsupported_market_or_investment_advice")
        quotes = [by_id[key]["quote"] for key in ids]
        _preserve_conditions(text, quotes, kind)
        _preserve_currency_quantities(text, quotes)
    return copied(draft)


def generate_items(client, selections, context, prior_failures=None):
    safe = prepare_selections(selections, context)
    if not safe:
        return {"requestDigest": None, "rawReply": None, "items": [], "perIssueStatuses": {}, "failures": {}}
    failures = prior_failures if type(prior_failures) is dict else {}
    # Only machine codes for these missing items are repair hints. Never copy a
    # previous verifier's prose, old generated text, or normal items into input.
    hints = {}
    for selection in safe:
        key, value = selection["issueId"], failures.get(selection["issueId"])
        codes = [value] if type(value) is str else value.get("codes", []) if type(value) is dict else []
        if type(codes) is list:
            hints[key] = [code for code in codes if type(code) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", code)]
        if not hints.get(key):
            hints.pop(key, None)
    data = {**_envelope(context), "selections": safe, "priorFailures": hints}
    rows = [(s["issueId"], {
        ("properties", "titleEvidenceIds", "items"): [v["evidenceId"] for v in s["sources"]],
        ("properties", "claims", "items", "properties", "evidenceIds", "items"): [v["evidenceId"] for v in s["sources"]]}) for s in safe]
    digest, reply = _call(client, "generation", data, _keyed_schema("generation", "items", rows, "issueId"))
    items = _normalized_rows(reply, "items", [s["issueId"] for s in safe])
    accepted, statuses, problems = [], {}, {}
    for selection, item in zip(safe, items):
        try:
            accepted.append(validate_item(item, selection))
            statuses[item["issueId"]] = "PASS"
        except ReplayError as error:
            statuses[item["issueId"]], problems[item["issueId"]] = "WITHHELD", str(error)
    return {"requestDigest": digest, "rawReply": reply, "items": accepted,
            "perIssueStatuses": statuses, "failures": problems}


def verify_items(client, selections, drafts, context):
    safe = prepare_selections(selections, context)
    require(type(drafts) is list, "recovery_drafts_array_required")
    allowed = {s["issueId"]: s for s in safe}
    by_id = {}
    for draft in drafts:
        require(type(draft) is dict and draft.get("issueId") in allowed and draft["issueId"] not in by_id,
                "recovery_foreign_or_duplicate_draft")
        by_id[draft["issueId"]] = draft
    targets, inputs, statuses, failures = {}, [], {}, {}
    for selection in safe:
        key = selection["issueId"]
        try:
            require(key in by_id, "recovery_draft_missing")
            draft = validate_item(by_id[key], selection)
        except ReplayError as error:
            statuses[key], failures[key] = "WITHHELD", str(error)
            continue
        inputs.append({"issueId": key, "draft": draft, "sources": selection["sources"]})
        targets[key + ":title"] = (key, draft["title"])
        for index, claim in enumerate(draft["claims"]):
            targets[key + ":claim:" + str(index)] = (key, claim["text"])
        statuses[key] = "PASS"
    if not inputs:
        return {"requestDigest": None, "rawReply": None, "checks": [], "perIssueStatuses": statuses, "failures": failures}
    data = {**_envelope(context), "items": inputs}
    schema = _keyed_schema("verification", "checks", [(key, {}) for key in targets], "targetId")
    digest, reply = _call(client, "verification", data, schema)
    checks = _normalized_rows(reply, "checks", list(targets))
    for check in checks:
        key, text = targets[check["targetId"]]
        problem = None
        if check["checkedText"] != text:
            problem = "recovery_verifier_checked_text_mismatch"
        elif check["unsupportedSpan"] is not None and (not check["unsupportedSpan"] or check["unsupportedSpan"] not in text):
            problem = "recovery_verifier_invented_unsupported_span"
        elif check["verdict"] != "SUPPORTED" or not all(check["flags"][name] for name in FLAGS):
            problem = "recovery_fact_verification_failed"
        elif check["unsupportedSpan"] is not None:
            problem = "recovery_supported_check_has_unsupported_span"
        if problem:
            statuses[key], failures[key] = "WITHHELD", problem
    return {"requestDigest": digest, "rawReply": reply, "checks": checks,
            "perIssueStatuses": statuses, "failures": failures}


def assess_novelty(client, selections, history, context):
    safe = prepare_selections(selections, context)
    require(type(history) is list, "recovery_history_array_required")
    safe_context = minimal_context(context)
    prior = []
    for row in history:
        require(type(row) is dict and _text(row.get("issueId")) and type(row.get("sources")) is list,
                "recovery_history_identity_invalid")
        require(row["sources"], "recovery_history_sources_missing")
        prior.append({"issueId": row["issueId"], "sources": [_source(s, safe_context["window"], history=True) for s in row["sources"]]})
    if not safe or not prior:
        decisions = [{"issueId": s["issueId"], "decision": "NEW", "reason": "No prior published raw-evidence history was supplied.",
                      "deltaEvidenceIds": []} for s in safe]
        return {"requestDigest": None, "rawReply": None, "decisions": decisions, "decisionSource": "server_empty_history",
                "perIssueStatuses": {s["issueId"]: "PASS" for s in safe}, "failures": {}}
    data = {**_envelope(context), "selections": [{"issueId": s["issueId"], "sources": s["sources"]} for s in safe],
            "history": prior}
    schema = _keyed_schema("novelty", "decisions", [(s["issueId"], {}) for s in safe], "issueId")
    digest, reply = _call(client, "novelty", data, schema)
    decisions = _normalized_rows(reply, "decisions", [s["issueId"] for s in safe])
    statuses, failures = {}, {}
    old_quotes = {source["quote"] for row in prior for source in row["sources"]}
    for selection, decision in zip(safe, decisions):
        key, ids = selection["issueId"], decision["deltaEvidenceIds"]
        evidence = {s["evidenceId"]: s for s in selection["sources"]}
        problem = None
        if len(ids) != len(set(ids)) or not set(ids).issubset(evidence):
            problem = "recovery_novelty_foreign_or_duplicate_delta"
        elif decision["decision"] == "MATERIAL_UPDATE" and (not ids or not any(evidence[i]["quote"] not in old_quotes for i in ids)):
            problem = "recovery_novelty_update_without_new_evidence"
        elif decision["decision"] in {"REPEAT", "UNCERTAIN"}:
            problem = "recovery_novelty_" + decision["decision"].lower()
        if problem:
            statuses[key], failures[key] = "WITHHELD", problem
        else:
            statuses[key] = "PASS"
    return {"requestDigest": digest, "rawReply": reply, "decisions": decisions, "decisionSource": "model",
            "perIssueStatuses": statuses, "failures": failures}
