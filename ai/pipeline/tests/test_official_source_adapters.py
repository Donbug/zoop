"""Authored real HTTP, ZIP and XML fixtures; no external credentials or endpoints."""
import io
import json
import logging
import zipfile
from dataclasses import asdict, replace
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.collection_smoke import LocalSite
from zoop_ai_pipeline import official_source_adapters as official
from zoop_ai_pipeline.collection import Fetched
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, byte_hash

FIRST, LAST = "2026-07-28", "2026-10-28"
KEY = "a" * 40  # synthetic only, used exclusively against explicit numeric loopback


def zipped(values):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in values:
            archive.writestr(name, raw)
    return stream.getvalue()


@pytest.fixture
def site():
    server = LocalSite()
    server.route("/robots.txt", b"User-agent: *\nAllow: /\n", content_type="text/plain")
    yield server
    server.close()


def policy(**changes):
    return official.OfficialPolicy.model_validate({"schemaVersion": "zoop-collection-policy-1", "userAgent": "ZoopSynthetic/1.0",
        "timeoutSeconds": 5, "maxTotalSeconds": 60, "maxRedirects": 0, "maxRequests": 40,
        "maxResponseBytes": 2_000_000, "maxTotalBytes": 8_000_000, "minIntervalSeconds": 0,
        "allowedMediaTypes": official.MEDIA, "syntheticLoopback": True, **changes})


def fetcher(site, source, **changes):
    return official.OfficialFetcher(policy(**changes), source, synthetic_origin=site.url(""),
        **({"sec_company": "Synthetic Fixture", "sec_contact": "test@example.invalid"} if source == "sec-edgar" else {}))


def task(site, source, **options):
    return official.plan(source, FIRST, LAST, synthetic_origin=site.url(""), **options).tasks[0]


def test_keyless_plan_prerequisites_windows_and_actual_scope():
    matrix = {row["sourceId"]: row for row in official.source_matrix(FIRST, LAST)}
    assert matrix["opendart"]["state"] == "credential-blocked"
    assert matrix["sec-edgar"]["state"] == "operator-prerequisite"
    assert matrix["federal-register-bis"]["state"] == "supported"
    dart = official.plan("opendart", FIRST, LAST)
    assert [(t.from_day, t.through_day) for t in dart.tasks] == [(FIRST, "2026-10-27"), (LAST, LAST)]
    assert "crtfc_key" not in repr(dart)
    assert all(parse_qs(urlsplit(t.url).query)["last_reprt_at"] == ["N"] for t in dart.tasks)
    with pytest.raises(IngestionFailure, match="366"):
        official.plan("opendart", "2025-01-01", "2026-01-02")
    assert official.plan("sec-edgar", FIRST, LAST).tasks == ()
    with pytest.raises(IngestionFailure, match="contact_required"):
        official.OfficialFetcher(policy(), "sec-edgar", synthetic_origin="http://127.0.0.1:12345")


def test_missing_key_sends_nothing_and_task_source_binding(site):
    client = fetcher(site, "opendart")
    selected = task(site, "opendart", tickers=("005930",))
    with pytest.raises(IngestionFailure, match="credentials_required"):
        official.execute(selected, client)
    assert site.log == []
    with pytest.raises(IngestionFailure, match="source_binding"):
        official.execute(replace(selected, source_id="sec-edgar"), client, runtime_key=KEY)
    with pytest.raises(IngestionFailure, match="source_binding"):
        official.execute(replace(selected, url="https://attacker.invalid/api/corpCode.xml"), client, runtime_key=KEY)
    assert site.log == []


def test_dart_actual_corp_lookup_pages_corrections_zip_mapping_and_redaction(site, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    corp_raw = zipped([("CORPCODE.xml", b"<result><list><corp_code>00126380</corp_code><corp_name>Fixture</corp_name><stock_code>005930</stock_code><modify_date>20261001</modify_date></list></result>")])
    site.route("/api/corpCode.xml", corp_raw, content_type="application/zip")
    client = fetcher(site, "opendart")
    corps = official.execute(task(site, "opendart", tickers=("005930", "000000")), client, runtime_key=KEY)
    assert corps.candidates[0].facts["corpCode"] == "00126380"
    assert corps.candidates[0].facts["stockCode"] == "005930"
    assert corps.candidates[0].facts["memberSha256"] == byte_hash(corps.members[0].raw)
    assert corps.limitations == ("ticker_not_in_actual_records:000000",)
    assert corps.raw == corp_raw
    selected = corps.next_tasks[0]
    rows = [{"corp_code": "00126380", "stock_code": "005930", "rcept_no": "20261028000001", "rcept_dt": "20261028", "report_nm": "Report"},
            {"corp_code": "00126380", "stock_code": "005930", "rcept_no": "20261028000002", "rcept_dt": "20261028", "report_nm": "[기재정정] Report"}]
    site.route("/api/list.json", json.dumps({"status": "000", "page_no": 1, "total_page": 2, "list": rows[:1]}).encode(), content_type="application/json")
    first = official.execute(selected, client, runtime_key=KEY)
    assert first.candidates[0].publication == {"raw": "20261028", "value": LAST, "day": LAST, "precision": "day", "field": "rcept_dt"}
    assert len(first.next_tasks) == 1
    site.route("/api/list.json", json.dumps({"status": "000", "page_no": 2, "total_page": 2, "list": rows[1:]}).encode(), content_type="application/json")
    second = official.execute(first.next_tasks[0], client, runtime_key=KEY)
    assert second.candidates[0].candidate_id != first.candidates[0].candidate_id
    assert second.candidates[0].facts["correction"] is True and not second.next_tasks
    raw = zipped([("main.xml", "<DOCUMENT><TITLE>공시😀</TITLE><P>Exact &amp; original.</P></DOCUMENT>".encode()),
                  ("exchange.xml", b"<html><head><script>NO</script></head><body><p>Exchange text.</p></body></html>"),
                  ("figure.png", b"unsupported retained bytes")])
    site.route("/api/document.xml", raw, content_type="application/octet-stream")
    body_task = second.candidates[0].body_task
    body = official.execute(body_task, client, runtime_key=KEY)
    assert body.raw == raw and len(body.members) == 3
    assert "공시😀" in body.prepared["text"] and "Exact & original." in body.prepared["text"]
    assert "Exchange text." in body.prepared["text"] and "NO" not in body.prepared["text"]
    for segment in body.prepared["segments"]:
        source = body.prepared["sources"][segment["sourceIndex"]]
        assert body.prepared["text"][segment["cleanStart"]:segment["cleanEnd"]] == source["text"][segment["sourceStart"]:segment["sourceEnd"]]
        assert source["containerSha256"] == byte_hash(raw) and source["memberRef"] in {"main.xml", "exchange.xml"}
    envelope = body.extraction()
    assert official.verify_extraction(envelope, raw, body_task, synthetic_origin=site.url("")) == body.prepared
    assert envelope["publicUse"] is False and envelope["modelSend"] is False
    assert KEY not in repr(body) + json.dumps(envelope) + caplog.text
    assert all(KEY in item["path"] for item in site.log if item["path"] != "/robots.txt")
    assert all("crtfc_key" not in repr(value) for value in [corps, first, second, body_task])
    envelope["members"][0]["sha256"] = "0" * 64
    with pytest.raises(IngestionFailure, match="extraction_invalid"):
        official.verify_extraction(envelope, raw, body_task, synthetic_origin=site.url(""))


@pytest.mark.parametrize("raw,code", [
    (zipped([("../escape.xml", b"<x>bad</x>")]), "zip_member_unsafe"),
    (zipped([("main.xml", b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>')]), "xml_entities_forbidden"),
    (b'<result><status>020</status><message>quota</message></result>', "auth_or_quota_020"),
    (b'<result><status>010</status><message>key denied</message></result>', "auth_or_quota_010"),
])
def test_dart_zip_and_api_refusals(site, raw, code):
    selected = official.OfficialTask("opendart", "dart-document", site.url("/api/document.xml?rcept_no=20261028000001"),
                                    FIRST, LAST, {"candidateId": "20261028000001"})
    site.route("/api/document.xml", raw, content_type="application/zip")
    with pytest.raises(IngestionFailure, match=code):
        official.execute(selected, fetcher(site, "opendart"), runtime_key=KEY)


def test_zip_expansion_bound(site, monkeypatch):
    monkeypatch.setattr(official, "MAX_EXPANDED", 10)
    site.route("/api/corpCode.xml", zipped([("CORPCODE.xml", b"<result>too large</result>")]), content_type="application/zip")
    with pytest.raises(IngestionFailure, match="zip_size_limit"):
        official.execute(task(site, "opendart", tickers=("005930",)), fetcher(site, "opendart"), runtime_key=KEY)


@pytest.mark.parametrize("mode", ["echo", "redirect", "status"])
def test_secret_never_returned_on_errors_or_redirects(site, mode, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    selected = task(site, "opendart", tickers=("005930",))
    if mode == "echo":
        site.route("/api/corpCode.xml", KEY.encode(), content_type="application/xml")
    elif mode == "redirect":
        site.route("/api/corpCode.xml", b"", status=302, headers={"Location": "https://attacker.invalid/?key=" + KEY})
    else:
        site.route("/api/corpCode.xml", b"denied", status=403)
    with pytest.raises(IngestionFailure) as failure:
        official.execute(selected, fetcher(site, "opendart"), runtime_key=KEY)
    assert KEY not in str(failure.value) + repr(failure.value) + caplog.text
    assert failure.value.__cause__ is None
    assert not any("attacker" in item["path"] for item in site.log)


def test_fsc_feed_bound_links_and_original_html(site):
    link = site.url("/no010101/123")
    feed = f'<rss><channel><item><title>Official release</title><link>{link}</link><pubDate>Wed, 28 Oct 2026 09:00:00 +0900</pubDate></item></channel></rss>'.encode()
    site.route("/about/fsc_bbs_rss/", feed, content_type="application/xml")
    site.route("/no010101/123", b'<html><body><div class="board-view-wrap"><div class="cont"><p>Actual official body.</p></div></div></body></html>')
    client = fetcher(site, "fsc-press")
    listing = official.execute(task(site, "fsc-press"), client)
    assert listing.candidates[0].publication["precision"] == "instant"
    assert listing.candidates[0].response_sha256 == byte_hash(feed)
    body = official.execute(listing.candidates[0].body_task, client)
    assert "Actual official body." in body.prepared["text"]
    site.route("/about/fsc_bbs_rss/", feed.replace(link.encode(), b"https://foreign.invalid/no010101/123"), content_type="application/xml")
    with pytest.raises(IngestionFailure, match="source_binding"):
        official.execute(task(site, "fsc-press"), client)


def test_bis_paginated_search_detail_original_text_and_agency_binding(site):
    number = "2026-12345"
    row = {"document_number": number, "title": "BIS rule", "publication_date": LAST,
           "agencies": [{"slug": "industry-and-security-bureau"}],
           "html_url": site.url("/documents/2026/10/28/2026-12345/bis-rule"),
           "raw_text_url": site.url("/documents/full_text/text/2026/10/28/2026-12345.txt")}
    site.route("/api/v1/documents.json", json.dumps({"results": [row], "total_pages": 2}).encode(), content_type="application/json")
    site.route("/api/v1/documents/2026-12345.json", json.dumps(row).encode(), content_type="application/json")
    site.route("/documents/full_text/text/2026/10/28/2026-12345.txt", b"Exact Federal Register text.\nSecond paragraph.", content_type="text/plain")
    client = fetcher(site, "federal-register-bis")
    page = official.execute(task(site, "federal-register-bis"), client)
    assert len(page.next_tasks) == 1 and "page=2" in page.next_tasks[0].url
    detail = official.execute(page.candidates[0].body_task, client)
    body = official.execute(detail.next_tasks[0], client)
    assert body.prepared["text"] == "Exact Federal Register text.\nSecond paragraph."
    assert detail.candidates[0].publication["precision"] == "day"
    row["agencies"] = [{"slug": "other-agency"}]
    site.route("/api/v1/documents.json", json.dumps({"results": [row], "total_pages": 1}).encode(), content_type="application/json")
    with pytest.raises(IngestionFailure, match="agency_binding"):
        official.execute(task(site, "federal-register-bis"), client)


def sec_columns(accession="0000123456-26-000001"):
    return {"accessionNumber": [accession], "filingDate": [LAST], "form": ["10-K"], "primaryDocument": ["report.htm"],
            "acceptanceDateTime": ["2026-10-28T16:34:51.000Z"], "isInlineXBRL": [1]}


def test_sec_recent_and_past_files_actual_accessions_dates_and_ua(site):
    recent = {"cik": "123456", "name": "Fixture Registrant", "tickers": ["SYN"], "filings": {"recent": sec_columns(), "files": [
        {"name": "CIK0000123456-submissions-001.json", "filingFrom": FIRST, "filingTo": LAST},
        {"name": "CIK0000123456-submissions-002.json", "filingFrom": "2020-01-01", "filingTo": "2021-01-01"}]}}
    site.route("/submissions/CIK0000123456.json", json.dumps(recent).encode(), content_type="application/json")
    site.route("/submissions/CIK0000123456-submissions-001.json", json.dumps(sec_columns("0000654321-26-000002")).encode(), content_type="application/json")
    client = fetcher(site, "sec-edgar")
    first = official.execute(task(site, "sec-edgar", ciks=("123456",)), client)
    assert len(first.next_tasks) == 1
    assert first.candidates[0].publication["raw"] == LAST
    assert first.candidates[0].facts["acceptanceDateTime"] == "2026-10-28T16:34:51.000Z"
    assert first.candidates[0].facts["publisher"] is None
    past = official.execute(first.next_tasks[0], client)
    candidate = past.candidates[0]
    assert candidate.candidate_id == "0000654321-26-000002"
    assert "/123456/000065432126000002/report.htm" in candidate.url
    site.route(urlsplit(candidate.url).path, b'<html><head><title>Not article</title></head><body><p>Exact filing <ix:nonNumeric>text</ix:nonNumeric>.</p></body></html>')
    body = official.execute(candidate.body_task, client)
    assert "Exact filing text." in body.prepared["text"]
    assert all(item["headers"]["user-agent"] == "Synthetic Fixture test@example.invalid" for item in site.log)
    assert client.policy.min_interval_seconds >= 0.1
    recent["cik"] = "999999"
    site.route("/submissions/CIK0000123456.json", json.dumps(recent).encode(), content_type="application/json")
    with pytest.raises(IngestionFailure, match="cik_binding"):
        official.execute(task(site, "sec-edgar", ciks=("123456",)), client)


def test_resource_budget_returns_tasks_without_recursing(site):
    selected = task(site, "opendart", tickers=("005930",))
    site.route("/api/corpCode.xml", zipped([("corp.xml", b"<result><list><stock_code>005930</stock_code><corp_code>00126380</corp_code></list></result>")]), content_type="application/zip")
    client = fetcher(site, "opendart", maxRequests=2)
    result = official.execute(selected, client, runtime_key=KEY)
    assert len(result.next_tasks) == 1 and len(site.log) == 2
    with pytest.raises(IngestionFailure, match="request_budget"):
        official.execute(result.next_tasks[0], client, runtime_key=KEY)
    assert len(site.log) == 2 and result.next_tasks[0].context["page"] == 1


def config(site, tmp_path, source="fsc-press", **overrides):
    from zoop_ai_pipeline.official_source_intake import OfficialConfig
    return OfficialConfig.model_validate({"schemaVersion": "zoop-official-source-config-1", "planId": "official-fixture",
        "stateDir": str(tmp_path / "state"), "sourceId": source, "fromDay": FIRST, "throughDay": LAST,
        "operatorApprovalRef": "authored-loopback-only", "policy": policy().model_dump(mode="json", by_alias=True),
        "syntheticBaseUrl": site.url(""), **overrides})


def fsc_routes(site):
    link = site.url("/no010101/123")
    site.route("/about/fsc_bbs_rss/", f'<rss><channel><item><title>Fixture release</title><link>{link}</link><pubDate>Wed, 28 Oct 2026 09:00:00 +0900</pubDate></item></channel></rss>'.encode(), content_type="application/xml")
    site.route("/no010101/123", b'<html><body><div class="board-view-wrap"><div class="cont"><p>Exact original disclosure text.</p></div></div></body></html>')


def test_durable_retention_derivation_proof_and_read_only_status(site, tmp_path):
    from pathlib import Path
    fsc_routes(site)
    selected = config(site, tmp_path)
    result = official.run(selected)
    assert result["retainedInWindow"] == 1 and result["state"] == "completed", result
    refs = list(official.retained_items(selected))
    assert len(refs) == 1 and set(refs[0]) == {"sourceId", "stateDir", "recordPath", "recordSha256", "privateId", "planId"}
    reference = refs[0]
    root = Path(reference["stateDir"])
    record = json.loads(Path(reference["recordPath"]).read_bytes())
    raw = (root / (reference["privateId"] + ".raw")).read_bytes()
    body = (root / record["bodyArtifact"]["file"]).read_bytes()
    extraction = (root / record["extractionArtifact"]["file"]).read_bytes()
    assert body == b"Exact original disclosure text."
    assert record["rawSha256"] != record["bodyArtifact"]["sha256"]
    assert record["publication"]["raw"] == "Wed, 28 Oct 2026 09:00:00 +0900"
    assert record["publication"]["value"] == "2026-10-28T09:00:00+09:00"
    assert official.verify_record(record, raw, extraction_raw=extraction, body_raw=body) == record
    before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.iterdir()}
    assert official.status(selected)["sourceRequests"] == len(site.log) == 3
    assert list(official.retained_items(selected)) == refs
    assert before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.iterdir()}
    assert official.run(selected, "resume")["sourceRequests"] == 3
    assert len(site.log) == 3
    record["publication"]["day"] = "2026-10-27"
    with pytest.raises(IngestionFailure):
        official.verify_record(record, raw, extraction_raw=extraction, body_raw=body)


def test_runner_credential_prerequisite_no_network_or_secret_artifacts(site, tmp_path):
    selected = config(site, tmp_path, "opendart", tickers=["005930"])
    result = official.run(selected)
    assert result["state"] == "prerequisite" and result["sourceRequests"] == 0
    assert result["pendingCandidates"] == 1 and site.log == []
    assert "OPENDART_API_KEY" in result["prerequisites"][0]


def test_pinned_successor_only_fetches_pending_body(site, tmp_path):
    from pathlib import Path
    fsc_routes(site)
    first = config(site, tmp_path, policy=policy(maxRequests=2).model_dump(mode="json", by_alias=True))
    result = official.run(first)
    assert result["continuationEligible"] and result["stopCode"] == "request_budget"
    root = Path(first.state_dir)
    previous = {"stateDir": str(root), "planSha256": byte_hash((root / "PLAN.json").read_bytes()),
                "stateSha256": byte_hash((root / "STATE.json").read_bytes())}
    second = config(site, tmp_path, planId="official-successor", stateDir=str(tmp_path / "successor"), predecessor=previous)
    result = official.run(second)
    assert result["retainedInWindow"] == 1 and not result["continuationEligible"], result
    assert site.hits("/about/fsc_bbs_rss/") == 1 and site.hits("/no010101/123") == 1
    assert len(list(official.retained_items(second))) == 1


def test_sent_timeout_is_unknown_not_continuable_or_retried(site, tmp_path):
    fsc_routes(site)
    site.routes["/about/fsc_bbs_rss/"]["delay"] = 1.2
    selected = config(site, tmp_path, policy=policy(timeoutSeconds=1).model_dump(mode="json", by_alias=True))
    result = official.run(selected)
    assert result["unknownRequests"] == 1 and result["stopCode"] == "timeout", result
    assert result["continuationEligible"] is False
    count = len(site.log)
    assert official.run(selected, "resume")["unknownRequests"] == 1
    assert len(site.log) == count


def test_persisted_denial_never_retries_pending_tasks(site, tmp_path):
    site.route("/api/list.json", b"rate limited", status=429, content_type="application/json")
    selected = config(site, tmp_path, "opendart")
    result = official.run(selected, runtime_key=KEY)
    assert result["stopCode"] == "http_429" and result["continuationEligible"] is False
    count = len(site.log)
    assert official.run(selected, "resume", runtime_key=KEY)["stopCode"] == "http_429"
    assert len(site.log) == count
