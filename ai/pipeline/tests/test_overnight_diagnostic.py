"""Verification-purpose isolation over real native LIVE ledgers and history selection.

Acquisition bytes and HTTP responses are authored, transport is MockTransport,
and all state/budget/history lives in pytest's offline-verification namespace.
No real provider calls or vendor-quality assertions are made.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))
sys.path.insert(0, str(PIPELINE / "scripts"))
from scripts import overnight_run as runner
from tests.test_overnight_history import ACTOR, CATALOGUE, author_mention, forbid_network, run_s2, world
from zoop_ai_pipeline import live_runtime as live
from zoop_ai_pipeline.live_budget import Budget, NANO


def test_diagnostic_native_ready_candidate_cannot_seed_ordinary_snapshot_or_totals(world, monkeypatch):
    root = world.root / "control/offline-verification"
    controller = runner.Controller(SimpleNamespace(root=root, collection_index=root / "collection/INDEX.json"))
    controller.catalogue = CATALOGUE
    controller.cohort = "luna"

    first, first_state, _ = run_s2(world, 0, "ordinary-first")
    first_entry = {"state": "completed", "unit": world.units[0], "cohort": "luna",
                   "comparison": {"completedComparisons": first["counts"]["comparisons"]}}
    recorded_first = controller.record_history(first_entry, world.units[0], first, first_state)
    assert recorded_first["status"] == "recorded"

    ordinary, ordinary_state, _ = run_s2(world, 1, "ordinary-second")
    assert ordinary["state"] == "ready" and ordinary["counts"]["comparisons"] == 1
    ordinary_entry = {"state": "completed", "unit": world.units[1], "cohort": "luna",
                      "comparison": {"completedComparisons": ordinary["counts"]["comparisons"]}}
    controller.record_history(ordinary_entry, world.units[1], ordinary, ordinary_state)

    # Deliberately reanalyse the SAME incoming document for a diagnostic, but use
    # a distinct native mention so a missing purpose fence cannot hide behind dedup.
    diagnostic_mention = author_mention(world.units[1], "diagnostic-mention")[1]
    diagnostic, diagnostic_state, _ = run_s2(world, 1, "diagnostic-duplicate", mentions=[diagnostic_mention])
    assert diagnostic["state"] == "ready" and diagnostic["counts"]["comparisons"] == 1
    controller.cohort = "deepseek-diagnostic"
    diagnostic_entry = {"state": "completed", "unit": world.units[1], "cohort": "deepseek-diagnostic",
                        "queueKind": "deepseek-diagnostic", "comparison": {"completedComparisons": diagnostic["counts"]["comparisons"]}}
    excluded = controller.record_history(diagnostic_entry, world.units[1], diagnostic, diagnostic_state)
    assert excluded["status"] == "not-recorded"
    assert excluded["reasonCode"] == "diagnostic-history-excluded"

    selected = runner.history.snapshot_for(world.units[2], CATALOGUE, max_events=8, max_members=20)
    prior_jobs = {row["upstream"]["jobId"] for row in selected["coverage"]["selected"]}
    prior_candidates = {row["eventCandidateId"] for row in selected["coverage"]["selected"]}
    assert prior_jobs == {"ordinary-first", "ordinary-second"}
    assert diagnostic["eventCandidates"][0]["eventCandidateId"] not in prior_candidates
    records = [runner.load(path) for path in (Path(world.units[0]["history"]["directory"]) / "ready").glob("*.json")]
    assert {record["jobId"] for record in records} == prior_jobs

    queue = {"first": first_entry, "second": ordinary_entry, "diagnostic": diagnostic_entry}
    totals = runner.queue_totals(queue)
    assert totals["ordinary"] == {"states": {"completed": 2}, "completed": 2, "completedComparisons": 1}
    assert totals["deepseek-diagnostic"] == {"states": {"completed": 1}, "completed": 1, "completedComparisons": 1}

    # Purpose isolation excludes data contribution, NOT the diagnostic's charge:
    # the native simulator ledger still contains first(1)+second(2)+diagnostic(2).
    budget = Budget(os.environ[live.BUDGET_DIR_VAR], 10 * NANO, 100)
    assert budget.snapshot()["calls"] == 5

    def forbidden_graph(*args, **kwargs):
        raise AssertionError("diagnostic must not dispatch any graph CLI")

    monkeypatch.setattr(controller, "cli", forbidden_graph)
    controller.project_graph(diagnostic_entry, world.units[1], diagnostic, {}, diagnostic_state.parent)
    assert diagnostic_entry["graph"]["status"] == "not-exercised"
    assert diagnostic_entry["graph"]["reasonCode"] == "diagnostic-graph-excluded"
    assert not (root / "analysis/graph").exists()
    assert budget.snapshot()["calls"] == 5


def test_http200_empty_summary_is_received_producer_invalid_not_success(tmp_path, monkeypatch):
    """Actual runtime/producer parser and collector; source authorization is an authored seam."""
    from tests.live_support import json_response, openai_reply
    from tests.test_live_funding import runtime, finite_plan, DAY_START, DAY_END
    from tests.test_overnight_controller import write_ready_canary
    from zoop_ai_pipeline import extraction, live_budget, live_funding

    root = tmp_path / "summary-control"
    root.mkdir()
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "RUN_ID", "day-test")
    monkeypatch.setattr(runner, "MAX_CALLS", 100000)
    monkeypatch.setattr(runner, "RUN_CONFIG", {
        "schemaVersion": "zoop-private-run-4", "runId": "day-test", "root": str(root),
        "admitFrom": DAY_START, "admitUntil": DAY_END, "finishBy": "2026-10-28T09:30:00Z",
        "graphPort": 32829, "maxCalls": 100000, "processingActor": ACTOR,
        "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"}})
    monkeypatch.setattr(runner, "code_pins", lambda: [])
    def verify_fixture(unit):
        for key in ("registry", "export"):
            assert runner.sha(Path(unit[key]).read_bytes()) == unit[key + "Sha256"]
    monkeypatch.setattr(runner, "verify_item", verify_fixture)
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T08:00:00+00:00")
    from datetime import datetime
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(live_budget._now())
    monkeypatch.setattr(live_funding, "datetime", Clock)
    rt, peer = runtime(monkeypatch, tmp_path, family=live.ISSUE_SUMMARY,
                       handler=lambda request: json_response(openai_reply({"claims": []}, model=live.MODEL)), **{
        live.PROFILE_VAR: live_funding.CAPPED_PROFILE, live.RUN_ID_VAR: "day-test", live.NOT_AFTER_VAR: None,
        live.ADMIT_FROM_VAR: DAY_START, live.ADMIT_UNTIL_VAR: DAY_END, live.SET_ID_VAR: "set-summary",
        live.BUDGET_DIR_VAR: str(root / "modelbudget"), live.MAX_CALLS_VAR: "100000"})
    runner.funding(root).admit_set("set-summary", "a" * 64, finite_plan())
    monkeypatch.setattr(live.LiveRuntime, "from_env", classmethod(lambda cls, **kwargs: rt))

    class SourceAuthority:
        def __init__(self, state, authority):
            assert state == root / "ingestion"
            assert authority.public is True
            assert authority.registry.revision == "authored-summary-1"

        def authorize_model_send(self, ref, purpose, recipient):
            assert purpose in {"pipeline:issue-summary", "pipeline:verify-issue-summary"}
            assert ref.document_id == "summary-document"

    monkeypatch.setattr(extraction, "Sources", SourceAuthority)
    registry, export = root / "registry.json", root / "export.json"
    text = "합성기업은 공급 계약을 발표했다."
    runner.save(registry, {"schemaVersion": "zoop-ingestion-s2-1", "revision": "authored-summary-1", "sources": []})
    runner.save(export, {"document": {"text": text}})
    observation = {"roundId": "summary-round", "sourceId": "synthetic-source", "page": 0, "ordinal": 0,
                   "documentId": "summary-document", "rawVersion": "a" * 64, "documentVersion": "b" * 64}
    unit = {"unitId": "summary-unit", "sourceId": observation["sourceId"], "observation": observation,
            "registry": str(registry), "export": str(export), "ingestionStateDir": str(root / "ingestion"),
            "registrySha256": runner.sha(registry.read_bytes()), "exportSha256": runner.sha(export.read_bytes()), "originalPins": []}
    directory = root / "analysis/luna/summary-unit"
    runner.save(directory / "unit.json", unit)
    candidate = {"eventCandidateId": "candidate-summary", "state": "candidate", "mention": {"title": "합성 발표"},
                 "citations": [{"documentId": observation["documentId"], "documentVersion": observation["documentVersion"],
                                "evidenceId": "q-owner", "start": 0, "end": len(text)}]}
    s2 = {"inputDigest": "c" * 64, "eventCandidates": [candidate]}
    runner.save(directory / "s2-result.json", s2)
    runner.save(directory / "summary-runtime.json", rt.binding())
    pins = {"codePins": [], "runConfig": runner.RUN_CONFIG, "identityPolicy": runner.POLICY, "units": [unit],
            "funding": {"policyVersion": rt.binding()["funding"]["version"],
                        "policyIdentity": runner.sha(runner.encoded(rt.binding()["funding"])),
                        "totalMaxNanoUsd": 4_000_000_000, "bucketMaxNanoUsd": {"shared": 3_500_000_000, "personal": 500_000_000}, "maxCalls": 100000},
            "runtimeBindings": {"luna": {"pipeline": rt.binding(), "summary": rt.binding()}}}
    checked = {"checkDigest": runner.sha(runner.encoded(pins)), "pins": pins}
    runner.save(root / "control/CHECK.json", checked)
    runner.save(root / "control/greenlight.json", runner.v2_greenlight(checked, "run"))
    for profile in ("luna", "deepseek-diagnostic"):
        write_ready_canary(root, checked, profile, unit)
    with pytest.raises(ValueError, match="producer-invalid"):
        runner.private_summary_child(directory, candidate["eventCandidateId"])
    folder = directory / "candidate-summaries" / runner.sha(candidate["eventCandidateId"].encode())[:24]
    receipt_path = folder / "issue-summary-receipt.json"
    original_receipt = receipt_path.read_bytes()
    assert live.physical_attempts(runner.load(receipt_path))[0]["receipt"]["http"]["status"] == 200
    assert runner.load(folder / "issue-summary-verdict.json")["code"] == "producer-invalid"
    assert not (folder / "issue-summary-failure.json").exists()
    assert not (folder / "verify-issue-summary-intent.json").exists()
    assert len(peer.requests) == 1

    controller = runner.Controller(SimpleNamespace(root=root, collection_index=root / "collection/INDEX.json"))
    controller.pins = {"runtimeBindings": {"luna": {"summary": rt.binding()}}}
    def exited_producer(*args, **kwargs):
        raise runner.Refused("producer-invalid")
    monkeypatch.setattr(controller, "command", exited_producer)
    outcomes = controller.summaries(unit, directory, s2, {})
    assert outcomes["technicalComplete"] is False
    events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
    attempt = next(event for event in events if event.get("kind") == "attempt")
    assert attempt["attemptState"] == "received" and attempt["status"] == "error"
    assert attempt["reasonCode"] == "producer-invalid" and attempt["httpStatus"] == 200
    assert receipt_path.read_bytes() == original_receipt
    assert runner.funding(root).snapshot()["calls"] == 1
