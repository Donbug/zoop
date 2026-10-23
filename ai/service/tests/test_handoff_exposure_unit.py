"""Deterministic gate/authorization boundaries and independent optional configuration."""
from contextlib import contextmanager

import pytest

from exposure_support import exposure_env, query, report, workspace
from handoff_support import HANDOFF, export_entry
from zoop_ai_service.config import HANDOFF_EXPOSURE_VARS, ConfigError, load
from zoop_ai_service.handoff_exposure_reads import HandoffExposureReads
from zoop_ai_service.handoff_exposure_wire import ExposureQuery
from zoop_ai_service.handoff_reads import HandoffError
from zoop_ai_service.jobs import Observation
from zoop_ai_service.relation_runtime import RelationGate
from zoop_ai_service.runtime import Outcome


def test_exposure_only_configuration_has_no_other_groups_or_credentials(tmp_path):
    ws = workspace(tmp_path)
    cfg = load(ws.env(**exposure_env(ws, only=True)))
    assert cfg.handoff is cfg.relation is cfg.extraction is cfg.graph is None
    group = cfg.handoff_exposure
    assert group is not None and not group.shared_gate
    assert group.state_dir == ws.handoff_state and group.exports_path == ws.exports
    assert set(group.child_env) == {"PATH", "LANG", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "PYTHONNOUSERSITE", "PYTHONUTF8",
                                    "ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"}


@pytest.mark.parametrize("missing", HANDOFF_EXPOSURE_VARS)
def test_partial_group_refuses_startup(tmp_path, missing):
    ws = workspace(tmp_path)
    env = ws.env(**exposure_env(ws, only=True))
    del env[missing]
    with pytest.raises(ConfigError) as caught:
        load(env)
    assert caught.value.field == missing and caught.value.reason == "handoff_exposure_group_incomplete"


@pytest.mark.parametrize("index", [1, 2, 3, 4])
def test_existing_handoff_namespace_must_match(tmp_path, index):
    ws = workspace(tmp_path)
    env = ws.env(**exposure_env(ws))
    other = tmp_path / "other"
    if index == 4:
        other.write_bytes(ws.exports.read_bytes())
    else:
        other.mkdir()
    env[HANDOFF_EXPOSURE_VARS[index]] = str(other)
    with pytest.raises(ConfigError) as caught:
        load(env)
    assert caught.value.reason == "handoff_exposure_source_inconsistent"


class Process:
    def __init__(self, callback=lambda: None):
        self.calls = 0
        self.callback = callback

    def query(self, request):
        self.calls += 1
        self.callback()
        return Outcome("result", result=report(request.wire()))


def reads(ws, process, gate=None):
    return HandoffExposureReads(load(ws.env(**exposure_env(ws))), process, gate, busy_wait=0.01)


def invoke(service):
    return service.query("alpha", ExposureQuery.model_validate(query()), Observation())


@pytest.mark.parametrize("changed", [False, True])
def test_allowlist_changed_while_waiting_prevents_child(tmp_path, changed):
    ws = workspace(tmp_path)
    process = Process()

    class WaitGate:
        @contextmanager
        def hold(self, seconds):
            ws.write_exports([export_entry(principal="alpha", manifestDigest="a" * 64)] if changed else [])
            yield

    service = reads(ws, process, WaitGate())
    with pytest.raises(HandoffError) as caught:
        invoke(service)
    assert caught.value.code == "handoff_not_allowed" and process.calls == 0


def test_shared_gate_and_two_slots_refuse_without_child(tmp_path):
    ws = workspace(tmp_path, with_relation=True)
    cfg = load(ws.env(**exposure_env(ws)))
    assert cfg.handoff_exposure.shared_gate
    gate, process = RelationGate(), Process()
    service = reads(ws, process, gate)
    assert gate.acquire(0)
    try:
        with pytest.raises(HandoffError) as caught:
            invoke(service)
        assert caught.value.code == "runtime_busy" and process.calls == 0
    finally:
        gate.release()
    assert service._slots.acquire(False) and service._slots.acquire(False)
    try:
        with pytest.raises(HandoffError) as caught:
            invoke(service)
        assert caught.value.code == "service_busy" and process.calls == 0
    finally:
        service._slots.release()
        service._slots.release()
    assert invoke(service).status == 200 and process.calls == 1


def test_final_recheck_suppresses_revocation_during_report_validation(tmp_path, monkeypatch):
    from zoop_ai_service.handoff_exposure_wire import ExposureReport
    ws = workspace(tmp_path)
    service = reads(ws, Process())
    validate = ExposureReport.model_validate

    def revoke(value):
        parsed = validate(value)
        ws.write_exports([])
        return parsed

    monkeypatch.setattr(ExposureReport, "model_validate", revoke)
    with pytest.raises(HandoffError) as caught:
        invoke(service)
    assert caught.value.code == "handoff_not_allowed"
