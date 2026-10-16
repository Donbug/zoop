"""`zoop-ai-graph preflight`: the read-only, ledger-free candidate check that runs before the one-time `init`.

The Neo4j driver boundary (`GraphDatabase.driver`) is replaced by `FakeNeo4j`, a small in-memory server that ANSWERS the adapter's closed read statements
from configured server state and records everything it is asked. It rejects (and records) every other statement, every non-read session and every commit,
so these tests observe the behavior of the real CLI -> Projector rules -> adapter stack, not that a function was called. TLS and authentication on the wire
are the driver's and the server's: they are proven only by `scripts/graph_tls_smoke.py` against a real Neo4j, never by this fake.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from neo4j import READ_ACCESS
from neo4j.exceptions import AuthError, ServiceUnavailable

from tests.test_ingestion import _installed
from zoop_ai_pipeline import graph_neo4j as neo
from zoop_ai_pipeline import graph_projection as gp
from zoop_ai_pipeline import graph_projection_cli as cli

SCHEMA = "zoop-graph-projection-1"
INIT = {"schemaVersion": SCHEMA, "storeId": "zoop-dev-graph", "database": "neo4j"}
TLS_URI = "bolt+s://neo4j.dev.zoop.internal:7687"
USER, PASSWORD = "svc-graph-operator", "correct horse battery 7421"
# The only statements a read-only probe may run, written out by hand (not read back from the adapter).
READ_ONLY = {neo.COMPONENTS, neo.DB_INFO, neo.COUNT_NODES, neo.COUNT_RELATIONSHIPS, neo.STORE_READ, neo.SHOW_CONSTRAINTS, neo.SHOW_INDEXES}
ALLOWED_DRIVER_KWARGS = {"connection_timeout", "connection_acquisition_timeout", "max_connection_pool_size", "disable_auto_commit_retries", "user_agent",
                         "telemetry_disabled"}


class Record(dict):
    def data(self) -> dict:
        return dict(self)


class FakeNeo4j:
    """One Neo4j 5 server's answers to the closed read statements, plus a record of every driver interaction."""

    def __init__(self, *, nodes=0, relationships=0, database="neo4j", db_id="d1b2c3", version="5.26.32", edition="community", stores=(), constraints=(), indexes=(),
                 password=PASSWORD, connect_error: Exception | None = None, name="Neo4j Kernel"):
        self.facts = dict(nodes=nodes, relationships=relationships, database=database, db_id=db_id, version=version, edition=edition, stores=list(stores),
                          constraints=list(constraints), indexes=list(indexes), name=name)
        self.password, self.connect_error = password, connect_error
        self.drivers: list[dict] = []
        self.begins = 0
        self.statements: list[str] = []
        self.session_modes: list = []
        self.violations: list[str] = []

    # what GraphDatabase.driver is replaced with
    def driver(self, uri, auth=None, **kwargs):
        self.drivers.append({"uri": uri, "auth": auth, "kwargs": kwargs})
        return _Driver(self)

    def rows(self, statement: str) -> list[dict]:
        f = self.facts
        if statement == neo.COMPONENTS:
            return [{"name": f["name"], "versions": [f["version"]], "edition": f["edition"]}]
        if statement == neo.DB_INFO:
            return [{"id": f["db_id"], "name": f["database"]}]
        if statement == neo.COUNT_NODES:
            return [{"c": f["nodes"]}]
        if statement == neo.COUNT_RELATIONSHIPS:
            return [{"c": f["relationships"]}]
        if statement == neo.STORE_READ:
            return f["stores"]
        if statement == neo.SHOW_CONSTRAINTS:
            return f["constraints"]
        if statement == neo.SHOW_INDEXES:
            return f["indexes"]
        raise AssertionError("not a read statement")


class _Driver:
    def __init__(self, fake: FakeNeo4j):
        self.fake = fake

    def session(self, database=None, default_access_mode=None, **_):
        self.fake.session_modes.append(default_access_mode)
        return _Session(self.fake)

    def close(self) -> None:
        pass


class _Session:
    def __init__(self, fake: FakeNeo4j):
        self.fake = fake

    def begin_transaction(self, **_):
        self.fake.begins += 1
        if self.fake.connect_error is not None:
            raise self.fake.connect_error
        auth = self.fake.drivers[-1]["auth"]
        if self.fake.password is not None and (auth is None or auth.credentials != self.fake.password):
            raise AuthError("The client is unauthorized due to authentication failure.")
        return _Tx(self.fake)

    def close(self) -> None:
        pass


class _Tx:
    def __init__(self, fake: FakeNeo4j):
        self.fake = fake

    def run(self, statement, params=None):
        self.fake.statements.append(statement)
        if statement not in READ_ONLY:
            self.fake.violations.append(statement)
            raise AssertionError("a read-only preflight issued a non-read statement")
        return [Record(row) for row in self.fake.rows(statement)]

    def commit(self) -> None:
        self.fake.violations.append("commit")
        raise AssertionError("a read-only preflight committed")

    def close(self) -> None:
        pass


def _no_network(*_a, **_k):
    raise AssertionError("a socket was used: the fake driver must be the only target")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("ZOOP_GRAPH_AUTH", "ZOOP_GRAPH_USER", "ZOOP_GRAPH_PASSWORD", "ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(socket, "getaddrinfo", _no_network)


def basic(monkeypatch, user: str = USER, password: str = PASSWORD) -> None:
    monkeypatch.setenv("ZOOP_GRAPH_AUTH", "basic")
    monkeypatch.setenv("ZOOP_GRAPH_USER", user)
    monkeypatch.setenv("ZOOP_GRAPH_PASSWORD", password)


def serve(monkeypatch, fake: FakeNeo4j) -> FakeNeo4j:
    monkeypatch.setattr(neo, "GraphDatabase", SimpleNamespace(driver=fake.driver))
    return fake


def run(command: str, state: Path, *, uri: str | None = TLS_URI, request=INIT, expected: int, raw: bytes | None = None, extra: tuple = ()):
    argv = ["zoop-ai-graph", command, "--state-dir", str(state)]
    if uri is not None:
        argv += ["--graph-uri", uri]
    argv += list(extra)
    out = io.StringIO()
    data = raw if raw is not None else json.dumps(request).encode()
    with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(data))), contextlib.redirect_stdout(out):
        code = cli.main()
    text = out.getvalue()
    assert code == expected, text
    assert text.endswith("\n") and text.count("\n") == 1, text
    return json.loads(text), text


def failure(out: dict, code: str, detail: dict | None = None) -> None:
    assert out == {"schemaVersion": SCHEMA, "error": {"code": code, **({"detail": detail} if detail else {})}}, out


def snapshot(path: Path) -> dict:
    """Every entry under (and including) the path: type, mode, size, mtime, content. Equal before and after means nothing was created, chmod-ed or written."""
    found = {}
    for item in [path, *sorted(path.rglob("*"))]:
        info = item.lstat()
        found[str(item)] = (stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_size, info.st_mtime_ns, item.read_bytes() if item.is_file() else None)
    return found


def read_only(fake: FakeNeo4j) -> None:
    assert fake.violations == [] and set(fake.statements) <= READ_ONLY and fake.statements
    assert fake.session_modes and set(fake.session_modes) == {READ_ACCESS}


def constraint(name="zg_company_vk", kind="UNIQUENESS", entity="NODE", label="ZgCompany", prop="vk") -> dict:
    return {"name": name, "type": kind, "entityType": entity, "labelsOrTypes": [label], "properties": [prop]}


def index(name="zg_company_v", kind="RANGE", label="ZgCompany", prop="v", state="ONLINE") -> dict:
    return {"name": name, "type": kind, "entityType": "NODE", "labelsOrTypes": [label], "properties": [prop], "state": state}


# ---------------------------------------------------------------- the eligible candidate ---------------------------------------------------

@pytest.mark.parametrize(("uri", "tls"), [(TLS_URI, "verified"), ("bolt://127.0.0.1:7687", "loopback-plain")])
def test_an_empty_reachable_target_is_an_eligible_candidate_and_nothing_is_written_anywhere(tmp_path, monkeypatch, uri, tls):
    fake = serve(monkeypatch, FakeNeo4j(password=PASSWORD if tls == "verified" else None))
    if tls == "verified":
        basic(monkeypatch)
    else:
        monkeypatch.setenv("ZOOP_GRAPH_AUTH", "none")
    state = tmp_path / "ws" / "graph"
    out, text = run("preflight", state, uri=uri, expected=0)
    assert out == {"schemaVersion": SCHEMA, "usage": {"providerCalls": 0, "modelCalls": 0},
                   "preflight": {"result": "eligible-empty-target", "ddlPermission": "unverified", "tls": tls, "ledger": "absent",
                                 "server": {"agent": "Neo4j/5.26.32", "edition": "community"}, "database": "neo4j", "dbId": "d1b2c3",
                                 "counts": {"nodes": 0, "relationships": 0}, "schemaObjects": {"constraints": 0, "indexes": 0}}}
    # No ledger, directory, lock or parent was created; the closed read statements only; read sessions only; no commit.
    assert not (tmp_path / "ws").exists()
    read_only(fake)
    # One driver, built from exactly the target the operator named (no rewrite, no trust override), one connection attempt, no retry.
    assert len(fake.drivers) == 1 and fake.drivers[0]["uri"] == uri and set(fake.drivers[0]["kwargs"]) == ALLOWED_DRIVER_KWARGS
    assert fake.drivers[0]["kwargs"]["disable_auto_commit_retries"] is True
    # Nothing identifying the operator, the credentials, the target host or the workspace is part of the answer.
    for secret in (USER, PASSWORD, "dev.zoop.internal", "127.0.0.1", "bolt", str(tmp_path), "owner"):
        assert secret not in text, secret


def test_an_existing_empty_directory_is_untouched_and_a_partial_expected_schema_is_still_eligible(tmp_path, monkeypatch):
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j(constraints=[constraint()], indexes=[index()]))
    state = tmp_path / "graph"
    state.mkdir(mode=0o755)
    state.chmod(0o755)
    before = snapshot(state)
    out, _ = run("preflight", state, expected=0)
    assert out["preflight"]["schemaObjects"] == {"constraints": 1, "indexes": 1} and out["preflight"]["ledger"] == "absent"
    assert snapshot(state) == before and stat.S_IMODE(state.stat().st_mode) == 0o755   # not chmod-ed to 0700 as `init` would
    read_only(fake)


# ---------------------------------------------------------------- the same refusals as init ------------------------------------------------

REFUSALS = {
    "nodes": (dict(nodes=3), "graph_store_not_empty"),
    "relationships": (dict(relationships=1), "graph_store_not_empty"),
    "store marker": (dict(nodes=1, stores=[{"l": ["ZgStore"], "p": {"slot": "store", "storeId": "other", "schema": "x", "owner": "someone-else"}}]), "graph_store_not_empty"),
    "foreign index": (dict(indexes=[index(name="app_user_email", label="User", prop="email")]), "graph_store_not_empty"),
    "foreign constraint": (dict(constraints=[constraint(name="app_user_id", label="User", prop="id")]), "graph_store_not_empty"),
    "expected name, other definition": (dict(constraints=[constraint(label="Other")]), "graph_store_schema_mismatch"),
    "expected index name, failed": (dict(indexes=[index(state="FAILED")]), "graph_store_schema_mismatch"),
    "other database": (dict(database="other"), "graph_store_identity_mismatch"),
    "unsupported server": (dict(version="4.4.30"), "graph_server_unsupported"),
    "not neo4j": (dict(name="Something Else"), "graph_server_unsupported"),
}


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_preflight_refuses_exactly_what_init_refuses_and_writes_nothing(tmp_path, monkeypatch, name):
    server, code = REFUSALS[name]
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j(**server))
    state = tmp_path / "ws" / "graph"
    failure(run("preflight", state, expected=2)[0], code)
    assert not (tmp_path / "ws").exists()
    read_only(fake)
    # The very same answer from the same server makes `init` refuse with the same code, before any DDL or marker (it records no non-read statement).
    init_fake = serve(monkeypatch, FakeNeo4j(**server))
    failure(run("init", tmp_path / "init-ledger", expected=2)[0], code)
    assert init_fake.violations == [] and set(init_fake.statements) <= READ_ONLY


def test_a_wrong_password_is_one_attempt_with_a_stable_code_and_no_state(tmp_path, monkeypatch):
    basic(monkeypatch, password="not the password")
    fake = serve(monkeypatch, FakeNeo4j())
    out, text = run("preflight", tmp_path / "ws" / "graph", expected=2)
    failure(out, "graph_auth_failed")
    assert len(fake.drivers) == 1 and fake.begins == 1 and fake.statements == []   # no automatic retry
    assert "not the password" not in text and not (tmp_path / "ws").exists()


def test_an_unreachable_server_is_a_stable_code_after_one_attempt(tmp_path, monkeypatch):
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j(connect_error=ServiceUnavailable("tls handshake failed for neo4j.dev.zoop.internal /private/path")))
    out, text = run("preflight", tmp_path / "ws" / "graph", expected=2)
    failure(out, "graph_unavailable", {"driver": "ServiceUnavailable"})
    assert fake.begins == 1 and len(fake.drivers) == 1 and "zoop.internal" not in text and "/private" not in text and not (tmp_path / "ws").exists()


# ---------------------------------------------------------------- refused before any connection --------------------------------------------

@pytest.mark.parametrize("uri", ["bolt+ssc://neo4j.dev.zoop.internal:7687", "neo4j+s://neo4j.dev.zoop.internal:7687", "bolt://neo4j.dev.zoop.internal:7687",
                                 "bolt+s://op:secret@neo4j.dev.zoop.internal:7687", "bolt+s://neo4j.dev.zoop.internal", "bolt+s://neo4j.dev.zoop.internal:7687/neo4j",
                                 "bolt+s://neo4j.dev.zoop.internal:7687?x=1", "http://127.0.0.1:7687", "bolt+s://under_score.example:7687", ""])
def test_unsafe_targets_are_refused_before_any_driver_or_socket_and_leave_no_state(tmp_path, monkeypatch, uri):
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j())
    out, text = run("preflight", tmp_path / "ws" / "graph", uri=uri, expected=2)
    failure(out, "graph_uri_invalid")
    assert fake.drivers == [] and not (tmp_path / "ws").exists() and "secret" not in text


@pytest.mark.parametrize("env", [{}, {"ZOOP_GRAPH_AUTH": "none"}, {"ZOOP_GRAPH_AUTH": "basic"}, {"ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": "u"},
                                 {"ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_PASSWORD": "p"}, {"ZOOP_GRAPH_AUTH": "token", "ZOOP_GRAPH_USER": "u", "ZOOP_GRAPH_PASSWORD": "p"}])
def test_a_tls_target_without_complete_basic_credentials_is_refused_before_any_connection(tmp_path, monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    fake = serve(monkeypatch, FakeNeo4j())
    failure(run("preflight", tmp_path / "ws" / "graph", expected=2)[0], "graph_auth_unconfigured")
    assert fake.drivers == [] and not (tmp_path / "ws").exists()


def test_malformed_stdin_and_unrelated_flags_are_refused_before_state_or_connection(tmp_path, monkeypatch):
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j())
    state = tmp_path / "ws" / "graph"
    for raw in (b"", b"[]", b"{not json", b"\xff", json.dumps({**INIT, "database": "system"}).encode(), json.dumps({**INIT, "storeId": "a b"}).encode(),
                json.dumps({**INIT, "extra": 1}).encode(), json.dumps({"schemaVersion": SCHEMA, "versionId": "v1"}).encode()):
        failure(run("preflight", state, raw=raw, expected=2)[0], "input_or_configuration_invalid")
    failure(run("preflight", state, raw=b"x" * 70_000, expected=2)[0], "command_input_limit")
    failure(run("preflight", state, uri=None, expected=2)[0], "input_or_configuration_invalid")   # a target is required
    for extra in (("--sources", str(tmp_path / "s.json")), ("--canonical", str(tmp_path / "c.json")), ("--relation-state-dir", str(tmp_path / "r"))):
        failure(run("preflight", state, expected=2, extra=extra)[0], "input_or_configuration_invalid")   # a source flag is never accepted
    failure(run("inspect", state, expected=2, request={"schemaVersion": SCHEMA, "versionId": "v1"})[0], "input_or_configuration_invalid")   # still init|preflight only
    assert fake.drivers == [] and not (tmp_path / "ws").exists()


# ---------------------------------------------------------------- placement and ownership: pure, read-only, before any connection ----------

def test_an_existing_ledger_is_refused_unchanged_unlocked_and_without_a_connection(tmp_path, monkeypatch):
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j())
    state = tmp_path / "graph"
    gp.Store(state, mode="create").close()
    before = snapshot(state)
    failure(run("preflight", state, expected=2)[0], "graph_store_already_bound")
    assert snapshot(state) == before and fake.drivers == []
    held = gp.Store(state, mode="write")   # a running writer holds the exclusive lock: preflight neither waits for it nor needs it
    try:
        failure(run("preflight", state, expected=2)[0], "graph_store_already_bound")
    finally:
        held.close()


def test_foreign_or_non_directory_state_is_refused_unchanged_before_any_connection(tmp_path, monkeypatch):
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j())
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("not ours")
    a_file = tmp_path / "a-file"
    a_file.write_text("x")
    inside = tmp_path / "inside"
    inside.mkdir()
    (inside / "graph.sqlite3").symlink_to(a_file)
    for candidate in (foreign, a_file, inside):
        before = snapshot(candidate)
        failure(run("preflight", candidate, expected=2)[0], "state_namespace_conflict")
        assert snapshot(candidate) == before
    assert fake.drivers == []


def test_symlinked_ancestors_even_dangling_ones_are_refused_without_following_them(tmp_path, monkeypatch):
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j())
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    (tmp_path / "dangling").symlink_to(tmp_path / "nowhere")
    for candidate in (tmp_path / "link" / "state", tmp_path / "link", tmp_path / "dangling", tmp_path / "dangling" / "state"):
        failure(run("preflight", candidate, expected=2)[0], "state_namespace_invalid")
    assert list(real.iterdir()) == [] and not (tmp_path / "nowhere").exists() and fake.drivers == []


def test_a_location_inside_or_around_a_reserved_state_root_is_refused(tmp_path, monkeypatch):
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j())
    app, worker = tmp_path / "reserved" / "app-state", tmp_path / "reserved" / "worker-state"
    monkeypatch.setenv("ZOOP_STATE_DIR", str(app))
    monkeypatch.setenv("ZOOP_AI_WORKER_STATE_DIR", str(worker))
    for candidate in (app, app / "graph", worker / "graph", tmp_path / "reserved", tmp_path):
        failure(run("preflight", candidate, expected=2)[0], "state_namespace_conflict")
    assert not (tmp_path / "reserved").exists() and fake.drivers == []
    out, _ = run("preflight", tmp_path / "graph", expected=0)   # a disjoint location is fine with the same ownership variables
    assert out["preflight"]["ledger"] == "absent" and not (tmp_path / "graph").exists()


def test_an_installed_package_without_ownership_variables_stops_before_any_connection(tmp_path, monkeypatch):
    _installed(monkeypatch, tmp_path)
    basic(monkeypatch)
    fake = serve(monkeypatch, FakeNeo4j())
    state = tmp_path / "ws" / "graph"
    for present in ((), ("ZOOP_STATE_DIR",), ("ZOOP_AI_WORKER_STATE_DIR",)):
        for key in present:
            monkeypatch.setenv(key, str(tmp_path / key.lower()))
        failure(run("preflight", state, expected=2)[0], "state_ownership_unconfigured")
        for key in present:
            monkeypatch.delenv(key)
    monkeypatch.setenv("ZOOP_STATE_DIR", "relative/app")
    monkeypatch.setenv("ZOOP_AI_WORKER_STATE_DIR", str(tmp_path / "worker"))
    failure(run("preflight", state, expected=2)[0], "state_ownership_unconfigured")
    assert fake.drivers == [] and not (tmp_path / "ws").exists()
    monkeypatch.setenv("ZOOP_STATE_DIR", str(tmp_path / "app"))
    assert run("preflight", state, expected=0)[0]["preflight"]["result"] == "eligible-empty-target"


def test_a_user_named_like_the_database_cannot_make_the_privacy_check_vacuous(tmp_path, monkeypatch):
    # With basic auth on Community the only user is `neo4j`, the same word as the database name in every answer. The credential that must never appear is the
    # password; a username that equals a legitimate constant of the answer is not a leak, and a password must not be a legitimate constant of the answer.
    basic(monkeypatch, user="neo4j", password="zq-secret-91af")
    serve(monkeypatch, FakeNeo4j(password="zq-secret-91af"))
    out, text = run("preflight", tmp_path / "ws" / "graph", expected=0)
    assert out["preflight"]["database"] == "neo4j" and "zq-secret-91af" not in text
    assert "ZOOP_GRAPH" not in text and "auth" not in text.lower()
    assert os.environ["ZOOP_GRAPH_PASSWORD"] not in text
