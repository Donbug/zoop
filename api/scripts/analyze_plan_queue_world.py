#!/usr/bin/env python3
"""Test-owned builder: complete authored rounds -> installed plan-round, two units each.

Executed only by the installed pipeline interpreter under inherited recursive network
refusal. No application job or application database is opened by this helper.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from importlib.metadata import version as distribution_version
from pathlib import Path
from types import SimpleNamespace

PIPELINE, ROOT, PLAN_ROOT = (Path(value).resolve() for value in sys.argv[1:4])
sys.path.insert(0, str(PIPELINE))
from scripts.relation_smoke import EVT, SUP, RelKit, co, converge, page, proposal, world_cite


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def main():
    kit = RelKit(ROOT)
    PLAN_ROOT.mkdir(mode=0o700)
    rounds = [kit.ingest(f"queue-{index}", [
        {"supplier": f"queue-{index}-{unit}", "html": page(EVT, SUP, f"합성 큐 표본 {index}/{unit}.")}
        for unit in range(2)]) for index in range(3)]
    replay = kit.replay("queue-s2")
    for index, refs in enumerate(rounds):
        for unit, ref in enumerate(refs):
            article = kit.article(ref)
            replay.extract(article, [kit.mention(article, f"queue-mention-{index}-{unit}", [kit.evidence(article, EVT)])])
    s2_replay = replay.write()
    references, producers, verifiers = [], [], []
    for index, refs in enumerate(rounds):
        request = kit.submit(f"operator-queue-{index}", refs[0])
        descriptor = {key: request[key] for key in ("schemaVersion", "provenance", "promptVersion", "catalogue", "snapshot", "topic")}
        descriptor.update(enqueueId=f"queue-round-{index}", roundId=refs[0]["roundId"], sourceId=refs[0]["sourceId"])
        staging = ROOT / f"plan-{index}"
        done = subprocess.run([str(Path(sys.executable).parent / "zoop-ai-extract"), "plan-round",
                               "--ingestion-state-dir", str(ROOT / "ingestion"), "--sources", str(kit.registry_path),
                               "--replay", str(s2_replay), "--principal", "alpha", "--output", str(staging)],
                              input=canonical(descriptor).encode(), capture_output=True, timeout=120)
        assert done.returncode == 0 and not done.stderr, "installed plan producer refused authored round"
        receipt = json.loads((staging / "receipt.json").read_bytes())
        target = PLAN_ROOT / receipt["planId"]
        staging.rename(target)
        references.append({"schemaVersion": "zoop-ai-plan-admission-1", "planId": receipt["planId"], "planDigest": receipt["planDigest"]})
        entries = json.loads((target / "approvals.json").read_bytes())["approvals"]
        assert len(entries) == 2, "round must produce two distinct real units"
        for entry in entries:
            planned = entry["request"]
            # A planned unit has exactly one observation. Resolve by document identity,
            # rather than depending on planner sort order or the request field spelling.
            wire = canonical(planned)
            matched = [candidate for candidate in refs if candidate["documentId"] in wire]
            assert len(matched) == 1, "planned observation identity is ambiguous"
            ref = matched[0]
            s2 = kit.job("run", planned, replay=s2_replay)
            assert s2["state"] == "ready" and s2["usage"]["providerCalls"] == 0
            world = SimpleNamespace(kit=kit, refs={"main": ref}, art={"main": kit.article(ref)}, s2=s2)
            authored = converge(world, f"author-queue-{index}-{len(producers)}", [
                proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [world_cite(world, "main", SUP)])])
            assert authored["state"] == "ready" and authored["usage"]["providerCalls"] == 0
            producer, verifier = authored["fixtures"]
            producers.extend(producer)
            verifiers.extend(verifier)
    producer = kit.fixture("producer", "queue-combined", producers)
    verifier = kit.fixture("verifier", "queue-combined", verifiers)
    topic = ROOT / "unused-topic.json"
    topic.write_text(canonical({"format": "zoop-topic-replay-1", "synthetic": True, "recordingKind": "authored-test",
                                "producerVersion": "zoop-topic-replay-producer-1", "records": []}))
    policy = {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": True, "principal": "alpha", "sourceIds": ["synthetic-source"],
              "sourceKind": "synthetic", "promptVersion": request["promptVersion"], "catalogueDigest": digest(request["catalogue"]),
              "snapshotDigest": digest(request["snapshot"]), "topic": None,
              "runtime": {"kind": "replay", "producerReplayDigest": hashlib.sha256(s2_replay.read_bytes()).hexdigest(),
                          "topicReplayDigest": None, "relationReplayDigest": hashlib.sha256(producer.read_bytes()).hexdigest(),
                          "relationVerifierReplayDigest": hashlib.sha256(verifier.read_bytes()).hexdigest()}}
    return {"root": str(ROOT), "ingestion": str(ROOT / "ingestion"), "extraction": str(ROOT / "extraction"),
            "registry": str(kit.registry_path), "producer": str(producer), "verifier": str(verifier),
            "s2Replay": str(s2_replay), "s2Topic": str(topic), "s2Request": request,
            "references": references, "policy": policy, "providerCalls": 0,
            "pipelineVersion": distribution_version("zoop-ai-pipeline"), "pipelinePython": sys.executable}


if __name__ == "__main__":
    print(canonical(main()))
