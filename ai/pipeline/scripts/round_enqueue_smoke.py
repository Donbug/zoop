#!/usr/bin/env python3
"""FS076 completed round -> S2-2 registration: actual `zoop-ai-extract enqueue-round` subprocesses over a real `zoop-ai-ingest tick` ledger.

Every expectation below is an authored literal from the settled contract, never the enqueue implementation's own output:
  * the job ID is recomputed here as `"s2r-" + digest({format: "zoop-round-enqueue-1", enqueueId, observation})` from the contract text, and the stored
    `input_digest`/`request` of every job is recomputed from the descriptor and the replay (or live runtime identity) bytes this script wrote;
  * the plan (held / ambiguous / in_snapshot / duplicate_in_round, their codes and details, the counts) follows from the authored layout of the
    source round, whose ingestion states are verified first through the actual `zoop-ai-ingest inspect`, a hundred references per page;
  * nothing here imports `extraction_enqueue` or the planner. Only the generic canonical `digest` and the existing authored fixture kits are shared.

Every child runs under an audit hook that aborts any socket/DNS event, and under a second hook that ends the process (exit 76) if it reaches stage
execution, a replay lookup or a call reservation, so a registration that made a call would fail the run instead of being believed. Crashes, a registry
that changes in the middle of a batch and an injected freeze failure are monkeypatches of the throwaway wrapper only; there is no production hook.
The extraction ledger is inspected only through private copies (the committed rows of a killed writer live in its WAL) and the CLI's own outputs.
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.extraction_smoke import CATALOGUE, CUSTOM, FAKE_KEYS, LIVE_PROMPT, PROMPT, Kit, Replay, page, simulator_env  # noqa: E402
from scripts.ingestion_smoke import json_bytes, ownership_env, sha  # noqa: E402
from scripts.round_smoke import CHILDREN, HOOKS, NETWORK_GUARD, SCOPE, SOURCE, Rounds, at, due, guard_probe, instant, pause_hook, round_id, slot  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import canonical, digest  # noqa: E402

SCHEMA = "zoop-extraction-s2-2"
ENQUEUE_FORMAT = "zoop-round-enqueue-1"
REPLAY_ADAPTER, LIVE_ADAPTER = "zoop-extraction-native-replay-3", "zoop-extraction-native-live-3"
PROMPT_2 = "zoop-extraction-authored-2"
CATALOGUE_2 = {**CATALOGUE, "revision": "catalogue-2"}
TOPIC = {"producerVersion": "zoop-topic-replay-producer-1"}
SCOPE_MISSING = "article_scope_ambiguous_or_missing"   # HTML with no article element
RESTRICTED = "access_restricted"                       # an explicit paywall marker
AMBIGUOUS_CODE = "source_identity_ambiguous"           # a URL already owned by another supplier document
GATE, BUDGET_DIR = "ZOOP_AI_PIPELINE_LIVE_ENABLED", "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"
NO_JOBS = {"stages": 0, "calls": 0, "event_candidates": 0, "comparisons": 0, "dispositions": 0, "topic_candidates": 0}

# The process dies (76) if registration ever reaches stage execution, a replay record lookup or a call reservation.
FORBID = ("from zoop_ai_pipeline.extraction import Extractor, Fixtures\n"
          "def _forbidden(*a, **k):\n os._exit(76)\n"
          "Extractor._execute = Extractor._reserve = Extractor._receipted = Extractor._live_receipted = Fixtures.index = _forbidden\n")


def ledger_hook(*, after: int | None = None, then: str = "", before: int | None = None, fail: str = "") -> str:
    """Child-only wrapper of the extraction ledger's write transaction, which is exactly one freeze each: `then` runs right after the `after`-th COMMIT,
    `fail` instead of the `before`-th transaction (nothing of it is written)."""
    text = ("import contextlib\nfrom zoop_ai_pipeline import extraction as _x\n_orig, _n = _x.Store.transaction, [0]\n"
            "@contextlib.contextmanager\ndef _tx(self, guard=None):\n _n[0] += 1\n")
    if before is not None:
        text += f" if _n[0] == {before}:\n  {fail}\n"
    text += " with _orig(self, guard):\n  yield\n"
    if after is not None:
        text += f" if _n[0] == {after}:\n  {then}\n"
    return text + "_x.Store.transaction = _tx\n"


def open_hook(then: str) -> str:
    """Child-only: `then` runs right after the extraction writer ledger is opened, i.e. after the round was authorized and read, before any preflight."""
    return ("from zoop_ai_pipeline import extraction as _x\n_init = _x.Store.__init__\n"
            "def _open(self, *a, **k):\n _init(self, *a, **k)\n " + then + "\n_x.Store.__init__ = _open\n")


def close_hook(then: str) -> str:
    """Child-only: `then` runs right after the extraction ledger was really closed (every commit is durable by then) and makes that close report a failure."""
    return ("import sqlite3\nfrom zoop_ai_pipeline import extraction as _x\n_shut = _x.Store.close\n"
            "def _close(self):\n _shut(self)\n " + then + "\n_x.Store.close = _close\n")


# ======================================================================== authored contract literals ===============

def text_of(tag: str) -> str:
    return f"합성기업은 {tag} 공급 계약을 발표했다."


NO_ARTICLE = "<html><body><div>본문 없음</div></body></html>".encode()
PAYWALL = '<html><body><article class="paywall"><p>구독자 전용</p></article></body></html>'.encode()


def observation(rid: str, ref: dict) -> dict:
    """The exact ObservationRef wire: the round, the source and the five identities of one prepared candidate."""
    return {"roundId": rid, "sourceId": SOURCE, "page": ref["page"], "ordinal": ref["ordinal"], "documentId": ref["documentId"],
            "rawVersion": ref["rawVersion"], "documentVersion": ref["documentVersion"]}


def job_id(enqueue_id: str, observed: dict) -> str:
    """Contract: only the label and the exact observation enter the id; the descriptor and the replay/live input never do."""
    found = "s2r-" + digest({"format": ENQUEUE_FORMAT, "enqueueId": enqueue_id, "observation": observed})
    assert len(found) == 68
    return found


def descriptor(rid: str, enqueue_id: str, *, snapshot: dict | None = None, topic: dict | None = None, prompt: str = PROMPT, catalogue: dict | None = None,
               source_kind: str = "synthetic", live: bool = False, source: str = SOURCE) -> dict:
    mode = ("live", "provider") if live else ("replay", "authored-test")
    return {"schemaVersion": SCHEMA, "enqueueId": enqueue_id, "roundId": rid, "sourceId": source,
            "provenance": {"sourceKind": source_kind, "executionMode": mode[0], "recordingKind": mode[1]}, "promptVersion": prompt,
            "catalogue": catalogue or CATALOGUE, "snapshot": snapshot or {"revision": "snapshot-1", "events": []}, "topic": topic}


def submit_of(d: dict, jid: str, observed: dict) -> dict:
    """The one ordinary Submit the descriptor means for an observation (the contract says it is byte-identical to a hand-written submit)."""
    return {"schemaVersion": SCHEMA, "jobId": jid, "provenance": d["provenance"], "promptVersion": d["promptVersion"], "incoming": observed,
            "catalogue": d["catalogue"], "snapshot": d["snapshot"], "topic": d["topic"]}


def expected_report(enqueue_id: str, rid: str, first: dict, refs: list[dict], skips: dict, registration="registered", *, outcome: str = "complete", error: dict | None = None) -> dict:
    """The authored report. `skips`: (page, ordinal) -> (code, detail); a detail of ("kept", position) means the job id of that kept observation.
    `registration`: one literal for every job, or a function of the job's index in plan order."""
    state_of = registration if callable(registration) else (lambda index: registration)
    ids = {(r["page"], r["ordinal"]): job_id(enqueue_id, observation(rid, r)) for r in refs if (r["page"], r["ordinal"]) not in skips}
    jobs, skipped = [], []
    for r in refs:
        position = (r["page"], r["ordinal"])
        if position in skips:
            code, detail = skips[position]
            skipped.append({"page": position[0], "ordinal": position[1], "documentId": r["documentId"], "documentVersion": r["documentVersion"], "code": code,
                            "detail": ids[detail[1]] if isinstance(detail, tuple) else detail})
        else:
            jobs.append({"jobId": ids[position], "page": position[0], "ordinal": position[1], "documentId": r["documentId"], "rawVersion": r["rawVersion"],
                         "documentVersion": r["documentVersion"], "registration": state_of(len(jobs))})
    states = Counter(job["registration"] for job in jobs)
    return {"schemaVersion": SCHEMA, "enqueueId": enqueue_id,
            "round": {"roundId": rid, "sourceId": SOURCE, "inputDigest": first["inputDigest"], "provenance": first["provenance"], "completion": first["completion"]},
            "outcome": outcome, "jobs": jobs, "skipped": skipped,
            "counts": {"refs": len(refs), "jobs": len(jobs), "registered": states["registered"], "existing": states["existing"], "failed": states["failed"],
                       "notAttempted": states["not-attempted"], "skipped": len(skipped)},
            "error": error}


def diff(actual, expected, path: str = "$") -> str | None:
    """The first difference of two JSON values, short enough to read (a 200-job report is never dumped)."""
    if type(actual) is not type(expected):
        return f"{path}: {type(actual).__name__} != {type(expected).__name__}"
    if isinstance(actual, dict):
        for key in sorted(set(actual) | set(expected)):
            if key not in actual or key not in expected:
                return f"{path}.{key}: present on one side only"
            found = diff(actual[key], expected[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(actual, list):
        if len(actual) != len(expected):
            return f"{path}: length {len(actual)} != {len(expected)}"
        for index, (a, b) in enumerate(zip(actual, expected)):
            found = diff(a, b, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if actual == expected else f"{path}: {actual!r} != {expected!r}"


def same(actual, expected, what: str) -> None:
    found = diff(actual, expected)
    assert found is None, f"{what}: {found}"


def refused(out, code: str) -> None:
    assert out == {"schemaVersion": SCHEMA, "error": {"code": code}}, out


def fingerprint(folder: Path) -> dict:
    """Mode, size, mtime and sha256 of every file plus the directory itself: a read-only open must leave all of it alone."""
    return {p.name: (stat.S_IMODE(p.stat().st_mode), p.stat().st_size, p.stat().st_mtime_ns, sha(p.read_bytes())) for p in sorted(folder.iterdir())} | {
        ".": (stat.S_IMODE(folder.stat().st_mode), folder.stat().st_mtime_ns)}


@contextlib.contextmanager
def edited(w: "World", mutate):
    """The source registry with `mutate` applied for the duration of the block, restored to the original bytes afterwards."""
    original = copy.deepcopy(w.registry)
    mutate(w.registry)
    w.save_registry()
    try:
        yield
    finally:
        w.registry = original
        w.save_registry()


def grant(r: dict) -> dict:
    return r["sources"][0]["grant"]


def doc_item(w: "World", key: str, *, supplier: str | None = None, url: str | None = None, candidate: str | None = None) -> dict:
    return w.item(candidate or key, supplier or "supplier-" + key, url or f"https://example.invalid/{key}", ref=key)


def docs(w: "World", keys) -> tuple[list[dict], dict]:
    return [doc_item(w, key) for key in keys], {key: page(text_of(key)) for key in keys}


# ======================================================================== the world ================================

class World(Rounds, Kit):
    """One authored source, one ingestion state directory (`ingestion`, driven by real `tick` children) and any number of extraction ledgers.

    `Rounds.article` builds a source item and `Kit.article` decodes an observation: the names collide, so this script only uses `doc_item` and `document`."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.through = instant(at("00:00:00"))

    def document(self, observed: dict):
        return Kit.article(self, observed)

    def finish(self, child, expected, timeout: int = 300):
        stdout, stderr = child.communicate(timeout=timeout)
        text = stderr.decode()
        self.calls = [line.removeprefix("TRACE:") for line in text.splitlines() if line.startswith("TRACE:")]
        assert child.returncode == expected, (child.returncode, expected, stdout.decode(), text)
        return json.loads(stdout) if stdout else None

    def run(self, command, request, **options):
        CHILDREN.append("extract:" + command)
        return Kit.run(self, command, request, **options)

    def new_round(self, hhmm: str, items, bodies, *, first: bool = False, pages=None) -> tuple[str, dict]:
        """One complete ingestion round through the real `tick` (slot `hhmm` on Saturday). `through` tracks the stored boundary for the catch-up flag."""
        when = slot(hhmm)
        manifest = self.covering("m-" + hhmm.replace(":", ""), when, items, bodies, pages=pages)
        now = at(hhmm + ":30")
        catch_up = instant(when) - self.through > timedelta(minutes=30)
        result = due(self, self.tick(now, initial=at("00:00:00") if first else None, manifest=manifest, state="ingestion"), "started", now, when, catch_up, "complete")
        self.through = instant(when)
        return round_id(SCOPE, when), result

    def refs(self, rid: str) -> tuple[dict, list[dict]]:
        """The first page's round summary and EVERY reference, read through the actual `zoop-ai-ingest inspect` a hundred at a time."""
        first, refs, offset = None, [], 0
        while offset is not None:
            out = self.command("inspect", self.selector(rid, offset=offset, limit=100), state="ingestion")
            first = first or out
            refs += out["documentRefs"]
            offset = out["pagination"]["nextOffset"]
        return first, refs

    def jobs_ledger(self, state: str = "extraction") -> dict | None:
        """Every job row and the row count of every table, from a private copy of the database and its WAL (a killed writer's rows are only in the WAL)."""
        source = self.root / state
        if not (source / "extraction.sqlite3").exists():
            return None
        copied = self.root / f"ledger-copy-{next(self.counter)}"
        copied.mkdir()
        try:
            for name in ("extraction.sqlite3", "extraction.sqlite3-wal"):
                if (source / name).exists():
                    shutil.copy2(source / name, copied / name)
            db = sqlite3.connect(copied / "extraction.sqlite3")
            db.row_factory = sqlite3.Row
            try:
                rows = [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY job_id")]      # every column, the frozen binding included
                tables = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("jobs", *NO_JOBS)}
            finally:
                db.close()
        finally:
            shutil.rmtree(copied)
        return {"jobs": rows, "tables": tables}

    def enqueue(self, d, *, replay: Path | None = None, topic: Path | None = None, state: str = "extraction", expected: int = 0, hooks=(), env: dict | None = None,
                flags=(), raw: bool = False, timeout: int = 900):
        """`zoop-ai-extract enqueue-round` as a real child: no network, no execution (a stage/replay/call attempt ends it with 76), canonical stdout."""
        program = NETWORK_GUARD + FORBID + "".join(hooks) + "runpy.run_module('zoop_ai_pipeline.extraction_cli', run_name='__main__')\n"
        argv = [sys.executable, "-c", program, "enqueue-round", *flags, "--state-dir", str(self.root / state), "--ingestion-state-dir", str(self.root / "ingestion"),
                "--sources", str(self.registry_path)]
        if replay:
            argv += ["--replay", str(replay)]
        if topic:
            argv += ["--topic-replay", str(topic)]
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM, **(env or {})}
        CHILDREN.append("enqueue-round")
        child = subprocess.run(argv, input=json_bytes(d), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, cwd=PIPELINE, timeout=timeout)
        assert child.returncode == expected, (child.returncode, expected, child.stdout.decode()[:2000], child.stderr.decode()[:2000])
        assert child.stderr == b"", child.stderr.decode()
        text = child.stdout.decode()
        if not text:
            return None
        body = json.loads(text)
        assert text == canonical(body) + "\n", "stdout must be exactly one canonical JSON line"
        return text if raw else body


def check_rows(w: "World", groups: list, replay_hash: str, *, state: str = "extraction", identity: str | None = None) -> None:
    """The stored ledger is exactly the union of every REGISTERED/EXISTING job of `groups` = [(descriptor, round id, jobs of an expected report)]: each row's
    input digest and request are recomputed from the descriptor and the replay (or live identity), the job is `queued`, and nothing ever ran."""
    ledger = w.jobs_ledger(state)
    rows = {row["job_id"]: row for row in ledger["jobs"]}
    wanted = {}
    for d, rid, jobs in groups:
        for job in jobs:
            if job["registration"] in {"registered", "existing"}:
                wanted[job["jobId"]] = (d, rid, job)
    assert set(rows) == set(wanted), (len(rows), len(wanted), sorted(set(rows) ^ set(wanted))[:3])
    for jid, (d, rid, job) in wanted.items():
        request = submit_of(d, jid, observation(rid, job))
        preimage = {"request": request, "replayFixtureHash": replay_hash} if identity is None else {"request": request, "liveBindingDigest": identity}
        row = rows[jid]
        assert row["input_digest"] == digest(preimage) and json.loads(row["request"]) == request and row["replay_hash"] == (identity or replay_hash), jid
        assert (row["state"], row["phase"], row["failure"], row["detail"], row["resume_mode"], row["fence"]) == ("queued", "extract", None, None, "resume", 0), row
    assert ledger["tables"] == {"jobs": len(wanted), **NO_JOBS}, ledger["tables"]


def replay_file(w: "World", name: str) -> tuple[Path, str]:
    """A header-only authored replay: registration freezes its hash and reads its header, never a record."""
    path = w.replay(name).write()
    return path, sha(path.read_bytes())


def snapshot_of(w: "World", rid: str, refs: list[dict], keys, revision: str = "snapshot-1") -> dict:
    """A snapshot with ONE event whose members are exactly these observations of the round, with real exactly-grounded mentions."""
    members = []
    for ref, key in zip(refs, keys):
        observed = observation(rid, ref)
        article = w.document(observed)
        members.append((observed, w.mention(article, "m-" + key, [w.evidence(article, text_of(key))])))
    return {"revision": revision, "events": [w.event("event-" + revision, members)]}


# ======================================================================== scenario 1: > 205 references, 3 pages ======
PAGE_SIZES = (77, 77, 76)                                        # 230 references on 3 pages (the ingestion result is read 100 at a time: three reads)
REFS, SKIPPED = sum(PAGE_SIZES), 11

HELD = {(0, 5): ("scope", SCOPE_MISSING), (1, 17): ("paywall", RESTRICTED), (2, 3): ("scope", SCOPE_MISSING), (2, 60): ("paywall", RESTRICTED)}
OWNERS = {(0, 20): "u1", (1, 40): "u2"}                          # the first supplier of a shared URL: an ordinary, kept document
AMBIGUOUS = {(1, 30): "u1", (2, 10): "u2"}                       # a second supplier on a URL the first one already owns
DUPLICATES = {(0, 40): (0, 2), (1, 3): (0, 7), (2, 50): (1, 60)}  # same supplier, URL and bytes as an earlier kept document, another candidate id
IN_SNAPSHOT = {(0, 50): "s1", (2, 30): "s2"}                     # the very documents the snapshot event is made of
SKIPS = ({position: ("held", code) for position, (_, code) in HELD.items()}
         | {position: ("ambiguous", AMBIGUOUS_CODE) for position in AMBIGUOUS}
         | {position: ("in_snapshot", None) for position in IN_SNAPSHOT}
         | {position: ("duplicate_in_round", ("kept", kept)) for position, kept in DUPLICATES.items()})


def big_pages(w: "World", seed_items: dict, seed_bodies: dict) -> tuple[list[list[dict]], dict]:
    """3 pages (77 + 77 + 76 candidates) with the authored layout above; every other candidate is its own ordinary document."""
    pages, bodies, placed = [], {}, {}
    for p, size in enumerate(PAGE_SIZES):
        items = []
        for o in range(size):
            position = (p, o)
            if position in HELD:
                key = f"held-{p}-{o}"
                bodies[key] = NO_ARTICLE if HELD[position][0] == "scope" else PAYWALL
                item = doc_item(w, key)
            elif position in DUPLICATES:
                item = {**placed[DUPLICATES[position]], "candidateId": f"dup-{p}-{o}"}
            elif position in IN_SNAPSHOT:
                key = IN_SNAPSHOT[position]
                bodies[key] = seed_bodies[key]
                item = seed_items[key]
            elif position in OWNERS or position in AMBIGUOUS:
                shared = OWNERS.get(position) or AMBIGUOUS[position]
                key = f"{'own' if position in OWNERS else 'amb'}-{p}-{o}"
                bodies[key] = page(text_of(key))
                item = doc_item(w, key, url=f"https://example.invalid/shared-{shared}")
            else:
                key = f"n{p}-{o}"
                bodies[key] = page(text_of(key))
                item = doc_item(w, key)
            placed[position] = item
            items.append(item)
        pages.append(items)
    return pages, bodies


def check_big_world(refs: list[dict], seed_refs: list[dict]) -> None:
    """The ingestion states the layout is supposed to produce, read from the actual ingestion output: nothing is planned over an unverified world."""
    index = {(r["page"], r["ordinal"]): r for r in refs}
    assert list(index) == [(p, o) for p, size in enumerate(PAGE_SIZES) for o in range(size)] and len(refs) == REFS == 230 and len(SKIPS) == SKIPPED
    assert {k: r["hold"] for k, r in index.items() if r["hold"]} == {k: code for k, (_, code) in HELD.items()}
    assert {k: r["ambiguity"] for k, r in index.items() if r["ambiguity"]} == {k: AMBIGUOUS_CODE for k in AMBIGUOUS}
    assert all(r["error"] is None and r["failure"] is None and ((r["documentVersion"] is None) == (k in HELD)) for k, r in index.items())
    seeds = {"s1": seed_refs[0], "s2": seed_refs[1]}
    for position, key in IN_SNAPSHOT.items():
        assert (index[position]["documentId"], index[position]["documentVersion"]) == (seeds[key]["documentId"], seeds[key]["documentVersion"])
    for position, original in DUPLICATES.items():
        assert (index[position]["documentId"], index[position]["documentVersion"], index[position]["rawVersion"]) == tuple(index[original][k] for k in ("documentId", "documentVersion", "rawVersion"))
    versions = Counter((r["documentId"], r["documentVersion"]) for k, r in index.items() if k not in HELD)
    assert sorted(count for count in versions.values() if count > 1) == [2] * len(DUPLICATES)      # each duplicate pair is one document version seen twice
    for position, shared in AMBIGUOUS.items():
        owner = next(o for o, u in OWNERS.items() if u == shared)
        assert index[position]["documentId"] != index[owner]["documentId"] and index[position]["documentVersion"] != index[owner]["documentVersion"]


def big(root: Path) -> list[str]:
    w = World(root / "big")
    seed_items = {key: doc_item(w, key) for key in ("s1", "s2")}
    seed_bodies = {key: page(text_of(key)) for key in seed_items}
    seed_rid, _ = w.new_round("09:05", list(seed_items.values()), seed_bodies, first=True)
    _, seed_refs = w.refs(seed_rid)
    snapshot = snapshot_of(w, seed_rid, seed_refs, ("s1", "s2"))
    pages, bodies = big_pages(w, seed_items, seed_bodies)
    rid, ticked = w.new_round("09:35", (), bodies, pages=pages)
    assert ticked["counts"]["discoveredCandidates"] == 230 and [p["complete"] for p in ticked["pages"]] == [True, True, True]
    first, refs = w.refs(rid)
    check_big_world(refs, seed_refs)
    assert first["completion"] == "nonzero-discovery" and first["provenance"] == "authored_control"

    replay, replay_hash = replay_file(w, "big")
    d = descriptor(rid, "enqueue-0935", snapshot=snapshot)
    ingestion = w.root / "ingestion"
    frozen = fingerprint(ingestion)
    started = time.monotonic()
    report = w.enqueue(d, replay=replay)
    elapsed = time.monotonic() - started
    want = expected_report("enqueue-0935", rid, first, refs, SKIPS)
    same(report, want, "the 230-reference plan")
    assert report["counts"] == {"refs": 230, "jobs": 219, "registered": 219, "existing": 0, "failed": 0, "notAttempted": 0, "skipped": 11}
    assert report["outcome"] == "complete" and report["error"] is None and len(report["jobs"]) == 219 and len({j["jobId"] for j in report["jobs"]}) == 219
    assert [(s["page"], s["ordinal"], s["code"]) for s in report["skipped"]] == [
        (0, 5, "held"), (0, 40, "duplicate_in_round"), (0, 50, "in_snapshot"), (1, 3, "duplicate_in_round"), (1, 17, "held"), (1, 30, "ambiguous"),
        (2, 3, "held"), (2, 10, "ambiguous"), (2, 30, "in_snapshot"), (2, 50, "duplicate_in_round"), (2, 60, "held")]
    assert fingerprint(ingestion) == frozen, "registration changed an ingestion byte, mode or mtime"
    check_rows(w, [(d, rid, report["jobs"])], replay_hash)
    sample = [report["jobs"][0], report["jobs"][99], report["jobs"][-1]]
    for job in sample:
        queued = w.run("inspect", w.job_selector(job["jobId"]))
        assert queued["state"] == "queued" and queued["calls"] == [] and queued["usage"]["replayCalls"] == 0 and queued["eventCandidates"] == [] and queued["resumeMode"] == "resume"
        assert queued["binding"]["adapter"]["version"] == REPLAY_ADAPTER and queued["binding"]["incoming"] and queued["delivery"]["status"] == "current"
    checks = [f"230 references on 3 pages (4 held, 2 ambiguous, 3 duplicate, 2 in_snapshot, authored layout verified through the actual ingestion output): the plan reports exactly "
              f"219 jobs and 11 skipped with literal codes/details, the duplicate details are the kept job ids, every job id is recomputed from the contract text ({elapsed:.0f}s)",
              "every stored row's input digest and request is recomputed from the descriptor and the replay hash, all jobs are queued, no stage/call/candidate row exists (a call would have ended the child with 76)",
              "the ingestion directory's bytes, modes and mtimes are unchanged by registration; sampled `inspect` shows queued, calls [], replayCalls 0"]

    # The same command again: only existing rows, nothing rewritten (updated_at and every column unchanged).
    held = w.jobs_ledger()
    again = w.enqueue(d, replay=replay)
    same(again, expected_report("enqueue-0935", rid, first, refs, SKIPS, "existing"), "the identical rerun")
    assert again["counts"]["registered"] == 0 and again["counts"]["existing"] == 219 and w.jobs_ledger() == held and fingerprint(ingestion) == frozen
    checks.append("the identical rerun reports 219 existing and 0 registered and rewrites no row (every column, created/updated times included)")

    # Any other descriptor or replay for the same ids is a conflict that writes nothing, even when the plan would filter or change.
    prompt_2 = Replay(w, "prompt-2", prompt=PROMPT_2).write()
    padded = json.loads(replay.read_bytes())
    padded["records"] = [{"stage": "extract", "requestDigest": "0" * 64, "response": {"mentions": []}}]
    padded_path = w.root / "padded.replay.json"
    padded_path.write_bytes(json_bytes(padded))
    renamed = json.loads(replay.read_bytes())
    renamed["analysisVersion"] = "authored-analysis-2"
    renamed_path = w.root / "renamed.replay.json"
    renamed_path.write_bytes(json_bytes(renamed))
    variants = [("catalogue", {**d, "catalogue": CATALOGUE_2}, replay), ("snapshot revision", {**d, "snapshot": {**snapshot, "revision": "snapshot-2"}}, replay),
                ("snapshot removed (the plan itself changes)", {**d, "snapshot": {"revision": "snapshot-1", "events": []}}, replay), ("topic", {**d, "topic": TOPIC}, replay),
                ("prompt (with the matching replay header)", {**d, "promptVersion": PROMPT_2}, prompt_2), ("replay bytes", d, padded_path), ("replay analysisVersion", d, renamed_path)]
    for name, changed, fixture in variants:
        refused(w.enqueue(changed, replay=fixture, expected=2), "job_input_conflict")
        assert w.jobs_ledger() == held, name
    assert fingerprint(ingestion) == frozen
    checks.append(f"{len(variants)} changed descriptors/replays for the same ids (catalogue, snapshot revision, snapshot removed, topic, prompt, replay bytes, replay analysisVersion): job_input_conflict, ledger unchanged; the descriptor is not in the id")
    return checks


# ======================================================================== scenario 2: identity, other ids, filtered conflicts ===

def identity(root: Path) -> list[str]:
    w = World(root / "identity")
    keys = "abcdef"
    rid1, _ = w.new_round("09:05", *docs(w, keys), first=True)
    keys2 = "abcg"
    rid2, _ = w.new_round("09:35", *docs(w, keys2))
    first1, refs1 = w.refs(rid1)
    first2, refs2 = w.refs(rid2)
    replay, replay_hash = replay_file(w, "identity")
    ingestion, extraction = w.root / "ingestion", w.root / "extraction"
    frozen = fingerprint(ingestion)
    d1 = descriptor(rid1, "E1")
    r1 = w.enqueue(d1, replay=replay)
    want1 = expected_report("E1", rid1, first1, refs1, {})
    same(r1, want1, "first enqueue")
    check_rows(w, [(d1, rid1, r1["jobs"])], replay_hash)
    held = w.jobs_ledger()
    same(w.enqueue(d1, replay=replay), expected_report("E1", rid1, first1, refs1, {}, "existing"), "rerun")
    assert w.jobs_ledger() == held
    checks = ["6 documents: registered once, an identical rerun is 6 existing with every row byte-equal"]

    # A new enqueueId is a new analysis of the same observations: new ids, the old jobs untouched, the old label still works.
    d_other = descriptor(rid1, "E2", catalogue=CATALOGUE_2)
    r_other = w.enqueue(d_other, replay=replay)
    same(r_other, expected_report("E2", rid1, first1, refs1, {}), "new enqueue id")
    assert not {j["jobId"] for j in r1["jobs"]} & {j["jobId"] for j in r_other["jobs"]}
    check_rows(w, [(d1, rid1, r1["jobs"]), (d_other, rid1, r_other["jobs"])], replay_hash)
    assert {row["job_id"]: row for row in w.jobs_ledger()["jobs"] if row["job_id"] in {j["jobId"] for j in r1["jobs"]}} == {row["job_id"]: row for row in held["jobs"]}
    same(w.enqueue(d1, replay=replay), expected_report("E1", rid1, first1, refs1, {}, "existing"), "old label after the new one")
    checks.append("a new enqueueId with another catalogue: 6 new ids, the E1 rows untouched, E1 itself still 6 existing")

    # The same label on another round is independent: no cross-round dedup, even for an identical document version.
    r2 = w.enqueue(d1 | {"roundId": rid2}, replay=replay)
    same(r2, expected_report("E1", rid2, first2, refs2, {}), "same label, other round")
    by_key = {key: (a, b) for key, a, b in zip(keys2, refs1, refs2)}
    assert all(r1ref["documentVersion"] == r2ref["documentVersion"] for key, (r1ref, r2ref) in by_key.items() if key in "abc")
    ids1 = {(j["documentId"], j["documentVersion"]): j["jobId"] for j in r1["jobs"]}
    shared = [(j["documentId"], j["documentVersion"]) for j in r2["jobs"] if (j["documentId"], j["documentVersion"]) in ids1]
    assert len(shared) == 3 and all(ids1[k] != next(j["jobId"] for j in r2["jobs"] if (j["documentId"], j["documentVersion"]) == k) for k in shared)
    assert all(j["registration"] == "registered" for j in r2["jobs"]) and len(w.jobs_ledger()["jobs"]) == 6 + 6 + 4
    checks.append("the same enqueueId on another round, with 3 documents of an identical documentVersion: 4 new jobs, no existing, different ids (no cross-round dedup or paid-call reuse)")

    # Filtered ids are still checked against the ledger: a snapshot that filters EVERY previous reference cannot hide the old binding.
    everything = snapshot_of(w, rid1, refs1, keys)
    before = fingerprint(extraction)
    refused(w.enqueue(descriptor(rid1, "E1", snapshot=everything), replay=replay, expected=2), "job_input_conflict")
    assert fingerprint(extraction) == before, "an all-filtered refusal must open the ledger read-only (bytes, modes, mtimes unchanged)"
    partial = snapshot_of(w, rid1, refs1[:3], keys[:3])
    ledger = w.jobs_ledger()
    refused(w.enqueue(descriptor(rid1, "E1", snapshot=partial), replay=replay, expected=2), "job_input_conflict")
    assert w.jobs_ledger() == ledger
    before = fingerprint(extraction)       # a writer open (the refusal above) creates and removes its WAL files: the read-only checks below start from here
    checks.append("a changed snapshot that filters ALL previous references (read-only open, extraction bytes/mtimes unchanged) or SOME of them: job_input_conflict, nothing written")

    # All filtered under a NEW label: a plain report, no write.
    report = w.enqueue(descriptor(rid1, "E3", snapshot=everything), replay=replay)
    same(report, expected_report("E3", rid1, first1, refs1, {(0, i): ("in_snapshot", None) for i in range(6)}), "all filtered")
    assert report["counts"] == {"refs": 6, "jobs": 0, "registered": 0, "existing": 0, "failed": 0, "notAttempted": 0, "skipped": 6} and fingerprint(extraction) == before
    checks.append("every reference in_snapshot under a new label: exit 0 with 6 skipped and 0 jobs, the ledger opened read-only and left byte-identical")

    # A busy writer refuses both the read-only and the writer path without waiting or writing.
    lock = os.open(extraction / "extraction.lock", os.O_RDWR)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        refused(w.enqueue(descriptor(rid1, "E3", snapshot=everything), replay=replay, expected=2), "extraction_busy")
        refused(w.enqueue(d1, replay=replay, expected=2), "extraction_busy")
    finally:
        os.close(lock)
    assert fingerprint(extraction) == before
    checks.append("an exclusive holder of the extraction lock: the all-filtered (read-only) and the planned (writer) enqueue are both extraction_busy, nothing changes")

    # The report is withheld as soon as the CURRENT registry no longer authorizes the saved round, even when every job already exists.
    with edited(w, lambda r: grant(r).update(enabled=False)):
        out = w.enqueue(d1, replay=replay, expected=2, raw=True)
        assert out == canonical({"schemaVersion": SCHEMA, "error": {"code": "source_unauthorized"}}) + "\n" and "s2r-" not in out and rid1 not in out
    same(w.enqueue(d1, replay=replay), expected_report("E1", rid1, first1, refs1, {}, "existing"), "after the grant is back")
    assert fingerprint(ingestion) == frozen
    checks.append("a revoked grant after full registration: error body only (no job id, no round id); restored, the same command reports 6 existing")
    return checks


# ======================================================================== scenario 3: authority gates, zero and all-held rounds ===

def gates(root: Path) -> list[str]:
    w = World(root / "gates")
    zero_rid, _ = w.new_round("09:05", (), None, first=True)
    held_items = [doc_item(w, f"h{i}") for i in (1, 2, 3)]
    held_bodies = {f"h{i}": f"<html><body><div>본문 없음 {i}</div></body></html>".encode() for i in (1, 2, 3)}
    held_rid, _ = w.new_round("09:35", held_items, held_bodies)
    prepared_rid, _ = w.new_round("10:05", *docs(w, ("p1", "p2")))
    zero_first, zero_refs = w.refs(zero_rid)
    held_first, held_refs = w.refs(held_rid)
    prepared_first, prepared_refs = w.refs(prepared_rid)
    assert (zero_first["completion"], held_first["completion"], prepared_first["completion"]) == ("source-zero", "nonzero-discovery", "nonzero-discovery")
    assert zero_refs == [] and [r["hold"] for r in held_refs] == [SCOPE_MISSING] * 3 and all(r["documentVersion"] is None for r in held_refs)
    replay, _ = replay_file(w, "gates")
    own = snapshot_of(w, prepared_rid, prepared_refs, ("p1", "p2"))
    extraction, ingestion = w.root / "extraction", w.root / "ingestion"
    frozen = fingerprint(ingestion)
    rounds = {"zero": zero_rid, "held": held_rid, "prepared": prepared_rid}
    held_skips = {(0, i): ("held", SCOPE_MISSING) for i in range(3)}
    prepared_filtered = {(0, 0): ("in_snapshot", None), (0, 1): ("in_snapshot", None)}

    def ask(name: str, *, expected: int = 0, fixture: Path | None = replay, **changes):
        return w.enqueue(descriptor(rounds[name], "E-" + name, **changes), replay=fixture, expected=expected)

    with edited(w, lambda r: grant(r).update(enabled=False)):
        for name in rounds:
            refused(ask(name, expected=2), "source_unauthorized")
        refused(ask("zero", expected=2, fixture=None), "replay_fixture_required")    # the pure input check needs no registry
    with edited(w, lambda r: grant(r).update(allowedOperations=["read", "quote-display"])):
        for name in ("zero", "held"):
            refused(ask(name, expected=2), "source_unauthorized")                      # `store` is needed even with nothing to register
    assert not extraction.exists()
    checks = ["a disabled grant, or one without `store`: a zero-reference and an all-held round get the bare source_unauthorized body (no round or skip metadata) and no extraction directory exists"]

    with edited(w, lambda r: grant(r).update(allowedOperations=["read", "store"])):
        same(ask("zero"), expected_report("E-zero", zero_rid, zero_first, zero_refs, {}), "zero without quote-display")
        same(ask("held"), expected_report("E-held", held_rid, held_first, held_refs, held_skips), "all-held without quote-display")
        refused(ask("prepared", expected=2), "source_unauthorized")
    assert not extraction.exists()
    checks.append("read+store without quote-display: zero and all-held rounds report normally (no directory), a round with a prepared document is source_unauthorized (it needs quote-display)")

    zero = ask("zero")
    same(zero, expected_report("E-zero", zero_rid, zero_first, zero_refs, {}), "zero")
    assert zero["jobs"] == [] and zero["skipped"] == [] and zero["round"]["completion"] == "source-zero" and zero["counts"] == {
        "refs": 0, "jobs": 0, "registered": 0, "existing": 0, "failed": 0, "notAttempted": 0, "skipped": 0}
    same(ask("held"), expected_report("E-held", held_rid, held_first, held_refs, held_skips), "all-held")
    filtered = ask("prepared", snapshot=own)
    same(filtered, expected_report("E-prepared", prepared_rid, prepared_first, prepared_refs, prepared_filtered), "all-filtered, ledger missing")
    assert not extraction.exists() and fingerprint(ingestion) == frozen
    checks.append("authorized: a source-zero round, an all-held round (3 held) and a prepared round whose every document is in the snapshot all exit 0 with exact skips, 0 jobs, and create no extraction directory")

    # Only a state that is genuinely absent (no directory, or an empty one) means "no prior jobs". Anything half there or foreign fails closed and is left alone.
    empty_state = w.root / "extraction-empty"
    empty_state.mkdir()
    same(w.enqueue(descriptor(prepared_rid, "E-prepared", snapshot=own), replay=replay, state="extraction-empty"),
         expected_report("E-prepared", prepared_rid, prepared_first, prepared_refs, prepared_filtered), "an empty state directory is no state")
    assert list(empty_state.iterdir()) == []
    for name, files in (("extraction-lock-only", {"extraction.lock": b""}), ("extraction-db-only", {"extraction.sqlite3": b""}), ("extraction-foreign", {"notes.txt": b"foreign"})):
        folder = w.root / name
        folder.mkdir()
        for filename, data in files.items():
            (folder / filename).write_bytes(data)
        untouched = fingerprint(folder)
        refused(w.enqueue(descriptor(prepared_rid, "E-prepared", snapshot=own), replay=replay, state=name, expected=2), "extraction_state_missing")
        assert fingerprint(folder) == untouched
    checks.append("an all-filtered round over an empty extraction directory reports normally and creates nothing; a directory holding only the lock, only the database or only a foreign file is extraction_state_missing "
                  "(never 'no prior jobs'), and none of them is modified")

    with edited(w, lambda r: r["sources"][0]["scopes"][0].update(selection="selection changed after the round")):
        for name in rounds:
            refused(ask(name, expected=2), "scope_configuration_conflict")
    with edited(w, lambda r: grant(r).update(expiresAt=at("12:00:00"))):
        for name in rounds:
            refused(ask(name, expected=2), "source_unauthorized")              # judged by the REAL clock (this expiry is long past)
    unknown = "slot-" + "0" * 64
    for state in (False, True):
        with edited(w, lambda r: grant(r).update(enabled=state)):
            refused(w.enqueue(descriptor(unknown, "E-unknown"), replay=replay, expected=2), "round_not_found")
    refused(w.enqueue(descriptor(prepared_rid, "E-other-source", source="other-source"), replay=replay, expected=2), "round_not_found")
    assert not extraction.exists()
    checks.append("a changed scope configuration and a grant expired by the REAL clock refuse every round kind; an unknown round or another source is round_not_found, before authorization (revoked grant or not)")

    for name, fixture, code in (("no replay file", None, "replay_fixture_required"),
                                ("replay that is not JSON", w.root / "garbage.replay.json", "replay_fixture_invalid"),
                                ("replay with a wrong format", w.root / "format.replay.json", "replay_fixture_invalid"),
                                ("replay for another prompt", Replay(w, "other-prompt", prompt=PROMPT_2).write(), "replay_prompt_version_conflict"),
                                ("replay recorded for actual sources", Replay(w, "actual-kind", synthetic=False).write(), "replay_provenance_conflict")):
        if name == "replay that is not JSON":
            fixture.write_bytes(b"{not json")
        if name == "replay with a wrong format":
            fixture.write_bytes(json_bytes({"format": "something-else", "records": []}))
        refused(ask("zero", expected=2, fixture=fixture), code)
    base = {k: v for k, v in descriptor(zero_rid, "E-zero").items()}
    for name, mutated in (("enqueueId with a space", {**base, "enqueueId": "bad id"}), ("enqueueId of 121 characters", {**base, "enqueueId": "e" * 121}),
                          ("unknown key", {**base, "unexpected": True}), ("missing topic key", {k: v for k, v in base.items() if k != "topic"}),
                          ("missing catalogue key", {k: v for k, v in base.items() if k != "catalogue"}), ("wrong schemaVersion", {**base, "schemaVersion": "zoop-extraction-s2-1"})):
        refused(w.enqueue(mutated, replay=replay, expected=2), "input_or_configuration_invalid")
    refused(w.enqueue(base, replay=replay, topic=replay, expected=2), "fixture_not_allowed")
    refused(w.enqueue(base, replay=replay, flags=("--initial-only",), expected=2), "initial_only_not_allowed")
    live_zero = descriptor(zero_rid, "E-live-zero", live=True, prompt=LIVE_PROMPT)
    refused(w.enqueue(live_zero, expected=2), "live_not_enabled")
    refused(w.enqueue(live_zero, env={GATE: "1"}, expected=2), "live_budget_config_invalid")
    refused(w.enqueue(live_zero, replay=replay, expected=2), "fixture_not_allowed")
    assert not extraction.exists() and not (w.root / "budget").exists() and fingerprint(ingestion) == frozen
    checks.append("even for a ZERO-reference round the pure input is refused first: no/garbage/foreign replay (required, invalid, wrong prompt, wrong provenance), live without the gate or budget directory, "
                  "a live job given a replay, --topic-replay, --initial-only, and 6 malformed descriptors; none creates a directory")
    return checks


# ======================================================================== scenario 4: unfinished rounds, locks, hot WAL =======

def refusals(root: Path) -> list[str]:
    w = World(root / "refusals")
    done_rid, _ = w.new_round("09:05", *docs(w, ("ok1",)), first=True)
    replay, _ = replay_file(w, "refusals")
    extraction, ingestion = w.root / "extraction", w.root / "ingestion"

    failed_when = slot("09:35")
    failed = due(w, w.tick(at("09:35:30"), manifest=w.covering("m-0935", failed_when, status="failed", covered=False), state="ingestion", expected=3),
                 "started", at("09:35:30"), failed_when, False, "incomplete", failure="discovery_page_failed")
    refused(w.enqueue(descriptor(failed["roundId"], "E-failed"), replay=replay, expected=2), "round_not_complete")
    assert not extraction.exists()

    # A reader may not look while the ingestion writer holds its lock (one tick paused inside its first page read).
    busy_manifest = w.covering("m-1005", slot("10:05"), *docs(w, ("ok2",)))
    ready, release = w.root / "holder-ready", w.root / "holder-release"
    holder = w.launch("tick", w.tick_request(at("10:05:30")), state="ingestion", manifest=busy_manifest, hooks=(pause_hook(ready, release),))
    try:
        deadline = time.monotonic() + 60
        while not ready.exists():
            assert holder.poll() is None and time.monotonic() < deadline, "the holder tick never reached its page while holding the lock"
            time.sleep(0.02)
        refused(w.enqueue(descriptor(done_rid, "E-busy"), replay=replay, expected=2), "ingestion_busy")
        assert holder.poll() is None
        release.write_bytes(b"")
        started = w.finish(holder, 0)
        assert started["tick"]["action"] == "started" and started["round"]["state"] == "complete"
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.communicate()
    assert not extraction.exists()

    # A killed ingestion writer leaves committed rows only in its WAL: a reader refuses; once a writer recovered it, the round is still `running`.
    crash_manifest = w.covering("m-1035", slot("10:35"), pages=[[doc_item(w, "ok3")], [doc_item(w, "ok4")]], bodies={"ok3": page(text_of("ok3")), "ok4": page(text_of("ok4"))})
    assert w.tick(at("10:35:30"), manifest=crash_manifest, state="ingestion", hooks=(HOOKS["stop-after-first-page"],), expected=75) is None
    running_rid = round_id(SCOPE, slot("10:35"))
    wal = ingestion / "ingestion.sqlite3-wal"
    assert wal.exists() and wal.stat().st_size > 0, "the killed tick must leave a non-empty WAL"
    for rid in (done_rid, running_rid):
        refused(w.enqueue(descriptor(rid, "E-wal"), replay=replay, expected=2), "ingestion_recovery_required")
    assert w.command("inspect", w.selector(running_rid), state="ingestion")["state"] == "running"
    assert not wal.exists() or wal.stat().st_size == 0
    refused(w.enqueue(descriptor(running_rid, "E-running"), replay=replay, expected=2), "round_not_complete")
    assert not extraction.exists()
    return ["an incomplete (failed page) and a still-running round: round_not_complete, no extraction directory; the registered round stays untouched",
            "an ingestion writer holding its lock (tick paused inside its page read): ingestion_busy without waiting; released, that tick completes normally",
            "a killed ingestion writer's non-empty WAL: ingestion_recovery_required for any round; after a writer recovered it the unfinished round is round_not_complete"]


# ======================================================================== scenario 5: crash, partial registration, rights ======

def crash(root: Path) -> list[str]:
    w = World(root / "crash")
    keys = [f"k{i}" for i in range(1, 9)]
    rid, _ = w.new_round("09:05", *docs(w, keys), first=True)
    first, refs = w.refs(rid)
    replay, replay_hash = replay_file(w, "crash")
    ingestion = w.root / "ingestion"
    frozen = fingerprint(ingestion)
    d = descriptor(rid, "E-crash")

    def plan(registration, **kwargs):
        return expected_report("E-crash", rid, first, refs, {}, registration, **kwargs)

    ids = [job["jobId"] for job in plan("registered")["jobs"]]
    kill = ledger_hook(after=3, then="os._exit(75)")
    assert w.enqueue(d, replay=replay, hooks=(kill,), expected=75) is None
    wal = w.root / "extraction" / "extraction.sqlite3-wal"
    assert wal.exists() and wal.stat().st_size > 0, "the killed writer must leave a non-empty WAL"
    after_kill = w.jobs_ledger()
    assert [row["job_id"] for row in after_kill["jobs"]] == sorted(ids[:3]) and after_kill["tables"]["jobs"] == 3
    everything = snapshot_of(w, rid, refs, keys)
    refused(w.enqueue(descriptor(rid, "E-crash", snapshot=everything), replay=replay, expected=2), "extraction_recovery_required")
    assert w.jobs_ledger() == after_kill
    again = w.enqueue(d, replay=replay)
    same(again, plan(lambda index: "existing" if index < 3 else "registered"), "rerun after the kill")
    assert again["counts"] == {"refs": 8, "jobs": 8, "registered": 5, "existing": 3, "failed": 0, "notAttempted": 0, "skipped": 0}
    kept = {row["job_id"]: row for row in after_kill["jobs"]}
    assert all(row == kept[row["job_id"]] for row in w.jobs_ledger()["jobs"] if row["job_id"] in kept)
    check_rows(w, [(d, rid, again["jobs"])], replay_hash)
    checks = ["killed after the 3rd freeze commit: exactly the first 3 jobs of the plan order are durable (found in the non-empty WAL); a read-only all-filtered attempt is extraction_recovery_required; "
              "the identical rerun reports 3 existing + 5 registered and rewrites none of the first 3 rows"]

    # The registry changes in the middle of the batch: the report is withheld, only the honest `partialRegistration` flag remains.
    original = w.registry_path.read_bytes()
    revoked = copy.deepcopy(w.registry)
    grant(revoked)["enabled"] = False
    edit = f"open({str(w.registry_path)!r}, 'wb').write({json_bytes(revoked)!r})"
    out = w.enqueue(d, replay=replay, state="extraction-revoked", hooks=(ledger_hook(after=3, then=edit),), expected=2, raw=True)
    assert out == canonical({"schemaVersion": SCHEMA, "error": {"code": "registry_changed", "partialRegistration": True}}) + "\n"
    assert "s2r-" not in out and rid not in out and "registered" not in out
    prefix = w.jobs_ledger("extraction-revoked")
    assert [row["job_id"] for row in prefix["jobs"]] == sorted(ids[:3])
    w.save_registry()
    assert w.registry_path.read_bytes() == original
    healed = w.enqueue(d, replay=replay, state="extraction-revoked")
    same(healed, plan(lambda index: "existing" if index < 3 else "registered"), "rerun after the registry is restored")
    check_rows(w, [(d, rid, healed["jobs"])], replay_hash, state="extraction-revoked")
    checks.append("the registry edited after the 3rd commit: exit 2 with ONLY {error:{code:registry_changed, partialRegistration:true}} (no job or round id in the output), the 3 committed jobs stay; restored, the rerun is 3 existing + 5 registered")

    # The registry changes only AFTER the last freeze: every job is durable and the report is still withheld. A denial with every job already stored commits
    # nothing in that run, so its flag is false although the rows exist.
    final = w.enqueue(d, replay=replay, state="extraction-final", hooks=(ledger_hook(after=8, then=edit),), expected=2, raw=True)
    assert final == canonical({"schemaVersion": SCHEMA, "error": {"code": "registry_changed", "partialRegistration": True}}) + "\n" and "s2r-" not in final and rid not in final
    assert [row["job_id"] for row in w.jobs_ledger("extraction-final")["jobs"]] == sorted(ids)
    w.save_registry()
    stored = w.jobs_ledger("extraction-final")
    stale = w.enqueue(d, replay=replay, state="extraction-final", hooks=(open_hook(edit),), expected=2, raw=True)
    assert stale == canonical({"schemaVersion": SCHEMA, "error": {"code": "registry_changed", "partialRegistration": False}}) + "\n" and "s2r-" not in stale
    assert w.jobs_ledger("extraction-final") == stored
    w.save_registry()
    same(w.enqueue(d, replay=replay, state="extraction-final"), plan("existing"), "all existing after both denials")
    check_rows(w, [(d, rid, plan("existing")["jobs"])], replay_hash, state="extraction-final")
    checks.append("the registry edited only after the LAST (8th) commit: error body only with partialRegistration true and all 8 jobs durable; the same edit over 8 existing jobs commits nothing, so partialRegistration is false and no row changes; restored, the rerun is 8 existing")

    # A close that fails after every job committed: the prefix is reported with its real counts and the batch error; the final authority recheck still decides first.
    shut = "raise sqlite3.OperationalError('injected close failure')"
    closed = w.enqueue(d, replay=replay, state="extraction-close", hooks=(close_hook(shut),), expected=2)
    same(closed, plan("registered", outcome="incomplete", error={"code": "persistence_failed"}), "a failing close after the last commit")
    assert closed["counts"] == {"refs": 8, "jobs": 8, "registered": 8, "existing": 0, "failed": 0, "notAttempted": 0, "skipped": 0}
    check_rows(w, [(d, rid, closed["jobs"])], replay_hash, state="extraction-close")
    same(w.enqueue(d, replay=replay, state="extraction-close"), plan("existing"), "rerun after a failing close")
    gone = w.enqueue(d, replay=replay, state="extraction-close-rights", hooks=(ledger_hook(after=8, then=edit), close_hook(shut)), expected=2, raw=True)
    assert gone == canonical({"schemaVersion": SCHEMA, "error": {"code": "registry_changed", "partialRegistration": True}}) + "\n" and "s2r-" not in gone
    assert [row["job_id"] for row in w.jobs_ledger("extraction-close-rights")["jobs"]] == sorted(ids)
    w.save_registry()
    same(w.enqueue(d, replay=replay, state="extraction-close-rights"), plan("existing"), "rerun after a failing close and a registry change")
    checks.append("the ledger close failing AFTER all 8 commits: exit 2 with the full report (8 registered, error persistence_failed, no job hidden) and a clean rerun of 8 existing; with the registry also changed after the last commit "
                  "the final authority recheck wins (error body only, partialRegistration true, the 8 jobs durable)")

    # The same edit before anything was registered is an ordinary refusal: no flag, no job.
    out = w.enqueue(d, replay=replay, state="extraction-edited", hooks=(open_hook(edit),), expected=2)
    refused(out, "registry_changed")
    ledger = w.jobs_ledger("extraction-edited")
    assert ledger is None or ledger["jobs"] == []
    w.save_registry()
    same(w.enqueue(d, replay=replay, state="extraction-edited"), plan("registered"), "rerun after a preflight refusal")
    checks.append("the registry edited after the round was authorized but before any freeze: plain registry_changed (no partialRegistration key), zero jobs; the rerun registers all 8")

    # A freeze that fails for another reason: full, honest report; nothing is rolled back and nothing is retried automatically.
    fail = ledger_hook(before=4, fail="raise _x.ExtractionFailure('document_binding_changed')")
    partial = w.enqueue(d, replay=replay, state="extraction-partial", hooks=(fail,), expected=2)
    same(partial, plan(lambda index: "registered" if index < 3 else "failed" if index == 3 else "not-attempted", outcome="incomplete", error={"code": "document_binding_changed"}), "partial report")
    assert partial["counts"] == {"refs": 8, "jobs": 8, "registered": 3, "existing": 0, "failed": 1, "notAttempted": 4, "skipped": 0}
    assert [row["job_id"] for row in w.jobs_ledger("extraction-partial")["jobs"]] == sorted(ids[:3])
    same(w.enqueue(d, replay=replay, state="extraction-partial"), plan(lambda index: "existing" if index < 3 else "registered"), "rerun after a partial failure")
    checks.append("the 4th freeze fails (document_binding_changed): exit 2 with the full report (3 registered, 1 failed, 4 not-attempted), the durable prefix is not rolled back and no job after the failure is tried; the rerun registers exactly the rest")

    # A first run that fails before any row exists binds nothing: another configuration may then register under the same label.
    first_fail = ledger_hook(before=1, fail="raise _x.ExtractionFailure('document_binding_changed')")
    none = w.enqueue(d, replay=replay, state="extraction-first", hooks=(first_fail,), expected=2)
    same(none, plan(lambda index: "failed" if index == 0 else "not-attempted", outcome="incomplete", error={"code": "document_binding_changed"}), "first freeze fails")
    empty = w.jobs_ledger("extraction-first")
    assert empty is not None and empty["jobs"] == [] and empty["tables"]["jobs"] == 0
    d_other = descriptor(rid, "E-crash", catalogue=CATALOGUE_2)
    fresh = w.enqueue(d_other, replay=replay, state="extraction-first")
    same(fresh, expected_report("E-crash", rid, first, refs, {}), "another configuration after a first failure")
    check_rows(w, [(d_other, rid, fresh["jobs"])], replay_hash, state="extraction-first")
    assert fingerprint(ingestion) == frozen
    checks.append("a first run whose first freeze fails leaves only an empty initialised ledger and binds nothing: the same label with another catalogue then registers all 8; ingestion bytes unchanged")
    return checks


# ======================================================================== scenario 6: a filtered id that exists, a legacy id =====

def history(root: Path) -> list[str]:
    w = World(root / "history")
    items = [doc_item(w, "a"), doc_item(w, "c1"), doc_item(w, "c2", url="https://example.invalid/c1")]
    bodies = {key: page(text_of(key)) for key in ("a", "c1", "c2")}
    rid, _ = w.new_round("09:05", items, bodies, first=True)
    first, refs = w.refs(rid)
    assert [r["ambiguity"] for r in refs] == [None, None, AMBIGUOUS_CODE]
    replay, replay_hash = replay_file(w, "history")
    d = descriptor(rid, "E-hist")
    skips = {(0, 2): ("ambiguous", AMBIGUOUS_CODE)}

    # `enqueue` never registers a filtered id; a hand-made `submit` of exactly that id and input is the one way it can exist, and it is refused.
    hand = submit_of(d, job_id("E-hist", observation(rid, refs[2])), observation(rid, refs[2]))
    queued = w.run("submit", hand, replay=replay, forbid_execution=True, state="extraction-hand")
    assert queued["state"] == "queued" and queued["calls"] == []
    ledger = w.jobs_ledger("extraction-hand")
    refused(w.enqueue(d, replay=replay, state="extraction-hand", expected=2), "enqueue_plan_conflict")
    assert w.jobs_ledger("extraction-hand") == ledger and len(ledger["jobs"]) == 1
    assert w.run("inspect", w.job_selector(hand["jobId"]), state="extraction-hand") == queued
    checks = ["a hand-made `submit` of the id of an AMBIGUOUS (filtered) observation with the same input exists as an ordinary queued job; the round enqueue refuses it as enqueue_plan_conflict and writes nothing"]

    # A stored pre-cutover (legacy) binding at a PLANNED id refuses the whole batch before any job is registered.
    from zoop_ai_pipeline.extraction import Store
    state = w.root / "extraction-legacy"
    Store(state, w.root / "ingestion").close()
    planned = job_id("E-hist", observation(rid, refs[0]))
    legacy_binding = {"adapter": {"version": "zoop-extraction-poc-adapter-1", "candidate": "zoop-event-candidate-1", "fingerprint": "f" * 64},
                      "replay": {"format": "investmate-replay-v2", "synthetic": True, "promptVersion": PROMPT, "analysisVersion": "authored-analysis-1", "fixtureHash": replay_hash}}
    db = sqlite3.connect(state / "extraction.sqlite3")
    try:
        db.execute("INSERT INTO jobs(job_id,input_digest,request,binding,replay_hash,state,phase,failure,detail,resume_mode,fence,created_at,updated_at) VALUES(?,?,?,?,?,'ready','complete',NULL,NULL,'none',0,?,?)",
                   (planned, "0" * 64, canonical(submit_of(d, planned, observation(rid, refs[0]))), canonical(legacy_binding), replay_hash, "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        db.close()
    legacy = w.jobs_ledger("extraction-legacy")
    refused(w.enqueue(d, replay=replay, state="extraction-legacy", expected=2), "analysis_contract_changed")
    assert w.jobs_ledger("extraction-legacy") == legacy and [row["job_id"] for row in legacy["jobs"]] == [planned]
    first_run = w.enqueue(d, replay=replay)
    same(first_run, expected_report("E-hist", rid, first, refs, skips), "plan with an ambiguous skip")
    check_rows(w, [(d, rid, first_run["jobs"])], replay_hash)
    checks.append("an explicitly planted legacy-adapter row at a planned id: analysis_contract_changed, the legacy row is the only row (the other planned id is not registered); in a clean ledger the same descriptor plans 2 jobs and skips the ambiguous one")
    return checks


# ======================================================================== scenario 7: live registration ======================

def live(root: Path) -> list[str]:
    w = World(root / "live")
    keys = ("l1", "l2", "l3")
    rid, _ = w.new_round("09:05", *docs(w, keys), first=True)
    first, refs = w.refs(rid)
    budget = w.root / "budget-never-created"
    env = {k: v for k, v in simulator_env("http://127.0.0.1:9/v1", budget).items() if k not in FAKE_KEYS and k not in ("ZOOP_AI_PIPELINE_LIVE_MAX_USD", "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS")}
    assert env[GATE] == "1" and env[BUDGET_DIR] == str(budget) and not set(FAKE_KEYS) & set(env), "the live child gets the gate and the model configuration only: no key, no ceiling"
    ingestion, extraction = w.root / "ingestion", w.root / "extraction"
    frozen = fingerprint(ingestion)
    d = descriptor(rid, "E-live", live=True, prompt=LIVE_PROMPT)
    report = w.enqueue(d, env=env)
    same(report, expected_report("E-live", rid, first, refs, {}), "live registration")
    queued = [w.run("inspect", w.job_selector(job["jobId"])) for job in report["jobs"]]
    identities = {job["binding"]["live"]["bindingDigest"] for job in queued}
    assert len(identities) == 1 and all(len(i) == 64 for i in identities)
    runtime = identities.pop()
    for job in queued:
        assert job["state"] == "queued" and job["calls"] == [] and job["usage"]["executionMode"] == "live" and job["usage"]["providerCalls"] == 0 and "replay" not in job["binding"]
        assert job["binding"]["adapter"]["version"] == LIVE_ADAPTER and job["provenance"] == {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}
    check_rows(w, [(d, rid, report["jobs"])], "", identity=runtime)
    assert not budget.exists() and fingerprint(ingestion) == frozen and {p.name for p in extraction.iterdir()} <= {"extraction.lock", "extraction.sqlite3", "extraction.sqlite3-shm", "extraction.sqlite3-wal"}
    checks = ["live enqueue with only the gate and the model/budget-directory configuration (no key, no ceiling) under the socket audit hook: 3 queued jobs bound to one secret-free runtime identity, "
              "calls [], providerCalls 0, the budget directory never created, input digests recomputed from the runtime identity"]

    held = w.jobs_ledger()
    same(w.enqueue(d, env=env), expected_report("E-live", rid, first, refs, {}, "existing"), "live rerun")
    refused(w.enqueue(d, env={**env, "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT": "low"}, expected=2), "job_input_conflict")
    refused(w.enqueue(descriptor(rid, "E-live", live=True, prompt=LIVE_PROMPT, source_kind="actual"), env=env, expected=2), "job_input_conflict")
    refused(w.enqueue(d, env={k: v for k, v in env.items() if k != GATE}, expected=2), "live_not_enabled")
    refused(w.enqueue(d, env=env, replay=w.replay("unused").write(), expected=2), "fixture_not_allowed")
    refused(w.enqueue(descriptor(rid, "E-replay-label"), env=env, expected=2), "replay_fixture_required")
    assert w.jobs_ledger() == held and not budget.exists()
    checks.append("live rerun: 3 existing; another runtime configuration or sourceKind is job_input_conflict, no gate is live_not_enabled, a replay given to a live job is fixture_not_allowed, a replay descriptor without a replay is replay_fixture_required; nothing written")
    return checks


# ======================================================================== scenario 8: explicit resume, then the next tick =====

def resume(root: Path) -> list[str]:
    w = World(root / "resume")
    keys = ("x1", "x2", "x3", "x4")
    rid, _ = w.new_round("09:05", *docs(w, keys), first=True)
    first, refs = w.refs(rid)
    authored = w.replay("resume")
    for ref, key in zip(refs, keys):
        article = w.document(observation(rid, ref))
        authored.extract(article, [w.mention(article, "m-" + key, [w.evidence(article, text_of(key))])])
    replay = authored.write()
    replay_hash = sha(replay.read_bytes())
    d = descriptor(rid, "E-resume")
    ingestion = w.root / "ingestion"
    frozen = fingerprint(ingestion)
    report = w.enqueue(d, replay=replay)
    same(report, expected_report("E-resume", rid, first, refs, {}), "registration with a recorded replay")
    check_rows(w, [(d, rid, report["jobs"])], replay_hash)
    assert fingerprint(ingestion) == frozen
    jobs = report["jobs"]

    # Only the explicit operator commands change a registered job: two are executed, one is cancelled while queued, one is stopped by a rights change.
    for job, key in list(zip(jobs, keys))[:2]:
        done = w.run("resume", w.job_selector(job["jobId"]), replay=replay)
        candidate = done["eventCandidates"][0]
        assert done["state"] == "ready" and done["usage"]["replayCalls"] == 1 and done["usage"]["paidModelCalls"] == 0 and len(done["calls"]) == 1 and len(done["eventCandidates"]) == 1
        assert candidate["approved"] is False and candidate["disposition"]["status"] == "new-event-candidate" and candidate["citations"][0]["quote"] == text_of(key)
        assert candidate["document"]["documentId"] == job["documentId"]
        assert w.run("inspect", w.job_selector(job["jobId"])) == done
    cancelled = w.run("cancel", w.job_selector(jobs[2]["jobId"]), expected=2)
    assert cancelled["state"] == "cancelled" and cancelled["calls"] == [] and cancelled["delivery"] == {"status": "withheld", "code": "job_cancelled"}
    with edited(w, lambda r: grant(r).update(revision="rights-2")):
        stopped = w.run("resume", w.job_selector(jobs[3]["jobId"]), replay=replay, expected=2)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "grant_revision_changed" and stopped["calls"] == []
    ledger = w.jobs_ledger()
    states = {row["job_id"]: row["state"] for row in ledger["jobs"]}
    assert [states[job["jobId"]] for job in jobs] == ["ready", "ready", "cancelled", "stopped"] and ledger["tables"]["calls"] == 2
    assert fingerprint(ingestion) == frozen, "explicit operator commands on enqueued jobs must leave the ingestion state untouched"
    checks = ["4 jobs registered from a real round change ONLY through explicit operator commands: `resume --replay` makes two ready (exactly 1 replay call, 0 paid calls, one exact-quote candidate each), "
              "a queued `cancel` cancels one, a rights revision change stops one; the ingestion bytes/mtimes never change"]

    # Re-enqueueing is a report of what exists: it never re-queues, resumes, restarts or un-cancels a job, whatever state it is in.
    again = w.enqueue(d, replay=replay)
    same(again, expected_report("E-resume", rid, first, refs, {}, "existing"), "re-enqueue over ready, cancelled and stopped jobs")
    assert w.jobs_ledger() == ledger and fingerprint(ingestion) == frozen
    checks.append("the same enqueue again over 2 ready, 1 cancelled and 1 stopped job: 4 existing, every row (state, fence, updated_at) and call count unchanged, nothing executed (a stage/replay/call attempt would have ended the child with 76)")

    nxt_rid, nxt = w.new_round("09:35", *docs(w, ("x5",)))
    assert nxt["checkedWindow"]["from"] == slot("09:05") and nxt["checkpoint"]["through"] == slot("09:35") and nxt["checkpoint"]["revision"] == 2 and nxt["counts"]["newTextVersions"] == 1
    assert w.jobs_ledger() == ledger and fingerprint(ingestion) != frozen
    checks.append("the next tick afterwards starts at the stored 09:05 boundary and advances the checkpoint to 09:35 (revision 2) normally; it registers and executes nothing (the extraction ledger is unchanged)")
    return checks


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zoop-round-enqueue-smoke-") as temporary:
        root = Path(temporary).resolve()
        checks: list[str] = []
        for scenario in (guard_probe, big, identity, gates, refusals, crash, history, live, resume):
            checks += scenario(root)
    assert not root.exists()
    print(json.dumps({"schemaVersion": SCHEMA, "status": "passed", "providerCalls": 0, "modelCalls": 0,
                      "children": {"total": len(CHILDREN), **Counter(CHILDREN)},
                      "network": "every child ran under an audit hook that aborts any socket/DNS event; every enqueue child also died (76) on any stage execution, replay lookup or call reservation",
                      "clock": "injected `now` on Saturday 2026-10-17 KST for the ingestion ticks; grant expiry is judged by the real clock",
                      "temporaryStateCleanup": {"removed": True}, "checks": checks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
