"""Existing nonempty outlook production→immutable round→real GET, using actual worker subprocesses."""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from investmate.domain import Article

from zoop_bff.ai_worker import AiWorkerClient
from zoop_bff.audit import Actor
from zoop_bff.config import BFF_ROOT

FIXTURE = BFF_ROOT.parents[1] / "ai/worker/fixtures/contracts/synthetic-outlook"
MOMENT = datetime.fromisoformat("2026-10-08T18:15:00+09:00")
RID = "brf-2026-10-08-evening"


def fixture(name):
    return json.loads((FIXTURE / (name + ".json")).read_text())


def attach(kit, tmp_path, *, grants=None):
    client = AiWorkerClient(state_dir=kit.state_dir, worker_state=tmp_path / "worker",
                           grants=grants or FIXTURE / "grants.json", replay=FIXTURE / "replay.json")
    kit.services.sentiment.configure_outlook(client, {"mode": "replay", "sourceKind": "synthetic",
        "sourceId": "authored-synthetic-round", "grantId": "grant-synthetic-outlook", "grantRevision": "grant-synthetic-outlook-1"})
    return client


def generate(kit):
    kit.clock.travel_to(MOMENT)
    kit.services.briefings.generate(MOMENT.date(), "evening", trigger="admin",
                                   actor=Actor("admin", "synthetic-admin", "synthetic-admin@zoop.local"), blocking=True)
    return kit.services.briefings.record(RID)


def test_existing_outlook_generates_then_round_get_and_restart_preserve_it(make_admin, tmp_path):
    kit = make_admin(fixture("snapshot"))
    worker = attach(kit, tmp_path)
    published = generate(kit)
    assert published.payload and len(published.payload["items"]) == 1
    original = published.payload["outlook"]
    assert original["label"] == "undetermined" and original["issueIds"] == ["event-synthetic-s1"]
    assert original["model"] == "authored-synthetic-briefing-outlook"
    url = "/api/briefings?date=2026-10-08&edition=evening"
    assert kit.client.get(url).json()["outlook"] == original
    assert kit.restart().client.get(url).json()["outlook"] == original
    job_id = next(iter(kit.services.sentiment.outlook_runs))
    before = worker.get(job_id)
    assert before["usage"]["providerAttempts"] == 0 and before["usage"]["replayCalls"] == 1
    # Published rows remain frozen even if a caller supplies a different context/model afterward.
    changed = {**fixture("jobs")["jobs"][0]["input"], "issues": []}
    assert kit.services.sentiment.judge_outlook(changed, synthetic=True).model_dump(by_alias=True) == original
    assert worker.get(job_id)["usage"] == before["usage"]
    kit.login()
    assert kit.client.post(f"/api/admin/briefings/{RID}/reprocess", json={"reason": "발행 후 재판정"}).status_code == 409
    assert kit.client.get(url).json()["outlook"] == original
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        kit.services.db.execute("UPDATE briefing_rounds SET payload='{}' WHERE id=?", (RID,))
    row = kit.services.db.one("SELECT COUNT(*) AS n FROM briefing_outlook_results")
    assert row["n"] == 1
    feature = next(f for f in kit.services.usage.response("all", []).features if f.feature == "briefing-outlook")
    assert feature.usage.model_calls == 0 and feature.usage.replay_calls == 1

def test_preexisting_weak_policy_ready_outlook_is_blocked_before_publication(make_admin, tmp_path):
    kit = make_admin(fixture("snapshot"))
    worker = attach(kit, tmp_path)
    request = fixture("jobs")["jobs"][0]
    worker.command("submit", request)
    ready = worker.command("run", {"schemaVersion": "zoop-ai-s1-1", "jobId": request["jobId"]})
    weak = copy.deepcopy(ready)
    artifact = next(a for a in weak["artifacts"] if a["kind"] == "briefing-outlook")
    artifact["result"]["rationale"] = "내일 지수가 오를 전망입니다."

    class StoredWeakResult:
        def get(self, job_id):
            assert job_id == request["jobId"]
            return copy.deepcopy(weak)

        def command(self, command, payload):
            raise AssertionError(f"stored ready result must not execute {command}")

    context = dict(kit.services.sentiment.outlook_context)
    kit.services.sentiment.configure_outlook(StoredWeakResult(), context)
    record = generate(kit)
    assert record.status == "failed" and record.payload is None
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM briefing_outlook_results")["n"] == 0
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"] == 0


def test_empty_round_publishes_null_without_any_worker_command(make_admin, tmp_path):
    kit = make_admin(fixture("snapshot"))
    attach(kit, tmp_path)
    moment = datetime.fromisoformat("2026-10-08T07:45:00+09:00")
    kit.clock.travel_to(moment)
    kit.services.briefings.generate(moment.date(), "morning", trigger="admin",
                                   actor=Actor("admin", "synthetic-admin"), blocking=True)
    payload = kit.services.briefings.record("brf-2026-10-08-morning").payload
    assert payload and payload["items"] == [] and payload["outlook"] is None
    assert not (tmp_path / "worker").exists()
    assert kit.services.db.one("SELECT COUNT(*) AS n FROM document_analysis_calls")["n"] == 0


def test_round_authority_and_unknown_source_rights_never_call_a_model(make_admin, tmp_path):
    kit = make_admin(fixture("snapshot"))
    attach(kit, tmp_path)
    assert kit.client.post(f"/api/admin/briefings/{RID}/reprocess", json={"reason": "권한 없는 실행"}).status_code == 401
    assert not (tmp_path / "worker").exists()
    rights = fixture("grants")
    rights["grants"][0]["rights"] = "unknown"
    registry = tmp_path / "unknown-grants.json"
    registry.write_text(json.dumps(rights))
    worker = attach(kit, tmp_path, grants=registry)
    record = generate(kit)
    assert record.payload is None and record.status == "failed"
    request = fixture("jobs")["jobs"][0]
    result = worker.get(request["jobId"])
    assert result["state"] == "failed" and result["failure"]["code"] == "source_rights_unknown_or_denied"
    assert result["calls"] == [] and result["usage"]["providerAttempts"] == result["usage"]["replayCalls"] == 0


def test_authored_outlook_is_not_applied_to_actual_source(make_admin, tmp_path):
    raw = fixture("snapshot")
    article = raw["issues"][0]["articles"][0]
    article["synthetic"] = False
    version = Article.model_validate(article).version
    for issue in raw["issues"]:
        for mention in issue["mentions"]:
            mention["article_version"] = version
            for evidence in mention["evidence"]:
                evidence["article_version"] = version
        for relation in issue["relations"]:
            for evidence in relation["evidence"]:
                evidence["article_version"] = version
    kit = make_admin(raw)
    attach(kit, tmp_path)
    assert kit.services.provider.get().synthetic is False
    record = generate(kit)
    assert record.payload is None and record.status == "failed"
    assert not (tmp_path / "worker").exists()


def test_actual_outlook_cli_publishes_nonempty_and_empty_rounds_without_live_calls(tmp_path):
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, str(BFF_ROOT / "scripts/replay_outlook_fixture.py"),
               "--worker-state", str(tmp_path / "cli-worker"), "--bff-state", str(tmp_path / "cli-bff"),
               "--empty-bff-state", str(tmp_path / "cli-empty")]
    process = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
    assert process.returncode == 0, process.stdout + process.stderr
    report = json.loads(process.stdout)
    assert report["nonempty"]["rounds"][0]["issueCount"] == 1
    assert report["nonempty"]["rounds"][0]["outlook"]["label"] == "undetermined"
    assert report["immutableRepeat"]["workerJobs"] == report["emptyNoCall"]["workerJobs"] == []
    assert report["modelNetworkCalls"] == 0
