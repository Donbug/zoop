#!/usr/bin/env python3
"""Build three complete authored rounds and exact plans with the pipeline interpreter.

Only test-owned sources are read. The parent installs sitecustomize network denial,
which is inherited by every Python subprocess, including the installed plan CLI.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
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
    slot = "2026-10-31T09:00:00+09:00"
    observations = [kit.ingest(f"online-{index}", [{"supplier": f"online-supplier-{index}", "html": page(EVT, SUP)}], slot=slot)[0]
                    for index in range(3)]
    selection = ROOT / "selection.json"
    selection.write_text(canonical({"schemaVersion": "zoop-extraction-round-selection-1", "asOf": slot, "maxAgeSeconds": 3600}))
    replay = kit.replay("online-s2")
    for index, ref in enumerate(observations):
        article = kit.article(ref)
        mention = kit.mention(article, f"online-mention-{index}", [kit.evidence(article, EVT)])
        replay.extract(article, [mention])
    s2_replay = replay.write()
    references, producers, verifiers = [], [], []
    for index, ref in enumerate(observations):
        request = kit.submit(f"operator-{index}", ref)
        descriptor = {key: request[key] for key in ("schemaVersion", "provenance", "promptVersion", "catalogue", "snapshot", "topic")}
        descriptor.update(enqueueId=f"online-round-{index}", roundId=ref["roundId"], sourceId=ref["sourceId"])
        staging = ROOT / f"plan-{index}"
        done = subprocess.run([str(Path(sys.executable).parent / "zoop-ai-extract"), "plan-round", "--ingestion-state-dir", str(ROOT / "ingestion"),
                               "--sources", str(kit.registry_path), "--replay", str(s2_replay), "--principal", "alpha", "--output", str(staging),
                               "--selection", str(selection)], input=canonical(descriptor).encode(), capture_output=True, timeout=120)
        assert done.returncode == 0 and not done.stderr, "installed plan-round refused synthetic round"
        receipt = json.loads((staging / "receipt.json").read_bytes())
        target = PLAN_ROOT / receipt["planId"]
        staging.rename(target)
        references.append({"schemaVersion": "zoop-ai-plan-admission-1", "planId": receipt["planId"], "planDigest": receipt["planDigest"]})
        entries = json.loads((target / "approvals.json").read_bytes())["approvals"]
        assert len(entries) == 1
        planned = entries[0]["request"]
        s2 = kit.job("run", planned, replay=s2_replay)
        assert s2["state"] == "ready" and s2["usage"]["providerCalls"] == 0 and len(s2["eventCandidates"]) == 1
        world = SimpleNamespace(kit=kit, refs={"main": ref}, art={"main": kit.article(ref)}, s2=s2)
        authored = converge(world, f"author-online-{index}", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [world_cite(world, "main", SUP)])])
        assert authored["state"] == "ready" and authored["usage"]["providerCalls"] == 0 and len(authored["relations"]) == 1
        assert authored["relations"][0]["eligibility"]["status"] == "eligible"
        producer, verifier = authored["fixtures"]
        producers.extend(producer)
        verifiers.extend(verifier)
    producer = kit.fixture("producer", "online-combined", producers)
    verifier = kit.fixture("verifier", "online-combined", verifiers)
    # The service uses an empty, syntactically real topic fixture only as a Workspace
    # construction input; online mode omits topic config because the descriptor is null.
    topic = ROOT / "unused-topic.json"
    topic.write_text(canonical({"format": "zoop-topic-replay-1", "synthetic": True, "recordingKind": "authored-test",
                                "producerVersion": "zoop-topic-replay-producer-1", "records": []}))
    policy = {"schemaVersion": "zoop-ai-plan-policy-1", "enabled": True, "principal": "alpha", "sourceIds": ["synthetic-source"],
              "sourceKind": "synthetic", "promptVersion": request["promptVersion"], "catalogueDigest": digest(request["catalogue"]),
              "snapshotDigest": digest(request["snapshot"]), "topic": None,
              "runtime": {"kind": "replay", "producerReplayDigest": hashlib.sha256(s2_replay.read_bytes()).hexdigest(), "topicReplayDigest": None,
                          "relationReplayDigest": hashlib.sha256(producer.read_bytes()).hexdigest(),
                          "relationVerifierReplayDigest": hashlib.sha256(verifier.read_bytes()).hexdigest()}}
    return {"root": str(ROOT), "ingestion": str(ROOT / "ingestion"), "extraction": str(ROOT / "extraction"), "registry": str(kit.registry_path),
            "producer": str(producer), "verifier": str(verifier), "s2Replay": str(s2_replay), "s2Topic": str(topic),
            "s2Request": request, "references": references, "policy": policy, "providerCalls": 0}


if __name__ == "__main__":
    print(canonical(main()))
