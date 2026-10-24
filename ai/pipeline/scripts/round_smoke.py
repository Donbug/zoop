#!/usr/bin/env python3
"""FS058 round controller: actual `zoop-ai-ingest tick` subprocesses with an injected clock (Saturday 2026-10-17 and Sunday 2026-10-18, KST).

The expected slots, windows and round IDs below are authored literals from the functional spec and the settled contract (09:05, 09:35, ... 17:35
every calendar day, accepted while 09:00 <= now < 18:00; `window.from` is the last stored success boundary; `catchUp` only when the window is
longer than 30 minutes; `roundId = "slot-" + digest({sourceId, scopeId, slot})`). Nothing here imports the schedule implementation.

Every child is a throwaway wrapper around the installed CLI. The wrapper denies every socket/DNS event, and it traces calls to `Ingestor.run`/`resume`
on stderr. Crash, pause and "the engine must not run" are monkeypatches of that wrapper only; there is no production hook. No model or provider exists on this
path, so a single socket attempt would fail the run. The ledger is inspected only through copies and the CLI's own outputs, never in place.
"""
from __future__ import annotations

import copy
import itertools
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.ingestion_smoke import HTML, OfflineFixture, json_bytes, ownership_env  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import digest  # noqa: E402

SCHEMA = "zoop-ingestion-s2-1"
SOURCE, SCOPE = "synthetic-source", "body"
SATURDAY, SUNDAY = "2026-10-17", "2026-10-18"
assert (date.fromisoformat(SATURDAY).weekday(), date.fromisoformat(SUNDAY).weekday()) == (5, 6)
CHILDREN: list[str] = []


def body(text: str) -> bytes:
    return f"<html><body><article><p>{text}</p></article></body></html>".encode()


A1, A2, A3 = HTML, body("합성 속보 A 정정"), body("합성 속보 A 재정정")
B1, G1, H1 = body("합성 속보 B 다른 매체"), body("합성 속보 G"), body("합성 속보 H")


def at(clock: str, day: str = SATURDAY) -> str:
    return f"{day}T{clock}+09:00"


def slot(hhmm: str, day: str = SATURDAY) -> str:
    return f"{day}T{hhmm}:00+09:00"


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text)


def round_id(scope: str, when: str) -> str:
    return "slot-" + digest({"sourceId": SOURCE, "scopeId": scope, "slot": when})


NETWORK_GUARD = ("import os, sys, runpy, time\n"
                 "def _guard(event, args):\n"
                 " if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.bind', 'socket.sendto'}:\n"
                 "  raise RuntimeError('network attempted')\n"
                 "sys.addaudithook(_guard)\n")
TRACE = ("from zoop_ai_pipeline.ingestion import Ingestor\n"
         "def _trace(name):\n"
         " original = getattr(Ingestor, name)\n"
         " def traced(self, *a, **k):\n"
         "  sys.stderr.write('TRACE:' + name + '\\n')\n"
         "  sys.stderr.flush()\n"
         "  return original(self, *a, **k)\n"
         " setattr(Ingestor, name, traced)\n"
         "for _name in ('run', 'resume'):\n"
         " _trace(_name)\n")
HOOKS = {
    # The process dies after the store is open and before the engine registers anything.
    "stop-before-registration": "Ingestor.run = lambda *a, **k: os._exit(75)\n",
    # The process dies right after a NON-final page is committed (receipt, candidates, versions and checkpoint).
    "stop-after-first-page": ("_complete = Ingestor._complete_page\n"
                              "def _stop(self, *a):\n"
                              " _complete(self, *a)\n"
                              " if not a[-1]:\n"
                              "  os._exit(75)\n"
                              "Ingestor._complete_page = _stop\n"),
    # The process dies after the page response is durably saved and before any candidate is read.
    "stop-after-page-saved": "Ingestor._discover = lambda *a, **k: os._exit(75)\n",
    # A same-slot replay may only read the stored result: the engine entry points kill the child with a code nobody expects.
    "forbid-engine": "Ingestor.run = Ingestor.resume = lambda *a, **k: os._exit(97)\n",
}


def pause_hook(ready: Path, release: Path) -> str:
    """Hold the exclusive ledger lock inside the first page read until `release` appears."""
    return ("_receive = Ingestor._receive_page\n"
            "def _pause(self, *a):\n"
            f" open({str(ready)!r}, 'w').close()\n"
            " deadline = time.monotonic() + 60\n"
            f" while not os.path.exists({str(release)!r}):\n"
            "  if time.monotonic() > deadline:\n"
            "   os._exit(98)\n"
            "  time.sleep(0.02)\n"
            " return _receive(self, *a)\n"
            "Ingestor._receive_page = _pause\n")


def observer(prefixes: list[str], names: list[str]) -> str:
    """Kills the child on anything that would mean a not-due tick touched state, the registry or the manifest.

    The registry and manifest are read through `dir_fd` opens, which the audit event reports as the bare leaf name, hence the name list."""
    return (f"PREFIXES, NAMES = {tuple(prefixes)!r}, {tuple(names)!r}\n"
            "def _observe(event, args):\n"
            " if event in {'sqlite3.connect', 'fcntl.flock', 'os.mkdir'}:\n"
            "  raise RuntimeError('state touched: ' + event)\n"
            " if event == 'open':\n"
            "  try:\n"
            "   path = os.fsdecode(os.fspath(args[0]))\n"
            "  except TypeError:\n"
            "   return\n"
            "  if path.startswith(PREFIXES) or os.path.basename(path) in NAMES:\n"
            "   raise RuntimeError('watched path opened: ' + path)\n"
            "sys.addaudithook(_observe)\n")


class Rounds(OfflineFixture):
    """The existing authored-source fixture plus guarded `tick`/command children and a copy-based ledger oracle."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.requests = self.root / "requests"
        self.requests.mkdir()
        self.counter = itertools.count()
        self.calls: list[str] = []

    def article(self, key: str, **extra):
        return {**self.item(key, "supplier-" + key, f"https://example.invalid/{key}", ref=key), **extra}

    def covering(self, name: str, when: str, items=(), bodies=None, *, pages=None, status="ok", covered=True, scope=SCOPE):
        batches = pages if pages is not None else [list(items)]
        path = self.manifest(name, batches, bodies=bodies, statuses=[status] * len(batches), coverage=when if covered else None)
        if scope != SCOPE:
            payload = json.loads(path.read_bytes())
            payload["scopeId"] = scope
            path.write_bytes(json_bytes(payload))
        return path

    def watching(self, manifest: Path, state: str = "state"):
        return [str(self.root / state)], [self.registry_path.name, Path(manifest).name]

    def tick_request(self, now, initial=None, scope=SCOPE, extra=None):
        request = {"schemaVersion": SCHEMA, "sourceId": SOURCE, "scopeId": scope, **(extra or {})}
        if now is not None:
            request["now"] = now
        if initial is not None:
            request["initialFrom"] = initial
        return request

    def launch(self, command, request, *, state="state", manifest=None, sources=None, hooks=(), watch=None, flags=()):
        program = NETWORK_GUARD + TRACE + (observer(*watch) if watch else "") + "".join(hooks)
        program += "runpy.run_module('zoop_ai_pipeline.ingestion_cli', run_name='__main__')\n"
        argv = [sys.executable, "-c", program, command, "--state-dir", str(self.root / state), "--sources", str(sources or self.registry_path)]
        if manifest:
            argv += ["--fixture-manifest", str(manifest)]
        argv += list(flags)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", **ownership_env()}
        path = self.requests / f"{next(self.counter)}.json"
        path.write_bytes(json_bytes(request))
        CHILDREN.append(command)
        with path.open("rb") as stdin:
            return subprocess.Popen(argv, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE)

    def finish(self, child, expected):
        stdout, stderr = child.communicate(timeout=60)
        text = stderr.decode()
        self.calls = [line.removeprefix("TRACE:") for line in text.splitlines() if line.startswith("TRACE:")]
        assert child.returncode == expected, (child.returncode, expected, stdout.decode(), text)
        return json.loads(stdout) if stdout else None

    def tick(self, now, *, initial=None, manifest=None, state="state", scope=SCOPE, expected=0, hooks=(), watch=None, sources=None, flags=(), extra=None):
        child = self.launch("tick", self.tick_request(now, initial, scope, extra), state=state, manifest=manifest, sources=sources, hooks=hooks, watch=watch, flags=flags)
        return self.finish(child, expected)

    def command(self, name, request, *, state="state", expected=0):
        return self.finish(self.launch(name, request, state=state), expected)

    def ledger(self, state: str = "state"):
        """What the ledger holds, read from a private copy of the database and its WAL (a crashed child leaves committed rows only in the WAL)."""
        source = self.root / state
        if not (source / "ingestion.sqlite3").exists():
            return None
        copied = self.root / f"ledger-copy-{next(self.counter)}"
        copied.mkdir()
        try:
            for name in ("ingestion.sqlite3", "ingestion.sqlite3-wal"):
                if (source / name).exists():
                    shutil.copy2(source / name, copied / name)
            db = sqlite3.connect(copied / "ingestion.sqlite3")
            try:
                rounds = db.execute("SELECT id, state, next_page, expected_revision FROM rounds ORDER BY id").fetchall()
                counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("pages", "candidates", "raw_versions", "versions")}
                scopes = db.execute("SELECT revision, through_time FROM scopes").fetchall()
            finally:
                db.close()
        finally:
            shutil.rmtree(copied)
        return {"rounds": rounds, "counts": counts, "scopes": scopes}

    def states(self, state: str = "state") -> dict[str, str]:
        return {row[0]: row[1] for row in self.ledger(state)["rounds"]}


def tree(folder: Path):
    return {p.name: (p.read_bytes(), p.stat().st_mode) for p in sorted(folder.iterdir())}


def due(kit, out, action, now, when, catch_up, state, *, scope=SCOPE, failure=None):
    """Assert the wire shape of a due tick and return its (unchanged engine) round result."""
    assert set(out) == {"schemaVersion", "tick", "round"} and out["schemaVersion"] == SCHEMA, out
    tick, result = out["tick"], out["round"]
    assert set(tick) == {"action", "at", "slot", "roundId", "reason", "catchUp"}, tick
    assert (tick["action"], tick["slot"], tick["reason"], tick["catchUp"]) == (action, when, None, catch_up), tick
    assert tick["roundId"] == result["roundId"] == round_id(scope, when) and len(tick["roundId"]) <= 200, tick
    assert instant(tick["at"]) == instant(now) and tick["at"].endswith("+09:00"), tick
    assert result["state"] == state and (result["failure"] or {}).get("code") == failure and result["checkedWindow"]["through"] == when, result
    engine = {"started": kit.calls.count("run") == 1, "recovered": kit.calls == ["resume"], "replayed": kit.calls == []}[action]
    assert engine, (action, kit.calls)
    return result


def not_due(out, now, reason):
    expected = {"action": "not-due", "at": out["tick"]["at"], "slot": None, "roundId": None, "reason": reason, "catchUp": None}
    assert out == {"schemaVersion": SCHEMA, "tick": expected, "round": None}, out
    assert instant(out["tick"]["at"]) == instant(now) and out["tick"]["at"].endswith("+09:00"), out


def error(out, code):
    assert out == {"schemaVersion": SCHEMA, "error": {"code": code}}, out


def idle(kit, now, reason, manifest, state="state"):
    """Not due on the real registry, a real manifest and an existing ledger: the observer kills the child on any state/registry/manifest access."""
    folder = kit.root / state
    before = tree(folder) if folder.exists() else None
    not_due(kit.tick(now, manifest=manifest, state=state, watch=kit.watching(manifest, state)), now, reason)
    assert (tree(folder) if folder.exists() else None) == before


def guard_probe(root: Path):
    for code in ("import socket\nsocket.getaddrinfo('example.invalid', 80)\n", "import socket\nsocket.socket().connect(('127.0.0.1', 9))\n"):
        child = subprocess.run([sys.executable, "-c", NETWORK_GUARD + code], capture_output=True, timeout=60)
        assert child.returncode != 0 and b"network attempted" in child.stderr, child.stderr
    return ["the network guard used by every child really aborts DNS and connect (probed with the same program text)"]


NOT_DUE = [
    (at("00:00:00"), "outside_operating_window"),
    (at("08:59:59.999999"), "outside_operating_window"),
    (at("09:00:00"), "before_first_slot"),
    (at("09:04:59.999999"), "before_first_slot"),
    (at("18:00:00"), "outside_operating_window"),
    (at("23:59:59.999999"), "outside_operating_window"),
    (at("00:00:00", SUNDAY), "outside_operating_window"),
    ("2026-10-16T23:59:59Z", "outside_operating_window"),               # 08:59:59 KST
    ("2026-10-17T00:04:59.999999Z", "before_first_slot"),                # 09:04:59.999999 KST
    ("2026-10-17T09:00:00Z", "outside_operating_window"),                # 18:00:00 KST
    ("2026-10-16T19:00:00-05:00", "before_first_slot"),                  # 09:00:00 KST
]
# now, initialFrom, expected slot, expected catchUp (the window is longer than 30 minutes, strictly)
SLOTS = [
    (at("09:05:00"), at("09:00:00"), slot("09:05"), False),
    (at("09:34:59.999999"), at("09:00:00"), slot("09:05"), False),
    (at("09:35:00"), at("09:05:01"), slot("09:35"), False),              # window 29:59
    (at("10:04:59"), at("09:05:00"), slot("09:35"), False),              # window exactly 30:00
    (at("10:05:00"), at("09:34:59"), slot("10:05"), True),               # window 30:01
    (at("17:35:00"), at("17:30:00"), slot("17:35"), False),
    (at("17:59:59.999999"), at("17:30:00"), slot("17:35"), False),
    ("2026-10-17T00:05:00Z", "2026-10-16T15:00:00Z", slot("09:05"), True),                       # 09:05 KST from 00:00 KST, spelled in UTC
    ("2026-10-17T00:59:59.999999-08:00", "2026-10-16T22:00:00-08:00", slot("17:35"), True),      # 17:59:59.999999 KST from 15:00 KST
    (at("09:05:00", SUNDAY), at("18:00:00"), slot("09:05", SUNDAY), True),                       # the evening before
]


def boundaries(root: Path):
    table = Rounds(root / "table")
    never = table.covering("never-read", slot("09:05"))
    for now, reason in NOT_DUE:
        idle(table, now, reason, never)
        assert not (table.root / "state").exists()
    garbage = table.root / "garbage-sources.json"
    garbage.write_bytes(b"{not a registry")
    not_due(table.tick(at("08:00:00"), manifest=never, sources=garbage, watch=table.watching(never)), at("08:00:00"), "outside_operating_window")
    for number, (now, initial, when, catch_up) in enumerate(SLOTS):
        kit = Rounds(root / f"slot-{number}")
        result = due(kit, kit.tick(now, initial=initial, manifest=kit.covering("zero", when)), "started", now, when, catch_up, "complete")
        assert instant(result["checkedWindow"]["from"]) == instant(initial) and result["completion"] == "source-zero" and result["checkpoint"]["through"] == when, result
    return [f"{len(NOT_DUE)} not-due instants (seconds, midnight, Sunday, UTC/-05:00 spelling): exit 0, the real registry/manifest/ledger never opened, no state directory created",
            "an unreadable registry does not matter while not due",
            f"{len(SLOTS)} due instants map to the literal slot with the literal catchUp (29:59/30:00 false, 30:01 true, UTC and -08:00 spelling, Sunday morning)"]


def week(root: Path):
    kit = Rounds(root / "week")
    folder = kit.root / "state"
    # Baseline: the first slot needs an explicit start, which must lie before the slot.
    m0905 = kit.covering("m-0905", slot("09:05"), [kit.article("a")], {"a": A1})
    error(kit.tick(at("09:05:00"), manifest=m0905, expected=2), "initial_baseline_required")
    error(kit.tick(at("09:05:00"), initial=slot("09:05"), manifest=m0905, expected=2), "slot_not_after_baseline")
    error(kit.tick(at("09:05:00"), initial=at("09:06:00"), manifest=m0905, expected=2), "slot_not_after_baseline")
    assert kit.ledger()["rounds"] == [] and kit.ledger()["scopes"] == []
    first = due(kit, kit.tick(at("09:05:30"), initial=at("00:00:00"), manifest=m0905), "started", at("09:05:30"), slot("09:05"), True, "complete")
    assert instant(first["checkedWindow"]["from"]) == instant(at("00:00:00")) and first["checkpoint"]["through"] == slot("09:05")
    assert first["completion"] == "nonzero-discovery" and first["counts"]["newTextVersions"] == 1 and first["checkpoint"]["revision"] == 1
    a_first = first["documentRefs"][0]
    # The same slot again is a replay of the stored result, never a retry: the engine entry points kill the child.
    before = kit.ledger()
    for now, initial, manifest in (("09:20:00", at("00:00:00"), m0905), ("09:21:00", "2026-10-16T15:00:00Z", m0905), ("09:22:00", None, m0905), ("09:23:00", None, None)):
        again = due(kit, kit.tick(at(now), initial=initial, manifest=manifest, hooks=(HOOKS["forbid-engine"],)), "replayed", at(now), slot("09:05"), True, "complete")
        assert again == first
    assert kit.ledger() == before
    # The stored request is frozen: another baseline or another manifest for the same slot is a conflict that writes nothing.
    edited = kit.covering("edited-0905", slot("09:05"), [kit.article("a")], {"a": A2})
    error(kit.tick(at("09:25:00"), initial=at("00:00:01"), manifest=m0905, expected=2), "slot_input_conflict")
    error(kit.tick(at("09:25:00"), manifest=edited, expected=2), "slot_input_conflict")
    assert kit.ledger() == before
    # Next slot starts at the exact stored boundary; a 30 minute window is not a catch-up. A known article is reused, another article about the event stays separate.
    m0935 = kit.covering("m-0935", slot("09:35"), [kit.article("a"), kit.article("b")], {"a": A1, "b": B1})
    second = due(kit, kit.tick(at("09:35:00"), manifest=m0935), "started", at("09:35:00"), slot("09:35"), False, "complete")
    a_second, b_second = second["documentRefs"]
    assert second["checkedWindow"]["from"] == slot("09:05") and second["checkpoint"]["through"] == slot("09:35")
    assert (a_second["documentId"], a_second["documentVersion"]) == (a_first["documentId"], a_first["documentVersion"]) and b_second["documentId"] != a_first["documentId"]
    assert {k: second["counts"][k] for k in ("discoveredCandidates", "newRawVersions", "newTextVersions", "reusedVersions", "textReady")} == {"discoveredCandidates": 2, "newRawVersions": 1, "newTextVersions": 1, "reusedVersions": 1, "textReady": 2}
    # initialFrom is only for a scope that has no stored success time.
    before = kit.ledger()
    error(kit.tick(at("10:05:00"), initial=slot("09:35"), manifest=kit.covering("m-1005-x", slot("10:05")), expected=2), "initial_baseline_conflict")
    assert kit.ledger() == before
    # A failed page: exit 3, the success boundary stays, and a duplicate trigger (even with the same manifest) does not retry.
    failing_item = kit.article("a", modifiedAt=at("10:00:00"))
    m1005 = kit.covering("m-1005", slot("10:05"), [failing_item], {"a": A2}, status="failed", covered=False)
    failed = due(kit, kit.tick(at("10:05:00"), manifest=m1005, expected=3), "started", at("10:05:00"), slot("10:05"), False, "incomplete", failure="discovery_page_failed")
    assert failed["checkpoint"]["through"] == slot("09:35") and failed["checkpoint"]["revision"] == second["checkpoint"]["revision"]
    before = kit.ledger()
    for now, manifest in (("10:20:00", None), ("10:21:00", m1005)):
        again = due(kit, kit.tick(at(now), manifest=manifest, expected=3, hooks=(HOOKS["forbid-engine"],)), "replayed", at(now), slot("10:05"), False, "incomplete", failure="discovery_page_failed")
        assert again == failed
    assert kit.ledger() == before
    # The next slot starts from the last SUCCESS (09:35), so it covers the failed slot too; a changed body is a new version of the same document.
    m1035 = kit.covering("m-1035", slot("10:35"), [kit.article("a", modifiedAt=at("10:30:00"))], {"a": A3})
    third = due(kit, kit.tick(at("10:35:00"), manifest=m1035), "started", at("10:35:00"), slot("10:35"), True, "complete")
    assert third["checkedWindow"]["from"] == slot("09:35") and third["checkpoint"]["through"] == slot("10:35")
    a_third = third["documentRefs"][0]
    assert a_third["documentId"] == a_first["documentId"]
    assert a_third["documentVersion"] not in {a_first["documentVersion"], failed["documentRefs"][0]["documentVersion"]}
    assert third["counts"]["newTextVersions"] == 1 and third["counts"]["reusedVersions"] == 0
    # A partial page: its text is prepared once, the boundary does not move, no retry.
    m1105 = kit.covering("m-1105", slot("11:05"), [kit.article("g")], {"g": G1}, status="partial", covered=False)
    partial = due(kit, kit.tick(at("11:05:00"), manifest=m1105, expected=3), "started", at("11:05:00"), slot("11:05"), False, "incomplete", failure="discovery_page_partial")
    assert partial["checkpoint"]["through"] == slot("10:35") and partial["counts"]["textReady"] == 1
    again = due(kit, kit.tick(at("11:20:00"), expected=3, hooks=(HOOKS["forbid-engine"],)), "replayed", at("11:20:00"), slot("11:05"), False, "incomplete", failure="discovery_page_partial")
    assert again == partial
    # A covered round with nothing new is a valid result and advances the boundary (from the last success, so a 60 minute window is a catch-up).
    zero = due(kit, kit.tick(at("11:35:00"), manifest=kit.covering("m-1135", slot("11:35"))), "started", at("11:35:00"), slot("11:35"), True, "complete")
    assert zero["completion"] == "source-zero" and zero["counts"]["discoveredCandidates"] == 0 and zero["checkedWindow"]["from"] == slot("10:35") and zero["checkpoint"]["through"] == slot("11:35")
    # Nothing new WITHOUT declared coverage is not a success: the boundary stays.
    unproven = due(kit, kit.tick(at("12:05:00"), manifest=kit.covering("m-1205", slot("12:05"), covered=False), expected=3), "started", at("12:05:00"), slot("12:05"), False, "incomplete", failure="coverage_incomplete")
    assert unproven["checkpoint"]["through"] == slot("11:35") and unproven["completion"] is None
    # The following slot covers the whole gap, and the text prepared by the partial round is reused, not duplicated.
    m1235 = kit.covering("m-1235", slot("12:35"), [kit.article("g"), kit.article("h")], {"g": G1, "h": H1})
    gap = due(kit, kit.tick(at("12:35:00"), manifest=m1235), "started", at("12:35:00"), slot("12:35"), True, "complete")
    assert gap["checkedWindow"]["from"] == slot("11:35") and gap["checkpoint"]["through"] == slot("12:35")
    assert gap["documentRefs"][0]["documentVersion"] == partial["documentRefs"][0]["documentVersion"]
    assert {k: gap["counts"][k] for k in ("discoveredCandidates", "newRawVersions", "newTextVersions", "reusedVersions")} == {"discoveredCandidates": 2, "newRawVersions": 1, "newTextVersions": 1, "reusedVersions": 1}
    # Late triggers: slots 13:05-14:35 never fired; 15:20 runs 15:05, and 17:59:59.999999 still runs 17:35 (one catch-up round each, not one per missed slot).
    late = due(kit, kit.tick(at("15:20:00"), manifest=kit.covering("m-1505", slot("15:05"))), "started", at("15:20:00"), slot("15:05"), True, "complete")
    assert late["checkedWindow"]["from"] == slot("12:35")
    m1735 = kit.covering("m-1735", slot("17:35"), [kit.article("b")], {"b": B1})
    last = due(kit, kit.tick(at("17:59:59.999999"), manifest=m1735), "started", at("17:59:59.999999"), slot("17:35"), True, "complete")
    assert last["checkedWindow"]["from"] == slot("15:05") and last["counts"]["reusedVersions"] == 1 and last["counts"]["newTextVersions"] == 0
    # Closing time and midnight leave the ledger bytes alone; a clock that moved back to a slot with no round is refused.
    for now, reason in ((at("18:00:00"), "outside_operating_window"), (at("23:59:59.999999"), "outside_operating_window"),
                        (at("00:00:00", SUNDAY), "outside_operating_window"), (at("09:04:59.999999", SUNDAY), "before_first_slot")):
        idle(kit, now, reason, m1735)
    before = kit.ledger()
    error(kit.tick(at("16:05:00"), manifest=kit.covering("m-1605", slot("16:05")), expected=2), "slot_not_after_baseline")
    assert kit.ledger() == before
    # Sunday has no special rule: the first slot runs from Saturday's last boundary (overnight catch-up) and the known articles are reused across midnight.
    sun_items = [kit.article("a", modifiedAt=at("10:30:00")), kit.article("b")]
    sunday = due(kit, kit.tick(at("09:05:00", SUNDAY), manifest=kit.covering("m-sun-0905", slot("09:05", SUNDAY), sun_items, {"a": A3, "b": B1})),
                 "started", at("09:05:00", SUNDAY), slot("09:05", SUNDAY), True, "complete")
    assert sunday["checkedWindow"]["from"] == slot("17:35") and sunday["counts"]["reusedVersions"] == 2 and sunday["counts"]["newTextVersions"] == 0
    assert [r["documentVersion"] for r in sunday["documentRefs"]] == [a_third["documentVersion"], last["documentRefs"][0]["documentVersion"]]
    again = due(kit, kit.tick(at("09:20:00", SUNDAY), hooks=(HOOKS["forbid-engine"],)), "replayed", at("09:20:00", SUNDAY), slot("09:05", SUNDAY), True, "complete")
    assert again == sunday
    sunday_next = due(kit, kit.tick(at("09:35:00", SUNDAY), manifest=kit.covering("m-sun-0935", slot("09:35", SUNDAY))), "started", at("09:35:00", SUNDAY), slot("09:35", SUNDAY), False, "complete")
    assert sunday_next["checkedWindow"]["from"] == slot("09:05", SUNDAY)
    # Exactly the twelve slots ran, replays and refusals created nothing; the incomplete ones are the three that never proved coverage.
    slots = [slot(h) for h in ("09:05", "09:35", "10:05", "10:35", "11:05", "11:35", "12:05", "12:35", "15:05", "17:35")] + [slot("09:05", SUNDAY), slot("09:35", SUNDAY)]
    incomplete = {slot("10:05"), slot("11:05"), slot("12:05")}
    assert kit.states() == {round_id(SCOPE, s): "incomplete" if s in incomplete else "complete" for s in slots}
    final = kit.ledger()
    assert final["scopes"] == [(10, slot("09:35", SUNDAY))], final["scopes"]   # failed and partial pages never completed; the unproven one only moved the revision
    assert folder.is_dir() and all(p.name.startswith("ingestion.") for p in folder.iterdir())
    return ["baseline: required, conflict once a success exists, and must lie before the slot; clock moved back to a slot with no round refused",
            "same slot again: replay of the stored result with the engine forbidden (byte-identical round), also with a differently spelled equal baseline; other baseline/manifest = slot_input_conflict, nothing written",
            "new slot starts at the exact stored boundary: 30 minutes is not catchUp, a catch-up round covers the failed slot",
            "cross-round dedup (same version reused, other article separate), changed body = same document ID with a new version, also across midnight",
            "failed and partial pages: exit 3, boundary unchanged, duplicate triggers never retry; zero with coverage advances, zero without coverage does not",
            "skipped slots: one late round per trigger (15:20 -> 15:05, 17:59:59.999999 -> 17:35); closing time and midnight change no ledger byte; Sunday runs and spans the night",
            "twelve slots -> exactly twelve rounds in the ledger, no duplicate or hidden round"]


def crash(root: Path):
    kit = Rounds(root / "crash")
    # Dies after the store is open and before the engine registers the round: nothing is stored and the same slot starts normally.
    m1135 = kit.covering("m-1135", slot("11:35"), [kit.article("a")], {"a": A1})
    assert kit.tick(at("11:35:10"), initial=at("11:10:00"), manifest=m1135, hooks=(HOOKS["stop-before-registration"],), expected=75) is None
    assert kit.ledger()["rounds"] == [] and kit.ledger()["scopes"] == []
    started = due(kit, kit.tick(at("11:36:00"), initial=at("11:10:00"), manifest=m1135), "started", at("11:36:00"), slot("11:35"), False, "complete")
    assert started["counts"]["newTextVersions"] == 1 and list(kit.states().values()) == ["complete"]
    # Dies right after the first of two pages is committed. The inputs of that page are then removed: the recovery must not read them again.
    m1205 = kit.covering("m-1205", slot("12:05"), pages=[[kit.article("b")], [kit.article("g")]], bodies={"b": B1, "g": G1})
    assert kit.tick(at("12:05:20"), manifest=m1205, hooks=(HOOKS["stop-after-first-page"],), expected=75) is None
    held = kit.ledger()
    assert kit.states()[round_id(SCOPE, slot("12:05"))] == "running" and held["counts"]["pages"] == 2 and held["scopes"][0][1] == slot("11:35")
    # A running round is never resumed under a changed or revoked right. The check comes before the resume, so the round stays `running` (it is not
    # turned into `incomplete` by a refused resume) and a later tick still recovers it.
    shown, original = kit.ledger(), copy.deepcopy(kit.registry)
    kit.registry["sources"][0]["scopes"][0]["selection"] = "selection changed after the crash"
    kit.save_registry()
    error(kit.tick(at("12:05:40"), manifest=m1205, expected=2), "scope_configuration_conflict")
    kit.registry = copy.deepcopy(original)
    kit.registry["sources"][0]["grant"]["enabled"] = False
    kit.save_registry()
    error(kit.tick(at("12:05:50"), manifest=m1205, expected=2), "source_unauthorized")
    assert kit.ledger() == shown and kit.states()[round_id(SCOPE, slot("12:05"))] == "running"
    kit.registry = copy.deepcopy(original)
    kit.save_registry()
    payload = json.loads(m1205.read_bytes())
    (kit.inputs / payload["pages"][0]["response"]["file"]).unlink()
    (kit.inputs / payload["documents"]["b"]["file"]).unlink()
    recovered = due(kit, kit.tick(at("12:06:00"), manifest=m1205), "recovered", at("12:06:00"), slot("12:05"), False, "complete")
    assert [p["complete"] for p in recovered["pages"]] == [True, True] and recovered["counts"]["newTextVersions"] == 2 and recovered["checkpoint"]["through"] == slot("12:05")
    done = kit.ledger()
    assert done["counts"]["pages"] == 3 and done["counts"]["candidates"] == 3 and len(done["rounds"]) == 2
    again = due(kit, kit.tick(at("12:07:00"), hooks=(HOOKS["forbid-engine"],)), "replayed", at("12:07:00"), slot("12:05"), False, "complete")
    assert again == recovered and kit.ledger() == done
    # Dies after a page response is saved. An older unfinished slot is never resumed by a newer slot, which starts at the last success.
    old = round_id(SCOPE, slot("12:35"))
    m1235 = kit.covering("m-1235", slot("12:35"), [kit.article("h")], {"h": H1})
    assert kit.tick(at("12:35:30"), manifest=m1235, hooks=(HOOKS["stop-after-page-saved"],), expected=75) is None
    assert kit.states()[old] == "running"
    newer = due(kit, kit.tick(at("13:05:00"), manifest=kit.covering("m-1305", slot("13:05"), [kit.article("h")], {"h": H1})), "started", at("13:05:00"), slot("13:05"), True, "complete")
    assert newer["checkedWindow"]["from"] == slot("12:05") and kit.states()[old] == "running"
    # Only an explicit operator resume touches it, and the engine's own checkpoint rule refuses it as stale.
    stale = kit.command("resume", kit.selector(old))
    assert stale["state"] == "incomplete" and stale["failure"] == {"code": "checkpoint_stale"} and kit.states()[old] == "incomplete"
    held = kit.ledger()
    replay = due(kit, kit.tick(at("12:40:00"), expected=3, hooks=(HOOKS["forbid-engine"],)), "replayed", at("12:40:00"), slot("12:35"), False, "incomplete", failure="checkpoint_stale")
    assert replay["roundId"] == old and kit.ledger() == held
    return ["crash before the round is registered: nothing stored, the same slot then starts once normally",
            "crash after the first page commit: a changed scope configuration or a revoked grant refuses the tick while the round stays `running`; restored, it is recovered once from the stored page with the page's input files removed (no re-fetch), then replayed; no duplicate pages/candidates",
            "an older running slot is not auto-resumed by the next slot (starts at the last success); explicit resume is stale; the stale round is only replayed"]


def concurrency(root: Path):
    kit = Rounds(root / "concurrent")
    base = due(kit, kit.tick(at("13:05:00"), initial=at("13:00:00"), manifest=kit.covering("m-1305", slot("13:05"), [kit.article("a")], {"a": A1})), "started", at("13:05:00"), slot("13:05"), False, "complete")
    m1335 = kit.covering("m-1335", slot("13:35"), [kit.article("b")], {"b": B1})
    ready, release = kit.root / "holder-ready", kit.root / "holder-release"
    holder = kit.launch("tick", kit.tick_request(at("13:35:00")), manifest=m1335, hooks=(pause_hook(ready, release),))
    try:
        deadline = time.monotonic() + 30
        while not ready.exists():
            assert holder.poll() is None and time.monotonic() < deadline, "the first tick never reached its page while holding the lock"
            time.sleep(0.02)
        rivals = [kit.launch("tick", kit.tick_request(at(clock)), manifest=m1335) for clock in ("13:35:10", "13:35:20")]
        for rival in rivals:
            error(kit.finish(rival, 2), "ingestion_busy")
        assert holder.poll() is None, "the holder must still own the lock while the rivals were refused"
        release.write_bytes(b"")
        won = due(kit, kit.finish(holder, 0), "started", at("13:35:00"), slot("13:35"), False, "complete")
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.communicate()
    assert won["checkedWindow"]["from"] == slot("13:05") and won["counts"]["newTextVersions"] == 1
    again = due(kit, kit.tick(at("13:40:00"), manifest=m1335, hooks=(HOOKS["forbid-engine"],)), "replayed", at("13:40:00"), slot("13:35"), False, "complete")
    assert again == won
    final = kit.ledger()
    assert kit.states() == {round_id(SCOPE, slot("13:05")): "complete", round_id(SCOPE, slot("13:35")): "complete"}, kit.states()
    assert final["counts"]["pages"] == 2 and final["counts"]["candidates"] == 2 and base["checkpoint"]["revision"] == 1
    return ["concurrent same-slot ticks while one holds the ledger lock: both refused with ingestion_busy without waiting or writing, the holder wins once, the next tick replays; exactly one round for the slot"]


def retry(root: Path):
    """A recoverable incomplete round is the sharpest 'no hidden retry' case: the engine COULD finish it as soon as the missing file is back."""
    kit = Rounds(root / "retry")
    manifest = kit.covering("m-0905", slot("09:05"), pages=[[kit.article("a")], [kit.article("b")]], bodies={"a": A1, "b": B1})
    missing = kit.inputs / json.loads(manifest.read_bytes())["documents"]["b"]["file"]
    saved = missing.read_bytes()
    missing.unlink()
    rid = round_id(SCOPE, slot("09:05"))
    held = due(kit, kit.tick(at("09:05:10"), initial=at("09:00:00"), manifest=manifest, expected=3), "started", at("09:05:10"), slot("09:05"), False, "incomplete", failure="persistence_or_input_failed")
    assert [p["complete"] for p in held["pages"]] == [True, False] and held["checkpoint"]["through"] is None
    # The file is back and the engine could finish now; neither a bare same-slot tick nor one that passes the manifest again may do it.
    missing.write_bytes(saved)
    before = kit.ledger()
    for now, given in (("09:20:00", None), ("09:21:00", manifest)):
        again = due(kit, kit.tick(at(now), manifest=given, expected=3, hooks=(HOOKS["forbid-engine"],)), "replayed", at(now), slot("09:05"), False, "incomplete", failure="persistence_or_input_failed")
        assert again == held
    assert kit.ledger() == before and kit.states() == {rid: "incomplete"}
    # Only the explicit operator command completes it, and afterwards the same slot is a plain replay of the completed result.
    resumed = kit.command("resume", kit.selector(rid))
    assert resumed["state"] == "complete" and [p["complete"] for p in resumed["pages"]] == [True, True], resumed
    assert resumed["checkpoint"]["through"] == slot("09:05") and resumed["counts"]["newTextVersions"] == 2
    done = due(kit, kit.tick(at("09:22:00"), hooks=(HOOKS["forbid-engine"],)), "replayed", at("09:22:00"), slot("09:05"), False, "complete")
    assert done == resumed
    return ["no hidden retry on a RECOVERABLE incomplete round: the missing body is restored, same-slot ticks (with and without the manifest) still replay `incomplete` with the engine forbidden and the ledger unchanged; only the explicit operator `resume` completes it, then the slot replays complete"]


def rights(root: Path):
    kit = Rounds(root / "rights")
    m0905 = kit.covering("m-0905", slot("09:05"), [kit.article("a")], {"a": A1})
    first = due(kit, kit.tick(at("09:05:00"), initial=at("09:00:00"), manifest=m0905), "started", at("09:05:00"), slot("09:05"), False, "complete")
    original = copy.deepcopy(kit.registry)
    m0935 = kit.covering("m-0935", slot("09:35"), [kit.article("b")], {"b": B1})
    kit.registry["sources"][0]["grant"]["enabled"] = False
    kit.save_registry()
    before = kit.ledger()
    # A revoked grant denies a due tick and the replay of a stored result; the slot is not skipped silently, no body is returned, nothing is stored.
    error(kit.tick(at("09:35:00"), manifest=m0935, expected=2), "source_unauthorized")
    error(kit.tick(at("09:20:00"), expected=2), "source_unauthorized")
    # While not due the registry is never even opened.
    idle(kit, at("08:00:00"), "outside_operating_window", m0935)
    idle(kit, at("09:02:00"), "before_first_slot", m0935)
    kit.registry["sources"] = []
    kit.save_registry()
    error(kit.tick(at("09:35:00"), manifest=m0935, expected=2), "source_unauthorized")
    error(kit.tick(at("09:20:00"), expected=2), "source_unauthorized")
    assert kit.ledger() == before
    # Grant expiry is judged by the REAL clock, not the injected one: this grant expires after the injected 09:35 but long before today.
    kit.registry = copy.deepcopy(original)
    kit.registry["sources"][0]["grant"]["expiresAt"] = at("12:00:00")
    kit.save_registry()
    error(kit.tick(at("09:35:00"), manifest=m0935, expected=2), "source_unauthorized")
    error(kit.tick(at("09:20:00"), expected=2), "source_unauthorized")
    assert kit.ledger() == before
    # The same ledger works again once the right is back, so the denials were rights, not state. An unregistered scope is no source either.
    kit.registry = copy.deepcopy(original)
    kit.save_registry()
    error(kit.tick(at("09:35:00"), scope="unregistered", manifest=m0935, expected=2), "source_unauthorized")
    again = due(kit, kit.tick(at("09:20:00"), hooks=(HOOKS["forbid-engine"],)), "replayed", at("09:20:00"), slot("09:05"), False, "complete")
    assert again == first
    resumed = due(kit, kit.tick(at("09:35:00"), manifest=m0935), "started", at("09:35:00"), slot("09:35"), False, "complete")
    assert resumed["checkedWindow"]["from"] == slot("09:05")
    return ["revoked, removed or (by the REAL clock, not the injected `now`) expired grant: a due tick and a replay are denied (source_unauthorized, no body, no write); not due stays exit 0 without opening the registry; restored rights replay and run normally"]


def inputs(root: Path):
    kit = Rounds(root / "inputs")
    manifest = kit.covering("m-0905", slot("09:05"), [kit.article("a")], {"a": A1})
    for now in ("2099-01-01T09:05:00+09:00", (datetime.now(UTC) + timedelta(minutes=1)).isoformat()):
        error(kit.tick(now, initial=at("09:00:00"), manifest=manifest, expected=2), "clock_in_future")
    for bad in ({"now": "2026-10-17T09:05:00"}, {"initialFrom": "2026-10-17T09:00:00"}, {"unexpected": True}):
        request = {**kit.tick_request(at("09:05:00"), at("09:00:00")), **bad}
        error(kit.finish(kit.launch("tick", request, manifest=manifest), 2), "input_or_configuration_invalid")
    error(kit.finish(kit.launch("tick", kit.tick_request(at("09:05:00"), at("09:00:00")), manifest=manifest, flags=["--require-store"]), 2), "require_store_not_allowed")
    assert not (kit.root / "state").exists()
    error(kit.tick(at("09:05:00"), initial=at("09:00:00"), expected=2), "fixture_manifest_required")
    assert kit.ledger()["rounds"] == []
    # The 200 character scope the engine allows still gets a bounded, distinct, deterministic round ID.
    long_scope = ("긴범위-" * 50)[:200]
    assert len(long_scope) == 200
    long = Rounds(root / "long")
    long.registry["sources"][0]["scopes"][0]["scopeId"] = long_scope
    long.save_registry()
    result = due(long, long.tick(at("09:35:00"), initial=at("09:05:00"), scope=long_scope, manifest=long.covering("m-0935", slot("09:35"), scope=long_scope)),
                 "started", at("09:35:00"), slot("09:35"), False, "complete", scope=long_scope)
    assert len(result["roundId"]) == 69 and result["roundId"] != round_id(SCOPE, slot("09:35"))
    return ["clock in the future (2099 and one minute ahead), naive timestamps, unknown keys, --require-store: refused before any state exists",
            "a due first slot without a manifest: fixture_manifest_required, no round",
            "200 character scope: bounded deterministic round ID, no artificial scope limit"]


def main():
    with tempfile.TemporaryDirectory(prefix="zoop-round-smoke-") as temporary:
        root = Path(temporary).resolve()
        checks = []
        for scenario in (guard_probe, boundaries, week, crash, concurrency, retry, rights, inputs):
            checks += scenario(root)
    assert not root.exists()
    print(json.dumps({"schemaVersion": SCHEMA, "status": "passed", "providerCalls": 0, "modelCalls": 0,
                      "children": {"total": len(CHILDREN), **Counter(CHILDREN)},
                      "network": "every child ran under an audit hook that aborts any socket/DNS event; no provider or model client exists on this path",
                      "clock": f"injected `now` on Saturday {SATURDAY} and Sunday {SUNDAY} KST (before the real date)",
                      "temporaryStateCleanup": {"removed": True}, "checks": checks}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
