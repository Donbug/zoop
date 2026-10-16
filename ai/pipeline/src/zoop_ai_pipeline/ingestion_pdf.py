"""Bounded PDF text extraction. Runs only inside the disposable child process started by ingestion_parsers.prepare().

The parent enforces a wall-clock deadline and treats any non-zero exit or oversized output as a closed failure. Inside the
child every decoded stream is charged against fixed budgets before pypdf concatenates content or parses text operators, and
filters that would call an external decoder are refused. Failure codes are stable strings; pypdf exception text (which can
carry attacker-controlled objects) never leaves this module.
"""
from __future__ import annotations

import io
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

import pypdf.filters
from pypdf import PdfReader, apply_configuration
from pypdf.errors import DependencyError, LimitReachedError, PyPdfError
from pypdf.generic import ArrayObject, DictionaryObject, EncodedStreamObject, IndirectObject, StreamObject

from .ingestion_contracts import MAX_RAW, MAX_TEXT, IngestionFailure, canonical, digest

MAX_PDF_BYTES = 10_000_000
MAX_PAGE_COUNT = 150
MAX_STREAM_BYTES = 20_000_000
MAX_AGGREGATE_BYTES = 40_000_000
MAX_FILTER_CHAIN = 8
EXTERNAL_DECODERS = frozenset({"/JBIG2Decode"})
_HOOK = Lock()


def _resolved(value):
    while isinstance(value, IndirectObject):
        value = value.get_object()
    return value


class _Budget:
    def __init__(self, decoder):
        self.decoder, self.total, self.charged = decoder, 0, set()

    def check_filters(self, stream: StreamObject) -> None:
        filters = _resolved(stream.get("/Filter", ()))
        names = tuple(filters) if isinstance(filters, ArrayObject) else (filters,) if filters else ()
        if len(names) > MAX_FILTER_CHAIN:
            raise IngestionFailure("pdf_filter_chain_limit")
        if any(str(name) in EXTERNAL_DECODERS for name in names):
            raise IngestionFailure("pdf_external_decoder_filter")

    def charge(self, stream: StreamObject, length: int) -> None:
        if id(stream) in self.charged:
            return
        if length > MAX_STREAM_BYTES:
            raise IngestionFailure("pdf_decoded_stream_limit")
        if self.total + length > MAX_AGGREGATE_BYTES:
            raise IngestionFailure("pdf_aggregate_decoded_stream_limit")
        self.total += length
        self.charged.add(id(stream))

    def decode(self, stream: StreamObject) -> bytes:
        self.check_filters(stream)
        try:
            data = self.decoder(stream)
        except LimitReachedError as exc:
            raise IngestionFailure("pdf_decoded_stream_limit") from exc
        self.charge(stream, len(data))
        return data

    def materialize(self, stream: StreamObject) -> None:
        self.check_filters(stream)
        if id(stream) in self.charged:
            return
        data = stream.get_data()
        if not isinstance(stream, EncodedStreamObject):
            # Encoded streams were charged by the decode hook; plain ones are charged here.
            self.charge(stream, len(data))


@contextmanager
def _bounded() -> Iterator[_Budget]:
    # pypdf decodes object/xref streams while building the reader, so the hook must exist before PdfReader does.
    with _HOOK:
        original = pypdf.filters.decode_stream_data
        budget = _Budget(original)
        pypdf.filters.decode_stream_data = budget.decode
        try:
            with apply_configuration(maximum_declared_stream_length=MAX_PDF_BYTES, array_based_stream_maximum_output_length=MAX_STREAM_BYTES,
                                     jbig2_maximum_output_length=MAX_STREAM_BYTES, lzw_maximum_output_length=MAX_STREAM_BYTES,
                                     run_length_maximum_output_length=MAX_STREAM_BYTES, zlib_maximum_output_length=MAX_STREAM_BYTES,
                                     image_maximum_buffer_size=MAX_STREAM_BYTES, jbig2dec_binary=None, disable_legacy_handling=True):
                yield budget
        finally:
            pypdf.filters.decode_stream_data = original


def _font(font, budget: _Budget, seen: set[int]) -> None:
    font = _resolved(font)
    if not isinstance(font, DictionaryObject) or id(font) in seen:
        return
    seen.add(id(font))
    unicode_map = _resolved(font.get("/ToUnicode"))
    if isinstance(unicode_map, StreamObject):
        budget.materialize(unicode_map)
    descriptor = _resolved(font.get("/FontDescriptor"))
    if isinstance(descriptor, DictionaryObject):
        for key in ("/FontFile", "/FontFile2", "/FontFile3"):
            program = _resolved(descriptor.get(key))
            if isinstance(program, StreamObject):
                budget.materialize(program)
    descendants = _resolved(font.get("/DescendantFonts"))
    if isinstance(descendants, ArrayObject):
        for child in descendants:
            _font(child, budget, seen)


def _resources(resources, budget: _Budget, seen: set[int]) -> None:
    resources = _resolved(resources)
    if not isinstance(resources, DictionaryObject) or id(resources) in seen:
        return
    seen.add(id(resources))
    fonts = _resolved(resources.get("/Font"))
    if isinstance(fonts, DictionaryObject):
        for font in fonts.values():
            _font(font, budget, seen)
    objects = _resolved(resources.get("/XObject"))
    if not isinstance(objects, DictionaryObject):
        return
    for candidate in objects.values():
        xobject = _resolved(candidate)
        if not isinstance(xobject, StreamObject):
            continue
        # Even an ignored image may not opt this worker into an external decoder executable.
        budget.check_filters(xobject)
        if str(xobject.get("/Subtype", "")) == "/Image":
            continue
        budget.materialize(xobject)
        _resources(xobject.get("/Resources"), budget, seen)


def _page(page, budget: _Budget) -> None:
    contents = _resolved(page.get("/Contents"))
    for candidate in contents if isinstance(contents, ArrayObject) else [contents]:
        stream = _resolved(candidate)
        if isinstance(stream, StreamObject):
            budget.materialize(stream)
    _resources(page.get_inherited("/Resources", default=DictionaryObject()), budget, set())


def extract(raw: bytes) -> dict:
    """{'sources': [{'pageNumber','pageTextHash','text'}...]} or {'error': code}."""
    try:
        if len(raw) > min(MAX_RAW, MAX_PDF_BYTES):
            raise IngestionFailure("pdf_byte_limit")
        sources, total = [], 0
        with _bounded() as budget:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted:
                raise IngestionFailure("encrypted_pdf")
            if len(reader.pages) > MAX_PAGE_COUNT:
                raise IngestionFailure("pdf_page_limit")
            for number, page in enumerate(reader.pages, 1):
                _page(page, budget)
                text = page.extract_text() or ""
                total += len(text)
                if total > MAX_TEXT:
                    raise IngestionFailure("text_output_limit")
                sources.append({"pageNumber": number, "pageTextHash": digest(text), "text": text})
        return {"sources": sources}
    except IngestionFailure as exc:
        return {"error": exc.code}
    except LimitReachedError:
        return {"error": "pdf_decoded_stream_limit"}
    except (PyPdfError, DependencyError, ValueError, TypeError, OSError, RuntimeError, LookupError, ArithmeticError, MemoryError):
        return {"error": "pdf_extraction_failed"}


if __name__ == "__main__":
    print(canonical(extract(sys.stdin.buffer.read(MAX_RAW + 1))))
