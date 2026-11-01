"""Retained-byte extraction and one explicitly budgeted public-page Fetch fallback.

Provider Markdown is a new representation, never original HTML or a collected-http receipt.
Unknown transport outcomes are terminal; the monetary reservation remains outstanding.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Protocol
from urllib.parse import urlsplit

import httpx
from lxml import etree, html

from .collection import _resolve, public_address, system_resolver
from . import live_funding
from .fetch_pacing import SharedFetchPacer
from .ingestion_contracts import MAX_RAW, MAX_TEXT, IngestionFailure, byte_hash, canonical, digest, now
from .ingestion_parsers import _restricted, prepare, profile
from .ingestion_url import canonical_url

FETCH_ENDPOINT = "https://api.deepseek.com/v1/tools/fetch"
FETCH_COST_NANO = 750_000
FETCH_STAGE = "fetch"
FETCH_RECIPIENT = "deepseek-fetch"
FETCH_ACCOUNT_ROLE = "personal-deepseek"
MARKDOWN_PROFILE = {"parser": "provider-markdown-exact-1", "mappingVersion": "unicode-copy-segments-1",
                    "coordinates": "retained-markdown-codepoints", "normalization": "identity"}
DEFUDDLE_PROFILE = {"parser": "defuddle-0.19.6", "dom": "linkedom-0.18.14", "representation": "extracted-html-1"}
_BLOCK_TITLE = re.compile(r"(?:^|\b)(?:404|410|page not found|not found|page (?:has been |was )?removed|"
                          r"content (?:is )?(?:unavailable|deleted)|access denied|forbidden|"
                          r"sign in to continue|log ?in (?:required|to continue)|authentication required|"
                          r"verify (?:you are|you're) human|captcha|just a moment|"
                          r"robots(?:\.txt)? (?:denied|disallow))\b|페이지를? 찾을 수 없|접근.*거부|로그인.*필요", re.I)
_CHALLENGE_TITLE = re.compile(r"captcha|just a moment|checking your browser|verify (?:that )?(?:you are|you're) human|"
                              r"security verification|browser verification|attention required", re.I)
_CHALLENGE_MARKER = re.compile(r"captcha|challenge-form|cf-chl|cf-browser-verification", re.I)
_EXPLICIT_ACCESS = re.compile(r"log ?in (?:required|to (?:continue|read|view))|sign in to|authentication required|"
                              r"private (?:page|content|resource)|subscription required|subscribe to (?:read|continue)|"
                              r"(?:automated access|crawling|scraping) (?:is )?(?:prohibited|forbidden)|"
                              r"robots(?:\.txt)?.{0,40}(?:disallow|denied)|publisher policy|로그인.*필요", re.I)
_STRUCTURED = frozenset({"application/xml", "text/xml", "application/rss+xml", "application/atom+xml",
                         "application/json", "application/ld+json"})
_TERMINAL_CODES = frozenset({"access_restricted", "robots_denied", "robots_unavailable", "archive_source_policy_denied",
                             "host_blocked", "host_not_allowed", "private_address", "http_401", "http_410"})


@dataclass(frozen=True)
class ObservedMetadata:
    title: str | None = None
    published_at: str | None = None
    publisher: str | None = None

    @property
    def publication_precision(self) -> str:
        value = self.published_at
        if value is None:
            return "unknown"
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                datetime.strptime(value, "%Y-%m-%d")
                return "day"
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?", value):
                return "unknown"
            datetime.fromisoformat(value)
        except ValueError:
            return "unknown"
        time = value[11:]
        return "subsecond" if "." in time else "second" if re.match(r"\d{2}:\d{2}:\d{2}", time) else "minute"

    def wire(self) -> dict:
        return {"title": self.title, "publishedAt": self.published_at,
                "publicationPrecision": self.publication_precision, "publisher": self.publisher}


@dataclass(frozen=True)
class NativePageObservation:
    requested_url: str
    observed_at: str
    http_status: int | None
    final_url: str | None = None
    media_type: str | None = None
    body: bytes | None = field(default=None, repr=False)
    failure_code: str | None = None
    access: Literal["public", "auth", "private", "robots", "deleted", "unknown"] = "unknown"
    redirects: tuple[str, ...] = ()
    www_authenticate: bool = False
    known_unsent: PriorPublicClient403 | None = None
    public_article_ref: str | None = None
    robots_allowed_url: str | None = None
    robots_observed_at: str | None = None

    def wire(self) -> dict:
        return {"requestedUrl": self.requested_url, "finalUrl": self.final_url, "observedAt": self.observed_at,
                "httpStatus": self.http_status, "mediaType": self.media_type, "failureCode": self.failure_code,
                "access": self.access, "redirects": list(self.redirects), "wwwAuthenticate": self.www_authenticate,
                "rawSha256": byte_hash(self.body) if self.body is not None else None,
                "rawBytes": len(self.body) if self.body is not None else None,
                "rawBodyBase64": base64.b64encode(self.body).decode("ascii") if self.body is not None else None,
                "knownUnsent": self.known_unsent.wire() if self.known_unsent else None,
                "publicArticleRef": self.public_article_ref, "robotsAllowedUrl": self.robots_allowed_url,
                "robotsObservedAt": self.robots_observed_at}


@dataclass(frozen=True)
class PriorPublicClient403:
    """A retained public-client refusal plus current-URL robots permission, not a new native response."""
    observation: NativePageObservation
    receipt_ref: str
    receipt_sha256: str
    robots_allowed_url: str
    robots_observed_at: str

    def wire(self) -> dict:
        return {"disposition": "prior_public_client_403", "observation": self.observation.wire(),
                "receiptRef": self.receipt_ref, "receiptSha256": self.receipt_sha256,
                "robotsAllowedUrl": self.robots_allowed_url, "robotsObservedAt": self.robots_observed_at}


@dataclass(frozen=True)
class ProviderReceipt:
    attempt_id: str
    observed_at: str
    http_status: int | None
    outcome: Literal["success", "http-failure", "empty", "invalid", "unknown"]
    raw_response: bytes | None = field(default=None, repr=False)
    request_id: str | None = None
    actual_nano: int | None = None
    received_bytes: int | None = None
    response_byte_limit: int = MAX_RAW

    def __post_init__(self):
        if self.received_bytes is None:
            object.__setattr__(self, "received_bytes", len(self.raw_response) if self.raw_response is not None else 0)

    def wire(self) -> dict:
        return {"provider": FETCH_RECIPIENT, "endpoint": FETCH_ENDPOINT, "attemptId": self.attempt_id,
                "observedAt": self.observed_at, "httpStatus": self.http_status, "outcome": self.outcome,
                "requestId": self.request_id, "rawResponseSha256": byte_hash(self.raw_response) if self.raw_response is not None else None,
                "rawResponseBase64": base64.b64encode(self.raw_response).decode("ascii") if self.raw_response is not None else None,
                "actualNano": self.actual_nano, "reservedNano": FETCH_COST_NANO,
                "receivedBytes": self.received_bytes, "responseByteLimit": self.response_byte_limit,
                "byteBasis": "http-response-body-before-content-decoding"}


@dataclass(frozen=True)
class FrozenExtractedPage:
    requested_url: str
    final_url: str | None
    backend: Literal["native", "defuddle", "deepseek-fetch"]
    observed_at: str
    format: Literal["html", "markdown"]
    retained_text: str = field(repr=False)
    native_observation: NativePageObservation
    metadata: ObservedMetadata
    normalization_profile_json: str = field(repr=False)
    prepared_json: str = field(repr=False)
    provider_receipt: ProviderReceipt | None = None
    fallback_reasons: tuple[str, ...] = ()

    @property
    def prepared(self) -> dict:
        return json.loads(self.prepared_json)

    @property
    def normalization_profile(self) -> dict:
        return json.loads(self.normalization_profile_json)

    def wire(self) -> dict:
        return {"schemaVersion": "zoop-extracted-page-1", "requestedUrl": self.requested_url,
                "finalUrl": self.final_url, "backend": self.backend, "observedAt": self.observed_at,
                "format": self.format, "retainedText": self.retained_text,
                "rawSha256": byte_hash(self.retained_text.encode("utf-8")),
                "contentSha256": byte_hash(self.prepared["text"].encode("utf-8")),
                "nativeObservation": self.native_observation.wire(), "metadata": self.metadata.wire(),
                "normalizationProfile": self.normalization_profile, "prepared": self.prepared,
                "providerReceipt": self.provider_receipt.wire() if self.provider_receipt else None,
                "fallbackReasons": list(self.fallback_reasons)}


class ExtractionFallbackFailure(IngestionFailure):
    def __init__(self, code: str, *, native: NativePageObservation | None = None,
                 receipt: ProviderReceipt | None = None, reasons: tuple[str, ...] = ()):
        super().__init__(code)
        self.native_observation, self.provider_receipt, self.fallback_reasons = native, receipt, reasons


class FetchBudget(Protocol):
    def reserve(self, attempt_id: str, stage: str, recipient: str, request_digest: str,
                worst_case_nano: int, *, account_role: str, set_id: str): ...
    def check_send(self, attempt_id: str): ...
    def settle(self, attempt_id: str, actual_nano: int | None): ...
    def release(self, attempt_id: str): ...


def guard_public_url(value: str, allowed_hosts: tuple[str, ...], *, resolver=system_resolver,
                     resolve: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise ExtractionFallbackFailure("fallback_url_invalid")
    url, host = canonical_url(value)
    if host not in allowed_hosts:
        raise ExtractionFallbackFailure("fallback_host_not_allowed")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ExtractionFallbackFailure("fallback_private_address")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not public_address(literal):
        raise ExtractionFallbackFailure("fallback_private_address")
    if resolve:
        addresses = _resolve(resolver, host, 443 if urlsplit(url).scheme == "https" else 80, 5)
        try:
            if not addresses or any(not public_address(ipaddress.ip_address(address)) for address in addresses):
                raise ExtractionFallbackFailure("fallback_private_address")
        except ValueError as exc:
            raise ExtractionFallbackFailure("fallback_private_address") from exc
    return url


def _text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtractionFallbackFailure("fallback_empty_content")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ExtractionFallbackFailure("fallback_invalid_content") from exc
    if len(raw) > MAX_RAW or len(value) > MAX_TEXT:
        raise ExtractionFallbackFailure("fallback_content_limit")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ExtractionFallbackFailure("fallback_invalid_content")
    return value


def _reject_page(text: str, *, is_html: bool, title: str | None = None) -> None:
    if title and _BLOCK_TITLE.search(title):
        raise ExtractionFallbackFailure("fallback_error_page")
    if is_html:
        try:
            tree = html.document_fromstring(text, parser=html.HTMLParser(no_network=True))
        except (ValueError, etree.LxmlError) as exc:
            raise ExtractionFallbackFailure("fallback_invalid_html") from exc
        if _restricted(tree) or tree.xpath('//input[translate(@type,"PASSWORD","password")="password"]'):
            raise ExtractionFallbackFailure("fallback_access_restricted")
        labels = tree.xpath("//title/text() | //h1//text()")
        if any(_BLOCK_TITLE.search(label.strip()) for label in labels):
            raise ExtractionFallbackFailure("fallback_error_page")
        leading = " ".join(tree.xpath("//body//text()"))[:400].strip()
    else:
        leading = next((line.lstrip("# >*_").strip() for line in text.splitlines() if line.strip()), "")
        # Markdown may contain raw HTML; deny access walls without rewriting any content.
        if re.search(r"<\s*(?:html|form|input)\b", text, re.I):
            _reject_page(text, is_html=True)
    if _BLOCK_TITLE.search(leading) and len(leading) < 400:
        raise ExtractionFallbackFailure("fallback_error_page")


def _public_article_evidence(native: NativePageObservation, allowed_hosts: tuple[str, ...]) -> bool:
    try:
        ref = native.public_article_ref
        if (native.access != "public" or native.www_authenticate or not isinstance(ref, str) or
                not ref.strip() or len(ref) > 500 or any(ord(c) < 32 for c in ref)):
            return False
        if guard_public_url(native.robots_allowed_url, allowed_hosts) != guard_public_url(native.requested_url, allowed_hosts):
            return False
        observed, robots = datetime.fromisoformat(native.observed_at), datetime.fromisoformat(native.robots_observed_at)
        return observed.tzinfo is not None and robots.tzinfo is not None and robots <= observed
    except (ValueError, TypeError, IngestionFailure):
        return False


def _public_origin_challenge(native: NativePageObservation, allowed_hosts: tuple[str, ...]) -> bool:
    """Only classify the origin interstitial; never parse or solve it as article content."""
    if (native.http_status not in {200, 403, 404} or native.body is None or len(native.body) > MAX_RAW or
            not _public_article_evidence(native, allowed_hosts)):
        return False
    try:
        tree = html.document_fromstring(native.body.decode("utf-8", errors="strict"), parser=html.HTMLParser(no_network=True))
        headings = tree.xpath("//title | //h1")
        title_challenge = any(_CHALLENGE_TITLE.search(node.text_content()) for node in headings)
        marked = tree.xpath("//*[@id or @class]")
        marker_challenge = any(_CHALLENGE_MARKER.search(f"{node.get('id', '')} {node.get('class', '')}") for node in marked)
        if not (title_challenge or marker_challenge):
            return False
        visible = " ".join(tree.xpath("//text()[not(ancestor::script or ancestor::style)]"))
        if (_EXPLICIT_ACCESS.search(visible) or
                tree.xpath('//input[translate(@type,"PASSWORD","password")="password"]')):
            return False
        # A classifier-only DOM copy removes challenge labels; paywall JSON and explicit access markers still refuse.
        for node in headings:
            if _CHALLENGE_TITLE.search(node.text_content()) or marker_challenge and re.search(r"access denied|forbidden", node.text_content(), re.I):
                node.text = ""
        for node in marked:
            for attribute in ("id", "class"):
                if node.get(attribute):
                    node.set(attribute, _CHALLENGE_MARKER.sub("", node.get(attribute)))
        return not _restricted(tree)
    except (UnicodeError, ValueError, etree.LxmlError):
        return False


def prepare_markdown(text: str) -> dict:
    """Identity mapping into the *retained Markdown artifact*, not original webpage coordinates."""
    _text(text)
    _reject_page(text, is_html=False)
    return {"text": text, "sources": [{"representation": "markdown", "text": text}],
            "segments": [{"cleanStart": 0, "cleanEnd": len(text), "sourceIndex": 0,
                          "sourceStart": 0, "sourceEnd": len(text)}],
            "runs": [{"start": 0, "end": len(text)}],
            "limitations": ["identity Unicode codepoint coordinates in retained provider Markdown, not original HTML",
                            "provider redirect chain, final URL and original source bytes are unobserved"]}


class DefuddleExtractor:
    """A credential-free, non-networking ESM subprocess operating only on supplied HTML."""
    def __init__(self, *, node: str = "node", timeout: float = 30):
        self.node, self.timeout = node, timeout

    def __call__(self, raw: bytes, url: str) -> str:
        if len(raw) > MAX_RAW:
            raise ExtractionFallbackFailure("fallback_content_limit")
        try:
            text = raw.decode("utf-8", errors="strict")
            child = subprocess.run([self.node, "--max-old-space-size=256", str(Path(__file__).with_name("_defuddle") / "extract.mjs")],
                                   input=canonical({"html": text, "url": url}).encode("utf-8"),
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env={"PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8"},
                                   timeout=self.timeout, check=False)
            if child.returncode or len(child.stdout) > MAX_RAW:
                raise ExtractionFallbackFailure("defuddle_extraction_failed")
            output = json.loads(child.stdout)
            if output.get("profile") != DEFUDDLE_PROFILE or not isinstance(output.get("content"), str):
                raise ExtractionFallbackFailure("defuddle_output_invalid")
            return _text(output["content"])
        except (OSError, UnicodeError, ValueError, subprocess.TimeoutExpired) as exc:
            raise ExtractionFallbackFailure("defuddle_extraction_failed") from exc


class DeepSeekFetchClient:
    """One POST, no redirects/retries; callers supply approved key and an admitted budget set."""
    def __init__(self, *, api_key: str, budget: FetchBudget, set_id: str, allowed_hosts: tuple[str, ...],
                 pacer: SharedFetchPacer, min_interval_seconds: float = 2, max_response_bytes: int = MAX_RAW,
                 timeout: float = 30, transport: httpx.BaseTransport | None = None,
                 resolver=system_resolver, clock: Callable[[], str] = now, send_before: str | None = None):
        if (not api_key or not api_key.strip() or not set_id or budget is None or pacer is None or
                type(max_response_bytes) is not int or not 1 <= max_response_bytes <= MAX_RAW):
            raise ExtractionFallbackFailure("fallback_configuration_invalid")
        self._api_key, self.budget, self.set_id = api_key, budget, set_id
        self.allowed_hosts, self.timeout, self.transport = allowed_hosts, timeout, transport
        self.resolver, self.clock = resolver, clock
        self.pacer, self.min_interval_seconds = pacer, min_interval_seconds
        self.max_response_bytes = max_response_bytes
        self.send_before = send_before if send_before is not None else os.environ.get(live_funding.SEND_BEFORE_ENV)

    def fetch(self, url: str, *, min_interval_seconds: float | None = None, not_before_monotonic: float = 0,
              deadline_monotonic: float | None = None) -> tuple[str, str | None, ProviderReceipt]:
        live_funding.require_send_window(self.timeout, self.send_before)
        url = guard_public_url(url, self.allowed_hosts, resolver=self.resolver, resolve=True)
        deadline = time.monotonic() + self.timeout
        if deadline_monotonic is not None:
            deadline = min(deadline, deadline_monotonic)
        self.pacer.acquire(url, min_interval_seconds=max(self.min_interval_seconds, min_interval_seconds)
                           if min_interval_seconds is not None else self.min_interval_seconds,
                           not_before_monotonic=not_before_monotonic, deadline_monotonic=deadline)
        live_funding.require_send_window(self.timeout, self.send_before)
        # A pacing wait is not a paid attempt. A process death after admission only wastes a slot.
        payload = {"url": url}
        attempt_id = "fetch-" + uuid.uuid4().hex
        self.budget.reserve(attempt_id, FETCH_STAGE, FETCH_RECIPIENT, digest({"endpoint": FETCH_ENDPOINT, "body": payload}),
                            FETCH_COST_NANO, account_role=FETCH_ACCOUNT_ROLE, set_id=self.set_id)
        sent = False
        status = None
        response, request_id, received_bytes = None, None, 0
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                self.budget.check_send(attempt_id)
                live_funding.require_send_window(self.timeout, self.send_before)
                sent = True
                with client.stream("POST", FETCH_ENDPOINT,
                                   headers={"Authorization": "Bearer " + self._api_key, "Content-Type": "application/json",
                                            "Accept-Encoding": "identity"},
                                   json=payload) as response:
                    status = response.status_code
                    request_id = response.headers.get("x-request-id")
                    encoding = response.headers.get("content-encoding", "identity").strip().lower()
                    chunks = bytearray()
                    for chunk in response.iter_raw(chunk_size=min(self.max_response_bytes, 65_536)):
                        if time.monotonic() >= deadline:
                            raise httpx.ReadTimeout("fetch deadline")
                        # The transport may have read ahead of the yielded chunk. Preserve that observed count too.
                        received_bytes = max(response.num_bytes_downloaded, len(chunks) + len(chunk))
                        if received_bytes > self.max_response_bytes:
                            raise ExtractionFallbackFailure("provider_response_limit")
                        chunks.extend(chunk)
                    raw = bytes(chunks)
        except BaseException as exc:
            if not sent:
                self.budget.release(attempt_id)
                raise
            # Even a body-read failure after HTTP200 can have been billed. Keep the reservation.
            if response is not None:
                received_bytes = max(received_bytes, response.num_bytes_downloaded)
            receipt = ProviderReceipt(attempt_id, self.clock(), status, "unknown", request_id=request_id,
                                      received_bytes=received_bytes, response_byte_limit=self.max_response_bytes)
            raise ExtractionFallbackFailure("provider_unknown_no_retry", receipt=receipt) from exc
        observed = self.clock()
        if status != 200:
            receipt = ProviderReceipt(attempt_id, observed, status, "http-failure", raw, request_id, 0,
                                      received_bytes, self.max_response_bytes)
            self.budget.settle(attempt_id, 0)
            raise ExtractionFallbackFailure(f"provider_http_{status}", receipt=receipt)
        try:
            if encoding not in {"", "identity"}:
                raise ValueError("unexpected response content encoding")
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate response field")
                    result[key] = value
                return result
            response = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique)
            if not isinstance(response, dict) or not isinstance(response.get("title"), str) or not isinstance(response.get("content"), str):
                raise ValueError("invalid Fetch schema")
            content = response["content"]
        except (ValueError, UnicodeError, RecursionError) as exc:
            # Malformed200 does not prove a free request: reserve remains outstanding.
            receipt = ProviderReceipt(attempt_id, observed, status, "invalid", raw, request_id,
                                      received_bytes=received_bytes, response_byte_limit=self.max_response_bytes)
            raise ExtractionFallbackFailure("provider_invalid_response", receipt=receipt) from exc
        cost = FETCH_COST_NANO if content.strip() else 0
        receipt = ProviderReceipt(attempt_id, observed, status, "success" if cost else "empty", raw, request_id, cost,
                                  received_bytes, self.max_response_bytes)
        self.budget.settle(attempt_id, cost)
        try:
            _text(content)
            _reject_page(content, is_html=False, title=response["title"])
        except ExtractionFallbackFailure as exc:
            raise ExtractionFallbackFailure(exc.code, receipt=receipt) from exc
        return content, response["title"] or None, receipt


def _known_unsent_allowed(native: NativePageObservation, allowed_hosts: tuple[str, ...]) -> bool:
    cause = native.known_unsent
    if cause is None:
        return False
    try:
        prior = cause.observation
        if (native.http_status is not None or native.body is not None or native.final_url is not None or native.redirects or
                native.failure_code != "host_blocked" or native.access != "public" or native.www_authenticate or
                prior.known_unsent is not None or prior.http_status != 403 or prior.failure_code != "http_403" or
                prior.access != "public" or prior.www_authenticate):
            raise ValueError("not an eligible known-unsent request")
        if (not isinstance(cause.receipt_ref, str) or not cause.receipt_ref.strip() or len(cause.receipt_ref) > 500 or
                any(ord(c) < 32 for c in cause.receipt_ref) or cause.receipt_sha256 != digest(prior.wire())):
            raise ValueError("causal receipt is not pinned")
        current_url = guard_public_url(native.requested_url, allowed_hosts)
        prior_url = guard_public_url(prior.requested_url, allowed_hosts)
        if current_url == prior_url or guard_public_url(cause.robots_allowed_url, allowed_hosts) != current_url:
            raise ValueError("must be a new robots-permitted URL")
        origin = urlsplit(current_url)[:2]
        for url in (prior_url, *prior.redirects, *((prior.final_url,) if prior.final_url else ())):
            if urlsplit(guard_public_url(url, allowed_hosts))[:2] != origin:
                raise ValueError("causal refusal must have the exact same origin")
        current_time, prior_time, robots_time = (datetime.fromisoformat(value) for value in
                                                (native.observed_at, prior.observed_at, cause.robots_observed_at))
        if any(value.tzinfo is None for value in (current_time, prior_time, robots_time)) or max(prior_time, robots_time) > current_time:
            raise ValueError("invalid causal observation times")
        if prior.body is not None:
            if len(prior.body) > MAX_RAW:
                raise ValueError("causal body limit")
            text = prior.body.decode("utf-8", errors="strict")
            if text.strip():
                if _public_origin_challenge(prior, allowed_hosts):
                    if not _public_article_evidence(native, allowed_hosts):
                        raise ValueError("new URL lacks independent public article evidence")
                else:
                    _reject_page(text, is_html=(prior.media_type or "").split(";", 1)[0] == "text/html")
        return True
    except (ValueError, TypeError, AttributeError, IngestionFailure) as exc:
        raise ExtractionFallbackFailure("fallback_known_unsent_invalid") from exc


def _observation_from_wire(value: dict, *, nested: bool = False) -> NativePageObservation:
    cause = value["knownUnsent"]
    if nested and cause is not None:
        raise ValueError("recursive causal observation")
    known_unsent = None
    if cause is not None:
        if cause["disposition"] != "prior_public_client_403":
            raise ValueError("unknown unsent disposition")
        known_unsent = PriorPublicClient403(_observation_from_wire(cause["observation"], nested=True),
                                           cause["receiptRef"], cause["receiptSha256"],
                                           cause["robotsAllowedUrl"], cause["robotsObservedAt"])
    raw = value["rawBodyBase64"]
    return NativePageObservation(value["requestedUrl"], value["observedAt"], value["httpStatus"],
                                 value["finalUrl"], value["mediaType"],
                                 base64.b64decode(raw, validate=True) if raw is not None else None,
                                 value["failureCode"], value["access"], tuple(value["redirects"]),
                                 value["wwwAuthenticate"], known_unsent, value["publicArticleRef"],
                                 value["robotsAllowedUrl"], value["robotsObservedAt"])


def extract_page(native: NativePageObservation, *, allowed_hosts: tuple[str, ...], article_xpath: str | None = None,
                 metadata: ObservedMetadata = ObservedMetadata(), defuddle: Callable[[bytes, str], str] | None = None,
                 provider: DeepSeekFetchClient | None = None) -> FrozenExtractedPage:
    """Native parser → same-byte local extraction → eligible public-page provider; never re-GET."""
    reasons: list[str] = []
    try:
        guard_public_url(native.requested_url, allowed_hosts)
        for url in (*native.redirects, *((native.final_url,) if native.final_url else ())):
            guard_public_url(url, allowed_hosts)
            if urlsplit(native.requested_url).scheme == "https" and urlsplit(url).scheme != "https":
                raise ExtractionFallbackFailure("fallback_redirect_downgrade")
        known_unsent = _known_unsent_allowed(native, allowed_hosts)
        origin_challenge = _public_origin_challenge(native, allowed_hosts)
        if (native.access in {"auth", "private", "robots", "deleted"} or native.www_authenticate or
                native.failure_code in _TERMINAL_CODES and not known_unsent and
                not (native.failure_code == "access_restricted" and origin_challenge)):
            raise ExtractionFallbackFailure("fallback_access_restricted")
        if native.http_status is None and not known_unsent:
            raise ExtractionFallbackFailure("native_unknown_no_retry")
        if native.http_status in {401, 410, 429}:
            raise ExtractionFallbackFailure(f"native_http_{native.http_status}")
        media = (native.media_type or "").split(";", 1)[0].strip().lower()
        if media in _STRUCTURED or native.body and re.match(br"\s*(?:<\?xml\b|<(?:rss|feed|sitemapindex|urlset)\b)", native.body, re.I):
            raise ExtractionFallbackFailure("fallback_structured_document_refused")
        original = None
        if native.body is not None:
            if len(native.body) > MAX_RAW:
                raise ExtractionFallbackFailure("fallback_content_limit")
            try:
                original = native.body.decode("utf-8", errors="strict")
            except UnicodeError:
                reasons.append("native_invalid_utf8")
            if origin_challenge:
                reasons.append("public_origin_challenge")
                original = None
            elif original and (media == "text/html" or re.search(r"<\s*(?:html|body|h1|title|form)\b", original, re.I)):
                _reject_page(original, is_html=True, title=metadata.title)
        if native.http_status == 200 and media == "text/html" and original is not None:
            try:
                prepared = prepare(native.body, "text/html", article_xpath)
                return FrozenExtractedPage(native.requested_url, native.final_url, "native", native.observed_at, "html",
                                           original, native, metadata, canonical(profile(article_xpath)), canonical(prepared))
            except IngestionFailure as exc:
                if exc.code == "access_restricted":
                    raise ExtractionFallbackFailure("fallback_access_restricted") from exc
                reasons.append(exc.code)
            try:
                extracted = (defuddle or DefuddleExtractor())(native.body, native.final_url or native.requested_url)
                _text(extracted)
                _reject_page(extracted, is_html=True)
                prepared = prepare(extracted.encode("utf-8"), "text/html", "//body")
                return FrozenExtractedPage(native.requested_url, native.final_url, "defuddle", native.observed_at, "html",
                                           extracted, native, metadata,
                                           canonical({**profile("//body"), **DEFUDDLE_PROFILE,
                                                      "coordinates": "retained-extracted-html-dom"}),
                                           canonical(prepared), fallback_reasons=tuple(reasons))
            except IngestionFailure as exc:
                if exc.code in {"fallback_access_restricted", "fallback_error_page", "access_restricted"}:
                    raise
                reasons.append(exc.code)
        elif native.http_status not in {200, 403, 404} and not known_unsent:
            raise ExtractionFallbackFailure(f"native_http_{native.http_status}")
        else:
            reasons.append("prior_public_client_403" if known_unsent else native.failure_code or
                           (f"native_http_{native.http_status}" if native.http_status != 200 else "native_unsupported_page"))
        if native.access != "public":
            raise ExtractionFallbackFailure("fallback_public_access_unconfirmed")
        if provider is None:
            raise ExtractionFallbackFailure("fallback_provider_unconfigured")
        content, title, receipt = provider.fetch(native.requested_url)
        # Provider metadata is not merged with old HTML metadata: different retrieval/representation.
        return FrozenExtractedPage(native.requested_url, None, "deepseek-fetch", receipt.observed_at, "markdown",
                                   content, native, ObservedMetadata(title=title), canonical(MARKDOWN_PROFILE),
                                   canonical(prepare_markdown(content)), receipt, tuple(reasons))
    except IngestionFailure as exc:
        raise ExtractionFallbackFailure(exc.code, native=native,
                                        receipt=getattr(exc, "provider_receipt", None), reasons=tuple(reasons)) from exc


def verify_extracted_page(value: dict, *, allowed_hosts: tuple[str, ...]) -> FrozenExtractedPage:
    """Validate a pinned envelope offline; never re-fetch or re-run the Node extractor."""
    try:
        native = _observation_from_wire(value["nativeObservation"])
        body = native.body
        if native.access not in {"public", "auth", "private", "robots", "deleted", "unknown"}:
            raise ValueError("invalid access disposition")
        if native.http_status is not None and type(native.http_status) is not int:
            raise ValueError("invalid status")
        if type(native.www_authenticate) is not bool:
            raise ValueError("invalid authentication observation")
        for observed in (native.observed_at, value["observedAt"]):
            if datetime.fromisoformat(observed).tzinfo is None:
                raise ValueError("observation must include timezone")
        guard_public_url(native.requested_url, allowed_hosts)
        for url in (*native.redirects, *((native.final_url,) if native.final_url else ())):
            guard_public_url(url, allowed_hosts)
            if urlsplit(native.requested_url).scheme == "https" and urlsplit(url).scheme != "https":
                raise ValueError("redirect downgrade")
        known_unsent = _known_unsent_allowed(native, allowed_hosts)
        origin_challenge = _public_origin_challenge(native, allowed_hosts)
        if (native.http_status not in {200, 403, 404} and not known_unsent or native.www_authenticate or
                native.access in {"auth", "private", "robots", "deleted"} or
                native.failure_code in _TERMINAL_CODES and not known_unsent and
                not (native.failure_code == "access_restricted" and origin_challenge)):
            raise ValueError("ineligible native observation")
        media = (native.media_type or "").split(";", 1)[0].strip().lower()
        if media in _STRUCTURED or body and re.match(br"\s*(?:<\?xml\b|<(?:rss|feed|sitemapindex|urlset)\b)", body, re.I):
            raise ValueError("structured document")
        if body is not None:
            if len(body) > MAX_RAW:
                raise ValueError("native body limit")
            try:
                original = body.decode("utf-8", errors="strict")
            except UnicodeError:
                original = None
            if original and (media == "text/html" or re.search(r"<\s*(?:html|body|h1|title|form)\b", original, re.I)):
                if not (origin_challenge and value["backend"] == "deepseek-fetch"):
                    _reject_page(original, is_html=True)
        else:
            original = None
        meta = value["metadata"]
        metadata = ObservedMetadata(meta["title"], meta["publishedAt"], meta["publisher"])
        if any(item is not None and not isinstance(item, str) for item in (metadata.title, metadata.published_at, metadata.publisher)):
            raise ValueError("invalid metadata")
        content = _text(value["retainedText"])
        backend = value["backend"]
        receipt = None
        if backend == "deepseek-fetch":
            if native.access != "public" or value["finalUrl"] is not None or value["format"] != "markdown":
                raise ValueError("invalid provider provenance")
            r = value["providerReceipt"]
            response_raw = base64.b64decode(r["rawResponseBase64"], validate=True)
            if len(response_raw) > MAX_RAW:
                raise ValueError("provider body limit")
            response = json.loads(response_raw.decode("utf-8"))
            receipt = ProviderReceipt(r["attemptId"], r["observedAt"], r["httpStatus"], r["outcome"],
                                      response_raw, r["requestId"], r["actualNano"], r["receivedBytes"], r["responseByteLimit"])
            if (type(receipt.received_bytes) is not int or type(receipt.response_byte_limit) is not int or
                    not 1 <= receipt.response_byte_limit <= MAX_RAW or
                    receipt.received_bytes != len(response_raw) or len(response_raw) > receipt.response_byte_limit):
                raise ValueError("provider byte accounting mismatch")
            if (receipt.http_status != 200 or receipt.outcome != "success" or receipt.actual_nano != FETCH_COST_NANO or
                    receipt.observed_at != value["observedAt"] or response["content"] != content or
                    (response["title"] or None) != metadata.title or metadata.published_at is not None or metadata.publisher is not None):
                raise ValueError("provider receipt mismatch")
            _reject_page(content, is_html=False, title=metadata.title)
            expected_profile, prepared = MARKDOWN_PROFILE, prepare_markdown(content)
        elif backend in {"native", "defuddle"}:
            if (native.http_status != 200 or media != "text/html" or original is None or value["format"] != "html" or
                    value["observedAt"] != native.observed_at or value["finalUrl"] != native.final_url or value["providerReceipt"] is not None):
                raise ValueError("invalid local provenance")
            _reject_page(content, is_html=True, title=metadata.title)
            if backend == "native":
                if content != original or value["fallbackReasons"]:
                    raise ValueError("native body mismatch")
                xpath = value["normalizationProfile"]["articleXPath"]
                expected_profile = profile(xpath)
            else:
                xpath = "//body"
                expected_profile = {**profile(xpath), **DEFUDDLE_PROFILE, "coordinates": "retained-extracted-html-dom"}
            prepared = prepare(content.encode("utf-8"), "text/html", xpath)
        else:
            raise ValueError("invalid backend")
        page = FrozenExtractedPage(native.requested_url, value["finalUrl"], backend, value["observedAt"],
                                   value["format"], content, native, metadata, canonical(expected_profile),
                                   canonical(prepared), receipt, tuple(value["fallbackReasons"]))
        # Exact equality validates all hashes, schema/metadata precision, keys and coordinate arrays.
        if canonical(page.wire()) != canonical(value):
            raise ValueError("envelope mismatch")
        return page
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, IngestionFailure) as exc:
        raise ExtractionFallbackFailure("extracted_page_invalid") from exc
