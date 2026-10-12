"""One version-specific adapter for installed PoC safeguards, with exact source spans."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from importlib.metadata import distribution, version
from pathlib import Path

from .ingestion_contracts import MAX_RAW, MAX_TEXT, IngestionFailure, canonical, digest

PIN = "fa446e7c72edfa06ec1a0e8e999199a21d31c695"
MAPPING = "unicode-copy-segments-1"


def profile(article_xpath: str | None = None) -> dict:
    # Never load the original checkout through PYTHONPATH or use a live collector.
    from importlib.util import find_spec
    try:
        installed = distribution("investmate-poc")
        spec = find_spec("investmate")
        package = Path(installed.locate_file("investmate")).resolve()
        if spec is None or spec.origin is None or Path(spec.origin).resolve().parent != package or "InvestMateLogicTest" in str(package):
            raise IngestionFailure("pinned_parser_unavailable")
        origin = json.loads(installed.read_text("direct_url.json") or "{}")
        from investmate import crawler, fetching, source_pdf
    except (ImportError, ValueError, OSError) as exc:
        raise IngestionFailure("pinned_parser_unavailable") from exc
    if origin.get("vcs_info", {}).get("commit_id") != PIN or any("InvestMateLogicTest" in str(Path(m.__file__).resolve()) for m in (crawler, fetching, source_pdf)):
        raise IngestionFailure("pinned_parser_unavailable")
    required = ((crawler, ("_scope", "_restricted", "_NOISE", "_BLOCKS")),
                (fetching, ("canonical_url",)),
                (source_pdf, ("_bounded_decoding", "_preflight_page", "MAX_PAGE_COUNT", "MAX_PDF_BYTES")))
    if any(not hasattr(module, name) for module, names in required for name in names):
        raise IngestionFailure("pinned_parser_unavailable")
    return {"pocCommit": PIN, "lxml": version("lxml"), "pypdf": version("pypdf"),
            "mappingVersion": MAPPING, "htmlDecoding": "utf-8-strict", "pdfExtraction": "page-text-1",
            "articleXPath": article_xpath}


def normalize_url(value: str, hosts: list[str]) -> str:
    from investmate.crawl_types import CrawlFailure
    from investmate.fetching import canonical_url
    try:
        normalized, host = canonical_url(value)
    except CrawlFailure as exc:
        raise IngestionFailure("source_url_invalid") from exc
    if host not in hosts:
        raise IngestionFailure("source_host_not_allowed")
    return normalized


def _mapped(parts: list, sources: list[dict], limitations: list[str]) -> dict:
    if len(parts) > 30_000 or len(sources) > 10_000:
        raise IngestionFailure("source_segment_limit")
    pieces, length, ends_newline = [], 0, False
    segments = []
    for part in parts:
        if part is None:
            if length and not ends_newline:
                pieces.append("\n")
                length += 1
                ends_newline = True
            # A copied newline also must not join across removed content.
            segments.append({"barrier": length})
            continue
        index, start, end = part
        value = sources[index]["text"][start:end]
        if value:
            segments.append({"cleanStart": length, "cleanEnd": length + len(value),
                             "sourceIndex": index, "sourceStart": start, "sourceEnd": end})
            pieces.append(value)
            length += len(value)
            ends_newline = value.endswith("\n")
    text = "".join(pieces)
    left, right = len(text) - len(text.lstrip()), len(text.rstrip())
    text = text[left:right]
    mapped = []
    barriers = set()
    for segment in segments:
        if "barrier" in segment:
            barriers.add(segment["barrier"] - left)
            continue
        a, b = max(segment["cleanStart"], left), min(segment["cleanEnd"], right)
        if a < b:
            start = segment["sourceStart"] + a - segment["cleanStart"]
            mapped.append({"cleanStart": a - left, "cleanEnd": b - left, "sourceIndex": segment["sourceIndex"],
                           "sourceStart": start, "sourceEnd": start + b - a})
    if not text or not mapped:
        raise IngestionFailure("no_usable_body", {"sources": sources, "limitations": limitations})
    if len(text) > MAX_TEXT:
        raise IngestionFailure("text_output_limit")
    runs = []
    for index, segment in enumerate(mapped):
        source = sources[segment["sourceIndex"]]
        a, b = segment["cleanStart"], segment["cleanEnd"]
        if text[a:b] != source["text"][segment["sourceStart"]:segment["sourceEnd"]]:
            raise IngestionFailure("source_mapping_invalid")
        if runs and runs[-1]["end"] == a and a not in barriers and source.get("pageNumber") == sources[mapped[runs[-1]["lastSegment"]]["sourceIndex"]].get("pageNumber"):
            runs[-1]["end"] = b
            runs[-1]["lastSegment"] = index
        else:
            runs.append({"start": a, "end": b, "lastSegment": index})
    return {"text": text, "sources": sources, "segments": mapped,
            "runs": [{"start": r["start"], "end": r["end"]} for r in runs], "limitations": limitations}


def _html(raw: bytes, url: str, xpath: str | None) -> dict:
    from investmate import crawler
    from investmate.crawl_types import CrawlOptions
    from lxml import etree, html
    from urllib.parse import urlsplit
    try:
        decoded = raw.decode("utf-8", errors="strict")
        tree = html.document_fromstring(decoded, parser=html.HTMLParser(no_network=True, recover=True))
        if crawler._restricted(tree):
            raise IngestionFailure("access_restricted")
        limitations = []
        host = (urlsplit(url).hostname or "").lower()
        options = CrawlOptions(article_xpaths={host: xpath} if xpath else {})
        scope, kind = crawler._scope(tree, url, options, limitations)
        if scope is None or limitations:
            raise IngestionFailure("article_scope_ambiguous_or_missing")
        sources, indices = [], {}
        original = tree.getroottree()
        for node in scope.iter():
            for slot in ("text", "tail"):
                value = getattr(node, slot)
                if value:
                    indices[(node, slot)] = len(sources)
                    sources.append({"domPath": original.getpath(node), "slot": slot, "text": value})
        if sum(len(s["text"]) for s in sources) > MAX_TEXT:
            raise IngestionFailure("source_representation_limit")
        parts = []

        def copy(node, slot):
            if (node, slot) in indices:
                i = indices[(node, slot)]
                parts.append((i, 0, len(sources[i]["text"])))

        def visit(node):
            tag = node.tag if isinstance(node.tag, str) else ""
            label = f"{node.get('id', '')} {node.get('class', '')}" if tag else ""
            if not tag or tag in {"script", "style", "nav", "aside", "footer", "form", "iframe", "noscript", "template"} or crawler._NOISE.search(label):
                parts.append(None)
                return
            if tag in crawler._BLOCKS or tag == "br":
                parts.append(None)
            copy(node, "text")
            for child in node:
                visit(child)
                copy(child, "tail")
            if tag in crawler._BLOCKS or tag in {"td", "th"}:
                parts.append(None)

        visit(scope)
        return _mapped(parts, sources, ["decoded HTML text-node coordinates, not markup byte offsets", f"static {kind}; no JavaScript or image/OCR coverage"])
    except (UnicodeError, etree.LxmlError, ValueError, RecursionError) as exc:
        raise IngestionFailure("html_extraction_failed") from exc


def _pdf_child(raw: bytes) -> dict:
    from investmate import source_pdf as pdf
    from pypdf import PdfReader
    from pypdf.errors import DependencyError, LimitReachedError, PyPdfError
    try:
        profile()
        if len(raw) > min(MAX_RAW, pdf.MAX_PDF_BYTES):
            raise IngestionFailure("pdf_byte_limit")
        sources = []
        total = 0
        with pdf._bounded_decoding() as budget:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise IngestionFailure("encrypted_pdf")
            if len(reader.pages) > pdf.MAX_PAGE_COUNT:
                raise IngestionFailure("pdf_page_limit")
            for number, page in enumerate(reader.pages, 1):
                pdf._preflight_page(page, budget)
                text = page.extract_text() or ""
                total += len(text)
                if total > MAX_TEXT:
                    raise IngestionFailure("text_output_limit")
                sources.append({"pageNumber": number, "pageTextHash": digest(text), "text": text})
        return {"sources": sources}
    except pdf._PdfPolicyError as exc:
        return {"error": exc.code}
    except IngestionFailure as exc:
        return {"error": exc.code}
    except LimitReachedError:
        return {"error": "pdf_decoded_stream_limit"}
    except (PyPdfError, DependencyError, ValueError, TypeError, OSError, RuntimeError, LookupError, ArithmeticError, MemoryError):
        return {"error": "pdf_extraction_failed"}


def prepare(raw: bytes, media_type: str, url: str, xpath: str | None) -> dict:
    if len(raw) > MAX_RAW:
        raise IngestionFailure("raw_byte_limit")
    if media_type == "text/html":
        return _html(raw, url, xpath)
    # Only this supervised child touches PdfReader. Its trusted output is bounded
    # by page and aggregate character limits; it emits no raw parser exception.
    try:
        child = subprocess.run([sys.executable, "-m", __name__], input=raw, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=30, check=False)
        if child.returncode != 0 or len(child.stdout) > 6 * MAX_TEXT + 100_000:
            raise IngestionFailure("pdf_child_failed_or_output_limit")
        extracted = json.loads(child.stdout)
    except subprocess.TimeoutExpired as exc:
        raise IngestionFailure("pdf_parser_timeout") from exc
    except (ValueError, OSError) as exc:
        raise IngestionFailure("pdf_child_failed") from exc
    if "error" in extracted:
        raise IngestionFailure(extracted["error"])
    sources = extracted["sources"]
    parts = []
    for i, source in enumerate(sources):
        parts.append(None)
        text = source["text"]
        start, end = len(text) - len(text.lstrip()), len(text.rstrip())
        parts.append((i, start, end))
    try:
        output = _mapped(parts, sources, ["page-extracted Unicode coordinates, not PDF bytes/glyph geometry/OCR", "extraction order is not verified visual reading order"])
    except IngestionFailure as exc:
        if exc.preparation is not None:
            exc.preparation["pageCount"] = len(sources)
            exc.preparation["emptyPageCount"] = sum(not s["text"].strip() for s in sources)
        raise
    output["pageCount"] = len(sources)
    output["emptyPageCount"] = sum(not s["text"].strip() for s in sources)
    return output


if __name__ == "__main__":
    raw = sys.stdin.buffer.read(MAX_RAW + 1)
    print(canonical(_pdf_child(raw)))
