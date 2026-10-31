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

from .country_context import VERSION as COUNTRY_CONTEXT
from .extraction_contracts import ExtractionFailure, ObservationRef
from .graph_projection_contracts import APPROVAL_KEYS, APPROVAL_KINDS
from .ingestion_contracts import Wire, canonical, digest, timestamp
from .issue_summary_contracts import POLICY as ISSUE_SUMMARY_POLICY
from .issue_summary_contracts import check_summary, summary_basis
from .relation_contracts import LABELS, POLICY as RELATION_POLICY
from .relation_rules import label_from
from .source_support import KEYS as SOURCE_SUPPORT_KEYS
from .source_support import source_support

__all__ = ["ExtractionFailure", "canonical", "digest"]

SCHEMA = "zoop-ai-handoff-1"
BUNDLE_SCHEMA = "zoop-graph-handoff-bundle-8"
DECISIONS_SCHEMA = "zoop-public-decisions-4"
BINDINGS_SCHEMA = "zoop-app-document-bindings-1"
LEDGER_VERSION = "zoop-handoff-ledger-1"
POLICY = "zoop-public-projection-policy-2"
UNKNOWN_POLICY = "zoop-public-projection-policy-3"
BUNDLE_POLICIES = {BUNDLE_SCHEMA: POLICY, "zoop-graph-handoff-bundle-9": UNKNOWN_POLICY}
UNKNOWN_REASONS = ("not-stated", "not-supported", "conflicting")
EVIDENCE_KIND = "graph-body-span"
OFFSET_UNIT = "unicode_code_point"
STRUCTURAL_BASIS_TYPES = ("SUPPLIES",)       # the only S3 type inside the PoC structural basis set (PRODUCES/SUPPLIES/USES/...); others are rejected
PUBLIC_TYPES = ("INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS")
STRUCTURAL_PATH_UNAVAILABLE = "intermediate_company_unmapped"      # the ONLY reason a structural path is unavailable: a middle company the operator did not map to a public id
CONTENT_KEYS = ("companies", "pathCompanies", "issues", "relations", "evidence", "articles", "impacts")      # the public collections `digests.content` covers
MAX_SCOPE = 500                                                      # Unicode code points of an S3 `businessScope`/`productScope` (S3's own bound)
TIME_PRECISIONS = ("year", "month", "day", "datetime", "unknown")
ASSERTION_STATUSES = ("occurred", "announced", "planned", "forecast", "cancelled", "unknown")     # S2 `Mention.assertion_status`, copied as is
MENTION_VERIFICATION = "none"             # S2 candidate or operator-frozen snapshot values: no field of a mention is verified, decided or approved here
MENTION_KEYS = ("documentId", "documentVersion", "mentionId", "articleId", "articleVersion", "verification", "title", "action", "target", "eventTime",
                "timePrecision", "period", "assertionStatus", "background", "participants", "evidenceIds")
PARTICIPANT_KEYS = ("sourceCompanyId", "companyId", "name", "role")
MENTION_IDENTITY = ("documentId", "documentVersion", "mentionId")     # what names one original mention (a local mention id is unique only within one document version)
# The six headline values of an issue, as (S2 mention field, bundle wire name). The planner reads them from the chosen source (the operator's representative, or any
# member when all agree) and the validator checks them against the original mentions that state exactly the same value: ONE list, never two copies.
ISSUE_FIELDS = (("title", "title"), ("action", "action"), ("target", "target"), ("event_time", "eventTime"), ("period", "period"),
                ("assertion_status", "assertionStatus"))
VERDICT_FIELDS = (("event_time", "eventTime"), ("period", "period"))      # the two fields an operator may judge, in canonical order (a subset of ISSUE_FIELDS)
VERDICT_REASONS = {("ALLOW", "stated"), ("HOLD", "unstated"), ("HOLD", "ambiguous"), ("HOLD", "unsupported-format"), ("REJECT", "contradicted")}
VERDICT_NO_SPAN = ("HOLD", "unstated")       # the only combination that states no text (the field is absent); every other combination needs >= 1 span
VERDICT_KEYS = ("documentId", "documentVersion", "mentionId", "field", "value", "decision", "reasonCode", "evidenceIds", "verification", "reviewer", "decisionRef",
                "decisionVersion")
# What was actually run (never copied from the first source): one pair per bundle. A replay is an authored fixture response; `live`/`provider` is a real
# provider call recorded by the S2/S3 ledgers. The source KIND (synthetic or actual material) is independent of the mode.
EXECUTION_MODES = (("replay", "authored-test"), ("live", "provider"))
# `s3SemanticValidation` of INVOLVES and `basisEligibility` of a structural edge, by the approvals of the S3 relations behind it. The automatic literal is true ONLY
# when EVERY one of them was approved by the independent verifier; one operator final approval makes the whole edge `manual`.
INVOLVES_AUTOMATIC = "independent-verifier-supported-all-claims"
INVOLVES_MANUAL = "manual-operator-final-approval"
BASIS_AUTOMATIC = "s3-independent-verifier-supported-all-claims"
BASIS_MANUAL = "s3-operator-final-approval"
SOURCE_SUPPORT_POLICY = "origin-or-exact-text-union"
ORIGIN_VERIFICATION = "operator-declared-origin"
ORIGIN_KEYS = ("originId", "reviewer", "decisionRef", "decisionVersion", "verification")
# Receipt-only impact rows (S3 independent-verifier quote effects), exactly ONE per emitted INVOLVES source relation. Text effect of cited statements only.
IMPACT_POLICY_NAME = "s3-independent-verifier-quote-effect"
IMPACT_KEYS = ("edgeId", "issueId", "companyId", "sourceRelation", "impactCandidateId", "status", "code", "label", "targetVerdict", "effects", "verifier",
               "verifierRequestDigest", "proposal")
IMPACT_STATUSES = ("not-applicable", "not-proposed", "no-evidence", "technical-reject", "verifier-reject", "verified", "withheld")
IMPACT_TECHNICAL_CODES = ("producer_reply_invalid", "impact_precheck_rejected", "verifier_reply_invalid")
IMPACT_WITHHELD_CODES = ("impact_evidence_outside_relation_documents", "impact_quote_ambiguous")
IMPACT_SIDES = ("positive", "negative", "neutral", "uncertain")
IMPACT_CANDIDATE_ID = r"^ic-[a-f0-9]{64}$"
MAX_IMPACT_EFFECTS = 40                      # 20 supporting + 20 opposing citations of one S3 impact proposal
MAX_IMPACT_REASON = 2000                     # Unicode code points (never UTF-16 units)
MAX_IMPACT_LIMITATIONS = 1000

MAX_COMMAND = 65_536
MAX_OPERATOR_FILE = 4_000_000
MAX_SOURCES = 20
MAX_DECISIONS = 20_000
MAX_ISSUES = 2_000
MAX_RELATIONS = 10_000
MAX_EVIDENCE = 20_000
MAX_ARTICLES = 1_000
MAX_EXCLUSIONS = 20_000
MAX_MENTIONS = 1_000                        # per issue; also the bound of an issue's source events
MAX_PARTICIPANTS = 1_000                    # per mention
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


class SummaryPin(Wire):
    """The operator's pin of ONE immutable ready issue-summary job result (`zoop-ai-issue-summary` ledger): the job, its input digest and the digest of its
    result. Only a pin makes a summary part of a handoff; nothing here says what the summary states."""
    job_id: str = Field(pattern=ID)
    input_digest: str = Field(pattern=HASH)
    result_digest: str = Field(pattern=HASH)


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
    policy_version: Literal["zoop-public-projection-policy-2", "zoop-public-projection-policy-3"]
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


class FieldVerdict(Wire):
    """An operator verdict on ONE original mention's `eventTime` or `period` value (the PoC's per-field ALLOW/HOLD/REJECT). S2/S3 do not verify these fields,
    so this is the only verification there is. `value` is the exact string the reviewer judged: it must equal the mention's current value. No free-text note."""
    document_id: str = Field(min_length=1, max_length=200)
    document_version: str = Field(pattern=HASH)
    mention_id: str = Field(min_length=1, max_length=200)
    field: Literal["eventTime", "period"]
    value: str
    decision: Literal["ALLOW", "HOLD", "REJECT"]
    reason_code: Literal["stated", "unstated", "ambiguous", "unsupported-format", "contradicted"]
    evidence: list[Span] = Field(max_length=20)
    reviewer: str = Field(pattern=ID)
    decision_ref: str = Field(pattern=ID)
    decision_version: str = Field(pattern=ID)

    @model_validator(mode="after")
    def consistent(self):
        if (self.decision, self.reason_code) not in VERDICT_REASONS:
            raise ValueError("decision and reason code do not match")
        if ((self.decision, self.reason_code) == VERDICT_NO_SPAN) != (not self.evidence):
            raise ValueError("evidence count does not match the verdict")
        if self.reason_code == "unsupported-format" and (self.field != "eventTime" or receipt_time_precision(self.value) != "unresolved"):
            raise ValueError("unsupported-format requires an unresolved eventTime")
        return self


class Geography(Wire):
    """An explicit field verdict (the PoC's field ALLOW equivalent) for the event's country field. S2/S3 do NOT verify country fields, so this is the
    only verification there is; it is bound to the exact country set, never inferred from language, ticker, exchange or company."""
    classification: Literal["domestic", "international"]
    countries: list[str] = Field(min_length=1, max_length=10)
    evidence: list[Span] = Field(min_length=1, max_length=20)
    decision_ref: str = Field(pattern=ID)
    decision_version: str = Field(pattern=ID)


class UnknownGeography(Wire):
    classification: None
    countries: list[str] = Field(max_length=0)
    evidence: list[Span] = Field(max_length=0)
    reason_code: Literal["not-stated", "not-supported", "conflicting"]
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
    geography: Geography | UnknownGeography
    representative: Representative | None
    decision_ref: str = Field(pattern=ID)
    field_verdicts: list[FieldVerdict] = Field(max_length=2 * MAX_MENTIONS)
    summary: SummaryPin | None

    @model_validator(mode="after")
    def distinct_verdicts(self):
        keys = [(v.document_id, v.document_version, v.mention_id, v.field) for v in self.field_verdicts]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate field verdict")
        return self


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


class Origin(Wire):
    """An operator-DECLARED origin (the first publisher of a wire/press text) of ONE exact source document version. It is the only origin source: it is never
    inferred from a publisher, URL, host, source id or title, and a version without a declaration is simply unknown. `originId` is an opaque operator label."""
    document_id: str = Field(min_length=1, max_length=200)
    document_version: str = Field(pattern=HASH)
    origin_id: str = Field(pattern=ID)
    reviewer: str = Field(pattern=ID)
    decision_ref: str = Field(pattern=ID)
    decision_version: str = Field(pattern=ID)


class Decisions(Wire):
    schema_version: Literal["zoop-public-decisions-4", "zoop-public-decisions-5"]
    policy_version: Literal["zoop-public-projection-policy-2", "zoop-public-projection-policy-3"]
    companies: list[CompanyDecision] = Field(max_length=MAX_DECISIONS)
    issues: list[IssueDecision] = Field(max_length=MAX_DECISIONS)
    structural: list[StructuralDecision] = Field(max_length=MAX_DECISIONS)
    follows: list[FollowsDecision] = Field(max_length=MAX_DECISIONS)
    origins: list[Origin] = Field(max_length=MAX_DECISIONS)

    @model_validator(mode="after")
    def unique(self):
        expected = {"zoop-public-decisions-4": POLICY, "zoop-public-decisions-5": UNKNOWN_POLICY}
        if self.policy_version != expected[self.schema_version]:
            raise ValueError("decision schema and policy disagree")
        if self.policy_version == POLICY and any(isinstance(i.geography, UnknownGeography) for i in self.issues):
            raise ValueError("explicit unknown geography requires decisions5")
        def dup(values: list) -> bool:
            return len(set(values)) != len(values)

        if (dup([c.canonical_id for c in self.companies]) or dup([c.public_id for c in self.companies])
                or dup([i.canonical_id for i in self.issues]) or dup([i.public_id for i in self.issues])
                or dup([(s.issue, s.company) for s in self.structural]) or dup([(f.from_, f.to) for f in self.follows])
                or dup([(o.document_id, o.document_version) for o in self.origins])):
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


# Explicit shared calendar grammar: Python's broader ISO parser also accepts forms the app cannot represent.
# Calendar years start at 1, except the original bare year 0000; offsets stop at 18 hours.
# Unsupported nonempty source strings are retained separately by receipt_time_precision.
_MENTION_TIME = re.compile(r"([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2})(?:T([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.[0-9]{1,9})?)?(Z|[+-][0-9]{2}:[0-9]{2}))?)?)?")


def mention_time_precision(value: str | None) -> str:
    """Strict calendar classification of an original mention. Unsupported strings raise ValueError; receipt retention is handled separately."""
    if value is None:
        return "unknown"
    if not isinstance(value, str):
        raise ValueError("unsupported time form")
    found = _MENTION_TIME.fullmatch(value)
    if found is None:
        raise ValueError("unsupported time form")
    year, month, day, hour, minute, second, offset = found.groups()
    if month is None:
        return "year"
    if year == "0000" or not 1 <= int(month) <= 12:
        raise ValueError("unsupported time form")
    if day is None:
        return "month"
    date(int(year), int(month), int(day))             # ValueError for a day that does not exist in that month
    if hour is None:
        return "day"
    if int(hour) > 23 or int(minute) > 59 or (second is not None and int(second) > 59):
        raise ValueError("unsupported time form")
    if offset != "Z":
        hours, minutes = int(offset[1:3]), int(offset[4:6])
        if minutes > 59 or hours * 60 + minutes > 18 * 60:
            raise ValueError("unsupported time form")
    return "datetime"


def receipt_time_precision(value: str | None) -> str:
    """Preserve an unsupported nonempty source string as unresolved receipt data, without interpreting its calendar."""
    try:
        return mention_time_precision(value)
    except ValueError:
        if not isinstance(value, str) or not value:
            raise
        return "unresolved"


def mention_key(document_id: str, document_version: str, mention_id: str) -> str:
    """The total order of an issue's mentions: the canonical JSON of the mention identity. An S2 local mention id is unique only within one document
    version, so the document is part of the identity."""
    return canonical({"documentId": document_id, "documentVersion": document_version, "mentionId": mention_id})


def countries_class(countries: list[str]) -> str:
    """`invalid` | `unknown` (empty) | `domestic` (exactly KR) | `international` (any non-KR country, KR+other included). Pure; never a heuristic."""
    if not countries:
        return "unknown"
    if any(len(c) != 2 or not (c.isascii() and c.isalpha() and c.isupper()) for c in countries):
        return "invalid"
    return "domestic" if set(countries) == {"KR"} else "international"


def content_digest(bundle: dict) -> str:
    return digest({key: bundle[key] for key in CONTENT_KEYS})


def impact_label(target_verdict: str | None, effects: dict) -> str:
    """The deterministic label of a VERIFIED impact row from the verifier's own mapping: one uncertain quote effect or an insufficient target verdict leaves no
    label to compute (`undetermined`); otherwise positive-only, negative-only, both (`mixed`) or neither. A text effect of cited statements, never a price view."""
    if effects["uncertain"] or target_verdict == "insufficient":
        return "undetermined"
    return label_from(effects["positive"], effects["negative"])


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


def _approval(value, revision: int, at: str) -> dict:
    """`approvalBasis` of one used S3 relation: closed, its revision is the revision it was used at, an automatic basis has no reviewer and an operator final
    approval always names one."""
    basis = _keys(value, APPROVAL_KEYS, at)
    _need(basis["kind"] in APPROVAL_KINDS, f"{at}.kind")
    _need(type(basis["revision"]) is int and basis["revision"] == revision, f"{at}.revision")
    _need((basis["reviewer"] is None) == (basis["kind"] == "automatic-verifier"), f"{at}.reviewer")
    _text(basis["reviewer"], f"{at}.reviewer", nullable=True)          # the S3 review wire's free text (1..200 characters), not an identifier pattern
    _need(basis["reviewer"] is None or (bool(basis["reviewer"].strip()) and len(basis["reviewer"]) <= 200), f"{at}.reviewer")
    _text(basis["decidedAt"], f"{at}.decidedAt")
    try:
        timestamp(basis["decidedAt"])          # the native rule (an ISO form WITH an offset), the same one the app's OffsetDateTime parse enforces
    except (ValueError, TypeError):
        _bad(f"{at}.decidedAt")
    return basis


def involves_validation(approvals: list[dict]) -> str:
    """The honest `s3SemanticValidation` of an INVOLVES edge: the automatic literal only when EVERY S3 relation behind it was approved by the independent
    verifier; one operator final approval makes the edge `manual`."""
    return INVOLVES_AUTOMATIC if all(a["kind"] == "automatic-verifier" for a in approvals) else INVOLVES_MANUAL


def basis_eligibility(approvals: list[dict]) -> str:
    """Same rule for the `basisEligibility` of a structural edge, over its basis relations."""
    return BASIS_AUTOMATIC if all(a["kind"] == "automatic-verifier" for a in approvals) else BASIS_MANUAL


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


def selected_basis(representative: dict | None, mentions: list) -> list:
    """The identities whose value the issue headline is selected from: the operator's representative mention, or EVERY mention when none was named (`unanimous`)."""
    if representative is None:
        return [{key: m[key] for key in MENTION_IDENTITY} for m in mentions]
    return [{key: representative[key] for key in MENTION_IDENTITY}]


def withheld_fields(verdicts: list, basis: list) -> list:
    """The judged fields whose issue headline the producer withholds: a HOLD or REJECT on a mention of the selection basis, in the canonical field order."""
    bad = {v["field"] for v in verdicts if v["decision"] != "ALLOW" and {key: v[key] for key in MENTION_IDENTITY} in basis}
    return [wire for _, wire in VERDICT_FIELDS if wire in bad]


def _field_verdicts(issue: dict, mentions: list, evidence: dict, evidence_ids) -> list:
    """`issue.fieldVerdicts`: the operator's per-field verdicts, each bound to one original mention of this issue and to the exact value that mention states. Closed
    shape, one entry per (mention identity, field), in the canonical order (mention key, then field order), spans cited as app evidence of the mention's OWN article.
    ALLOW/stated, HOLD/ambiguous and REJECT/contradicted need at least one span, HOLD/unstated none. Returns the withheld fields the verdicts imply."""
    at = "issue.fieldVerdicts"
    verdicts = _list(issue["fieldVerdicts"], at, 2 * MAX_MENTIONS)
    by_identity = {mention_key(m["documentId"], m["documentVersion"], m["mentionId"]): m for m in mentions}
    order = {wire: n for n, (_, wire) in enumerate(VERDICT_FIELDS)}
    previous = None
    for v in verdicts:
        _keys(v, VERDICT_KEYS, at)
        _text(v["documentId"], f"{at}.documentId", ID)
        _text(v["documentVersion"], f"{at}.documentVersion", HASH)
        _text(v["mentionId"], f"{at}.mentionId")
        key = mention_key(v["documentId"], v["documentVersion"], v["mentionId"])
        mention = by_identity.get(key)
        _need(mention is not None, f"{at}.mentionClosure")
        _need(v["field"] in order, f"{at}.field")
        _text(v["value"], f"{at}.value")
        _need(v["value"] == mention[v["field"]], f"{at}.value.exact")
        _need((v["decision"], v["reasonCode"]) in VERDICT_REASONS, f"{at}.reasonCode")
        _need(v["reasonCode"] != "unsupported-format" or (v["field"] == "eventTime" and mention["timePrecision"] == "unresolved"),
              f"{at}.unsupportedFormat")
        _need(v["verification"] == "operator-field-verdict", f"{at}.verification")
        for name in ("reviewer", "decisionRef", "decisionVersion"):
            _text(v[name], f"{at}.{name}", ID)
        unstated = (v["decision"], v["reasonCode"]) == VERDICT_NO_SPAN
        ids = evidence_ids(v["evidenceIds"], f"{at}.evidenceIds", 0 if unstated else 1)
        _need(len(ids) <= 20, f"{at}.evidenceIds")                    # the operator file's bound (`FieldVerdict.evidence` <= 20 spans), as in the service and the app
        _need(bool(ids) != unstated, f"{at}.evidenceCount")
        _need(all((evidence[x]["articleId"], evidence[x]["articleVersion"]) == (mention["articleId"], mention["articleVersion"]) for x in ids), f"{at}.evidenceClosure")
        position = (key, order[v["field"]])
        _need(previous is None or previous < position, f"{at}.order")
        previous = position
    reviewed = {mention_key(v["documentId"], v["documentVersion"], v["mentionId"]) for v in verdicts
                if v["field"] == "eventTime" and v["decision"] != "ALLOW"}
    _need(all(m["timePrecision"] != "unresolved" or key in reviewed for key, m in by_identity.items()), f"{at}.unresolvedTime")
    return verdicts


def _field_provenance(issue: dict, mentions: list, verdicts: list) -> None:
    """`issue.fieldProvenance`: how the issue's six headline values were SELECTED and which original mentions state exactly each of them. It is a selection record,
    never a verification: `verification` is `none`, and listing a mention says only that it states the same string (or the same absence), not that anything is
    supported, approved or true. Every list must equal, in the mentions' own order, the identities of the mentions whose value equals the SELECTED value (the
    representative's, or the shared one when `unanimous`) by exact JSON equality (`null` equals `null`; no trimming, no time normalisation), so order, uniqueness and
    closure need no separate rule. It must be non-empty, equal to ALL mentions when no representative exists and contain the representative's mention in every field
    when the operator named one. `withheld` is recomputed from the verdicts: the issue's value of a withheld field is `null` (and an event time's precision `unknown`),
    otherwise exactly the selected value. Called after the mentions, the verdicts and the representative are closed."""
    at = "issue.fieldProvenance"
    provenance = _keys(issue["fieldProvenance"], ("selection", "verification", "withheld", "sameValueMentions"), at)
    representative = issue["representative"]
    _need(provenance["selection"] == ("unanimous" if representative is None else "operator-representative"), f"{at}.selection")
    _need(provenance["verification"] == MENTION_VERIFICATION, f"{at}.verification")
    basis = selected_basis(representative, mentions)
    withheld = withheld_fields(verdicts, basis)
    _need(provenance["withheld"] == withheld, f"{at}.withheld")
    chosen = next(m for m in mentions if {key: m[key] for key in MENTION_IDENTITY} == basis[0])
    same = _keys(provenance["sameValueMentions"], tuple(wire for _, wire in ISSUE_FIELDS), f"{at}.sameValueMentions")
    identities = [{key: m[key] for key in MENTION_IDENTITY} for m in mentions]
    for _, wire in ISSUE_FIELDS:
        listed = _list(same[wire], f"{at}.{wire}", MAX_MENTIONS)
        for ref in listed:
            _keys(ref, MENTION_IDENTITY, f"{at}.{wire}")
        _need(listed == [identity for identity, m in zip(identities, mentions) if m[wire] == chosen[wire]], f"{at}.{wire}.exact")
        _need(bool(listed), f"{at}.{wire}.nonEmpty")
        if representative is None:
            _need(listed == identities, f"{at}.{wire}.unanimous")
        else:
            _need(basis[0] in listed, f"{at}.{wire}.representative")
        _need(issue[wire] == (None if wire in withheld else chosen[wire]), f"{at}.{wire}.published")
    _need("eventTime" not in withheld or issue["timePrecision"] == "unknown", "issue.timePrecision.withheld")
    _need("eventTime" in withheld or issue["timePrecision"] == chosen["timePrecision"], "issue.timePrecision.selected")


def _issue_summary(issue: dict, evidence: dict, articles: dict, execution: tuple) -> None:
    """`issue.summary`: recomputed from the bundle ITSELF by the pure `issue_summary_contracts` rules, never trusted. A HOLD/REJECT field verdict anywhere on the issue
    leaves exactly `unavailable/temporal-review-pending` (and an oversize input exactly `input-too-large`): no summary text exists in the bundle then. Otherwise the
    summary is `not-requested`, a verified job's `available` object (its claims cite only the issue's own mention evidence, the basis digest, the result version and
    the producer/verifier kinds are recomputed against the bundle's execution mode) or a job-coded `unavailable` that names its pinned result. The checker raises
    `ValueError(code)` and nothing else of the summary is read."""
    try:
        check_summary(issue, issue["summary"], summary_basis(issue, evidence, articles), execution)
    except ValueError as exc:
        _bad(f"issue.{exc}")                  # the checker's own location already starts with `summary.`
    except (KeyError, TypeError, AttributeError):
        _bad("issue.summary")


def _impact_proposal(value, at: str) -> None:
    proposal = _keys(value, ("direction", "reason", "limitations", "verification"), at)
    _need(proposal["direction"] in LABELS, f"{at}.direction")
    _text(proposal["reason"], f"{at}.reason")
    _need(1 <= len(proposal["reason"]) <= MAX_IMPACT_REASON, f"{at}.reason.length")              # Unicode code points, as in the S3 wire and the app's codePointCount
    _text(proposal["limitations"], f"{at}.limitations", nullable=True)
    _need(proposal["limitations"] is None or len(proposal["limitations"]) <= MAX_IMPACT_LIMITATIONS, f"{at}.limitations.length")
    _need(proposal["verification"] == "none", f"{at}.verification")          # the producer's own words are never verified here


def _impacts(rows, involves: dict, used_reviews: dict, evidence: dict, evidence_ids, execution_mode: str, jobs: set) -> list:
    """`impacts`: the receipt-only text effects of the quotes of every emitted INVOLVES source relation, closed. Exactly one row per (edge, S3 job, relation) of an
    INVOLVES `sourceRefs`, sorted by that tuple; the status/code/null table, the approval basis (`not-applicable` iff an operator final approval), the replay-only
    technical `verifier_reply_invalid`, unique impact candidates per job, and for a verified row: the verifier's effect sides (sorted, unique, disjoint, 1..40 in total,
    app evidence of the edge's own article versions, distinct source evidence ids) with the label recomputed from them. Verified effect ids count as referenced
    evidence. Called AFTER every INVOLVES edge is known and BEFORE the evidence orphan rule."""
    at = "impacts"
    rows = _list(rows, at, MAX_RELATIONS)
    expected = sorted((edge_id, ref["jobId"], ref["id"]) for edge_id, (_, refs) in involves.items() for ref in refs)
    keys, candidates = [], set()
    for row in rows:
        _keys(row, IMPACT_KEYS, at)
        _text(row["edgeId"], f"{at}.edgeId", ID)
        _need(row["edgeId"] in involves, f"{at}.edgeClosure")
        edge = involves[row["edgeId"]][0]
        _need(row["issueId"] == edge["source"] and row["companyId"] == edge["target"], f"{at}.endpoints")
        source = _keys(row["sourceRelation"], ("jobId", "relationCandidateId"), f"{at}.sourceRelation")
        _text(source["jobId"], f"{at}.sourceRelation", ID)
        _text(source["relationCandidateId"], f"{at}.sourceRelation", RC)
        job, rc = source["jobId"], source["relationCandidateId"]
        _need(job in jobs and rc in used_reviews[job], f"{at}.sourceClosure")
        keys.append((row["edgeId"], job, rc))
        operator = used_reviews[job][rc]["kind"] == "operator-final-approval"
        status, code = row["status"], row["code"]
        _need(status in IMPACT_STATUSES, f"{at}.status")
        _need((status == "not-applicable") == operator, f"{at}.approval")                  # both ways: no label may exist on a human-approved relation
        ic = row["impactCandidateId"]
        _text(ic, f"{at}.impactCandidateId", IMPACT_CANDIDATE_ID, nullable=True)
        _need(row["verifier"] in ("called", "not-called"), f"{at}.verifier")
        called = row["verifier"] == "called"
        _text(row["verifierRequestDigest"], f"{at}.verifierRequestDigest", HASH, nullable=True)
        _need((row["verifierRequestDigest"] is not None) == called, f"{at}.verifierRequestDigest")
        if row["proposal"] is not None:
            _impact_proposal(row["proposal"], f"{at}.proposal")
        # The state table: (impact candidate present, verifier called, proposal present) per status and technical/withheld code.
        if status == "technical-reject":
            _need(code in IMPACT_TECHNICAL_CODES, f"{at}.code")
            shape = {"producer_reply_invalid": (False, False, False), "impact_precheck_rejected": (True, False, False),
                     "verifier_reply_invalid": (True, True, True)}[code]
            _need(code != "verifier_reply_invalid" or execution_mode == "replay", f"{at}.code.replayOnly")      # a live verifier reply that is no judgment writes no verdict
        elif status == "withheld":
            _need(code in IMPACT_WITHHELD_CODES, f"{at}.code")
            shape = (True, True, True)
        else:
            _need(code is None, f"{at}.code")
            shape = {"not-applicable": (False, False, False), "not-proposed": (False, False, False), "no-evidence": (True, False, True),
                     "verifier-reject": (True, True, True), "verified": (True, True, True)}[status]
        _need((ic is not None, called, row["proposal"] is not None) == shape, f"{at}.state")
        if status != "verified":
            _need(row["targetVerdict"] == ("contradicted" if status == "verifier-reject" else None), f"{at}.targetVerdict")
        if ic is not None:
            _need((job, ic) not in candidates, f"{at}.impactCandidateId.unique")
            candidates.add((job, ic))
        if status != "verified":
            _need(row["label"] is None and row["effects"] is None, f"{at}.verifiedOnly")
            continue
        _need(row["targetVerdict"] in ("supported", "insufficient"), f"{at}.targetVerdict")
        effects = _keys(row["effects"], IMPACT_SIDES, f"{at}.effects")
        everything: list = []
        for side in IMPACT_SIDES:
            everything.extend(evidence_ids(effects[side], f"{at}.effects.{side}", 0))
        _need(1 <= len(everything) <= MAX_IMPACT_EFFECTS and len(set(everything)) == len(everything), f"{at}.effects.union")        # disjoint sides, 1..40 in total
        allowed = {(evidence[x]["articleId"], evidence[x]["articleVersion"]) for x in edge["evidenceIds"]}
        _need(all((evidence[x]["articleId"], evidence[x]["articleVersion"]) in allowed for x in everything), f"{at}.effects.articleClosure")
        _need(len({evidence[x]["source"]["sourceEvidenceId"] for x in everything}) == len(everything), f"{at}.effects.sourceEvidenceId")
        _need(row["label"] == impact_label(row["targetVerdict"], effects), f"{at}.label")
    _need(keys == expected, f"{at}.coverage")              # exactly the INVOLVES source relations: none missing, duplicated or extra, in code point order
    return rows


def validate_bundle(bundle: dict) -> None:
    """Strict, closed validation of a bundle: exact key sets, types, patterns, referential closure, id formulas, counts and the content digest. Anything
    else is `handoff_bundle_invalid` (a damaged or hand-edited artifact), never a partial read."""
    _keys(bundle, ("schemaVersion", "handoffId", "manifestDigest", "provenance", "policy", "sources", "companies", "pathCompanies", "issues", "relations",
                   "evidence", "articles", "impacts", "exclusions", "counts", "checks", "readiness", "digests"), "bundle")
    _need(bundle["schemaVersion"] in BUNDLE_POLICIES, "schemaVersion")
    policy_version = BUNDLE_POLICIES[bundle["schemaVersion"]]
    explicit_unknown = policy_version == UNKNOWN_POLICY
    _text(bundle["handoffId"], "handoffId", ID)
    _text(bundle["manifestDigest"], "manifestDigest", HASH)
    prov = _keys(bundle["provenance"], ("declaredSourceKind", "observedSourceKind", "executionMode", "recordingKind"), "provenance")
    _need(prov["declaredSourceKind"] == prov["observedSourceKind"] and prov["declaredSourceKind"] in ("synthetic", "actual"), "provenance")
    _need((prov["executionMode"], prov["recordingKind"]) in EXECUTION_MODES, "provenance.mode")
    policy = _keys(bundle["policy"], ("version", "files", "evidenceIdKind", "offsetUnit", "geography", "structural", "sequence", "sourceSupport", "impacts",
                                      "issueSummary"), "policy")
    _need(policy["version"] == policy_version and policy["evidenceIdKind"] == EVIDENCE_KIND and policy["offsetUnit"] == OFFSET_UNIT, "policy")
    for name, expected in (("geography", "operator-field-verdict-or-explicit-unknown" if explicit_unknown else "operator-field-verdict"), ("structural", "manual-operator-review"),
                           ("sequence", "s2-comparison-with-operator-decision"), ("sourceSupport", SOURCE_SUPPORT_POLICY), ("impacts", IMPACT_POLICY_NAME),
                           ("issueSummary", ISSUE_SUMMARY_POLICY)):
        _need(policy[name] == expected, f"policy.{name}")
    files = _keys(policy["files"], ("canonical", "decisions", "bindings"), "policy.files")
    for value in files.values():
        _text(value, "policy.files", HASH)

    sources = _list(bundle["sources"], "sources", MAX_SOURCES)
    _need(len(sources) >= 1, "sources")
    jobs, upstreams, used_reviews = set(), set(), {}
    for s in sources:
        _keys(s, ("relation", "upstream", "reviewDigest", "policies", "reviewUsed", "audit", "provenance"), "source")
        sprov = _keys(s["provenance"], ("sourceKind", "executionMode", "recordingKind"), "source.provenance")
        _need(sprov == {"sourceKind": prov["observedSourceKind"], "executionMode": prov["executionMode"], "recordingKind": prov["recordingKind"]}, "source.provenance.mixed")
        r = _keys(s["relation"], ("jobId", "inputDigest"), "source.relation")
        _text(r["jobId"], "source.relation", ID)
        _text(r["inputDigest"], "source.relation", HASH)
        u = _keys(s["upstream"], ("jobId", "inputDigest", "digest"), "source.upstream")
        _text(u["jobId"], "source.upstream", ID)
        _text(u["inputDigest"], "source.upstream", HASH)
        _text(u["digest"], "source.upstream", HASH)
        _text(s["reviewDigest"], "source.reviewDigest", HASH)
        policy_keys = ("producer", "verifier", "impactProducer", "impactVerifier", "policy", "revalidationPolicy", "impactPolicy")
        _need(isinstance(s["policies"], dict) and s["policies"].get("policy") in ("zoop-relation-policy-1", RELATION_POLICY),
              "source.policies")
        current = s["policies"]["policy"] == RELATION_POLICY
        versions = _keys(s["policies"], policy_keys + (("countryContext",) if current else ()), "source.policies")
        if current:
            _need(versions["countryContext"] == COUNTRY_CONTEXT, "source.policies.countryContext")
        for value in versions.values():
            _text(value, "source.policies")
            _need(bool(value), "source.policies")
        used, previous = {}, None
        for item in _list(s["reviewUsed"], "source.reviewUsed", MAX_RELATIONS):
            _keys(item, ("relationCandidateId", "revision", "approvalBasis"), "source.reviewUsed")
            _text(item["relationCandidateId"], "source.reviewUsed", RC)
            _int(item["revision"], "source.reviewUsed", 1)
            _need(previous is None or previous < item["relationCandidateId"], "source.reviewUsed.order")
            previous = item["relationCandidateId"]
            used[item["relationCandidateId"]] = _approval(item["approvalBasis"], item["revision"], "source.reviewUsed.approvalBasis")
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
                  "textSha256", "origin", "observations"), "article")
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
        _text(a["textSha256"], "article.textSha256", HASH)
        if a["origin"] is not None:
            origin = _keys(a["origin"], ORIGIN_KEYS, "article.origin")
            for name in ("originId", "reviewer", "decisionRef", "decisionVersion"):
                _text(origin[name], f"article.origin.{name}", ID)
            _need(origin["verification"] == ORIGIN_VERIFICATION, "article.origin.verification")
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

    def company(c, at: str) -> None:
        _keys(c, ("id", "canonicalId", "label", "decisionRef"), at)
        for name in ("id", "canonicalId", "decisionRef"):
            _text(c[name], at, ID)
        _text(c["label"], f"{at}.label")

    companies = {}
    for c in _list(bundle["companies"], "companies", MAX_DECISIONS):
        company(c, "company")
        _need(c["id"] not in companies, "companies.unique")
        companies[c["id"]] = c
    # Private support references of structural paths: the same closed record as a company, never a graph node, disjoint from the public companies and the issues.
    path_companies = {}
    for c in _list(bundle["pathCompanies"], "pathCompanies", MAX_DECISIONS):
        company(c, "pathCompany")
        _need(c["id"] not in path_companies and c["id"] not in companies, "pathCompanies.unique")
        path_companies[c["id"]] = c
    _need(list(path_companies) == sorted(path_companies), "pathCompanies.order")

    by_document: dict = {}
    for article in articles.values():
        by_document.setdefault((article["documentId"], article["documentVersion"]), []).append((article["articleId"], article["articleVersion"]))

    def mention(m, at: str) -> list:
        """One original S2 mention. Every value is a candidate/snapshot value (`verification` is always `none`); the only closure checked here is identity,
        the article of the mention's own document, its time precision and the evidence on that article."""
        _keys(m, MENTION_KEYS, at)
        _text(m["documentId"], f"{at}.documentId", ID)
        _text(m["documentVersion"], f"{at}.documentVersion", HASH)
        _text(m["mentionId"], f"{at}.mentionId")
        _need(bool(m["mentionId"]), f"{at}.mentionId")
        _text(m["articleId"], f"{at}.articleId", ARTICLE_ID)
        _text(m["articleVersion"], f"{at}.articleVersion", HASH)
        _need(m["verification"] == MENTION_VERIFICATION, f"{at}.verification")
        _text(m["title"], f"{at}.title")
        _text(m["action"], f"{at}.action")
        for name in ("target", "eventTime", "period"):
            _text(m[name], f"{at}.{name}", nullable=True)
        try:
            precision = receipt_time_precision(m["eventTime"])
        except ValueError:
            precision = None
        _need(precision is not None and m["timePrecision"] == precision, f"{at}.timePrecision")
        _need(m["assertionStatus"] in ASSERTION_STATUSES, f"{at}.assertionStatus")
        _need(type(m["background"]) is bool, f"{at}.background")
        for p in _list(m["participants"], f"{at}.participants", MAX_PARTICIPANTS):
            _keys(p, PARTICIPANT_KEYS, f"{at}.participant")
            _text(p["sourceCompanyId"], f"{at}.participant.sourceCompanyId", nullable=True)
            _text(p["companyId"], f"{at}.participant.companyId", nullable=True)
            _text(p["name"], f"{at}.participant.name")
            _text(p["role"], f"{at}.participant.role")
            _need(p["companyId"] is None or (p["companyId"] in companies and p["sourceCompanyId"] is not None), f"{at}.participant.companyId")
        ids = evidence_ids(m["evidenceIds"], f"{at}.evidenceIds")
        _need(by_document.get((m["documentId"], m["documentVersion"])) == [(m["articleId"], m["articleVersion"])], f"{at}.articleClosure")
        _need(all((evidence[x]["articleId"], evidence[x]["articleVersion"]) == (m["articleId"], m["articleVersion"]) for x in ids), f"{at}.evidenceClosure")
        return ids

    issues = {}
    for i in _list(bundle["issues"], "issues", MAX_ISSUES):
        _keys(i, ("id", "canonicalId", "title", "action", "target", "eventTime", "timePrecision", "period", "assertionStatus", "geography", "evidenceIds",
                  "sourceEvents", "decisionRef", "representative", "fieldProvenance", "fieldVerdicts", "mentions", "sourceSupport", "summary"), "issue")
        _text(i["id"], "issue.id", ID)
        _text(i["canonicalId"], "issue", ID)
        _text(i["decisionRef"], "issue", ID)
        _text(i["title"], "issue.title")
        for name in ("action", "target", "eventTime", "period", "assertionStatus"):
            _text(i[name], f"issue.{name}", nullable=True)
        _need(i["timePrecision"] in TIME_PRECISIONS, "issue.timePrecision")
        _need(isinstance(i["geography"], dict), "issue.geography")
        unknown = explicit_unknown and i["geography"].get("value") is None
        geo_keys = ("value", "decisionRef", "decisionVersion", "policyVersion", "countries", "verification", "evidenceIds", "basis")
        geo = _keys(i["geography"], geo_keys + (("reasonCode",) if unknown else ()), "issue.geography")
        _need(geo["policyVersion"] == policy_version, "issue.geography.policyVersion")
        _text(geo["decisionRef"], "issue.geography", ID)
        _text(geo["decisionVersion"], "issue.geography", ID)
        if unknown:
            _need(geo["countries"] == [] and geo["evidenceIds"] == [] and geo["verification"] == "not-established"
                  and geo["reasonCode"] in UNKNOWN_REASONS, "issue.geography.unknown")
        else:
            _need(geo["value"] in ("domestic", "international") and geo["verification"] == "operator-field-verdict", "issue.geography")
            _need(countries_class(_strings(geo["countries"], "issue.geography.countries", maximum=10)) == geo["value"], "issue.geography.class")
        evidence_ids(i["evidenceIds"], "issue.evidenceIds")
        evidence_ids(geo["evidenceIds"], "issue.geography.evidenceIds", 0 if unknown else 1)
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
            _strings(item["countries"], "issue.geography.basisCountries", maximum=10)
            _need(unknown or item["countries"] == [] or item["countries"] == geo["countries"], "issue.geography.basisCountries")
        _need([{k: v for k, v in b.items() if k != "countries"} for b in basis] == source_events, "issue.geography.basisClosure")
        own_documents = {(s["documentId"], s["documentVersion"]) for s in source_events}
        _need(all((evidence[x]["source"]["documentId"], evidence[x]["source"]["documentVersion"]) in own_documents
                  for x in geo["evidenceIds"]), "issue.geography.evidenceDocument")
        if i["representative"] is not None:
            rep = _keys(i["representative"], ("upstream", "kind", "ref", "mentionId", "documentId", "documentVersion", "observation"),
                        "issue.representative")
            _source_event(rep, "issue.representative", upstreams)
            _need(rep in source_events, "issue.representativeClosure")
        mentions = _list(i["mentions"], "issue.mentions", MAX_MENTIONS)
        mentioned = set(geo["evidenceIds"])
        for m in mentions:
            mentioned.update(mention(m, "issue.mention"))
        keys = [mention_key(m["documentId"], m["documentVersion"], m["mentionId"]) for m in mentions]
        _need(keys == sorted(set(keys)), "issue.mentions.order")
        _need({(m["documentId"], m["documentVersion"], m["mentionId"]) for m in mentions} ==
              {(s["documentId"], s["documentVersion"], s["mentionId"]) for s in source_events}, "issue.mentions.sourceClosure")
        verdicts = _field_verdicts(i, mentions, evidence, evidence_ids)
        for v in verdicts:
            mentioned.update(v["evidenceIds"])
        _need(set(i["evidenceIds"]) == mentioned, "issue.evidenceClosure")
        cited = sorted({(evidence[x]["articleId"], evidence[x]["articleVersion"]) for x in i["evidenceIds"]})
        _need(len({article for article, _ in cited}) == len(cited), "issue.articleVersions")        # exactly one cited version of each article
        support = _keys(i["sourceSupport"], SOURCE_SUPPORT_KEYS, "issue.sourceSupport")
        _need(support == source_support([{"articleId": a, "textSha256": articles[(a, v)]["textSha256"],
                                          "originId": (articles[(a, v)]["origin"] or {}).get("originId")} for a, v in cited]), "issue.sourceSupport.exact")
        _field_provenance(i, mentions, verdicts)
        try:
            headline_precision = mention_time_precision(i["eventTime"])
        except ValueError:
            headline_precision = None
        _need(i["timePrecision"] == headline_precision, "issue.timePrecision.value")
        _issue_summary(i, evidence, articles, (prov["executionMode"], prov["recordingKind"]))
        _need(i["id"] not in issues and i["id"] not in companies and i["id"] not in path_companies, "issues.unique")
        issues[i["id"]] = i

    relation_ids = set()
    counts = {name: 0 for name in PUBLIC_TYPES}
    linked: dict[str, set] = {name: set() for name in ("issue", "company")}
    participants: dict[str, set] = {}          # public issue -> the companies an INVOLVES edge of that issue names
    involves: dict[str, tuple] = {}            # INVOLVES edge id -> (edge, sourceRefs): what every impact row must cover exactly
    structural_paths: list = []                # (relation, path) of every STRUCTURALLY_RELATED_TO edge, checked once every INVOLVES edge is known
    for r in _list(bundle["relations"], "relations", MAX_RELATIONS):
        _keys(r, ("id", "type", "source", "target", "role", "assertionStatus", "evidenceIds", "basis", "structuralPath", "provenance", "decisionRef",
                  "sourceRefs"), "relation")
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
            _keys(b, ("sourceRelation", "relationKey", "relationType", "businessScope", "productScope", "validFrom", "validUntil", "countries", "verifiedAt",
                      "sourceArticles", "evidenceIds"), "basis")
            src = _keys(b["sourceRelation"], ("jobId", "relationCandidateId"), "basis.sourceRelation")
            _text(src["jobId"], "basis.sourceRelation", ID)
            _text(src["relationCandidateId"], "basis.sourceRelation", RC)
            _need(src["jobId"] in jobs and src["relationCandidateId"] in used_reviews[src["jobId"]], "basis.sourceClosure")
            basis_refs.append(("s3-relation", src["jobId"], src["relationCandidateId"]))
            _text(b["relationKey"], "basis.relationKey", HASH)
            _need(b["relationType"] in STRUCTURAL_BASIS_TYPES, "basis.relationType")
            _text(b["verifiedAt"], "basis.verifiedAt")
            _need(b["verifiedAt"] == used_reviews[src["jobId"]][src["relationCandidateId"]]["decidedAt"], "basis.verifiedAt.approval")
            _text(b["validFrom"], "basis.validFrom", nullable=True)
            _text(b["validUntil"], "basis.validUntil", nullable=True)
            _strings(b["countries"], "basis.countries", maximum=10)
            if explicit_unknown:
                issue = issues[r["source"]]
                countries = issue["geography"]["countries"]
                _need(not b["countries"] or bool(countries) and set(countries) <= set(b["countries"]), "basis_countries_unprovable")
                if b["validFrom"] is not None or b["validUntil"] is not None:
                    when = issue["eventTime"]
                    _need(when is not None and issue["timePrecision"] in ("day", "datetime"), "basis_validity_unprovable")
                    day = date.fromisoformat(when[:10])
                    _need((b["validFrom"] is None or day >= date.fromisoformat(b["validFrom"]))
                          and (b["validUntil"] is None or day <= date.fromisoformat(b["validUntil"])), "basis_validity_outside_event_time")
            for name in ("businessScope", "productScope"):        # S3 text copied exactly (never an entity id), bounded in code points
                _text(b[name], f"basis.{name}", nullable=True)
                _need(b[name] is None or len(b[name]) <= MAX_SCOPE, f"basis.{name}.length")
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
        if r["type"] != "STRUCTURALLY_RELATED_TO":
            _need(r["structuralPath"] is None, "relation.structuralPath")
        if r["type"] == "INVOLVES":
            participants.setdefault(r["source"], set()).add(r["target"])
            involves[r["id"]] = (r, refs)
            _keys(provenance, ("origin", "s3SemanticValidation"), "relation.provenance")
            _need(provenance["origin"] == "s3-relation" and provenance["s3SemanticValidation"] ==
                  involves_validation([used_reviews[ref["jobId"]][ref["id"]] for ref in refs]), "relation.provenance")
            _need(r["decisionRef"] is None and r["role"] is None and not basis, "relation.involves")
        elif r["type"] == "STRUCTURALLY_RELATED_TO":
            _keys(provenance, ("origin", "s3SemanticValidation", "status", "reviewer", "decisionRef", "decisionVersion",
                               "bindingDigest", "basisEligibility"), "relation.provenance")
            _need(provenance["origin"] == "manual-operator-review" and provenance["s3SemanticValidation"] == "none"
                  and provenance["status"] == "operator-asserted"
                  and provenance["basisEligibility"] == basis_eligibility([used_reviews[ref["jobId"]][ref["id"]] for ref in refs]), "relation.provenance")
            for name in ("reviewer", "decisionRef", "decisionVersion"):
                _text(provenance[name], "relation.provenance", ID)
            _text(provenance["bindingDigest"], "relation.provenance", HASH)
            _need(r["decisionRef"] == provenance["decisionRef"] and r["role"] is None and reference_keys == basis_refs, "relation.structural")
            preimage["basis"] = [b["relationKey"] for b in basis]
            structural_paths.append((r, r["structuralPath"]))
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
    impacts = _impacts(bundle["impacts"], involves, used_reviews, evidence, evidence_ids, prov["executionMode"], jobs)
    _need(isinstance(bundle["counts"], dict) and counts == bundle["counts"].get("relations"), "counts.relations")
    _need(set(issues) == linked["issue"], "issues.noOrphan")
    _need(set(companies) == linked["company"], "companies.noOrphan")
    _need(set(evidence) == referenced, "evidence.noOrphan")

    # Structural paths: shape and connectivity per edge, then the closure of the private support companies over the complete paths.
    middles: set = set()
    for r, path in structural_paths:
        size = len(r["basis"])
        _need(isinstance(path, dict) and path.get("status") in ("complete", "unavailable"), "structuralPath")
        if path["status"] == "unavailable":
            _keys(path, ("status", "reason"), "structuralPath")
            _need(path["reason"] == STRUCTURAL_PATH_UNAVAILABLE and size == 2, "structuralPath.unavailable")      # only a two-relation edge has a middle company to be unmapped
            continue
        _keys(path, ("status", "companyIds", "links"), "structuralPath")
        chain = _strings(path["companyIds"], "structuralPath.companyIds", ID, 3)
        _need(len(chain) == size + 1 and len(set(chain)) == len(chain), "structuralPath.companyIds")
        _need(set(chain) <= set(companies) | set(path_companies), "structuralPath.catalogue")
        _need(chain[0] in participants.get(r["source"], ()) and chain[-1] == r["target"] and r["target"] not in participants.get(r["source"], ()), "structuralPath.ends")
        links = _list(path["links"], "structuralPath.links", 2)
        _need(len(links) == size, "structuralPath.links")
        for n, link in enumerate(links):          # one link per basis, in basis order, joining the two adjacent companies of the chain in either S3 direction
            _keys(link, ("supplierCompanyId", "customerCompanyId"), "structuralPath.link")
            _text(link["supplierCompanyId"], "structuralPath.link", ID)
            _text(link["customerCompanyId"], "structuralPath.link", ID)
            _need(link["supplierCompanyId"] != link["customerCompanyId"]
                  and {link["supplierCompanyId"], link["customerCompanyId"]} == {chain[n], chain[n + 1]}, "structuralPath.link")
        middles.update(chain[1:-1])
    _need(set(path_companies) == middles - set(companies), "pathCompanies.closure")

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
                      {wire for _, wire in ISSUE_FIELDS}, "exclusion.detail.fields")
            elif item["code"] == "applicability_binding_mismatch":
                detail = _keys(item["detail"], ("expectedBindingDigest",), "exclusion.detail")
                _text(detail["expectedBindingDigest"], "exclusion.detail.expectedBindingDigest", HASH)
            else:
                _bad("exclusion.detail")
        tally[item["code"]] = tally.get(item["code"], 0) + 1
    _need(ex["counts"] == tally, "exclusions.counts")
    expected = {"companies": len(companies), "pathCompanies": len(path_companies), "issues": len(issues), "relations": counts, "evidence": len(evidence),
                "articles": len(articles), "impacts": len(impacts), "exclusions": len(items)}
    _need(bundle["counts"] == expected, "counts")
    checks = _keys(bundle["checks"], ("producerConfirmed", "appImportPending"), "checks")
    _need(checks["producerConfirmed"] == list(PRODUCER_CHECKS) and checks["appImportPending"] == list(APP_IMPORT_PENDING), "checks")
    ready = _keys(bundle["readiness"], ("app", "evidenceRegistration", "publicActivation", "graphDb"), "readiness")
    _need(ready == {"app": "import-pending", "evidenceRegistration": "not-registered", "publicActivation": "none", "graphDb": "none"}, "readiness")
    digests = _keys(bundle["digests"], ("content",), "digests")
    _need(digests["content"] == content_digest(bundle), "digests.content")
