#!/usr/bin/env python3
"""Actual prepare/verify/annotations CLI with authored native ledgers only; no network."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.ingestion_smoke import OfflineFixture, json_bytes, sha
from zoop_ai_pipeline.ingestion import Ingestor, Store
from zoop_ai_pipeline.ingestion_contracts import Authority, Export, Run, canonical



def pin(path):
    return {"path": str(path), "sha256": sha(path.read_bytes())}


def native_plan_fixture(root, gate="korea-portal-static-3"):
    """Authored synthetic HTTP records: no server, collection runner, or network execution."""
    from scripts.korea_corpus_smoke import article, config as corpus_config
    from zoop_ai_pipeline.collection import Fetched
    from zoop_ai_pipeline.korea_corpus import Config
    from zoop_ai_pipeline.korea_portal import BODY_XPATH, ROUTES, validate_article

    class Origin:
        def url(self, path):
            return "http://127.0.0.1:12345" + path

    root = root.resolve()
    config, _ = corpus_config(root / "plan-inputs", Origin())
    identifier, fetched_at = "100000001", "2026-10-24T00:00:00+00:00"
    collection_id = "item-" + identifier
    url = Origin().url(ROUTES["policy-news"][1]) + "?newsId=" + identifier
    body = article(Origin(), identifier)
    body_hash = sha(body)
    receipt = {"schemaVersion": "zoop-collection-receipt-1", "collectionId": collection_id,
        "sourceId": "korea-portal", "scopeId": identifier, "candidateId": identifier,
        "grantId": config["grant"]["grantId"], "grantRevision": config["grant"]["revision"],
        "requestedUrl": url, "finalUrl": url, "redirects": [], "httpStatus": 200, "contentType": "text/html",
        "mediaType": "text/html", "contentLength": str(len(body)), "etag": None, "lastModified": None,
        "serverDate": None, "bodySha256": body_hash, "bodyBytes": len(body), "fetchedAt": fetched_at,
        "userAgent": config["policy"]["userAgent"], "network": "synthetic_loopback",
        "robots": [{"url": Origin().url("/robots.txt"), "status": 200}], "requestCount": 2}
    receipt_raw = json_bytes(receipt)
    receipt_file = f"collections/{collection_id}/receipts/{sha(receipt_raw)}.json"
    body_file = f"collections/{collection_id}/bodies/{body_hash}.bin"
    kit = OfflineFixture(root / "native")
    source = kit.registry["sources"][0]
    source.update(sourceId="korea-portal", adapter="collected-http")
    source["allowedHosts"] = ["127.0.0.1"]
    source["grant"] = config["grant"]
    source["scopes"][0].update(scopeId=identifier, articleXPath=BODY_XPATH)
    kit.save_registry()
    for name, raw in ((receipt_file, receipt_raw), (body_file, body)):
        path = kit.inputs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    item = kit.item(identifier, identifier, url, publisher="합성기관")
    item.update(title="합성 기사 " + identifier, publishedAt=None, collection={
        "provenance": "collected_http", "collectionId": collection_id,
        "receipt": {"file": receipt_file, "sha256": sha(receipt_raw)}, "fetchedAt": fetched_at,
        "finalUrl": url, "httpStatus": 200, "contentType": "text/html", "bodySha256": body_hash,
        "documentKind": "news", "network": "synthetic_loopback",
        "published": {"raw": "2026-10-23", "precision": "day", "date": "2026-10-23", "basis": "operator-declared"}})
    manifest = kit.manifest("authored", [[item]], bodies={"html": body})
    data = json.loads(manifest.read_bytes())
    data.update(sourceId="korea-portal", scopeId=identifier)
    data["documents"]["html"] = {"file": body_file, "sha256": body_hash}
    manifest.write_bytes(json_bytes(data))
    request = kit.request(manifest, collection_id)
    request.update(sourceId="korea-portal", scopeId=identifier)
    store = Store(kit.root / "state")
    try:
        result = Ingestor(store, Authority(kit.registry_path)).run(Run.model_validate(request), manifest)
        assert result["state"] == "complete" and result["counts"]["textReady"] == 1
    finally:
        store.close()
    ref = result["documentRefs"][0]
    selector = {"schemaVersion": "zoop-ingestion-s2-1", "roundId": collection_id, "sourceId": "korea-portal",
                **{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
    store = Store(kit.root / "state", existing=True)
    try:
        exported = Ingestor(store, Authority(kit.registry_path)).export(Export.model_validate(selector), require_store=True)
    finally:
        store.close()
    (kit.root / "exports").mkdir()
    export = kit.root / "exports" / "one.json"
    export.write_bytes(json_bytes(exported))
    candidate = {"newsId": identifier, "channel": "policy-news", "url": url,
                 "title": item["title"], "publisher": item["publisher"], "publicationDay": "2026-10-23"}
    rights = validate_article(Fetched(url, url, 200, "text/html", "text/html", body, {}, [], [], 0,
                                     fetched_at=fetched_at), candidate, Config.model_validate(config))
    rights_path = Path(config["stateDir"]) / "items" / identifier / "rights.json"
    rights_path.parent.mkdir(parents=True)
    rights_path.write_bytes(json_bytes(rights))
    plan = root / "plan-inputs" / "PLAN.json"
    plan.write_bytes(json_bytes({"config": config, "rightsSha256": config["rightsEvidence"]["sha256"], "gateVersion": gate}))
    bindings = {"schemaVersion": "zoop-corpus-review-bindings-1",
        "selectionPolicy": {"perStratumQuota": 3, "maxReviewDocuments": 36, "allowUnknownDate": True},
        "documents": [{"originalExport": pin(export), "nativeExport": selector, "sourceRegistryFile": pin(kit.registry_path),
            "ingestionStateDir": str(kit.root / "state"), "authorityEvidence": {"kind": "native-corpus-plan",
                "rightsEvidence": config["rightsEvidence"], "planFile": pin(plan), "exclusionManifest": config["exclusionManifest"]},
            "selection": {"channel": "policy-news", "channelBasis": "operator-classification",
                "channelProvenance": "authored synthetic portal route", "publicationDay": "2026-10-23",
                "dayProvenance": "native collection.published.date"}}]}
    path = root / "bindings.json"
    path.write_bytes(json_bytes(bindings))
    return bindings, path


def fixture(root):
    """Six observations in one ledger plus two explicit independent item ledgers."""
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    evidence = root / "operator-rights.json"
    evidence.write_bytes(json_bytes({"authoredSynthetic": True, "permission": "local synthetic fixture only"}))
    documents, kits = [], []
    for index, count in enumerate((6, 1, 1)):
        kit = OfflineFixture(root / ("shared" if index == 0 else f"item-{index}"))
        kits.append(kit)
        items = []
        for n in range(count):
            item = kit.item(f"candidate-{n}", f"supplier-{n}", f"https://example.invalid/article-{n}")
            if index == 0:
                item["publishedAt"] = "2026-10-08T00:00:00+00:00" if n < 4 else "2026-10-15T00:00:00+00:00"
            elif index == 2:
                item["publishedAt"] = None
            items.append(item)
        manifest = kit.manifest("authored", [items])
        store = Store(kit.root / "state")
        try:
            result = Ingestor(store, Authority(kit.registry_path)).run(Run.model_validate(kit.request(manifest, f"round-{index}")), manifest)
            assert result["state"] == "complete" and len(result["documentRefs"]) == count
        finally:
            store.close()
        exports = kit.root / "exports"
        exports.mkdir()
        store = Store(kit.root / "state", existing=True)
        try:
            for n, ref in enumerate(result["documentRefs"]):
                selector = {"schemaVersion": "zoop-ingestion-s2-1", "roundId": f"round-{index}", "sourceId": "synthetic-source",
                            **{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}
                exported = Ingestor(store, Authority(kit.registry_path)).export(Export.model_validate(selector), require_store=True)
                path = exports / f"{n}.json"
                # Noncanonical whitespace proves that prepare copies exact bytes, not a JSON rewrite.
                path.write_text(json.dumps(exported, ensure_ascii=False, indent=2) + "\n")
                documents.append({"originalExport": pin(path), "nativeExport": selector, "sourceRegistryFile": pin(kit.registry_path),
                    "ingestionStateDir": str(kit.root / "state"), "authorityEvidence": {"kind": "legacy-operator-evidence", "rightsEvidence": pin(evidence), "planFile": None, "exclusionManifest": None},
                    "selection": {"channel": "alpha" if n < 4 else "beta", "channelBasis": "operator-classification",
                        "channelProvenance": "authored synthetic group; no relevance claim", "publicationDay": items[n]["publishedAt"][:10] if items[n]["publishedAt"] else None,
                        "dayProvenance": "native authored publication timestamp date, or unknown"}})
        finally:
            store.close()
    value = {"schemaVersion": "zoop-corpus-review-bindings-1", "selectionPolicy": {"perStratumQuota": 2, "maxReviewDocuments": 3, "allowUnknownDate": True}, "documents": documents}
    path = root / "bindings.json"
    path.write_bytes(json_bytes(value))
    return value, path, kits


def cli(*args, expected=0):
    result = subprocess.run([sys.executable, "-B", "-m", "zoop_ai_pipeline.corpus_review_cli", *map(str, args)],
                            cwd=PIPELINE, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, timeout=180)
    assert result.returncode == expected, (result.returncode, result.stdout.decode(), result.stderr.decode())
    assert not result.stderr and "반복" not in result.stdout.decode()
    return json.loads(result.stdout)


def smoke(root):
    value, bindings, kits = fixture(root / "source")
    pack = root / "pack"
    before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for kit in kits for p in (kit.root / "state").iterdir()}
    prepared = cli("prepare", "--bindings", bindings, "--output", pack)
    assert prepared["state"] == "prepared" and prepared["documents"] == 8 and prepared["reviewDocuments"] == 3
    assert before == {p: (Path(p).read_bytes(), Path(p).stat().st_mtime_ns, Path(p).stat().st_mode) for p in before}
    assert cli("prepare", "--bindings", bindings, "--output", pack, expected=2)["error"]["code"] == "review_output_exists"
    inputs = json.loads((pack / "inputs.json").read_bytes())
    assert [s["selectedCount"] for s in inputs["selection"]["strata"]] == [1, 1, 1]
    annotation = json.loads((pack / "annotations.template.json").read_bytes())
    separate = root / "synthetic-human.json"
    separate.write_bytes(json_bytes(annotation))
    assert cli("annotations-check", "--pack", pack, "--annotations", separate)["counts"] == {"unreviewed": 3, "reviewed": 0, "excluded": 0}
    row = annotation["cases"][0]
    record = next(r for r in inputs["documents"] if r["caseId"] == row["caseId"])
    document = json.loads((pack / record["export"]["file"]).read_bytes())["document"]
    start = document["text"].index("반복😀")
    row.update(status="reviewed", reviewerId="synthetic-reviewer", reviewedAt="2026-10-24T00:00:00+00:00", graphNotes="Synthetic test only: uncertain", ragQuestions=[], evidenceSpans=[{
        "documentId": document["documentId"], "documentVersion": document["documentVersion"], "start": start, "end": start + 3, "quote": "반복😀"}])
    separate.write_bytes(json_bytes(annotation))
    assert cli("annotations-check", "--pack", pack, "--annotations", separate)["counts"]["reviewed"] == 1
    bad = copy.deepcopy(annotation)
    bad["cases"][0]["evidenceSpans"][0]["end"] += 1
    separate.write_bytes(json_bytes(bad))
    assert cli("annotations-check", "--pack", pack, "--annotations", separate, expected=2)["error"]["code"] == "review_evidence_span"
    moved = root / "moved"
    shutil.copytree(pack, moved)
    # Neither source ledgers nor the mutable annotation template are available to portable verification.
    shutil.rmtree(root / "source")
    (moved / "annotations.template.json").unlink()
    verified = cli("verify", "--pack", moved)
    assert verified["inputsSha256"] == prepared["inputsSha256"]
    for version in ("korea-portal-static-2", "korea-portal-static-3"):
        _, pinned = native_plan_fixture(root / version, gate=version)
        source_root = pinned.parent
        snapshot = {str(p.relative_to(source_root)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                    for p in source_root.rglob("*") if p.is_file()}
        destination = root / (version + "-pack")
        assert cli("prepare", "--bindings", pinned, "--output", destination)["documents"] == 1
        assert cli("verify", "--pack", destination)["documents"] == 1
        assert snapshot == {str(p.relative_to(source_root)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                            for p in source_root.rglob("*") if p.is_file()}
    return {"status": "passed", "documents": 8, "reviewDocuments": 3,
            "checks": ["actual native shared and per-item ledgers", "exact export bytes", "unchanged ledger bytes/mode/mtime",
                       "no-clobber", "stratum quotas", "unreviewed versus synthetic human claims", "Unicode exact evidence",
                       "moved pack without source or annotations", "gate 2 and 3 native body/receipt/all-rights readonly revalidation"],
            "nativeProofGates": ["korea-portal-static-2", "korea-portal-static-3"], "externalRequests": 0, "modelCalls": 0}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zoop-review-synthetic-") as directory:
        print(canonical(smoke(Path(directory).resolve())))
