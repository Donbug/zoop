"""The service reaches the runtime only through the installed CLI: no imports, no ledger access, fixed argv, nameless transport files."""
from __future__ import annotations

import ast
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from support import ZOOP_AI, live_job, runtime_processes, terminate_runtime, wait_for

SOURCE = Path(__file__).resolve().parents[1] / "src" / "zoop_ai_service"
FORBIDDEN_ROOTS = {"zoop_ai", "zoop_ai_pipeline", "zoop_bff", "investmate_poc", "prototype"}


def imported_roots() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in SOURCE.rglob("*.py"):
        roots = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        found[path.name] = roots
    return found


def test_service_source_imports_nothing_from_the_runtime_pipeline_or_app():
    for name, roots in imported_roots().items():
        assert not roots & FORBIDDEN_ROOTS, name


def test_importing_the_service_does_not_load_the_runtime_even_though_it_is_installed():
    probe = ("import sys, importlib.util; assert importlib.util.find_spec('zoop_ai') is not None; "
             "import zoop_ai_service.app, zoop_ai_service.main, zoop_ai_service.openapi_doc; "
             "bad = sorted(m for m in sys.modules if m.split('.')[0] in {'zoop_ai', 'zoop_ai_pipeline', 'zoop_bff'}); "
             "print(bad)")
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip() == "[]", done.stderr


def test_service_never_names_the_worker_ledger_or_spawns_a_shell():
    for path in SOURCE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "worker.sqlite3" not in text and "shell=True" not in text and "os.system" not in text, path.name
        assert not re.search(r"\b(eval|exec)\(", text), path.name
        assert "os.environ" not in text or path.name == "main.py", path.name  # configuration is read once, at the entry point


def test_the_child_command_line_holds_only_configured_values_and_no_named_request_file_exists(start, provider, live):
    workspace, env = live()
    service = start(workspace=workspace, env=env)
    gate = provider.gate("document_summary")
    job = live_job()
    assert service.submit(job).status_code == 202
    assert gate.entered.wait(30)
    pids = wait_for(lambda: runtime_processes(workspace.worker), 10, 0.1, "the run child")
    assert len(pids) == 1
    command = subprocess.run(["ps", "-o", "command=", "-p", str(pids[0])], capture_output=True, text=True).stdout.strip()
    argv = shlex.split(command)
    assert argv[1:] == [str(ZOOP_AI), "run", "--state-dir", str(workspace.worker), "--grants", str(workspace.grants_path)]
    # Request data travels in an anonymous stdin file: nothing named exists under the transport directory.
    assert list((workspace.state / "transport").iterdir()) == []
    gate.release()
    service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    assert list((workspace.state / "transport").iterdir()) == []
    assert str(job["input"]["document"]["text"][:20]) not in command


def test_replay_runs_add_only_the_configured_fixture_path(start):
    from support import document_jobs, document_replay
    service = start(replay=document_replay())
    job = document_jobs()[0]
    service.submit(job)
    service.wait_state(job["jobId"], {"ready"}, dispatch={"idle"})
    # Nothing a request carries can name a path, command, URL, model or fixture: the whole Submit is data for the runtime.
    hostile = {**job, "jobId": "hostile-fields", "replay": "/etc/passwd", "command": "rm -rf /", "baseUrl": "http://evil.example"}
    assert service.submit(hostile).status_code == 422
    assert service.request("POST", "/internal/v1/analysis-jobs?replay=/etc/passwd&command=x", body=job, key=job["jobId"]).status_code == 200


def test_cleanup_finds_and_kills_an_orphaned_worker_before_state_is_removed(start, provider, live):
    workspace, env = live()
    service = start(workspace=workspace, env=env)
    gate = provider.gate("document_summary")
    assert service.submit(live_job()).status_code == 202
    assert gate.entered.wait(30)
    service.kill()  # the service dies; its runtime child is deliberately left running in its own session
    assert wait_for(lambda: runtime_processes(workspace.worker), 10, 0.1, "the orphaned worker")
    terminate_runtime(workspace.worker)
    assert runtime_processes(workspace.worker) == []


def test_process_lookup_failure_is_an_error_and_not_a_clean_no_match(tmp_path, monkeypatch):
    import support
    assert runtime_processes(tmp_path / "state with spaces (and.regex)") == []  # exit 1 is a genuine no-match
    failing = tmp_path / "pgrep"
    failing.write_text("#!/bin/sh\nexit 3\n")
    failing.chmod(0o755)
    monkeypatch.setattr(support, "PGREP", str(failing))
    with pytest.raises(RuntimeError):
        runtime_processes(tmp_path / "state")
    monkeypatch.setattr(support, "PGREP", str(tmp_path / "absent"))
    with pytest.raises(OSError):
        runtime_processes(tmp_path / "state")
