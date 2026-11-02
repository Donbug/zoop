"""Private-origin, pre-read admission, and per-send revocation controls; no network."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts import overnight_history as history
from overnight_inputs import bind_execution, load, prepare_item, save
from tests.test_overnight_history import ACTOR, forbid_network, make_original, runtimes, world  # noqa: F401
from tests.test_private_processing import ACTOR as RETAINED_ACTOR, RUNTIMES, cli, retained_fixture
from zoop_ai_pipeline.extraction import Sources
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure, ObservationRef
from zoop_ai_pipeline.ingestion import Ingestor, Store
from zoop_ai_pipeline.ingestion_contracts import Run
from zoop_ai_pipeline.private_processing import PrivateAuthority


@pytest.mark.parametrize("require_store", [False, True])
def test_public_cli_refuses_private_imported_native_but_preserves_original_round(world, require_store):
    unit, item = world.units[0], world.items[0]
    request = {"schemaVersion": "zoop-ingestion-s2-1", **unit["observation"]}
    flags = ["--require-store"] if require_store else []
    refused = cli("ingestion", "export", request, "--state-dir", unit["ingestionStateDir"],
                  "--sources", unit["registry"], *flags, expected=2)
    assert refused == {"schemaVersion": "zoop-ingestion-s2-1", "error": {"code": "private_processing_not_public"}}
    original = load(item["exportPath"])
    request = {"schemaVersion": "zoop-ingestion-s2-1", **world.old_units[0]["observation"]}
    public = cli("ingestion", "export", request, "--state-dir", item["owningIngestionStateDir"],
                 "--sources", item["acquisitionRegistryPath"], *flags)
    assert public == original
    revised = load(item["acquisitionRegistryPath"])
    revised["revision"] = "legitimate-new-public-registry"
    revised["sources"][0]["grant"]["revision"] = "legitimate-new-public-grant"
    revised_path = world.root / "revised-public-registry.json"
    save(revised_path, revised)
    public_revised = cli("ingestion", "export", request, "--state-dir", item["owningIngestionStateDir"],
                         "--sources", revised_path, *flags)
    assert public_revised == {**original, "grant": {**original["grant"], "revision": "legitimate-new-public-grant"}}


@pytest.mark.parametrize("with_document", [False, True])
def test_public_cli_cannot_inspect_private_imported_native_round(world, with_document):
    unit = world.units[0]
    request = {"schemaVersion": "zoop-ingestion-s2-1", "roundId": unit["observation"]["roundId"], "sourceId": unit["sourceId"]}
    if with_document:
        request.update({key: unit["observation"][key] for key in ("documentId", "documentVersion")})
    refused = cli("ingestion", "inspect", request, "--state-dir", unit["ingestionStateDir"],
                  "--sources", unit["registry"], expected=2)
    assert refused["error"]["code"] == "private_processing_not_public"


@pytest.mark.parametrize("variant", ["native", "html", "markdown", "defuddle"])
def test_unknown_import_member_is_refused_before_original_artifact_open(world, tmp_path, monkeypatch, variant):
    if variant == "native":
        unit = world.old_units[0]
        import_path = Path(world.units[0]["history"]["proofPath"]).parent / "import.json"
        forbidden_names = {"a.html", "a-receipt.json"}
        identity_field = "candidateId"
    else:
        item = retained_fixture(tmp_path / ("retained-" + variant), variant)
        unit = prepare_item(item, tmp_path / "retained-owned", "authored-run", RUNTIMES, actor=RETAINED_ACTOR)
        import_path = Path(unit["export"]).parent / "import.json"
        forbidden_names = {item["privateId"] + suffix for suffix in (".raw", ".json", ".extraction.json")}
        identity_field = "privateId"
    authority_data = load(import_path)
    authority_data["members"][0]["input"][identity_field] = "another-authorized-member"
    changed_import = tmp_path / (variant + "-import.json")
    save(changed_import, authority_data)
    opened, original_open = [], os.open

    def observe(path, *args, **kwargs):
        if Path(path).name in forbidden_names:
            opened.append(Path(path).name)
        return original_open(path, *args, **kwargs)

    store = Store(tmp_path / (variant + "-new-ingestion"))
    try:
        with monkeypatch.context() as tracing:
            tracing.setattr(os, "open", observe)
            result = Ingestor(store, PrivateAuthority(changed_import)).run(
                Run.model_validate(unit["importRequest"]), Path(unit["importManifest"]))
        assert result["state"] == "incomplete"
        assert result["failure"]["code"] == "private_processing_member_unknown"
        assert result["counts"]["newRawVersions"] == result["counts"]["textReady"] == 0
        assert opened == [], "an unlisted input must be rejected before any original content or receipt is opened"
    finally:
        store.close()


@pytest.mark.parametrize("change", ["denied", "disabled", "registry-edit", "proof-edit", "receipt-edit"])
def test_next_send_rechecks_original_native_registry_and_proofs_without_controller(world, monkeypatch, change):
    from zoop_ai_pipeline.ingestion_contracts import IngestionFailure
    unit = bind_execution(world.units[0], {"setId": "revocation-test", "fundingPolicy": "zoop-set-funding-3"}, runtimes())
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_SET_ID", "revocation-test")
    authority = PrivateAuthority(Path(unit["privateProcessing"]))
    sources = Sources(Path(unit["ingestionStateDir"]), authority)
    ref = ObservationRef.model_validate(unit["observation"])
    runtime = runtimes()[0]
    pair = runtime.purpose("extract"), runtime.recipient("extract")
    sources.authorize_model_send(ref, *pair)
    original_path = Path(world.items[0]["acquisitionRegistryPath"])
    if change == "proof-edit":
        path = Path(world.items[0]["rightsProofPath"])
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "receipt-edit":
        original = load(world.items[0]["exportPath"])
        source = load(original_path)["sources"][0]
        path = Path(source["inputRoot"]) / original["observation"]["collection"]["receipt"]["file"]
        path.write_bytes(path.read_bytes() + b" ")
    else:
        registry = load(original_path)
        if change == "denied":
            registry["sources"][0]["grant"]["rights"] = "denied"
        elif change == "disabled":
            registry["sources"][0]["grant"]["enabled"] = False
        else:
            registry["revision"] += "-edited"
        save(original_path, registry)
    # Reuse the exact already-constructed authority, as a second physical send
    # would. No verify_item/verify_unit/controller redispatch intervenes.
    with pytest.raises((IngestionFailure, ExtractionFailure), match="private_processing_acquisition_changed|registry_changed|source_rights_denied|source_unauthorized"):
        authority.sending(*pair).check(unit["sourceId"], unit["scopeId"], ("read",))
        sources.authorize_model_send(ref, *pair)


def test_expired_original_operator_window_does_not_revoke_new_private_consent(tmp_path, monkeypatch):
    item, _ = make_original(tmp_path / "originals", "expired", tmp_path / "originals/native", monkeypatch)
    path = Path(item["acquisitionRegistryPath"])
    registry = load(path)
    registry["sources"][0]["grant"]["expiresAt"] = "2020-01-01T00:00:00+00:00"
    assert registry["sources"][0]["grant"]["purposes"] == registry["sources"][0]["grant"]["recipients"] == []
    assert "model-send" not in registry["sources"][0]["grant"]["allowedOperations"]
    save(path, registry)
    unit = prepare_item(item, tmp_path / "new-private-consent", "expired-control", runtimes(), actor=ACTOR)
    unit = history.prepare_groups([item], [unit], tmp_path / "new-private-consent", "expired-control", runtimes(), actor=ACTOR)[0]
    unit = bind_execution(unit, {"setId": "new-consent", "fundingPolicy": "zoop-set-funding-3"}, runtimes())
    monkeypatch.setenv("ZOOP_AI_PIPELINE_LIVE_SET_ID", "new-consent")
    runtime = runtimes()[0]
    Sources(Path(unit["ingestionStateDir"]), PrivateAuthority(Path(unit["privateProcessing"]))).authorize_model_send(
        ObservationRef.model_validate(unit["observation"]), runtime.purpose("extract"), runtime.recipient("extract"))
    assert load(path) == registry
