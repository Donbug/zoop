"""Configuration fails closed: exit 78, no listener, a field name and a stable reason only, never a configured value."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from support import Workspace, fixture
from zoop_ai_service import config as service_config
from zoop_ai_service.config import ConfigError, load


def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path, replay=fixture("synthetic-document", "replay"))


def principals(workspace: Workspace) -> list[dict]:
    return json.loads(workspace.credentials.principals_json())


def refused(env: dict[str, str]) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load(env)
    return caught.value


def test_valid_environment_loads_and_creates_private_state(tmp_path):
    ws = workspace(tmp_path)
    config = load(ws.env())
    assert config.port == ws.port and config.replay_path == ws.replay_path and not config.live_available
    assert oct(ws.state.stat().st_mode & 0o777) == "0o700" and oct((ws.state / "transport").stat().st_mode & 0o777) == "0o700"
    assert config.child_env["PATH"] == "/usr/bin:/bin" and "ZOOP_AI_SERVICE_PRINCIPALS" not in config.child_env
    assert "ZOOP_AI_LIVE_ENABLED" not in config.child_env


@pytest.mark.parametrize("mutate,reason", [
    (lambda entries: entries.clear(), "empty"),
    (lambda entries: entries[0].update(tokenSha256=["not-a-digest"]), "digest_invalid"),
    (lambda entries: entries[0].update(tokenSha256=["A" * 64]), "digest_invalid"),
    (lambda entries: entries[0].update(tokenSha256=[]), "digest_invalid"),
    (lambda entries: entries[0].update(tokenSha256=["a" * 64, "b" * 64, "c" * 64]), "digest_invalid"),
    (lambda entries: entries[0].update(scopes=[]), "scope_invalid"),
    (lambda entries: entries[0].update(scopes=["analysis.admin"]), "scope_invalid"),
    (lambda entries: entries[0].update(scopes=["analysis.read", "analysis.read"]), "scope_invalid"),
    (lambda entries: entries[0].update(principal="Not Valid"), "principal_invalid"),
    (lambda entries: entries[1].update(principal=entries[0]["principal"]), "principal_invalid"),
    (lambda entries: entries[1].update(tokenSha256=entries[0]["tokenSha256"]), "digest_invalid"),
    (lambda entries: entries[0].update(extra=True), "entry_shape"),
])
def test_principal_configuration_is_strict(tmp_path, mutate, reason):
    ws = workspace(tmp_path)
    entries = principals(ws)
    mutate(entries)
    error = refused(ws.env(ZOOP_AI_SERVICE_PRINCIPALS=json.dumps(entries)))
    assert (error.field, error.reason) == ("ZOOP_AI_SERVICE_PRINCIPALS", reason)


@pytest.mark.parametrize("raw,reason", [(None, "missing"), ("", "missing"), ("{not json", "not_json"), ("{}", "empty"), ("[1]", "entry_shape")])
def test_principals_missing_or_not_json(tmp_path, raw, reason):
    error = refused(workspace(tmp_path).env(ZOOP_AI_SERVICE_PRINCIPALS=raw))
    assert (error.field, error.reason) == ("ZOOP_AI_SERVICE_PRINCIPALS", reason)


def test_paths_must_be_absolute_unlinked_and_disjoint(tmp_path):
    ws = workspace(tmp_path)
    assert refused(ws.env(ZOOP_AI_SERVICE_STATE_DIR="relative/state")).reason == "not_absolute_normalized"
    assert refused(ws.env(ZOOP_AI_SERVICE_STATE_DIR=str(ws.state) + "/../other")).reason == "not_absolute_normalized"
    link = tmp_path / "linked"
    link.symlink_to(tmp_path / "real", target_is_directory=True)
    (tmp_path / "real").mkdir()
    assert refused(ws.env(ZOOP_AI_SERVICE_STATE_DIR=str(link))).reason == "symlinked_component"
    assert refused(ws.env(ZOOP_AI_WORKER_STATE_DIR=str(link / "w"))).reason == "symlinked_component"
    nested = refused(ws.env(ZOOP_AI_WORKER_STATE_DIR=str(ws.state / "worker")))
    assert (nested.field, nested.reason) == ("ZOOP_AI_SERVICE_STATE_DIR", "overlaps_worker_state")
    assert refused(ws.env(ZOOP_AI_WORKER_STATE_DIR=str(tmp_path))).reason == "overlaps_worker_state"
    assert refused(ws.env(ZOOP_STATE_DIR=str(ws.state))).reason == "overlaps_app_state"
    assert refused(ws.env(ZOOP_STATE_DIR=str(ws.worker))).field == "ZOOP_AI_WORKER_STATE_DIR"
    assert refused(ws.env(ZOOP_STATE_DIR="relative")).field == "ZOOP_STATE_DIR"
    assert refused(ws.env(ZOOP_AI_SERVICE_STATE_DIR=str(tmp_path / "missing" / "state"))).reason == "parent_missing"


def test_state_dir_that_others_can_read_is_refused(tmp_path):
    ws = workspace(tmp_path)
    ws.state.mkdir()
    ws.state.chmod(0o755)
    assert refused(ws.env()).reason == "state_dir_not_private"


def test_command_grants_replay_and_port(tmp_path):
    ws = workspace(tmp_path)
    assert refused(ws.env(ZOOP_AI_SERVICE_WORKER_COMMAND=None)).reason == "missing"
    assert refused(ws.env(ZOOP_AI_SERVICE_WORKER_COMMAND=str(tmp_path / "absent"))).field == "ZOOP_AI_SERVICE_WORKER_COMMAND"
    assert refused(ws.env(ZOOP_AI_SERVICE_WORKER_COMMAND=str(ws.grants_path))).reason == "file_unusable"  # not executable
    assert refused(ws.env(ZOOP_AI_SERVICE_GRANTS=str(tmp_path / "absent.json"))).field == "ZOOP_AI_SERVICE_GRANTS"
    ws.grants_path.write_text("{not json")
    assert refused(ws.env()).reason == "grant_registry_unreadable"
    ws.grants_path.write_text(json.dumps({"schemaVersion": "zoop-ai-s1-1", "grants": [{"grantId": "g"}]}))
    assert refused(ws.env()).reason == "grant_registry_schema_invalid"
    ws.grants_path.write_text(json.dumps({"schemaVersion": "zoop-ai-s1-1", "grants": []}))
    assert refused(ws.env(ZOOP_AI_SERVICE_REPLAY=str(tmp_path / "absent.json"))).field == "ZOOP_AI_SERVICE_REPLAY"
    for port in ("80", "70000", "abc", ""):
        assert refused(ws.env(ZOOP_AI_SERVICE_PORT=port)).field == "ZOOP_AI_SERVICE_PORT"


def test_live_is_enabled_only_with_opt_in_and_a_positive_ceiling(tmp_path):
    ws = workspace(tmp_path)
    for live, ceiling, expected in (("1", "5", True), ("1", "0", False), ("1", None, False), (None, "5", False), ("true", "5", False)):
        config = load(ws.env(ZOOP_AI_LIVE_ENABLED=live, ZOOP_AI_GLOBAL_MAX_CALLS=ceiling, ZOOP_AI_API_KEY="synthetic-key"))
        assert config.live_available is expected
        # Without the opt-in the child never receives either switch, so it cannot go live whatever else is set.
        assert ("ZOOP_AI_LIVE_ENABLED" in config.child_env) is expected
    assert refused(ws.env(ZOOP_AI_GLOBAL_MAX_CALLS="many")).field == "ZOOP_AI_GLOBAL_MAX_CALLS"


def test_child_environment_is_an_allowlist(tmp_path):
    ws = workspace(tmp_path)
    env = ws.env(ZOOP_AI_LIVE_ENABLED="1", ZOOP_AI_GLOBAL_MAX_CALLS="3", ZOOP_AI_DOCUMENT_SUMMARY_MODEL="m", HOME="/home/x",
                 ZOOP_STATE_DIR=str(tmp_path / "app"), AWS_SECRET_ACCESS_KEY="not-forwarded", OPENAI_API_KEY="not-forwarded")
    child = load(env).child_env
    assert set(child) == set(service_config.CHILD_BASE_ENV) | {"ZOOP_AI_LIVE_ENABLED", "ZOOP_AI_GLOBAL_MAX_CALLS", "ZOOP_AI_DOCUMENT_SUMMARY_MODEL"}


NATIVE = {"ZOOP_AI_VERIFY_PROVIDER": "typesafe-native", "TYPESAFE_API_KEY": "synthetic-jev-key",
          "TYPESAFE_BASE_URL": "http://127.0.0.1:9/v1", "TYPESAFE_VALIDATION_MODEL": "jev-1.14.0"}


def test_native_jev_selection_and_key_reach_the_s1_child_only_when_live_is_available(tmp_path):
    ws = workspace(tmp_path)
    closed = load(ws.env(ZOOP_AI_API_KEY="synthetic-key", **NATIVE))
    assert not closed.live_available and not set(NATIVE) & set(closed.child_env)
    live = load(ws.env(ZOOP_AI_LIVE_ENABLED="1", ZOOP_AI_GLOBAL_MAX_CALLS="3", ZOOP_AI_API_KEY="synthetic-key", **NATIVE))
    assert live.live_available and NATIVE.items() <= dict(live.child_env).items()
    # The key names only ever join the live-only group: the always-forwarded stage settings never carry a provider key.
    assert not {"TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "TYPESAFE_VALIDATION_MODEL"} & set(service_config.STAGE_SETTINGS)


def run_service(env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "zoop_ai_service.main"], env=env, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("break_it,field,reason", [
    (lambda ws: ws.env(ZOOP_AI_SERVICE_PRINCIPALS=None), "ZOOP_AI_SERVICE_PRINCIPALS", "missing"),
    (lambda ws: ws.env(ZOOP_AI_SERVICE_PRINCIPALS="[{" + ws.credentials.digest("alpha") + "]"), "ZOOP_AI_SERVICE_PRINCIPALS", "not_json"),
    (lambda ws: ws.env(ZOOP_AI_SERVICE_STATE_DIR="state"), "ZOOP_AI_SERVICE_STATE_DIR", "not_absolute_normalized"),
    (lambda ws: ws.env(ZOOP_AI_SERVICE_GRANTS=None), "ZOOP_AI_SERVICE_GRANTS", "missing"),
])
def test_refusal_is_a_process_exit_with_no_listener_and_no_values(tmp_path, break_it, field, reason):
    ws = workspace(tmp_path)
    done = run_service(break_it(ws))
    assert done.returncode == 78
    assert json.loads(done.stdout) == {"error": "service_config_invalid", "field": field, "reason": reason}
    assert done.stderr == ""
    for value in ws.private_strings():
        assert value not in done.stdout and value not in done.stderr
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", ws.port), timeout=0.3)


def test_second_instance_on_the_same_state_dir_is_refused_and_first_keeps_serving(tmp_path, start):
    first = start(replay=fixture("synthetic-document", "replay"))
    done = run_service(first.workspace.env())
    assert done.returncode == 78
    assert json.loads(done.stdout) == {"error": "service_config_invalid", "field": "ZOOP_AI_SERVICE_STATE_DIR", "reason": "service_state_busy"}
    assert first.request("GET", "/internal/v1/analysis-jobs/nothing").status_code == 404


def test_worker_ledger_binding_mismatch_is_refused(start):
    first = start(replay=fixture("synthetic-document", "replay"))
    ws = first.workspace
    first.stop()
    other = ws.root / "other-worker"
    done = run_service(ws.env(ZOOP_AI_WORKER_STATE_DIR=str(other)))
    assert done.returncode == 78
    assert json.loads(done.stdout) == {"error": "service_config_invalid", "field": "ZOOP_AI_WORKER_STATE_DIR",
                                       "reason": "worker_ledger_binding_mismatch"}
    assert not other.exists()  # the service never creates anything under a worker state dir
    again = run_service_started(ws)
    assert again.process.poll() is None
    again.close()


def run_service_started(ws: Workspace):
    from support import ServiceProcess
    return ServiceProcess(ws, env=ws.env()).start()


def test_service_never_listens_beyond_loopback(start):
    service = start(replay=fixture("synthetic-document", "replay"))
    if shutil.which("lsof"):
        listing = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", str(service.process.pid)], capture_output=True, text=True)
        if listing.returncode == 0 and listing.stdout:
            assert f"127.0.0.1:{service.workspace.port}" in listing.stdout and "*:" not in listing.stdout
    # The bind address is not a setting: a non-loopback local address of this host cannot reach the service.
    try:
        non_loopback = [a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith("127.")]
    except OSError:
        non_loopback = []
    for address in non_loopback[:1]:
        with pytest.raises(OSError):
            socket.create_connection((address, service.workspace.port), timeout=0.5)


@pytest.mark.parametrize("bad", [[], {}, ["known"], {"known": True}, 1, None, "KNOWN"])
def test_a_malformed_rights_value_is_a_registry_error_not_a_crash(tmp_path, bad):
    from zoop_ai_service import grants
    registry = json.loads(workspace(tmp_path).grants_path.read_text())
    registry["grants"][0]["rights"] = bad
    with pytest.raises(grants.GrantRegistryError) as caught:
        grants.parse(json.dumps(registry).encode())
    assert caught.value.code == "grant_registry_schema_invalid"


@pytest.mark.parametrize("field,bad", [("rights", []), ("rights", {}), ("enabled", []), ("expiresAt", []), ("grantId", []),
                                       ("recipients", [[]]), ("purposes", [{}]), ("allowedOperations", [[]]), ("evidence", [1])])
def test_startup_with_a_malformed_registry_exits_78_with_a_code_and_no_traceback(tmp_path, field, bad):
    ws = workspace(tmp_path)
    registry = json.loads(ws.grants_path.read_text())
    registry["grants"][0][field] = bad
    ws.grants_path.write_text(json.dumps(registry))
    done = run_service(ws.env())
    assert done.returncode == 78 and done.stderr == ""
    assert json.loads(done.stdout) == {"error": "service_config_invalid", "field": "ZOOP_AI_SERVICE_GRANTS",
                                       "reason": "grant_registry_schema_invalid"}
