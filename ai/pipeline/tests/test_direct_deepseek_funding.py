"""Direct generation/tool funding uses the existing SQLite authority, not a second budget."""
from __future__ import annotations

import threading

import pytest

from zoop_ai_pipeline import live_budget, live_funding
from zoop_ai_pipeline.live_budget import Budget, BudgetError, NANO
from zoop_ai_pipeline.relation_contracts import digest

START, END = "2026-10-28T00:15:00Z", "2026-10-28T08:30:00Z"
TOOL_REQUEST_NANO = 750_000


def authority(tmp_path):
    return Budget(tmp_path / "budget", 20 * NANO, 100,
                  funding=live_funding.set_funding_policy("direct-fallback-test", START, END))


def plan():
    return dict.fromkeys(live_funding.GENERATION_STAGES + live_funding.VERIFY_STAGES + live_funding.ACQUISITION_STAGES, 2)


def reserve(budget, attempt, role, amount, *, set_id="set-one", stage=None):
    route = budget.funding["roles"][role]
    stage = stage or route["stages"][0]
    recipient = route.get("stageRecipients", {}).get(stage, route["recipient"])
    budget.reserve(attempt, stage, recipient, digest(attempt), amount, account_role=role, set_id=set_id)


@pytest.fixture(autouse=True)
def before_cutoff(monkeypatch):
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:29:59+00:00")


def test_concurrent_direct_and_jev_reservations_share_one_ten_dollar_personal_cap(tmp_path):
    budget = authority(tmp_path)
    budget.admit_set("set-one", digest("original-input"), plan())
    reserve(budget, "primary-charge", "shared-openai", 9 * NANO)
    for i in range(24):
        budget.admit_set(f"personal-{i}", digest(i), plan())
    barrier, lock, outcomes = threading.Barrier(24), threading.Lock(), []

    def work(i):
        role = "personal-deepseek" if i % 2 else "personal-typesafe"
        barrier.wait()
        try:
            reserve(authority(tmp_path), f"attempt-{i}", role, 3 * NANO, set_id=f"personal-{i}")
            outcome = "reserved"
        except BudgetError as error:
            outcome = error.code
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    snapshot = authority(tmp_path).snapshot()
    assert len(outcomes) == 24
    assert outcomes.count("reserved") == 3
    assert snapshot["calls"] == 4 and snapshot["chargedUsd"] == "18.000000000"
    assert snapshot["buckets"]["shared"]["chargedUsd"] == "9.000000000"
    assert snapshot["buckets"]["personal"]["chargedUsd"] == "9.000000000"
    # The next $3 exceeds both caps; the ledger checks the global $20 cap first.
    assert set(outcomes) <= {"reserved", "live_budget_exhausted_usd", "live_budget_exhausted_personal",
                             "live_budget_verification_blocked"}


def test_fetch_search_unknown_and_generation_compete_with_required_verification(tmp_path):
    budget = authority(tmp_path)
    budget.admit_set("set-one", digest("original-input"), plan())
    reserve(budget, "verifier-work", "personal-typesafe", 9_997_500_000)
    budget.settle("verifier-work", 9_997_500_000)
    reserve(budget, "fetch-success", "personal-deepseek", TOOL_REQUEST_NANO, stage="fetch")
    budget.settle("fetch-success", TOOL_REQUEST_NANO)
    reserve(budget, "search-unknown", "personal-deepseek", TOOL_REQUEST_NANO, stage="search")
    with pytest.raises(BudgetError, match="live_budget_verification_blocked"):
        reserve(budget, "generation-would-steal-verifier-reserve", "personal-deepseek", 1)
    # The finite reserve remains spendable by verification, not by unlimited generation/tools.
    reserve(budget, "required-verification", "personal-typesafe", 1_000_000)
    snapshot = budget.snapshot()
    assert snapshot["buckets"]["personal"]["chargedUsd"] == "10.000000000"
    assert snapshot["buckets"]["personal"]["reservedUsd"] == "0.001750000"
    assert snapshot["buckets"]["shared"]["chargedUsd"] == "0.000000000"
    with pytest.raises(BudgetError, match="live_budget_exhausted_personal"):
        reserve(budget, "no-unbounded-verifier-fanout", "personal-typesafe", 1, stage="verify-impact")


def test_same_admitted_set_can_reserve_distinct_provider_after_cutoff_without_new_set(tmp_path, monkeypatch):
    budget = authority(tmp_path)
    original_input = digest("original-input")
    budget.admit_set("set-one", original_input, plan())
    reserve(budget, "primary-invalid", "shared-openai", 1_000_000)
    budget.settle("primary-invalid", 700_000)
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:30:01+00:00")
    reserve(authority(tmp_path), "successor", "personal-deepseek", 1_000_000)
    budget.check_send("successor")
    budget.settle("successor", 900_000)
    assert budget.resume_set("set-one", original_input) == plan()
    with pytest.raises(BudgetError, match="live_set_admission_closed"):
        budget.admit_set("hidden-replacement", original_input, plan())
    with pytest.raises(BudgetError, match="live_set_work_exhausted"):
        reserve(budget, "third-generation", "personal-deepseek", 1)
    assert budget.snapshot()["calls"] == 2
    assert budget.snapshot()["buckets"]["shared"]["chargedUsd"] == "0.000700000"
    assert budget.snapshot()["buckets"]["personal"]["chargedUsd"] == "0.000900000"
