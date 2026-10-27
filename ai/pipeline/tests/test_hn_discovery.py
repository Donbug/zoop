"""Discovery contract/security coverage. All HTTP uses explicit synthetic loopback mode."""
from __future__ import annotations

import fcntl
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.collection_smoke import LocalSite
from scripts.hn_discovery_smoke import PRIVATE, ROBOTS, config_data, route_json, story
from zoop_ai_pipeline.collection_contracts import Policy
from zoop_ai_pipeline.hn_discovery import Config, _JsonFetcher, link_identity, parse_item, run, status
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure

OBSERVED = "2026-10-24T12:00:00+00:00"


@pytest.fixture
def site():
    server = LocalSite()
    server.route("/robots.txt", ROBOTS, content_type="text/plain")
    yield server
    server.close()


def config(site, **overrides):
    return Config.model_validate(config_data(site, **overrides))


def parsed(item, pinned=1):
    return parse_item(json.dumps(item).encode(), pinned, OBSERVED)


@pytest.mark.parametrize(("item", "code"), [
    (None, "item_null"), ({}, "item_identity_invalid"),
    ({"id": True}, "item_identity_invalid"), ({"id": "1"}, "item_identity_invalid"),
    ({"id": 2, "type": "story"}, "item_identity_invalid"),
    ({"id": 1, "deleted": True, "text": PRIVATE}, "item_deleted"),
    ({"id": 1, "dead": True, "by": PRIVATE}, "item_dead"),
    ({"id": 1, "deleted": 1}, "item_type_invalid"),
    ({"id": 1, "type": "job"}, "item_nonstory"), ({"id": 1, "type": "comment"}, "item_nonstory"),
    ({"id": 1, "type": "future-type"}, "item_unsupported"),
    ({"id": 1, "type": 3}, "item_type_invalid"),
    (story(1, "https://example.invalid/a", title=10), "item_metadata_invalid"),
    (story(1, "https://example.invalid/a", time=True), "item_metadata_invalid"),
    (story(1, "https://example.invalid/a", time=-1), "item_metadata_invalid"),
    (story(1, "https://example.invalid/a", time=253402300800), "item_metadata_invalid"),
    (story(1, "https://example.invalid/a", score=None), "item_metadata_invalid"),
    (story(1, "https://example.invalid/a", descendants=True), "item_metadata_invalid"),
    ({"id": 1, "type": "story", "time": 1, "title": "Ask HN"}, "item_no_link"),
    (story(1, None), "link_invalid"), (story(1, "javascript:alert(1)"), "link_invalid"),
    (story(1, "https://user:secret@example.invalid/a"), "link_invalid"),
    (story(1, "https://news.ycombinator.com/item?id=1"), "item_internal_link"),
], ids=["null", "missing-id", "boolean-id", "string-id", "id-pin", "deleted", "dead", "bad-flag", "job", "comment",
        "unknown-type", "bad-type", "bad-title", "boolean-time", "negative-time", "overflow-time", "null-score",
        "boolean-comments", "no-url", "null-url", "script-url", "credential-url", "self-link"])
def test_item_fail_closed(item, code):
    with pytest.raises(IngestionFailure) as failure:
        parsed(item)
    assert failure.value.code == code
    assert PRIVATE not in str(failure.value)


@pytest.mark.parametrize("raw", [b'{"id":1,"id":2}', b'{', b'NaN', b'"not an item"'])
def test_invalid_json_or_shape(raw):
    with pytest.raises(IngestionFailure) as failure:
        parse_item(raw, 1, OBSERVED)
    assert failure.value.code in {"json_invalid", "item_identity_invalid"}


def test_minimization_and_time_are_not_article_publication():
    url, ref = parsed(story(1, "http://Example.invalid:80/a?edition=two#part"))
    assert url == "http://example.invalid/a?edition=two"
    data = ref.wire()
    assert data["hnSubmittedTitleHtml"] == "Synthetic submitted <b>title</b>"
    assert data["storyCreatedAt"] == "2023-11-14T22:13:20+00:00" and data["observedAt"] == OBSERVED
    assert data["score"] is None and data["commentCount"] is None
    assert set(data) == {"hnStoryId", "hnSubmittedTitleHtml", "storyCreatedAt", "observedAt", "score", "commentCount", "rawResponseSha256"}
    assert PRIVATE not in json.dumps(data)
    assert link_identity("https://example.invalid/?q=one") != link_identity("https://example.invalid/?q=two")
    assert link_identity("http://example.invalid:8080/a") == "http://example.invalid:8080/a"


@pytest.mark.parametrize("url", [
    "https://example.invalid/a%2Fb?q=%2F%26&x=+#section",
    "https://example.invalid/a/%2e%2e/b?q=%252F#section",
    "http://example.invalid/a%252Fb?edition=two#section",
])
def test_link_identity_preserves_encoded_path_and_query(url):
    assert link_identity(url) == url.split("#")[0]
    assert link_identity("https://example.invalid/a%2Fb") != link_identity("https://example.invalid/a/b")
    assert link_identity("https://example.invalid/a/%2e%2e/b") != link_identity("https://example.invalid/b")


@pytest.mark.parametrize("host", ["news.ycombinator.com.", "hacker-news.firebaseio.com.", "NEWS.YCOMBINATOR.COM."])
def test_dns_equivalent_hn_self_links_are_not_external_candidates(host):
    with pytest.raises(IngestionFailure) as failure:
        parsed(story(1, f"https://{host}/item?id=1"))
    assert failure.value.code == "item_internal_link"


@pytest.mark.parametrize("overrides", [{"limit": 51}, {"limit": True}, {"minIntervalSeconds": 0.99}, {"maxRequests": 53},
    {"maxTotalSeconds": 0}, {"maxTotalBytes": 0}, {"userAgent": "bad\nagent"}, {"env": {}},
    {"syntheticLoopback": False}, {"syntheticBaseUrl": "https://example.invalid"},
    {"syntheticBaseUrl": "http://127.0.0.1:99999"}, {"syntheticBaseUrl": "http://127.0.0.1:80/arbitrary"}])
def test_config_rejects_unbounded_or_arbitrary_transport(site, overrides):
    with pytest.raises(ValidationError):
        config(site, **overrides)


def test_production_origin_is_not_operator_selectable():
    data = {"schemaVersion": "zoop-hn-discovery-config-1", "feed": "best", "limit": 20,
            "userAgent": "ZoopDiscovery/1.0", "timeoutSeconds": 15, "maxTotalSeconds": 120,
            "maxRequests": 22, "maxResponseBytes": 100_000, "maxTotalBytes": 1_000_000, "minIntervalSeconds": 1.0}
    validated = Config.model_validate(data)
    assert validated.origin == "https://hacker-news.firebaseio.com" and validated.max_redirects == 0
    for field in ("baseUrl", "endpoint", "proxy", "backend"):
        with pytest.raises(ValidationError):
            Config.model_validate({**data, field: "https://elsewhere.invalid"})
    fetcher = _JsonFetcher(validated)
    for url in ("https://example.invalid/v0/beststories.json", "https://hacker-news.firebaseio.com/v0/user/a.json",
                "https://hacker-news.firebaseio.com/v0/item/1.json", "https://hacker-news.firebaseio.com/v0/beststories.json?x=1"):
        with pytest.raises(IngestionFailure):
            fetcher.fetch(url)
    assert fetcher.requests == 0


def test_native_document_policy_still_refuses_json():
    with pytest.raises(ValidationError):
        Policy.model_validate({"schemaVersion": "zoop-collection-policy-1", "userAgent": "Test/1", "timeoutSeconds": 5,
            "maxTotalSeconds": 60, "maxRedirects": 0, "maxRequests": 10, "maxResponseBytes": 1000,
            "maxTotalBytes": 10000, "minIntervalSeconds": 1.0, "allowedMediaTypes": ["application/json"]})


@pytest.mark.parametrize(("robots", "code"), [(b"User-agent: *\nDisallow: /\n", "robots_denied"),
                                                   (b"malformed robots", "robots_malformed")])
def test_robots_are_real_gates(site, tmp_path, robots, code):
    site.route("/robots.txt", robots, content_type="text/plain")
    result = run(config(site), tmp_path / "metadata")
    assert result["state"] == "stopped" and result["stopCode"] == code
    assert [entry["path"] for entry in site.log] == ["/robots.txt"]
    assert not result["candidates"]


@pytest.mark.parametrize("status_code", [401, 403, 429])
def test_blocked_host_stops_without_retry_or_next_item(site, tmp_path, status_code):
    route_json(site, "/v0/newstories.json", [1, 2])
    route_json(site, "/v0/item/1.json", {"error": PRIVATE}, status=status_code)
    route_json(site, "/v0/item/2.json", story(2, site.url("/unfetched")))
    cfg = config(site)
    output = tmp_path / "metadata"
    first = run(cfg, output)
    assert first["stopCode"] == f"http_{status_code}"
    assert [d["code"] for d in first["dispositions"]] == [f"http_{status_code}", f"not_requested_http_{status_code}"]
    assert site.hits("/v0/item/1.json") == 1 and site.hits("/v0/item/2.json") == 0
    requests = len(site.log)
    assert run(cfg, output)["replayed"] is True and status(cfg, output)["replayed"] is True
    assert len(site.log) == requests
    assert PRIVATE.encode() not in (output / "SNAPSHOT.json").read_bytes()


@pytest.mark.parametrize(("overrides", "code"), [({"maxRequests": 1}, "request_budget"),
    ({"maxResponseBytes": 20}, "response_too_large"),
    ({"maxResponseBytes": 80, "maxTotalBytes": 80}, "byte_budget"),
    ({"timeoutSeconds": 1, "maxTotalSeconds": 1}, "rate_limit")])
def test_finite_request_byte_response_and_time_caps(site, tmp_path, overrides, code):
    route_json(site, "/v0/newstories.json", [123456789012345, 234567890123456, 345678901234567])
    result = run(config(site, **overrides), tmp_path / "metadata")
    assert result["state"] == "stopped" and result["stopCode"] == code, result
    assert not any("/item/" in entry["path"] for entry in site.log)


def test_streaming_over_budget_keeps_truthful_bytes_and_publishes_stopped_snapshot(site, tmp_path):
    route_json(site, "/v0/newstories.json", list(range(1, 13)))
    route_json(site, "/v0/item/1.json", story(1, "https://example.invalid/unfetched"))
    # Stay below the total through item 10, then cross it in an actual unframed HTTP body.
    # The final chunk is counted before the native transport stops; no giant payload enters an assertion ID.
    padding = b" " * 1_000_000
    for story_id in range(2, 11):
        site.route(f"/v0/item/{story_id}.json", padding, content_type="application/json")
    site.route("/v0/item/11.json", padding, content_type="application/json", length=False)
    cfg = config(site, limit=12, maxResponseBytes=1_000_000, maxTotalBytes=10_000_000)
    output = tmp_path / "metadata"
    result = run(cfg, output)
    assert result["state"] == "stopped" and result["stopCode"] == "byte_budget"
    assert result["sourceBytes"] > cfg.max_total_bytes
    assert len(result["candidates"]) == 1
    assert [d["code"] for d in result["dispositions"]] == ["json_invalid"] * 9 + ["byte_budget", "not_requested_byte_budget"]
    assert site.hits("/v0/item/11.json") == 1 and site.hits("/v0/item/12.json") == 0
    raw = (output / "SNAPSHOT.json").read_bytes()
    assert len(raw) < 1_000_000
    assert json.loads(raw)["snapshot"]["sourceBytes"] == result["sourceBytes"]
    requests = len(site.log)
    assert status(cfg, output)["sourceBytes"] == result["sourceBytes"]
    assert run(cfg, output) == {**result, "replayed": True}
    assert len(site.log) == requests and (output / "SNAPSHOT.json").read_bytes() == raw


@pytest.mark.parametrize("ids", [[True], ["1"], [1, 1], [-1], [0], list(range(1, 502))],
                         ids=["boolean", "string", "duplicate", "negative", "zero", "oversized-feed"])
def test_feed_pins_only_valid_bounded_unique_ids(site, tmp_path, ids):
    route_json(site, "/v0/newstories.json", ids)
    result = run(config(site), tmp_path / "metadata")
    assert result["stopCode"] == "feed_identity_invalid" and result["selectedStoryIds"] == []
    assert len(site.log) == 2


def test_nonterminal_item_errors_are_dispositions_and_not_good_articles(site, tmp_path):
    route_json(site, "/v0/newstories.json", [1, 2, 3, 4])
    route_json(site, "/v0/item/1.json", story(99, "https://example.invalid/a"))
    route_json(site, "/v0/item/2.json", None)
    site.route("/v0/item/3.json", b"{", content_type="application/json")
    route_json(site, "/v0/item/4.json", {"error": PRIVATE}, status=500)
    result = run(config(site), tmp_path / "metadata")
    assert result["state"] == "completed" and result["candidates"] == []
    assert [d["code"] for d in result["dispositions"]] == ["item_identity_invalid", "item_null", "json_invalid", "http_500"]
    assert len(site.log) == 6


def test_redirect_and_nonjson_feed_do_not_become_candidates(site, tmp_path):
    site.route("/v0/newstories.json", status=302, headers={"Location": "https://example.invalid/secret"})
    first = run(config(site), tmp_path / "redirect")
    assert first["stopCode"] == "redirect_limit" and len(site.log) == 2
    site.route("/v0/newstories.json", b"[1]", content_type="text/html")
    second = run(config(site), tmp_path / "html")
    assert second["stopCode"] == "media_type_not_allowed" and len(site.log) == 4


def test_limit_aggregation_privacy_no_clobber_and_offline_replay(site, tmp_path):
    route_json(site, "/v0/newstories.json", [1, 2, 3, 4])
    link = site.url("/article?x=meaningful")
    route_json(site, "/v0/item/1.json", story(1, link + "#a", score=5, descendants=2))
    route_json(site, "/v0/item/2.json", story(2, link + "#b"))
    route_json(site, "/v0/item/3.json", {"id": 3, "type": "job", "text": PRIVATE})
    cfg, output = config(site, limit=3), tmp_path / "metadata"
    first = run(cfg, output)
    assert len(first["candidates"]) == 1 and len(first["dispositions"]) == 1
    candidate = first["candidates"][0]
    assert [ref["hnStoryId"] for ref in candidate["storyRefs"]] == [1, 2]
    assert candidate["canonicalUrl"] == link and candidate["articlePublishedAt"] is None
    assert candidate["publisher"] is None and candidate["articleAccess"] == candidate["license"] == "not-assessed"
    assert candidate["modelSend"] == "not-authorized"
    assert site.hits("/article") == site.hits("/v0/item/4.json") == 0
    assert first["sourceRequests"] == 5 and first["sourceBytes"] > 0
    raw = (output / "SNAPSHOT.json").read_bytes()
    assert PRIVATE.encode() not in raw
    for field in ("by", "text", "kids", "users", "profiles", "comments", "futureUnknown"):
        assert ('"' + field + '"').encode() not in raw
    requests = len(site.log)
    assert run(cfg, output) == {**first, "replayed": True}
    assert status(cfg, output) == {**first, "replayed": True}
    with pytest.raises(IngestionFailure) as failed:
        run(config(site, limit=2), output)
    assert failed.value.code == "discovery_config_conflict"
    assert len(site.log) == requests and (output / "SNAPSHOT.json").read_bytes() == raw
    assert sorted(path.name for path in output.iterdir()) == [".lock", "SNAPSHOT.json"]


def test_foreign_partial_symlink_and_busy_namespaces_do_not_fetch(site, tmp_path):
    cfg = config(site)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "SNAPSHOT.json").write_bytes(b"do not clobber")
    with pytest.raises(IngestionFailure):
        run(cfg, foreign)
    assert (foreign / "SNAPSHOT.json").read_bytes() == b"do not clobber"
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / ".lock").touch()
    with pytest.raises(IngestionFailure) as failed:
        run(cfg, partial)
    assert failed.value.code == "discovery_incomplete_output"
    linked = tmp_path / "linked"
    linked.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(OSError):
        run(cfg, linked)
    with (partial / ".lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(IngestionFailure) as failed:
            run(cfg, partial)
        assert failed.value.code == "discovery_busy"
    assert site.log == []


def test_status_refuses_tampering_and_snapshot_symlinks_without_network(site, tmp_path):
    route_json(site, "/v0/newstories.json", [])
    cfg, output = config(site), tmp_path / "metadata"
    run(cfg, output)
    file = output / "SNAPSHOT.json"
    raw = file.read_bytes()
    file.write_bytes(raw.replace(b'"sourceRequests":2', b'"sourceRequests":1'))
    requests = len(site.log)
    with pytest.raises(IngestionFailure) as failed:
        status(cfg, output)
    assert failed.value.code == "discovery_snapshot_invalid"
    file.unlink()
    target = tmp_path / "other.json"
    target.write_bytes(raw)
    file.symlink_to(target)
    with pytest.raises(OSError):
        run(cfg, output)
    assert len(site.log) == requests
