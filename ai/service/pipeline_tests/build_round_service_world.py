#!/usr/bin/env python3
"""Authored native tick inputs and later exact-plan S3 replay; pipeline interpreter only."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

PIPELINE, ROOT = (Path(value).resolve() for value in sys.argv[1:3])
sys.path.insert(0, str(PIPELINE))

from scripts.relation_smoke import EVT, SUP, RelKit, co, converge, ev, page, proposal, world_cite
from scripts.round_enqueue_smoke import World, doc_item
from scripts.round_smoke import at, slot
from zoop_ai_pipeline.ingestion_contracts import canonical


def write(path, value):
    path.write_text(canonical(value), encoding="utf-8")
    return path


def initial():
    world = World(ROOT)
    items = [doc_item(world, "main")]
    manifest = world.covering("service-round", slot("09:05"), items, {"main": page(EVT, SUP)})
    empty_manifest = world.covering("empty-round", slot("10:05"), [])
    tick = world.tick(at("09:05:00"), initial=at("00:00:00"), manifest=manifest, state="ingestion")
    assert tick["round"]["state"] == "complete"
    head, refs = world.refs(tick["tick"]["roundId"])
    ref = {"roundId": head["roundId"], "sourceId": head["sourceId"],
           **{key: refs[0][key] for key in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
    kit = RelKit.__new__(RelKit)
    kit.root, kit.registry_path, kit.rounds = ROOT, world.registry_path, 1
    article = kit.article(ref)
    replay = kit.replay("round-service")
    replay.extract(article, [kit.mention(article, "round-mention", [kit.evidence(article, EVT)])])
    s2_replay = replay.write()
    request = kit.submit("authored-round", ref)
    topic = write(ROOT / "topic.json", {"format": "zoop-topic-replay-1", "synthetic": True, "recordingKind": "authored-test",
                                      "producerVersion": "zoop-topic-replay-producer-1", "records": []})
    producer, verifier = kit.fixture("producer", "empty", []), kit.fixture("verifier", "empty", [])
    bindings = {"schemaVersion": "zoop-app-document-bindings-1", "bindings": [{"documentId": ref["documentId"],
        "documentVersion": ref["documentVersion"], "articleId": ref["documentId"], "articleVersion": ref["documentVersion"],
        "textSha256": hashlib.sha256(article.body.encode()).hexdigest(), "offsetUnit": "unicode_code_point"}]}
    descriptor = {key: request[key] for key in ("schemaVersion", "provenance", "promptVersion", "catalogue", "snapshot", "topic")}
    return {"root": str(ROOT), "ingestion": str(ROOT / "ingestion"), "extraction": str(ROOT / "extraction"),
            "registry": str(world.registry_path), "fixtureManifest": str(manifest), "emptyManifest": str(empty_manifest), "s2Replay": str(s2_replay), "s2Topic": str(topic),
            "producer": str(producer), "verifier": str(verifier), "s2Request": request, "descriptor": descriptor,
            "bindings": bindings, "providerCalls": 0}


def author(approvals, replay):
    request = json.loads(approvals.read_bytes())["approvals"][0]["request"]
    scratch = ROOT / "author-scratch"
    scratch.mkdir()
    shutil.copytree(ROOT / "ingestion", scratch / "ingestion")
    kit = RelKit.__new__(RelKit)
    kit.root, kit.registry_path, kit.rounds = scratch, ROOT / "sources.json", 1
    s2 = kit.job("run", request, replay=replay)
    assert s2["state"] == "ready" and s2["usage"]["providerCalls"] == 0
    ref = request["incoming"]
    article = kit.article(ref)
    world = SimpleNamespace(kit=kit, refs={"main": ref}, art={"main": article}, s2=s2)
    event = s2["eventCandidates"][0]["eventCandidateId"]
    s3 = converge(world, "authored-relation", [
        proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(event), [world_cite(world, "main", EVT)]),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [world_cite(world, "main", SUP)])])
    assert s3["state"] == "ready" and s3["usage"]["providerCalls"] == 0
    producer, verifier = s3["fixtures"]
    upstream = {"jobId": s2["jobId"], "inputDigest": s2["inputDigest"]}
    canonical_doc = {"schemaVersion": "zoop-graph-canonical-1", "entries": [
        {"upstream": upstream, "kind": kind, "ref": identity, "canonicalId": public, "decisionRef": "authored-canonical"}
        for kind, identity, public in (("company", "SYNTH-1", "co:one"), ("company", "SYNTH-3", "co:three"), ("event", event, "issue:round"))]}
    quote = EVT
    start = article.body.index(quote)
    decisions = {"schemaVersion": "zoop-public-decisions-4", "policyVersion": "zoop-public-projection-policy-2",
        "companies": [{"canonicalId": identity, "publicId": ticker, "label": "Synthetic company", "decisionRef": "authored-company"}
                      for identity, ticker in (("co:one", "KRX:005930"), ("co:three", "KRX:000660"))],
        "issues": [{"canonicalId": "issue:round", "publicId": "issue:round-service", "decisionRef": "authored-issue",
            "geography": {"classification": "domestic", "countries": ["KR"], "decisionRef": "authored-geography", "decisionVersion": "v1",
                "evidence": [{"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "start": start,
                              "end": start + len(quote), "quoteSha256": hashlib.sha256(quote.encode()).hexdigest()}]},
            "representative": None, "fieldVerdicts": [], "summary": None}], "structural": [], "follows": [], "origins": []}
    return {"producer": str(kit.fixture("producer", "round", producer)), "verifier": str(kit.fixture("verifier", "round", verifier)),
            "canonical": canonical_doc, "decisions": decisions, "providerCalls": 0}


if __name__ == "__main__":
    result = author(Path(sys.argv[3]), Path(sys.argv[4])) if len(sys.argv) > 3 else initial()
    print(canonical(result))
