#!/usr/bin/env python3
"""Authored HTML/PDF → actual JSON subprocesses. Fresh owned state is always removed."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BFF = Path(__file__).resolve().parents[1]
PROJECT = BFF.parents[1]
SCHEMA = "zoop-ingestion-s2-1"
HTML = '<html><body><article><p>반복 &amp; <b>반복😀</b> 꼬리<span class="advertisement">삭제</span>뒤</p><p>반복😀 둘째</p></article></body></html>'.encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def authored_pdf(*texts, encrypted=False):
    """Real minimal PDF pages with explicit fonts/content, no image/OCR dependency."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 10 100 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("authored-test")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class OfflineFixture:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.registry_path = self.root / "sources.json"
        self.registry = {"schemaVersion": SCHEMA, "revision": "operator-1", "sources": [{"sourceId": "synthetic-source", "adapter": "authored-files", "inputRoot": str(self.inputs), "allowedHosts": ["example.invalid"], "scopes": [{"scopeId": "body", "selection": "authored source slice", "initialCursor": None, "articleXPath": None, "timestampLimitations": ["authored fixtures; no real provider late-registration guarantee"]}], "grant": {"grantId": "operator-grant", "revision": "rights-1", "sourceId": "synthetic-source", "enabled": True, "rights": "known", "allowedOperations": ["read", "store", "quote-display"], "recipients": [], "purposes": [], "evidence": ["operator-owned authored synthetic fixtures"], "expiresAt": None}}]}
        self.save_registry()

    def save_registry(self):
        temporary = self.root / "next-sources.json"
        temporary.write_bytes(json_bytes(self.registry))
        temporary.replace(self.registry_path)

    def file(self, name, raw):
        path = self.inputs / name
        path.write_bytes(raw)
        return {"file": name, "sha256": sha(raw)}

    def item(self, candidate="c1", supplier="supplier-1", url="https://example.invalid/article", ref="html", media="text/html"):
        return {"candidateId": candidate, "supplierDocumentId": supplier, "url": url, "bodyRef": ref, "mediaType": media, "title": "authored", "publishedAt": "2026-10-08T00:00:00+00:00", "modifiedAt": None, "sourceRevision": None}

    def manifest(self, name, batches, *, bodies=None, statuses=None, terminal=True, coverage=None):
        documents = {key: self.file(f"{name}-{key}.bin", body) for key, body in (bodies or {"html": HTML}).items()}
        pages = []
        for ordinal, items in enumerate(batches):
            last = ordinal == len(batches) - 1
            end = last and terminal
            cursor = None if ordinal == 0 else f"cursor-{ordinal}"
            following = None if end else f"cursor-{ordinal + 1}"
            response = self.file(f"{name}-page-{ordinal}.json", json_bytes({"items": items, "more": not end, "nextCursor": following}))
            pages.append({"pageId": f"page-{ordinal}", "cursor": cursor, "response": response, "status": (statuses or ["ok"] * len(batches))[ordinal], "nextCursor": following, "terminal": end, "coverageThrough": coverage if end else None})
        payload = {"schemaVersion": SCHEMA, "sourceId": "synthetic-source", "scopeId": "body", "pages": pages, "documents": documents}
        path = self.root / f"{name}-manifest.json"
        path.write_bytes(json_bytes(payload))
        return path

    def request(self, manifest, rid="round-1", revision=0, window=None):
        return {"schemaVersion": SCHEMA, "roundId": rid, "sourceId": "synthetic-source", "scopeId": "body", "window": window, "checkpointRevision": revision, "fixtureManifestHash": sha(manifest.read_bytes()), "cleanerVersion": "exact-copy-1"}

    def selector(self, rid="round-1", **extra):
        return {"schemaVersion": SCHEMA, "roundId": rid, "sourceId": "synthetic-source", **extra}

    def cli(self, command, request, *, state="state", manifest=None, crash=None, sources=True, expected=0):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(BFF / "src")}
        if crash:
            # Kill the actual process at a durable stage, not a fake CLI result.
            hooks = {"receipt": "Ingestor._discover=lambda *a: os._exit(75)", "raw": "parsers.prepare=lambda *a: os._exit(75)", "version": "Ingestor._complete_page=lambda *a: os._exit(75)", "checkpoint": "original=Ingestor._complete_page\ndef stop(*a):\n original(*a)\n os._exit(75)\nIngestor._complete_page=stop"}
            code = "import os\nfrom zoop_bff.ingestion import Ingestor, parsers\nfrom zoop_bff.ingestion_cli import main\n" + hooks[crash] + "\nraise SystemExit(main())"
            argv = [sys.executable, "-c", code, command]
        else:
            argv = [sys.executable, "-m", "zoop_bff.ingestion_cli", command]
        argv += ["--state-dir", str(self.root / state)]
        if sources:
            argv += ["--sources", str(self.registry_path)]
        if manifest:
            argv += ["--fixture-manifest", str(manifest)]
        child = subprocess.run(argv, input=json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=BFF, timeout=60)
        assert child.returncode == expected, (command, child.returncode, child.stdout.decode(), child.stderr.decode())
        return json.loads(child.stdout) if child.stdout else None


def exact_check(document, start, end, allowed=True):
    sys.path.insert(0, str(BFF.parent / "ai-worker/src"))
    from zoop_ai.contracts import Document, SummaryAnswer, exact
    doc = Document.model_validate(document)
    candidate = SummaryAnswer.model_validate({"text": "합성 사실", "claims": [{"claimId": "claim", "text": "합성 사실", "assertionKind": "fact", "evidenceIds": ["e"]}], "citations": [{"evidenceId": "e", "documentId": doc.document_id, "documentVersion": doc.document_version, "textArtifactId": doc.text_artifact_id, "offsetUnit": "unicode_code_point", "start": start, "end": end, "quote": doc.text[start:end], "inputKind": "body", "rawLocatorIds": [r.locator_id for r in doc.raw_locators]}], "limitations": []})
    if allowed:
        exact(candidate, doc)
    else:
        try:
            exact(candidate, doc)
        except ValueError as exc:
            assert str(exc) == "raw_locator_mismatch"
        else:
            raise AssertionError("generated separator accepted")


def smoke(root):
    kit = OfflineFixture(root)
    manifest = kit.manifest("main", [[kit.item(), kit.item("c2", "supplier-2", ref="pdf", media="application/pdf")]], bodies={"html": HTML, "pdf": authored_pdf("repeat", "repeat", "")})
    request = kit.request(manifest)
    first = kit.cli("run", request, manifest=manifest)
    assert first["state"] == "complete" and first["counts"]["newTextVersions"] == 2
    assert kit.cli("run", request, manifest=manifest) == first
    replay = kit.cli("run", kit.request(manifest, "replay", 1), manifest=manifest)
    assert replay["completion"] == "nonzero-discovery" and replay["counts"]["reusedVersions"] == 2 and replay["counts"]["newTextVersions"] == 0
    html, pdf = first["documentRefs"]
    selector = kit.selector(documentId=html["documentId"], documentVersion=html["documentVersion"])
    inspected = kit.cli("inspect", selector)
    doc = inspected["document"]
    assert doc["text"] == "반복 & 반복😀 꼬리\n뒤\n반복😀 둘째"
    assert inspected["locatorMetadata"]["rawHash"] == sha(HTML) != doc["sourceHash"]
    # Same string occurs twice: resolve the declared second interval, not a search.
    start = doc["text"].rindex("반복😀")
    locator = next(r for r in doc["rawLocators"] if r["start"] <= start < start + 3 <= r["end"])
    resolved = kit.cli("inspect", {**selector, "locatorId": locator["locatorId"], "start": start, "end": start + 3})["resolvedLocator"]
    assert resolved["segments"][0]["domPath"] == "/html/body/article/p[2]" and resolved["segments"][0]["sourceStart"] == 0
    assert resolved["segments"][0]["text"] == "반복😀"
    exact_check(doc, 0, doc["rawLocators"][0]["end"])
    exact_check(doc, 0, len(doc["text"]), False)
    pdf_selector = kit.selector(documentId=pdf["documentId"], documentVersion=pdf["documentVersion"])
    pdf_inspect = kit.cli("inspect", pdf_selector)
    pd = pdf_inspect["document"]
    assert pd["text"] == "repeat\nrepeat" and pdf_inspect["locatorMetadata"]["pageCount"] == 3 and pdf_inspect["locatorMetadata"]["emptyPageCount"] == 1
    loc = pd["rawLocators"][1]
    mapped = kit.cli("inspect", {**pdf_selector, "locatorId": loc["locatorId"], "start": loc["start"], "end": loc["end"]})["resolvedLocator"]
    assert mapped["segments"][0]["pageNumber"] == 2 and mapped["segments"][0]["text"] == "repeat"
    exact_check(pd, 0, 6)
    exact_check(pd, 0, len(pd["text"]), False)
    changed = kit.manifest("changed", [[kit.item()]], bodies={"html": HTML.replace("꼬리".encode(), "변경".encode())})
    new = kit.cli("run", kit.request(changed, "changed", 2), manifest=changed)
    assert new["documentRefs"][0]["documentId"] == html["documentId"] and new["documentRefs"][0]["documentVersion"] != html["documentVersion"]
    assert kit.cli("inspect", selector)["document"] == doc
    # Immutable requests cannot be reinterpreted as a retry.
    conflict = kit.cli("run", {**request, "fixtureManifestHash": sha(changed.read_bytes())}, manifest=changed, expected=2)
    assert conflict["error"]["code"] == "round_input_conflict"
    zero = kit.manifest("zero", [[]])
    result = kit.cli("run", kit.request(zero, "zero", 3), manifest=zero)
    assert result["state"] == "complete" and result["completion"] == "source-zero"
    failed = kit.manifest("failed", [[]], statuses=["failed"])
    result = kit.cli("run", kit.request(failed, "failed", 4), manifest=failed)
    assert result["state"] == "incomplete" and result["checkpoint"]["revision"] == 4
    partial = kit.manifest("partial", [[kit.item()]], statuses=["partial"])
    result = kit.cli("run", kit.request(partial, "partial", 4), manifest=partial)
    assert result["state"] == "incomplete" and result["counts"]["textReady"] == 1 and result["checkpoint"]["revision"] == 4
    held = kit.manifest("hold", [[kit.item(ref="bad", media="application/pdf")]], bodies={"bad": b"not a PDF"})
    result = kit.cli("run", kit.request(held, "held", 4), manifest=held)
    assert result["state"] == "complete" and result["counts"]["held"] == 1 and result["counts"]["textReady"] == 0
    # Actual process death before/after every durable boundary; remove inputs after save.
    for boundary in ("receipt", "raw", "version", "checkpoint"):
        m = kit.manifest("crash-" + boundary, [[kit.item()]])
        state = "crash-" + boundary
        req = kit.request(m)
        kit.cli("run", req, state=state, manifest=m, crash=boundary, expected=75)
        if boundary != "receipt":
            for ref in json.loads(m.read_bytes())["documents"].values():
                (kit.inputs / ref["file"]).unlink()
        for p in json.loads(m.read_bytes())["pages"]:
            (kit.inputs / p["response"]["file"]).unlink()
        m.unlink()
        recovered = kit.cli("resume", kit.selector(), state=state)
        assert recovered["state"] == "complete" and recovered["counts"]["newTextVersions"] == 1
        assert kit.cli("resume", kit.selector(), state=state) == recovered
    stale = kit.manifest("stale", [[kit.item()]])
    kit.cli("run", kit.request(stale, "old"), state="stale-state", manifest=stale, crash="raw", expected=75)
    latest = kit.cli("run", kit.request(stale, "new"), state="stale-state", manifest=stale)
    rejected = kit.cli("resume", kit.selector("old"), state="stale-state")
    assert rejected["failure"]["code"] == "checkpoint_stale" and rejected["checkpoint"]["revision"] == latest["checkpoint"]["revision"] == 1
    kit.registry["sources"][0]["grant"]["enabled"] = False
    kit.save_registry()
    assert kit.cli("inspect", selector, expected=2)["error"]["code"] == "source_unauthorized"
    kit.registry["sources"] = []
    kit.save_registry()
    assert kit.cli("inspect", selector, expected=2)["error"]["code"] == "source_unauthorized"
    kit.cli("resume", kit.selector(), sources=False, expected=2)
    # Dedicated stores cannot accidentally use app/S1 directories.
    for name, filename in (("app-state", "app.sqlite3"), ("s1-state", "worker.sqlite3")):
        folder = kit.root / name
        folder.mkdir()
        sentinel = folder / filename
        sentinel.write_bytes(b"untouched state sentinel")
        assert kit.cli("resume", kit.selector(), state=name, expected=2)["error"]["code"] == "state_namespace_conflict"
        assert sentinel.read_bytes() == b"untouched state sentinel"
    assert all(p.name.startswith("ingestion.") for p in (kit.root / "state").iterdir())
    return {"schemaVersion": SCHEMA, "status": "passed", "preparedDocuments": 2, "interruptionBoundaries": ["receipt", "raw", "version", "checkpoint"], "providerCalls": 0, "modelCalls": 0, "appAndS1State": "sentinels unchanged; dedicated ingestion files only", "originalPoc": "installed pinned parsers only; no original state imported", "checks": ["same cursor replay", "new body version", "distinct supplier documents", "zero/failure/partial/parse hold", "resume without saved input files", "stale checkpoint", "complete registry revocation/omission", "HTML entity/tail/repeated Korean emoji coordinates", "PDF repeated page text and empty page", "S1 exact accepts mapped and rejects generated separators"]}


def review_smoke(root):
    raw = '<html><body><article id="a">이전 A😀</article><article id="b">현재 B😀</article></body></html>'.encode()
    checked = []
    for mode, xpath in (("ready", '//article[@id="a"]'), ("held", None)):
        kit = OfflineFixture(root / ("scope-" + mode))
        base = kit.registry["sources"][0]["scopes"][0]
        a_scope = {**base, "scopeId": "a", "articleXPath": xpath}
        b_scope = {**base, "scopeId": "b", "articleXPath": '//article[@id="b"]'}
        kit.registry["sources"][0]["scopes"] = [a_scope, b_scope]
        kit.save_registry()
        results = []
        for scope in (a_scope, b_scope):
            if scope["scopeId"] == "b":
                kit.registry["sources"][0]["scopes"] = [b_scope]
                kit.save_registry()
            name = "scope-" + scope["scopeId"]
            manifest = kit.manifest(name, [[kit.item()]], bodies={"html": raw})
            payload = json.loads(manifest.read_bytes())
            payload["scopeId"] = scope["scopeId"]
            manifest.write_bytes(json_bytes(payload))
            request = {**kit.request(manifest, name), "scopeId": scope["scopeId"]}
            results.append(kit.cli("run", request, manifest=manifest))
        a, b = (result["documentRefs"][0] for result in results)
        assert a["documentId"] == b["documentId"] and a["rawVersion"] == b["rawVersion"]
        assert results[1]["counts"]["newTextVersions"] == 1 and results[1]["counts"]["reusedVersions"] == 0
        output = kit.cli("inspect", kit.selector("scope-b", documentId=b["documentId"], documentVersion=b["documentVersion"]))
        assert output["document"]["text"] == "현재 B😀"
        assert output["locatorMetadata"]["parserProfile"]["articleXPath"] == b_scope["articleXPath"]
        if mode == "ready":
            assert a["documentVersion"] != b["documentVersion"]
            assert kit.cli("inspect", kit.selector("scope-a", documentId=a["documentId"], documentVersion=a["documentVersion"]), expected=2)["error"]["code"] == "source_unauthorized"
        else:
            assert a["hold"] == "article_scope_ambiguous_or_missing" and b["hold"] is None
        checked.append("revoked scope A " + mode + " does not supply scope B text/hold")
    kit = OfflineFixture(root / "shared-body")
    manifest = kit.manifest("shared", [[kit.item(), kit.item("c2", "supplier-2")]])
    payload = json.loads(manifest.read_bytes())
    kit.cli("run", kit.request(manifest), manifest=manifest, crash="raw", expected=75)
    for page in payload["pages"]:
        (kit.inputs / page["response"]["file"]).unlink()
    (kit.inputs / payload["documents"]["html"]["file"]).unlink()
    manifest.unlink()
    recovered = kit.cli("resume", kit.selector())
    assert recovered["state"] == "complete" and recovered["counts"]["textReady"] == 2
    assert len({ref["documentId"] for ref in recovered["documentRefs"]}) == 2
    assert len({ref["documentVersion"] for ref in recovered["documentRefs"]}) == 2
    assert kit.cli("resume", kit.selector()) == recovered
    checked.append("shared body resumes two distinct suppliers after first raw commit and input removal")
    return checked


def main():
    with tempfile.TemporaryDirectory(prefix="zoop-s2-ingestion-smoke-") as temporary:
        root = Path(temporary).resolve()
        result = smoke(root)
        result["reviewRegressions"] = review_smoke(root)
    assert not root.exists()
    result["temporaryStateCleanup"] = {"removed": True, "root": str(root)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
