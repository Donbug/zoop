"""Read-only retained article bridge; never opens private-intake State or a corpus ledger."""
from __future__ import annotations

import json
from pathlib import Path

from .ingestion_contracts import FileRef, IngestionFailure, MAX_RAW, byte_hash, read_file

OFFICIAL_RECORD = "zoop-official-source-record-1"


def _body_reference(record):
    if record["schemaVersion"] == OFFICIAL_RECORD:
        artifact = record["bodyArtifact"]
        return FileRef.model_validate({"file": artifact["file"], "sha256": artifact["sha256"]})
    return FileRef.model_validate({"file": record["privateId"] + ".raw", "sha256": record["rawSha256"]})


def _representation(record):
    if record["schemaVersion"] == OFFICIAL_RECORD:
        return "text/markdown", None
    if record["schemaVersion"] == "zoop-private-news-record-1":
        return "text/html", record["articleXPath"]
    return ("text/markdown", None) if record["representation"] == "markdown" else ("text/html", "//body")


def _publication(record):
    publication = record["publication"]
    if record["schemaVersion"] == OFFICIAL_RECORD:
        # Actual parsed instants may originate as RFC-822/compact API fields.
        # Their original spelling remains in the record, never an invented midnight.
        return {"raw": publication["value"] if publication["precision"] == "instant" else publication["raw"],
                "precision": publication["precision"], "date": publication["day"],
                "basis": "official field " + publication["field"] + "; original raw value retained in record"}
    return {"raw": publication["raw"], "precision": publication["precision"],
            "date": publication["day"], "basis": publication["basis"]}


def read_record(root: Path, reference: FileRef):
    """Verify exact record/body/envelope bytes using their owners' pure offline verifiers."""
    from .private_intake import MAX_FILE, verify_record

    try:
        record_raw = read_file(root / reference.file, MAX_FILE)
        if byte_hash(record_raw) != reference.sha256:
            raise IngestionFailure("retained_record_hash_mismatch")
        record = json.loads(record_raw)
        identifier = record["privateId"]
        if reference.file != identifier + ".json":
            raise IngestionFailure("retained_record_identity_mismatch")
        original_ref = FileRef.model_validate({"file": identifier + ".raw", "sha256": record["rawSha256"]})
        original = read_file(root / original_ref.file, MAX_RAW)
        if record["schemaVersion"] == OFFICIAL_RECORD:
            from .official_source_adapters import verify_record as verify_official
            body_ref = _body_reference(record)
            envelope_ref = FileRef.model_validate(record["extractionArtifact"])
            body = read_file(root / body_ref.file, MAX_RAW)
            envelope_raw = read_file(root / envelope_ref.file, MAX_FILE)
            verify_official(record, original, extraction_raw=envelope_raw, body_raw=body)
            if record["provenance"] != "official-public-api":
                raise IngestionFailure("retained_record_provenance_invalid")
            return record, body, record_raw, [reference, original_ref, envelope_ref, body_ref]
        body_ref, body = original_ref, original
        envelope_raw = causal_raw = None
        references = [reference, body_ref]
        if record["schemaVersion"] in {"zoop-private-news-record-2", "zoop-private-news-record-3"}:
            envelope_ref = FileRef.model_validate(record["extractionArtifact"])
            envelope_raw = read_file(root / envelope_ref.file, MAX_FILE)
            if byte_hash(envelope_raw) != envelope_ref.sha256:
                raise IngestionFailure("retained_envelope_hash_mismatch")
            from .extraction_fallback import verify_extracted_page
            from .ingestion_url import canonical_url
            envelope = json.loads(envelope_raw)
            hosts = {canonical_url(record["requestUrl"])[1]}
            if record.get("finalUrl"):
                hosts.add(canonical_url(record["finalUrl"])[1])
            verify_extracted_page(envelope, allowed_hosts=tuple(sorted(hosts)))
            references.append(envelope_ref)
            causal = envelope["nativeObservation"].get("knownUnsent")
            if causal is not None:
                causal_ref = FileRef.model_validate({"file": causal["receiptRef"], "sha256": causal["receiptSha256"]})
                causal_raw = read_file(root / causal_ref.file, MAX_RAW)
                if byte_hash(causal_raw) != causal_ref.sha256:
                    raise IngestionFailure("retained_causal_receipt_mismatch")
                references.append(causal_ref)
        verify_record(record, body, extraction_raw=envelope_raw, causal_raw=causal_raw)
        if record["schemaVersion"] == "zoop-private-news-record-3":
            from .ingestion_contracts import digest
            plan = json.loads(read_file(root / "PLAN.json", MAX_FILE))
            sources = [source for source in plan["config"]["sources"] if source["name"] == record["source"]]
            if (digest(plan) != record["planDigest"] or len(sources) != 1
                    or sources[0].get("descriptor") != record["publicationEvidence"]["sourceDescriptor"]):
                raise IngestionFailure("retained_publication_source_unbound")
        expected = "private-public-web" if record["schemaVersion"] == "zoop-private-news-record-1" else "private-public-web-extracted"
        if record["provenance"] != expected:
            raise IngestionFailure("retained_record_provenance_invalid")
        return record, body, record_raw, references
    except IngestionFailure:
        raise
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise IngestionFailure("retained_record_invalid") from exc


def retained_input(source, scope, item, body_ref):
    """Bind an import item to a verified retained root, record and new representation."""
    retained = item.private
    if retained is None or retained.state_dir not in (source.retained_roots or []):
        raise IngestionFailure("retained_root_unauthorized")
    record, body, record_raw, _ = read_record(Path(retained.state_dir), retained.record)
    version = record["schemaVersion"]
    official = version == OFFICIAL_RECORD
    media, xpath = _representation(record)
    published = _publication(record)
    retained_body = _body_reference(record)
    if (record["source"] != source.source_id or record["privateId"] != retained.private_id
            or item.candidate_id != retained.private_id or record["schemaVersion"] != retained.record_schema
            or record["requestUrl"] != item.url or (record["title"] or "" if official else record["title"]) != item.title
            or record["publisher"] != item.publisher or record["finalUrl"] != retained.final_url
            or (None if official else record["canonicalUrl"]) != retained.canonical_url or record["observedAt"] != retained.observed_at
            or published != retained.published.wire() or item.media_type != media or scope.article_xpath != xpath
            or body_ref.wire() != retained_body.wire()):
        raise IngestionFailure("retained_record_identity_mismatch")
    from .ingestion_parsers import prepare, profile
    if version == "zoop-private-news-record-1" and record["parserProfile"] != profile(scope.article_xpath):
        raise IngestionFailure("retained_record_parser_changed")
    prepared = (prepare(body, item.media_type, scope.article_xpath, retained_schema=version) if official
                else prepare(body, item.media_type, scope.article_xpath))
    if byte_hash(prepared["text"].encode("utf-8")) != record["textSha256"]:
        raise IngestionFailure("retained_record_text_changed")
    return body, record_raw


def describe_record(index: dict, input_root: Path) -> dict:
    """Translate one collection-index pin into truthful native import metadata; writes nothing."""
    from .ingestion_contracts import Item, Source, canonical, digest
    from .ingestion_url import canonical_url

    required = {"sourceId", "stateDir", "recordPath", "recordSha256", "privateId", "planId"}
    if set(index) != required:
        raise IngestionFailure("private_index_schema_invalid")
    root = Path(index["stateDir"])
    path = Path(index["recordPath"])
    if not root.is_absolute() or not path.is_absolute() or path.parent != root:
        raise IngestionFailure("retained_root_unauthorized")
    reference = FileRef.model_validate({"file": path.name, "sha256": index["recordSha256"]})
    record, body, _, references = read_record(root, reference)
    plan_raw = read_file(root / "PLAN.json", MAX_RAW)
    plan = json.loads(plan_raw)
    official = record["schemaVersion"] == OFFICIAL_RECORD
    plan_id = plan["planId"] if official else plan["config"]["planId"]
    if (record["privateId"] != index["privateId"] or record["source"] != index["sourceId"]
            or record["planDigest"] != digest(plan) or plan_id != index["planId"]):
        raise IngestionFailure("retained_plan_identity_mismatch")
    if official:
        if record["planId"] != plan_id or plan["sourceId"] != record["source"] or plan["stateDir"] != str(root):
            raise IngestionFailure("retained_plan_identity_mismatch")
    elif record["privateId"] != "private-news-" + digest([index["planId"], record["requestUrl"]]):
        raise IngestionFailure("retained_plan_identity_mismatch")
    if input_root == root or input_root.is_relative_to(root) or root.is_relative_to(input_root):
        raise IngestionFailure("retained_input_root_overlap")
    identifier = record["privateId"]
    media, xpath = _representation(record)
    body_ref = _body_reference(record)
    published = _publication(record)
    hosts = {canonical_url(record["requestUrl"])[1]}
    if record["finalUrl"] is not None:
        hosts.add(canonical_url(record["finalUrl"])[1])
    scope_id = "retained-" + digest([index["sourceId"], str(root), xpath])
    source = Source.model_validate({
        "sourceId": index["sourceId"], "adapter": "retained-private", "inputRoot": str(input_root),
        "retainedRoots": [str(root)], "allowedHosts": sorted(hosts),
        "scopes": [{"scopeId": scope_id, "selection": "exact manifest members under private import authority",
                    "initialCursor": None, "articleXPath": xpath,
                    "timestampLimitations": [published["basis"]]}],
        "grant": {"grantId": "retained-no-public-grant-" + digest([index["sourceId"], str(root)]),
                  "revision": "retained-descriptor-1", "sourceId": index["sourceId"], "enabled": False,
                  "rights": "unknown", "allowedOperations": [], "recipients": [], "purposes": [],
                  "evidence": ["Retained acquisition facts only; publisher rights remain unconfirmed."], "expiresAt": None}})
    item = Item.model_validate({
        "candidateId": identifier, "supplierDocumentId": identifier, "url": record["requestUrl"], "bodyRef": identifier,
        "mediaType": media, "title": (record["title"] or "") if official else record["title"],
        "publisher": record["publisher"], "publishedAt": published["raw"] if published["precision"] == "instant" else None,
        "modifiedAt": None, "sourceRevision": None,
        "private": {"provenance": "retained_private", "stateDir": str(root), "privateId": identifier,
                    "recordSchema": record["schemaVersion"], "record": reference.wire(), "observedAt": record["observedAt"],
                    "finalUrl": record["finalUrl"], "canonicalUrl": None if official else record["canonicalUrl"], "published": published}})
    page = {"items": [item.wire()], "more": False, "nextCursor": None}
    page_raw = canonical(page).encode("utf-8")
    manifest = {"schemaVersion": "zoop-ingestion-s2-1", "sourceId": source.source_id, "scopeId": scope_id,
                "pages": [{"pageId": identifier, "cursor": None, "response": {"file": identifier + ".page.json", "sha256": byte_hash(page_raw)},
                           "status": "ok", "nextCursor": None, "terminal": True, "coverageThrough": None}],
                "documents": {identifier: body_ref.wire()}}
    return {"source": source.wire(), "item": item.wire(), "manifest": manifest, "page": page_raw,
            "record": record, "bodySha256": byte_hash(body),
            "pins": [root / ref.file for ref in references] + [root / "PLAN.json"]}
