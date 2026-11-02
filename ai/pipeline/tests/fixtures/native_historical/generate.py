"""Generate synthetic golden archives with the sealed historical source, never with current builders.

Run with the historical pipeline virtualenv under env -i, PYTHONDONTWRITEBYTECODE=1.
The source root and seal are positional arguments. Output is golden.json; --timed-round writes only timed-round.json.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace


def main():
    source, seal = map(Path, sys.argv[1:3])
    sys.path[:0] = [str(source / "src"), str(source)]
    manifest = json.loads(seal.read_text())
    sealed = {r["path"]: r["sha256"] for r in manifest["files"]}
    names = ("extraction_contracts", "extraction_replay", "extraction", "relation_contracts", "relation", "live_runtime", "live_prompts",
             "live_jev", "live_funding", "handoff", "handoff_contracts", "graph_projection", "graph_projection_contracts")
    pins = {}
    for name in names:
        relative = f"src/zoop_ai_pipeline/{name}.py"
        actual = hashlib.sha256((source / relative).read_bytes()).hexdigest()
        if actual != sealed[f"ai/pipeline/{relative}"]:
            raise RuntimeError(f"Historical source seal mismatch: {relative}")
        pins[relative] = actual

    def guard(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.bind"}:
            raise RuntimeError("Fixture generation is offline")
    sys.addaudithook(guard)
    from scripts import graph_handoff_smoke as hs
    from tests.test_handoff import Rig
    from scripts.extraction_smoke import LiveWorld, chat_reply, simulator_env
    from tests.test_extraction_live import Provider, go
    from zoop_ai_pipeline.extraction import Extractor, Sources, upstream_digest
    from zoop_ai_pipeline.extraction_contracts import Submit, canonical, digest
    from zoop_ai_pipeline.ingestion_contracts import Authority
    from zoop_ai_pipeline.live_runtime import LiveRuntime
    from zoop_ai_pipeline.relation import Engine, Fixtures, Store
    from zoop_ai_pipeline.relation_contracts import Submit as RelationSubmit
    from zoop_ai_pipeline.graph_projection import Paths, Projector, Store as GraphStore
    from zoop_ai_pipeline.graph_projection_contracts import Freeze
    import httpx

    def archive(root):
        paths = [root / "sources.json", root / "canonical.json", root / "decisions.json", root / "bindings.json"]
        for name in ("ingestion", "extraction", "relation", "handoff", "graph"):
            directory = root / name
            if directory.exists():
                paths.extend(p for p in directory.rglob("*") if p.is_file())
        return {str(p.relative_to(root)): {"base64": base64.b64encode(p.read_bytes()).decode(), "mode": p.stat().st_mode & 0o777}
                for p in paths if p.exists()}

    if sys.argv[3:]:
        if sys.argv[3:] != ["--timed-round"]:
            raise SystemExit("Expected --timed-round")
        from scripts.relation_smoke import RelKit, converge
        from scripts.extraction_smoke import page

        with tempfile.TemporaryDirectory(prefix="zoop-historical-timed-") as temporary:
            kit = RelKit(Path(temporary).resolve() / "owned")
            text = "합성기업은 역사 계약을 발표했다."
            ref, = kit.ingest("historical", [{"supplier": "historical-supplier", "html": page(text)}],
                              slot="2026-10-29T09:05:00+09:00")
            article = kit.article(ref)
            mention = kit.mention(article, "m-historical", [kit.evidence(article, text)])
            request = kit.submit("s2-historical", ref)
            result = kit.job("run", request, replay=kit.replay("historical").extract(article, [mention]).write())
            relation = converge(SimpleNamespace(kit=kit, s2=result), "rel-a-historical", [])
            output = {"schemaVersion": "zoop-historical-native-synthetic-1", "sourcePins": pins,
                      "sourceSeal": {"sha256": hashlib.sha256(seal.read_bytes()).hexdigest(), "archive": manifest["archive"]},
                      "files": archive(kit.root), "request": request, "result": result,
                      "relation": {k: v for k, v in relation.items() if k != "fixtures"}}
            destination = Path(__file__).with_name("timed-round.json")
            destination.write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            print(json.dumps({"path": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "sourcePins": pins}))
        return

    with tempfile.TemporaryDirectory(prefix="zoop-historical-authored-") as temporary:
        root = Path(temporary).resolve()
        world = hs.build_world(root / "world", approve=True, impact="rich")
        rig = Rig(world, root)
        rig.freeze()
        exported = rig.run("export", rig.sel())
        graph = GraphStore(rig.root / "graph", mode="create")
        try:
            paths = Paths(rig.root / "relation", rig.root / "extraction", rig.root / "ingestion", rig.root / "sources.json", rig.root / "canonical.json")
            Projector(graph, paths).freeze(Freeze.model_validate({"schemaVersion": "zoop-graph-projection-1", "versionId": "historical-graph",
                "relation": {"jobId": "rel-a", "inputDigest": world.jobs["rel-a"]["inputDigest"]}}))
        finally:
            graph.close()
        replay = {"files": archive(rig.root), "manifest": rig.manifest(), "export": exported, "results": world.s2, "relations": world.jobs,
                  "upstreamDigests": {key: upstream_digest(value) for key, value in world.s2.items()}}
        preimages = []
        for language in (None, "en"):
            request = world.kit.submit("historical-preimage", world.refs["b"], [
                world.kit.event("event-a", [(world.refs["a"], world.s2["a"]["eventCandidates"][0]["mention"])])])
            request["snapshot"]["events"][0]["members"][0]["mention"] = json.loads(json.dumps(request["snapshot"]["events"][0]["members"][0]["mention"]))
            request["snapshot"]["events"][0]["members"][0]["mention"]["participants"][0]["name"] = "old-valid-noncatalogue-name"
            exports = {digest(ref): world.kit.export(ref) for ref in (world.refs["a"], world.refs["b"])}
            for value in exports.values():
                value["observation"].pop("language", None)
                if language is not None:
                    value["observation"]["language"] = language
            submit = Submit.model_validate(request)
            owner = Extractor(SimpleNamespace(db=None), SimpleNamespace(export=lambda ref: exports[digest(ref.wire())]))
            replay_binding = world.s2["b"]["binding"]["replay"]
            bound = owner._binding(owner._context(submit), replay_binding)
            preimages.append({"language": language, "request": submit.wire(), "exports": exports,
                              "row": {"job_id": submit.job_id, "input_digest": digest({"request": submit.wire(), "replayFixtureHash": replay_binding["fixtureHash"]}),
                                      "binding": canonical(bound), "replay_hash": replay_binding["fixtureHash"]}})
        env = simulator_env("https://api.openai.com/v1", root / "synthetic-budget")
        os.environ.update(env)
        live_world = LiveWorld(root / "live", env)
        provider = Provider()
        live = go(live_world, provider.access(), "historical-live", snapshot=True, topic=True)
        def factory(need_send=False):
            return LiveRuntime.from_env(need_send=need_send, transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=chat_reply(json.dumps({
                    "schemaVersion": "zoop-relation-response-1", "producerVersion": "zoop-relation-producer-1",
                    "citationFormat": "zoop-live-source-segments-1", "relations": []})))))
        live_world.kit.allow_model_send(factory(), ("extract", "compare", "topic", "relation", "verify-relation", "impact", "verify-impact"))
        store = Store(live_world.kit.root / "relation", live_world.kit.root / "extraction", live_world.kit.root / "ingestion")
        try:
            engine = Engine(store, Sources(live_world.kit.root / "ingestion", Authority(live_world.kit.registry_path)),
                            live_world.kit.root / "extraction", live_world.kit.root / "ingestion", factory)
            relation = engine.run(RelationSubmit.model_validate({"schemaVersion": "zoop-relation-s3", "jobId": "historical-live-relation",
                "provenance": live["provenance"], "upstream": {"jobId": live["jobId"], "inputDigest": live["inputDigest"]}}), Fixtures(None, None))
            assert relation["state"] == "ready", relation.get("failure")
        finally:
            store.close()
        (live_world.kit.root / "sources.json").write_bytes(live_world.kit.registry_path.read_bytes())
        runtime = live["binding"]["live"]["runtime"]
        output = {"schemaVersion": "zoop-historical-native-synthetic-1", "sourcePins": pins,
                  "sourceSeal": {"sha256": hashlib.sha256(seal.read_bytes()).hexdigest(), "archive": manifest["archive"]},
                  "replay": replay, "live": {"files": archive(live_world.kit.root), "result": live, "relation": relation, "upstreamDigest": upstream_digest(live)},
                  "runtime": runtime, "preimages": preimages}
        destination = Path(__file__).with_name("golden.json")
        destination.write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        print(json.dumps({"path": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "sourcePins": pins}))


if __name__ == "__main__":
    main()
