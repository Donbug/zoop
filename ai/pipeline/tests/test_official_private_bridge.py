"""Authored official protocol responses -> retained containers -> private native CLIs.

No external request, runtime key, or model call is made. Public-origin record wire
shapes below are synthetic controls, not evidence of acquisition from those URLs.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from overnight_inputs import load, prepare_item, save
from scripts.extraction_smoke import Kit, PROMPT
from scripts.relation_smoke import CATALOGUE
from tests.test_official_source_adapters import FIRST, LAST, policy, zipped
from tests.test_private_processing import ACTOR, QUOTE, RUNTIMES, SUPPLY, cli, fingerprint
from zoop_ai_pipeline import extraction_replay as analysis, official_source_adapters as adapters, official_source_intake as intake
from zoop_ai_pipeline.collection import Fetched
from zoop_ai_pipeline.extraction_contracts import Catalogue
from zoop_ai_pipeline.ingestion import Ingestor, Store
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, Run, byte_hash, canonical
from zoop_ai_pipeline.private_processing import PrivateAuthority

WHEN = "2026-10-28T04:00:00+00:00"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("official bridge controls must not open a network socket")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def response(task, raw, media):
    return Fetched(task.url, task.url, 200, media, media, raw, {}, [], [], 0, WHEN)


def official_record(root, source="opendart", *, title="Authored official filing", synthetic=False):
    """Use the real official parser and record writer, with authored byte responses only."""
    origin = "http://127.0.0.1:12345" if synthetic else None
    config = intake.OfficialConfig.model_validate({
        "schemaVersion": "zoop-official-source-config-1", "planId": "official-bridge-control", "stateDir": str(root),
        "sourceId": source, "fromDay": FIRST, "throughDay": LAST, "operatorApprovalRef": "synthetic-retention-control-only",
        "policy": policy(syntheticLoopback=synthetic, minIntervalSeconds=0.1).wire(), "syntheticBaseUrl": origin})
    listing_task = adapters.plan(source, FIRST, LAST, synthetic_origin=origin).tasks[-1]
    if source == "opendart":
        listing_raw = canonical({"status": "000", "page_no": 1, "total_page": 1, "list": [{
            "corp_code": "00126380", "stock_code": "005930", "rcept_no": "20261028000001", "rcept_dt": "20261028", "report_nm": title}]}).encode()
        listing_media = "application/json"
        raw = zipped([("main.xml", ("<DOCUMENT><P>" + QUOTE + "</P><P>" + SUPPLY + "</P><P>😀 e\u0301</P></DOCUMENT>").encode()),
                      ("supplement.xml", b"<document><p>Second member.</p></document>"), ("image.png", b"unparsed retained attachment")])
        media = "application/zip"
    else:
        article_url = (origin or "https://www.fsc.go.kr") + "/no010101/123"
        listing_raw = (f"<rss><channel><item><title>{title}</title><link>{article_url}</link>"
                       "<pubDate>Wed, 28 Oct 2026 09:00:00 +0900</pubDate></item></channel></rss>").encode()
        listing_media = "application/xml"
        raw = ('<html><body><div class="board-view-wrap"><div class="cont"><p>' + QUOTE + '</p><p>' + SUPPLY +
               '</p></div></div></body></html>').encode()
        media = "text/html"
    listing = adapters.parse_response(listing_task, response(listing_task, listing_raw, listing_media), synthetic_origin=origin)
    task = listing.candidates[0].body_task
    body = adapters.parse_response(task, response(task, raw, media), synthetic_origin=origin)
    state = intake.State(config, "run")
    try:
        intake._publish(state.fd, "response-" + listing_task.key + ".raw", listing_raw, immutable=True)
        intake._publish(state.fd, "response-" + listing_task.key + ".json", canonical({
            "task": asdict(listing_task), "response": asdict(listing.response)}).encode(), immutable=True)
        state.data["responses"][listing.response.raw_sha256] = {"stateDir": str(root), "taskKey": listing_task.key}
        intake._retain(config, state, task, body)
        state.save()
        index = next(iter(state.data["records"].values()))
    finally:
        state.close()
    return index


def cli_export(unit, state=None):
    return cli("ingestion", "export", {"schemaVersion": "zoop-ingestion-s2-1", **unit["observation"]},
               "--state-dir", state or unit["ingestionStateDir"], "--private-processing", unit["privateProcessing"])


@pytest.mark.parametrize("source", ["opendart", "fsc-press"])
def test_original_container_and_derived_body_remain_separate_through_native_cli(tmp_path, monkeypatch, source):
    old = tmp_path / "official-retained"
    index = official_record(old, source)
    record = load(index["recordPath"])
    before = fingerprint(old)
    original_open = os.open

    def forbid_old_state(path, *args, **kwargs):
        if str(path) in {"STATE.json", ".lock", "QUEUE.sqlite3", "QUEUE.sqlite3-wal"}:
            raise AssertionError("bridge must not open the official runner state")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as guard:
        guard.setattr(os, "open", forbid_old_state)
        unit = prepare_item(index, tmp_path / "owned", "official-bridge", RUNTIMES, actor=ACTOR)
    state = tmp_path / "cli-ingestion"
    imported = cli("ingestion", "run", unit["importRequest"], "--state-dir", state,
                   "--private-processing", Path(unit["export"]).parent / "import.json",
                   "--fixture-manifest", unit["importManifest"])
    assert imported["state"] == "complete" and imported["counts"]["textReady"] == 1
    assert imported["provenance"] == "retained_private"
    out = cli_export(unit, state)
    body = (old / record["bodyArtifact"]["file"]).read_bytes()
    container = (old / (record["privateId"] + ".raw")).read_bytes()
    assert out["document"]["text"].encode() == body
    assert out["locatorMetadata"]["rawHash"] == byte_hash(body) == record["bodyArtifact"]["sha256"]
    assert byte_hash(container) == record["rawSha256"] != byte_hash(body)
    assert record["representation"] == ("application/zip" if source == "opendart" else "text/html")
    assert out["observation"]["mediaType"] == "text/markdown"
    assert out["observation"]["retained"]["recordSchema"] == "zoop-official-source-record-1"
    assert out["observation"]["retained"]["canonicalUrl"] is None
    assert "collection" not in out["observation"]
    assert record["rights"] == "unconfirmed" and record["publicUse"] is False and record["modelSend"] is False
    if source == "opendart":
        assert out["observation"]["publishedAt"] is None
        assert out["observation"]["retained"]["published"]["date"] == "2026-10-28"
        assert record["publication"]["raw"] == "20261028"
        assert {s["memberRef"] for s in record["prepared"]["sources"]} == {"main.xml", "supplement.xml"}
    else:
        assert out["observation"]["publishedAt"] == record["publication"]["value"]
        assert record["publication"]["raw"] == "Wed, 28 Oct 2026 09:00:00 +0900"
    text = out["document"]["text"]
    start = text.index(QUOTE)
    locator = out["document"]["rawLocators"][0]
    resolved = cli("ingestion", "inspect", {"schemaVersion": "zoop-ingestion-s2-1",
        "roundId": unit["observation"]["roundId"], "sourceId": unit["sourceId"],
        "documentId": unit["observation"]["documentId"], "documentVersion": unit["observation"]["documentVersion"],
        "locatorId": locator["locatorId"], "start": start, "end": start + len(QUOTE)},
        "--state-dir", state, "--private-processing", unit["privateProcessing"])
    spans = resolved["resolvedLocator"]["segments"]
    assert "".join(span["text"] for span in spans) == QUOTE
    assert all(span["representation"] == "official-derived-utf8-text-1" for span in spans)
    assert all("xpath" not in span and "domPath" not in span and "memberRef" not in span for span in spans)
    assert any("container/member/XPath" in value for value in out["locatorMetadata"]["limitations"])
    assert fingerprint(old) == before
    public = cli("ingestion", "export", {"schemaVersion": "zoop-ingestion-s2-1", **unit["observation"]},
                 "--state-dir", state, "--sources", unit["registry"], "--require-store", expected=2)
    assert public["error"]["code"] == "private_processing_not_public"


def test_official_body_is_an_actual_analysis_input_not_a_fixture_adapter(tmp_path):
    index = official_record(tmp_path / "old")
    unit = prepare_item(index, tmp_path / "owned", "official-bridge", RUNTIMES, actor=ACTOR)
    out = cli_export(unit)
    article = analysis.article(out, True)
    mention = Kit.mention(None, article, "official-mention", [Kit.evidence(article, QUOTE)])
    replay = tmp_path / "authored-reply.json"
    save(replay, {"format": "zoop-analysis-replay-1", "synthetic": True, "recordingKind": "authored-test",
        "promptVersion": PROMPT, "analysisVersion": "official-bridge-control-1", "records": [{"stage": "extract",
        "requestDigest": analysis.request_digest("extract", analysis.extract_input(article, PROMPT, Catalogue.model_validate(CATALOGUE)),
                                                 "official-bridge-control-1"), "response": {"mentions": [mention]}}]})
    result = cli("extraction", "run", {"schemaVersion": "zoop-extraction-s2-2", "jobId": "official-s2",
        "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
        "promptVersion": PROMPT, "incoming": unit["observation"], "catalogue": CATALOGUE,
        "snapshot": {"revision": "empty", "events": []}, "topic": None},
        "--state-dir", tmp_path / "s2", "--ingestion-state-dir", unit["ingestionStateDir"],
        "--private-processing", unit["privateProcessing"], "--replay", replay)
    assert result["state"] == "ready" and result["delivery"]["status"] == "current"
    assert result["counts"]["eventCandidates"]["candidate"] == 1
    assert result["usage"]["providerCalls"] == 0


@pytest.mark.parametrize("artifact", ["container", "body", "envelope", "member-hash"])
def test_official_container_member_and_body_hash_chain_is_not_optional(tmp_path, artifact):
    index = official_record(tmp_path / "old")
    record = load(index["recordPath"])
    root = Path(index["stateDir"])
    if artifact == "container":
        path = root / (record["privateId"] + ".raw")
        path.write_bytes(path.read_bytes() + b"changed")
    elif artifact == "body":
        path = root / record["bodyArtifact"]["file"]
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        path = root / record["extractionArtifact"]["file"]
        envelope = load(path)
        envelope["members"][0]["sha256"] = "0" * 64
        save(path, envelope)
        if artifact == "member-hash":
            record["extractionArtifact"]["sha256"] = byte_hash(path.read_bytes())
            save(index["recordPath"], record)
            index["recordSha256"] = byte_hash(Path(index["recordPath"]).read_bytes())
    with pytest.raises(IngestionFailure):
        prepare_item(index, tmp_path / "owned", "official-bridge", RUNTIMES, actor=ACTOR)


def test_official_unknown_member_is_rejected_before_any_container_or_derived_body_open(tmp_path, monkeypatch):
    index = official_record(tmp_path / "old")
    unit = prepare_item(index, tmp_path / "owned", "official-bridge", RUNTIMES, actor=ACTOR)
    document = load(Path(unit["export"]).parent / "import.json")
    document["members"][0]["input"]["privateId"] = "another-official-member"
    authority_path = tmp_path / "unlisted-import.json"
    save(authority_path, document)
    original_open, opened = os.open, []

    def observe(path, *args, **kwargs):
        if Path(path).name.startswith(index["privateId"]) and not Path(path).name.endswith(".page.json"):
            opened.append(str(path))
        return original_open(path, *args, **kwargs)

    store = Store(tmp_path / "unlisted-ingestion")
    try:
        with monkeypatch.context() as tracing:
            tracing.setattr(os, "open", observe)
            result = Ingestor(store, PrivateAuthority(authority_path)).run(Run.model_validate(unit["importRequest"]), Path(unit["importManifest"]))
        assert result["state"] == "incomplete" and result["failure"]["code"] == "private_processing_member_unknown"
        assert result["counts"]["newRawVersions"] == 0 and opened == []
    finally:
        store.close()


@pytest.mark.parametrize("change", ["planId", "privateId", "synthetic-origin", "body-symlink"])
def test_official_plan_identity_and_retained_namespace_stay_strict(tmp_path, change):
    index = official_record(tmp_path / "old", synthetic=change == "synthetic-origin")
    if change in {"planId", "privateId"}:
        index[change] = "wrong-index-identity"
    if change == "body-symlink":
        record = load(index["recordPath"])
        body = Path(index["stateDir"]) / record["bodyArtifact"]["file"]
        body.rename(tmp_path / "outside.md")
        body.symlink_to(tmp_path / "outside.md")
    with pytest.raises(IngestionFailure):
        prepare_item(index, tmp_path / "owned", "official-bridge", RUNTIMES, actor=ACTOR)


def test_missing_official_title_does_not_invent_one(tmp_path):
    index = official_record(tmp_path / "old", title=None)
    unit = prepare_item(index, tmp_path / "owned", "official-bridge", RUNTIMES, actor=ACTOR)
    assert load(index["recordPath"])["title"] is None
    assert cli_export(unit)["observation"]["title"] == ""
