"""Wire models of the read-only handoff family (`zoop-ai-internal-handoff-1`) and the CLOSED model of the `zoop-graph-handoff-bundle-7` bundle.

Three kinds of model live here:
  * `Hd*` models (extra forbidden) are what this service emits as status and what the generated OpenAPI documents;
  * `Export` / `Rcpt` projections (strict, extra ignored) parse the envelope the installed `zoop-ai-handoff export` prints. Each envelope field the service
    relays is named exactly once, so a key the producer adds later (attempts, source job ids and counts of the receipt, failure detail, usage) is dropped
    instead of leaking, and a missing or mistyped required field fails closed;
  * `Bundle` and the `B*` models (extra forbidden at EVERY level, strict) are the bundle itself. The bundle is the producer's artifact and its SHA-256 is
    over its canonical bytes, so the service may relay it only byte-for-byte equal in canonical form: the models decide what shapes are acceptable, and
    `Bundle.wire()` dumps exactly the keys the input carried (`exclude_unset`), never a default, an alias or a coerced value. The reader additionally
    compares the canonical form of the dump with the canonical form it received, so a model that normalised anything would fail closed instead of
    delivering a bundle whose digest no longer matches.

The models are the structural contract the application can rely on (exact key sets, types, patterns and bounds). The producer owns the semantic rules
(referential closure, id formulas, source authority, counts): they are checked by the producer before it ever writes the bundle and again on every
export, and the service never repeats or second-guesses them. Everything in the bundle that came from a source (titles, URLs, labels, observation
metadata) is data, never authority: no field of it grants, extends or proves a right, and the service gates delivery only on the producer's current
verdict and the operator's pins.
Two exceptions: the `impacts` list (its row state table and every closure the closed models can see: one row per emitted INVOLVES source relation, endpoints, source
approval kind, effect evidence ids and article versions, counts, policy, deterministic label) and the issue `summary` (bundle `-7`: the whole decision table of the
producer's `issue_summary_contracts` is recomputed from the bundle, see `check_issue_summary`) are enforced here as well, so a forged row or summary never leaves.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from .relation_wire import Rel
from .wire import ErrorBody, Reviewer, Safe

SCHEMA = "zoop-ai-internal-handoff-1"
RUNTIME_SCHEMA = "zoop-ai-handoff-1"
BUNDLE_SCHEMA = "zoop-graph-handoff-bundle-7"
POLICY = "zoop-public-projection-policy-1"
HANDOFF_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,200}$"
HASH_PATTERN = r"^[a-f0-9]{64}$"
RC_PATTERN = r"^rc-[a-f0-9]{64}$"
EVC_PATTERN = r"^evc-[a-f0-9]{64}$"
ARTICLE_ID_PATTERN = r"^doc-[a-f0-9]{64}$"
EVIDENCE_ID_PATTERN = r"^ev-[a-f0-9]{64}$"
SOURCE_EVIDENCE_ID_PATTERN = r"^ev-[a-f0-9]{32}$"
STAMP_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?\+00:00$"
# Limits mirror the producer's (`handoff_contracts.py`); free text is bounded far above anything a source field holds and far below the 6 MiB bundle cap.
MAX_SOURCES, MAX_COMPANIES, MAX_ISSUES, MAX_RELATIONS, MAX_EVIDENCE, MAX_ARTICLES, MAX_EXCLUSIONS = 20, 20_000, 2_000, 10_000, 20_000, 1_000, 20_000
MAX_TEXT = 20_000
# Issue summary limits and vocabulary mirror the producer's `issue_summary_contracts`. The input quote cap is part of the policy identity: changing it changes the policy string.
SUMMARY_POLICY = "zoop-issue-summary-policy-1"
MAX_QUOTES, MAX_CLAIMS, MAX_CLAIM_QUOTES, MAX_CLAIM_TEXT = 60, 5, 5, 280      # MAX_CLAIM_TEXT counts Unicode code points
SUMMARY_DETERMINISTIC = ("not-requested", "temporal-review-pending", "input-too-large")      # no job exists behind them: `source` is null
SUMMARY_HELD_DECISIONS = ("HOLD", "REJECT")
# (executionMode, recordingKind) -> (producer kind, verifier kind): a replay summary is an authored answer, never an independent model's, and never sits in a live bundle.
SUMMARY_KINDS = {("replay", "authored-test"): ("authored-replay", "authored-replay"), ("live", "provider"): ("provider", "independent-verifier")}
RETRYABLE = frozenset({"runtime_unavailable", "runtime_busy", "service_busy", "service_configuration_invalid"})

STATES = ("reserved", "ready", "failed")
State = Literal["reserved", "ready", "failed"]


# ---- the closed bundle model -----------------------------------------------------------------------------------------------

class Bx(BaseModel):
    """Closed (extra forbidden) and strict: a key the producer did not define, a wrongly typed value or an alias spelling is a refusal, never a pass-through."""
    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", strict=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude_unset=True)


Id = Annotated[str, StringConstraints(pattern=HANDOFF_ID_PATTERN)]
Hash = Annotated[str, StringConstraints(pattern=HASH_PATTERN)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(max_length=MAX_TEXT)]
# Original S2 mention strings (title, action, target, period, participant source id, name, role) carry no length or emptiness rule in S2 (`extraction_contracts`
# `Mention`/`Participant`) and the producer adds none: they are relayed verbatim, empty included. Only the producer's 6 MiB bundle cap bounds them.
MentionText = Annotated[str, StringConstraints(max_length=6 * 1024 * 1024)]
Stamp = Annotated[str, StringConstraints(max_length=100)]
Countries = Annotated[list[Annotated[str, StringConstraints(max_length=100)]], Field(max_length=10)]
EvidenceIds = Annotated[list[Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN)]], Field(max_length=MAX_EVIDENCE)]
Count = Annotated[int, Field(ge=0)]
CountMap = dict[Annotated[str, StringConstraints(pattern=HANDOFF_ID_PATTERN)], Count]
SourceKind = Literal["synthetic", "actual"]


class BProvenance(Bx):
    declared_source_kind: SourceKind
    observed_source_kind: SourceKind
    execution_mode: Literal["replay", "live"]
    recording_kind: Literal["authored-test", "provider"]

    @model_validator(mode="after")
    def pair(self) -> BProvenance:
        if (self.execution_mode, self.recording_kind) not in (("replay", "authored-test"), ("live", "provider")):
            raise ValueError("executionMode and recordingKind disagree")
        return self


class BPolicyFiles(Bx):
    canonical: Hash
    decisions: Hash
    bindings: Hash


class BPolicy(Bx):
    version: Literal["zoop-public-projection-policy-1"]
    files: BPolicyFiles
    evidence_id_kind: Literal["graph-body-span"]
    offset_unit: Literal["unicode_code_point"]
    geography: Literal["operator-field-verdict"]
    structural: Literal["manual-operator-review"]
    sequence: Literal["s2-comparison-with-operator-decision"]
    source_support: Literal["origin-or-exact-text-union"]
    impacts: Literal["s3-independent-verifier-quote-effect"]
    issue_summary: Literal["zoop-issue-summary-policy-1"]


class BJob(Bx):
    job_id: Id
    input_digest: Hash


class BUpstream(Bx):
    job_id: Id
    input_digest: Hash
    digest: Hash


class BSourcePolicyVersions(Bx):
    producer: Name
    verifier: Name
    impact_producer: Name
    impact_verifier: Name
    revalidation_policy: Name
    impact_policy: Name


class BRetainedSourcePolicies(BSourcePolicyVersions):
    policy: Literal["zoop-relation-policy-1"]


class BSourcePolicies(BSourcePolicyVersions):
    policy: Literal["zoop-relation-policy-2"]
    country_context: Literal["zoop-country-context-1"]


class BEligibility(Bx):
    eligible: Count
    hold: Count
    reject: Count
    pending: Count


class BAudit(Bx):
    s3_relations: Count
    eligibility: BEligibility
    review_pending: Count
    impact_candidates: Count
    eligible_not_public_by_type: CountMap


class BApprovalBasis(Bx):
    """Why one S3 relation was eligible when the producer used it: the automatic verifier's verdict (`reviewer` null) or an operator's final approval
    (`reviewer` the approving principal). `revision` is the deciding chain event's sequence."""
    kind: Literal["automatic-verifier", "operator-final-approval"]
    revision: Annotated[int, Field(ge=1)]
    reviewer: Reviewer | None
    decided_at: Stamp

    @model_validator(mode="after")
    def reviewer_only_for_a_human(self) -> BApprovalBasis:
        if (self.reviewer is None) != (self.kind == "automatic-verifier"):
            raise ValueError("reviewer is null exactly for the automatic verifier")
        return self


class BReviewUse(Bx):
    """The chain revision of one relation the bundle used, with the basis that made it eligible (`approvalBasis.revision` equals `revision`)."""
    relation_candidate_id: Annotated[str, StringConstraints(pattern=RC_PATTERN)]
    revision: Annotated[int, Field(ge=1)]
    approval_basis: BApprovalBasis

    @model_validator(mode="after")
    def basis_is_the_used_revision(self) -> BReviewUse:
        if self.approval_basis.revision != self.revision:
            raise ValueError("approvalBasis.revision must equal the used revision")
        return self


class BSourceProvenance(Bx):
    """The execution provenance of ONE S3 source job. Every source of a bundle carries exactly the bundle's own triple (the producer withholds a mix)."""
    source_kind: SourceKind
    execution_mode: Literal["replay", "live"]
    recording_kind: Literal["authored-test", "provider"]

    @model_validator(mode="after")
    def pair(self) -> BSourceProvenance:
        if (self.execution_mode, self.recording_kind) not in (("replay", "authored-test"), ("live", "provider")):
            raise ValueError("executionMode and recordingKind disagree")
        return self


class BSource(Bx):
    relation: BJob
    upstream: BUpstream
    review_digest: Hash
    provenance: BSourceProvenance
    policies: Annotated[Union[BRetainedSourcePolicies, BSourcePolicies], Field(discriminator="policy")]
    review_used: Annotated[list[BReviewUse], Field(max_length=MAX_RELATIONS)]
    audit: BAudit


class BCompany(Bx):
    id: Id
    canonical_id: Id
    label: Annotated[str, StringConstraints(max_length=MAX_TEXT)]
    decision_ref: Id


class BObservationRef(Bx):
    round_id: Name
    source_id: Name
    page: Count
    ordinal: Count
    document_id: Name
    raw_version: Hash
    document_version: Hash


class BSourceEvent(Bx):
    upstream: BJob
    kind: Literal["event-candidate", "snapshot-event"]
    ref: Name
    mention_id: Name
    document_id: Id
    document_version: Hash
    observation: BObservationRef


class BGeographyBasis(BSourceEvent):
    countries: Countries


class BGeography(Bx):
    value: Literal["domestic", "international"]
    decision_ref: Id
    decision_version: Id
    policy_version: Literal["zoop-public-projection-policy-1"]
    countries: Countries
    verification: Literal["operator-field-verdict"]
    evidence_ids: EvidenceIds
    basis: Annotated[list[BGeographyBasis], Field(max_length=1000)]


class BParticipant(Bx):
    """A participant exactly as the S2 mention states it. `role` is the S2 text, never a confirmed role; `company_id` is the public company id only where every
    carrying upstream mapped `source_company_id` to the same company of this bundle, otherwise null."""
    source_company_id: MentionText | None
    company_id: Id | None
    name: MentionText
    role: MentionText


class BMention(Bx):
    """One original S2 mention of the issue, identified by its source document version and S2 local id (a local id is unique only within one document version).
    `verification` is always `none`: these are S2 candidate or snapshot values, never verified, decided or approved fields."""
    document_id: Id
    document_version: Hash
    mention_id: Name
    article_id: Annotated[str, StringConstraints(pattern=ARTICLE_ID_PATTERN)]
    article_version: Hash
    verification: Literal["none"]
    title: MentionText
    action: MentionText
    target: MentionText | None
    event_time: Stamp | None
    time_precision: Literal["year", "month", "day", "datetime", "unknown"]
    period: MentionText | None
    assertion_status: Literal["occurred", "announced", "planned", "forecast", "cancelled", "unknown"]
    background: bool
    participants: Annotated[list[BParticipant], Field(max_length=1000)]
    evidence_ids: Annotated[list[Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN)]], Field(min_length=1, max_length=MAX_EVIDENCE)]


class BMentionRef(Bx):
    """The identity of one original mention of the same issue (a reference, never a copy of its values)."""
    document_id: Id
    document_version: Hash
    mention_id: Name


SameValueList = Annotated[list[BMentionRef], Field(min_length=1, max_length=1000)]


class BSameValueMentions(Bx):
    """Per headline field, the mentions whose own value equals the issue's value exactly (null equals null, no normalisation). Shape only: the producer owns the
    exactness, order and closure of these lists."""
    title: SameValueList
    action: SameValueList
    target: SameValueList
    event_time: SameValueList
    period: SameValueList
    assertion_status: SameValueList


class BFieldVerdict(Bx):
    """An operator's per-field verdict on one original mention's `eventTime` or `period` value, exactly as reviewed. Shape only: the producer owns binding,
    evidence closure, order and the effect on the issue's headline. There is no free-text reason and never AI output."""
    document_id: Id
    document_version: Hash
    mention_id: Name
    field: Literal["eventTime", "period"]
    value: MentionText
    decision: Literal["ALLOW", "HOLD", "REJECT"]
    reason_code: Literal["stated", "unstated", "ambiguous", "contradicted"]
    evidence_ids: Annotated[list[Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN)]], Field(max_length=20)]
    verification: Literal["operator-field-verdict"]
    reviewer: Id
    decision_ref: Id
    decision_version: Id

    @model_validator(mode="after")
    def _code_and_evidence_shape(self) -> "BFieldVerdict":
        allowed = {"ALLOW": ("stated", 1), "HOLD": None, "REJECT": ("contradicted", 1)}
        spans = len(self.evidence_ids)
        if self.decision == "HOLD":
            ok = (self.reason_code == "unstated" and spans == 0) or (self.reason_code == "ambiguous" and spans >= 1)
        else:
            code, minimum = allowed[self.decision]  # type: ignore[misc]
            ok = self.reason_code == code and spans >= minimum
        if not ok:
            raise ValueError("verdict decision, reasonCode and evidence count do not combine")
        return self


class BSourceSupport(Bx):
    """How many independent sources the issue's cited article versions represent. `knownLineageCount` counts lineage groups that have a declared origin
    (never articles), `duplicateGroups` are groups of articles whose prepared text is exactly equal (never transitive components) and
    `independentSourceCount` is null whenever an origin is missing or conflicting. Shape only: the producer owns every count."""
    article_count: Count
    known_lineage_count: Count
    unknown_lineage_articles: Annotated[list[Annotated[str, StringConstraints(pattern=ARTICLE_ID_PATTERN)]], Field(max_length=MAX_ARTICLES)]
    independent_source_count: Count | None
    duplicate_groups: Annotated[list[Annotated[list[Annotated[str, StringConstraints(pattern=ARTICLE_ID_PATTERN)]], Field(min_length=2, max_length=MAX_ARTICLES)]],
                                Field(max_length=MAX_ARTICLES)]


class BFieldProvenance(Bx):
    """How the producer chose the issue's six headline values: `unanimous` (every mention states them) or `operator-representative` (the operator's single
    representative decision). `verification` is always `none`: this is the actual selection, never a verification, support or approval of any value.
    `withheld` lists the fields (`eventTime`, `period` order) whose headline the producer set to null because of an operator HOLD or REJECT."""
    selection: Literal["unanimous", "operator-representative"]
    verification: Literal["none"]
    same_value_mentions: BSameValueMentions
    withheld: Annotated[list[Literal["eventTime", "period"]], Field(max_length=2)]


# ---- the issue summary (`issues[].summary`, bundle `-7`) --------------------------------------------------------------------

EvidenceId = Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN)]


class BSummarySource(Bx):
    """The immutable summary job result this value came from: the job, its input digest, the digest of its result and the basis digest of the issue input it was
    written for. A deterministic `unavailable` value has no job and therefore no source (`null`)."""
    job_id: Id
    input_digest: Hash
    result_digest: Hash
    basis_digest: Hash


class BSummaryClaim(Bx):
    """One sentence of an available summary with the quote evidence ids it rests on (1..5, sorted, unique, all inside the issue's own input basis)."""
    claim_id: Annotated[str, StringConstraints(pattern=r"^c[1-5]$")]
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_CLAIM_TEXT)]
    evidence_ids: Annotated[list[EvidenceId], Field(min_length=1, max_length=MAX_CLAIM_QUOTES)]

    @model_validator(mode="after")
    def one_korean_line_over_sorted_unique_quotes(self) -> BSummaryClaim:
        if "\n" in self.text or "\r" in self.text or not _hangul(self.text):
            raise ValueError("a claim is one line of text with at least one Hangul syllable")
        if self.evidence_ids != sorted(set(self.evidence_ids)):
            raise ValueError("a claim's evidenceIds are sorted and unique")
        return self


class BSummaryProducer(Bx):
    """Who wrote the claims. `kind` pairs with the bundle's execution mode: `authored-replay` (an authored answer, no model, `model` and `reasoningEffort` null) in a
    replay bundle, `provider` (a named model and reasoning effort) in a live one."""
    kind: Literal["authored-replay", "provider"]
    model: Name | None
    reasoning_effort: Annotated[str, StringConstraints(min_length=1, max_length=50)] | None
    prompt_version: Name
    schema_digest: Hash
    runtime_identity: Hash


class BSummaryVerifier(Bx):
    """Who checked the claims against the quotes. `authored-replay` in a replay bundle (never an independent model's verdict), `independent-verifier` in a live one."""
    kind: Literal["authored-replay", "independent-verifier"]
    model: Name | None
    adapter_identity: Hash
    request_digest: Hash


class BSummaryAvailable(Bx):
    """A verified multi-article summary of ONE issue: 1..5 claims, each cited to quote evidence of the issue's own mentions. Its closure with the issue (basis digest,
    result version, result digest, evidence ids inside the basis, execution-mode kinds) is `check_issue_summary`; what this model fixes is the shape and everything a
    value says about itself (claim ids `c1..cn`, `text` = claims joined by a newline, `evidenceIds` = the sorted union of the claims', a strict offset-aware `generatedAt`)."""
    status: Literal["available"]
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_CLAIMS * (MAX_CLAIM_TEXT + 1) - 1)]
    claims: Annotated[list[BSummaryClaim], Field(min_length=1, max_length=MAX_CLAIMS)]
    evidence_ids: Annotated[list[EvidenceId], Field(min_length=1, max_length=MAX_CLAIMS * MAX_CLAIM_QUOTES)]
    generated_at: Stamp
    result_version: Annotated[str, StringConstraints(pattern=r"^isr-[a-f0-9]{64}$")]
    language: Literal["ko"]
    source: BSummarySource
    producer: BSummaryProducer
    verifier: BSummaryVerifier

    @model_validator(mode="after")
    def text_evidence_and_time_say_what_the_claims_say(self) -> BSummaryAvailable:
        if [c.claim_id for c in self.claims] != [f"c{n}" for n in range(1, len(self.claims) + 1)]:
            raise ValueError("claim ids are c1..cn in order")
        if self.text != "\n".join(c.text for c in self.claims):
            raise ValueError("text is the claims joined by a newline")
        if self.evidence_ids != sorted({i for c in self.claims for i in c.evidence_ids}):
            raise ValueError("evidenceIds is the sorted union of the claims' evidenceIds")
        if not summary_time_valid(self.generated_at):
            raise ValueError("generatedAt is a strict offset-aware time: YYYY-MM-DDTHH:MM:SS[.f{1,9}](Z|+HH:MM|-HH:MM)")
        return self


class BSummaryUnavailable(Bx):
    """No summary text exists. A deterministic `code` (`not-requested`, `temporal-review-pending`, `input-too-large`) has no job behind it (`source` null); a job
    `code` (`producer-invalid`, `verifier-hold`, `verifier-reject`) names the pinned result of the job that failed. It is never an empty available summary."""
    status: Literal["unavailable"]
    code: Literal["not-requested", "temporal-review-pending", "input-too-large", "producer-invalid", "verifier-hold", "verifier-reject"]
    source: BSummarySource | None

    @model_validator(mode="after")
    def a_job_code_names_its_job_and_a_deterministic_one_has_none(self) -> BSummaryUnavailable:
        if (self.source is None) != (self.code in SUMMARY_DETERMINISTIC):
            raise ValueError("source is null exactly for a deterministic code")
        return self


Summary = Annotated[Union[BSummaryAvailable, BSummaryUnavailable], Field(discriminator="status")]


def _hangul(text: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in text)


# The shared summary-time grammar (producer `issue_summary_contracts`, app `HandoffTime`, these rules: `api/src/test/resources/graph-handoff/summary-time-vectors.json` is read by all
# three). ASCII only, uppercase `T` and `Z`, seconds required, an optional fraction of 1..9 digits, a MANDATORY offset (`Z` or `+HH:MM` / `-HH:MM`, hour:minute with a colon, at most
# 18:00 in either direction), a real calendar date and clock time in years 1..9999. No basic (compact) form, no space or lowercase separator, no week or ordinal date, no leap
# second. It is deliberately NOT `datetime.fromisoformat`, which also takes forms another language refuses.
_SUMMARY_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?(Z|[+-]([0-9]{2}):([0-9]{2}))", re.ASCII)


def summary_time_valid(value: Any) -> bool:
    found = _SUMMARY_TIME.fullmatch(value) if isinstance(value, str) else None
    if found is None:
        return False
    year, month, day, hour, minute, second = (int(found.group(n)) for n in range(1, 7))
    try:
        datetime(year, month, day, hour, minute, second)         # years 1..9999, a real calendar day, hour 0..23, minute and second 0..59
    except ValueError:
        return False
    if found.group(7) != "Z":
        offset_hours, offset_minutes = int(found.group(8)), int(found.group(9))
        return offset_minutes <= 59 and offset_hours * 60 + offset_minutes <= 18 * 60
    return True


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# The pure rules below take plain bundle dictionaries, exactly as the producer's `issue_summary_contracts` does, so the bundle model, the authored examples and the
# tests derive every digest from ONE definition. `issue` needs only `id`, `title`, `mentions[].evidenceIds/background` and `fieldVerdicts[].decision`; `evidence` maps an
# evidence id to a record with `articleId`, `articleVersion`, `start`, `end`, `quoteSha256`; `articles` maps (articleId, articleVersion) to a record with `documentId`,
# `documentVersion`, `textSha256`.

def temporal_review_pending(issue: dict[str, Any]) -> bool:
    """Any operator field verdict of the issue (on ANY mention, representative or not) that is HOLD or REJECT. Only `eventTime` and `period` are judged."""
    return any(v["decision"] in SUMMARY_HELD_DECISIONS for v in issue["fieldVerdicts"])


def summary_basis(issue: dict[str, Any], evidence: dict[str, dict[str, Any]], articles: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    """The exact model input of one issue (the producer's `summary_basis`): its title and the union of `mentions[].evidenceIds` sorted by evidence id, each quote pinned
    to its article version and quote hash. A quote is `background` only when EVERY mention citing it is a background mention. Geography-only and verdict-only evidence is
    never part of it. A KeyError means the bundle does not hold an evidence row or article the basis names."""
    background: dict[str, bool] = {}
    for mention in issue["mentions"]:
        for ident in mention["evidenceIds"]:
            background[ident] = background.get(ident, True) and mention["background"] is True
    quotes, used = [], {}
    for ident in sorted(background):
        record = evidence[ident]
        key = (record["articleId"], record["articleVersion"])
        article = articles[key]
        used[key] = {"articleId": key[0], "articleVersion": key[1], "documentId": article["documentId"], "documentVersion": article["documentVersion"],
                     "textSha256": article["textSha256"]}
        quotes.append({"evidenceId": ident, "articleId": key[0], "articleVersion": key[1], "start": record["start"], "end": record["end"],
                       "quoteSha256": record["quoteSha256"], "context": "background" if background[ident] else "report"})
    return {"policy": SUMMARY_POLICY, "issueId": issue["id"], "title": issue["title"], "quotes": quotes, "articles": [used[key] for key in sorted(used)]}


def basis_digest(basis: dict[str, Any]) -> str:
    return _digest(basis)


def deterministic_code(issue: dict[str, Any], basis: dict[str, Any]) -> str | None:
    """The zero-call rule table, in order: a held or rejected time field, then an oversized input. None means a job may exist for this issue."""
    if temporal_review_pending(issue):
        return "temporal-review-pending"
    if len(basis["quotes"]) > MAX_QUOTES:
        return "input-too-large"
    return None


def result_version(basis_digest_: str, claims: list[dict[str, Any]]) -> str:
    """Content identity of an available summary: the basis it was written for and its claims. Never a time, a job id or a runtime."""
    return "isr-" + _digest({"basisDigest": basis_digest_, "claims": claims})


def result_digest(job_id: str, input_digest: str, basis_digest_: str, body: dict[str, Any]) -> str:
    """The digest a decisions pin and the bundle `source` carry: the job identity and basis around the result `body` (the summary without `source`)."""
    return _digest({"jobId": job_id, "inputDigest": input_digest, "basisDigest": basis_digest_, "result": body})


def check_issue_summary(issue: BIssue, evidence: dict[str, dict[str, Any]], articles: dict[tuple[str, str], dict[str, Any]], execution: tuple[str, str]) -> None:
    """The producer's `check_summary` over one issue of the bundle, recomputed from the bundle itself. A deterministic code is accepted only while its own condition
    holds (a held issue carries no other value, `available` included, and `not-requested` only while no deterministic rule applies); a job-coded or `available` value
    only while no deterministic rule applies and only for the exact basis it was produced for (basis digest, result digest, result version, claim evidence inside the
    issue's own input quotes, producer and verifier kinds of the bundle's execution mode). `execution` is the bundle's (executionMode, recordingKind). Raises ValueError."""
    view = {"id": issue.id, "title": issue.title, "mentions": [{"evidenceIds": m.evidence_ids, "background": m.background} for m in issue.mentions],
            "fieldVerdicts": [{"decision": v.decision} for v in issue.field_verdicts]}
    try:
        basis = summary_basis(view, evidence, articles)
    except KeyError:
        raise ValueError("an issue's summary basis names evidence or an article the bundle does not hold") from None
    expected, digest, summary = deterministic_code(view, basis), basis_digest(basis), issue.summary
    if isinstance(summary, BSummaryUnavailable):
        if summary.code in SUMMARY_DETERMINISTIC:
            if summary.code != (expected or "not-requested"):
                raise ValueError("a deterministic summary code applies exactly while its own condition holds")
            return
        source = summary.source
        if expected is not None or source is None or source.basis_digest != digest or source.result_digest != result_digest(
                source.job_id, source.input_digest, digest, {"status": "unavailable", "code": summary.code}):
            raise ValueError("a job-coded unavailable summary needs the issue's basis, no deterministic code and its own result digest")
        return
    if expected is not None:
        raise ValueError("an issue with a deterministic summary code carries no available summary")
    kinds = SUMMARY_KINDS.get(execution)
    if kinds is None or (summary.producer.kind, summary.verifier.kind) != kinds:
        raise ValueError("the summary's producer and verifier kinds pair with the bundle's execution mode")
    live = execution[0] == "live"
    if (summary.producer.model is not None) != live or (summary.producer.reasoning_effort is not None) != live or (summary.verifier.model is not None) != live:
        raise ValueError("a model and reasoning effort are named exactly in a live bundle")
    allowed = {q["evidenceId"] for q in basis["quotes"]}
    if any(i not in allowed for claim in summary.claims for i in claim.evidence_ids):
        raise ValueError("a claim cites only the issue's own input quotes")
    if summary.result_version != result_version(digest, [claim.wire() for claim in summary.claims]):
        raise ValueError("resultVersion is the digest of the basis and the claims")
    body = {k: v for k, v in summary.wire().items() if k != "source"}
    source = summary.source
    if source.basis_digest != digest or source.result_digest != result_digest(source.job_id, source.input_digest, digest, body):
        raise ValueError("the summary's source pins the issue's basis and the result it carries")


class BIssue(Bx):
    id: Id
    canonical_id: Id
    title: Text
    action: Text | None
    target: Text | None
    event_time: Stamp | None
    time_precision: Literal["year", "month", "day", "datetime", "unknown"]
    period: Text | None
    assertion_status: Text | None
    geography: BGeography
    evidence_ids: EvidenceIds
    source_events: Annotated[list[BSourceEvent], Field(max_length=1000)]
    mentions: Annotated[list[BMention], Field(max_length=1000)]
    decision_ref: Id
    representative: BSourceEvent | None
    field_provenance: BFieldProvenance
    field_verdicts: Annotated[list[BFieldVerdict], Field(max_length=2000)]
    source_support: BSourceSupport
    summary: Summary


class BSourceRef(Bx):
    kind: Literal["s2-comparison", "s3-relation"]
    job_id: Id
    id: Name


class BSourceRelation(Bx):
    job_id: Id
    relation_candidate_id: Annotated[str, StringConstraints(pattern=RC_PATTERN)]


class BSourceArticle(Bx):
    article_id: Annotated[str, StringConstraints(pattern=ARTICLE_ID_PATTERN)]
    article_version: Hash


MAX_SCOPE = 500
Scope = Annotated[str, StringConstraints(max_length=MAX_SCOPE)] | None


class BBasis(Bx):
    source_relation: BSourceRelation
    relation_key: Hash
    relation_type: Literal["SUPPLIES"]
    business_scope: Scope
    product_scope: Scope
    valid_from: Stamp | None
    valid_until: Stamp | None
    countries: Countries
    verified_at: Stamp
    source_articles: Annotated[list[BSourceArticle], Field(max_length=1000)]
    evidence_ids: EvidenceIds


class BPathLink(Bx):
    supplier_company_id: Id
    customer_company_id: Id


class BStructuralComplete(Bx):
    """An ordered chain [participant, (mapped middle,) target] with one directed supplier→customer link per S3 basis. Operator-mapped basis chain only."""
    status: Literal["complete"]
    company_ids: Annotated[list[Id], Field(min_length=2, max_length=3)]
    links: Annotated[list[BPathLink], Field(min_length=1, max_length=2)]

    @model_validator(mode="after")
    def chain_and_links_agree(self) -> BStructuralComplete:
        ids = self.company_ids
        if len(set(ids)) != len(ids) or len(self.links) != len(ids) - 1:
            raise ValueError("companyIds must be distinct with exactly one link per adjacent pair")
        for (left, right), link in zip(zip(ids, ids[1:]), self.links):
            if {link.supplier_company_id, link.customer_company_id} != {left, right} or left == right:
                raise ValueError("each link must join its adjacent companyIds")
        return self


class BStructuralUnavailable(Bx):
    status: Literal["unavailable"]
    reason: Literal["intermediate_company_unmapped"]


StructuralPath = Annotated[Union[BStructuralComplete, BStructuralUnavailable], Field(discriminator="status")]


class BInvolvesProvenance(Bx):
    origin: Literal["s3-relation"]
    s3_semantic_validation: Literal["independent-verifier-supported-all-claims", "manual-operator-final-approval"]


class BStructuralProvenance(Bx):
    origin: Literal["manual-operator-review"]
    s3_semantic_validation: Literal["none"]
    status: Literal["operator-asserted"]
    reviewer: Id
    decision_ref: Id
    decision_version: Id
    binding_digest: Hash
    basis_eligibility: Literal["s3-independent-verifier-supported-all-claims", "s3-operator-final-approval"]


class BFollowsProvenance(Bx):
    origin: Literal["s2-comparison-with-operator-decision"]
    s3_semantic_validation: Literal["none"]
    s2_relation: Literal["FOLLOWS"]
    evidence_gate: Literal["exact-source-citation-in-incoming-article"]
    group_digest: Hash
    decision_ref: Id
    decision_version: Id


Provenance = Annotated[Union[BInvolvesProvenance, BStructuralProvenance, BFollowsProvenance], Field(discriminator="origin")]


class BRelation(Bx):
    id: Id
    type: Literal["INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS"]
    source: Id
    target: Id
    role: Name | None
    assertion_status: Text | None
    evidence_ids: EvidenceIds
    basis: Annotated[list[BBasis], Field(max_length=2)]
    structural_path: StructuralPath | None
    provenance: Provenance
    decision_ref: Id | None
    source_refs: Annotated[list[BSourceRef], Field(max_length=MAX_RELATIONS)]

    @model_validator(mode="after")
    def path_only_for_a_structural_relation(self) -> BRelation:
        path = self.structural_path
        if (path is None) != (self.type != "STRUCTURALLY_RELATED_TO"):
            raise ValueError("structuralPath is present exactly on STRUCTURALLY_RELATED_TO")
        if isinstance(path, BStructuralComplete):
            if len(path.links) != len(self.basis) or path.company_ids[-1] != self.target:
                raise ValueError("a complete path has one link per basis and ends at the relation target")
        elif path is not None and len(self.basis) != 2:
            raise ValueError("an unavailable path is only possible for a two-basis relation")
        return self


ImpactLabel = Literal["positive", "negative", "mixed", "undetermined"]
IMPACT_CANDIDATE_PATTERN = r"^ic-[a-f0-9]{64}$"
WITHHELD_CODES = ("impact_evidence_outside_relation_documents", "impact_quote_ambiguous")
MAX_EFFECT_IDS = 40
EffectIds = Annotated[list[Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN)]], Field(max_length=MAX_EFFECT_IDS)]


class BImpactProposal(Bx):
    """The producer's UNVERIFIED private proposal (direction, reason, limitations): never a verified reason. Lengths are Unicode code points."""
    direction: ImpactLabel
    reason: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    limitations: Annotated[str, StringConstraints(max_length=1000)] | None
    verification: Literal["none"]


class BImpactEffects(Bx):
    """The verifier-mapped app evidence ids per effect side: sorted, unique, disjoint, 1..40 in all."""
    positive: EffectIds
    negative: EffectIds
    neutral: EffectIds
    uncertain: EffectIds

    @model_validator(mode="after")
    def sides_are_sorted_unique_disjoint_and_bounded(self) -> BImpactEffects:
        sides = (self.positive, self.negative, self.neutral, self.uncertain)
        if any(side != sorted(set(side)) for side in sides):
            raise ValueError("every effect side is sorted and unique")
        union = [i for side in sides for i in side]
        if len(union) != len(set(union)) or not 1 <= len(union) <= MAX_EFFECT_IDS:
            raise ValueError("effect sides are disjoint and hold 1..40 evidence ids in all")
        return self

    def all_ids(self) -> list[str]:
        return [*self.positive, *self.negative, *self.neutral, *self.uncertain]


def impact_label(target_verdict: str, effects: BImpactEffects) -> str:
    if effects.uncertain or target_verdict == "insufficient":
        return "undetermined"
    if effects.positive and effects.negative:
        return "mixed"
    if effects.positive:
        return "positive"
    if effects.negative:
        return "negative"
    return "undetermined"


class BImpact(Bx):
    """One impact row per emitted INVOLVES source relation: the independent verifier's mapped effect on the company, or why there is none. Never a public
    label of the event, never causality or price probability."""
    edge_id: Id
    issue_id: Id
    company_id: Id
    source_relation: BSourceRelation
    impact_candidate_id: Annotated[str, StringConstraints(pattern=IMPACT_CANDIDATE_PATTERN)] | None
    status: Literal["not-applicable", "not-proposed", "no-evidence", "technical-reject", "verifier-reject", "verified", "withheld"]
    code: Literal["producer_reply_invalid", "impact_precheck_rejected", "verifier_reply_invalid",
                  "impact_evidence_outside_relation_documents", "impact_quote_ambiguous"] | None
    label: ImpactLabel | None
    target_verdict: Literal["supported", "insufficient", "contradicted"] | None
    effects: BImpactEffects | None
    verifier: Literal["called", "not-called"]
    verifier_request_digest: Hash | None
    proposal: BImpactProposal | None

    @model_validator(mode="after")
    def state_table(self) -> BImpact:
        s, c = self.status, self.code
        called = self.verifier == "called"
        has_ic, has_proposal = self.impact_candidate_id is not None, self.proposal is not None
        if called != (self.verifier_request_digest is not None):
            raise ValueError("verifierRequestDigest is present exactly when the verifier was called")
        verified = s == "verified"
        if (self.label is not None) != verified or (self.effects is not None) != verified:
            raise ValueError("label and effects exist only on a verified row")
        if (self.target_verdict is not None) != (s in ("verified", "verifier-reject")):
            raise ValueError("targetVerdict exists only on verified and verifier-reject rows")
        if verified:
            if self.target_verdict not in ("supported", "insufficient") or self.label != impact_label(self.target_verdict, self.effects):  # type: ignore[arg-type]
                raise ValueError("a verified row has a supported or insufficient target and its deterministic label")
        if s == "verifier-reject" and self.target_verdict != "contradicted":
            raise ValueError("a verifier-reject row is a contradicted target")
        if s in ("not-applicable", "not-proposed"):
            ok = c is None and not has_ic and not called and not has_proposal
        elif s == "no-evidence":
            ok = c is None and has_ic and not called and has_proposal
        elif s == "technical-reject":
            ok = {"producer_reply_invalid": not has_ic and not called and not has_proposal,
                  "impact_precheck_rejected": has_ic and not called and not has_proposal,
                  "verifier_reply_invalid": has_ic and called and has_proposal}.get(c or "", False)
        elif s in ("verifier-reject", "verified"):
            ok = c is None and has_ic and called and has_proposal
        else:
            ok = c in WITHHELD_CODES and has_ic and called and has_proposal
        if not ok:
            raise ValueError("status, code, impactCandidateId, verifier and proposal do not combine")
        return self


class BEvidenceSource(Bx):
    document_id: Name
    document_version: Hash
    raw_version: Hash
    text_artifact_id: Name
    source_evidence_id: Annotated[str, StringConstraints(pattern=SOURCE_EVIDENCE_ID_PATTERN)]
    input_kind: Literal["body"]


class BEvidence(Bx):
    id: Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN)]
    kind: Literal["graph-body-span"]
    article_id: Annotated[str, StringConstraints(pattern=ARTICLE_ID_PATTERN)]
    article_version: Hash
    start: Count
    end: Annotated[int, Field(ge=1)]
    offset_unit: Literal["unicode_code_point"]
    quote_sha256: Hash
    raw_locator_ids: Annotated[list[Annotated[str, StringConstraints(max_length=400)]], Field(max_length=1000)]
    source: BEvidenceSource


class BGrant(Bx):
    grant_id: Name
    revision: Name


class BObservation(Bx):
    round_id: Name
    source_id: Name
    page: Count
    ordinal: Count
    observed_at: Stamp
    grant: BGrant


class BArticleOrigin(Bx):
    """The operator's declared origin of one article version (never inferred from a publisher, domain or source id)."""
    origin_id: Id
    reviewer: Id
    decision_ref: Id
    decision_version: Id
    verification: Literal["operator-declared-origin"]


class BArticle(Bx):
    article_id: Annotated[str, StringConstraints(pattern=ARTICLE_ID_PATTERN)]
    article_version: Hash
    document_id: Name
    document_version: Hash
    raw_version: Hash
    text_sha256: Hash
    origin: BArticleOrigin | None
    title: Annotated[str, StringConstraints(max_length=2000)]
    url: Annotated[str, StringConstraints(max_length=4000)]
    published_at: Stamp | None
    publication_precision: Literal["datetime", "day", "unknown"]
    observations: Annotated[list[BObservation], Field(min_length=1, max_length=1000)]


class BConflictDetail(Bx):
    fields: Annotated[list[Literal["title", "action", "target", "eventTime", "period", "assertionStatus"]], Field(min_length=1, max_length=6)]


class BBindingDetail(Bx):
    expected_binding_digest: Hash


class BExclusionItem(Bx):
    kind: Literal["issue", "relation", "structural", "follows"]
    id: Text
    job_id: Id | None
    code: Id
    detail: BConflictDetail | BBindingDetail | None = None


class BExclusions(Bx):
    counts: CountMap
    items: Annotated[list[BExclusionItem], Field(max_length=MAX_EXCLUSIONS)]


class BRelationCounts(Bx):
    involves: Count = Field(alias="INVOLVES")
    structurally_related_to: Count = Field(alias="STRUCTURALLY_RELATED_TO")
    follows: Count = Field(alias="FOLLOWS")


class BCounts(Bx):
    companies: Count
    path_companies: Count
    impacts: Count
    issues: Count
    relations: BRelationCounts
    evidence: Count
    articles: Count
    exclusions: Count


CheckName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_]{1,100}$")]


class BChecks(Bx):
    producer_confirmed: Annotated[list[CheckName], Field(max_length=20)]
    app_import_pending: Annotated[list[CheckName], Field(max_length=20)]


class BReadiness(Bx):
    app: Literal["import-pending"]
    evidence_registration: Literal["not-registered"]
    public_activation: Literal["none"]
    graph_db: Literal["none"]


class BDigests(Bx):
    content: Hash


class Bundle(Bx):
    """The producer's artifact. Key names, order-free content and every value are the producer's; this class only says which shapes are acceptable."""
    schema_version: Literal["zoop-graph-handoff-bundle-7"]
    handoff_id: Id
    manifest_digest: Hash
    provenance: BProvenance
    policy: BPolicy
    sources: Annotated[list[BSource], Field(min_length=1, max_length=MAX_SOURCES)]
    companies: Annotated[list[BCompany], Field(max_length=MAX_COMPANIES)]
    path_companies: Annotated[list[BCompany], Field(max_length=MAX_COMPANIES)]
    issues: Annotated[list[BIssue], Field(max_length=MAX_ISSUES)]
    relations: Annotated[list[BRelation], Field(max_length=MAX_RELATIONS)]
    impacts: Annotated[list[BImpact], Field(max_length=MAX_RELATIONS)]
    evidence: Annotated[list[BEvidence], Field(max_length=MAX_EVIDENCE)]
    articles: Annotated[list[BArticle], Field(max_length=MAX_ARTICLES)]
    exclusions: BExclusions
    counts: BCounts
    checks: BChecks
    readiness: BReadiness
    digests: BDigests

    @model_validator(mode="after")
    def private_path_companies_close_over_the_complete_paths(self) -> Bundle:
        main = [c.id for c in self.companies]
        private = [c.id for c in self.path_companies]
        if private != sorted(set(private)) or set(private) & set(main) or set(private) & {i.id for i in self.issues}:
            raise ValueError("pathCompanies are sorted, unique and disjoint from companies and issues")
        participants: dict[str, set[str]] = {}
        for relation in self.relations:
            if relation.type == "INVOLVES":
                participants.setdefault(relation.source, set()).add(relation.target)
        used: set[str] = set()
        for relation in self.relations:
            path = relation.structural_path
            if not isinstance(path, BStructuralComplete):
                continue
            ids = path.company_ids
            here = participants.get(relation.source, set())
            if ids[0] not in here or ids[-1] in here or not {ids[0], ids[-1]} <= set(main):
                raise ValueError("a path starts at an INVOLVES participant of the same issue and ends at a non-participant main company")
            used.update(ids[1:-1])
        if used - set(main) != set(private):
            raise ValueError("pathCompanies must equal the mapped middle companies of complete paths that are not main companies")
        if self.counts.companies != len(main) or self.counts.path_companies != len(private):
            raise ValueError("counts.companies and counts.pathCompanies must equal the list lengths")
        self.impacts_close_over_the_involves_sources()
        return self

    @model_validator(mode="after")
    def issue_summaries_follow_the_decision_table(self) -> Bundle:
        """Every `issues[].summary` is recomputed from the bundle ITSELF (basis digest, deterministic temporal/input-size code, claim and result identity, execution-mode
        provenance), never trusted: see `check_issue_summary`. A bundle whose summary is missing, dropped or of another shape never reaches this point (the key is
        required and the models are closed)."""
        evidence = {e.id: {"articleId": e.article_id, "articleVersion": e.article_version, "start": e.start, "end": e.end, "quoteSha256": e.quote_sha256}
                    for e in self.evidence}
        articles = {(a.article_id, a.article_version): {"documentId": a.document_id, "documentVersion": a.document_version, "textSha256": a.text_sha256}
                    for a in self.articles}
        execution = (self.provenance.execution_mode, self.provenance.recording_kind)
        for issue in self.issues:
            check_issue_summary(issue, evidence, articles, execution)
        return self

    def impacts_close_over_the_involves_sources(self) -> None:
        """Exact one-row coverage of every emitted INVOLVES s3 sourceRef, endpoint/source-approval agreement and the evidence bindings of verified effects."""
        edges: dict[tuple[str, str, str], BRelation] = {}
        for r in self.relations:
            if r.type != "INVOLVES":
                continue
            if not r.source_refs or any(ref.kind != "s3-relation" for ref in r.source_refs):
                raise ValueError("an INVOLVES relation has at least one sourceRef and all of them are s3-relation")
            for ref in r.source_refs:
                if (r.id, ref.job_id, ref.id) in edges:
                    raise ValueError("INVOLVES sourceRefs are unique per edge")
                edges[(r.id, ref.job_id, ref.id)] = r
        keys = [(i.edge_id, i.source_relation.job_id, i.source_relation.relation_candidate_id) for i in self.impacts]
        if keys != sorted(set(keys)) or set(keys) != set(edges) or len(keys) > MAX_RELATIONS:
            raise ValueError("impacts are sorted, unique and cover exactly the INVOLVES s3 source relations")
        if self.counts.impacts != len(self.impacts):
            raise ValueError("counts.impacts must equal the impact list length")
        approvals = {(s.relation.job_id, u.relation_candidate_id): u.approval_basis.kind for s in self.sources for u in s.review_used}
        evidence = {e.id: e for e in self.evidence}
        seen: set[tuple[str, str]] = set()
        for impact, key in zip(self.impacts, keys):
            edge = edges[key]
            job, rc = key[1], key[2]
            if impact.code == "verifier_reply_invalid" and (self.provenance.execution_mode != "replay" or any(s.provenance.execution_mode != "replay" for s in self.sources)):
                raise ValueError("verifier_reply_invalid exists only in a replay bundle")
            if (impact.issue_id, impact.company_id) != (edge.source, edge.target):
                raise ValueError("an impact row repeats its edge endpoints")
            if (job, rc) not in approvals or (approvals[(job, rc)] == "operator-final-approval") != (impact.status == "not-applicable"):
                raise ValueError("an impact row is not-applicable exactly for an operator-final-approval source")
            if impact.impact_candidate_id is not None:
                if (job, impact.impact_candidate_id) in seen:
                    raise ValueError("an impact candidate belongs to one row per job")
                seen.add((job, impact.impact_candidate_id))
            if impact.effects is None:
                continue
            cited = {(evidence[e].article_id, evidence[e].article_version) for e in edge.evidence_ids if e in evidence}
            ids = impact.effects.all_ids()
            if any(e not in evidence or (evidence[e].article_id, evidence[e].article_version) not in cited for e in ids):
                raise ValueError("every effect evidence id is in the bundle and of an article version the edge cites")
            if len({evidence[e].source.source_evidence_id for e in ids}) != len(ids):
                raise ValueError("effect evidence of one row has distinct source evidence ids")


class BmSource(Bx):
    relation: BJob
    upstream: BUpstream
    review_digest: Hash


class HandoffManifest(Bx):
    """The operator's frozen manifest exactly as the producer's ledger stores it (closed at every level): pins and file hashes only, no path or secret.
    Its canonical JSON bytes hash to `verification.manifestDigest` and to the bundle's `manifestDigest`."""
    schema_version: Literal["zoop-ai-handoff-1"]
    handoff_id: Id
    source_kind: SourceKind
    policy_version: Literal["zoop-public-projection-policy-1"]
    sources: Annotated[list[BmSource], Field(min_length=1, max_length=MAX_SOURCES)]
    files: BPolicyFiles


# ---- what this service emits ----------------------------------------------------------------------------------------------

class HdDelivery(Rel):
    state: Literal["current", "withheld"]
    reason: Safe | None = None
    checked_at: str | None = Field(default=None, pattern=STAMP_PATTERN, description="The producer's own time of the current-authority check. null while withheld.")


class HdVerification(Rel):
    """What was verified for this very response: digests of the received bytes and the counts the bundle itself reports. No source id, text or title."""
    manifest_digest: str = Field(pattern=HASH_PATTERN)
    bundle_digest: str = Field(pattern=HASH_PATTERN, description="SHA-256 of the canonical UTF-8 bytes of the bundle; equals the operator's pin.")
    content_digest: str = Field(pattern=HASH_PATTERN)
    bundle_bytes: int
    counts: BCounts
    sources: int = Field(description="Number of S3 source jobs the handoff was frozen from.")
    provenance: BProvenance


class HdStatus(Rel):
    schema_version: Literal["zoop-ai-internal-handoff-1"] = SCHEMA
    handoff_id: str = Field(pattern=HANDOFF_ID_PATTERN)
    state: State
    publication: Literal["not-published"] = "not-published"
    app_import: Literal["pending"] = "pending"
    delivery: HdDelivery
    verification: HdVerification | None
    observed_at: str


class HdBundle(HdStatus):
    """The status fields plus the frozen `manifest` and the whole `bundle`, only while delivery is current. `manifest` and `bundle` are the producer's own
    artifacts exactly: the canonical JSON bytes of `manifest` hash to `verification.manifestDigest` (= `bundle.manifestDigest`), those of `bundle` to
    `verification.bundleDigest`, so the application can recompute both from this one response. Nothing the service adds is part of either; every
    service field is a sibling."""
    manifest: HandoffManifest | None
    bundle: Bundle | None

    def wire(self) -> dict[str, Any]:
        body = self.model_dump(by_alias=True, mode="json", exclude={"bundle", "manifest"})
        body["manifest"] = None if self.manifest is None else self.manifest.wire()
        body["bundle"] = None if self.bundle is None else self.bundle.wire()
        return body


class HdErrorEnvelope(Rel):
    schema_version: Literal["zoop-ai-internal-handoff-1"] = SCHEMA
    error: ErrorBody


# ---- what the producer reports (`zoop-ai-handoff export`) ------------------------------------------------------------------

class Projection(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore", strict=True)


class RtDelivery(Projection):
    status: Literal["current", "withheld"]
    code: str | None = None
    checked_at: str | None = Field(default=None, pattern=STAMP_PATTERN)


class RtUsage(Projection):
    provider_calls: Literal[0]
    model_calls: Literal[0]


class RtReceipt(Projection):
    handoff_id: str
    manifest_digest: str = Field(pattern=HASH_PATTERN)
    bundle_schema: Literal["zoop-graph-handoff-bundle-7"]
    bundle_digest: str = Field(pattern=HASH_PATTERN)
    content_digest: str = Field(pattern=HASH_PATTERN)
    bundle_bytes: int = Field(ge=1)


class Export(Projection):
    """An export result. A withheld one carries only identity, state, delivery and usage; a current one also carries receipt, manifest and bundle. Manifest
    and bundle are kept as the received objects here and only parsed into their closed models after the digests matched the operator's pins."""
    schema_version: Literal["zoop-ai-handoff-1"]
    handoff_id: str
    state: State
    publication: Literal["not-published"]
    delivery: RtDelivery
    usage: RtUsage
    receipt: RtReceipt | None = None
    bundle: dict[str, Any] | None = None
    manifest: dict[str, Any] | None = None
