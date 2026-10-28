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
