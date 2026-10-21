"""One-off HTTP collection against an actual local HTTP server, then the unchanged offline ingestion CLI.

Nothing here reaches a real site: URLs are loopback, DNS answers that must never be trusted are simulated by the resolver
the fetcher is constructed with, and the policy's explicit `syntheticLoopback` switch is the only way loopback is reachable."""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.collection_smoke import NEWS, PROXY_ENV, ROBOTS, CollectionKit, LocalSite
from scripts.ingestion_smoke import OfflineFixture, authored_pdf, exact_check, sha
from zoop_ai_pipeline.collection import Fetcher, parse_robots
from zoop_ai_pipeline.collection_contracts import Policy, Request
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, canonical
from zoop_ai_pipeline.ingestion_url import canonical_url

UA = "ZoopSyntheticCollector/1.0 (+synthetic-local-test)"


@pytest.fixture
def site():
    server = LocalSite()
    yield server
    server.close()


@pytest.fixture
def kit(tmp_path):
    return CollectionKit(tmp_path / "owned")


def codes(result):
    return {t["candidateId"]: t["code"] for t in result["targets"]}


def fetcher(kit, hosts, resolver, **policy):
    return Fetcher(Policy.model_validate({**kit.policy, **policy}), hosts, resolver)


# ------------------------------------------------------------------------------------------------ URL identity

@pytest.mark.parametrize("given,expected", [
    ("https://EXAMPLE.invalid:443/a?b=2&a=1#one", "https://example.invalid/a?b=2&a=1"),
    ("http://example.invalid:80", "http://example.invalid/"),
    ("https://example.invalid", "https://example.invalid/"),
    ("https://example.invalid./x", "https://example.invalid/x"),
    ("https://BÜCHER.example/x", "https://xn--bcher-kva.example/x"),
    ("http://127.0.0.1:8123/x", "http://127.0.0.1:8123/x"),
])
def test_url_identity_vectors(given, expected):
    assert canonical_url(given)[0] == expected


@pytest.mark.parametrize("given", [
    "https://user:secret@example.invalid/x", "https://user@example.invalid/x", "ftp://example.invalid/x", "https://example.invalid:8443/x",
    "http://example.invalid:8080/x", "https://example.invalid/%2e%2e/x", "https://example.invalid/a%2Fb", "https://example.invalid/a\\b",
    "https://example.invalid/a b", "https://example.invalid/%zz", "https:///x", "https://exa mple.invalid/", "javascript:alert(1)",
])
def test_ambiguous_credentialed_or_foreign_urls_are_not_identities(given):
    with pytest.raises(IngestionFailure, match="source_url_invalid"):
        canonical_url(given)


# ------------------------------------------------------------------------------------------------ robots.txt

def test_robots_longest_match_product_token_wildcards_and_delay():
    rules = parse_robots(b"User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /*.pdf$\nCrawl-delay: 2.5\nSitemap: https://example.invalid/s.xml\n", UA)
    assert rules.permits("https://h.invalid/a/b/c") and not rules.permits("https://h.invalid/a/x") and rules.permits("https://h.invalid/z")
    assert not rules.permits("https://h.invalid/x.pdf") and rules.permits("https://h.invalid/x.pdf?download=1") and rules.delay == 2.5
    specific = parse_robots(b"User-agent: zoopsyntheticcollector\nDisallow: /\n\nUser-agent: *\nAllow: /\n", UA)
    assert not specific.permits("https://h.invalid/anything")
    assert parse_robots(b"User-agent: otherbot\nDisallow: /\n", UA).permits("https://h.invalid/anything")


@pytest.mark.parametrize("body", [b"this is not robots", b"Disallow: /orphan-rule", b"User-agent: *\nDisallow: private\n", b"User-agent: *\nCrawl-delay: soon\n", b"\xff\xfe"])
def test_uninterpretable_robots_denies_instead_of_allowing(body):
    with pytest.raises(IngestionFailure, match="robots_malformed"):
        parse_robots(body, UA)


@pytest.mark.parametrize("status,body,expected", [(500, b"down", "robots_unavailable"), (200, b"nonsense", "robots_malformed"), (403, b"no", "http_403")])
def test_unavailable_or_malformed_robots_blocks_the_whole_origin(kit, site, status, body, expected):
    site.route("/robots.txt", body, status=status, content_type="text/plain")
    site.route("/news/a", NEWS)
    result = kit.collect("robots-variant", [kit.target(site.url("/news/a"), "n1")], expected=2)
    assert result["state"] == "failed" and codes(result) == {"n1": expected}
    assert site.hits("/news/a") == 0


def test_missing_robots_allows_and_allow_beats_disallow_by_longest_match(kit, site):
    site.route("/robots.txt", ROBOTS, content_type="text/plain")
    site.route("/private/open", NEWS)
    site.route("/private/x", NEWS)
    result = kit.collect("robots-longest", [kit.target(site.url("/private/open"), "open"), kit.target(site.url("/private/x"), "closed")], expected=2)
    assert result["state"] == "partial" and codes(result) == {"open": None, "closed": "robots_denied"} and site.hits("/private/x") == 0
    site.routes.pop("/robots.txt")
    none = kit.collect("robots-absent", [kit.target(site.url("/private/x"), "closed")])
    assert none["state"] == "complete"


# ------------------------------------------------------------------------------------- address policy / DNS

def test_loopback_http_is_refused_unless_the_policy_names_synthetic_loopback(kit, site):
    site.route("/news/a", NEWS)
    kit.policy["syntheticLoopback"] = False
    kit.save_policy()
    result = kit.collect("default-deny", [kit.target(site.url("/news/a"), "n1")], expected=2)
    assert result["state"] == "failed" and codes(result) == {"n1": "private_address"} and site.log == []


def test_dns_answer_change_between_requests_is_revalidated_and_never_connected(kit, site):
    answers = iter([["127.0.0.1"], ["10.0.0.7"]])
    site.route("/p", NEWS)
    with pytest.raises(IngestionFailure, match="private_address"):
        fetcher(kit, ["localhost"], lambda host, port: next(answers)).fetch(f"http://localhost:{site.port}/p")
    # robots (first lookup) reached the server with the requested Host over the validated address; the page (second, private lookup) never did.
    assert [e["path"] for e in site.log] == ["/robots.txt"]
    assert site.log[0]["headers"]["host"] == f"localhost:{site.port}"


def test_a_mixed_dns_answer_is_refused_as_a_whole(kit, site):
    with pytest.raises(IngestionFailure, match="private_address"):
        fetcher(kit, ["localhost"], lambda host, port: ["127.0.0.1", "10.0.0.7"]).fetch(f"http://localhost:{site.port}/p")
    assert site.log == []


def test_a_public_looking_name_resolving_to_loopback_is_never_allowed_even_in_synthetic_mode(kit, site):
    with pytest.raises(IngestionFailure, match="private_address"):
        fetcher(kit, ["docs.example.test"], lambda host, port: ["127.0.0.1"]).fetch("https://docs.example.test/x")
    assert site.log == []


@pytest.mark.parametrize("answer", ["::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "169.254.169.254", "0.0.0.0", "100.64.0.1", "fe80::1", "::1", "fd00::1", "192.168.1.5", "not-an-address"])
def test_every_nonglobal_answer_family_is_refused(kit, answer):
    with pytest.raises(IngestionFailure, match="private_address"):
        fetcher(kit, ["docs.example.test"], lambda host, port: [answer]).fetch("https://docs.example.test/x")


def test_redirect_to_a_host_that_resolves_privately_is_refused_before_connecting(kit, site):
    answers = {"localhost": ["127.0.0.1"], "alt.test": ["192.168.1.5"]}
    site.route("/go", status=302, headers={"Location": "https://alt.test/x"})
    with pytest.raises(IngestionFailure, match="private_address"):
        fetcher(kit, ["localhost", "alt.test"], lambda host, port: answers[host]).fetch(f"http://localhost:{site.port}/go")
    assert [e["path"] for e in site.log] == ["/robots.txt", "/go"]


def test_literal_private_hosts_are_refused_before_any_lookup(kit):
    looked = []

    def resolver(host, port):
        looked.append(host)
        return ["10.0.0.5"]

    for url, host in (("https://10.0.0.5/x", "10.0.0.5"), ("https://[::1]/x", "::1"), ("https://169.254.169.254/latest", "169.254.169.254")):
        with pytest.raises(IngestionFailure, match="private_address"):
            fetcher(kit, [host], resolver).fetch(url)
    assert looked == []


def test_dns_failure_and_a_hanging_resolver_are_closed_failures(kit):
    def broken(host, port):
        raise OSError("synthetic")

    with pytest.raises(IngestionFailure, match="dns_failed"):
        fetcher(kit, ["docs.example.test"], broken).fetch("https://docs.example.test/x")
    with pytest.raises(IngestionFailure, match="timeout"):
        fetcher(kit, ["docs.example.test"], lambda host, port: time.sleep(3) or ["93.184.216.34"], timeoutSeconds=1).fetch("https://docs.example.test/x")


def test_proxy_environment_variables_are_ignored(kit, site):
    site.route("/news/a", NEWS)
    result = kit.collect("proxy-env", [kit.target(site.url("/news/a"), "n1")], env=PROXY_ENV)
    assert result["state"] == "complete" and site.hits("/news/a") == 1


# ------------------------------------------------------------------------------------------- limits / types

def test_credential_headers_are_never_sent_and_redirects_stay_on_listed_hosts(kit, site):
    site.route("/go", status=302, headers={"Location": "/news/a"})
    site.route("/news/a", NEWS)
    result = kit.collect("redirect-ok", [kit.target(site.url("/go"), "n1")])
    assert result["state"] == "complete"
    with_agent = [e for e in site.log if e["path"] != "/robots.txt"]
    assert [e["path"] for e in with_agent] == ["/go", "/news/a"]
    assert all(e["headers"]["user-agent"] == kit.policy["userAgent"] for e in site.log)
    assert not any(name in e["headers"] for e in site.log for name in ("cookie", "authorization", "proxy-authorization", "referer"))
    receipt = _receipts(kit, "redirect-ok")[0]
    assert receipt["requestedUrl"] == site.url("/go") and receipt["finalUrl"] == site.url("/news/a") and receipt["redirects"] == [site.url("/news/a")]


def test_auth_statuses_block_the_host_for_the_rest_of_the_run_without_retry(kit, site):
    site.route("/denied", b"no", status=403, content_type="text/plain")
    site.route("/open", NEWS)
    result = kit.collect("blocked-host", [kit.target(site.url("/denied"), "a"), kit.target(site.url("/open"), "b")], expected=2)
    assert result["state"] == "failed" and codes(result) == {"a": "http_403", "b": "host_blocked"}
    assert site.hits("/denied") == 1 and site.hits("/open") == 0


def test_run_byte_and_request_budgets_stop_later_targets(kit, site):
    site.route("/one", b"<article>" + b"a" * 1000 + b"</article>")
    site.route("/two", b"<article>" + b"b" * 1000 + b"</article>")
    kit.policy.update(maxResponseBytes=1200, maxTotalBytes=1500)
    kit.save_policy()
    byte_limited = kit.collect("byte-budget", [kit.target(site.url("/one"), "a"), kit.target(site.url("/two"), "b")], expected=2)
    assert byte_limited["state"] == "partial" and codes(byte_limited) == {"a": None, "b": "byte_budget"}
    kit.policy.update(maxResponseBytes=200_000, maxTotalBytes=3_000_000, maxRequests=2)
    kit.save_policy()
    request_limited = kit.collect("request-budget", [kit.target(site.url("/one"), "a"), kit.target(site.url("/two"), "b")], expected=2)
    assert request_limited["state"] == "partial" and codes(request_limited) == {"a": None, "b": "request_budget"} and site.hits("/two") == 1


def test_slow_response_hits_the_deadline_and_other_targets_still_run(kit, site):
    site.route("/slow", NEWS, delay=3)
    site.route("/fast", NEWS)
    kit.policy.update(timeoutSeconds=1)
    kit.save_policy()
    result = kit.collect("deadline", [kit.target(site.url("/slow"), "slow"), kit.target(site.url("/fast"), "fast")], expected=2)
    assert result["state"] == "partial" and codes(result) == {"slow": "timeout", "fast": None}


@pytest.mark.parametrize("path,kwargs,code", [
    ("/img", {"body": b"\x89PNG", "content_type": "image/png"}, "media_type_not_allowed"),
    ("/gz", {"body": b"x", "headers": {"Content-Encoding": "gzip"}}, "content_encoding"),
    ("/huge", {"body": b"a" * 250_000, "length": False}, "response_too_large"),
    ("/big", {"body": b"a" * 300_000}, "response_too_large"),
    ("/gone", {"body": b"x", "status": 410}, "http_410"),
    ("/loop", {"status": 302, "headers": {"Location": "/loop"}}, "redirect_limit"),
    ("/nowhere", {"status": 302}, "redirect_limit"),
    ("/userinfo", {"status": 302, "headers": {"Location": "https://user:pw@example.invalid/x"}}, "redirect_invalid"),
])
def test_a_bad_response_is_one_stable_code_with_no_url_or_header_text(kit, site, path, kwargs, code):
    site.route(path, **kwargs)
    result = kit.collect("bad-response", [kit.target(site.url(path), "t")], expected=2)
    assert result["state"] == "failed" and codes(result) == {"t": code}
    assert "pw" not in str(result) and "secret" not in str(result)


# --------------------------------------------------------------------------- request, grant and namespace

@pytest.mark.parametrize("target_url", ["https://user:pw@127.0.0.1/x", "https://other.invalid/x", "ftp://127.0.0.1/x", "not a url"])
def test_a_target_outside_the_listed_hosts_or_with_userinfo_fails_the_whole_request_before_any_request(kit, site, target_url):
    result = kit.collect("bad-target", [kit.target(site.url("/news/a"), "ok"), kit.target(target_url, "bad")], expected=2)
    assert result["error"]["code"] == "target_invalid" and site.log == []
    assert not (kit.inputs / "collections" / "bad-target").exists()


def test_duplicate_targets_are_refused_even_when_spelled_differently(kit, site):
    result = kit.collect("dupes", [kit.target(site.url("/a"), "a"), kit.target(site.url("/a#frag"), "b")], expected=2)
    assert result["error"]["code"] == "target_invalid" and site.log == []


def test_request_validation_rejects_ambiguous_declared_metadata(kit, site):
    for bad in ("2026-10-14 09:00", "2026-13-40", "Oct 14 2026", "20261014", "2026-10-14T09:00"[:11]):
        target = kit.target(site.url("/news/a"), "n1", published=bad)
        assert kit.collect("bad-date", [target], expected=2)["error"]["code"] == "input_or_configuration_invalid"
    assert kit.collect("bad-modified", [kit.target(site.url("/news/a"), "n1", modified="2026-10-14")], expected=2)["error"]["code"] == "input_or_configuration_invalid"
    assert site.log == []


def test_only_a_known_enabled_collected_http_source_is_ever_fetched(kit, site):
    site.route("/news/a", NEWS)
    target = [kit.target(site.url("/news/a"), "n1")]
    grant = kit.registry["sources"][0]["grant"]
    for change, code in (({"rights": "unknown"}, "source_unauthorized"), ({"enabled": False}, "source_unauthorized"), ({"allowedOperations": ["read"]}, "source_unauthorized"),
                         ({"expiresAt": "2000-01-01T00:00:00+00:00"}, "source_unauthorized"), ({"evidence": []}, "source_unauthorized")):
        original = {key: grant[key] for key in change}
        grant.update(change)
        kit.save_registry()
        assert kit.collect("unauthorized", target, expected=2)["error"]["code"] == code
        grant.update(original)
        kit.save_registry()
    kit.registry["sources"][0]["adapter"] = "authored-files"
    kit.save_registry()
    assert kit.collect("authored-source", target, expected=2)["error"]["code"] == "source_adapter_mismatch"
    assert site.log == [] and not (kit.inputs / "collections").exists()


def test_immutable_collection_id_replays_without_refetch_and_refuses_changed_input(kit, site):
    site.route("/news/a", NEWS)
    site.route("/private/x", NEWS)
    site.route("/robots.txt", ROBOTS, content_type="text/plain")
    mixed = [kit.target(site.url("/news/a"), "n1"), kit.target(site.url("/private/x"), "p1")]
    first = kit.collect("fixed-id", mixed, expected=2)
    assert first["state"] == "partial"
    seen = len(site.log)
    again = kit.collect("fixed-id", mixed, expected=2)
    assert again["replayed"] is True and again["state"] == "partial" and again["targets"] == first["targets"] and len(site.log) == seen
    changed = kit.collect("fixed-id", [kit.target(site.url("/news/a"), "n1", title="another declared title"), mixed[1]], expected=2)
    assert changed["error"]["code"] == "collection_input_conflict" and len(site.log) == seen
    kit.policy["userAgent"] = "AnotherAgent/1.0"
    kit.save_policy()
    assert kit.collect("fixed-id", mixed, expected=2)["error"]["code"] == "collection_input_conflict"


def test_symlinked_roots_foreign_files_and_foreign_directories_are_never_adopted(kit, site, tmp_path):
    site.route("/news/a", NEWS)
    target = [kit.target(site.url("/news/a"), "n1")]
    source = kit.registry["sources"][0]
    real = Path(source["inputRoot"])
    link = kit.root / "linked-inputs"
    link.symlink_to(real, target_is_directory=True)
    source["inputRoot"] = str(link)
    kit.save_registry()
    assert kit.collect("linked-root", target, expected=2)["error"]["code"] == "collection_namespace_invalid"
    source["inputRoot"] = str(real)
    kit.save_registry()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (real / "collections").symlink_to(elsewhere, target_is_directory=True)
    assert kit.collect("linked-collections", target, expected=2)["error"]["code"] == "collection_namespace_invalid"
    assert list(elsewhere.iterdir()) == []
    (real / "collections").unlink()
    (real / "collections").mkdir()
    foreign = real / "collections" / "app.sqlite3"
    foreign.write_bytes(b"foreign sqlite sentinel")
    assert kit.collect("foreign-file", target, expected=2)["error"]["code"] == "collection_namespace_conflict"
    assert foreign.read_bytes() == b"foreign sqlite sentinel"
    foreign.unlink()
    squatter = real / "collections" / "squatted-id"
    squatter.mkdir()
    (squatter / "keep.txt").write_bytes(b"not ours")
    assert kit.collect("squatted-id", target, expected=2)["error"]["code"] == "collection_namespace_conflict"
    assert (squatter / "keep.txt").read_bytes() == b"not ours" and site.log == []
    stale = real / "collections" / ".tmp-old-1-deadbeef"
    stale.mkdir()
    assert kit.collect("with-stale-tmp", target)["state"] == "complete" and stale.is_dir()


def test_an_input_root_inside_a_reserved_state_root_is_refused_without_touching_it(kit, site):
    reserved = Path.home() / "InvestMateLogicTest" / "inputs"
    kit.registry["sources"][0]["inputRoot"] = str(reserved)
    kit.save_registry()
    assert kit.collect("reserved", [kit.target(site.url("/news/a"), "n1")], expected=2)["error"]["code"] == "state_namespace_conflict"
    assert site.log == []


# -------------------------------------------------------------------------- ingestion of collected records

def _receipts(kit, collection_id):
    folder = kit.inputs / "collections" / collection_id / "receipts"
    return [json.loads(p.read_bytes()) for p in sorted(folder.iterdir())]


def _collect_and_run(kit, site, collection_id="c1", **target):
    site.route("/news/a", NEWS)
    collected = kit.collect(collection_id, [kit.target(site.url("/news/a"), "n1", **target)])
    manifest = Path(collected["manifestPath"])
    return collected, manifest


def test_collected_documents_are_exported_with_truthful_provenance_and_declared_time(kit, site):
    site.route("/news/a", b'<html><head><title>scraped title</title><meta property="article:published_time" content="2020-01-01T00:00:00Z"></head>'
                          b'<body><article><p>' + "본문 첫째 😀".encode() + b'</p></article></body></html>')
    site.route("/news/b", NEWS)
    site.route("/news/c", NEWS)
    targets = [kit.target(site.url("/news/a"), "day", title="declared title", published="2026-10-14", kind="news"),
               kit.target(site.url("/news/b"), "naive", published="2026-10-14T09:30:00", kind="disclosure"),
               kit.target(site.url("/news/c"), "zulu", published="2026-10-14T00:00:00Z", modified="2026-10-15T01:02:03+09:00")]
    collected = kit.collect("times", targets)
    manifest = Path(collected["manifestPath"])
    ran = kit.cli("run", kit.request(manifest, "r1"), manifest=manifest)
    assert ran["state"] == "complete" and ran["provenance"] == "collected_http" and ran["counts"]["textReady"] == 3
    exports = {ref["ordinal"]: kit.cli("export", kit.export_selector("r1", ref)) for ref in ran["documentRefs"]}
    day, naive, zulu = (exports[i] for i in range(3))
    assert day["observation"]["title"] == "declared title" and day["observation"]["publishedAt"] is None
    assert day["observation"]["collection"]["published"]["precision"] == "day" and day["observation"]["collection"]["published"]["date"] == "2026-10-14"
    assert day["document"]["text"] == "본문 첫째 😀" and "scraped title" not in str(day) and "article:published_time" not in str(day)
    assert naive["observation"]["publishedAt"] is None and naive["observation"]["collection"]["published"]["precision"] == "unresolved"
    assert naive["observation"]["collection"]["documentKind"] == "disclosure"
    assert zulu["observation"]["publishedAt"] == "2026-10-14T00:00:00Z" and zulu["observation"]["collection"]["published"]["precision"] == "instant"
    assert zulu["observation"]["modifiedAt"] == "2026-10-15T01:02:03+09:00"
    authored_keys = {"roundId", "sourceId", "page", "ordinal", "pageId", "observedAt", "documentId", "rawVersion", "documentVersion",
                     "url", "title", "publishedAt", "modifiedAt", "sourceRevision", "mediaType"}
    for export in exports.values():
        # The Java importer pins these exact key sets (IngestionExportParser): change both sides together.
        assert set(export["observation"]) == authored_keys | {"provenance", "collection"}
        assert set(export["observation"]["collection"]) == {"provenance", "collectionId", "receipt", "fetchedAt", "finalUrl", "httpStatus", "contentType",
                                                            "bodySha256", "documentKind", "network", "published"}
        assert set(export["observation"]["collection"]["receipt"]) == {"file", "sha256"}
        assert set(export["observation"]["collection"]["published"]) == {"raw", "precision", "date", "basis"}
        assert export["observation"]["collection"]["network"] == "synthetic_loopback"
        assert export["observation"]["collection"]["bodySha256"] == export["locatorMetadata"]["rawHash"]
        fetched = datetime.fromisoformat(export["observation"]["collection"]["fetchedAt"])
        assert fetched.tzinfo is not None and export["observation"]["provenance"] == "collected_http"
    assert zulu["grant"] == {"grantId": "operator-grant", "revision": "rights-1"}


def test_the_same_page_collected_twice_is_the_same_raw_and_text_version(kit, site):
    site.route("/news/a", NEWS)
    refs = []
    for index, round_id in enumerate(("r1", "r2")):
        collected = kit.collect(f"again-{round_id}", [kit.target(site.url("/news/a"), "n1")])
        manifest = Path(collected["manifestPath"])
        ran = kit.cli("run", kit.request(manifest, round_id, index), manifest=manifest)
        refs.append(ran["documentRefs"][0])
    assert refs[0]["rawVersion"] == refs[1]["rawVersion"] and refs[0]["documentVersion"] == refs[1]["documentVersion"]


def test_authored_fixtures_cannot_be_relabelled_actual_and_collected_sources_reject_authored_items(kit, site):
    collected, manifest = _collect_and_run(kit, site)
    kit.registry["sources"][0]["adapter"] = "authored-files"
    kit.save_registry()
    relabelled = kit.cli("run", kit.request(manifest, "authored"), manifest=manifest)
    assert relabelled["state"] == "incomplete" and relabelled["counts"]["textReady"] == 0 and relabelled["documentRefs"][0]["error"] == "discovery_item_invalid"
    kit.registry["sources"][0]["adapter"] = "collected-http"
    kit.save_registry()
    unrecorded = kit.manifest("hand-authored", [[kit.item(url=site.url("/news/a"))]])
    held = kit.cli("run", kit.request(unrecorded, "unrecorded"), state="other", manifest=unrecorded)
    assert held["state"] == "incomplete" and held["counts"]["textReady"] == 0 and held["documentRefs"][0]["error"] == "discovery_item_invalid"


@pytest.mark.parametrize("tamper", ["body", "receipt", "grant-revision"])
def test_a_tampered_or_stale_acquisition_record_stops_ingestion_with_nothing_recorded(kit, site, tamper):
    collected, manifest = _collect_and_run(kit, site)
    folder = kit.inputs / "collections" / "c1"
    if tamper == "body":
        next((folder / "bodies").iterdir()).write_bytes(b"<article>changed after collection</article>")
    elif tamper == "receipt":
        path = next((folder / "receipts").iterdir())
        path.write_bytes(path.read_bytes().replace(b"synthetic-source", b"another-source"))
    else:
        kit.registry["sources"][0]["grant"]["revision"] = "rights-2"
        kit.save_registry()
    result = kit.cli("run", kit.request(manifest, "tampered"), manifest=manifest)
    assert result["state"] == "incomplete" and result["counts"]["textReady"] == 0 and result["counts"]["newRawVersions"] == 0
    assert result["documentRefs"][0]["failure"]["code"] == ("collection_receipt_invalid" if tamper == "grant-revision" else "fixture_hash_mismatch")


def test_collected_text_survives_removal_of_the_collection_files_after_ingestion(kit, site):
    collected, manifest = _collect_and_run(kit, site)
    ran = kit.cli("run", kit.request(manifest, "r1"), manifest=manifest)
    ref = ran["documentRefs"][0]
    shutil.rmtree(kit.inputs / "collections" / "c1")
    assert kit.cli("resume", kit.selector("r1"))["documentRefs"][0]["documentVersion"] == ref["documentVersion"]
    exported = kit.cli("export", kit.export_selector("r1", ref))
    assert exported["document"]["text"].startswith("합성 공시 & 본문😀 끝")
    exact_check(exported["document"], 0, exported["document"]["rawLocators"][0]["end"])


def test_pdf_and_html_collected_over_http_become_exact_citable_versions(kit, site):
    body = authored_pdf("filing page one", "filing page two")
    site.route("/f.pdf", body, content_type="application/pdf")
    site.route("/news/a", NEWS)
    collected = kit.collect("mixed", [kit.target(site.url("/f.pdf"), "pdf", kind="disclosure", supplier="filing-9"), kit.target(site.url("/news/a"), "html")])
    manifest = Path(collected["manifestPath"])
    ran = kit.cli("run", kit.request(manifest, "r1"), manifest=manifest)
    pdf_ref = next(r for r in ran["documentRefs"] if r["ordinal"] == 0)
    exported = kit.cli("export", kit.export_selector("r1", pdf_ref))
    assert exported["document"]["text"] == "filing page one\nfiling page two" and exported["locatorMetadata"]["pageCount"] == 2
    assert exported["observation"]["collection"]["bodySha256"] == exported["locatorMetadata"]["rawHash"] == sha(body)
    exact_check(exported["document"], 0, 15)


def test_an_authored_export_keeps_exactly_the_closed_key_set_the_application_importer_accepts(tmp_path):
    authored = OfflineFixture(tmp_path / "authored")
    manifest = authored.manifest("a", [[authored.item()]])
    ran = authored.cli("run", authored.request(manifest), manifest=manifest)
    assert ran["provenance"] == "authored_control"
    ref = ran["documentRefs"][0]
    exported = authored.cli("export", {"schemaVersion": "zoop-ingestion-s2-1", "roundId": "round-1", "sourceId": "synthetic-source",
                                       **{k: ref[k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}})
    assert set(exported["observation"]) == {"roundId", "sourceId", "page", "ordinal", "pageId", "observedAt", "documentId", "rawVersion", "documentVersion",
                                            "url", "title", "publishedAt", "modifiedAt", "sourceRevision", "mediaType"}
    assert set(exported) == {"schemaVersion", "observation", "grant", "document", "locatorMetadata"}


# ------------------------------------------------------------------------------------ declared publisher

def _old_request(targets=None):
    return {"schemaVersion": "zoop-collection-1", "collectionId": "c1", "sourceId": "synthetic-source", "scopeId": "body",
            "targets": targets or [{"candidateId": "n1", "url": "http://127.0.0.1:1/a", "title": "t", "documentKind": "news", "publishedAt": "2026-10-14",
                                    "modifiedAt": None, "supplierDocumentId": None, "sourceRevision": None}]}


def test_a_request_without_publisher_serializes_and_hashes_exactly_as_before():
    # Literal taken from the commit before `publisher` existed (a one-time run of that code), not from this implementation.
    expected = ('{"collectionId":"c1","schemaVersion":"zoop-collection-1","scopeId":"body","sourceId":"synthetic-source","targets":[{"candidateId":"n1",'
                '"documentKind":"news","modifiedAt":null,"publishedAt":"2026-10-14","sourceRevision":null,"supplierDocumentId":null,"title":"t","url":"http://127.0.0.1:1/a"}]}')
    wire = canonical(Request.model_validate(_old_request()).wire())
    assert wire == expected and sha(wire.encode()) == "198b724928ecbdacab977624bf8854a5c57ce31c0c5326c1163de429a2e384f4"
    # The nested target is dumped by the parent request, so the key must be dropped there too, not only by Target.wire().
    nulled = _old_request()
    nulled["targets"][0]["publisher"] = None
    assert canonical(Request.model_validate(nulled).wire()) == expected
    assert "publisher" not in Request.model_validate(nulled).targets[0].wire()


def test_a_declared_publisher_is_in_the_request_wire_and_changes_its_digest():
    declared = _old_request()
    declared["targets"][0]["publisher"] = "합성일보"
    request = Request.model_validate(declared)
    assert request.wire()["targets"][0]["publisher"] == "합성일보" == request.targets[0].wire()["publisher"]
    assert sha(canonical(request.wire()).encode()) != "198b724928ecbdacab977624bf8854a5c57ce31c0c5326c1163de429a2e384f4"
    assert set(request.wire()["targets"][0]) == set(_old_request()["targets"][0]) | {"publisher"}


@pytest.mark.parametrize("value", ["", " ", "\u3000", "\t", "a\nb", "a\x00b", "\x7f", "x" * 201, 5, True, ["a"]])
def test_an_invalid_target_publisher_is_refused_before_any_request(kit, site, value):
    invalid = _old_request()
    invalid["targets"][0]["publisher"] = value
    with pytest.raises(ValidationError):
        Request.model_validate(invalid)
    site.route("/news/a", NEWS)
    result = kit.collect("bad-publisher", [kit.target(site.url("/news/a"), "n1", publisher=value)], expected=2)
    assert result["error"]["code"] == "input_or_configuration_invalid" and site.log == []


def test_a_lone_surrogate_target_publisher_is_refused():
    invalid = _old_request()
    invalid["targets"][0]["publisher"] = "a\ud800b"
    with pytest.raises(ValidationError):
        Request.model_validate(invalid)


def test_authored_and_collected_publisher_reach_the_export_and_are_never_scraped(kit, site):
    site.route("/news/a", b'<html><head><meta property="og:site_name" content="Scraped Outlet"><meta name="author" content="Scraped Author"></head>'
                          b'<body><article><p>' + "본문".encode() + b'</p></article></body></html>')
    site.route("/news/b", NEWS)
    targets = [kit.target(site.url("/news/a"), "undeclared", supplier="s-1"), kit.target(site.url("/news/b"), "declared", supplier="s-2", publisher="  합성일보  ")]
    collected = kit.collect("pub-1", targets)
    manifest = Path(collected["manifestPath"])
    page = json.loads((kit.inputs / "collections" / "pub-1" / "page-0.json").read_bytes())
    assert "publisher" not in page["items"][0] and page["items"][1]["publisher"] == "  합성일보  "
    ran = kit.cli("run", kit.request(manifest, "r1", 0), manifest=manifest)
    undeclared, declared = (kit.cli("export", kit.export_selector("r1", ref), extra=["--require-store"]) for ref in ran["documentRefs"])
    assert "publisher" not in undeclared["observation"] and "Scraped" not in str(undeclared)
    assert declared["observation"]["publisher"] == "  합성일보  " and declared["observation"]["collection"]["network"] == "synthetic_loopback"
    # The same fetched page re-collected under a different declared outlet is a new raw/document version of the same document.
    again = kit.collect("pub-2", [kit.target(site.url("/news/b"), "declared", supplier="s-2", publisher="Another Outlet")])
    second_manifest = Path(again["manifestPath"])
    second = kit.cli("run", kit.request(second_manifest, "r2", 1), manifest=second_manifest)["documentRefs"][0]
    first = ran["documentRefs"][1]
    assert second["documentId"] == first["documentId"] and second["rawVersion"] != first["rawVersion"] and second["documentVersion"] != first["documentVersion"]
    assert kit.cli("export", kit.export_selector("r2", second))["observation"]["publisher"] == "Another Outlet"
    assert kit.cli("export", kit.export_selector("r1", ran["documentRefs"][1]))["observation"]["publisher"] == "  합성일보  "


def test_collection_replay_treats_null_as_omitted_and_a_changed_publisher_as_a_conflict(kit, site):
    site.route("/news/a", NEWS)
    declared = [kit.target(site.url("/news/a"), "n1", publisher="합성일보")]
    first = kit.collect("fixed-publisher", declared)
    seen = len(site.log)
    assert kit.collect("fixed-publisher", declared)["replayed"] is True and len(site.log) == seen
    assert kit.collect("fixed-publisher", [kit.target(site.url("/news/a"), "n1", publisher="다른일보")], expected=2)["error"]["code"] == "collection_input_conflict"
    assert kit.collect("fixed-publisher", [kit.target(site.url("/news/a"), "n1")], expected=2)["error"]["code"] == "collection_input_conflict"
    plain = [kit.target(site.url("/news/a"), "n1")]
    kit.collect("fixed-plain", plain)
    seen = len(site.log)
    explicit = kit.collect("fixed-plain", [{**plain[0], "publisher": None}])
    assert explicit["replayed"] is True and len(site.log) == seen and first["state"] == "complete"
