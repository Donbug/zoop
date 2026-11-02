"""Native HTML and PDF preparation with exact Unicode source spans. No private PoC import, no hidden fallback.

The profile below is persisted in every round and prepared version, so any change to extraction behaviour MUST change one of
its labels (htmlScope, mappingVersion, pdfExtraction). A round or version recorded under another profile is never
re-interpreted: resume refuses it (`parser_profile_changed`) while its stored versions stay readable.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

from .ingestion_contracts import (MAX_RAW, MAX_TEXT, IngestionFailure, TextProjection, ScopeTextProjection,
    PdfBodyProjection, PdfBodyMember, PdfRightsReceipt, HtmlBodyProjection, JsonHtmlBodyProjection,
    HtmlBodyMember, HtmlReviewUnit, byte_hash, digest)
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


def profile(article_xpath: str | None = None, projection: ScopeTextProjection | None = None) -> dict:
    try:
        lxml_version, pypdf_version = version("lxml"), version("pypdf")
    except PackageNotFoundError as exc:
        raise IngestionFailure("input_or_configuration_invalid") from exc
    if any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in (lxml_version, pypdf_version)):
        raise IngestionFailure("input_or_configuration_invalid")
    result = {"parser": PARSER, "lxml": lxml_version, "pypdf": pypdf_version, "mappingVersion": MAPPING,
              "htmlDecoding": "utf-8-strict", "htmlScope": HTML_SCOPE, "pdfExtraction": PDF_EXTRACTION, "articleXPath": article_xpath}
    if projection is not None:
        result["textProjection"] = {"profile": projection.profile, "descriptorHash": digest(projection.wire())}
    return result


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


def _html(raw: bytes, xpath: str | None, projection: TextProjection | None = None, *,
          body_member: HtmlBodyMember | None = None, body_projection: HtmlBodyProjection | None = None,
          review_paths: list[str] | None = None, representation: dict | None = None) -> dict:
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
        excluded = set()

        def copy(node, slot):
            if (node, slot) in indices:
                i = indices[(node, slot)]
                parts.append((i, 0, len(sources[i]["text"])))

        def visit(node):
            tag = node.tag if isinstance(node.tag, str) else ""
            label = f"{node.get('id', '')} {node.get('class', '')}" if tag else ""
            if node in excluded:
                parts.append(None)
                return
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
        limitations = ["decoded HTML text-node coordinates, not markup byte offsets", f"static {kind}; no JavaScript or image/OCR coverage"]
        baseline = _mapped(parts, sources, limitations)
        if review_paths is not None or body_projection is not None:
            return _positive_html(tree, scope, baseline, body_member, body_projection, review_paths, representation)
        if projection is None:
            return baseline
        parent = projection.parent
        representation_hash = digest(sources)
        mapping_hash = digest({"representationHash": representation_hash, "segments": baseline["segments"], "runs": baseline["runs"]})
        if (digest(baseline["text"]), representation_hash, mapping_hash) != (parent.source_hash, parent.representation_hash, parent.mapping_hash):
            raise IngestionFailure("projection_parent_mismatch")
        paths = set(projection.excluded_caption_paths)
        captions = list(scope.iter("figcaption"))
        if {original.getpath(node) for node in captions} != paths:
            raise IngestionFailure("projection_caption_boundary_incomplete")
        for node in captions:
            # Compare canonical original paths, never execute descriptor text as XPath.
            figure = node.getparent()
            if (figure is None or figure.tag != "figure" or not figure.xpath(".//img")
                    or figure.xpath(".//video | .//audio | .//object | .//embed | .//iframe")
                    or not any(child.text or (child is not node and child.tail) for child in node.iter())):
                raise IngestionFailure("projection_caption_boundary_unsupported")
            excluded.add(node)
        parts.clear()
        visit(scope)
        projected = _mapped(parts, sources, limitations)
        projected["textProjection"] = {"profile": projection.profile, "descriptorHash": digest(projection.wire()),
            "parentDocumentVersion": parent.document_version, "boundaryDecisionRevision": projection.boundary_decision.revision,
            "rightsReceiptHash": projection.rights_receipt.sha256,
            "excludedSourceSlots": [{k: source[k] for k in ("domPath", "slot")} for source in sources
                if any(source["domPath"].startswith(path + "/") or (source["domPath"] == path and source["slot"] == "text") for path in paths)]}
        return projected
    except (UnicodeError, etree.LxmlError, ValueError, RecursionError) as exc:
        raise IngestionFailure("html_extraction_failed") from exc


def _decode_ec_json(raw: bytes, expected_reference: str, expected_language: str) -> bytes:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def finite(value):
        raise ValueError("nonfinite JSON constant")

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("nonfinite JSON number")
        return parsed

    def unicode_strings(value):
        if isinstance(value, str):
            value.encode("utf-8", errors="strict")
        elif isinstance(value, dict):
            for key, child in value.items():
                unicode_strings(key)
                unicode_strings(child)
        elif isinstance(value, list):
            for child in value:
                unicode_strings(child)

    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique, parse_constant=finite, parse_float=number)
        unicode_strings(value)
        if not isinstance(value, dict) or not isinstance(value.get("docuLanguageResource"), dict):
            raise ValueError("EC object required")
        resource = value["docuLanguageResource"]
        if value.get("refCd") != expected_reference or resource.get("language") != expected_language:
            raise IngestionFailure("projection_reference_or_language_mismatch")
        member = resource.get("htmlContent")
        if not isinstance(member, str) or not member.strip():
            raise ValueError("HTML member required")
        decoded = member.encode("utf-8")
        if len(decoded) > MAX_RAW:
            raise ValueError("HTML member limit")
        return decoded
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise IngestionFailure("projection_json_invalid") from exc


def _positive_html(tree, scope, baseline: dict, member: HtmlBodyMember | None,
                   projection: HtmlBodyProjection | None, review_paths: list[str] | None,
                   representation: dict | None) -> dict:
    original = tree.getroottree()
    nodes = {original.getpath(node): node for node in scope.iter()}
    sources = baseline["sources"]
    representation_hash = digest(sources)
    baseline_pins = {"sourceHash": digest(baseline["text"]), "representationHash": representation_hash,
        "mappingHash": digest({"representationHash": representation_hash, "segments": baseline["segments"], "runs": baseline["runs"]})}
    paths = review_paths if review_paths is not None else [unit.dom_path for unit in member.selected_units]
    roots = []
    for path in paths:
        node = nodes.get(path)
        if node is None or node.tag not in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            raise IngestionFailure("projection_whole_positive_unit_required")
        roots.append(node)
    root_set = set(roots)
    if len(root_set) != len(roots) or any(parent in root_set for node in roots for parent in node.iterancestors()):
        raise IngestionFailure("projection_disjoint_source_order_required")
    units, parts, copied_intervals = [], [], {}
    previous_clean_end = 0
    for ordinal, (path, node) in enumerate(zip(paths, roots)):
        for child in node.iter():
            tag = child.tag if isinstance(child.tag, str) else ""
            if (not tag or tag in _REMOVED_TAGS or tag in {"img", "video", "audio", "object", "embed", "svg"}
                    or _NOISE.search(f"{child.get('id', '')} {child.get('class', '')}")):
                raise IngestionFailure("projection_unsafe_unit")
        selected = [(index, source) for index, source in enumerate(sources)
                    if source["domPath"].startswith(path + "/") or
                    (source["domPath"] == path and source["slot"] == "text")]
        indices = {index for index, _ in selected}
        segments = [segment for segment in baseline["segments"] if segment["sourceIndex"] in indices]
        if not segments or segments[0]["cleanStart"] < previous_clean_end:
            raise IngestionFailure("projection_disjoint_source_order_required")
        # Preserve the baseline's barriers inside a unit as well as between whole units.
        unit_parts, end = [], None
        for segment in segments:
            if end != segment["cleanStart"] or any(run["start"] == segment["cleanStart"] for run in baseline["runs"]):
                unit_parts.append(None)
            unit_parts.append((segment["sourceIndex"], segment["sourceStart"], segment["sourceEnd"]))
            end = segment["cleanEnd"]
        prepared = _mapped(unit_parts, sources, baseline["limitations"])
        spans = []
        for segment in prepared["segments"]:
            interval = (segment["sourceStart"], segment["sourceEnd"])
            copied = copied_intervals.setdefault(segment["sourceIndex"], [])
            if any(interval[0] < end and start < interval[1] for start, end in copied):
                raise IngestionFailure("projection_disjoint_source_order_required")
            copied.append(interval)
            source = sources[segment["sourceIndex"]]
            spans.append({"domPath": source["domPath"], "slot": source["slot"],
                "sourceStart": segment["sourceStart"], "sourceEnd": segment["sourceEnd"],
                "textUtf8Sha256": byte_hash(source["text"][segment["sourceStart"]:segment["sourceEnd"]].encode("utf-8"))})
        unit = {"unitId": path, "domPath": path, "classification": "commission-narrative",
                "spans": spans, "textUtf8Sha256": byte_hash(prepared["text"].encode("utf-8"))}
        if member is not None:
            declared = member.selected_units[ordinal]
            unit.update(unitId=declared.unit_id, classification=declared.classification)
            if unit != declared.wire():
                raise IngestionFailure("projection_whole_positive_unit_required")
        units.append(HtmlReviewUnit.model_validate(unit).wire())
        parts.append(None)
        run_starts = {run["start"] for run in prepared["runs"]}
        for segment in prepared["segments"]:
            if segment["cleanStart"] in run_starts:
                parts.append(None)
            parts.append((segment["sourceIndex"], segment["sourceStart"], segment["sourceEnd"]))
        previous_clean_end = segments[-1]["cleanEnd"]
    output = _mapped(parts, sources, baseline["limitations"])
    if review_paths is not None:
        return {"status": "review", "baseline": baseline_pins, "selectedUnits": units,
                "selectionHash": digest(units), "textUtf8Sha256": byte_hash(output["text"].encode("utf-8")),
                "text": output["text"], "representation": representation}
    expected = member.representation
    if any(baseline_pins[key] != expected.wire()[key] for key in baseline_pins):
        raise IngestionFailure("projection_parent_mismatch")
    if expected.parser_profile.wire() != profile(original.getpath(scope)):
        raise IngestionFailure("projection_parent_mismatch")
    if representation is not None:
        if any(expected.wire().get(key) != value for key, value in representation.items() if key != "rawHash"):
            raise IngestionFailure("projection_representation_mismatch")
        for source in sources:
            source.update(representation)
    output["textProjection"] = {"profile": projection.profile, "descriptorHash": digest(projection.wire()),
        "parent": member.parent.wire(), "representation": expected.wire(), "parentBindingHash": member.parent_binding_hash,
        "selectionHash": member.boundary_decision.selection_hash, "boundaryDecisionRevision": member.boundary_decision.revision,
        "rightsReceiptHash": member.rights_receipt.sha256, "retainedUnits": units}
    return output


def review_html_body(raw: bytes, media_type: str, xpath: str, paths: list[str], *,
                     expected_reference: str | None = None, expected_language: str | None = None) -> dict:
    """Offline representation review; produces neither native identities nor acquisition/rights receipts."""
    if len(raw) > MAX_RAW:
        raise IngestionFailure("raw_byte_limit")
    representation = None
    html_raw = raw
    if media_type == "application/json":
        if xpath != "/html/body" or expected_reference is None or expected_language is None:
            raise IngestionFailure("projection_json_scope_required")
        html_raw = _decode_ec_json(raw, expected_reference, expected_language)
        representation = {"decoder": "ec-presscorner-json-html-1", "jsonPointer": "/docuLanguageResource/htmlContent",
            "decodedHtmlUtf8Sha256": byte_hash(html_raw), "expectedReference": expected_reference,
            "expectedLanguage": expected_language}
    elif media_type != "text/html":
        raise IngestionFailure("projection_media_unsupported")
    reviewed = _html(html_raw, xpath, review_paths=paths, representation=representation)
    reviewed.update(rawHash=byte_hash(raw), parserProfile=profile(xpath))
    return reviewed


def _pdf(raw: bytes, projection: PdfBodyProjection | None = None, member: PdfBodyMember | None = None,
         rights: PdfRightsReceipt | None = None) -> dict:
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
    if projection is not None:
        if member is None or rights is None or member not in projection.members:
            raise IngestionFailure("projection_member_missing")
        parent = member.parent
        representation = digest(sources)
        mapping = digest({"representationHash": representation, "segments": output["segments"], "runs": output["runs"]})
        if ((digest(output["text"]), representation, mapping) !=
                (parent.source_hash, parent.representation_hash, parent.mapping_hash)):
            raise IngestionFailure("projection_parent_mismatch")
        if ((rights.body_sha256, rights.parent_document_version, rights.selection_hash) !=
                (byte_hash(raw), parent.document_version, member.boundary_decision.selection_hash)):
            raise IngestionFailure("projection_rights_receipt_invalid")
        pages = {source["pageNumber"]: (i, source) for i, source in enumerate(sources)}
        coverage = {number: [] for number in pages}
        units = {}
        for unit in rights.review_units:
            if unit.unit_id in units or not unit.review_basis.strip():
                raise IngestionFailure("projection_review_units_invalid")
            units[unit.unit_id] = unit
            previous = None
            for span in unit.spans:
                page = pages.get(span.page_number)
                if page is None:
                    raise IngestionFailure("projection_review_units_invalid")
                _, source = page
                if (span.source_end > len(source["text"]) or span.page_text_hash != source["pageTextHash"]
                        or byte_hash(source["text"][span.source_start:span.source_end].encode("utf-8")) != span.text_utf8_sha256
                        or (previous is not None and (span.page_number, span.source_start) < previous)):
                    raise IngestionFailure("projection_review_units_invalid")
                previous = (span.page_number, span.source_end)
                coverage[span.page_number].append((span.source_start, span.source_end))
        for number, intervals in coverage.items():
            text = pages[number][1]["text"]
            end = 0
            for start, stop in sorted(intervals):
                if start < end or text[end:start].strip():
                    raise IngestionFailure("projection_review_coverage_invalid")
                end = stop
            if text[end:].strip():
                raise IngestionFailure("projection_review_coverage_invalid")
        selected = {}
        for span in member.allowed_ranges:
            selected.setdefault(span.review_unit_id, []).append({k: v for k, v in span.wire().items() if k != "reviewUnitId"})
        for uid, spans in selected.items():
            unit = units.get(uid)
            if (unit is None or unit.classification not in
                    {"original-dateline", "commission-narrative", "public-official-statement"}
                    or spans != [span.wire() for span in unit.spans]):
                raise IngestionFailure("projection_whole_positive_unit_required")
        parts = []
        previous = None
        for span in member.allowed_ranges:
            index, source = pages[span.page_number]
            if not any(segment["sourceIndex"] == index and
                    segment["sourceStart"] <= span.source_start < span.source_end <= segment["sourceEnd"]
                    for segment in output["segments"]):
                raise IngestionFailure("projection_range_outside_parent_mapping")
            if previous != (index, span.source_start):
                parts.append(None)
            parts.append((index, span.source_start, span.source_end))
            previous = (index, span.source_end)
        projected = _mapped(parts, sources, output["limitations"])
        projected.update(counts)
        projected["textProjection"] = {"profile": projection.profile, "descriptorHash": digest(projection.wire()),
            "parentDocumentId": parent.document_id, "parentRawVersion": parent.raw_version,
            "parentDocumentVersion": parent.document_version, "selectionHash": member.boundary_decision.selection_hash,
            "boundaryDecisionRevision": member.boundary_decision.revision, "rightsReceiptHash": member.rights_receipt.sha256,
            "retainedSourceRanges": [span.wire() for span in member.allowed_ranges]}
        return projected
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


def prepare(raw: bytes, media_type: str, xpath: str | None, *, retained_schema: str | None = None,
            projection: ScopeTextProjection | None = None, pdf_member: PdfBodyMember | None = None,
            pdf_rights: PdfRightsReceipt | None = None, html_member: HtmlBodyMember | None = None) -> dict:
    if len(raw) > MAX_RAW:
        raise IngestionFailure("raw_byte_limit")
    if isinstance(projection, HtmlBodyProjection):
        is_json = isinstance(projection, JsonHtmlBodyProjection)
        if (media_type != ("application/json" if is_json else "text/html") or
                html_member is None or html_member not in projection.members or
                (is_json and xpath != "/html/body")):
            raise IngestionFailure("projection_media_unsupported")
        if byte_hash(raw) != html_member.parent.raw_hash:
            raise IngestionFailure("projection_parent_mismatch")
        if html_member.boundary_decision.status != "approved":
            raise IngestionFailure("projection_boundary_review_required")
        representation = None
        html_raw = raw
        if is_json:
            expected = html_member.representation
            html_raw = _decode_ec_json(raw, expected.expected_reference, expected.expected_language)
            representation = {"rawHash": byte_hash(raw), "decoder": expected.decoder, "jsonPointer": expected.json_pointer,
                "decodedHtmlUtf8Sha256": byte_hash(html_raw), "expectedReference": expected.expected_reference,
                "expectedLanguage": expected.expected_language}
        return _html(html_raw, xpath, body_member=html_member, body_projection=projection, representation=representation)
    if projection is not None:
        expected = "application/pdf" if isinstance(projection, PdfBodyProjection) else "text/html"
        if media_type != expected or (expected == "application/pdf" and xpath is not None):
            raise IngestionFailure("projection_media_unsupported")
    if media_type == "text/markdown":
        return _markdown(raw, official=retained_schema == "zoop-official-source-record-1")
    if media_type == "text/html":
        return _html(raw, xpath, projection)
    if media_type == "application/pdf":
        return _pdf(raw, projection, pdf_member, pdf_rights)
    raise IngestionFailure("media_type_unsupported")
