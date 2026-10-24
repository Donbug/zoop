"""Portable review behavior with actual authored native ledgers, never real corpus bodies."""
import copy
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.corpus_review_smoke import fixture, native_plan_fixture, pin
from scripts.ingestion_smoke import json_bytes
from zoop_ai_pipeline import corpus_review as review
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, byte_hash


@pytest.fixture
def kit(tmp_path):
    value, path, ledgers = fixture(tmp_path / "source")
    return value, path, ledgers, tmp_path / "pack"


def save(kit):
    value, path, _, _ = kit
    path.write_bytes(json_bytes(value))


def prepare(kit):
    _, path, _, pack = kit
    return review.prepare(path, pack)


def annotation_file(kit):
    _, _, _, pack = kit
    path = pack.parent / "synthetic-human.json"
    value = json.loads((pack / "annotations.template.json").read_bytes())
    path.write_bytes(json_bytes(value))
    return value, path


def reviewed(value):
    value["cases"][0].update(status="reviewed", reviewerId="synthetic-reviewer", reviewedAt="2026-10-24T01:00:00+09:00",
                             graphNotes="Unknown: not enough context for a graph claim", ragQuestions=[])
    return value["cases"][0]


def rebind_pack(pack, change):
    inputs = json.loads((pack / "inputs.json").read_bytes())
    change(inputs)
    raw = json_bytes(inputs)
    (pack / "inputs.json").write_bytes(raw)
    manifest = json.loads((pack / "manifest.json").read_bytes())
    manifest["immutableInputsSha256"] = manifest["inputs"]["sha256"] = byte_hash(raw)
    manifest["inputs"]["bytes"] = len(raw)
    (pack / "manifest.json").write_bytes(json_bytes(manifest))


def test_all_documents_exact_bytes_portable_and_annotations_unread(kit, monkeypatch):
    value, path, ledgers, pack = kit
    before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for k in ledgers for p in (k.root / "state").iterdir()}
    real_read = review.read_file
    opens, live, maximum = [], 0, 0
    real_store = review.Store

    class Reader(real_store):
        def __init__(self, root, *, existing=False):
            nonlocal live, maximum
            assert existing is True
            super().__init__(root, existing=existing)
            live += 1
            maximum = max(maximum, live)

        def close(self):
            nonlocal live
            super().close()
            live -= 1

    def read(path, cap):
        assert "annotation" not in path.name and "gold" not in path.name
        opens.append(str(path))
        return real_read(path, cap)

    def forbidden(*args, **kwargs):
        raise AssertionError("network/child process not permitted")

    monkeypatch.setattr(review, "read_file", read)
    monkeypatch.setattr(review, "Store", Reader)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    result = prepare(kit)
    assert result["documents"] == 8 and result["reviewDocuments"] == 3 and maximum == 1 and live == 0
    assert before == {p: (Path(p).read_bytes(), Path(p).stat().st_mtime_ns, Path(p).stat().st_mode) for p in before}
    inputs = json.loads((pack / "inputs.json").read_bytes())
    originals = {d["originalExport"]["sha256"]: Path(d["originalExport"]["path"]).read_bytes() for d in value["documents"]}
    for record in inputs["documents"]:
        assert (pack / record["export"]["file"]).read_bytes() == originals[record["export"]["sha256"]]
    assert str(ledgers[0].root).encode() not in (pack / "inputs.json").read_bytes()
    (pack / "annotations.template.json").unlink()
    (pack / "annotations.template.json").symlink_to(pack.parent / "nonexistent-gold.json")
    moved = pack.parent / "moved"
    shutil.copytree(pack, moved, symlinks=True)
    shutil.rmtree(path.parent)
    assert review.verify(moved)["inputsSha256"] == result["inputsSha256"]
    assert len(opens) > 0


def test_selection_is_stable_round_robin_not_input_order(kit):
    value, path, _, pack = kit
    prepare(kit)
    first = json.loads((pack / "inputs.json").read_bytes())
    value["documents"].reverse()
    save(kit)
    review.prepare(path, pack.parent / "second")
    second = json.loads((pack.parent / "second" / "inputs.json").read_bytes())
    assert first["selection"] == second["selection"]
    strata = first["selection"]["strata"]
    assert [(s["channel"], s["publicationWeek"], s["availableCount"], s["selectedCount"]) for s in strata] == [
        ("alpha", "2026-W41", 5, 1), ("alpha", "unknown", 1, 1), ("beta", "2026-W42", 2, 1)]
    assert first["selection"]["selectedCaseIds"] == [s["availableCaseIds"][0] for s in strata]


@pytest.mark.parametrize("change", ["hash", "selector", "export", "rights", "registry", "binding-file"])
def test_stale_input_refuses_entire_pack(kit, change, monkeypatch):
    value, path, ledgers, pack = kit
    document = value["documents"][0]
    if change == "hash":
        document["originalExport"]["sha256"] = "0" * 64
    elif change == "selector":
        document["nativeExport"]["ordinal"] = 10
    elif change == "export":
        export = Path(document["originalExport"]["path"])
        raw = json.loads(export.read_bytes())
        raw["observation"]["title"] = "stale synthetic title"
        export.write_bytes(json_bytes(raw))
        document["originalExport"] = pin(export)
    elif change in {"rights", "registry"}:
        Path(document["authorityEvidence"]["rightsEvidence"]["path"] if change == "rights" else document["sourceRegistryFile"]["path"]).write_bytes(b"changed")
    else:
        original = review._write

        def write(output, raw):
            original(output, raw)
            if output.name == "manifest.json":
                path.write_bytes(path.read_bytes() + b" ")

        monkeypatch.setattr(review, "_write", write)
    save(kit)
    with pytest.raises(IngestionFailure):
        prepare(kit)
    assert not pack.exists() and not list(pack.parent.glob(".review-stage-*"))


@pytest.mark.parametrize("operation", ["disabled", "read", "store", "quote-display", "expired"])
def test_current_native_grants_not_saved_export_grants(kit, operation):
    value, _, ledgers, pack = kit
    grant = ledgers[0].registry["sources"][0]["grant"]
    if operation == "disabled":
        grant["enabled"] = False
    elif operation == "expired":
        grant["expiresAt"] = "2020-01-01T00:00:00+00:00"
    else:
        grant["allowedOperations"].remove(operation)
    ledgers[0].save_registry()
    for document in value["documents"][:6]:
        document["sourceRegistryFile"] = pin(ledgers[0].registry_path)
    save(kit)
    with pytest.raises(IngestionFailure, match="source_unauthorized"):
        prepare(kit)
    assert not pack.exists()


@pytest.mark.parametrize("operation", ["disabled", "read", "expired"])
def test_denied_grant_never_reads_original_export(kit, monkeypatch, operation):
    value, _, ledgers, pack = kit
    grant = ledgers[0].registry["sources"][0]["grant"]
    if operation == "disabled":
        grant["enabled"] = False
    elif operation == "expired":
        grant["expiresAt"] = "2020-01-01T00:00:00+00:00"
    else:
        grant["allowedOperations"].remove("read")
    ledgers[0].save_registry()
    originals = {Path(d["originalExport"]["path"]) for d in value["documents"]}
    for document in value["documents"][:6]:
        document["sourceRegistryFile"] = pin(ledgers[0].registry_path)
    save(kit)
    state = {str(p): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
             for ledger in ledgers for p in (ledger.root / "state").iterdir()}
    seen = []
    original = review.read_file

    def read(path, maximum):
        if path in originals:
            seen.append(path)
        return original(path, maximum)

    monkeypatch.setattr(review, "read_file", read)
    with pytest.raises(IngestionFailure, match="source_unauthorized"):
        prepare(kit)
    assert seen == [] and not pack.exists()
    assert state == {p: (Path(p).read_bytes(), Path(p).stat().st_mtime_ns, Path(p).stat().st_mode) for p in state}


def test_foreign_replacement_during_retraction_survives(kit, monkeypatch):
    _, _, ledgers, pack = kit
    original = review._publish
    rescued = pack.parent / "rescued-owned"
    adjacent = pack.parent / "unrelated"
    adjacent.write_bytes(b"untouched")
    replaced = False

    def publish(source, target, *args, **kwargs):
        nonlocal replaced
        if source == pack and not replaced:
            replaced = True
            os.rename(pack, rescued)
            pack.mkdir()
            (pack / "foreign").write_bytes(b"foreign replacement")
        original(source, target, *args, **kwargs)
        if target == pack:
            ledgers[0].registry["sources"][0]["grant"]["enabled"] = False
            ledgers[0].save_registry()

    monkeypatch.setattr(review, "_publish", publish)
    with pytest.raises(IngestionFailure):
        prepare(kit)
    assert replaced
    assert (rescued / "manifest.json").is_file()
    assert (pack / "foreign").read_bytes() == b"foreign replacement"
    assert adjacent.read_bytes() == b"untouched"


def test_foreign_replacement_is_quarantined_if_restore_name_taken(kit, monkeypatch):
    _, _, ledgers, pack = kit
    original = review._publish
    rescued = pack.parent / "rescued-owned"
    replaced = False

    def publish(source, target, parent):
        nonlocal replaced
        if source == pack and not replaced:
            replaced = True
            os.rename(pack, rescued)
            pack.mkdir()
            (pack / "foreign").write_bytes(b"foreign replacement")
            original(source, target, parent)
            pack.mkdir()
            (pack / "newer").write_bytes(b"new output")
        else:
            original(source, target, parent)
            if target == pack:
                ledgers[0].registry["sources"][0]["grant"]["enabled"] = False
                ledgers[0].save_registry()

    monkeypatch.setattr(review, "_publish", publish)
    with pytest.raises(IngestionFailure, match="review_pin_changed"):
        prepare(kit)
    quarantine = list(pack.parent.glob(".review-quarantine-*"))
    assert replaced and len(quarantine) == 1
    assert (quarantine[0] / "foreign").read_bytes() == b"foreign replacement"
    assert (pack / "newer").read_bytes() == b"new output"
    assert (rescued / "manifest.json").is_file()


def test_rollback_refuses_occupied_quarantine(kit, monkeypatch):
    _, _, ledgers, pack = kit
    original = review._publish
    quarantine = None

    def publish(source, target, *args, **kwargs):
        nonlocal quarantine
        original(source, target, *args, **kwargs)
        if target == pack:
            quarantine = source
            quarantine.mkdir()
            (quarantine / "foreign").write_bytes(b"not ours")
            ledgers[0].registry["sources"][0]["grant"]["enabled"] = False
            ledgers[0].save_registry()

    monkeypatch.setattr(review, "_publish", publish)
    with pytest.raises(IngestionFailure, match="review_pin_changed"):
        prepare(kit)
    assert not pack.exists()
    assert (quarantine / "foreign").read_bytes() == b"not ours"


def test_cleanup_keeps_foreign_directory_replacing_opened_quarantine(kit, monkeypatch):
    _, _, ledgers, pack = kit
    publish = review._publish
    remove = review._remove_owned
    scan = os.scandir
    rescued = pack.parent / "rescued-cleanup"
    swapped = False

    def revoke(source, target, parent):
        publish(source, target, parent)
        if target == pack:
            ledgers[0].registry["sources"][0]["grant"]["enabled"] = False
            ledgers[0].save_registry()

    def replace_on_scan(directory):
        nonlocal swapped
        if isinstance(directory, int) and not swapped:
            swapped = True
            os.rename(quarantine, rescued)
            quarantine.mkdir()
            (quarantine / "foreign").write_bytes(b"keep after open")
        return scan(directory)

    def cleanup(parent, path, owned):
        nonlocal quarantine
        quarantine = path
        monkeypatch.setattr(os, "scandir", replace_on_scan)
        return remove(parent, path, owned)

    quarantine = None
    monkeypatch.setattr(review, "_publish", revoke)
    monkeypatch.setattr(review, "_remove_owned", cleanup)
    with pytest.raises(IngestionFailure, match="review_pin_changed"):
        prepare(kit)
    assert swapped and not pack.exists()
    assert (quarantine / "foreign").read_bytes() == b"keep after open"
    assert rescued.is_dir()


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_revocation_through_publication_retracts_own_pack(kit, monkeypatch, boundary):
    _, _, ledgers, pack = kit
    original_publish = review._publish
    original_write = review._write

    def revoke():
        ledgers[0].registry["sources"][0]["grant"]["enabled"] = False
        ledgers[0].save_registry()

    def publish(source, target, parent):
        original_publish(source, target, parent)
        if target == pack:
            revoke()

    def write(output, raw):
        original_write(output, raw)
        if output.name == "manifest.json":
            revoke()

    monkeypatch.setattr(review, "_publish" if boundary == "after" else "_write", publish if boundary == "after" else write)
    with pytest.raises(IngestionFailure, match="review_pin_changed"):
        prepare(kit)
    assert not pack.exists() and not list(pack.parent.glob(".review-stage-*"))


@pytest.mark.parametrize("variation", ["existing-empty", "existing-foreign", "symlink", "overlap", "input-symlink", "unknown-date", "extra", "duplicate", "bool-quota", "partial-state", "hot-wal"])
def test_namespaces_closed_fields_and_unknown_policy(kit, variation):
    value, path, ledgers, pack = kit
    if variation.startswith("existing"):
        pack.mkdir()
        if variation == "existing-foreign":
            (pack / "foreign").write_bytes(b"sentinel")
    elif variation == "symlink":
        pack.symlink_to(path.parent, target_is_directory=True)
    elif variation == "overlap":
        pack = Path(value["documents"][0]["originalExport"]["path"]).parent / "pack"
    elif variation == "input-symlink":
        source = Path(value["documents"][0]["originalExport"]["path"])
        link = source.parent / "link.json"
        link.symlink_to(source)
        value["documents"][0]["originalExport"]["path"] = str(link)
    elif variation == "unknown-date":
        value["selectionPolicy"]["allowUnknownDate"] = False
    elif variation == "extra":
        value["gold"] = "forbidden"
    elif variation == "duplicate":
        value["documents"].append(copy.deepcopy(value["documents"][0]))
    elif variation == "bool-quota":
        value["selectionPolicy"]["perStratumQuota"] = True
    elif variation == "partial-state":
        (ledgers[0].root / "state" / "ingestion.lock").unlink()
    elif variation == "hot-wal":
        (ledgers[0].root / "state" / "ingestion.sqlite3-wal").write_bytes(b"unrecovered")
    save(kit)
    with pytest.raises((IngestionFailure, ValidationError, OSError)):
        review.prepare(path, pack)
    if variation == "existing-foreign":
        assert (pack / "foreign").read_bytes() == b"sentinel"
    if variation == "partial-state":
        assert not (ledgers[0].root / "state" / "ingestion.lock").exists()


def test_unreviewed_unknown_and_excluded_are_not_scores(kit):
    prepare(kit)
    value, path = annotation_file(kit)
    assert review.annotations_check(kit[3], path)["counts"] == {"unreviewed": 3, "reviewed": 0, "excluded": 0}
    reviewed(value)
    value["cases"][1].update(status="excluded", reviewerId="synthetic-reviewer", reviewedAt="2026-10-24T01:00:00+00:00", exclusionReason="Synthetic exclusion only")
    path.write_bytes(json_bytes(value))
    result = review.annotations_check(kit[3], path)
    assert result["counts"] == {"unreviewed": 1, "reviewed": 1, "excluded": 1}
    assert "score" not in result and "accuracy" not in result


@pytest.mark.parametrize("variation", ["foreign", "extra-case", "duplicate", "missing", "extra-field", "wrong-input", "empty-terminal", "no-reviewer", "no-time", "no-notes", "no-rag", "unreviewed-judgment", "no-exclusion-reason", "unknown-status"])
def test_annotation_closed_shape_and_required_human_fields(kit, variation):
    prepare(kit)
    value, path = annotation_file(kit)
    row = reviewed(value)
    if variation == "foreign":
        row["caseId"] = "foreign"
    elif variation == "extra-case":
        value["cases"].append({**row, "caseId": "foreign"})
    elif variation == "duplicate":
        value["cases"].append(copy.deepcopy(row))
    elif variation == "missing":
        value["cases"].pop()
    elif variation == "extra-field":
        row["automaticScore"] = 1
    elif variation == "wrong-input":
        value["inputsSha256"] = "0" * 64
    elif variation == "empty-terminal":
        row.update(graphNotes=" ")
    elif variation in {"no-reviewer", "no-time", "no-notes", "no-rag"}:
        row[{"no-reviewer": "reviewerId", "no-time": "reviewedAt", "no-notes": "graphNotes", "no-rag": "ragQuestions"}[variation]] = None
    elif variation == "unreviewed-judgment":
        row["status"] = "unreviewed"
    elif variation == "no-exclusion-reason":
        row["status"] = "excluded"
    else:
        row["status"] = "unknown"
    path.write_bytes(json_bytes(value))
    with pytest.raises((IngestionFailure, ValidationError)):
        review.annotations_check(kit[3], path)


@pytest.mark.parametrize("variation", ["valid", "utf8-offset", "wrong-quote", "foreign-document", "wrong-version", "bounds", "generated-separator"])
def test_exact_unicode_evidence_and_raw_locator_bounds(kit, variation):
    prepare(kit)
    value, path = annotation_file(kit)
    row = reviewed(value)
    inputs = json.loads((kit[3] / "inputs.json").read_bytes())
    record = next(d for d in inputs["documents"] if d["caseId"] == row["caseId"])
    document = json.loads((kit[3] / record["export"]["file"]).read_bytes())["document"]
    start = document["text"].index("반복😀")
    span = {"documentId": document["documentId"], "documentVersion": document["documentVersion"], "start": start, "end": start + 3, "quote": "반복😀"}
    if variation == "utf8-offset":
        span["start"] = len(document["text"][:start].encode())
    elif variation == "wrong-quote":
        span["quote"] = "반복"
    elif variation == "foreign-document":
        span["documentId"] = "foreign"
    elif variation == "wrong-version":
        span["documentVersion"] = "foreign"
    elif variation == "bounds":
        span["end"] = len(document["text"]) + 1
    elif variation == "generated-separator":
        span.update(start=0, end=len(document["text"]), quote=document["text"])
    row["evidenceSpans"] = [span]
    path.write_bytes(json_bytes(value))
    if variation == "valid":
        assert review.annotations_check(kit[3], path)["counts"]["reviewed"] == 1
    else:
        with pytest.raises((IngestionFailure, ValidationError)):
            review.annotations_check(kit[3], path)


@pytest.mark.parametrize("variation", ["relative-escape", "observation", "selection", "extra-key", "duplicate-case", "locator-bounds", "document-hash", "foreign-file", "symlink-document"])
def test_portable_verify_rejects_rebound_tampering(kit, variation):
    prepare(kit)
    pack = kit[3]
    if variation in {"relative-escape", "observation", "selection", "extra-key", "duplicate-case"}:
        def change(inputs):
            record = inputs["documents"][0]
            if variation == "relative-escape":
                record["export"]["file"] = "../escape.json"
            elif variation == "observation":
                record["observation"]["title"] = "foreign"
            elif variation == "selection":
                inputs["selection"]["selectedCaseIds"].reverse()
            elif variation == "extra-key":
                inputs["gold"] = []
            else:
                inputs["documents"][1]["caseId"] = record["caseId"]
        rebind_pack(pack, change)
    elif variation in {"locator-bounds", "document-hash"}:
        def change(inputs):
            record = inputs["documents"][0]
            path = pack / record["export"]["file"]
            data = json.loads(path.read_bytes())
            if variation == "locator-bounds":
                data["document"]["rawLocators"][0]["end"] = len(data["document"]["text"]) + 1
            else:
                data["document"]["sourceHash"] = "0" * 64
            raw = json_bytes(data)
            path.unlink()
            name = "documents/" + byte_hash(raw) + ".json"
            (pack / name).write_bytes(raw)
            record["export"] = {"file": name, "sha256": byte_hash(raw), "bytes": len(raw)}
        rebind_pack(pack, change)
    elif variation == "foreign-file":
        (pack / "documents" / "foreign").write_bytes(b"foreign")
    else:
        path = next((pack / "documents").iterdir())
        path.unlink()
        path.symlink_to(kit[1])
    with pytest.raises((IngestionFailure, ValidationError, OSError)):
        review.verify(pack)


def test_portable_explicit_null_optional_collection_is_supported(kit):
    from scripts.corpus_review_smoke import cli

    prepare(kit)
    pack = kit[3]

    def change(inputs):
        record = inputs["documents"][0]
        path = pack / record["export"]["file"]
        document = json.loads(path.read_bytes())
        for observation in (document["observation"], record["observation"]):
            observation["collection"] = None
            observation["provenance"] = None
        raw = json_bytes(document)
        path.unlink()
        name = "documents/" + byte_hash(raw) + ".json"
        (pack / name).write_bytes(raw)
        record["export"] = {"file": name, "sha256": byte_hash(raw), "bytes": len(raw)}

    rebind_pack(pack, change)
    assert cli("verify", "--pack", pack)["documents"] == 8


@pytest.mark.parametrize("variation", ["valid", "rights-pin", "exclusion-pin", "plan-pin", "unbound-rights", "unbound-exclusion", "missing-plan", "grant"])
def test_current_corpus_plan_external_evidence_boundary(tmp_path, variation):
    bindings, path = native_plan_fixture(tmp_path)
    document = bindings["documents"][0]
    evidence = document["authorityEvidence"]
    if variation in {"rights-pin", "exclusion-pin", "plan-pin"}:
        key = {"rights-pin": "rightsEvidence", "exclusion-pin": "exclusionManifest", "plan-pin": "planFile"}[variation]
        Path(evidence[key]["path"]).write_bytes(b"changed")
    elif variation in {"unbound-rights", "unbound-exclusion"}:
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(b"{}")
        evidence["rightsEvidence" if variation == "unbound-rights" else "exclusionManifest"] = pin(replacement)
    elif variation == "missing-plan":
        evidence["planFile"] = None
    elif variation == "grant":
        plan_path = Path(evidence["planFile"]["path"])
        data = json.loads(plan_path.read_bytes())
        data["config"]["grant"]["revision"] = "different"
        plan_path.write_bytes(json_bytes(data))
        evidence["planFile"] = pin(plan_path)
    path.write_bytes(json_bytes(bindings))
    output = tmp_path / "pack"
    if variation == "valid":
        assert review.prepare(path, output)["documents"] == 1
        assert review.verify(output)["documents"] == 1
    else:
        with pytest.raises((IngestionFailure, ValidationError)):
            review.prepare(path, output)
        assert not output.exists()


@pytest.mark.parametrize("channel,basis,url,allowed", [
    ("policy-news", "portal-path", "https://m.korea.kr/news/policyNewsView.do?newsId=100000001", True),
    ("press-release", "operator-classification", "https://m.korea.kr/news/policyNewsView.do?newsId=100000001", False),
    ("policy-news", "portal-path", "https://example.invalid/news/policyNewsView.do?newsId=100000001", False),
])
def test_portal_channel_claim_must_match_native_url(kit, channel, basis, url, allowed):
    # Exercise metadata through portable verification; creation's native equality is covered separately.
    prepare(kit)
    pack = kit[3]
    def change(inputs):
        record = inputs["documents"][0]
        path = pack / record["export"]["file"]
        data = json.loads(path.read_bytes())
        data["observation"]["url"] = url
        record["observation"]["url"] = url
        record["selection"].update(channel=channel, channelBasis=basis)
        path.unlink()
        raw = json_bytes(data)
        name = "documents/" + byte_hash(raw) + ".json"
        (pack / name).write_bytes(raw)
        record["export"] = {"file": name, "sha256": byte_hash(raw), "bytes": len(raw)}
        records = [review.Record.model_validate(r) for r in inputs["documents"]]
        inputs["selection"] = review.choose(records, review.Policy.model_validate(inputs["selection"]["policy"])).wire()
    rebind_pack(pack, change)
    if allowed:
        assert review.verify(pack)["documents"] == 8
    else:
        with pytest.raises(IngestionFailure, match="review_channel"):
            review.verify(pack)


@pytest.mark.parametrize("variation", ["bindings-size", "export-size", "total-size", "document-count", "quota", "review-count", "duplicate-json", "nan-json"])
def test_explicit_input_caps_and_strict_json(kit, monkeypatch, variation):
    value, path, _, pack = kit
    if variation == "bindings-size":
        monkeypatch.setattr(review, "MAX_BINDINGS", 10)
    elif variation == "export-size":
        monkeypatch.setattr(review, "MAX_EXPORT", 10)
    elif variation == "total-size":
        monkeypatch.setattr(review, "MAX_TOTAL", 10)
    elif variation == "document-count":
        value["documents"] = [value["documents"][0]] * 2001
    elif variation == "quota":
        value["selectionPolicy"]["perStratumQuota"] = 51
    elif variation == "review-count":
        value["selectionPolicy"]["maxReviewDocuments"] = 201
    save(kit)
    if variation == "duplicate-json":
        path.write_bytes(path.read_bytes().replace(b'"perStratumQuota":2', b'"perStratumQuota":2,"perStratumQuota":2'))
    elif variation == "nan-json":
        path.write_bytes(path.read_bytes().replace(b'"perStratumQuota":2', b'"perStratumQuota":NaN'))
    with pytest.raises((IngestionFailure, ValidationError)):
        prepare(kit)
    assert not pack.exists()


def test_native_item_round_cannot_downgrade_evidence_boundary(kit):
    value, _, _, pack = kit
    selector = value["documents"][0]["nativeExport"]
    selector.update(sourceId="korea-portal", roundId="item-100000001")
    save(kit)
    with pytest.raises(IngestionFailure, match="review_corpus_plan_required"):
        prepare(kit)
    assert not pack.exists()


def test_crashed_staging_is_not_published_or_adopted(kit):
    _, path, _, pack = kit
    code = """import os,sys
from zoop_ai_pipeline import corpus_review as r
from pathlib import Path
original=r._write
def stop(path,raw):
    original(path,raw)
    if path.name=='inputs.json':
        os._exit(73)
r._write=stop
r.prepare(Path(sys.argv[1]),Path(sys.argv[2]))
"""
    child = subprocess.run([sys.executable, "-B", "-c", code, str(path), str(pack)], capture_output=True, timeout=60)
    assert child.returncode == 73 and not child.stdout and not child.stderr and not pack.exists()
    abandoned = list(pack.parent.glob(".review-stage-*"))
    assert len(abandoned) == 1
    snapshot = {str(p.relative_to(abandoned[0])): p.read_bytes() for p in abandoned[0].rglob("*") if p.is_file()}
    assert prepare(kit)["state"] == "prepared"
    assert snapshot == {str(p.relative_to(abandoned[0])): p.read_bytes() for p in abandoned[0].rglob("*") if p.is_file()}


@pytest.mark.parametrize("gate", ["korea-portal-static-2", "korea-portal-static-3"])
@pytest.mark.parametrize("variation", [
    "valid", "missing-body", "corrupt-body", "missing-receipt", "corrupt-receipt",
    "receipt-identity", "receipt-url", "receipt-size", "missing-rights", "rights-hash", "rights-notice",
    "rights-warning", "rights-contact", "rights-extra", "rights-missing-field", "unknown-gate",
])
def test_native_body_receipt_and_all_rights_revalidated_readonly(tmp_path, monkeypatch, gate, variation):
    bindings, path = native_plan_fixture(tmp_path / "source", gate=gate)
    document = bindings["documents"][0]
    exported = json.loads(Path(document["originalExport"]["path"]).read_bytes())
    registry = json.loads(Path(document["sourceRegistryFile"]["path"]).read_bytes())
    source_root = Path(registry["sources"][0]["inputRoot"])
    collected = exported["observation"]["collection"]
    receipt_path = source_root / collected["receipt"]["file"]
    body_path = source_root / "collections" / collected["collectionId"] / "bodies" / (collected["bodySha256"] + ".bin")
    plan_path = Path(document["authorityEvidence"]["planFile"]["path"])
    plan = json.loads(plan_path.read_bytes())
    rights_path = Path(plan["config"]["stateDir"]) / "items" / "100000001" / "rights.json"
    if variation == "missing-body":
        body_path.unlink()
    elif variation == "corrupt-body":
        body_path.write_bytes(body_path.read_bytes() + b" ")
    elif variation == "missing-receipt":
        receipt_path.unlink()
    elif variation == "corrupt-receipt":
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    elif variation.startswith("receipt-"):
        receipt = json.loads(receipt_path.read_bytes())
        if variation == "receipt-identity":
            receipt["candidateId"] = "100000002"
        elif variation == "receipt-url":
            receipt["requestedUrl"] = receipt["requestedUrl"].replace("100000001", "100000002")
        else:
            receipt["bodyBytes"] += 1
        raw = json_bytes(receipt)
        replacement = receipt_path.parent / (byte_hash(raw) + ".json")
        replacement.write_bytes(raw)
        # Rebind every exported pin and the actual native candidate, so the proof checker,
        # not merely a stale-export/hash check, must reject the forged receipt claims.
        collected["receipt"] = {"file": str(replacement.relative_to(source_root)), "sha256": byte_hash(raw)}
        import sqlite3
        database = Path(document["ingestionStateDir"]) / "ingestion.sqlite3"
        connection = sqlite3.connect(database)
        try:
            candidate = json.loads(connection.execute("SELECT data FROM candidates").fetchone()[0])
            candidate["collection"]["receipt"] = collected["receipt"]
            connection.execute("UPDATE candidates SET data=?", (json_bytes(candidate).decode(),))
            connection.commit()
        finally:
            connection.close()
        export_path = Path(document["originalExport"]["path"])
        export_path.write_bytes(json_bytes(exported))
        document["originalExport"] = pin(export_path)
        path.write_bytes(json_bytes(bindings))
    elif variation == "missing-rights":
        rights_path.unlink()
    elif variation.startswith("rights-"):
        rights = json.loads(rights_path.read_bytes())
        field = {"rights-hash": "bodySha256", "rights-notice": "notice", "rights-warning": "qualityWarnings",
                 "rights-contact": "contactPresent", "rights-extra": "extra", "rights-missing-field": "license"}[variation]
        if variation == "rights-missing-field":
            del rights[field]
        elif variation == "rights-contact":
            rights[field] = not rights[field]
        elif variation == "rights-warning":
            rights[field] = []
        else:
            rights[field] = "changed"
        rights_path.write_bytes(json_bytes(rights))
    elif variation == "unknown-gate":
        plan["gateVersion"] = "korea-portal-static-999"
        plan_path.write_bytes(json_bytes(plan))
        document["authorityEvidence"]["planFile"] = pin(plan_path)
        path.write_bytes(json_bytes(bindings))
    before = {str(p.relative_to(path.parent)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
              for p in path.parent.rglob("*") if p.is_file()}
    output = tmp_path / "pack"
    def forbidden(*args, **kwargs):
        raise AssertionError("network/child process not permitted")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    if variation == "valid":
        assert review.prepare(path, output)["documents"] == 1
        assert review.verify(output)["documents"] == 1
    else:
        with pytest.raises(IngestionFailure, match="review_(native_proof_mismatch|plan_invalid)"):
            review.prepare(path, output)
        assert not output.exists()
    assert before == {str(p.relative_to(path.parent)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                      for p in path.parent.rglob("*") if p.is_file()}
