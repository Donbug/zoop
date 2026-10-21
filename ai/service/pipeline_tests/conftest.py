from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from extraction_support import ExtractionService, ExtractionWorkspace, make_service, terminate_extraction
from relation_support import RelationService, RelationWorkspace, World, build_world, terminate_relation, tree
from real_handoff_support import BUILD_VERDICT_HANDOFF_WORLD, HandoffWorld, RealWorkspace, build_handoff_world
from support import ServiceProcess, remove_tree


@pytest.fixture(scope="session")
def world(tmp_path_factory: pytest.TempPathFactory) -> World:
    """One fresh synthetic operator world (actual ingestion + a READY S2 job + authored S3 fixtures) for the whole session."""
    return build_world(tmp_path_factory.mktemp("operator-world"))


@pytest.fixture(autouse=True)
def operator_state_is_never_written(world: World):
    """The service only reads the operator's ingestion and extraction ledgers: bytes, modes and sizes are identical after every test."""
    before = {"ingestion": tree(world.ingestion), "extraction": tree(world.extraction)}
    yield
    assert {"ingestion": tree(world.ingestion), "extraction": tree(world.extraction)} == before


@pytest.fixture
def start_relation(tmp_path: Path, world: World) -> Callable[..., RelationService]:
    """Factory for services over fresh private state. Everything it started (servers, orphaned relation children, temp dirs) is cleaned up."""
    started: list[RelationService] = []

    def factory(*, producer: Path | None = None, verifier: Path | None = None, listed: tuple[str, ...] = ("alpha", "beta"),
                env: dict[str, str | None] | None = None, launcher: bool = False, launcher_env: dict[str, str] | None = None,
                workspace: RelationWorkspace | None = None, wrapper: str | None = None, hold: bool = False, wait: bool = True,
                review_gate: bool = False) -> RelationService:
        if workspace is None:
            root = tmp_path / f"ws{len(started)}"
            root.mkdir()
            workspace = RelationWorkspace(root, world, producer=producer, verifier=verifier, listed=listed)
            if wrapper is not None:
                workspace.write_wrapper(wrapper)
            if review_gate:
                workspace.write_review_gate_wrapper()
        launcher_env = dict(launcher_env or {})
        if hold:
            launcher_env["ZOOP_TEST_RELATION_HOLD_FILE"] = str(workspace.root / "go")
        service = RelationService(workspace, env=workspace.env(**(env or {})), launcher=launcher or bool(launcher_env), launcher_env=launcher_env)
        started.append(service)
        return service.start(wait=wait)

    yield factory
    for service in started:
        service.close()
    workspaces = {id(service.workspace): service.workspace for service in started}
    for workspace in workspaces.values():
        terminate_relation(workspace)  # orphaned children die (and are proven gone) before their state is removed
    for workspace in workspaces.values():
        remove_tree(workspace.root)


@pytest.fixture
def start_extraction(tmp_path: Path, world: World) -> Callable[..., ExtractionService]:
    """Factory for S2 services over fresh private state and an EMPTY extraction ledger. Everything it started (servers, orphaned children, temp dirs)
    is cleaned up. `hold` keeps accepted jobs queued until `workspace.go()`."""
    started: list[ExtractionService] = []

    def factory(*, workspace: ExtractionWorkspace | None = None, hold: bool = False, wrapper: str | None = None, chain: bool = False,
                topic: bool = True, requests: tuple[str, ...] | None = None, wrapper_command: str = "resume", launcher_env: dict[str, str] | None = None,
                env: dict[str, str | None] | None = None, wait: bool = True) -> ExtractionService:
        if workspace is None:
            root = tmp_path / f"s2ws{len(started)}"
            root.mkdir()
            kwargs = {} if requests is None else {"requests": requests}
            workspace = ExtractionWorkspace(root, world, chain=chain, topic=topic, **kwargs)
            if wrapper is not None:
                workspace.write_wrapper(wrapper, wrapper_command)
        launcher_env = dict(launcher_env or {})
        if hold:
            launcher_env["ZOOP_TEST_EXTRACTION_HOLD_FILE"] = str(workspace.root / "extract-go")
        service = make_service(workspace, env=workspace.env(**(env or {})), launcher=bool(launcher_env), launcher_env=launcher_env)
        started.append(service)
        return service.start(wait=wait)

    yield factory
    for service in started:
        service.close()
    workspaces = {id(service.workspace): service.workspace for service in started}
    for workspace in workspaces.values():
        terminate_extraction(workspace)
        if workspace.chain:
            terminate_relation(workspace)
    for workspace in workspaces.values():
        remove_tree(workspace.root)


@pytest.fixture(scope="session")
def handoff_world(tmp_path_factory: pytest.TempPathFactory) -> HandoffWorld:
    """One fresh actual two-S3-job operator world with two frozen handoffs, built once by the pipeline's interpreter."""
    return build_handoff_world(tmp_path_factory.mktemp("handoff-world"))


@pytest.fixture(scope="session")
def verdict_world(tmp_path_factory: pytest.TempPathFactory) -> HandoffWorld:
    """One fresh actual two-S3-job world whose operator decisions carry SYNTHETIC per-field eventTime/period verdicts, with ONE handoff frozen and exported through the
    installed CLI by the pipeline's interpreter. `expect` holds the pipeline smoke's hand-written expectations."""
    return build_handoff_world(tmp_path_factory.mktemp("verdict-world"), BUILD_VERDICT_HANDOFF_WORLD)


def _handoff_services(tmp_path: Path, world: HandoffWorld):
    before = world.ledgers()
    started: list[ServiceProcess] = []

    def factory(exports: list[dict], *, env: dict[str, str | None] | None = None, launcher_env: dict[str, str] | None = None) -> tuple[RealWorkspace, ServiceProcess]:
        root = tmp_path / f"hws{len(started)}"
        workspace = RealWorkspace(root, world, exports)
        service = ServiceProcess(workspace, env=workspace.env(**(env or {})), launcher=bool(launcher_env), launcher_env=launcher_env)
        started.append(service)
        return workspace, service.start()

    yield factory
    for service in started:
        service.close()
    for service in started:
        remove_tree(service.workspace.root)
    assert world.ledgers() == before, "a read-only handoff door changed an operator ledger"


@pytest.fixture
def start_handoff(tmp_path: Path, handoff_world: HandoffWorld) -> Callable[..., tuple[RealWorkspace, ServiceProcess]]:
    """Factory for services over the real `zoop-ai-handoff`. The shared ledgers are checked byte for byte after every test: the service only reads them."""
    yield from _handoff_services(tmp_path, handoff_world)


@pytest.fixture
def start_verdict_handoff(tmp_path: Path, verdict_world: HandoffWorld) -> Callable[..., tuple[RealWorkspace, ServiceProcess]]:
    """The same factory over the reviewed (verdict) world and its own ledgers."""
    yield from _handoff_services(tmp_path, verdict_world)
