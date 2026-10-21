"""Distinct topic-candidate producer contract (request/response/replay), separate from event extraction/SAME.

Topics are broad groupings of events, never renamed event identities. A topic candidate is not an approved topic.
Replay can only return authored responses and live can only return the provider's; neither infers a topic or fabricates an empty stub.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .extraction_contracts import (TOPIC_CANDIDATE, TOPIC_PRODUCER, TOPIC_REQUEST, ExtractionFailure, ReplyInvalid, TopicReplay,
    TopicResponse, digest)


def build_request(events: list[dict], documents: list[dict]) -> dict:
    return {"schemaVersion": TOPIC_REQUEST, "producerVersion": TOPIC_PRODUCER, "events": events, "documents": documents}


def request_digest(request: dict) -> str:
    return digest(request)


class ReplayProducer:
    """Authored replay keyed by the exact request digest; a missing record is a failure, never a fallback."""

    def __init__(self, raw: bytes, synthetic: bool):
        try:
            self.document = TopicReplay.model_validate_json(raw)
        except ValidationError as exc:
            raise ExtractionFailure("topic_replay_invalid") from exc
        if self.document.synthetic != synthetic:
            raise ExtractionFailure("topic_replay_provenance_conflict")
        self.hash = hashlib.sha256(raw).hexdigest()
        self.records = {r.request_digest: r.response for r in self.document.records}

    def response(self, key: str) -> Any | None:
        return self.records.get(key)


def parse(raw: Any) -> TopicResponse:
    try:
        return TopicResponse.model_validate(raw)
    except ValidationError as exc:
        raise ReplyInvalid("topic_reply_invalid") from exc


def topic_candidate_id(members: list[tuple[str, str, str | None]]) -> str:
    return "tp-" + digest({"version": TOPIC_CANDIDATE, "producer": TOPIC_PRODUCER, "members": sorted(members, key=lambda m: (m[0], m[1], m[2] or ""))})


def candidates(request: dict, response: TopicResponse, cite: Callable[[str, str, int, int, str], dict]) -> list[dict]:
    """Validate every membership and citation against the frozen request; unknown input is rejected, not dropped."""
    events = {(e["kind"], e["ref"]): e for e in request["events"]}
    result, seen = [], set()
    for proposal in response.topics:
        keys = [(m.kind, m.ref) for m in proposal.members]
        if len(set(keys)) != len(keys):
            raise ReplyInvalid("topic_member_duplicate")
        if any(k not in events for k in keys):
            raise ReplyInvalid("topic_member_unknown")
        allowed = {(d["documentId"], d["documentVersion"]) for k in keys for d in events[k]["documents"]}
        citations = []
        for c in proposal.citations:
            if (c.document_id, c.document_version) not in allowed:
                raise ReplyInvalid("topic_citation_unbound")
            citations.append(cite(c.document_id, c.document_version, c.start, c.end, c.quote))
        members = [(k[0], k[1], events[k]["revision"]) for k in keys]
        topic_id = topic_candidate_id(members)
        if topic_id in seen:
            raise ReplyInvalid("topic_candidate_duplicate")
        seen.add(topic_id)
        result.append({"topicCandidateId": topic_id, "status": "candidate", "approved": False, "producerVersion": TOPIC_PRODUCER,
                       "label": proposal.label, "criteria": proposal.criteria, "rationale": proposal.rationale,
                       "members": [{"kind": k, "ref": r, "revision": v} for k, r, v in sorted(members, key=lambda m: (m[0], m[1]))],
                       "citations": citations})
    return sorted(result, key=lambda t: t["topicCandidateId"])
