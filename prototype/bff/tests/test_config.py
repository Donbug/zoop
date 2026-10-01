from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from zoop_bff.config import BFF_ROOT, DEFAULT_COMPANY_CATALOG, DEFAULT_SNAPSHOT_PATH, Settings


def test_default_paths_ignore_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("ZOOP_SOURCE", raising=False)
    monkeypatch.delenv("ZOOP_COMPANY_CATALOG", raising=False)
    monkeypatch.delenv("ZOOP_SNAPSHOT_PATH", raising=False)
    monkeypatch.delenv("ZOOP_STATE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = Settings.from_env()
    assert settings.state_dir == BFF_ROOT / "var"
    assert settings.snapshot_path == DEFAULT_SNAPSHOT_PATH
    assert settings.company_catalog == DEFAULT_COMPANY_CATALOG
    assert DEFAULT_COMPANY_CATALOG == BFF_ROOT.parents[2] / "InvestMateLogicTest/examples/synthetic/settings.json"


def test_live_source_was_removed_instead_of_silently_ignored(monkeypatch):
    # Users see the active published graph version; a stale ZOOP_SOURCE=live must not look accepted.
    monkeypatch.setenv("ZOOP_SOURCE", "live")
    with pytest.raises(ValueError, match="ZOOP_SOURCE=live was removed"):
        Settings.from_env()


def test_model_call_cap_bounds_the_default(monkeypatch):
    monkeypatch.setenv("ZOOP_ADMIN_MAX_MODEL_CALLS", "20")
    settings = Settings.from_env()
    assert (settings.admin_default_model_calls, settings.admin_max_model_calls) == (20, 20)
    monkeypatch.delenv("ZOOP_ADMIN_MAX_MODEL_CALLS")
    settings = Settings.from_env()
    assert (settings.admin_default_model_calls, settings.admin_max_model_calls) == (50, 200)


def test_catalog_override_stays_explicit(monkeypatch, tmp_path):
    catalog = tmp_path / "custom.json"
    monkeypatch.setenv("ZOOP_COMPANY_CATALOG", str(catalog))
    assert Settings.from_env().company_catalog == catalog


def test_default_catalog_follows_relocated_checkout(tmp_path):
    relocated = tmp_path / "zoop/prototype/bff/src/zoop_bff/config.py"
    relocated.parent.mkdir(parents=True)
    relocated.write_text((BFF_ROOT / "src/zoop_bff/config.py").read_text())
    namespace = runpy.run_path(str(relocated), run_name="zoop_bff_config_relocated_test")
    assert namespace["DEFAULT_COMPANY_CATALOG"] == tmp_path / "InvestMateLogicTest/examples/synthetic/settings.json"
    assert namespace["Settings"]().snapshot_path == tmp_path / "zoop/prototype/bff/fixtures/poc-synthetic-inspect.json"


def test_installed_layout_preserves_legacy_default(tmp_path, monkeypatch):
    installed = tmp_path / "venv/lib/python3.12/site-packages/zoop_bff/config.py"
    installed.parent.mkdir(parents=True)
    installed.write_text((BFF_ROOT / "src/zoop_bff/config.py").read_text())
    namespace = runpy.run_path(str(installed), run_name="zoop_bff_config_installed_test")
    assert namespace["DEFAULT_COMPANY_CATALOG"] == Path(
        "/Users/asqi/InvestMateLogicTest/examples/synthetic/settings.json"
    )
    catalog = tmp_path / "explicit.json"
    monkeypatch.setenv("ZOOP_COMPANY_CATALOG", str(catalog))
    assert namespace["Settings"].from_env().company_catalog == catalog


def test_relative_catalog_override_uses_working_directory(monkeypatch, tmp_path):
    from zoop_bff.sources import _load_catalog

    monkeypatch.chdir(tmp_path)
    (tmp_path / "catalog.json").write_text('{"companies": []}')
    monkeypatch.setenv("ZOOP_COMPANY_CATALOG", "catalog.json")
    settings = Settings.from_env()
    assert settings.company_catalog == Path("catalog.json")
    _, warnings, _ = _load_catalog(settings.company_catalog)
    assert warnings == []


def test_missing_sibling_catalog_is_visible_in_health(make_client, tmp_path):
    relocated = tmp_path / "zoop/prototype/bff/src/zoop_bff/config.py"
    relocated.parent.mkdir(parents=True)
    relocated.write_text((BFF_ROOT / "src/zoop_bff/config.py").read_text())
    namespace = runpy.run_path(str(relocated), run_name="zoop_bff_config_missing_test")
    catalog = namespace["DEFAULT_COMPANY_CATALOG"]
    assert not catalog.exists()
    client = make_client(company_catalog=catalog)
    response = client.get("/api/health")
    assert response.status_code == 200
    health = response.json()
    assert health["status"] == "degraded"
    assert health["source"]["mode"] == "snapshot"
    assert health["source"]["connected"] is True
    assert health["warnings"] == ["company catalog unreadable: settings.json (FileNotFoundError)"]
