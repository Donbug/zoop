"""Requirements 76 and 59: the job runner runs the PoC CLI one job at a time, with a call cap and recovery."""

from __future__ import annotations

import json
import signal
import time

from .conftest import jobs_settled
from .fakes import POLICY, SECRET, run_report

FLUSH = {"kind": "flush-graph", "reason": "GraphDB 미반영 재시도"}
PAID = {"kind": "retry-model-errors", "reason": "모델 오류 재처리", "confirmPaid": True}


def _create(kit, body):
    return kit.client.post("/api/admin/jobs", json=body)


def _job(kit, job_id):
    return kit.client.get(f"/api/admin/jobs/{job_id}").json()


def _until(kit, job_id, status, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = _job(kit, job_id)
        if job["status"] == status:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never became {status}: {_job(kit, job_id)['status']}")


def _events(kit) -> set[str]:
    return {e["id"] for e in kit.client.get("/api/events").json()["items"]}


def test_flush_graph_runs_the_cli_and_does_not_touch_what_users_see(admin):
    admin.launcher.script(stdout=json.dumps({"completed_projection_jobs": 3}))
    before = _events(admin)
    created = _create(admin, FLUSH)
    assert created.status_code == 202, created.text
    job = created.json()["job"]
    assert created.json()["deduplicated"] is False
    assert (job["kind"], job["paid"], job["command"], job["maxModelCalls"]) == ("flush-graph", False, ["poc", "flush-graph"], None)
    jobs_settled(admin)

    done = _job(admin, job["id"])
    assert done["status"] == "succeeded" and done["exitCode"] == 0
    assert done["flush"] == {"completedProjectionJobs": 3}
    assert done["startedAt"] and done["finishedAt"] and done["durationSeconds"] is not None
    assert done["ledgerBefore"]["issues"] == 3 and done["ledgerAfter"]["pendingProjections"] == 0
    assert [p.spec.argv[1:] for p in admin.launcher.launches] == [["flush-graph"]]
    assert _events(admin) == before  # a job changes the ledger side only; publication is a separate step

    entry = admin.client.get("/api/admin/audit-log", params={"action": "job.create"}).json()["items"][0]
    assert entry["reason"] == "GraphDB 미반영 재시도" and entry["actorEmail"] == "admin@zoop.local"
    assert entry["targetId"] == job["id"]


def test_only_one_job_runs_at_a_time_and_a_repeat_returns_the_running_one(admin):
    admin.launcher.script(hold=True)
    first = _create(admin, FLUSH).json()["job"]
    _until(admin, first["id"], "running")

    same = _create(admin, FLUSH)
    assert same.status_code == 200 and same.json()["deduplicated"] is True
    assert same.json()["job"]["id"] == first["id"]
    other = _create(admin, PAID)
    assert other.status_code == 409 and other.json()["error"]["code"] == "job_in_progress"
    assert other.json()["error"]["details"]["jobId"] == first["id"]
    assert len(admin.launcher.launches) == 1

    listing = admin.client.get("/api/admin/jobs").json()
    assert listing["lock"]["locked"] is True and listing["lock"]["jobId"] == first["id"]
    assert listing["active"]["id"] == first["id"]

    admin.launcher.launches[0].finish(0, json.dumps({"completed_projection_jobs": 0}))
    _until(admin, first["id"], "succeeded")
    assert admin.client.get("/api/admin/jobs").json()["lock"]["locked"] is False
    second = _create(admin, FLUSH).json()
    assert second["deduplicated"] is False and second["job"]["id"] != first["id"]
    jobs_settled(admin)


def test_paid_jobs_need_confirmation_and_a_bounded_call_cap(make_admin):
    kit = make_admin(admin_max_model_calls=100)
    kit.login()
    missing = _create(kit, {"kind": "retry-model-errors", "reason": "재처리"})
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "paid_confirmation_required"
    not_true = _create(kit, {**PAID, "confirmPaid": "yes"})
    assert not_true.status_code == 422  # only a real boolean true counts
    for cap in (0, -1, 101):
        invalid = _create(kit, {**PAID, "maxModelCalls": cap})
        assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "max_model_calls_invalid", cap
        assert invalid.json()["error"]["details"]["allowedMax"] == 100
    assert kit.launcher.launches == [] and kit.client.get("/api/admin/jobs").json()["items"] == []

    kit.launcher.script(stdout=json.dumps(run_report(calls=7)))
    ok = _create(kit, {**PAID, "maxModelCalls": 30}).json()["job"]
    jobs_settled(kit)
    argv = kit.launcher.launches[0].spec.argv
    assert argv[1:5] == ["run", "--live", "--retry-model-errors", "--config"]
    assert json.loads(open(argv[5]).read())["max_calls"] == 30  # the PoC stops calling the model at this count
    assert ok["maxModelCalls"] == 30 and ok["paid"] is True


def test_omitted_cap_uses_the_default_of_fifty(admin):
    admin.launcher.script(stdout=json.dumps(run_report(calls=1)))
    job = _create(admin, PAID).json()["job"]
    jobs_settled(admin)
    assert job["maxModelCalls"] == 50
    assert json.loads(open(admin.launcher.launches[0].spec.argv[5]).read())["max_calls"] == 50
    assert admin.client.get("/api/admin/jobs").json()["limits"] == {"defaultMaxModelCalls": 50, "maxModelCalls": 200}


def test_ingest_run_processes_only_a_sandbox_article_file_within_the_call_cap(admin):
    ingest = {"kind": "ingest-run", "reason": "신규 기사 처리", "confirmPaid": True, "maxModelCalls": 40}
    missing = _create(admin, {k: v for k, v in ingest.items() if k != "maxModelCalls"})
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "dataset_required"
    for name in ("nope.jsonl", "../.env", "sub/batch-01.jsonl"):
        unknown = _create(admin, {**ingest, "dataset": name})
        assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "dataset_not_found", name
    stray = _create(admin, {**PAID, "dataset": "batch-01.jsonl"})
    assert stray.status_code == 422 and stray.json()["error"]["code"] == "dataset_not_allowed"
    assert admin.launcher.launches == []

    dataset = admin.sandbox.datasets_dir / "batch-01.jsonl"
    dataset.write_text("{}\n")
    assert admin.client.get("/api/admin/jobs").json()["sandbox"]["datasets"] == ["batch-01.jsonl"]
    admin.launcher.script(code=1, stdout=json.dumps(run_report(calls=40, errors=1)))
    created = _create(admin, {**ingest, "dataset": "batch-01.jsonl"}).json()["job"]
    jobs_settled(admin)
    argv = admin.launcher.launches[0].spec.argv
    assert argv[1:4] == ["run", "--live", "--config"] and "--retry-model-errors" not in argv
    assert argv[argv.index("--dataset") + 1] == str(dataset)
    assert json.loads(open(argv[4]).read())["max_calls"] == 40  # the cap reaches the PoC settings of this run
    assert (created["kind"], created["paid"], created["dataset"], created["maxModelCalls"]) == ("ingest-run", True, "batch-01.jsonl", 40)

    admin.launcher.script(stdout=json.dumps(run_report(calls=9, run_id="run-test-2")))
    retried = admin.client.post(f"/api/admin/jobs/{created['id']}/retry", json={"reason": "남은 기사", "confirmPaid": True, "maxModelCalls": 25}).json()["job"]
    jobs_settled(admin)
    again = admin.launcher.launches[1].spec.argv
    assert again[again.index("--dataset") + 1] == str(dataset) and retried["dataset"] == "batch-01.jsonl"

    usage = admin.client.get("/api/admin/ai-usage", params={"window": "all"}).json()
    news = next(f for f in usage["features"] if f["feature"] == "news-analysis")
    assert news["usage"]["modelCalls"] == 49  # 40 + 9: article-processing jobs count toward the AI usage screen


def test_a_paid_run_reports_usage_and_a_nonzero_exit_keeps_the_partial_report(admin):
    admin.launcher.script(stdout=json.dumps(run_report(calls=12)))
    ok = _create(admin, PAID).json()["job"]
    jobs_settled(admin)
    done = _job(admin, ok["id"])
    assert done["status"] == "succeeded"
    assert done["report"]["processed"] == 4 and done["report"]["usage"]["calls"] == 12
    assert done["report"]["usage"]["estimatedCost"] is None  # no price is invented

    admin.launcher.script(
        code=1,
        stdout=json.dumps(run_report(calls=30, errors=2, run_id="run-test-2")),
        stderr=f"warning: key {SECRET}\nAuthorization: Bearer abcdefgh12345678\n",
    )
    failed = _create(admin, {**PAID, "maxModelCalls": 30}).json()["job"]
    jobs_settled(admin)
    job = _job(admin, failed["id"])
    assert job["status"] == "failed" and job["exitCode"] == 1
    assert job["error"]["code"] == "cli_nonzero_exit" and "상한(30회)" in job["error"]["message"]
    assert job["report"]["errorCount"] == 2 and job["report"]["pending"] == 2  # partial progress stays visible
    tail = "\n".join(job["logTail"])
    assert SECRET not in tail and "abcdefgh12345678" not in tail and "[redacted]" in tail
    assert SECRET not in json.dumps(job) and SECRET not in admin.client.get("/api/admin/jobs").text


def test_retry_creates_a_linked_job_only_for_failed_or_cancelled_ones(admin):
    admin.launcher.script(code=1, stdout=json.dumps(run_report(calls=3, errors=1)))
    failed = _create(admin, PAID).json()["job"]
    jobs_settled(admin)
    assert _job(admin, failed["id"])["retryable"] is True

    admin.launcher.script(stdout=json.dumps(run_report(calls=3)))
    retry = admin.client.post(
        f"/api/admin/jobs/{failed['id']}/retry", json={"reason": "다시", "confirmPaid": True, "maxModelCalls": 10}
    )
    assert retry.status_code == 202, retry.text
    new = retry.json()["job"]
    assert new["retryOf"] == failed["id"] and new["maxModelCalls"] == 10 and new["kind"] == "retry-model-errors"
    jobs_settled(admin)
    assert _job(admin, new["id"])["retryable"] is False
    again = admin.client.post(f"/api/admin/jobs/{new['id']}/retry", json={"reason": "또", "confirmPaid": True})
    assert again.status_code == 409 and again.json()["error"]["code"] == "job_not_retryable"
    assert admin.client.post("/api/admin/jobs/job-9999/retry", json={"reason": "x"}).status_code == 404

    unconfirmed = admin.client.post(f"/api/admin/jobs/{failed['id']}/retry", json={"reason": "확인 없이"})
    assert unconfirmed.status_code == 422 and unconfirmed.json()["error"]["code"] == "paid_confirmation_required"


def test_a_policy_hash_mismatch_or_missing_sandbox_blocks_paid_jobs_only(admin):
    admin.sandbox.expected = "zoop-test-relaxed-1:ffffffffffffffff"
    blocked = _create(admin, PAID)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "policy_mismatch"
    assert blocked.json()["error"]["details"] == {"expected": "zoop-test-relaxed-1:ffffffffffffffff", "active": POLICY}
    assert admin.launcher.launches == []
    sandbox = admin.client.get("/api/admin/jobs").json()["sandbox"]
    assert sandbox["policy"]["match"] is False and sandbox["problems"]
    assert _create(admin, FLUSH).status_code == 202  # no model call, no policy needed
    jobs_settled(admin)

    admin.sandbox.expected = POLICY
    assert admin.client.get("/api/admin/jobs").json()["sandbox"]["policy"]["match"] is True

    admin.sandbox.problem_list = ["샌드박스에 .env가 없어 모델 호출 설정을 읽을 수 없습니다."]
    not_ready = _create(admin, PAID)
    assert not_ready.status_code == 409 and not_ready.json()["error"]["code"] == "sandbox_not_ready"
    assert not_ready.json()["error"]["details"]["problems"] == admin.sandbox.problem_list


def test_cancel_interrupts_the_process_and_is_idempotent(admin):
    admin.launcher.script(hold=True)
    job = _create(admin, FLUSH).json()["job"]
    _until(admin, job["id"], "running")

    cancelled = admin.client.post(f"/api/admin/jobs/{job['id']}/cancel", json={"reason": "중단 요청"})
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["status"] == "cancelled" and body["cancelRequested"] is True and body["finishedAt"]
    assert admin.launcher.launches[0].signals == [signal.SIGINT]
    assert admin.client.post(f"/api/admin/jobs/{job['id']}/cancel", json={"reason": "또"}).json()["status"] == "cancelled"
    assert admin.client.get("/api/admin/jobs").json()["lock"]["locked"] is False
    assert _job(admin, job["id"])["retryable"] is True

    admin.launcher.script(stdout=json.dumps({"completed_projection_jobs": 0}))
    done = _create(admin, FLUSH).json()["job"]
    jobs_settled(admin)
    finished = admin.client.post(f"/api/admin/jobs/{done['id']}/cancel", json={"reason": "늦음"})
    assert finished.status_code == 409 and finished.json()["error"]["code"] == "job_not_cancellable"
    assert admin.client.post("/api/admin/jobs/job-9999/cancel", json={"reason": "x"}).status_code == 404


def test_jobs_left_running_when_the_bff_restarts_are_settled_as_interrupted(admin):
    admin.launcher.script(hold=True, stdout="")
    job = _create(admin, PAID).json()["job"]
    _until(admin, job["id"], "running")
    # The child managed to print its report before the BFF died.
    admin.launcher.launches[0].spec.stdout.write_text(json.dumps(run_report(calls=9)))

    restarted = admin.restart()
    restarted.login()
    settled = _job(restarted, job["id"])
    assert (settled["status"], settled["recovered"]) == ("failed", True)
    assert settled["error"]["code"] == "interrupted_by_restart"
    assert settled["report"]["usage"]["calls"] == 9  # the surviving output is attached
    assert restarted.client.get("/api/admin/jobs").json()["lock"]["locked"] is False
    recover = restarted.client.get("/api/admin/audit-log", params={"action": "job.recover"}).json()["items"]
    assert recover and recover[0]["targetId"] == job["id"] and recover[0]["actorKind"] == "system"

    # The old process is gone for good: even if its watcher woke up now it must not rewrite the verdict.
    admin.launcher.launches[0].finish(0)
    jobs_settled(admin)
    assert _job(restarted, job["id"])["status"] == "failed"


def test_the_sandbox_info_and_lookup_errors(admin):
    listing = admin.client.get("/api/admin/jobs").json()
    assert listing["sandbox"]["ready"] is True and listing["sandbox"]["policy"]["expected"] == POLICY
    assert admin.client.get("/api/admin/jobs/job-0000").status_code == 404
    assert admin.client.get("/api/admin/jobs", params={"status": "bogus"}).status_code == 422
