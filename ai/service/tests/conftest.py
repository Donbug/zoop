from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

import pytest

from support import (ProviderStub, ServiceProcess, Workspace, live_workspace, outlook_replay, remove_tree, terminate_runtime,
                     semantic_job_and_entry)


def outlook_verify_replay() -> dict[str, Any]:
    """One outlook call, then one standalone verification call (an empty-round job in between consumes none)."""
    replay = copy.deepcopy(outlook_replay())
    replay["responses"].append(semantic_job_and_entry()[1])
    return replay


@pytest.fixture
def start(tmp_path: Path) -> Callable[..., ServiceProcess]:
    """Factory for services on fresh state. Everything it started (servers, orphaned runtime children, temp dirs) is cleaned up."""
    started: list[ServiceProcess] = []

    def factory(*, replay: dict[str, Any] | None = None, grants: dict[str, Any] | None = None,
                env: dict[str, str | None] | None = None, launcher: bool = False, launcher_env: dict[str, str] | None = None,
                workspace: Workspace | None = None, wait: bool = True) -> ServiceProcess:
        if workspace is None:
            root = tmp_path / f"ws{len(started)}"
            root.mkdir()
            workspace = Workspace(root, replay=replay, grants=grants)
        service = ServiceProcess(workspace, env=workspace.env(**(env or {})), launcher=launcher, launcher_env=launcher_env)
        started.append(service)
        return service.start(wait=wait)

    yield factory
    for service in started:
        service.close()
    for service in started:
        terminate_runtime(service.workspace.worker)  # orphaned workers die (and are proven gone) before their state is removed
    for service in started:
        remove_tree(service.workspace.root)


@pytest.fixture
def live(tmp_path: Path, provider: ProviderStub) -> Callable[..., tuple[Workspace, dict[str, str]]]:
    """Factory for a workspace whose grants name the loopback provider, plus the live opt-in environment pointing at it."""
    made = []

    def factory(ceiling: str = "20") -> tuple[Workspace, dict[str, str]]:
        root = tmp_path / f"live{len(made)}"
        root.mkdir()
        made.append(root)
        return live_workspace(root, provider, ceiling)

    return factory


@pytest.fixture
def provider() -> ProviderStub:
    stub = ProviderStub()
    yield stub
    stub.close()
