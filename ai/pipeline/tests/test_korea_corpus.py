"""Deterministic synthetic loopback behavior; no external source or model calls."""
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from scripts.collection_smoke import LocalSite
from scripts.korea_corpus_smoke import SUBSTANCE, article, config, listing, smoke
from zoop_ai_pipeline import korea_corpus as corpus
from zoop_ai_pipeline.collection import Fetcher, Fetched, collect
from zoop_ai_pipeline.collection_contracts import Request
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, byte_hash, canonical
from zoop_ai_pipeline.korea_portal import ROUTES, parse_listing, validate_article


@pytest.fixture
def kit(tmp_path):
    site = LocalSite()
    site.route("/robots.txt", b"User-agent: *\nAllow: /\n", content_type="text/plain")
    value, path = config(tmp_path, site)
    site.route(ROUTES["policy-news"][0], listing(["100000001"]))
    site.route(ROUTES["policy-news"][1], article(site, "100000001"))
    yield site, value, path
    site.close()


def run(value):
    return corpus.run(corpus.Config.model_validate(value))


def saved(value):
    return json.loads((Path(value["stateDir"]) / "STATE.json").read_bytes())


def test_actual_cli_positive_negative_dedup_resume_and_readonly_status(tmp_path):
    assert smoke(tmp_path)["status"] == "passed"


@pytest.mark.parametrize("variation,code", [
    ({"license_type": 4}, "portal_item_not_kogl1_text"),
    ({"notice": False}, "portal_item_not_kogl1_text"),
    ({"body": "첨부 파일을 확인하세요."}, "portal_no_substantive_inline_body_or_contact_only"),
    ({"body": '<iframe src="/never-fetch"></iframe>'}, "portal_no_substantive_inline_body_or_contact_only"),
    ({"canonical_id": "100000009"}, "portal_canonical_mismatch"),
    ({"title": "바뀐 제목"}, "portal_article_metadata_changed"),
    ({"publisher": "합성 기관", "publisher_link": False}, "portal_article_metadata_changed"),
], ids=["type4", "no-notice", "attachment-only", "iframe-only", "wrong-canonical", "changed-title", "publisher-spacing"])
def test_per_item_refusals_never_publish_native_body(kit, variation, code):
    site, value, _ = kit
    site.route(ROUTES["policy-news"][1], article(site, "100000001", **variation))
    result = run(value)
    assert result["counts"]["refused"] == 1
    assert result["dispositions"][0]["reason"] == code
    native = Path(value["stateDir"]) / "native" / "collections" / "item-100000001"
    assert not (native / "bodies").exists() and not (native / "receipts").exists()
    assert json.loads((native / "collection.json").read_bytes())["state"] == "failed"
    assert site.hits("/never-fetch") == 0
    before = len(site.log)
    run(value)
    assert len(site.log) == before


def test_footer_wide_badge_not_an_item_license(kit):
    site, value, _ = kit
    raw = article(site, "100000001")
    # Move the rights block outside the actual inline article body.
    raw = raw.replace(b'<div class="law_copy_wrap">', b'</div></div><footer><div class="law_copy_wrap">')
    site.route(ROUTES["policy-news"][1], raw)
    result = run(value)
    assert result["dispositions"][0]["reason"] == "portal_item_license_missing"


def test_volatile_page_shell_is_accepted_by_single_native_get(kit):
    site, value, _ = kit
    hits = 0

    def volatile():
        nonlocal hits
        hits += 1
        site.routes[ROUTES["policy-news"][1]]["body"] = article(site, "100000001", shell=f'<meta name="nonce" content="{hits}">')

    site.routes[ROUTES["policy-news"][1]]["hook"] = volatile
    result = run(value)
    assert result["counts"]["exported"] == 1 and hits == 1
    assert site.hits(ROUTES["policy-news"][1]) == 1
    native = Path(value["stateDir"]) / "native" / "collections" / "item-100000001"
    assert (native / "bodies" / (result["documents"][0]["nativeBodySha256"] + ".bin")).exists()


@pytest.mark.parametrize("publisher", ["합성기관", "관계부처 합동"])
def test_plaintext_publisher_matches_listing_without_internal_space_loss(kit, publisher):
    site, value, _ = kit
    site.route(ROUTES["policy-news"][0], listing(["100000001"], publisher=publisher))
    site.route(ROUTES["policy-news"][1], article(site, "100000001", publisher=publisher, publisher_link=False))
    result = run(value)
    assert result["counts"]["exported"] == 1
    assert result["documents"][0]["candidate"]["publisher"] == publisher


def test_second_badge_in_type_refused(kit):
    site, value, _ = kit
    raw = article(site, "100000001")
    raw = raw.replace(b'</div><div class="info"><p>', b'<a href="https://www.kogl.or.kr/info/license.do"><img src="/images/common/open_type_04.png" alt="other"></a></div><div class="info"><p>')
    site.route(ROUTES["policy-news"][1], raw)
    result = run(value)
    assert result["dispositions"][0]["reason"] == "portal_item_not_kogl1_text"
    assert not (Path(value["stateDir"]) / "native" / "collections" / "item-100000001" / "bodies").exists()

def test_configuration_conflict_precedes_all_mutation(kit):
    site, value, _ = kit
    run(value)
    root = Path(value["stateDir"])
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    value["throughDay"] = "2026-10-24"
    requests = len(site.log)
    with pytest.raises(IngestionFailure, match="corpus_configuration_conflict"):
        run(value)
    assert requests == len(site.log)
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("cap,expected_export", [(2, 0), (3, 1)])
def test_requests_are_cumulative_across_listing_native_and_restart(kit, cap, expected_export):
    site, value, _ = kit
    value["policy"]["maxRequests"] = cap
    result = run(value)
    assert result["counts"]["exported"] == expected_export
    assert len(site.log) == cap and result["usage"]["requests"] == cap
    run(value)
    assert len(site.log) == cap


def test_byte_cap_covers_listing_and_robots(kit):
    site, value, _ = kit
    value["policy"].update(maxResponseBytes=100, maxTotalBytes=100)
    result = run(value)
    assert result["state"] == "partial"
    assert result["channels"]["policy-news"]["reason"] in {"byte_budget", "response_too_large"}
    assert result["usage"]["requests"] == 2
    assert site.hits(ROUTES["policy-news"][1]) == 0


def test_shared_transport_pacing_and_blocked_host_survive_batches(kit):
    site, value, _ = kit
    value["policy"]["minIntervalSeconds"] = 0.025
    instants = []
    for path in ("/robots.txt", ROUTES["policy-news"][0], ROUTES["policy-news"][1]):
        site.routes[path]["hook"] = lambda: instants.append(time.monotonic())
    result = run(value)
    assert result["counts"]["exported"] == 1
    assert len(instants) == 3 and all(b - a >= 0.018 for a, b in zip(instants, instants[1:]))


def test_403_block_persists_without_a_second_article_fetch(kit):
    site, value, _ = kit
    site.route(ROUTES["policy-news"][0], listing(["100000001", "100000002"]))
    site.route(ROUTES["policy-news"][1], b"denied", status=403)
    result = run(value)
    assert result["counts"]["failed"] == 2 and site.hits(ROUTES["policy-news"][1]) == 1
    assert saved(value)["blocked"] == ["127.0.0.1"]
    assert {r["reason"] for r in result["dispositions"]} == {"http_403", "host_blocked"}


def test_partial_crash_after_native_publication_recovers_without_network(kit, monkeypatch):
    site, value, _ = kit
    original = corpus.collect

    def collected_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt("synthetic interruption after native publication")

    monkeypatch.setattr(corpus, "collect", collected_then_crash)
    with pytest.raises(KeyboardInterrupt):
        run(value)
    before = len(site.log)
    monkeypatch.setattr(corpus, "collect", original)
    result = run(value)
    assert result["counts"]["exported"] == 1 and len(site.log) == before


def test_interrupted_inflight_request_is_unknown_not_retried(kit, monkeypatch):
    site, value, _ = kit
    original = corpus.acquire_item

    def crash(config, state, fetcher, record, guard, **kwargs):
        record["phase"] = "collection-intent"
        state.data["pendingRequest"] = {"url": record["candidate"]["url"], "host": "127.0.0.1", "byteUpperBound": 100000, "startedAt": "synthetic"}
        state.save()
        raise KeyboardInterrupt

    monkeypatch.setattr(corpus, "acquire_item", crash)
    with pytest.raises(KeyboardInterrupt):
        run(value)
    before = len(site.log)
    monkeypatch.setattr(corpus, "acquire_item", original)
    result = run(value)
    assert result["counts"]["unknown"] == 1 and len(site.log) == before
    assert result["usage"]["unknownRequests"] == 1 and result["usage"]["unknownByteUpperBound"] == 100000
    assert saved(value)["blocked"] == ["127.0.0.1"]


def test_repeated_page_is_partial_and_never_recollects_completed_item(kit):
    site, value, _ = kit

    def current_page():
        page = int(parse_qs(urlsplit(site.log[-1]["path"]).query)["pageIndex"][0])
        site.routes[ROUTES["policy-news"][0]]["body"] = listing(["100000001"], page=page, more=page == 1, total=2)

    site.routes[ROUTES["policy-news"][0]]["hook"] = current_page
    result = run(value)
    assert result["counts"]["exported"] == 1 and result["state"] == "partial"
    assert result["channels"]["policy-news"]["reason"] == "portal_repeated_page"
    assert site.hits(ROUTES["policy-news"][1]) == 1


def test_caps_are_partial_even_when_all_selected_items_export(kit):
    site, value, _ = kit
    value["maxDocuments"] = 1
    site.route(ROUTES["policy-news"][0], listing(["100000001", "100000002"]))
    result = run(value)
    assert result["state"] == "partial" and result["reason"] == "document-cap"
    assert result["counts"]["pending"] == 1 and result["counts"]["exported"] == 1


@pytest.mark.parametrize("replacement,reason", [
    ((b'2026.10.23', b'not-a-day'), "portal_date_invalid"),
    ((b'newsId=100000001', b'newsId=100000001&unexpected=x'), "portal_link_invalid"),
    ((b'name="pageIndex" value="1"', b'name="pageIndex" value="2"'), "portal_page_nonadvancing"),
    ((b'name="endDate" value="2026-10-23"', b'name="endDate" value="2026-10-24"'), "portal_period_unbound"),
])
def test_listing_rejects_invalid_period_date_identity_and_page(kit, replacement, reason):
    site, value, _ = kit
    raw = listing(["100000001"]).replace(*replacement)
    with pytest.raises(IngestionFailure, match=reason):
        parse_listing(raw, corpus.Config.model_validate(value), "policy-news", 1)


@pytest.mark.parametrize("raw,more,count", [
    (listing(["100000001"], more=True), True, 1),
    (listing(["100000001"], more=True).replace(b"pageLink(2); return false;", b"pageLink(2)"), True, 1),
    (listing(["100000001"]), False, 1),
    (listing([]), False, 0),
], ids=["observed-next", "finite-next-variant", "proven-end", "proven-empty"])
def test_listing_requires_positive_continuation_or_end(kit, raw, more, count):
    _, value, _ = kit
    candidates, result_more = parse_listing(raw, corpus.Config.model_validate(value), "policy-news", 1)
    assert result_more is more
    assert len(candidates) == count


def test_real_empty_marker_ignores_featured_article_outside_results(kit):
    site, value, _ = kit
    featured = b'<aside><a href="/news/policyNewsView.do?newsId=100000001">featured, not a result</a></aside>'
    site.route(ROUTES["policy-news"][0], listing([]).replace(b"</body>", featured + b"</body>"))
    result = run(value)
    assert result["state"] == "completed" and result["candidateCount"] == 0
    assert result["channels"]["policy-news"]["reason"] == "listing-end"
    assert site.hits(ROUTES["policy-news"][1]) == 0


@pytest.mark.parametrize("raw", [
    listing(["100000001"], more=True).replace(b"pageLink(2); return false;", b"javascript:goNext()"),
    listing(["100000001"], more=True).replace(b'<div class="list_type">', b'<div class="unrecognized">'),
    listing(["100000001"], more=True).replace(b'<div class="paging">', b'<div class="unrecognized">'),
    listing(["100000001"], more=True).replace(b"<strong>2</strong>", b"<strong>1</strong>"),
    listing(["100000001"]).replace(b"<strong>1</strong>", b"<strong>2</strong>"),
    listing([]).replace(b'class="no_data"', b'class="unknown"'),
    listing([]).replace('<li class="no_data"><span>등록된 정보가 없습니다.</span></li>'.encode(), b""),
    listing([]).replace(b'</span></li></ul>', b'<a href="/news/policyNewsView.do?newsId=100000001">other</a></span></li></ul>'),
    listing([]).replace('<span>등록된 정보가 없습니다.</span>'.encode(), '<span><em>등록된 정보가 없습니다.</em></span>'.encode()),
], ids=["unknown-next", "missing-results", "missing-controls", "link-count-conflict", "count-without-next",
        "unknown-empty-marker", "missing-empty-marker", "empty-marker-with-link", "empty-marker-nested"])
def test_unknown_listing_never_reports_completed(kit, raw):
    site, value, _ = kit
    site.route(ROUTES["policy-news"][0], raw)
    result = run(value)
    assert result["state"] == "partial"
    assert result["channels"]["policy-news"]["reason"] == "portal_pagination_ambiguous"
    assert site.hits(ROUTES["policy-news"][1]) == 0


def test_second_page_positive_terminal_requires_observed_page_size(kit):
    _, value, _ = kit
    raw = listing(["100000002"], page=2, total=2)
    assert parse_listing(raw, corpus.Config.model_validate(value), "policy-news", 2, page_size=1)[1] is False
    with pytest.raises(IngestionFailure, match="portal_pagination_ambiguous"):
        parse_listing(raw.replace(b"<strong>2</strong>", b"<strong>3</strong>"), corpus.Config.model_validate(value), "policy-news", 2, page_size=1)


def test_foreign_and_symlink_state_refused_without_adoption(kit, tmp_path):
    _, value, _ = kit
    root = Path(value["stateDir"])
    root.mkdir()
    foreign = root / "foreign.sqlite3"
    foreign.write_bytes(b"not ours")
    with pytest.raises((IngestionFailure, OSError)):
        run(value)
    assert foreign.read_bytes() == b"not ours" and not (root / ".lock").exists()
    value["stateDir"] = str(tmp_path / "linked")
    Path(value["stateDir"]).symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        run(value)


def test_real_configuration_requires_two_second_pacing_and_no_model_grant(kit):
    _, value, _ = kit
    value.update(listingOrigin="https://www.korea.kr", articleOrigin="https://m.korea.kr", exactHosts=["www.korea.kr", "m.korea.kr"])
    value["policy"]["syntheticLoopback"] = False
    with pytest.raises(ValidationError):
        corpus.Config.model_validate(value)
    value["policy"]["minIntervalSeconds"] = 2.0
    assert corpus.Config.model_validate(value)
    value["grant"]["allowedOperations"].append("model-send")
    with pytest.raises(ValidationError):
        corpus.Config.model_validate(value)


def test_atomic_record_and_snapshot_never_publish_partial_bytes(tmp_path, monkeypatch):
    record = tmp_path / "record.json"
    snapshot = tmp_path / "snapshot.json"
    corpus.atomic(snapshot, {"generation": 1})
    original_link, original_replace = os.link, os.replace

    def crash(*args, **kwargs):
        raise KeyboardInterrupt("synthetic interruption before publication")

    monkeypatch.setattr(os, "link", crash)
    with pytest.raises(KeyboardInterrupt):
        corpus.atomic(record, {"complete": True}, immutable=True)
    assert not record.exists()
    monkeypatch.setattr(os, "link", original_link)
    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(KeyboardInterrupt):
        corpus.atomic(snapshot, {"generation": 2})
    assert json.loads(snapshot.read_bytes()) == {"generation": 1}
    monkeypatch.setattr(os, "replace", original_replace)
    corpus.atomic(record, {"complete": True}, immutable=True)
    assert json.loads(record.read_bytes()) == {"complete": True}


def test_exclusive_process_ownership_without_state_mutation(kit):
    import fcntl
    _, value, _ = kit
    run(value)
    path = Path(value["stateDir"])
    before = (path / "STATE.json").read_bytes()
    fd = os.open(path / ".lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(IngestionFailure, match="corpus_busy"):
            run(value)
    finally:
        os.close(fd)
    assert (path / "STATE.json").read_bytes() == before


def test_time_budget_remains_expired_across_resume(kit):
    site, value, _ = kit
    cfg = corpus.Config.model_validate(value)
    binding = {"config": cfg.wire(), "rightsSha256": byte_hash(corpus.load_evidence(cfg.rights_evidence)), "gateVersion": "korea-portal-static-3"}
    state = corpus.State(cfg, binding)
    state.data["startedAt"] = "2020-01-01T00:00:00+00:00"
    state.save()
    state.close()
    result = run(value)
    assert result["state"] == "partial" and result["channels"]["policy-news"]["reason"] == "timeout"
    assert site.log == []


def test_all_three_channels_use_native_export_and_balanced_caps(kit):
    site, value, _ = kit
    value["channels"] = [{"name": name, "maxPages": 1, "maxDocuments": 1} for name in ROUTES]
    value["maxDocuments"] = 3
    for number, channel in enumerate(ROUTES, 1):
        identifier = "10000000" + str(number)
        site.route(ROUTES[channel][0], listing([identifier], channel=channel))
        site.route(ROUTES[channel][1], article(site, identifier, channel=channel))
    result = run(value)
    assert result["counts"]["exported"] == 3 and result["state"] == "partial"
    assert all(c["exported"] == 1 for c in result["channels"].values())
    assert result["usage"]["requests"] == 7  # one robots cache shared by all three channels


def test_empty_response_is_a_terminal_refusal_not_a_parser_crash(kit):
    site, value, _ = kit
    site.route(ROUTES["policy-news"][1], b"")
    result = run(value)
    assert result["counts"]["refused"] == 1
    assert result["dispositions"][0]["reason"] == "portal_html_invalid"


def test_unmarked_article_is_not_licensed_by_neighboring_items(kit):
    site, value, _ = kit
    raw = article(site, "100000001")
    start = raw.index(b'<div class="law_copy_wrap">')
    site.route(ROUTES["policy-news"][1], raw[:start] + b"</div></div></body></html>")
    result = run(value)
    assert result["counts"]["refused"] == 1
    assert result["dispositions"][0]["reason"] == "portal_item_license_missing"


def test_rights_evidence_change_during_native_response_prevents_publication(kit):
    site, value, _ = kit
    hits = 0

    def revoke():
        nonlocal hits
        hits += 1
        if hits == 1:
            Path(value["rightsEvidence"]["path"]).write_text("revoked synthetic permission")

    site.routes[ROUTES["policy-news"][1]]["hook"] = revoke
    result = run(value)
    assert result["counts"]["failed"] == 1
    assert result["dispositions"][0]["reason"] == "corpus_evidence_changed"
    assert not (Path(value["stateDir"]) / "native" / "collections" / "item-100000001").exists()


def test_revocation_after_native_collection_prevents_local_export(kit, monkeypatch):
    site, value, _ = kit
    original = corpus.collect

    def collected_then_revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(value["rightsEvidence"]["path"]).write_text("revoked after native publication")
        return result

    monkeypatch.setattr(corpus, "collect", collected_then_revoke)
    result = run(value)
    root = Path(value["stateDir"])
    assert result["counts"]["failed"] == 1 and result["dispositions"][0]["reason"] == "corpus_evidence_changed"
    assert (root / "native" / "collections" / "item-100000001" / "collection.json").exists()
    assert not (root / "exports" / "100000001.json").exists()
    assert site.hits(ROUTES["policy-news"][1]) == 1


def test_revocation_during_cached_recovery_prevents_export_and_replay(kit, monkeypatch):
    site, value, _ = kit
    original = corpus.collect

    def collected_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt("interrupted after native publication")

    monkeypatch.setattr(corpus, "collect", collected_then_crash)
    with pytest.raises(KeyboardInterrupt):
        run(value)
    before = len(site.log)

    def cached_then_revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result["replayed"]
        Path(value["exclusionManifest"]["path"]).write_text("revoked during cached recovery")
        return result

    monkeypatch.setattr(corpus, "collect", cached_then_revoke)
    result = run(value)
    root = Path(value["stateDir"])
    assert result["counts"]["failed"] == 1 and result["dispositions"][0]["reason"] == "corpus_evidence_changed"
    assert (root / "native" / "collections" / "item-100000001" / "collection.json").exists()
    assert not (root / "exports" / "100000001.json").exists()
    assert len(site.log) == before


@pytest.mark.parametrize("tamper", ["body-hash", "native-body", "missing-facts", "hash-only", "changed-license", "changed-notice", "extra-fact", "boolean-as-integer"])
def test_cached_recovery_rejects_rights_facts_without_matching_native_body(kit, monkeypatch, tamper):
    site, value, _ = kit
    original = corpus.collect

    def collected_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt("interrupted after native publication")

    monkeypatch.setattr(corpus, "collect", collected_then_crash)
    with pytest.raises(KeyboardInterrupt):
        run(value)
    root = Path(value["stateDir"])
    rights = root / "items" / "100000001" / "rights.json"
    if tamper == "body-hash":
        changed = json.loads(rights.read_bytes())
        changed["bodySha256"] = "0" * 64
        rights.write_text(canonical(changed))
    elif tamper == "native-body":
        collection = root / "native" / "collections" / "item-100000001"
        native = json.loads((collection / "collection.json").read_bytes())
        body_hash = native["targets"][0]["bodySha256"]
        (collection / "bodies" / (body_hash + ".bin")).write_bytes(b"modified body")
    elif tamper == "missing-facts":
        rights.unlink()
    else:
        changed = json.loads(rights.read_bytes())
        if tamper == "hash-only":
            changed = {"bodySha256": changed["bodySha256"]}
        elif tamper == "changed-license":
            changed["license"] = "KOGL-type-4"
        elif tamper == "changed-notice":
            changed["notice"] = "텍스트 사용 조건이 변경되었습니다."
        elif tamper == "extra-fact":
            changed["unverified"] = True
        else:
            changed["contactPresent"] = int(changed["contactPresent"])
        rights.write_text(canonical(changed))
    before = len(site.log)
    monkeypatch.setattr(corpus, "collect", original)
    result = run(value)
    assert result["counts"]["unknown"] == 1 and result["dispositions"][0]["reason"] == "corpus_rights_receipt_mismatch"
    assert not (root / "exports" / "100000001.json").exists()
    assert len(site.log) == before


def test_revocation_during_local_export_is_not_published(kit, monkeypatch):
    site, value, _ = kit
    original = corpus.Ingestor.export

    def export_then_revoke(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        Path(value["rightsEvidence"]["path"]).write_text("revoked during local export")
        return result

    monkeypatch.setattr(corpus.Ingestor, "export", export_then_revoke)
    result = run(value)
    root = Path(value["stateDir"])
    assert result["counts"]["failed"] == 1 and result["dispositions"][0]["reason"] == "corpus_evidence_changed"
    assert not (root / "exports" / "100000001.json").exists()
    assert (root / "native" / "collections" / "item-100000001" / "collection.json").exists()
    assert site.hits(ROUTES["policy-news"][1]) == 1


def test_revocation_during_export_publication_retracts_only_new_export(kit, monkeypatch):
    site, value, _ = kit
    original_link = os.link
    revoked = False

    def publish_then_revoke(source, destination, **kwargs):
        nonlocal revoked
        original_link(source, destination, **kwargs)
        if destination == "100000001.json":
            revoked = True
            Path(value["rightsEvidence"]["path"]).write_text("revoked at export publication")

    monkeypatch.setattr(os, "link", publish_then_revoke)
    result = run(value)
    root = Path(value["stateDir"])
    assert revoked and result["counts"]["failed"] == 1
    assert result["dispositions"][0]["reason"] == "corpus_evidence_changed"
    assert not (root / "exports" / "100000001.json").exists()
    assert (root / "native" / "collections" / "item-100000001" / "collection.json").exists()
    assert site.hits(ROUTES["policy-news"][1]) == 1
