"""One version-specific pure adapter over the installed, pinned investmate domain/ReplayModel contracts.

No repository, pipeline, graph, retrieval, network or live-model path is imported. ReplayModel here replays authored
responses; it is not independent AI inference. Fail closed when the pinned package or its analysis contract changes.
"""
from __future__ import annotations

import json
import tempfile
from importlib.metadata import distribution
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .extraction_contracts import (ADAPTER_VERSION, ANALYSIS_FINGERPRINT, ARTICLE_PROJECTION, CANDIDATE_VERSION,
    CONTEXT_REVISION, POC_COMMIT, Catalogue, ExtractionFailure, Provenance, ReplyInvalid, digest)

try:
    from investmate import prompts
    from investmate.domain import Article, Company, Extraction, IssueSnapshot, Mention, PairDecision, Settings
    from investmate.ports import CallLimitExceeded
    from investmate.providers import ModelResponseError, ReplayModel, ReplayResponseMissingError
    from investmate.search import incompatible
except ImportError:  # pragma: no cover - environment failure is reported by pin()
    prompts = None

MODEL_ERRORS = (ValueError, ModelResponseError) if prompts is not None else (ValueError,)


def pin() -> dict:
    """Installed package identity, direct-url commit and pure analysis contract fingerprint."""
    if prompts is None:
        raise ExtractionFailure("pinned_poc_unavailable")
    try:
        installed = distribution("investmate-poc")
        spec = find_spec("investmate")
        package = Path(installed.locate_file("investmate")).resolve()
        if spec is None or spec.origin is None or Path(spec.origin).resolve().parent != package or "InvestMateLogicTest" in str(package):
            raise ExtractionFailure("pinned_poc_unavailable")
        origin = json.loads(installed.read_text("direct_url.json") or "{}")
    except (ValueError, OSError) as exc:
        raise ExtractionFailure("pinned_poc_unavailable") from exc
    if origin.get("vcs_info", {}).get("commit_id") != POC_COMMIT:
        raise ExtractionFailure("pinned_poc_unavailable")
    if prompts.CONTEXT_REVISION != CONTEXT_REVISION or prompts.analysis_contract_fingerprint() != ANALYSIS_FINGERPRINT:
        raise ExtractionFailure("poc_contract_changed")
    return {"pocCommit": POC_COMMIT, "analysisFingerprint": ANALYSIS_FINGERPRINT, "contextRevision": CONTEXT_REVISION}


# ---------------------------------------------------------------- replay fixture -----------------------------------

def fixture_identity(doc: Any, provenance: Provenance, prompt_version: str) -> dict:
    if not isinstance(doc, dict) or doc.get("format") != "investmate-replay-v2" or type(doc.get("synthetic")) is not bool or not isinstance(doc.get("records"), list):
        raise ExtractionFailure("replay_fixture_invalid")
    if doc["synthetic"] != (provenance.source_kind == "synthetic"):
        raise ExtractionFailure("replay_provenance_conflict")
    if doc.get("prompt_version") != prompt_version:
        raise ExtractionFailure("replay_prompt_version_conflict")
    if any(not isinstance(doc.get(k), str) or not doc[k] for k in ("model_version", "embedding_version")) or not isinstance(doc.get("analysis_version", doc["model_version"]), str):
        raise ExtractionFailure("replay_fixture_invalid")
    return {"format": doc["format"], "synthetic": doc["synthetic"], "promptVersion": prompt_version, "modelVersion": doc["model_version"],
            "analysisVersion": doc.get("analysis_version", doc["model_version"]), "embeddingVersion": doc["embedding_version"]}


def replay_model(doc: dict, settings: Any):
    """Construct the real installed ReplayModel from an in-memory document (it only accepts a path)."""
    with tempfile.TemporaryDirectory(prefix="zoop-replay-") as directory:
        path = Path(directory) / "replay.json"
        path.write_text(json.dumps(doc), encoding="ascii")
        try:
            return ReplayModel(str(path), settings)
        except (ValueError, KeyError, TypeError) as exc:
            raise ExtractionFailure("replay_fixture_invalid") from exc


def request_key(stage: str, request_input: dict, analysis_version: str) -> str:
    return prompts.request_key(stage, request_input, analysis_version)


def recorded(doc: dict, analysis_version: str) -> dict[str, Any]:
    """Authored raw responses by exact request key (extract/compare only)."""
    return {request_key(r["stage"], r["input"], analysis_version): r["response"] for r in doc["records"] if r["stage"] in {"extract", "compare"}}


def single_record(identity: dict, stage: str, request_input: dict, response: Any) -> dict:
    """One-record replay used to revalidate a saved receipt through the production parser, with no fixture lookup."""
    return {"format": identity["format"], "synthetic": identity["synthetic"], "prompt_version": identity["promptVersion"],
            "model_version": identity["modelVersion"], "analysis_version": identity["analysisVersion"],
            "embedding_version": identity["embeddingVersion"],
            "records": [{"stage": stage, "input": request_input, "response": response}]}


# ---------------------------------------------------------------- Article / settings ------------------------------

def settings(prompt_version: str, catalogue: Catalogue):
    return Settings(prompt_version=prompt_version, companies=[
        Company(company_id=c.company_id, name=c.name, aliases=c.aliases, ticker=c.ticker) for c in catalogue.companies])


def article(export: dict, synthetic: bool):
    """Real investmate Article from authorized ingestion export. Publisher stays empty: no source-name claim."""
    o, d = export["observation"], export["document"]
    return Article(article_id=o["documentId"], url=o["url"], title=o["title"], body=d["text"], publisher="",
                   published_at=o["publishedAt"], collected_at=o["observedAt"], language="ko", input_kind=d["inputKind"],
                   origin_id=None, withdrawn=False, allow_model_send=False, synthetic=synthetic)


def bind(export: dict, projected: Any) -> dict:
    """Immutable outer binding. Article.version is genuine and deliberately not a substitute for these fields."""
    o, d, m = export["observation"], export["document"], export["locatorMetadata"]
    return {"observation": {k: o[k] for k in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")},
            "grant": export["grant"], "sourceHash": d["sourceHash"], "textArtifactId": d["textArtifactId"],
            "rawArtifactId": m["rawArtifactId"], "rawHash": m["rawHash"], "representationHash": m["representationHash"],
            "mappingHash": m["mappingHash"], "parserProfileDigest": digest(m["parserProfile"]), "locatorDigest": digest(d["rawLocators"]),
            "metadataDigest": digest({k: o[k] for k in ("url", "title", "publishedAt", "modifiedAt", "sourceRevision", "mediaType")}),
            "articleProjection": ARTICLE_PROJECTION, "articleVersion": projected.version}


def locators_containing(document: dict, start: int, end: int) -> list[str]:
    """Whole interval must lie inside one mapped run (same rule as S1 exact), never across removed/generated text."""
    return [r["locatorId"] for r in document["rawLocators"] if r["start"] <= start < end <= r["end"]]


# ---------------------------------------------------------------- identities --------------------------------------

def extraction_fingerprint(identity: dict, config: Any, catalogue_revision: str) -> str:
    return digest({"adapter": ADAPTER_VERSION, "candidate": CANDIDATE_VERSION, "pocCommit": POC_COMMIT, "analysis": ANALYSIS_FINGERPRINT,
                   "context": CONTEXT_REVISION, "promptVersion": identity["promptVersion"], "modelVersion": identity["modelVersion"],
                   "analysisVersion": identity["analysisVersion"], "settings": config.model_dump(mode="json"), "catalogueRevision": catalogue_revision})


def mention_candidate_id(binding: dict, extract_key: str, fingerprint: str, local_mention_id: str) -> str:
    return "mc-" + digest({"version": CANDIDATE_VERSION, "binding": digest(binding), "extractKey": extract_key,
                           "fingerprint": fingerprint, "localMentionId": local_mention_id})


def event_candidate_id(mention_candidate: str) -> str:
    return "evc-" + digest({"version": CANDIDATE_VERSION, "mentionCandidate": mention_candidate})


# ---------------------------------------------------------------- strict parsing / grounding -----------------------

def member_mention(raw: dict, projected: Any):
    """Snapshot member: strict Mention bound to the exact Article.version and literal body evidence."""
    try:
        mention = Mention.model_validate(raw, strict=True)
    except ValidationError as exc:
        raise ExtractionFailure("snapshot_member_invalid") from exc
    if (mention.article_id, mention.article_version) != (projected.article_id, projected.version) or not mention.mention_id \
            or not mention.evidence or not all(e.matches(projected) for e in mention.evidence):
        raise ExtractionFailure("snapshot_member_invalid")
    return mention


def _parse(call, code: str):
    try:
        return call()
    except ReplayResponseMissingError as exc:
        raise ExtractionFailure("replay_response_missing") from exc
    except CallLimitExceeded as exc:
        raise ExtractionFailure("replay_call_limit") from exc
    except (ValidationError, *MODEL_ERRORS) as exc:
        raise ReplyInvalid(code) from exc


def parse_extraction(model: Any, projected: Any, config: Any) -> Any:
    return _parse(lambda: model.extract(projected, config), "extraction_reply_invalid")


def parse_comparison(model: Any, mention: Any, group: Any, projected: Any) -> Any:
    return _parse(lambda: model.compare(mention, group, projected), "comparison_reply_invalid")


def extract_input(projected: Any, config: Any) -> dict:
    return prompts.request_input("extract", article=projected, settings=config)


def compare_input(mention: Any, group: Any, projected: Any) -> dict:
    return prompts.request_input("compare", mention=mention, issue=group, article=projected)


def issue_snapshot(event_id: str, mentions: list, articles: list):
    return IssueSnapshot(issue_id=event_id, mentions=mentions, articles=articles)


# ---------------------------------------------------------------- SAME rules outside Pipeline ---------------------

def effective(mention: Any, group: Any, projected: Any, decision: Any, sources: list[tuple[str, Any]]) -> dict:
    """Reapply the orchestration-level guards of investmate.pipeline._compare plus exact source-binding checks.

    `sources` is [(documentVersion, Article)] for the incoming article and every member article of this whole event.
    A raw ReplayModel.compare() result is never event-membership authority, and no member match grants a transitive union.
    """
    def result(relation: str, reason: str, rule: str | None, documents: list | None = None) -> dict:
        return {"relation": relation, "reason": reason, "rule": rule, "evidenceDocuments": documents or []}

    if decision.relation == "SAME" and any(incompatible(mention, member) for member in group.mentions):
        return result("DIFFERENT", "known event identity conflicts with an existing member", "all_member_incompatibility")
    articles = [a for _, a in sources]
    versions: list[str | None] = []
    for e in decision.evidence:
        matched = {v for v, a in sources if e.matches(a)}
        versions.append(next(iter(matched)) if len(matched) == 1 else None)
    if decision.relation in {"SAME", "FOLLOWS"}:
        if not decision.evidence or any(not any(e.matches(a) for a in articles) for e in decision.evidence):
            return result("HOLD", "comparison lacks exact source evidence", "evidence_missing")
        if decision.relation == "FOLLOWS" and not any(e.matches(projected) for e in decision.evidence):
            return result("HOLD", "follow-up relation lacks evidence in incoming article", "follows_incoming_evidence_missing")
        if any(v is None for v in versions):
            # Same Article.version bound to two prepared versions: never choose the newest or first.
            return result("HOLD", "evidence source binding is ambiguous", "evidence_source_ambiguous")
    return result(decision.relation, decision.reason, None, versions)


def disposition(decisions: list[dict]) -> dict:
    """Mirror Pipeline._work_snapshot selection: more than one SAME or any unresolved HOLD/CONFLICT prevents selection."""
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
