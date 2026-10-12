"""The internal `initial_only` permission used by automatic redispatch, decided under the real job lock.

It may start a job that has never made a call; once any call record exists it only persists receipts already stored and never
reserves or sends a stage. Ordinary callers (no flag) keep every existing semantic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from test_documents import FIXTURE, setup
from zoop_ai.runner import Runner


class Interrupted(BaseException):
    """A process dying between the two stages: not an Exception, so no runner handler can absorb it."""


class CutAfterGeneration(Runner):
    def _call(self, request, stage, payload, config, fence):
        if stage == "semantic-verification":
            raise Interrupted()
        return super()._call(request, stage, payload, config, fence)


def between_stages(tmp_path):
    runner, provider, request = setup(tmp_path)
    cut = CutAfterGeneration(runner.store, provider)
    with pytest.raises(Interrupted):
        cut.run(request.job_id)
    assert provider.calls == 1 and [c["stage"] for c in runner.store.calls(request.job_id)] == ["document-summary"]
    return runner, provider, request


def test_initial_only_never_sends_the_missing_stage_but_ordinary_run_does(tmp_path):
    runner, provider, request = between_stages(tmp_path)
    before = runner.get(request.job_id)
    for call in (runner.run, runner.resume):
        held = call(request.job_id, initial_only=True)
        assert (held.state, held.phase, held.resume_mode) == (before.state, before.phase, before.resume_mode)
        assert provider.calls == 1 and len(runner.store.calls(request.job_id)) == 1  # nothing reserved, nothing sent
    done = runner.run(request.job_id)  # the explicit/ordinary continuation is unchanged
    assert done.state == "ready" and provider.calls == 2
    runner.store.close()


def test_initial_only_starts_a_job_that_never_made_a_call_and_persists_complete_receipts(tmp_path):
    runner, provider, request = setup(tmp_path)
    assert runner.get(request.job_id).state == "queued"
    ready = runner.run(request.job_id, initial_only=True)
    assert ready.state == "ready" and provider.calls == 2
    again = runner.run(request.job_id, initial_only=True)
    assert again.state == "ready" and provider.calls == 2
    runner.store.close()


def test_initial_only_still_turns_a_lost_started_call_into_reconciling(tmp_path):
    runner, provider, request = setup(tmp_path)
    runner.store.reserve(job_id=request.job_id, stage="document-summary", request_digest="d", config={}, mode="replay",
                         fence=0, attempt_id="attempt-lost", fixture_digest=None)
    held = runner.run(request.job_id, initial_only=True)
    assert held.state == "reconciling" and held.resume_mode == "reconcile_only" and provider.calls == 0
    runner.store.close()


def test_initial_only_is_only_for_run_and_resume_and_never_builds_a_provider_after_a_call_record(tmp_path):
    runner, provider, request = between_stages(tmp_path)
    runner.store.close()
    env = {"PATH": "/usr/bin:/bin"}
    submit = [sys.executable, "-m", "zoop_ai.cli"]
    state = str(tmp_path / "worker")
    payload = json.dumps({"schemaVersion": "zoop-ai-s1-1", "jobId": request.job_id})

    def call(command, *extra):
        done = subprocess.run([*submit, command, "--state-dir", state, *extra], input=payload, capture_output=True, text=True, env=env)
        return done.returncode, json.loads(done.stdout)

    code, body = call("get", "--initial-only")
    assert code == 2 and body["error"]["code"] == "command_input_invalid"
    # No --replay is given: an ordinary run would fail replay_fixture_required, initial-only builds no provider and hands back the job.
    code, body = call("run")
    assert code == 2 and body["error"]["code"] == "replay_fixture_required"
    code, body = call("run", "--initial-only")
    assert code == 0 and body["state"] == "running" and len(body["calls"]) == 1
