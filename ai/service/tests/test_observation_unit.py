"""Observation configuration and closed selector; the real transport proof lives in pipeline_tests."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from support import Workspace
from zoop_ai_service.config import CHILD_BASE_ENV, ConfigError, load
from zoop_ai_service.observation_wire import NativeObservation, ObservationExportRequest

SELECTOR = {"schemaVersion": "zoop-ingestion-s2-1", "roundId": "round-1", "sourceId": "synthetic-source",
            "page": 0, "ordinal": 0, "documentId": "document-1", "rawVersion": "a" * 64, "documentVersion": "b" * 64}


def environment(tmp_path):
    ws = Workspace(tmp_path)
    ingestion = tmp_path / "ingestion"
    ingestion.mkdir()
    sources = tmp_path / "sources.json"
    sources.write_text('{}')  # configuration only checks file accessibility; native CLI validates the registry on every read
    return ws, ws.env(ZOOP_AI_SERVICE_INGESTION_COMMAND=str(ws.env()["ZOOP_AI_SERVICE_WORKER_COMMAND"]),
                      ZOOP_AI_INGESTION_STATE_DIR=str(ingestion), ZOOP_AI_SERVICE_SOURCES=str(sources),
                      ZOOP_STATE_DIR=str(tmp_path / "app"))


def test_observation_is_explicit_and_reuses_shared_settings_without_enabling_execution(tmp_path):
    ws, env = environment(tmp_path)
    assert load(ws.env()).observation is None
    config = load(env)
    assert config.observation is not None
    assert config.relation is config.extraction is None
    assert all("observation.read" not in p.scopes for p in config.principals)
    assert set(config.observation.child_env) == set(CHILD_BASE_ENV) | {"ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"}
    ws.credentials.scopes["alpha"].append("observation.read")
    env["ZOOP_AI_SERVICE_PRINCIPALS"] = ws.credentials.principals_json()
    assert "observation.read" in load(env).principals[0].scopes


@pytest.mark.parametrize("field", ["ZOOP_AI_INGESTION_STATE_DIR", "ZOOP_AI_SERVICE_SOURCES"])
def test_observation_partial_group_fails_closed(tmp_path, field):
    _, env = environment(tmp_path)
    del env[field]
    with pytest.raises(ConfigError) as caught:
        load(env)
    assert (caught.value.field, caught.value.reason) == (field, "observation_group_incomplete")


def test_observation_ingestion_cannot_overlap_service_state(tmp_path):
    ws, env = environment(tmp_path)
    env["ZOOP_AI_INGESTION_STATE_DIR"] = str(ws.state)
    with pytest.raises(ConfigError) as caught:
        load(env)
    assert caught.value.reason == "observation_roots_overlap"


@pytest.mark.parametrize("changes", [{"observationId": "invented"}, {"requireStore": False}, {"stateDir": "/tmp/client"},
                                    {"page": True}, {"ordinal": -1}, {"schemaVersion": "unknown"}, {"round_id": "alias"}])
def test_selector_is_closed_and_strict(changes):
    with pytest.raises(ValidationError):
        ObservationExportRequest.model_validate({**SELECTOR, **changes})


def test_schema_version_is_required_and_selector_round_trips_without_normalization():
    assert ObservationExportRequest.model_validate(SELECTOR).wire() == SELECTOR
    with pytest.raises(ValidationError):
        ObservationExportRequest.model_validate({k: v for k, v in SELECTOR.items() if k != "schemaVersion"})


def test_native_language_is_optional_bounded_and_preserved_without_normalization():
    observation = {key: value for key, value in SELECTOR.items() if key != "schemaVersion"} | {
        "pageId": "page-0", "observedAt": "2026-10-29T00:00:00Z", "url": "https://example.invalid/article",
        "title": "authored", "publishedAt": None, "modifiedAt": None, "sourceRevision": None, "mediaType": "text/html"}
    assert NativeObservation.model_validate(observation).wire() == observation
    for language in ("ko", "en-US", "und", "x" * 35):
        declared = {**observation, "language": language}
        assert NativeObservation.model_validate(declared).wire() == declared
    for language in (None, "", "k", "x" * 36, 7):
        with pytest.raises(ValidationError):
            NativeObservation.model_validate({**observation, "language": language})
