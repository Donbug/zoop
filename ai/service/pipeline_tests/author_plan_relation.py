#!/usr/bin/env python3
"""Author the S3 producer/verifier replay fixtures for ONE planned S2 job. Run with the interpreter of `ai/pipeline/.venv`, never the service's.

The S3 producer request carries the upstream `{jobId, inputDigest}`, so fixtures authored for the world's own `s2-job` can never answer a plan's job.
This runs the planned approval's exact S2 request in a SCRATCH extraction ledger (authored replay, and the authored topic fixture when the request asks for a
topic stage; no network), then lets the pipeline's own authoring loop (`relation_smoke.converge`, the one `build_world.py` uses) answer every stop from the
real stored candidates, and prints the two fixture paths.

usage: author_plan_relation.py <pipeline dir> <world root> <approvals.json> <jobId> <s2 replay> <scratch dir> [<s2 topic replay>]
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

PIPELINE, WORLD, APPROVALS, JOB, REPLAY, SCRATCH = (Path(a).resolve() if i != 3 else a for i, a in enumerate(sys.argv[1:7]))
TOPIC = Path(sys.argv[7]).resolve() if len(sys.argv) > 7 else None
sys.path[:0] = [str(PIPELINE)]

from scripts.relation_smoke import BAD, GOOD, RelKit, converge, impact_item, main_proposals, world_cite  # noqa: E402


def main() -> dict:
    entry = next(e for e in json.loads(APPROVALS.read_text(encoding="utf-8"))["approvals"] if e["jobId"] == JOB)
    request = entry["request"]
    assert (request["topic"] is None) == (TOPIC is None), "a topic request needs the topic fixture, and only then"
    SCRATCH.mkdir()
    shutil.copytree(WORLD / "ingestion", SCRATCH / "ingestion")
    kit = RelKit.__new__(RelKit)  # a kit over the scratch ledger and the world's own (read-only) registry; never the world's extraction ledger
    kit.root, kit.registry_path, kit.rounds = SCRATCH, WORLD / "sources.json", 0
    done = kit.job("run", request, replay=REPLAY)
    if TOPIC is not None:
        assert done["failure"]["code"] == "topic_replay_required", done.get("failure")
        done = kit.job("resume", kit.job_selector(JOB), topic=TOPIC)
    assert done["state"] == "ready", done.get("failure")
    main_ref = request["incoming"]
    other = request["snapshot"]["events"][0]["members"][0]["observation"]
    world = SimpleNamespace(kit=kit, refs={"main": main_ref, "b": other}, art={"main": kit.article(main_ref), "b": kit.article(other)},
                            evc=done["eventCandidates"][0]["eventCandidateId"], tp=done["topicCandidates"][0]["topicCandidateId"] if TOPIC else "tp-none",
                            event=request["snapshot"]["events"][0]["eventId"], s2=done)
    proposals = main_proposals(world)
    cite = lambda text, nth=0: world_cite(world, "main", text, nth)  # noqa: E731

    def verify(relation: dict):
        if relation["type"] == "SUPPLIES" and relation["subject"]["ref"] == "SYNTH-1" and relation["object"]["ref"] == "SYNTH-2":
            return {"type": "insufficient", "direction": "insufficient"}
        return None

    def impacts(relation: dict):
        if relation["type"] == "SUPPLIES" and relation["subject"]["ref"] == "SYNTH-3" and relation["object"]["ref"] == "SYNTH-1":
            return [impact_item("SYNTH-1", "positive", [cite(GOOD)], [cite(BAD)])]
        return []

    authored = converge(world, "plan-author", [proposals[0], proposals[10]], verify=verify, impacts=impacts, effects=lambda impact: {GOOD: "positive", BAD: "negative"})
    assert authored["state"] == "ready" and authored["usage"]["providerCalls"] == 0, authored.get("failure")
    producer, verifier = authored["fixtures"]
    return {"inputDigest": done["inputDigest"], "producer": str(kit.fixture("producer", "plan", producer)), "verifier": str(kit.fixture("verifier", "plan", verifier))}


if __name__ == "__main__":
    print(json.dumps(main()))
