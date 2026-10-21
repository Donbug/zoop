"""Review operations over the pipeline's append-only event chain, as pure functions: the owner marker, the proof that a chain event is (or is
not) the one an operation wrote, and the content-free view of an operation.

The pipeline appends a relation's events in a transaction guarded by `expectedRevision` (the number of events the caller saw). So an event
exists at sequence `expected + 1`, or the relation has moved past `expected`, or neither (nothing was appended yet). The service writes a
marker into the event it asks for (`reviewer` = the authenticated principal, `note` = a string derived from the operation id), which turns
"did my append land?" into a lookup in the chain instead of a guess: an ambiguous review is reconciled by reading the chain, and an event is
adopted as the operation's only if EVERY field of it matches what that operation asked for.

Revisions: `expectedSourceRevision` is the pipeline's event count of ONE relation candidate, a decimal string on the wire and an integer here.
It is a runtime concurrency token. It is not, and never converts to or from, the application's own review revision.
"""
from __future__ import annotations

from dataclasses import dataclass

from .relation_ledger import OperationRow
from .relation_wire import (RelationChain, RelationOperationStatus, RelationPublicationPhase, RelationReviewPhase,
                            RelationRevalidationPhase, RtChainRelation)

MARKER_PREFIX = "zoop-ai-service-review:"
# The event a CURRENT-contract operation asks for: an `allow` is the operator's FINAL approval (no model call, no revalidation), a `reject` an
# exclusion. The old effect `revalidation-requested` is history of a contract that no longer exists and is never matched here.
EFFECT = {"allow": "approved", "reject": "excluded"}
LIMITATION = "review_contract_changed"


def marker(operation_id: str) -> str:
    """The `note` of the event an operation asks the pipeline to append. Service-derived: a caller can neither choose nor see free text."""
    return MARKER_PREFIX + operation_id


@dataclass(frozen=True)
class Evidence:
    """What the chain says about one reserved operation.

    applied   the exact event is at sequence expected + 1 (`event_at` is the pipeline's own timestamp of it)
    absent    the relation is still at the expected revision and holds no event of this operation
    moved     the relation moved past the expected revision without an event of this operation: it can never be appended at that revision
    mismatch  an event carries this operation's marker but is not exactly what the operation asked for (contradiction: never adopted)
    missing   the candidate is not in the chain
    unreadable the chain could not be read (busy, withheld while rights or the exact upstream do not hold, or not parseable): no proof either way
    """
    kind: str
    event_at: str | None = None


def relation_of(chain: RelationChain, relation_candidate_id: str) -> RtChainRelation | None:
    return next((relation for relation in chain.relations if relation.relation_candidate_id == relation_candidate_id), None)


def evidence(chain: RelationChain, op: OperationRow) -> Evidence:
    relation = relation_of(chain, op.relation_candidate_id)
    if relation is None:
        return Evidence("missing")
    ours = [event for event in relation.history if event.kind == "review" and event.note == marker(op.operation_id)]
    if ours:
        event = ours[0]
        exact = (len(ours) == 1 and event.seq == op.expected_source_revision + 1 and event.reviewer == op.owner
                 and event.decision == op.decision and event.expected_revision == op.expected_source_revision and event.effect == EFFECT[op.decision])
        return Evidence("applied" if exact else "mismatch", event.created_at)
    return Evidence("absent" if relation.eligibility.revision == op.expected_source_revision else "moved")


def _revalidation(op: OperationRow) -> tuple[str, str | None, str | None]:
    """(state, verdict eligibility, resulting source revision). Only a legacy `allow` ever requested a revalidation; what its own stored columns
    settled is reported as history and anything unsettled is `contract_changed`: it is never dispatched or resent."""
    if not op.legacy or op.decision == "reject" or op.review_state != "applied":
        return "not_requested", None, None
    after = str(op.expected_source_revision + 2)
    if op.settled == "verified":
        return "verified", op.settled_eligibility, after
    if op.settled == "superseded":
        return "superseded", None, after
    return "contract_changed", None, None


def next_operation_action(op: OperationRow) -> str:
    """Pure and ordered: what the caller should do next. A legacy operation has nothing to do: an unconfirmed legacy review is never retried and
    a legacy revalidation is never run (a NEW decision at the relation's current revision is the way forward)."""
    if op.legacy:
        return "none"
    return "none" if op.review_state == "applied" else "retry_review"


def operation_status(op: OperationRow, observed_at: str) -> RelationOperationStatus:
    """The content-free view of one operation, read from the service ledger only: identity, the exact expectations the caller sent, the
    acceptance of the decision and (always) that nothing is published here. `limitation` names a legacy operation."""
    applied = op.review_state == "applied"
    state, verdict, resulting = _revalidation(op)
    return RelationOperationStatus(
        operation_id=op.operation_id, job_id=op.job_id, relation_candidate_id=op.relation_candidate_id, decision=op.decision, reviewer=op.owner,
        expected_source_version=op.expected_source_version, expected_source_revision=str(op.expected_source_revision),
        review=RelationReviewPhase(state="applied" if applied else "unconfirmed",
                                   resulting_source_revision=str(op.expected_source_revision + 1) if applied else None, recorded_at=op.applied_at),
        revalidation=RelationRevalidationPhase(state=state, dispatch_count=op.reval_count, last_outcome=op.last_outcome,
                                               last_runtime_code=op.last_runtime_code, verdict=verdict, resulting_source_revision=resulting,
                                               updated_at=op.reval_updated_at),
        publication=RelationPublicationPhase(), next=next_operation_action(op), limitation=LIMITATION if op.legacy else None,
        accepted_at=op.reserved_at, observed_at=observed_at)
