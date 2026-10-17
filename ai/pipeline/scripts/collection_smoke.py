#!/usr/bin/env python3
"""Actual local HTTP server -> zoop-ai-collect -> zoop-ai-ingest -> inspect/export, all as real subprocesses.

Everything is synthetic and loopback-only (the policy sets `syntheticLoopback`, the only way an http/loopback URL is ever fetched). No
external site, model, provider, proxy or credential is used, the original PoC is not imported, and all state is removed afterwards.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.ingestion_smoke import OfflineFixture, authored_pdf, exact_check, json_bytes, ownership_env, sha  # noqa: E402

COLLECTION_SCHEMA = "zoop-collection-1"
INGESTION_SCHEMA = "zoop-ingestion-s2-1"
NEWS = '<html><head><title>합성</title></head><body><article><p>합성 공시 &amp; <b>본문😀</b> 끝</p><p>둘째 문단</p></article></body></html>'.encode()
ROBOTS = b"User-agent: *\nDisallow: /private/\nAllow: /private/open\n"
PROXY_ENV = {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
             "https_proxy": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9", "all_proxy": "http://127.0.0.1:9"}


class LocalSite:
    """A real HTTP/1.0 server on 127.0.0.1 with scripted routes and a request log (path + lower-cased headers)."""

    def __init__(self):
        self.routes: dict[str, dict] = {}
        self.log: list[dict] = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.log.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
                route = site.routes.get(self.path.split("?")[0]) or {"status": 404, "body": b"missing", "headers": {"Content-Type": "text/plain"}}
                if route.get("hook"):
                    route["hook"]()
                if route.get("delay"):
                    time.sleep(route["delay"])
                self.send_response(route["status"])
                headers = dict(route["headers"])
                if route.get("length", True):
                    headers.setdefault("Content-Length", str(len(route["body"])))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                try:
                    self.wfile.write(route["body"])
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        Thread(target=self.server.serve_forever, daemon=True).start()

    def route(self, path, body=b"", status=200, content_type="text/html; charset=utf-8", headers=None, **options):
        self.routes[path] = {"status": status, "body": body, "headers": {"Content-Type": content_type, **(headers or {})}, **options}

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def hits(self, path):
        return sum(entry["path"].split("?")[0] == path for entry in self.log)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class CollectionKit(OfflineFixture):
    """The ingestion fixture's registry, switched to one `collected-http` source for the loopback host, plus a collector policy."""

    def __init__(self, root: Path):
        super().__init__(root)
        source = self.registry["sources"][0]
        source["adapter"], source["allowedHosts"] = "collected-http", ["127.0.0.1"]
        source["scopes"][0]["timestampLimitations"] = ["one-off explicit URL list; no discovery or time-window coverage"]
        self.save_registry()
        self.policy_path = self.root / "policy.json"
        self.policy = {"schemaVersion": "zoop-collection-policy-1", "userAgent": "ZoopSyntheticCollector/1.0 (+synthetic-local-test)", "timeoutSeconds": 5,
                       "maxTotalSeconds": 60, "maxRedirects": 3, "maxRequests": 40, "maxResponseBytes": 200_000, "maxTotalBytes": 3_000_000,
                       "minIntervalSeconds": 0, "allowedMediaTypes": ["text/html", "application/pdf"], "syntheticLoopback": True}
        self.save_policy()

    def save_policy(self):
        self.policy_path.write_bytes(json_bytes(self.policy))

    @staticmethod
    def target(url, candidate, *, title="synthetic title", kind="news", published=None, modified=None, supplier=None, revision=None):
        return {"candidateId": candidate, "url": url, "title": title, "documentKind": kind, "publishedAt": published, "modifiedAt": modified,
                "supplierDocumentId": supplier, "sourceRevision": revision}

    def collection_request(self, collection_id, targets):
        return {"schemaVersion": COLLECTION_SCHEMA, "collectionId": collection_id, "sourceId": "synthetic-source", "scopeId": "body", "targets": targets}

    def collect(self, collection_id, targets, *, expected=0, env=None):
        return self.collect_raw(self.collection_request(collection_id, targets), expected=expected, env=env)

    def collect_raw(self, request, *, expected=0, env=None, sources=None, policy=None):
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
                       "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", **ownership_env(), **(env or {})}
        argv = [sys.executable, "-m", "zoop_ai_pipeline.collection_cli", "run", "--sources", str(sources or self.registry_path),
                "--policy", str(policy or self.policy_path)]
        child = subprocess.run(argv, input=json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, cwd=PIPELINE, timeout=180)
        assert child.returncode == expected, (child.returncode, child.stdout.decode(), child.stderr.decode())
        return json.loads(child.stdout)

    def export_selector(self, rid, ref):
        return {"schemaVersion": INGESTION_SCHEMA, "roundId": rid, "sourceId": "synthetic-source",
                **{key: ref[key] for key in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}}


def smoke(root: Path) -> dict:
    site = LocalSite()
    checks = []
    try:
        kit = CollectionKit(root / "kit")
        site.route("/robots.txt", ROBOTS, content_type="text/plain")
        site.route("/news/a", NEWS)
        site.route("/disclosure/b.pdf", authored_pdf("disclosure body"), content_type="application/pdf")
        site.route("/private/x", NEWS)
        targets = [kit.target(site.url("/news/a"), "n1", published="2026-10-14"),
                   kit.target(site.url("/disclosure/b.pdf"), "d1", kind="disclosure", published="2026-10-14T09:00:00+09:00", supplier="filing-1")]
        first = kit.collect("collect-1", targets, env=PROXY_ENV)
        assert first["state"] == "complete" and first["provenance"] == "collected_http" and first["replayed"] is False, first
        assert first["usage"] == {"requests": 3, "bytes": first["usage"]["bytes"], "targets": 2, "collected": 2}, first["usage"]
        page_requests = [e for e in site.log if e["path"] != "/robots.txt"]
        assert len(site.log) == 3 and all(e["headers"]["user-agent"] == kit.policy["userAgent"] for e in site.log)
        assert all(e["headers"]["host"] == f"127.0.0.1:{site.port}" and e["headers"]["accept-encoding"] == "identity" for e in site.log)
        assert not any(name in e["headers"] for e in page_requests for name in ("cookie", "authorization", "proxy-authorization", "referer")), page_requests
        checks.append("actual loopback HTTP: robots first, exact user agent/Host, no cookie/authorization/referer, proxy environment ignored")
        again = kit.collect("collect-1", targets)
        assert again["replayed"] is True and len(site.log) == 3 and again["manifest"] == first["manifest"]
        checks.append("same immutable collectionId and input: replayed from the stored record, zero new requests")

        manifest = Path(first["manifestPath"])
        ran = kit.cli("run", kit.request(manifest, "round-1"), manifest=manifest)
        assert ran["state"] == "complete" and ran["provenance"] == "collected_http" and ran["counts"]["textReady"] == 2 == ran["counts"]["newTextVersions"], ran
        html_ref, pdf_ref = ran["documentRefs"]
        html = kit.cli("export", kit.export_selector("round-1", html_ref), extra=["--require-store"])
        pdf = kit.cli("export", kit.export_selector("round-1", pdf_ref), extra=["--require-store"])
        o, c = html["observation"], html["observation"]["collection"]
        assert o["provenance"] == "collected_http" and o["url"] == site.url("/news/a") and o["publishedAt"] is None and o["mediaType"] == "text/html"
        assert c["published"] == {"raw": "2026-10-14", "precision": "day", "date": "2026-10-14", "basis": c["published"]["basis"]}
        assert c["network"] == "synthetic_loopback", "a local test server is never labelled an external document"
        assert c["documentKind"] == "news" and c["httpStatus"] == 200 and c["finalUrl"] == o["url"] and c["bodySha256"] == sha(NEWS)
        assert datetime.fromisoformat(c["fetchedAt"]).tzinfo is not None and html["locatorMetadata"]["rawHash"] == sha(NEWS)
        assert html["document"]["text"] == "합성 공시 & 본문😀 끝\n둘째 문단"
        p = pdf["observation"]
        assert p["publishedAt"] == "2026-10-14T09:00:00+09:00" and p["collection"]["published"]["precision"] == "instant" and p["collection"]["documentKind"] == "disclosure"
        assert pdf["document"]["text"] == "disclosure body" and pdf["grant"] == {"grantId": "operator-grant", "revision": "rights-1"}
        exact_check(html["document"], 0, html["document"]["rawLocators"][0]["end"])
        exact_check(pdf["document"], 0, len(pdf["document"]["text"]))
        checks.append("collect -> ingest -> export: hash-bound HTML and PDF versions, exact citations, day precision never becomes midnight, instant keeps its offset")

        partial = kit.collect("collect-partial", [kit.target(site.url("/news/a"), "n1", published="2026-10-14"), kit.target(site.url("/private/x"), "p1")], expected=2)
        assert partial["state"] == "partial" and {t["candidateId"]: t["code"] for t in partial["targets"]} == {"n1": None, "p1": "robots_denied"}
        pm = Path(partial["manifestPath"])
        incomplete = kit.cli("run", kit.request(pm, "round-partial", 1), manifest=pm)
        assert incomplete["state"] == "incomplete" and incomplete["failure"]["code"] == "discovery_page_partial" and incomplete["counts"]["textReady"] == 1
        checks.append("partial collection is partial (robots denial), and ingestion keeps the round incomplete instead of reporting success")

        site.route("/img", b"\x89PNG", content_type="image/png")
        site.route("/gz", b"x", headers={"Content-Encoding": "gzip"})
        site.route("/huge", b"a" * 250_000, length=False)
        site.route("/big-cl", b"a" * 300_000)
        site.route("/loop", status=302, headers={"Location": "/loop"})
        site.route("/off", status=302, headers={"Location": f"http://localhost:{site.port}/news/a"})
        names = {"img": "media_type_not_allowed", "gz": "content_encoding", "huge": "response_too_large", "big-cl": "response_too_large",
                 "missing": "http_404", "loop": "redirect_limit", "off": "host_not_allowed"}
        failed = kit.collect("collect-failed", [kit.target(site.url("/" + n), n) for n in names], expected=2)
        assert failed["state"] == "failed" and {t["candidateId"]: t["code"] for t in failed["targets"]} == names, failed["targets"]
        fm = Path(failed["manifestPath"])
        stopped = kit.cli("run", kit.request(fm, "round-failed", 1), manifest=fm)
        assert stopped["state"] == "incomplete" and stopped["failure"]["code"] == "discovery_page_failed" and stopped["counts"]["textReady"] == 0
        checks.append("type, encoding, size, status, redirect-loop and redirect-to-unlisted-host failures are distinct codes; an all-failed collection is failed, never a zero success")

        def revoke():
            kit.registry["sources"][0]["grant"]["enabled"] = False
            kit.save_registry()

        site.route("/revoking", NEWS, hook=revoke)
        refused = kit.collect("collect-revoked", [kit.target(site.url("/revoking"), "r1")], expected=2)
        assert refused["error"]["code"] == "registry_changed", refused
        assert sorted(os.listdir(kit.inputs / "collections")) == [".lock", "collect-1", "collect-failed", "collect-partial"]
        kit.registry["sources"][0]["grant"]["enabled"] = True
        kit.save_registry()
        checks.append("a grant revoked while bytes were downloading keeps nothing: no collection directory and no temporary directory remain")

        kit.registry["sources"][0]["grant"]["enabled"] = False
        kit.save_registry()
        assert kit.cli("export", kit.export_selector("round-1", html_ref), expected=2)["error"]["code"] == "source_unauthorized"
        assert kit.collect("collect-1", targets, expected=2)["error"]["code"] == "source_unauthorized"
        kit.registry["sources"][0]["grant"]["enabled"] = True
        kit.save_registry()
        checks.append("revoked grant: export and even a stored-collection replay return no body, only source_unauthorized")
    finally:
        site.close()
    return {"status": "passed", "providerCalls": 0, "modelCalls": 0, "externalNetwork": "none: loopback server only", "checks": checks}


def main():
    with tempfile.TemporaryDirectory(prefix="zoop-collection-smoke-") as temporary:
        root = Path(temporary).resolve()
        result = smoke(root)
    assert not root.exists()
    result["temporaryStateCleanup"] = {"removed": True}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
