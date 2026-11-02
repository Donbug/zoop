"""Synthetic original HTTP bodies exercise opt-in EC representations and whole DOM units."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.collection_smoke import CollectionKit, LocalSite, ROBOTS
from scripts.ingestion_smoke import exact_check, json_bytes
from tests.test_ingestion import execute
from zoop_ai_pipeline import ingestion_parsers as parsers
from zoop_ai_pipeline.ingestion import Ingestor, Store
from zoop_ai_pipeline.ingestion_contracts import Authority, Export, IngestionFailure, Inspect, Item, byte_hash, digest

HTML = '<html><body><p>Retained 😀e\u0301 &amp; <b>inline</b> tail</p><p>EXCLUDED_BODY_SENTINEL</p><p>Final retained paragraph</p></body></html>'
RAW = json_bytes({"refCd": "IP/SYNTHETIC/1", "docuLanguageResource": {"language": "EN", "htmlContent": HTML},
                  "quote": "EXCLUDED_WRAPPER_SENTINEL"})
PATHS = ["/html/body/p[1]", "/html/body/p[3]"]
TEXT = "Retained 😀e\u0301 & inline tail\nFinal retained paragraph"
JSON_PROFILE = "eu-commission-json-html-body-ranges-1"
HTML_PROFILE = "eu-commission-html-body-ranges-1"


def collected_projection(root: Path, *, direct=False, raw: bytes | None = None, paths: list[str] | None = None):
    kit = CollectionKit(root)
    media = "text/html" if direct else "application/json"
    if raw is None:
        raw = HTML.encode() if direct else RAW
    if paths is None:
        paths = PATHS
    if not direct:
        kit.policy.update(allowedMediaTypes=["application/json"], jsonBodyProfile=JSON_PROFILE)
        kit.save_policy()
    site = LocalSite()
    try:
        site.route("/robots.txt", ROBOTS, content_type="text/plain")
        site.route("/document", raw, content_type=media)
        target = kit.target(site.url("/document"), "ec", supplier="synthetic-ec", published="2026-10-08",
                            publisher="Authored Synthetic Commission")
        collected = kit.collect("ec-body", [target])
        assert collected["state"] == "complete"
        assert all(entry["headers"]["accept-encoding"] == "identity" for entry in site.log)
        if not direct:
            assert all("application/json" in entry["headers"]["accept"] for entry in site.log)
    finally:
        site.close()
    manifest = Path(collected["manifestPath"])
    page = json.loads((kit.inputs / "collections/ec-body/page-0.json").read_bytes())
    item = Item.model_validate(page["items"][0])
    document = "doc-" + digest(["synthetic-source", "supplier", "synthetic-ec"])
    parent = {"documentId": document, "rawVersion": digest([document, byte_hash(raw), item.metadata()]),
              "rawHash": byte_hash(raw), "collectionReceiptSha256": item.collection.receipt.sha256}
    reviewed = parsers.review_html_body(raw, media, "/html/body", paths,
                **({} if direct else {"expected_reference": "IP/SYNTHETIC/1", "expected_language": "EN"}))
    representation = {**reviewed["baseline"], "parserProfile": reviewed["parserProfile"],
                      **(reviewed["representation"] or {})}
    binding = digest({"parent": parent, "representation": representation})
    evidence = kit.file("synthetic-rights-evidence.txt", b"Authored synthetic content owned for this local test")
    rights = {"schemaVersion": "zoop-eu-html-body-rights-1", "bodySha256": byte_hash(raw), "parentBindingHash": binding,
              "selectionHash": reviewed["selectionHash"], "license": "CC-BY-4.0-qualified-commission-content",
              "applicabilityAssessment": "Authored synthetic content only", "notice": "Synthetic rights notice",
              "attribution": "Synthetic Commission", "changesNotice": "Selected complete paragraphs",
              "evidence": [{"path": str(kit.inputs / evidence["file"]), "sha256": evidence["sha256"]}]}
    receipt = kit.file("synthetic-rights.json", json_bytes(rights))
    member = {"parent": parent, "representation": representation, "parentBindingHash": binding,
              "selectedUnits": reviewed["selectedUnits"],
              "rightsReceipt": {"path": str(kit.inputs / receipt["file"]), "sha256": receipt["sha256"]},
              "boundaryDecision": {"revision": "synthetic-review-1", "status": "approved",
                  "retainedScope": "selected-complete-commission-narrative-units", "selectionHash": reviewed["selectionHash"],
                  "evidence": ["Synthetic owner reviewed these two complete paragraphs"]}}
    projection = {"profile": HTML_PROFILE if direct else JSON_PROFILE, "members": [member]}
    scope = kit.registry["sources"][0]["scopes"][0]
    scope.update(articleXPath="/html/body", textProjection=projection)
    kit.save_registry()
    return kit, manifest, projection, raw


def exported(kit, result, state="state"):
    ref = result["documentRefs"][0]
    store = Store(kit.root / state, existing=True)
    try:
        return Ingestor(store, Authority(kit.registry_path)).export(Export.model_validate(kit.export_selector("round-1", ref)))
    finally:
        store.close()


@pytest.mark.parametrize("direct", [False, True])
def test_original_collected_body_produces_exact_selected_dom_spans_and_barriers(tmp_path, direct):
    kit, manifest, projection, raw = collected_projection(tmp_path / "source", direct=direct)
    result = execute(kit, manifest)
    assert result["counts"]["textReady"] == 1
    value = exported(kit, result)
    doc, metadata = value["document"], value["locatorMetadata"]
    assert doc["text"] == TEXT
    assert value["observation"]["collection"]["published"]["date"] == "2026-10-08"
    assert metadata["rawArtifactId"] == "raw-" + byte_hash(raw)
    assert metadata["textProjection"]["parent"] == projection["members"][0]["parent"]
    exact_check(doc, 0, doc["rawLocators"][0]["end"])
    exact_check(doc, 0, len(TEXT), False)
    store = Store(kit.root / "state", existing=True)
    try:
        assert store.one("SELECT data FROM blobs WHERE hash=?", (byte_hash(raw),))["data"] == raw
        runner = Ingestor(store, Authority(kit.registry_path))
        loc = doc["rawLocators"][0]
        resolved = runner.inspect(Inspect.model_validate(kit.selector(documentId=doc["documentId"],
            documentVersion=doc["documentVersion"], locatorId=loc["locatorId"], start=0, end=loc["end"])))["resolvedLocator"]
        assert "".join(span["text"] for span in resolved["segments"]) == TEXT[:loc["end"]]
        assert resolved["segments"][0]["domPath"] == PATHS[0]
        if not direct:
            assert all(span["rawHash"] == byte_hash(raw) and span["jsonPointer"] == "/docuLanguageResource/htmlContent"
                       for span in resolved["segments"])
            assert metadata["textProjection"]["representation"]["expectedLanguage"] == "EN"
    finally:
        store.close()


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}',
    b'{"x":"\\ud800"}', b'[]', b'{"docuLanguageResource":{"htmlContent":3}}',
    b'{"docuLanguageResource":{"language":"EN","htmlContent":"x","htmlContent":"y"},"refCd":"IP/SYNTHETIC/1"}'])
def test_strict_json_review_refuses_ambiguous_or_non_unicode_representations(raw):
    with pytest.raises(IngestionFailure):
        parsers.review_html_body(raw, "application/json", "/html/body", PATHS,
                                expected_reference="IP/SYNTHETIC/1", expected_language="EN")


@pytest.mark.parametrize("reference,language", [("wrong", "EN"), ("IP/SYNTHETIC/1", "FR")])
def test_json_member_reference_and_language_are_exact(reference, language):
    with pytest.raises(IngestionFailure, match="projection_reference_or_language_mismatch"):
        parsers.review_html_body(RAW, "application/json", "/html/body", PATHS,
                                expected_reference=reference, expected_language=language)


@pytest.mark.parametrize("fault,code", [("proposal", "projection_boundary_review_required"), ("hold", "projection_boundary_review_required"),
    ("partial", "projection_whole_positive_unit_required"), ("reverse", "projection_disjoint_source_order_required"),
    ("decoded", "projection_representation_mismatch"), ("baseline", "projection_parent_mismatch"),
    ("rights", "projection_rights_receipt_hash_mismatch"), ("receipt", "projection_collection_receipt_mismatch")])
def test_unapproved_or_changed_boundaries_hold_without_preparing_excluded_content(tmp_path, fault, code):
    kit, manifest, projection, _ = collected_projection(tmp_path / "source")
    member = projection["members"][0]
    if fault in {"proposal", "hold"}:
        member["boundaryDecision"]["status"] = fault
    elif fault == "partial":
        member["selectedUnits"][0]["spans"][0]["sourceEnd"] -= 1
    elif fault == "reverse":
        member["selectedUnits"].reverse()
    elif fault == "decoded":
        member["representation"]["decodedHtmlUtf8Sha256"] = "0" * 64
    elif fault == "baseline":
        member["representation"]["sourceHash"] = "0" * 64
    elif fault == "rights":
        member["rightsReceipt"]["sha256"] = "0" * 64
    else:
        member["parent"]["collectionReceiptSha256"] = "0" * 64
    member["parentBindingHash"] = digest({"parent": member["parent"], "representation": member["representation"]})
    member["boundaryDecision"]["selectionHash"] = digest(member["selectedUnits"])
    if fault in {"partial", "reverse", "decoded", "baseline"}:
        path = Path(member["rightsReceipt"]["path"])
        rights = json.loads(path.read_bytes())
        rights.update(parentBindingHash=member["parentBindingHash"], selectionHash=member["boundaryDecision"]["selectionHash"])
        path.write_bytes(json_bytes(rights))
        member["rightsReceipt"]["sha256"] = byte_hash(path.read_bytes())
    kit.save_registry()
    result = execute(kit, manifest)
    assert result["counts"]["textReady"] == 0 and result["documentRefs"][0]["hold"] == code


@pytest.mark.parametrize("grant", [{"enabled": False}, {"rights": "denied"}, {"rights": "unknown"},
                                   {"expiresAt": "2000-01-01T00:00:00+00:00"}])
def test_current_authority_denies_existing_projected_versions(tmp_path, grant):
    kit, manifest, _, _ = collected_projection(tmp_path / "source")
    result = execute(kit, manifest)
    kit.registry["sources"][0]["grant"].update(grant)
    kit.save_registry()
    with pytest.raises(IngestionFailure, match="source_unauthorized"):
        exported(kit, result)


def test_whole_unit_review_refuses_unsafe_children_and_source_order():
    for html, paths, code in [(b'<p>Safe<script>bad</script>tail</p>', ["/html/body/p"], "projection_unsafe_unit"),
                              (HTML.encode(), PATHS[::-1], "projection_disjoint_source_order_required")]:
        with pytest.raises(IngestionFailure, match=code):
            parsers.review_html_body(html, "text/html", "/html/body", paths)


def test_json_without_selected_profile_is_not_prepared():
    with pytest.raises(IngestionFailure, match="media_type_unsupported"):
        parsers.prepare(RAW, "application/json", "/html/body")


@pytest.mark.parametrize("output_contract", [None, "citation-enum-1"])
def test_projected_generation_and_verifier_payloads_contain_only_selected_body(tmp_path, monkeypatch, output_contract):
    from tests.live_support import PAYLOADS, article, environment
    from zoop_ai_pipeline import live_runtime
    from zoop_ai_pipeline.live_runtime import LiveRuntime

    kit, manifest, _, _ = collected_projection(tmp_path / "source")
    value = exported(kit, execute(kit, manifest))
    doc = value["document"]
    native = article(doc["text"]).model_copy(update={"article_id": doc["documentId"]})
    citation = {"documentId": doc["documentId"], "documentVersion": doc["documentVersion"],
        "article_id": native.article_id, "article_version": native.version, "text": doc["text"],
        "mapped": [[r["start"], r["end"]] for r in doc["rawLocators"]]}
    quote = {"quoteId": "ev-a", "documentId": doc["documentId"], "documentVersion": doc["documentVersion"],
        "start": 0, "end": doc["rawLocators"][0]["end"], "text": doc["text"][:doc["rawLocators"][0]["end"]]}
    environment(monkeypatch, tmp_path, **{live_runtime.OPENAI_KEY_VAR: None, live_runtime.JEV_KEY_VAR: None,
                                        live_runtime.OUTPUT_VAR: output_contract})
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
        body = json_bytes(runtime.prepare(stage, payload)["body"])
        assert "Retained 😀e\u0301 & inline tail".encode() in body, stage
        assert b"EXCLUDED_BODY_SENTINEL" not in body and b"EXCLUDED_WRAPPER_SENTINEL" not in body, stage


@pytest.mark.parametrize("fault,code", [("raw", "projection_parent_mismatch"), ("media", "projection_media_unsupported")])
def test_json_projection_rejects_changed_original_bytes_or_media(tmp_path, fault, code):
    from zoop_ai_pipeline.ingestion_contracts import JsonHtmlBodyProjection

    kit, _, descriptor, raw = collected_projection(tmp_path / "source")
    projection = JsonHtmlBodyProjection.model_validate(descriptor)
    with pytest.raises(IngestionFailure, match=code):
        parsers.prepare(raw + b" " if fault == "raw" else raw,
            "text/html" if fault == "media" else "application/json", "/html/body",
            projection=projection, html_member=projection.members[0])


def test_json_collection_retains_the_identity_encoding_requirement(tmp_path):
    kit = CollectionKit(tmp_path / "source")
    kit.policy.update(allowedMediaTypes=["application/json"], jsonBodyProfile=JSON_PROFILE)
    kit.save_policy()
    site = LocalSite()
    try:
        site.route("/robots.txt", ROBOTS, content_type="text/plain")
        site.route("/compressed", RAW, content_type="application/json", headers={"Content-Encoding": "gzip"})
        result = kit.collect("compressed", [kit.target(site.url("/compressed"), "ec")], expected=2)
        assert result["state"] == "failed"
        assert result["targets"][0]["code"] == "content_encoding"
    finally:
        site.close()


@pytest.mark.parametrize("paths", [
    ["/html/body/ul/li", "/html/body/ul/li/ul/li"],
    ["/html/body/ul/li/ul/li", "/html/body/ul/li"],
    ["/html/body/ul/li", "/html/body/ul/li"],
])
def test_whole_unit_selection_rejects_nested_or_duplicate_roots(paths):
    with pytest.raises(IngestionFailure, match="projection_disjoint_source_order_required"):
        parsers.review_html_body(b"<ul><li>Outer<ul><li>Inner</li></ul>After</li></ul>",
                                 "text/html", "/html/body", paths)


def test_whole_unit_selection_follows_rendered_order_with_descendants_and_tails():
    reviewed = parsers.review_html_body(
        b"<ul><li>Outer<ul><li>Inner</li></ul>After</li><li>Final</li></ul>",
        "text/html", "/html/body", ["/html/body/ul/li[1]", "/html/body/ul/li[2]"])
    assert reviewed["text"] == "Outer\nInner\nAfter\nFinal"


def test_native_projection_copies_only_approved_trimmed_source_intervals(tmp_path):
    paths = ["/html/body/p[1]", "/html/body/p[2]"]
    kit, manifest, _, _ = collected_projection(tmp_path / "source", direct=True,
        raw=b"<p>A </p><p> B</p>", paths=paths)
    value = exported(kit, execute(kit, manifest))
    doc = value["document"]
    assert doc["text"] == "A\nB"
    approved = [span for unit in value["locatorMetadata"]["textProjection"]["retainedUnits"] for span in unit["spans"]]
    assert [(span["sourceStart"], span["sourceEnd"]) for span in approved] == [(0, 1), (1, 2)]
    store = Store(kit.root / "state", existing=True)
    try:
        runner = Ingestor(store, Authority(kit.registry_path))
        for locator in doc["rawLocators"]:
            resolved = runner.inspect(Inspect.model_validate(kit.selector(documentId=doc["documentId"],
                documentVersion=doc["documentVersion"], locatorId=locator["locatorId"],
                start=locator["start"], end=locator["end"])))["resolvedLocator"]
            for segment in resolved["segments"]:
                assert any(segment["domPath"] == span["domPath"] and segment["slot"] == span["slot"]
                    and span["sourceStart"] <= segment["sourceStart"] < segment["sourceEnd"] <= span["sourceEnd"]
                    for span in approved)
    finally:
        store.close()
