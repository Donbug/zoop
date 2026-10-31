"""Synthetic retained-byte controls through real private CLI seams; no external sockets or keys.

Records deliberately exercise the actual acquisition wire shape. They are authored
controls, not evidence of fetching these publisher URLs or independent model quality.
"""
from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE / "scripts"))
from scripts import overnight_history as history
from overnight_inputs import bind_execution, encoded, file_pin, indexed_items, load, prepare_item, save, sha
from scripts.ingestion_smoke import ownership_env
from scripts.extraction_smoke import Kit, PROMPT
from scripts.relation_smoke import CATALOGUE, RelKit, co, converge, proposal
from tests.test_private_intake import extracted_fixture
from zoop_ai_pipeline import extraction_replay as analysis, ingestion_parsers as parsers
from zoop_ai_pipeline.extraction_contracts import Catalogue
from zoop_ai_pipeline.ingestion import Ingestor, Store
from zoop_ai_pipeline.ingestion_contracts import Authority, Export, FileRef, IngestionFailure, Item, Registry, canonical, digest
from zoop_ai_pipeline.private_processing import PrivateAuthority
from zoop_ai_pipeline.private_retained import read_record

ACTOR = {"kind": "user-private-experiment", "acceptedBy": "Main", "decidedAt": "2026-10-28T00:00:00+00:00",
         "statement": "Synthetic offline authority control; not authorization for external calls or public reuse."}
QUOTE = "합성기업은 2026년 3분기 공급 계약을 발표했다."
SUPPLY = "합성부품은 합성기업에 배터리 부품을 공급한다."
OPENAI = "openai-compatible:" + digest({"endpoint": "https://api.openai.com/v1"})
TYPESAFE = "typesafe-native:" + digest({"api": "systemone", "endpoint": "https://api.typesafe.ai/v1"})


class RuntimeIdentity:
    """Non-executing runtime configuration fixture; cannot send or open a socket."""
    family = SimpleNamespace(stages=("extract", "compare", "topic", "relation", "impact", "verify-relation", "verify-impact"))

    def binding(self):
        return {"identity": "a" * 64, "generation": {"endpoint": "https://api.openai.com/v1"},
                "verifier": {"endpoint": "https://api.typesafe.ai/v1"}}

    def purpose(self, stage):
        return "pipeline:" + stage

    def recipient(self, stage):
        return TYPESAFE if stage.startswith("verify-") else OPENAI

    def fallback_recipient(self, stage):
        return None


RUNTIMES = [RuntimeIdentity()]


def fingerprint(root):
    return {str(path.relative_to(root)): (stat.S_IMODE(path.stat().st_mode), path.stat().st_mtime_ns,
                                         sha(path.read_bytes()) if path.is_file() else None)
            for path in [root, *sorted(root.rglob("*"))]}


def retained_fixture(root, variant="markdown", *, suffix="", source=None):
    """Immutable-shaped files only; not private_intake.State and not a live fetch."""
    root.mkdir(parents=True, mode=0o700)
    record, raw, envelope_raw, _ = extracted_fixture(backend="defuddle" if variant == "defuddle" else "deepseek-fetch")
    record = copy.deepcopy(record)
    plan_id = "authored-plan" + suffix
    record["requestUrl"] += suffix
    identifier = "private-news-" + digest([plan_id, record["requestUrl"]])
    record["privateId"] = identifier
    plan = {"schemaVersion": "zoop-private-news-plan-1", "config": {"planId": plan_id}}
    record["planDigest"] = digest(plan)
    record["source"] = source or ("foreign-newsroom" if variant == "html" else "openai-newsroom")
    if variant == "html":
        raw = ("<html><article><p>" + QUOTE + "</p><p>" + SUPPLY + "</p></article></html>").encode()
        record.update(schemaVersion="zoop-private-news-record-1", provenance="private-public-web",
                      articleXPath=None, finalUrl=record["requestUrl"], canonicalUrl=record["requestUrl"],
                      publisher="Authored foreign newsroom", parserProfile=parsers.profile(),
                      prepared=parsers.prepare(raw, "text/html", None))
        for key in ("extractionArtifact", "extractionBackend", "representation"):
            del record[key]
    else:
        envelope = json.loads(envelope_raw)
        if variant == "markdown":
            from zoop_ai_pipeline.extraction_fallback import prepare_markdown
            text = "# Authored fixture\n\nJuly 27, 2026\n\n" + QUOTE + "\n\n" + SUPPLY + "\n\n😀 e\u0301 `code` \\{x\\}\n"
            prepared = prepare_markdown(text)
            import base64
            response = canonical({"title": "Authored fixture", "content": text}).encode()
            envelope["providerReceipt"].update(rawResponseBase64=base64.b64encode(response).decode(),
                                               rawResponseSha256=sha(response), receivedBytes=len(response))
        else:
            text = "<html><body><p>" + QUOTE + "</p><p>" + SUPPLY + "</p></body></html>"
            prepared = parsers.prepare(text.encode(), "text/html", "//body")
        raw = text.encode()
        envelope.update(requestedUrl=record["requestUrl"], retainedText=text, rawSha256=sha(raw),
                        contentSha256=sha(prepared["text"].encode()), prepared=prepared)
        envelope["nativeObservation"]["requestedUrl"] = record["requestUrl"]
        envelope_raw = canonical(envelope).encode()
        artifact = {"file": identifier + ".extraction.json", "sha256": sha(envelope_raw)}
        record.update(prepared=prepared, extractionArtifact=artifact)
        (root / artifact["file"]).write_bytes(envelope_raw)
    record.update(rawSha256=sha(raw), rawBytes=len(raw), textSha256=sha(record["prepared"]["text"].encode()))
    (root / "PLAN.json").write_bytes(canonical(plan).encode())
    (root / (identifier + ".raw")).write_bytes(raw)
    path = root / (identifier + ".json")
    path.write_bytes(canonical(record).encode())
    # These must never be opened by the production bridge (even for recovery).
    (root / "STATE.json").write_bytes(b"immutable old state sentinel")
    (root / "QUEUE.sqlite3-wal").write_bytes(b"immutable old WAL sentinel")
    for file in root.iterdir():
        file.chmod(0o600)
    return {"sourceId": record["source"], "stateDir": str(root), "recordPath": str(path),
            "recordSha256": sha(path.read_bytes()), "privateId": identifier, "planId": plan_id}


def cli(module, command, request, *args, expected=0):
    guard = ("import sys,runpy\n"
             "def deny(event,args):\n"
             " if event in {'socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.bind'}: raise RuntimeError('network forbidden')\n"
             "sys.addaudithook(deny)\n"
             f"runpy.run_module('zoop_ai_pipeline.{module}_cli',run_name='__main__')\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", **ownership_env()}
    process = subprocess.run([sys.executable, "-c", guard, command, *map(str, args)], input=encoded(request),
                             capture_output=True, env=env, cwd=PIPELINE, timeout=120)
    assert process.returncode == expected, (process.stdout.decode(), process.stderr.decode())
    assert not process.stderr
    return json.loads(process.stdout)


def exported(unit, *, authority=None, require_store=False):
    store = Store(Path(unit["ingestionStateDir"]), existing=True)
    try:
        return Ingestor(store, authority or PrivateAuthority(Path(unit["privateProcessing"]))).export(
            Export.model_validate({"schemaVersion": "zoop-ingestion-s2-1", **unit["observation"]}), require_store=require_store)
    finally:
        store.close()


@pytest.fixture
def unit(tmp_path):
    item = retained_fixture(tmp_path / "old", "markdown")
    return prepare_item(item, tmp_path / "new", "authored-run", RUNTIMES, actor=ACTOR)


@pytest.mark.parametrize("variant", ["html", "markdown", "defuddle"])
def test_retained_import_cli_is_analysis_ready_and_old_namespace_is_untouched(tmp_path, monkeypatch, variant):
    old = tmp_path / "old"
    item = retained_fixture(old, variant)
    before = fingerprint(old)
    original_open, opened = os.open, []

    def observed_open(path, *args, **kwargs):
        if str(path) in {"STATE.json", "QUEUE.sqlite3-wal", "QUEUE.sqlite3", ".lock"}:
            raise AssertionError("bridge attempted old state or WAL access")
        opened.append(str(path))
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as guard:
        guard.setattr(os, "open", observed_open)
        prepared = prepare_item(item, tmp_path / "new", "authored-run", RUNTIMES, actor=ACTOR)
    assert fingerprint(old) == before
    assert prepared["originalPreserved"] and prepared["sourceId"] == item["sourceId"]
    request = prepared["importRequest"]
    import_auth = Path(prepared["export"]).parent / "import.json"
    state = tmp_path / "cli-ingestion"
    result = cli("ingestion", "run", request, "--state-dir", state, "--private-processing", import_auth,
                 "--fixture-manifest", prepared["importManifest"])
    assert result["state"] == "complete" and result["counts"]["textReady"] == 1
    assert result["provenance"] == "retained_private"
    selector = {"schemaVersion": "zoop-ingestion-s2-1", **prepared["observation"]}
    output = cli("ingestion", "export", selector, "--state-dir", state, "--private-processing", prepared["privateProcessing"])
    assert output["observation"]["provenance"] == "retained_private"
    assert "collection" not in output["observation"]
    assert QUOTE in output["document"]["text"]
    assert output["grant"]["grantId"].startswith("private-processing:")
    assert analysis.article(output, True).language == "und"
    if variant == "markdown":
        assert output["observation"]["mediaType"] == "text/markdown"
        assert output["observation"]["retained"]["finalUrl"] is None
        assert output["document"]["text"] == (old / (item["privateId"] + ".raw")).read_text()
        assert any("Markdown" in limitation for limitation in output["locatorMetadata"]["limitations"])
    assert fingerprint(old) == before


class PrivateReplayKit(RelKit):
    def __init__(self, root, unit):
        self.root, self.unit = root, unit

    def export(self, ref):
        assert ref == self.unit["observation"]
        return exported(self.unit)

    def rel(self, command, request, *, replay=None, verifier=None):
        args = ["--state-dir", self.root / "relation", "--extraction-state-dir", self.root / "extraction",
                "--ingestion-state-dir", self.unit["ingestionStateDir"], "--private-processing", self.unit["privateProcessing"]]
        if replay:
            args += ["--replay", replay]
        if verifier:
            args += ["--verifier-replay", verifier]
        return cli("relation", command, request, *args)


@pytest.mark.parametrize("variant", ["html", "markdown"])
def test_real_cli_s2_s3_and_private_graph_inputs_keep_retained_authority(tmp_path, variant):
    from zoop_ai_pipeline.graph_projection import Paths, Source, gate, load_registry, plan_version
    item = retained_fixture(tmp_path / "old", variant)
    unit = prepare_item(item, tmp_path / "new", "authored-run", RUNTIMES, actor=ACTOR)
    output = exported(unit)
    article = analysis.article(output, True)
    evidence = Kit.evidence(article, QUOTE)
    mention = Kit.mention(None, article, "m-retained", [evidence])
    fixture = {"format": "zoop-analysis-replay-1", "synthetic": True, "recordingKind": "authored-test", "promptVersion": PROMPT,
               "analysisVersion": "authored-private-1", "records": [{"stage": "extract", "requestDigest": analysis.request_digest(
                   "extract", analysis.extract_input(article, PROMPT, Catalogue.model_validate(CATALOGUE)), "authored-private-1"),
                   "response": {"mentions": [mention]}}]}
    replay = tmp_path / "s2-replay.json"
    save(replay, fixture)
    request = {"schemaVersion": "zoop-extraction-s2-2", "jobId": "private-s2", "incoming": unit["observation"],
               "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
               "promptVersion": PROMPT, "catalogue": CATALOGUE, "snapshot": {"revision": "empty", "events": []}, "topic": None}
    s2 = cli("extraction", "run", request, "--state-dir", tmp_path / "extraction", "--ingestion-state-dir", unit["ingestionStateDir"],
             "--private-processing", unit["privateProcessing"], "--replay", replay)
    assert s2["state"] == "ready" and s2["delivery"]["status"] == "current"
    assert s2["counts"]["eventCandidates"]["candidate"] == 1
    assert next(iter(s2["binding"]["documents"].values()))["grant"] == output["grant"]
    kit = PrivateReplayKit(tmp_path, unit)
    world = SimpleNamespace(kit=kit, refs={"main": unit["observation"]}, s2=s2)
    start = article.body.index(SUPPLY)
    citation = {"documentId": unit["observation"]["documentId"], "documentVersion": unit["observation"]["documentVersion"],
                "start": start, "end": start + len(SUPPLY), "quote": SUPPLY}
    s3 = converge(world, "private-s3", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [citation], product="배터리 부품")], process=True)
    assert s3["state"] == "ready" and s3["delivery"]["status"] == "current"
    canonical_path = tmp_path / "private-graph-canonical.json"
    save(canonical_path, {"schemaVersion": "zoop-graph-canonical-1", "entries": [
        {"upstream": {"jobId": s2["jobId"], "inputDigest": s2["inputDigest"]}, "kind": "company", "ref": company,
         "canonicalId": company, "decisionRef": "synthetic-private-only"} for company in ("SYNTH-1", "SYNTH-3")]})
    paths = Paths(tmp_path / "relation", tmp_path / "extraction", Path(unit["ingestionStateDir"]), None, canonical_path, Path(unit["privateProcessing"]))
    relation = {"jobId": s3["jobId"], "inputDigest": s3["inputDigest"]}
    with Source(paths) as source:
        current = gate(source, relation, None)
        plan = plan_version("private-smoke", current, load_registry(canonical_path).entries)
    assert len(plan["nodes"]) == 2 and len(plan["edges"]) == 1
    assert QUOTE not in canonical(plan) and SUPPLY not in canonical(plan)
    save(tmp_path / "private-graph-freeze.json", {"schemaVersion": "zoop-graph-projection-1", "versionId": "private-smoke", "relation": relation})
    # The ordinary public CLI route cannot load the private execution receipt.
    refused = cli("extraction", "inspect", {"schemaVersion": "zoop-extraction-s2-2", "jobId": "private-s2"},
                  "--state-dir", tmp_path / "extraction", "--ingestion-state-dir", unit["ingestionStateDir"],
                  "--sources", unit["privateProcessing"], expected=2)
    assert refused["error"]["code"] == "private_processing_not_public"


def rewritten(unit, tmp_path, *, change_member=None, change_segment=None, change_receipt=None):
    receipt = load(unit["privateProcessing"])
    segment = load(receipt["segments"][0]["path"])
    if change_member:
        change_member(segment["members"][0])
    if change_segment:
        change_segment(segment)
    segment_path = tmp_path / "changed-segment.json"
    save(segment_path, segment)
    receipt["segments"] = [{"path": str(segment_path), "sha256": file_pin(segment_path)["sha256"]}]
    if change_receipt:
        change_receipt(receipt)
    receipt_path = tmp_path / "changed-receipt.json"
    save(receipt_path, receipt)
    return PrivateAuthority(receipt_path)


@pytest.mark.parametrize(("change", "code"), [
    (lambda member: member["observation"].update(ordinal=9), "private_processing_member_unknown"),
    (lambda member: member.update(textSha256="0" * 64), "private_processing_member_mismatch"),
    (lambda member: member["input"].update(bodySha256="0" * 64), "private_processing_member_mismatch"),
])
def test_exact_member_and_hash_checks_are_not_scope_grants(unit, tmp_path, change, code):
    authority = rewritten(unit, tmp_path, change_member=change)
    with pytest.raises(IngestionFailure, match=code):
        exported(unit, authority=authority)


def test_wrong_phase_public_export_and_public_handoff_authorities_refuse(unit, tmp_path):
    import zoop_ai_pipeline.handoff as public_handoff
    import_path = Path(unit["export"]).parent / "import.json"
    for path in (Path(unit["privateProcessing"]), import_path):
        with pytest.raises(IngestionFailure, match="private_processing_not_public"):
            public_handoff.Authority(path)
    with pytest.raises(IngestionFailure, match="private_processing_not_public"):
        exported(unit, require_store=True)
    with pytest.raises(IngestionFailure, match="private_processing_phase_denied"):
        exported(unit, authority=PrivateAuthority(import_path))
    result = cli("ingestion", "export", {"schemaVersion": "zoop-ingestion-s2-1", **unit["observation"]},
                 "--state-dir", unit["ingestionStateDir"], "--private-processing", unit["privateProcessing"], "--require-store", expected=2)
    assert result == {"schemaVersion": "zoop-ingestion-s2-1", "error": {"code": "private_processing_not_public"}}
    result = cli("ingestion", "run", unit["importRequest"], "--state-dir", tmp_path / "wrong-phase",
                 "--private-processing", unit["privateProcessing"], "--fixture-manifest", unit["importManifest"], expected=2)
    assert result["error"]["code"] == "private_processing_phase_denied"


def test_per_set_receipts_keep_stable_grants_and_reads_survive_set_closure(unit, monkeypatch):
    original = exported(unit)
    a = bind_execution(unit, {"setId": "set-a", "fundingPolicy": "zoop-set-funding-3"}, RUNTIMES)
    b = bind_execution(unit, {"setId": "set-b", "fundingPolicy": "zoop-set-funding-3"}, RUNTIMES)
    assert a["privateProcessing"] != b["privateProcessing"]
    assert exported(a) == exported(b) == original
    authority = PrivateAuthority(Path(b["privateProcessing"]))
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_SET_ID", "set-a")
    with pytest.raises(IngestionFailure, match="private_processing_set_mismatch"):
        exported(b, authority=authority.sending("pipeline:extract", OPENAI))
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_SET_ID", "set-b")
    assert exported(b, authority=authority.sending("pipeline:extract", OPENAI)) == original
    with pytest.raises(IngestionFailure, match="source_purpose_or_recipient_denied"):
        exported(b, authority=authority.sending("pipeline:extract", TYPESAFE))
    with pytest.raises(IngestionFailure, match="private_processing_runtime_unbound"):
        authority.check_runtime({"identity": "f" * 64})
    monkeypatch.delenv("ZOOP_AI_PIPELINE_LIVE_SET_ID")
    assert exported(b) == original
    with pytest.raises(IngestionFailure, match="private_processing_set_mismatch"):
        exported(unit, authority=PrivateAuthority(Path(unit["privateProcessing"])).sending("pipeline:extract", OPENAI))


def test_unknown_source_duplicate_members_and_changed_pins_are_refused(unit, tmp_path):
    with pytest.raises(IngestionFailure, match="source_unauthorized"):
        rewritten(unit, tmp_path, change_member=lambda member: member.update(sourceId="not-registered"))
    receipt = load(unit["privateProcessing"])
    receipt["segments"].append(receipt["segments"][0])
    path = tmp_path / "duplicate.json"
    save(path, receipt)
    with pytest.raises(IngestionFailure, match="private_processing_member_ambiguous"):
        PrivateAuthority(path)
    receipt["segments"] = [{**receipt["segments"][0], "sha256": "0" * 64}]
    save(path, receipt)
    with pytest.raises(IngestionFailure, match="private_processing_segment_mismatch"):
        PrivateAuthority(path)
    authority = PrivateAuthority(Path(unit["privateProcessing"]))
    Path(unit["privateProcessing"]).write_bytes(Path(unit["privateProcessing"]).read_bytes() + b"\n")
    with pytest.raises(IngestionFailure, match="registry_changed"):
        exported(unit, authority=authority)


def test_retained_roots_record_hashes_and_public_grant_structure_refuse(unit, tmp_path):
    registry = load(unit["registry"])
    with pytest.raises(IngestionFailure, match="private_processing_not_public"):
        Authority(Path(unit["registry"])).check(unit["sourceId"], unit["scopeId"])
    from pydantic import ValidationError
    for update in ({"enabled": True}, {"rights": "known"}, {"allowedOperations": ["read"]}, {"grantId": "private-processing:collision"}):
        candidate = copy.deepcopy(registry)
        candidate["sources"][0]["grant"].update(update)
        with pytest.raises(ValidationError):
            Registry.model_validate(candidate)
    retained = load(unit["export"])["observation"]["retained"]
    with pytest.raises(IngestionFailure, match="retained_record_hash_mismatch"):
        read_record(Path(retained["stateDir"]), FileRef.model_validate({**retained["record"], "sha256": "0" * 64}))
    linked = tmp_path / "linked"
    linked.symlink_to(Path(retained["stateDir"]), target_is_directory=True)
    with pytest.raises(IngestionFailure, match="retained_record_invalid"):
        read_record(linked, FileRef.model_validate(retained["record"]))


def test_collection_index_preserves_foreign_and_private_rows_without_korea_filter(tmp_path):
    native = {"sourceId": "foreign-native", "exportPath": "not-opened"}
    private = {"sourceId": "openai-newsroom", "recordPath": "not-opened"}
    path = tmp_path / "INDEX.json"
    save(path, {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": [native], "privateItems": [private]})
    assert indexed_items(path) == [native, private]


def test_publisher_denial_and_naver_search_prohibition_survive_private_permission(unit, tmp_path, monkeypatch):
    registry = load(unit["registry"])
    registry["sources"][0]["grant"]["rights"] = "denied"
    denied = tmp_path / "denied-registry.json"
    save(denied, registry)
    with pytest.raises(IngestionFailure, match="source_rights_denied"):
        rewritten(unit, tmp_path, change_receipt=lambda receipt: receipt.update(
            registry={"path": str(denied), "sha256": file_pin(denied)["sha256"]}))
    registry = load(unit["registry"])
    registry["sources"][0]["sourceId"] = registry["sources"][0]["grant"]["sourceId"] = "naver-search"
    naver = tmp_path / "naver-registry.json"
    save(naver, registry)
    pin = {"path": str(naver), "sha256": file_pin(naver)["sha256"]}
    authority = rewritten(unit, tmp_path,
        change_member=lambda member: member.update(sourceId="naver-search"),
        change_segment=lambda segment: segment.update(registry=pin),
        change_receipt=lambda receipt: receipt.update(registry=pin, execution={"setId": "naver-test", "fundingPolicy": "zoop-set-funding-3"},
                                                      runtimeIdentities=["a" * 64]))
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_SET_ID", "naver-test")
    with pytest.raises(IngestionFailure, match="naver_search_ai_prohibited"):
        authority.check("naver-search", unit["scopeId"], ("read",), purpose="pipeline:extract", recipient=OPENAI)


def test_another_segment_cannot_lend_its_recipient_permission(unit, tmp_path, monkeypatch):
    receipt = load(unit["privateProcessing"])
    segment = load(receipt["segments"][0]["path"])
    other = copy.deepcopy(segment)
    other["authorizationId"] = "different-document-segment"
    other["members"][0]["observation"]["ordinal"] = 99
    other_path = tmp_path / "other-segment.json"
    save(other_path, other)
    authority = rewritten(unit, tmp_path,
        change_segment=lambda segment: segment.update(sends=[]),
        change_receipt=lambda receipt: receipt.update(
            segments=[*receipt["segments"], {"path": str(other_path), "sha256": file_pin(other_path)["sha256"]}],
            execution={"setId": "set-b", "fundingPolicy": "zoop-set-funding-3"}, runtimeIdentities=["a" * 64]))
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_SET_ID", "set-b")
    with pytest.raises(IngestionFailure, match="source_purpose_or_recipient_denied"):
        exported(unit, authority=authority.sending("pipeline:extract", OPENAI))


def test_import_manifest_cannot_escape_its_retained_roots_or_change_record_bytes(unit, tmp_path):
    page_path = Path(unit["importManifest"])
    manifest = load(page_path)
    registry = load(unit["registry"])
    page_ref = manifest["pages"][0]["response"]
    page = load(Path(registry["sources"][0]["inputRoot"]) / page_ref["file"])
    item = Item.model_validate(page["items"][0])
    from zoop_ai_pipeline.private_retained import retained_input
    from zoop_ai_pipeline.ingestion_contracts import Source
    source = Source.model_validate(registry["sources"][0])
    body_ref = FileRef.model_validate(manifest["documents"][item.body_ref])
    outside = item.model_copy(update={"private": item.private.model_copy(update={"state_dir": str(tmp_path / "outside")})})
    with pytest.raises(IngestionFailure, match="retained_root_unauthorized"):
        retained_input(source, source.scopes[0], outside, body_ref)
    record = Path(item.private.state_dir) / item.private.record.file
    record.write_bytes(record.read_bytes() + b" ")
    failed = cli("ingestion", "run", unit["importRequest"], "--state-dir", tmp_path / "changed-record",
                 "--private-processing", Path(unit["export"]).parent / "import.json",
                 "--fixture-manifest", unit["importManifest"])
    assert failed["state"] == "incomplete" and failed["counts"]["textReady"] == 0
    assert failed["failure"]["code"] == "retained_record_hash_mismatch"
