#!/usr/bin/env python3
"""Observe publisher publication declarations; never infer clocks from search dates or article text."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from briefing_replay import ReplayError, canonical, digest, now, private_dir, regular, save_json, strict_load, write_once

META_KEYS = {"article:published_time", "datepublished", "pubdate", "publish_date", "publication_date"}
ARTICLE_TYPES = {"Article", "NewsArticle", "BlogPosting", "Report", "TechArticle", "PressRelease"}
MEANING = "Current publisher date declaration observed; unchanged historical body unproven"


def aware(value):
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except ValueError:
        return None


def same_page(left, right):
    a, b = urllib.parse.urlsplit(left), urllib.parse.urlsplit(right)
    return (a.hostname or "").removeprefix("www.").lower() == (b.hostname or "").removeprefix("www.").lower() \
        and urllib.parse.unquote(a.path).rstrip("/") == urllib.parse.unquote(b.path).rstrip("/") and a.query == b.query


class PublicationParser(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.declarations, self.script, self.parts = url, [], False, []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): v for k, v in attrs if v is not None}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key in META_KEYS and a.get("content"):
                self.declarations.append({"value": a["content"], "source": "meta:" + key})
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.script, self.parts = True, []

    def handle_data(self, data):
        if self.script:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or not self.script:
            return
        self.script = False
        try:
            parsed = json.loads("".join(self.parts))
        except (ValueError, TypeError):
            return
        queue = parsed if isinstance(parsed, list) else [parsed]
        examined = 0
        while queue and examined < 1000:
            item = queue.pop(); examined += 1
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("@graph"), list):
                queue.extend(item["@graph"])
            kinds = item.get("@type", [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if not isinstance(kinds, list) or not ARTICLE_TYPES.intersection(str(k) for k in kinds):
                continue
            declared = item.get("url") or item.get("mainEntityOfPage") or item.get("@id")
            if isinstance(declared, dict):
                declared = declared.get("@id")
            if isinstance(declared, str) and not same_page(urllib.parse.urljoin(self.url, declared), self.url):
                continue
            if isinstance(item.get("datePublished"), str):
                self.declarations.append({"value": item["datePublished"], "source": "jsonld:datePublished"})


def declaration_status(raw, url):
    parser = PublicationParser(url)
    parser.feed(raw.decode("utf-8", errors="replace"))
    declarations = list({(d["value"], d["source"]): d for d in parser.declarations}.values())
    exact = [aware(d["value"]) for d in declarations]
    exact = [d for d in exact if d is not None]
    instants = {d.astimezone(timezone.utc).isoformat() for d in exact}
    days = {d["value"] for d in declarations if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["value"])}
    if len(instants) > 1 or (exact and any(day not in {d.date().isoformat() for d in exact} for day in days)):
        return "conflicting", None, declarations
    if len(instants) == 1:
        return "verified_timestamp", next(iter(instants)), declarations
    return ("date_only" if days else "unverified"), None, declarations


def public_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or not parsed.hostname \
            or parsed.port not in {None, 80, 443}:
        raise ReplayError("unsupported_public_page_url")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ReplayError("nonpublic_page_destination")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ClockCollector:
    def __init__(self, output, source_sha, *, timeout=5, max_bytes=524288, max_total_bytes=134217728, reuse_dirs=()):
        self.output, self.source_sha, self.timeout, self.max_bytes = output, source_sha, timeout, max_bytes
        self.max_total_bytes, self.total_bytes, self.network_requests = max_total_bytes, 0, 0
        self.reused_pages = 0
        self.lock, self.host_locks, self.reuse_dirs = threading.Lock(), {}, [Path(p) for p in reuse_dirs]
        private_dir(output); private_dir(output / "records"); private_dir(output / "html")

    def base(self, row):
        return {"schemaVersion": "zoop-publication-clock-v1", "documentId": row["documentId"],
                "sourceFileSha256": self.source_sha, "bodySha256": row["bodySha256"], "url": row["url"],
                "status": "not_observed", "publishedAt": None, "checkedAt": now(), "htmlSha256": None,
                "declarations": [], "finalUrl": row["url"], "httpStatus": None, "meaning": MEANING}

    def observed(self, row, raw, final_url, checked_at=None, truncated=False):
        sha = digest(raw); write_once(self.output / "html" / (sha + ".html"), raw)
        status, timestamp, declarations = declaration_status(raw, final_url)
        return {**self.base(row), "status": status, "publishedAt": timestamp, "declarations": declarations,
                "checkedAt": checked_at or now(), "htmlSha256": sha, "httpStatus": 200, "finalUrl": final_url,
                "htmlScope": "bounded_prefix" if truncated else "captured_page", "htmlTruncated": truncated}

    def reuse(self, row):
        for directory in self.reuse_dirs:
            html = directory / (row["documentId"] + ".html")
            receipt = directory.parent / "original-publication" / (row["documentId"] + ".json")
            if not html.is_file() or not receipt.is_file() or html.is_symlink() or receipt.is_symlink():
                continue
            info = strict_load(regular(receipt)); raw = regular(html)
            if info.get("documentId") == row["documentId"] and info.get("url") == row["url"] \
                    and info.get("htmlSha256") == digest(raw) and same_page(info.get("finalUrl", ""), row["url"]):
                with self.lock: self.reused_pages += 1
                return self.observed(row, raw, info.get("finalUrl", row["url"]), info.get("checkedAt"))
        return None

    def collect(self, row, fetch=False):
        key = digest(canonical([row["documentId"], row["bodySha256"], row["url"], self.source_sha]))
        path = self.output / "records" / (key + ".json")
        if path.exists():
            saved = strict_load(regular(path))
            if saved.get("htmlSha256"):
                if digest(regular(self.output / "html" / (saved["htmlSha256"] + ".html"))) != saved["htmlSha256"]:
                    raise ReplayError("cached_clock_html_hash_changed")
            return saved
        if row.get("sourceKind") == "disclosure":
            value = {**self.base(row), "status": "date_only", "reason": "dart_reception_date_is_not_publication_time"}
        else:
            value = self.reuse(row)
            if value is None:
                value = self.fetch(row) if fetch else {**self.base(row), "reason": "original_page_not_observed"}
        save_json(path, value)
        return value

    def fetch(self, row):
        base = self.base(row)
        try:
            host = urllib.parse.urlsplit(row["url"]).hostname
            with self.lock:
                host_lock = self.host_locks.setdefault(host, threading.Lock())
            with host_lock:
                public_url(row["url"])
                with self.lock:
                    if self.total_bytes >= self.max_total_bytes:
                        return {**base, "reason": "bounded_collection_budget_exhausted"}
                opener = urllib.request.build_opener(NoRedirect())
                target = row["url"]
                for _ in range(4):
                    public_url(target)
                    with self.lock: self.network_requests += 1
                    request = urllib.request.Request(target, headers={"User-Agent": "Zoop-Publication-Clock/1.0", "Accept": "text/html,application/xhtml+xml"})
                    try:
                        with opener.open(request, timeout=self.timeout) as response:
                            if response.status != 200:
                                return {**base, "httpStatus": response.status, "reason": "page_http_not_success"}
                            if not any(t in response.headers.get("Content-Type", "").lower() for t in ["text/html", "application/xhtml+xml"]):
                                return {**base, "httpStatus": response.status, "reason": "page_not_html"}
                            raw = response.read(self.max_bytes + 1)
                            with self.lock: self.total_bytes += len(raw)
                            if not same_page(target, row["url"]):
                                return {**base, "reason": "redirect_does_not_identify_original_article"}
                            return self.observed(row, raw[:self.max_bytes], target, truncated=len(raw) > self.max_bytes)
                    except urllib.error.HTTPError as error:
                        if error.code in {301, 302, 303, 307, 308} and error.headers.get("Location"):
                            redirected = urllib.parse.urljoin(target, error.headers["Location"])
                            if not same_page(redirected, row["url"]):
                                return {**base, "httpStatus": error.code, "reason": "redirect_does_not_identify_original_article"}
                            target = redirected; continue
                        return {**base, "httpStatus": error.code, "reason": "page_access_failed_no_retry"}
                return {**base, "reason": "page_redirect_bound_exceeded"}
        except Exception as error:
            return {**base, "reason": "page_not_observed", "errorClass": type(error).__name__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", required=True); parser.add_argument("--output", required=True)
    parser.add_argument("--fetch-public-pages", action="store_true")
    parser.add_argument("--reuse-html-dir", action="append", default=[])
    parser.add_argument("--workers", type=int, choices=range(1, 25), default=16)
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    raw = regular(Path(args.sources)); rows = [strict_load(line) for line in raw.splitlines() if line.strip()]
    if not 1 <= len(rows) <= 1000 or not 0 < args.timeout <= 15:
        raise ReplayError("bounded_source_and_timeout_required")
    collector = ClockCollector(Path(args.output).resolve(), digest(raw), timeout=args.timeout, reuse_dirs=args.reuse_html_dir)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(lambda row: collector.collect(row, args.fetch_public_pages), rows))
    value = {"schemaVersion": "zoop-publication-clock-registry-v1", "sourceFileSha256": digest(raw), "records": records}
    save_json(collector.output / "registry.json", value)
    summary = {"sourceRecords": len(rows), "statuses": dict(Counter(r["status"] for r in records)),
               "networkRequestsThisRun": collector.network_requests, "reusedCapturedPagesThisRun": collector.reused_pages,
               "capturedBytesThisRun": collector.total_bytes, "paidCalls": 0, "meaning": MEANING}
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
