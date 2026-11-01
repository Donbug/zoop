#!/usr/bin/env python3
"""Installed-CLI synthetic acquisition and offline retained-public-surface inspection.

Default/--families use authored loopback bodies. --retained-source never fetches:
it inspects an existing raw capture and reports metadata/hash evidence, not prose.
No model call, provider call, native grant or ingestion export is created.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE), str(PIPELINE / "src")]

from scripts.collection_smoke import LocalSite, PROXY_ENV  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import byte_hash  # noqa: E402
from zoop_ai_pipeline.ingestion_parsers import prepare  # noqa: E402
from zoop_ai_pipeline import news_archives as archives  # noqa: E402
from zoop_ai_pipeline.news_sources import descriptor, source_descriptor, surface  # noqa: E402
from zoop_ai_pipeline.private_intake import Config, retained_items  # noqa: E402

PRIVATE = "SYNTHETIC_PRIVATE_NEWS_BODY_MARKER"


def config_data(root, origin, **overrides):
    return {"schemaVersion": "zoop-private-news-config-1", "planId": "synthetic-private-news",
            "stateDir": str(root / "private-state"), "fromDay": "2026-07-25", "throughDay": "2026-07-27",
            "operatorApprovalRef": "synthetic-authored-local-fixture-only",
            "sources": [{"name": "hankyung-daily", "sourceType": "editorial",
                         "reliability": "synthetic-not-real-news", "queries": []}],
            "exactArticleHosts": ["127.0.0.1"], "maxListingPages": 3, "maxCandidates": 20,
            "maxDocuments": 3, "maxArticleAttempts": 20, "perDayCap": 1, "companyAliases": ["SyntheticCo"],
            "syntheticBaseUrl": origin,
            "policy": {"schemaVersion": "zoop-collection-policy-1", "userAgent": "ZoopSyntheticPrivateNews/1.0",
                       "timeoutSeconds": 10, "maxTotalSeconds": 120, "maxRedirects": 2, "maxRequests": 30,
                       "maxResponseBytes": 100_000, "maxTotalBytes": 1_000_000,
                       "minIntervalSeconds": 0, "allowedMediaTypes": ["text/html"], "syntheticLoopback": True}, **overrides}


def article(day, *, extra="", canonical="/not-fetched-canonical"):
    return (f'<html><head><title>SyntheticCo {day}</title><meta property="article:published_time" '
            f'content="{day}T12:34:56+09:00"><link rel="canonical" href="{canonical}">{extra}</head>'
            f'<body><nav>NOT ARTICLE</nav><article><div id="articletxt"><p>{PRIVATE} SyntheticCo '
            f'authored &amp; exact <b>text</b> {day}.</p><p>Second paragraph.</p></div></article></body></html>').encode()


def sitemap(urls):
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
        f'<url><loc>{url}</loc><lastmod>2026-10-25</lastmod></url>' for url in urls) + '</urlset>').encode()


def cli(config, command, *, expected=0):
    executable = Path(sys.executable).parent / "zoop-ai-private-news"
    if not executable.is_file():
        found = shutil.which("zoop-ai-private-news")
        assert found, "Install the frozen local project console entry before this smoke"
        executable = Path(found)
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(Path.home()),
           "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(PIPELINE / "src"), **PROXY_ENV}
    child = subprocess.run([str(executable), command, "--config", str(config)], cwd=PIPELINE,
                           capture_output=True, env=env, timeout=150)
    assert child.returncode == expected, (child.returncode, child.stdout, child.stderr)
    assert PRIVATE.encode() not in child.stdout + child.stderr
    result = json.loads(child.stdout)
    assert b'SyntheticCo' not in child.stdout, child.stdout
    return result


def smoke(root):
    site = LocalSite()
    try:
        site.route("/robots.txt", b"User-agent: *\nDisallow: /denied\n", content_type="text/plain")
        bodies = {}
        for index, day in enumerate(("2026-07-25", "2026-07-26", "2026-07-27"), 1):
            url = site.url(f"/article/a{index}")
            site.route(f"/sitemap/daily-article/{day.replace('-', '')}.xml", sitemap([url]), content_type="application/xml")
            bodies[url] = article(day)
            site.route(f"/article/a{index}", bodies[url])
        config = root / "config.json"
        values = config_data(root, site.url(""))
        config.write_text(json.dumps(values))
        first = cli(config, "run")
        assert first["state"] == "completed" and first["coverage"] == "all", first
        assert first["retainedInWindow"] == 3 and len(first["dayCounts"]) == 3
        assert first["provenance"] == "synthetic-loopback"
        assert first["sourceRequests"] == len(site.log) == 7
        expected_bytes = sum(len(site.routes[entry["path"].split('?')[0]]["body"]) for entry in site.log)
        assert first["sourceBytes"] == expected_bytes
        assert first["rights"] == "unconfirmed" and first["modelSend"] is False and first["publicUse"] is False
        state = Path(values["stateDir"])
        assert stat.S_IMODE(state.stat().st_mode) == 0o700
        records = sorted(state.glob("private-news-*.json"))
        assert len(records) == 3
        for path in records:
            record = json.loads(path.read_bytes())
            raw = path.with_suffix(".raw").read_bytes()
            assert raw == bodies[record["requestUrl"]]
            assert record["rawSha256"] == byte_hash(raw)
            assert record["prepared"] == prepare(raw, "text/html", "//div[@id='articletxt']")
            assert "NOT ARTICLE" not in record["prepared"]["text"]
            assert record["canonicalUrl"] == site.url("/not-fetched-canonical")
            for segment in record["prepared"]["segments"]:
                source = record["prepared"]["sources"][segment["sourceIndex"]]
                assert record["prepared"]["text"][segment["cleanStart"]:segment["cleanEnd"]] == source["text"][segment["sourceStart"]:segment["sourceEnd"]]
        before = {p.name: p.read_bytes() for p in state.iterdir() if p.name != ".lock"}
        request_count = len(site.log)
        assert cli(config, "resume")["sourceRequests"] == request_count
        assert cli(config, "status")["retainedInWindow"] == 3
        assert len(site.log) == request_count
        assert before == {p.name: p.read_bytes() for p in state.iterdir() if p.name != ".lock"}
        changed = root / "changed.json"
        changed.write_text(json.dumps({**values, "maxDocuments": 2}))
        assert cli(changed, "resume", expected=2)["error"]["code"] == "private_plan_conflict"
        assert len(site.log) == request_count
        assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in state.iterdir())
        assert not any(p.is_dir() or p.name.startswith(("doc-", "ev-", "job-")) for p in state.iterdir())
        assert not any(entry["path"] == "/not-fetched-canonical" for entry in site.log)
        assert all(not {"authorization", "cookie", "proxy-authorization"} & set(entry["headers"]) for entry in site.log)
        return {"status": "passed", "provenance": "synthetic-loopback", "sourceRequests": request_count,
                "sourceBytes": expected_bytes, "retainedInWindow": 3, "externalCalls": 0, "modelCalls": 0,
                "checks": ["installed console entry", "discovery before date-balanced bodies", "exact raw/text mappings",
                           "0700/0600 namespace", "immutable plan conflict", "offline resume and status",
                           "content-free stdout", "no native records or grants", "canonical observation not fetched"]}
    finally:
        site.close()


def family_smoke(root):
    reports = []
    for family in ("rss", "atom", "sitemap", "listing"):
        folder = root / family
        folder.mkdir()
        site = LocalSite()
        try:
            site.route("/robots.txt", b"User-agent: *\nAllow: /\n", content_type="text/plain")
            kind = "feed" if family in {"rss", "atom"} else family
            source = descriptor("synthetic-" + family, "editorial",
                                [surface(kind, "https://publisher.example/discovery",
                                         routes=[r"/discovery(?:/2)?"],
                                         coverage="rolling" if kind == "feed" else "finite-index")],
                                ["publisher.example"], [r"/article/[12]"], bodies=["//*[@id='articletxt']"])
            urls = [site.url("/article/1"), site.url("/article/2")]
            for url in urls:
                site.route(url.removeprefix(site.url("")), article("2026-07-27"))
            if family == "rss":
                raw = ('<rss version="2.0"><channel>' + ''.join(
                    f"<item><link>{url}</link><pubDate>Mon, 27 Jul 2026 12:00:00 GMT</pubDate></item>" for url in urls)
                    + '</channel></rss>').encode()
            elif family == "atom":
                raw = ('<feed xmlns="http://www.w3.org/2005/Atom">' + ''.join(
                    f'<entry><link href="{url}"/><published>2026-07-27</published></entry>' for url in urls) + '</feed>').encode()
            elif family == "sitemap":
                raw = (f'<sitemapindex xmlns="{archives.SITEMAP_NS}"><sitemap>'
                       f'<loc>{site.url("/discovery/2")}</loc></sitemap></sitemapindex>').encode()
                site.route("/discovery/2", sitemap(urls), content_type="application/xml")
            else:
                raw = f'<html><main><a href="{urls[0]}">Authored first</a><a rel="next" href="/discovery/2">Next</a></main></html>'.encode()
                site.route("/discovery/2", f'<html><main><a href="{urls[1]}">Authored second</a></main></html>'.encode())
            site.route("/discovery", raw, content_type="text/html" if family == "listing" else "application/xml")
            values = config_data(folder, site.url(""))
            for key in ("maxListingPages", "maxCandidates", "maxDocuments", "maxArticleAttempts", "perDayCap"):
                values.pop(key)
            values.update(schemaVersion="zoop-private-news-config-2",
                          sources=[{"name": source.source_id, "sourceType": "editorial",
                                    "reliability": "authored fixture", "queries": [], "descriptor": source.wire()}])
            config = folder / "config.json"
            config.write_text(json.dumps(values))
            result = cli(config, "run", expected=2 if kind == "feed" else 0)
            assert result["retainedInWindow"] == 2 and result["pendingCandidates"] == 0
            assert result["stopCode"] is None
            assert len(list(retained_items(Config.model_validate(values)))) == 2
            before = len(site.log)
            assert cli(config, "status", expected=2 if kind == "feed" else 0)["sourceRequests"] == before
            assert len(site.log) == before
            reports.append({"family": family, "state": result["state"], "retained": 2, "requests": before,
                            "coverage": result["coverage"], "externalCalls": 0, "modelCalls": 0})
        finally:
            site.close()
    return {"status": "passed", "families": reports}


def retained_surface(args):
    raw = args.raw.read_bytes()
    # Reader raw captures carry this known metadata preamble; the original capture
    # remains untouched and its full-byte hash is reported separately.
    capture_hash = byte_hash(raw)
    if raw.startswith(("URL: " + args.url + "\n").encode()):
        header, separator, body = raw.partition(b"\n---\n\n")
        if not separator or len(header) > 1000:
            raise ValueError("invalid reader raw capture")
        raw = body
    source = args.retained_source
    if args.kind == "article":
        meta = archives.article_metadata(source, raw, args.url)
        prepared = prepare(raw, "text/html", meta.article_xpath)
        return {"sourceId": source, "kind": "article", "captureSha256": capture_hash,
                "rawSha256": byte_hash(raw), "publication": meta.published_at, "publisher": meta.publisher,
                "articleXPath": meta.article_xpath, "textSha256": byte_hash(prepared["text"].encode()),
                "textCharacters": len(prepared["text"]), "externalCalls": 0}
    configured = source_descriptor(source)
    if configured is not None:
        entry = configured.discovery[args.surface]
        selected = archives._configured_task(source, args.surface, entry.kind, args.url, args.from_day, args.through_day)
    else:
        selected = next(item for item in archives.initial_tasks(source, args.from_day, args.through_day) if item.url == args.url)
    listing = archives.parse_listing(source, selected, raw, args.url)
    return {"sourceId": source, "kind": "discovery", "captureSha256": capture_hash, "rawSha256": byte_hash(raw),
            "candidates": len(listing.candidates), "nextTasks": len(listing.next_tasks),
            "saturated": listing.saturated, "externalCalls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", action="store_true")
    parser.add_argument("--retained-source")
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--url")
    parser.add_argument("--kind", choices=("article", "discovery"), default="article")
    parser.add_argument("--surface", type=int, default=0)
    parser.add_argument("--from-day", default="2026-07-28")
    parser.add_argument("--through-day", default="2026-10-28")
    args = parser.parse_args()
    if args.retained_source:
        if args.raw is None or args.url is None:
            parser.error("--retained-source requires --raw and --url")
        print(json.dumps(retained_surface(args), sort_keys=True))
    else:
        with tempfile.TemporaryDirectory(prefix="zoop-private-news-synthetic-") as temporary:
            print(json.dumps((family_smoke if args.families else smoke)(Path(temporary).resolve()), sort_keys=True))
