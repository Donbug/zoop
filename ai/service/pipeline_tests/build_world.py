#!/usr/bin/env python3
"""Fresh synthetic OPERATOR world for the S3 service tests. Run with the interpreter of `ai/pipeline/.venv`, never the service's.

Everything the service must treat as operator-owned is produced here by the actual pipeline code, the way the pipeline's own smoke does:
authored HTML -> actual `zoop-ai-ingest` subprocess -> a READY S2 extraction job (in-process, with event candidate, snapshot event and
topic candidate) -> authored producer/verifier replay fixtures for the S3 stages, derived from the real stored candidates (never from a
mock echo). The service tests then talk to the service only; they read this world's directories only to prove the service left them alone.

The fixtures also carry the answers of a review's revalidation, authored the same way the pipeline's smoke authors them: the HOLD relation is
reviewed (allow) in this builder's OWN private ledger, the exact verifier request of its revalidation attempt is derived from the real stored
candidate, and an answer is recorded. That request holds no job id, so the same records serve the service's own job. Two answers exist: the
default verifier fixture answers `supported` (the relation becomes eligible and its impact stage, also authored, follows) and the second
fixture (`verifierHold`) answers `insufficient` again (the relation stays on hold).

usage: build_world.py <pipeline project dir> <empty output dir>   (prints one JSON document describing the world)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PIPELINE = Path(sys.argv[1]).resolve()
ROOT = Path(sys.argv[2]).resolve()
sys.path[:0] = [str(PIPELINE)]

from scripts.relation_smoke import (BAD, CO, COMP, GOOD, SUP, SUP2, build_world, converge, digest, impact_item, main_proposals, next_attempt,  # noqa: E402
                                    rules, verifier_reply, world_cite)


def main() -> dict:
    world = build_world(ROOT)
    kit = world.kit
    proposals = main_proposals(world)
    cite = lambda text, nth=0: world_cite(world, "main", text, nth)  # noqa: E731
    chosen = [proposals[0],     # SUPPLIES SYNTH-3 -> SYNTH-1, cited and correctly directed: eligible, with a mixed impact
              proposals[10]]    # SUPPLIES SYNTH-1 -> SYNTH-2 cited only by a co-mention sentence: held by the independent verifier

    def verify(relation: dict):
        if relation["type"] == "SUPPLIES" and relation["subject"]["ref"] == "SYNTH-1" and relation["object"]["ref"] == "SYNTH-2":
            return {"type": "insufficient", "direction": "insufficient"}
        return None

    def impacts(relation: dict):
        if relation["type"] == "SUPPLIES" and relation["subject"]["ref"] == "SYNTH-3" and relation["object"]["ref"] == "SYNTH-1":
            return [impact_item("SYNTH-1", "positive", [cite(GOOD)], [cite(BAD)])]
        return []

    def effects(impact: dict):
        return {GOOD: "positive", BAD: "negative"}

    authored = converge(world, "author-reference", chosen, verify=verify, impacts=impacts, effects=lambda impact: effects(impact))
    assert authored["state"] == "ready" and authored["usage"]["providerCalls"] == 0, authored.get("failure")
    producer, verifier = authored["fixtures"]
    eligibility = {r["relationCandidateId"]: r["eligibility"]["status"] for r in authored["relations"]}
    held = next(r for r in authored["relations"] if r["eligibility"]["status"] == "hold")
    held_id, held_revision = held["relationCandidateId"], held["eligibility"]["revision"]

    # The allow -> revalidation path of the HOLD relation, authored in this builder's private ledger (never the service's).
    reviewed = kit.rel_job("review", {**kit.rsel("author-reference"), "relationCandidateId": held_id, "expectedRevision": held_revision,
                                      "decision": "allow", "reviewer": "author", "note": "author"})
    allowed = next(r for r in reviewed["relations"] if r["relationCandidateId"] == held_id)
    key = digest(rules.verifier_request(allowed, next_attempt(allowed["history"], "revalidation")))
    verifier_hold = [*verifier, ("verify-relation", key, verifier_reply(allowed, type="insufficient", direction="insufficient"))]
    verifier_eligible = [*verifier, ("verify-relation", key, verifier_reply(allowed))]
    # A revalidation that makes the relation eligible continues into that relation's impact stage: author it as well. The first call stops
    # with `producer_replay_missing` for it (nothing is sent), and `converge` answers that stop from the real stored candidate.
    kit.rel_job("revalidate", {**kit.rsel("author-reference"), "relationCandidateId": held_id, "expectedRevision": allowed["eligibility"]["revision"]},
                replay=kit.fixture("producer", "author-p", producer), verifier=kit.fixture("verifier", "author-v", verifier_eligible))

    def impacts_with_held(relation: dict):
        if relation["type"] == "SUPPLIES" and relation["subject"]["ref"] == "SYNTH-1" and relation["object"]["ref"] == "SYNTH-2":
            return [impact_item("SYNTH-2", "undetermined", [], [])]   # no cited evidence: recorded as undetermined without a verifier call
        return impacts(relation)

    final = converge(world, "author-reference", chosen, verify=verify, impacts=impacts_with_held, effects=lambda impact: effects(impact),
                     seed=(producer, verifier_eligible))
    assert final["state"] == "ready" and final["usage"]["providerCalls"] == 0, final.get("failure")
    producer, verifier_eligible = final["fixtures"]
    revalidated = next(r for r in final["relations"] if r["relationCandidateId"] == held_id)
    assert revalidated["eligibility"]["status"] == "eligible" and revalidated["eligibility"]["revision"] == held_revision + 2
    assert revalidated["impact"]["status"] == "complete", revalidated["impact"]

    producer_path = kit.fixture("producer", "svc", producer)
    verifier_path = kit.fixture("verifier", "svc", verifier_eligible)
    verifier_hold_path = kit.fixture("verifier", "svc-hold", verifier_hold)
    empty_producer, empty_verifier = kit.fixture("producer", "svc-empty", []), kit.fixture("verifier", "svc-empty", [])
    return {
        "root": str(ROOT), "extraction": str(ROOT / "extraction"), "ingestion": str(ROOT / "ingestion"), "registry": str(kit.registry_path),
        "upstream": {"jobId": world.s2["jobId"], "inputDigest": world.s2["inputDigest"]},
        # The S2 HTTP tests submit these through the service into their OWN empty extraction ledger: the same authored request and fixtures the
        # operator job above was built from (so the job the service produces is byte-identical to it), plus a topic-less sibling.
        "s2Request": world.s2_request, "s2PlainRequest": kit.submit("s2-plain", world.refs["main"], [world.snapshot], topic=False),
        "s2Replay": str(world.s2_replay), "s2Topic": str(world.s2_topic), "s2Counts": world.s2["counts"], "s2ReplayCalls": world.s2["usage"]["replayCalls"],
        "producer": str(producer_path), "verifier": str(verifier_path), "verifierHold": str(verifier_hold_path),
        "emptyProducer": str(empty_producer), "emptyVerifier": str(empty_verifier),
        "relations": eligibility, "counts": authored["counts"], "replayCalls": authored["usage"]["replayCalls"],
        "held": held_id, "heldRevision": held_revision, "eligible": next(rc for rc, status in eligibility.items() if status == "eligible"),
        # Source text the service must never put in a status, an error, a withheld result or a log line.
        "sourceTexts": [SUP, SUP2, COMP, CO, GOOD, BAD],
    }


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
