"""Wire models, limits, pure helpers and the strict bundle validator of the AI -> backend public graph HANDOFF bundle. No I/O.

The bundle is a versioned, immutable AI-side artifact. It is NOT an app graph version, is never activated here and never claims public
readiness: app import (document/text/hash verification, evidence registration, graph version row, activation, asOf policy) is the backend's.
Operator files (canonical registry, public decisions, app document bindings) are operator-owned inputs pinned by their exact file hashes.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from .extraction_contracts import ExtractionFailure, ObservationRef
from .ingestion_contracts import Wire, canonical, digest, timestamp

__all__ = ["ExtractionFailure", "canonical", "digest"]

SCHEMA = "zoop-ai-handoff-1"
BUNDLE_SCHEMA = "zoop-graph-handoff-bundle-1"
DECISIONS_SCHEMA = "zoop-public-decisions-1"
BINDINGS_SCHEMA = "zoop-app-document-bindings-1"
LEDGER_VERSION = "zoop-handoff-ledger-1"
POLICY = "zoop-public-projection-policy-1"
EVIDENCE_KIND = "graph-body-span"
OFFSET_UNIT = "unicode_code_point"
STRUCTURAL_BASIS_TYPES = ("SUPPLIES",)       # the only S3 type inside the PoC structural basis set (PRODUCES/SUPPLIES/USES/...); others are rejected
PUBLIC_TYPES = ("INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS")
TIME_PRECISIONS = ("year", "month", "day", "datetime", "unknown")

MAX_COMMAND = 65_536
MAX_OPERATOR_FILE = 4_000_000
MAX_SOURCES = 20
MAX_DECISIONS = 20_000
MAX_ISSUES = 2_000
MAX_RELATIONS = 10_000
MAX_EVIDENCE = 20_000
MAX_ARTICLES = 1_000
MAX_EXCLUSIONS = 20_000
MAX_BUNDLE = 6 * 1024 * 1024               # the whole export envelope must stay below the 8 MiB subprocess output bound the backend clients use
MAX_ATTEMPTS = 5

ID = r"^[A-Za-z0-9._:-]{1,200}$"
HASH = r"^[a-f0-9]{64}$"
RC = r"^rc-[a-f0-9]{64}$"
EVC = r"^evc-[a-f0-9]{64}$"
ARTICLE_ID = r"^doc-[a-f0-9]{64}$"
EVIDENCE_ID = r"^ev-[a-f0-9]{64}$"
SOURCE_EVIDENCE_ID = r"^ev-[a-f0-9]{32}$"

# What the PRODUCER confirmed (source side only) and what only the APP import can confirm. Nothing in the second list is claimed.
PRODUCER_CHECKS = (
    "s3_authority_current", "s2_upstream_pinned", "review_state_pinned", "operator_files_pinned", "provenance_observed_equals_declared",
    "evidence_exact_resolved_against_source_text", "app_binding_text_digest_equals_source_text", "bundle_schema_and_closure_validated",
    "artifact_written_and_hashed",
)
APP_IMPORT_PENDING = (
    "article_and_version_exist_in_app", "app_text_sha256_equals_binding", "app_text_span_hash_equals_evidence_quoteSha256",
    "article_title_url_publishedAt_equal_bundle", "company_ids_exist_in_app_catalog_with_equal_label",
    "evidence_rows_registered_in_app", "getEvidence_graph_evidence_path", "graph_version_row_and_activation", "asOf_policy",
)


# ---------------------------------------------------------------------------------------------- wire models ------------------------

class Pin(Wire):
    job_id: str = Field(pattern=ID)
    input_digest: str = Field(pattern=HASH)


class Upstream(Wire):
    job_id: str = Field(pattern=ID)
    input_digest: str = Field(pattern=HASH)
    digest: str = Field(pattern=HASH)


class SourcePin(Wire):
    relation: Pin
    upstream: Upstream
    review_digest: str = Field(pattern=HASH)


class Files(Wire):
    canonical: str = Field(pattern=HASH)
    decisions: str = Field(pattern=HASH)
    bindings: str = Field(pattern=HASH)


class Manifest(Wire):
    """The operator's explicit pin of everything a handoff may consume. `sourceKind` is a DECLARATION that must equal the observed provenance of
    every S3 job and S2 upstream (it can never upgrade a synthetic source into an actual one)."""
    schema_version: Literal["zoop-ai-handoff-1"]
    handoff_id: str = Field(pattern=ID)
    source_kind: Literal["synthetic", "actual"]
    policy_version: Literal["zoop-public-projection-policy-1"]
    sources: list[SourcePin] = Field(min_length=1, max_length=MAX_SOURCES)
    files: Files

    @model_validator(mode="after")
    def unique(self):
        if len({s.relation.job_id for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate relation job")
        return self


class Selector(Wire):
    schema_version: Literal["zoop-ai-handoff-1"]
    handoff_id: str = Field(pattern=ID)


class Span(Wire):
    """A reviewed text span, pinned by coordinates AND the hash of the exact text the reviewer saw."""
    document_id: str = Field(min_length=1, max_length=200)
    document_version: str = Field(pattern=HASH)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote_sha256: str = Field(pattern=HASH)


class Geography(Wire):
    """An explicit field verdict (the PoC's field ALLOW equivalent) for the event's country field. S2/S3 do NOT verify country fields, so this is the
    only verification there is; it is bound to the exact country set, never inferred from language, ticker, exchange or company."""
    classification: Literal["domestic", "international"]
    countries: list[str] = Field(min_length=1, max_length=10)
    evidence: list[Span] = Field(min_length=1, max_length=20)
    decision_ref: str = Field(pattern=ID)
    decision_version: str = Field(pattern=ID)


class Representative(Wire):
    upstream: Pin
    kind: Literal["event-candidate", "snapshot-event"]
    ref: str = Field(min_length=1, max_length=200)
    mention_id: str = Field(min_length=1, max_length=200)
    document_id: str = Field(min_length=1, max_length=200)
    document_version: str = Field(pattern=HASH)
    observation: ObservationRef


class CompanyDecision(Wire):
    canonical_id: str = Field(pattern=ID)
    public_id: str = Field(pattern=ID)
    label: str = Field(min_length=1, max_length=200)
    decision_ref: str = Field(pattern=ID)


class IssueDecision(Wire):
    canonical_id: str = Field(pattern=ID)
    public_id: str = Field(pattern=ID)
    geography: Geography
    representative: Representative | None
    decision_ref: str = Field(pattern=ID)


class Applicability(Wire):
    """A MANUAL operator assertion that the structural basis applies to this issue. It is not produced or validated by S3 relation/impact results; its
    `bindingDigest` pins the exact issue source events, basis relations (with their S3 review revision) and decision version it was reviewed against."""
    status: Literal["operator-asserted"]
    reviewer: str = Field(pattern=ID)
    decision_ref: str = Field(pattern=ID)
    decision_version: str = Field(pattern=ID)
    binding_digest: str = Field(pattern=HASH)


class BasisRef(Wire):
    job_id: str = Field(pattern=ID)
    relation_candidate_id: str = Field(pattern=RC)


class StructuralDecision(Wire):
    issue: str = Field(pattern=ID)
    company: str = Field(pattern=ID)
    applicability: Applicability
    basis: list[BasisRef] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def distinct(self):
        if len({(b.job_id, b.relation_candidate_id) for b in self.basis}) != len(self.basis):
            raise ValueError("duplicate basis relation")
        return self


class FollowsSource(Wire):
    upstream: Pin
    event_candidate_id: str = Field(pattern=EVC)
    target_event_id: str = Field(min_length=1, max_length=200)
    group_digest: str = Field(pattern=HASH)


class FollowsDecision(Wire):
    from_: str = Field(alias="from", pattern=ID)
    to: str = Field(pattern=ID)
    source: FollowsSource
    decision_ref: str = Field(pattern=ID)
    decision_version: str = Field(pattern=ID)


class Decisions(Wire):
    schema_version: Literal["zoop-public-decisions-1"]
    policy_version: Literal["zoop-public-projection-policy-1"]
    companies: list[CompanyDecision] = Field(max_length=MAX_DECISIONS)
    issues: list[IssueDecision] = Field(max_length=MAX_DECISIONS)
    structural: list[StructuralDecision] = Field(max_length=MAX_DECISIONS)
    follows: list[FollowsDecision] = Field(max_length=MAX_DECISIONS)

    @model_validator(mode="after")
    def unique(self):
        def dup(values: list) -> bool:
            return len(set(values)) != len(values)

        if (dup([c.canonical_id for c in self.companies]) or dup([c.public_id for c in self.companies])
                or dup([i.canonical_id for i in self.issues]) or dup([i.public_id for i in self.issues])
                or dup([(s.issue, s.company) for s in self.structural]) or dup([(f.from_, f.to) for f in self.follows])):
            raise ValueError("duplicate decision")
        if {c.public_id for c in self.companies} & {i.public_id for i in self.issues}:
            raise ValueError("company and issue public ids must be disjoint")
        return self


class Binding(Wire):
    """Server-owned: this exact source document version IS this app article version, whose stored UTF-8 text has this sha256 and is read in code points."""
    document_id: str = Field(min_length=1, max_length=200)
    document_version: str = Field(pattern=HASH)
    article_id: str = Field(pattern=ARTICLE_ID)
    article_version: str = Field(pattern=HASH)
    text_sha256: str = Field(pattern=HASH)
    offset_unit: Literal["unicode_code_point"]


class Bindings(Wire):
    schema_version: Literal["zoop-app-document-bindings-1"]
    bindings: list[Binding] = Field(max_length=MAX_DECISIONS)

    @model_validator(mode="after")
    def unique(self):
        if (len({(b.document_id, b.document_version) for b in self.bindings}) != len(self.bindings)
                or len({(b.article_id, b.article_version) for b in self.bindings}) != len(self.bindings)):
            raise ValueError("duplicate binding")
        return self


# ---------------------------------------------------------------------------------------------- pure helpers -----------------------

def app_evidence_id(article_id: str, article_version: str, start: int, end: int) -> str:
    """The proposed app graph-evidence id: the app's own `ev-`+sha256(canonical JSON) rule over a graph-specific preimage, so it can never collide with
    the S1 `{analysisId, evidenceId}` preimage, never aliases the S2 `ev-`+32hex id (which excludes documentId) and is stable across versions/retries."""
    return "ev-" + digest({"kind": EVIDENCE_KIND, "articleId": article_id, "articleVersion": article_version, "start": start, "end": end})


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def time_precision(value: str | None) -> str:
    """Precision of an event time by FORMAT only. A missing time is `unknown` (never midnight); an unsupported form is a ValueError."""
    if value is None:
        return "unknown"
    if len(value) == 4 and value.isascii() and value.isdigit():
        return "year"
    if len(value) == 7 and value[4] == "-":
        date.fromisoformat(value + "-01")
        return "month"
    if len(value) == 10:
        date.fromisoformat(value)
        return "day"
    if "T" in value:
        timestamp(value)
        return "datetime"
    raise ValueError("unsupported time form")


def countries_class(countries: list[str]) -> str:
    """`invalid` | `unknown` (empty) | `domestic` (exactly KR) | `international` (any non-KR country, KR+other included). Pure; never a heuristic."""
    if not countries:
        return "unknown"
    if any(len(c) != 2 or not (c.isascii() and c.isalpha() and c.isupper()) for c in countries):
        return "invalid"
    return "domestic" if set(countries) == {"KR"} else "international"


def content_digest(bundle: dict) -> str:
    return digest({key: bundle[key] for key in ("companies", "issues", "relations", "evidence", "articles")})


# ---------------------------------------------------------------------------------------------- bundle validator --------------------

def _bad(at: str):
    raise ExtractionFailure("handoff_bundle_invalid", {"at": at})


def _need(condition: bool, at: str) -> None:
    if not condition:
        _bad(at)


def _keys(value, keys: tuple, at: str) -> dict:
    _need(isinstance(value, dict) and set(value) == set(keys), at)
    return value


def _text(value, at: str, pattern: str | None = None, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    _need(isinstance(value, str) and (pattern is None or re.fullmatch(pattern, value) is not None), at)


def _list(value, at: str, maximum: int) -> list:
    _need(isinstance(value, list) and len(value) <= maximum, at)
    return value


def _int(value, at: str, minimum: int = 0) -> None:
    _need(type(value) is int and value >= minimum, at)


def _strings(value, at: str, pattern: str | None = None, maximum: int = 100_000) -> list:
    items = _list(value, at, maximum)
    for item in items:
        _text(item, at, pattern)
    return items

def _observation(value, at: str) -> None:
    ref = _keys(value, ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion"), at)
    for key in ("roundId", "sourceId", "documentId"):
        _text(ref[key], at)
        _need(bool(ref[key]), at)
    for key in ("rawVersion", "documentVersion"):
        _text(ref[key], at, HASH)
    _int(ref["page"], at)
    _int(ref["ordinal"], at)


def _source_event(value, at: str, upstreams: set) -> None:
    event = _keys(value, ("upstream", "kind", "ref", "mentionId", "documentId", "documentVersion", "observation"), at)
    up = _keys(event["upstream"], ("jobId", "inputDigest"), f"{at}.upstream")
    _text(up["jobId"], at, ID)
    _text(up["inputDigest"], at, HASH)
    _need((up["jobId"], up["inputDigest"]) in upstreams, f"{at}.upstreamClosure")
    _need(event["kind"] in ("event-candidate", "snapshot-event"), f"{at}.kind")
    _text(event["ref"], at, EVC if event["kind"] == "event-candidate" else None)
    _text(event["mentionId"], at)
    _need(bool(event["ref"]) and bool(event["mentionId"]), at)
    _text(event["documentId"], at, ID)
    _text(event["documentVersion"], at, HASH)
    _observation(event["observation"], f"{at}.observation")
    _need(event["observation"]["documentId"] == event["documentId"] and event["observation"]["documentVersion"] == event["documentVersion"],
          f"{at}.documentClosure")


def validate_bundle(bundle: dict) -> None:
    """Strict, closed validation of a bundle: exact key sets, types, patterns, referential closure, id formulas, counts and the content digest. Anything
    else is `handoff_bundle_invalid` (a damaged or hand-edited artifact), never a partial read."""
    _keys(bundle, ("schemaVersion", "handoffId", "manifestDigest", "provenance", "policy", "sources", "companies", "issues", "relations", "evidence",
                   "articles", "exclusions", "counts", "checks", "readiness", "digests"), "bundle")
    _need(bundle["schemaVersion"] == BUNDLE_SCHEMA, "schemaVersion")
    _text(bundle["handoffId"], "handoffId", ID)
    _text(bundle["manifestDigest"], "manifestDigest", HASH)
    prov = _keys(bundle["provenance"], ("declaredSourceKind", "observedSourceKind", "executionMode", "recordingKind"), "provenance")
    _need(prov["declaredSourceKind"] == prov["observedSourceKind"] and prov["declaredSourceKind"] in ("synthetic", "actual"), "provenance")
    _need(prov["executionMode"] == "replay" and prov["recordingKind"] == "authored-test", "provenance")
    policy = _keys(bundle["policy"], ("version", "files", "evidenceIdKind", "offsetUnit", "geography", "structural", "sequence"), "policy")
    _need(policy["version"] == POLICY and policy["evidenceIdKind"] == EVIDENCE_KIND and policy["offsetUnit"] == OFFSET_UNIT, "policy")
    for name, expected in (("geography", "operator-field-verdict"), ("structural", "manual-operator-review"),
                           ("sequence", "s2-comparison-with-operator-decision")):
        _need(policy[name] == expected, f"policy.{name}")
    files = _keys(policy["files"], ("canonical", "decisions", "bindings"), "policy.files")
    for value in files.values():
        _text(value, "policy.files", HASH)

    sources = _list(bundle["sources"], "sources", MAX_SOURCES)
    _need(len(sources) >= 1, "sources")
    jobs, upstreams, used_reviews = set(), set(), {}
    for s in sources:
        _keys(s, ("relation", "upstream", "reviewDigest", "policies", "reviewUsed", "audit"), "source")
        r = _keys(s["relation"], ("jobId", "inputDigest"), "source.relation")
        _text(r["jobId"], "source.relation", ID)
        _text(r["inputDigest"], "source.relation", HASH)
        u = _keys(s["upstream"], ("jobId", "inputDigest", "digest"), "source.upstream")
        _text(u["jobId"], "source.upstream", ID)
        _text(u["inputDigest"], "source.upstream", HASH)
        _text(u["digest"], "source.upstream", HASH)
        _text(s["reviewDigest"], "source.reviewDigest", HASH)
        versions = _keys(s["policies"], ("producer", "verifier", "impactProducer", "impactVerifier", "policy", "revalidationPolicy", "impactPolicy"), "source.policies")
        for value in versions.values():
            _text(value, "source.policies")
            _need(bool(value), "source.policies")
        used = set()
        for item in _list(s["reviewUsed"], "source.reviewUsed", MAX_RELATIONS):
            _need(isinstance(item, list) and len(item) == 2, "source.reviewUsed")
            _text(item[0], "source.reviewUsed", RC)
            _int(item[1], "source.reviewUsed", 1)
            _need(item[0] not in used, "source.reviewUsed.unique")
            used.add(item[0])
        audit = _keys(s["audit"], ("s3Relations", "eligibility", "reviewPending", "impactCandidates", "eligibleNotPublicByType"), "source.audit")
        for name in ("s3Relations", "reviewPending", "impactCandidates"):
            _int(audit[name], f"source.audit.{name}")
        eligibility = _keys(audit["eligibility"], ("eligible", "hold", "reject", "pending"), "source.audit.eligibility")
        for count in eligibility.values():
            _int(count, "source.audit.eligibility")
        _need(isinstance(audit["eligibleNotPublicByType"], dict), "source.audit.eligibleNotPublicByType")
        for kind, count in audit["eligibleNotPublicByType"].items():
            _text(kind, "source.audit.eligibleNotPublicByType", ID)
            _int(count, "source.audit.eligibleNotPublicByType")
        jobs.add(r["jobId"])
        upstreams.add((u["jobId"], u["inputDigest"]))
        used_reviews[r["jobId"]] = used
    _need(len(jobs) == len(sources), "sources.unique")

    evidence = {}
    for e in _list(bundle["evidence"], "evidence", MAX_EVIDENCE):
        _keys(e, ("id", "kind", "articleId", "articleVersion", "start", "end", "offsetUnit", "quoteSha256", "rawLocatorIds", "source"), "evidence")
        _text(e["id"], "evidence.id", EVIDENCE_ID)
        _need(e["kind"] == EVIDENCE_KIND and e["offsetUnit"] == OFFSET_UNIT, "evidence.kind")
        _text(e["articleId"], "evidence.articleId", ARTICLE_ID)
        _text(e["articleVersion"], "evidence.articleVersion", HASH)
        _int(e["start"], "evidence.start")
        _int(e["end"], "evidence.end", 1)
        _need(e["end"] > e["start"], "evidence.span")
        _text(e["quoteSha256"], "evidence.quoteSha256", HASH)
        _strings(e["rawLocatorIds"], "evidence.rawLocatorIds", maximum=1000)
        src = _keys(e["source"], ("documentId", "documentVersion", "rawVersion", "textArtifactId", "sourceEvidenceId", "inputKind"), "evidence.source")
        _text(src["documentId"], "evidence.source")
        _text(src["documentVersion"], "evidence.source", HASH)
        _text(src["rawVersion"], "evidence.source", HASH)
        _text(src["textArtifactId"], "evidence.source")
        _text(src["sourceEvidenceId"], "evidence.source", SOURCE_EVIDENCE_ID)
        _need(src["inputKind"] == "body", "evidence.source.inputKind")
        _need(e["id"] == app_evidence_id(e["articleId"], e["articleVersion"], e["start"], e["end"]), "evidence.idFormula")
        _need(e["id"] not in evidence, "evidence.unique")
        evidence[e["id"]] = e

    articles = {}
    for a in _list(bundle["articles"], "articles", MAX_ARTICLES):
        _keys(a, ("articleId", "articleVersion", "documentId", "documentVersion", "rawVersion", "title", "url", "publishedAt", "publicationPrecision",
                  "observations"), "article")
        _text(a["articleId"], "article.articleId", ARTICLE_ID)
        _text(a["articleVersion"], "article.articleVersion", HASH)
        _text(a["documentId"], "article")
        _text(a["documentVersion"], "article", HASH)
        _text(a["rawVersion"], "article", HASH)
        _text(a["title"], "article.title")
        _text(a["url"], "article.url")
        _text(a["publishedAt"], "article.publishedAt", nullable=True)
        # `datetime`: an instant; `day`: a calendar date `YYYY-MM-DD` (never widened to a midnight); `unknown`: none.
        _need((a["publicationPrecision"], a["publishedAt"] is None) in (("datetime", False), ("day", False), ("unknown", True)), "article.publicationPrecision")
        _need(a["publicationPrecision"] != "day" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", a["publishedAt"]) is not None, "article.publishedAt.day")
        observations = _list(a["observations"], "article.observations", 1000)
        _need(len(observations) >= 1, "article.observations")
        for o in observations:
            _keys(o, ("roundId", "sourceId", "page", "ordinal", "observedAt", "grant"), "observation")
            for name in ("roundId", "sourceId", "observedAt"):
                _text(o[name], "observation")
            _int(o["page"], "observation")
            _int(o["ordinal"], "observation")
            grant = _keys(o["grant"], ("grantId", "revision"), "observation.grant")
            _text(grant["grantId"], "observation.grant")
            _text(grant["revision"], "observation.grant")
        _need(observations == sorted({canonical(o): o for o in observations}.values(), key=canonical), "article.observations.unique")
        key = (a["articleId"], a["articleVersion"])
        _need(key not in articles, "articles.unique")
        articles[key] = a
    for e in evidence.values():
        article = articles.get((e["articleId"], e["articleVersion"]))
        _need(article is not None, "evidence.articleClosure")
        _need((article["documentId"], article["documentVersion"], article["rawVersion"]) ==
              tuple(e["source"][k] for k in ("documentId", "documentVersion", "rawVersion")), "evidence.documentClosure")
    _need(set(articles) == {(e["articleId"], e["articleVersion"]) for e in evidence.values()}, "articles.noOrphan")

    referenced: set[str] = set()

    def evidence_ids(value, at: str, minimum: int = 1) -> list:
        ids = _strings(value, at, EVIDENCE_ID)
        _need(len(ids) >= minimum and ids == sorted(set(ids)) and set(ids) <= set(evidence), at)
        referenced.update(ids)
        return ids

    companies = {}
    for c in _list(bundle["companies"], "companies", MAX_DECISIONS):
        _keys(c, ("id", "canonicalId", "label", "decisionRef"), "company")
        for name in ("id", "canonicalId", "decisionRef"):
            _text(c[name], "company", ID)
        _text(c["label"], "company.label")
        _need(c["id"] not in companies, "companies.unique")
        companies[c["id"]] = c

    issues = {}
    for i in _list(bundle["issues"], "issues", MAX_ISSUES):
        _keys(i, ("id", "canonicalId", "title", "action", "target", "eventTime", "timePrecision", "period", "assertionStatus", "geography", "evidenceIds",
                  "sourceEvents", "decisionRef", "representative"), "issue")
        _text(i["id"], "issue.id", ID)
        _text(i["canonicalId"], "issue", ID)
        _text(i["decisionRef"], "issue", ID)
        _text(i["title"], "issue.title")
        for name in ("action", "target", "eventTime", "period", "assertionStatus"):
            _text(i[name], f"issue.{name}", nullable=True)
        _need(i["timePrecision"] in TIME_PRECISIONS, "issue.timePrecision")
        geo = _keys(i["geography"], ("value", "decisionRef", "decisionVersion", "policyVersion", "countries", "verification", "evidenceIds", "basis"), "issue.geography")
        _need(geo["value"] in ("domestic", "international") and geo["policyVersion"] == POLICY, "issue.geography")
        _need(geo["verification"] == "operator-field-verdict", "issue.geography.verification")
        _text(geo["decisionRef"], "issue.geography", ID)
        _text(geo["decisionVersion"], "issue.geography", ID)
        _need(countries_class(_strings(geo["countries"], "issue.geography.countries", maximum=10)) == geo["value"], "issue.geography.class")
        evidence_ids(i["evidenceIds"], "issue.evidenceIds")
        evidence_ids(geo["evidenceIds"], "issue.geography.evidenceIds")
        _need(set(geo["evidenceIds"]) <= set(i["evidenceIds"]), "issue.geography.evidenceClosure")
        source_events = _list(i["sourceEvents"], "issue.sourceEvents", 1000)
        _need(bool(source_events), "issue.sourceEvents")
        for s in source_events:
            _source_event(s, "issue.sourceEvent", upstreams)
        _need(source_events == sorted({canonical(s): s for s in source_events}.values(), key=canonical), "issue.sourceEvents.unique")
        for s in source_events:
            o = s["observation"]
            _need(any((a["documentId"], a["documentVersion"], a["rawVersion"]) ==
                      (s["documentId"], s["documentVersion"], o["rawVersion"])
                      and any(all(ob[k] == o[k] for k in ("roundId", "sourceId", "page", "ordinal")) for ob in a["observations"])
                      for a in articles.values()), "issue.sourceEvent.articleClosure")
        basis = _list(geo["basis"], "issue.geography.basis", 1000)
        _need(len(basis) == len(source_events), "issue.geography.basisClosure")
        for b in basis:
            item = _keys(b, ("upstream", "kind", "ref", "mentionId", "documentId", "documentVersion", "observation", "countries"),
                         "issue.geography.basis")
            _source_event({k: v for k, v in item.items() if k != "countries"}, "issue.geography.basis", upstreams)
            _need(item["countries"] == geo["countries"], "issue.geography.basisCountries")
        _need([{k: v for k, v in b.items() if k != "countries"} for b in basis] == source_events, "issue.geography.basisClosure")
        if i["representative"] is not None:
            rep = _keys(i["representative"], ("upstream", "kind", "ref", "mentionId", "documentId", "documentVersion", "observation"),
                        "issue.representative")
            _source_event(rep, "issue.representative", upstreams)
            _need(rep in source_events, "issue.representativeClosure")
        _need(i["id"] not in issues and i["id"] not in companies, "issues.unique")
        issues[i["id"]] = i

    relation_ids = set()
    counts = {name: 0 for name in PUBLIC_TYPES}
    linked: dict[str, set] = {name: set() for name in ("issue", "company")}
    for r in _list(bundle["relations"], "relations", MAX_RELATIONS):
        _keys(r, ("id", "type", "source", "target", "role", "assertionStatus", "evidenceIds", "basis", "provenance", "decisionRef", "sourceRefs"), "relation")
        _text(r["id"], "relation.id", ID)
        _need(r["type"] in PUBLIC_TYPES and r["id"] not in relation_ids, "relation.type")
        relation_ids.add(r["id"])
        counts[r["type"]] += 1
        _need(r["source"] in issues, "relation.sourceClosure")
        _need(r["target"] in (issues if r["type"] == "FOLLOWS" else companies), "relation.targetClosure")
        _need(r["source"] != r["target"], "relation.self")
        linked["issue"].add(r["source"])
        if r["type"] == "FOLLOWS":
            linked["issue"].add(r["target"])
        else:
            linked["company"].add(r["target"])
        _text(r["role"], "relation.role", nullable=True)
        _text(r["assertionStatus"], "relation.assertionStatus", nullable=True)
        _text(r["decisionRef"], "relation.decisionRef", ID, nullable=True)
        evidence_ids(r["evidenceIds"], "relation.evidenceIds")
        basis = _list(r["basis"], "relation.basis", 2)
        _need((r["type"] == "STRUCTURALLY_RELATED_TO") == (len(basis) >= 1), "relation.basis")
        basis_refs = []
        for b in basis:
            _keys(b, ("sourceRelation", "relationKey", "relationType", "validFrom", "validUntil", "countries", "verifiedAt",
                      "sourceArticles", "evidenceIds"), "basis")
            src = _keys(b["sourceRelation"], ("jobId", "relationCandidateId"), "basis.sourceRelation")
            _text(src["jobId"], "basis.sourceRelation", ID)
            _text(src["relationCandidateId"], "basis.sourceRelation", RC)
            _need(src["jobId"] in jobs and src["relationCandidateId"] in used_reviews[src["jobId"]], "basis.sourceClosure")
            basis_refs.append(("s3-relation", src["jobId"], src["relationCandidateId"]))
            _text(b["relationKey"], "basis.relationKey", HASH)
            _need(b["relationType"] in STRUCTURAL_BASIS_TYPES, "basis.relationType")
            _text(b["verifiedAt"], "basis.verifiedAt")
            _text(b["validFrom"], "basis.validFrom", nullable=True)
            _text(b["validUntil"], "basis.validUntil", nullable=True)
            _strings(b["countries"], "basis.countries", maximum=10)
            ids = evidence_ids(b["evidenceIds"], "basis.evidenceIds")
            links = _list(b["sourceArticles"], "basis.sourceArticles", 1000)
            for link in links:
                _keys(link, ("articleId", "articleVersion"), "basis.sourceArticle")
                _text(link["articleId"], "basis.sourceArticle", ARTICLE_ID)
                _text(link["articleVersion"], "basis.sourceArticle", HASH)
                _need((link["articleId"], link["articleVersion"]) in articles, "basis.articleClosure")
            _need(links == [{"articleId": a, "articleVersion": v} for a, v in sorted({(evidence[ident]["articleId"], evidence[ident]["articleVersion"])
                                                                                      for ident in ids})], "basis.articleEvidenceClosure")
        refs = _list(r["sourceRefs"], "relation.sourceRefs", MAX_RELATIONS)
        _need(bool(refs), "relation.sourceRefs")
        reference_keys = []
        for ref in refs:
            _keys(ref, ("kind", "jobId", "id"), "relation.sourceRef")
            _text(ref["jobId"], "relation.sourceRef", ID)
            _text(ref["id"], "relation.sourceRef")
            _need(bool(ref["id"]), "relation.sourceRef")
            if r["type"] == "FOLLOWS":
                _need(ref["kind"] == "s2-comparison" and re.fullmatch(EVC[:-1] + r">.+", ref["id"]) is not None
                      and ref["jobId"] in {job for job, _ in upstreams}, "relation.sourceRef")
            else:
                _need(ref["kind"] == "s3-relation" and re.fullmatch(RC, ref["id"]) is not None and ref["jobId"] in jobs
                      and ref["id"] in used_reviews[ref["jobId"]], "relation.sourceRef")
            reference_keys.append((ref["kind"], ref["jobId"], ref["id"]))
        _need(len(set(reference_keys)) == len(refs), "relation.sourceRefs.unique")
        provenance = r["provenance"]
        preimage = {"type": r["type"], "source": r["source"], "target": r["target"]}
        if r["type"] == "INVOLVES":
            _need(_keys(provenance, ("origin", "s3SemanticValidation"), "relation.provenance") ==
                  {"origin": "s3-relation", "s3SemanticValidation": "independent-verifier-supported-all-claims"}, "relation.provenance")
            _need(r["decisionRef"] is None and r["role"] is None and not basis, "relation.involves")
        elif r["type"] == "STRUCTURALLY_RELATED_TO":
            _keys(provenance, ("origin", "s3SemanticValidation", "status", "reviewer", "decisionRef", "decisionVersion",
                               "bindingDigest", "basisEligibility"), "relation.provenance")
            _need(provenance["origin"] == "manual-operator-review" and provenance["s3SemanticValidation"] == "none"
                  and provenance["status"] == "operator-asserted"
                  and provenance["basisEligibility"] == "s3-independent-verifier-supported-all-claims", "relation.provenance")
            for name in ("reviewer", "decisionRef", "decisionVersion"):
                _text(provenance[name], "relation.provenance", ID)
            _text(provenance["bindingDigest"], "relation.provenance", HASH)
            _need(r["decisionRef"] == provenance["decisionRef"] and r["role"] is None and reference_keys == basis_refs, "relation.structural")
            preimage["basis"] = [b["relationKey"] for b in basis]
        else:
            _keys(provenance, ("origin", "s3SemanticValidation", "s2Relation", "evidenceGate", "groupDigest", "decisionRef",
                               "decisionVersion"), "relation.provenance")
            _need(provenance["origin"] == "s2-comparison-with-operator-decision" and provenance["s3SemanticValidation"] == "none"
                  and provenance["s2Relation"] == "FOLLOWS" and provenance["evidenceGate"] == "exact-source-citation-in-incoming-article",
                  "relation.provenance")
            _text(provenance["groupDigest"], "relation.provenance", HASH)
            _text(provenance["decisionRef"], "relation.provenance", ID)
            _text(provenance["decisionVersion"], "relation.provenance", ID)
            _need(r["decisionRef"] == provenance["decisionRef"] and r["role"] is None and r["assertionStatus"] is None
                  and len(refs) == 1 and not basis, "relation.follows")
        _need(r["id"] == "edge-" + digest(preimage), "relation.idFormula")
    _need(isinstance(bundle["counts"], dict) and counts == bundle["counts"].get("relations"), "counts.relations")
    _need(set(issues) == linked["issue"], "issues.noOrphan")
    _need(set(companies) == linked["company"], "companies.noOrphan")
    _need(set(evidence) == referenced, "evidence.noOrphan")

    ex = _keys(bundle["exclusions"], ("counts", "items"), "exclusions")
    items = _list(ex["items"], "exclusions.items", MAX_EXCLUSIONS)
    tally: dict[str, int] = {}
    for item in items:
        _need(isinstance(item, dict) and {"kind", "id", "jobId", "code"} <= set(item) <= {"kind", "id", "jobId", "code", "detail"}, "exclusion")
        _need(item["kind"] in ("issue", "relation", "structural", "follows"), "exclusion.kind")
        _text(item["id"], "exclusion.id")
        _text(item["jobId"], "exclusion.jobId", ID, nullable=True)
        _text(item["code"], "exclusion.code", ID)
        if "detail" in item:
            if item["code"] == "issue_metadata_conflict":
                detail = _keys(item["detail"], ("fields",), "exclusion.detail")
                fields = _strings(detail["fields"], "exclusion.detail.fields")
                _need(bool(fields) and len(fields) == len(set(fields)) and set(fields) <=
                      {"title", "action", "target", "eventTime", "period", "assertionStatus"}, "exclusion.detail.fields")
            elif item["code"] == "applicability_binding_mismatch":
                detail = _keys(item["detail"], ("expectedBindingDigest",), "exclusion.detail")
                _text(detail["expectedBindingDigest"], "exclusion.detail.expectedBindingDigest", HASH)
            else:
                _bad("exclusion.detail")
        tally[item["code"]] = tally.get(item["code"], 0) + 1
    _need(ex["counts"] == tally, "exclusions.counts")
    expected = {"companies": len(companies), "issues": len(issues), "relations": counts, "evidence": len(evidence), "articles": len(articles),
                "exclusions": len(items)}
    _need(bundle["counts"] == expected, "counts")
    checks = _keys(bundle["checks"], ("producerConfirmed", "appImportPending"), "checks")
    _need(checks["producerConfirmed"] == list(PRODUCER_CHECKS) and checks["appImportPending"] == list(APP_IMPORT_PENDING), "checks")
    ready = _keys(bundle["readiness"], ("app", "evidenceRegistration", "publicActivation", "graphDb"), "readiness")
    _need(ready == {"app": "import-pending", "evidenceRegistration": "not-registered", "publicActivation": "none", "graphDb": "none"}, "readiness")
    digests = _keys(bundle["digests"], ("content",), "digests")
    _need(digests["content"] == content_digest(bundle), "digests.content")
