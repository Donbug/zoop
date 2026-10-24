"""Transaction tests with a test-owned verifier executable; real plan validation is a pipeline integration test.

The executable models only the external verification response. Registry merge, CAS, filesystem
publication, lock contention, interruption, and recovery run through the real installer.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from zoop_ai_service import plan_install as core
from zoop_ai_service.config import ConfigError
from zoop_ai_service.ledger import ProcessLock


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def put(path, value):
    path.write_bytes(canonical(value) + b"\n")


@pytest.fixture
def world(tmp_path):
    for name in ("service", "app", "worker", "ingestion", "extraction", "relation"):
        (tmp_path / name).mkdir(mode=0o700)
    for name in ("sources", "producer", "relation-replay", "verifier"):
        put(tmp_path / (name + ".json"), {})
    put(tmp_path / "approvals.json", {"schemaVersion": "zoop-ai-extraction-approvals-1", "approvals": []})
    put(tmp_path / "upstreams.json", {"schemaVersion": "zoop-ai-relation-upstreams-1", "upstreams": []})
    command = tmp_path / "verify"
    command.write_text(f"#!{sys.executable}\n" + '''import hashlib,json,pathlib,sys
args=sys.argv
p=pathlib.Path(args[args.index('--plan-dir')+1])
r=json.loads((p/'receipt.json').read_text())
m=json.loads((p/'manifest.json').read_text())
s=pathlib.Path(args[args.index('--sources')+1])
assert sys.stdin.read() == '{}\\n'
print(json.dumps(dict(schemaVersion='zoop-extraction-service-plan-verification-1',planId=r['planId'],planDigest=r['planDigest'],receiptSha256=hashlib.sha256((p/'receipt.json').read_bytes()).hexdigest(),principal=m['principal'],mode=m['mode'],pins=m['pins'],files=r['files'],counts=m['counts'],sourceRegistrySha256=hashlib.sha256(s.read_bytes()).hexdigest(),sourceBindingsDigest='a'*64)))
''')
    command.chmod(0o700)
    env = {
        "ZOOP_AI_SERVICE_STATE_DIR": str(tmp_path / "service"), "ZOOP_STATE_DIR": str(tmp_path / "app"),
        "ZOOP_AI_WORKER_STATE_DIR": str(tmp_path / "worker"), "ZOOP_AI_INGESTION_STATE_DIR": str(tmp_path / "ingestion"),
        "ZOOP_AI_EXTRACTION_STATE_DIR": str(tmp_path / "extraction"), "ZOOP_AI_RELATION_STATE_DIR": str(tmp_path / "relation"),
        "ZOOP_AI_SERVICE_EXTRACTION_COMMAND": str(command), "ZOOP_AI_SERVICE_RELATION_COMMAND": str(command),
        "ZOOP_AI_SERVICE_SOURCES": str(tmp_path / "sources.json"), "ZOOP_AI_SERVICE_EXTRACTION_REPLAY": str(tmp_path / "producer.json"),
        "ZOOP_AI_SERVICE_RELATION_REPLAY": str(tmp_path / "relation-replay.json"),
        "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY": str(tmp_path / "verifier.json"),
        "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS": str(tmp_path / "approvals.json"), "ZOOP_AI_SERVICE_RELATION_UPSTREAMS": str(tmp_path / "upstreams.json"),
        "ZOOP_AI_SERVICE_PRINCIPALS": json.dumps([{"principal": n, "tokenSha256": [h * 64], "scopes": ["extraction.submit", "relation.submit"]}
                                                 for n, h in (("alpha", "1"), ("beta", "2"))])}
    return SimpleNamespace(root=tmp_path, env=env)


def make_plan(world, name="a", principal="alpha", job=None):
    path = world.root / ("plan-" + name)
    path.mkdir()
    request = {"schemaVersion": "zoop-extraction-s2-2", "jobId": job or "s2p-" + name,
               "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
               "promptVersion": name, "incoming": {"roundId": name, "sourceId": "s", "page": 0, "ordinal": 0,
               "documentId": "d", "rawVersion": "c" * 64, "documentVersion": "d" * 64},
               "catalogue": {"revision": "c1", "companies": []}, "snapshot": {"revision": "s1", "events": []}, "topic": None}
    pin = hashlib.sha256((world.root / "producer.json").read_bytes()).hexdigest()
    approval = {"principal": principal, "jobId": request["jobId"], "approvedRequestDigest": digest(request), "request": request,
                "producerReplayDigest": pin, "topicReplayDigest": None}
    upstream = {"principal": principal, "jobId": request["jobId"], "inputDigest": digest({"request": request, "replayFixtureHash": pin})}
    put(path / "approvals.json", {"schemaVersion": "zoop-ai-extraction-approvals-1", "approvals": [approval]})
    put(path / "relation-upstreams.json", {"schemaVersion": "zoop-ai-relation-upstreams-1", "upstreams": [upstream]})
    pins = lambda names: {n: {"sha256": hashlib.sha256((path / n).read_bytes()).hexdigest(), "bytes": (path / n).stat().st_size} for n in names}
    manifest = {"schemaVersion": "zoop-extraction-service-plan-1", "planId": "s2plan-" + name, "principal": principal,
                "round": {"roundId": name}, "mode": "replay", "pins": {"producerReplayDigest": pin},
                "registryFiles": pins(("approvals.json", "relation-upstreams.json")), "counts": {"units": 1, "skipped": 0}}
    manifest["planDigest"] = digest(manifest)
    put(path / "manifest.json", manifest)
    put(path / "receipt.json", {"schemaVersion": "zoop-extraction-service-plan-receipt-1", "planId": manifest["planId"],
        "planDigest": manifest["planDigest"], "files": pins(("approvals.json", "relation-upstreams.json", "manifest.json"))})
    return path


def config(world, recovery=False):
    return core.settings(world.env, recovery=recovery)


def installed(world):
    return tuple((world.root / n).read_bytes() for n in ("approvals.json", "upstreams.json"))


def review(world, plan):
    return core.inspect(config(world), plan)


def apply(world, plan, facts):
    return core.install(config(world, True), plan, facts["currentDigest"], facts["reviewDigest"])


def service(world):
    return SimpleNamespace(state_dir=world.root / "service", principals=[SimpleNamespace(name=n) for n in ("alpha", "beta")],
        extraction=SimpleNamespace(approvals_path=world.root / "approvals.json", topic_replay=None),
        relation=SimpleNamespace(upstreams_path=world.root / "upstreams.json"), pipeline_live=None)


def test_inspect_is_read_only_and_merge_preserves_other_round_and_principal(world):
    a, b = make_plan(world), make_plan(world, "b", "beta")
    before = installed(world)
    facts = review(world, a)
    assert installed(world) == before
    assert not (world.root / "service" / "service.lock").exists()
    assert not (world.root / "service" / "plan-install").exists()
    first = apply(world, a, facts)
    assert first["appliedNow"] is True
    apply(world, b, review(world, b))
    after = installed(world)
    retry = apply(world, a, facts)
    assert retry["appliedNow"] is False and retry["installationCurrent"] is True
    assert retry["transactionDigest"] == first["transactionDigest"]
    assert installed(world) == after
    assert [x["principal"] for x in json.loads(after[0])["approvals"]] == ["alpha", "beta"]


def test_replay_reports_historical_receipt_without_regrant_after_revocation(world):
    plan = make_plan(world)
    facts = review(world, plan)
    result = apply(world, plan, facts)
    put(world.root / "approvals.json", {"schemaVersion": "zoop-ai-extraction-approvals-1", "approvals": []})
    before = installed(world)
    (world.root / "sources.json").unlink()  # Historical receipt does not need current source/model configuration.
    retry = apply(world, plan, facts)
    assert retry["transactionDigest"] == result["transactionDigest"]
    assert retry["appliedNow"] is False and retry["installationCurrent"] is False
    assert retry["error"]["code"] == "installation_not_current"
    assert installed(world) == before


def test_new_review_cannot_regrant_previously_removed_plan(world):
    plan = make_plan(world)
    apply(world, plan, review(world, plan))
    put(world.root / "approvals.json", {"schemaVersion": "zoop-ai-extraction-approvals-1", "approvals": []})
    before = installed(world)
    retry = apply(world, plan, review(world, plan))
    assert retry["error"]["code"] == "installation_not_current"
    assert retry["appliedNow"] is False and installed(world) == before


def test_stale_current_and_changed_configuration_write_no_targets(world):
    plan = make_plan(world)
    facts = review(world, plan)
    (world.root / "upstreams.json").write_bytes((world.root / "upstreams.json").read_bytes() + b" ")
    before = installed(world)
    with pytest.raises(core.InstallError, match="stale_current"):
        apply(world, plan, facts)
    assert installed(world) == before
    facts = review(world, plan)
    put(world.root / "sources.json", {"revision": 2})
    with pytest.raises(core.InstallError, match="stale_review"):
        apply(world, plan, facts)
    assert installed(world) == before


def test_conflicting_key_refuses_whole_merge(world):
    a, b = make_plan(world), make_plan(world, "b", job="s2p-a")
    apply(world, a, review(world, a))
    before = installed(world)
    with pytest.raises(core.InstallError, match="plan_conflict"):
        review(world, b)
    assert installed(world) == before


@pytest.mark.parametrize("fault", ["duplicate", "extra", "symlink", "receipt", "unknown"])
def test_bad_inputs_never_change_registries(world, fault):
    plan = make_plan(world, principal="unknown" if fault == "unknown" else "alpha")
    if fault == "duplicate":
        raw = (plan / "receipt.json").read_bytes()
        (plan / "receipt.json").write_bytes(b'{"planId":"duplicate",' + raw[1:])
    elif fault == "extra":
        (plan / "foreign").write_text("not a plan file")
    elif fault == "symlink":
        (plan / "approvals.json").unlink()
        (plan / "approvals.json").symlink_to(world.root / "approvals.json")
    elif fault == "receipt":
        (plan / "approvals.json").write_bytes(b"{}")
    before = installed(world)
    with pytest.raises((core.InstallError, core.relation_access.AccessError)):
        review(world, plan)
    assert installed(world) == before


def test_busy_process_lock_excludes_installer(world):
    plan = make_plan(world)
    facts = review(world, plan)
    before = installed(world)
    with ProcessLock(world.root / "service"):
        with pytest.raises(ConfigError) as caught:
            apply(world, plan, facts)
        assert caught.value.reason == "service_state_busy"
    assert installed(world) == before


def interrupt_after_first_replace(world, monkeypatch):
    original = os.replace
    def interrupted(source, target, **kwargs):
        original(source, target, **kwargs)
        found = os.fstat(kwargs["dst_dir_fd"])
        expected = world.root.stat()
        if Path(target).name == "approvals.json" and (found.st_dev, found.st_ino) == (expected.st_dev, expected.st_ino):
            raise OSError("simulated loss after first durable replacement")
    monkeypatch.setattr(os, "replace", interrupted)


def test_partial_replace_blocks_startup_then_explicit_recovery_aborts(world, monkeypatch):
    plan = make_plan(world)
    facts = review(world, plan)
    before = installed(world)
    with monkeypatch.context() as patch:
        interrupt_after_first_replace(world, patch)
        with pytest.raises(OSError):
            apply(world, plan, facts)
    assert installed(world)[0] != before[0] and installed(world)[1] == before[1]
    with pytest.raises(ConfigError, match="ZOOP_AI_SERVICE_STATE_DIR"):
        core.startup_barrier(service(world))
    status = core.status(config(world, True), facts["installationId"])
    result = core.recover(config(world, True), facts["installationId"], status["transactionDigest"])
    assert result["outcome"] == "aborted" and result["appliedNow"] is False
    assert installed(world) == before
    core.startup_barrier(service(world))
    assert apply(world, plan, facts)["outcome"] == "aborted"
    assert installed(world) == before


def test_recovery_never_overwrites_manual_third_state(world, monkeypatch):
    plan = make_plan(world)
    facts = review(world, plan)
    with monkeypatch.context() as patch:
        interrupt_after_first_replace(world, patch)
        with pytest.raises(OSError):
            apply(world, plan, facts)
    status = core.status(config(world, True), facts["installationId"])
    put(world.root / "approvals.json", {"schemaVersion": "zoop-ai-extraction-approvals-1", "approvals": [], "operator": "third-state"})
    foreign = installed(world)
    with pytest.raises(core.InstallError, match="journal_target_drift"):
        core.recover(config(world, True), facts["installationId"], status["transactionDigest"])
    assert installed(world) == foreign
    with pytest.raises(ConfigError):
        core.startup_barrier(service(world))


def test_unknown_status_path_and_reconfigured_targets_are_not_adopted(world):
    with pytest.raises(core.InstallError, match="installation_id_invalid"):
        core.status(config(world, True), "../outside")
    plan = make_plan(world)
    facts = review(world, plan)
    apply(world, plan, facts)
    before = installed(world)
    world.env["ZOOP_AI_SERVICE_RELATION_UPSTREAMS"] = str(world.root / "foreign.json")
    with pytest.raises(core.InstallError, match="journal_binding_changed"):
        core.status(config(world, True), facts["installationId"])
    assert installed(world) == before
    assert not (world.root / "foreign.json").exists()


def test_published_intent_before_pending_is_explicitly_recoverable(world, monkeypatch):
    plan = make_plan(world)
    facts = review(world, plan)
    before = installed(world)
    original = os.link
    def fail_marker(source, target, **kwargs):
        if Path(target).name == "pending.json":
            raise OSError("simulated failure before pending publication")
        return original(source, target, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(os, "link", fail_marker)
        with pytest.raises(OSError):
            apply(world, plan, facts)
    assert installed(world) == before
    with pytest.raises(ConfigError):
        core.startup_barrier(service(world))
    status = core.status(config(world, True), facts["installationId"])
    assert status["pendingMarker"] is False and status["outcome"] == "pending"
    result = core.recover(config(world, True), facts["installationId"], status["transactionDigest"])
    assert result["outcome"] == "aborted" and installed(world) == before
    core.startup_barrier(service(world))


def test_committed_receipt_with_leftover_marker_only_clears_bookkeeping(world, monkeypatch):
    plan = make_plan(world)
    facts = review(world, plan)
    original = os.unlink
    def fail_clear(path, **kwargs):
        if Path(path).name == "pending.json":
            raise OSError("simulated loss after committed receipt")
        return original(path, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", fail_clear)
        with pytest.raises(OSError):
            apply(world, plan, facts)
    after = installed(world)
    identities = [p.stat().st_ino for p in config(world, True).targets]
    status = core.status(config(world, True), facts["installationId"])
    assert status["outcome"] == "committed" and status["pendingMarker"] is True
    with pytest.raises(core.InstallError, match="stale_transaction"):
        core.recover(config(world, True), facts["installationId"], "0" * 64)
    result = core.recover(config(world, True), facts["installationId"], status["transactionDigest"])
    assert result["outcome"] == "committed" and result["appliedNow"] is False
    assert installed(world) == after
    assert [p.stat().st_ino for p in config(world, True).targets] == identities
    core.startup_barrier(service(world))


def test_corrupt_pending_marker_blocks_startup_without_ledger_creation(world):
    plan = make_plan(world)
    apply(world, plan, review(world, plan))
    marker = world.root / "service" / "plan-install" / "pending.json"
    marker.write_bytes(b'{"installationId":"first","installationId":"second"}')
    with pytest.raises(ConfigError):
        core.startup_barrier(service(world))
    assert not (world.root / "service" / "service.sqlite3").exists()


def test_hardlinked_target_is_never_replaced(world):
    plan = make_plan(world)
    os.link(world.root / "approvals.json", world.root / "other-owner-name.json")
    before = installed(world)
    with pytest.raises(core.InstallError, match="target_not_owned_regular"):
        review(world, plan)
    assert installed(world) == before


def test_fixture_rotation_refuses_without_replacing_registry(world):
    plan = make_plan(world)
    facts = review(world, plan)
    put(world.root / "producer.json", {"rotated": True})
    before = installed(world)
    with pytest.raises(core.InstallError, match="fixture_changed"):
        apply(world, plan, facts)
    assert installed(world) == before


def test_merged_size_limit_refuses_without_pruning_old_grants(world, monkeypatch):
    a, b = make_plan(world), make_plan(world, "b")
    apply(world, a, review(world, a))
    before = installed(world)
    # Either individual registry fits, but the cumulative two-entry union does not.
    largest = max(len(before[1]), (b / "relation-upstreams.json").stat().st_size)
    monkeypatch.setattr(core.relation_access, "MAX_BYTES", largest + 1)
    with pytest.raises(core.relation_access.AccessError, match="upstream_allowlist_too_large"):
        review(world, b)
    assert installed(world) == before


def test_inspect_verifier_capture_performs_no_writable_open_or_filesystem_mutation(world):
    plan = make_plan(world)
    before = installed(world)
    program = r'''
import json, os, pathlib, stat, sys
from zoop_ai_service import plan_install as core
env = json.loads(sys.stdin.read())
def read_only(event, args):
    if event == "open" and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        if isinstance(args[0], int) and stat.S_ISFIFO(os.fstat(args[0]).st_mode):
            return
        raise RuntimeError("writable open denied")
    if event in ("os.mkdir", "os.chmod", "os.chown", "os.rename", "os.link", "os.symlink", "os.remove", "os.rmdir", "os.truncate", "os.utime"):
        raise RuntimeError("filesystem mutation denied")
sys.addaudithook(read_only)
result = core.inspect(core.settings(env), pathlib.Path(sys.argv[1]))
print(json.dumps({"reviewDigest": result["reviewDigest"], "units": result["counts"]["units"]}))
'''
    done = subprocess.run([sys.executable, "-B", "-c", program, str(plan)], input=json.dumps(world.env).encode(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False)
    assert done.returncode == 0, done.stderr.decode()
    assert json.loads(done.stdout)["units"] == 1
    assert installed(world) == before
    assert not (world.root / "service" / "plan-install").exists()
    assert not (world.root / "service" / "service.lock").exists()


@pytest.mark.parametrize("behavior,code", [
    ("stdout", "plan_verifier_unavailable"),
    ("stderr", "plan_verifier_unavailable"),
    ("timeout", "plan_verifier_unavailable"),
])
def test_bounded_verifier_pipes_kill_and_reap_on_output_or_deadline_failure(world, monkeypatch, behavior, code):
    plan = make_plan(world)
    command = world.root / "verify"
    body = "import sys,time\nsys.stdin.read()\n"
    if behavior == "timeout":
        body += "time.sleep(60)\n"
    else:
        body += f"import os\nwhile True: os.write({1 if behavior == 'stdout' else 2}, b'x' * 8192)\n"
    command.write_text(f"#!{sys.executable}\n" + body)
    children = []
    original = subprocess.Popen
    def start(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    from zoop_ai_service import plan_verify
    monkeypatch.setattr(plan_verify.subprocess, "Popen", start)
    monkeypatch.setattr(plan_verify, "VERIFIER_TIMEOUT", 0.25 if behavior == "timeout" else 10)
    before = installed(world)
    with pytest.raises(core.InstallError, match=code):
        review(world, plan)
    assert len(children) == 1 and children[0].returncode is not None
    with pytest.raises(ChildProcessError):
        os.waitpid(children[0].pid, os.WNOHANG)
    assert installed(world) == before


def isolated_registry_parent(world):
    parent = world.root / "registries"
    parent.mkdir(mode=0o700)
    for old, variable in (("approvals.json", "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS"),
                          ("upstreams.json", "ZOOP_AI_SERVICE_RELATION_UPSTREAMS")):
        target = parent / old
        (world.root / old).rename(target)
        world.env[variable] = str(target)
    return parent


def replace_parent_with_identical_registry_bytes(parent):
    displaced = parent.with_name("displaced-registries")
    parent.rename(displaced)
    parent.mkdir(mode=0o700)
    for name in ("approvals.json", "upstreams.json"):
        target = parent / name
        target.write_bytes((displaced / name).read_bytes())
        target.chmod(0o600)
    return tuple((parent / name).read_bytes() for name in ("approvals.json", "upstreams.json"))


def test_replaced_registry_parent_after_inspection_refuses_foreign_same_bytes(world):
    parent = isolated_registry_parent(world)
    plan = make_plan(world)
    facts = review(world, plan)
    replacement = replace_parent_with_identical_registry_bytes(parent)
    inodes = [(parent / name).stat().st_ino for name in ("approvals.json", "upstreams.json")]
    with pytest.raises(core.InstallError) as caught:
        apply(world, plan, facts)
    assert caught.value.code in {"stale_current", "stale_review", "journal_binding_changed", "directory_identity_changed"}
    assert tuple((parent / name).read_bytes() for name in ("approvals.json", "upstreams.json")) == replacement
    assert [(parent / name).stat().st_ino for name in ("approvals.json", "upstreams.json")] == inodes


def test_replaced_registry_parent_during_pending_refuses_recovery_into_foreign_same_bytes(world, monkeypatch):
    parent = isolated_registry_parent(world)
    plan = make_plan(world)
    facts = review(world, plan)
    original = os.replace
    def interrupted(source, target, **kwargs):
        original(source, target, **kwargs)
        found = os.fstat(kwargs["dst_dir_fd"])
        expected = parent.stat()
        if Path(target).name == "approvals.json" and (found.st_dev, found.st_ino) == (expected.st_dev, expected.st_ino):
            raise OSError("simulated interruption after first replace")
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", interrupted)
        with pytest.raises(OSError):
            apply(world, plan, facts)
    pending = core.status(config(world, True), facts["installationId"])
    replacement = replace_parent_with_identical_registry_bytes(parent)
    inodes = [(parent / name).stat().st_ino for name in ("approvals.json", "upstreams.json")]
    with pytest.raises(core.InstallError) as caught:
        core.recover(config(world, True), facts["installationId"], pending["transactionDigest"])
    assert caught.value.code in {"journal_binding_changed", "directory_identity_changed"}
    assert tuple((parent / name).read_bytes() for name in ("approvals.json", "upstreams.json")) == replacement
    assert [(parent / name).stat().st_ino for name in ("approvals.json", "upstreams.json")] == inodes


def test_journal_capacity_preserves_terminal_replay_and_refuses_new_transaction(world, monkeypatch):
    monkeypatch.setattr(core, "MAX_OPERATIONS", 1)
    first, second = make_plan(world), make_plan(world, "b")
    facts = review(world, first)
    committed = apply(world, first, facts)
    core.startup_barrier(service(world))
    assert apply(world, first, facts) == {**committed, "appliedNow": False}
    next_facts = review(world, second)
    before = installed(world)
    root = world.root / "service" / "plan-install"
    journal = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises(core.InstallError, match="journal_bounds"):
        apply(world, second, next_facts)
    assert installed(world) == before
    assert {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()} == journal
    core.startup_barrier(service(world))


def test_sibling_directory_metadata_changes_do_not_stale_review(world):
    plan = make_plan(world)
    facts = review(world, plan)
    (world.root / "unrelated-sibling").mkdir()
    (world.root / "unrelated-sibling" / "note").write_text("not an installer input")
    assert apply(world, plan, facts)["appliedNow"] is True


def test_replaced_service_state_after_inspection_refuses_same_path(world):
    plan = make_plan(world)
    facts = review(world, plan)
    state = world.root / "service"
    state.rename(world.root / "displaced-service")
    state.mkdir(mode=0o700)
    before = installed(world)
    with pytest.raises(core.InstallError) as caught:
        apply(world, plan, facts)
    assert caught.value.code in {"stale_current", "stale_review", "directory_identity_changed"}
    assert installed(world) == before
    assert not (state / "plan-install").exists()


@pytest.mark.parametrize("program,expected", [
    ("import sys; sys.stdin.read(); sys.exit(7)", "plan_verifier_unavailable"),
    ("import os,signal,sys; sys.stdin.read(); os.kill(os.getpid(),signal.SIGKILL)", "plan_verifier_unavailable"),
    ("import sys; sys.stdin.read(); print('not-json')", "plan_verifier_unavailable"),
    ("import sys; sys.stdin.read()", "plan_verifier_unavailable"),
    ("import sys; sys.stdin.read(); print('not-json'); sys.exit(2)", "plan_verifier_unavailable"),
    ("import json,sys; sys.stdin.read(); print(json.dumps({'schemaVersion':'zoop-extraction-s2-2','error':{'code':'plan_content_mismatch'}})); sys.exit(2)",
     "plan_verification_failed"),
], ids=["abnormal-exit", "signal", "malformed-success", "empty-success", "malformed-refusal", "closed-substantive-refusal"])
def test_verifier_exit_classification_requires_a_closed_substantive_refusal(world, program, expected):
    plan = make_plan(world)
    command = world.root / "verify"
    command.write_text(f"#!{sys.executable}\n" + program + "\n")
    before = installed(world)
    with pytest.raises(core.InstallError, match=expected):
        review(world, plan)
    assert installed(world) == before
    assert not (world.root / "service" / "plan-authority.sqlite3").exists()
