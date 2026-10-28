"""Independent, closed identity-only exposure wire contract. The CLI alone computes closure."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .handoff_wire import Bx, Hash, Id, Name, ARTICLE_ID_PATTERN, EVIDENCE_ID_PATTERN, RC_PATTERN
from .relation_wire import Rel

SCHEMA = "zoop-handoff-exposure-1"
MAX_COMMAND = 65_536
MAX_OUTPUT = 6 * 1024 * 1024
NOT_COVERED = ["unselected-handoffs", "history-only-handoffs", "app-versions-not-imported-from-selected-handoffs", "app-exclusion-state", "app-article-listing",
               "graph-versions", "s1-worker", "published-briefings", "chat", "pins", "caches", "issue-summary-ledger", "poc-repository"]
BASIS = {"source-change": ("complete model-input closure: S2 stage inputs per S4 (extract = incoming, compare = incoming + compared group), and every relation of an S3 "
                           "job whose S2 upstream binds an affected document under its frozen binding; frozen bundle artifacts of the selected handoffs; "
                           "current registry, rights and delivery were not evaluated"),
         "relation-retraction": ("the frozen bundle artifacts of the selected handoffs; only the named S3 relation (job and candidate) is retracted: "
                                 "no quote or document is withdrawn; current registry, rights and delivery were not evaluated")}
CONSISTENCY = "shared locks on every opened ledger were held from the first read until this output"
EFFECT = ("none: identity-only proposal for the selected handoffs; nothing was excluded, revised, overlaid, activated or written, "
          "and an empty or smaller result never clears or narrows any existing exclusion")


def ordered(values: list) -> list:
    if values != sorted(set(values)):
        raise ValueError("ordered unique identities required")
    return values


class DocumentChange(Bx):
    kind: Literal["document"]
    document_id: Name
    document_version: Hash | None
    raw_version: Hash | None


class SourceChange(Bx):
    kind: Literal["source"]
    source_id: Name


class GrantChange(Bx):
    kind: Literal["grant"]
    grant_id: Name
    revision: Name | None


class RelationChange(Bx):
    kind: Literal["s3-relation"]
    job_id: Id
    relation_candidate_id: Annotated[str, StringConstraints(pattern=RC_PATTERN)]


Change = Annotated[DocumentChange | SourceChange | GrantChange | RelationChange, Field(discriminator="kind")]


class ExposureQuery(Bx):
    schema_version: Literal["zoop-handoff-exposure-1"]
    handoff_ids: list[Id] = Field(min_length=1, max_length=20)
    changed: Change

    @field_validator("handoff_ids")
    @classmethod
    def unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate selection")
        return values


class ExposureArticle(Bx):
    article_id: Annotated[str, StringConstraints(pattern=ARTICLE_ID_PATTERN)]
    article_version: Hash
    document_id: Name
    document_version: Hash


class ExposureIssue(Bx):
    id: Id
    reasons: list[Literal["disposition-input", "involvement-lost", "source-document"]] = Field(min_length=1)

    @field_validator("reasons")
    @classmethod
    def unique(cls, values: list[str]) -> list[str]:
        return ordered(values)


class ExposureRelation(Bx):
    id: Id
    type: Literal["INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS"]
    reasons: list[Literal["anchor", "anchor-undetermined", "basis-evidence", "evidence", "issue", "source-relation", "upstream-input"]] = Field(min_length=1)

    @field_validator("reasons")
    @classmethod
    def unique(cls, values: list[str]) -> list[str]:
        return ordered(values)


class ExposureCounts(Bx):
    articles: int = Field(ge=0)
    issues: int = Field(ge=0)
    relations: int = Field(ge=0)
    evidence: int = Field(ge=0)


class ExposureHandoff(Bx):
    handoff_id: Id
    bundle_schema: Literal["zoop-graph-handoff-bundle-7"]
    manifest_digest: Hash
    bundle_digest: Hash
    content_digest: Hash
    bound: bool
    exposed: bool
    articles: list[ExposureArticle] = Field(max_length=1000)
    issues: list[ExposureIssue] = Field(max_length=2000)
    relations: list[ExposureRelation] = Field(max_length=10000)
    evidence_ids: list[Annotated[str, StringConstraints(pattern=EVIDENCE_ID_PATTERN)]] = Field(max_length=20000)
    counts: ExposureCounts

    @model_validator(mode="after")
    def consistent(self) -> ExposureHandoff:
        ordered([(a.article_id, a.article_version) for a in self.articles])
        ordered([i.id for i in self.issues])
        ordered([r.id for r in self.relations])
        ordered(self.evidence_ids)
        lengths = [len(self.articles), len(self.issues), len(self.relations), len(self.evidence_ids)]
        if lengths != [self.counts.articles, self.counts.issues, self.counts.relations, self.counts.evidence] or self.exposed != any(lengths):
            raise ValueError("inconsistent counts")
        if not self.bound and self.exposed:
            raise ValueError("unbound exposure")
        return self


class ExposureIdentity(Bx):
    bound_in_selection: bool
    recorded_in_ingestion: bool | None


class ExposureScope(Bx):
    selection: Literal["explicit"]
    handoff_ids: list[Id] = Field(min_length=1, max_length=20)
    not_covered: list[str]

    @model_validator(mode="after")
    def fixed(self) -> ExposureScope:
        ordered(self.handoff_ids)
        if self.not_covered != NOT_COVERED:
            raise ValueError("scope mismatch")
        return self


class ExposureUsage(Bx):
    provider_calls: Annotated[int, Field(ge=0, le=0)]
    model_calls: Annotated[int, Field(ge=0, le=0)]


class ExposureReport(Bx):
    schema_version: Literal["zoop-handoff-exposure-1"]
    changed: Change
    cause: Literal["source-change", "relation-retraction"]
    identity: ExposureIdentity
    scope: ExposureScope
    basis: str
    consistency: Literal[CONSISTENCY]
    effect: Literal[EFFECT]
    handoffs: list[ExposureHandoff] = Field(min_length=1, max_length=20)
    usage: ExposureUsage

    @model_validator(mode="after")
    def consistent(self) -> ExposureReport:
        relation = self.changed.kind == "s3-relation"
        if self.cause != ("relation-retraction" if relation else "source-change") or self.basis != BASIS[self.cause]:
            raise ValueError("cause mismatch")
        if [h.handoff_id for h in self.handoffs] != self.scope.handoff_ids:
            raise ValueError("selection mismatch")
        bound = any(h.bound for h in self.handoffs)
        if self.identity.bound_in_selection != bound:
            raise ValueError("identity mismatch")
        recorded = self.identity.recorded_in_ingestion
        if relation:
            if recorded is not None or not bound or any(h.articles or h.evidence_ids for h in self.handoffs):
                raise ValueError("relation identity mismatch")
        elif recorded is None or not (recorded or bound):
            raise ValueError("unknown identity")
        return self


class HdExposure(Rel):
    schema_version: Literal["zoop-ai-internal-handoff-1"] = "zoop-ai-internal-handoff-1"
    report: ExposureReport
