from dataclasses import replace
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from zoop_ai_pipeline import private_intake as intake
from zoop_ai_pipeline import private_continuation as continuation
from zoop_ai_pipeline.extraction_fallback import verify_extracted_page, prepare_markdown
from zoop_ai_pipeline.ingestion_contracts import IngestionFailure, canonical, digest, byte_hash, FileRef
from zoop_ai_pipeline.publication_evidence import publication_evidence, verify_publication
from zoop_ai_pipeline.private_retained import read_record, describe_record
from .test_private_intake import extracted_fixture, public_offline_config

WHEN = "2026-07-27T09:12:34.123+09:00"


def publication_config(tmp_path):
    values = public_offline_config(tmp_path).wire()
    values.update(exactArticleHosts=["techcrunch.com"],
                  sources=[{"name": "techcrunch", "sourceType": "editorial", "reliability": "authored fixture", "queries": []}])
    return intake.Config.model_validate(values)


def page_fixture(*, published=WHEN, canonical_url=None, status=200, title="Authored fixture", text=None):
    _, _, _, page = extracted_fixture()
    url = "https://techcrunch.com/2026/07/27/authored-fixture/"
    html = (f'<html><head><title>{title}</title><link rel="canonical" href="{canonical_url or url}">'
            + (f'<meta property="article:published_time" content="{published}">' if published else "")
            + '</head><body><div>Original article body without semantic scope.</div></body></html>').encode()
    native = replace(page.native_observation, requested_url=url, final_url=url,
                     http_status=status, media_type="text/html", body=html,
                     failure_code="article_scope_ambiguous_or_missing" if status == 200 else "http_403")
    content = text or "Provider Markdown body; no publication header."
    receipt = replace(page.provider_receipt, raw_response=canonical({"title": page.metadata.title, "content": content}).encode(),
                      received_bytes=None)
    return replace(page, requested_url=url, native_observation=native, retained_text=content, provider_receipt=receipt,
                   prepared_json=canonical(prepare_markdown(content)))


def test_record3_roundtrip_keeps_separate_native_and_provider_hashes_and_precision(tmp_path):
    page = page_fixture()
    config = publication_config(tmp_path)
    state = intake.State(config, "run")
    source = config.sources[0]
    identifier = "private-news-" + digest([config.plan_id, page.requested_url])
    item = {"url": page.requested_url, "refs": []}
    evidence = publication_evidence(source.name, page, descriptor=source.descriptor)
    meta = intake.archives.ArticleMeta(page.metadata.title, evidence["publishedAt"], None, None, None, source.source_type)
    try:
        record = intake._retain_extracted(config, state, identifier, item, source.name, source, meta,
                                          intake._publication(evidence["publishedAt"]), page, [])
    finally:
        state.close()
    reference = FileRef(file=identifier + ".json", sha256=byte_hash((Path(config.state_dir) / (identifier + ".json")).read_bytes()))
    retained, body, _, _ = read_record(Path(config.state_dir), reference)
    assert retained["schemaVersion"] == "zoop-private-news-record-3"
    assert retained["publication"]["raw"] == WHEN
    assert retained["publication"]["precision"] == "instant"
    assert retained["publicationEvidence"]["nativeRawSha256"] == byte_hash(page.native_observation.body)
    assert retained["publicationEvidence"]["markdownSha256"] == byte_hash(body)
    assert retained["publicationEvidence"]["nativeRawSha256"] != retained["publicationEvidence"]["markdownSha256"]
    assert page.metadata.published_at is None and retained["finalUrl"] is None
    index = {"sourceId": source.name, "stateDir": config.state_dir,
             "recordPath": str(Path(config.state_dir) / reference.file), "recordSha256": reference.sha256,
             "privateId": identifier, "planId": config.plan_id}
    described = describe_record(index, tmp_path / "native-input")
    assert described["item"]["private"]["recordSchema"] == "zoop-private-news-record-3"
    assert described["item"]["publishedAt"] == WHEN
    assert described["bodySha256"] == byte_hash(page.retained_text.encode())
    altered = copy.deepcopy(record)
    altered["publicationEvidence"]["nativeRawSha256"] = "a" * 64
    with pytest.raises(IngestionFailure, match="private_publication_evidence_invalid"):
        intake.verify_record(altered, body, extraction_raw=canonical(page.wire()).encode())


@pytest.mark.parametrize("changes,reason", [
    ({"canonical_url": "https://openai.com/index/other/"}, "publication_source_mismatch"),
    ({"title": "Other document"}, "publication_document_mismatch"),
    ({"published": None}, "article_date_unknown"),
    ({"status": 403}, "article_date_unknown"),
    ({"title": "Page not found"}, "fallback_error_page"),
    ({"title": "Access denied"}, "fallback_access_restricted"),
    ({"published": None, "text": "An event occurred on July 27, 2026.\n\nUpdated: July 28, 2026"}, "article_date_unknown"),
    ({"published": None, "text": "The story quotes a book jacket.\n\nPublished: 1999-01-01"}, "article_date_unknown"),
])
def test_publication_rejects_unbound_missing_and_error_evidence(changes, reason):
    with pytest.raises(IngestionFailure, match=reason):
        publication_evidence("techcrunch", page_fixture(**changes))


@pytest.mark.parametrize("value,expected", [
    ("Published: 2026-07-27", "2026-07-27"),
    ("Published on July 27, 2026", "2026-07-27"),
    ("Published: 2026-07-27T12:34", "2026-07-27T12:34"),
])
def test_explicit_publication_headers_do_not_invent_timezone_or_midnight(value, expected):
    page = page_fixture(status=403, text="# Authored fixture\n\n" + value + "\n\nArticle body.")
    proof = publication_evidence("techcrunch", page)
    assert proof["publishedAt"] == expected and proof["method"] == "explicit-markdown-header"
    assert proof["nativeRawSha256"] is None
    assert verify_publication(proof, "techcrunch", page) == expected


def test_retained_provider_bytes_are_independent_of_native_metadata_and_reject_tampering():
    page = page_fixture()
    wire = page.wire()
    assert verify_extracted_page(wire, allowed_hosts=("techcrunch.com",)).wire() == wire
    wire["nativeObservation"]["rawSha256"] = "f" * 64
    with pytest.raises(IngestionFailure, match="extracted_page_invalid"):
        verify_extracted_page(wire, allowed_hosts=("techcrunch.com",))
    conflicting = page_fixture(text="# Authored fixture\n\nPublished: 2026-07-28\n\nArticle body.")
    with pytest.raises(IngestionFailure, match="article_date_conflict"):
        publication_evidence("techcrunch", conflicting)


def old_group(tmp_path, mutation):
    root = tmp_path / "old"
    root.mkdir()
    page = page_fixture()
    config = {"planId": "old-plan"}
    binding = {"config": config}
    identifier = "private-news-" + digest(["old-plan", page.requested_url])
    candidate = {"url": page.requested_url, "status": "refused", "code": continuation.REASON, "refs": []}
    attempt = {"kind": "article", "key": identifier, "status": "refused", "code": continuation.REASON,
               "nativeObservation": page.native_observation.wire()}
    if mutation == "other-reason":
        candidate["code"] = attempt["code"] = "provider_unknown_no_retry"
    elif mutation == "provider-attempt":
        attempt["providerAttemptId"] = "unresolved-attempt"
    elif mutation == "provider-receipt":
        attempt["providerReceipt"] = {"outcome": "success"}
    elif mutation in {"404", "429"}:
        attempt["nativeObservation"]["httpStatus"] = int(mutation)
    elif mutation == "security":
        attempt["nativeObservation"]["access"] = "private"
    elif mutation == "missing-native":
        attempt.pop("nativeObservation")
    data = {"planDigest": digest(binding), "pendingRequest": None, "pendingProviderRequest": None}
    for name, value in (("PLAN.json", binding), ("STATE.json", {"state": data, "sha256": digest(data)})):
        (root / name).write_text(canonical(value))
    with sqlite3.connect(root / "QUEUE.sqlite3") as db:
        db.execute("CREATE TABLE binding(digest TEXT)")
        db.execute("INSERT INTO binding VALUES(?)", (digest(binding),))
        for table in ("candidates", "attempts", "tasks"):
            db.execute(f"CREATE TABLE {table}(key TEXT,value TEXT,sha256 TEXT)")
        db.execute("INSERT INTO candidates VALUES(?,?,?)", (identifier, canonical(candidate), digest(candidate)))
        db.execute("INSERT INTO attempts VALUES(?,?,?)", ("0", canonical(attempt), digest(attempt)))
        if mutation == "second-attempt":
            db.execute("INSERT INTO attempts VALUES(?,?,?)", ("1", canonical(attempt), digest(attempt)))
    return {"plan": continuation.pin(root / "PLAN.json"), "state": continuation.pin(root / "STATE.json"),
            "queue": continuation.pin(root / "QUEUE.sqlite3"), "members": [{"candidateId": identifier,
                "nativeObservationDigest": digest(attempt.get("nativeObservation"))}]}


@pytest.mark.parametrize("mutation", ["other-reason", "provider-attempt", "provider-receipt", "404", "429", "security", "missing-native", "second-attempt"])
def test_old_refusal_cannot_be_relabelled_without_zero_attempt_native_proof(tmp_path, mutation):
    group = old_group(tmp_path, mutation)
    before = {key: continuation.pin(group[key]["path"]) for key in ("plan", "state", "queue")}
    with pytest.raises(IngestionFailure):
        continuation._members(group)
    assert before == {key: continuation.pin(group[key]["path"]) for key in before}


def test_exact_old_refusal_retains_native_identity_and_original_bytes(tmp_path):
    group = old_group(tmp_path, None)
    _, _, members = continuation._members(group)
    assert len(members) == 1
    candidate, native = members[0]
    assert candidate["status"] == "refused" and native.http_status == 200
    assert digest(native.wire()) == group["members"][0]["nativeObservationDigest"]
    Path(group["queue"]["path"] + "-wal").write_bytes(b"unresolved")
    with pytest.raises(IngestionFailure, match="continuation_unsettled_database"):
        continuation._members(group)


def test_current_admission_refuses_robots_without_refetching_retained_article(tmp_path):
    from zoop_ai_pipeline.collection import Rules
    page = page_fixture()
    config = publication_config(tmp_path)
    state = intake.State(config, "run")
    config.known_unsent = intake.KnownUnsent.model_validate({"path": str(tmp_path / "proof.json"), "sha256": "a" * 64, "planId": "old"})
    native_pin = intake._retain_observation(state, page.native_observation)
    events = []
    class Transport:
        native_response = None
        native_redirects = []
        run_deadline = intake.time.monotonic() + 30
        def _guard(self, url):
            events.append(("guard", url))
        def _rules(self, url, deadline):
            events.append(("robots", url))
            return Rules(((False, "/"),))
        def fetch(self, url):
            pytest.fail("retained candidate must never perform another GET")
    transport = Transport()
    transport.state = state
    try:
        with pytest.raises(IngestionFailure, match="robots_denied"):
            intake._fetch_article(config, transport, page.requested_url, config.sources[0].name,
                                  {**native_pin, "reason": continuation.REASON})
        assert events == [("guard", page.requested_url), ("robots", page.requested_url)]
    finally:
        state.close()


def test_actual_retained_replay_cli_builds_verified_record_without_network_or_old_writes(tmp_path):
    page = page_fixture()
    config = publication_config(tmp_path)
    state = intake.State(config, "run")
    identifier = "private-news-" + digest([config.plan_id, page.requested_url])
    refs = [{"source": config.sources[0].name, "url": page.requested_url, "published_at": None}]
    try:
        state.data["candidates"][identifier] = {"url": page.requested_url, "status": "refused",
                                                "code": "article_date_unknown", "refs": refs}
        envelope = canonical(page.wire()).encode()
        intake._publish(state.fd, identifier + ".extraction.json", envelope, immutable=True)
        state.data["attempts"].append({"kind": "article", "key": identifier, "status": "refused",
            "code": "article_date_unknown", "providerOutcome": "success", "providerAttemptId": page.provider_receipt.attempt_id,
            "extractionArtifact": {"file": identifier + ".extraction.json", "sha256": byte_hash(envelope)}})
        state.save()
    finally:
        state.close()
    original = {path.name: byte_hash(path.read_bytes()) for path in Path(config.state_dir).iterdir()}
    output = tmp_path / "replayed"
    command = [sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "scripts/retained_news_replay.py"),
               "replay-markdown", "--state-dir", config.state_dir, "--output", str(output),
               "--approval-ref", "authored-offline-replay", "--limit", "1"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == {"considered": 1, "available": 1, "retained": 1, "unrecovered": {},
                      "externalCalls": 0, "originalsModified": False}
    index = json.loads((output / "INDEX.json").read_bytes())
    record = describe_record(index["privateItems"][0], tmp_path / "native-import")["record"]
    assert record["publication"]["raw"] == WHEN and record["schemaVersion"] == "zoop-private-news-record-3"
    assert original == {path.name: byte_hash(path.read_bytes()) for path in Path(config.state_dir).iterdir()}


@pytest.mark.parametrize("identity", [
    "own-actor-only", "same-candidate", "response-request", "response-final", "canonical",
    "native-final", "native-redirect", "retained-canonical", "retained-redirect", "other-actor-final",
])
def test_explicit_history_preserves_unknowns_over_actor_exception_and_reuses_refs(tmp_path, monkeypatch, identity):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import collection_history
    collect = collection_history.base
    url = "https://techcrunch.com/2026/07/27/authored-fixture/"
    roots = []
    before = {}
    for number, reason in enumerate(("fallback_admission_mismatch", "provider_unknown_no_retry")):
        root = tmp_path / f"prior-{number}"
        state = root / "state" / "old"
        state.mkdir(parents=True)
        (root / ".controller.lock").touch()
        collect.atomic(state / "PLAN.json", {"config": {"schemaVersion": "zoop-private-news-config-2", "planId": "old"}})
        candidate_url = url if number == 0 or identity == "same-candidate" else "https://techcrunch.com/2026/07/27/other-document/"
        identifier = "private-news-" + digest(["old", candidate_url])
        attempt = {"kind": "article", "key": identifier, "status": "refused" if number == 0 else "unknown", "code": reason}
        if number == 0 or identity == "other-actor-final":
            reason = "fallback_admission_mismatch"
            attempt.update(status="refused", code=reason,
                           nativeObservation={"requestedUrl": candidate_url, "finalUrl": candidate_url, "httpStatus": 200})
        if number == 1:
            if identity in {"response-request", "response-final", "other-actor-final"}:
                attempt["response"] = {"requestUrl": candidate_url, "finalUrl": candidate_url}
                attempt["response"]["requestUrl" if identity == "response-request" else "finalUrl"] = url
            elif identity == "canonical":
                attempt["articleMetadata"] = {"canonicalUrl": url}
            elif identity in {"native-final", "native-redirect"}:
                attempt["nativeObservation"] = {"requestedUrl": candidate_url, "finalUrl": candidate_url,
                                                "httpStatus": 200, "redirects": []}
                attempt["nativeObservation"]["finalUrl" if identity == "native-final" else "redirects"] = url if identity == "native-final" else [url]
            elif identity in {"retained-canonical", "retained-redirect"}:
                collect.atomic(state / "private-news-retained.json",
                               {"requestUrl": candidate_url, "canonicalUrl": url if identity == "retained-canonical" else None,
                                "redirects": [url] if identity == "retained-redirect" else []})
        collect.atomic(state / "STATE.json", {"state": {"candidates": {identifier: {
            "url": candidate_url, "status": attempt["status"], "code": reason}},
            "tasks": {}, "attempts": [attempt]}})
        plan = {"id": "old", "kind": "private", "hosts": ["techcrunch.com"], "configTemplate": {"stateDir": str(state)}}
        collect.atomic(root / "PLAN.json", {"runId": "old-run", "plans": [plan]})
        collect.atomic(root / "LEDGER.json", {"planSha256": collect.sha(root / "PLAN.json"), "endedAt": WHEN,
                                             "plans": {"old": {"status": "unknown"}}})
        collect.atomic(root / "INDEX.json", {"runId": "old-run", "privateItems": [{"recordPath": "/authored/retained.json"}], "nativeItems": []})
        roots.append(str(root))
        before.update({str(path): byte_hash(path.read_bytes()) for path in root.rglob("*") if path.is_file()})
    retained = {"privateItems": [], "nativeItems": [], "reusedCorpus": []}
    exclusion = collect.exclusion_sets()
    receipt = collection_history.include(roots, tmp_path / "fresh", retained, exclusion)
    assert collect.deny(url, exclusion) == ("prior_url_excluded" if identity == "own-actor-only" else "prior_url_no_replay")
    assert retained["privateItems"] == [{"recordPath": "/authored/retained.json"}]
    report = json.loads(Path(receipt["path"]).read_bytes())
    assert len(report["selected"]) == 2 and all(row["unknownPlans"] == ["old"] for row in report["selected"])
    for row in report["selected"]:
        for name, reference in row["snapshots"].items():
            assert reference["sha256"] == row["originals"][name]["sha256"]
    assert before == {path: byte_hash(Path(path).read_bytes()) for path in before}
    if identity != "own-actor-only":
        config = publication_config(tmp_path)
        state = intake.State(config, "run")
        current_id = "private-news-" + digest([config.plan_id, url])
        try:
            state.data["candidates"][current_id] = {
                "url": url, "status": "pending",
                "refs": [{"source": config.sources[0].name, "url": url, "published_at": None}],
                "reusableNative": {**intake._retain_observation(state, page_fixture().native_observation),
                                   "reason": "fallback_admission_mismatch"}}
            state.save()
        finally:
            state.close()
        # Author a persisted, already-seeded synthetic state; this test exercises
        # selection after proof admission, not the separately tested proof producer.
        config.known_unsent = intake.KnownUnsent.model_validate(
            {"path": str(tmp_path / "already-admitted-proof.json"), "sha256": "a" * 64, "planId": "old"})
        binding = intake._binding(config)
        current_root = Path(config.state_dir)
        (current_root / "PLAN.json").write_text(canonical(binding))
        snapshot = json.loads((current_root / "STATE.json").read_bytes())
        snapshot["state"]["planDigest"] = digest(binding)
        snapshot["sha256"] = digest(snapshot["state"])
        (current_root / "STATE.json").write_text(canonical(snapshot))
        with sqlite3.connect(current_root / "QUEUE.sqlite3") as db:
            db.execute("DELETE FROM tasks")
            db.execute("UPDATE binding SET digest=?", (digest(binding),))
        config_path, exclusions_path = tmp_path / "child.json", tmp_path / "exclusions.json"
        collect.atomic(config_path, config.wire())
        collect.atomic(exclusions_path, collect.frozen_exclusions(exclusion))
        dispatches = []

        def forbidden_dispatch(*args, **kwargs):
            dispatches.append("attempted")
            pytest.fail("noReplay aliases must stop before any article GET or provider dispatch")

        monkeypatch.setattr(intake, "PrivateFetcher", intake.PrivateFetcher)
        monkeypatch.setattr(intake, "_selection", intake._selection)
        monkeypatch.setattr(intake.PrivateFetcher, "fetch", forbidden_dispatch)
        monkeypatch.setattr(intake._FundedFetch, "fetch", forbidden_dispatch)
        collect.child("private", config_path, exclusions_path)
        with continuation.immutable_db(current_root / "QUEUE.sqlite3") as db:
            item = json.loads(db.execute("SELECT value FROM candidates WHERE key=?", (current_id,)).fetchone()[0])
            assert item["status"] == "refused" and item["code"] == "prior_url_no_replay"
            assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
        assert dispatches == []


def replay_fixture(tmp_path, *, count=1, unresolved=False):
    """Persist authored historical Fetch receipts, then use the actual offline CLI."""
    tmp_path.mkdir(parents=True)
    config = publication_config(tmp_path)
    state = intake.State(config, "run")
    try:
        for number in range(count + int(unresolved)):
            page = page_fixture(published=None if number == count else WHEN)
            url = page.requested_url.replace("authored-fixture/", f"authored-{number}/")
            native = replace(page.native_observation, requested_url=url, final_url=url,
                             body=page.native_observation.body.replace(page.requested_url.encode(), url.encode()))
            page = replace(page, requested_url=url, native_observation=native)
            identifier = "private-news-" + digest([config.plan_id, url])
            refs = [{"source": "techcrunch", "url": url, "published_at": None}]
            state.data["candidates"][identifier] = {"url": url, "status": "refused", "code": "article_date_unknown", "refs": refs}
            envelope = canonical(page.wire()).encode()
            intake._publish(state.fd, identifier + ".extraction.json", envelope, immutable=True)
            state.data["attempts"].append({"kind": "article", "key": identifier, "status": "refused",
                "code": "article_date_unknown", "providerOutcome": "success", "providerAttemptId": page.provider_receipt.attempt_id,
                "extractionArtifact": {"file": identifier + ".extraction.json", "sha256": byte_hash(envelope)}})
        state.save()
    finally:
        state.close()
    output = tmp_path / "replay"
    result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "scripts/retained_news_replay.py"),
        "replay-markdown", "--state-dir", config.state_dir, "--output", str(output),
        "--approval-ref", "authored-offline-replay", "--limit", "10000"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return output / "INDEX.json"


def collector_fixture(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import overnight_collect as collect
    from zoop_ai_pipeline.news_sources import source_descriptors, source_catalog
    seed = tmp_path / "seed"
    monkeypatch.setattr(collect, "AFTERNOON", seed)
    monkeypatch.setattr(collect, "OLD_ROOTS", ())
    monkeypatch.setattr(collect, "FOREIGN", tmp_path / "no-foreign-corpus")
    collect.atomic(seed / "configs/native-exclusions-prior-union.json", {"newsIds": []})
    collect.atomic(seed / "configs/native-rights-evidence-20261027.json", {"authorization": "authored fixture only"})
    collect.atomic(seed / "configs/afternoon-corporate-20261026-20261027.json", {"companyAliases": []})
    collect.atomic(seed / "configs/afternoon-korea-20261026-20261027.json", {
        "schemaVersion": "zoop-korea-corpus-1", "listingOrigin": "https://www.korea.kr",
        "articleOrigin": "https://m.korea.kr", "exactHosts": ["www.korea.kr", "m.korea.kr"],
        "grant": {"grantId": "authored", "revision": "authored", "sourceId": "korea-portal", "enabled": True,
                  "rights": "known", "allowedOperations": ["read", "store", "quote-display"], "recipients": [],
                  "purposes": [], "evidence": ["authored synthetic evidence only"], "expiresAt": None}})
    rows = collect.source_matrix([item.wire() for item in source_descriptors()], catalog=source_catalog())
    routes = seed / "routes.json"
    collect.atomic(routes, {"sources": [{"id": row["sourceId"], "name": row["label"],
                                        "roster": row.get("roster", "government_regulator")} for row in rows[:58]]})
    return collect, routes


def prepare_args(root, routes, packages, priors=()):
    args = ["prepare", "--root", str(root), "--routes", str(routes), "--approval-ref", "authored-bridge-only",
            "--from-day", "2026-07-27", "--fresh-from-day", "2026-10-28", "--through-day", "2026-10-29",
            "--stop-new-at", "2026-10-28T21:00:00Z"]
    for path in priors:
        args.extend(("--prior-collection", str(path)))
    for path in packages:
        args.extend(("--replay-package", str(path)))
    return args


def prior_fixture(root, native, private):
    import overnight_collect as collect
    collect.atomic(root / "PLAN.json", {"runId": "authored-prior", "plans": []})
    collect.atomic(root / "LEDGER.json", {"planSha256": collect.sha(root / "PLAN.json"), "endedAt": WHEN,
                                        "plans": {"unresolved": {"status": "unknown"}}})
    collect.atomic(root / "INDEX.json", {"schemaVersion": "zoop-overnight-collection-index-1",
                                        "runId": "authored-prior", "nativeItems": native, "privateItems": private})
    collect.atomic(root / "evidence/CURRENT_EXCLUSIONS.json",
                   {"urls": ["https://techcrunch.com/unknown-request"], "noReplayUrls": ["https://techcrunch.com/unknown-request"]})
    (root / ".controller.lock").touch()
    return root


@pytest.mark.parametrize("mutation", ["schema", "extra", "count", "record-v2", "record-future", "source", "raw", "mutable", "evidence"])
def test_prepare_rejects_invalid_replay_packages_before_frozen_plan(tmp_path, monkeypatch, mutation):
    collect, routes = collector_fixture(tmp_path, monkeypatch)
    path = replay_fixture(tmp_path / "old")
    index = collect.load(path)
    item = index["privateItems"][0]
    if mutation == "schema":
        index["schemaVersion"] = "zoop-retained-markdown-replay-2"
    elif mutation == "extra":
        index["publicUse"] = True
    elif mutation == "count":
        index["retained"] = 0
    elif mutation.startswith("record-"):
        record = collect.load(item["recordPath"])
        record["schemaVersion"] = "zoop-private-news-record-" + ("2" if mutation == "record-v2" else "4")
        collect.atomic(item["recordPath"], record)
        item["recordSha256"] = collect.sha(item["recordPath"])
    elif mutation == "source":
        binding = collect.load(path.parent / "state/PLAN.json")
        binding["config"]["sources"][0]["reliability"] = "different frozen source descriptor"
        collect.atomic(path.parent / "state/PLAN.json", binding)
    elif mutation == "raw":
        Path(item["recordPath"]).with_suffix(".raw").write_bytes(b"changed retained bytes")
    elif mutation == "mutable":
        (path.parent / "state/QUEUE.sqlite3").write_bytes(b"mutable queue must never be treated as a record package")
    elif mutation == "evidence":
        index["evidencePins"] = []
    collect.atomic(path, index)
    root = tmp_path / "new-collection"
    with pytest.raises((ValueError, IngestionFailure)):
        collect.main(prepare_args(root, routes, [path]))
    assert not (root / "PLAN.json").exists()


def test_replay_identity_dedup_conflicts_and_post_prepare_mutation(tmp_path, monkeypatch):
    collect, routes = collector_fixture(tmp_path, monkeypatch)
    import collection_history
    path = replay_fixture(tmp_path / "old", unresolved=True)
    index = collect.load(path)
    item = index["privateItems"][0]
    first = prior_fixture(tmp_path / "prior-a", [], [item])
    second = prior_fixture(tmp_path / "prior-b", [], [item])
    root = tmp_path / "new-collection"
    before = {str(p): p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
    assert collect.main(prepare_args(root, routes, [path, path], [first, second])) == 0
    combined = collect.load(root / "INDEX.json")
    assert combined["privateItems"] == [item]
    assert all(value["freshness"] == "reused" for value in combined["itemFreshness"].values())
    replay = [row for row in combined["reusedCorpus"] if row["kind"] == "retained-markdown-replay"]
    assert len(replay) == 1 and replay[0]["unrecovered"] == {"article_date_unknown": 1}
    assert replay[0]["externalCalls"] == 0 and replay[0]["newCollection"] is False
    assert before == {str(p): p.read_bytes() for p in path.parent.rglob("*") if p.is_file()}
    exclusions = collect.load(root / "evidence/PRIOR_EXCLUSIONS.json")
    assert "https://techcrunch.com/unknown-request" in exclusions["noReplayUrls"]
    assert collect.load(root / "evidence/PRIOR_COLLECTIONS.json")["selected"][0]["unknownPlans"] == ["unresolved"]
    with pytest.raises(ValueError, match="identity_conflict"):
        collection_history.merge_private([item, {**item, "recordSha256": "0" * 64}])
    with pytest.raises(ValueError, match="identity_conflict"):
        collection_history.merge_private([item, {**item, "sourceId": "other-source"}])
    with pytest.raises(ValueError, match="reference_conflict"):
        collect.unique_items([item, {**item, "recordSha256": "0" * 64}], "recordPath")
    manifest, ledger = collect.load(root / "PLAN.json"), collect.load(root / "LEDGER.json")
    collect.validate_manifest(root, manifest, ledger)
    queue = path.parent / "state/QUEUE.sqlite3"
    queue.write_bytes(b"new mutable queue after preparation")
    with pytest.raises(ValueError, match="immutable_replay_package_required"):
        collect.validate_manifest(root, manifest, ledger)
    queue.unlink()
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(IngestionFailure, match="pin_changed"):
        collect.validate_manifest(root, manifest, ledger)
    old_index = (root / "INDEX.json").read_bytes()
    with pytest.raises(IngestionFailure, match="pin_changed"):
        collect.publish_index(root, manifest, ledger)
    assert (root / "INDEX.json").read_bytes() == old_index


def test_replay_combined_index_has_no_128_record_truncation_and_keeps_empty_unknowns(tmp_path, monkeypatch):
    collect, routes = collector_fixture(tmp_path, monkeypatch)
    from overnight_inputs import indexed_items
    path = replay_fixture(tmp_path / "old", count=129)
    unknown = replay_fixture(tmp_path / "unknown", count=0, unresolved=True)
    empty = replay_fixture(tmp_path / "empty", count=0)
    root = tmp_path / "new-collection"
    collect.main(prepare_args(root, routes, [path, unknown, empty]))
    items = indexed_items(root / "INDEX.json")
    assert len(items) == 129 and len({item["privateId"] for item in items}) == 129
    summaries = [row for row in collect.load(root / "INDEX.json")["reusedCorpus"] if row["kind"] == "retained-markdown-replay"]
    assert [row["retained"] for row in summaries] == [129, 0, 0]
    assert summaries[1]["unrecovered"] == {"article_date_unknown": 1} and summaries[2]["available"] == 0


def test_replay_collector_cli_to_controller_private_native_admission(tmp_path, monkeypatch):
    from .test_overnight_history import make_original, ACTOR
    from zoop_ai_pipeline import live_budget
    from .live_support import environment
    from zoop_ai_pipeline import live_runtime as live
    environment(monkeypatch, tmp_path / "authored-budget", **{live.OPENAI_KEY_VAR: None, live.JEV_KEY_VAR: None})
    collect, routes = collector_fixture(tmp_path, monkeypatch)
    from scripts import overnight_run as runner
    from overnight_inputs import indexed_items
    path = replay_fixture(tmp_path / "old", unresolved=True)
    native, _ = make_original(tmp_path / "native-old", "one", tmp_path / "native-inputs", monkeypatch)
    native["sourceKind"] = "policy-news"
    priors = [prior_fixture(tmp_path / "prior-a", [native], []), prior_fixture(tmp_path / "prior-b", [native], [])]
    root = tmp_path / "new-night"
    collection = root / "collection"
    config_path = tmp_path / "run.json"
    collect.atomic(config_path, {"schemaVersion": "zoop-private-run-4", "funding": {"totalMaxUsd": "4", "sharedMaxUsd": "3.5", "personalMaxUsd": "0.5"}, "runId": "authored-replay-cli", "root": str(root),
        "admitFrom": "2026-10-28T09:00:00Z", "admitUntil": "2026-10-28T21:00:00Z", "finishBy": "2026-10-28T22:00:00Z",
        "graphPort": 32829, "maxCalls": 100000, "processingActor": ACTOR})
    old_plan = tmp_path / "old-night/collection/PLAN.json"
    collect.atomic(old_plan, {"unchanged": "previously frozen, never launched"})
    original_plan = old_plan.read_bytes()
    # Only historical input locations are injected; parser, PREPARE, verification
    # and publication execute unchanged in the actual collector process.
    program = ("import sys; from pathlib import Path; import overnight_collect as c; "
               "c.AFTERNOON=Path(sys.argv[1]); c.OLD_ROOTS=(); c.FOREIGN=Path(sys.argv[2]); "
               "raise SystemExit(c.main(sys.argv[3:]))")
    import os
    env = {key: os.environ[key] for key in ("HOME", "PATH", "PYTHONPATH") if key in os.environ}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "scripts") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-B", "-c", program, str(collect.AFTERNOON), str(collect.FOREIGN),
        *prepare_args(collection, routes, [path], priors), "--enable-deepseek-fetch", "--run-config", str(config_path)],
        env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["prepared"] is True
    assert len(indexed_items(collection / "INDEX.json")) == 2
    assert old_plan.read_bytes() == original_plan
    for wrong in (tmp_path / "collection-other-run", root / "collection-with-retained-replay", root / "nested/collection"):
        with pytest.raises(ValueError, match="collection_funding_config_mismatch"):
            collect.validate_run_config(collect.ref(config_path), wrong, "2026-10-28T21:00:00Z")
    args = runner.parse(["--check", "--run-config", str(config_path), "--collection-index", str(collection / "INDEX.json"),
                         "--preparation-chunks", "1", "--exclude-unit", "2332ecd8df34079606e28a5f"])
    for name in ("RUN_CONFIG", "RUN_CONFIG_PATH", "ROOT", "RUN_ID", "ADMIT_UNTIL", "GRAPH_PORT", "MAX_CALLS"):
        monkeypatch.setattr(runner, name, getattr(runner, name))
    runner.configure(args)
    monkeypatch.setattr(live_budget, "_now", lambda: "2026-10-28T10:00:00Z")
    monkeypatch.setattr(runner, "remaining", lambda _: 3600)
    controller = runner.Controller(args)
    monkeypatch.setattr(controller, "provision_graph", lambda: None)
    monkeypatch.setattr(runner, "read_named_env", lambda *args: pytest.fail("keyless admission must not read credentials"))
    checked = controller.check()
    assert checked["units"] == 2 and checked["paidCalls"] == 0
    check = collect.load(root / "control/CHECK.json")
    assert check["budget"]["calls"] == 0
    units = check["pins"]["units"]
    assert {unit["sourceId"] for unit in units} == {"techcrunch", "korea-portal"}
    private = next(unit for unit in units if unit["sourceId"] == "techcrunch")
    record = collect.load(collect.load(path)["privateItems"][0]["recordPath"])
    assert private["publication"]["collectedAt"] == record["observedAt"]
    exported = collect.load(private["export"])
    assert exported["document"]["text"] == record["prepared"]["text"]
    assert exported["grant"]["grantId"].startswith("private-processing:")
    source = next(source for source in collect.load(private["registry"])["sources"] if source["sourceId"] == "techcrunch")
    assert source["grant"]["rights"] == "unknown" and source["grant"]["enabled"] is False
    assert runner.HISTORY_CHUNK_UNITS == 128
