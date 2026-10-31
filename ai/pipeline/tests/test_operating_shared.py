"""One common input context and shared native outputs consumed by the existing combined handoff reader."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx
import pytest

from scripts.operating_smoke import combined_handoff_source_check, fixture, response, two_sets
from tests.live_support import json_response
from tests.test_operating import native
from tests.test_operating_review import unregistered
from zoop_ai_pipeline import live_budget
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure
from zoop_ai_pipeline.live_budget import BudgetError


def test_shared_native_jobs_feed_existing_combined_handoff(native, tmp_path):
    kit, config, inputs, owner, sent, transport = native
    combined = two_sets(inputs)
    owner.register(combined)
    assert owner.run(1)["status"] == "batch-complete"
    assert owner.run(1)["status"] == "complete"
    assert len(sent) == 12
    checked = combined_handoff_source_check(tmp_path, config, combined["sets"])
    assert checked["relationJobs"] == ["native-s3-1", "native-s3-2"]
    assert checked["upstreamJobs"] == ["native-s2-1", "native-s2-2"]
    assert checked["sourceCount"] == len(checked["incomingDocuments"]) == 2
    assert len(sent) == 12


def test_invalid_first_registration_does_not_claim_common_context(tmp_path, monkeypatch):
    owner, config, inputs = unregistered(tmp_path, monkeypatch, ["set-1"])
    other_kit, _, other_inputs = fixture(tmp_path / "other-context", "https://synthetic.invalid/v1")
    other_inputs["sets"][0]["extraction"]["incoming"]["documentId"] = "doc-not-present"
    with pytest.raises(ExtractionFailure, match="observation_not_found"):
        owner.register(other_inputs)
    assert owner.budget.bound("native-input-context") is None
    owner.register(inputs)
    assert owner.budget.bound("native-input-context") == {
        key: inputs["sets"][0][key] for key in ("ingestionStateDirectory", "sources")}
    assert owner.run(1)["status"] == "complete"


@pytest.mark.parametrize("change", ["missing", "replaced"])
@pytest.mark.parametrize("filename", ["extraction.sqlite3", "relation.sqlite3"])
def test_new_set_cannot_recreate_or_adopt_changed_shared_database(native, tmp_path, change, filename):
    kit, config, inputs, owner, sent, transport = native
    assert owner.run(1)["status"] == "complete"
    databases = list(Path(config["stateDirectory"]).rglob(filename))
    assert len(databases) == 1
    database = databases[0]
    if change == "missing":
        database.unlink()
    else:
        replacement = tmp_path / "replacement.sqlite3"
        shutil.copy2(database, replacement)
        replacement.replace(database)
    second = two_sets(inputs)
    second["sets"] = second["sets"][1:]
    with pytest.raises(BudgetError, match="operating_native_state_(missing|replaced)"):
        owner.register(second)
    assert owner.budget.bound("job:native-s2-2") is None
    assert [entry["id"] for entry in owner.budget.sets()] == ["set-1"]
    assert len(sent) == 7


def test_selected_independent_set_preserves_failed_attempts_and_full_frontier(tmp_path, monkeypatch):
    owner, config, inputs = unregistered(tmp_path, monkeypatch, [f"set-{i}" for i in range(1, 61)])
    inputs = two_sets(inputs)
    inputs["sets"][0]["extraction"]["snapshot"] = {"revision": "empty-native-history", "events": []}
    for unit in inputs["sets"]:
        unit["stageAllowances"]["compare"] = 0
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        answer = response(body)
        if "messages" in body and json.loads(body["messages"][1]["content"])["stage"] == "topic":
            parsed = json.loads(answer["choices"][0]["message"]["content"])
            parsed["topics"][0]["citations"] = []
            answer["choices"][0]["message"]["content"] = json.dumps(parsed)
        return json_response(answer)

    owner.transport = httpx.MockTransport(handler)
    owner.register(inputs)
    failed = owner.run(2)
    assert failed["status"] == "blocked" and [item["setId"] for item in failed["sets"]] == ["set-1"]
    assert failed["sets"][0]["s2"]["failure"]["code"] == "topic_reply_invalid"
    assert len(sent) == 2 and failed["metering"]["states"] == {"settled": 2}
    with owner.native(inputs["sets"][0], "s2") as store:
        frozen_job = dict(store.one("SELECT * FROM jobs WHERE job_id='native-s2-1'"))
        frozen_calls = [dict(row) for row in store.all("SELECT * FROM calls WHERE job_id='native-s2-1' ORDER BY rowid")]
    frozen_money = owner.budget.attempts()

    selected = owner.run(2, set_ids=["set-2", "set-2"])
    assert selected["status"] == "batch-complete" and [item["setId"] for item in selected["sets"]] == ["set-2"]
    assert selected["sets"][0]["s2"]["state"] == selected["sets"][0]["s3"]["state"] == "ready"
    assert selected["metering"]["sets"] == {"admitted": 2, "complete": 1}
    assert selected["metering"]["states"] == {"settled": 7} and len(sent) == 7
    assert selected["metering"]["ledgerId"] == failed["metering"]["ledgerId"]
    assert selected["metering"]["control"]["state"] == "running"
    with owner.native(inputs["sets"][0], "s2") as store:
        assert dict(store.one("SELECT * FROM jobs WHERE job_id='native-s2-1'")) == frozen_job
        assert [dict(row) for row in store.all("SELECT * FROM calls WHERE job_id='native-s2-1' ORDER BY rowid")] == frozen_calls
    assert {key: owner.budget.attempts()[key] for key in frozen_money} == frozen_money
    repeated = owner.run(2, set_ids=["set-2", "set-2"])
    assert repeated["status"] == "batch-complete" and repeated["sets"] == [] and len(sent) == 7
    selected_failure = owner.run(2, set_ids=["set-2", "set-1"])
    assert selected_failure["status"] == "blocked" and selected_failure["sets"] == failed["sets"]
    assert owner.run(2)["sets"] == failed["sets"] and len(sent) == 7
    with owner.native(inputs["sets"][0], "s2") as store:
        assert [dict(row) for row in store.all("SELECT * FROM calls WHERE job_id='native-s2-1' ORDER BY rowid")] == frozen_calls


def test_selectors_preserve_admission_order_and_completed_sets_do_not_consume_limit(native):
    kit, config, inputs, owner, sent, transport = native
    owner.register(two_sets(inputs))
    selectors = ["set-2", "set-1", "set-2", "set-1"]
    first = owner.run(1, set_ids=selectors)
    assert first["status"] == "batch-complete" and [item["setId"] for item in first["sets"]] == ["set-1"]
    assert len(sent) == 7
    second = owner.run(1, set_ids=selectors)
    assert second["status"] == "complete" and [item["setId"] for item in second["sets"]] == ["set-2"]
    assert owner.run(2, set_ids=selectors)["sets"] == [] and len(sent) == 12


def test_unadmitted_selector_refuses_entire_batch_before_native_progress(tmp_path, monkeypatch):
    owner, config, inputs = unregistered(tmp_path, monkeypatch, ["set-1", "set-2"])
    owner.register(inputs)
    with owner.native(inputs["sets"][0], "s2") as store:
        before = list(store.db.iterdump())
    with pytest.raises(BudgetError, match="operating_set_unavailable"):
        owner.run(1, set_ids=["set-1", "set-2"])
    with owner.native(inputs["sets"][0], "s2") as store:
        assert list(store.db.iterdump()) == before
    assert owner.budget.snapshot()["calls"] == 0
    assert owner.budget.snapshot()["sets"] == {"admitted": 1, "complete": 0}


@pytest.mark.parametrize("gate", ["pause", "force-stop", "stop", "unknown"])
def test_selected_set_obeys_global_control_and_financial_holds(native, monkeypatch, gate):
    kit, config, inputs, owner, sent, transport = native
    owner.register(two_sets(inputs))
    if gate == "unknown":
        def lost_response(request):
            sent.append(json.loads(request.content))
            raise httpx.ReadError("synthetic response lost", request=request)

        owner.transport = httpx.MockTransport(lost_response)
        first = owner.run(1)
        assert first["sets"][0]["s2"]["failure"]["code"] == "live_response_unknown"
        assert len(sent) == 1 and owner.budget.snapshot()["states"] == {"reserved": 1}
        owner.transport = transport
    else:
        owner.budget.control(gate, "synthetic-control")
        if gate == "stop":
            after_drain = owner.budget.snapshot()["control"]["drainUntil"] + 1
            monkeypatch.setattr(live_budget.time, "time", lambda: after_drain)
    before = owner.budget.snapshot()
    attempts = owner.budget.attempts()
    if gate == "unknown":
        result = owner.run(1, set_ids=["set-2"])
        assert result["status"] == "blocked"
        assert result["sets"][0]["s2"]["failure"]["code"] == "operating_unresolved_attempt"
        assert len(sent) == 1
    else:
        code = {"pause": "operating_paused", "force-stop": "operating_stopped", "stop": "operating_stopping"}[gate]
        with pytest.raises(BudgetError, match=code):
            owner.run(1, set_ids=["set-2"])
        assert sent == []
    assert owner.budget.snapshot() == before and owner.budget.attempts() == attempts
