"""Observation profiles keep exact routing and credential-filtered read authority."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest
from pydantic import ValidationError

from support import Workspace
from zoop_ai_service.config import CHILD_BASE_ENV, ConfigError, load
from zoop_ai_service.handoff_contexts import observation_route
from zoop_ai_service.observation_wire import NativeObservation, ObservationExportRequest

SELECTOR = {"roundId": "round-1", "sourceId": "source", "page": 0, "ordinal": 0,
            "documentId": "doc-1", "rawVersion": "a" * 64, "documentVersion": "b" * 64}


def profile(tmp_path):
    ws = Workspace(tmp_path / "profile")
    routes = []
    for i in range(2):
        roots = [tmp_path / f"context-{i}-{name}" for name in ("relation", "extraction", "ingestion")]
        for root in roots:
            root.mkdir()
        sources = tmp_path / f"sources-{i}.json"
        sources.write_text('{}')
        routes.append({"contextId": f"context-{i}", "relationStateDirectory": str(roots[0]),
                       "extractionStateDirectory": str(roots[1]), "ingestionStateDirectory": str(roots[2]), "sources": str(sources),
                       "sourcePins": [{"relation": {"jobId": f"r-{i}", "inputDigest": "c" * 64},
                                       "upstream": {"jobId": f"u-{i}", "inputDigest": "d" * 64, "digest": "e" * 64}, "reviewDigest": "f" * 64}],
                       "observations": [{**SELECTOR, "ordinal": i}]})
    path = tmp_path / "contexts.json"
    path.write_text(json.dumps({"schemaVersion": "zoop-handoff-source-contexts-1", "contexts": routes}))
    path.chmod(0o600)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    env = ws.env(ZOOP_AI_SERVICE_INGESTION_COMMAND=ws.env()["ZOOP_AI_SERVICE_WORKER_COMMAND"],
                 ZOOP_AI_SERVICE_OBSERVATION_SOURCE_CONTEXTS=str(path), ZOOP_AI_SERVICE_OBSERVATION_SOURCE_CONTEXTS_SHA256=sha,
                 ZOOP_STATE_DIR=str(tmp_path / "app"))
    return ws, env, path, sha, routes


def test_exact_routes_and_fresh_pin(tmp_path):
    _, env, path, sha, routes = profile(tmp_path)
    cfg = load(env)
    assert cfg.relation is cfg.extraction is None
    assert set(cfg.observation.child_env) == set(CHILD_BASE_ENV) | {"ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"}
    from pathlib import Path
    for i in range(2):
        assert observation_route(path, sha, {**SELECTOR, "ordinal": i}) == (
            Path(routes[i]["ingestionStateDirectory"]), Path(routes[i]["sources"]))
    for key, value in SELECTOR.items():
        changed = {**SELECTOR, key: value + 10 if type(value) is int else value + "x"}
        assert observation_route(path, sha, changed) is None
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="source_contexts_changed"):
        observation_route(path, sha, SELECTOR)


def test_duplicate_route_and_mixed_profile_refused(tmp_path):
    _, env, path, _, routes = profile(tmp_path)
    routes[1]["observations"] = copy.deepcopy(routes[0]["observations"])
    path.write_text(json.dumps({"schemaVersion": "zoop-handoff-source-contexts-1", "contexts": routes}))
    env["ZOOP_AI_SERVICE_OBSERVATION_SOURCE_CONTEXTS_SHA256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ConfigError, match="ZOOP_AI_SERVICE_OBSERVATION_SOURCE_CONTEXTS"):
        load(env)
    env["ZOOP_AI_INGESTION_STATE_DIR"] = routes[0]["ingestionStateDirectory"]
    with pytest.raises(ConfigError):
        load(env)


def test_singular_profile_and_bind_configuration(tmp_path):
    _, env, _, _, routes = profile(tmp_path)
    del env["ZOOP_AI_SERVICE_OBSERVATION_SOURCE_CONTEXTS"]
    del env["ZOOP_AI_SERVICE_OBSERVATION_SOURCE_CONTEXTS_SHA256"]
    env.update(ZOOP_AI_INGESTION_STATE_DIR=routes[0]["ingestionStateDirectory"], ZOOP_AI_SERVICE_SOURCES=routes[0]["sources"])
    assert load(env).host == "127.0.0.1"
    assert load({**env, "ZOOP_AI_SERVICE_HOST": "0.0.0.0"}).host == "0.0.0.0"
    assert load({**env, "ZOOP_AI_SERVICE_HOST": "::"}).host == "::"
    for host in ("localhost", "https://127.0.0.1", "224.0.0.1", "fe80::1%en0", ""):
        with pytest.raises(ConfigError):
            load({**env, "ZOOP_AI_SERVICE_HOST": host})


@pytest.mark.parametrize("changes", [{"observationId": "invented"}, {"requireStore": False}, {"stateDir": "/tmp/client"},
                                    {"page": True}, {"ordinal": -1}, {"schemaVersion": "unknown"}, {"round_id": "alias"}])
def test_closed_native_selector(changes):
    with pytest.raises(ValidationError):
        ObservationExportRequest.model_validate({"schemaVersion": "zoop-ingestion-s2-1", **SELECTOR, **changes})


def test_selector_requires_schema_and_all_fields():
    body = {"schemaVersion": "zoop-ingestion-s2-1", **SELECTOR}
    assert ObservationExportRequest.model_validate(body).wire() == body
    for key in body:
        with pytest.raises(ValidationError):
            ObservationExportRequest.model_validate({k: v for k, v in body.items() if k != key})


def environment(tmp_path):
    ws = Workspace(tmp_path)
    ingestion = tmp_path / "ingestion"
    ingestion.mkdir()
    sources = tmp_path / "sources.json"
    sources.write_text('{}')
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


def test_native_language_is_optional_bounded_and_preserved_without_normalization():
    observation = {**SELECTOR, "pageId": "page-0", "observedAt": "2026-10-29T00:00:00Z",
                   "url": "https://example.invalid/article", "title": "authored", "publishedAt": None,
                   "modifiedAt": None, "sourceRevision": None, "mediaType": "text/html"}
    assert NativeObservation.model_validate(observation).wire() == observation
    for language in ("ko", "en-US", "und", "x" * 35):
        declared = {**observation, "language": language}
        assert NativeObservation.model_validate(declared).wire() == declared
    for language in (None, "", "k", "x" * 36, 7):
        with pytest.raises(ValidationError):
            NativeObservation.model_validate({**observation, "language": language})
