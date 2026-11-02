"""Offline durable-state and exact-source behavior, not dependency wiring tests."""
from __future__ import annotations

import copy
import io
import json
import os
import sqlite3
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.ingestion_smoke import HTML, OfflineFixture, authored_pdf, exact_check, json_bytes, sha
from zoop_ai_pipeline.ingestion import Ingestor, Store
from zoop_ai_pipeline.ingestion_contracts import Authority, Export, IngestionFailure, Inspect, Item, Run, canonical
from zoop_ai_pipeline import ingestion_parsers as parsers


@pytest.fixture
def kit(tmp_path):
    return OfflineFixture(tmp_path / "owned")


def execute(kit, manifest, rid="round-1", revision=0, *, state="state", window=None):
    store = Store(kit.root / state)
    try:
        return Ingestor(store, Authority(kit.registry_path)).run(Run.model_validate(kit.request(manifest, rid, revision, window)), manifest)
    finally:
        store.close()


def inspect(kit, ref, rid="round-1", **kwargs):
    store = Store(kit.root / "state")
    try:
        request = Inspect.model_validate(kit.selector(rid, documentId=ref["documentId"], documentVersion=ref["documentVersion"], **kwargs))
        return Ingestor(store, Authority(kit.registry_path)).inspect(request)
    finally:
        store.close()


def resume(kit, rid="round-1"):
    store = Store(kit.root / "state")
    try:
        return Ingestor(store, Authority(kit.registry_path)).resume(rid, "synthetic-source")
    finally:
        store.close()


def _unknown_parser_version(monkeypatch, library, failure):
    lookup = parsers.version

    def damaged_metadata(name):
        if name != library:
            return lookup(name)
        if failure == "missing":
            raise PackageNotFoundError(name)
        return None if failure == "null" else ""

    monkeypatch.setattr(parsers, "version", damaged_metadata)


@pytest.mark.parametrize("library", ["lxml", "pypdf"])
@pytest.mark.parametrize("failure", ["null", "empty", "missing"])
def test_unknown_parser_identity_refuses_cli_run_before_preparation(kit, monkeypatch, capsys, library, failure):
    from zoop_ai_pipeline.ingestion_cli import main

    manifest = kit.manifest("unknown-parser", [[kit.item()]])
    _unknown_parser_version(monkeypatch, library, failure)
    monkeypatch.setattr(sys, "argv", ["zoop-ingestion", "run", "--state-dir", str(kit.root / "state"),
                                    "--sources", str(kit.registry_path), "--fixture-manifest", str(manifest)])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json_bytes(kit.request(manifest)))))
    assert main() == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"schemaVersion": "zoop-ingestion-s2-1", "error": {"code": "input_or_configuration_invalid"}}
    assert captured.err == ""
    store = Store(kit.root / "state", existing=True)
    try:
        for table in ("rounds", "raw_versions", "preparations", "versions", "candidates"):
            assert store.one(f"SELECT COUNT(*) n FROM {table}")["n"] == 0
        request = Export.model_validate(kit.selector(page=0, ordinal=0, documentId="not-created",
                                                    rawVersion="not-created", documentVersion="not-created"))
        with pytest.raises(IngestionFailure, match="^round_not_found$"):
            Ingestor(store, Authority(kit.registry_path)).export(request)
    finally:
        store.close()


@pytest.mark.parametrize("library", ["lxml", "pypdf"])
@pytest.mark.parametrize("failure", ["null", "empty", "missing"])
def test_unknown_parser_identity_stops_incomplete_resume_without_durable_hold(kit, monkeypatch, library, failure):
    manifest = kit.manifest("recover-parser", [[kit.item()]])
    payload = json.loads(manifest.read_bytes())
    body = kit.inputs / payload["documents"]["html"]["file"]
    body.unlink()
    first = execute(kit, manifest)
    assert first["state"] == "incomplete" and first["counts"]["textReady"] == 0
    body.write_bytes(HTML)
    with monkeypatch.context() as damaged:
        _unknown_parser_version(damaged, library, failure)
        stopped = resume(kit)
    assert stopped["state"] == "incomplete"
    assert stopped["failure"] == {"code": "input_or_configuration_invalid"}
    assert stopped["checkpoint"]["revision"] == 0
    assert stopped["counts"]["textReady"] == stopped["counts"]["held"] == 0
    ref = stopped["documentRefs"][0]
    assert ref["rawVersion"] is not None and ref["documentVersion"] is None
    store = Store(kit.root / "state", existing=True)
    try:
        for table in ("preparations", "versions"):
            assert store.one(f"SELECT COUNT(*) n FROM {table}")["n"] == 0
        request = Export.model_validate(kit.selector(page=0, ordinal=0, documentId=ref["documentId"],
                                                    rawVersion=ref["rawVersion"], documentVersion="not-prepared"))
        with pytest.raises(IngestionFailure, match="^observation_not_found$"):
            Ingestor(store, Authority(kit.registry_path)).export(request)
    finally:
        store.close()
    recovered = resume(kit)
    assert recovered["state"] == "complete" and recovered["counts"]["textReady"] == 1
    assert recovered["counts"]["newRawVersions"] == recovered["counts"]["newTextVersions"] == 1


@pytest.mark.parametrize("library", ["lxml", "pypdf"])
@pytest.mark.parametrize("failure", ["null", "empty", "missing"])
def test_healthy_parser_identity_and_history_remain_exact_when_runtime_metadata_breaks(kit, monkeypatch, library, failure):
    from zoop_ai_pipeline.corpus_review import NativeDocument

    assert parsers.profile() == {"parser": "zoop-native-parsers-1", "lxml": "6.1.3", "pypdf": "6.19.0",
        "mappingVersion": "unicode-copy-segments-1", "htmlDecoding": "utf-8-strict", "htmlScope": "native-article-scope-1",
        "pdfExtraction": "page-text-bounded-1", "articleXPath": None}
    result = execute(kit, kit.manifest("healthy-parser", [[kit.item()]]))
    ref = result["documentRefs"][0]
    assert ref["documentVersion"] == "4b685906fc3a1402c605da54a7ab7fc9e2e49f7af6021dbc06eab3287a551fe9"
    before = inspect(kit, ref)
    store = Store(kit.root / "state", existing=True)
    try:
        runner = Ingestor(store, Authority(kit.registry_path))
        selector = Export.model_validate(kit.selector(**{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}))
        exported = runner.export(selector)
        NativeDocument.model_validate(exported)
        _unknown_parser_version(monkeypatch, library, failure)
        assert runner.export(selector) == exported
        inspected = runner.inspect(Inspect.model_validate(kit.selector(documentId=ref["documentId"], documentVersion=ref["documentVersion"])))
        assert inspected == before
        assert runner.resume("round-1", "synthetic-source") == result
    finally:
        store.close()


def test_exact_replay_new_body_and_equal_text_raw_lineage(kit):
    m = kit.manifest("a", [[kit.item()]])
    first = execute(kit, m)
    assert first["state"] == "complete" and execute(kit, m) == first
    replay = execute(kit, m, "replay", 1)
    assert replay["counts"]["reusedVersions"] == 1 and replay["counts"]["newRawVersions"] == 0
    ref = first["documentRefs"][0]
    before = inspect(kit, ref)
    # Raw spelling changes while decoded HTML text is literally equal.
    b = kit.manifest("b", [[kit.item()]], bodies={"html": HTML.replace(b"&amp;", b"&#38;")})
    changed = execute(kit, b, "changed", 2)
    newer = changed["documentRefs"][0]
    assert newer["documentId"] == ref["documentId"] and newer["documentVersion"] != ref["documentVersion"]
    after = inspect(kit, newer, "changed")
    assert after["document"]["text"] == before["document"]["text"]
    assert after["document"]["sourceHash"] == before["document"]["sourceHash"]
    assert after["locatorMetadata"]["rawHash"] != before["locatorMetadata"]["rawHash"]
    retained = inspect(kit, ref)
    assert retained["document"] == before["document"] and retained["locatorMetadata"] == before["locatorMetadata"]
    assert retained["checkpoint"]["revision"] == 3 and retained["checkpoint"]["roundRevision"] == 1
    revisit = execute(kit, m, "revisit", 3)
    assert revisit["documentRefs"][0]["documentVersion"] == ref["documentVersion"]


def test_supplier_promotion_conflict_and_uncertain_url_identity(kit):
    first = execute(kit, kit.manifest("url", [[kit.item(supplier=None)]]))
    original = first["documentRefs"][0]
    promoted = execute(kit, kit.manifest("id", [[kit.item()]]), "promoted", 1)
    assert promoted["documentRefs"][0]["documentId"] == original["documentId"]
    second = execute(kit, kit.manifest("conflict", [[kit.item(supplier="other-supplier")]]), "conflict", 2)
    assert second["documentRefs"][0]["documentId"] != original["documentId"]
    assert second["documentRefs"][0]["ambiguity"] == "source_identity_ambiguous"
    uncertain = execute(kit, kit.manifest("uncertain", [[kit.item(supplier=None)]]), "uncertain", 3)
    assert uncertain["counts"]["held"] == 1 and uncertain["counts"]["textReady"] == 0
    assert uncertain["documentRefs"][0]["hold"] == "source_identity_ambiguous"
    assert uncertain["documentRefs"][0]["documentId"] not in {original["documentId"], second["documentRefs"][0]["documentId"]}


def test_distinct_same_event_documents_and_cross_source_do_not_merge(kit):
    m = kit.manifest("same-event", [[kit.item(), kit.item("c2", "supplier-2")]])
    result = execute(kit, m)
    assert len({r["documentId"] for r in result["documentRefs"]}) == 2
    source = copy.deepcopy(kit.registry["sources"][0])
    source["sourceId"] = source["grant"]["sourceId"] = "other-source"
    kit.registry["sources"].append(source)
    kit.save_registry()
    payload = json.loads(m.read_bytes())
    payload["sourceId"] = "other-source"
    m.write_bytes(json_bytes(payload))
    request = kit.request(m, "other")
    request["sourceId"] = "other-source"
    store = Store(kit.root / "state")
    try:
        other = Ingestor(store, Authority(kit.registry_path)).run(Run.model_validate(request), m)
        assert {r["documentId"] for r in other["documentRefs"]}.isdisjoint({r["documentId"] for r in result["documentRefs"]})
    finally:
        store.close()


def test_url_normalization_is_minimal_without_query_or_source_merging(kit):
    m = kit.manifest("urls", [[kit.item("c1", None, "https://EXAMPLE.invalid:443/a?b=2&a=1#one"), kit.item("c2", None, "https://example.invalid/a?b=2&a=1#two"), kit.item("c3", None, "https://example.invalid/a?a=1&b=2")]])
    result = execute(kit, m)
    refs = result["documentRefs"]
    assert refs[0]["documentId"] == refs[1]["documentId"] != refs[2]["documentId"]
    assert result["counts"]["newTextVersions"] == 2 and result["counts"]["reusedVersions"] == 1


@pytest.mark.parametrize("status,items,terminal,state,completion,checkpoint", [
    ("ok", [], True, "complete", "source-zero", 1),
    ("failed", [], True, "incomplete", None, 0),
    ("partial", "one", True, "incomplete", None, 0),
    ("ok", "one", False, "incomplete", None, 1),
])
def test_zero_failure_partial_and_page_limit_are_distinct(kit, status, items, terminal, state, completion, checkpoint):
    m = kit.manifest("response", [[kit.item()] if items == "one" else items], statuses=[status], terminal=terminal)
    result = execute(kit, m)
    assert result["state"] == state and result["completion"] == completion and result["checkpoint"]["revision"] == checkpoint
    if status == "partial":
        assert result["counts"]["textReady"] == 1 and result["failure"]["code"] == "discovery_page_partial"
    if not terminal:
        assert result["checkpoint"]["continuation"] == "cursor-1" and result["checkpoint"]["through"] is None


def test_contiguous_checkpoint_stops_at_missing_body_and_resumes_durably(kit):
    later_html = HTML.replace("뒤".encode(), "다른 뒤".encode())
    m = kit.manifest("pages", [[kit.item()], [kit.item("second", "second", ref="later")]], bodies={"html": HTML, "later": later_html})
    payload = json.loads(m.read_bytes())
    missing = kit.inputs / payload["documents"]["later"]["file"]
    missing.unlink()
    first = execute(kit, m)
    assert first["state"] == "incomplete" and first["checkpoint"]["revision"] == 1 and first["checkpoint"]["continuation"] == "cursor-1"
    assert first["pages"][0]["complete"] and not first["pages"][1]["complete"]
    assert first["counts"]["textReady"] == 1
    # Saved discovery and first raw/version no longer need their authored inputs.
    for p in payload["pages"]:
        (kit.inputs / p["response"]["file"]).unlink()
    (kit.inputs / payload["documents"]["html"]["file"]).unlink()
    m.unlink()
    missing.write_bytes(later_html)
    recovered = resume(kit)
    assert recovered["state"] == "complete" and recovered["checkpoint"]["revision"] == 2 and recovered["counts"]["newTextVersions"] == 2
    assert recovered["documentRefs"][1]["failure"] is None


def test_item_error_preserves_good_document_but_never_advances_page(kit):
    bad = {**kit.item("bad"), "extra": "untrusted"}
    m = kit.manifest("invalid", [[kit.item(), bad]])
    result = execute(kit, m)
    assert result["counts"]["textReady"] == 1 and result["checkpoint"]["revision"] == 0
    assert result["documentRefs"][1]["error"] == "discovery_item_invalid"
    assert resume(kit)["checkpoint"]["revision"] == 0


def test_successful_query_boundary_requires_terminal_declared_coverage(kit):
    window = {"from": "2026-10-08T00:00:00+00:00", "through": "2026-10-08T01:00:00+00:00"}
    unknown = execute(kit, kit.manifest("unknown", [[]]), window=window)
    assert unknown["state"] == "incomplete" and unknown["checkpoint"]["through"] is None
    complete = execute(kit, kit.manifest("known", [[]], coverage=window["through"]), "known", 1, window=window)
    assert complete["state"] == "complete" and complete["checkpoint"]["through"] == window["through"]
    historical = {"from": "2026-10-07T00:00:00+00:00", "through": "2026-10-07T01:00:00+00:00"}
    older = execute(kit, kit.manifest("historical", [[]], coverage=historical["through"]), "historical", 2, window=historical)
    assert older["checkpoint"]["through"] == window["through"]
    assert resume(kit, "known")["checkpoint"]["revision"] == 3


@pytest.mark.parametrize("table", ["blobs", "versions"])
def test_save_failure_recovery_never_puts_checkpoint_ahead_of_content(kit, table):
    m = kit.manifest("save", [[kit.item()]])
    store = Store(kit.root / "state")
    try:
        # Register normally, then fault a real SQLite commit boundary. The BLOB
        # condition targets document bytes rather than the saved discovery response.
        condition = " WHEN length(NEW.data)>10 AND substr(NEW.data,1,1)=x'3c'" if table == "blobs" else ""
        store.db.execute(f"CREATE TRIGGER fail_save BEFORE INSERT ON {table}{condition} BEGIN SELECT RAISE(ABORT,'synthetic-save-failure'); END")
        result = Ingestor(store, Authority(kit.registry_path)).run(Run.model_validate(kit.request(m)), m)
        assert result["state"] == "incomplete" and result["checkpoint"]["revision"] == 0
        if table == "versions":
            assert result["counts"]["newRawVersions"] == 1 and result["counts"]["textReady"] == 0
            for r in json.loads(m.read_bytes())["documents"].values():
                (kit.inputs / r["file"]).unlink()
        store.db.execute("DROP TRIGGER fail_save")
    finally:
        store.close()
    recovered = resume(kit)
    assert recovered["state"] == "complete" and recovered["counts"]["newRawVersions"] == 1 and recovered["counts"]["newTextVersions"] == 1


def test_registry_changes_inside_commit_roll_back_new_content(kit, monkeypatch):
    m = kit.manifest("rights", [[kit.item()]])
    original = Store.blob

    def revoke(store, raw):
        result = original(store, raw)
        if raw == HTML:
            kit.registry["sources"][0]["grant"]["enabled"] = False
            kit.save_registry()
        return result

    monkeypatch.setattr(Store, "blob", revoke)
    result = execute(kit, m)
    assert result["failure"]["code"] == "registry_changed" and result["checkpoint"]["revision"] == 0 and result["counts"]["newRawVersions"] == 0
    store = Store(kit.root / "state")
    try:
        assert store.one("SELECT COUNT(*) n FROM blobs WHERE hash=?", (sha(HTML),))["n"] == 0
    finally:
        store.close()
    denied = resume(kit)
    assert denied["failure"]["code"] == "source_unauthorized"


@pytest.mark.parametrize("change", ["omission", "disabled", "unknown", "expired", "evidence", "scope"])
def test_current_complete_registry_blocks_content_after_prior_authority(kit, change):
    result = execute(kit, kit.manifest("allowed", [[kit.item()]]))
    ref = result["documentRefs"][0]
    if change == "omission":
        kit.registry["sources"] = []
    elif change == "scope":
        kit.registry["sources"][0]["scopes"][0]["scopeId"] = "another-scope"
    else:
        grant = kit.registry["sources"][0]["grant"]
        key, value = {"disabled": ("enabled", False), "unknown": ("rights", "unknown"), "expired": ("expiresAt", "2000-01-01T00:00:00+00:00"), "evidence": ("evidence", [])}[change]
        grant[key] = value
    kit.save_registry()
    with pytest.raises(IngestionFailure, match="source_unauthorized"):
        inspect(kit, ref)


def test_read_store_is_not_model_send_or_quote_display_authority(kit):
    kit.registry["sources"][0]["grant"]["allowedOperations"] = ["read", "store"]
    kit.save_registry()
    result = execute(kit, kit.manifest("stored", [[kit.item()]]))
    ref = result["documentRefs"][0]
    doc = inspect(kit, ref)["document"]
    assert result["state"] == "complete"
    loc = doc["rawLocators"][0]
    with pytest.raises(IngestionFailure, match="source_unauthorized"):
        inspect(kit, ref, locatorId=loc["locatorId"], start=loc["start"], end=loc["end"])


def test_exact_entity_inline_tail_repeated_korean_emoji_and_separators(kit):
    result = execute(kit, kit.manifest("coordinates", [[kit.item()]]))
    ref = result["documentRefs"][0]
    doc = inspect(kit, ref)["document"]
    assert doc["text"] == "반복 & 반복😀 꼬리\n뒤\n반복😀 둘째"
    first = doc["rawLocators"][0]
    compound = inspect(kit, ref, locatorId=first["locatorId"], start=3, end=11)["resolvedLocator"]["segments"]
    assert "".join(s["text"] for s in compound) == "& 반복😀 꼬리"
    assert [s["slot"] for s in compound] == ["text", "text", "tail"]
    assert compound[1]["sourceStart"] == 0 and compound[1]["sourceEnd"] == 3
    tail = doc["rawLocators"][1]
    resolved = inspect(kit, ref, locatorId=tail["locatorId"], start=tail["start"], end=tail["end"])["resolvedLocator"]["segments"]
    assert resolved[0]["slot"] == "tail" and resolved[0]["domPath"] == "/html/body/article/p[1]/span" and resolved[0]["text"] == "뒤"
    exact_check(doc, 3, 11)
    exact_check(doc, 0, len(doc["text"]), False)
    with pytest.raises(IngestionFailure, match="locator_interval_unmapped"):
        inspect(kit, ref, locatorId=first["locatorId"], start=0, end=len(doc["text"]))


@pytest.mark.parametrize("body,media,hold", [
    (b"<html><body>no article</body></html>", "text/html", "article_scope_ambiguous_or_missing"),
    (b"<article>a</article><article>b</article>", "text/html", "article_scope_ambiguous_or_missing"),
    (b"<article>\xff</article>", "text/html", "html_extraction_failed"),
    (b"<article><aside>removed</aside></article>", "text/html", "no_usable_body"),
    (b"not-pdf", "application/pdf", "pdf_extraction_failed"),
])
def test_reasoned_parse_holds_preserve_raw_without_projection_or_reparse(kit, monkeypatch, body, media, hold):
    result = execute(kit, kit.manifest("hold", [[kit.item(media=media)]], bodies={"html": body}))
    assert result["state"] == "complete" and result["counts"]["held"] == 1 and result["documentRefs"][0]["hold"] == hold
    monkeypatch.setattr(parsers, "prepare", lambda *a: pytest.fail("durable hold reparsed"))
    assert resume(kit) == result
    with pytest.raises(IngestionFailure, match="document_version_not_in_round"):
        inspect(kit, {"documentId": result["documentRefs"][0]["documentId"], "documentVersion": "not-prepared"})


def test_pdf_frozen_repeated_page_positions_empty_pages_and_encryption(kit):
    raw = authored_pdf("repeat", "repeat", "")
    result = execute(kit, kit.manifest("pdf", [[kit.item(media="application/pdf")]], bodies={"html": raw}))
    ref = result["documentRefs"][0]
    output = inspect(kit, ref)
    doc = output["document"]
    assert doc["text"] == "repeat\nrepeat"
    assert output["locatorMetadata"]["rawHash"] == sha(raw)
    assert output["locatorMetadata"]["pageCount"] == 3 and output["locatorMetadata"]["emptyPageCount"] == 1
    loc = doc["rawLocators"][1]
    mapped = inspect(kit, ref, locatorId=loc["locatorId"], start=loc["start"] + 1, end=loc["end"])["resolvedLocator"]["segments"][0]
    assert mapped["pageNumber"] == 2 and mapped["sourceStart"] == 1 and mapped["sourceEnd"] == 6 and mapped["text"] == "epeat"
    exact_check(doc, loc["start"], loc["end"])
    exact_check(doc, 0, len(doc["text"]), False)
    encrypted = execute(kit, kit.manifest("encrypted", [[kit.item(media="application/pdf")]], bodies={"html": authored_pdf("secret", encrypted=True)}), "encrypted", 1)
    assert encrypted["documentRefs"][0]["hold"] == "encrypted_pdf"
    blank = execute(kit, kit.manifest("blank", [[kit.item(media="application/pdf")]], bodies={"html": authored_pdf("", "")}), "blank", 2)
    held = blank["documentRefs"][0]
    assert held["hold"] == "no_usable_body" and held["documentVersion"] is None
    assert held["preparationMetadata"]["pageCount"] == held["preparationMetadata"]["emptyPageCount"] == 2
    store = Store(kit.root / "state")
    try:
        saved = json.loads(store.one("SELECT content FROM preparations WHERE raw_version=?", (held["rawVersion"],))["content"])
        assert [s["text"] for s in saved["sources"]] == ["", ""]
        assert [s["pageNumber"] for s in saved["sources"]] == [1, 2]
    finally:
        store.close()
    assert resume(kit, "blank")["documentRefs"][0]["preparationMetadata"] == held["preparationMetadata"]


@pytest.mark.parametrize("attack", ["traversal", "absolute", "remote", "symlink", "hash", "url"])
def test_untrusted_fixture_path_hash_url_never_falls_back_to_network(kit, attack):
    item = kit.item()
    if attack == "url":
        item["url"] = "http://other.invalid/%2e%2e/private"
    m = kit.manifest("unsafe", [[item]])
    payload = json.loads(m.read_bytes())
    ref = payload["documents"]["html"]
    if attack in {"traversal", "absolute", "remote"}:
        ref["file"] = {"traversal": "../sources.json", "absolute": str(kit.registry_path), "remote": "https://example.invalid/body"}[attack]
        m.write_bytes(json_bytes(payload))
        with pytest.raises(ValueError):
            execute(kit, m)
    else:
        if attack == "symlink":
            path = kit.inputs / ref["file"]
            path.unlink()
            path.symlink_to(kit.registry_path)
        if attack == "hash":
            (kit.inputs / ref["file"]).write_bytes(b"changed")
        result = execute(kit, m)
        assert result["state"] == "incomplete" and result["checkpoint"]["revision"] == 0 and result["counts"]["newRawVersions"] == 0


def test_exclusive_writer_immutable_records_and_state_isolation(kit):
    m = kit.manifest("private", [[kit.item()]])
    result = execute(kit, m)
    store = Store(kit.root / "state")
    try:
        with pytest.raises(IngestionFailure, match="ingestion_busy"):
            Store(kit.root / "state")
        for table in ("blobs", "versions", "raw_versions", "preparations"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store.db.execute(f"DELETE FROM {table}")
        assert result["state"] == "complete"
    finally:
        store.close()
    assert (kit.root / "state").stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in (kit.root / "state").iterdir())
    for filename in ("worker.sqlite3", "state.sqlite3"):
        root = kit.root / filename.replace(".", "-")
        root.mkdir()
        (root / filename).write_bytes(b"sentinel")
        with pytest.raises(IngestionFailure, match="state_namespace_conflict"):
            Store(root)
        assert (root / filename).read_bytes() == b"sentinel"


def test_metadata_is_bounded_and_exact_content_is_round_scoped(kit):
    m = kit.manifest("many", [[kit.item(str(i), str(i), f"https://example.invalid/{i}") for i in range(5)]])
    result = execute(kit, m)
    store = Store(kit.root / "state")
    try:
        runner = Ingestor(store, Authority(kit.registry_path))
        page = runner.inspect(Inspect.model_validate(kit.selector(limit=2)))
        assert len(page["documentRefs"]) == 2 and page["pagination"]["nextOffset"] == 2 and "document" not in page
        next_page = runner.inspect(Inspect.model_validate(kit.selector(limit=2, offset=2)))
        assert set(r["documentId"] for r in page["documentRefs"]).isdisjoint(r["documentId"] for r in next_page["documentRefs"])
    finally:
        store.close()
    execute(kit, kit.manifest("zero", [[]]), "zero", 1)
    with pytest.raises(IngestionFailure, match="document_version_not_in_round"):
        inspect(kit, result["documentRefs"][0], "zero")


def test_final_checkpoint_cas_rejects_change_after_raw_and_parse(kit, monkeypatch):
    m = kit.manifest("cas", [[kit.item()]])
    original = parsers.prepare
    store = Store(kit.root / "state")
    try:
        def parse_and_advance(*args):
            output = original(*args)
            store.db.execute("UPDATE scopes SET revision=9,cursor='newer-cursor'")
            return output

        monkeypatch.setattr(parsers, "prepare", parse_and_advance)
        result = Ingestor(store, Authority(kit.registry_path)).run(Run.model_validate(kit.request(m)), m)
        assert result["failure"]["code"] == "checkpoint_stale"
        assert result["checkpoint"]["revision"] == 9 and result["checkpoint"]["continuation"] == "newer-cursor"
        assert result["counts"]["textReady"] == 1 and not result["pages"][0]["complete"]
    finally:
        store.close()


def test_pdf_page_and_output_budgets_hold_without_truncating_or_projection(kit):
    too_many = authored_pdf(*(["a"] * 151))
    result = execute(kit, kit.manifest("page-limit", [[kit.item(media="application/pdf")]], bodies={"html": too_many}))
    assert result["documentRefs"][0]["hold"] == "pdf_page_limit" and result["counts"]["textReady"] == 0
    too_much = authored_pdf("x" * 500_001)
    result = execute(kit, kit.manifest("text-limit", [[kit.item(media="application/pdf")]], bodies={"html": too_much}), "text-limit", 1)
    assert result["documentRefs"][0]["hold"] == "text_output_limit" and result["counts"]["textReady"] == 0


def test_pdf_external_decoder_filter_is_rejected_in_supervised_child(kit):
    import io
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, DictionaryObject, EncodedStreamObject
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(authored_pdf("text"))))
    image = EncodedStreamObject()
    image._data = b"authored invalid external decoder payload"
    image[NameObject("/Type")] = NameObject("/XObject")
    image[NameObject("/Subtype")] = NameObject("/Image")
    image[NameObject("/Filter")] = NameObject("/JBIG2Decode")
    writer.pages[0]["/Resources"][NameObject("/XObject")] = DictionaryObject({NameObject("/Img"): writer._add_object(image)})
    raw = io.BytesIO()
    writer.write(raw)
    result = execute(kit, kit.manifest("external-decoder", [[kit.item(media="application/pdf")]], bodies={"html": raw.getvalue()}))
    assert result["documentRefs"][0]["hold"] == "pdf_external_decoder_filter" and result["counts"]["textReady"] == 0


@pytest.mark.parametrize("first_xpath", ['//article[@id="a"]', '/html/body/article[@id="b"]', None])
def test_preparation_isolation_after_scope_a_is_removed(kit, first_xpath):
    raw = '<html><body><article id="a">이전 A😀</article><article id="b">현재 B😀</article></body></html>'.encode()
    scope_a = copy.deepcopy(kit.registry["sources"][0]["scopes"][0])
    scope_a.update({"scopeId": "a", "articleXPath": first_xpath, "selection": "only original A"})
    scope_b = {**scope_a, "scopeId": "b", "articleXPath": '//article[@id="b"]', "selection": "only current B"}
    kit.registry["sources"][0]["scopes"] = [scope_a, scope_b]
    kit.save_registry()

    def run_scope(scope_id):
        manifest = kit.manifest("scope-" + scope_id, [[kit.item()]], bodies={"html": raw})
        payload = json.loads(manifest.read_bytes())
        payload["scopeId"] = scope_id
        manifest.write_bytes(json_bytes(payload))
        request = kit.request(manifest, "scope-" + scope_id)
        request["scopeId"] = scope_id
        store = Store(kit.root / "state")
        try:
            return Ingestor(store, Authority(kit.registry_path)).run(Run.model_validate(request), manifest)
        finally:
            store.close()

    first = run_scope("a")
    a = first["documentRefs"][0]
    assert first["counts"]["textReady"] == int(first_xpath is not None)
    kit.registry["sources"][0]["scopes"] = [scope_b]
    kit.save_registry()
    second = run_scope("b")
    b = second["documentRefs"][0]
    assert b["documentId"] == a["documentId"] and b["rawVersion"] == a["rawVersion"]
    assert second["counts"]["textReady"] == 1 and second["counts"]["newTextVersions"] == 1
    assert second["counts"]["reusedVersions"] == 0 and b["documentVersion"] != a["documentVersion"]
    current = inspect(kit, b, "scope-b")
    assert current["document"]["text"] == "현재 B😀"
    assert current["locatorMetadata"]["parserProfile"]["articleXPath"] == scope_b["articleXPath"]
    if first_xpath is not None:
        with pytest.raises(IngestionFailure, match="source_unauthorized"):
            inspect(kit, a, "scope-a")
    kit.registry["revision"] = "opaque-replacement"
    kit.registry["sources"][0]["grant"]["revision"] = "new-authority-not-new-text"
    kit.save_registry()
    assert run_scope("b") == second


def test_shared_durable_body_response_resumes_distinct_suppliers_without_files(kit):
    manifest = kit.manifest("shared-body", [[kit.item(), kit.item("c2", "supplier-2")]])
    payload = json.loads(manifest.read_bytes())
    kit.cli("run", kit.request(manifest), manifest=manifest, crash="raw", expected=75)
    for page in payload["pages"]:
        (kit.inputs / page["response"]["file"]).unlink()
    (kit.inputs / payload["documents"]["html"]["file"]).unlink()
    manifest.unlink()
    recovered = kit.cli("resume", kit.selector())
    assert recovered["state"] == "complete", recovered["failure"]
    assert recovered["counts"]["textReady"] == recovered["counts"]["newTextVersions"] == 2
    assert recovered["counts"]["newRawVersions"] == 2
    assert len({ref["documentId"] for ref in recovered["documentRefs"]}) == 2
    assert len({ref["documentVersion"] for ref in recovered["documentRefs"]}) == 2
    assert kit.cli("resume", kit.selector()) == recovered


def test_retired_and_new_app_and_worker_state_roots_are_never_adopted(tmp_path):
    from zoop_ai_pipeline.ingestion_contracts import reserved_state_roots
    reserved = reserved_state_roots()
    project = Path(__file__).resolve().parents[3]
    assert {p.relative_to(project).as_posix() for p in reserved if p.is_relative_to(project)} == {"prototype/bff/var", "prototype/ai-worker/var", "api/var", "ai/worker/var"}
    for root in reserved:
        for candidate in (root, root / "ingestion", root.parent):
            with pytest.raises(IngestionFailure, match="state_namespace_conflict"):
                Store(candidate)


def _installed(monkeypatch, tmp_path):
    """Make the contracts module look pip-installed: its file lives in a venv, not in a repository checkout."""
    from zoop_ai_pipeline import ingestion_contracts as contracts
    site = tmp_path / "venv/lib/python3.12/site-packages/zoop_ai_pipeline"
    site.mkdir(parents=True)
    monkeypatch.setattr(contracts, "__file__", str(site / "ingestion_contracts.py"))
    return contracts


def test_installed_package_without_explicit_ownership_roots_fails_closed(monkeypatch, tmp_path):
    contracts = _installed(monkeypatch, tmp_path)
    assert not contracts.source_checkout()
    for unset in (("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"), ("ZOOP_STATE_DIR",), ("ZOOP_AI_WORKER_STATE_DIR",)):
        for key in ("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"):
            monkeypatch.setenv(key, str(tmp_path / key.lower()))
        for key in unset:
            monkeypatch.delenv(key)
        with pytest.raises(IngestionFailure, match="state_ownership_unconfigured"):
            Store(tmp_path / "ledger")
    assert not (tmp_path / "ledger").exists()
    monkeypatch.setenv("ZOOP_STATE_DIR", "relative/app")
    monkeypatch.setenv("ZOOP_AI_WORKER_STATE_DIR", str(tmp_path / "worker"))
    with pytest.raises(IngestionFailure, match="state_ownership_unconfigured"):
        Store(tmp_path / "ledger")


def test_installed_package_rejects_the_explicit_app_and_worker_roots_of_a_synthetic_repository(monkeypatch, tmp_path):
    _installed(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    app, worker = repo / "api/var", repo / "ai/worker/var"
    monkeypatch.setenv("ZOOP_STATE_DIR", str(app))
    monkeypatch.setenv("ZOOP_AI_WORKER_STATE_DIR", str(worker))
    for root in (app, app / "ingestion", worker, worker / "ingestion", repo / "api", repo / "ai/worker"):
        with pytest.raises(IngestionFailure, match="state_namespace_conflict"):
            Store(root)
    assert not app.exists() and not worker.exists()
    # The interpreter's own venv is never mistaken for a repository: its api/var path is not reserved.
    guessed = tmp_path / "venv/api/var"
    assert guessed not in __import__("zoop_ai_pipeline.ingestion_contracts", fromlist=["x"]).reserved_state_roots()
    ledger = Store(tmp_path / "independent-ledger")
    ledger.close()


# ------------------------------------------------------------------------------------ declared publisher

OLD_OBSERVATION_KEYS = {"roundId", "sourceId", "page", "ordinal", "pageId", "observedAt", "documentId", "rawVersion", "documentVersion",
                        "url", "title", "publishedAt", "modifiedAt", "sourceRevision", "mediaType"}


def export(kit, ref, rid="round-1"):
    store = Store(kit.root / "state")
    try:
        request = Export.model_validate(kit.selector(rid, **{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}))
        return Ingestor(store, Authority(kit.registry_path)).export(request)
    finally:
        store.close()


def test_a_fixture_without_publisher_keeps_every_earlier_byte_and_identity(kit):
    # The literals below were taken from the commit before `publisher` existed (a one-time run of that code), not from this implementation.
    assert canonical(Item.model_validate(kit.item()).metadata()) == \
        '{"mediaType":"text/html","modifiedAt":null,"publishedAt":"2026-10-08T00:00:00+00:00","sourceRevision":null,"title":"authored"}'
    assert canonical(Item.model_validate(kit.item()).wire()) == \
        ('{"bodyRef":"html","candidateId":"c1","collection":null,"mediaType":"text/html","modifiedAt":null,"publishedAt":"2026-10-08T00:00:00+00:00",'
         '"sourceRevision":null,"supplierDocumentId":"supplier-1","title":"authored","url":"https://example.invalid/article"}')
    ref = execute(kit, kit.manifest("a", [[kit.item()]]))["documentRefs"][0]
    assert (ref["documentId"], ref["rawVersion"], ref["documentVersion"]) == (
        "doc-e222c75b08309d1fb600b12fee9d0e3d1608abf308b1e2729d150b70edde50a0",
        "763f311a471328bb47ba04b484173642acc840e6f5bba9afcad601424c424986",
        "4b685906fc3a1402c605da54a7ab7fc9e2e49f7af6021dbc06eab3287a551fe9")
    assert set(export(kit, ref)["observation"]) == OLD_OBSERVATION_KEYS


def test_a_declared_publisher_is_a_new_version_of_the_same_document_exported_exactly(kit):
    plain = execute(kit, kit.manifest("plain", [[kit.item()]]), "plain", 0)["documentRefs"][0]
    before = export(kit, plain, "plain")
    named_item = kit.item(publisher="한국경제 Daily")
    named = execute(kit, kit.manifest("named", [[named_item]]), "named", 1)["documentRefs"][0]
    other = execute(kit, kit.manifest("other", [[kit.item(publisher="Other Daily")]]), "other", 2)["documentRefs"][0]
    assert plain["documentId"] == named["documentId"] == other["documentId"]
    assert len({plain["rawVersion"], named["rawVersion"], other["rawVersion"]}) == 3
    assert len({plain["documentVersion"], named["documentVersion"], other["documentVersion"]}) == 3
    assert export(kit, named, "named")["observation"]["publisher"] == "한국경제 Daily"
    assert export(kit, other, "other")["observation"]["publisher"] == "Other Daily"
    assert export(kit, plain, "plain") == before and "publisher" not in before["observation"]
    # Same declared outlet again (a new round, a fresh manifest) is exactly the version already stored, not a new one.
    again = execute(kit, kit.manifest("again", [[named_item]]), "again", 3)
    assert again["counts"]["newRawVersions"] == 0 and again["counts"]["newTextVersions"] == 0
    assert again["documentRefs"][0]["documentVersion"] == named["documentVersion"] and again["documentRefs"][0]["rawVersion"] == named["rawVersion"]
    # An explicit null is unspecified: the earlier version, with no key and no new row.
    null = execute(kit, kit.manifest("null", [[{**kit.item(), "publisher": None}]]), "null", 4)["documentRefs"][0]
    assert (null["rawVersion"], null["documentVersion"]) == (plain["rawVersion"], plain["documentVersion"])
    assert "publisher" not in export(kit, null, "null")["observation"]


@pytest.mark.parametrize("value", ["", " ", "   ", "\u3000", "\u2028", "\u00a0", "\t", "a\nb", "a\x00b", "\x7f", "\x85", "x" * 201, "😀" * 201, 5, True, ["a"], {"name": "a"}])
def test_an_invalid_declared_publisher_is_refused_everywhere_it_can_enter(kit, value):
    with pytest.raises(ValidationError):
        Item.model_validate({**kit.item(), "publisher": value})
    refused = execute(kit, kit.manifest("bad", [[{**kit.item(), "publisher": value}]]))
    assert refused["state"] == "incomplete" and refused["counts"]["textReady"] == 0 and refused["documentRefs"][0]["error"] == "discovery_item_invalid"


@pytest.mark.parametrize("value", ["x", " A ", "A  B", "x" * 200, "😀" * 200, "e\u0301", "\u00e9", "한국경제TV", "A\u00a0B"])
def test_a_valid_declared_publisher_is_stored_and_exported_exactly_without_normalization(kit, value):
    ref = execute(kit, kit.manifest("good", [[kit.item(publisher=value)]]))["documentRefs"][0]
    assert export(kit, ref)["observation"]["publisher"] == value
    assert Item.model_validate(kit.item(publisher=value)).metadata()["publisher"] == value


def test_a_lone_surrogate_publisher_is_refused(kit):
    with pytest.raises(ValidationError):
        Item.model_validate({**kit.item(), "publisher": "a\ud800b"})


def caption_fixture(kit):
    """Synthetic collected bytes and an explicit synthetic-only boundary decision."""
    raw = ("<html><body><article><p>허용 한😀e\u0301 &amp; <b>인라인</b> 꼬리</p>"
           "<figure>도표 본문도 유지<img src='a.jpg'><figcaption><b>제외캡션하나</b></figcaption>캡션꼬리</figure>"
           "<p>뉴스1 무단 전재라는 단어도 본문이면 유지</p>"
           "<figure><img src='b.jpg'><figcaption>제외캡션둘</figcaption></figure>"
           "<p>마지막 허용본문</p></article></body></html>").encode()
    source = kit.registry["sources"][0]
    source["adapter"] = "collected-http"
    kit.save_registry()
    item = kit.item()
    item["publishedAt"] = None
    collection = {"provenance": "collected_http", "collectionId": "synthetic-caption", "fetchedAt": "2026-10-08T01:00:00+00:00",
        "finalUrl": item["url"], "httpStatus": 200, "contentType": "text/html", "bodySha256": sha(raw),
        "documentKind": "news", "network": "synthetic_loopback",
        "published": {"raw": "2026-10-08", "precision": "day", "date": "2026-10-08", "basis": "synthetic declaration"}}
    receipt = {"schemaVersion": "zoop-collection-receipt-1", "collectionId": collection["collectionId"],
        "sourceId": source["sourceId"], "scopeId": "body", "candidateId": item["candidateId"],
        "grantId": source["grant"]["grantId"], "grantRevision": source["grant"]["revision"],
        "requestedUrl": item["url"], "finalUrl": item["url"], "redirects": [], "httpStatus": 200,
        "contentType": "text/html", "mediaType": "text/html", "contentLength": None, "etag": None,
        "lastModified": None, "serverDate": None, "bodySha256": sha(raw), "bodyBytes": len(raw),
        "fetchedAt": collection["fetchedAt"], "userAgent": "synthetic", "network": "synthetic_loopback",
        "robots": [], "requestCount": 1}
    collection["receipt"] = kit.file("receipt.json", json_bytes(receipt))
    item["collection"] = collection
    manifest = kit.manifest("captions", [[item]], bodies={"html": raw})
    parent = execute(kit, manifest)
    ref = parent["documentRefs"][0]
    exported = inspect(kit, ref)
    paths = [f"/html/body/article/figure[{i}]/figcaption" for i in (1, 2)]
    rights = kit.file("rights.json", json_bytes({"bodySha256": sha(raw), "canonicalUrl": item["url"],
        "license": "KOGL-type-1-text-only", "notice": "synthetic item-local text-only notice"}))
    metadata = exported["locatorMetadata"]
    projection = {"profile": "korea-kogl1-caption-boundary-1",
        "parent": {**{k: ref[k] for k in ("documentId", "rawVersion", "documentVersion")},
            **{k: metadata[k] for k in ("rawHash", "representationHash", "mappingHash", "parserProfile")},
            "sourceHash": exported["document"]["sourceHash"]},
        "excludedCaptionPaths": paths, "rightsReceipt": {"path": str(kit.inputs / rights["file"]), "sha256": rights["sha256"]},
        "boundaryDecision": {"revision": "synthetic-boundary-1", "status": "approved",
            "retainedScope": "article-prose-only", "reviewedCaptionPaths": paths,
            "evidence": ["synthetic fixture owner reviewed all retained prose and both caption boundaries"]}}
    return manifest, projection, exported


def test_caption_projection_preserves_exact_slots_and_barriers_with_new_identity(kit):
    manifest, projection, parent = caption_fixture(kit)
    kit.registry["sources"][0]["scopes"][0]["textProjection"] = projection
    kit.save_registry()
    result = execute(kit, manifest, state="projected")
    assert result["counts"]["textReady"] == 1
    ref = result["documentRefs"][0]
    store = Store(kit.root / "projected", existing=True)
    try:
        runner = Ingestor(store, Authority(kit.registry_path))
        selected = kit.selector(**{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")})
        derived = runner.export(Export.model_validate(selected))
        doc = derived["document"]
        assert doc["text"] == "허용 한😀e\u0301 & 인라인 꼬리\n도표 본문도 유지\n캡션꼬리\n뉴스1 무단 전재라는 단어도 본문이면 유지\n마지막 허용본문"
        assert ref["documentId"] == parent["document"]["documentId"]
        assert ref["rawVersion"] == parent["locatorMetadata"]["rawVersion"]
        assert ref["documentVersion"] != parent["document"]["documentVersion"]
        assert derived["locatorMetadata"]["representationHash"] == parent["locatorMetadata"]["representationHash"]
        assert derived["observation"]["publishedAt"] is None
        assert derived["observation"]["collection"]["published"]["precision"] == "day"
        for quote in ("한😀e\u0301 & 인라인 꼬리", "캡션꼬리", "마지막 허용본문"):
            start = doc["text"].index(quote)
            end = start + len(quote)
            locator = next(loc for loc in doc["rawLocators"] if loc["start"] <= start < end <= loc["end"])
            resolved = runner.inspect(Inspect.model_validate(kit.selector(documentId=ref["documentId"],
                documentVersion=ref["documentVersion"], locatorId=locator["locatorId"], start=start, end=end)))["resolvedLocator"]
            assert "".join(s["text"] for s in resolved["segments"]) == quote
            if quote == "캡션꼬리":
                assert resolved["segments"][0]["domPath"] == "/html/body/article/figure[1]/figcaption"
                assert resolved["segments"][0]["slot"] == "tail"
        exact_check(doc, 0, len(doc["text"]), False)
    finally:
        store.close()


@pytest.mark.parametrize("fault,code", [
    ("rawHash", "projection_parent_mismatch"),
    ("sourceHash", "projection_parent_mismatch"),
    ("representationHash", "projection_parent_mismatch"),
    ("mappingHash", "projection_parent_mismatch"),
    ("documentId", "projection_parent_mismatch"),
    ("rawVersion", "projection_parent_mismatch"),
    ("documentVersion", "projection_parent_mismatch"),
    ("parserProfile", "projection_parent_mismatch"),
    ("path", "projection_caption_boundary_incomplete"),
    ("one-caption", "projection_caption_boundary_incomplete"),
    ("rights-hash", "projection_rights_receipt_hash_mismatch"),
    ("rights-body", "projection_rights_receipt_invalid"),
    ("rights-license", "projection_rights_receipt_invalid"),
    ("proposal", "projection_boundary_review_required"),
    ("hold", "projection_boundary_review_required"),
])
def test_caption_projection_failures_hold_instead_of_exporting_parent_text(kit, fault, code):
    manifest, projection, _ = caption_fixture(kit)
    if fault in projection["parent"]:
        projection["parent"][fault] = {} if fault == "parserProfile" else "0" * 64
    elif fault in {"path", "one-caption"}:
        paths = ["/html/body/article/p[1]"] if fault == "path" else projection["excludedCaptionPaths"][:1]
        projection["excludedCaptionPaths"] = projection["boundaryDecision"]["reviewedCaptionPaths"] = paths
    elif fault == "rights-hash":
        projection["rightsReceipt"]["sha256"] = "0" * 64
    elif fault in {"rights-body", "rights-license"}:
        rights = json.loads(Path(projection["rightsReceipt"]["path"]).read_bytes())
        rights["bodySha256" if fault == "rights-body" else "license"] = "wrong"
        changed = kit.file("changed-rights.json", json_bytes(rights))
        projection["rightsReceipt"] = {"path": str(kit.inputs / changed["file"]), "sha256": changed["sha256"]}
    else:
        projection["boundaryDecision"]["status"] = fault
    kit.registry["sources"][0]["scopes"][0]["textProjection"] = projection
    kit.save_registry()
    result = execute(kit, manifest, state="refused")
    assert result["counts"]["held"] == 1 and result["counts"]["textReady"] == 0
    assert result["documentRefs"][0]["hold"] == code
    assert result["documentRefs"][0]["documentVersion"] is None


def test_caption_projection_descriptor_is_optional_closed_and_adapter_bound(kit):
    from zoop_ai_pipeline.ingestion_contracts import Registry

    original = copy.deepcopy(kit.registry)
    assert Registry.model_validate(original).wire() == original
    _, projection, _ = caption_fixture(kit)
    for fault in ("profile", "decision", "reviewed", "adapter"):
        registry = copy.deepcopy(kit.registry)
        value = copy.deepcopy(projection)
        registry["sources"][0]["scopes"][0]["textProjection"] = value
        if fault == "profile":
            value["profile"] = "arbitrary-xpath-delete"
        elif fault == "decision":
            del value["boundaryDecision"]
        elif fault == "reviewed":
            value["boundaryDecision"]["reviewedCaptionPaths"] = value["excludedCaptionPaths"][:1]
        else:
            registry["sources"][0]["adapter"] = "authored-files"
        with pytest.raises(ValidationError):
            Registry.model_validate(registry)


def test_caption_projection_cache_and_current_send_authority_bind_the_frozen_descriptor(kit):
    from zoop_ai_pipeline.ingestion_contracts import Registry

    manifest, projection, _ = caption_fixture(kit)
    original = copy.deepcopy(kit.registry)
    source = kit.registry["sources"][0]
    source["scopes"][0]["textProjection"] = projection
    kit.save_registry()
    first = execute(kit, manifest, state="projected")
    ref = first["documentRefs"][0]
    reused = execute(kit, manifest, "again", 1, state="projected")
    assert reused["counts"]["reusedVersions"] == 1
    projection["boundaryDecision"]["revision"] = "synthetic-boundary-2"
    kit.save_registry()
    second = execute(kit, manifest, state="changed-descriptor")
    assert second["documentRefs"][0]["documentVersion"] != ref["documentVersion"]
    current = copy.deepcopy(kit.registry)
    current["sources"][0]["scopes"][0]["textProjection"]["boundaryDecision"]["revision"] = "synthetic-boundary-1"
    current["sources"][0]["grant"].update(revision="send-2", allowedOperations=["read", "quote-display", "model-send"],
        purposes=["pipeline:extract"], recipients=["synthetic-recipient"])
    parsed = Registry.model_validate(current).sources[0]
    config = parsed.configuration(parsed.scopes[0])
    kit.registry = current
    kit.save_registry()
    authority = Authority(kit.registry_path)
    authority.check("synthetic-source", "body", ("read", "quote-display"), config, purpose="pipeline:extract", recipient="synthetic-recipient")
    for purpose, recipient in (("wrong", "synthetic-recipient"), ("pipeline:extract", "wrong")):
        with pytest.raises(IngestionFailure, match="source_purpose_or_recipient_denied"):
            authority.check("synthetic-source", "body", ("read",), config, purpose=purpose, recipient=recipient)
    old = Registry.model_validate(original).sources[0]
    with pytest.raises(IngestionFailure, match="scope_configuration_conflict"):
        authority.check("synthetic-source", "body", ("read",), old.configuration(old.scopes[0]),
            purpose="pipeline:extract", recipient="synthetic-recipient")
    kit.registry["sources"][0]["grant"]["enabled"] = False
    kit.save_registry()
    with pytest.raises(IngestionFailure, match="source_unauthorized"):
        Authority(kit.registry_path).check("synthetic-source", "body", ("read",), config,
            purpose="pipeline:extract", recipient="synthetic-recipient")


def test_projected_native_export_is_caption_free_in_every_real_offline_request(kit, monkeypatch, tmp_path):
    from tests.live_support import PAYLOADS, article, environment
    from zoop_ai_pipeline import live_runtime
    from zoop_ai_pipeline.live_runtime import LiveRuntime

    manifest, projection, _ = caption_fixture(kit)
    kit.registry["sources"][0]["scopes"][0]["textProjection"] = projection
    kit.save_registry()
    result = execute(kit, manifest, state="projected")
    ref = result["documentRefs"][0]
    store = Store(kit.root / "projected", existing=True)
    try:
        exported = Ingestor(store, Authority(kit.registry_path)).export(Export.model_validate(
            kit.selector(**{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")})))
    finally:
        store.close()
    doc = exported["document"]
    native_article = article(doc["text"]).model_copy(update={"article_id": doc["documentId"]})
    source = {"documentId": doc["documentId"], "documentVersion": doc["documentVersion"],
        "article_id": native_article.article_id, "article_version": native_article.version, "text": doc["text"],
        "mapped": [[r["start"], r["end"]] for r in doc["rawLocators"]]}
    quote = {"quoteId": "ev-a", "documentId": doc["documentId"], "documentVersion": doc["documentVersion"],
        "start": 0, "end": doc["rawLocators"][0]["end"], "text": doc["text"][:doc["rawLocators"][0]["end"]]}
    environment(monkeypatch, tmp_path, **{live_runtime.OPENAI_KEY_VAR: None, live_runtime.JEV_KEY_VAR: None})
    runtime = LiveRuntime.from_binding(LiveRuntime.from_env().binding())
    for stage, factory in PAYLOADS.items():
        payload = factory()
        if "article" in payload:
            payload["article"] = native_article.model_dump(mode="json")
        if "article_version" in payload:
            payload["article_version"] = native_article.version
        if "issue" in payload:
            payload["issue"]["articles"] = [native_article.model_dump(mode="json")]
        if stage in {"topic", "relation", "impact"}:
            payload["documents"] = [{k: doc[k] for k in ("documentId", "documentVersion", "text")} | {"title": "synthetic"}]
        if stage in {"extract", "compare", "topic", "relation", "impact"}:
            payload["citationSources"] = [source]
        if "quotes" in payload:
            payload["quotes"] = [quote, {**quote, "quoteId": "ev-b"}]
        if "relationQuotes" in payload:
            payload["relationQuotes"] = [quote]
        body = canonical(runtime.prepare(stage, payload)["body"])
        assert "허용 한😀e\u0301 & 인라인 꼬리" in body, stage
        assert "제외캡션하나" not in body and "제외캡션둘" not in body, stage


@pytest.mark.parametrize("media", ["application/pdf", "text/markdown"])
def test_caption_projection_refuses_non_html_representations(kit, media):
    from zoop_ai_pipeline.ingestion_contracts import TextProjection

    _, projection, _ = caption_fixture(kit)
    with pytest.raises(IngestionFailure, match="projection_media_unsupported"):
        parsers.prepare(b"body", media, None, projection=TextProjection.model_validate(projection))


def test_caption_projection_requires_image_associated_caption_boundaries(kit):
    from zoop_ai_pipeline.ingestion_contracts import TextProjection, digest

    manifest, projection, _ = caption_fixture(kit)
    payload = json.loads(manifest.read_bytes())
    raw = (kit.inputs / payload["documents"]["html"]["file"]).read_bytes().replace(b"<img src='a.jpg'>", b"")
    baseline = parsers.prepare(raw, "text/html", None)
    representation = digest(baseline["sources"])
    projection["parent"].update(sourceHash=digest(baseline["text"]), representationHash=representation,
        mappingHash=digest({"representationHash": representation, "segments": baseline["segments"], "runs": baseline["runs"]}))
    with pytest.raises(IngestionFailure, match="projection_caption_boundary_unsupported"):
        parsers.prepare(raw, "text/html", None, projection=TextProjection.model_validate(projection))


def pdf_projection_fixture(kit):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject
    from zoop_ai_pipeline.ingestion_contracts import digest

    caption_fixture(kit)
    raw = authored_pdf("DATE. Narrative first. CONTACT_SENTINEL. Continued paragraph",
                       "continues here. Retained final. DIGEST_SENTINEL.")
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(raw)))
    page = writer.pages[1]
    page["/Resources"]["/Font"]["/F1"][NameObject("/Encoding")] = NameObject("/WinAnsiEncoding")
    stream = page["/Contents"]
    stream.set_data(stream.get_data().replace(b"final", b"fin\\341l"))
    output = io.BytesIO()
    writer.write(output)
    raw = output.getvalue()
    collected = kit.item()
    collected["publishedAt"] = None
    receipt = json.loads((kit.inputs / "receipt.json").read_bytes())
    receipt.update(contentType="application/pdf", mediaType="application/pdf", bodySha256=sha(raw), bodyBytes=len(raw))
    receipt_ref = kit.file("pdf-receipt.json", json_bytes(receipt))
    collected.update(mediaType="application/pdf", collection={
        "provenance": "collected_http", "collectionId": receipt["collectionId"], "fetchedAt": receipt["fetchedAt"],
        "finalUrl": collected["url"], "httpStatus": 200, "contentType": "application/pdf", "bodySha256": sha(raw),
        "documentKind": "news", "network": "synthetic_loopback", "receipt": receipt_ref,
        "published": {"raw": "2026-10-08", "precision": "day", "date": "2026-10-08", "basis": "synthetic"}})
    manifest = kit.manifest("pdf-body", [[collected]], bodies={"html": raw})
    parent_result = execute(kit, manifest, state="pdf-parent")
    ref = parent_result["documentRefs"][0]
    store = Store(kit.root / "pdf-parent", existing=True)
    try:
        parent = Ingestor(store, Authority(kit.registry_path)).export(Export.model_validate(
            kit.selector(**{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")})))
    finally:
        store.close()
    baseline = parsers.prepare(raw, "application/pdf", None)
    units, allowed = [], []
    cuts = [
        [(0, 5, "date", "original-dateline"), (5, 23, "narrative", "commission-narrative"),
         (23, 41, "contact", "press-contact"), (41, len(baseline["sources"][0]["text"]), "cross", "commission-narrative")],
        [(0, 15, "cross", "commission-narrative"), (15, 31, "final", "commission-narrative"),
         (31, len(baseline["sources"][1]["text"]), "digest", "unrelated-digest")]]
    by_id = {}
    for source, spans in zip(baseline["sources"], cuts):
        for start, end, uid, classification in spans:
            span = {"pageNumber": source["pageNumber"], "pageTextHash": source["pageTextHash"],
                "sourceStart": start, "sourceEnd": end, "textUtf8Sha256": sha(source["text"][start:end].encode())}
            if uid not in by_id:
                by_id[uid] = {"unitId": uid, "classification": classification, "spans": [],
                    "reviewBasis": "Synthetic fixture owner specifies whole source units"}
                units.append(by_id[uid])
            by_id[uid]["spans"].append(span)
            if classification not in {"press-contact", "unrelated-digest"}:
                allowed.append({**span, "reviewUnitId": uid})
    metadata = parent["locatorMetadata"]
    rights = {"schemaVersion": "zoop-eu-pdf-body-rights-1", "bodySha256": sha(raw),
        "parentDocumentVersion": ref["documentVersion"], "selectionHash": digest(allowed),
        "license": "CC-BY-4.0-qualified-commission-content", "applicabilityAssessment": "Synthetic owner",
        "notice": "Synthetic CC BY notice", "evidence": [], "attribution": "Synthetic Commission",
        "changesNotice": "Selected paragraphs; contacts and unrelated digest omitted", "reviewUnits": units}
    evidence = kit.file("pdf-policy.txt", b"Synthetic policy evidence")
    rights["evidence"] = [{"path": str(kit.inputs / evidence["file"]), "sha256": evidence["sha256"]}]
    rights_file = kit.file("pdf-rights.json", json_bytes(rights))
    member = {"parent": {**{k: ref[k] for k in ("documentId", "rawVersion", "documentVersion")},
        **{k: metadata[k] for k in ("rawHash", "representationHash", "mappingHash", "parserProfile")},
        "sourceHash": parent["document"]["sourceHash"]}, "collectionReceiptSha256": receipt_ref["sha256"],
        "allowedRanges": allowed, "rightsReceipt": {"path": str(kit.inputs / rights_file["file"]), "sha256": rights_file["sha256"]},
        "boundaryDecision": {"revision": "synthetic-pdf-1", "status": "approved",
            "retainedScope": "commission-narrative-and-original-dateline", "selectionHash": digest(allowed),
            "evidence": ["Synthetic whole-paragraph review"]}}
    return manifest, {"profile": "eu-commission-pdf-body-ranges-1", "members": [member]}, parent, rights


def test_pdf_body_projection_native_identity_and_whole_source_units(kit):
    manifest, projection, parent, _ = pdf_projection_fixture(kit)
    kit.registry["sources"][0]["scopes"][0]["textProjection"] = projection
    kit.save_registry()
    result = execute(kit, manifest, state="pdf-projected")
    assert result["counts"]["textReady"] == 1
    ref = result["documentRefs"][0]
    store = Store(kit.root / "pdf-projected", existing=True)
    try:
        derived = Ingestor(store, Authority(kit.registry_path)).export(Export.model_validate(
            kit.selector(**{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")})))
        assert derived["document"]["text"] == "DATE. Narrative first. \nContinued paragraph\ncontinues here. Retained finál."
        assert derived["locatorMetadata"]["representationHash"] == parent["locatorMetadata"]["representationHash"]
        assert derived["document"]["documentId"] == parent["document"]["documentId"]
        assert derived["locatorMetadata"]["rawVersion"] == parent["locatorMetadata"]["rawVersion"]
        assert derived["document"]["documentVersion"] != parent["document"]["documentVersion"]
        assert derived["observation"]["collection"] == parent["observation"]["collection"]
        exact_check(derived["document"], 0, len(derived["document"]["text"]), False)
    finally:
        store.close()


def test_pdf_projection_warm_cache_checks_each_observation_receipt(kit):
    manifest, projection, _, _ = pdf_projection_fixture(kit)
    kit.registry["sources"][0]["scopes"][0]["textProjection"] = projection
    kit.save_registry()
    state = "pdf-receipt-reuse"
    first = kit.cli("run", kit.request(manifest), state=state, manifest=manifest)
    ref = first["documentRefs"][0]
    selector = kit.selector(**{k: ref[k] for k in
        ("page", "ordinal", "documentId", "rawVersion", "documentVersion")})
    original = kit.cli("export", selector, state=state)

    payload = json.loads(manifest.read_bytes())
    page = json.loads((kit.inputs / payload["pages"][0]["response"]["file"]).read_bytes())
    second_item = page["items"][0]
    receipt = json.loads((kit.inputs / second_item["collection"]["receipt"]["file"]).read_bytes())
    receipt.update(collectionId="synthetic-reacquisition", fetchedAt="2026-10-09T01:02:03+00:00")
    second_item["collection"].update(collectionId=receipt["collectionId"], fetchedAt=receipt["fetchedAt"],
        receipt=kit.file("reacquisition-receipt.json", json_bytes(receipt)))
    raw = (kit.inputs / payload["documents"]["html"]["file"]).read_bytes()
    second_manifest = kit.manifest("reacquisition", [[second_item]], bodies={"html": raw})
    second_request = kit.request(second_manifest, "reacquisition", 1)
    second = kit.cli("run", second_request, state=state, manifest=second_manifest)
    second_ref = second["documentRefs"][0]
    assert second["state"] == "complete"
    assert second_ref["rawVersion"] == ref["rawVersion"]
    assert second["counts"]["held"] == 1 and second["counts"]["textReady"] == 0
    assert second_ref["hold"] == "projection_collection_receipt_mismatch"
    assert second_ref["documentVersion"] is None and second_ref["failure"] is None
    assert kit.cli("run", second_request, state=state, manifest=second_manifest) == second
    refused = kit.cli("export", {**selector, "roundId": "reacquisition"}, state=state, expected=2)
    assert refused["error"]["code"] == "observation_not_found"

    assert kit.cli("export", selector, state=state) == original
    inspected = kit.cli("inspect", kit.selector(documentId=ref["documentId"],
        documentVersion=ref["documentVersion"]), state=state)
    assert inspected["document"] == original["document"]
    store = Store(kit.root / state, existing=True)
    try:
        assert store.one("SELECT data FROM blobs WHERE hash=?",
            (projection["members"][0]["collectionReceiptSha256"],))["data"] == (kit.inputs / "pdf-receipt.json").read_bytes()
        assert store.one("SELECT COUNT(*) n FROM preparations")["n"] == 1
        assert store.one("SELECT COUNT(*) n FROM versions")["n"] == 1
    finally:
        store.close()
    replay = kit.cli("run", kit.request(manifest, "unchanged-receipt", 2), state=state, manifest=manifest)
    assert replay["counts"]["reusedVersions"] == 1
    assert replay["counts"]["newRawVersions"] == replay["counts"]["newTextVersions"] == 0
    assert replay["documentRefs"][0]["documentVersion"] == ref["documentVersion"]


@pytest.mark.parametrize("fault,code", [
    ("parent", "projection_parent_mismatch"), ("receipt", "projection_collection_receipt_mismatch"),
    ("member", "projection_member_missing"), ("rights-pin", "projection_rights_receipt_hash_mismatch"),
    ("rights-binding", "projection_rights_receipt_invalid"), ("evidence", "projection_rights_evidence_mismatch"),
    ("rights-missing", "projection_rights_receipt_invalid"), ("rights-unresolved", "projection_rights_receipt_invalid"),
    ("coverage", "projection_review_coverage_invalid"), ("unit-overlap", "projection_review_coverage_invalid"),
    ("page-hash", "projection_review_units_invalid"), ("page-bounds", "projection_review_units_invalid"),
    ("slice-hash", "projection_review_units_invalid"), ("partial", "projection_whole_positive_unit_required"),
    ("cross-page-partial", "projection_whole_positive_unit_required"),
    ("contact", "projection_whole_positive_unit_required"), ("whole-page", "projection_whole_positive_unit_required"),
    ("proposal", "projection_boundary_review_required"), ("hold", "projection_boundary_review_required"),
])
def test_pdf_body_projection_refuses_unreviewed_or_unbound_content(kit, fault, code):
    from zoop_ai_pipeline.ingestion_contracts import digest

    manifest, projection, _, rights = pdf_projection_fixture(kit)
    member = projection["members"][0]
    if fault == "parent":
        member["parent"]["mappingHash"] = "0" * 64
    elif fault == "receipt":
        member["collectionReceiptSha256"] = "0" * 64
    elif fault == "member":
        member["parent"]["documentId"] = "different-document"
    elif fault in {"rights-pin", "rights-missing"}:
        member["rightsReceipt"]["sha256"] = "0" * 64
    elif fault == "rights-binding":
        rights["bodySha256"] = "0" * 64
    elif fault == "rights-unresolved":
        rights["applicabilityAssessment"] = " "
    elif fault == "evidence":
        rights["evidence"][0]["sha256"] = "0" * 64
    elif fault == "coverage":
        rights["reviewUnits"].pop()
    elif fault == "unit-overlap":
        rights["reviewUnits"].append({**rights["reviewUnits"][0], "unitId": "overlap"})
    elif fault in {"page-hash", "page-bounds", "slice-hash"}:
        span = rights["reviewUnits"][0]["spans"][0]
        span[{"page-hash": "pageTextHash", "page-bounds": "sourceEnd", "slice-hash": "textUtf8Sha256"}[fault]] = (
            10000 if fault == "page-bounds" else "0" * 64)
    elif fault == "partial":
        member["allowedRanges"][1]["sourceEnd"] -= 1
    elif fault == "cross-page-partial":
        member["allowedRanges"] = [s for s in member["allowedRanges"] if not
            (s["reviewUnitId"] == "cross" and s["pageNumber"] == 2)]
    elif fault == "contact":
        span = rights["reviewUnits"][2]["spans"][0]
        member["allowedRanges"].insert(2, {**span, "reviewUnitId": "contact"})
    elif fault == "whole-page":
        member["allowedRanges"] = [{**member["allowedRanges"][0], "sourceEnd": 57}]
    else:
        member["boundaryDecision"]["status"] = fault
    selection = digest(member["allowedRanges"])
    member["boundaryDecision"]["selectionHash"] = rights["selectionHash"] = selection
    changed = kit.file("pdf-changed-rights.json", json_bytes(rights))
    if fault != "rights-pin":
        member["rightsReceipt"] = {"path": str(kit.inputs / changed["file"]), "sha256": changed["sha256"]}
    if fault == "rights-missing":
        member["rightsReceipt"]["path"] = str(kit.inputs / "missing-rights.json")
    kit.registry["sources"][0]["scopes"][0]["textProjection"] = projection
    kit.save_registry()
    result = execute(kit, manifest, state="pdf-refused")
    assert result["counts"]["held"] == 1 and result["counts"]["textReady"] == 0
    assert result["documentRefs"][0]["hold"] == code
    assert result["documentRefs"][0]["documentVersion"] is None


@pytest.mark.parametrize("fault", ["duplicate", "overlap", "reverse", "selection", "empty"])
def test_pdf_body_projection_rejects_malformed_descriptor_without_repair(kit, fault):
    from zoop_ai_pipeline.ingestion_contracts import Registry, digest

    _, projection, _, _ = pdf_projection_fixture(kit)
    member = projection["members"][0]
    if fault == "duplicate":
        projection["members"].append(copy.deepcopy(member))
    elif fault == "overlap":
        member["allowedRanges"][1]["sourceStart"] = 0
    elif fault == "reverse":
        member["allowedRanges"].reverse()
    elif fault == "selection":
        member["boundaryDecision"]["selectionHash"] = "0" * 64
    else:
        member["allowedRanges"] = []
    if fault != "selection":
        member["boundaryDecision"]["selectionHash"] = digest(member["allowedRanges"])
    kit.registry["sources"][0]["scopes"][0]["textProjection"] = projection
    with pytest.raises(ValidationError):
        Registry.model_validate(kit.registry)


def test_pdf_projected_export_serializes_only_retained_body_in_all_seven_routes(kit, monkeypatch, tmp_path):
    from tests.live_support import PAYLOADS, article, environment
    from zoop_ai_pipeline import live_runtime
    from zoop_ai_pipeline.live_runtime import LiveRuntime

    manifest, projection, _, _ = pdf_projection_fixture(kit)
    kit.registry["sources"][0]["scopes"][0]["textProjection"] = projection
    kit.save_registry()
    result = execute(kit, manifest, state="pdf-payload")
    ref = result["documentRefs"][0]
    store = Store(kit.root / "pdf-payload", existing=True)
    try:
        exported = Ingestor(store, Authority(kit.registry_path)).export(Export.model_validate(
            kit.selector(**{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")})))
    finally:
        store.close()
    doc = exported["document"]
    native = article(doc["text"]).model_copy(update={"article_id": doc["documentId"]})
    citation = {"documentId": doc["documentId"], "documentVersion": doc["documentVersion"],
        "article_id": native.article_id, "article_version": native.version, "text": doc["text"],
        "mapped": [[r["start"], r["end"]] for r in doc["rawLocators"]]}
    quote = {"quoteId": "ev-a", "documentId": doc["documentId"], "documentVersion": doc["documentVersion"],
        "start": 0, "end": doc["rawLocators"][0]["end"], "text": doc["text"][:doc["rawLocators"][0]["end"]]}
    environment(monkeypatch, tmp_path, **{live_runtime.OPENAI_KEY_VAR: None, live_runtime.JEV_KEY_VAR: None})
    runtime = LiveRuntime.from_binding(LiveRuntime.from_env().binding())
    for stage, factory in PAYLOADS.items():
        payload = factory()
        if "article" in payload:
            payload["article"] = native.model_dump(mode="json")
        if "article_version" in payload:
            payload["article_version"] = native.version
        if "issue" in payload:
            payload["issue"]["articles"] = [native.model_dump(mode="json")]
        if stage in {"topic", "relation", "impact"}:
            payload["documents"] = [{k: doc[k] for k in ("documentId", "documentVersion", "text")} | {"title": "synthetic"}]
        if stage in {"extract", "compare", "topic", "relation", "impact"}:
            payload["citationSources"] = [citation]
        for name in ("quotes", "relationQuotes"):
            if name in payload:
                payload[name] = [quote, {**quote, "quoteId": "ev-b"}] if name == "quotes" else [quote]
        body = canonical(runtime.prepare(stage, payload)["body"])
        assert "Narrative first." in body, stage
        assert all(value not in body for value in ("CONTACT_SENTINEL", "DIGEST_SENTINEL",
            projection["members"][0]["rightsReceipt"]["path"], "Synthetic CC BY notice")), stage


def test_pdf_shared_scope_cohort_identity_and_current_send_configuration(kit):
    from zoop_ai_pipeline.ingestion_contracts import Registry

    manifest, projection, _, rights = pdf_projection_fixture(kit)
    original_registry = copy.deepcopy(kit.registry)
    payload = json.loads(manifest.read_bytes())
    response = json.loads((kit.inputs / payload["pages"][0]["response"]["file"]).read_bytes())
    second = copy.deepcopy(response["items"][0])
    second.update(candidateId="c2", supplierDocumentId="supplier-2", url="https://example.invalid/second")
    receipt = json.loads((kit.inputs / "pdf-receipt.json").read_bytes())
    receipt.update(candidateId="c2", requestedUrl=second["url"], finalUrl=second["url"])
    second["collection"].update(finalUrl=second["url"], receipt=kit.file("second-receipt.json", json_bytes(receipt)))
    raw = (kit.inputs / payload["documents"]["html"]["file"]).read_bytes()
    cohort_manifest = kit.manifest("pdf-cohort", [[response["items"][0], second]], bodies={"html": raw})
    parents = execute(kit, cohort_manifest, state="cohort-parents")
    parent_ref = parents["documentRefs"][1]
    store = Store(kit.root / "cohort-parents", existing=True)
    try:
        parent = Ingestor(store, Authority(kit.registry_path)).export(Export.model_validate(
            kit.selector(**{k: parent_ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")})))
    finally:
        store.close()
    member = copy.deepcopy(projection["members"][0])
    member["parent"] = {**{k: parent_ref[k] for k in ("documentId", "rawVersion", "documentVersion")},
        **{k: parent["locatorMetadata"][k] for k in ("rawHash", "representationHash", "mappingHash", "parserProfile")},
        "sourceHash": parent["document"]["sourceHash"]}
    member["collectionReceiptSha256"] = second["collection"]["receipt"]["sha256"]
    rights["parentDocumentVersion"] = parent_ref["documentVersion"]
    pinned = kit.file("second-rights.json", json_bytes(rights))
    member["rightsReceipt"] = {"path": str(kit.inputs / pinned["file"]), "sha256": pinned["sha256"]}
    projection["members"].append(member)
    source = kit.registry["sources"][0]
    source["scopes"][0]["textProjection"] = projection
    kit.save_registry()
    first = execute(kit, cohort_manifest, state="cohort-projected")
    assert first["counts"]["textReady"] == 2
    assert len({ref["documentId"] for ref in first["documentRefs"]}) == 2
    assert projection["members"][0]["parent"]["rawHash"] == member["parent"]["rawHash"]
    reused = execute(kit, cohort_manifest, "again", 1, state="cohort-projected")
    assert reused["counts"]["reusedVersions"] == 2
    frozen = Registry.model_validate(kit.registry).sources[0]
    config = frozen.configuration(frozen.scopes[0])
    member["boundaryDecision"]["revision"] = "second-member-revised"
    kit.save_registry()
    changed = execute(kit, cohort_manifest, state="cohort-changed")
    assert all(a["documentVersion"] != b["documentVersion"] for a, b in zip(first["documentRefs"], changed["documentRefs"]))
    member["boundaryDecision"]["revision"] = "synthetic-pdf-1"
    source["grant"].update(revision="synthetic-send-2", allowedOperations=["read", "quote-display", "model-send"],
        purposes=["pipeline:extract"], recipients=["synthetic-recipient"])
    kit.save_registry()
    authority = Authority(kit.registry_path)
    authority.check("synthetic-source", "body", ("read",), config, purpose="pipeline:extract", recipient="synthetic-recipient")
    old = Registry.model_validate(original_registry).sources[0]
    with pytest.raises(IngestionFailure, match="scope_configuration_conflict"):
        authority.check("synthetic-source", "body", ("read",), old.configuration(old.scopes[0]),
            purpose="pipeline:extract", recipient="synthetic-recipient")
    for purpose, recipient in (("wrong", "synthetic-recipient"), ("pipeline:extract", "wrong")):
        with pytest.raises(IngestionFailure, match="source_purpose_or_recipient_denied"):
            authority.check("synthetic-source", "body", ("read",), config, purpose=purpose, recipient=recipient)
    source["grant"]["enabled"] = False
    kit.save_registry()
    with pytest.raises(IngestionFailure, match="source_unauthorized"):
        Authority(kit.registry_path).check("synthetic-source", "body", ("read",), config,
            purpose="pipeline:extract", recipient="synthetic-recipient")


@pytest.mark.parametrize("media,xpath", [("text/html", None), ("text/markdown", None), ("application/pdf", "/html/body")])
def test_pdf_projection_is_bound_to_native_pdf_page_sources(kit, media, xpath):
    from zoop_ai_pipeline.ingestion_contracts import PdfBodyProjection

    _, projection, _, _ = pdf_projection_fixture(kit)
    with pytest.raises(IngestionFailure, match="projection_media_unsupported"):
        parsers.prepare(b"not admitted", media, xpath, projection=PdfBodyProjection.model_validate(projection))
