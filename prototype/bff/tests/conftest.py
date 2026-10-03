from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from zoop_bff.admin_services import AdminServices, build_admin_services
from zoop_bff.app import create_app
from zoop_bff.config import DEFAULT_SNAPSHOT_PATH, Settings

from .fakes import FakeLauncher, FakeLedger, FakeNeo4j, FakeSandbox

ALPHA_ISSUES = {
    "q1": "issue-b4c3b887f7cbb6aa9ca6f2cf",
    "plant": "issue-274a2d51925bcf4e2a20ae5a",
    "q2": "issue-89ad5ad44679f34fb1c2c255",
}
HELD_ISSUE = "issue-bf022d03d6a71a1bb359e610"  # HOLD in the PoC fixture
HELD_ARTICLE = "synthetic-unknown"
DEMO = {"email": "demo@zoop.local", "password": "zoop-demo"}
ADMIN = {"email": "admin@zoop.local", "password": "zoop-admin"}


def base_payload() -> dict[str, Any]:
    return json.loads(DEFAULT_SNAPSHOT_PATH.read_text(encoding="utf-8"))


def with_companies(payload: dict[str, Any], count: int = 5) -> dict[str, Any]:
    payload["zoop"] = {
        **payload.get("zoop", {}),
        "companies": [
            {"company_id": f"SYNTH-C{i}", "name": f"합성 기업{i}", "ticker": f"C{i:04d}", "aliases": []}
            for i in range(count)
        ],
    }
    return payload


@pytest.fixture
def make_client(tmp_path: Path) -> Callable[..., TestClient]:
    built = 0

    def build(payload: dict[str, Any] | None = None, **settings: Any) -> TestClient:
        # Every client gets its own snapshot and state directory: a graph version is immutable once
        # registered, so a second payload must never meet an earlier client's v1.
        nonlocal built
        built += 1
        path = tmp_path / f"snapshot-{built}.json"
        path.write_text(json.dumps(payload if payload is not None else base_payload()), encoding="utf-8")
        settings.setdefault("company_catalog", None)
        settings.setdefault("state_dir", tmp_path / f"state-{built}")
        settings.setdefault("briefing_scheduler", False)
        return TestClient(create_app(Settings(snapshot_path=path, **settings)))

    return build


@dataclass
class AdminKit:
    client: TestClient
    services: AdminServices
    ledger: FakeLedger
    neo4j: FakeNeo4j
    sandbox: FakeSandbox
    launcher: FakeLauncher
    settings: Settings
    state_dir: Path
    market: Any = None

    @property
    def clock(self):
        return self.services.clock

    def login(self, client: TestClient | None = None) -> TestClient:
        target = client or self.client
        response = target.post("/api/admin/auth/login", json=ADMIN)
        assert response.status_code == 200, response.text
        return target

    def restart(self) -> AdminKit:
        """A new app over the same state directory, ledger and sandbox (a BFF process restart)."""
        return _assemble(self.settings, self.ledger, self.neo4j, self.sandbox, self.launcher, self.market)


def _assemble(settings, ledger, neo4j, sandbox, launcher, market=None) -> AdminKit:
    services = build_admin_services(settings, ledger=ledger, neo4j=neo4j, sandbox=sandbox, launcher=launcher, market=market)
    client = TestClient(create_app(settings, services=services))
    return AdminKit(client, services, ledger, neo4j, sandbox, launcher, settings, settings.state_dir, market)


@pytest.fixture
def make_admin(tmp_path: Path) -> Callable[..., AdminKit]:
    """BFF with the admin side wired to fakes (ledger, Neo4j, sandbox, CLI child)."""
    built = 0

    def build(
        payload: dict[str, Any] | None = None, *, ledger_payload: dict[str, Any] | None = None, market: Any = None, **settings: Any
    ) -> AdminKit:
        nonlocal built
        built += 1
        seed = payload if payload is not None else base_payload()
        snapshot = tmp_path / f"admin-snapshot-{built}.json"
        snapshot.write_text(json.dumps(seed), encoding="utf-8")
        settings.setdefault("company_catalog", None)
        settings.setdefault("state_dir", tmp_path / f"admin-state-{built}")
        settings.setdefault("briefing_scheduler", False)
        config = Settings(snapshot_path=snapshot, **settings)
        ledger = FakeLedger(copy.deepcopy(ledger_payload if ledger_payload is not None else seed))
        sandbox = FakeSandbox(tmp_path / f"admin-sandbox-{built}")
        return _assemble(config, ledger, FakeNeo4j(ledger), sandbox, FakeLauncher(), market)

    return build


@pytest.fixture
def admin(make_admin: Callable[..., AdminKit]) -> AdminKit:
    # Tests that move the clock by hours must not trip the idle timeout; test_admin_auth covers it.
    kit = make_admin(admin_idle_seconds=7 * 86400, admin_absolute_seconds=30 * 86400)
    kit.login()
    return kit


def jobs_settled(kit: AdminKit) -> None:
    """Wait for every job monitor thread to end (jobs run in background threads)."""
    for thread in list(kit.services.jobs._threads.values()):
        thread.join(timeout=10)


@pytest.fixture
def member(make_client: Callable[..., TestClient]) -> TestClient:
    client = make_client(with_companies(base_payload()))
    assert client.post("/api/auth/login", json=DEMO).status_code == 200
    return client


def fresh(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return copy.deepcopy(payload if payload is not None else base_payload())
