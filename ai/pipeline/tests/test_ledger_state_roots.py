"""State-root ownership for the extraction and relation ledgers.

The ingestion ledger's own versions of these checks live in test_ingestion.py."""
from __future__ import annotations

import pytest

from tests.test_ingestion import _installed
from zoop_ai_pipeline.extraction import Store as ExtractionStore
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, reserved_state_roots
from zoop_ai_pipeline.relation import Store as RelationStore


def test_extraction_and_relation_ledgers_never_adopt_reserved_roots(tmp_path):
    for root in reserved_state_roots():
        for candidate in (root, root / "ingestion", root.parent):
            with pytest.raises(Exception, match="state_namespace_conflict"):
                ExtractionStore(candidate, tmp_path / "ingestion")
            with pytest.raises(Exception, match="state_namespace_conflict"):
                RelationStore(candidate, tmp_path / "extraction", tmp_path / "ingestion")


def test_installed_package_without_ownership_roots_stops_extraction_and_relation_ledgers(monkeypatch, tmp_path):
    _installed(monkeypatch, tmp_path)
    for unset in (("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"), ("ZOOP_STATE_DIR",), ("ZOOP_AI_WORKER_STATE_DIR",)):
        for key in ("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"):
            monkeypatch.setenv(key, str(tmp_path / key.lower()))
        for key in unset:
            monkeypatch.delenv(key)
        with pytest.raises(IngestionFailure, match="state_ownership_unconfigured"):
            ExtractionStore(tmp_path / "ledger", tmp_path / "ingestion")
        with pytest.raises(IngestionFailure, match="state_ownership_unconfigured"):
            RelationStore(tmp_path / "ledger", tmp_path / "extraction", tmp_path / "ingestion")
    assert not (tmp_path / "ledger").exists()
