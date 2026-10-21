"""Wire models of the read-only handoff family (`zoop-ai-internal-handoff-1`) and the CLOSED model of the `zoop-graph-handoff-bundle-5` bundle.

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
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from .relation_wire import Rel
from .wire import ErrorBody, Reviewer, Safe

SCHEMA = "zoop-ai-internal-handoff-1"
RUNTIME_SCHEMA = "zoop-ai-handoff-1"
BUNDLE_SCHEMA = "zoop-graph-handoff-bundle-5"
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


class BJob(Bx):
    job_id: Id
    input_digest: Hash


class BUpstream(Bx):
    job_id: Id
    input_digest: Hash
    digest: Hash


class BSourcePolicies(Bx):
    producer: Name
    verifier: Name
    impact_producer: Name
    impact_verifier: Name
    policy: Name
    revalidation_policy: Name
    impact_policy: Name


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
    policies: BSourcePolicies
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
    schema_version: Literal["zoop-graph-handoff-bundle-5"]
    handoff_id: Id
    manifest_digest: Hash
    provenance: BProvenance
    policy: BPolicy
    sources: Annotated[list[BSource], Field(min_length=1, max_length=MAX_SOURCES)]
    companies: Annotated[list[BCompany], Field(max_length=MAX_COMPANIES)]
    path_companies: Annotated[list[BCompany], Field(max_length=MAX_COMPANIES)]
    issues: Annotated[list[BIssue], Field(max_length=MAX_ISSUES)]
    relations: Annotated[list[BRelation], Field(max_length=MAX_RELATIONS)]
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
        return self


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
    bundle_schema: Literal["zoop-graph-handoff-bundle-5"]
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
