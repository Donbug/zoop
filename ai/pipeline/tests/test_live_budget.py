"""Shared live USD/call budget: unique attempts, ceilings, conservative accounting, concurrency and process death (offline)."""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from zoop_ai_pipeline.live_budget import DB_NAME, NANO, Budget, BudgetError, nano_from_usd, usd

PIPELINE = Path(__file__).resolve().parents[1]


def budget(tmp_path: Path, usd_cap: str = "1", calls: int = 10) -> Budget:
    return Budget(tmp_path / "budget", nano_from_usd(usd_cap), calls)


def reserve(b: Budget, attempt: str, nano: int = 100_000) -> None:
    b.reserve(attempt, "extract", "openai-compatible:r", "d" * 64, nano)


def code_of(call) -> str:
    with pytest.raises(BudgetError) as caught:
        call()
    return caught.value.code


def test_usd_parsing_is_exact_and_refuses_anything_that_is_not_a_positive_plain_decimal():
    assert nano_from_usd("10") == 10 * NANO and nano_from_usd("0.000000001") == 1 and nano_from_usd(" 2.5 ") == 2_500_000_000
    assert usd(575_000) == "0.000575000" and usd(10 * NANO) == "10.000000000"
    for bad in ("", "0", "-1", "1e3", "1.0000000001", "abc", "１", "1.", ".5", "1,5", "NaN", "9999999"):
        with pytest.raises(ValueError):
            nano_from_usd(bad)


def test_a_new_budget_directory_is_private_and_an_attempt_id_can_never_be_reserved_twice(tmp_path):
    b = budget(tmp_path)
    reserve(b, "a-1")
    assert (tmp_path / "budget").stat().st_mode & 0o777 == 0o700 and (tmp_path / "budget" / DB_NAME).stat().st_mode & 0o777 == 0o600
    assert code_of(lambda: reserve(b, "a-1")) == "live_budget_attempt_duplicate"
    b.release("a-1")
    assert code_of(lambda: reserve(b, "a-1")) == "live_budget_attempt_duplicate", "a released attempt id is spent: it can never be resent"


def test_usd_and_call_ceilings_refuse_before_any_charge(tmp_path):
    b = budget(tmp_path, "0.0003", calls=2)
    reserve(b, "a-1", 100_000)
    reserve(b, "a-2", 100_000)
    assert code_of(lambda: reserve(b, "a-3", 100_000)) == "live_budget_exhausted_calls"
    b = Budget(tmp_path / "other", nano_from_usd("0.0003"), 10)
    reserve(b, "b-1", 200_000)
    assert code_of(lambda: reserve(b, "b-2", 200_000)) == "live_budget_exhausted_usd"
    assert b.snapshot()["calls"] == 1 and b.snapshot()["chargedUsd"] == "0.000200000"


def test_settlement_replaces_the_worst_case_only_with_known_usage_and_never_below_nothing_known(tmp_path):
    b = budget(tmp_path)
    reserve(b, "known", 900_000)
    reserve(b, "unknown", 900_000)
    assert b.settle("known", 575_000) == 575_000
    assert b.settle("unknown", None) == 900_000, "missing usage keeps the worst-case charge"
    assert b.snapshot()["chargedUsd"] == "0.001475000"
    assert code_of(lambda: b.settle("known", 1)) == "live_budget_unavailable", "a settled attempt cannot be settled again"


def test_an_actual_above_the_reservation_is_recorded_not_hidden(tmp_path):
    b = budget(tmp_path)
    reserve(b, "over", 100)
    assert b.settle("over", 5_000) == 5_000 and b.snapshot()["chargedUsd"] == "0.000005000"


def test_a_released_reservation_is_free_and_not_counted_as_a_call_but_a_settled_one_cannot_be_released(tmp_path):
    b = budget(tmp_path, calls=1)
    reserve(b, "a-1")
    b.release("a-1")
    assert b.snapshot()["calls"] == 0 and b.snapshot()["chargedUsd"] == "0.000000000"
    reserve(b, "a-2")
    b.settle("a-2", 10)
    b.release("a-2")
    assert b.snapshot()["calls"] == 1 and b.snapshot()["states"] == {"released": 1, "settled": 1}


def test_ceilings_bind_on_first_use_may_decrease_and_never_increase(tmp_path):
    reserve(budget(tmp_path, "1", 10), "a-1")
    assert code_of(lambda: reserve(budget(tmp_path, "2", 10), "a-2")) == "live_budget_ceiling_increase"
    assert code_of(lambda: reserve(budget(tmp_path, "1", 11), "a-2")) == "live_budget_ceiling_increase"
    lower = budget(tmp_path, "0.5", 3)
    reserve(lower, "a-2")
    assert lower.snapshot()["maxUsd"] == "0.500000000" and lower.snapshot()["maxCalls"] == 3
    assert code_of(lambda: reserve(budget(tmp_path, "1", 10), "a-3")) == "live_budget_ceiling_increase", "a decrease is permanent"


def test_concurrent_reservations_from_many_threads_and_handles_never_overspend_the_calls_ceiling(tmp_path):
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        try:
            reserve(budget(tmp_path, "1", 5), f"t-{index}")
            result = "ok"
        except BudgetError as exc:
            result = exc.code
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 5 and outcomes.count("live_budget_exhausted_calls") == 19


def test_concurrent_reservations_never_overspend_the_usd_ceiling(tmp_path):
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        try:
            reserve(budget(tmp_path, "0.001", 1000), f"u-{index}", 300_000)  # 0.0003 USD each: three fit
            result = "ok"
        except BudgetError as exc:
            result = exc.code
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 3 and outcomes.count("live_budget_exhausted_usd") == 13


def test_a_process_that_dies_after_reserving_leaves_the_worst_case_charged_and_the_attempt_unusable(tmp_path):
    code = (f"import os\nfrom pathlib import Path\nfrom zoop_ai_pipeline.live_budget import Budget\n"
            f"Budget(Path({str(tmp_path / 'budget')!r}), 1_000_000_000, 4).reserve('dead-1','verify-relation','typesafe-native:r','d'*64, 700_000)\n"
            f"os._exit(9)")
    child = subprocess.run([sys.executable, "-B", "-c", code], cwd=PIPELINE, capture_output=True, timeout=60)
    assert child.returncode == 9, child.stderr.decode()
    b = budget(tmp_path, "1", 4)
    snapshot = b.snapshot()
    assert snapshot["calls"] == 1 and snapshot["chargedUsd"] == "0.000700000" and snapshot["states"] == {"reserved": 1}
    assert code_of(lambda: reserve(b, "dead-1")) == "live_budget_attempt_duplicate"


def test_an_unusable_budget_location_is_a_budget_error_not_a_crash(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert code_of(lambda: reserve(Budget(blocker / "inside", NANO, 1), "a-1")) == "live_budget_unavailable"


def test_a_lowered_ceiling_persists_even_when_the_same_reserve_is_denied(tmp_path):
    reserve(budget(tmp_path, "1", 10), "a-1", 400_000)
    lowered = budget(tmp_path, "0.0003", 10)
    assert code_of(lambda: reserve(lowered, "a-2", 100_000)) == "live_budget_exhausted_usd", "0.0004 already charged against the lowered 0.0003"
    # the refusal must not roll the decrease back: the original, higher handle is now an increase and is refused as one
    assert code_of(lambda: reserve(budget(tmp_path, "1", 10), "a-3", 1)) == "live_budget_ceiling_increase"
    assert budget(tmp_path, "0.0003", 10).snapshot()["maxUsd"] == "0.000300000"
    calls = budget(tmp_path, "0.0003", 1)
    assert code_of(lambda: reserve(calls, "a-4", 1)) == "live_budget_exhausted_calls"
    assert budget(tmp_path, "0.0003", 1).snapshot()["maxCalls"] == 1 and code_of(lambda: reserve(budget(tmp_path, "0.0003", 10), "a-5", 1)) == "live_budget_ceiling_increase"


def test_a_decrease_is_kept_even_when_the_other_ceiling_is_an_increase_attempt(tmp_path):
    reserve(budget(tmp_path, "1", 10), "a-1")
    assert code_of(lambda: reserve(budget(tmp_path, "0.5", 20), "a-2")) == "live_budget_ceiling_increase"
    stored = budget(tmp_path, "0.5", 10).snapshot()
    assert stored["maxUsd"] == "0.500000000" and stored["maxCalls"] == 10 and stored["calls"] == 1, "the refusal added no reservation"


def test_racing_handles_with_different_ceilings_converge_on_the_lowest_and_never_exceed_it(tmp_path):
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt(index: int) -> None:
        ceiling = 3 if index % 4 == 0 else 8
        try:
            reserve(budget(tmp_path, "1", ceiling), f"r-{index}")
            result = "ok"
        except BudgetError as exc:
            result = exc.code
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stored = budget(tmp_path, "1", 3).snapshot()
    assert stored["maxCalls"] == 3, "the lowest requested ceiling won the race, whatever order the handles arrived in"
    assert stored["calls"] == outcomes.count("ok") <= 8 and set(outcomes) <= {"ok", "live_budget_exhausted_calls", "live_budget_ceiling_increase"}
    assert code_of(lambda: reserve(budget(tmp_path, "1", 8), "late", 1)) == "live_budget_ceiling_increase"
