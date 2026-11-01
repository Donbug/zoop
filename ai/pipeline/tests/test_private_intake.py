"""Private intake lifecycle and access boundaries, with authored loopback bodies only."""
import errno
import json
import os
import stat
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from scripts.collection_smoke import LocalSite
from scripts.private_intake_smoke import PRIVATE, article, config_data, sitemap
from zoop_ai_pipeline import private_intake as intake
from zoop_ai_pipeline import collection as collection_transport
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, canonical, digest
from zoop_ai_pipeline.news_sources import descriptor, surface


@pytest.fixture
def kit(tmp_path):
    root = tmp_path.resolve()
    site = LocalSite()
    site.route("/robots.txt", b"User-agent: *\nAllow: /\n", content_type="text/plain")
    values = config_data(root, site.url(""))
    for index, day in enumerate(("2026-07-25", "2026-07-26", "2026-07-27"), 1):
        site.route(f"/sitemap/daily-article/{day.replace('-', '')}.xml",
                   sitemap([site.url(f"/article/a{index}")]), content_type="application/xml")
        site.route(f"/article/a{index}", article(day))
    yield site, values
    site.close()


def run(values, command="run"):
    return intake.run(intake.Config.model_validate(values), command)


def saved(values):
    return json.loads((Path(values["stateDir"]) / "STATE.json").read_bytes())["state"]


def set_state(values, data):
    path = Path(values["stateDir"]) / "STATE.json"
    path.write_text(canonical({"state": data, "sha256": digest(data)}))


def test_real_discovery_precedes_bodies_exact_mapping_and_offline_resume(kit):
    site, values = kit
    result = run(values)
    assert result["retainedInWindow"] == 3 and result["coverage"] == "all"
    assert [entry["path"] for entry in site.log[:4]] == ["/robots.txt", "/sitemap/daily-article/20260725.xml",
                                                        "/sitemap/daily-article/20260727.xml", "/sitemap/daily-article/20260726.xml"]
    assert result["sourceRequests"] == len(site.log) == 7
    root = Path(values["stateDir"])
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    for path in root.glob("private-news-*.json"):
        record = json.loads(path.read_bytes())
        assert record["rights"] == "unconfirmed" and record["publicUse"] is False and record["modelSend"] is False
        assert record["prepared"] == intake.prepare(path.with_suffix(".raw").read_bytes(), "text/html", record["articleXPath"])
        assert PRIVATE in record["prepared"]["text"] and "NOT ARTICLE" not in record["prepared"]["text"]
        assert record["publication"]["precision"] == "instant"
        assert record["canonicalUrl"].endswith("/not-fetched-canonical")
    assert run(values, "resume")["sourceRequests"] == 7
    assert run(values, "status")["sourceRequests"] == 7
    assert len(site.log) == 7
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}
    assert not any(p.is_dir() for p in root.iterdir())
    assert PRIVATE not in canonical(result)


def test_plan_conflict_and_repeated_run_never_touch_committed_state(kit):
    site, values = kit
    run(values)
    root = Path(values["stateDir"])
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(IngestionFailure, match="private_plan_conflict"):
        run({**values, "maxDocuments": 2}, "resume")
    with pytest.raises(IngestionFailure, match="private_explicit_resume_required"):
        run(values)
    assert len(site.log) == 7
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}


def test_cumulative_request_budget_survives_resume_without_retry(kit):
    site, values = kit
    values["policy"]["maxRequests"] = 4
    first = run(values)
    assert first["sourceRequests"] == len(site.log) == 4
    assert first["pendingCandidates"] == 3 and first["retainedInWindow"] == 0
    assert first["stopCode"] == "request_budget" and first["coverage"] == "some"
    second = run(values, "resume")
    assert second["sourceRequests"] == 4 and len(site.log) == 4
    assert second["pendingCandidates"] == 3


def test_document_cap_keeps_all_discoveries_and_rotates_dates(kit):
    site, values = kit
    values["maxDocuments"] = 2
    for day in ("25", "26", "27"):
        urls = [site.url(f"/article/d{day}x{i}") for i in range(3)]
        site.route(f"/sitemap/daily-article/202607{day}.xml", sitemap(urls), content_type="application/xml")
        for index in range(3):
            site.route(f"/article/d{day}x{index}", article(f"2026-07-{day}"))
    result = run(values)
    assert result["candidates"] == 9 and result["pendingCandidates"] == 7
    assert result["dayCounts"] == {"2026-07-25": 1, "2026-07-27": 1}
    assert result["stopCode"] == "document_cap" and result["coverage"] == "some"
    requests = len(site.log)
    assert run(values, "resume")["pendingCandidates"] == 7
    assert len(site.log) == requests


def test_listing_cap_is_explicit_partial_coverage(kit):
    site, values = kit
    values["maxListingPages"] = 1
    result = run(values)
    assert result["traversedPartitions"] == 1 and result["pendingPartitions"] == 2
    assert result["retainedInWindow"] == 1 and result["coverage"] == "some"
    assert result["stopCode"] == "listing_page_cap"
    requests = len(site.log)
    run(values, "resume")
    assert len(site.log) == requests


class SimulatedCrash(BaseException):
    pass


@pytest.mark.parametrize("after_record", [False, True], ids=["raw-before-record", "record-before-state"])
def test_interrupted_commit_recovery_never_refetches(kit, monkeypatch, after_record):
    site, values = kit
    original = intake._publish
    triggered = False

    def interrupt(fd, name, raw, **options):
        nonlocal triggered
        original(fd, name, raw, **options)
        suffix = ".json" if after_record else ".raw"
        if name.startswith("private-news-") and name.endswith(suffix) and not triggered:
            triggered = True
            raise SimulatedCrash()

    monkeypatch.setattr(intake, "_publish", interrupt)
    with pytest.raises(SimulatedCrash):
        run(values)
    assert triggered
    attempted = [entry["path"] for entry in site.log if entry["path"].startswith("/article/")]
    assert len(attempted) == 1
    monkeypatch.setattr(intake, "_publish", original)
    result = run(values, "resume")
    assert site.hits(attempted[0]) == 1
    if after_record:
        assert result["retainedInWindow"] == 3
        assert result["coverage"] == "all"
    else:
        assert result["retainedInWindow"] == 2
        assert result["candidateDispositions"]["unsettled_article_no_retry"] == 1
        assert result["coverage"] == "unknown"


def test_unsettled_get_reserves_unknown_budget_and_never_retries(kit):
    site, values = kit
    values["policy"]["maxRequests"] = 4
    run(values)
    data = saved(values)
    identifier, item = next(iter(data["candidates"].items()))
    item["status"] = "attempting"
    data["attempts"].append({"kind": "article", "key": identifier, "status": "attempting", "startedAt": intake.now()})
    reserve = values["policy"]["maxTotalBytes"] - data["bytes"]
    data["pendingRequest"] = {"host": "127.0.0.1", "byteUpperBound": reserve, "startedAt": intake.now()}
    set_state(values, data)
    assert run(values, "status")["coverage"] == "unknown"
    requests = len(site.log)
    result = run(values, "resume")
    assert result["sourceRequests"] == 4 and result["unknownRequests"] == 1
    assert result["unknownByteUpperBound"] == reserve
    assert len(site.log) == requests
    assert run(values, "resume")["unknownRequests"] == 1


@pytest.mark.parametrize("change,code", [
    (lambda raw: raw.replace(b'2026-07-25T12:34:56+09:00', b'2026-07-25T12:34:56'), "article_date_unresolved"),
    (lambda raw: raw.replace(b'2026-07-25T12:34:56+09:00', b'2026-07-24T12:34:56+09:00'), "article_outside_window"),
    (lambda raw: raw.replace(b'<meta property="article:published_time" content="2026-07-25T12:34:56+09:00">', b''), "article_date_unknown"),
    (lambda raw: raw.replace(b'</head>', b'<meta property="article:published_time" content="2026-07-26"></head>'), "article_date_conflict"),
    (lambda raw: raw.replace(b'<div id="articletxt">', b'<div class="paywall" id="articletxt">'), "access_restricted"),
])
def test_article_date_and_access_refusals_are_visible_not_dated_coverage(kit, change, code):
    site, values = kit
    site.route("/article/a1", change(article("2026-07-25")))
    result = run(values)
    assert result["candidateDispositions"][code] == 1
    assert "2026-07-25" not in result["dayCounts"]
    assert result["retainedInWindow"] == 2 and result["coverage"] != "all"
    requests = len(site.log)
    run(values, "resume")
    assert len(site.log) == requests


def test_day_precision_is_not_fabricated_midnight(kit):
    site, values = kit
    site.route("/article/a1", article("2026-07-25").replace(b'2026-07-25T12:34:56+09:00', b'2026-07-25'))
    run(values)
    record = next(json.loads(path.read_bytes()) for path in Path(values["stateDir"]).glob("private-news-*.json")
                  if json.loads(path.read_bytes())["publicationDay"] == "2026-07-25")
    assert record["publication"]["raw"] == "2026-07-25"
    assert record["publication"]["precision"] == "day"


def test_untrusted_xml_and_out_of_allowlist_redirect_never_escape_transport(kit):
    site, values = kit
    malicious = b'<!DOCTYPE urlset [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>&xxe;</loc></url></urlset>'
    site.route("/sitemap/daily-article/20260725.xml", malicious, content_type="application/xml")
    site.route("/article/a2", b"", status=302, headers={"Location": "http://localhost:9/never"})
    result = run(values)
    assert result["coverage"] == "unknown" and result["retainedInWindow"] == 1
    assert site.hits("/article/a1") == 0
    assert any(key in result["candidateDispositions"] for key in ("host_not_allowed", "private_synthetic_origin_invalid"))


def test_discovery_redirect_to_other_partition_rejected_before_get(kit):
    site, values = kit
    site.route("/sitemap/daily-article/20260725.xml", b"", status=302,
               headers={"Location": site.url("/sitemap/daily-article/20260724.xml")})
    result = run(values)
    assert result["partitionDispositions"]["archive_endpoint_invalid"] == 1
    assert site.hits("/sitemap/daily-article/20260724.xml") == 0


def test_http_429_blocks_host_across_resume(kit):
    site, values = kit
    site.route("/article/a1", b"refused", status=429)
    result = run(values)
    assert result["candidateDispositions"]["http_429"] == 1
    assert site.hits("/article/a2") == site.hits("/article/a3") == 0
    requests = len(site.log)
    run(values, "resume")
    assert len(site.log) == requests
    assert saved(values)["blocked"] == ["127.0.0.1"]


def test_saturated_gdelt_is_partial_and_seendate_is_not_publication(kit):
    site, values = kit
    values.update(fromDay="2026-07-25", throughDay="2026-07-25", maxDocuments=1,
                  sources=[{"name": "gdelt-doc", "sourceType": "discovery", "reliability": "synthetic", "queries": ['"SyntheticCo"']}])
    rows = [{"url": site.url(f"/article/g{i}"), "title": "synthetic", "seendate": "20260726T001500Z"} for i in range(250)]
    site.route("/api/v2/doc/doc", json.dumps({"articles": rows}).encode(), content_type="application/json")
    for index in range(250):
        site.route(f"/article/g{index}", article("2026-07-25"))
    result = run(values)
    assert result["saturatedPartitions"] == 1 and result["coverage"] == "some"
    assert result["candidates"] == 250 and result["pendingCandidates"] == 249
    assert result["dayCounts"] == {"2026-07-25": 1}
    record = json.loads(next(Path(values["stateDir"]).glob("private-news-*.json")).read_bytes())
    assert record["observedSourceKind"] == "unknown"
    assert record["discoveryRefs"][0]["published_at"] is None


@pytest.mark.parametrize("target", ["STATE.json", "PLAN.json", "foreign", ".stage-" + "a" * 32])
def test_symlink_and_foreign_namespace_are_not_adopted(kit, target):
    site, values = kit
    run(values)
    root = Path(values["stateDir"])
    outside = root.parent / "outside"
    outside.write_text("unrelated")
    existing = root / target
    if existing.exists():
        existing.unlink()
    existing.symlink_to(outside)
    with pytest.raises((IngestionFailure, OSError, ValueError)):
        run(values, "resume")
    assert outside.read_text() == "unrelated" and len(site.log) == 7


def test_corrupted_state_checksum_and_body_remain_visible(kit):
    site, values = kit
    run(values)
    root = Path(values["stateDir"])
    path = root / "STATE.json"
    original = path.read_bytes()
    envelope = json.loads(original)
    envelope["state"]["requests"] = 0
    path.write_text(json.dumps(envelope))
    with pytest.raises(IngestionFailure, match="private_state_corrupt"):
        run(values, "status")
    path.write_bytes(original)
    raw = next(root.glob("private-news-*.raw"))
    raw.write_bytes(b"corrupt")
    with pytest.raises(IngestionFailure, match="private_record_corrupt"):
        run(values, "resume")
    assert len(site.log) == 7


def test_no_clobber_and_external_hardlink_rejected(kit):
    _, values = kit
    run(values)
    root = Path(values["stateDir"])
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(FileExistsError):
            intake._publish(fd, "PLAN.json", b"replacement", immutable=True)
    finally:
        os.close(fd)
    raw = next(root.glob("private-news-*.raw"))
    os.link(raw, root.parent / "outside-hardlink")
    with pytest.raises(IngestionFailure, match="private_namespace_conflict"):
        run(values, "resume")


@pytest.mark.parametrize("extra", [{"rights": "known"}, {"modelSend": True}, {"publicUse": True},
                                    {"grant": {}}, {"nativeManifest": {}}, {"unknown": 1}])
def test_closed_operator_config_cannot_elevate_private_use(kit, extra):
    _, values = kit
    with pytest.raises(ValidationError):
        intake.Config.model_validate({**values, **extra})


def test_candidate_selection_cap_preserves_excess_candidates(kit):
    _, values = kit
    values.update(maxCandidates=1, maxArticleAttempts=1, maxDocuments=1)
    result = run(values)
    assert result["candidates"] == 3 and result["pendingCandidates"] == 2
    assert result["coverage"] == "some" and result["retainedInWindow"] == 1


def test_byte_and_wall_clock_budgets_do_not_reset_on_resume(kit):
    site, values = kit
    values["policy"]["maxRequests"] = 4
    first = run(values)
    data = saved(values)
    data["bytes"] = values["policy"]["maxTotalBytes"]
    set_state(values, data)
    requests = len(site.log)
    result = run(values, "resume")
    # Both exhausted counters are preserved, rather than starting a new transport budget.
    assert result["sourceBytes"] == values["policy"]["maxTotalBytes"]
    assert result["sourceRequests"] == first["sourceRequests"]
    assert len(site.log) == requests
    data = saved(values)
    data["startedAt"] = "2000-01-01T00:00:00+00:00"
    set_state(values, data)
    assert run(values, "resume")["retainedInWindow"] == 0
    assert len(site.log) == requests


def test_real_received_byte_budget_is_cumulative(kit):
    site, values = kit
    values["policy"].update(maxResponseBytes=600, maxTotalBytes=600)
    result = run(values)
    measured = result["sourceBytes"]
    assert 0 < measured <= 600
    assert result["retainedInWindow"] == 0
    assert "byte_budget" in result["partitionDispositions"] or "byte_budget" in result["candidateDispositions"]
    requests = len(site.log)
    resumed = run(values, "resume")
    assert resumed["sourceBytes"] == measured
    assert len(site.log) == requests


def test_per_publication_day_cap_remains_cumulative(kit):
    site, values = kit
    values["throughDay"] = values["fromDay"]
    site.route("/sitemap/daily-article/20260725.xml",
               sitemap([site.url("/article/same1"), site.url("/article/same2")]), content_type="application/xml")
    site.route("/article/same1", article("2026-07-25"))
    site.route("/article/same2", article("2026-07-25"))
    result = run(values)
    assert result["retainedInWindow"] == 1 and result["candidateDispositions"]["publication_day_cap"] == 1
    assert result["coverage"] == "some"
    requests = len(site.log)
    assert run(values, "resume")["dayCounts"] == {"2026-07-25": 1}
    assert len(site.log) == requests


def test_owned_namespace_lock_excludes_second_operator(kit):
    _, values = kit
    run(values)
    config = intake.Config.model_validate(values)
    first = intake.State(config, "status")
    try:
        with pytest.raises(IngestionFailure, match="private_busy"):
            intake.State(config, "resume")
    finally:
        first.close()


def test_small_cap_spreads_across_the_whole_calendar_window():
    days = [f"2026-07-{day:02d}" for day in range(1, 32)]
    selected = intake._balanced_days(days)
    assert selected[:3] == ["2026-07-01", "2026-07-31", "2026-07-16"]
    assert set(selected) == set(days)


def test_cumulative_wall_clock_expires_before_any_transport(kit):
    site, values = kit
    config = intake.Config.model_validate(values)
    state = intake.State(config, "run")
    try:
        state.data["startedAt"] = "2000-01-01T00:00:00+00:00"
        state.save()
    finally:
        state.close()
    result = run(values, "resume")
    assert result["stopCode"] == "timeout" and result["sourceRequests"] == 0
    assert result["pendingPartitions"] == 3 and result["retainedInWindow"] == 0
    assert site.log == []
    assert run(values, "resume")["sourceRequests"] == 0


def test_nanosecond_metadata_preserves_precision_and_original_calendar_date(kit):
    site, values = kit
    value = "2026-07-25T23:59:59.123456789-11:00"
    site.route("/article/a1", article("2026-07-25").replace(b"2026-07-25T12:34:56+09:00", value.encode()))
    result = run(values)
    assert result["dayCounts"]["2026-07-25"] == 1
    record = next(json.loads(path.read_bytes()) for path in Path(values["stateDir"]).glob("private-news-*.json")
                  if json.loads(path.read_bytes())["publicationDay"] == "2026-07-25")
    assert record["publication"]["raw"] == value and record["publication"]["precision"] == "instant"


def test_exact_text_duplicates_are_counted_without_source_independence_claim(kit):
    site, values = kit
    values.update(throughDay="2026-07-25", perDayCap=2)
    site.route("/sitemap/daily-article/20260725.xml",
               sitemap([site.url("/article/dup1"), site.url("/article/dup2")]), content_type="application/xml")
    for path in ("/article/dup1", "/article/dup2"):
        site.route(path, article("2026-07-25"))
    result = run(values)
    assert result["retainedInWindow"] == 2 and result["exactTextDuplicateGroups"] == 1
    assert result["sourceCounts"] == {"hankyung-daily": 2}
    assert result["domainCounts"] == {"127.0.0.1": 2}


def test_nonqualifying_response_keeps_private_hash_and_metadata_not_a_body_record(kit):
    site, values = kit
    raw = article("2026-07-24")
    site.route("/article/a1", raw)
    result = run(values)
    data = saved(values)
    attempt = next(a for a in data["attempts"] if a.get("code") == "article_outside_window")
    assert attempt["response"]["rawSha256"] == intake.byte_hash(raw)
    assert attempt["articleMetadata"]["publication"]["day"] == "2026-07-24"
    identifier = attempt["key"]
    assert not (Path(values["stateDir"]) / (identifier + ".raw")).exists()
    assert not (Path(values["stateDir"]) / (identifier + ".json")).exists()
    assert "2026-07-24" not in result["dayCounts"] and PRIVATE not in canonical(result)


def test_native_looking_fields_in_private_record_are_corruption(kit):
    _, values = kit
    run(values)
    path = next(Path(values["stateDir"]).glob("private-news-*.json"))
    record = json.loads(path.read_bytes())
    record["grant"] = {"rights": "known"}
    path.write_text(canonical(record))
    with pytest.raises(IngestionFailure, match="private_record_corrupt"):
        run(values, "status")


@pytest.mark.parametrize("raw,day", [
    ("2026-08-20", "2026-08-20"),
    ("2026.08.20", "2026-08-20"),
    ("2026.09.30", "2026-09-30"),
    ("October 21, 2026", "2026-10-21"),
    ("August 26, 2026", "2026-08-26"),
    ("August 27, 2026", "2026-08-27"),
    ("January 1, 2026", "2026-01-01"),
    ("December 31, 2026", "2026-12-31"),
    ("2024.02.29", "2024-02-29"),
    ("February 29, 2024", "2024-02-29"),
])
def test_private_publication_calendar_spellings_preserve_raw_without_time_or_zone(raw, day):
    publication = intake._publication(raw)
    assert publication["raw"] == raw
    assert publication["day"] == day
    assert publication["precision"] == "day"
    assert "T" not in publication["day"] and not publication["day"].endswith("Z")


@pytest.mark.parametrize("raw", [
    "2026-02-29", "2026-09-31", "0000-08-20",
    "2026.02.29", "2026.09.31", "2026.00.20", "2026.13.20", "0000.08.20",
    "February 29, 2026", "April 31, 2026", "August 0, 2026", "August 32, 2026",
    "August 26, 0000", "August 26, 10000", "August 026, 2026",
    "2026.8.20", "2026.08.2", "2026/08/20", "2026.08.20Z", "2026.08.20T00:00:00",
    "Aug 26, 2026", "august 26, 2026", "AUGUST 26, 2026", "August 26,2026",
    "August 26 2026", "August 26, 2026 UTC", "26 August 2026", "August 01, 2026",
    " 2026.08.20", "2026.08.20 ", " August 26, 2026", "August 26, 2026 ",
    "2026-08-27Z", "2026-08-27+00:00",
])
def test_private_publication_calendar_validation_rejects_invalid_or_inferred_formats(raw):
    with pytest.raises(IngestionFailure, match="article_date_invalid"):
        intake._publication(raw)


@pytest.mark.parametrize("phase", ["discovery", "article"])
def test_settled_target_timeout_keeps_healthy_unattempted_work_and_never_retries(kit, phase):
    site, values = kit
    values["policy"]["timeoutSeconds"] = 1
    failed_path = "/sitemap/daily-article/20260725.xml" if phase == "discovery" else "/article/a1"
    original = site.routes[failed_path]
    site.route(failed_path, original["body"], content_type=original["headers"]["Content-Type"], delay=1.5)
    result = run(values)
    data = saved(values)
    failures = [attempt for attempt in data["attempts"] if attempt.get("code") == "timeout"]
    assert len(failures) == 1 and failures[0]["status"] == "refused"
    assert failures[0]["kind"] == phase
    assert site.hits(failed_path) == 1
    assert result["retainedInWindow"] == 2
    assert result["dayCounts"] == {"2026-07-26": 1, "2026-07-27": 1}
    assert result["pendingCandidates"] == 0
    assert result["stopCode"] is None
    assert result["sourceRequests"] == len(site.log) < values["policy"]["maxRequests"]
    assert result["unknownRequests"] == 0 and data["pendingRequest"] is None
    assert result["sourceBytes"] == sum(
        len(site.routes[entry["path"].split("?")[0]]["body"])
        for entry in site.log if entry["path"] != failed_path)
    requests = len(site.log)
    resumed = run(values, "resume")
    assert resumed["retainedInWindow"] == 2 and resumed["sourceRequests"] == result["sourceRequests"]
    assert resumed["sourceBytes"] == result["sourceBytes"]
    assert site.hits(failed_path) == 1 and len(site.log) == requests


def test_target_pacing_refusal_does_not_stop_other_permitted_host(tmp_path, monkeypatch):
    values = config_data(tmp_path.resolve(), "http://127.0.0.1:1")
    values.pop("syntheticBaseUrl")
    values.update(throughDay="2026-07-25", maxListingPages=1, maxCandidates=2,
                  maxArticleAttempts=2, maxDocuments=2, perDayCap=2,
                  sources=[{"name": "gdelt-doc", "sourceType": "discovery",
                            "reliability": "authored transport fixture", "queries": ['"SyntheticCo"']}],
                  exactArticleHosts=["a-paced.example.org", "z-healthy.example.org"])
    values["policy"].update(syntheticLoopback=False, minIntervalSeconds=2, timeoutSeconds=5)
    slow = "https://a-paced.example.org/article/slow"
    healthy = "https://z-healthy.example.org/article/healthy"
    listings = json.dumps({"articles": [{"url": slow}, {"url": healthy}]}).encode()
    observed = []
    waits = []

    class Body(httpx.AsyncByteStream):
        def __init__(self, raw):
            self.raw = raw

        async def __aiter__(self):
            yield self.raw

    def handle(request):
        host, path = request.headers["host"], request.url.path
        if path == "/robots.txt":
            raw = b"User-agent: *\nAllow: /\n"
            if host == "a-paced.example.org":
                raw += b"Crawl-delay: 10\n"
            media = "text/plain"
        elif host == "api.gdeltproject.org" and path == "/api/v2/doc/doc":
            raw, media = listings, "application/json"
        elif host == "z-healthy.example.org" and path == "/article/healthy":
            raw, media = article("2026-07-25"), "text/html"
        else:
            pytest.fail(f"unexpected authored transport request: {host}{path}")
        observed.append({"host": host, "path": path, "bytes": len(raw)})
        return httpx.Response(200, headers={"Content-Type": media, "Content-Length": str(len(raw))},
                              stream=Body(raw))

    original_client = httpx.AsyncClient

    def client(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handle), **kwargs)

    # Replace only network/DNS and wall-clock waiting boundaries; keep native robots,
    # target deadline, request counting, parsing and private persistence real.
    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(collection_transport, "_resolve", lambda *args: ["93.184.216.34"])
    monkeypatch.setattr(collection_transport.time, "sleep", waits.append)
    result = run(values)
    data = saved(values)
    assert result["candidateDispositions"]["rate_limit"] == 1
    assert result["retainedInWindow"] == 1 and result["pendingCandidates"] == 0
    assert result["stopCode"] is None
    assert result["sourceRequests"] == len(observed) == 5
    assert result["sourceBytes"] == sum(entry["bytes"] for entry in observed)
    assert result["unknownRequests"] == 0 and data["pendingRequest"] is None
    assert waits and all(0 < wait <= 2 for wait in waits)
    assert not any(entry["host"] == "a-paced.example.org" and entry["path"] == "/article/slow" for entry in observed)
    record = json.loads(next(Path(values["stateDir"]).glob("private-news-*.json")).read_bytes())
    assert record["requestUrl"] == healthy and PRIVATE in record["prepared"]["text"]
    attempts = [attempt for attempt in data["attempts"] if attempt.get("code") == "rate_limit"]
    assert len(attempts) == 1 and attempts[0]["status"] == "refused"
    requests = len(observed)
    assert run(values, "resume")["sourceRequests"] == requests
    assert len(observed) == requests


def test_actual_total_deadline_remains_globally_latched_across_resume(kit):
    site, values = kit
    values["policy"].update(timeoutSeconds=1, maxTotalSeconds=1)
    failed_path = "/sitemap/daily-article/20260725.xml"
    site.route(failed_path, site.routes[failed_path]["body"], content_type="application/xml", delay=1.5)
    result = run(values)
    data = saved(values)
    assert result["stopCode"] == "timeout" and result["retainedInWindow"] == 0
    assert result["pendingPartitions"] == 2
    assert result["sourceRequests"] == len(site.log) == 2
    assert result["unknownRequests"] == 0 and data["pendingRequest"] is None
    assert site.hits(failed_path) == 1
    assert not any(entry["path"].startswith("/article/") for entry in site.log)
    requests = len(site.log)
    resumed = run(values, "resume")
    assert resumed["stopCode"] == "timeout" and resumed["pendingPartitions"] == 2
    assert resumed["sourceRequests"] == result["sourceRequests"]
    assert resumed["sourceBytes"] == result["sourceBytes"]
    assert len(site.log) == requests


def test_specific_corporate_adapter_wins_over_earlier_gdelt_reference(kit):
    site, values = kit
    values.update(throughDay="2026-07-25", sources=[
        {"name": "gdelt-doc", "sourceType": "discovery", "reliability": "metadata only", "queries": ['"SyntheticCo"']},
        {"name": "nvidia-newsroom", "sourceType": "corporate-pr", "reliability": "publisher authored", "queries": []},
    ])
    url = site.url("/news/synthetic-release")
    site.route("/api/v2/doc/doc", json.dumps({"articles": [{"url": url}]}).encode(), content_type="application/json")
    site.route("/sitemap.xml", sitemap([url]), content_type="application/xml")
    site.route("/cats/press_release.xml", b'<rss version="2.0"><channel/></rss>', content_type="application/rss+xml")
    raw = (f'<html><head><title>Synthetic corporate release</title></head><body>'
           f'<div class="article-date">July 25, 2026</div><div class="article-body"><p>{PRIVATE}'
           f' authored corporate body.</p></div><aside>EXCLUDED_CORPORATE_SIDEBAR</aside></body></html>').encode()
    site.route("/news/synthetic-release", raw)
    result = run(values)
    assert result["retainedInWindow"] == 1
    record_path = next(Path(values["stateDir"]).glob("private-news-*.json"))
    record = json.loads(record_path.read_bytes())
    assert record["source"] == "nvidia-newsroom" and record["observedSourceKind"] == "corporate-pr"
    assert record["declaredSourceType"] == "corporate-pr"
    assert record["publication"]["raw"] == "July 25, 2026" and record["publicationDay"] == "2026-07-25"
    assert {ref["source"] for ref in record["discoveryRefs"]} == {"gdelt-doc", "nvidia-newsroom"}
    assert record["discoveryRefs"][0]["source"] == "gdelt-doc"
    assert PRIVATE in record["prepared"]["text"] and "EXCLUDED_CORPORATE_SIDEBAR" not in record["prepared"]["text"]
    assert record_path.with_suffix(".raw").read_bytes() == raw
    assert site.hits("/news/synthetic-release") == 1
    requests = len(site.log)
    assert run(values, "resume")["retainedInWindow"] == 1
    assert len(site.log) == requests


def test_state_parent_durability_failure_refuses_before_any_fetch(kit, monkeypatch):
    site, values = kit
    parent = Path(values["stateDir"]).parent.stat()
    original_fsync = os.fsync

    def fail_parent_sync(fd):
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (parent.st_dev, parent.st_ino):
            raise OSError(errno.EIO, "synthetic parent directory durability failure")
        return original_fsync(fd)

    # This asserts refusal when namespace durability cannot be established, not
    # that a process-kill test can reproduce a filesystem's power-loss behavior.
    monkeypatch.setattr(os, "fsync", fail_parent_sync)
    with pytest.raises(OSError, match="synthetic parent directory durability failure"):
        run(values)
    assert site.log == []
    assert not list(Path(values["stateDir"]).glob("private-news-*"))


def test_committed_record_recovery_preserves_selected_source_counts_without_refetch(kit, monkeypatch):
    site, values = kit
    values.update(throughDay="2026-07-25", sources=[
        {"name": "gdelt-doc", "sourceType": "discovery", "reliability": "metadata only", "queries": ['"SyntheticCo"']},
        {"name": "hankyung-daily", "sourceType": "editorial", "reliability": "authored fixture", "queries": []},
    ])
    url = site.url("/article/a1")
    site.route("/api/v2/doc/doc", json.dumps({"articles": [{"url": url}]}).encode(), content_type="application/json")
    original_publish = intake._publish
    interrupted = False

    def interrupt_after_record(fd, name, raw, **options):
        nonlocal interrupted
        original_publish(fd, name, raw, **options)
        if name.startswith("private-news-") and name.endswith(".json") and not interrupted:
            interrupted = True
            raise SimulatedCrash()

    monkeypatch.setattr(intake, "_publish", interrupt_after_record)
    with pytest.raises(SimulatedCrash):
        run(values)
    assert interrupted and site.hits("/article/a1") == 1
    record = json.loads(next(Path(values["stateDir"]).glob("private-news-*.json")).read_bytes())
    assert record["source"] == "hankyung-daily"
    assert record["discoveryRefs"][0]["source"] == "gdelt-doc"
    monkeypatch.setattr(intake, "_publish", original_publish)
    requests = len(site.log)
    result = run(values, "resume")
    assert result["retainedInWindow"] == 1
    assert result["sourceCounts"] == {"hankyung-daily": 1}
    assert result["sourceCounts"] == {record["source"]: 1}
    assert len(site.log) == requests and site.hits("/article/a1") == 1
    assert run(values, "status")["sourceCounts"] == result["sourceCounts"]


def paged_config(values, source=None):
    result = {key: value for key, value in values.items()
              if key not in {"maxListingPages", "maxCandidates", "maxDocuments", "maxArticleAttempts", "perDayCap"}}
    result.update(schemaVersion="zoop-private-news-config-2", selectionMode="fresh-first")
    if source is not None:
        result["sources"] = [{"name": source.source_id, "sourceType": source.category,
                              "reliability": "authored synthetic fixture", "queries": [], "descriptor": source.wire()}]
    return result


def test_v2_finishes_finite_multi_page_corpus_without_day_document_or_attempt_quota(kit):
    site, values = kit
    source = descriptor("paged-fixture", "editorial", [
        surface("listing", "https://publisher.example/list", routes=[r"/list(?:/[1-3])?"], coverage="finite-index")],
        ["publisher.example"], [r"/article/[0-9]+"], bodies=["//article"])
    values = paged_config(values, source)
    values["policy"] = {**values["policy"], "maxRequests": 220, "maxTotalBytes": 8_000_000}
    # More than one queue chunk and many more than the former per-day=1 quota.
    for page in range(1, 4):
        links = "".join(f'<a href="{site.url(f"/article/{index}")}">SyntheticCo {index}</a>'
                        for index in range((page - 1) * 50, page * 50))
        following = f'<a rel="next" href="/list/{page + 1}">Next</a>' if page < 3 else ""
        route = "/list" if page == 1 else f"/list/{page}"
        site.route(route, f"<html><main>{links}{following}</main></html>".encode())
    for index in range(150):
        site.route(f"/article/{index}", article("2026-07-27"))
    result = run(values)
    assert result["retainedInWindow"] == 150 and result["dayCounts"] == {"2026-07-27": 150}
    assert result["pendingCandidates"] == 0 and result["pendingPartitions"] == 0
    assert result["stopCode"] is None and result["coverage"] == "all"
    root = Path(values["stateDir"])
    assert saved(values)["candidates"] == "sqlite:candidates"
    assert (root / "STATE.json").stat().st_size < 10_000
    pins = list(intake.retained_items(intake.Config.model_validate(values)))
    assert len(pins) == 150
    assert set(pins[0]) == {"sourceId", "stateDir", "recordPath", "recordSha256", "privateId", "planId"}
    before = len(site.log)
    assert run(values, "resume")["retainedInWindow"] == 150
    assert len(site.log) == before


def test_v2_fresh_feed_is_acquired_before_old_sitemap_candidates(kit):
    site, values = kit
    source = descriptor("fresh-fixture", "editorial", [
        surface("sitemap", "https://publisher.example/archive.xml", coverage="finite-index"),
        surface("feed", "https://publisher.example/feed")],
        ["publisher.example"], [r"/article/[a-z0-9]+"], bodies=["//article"])
    values = paged_config(values, source)
    values["policy"] = {**values["policy"], "maxRequests": 3}
    site.route("/archive.xml", sitemap([site.url("/article/old")]), content_type="application/xml")
    site.route("/article/old", article("2020-01-01"))
    site.route("/feed", ('<rss version="2.0"><channel><item><link>' + site.url("/article/fresh") +
                        '</link><title>Authored</title><pubDate>Mon, 27 Jul 2026 12:00:00 GMT</pubDate>'
                        '</item></channel></rss>').encode(), content_type="application/rss+xml")
    site.route("/article/fresh", article("2026-07-27"))
    result = run(values)
    assert result["retainedInWindow"] == 1 and result["stopCode"] == "request_budget"
    assert site.hits("/article/fresh") == 1 and site.hits("/article/old") == 0
    assert site.hits("/archive.xml") == 0 and result["pendingPartitions"] == 1
    assert result["coverage"] != "all"


def test_v2_discovery_duplicates_never_mutate_retained_record_refs(kit):
    site, values = kit
    source = descriptor("duplicate-fixture", "editorial", [
        surface("feed", "https://publisher.example/feed"),
        surface("sitemap", "https://publisher.example/map.xml", coverage="finite-index")],
        ["publisher.example"], [r"/article/a1"], bodies=["//article"])
    values = paged_config(values, source)
    site.route("/feed", ('<rss version="2.0"><channel><item><link>' + site.url("/article/a1") +
                        '</link></item></channel></rss>').encode(), content_type="application/rss+xml")
    site.route("/map.xml", sitemap([site.url("/article/a1")]), content_type="application/xml")
    result = run(values)
    assert result["retainedInWindow"] == 1 and site.hits("/article/a1") == 1
    record = json.loads(next(Path(values["stateDir"]).glob("private-news-*.json")).read_bytes())
    assert len(record["discoveryRefs"]) == 1
    assert run(values, "status")["retainedInWindow"] == 1


@pytest.mark.parametrize("field", ["maxListingPages", "maxCandidates", "maxDocuments", "maxArticleAttempts", "perDayCap"])
def test_v2_rejects_accidentally_reintroduced_product_quotas(kit, field):
    _, values = kit
    values = paged_config(values)
    values[field] = 1
    with pytest.raises(ValidationError, match="resource budgets"):
        intake.Config.model_validate(values)


def test_v2_declared_source_policy_denial_never_sends_any_request(kit):
    site, values = kit
    source = descriptor("policy-denied-fixture", "editorial", [surface("feed", "https://publisher.example/feed")],
                        ["publisher.example"], [r"/article/a1"], access_status="blocked-policy",
                        access_reason="authored denial fixture")
    result = run(paged_config(values, source))
    assert not site.log and result["retainedInWindow"] == 0
    assert result["partitionDispositions"]["archive_source_policy_denied"] == 1
    assert result["coverage"] == "unknown"


@pytest.mark.parametrize("after_record", [False, True])
def test_v2_crash_recovery_keeps_unknown_attempt_without_refetch(kit, monkeypatch, after_record):
    site, values = kit
    values = paged_config(values)
    original = intake._publish
    interrupted = False

    def stop(fd, name, raw, **options):
        nonlocal interrupted
        original(fd, name, raw, **options)
        if name.startswith("private-news-") and name.endswith(".json" if after_record else ".raw") and not interrupted:
            interrupted = True
            raise SimulatedCrash()

    monkeypatch.setattr(intake, "_publish", stop)
    with pytest.raises(SimulatedCrash):
        run(values)
    monkeypatch.setattr(intake, "_publish", original)
    attempted = [row["path"] for row in site.log if row["path"].startswith("/article/")]
    assert len(attempted) == 1
    result = run(values, "resume")
    assert site.hits(attempted[0]) == 1
    assert result["retainedInWindow"] == (3 if after_record else 2)


def extracted_fixture(*, backend="deepseek-fetch", cause=None):
    from zoop_ai_pipeline.extraction_fallback import (
        DEFUDDLE_PROFILE, FETCH_COST_NANO, MARKDOWN_PROFILE, FrozenExtractedPage,
        NativePageObservation, ObservedMetadata, ProviderReceipt, prepare_markdown,
    )
    url = "https://openai.com/index/authored-fixture/"
    day, observed = "2026-07-27", "2026-07-27T12:00:00+00:00"
    if backend == "deepseek-fetch":
        text = "# Authored fixture\n\nJuly 27, 2026\n\nSynthetic prose with `code`, [link](https://example.com/) and \\\\ escapes.\n"
        native = (NativePageObservation(url, observed, None, failure_code="host_blocked", access="public", known_unsent=cause)
                  if cause else NativePageObservation(url, observed, 403, final_url=url, failure_code="http_403", access="public"))
        receipt = ProviderReceipt("authored-attempt", observed, 200, "success",
                                  canonical({"title": "Authored fixture", "content": text}).encode(),
                                  actual_nano=FETCH_COST_NANO)
        metadata, prepared, parser, final, representation = (
            ObservedMetadata(title="Authored fixture"), prepare_markdown(text), MARKDOWN_PROFILE, None, "markdown")
    else:
        text = "<html><body><p>Synthetic extracted prose.</p></body></html>"
        native = NativePageObservation(url, observed, 200, final_url=url, media_type="text/html",
                                      body=b"<html><body><div>Synthetic original prose.</div></body></html>",
                                      failure_code="article_scope_ambiguous_or_missing", access="public")
        receipt = None
        metadata = ObservedMetadata(title="Authored fixture", published_at=day)
        prepared = intake.prepare(text.encode(), "text/html", "//body")
        parser = {**intake.profile("//body"), **DEFUDDLE_PROFILE, "coordinates": "retained-extracted-html-dom"}
        final, representation = url, "html"
    page = FrozenExtractedPage(url, final, backend, observed, representation, text, native, metadata,
                               canonical(parser), canonical(prepared), receipt, ("authored-native-refusal",))
    raw = text.encode()
    identifier = "private-news-" + digest(["authored-plan", url])
    envelope = canonical(page.wire()).encode()
    record = {"schemaVersion": "zoop-private-news-record-2", "privateId": identifier,
              "provenance": "private-public-web-extracted", "planDigest": "a" * 64,
              "source": "openai-newsroom", "discoveryRefs": [], "requestUrl": url, "finalUrl": final,
              "canonicalUrl": None, "redirects": [], "robots": [{"url": "https://openai.com/robots.txt", "status": 200}],
              "title": "Authored fixture", "publication": intake._publication(day), "publicationDay": day,
              "observedAt": observed, "publisher": None, "declaredSourceType": "corporate-pr",
              "declaredReliability": "authored fixture", "observedSourceKind": "corporate-pr", "articleXPath": None,
              "rawSha256": intake.byte_hash(raw), "rawBytes": len(raw), "textSha256": intake.byte_hash(prepared["text"].encode()),
              "parserProfile": parser, "prepared": prepared, "literalAliasMatches": [],
              "extractionArtifact": {"file": identifier + ".extraction.json", "sha256": intake.byte_hash(envelope)},
              "extractionBackend": backend, "representation": representation, **intake.USE}
    return record, raw, envelope, page


@pytest.mark.parametrize("backend", ["deepseek-fetch", "defuddle"])
def test_record2_pure_verifier_preserves_new_coordinates_and_original_unknowns(backend):
    record, raw, envelope, _ = extracted_fixture(backend=backend)
    assert intake.verify_record(record, raw, extraction_raw=envelope) == record
    assert record["modelSend"] is False and record["publicUse"] is False
    if backend == "deepseek-fetch":
        assert record["prepared"]["text"] == raw.decode() and record["finalUrl"] is None
        assert json.loads(envelope)["metadata"]["publishedAt"] is None
        assert record["publication"]["precision"] == "day"
    with pytest.raises(IngestionFailure):
        intake.verify_record(record, raw + b"x", extraction_raw=envelope)
    with pytest.raises(IngestionFailure):
        intake.verify_record({**record, "modelSend": True}, raw, extraction_raw=envelope)
    with pytest.raises(IngestionFailure):
        intake.verify_record({**record, "publicationDay": "2026-07-26"}, raw, extraction_raw=envelope)
    with pytest.raises(IngestionFailure):
        intake.verify_record({**record, "publisher": "Invented publisher"}, raw, extraction_raw=envelope)


def test_record2_causal_receipt_requires_exact_separate_retained_bytes():
    from zoop_ai_pipeline.extraction_fallback import NativePageObservation, PriorPublicClient403
    prior = NativePageObservation("https://openai.com/index/prior-fixture/", "2026-07-27T11:00:00+00:00", 403,
                                  final_url="https://openai.com/index/prior-fixture/", failure_code="http_403", access="public")
    raw_cause = canonical(prior.wire()).encode()
    sha = intake.byte_hash(raw_cause)
    cause = PriorPublicClient403(prior, f"native-{sha}.json", sha,
                                "https://openai.com/index/authored-fixture/", "2026-07-27T10:00:00+00:00")
    record, raw, envelope, _ = extracted_fixture(cause=cause)
    with pytest.raises(IngestionFailure):
        intake.verify_record(record, raw, extraction_raw=envelope)
    with pytest.raises(IngestionFailure):
        intake.verify_record(record, raw, extraction_raw=envelope, causal_raw=raw_cause + b"\n")
    assert intake.verify_record(record, raw, extraction_raw=envelope, causal_raw=raw_cause) == record


def public_offline_config(tmp_path):
    values = paged_config(config_data(tmp_path, "http://127.0.0.1:18765"))
    values.update(syntheticBaseUrl=None, exactArticleHosts=["openai.com"],
                  sources=[{"name": "openai-newsroom", "sourceType": "corporate-pr",
                            "reliability": "authored fixture", "queries": []}])
    values["policy"].update(syntheticLoopback=False, minIntervalSeconds=2)
    return intake.Config.model_validate(values)


def test_record2_state_retention_status_and_streaming_pins_are_offline(tmp_path):
    config = public_offline_config(tmp_path)
    _, _, _, page = extracted_fixture()
    state = intake.State(config, "run")
    try:
        identifier = "private-news-" + digest([config.plan_id, page.requested_url])
        state.data["candidates"][identifier] = {"url": page.requested_url, "status": "attempting", "refs": []}
        item = state.data["candidates"][identifier]
        meta = intake.archives.ArticleMeta("Authored fixture", "2026-07-27", None, None, None, "corporate-pr")
        record = intake._retain_extracted(config, state, identifier, item, "openai-newsroom", config.sources[0],
                                          meta, intake._publication(meta.published_at), page, [])
        item.update(status="retained", publicationDay=record["publicationDay"], textSha256=record["textSha256"],
                    source="openai-newsroom", literalAliasMatches=[])
        state.save()
    finally:
        state.close()
    before = {path.name: path.read_bytes() for path in Path(config.state_dir).iterdir()}
    result = intake.status(config)
    pins = list(intake.retained_items(config))
    assert result["retainedInWindow"] == 1 and result["sourceRequests"] == 0
    assert len(pins) == 1 and pins[0]["recordSha256"] == intake.byte_hash(before[identifier + ".json"])
    assert before == {path.name: path.read_bytes() for path in Path(config.state_dir).iterdir()}


def test_known_unsent_proof_uses_cached_exact_url_robots_and_never_unblocks_native(tmp_path):
    from zoop_ai_pipeline.extraction_fallback import NativePageObservation
    config = public_offline_config(tmp_path)
    state = intake.State(config, "run")
    try:
        prior = NativePageObservation("https://openai.com/index/prior-fixture/", "2026-07-27T11:00:00+00:00", 403,
                                      final_url="https://openai.com/index/prior-fixture/", failure_code="http_403", access="public")
        rules = collection_transport.parse_robots(b"User-agent: *\nDisallow: /index/denied/\n", "ZoopSyntheticPrivateNews/1.0")
        fetcher = SimpleNamespace(state=state, _robots={"https://openai.com": rules},
                                  robots_observed_at={"https://openai.com": "2026-07-27T10:00:00+00:00"},
                                  _blocked={"openai.com"})
        intake._retain_client403(fetcher, prior)
        observed = intake._known_unsent_observation(fetcher, "https://openai.com/index/authored-fixture/")
        assert observed.http_status is None and observed.body is None and observed.final_url is None
        assert observed.known_unsent.observation == prior and fetcher._blocked == {"openai.com"}
        with pytest.raises(IngestionFailure, match="host_blocked"):
            intake._known_unsent_observation(fetcher, "https://openai.com/index/denied/")
        fetcher._robots.clear()
        with pytest.raises(IngestionFailure, match="host_blocked"):
            intake._known_unsent_observation(fetcher, "https://openai.com/index/authored-fixture/")
    finally:
        state.close()


def successor_values(values, suffix):
    old_root = Path(values["stateDir"])
    result = json.loads(json.dumps(values))
    result.update(planId=values["planId"] + suffix, stateDir=str(old_root.parent / (old_root.name + suffix)),
                  predecessor={"stateDir": str(old_root), "planSha256": intake.byte_hash((old_root / "PLAN.json").read_bytes()),
                               "stateSha256": intake.byte_hash((old_root / "STATE.json").read_bytes()),
                               "queueSha256": intake.byte_hash((old_root / "QUEUE.sqlite3").read_bytes())})
    if result.get("fallback"):
        result["fallback"]["setId"] += suffix
    return result


def namespace_fingerprint(root):
    return {path.name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode), path.stat().st_mtime_ns)
            for path in Path(root).iterdir()}


def test_successor_chunks_finish_pending_work_without_refetch_or_predecessor_mutation(kit):
    site, original = kit
    values = paged_config(original)
    values["policy"] = {**values["policy"], "maxRequests": 3}
    first = run(values)
    assert first["currentRetainedInWindow"] == 1 and first["continuationEligible"]
    first_snapshot = namespace_fingerprint(values["stateDir"])
    second_values = successor_values(values, "-second")
    second_values["selectionMode"] = "backfill"
    second = run(second_values)
    assert second["currentRetainedInWindow"] == 1 and second["inheritedRetainedInWindow"] == 1
    assert second["pendingCandidates"] == 1 and second["continuationEligible"]
    assert namespace_fingerprint(values["stateDir"]) == first_snapshot
    second_snapshot = namespace_fingerprint(second_values["stateDir"])
    third_values = successor_values(second_values, "-third")
    third = run(third_values)
    assert third["currentRetainedInWindow"] == 1 and third["inheritedRetainedInWindow"] == 2
    assert third["currentDiscoveredCandidates"] == 0 and third["coverage"] == "all"
    assert not third["continuationEligible"] and third["sourceRequests"] == 1
    assert len(list(intake.retained_items(intake.Config.model_validate(third_values)))) == 1
    assert namespace_fingerprint(values["stateDir"]) == first_snapshot
    assert namespace_fingerprint(second_values["stateDir"]) == second_snapshot
    assert site.hits("/robots.txt") == 1
    assert all(site.hits(f"/article/a{index}") == 1 for index in (1, 2, 3))


def test_known_unsent_discovery_budget_keeps_partition_for_successor(kit):
    site, original = kit
    values = paged_config(original)
    values["policy"] = {**values["policy"], "maxRequests": 1}
    first = run(values)
    assert first["sourceRequests"] == 1 and first["pendingPartitions"] == 3
    assert first["currentRetainedInWindow"] == 0 and first["continuationEligible"]
    assert not first["discoveredCorpusExhausted"]
    successor = successor_values(values, "-next")
    successor["policy"]["maxRequests"] = 20
    result = run(successor)
    assert result["currentRetainedInWindow"] == 3 and result["coverage"] == "all"
    assert site.hits("/robots.txt") == 1


@pytest.mark.parametrize("change,code", [
    (lambda value: value["predecessor"].update(queueSha256="0" * 64), "private_predecessor_pin_mismatch"),
    (lambda value: value.update(throughDay="2026-07-28"), "private_predecessor_scope_mismatch"),
    (lambda value: value["policy"].update(userAgent="AnotherHonestClient/1.0"), "private_predecessor_scope_mismatch"),
])
def test_successor_refuses_pin_or_scope_changes_before_network(kit, change, code):
    site, original = kit
    values = paged_config(original)
    values["policy"] = {**values["policy"], "maxRequests": 3}
    run(values)
    before = namespace_fingerprint(values["stateDir"])
    request_count = len(site.log)
    successor = successor_values(values, "-invalid")
    change(successor)
    with pytest.raises(IngestionFailure, match=code):
        run(successor)
    assert len(site.log) == request_count and namespace_fingerprint(values["stateDir"]) == before


def test_successor_refuses_active_or_unsettled_predecessor_without_recovery(kit):
    site, original = kit
    values = paged_config(original)
    values["policy"] = {**values["policy"], "maxRequests": 3}
    run(values)
    previous = intake.State(intake.Config.model_validate(values), "status")
    try:
        with pytest.raises(IngestionFailure, match="private_predecessor_busy"):
            run(successor_values(values, "-busy"))
    finally:
        previous.close()
    journal = Path(values["stateDir"]) / "QUEUE.sqlite3-journal"
    journal.write_bytes(b"AUTHORED_UNSETTLED_JOURNAL")
    before = namespace_fingerprint(values["stateDir"])
    count = len(site.log)
    with pytest.raises(IngestionFailure, match="private_predecessor_unsettled"):
        run(successor_values(values, "-unsettled"))
    assert namespace_fingerprint(values["stateDir"]) == before and len(site.log) == count


def test_provider_unsent_allowance_preserves_native_observation_across_successor(tmp_path, monkeypatch):
    from zoop_ai_pipeline.extraction_fallback import FETCH_COST_NANO, ProviderReceipt
    config = public_offline_config(tmp_path)
    values = config.wire()
    values["fallback"] = {"enabled": True, "setId": "authored-fetch-set", "sourceId": "openai-newsroom",
                          "approvalRef": "authored-no-network-fixture", "budgetConfigPath": str(tmp_path / "not-read-budget.json"),
                          "budgetConfigSha256": "a" * 64, "setProofPath": str(tmp_path / "not-read-set.json"),
                          "setProofSha256": "b" * 64, "allowedHosts": ["openai.com"], "maxCalls": 1}
    config = intake.Config.model_validate(values)
    url = "https://openai.com/index/authored-fixture/"
    requests = []
    original_client = httpx.AsyncClient

    class AuthoredStream(httpx.AsyncByteStream):
        def __init__(self, raw):
            self.raw = raw

        async def __aiter__(self):
            yield self.raw

    def transport(request):
        requests.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, stream=AuthoredStream(b"User-agent: *\nAllow: /\n"), headers={"content-type": "text/plain"})
        if request.url.path == "/news/rss.xml":
            raw = f'<rss version="2.0"><channel><item><link>{url}</link></item></channel></rss>'.encode()
            return httpx.Response(200, stream=AuthoredStream(raw), headers={"content-type": "application/rss+xml"})
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, stream=AuthoredStream(sitemap([])), headers={"content-type": "application/xml"})
        return httpx.Response(403, headers={"cf-mitigated": "challenge"})

    monkeypatch.setattr(collection_transport.httpx, "AsyncClient",
                        lambda **options: original_client(transport=httpx.MockTransport(transport), **options))

    class UnsentAllowance:
        def fetch(self, _url):
            raise IngestionFailure("fallback_budget_live_set_work_exhausted")

    state = intake.State(config, "run")
    try:
        identifier = "private-news-" + digest([config.plan_id, url])
        fetcher = intake.PrivateFetcher(config, state)
        fetcher.resolver = lambda host, port: ["93.184.216.34"]
        fetcher._last["openai.com"] = 0
        fetcher.fallback_provider = UnsentAllowance()
        intake._discover(config, state, fetcher)
        result = intake.summary(config, state)
        assert result["continuationEligible"] and result["pendingCandidates"] == 1
        assert state.data["candidates"][identifier]["reusableNative"]["reason"] == "fallback_budget_live_set_work_exhausted"
        assert intake.public_client403_hosts(state) == ("openai.com",)
    finally:
        state.close()
    assert requests == ["/robots.txt", "/news/rss.xml", "/index/authored-fixture/"]
    before = namespace_fingerprint(config.state_dir)
    successor = intake.Config.model_validate(successor_values(values, "-next"))
    state = intake.State(successor, "run")
    try:
        fetcher = intake.PrivateFetcher(successor, state)

        fetcher.resolver = lambda host, port: ["93.184.216.34"]
        fetcher._last["openai.com"] = 0

        class RetainedProviderFixture:
            def fetch(self, requested):
                assert requested == url
                text = "# Authored fixture\n\nJuly 27, 2026\n\nSynthetic provider content.\n"
                receipt = ProviderReceipt("authored-provider-attempt", intake.now(), 200, "success",
                                          canonical({"title": "Authored fixture", "content": text}).encode(),
                                          actual_nano=FETCH_COST_NANO)
                return text, "Authored fixture", receipt

        fetcher.fallback_provider = RetainedProviderFixture()
        intake._discover(successor, state, fetcher)
        result = intake.summary(successor, state)
        assert result["currentRetainedInWindow"] == 1 and result["sourceRequests"] == 1
        assert result["providerOutcomeCounts"]["success"] == 1
        assert result["providerKnownCostNano"] == FETCH_COST_NANO
        assert intake.public_client403_hosts(state) == ("openai.com",)
    finally:
        state.close()
    assert namespace_fingerprint(config.state_dir) == before
    assert requests == ["/robots.txt", "/news/rss.xml", "/index/authored-fixture/", "/sitemap.xml"]


def test_funded_fetch_wrapper_forwards_current_robots_and_native_dispatch_timing(tmp_path):
    from zoop_ai_pipeline.extraction_fallback import ProviderReceipt
    config = public_offline_config(tmp_path)
    state = intake.State(config, "run")
    try:
        fetcher = SimpleNamespace(_delay={"openai.com": 10.0}, _last={"openai.com": 30.0}, run_deadline=100.0, state=state)
        wrapper = intake._FundedFetch(config, fetcher)
        observed = []

        class NoNetworkClient:
            def fetch(self, url, **options):
                observed.append((url, options))
                receipt = ProviderReceipt("authored-timing-" + str(len(observed)), intake.now(), 200, "success",
                                          b'{"title":"Authored","content":"authored-result"}')
                return "authored-result", "Authored", receipt

        wrapper.client = NoNetworkClient()
        assert wrapper.fetch("https://openai.com/index/authored/")[0] == "authored-result"
        assert observed[-1][1] == {"min_interval_seconds": 10.0, "not_before_monotonic": 40.0, "deadline_monotonic": 100.0}
        fetcher._delay["openai.com"], fetcher._last["openai.com"] = 20.0, 31.0
        wrapper.fetch("https://openai.com/index/authored-other/")
        assert observed[-1][1] == {"min_interval_seconds": 20.0, "not_before_monotonic": 51.0, "deadline_monotonic": 100.0}
        assert state.data["providerBytes"] == len(b'{"title":"Authored","content":"authored-result"}') * 2
    finally:
        state.close()


def test_combined_native_provider_body_budget_gates_before_reserve_and_native_get(tmp_path):
    from zoop_ai_pipeline.extraction_fallback import ProviderReceipt
    config = public_offline_config(tmp_path)
    state = intake.State(config, "run")
    calls = []

    class AuthoredBudget:
        def reserve(self, *args, **kwargs):
            calls.append("reserve")

        def check_send(self, identifier):
            calls.append(("send", identifier))

        def settle(self, *args, **kwargs):
            calls.append("settle")

        def release(self, *args, **kwargs):
            calls.append("release")

    try:
        state.data.update(bytes=850_000, providerBytes=100_000)
        budget = intake._FetchByteBudget(AuthoredBudget(), config, state)
        with pytest.raises(IngestionFailure, match="fallback_byte_budget"):
            budget.reserve("authored")
        assert calls == []
        state.data.update(bytes=900_000, providerBytes=0)
        budget.reserve("authored")
        budget.check_send("authored")
        assert state.data["pendingProviderRequest"]["attemptId"] == "authored"
        receipt = ProviderReceipt("authored", intake.now(), None, "unknown",
                                  received_bytes=20, response_byte_limit=100_000)
        intake._account_provider(state, receipt)
        assert state.data["providerBytes"] == 20 and state.data["providerUnknownByteUpperBound"] == 99_980
        assert state.data["providerUnknownRequests"] == 1 and state.data["pendingProviderRequest"] is None
        fetcher = intake.PrivateFetcher(config, state)
        fetcher.resolver = lambda host, port: (_ for _ in ()).throw(AssertionError("network was attempted"))
        with pytest.raises(IngestionFailure, match="byte_budget"):
            fetcher._get("https://openai.com/index/not-sent/", "openai.com", intake.time.monotonic() + 10, 100_000)
        assert fetcher.requests == 0 and fetcher.last_get_known_unsent
        result = intake.summary(config, state)
        assert result["providerBytes"] == 20 and result["providerUnknownByteUpperBound"] == 99_980
        assert not result["continuationEligible"] and result["artifactBytes"] > 0
    finally:
        state.close()


def test_unsettled_provider_intent_is_preserved_without_send_or_recovery_guess(tmp_path, monkeypatch):
    monkeypatch.setattr(intake.PrivateFetcher, "fetch",
                        lambda self, url: (_ for _ in ()).throw(AssertionError("network was attempted")))
    config = public_offline_config(tmp_path)
    state = intake.State(config, "run")
    try:
        state.data["pendingProviderRequest"] = {"attemptId": "authored-unknown", "byteUpperBound": 100_000, "startedAt": intake.now()}
        state.save()
    finally:
        state.close()
    result = intake.run(config, "resume")
    assert result["sourceRequests"] == 0 and result["providerUnknownRequests"] == 1
    assert result["providerUnknownByteUpperBound"] == 100_000
    assert result["stopCode"] == "provider_unknown_no_retry" and not result["continuationEligible"]


@pytest.mark.parametrize("case", ["allowed", "article", "unadvertised", "failed-discovery", "robots-denied",
                                 "generic429", "auth", "challenge", "orphan-child", "trusted-child"])
def test_client403_discovery_exception_is_route_scoped_and_never_unblocks_host(tmp_path, case):
    from dataclasses import asdict
    from zoop_ai_pipeline.extraction_fallback import NativePageObservation
    config = public_offline_config(tmp_path)
    state = intake.State(config, "run")
    try:
        raw = b"User-agent: *\n" + (b"Disallow: /news/rss.xml\n" if case == "robots-denied" else b"Allow: /\n")
        filename = "robots-" + intake.byte_hash(raw) + ".raw"
        intake._publish(state.fd, filename, raw, immutable=True)
        state.data["robotsFacts"] = {"https://openai.com": {"file": filename, "sha256": intake.byte_hash(raw),
            "status": 200, "code": None, "url": "https://openai.com/robots.txt", "observedAt": "2026-07-27T10:00:00+00:00"}}
        state.data["blocked"] = ["openai.com"]
        prior = NativePageObservation("https://openai.com/index/prior-fixture/", "2026-07-27T11:00:00+00:00",
            429 if case == "generic429" else 403, final_url="https://openai.com/index/prior-fixture/",
            failure_code="http_429" if case == "generic429" else "http_403",
            access="auth" if case == "auth" else "unknown" if case == "challenge" else "public",
            www_authenticate=case == "auth")
        intake._retain_client403(SimpleNamespace(state=state), prior)
        fetcher = intake.PrivateFetcher(config, state)
        url = "https://openai.com/news/rss.xml"
        fetcher.discovery_source = "openai-newsroom"
        if case == "article":
            fetcher.discovery_source = None
            fetcher.article_source = "openai-newsroom"
            url = "https://openai.com/index/other/"
        elif case == "unadvertised":
            url = "https://openai.com/sitemap.xml/unadvertised/"
        elif case in {"orphan-child", "trusted-child"}:
            selected = intake.archives.initial_tasks("openai-newsroom", config.from_day, config.through_day)[1]
            parent_key = digest(["openai-newsroom", selected.key])
            child_url = "https://openai.com/sitemap.xml/page/"
            xml = (f'<sitemapindex xmlns="{intake.archives.SITEMAP_NS}"><sitemap>'
                   f'<loc>{child_url}</loc></sitemap></sitemapindex>').encode()
            parsed = intake.archives.parse_listing("openai-newsroom", selected, xml, selected.url)
            evidence = {"rawSha256": intake.byte_hash(xml)}
            intake._publish(state.fd, "listing-" + parent_key + ".raw", xml, immutable=True)
            intake._publish(state.fd, "listing-" + parent_key + ".json", canonical(evidence).encode(), immutable=True)
            parent = state.data["tasks"][parent_key]
            parent.update(status="done", listingDigest=digest(evidence))
            child = parsed.next_tasks[0]
            row = {"source": "openai-newsroom", "task": asdict(child), "status": "pending", "saturated": False}
            if case == "trusted-child":
                row["discoveredFrom"] = parent_key
            state.data["tasks"][digest(["openai-newsroom", child.key])] = row
            url = child_url
        elif case == "failed-discovery":
            for task in state.data["tasks"].values():
                if task["task"]["url"] == url:
                    task.update(status="refused", code="http_403")
        fetcher.discovery_task_url = url
        if case in {"allowed", "trusted-child"}:
            assert fetcher._guard(url) == (url, "openai.com")
        else:
            with pytest.raises(IngestionFailure, match="host_blocked"):
                fetcher._guard(url)
        assert fetcher._blocked == {"openai.com"} and fetcher.requests == 0
    finally:
        state.close()


@pytest.mark.parametrize("headers,field", [
    ({"www-authenticate": "Basic realm=authored"}, "wwwAuthenticate"),
    ({"cf-mitigated": "challenge"}, "challenge"),
    ({"x-amzn-waf-action": "captcha"}, "challenge"),
])
def test_authentication_and_challenge_headers_are_observed_before_native403_refusal(tmp_path, headers, field):
    config = public_offline_config(tmp_path)
    state = intake.State(config, "run")
    try:
        fetcher = intake.PrivateFetcher(config, state)
        fetcher.article_source = "openai-newsroom"
        fetcher._request_url = "https://openai.com/index/authored/"
        with pytest.raises(IngestionFailure, match="http_403"):
            fetcher._check(httpx.Response(403, headers=headers), "openai.com", config.policy.max_response_bytes)
        assert fetcher.native_response[field] is True
        assert "openai.com" in fetcher._blocked and fetcher.requests == 0
        assert intake.public_client403_hosts(state) == ()
    finally:
        state.close()


def test_fresh_first_full_window_retains_older_and_current_actual_publications(kit):
    site, original = kit
    source = descriptor("full-window-fixture", "editorial", [
        surface("sitemap", "https://publisher.example/archive", coverage="finite-index")],
        ["publisher.example"], [r"/article/[a-z]+"], bodies=["//*[@id='articletxt']"])
    values = paged_config(original, source)
    values.update(fromDay="2026-07-28", throughDay="2026-10-28", selectionMode="fresh-first")
    site.route("/archive", sitemap([site.url("/article/older"), site.url("/article/current")]), content_type="application/xml")
    site.route("/article/older", article("2026-08-01"))
    site.route("/article/current", article("2026-10-28"))
    result = run(values)
    assert result["retainedInWindow"] == 2
    assert result["dayCounts"] == {"2026-08-01": 1, "2026-10-28": 1}
    assert "article_outside_window" not in result["candidateDispositions"]
    records = [json.loads(path.read_bytes()) for path in Path(values["stateDir"]).glob("private-news-*.json")]
    freshness = ["fresh" if record["publicationDay"] >= "2026-10-28" else "backfill" for record in records]
    assert sorted(freshness) == ["backfill", "fresh"]


@pytest.mark.parametrize("source_id,case,expected", [
    ("broadcom-newsroom", "canonical", "fallback_missing_key"),
    ("anthropic-newsroom", "canonical", "fallback_missing_key"),
    ("broadcom-newsroom", "string-actor", "fallback_configuration_invalid"),
    ("broadcom-newsroom", "extra-actor-field", "fallback_configuration_invalid"),
    ("broadcom-newsroom", "wrong-actor-kind", "fallback_configuration_invalid"),
    ("broadcom-newsroom", "invalid-actor-time", "fallback_configuration_invalid"),
    ("broadcom-newsroom", "proof-source", "fallback_admission_mismatch"),
    ("broadcom-newsroom", "proof-set", "fallback_admission_mismatch"),
    ("broadcom-newsroom", "proof-unit", "fallback_admission_mismatch"),
    ("broadcom-newsroom", "proof-allowance", "fallback_admission_mismatch"),
    ("broadcom-newsroom", "environment-set", "fallback_admission_mismatch"),
    ("broadcom-newsroom", "control-pin", "fallback_config_pin_mismatch"),
    ("broadcom-newsroom", "proof-pin", "fallback_config_pin_mismatch"),
    ("broadcom-newsroom", "unadmitted-set", "fallback_budget_live_set_not_admitted"),
])
def test_funded_fetch_lazy_actor_contract_uses_collector_proofs_without_credentials(
        tmp_path, monkeypatch, record_property, source_id, case, expected):
    from datetime import datetime, timedelta, timezone

    from scripts import overnight_collect as collector
    from zoop_ai_pipeline.live_budget import Budget
    from zoop_ai_pipeline.live_funding import run_policy

    # Only the environment boundary is replaced. Pins, normalization, collector
    # proof generation, canonical Actor validation and the SQLite ledger are real.
    current = datetime.now(timezone.utc)
    root = tmp_path.resolve() / "authored-experiment"
    collection = root / "collection"
    collection.mkdir(parents=True)
    actor = {"kind": "user-private-experiment", "acceptedBy": "Main",
             "decidedAt": (current - timedelta(minutes=1)).isoformat(),
             "statement": "Authored offline regression; no source or provider access is authorized."}
    if case == "string-actor":
        actor = "Authored legacy string, not the canonical actor contract"
    elif case == "extra-actor-field":
        actor = {**actor, "publicUse": True}
    elif case == "wrong-actor-kind":
        actor = {**actor, "kind": "public-publication"}
    elif case == "invalid-actor-time":
        actor = {**actor, "decidedAt": "not-a-timestamp"}
    control = {"schemaVersion": "zoop-private-run-4", "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"}, "runId": "authored-actor-gate",
               "root": str(root), "admitFrom": (current - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "admitUntil": (current + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "graphPort": 32810,
               "finishBy": (current + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "maxCalls": 100, "processingActor": actor}
    control_path = root / "run-config.json"
    collector.atomic(control_path, control, immutable=True)
    funding_pin = collector.ref(control_path)
    if case not in {"string-actor", "extra-actor-field", "wrong-actor-kind", "invalid-actor-time"}:
        assert collector.validate_run_config(funding_pin, collection, control["admitUntil"]) == control

    source = intake.archives.source_descriptor(source_id)
    values = public_offline_config(tmp_path.resolve()).wire()
    values.update(exactArticleHosts=list(source.article_hosts),
                  sources=[{"name": source_id, "sourceType": source.category,
                            "reliability": "authored lazy-initialization fixture", "queries": []}])
    plan = {"id": "authored-" + source_id, "sourceId": source_id, "configTemplate": values,
            "ceilings": {"requests": values["policy"]["maxRequests"]}}
    collector.attach_fallback(plan, collection, {"approvalRef": "authored-offline-only", "fundingConfig": funding_pin})
    proof = plan["funding"]
    budget = Budget(root / "modelbudget", 4_000_000_000, control["maxCalls"],
                    funding=run_policy(control), bucket_caps={"shared": 3_500_000_000, "personal": 500_000_000},
                    finish_by=control["finishBy"])
    budget.snapshot()  # Creates only this test's empty ledger; never a provider reservation.
    if case != "unadmitted-set":
        budget.admit_set(proof["setId"], proof["unitDigest"], proof["allowance"])
    if case.startswith("proof-") and case != "proof-pin":
        changed = collector.load(values["fallback"]["setProofPath"])
        field, replacement = {
            "proof-source": ("sourceId", "another-source"),
            "proof-set": ("setId", "acquisition:another-set"),
            "proof-unit": ("unitDigest", "0" * 64),
            "proof-allowance": ("allowance", {"fetch": 1, "search": 0}),
        }[case]
        changed[field] = replacement
        collector.atomic(values["fallback"]["setProofPath"], changed)
        values["fallback"]["setProofSha256"] = collector.sha(values["fallback"]["setProofPath"])
    elif case == "control-pin":
        values["fallback"]["budgetConfigSha256"] = "0" * 64
    elif case == "proof-pin":
        values["fallback"]["setProofSha256"] = "0" * 64
    config = intake.Config.model_validate(values)
    before = budget.snapshot()
    requested_environment = []

    class KeylessEnvironment:
        def get(self, name, default=None):
            requested_environment.append(name)
            if name == "ZOOP_AI_PIPELINE_LIVE_SET_ID":
                return "acquisition:wrong-environment" if case == "environment-set" else proof["setId"]
            if name == "DEEPSEEK_API_KEY":
                return None  # No lookup of the real environment and no credential value.
            raise AssertionError("unexpected environment lookup")

    class OSBoundary:
        environ = KeylessEnvironment()

        def __getattr__(self, name):
            return getattr(os, name)

    monkeypatch.setattr(intake, "os", OSBoundary())
    wrapper = intake._FundedFetch(config, SimpleNamespace())
    assert wrapper.client is None
    with pytest.raises(IngestionFailure) as failure:
        wrapper.fetch("https://" + source.article_hosts[0] + "/authored-no-dispatch")
    record_property("lazy_failure_code", failure.value.code)
    assert failure.value.code == expected
    assert wrapper.client is None
    assert ("DEEPSEEK_API_KEY" in requested_environment) == (case == "canonical")
    assert budget.snapshot() == before
    assert before["calls"] == 0 and before["states"] == {}


@pytest.mark.parametrize("contact", [None, "https://example.com/collector"])
def test_metadata_repair_discovery_limit_omission_preserves_policy_wire(tmp_path, contact):
    policy = config_data(tmp_path, "http://127.0.0.1:18765")["policy"]
    policy["contactUrl"] = contact
    assert intake.PrivatePolicy.model_validate(policy).wire() == intake.Policy.model_validate(policy).wire()
    assert intake.PrivatePolicy.model_validate({**policy, "maxDiscoveryResponseBytes": None}).wire() == intake.Policy.model_validate(policy).wire()
    explicit = intake.PrivatePolicy.model_validate({**policy, "maxDiscoveryResponseBytes": 500_000})
    assert explicit.wire()["maxDiscoveryResponseBytes"] == 500_000
    for invalid in (0, 1_000_001, 10_000_001):
        with pytest.raises(ValidationError):
            intake.PrivatePolicy.model_validate({**policy, "maxDiscoveryResponseBytes": invalid})


@pytest.mark.parametrize("case", ["discovery", "default", "article", "robots", "total"])
def test_metadata_repair_discovery_stream_keeps_article_robots_and_total_bounds(tmp_path, monkeypatch, case):
    origin = "http://127.0.0.1:18765"
    values = paged_config(config_data(tmp_path, origin))
    values["sources"] = [{"name": "fnnews-sitemaps", "sourceType": "editorial",
                          "reliability": "authored offline fixture", "queries": []}]
    values["policy"].update(maxResponseBytes=2_000_000, maxTotalBytes=40_000_000)
    if case != "default":
        values["policy"]["maxDiscoveryResponseBytes"] = 10_000_000
    if case == "total":
        values["policy"]["maxTotalBytes"] = 10_000_000
    index_path = "/resource/view_xml/sitemap_index/news-sitemap-index-2026.xml"
    child_path = "/resource/view_xml/sitemap_v3/sitemap-202607-1.xml"
    article_path = "/news/202607251234560001"
    index = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>' +
             origin + child_path + '</loc></sitemap></sitemapindex>').encode()
    child = sitemap([origin + article_path]).replace(b'</urlset>', b'<!--' + b' ' * 2_000_000 + b'--></urlset>')
    body = article("2026-07-25").replace(b'<article>', b'<article class="article-view">').replace(
        b'<div id="articletxt">', b'<div class="article-view__body">')
    if case == "article":
        body += b' ' * 2_000_000
    robots = b"User-agent: *\nAllow: /\n"
    if case == "robots":
        robots += b'#' + b' ' * 600_000
    routes = {"/robots.txt": (robots, "text/plain"), index_path: (index, "application/xml"),
              child_path: (child, "application/xml"), article_path: (body, "text/html")}
    observed, consumed = [], []

    class Stream(httpx.AsyncByteStream):
        def __init__(self, raw):
            self.raw = raw

        async def __aiter__(self):
            for start in range(0, len(self.raw), 65_536):
                chunk = self.raw[start:start + 65_536]
                consumed.append(len(chunk))
                yield chunk

    def response(request):
        assert request.url.host == "127.0.0.1"
        observed.append(request.url.path)
        raw, media_type = routes[request.url.path]
        return httpx.Response(200, headers={"content-type": media_type}, stream=Stream(raw))

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(response), **kwargs))
    monkeypatch.setattr(collection_transport, "_resolve", lambda resolver, host, port, remaining: ["127.0.0.1"])
    result = run(values)
    assert result["sourceBytes"] == sum(consumed)
    assert result["sourceRequests"] == len(observed)
    assert result["unknownByteUpperBound"] == 0
    if case == "discovery":
        assert result["retainedInWindow"] == 1
        assert observed == ["/robots.txt", index_path, child_path, article_path]
        assert result["sourceBytes"] == sum(len(raw) for raw, _ in routes.values())
        before = {path.name: path.read_bytes() for path in Path(values["stateDir"]).iterdir()}
        assert run(values, "status")["retainedInWindow"] == 1
        assert {path.name: path.read_bytes() for path in Path(values["stateDir"]).iterdir()} == before
        assert len(observed) == 4
    elif case == "default":
        assert result["retainedInWindow"] == 0
        assert result["partitionDispositions"]["response_too_large"] == 1
        assert observed == ["/robots.txt", index_path, child_path]
    elif case == "article":
        assert result["retainedInWindow"] == 0
        assert result["candidateDispositions"]["response_too_large"] == 1
        assert observed == ["/robots.txt", index_path, child_path, article_path]
    elif case == "robots":
        assert result["retainedInWindow"] == 0
        assert observed == ["/robots.txt"]
        assert collection_transport.ROBOTS_BYTES < result["sourceBytes"] <= collection_transport.ROBOTS_BYTES + 65_536
    else:
        assert result["stopCode"] == "byte_budget" and result["retainedInWindow"] == 0
        assert observed == ["/robots.txt"] and result["sourceBytes"] == len(robots)


def test_metadata_repair_actual_cli_fnnews_large_sitemap_and_immutable_status(tmp_path):
    import subprocess
    import sys

    site = LocalSite()
    try:
        values = paged_config(config_data(tmp_path, site.url("")))
        values["sources"] = [{"name": "fnnews-sitemaps", "sourceType": "editorial",
                              "reliability": "authored loopback fixture", "queries": []}]
        values["policy"].update(maxDiscoveryResponseBytes=10_000_000, maxResponseBytes=2_000_000,
                                maxTotalBytes=160_000_000)
        index_path = "/resource/view_xml/sitemap_index/news-sitemap-index-2026.xml"
        child_path = "/resource/view_xml/sitemap_v3/sitemap-202607-1.xml"
        article_path = "/news/202607251234560001"
        index = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>' +
                 site.url(child_path) + '</loc></sitemap></sitemapindex>').encode()
        listing = sitemap([site.url(article_path)]).replace(
            b'</urlset>', b'<!--' + b' ' * 2_000_000 + b'--></urlset>')
        body = article("2026-07-25").replace(b'<article>', b'<article class="article-view">').replace(
            b'<div id="articletxt">', b'<div class="article-view__body">')
        site.route("/robots.txt", b"User-agent: *\nAllow: /\n", content_type="text/plain")
        site.route(index_path, index, content_type="application/xml", length=False)
        site.route(child_path, listing, content_type="application/xml", length=False)
        site.route(article_path, body)
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(values))
        source = Path(intake.__file__).resolve().parents[1]
        env = {"PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1", "PATH": os.defpath}

        def cli(command):
            result = subprocess.run([sys.executable, "-B", "-m", "zoop_ai_pipeline.private_intake_cli",
                                     command, "--config", str(config_path)], env=env,
                                    capture_output=True, text=True, timeout=120)
            assert result.returncode == 0, (result.stdout, result.stderr)
            return json.loads(result.stdout)

        result = cli("run")
        assert result["retainedInWindow"] == 1 and result["sourceRequests"] == 4
        assert result["sourceBytes"] == sum(len(route["body"]) for route in site.routes.values())
        state = Path(values["stateDir"])
        records = list(state.glob("private-news-*.json"))
        assert len(records) == 1
        record = json.loads(records[0].read_bytes())
        assert records[0].with_suffix(".raw").read_bytes() == body
        assert record["publication"]["raw"] == "2026-07-25T12:34:56+09:00"
        assert record["rights"] == "unconfirmed" and record["modelSend"] is False and record["publicUse"] is False
        before = {p.name: p.read_bytes() for p in state.iterdir() if p.name != ".lock"}
        assert cli("status")["retainedInWindow"] == 1
        assert before == {p.name: p.read_bytes() for p in state.iterdir() if p.name != ".lock"}
        assert len(site.log) == 4 and site.hits(article_path) == 1
    finally:
        site.close()
