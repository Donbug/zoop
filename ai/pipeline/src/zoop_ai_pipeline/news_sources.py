"""Declared discovery surfaces, never access grants or publisher-license assertions.

A descriptor names exact origins and route patterns before transport. A matching
route is only a candidate; metadata, access and one-body checks still apply.
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from lxml import etree
from pydantic import ConfigDict, Field, model_validator

from .ingestion_contracts import Wire


class DiscoverySurface(Wire):
    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["feed", "sitemap", "listing"]
    url: str = Field(min_length=1, max_length=4000)
    origins: list[str] = Field(min_length=1, max_length=16)
    routes: list[str] = Field(min_length=1, max_length=32)
    links_xpath: str = "//main//a[@href]"
    next_xpath: str = "//a[@rel='next']/@href | //link[@rel='next']/@href"
    coverage: Literal["rolling", "finite-index", "unverified-pagination"] = "rolling"

    @model_validator(mode="after")
    def checked(self):
        for origin in self.origins:
            parts = urlsplit(origin)
            if (parts.scheme != "https" or not parts.hostname or parts.netloc != parts.hostname
                    or origin != f"https://{parts.hostname}"):
                raise ValueError("exact HTTPS discovery origin required")
        parts = urlsplit(self.url)
        if f"{parts.scheme}://{parts.netloc}" not in self.origins or parts.fragment:
            raise ValueError("discovery URL outside declared origins")
        for route in self.routes:
            re.compile(route)
        if not any(re.fullmatch(route, parts.path + ("?" + parts.query if parts.query else "")) for route in self.routes):
            raise ValueError("initial discovery URL outside declared routes")
        etree.XPath(self.links_xpath)
        etree.XPath(self.next_xpath)
        return self


class SourceDescriptor(Wire):
    model_config = ConfigDict(populate_by_name=True)
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    category: Literal["editorial", "corporate-pr", "government"]
    discovery: list[DiscoverySurface] = Field(min_length=1, max_length=32)
    article_hosts: list[str] = Field(min_length=1, max_length=16)
    article_routes: list[str] = Field(min_length=1, max_length=32)
    excluded_routes: list[str] = Field(default_factory=list, max_length=32)
    body_xpaths: list[str] = Field(default_factory=list, max_length=16)
    publication_meta: list[str] = Field(default_factory=lambda: ["article:published_time"], max_length=16)
    publication_xpath: str | None = None
    publication_policy: Literal["declared", "visible-day"] = "declared"
    publisher_policy: Literal["article-metadata-only"] = "article-metadata-only"
    body_policy: Literal["single-configured-scope", "native-single-semantic-scope", "native-pdf-intake-required"] = "native-single-semantic-scope"
    evidence_status: str = "configured; live access and body selector unverified"
    access_status: Literal["unassessed", "blocked-policy", "blocked-http"] = "unassessed"
    access_reason: str | None = None

    @model_validator(mode="after")
    def checked(self):
        for host in self.article_hosts:
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or ".." in host:
                raise ValueError("exact lower-case article host required")
        for route in [*self.article_routes, *self.excluded_routes]:
            re.compile(route)
        for expression in self.body_xpaths:
            etree.XPath(expression)
        if self.publication_xpath is not None:
            etree.XPath(self.publication_xpath)
        if self.publication_policy == "visible-day" and self.publication_xpath is None:
            raise ValueError("visible day requires a publication selector")
        if self.body_policy == "single-configured-scope" and not self.body_xpaths:
            raise ValueError("configured body policy requires selectors")
        return self


def surface(kind, url, *, routes=None, origins=None, coverage="rolling", **options):
    parts = urlsplit(url)
    route = parts.path + ("?" + parts.query if parts.query else "")
    return DiscoverySurface(kind=kind, url=url, origins=origins or [f"{parts.scheme}://{parts.netloc}"],
                            routes=routes or [re.escape(route)], coverage=coverage, **options)


def descriptor(source_id, category, discovery, hosts, routes, *, bodies=(), **options):
    return SourceDescriptor(source_id=source_id, category=category, discovery=discovery,
                            article_hosts=hosts, article_routes=routes, body_xpaths=list(bodies),
                            body_policy=options.pop("body_policy", "single-configured-scope" if bodies else "native-single-semantic-scope"), **options)


# Exact publisher endpoints are independent discovery registrations, not alternate
# GDELT identities. A persisted denial on either host is never cleared by this table.
SOURCES = {
    item.source_id: item for item in [
        descriptor("openai-newsroom", "corporate-pr", [
            surface("feed", "https://openai.com/news/rss.xml"),
            surface("sitemap", "https://openai.com/sitemap.xml", routes=[r"/sitemap\.xml(?:/[a-z0-9-]+/)?"], coverage="finite-index"),
        ], ["openai.com"], [r"/index/[^/?]+/?"],
                   bodies=["//main[@id='main']/article//*[@data-toc-content]"],
                   publication_xpath="//main[@id='main']/article//*[@data-article-hero-copy-region='meta']/p",
                   publication_policy="visible-day",
                   evidence_status="retained static HTML selector evidence; direct identifiable-agent request returned403 on2026-10-28"),
        descriptor("anthropic-newsroom", "corporate-pr", [
            surface("listing", "https://www.anthropic.com/news", coverage="unverified-pagination"),
            surface("sitemap", "https://www.anthropic.com/sitemap.xml", coverage="finite-index"),
        ], ["www.anthropic.com"], [r"/(?:news|research|features|institute)/[^/?]+/?"],
                   excluded_routes=[r"/news/(?:announcements|product|features|partnerships|policy)/?"],
                   bodies=["//article//div[starts-with(@class,'Body-') and contains(@class,'__body')]"],
                   publication_xpath="//article/header//time/@datetime", publication_policy="visible-day",
                   evidence_status="static article retained 2026-10-28; visible publication day and one prose scope observed"),
        descriptor("samsung-newsroom", "corporate-pr", [surface("feed", "https://news.samsung.com/kr/feed")],
                   ["news.samsung.com"], [r"/kr/(?!feed(?:/|$))[^/?]+/?"],
                   bodies=["//*[contains(concat(' ',normalize-space(@class),' '),' single_contents ')]"]),
        descriptor("samsung-ir", "corporate-pr", [
            surface("listing", "https://www.samsung.com/global/ir/financial-information/earnings-release/",
                    links_xpath="//a[contains(@href,'/global/ir/docs/') and contains(@href,'.pdf')]",
                    coverage="unverified-pagination")],
                   ["www.samsung.com", "images.samsung.com"], [r"/global/ir/docs/[^/?]+\.pdf"],
                   body_policy="native-pdf-intake-required",
                   evidence_status="PoC index/PDF route ported for discovery; binary text must use native PDF intake, not private HTML records"),
        descriptor("skhynix-newsroom", "corporate-pr", [surface("feed", "https://news.skhynix.com/en/feed/")],
                   ["news.skhynix.com"], [r"/(?:en/)?(?!feed(?:/|$))[^/?]+/?"],
                   bodies=["//*[contains(concat(' ',normalize-space(@class),' '),' post-body ')]//*[contains(concat(' ',normalize-space(@class),' '),' post-contents ')]"]),
        descriptor("nvidia-blog", "corporate-pr", [surface("feed", "https://blogs.nvidia.com/feed/")],
                   ["blogs.nvidia.com"], [r"/blog/[^?]+/?"],
                   bodies=["//*[contains(concat(' ',normalize-space(@class),' '),' entry-content ')]", "//*[@itemprop='articleBody']"]),
        descriptor("fsc-press-releases", "government", [surface("feed", "https://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111")],
                   ["www.fsc.go.kr"], [r"/no010101/[0-9]+(?:\?[^#]*)?"],
                   bodies=["//*[contains(concat(' ',normalize-space(@class),' '),' board-view-wrap ')]//*[contains(concat(' ',normalize-space(@class),' '),' cont ')]"]),
        descriptor("microsoft-newsroom", "corporate-pr", [surface("feed", "https://news.microsoft.com/source/feed/")],
                   ["news.microsoft.com", "blogs.microsoft.com", "techcommunity.microsoft.com", "commandline.microsoft.com"],
                   [r"/source/\d{4}/\d{2}/\d{2}/[^/?]+/?", r"/blog/\d{4}/\d{2}/\d{2}/[^/?]+/?",
                    r"/(?:blogs|t5)/[^?]+", r"/[^/?]+/?"], evidence_status="official current feed observed; article scopes unverified"),
        descriptor("meta-newsroom", "corporate-pr", [surface("feed", "https://about.fb.com/news/feed/")],
                   ["about.fb.com"], [r"/news/\d{4}/\d{2}/[^/?]+/?"], evidence_status="official feed observed; article scope unverified"),
        descriptor("alphabet-newsroom", "corporate-pr", [surface("feed", "https://blog.google/rss/")],
                   ["blog.google"], [r"/(?:products|technology|inside-google|outreach-initiatives|around-the-globe|company-news)/[^?]+/?"],
                   evidence_status="official feed observed; article scope unverified"),
        descriptor("amazon-newsroom", "corporate-pr", [
            surface("listing", "https://press.aboutamazon.com/press-release-archive", coverage="unverified-pagination")],
                   ["press.aboutamazon.com"], [r"/(?:aws/)?\d{4}/\d{1,2}/[^/?]+/?"],
                   publication_meta=["parsely-pub-date", "article:published_time"],
                   evidence_status="official static index observed; article zoned publication metadata observed; body scope unverified"),
        descriptor("arm-newsroom", "corporate-pr", [surface("feed", "https://newsroom.arm.com/feed")],
                   ["newsroom.arm.com"], [r"/(?:blog|news)/[^/?]+/?"], evidence_status="official feed observed; article scope unverified"),
        descriptor("intel-newsroom", "corporate-pr", [
            surface("sitemap", "https://www.intel.com/sitemap.xml", routes=[r"/sitemap(?:_[1-8])?\.xml"], coverage="finite-index")],
                   ["www.intel.com"], [r"/content/www/us/en/newsroom/(?:news|resources)/[^?]+\.html"],
                   evidence_status="official sitemap index observed; child/body scope unverified"),
        descriptor("tsmc-newsroom", "corporate-pr", [
            surface("listing", "https://pr.tsmc.com/english/latest-news", coverage="unverified-pagination"),
            surface("listing", "https://pr.tsmc.com/english/news-archives", coverage="unverified-pagination")],
                   ["pr.tsmc.com"], [r"/english/news/[0-9]+/?"], evidence_status="official static latest/archive routes observed; body scope unverified"),
        descriptor("sk-telecom-newsroom", "corporate-pr", [surface("feed", "https://news.sktelecom.com/feed/")],
                   ["news.sktelecom.com"], [r"/[0-9]+/?"], evidence_status="official feed observed; publication must come from article, not UTC feed day"),
        descriptor("micron-newsroom", "corporate-pr", [
            surface("listing", "https://www.micron.com/about/press/news", links_xpath="//a[@href]", coverage="unverified-pagination")],
                   ["investors.micron.com"], [r"/news/press-release/[0-9]{4}/[^/?]+/default\.aspx"],
                   evidence_status="official listing and investor article routes observed; distributed newswire provenance; body scope unverified"),
        descriptor("kakao-newsroom", "corporate-pr", [
            surface("sitemap", "https://www.kakaocorp.com/page/sitemap.xml", coverage="finite-index"),
            surface("listing", "https://www.kakaocorp.com/page/presskit/press-release", links_xpath="//a[@href]", coverage="unverified-pagination")],
                   ["www.kakaocorp.com"], [r"/page/presskit/[^?]+"], excluded_routes=[r"/page/presskit/press-release/?"],
                   evidence_status="official sitemap namespace observed; SPA article/date/body rendering unverified"),
        descriptor("lg-cns-newsroom", "corporate-pr", [
            surface("sitemap", "https://www.lgcns.com/content/lgcns.sitemap.kr-sitemap.xml", coverage="finite-index"),
            surface("listing", "https://www.lgcns.com/kr/newsroom/press", links_xpath="//a[@href]", coverage="unverified-pagination")],
                   ["www.lgcns.com"], [r"/kr/newsroom/press/detail(?:\?[^#]+)?"],
                   evidence_status="official sitemap/detail route observed; article publication metadata unverified"),
        descriptor("samsung-sds-newsroom", "corporate-pr", [
            surface("listing", "https://www.samsungsds.com/us/news/index.html", links_xpath="//a[@href]", coverage="unverified-pagination"),
            surface("listing", "https://www.samsungsds.com/kr/news/index.html", links_xpath="//a[@href]", coverage="unverified-pagination")],
                   ["www.samsungsds.com"], [r"/(?:us|kr)/news/(?!index\.html)[A-Za-z0-9_-]+\.html"],
                   evidence_status="official first-page listing observed; Load more continuation unverified; error-page redirects are not articles"),
        descriptor("db-hitek-newsroom", "corporate-pr", [
            surface("listing", "https://dbhitek.com/kr/media/news/list", links_xpath="//a[@href]", coverage="unverified-pagination")],
                   ["dbhitek.com"], [r"/kr/media/news/view/[0-9]+/?"],
                   evidence_status="publisher canonical .com host and dated board observed; legacy .co.kr TLS mismatch is not bypassed"),
        descriptor("broadcom-newsroom", "corporate-pr", [
            surface("sitemap", "https://www.broadcom.com/company/sitemap.xml", coverage="finite-index")],
                   ["www.broadcom.com"], [r"/company/news/(?:[a-z-]+/)?articles/[^/?]+/[^/?]+/?"],
                   evidence_status="official corporate article sitemap observed; publication/body scope unverified; investor-host403 remains separate"),
        descriptor("cnbc", "editorial", [
            surface("sitemap", "https://www.cnbc.com/sitemap_news.xml", coverage="finite-index"),
            surface("sitemap", "https://www.cnbc.com/sitemapAll.xml", routes=[r"/sitemap[^?]*\.xml"], coverage="finite-index")],
                   ["www.cnbc.com"], [r"/\d{4}/\d{2}/\d{2}/[^/?]+\.html"]),
        descriptor("france24", "editorial", [
            surface("sitemap", "https://www.france24.com/sitemaps/en/news.xml", coverage="finite-index"),
            surface("sitemap", "https://www.france24.com/sitemaps/en/index.xml", routes=[r"/sitemaps/en/[^?]+\.xml"], coverage="finite-index")],
                   ["www.france24.com"], [r"/en/(?:[^/?]+/)?\d{8}-[^/?]+/?"]),
        descriptor("techcrunch", "editorial", [
            surface("feed", "https://techcrunch.com/feed/"),
            surface("sitemap", "https://techcrunch.com/sitemap.xml", routes=[r"/[^/?]*sitemap[^/?]*\.xml"], coverage="finite-index")],
                   ["techcrunch.com"], [r"/\d{4}/\d{2}/\d{2}/[^/?]+/?"]),
        descriptor("arstechnica", "editorial", [
            surface("sitemap", "https://arstechnica.com/sitemap.xml", routes=[r"/(?:[^?]*/)?[^/?]*sitemap[^/?]*\.xml"], coverage="finite-index")],
                   ["arstechnica.com"], [r"/[^/?]+/\d{4}/\d{2}/[^/?]+/?"]),
        descriptor("tomshardware", "editorial", [
            surface("sitemap", "https://www.tomshardware.com/sitemap-news.xml", coverage="finite-index"),
            surface("sitemap", "https://www.tomshardware.com/sitemap.xml", routes=[r"/sitemap[^?]*(?:\.xml|/[^?]+)"], coverage="finite-index")],
                   ["www.tomshardware.com"], [r"/(?:news|pc-components|tech-industry|software|pc-hardware|video-games|laptops|desktops|monitors|networking)/[^?]+"]),
        descriptor("business-standard", "editorial", [
            surface("sitemap", "https://www.business-standard.com/sitemap/news-sitemap.xml", coverage="finite-index"),
            surface("sitemap", "https://www.business-standard.com/sitemap/sitemap-index.xml", routes=[r"/sitemap/[^?]+\.xml"], coverage="finite-index")],
                   ["www.business-standard.com"], [r"/[^?]+-[0-9]+_1\.html"]),
        descriptor("channelnewsasia", "editorial", [
            surface("feed", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml"),
            surface("sitemap", "https://www.channelnewsasia.com/api/v1/sitemap-news-feed?_format=xml", coverage="finite-index")],
                   ["www.channelnewsasia.com"], [r"/[^/?]+/[^/?]+-[0-9]+"], evidence_status="official feed observed; robots Crawl-delay 10 applies"),
        descriptor("reuters", "editorial", [
            surface("sitemap", "https://www.reuters.com/arc/outboundfeeds/news-sitemap-index/?outputType=xml", coverage="finite-index")],
                   ["www.reuters.com"], [r"/[^?]+-\d{4}-\d{2}-\d{2}/?"], access_status="blocked-policy",
                   access_reason="robots wildcard denial and explicit automated-collection restriction observed"),
        descriptor("bbc", "editorial", [
            surface("sitemap", "https://www.bbc.com/sitemaps/https-index-com-news.xml", coverage="finite-index")],
                   ["www.bbc.com"], [r"/news/[^?]+"], access_status="blocked-policy",
                   access_reason="explicit automated extraction and AI/RAG prohibition observed"),
        descriptor("dw", "editorial", [surface("sitemap", "https://www.dw.com/sitemap.xml", coverage="finite-index")],
                   ["www.dw.com"], [r"/[a-z-]+/[^/?]+/a-[0-9]+"], access_status="blocked-policy",
                   access_reason="explicit automated mining/scraping permission requirement observed"),
        descriptor("aljazeera", "editorial", [surface("sitemap", "https://www.aljazeera.com/news-sitemap.xml", coverage="finite-index")],
                   ["www.aljazeera.com"], [r"/(?:news|economy|features)/\d{4}/\d{1,2}/\d{1,2}/[^/?]+"],
                   access_status="blocked-policy", access_reason="automated-mining permission restriction observed"),
        descriptor("theverge", "editorial", [surface("feed", "https://www.theverge.com/rss/index.xml")],
                   ["www.theverge.com"], [r"/[^/?]+/[0-9]+/[^/?]+"], access_status="blocked-policy",
                   access_reason="robots wildcard denial observed; no alternate bot identity"),
        descriptor("zdnet", "editorial", [surface("sitemap", "https://www.zdnet.com/sitemaps/news/index.xml", coverage="finite-index")],
                   ["www.zdnet.com"], [r"/article/[^/?]+/?"], access_status="blocked-policy",
                   access_reason="explicit automated extraction/AI permission requirement observed"),
    ]
}


def source_descriptor(source_id: str) -> SourceDescriptor | None:
    return SOURCES.get(source_id)


def source_descriptors() -> tuple[SourceDescriptor, ...]:
    return tuple(SOURCES[key] for key in sorted(SOURCES))


UNSUPPORTED = (
    ("yahoo-finance", "editorial", "finance.yahoo.com", "news-discovery-unverified; declared sitemap covers quotes, not news"),
    ("timesofindia", "editorial", "timesofindia.indiatimes.com", "news-discovery-unverified; advertised feed paths denied by robots"),
    ("theregister", "editorial", "www.theregister.com", "blocked-policy; robots default-deny, no permitted discovery route"),
    ("asml-newsroom", "corporate-pr", "www.asml.com", "investor-host HTTP403 observed; alternate newsroom discovery unverified"),
    ("hanmi-newsroom", "corporate-pr", "hanmisemi.com", "no press-release channel found in inspected publisher boards; DART/domestic press remain distinct sources"),
)


def source_catalog() -> tuple[dict, ...]:
    """Full private-source capability matrix; configured never means live verified."""
    # Imported lazily to keep descriptor validation independent of adapter dispatch.
    from . import news_archives as archives
    rows = []
    for source_id in ("hankyung-daily", "etnews-ai", "fnnews-sitemaps", "nvidia-newsroom",
                      "amd-newsroom", "naver-press", "apple-newsroom"):
        category = "editorial" if source_id in {"hankyung-daily", "etnews-ai", "fnnews-sitemaps"} else "corporate-pr"
        origin = archives._ORIGINS[source_id]
        routes = {
            "hankyung-daily": [r"/article/[A-Za-z0-9]+"],
            "etnews-ai": [r"/[0-9]{14}"], "fnnews-sitemaps": [r"/news/[0-9]{18}"],
            "nvidia-newsroom": [r"/news/[A-Za-z0-9][A-Za-z0-9-]*/?"],
            "amd-newsroom": [r"/news/[A-Za-z0-9][A-Za-z0-9-]*/?"],
            "naver-press": [r"/en/media/pressReleasesDetail\?seq=[0-9]{1,20}"],
            "apple-newsroom": [r"/newsroom/[0-9]{4}/(?:0[1-9]|1[0-2])/[A-Za-z0-9][A-Za-z0-9-]*/?"],
        }
        templates = {
            "hankyung-daily": [("sitemap", "/sitemap/daily-article/{YYYYMMDD}.xml")],
            "etnews-ai": [("listing", "/news/category_list.html?id=2958&page={page}")],
            "fnnews-sitemaps": [("sitemap", "/resource/view_xml/sitemap_index/news-sitemap-index-{YYYY}.xml")],
            "naver-press": [("listing", "/en/media/pressReleases?keyword=&year={YYYY}&month={month}")],
        }
        discovery = [{"kind": kind, "urlTemplate": origin + route, "origins": [origin]}
                     for kind, route in templates.get(source_id, [])]
        discovery.extend({"kind": "feed" if kind == "rss-xml" else "sitemap", "url": origin + route, "origins": [origin]}
                         for route, kind in archives._CORPORATE_ROUTES.get(source_id, ()))
        scope = (archives._HK_SCOPE if source_id == "hankyung-daily" else
                 archives._EDITORIAL_SCOPES.get(source_id) or archives._CORPORATE_SCOPES[source_id])
        rows.append({"sourceId": source_id, "category": category, "adapter": "native-archive",
                     "articleHosts": list(archives.source_hosts(source_id)), "articleRoutes": routes[source_id],
                     "discovery": discovery, "bodyPolicy": "single-configured-scope", "bodyXpaths": [scope],
                     "publicationPolicy": "visible-day" if source_id in archives._VISIBLE_DATES else "declared",
                     "publicationXpath": archives._VISIBLE_DATES.get(source_id),
                     "publicationMeta": [] if source_id in archives._VISIBLE_DATES else ["article:published_time", "schema.datePublished"],
                     "publisherPolicy": "article-metadata-with-original-editorial-publisher" if source_id in archives._EDITORIAL else "article-metadata-only",
                     "discoveryStatus": "implemented", "bodyStatus": "previously-retained",
                     "rights": "unconfirmed", "publicUse": False})
    for item in source_descriptors():
        rows.append({**item.wire(), "adapter": "configured", "discoveryStatus": item.access_status,
                     "bodyStatus": "native-pdf-intake-required" if item.body_policy == "native-pdf-intake-required" else "configured-not-live-verified",
                     "rights": "unconfirmed", "publicUse": False})
        if item.source_id == "openai-newsroom":
            rows[-1].update(discoveryAccessStatus="observed-public-response",
                            bodyAccessStatus="observed-http403",
                            bodyAccessReason="https://openai.com/index/mixi/ returned403 to ZoopSourceAdapterResearch/1.0 on2026-10-28; one article, not a whole-source denial")
        elif item.source_id == "anthropic-newsroom":
            rows[-1].update(discoveryAccessStatus="observed-public-response", bodyAccessStatus="observed-http200",
                            bodyAccessReason="https://www.anthropic.com/news/s1-sec static response retained on2026-10-28")
    rows.extend({"sourceId": identifier, "category": category, "articleHosts": [host],
                 "adapter": "unsupported", "discoveryStatus": "unsupported-or-blocked", "reason": reason,
                 "rights": "unconfirmed", "publicUse": False} for identifier, category, host, reason in UNSUPPORTED)
    rows.append({"sourceId": "gdelt-doc", "category": "discovery", "articleHosts": [],
                 "adapter": "native-archive", "discoveryStatus": "blocked-provider-429",
                 "reason": "existing provider denial remains; no automatic retry or alternate identity"})
    return tuple(rows)
