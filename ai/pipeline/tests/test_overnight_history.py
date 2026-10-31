"""Native LIVE history controls with authored acquisition/HTTP responses, no network.

The provider peer alone is httpx.MockTransport; native requests, grants, budgets,
receipts, decoding, candidate states and history admission are real. Fixtures
author the external-source wire shape and do not claim actual KOGL acquisition
or real-model quality. Every control ledger stays outside the real nightly run.
"""
from __future__ import annotations

import copy
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE / "scripts"))
from scripts import overnight_history as history
from overnight_inputs import bind_execution, encoded, file_pin, load, prepare_item, save, sha
from tests.live_support import environment, openai_reply
from zoop_ai_pipeline import extraction_replay as analysis, ingestion, live_runtime as live
from zoop_ai_pipeline.extraction import Extractor, Fixtures, LiveAccess, Sources, Store as ExtractionStore
from zoop_ai_pipeline.extraction_contracts import Catalogue, Submit
from zoop_ai_pipeline.ingestion import Ingestor, Store
from zoop_ai_pipeline.ingestion_contracts import Authority, Export, Run
from zoop_ai_pipeline.live_runtime import LiveRuntime
from zoop_ai_pipeline.private_processing import PrivateAuthority

CATALOGUE = {"revision": "authored-history-1", "companies": [
    {"companyId": "SYNTH-1", "name": "합성기업", "aliases": [], "ticker": None}]}
PROMPT = "authored-history-1"
VERSION = "authored-history-analysis-1"
QUOTE = "합성기업은 2026년 3분기 공급 계약을 발표했다."
ACTOR = {"kind": "user-private-experiment", "acceptedBy": "Main", "decidedAt": "2026-10-28T00:00:00+00:00",
         "statement": "Synthetic offline authorization fixture only; no real source collection or model spending."}


def runtimes():
    return [LiveRuntime.from_env()]


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path / "control/offline-verification",
                **{live.PROFILE_VAR: None, live.RUN_ID_VAR: None, live.NOT_AFTER_VAR: None,
                   live.MAX_USD_VAR: "10", live.MAX_CALLS_VAR: "100"})
    def forbidden(*args, **kwargs):
        raise AssertionError("history tests must not use network")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def make_original(root, name, input_root, monkeypatch, *, scope=None, hosts=None, selection=None):
    """Ordinary native ingestion into independent original stores under old grants."""
    directory = root / name
    directory.mkdir(parents=True)
    input_root.mkdir(parents=True, exist_ok=True)
    scope = scope or name
    url = "https://www.korea.kr/news/" + name
    body = ("<html><body><article><p>" + QUOTE + "</p><p>" + name + "</p></article></body></html>").encode()
    body_path = input_root / (name + ".html")
    body_path.write_bytes(body)
    grant = {"grantId": "original-acquisition-" + name, "revision": "original-1", "sourceId": "korea-portal",
             "enabled": True, "rights": "known", "allowedOperations": ["read", "store", "quote-display"],
             "recipients": [], "purposes": [], "evidence": ["authored fixture, not a real license decision"], "expiresAt": None}
    source = {"sourceId": "korea-portal", "adapter": "collected-http", "inputRoot": str(input_root),
              "allowedHosts": hosts or ["www.korea.kr", "m.korea.kr"], "grant": grant,
              "scopes": [{"scopeId": scope, "selection": selection or "verbatim authored scope " + name,
                          "initialCursor": None, "articleXPath": "//article", "timestampLimitations": ["authored day only"]}]}
    registry_path = directory / "sources.json"
    save(registry_path, {"schemaVersion": "zoop-ingestion-s2-1", "revision": "original-1", "sources": [source]})
    receipt = {"schemaVersion": "zoop-collection-receipt-1", "collectionId": name, "sourceId": "korea-portal", "scopeId": scope,
               "candidateId": name, "grantId": grant["grantId"], "grantRevision": grant["revision"],
               "requestedUrl": url, "finalUrl": url, "redirects": [], "httpStatus": 200, "contentType": "text/html",
               "mediaType": "text/html", "contentLength": str(len(body)), "etag": None, "lastModified": None, "serverDate": None,
               "bodySha256": sha(body), "bodyBytes": len(body), "fetchedAt": "2026-10-08T00:00:00+00:00",
               "userAgent": "authored-history-fixture", "network": "external", "robots": [], "requestCount": 1}
    receipt_path = input_root / (name + "-receipt.json")
    save(receipt_path, receipt)
    collection = {"provenance": "collected_http", "collectionId": name,
                  "receipt": {"file": receipt_path.name, "sha256": sha(receipt_path.read_bytes())},
                  "fetchedAt": receipt["fetchedAt"], "finalUrl": url, "httpStatus": 200, "contentType": "text/html",
                  "bodySha256": sha(body), "documentKind": "news", "network": "external",
                  "published": {"raw": "2026-10-08", "precision": "day", "date": "2026-10-08", "basis": "authored day"}}
    candidate = {"candidateId": name, "supplierDocumentId": name, "url": url, "bodyRef": "body", "mediaType": "text/html",
                 "title": "Authored history " + name, "publishedAt": None, "modifiedAt": None, "sourceRevision": None, "collection": collection}
    page = input_root / (name + "-page.json")
    save(page, {"items": [candidate], "more": False, "nextCursor": None})
    manifest_path = directory / "manifest.json"
    save(manifest_path, {"schemaVersion": "zoop-ingestion-s2-1", "sourceId": "korea-portal", "scopeId": scope,
                        "pages": [{"pageId": "page-" + name, "cursor": None, "response": {"file": page.name, "sha256": sha(page.read_bytes())},
                                   "status": "ok", "nextCursor": None, "terminal": True, "coverageThrough": None}],
                        "documents": {"body": {"file": body_path.name, "sha256": sha(body)}}})
    request = {"schemaVersion": "zoop-ingestion-s2-1", "roundId": "original-" + name, "sourceId": "korea-portal", "scopeId": scope,
               "window": None, "checkpointRevision": 0, "fixtureManifestHash": sha(manifest_path.read_bytes()), "cleanerVersion": "exact-copy-1"}
    store = Store(directory / "ingestion")
    try:
        with monkeypatch.context() as clock:
            clock.setattr(ingestion, "now", lambda: "2026-10-08T01:00:00+00:00")
            result = Ingestor(store, Authority(registry_path)).run(Run.model_validate(request), manifest_path)
        assert result["state"] == "complete", result
        ref = {"roundId": request["roundId"], "sourceId": "korea-portal",
               **{key: result["documentRefs"][0][key] for key in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
        exported = Ingestor(store, Authority(registry_path)).export(Export.model_validate({"schemaVersion": "zoop-ingestion-s2-1", **ref}))
    finally:
        store.close()
    export_path, rights_path = directory / "export.json", directory / "rights.json"
    save(export_path, exported)
    save(rights_path, {"license": "KOGL-type-1-text-only", "bodySha256": sha(body)})
    item = {"sourceId": "korea-portal", "sourceScopeId": scope, "owningIngestionStateDir": str(directory / "ingestion"),
            "acquisitionRegistryPath": str(registry_path), "rightsProofPath": str(rights_path), "exportPath": str(export_path),
            "acquisitionManifestPath": str(manifest_path), "freshness": "reused"}
    unit = prepare_item(item, root.parent / "control/offline-verification", "authored-run", runtimes(), actor=ACTOR)
    return item, unit


@pytest.fixture
def world(tmp_path, monkeypatch):
    originals = tmp_path / "originals"
    pairs = [make_original(originals, name, originals / "native", monkeypatch) for name in ("a", "b", "c")]
    items, old_units = [p[0] for p in pairs], [p[1] for p in pairs]
    before = {str(path): file_pin(path) for path in originals.rglob("*") if path.is_file()}
    units = history.prepare_groups(items, old_units, tmp_path / "control/offline-verification", "authored-run", runtimes(), actor=ACTOR)
    return SimpleNamespace(root=tmp_path, originals=originals, items=items, old_units=old_units, units=units, before=before, monkeypatch=monkeypatch)


def author_mention(unit, ident="m1", *, background=False):
    article = analysis.article(load(unit["export"]), False)
    start = article.body.index(QUOTE)
    mention = {"mention_id": ident, "article_id": article.article_id, "article_version": article.version,
               "title": "Authored supply contract", "event_type": "supply_contract", "action": "announced", "target": "supply contract",
               "event_time": None, "period": "2026Q3", "assertion_status": "announced",
               "participants": [{"company_id": "SYNTH-1", "name": "합성기업", "role": "issuer"}],
               "evidence": [{"article_id": article.article_id, "article_version": article.version, "start": start, "end": start + len(QUOTE), "quote": QUOTE}],
               "keywords": [], "background": background, "countries": []}
    return article, mention


def run_s2(world, index, job, *, relation="DIFFERENT", mentions=None, topic=False, complete_topic=True, catalogue=None, replay=False):
    """Real native LIVE adapter; the authored HTTP peer is the only replacement."""
    unit = world.units[index]
    catalogue = catalogue or CATALOGUE
    frozen = history.snapshot_for(unit, catalogue)
    unit = bind_execution(frozen["unit"], {"setId": "test-" + job, "fundingPolicy": "zoop-set-funding-3"}, runtimes())
    world.monkeypatch.setenv(live.SET_ID_VAR, "test-" + job)
    article, mention = author_mention(unit)
    mentions = [mention] if mentions is None else mentions
    members = {event["eventId"]: event["members"][0]["mention"] for event in frozen["snapshot"]["events"]}
    stages = []

    def handler(request):
        assert request.url.host == "api.openai.com"
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        stage, projection = payload["stage"], payload["input"]
        stages.append(stage)
        if stage == "extract":
            answer = {"mentions": mentions}
        elif stage == "compare":
            answer = {"relation": relation, "reason": "authored transport control; not model quality or gold",
                      "evidence": projection["mention"]["evidence"] + members[projection["issue"]["issue_id"]]["evidence"]}
        elif stage == "topic":
            answer = ({"schemaVersion": "zoop-topic-response-1", "producerVersion": "zoop-topic-replay-producer-1", "topics": []}
                      if complete_topic else "deliberately invalid topic response")
        else:
            raise AssertionError(stage)
        return httpx.Response(200, json=openai_reply(answer))

    def from_env(need_send=False):
        runtime = LiveRuntime.from_env(need_send=need_send, transport=httpx.MockTransport(handler))
        PrivateAuthority(Path(unit["privateProcessing"])).check_runtime(runtime.binding())
        return runtime

    fixtures = Fixtures(None, None)
    provenance = {"sourceKind": "actual", "executionMode": "live", "recordingKind": "provider"}
    if replay:
        assert not frozen["snapshot"]["events"] and not topic
        fixture = {"format": "zoop-analysis-replay-1", "synthetic": False, "recordingKind": "authored-test",
                   "promptVersion": PROMPT, "analysisVersion": VERSION, "records": [
                       {"stage": "extract", "requestDigest": analysis.request_digest(
                           "extract", analysis.extract_input(article, PROMPT, Catalogue.model_validate(catalogue)), VERSION),
                        "response": {"mentions": mentions}}]}
        fixtures = Fixtures(encoded(fixture), None)
        provenance = {"sourceKind": "actual", "executionMode": "replay", "recordingKind": "authored-test"}
    request = {"schemaVersion": "zoop-extraction-s2-2", "jobId": job, "provenance": provenance,
               "promptVersion": PROMPT, "incoming": unit["observation"], "catalogue": catalogue, "snapshot": frozen["snapshot"],
               "topic": {"producerVersion": "zoop-topic-replay-producer-1"} if topic else None}
    extraction_dir = world.root / "control/offline-verification/s2" / job
    store = ExtractionStore(extraction_dir, Path(unit["ingestionStateDir"]))
    try:
        extractor = Extractor(store, Sources(Path(unit["ingestionStateDir"]), PrivateAuthority(Path(unit["privateProcessing"]))),
                              LiveAccess(from_env=from_env))
        result = extractor.run(Submit.model_validate(request), fixtures)
    finally:
        store.close()
    if not hasattr(world, "provider_stages"):
        world.provider_stages = {}
    world.provider_stages[job] = stages
    return result, extraction_dir, frozen


def test_shared_native_ingestion_preserves_acquisition_and_freezes_all_scopes(world):
    assert len({u["ingestionStateDir"] for u in world.units}) == 1
    assert len({u["registrySha256"] for u in world.units}) == 1
    registry = load(world.units[0]["registry"])
    assert registry["sources"][0]["scopes"] == [load(item["acquisitionRegistryPath"])["sources"][0]["scopes"][0] for item in world.items]
    assert registry["sources"][0]["grant"]["expiresAt"] is None
    for item, old, unit in zip(world.items, world.old_units, world.units):
        assert unit["proofPath"] == old["proofPath"] and unit["freshness"] == "reused"
        assert unit["originalObservation"] == old["observation"]
        assert unit["observation"]["roundId"] != old["observation"]["roundId"]
        fresh, original = load(unit["export"]), load(old["export"])
        assert fresh["document"] == original["document"]
        assert fresh["locatorMetadata"] == original["locatorMetadata"]
        assert fresh["observation"]["collection"] == original["observation"]["collection"]
        assert fresh["observation"]["publishedAt"] is None
        assert fresh["observation"]["observedAt"] > original["observation"]["observedAt"]
        assert unit["reingestion"]["acquisitionGrant"] == load(item["exportPath"])["grant"]
        assert fresh["grant"]["grantId"].startswith("private-processing:")
        assert (Path(unit["history"]["proofPath"]).parent / "original-manifest.json").read_bytes() == Path(item["acquisitionManifestPath"]).read_bytes()
        store = Store(Path(unit["ingestionStateDir"]), existing=True)
        try:
            saved = store.one("SELECT registry_hash FROM rounds WHERE id=?", (unit["observation"]["roundId"],))
            import_path = Path(unit["history"]["proofPath"]).parent / "import.json"
            assert saved["registry_hash"] == sha(import_path.read_bytes())
            assert load(import_path)["registry"]["sha256"] == sha(Path(item["acquisitionRegistryPath"]).read_bytes())
        finally:
            store.close()
        history.verify_unit(unit)
    assert {str(path): file_pin(path) for path in world.originals.rglob("*") if path.is_file()} == world.before
    assert history.prepare_groups(world.items, world.old_units, world.root / "control/offline-verification", "authored-run", runtimes(), actor=ACTOR) == world.units


@pytest.mark.parametrize("relation", ["SAME", "DIFFERENT", "FOLLOWS", "CONFLICT", "HOLD"])
def test_actual_ready_a_is_b_native_snapshot_and_all_comparison_outcomes_survive(world, relation):
    a, a_state, empty = run_s2(world, 0, "a", topic=True)
    assert a["state"] == "ready" and empty["snapshot"]["events"] == []
    assert a["counts"]["comparisons"] == 0
    history.record_ready(world.units[0], a, CATALOGUE, a_state)
    b, b_state, frozen = run_s2(world, 1, "b", relation=relation, topic=True)
    assert b["state"] == "ready", b
    assert b["stages"]["topic"]["status"] == "complete"
    assert b["counts"]["comparisons"] == 1
    assert [c["stage"] for c in b["calls"]].count("compare") == 1
    assert b["provenance"] == {"sourceKind": "actual", "executionMode": "live", "recordingKind": "provider"}
    assert b["usage"]["providerCalls"] == 3 and b["usage"]["replayCalls"] == 0
    assert world.provider_stages["b"] == ["extract", "compare", "topic"]
    event = frozen["snapshot"]["events"][0]
    assert event["members"] == [{"observation": world.units[0]["observation"], "mention": a["eventCandidates"][0]["mention"]}]
    mapping = frozen["canonicalMappings"][event["eventId"]]
    assert mapping["eventCandidateId"] == a["eventCandidates"][0]["eventCandidateId"]
    assert mapping["canonicalId"] == "private-event-" + sha(encoded({"upstream": {"jobId": a["jobId"], "inputDigest": a["inputDigest"]}, "ref": mapping["eventCandidateId"]}))
    candidate = b["eventCandidates"][0]
    assert candidate["comparisons"][0]["original"]["relation"] == relation
    assert candidate["comparisons"][0]["effective"]["relation"] == relation
    assert candidate["approved"] is False
    record = history.record_ready(world.units[1], b, CATALOGUE, b_state)
    assert record["eligibleCandidates"] == (0 if relation in {"HOLD", "CONFLICT"} else 1)
    for unit in world.units:
        history.verify_unit(unit)
    assert {str(path): file_pin(path) for path in world.originals.rglob("*") if path.is_file()} == world.before


def test_nonready_forged_and_foreign_catalogue_results_never_enter_history(world):
    pending, state, _ = run_s2(world, 0, "pending", topic=True, complete_topic=False)
    with pytest.raises(ValueError, match="history_s2_not_ready_current"):
        history.record_ready(world.units[0], pending, CATALOGUE, state)
    a, state, _ = run_s2(world, 0, "ready")
    forged = copy.deepcopy(a)
    forged["eventCandidates"][0]["mention"]["title"] = "caller forged candidate"
    with pytest.raises(ValueError, match="history_s2_result_mismatch"):
        history.record_ready(world.units[0], forged, CATALOGUE, state)
    with pytest.raises(ValueError, match="history_s2_binding_mismatch"):
        history.record_ready(world.units[0], a, {**CATALOGUE, "revision": "other"}, state)
    history.record_ready(world.units[0], a, CATALOGUE, state)
    different = history.snapshot_for(world.units[1], {**CATALOGUE, "revision": "other"})
    assert different["snapshot"]["events"] == []
    assert different["coverage"]["excluded"] == {"different-catalogue": 1}
    same_document = history.snapshot_for(world.units[0], CATALOGUE)
    assert same_document["snapshot"]["events"] == []
    assert same_document["coverage"]["excluded"]["incoming-document-version"] == 1


def test_history_is_deterministic_bounded_candidate_coverage_not_merged_gold(world):
    mentions = [author_mention(world.units[0], "mention-" + str(n))[1] for n in range(23)]
    article, rejected_mention = author_mention(world.units[0], "unmapped")
    # Exact clean-text evidence crosses a generated paragraph separator. Native
    # parsing accepts the same article/mention identity; raw mapping rejects it.
    assert "\n" in article.body
    rejected_mention["evidence"] = [{"article_id": article.article_id, "article_version": article.version,
                                   "start": 0, "end": len(article.body), "quote": article.body}]
    mentions.append(rejected_mention)
    a, state, _ = run_s2(world, 0, "a-many", mentions=mentions)
    assert a["state"] == "ready"
    rejected = next(c for c in a["eventCandidates"] if c["localMentionId"] == "unmapped")
    assert rejected["mention"]["mention_id"] == rejected["localMentionId"]
    assert rejected["state"] == "rejected" and rejected["reason"] == "raw_locator_mismatch" and rejected["citations"] == []
    assert a["counts"]["eventCandidates"] == {"total": 24, "candidate": 23, "rejected": 1}
    receipt = history.record_ready(world.units[0], a, CATALOGUE, state)
    assert receipt["eligibleCandidates"] == 23 and receipt["excluded"] == {"rejected-candidate": 1}
    frozen = history.snapshot_for(world.units[1], CATALOGUE)
    assert frozen == history.snapshot_for(world.units[1], CATALOGUE)
    assert frozen["coverage"]["selectedEvents"] == frozen["coverage"]["selectedMembers"] == 8
    assert frozen["coverage"]["examinedPriorCandidates"] == 24
    assert frozen["coverage"]["eligibleHistoryTotal"] == 23
    assert frozen["coverage"]["excluded"] == {"bounded-coverage": 15, "rejected-candidate": 1}
    manifest = load(Path(world.units[0]["history"]["directory"]) / "group.json")
    assert manifest["historyLimits"] == {"maxEvents": 8, "maxMembersTotal": 20, "membersPerEvent": 1}
    assert all(len(event["members"]) == 1 for event in frozen["snapshot"]["events"])
    selected = [entry["eventCandidateId"] for entry in frozen["coverage"]["selected"]]
    assert selected == sorted(c["eventCandidateId"] for c in a["eventCandidates"] if c["state"] == "candidate")[:8]
    assert len(history.snapshot_for(world.units[1], CATALOGUE, max_events=2, max_members=3)["snapshot"]["events"]) == 2
    with pytest.raises(ValueError, match="history_limits_invalid"):
        history.snapshot_for(world.units[1], CATALOGUE, max_members=21)
    with pytest.raises(ValueError, match="history_limits_invalid"):
        history.snapshot_for(world.units[1], CATALOGUE, max_events=9)


def test_changed_prior_source_and_cancelled_job_are_excluded_without_invented_history(world):
    a, state, _ = run_s2(world, 0, "a")
    history.record_ready(world.units[0], a, CATALOGUE, state)
    old_export = Path(world.items[0]["exportPath"])
    raw = old_export.read_bytes()
    old_export.write_bytes(raw + b" ")
    changed = history.snapshot_for(world.units[1], CATALOGUE)
    assert changed["snapshot"]["events"] == []
    assert changed["coverage"]["excluded"] == {"prior-not-current-or-invalid": 1}
    # Native ready jobs cannot be cancelled; cancel a genuinely pending topic job.
    c, c_state, _ = run_s2(world, 2, "c", topic=True, complete_topic=False)
    store = ExtractionStore(c_state, Path(world.units[2]["ingestionStateDir"]))
    try:
        cancelled = Extractor(store, Sources(Path(world.units[2]["ingestionStateDir"]), PrivateAuthority(Path(world.units[2]["privateProcessing"])))).cancel("c")
    finally:
        store.close()
    assert cancelled["state"] == "cancelled"
    with pytest.raises(ValueError, match="history_s2_not_ready_current"):
        history.record_ready(world.units[2], cancelled, CATALOGUE, c_state)
    assert history.snapshot_for(world.units[1], CATALOGUE)["snapshot"]["events"] == []


def test_incompatible_configs_stay_separate_but_compatible_later_batches_preserve_history(tmp_path, monkeypatch):
    old = tmp_path / "old"
    pairs = [make_original(old, "a", old / "native", monkeypatch, scope="shared", selection="exact-one"),
             make_original(old, "b", old / "native", monkeypatch, scope="shared", selection="exact-two"),
             make_original(old, "c", old / "other-native", monkeypatch),
             make_original(old, "d", old / "native", monkeypatch, hosts=["www.korea.kr"])]
    items, units = [p[0] for p in pairs], [p[1] for p in pairs]
    prepared = history.prepare_groups(items, units, tmp_path / "control/offline-verification", "authored-run", runtimes(), actor=ACTOR)
    assert len({u["history"]["groupId"] for u in prepared}) == 4
    isolated = SimpleNamespace(root=tmp_path, units=prepared, monkeypatch=monkeypatch)
    a, state, _ = run_s2(isolated, 0, "isolated-a")
    history.record_ready(prepared[0], a, CATALOGUE, state)
    assert all(history.snapshot_for(unit, CATALOGUE)["snapshot"]["events"] == [] for unit in prepared[1:])
    a_registry = file_pin(prepared[0]["registry"])
    later_item, later_unit = make_original(old, "later", old / "native", monkeypatch)
    later = history.prepare_groups([later_item], [later_unit], tmp_path / "control/offline-verification", "authored-run", runtimes(), actor=ACTOR)[0]
    assert later["history"]["groupId"] in {u["history"]["groupId"] for u in prepared}
    assert file_pin(prepared[0]["registry"]) == a_registry
    current = history.snapshot_for(later, CATALOGUE)
    if later["history"]["groupId"] == prepared[0]["history"]["groupId"]:
        assert len(current["snapshot"]["events"]) == 1
        assert current["snapshot"]["events"][0]["members"][0]["observation"] == prepared[0]["observation"]
    else:
        assert current["snapshot"]["events"] == []


def test_old_manifest_bytes_and_receipt_are_required_not_rewritten(world):
    receipt_path = next(Path(p["path"]) for p in world.old_units[0]["originalPins"] if p["path"].endswith("-receipt.json"))
    receipt = load(receipt_path)
    receipt["grantId"] = "new-processing-grant-must-not-repair-old-receipt"
    save(receipt_path, receipt)
    with pytest.raises(ValueError, match="original_acquisition_pin_changed"):
        history.prepare_groups(world.items, world.old_units, world.root / "control/offline-verification/another-run", "another-run", runtimes(), actor=ACTOR)
    assert not (world.root / "control/offline-verification/another-run/processing/history").exists()


def test_authored_replay_is_refused_on_insertion_and_native_reread(world):
    unit = world.units[0]
    replayed, state, _ = run_s2(world, 0, "authored-replay-negative", replay=True)
    assert replayed["state"] == "ready" and replayed["usage"]["providerCalls"] == 0
    assert replayed["provenance"] == {"sourceKind": "actual", "executionMode": "replay", "recordingKind": "authored-test"}
    assert world.provider_stages["authored-replay-negative"] == []
    with pytest.raises(ValueError, match="history_s2_provenance_mismatch"):
        history.record_ready(unit, replayed, CATALOGUE, state)
    directory = Path(unit["history"]["directory"]) / "ready"
    assert not directory.exists()
    # Adversarial index metadata cannot relabel an actual native replay ledger.
    injected = {"schemaVersion": "zoop-overnight-history-ready-1", "groupId": unit["history"]["groupId"],
                "provenance": history.LIVE_PROVENANCE, "unitProof": unit["history"]["proofPath"],
                "unitProofSha256": sha(Path(unit["history"]["proofPath"]).read_bytes()),
                "extractionStateDir": str(state), "jobId": replayed["jobId"], "inputDigest": replayed["inputDigest"],
                "catalogueDigest": sha(encoded(CATALOGUE)), "upstreamDigest": history.upstream_digest(replayed),
                "candidateIds": [c["eventCandidateId"] for c in replayed["eventCandidates"]], "excluded": {}}
    save(directory / "adversarial-control-index.json", injected)
    reread = history.snapshot_for(world.units[1], CATALOGUE)
    assert reread["snapshot"]["events"] == []
    assert reread["coverage"]["excluded"] == {"prior-not-current-or-invalid": 1}
    save(directory / "adversarial-control-index.json", {**injected, "provenance": replayed["provenance"]})
    declared = history.snapshot_for(world.units[1], CATALOGUE)
    assert declared["snapshot"]["events"] == []
    assert declared["coverage"]["excluded"] == {"different-history-provenance": 1}


def test_public_registry_cannot_rebind_private_native_jobs(world):
    result, directory, _ = run_s2(world, 0, "private-binding")
    assert result["state"] == "ready"
    unit = world.units[0]
    store = ExtractionStore(directory, Path(unit["ingestionStateDir"]), existing=True)
    try:
        current = Extractor(store, Sources(Path(unit["ingestionStateDir"]), Authority(Path(unit["registry"])))).result("private-binding")
    finally:
        store.close()
    assert current["delivery"] == {"status": "withheld", "code": "private_processing_not_public"}


def test_current_index_append_uses_actual_keyless_history_and_native_admission_clis(world, monkeypatch):
    from scripts import overnight_run as runner
    from zoop_ai_pipeline import live_budget

    root = (world.root / "new-night").resolve()
    root.mkdir(mode=0o700)
    config = {"schemaVersion": "zoop-private-run-4", "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"}, "runId": "offline-night-cli", "root": str(root),
              "admitFrom": "2026-10-28T09:00:00Z", "admitUntil": "2026-10-28T21:00:00Z", "finishBy": "2026-10-28T22:00:00Z",
              "graphPort": 32829, "maxCalls": 100000, "processingActor": ACTOR}
    config_path = root / "run.json"
    save(config_path, config)
    index = world.root / "collection-revisions/new/INDEX.json"
    save(index, {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": world.items[:1]})
    args = runner.parse(["--check", "--run-config", str(config_path), "--collection-index", str(index), "--preparation-chunks", "1"])
    for name in ("RUN_CONFIG", "RUN_CONFIG_PATH", "ROOT", "RUN_ID", "ADMIT_UNTIL", "GRAPH_PORT", "MAX_CALLS"):
        monkeypatch.setattr(runner, name, getattr(runner, name))
    runner.configure(args)
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T10:00:00Z")
    monkeypatch.setattr(runner, "remaining", lambda _: 3600)
    controller = runner.Controller(args)
    # Graph ownership is exercised separately; this test runs the real keyless
    # preparation child and both native extraction-submit processes.
    monkeypatch.setattr(controller, "provision_graph", lambda: None)
    monkeypatch.setattr(runner, "read_named_env", lambda *args: pytest.fail("keyless CHECK must not load credentials"))
    first = controller.check()
    first_check = load(root / "control/CHECK.json")
    old_unit = first_check["pins"]["units"][0]
    old_proof = Path(old_unit["history"]["proofPath"]).read_bytes()
    old_chunks = {path: path.read_bytes() for path in (root / "control/history-preparations/v2/chunks").glob("*/complete.json")}
    assert first["units"] == 1 and first["paidCalls"] == 0
    save(index, {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": world.items[:2]})
    second = controller.check()
    second_check = load(root / "control/CHECK.json")
    assert second["units"] == 2 and second["paidCalls"] == 0
    assert second_check["pins"]["units"][0] == old_unit
    assert Path(old_unit["history"]["proofPath"]).read_bytes() == old_proof
    assert {path: path.read_bytes() for path in old_chunks} == old_chunks
    assert first_check["checkDigest"] != second_check["checkDigest"]
    assert first_check["providerApprovalDigest"] == second_check["providerApprovalDigest"]
    assert len(list((root / "control/history-preparations/v2/chunks").glob("*/complete.json"))) == 2
    assert second_check["budget"]["calls"] == 0
    assert {str(path): file_pin(path) for path in world.originals.rglob("*") if path.is_file()} == world.before
    assert second_check["pins"]["limits"]["unitScope"] == "whole-checked-input-manifest"
    assert second_check["pins"]["inputAuthorization"]["coverage"] == {
        "manifestItems": 2, "excluded": 0, "prepared": {"native": 2, "retained": 0}, "awaitingHistory": 0, "blocked": {}}
    sidecar = Path(world.items[2]["owningIngestionStateDir"]) / "ingestion.sqlite3-wal"
    sidecar.touch()
    save(index, {"schemaVersion": "zoop-overnight-collection-index-1", "nativeItems": world.items})
    controller.check()
    partial = load(root / "control/CHECK.json")["pins"]
    assert partial["limits"]["unitScope"] == "prepared-subset-of-checked-input-manifest"
    assert partial["inputAuthorization"]["coverage"] == {
        "manifestItems": 3, "excluded": 0, "prepared": {"native": 2, "retained": 0}, "awaitingHistory": 0,
        "blocked": {"ingestion_state_not_quiescent": 1}}
    assert not (root / "processing" / runner.item_id(world.items[2])).exists()
    sidecar.unlink()
    controller.check()
    complete = load(root / "control/CHECK.json")["pins"]
    assert complete["limits"]["unitScope"] == "whole-checked-input-manifest"
    assert complete["inputAuthorization"]["coverage"] == {
        "manifestItems": 3, "excluded": 0, "prepared": {"native": 3, "retained": 0}, "awaitingHistory": 0, "blocked": {}}
