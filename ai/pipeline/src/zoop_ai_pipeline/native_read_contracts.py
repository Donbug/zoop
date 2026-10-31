"""Closed, pure persistence readers for native S2 replay-1/live-2 and S3 policy-1.

Preimages are pinned by tests/fixtures/native_historical to the sealed 2026-10-31
source. Authority, store locks, result projections and downstream pins remain
with their existing owners. A readable historical binding grants no execution.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from .extraction_contracts import Article, ExtractionFailure, Mention, digest

S2_REPLAY = "zoop-extraction-native-replay-1"
S2_LIVE = "zoop-extraction-native-live-2"
S3_VERSIONS = {
    "producer": "zoop-relation-producer-1", "verifier": "zoop-relation-verifier-1",
    "impactProducer": "zoop-impact-producer-1", "impactVerifier": "zoop-impact-verifier-1",
    "policy": "zoop-relation-policy-1", "revalidationPolicy": "zoop-relation-revalidation-policy-1",
    "impactPolicy": "zoop-impact-policy-1",
}
_GENERATION = ("extract", "compare", "topic", "relation", "impact")
_VERIFY = ("verify-relation", "verify-impact")


def s2_historical(binding: dict) -> bool:
    adapter = binding.get("adapter")
    return isinstance(adapter, dict) and adapter.get("version") in {S2_REPLAY, S2_LIVE}


def s3_historical(binding: dict) -> bool:
    versions = binding.get("versions")
    return isinstance(versions, dict) and versions.get("policy") == S3_VERSIONS["policy"]


def _require(condition, code="job_binding_changed"):
    if not condition:
        raise ExtractionFailure(code)


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _keys(value, keys):
    _require(isinstance(value, dict) and set(value) == set(keys), "live_binding_mismatch")


def _endpoint(value):
    _require(isinstance(value, str), "live_binding_mismatch")
    parsed = urlsplit(value)
    _require(parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password
             and not parsed.query and not parsed.fragment and not value.endswith("/"), "live_binding_mismatch")
    _require(parsed.scheme == "https" or parsed.hostname in {"localhost", "127.0.0.1", "::1"}, "live_binding_mismatch")


def _funding(value):
    _keys(value, ("schemaVersion", "mode", "operationId", "accounts", "lifecycle", "requestTimeoutSeconds", "drainSeconds",
                  "cleanupSeconds", "minIntervalMilliseconds"))
    _require(value["schemaVersion"] == "zoop-operating-funding-1" and value["mode"] == "operating-metered-v1", "live_binding_mismatch")
    _require(isinstance(value["operationId"], str) and 1 <= len(value["operationId"]) <= 120, "live_binding_mismatch")
    _keys(value["accounts"], ("openai-compatible", "typesafe-native"))
    _require(all(isinstance(v, str) and 1 <= len(v) <= 200 for v in value["accounts"].values()), "live_binding_mismatch")
    for key, low, high in (("requestTimeoutSeconds", 10, 300), ("drainSeconds", 1, 604800),
                           ("cleanupSeconds", 1, 60), ("minIntervalMilliseconds", 1, 86400000)):
        _require(type(value[key]) is int and low <= value[key] <= high, "live_binding_mismatch")
    lifecycle = value["lifecycle"]
    _require(isinstance(lifecycle, dict), "live_binding_mismatch")
    if lifecycle.get("kind") == "explicit-stop":
        _keys(lifecycle, ("kind",))
    elif lifecycle.get("kind") == "deadline":
        _keys(lifecycle, ("kind", "until"))
        _require(datetime.fromisoformat(lifecycle["until"].replace("Z", "+00:00")).tzinfo is not None, "live_binding_mismatch")
    elif lifecycle.get("kind") == "frontier":
        _keys(lifecycle, ("kind", "setIds"))
        ids = lifecycle["setIds"]
        _require(isinstance(ids, list) and 1 <= len(ids) <= 100000
                 and all(isinstance(v, str) and 1 <= len(v) <= 200 for v in ids) and len(set(ids)) == len(ids), "live_binding_mismatch")
    else:
        raise ExtractionFailure("live_binding_mismatch")


def _runtime(value):
    """Check frozen metadata and its self-identity, without rebuilding prompts or opening its budget."""
    keys = {"version", "generation", "verifier", "stages", "pricing", "budget", "limits", "identity"}
    _require(isinstance(value, dict), "live_binding_mismatch")
    if "funding" in value:
        keys.add("funding")
        _funding(value["funding"])
    _keys(value, keys)
    _require(value["version"] in {"zoop-live-runtime-1", "zoop-live-runtime-1-production-1"}, "live_binding_mismatch")
    _require(value["identity"] == digest({k: v for k, v in value.items() if k != "identity"}), "live_binding_mismatch")
    profiled = value["version"] == "zoop-live-runtime-1-production-1"
    generation, verifier = value["generation"], value["verifier"]
    generation_keys = {"provider", "api", "endpoint", "endpointRevision", "model", "reasoningEffort", "maxOutputTokens"}
    _keys(generation, generation_keys | ({"productionProfile"} if profiled else set()))
    _endpoint(generation["endpoint"])
    _require(generation["provider"] == "openai-compatible" and generation["api"] == "chat.completions"
             and generation["model"] == "gpt-6-luna" and generation["reasoningEffort"] in {"none", "low", "medium", "high", "xhigh", "max"}
             and type(generation["maxOutputTokens"]) is int and 1000 <= generation["maxOutputTokens"] <= 100000
             and generation["endpointRevision"] == digest({"endpoint": generation["endpoint"]}), "live_binding_mismatch")
    _keys(verifier, ("provider", "api", "endpoint", "endpointRevision", "model", "adapterRevision", "adapterIdentity", "policy"))
    _endpoint(verifier["endpoint"])
    _require(verifier["provider"] == "typesafe-native" and verifier["api"] == "systemone" and verifier["model"] == "jev-1.14.0"
             and verifier["adapterRevision"] == "zoop-jev-pipeline-verify-1" and _hash(verifier["adapterIdentity"])
             and verifier["endpointRevision"] == digest({"api": verifier["api"], "endpoint": verifier["endpoint"]}), "live_binding_mismatch")
    _require(verifier["policy"] == {"choiceConfidence": 0.8, "choiceProbability": 0.9, "distributionTolerance": 0.02,
             "lowConfidence": {"claims": "insufficient", "effect": "uncertain", "target": "insufficient"}, "provisional": True}, "live_binding_mismatch")
    _keys(value["budget"], ("scope", "directoryIdentity", "unit"))
    _require(value["budget"]["scope"] == "directory" and value["budget"]["unit"] == "nanoUsd"
             and _hash(value["budget"]["directoryIdentity"]), "live_binding_mismatch")
    _require(value["limits"] == {"maxRequestBytes": 300000, "maxVerifierRequestBytes": 150000,
                                  "maxResponseBytes": 8388608, "inputOverheadTokens": 1024}, "live_binding_mismatch")
    pricing = {"asOf": "2026-10-21", "unit": "nanoUsdPerToken", "tier": "conservative-long",
               "sources": ["https://developers.openai.com/api/docs/pricing", "https://docs.typesafe.ai/models.md"],
               "gpt-6-luna": {"input": 200, "output": 750}, "jev-1.14.0": {"input": 42, "output": 0}}
    if profiled:
        _require("funding" in value and generation["productionProfile"] in {"background-v1", "latency-v1"}
                 and generation["endpoint"] == "https://api.openai.com/v1" and generation["reasoningEffort"] == "high"
                 and generation["maxOutputTokens"] == 24000 and value["funding"]["requestTimeoutSeconds"] == 300
                 and value["funding"]["minIntervalMilliseconds"] >= 6000, "live_binding_mismatch")
        pricing.update(asOf="2026-10-31", tier="reported-cache-categories-conservative-long", revision="zoop-production-cache-flex-pricing-1")
        pricing["gpt-6-luna"] = {"input": 500, "output": 750, "uncachedInput": 200, "cachedInput": 20, "cacheWrite30m": 250,
                                 "inputChargePolicy": "reported-disjoint-categories-30m-else-highest",
                                 "flex": {"uncachedInput": 100, "cachedInput": 10, "cacheWrite30m": 125, "output": 375}}
    _require(value["pricing"] == pricing, "live_binding_mismatch")
    _keys(value["stages"], (*_GENERATION, *_VERIFY))
    for stage, entry in value["stages"].items():
        if stage in _GENERATION:
            _keys(entry, {"purpose", "recipient", "provider", "promptVersion", "schemaDigest", "maxOutputTokens"}
                  | ({"reasoningEffort", "serviceTier", "compareCache"} if profiled else set()))
            _require(isinstance(entry["promptVersion"], str) and re.fullmatch(r"zoop-live-prompt-[a-f0-9]{24}", entry["promptVersion"])
                     and _hash(entry["schemaDigest"]), "live_binding_mismatch")
            provider, revision, maximum = "openai-compatible", generation["endpointRevision"], generation["maxOutputTokens"]
            if profiled:
                _require(entry["reasoningEffort"] == ("medium" if stage == "extract" else "high")
                         and entry["serviceTier"] == ("flex" if generation["productionProfile"] == "background-v1" else "default")
                         and entry["compareCache"] == ("source-breakpoints-30m" if stage == "compare" else None), "live_binding_mismatch")
        else:
            _keys(entry, ("purpose", "recipient", "provider", "promptVersion", "questionsDigest", "maxOutputTokens"))
            _require(entry["questionsDigest"] == verifier["adapterIdentity"]
                     and entry["promptVersion"] == "zoop-jev-pipeline-" + verifier["adapterIdentity"][:16], "live_binding_mismatch")
            provider, revision, maximum = "typesafe-native", verifier["endpointRevision"], None
        _require(entry["provider"] == provider and entry["recipient"] == provider + ":" + revision
                 and entry["purpose"] == "pipeline:" + stage and entry["maxOutputTokens"] == maximum, "live_binding_mismatch")


def _document(export, synthetic):
    o, d, m = export["observation"], export["document"], export["locatorMetadata"]
    article = Article(article_id=o["documentId"], url=o["url"], title=o["title"], body=d["text"], publisher="", published_at=o["publishedAt"],
                      language="ko", input_kind=d["inputKind"], origin_id=None, withdrawn=False, allow_model_send=False, synthetic=synthetic)
    binding = {"observation": {k: o[k] for k in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")},
               "grant": export["grant"], "sourceHash": d["sourceHash"], "textArtifactId": d["textArtifactId"],
               "rawArtifactId": m["rawArtifactId"], "rawHash": m["rawHash"], "representationHash": m["representationHash"],
               "mappingHash": m["mappingHash"], "parserProfileDigest": digest(m["parserProfile"]), "locatorDigest": digest(d["rawLocators"]),
               "metadataDigest": digest({k: o[k] for k in ("url", "title", "publishedAt", "modifiedAt", "sourceRevision", "mediaType")}),
               "articleProjection": "zoop-article-projection-1", "articleVersion": article.version}
    return article, binding


def validate_s2_historical_read(row, request, exports: dict) -> None:
    """Rebuild the whole historical binding from exact, freshly authorized exports."""
    try:
        stored = json.loads(row["binding"])
        _require(s2_historical(stored), "analysis_contract_changed")
        live = request.provenance.execution_mode == "live"
        mode, version = ("live", S2_LIVE) if live else ("replay", S2_REPLAY)
        _require(stored["adapter"]["version"] == version and set(stored) ==
                 {"adapter", mode, "catalogue", "incoming", "documents", "snapshot", "topic"}, "analysis_contract_changed")
        source = stored[mode]
        synthetic = request.provenance.source_kind == "synthetic"
        _require(source["promptVersion"] == request.prompt_version)
        if live:
            _require(set(source) == {"promptVersion", "analysisVersion", "runtime", "bindingDigest"})
            _runtime(source["runtime"])
            identity = source["runtime"]["identity"]
            _require(source["bindingDigest"] == identity and source["analysisVersion"] == "live-" + identity)
            input_digest = digest({"request": request.wire(), "liveBindingDigest": identity})
        else:
            _require(set(source) == {"format", "synthetic", "recordingKind", "promptVersion", "analysisVersion", "fixtureHash"})
            _require(source["format"] == "zoop-analysis-replay-1" and type(source["synthetic"]) is bool and source["synthetic"] == synthetic
                     and source["recordingKind"] == "authored-test" and isinstance(source["analysisVersion"], str) and source["analysisVersion"])
            identity = source["fixtureHash"]
            _require(_hash(identity))
            input_digest = digest({"request": request.wire(), "replayFixtureHash": identity})
        _require(row["job_id"] == request.job_id and row["input_digest"] == input_digest and row["replay_hash"] == identity)
        refs = {digest(request.incoming.wire()): request.incoming}
        for event in request.snapshot.events:
            for member in event.members:
                refs.setdefault(digest(member.observation.wire()), member.observation)
        _require(len(refs) <= 200 and set(exports) == set(refs))
        docs = {k: _document(exports[k], synthetic) for k in refs}
        incoming = digest(request.incoming.wire())
        groups, seen = [], set()
        for event in request.snapshot.events:
            members = []
            for member in event.members:
                key = digest(member.observation.wire())
                article, bound = docs[key]
                try:
                    mention = Mention.model_validate(member.mention, strict=True)
                except ValueError as exc:
                    raise ExtractionFailure("snapshot_member_invalid") from exc
                _require((mention.article_id, mention.article_version) == (article.article_id, article.version) and mention.mention_id
                         and mention.evidence and all(e.matches(article) for e in mention.evidence), "snapshot_member_invalid")
                member_id = (member.observation.document_version, mention.mention_id)
                _require(member.observation.document_version != request.incoming.document_version and member_id not in seen, "snapshot_member_invalid")
                seen.add(member_id)
                members.append({"binding": digest(bound), "mention": mention.model_dump(mode="json")})
            groups.append({"eventId": event.event_id, "revision": event.revision,
                           "digest": digest({"eventId": event.event_id, "revision": event.revision, "members": members})})
        fresh = {"adapter": {"version": version, "candidate": "zoop-event-candidate-1",
                            "fingerprint": digest({"adapter": version, "candidate": "zoop-event-candidate-1", "promptVersion": source["promptVersion"],
                                                   "analysisVersion": source["analysisVersion"], "catalogue": digest(request.catalogue.wire())})},
                 mode: source, "catalogue": {"revision": request.catalogue.revision, "digest": digest(request.catalogue.wire())},
                 "incoming": incoming, "documents": {k: docs[k][1] for k in sorted(docs)},
                 "snapshot": {"revision": request.snapshot.revision, "events": groups,
                              "digest": digest({"revision": request.snapshot.revision,
                                                "events": sorted([g["eventId"], g["revision"], g["digest"]] for g in groups)})},
                 "topic": request.topic.wire() if request.topic else None}
        for key, bound in stored["documents"].items():
            if fresh["documents"].get(key) != bound:
                raise ExtractionFailure("grant_revision_changed" if fresh["documents"].get(key, {}).get("grant") != bound["grant"] else "document_binding_changed")
        _require(fresh["adapter"] == stored["adapter"], "analysis_contract_changed")
        _require(fresh == stored)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ExtractionFailure("job_binding_changed") from exc


def validate_s3_historical_read(row, request, upstream_request, upstream_result, upstream_digest: str) -> None:
    """Validate policy-1 without creating a geography-aware execution context."""
    try:
        stored = json.loads(row["binding"])
        _require(stored["versions"] == S3_VERSIONS, "analysis_contract_changed")
        _require(row["job_id"] == request.job_id and row["input_digest"] == digest(request.wire()))
        _require(upstream_request.job_id == request.upstream.job_id and upstream_result["inputDigest"] == request.upstream.input_digest,
                 "upstream_input_mismatch")
        _require(upstream_request.provenance == request.provenance, "provenance_conflict")
        expected_adapter = S2_LIVE if request.provenance.execution_mode == "live" else S2_REPLAY
        _require(upstream_result["binding"]["adapter"]["version"] == expected_adapter)
        _require(len(upstream_result["binding"]["documents"]) <= 50, "document_limit_exceeded")
        fresh = {"schema": "zoop-relation-s3", "candidate": "zoop-relation-candidate-1", "impactCandidate": "zoop-impact-candidate-1",
                 "versions": S3_VERSIONS, "upstream": {"jobId": request.upstream.job_id, "inputDigest": request.upstream.input_digest,
                                                     "digest": upstream_digest}, "provenance": request.provenance.wire()}
        if request.provenance.execution_mode == "live":
            _runtime(stored["runtime"])
            fresh["runtime"] = stored["runtime"]
        _require(fresh["upstream"] == stored["upstream"], "upstream_changed")
        _require(fresh == stored)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ExtractionFailure("job_binding_changed") from exc
