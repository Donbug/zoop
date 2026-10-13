#!/usr/bin/env python3
"""Authored HTML -> actual ingestion + S2 extraction + S3 relation/impact, then the actual S4 dependents CLI as a subprocess.
Fresh owned state is always removed.

Replay is authored response replay for every producer and verifier: no network, no model, no original PoC state, and no claim about real AI
quality. The dependents command is a read-only identity lookup; its subprocess runs under an audit hook that aborts any network use and any
write/mutation under the state root, and the ledger directories must come out byte/mode/mtime identical.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.extraction_smoke import topic_replay, topic_response  # noqa: E402
from scripts.ingestion_smoke import json_bytes, ownership_env  # noqa: E402
from scripts.relation_smoke import (BAD, CO, COMP, CUSTOM, EVT, GOOD, INV, QB, SUP, SUP2, VALID, build_world, co, converge, ev, find,  # noqa: E402
    forged_span, impact_item, proposal, step, tp, tree, world_cite)
from zoop_ai_pipeline.dependency_contracts import SCHEMA  # noqa: E402
from zoop_ai_pipeline.extraction import Extractor, Fixtures, Sources  # noqa: E402
from zoop_ai_pipeline.extraction import Store as ExtractionStore  # noqa: E402
from zoop_ai_pipeline.extraction_contracts import Submit  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import Authority  # noqa: E402

LEDGERS = ("ingestion", "extraction", "relation")
PRIVATE = (SUP, SUP2, COMP, INV, VALID, CO, EVT, GOOD, BAD, QB, "합성기업 계약과 공장", "example.invalid")


# ---------------------------------------------------------------- authored wire builders ------------------------------

def query(changed: dict) -> dict:
    return {"schemaVersion": SCHEMA, "changed": changed}


def document(ref: dict, *, version: bool = True, raw: bool = False) -> dict:
    return query({"kind": "document", "documentId": ref["documentId"], "documentVersion": ref["documentVersion"] if version else None,
                  "rawVersion": ref["rawVersion"] if raw else None})


def source(source_id: str = "synthetic-source") -> dict:
    return query({"kind": "source", "sourceId": source_id})


def grant(grant_id: str = "operator-grant", revision: str | None = None) -> dict:
    return query({"kind": "grant", "grantId": grant_id, "revision": revision})


# ---------------------------------------------------------------- authored world --------------------------------------

def authored(world: SimpleNamespace):
    """Nine relations over the S2 job's two documents, chosen so each dependency route (endpoint kind, citation slot, impact) is distinct.

    main = the incoming document, b = the snapshot member of event-1. Citations: main in battery/two-hop/invest/topic/alias/candidate/reversed/forged,
    b only in `event`; endpoints: topic -> the topic candidate, alias -> an event ID spelled as a topic, candidate -> the extracted event candidate,
    event -> the snapshot event."""
    def c(text: str) -> dict:
        return world_cite(world, "main", text)

    s1, s2 = step("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(SUP)]), step("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(SUP2)])
    proposals = [
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(SUP)], product="battery"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", path=[s1, s2], product="two-hop"),
        proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(INV)], validity={"from": "2026-01-01", "until": "2026-12-31", "citations": [c(VALID)]}),
        proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(world.event), [world_cite(world, "b", QB)]),
        proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp(world.tp), [c(EVT)]),
        proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp(world.event), [c(EVT)]),
        proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(world.evc), [c(EVT)]),
        proposal("SUPPLIES", co("SYNTH-1"), co("SYNTH-3"), [c(SUP)], product="reversed"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [forged_span(world, "main", SUP)], product="forged"),
    ]

    def verify(r: dict):
        return {"direction": "reversed"} if r["type"] == "SUPPLIES" and r["subject"]["ref"] == "SYNTH-1" else None

    def impacts(r: dict):
        if r["type"] == "SUPPLIES" and r["productScope"] == "battery":
            return [impact_item("SYNTH-1", "positive", [c(GOOD)], [c(BAD)])]
        if r["type"] == "PARTICIPATES_IN" and r["object"]["ref"] == world.event:
            return [impact_item("SYNTH-1", "positive", [world_cite(world, "b", QB)], [])]
        return []

    return proposals, verify, impacts, lambda i: {GOOD: "positive", BAD: "negative", QB: "positive"}


def build(root: Path, *, process: bool = False) -> SimpleNamespace:
    """Real ingestion + S2 (a ready job, plus the same request stopped at the topic stage then cancelled) + S3 (a ready job and a stopped one)."""
    world = build_world(root)
    kit = world.kit
    stopped = kit.job("run", kit.submit("s2-cancel", world.refs["main"], [world.snapshot], topic=True), replay=world.s2_replay)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "topic_replay_required", stopped["failure"]
    world.cancelled = kit.job("cancel", kit.job_selector("s2-cancel"))
    assert world.cancelled["state"] == "cancelled", world.cancelled["state"]
    proposals, verify, impacts, effects = authored(world)
    world.rel = converge(world, "rel-main", proposals, verify=verify, impacts=impacts, effects=effects, process=process)
    assert world.rel["state"] == "ready" and world.rel["counts"]["relations"] == 9 and world.rel["counts"]["impactCandidates"] == 2, world.rel.get("failure")
    world.rel_stopped = kit.rel_job("run", kit.rsubmit("rel-stopped", world.s2))
    assert world.rel_stopped["state"] == "stopped" and world.rel_stopped["failure"]["code"] == "producer_replay_required", world.rel_stopped["failure"]
    return world


def same_request_other_binding(world: SimpleNamespace, directory: Path, name: str, *, revision: str | None, finish: bool):
    """Owner-produced extraction ledger `name` (next to the built ledgers in `directory`) holding job `s2-job` with the IDENTICAL Submit and replay
    bytes as the original, so the same inputDigest, run through the real Extractor. `revision` freezes another grant revision (a copy of the registry
    with only that changed, never the original); `finish` also authors and supplies the topic replay so the job reaches `ready` like the original.

    The topic replay cannot be reused: event/mention candidate IDs are derived from the incoming document's frozen binding, which includes the grant,
    so a job frozen under another revision has other candidate IDs and therefore another topic request digest. The reply is authored again from that
    job's own stop (digest and candidate ID), with the same topic and the same exact citations."""
    path = world.kit.registry_path
    if revision is not None:
        registry = json.loads(path.read_bytes())
        registry["sources"][0]["grant"]["revision"] = revision
        path = directory / f"sources-{name}.json"
        path.write_bytes(json_bytes(registry))
    store = ExtractionStore(directory / name, directory / "ingestion")
    try:
        extractor = Extractor(store, Sources(directory / "ingestion", Authority(path)))
        request = Submit.model_validate(world.kit.submit("s2-job", world.refs["main"], [world.snapshot], topic=True))
        result = extractor.run(request, Fixtures(world.s2_replay.read_bytes(), None))
        if finish:
            assert result["failure"]["code"] == "topic_replay_required", result["failure"]
            candidate = result["eventCandidates"][0]["eventCandidateId"]
            topic = topic_replay(SimpleNamespace(root=directory), f"{name}-topic", {result["failure"]["detail"]["topicRequestDigest"]: topic_response([{
                "label": "합성기업 계약과 공장", "criteria": "같은 기업의 서로 다른 사업 사건", "rationale": "authored replay",
                "members": [{"kind": "event-candidate", "ref": candidate}, {"kind": "snapshot-event", "ref": world.event}],
                "citations": [world_cite(world, "main", EVT), world_cite(world, "b", QB)]}])})
            result = extractor.resume("s2-job", Fixtures(None, topic.read_bytes()))
    finally:
        store.close()
    assert result["inputDigest"] == world.s2["inputDigest"]   # the premise: job ID and inputDigest alone cannot tell these jobs apart
    return result


def labels(world: SimpleNamespace) -> dict[str, str]:
    """relationCandidateId of each authored relation, taken from the owner's own delivered result."""
    def pick(*args, **match) -> str:
        return find(world.rel, *args, **match)["relationCandidateId"]

    return {"battery": pick("SUPPLIES", "SYNTH-3", "SYNTH-1", productScope="battery"), "two-hop": pick("SUPPLIES", "SYNTH-3", "SYNTH-2", productScope="two-hop"),
            "invest": pick("INVESTS_IN", "SYNTH-4", "SYNTH-3"), "event": pick("PARTICIPATES_IN", "SYNTH-1", world.event),
            "topic": pick("RELATES_TO_TOPIC", "SYNTH-1", world.tp), "alias": pick("RELATES_TO_TOPIC", "SYNTH-1", world.event),
            "candidate": pick("PARTICIPATES_IN", "SYNTH-1", world.evc), "reversed": pick("SUPPLIES", "SYNTH-1", "SYNTH-3"),
            "forged": pick("SUPPLIES", "SYNTH-3", "SYNTH-1", productScope="forged")}


# ---------------------------------------------------------------- actual process runner ------------------------------

def guard_source(root: Path) -> str:
    """Audit hook for the dependents subprocess: no network, and no write/mutation of anything under the state root."""
    return ("import os, sys, runpy\n"
            f"STATE = {str(root)!r}\n"
            "NETWORK = {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.bind'}\n"
            "MUTATE = {'os.chmod', 'os.chown', 'os.mkdir', 'os.remove', 'os.rename', 'os.replace', 'os.rmdir', 'os.truncate', 'os.utime', 'os.symlink', 'os.link'}\n"
            "WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND\n"
            "def _guard(event, args):\n"
            " if event in NETWORK:\n"
            "  raise RuntimeError('network attempted')\n"
            " if event in MUTATE and str(args[0]).startswith(STATE):\n"
            "  raise RuntimeError('write attempted')\n"
            " if event == 'open' and str(args[0]).startswith(STATE) and ((args[2] or 0) & WRITE or any(c in (args[1] or '') for c in 'wax+')):\n"
            "  raise RuntimeError('write attempted')\n"
            "sys.addaudithook(_guard)\n")


def dep(root: Path, request: dict | bytes, *, ingestion: str = "ingestion", extraction: str = "extraction", relation: str | None = "relation",
        expected: int = 0, raw: bool = False):
    """Actual `zoop_ai_pipeline.dependency_cli` subprocess with the audit hook (a network attempt or write aborts the process)."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM}
    argv = [sys.executable, "-c", guard_source(root) + "runpy.run_module('zoop_ai_pipeline.dependency_cli', run_name='__main__')",
            "--ingestion-state-dir", str(root / ingestion), "--extraction-state-dir", str(root / extraction)]
    if relation:
        argv += ["--relation-state-dir", str(root / relation)]
    child = subprocess.run(argv, input=request if isinstance(request, bytes) else json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, cwd=PIPELINE, timeout=120)
    assert child.returncode == expected, (child.returncode, child.stdout.decode(), child.stderr.decode())
    assert not child.stderr, child.stderr.decode()
    return child.stdout.decode() if raw else json.loads(child.stdout)


def by(items: list[dict], key: str, value: str) -> dict:
    found = [i for i in items if i[key] == value]
    assert len(found) == 1, (key, value, [i[key] for i in items])
    return found[0]


def listed(job: dict, ids: dict[str, str]) -> set[str]:
    named = {r["relationCandidateId"] for r in job["relationCandidates"]}
    return {label for label, relation_id in ids.items() if relation_id in named}


# ======================================================================== actual subprocess smoke ===================

def smoke(root: Path) -> dict:
    world = build(root, process=True)
    kit, checks, ids = world.kit, [], labels(world)
    main, b = world.refs["main"], world.refs["b"]
    outputs: list[str] = []

    def text_of(request: dict, *, expected: int = 0, **kwargs) -> str:
        """One dependents subprocess; no ledger may change by a byte, mode or mtime across it."""
        snapshot = {name: tree(root / name) for name in LEDGERS}
        text = dep(root, request, raw=True, expected=expected, **kwargs)
        assert {name: tree(root / name) for name in LEDGERS} == snapshot, "dependents changed a ledger"
        if expected == 0:
            outputs.append(text)
        return text

    def run(request: dict, **kwargs) -> dict:
        return json.loads(text_of(request, **kwargs))

    # 1. A snapshot-member document reaches its event, the comparison against it, the topic, and only the relations/impacts that route through it.
    report = run(document(b))
    assert report["identity"] == {"bound": True, "recordedInIngestion": True} and report["usage"] == {"providerCalls": 0, "modelCalls": 0}
    job = by(report["extraction"]["jobs"], "jobId", "s2-job")
    assert [m["role"] for m in job["matchedDocuments"]] == ["snapshot-member"] and [e["eventId"] for e in job["snapshotEvents"]] == ["event-1"]
    assert job["eventCandidates"] == [{"eventCandidateId": world.evc, "state": "candidate", "reasons": [{"code": "disposition_input", "targetEventId": "event-1"}]}]
    assert [r["code"] for r in job["topicCandidates"][0]["reasons"]] == ["member_event", "cites"] and by(report["extraction"]["jobs"], "jobId", "s2-cancel")["state"] == "cancelled"
    rel = by(report["relation"]["jobs"], "jobId", "rel-main")
    assert listed(rel, ids) == {"event", "topic"} and [i["relationCandidateId"] for i in rel["impactCandidates"]] == [ids["event"]] and report["relation"]["unresolved"] == []
    checks.append("snapshot-member document -> event, disposition input, topic, event/topic-endpoint relations and the cited impact; relations citing only the other document stay out")

    # 2. The incoming document reaches the extracted candidates and everything resting on them, but not the snapshot event or its relation.
    report = run(document(main))
    job, rel = by(report["extraction"]["jobs"], "jobId", "s2-job"), by(report["relation"]["jobs"], "jobId", "rel-main")
    assert [m["role"] for m in job["matchedDocuments"]] == ["incoming"] and job["snapshotEvents"] == []
    assert job["eventCandidates"][0]["reasons"] == [{"code": "extracted_from"}] and job["comparisons"][0]["reasons"] == [{"code": "incoming_document"}]
    assert listed(rel, ids) == set(ids) - {"event"} and [i["relationCandidateId"] for i in rel["impactCandidates"]] == [ids["battery"]]
    by_id = {r["relationCandidateId"]: r for r in rel["relationCandidates"]}
    assert by_id[ids["reversed"]]["eligibility"] == "hold" and by_id[ids["forged"]]["eligibility"] == "reject" and by_id[ids["alias"]]["eligibility"] == "reject"
    assert [r["code"] for r in by_id[ids["alias"]]["reasons"]] == ["cites"] and [r["code"] for r in by_id[ids["candidate"]]["reasons"]] == ["endpoint_event", "cites"]
    checks.append("incoming document -> extracted candidates, comparisons, topic, relations incl. held/rejected/failed-citation ones; an event ID spelled as a topic is not an endpoint dependency")

    # 3. A source/grant seed lists every artifact of each affected job, and the whole-job scope equals what the owner delivers.
    s2 = kit.run("inspect", kit.job_selector("s2-job"))
    relation_result = kit.rel("inspect", kit.rsel("rel-main"))
    for request in (source(), grant()):
        report = run(request)
        for job in report["extraction"]["jobs"]:
            scope = job["jobScope"]
            assert [len(job[n]) for n in ("snapshotEvents", "eventCandidates", "comparisons", "topicCandidates")] == [scope[n] for n in ("snapshotEvents", "eventCandidates", "comparisons", "topicCandidates")]
        scope = by(report["extraction"]["jobs"], "jobId", "s2-job")["jobScope"]
        assert scope == {"boundDocuments": s2["counts"]["documents"], "snapshotEvents": s2["counts"]["snapshotEvents"], "eventCandidates": s2["counts"]["eventCandidates"]["total"],
                         "comparisons": s2["counts"]["comparisons"], "topicCandidates": s2["counts"]["topicCandidates"]}
        rel = by(report["relation"]["jobs"], "jobId", "rel-main")
        assert rel["jobScope"] == {"relationCandidates": relation_result["counts"]["relations"], "impactCandidates": relation_result["counts"]["impactCandidates"]}
        assert len(rel["relationCandidates"]) == rel["jobScope"]["relationCandidates"] and len(rel["impactCandidates"]) == rel["jobScope"]["impactCandidates"]
    checks.append("source and grant seeds list every artifact of every affected job; jobScope equals the owner's delivered S2/S3 totals")

    # 4. Frozen identities, not the current registry: revoking rights withholds the owner delivery but cannot change the report.
    baseline = text_of(document(main))
    kit.registry["sources"][0]["grant"]["enabled"] = False
    kit.save_registry()
    assert kit.rel("inspect", kit.rsel("rel-main"), expected=2)["delivery"] == {"status": "withheld", "code": "source_unauthorized"}
    assert kit.run("inspect", kit.job_selector("s2-job"), expected=2)["delivery"]["status"] == "withheld"
    assert text_of(document(main)) == baseline
    kit.registry["sources"][0]["grant"]["enabled"] = True
    kit.save_registry()
    assert kit.rel("inspect", kit.rsel("rel-main"))["delivery"]["status"] == "current"
    checks.append("with the source's grant revoked the owner inspect is withheld (exit 2) while the dependents report is byte-identical")

    # 5. Missing, hot, unknown: closed failures, never created ledgers, never success-empty.
    missing = run(document(main), relation="relation-missing", expected=2)
    assert missing == {"schemaVersion": SCHEMA, "error": {"code": "relation_state_missing"}} and not (root / "relation-missing").exists()
    shutil.copytree(root / "extraction", root / "extraction-hot")
    (root / "extraction-hot" / "extraction.sqlite3-wal").write_bytes(b"hot")
    assert run(document(main), extraction="extraction-hot", relation=None, expected=2)["error"]["code"] == "extraction_recovery_required"
    unknown = dict(document(main)["changed"], documentId="doc-unknown")
    assert run(query(unknown), expected=2) == {"schemaVersion": SCHEMA, "error": {"code": "changed_identity_unknown"}}
    assert run(grant(revision="rights-9"), expected=2)["error"]["code"] == "changed_identity_unknown"
    checks.append("absent relation ledger is not created, a hot WAL needs the writer first, unknown document/grant revision is refused instead of reported empty")

    # 5b. The same job ID and inputDigest under another FROZEN grant revision (an equal cheap join key, a different binding): the S3 jobs pinned the
    # original upstream, so they are unresolved for every seed, never omitted (r1 seed) and never attributed to the other ledger's job (r2 seed).
    other = same_request_other_binding(world, root, "extraction-r2", revision="rights-2", finish=True)
    assert other["state"] == "ready" and {d["grant"]["revision"] for d in other["binding"]["documents"].values()} == {"rights-2"}
    pinned = {"jobId": "s2-job", "inputDigest": world.s2["inputDigest"]}
    control = run(grant(revision="rights-1"))
    assert [j["jobId"] for j in control["relation"]["jobs"]] == ["rel-main", "rel-stopped"] and control["relation"]["unresolved"] == []
    for request, bound in ((grant(revision="rights-1"), False), (grant(revision="rights-2"), True), (document(main), True)):
        report = run(request, extraction="extraction-r2")
        assert report["identity"]["bound"] is bound and report["relation"]["jobs"] == []
        assert [(u["jobId"], u["code"], u["upstream"]) for u in report["relation"]["unresolved"]] == [
            ("rel-main", "upstream_binding_mismatch", pinned), ("rel-stopped", "upstream_binding_mismatch", pinned)]
    checks.append("same job ID and inputDigest with another frozen grant revision is unresolved (upstream_binding_mismatch) for r1, r2 and document seeds; the original ledger still lists both S3 jobs")

    # 6. Every output is identity-only, deterministic, and no ledger moved by a byte.
    assert text_of(document(b)) == outputs[0]
    for text in outputs:
        assert not any(sentence in text for sentence in PRIVATE) and str(root) not in text and not re.search(r"[가-힣]", text)
    assert not (root / "relation-missing").exists()
    for name in LEDGERS:
        assert sorted(p.name for p in (root / name).iterdir()) == [f"{name}.lock", f"{name}.sqlite3"]
    checks.append("reports contain no source text, quote, title, URL, label or path and are byte-deterministic; ingestion/extraction/relation directories byte/mode/mtime unchanged, no WAL/SHM created")
    return {"status": "passed", "schemaVersion": SCHEMA, "checks": checks, "providerCalls": 0, "modelCalls": 0,
            "networkAttempts": "audit hook rejected socket use and any write under the state root in every dependents subprocess; none occurred"}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zoop-s4-smoke-") as temporary:
        root = Path(temporary).resolve()
        result = smoke(root)
    assert not root.exists()
    result["temporaryStateCleanup"] = {"removed": True, "root": str(root)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
