"""Pure private-news discovery adapters; metadata is neither permission nor coverage proof.

Hankyung daily sitemaps identify archive days, not publication dates. Their lastmod
remains in the caller's raw listing evidence, never in a publication/observation field.
GDELT DOC artlist is capped at 250 rows per exact query/day; saturation is visible
and never recursively queried here. Generic metadata supplies no guessed body scope.

Corporate sitemaps retain only verified article-route shapes (not navigation URLs).
Apple additionally restricts URL months to requested months; neither month paths nor
lastmod prove publication. archive_day can be a day or month precision discovery hint.
Latest-only RSS and unpaginated NAVER monthly pages always report saturated=True:
no verified continuation exists, so they cannot claim complete historical coverage.
XML safety caps are 50,000 sitemap entries and 1,000 RSS entries, within MAX_RAW bytes.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

import httpx
from lxml import etree, html

from .ingestion_contracts import IngestionFailure, MAX_RAW
from .news_sources import SourceDescriptor, source_descriptor

MAX_DAYS = 366
MAX_QUERIES = 64
MAX_QUERY_LENGTH = 1000
GDELT_CAP = 250
MAX_SITEMAP_URLS = 50_000
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_HK = "https://www.hankyung.com"
_GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
_HK_SCOPE = "//div[@id='articletxt']"
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_PUBLICATION = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2}|[+-](?:[01]\d|2[0-3])[0-5]\d)?)?\Z")
_ARTICLE_TYPES = frozenset({"Article", "NewsArticle", "ReportageNewsArticle", "AnalysisNewsArticle", "OpinionNewsArticle", "BlogPosting", "PressRelease"})
_CORPORATE = frozenset({"nvidia-newsroom", "amd-newsroom", "naver-press", "apple-newsroom"})
_EDITORIAL = frozenset({"etnews-ai", "fnnews-sitemaps"})
_EDITORIAL_SCOPES = {
    "etnews-ai": "//*[@id='articleBody']",
    "fnnews-sitemaps": '//article[contains(concat(" ",normalize-space(@class)," ")," article-view ")]//div[contains(concat(" ",normalize-space(@class)," ")," article-view__body ")]',
}
_ET_LIST = '//main//ul[contains(concat(" ",normalize-space(@class)," ")," news_list ")]'
_FN_INDEX = "/resource/view_xml/sitemap_index/news-sitemap-index-"
_FN_PART = "/resource/view_xml/sitemap_v3/sitemap-"
_PARTITION = re.compile(r"([0-9]{4})(0[1-9]|1[0-2])-([1-9][0-9]{0,4})\Z")
_ORIGINS = {"hankyung-daily": _HK, "gdelt-doc": "https://api.gdeltproject.org",
            "nvidia-newsroom": "https://nvidianews.nvidia.com", "amd-newsroom": "https://newsroom.amd.com",
            "naver-press": "https://www.navercorp.com", "apple-newsroom": "https://www.apple.com",
            "etnews-ai": "https://www.etnews.com", "fnnews-sitemaps": "https://www.fnnews.com"}
_CORPORATE_ROUTES = {
    "nvidia-newsroom": (("/sitemap.xml", "sitemap-xml"), ("/cats/press_release.xml", "rss-xml")),
    "amd-newsroom": (("/sitemap.xml", "sitemap-xml"), ("/rss.xml?content-type=news", "rss-xml")),
    "apple-newsroom": (("/newsroom/sitemap.xml", "sitemap-xml"), ("/newsroom/rss-feed.rss", "rss-xml")),
}
_CORPORATE_SCOPES = {
    "naver-press": '//div[contains(concat(" ",normalize-space(@class)," ")," board-view-detail ")]',
    "nvidia-newsroom": '//div[contains(concat(" ",normalize-space(@class)," ")," article-body ")]',
    "amd-newsroom": '//article//div[contains(concat(" ",normalize-space(@class)," ")," article-body ")]//div[contains(concat(" ",normalize-space(@class)," ")," content-body ")]',
    "apple-newsroom": '//main//article[contains(concat(" ",normalize-space(@class)," ")," article ")]',
}
_VISIBLE_DATES = {
    "naver-press": '//div[contains(concat(" ",normalize-space(@class)," ")," media-detail__date ")]',
    "nvidia-newsroom": '//div[contains(concat(" ",normalize-space(@class)," ")," article-date ")]',
    "apple-newsroom": '//span[contains(concat(" ",normalize-space(@class)," ")," category-eyebrow__date ")]',
}
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_NAVER_SEARCH = '//div[contains(concat(" ",normalize-space(@class)," ")," media-press__wrap ") and contains(concat(" ",normalize-space(@class)," ")," is-search ")]'


@dataclass(frozen=True)
class ArchiveTask:
    key: str
    url: str
    kind: str
    from_day: str
    through_day: str


@dataclass(frozen=True)
class Candidate:
    url: str
    title: str | None
    published_at: str | None
    discovery_seen_at: str | None
    archive_day: str | None


@dataclass(frozen=True)
class Listing:
    candidates: tuple[Candidate, ...]
    next_tasks: tuple[ArchiveTask, ...]
    saturated: bool


@dataclass(frozen=True)
class ArticleMeta:
    title: str
    published_at: str | None
    canonical_url: str | None
    article_xpath: str | None
    publisher: str | None
    source_kind: str


def _descriptor(source: str, descriptor: SourceDescriptor | None = None) -> SourceDescriptor | None:
    selected = descriptor if descriptor is not None else source_descriptor(source)
    if selected is not None and selected.source_id != source:
        raise IngestionFailure("archive_source_unsupported")
    return selected


def _origin(source: str, synthetic_origin: str | None, descriptor: SourceDescriptor | None = None) -> str:
    selected = _descriptor(source, descriptor)
    if not isinstance(source, str) or source not in _ORIGINS and selected is None:
        raise IngestionFailure("archive_source_unsupported")
    if synthetic_origin is not None:
        try:
            parts = urlsplit(synthetic_origin)
            if (parts.scheme != "http" or parts.hostname != "127.0.0.1" or parts.port is None
                    or not 1 <= parts.port <= 65535 or synthetic_origin != f"http://127.0.0.1:{parts.port}"):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise IngestionFailure("archive_synthetic_origin_invalid") from None
        return synthetic_origin
    return selected.discovery[0].origins[0] if selected is not None else _ORIGINS[source]


def source_hosts(source: str, *, synthetic_origin: str | None = None,
                 descriptor: SourceDescriptor | None = None) -> tuple[str, ...]:
    origin = _origin(source, synthetic_origin, descriptor)
    selected = _descriptor(source, descriptor)
    if selected is None or synthetic_origin is not None:
        return (urlsplit(origin).hostname,)
    return tuple(sorted({urlsplit(origin).hostname for surface in selected.discovery for origin in surface.origins}))


def _day(value: str) -> date:
    try:
        if not isinstance(value, str) or not _DAY.fullmatch(value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise IngestionFailure("archive_date_invalid") from None


def _window(from_day: str, through_day: str) -> tuple[date, date]:
    first, last = _day(from_day), _day(through_day)
    if last < first or (last - first).days >= MAX_DAYS:
        raise IngestionFailure("archive_window_invalid")
    return first, last


def _query(value: str) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > MAX_QUERY_LENGTH
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise IngestionFailure("archive_query_invalid")
    return value


def _link(value, code="archive_url_invalid") -> str:
    """Preserve encoded path/query identity; never resolve DNS or follow a link."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 4000:
            raise ValueError
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None
                or parts.password is not None or "\\" in value or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            raise ValueError
        parts.port  # Reject invalid ports even though this function grants no access.
        parsed = httpx.URL(value)
        result = str(parsed.copy_with(raw_path=parsed.raw_path, fragment=None))
        if len(result) > 4000:
            raise ValueError
        return result
    except (ValueError, UnicodeError, httpx.InvalidURL):
        raise IngestionFailure(code) from None


def _gdelt_url(query: str, day: date) -> str:
    compact = day.isoformat().replace("-", "")
    return _GDELT + "?" + urlencode({"query": query, "mode": "artlist", "format": "json", "maxrecords": str(GDELT_CAP),
                                     "startdatetime": compact + "000000", "enddatetime": compact + "235959", "sort": "dateasc"})


def _et_task(origin: str, page: int, first: str, last: str) -> ArchiveTask:
    return ArchiveTask(f"etnews-ai:{page}:{first}:{last}",
                       f"{origin}/news/category_list.html?id=2958&page={page}", "etnews-list", first, last)


def _fn_tokens(tokens: tuple[str, ...], first: str, last: str, *, code="archive_query_invalid") -> tuple[str, ...]:
    for token in tokens:
        match = _PARTITION.fullmatch(token)
        if match is None or int(match.group(1)) == 0:
            raise IngestionFailure(code)
        month = f"{match.group(1)}-{match.group(2)}"
        if not first[:7] <= month <= last[:7]:
            raise IngestionFailure(code)
    return tuple(sorted(set(tokens)))


def _fn_part_task(origin: str, token: str, first: str, last: str) -> ArchiveTask:
    _fn_tokens((token,), first, last, code="archive_task_invalid")
    month = date(int(token[:4]), int(token[4:6]), 1)
    following = (month.replace(day=28) + timedelta(days=4)).replace(day=1) if month.year < 9999 or month.month < 12 else None
    begin = max(first, month.isoformat())
    end = min(last, (following - timedelta(days=1)).isoformat()) if following else last
    return ArchiveTask(f"fnnews-sitemaps:{token}:{begin}:{end}", f"{origin}{_FN_PART}{token}.xml",
                       "fnnews-partition", begin, end)


def _bound_editorial_task(source: str, task: ArchiveTask, requested: str, final: str,
                          synthetic_origin: str | None) -> None:
    origin = _origin(source, synthetic_origin)
    parts = urlsplit(requested)
    if source == "etnews-ai":
        expected = _et_task(origin, int(dict(parse_qsl(parts.query))["page"]), task.from_day, task.through_day)
    elif task.kind == "fnnews-partition":
        token = parts.path.removeprefix(_FN_PART).removesuffix(".xml")
        expected = _fn_part_task(origin, token, task.from_day, task.through_day)
    else:
        if not isinstance(task.kind, str) or not (task.kind == "fnnews-index" or task.kind.startswith("fnnews-index:")):
            raise IngestionFailure("archive_task_invalid")
        queries = tuple(task.kind.split(":", 1)[1].split(",")) if ":" in task.kind else ()
        options = initial_tasks(source, task.from_day, task.through_day, queries, synthetic_origin=synthetic_origin)
        matches = [item for item in options if item.key == task.key]
        if len(matches) != 1:
            raise IngestionFailure("archive_task_invalid")
        expected = matches[0]
    if (task.key != expected.key or task.kind != expected.kind
            or parts.path != urlsplit(expected.url).path
            or dict(parse_qsl(parts.query)) != dict(parse_qsl(urlsplit(expected.url).query))
            or urlsplit(final).path != parts.path
            or dict(parse_qsl(urlsplit(final).query)) != dict(parse_qsl(parts.query))):
        raise IngestionFailure("archive_task_invalid")


def _editorial_article(source: str, url: str, synthetic_origin: str | None) -> str:
    identity = _link(url)
    parts, origin = urlsplit(identity), urlsplit(_origin(source, synthetic_origin))
    if (parts.scheme, parts.netloc) != (origin.scheme, origin.netloc):
        raise IngestionFailure("archive_article_host_invalid")
    route = r"/[0-9]{14}" if source == "etnews-ai" else r"/news/[0-9]{18}"
    if not re.fullmatch(route, parts.path) or parts.query or "#" in url:
        raise IngestionFailure("archive_article_route_invalid")
    return identity


def _et_listing(task: ArchiveTask, raw: bytes, final_url: str, synthetic_origin: str | None) -> Listing:
    try:
        tree = html.document_fromstring(raw.decode("utf-8", errors="strict"), parser=html.HTMLParser(no_network=True, recover=True))
    except (ValueError, UnicodeError, etree.ParserError):
        raise IngestionFailure("archive_html_invalid") from None
    scopes = tree.xpath(_ET_LIST)
    if len(scopes) != 1:
        raise IngestionFailure("archive_listing_ambiguous")
    rows = scopes[0].xpath("./li")
    if len(rows) > MAX_SITEMAP_URLS:
        raise IngestionFailure("archive_listing_limit")
    candidates = {}
    for row in rows:
        links = {}
        for node in row.xpath(".//a[@href]"):
            href = node.get("href")
            if any(ord(c) < 33 or ord(c) == 127 for c in href):
                raise IngestionFailure("archive_url_invalid")
            resolved = urljoin(final_url, href)
            if not re.fullmatch(r"/[0-9]{14}", urlsplit(resolved).path):
                continue
            url = _editorial_article("etnews-ai", resolved, synthetic_origin)
            text = "".join(node.itertext()).strip()
            if text:
                links[url] = _optional_text(text, "archive_listing_invalid")
            else:
                links.setdefault(url, None)
        if len(links) > 1:
            raise IngestionFailure("archive_listing_ambiguous")
        if not links:
            continue
        dates = row.xpath('.//span[contains(concat(" ",normalize-space(@class)," ")," date ")]')
        hint = None
        if len(dates) == 1:
            value = "".join(dates[0].itertext()).strip()
            if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", value):
                hint = _date_hint(value.replace(" ", "T"))
        url, title = next(iter(links.items()))
        candidates.setdefault(url, Candidate(url, title, None, None, hint))
    page = int(dict(parse_qsl(urlsplit(task.url).query))["page"])
    following = None
    for node in tree.xpath("//main//a[@href]"):
        href = node.get("href")
        if any(ord(c) < 33 or ord(c) == 127 for c in href):
            continue
        try:
            url = validate_discovery_url("etnews-ai", urljoin(final_url, href), synthetic_origin=synthetic_origin)
        except IngestionFailure:
            continue
        if int(dict(parse_qsl(urlsplit(url).query))["page"]) == page + 1:
            following = _et_task(_origin("etnews-ai", synthetic_origin), page + 1, task.from_day, task.through_day)
    # Never stop by a listing date: the AI category is not a complete publisher archive.
    # Missing continuation is visibly incomplete, not evidence that the date window is exhausted.
    return Listing(tuple(candidates.values()), (following,) if following else (),
                   len(rows) == MAX_SITEMAP_URLS or following is None)


def _fn_listing(task: ArchiveTask, raw: bytes, synthetic_origin: str | None) -> Listing:
    root = _xml_root(raw)
    prefix = "{" + SITEMAP_NS + "}"
    is_index = task.kind != "fnnews-partition"
    entry_name = prefix + ("sitemap" if is_index else "url")
    if (root.tag != prefix + ("sitemapindex" if is_index else "urlset")
            or any(isinstance(node.tag, str) and node.tag != entry_name for node in root)):
        raise IngestionFailure("archive_xml_invalid")
    entries = root.findall(entry_name)
    if len(entries) > MAX_SITEMAP_URLS:
        raise IngestionFailure("archive_listing_limit")
    candidates, advertised = {}, {}
    origin = _origin("fnnews-sitemaps", synthetic_origin)
    for entry in entries:
        location = _xml_text(entry, prefix + "loc", required=True)
        if is_index:
            url = validate_discovery_url("fnnews-sitemaps", location, synthetic_origin=synthetic_origin)
            path = urlsplit(url).path
            if not path.startswith(_FN_PART):
                raise IngestionFailure("archive_endpoint_invalid")
            token = path.removeprefix(_FN_PART).removesuffix(".xml")
            if token[:4] != task.from_day[:4]:
                raise IngestionFailure("archive_endpoint_invalid")
            advertised[token] = url
        else:
            url = _editorial_article("fnnews-sitemaps", location, synthetic_origin)
            hint = _date_hint(_xml_text(entry, prefix + "lastmod"))
            if hint is None:
                digits = urlsplit(url).path.rsplit("/", 1)[1][:8]
                hint = _date_hint(f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}")
            # Keep even out-of-window hints in their own date bucket, never clamp to
            # an in-window partition day or discard a possibly in-window article.
            candidates.setdefault(url, Candidate(url, None, None, None, hint))
    if not is_index:
        return Listing(tuple(candidates.values()), (), len(entries) == MAX_SITEMAP_URLS)
    selected = tuple(task.kind.split(":", 1)[1].split(",")) if ":" in task.kind else ()
    if any(token not in advertised for token in selected):
        raise IngestionFailure("archive_partition_unadvertised")
    tokens = selected or tuple(sorted(token for token in advertised
                                     if task.from_day[:7] <= f"{token[:4]}-{token[4:6]}" <= task.through_day[:7]))
    following = tuple(_fn_part_task(origin, token, task.from_day, task.through_day) for token in tokens)
    return Listing((), following, len(entries) == MAX_SITEMAP_URLS)


def initial_tasks(source: str, from_day: str, through_day: str, queries: tuple[str, ...] = (),
                  *, synthetic_origin: str | None = None,
                  descriptor: SourceDescriptor | None = None) -> tuple[ArchiveTask, ...]:
    origin = _origin(source, synthetic_origin, descriptor)
    first, last = _window(from_day, through_day)
    selected = _descriptor(source, descriptor)
    if selected is not None:
        if queries:
            raise IngestionFailure("archive_query_invalid")
        return tuple(_configured_task(source, index, surface.kind, _synthetic_url(surface.url, synthetic_origin),
                                      from_day, through_day) for index, surface in enumerate(selected.discovery))
    if not isinstance(queries, tuple) or len(queries) > MAX_QUERIES:
        raise IngestionFailure("archive_query_invalid")
    if source not in {"gdelt-doc", "fnnews-sitemaps"} and queries:
        raise IngestionFailure("archive_query_invalid")
    unique_queries = tuple(dict.fromkeys(_query(query) for query in queries))
    if source == "gdelt-doc" and not unique_queries:
        raise IngestionFailure("archive_query_invalid")
    if source == "etnews-ai":
        return (_et_task(origin, 1, from_day, through_day),)
    if source == "fnnews-sitemaps":
        tokens = _fn_tokens(unique_queries, from_day, through_day)
        tasks = []
        for year in range(first.year, last.year + 1):
            selected = tuple(token for token in tokens if token[:4] == f"{year:04d}")
            if tokens and not selected:
                continue
            begin, end = max(first, date(year, 1, 1)).isoformat(), min(last, date(year, 12, 31)).isoformat()
            kind = "fnnews-index" + (":" + ",".join(selected) if selected else "")
            tasks.append(ArchiveTask(f"{source}:{year:04d}:{kind}:{begin}:{end}",
                                     f"{origin}{_FN_INDEX}{year:04d}.xml", kind, begin, end))
        return tuple(tasks)
    if source in _CORPORATE_ROUTES:
        return tuple(ArchiveTask(f"{source}:{kind}:{from_day}:{through_day}", origin + route, kind, from_day, through_day)
                     for route, kind in _CORPORATE_ROUTES[source])
    if source == "naver-press":
        tasks = []
        month = first.replace(day=1)
        while month <= last:
            following = (month.replace(day=28) + timedelta(days=4)).replace(day=1) if month.year < 9999 or month.month < 12 else None
            end = min(last, following - timedelta(days=1)) if following is not None else last
            begin = max(first, month)
            url = origin + "/en/media/pressReleases?" + urlencode({"keyword": "", "year": f"{month.year:04d}", "month": month.month})
            tasks.append(ArchiveTask(f"{source}:{month.isoformat()[:7]}:{begin}:{end}", url, "archive-html", begin.isoformat(), end.isoformat()))
            if following is None:
                break
            month = following
        return tuple(tasks)
    tasks = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        label = day.isoformat()
        if source == "hankyung-daily":
            compact = label.replace("-", "")
            tasks.append(ArchiveTask(f"{source}:{label}", f"{origin}/sitemap/daily-article/{compact}.xml", "sitemap-xml", label, label))
        else:
            for query in unique_queries:
                key = hashlib.sha256(query.encode("utf-8")).hexdigest()
                url = origin + _gdelt_url(query, day).removeprefix("https://api.gdeltproject.org")
                tasks.append(ArchiveTask(f"{source}:{label}:{key}", url, "gdelt-artlist", label, label))
    return tuple(tasks)


def validate_discovery_url(source: str, url: str, *, synthetic_origin: str | None = None,
                           descriptor: SourceDescriptor | None = None) -> str:
    """Validate BEFORE transport, including redirect targets; source_hosts alone is insufficient."""
    selected = _descriptor(source, descriptor)
    if selected is not None:
        return _configured_url(selected, url, synthetic_origin, discovery=True)
    origin = urlsplit(_link(_origin(source, synthetic_origin)))
    identity = _link(url, "archive_endpoint_invalid")
    parts = urlsplit(identity)
    if (parts.scheme, parts.netloc) != (origin.scheme, origin.netloc) or "#" in url:
        raise IngestionFailure("archive_endpoint_invalid")
    if source == "hankyung-daily":
        match = re.fullmatch(r"/sitemap/daily-article/(\d{4})(\d{2})(\d{2})\.xml", parts.path)
        if not match or parts.query:
            raise IngestionFailure("archive_endpoint_invalid")
        _day("-".join(match.groups()))
    elif source == "etnews-ai":
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        params = dict(pairs)
        if (parts.path != "/news/category_list.html" or len(pairs) != 2
                or set(params) != {"id", "page"} or params["id"] != "2958"
                or not re.fullmatch(r"[1-9][0-9]{0,8}", params["page"])):
            raise IngestionFailure("archive_endpoint_invalid")
    elif source == "fnnews-sitemaps":
        index = re.fullmatch(re.escape(_FN_INDEX) + r"([0-9]{4})\.xml", parts.path)
        partition = re.fullmatch(re.escape(_FN_PART) + r"(.+)\.xml", parts.path)
        if parts.query or not (index or partition):
            raise IngestionFailure("archive_endpoint_invalid")
        if index:
            if int(index.group(1)) == 0:
                raise IngestionFailure("archive_endpoint_invalid")
        else:
            _fn_tokens((partition.group(1),), "0001-01-01", "9999-12-31", code="archive_endpoint_invalid")
    elif source in _CORPORATE_ROUTES:
        if not any((parts.path, parts.query) == (urlsplit(route).path, urlsplit(route).query)
                   for route, _ in _CORPORATE_ROUTES[source]):
            raise IngestionFailure("archive_endpoint_invalid")
    elif source == "naver-press":
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        params = dict(pairs)
        try:
            if (parts.path != "/en/media/pressReleases" or len(pairs) != 3 or set(params) != {"keyword", "year", "month"}
                    or params["keyword"] != "" or not re.fullmatch(r"\d{4}", params["year"])
                    or not re.fullmatch(r"[1-9]|1[0-2]", params["month"])):
                raise ValueError
            date(int(params["year"]), int(params["month"]), 1)
        except (ValueError, KeyError):
            raise IngestionFailure("archive_endpoint_invalid") from None
    else:
        try:
            pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
            params = dict(pairs)
            if (parts.path != "/api/v2/doc/doc" or len(pairs) != len(params)
                    or set(params) != {"query", "mode", "format", "maxrecords", "startdatetime", "enddatetime", "sort"}
                    or params["mode"] != "artlist" or params["format"] != "json"
                    or params["maxrecords"] != str(GDELT_CAP) or params["sort"] != "dateasc"):
                raise ValueError
            _query(params["query"])
            start, end = params["startdatetime"], params["enddatetime"]
            if (not re.fullmatch(r"\d{8}000000", start) or end != start[:8] + "235959"):
                raise ValueError
            _day(f"{start[:4]}-{start[4:6]}-{start[6:8]}")
        except (ValueError, KeyError):
            raise IngestionFailure("archive_endpoint_invalid") from None
    return identity


def _bound_task(source: str, task: ArchiveTask, final_url: str, synthetic_origin: str | None) -> None:
    if not isinstance(task, ArchiveTask):
        raise IngestionFailure("archive_task_invalid")
    first, last = _window(task.from_day, task.through_day)
    if source not in _CORPORATE | _EDITORIAL and first != last:
        raise IngestionFailure("archive_task_invalid")
    requested = validate_discovery_url(source, task.url, synthetic_origin=synthetic_origin)
    final = validate_discovery_url(source, final_url, synthetic_origin=synthetic_origin)
    if source in _EDITORIAL:
        _bound_editorial_task(source, task, requested, final, synthetic_origin)
        return
    query = (dict(parse_qsl(urlsplit(requested).query))["query"],) if source == "gdelt-doc" else ()
    expected_tasks = initial_tasks(source, task.from_day, task.through_day, query, synthetic_origin=synthetic_origin)
    matches = [item for item in expected_tasks if item.key == task.key and item.kind == task.kind]
    if len(matches) != 1:
        raise IngestionFailure("archive_task_invalid")
    expected = matches[0]
    # Query ordering can differ after a legitimate redirect, but query/date identity cannot.
    if (task.key != expected.key or task.kind != expected.kind
            or urlsplit(requested).path != urlsplit(expected.url).path
            or dict(parse_qsl(urlsplit(requested).query)) != dict(parse_qsl(urlsplit(expected.url).query))
            or urlsplit(final).path != urlsplit(requested).path
            or dict(parse_qsl(urlsplit(final).query)) != dict(parse_qsl(urlsplit(requested).query))):
        raise IngestionFailure("archive_task_invalid")


def _raw(raw: bytes) -> None:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_RAW:
        raise IngestionFailure("archive_input_invalid")


def _json(raw: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError

    try:
        return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError):
        raise IngestionFailure("archive_json_invalid") from None


def _hankyung_article(url: str, synthetic_origin: str | None) -> str:
    identity = _link(url)
    parts = urlsplit(identity)
    origin = urlsplit(_link(_origin("hankyung-daily", synthetic_origin)))
    if ((parts.scheme, parts.netloc) != (origin.scheme, origin.netloc)
            or not re.fullmatch(r"/article/[A-Za-z0-9]+", parts.path) or parts.query or "#" in url):
        raise IngestionFailure("archive_article_host_invalid")
    return identity


def _corporate_article(source: str, url: str, synthetic_origin: str | None, *, strict=True) -> str | None:
    identity = _link(url)
    parts = urlsplit(identity)
    origin = urlsplit(_link(_origin(source, synthetic_origin)))
    if (parts.scheme, parts.netloc) != (origin.scheme, origin.netloc):
        raise IngestionFailure("archive_article_host_invalid")
    if source in {"nvidia-newsroom", "amd-newsroom"}:
        valid = bool(re.fullmatch(r"/news/[A-Za-z0-9][A-Za-z0-9-]*/?", parts.path)) and not parts.query
    elif source == "apple-newsroom":
        match = re.fullmatch(r"/newsroom/(\d{4})/(0[1-9]|1[0-2])/[A-Za-z0-9][A-Za-z0-9-]*/?", parts.path)
        valid = bool(match) and not parts.query
    else:
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        valid = (parts.path == "/en/media/pressReleasesDetail" and len(pairs) == 1
                 and pairs[0][0] == "seq" and re.fullmatch(r"[0-9]{1,20}", pairs[0][1]) is not None)
    if not valid or "#" in url:
        if strict:
            raise IngestionFailure("archive_article_route_invalid")
        return None
    return identity


def _xml_root(raw: bytes):
    try:
        root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False, huge_tree=False))
        if root.getroottree().docinfo.doctype or any(isinstance(node, etree._Entity) for node in root.iter()):
            raise IngestionFailure("archive_xml_unsafe")
        return root
    except etree.XMLSyntaxError:
        raise IngestionFailure("archive_xml_invalid") from None


def _xml_text(parent, tag: str, *, required=False) -> str | None:
    nodes = parent.findall(tag)
    if len(nodes) > 1 or (required and len(nodes) != 1) or any(len(node) for node in nodes):
        raise IngestionFailure("archive_xml_invalid")
    value = nodes[0].text if nodes else None
    if required and (value is None or not value.strip()):
        raise IngestionFailure("archive_xml_invalid")
    return value.strip() if value else None


def _date_hint(value: str | None, *, rss=False) -> str | None:
    if value is None:
        return None
    try:
        if rss:
            return parsedate_to_datetime(value).date().isoformat()
        return _publication(value)[:10]
    except (IngestionFailure, ValueError, TypeError, OverflowError):
        return None


def _corporate_xml(source: str, task: ArchiveTask, raw: bytes, synthetic_origin: str | None) -> Listing:
    root = _xml_root(raw)
    candidates = {}
    if task.kind == "sitemap-xml":
        prefix = "{" + SITEMAP_NS + "}"
        if root.tag != prefix + "urlset" or any(isinstance(node.tag, str) and node.tag != prefix + "url" for node in root):
            raise IngestionFailure("archive_xml_invalid")
        entries = root.findall(prefix + "url")
        if len(entries) > MAX_SITEMAP_URLS:
            raise IngestionFailure("archive_listing_limit")
        for entry in entries:
            url = _corporate_article(source, _xml_text(entry, prefix + "loc", required=True), synthetic_origin, strict=False)
            if url is None:
                continue
            hint = _date_hint(_xml_text(entry, prefix + "lastmod"))
            if source == "apple-newsroom":
                # Month precision only: URL dates are discovery hints, not publication evidence.
                hint = "/".join(urlsplit(url).path.split("/")[2:4]).replace("/", "-")
                if not task.from_day[:7] <= hint <= task.through_day[:7]:
                    continue
            candidates.setdefault(url, Candidate(url, None, None, None, hint))
        return Listing(tuple(candidates.values()), (), len(entries) == MAX_SITEMAP_URLS)
    if source == "apple-newsroom":
        atom = "{http://www.w3.org/2005/Atom}"
        if root.tag != atom + "feed":
            raise IngestionFailure("archive_xml_invalid")
        entries = root.findall(atom + "entry")
        if len(entries) > 1000:
            raise IngestionFailure("archive_listing_limit")
        for entry in entries:
            links = []
            for node in entry.findall(atom + "link"):
                if node.get("rel", "alternate") != "alternate" or node.get("type") not in {None, "text/html"}:
                    continue
                if not node.get("href"):
                    raise IngestionFailure("archive_xml_invalid")
                url = _corporate_article(source, node.get("href"), synthetic_origin, strict=False)
                if url is not None:
                    links.append(url)
            if len(links) != 1:
                raise IngestionFailure("archive_xml_invalid")
            url = links[0]
            title = _optional_text(_xml_text(entry, atom + "title"), "archive_listing_invalid")
            hint = "-".join(urlsplit(url).path.split("/")[2:4])
            candidates.setdefault(url, Candidate(url, title, None, None, hint))
        # Atom updated is not publication; neither image links nor their targets are retained.
        return Listing(tuple(candidates.values()), (), True)
    if root.tag != "rss" or root.get("version") != "2.0":
        raise IngestionFailure("archive_xml_invalid")
    channels = root.findall("channel")
    if len(channels) != 1:
        raise IngestionFailure("archive_xml_invalid")
    entries = channels[0].findall("item")
    if len(entries) > 1000:
        raise IngestionFailure("archive_listing_limit")
    for entry in entries:
        url = _corporate_article(source, _xml_text(entry, "link", required=True), synthetic_origin)
        title = _optional_text(_xml_text(entry, "title"), "archive_listing_invalid")
        hint = _date_hint(_xml_text(entry, "pubDate"), rss=True)
        candidates.setdefault(url, Candidate(url, title, None, None, hint))
    # A rolling latest-only feed has no proven pagination/history coverage even below its row cap.
    return Listing(tuple(candidates.values()), (), True)


def _naver_listing(task: ArchiveTask, raw: bytes, final_url: str, synthetic_origin: str | None) -> Listing:
    try:
        tree = html.document_fromstring(raw.decode("utf-8", errors="strict"), parser=html.HTMLParser(no_network=True, recover=True))
    except (ValueError, UnicodeError, etree.ParserError):
        raise IngestionFailure("archive_html_invalid") from None
    candidates = {}
    scopes = tree.xpath(_NAVER_SEARCH)
    if len(scopes) != 1:
        raise IngestionFailure("archive_listing_ambiguous")
    rows = scopes[0].xpath(".//li")
    if len(rows) > MAX_SITEMAP_URLS:
        raise IngestionFailure("archive_listing_limit")
    for row in rows:
        links = {}
        for node in row.xpath(".//a[@href]"):
            href = node.get("href")
            if "pressReleasesDetail" not in href:
                continue
            if any(ord(c) < 33 or ord(c) == 127 for c in href):
                raise IngestionFailure("archive_url_invalid")
            url = _corporate_article("naver-press", urljoin(final_url, href), synthetic_origin)
            links.setdefault(url, _optional_text(node.get("title"), "archive_listing_invalid"))
        if len(links) > 1:
            raise IngestionFailure("archive_listing_ambiguous")
        if not links:
            continue
        date_nodes = row.xpath('.//span[contains(concat(" ",normalize-space(@class)," ")," news-date ")]')
        hint = None
        if len(date_nodes) == 1:
            value = "".join(date_nodes[0].itertext()).strip()
            if re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}", value):
                hint = _date_hint(value.replace(".", "-"))
        url, title = next(iter(links.items()))
        candidates.setdefault(url, Candidate(url, title, None, None, hint))
    # No next-page route was verified. A monthly page cannot establish exhaustive month coverage.
    return Listing(tuple(candidates.values()), (), True)


def _sitemap(raw: bytes, day: str, synthetic_origin: str | None) -> Listing:
    root = _xml_root(raw)
    prefix = "{" + SITEMAP_NS + "}"
    if root.tag != prefix + "urlset":
        raise IngestionFailure("archive_xml_invalid")
    entries = root.findall(prefix + "url")
    if len(entries) > MAX_SITEMAP_URLS:
        raise IngestionFailure("archive_listing_limit")
    candidates = {}
    for entry in entries:
        url = _hankyung_article(_xml_text(entry, prefix + "loc", required=True), synthetic_origin)
        candidates.setdefault(url, Candidate(url, None, None, None, day))
    if any(isinstance(node.tag, str) and node.tag != prefix + "url" for node in root):
        raise IngestionFailure("archive_xml_invalid")
    return Listing(tuple(candidates.values()), (), len(entries) == MAX_SITEMAP_URLS)


def _optional_text(value, code: str) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, str) or not value.strip() or len(value) > 4000
            or any((ord(c) < 32 and c not in "\t\n\r") or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise IngestionFailure(code)
    return value


def _gdelt(raw: bytes) -> Listing:
    data = _json(raw)
    if not isinstance(data, dict) or not isinstance(data.get("articles"), list):
        raise IngestionFailure("archive_listing_invalid")
    rows = data["articles"]
    if len(rows) > GDELT_CAP:
        raise IngestionFailure("archive_listing_limit")
    candidates = {}
    for row in rows:
        if not isinstance(row, dict):
            raise IngestionFailure("archive_listing_invalid")
        url = _link(row.get("url"))
        title = _optional_text(row.get("title"), "archive_listing_invalid")
        seen = _optional_text(row.get("seendate"), "archive_seen_date_invalid")
        if seen is not None:
            try:
                if not re.fullmatch(r"\d{8}T\d{6}Z", seen):
                    raise ValueError
                datetime.strptime(seen, "%Y%m%dT%H%M%SZ")
            except ValueError:
                raise IngestionFailure("archive_seen_date_invalid") from None
        candidate = Candidate(url, title, None, seen, None)
        # Conflicting duplicate metadata is unknown, not arbitrarily first/last truth.
        previous = candidates.get(url)
        if previous is not None:
            candidate = Candidate(url, title if title == previous.title else None, None,
                                  seen if seen == previous.discovery_seen_at else None, None)
        candidates[url] = candidate
    return Listing(tuple(candidates.values()), (), len(rows) == GDELT_CAP)


def parse_listing(source: str, task: ArchiveTask, raw: bytes, final_url: str, *, synthetic_origin: str | None = None,
                  descriptor: SourceDescriptor | None = None) -> Listing:
    selected = _descriptor(source, descriptor)
    if selected is not None:
        return _configured_listing(selected, task, raw, final_url, synthetic_origin)
    _origin(source, synthetic_origin)
    _bound_task(source, task, final_url, synthetic_origin)
    _raw(raw)
    if source == "hankyung-daily":
        return _sitemap(raw, task.from_day, synthetic_origin)
    if source == "gdelt-doc":
        return _gdelt(raw)
    if source == "etnews-ai":
        return _et_listing(task, raw, final_url, synthetic_origin)
    if source == "fnnews-sitemaps":
        return _fn_listing(task, raw, synthetic_origin)
    if source == "naver-press":
        return _naver_listing(task, raw, final_url, synthetic_origin)
    return _corporate_xml(source, task, raw, synthetic_origin)


def _one(values: list[str], code: str) -> str | None:
    unique = set(values)
    if len(unique) > 1:
        raise IngestionFailure(code)
    return next(iter(unique)) if unique else None


def _publication(value: str) -> str:
    try:
        if not _PUBLICATION.fullmatch(value):
            raise ValueError
        if "T" in value:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            date.fromisoformat(value)
        return value
    except ValueError:
        raise IngestionFailure("article_date_invalid") from None


def _published(values: list[str]) -> str | None:
    """OG publication precedes schema datePublished; equivalent offsets keep original spelling."""
    checked = [_publication(value) for value in values]
    if not checked:
        return None
    chosen = checked[0]
    for other in checked[1:]:
        if chosen == other:
            continue
        if "T" not in chosen or "T" not in other:
            if chosen[:10] != other[:10]:
                raise IngestionFailure("article_date_conflict")
            continue
        first = datetime.fromisoformat(chosen.replace("Z", "+00:00"))
        second = datetime.fromisoformat(other.replace("Z", "+00:00"))
        if first.tzinfo is None or second.tzinfo is None:
            # No timezone is invented for an unzoned declaration.
            compatible = first.replace(tzinfo=None) == second.replace(tzinfo=None)
        else:
            compatible = first == second
        fractions = [re.search(r"\.(\d+)", value) for value in (chosen, other)]
        nanos = [(match.group(1) if match else "").ljust(9, "0") for match in fractions]
        if not compatible or nanos[0] != nanos[1]:
            raise IngestionFailure("article_date_conflict")
    return chosen


def _schema_type(value) -> str:
    if not isinstance(value, str):
        return ""
    if re.fullmatch(r"[A-Za-z]+", value):
        return value
    match = re.fullmatch(r"https?://schema\.org/([A-Za-z]+)", value)
    return match.group(1) if match else ""


def _article_nodes(tree) -> list[dict]:
    nodes = []
    for script in tree.xpath("//script[@type='application/ld+json']"):
        if not script.text or not script.text.strip():
            continue
        data = _json(script.text.encode("utf-8"))
        pending = list(data) if isinstance(data, list) else [data]
        while pending:
            item = pending.pop()
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                pending.extend(graph)
            kinds = item.get("@type", [])
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if any(_schema_type(kind) in _ARTICLE_TYPES for kind in kinds):
                nodes.append(item)
    if len(nodes) > 1:
        raise IngestionFailure("article_metadata_ambiguous")
    return nodes


def _visible_publication(source: str, tree) -> str | None:
    nodes = tree.xpath(_VISIBLE_DATES[source])
    if not nodes:
        return None
    if len(nodes) != 1:
        raise IngestionFailure("article_date_conflict")
    value = "".join(nodes[0].itertext()).strip()
    try:
        if source == "naver-press":
            if not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}", value):
                raise ValueError
            date.fromisoformat(value.replace(".", "-"))
        else:
            match = re.fullmatch(r"([A-Za-z]+) ([1-9]|[12][0-9]|3[01]), ([0-9]{4})", value)
            if match is None or match.group(1) not in _MONTHS:
                raise ValueError
            date(int(match.group(3)), _MONTHS.index(match.group(1)) + 1, int(match.group(2)))
    except ValueError:
        raise IngestionFailure("article_date_invalid") from None
    return value


def article_metadata(source: str, raw: bytes, final_url: str, *, synthetic_origin: str | None = None,
                     descriptor: SourceDescriptor | None = None, require_body: bool = True) -> ArticleMeta:
    """Parse only metadata; caller must separately authorize final_url's exact host.

    Out-of-host canonical URLs are observations, never acquisition targets. Generic
    body extraction remains the native preparer's unambiguous semantic scope check.
    """
    selected = _descriptor(source, descriptor)
    origin = _origin(source, synthetic_origin, descriptor)
    if selected is not None:
        final = _configured_url(selected, final_url, synthetic_origin)
    elif source == "hankyung-daily":
        final = _hankyung_article(final_url, synthetic_origin)
    elif source in _EDITORIAL:
        final = _editorial_article(source, final_url, synthetic_origin)
    elif source in _CORPORATE:
        final = _corporate_article(source, final_url, synthetic_origin)
    else:
        final = _link(final_url)
    if synthetic_origin is not None and (urlsplit(final).scheme, urlsplit(final).netloc) != (urlsplit(_link(origin)).scheme, urlsplit(_link(origin)).netloc):
        raise IngestionFailure("archive_article_host_invalid")
    _raw(raw)
    try:
        tree = html.document_fromstring(raw.decode("utf-8", errors="strict"), parser=html.HTMLParser(no_network=True, recover=True))
    except (ValueError, UnicodeError, etree.ParserError):
        raise IngestionFailure("article_html_invalid") from None

    def meta(name):
        return [_optional_text(node.get("content"), "article_metadata_invalid") for node in tree.xpath("//meta")
                if (node.get("property") or node.get("name") or "").lower() == name]

    def values(items):
        return [item for item in items if item is not None]

    schema = _article_nodes(tree)
    item = schema[0] if schema else {}
    headline = _optional_text(item.get("headline"), "article_metadata_invalid")
    title = _one(values(meta("og:title")), "article_title_conflict")
    if title is None:
        title = headline
    if title is None:
        # A title element is a declared document title, not guessed body text.
        title = _one([node.text for node in tree.xpath("//title") if node.text and node.text.strip()], "article_title_conflict")
    if title is None or len(title) > 4000:
        raise IngestionFailure("article_title_missing")
    if source in _VISIBLE_DATES:
        # These exact first-party header fields are proven publication metadata.
        # In particular Apple's malformed schema date-only-Z and all modified dates
        # cannot replace the visible day or turn it into an inferred instant.
        published = _visible_publication(source, tree)
    elif source in _EDITORIAL:
        publication = meta("article:published_time")
        if len(publication) > 1:
            raise IngestionFailure("article_date_conflict")
        published = _published(values(publication))
        if published is not None and ("T" not in published or datetime.fromisoformat(published.replace("Z", "+00:00")).tzinfo is None):
            raise IngestionFailure("article_date_invalid")
    else:
        publication = values([value for name in (selected.publication_meta if selected else ["article:published_time"])
                              for value in meta(name)])
        schema_date = _optional_text(item.get("datePublished"), "article_date_invalid")
        if schema_date is not None:
            publication.append(schema_date)
        published = _published(publication)
        if selected is not None and selected.publication_xpath is not None:
            visible = _configured_publication(tree, selected)
            if selected.publication_policy == "visible-day":
                if published is not None and visible is not None and published[:10] != visible[:10]:
                    raise IngestionFailure("article_date_conflict")
                published = visible
            elif visible is not None:
                published = _published([value for value in (published, visible) if value is not None])

    canonicals = []
    for node in tree.xpath("//link[@href]"):
        if "canonical" in (node.get("rel") or "").lower().split():
            href = _optional_text(node.get("href"), "article_canonical_invalid")
            if any(ord(c) < 33 or ord(c) == 127 for c in href):
                raise IngestionFailure("article_canonical_invalid")
            canonicals.append(_link(urljoin(final, href), "article_canonical_invalid"))
    canonical = _one(canonicals, "article_canonical_conflict")
    site_name = _one(values(meta("og:site_name")), "article_publisher_conflict")
    publisher = item.get("publisher")
    if publisher is not None:
        if isinstance(publisher, dict):
            publisher = publisher.get("name")
        publisher = _optional_text(publisher, "article_metadata_invalid")
    # Organization publisher and social site/brand names are distinct metadata fields.
    publisher_name = publisher if publisher is not None else site_name
    if source in _EDITORIAL:
        # Website identity is not evidence of the original publisher of syndicated copy.
        publisher_name = "전자신문" if source == "etnews-ai" else "파이낸셜뉴스"
    genre = item.get("genre")
    genres = genre if isinstance(genre, list) else [genre]
    corporate = any(isinstance(value, str) and value.strip().lower() in {"press release", "press-release", "보도자료"} for value in genres)
    kinds = item.get("@type", [])
    kinds = kinds if isinstance(kinds, list) else [kinds]
    corporate = corporate or any(_schema_type(kind) == "PressRelease" for kind in kinds)
    source_kind = "corporate-pr" if corporate or source in _CORPORATE else "unknown"
    scope = None
    if source == "hankyung-daily":
        scopes = tree.xpath("//*[@id='articletxt']")
        if require_body and (len(scopes) != 1 or scopes[0].tag != "div"):
            raise IngestionFailure("article_scope_ambiguous_or_missing")
        scope = _HK_SCOPE
        source_kind = "corporate-pr" if corporate else "editorial"
    elif source in _EDITORIAL_SCOPES:
        scope = _EDITORIAL_SCOPES[source]
        if require_body and len(tree.xpath(scope)) != 1:
            raise IngestionFailure("article_scope_ambiguous_or_missing")
        source_kind = "corporate-pr" if corporate else "editorial"
    elif source in _CORPORATE_SCOPES:
        scope = _CORPORATE_SCOPES[source]
        if require_body and len(tree.xpath(scope)) != 1:
            raise IngestionFailure("article_scope_ambiguous_or_missing")
    if selected is not None:
        source_kind = "corporate-pr" if corporate else selected.category
        if selected.body_xpaths:
            matches = [(expression, tree.xpath(expression)) for expression in selected.body_xpaths]
            matches = [(expression, nodes) for expression, nodes in matches if nodes]
            if (not matches or any(len(nodes) != 1 or not isinstance(nodes[0], etree._Element) for _, nodes in matches)
                    or len({id(nodes[0]) for _, nodes in matches}) != 1):
                if require_body:
                    raise IngestionFailure("article_scope_ambiguous_or_missing")
                # This deliberately nonmatching scope makes the retained-byte extraction
                # chain take its explicit alternative path, never an arbitrary body.
                scope = "/*[false()]"
            else:
                scope = matches[0][0]
    return ArticleMeta(title, published, canonical, scope, publisher_name, source_kind)


def _synthetic_url(url, origin):
    parts = urlsplit(url)
    return origin + parts.path + ("?" + parts.query if parts.query else "") if origin else url


def _configured_url(descriptor, url, synthetic_origin, *, discovery=False, surface=None):
    identity = _link(url)
    parts = urlsplit(identity)
    route = parts.path + ("?" + parts.query if parts.query else "")
    origin = f"{parts.scheme}://{parts.netloc}"
    if "#" in url:
        raise IngestionFailure("archive_endpoint_invalid" if discovery else "archive_article_route_invalid")
    if discovery:
        surfaces = [surface] if surface is not None else descriptor.discovery
        valid = any(origin in ([synthetic_origin] if synthetic_origin else entry.origins)
                    and any(re.fullmatch(pattern, route) for pattern in entry.routes) for entry in surfaces)
    else:
        valid = (origin == synthetic_origin if synthetic_origin else
                 parts.scheme == "https" and parts.netloc in descriptor.article_hosts)
        if not valid:
            raise IngestionFailure("archive_article_host_invalid")
        valid = (any(re.fullmatch(pattern, route) for pattern in descriptor.article_routes)
                 and not any(re.fullmatch(pattern, route) for pattern in descriptor.excluded_routes))
    if not valid:
        raise IngestionFailure("archive_endpoint_invalid" if discovery else "archive_article_route_invalid")
    return identity


def _configured_task(source, index, kind, url, first, last):
    key = hashlib.sha256(f"{index}\n{kind}\n{url}\n{first}\n{last}".encode()).hexdigest()
    return ArchiveTask(f"{source}:{key}", url, f"configured:{index}:{kind}", first, last)


def _configured_listing(descriptor, task, raw, final_url, synthetic_origin):
    _raw(raw)
    _window(task.from_day, task.through_day)
    try:
        marker, index, kind = task.kind.split(":")
        if marker != "configured" or not index.isdigit():
            raise ValueError
        surface = descriptor.discovery[int(index)]
        if kind != surface.kind:
            raise ValueError
    except (ValueError, IndexError):
        raise IngestionFailure("archive_task_invalid") from None
    requested = _configured_url(descriptor, task.url, synthetic_origin, discovery=True, surface=surface)
    final = _configured_url(descriptor, final_url, synthetic_origin, discovery=True, surface=surface)
    if task != _configured_task(descriptor.source_id, int(index), kind, requested, task.from_day, task.through_day):
        raise IngestionFailure("archive_task_invalid")
    # Redirect origins may be declared, but a discovery response cannot change its query/partition.
    if (urlsplit(final).path, urlsplit(final).query) != (urlsplit(requested).path, urlsplit(requested).query):
        raise IngestionFailure("archive_task_invalid")
    candidates, following = {}, {}

    def candidate(url, title=None, hint=None):
        absolute = urljoin(final, url)
        try:
            identity = _configured_url(descriptor, absolute, synthetic_origin)
        except IngestionFailure as exc:
            if exc.code in {"archive_article_route_invalid", "archive_article_host_invalid"}:
                return
            raise
        candidates.setdefault(identity, Candidate(identity, _optional_text(title, "archive_listing_invalid"), None, None, hint))

    def continuation(url):
        identity = _configured_url(descriptor, urljoin(final, url), synthetic_origin, discovery=True, surface=surface)
        if identity != requested:
            following[identity] = _configured_task(descriptor.source_id, int(index), kind, identity,
                                                   task.from_day, task.through_day)

    saturated = surface.coverage != "finite-index"
    if kind == "listing":
        try:
            tree = html.document_fromstring(raw.decode("utf-8"), parser=html.HTMLParser(no_network=True))
        except (ValueError, UnicodeError, etree.ParserError):
            raise IngestionFailure("archive_html_invalid") from None
        nodes = tree.xpath(surface.links_xpath)
        if len(nodes) > MAX_SITEMAP_URLS:
            raise IngestionFailure("archive_listing_limit")
        for node in nodes:
            if not isinstance(node, etree._Element) or not node.get("href"):
                raise IngestionFailure("archive_listing_invalid")
            title = " ".join(" ".join(node.itertext()).split()) or None
            candidate(node.get("href"), title)
        links = tree.xpath(surface.next_xpath)
        if len(set(links)) > 1:
            raise IngestionFailure("archive_listing_ambiguous")
        for url in links:
            continuation(url)
        saturated = (not following and surface.coverage == "unverified-pagination") or len(nodes) == MAX_SITEMAP_URLS
    else:
        root = _xml_root(raw)
        ns = "{" + SITEMAP_NS + "}"
        atom = "{http://www.w3.org/2005/Atom}"
        if kind == "sitemap":
            if root.tag not in {ns + "sitemapindex", ns + "urlset"}:
                raise IngestionFailure("archive_xml_invalid")
            is_index = root.tag == ns + "sitemapindex"
            tag = ns + ("sitemap" if is_index else "url")
            entries = root.findall(tag)
            if any(isinstance(node.tag, str) and node.tag != tag for node in root):
                raise IngestionFailure("archive_xml_invalid")
            if len(entries) > MAX_SITEMAP_URLS:
                raise IngestionFailure("archive_listing_limit")
            # Lastmod only orders acquisition. It never supplies publication metadata.
            entries.sort(key=lambda entry: _xml_text(entry, ns + "lastmod") or "", reverse=True)
            for entry in entries:
                location = _xml_text(entry, ns + "loc", required=True)
                if is_index:
                    continuation(location)
                else:
                    candidate(location, hint=_date_hint(_xml_text(entry, ns + "lastmod")))
            saturated = len(entries) == MAX_SITEMAP_URLS
        elif root.tag == atom + "feed":
            entries = root.findall(atom + "entry")
            if len(entries) > 1000:
                raise IngestionFailure("archive_listing_limit")
            for entry in entries:
                links = [node.get("href") for node in entry.findall(atom + "link")
                         if node.get("rel", "alternate") == "alternate" and node.get("type") in {None, "text/html"}]
                if len(links) != 1 or not links[0]:
                    raise IngestionFailure("archive_xml_invalid")
                candidate(links[0], _xml_text(entry, atom + "title"),
                          _date_hint(_xml_text(entry, atom + "published")))
            for node in root.findall(atom + "link"):
                if node.get("rel") == "next":
                    continuation(node.get("href"))
        elif root.tag == "rss" and root.get("version") == "2.0":
            channels = root.findall("channel")
            if len(channels) != 1:
                raise IngestionFailure("archive_xml_invalid")
            entries = channels[0].findall("item")
            if len(entries) > 1000:
                raise IngestionFailure("archive_listing_limit")
            for entry in entries:
                candidate(_xml_text(entry, "link", required=True), _xml_text(entry, "title"),
                          _date_hint(_xml_text(entry, "pubDate"), rss=True))
            for node in channels[0].findall(atom + "link"):
                if node.get("rel") == "next":
                    continuation(node.get("href"))
        else:
            raise IngestionFailure("archive_xml_invalid")
    return Listing(tuple(candidates.values()), tuple(following.values()), saturated)


def _configured_publication(tree, descriptor):
    nodes = tree.xpath(descriptor.publication_xpath)
    if not nodes:
        return None
    values = []
    for node in nodes:
        value = " ".join(("".join(node.itertext()) if isinstance(node, etree._Element) else str(node)).split())
        value = re.sub(r"^(?:Published|Updated)\s+", "", value)
        try:
            values.append(_publication(value))
            continue
        except IngestionFailure:
            pass
        for pattern in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%Y.%m.%d", "%Y-%m-%d"):
            try:
                values.append(datetime.strptime(value, pattern).date().isoformat())
                break
            except ValueError:
                continue
        else:
            raise IngestionFailure("article_date_invalid")
    return _one(values, "article_date_conflict")


def validate_article_url(source, url, *, synthetic_origin=None, descriptor=None):
    selected = _descriptor(source, descriptor)
    if selected is not None:
        return _configured_url(selected, url, synthetic_origin)
    if source == "hankyung-daily":
        return _hankyung_article(url, synthetic_origin)
    if source in _EDITORIAL:
        return _editorial_article(source, url, synthetic_origin)
    if source in _CORPORATE:
        return _corporate_article(source, url, synthetic_origin)
    return _link(url)


def markdown_publication(source: str, text: str) -> str | None:
    """Recognize only source-specific publication headers in the new representation.

    No dates from discovery/old HTML are transferred to provider Markdown. Bare
    dates in prose, modified dates and sitemap hints never become publication.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()][:8]
    if source not in {"openai-newsroom", "anthropic-newsroom"}:
        return None
    matches = []
    for index, line in enumerate(lines):
        if source == "anthropic-newsroom":
            if not line.startswith("Published "):
                continue
            value = line.removeprefix("Published ")
        else:
            value = line
            # OpenAI places the bare publication day directly adjacent to its H1.
            if not any(0 <= other < len(lines) and lines[other].startswith("# ") for other in (index - 1, index + 1)):
                continue
        for pattern in ("%B %d, %Y", "%b %d, %Y"):
            try:
                matches.append(datetime.strptime(value, pattern).date().isoformat())
                break
            except ValueError:
                continue
    return _one(matches, "article_date_conflict")
