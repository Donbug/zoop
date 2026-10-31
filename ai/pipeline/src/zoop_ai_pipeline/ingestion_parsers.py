"""Native HTML and PDF preparation with exact Unicode source spans. No private PoC import, no hidden fallback.

The profile below is persisted in every round and prepared version, so any change to extraction behaviour MUST change one of
its labels (htmlScope, mappingVersion, pdfExtraction). A round or version recorded under another profile is never
re-interpreted: resume refuses it (`parser_profile_changed`) while its stored versions stay readable.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

from .ingestion_contracts import MAX_RAW, MAX_TEXT, IngestionFailure
from .ingestion_url import canonical_url

PARSER = "zoop-native-parsers-1"
MAPPING = "unicode-copy-segments-1"
HTML_SCOPE = "native-article-scope-1"
PDF_EXTRACTION = "page-text-bounded-1"

_REMOVED_TAGS = frozenset({"script", "style", "nav", "aside", "footer", "form", "iframe", "noscript", "template"})
_BLOCK_TAGS = frozenset({"p", "div", "section", "article", "blockquote", "li", "h1", "h2", "h3", "h4", "h5", "h6", "figure", "figcaption",
                         "ul", "ol", "table", "thead", "tbody", "tfoot", "tr"})
_NOISE = re.compile(r"(?:^|[\s_-])(?:ads?|advertisement|advertising|banner|recommend(?:ed|ation|ations)?|related(?:-articles|-news)?|"
                    r"social|share|newsletter|comments?|navigation)(?:$|[\s_-])", re.IGNORECASE)
_RESTRICTED_TITLE = re.compile(r"access denied|just a moment|verify (?:you are|you're) human|captcha|로그인.*필요", re.IGNORECASE)
_RESTRICTED_MARKER = re.compile(r"(?:^|[\s_-])(?:paywall|login-required|subscription-required|captcha|challenge-form)(?:$|[\s_-])", re.IGNORECASE)


def profile(article_xpath: str | None = None) -> dict:
    try:
        lxml_version, pypdf_version = version("lxml"), version("pypdf")
    except PackageNotFoundError as exc:
        raise IngestionFailure("input_or_configuration_invalid") from exc
    if any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in (lxml_version, pypdf_version)):
        raise IngestionFailure("input_or_configuration_invalid")
    return {"parser": PARSER, "lxml": lxml_version, "pypdf": pypdf_version, "mappingVersion": MAPPING,
            "htmlDecoding": "utf-8-strict", "htmlScope": HTML_SCOPE, "pdfExtraction": PDF_EXTRACTION, "articleXPath": article_xpath}


def normalize_url(value: str, hosts: list[str]) -> str:
    normalized, host = canonical_url(value)
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


def _restricted(tree) -> bool:
    """Explicit public-page access blocks only (paywall, login wall, bot challenge); an ordinary login link is fine."""
    def closed(value) -> bool:
        if isinstance(value, dict):
            return value.get("isAccessibleForFree") in (False, "false", "False") or any(closed(child) for child in value.values())
        return isinstance(value, list) and any(closed(child) for child in value)

    for script in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            if closed(json.loads(script.text or "null")):
                return True
        except (ValueError, RecursionError):
            continue
    if _RESTRICTED_TITLE.search(" ".join(tree.xpath("//title/text()"))):
        return True
    return any(_RESTRICTED_MARKER.search(f"{node.get('id', '')} {node.get('class', '')}") for node in tree.xpath("//*[@id or @class]"))


def _scope(tree, xpath: str | None):
    """The single static article element, or (None, reason). Never a heuristic guess between competing candidates."""
    from lxml import etree, html
    if xpath:
        try:
            found = tree.xpath(xpath)
        except etree.XPathError:
            return None, "configured_xpath"
        nodes = [n for n in found if isinstance(n, html.HtmlElement)] if isinstance(found, list) else []
        return (nodes[0], "configured_xpath") if len(nodes) == 1 else (None, "configured_xpath")
    nodes = tree.xpath('//*[contains(concat(" ", normalize-space(@itemprop), " "), " articleBody ")]') or tree.xpath("//article")
    # Nested scopes are not independent candidates; stop as soon as two outermost scopes are found.
    candidates = set(nodes)
    outermost = None
    for node in nodes:
        if not any(parent in candidates for parent in node.iterancestors()):
            if outermost is not None:
                return None, "semantic_article"
            outermost = node
    return outermost, "semantic_article"


def _html(raw: bytes, xpath: str | None) -> dict:
    from lxml import etree, html
    try:
        tree = html.document_fromstring(raw.decode("utf-8", errors="strict"), parser=html.HTMLParser(no_network=True, recover=True))
        if _restricted(tree):
            raise IngestionFailure("access_restricted")
        scope, kind = _scope(tree, xpath)
        if scope is None:
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
            if not tag or tag in _REMOVED_TAGS or _NOISE.search(label):
                parts.append(None)
                return
            if tag in _BLOCK_TAGS or tag == "br":
                parts.append(None)
            copy(node, "text")
            for child in node:
                visit(child)
                copy(child, "tail")
            if tag in _BLOCK_TAGS or tag in {"td", "th"}:
                parts.append(None)

        visit(scope)
        return _mapped(parts, sources, ["decoded HTML text-node coordinates, not markup byte offsets", f"static {kind}; no JavaScript or image/OCR coverage"])
    except (UnicodeError, etree.LxmlError, ValueError, RecursionError) as exc:
        raise IngestionFailure("html_extraction_failed") from exc


def _pdf(raw: bytes) -> dict:
    # Only this supervised child touches PdfReader. Its trusted output is bounded by page and aggregate
    # character limits; it emits no raw parser exception and inherits no credentials from this process.
    environment = {k: os.environ[k] for k in ("PATH", "PYTHONPATH", "LANG", "LC_ALL") if k in os.environ}
    environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        child = subprocess.run([sys.executable, "-m", "zoop_ai_pipeline.ingestion_pdf"], input=raw, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=30, check=False, env=environment)
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
        parts.append((i, len(text) - len(text.lstrip()), len(text.rstrip())))
    counts = {"pageCount": len(sources), "emptyPageCount": sum(not s["text"].strip() for s in sources)}
    try:
        output = _mapped(parts, sources, ["page-extracted Unicode coordinates, not PDF bytes/glyph geometry/OCR", "extraction order is not verified visual reading order"])
    except IngestionFailure as exc:
        if exc.preparation is not None:
            exc.preparation.update(counts)
        raise
    output.update(counts)
    return output


def _markdown(raw: bytes, *, official: bool = False) -> dict:
    """Exact retained UTF-8 Markdown coordinates, never DOM or original HTTP byte spans."""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise IngestionFailure("markdown_extraction_failed") from exc
    if not text.strip():
        raise IngestionFailure("no_usable_body")
    if len(text) > MAX_TEXT:
        raise IngestionFailure("text_output_limit")
    representation = "official-derived-utf8-text-1" if official else "markdown-utf8-exact-1"
    limitations = (["exact Unicode coordinates in the separately retained official derived body artifact",
                    "original container/member/XPath coordinates remain in the pinned extraction envelope, not these citation offsets"]
                   if official else ["exact retained Markdown Unicode code points including syntax; not original HTML or byte coordinates",
                                     "provider extraction is a new representation; original HTML spans are unavailable"])
    return {"text": text, "sources": [{"representation": representation, "text": text}],
            "segments": [{"cleanStart": 0, "cleanEnd": len(text), "sourceIndex": 0, "sourceStart": 0, "sourceEnd": len(text)}],
            "runs": [{"start": 0, "end": len(text)}],
            "limitations": limitations}


def prepare(raw: bytes, media_type: str, xpath: str | None, *, retained_schema: str | None = None) -> dict:
    if len(raw) > MAX_RAW:
        raise IngestionFailure("raw_byte_limit")
    if media_type == "text/markdown":
        return _markdown(raw, official=retained_schema == "zoop-official-source-record-1")
    if media_type == "text/html":
        return _html(raw, xpath)
    if media_type == "application/pdf":
        return _pdf(raw)
    raise IngestionFailure("media_type_unsupported")
