"""Private intake lifecycle and access boundaries, with authored loopback bodies only."""
import errno
import json
import os
import stat
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from scripts.collection_smoke import LocalSite
from scripts.private_intake_smoke import PRIVATE, article, config_data, sitemap
from zoop_ai_pipeline import private_intake as intake
from zoop_ai_pipeline import collection as collection_transport
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, canonical, digest


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
