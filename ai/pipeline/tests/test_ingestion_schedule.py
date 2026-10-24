"""Round controller behavior through the real `zoop-ai-ingest tick` process: latest due slot, one round per slot, no hidden retry."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from scripts.ingestion_smoke import HTML, PIPELINE, OfflineFixture, json_bytes, ownership_env
from zoop_ai_pipeline.ingestion import Store
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, Tick
from zoop_ai_pipeline.ingestion_schedule import KST, catch_up, clock, latest_slot, round_id, slot_text

DAY = "2026-10-17"  # a Saturday: every calendar day runs
NO_NETWORK = "import socket\ndef _deny(*a, **k):\n raise OSError('network forbidden')\nsocket.socket.connect = _deny\nsocket.create_connection = _deny\n"
CRASH = {"receipt": "Ingestor._discover=lambda *a: os._exit(75)",
         "raw": "parsers.prepare=lambda *a: os._exit(75)",
         "checkpoint": "original=Ingestor._complete_page\ndef stop(*a):\n original(*a)\n os._exit(75)\nIngestor._complete_page=stop"}


@pytest.fixture
def kit(tmp_path):
    return OfflineFixture(tmp_path / "owned")


def at(hhmm, day=DAY, seconds="00"):
    return f"{day}T{hhmm}:{seconds}+09:00"


def tick_body(now=None, initial=None):
    body = {"schemaVersion": "zoop-ingestion-s2-1", "sourceId": "synthetic-source", "scopeId": "body"}
    if now:
        body["now"] = now
    if initial:
        body["initialFrom"] = initial
    return body


def covered(kit, name, slot_hhmm, items=(), day=DAY, **kwargs):
    """A manifest whose terminal page covers exactly the given slot."""
    return kit.manifest(name, [list(items)], coverage=at(slot_hhmm, day), **kwargs)


def tick(kit, body, *, manifest=None, state="state", expected=0, crash=None, sources=None, extra=()):
    """The actual CLI in a child process with every socket connect denied; optional crash hook kills the process at a durable stage."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(os.path.expanduser("~")), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", **ownership_env()}
    hook = CRASH[crash] if crash else ""
    code = NO_NETWORK + "import os\nfrom zoop_ai_pipeline.ingestion import Ingestor, parsers\nfrom zoop_ai_pipeline.ingestion_cli import main\n" + hook + "\nraise SystemExit(main())"
    argv = [sys.executable, "-c", code, "tick", "--state-dir", str(kit.root / state), "--sources", str(sources or kit.registry_path)]
    if manifest:
        argv += ["--fixture-manifest", str(manifest)]
    child = subprocess.run([*argv, *extra], input=json_bytes(body), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=60)
    assert child.returncode == expected or (expected is None and child.returncode in {0, 3}), (child.returncode, child.stdout.decode(), child.stderr.decode())
    return json.loads(child.stdout) if child.stdout else None


def resume_cli(kit, rid):
    """The explicit operator `resume` command (the only way to retry a terminal round)."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.path.expanduser("~"), **ownership_env()}
    child = subprocess.run([sys.executable, "-m", "zoop_ai_pipeline.ingestion_cli", "resume", "--state-dir", str(kit.root / "state"), "--sources", str(kit.registry_path)],
        input=json_bytes({"schemaVersion": "zoop-ingestion-s2-1", "roundId": rid, "sourceId": "synthetic-source"}), stdout=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=60)
    assert child.returncode == 0, child.stdout.decode()
    return json.loads(child.stdout)


def rows(kit, sql, state="state"):
    db = sqlite3.connect(kit.root / state / "ingestion.sqlite3")
    try:
        return db.execute(sql).fetchall()
    finally:
        db.close()


@pytest.mark.parametrize("now,slot,reason", [
    ("2026-10-17T08:59:59+09:00", None, "outside_operating_window"),
    ("2026-10-17T09:00:00+09:00", None, "before_first_slot"),
    ("2026-10-17T09:04:59+09:00", None, "before_first_slot"),
    ("2026-10-17T09:05:00+09:00", "2026-10-17T09:05:00+09:00", None),
    ("2026-10-17T09:20:00+09:00", "2026-10-17T09:05:00+09:00", None),
    ("2026-10-17T09:34:59+09:00", "2026-10-17T09:05:00+09:00", None),
    ("2026-10-17T10:04:00+09:00", "2026-10-17T09:35:00+09:00", None),
    ("2026-10-17T17:59:59+09:00", "2026-10-17T17:35:00+09:00", None),
    ("2026-10-17T18:00:00+09:00", None, "outside_operating_window"),
    ("2026-10-17T00:05:00+00:00", "2026-10-17T09:05:00+09:00", None),        # UTC instant, KST slot
    ("2026-10-16T23:59:00+00:00", None, "outside_operating_window"),         # 08:59 KST the next day
    ("2026-10-18T10:04:00+09:00", "2026-10-18T09:35:00+09:00", None),        # Sunday
    ("2026-10-16T18:04:00-07:00", "2026-10-17T09:35:00+09:00", None),        # other offset, same instant
    ("2026-10-17T02:04:00-07:00", None, "outside_operating_window"),         # 18:04 KST
])
def test_latest_due_slot_table(now, slot, reason):
    found, why = latest_slot(datetime.fromisoformat(now))
    assert (found and slot_text(found), why) == (slot, reason)


def test_round_id_is_bounded_hashed_and_slot_specific():
    slot = datetime.fromisoformat("2026-10-17T09:35:00+09:00")
    long_id = round_id("s" * 200, "x" * 200, slot)
    assert len(long_id) == len("slot-") + 64 and long_id == round_id("s" * 200, "x" * 200, slot)
    assert long_id != round_id("s" * 200, "x" * 200, slot + timedelta(minutes=30)) != round_id("s" * 200, "y" * 200, slot)
    assert slot_text(slot.astimezone(UTC)) == "2026-10-17T09:35:00+09:00"


def test_catch_up_only_beyond_thirty_minutes():
    slot = datetime.fromisoformat("2026-10-17T09:35:00+09:00")
    assert not catch_up(slot - timedelta(minutes=5), slot) and not catch_up(slot - timedelta(minutes=30), slot)
    assert catch_up(slot - timedelta(minutes=30, seconds=1), slot)
    assert catch_up(datetime.fromisoformat("2026-10-16T17:35:00+09:00"), datetime.fromisoformat("2026-10-17T09:05:00+09:00"))


def test_clock_rejects_the_future_and_naive_time():
    actual = datetime(2026, 10, 17, tzinfo=UTC)
    base = {"schemaVersion": "zoop-ingestion-s2-1", "sourceId": "a", "scopeId": "b"}
    assert clock(Tick.model_validate({**base, "now": "2026-10-17T00:00:00+00:00"}), actual) == actual
    with pytest.raises(IngestionFailure) as future:
        clock(Tick.model_validate({**base, "now": "2026-10-17T00:00:01+00:00"}), actual)
    assert future.value.code == "clock_in_future"
    with pytest.raises(ValueError):
        Tick.model_validate({**base, "now": "2026-10-17T00:00:00"})


def test_not_due_reads_and_creates_nothing(kit, tmp_path):
    for now, reason in ((at("09:04", seconds="59"), "before_first_slot"), (at("18:00"), "outside_operating_window")):
        out = tick(kit, tick_body(now), state="never-created", sources=tmp_path / "no-registry.json", manifest=tmp_path / "no-manifest.json")
        assert out == {"schemaVersion": "zoop-ingestion-s2-1", "round": None, "tick": {"action": "not-due", "at": now, "slot": None, "roundId": None, "reason": reason, "catchUp": None}}
    assert not (kit.root / "never-created").exists()


def test_future_clock_is_denied_without_state(kit):
    future = (datetime.now(UTC) + timedelta(days=1)).astimezone(KST).isoformat()
    out = tick(kit, tick_body(future), expected=2)
    assert out["error"]["code"] == "clock_in_future" and not (kit.root / "state").exists()


def test_default_clock_follows_actual_kst_without_waiting(kit):
    def expected():
        return latest_slot(datetime.now(UTC))[0] is None
    before = expected()
    out = tick(kit, tick_body(initial="2026-10-01T00:00:00+09:00"), manifest=covered(kit, "any", "09:05"), expected=None)
    if before == expected():
        assert (out["tick"]["action"] == "not-due") == before
    assert out["tick"]["action"] in {"not-due", "started"}


def test_first_slot_needs_explicit_baseline_and_the_window_is_a_catch_up(kit):
    m = covered(kit, "first", "09:35", [kit.item()])
    assert tick(kit, tick_body(at("10:04")), manifest=m, expected=2)["error"]["code"] == "initial_baseline_required"
    assert tick(kit, tick_body(at("10:04"), initial=at("09:35")), manifest=m, expected=2)["error"]["code"] == "slot_not_after_baseline"
    assert tick(kit, tick_body(at("10:04"), initial=at("09:00")), expected=2)["error"]["code"] == "fixture_manifest_required"
    out = tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=m)
    assert out["tick"] == {"action": "started", "at": at("10:04"), "slot": at("09:35"), "roundId": round_id("synthetic-source", "body", datetime.fromisoformat(at("09:35"))), "reason": None, "catchUp": True}
    assert out["round"]["state"] == "complete" and out["round"]["checkedWindow"] == {"from": at("09:00"), "through": at("09:35")}
    assert out["round"]["checkpoint"]["through"] == at("09:35") and out["round"]["counts"]["newTextVersions"] == 1


def test_explicit_five_minute_baseline_is_not_a_catch_up(kit):
    out = tick(kit, tick_body(at("10:04"), initial=at("09:30")), manifest=covered(kit, "short", "09:35"))
    assert out["tick"]["catchUp"] is False and out["round"]["state"] == "complete"


def test_same_slot_replay_is_frozen_and_never_runs_again(kit):
    m = covered(kit, "one", "09:35", [kit.item()])
    first = tick(kit, tick_body(at("10:00"), initial=at("09:00")), manifest=m)
    again = tick(kit, tick_body(at("10:04")), manifest=m)
    assert again["tick"]["action"] == "replayed" and again["round"] == first["round"] and again["tick"]["catchUp"] is True
    assert tick(kit, tick_body(at("10:04")))["round"] == first["round"]   # no manifest needed to replay
    assert tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=m)["tick"]["action"] == "replayed"
    assert rows(kit, "SELECT COUNT(*) FROM rounds") == [(1,)]


def test_same_slot_inputs_that_differ_from_the_stored_round_conflict(kit):
    m = covered(kit, "frozen", "09:35", [kit.item()])
    tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=m)
    other = covered(kit, "other", "09:35", [], bodies={"html": HTML + b" "})
    assert tick(kit, tick_body(at("10:04")), manifest=other, expected=2)["error"]["code"] == "slot_input_conflict"
    assert tick(kit, tick_body(at("10:04"), initial=at("09:01")), manifest=m, expected=2)["error"]["code"] == "slot_input_conflict"
    assert rows(kit, "SELECT COUNT(*) FROM rounds") == [(1,)]


def test_next_slot_covers_the_whole_gap_and_dedupes_across_rounds(kit):
    first = tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=covered(kit, "a", "09:35", [kit.item()]))
    changed = HTML.replace("둘째".encode(), "셋째".encode())
    # Slots 10:05..12:35 were never ticked; the 12:40 reading takes only the latest slot 12:35 and covers 09:35 -> 12:35.
    second = tick(kit, tick_body(at("12:40")), manifest=covered(kit, "b", "12:35", [kit.item(), kit.item("c2", "supplier-2", "https://example.invalid/other", ref="new")], bodies={"html": HTML, "new": changed}))
    assert second["tick"]["slot"] == at("12:35") and second["tick"]["catchUp"] is True and second["tick"]["action"] == "started"
    assert second["round"]["checkedWindow"] == {"from": at("09:35"), "through": at("12:35")} and second["round"]["checkpoint"]["revision"] == 2
    assert second["round"]["counts"]["reusedVersions"] == 1 and second["round"]["counts"]["newTextVersions"] == 1
    assert second["round"]["documentRefs"][0]["documentVersion"] == first["round"]["documentRefs"][0]["documentVersion"]
    third = tick(kit, tick_body(at("13:10")), manifest=covered(kit, "c", "13:05"))
    assert third["tick"]["catchUp"] is False and third["round"]["checkedWindow"]["from"] == at("12:35")


def test_zero_new_covered_round_advances_and_failed_or_partial_does_not(kit):
    zero = tick(kit, tick_body(at("09:20"), initial=at("09:00")), manifest=covered(kit, "zero", "09:05"))
    assert zero["round"]["completion"] == "source-zero" and zero["round"]["checkpoint"]["through"] == at("09:05")
    for name, status in (("failed", "failed"), ("partial", "partial")):
        state = "state-" + name
        out = tick(kit, tick_body(at("09:50"), initial=at("09:00")), state=state, manifest=kit.manifest(name, [[kit.item()]], statuses=[status]), expected=3)
        assert out["round"]["state"] == "incomplete" and out["round"]["checkpoint"]["through"] is None and out["round"]["failure"]["code"] == "discovery_page_" + status
        replay = tick(kit, tick_body(at("09:50")), state=state, expected=3)
        assert replay["tick"]["action"] == "replayed" and replay["round"] == out["round"]
    # After an incomplete slot the next slot restarts from the explicit baseline and covers the whole gap.
    retry = tick(kit, tick_body(at("10:20"), initial=at("09:00")), state="state-failed", manifest=covered(kit, "later", "10:05", [kit.item()]))
    assert retry["round"]["state"] == "complete" and retry["round"]["checkedWindow"]["from"] == at("09:00")


def test_collected_style_incomplete_exit_is_honest_when_coverage_is_missing(kit):
    out = tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=kit.manifest("nocoverage", [[kit.item()]]), expected=3)
    assert out["round"]["state"] == "incomplete" and out["round"]["failure"]["code"] == "coverage_incomplete" and out["round"]["checkpoint"]["through"] is None


def test_checkpoint_baseline_cannot_be_overridden_by_initial_from(kit):
    tick(kit, tick_body(at("09:20"), initial=at("09:00")), manifest=covered(kit, "a", "09:05"))
    assert tick(kit, tick_body(at("09:50"), initial=at("09:00")), manifest=covered(kit, "b", "09:35"), expected=2)["error"]["code"] == "initial_baseline_conflict"
    assert tick(kit, tick_body(at("09:20")))["tick"]["action"] == "replayed"


@pytest.mark.parametrize("crash", ["receipt", "raw"])
def test_crashed_running_slot_is_recovered_once_without_duplicates(kit, crash):
    m = covered(kit, "crash", "09:35", [kit.item()])
    tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=m, crash=crash, expected=75)
    assert rows(kit, "SELECT state FROM rounds") == [("running",)]
    recovered = tick(kit, tick_body(at("10:04")), manifest=m)
    assert recovered["tick"]["action"] == "recovered" and recovered["round"]["state"] == "complete" and recovered["round"]["counts"]["newTextVersions"] == 1
    assert rows(kit, "SELECT COUNT(*) FROM rounds") == [(1,)] and rows(kit, "SELECT COUNT(*) FROM candidates") == [(1,)] and rows(kit, "SELECT COUNT(*) FROM versions") == [(1,)]
    assert tick(kit, tick_body(at("10:04")))["tick"]["action"] == "replayed"


def test_old_running_slot_is_not_resumed_automatically_and_explicit_resume_is_stale(kit):
    two_pages = kit.manifest("two", [[kit.item()], [kit.item("c2", "supplier-2", ref="later")]], bodies={"html": HTML, "later": HTML.replace("둘째".encode(), "넷째".encode())}, coverage=at("09:35"))
    tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=two_pages, crash="checkpoint", expected=75)
    assert rows(kit, "SELECT state FROM rounds") == [("running",)]
    # Page one committed (revision 1, through unchanged), so the next slot starts from the stored baseline revision.
    nxt = tick(kit, tick_body(at("10:40"), initial=at("09:00")), manifest=covered(kit, "next", "10:35"))
    assert nxt["tick"]["action"] == "started" and nxt["round"]["state"] == "complete" and nxt["round"]["checkpoint"]["revision"] == 2
    old = round_id("synthetic-source", "body", datetime.fromisoformat(at("09:35")))
    assert dict(rows(kit, "SELECT id, state FROM rounds"))[old] == "running"
    assert resume_cli(kit, old)["failure"]["code"] == "checkpoint_stale"


def test_concurrent_tick_is_busy_while_the_store_lock_is_held(kit):
    holder = Store(kit.root / "state")
    try:
        assert tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=covered(kit, "busy", "09:35"), expected=2)["error"]["code"] == "ingestion_busy"
    finally:
        holder.close()
    assert tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=covered(kit, "busy", "09:35"))["tick"]["action"] == "started"


def test_revoked_grant_denies_due_slot_but_not_a_slot_that_is_not_due(kit):
    m = covered(kit, "revoked", "09:35", [kit.item()])
    tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=m)
    kit.registry["sources"][0]["grant"]["enabled"] = False
    kit.save_registry()
    assert tick(kit, tick_body(at("10:04")), manifest=m, expected=2)["error"]["code"] == "source_unauthorized"
    assert tick(kit, tick_body(at("10:40")), manifest=covered(kit, "later", "10:35"), expected=2)["error"]["code"] == "source_unauthorized"
    assert tick(kit, tick_body(at("18:30")))["tick"]["action"] == "not-due"
    assert rows(kit, "SELECT COUNT(*) FROM rounds") == [(1,)]


def test_require_store_is_still_export_only(kit):
    assert tick(kit, tick_body(at("18:30")), extra=("--require-store",), expected=2)["error"]["code"] == "require_store_not_allowed"


@pytest.mark.parametrize("change", ["selection", "articleXPath"])
def test_changed_scope_configuration_denies_recovery_without_mutating_then_restores(kit, change):
    m = covered(kit, "config", "09:35", [kit.item()])
    tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=m, crash="raw", expected=75)
    snapshot = lambda: (rows(kit, "SELECT * FROM rounds"), rows(kit, "SELECT * FROM scopes"), rows(kit, "SELECT COUNT(*) FROM pages"))
    before = snapshot()
    scope = kit.registry["sources"][0]["scopes"][0]
    original = scope[change]
    scope[change] = "changed selection" if change == "selection" else "//article"
    kit.save_registry()
    assert tick(kit, tick_body(at("10:04")), manifest=m, expected=2)["error"]["code"] == "scope_configuration_conflict"
    assert snapshot() == before and before[0][0][rows(kit, "SELECT name FROM pragma_table_info('rounds')").index(("state",))] == "running"
    scope[change] = original
    kit.save_registry()
    recovered = tick(kit, tick_body(at("10:04")), manifest=m)
    assert recovered["tick"]["action"] == "recovered" and recovered["round"]["state"] == "complete"


def test_incomplete_missing_body_stays_incomplete_on_tick_and_only_explicit_resume_retries(kit):
    m = covered(kit, "gap", "09:35", [kit.item()])
    body = kit.inputs / json.loads(m.read_bytes())["documents"]["html"]["file"]
    raw = body.read_bytes()
    body.unlink()
    first = tick(kit, tick_body(at("10:04"), initial=at("09:00")), manifest=m, expected=3)
    assert first["round"]["state"] == "incomplete" and first["round"]["failure"]["code"] == "persistence_or_input_failed"
    body.write_bytes(raw)
    again = tick(kit, tick_body(at("10:04")), manifest=m, expected=3)
    assert again["tick"]["action"] == "replayed" and again["round"] == first["round"]
    assert rows(kit, "SELECT COUNT(*) FROM versions") == [(0,)]
    resumed = resume_cli(kit, first["tick"]["roundId"])
    assert resumed["state"] == "complete" and resumed["counts"]["newTextVersions"] == 1
    done = tick(kit, tick_body(at("10:04")))
    assert done["tick"]["action"] == "replayed" and done["round"]["state"] == "complete"
