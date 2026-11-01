"""Authored bodies + HTTP transport doubles only; no keys, public GETs or paid calls."""
from dataclasses import FrozenInstanceError, replace
import gzip
import base64
import json

import httpx
import pytest

from zoop_ai_pipeline.extraction_fallback import (
    FETCH_ACCOUNT_ROLE, FETCH_COST_NANO, FETCH_ENDPOINT, DeepSeekFetchClient, ExtractionFallbackFailure,
    NativePageObservation, ObservedMetadata, PriorPublicClient403, extract_page, guard_public_url, prepare_markdown, verify_extracted_page,
)
from zoop_ai_pipeline.ingestion_contracts import byte_hash, digest

URL = "https://news.example/article"
HOSTS = ("news.example",)
WHEN = "2026-10-28T07:12:01.123456+00:00"
BODY = "<html><title>Company results</title><article><p>한글 😀 e\u0301 실적 발표.</p></article></html>".encode()
MARKDOWN = "# 결과 😀\n\n[원문](https://news.example/source?q=a%26b) e\u0301\n\n```python\nprint('\\{값\\}')\n```\n"


class Budget:
    def __init__(self, *, refuse=False):
        self.events = []
        self.refuse = refuse

    def reserve(self, attempt_id, stage, recipient, request_digest, worst_case_nano, *, account_role, set_id):
        self.events.append(("reserve", attempt_id, stage, recipient, request_digest, worst_case_nano, account_role, set_id))

    def check_send(self, attempt_id):
        self.events.append(("check_send", attempt_id))
        if self.refuse:
            raise RuntimeError("admission closed")

    def settle(self, attempt_id, actual_nano):
        self.events.append(("settle", attempt_id, actual_nano))

    def release(self, attempt_id):
        self.events.append(("release", attempt_id))


class Pacer:
    """Synthetic dispatch gate; real process-shared timing is exercised in test_fetch_pacing."""
    def __init__(self):
        self.calls = []

    def acquire(self, url, **timing):
        self.calls.append((url, timing))
        return timing["not_before_monotonic"]


def native(**kwargs):
    return replace(NativePageObservation(URL, WHEN, 200, final_url=URL, media_type="text/html", body=BODY,
                                         access="public"), **kwargs)


def forbidden(*args, **kwargs):
    raise AssertionError("fallback must not be called")


def provider(handler=None, *, budget=None, resolver=None, pacer=None, max_response_bytes=10_000_000):
    calls = []
    budget = budget or Budget()

    def send(request):
        calls.append(request)
        assert request.url == FETCH_ENDPOINT and request.method == "POST"
        assert json.loads(request.content) == {"url": URL}
        assert budget.events[-1][0] == "check_send"
        response = handler(request) if handler else httpx.Response(200, json={"title": "결과 😀", "content": MARKDOWN},
                                                                   headers={"x-request-id": "synthetic-receipt"})
        if response.is_stream_consumed:
            response = httpx.Response(response.status_code, headers=response.headers, stream=httpx.ByteStream(response.content))
        return response

    client = DeepSeekFetchClient(api_key="synthetic-only", budget=budget, set_id="synthetic-acquisition",
                                allowed_hosts=HOSTS, transport=httpx.MockTransport(send), pacer=pacer or Pacer(),
                                max_response_bytes=max_response_bytes,
                                resolver=resolver or (lambda host, port: ["93.184.216.34"]), clock=lambda: WHEN)
    return client, budget, calls


def test_native_success_does_not_fallback_and_envelope_is_frozen():
    page = extract_page(native(), allowed_hosts=HOSTS, defuddle=forbidden)
    assert page.backend == "native" and page.format == "html"
    assert page.retained_text.encode() == BODY
    assert page.prepared["text"] == "한글 😀 e\u0301 실적 발표."
    assert page.provider_receipt is None
    assert page.wire()["nativeObservation"]["httpStatus"] == 200
    with pytest.raises(FrozenInstanceError):
        page.backend = "defuddle"
    copy = page.prepared
    copy["text"] = "changed"
    assert page.prepared["text"] != "changed"


def test_parser_failure_uses_same_retained_bytes_and_new_extracted_html_coordinates():
    raw = b"<html><title>Report</title><main><p>Unscoped retained report.</p></main></html>"
    received = []

    def local(body, url):
        received.append((body, url))
        return "<html><body><p>Unscoped retained report.</p></body></html>"

    page = extract_page(native(body=raw), allowed_hosts=HOSTS, defuddle=local)
    assert received == [(raw, URL)] and received[0][0] is raw
    assert page.backend == "defuddle" and page.format == "html"
    assert page.normalization_profile["coordinates"] == "retained-extracted-html-dom"
    assert page.fallback_reasons == ("article_scope_ambiguous_or_missing",)
    assert base64.b64decode(page.wire()["nativeObservation"]["rawBodyBase64"]) == raw
    assert page.retained_text.encode() != raw


def test_public_client403_falls_back_with_separate_receipt_exact_markdown_and_unknown_metadata():
    client, budget, calls = provider()
    page = extract_page(native(http_status=403, body=None, failure_code="http_403"), allowed_hosts=HOSTS,
                        defuddle=forbidden, provider=client,
                        metadata=ObservedMetadata("Old title", "2026-01-01", "Old publisher"))
    wire = page.wire()
    assert len(calls) == 1 and page.backend == "deepseek-fetch" and page.format == "markdown"
    assert page.final_url is None and page.observed_at == WHEN
    assert page.retained_text == page.prepared["text"] == MARKDOWN
    assert wire["metadata"] == {"title": "결과 😀", "publishedAt": None, "publisher": None, "publicationPrecision": "unknown"}
    assert wire["nativeObservation"]["httpStatus"] == 403
    receipt = wire["providerReceipt"]
    raw = base64.b64decode(receipt["rawResponseBase64"])
    assert receipt["rawResponseSha256"] == byte_hash(raw)
    assert json.loads(raw)["content"] == MARKDOWN
    assert receipt["httpStatus"] == 200 and receipt["actualNano"] == FETCH_COST_NANO
    assert [e[0] for e in budget.events] == ["reserve", "check_send", "settle"]
    assert budget.events[0][2:4] == ("fetch", "deepseek-fetch")
    assert budget.events[0][5:] == (750_000, FETCH_ACCOUNT_ROLE, "synthetic-acquisition")


@pytest.mark.parametrize("changes", [
    {"access": "auth"}, {"access": "private"}, {"access": "robots"}, {"access": "deleted"},
    {"www_authenticate": True}, {"failure_code": "robots_denied"}, {"failure_code": "robots_unavailable"},
    {"http_status": 401}, {"http_status": 410}, {"http_status": 429},
])
def test_actual_access_denials_do_not_route_around(changes):
    client, budget, calls = provider()
    with pytest.raises(ExtractionFallbackFailure):
        extract_page(native(**changes), allowed_hosts=HOSTS, defuddle=forbidden, provider=client)
    assert not budget.events and not calls


@pytest.mark.parametrize("body", [
    b"<html><title>404 Page not found</title><article>Not an article.</article></html>",
    b"<html><title>Login required</title><input type=password></html>",
    b"<html><title>Verify you are human</title><article>Challenge</article></html>",
    b'<html><script type="application/ld+json">{"isAccessibleForFree": false}</script><article>Paywall</article></html>',
    b"<html><h1>Content deleted</h1><article>Gone.</article></html>",
])
def test_soft404_login_captcha_paywall_deleted_rejected_before_any_fallback(body):
    client, budget, calls = provider()
    with pytest.raises(ExtractionFallbackFailure):
        extract_page(native(body=body), allowed_hosts=HOSTS, defuddle=forbidden, provider=client)
    assert not budget.events and not calls


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_provider_known_failure_is_retained_and_not_retried(status):
    client, budget, calls = provider(lambda _: httpx.Response(status, json={"error": {"message": "denied"}}))
    with pytest.raises(ExtractionFallbackFailure, match=f"provider_http_{status}") as error:
        extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    assert len(calls) == 1 and budget.events[-1][0::2] == ("settle", 0)
    assert error.value.native_observation.http_status == 403
    assert error.value.provider_receipt.http_status == status
    assert json.loads(error.value.provider_receipt.raw_response)["error"]["message"] == "denied"


def test_native_unknown_transport_never_sends_provider():
    client, budget, calls = provider()
    with pytest.raises(ExtractionFallbackFailure, match="native_unknown_no_retry"):
        extract_page(native(http_status=None, body=None, failure_code="timeout"), allowed_hosts=HOSTS, provider=client)
    assert not budget.events and not calls


def test_provider_unknown_transport_keeps_reservation_no_retry():
    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)
    client, budget, calls = provider(timeout)
    with pytest.raises(ExtractionFallbackFailure, match="provider_unknown_no_retry") as error:
        extract_page(native(http_status=404, body=None), allowed_hosts=HOSTS, provider=client)
    assert len(calls) == 1 and [e[0] for e in budget.events] == ["reserve", "check_send"]
    assert error.value.provider_receipt.outcome == "unknown"
    assert error.value.provider_receipt.actual_nano is None


@pytest.mark.parametrize(("value", "precision"), [
    (None, "unknown"), ("2026-10-28", "day"), ("2026-10-28T03:21", "minute"),
    ("2026-10-28T03:21:19+09:00", "second"), ("2026-10-28T03:21:19.12Z", "subsecond"),
    ("2026-02-30", "unknown"), ("October 28, 2026", "unknown"),
])
def test_publication_metadata_keeps_original_precision_without_midnight(value, precision):
    meta = ObservedMetadata(published_at=value)
    page = extract_page(native(), allowed_hosts=HOSTS, metadata=meta)
    assert page.metadata.published_at == value
    assert page.metadata.publication_precision == precision
    assert page.metadata.publisher is None


def test_unicode_citations_are_exact_codepoint_copies_with_code_links_and_backslashes():
    prepared = prepare_markdown(MARKDOWN)
    assert prepared["text"] == MARKDOWN
    for segment in prepared["segments"]:
        assert prepared["text"][segment["cleanStart"]:segment["cleanEnd"]] == prepared["sources"][segment["sourceIndex"]]["text"][segment["sourceStart"]:segment["sourceEnd"]]
    citation = "결과 😀"
    start = prepared["text"].index(citation)
    assert prepared["text"][start:start + len(citation)] == citation
    assert "e\u0301" in prepared["text"] and "\\{값\\}" in prepared["text"]


@pytest.mark.parametrize("content", ["", " \n\t", "\x00invalid", "# 404 Page not found\n", "# Login required\n"])
def test_invalid_empty_or_error_markdown_never_becomes_analysis(content):
    client, budget, calls = provider(lambda _: httpx.Response(200, json={"title": "", "content": content}))
    with pytest.raises(ExtractionFallbackFailure) as error:
        extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    assert len(calls) == 1
    assert budget.events[-1][2] == (FETCH_COST_NANO if content.strip() else 0)
    assert error.value.provider_receipt.raw_response is not None


@pytest.mark.parametrize("raw", [b'{"title":null,"content":"x"}', b'{"content":"x"}', b'not-json',
                                 b'{"title":"a","title":"b","content":"x"}', b'{"title":"x","content":"\\ud800"}'])
def test_malformed_provider_response_is_not_silently_normalized(raw):
    client, budget, calls = provider(lambda _: httpx.Response(200, content=raw))
    with pytest.raises(ExtractionFallbackFailure):
        extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    assert len(calls) == 1
    assert not any(e[0] == "release" for e in budget.events)


def test_malformed_html_does_not_get_second_native_request():
    client, _, calls = provider()
    page = extract_page(native(body=b"\xff<html>"), allowed_hosts=HOSTS, defuddle=forbidden, provider=client)
    assert page.backend == "deepseek-fetch" and "native_invalid_utf8" in page.fallback_reasons
    assert len(calls) == 1


@pytest.mark.parametrize(("media", "body"), [("application/rss+xml", b"<rss/>"), ("text/html", b"<?xml version='1.0'?><feed/>"),
                                              ("application/json", b'{}')])
def test_structured_documents_are_never_reinterpreted_as_articles(media, body):
    client, budget, calls = provider()
    with pytest.raises(ExtractionFallbackFailure, match="fallback_structured_document_refused"):
        extract_page(native(media_type=media, body=body), allowed_hosts=HOSTS, provider=client)
    assert not budget.events and not calls


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://169.254.169.254/", "https://10.0.0.1/", "https://localhost/",
                                 "https://user:password@news.example/", "file:///etc/passwd", "https://news.example/%2e%2e/a",
                                 "https://[::ffff:127.0.0.1]/", "https://[64:ff9b::7f00:1]/"])
def test_egress_url_guards(url):
    with pytest.raises(Exception):
        guard_public_url(url, (*HOSTS, "127.0.0.1", "169.254.169.254", "10.0.0.1", "localhost", "::ffff:127.0.0.1", "64:ff9b::7f00:1"))


def test_dns_private_address_mixed_answers_refuse_before_reserving():
    client, budget, calls = provider(resolver=lambda h, p: ["93.184.216.34", "10.2.3.4"])
    with pytest.raises(ExtractionFallbackFailure, match="fallback_private_address"):
        extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    assert not budget.events and not calls


@pytest.mark.parametrize("final", ["https://other.example/article", "http://news.example/article"])
def test_known_native_redirects_must_match_host_and_no_downgrade(final):
    with pytest.raises(ExtractionFallbackFailure):
        extract_page(native(final_url=final, redirects=(final,)), allowed_hosts=HOSTS, defuddle=forbidden)


def test_budget_closure_releases_only_proven_unsent_attempt():
    client, budget, calls = provider(budget=Budget(refuse=True))
    with pytest.raises(RuntimeError, match="admission closed"):
        extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    assert not calls
    assert [e[0] for e in budget.events] == ["reserve", "check_send", "release"]


def test_provider_http_redirect_not_followed_or_claimed_as_final_url():
    client, budget, calls = provider(lambda _: httpx.Response(302, headers={"Location": "http://127.0.0.1/"}))
    with pytest.raises(ExtractionFallbackFailure, match="provider_http_302"):
        extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    assert len(calls) == 1 and budget.events[-1][2] == 0


@pytest.mark.parametrize("backend", ["native", "defuddle", "deepseek-fetch"])
def test_pinned_envelope_revalidates_offline_without_any_provider_or_node(backend):
    if backend == "native":
        page = extract_page(native(), allowed_hosts=HOSTS)
    elif backend == "defuddle":
        page = extract_page(native(body=b"<html><main>Report.</main></html>"), allowed_hosts=HOSTS,
                            defuddle=lambda raw, url: "<html><body>Report.</body></html>")
    else:
        client, _, calls = provider()
        page = extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
        assert len(calls) == 1
    assert verify_extracted_page(page.wire(), allowed_hosts=HOSTS).wire() == page.wire()


@pytest.mark.parametrize("field", ["retainedText", "rawSha256", "contentSha256", "finalUrl", "prepared", "normalizationProfile"])
def test_offline_envelope_verifier_refuses_artifact_and_coordinate_tampering(field):
    client, _, _ = provider()
    wire = extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client).wire()
    wire[field] = "tampered"
    with pytest.raises(ExtractionFallbackFailure, match="extracted_page_invalid"):
        verify_extracted_page(wire, allowed_hosts=HOSTS)


def test_offline_envelope_verifier_rejects_invented_provider_publication_and_original_final_url():
    client, _, _ = provider()
    page = extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    for mutation in ("metadata", "providerReceipt", "nativeObservation"):
        wire = page.wire()
        if mutation == "metadata":
            wire["metadata"]["publishedAt"] = "2026-10-28T00:00:00Z"
        elif mutation == "providerReceipt":
            wire["providerReceipt"]["httpStatus"] = 404
        else:
            wire["nativeObservation"]["access"] = "robots"
        with pytest.raises(ExtractionFallbackFailure, match="extracted_page_invalid"):
            verify_extracted_page(wire, allowed_hosts=HOSTS)


def known_unsent(**prior_changes):
    prior = native(requested_url="https://news.example/previous", final_url="https://news.example/previous",
                   http_status=403, body=None, failure_code="http_403")
    prior = replace(prior, **prior_changes)
    cause = PriorPublicClient403(prior, "native-refusal-prior.json", digest(prior.wire()), URL, WHEN)
    return native(http_status=None, body=None, final_url=None, failure_code="host_blocked", known_unsent=cause)


def test_known_unsent_new_url_preserves_original403_pin_without_inventing_another_native_response():
    client, budget, calls = provider()
    observation = known_unsent()
    page = extract_page(observation, allowed_hosts=HOSTS, provider=client, defuddle=forbidden)
    assert len(calls) == 1
    assert page.fallback_reasons == ("prior_public_client_403",)
    wire = page.wire()
    current = wire["nativeObservation"]
    assert current["httpStatus"] is None and current["rawBodyBase64"] is None and current["finalUrl"] is None
    assert current["failureCode"] == "host_blocked"
    cause = current["knownUnsent"]
    assert cause["disposition"] == "prior_public_client_403"
    assert cause["observation"]["httpStatus"] == 403
    assert cause["receiptSha256"] == digest(cause["observation"])
    assert cause["robotsAllowedUrl"] == URL
    assert [entry[0] for entry in budget.events] == ["reserve", "check_send", "settle"]
    assert verify_extracted_page(wire, allowed_hosts=HOSTS).wire() == wire


@pytest.mark.parametrize("prior_changes", [
    {"http_status": 401}, {"http_status": 429}, {"failure_code": "provider_http_403"},
    {"access": "auth"}, {"access": "private"}, {"access": "robots"}, {"access": "unknown"},
    {"www_authenticate": True}, {"failure_code": "robots_denied"},
    {"requested_url": URL, "final_url": URL},
    {"requested_url": "http://news.example/previous", "final_url": "http://news.example/previous"},
    {"final_url": "https://different.example/previous"},
    {"body": b"<html><title>Just a moment</title><p>Challenge</p></html>"},
    {"body": b'<html><input type="password"><p>Private account</p></html>'},
    {"body": b'<html><script type="application/ld+json">{"isAccessibleForFree":false}</script></html>'},
    {"body": b"\xffundecodable refusal"},
])
def test_prior_refusal_must_be_unambiguously_public_client403(prior_changes):
    client, budget, calls = provider()
    with pytest.raises(ExtractionFallbackFailure, match="fallback_known_unsent_invalid"):
        extract_page(known_unsent(**prior_changes), allowed_hosts=HOSTS, provider=client, defuddle=forbidden)
    assert not calls and not budget.events


@pytest.mark.parametrize("changes", [
    {"receipt_ref": ""}, {"receipt_sha256": "0" * 64},
    {"robots_allowed_url": "https://news.example/another"},
    {"robots_observed_at": "2026-10-28"},
    {"robots_observed_at": "2026-10-29T00:00:00Z"},
])
def test_known_unsent_requires_pinned_cause_and_current_url_robots_evidence(changes):
    client, budget, calls = provider()
    observation = known_unsent()
    observation = replace(observation, known_unsent=replace(observation.known_unsent, **changes))
    with pytest.raises(ExtractionFallbackFailure, match="fallback_known_unsent_invalid"):
        extract_page(observation, allowed_hosts=HOSTS, provider=client)
    assert not calls and not budget.events


@pytest.mark.parametrize("code", ["host_blocked", "prior_host_blocked", "timeout", "network_error"])
def test_generic_host_block_or_unknown_transport_cannot_use_provider_without_typed_cause(code):
    client, budget, calls = provider()
    with pytest.raises(ExtractionFallbackFailure):
        extract_page(native(http_status=None, body=None, final_url=None, failure_code=code),
                     allowed_hosts=HOSTS, provider=client)
    assert not calls and not budget.events


def test_typed_cause_cannot_relabel_an_unknown_transmitted_request_as_known_unsent():
    client, budget, calls = provider()
    observation = replace(known_unsent(), failure_code="timeout")
    with pytest.raises(ExtractionFallbackFailure, match="fallback_known_unsent_invalid"):
        extract_page(observation, allowed_hosts=HOSTS, provider=client)
    assert not calls and not budget.events


def test_offline_verifier_refuses_mutated_known_unsent_causal_receipt():
    client, _, _ = provider()
    page = extract_page(known_unsent(), allowed_hosts=HOSTS, provider=client)
    wire = page.wire()
    wire["nativeObservation"]["knownUnsent"]["observation"]["httpStatus"] = 401
    with pytest.raises(ExtractionFallbackFailure, match="extracted_page_invalid"):
        verify_extracted_page(wire, allowed_hosts=HOSTS)


def test_pacing_wait_occurs_before_any_monetary_attempt_and_keeps_robots_interval():
    budget = Budget()

    class ObservedPacer(Pacer):
        def acquire(self, url, **timing):
            assert not budget.events
            return super().acquire(url, **timing)

    pacing = ObservedPacer()
    client, _, calls = provider(budget=budget, pacer=pacing)
    client.fetch(URL, min_interval_seconds=7, not_before_monotonic=123)
    assert len(calls) == 1
    assert pacing.calls[0][1]["min_interval_seconds"] == 7
    assert pacing.calls[0][1]["not_before_monotonic"] == 123
    assert [event[0] for event in budget.events] == ["reserve", "check_send", "settle"]


def test_pacing_deadline_is_proven_unsent_without_even_a_budget_reservation():
    class RefusedPacer(Pacer):
        def acquire(self, url, **timing):
            raise ExtractionFallbackFailure("fetch_pacing_deadline")

    client, budget, calls = provider(pacer=RefusedPacer())
    with pytest.raises(ExtractionFallbackFailure, match="fetch_pacing_deadline"):
        extract_page(known_unsent(), allowed_hosts=HOSTS, provider=client)
    assert not budget.events and not calls


def test_native_success_does_not_acquire_a_provider_pacing_slot():
    pacing = Pacer()
    client, budget, calls = provider(pacer=pacing)
    extract_page(native(), allowed_hosts=HOSTS, provider=client)
    assert not pacing.calls and not budget.events and not calls


class ChunkedBody(httpx.SyncByteStream):
    def __init__(self, *parts):
        self.parts = parts

    def __iter__(self):
        for part in self.parts:
            if isinstance(part, Exception):
                raise part
            yield part


def test_provider_response_byte_limit_accepts_exact_complete_identity_body():
    raw = json.dumps({"title": "Exact result", "content": MARKDOWN}, ensure_ascii=False).encode()
    client, budget, calls = provider(lambda _: httpx.Response(200, stream=ChunkedBody(raw)),
                                    max_response_bytes=len(raw))
    page = extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    receipt = page.provider_receipt
    assert receipt.raw_response == raw and receipt.received_bytes == len(raw)
    assert receipt.response_byte_limit == len(raw)
    assert calls[0].headers["Accept-Encoding"] == "identity"
    assert budget.events[-1][2] == FETCH_COST_NANO
    assert verify_extracted_page(page.wire(), allowed_hosts=HOSTS).wire() == page.wire()


def test_provider_response_overflow_retains_actual_read_ahead_count_without_fake_complete_body():
    client, budget, calls = provider(
        lambda _: httpx.Response(200, stream=ChunkedBody(b"12345678", b"abcdefghij", b"not-read")),
        max_response_bytes=16)
    with pytest.raises(ExtractionFallbackFailure, match="provider_unknown_no_retry") as error:
        extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    receipt = error.value.provider_receipt
    assert len(calls) == 1 and receipt.outcome == "unknown"
    assert receipt.received_bytes == 18 and receipt.response_byte_limit == 16
    assert receipt.raw_response is None and receipt.wire()["rawResponseSha256"] is None
    assert [event[0] for event in budget.events] == ["reserve", "check_send"]


def test_partial_provider_body_failure_counts_unyielded_buffered_bytes():
    client, budget, calls = provider(
        lambda _: httpx.Response(200, stream=ChunkedBody(b"partial", httpx.ReadError("synthetic disconnect"))),
        max_response_bytes=100)
    with pytest.raises(ExtractionFallbackFailure, match="provider_unknown_no_retry") as error:
        extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    assert len(calls) == 1
    assert error.value.provider_receipt.received_bytes == 7
    assert error.value.provider_receipt.raw_response is None
    assert not any(event[0] in {"settle", "release"} for event in budget.events)


def test_unexpected_provider_compression_preserves_raw_bytes_without_decoding_into_article():
    compressed = gzip.compress(json.dumps({"title": "Compressed", "content": MARKDOWN}).encode())
    client, budget, calls = provider(
        lambda _: httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=ChunkedBody(compressed)),
        max_response_bytes=len(compressed))
    with pytest.raises(ExtractionFallbackFailure, match="provider_invalid_response") as error:
        extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client)
    receipt = error.value.provider_receipt
    assert len(calls) == 1 and receipt.raw_response == compressed
    assert receipt.received_bytes == len(compressed) and receipt.outcome == "invalid"
    assert [event[0] for event in budget.events] == ["reserve", "check_send"]


@pytest.mark.parametrize("limit", [0, -1, 10_000_001, True, 1.5])
def test_invalid_provider_response_byte_limit_refused_before_any_request(limit):
    with pytest.raises(ExtractionFallbackFailure, match="fallback_configuration_invalid"):
        provider(max_response_bytes=limit)


@pytest.mark.parametrize("field", ["receivedBytes", "responseByteLimit"])
def test_offline_verifier_refuses_provider_byte_accounting_tampering(field):
    client, _, _ = provider()
    wire = extract_page(native(http_status=403, body=None), allowed_hosts=HOSTS, provider=client).wire()
    wire["providerReceipt"][field] = 1
    with pytest.raises(ExtractionFallbackFailure, match="extracted_page_invalid"):
        verify_extracted_page(wire, allowed_hosts=HOSTS)


CHALLENGE = b"<html><title>Just a moment...</title><body><form id='challenge-form'>Verify you are human</form></body></html>"


def public_challenge(**changes):
    observation = native(http_status=403, body=CHALLENGE, failure_code="http_403",
                         public_article_ref="source-discovery:news.example/article",
                         robots_allowed_url=URL, robots_observed_at=WHEN)
    return replace(observation, **changes)


@pytest.mark.parametrize("status", [200, 403, 404])
def test_qualified_public_origin_challenge_is_not_article_content_but_can_use_official_fetch(status):
    client, _, calls = provider()
    observation = public_challenge(http_status=status, failure_code="access_restricted" if status == 200 else f"http_{status}")
    page = extract_page(observation, allowed_hosts=HOSTS, defuddle=forbidden, provider=client)
    assert len(calls) == 1 and page.backend == "deepseek-fetch" and page.retained_text == MARKDOWN
    assert page.native_observation.body == CHALLENGE
    assert "public_origin_challenge" in page.fallback_reasons
    assert "Verify you are human" not in page.prepared["text"]
    assert verify_extracted_page(page.wire(), allowed_hosts=HOSTS).wire() == page.wire()


@pytest.mark.parametrize("changes", [
    {"public_article_ref": None}, {"robots_allowed_url": "https://news.example/different"},
    {"robots_observed_at": "2026-10-29T00:00:00Z"}, {"access": "auth"},
    {"www_authenticate": True}, {"http_status": 429}, {"failure_code": "robots_denied"},
    {"body": b"<html><title>Just a moment</title><input type=password></html>"},
    {"body": b'<html><title>Just a moment</title><script type="application/ld+json">{"isAccessibleForFree":false}</script></html>'},
    {"body": b'<html><h1 class="paywall">Just a moment</h1></html>'},
    {"body": b"<html><title>Just a moment</title><p>Automated access is prohibited by publisher policy.</p></html>"},
])
def test_origin_challenge_exception_still_requires_public_proof_and_refuses_real_access_denial(changes):
    client, budget, calls = provider()
    with pytest.raises(ExtractionFallbackFailure):
        extract_page(public_challenge(**changes), allowed_hosts=HOSTS, defuddle=forbidden, provider=client)
    assert not calls and not budget.events


@pytest.mark.parametrize("status", [403, 404])
def test_public_origin_challenge_never_routes_around_provider_denial(status):
    client, _, calls = provider(lambda _: httpx.Response(status, json={"error": {"message": "denied"}}))
    with pytest.raises(ExtractionFallbackFailure, match=f"provider_http_{status}"):
        extract_page(public_challenge(), allowed_hosts=HOSTS, provider=client)
    assert len(calls) == 1


def test_provider_challenge_remains_unusable_even_when_origin_challenge_was_eligible():
    client, budget, calls = provider(lambda _: httpx.Response(200, json={"title": "Just a moment", "content": "# Verify you are human"}))
    with pytest.raises(ExtractionFallbackFailure, match="fallback_error_page"):
        extract_page(public_challenge(), allowed_hosts=HOSTS, provider=client)
    assert len(calls) == 1 and budget.events[-1][2] == FETCH_COST_NANO


def test_qualified_prior_origin_challenge_can_support_known_unsent_new_public_url():
    observation = known_unsent(body=CHALLENGE, public_article_ref="source-discovery:previous",
                               robots_allowed_url="https://news.example/previous", robots_observed_at=WHEN)
    observation = replace(observation, public_article_ref="source-discovery:current",
                          robots_allowed_url=URL, robots_observed_at=WHEN)
    client, _, calls = provider()
    page = extract_page(observation, allowed_hosts=HOSTS, provider=client)
    assert len(calls) == 1 and page.native_observation.http_status is None
    assert page.native_observation.known_unsent.observation.body == CHALLENGE
    assert verify_extracted_page(page.wire(), allowed_hosts=HOSTS).wire() == page.wire()


def test_origin_challenge_public_evidence_is_required_again_during_offline_verification():
    client, _, _ = provider()
    wire = extract_page(public_challenge(), allowed_hosts=HOSTS, provider=client).wire()
    wire["nativeObservation"]["publicArticleRef"] = None
    with pytest.raises(ExtractionFallbackFailure, match="extracted_page_invalid"):
        verify_extracted_page(wire, allowed_hosts=HOSTS)
