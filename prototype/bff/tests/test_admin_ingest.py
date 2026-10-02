"""FS058 / D11: an article run that really found nothing new is a success; a failed request is never recorded as
zero, and neither a failure nor a zero-article run can move the checkpoint the next run starts from wrongly."""

from __future__ import annotations

import json
import time

from .conftest import jobs_settled
from .fakes import run_report

INGEST = {
    "kind": "ingest-run",
    "reason": "신규 기사 처리",
    "confirmPaid": True,
    "maxModelCalls": 40,
    "dataset": "batch-01.jsonl",
}
HOUR = 3600


def _report(*, processed: int, skipped: int = 0, **extra) -> str:
    return json.dumps({**run_report(calls=2), "processed": processed, "skipped": skipped, **extra})


def _run(kit, **outcome) -> dict:
    kit.launcher.script(**outcome)
    job = kit.client.post("/api/admin/jobs", json=INGEST).json()["job"]
    jobs_settled(kit)
    return kit.client.get(f"/api/admin/jobs/{job['id']}").json()


def _until_running(kit, job_id: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if kit.client.get(f"/api/admin/jobs/{job_id}").json()["status"] == "running":
            return
        time.sleep(0.02)
    raise AssertionError(f"{job_id} never started")


def _baseline(kit) -> dict:
    return kit.client.get("/api/admin/jobs").json()["ingest"]


def test_a_normal_run_without_new_articles_is_a_success_and_moves_the_baseline(admin):
    (admin.sandbox.datasets_dir / "batch-01.jsonl").write_text("{}\n")
    assert _baseline(admin) == {"at": None, "jobId": None, "outcome": None, "newArticles": None, "unresolvedFailures": 0}

    empty = _run(admin, stdout=_report(processed=0, skipped=3))
    assert empty["status"] == "succeeded" and empty["error"] is None
    assert empty["ingest"]["outcome"] == "empty"
    assert (empty["ingest"]["newArticles"], empty["ingest"]["duplicateArticles"]) == (0, 3)  # confirmed zero
    assert empty["ingest"]["baselineBefore"] is None
    assert empty["ingest"]["baselineAfter"] == empty["startedAt"] and empty["ingest"]["baselineAdvanced"] is True
    assert _baseline(admin) == {
        "at": empty["startedAt"],
        "jobId": empty["id"],
        "outcome": "empty",
        "newArticles": 0,
        "unresolvedFailures": 0,
    }

    admin.clock.advance(HOUR)
    found = _run(admin, stdout=_report(processed=5, skipped=1))
    assert found["ingest"]["outcome"] == "collected" and found["ingest"]["newArticles"] == 5
    assert found["ingest"]["baselineBefore"] == empty["startedAt"]  # the round starts from the last success
    assert found["ingest"]["baselineAfter"] == found["startedAt"] != empty["startedAt"]


def test_failed_cancelled_and_unconfirmed_runs_record_no_zero_and_keep_the_baseline(admin):
    (admin.sandbox.datasets_dir / "batch-01.jsonl").write_text("{}\n")
    good = _run(admin, stdout=_report(processed=2))
    checkpoint = good["startedAt"]

    # A request failure (the PoC exits 1 and lists the failed collection request) is not "0 new articles".
    admin.clock.advance(HOUR)
    request_failed = _run(
        admin,
        code=1,
        stdout=_report(processed=0, collection_errors=[{"stage": "feed", "code": "CrawlTimeout", "error": "timed out", "url": "https://x"}]),
    )
    assert request_failed["status"] == "failed" and request_failed["error"]["code"] == "collection_failed"
    assert request_failed["report"]["collectionErrorCount"] == 1
    assert request_failed["report"]["collectionErrors"] == [{"stage": "feed", "type": "CrawlTimeout", "message": "timed out"}]
    assert request_failed["ingest"]["outcome"] == "failed"
    assert request_failed["ingest"]["newArticles"] is None and request_failed["ingest"]["duplicateArticles"] is None
    assert request_failed["ingest"]["baselineBefore"] == request_failed["ingest"]["baselineAfter"] == checkpoint
    assert request_failed["ingest"]["baselineAdvanced"] is False

    # Exit 0 with no readable report cannot prove that nothing was new: a failure, not an empty success.
    admin.clock.advance(HOUR)
    silent = _run(admin, stdout="")
    assert silent["status"] == "failed" and silent["error"]["code"] == "ingest_unconfirmed"
    assert silent["ingest"]["outcome"] == "failed" and silent["ingest"]["newArticles"] is None
    assert silent["ingest"]["baselineAfter"] == checkpoint

    # Exit 0 whose report still lists failed requests is not a clean run either.
    admin.clock.advance(HOUR)
    inconsistent = _run(admin, stdout=_report(processed=0, collection_errors=[{"stage": "item", "code": "X", "error": "e"}]))
    assert inconsistent["status"] == "failed" and inconsistent["ingest"]["baselineAfter"] == checkpoint

    admin.clock.advance(HOUR)
    admin.launcher.script(hold=True)
    held = admin.client.post("/api/admin/jobs", json=INGEST).json()["job"]
    _until_running(admin, held["id"])
    admin.clock.advance(HOUR)
    cancelled = admin.client.post(f"/api/admin/jobs/{held['id']}/cancel", json={"reason": "중단"}).json()
    assert cancelled["status"] == "cancelled" and cancelled["ingest"]["outcome"] == "cancelled"
    assert cancelled["ingest"]["newArticles"] is None and cancelled["ingest"]["baselineAfter"] == checkpoint

    assert _baseline(admin) == {
        "at": checkpoint,
        "jobId": good["id"],
        "outcome": "collected",
        "newArticles": 2,
        "unresolvedFailures": 1,  # one article file, whose latest run did not finish
    }

    # The retry reads from the last success, not from any failed attempt, and a success clears the open failure.
    admin.clock.advance(HOUR)
    admin.launcher.script(stdout=_report(processed=0, skipped=2))
    retried = admin.client.post(f"/api/admin/jobs/{cancelled['id']}/retry", json={"reason": "다시", "confirmPaid": True}).json()["job"]
    jobs_settled(admin)
    done = admin.client.get(f"/api/admin/jobs/{retried['id']}").json()
    assert done["ingest"]["baselineBefore"] == checkpoint  # the failures did not shorten the range to read
    assert done["ingest"]["outcome"] == "empty" and done["ingest"]["baselineAfter"] == done["startedAt"]
    assert _baseline(admin)["at"] == done["startedAt"] and _baseline(admin)["unresolvedFailures"] == 0


def test_a_restart_that_interrupts_an_article_run_leaves_the_baseline_alone(admin):
    (admin.sandbox.datasets_dir / "batch-01.jsonl").write_text("{}\n")
    good = _run(admin, stdout=_report(processed=1))
    admin.clock.advance(HOUR)
    admin.launcher.script(hold=True, stdout="")
    held = admin.client.post("/api/admin/jobs", json=INGEST).json()["job"]
    _until_running(admin, held["id"])

    restarted = admin.restart()
    restarted.login()
    interrupted = restarted.client.get(f"/api/admin/jobs/{held['id']}").json()
    assert interrupted["status"] == "failed" and interrupted["error"]["code"] == "interrupted_by_restart"
    assert interrupted["ingest"]["outcome"] == "failed" and interrupted["ingest"]["newArticles"] is None
    assert interrupted["ingest"]["baselineAfter"] == good["startedAt"]
    assert _baseline(restarted)["at"] == good["startedAt"]

    admin.launcher.launches[-1].finish(0)  # the old process's watcher must not rewrite the verdict
    jobs_settled(admin)
    assert restarted.client.get(f"/api/admin/jobs/{held['id']}").json()["ingest"]["outcome"] == "failed"
