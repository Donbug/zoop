"""Private candidate history over newly owned native ingestion ledgers.

Compatible source configurations share a history group, including different
countries and retained formats. Each corpus segment is immutable; execution-set
receipts never replace document grants. Serialization limits partition all inputs,
not the global experiment scope. Old acquisition roots are read only.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from overnight_inputs import (authorization, bind_execution, encoded, execution_receipt, file_pin, load,
                              observation_selector, permissions, raw_save, save, sha, _processed_member)
from zoop_ai_pipeline import extraction_replay as analysis
from zoop_ai_pipeline.extraction import Extractor, Sources, Store as ExtractionStore, cite_exact, upstream_digest
from zoop_ai_pipeline.extraction_contracts import Catalogue, ExtractionFailure, ObservationRef, Snapshot, Submit
from zoop_ai_pipeline.ingestion import Ingestor, Store
from zoop_ai_pipeline.ingestion_contracts import Export, IngestionFailure, Run, now
from zoop_ai_pipeline.private_processing import Actor, PrivateAuthority

MAX_SCOPES = 100
MAX_EVENTS = 8  # Explicit nightly measurement cap; native contract permits 50.
MAX_MEMBERS = 20  # Total snapshot members, not 20 per event.
POLICY = "ready-prior-candidates-exact-singletons-1"
LIVE_PROVENANCE = {"sourceKind": "actual", "executionMode": "live", "recordingKind": "provider"}


def _pins_unchanged(pins):
    if any(file_pin(pin["path"]) != pin for pin in pins):
        raise ValueError("original_acquisition_pin_changed")


def _original(item, unit):
    _pins_unchanged(unit["originalPins"])
    old = load(unit["export"])
    selector = observation_selector(old["observation"])
    if selector != unit["observation"] or item["sourceId"] != selector["sourceId"]:
        raise ValueError("history_original_selector_mismatch")
    registry = load(unit["registry"])
    source = next(s for s in registry["sources"] if s["sourceId"] == unit["sourceId"])
    scope = next(s for s in source["scopes"] if s["scopeId"] == unit["scopeId"])
    raw_manifest = Path(unit["importManifest"]).read_bytes()
    if sha(raw_manifest) != unit["importRequest"]["fixtureManifestHash"]:
        raise ValueError("history_original_manifest_mismatch")
    pins = {pin["path"]: pin for pin in unit["originalPins"]}
    for path in (unit["registry"], unit["export"], unit["privateProcessing"], unit["importManifest"]):
        pin = file_pin(path)
        pins[pin["path"]] = pin
    return {"item": item, "unit": unit, "old": old, "selector": selector,
            "request": unit["importRequest"], "manifest": raw_manifest,
            "base": {key: value for key, value in source.items() if key not in {"scopes", "grant"}},
            "grant": source["grant"], "scope": scope, "pins": sorted(pins.values(), key=lambda pin: pin["path"])}


def _batches(records, prior=()):
    """Pack compatible sources together, retaining existing append-only group identities."""
    groups = []
    for index in prior:
        sources = {source["sourceId"]: {"base": {key: value for key, value in source.items() if key not in {"scopes", "grant"}},
                   "grant": source["grant"], "scopes": {scope["scopeId"]: scope for scope in source["scopes"]}} for source in index["sources"]}
        groups.append({"sources": sources, "records": [], "index": index})
    for record in sorted(records, key=lambda value: (value["base"]["sourceId"], encoded(value["base"]), value["unit"]["unitId"])):
        source_id = record["base"]["sourceId"]
        scope_id = record["scope"]["scopeId"]
        selected = None
        for group in groups:
            existing = group["sources"].get(source_id)
            if existing is None and len(group["sources"]) >= 100:
                continue
            if existing is not None and (existing["base"] != record["base"]
                    or scope_id in existing["scopes"] and existing["scopes"][scope_id] != record["scope"]
                    or scope_id not in existing["scopes"] and len(existing["scopes"]) >= MAX_SCOPES):
                continue
            selected = group
            break
        if selected is None:
            selected = {"sources": {}, "records": []}
            groups.append(selected)
        source = selected["sources"].setdefault(source_id, {"base": record["base"], "grant": record["grant"], "scopes": {}})
        source["scopes"][scope_id] = record["scope"]
        selected["records"].append(record)
    return groups


def _conserved(old, fresh):
    if any(old[key] != fresh[key] for key in ("schemaVersion", "document", "locatorMetadata")):
        raise ValueError("history_document_version_changed")
    # New round and observation timestamps are real new ingestion facts. Every
    # acquisition/publication/body/receipt/metadata field remains exactly original.
    omit = {"roundId", "observedAt"}
    if {k: v for k, v in old["observation"].items() if k not in omit} != {
            k: v for k, v in fresh["observation"].items() if k not in omit}:
        raise ValueError("history_collection_facts_changed")


def _import_batch(records, directory, ingestion_path, actor):
    prepared_members, pending = [], []
    store = Store(ingestion_path)
    try:
        for record in records:
            unit = record["unit"]
            own = directory / "units" / unit["unitId"]
            import_path = own / "import.json"
            # A combined reader registry must never replace the acquisition grant
            # against which this exact original HTTP receipt was recorded.
            same_manifest = [other["unit"]["importMember"] for other in records
                             if other["unit"]["registry"] == unit["registry"] and other["manifest"] == record["manifest"]]
            authorization(import_path, Path(unit["registry"]), same_manifest, actor, [], phase="import")
            ingestor = Ingestor(store, PrivateAuthority(import_path))
            _pins_unchanged(record["pins"])
            manifest_path = own / "original-manifest.json"
            raw_save(manifest_path, record["manifest"])
            request = dict(record["request"])
            request["roundId"] = "history-" + sha(encoded([request["roundId"], request["sourceId"], request["fixtureManifestHash"]]))
            existing = store.one("SELECT request FROM rounds WHERE id=? AND source=?", (request["roundId"], request["sourceId"]))
            if existing:
                request = json.loads(existing["request"])
            else:
                checkpoint = store.one("SELECT revision FROM scopes WHERE source=? AND scope=?", (request["sourceId"], request["scopeId"]))
                request["checkpointRevision"] = checkpoint["revision"] if checkpoint else 0
            save(own / "request.json", request, immutable=True)
            if not (own / "start.json").exists():
                save(own / "start.json", {"startedAt": now()}, immutable=True)
            result = ingestor.run(Run.model_validate(request), manifest_path)
            save(own / "ingestion-result.json", result)
            if result["state"] != "complete" or result["counts"]["held"] or not result["counts"]["textReady"]:
                raise ValueError((result.get("failure") or {}).get("code", "history_native_ingestion_not_ready"))
            ref = {**record["selector"], "roundId": request["roundId"]}
            from zoop_ai_pipeline.ingestion_contracts import Inspect
            inspection = ingestor.inspect(Inspect.model_validate({"schemaVersion": "zoop-ingestion-s2-1",
                "roundId": ref["roundId"], "sourceId": ref["sourceId"],
                "documentId": ref["documentId"], "documentVersion": ref["documentVersion"]}))
            prepared_members.append(_processed_member(unit["importMember"], ref, inspection["document"]["text"]))
            pending.append((record, own, ref))
    finally:
        store.close()
    return prepared_members, pending


def prepare_groups(items, units, root, run_id, runtimes, *, actor, executions=None):
    """Append authorized imports while preserving all earlier corpus segments and job grants.

    The controller serializes this writer against S2/S3/graph readers. New
    registry versions are immutable files; corpus-index.json is only a run-owned
    discovery pointer. Receipt pins, not that pointer, authorize reads and sends.
    """
    actor = Actor.model_validate(actor).wire()
    if len(items) != len(units) or len({unit["unitId"] for unit in units}) != len(units):
        raise ValueError("history_batch_identity_invalid")
    records = [_original(item, unit) for item, unit in zip(items, units)]
    sends = permissions(runtimes)
    root = Path(root) / "processing/history"
    catalog_path = root / "catalog.json"
    catalog = load(catalog_path) if catalog_path.exists() else {"schemaVersion": "zoop-private-history-catalog-1", "runId": run_id, "groups": []}
    if catalog.get("schemaVersion") != "zoop-private-history-catalog-1" or catalog.get("runId") != run_id:
        raise ValueError("history_catalog_invalid")
    prior = []
    for group_id in catalog["groups"]:
        if not re.fullmatch(r"[a-f0-9]{64}", group_id):
            raise ValueError("history_catalog_invalid")
        prior.append(load(root / group_id / "corpus-index.json"))
    results = {}
    for group in _batches(records, prior):
        if not group["records"]:
            continue
        sources = [{**value["base"], "grant": value["grant"], "scopes": [value["scopes"][key] for key in sorted(value["scopes"])]}
                   for _, value in sorted(group["sources"].items())]
        index = group.get("index")
        initial = {"policy": POLICY, "historyProvenance": LIVE_PROVENANCE, "runId": run_id,
                   "initialSources": sources, "initialUnits": [record["unit"]["unitId"] for record in group["records"]],
                   "historyLimits": {"maxEvents": MAX_EVENTS, "maxMembersTotal": MAX_MEMBERS, "membersPerEvent": 1}}
        group_id = index["groupId"] if index else sha(encoded(initial))
        directory = root / group_id
        ingestion_path = directory / "ingestion"
        for record in group["records"]:
            for path in (record["unit"]["ingestionStateDir"], record["base"]["inputRoot"]):
                original = Path(path).resolve()
                if directory.resolve().is_relative_to(original) or original.is_relative_to(directory.resolve()):
                    raise ValueError("history_state_overlaps_original")
        if index is None:
            save(directory / "group.json", initial, immutable=True)
            index = {"schemaVersion": "zoop-private-history-index-1", "groupId": group_id, "sources": [], "segments": [], "units": []}
        if index.get("schemaVersion") != "zoop-private-history-index-1" or index["groupId"] != group_id:
            raise ValueError("history_corpus_index_invalid")
        registry_path = directory / ("sources-" + sha(encoded(sources)) + ".json")
        save(registry_path, {"schemaVersion": "zoop-ingestion-s2-1", "revision": "history-" + sha(encoded(sources)), "sources": sources}, immutable=True)
        new_records = [record for record in group["records"] if record["unit"]["unitId"] not in index["units"]]
        for offset in range(0, len(new_records), 1000):
            chunk = new_records[offset:offset + 1000]
            batch_id = sha(encoded([record["unit"]["unitId"] for record in chunk]))
            members, pending = _import_batch(chunk, directory, ingestion_path, actor)
            segment = authorization(directory / ("corpus-" + batch_id + ".json"), registry_path, members, actor, sends, phase="process")
            segments = [*index["segments"], segment]
            receipt_path = directory / ("read-" + sha(encoded([segments, str(registry_path)])) + ".json")
            receipt = execution_receipt(receipt_path, registry_path, segments, None, runtimes)
            store = Store(ingestion_path, existing=True)
            try:
                ingestor = Ingestor(store, PrivateAuthority(Path(receipt)))
                for record, own, ref in pending:
                    unit = record["unit"]
                    fresh = ingestor.export(Export.model_validate({"schemaVersion": "zoop-ingestion-s2-1", **ref}))
                    _conserved(record["old"], fresh)
                    _pins_unchanged(record["pins"])
                    export_path, proof_path = own / "export.json", own / "proof.json"
                    save(export_path, fresh, immutable=True)
                    prepared = {**unit, "observation": ref, "originalObservation": record["selector"],
                        "ingestionStateDir": str(ingestion_path), "registry": str(registry_path), "export": str(export_path),
                        "registrySha256": file_pin(registry_path)["sha256"], "exportSha256": file_pin(export_path)["sha256"],
                        "privateProcessing": receipt, "privateProcessingSha256": file_pin(receipt)["sha256"],
                        "segments": segments, "execution": None, "originalPins": record["pins"],
                        "originalPreserved": True, "onlyTopLevelGrantChanged": False,
                        "history": {"groupId": group_id, "directory": str(directory), "proofPath": str(proof_path),
                                    "groupSha256": file_pin(directory / "group.json")["sha256"], "policy": POLICY},
                        "reingestion": {"startedAt": load(own / "start.json")["startedAt"], "observedAt": fresh["observation"]["observedAt"],
                                       "originalObservedAt": record["old"]["observation"]["observedAt"],
                                       "originalManifestSha256": sha(record["manifest"]),
                                       "acquisitionGrant": {key: record["grant"][key] for key in ("grantId", "revision")}},
                        "snapshot": {"revision": "history-empty-" + group_id, "events": []},
                        "historyLimit": "Compatible cumulative source group and catalogue; explicit bounded snapshot, never globally complete."}
                    save(proof_path, prepared, immutable=True)
            finally:
                store.close()
            index = {**index, "sources": sources, "segments": segments,
                     "units": [*index["units"], *(record["unit"]["unitId"] for record in chunk)],
                     "privateProcessing": receipt, "privateProcessingSha256": file_pin(receipt)["sha256"]}
            save(directory / "corpus-index.json", index)
        if group_id not in catalog["groups"]:
            catalog["groups"].append(group_id)
            save(catalog_path, catalog)
        for record in group["records"]:
            unit_id = record["unit"]["unitId"]
            prepared = refresh_unit(load(directory / "units" / unit_id / "proof.json"))
            results[unit_id] = bind_execution(prepared, executions[unit_id], runtimes) if executions and unit_id in executions else prepared
    return [results[unit["unitId"]] for unit in units]


def refresh_unit(unit):
    """Choose a cumulative read receipt, without changing the observation's original proof or grant."""
    index = load(Path(unit["history"]["directory"]) / "corpus-index.json")
    if index.get("schemaVersion") != "zoop-private-history-index-1" or index.get("groupId") != unit["history"]["groupId"] or unit["unitId"] not in index["units"]:
        raise ValueError("history_corpus_index_invalid")
    authority = PrivateAuthority(Path(index["privateProcessing"]))
    if file_pin(index["privateProcessing"])["sha256"] != index["privateProcessingSha256"]:
        raise ValueError("private_execution_pin_changed")
    current = {**unit, "privateProcessing": index["privateProcessing"],
               "privateProcessingSha256": index["privateProcessingSha256"],
               "segments": [pin.wire() for pin in authority.receipt.segments], "execution": None}
    verify_unit(current)
    return current


def verify_unit(unit):
    """Revalidate immutable acquisition pins and the exact private export from its new owner."""
    history = unit["history"]
    directory = Path(history["directory"])
    if file_pin(directory / "group.json")["sha256"] != history["groupSha256"]:
        raise ValueError("history_group_pin_changed")
    if file_pin(unit["registry"])["sha256"] != unit["registrySha256"] or file_pin(unit["export"])["sha256"] != unit["exportSha256"]:
        raise ValueError("history_processing_pin_changed")
    _pins_unchanged(unit["originalPins"])
    proof = load(history["proofPath"])
    for key in ("unitId", "history", "observation", "originalObservation", "ingestionStateDir", "registry", "export",
                "registrySha256", "exportSha256", "originalPins", "reingestion"):
        if proof[key] != unit[key]:
            raise ValueError("history_unit_proof_changed")
    if not {encoded(pin) for pin in proof["segments"]} <= {encoded(pin) for pin in unit["segments"]}:
        raise ValueError("history_segment_removed")
    if file_pin(unit["privateProcessing"])["sha256"] != unit["privateProcessingSha256"]:
        raise ValueError("private_execution_pin_changed")
    store = Store(Path(unit["ingestionStateDir"]), existing=True)
    try:
        exported = Ingestor(store, PrivateAuthority(Path(unit["privateProcessing"]))).export(
            Export.model_validate({"schemaVersion": "zoop-ingestion-s2-1", **unit["observation"]}))
        if exported != load(unit["export"]):
            raise ValueError("history_owning_export_changed")
    finally:
        store.close()




def _ready(unit, job_id, catalogue, extraction_state_dir):
    verify_unit(unit)
    sources = Sources(Path(unit["ingestionStateDir"]), PrivateAuthority(Path(unit["privateProcessing"])))
    store = ExtractionStore(Path(extraction_state_dir), Path(unit["ingestionStateDir"]), existing=True)
    try:
        row = store.one("SELECT request FROM jobs WHERE job_id=?", (job_id,))
        if row is None:
            raise ValueError("history_s2_job_missing")
        request = Submit.model_validate_json(row["request"])
        if request.incoming.wire() != unit["observation"] or request.catalogue.wire() != catalogue:
            raise ValueError("history_s2_binding_mismatch")
        result = Extractor(store, sources).result(job_id)
        if result["state"] != "ready" or result.get("delivery", {}).get("status") != "current":
            raise ValueError("history_s2_not_ready_current")
        usage = result["usage"]
        if (request.provenance.wire() != LIVE_PROVENANCE or result["provenance"] != LIVE_PROVENANCE
                or usage["executionMode"] != "live" or usage["replayCalls"] != 0):
            raise ValueError("history_s2_provenance_mismatch")
        return result, request, sources
    finally:
        store.close()


def _candidate_reason(candidate, unit, request, sources):
    if candidate["state"] != "candidate":
        return "rejected-candidate"
    if (candidate.get("disposition") or {}).get("status") not in {"new-event-candidate", "same-event-candidate"}:
        return "held-or-undecided-candidate"
    if candidate["document"] != {key: unit["observation"][key] for key in ("documentId", "documentVersion", "rawVersion")}:
        return "candidate-document-mismatch"
    try:
        exported = sources.export(request.incoming)
        projected = analysis.article(exported, request.provenance.source_kind == "synthetic")
        mention = analysis.member_mention(candidate["mention"], projected, analysis.company_names(request.catalogue))
        if mention.background:
            return "background-candidate"
        if mention.mention_id != candidate["localMentionId"]:
            return "candidate-mention-mismatch"
        for evidence in mention.evidence:
            cite_exact(sources, request.incoming, exported, evidence.start, evidence.end, evidence.quote)
    except (ExtractionFailure, ValueError):
        return "invalid-source-evidence"
    return None


def record_ready(unit, s2, catalogue, extraction_state_dir):
    """Record only a reference to a proven ready S2 result, never caller-made events."""
    catalogue = Catalogue.model_validate(catalogue).wire()
    current, request, sources = _ready(unit, s2["jobId"], catalogue, extraction_state_dir)
    if current["inputDigest"] != s2["inputDigest"] or upstream_digest(current) != upstream_digest(s2):
        raise ValueError("history_s2_result_mismatch")
    exclusions = Counter()
    candidates = []
    for candidate in current["eventCandidates"]:
        reason = _candidate_reason(candidate, unit, request, sources)
        if reason:
            exclusions[reason] += 1
        else:
            candidates.append(candidate["eventCandidateId"])
    record = {"schemaVersion": "zoop-overnight-history-ready-1", "groupId": unit["history"]["groupId"],
              "provenance": current["provenance"],
              "unitProof": unit["history"]["proofPath"], "unitProofSha256": sha(Path(unit["history"]["proofPath"]).read_bytes()),
              "extractionStateDir": str(Path(extraction_state_dir).resolve()), "jobId": current["jobId"],
              "inputDigest": current["inputDigest"], "catalogueDigest": sha(encoded(catalogue)),
              "upstreamDigest": upstream_digest(current), "candidateIds": sorted(candidates), "excluded": dict(exclusions)}
    key = sha(encoded({k: record[k] for k in ("jobId", "inputDigest", "extractionStateDir")}))
    path = Path(unit["history"]["directory"]) / "ready" / (key + ".json")
    save(path, record, immutable=True)
    return {"recordPath": str(path), "eligibleCandidates": len(candidates), "excluded": dict(exclusions)}


def snapshot_for(unit, catalogue, *, max_events=MAX_EVENTS, max_members=MAX_MEMBERS):
    """Current bounded candidate coverage. Caller freezes the return before submit.

    canonicalMappings retains each prior private graph identity; it does not
    approve, union, or publish the candidate and never mutates its disposition.
    """
    if type(max_events) is not int or not 0 <= max_events <= MAX_EVENTS or type(max_members) is not int or not 0 <= max_members <= MAX_MEMBERS:
        raise ValueError("history_limits_invalid")
    unit = refresh_unit(unit)
    verify_unit(unit)
    catalogue = Catalogue.model_validate(catalogue).wire()
    cat_digest = sha(encoded(catalogue))
    records = [load(path) for path in sorted((Path(unit["history"]["directory"]) / "ready").glob("*.json"))]
    eligible, exclusions = [], Counter()
    examined = 0
    for record in records:
        if record["groupId"] != unit["history"]["groupId"]:
            exclusions["different-group"] += 1
            continue
        if record.get("provenance") != LIVE_PROVENANCE:
            exclusions["different-history-provenance"] += 1
            continue
        if record["catalogueDigest"] != cat_digest:
            exclusions["different-catalogue"] += 1
            continue
        if sha(Path(record["unitProof"]).read_bytes()) != record["unitProofSha256"]:
            raise ValueError("history_prior_proof_changed")
        prior = load(record["unitProof"])
        if prior["ingestionStateDir"] != unit["ingestionStateDir"]:
            exclusions["different-owning-ledger"] += 1
            continue
        if prior["observation"]["documentVersion"] == unit["observation"]["documentVersion"]:
            exclusions["incoming-document-version"] += len(record["candidateIds"])
            continue
        try:
            prior = refresh_unit(prior)
            current, request, sources = _ready(prior, record["jobId"], catalogue, record["extractionStateDir"])
            if current["inputDigest"] != record["inputDigest"] or upstream_digest(current) != record["upstreamDigest"]:
                raise ValueError("history_prior_result_changed")
            examined += len(current["eventCandidates"])
            by_id = {c["eventCandidateId"]: c for c in current["eventCandidates"]}
            for ident in record["candidateIds"]:
                candidate = by_id[ident]
                reason = _candidate_reason(candidate, prior, request, sources)
                if reason:
                    exclusions[reason] += 1
                else:
                    eligible.append((record, prior, candidate))
            exclusions.update(record["excluded"])
        except (ExtractionFailure, IngestionFailure, ValueError, OSError, KeyError):
            exclusions["prior-not-current-or-invalid"] += max(1, len(record["candidateIds"]))
    eligible.sort(key=lambda entry: (entry[0]["jobId"], entry[0]["inputDigest"], entry[2]["eventCandidateId"], entry[0]["extractionStateDir"]))
    events, mappings, selected, seen = [], {}, [], set()
    for record, prior, candidate in eligible:
        identity = (prior["observation"]["documentVersion"], candidate["localMentionId"])
        if identity in seen:
            exclusions["duplicate-exact-mention"] += 1
            continue
        seen.add(identity)
        if len(events) >= min(max_events, max_members):
            exclusions["bounded-coverage"] += 1
            continue
        upstream = {"jobId": record["jobId"], "inputDigest": record["inputDigest"]}
        origin = {"upstream": upstream, "ref": candidate["eventCandidateId"]}
        event_id = "night-history-" + sha(encoded({"groupId": record["groupId"], **origin}))
        events.append({"eventId": event_id, "revision": record["upstreamDigest"],
                       "members": [{"observation": prior["observation"], "mention": candidate["mention"]}]})
        mappings[event_id] = {"canonicalId": "private-event-" + sha(encoded(origin)), "upstream": upstream,
                              "eventCandidateId": candidate["eventCandidateId"]}
        selected.append({"eventId": event_id, "upstream": upstream, "eventCandidateId": candidate["eventCandidateId"],
                         "mentionCandidateId": candidate["mentionCandidateId"], "localMentionId": candidate["localMentionId"],
                         "observation": prior["observation"], "extractionStateDir": record["extractionStateDir"]})
    snapshot = {"revision": "history-" + sha(encoded({"groupId": unit["history"]["groupId"], "catalogue": cat_digest, "events": events})), "events": events}
    Snapshot.model_validate(snapshot)
    return {"unit": unit, "snapshot": snapshot, "canonicalMappings": mappings, "coverage": {
        "policy": POLICY, "groupId": unit["history"]["groupId"], "catalogueDigest": cat_digest,
        "provenance": LIVE_PROVENANCE,
        "maxEvents": max_events, "maxMembersTotal": max_members, "membersPerEvent": 1,
        "recordedJobs": len(records), "eligibleBeforeDedupAndBounds": len(eligible), "selectedEvents": len(events),
        "examinedPriorCandidates": examined, "eligibleHistoryTotal": len(seen),
        "selectedMembers": len(events), "excluded": dict(sorted(exclusions.items())), "selected": selected,
        "ordering": "jobId,inputDigest,eventCandidateId,extractionStateDir ascending",
        "scope": "same frozen group and catalogue only; independent candidate singletons; not globally complete, gold, or approved",
        "newMeaning": "no SAME in this frozen bounded snapshot, not global novelty"}}
