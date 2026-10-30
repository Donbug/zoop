"""`zoop-ai-handoff freeze-round`: the cumulative window, the own-round gate and the byte-exact narrowing of the operator's master files.

Every ledger is REAL (authored-replay ingestion with timed `tick`-style rounds -> S2 -> S3 jobs, no model, no provider, no network). Expectations are hand-written from the
authored rounds, never echoed from the selector under test.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from scripts import graph_handoff_smoke as hs
from scripts.extraction_smoke import page
from scripts.ingestion_smoke import json_bytes
from scripts.relation_smoke import RelKit, converge, co, ev, proposal, world_cite
from tests.test_round_enqueue import simple_round, world  # noqa: F401 - `world` is a fixture
from tests.test_round_plan import make
from zoop_ai_pipeline import handoff_cli as cli
from zoop_ai_pipeline import handoff_round
from zoop_ai_pipeline.extraction_plan import PLAN_SCHEMA, RECEIPT_SCHEMA
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure
from zoop_ai_pipeline.handoff_contracts import POLICY
from zoop_ai_pipeline.ingestion_contracts import canonical, digest

BASE = datetime.fromisoformat("2026-10-29T09:05:00+09:00")


def slot(n: int) -> str:
    """The `tick` slot number n of the day (09:05, 09:35, ...)."""
    return (BASE + timedelta(minutes=30 * n)).isoformat()


# ---------------------------------------------------------------- a light world of independent units -----------------------------------

class Units:
    """Independent one-document units in timed rounds: unit `x` is one document, one S2 job (`s2-x`) and one S3 job (`rel-x`) with a single participation proposal."""

    def __init__(self, root: Path):
        self.kit = RelKit(root)
        self.root = root
        self.s2: dict = {}
        self.view: dict = {}

    def round(self, name: str, at: int, units: list[str], *, run: tuple | None = None) -> None:
        """One timed round holding `units` (page 0, ordinals in the given order) with their S2 jobs; S3 jobs run to `ready` unless the unit is in `defer` (queued)."""
        kit = self.kit
        docs = [{"supplier": f"supplier-{u}", "html": page(f"합성기업은 {u} 공급 계약을 발표했다.")} for u in units]
        refs = kit.ingest(name, docs, slot=slot(at))
        for unit, ref in zip(units, refs):
            art = kit.article(ref)
            text = f"합성기업은 {unit} 공급 계약을 발표했다."
            mention = {**kit.mention(art, f"m-{unit}", [kit.evidence(art, text)], event_time="2026-09-30"), "countries": ["KR"]}
            s2 = kit.job("run", kit.submit(f"s2-{unit}", ref), replay=kit.replay(f"s2-{unit}").extract(art, [mention]).write())
            assert s2["state"] == "ready", s2.get("failure")
            self.s2[unit] = s2
            self.view[unit] = SimpleNamespace(kit=kit, refs={unit: ref}, art={unit: art}, s2=s2, text=text)

    def relate(self, unit: str, *, queue: bool = False) -> dict | None:
        """Run the unit's S3 job to `ready`, or only register it (`queued`) when `queue`."""
        view = self.view[unit]
        if queue:
            queued = self.kit.rel("submit", self.kit.rsubmit(f"rel-{unit}", view.s2))
            assert queued["state"] == "queued"
            return None
        out = converge(view, f"rel-{unit}", [proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(view.s2["eventCandidates"][0]["eventCandidateId"]),
                                                         [world_cite(view, unit, view.text)])])
        assert out["state"] == "ready", out.get("failure")
        return out

    def upstream(self, unit: str) -> dict:
        return {"jobId": self.s2[unit]["jobId"], "inputDigest": self.s2[unit]["inputDigest"]}

    def entries(self, units) -> list[dict]:
        return [{"upstream": self.upstream(u), "kind": "event", "ref": self.s2[u]["eventCandidates"][0]["eventCandidateId"], "canonicalId": f"issue:{u}",
                 "decisionRef": "canon-2026-10-29:event"} for u in units]


def empty_decisions() -> dict:
    return {"schemaVersion": "zoop-public-decisions-3", "policyVersion": POLICY, "companies": [], "issues": [], "structural": [], "follows": [], "origins": []}


EMPTY_BINDINGS = {"schemaVersion": "zoop-app-document-bindings-1", "bindings": []}


class RoundRig:
    """The master operator files, the installed files directory, a handoff state directory and the `freeze-round` runner for one world."""

    def __init__(self, root: Path, kit, canonical_doc: dict, decisions: dict, bindings: dict, *, state: Path | None = None, files: Path | None = None):
        self.root, self.kit = root, kit
        self.state, self.files, self.plans = state or root / "handoff", files or root / "installed", root / "plans"
        self.plans.mkdir(exist_ok=True)
        self.write(canonical_doc, decisions, bindings)

    def write(self, canonical_doc: dict | None = None, decisions: dict | None = None, bindings: dict | None = None) -> None:
        for name, doc in (("master-canonical", canonical_doc), ("master-decisions", decisions), ("bindings", bindings)):
            if doc is not None:
                (self.root / f"{name}.json").write_bytes(json_bytes(doc))

    def argv(self, command: str, *extra: str, summaries: Path | None = None) -> list[str]:
        root, master = self.kit.root, command == "freeze-round"
        argv = ["zoop-ai-handoff", command, "--state-dir", str(self.state), "--relation-state-dir", str(root / "relation"),
                "--extraction-state-dir", str(root / "extraction"), "--ingestion-state-dir", str(root / "ingestion"), "--sources", str(self.kit.registry_path),
                "--canonical", str(self.root / "master-canonical.json" if master else self.files / "canonical.json"),
                "--decisions", str(self.root / "master-decisions.json" if master else self.files / "decisions.json"), "--bindings", str(self.root / "bindings.json")]
        if summaries is not None:
            argv += ["--issue-summary-state-dir", str(summaries)]
        return [*argv, *extra]

    def invoke(self, argv: list[str], stdin: bytes = b"", *, expected: int = 0, process: bool = False) -> dict:
        if process:
            completed = subprocess.run([sys.executable, "-m", "zoop_ai_pipeline.handoff_cli", *argv[1:]], input=stdin, capture_output=True, timeout=30)
            code, text = completed.returncode, completed.stdout.decode()
            assert code == expected, (text[:3000], completed.stderr.decode()[:3000])
        else:
            out = io.StringIO()
            with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin))), contextlib.redirect_stdout(out):
                code = cli.main()
            text = out.getvalue()
            assert code == expected, text[:3000]
        assert text.endswith("\n") and text.count("\n") == 1, text[:500]
        return json.loads(text)

    def freeze_round(self, round_id: str, plan_id: str | None = None, *, expected: int = 0, summaries: Path | None = None) -> dict:
        extra = ["--round-id", round_id, "--files-dir", str(self.files)]
        if plan_id:
            extra += ["--plan-id", plan_id, "--plan-root", str(self.plans)]
        return self.invoke(self.argv("freeze-round", *extra, summaries=summaries), expected=expected)

    def export(self, handoff_id: str, *, expected: int = 0) -> dict:
        return self.invoke(self.argv("export"), json_bytes({"schemaVersion": "zoop-ai-handoff-1", "handoffId": handoff_id}), expected=expected)

    def bundle(self, out: dict) -> dict:
        """The current export of a freeze-round result (the installed files are the ones that handoff pinned)."""
        exported = self.export(out["handoffId"])
        assert exported["delivery"]["status"] == "current", exported["delivery"]
        return exported["bundle"]

    def snapshot(self) -> dict:
        """Everything freeze-round may write: the handoff ledger and bundles, the installed files."""
        state = {str(p.relative_to(self.state)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.state.rglob("*"))
                 if self.state.exists() and p.is_file() and p.parent.name == "bundles"}
        installed = {name: hashlib.sha256((self.files / name).read_bytes()).hexdigest() for name in ("canonical.json", "decisions.json") if (self.files / name).exists()}
        rows = []
        if (self.state / "handoff.sqlite3").exists():
            import sqlite3
            db = sqlite3.connect((self.state / "handoff.sqlite3").as_uri() + "?mode=ro", uri=True)
            rows = [tuple(r) for r in db.execute("SELECT handoff_id,state FROM handoffs ORDER BY handoff_id")]
            db.close()
        return {"bundles": state, "installed": installed, "handoffs": rows}


def write_plan(plans: Path, round_id: str, upstreams: list[dict]) -> str:
    """An immutable plan directory in the exact layout `plan-round` publishes (hand-built: no model, ledger or source is needed to read it)."""
    base = {"schemaVersion": PLAN_SCHEMA, "principal": "synthetic", "round": {"roundId": round_id, "sourceId": "synthetic-source", "ingestionInputDigest": "0" * 64},
            "units": [{"jobId": u["jobId"], "inputDigest": u["inputDigest"]} for u in upstreams]}
    plan_id = "s2plan-" + digest(base)
    manifest = {**base, "planId": plan_id}
    manifest["planDigest"] = digest(manifest)
    line = lambda value: (canonical(value) + "\n").encode()  # noqa: E731
    files = {"approvals.json": line({"schemaVersion": "zoop-ai-extraction-approvals-1", "approvals": []}),
             "relation-upstreams.json": line({"schemaVersion": "zoop-ai-relation-upstreams-1", "upstreams": []}), "manifest.json": line(manifest)}
    receipt = {"schemaVersion": RECEIPT_SCHEMA, "planId": plan_id, "planDigest": manifest["planDigest"],
               "files": {name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)} for name, raw in sorted(files.items())}}
    directory = plans / plan_id
    directory.mkdir()
    for name, raw in {**files, "receipt.json": line(receipt)}.items():
        (directory / name).write_bytes(raw)
    return plan_id


def light_rig(tmp_path: Path, units: Units, mapped: list[str]) -> RoundRig:
    return RoundRig(tmp_path, units.kit, {"schemaVersion": "zoop-graph-canonical-1", "entries": units.entries(mapped)}, empty_decisions(), EMPTY_BINDINGS)


def jobs_of(out: dict) -> list[str]:
    """The S3 jobs the frozen manifest pinned, in the manifest's order."""
    return [s["relation"]["jobId"] for s in out["freeze"]["receipt"]["sources"]]


def statuses(out_or_error: dict) -> dict:
    selection = out_or_error["selection"] if "selection" in out_or_error else out_or_error["error"]["detail"]["selection"]
    return {item["jobId"]: item["status"] for item in selection["jobs"]}


@pytest.fixture
def units(tmp_path_factory):
    return Units(tmp_path_factory.mktemp("zoop-round-units") / "owned")


# ---------------------------------------------------------------- the window -------------------------------------------------------------

def test_late_completion_is_carried_into_the_next_slot(units, tmp_path):
    """R1{a,b}, R2{c,d}: b finishes after H2. H2 = {a,c,d} with b `not_ready` (R2 does not wait for R1's b); R3 has no plan and carries b: H3 = {a,b,c,d}."""
    units.round("r1", 1, ["a", "b"])
    units.round("r2", 2, ["c", "d"])
    units.relate("a")
    units.relate("b", queue=True)
    units.relate("c")
    units.relate("d")
    rig = light_rig(tmp_path, units, ["a", "b", "c", "d"])
    plan2 = write_plan(rig.plans, "round-r2", [units.upstream("c"), units.upstream("d")])

    h2 = rig.freeze_round("round-r2", plan2)
    assert sorted(jobs_of(h2)) == ["rel-a", "rel-c", "rel-d"]
    assert statuses(h2) == {"rel-a": "selected", "rel-b": "not_ready", "rel-c": "selected", "rel-d": "selected"}
    late = next(item for item in h2["selection"]["jobs"] if item["jobId"] == "rel-b")
    assert (late["code"], late["roundId"], late["slot"]) == ("queued", "round-r1", slot(1))

    units.relate("b")
    h3 = rig.freeze_round("round-r3")                                              # a slot with no new plan: carried jobs only
    assert sorted(jobs_of(h3)) == ["rel-a", "rel-b", "rel-c", "rel-d"]
    assert statuses(h3) == {f"rel-{u}": "selected" for u in "abcd"}
    assert h3["handoffId"] != h2["handoffId"] and h3["freeze"]["state"] == "ready"
    # window order is newest slot first, then page/ordinal: R2's c, d, then R1's a, b
    assert [item["jobId"] for item in h3["selection"]["jobs"]] == ["rel-c", "rel-d", "rel-a", "rel-b"]

    # a carry-only freeze of an unchanged window is the SAME handoff (the id is a pure function of the manifest content)
    again = rig.freeze_round("round-r4")
    assert again["handoffId"] == h3["handoffId"] and again["freeze"]["attempts"] == h3["freeze"]["attempts"]


def test_own_round_gate_blocks_only_the_requested_round(units, tmp_path):
    """Every S3 job admitted for the requested round must be done; an unfinished one (ledger or plan unit) is `analysis_incomplete` with nothing written."""
    units.round("r1", 1, ["a"])
    units.round("r2", 2, ["b", "c"])
    units.relate("a")
    units.relate("b", queue=True)
    units.relate("c")
    rig = light_rig(tmp_path, units, ["a", "b", "c"])
    before = rig.snapshot()
    refused = rig.freeze_round("round-r2", expected=2)
    assert refused["error"]["code"] == "analysis_incomplete"
    assert refused["error"]["detail"]["jobs"] == [{"jobId": "rel-b", "upstreamJobId": "s2-b", "code": "queued"}]
    assert not (rig.files).exists() and rig.snapshot()["handoffs"] == before["handoffs"] == []

    # a plan unit with no S3 job at all is incomplete too, even though no S3 job of that round is unfinished
    units.round("r3", 3, ["d"])
    plan = write_plan(rig.plans, "round-r3", [units.upstream("d")])
    rig.write(canonical_doc={"schemaVersion": "zoop-graph-canonical-1", "entries": units.entries(["a", "b", "c", "d"])})
    missing = rig.freeze_round("round-r3", plan, expected=2)
    assert missing["error"]["detail"]["jobs"] == [{"jobId": None, "upstreamJobId": "s2-d", "code": "relation_job_missing"}]
    assert not rig.files.exists()

    # the round that IS complete freezes, and the unfinished b of the earlier round is only reported
    units.relate("d")
    done = rig.freeze_round("round-r3", plan)
    assert statuses(done) == {"rel-a": "selected", "rel-b": "not_ready", "rel-c": "selected", "rel-d": "selected"}

    # a plan of another round is refused before anything is read from the ledgers
    other = write_plan(rig.plans, "round-r9", [units.upstream("d")])
    assert rig.freeze_round("round-r3", other, expected=2)["error"]["code"] == "plan_round_mismatch"


def test_the_window_holds_the_newest_20_mapped_jobs_and_unmapped_jobs_take_no_slot(units, tmp_path):
    """21 mapped jobs: the bundle holds the newest 20 and the oldest is reported `out_of_window` + `neverFrozen`. 20 further READY jobs nobody mapped yet take no slot: the same
    handoff id. Mapping one of them shifts the window; the job it pushes out had been frozen, the first one still never was."""
    names = [f"u{n:02d}" for n in range(21)]
    units.round("r1", 1, names[:1])
    units.round("r2", 2, names[1:11])
    units.round("r3", 3, names[11:])
    for name in names:
        units.relate(name)
    rig = light_rig(tmp_path, units, names)

    first = rig.freeze_round("round-r3")
    assert sorted(jobs_of(first)) == sorted(f"rel-{n}" for n in names[1:])
    evicted = [item for item in first["selection"]["jobs"] if item["status"] == "out_of_window"]
    assert [(item["jobId"], item["code"], item["neverFrozen"], item["roundId"]) for item in evicted] == [("rel-u00", "window_full", True, "round-r1")]
    assert first["selection"]["limit"] == 20 and len([i for i in first["selection"]["jobs"] if i["status"] == "selected"]) == 20

    extra = [f"x{n:02d}" for n in range(20)]
    units.round("r4", 4, extra[:10])
    units.round("r5", 5, extra[10:])
    for name in extra:
        units.relate(name)
    again = rig.freeze_round("round-r5")
    assert again["handoffId"] == first["handoffId"] and jobs_of(again) == jobs_of(first)
    assert sorted(i["jobId"] for i in again["selection"]["jobs"] if i["status"] == "awaiting_mapping") == sorted(f"rel-{n}" for n in extra)
    assert [i["jobId"] for i in again["selection"]["jobs"] if i["status"] == "out_of_window"] == ["rel-u00"]
    assert len(rig.snapshot()["handoffs"]) == 1

    rig.write(canonical_doc={"schemaVersion": "zoop-graph-canonical-1", "entries": units.entries([*names, "x19"])})      # x19: the newest observation (round r5, last ordinal)
    shifted = rig.freeze_round("round-r5")
    assert shifted["handoffId"] != first["handoffId"] and "rel-x19" in jobs_of(shifted)
    out = {i["jobId"]: i for i in shifted["selection"]["jobs"] if i["status"] == "out_of_window"}
    # the newest observation takes the first place; the last of the oldest window round (r2, ordinal 9 = u10) is the one that falls out, and it WAS in the first handoff
    assert {job: item["neverFrozen"] for job, item in out.items()} == {"rel-u00": True, "rel-u10": False}


def test_a_grant_revision_change_withholds_the_selected_job_and_freezes_nothing(units, tmp_path):
    units.round("r1", 1, ["a", "b"])
    units.relate("a")
    units.relate("b")
    rig = light_rig(tmp_path, units, ["a", "b"])
    good = rig.freeze_round("round-r1")
    before = rig.snapshot()
    assert before["handoffs"] == [(good["handoffId"], "ready")]

    registry = json.loads(units.kit.registry_path.read_text())
    registry["sources"][0]["grant"]["revision"] = "rights-2"
    units.kit.registry_path.write_bytes(json_bytes(registry))
    refused = rig.freeze_round("round-r1", expected=2)
    assert refused["error"]["code"] == "selected_job_withheld"
    assert refused["error"]["detail"]["jobIds"] == ["rel-a", "rel-b"]
    assert {i["jobId"]: (i["status"], i["code"]) for i in refused["error"]["detail"]["selection"]["jobs"]}.keys() == {"rel-a", "rel-b"}
    assert all(i["status"] == "withheld" for i in refused["error"]["detail"]["selection"]["jobs"])
    assert rig.snapshot() == before, "a refused freeze changed the ledger, a bundle or an installed file"


def test_freeze_round_refuses_without_a_declared_slot_or_any_mapped_job(tmp_path_factory, tmp_path):
    """An untimed round has no slot to order by; a window with no mapped job is not frozen as an empty graph."""
    world = hs.build_world(tmp_path_factory.mktemp("zoop-round-untimed") / "owned")
    rig = RoundRig(tmp_path, world.kit, hs.canonical_doc(world), hs.decisions_doc(world), hs.bindings_doc(world))
    refused = rig.freeze_round("round-docs", expected=2)
    assert refused["error"] == {"code": "round_slot_unavailable", "detail": {"jobId": "rel-a", "roundId": "round-docs"}}
    rig.write(canonical_doc={"schemaVersion": "zoop-graph-canonical-1", "entries": []})
    empty = rig.freeze_round("round-docs", expected=2)
    assert empty["error"]["code"] == "window_empty" and {i["status"] for i in empty["error"]["detail"]["selection"]["jobs"]} == {"awaiting_mapping"}
    assert not rig.files.exists() and rig.snapshot()["handoffs"] == []


@pytest.mark.parametrize(("master", "target"), [
    ("canonical", "canonical"), ("canonical", "decisions"), ("decisions", "canonical"), ("decisions", "decisions"),
])
def test_master_install_collision_is_refused_before_any_write(units, tmp_path, master, target):
    units.round("r1", 1, ["a"])
    units.relate("a")
    rig = light_rig(tmp_path, units, ["a"])
    if master == "decisions":
        rig.freeze_round("round-r1")
    else:
        rig.files.mkdir()
    for name in ("canonical", "decisions"):
        shutil.copyfile(rig.root / f"master-{name}.json", rig.files / f"{name}.json")
    collision = rig.files / f"{target}.json"
    shutil.copyfile(rig.root / f"master-{master}.json", collision)
    argv = rig.argv("freeze-round", "--round-id", "round-r1", "--files-dir", str(rig.files))
    argv[argv.index(f"--{master}") + 1] = str(collision)
    before = hs.ledger_snapshot(tmp_path)
    refused = rig.invoke(argv, expected=2, process=True)
    assert refused["error"]["code"] == "state_namespace_conflict"
    assert hs.ledger_snapshot(tmp_path) == before


@pytest.fixture
def interrupted_round(units, tmp_path):
    units.round("r1", 1, ["a"])
    units.relate("a")
    rig = light_rig(tmp_path, units, ["a"])
    original = rig.freeze_round("round-r1")
    installed = {name: (rig.files / name).read_bytes() for name in ("canonical.json", "decisions.json")}
    units.round("r2", 2, ["b"])
    units.relate("b")
    rig.write(canonical_doc={"schemaVersion": "zoop-graph-canonical-1", "entries": units.entries(["a", "b"])})
    sources = {name: hs.ledger_snapshot(units.kit.root / name) for name in ("ingestion", "extraction", "relation")}
    argv = rig.argv("freeze-round", "--round-id", "round-r2", "--files-dir", str(rig.files))
    crash = subprocess.run([sys.executable, "-c",
                            "import os; from zoop_ai_pipeline.handoff import Handoff; from zoop_ai_pipeline.handoff_cli import main; "
                            "Handoff._after_reserve = lambda self: os._exit(73); main()", *argv[1:]], capture_output=True, timeout=30)
    assert crash.returncode == 73, (crash.stdout, crash.stderr)
    yield rig, original, installed
    assert {name: hs.ledger_snapshot(units.kit.root / name) for name in sources} == sources


def test_reserved_repeat_preserves_the_installed_pair(interrupted_round):
    rig, original, installed = interrupted_round
    reserved = rig.freeze_round("round-r2")
    assert reserved["freeze"]["state"] == "reserved" and reserved["freeze"]["attempts"] == []
    assert {name: (rig.files / name).read_bytes() for name in installed} == installed
    assert rig.export(original["handoffId"])["delivery"]["status"] == "current"
    assert rig.freeze_round("round-r3")["freeze"] == reserved["freeze"]


def test_explicit_recovery_attempt_preserves_failed_history(interrupted_round):
    rig, original, installed = interrupted_round
    reserved = rig.freeze_round("round-r2")
    selector = json_bytes({"schemaVersion": "zoop-ai-handoff-1", "handoffId": reserved["handoffId"]})
    ledger_argv = ["zoop-ai-handoff", "recover", "--state-dir", str(rig.state)]
    failed = rig.invoke(ledger_argv, selector, process=True)
    assert failed["state"] == "failed" and failed["failure"] == {"code": "handoff_artifact_missing"}
    assert failed["attempts"] == [{"n": 1, "kind": "recover", "outcome": "artifact-missing", "code": "handoff_artifact_missing"}]
    assert rig.freeze_round("round-r3")["freeze"] == failed
    assert {name: (rig.files / name).read_bytes() for name in installed} == installed
    with contextlib.closing(handoff_round.Store(rig.state, mode="read")) as store:
        failed_row = dict(store.handoff(failed["handoffId"]))
        failed_attempts = [dict(attempt) for attempt in store.attempts(failed["handoffId"])]
    argv = rig.argv("freeze-round", "--round-id", "round-r3", "--files-dir", str(rig.files), "--recovery-attempt-id", "operator-recovery-1")
    recovered = rig.invoke(argv, process=True)
    assert recovered["freeze"]["state"] == "ready" and recovered["handoffId"] != failed["handoffId"]
    assert jobs_of(recovered) == ["rel-a", "rel-b"]
    assert rig.invoke(argv, process=True)["freeze"] == recovered["freeze"]
    argv[argv.index("--round-id") + 1] = "round-r4"
    assert rig.invoke(argv, process=True)["freeze"] == recovered["freeze"]
    ready_snapshot = rig.snapshot()
    assert rig.freeze_round("round-r4")["freeze"] == failed
    assert rig.snapshot() == ready_snapshot
    assert rig.invoke([ledger_argv[0], "inspect", *ledger_argv[2:]], selector, process=True) == failed
    with contextlib.closing(handoff_round.Store(rig.state, mode="read")) as store:
        assert dict(store.handoff(failed["handoffId"])) == failed_row
        assert [dict(attempt) for attempt in store.attempts(failed["handoffId"])] == failed_attempts
    assert rig.snapshot()["handoffs"] == sorted([(original["handoffId"], "ready"), (failed["handoffId"], "failed"), (recovered["handoffId"], "ready")])
    assert rig.export(recovered["handoffId"])["delivery"]["status"] == "current"


# ---------------------------------------------------------------- the authored issue world through freeze-round ----------------------

def rich_world(tmp_path_factory, **options):
    return hs.build_world(tmp_path_factory.mktemp("zoop-round-rich") / "owned", **options)


def rich_rig(tmp_path: Path, world, decisions: dict | None = None, *, files: Path | None = None) -> RoundRig:
    return RoundRig(world.root, world.kit, hs.canonical_doc(world), decisions or hs.decisions_doc(world), hs.bindings_doc(world), state=tmp_path / "handoff", files=files or tmp_path / "installed")


def public_ids(bundle: dict) -> dict:
    return {"issues": {i["id"] for i in bundle["issues"]}, "involves": {r["id"] for r in bundle["relations"] if r["type"] == "INVOLVES"},
            "evidence": {e["id"] for e in bundle["evidence"]}}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_public_ids_are_continuous_across_versions_and_a_full_window_equals_the_plain_freeze(tmp_path_factory, tmp_path):
    """V1 = {rel-a} while rel-b is still queued, V2 = {rel-a, rel-b}, V3 = a carry-only slot after the operator's field review. Issue ids, INVOLVES edge ids and `ev-` ids of the same
    span never change; V1 is a subset of V2; V2 (the whole ledger in the window, nothing to narrow) has exactly the content of the plain strict `freeze` of the master files."""
    world = rich_world(tmp_path_factory, slots=(slot(1), slot(2)), defer_b=True)
    rig = rich_rig(tmp_path, world)
    v1 = rig.freeze_round("round-docs-a")
    assert jobs_of(v1) == ["rel-a"] and statuses(v1) == {"rel-a": "selected", "rel-b": "not_ready"}
    assert v1["narrowing"]["issuesKept"] == ["issue:supply"] and v1["narrowing"]["issuesDropped"] == ["issue:factory", "issue:overseas"]
    b1 = rig.bundle(v1)

    world.finish_rel_b()
    v2 = rig.freeze_round("round-docs-b")
    assert sorted(jobs_of(v2)) == ["rel-a", "rel-b"] and [i["jobId"] for i in v2["selection"]["jobs"]] == ["rel-a", "rel-b"]      # a's round is the newer slot
    assert v2["narrowing"]["issuesDropped"] == [] and v2["narrowing"]["fieldVerdictsDropped"] == 0
    b2 = rig.bundle(v2)

    rig.write(decisions=hs.reviewed(world, published_time=None))
    v3 = rig.freeze_round("round-docs-3")
    b3 = rig.bundle(v3)
    assert len({v1["handoffId"], v2["handoffId"], v3["handoffId"]}) == 3

    ids1, ids2, ids3 = public_ids(b1), public_ids(b2), public_ids(b3)
    assert ids1["issues"] == {hs.SUPPLY} and ids1["involves"] and ids1["evidence"]
    for key in ("issues", "involves", "evidence"):
        assert ids1[key] <= ids2[key] <= ids3[key], key
    assert hs.FACTORY in ids2["issues"] and hs.FACTORY not in ids1["issues"]
    span = hs.evidence_id(world, "a", hs.EVT_A)
    assert all(span in ids for ids in (ids1["evidence"], ids2["evidence"], ids3["evidence"]))

    # the plain strict freeze of the same master files over the same two jobs
    rig.write(decisions=hs.decisions_doc(world))
    pins = [{"relation": {"jobId": job, "inputDigest": out["inputDigest"]}, "upstream": dict(out["binding"]["upstream"]), "reviewDigest": digest(hs.review_state(out))}
            for job, out in sorted(world.jobs.items())]
    files = {"canonical": sha(rig.root / "master-canonical.json"), "decisions": sha(rig.root / "master-decisions.json"), "bindings": sha(rig.root / "bindings.json")}
    manifest = {"schemaVersion": "zoop-ai-handoff-1", "handoffId": "plain-1", "sourceKind": "synthetic", "policyVersion": POLICY, "sources": pins, "files": files}
    plain_argv = [*rig.argv("freeze")]
    plain_argv[plain_argv.index("--state-dir") + 1] = str(tmp_path / "plain-state")
    plain_argv[plain_argv.index("--canonical") + 1] = str(rig.root / "master-canonical.json")
    plain_argv[plain_argv.index("--decisions") + 1] = str(rig.root / "master-decisions.json")
    plain = rig.invoke(plain_argv, json_bytes(manifest))
    assert plain["state"] == "ready"
    v2_again = rig.freeze_round("round-docs-4")
    assert v2_again["handoffId"] == v2["handoffId"], "unchanged operator files and window must give the V2 handoff again"
    exported = rig.invoke([plain_argv[0], "export", *plain_argv[2:]], json_bytes({"schemaVersion": "zoop-ai-handoff-1", "handoffId": "plain-1"}))
    assert exported["bundle"]["digests"]["content"] == b2["digests"]["content"]
    assert exported["bundle"]["issues"] == b2["issues"] and exported["bundle"]["relations"] == b2["relations"]


def test_a_representative_pushed_out_of_the_window_excludes_only_its_issue(tmp_path_factory, tmp_path, monkeypatch):
    """The supply issue's operator-pinned representative lives in rel-a's upstream. With a window of ONE job and rel-b the newer round, rel-a is pushed out: only the supply issue is
    excluded (`issue_representative_invalid`) while the freeze succeeds, and its summary pin (it names no ledger here) is dropped as `issue_not_public`."""
    world = rich_world(tmp_path_factory, slots=(slot(2), slot(1)))
    pin = {"jobId": "summary-job-x", "inputDigest": "1" * 64, "resultDigest": "2" * 64}
    rig = rich_rig(tmp_path, world, hs.decisions_doc(world, summaries={"issue:supply": pin}))
    monkeypatch.setattr(handoff_round, "WINDOW", 1)
    out = rig.freeze_round("round-docs-b")
    assert jobs_of(out) == ["rel-b"]
    assert {i["jobId"]: (i["status"], i.get("neverFrozen")) for i in out["selection"]["jobs"]} == {"rel-b": ("selected", None), "rel-a": ("out_of_window", True)}
    assert out["narrowing"]["summaryPinsDropped"] == [{"issueId": hs.SUPPLY, "code": "issue_not_public"}]
    bundle = rig.bundle(out)
    assert {i["id"] for i in bundle["issues"]} == {hs.FACTORY}                       # the overseas issue is never public: its mention states no country (`geography_unproven`), in every window
    assert sorted((e["id"], e["code"]) for e in bundle["exclusions"]["items"] if e["kind"] == "issue") == [
        ("issue:overseas", "geography_unproven"), ("issue:supply", "issue_representative_invalid")]


def test_out_of_window_verdicts_and_stale_summary_pins_are_dropped_and_current_ones_kept(tmp_path_factory, tmp_path, monkeypatch):
    """A real produced issue summary (authored replay) pinned by the master decisions. Full window: the supply pin stays (its summary is `available`), a pin on an issue with a HOLD
    verdict is dropped (the deterministic `temporal-review-pending` decides it). A window that loses the second article: the verdict on that article's mention is dropped and the
    pin's basis changed, so the issue carries `not-requested`. A pin that survives without its ledger is still refused by the strict freeze, leaving the installed files alone."""
    world = rich_world(tmp_path_factory, uncited_source=True, slots=(slot(1), slot(1)))
    rig = rich_rig(tmp_path, world, files=world.root)           # the summary job reads the installed files at the world's own operator-file paths
    held = hs.field_verdict(world, "b", "m-b", "period", "2026Q4", "HOLD", "ambiguous", [hs.PERIOD_B])
    allowed = hs.field_verdict(world, "a2", "m-a2", "period", "2026Q3", "ALLOW", "stated", [hs.PERIOD_A2])
    verdicts = {"issue:factory": [held], "issue:supply": [allowed]}

    rig.write(decisions=hs.decisions_doc(world, verdicts=verdicts))
    unpinned = rig.freeze_round("round-docs")
    assert sorted(jobs_of(unpinned)) == ["rel-a", "rel-b"] and unpinned["narrowing"]["fieldVerdictsDropped"] == 0
    exported = rig.export(unpinned["handoffId"])
    fixture = world.root / "summary-fixture.json"
    fixture.write_bytes(json_bytes(hs.summary_fixture(world, exported["bundle"], hs.SUPPLY, hs.SUMMARY_CLAIMS, ["supported"])))
    selector = {"schemaVersion": "zoop-issue-summary-1", "jobId": "summary-job-1"}
    request = {**selector, "issueId": hs.SUPPLY, "mode": "replay", "manifest": exported["manifest"]}
    hs.summary_cli(world, "submit", request)
    assert hs.summary_cli(world, "run", request, fixture=fixture)["state"] == "ready"
    done = hs.summary_cli(world, "export", selector)
    pin = {key: done[key] for key in ("jobId", "inputDigest", "resultDigest")}
    ledger = world.root / "summary"

    rig.write(decisions=hs.decisions_doc(world, verdicts=verdicts, summaries={"issue:supply": pin, "issue:factory": pin}))
    full = rig.freeze_round("round-docs", summaries=ledger)
    assert full["narrowing"]["summaryPinsDropped"] == [{"issueId": hs.FACTORY, "code": "temporal-review-pending"}]
    summaries = {i["id"]: i["summary"] for i in rig.bundle(full)["issues"]}
    assert summaries[hs.SUPPLY] == done["summary"] and summaries[hs.FACTORY] == {"status": "unavailable", "code": "temporal-review-pending", "source": None}

    before = rig.snapshot()
    refused = rig.freeze_round("round-docs", expected=2)                      # the surviving supply pin needs its ledger
    assert refused["error"]["code"] == "issue_summary_state_missing" and rig.snapshot() == before

    with monkeypatch.context() as window:
        window.setattr(handoff_round, "WINDOW", 1)
        narrow = rig.freeze_round("round-docs", summaries=ledger)
    assert jobs_of(narrow) == ["rel-a"] and [i["jobId"] for i in narrow["selection"]["jobs"] if i["status"] == "out_of_window"] == ["rel-b"]
    assert narrow["narrowing"]["issuesDropped"] == ["issue:factory", "issue:overseas"] and narrow["narrowing"]["fieldVerdictsDropped"] == 1
    assert narrow["narrowing"]["summaryPinsDropped"] == [{"issueId": hs.SUPPLY, "code": "issue_summary_basis_changed"}]
    issue = {i["id"]: i for i in rig.bundle(narrow)["issues"]}[hs.SUPPLY]
    assert issue["summary"] == {"status": "unavailable", "code": "not-requested", "source": None} and issue["fieldVerdicts"] == []
    assert {m["mentionId"] for m in issue["mentions"]} == {"m-a"}


# ---------------------------------------------------------------- byte-exact narrowing (pure) ------------------------------------------

MASTER_DECISIONS = """{ "schemaVersion" : "zoop-public-decisions-3", "policyVersion":"p",
 "companies":[ {"canonicalId":"co:1","publicId":"A","label":"é\\u00e9","decisionRef":"d:1"} ],
 "issues":[
  {"canonicalId":"issue:keep","publicId":"pub:keep","fieldVerdicts":[ {"documentId":"d1","documentVersion":"v1","mentionId":"m1",  "field":"period"},
      {"documentId":"d2","documentVersion":"v2","mentionId":"m2","field":"period"} ], "summary" : {"jobId":"j","inputDigest":"i","resultDigest":"r"}},
  {"canonicalId":"issue:gone","publicId":"pub:gone","fieldVerdicts":[],"summary":null}],
 "structural":[ {"issue":"issue:keep","company":"co:1"}, {"issue":"issue:gone","company":"co:1"} ],
 "follows":[ {"from":"issue:keep","to":"issue:gone"}, {"from":"issue:keep","to":"issue:keep"} ],
 "origins":[ {"documentId":"d1","documentVersion":"v1"}, {"documentId":"d9","documentVersion":"v9"} ] }"""


def test_narrowing_selects_the_masters_own_text():
    raw = MASTER_DECISIONS.encode()
    narrowed = handoff_round.narrow_decisions(raw, {"issue:keep": {("d1", "v1", "m1")}}, {("d1", "v1")})
    text = narrowed.raw.decode()
    members = dict(handoff_round.split_object(text))
    original = dict(handoff_round.split_object(MASTER_DECISIONS))
    # an array no rule touches keeps every byte; kept elements are the master's own text, spaces and escapes included
    assert members["companies"] == original["companies"] and "é\\u00e9" in members["companies"]
    assert handoff_round.split_array(members["structural"]) == [handoff_round.split_array(original["structural"])[0]]
    assert handoff_round.split_array(members["follows"]) == [handoff_round.split_array(original["follows"])[1]]
    assert handoff_round.split_array(members["origins"]) == [handoff_round.split_array(original["origins"])[0]]
    (issue,) = handoff_round.split_array(members["issues"])
    fields = dict(handoff_round.split_object(issue))
    master_issue = dict(handoff_round.split_object(handoff_round.split_array(original["issues"])[0]))
    assert handoff_round.split_array(fields["fieldVerdicts"]) == [handoff_round.split_array(master_issue["fieldVerdicts"])[0]]
    assert {k: v for k, v in fields.items() if k != "fieldVerdicts"} == {k: v for k, v in master_issue.items() if k != "fieldVerdicts"}
    assert (narrowed.issues, narrowed.dropped_issues, narrowed.verdicts_dropped) == (["issue:keep"], ["issue:gone"], 1)

    dropped = dict(handoff_round.split_object(handoff_round.split_array(dict(handoff_round.split_object(
        handoff_round.drop_summary_pins(narrowed.raw, {"pub:keep"}).decode()))["issues"])[0]))
    assert dropped["summary"] == "null" and {k: v for k, v in dropped.items() if k != "summary"} == {k: v for k, v in fields.items() if k != "summary"}
    assert handoff_round.drop_summary_pins(narrowed.raw, {"pub:other"}) == narrowed.raw


def test_narrowing_the_registry_keeps_whole_entries_in_order():
    entry = lambda job, ref: f'{{ "upstream" : {{"jobId":"{job}","inputDigest":"{"a" * 64}"}}, "kind":"event", "ref":"{ref}", "canonicalId":"c:{ref}", "decisionRef":"d:\\u00e9" }}'  # noqa: E731
    raw = ('{"schemaVersion":"zoop-graph-canonical-1",\n "entries":[\n ' + ",\n ".join([entry("s2-a", "r1"), entry("s2-b", "r2"), entry("s2-a", "r3")]) + "]}").encode()
    narrowed, kept = handoff_round.narrow_registry(raw, {("s2-a", "a" * 64)})
    assert kept == 2 and handoff_round.split_array(dict(handoff_round.split_object(narrowed.decode()))["entries"]) == [entry("s2-a", "r1"), entry("s2-a", "r3")]
    assert handoff_round.narrow_registry(raw, set())[1] == 0


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"a":1} x', '[1]', '{"a":1,}', '{"a" 1}', "", '{"a":'])
def test_the_splitter_refuses_anything_but_one_object_with_unique_keys(text):
    with pytest.raises(ValueError):
        handoff_round.split_object(text)


def test_freeze_round_flags_are_validated_before_anything_is_opened(tmp_path):
    rig = RoundRig(tmp_path, SimpleNamespace(root=tmp_path / "absent-world", registry_path=tmp_path / "sources.json"), {}, {}, {})
    plan = "s2plan-" + "a" * 64
    cases = [
        rig.argv("freeze-round", "--round-id", "r"),                                                                  # no --files-dir
        rig.argv("freeze-round", "--files-dir", str(tmp_path / "f")),                                                   # no --round-id
        rig.argv("freeze-round", "--round-id", "r", "--files-dir", str(tmp_path / "f"), "--plan-id", plan),             # plan without root
        rig.argv("freeze-round", "--round-id", "r", "--files-dir", str(tmp_path / "f"), "--plan-root", str(tmp_path)),  # root without plan
        rig.argv("freeze-round", "--round-id", "r", "--files-dir", str(tmp_path / "f"), "--plan-id", "../x", "--plan-root", str(tmp_path)),
        rig.argv("freeze-round", "--round-id", "r" * 201, "--files-dir", str(tmp_path / "f")),
        rig.argv("freeze", "--round-id", "r"),                                                                        # round flags belong to freeze-round only
        rig.argv("export", "--files-dir", str(tmp_path / "f")),
        rig.argv("freeze", "--recovery-attempt-id", "operator-1"),
        ["zoop-ai-handoff", "recover", "--state-dir", str(rig.state), "--recovery-attempt-id", "operator-1"],
    ]
    whole = rig.argv("freeze-round", "--round-id", "r", "--files-dir", str(tmp_path / "f"))
    cases.extend([*whole, "--recovery-attempt-id", attempt] for attempt in ("", "a" * 201, "../x", "attempt\n"))
    at = whole.index("--bindings")
    cases.append(whole[:at] + whole[at + 2:])                                                                          # a source flag missing
    for argv in cases:
        assert rig.invoke(argv, b"{}", expected=2)["error"]["code"] == "input_or_configuration_invalid", argv
    assert not rig.state.exists() and not (tmp_path / "f").exists()


def test_a_real_plan_round_directory_names_the_units_of_its_round(world, tmp_path):
    """`plan_units` over the directory `zoop-ai-extract plan-round` really publishes (not the hand-built layout of the other tests)."""
    rid, _ = simple_round(world.kit, "plan", ["supplier-a", "supplier-b"])
    staged = tmp_path / "staged"
    receipt = make(world, staged, rid)
    plans = tmp_path / "plans"
    plans.mkdir()
    staged.rename(plans / receipt["planId"])
    manifest = json.loads((plans / receipt["planId"] / "manifest.json").read_text())
    units = handoff_round.plan_units(plans, receipt["planId"], rid)
    assert units == {(u["jobId"], u["inputDigest"]) for u in manifest["units"]} and len(units) == 2
    with pytest.raises(ExtractionFailure) as refused:
        handoff_round.plan_units(plans, receipt["planId"], "another-round")
    assert refused.value.code == "plan_round_mismatch"
