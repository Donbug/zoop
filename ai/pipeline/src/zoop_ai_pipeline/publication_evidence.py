"""Publication evidence for new Markdown records; historical envelopes stay immutable."""
from __future__ import annotations

from datetime import datetime
from html import unescape
import json
import re
from urllib.parse import urljoin

from lxml import html

from . import news_archives as archives
from .extraction_fallback import _reject_page
from .ingestion_contracts import IngestionFailure, byte_hash, digest
from .news_sources import SourceDescriptor


def _title(value):
    return " ".join(unescape(value).split()).casefold() if isinstance(value, str) else None


def explicit_header(source, text):
    # A header must precede article prose, not be an arbitrary date somewhere in it.
    lines = [line.strip() for line in text.splitlines() if line.strip()][:12]
    found, header_lines = [], []
    for line in lines:
        line = re.sub(r"\\([\W_])", r"\1", line).strip("* ")
        header_lines.append(line)
        match = re.fullmatch(r"(?:Published(?: on)?|Publication date|Issued on)\s*:?\s+(.+)", line, re.I)
        if not match:
            if line.startswith(("# ", "By ")):
                continue
            break
        value = match[1].strip()
        if archives._PUBLICATION.fullmatch(value):
            found.append(archives._publication(value))
            continue
        for pattern in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
            try:
                found.append(datetime.strptime(value, pattern).date().isoformat())
                break
            except ValueError:
                continue
        else:
            if source == "france24":
                match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4}) - (\d{2}:\d{2})", value)
                if match:
                    day, month, year, minute = match.groups()
                    found.append(archives._publication(f"{year}-{month}-{day}T{minute}"))
    legacy = archives.markdown_publication(source, "\n".join(header_lines))
    if legacy is not None:
        found.append(legacy)
    return archives._published(found)


def _native_publication(source, page, descriptor):
    native = page.native_observation
    if (native.http_status != 200 or native.body is None or native.access != "public"
            or native.www_authenticate or native.known_unsent is not None):
        return None
    if (native.media_type or "").split(";", 1)[0].strip().lower() != "text/html":
        return None
    raw = native.body.decode("utf-8", errors="strict")
    _reject_page(raw, is_html=True)
    if native.final_url != page.requested_url or native.requested_url != page.requested_url:
        raise IngestionFailure("publication_source_mismatch")
    tree = html.document_fromstring(raw)
    identities = [urljoin(native.final_url, node.get("href")) for node in tree.xpath("//link[@href]")
                  if "canonical" in (node.get("rel") or "").lower().split()]
    identities += [node.get("content") for node in tree.xpath("//meta[@content]")
                   if (node.get("property") or node.get("name") or "").lower() == "og:url"]
    nodes = archives._article_nodes(tree)
    for node in nodes:
        for field in ("url", "mainEntityOfPage"):
            value = node.get(field)
            if isinstance(value, dict):
                value = value.get("@id")
            if value is not None:
                identities.append(value)
    if not identities or any(value != page.requested_url for value in identities):
        raise IngestionFailure("publication_source_mismatch")
    titles = [node.text for node in tree.xpath("//title")]
    titles += [node.get("content") for node in tree.xpath("//meta[@content]")
               if (node.get("property") or node.get("name") or "").lower() == "og:title"]
    titles += [node.get("headline") for node in nodes]
    if not page.metadata.title or _title(page.metadata.title) not in {_title(value) for value in titles}:
        raise IngestionFailure("publication_document_mismatch")
    dates = [node["datePublished"] for node in nodes if node.get("datePublished") is not None]
    archives._published(dates)
    return archives.article_metadata(source, native.body, native.final_url,
                                     descriptor=descriptor, require_body=False).published_at


def publication_evidence(source, page, *, descriptor=None):
    """Recompute exact publication and provenance, without rewriting provider metadata."""
    if page.backend != "deepseek-fetch" or page.format != "markdown" or page.provider_receipt is None:
        raise IngestionFailure("publication_representation_invalid")
    selected = archives._descriptor(source, descriptor)
    archives.validate_article_url(source, page.requested_url, descriptor=selected)
    _reject_page(page.retained_text, is_html=False, title=page.metadata.title)
    response = json.loads(page.provider_receipt.raw_response)
    for field in ("url", "sourceUrl", "requestedUrl"):
        if field in response and response[field] != page.requested_url:
            raise IngestionFailure("publication_source_mismatch")
    header = explicit_header(source, page.retained_text)
    native_date = _native_publication(source, page, selected)
    dates = [value for value in (native_date, header) if value is not None]
    if not dates:
        raise IngestionFailure("article_date_unknown")
    published = archives._published(dates)
    return {"schemaVersion": "zoop-publication-evidence-1", "source": source,
            "requestedUrl": page.requested_url, "publishedAt": published,
            "method": "native-publication" if native_date is not None else "explicit-markdown-header",
            "nativePublication": native_date, "headerPublication": header,
            "nativeObservationSha256": digest(page.native_observation.wire()),
            "nativeRawSha256": byte_hash(page.native_observation.body) if native_date is not None else None,
            "providerResponseSha256": byte_hash(page.provider_receipt.raw_response),
            "markdownSha256": byte_hash(page.retained_text.encode("utf-8")),
            "sourceDescriptor": selected.wire() if selected is not None else None}


def verify_publication(evidence, source, page):
    try:
        descriptor = evidence["sourceDescriptor"]
        selected = SourceDescriptor.model_validate(descriptor) if descriptor is not None else None
        if evidence != publication_evidence(source, page, descriptor=selected):
            raise ValueError("publication evidence mismatch")
    except (ValueError, KeyError, TypeError, UnicodeError, IngestionFailure) as exc:
        raise IngestionFailure("private_publication_evidence_invalid") from exc
    return evidence["publishedAt"]
