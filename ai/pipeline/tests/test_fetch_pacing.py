"""Shared SQLite dispatch timing with synthetic clocks and real processes; no HTTP."""
from __future__ import annotations

import multiprocessing
import sqlite3
import time
from types import SimpleNamespace

import pytest

from zoop_ai_pipeline import fetch_pacing
from zoop_ai_pipeline.fetch_pacing import SharedFetchPacer
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure


class Clock:
    def __init__(self):
        self.value = 1000.0
        self.waits = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(fetch_pacing, "time", SimpleNamespace(monotonic=value.monotonic, sleep=value.sleep))
    return value


def acquire(pacer, url="https://news.example/article", spacing=0, *, earliest=0, deadline=2000):
    return pacer.acquire(url, min_interval_seconds=spacing, not_before_monotonic=earliest, deadline_monotonic=deadline)


def test_twenty_sixth_dispatch_waits_for_shared_account_window_across_origins(tmp_path, clock):
    times = [acquire(SharedFetchPacer(tmp_path), f"https://source{i}.example/article") for i in range(26)]
    assert times[:25] == [1000.0] * 25
    assert times[25] > 1001.0
    assert len(clock.waits) == 1
    for at in times:
        assert sum(at <= other <= at + 1.0 for other in times) <= 25


def test_per_origin_spacing_preserves_stricter_robots_delay_without_blocking_other_origins(tmp_path, clock):
    pacer = SharedFetchPacer(tmp_path)
    assert acquire(pacer, spacing=2) == 1000
    assert acquire(pacer, "https://other.example/article", spacing=2) == 1000
    assert acquire(pacer, spacing=7) == 1007
    assert acquire(SharedFetchPacer(tmp_path), spacing=2) == 1014
    assert clock.waits == [7, 7]


def test_prior_native_request_paces_first_provider_call_and_resume_keeps_slot(tmp_path, clock):
    assert acquire(SharedFetchPacer(tmp_path), spacing=2, earliest=1006) == 1006
    assert acquire(SharedFetchPacer(tmp_path), spacing=2) == 1008
    assert clock.waits == [6, 2]


def test_pacing_deadline_never_records_a_dispatch_or_sleeps_beyond_deadline(tmp_path, clock):
    pacer = SharedFetchPacer(tmp_path)
    with pytest.raises(IngestionFailure, match="fetch_pacing_deadline"):
        acquire(pacer, spacing=10, earliest=1010, deadline=1005)
    assert clock.waits == []
    with sqlite3.connect(pacer.path) as db:
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        assert tables == []
    assert acquire(pacer, deadline=1005) == 1000


def test_account_capacity_is_not_reset_when_reopening_after_an_unsent_process_exit(tmp_path, clock):
    for i in range(25):
        acquire(SharedFetchPacer(tmp_path), f"https://source{i}.example/article")
    # There is deliberately no release method: a crash after admission wastes the slot.
    assert acquire(SharedFetchPacer(tmp_path), "https://new.example/article") > 1001


def test_monotonic_clock_regression_and_profile_mismatch_fail_closed(tmp_path, clock):
    pacer = SharedFetchPacer(tmp_path)
    acquire(pacer)
    clock.value = 999
    with pytest.raises(IngestionFailure, match="fetch_pacing_clock_regressed"):
        acquire(pacer)
    clock.value = 1001
    with sqlite3.connect(pacer.path) as db:
        db.execute("UPDATE profile SET value='unknown-profile'")
    with pytest.raises(IngestionFailure, match="fetch_pacing_profile_mismatch"):
        acquire(pacer)


@pytest.mark.parametrize("spacing", [float("nan"), float("inf"), -1, True])
def test_invalid_spacing_cannot_disable_the_limiter(tmp_path, clock, spacing):
    with pytest.raises(IngestionFailure, match="fetch_pacing_invalid"):
        acquire(SharedFetchPacer(tmp_path), spacing=spacing)
    assert not (tmp_path / fetch_pacing.DB_NAME).exists()


def _dispatch_worker(directory, barrier, output, index, count, spacing, same_origin):
    try:
        pacer = SharedFetchPacer(directory)
        barrier.wait(timeout=10)
        url = "https://news.example/article" if same_origin else f"https://source{index}.example/article"
        stamps = [pacer.acquire(url, min_interval_seconds=spacing, deadline_monotonic=time.monotonic() + 10)
                  for _ in range(count)]
        output.put(("ok", stamps))
    except Exception as exc:
        output.put(("error", type(exc).__name__ + ": " + str(exc)))


def _multiprocess_dispatches(directory, workers, count, spacing, same_origin):
    context = multiprocessing.get_context("spawn")
    barrier, output = context.Barrier(workers), context.Queue()
    processes = [context.Process(target=_dispatch_worker, args=(directory, barrier, output, i, count, spacing, same_origin))
                 for i in range(workers)]
    try:
        for process in processes:
            process.start()
        results = [output.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)
            assert process.exitcode == 0
        assert all(status == "ok" for status, _ in results), results
        return sorted(stamp for _, stamps in results for stamp in stamps)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        output.close()
        output.join_thread()


def test_real_processes_share_the_same_twenty_five_qps_account_window(tmp_path):
    stamps = _multiprocess_dispatches(str(tmp_path), workers=4, count=8, spacing=0, same_origin=False)
    assert len(stamps) == 32
    assert stamps[25] - stamps[0] > 1.0
    for at in stamps:
        assert sum(at <= other <= at + 1.0 for other in stamps) <= 25


def test_real_processes_cannot_skip_spacing_for_the_same_origin(tmp_path):
    stamps = _multiprocess_dispatches(str(tmp_path), workers=3, count=2, spacing=0.04, same_origin=True)
    assert len(stamps) == 6
    assert all(later - earlier >= 0.04 for earlier, later in zip(stamps, stamps[1:]))
