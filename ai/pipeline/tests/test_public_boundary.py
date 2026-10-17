"""The whole pipeline (collection, ingestion, extraction, relation, dependents, graph, handoff) is native: it installs and runs with public
packages only and never imports the original PoC (`investmate`), whether or not that package happens to exist in the interpreter."""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
SOURCE = PIPELINE / "src" / "zoop_ai_pipeline"
MODULES = sorted(p.stem for p in SOURCE.glob("*.py") if p.stem != "__init__")
BLOCK = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "investmate" or name.startswith("investmate."):
            raise ModuleNotFoundError(name)
sys.meta_path.insert(0, Block())
"""
CLIS = {
    "extraction_cli": ["run", "--state-dir", "/nonexistent/s", "--ingestion-state-dir", "/nonexistent/i", "--sources", "/nonexistent/r.json"],
    "relation_cli": ["inspect", "--state-dir", "/nonexistent/s", "--extraction-state-dir", "/nonexistent/e", "--ingestion-state-dir", "/nonexistent/i",
                     "--sources", "/nonexistent/r.json"],
    "dependency_cli": ["--ingestion-state-dir", "/nonexistent/i", "--extraction-state-dir", "/nonexistent/e"],
    "graph_projection_cli": ["inspect", "--state-dir", "/nonexistent/s"],
    "handoff_cli": ["inspect", "--state-dir", "/nonexistent/s"],
}


def run(code: str, *, stdin: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-c", BLOCK + code], input=stdin, capture_output=True, timeout=120, cwd=PIPELINE)


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0]
    return {name.split(".")[0] for name in names}


def test_no_source_script_or_test_imports_the_poc_and_the_old_adapter_and_guard_are_gone():
    files = [*SOURCE.glob("*.py"), *(PIPELINE / "scripts").glob("*.py"), *(PIPELINE / "tests").glob("*.py")]
    assert len(files) > 30
    assert [str(f.relative_to(PIPELINE)) for f in files if "investmate" in imported_roots(f)] == []
    assert not (SOURCE / "poc_guard.py").exists() and not (SOURCE / "extraction_poc.py").exists()


@pytest.mark.parametrize("module", MODULES)
def test_every_pipeline_module_imports_with_the_poc_blocked(module):
    child = run(f"import importlib\nimportlib.import_module('zoop_ai_pipeline.{module}')\nimport sys\nassert not [m for m in sys.modules if m.split('.')[0] == 'investmate']")
    assert child.returncode == 0, child.stderr.decode()[-800:]


def test_native_collection_ingestion_and_parsers_work_with_the_poc_blocked():
    code = """
import json
from zoop_ai_pipeline import ingestion_parsers as parsers
from zoop_ai_pipeline.ingestion_url import canonical_url
profile = parsers.profile('//article')
assert profile["parser"] and "pocCommit" not in profile and profile["articleXPath"] == "//article", profile
prepared = parsers.prepare("<article><p>native 😀 text</p></article>".encode(), "text/html", None)
assert prepared["text"] == "native 😀 text", prepared["text"]
assert canonical_url("HTTPS://Example.Invalid:443/a#x")[0] == "https://example.invalid/a"
print(json.dumps({"ok": True}))
"""
    child = run(code)
    assert child.returncode == 0 and json.loads(child.stdout) == {"ok": True}, child.stderr.decode()


@pytest.mark.parametrize("module", CLIS)
def test_every_command_answers_with_its_own_json_error_when_the_poc_is_blocked(module):
    """With no input the command stops at its own input validation: a stable JSON error, never an ImportError or a PoC-availability code."""
    code = f"import sys\nsys.argv = ['{module}', *{CLIS[module]!r}]\nfrom zoop_ai_pipeline.{module} import main\nraise SystemExit(main())"
    child = run(code)
    assert child.returncode == 2 and child.stderr == b"", child.stderr.decode()
    result = json.loads(child.stdout)
    assert result["schemaVersion"].startswith("zoop-") and result["error"] == {"code": "input_or_configuration_invalid"}, result


def test_the_manifest_and_lock_name_no_poc_package_source_or_extra():
    project = tomllib.loads((PIPELINE / "pyproject.toml").read_text(encoding="utf-8"))
    assert "optional-dependencies" not in project["project"] and not [d for d in project["project"]["dependencies"] if d.startswith("investmate")]
    assert "investmate-poc" not in project.get("tool", {}).get("uv", {}).get("sources", {})
    assert project["project"]["scripts"]["zoop-ai-collect"] == "zoop_ai_pipeline.collection_cli:main"
    lock = tomllib.loads((PIPELINE / "uv.lock").read_text(encoding="utf-8"))
    assert not [p["name"] for p in lock["package"] if "investmate" in p["name"]]
    root = next(p for p in lock["package"] if p["name"] == "zoop-ai-pipeline")
    assert "optional-dependencies" not in root and "provides-extras" not in root.get("metadata", {})
    assert "investmate" not in (PIPELINE / "uv.lock").read_text(encoding="utf-8") and "investmate" not in (PIPELINE / "pyproject.toml").read_text(encoding="utf-8")


def test_the_interpreter_running_the_suite_has_no_poc_installed():
    assert importlib.util.find_spec("investmate") is None
