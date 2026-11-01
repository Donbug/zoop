"""Native, pure S2-2 analysis rules: article projection, request identities, authored-replay parsing and grounding, SAME rules.

No I/O, network, model or repository is touched. A replay response is an authored answer looked up by the exact digest of
the request it answers; it is validated against the strict contracts of `extraction_contracts` and is not AI inference. A live
job answers the same requests through the provider runtime and is parsed, grounded and ruled by exactly these functions.
`ADAPTER_VERSION` and `LIVE_ADAPTER_VERSION` both cover everything below that changes a stored identity or verdict: the article
projection, the request preimages, quote resolution, strict parsing/grounding and the effective/disposition rules. Change one, bump both.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from pydantic import ValidationError

from .extraction_contracts import (ADAPTER_VERSION, ARTICLE_PROJECTION, CANDIDATE_VERSION, REPLAY_FORMAT, AnalysisReplay, Article, Catalogue,
    Extraction, ExtractionFailure, Mention, PairDecision, Provenance, ReplyInvalid, digest)

# ---------------------------------------------------------------- replay fixture -----------------------------------


def identity(doc: Any, provenance: Provenance, prompt_version: str) -> dict:
    """Header-only check that decides what the job is bound to. Records are validated later (`index`), before any call is reserved."""
    if (not isinstance(doc, dict) or doc.get("format") != REPLAY_FORMAT or type(doc.get("synthetic")) is not bool
            or doc.get("recordingKind") != "authored-test" or not isinstance(doc.get("records"), list)):
        raise ExtractionFailure("replay_fixture_invalid")
    if doc["synthetic"] != (provenance.source_kind == "synthetic"):
        raise ExtractionFailure("replay_provenance_conflict")
    if doc.get("promptVersion") != prompt_version:
        raise ExtractionFailure("replay_prompt_version_conflict")
    if not isinstance(doc.get("analysisVersion"), str) or not doc["analysisVersion"]:
        raise ExtractionFailure("replay_fixture_invalid")
    return {"format": REPLAY_FORMAT, "synthetic": doc["synthetic"], "recordingKind": "authored-test", "promptVersion": prompt_version,
            "analysisVersion": doc["analysisVersion"]}


def index(doc: dict) -> dict[tuple[str, str], Any]:
    """Authored responses by (stage, request digest). The whole fixture must be valid, including duplicates."""
    try:
        replay = AnalysisReplay.model_validate(doc)
    except ValidationError as exc:
        raise ExtractionFailure("replay_fixture_invalid") from exc
    return {(r.stage, r.request_digest): r.response for r in replay.records}


def request_digest(stage: str, request: dict, analysis_version: str) -> str:
    return digest({"stage": stage, "input": request, "version": analysis_version})


# ---------------------------------------------------------------- Article / binding --------------------------------

def article(export: dict, synthetic: bool) -> Article:
    """Authorized ingestion export -> analysed text. No publisher or language claim and no model transmission is authorized."""
    o, d = export["observation"], export["document"]
    return Article(article_id=o["documentId"], url=o["url"], title=o["title"], body=d["text"], publisher="", published_at=o["publishedAt"],
                   language=o.get("language") or "und", input_kind=d["inputKind"], origin_id=None, withdrawn=False, allow_model_send=False, synthetic=synthetic)


def bind(export: dict, projected: Article) -> dict:
    """Immutable outer binding. Article.version is genuine and deliberately not a substitute for these fields."""
    o, d, m = export["observation"], export["document"], export["locatorMetadata"]
    return {"observation": {k: o[k] for k in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")},
            "grant": export["grant"], "sourceHash": d["sourceHash"], "textArtifactId": d["textArtifactId"],
            "rawArtifactId": m["rawArtifactId"], "rawHash": m["rawHash"], "representationHash": m["representationHash"],
            "mappingHash": m["mappingHash"], "parserProfileDigest": digest(m["parserProfile"]), "locatorDigest": digest(d["rawLocators"]),
            "metadataDigest": digest({k: o[k] for k in ("url", "title", "publishedAt", "modifiedAt", "sourceRevision", "mediaType")}),
            "articleProjection": ARTICLE_PROJECTION, "articleVersion": projected.version}


# ---------------------------------------------------------------- request preimages and identities ----------------

def extract_input(projected: Article, prompt_version: str, catalogue: Catalogue) -> dict:
    companies = sorted(({"company_id": c.company_id, "name": c.name, "aliases": list(c.aliases), "ticker": c.ticker} for c in catalogue.companies),
                       key=lambda company: company["company_id"])
    return {"article": projected.model_dump(mode="json"), "article_version": projected.version, "companies": companies, "prompt_version": prompt_version}


def compare_input(mention: Mention, event_id: str, members: list[Mention], articles: list[Article], incoming: Article) -> dict:
    return {"mention": mention.model_dump(mode="json"),
            "issue": {"issue_id": event_id, "mentions": [m.model_dump(mode="json") for m in members], "articles": [a.model_dump(mode="json") for a in articles]},
            "article": incoming.model_dump(mode="json")}


def fingerprint(replay: dict, catalogue: Catalogue, adapter: str = ADAPTER_VERSION) -> str:
    """Identity of this analysis context, embedded in every candidate id. Native rules, authored/frozen labels and the exact catalogue.
    `replay` only needs promptVersion and analysisVersion; a live job passes its adapter version and its frozen runtime identity as analysisVersion."""
    return digest({"adapter": adapter, "candidate": CANDIDATE_VERSION, "promptVersion": replay["promptVersion"],
                   "analysisVersion": replay["analysisVersion"], "catalogue": digest(catalogue.wire())})


def mention_candidate_id(binding: dict, extract_key: str, fingerprint_: str, local_mention_id: str) -> str:
    return "mc-" + digest({"version": CANDIDATE_VERSION, "binding": digest(binding), "extractKey": extract_key,
                           "fingerprint": fingerprint_, "localMentionId": local_mention_id})


def event_candidate_id(mention_candidate: str) -> str:
    return "evc-" + digest({"version": CANDIDATE_VERSION, "mentionCandidate": mention_candidate})


# ---------------------------------------------------------------- strict parsing / grounding -----------------------

def company_names(catalogue: Catalogue) -> dict[str, set[str]]:
    """Only explicit names/aliases, casefolded with whitespace collapsed; punctuation and legal suffixes remain significant."""
    names: dict[str, set[str]] = {}
    for company in catalogue.companies:
        for name in (company.name, *company.aliases):
            key = " ".join(name.casefold().split())
            if key:
                names.setdefault(key, set()).add(company.company_id)
    return names


def participants_valid(mention: Mention, names: dict[str, set[str]]) -> bool:
    """A supplied ID needs exactly one matching master. Null remains unresolved, even when a unique alias exists."""
    return all(p.company_id is None or names.get(" ".join(p.name.casefold().split())) == {p.company_id}
               for p in mention.participants)


def member_mention(raw: dict, projected: Article, names: dict[str, set[str]]) -> Mention:
    """Snapshot member: exact source evidence and the same pinned-catalogue identity rule as a new extraction."""
    try:
        mention = Mention.model_validate(raw, strict=True)
    except ValidationError as exc:
        raise ExtractionFailure("snapshot_member_invalid") from exc
    if (mention.article_id, mention.article_version) != (projected.article_id, projected.version) or not mention.mention_id \
            or not mention.evidence or not all(e.matches(projected) for e in mention.evidence) or not participants_valid(mention, names):
        raise ExtractionFailure("snapshot_member_invalid")
    return mention


class _Unresolvable(ValueError):
    pass


def _resolve_quotes(value: Any, articles: list[Article]) -> Any:
    """Fill evidence offsets from literal quotes only. Identity and version are never repaired.

    A node with a `quote` needs a known (article_id, article_version) and a non-empty string quote. Exact integer offsets that
    already select the quote are kept; otherwise the quote must occur exactly once in the body and the offsets come from there."""
    sources = {(a.article_id, a.version): a for a in articles}
    result = copy.deepcopy(value)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if "quote" in node:
                article_id, version, quote = node.get("article_id"), node.get("article_version"), node["quote"]
                source = sources.get((article_id, version)) if isinstance(article_id, str) and isinstance(version, str) else None
                if source is None or not isinstance(quote, str) or not quote:
                    raise _Unresolvable("evidence requires a known source version and a nonempty exact quote")
                start, end = node.get("start"), node.get("end")
                if not (type(start) is int and type(end) is int and 0 <= start < end <= len(source.body) and source.body[start:end] == quote):
                    start = source.body.find(quote)
                    if start < 0:
                        raise _Unresolvable("evidence quote not found in the source body")
                    if source.body.find(quote, start + 1) >= 0:
                        raise _Unresolvable("a repeated evidence quote requires an exact disambiguating span")
                    node["start"], node["end"] = start, start + len(quote)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(result)
    return result


def parse_extraction(raw: Any, projected: Article, catalogue: Catalogue) -> Extraction:
    try:
        extraction = Extraction.model_validate(_resolve_quotes(raw, [projected]), strict=True)
        names = company_names(catalogue)
        ids: set[str] = set()
        for mention in extraction.mentions:
            if (mention.article_id, mention.article_version) != (projected.article_id, projected.version):
                raise _Unresolvable("extracted mention references a different source version")
            if not mention.evidence or not all(e.matches(projected) for e in mention.evidence):
                raise _Unresolvable("each extracted mention requires exact source evidence")
            if not mention.mention_id or mention.mention_id in ids:
                raise _Unresolvable("mention ids must be nonempty and unique")
            ids.add(mention.mention_id)
            if not participants_valid(mention, names):
                raise _Unresolvable("participant identity is not a unique name or alias in the pinned catalogue")
        return extraction
    except (ValidationError, _Unresolvable) as exc:
        raise ReplyInvalid("extraction_reply_invalid") from exc


def parse_comparison(raw: Any, mention: Mention, incoming: Article, articles: list[Article]) -> PairDecision:
    try:
        if (mention.article_id, mention.article_version) != (incoming.article_id, incoming.version):
            raise _Unresolvable("comparison mention source version mismatch")
        return PairDecision.model_validate(_resolve_quotes(raw, [incoming, *articles]), strict=True)
    except (ValidationError, _Unresolvable) as exc:
        raise ReplyInvalid("comparison_reply_invalid") from exc


# ---------------------------------------------------------------- SAME rules ---------------------------------------

def normalized(value: str | None) -> str:
    return " ".join(re.findall(r"[\w]+", (value or "").casefold()))


def incompatible(left: Mention, right: Mention) -> bool:
    """Known identity conflicts forbid SAME; absent or `unknown` values are never conflicts. Action is free text and stays semantic."""
    for field in ("period", "assertion_status", "event_time"):
        a, b = getattr(left, field), getattr(right, field)
        if a and b and a != "unknown" and b != "unknown" and normalized(a) != normalized(b):
            return True
    return False


def effective(mention: Mention, members: list[Mention], incoming: Article, decision: PairDecision, sources: list[tuple[str, Article]]) -> dict:
    """Event-membership rules applied to a parsed authored decision plus exact source-binding checks.

    `sources` is [(documentVersion, Article)] for the incoming article and every member article of this whole event.
    A parsed decision alone is never event-membership authority, and no member match grants a transitive union.
    """
    def result(relation: str, reason: str, rule: str | None, documents: list | None = None) -> dict:
        return {"relation": relation, "reason": reason, "rule": rule, "evidenceDocuments": documents or []}

    if decision.relation == "SAME" and any(incompatible(mention, member) for member in members):
        return result("DIFFERENT", "known event identity conflicts with an existing member", "all_member_incompatibility")
    articles = [a for _, a in sources]
    versions: list[str | None] = []
    for e in decision.evidence:
        matched = {v for v, a in sources if e.matches(a)}
        versions.append(next(iter(matched)) if len(matched) == 1 else None)
    if decision.relation in {"SAME", "FOLLOWS"}:
        if not decision.evidence or any(not any(e.matches(a) for a in articles) for e in decision.evidence):
            return result("HOLD", "comparison lacks exact source evidence", "evidence_missing")
        if decision.relation == "FOLLOWS" and not any(e.matches(incoming) for e in decision.evidence):
            return result("HOLD", "follow-up relation lacks evidence in incoming article", "follows_incoming_evidence_missing")
        if any(v is None for v in versions):
            # Same Article.version bound to two prepared versions: never choose the newest or first.
            return result("HOLD", "evidence source binding is ambiguous", "evidence_source_ambiguous")
    return result(decision.relation, decision.reason, None, versions)


def disposition(decisions: list[dict]) -> dict:
    """More than one SAME or any unresolved HOLD/CONFLICT prevents selecting a target event."""
    same = [d["targetEventId"] for d in decisions if d["effective"]["relation"] == "SAME"]
    follows = [d["targetEventId"] for d in decisions if d["effective"]["relation"] == "FOLLOWS"]
    held_by = [d["targetEventId"] for d in decisions if d["effective"]["relation"] in {"HOLD", "CONFLICT"}]
    if len(same) > 1:
        return {"status": "held", "reason": "multiple_same_events", "targetEventId": None, "sameTargets": same, "follows": follows, "heldBy": held_by}
    if held_by:
        return {"status": "held", "reason": "unresolved_identity_or_conflict", "targetEventId": None, "sameTargets": same, "follows": follows, "heldBy": held_by}
    if same:
        return {"status": "same-event-candidate", "reason": "single_grounded_same", "targetEventId": same[0], "sameTargets": same, "follows": follows, "heldBy": []}
    return {"status": "new-event-candidate", "reason": "no_same_in_frozen_snapshot", "targetEventId": None, "sameTargets": [], "follows": follows, "heldBy": []}
