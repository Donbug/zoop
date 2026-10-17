"""The real `zoop-ai-extract` process over stored pre-cutover (legacy-adapter) jobs, with NO usable source registry.

A legacy job is history: `inspect` shows what was stored, `resume`/`run` refuse with `analysis_contract_changed`, `cancel` still retires it. None of
that needs the operator registry, so a missing or malformed `--sources` file must not turn these answers into `input_or_configuration_invalid`, and a
*valid* registry must not even be read. Read-only answers must leave the ledger untouched (content, schema, modes, `updated_at`) and add no call.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.extraction_smoke import CUSTOM, PIPELINE
from scripts.ingestion_smoke import json_bytes, ownership_env
from tests.legacy_ledger import copy_as_legacy, counts, ledger, rows
from tests.test_extraction import Q3B, event, same_of, world  # noqa: F401  (`world` is the fixture of test_extraction)
from tests.test_extraction_replay import run_native

REGISTRY_PROBE = """
import os, sys
_TARGET, _MARK = {target!r}, {mark!r}
def _audit(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)) and os.path.basename(os.fsdecode(args[0])) == _TARGET:
        open(_MARK, "w").close()
        raise RuntimeError("the operator registry was read")
sys.addaudithook(_audit)
"""
KINDS = ["missing", "malformed", "valid-but-must-not-be-read"]
UNCHANGED = "analysis_contract_changed"


def sources_for(k, kind: str) -> tuple[Path, str | None]:
    """(--sources path, basename the audit probe forbids). The valid registry is a copy under a unique name so only that name is forbidden."""
    if kind == "missing":
        return k.root / "no-such-registry.json", None
    if kind == "malformed":
        path = k.root / "malformed-registry.json"
        path.write_bytes(b"{not json")
        return path, None
    path = k.root / "forbidden-registry.json"
    path.write_bytes(k.registry_path.read_bytes())
    return path, path.name


def cli(k, command: str, request: dict, sources: Path, *, forbidden: str | None = None, replay: Path | None = None) -> tuple[int, dict, bytes]:
    """The real extraction CLI as a subprocess (no in-process shortcut), optionally under a probe that fails and marks any open of `forbidden`."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM}
    probe = REGISTRY_PROBE.format(target=forbidden, mark=str(k.root / "registry-read")) if forbidden else ""
    argv = [sys.executable, "-c", probe + "import runpy\nrunpy.run_module('zoop_ai_pipeline.extraction_cli', run_name='__main__')", command,
            "--state-dir", str(k.root / "extraction"), "--ingestion-state-dir", str(k.root / "ingestion"), "--sources", str(sources)]
    if replay is not None:
        argv += ["--replay", str(replay)]
    child = subprocess.run(argv, input=json_bytes(request), capture_output=True, env=env, cwd=PIPELINE, timeout=120)
    return child.returncode, json.loads(child.stdout) if child.stdout else {}, child.stderr


def snapshot(root: Path) -> dict:
    """Everything a read-only answer must leave alone: row content, schema, file bytes, names and modes, and every job row verbatim (updated_at included)."""
    directory = root / "extraction"
    db = sqlite3.connect(f"file:{ledger(root)}?mode=ro&immutable=1", uri=True)
    try:
        dump = hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()
        schema = db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    finally:
        db.close()
    files = sorted(directory.iterdir())
    return {"dump": dump, "schema": schema, "names": [p.name for p in files], "bytes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "modes": {p.name: stat.S_IMODE(p.stat().st_mode) for p in files} | {".": stat.S_IMODE(directory.stat().st_mode)}, "jobs": rows(root)}


def make_read_only_sensitive(root: Path) -> None:
    """A writable open would repair these: a dropped immutability trigger (schema), 0750/0640 modes, a rewrite of the DDL. A read-only answer must not."""
    directory = root / "extraction"
    db = sqlite3.connect(ledger(root))
    db.execute("DROP TRIGGER immutable_calls_verdict")
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()
    for path in directory.iterdir():
        os.chmod(path, 0o640)
    os.chmod(directory, 0o750)


def legacy_world(w, state: str):
    request, native = run_native(w)
    replay = w.kit.root / "r-job-native.replay.json"
    legacy = copy_as_legacy(w.kit.root, "job-native", "job-legacy", state=state, children=state in {"ready", "stopped"},
                            failure="topic_replay_required" if state == "stopped" else None)
    return request, native, replay, legacy


def error(code: str) -> dict:
    return {"schemaVersion": "zoop-extraction-s2-2", "error": {"code": code}}


# ---------------------------------------------------------------- read-only answers need no registry --------------

@pytest.mark.parametrize("state", ["ready", "queued", "stopped", "reconciling"])
@pytest.mark.parametrize("kind", KINDS)
def test_inspect_shows_the_stored_history_of_a_legacy_job_with_no_usable_registry_and_changes_nothing(world, kind, state):
    w, k = world, world.kit
    _, _, _, legacy = legacy_world(w, state)
    make_read_only_sensitive(k.root)
    sources, forbidden = sources_for(k, kind)
    before = snapshot(k.root)
    code, result, stderr = cli(k, "inspect", k.job_selector("job-legacy"), sources, forbidden=forbidden)
    assert stderr == b"" and not (k.root / "registry-read").exists(), "a legacy inspect must not read the operator registry"
    assert code == 2 and result.get("error") is None, result
    assert result["state"] == state and result["binding"] == legacy["binding"] and result["delivery"] == {"status": "withheld", "code": UNCHANGED}
    assert "eventCandidates" not in result and "topicCandidates" not in result and Q3B not in json.dumps(result, ensure_ascii=False)
    assert snapshot(k.root) == before


@pytest.mark.parametrize("state", ["queued", "stopped", "ready", "reconciling"])
@pytest.mark.parametrize("kind", KINDS)
def test_run_and_resume_refuse_a_legacy_job_with_no_usable_registry_and_change_nothing(world, kind, state):
    w, k = world, world.kit
    _, _, replay, legacy = legacy_world(w, state)
    make_read_only_sensitive(k.root)
    sources, forbidden = sources_for(k, kind)
    before, children = snapshot(k.root), counts(k.root, "job-legacy")
    other = k.replay("r-other").extract(w.art["a1"], [w.mentions["a1"]]).write()
    for command, argument, fixture in (("resume", k.job_selector("job-legacy"), replay), ("resume", k.job_selector("job-legacy"), None),
                                       ("resume", k.job_selector("job-legacy"), other), ("run", legacy["request"], replay)):
        code, result, stderr = cli(k, command, argument, sources, forbidden=forbidden, replay=fixture)
        assert stderr == b"" and not (k.root / "registry-read").exists(), (command, "the operator registry was read")
        assert (code, result) == (2, error(UNCHANGED)), (command, kind, result)
        assert snapshot(k.root) == before and counts(k.root, "job-legacy") == children
    assert not [r for r in rows(k.root) if r["job_id"] == "job-legacy" and r["state"] == "running"]


# ---------------------------------------------------------------- cancel stays the explicit way out ---------------

@pytest.mark.parametrize("state", ["queued", "stopped"])
@pytest.mark.parametrize("kind", KINDS)
def test_cancel_retires_a_legacy_job_with_no_usable_registry_and_only_the_fence_state_columns_change(world, kind, state):
    w, k = world, world.kit
    _, _, _, legacy = legacy_world(w, state)
    sources, forbidden = sources_for(k, kind)
    before, children = {r["job_id"]: r for r in rows(k.root)}, counts(k.root, "job-legacy")
    code, result, stderr = cli(k, "cancel", k.job_selector("job-legacy"), sources, forbidden=forbidden)
    assert stderr == b"" and not (k.root / "registry-read").exists(), "cancel must not read the operator registry"
    assert code == 2 and result["state"] == "cancelled" and result["resumeMode"] == "none", result
    assert result["delivery"] == {"status": "withheld", "code": "job_cancelled"} and "eventCandidates" not in result
    after = {r["job_id"]: r for r in rows(k.root)}
    assert after["job-native"] == before["job-native"] and set(after) == set(before)
    changed = {name for name in after["job-legacy"] if after["job-legacy"][name] != before["job-legacy"][name]}
    assert changed <= {"state", "phase", "resume_mode", "fence", "updated_at"} and {"state", "resume_mode"} <= changed
    assert after["job-legacy"]["fence"] == before["job-legacy"]["fence"] + 1
    assert json.loads(after["job-legacy"]["binding"]) == legacy["binding"] and counts(k.root, "job-legacy") == children


@pytest.mark.parametrize("kind", KINDS)
def test_cancelling_a_finished_legacy_job_changes_nothing_and_still_answers_with_the_history_code(world, kind):
    w, k = world, world.kit
    _, _, _, legacy = legacy_world(w, "ready")
    sources, forbidden = sources_for(k, kind)
    before = snapshot(k.root)
    code, result, stderr = cli(k, "cancel", k.job_selector("job-legacy"), sources, forbidden=forbidden)
    assert stderr == b"" and not (k.root / "registry-read").exists()
    assert code == 2 and result["state"] == "ready" and result["binding"] == legacy["binding"]
    assert result["delivery"] == {"status": "withheld", "code": UNCHANGED} and "eventCandidates" not in result
    assert snapshot(k.root)["jobs"] == before["jobs"]


# ---------------------------------------------------------------- controls: the probe and native jobs ---------------

def test_the_registry_probe_really_trips_for_a_native_job_so_its_silence_for_legacy_jobs_means_something(world):
    w, k = world, world.kit
    run_native(w)
    sources, forbidden = sources_for(k, "valid-but-must-not-be-read")
    code, result, _ = cli(k, "inspect", k.job_selector("job-native"), sources, forbidden=forbidden)
    assert (k.root / "registry-read").exists() and code == 2 and result["error"]["code"] == "extraction_internal_failure"


@pytest.mark.parametrize("kind", ["missing", "malformed"])
def test_a_native_job_still_needs_a_usable_registry_and_a_missing_one_is_a_configuration_error(world, kind):
    w, k = world, world.kit
    run_native(w)
    before = snapshot(k.root)
    sources, _ = sources_for(k, kind)
    code, result, stderr = cli(k, "inspect", k.job_selector("job-native"), sources)
    assert (code, result, stderr) == (2, error("input_or_configuration_invalid"), b"")
    assert snapshot(k.root)["jobs"] == before["jobs"]


# ---------------------------------------------------------------- the boundary code comes before any fixture parse -------

def old_format_fixture(k) -> Path:
    """Bytes of the ORIGINAL pre-cutover replay format (investmate-replay-v2), the file a genuine old job was frozen with."""
    doc = {"format": "investmate-replay-v2", "synthetic": True, "prompt_version": "zoop-extraction-authored-1", "model_version": "authored-model-1",
           "analysis_version": "authored-analysis-1", "embedding_version": "authored-embedding-1",
           "records": [{"stage": "extract", "input": {"article": {"body": "copied source text"}}, "response": {"mentions": []}}]}
    path = k.root / "old-format.replay.json"
    path.write_bytes(json_bytes(doc))
    return path


def old_job(w, state: str):
    """A legacy job whose input digest and frozen replay hash are bound to the actual old-format bytes (not a relabelled native fixture)."""
    run_native(w)
    old = old_format_fixture(w.kit)
    legacy = copy_as_legacy(w.kit.root, "job-native", "job-legacy", state=state, children=state in {"ready", "stopped"},
                            failure="topic_replay_required" if state == "stopped" else None, fixture_hash=hashlib.sha256(old.read_bytes()).hexdigest())
    return old, legacy


@pytest.mark.parametrize("state", ["queued", "stopped", "ready", "reconciling"])
@pytest.mark.parametrize("kind", KINDS)
def test_an_existing_legacy_job_id_answers_analysis_contract_changed_before_any_fixture_is_parsed_or_required(world, kind, state):
    w, k = world, world.kit
    old, legacy = old_job(w, state)
    garbage = k.root / "garbage.replay.json"
    garbage.write_bytes(b"\xff\xfe not json at all")
    make_read_only_sensitive(k.root)
    sources, forbidden = sources_for(k, kind)
    before, children = snapshot(k.root), counts(k.root, "job-legacy")
    selector = k.job_selector("job-legacy")
    # The exact saved request with the exact old bytes, the same request with no fixture at all, and an unparseable fixture: every one is the
    # same history answer, never replay_fixture_invalid / replay_fixture_required and never a configuration error.
    for command, argument, fixture in (("run", legacy["request"], old), ("run", legacy["request"], None), ("run", legacy["request"], garbage),
                                       ("submit", legacy["request"], old), ("submit", legacy["request"], None), ("submit", legacy["request"], garbage),
                                       ("resume", selector, old), ("resume", selector, garbage)):
        code, result, stderr = cli(k, command, argument, sources, forbidden=forbidden, replay=fixture)
        assert stderr == b"" and not (k.root / "registry-read").exists(), (command, fixture and fixture.name, "the operator registry was read")
        assert (code, result) == (2, error(UNCHANGED)), (command, fixture and fixture.name, kind, result)
        assert snapshot(k.root) == before and counts(k.root, "job-legacy") == children


def test_the_same_old_format_bytes_are_still_an_invalid_fixture_for_a_job_id_that_does_not_exist(world):
    w, k = world, world.kit
    old, legacy = old_job(w, "ready")
    before = snapshot(k.root)["jobs"]
    fresh = {**legacy["request"], "jobId": "job-brand-new"}
    code, result, _ = cli(k, "submit", fresh, k.registry_path, replay=old)
    assert (code, result) == (2, error("replay_fixture_invalid"))
    assert snapshot(k.root)["jobs"] == before and "job-brand-new" not in {r["job_id"] for r in rows(k.root)}
