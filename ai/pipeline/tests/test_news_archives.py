"""Pure authored metadata fixtures: no network, private article bodies, or wall clock."""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest

from zoop_ai_pipeline import news_archives as archives
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure
from zoop_ai_pipeline.ingestion_parsers import prepare
from zoop_ai_pipeline.news_archives import (
    ArticleMeta, Candidate, Listing, article_metadata, initial_tasks, parse_listing, source_hosts, validate_discovery_url,
)

DAY = "2026-07-25"
HK = "https://www.hankyung.com/article/202607255242i"
LOOP = "http://127.0.0.1:18765"


def task(source="hankyung-daily", **kwargs):
    return initial_tasks(source, DAY, DAY, ("NVIDIA",) if source == "gdelt-doc" else (), **kwargs)[0]


def listing(raw, source="hankyung-daily", **kwargs):
    selected = task(source, **kwargs)
    return parse_listing(source, selected, raw, selected.url, **kwargs)


def xml(urls=(HK,), *, prefix=False):
    tag = "s:" if prefix else ""
    namespace = f'xmlns{":s" if prefix else ""}="{archives.SITEMAP_NS}"'
    entries = "".join(f"<{tag}url><{tag}loc>{escape(url)}</{tag}loc><{tag}lastmod>2026-10-25T10:05:00+09:00</{tag}lastmod></{tag}url>" for url in urls)
    return f"<{tag}urlset {namespace}>{entries}</{tag}urlset>".encode()


def gdelt(rows):
    return json.dumps({"articles": rows}).encode()


def document(head='', body='<article><p>Authored synthetic paragraph.</p></article>'):
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>".encode()


def og(*, published=None, title="Synthetic headline", extra="", body=None):
    head = f'<meta property="og:title" content="{escape(title)}">'
    if published is not None:
        head += f'<meta property="article:published_time" content="{escape(published)}">'
    return document(head + extra, body if body is not None else '<div id="articletxt">Authored scope.</div>')


def schema(item):
    return '<script type="application/ld+json">' + json.dumps(item) + '</script>'


def failed(code, function, *args, **kwargs):
    with pytest.raises(IngestionFailure) as failure:
        function(*args, **kwargs)
    assert failure.value.code == code
    assert str(failure.value) == code


def test_full_inclusive_window_and_calendar_boundaries():
    tasks = initial_tasks("hankyung-daily", DAY, "2026-10-25")
    assert len(tasks) == 93 and len({item.url for item in tasks}) == 93
    assert tasks[0].url.endswith("/20260725.xml")
    assert tasks[-1].url.endswith("/20261025.xml")
    assert all(item.from_day == item.through_day and item.kind == "sitemap-xml" for item in tasks)
    leap = initial_tasks("hankyung-daily", "2024-02-28", "2024-03-01")
    assert [item.from_day for item in leap] == ["2024-02-28", "2024-02-29", "2024-03-01"]
    assert len(initial_tasks("hankyung-daily", "2025-01-01", "2026-01-01")) == archives.MAX_DAYS


@pytest.mark.parametrize(("first", "last", "code"), [
    ("2026-02-29", DAY, "archive_date_invalid"), ("20260725", DAY, "archive_date_invalid"),
    (None, DAY, "archive_date_invalid"), (DAY, "2026-07-24", "archive_window_invalid"),
    ("2025-01-01", "2026-01-02", "archive_window_invalid"),
])
def test_invalid_windows(first, last, code):
    failed(code, initial_tasks, "hankyung-daily", first, last)


def test_gdelt_exact_query_and_day_partitions_are_deterministic():
    queries = ('"Samsung Electronics" sourcelang:korean', "삼성전자 OR NVIDIA")
    tasks = initial_tasks("gdelt-doc", DAY, "2026-07-26", queries + queries)
    assert len(tasks) == 4 and len({item.key for item in tasks}) == 4
    assert tasks == initial_tasks("gdelt-doc", DAY, "2026-07-26", queries)
    for selected in tasks:
        params = dict(parse_qsl(urlsplit(selected.url).query))
        assert params["query"] in queries
        assert params["startdatetime"] == selected.from_day.replace("-", "") + "000000"
        assert params["enddatetime"] == selected.through_day.replace("-", "") + "235959"
        assert params["mode"] == "artlist" and params["format"] == "json"
        assert params["maxrecords"] == "250" and params["sort"] == "dateasc"
        assert validate_discovery_url("gdelt-doc", selected.url) == selected.url
        assert selected.kind == "gdelt-artlist"


@pytest.mark.parametrize("queries", [(), ("",), (" \t",), ("a\nb",), ("a" * 1001,), ("\ud800",), tuple(str(i) for i in range(65)), ["NVIDIA"]])
def test_queries_are_required_and_bounded(queries):
    failed("archive_query_invalid", initial_tasks, "gdelt-doc", DAY, DAY, queries)


def test_hankyung_has_no_unsupported_query_semantics():
    failed("archive_query_invalid", initial_tasks, "hankyung-daily", DAY, DAY, ("NVIDIA",))
    failed("archive_source_unsupported", source_hosts, "corporate-newsroom-not-proven")
    assert source_hosts("hankyung-daily") == ("www.hankyung.com",)
    assert source_hosts("gdelt-doc") == ("api.gdeltproject.org",)


@pytest.mark.parametrize("prefix", [False, True])
def test_secure_sitemap_namespace_duplicates_and_lastmod_not_publication(prefix):
    result = listing(xml((HK, HK, "https://www.hankyung.com/article/202607255243i"), prefix=prefix))
    assert result.candidates == (
        Candidate(HK, None, None, None, DAY),
        Candidate("https://www.hankyung.com/article/202607255243i", None, None, None, DAY),
    )
    assert result.next_tasks == () and not result.saturated
    assert listing(xml(())).candidates == ()


@pytest.mark.parametrize("raw", [
    b"<urlset>", b"<urlset/>", b'<urlset xmlns="https://attacker.invalid"/>',
    f'<urlset xmlns="{archives.SITEMAP_NS}"><url><loc>{HK}</loc><loc>{HK}</loc></url></urlset>'.encode(),
    f'<urlset xmlns="{archives.SITEMAP_NS}"><url><loc><b>{HK}</b></loc></url></urlset>'.encode(),
    f'<urlset xmlns="{archives.SITEMAP_NS}" xmlns:e="https://attacker.invalid"><e:url><e:loc>{HK}</e:loc></e:url></urlset>'.encode(),
])
def test_malformed_or_wrong_namespace_xml_fails_closed(raw):
    failed("archive_xml_invalid", listing, raw)


@pytest.mark.parametrize("declaration", [
    '<!DOCTYPE urlset SYSTEM "file:///definitely-not-an-article">',
    '<!DOCTYPE urlset [<!ENTITY body SYSTEM "https://attacker.invalid/no-network">]>',
])
def test_dtd_and_external_entities_are_not_loaded(declaration):
    raw = (declaration + f'<urlset xmlns="{archives.SITEMAP_NS}"/>').encode()
    failed("archive_xml_unsafe", listing, raw)


@pytest.mark.parametrize("url", [
    "https://www.hankyung.com.attacker.invalid/article/202607255242i",
    "https://hankyung.com/article/202607255242i", "http://www.hankyung.com/article/202607255242i",
    "https://www.hankyung.com:444/article/202607255242i", "https://www.hankyung.com/sitemap/anything",
    HK + "?redirect=elsewhere", HK + "#fragment",
])
def test_sitemap_article_hosts_and_routes_are_exact(url):
    failed("archive_article_host_invalid", listing, xml((url,)))


@pytest.mark.parametrize("url", [
    "https://www.hankyung.com/sitemap/daily-article/20260725.xml?x=1",
    "https://www.hankyung.com/sitemap/daily-article/20260725.xml#fragment",
    "https://www.hankyung.com/article/202607255242i",
    "https://www.hankyung.com.attacker.invalid/sitemap/daily-article/20260725.xml",
    "https://www.hankyung.com:444/sitemap/daily-article/20260725.xml",
    "http://www.hankyung.com/sitemap/daily-article/20260725.xml",
    "https://name:password@www.hankyung.com/sitemap/daily-article/20260725.xml",
])
def test_discovery_hankyung_endpoint_is_checked_before_fetch(url):
    failed("archive_endpoint_invalid", validate_discovery_url, "hankyung-daily", url)


@pytest.mark.parametrize("change", [
    {"format": "html"}, {"mode": "timelinevol"}, {"maxrecords": "10"}, {"sort": "tonedesc"},
    {"callback": "malicious"}, {"startdatetime": "20260725120000"}, {"enddatetime": "20260726000000"},
])
def test_gdelt_endpoint_rejects_unapproved_mode_or_time_shape(change):
    selected = task("gdelt-doc")
    params = dict(parse_qsl(urlsplit(selected.url).query)) | change
    url = selected.url.split("?")[0] + "?" + urlencode(params)
    failed("archive_endpoint_invalid", validate_discovery_url, "gdelt-doc", url)


def test_gdelt_endpoint_duplicate_params_and_wrong_paths_rejected():
    selected = task("gdelt-doc")
    failed("archive_endpoint_invalid", validate_discovery_url, "gdelt-doc", selected.url + "&query=NVIDIA")
    failed("archive_endpoint_invalid", validate_discovery_url, "gdelt-doc", selected.url.replace("/doc/doc?", "/doc/other?"))
    failed("archive_endpoint_invalid", validate_discovery_url, "gdelt-doc", selected.url.replace("api.gdeltproject.org", "api.gdeltproject.org.attacker.invalid"))


def test_task_key_kind_and_partition_bind_listing_identity():
    selected = task()
    for forged in (replace(selected, key="different"), replace(selected, kind="gdelt-artlist"),
                   replace(selected, from_day="2026-07-24"), replace(selected, through_day="2026-07-26")):
        failed("archive_task_invalid", parse_listing, "hankyung-daily", forged, xml(), selected.url)
    failed("archive_task_invalid", parse_listing, "hankyung-daily", selected, xml(), selected.url.replace("20260725", "20260726"))
    gd = task("gdelt-doc")
    failed("archive_task_invalid", parse_listing, "gdelt-doc", gd, gdelt([]), gd.url.replace("NVIDIA", "Samsung"))
    reordered = gd.url.split("?")[0] + "?" + urlencode(list(reversed(parse_qsl(urlsplit(gd.url).query))))
    assert parse_listing("gdelt-doc", gd, gdelt([]), reordered) == Listing((), (), False)


def test_gdelt_seendate_never_becomes_publication_or_archive_day():
    rows = [{"url": "https://publisher.invalid/a%2Fb?q=%2F%26&edition=+#section", "title": "Lead only", "seendate": "20260726T001500Z", "domain": "wrong.invalid"}]
    candidate = listing(gdelt(rows), "gdelt-doc").candidates[0]
    assert candidate.url == rows[0]["url"].split("#")[0]
    assert candidate.discovery_seen_at == "20260726T001500Z"
    assert candidate.published_at is None and candidate.archive_day is None
    # The API's returned seen dates can exceed requested bounds; do not silently discard.
    assert candidate.title == "Lead only"


def test_gdelt_duplicates_preserve_exact_encoded_url_identities_and_unknown_conflicts():
    result = listing(gdelt([
        {"url": "https://publisher.invalid/a%2Fb", "title": "One", "seendate": "20260725T120000Z"},
        {"url": "https://publisher.invalid/a/b", "title": "Two"},
        {"url": "https://publisher.invalid/a%2Fb#fragment", "title": "Conflicting", "seendate": "20260725T121500Z"},
        {"url": "https://publisher.invalid/a%2Fb", "title": "One", "seendate": "20260725T120000Z"},
    ]), "gdelt-doc")
    assert len(result.candidates) == 2
    assert result.candidates[0] == Candidate("https://publisher.invalid/a%2Fb", None, None, None, None)


def test_gdelt_cap_counts_raw_rows_before_dedup_and_does_not_claim_complete():
    result = listing(gdelt([{"url": "https://publisher.invalid/same"}] * 250), "gdelt-doc")
    assert len(result.candidates) == 1 and result.saturated and result.next_tasks == ()
    assert not listing(gdelt([{"url": "https://publisher.invalid/same"}] * 249), "gdelt-doc").saturated
    failed("archive_listing_limit", listing, gdelt([{"url": "https://publisher.invalid/same"}] * 251), "gdelt-doc")


def test_sitemap_ceiling_is_visible_even_after_dedup(monkeypatch):
    monkeypatch.setattr(archives, "MAX_SITEMAP_URLS", 2)
    assert listing(xml((HK, HK))).saturated
    failed("archive_listing_limit", listing, xml((HK, HK, HK)))


@pytest.mark.parametrize(("raw", "code"), [
    (b'{"articles":[],"articles":[]}', "archive_json_invalid"), (b'NaN', "archive_json_invalid"),
    (b'{"articles":[{"url":"https://publisher.invalid/","title":NaN}]}', "archive_json_invalid"),
    (b'\xff', "archive_json_invalid"), (b'{', "archive_json_invalid"),
    (b'{}', "archive_listing_invalid"), (b'[]', "archive_listing_invalid"),
    (gdelt([None]), "archive_listing_invalid"), (gdelt([{"url": "javascript:alert(1)"}]), "archive_url_invalid"),
    (gdelt([{"url": "https://name:password@publisher.invalid/a"}]), "archive_url_invalid"),
    (gdelt([{"url": "https://publisher.invalid/a", "title": 7}]), "archive_listing_invalid"),
    (gdelt([{"url": "https://publisher.invalid/a", "seendate": "2026-07-25"}]), "archive_seen_date_invalid"),
    (gdelt([{"url": "https://publisher.invalid/a", "seendate": "20260230T000000Z"}]), "archive_seen_date_invalid"),
])
def test_invalid_gdelt_input_is_bounded_and_stable(raw, code):
    failed(code, listing, raw, "gdelt-doc")


@pytest.mark.parametrize("raw", [b"", "not bytes", None])
def test_invalid_raw_input(raw):
    failed("archive_input_invalid", listing, raw)


def test_raw_size_limit(monkeypatch):
    monkeypatch.setattr(archives, "MAX_RAW", 5)
    failed("archive_input_invalid", listing, b"123456")


@pytest.mark.parametrize("published", [
    "2026-07-25", "2026-07-25T22:08", "2026-07-25T22:08:09", "2026-07-25T22:08:09+09:00",
    "2026-07-25T13:08:09Z", "2026-07-25T22:08:09.123456789+09:00",
])
def test_publication_preserves_original_precision_and_timezone(published):
    meta = article_metadata("hankyung-daily", og(published=published), HK)
    assert meta.published_at == published and meta.article_xpath == "//div[@id='articletxt']"
    assert meta.publisher is None and meta.canonical_url is None and meta.source_kind == "editorial"


def test_absent_publication_remains_unknown_despite_modified_or_url_date():
    meta = article_metadata("hankyung-daily", og(extra='<meta property="article:modified_time" content="2026-07-25T10:00:00Z">'), HK)
    assert meta.published_at is None


@pytest.mark.parametrize("published", ["2026-02-30", "July 25, 2026", "2026-07-25T25:00:00Z", "2026-07-25T10:00:00+25:00", "20260725"])
def test_invalid_present_publication_never_silently_becomes_unknown(published):
    failed("article_date_invalid", article_metadata, "hankyung-daily", og(published=published), HK)


def test_date_and_title_conflicts_are_explicit():
    data = {"@type": "NewsArticle", "headline": "Synthetic headline", "datePublished": "2026-07-26"}
    failed("article_date_conflict", article_metadata, "hankyung-daily", og(published=DAY, extra=schema(data)), HK)
    failed("article_title_conflict", article_metadata, "hankyung-daily", og(extra='<meta property="og:title" content="Different headline">'), HK)
    # Lower-precision same-day declarations stay day precision, never inferred midnight.
    meta = article_metadata("hankyung-daily", og(published=DAY, extra='<meta property="article:published_time" content="2026-07-25T00:00:00Z">'), HK)
    assert meta.published_at == DAY


def test_equivalent_aware_timestamps_preserve_verified_og_spelling():
    chosen = "2026-07-25T22:08:09.123456789+09:00"
    data = {"@type": "NewsArticle", "headline": "Alternate schema headline", "datePublished": "2026-07-25T13:08:09.123456789Z"}
    meta = article_metadata("hankyung-daily", og(published=chosen, extra=schema(data)), HK)
    assert meta.published_at == chosen and meta.title == "Synthetic headline"
    data["datePublished"] = "2026-07-25T13:08:09.123456788Z"
    failed("article_date_conflict", article_metadata, "hankyung-daily", og(published=chosen, extra=schema(data)), HK)
    crossed = article_metadata("hankyung-daily", og(published="2026-07-25T01:00:00+09:00", extra=schema({"@type": "NewsArticle", "datePublished": "2026-07-24T16:00:00Z"})), HK)
    assert crossed.published_at == "2026-07-25T01:00:00+09:00"


def test_relative_canonical_preserves_encoded_identity_and_is_not_implicitly_fetched():
    raw = og(extra='<link rel="alternate canonical" href="../a%2Fb?q=%2F%26&amp;edition=+#section">')
    meta = article_metadata("gdelt-doc", raw, "https://publisher.invalid/news/example")
    assert meta.canonical_url == "https://publisher.invalid/a%2Fb?q=%2F%26&edition=+"
    assert meta.article_xpath is None and meta.source_kind == "unknown"
    foreign = article_metadata("hankyung-daily", og(extra='<link rel="canonical" href="https://other.invalid/a">'), HK)
    assert foreign.canonical_url == "https://other.invalid/a" and foreign.article_xpath == "//div[@id='articletxt']"


@pytest.mark.parametrize(("extra", "code"), [
    ('<link rel="canonical" href="/a"><link rel="canonical" href="/b">', "article_canonical_conflict"),
    ('<link rel="canonical" href="javascript:alert(1)">', "article_canonical_invalid"),
    ('<link rel="canonical" href="https://name:password@other.invalid/a">', "article_canonical_invalid"),
    ('<link rel="canonical" href=" /a">', "article_canonical_invalid"),
    ('<link rel="canonical" href="&#10;https://other.invalid/a">', "article_canonical_invalid"),
])
def test_invalid_or_conflicting_canonicals(extra, code):
    failed(code, article_metadata, "hankyung-daily", og(extra=extra), HK)


@pytest.mark.parametrize("body", ['<article>Wrong element</article>', '<p id="articletxt">Wrong tag</p>', '<div id="articletxt">One</div><div id="articletxt">Two</div>', '<div id="articletxt">One</div><p id="articletxt">Duplicate ID</p>'])
def test_hankyung_scope_is_exact_and_unique(body):
    failed("article_scope_ambiguous_or_missing", article_metadata, "hankyung-daily", og(body=body), HK)


def test_exact_hankyung_scope_excludes_outer_article_noise():
    raw = og(body='<article><p>OUTSIDE SCOPE</p><div id="articletxt"><p>Authored synthetic body.</p></div><p>OTHER OUTSIDE</p></article>')
    meta = article_metadata("hankyung-daily", raw, HK)
    prepared = prepare(raw, "text/html", meta.article_xpath)
    assert "Authored synthetic body." in prepared["text"]
    assert "OUTSIDE" not in prepared["text"]


def test_generic_jsonld_graph_is_metadata_only_and_not_editorial_proof():
    data = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": "Not the article"},
        {"@type": ["Thing", "https://schema.org/NewsArticle"], "headline": "Authored title", "datePublished": DAY,
         "publisher": {"@type": "Organization", "name": "Synthetic Publisher"}},
    ]}
    meta = article_metadata("gdelt-doc", document(schema(data)), "https://publisher.invalid/a")
    assert meta == ArticleMeta("Authored title", DAY, None, None, "Synthetic Publisher", "unknown")
    failed("article_scope_ambiguous_or_missing", prepare, document(schema(data), '<div>Not a semantic article.</div>'), "text/html", meta.article_xpath)


@pytest.mark.parametrize("marker", [{"genre": "press release"}, {"genre": ["보도자료"]}, {"@type": "PressRelease"}])
def test_explicit_press_release_not_mislabeled_editorial(marker):
    data = {"@type": "NewsArticle", "headline": "Synthetic headline"} | marker
    raw = og(extra=schema(data))
    assert article_metadata("gdelt-doc", raw, "https://publisher.invalid/a").source_kind == "corporate-pr"
    assert article_metadata("hankyung-daily", raw, HK).source_kind == "corporate-pr"


def test_multiple_jsonld_articles_and_malformed_metadata_are_not_guessed():
    data = [{"@type": "NewsArticle", "headline": "A"}, {"@type": "NewsArticle", "headline": "B"}]
    failed("article_metadata_ambiguous", article_metadata, "gdelt-doc", document(schema(data)), "https://publisher.invalid/a")
    failed("archive_json_invalid", article_metadata, "gdelt-doc", og(extra='<script type="application/ld+json">{</script>'), "https://publisher.invalid/a")
    failed("article_title_missing", article_metadata, "gdelt-doc", document(body='<article><h1>Not a metadata title</h1></article>'), "https://publisher.invalid/a")
    failed("article_html_invalid", article_metadata, "gdelt-doc", b'\xff', "https://publisher.invalid/a")
    failed("article_publisher_conflict", article_metadata, "gdelt-doc", og(extra='<meta property="og:site_name" content="A"><meta property="og:site_name" content="B">'), "https://publisher.invalid/a")
    branded = article_metadata("gdelt-doc", og(extra='<meta property="og:site_name" content="Brand">' + schema({"@type": "NewsArticle", "publisher": {"name": "Legal Publisher"}})), "https://publisher.invalid/a")
    assert branded.publisher == "Legal Publisher"


def test_paywall_markers_are_not_bypassed_by_metadata_scope():
    raw = og(body='<div class="paywall"><div id="articletxt">Not authorized by metadata.</div></div>')
    meta = article_metadata("hankyung-daily", raw, HK)
    failed("access_restricted", prepare, raw, "text/html", meta.article_xpath)


def test_shared_value_types_are_frozen():
    result = listing(xml())
    with pytest.raises(FrozenInstanceError):
        result.saturated = True
    with pytest.raises(FrozenInstanceError):
        result.candidates[0].published_at = DAY
    with pytest.raises(FrozenInstanceError):
        task().kind = "changed"


@pytest.mark.parametrize("source", ["hankyung-daily", "gdelt-doc"])
def test_explicit_synthetic_origin_keeps_actual_urls_and_does_not_relax_defaults(source):
    selected = task(source, synthetic_origin=LOOP)
    assert selected.url.startswith(LOOP + "/")
    assert source_hosts(source, synthetic_origin=LOOP) == ("127.0.0.1",)
    assert validate_discovery_url(source, selected.url, synthetic_origin=LOOP) == selected.url
    raw = xml((LOOP + "/article/synthetic1",)) if source == "hankyung-daily" else gdelt([{"url": LOOP + "/article/synthetic1"}])
    parsed = parse_listing(source, selected, raw, selected.url, synthetic_origin=LOOP)
    candidate = parsed.candidates[0]
    assert candidate.url == LOOP + "/article/synthetic1"
    meta = article_metadata(source, og(published=DAY), candidate.url, synthetic_origin=LOOP)
    assert meta.published_at == DAY
    failed("archive_endpoint_invalid", validate_discovery_url, source, selected.url)
    failed("archive_endpoint_invalid", validate_discovery_url, source, selected.url.replace(":18765", ":18766"), synthetic_origin=LOOP)
    failed("archive_article_host_invalid", article_metadata, source, og(), "https://other.invalid/article/synthetic1", synthetic_origin=LOOP)


@pytest.mark.parametrize("origin", [
    "http://localhost:18765", "http://127.0.0.2:18765", "http://127.0.0.1", "https://127.0.0.1:18765",
    LOOP + "/", LOOP + "?x=1", LOOP + "#f", "http://user:password@127.0.0.1:18765",
    "http://127.0.0.1:0", "http://127.0.0.1:65536", 7,
])
def test_synthetic_origin_is_explicit_numeric_and_exact(origin):
    failed("archive_synthetic_origin_invalid", source_hosts, "hankyung-daily", synthetic_origin=origin)


CORPORATE = [
    ("nvidia-newsroom", "https://nvidianews.nvidia.com/news/synthetic-release"),
    ("amd-newsroom", "https://newsroom.amd.com/news/synthetic-release/"),
    ("naver-press", "https://www.navercorp.com/en/media/pressReleasesDetail?seq=10034607"),
    ("apple-newsroom", "https://www.apple.com/newsroom/2026/08/synthetic-release/"),
]


def rss(url, *, published="Tue, 04 Aug 2026 20:17:01 GMT"):
    return (f'<rss version="2.0"><channel><item><link>{escape(url)}</link><title>Synthetic corporate release</title>'
            f'<pubDate>{published}</pubDate></item></channel></rss>').encode()


def atom(url):
    return (f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Synthetic corporate release</title>'
            f'<link rel="alternate" type="text/html" href="{escape(url)}"/>'
            '<link rel="enclosure" type="image/jpeg" href="https://www.apple.com/newsroom/images/synthetic.jpg"/>'
            '<updated>2026-10-23T06:10:35.677Z</updated></entry></feed>').encode()


def corporate_og(source, *, published="2026-08-04T20:17:01.728Z", extra=""):
    text = "<p>Authored synthetic corporate paragraph.</p>"
    if source == "amd-newsroom":
        body = f'<article><div class="article-body"><div class="content-body">{text}</div><p>RELATED OUTSIDE</p></div></article><aside><div class="content-body">ASIDE OUTSIDE</div></aside>'
    else:
        header = ""
        if published is not None:
            year, month, day = published[:10].split("-")
            english = f'{("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")[int(month)-1]} {int(day)}, {year}'
            if source == "naver-press":
                header = f'<div class="date media-detail__date">{year}.{month}.{day}</div>'
            elif source == "nvidia-newsroom":
                header = f'<div class="article-date">{english}</div>'
            else:
                header = f'<span class="category-eyebrow__date">{english}</span>'
        if source == "naver-press":
            body = header + f'<div class="board-view-detail">{text}</div>'
        elif source == "nvidia-newsroom":
            body = header + f'<div class="article-body">{text}</div>'
        else:
            body = f'<main><article class="article">{header}{text}</article></main>'
    return og(published=published, extra=extra, body=body)


def naver_search(content, *, outside=""):
    return document(body=outside + '<div class="media-press__wrap is-search"><ul>' + content + '</ul></div>')


@pytest.mark.parametrize(("source", "article"), CORPORATE)
def test_corporate_source_types_and_exact_article_host_boundaries(source, article):
    meta = article_metadata(source, corporate_og(source), article)
    expected = {"nvidia-newsroom": "August 4, 2026", "amd-newsroom": "2026-08-04T20:17:01.728Z",
                "naver-press": "2026.08.04", "apple-newsroom": "August 4, 2026"}
    assert meta.source_kind == "corporate-pr" and meta.published_at == expected[source]
    failed("archive_article_host_invalid", article_metadata, source, og(), article.replace(urlsplit(article).netloc, "attacker.invalid"))
    failed("archive_query_invalid", initial_tasks, source, DAY, "2026-10-25", ("NVIDIA",))


@pytest.mark.parametrize(("source", "article"), [entry for entry in CORPORATE if entry[0] != "naver-press"])
def test_corporate_sitemap_and_latest_feed_are_separate_fixed_tasks(source, article):
    selected = initial_tasks(source, DAY, "2026-10-25")
    assert [item.kind for item in selected] == ["sitemap-xml", "rss-xml"]
    assert all(item.from_day == DAY and item.through_day == "2026-10-25" for item in selected)
    for item in selected:
        assert validate_discovery_url(source, item.url) == item.url
    sitemap_result = parse_listing(source, selected[0], xml((article, article)), selected[0].url)
    assert len(sitemap_result.candidates) == 1 and not sitemap_result.saturated
    assert sitemap_result.candidates[0].published_at is None and sitemap_result.candidates[0].discovery_seen_at is None
    expected_hint = "2026-08" if source == "apple-newsroom" else "2026-10-25"
    assert sitemap_result.candidates[0].archive_day == expected_hint
    latest = parse_listing(source, selected[1], atom(article) if source == "apple-newsroom" else rss(article), selected[1].url)
    assert latest.saturated and latest.next_tasks == ()
    hint = "2026-08" if source == "apple-newsroom" else "2026-08-04"
    assert latest.candidates[0] == Candidate(article, "Synthetic corporate release", None, None, hint)
    failed("archive_task_invalid", parse_listing, source, selected[0], xml((article,)), selected[1].url)


@pytest.mark.parametrize(("source", "article"), [entry for entry in CORPORATE if entry[0] != "naver-press"])
def test_corporate_sitemaps_prune_only_verified_nonarticle_routes_and_refuse_foreign_hosts(source, article):
    selected = initial_tasks(source, DAY, "2026-10-25")[0]
    origin = urlsplit(article).scheme + "://" + urlsplit(article).netloc
    parsed = parse_listing(source, selected, xml((origin + "/contact", article)), selected.url)
    assert [item.url for item in parsed.candidates] == [article]
    failed("archive_article_host_invalid", parse_listing, source, selected, xml(("https://attacker.invalid/news/item",)), selected.url)


def test_apple_url_month_is_only_discovery_hint_and_pruning_is_month_precision():
    selected = initial_tasks("apple-newsroom", DAY, "2026-10-25")[0]
    urls = tuple(f"https://www.apple.com/newsroom/2026/{month}/synthetic-release/" for month in ("06", "07", "08", "10", "11"))
    result = parse_listing("apple-newsroom", selected, xml(urls), selected.url)
    assert [candidate.archive_day for candidate in result.candidates] == ["2026-07", "2026-08", "2026-10"]
    assert all(candidate.published_at is None for candidate in result.candidates)
    # A July discovery path cannot override conflicting actual body publication metadata.
    meta = article_metadata("apple-newsroom", corporate_og("apple-newsroom", published="2026-06-30T20:00:00Z"), urls[1])
    assert meta.published_at == "June 30, 2026"


def test_sitemap_lastmod_is_a_hint_even_when_unknown_or_later_than_publication():
    selected = initial_tasks("amd-newsroom", DAY, "2026-10-25")[0]
    article = "https://newsroom.amd.com/news/synthetic-release/"
    invalid = xml((article,)).replace(b"2026-10-25T10:05:00+09:00", b"not-a-date")
    parsed = parse_listing("amd-newsroom", selected, invalid, selected.url)
    assert parsed.candidates[0].archive_day is None
    assert parsed.candidates[0].published_at is None
    meta = article_metadata("amd-newsroom", corporate_og("amd-newsroom"), article)
    assert meta.published_at == "2026-08-04T20:17:01.728Z"


def test_naver_month_tasks_cover_partial_boundary_months_without_guessing_pages():
    tasks = initial_tasks("naver-press", DAY, "2026-10-25")
    assert [(item.from_day, item.through_day) for item in tasks] == [
        ("2026-07-25", "2026-07-31"), ("2026-08-01", "2026-08-31"),
        ("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-25"),
    ]
    assert all(item.kind == "archive-html" for item in tasks)
    assert tasks[1].url == "https://www.navercorp.com/en/media/pressReleases?keyword=&year=2026&month=8"
    for selected in tasks:
        assert validate_discovery_url("naver-press", selected.url) == selected.url
    selected = tasks[1]
    raw = naver_search('<li><a href="pressReleasesDetail?seq=10034607" title="Explicit listing title">Teaser is not a title</a><a href="/en/media/pressReleasesDetail?seq=10034607">Duplicate</a><span class="news-date">2026.08.20</span></li>',
                       outside='<a href="/en/media/pressReleasesDetail?seq=10034725">Unrelated featured release</a><span class="date">2026.09.30</span>')
    result = parse_listing("naver-press", selected, raw, selected.url)
    assert result == Listing((Candidate("https://www.navercorp.com/en/media/pressReleasesDetail?seq=10034607", "Explicit listing title", None, None, "2026-08-20"),), (), True)
    empty = parse_listing("naver-press", selected, naver_search(""), selected.url)
    assert empty == Listing((), (), True)
    failed("archive_task_invalid", parse_listing, "naver-press", selected, raw, tasks[2].url)


@pytest.mark.parametrize(("source", "url"), [
    ("nvidia-newsroom", "https://nvidianews.nvidia.com/news?page=8&year=2026"),
    ("amd-newsroom", "https://newsroom.amd.com/rss.xml?content-type=news&page=2"),
    ("amd-newsroom", "https://newsroom.amd.com/sitemap.xml?unverified=1"),
    ("amd-newsroom", "https://newsroom.amd.com/all-news/?page=4"),
    ("apple-newsroom", "https://www.apple.com/newsroom/archive/"),
    ("naver-press", "https://www.navercorp.com/en/media/pressReleases?keyword=&year=2026&month=8&page=2"),
    ("naver-press", "https://www.navercorp.com/en/media/pressReleases?keyword=Samsung&year=2026&month=8"),
    ("naver-press", "https://www.navercorp.com/en/media/pressReleases?keyword=&year=2026&month=13"),
])
def test_no_unverified_corporate_pagination_routes(source, url):
    failed("archive_endpoint_invalid", validate_discovery_url, source, url)


def test_corporate_rss_and_sitemap_security_share_xml_guards(monkeypatch):
    selected = initial_tasks("nvidia-newsroom", DAY, "2026-10-25")
    failed("archive_xml_unsafe", parse_listing, "nvidia-newsroom", selected[1], b'<!DOCTYPE rss SYSTEM "file:///private"><rss version="2.0"><channel/></rss>', selected[1].url)
    failed("archive_xml_invalid", parse_listing, "nvidia-newsroom", selected[1], b'<rss version="2.0"><channel/><channel/></rss>', selected[1].url)
    failed("archive_xml_invalid", parse_listing, "nvidia-newsroom", selected[0], b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>', selected[0].url)
    latest = parse_listing("nvidia-newsroom", selected[1], rss("https://nvidianews.nvidia.com/news/synthetic-release", published="unknown"), selected[1].url)
    assert latest.candidates[0].archive_day is None and latest.saturated
    monkeypatch.setattr(archives, "MAX_SITEMAP_URLS", 1)
    assert parse_listing("nvidia-newsroom", selected[0], xml(("https://nvidianews.nvidia.com/news/synthetic-release",)), selected[0].url).saturated


def test_naver_detail_href_cannot_escape_host_or_hide_controls():
    selected = initial_tasks("naver-press", "2026-08-01", "2026-08-31")[0]
    failed("archive_article_host_invalid", parse_listing, "naver-press", selected, naver_search('<li><a href="https://attacker.invalid/en/media/pressReleasesDetail?seq=1">Foreign</a></li>'), selected.url)
    failed("archive_url_invalid", parse_listing, "naver-press", selected, naver_search('<li><a href="&#10;/en/media/pressReleasesDetail?seq=1">Hidden control</a></li>'), selected.url)


@pytest.mark.parametrize(("source", "article"), CORPORATE)
def test_corporate_synthetic_mode_is_explicit_and_preserves_actual_origin(source, article):
    tasks = initial_tasks(source, DAY, "2026-10-25", synthetic_origin=LOOP)
    for selected in tasks:
        assert selected.url.startswith(LOOP + "/")
        assert validate_discovery_url(source, selected.url, synthetic_origin=LOOP) == selected.url
        failed("archive_endpoint_invalid", validate_discovery_url, source, selected.url)
    parts = urlsplit(article)
    synthetic_article = LOOP + parts.path + ("?" + parts.query if parts.query else "")
    assert article_metadata(source, corporate_og(source, published=DAY), synthetic_article, synthetic_origin=LOOP).source_kind == "corporate-pr"


@pytest.mark.parametrize(("source", "article"), CORPORATE)
def test_proven_corporate_scope_extracts_only_authored_fixture_body(source, article):
    raw = corporate_og(source).replace(b"</body>", b"<aside>UNRELATED OUTSIDE FOOTER</aside></body>")
    meta = article_metadata(source, raw, article)
    assert meta.article_xpath is not None
    prepared = prepare(raw, "text/html", meta.article_xpath)
    assert "Authored synthetic corporate paragraph." in prepared["text"]
    assert "OUTSIDE" not in prepared["text"]


@pytest.mark.parametrize(("source", "article", "duplicate"), [
    ("nvidia-newsroom", CORPORATE[0][1], '<div class="article-body">Ambiguous second body</div>'),
    ("amd-newsroom", CORPORATE[1][1], '<article><div class="article-body"><div class="content-body">Ambiguous second body</div></div></article>'),
    ("naver-press", CORPORATE[2][1], '<div class="board-view-detail">Ambiguous second body</div>'),
    ("apple-newsroom", CORPORATE[3][1], '<main><article class="article">Ambiguous second body</article></main>'),
])
def test_proven_corporate_scope_must_still_be_unique_per_response(source, article, duplicate):
    raw = corporate_og(source).replace(b"</body>", duplicate.encode() + b"</body>")
    failed("article_scope_ambiguous_or_missing", article_metadata, source, raw, article)


@pytest.mark.parametrize(("source", "article"), [entry for entry in CORPORATE if entry[0] != "amd-newsroom"])
def test_source_visible_publication_has_proven_precedence_and_missing_is_unknown(source, article):
    extra = ('<meta property="article:modified_time" content="2026-10-25T10:00:00Z">'
             '<meta property="article:published_time" content="2025-01-01T10:00:00Z">'
             + schema({"@type": "NewsArticle", "datePublished": "2026-08-27Z", "dateModified": "2026-10-25T10:00:00Z"}))
    meta = article_metadata(source, corporate_og(source, extra=extra), article)
    assert meta.published_at == ("2026.08.04" if source == "naver-press" else "August 4, 2026")
    unknown = article_metadata(source, corporate_og(source, published=None, extra=extra), article)
    assert unknown.published_at is None


@pytest.mark.parametrize(("source", "article", "before", "after"), [
    ("naver-press", CORPORATE[2][1], "2026.08.04", "2026.02.30"),
    ("nvidia-newsroom", CORPORATE[0][1], "August 4, 2026", "February 30, 2026"),
    ("nvidia-newsroom", CORPORATE[0][1], "August 4, 2026", "Aug 4, 2026"),
    ("apple-newsroom", CORPORATE[3][1], "August 4, 2026", "August 04, 2026"),
])
def test_source_visible_publication_is_closed_calendar_metadata(source, article, before, after):
    raw = corporate_og(source).replace(before.encode(), after.encode())
    failed("article_date_invalid", article_metadata, source, raw, article)


def test_visible_date_ignores_related_card_dates_and_refuses_multiple_publication_headers():
    article = CORPORATE[0][1]
    raw = corporate_og("nvidia-newsroom").replace(b"</body>", b'<div class="index-item-text-info-date">January 1, 2020</div></body>')
    assert article_metadata("nvidia-newsroom", raw, article).published_at == "August 4, 2026"
    duplicate = raw.replace(b"</body>", b'<div class="article-date">August 5, 2026</div></body>')
    failed("article_date_conflict", article_metadata, "nvidia-newsroom", duplicate, article)
    failed("article_date_invalid", article_metadata, "gdelt-doc", og(published="2026-08-27Z"), "https://publisher.invalid/a")


def test_apple_atom_never_retains_images_or_calls_updated_publication():
    selected = initial_tasks("apple-newsroom", DAY, "2026-10-25")[1]
    article = CORPORATE[3][1]
    parsed = parse_listing("apple-newsroom", selected, atom(article), selected.url)
    assert parsed == Listing((Candidate(article, "Synthetic corporate release", None, None, "2026-08"),), (), True)
    duplicate = atom(article).replace(b"</entry>", f'<link rel="alternate" type="text/html" href="{article}"/></entry>'.encode())
    failed("archive_xml_invalid", parse_listing, "apple-newsroom", selected, duplicate, selected.url)
    only_image = atom(article).replace(b'type="text/html"', b'type="image/jpeg"')
    failed("archive_xml_invalid", parse_listing, "apple-newsroom", selected, only_image, selected.url)


@pytest.mark.parametrize("declaration", [b"", b'rel="alternate" '])
def test_apple_atom_optional_html_type_still_requires_one_exact_article_alternate(declaration):
    selected = initial_tasks("apple-newsroom", DAY, "2026-10-25")[1]
    article = CORPORATE[3][1]
    raw = atom(article).replace(b'rel="alternate" type="text/html" ', declaration)
    raw = raw.replace(b"</entry>", (
        '<link rel="alternate" href="https://www.apple.com/support/"/>'
        '<link rel="alternate" type="application/pdf" href="https://www.apple.com/newsroom/2026/08/not-html/"/>'
        '</entry>').encode())
    parsed = parse_listing("apple-newsroom", selected, raw, selected.url)
    assert parsed == Listing((Candidate(article, "Synthetic corporate release", None, None, "2026-08"),), (), True)
    duplicate = raw.replace(b"</entry>", f'<link href="{article}"/></entry>'.encode())
    failed("archive_xml_invalid", parse_listing, "apple-newsroom", selected, duplicate, selected.url)
    foreign = raw.replace(article.encode(), b"https://attacker.invalid/newsroom/2026/08/synthetic-release/")
    failed("archive_article_host_invalid", parse_listing, "apple-newsroom", selected, foreign, selected.url)


def test_naver_missing_or_ambiguous_search_scope_is_not_empty_month_coverage():
    selected = initial_tasks("naver-press", "2026-08-01", "2026-08-31")[0]
    failed("archive_listing_ambiguous", parse_listing, "naver-press", selected, document(), selected.url)
    duplicate = naver_search("").replace(b"</body>", b'<div class="media-press__wrap is-search"></div></body>')
    failed("archive_listing_ambiguous", parse_listing, "naver-press", selected, duplicate, selected.url)


ET = "https://www.etnews.com/20260831000357"
FN = "https://www.fnnews.com/news/202608101455399495"
FN_ORIGIN = "https://www.fnnews.com"
FN_PART = "/resource/view_xml/sitemap_v3/sitemap-"


def et_listing(*, date="2026-08-31 18:28", pagination="", outside="", article=ET):
    return document(body=f'{outside}<main><ul class="extra news_list "><li>'
                         f'<figure><a href="{article}"><img alt="Thumbnail is not the title"></a></figure>'
                         f'<div><strong><a href="{article}">합성 인공지능 기사</a></strong>'
                         f'<span class="date">{date}</span></div></li></ul>{pagination}</main>')


def fn_index(tokens=("202607-1", "202608-1", "202608-2", "202610-3"), *, origin=FN_ORIGIN):
    entries = "".join(f"<sitemap><loc>{origin}{FN_PART}{token}.xml</loc></sitemap>" for token in tokens)
    return f'<sitemapindex xmlns="{archives.SITEMAP_NS}">{entries}</sitemapindex>'.encode()


def fn_partition(*, queries=("202608-1",), origin=None):
    kwargs = {"synthetic_origin": origin} if origin else {}
    selected = initial_tasks("fnnews-sitemaps", DAY, "2026-10-25", queries, **kwargs)[0]
    result = parse_listing("fnnews-sitemaps", selected, fn_index(origin=origin or FN_ORIGIN), selected.url, **kwargs)
    return result.next_tasks[0]


def editorial_og(source, *, published="2026-08-17T15:20:49+09:00", extra=""):
    text = "<p>합성 한국어 본문입니다. 실제 기사나 인용문이 아닙니다.</p>"
    if source == "etnews-ai":
        body = f'<main><article><p>OUTSIDE HEADER</p><div id="articleBody">{text}</div></article></main>'
    else:
        body = f'<article class="extra article-view"><p>OUTSIDE HEADER</p><div class="article-view__body extra">{text}</div></article>'
    return og(published=published, title="합성 한국어 제목", extra=extra, body=body + "<aside>OUTSIDE FOOTER</aside>")


def test_et_listing_deduplicates_thumbnail_title_and_isolates_main_list_scope():
    selected = initial_tasks("etnews-ai", DAY, "2026-10-25")[0]
    outside = '<ul class="news_list"><li><a href="https://www.etnews.com/20260101000001">OUTSIDE</a></li></ul>'
    pagination = ('<a href="?id=2958&amp;page=2">2</a>'
                  '<a href="?id=2958&amp;page=3">3</a><a href="?id=2958&amp;page=2">Next duplicate</a>'
                  '<a href="?id=9999&amp;page=2">Other category</a>'
                  '<a href="https://attacker.invalid/news/category_list.html?id=2958&amp;page=2">Foreign</a>')
    result = parse_listing("etnews-ai", selected, et_listing(outside=outside, pagination=pagination), selected.url)
    assert result.candidates == (Candidate(ET, "합성 인공지능 기사", None, None, "2026-08-31"),)
    assert len(result.next_tasks) == 1 and not result.saturated
    following = result.next_tasks[0]
    assert following.url == "https://www.etnews.com/news/category_list.html?id=2958&page=2"
    assert following.from_day == DAY and following.through_day == "2026-10-25"
    old = parse_listing("etnews-ai", following, et_listing(date="2026-07-19 09:10", pagination='<a href="?id=2958&amp;page=3">Next</a>'), following.url)
    assert old.candidates[0].archive_day == "2026-07-19"
    assert len(old.next_tasks) == 1  # Display dates cannot establish a publication-window stop.
    terminal = parse_listing("etnews-ai", old.next_tasks[0], et_listing(), old.next_tasks[0].url)
    assert terminal.saturated and terminal.next_tasks == ()


@pytest.mark.parametrize("query", [
    "id=9999&page=2", "id=2958&page=2&search=AI", "id=2958&page=2&id=2958",
    "id=2958&page=0", "id=2958&page=-1", "id=2958&page=02", "id=2958&page=2#f",
])
def test_et_category_route_has_no_foreign_or_duplicate_query_semantics(query):
    failed("archive_endpoint_invalid", validate_discovery_url, "etnews-ai",
           "https://www.etnews.com/news/category_list.html?" + query)


def test_et_missing_duplicate_scope_and_unobserved_page_are_not_valid_coverage():
    selected = initial_tasks("etnews-ai", DAY, "2026-10-25")[0]
    failed("archive_listing_ambiguous", parse_listing, "etnews-ai", selected, document(), selected.url)
    duplicate = et_listing().replace(b"</main>", b'<ul class="news_list"></ul></main>')
    failed("archive_listing_ambiguous", parse_listing, "etnews-ai", selected, duplicate, selected.url)
    failed("archive_task_invalid", parse_listing, "etnews-ai", selected, et_listing(), selected.url.replace("page=1", "page=2"))
    failed("archive_task_invalid", parse_listing, "etnews-ai", replace(selected, key="forged"), et_listing(), selected.url)
    failed("archive_query_invalid", initial_tasks, "etnews-ai", DAY, DAY, ("202608-1",))
    no_adjacent = parse_listing("etnews-ai", selected, et_listing(pagination='<a href="?id=2958&amp;page=11">11</a>'), selected.url)
    assert no_adjacent.next_tasks == () and no_adjacent.saturated


def test_fn_annual_index_selects_only_advertised_requested_month_partitions():
    selected = initial_tasks("fnnews-sitemaps", DAY, "2026-10-25")[0]
    assert selected.url == FN_ORIGIN + "/resource/view_xml/sitemap_index/news-sitemap-index-2026.xml"
    result = parse_listing("fnnews-sitemaps", selected, fn_index(("202606-1", "202607-1", "202608-2", "202610-3", "202611-1")), selected.url)
    assert result.candidates == () and not result.saturated
    assert [item.url for item in result.next_tasks] == [
        FN_ORIGIN + FN_PART + token + ".xml" for token in ("202607-1", "202608-2", "202610-3")]
    assert [(item.from_day, item.through_day) for item in result.next_tasks] == [
        (DAY, "2026-07-31"), ("2026-08-01", "2026-08-31"), ("2026-10-01", "2026-10-25")]


def test_fn_exact_partition_filters_are_bound_deterministically_and_must_be_advertised():
    tasks = initial_tasks("fnnews-sitemaps", DAY, "2026-10-25", ("202608-2", "202608-1", "202608-2"))
    assert tasks == initial_tasks("fnnews-sitemaps", DAY, "2026-10-25", ("202608-1", "202608-2"))
    selected = tasks[0]
    parsed = parse_listing("fnnews-sitemaps", selected, fn_index(), selected.url)
    assert [item.url for item in parsed.next_tasks] == [FN_ORIGIN + FN_PART + token + ".xml" for token in ("202608-1", "202608-2")]
    absent = initial_tasks("fnnews-sitemaps", DAY, "2026-10-25", ("202609-9",))[0]
    failed("archive_partition_unadvertised", parse_listing, "fnnews-sitemaps", absent, fn_index(), absent.url)
    failed("archive_task_invalid", parse_listing, "fnnews-sitemaps", replace(selected, kind="fnnews-index"), fn_index(), selected.url)
    failed("archive_task_invalid", parse_listing, "fnnews-sitemaps", selected, fn_index(), selected.url.replace("2026.xml", "2025.xml"))
    years = initial_tasks("fnnews-sitemaps", "2025-12-25", "2026-01-25", ("202512-2", "202601-1"))
    assert len(years) == 2
    assert years[0].through_day == "2025-12-31" and years[1].from_day == "2026-01-01"
    assert "202512-2" in years[0].kind and "202601-1" not in years[0].kind


@pytest.mark.parametrize("token", [
    "202608-0", "202608-01", "202613-1", "000008-1", "202608", "202608-1 ",
    "202608-1,202608-2", "202606-1", "https://www.fnnews.com/resource/view_xml/sitemap_v3/sitemap-202608-1.xml",
])
def test_fn_partition_queries_are_exact_tokens_in_requested_months(token):
    failed("archive_query_invalid", initial_tasks, "fnnews-sitemaps", DAY, "2026-10-25", (token,))


@pytest.mark.parametrize("url", [
    "https://fnnews.com/resource/view_xml/sitemap_v3/sitemap-202608-1.xml",
    "https://www.fnnews.com.attacker.invalid/resource/view_xml/sitemap_v3/sitemap-202608-1.xml",
    "http://www.fnnews.com/resource/view_xml/sitemap_v3/sitemap-202608-1.xml",
    FN_ORIGIN + FN_PART + "202608-1.xml?next=elsewhere",
    FN_ORIGIN + FN_PART + "202608-1.xml#f",
    FN_ORIGIN + "/resource/view_xml/sitemap_v2/sitemap-202608-1.xml",
    FN_ORIGIN + FN_PART + "202613-1.xml",
    FN_ORIGIN + "/resource/view_xml/sitemap_index/news-sitemap-index-0000.xml",
])
def test_fn_discovery_host_routes_and_partitions_are_exact(url):
    failed("archive_endpoint_invalid", validate_discovery_url, "fnnews-sitemaps", url)


def test_fn_lastmod_and_url_day_never_become_publication_or_clamped_window_hints():
    selected = fn_partition()
    raw = xml((FN, FN))
    parsed = parse_listing("fnnews-sitemaps", selected, raw, selected.url)
    assert parsed.candidates == (Candidate(FN, None, None, None, "2026-10-25"),)
    outside = raw.replace(b"2026-10-25T10:05:00+09:00", b"2026-11-01T10:05:00+09:00")
    assert parse_listing("fnnews-sitemaps", selected, outside, selected.url).candidates[0].archive_day == "2026-11-01"
    unknown = raw.replace(b"2026-10-25T10:05:00+09:00", b"unknown")
    assert parse_listing("fnnews-sitemaps", selected, unknown, selected.url).candidates[0].archive_day == "2026-08-10"
    # Actual publication is Aug 17 despite the URL's Aug 10 and unrelated sitemap lastmod.
    meta = article_metadata("fnnews-sitemaps", editorial_og("fnnews-sitemaps"), FN)
    assert meta.published_at == "2026-08-17T15:20:49+09:00"


def test_fn_secure_xml_index_and_partition_limits_and_raw_byte_ceiling(monkeypatch):
    index = initial_tasks("fnnews-sitemaps", DAY, "2026-10-25")[0]
    partition = fn_partition()
    for selected in (index, partition):
        failed("archive_xml_unsafe", parse_listing, "fnnews-sitemaps", selected,
               b'<!DOCTYPE urlset [<!ENTITY x SYSTEM "file:///private">]><urlset/>', selected.url)
        failed("archive_xml_invalid", parse_listing, "fnnews-sitemaps", selected, b"<broken>", selected.url)
    failed("archive_xml_invalid", parse_listing, "fnnews-sitemaps", index, xml((FN,)), index.url)
    foreign = fn_index().replace(b"www.fnnews.com", b"attacker.invalid")
    failed("archive_endpoint_invalid", parse_listing, "fnnews-sitemaps", index, foreign, index.url)
    monkeypatch.setattr(archives, "MAX_SITEMAP_URLS", 2)
    assert parse_listing("fnnews-sitemaps", index, fn_index(("202608-1", "202608-1")), index.url).saturated
    assert parse_listing("fnnews-sitemaps", partition, xml((FN, FN)), partition.url).saturated
    failed("archive_listing_limit", parse_listing, "fnnews-sitemaps", index, fn_index(), index.url)
    failed("archive_listing_limit", parse_listing, "fnnews-sitemaps", partition, xml((FN, FN, FN)), partition.url)
    monkeypatch.setattr(archives, "MAX_RAW", 10)
    failed("archive_input_invalid", parse_listing, "fnnews-sitemaps", partition, xml((FN,)), partition.url)


@pytest.mark.parametrize(("source", "article"), [("etnews-ai", ET), ("fnnews-sitemaps", FN)])
def test_editorial_utf8_aware_original_publication_exact_body_and_canonical_observation(source, article):
    raw = editorial_og(source, extra=('<link rel="canonical" href="https://unfetched.invalid/original">'
                                    '<meta name="dd:publisher" content="YHN">'
                                    + schema({"@type": "NewsArticle", "datePublished": "2020-01-01",
                                              "publisher": {"name": "Syndication label is not lineage proof"}})))
    meta = article_metadata(source, raw, article)
    assert meta.title == "합성 한국어 제목" and meta.published_at == "2026-08-17T15:20:49+09:00"
    assert meta.publisher == ("전자신문" if source == "etnews-ai" else "파이낸셜뉴스")
    assert meta.source_kind == "editorial" and meta.canonical_url == "https://unfetched.invalid/original"
    prepared = prepare(raw, "text/html", meta.article_xpath)
    assert "합성 한국어 본문입니다." in prepared["text"] and "OUTSIDE" not in prepared["text"]
    missing = article_metadata(source, editorial_og(source, published=None, extra='<meta property="article:modified_time" content="2026-08-17T00:00:00Z">'), article)
    assert missing.published_at is None
    duplicate = raw.replace(b"</head>", b'<meta property="article:published_time" content="2026-08-17T15:20:49+09:00"></head>')
    failed("article_date_conflict", article_metadata, source, duplicate, article)
    for value in ("2026-08-17", "2026-08-17T15:20:49", "2026-02-30T15:20:49+09:00"):
        failed("article_date_invalid", article_metadata, source, editorial_og(source, published=value), article)
    failed("archive_article_host_invalid", article_metadata, source, raw, article.replace(urlsplit(article).netloc, "attacker.invalid"))
    failed("archive_article_route_invalid", article_metadata, source, raw, article + "?next=foreign")


@pytest.mark.parametrize(("source", "article", "duplicate"), [
    ("etnews-ai", ET, '<div id="articleBody">Second body</div>'),
    ("fnnews-sitemaps", FN, '<article class="article-view"><div class="article-view__body">Second body</div></article>'),
])
def test_editorial_body_scope_must_be_present_and_unique(source, article, duplicate):
    failed("article_scope_ambiguous_or_missing", article_metadata, source, og(), article)
    raw = editorial_og(source).replace(b"</body>", duplicate.encode() + b"</body>")
    failed("article_scope_ambiguous_or_missing", article_metadata, source, raw, article)


@pytest.mark.parametrize("source", ["etnews-ai", "fnnews-sitemaps"])
def test_editorial_explicit_loopback_seam_never_relaxes_default_host_validation(source):
    kwargs = {"synthetic_origin": LOOP}
    if source == "etnews-ai":
        selected = initial_tasks(source, DAY, "2026-10-25", **kwargs)[0]
        article = LOOP + "/20260831000357"
        result = parse_listing(source, selected, et_listing(article=article), selected.url, **kwargs)
    else:
        selected = fn_partition(origin=LOOP)
        article = LOOP + "/news/202608101455399495"
        result = parse_listing(source, selected, xml((article,)), selected.url, **kwargs)
    assert result.candidates[0].url == article
    assert source_hosts(source, **kwargs) == ("127.0.0.1",)
    assert article_metadata(source, editorial_og(source), article, **kwargs).source_kind == "editorial"
    failed("archive_endpoint_invalid", validate_discovery_url, source, selected.url)
    failed("archive_article_host_invalid", article_metadata, source, editorial_og(source), article)
    failed("archive_endpoint_invalid", validate_discovery_url, source, selected.url.replace(":18765", ":18766"), **kwargs)
