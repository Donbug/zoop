"""Exact operator-plan verification: real ingestion, no extraction writes or send authority."""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import stat
import sys

import pytest

from scripts.extraction_smoke import LIVE_ENV_NAMES, SECRET_NAMES, simulator_env
from tests.test_round_plan import make, read, sha, world  # noqa: F401 - shared real-ingestion fixture
from tests.test_round_enqueue import descriptor, simple_round
from zoop_ai_pipeline import extraction_cli, extraction_plan, extraction_replay as analysis
from zoop_ai_pipeline.extraction import Extractor, Fixtures, Sources
from zoop_ai_pipeline.extraction_contracts import EnqueueRound, ExtractionFailure, canonical, digest
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure


def snapshot(root):
    """Include directories, bytes, modes and mtime; access time is deliberately not a write assertion."""
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        result[str(path.relative_to(root))] = (stat.S_IMODE(info.st_mode), info.st_mtime_ns,
                                              path.read_bytes() if path.is_file() else None)
    return result


def verify(world, out, *, expected=None, fixtures=None, live=None):
    return extraction_plan.verify_plan(out, expected or sha((out / "receipt.json").read_bytes()),
                                       fixtures or Fixtures(world.replay.read_bytes(), None),
                                       world.kit.root / "ingestion", world.kit.registry_path, live)


def rewrite(out, name, change):
    """An attacker can recompute every outer hash; only re-planning can reject these semantic changes."""
    value = json.loads((out / name).read_bytes())
    change(value)
    (out / name).write_bytes((canonical(value) + "\n").encode())
    files = read(out)
    receipt = json.loads(files["receipt.json"])
    receipt["files"] = {key: {"sha256": sha(raw), "bytes": len(raw)} for key, raw in files.items() if key != "receipt.json"}
    (out / "receipt.json").write_bytes((canonical(receipt) + "\n").encode())


def refuse(*args, **kwargs):
    raise AssertionError("verification must not write/freeze/send/connect")


def test_replay_exact_response_and_no_bytes_modes_mtime_or_state_changes(world, tmp_path, monkeypatch):
    rid, _ = simple_round(world.kit, "verify", ["a", "b"])
    out = tmp_path / "plan"
    make(world, out, rid)
    before = snapshot(tmp_path)
    monkeypatch.setattr(extraction_plan, "commit", refuse)
    monkeypatch.setattr(extraction_plan.tempfile, "mkdtemp", refuse)
    monkeypatch.setattr(Extractor, "freeze", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    response = verify(world, out)
    receipt = json.loads((out / "receipt.json").read_bytes())
    manifest = json.loads((out / "manifest.json").read_bytes())
    approvals = json.loads((out / "approvals.json").read_bytes())["approvals"]
    refs = {}
    for entry in approvals:
        request = entry["request"]
        refs[digest(request["incoming"])] = request["incoming"]
        for event in request["snapshot"]["events"]:
            for member in event["members"]:
                refs[digest(member["observation"])] = member["observation"]
    bindings = []
    for _, ref in sorted(refs.items()):
        exported = world.kit.export(ref)
        bindings.append({"observation": ref, "binding": analysis.bind(exported, analysis.article(exported, True))})
    assert response == {
        "schemaVersion": "zoop-extraction-service-plan-verification-1", "planId": receipt["planId"],
        "planDigest": receipt["planDigest"], "receiptSha256": sha((out / "receipt.json").read_bytes()),
        "principal": "alpha", "mode": "replay", "pins": {"producerReplayDigest": sha(world.replay.read_bytes())},
        "files": receipt["files"], "counts": manifest["counts"],
        "sourceRegistrySha256": sha(world.kit.registry_path.read_bytes()),
        "sourceBindingsDigest": digest({"format": "zoop-extraction-service-plan-source-bindings-1", "documents": bindings})}
    assert snapshot(tmp_path) == before
    assert not (world.kit.root / "extraction").exists()


def test_live_current_public_runtime_binding_needs_no_keys_budget_caps_or_network(world, tmp_path, monkeypatch):
    rid, _ = simple_round(world.kit, "live-verify", ["a"])
    budget = tmp_path / "budget"
    for name in LIVE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name, value in simulator_env("https://api.openai.com/v1", budget).items():
        if name not in SECRET_NAMES and not name.endswith(("MAX_USD", "MAX_CALLS")):
            monkeypatch.setenv(name, value)
    from zoop_ai_pipeline.extraction import LiveAccess
    out = tmp_path / "plan"
    make(world, out, rid, live=LiveAccess(), mode="live")
    before = snapshot(tmp_path)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(LiveAccess, "sender", refuse)
    response = verify(world, out, fixtures=Fixtures(None, None))
    assert response["mode"] == "live" and set(response["pins"]) == {"liveRuntimeIdentity"}
    assert not budget.exists() and snapshot(tmp_path) == before
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR", str(tmp_path / "other-budget"))
    with pytest.raises(ExtractionFailure, match="plan_content_mismatch"):
        verify(world, out, fixtures=Fixtures(None, None))
    with pytest.raises(ExtractionFailure, match="fixture_not_allowed"):
        verify(world, out)
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_ENABLED", "0")
    with pytest.raises(ExtractionFailure, match="live_not_enabled"):
        verify(world, out, fixtures=Fixtures(None, None))
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("name,change", [
    ("approvals.json", lambda value: value["approvals"][0]["request"]["incoming"].update(ordinal=99)),
    ("approvals.json", lambda value: value["approvals"][1]["request"]["catalogue"].update(revision="forged")),
    ("approvals.json", lambda value: value["approvals"][0].update(principal="beta")),
    ("approvals.json", lambda value: value["approvals"][0].update(unknown=True)),
    ("manifest.json", lambda value: value.update(principal="beta")),
    ("manifest.json", lambda value: value["round"].update(ingestionInputDigest="a" * 64)),
    ("manifest.json", lambda value: value.update(units=[])),
    ("manifest.json", lambda value: value.update(unknown=True)),
    ("relation-upstreams.json", lambda value: value["upstreams"][0].update(inputDigest="b" * 64)),
], ids=["incoming-ref", "inconsistent-descriptor", "approval-principal", "approval-extra", "manifest-principal",
        "round-pin", "no-manifest-units", "manifest-extra", "upstream-pin"])
def test_recomputed_receipt_cannot_wrap_altered_semantics(world, tmp_path, name, change):
    rid, _ = simple_round(world.kit, "tamper", ["a", "b"])
    out = tmp_path / "plan"
    make(world, out, rid)
    rewrite(out, name, change)
    before = snapshot(tmp_path)
    with pytest.raises(ExtractionFailure, match="plan_content_mismatch"):
        verify(world, out)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("damage,code", [
    (lambda out: (out / "extra.json").write_bytes(b"{}"), "plan_input_invalid"),
    (lambda out: (out / "manifest.json").write_bytes(b"{}"), "plan_receipt_mismatch"),
    (lambda out: (out / "receipt.json").write_bytes(b'{"files":{},"files":{}}'), "plan_input_invalid"),
    (lambda out: (out / "receipt.json").write_bytes(b'{"files":NaN}'), "plan_input_invalid"),
    (lambda out: rewrite(out, "receipt.json", lambda value: value.update(extra=1)), "plan_input_invalid"),
    (lambda out: rewrite(out, "approvals.json", lambda value: value.update(approvals=[])), "plan_has_no_units"),
], ids=["unknown-file", "raw-tamper", "duplicate-json-key", "nonfinite-json", "receipt-extra", "empty-approvals"])
def test_closed_bounded_duplicate_free_plan_files(world, tmp_path, damage, code):
    rid, _ = simple_round(world.kit, "invalid", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    damage(out)
    before = snapshot(tmp_path)
    with pytest.raises(ExtractionFailure, match=code):
        verify(world, out)
    assert snapshot(tmp_path) == before


def test_expected_receipt_pin_size_and_noncanonical_bytes_are_refused(world, tmp_path, monkeypatch):
    rid, _ = simple_round(world.kit, "bounded", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    with pytest.raises(ExtractionFailure, match="plan_receipt_mismatch"):
        verify(world, out, expected="0" * 64)
    with monkeypatch.context() as patch:
        patch.setattr(extraction_plan, "MAX_MANIFEST", 10)
        with pytest.raises(ExtractionFailure, match="plan_input_invalid"):
            verify(world, out)
    (out / "receipt.json").write_bytes((out / "receipt.json").read_bytes() + b" ")
    with pytest.raises(ExtractionFailure, match="plan_content_mismatch"):
        verify(world, out)


@pytest.mark.parametrize("alias", ["leaf-symlink", "parent-symlink", "hardlink", "fifo", "dotdot"])
def test_confined_regular_non_alias_paths(world, tmp_path, alias):
    rid, _ = simple_round(world.kit, "alias", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    expected = sha((out / "receipt.json").read_bytes())
    selected = out
    leaf = out / "manifest.json"
    if alias == "leaf-symlink":
        target = tmp_path / "manifest-copy"
        leaf.rename(target)
        leaf.symlink_to(target)
    elif alias == "parent-symlink":
        selected = tmp_path / "alias"
        selected.symlink_to(out, target_is_directory=True)
    elif alias == "hardlink":
        os.link(leaf, tmp_path / "manifest-copy")
    elif alias == "fifo":
        leaf.unlink()
        os.mkfifo(leaf)
    else:
        selected = out / ".." / "plan"
    with pytest.raises(ExtractionFailure, match="plan_(path|input)_invalid"):
        verify(world, selected, expected=expected)


def test_fixture_bytes_provenance_and_topic_pins_must_match(world, tmp_path):
    rid, _ = simple_round(world.kit, "fixture", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    original = world.replay.read_bytes()
    with pytest.raises(ExtractionFailure, match="replay_fixture_required"):
        verify(world, out, fixtures=Fixtures(None, None))
    with pytest.raises(ExtractionFailure, match="plan_content_mismatch"):
        verify(world, out, fixtures=Fixtures(original + b" ", None))
    doc = json.loads(original)
    doc["synthetic"] = False
    with pytest.raises(ExtractionFailure, match="replay_provenance_conflict"):
        verify(world, out, fixtures=Fixtures(canonical(doc).encode(), None))
    with pytest.raises(ExtractionFailure, match="fixture_not_allowed"):
        verify(world, out, fixtures=Fixtures(original, b"{}"))
    topic_out = tmp_path / "topic-plan"
    request = EnqueueRound.model_validate(descriptor(rid, events=[world.event], topic=True))
    extraction_plan.plan_round(request, Fixtures(original, b"{}"), "alpha", world.kit.root / "ingestion",
                               world.kit.registry_path, topic_out)
    with pytest.raises(ExtractionFailure, match="topic_replay_required"):
        verify(world, topic_out)
    assert verify(world, topic_out, fixtures=Fixtures(original, b"{}"))["pins"]["topicReplayDigest"] == sha(b"{}")
    with pytest.raises(ExtractionFailure, match="plan_content_mismatch"):
        verify(world, topic_out, fixtures=Fixtures(original, b"{ }"))


def test_current_read_authority_is_required_but_no_model_send_grant(world, tmp_path):
    rid, _ = simple_round(world.kit, "rights", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    registry = json.loads(world.kit.registry_path.read_bytes())
    grant = registry["sources"][0]["grant"]
    grant["allowedOperations"] = ["read", "store", "quote-display"]
    grant["purposes"] = []
    grant["recipients"] = []
    world.kit.registry_path.write_text(canonical(registry))
    assert verify(world, out)["sourceRegistrySha256"] == sha(world.kit.registry_path.read_bytes())
    grant["enabled"] = False
    world.kit.registry_path.write_text(canonical(registry))
    with pytest.raises((ExtractionFailure, IngestionFailure), match="source_unauthorized"):
        verify(world, out)


def test_snapshot_reference_is_exported_and_exact_source_identity_is_required(world, tmp_path):
    rid, _ = simple_round(world.kit, "snapshot-ref", ["a"])
    out = tmp_path / "plan"
    event = json.loads(json.dumps(world.event))
    event["members"][0]["observation"]["ordinal"] = 99
    # Planning deliberately does not do submit-time freeze viability; verification must still read every reference.
    request = EnqueueRound.model_validate(descriptor(rid, events=[event]))
    extraction_plan.plan_round(request, Fixtures(world.replay.read_bytes(), None), "alpha", world.kit.root / "ingestion",
                               world.kit.registry_path, out)
    with pytest.raises(ExtractionFailure, match="observation_not_found"):
        verify(world, out)


def test_source_registry_and_file_races_during_verification_fail_closed(world, tmp_path, monkeypatch):
    rid, _ = simple_round(world.kit, "races", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    original = Sources.export
    seen = []

    def replace(self, ref, *, send=None):
        result = original(self, ref, send=send)
        seen.append(ref.wire())
        if len(seen) == 1:
            leaf = out / "manifest.json"
            same = leaf.read_bytes()
            leaf.unlink()
            leaf.write_bytes(same)
        return result

    monkeypatch.setattr(Sources, "export", replace)
    with pytest.raises(ExtractionFailure, match="plan_files_changed"):
        verify(world, out)
    assert world.base in seen  # snapshot plus incoming both went through existing Sources.export
    seen.clear()

    def revoke(self, ref, *, send=None):
        result = original(self, ref, send=send)
        if not seen:
            seen.append(True)
            world.kit.registry_path.write_bytes(world.kit.registry_path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(Sources, "export", revoke)
    with pytest.raises((ExtractionFailure, IngestionFailure), match="registry_changed"):
        verify(world, out)


def test_cli_empty_object_and_options_use_existing_error_envelope(world, tmp_path, monkeypatch, capsys):
    rid, _ = simple_round(world.kit, "cli-verify", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    args = ["zoop-ai-extract", "verify-plan", "--plan-dir", str(out), "--expected-receipt-sha256",
            sha((out / "receipt.json").read_bytes()), "--ingestion-state-dir", str(world.kit.root / "ingestion"),
            "--sources", str(world.kit.registry_path), "--replay", str(world.replay)]
    for raw, extra, code, error in [(b"{}", [], 0, None), (b"[]", [], 2, "plan_option_not_allowed"),
                                    (b'{"x":1,"x":2}', [], 2, "plan_input_invalid"),
                                    (b"{}", ["--state-dir", str(tmp_path / "must-not-exist")], 2, "plan_option_not_allowed")]:
        monkeypatch.setattr(sys, "argv", [*args, *extra])
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
        assert extraction_cli.main() == code
        response = json.loads(capsys.readouterr().out)
        if error:
            assert response == {"schemaVersion": "zoop-extraction-s2-2", "error": {"code": error}}
        else:
            assert response["schemaVersion"] == "zoop-extraction-service-plan-verification-1"
    assert not (tmp_path / "must-not-exist").exists()


def test_current_source_configuration_change_is_refused_without_writes(world, tmp_path):
    rid, _ = simple_round(world.kit, "source-config", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    registry = json.loads(world.kit.registry_path.read_bytes())
    registry["sources"][0]["allowedHosts"].append("other.invalid")
    world.kit.registry_path.write_text(canonical(registry))
    before = snapshot(tmp_path)
    with pytest.raises((ExtractionFailure, IngestionFailure), match="scope_configuration_conflict"):
        verify(world, out)
    assert snapshot(tmp_path) == before


def test_source_binding_drift_between_authorized_reads_is_refused(world, tmp_path, monkeypatch):
    rid, _ = simple_round(world.kit, "binding-race", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    original = Sources.export
    seen = {}

    def changed(self, ref, *, send=None):
        result = original(self, ref, send=send)
        key = canonical(ref.wire())
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            # Inject an export-view race only after the real authorized read. No freeze or send is involved.
            result["observation"]["title"] += " changed"
        return result

    monkeypatch.setattr(Sources, "export", changed)
    before = snapshot(tmp_path)
    with pytest.raises(ExtractionFailure, match="plan_sources_changed"):
        verify(world, out)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("raw", [b'{"nested":{"x":1,"x":2}}', b'{"value":1e9999}', b'{"value":Infinity}', b"\xff"])
def test_strict_plan_json_rejects_duplicates_overflow_constants_and_invalid_utf8(raw):
    with pytest.raises(ExtractionFailure, match="plan_input_invalid"):
        extraction_plan.strict_json(raw)


def test_unrelated_sibling_creation_during_source_read_does_not_change_plan_validity(world, tmp_path, monkeypatch):
    rid, _ = simple_round(world.kit, "unrelated-sibling", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    expected = verify(world, out)
    original = Sources.export
    made = []

    def sibling(self, ref, *, send=None):
        result = original(self, ref, send=send)
        if not made:
            made.append(True)
            (out.parent / "unrelated-directory").mkdir()
            (out.parent / "unrelated-file").write_bytes(b"unrelated")
        return result

    monkeypatch.setattr(Sources, "export", sibling)
    before_plan = snapshot(out)
    before_ingestion = snapshot(world.kit.root / "ingestion")
    assert verify(world, out) == expected
    assert snapshot(out) == before_plan
    assert snapshot(world.kit.root / "ingestion") == before_ingestion


def test_replacement_of_actual_plan_parent_during_source_read_is_refused(world, tmp_path, monkeypatch):
    rid, _ = simple_round(world.kit, "parent-race", ["a"])
    parent = tmp_path / "plan-parent"
    parent.mkdir()
    out = parent / "plan"
    make(world, out, rid)
    original = Sources.export
    moved = tmp_path / "old-plan-parent"

    def replace(self, ref, *, send=None):
        result = original(self, ref, send=send)
        if not moved.exists():
            parent.rename(moved)
            parent.mkdir()
            shutil.copytree(moved / "plan", out)
        return result

    monkeypatch.setattr(Sources, "export", replace)
    with pytest.raises(ExtractionFailure, match="plan_files_changed"):
        verify(world, out)


def test_actual_current_grant_revision_changes_binding_digest_and_revocation_refuses(world, tmp_path):
    rid, _ = simple_round(world.kit, "grant-revision", ["a"])
    out = tmp_path / "plan"
    make(world, out, rid)
    original = verify(world, out)
    registry = json.loads(world.kit.registry_path.read_bytes())
    grant = registry["sources"][0]["grant"]
    grant["revision"] += "-new"
    world.kit.registry_path.write_text(canonical(registry))
    changed = verify(world, out)
    assert changed["planDigest"] == original["planDigest"]
    assert changed["sourceRegistrySha256"] != original["sourceRegistrySha256"]
    assert changed["sourceBindingsDigest"] != original["sourceBindingsDigest"]
    grant["enabled"] = False
    world.kit.registry_path.write_text(canonical(registry))
    with pytest.raises((ExtractionFailure, IngestionFailure), match="source_unauthorized"):
        verify(world, out)
