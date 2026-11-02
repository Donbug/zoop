"""Operator-only wire contract of the read-only handoff exposure report (`zoop-ai-handoff-exposure`). Not an S1 schema, HTTP route or application API.

One changed source identity or one retracted S3 relation goes in, together with the explicit handoff IDs to look at; identity-only lists of the public
issues, relations, evidence and articles of those frozen bundles come out. Nothing here evaluates current rights, writes a ledger, calls a model or
excludes, revises, overlays or activates anything.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from .dependency_contracts import DocumentChange, GrantChange, SourceChange
from .extraction_contracts import ExtractionFailure
from .handoff_contracts import ID, MAX_BUNDLE, RC
from .ingestion_contracts import Wire

__all__ = ["ExtractionFailure"]

SCHEMA = "zoop-handoff-exposure-1"
BUNDLE = "zoop-graph-handoff-bundle-8"
MAX_COMMAND = 65_536
MAX_HANDOFFS = 20
MAX_OUTPUT = MAX_BUNDLE
SOURCE_KINDS = ("document", "source", "grant")
CAUSES = {"document": "source-change", "source": "source-change", "grant": "source-change", "s3-relation": "relation-retraction"}

ISSUE_REASONS = ("disposition-input", "involvement-lost", "source-document")
RELATION_REASONS = ("anchor", "anchor-undetermined", "basis-evidence", "evidence", "issue", "source-relation", "upstream-input")
UNRESOLVED_REASONS = ("upstream_not_in_scanned_ledger", "upstream_input_mismatch", "upstream_binding_mismatch")

# What a report does NOT say. Listed in every report so an empty or narrow result is never read as global safety.
NOT_COVERED = ("unselected-handoffs", "history-only-handoffs", "app-versions-not-imported-from-selected-handoffs", "app-exclusion-state", "app-article-listing",
               "graph-versions", "s1-worker", "published-briefings", "chat", "pins", "caches", "issue-summary-ledger", "poc-repository")
BASIS = {"source-change": ("complete model-input closure: S2 stage inputs per S4 (extract = incoming, compare = incoming + compared group), and every relation of an S3 "
                           "job whose S2 upstream binds an affected document under its frozen binding; frozen bundle artifacts of the selected handoffs; "
                           "current registry, rights and delivery were not evaluated"),
         "relation-retraction": ("the frozen bundle artifacts of the selected handoffs; only the named S3 relation (job and candidate) is retracted: "
                                 "no quote or document is withdrawn; current registry, rights and delivery were not evaluated")}
CONSISTENCY = "shared locks on every opened ledger were held from the first read until this output"
EFFECT = ("none: identity-only proposal for the selected handoffs; nothing was excluded, revised, overlaid, activated or written, "
          "and an empty or smaller result never clears or narrows any existing exclusion")

Name = Annotated[str, StringConstraints(pattern=ID)]


class RelationChange(Wire):
    """A retracted S3 relation: always the job TOGETHER WITH its candidate id (a candidate id alone names nothing)."""
    kind: Literal["s3-relation"]
    job_id: Name
    relation_candidate_id: str = Field(pattern=RC)


class Query(Wire):
    schema_version: Literal["zoop-handoff-exposure-1"]
    handoff_ids: list[Name] = Field(min_length=1, max_length=MAX_HANDOFFS)
    changed: Annotated[DocumentChange | SourceChange | GrantChange | RelationChange, Field(discriminator="kind")]

    @field_validator("handoff_ids")
    @classmethod
    def _unique(cls, ids: list[str]) -> list[str]:
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate handoff id")
        return ids
