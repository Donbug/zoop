#!/usr/bin/env python3
"""Real loopback HTTP -> discovery CLI -> immutable minimized snapshot -> offline replay/status.

Synthetic only. No external article, API, provider, credential or model is contacted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE), str(PIPELINE / "src")]

from scripts.collection_smoke import LocalSite, PROXY_ENV  # noqa: E402

ROBOTS = b"User-agent: *\nAllow: /*.json$\nAllow: /*.json?*$\nDisallow: /\n"
PRIVATE = "SYNTHETIC_PRIVATE_BODY_AUTHOR_COMMENT_MARKER"


def config_data(site, **overrides):
    return {"schemaVersion": "zoop-hn-discovery-config-1", "feed": "new", "limit": 5,
            "userAgent": "ZoopSyntheticDiscovery/1.0 (+synthetic-local-test)", "timeoutSeconds": 10,
            "maxTotalSeconds": 60, "maxRequests": 20, "maxResponseBytes": 100_000, "maxTotalBytes": 1_000_000,
            "minIntervalSeconds": 1.0, "syntheticLoopback": True, "syntheticBaseUrl": site.url(""), **overrides}


def story(story_id, url, **overrides):
    return {"id": story_id, "type": "story", "title": "Synthetic submitted <b>title</b>", "url": url,
            "time": 1_700_000_000, "by": PRIVATE, "text": PRIVATE, "kids": [90001],
            "users": PRIVATE, "profiles": PRIVATE, "comments": PRIVATE, "futureUnknown": {"private": PRIVATE}, **overrides}


def route_json(site, path, value, **options):
    site.route(path, json.dumps(value).encode(), content_type="application/json", **options)


def cli(config, output, command="run", expected=0):
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8",
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(PIPELINE / "src"), **PROXY_ENV}
    child = subprocess.run([sys.executable, "-m", "zoop_ai_pipeline.hn_discovery_cli", command,
                            "--config", str(config), "--output", str(output)],
                           capture_output=True, env=environment, cwd=PIPELINE, timeout=90)
    assert child.returncode == expected, (child.returncode, child.stdout.decode(), child.stderr.decode())
    assert PRIVATE not in child.stdout.decode() + child.stderr.decode()
    return json.loads(child.stdout)


def smoke(root):
    site = LocalSite()
    try:
        site.route("/robots.txt", ROBOTS, content_type="text/plain")
        route_json(site, "/v0/newstories.json", [51, 52, 53, 54, 55, 56, 57, 58, 999])
        link = site.url("/unfetched%2Farticle?edition=two#section")
        route_json(site, "/v0/item/51.json", story(51, link, score=12, descendants=3))
        route_json(site, "/v0/item/52.json", story(52, link.replace("#section", "#other")))
        route_json(site, "/v0/item/53.json", {"id": 53, "deleted": True, "by": PRIVATE, "text": PRIVATE})
        route_json(site, "/v0/item/54.json", None)
        route_json(site, "/v0/item/55.json", story(55, "https://user:password@example.invalid/private"))
        literal_slash_link = site.url("/unfetched/article?edition=two")
        encoded_dot_link = site.url("/root/%2e%2e/article?edition=two")
        route_json(site, "/v0/item/56.json", story(56, literal_slash_link))
        route_json(site, "/v0/item/57.json", story(57, encoded_dot_link))
        route_json(site, "/v0/item/58.json", story(58, "https://news.ycombinator.com./item?id=51"))
        config = root / "config.json"
        config.write_text(json.dumps(config_data(site, limit=8)))
        output = root / "metadata"
        first = cli(config, output)
        assert first["candidates"] == 3 and first["dispositions"] == 4 and first["replayed"] is False, first
        raw = (output / "SNAPSHOT.json").read_bytes()
        snapshot = json.loads(raw)["snapshot"]
        assert snapshot["provenance"] == "synthetic-loopback-metadata"
        assert snapshot["selectedStoryIds"] == list(range(51, 59))
        candidate = snapshot["candidates"][0]
        assert candidate["canonicalUrl"] == link.split("#")[0]
        assert [ref["hnStoryId"] for ref in candidate["storyRefs"]] == [51, 52]
        assert [c["canonicalUrl"] for c in snapshot["candidates"]] == [link.split("#")[0], literal_slash_link, encoded_dot_link]
        assert snapshot["dispositions"][-1]["code"] == "item_internal_link"
        assert candidate["articlePublishedAt"] is None and candidate["publisher"] is None
        assert candidate["storyRefs"][0]["storyCreatedAt"] == "2023-11-14T22:13:20+00:00"
        assert candidate["storyRefs"][1]["score"] is None and candidate["storyRefs"][1]["commentCount"] is None
        assert candidate["storyRefs"][0]["observedAt"] != candidate["storyRefs"][0]["storyCreatedAt"]
        assert candidate["modelSend"] == "not-authorized" and candidate["license"] == candidate["articleAccess"] == "not-assessed"
        assert PRIVATE.encode() not in raw and b"password" not in raw
        for field in ("by", "text", "kids", "users", "profiles", "comments", "futureUnknown"):
            assert ('"' + field + '"').encode() not in raw
        paths = [entry["path"] for entry in site.log]
        assert paths == ["/robots.txt", "/v0/newstories.json", *[f"/v0/item/{i}.json" for i in range(51, 59)]], paths
        assert all(not ({"cookie", "authorization", "proxy-authorization", "referer"} & set(entry["headers"])) for entry in site.log)
        requests = len(site.log)
        assert cli(config, output)["replayed"] is True
        assert cli(config, output, "status")["replayed"] is True
        assert len(site.log) == requests and (output / "SNAPSHOT.json").read_bytes() == raw
        changed = root / "changed.json"
        changed.write_text(json.dumps(config_data(site, limit=4)))
        assert cli(changed, output, expected=2)["error"]["code"] == "discovery_config_conflict"
        assert len(site.log) == requests and (output / "SNAPSHOT.json").read_bytes() == raw
        assert sorted(path.name for path in output.iterdir()) == [".lock", "SNAPSHOT.json"]
        return {"status": "passed", "provenance": "synthetic-loopback-metadata", "sourceRequests": requests,
                "candidates": 3, "storyRefs": 4, "dispositions": 4, "externalCalls": 0, "modelCalls": 0,
                "checks": ["robots-gated exact selected IDs", "minimization and credential-link rejection", "duplicate URL grouping",
                           "encoded path/query identity preserved", "terminal-dot HN self-link rejected",
                           "submitted versus unknown publication time", "no article fetch or authority inference",
                           "proxy ignored and no cookies/auth", "byte-identical offline replay/status", "config conflict no-clobber"]}
    finally:
        site.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zoop-hn-synthetic-") as temporary:
        # macOS's system temporary parent may use /var -> /private/var; resolve our own sandbox only.
        print(json.dumps(smoke(Path(temporary).resolve()), sort_keys=True))
