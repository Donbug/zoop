"""Prototype-owned offline S4 dependents-report wire contract. Not an S1 schema alias, HTTP route or application dependency API.

One changed identity goes in; frozen binding identities of the scanned ledgers come out. Nothing here evaluates current rights,
registry or delivery, writes a ledger, calls a model, or revokes/withholds/regenerates anything.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from .extraction_contracts import ExtractionFailure, ObservationRef
from .ingestion_contracts import Wire

__all__ = ["ExtractionFailure"]

SCHEMA = "zoop-dependency-s4"
MAX_COMMAND = 100_000
MAX_REPORT_ENTRIES = 10_000
# What a report over the scanned ledgers does NOT say. Listed in every report so completeness is never read as full withdrawal.
NOT_COVERED = ("ingestion-ledger-records", "s1-worker", "application-state", "published-briefings", "chat", "pins", "caches", "graphdb",
               "poc-repository", "unscanned-extraction-ledgers", "unscanned-relation-ledgers")
BASIS = "frozen bindings and stored candidate rows of the scanned ledgers; current registry, rights and delivery were not evaluated"
CONSISTENCY = "shared locks on every opened ledger were held from the first read until this output"
EFFECT = "report only: nothing was revoked, withheld, regenerated or published"

Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class DocumentChange(Wire):
    """A document; null versions mean every bound version (historical included), never a resolved 'latest'."""
    kind: Literal["document"]
    document_id: Name
    document_version: Hash | None
    raw_version: Hash | None


class SourceChange(Wire):
    kind: Literal["source"]
    source_id: Name


class GrantChange(Wire):
    """A grant as frozen into job bindings; a null revision means every bound revision, not the current registry's."""
    kind: Literal["grant"]
    grant_id: Name
    revision: Name | None


class Query(Wire):
    schema_version: Literal["zoop-dependency-s4"]
    changed: Annotated[DocumentChange | SourceChange | GrantChange, Field(discriminator="kind")]


def matcher(changed: DocumentChange | SourceChange | GrantChange) -> Callable[[ObservationRef, str, str], bool]:
    """Seed predicate over one frozen bound observation and the grant frozen beside it (never the current registry)."""
    if isinstance(changed, DocumentChange):
        return lambda ref, grant_id, revision: (ref.document_id == changed.document_id
                                                and (changed.document_version is None or ref.document_version == changed.document_version)
                                                and (changed.raw_version is None or ref.raw_version == changed.raw_version))
    if isinstance(changed, SourceChange):
        return lambda ref, grant_id, revision: ref.source_id == changed.source_id
    return lambda ref, grant_id, revision: grant_id == changed.grant_id and (changed.revision is None or revision == changed.revision)


def invalid(ledger: str, job_id: str) -> ExtractionFailure:
    """A stored binding, request or payload that cannot be parsed fails the whole report; nothing is skipped."""
    return ExtractionFailure("dependency_record_invalid", {"ledger": ledger, "jobId": job_id})


def array(value) -> list:
    """A stored dependency-bearing container is a JSON array. A dict, string, number or null is malformed state, never 'no dependencies'."""
    if not isinstance(value, list):
        raise TypeError("dependency container")
    return value


def cites(citations, documents: set[tuple[str, str]], **at) -> list[dict]:
    """Distinct exact (documentId, documentVersion) pairs a stored citation array names that are among `documents`, in first-seen order.

    Failed citations are stored with their claimed document too and count: they still name the document. A container that is not an array
    and entries that are not objects with string identities raise; only a real empty array means no citations."""
    found: list[dict] = []
    for item in array(citations):
        if not isinstance(item, dict):
            raise TypeError("citation entry")
        pair = (item["documentId"], item["documentVersion"])
        if not isinstance(pair[0], str) or not isinstance(pair[1], str):
            raise TypeError("citation identity")
        reason = {"code": "cites", **at, "documentId": pair[0], "documentVersion": pair[1]}
        if pair in documents and reason not in found:
            found.append(reason)
    return found
