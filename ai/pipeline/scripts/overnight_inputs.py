"""Private retained/native input preparation. Acquisition bytes and grants are immutable.

Corpus permissions identify exact observations; execution receipts bind finite sets
without changing document grants. Every eligible indexed source is considered.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path

SELECTOR_KEYS = ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")
CATALOGUE = "api/src/main/resources/db/migration/V20261014163000__seed_confirmed_companies.sql"


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    return json.loads(Path(path).read_bytes())


def save(path, value, *, immutable=False):
    """Fsync then atomic replace; immutable records may only be reused identically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = encoded(value) + b"\n"
    if immutable and path.exists():
        if path.read_bytes() != raw:
            raise ValueError("immutable_artifact_conflict")
        return
    temporary = path.with_name(path.name + ".writing")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def file_pin(path):
    from zoop_ai_pipeline.ingestion_contracts import MAX_LEDGER_COPY, read_file
    path = Path(path)
    raw = read_file(path, MAX_LEDGER_COPY)
    info = path.stat()
    return {"path": str(path), "sha256": sha(raw), "bytes": info.st_size,
            "mtimeNs": info.st_mtime_ns, "mode": info.st_mode}


def catalogue(repo):
    """Parse only the committed, explicit SQL seed grammar, not model-invented aliases."""
    path = Path(repo) / CATALOGUE
    raw = path.read_text()
    quote = r"'((?:[^']|'')*)'"
    pattern = re.compile(r"\(\s*" + quote + r",\s*" + quote + r",\s*(NULL|'(?:[^']|'')*'),\s*(?:NULL|'(?:[^']|'')*'),\s*ARRAY\[(.*?)\]::text\[\],\s*(?:NULL|'(?:[^']|'')*')\)")
    companies = []
    for match in pattern.finditer(raw):
        ident, name, ticker, aliases = match.groups()
        companies.append({"companyId": ident.replace("''", "'"), "name": name.replace("''", "'"),
                          "ticker": None if ticker == "NULL" else ticker[1:-1].replace("''", "'"),
                          "aliases": [a.replace("''", "'") for a in re.findall(quote, aliases)]})
    if len(companies) != 24 or len({c["companyId"] for c in companies}) != 24:
        raise ValueError("committed_catalogue_parse_failed")
    from zoop_ai_pipeline.extraction_contracts import Catalogue
    result = {"revision": "committed-seed-" + sha(path.read_bytes()), "companies": companies}
    Catalogue.model_validate(result)
    return result, file_pin(path)


def indexed_items(index, *, with_metadata=False):
    """Read one collection snapshot without adding metadata to producer-owned rows."""
    if not Path(index).exists():
        return ([], {}) if with_metadata else []
    document = load(index)
    if document.get("schemaVersion") != "zoop-overnight-collection-index-1":
        raise ValueError("collection_index_schema_invalid")
    native, private = document.get("nativeItems"), document.get("privateItems", [])
    if not isinstance(native, list) or not isinstance(private, list):
        raise ValueError("collection_index_items_invalid")
    items = native + private
    if not with_metadata:
        return items
    metadata = document.get("itemFreshness", {})
    if not isinstance(metadata, dict):
        raise ValueError("collection_freshness_metadata_invalid")
    return items, metadata


def observation_selector(observation, indexed=None):
    """Project native metadata, validating the collector's closed, versioned selector."""
    selector = {key: observation[key] for key in SELECTOR_KEYS}
    if indexed is not None:
        if (not isinstance(indexed, dict) or set(indexed) != {"schemaVersion", *SELECTOR_KEYS}
                or indexed["schemaVersion"] != "zoop-ingestion-s2-1"
                or any(type(indexed[key]) is not type(selector[key]) for key in SELECTOR_KEYS)):
            raise ValueError("collection_observation_schema_invalid")
        if {key: indexed[key] for key in SELECTOR_KEYS} != selector:
            raise ValueError("collection_observation_mismatch")
    return selector


def input_freshness(item):
    freshness = item.get("freshness", "unknown")
    if freshness not in ("fresh", "backfill", "reused", "unknown"):
        raise ValueError("collection_freshness_invalid")
    return freshness


def prepare_input_metadata(item, unit_id, item_freshness, root):
    """Write a cohort-only consumer view, never a source/funding/grant preimage.

    Keep this view outside the immutable prepared unit. Native items already own
    their freshness declaration; only six-field retained references use the map.
    """
    if "recordPath" not in item:
        return None
    fields = {"sourceId", "stateDir", "recordPath", "recordSha256", "privateId", "planId"}
    if set(item) != fields or unit_id != sha(encoded(item))[:24]:
        raise ValueError("collection_metadata_identity_invalid")
    if not isinstance(item_freshness, dict):
        raise ValueError("collection_freshness_metadata_invalid")
    present = item["recordPath"] in item_freshness
    declared = item_freshness[item["recordPath"]] if present else {"freshness": "unknown", "publicationDay": None}
    if not isinstance(declared, dict) or set(declared) != {"freshness", "publicationDay"}:
        raise ValueError("collection_freshness_metadata_invalid")
    freshness = input_freshness(declared)
    day = declared["publicationDay"]
    if day is not None:
        try:
            valid = isinstance(day, str) and date.fromisoformat(day).isoformat() == day
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("collection_freshness_metadata_invalid")
    if freshness in {"fresh", "backfill"} and day is None:
        raise ValueError("collection_freshness_metadata_invalid")
    proof = {"schemaVersion": "zoop-private-input-metadata-1", "unitId": unit_id,
             "sourceId": item["sourceId"], "recordPath": item["recordPath"], "recordSha256": item["recordSha256"],
             "freshness": freshness, "publicationDay": day,
             "basis": "collection-index-item-freshness" if present else "collection-index-item-freshness-absent"}
    path = Path(root) / "control/input-metadata" / (unit_id + "-" + sha(encoded(proof)) + ".json")
    save(path, proof, immutable=True)
    return {**proof, "proofPath": str(path), "proofSha256": file_pin(path)["sha256"]}


def preparation_proof(directory, result, freshness):
    """Add provenance in a new proof revision; never rewrite first-failure evidence."""
    legacy = directory / "proof.json"
    prior = None
    if legacy.exists():
        if load(legacy) != result:
            raise ValueError("immutable_artifact_conflict")
        prior = {"path": str(legacy), "sha256": sha(legacy.read_bytes())}
    path = directory / "proof-v2.json"
    revised = {**result, "proofVersion": "zoop-overnight-input-proof-2", "proofPath": str(path),
               "freshness": freshness, "priorProof": prior}
    save(path, revised, immutable=True)
    return revised


def raw_save(path, raw):
    """Create a run-owned immutable byte artifact without changing its representation."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        from zoop_ai_pipeline.ingestion_contracts import MAX_INPUT, read_file
        if read_file(path, MAX_INPUT) != raw:
            raise ValueError("immutable_artifact_conflict")
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def permissions(runtimes):
    """Exact runtime stage pairs, including separately authorized physical fallbacks."""
    pairs = set()
    for runtime in runtimes:
        binding = runtime.binding()
        endpoint = binding["generation"]["endpoint"]
        if endpoint not in {"https://api.openai.com/v1", "https://api.deepseek.com"}:
            raise ValueError("private_runtime_recipient_forbidden")
        if binding["verifier"]["endpoint"] != "https://api.typesafe.ai/v1":
            raise ValueError("private_runtime_recipient_forbidden")
        for stage in runtime.family.stages:
            pairs.add((runtime.purpose(stage), runtime.recipient(stage)))
            fallback = runtime.fallback_recipient(stage)
            if fallback is not None:
                pairs.add((runtime.purpose(stage), fallback))
    return [{"purpose": purpose, "recipient": recipient} for purpose, recipient in sorted(pairs)]


def authorization(path, registry, members, actor, sends, *, phase):
    from zoop_ai_pipeline.private_processing import Segment
    document = {"schemaVersion": "zoop-private-processing-1", "authorizationId": "corpus-" + sha(encoded({
        "registry": str(registry), "members": members, "actor": actor, "sends": sends, "phase": phase})),
        "phase": phase, "registry": {"path": str(registry), "sha256": file_pin(registry)["sha256"]},
        "actor": actor, "use": {"publicUse": False, "redistribution": False, "publication": "not-published"},
        "sends": sends, "members": members}
    Segment.model_validate(document)
    save(path, document, immutable=True)
    return {"path": str(path), "sha256": file_pin(path)["sha256"]}


def execution_receipt(path, registry, segments, execution, runtimes):
    from zoop_ai_pipeline.private_processing import ExecutionReceipt, PrivateAuthority
    value = {"schemaVersion": "zoop-private-execution-1",
             "executionId": "execution-" + sha(encoded([execution, segments, str(registry)])),
             "execution": execution,
             "runtimeIdentities": sorted({runtime.binding()["identity"] for runtime in runtimes}) if execution else [],
             "registry": {"path": str(registry), "sha256": file_pin(registry)["sha256"]}, "segments": segments}
    ExecutionReceipt.model_validate(value)
    save(path, value, immutable=True)
    authority = PrivateAuthority(Path(path))
    if execution:
        for runtime in runtimes:
            authority.check_runtime(runtime.binding())
    return str(path)


def bind_execution(unit, execution, runtimes):
    """Return a new unit view; source/grant/export identity is unchanged across finite sets."""
    from zoop_ai_pipeline.private_processing import Execution, PrivateAuthority
    execution = Execution.model_validate(execution).wire()
    authority = PrivateAuthority(Path(unit["privateProcessing"]))
    registry = Path(authority.receipt.registry.path)
    directory = Path(unit["history"]["directory"]) / "executions" if "history" in unit else Path(unit["export"]).parent / "executions"
    path = directory / ("execution-" + sha(encoded([execution, unit["segments"], str(registry)])) + ".json")
    receipt = execution_receipt(path, registry, unit["segments"], execution, runtimes)
    return {**unit, "privateProcessing": receipt, "privateProcessingSha256": file_pin(path)["sha256"],
            "execution": execution}


def _member(source, scope_id, item, body_hash, *, acquisition=None):
    from zoop_ai_pipeline.ingestion_contracts import Item
    from zoop_ai_pipeline.private_processing import input_identity
    return {"sourceId": source["sourceId"], "scopeId": scope_id,
            "input": input_identity(Item.model_validate(item), body_hash), "observation": None, "textSha256": None,
            "publisherRights": {"status": "unconfirmed" if source["adapter"] == "retained-private" else "unknown", "evidence": []},
            "acquisition": acquisition}


def _processed_member(member, selector, text):
    return {**member, "observation": {key: selector[key] for key in SELECTOR_KEYS if key != "sourceId"},
            "textSha256": sha(text.encode("utf-8"))}


def prepare_item(item, root, run_id, runtimes, *, actor, execution=None):
    """Import retained articles or privately authorize exact native observations, without a send."""
    from zoop_ai_pipeline.ingestion import Store, Ingestor
    from zoop_ai_pipeline.ingestion_contracts import Export, Inspect, Run
    from zoop_ai_pipeline.private_processing import Actor, PrivateAuthority
    from zoop_ai_pipeline.private_retained import describe_record

    actor = Actor.model_validate(actor).wire()
    sends = permissions(runtimes)
    retained = "recordPath" in item
    identity = item if retained else observation_selector(load(item["exportPath"])["observation"], item.get("observation"))
    ident = sha(encoded(identity))[:24]
    directory = Path(root) / "processing" / ident
    old_export = None
    if retained:
        input_root = Path(root) / "processing/retained-inputs" / sha(encoded([item["sourceId"], item["stateDir"]]))
        description = describe_record(item, input_root)
        registry = directory / "sources.json"
        source = description["source"]
        save(registry, {"schemaVersion": "zoop-ingestion-s2-1", "revision": run_id + "-" + ident, "sources": [source]}, immutable=True)
        manifest_path = directory / "manifest.json"
        raw_save(Path(source["inputRoot"]) / description["manifest"]["pages"][0]["response"]["file"], description["page"])
        save(manifest_path, description["manifest"], immutable=True)
        scope_id = description["manifest"]["scopeId"]
        member = _member(source, scope_id, description["item"], description["bodySha256"])
        pins = [file_pin(path) for path in description["pins"]]
        request = {"schemaVersion": "zoop-ingestion-s2-1", "roundId": "retained-" + ident, "sourceId": source["sourceId"],
                   "scopeId": scope_id, "window": None, "checkpointRevision": 0,
                   "fixtureManifestHash": file_pin(manifest_path)["sha256"], "cleanerVersion": "exact-copy-1"}
        imported = directory / "import.json"
        authorization(imported, registry, [member], actor, [], phase="import")
        store_path = directory / "ingestion"
        store = Store(store_path)
        try:
            ingestor = Ingestor(store, PrivateAuthority(imported))
            result = ingestor.run(Run.model_validate(request), manifest_path)
            if result["state"] != "complete" or result["counts"]["textReady"] != 1:
                raise ValueError((result.get("failure") or {}).get("code", "retained_ingestion_not_ready"))
            ref = result["documentRefs"][0]
            selector = {"roundId": request["roundId"], "sourceId": source["sourceId"],
                        **{key: ref[key] for key in SELECTOR_KEYS if key not in {"roundId", "sourceId"}}}
            inspection = ingestor.inspect(Inspect.model_validate({"schemaVersion": "zoop-ingestion-s2-1",
                "roundId": request["roundId"], "sourceId": source["sourceId"],
                "documentId": ref["documentId"], "documentVersion": ref["documentVersion"]}))
            text = inspection["document"]["text"]
        finally:
            store.close()
        if sha(text.encode("utf-8")) != description["record"]["textSha256"]:
            raise ValueError("retained_text_identity_changed")
        published = description["item"]["private"]["published"]
        publication = {"precision": published["precision"],
                       "publishedAt": description["item"]["publishedAt"] or published["date"] or published["raw"],
                       "collectedAt": description["record"]["observedAt"]}
    else:
        old_export = load(item["exportPath"])
        selector = identity
        if item["sourceId"] != selector["sourceId"]:
            raise ValueError("collection_source_identity_mismatch")
        registry = Path(item["acquisitionRegistryPath"])
        original = load(registry)
        source = next(s for s in original["sources"] if s["sourceId"] == selector["sourceId"])
        collection = old_export["observation"].get("collection", {})
        if (source["adapter"] != "collected-http" or collection.get("network") != "external"
                or old_export["observation"].get("provenance") != "collected_http"):
            raise ValueError("native_actual_provenance_required")
        pins = [file_pin(item[key]) for key in ("acquisitionRegistryPath", "exportPath")]
        if item.get("rightsProofPath"):
            pins.append(file_pin(item["rightsProofPath"]))
        from overnight_receipts import capture_quiescent_sqlite
        original_store = Path(item["owningIngestionStateDir"])
        store_path = directory / "ingestion"
        directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ingestion-capture-" + ident + "-", dir=directory.parent) as temporary:
            stage = Path(temporary) / "ingestion"
            stage.mkdir(mode=0o700)
            original_fingerprint = capture_quiescent_sqlite(original_store / "ingestion.sqlite3", stage / "ingestion.sqlite3")
            raw_save(stage / "ingestion.lock", b"")
            directory.mkdir(mode=0o700)
            stage.rename(store_path)
        ingestion_copy = {"schemaVersion": "zoop-ingestion-state-copy-1", "originalStateDir": str(original_store),
                          "original": original_fingerprint, "neverOpened": ["ingestion.lock"],
                          "absentSidecars": ["ingestion.sqlite3-wal", "ingestion.sqlite3-shm", "ingestion.sqlite3-journal"],
                          "copy": {"path": str(store_path / "ingestion.sqlite3"), "sha256": original_fingerprint["sha256"]},
                          "identityProof": "export-equals-original-except-grant"}
        store = Store(store_path, existing=True)
        try:
            row = store.one("SELECT * FROM rounds WHERE id=? AND source=?", (selector["roundId"], selector["sourceId"]))
            if row is None or row["state"] != "complete":
                raise ValueError("native_round_not_complete")
            request = json.loads(row["request"])
            scope_id = request["scopeId"]
            candidate = store.one("SELECT * FROM candidates WHERE round=? AND source=? AND page=? AND ordinal=?",
                                  (selector["roundId"], selector["sourceId"], selector["page"], selector["ordinal"]))
            if candidate is None or (candidate["document"], candidate["raw_version"], candidate["version"]) != (
                    selector["documentId"], selector["rawVersion"], selector["documentVersion"]):
                raise ValueError("native_observation_mismatch")
            candidate_item = json.loads(candidate["data"])
            from zoop_ai_pipeline.ingestion_contracts import FileRef
            receipt_ref = FileRef.model_validate(collection["receipt"])
            proof_paths = [Path(source["inputRoot"]) / receipt_ref.file]
            if item.get("rightsProofPath"):
                proof_paths.append(Path(item["rightsProofPath"]))
            acquisition = {"registry": {"path": str(registry), "sha256": file_pin(registry)["sha256"]},
                           "proofs": [{"path": str(path), "sha256": file_pin(path)["sha256"]} for path in proof_paths]}
            member = _member(source, scope_id, candidate_item, collection["bodySha256"], acquisition=acquisition)
            raw_manifest = bytes(store.one("SELECT data FROM blobs WHERE hash=?", (request["fixtureManifestHash"],))["data"])
            if sha(raw_manifest) != request["fixtureManifestHash"]:
                raise ValueError("native_manifest_hash_mismatch")
            manifest_path = directory / "original-manifest.json"
            raw_save(manifest_path, raw_manifest)
            text = old_export["document"]["text"]
        finally:
            store.close()
        from zoop_ai_pipeline.ingestion_contracts import FileRef
        manifest = load(manifest_path)
        refs = [page["response"] for page in manifest["pages"]] + list(manifest["documents"].values()) + [collection["receipt"]]
        for value in refs:
            ref = FileRef.model_validate(value)
            pin = file_pin(Path(source["inputRoot"]) / ref.file)
            if pin["sha256"] != ref.sha256:
                raise ValueError("native_original_artifact_mismatch")
            pins.append(pin)
        publication = {"precision": collection.get("published", {}).get("precision", "unknown"),
                       "publishedAt": old_export["observation"].get("publishedAt") or collection.get("published", {}).get("date"),
                       "collectedAt": collection.get("fetchedAt")}
    process_member = _processed_member(member, selector, text)
    segment = authorization(directory / "corpus.json", registry, [process_member], actor, sends, phase="process")
    receipt = execution_receipt(directory / "read.json", registry, [segment], None, runtimes)
    store = Store(store_path, existing=True)
    try:
        current = Ingestor(store, PrivateAuthority(Path(receipt))).export(
            Export.model_validate({"schemaVersion": "zoop-ingestion-s2-1", **selector}))
    finally:
        store.close()
    if old_export is not None and {k: v for k, v in current.items() if k != "grant"} != {k: v for k, v in old_export.items() if k != "grant"}:
        raise ValueError("processing_export_provenance_changed")
    if any(file_pin(pin["path"]) != pin for pin in pins):
        raise ValueError("original_acquisition_changed")
    save(directory / "export.json", current, immutable=True)
    result = {"unitId": ident, "sourceId": selector["sourceId"], "scopeId": scope_id, "observation": selector,
              "ingestionStateDir": str(store_path), "registry": str(registry), "export": str(directory / "export.json"),
              "privateProcessing": receipt, "privateProcessingSha256": file_pin(receipt)["sha256"], "segments": [segment],
              "execution": None, "originalPins": pins, "registrySha256": file_pin(registry)["sha256"],
              "exportSha256": file_pin(directory / "export.json")["sha256"], "originalPreserved": True,
              "onlyTopLevelGrantChanged": not retained, "sendAuthorityStages": len(sends),
              "selection": item.get("selection", "collection-index-retained" if retained else "collection-index-native"),
              "importManifest": str(manifest_path), "importRequest": request, "importMember": member,
              "snapshot": {"revision": "explicit-empty-history-1", "events": []},
              "historyLimit": "No supplied cross-store history; NEW is local to this snapshot, not globally new.",
              "publication": publication}
    if not retained:
        result["ingestionStateCopy"] = ingestion_copy
    prepared = preparation_proof(directory, result, input_freshness(item))
    return bind_execution(prepared, execution, runtimes) if execution else prepared


def verify_item(unit):
    from zoop_ai_pipeline.private_processing import PrivateAuthority
    if "ingestionStateCopy" in unit:
        copied = unit["ingestionStateCopy"]["copy"]
        if file_pin(copied["path"])["sha256"] != copied["sha256"]:
            raise ValueError("ingestion_state_copy_pin_changed")
    for pin in unit["originalPins"]:
        if file_pin(pin["path"]) != pin:
            raise ValueError("original_acquisition_pin_changed")
    if file_pin(unit["registry"])["sha256"] != unit["registrySha256"] or file_pin(unit["export"])["sha256"] != unit["exportSha256"]:
        raise ValueError("processing_pin_changed")
    if file_pin(unit["privateProcessing"])["sha256"] != unit["privateProcessingSha256"]:
        raise ValueError("private_execution_pin_changed")
    PrivateAuthority(Path(unit["privateProcessing"]))
    if "history" in unit:
        from overnight_history import verify_unit
        verify_unit(unit)


def canonical_registry(s2, s3, catalogue_value, decision_ref, snapshot_mappings):
    """No fuzzy matching or merging. Unknown company refs make normal freeze refuse."""
    known = {c["companyId"] for c in catalogue_value["companies"]}
    events = {c["eventCandidateId"] for c in s2["eventCandidates"] if c["state"] == "candidate"}
    topics = {c["topicCandidateId"] for c in s2["topicCandidates"]}
    snapshot_refs = {event["eventId"] for event in s2["binding"]["snapshot"]["events"]}
    upstream = {k: s2[k] for k in ("jobId", "inputDigest")}
    endpoints = set()
    for relation in s3["relations"]:
        eligibility = relation["eligibility"]
        if eligibility["status"] != "eligible" or eligibility["reviewPending"]:
            continue
        if (eligibility.get("approvalBasis") or {}).get("kind") != "automatic-verifier":
            raise ValueError("nonautomatic_approval_forbidden")
        for edge in [relation, *relation["path"]]:
            for side in ("subject", "object"):
                endpoints.add((edge[side]["kind"], edge[side]["ref"]))
    entries = []
    for kind, ref in sorted(endpoints):
        if kind == "company" and ref in known:
            canonical_id = ref
        elif (kind == "event" and ref in events) or (kind == "topic" and ref in topics):
            canonical_id = "private-" + kind + "-" + sha(encoded({"upstream": upstream, "ref": ref}))
        elif kind == "event" and ref in snapshot_refs and ref in snapshot_mappings:
            mapping = snapshot_mappings[ref]
            canonical_id = "private-event-" + sha(encoded({"upstream": mapping["upstream"], "ref": mapping["eventCandidateId"]}))
            if mapping["canonicalId"] != canonical_id:
                raise ValueError("history_canonical_mapping_changed")
        else:
            raise ValueError("canonical_mapping_unresolved")
        entries.append({"upstream": upstream, "kind": kind, "ref": ref, "canonicalId": canonical_id, "decisionRef": decision_ref})
    return {"schemaVersion": "zoop-graph-canonical-1", "entries": entries}
