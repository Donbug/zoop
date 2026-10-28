"""Handoffs frozen under an earlier bundle schema (`-1` before original mentions, `-2` before field provenance) whose committed rows exist ONLY in a hot write-ahead log (a pre-cutover writer was killed).

An immutable/read-only open never sees such rows, and any writable open of the ledger re-permissions it, checkpoints the WAL and may run DDL BEFORE the legacy
refusal. Every command below runs through the real `zoop_ai_pipeline.handoff_cli` in a child process (`graph_handoff_smoke.Operator`) against a real ledger:
the legacy rows are committed by a writer that dies with `os._exit(9)` without closing it (stale `-shm` and a non-empty `-wal` stay), the directory and files are
set to modes a writer would visibly reset, and the whole ledger directory (bytes, modes, mtimes, every file) must be identical after each command.
Expectations are written by hand; nothing is derived from the code under test.
"""
from __future__ import annotations

import fcntl
import os
import sqlite3
import stat

import pytest

from scripts import graph_handoff_smoke as hs

CONTRACT_CHANGED = {"status": "withheld", "code": "handoff_contract_changed"}
ROWS = {"ready": ("ready", "written"), "reserved": ("reserved", "missing"), "failed": ("failed", "garbage")}
SCHEMAS = [hs.BUNDLE_1, hs.BUNDLE_2, hs.BUNDLE_3, hs.BUNDLE_4, hs.BUNDLE_5, hs.BUNDLE_6]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    built = hs.build_world(tmp_path_factory.mktemp("zoop-handoff-wal") / "owned")
    hs.write_operator(built)
    return built


class Hot:
    """A real current ledger (one current `-3` row) plus ONE legacy row (`schema=` `-1` or `-2`) committed only to its hot WAL, with modes a writer would reset."""

    def __init__(self, world, tmp_path, kind: str = "ready", **plant):
        self.world, self.operator, self.state = world, hs.Operator(world), tmp_path / "handoff"
        self.files = hs.file_hashes(world.root)
        self.operator.cli("freeze", self.manifest("current-0"), state=self.state)
        exported = self.operator.cli("export", self.operator.sel("current-0"), state=self.state)
        row_state, artifact = ROWS[kind]
        self.name = f"legacy-{kind}"
        self.row = hs.plant_legacy_handoff(self.state, self.manifest(self.name), exported["bundle"], row_state=row_state, artifact=artifact, wal=True, **plant)
        os.chmod(self.state, 0o755)
        for path in self.state.rglob("*"):
            os.chmod(path, 0o755 if path.is_dir() else 0o644)

    def manifest(self, name: str, **override) -> dict:
        return {**hs.manifest_doc(self.world, name, self.files), **override}

    def cli(self, command: str, *, expected: int, name: str | None = None, absent: bool = False, request: dict | None = None) -> dict:
        return self.operator.cli(command, request or self.operator.sel(name or self.name), expected=expected, state=self.state, absent=absent)

    def snapshot(self) -> dict:
        return hs.ledger_snapshot(self.state)

    def only_in_the_wal(self) -> bool:
        """True when the legacy row is invisible to an immutable open of the main file and a non-empty WAL exists."""
        wal = self.state / "handoff.sqlite3-wal"
        db = sqlite3.connect((self.state / "handoff.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            invisible = db.execute("SELECT COUNT(*) FROM handoffs WHERE handoff_id=?", (self.name,)).fetchone()[0] == 0
        finally:
            db.close()
        return invisible and wal.is_file() and wal.stat().st_size > 0 and (self.state / "handoff.sqlite3-shm").exists()


def error_code(out: dict) -> str:
    assert set(out) == {"schemaVersion", "error"}, out
    return out["error"]["code"]


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("kind", list(ROWS))
def test_a_legacy_row_committed_only_to_a_hot_wal_is_history_and_no_command_changes_the_ledger(world, tmp_path, kind, schema):
    hot = Hot(world, tmp_path, kind, schema=schema)
    assert hot.row["receipt"]["bundleSchema"] == schema
    assert hot.only_in_the_wal(), "the fixture must leave the legacy row only in a non-empty WAL"
    assert stat.S_IMODE(hot.state.stat().st_mode) == 0o755
    before = hot.snapshot()

    seen = hot.cli("inspect", expected=2)
    assert seen["state"] == hot.row["state"] and seen["next"] is None and seen["delivery"] == CONTRACT_CHANGED and seen["publication"] == "not-published", seen
    assert seen["receipt"] == hot.row["receipt"] and seen["attempts"] == hot.row["attempts"] and "bundle" not in seen
    assert hot.snapshot() == before, "inspect changed the ledger directory"

    gone = hot.cli("export", expected=2, absent=True)
    assert gone == {"schemaVersion": "zoop-ai-handoff-1", "handoffId": hot.name, "state": hot.row["state"], "publication": "not-published",
                    "delivery": CONTRACT_CHANGED, "usage": {"providerCalls": 0, "modelCalls": 0}}, gone
    assert hot.snapshot() == before, "export changed the ledger directory"

    assert error_code(hot.cli("recover", expected=2)) == "handoff_contract_changed"
    assert hot.snapshot() == before, "recover changed the ledger directory (re-permission, WAL checkpoint or a settled row)"

    for manifest in (hot.manifest(hot.name), hot.manifest(hot.name, sourceKind="actual")):
        assert error_code(hot.cli("freeze", expected=2, absent=True, request=manifest)) == "handoff_contract_changed"
        assert hot.snapshot() == before, "freeze changed the ledger directory before refusing"


@pytest.mark.parametrize("command", ["inspect", "export", "recover", "freeze"])
def test_a_damaged_receipt_in_the_wal_is_a_state_error_and_still_changes_nothing(world, tmp_path, command):
    hot = Hot(world, tmp_path, "ready", damaged=True)
    before = hot.snapshot()
    request = hot.manifest(hot.name) if command == "freeze" else None
    out = hot.cli(command, expected=2, absent=command in {"export", "freeze"}, request=request)
    assert error_code(out) == "handoff_state_invalid", out
    assert hot.snapshot() == before


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("command", ["inspect", "export", "recover", "freeze"])
def test_a_busy_writer_is_an_error_never_a_fall_through_to_a_writable_open(world, tmp_path, command, schema):
    hot = Hot(world, tmp_path, "ready", schema=schema)
    before = hot.snapshot()
    fd = os.open(hot.state / "handoff.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request = hot.manifest(hot.name) if command == "freeze" else None
        out = hot.cli(command, expected=2, absent=command in {"export", "freeze"}, request=request)
    finally:
        os.close(fd)
    assert error_code(out) == "handoff_busy", out
    assert hot.snapshot() == before


@pytest.mark.parametrize("schema", SCHEMAS)
def test_a_new_handoff_id_still_freezes_beside_the_wal_only_history_which_stays_as_it_was(world, tmp_path, schema):
    hot = Hot(world, tmp_path, "ready", schema=schema)

    def history() -> tuple:
        db = sqlite3.connect(hot.state / "handoff.sqlite3")
        try:
            return (db.execute("SELECT * FROM handoffs WHERE handoff_id=?", (hot.name,)).fetchall(),
                    db.execute("SELECT * FROM attempts WHERE handoff_id=?", (hot.name,)).fetchall())
        finally:
            db.close()

    artifact = hot.row["artifact"].read_bytes()
    hot.cli("freeze", expected=0, request=hot.manifest("current-1"))              # the ordinary writer path: settles the WAL, then freezes
    assert hot.cli("export", expected=0, name="current-1")["delivery"]["status"] == "current"
    rows, attempts = history()
    assert len(rows) == 1 and rows[0][0] == hot.name and rows[0][7] == "ready" and len(attempts) == 1
    assert hot.row["artifact"].read_bytes() == artifact
    seen = hot.cli("inspect", expected=2)
    assert seen["receipt"] == hot.row["receipt"] and seen["attempts"] == hot.row["attempts"] and seen["delivery"] == CONTRACT_CHANGED


# ---- the CURRENT contract's crash recovery must keep working (a killed current writer leaves the same hot WAL, and its rows ARE recoverable) ----------

@pytest.mark.parametrize("hook,final", [("kill-after-reserve", "failed"), ("kill-after-artifact", "ready")])
def test_a_killed_current_writer_is_still_recovered_from_its_hot_wal(world, tmp_path, hook, final):
    operator, state = hs.Operator(world), tmp_path / "handoff"
    name = f"current-{hook}"
    manifest = {**hs.manifest_doc(world, name, hs.file_hashes(world.root))}
    operator.cli("freeze", manifest, expected=9, hook=hook, state=state)
    assert (state / "handoff.sqlite3-wal").stat().st_size > 0
    before = hs.ledger_snapshot(state)
    assert error_code(operator.cli("inspect", operator.sel(name), expected=2, state=state)) == "handoff_recovery_required"     # readers still refuse a hot WAL
    assert hs.ledger_snapshot(state) == before
    settled = operator.cli("recover", operator.sel(name), state=state)
    assert settled["state"] == final and settled["attempts"][-1]["kind"] == "recover", settled
    if final == "ready":
        assert operator.cli("export", operator.sel(name), state=state)["bundle"]["handoffId"] == name
    else:
        assert settled["failure"] == {"code": "handoff_artifact_missing"}
