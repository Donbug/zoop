"""Consumer cohort views never become source authority or processing identity."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from overnight_inputs import encoded, file_pin, indexed_items, input_freshness, load, prepare_input_metadata, save, sha


@pytest.fixture
def private_item(tmp_path):
    root = tmp_path / "retained"
    root.mkdir()
    record = root / "private-news-fixture.json"
    record.write_bytes(b'{"fixture":"cohort metadata only; not an ingestion record"}\n')
    return {"sourceId": "foreign-editorial", "stateDir": str(root), "recordPath": str(record),
            "recordSha256": sha(record.read_bytes()), "privateId": "private-news-fixture", "planId": "old-plan"}


def unit_id(item):
    return sha(encoded(item))[:24]


def index_document(item, metadata=None):
    document = {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": [], "privateItems": [item]}
    if metadata is not None:
        document["itemFreshness"] = metadata
    return document


@pytest.mark.parametrize(("freshness", "day"), [("reused", None), ("fresh", "2026-10-28"),
                                                ("backfill", "2026-08-03"), ("unknown", None)])
def test_explicit_private_metadata_is_joined_without_changing_rows_or_preimages(tmp_path, private_item, freshness, day):
    path = tmp_path / "INDEX.json"
    declared = {private_item["recordPath"]: {"freshness": freshness, "publicationDay": day}}
    document = index_document(private_item, declared)
    save(path, document)
    before_index, before_record = file_pin(path), file_pin(private_item["recordPath"])
    original_row = encoded(private_item)
    immutable_unit = {"unitId": unit_id(private_item), "freshness": "unknown", "snapshot": {"revision": "same", "events": []},
                      "observation": {"documentId": "unchanged"}, "grant": {"grantId": "private-processing:unchanged", "revision": "a" * 64}}
    unit_preimage = encoded(immutable_unit)
    rows, metadata = indexed_items(path, with_metadata=True)
    assert rows == indexed_items(path) == [private_item]
    assert set(rows[0]) == {"sourceId", "stateDir", "recordPath", "recordSha256", "privateId", "planId"}
    assert metadata == declared
    view = prepare_input_metadata(rows[0], immutable_unit["unitId"], metadata, tmp_path / "owned")
    assert (view["freshness"], view["publicationDay"]) == (freshness, day)
    assert view["basis"] == "collection-index-item-freshness"
    assert view["schemaVersion"] == "zoop-private-input-metadata-1"
    assert view["unitId"] == unit_id(private_item)
    assert view["recordPath"] == private_item["recordPath"] and view["recordSha256"] == private_item["recordSha256"]
    proof = load(view["proofPath"])
    assert proof == {key: value for key, value in view.items() if key not in {"proofPath", "proofSha256"}}
    assert sha(Path(view["proofPath"]).read_bytes()) == view["proofSha256"]
    assert file_pin(path) == before_index and file_pin(private_item["recordPath"]) == before_record
    assert encoded(private_item) == original_row and encoded(rows[0]) == original_row
    assert encoded(immutable_unit) == unit_preimage
    assert sha(encoded(rows[0])) == sha(original_row)
    assert metadata == declared and load(path) == document


def test_missing_metadata_stays_unknown_without_order_or_record_date_inference(tmp_path, private_item):
    path = tmp_path / "INDEX.json"
    save(path, index_document(private_item))
    rows, metadata = indexed_items(path, with_metadata=True)
    assert metadata == {}
    view = prepare_input_metadata(rows[0], unit_id(rows[0]), metadata, tmp_path / "owned")
    assert view["freshness"] == "unknown" and view["publicationDay"] is None
    assert view["basis"] == "collection-index-item-freshness-absent"
    assert view["recordPath"] == private_item["recordPath"]


def test_native_freshness_remains_authoritative_and_has_no_private_overlay(tmp_path, private_item):
    native = {"sourceId": "foreign-native", "exportPath": "/not-opened/export.json", "freshness": "backfill"}
    document = index_document(private_item, {native["exportPath"]: {"freshness": "fresh", "publicationDay": "2026-10-28"}})
    document["nativeItems"] = [native]
    path = tmp_path / "INDEX.json"
    save(path, document)
    rows, metadata = indexed_items(path, with_metadata=True)
    assert rows[0] == native and input_freshness(rows[0]) == "backfill"
    assert prepare_input_metadata(native, "existing-native-unit", metadata, tmp_path / "owned") is None
    assert not (tmp_path / "owned").exists()


@pytest.mark.parametrize("declared", [None, {}, {"freshness": "fresh"},
    {"freshness": "invented", "publicationDay": "2026-10-28"},
    {"freshness": "fresh", "publicationDay": None}, {"freshness": "backfill", "publicationDay": None},
    {"freshness": "fresh", "publicationDay": "2026-02-30"},
    {"freshness": "fresh", "publicationDay": "20261028"},
    {"freshness": "fresh", "publicationDay": "2026-10-28T00:00:00Z"},
    {"freshness": "fresh", "publicationDay": "2026-10-28", "derivedFromOrder": True}])
def test_invalid_selected_metadata_is_explicitly_refused_without_writing(tmp_path, private_item, declared):
    with pytest.raises(ValueError, match="collection_freshness"):
        prepare_input_metadata(private_item, unit_id(private_item), {private_item["recordPath"]: declared}, tmp_path / "owned")
    assert not (tmp_path / "owned").exists()


def test_metadata_proofs_are_idempotent_and_new_classifications_do_not_rewrite_old_proofs(tmp_path, private_item):
    root = tmp_path / "owned"
    first = prepare_input_metadata(private_item, unit_id(private_item), {}, root)
    first_pin = file_pin(first["proofPath"])
    assert prepare_input_metadata(private_item, unit_id(private_item), {}, root) == first
    assert file_pin(first["proofPath"]) == first_pin
    explicit = {private_item["recordPath"]: {"freshness": "reused", "publicationDay": None}}
    second = prepare_input_metadata(private_item, unit_id(private_item), explicit, root)
    assert second["proofPath"] != first["proofPath"]
    assert second["unitId"] == first["unitId"] and second["recordSha256"] == first["recordSha256"]
    assert file_pin(first["proofPath"]) == first_pin
    assert load(first["proofPath"])["freshness"] == "unknown" and load(second["proofPath"])["freshness"] == "reused"


def test_private_metadata_cannot_change_six_field_identity(tmp_path, private_item):
    original = copy.deepcopy(private_item)
    with pytest.raises(ValueError, match="collection_metadata_identity_invalid"):
        prepare_input_metadata(private_item, "different-unit", {}, tmp_path / "owned")
    with pytest.raises(ValueError, match="collection_metadata_identity_invalid"):
        prepare_input_metadata({**private_item, "freshness": "reused"}, unit_id(private_item), {}, tmp_path / "owned")
    assert private_item == original and not (tmp_path / "owned").exists()


def test_index_metadata_shape_is_checked_without_changing_default_row_contract(tmp_path, private_item):
    path = tmp_path / "INDEX.json"
    save(path, {**index_document(private_item), "itemFreshness": []})
    assert indexed_items(path) == [private_item]
    with pytest.raises(ValueError, match="collection_freshness_metadata_invalid"):
        indexed_items(path, with_metadata=True)
    assert indexed_items(tmp_path / "missing.json", with_metadata=True) == ([], {})
    assert indexed_items(tmp_path / "missing.json") == []
