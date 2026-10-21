"""Native S2-2 analysis contract: golden identity parity, strict replay parsing, the replay format and the treatment of pre-cutover jobs.

`data/native_analysis_golden.json` holds the literal preimages, keys and versions that the original pinned analysis package (commit
fa446e7c) computed once, offline, for synthetic articles and mentions. Every expectation below is read from that file, never recomputed
through the production code under test. Replay is authored-response replay, never independent AI inference."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.legacy_ledger import copy_as_legacy, counts, rows
from tests.test_extraction import PROMPT, Q3B, calls, event, same_of, world  # noqa: F401  (`world` is the fixture of test_extraction)
from zoop_ai_pipeline import extraction_replay as analysis
from zoop_ai_pipeline.extraction import Extractor, Sources, current
from zoop_ai_pipeline.extraction_contracts import (ADAPTER_VERSION, Catalogue, ExtractionFailure, Mention, ReplyInvalid, digest)

GOLDEN = json.loads((Path(__file__).parent / "data" / "native_analysis_golden.json").read_text(encoding="utf-8"))
INPUTS, EXPECTED = GOLDEN["inputs"], GOLDEN["expected"]
ANALYSIS = INPUTS["analysisVersion"]


def article(name: str, synthetic: bool = True):
    return analysis.article(INPUTS["exports"][name], synthetic)


def mention(name: str) -> Mention:
    return Mention.model_validate(INPUTS["mentions"][name], strict=True)


def catalogue(name: str) -> Catalogue:
    return Catalogue.model_validate(INPUTS["catalogues"][name])


# ---------------------------------------------------------------- golden parity --------------------------------------

@pytest.mark.parametrize("name", sorted(EXPECTED["articles"]))
def test_article_projection_and_version_equal_the_captured_original(name):
    built = article(name)
    assert built.model_dump(mode="json") == EXPECTED["articles"][name]["projection"]
    assert built.version == EXPECTED["articles"][name]["version"]
    assert "collected_at" not in built.model_dump()


def test_a_non_synthetic_article_has_the_captured_distinct_version_and_only_that_flag_differs():
    actual, synthetic = article("a", synthetic=False), article("a")
    assert actual.version == EXPECTED["actualArticleVersionA"] != synthetic.version
    assert {k for k, v in actual.model_dump().items() if v != synthetic.model_dump()[k]} == {"synthetic"}


@pytest.mark.parametrize("name", sorted(EXPECTED["mentions"]))
def test_mention_dump_and_digest_equal_the_captured_original_including_defaults(name):
    built = mention(name)
    assert built.model_dump(mode="json") == EXPECTED["mentions"][name]["dump"]
    assert digest(built.model_dump(mode="json")) == EXPECTED["mentions"][name]["digest"]


@pytest.mark.parametrize("case", INPUTS["extractCases"], ids=lambda c: c["id"])
def test_extract_request_preimage_and_digest_equal_the_captured_original(case):
    built = analysis.extract_input(article(case["article"]), INPUTS["promptVersion"], catalogue(case["catalogue"]))
    assert built == EXPECTED["extract"][case["id"]]["input"]
    assert analysis.request_digest("extract", built, ANALYSIS) == EXPECTED["extract"][case["id"]]["key"]


@pytest.mark.parametrize("case", INPUTS["compareCases"], ids=lambda c: c["id"])
def test_compare_request_preimage_and_digest_equal_the_captured_original(case):
    built = analysis.compare_input(mention(case["mention"]), case["eventId"], [mention(m) for m in case["members"]],
                                   [article(a) for a in case["articles"]], article(case["incoming"]))
    assert built == EXPECTED["compare"][case["id"]]["input"]
    assert analysis.request_digest("compare", built, ANALYSIS) == EXPECTED["compare"][case["id"]]["key"]


def with_publisher(name: str, publisher: str = "합성일보 Synthetic Daily") -> dict:
    """The pinned golden export, plus an operator-declared publisher on the observation and another outer documentVersion (what a declared outlet changes)."""
    export = json.loads(json.dumps(INPUTS["exports"][name]))
    export["observation"].update(publisher=publisher, documentVersion="f" * 64)
    return export


@pytest.mark.parametrize("name", sorted(EXPECTED["articles"]))
def test_a_declared_publisher_never_changes_the_captured_article_projection_or_version(name):
    built = analysis.article(with_publisher(name), True)
    assert built.model_dump(mode="json") == EXPECTED["articles"][name]["projection"] and built.publisher == ""
    assert built.version == EXPECTED["articles"][name]["version"]
    if name == "a":
        assert analysis.article(with_publisher("a"), False).version == EXPECTED["actualArticleVersionA"]


@pytest.mark.parametrize("case", INPUTS["extractCases"], ids=lambda c: c["id"])
def test_a_declared_publisher_never_enters_the_captured_extract_request(case):
    built = analysis.extract_input(analysis.article(with_publisher(case["article"]), True), INPUTS["promptVersion"], catalogue(case["catalogue"]))
    assert built == EXPECTED["extract"][case["id"]]["input"] and "합성일보" not in json.dumps(built, ensure_ascii=False)
    assert analysis.request_digest("extract", built, ANALYSIS) == EXPECTED["extract"][case["id"]]["key"]


@pytest.mark.parametrize("case", INPUTS["compareCases"], ids=lambda c: c["id"])
def test_a_declared_publisher_never_enters_the_captured_compare_request(case):
    built = analysis.compare_input(mention(case["mention"]), case["eventId"], [mention(m) for m in case["members"]],
                                   [analysis.article(with_publisher(a), True) for a in case["articles"]], analysis.article(with_publisher(case["incoming"]), True))
    assert built == EXPECTED["compare"][case["id"]]["input"] and "합성일보" not in json.dumps(built, ensure_ascii=False)
    assert analysis.request_digest("compare", built, ANALYSIS) == EXPECTED["compare"][case["id"]]["key"]


def test_the_request_digest_binds_stage_input_and_analysis_version_and_ignores_catalogue_order():
    case = INPUTS["extractCases"][0]
    full = catalogue("full")
    reordered = Catalogue.model_validate({**full.wire(), "companies": list(reversed(full.wire()["companies"]))})
    request = analysis.extract_input(article(case["article"]), INPUTS["promptVersion"], full)
    key = EXPECTED["extract"][case["id"]]["key"]
    assert analysis.extract_input(article(case["article"]), INPUTS["promptVersion"], reordered) == request
    keys = {key, analysis.request_digest("compare", request, ANALYSIS), analysis.request_digest("extract", request, "authored-analysis-2"),
            analysis.request_digest("extract", {**request, "prompt_version": "other"}, ANALYSIS)}
    assert len(keys) == 4 and analysis.request_digest("extract", request, ANALYSIS) == key


# ---------------------------------------------------------------- strict parsing and quote grounding ----------------

A = article("a")
B = article("b")


def response(**over) -> dict:
    raw = json.loads(json.dumps(INPUTS["mentions"]["m-a"]))
    raw.update(over)
    return {"mentions": [raw]}


def span(raw: dict, **evidence) -> dict:
    raw["mentions"][0]["evidence"][0].update(evidence)
    return raw


def invalid(raw, parse, code):
    with pytest.raises(ReplyInvalid) as caught:
        parse(raw)
    assert caught.value.code == code


def extraction_invalid(raw):
    invalid(raw, lambda r: analysis.parse_extraction(r, A), "extraction_reply_invalid")


def test_a_valid_reply_keeps_its_exact_spans_and_a_null_unique_quote_is_resolved_from_the_body():
    kept = analysis.parse_extraction(response(), A).mentions[0].evidence[0]
    assert (kept.start, kept.end, kept.quote) == (16, 21, "공급 계약") and A.body[kept.start:kept.end] == kept.quote
    resolved = analysis.parse_extraction(span(response(), start=None, end=None), A).mentions[0].evidence[0]
    assert (resolved.start, resolved.end) == (16, 21)


@pytest.mark.parametrize("wrong", [{"start": 0, "end": 3}, {"start": True, "end": False}, {"start": "16", "end": "21"}, {"start": 99, "end": 100}])
def test_offsets_that_do_not_select_the_quote_are_never_trusted_and_are_re_derived_from_the_unique_quote(wrong):
    got = analysis.parse_extraction(span(response(), **wrong), A).mentions[0].evidence[0]
    assert (got.start, got.end) == (16, 21)


def test_a_repeated_quote_needs_its_exact_span_and_is_never_guessed():
    repeated = "계약"
    assert A.body.count(repeated) == 2
    extraction_invalid(span(response(), quote=repeated, start=None, end=None))
    second = A.body.rindex(repeated)
    got = analysis.parse_extraction(span(response(), quote=repeated, start=second, end=second + 2), A).mentions[0].evidence[0]
    assert (got.start, got.end) == (second, second + 2)


@pytest.mark.parametrize("change", [
    {"quote": "본문에 없는 문장"}, {"quote": ""}, {"quote": None}, {"article_version": "0" * 64}, {"article_id": ["not", "hashable"]}, {"article_id": "other-doc"},
    {"article_version": None}])
def test_evidence_that_names_an_unknown_source_or_an_absent_quote_is_a_permanent_reply_fault(change):
    extraction_invalid(span(response(), **change))


@pytest.mark.parametrize("raw", [
    {"mentions": []} | {"extra": 1}, {"mentions": "x"}, [], "mentions", None,
    response(assertion_status="maybe"), response(unknown_field=1), response(participants=[{"name": "x"}]), response(evidence=[]),
    response(mention_id=""), response(article_id="doc-golden-b"), response(article_version="0" * 64), response(keywords="a"), response(background="no"),
    {"mentions": response()["mentions"] * 2}])
def test_replies_violating_the_strict_mention_contract_are_permanent_faults(raw):
    extraction_invalid(raw)


def test_an_empty_mention_list_is_a_valid_empty_extraction():
    assert analysis.parse_extraction({"mentions": []}, A).mentions == []


def decision(**over) -> dict:
    return {"relation": "SAME", "reason": "authored", "evidence": [
        {"article_id": "doc-golden-a", "article_version": A.version, "quote": "공급 계약", "start": None, "end": None},
        {"article_id": "doc-golden-b", "article_version": B.version, "quote": "신규 공장 착공", "start": None, "end": None}], **over}


def test_a_comparison_reply_resolves_evidence_across_the_incoming_and_member_articles_and_defaults_to_no_evidence():
    got = analysis.parse_comparison(decision(), mention("m-a"), A, [B])
    assert [(e.article_id, e.start, e.end) for e in got.evidence] == [("doc-golden-a", 16, 21), ("doc-golden-b", 10, 18)]
    assert analysis.parse_comparison({"relation": "DIFFERENT", "reason": "authored"}, mention("m-a"), A, [B]).evidence == []


@pytest.mark.parametrize("raw", [decision(relation="MAYBE"), decision(extra=1), decision(reason=1), {"relation": "SAME"}, [], decision(evidence=[
    {"article_id": "doc-golden-c", "article_version": article("c").version, "quote": "투자 계약"}])])
def test_comparison_replies_with_unknown_relations_extra_keys_or_evidence_outside_the_compared_articles_are_permanent_faults(raw):
    invalid(raw, lambda r: analysis.parse_comparison(r, mention("m-a"), A, [B]), "comparison_reply_invalid")


def test_a_comparison_whose_mention_belongs_to_another_version_is_refused_before_its_reply_is_read():
    invalid(decision(), lambda r: analysis.parse_comparison(r, mention("m-b"), A, [B]), "comparison_reply_invalid")


@pytest.mark.parametrize("left,right,expected", [
    ({"period": "2026Q3"}, {"period": "2026Q4"}, True), ({"period": "2026-Q4"}, {"period": "2026 q4"}, False),
    ({"period": "2026Q3"}, {"period": None}, False), ({"assertion_status": "announced"}, {"assertion_status": "unknown"}, False),
    ({"assertion_status": "announced"}, {"assertion_status": "planned"}, True), ({"event_time": "2026-11"}, {"event_time": "2026-12"}, True),
    ({"event_time": ""}, {"event_time": "2026-12"}, False)])
def test_known_identity_fields_conflict_only_when_both_are_known_and_normalized_text_differs(left, right, expected):
    base = mention("m-a").model_dump(mode="json")
    assert analysis.incompatible(Mention.model_validate({**base, **left}), Mention.model_validate({**base, **right})) is expected


# ---------------------------------------------------------------- native replay format -------------------------------

def run_native(w, job="job-native", incoming="a2", members=("a1",)):
    request = w.kit.submit(job, w.refs[incoming], [event(w, "event-1", *members)])
    return request, w.kit.job("run", request, replay=same_of(w, incoming, *members, name="r-" + job).write())


def test_a_native_job_binds_the_native_adapter_and_replay_identity_and_current_recognizes_it(world):
    _, ready = run_native(world)
    assert ready["state"] == "ready" and ready["delivery"]["status"] == "current" and ready["usage"]["replayCalls"] == 2
    assert set(ready["binding"]["adapter"]) == {"version", "candidate", "fingerprint"} and ready["binding"]["adapter"]["version"] == ADAPTER_VERSION
    assert current(ready["binding"]) and not current({}) and not current({"adapter": "x"}) and not current({"adapter": {"version": "zoop-extraction-poc-adapter-1"}})


def test_the_analysis_label_is_part_of_every_candidate_identity_and_a_key_authored_for_another_label_is_missing(world):
    w, k = world, world.kit
    ids = []
    for label in ("authored-analysis-1", "authored-analysis-2"):
        replay = k.replay("r-" + label)
        replay.doc["analysisVersion"] = label
        replay.extract(w.art["a1"], [w.mentions["a1"]])
        done = k.job("run", k.submit("job-" + label, w.refs["a1"]), replay=replay.write())
        assert done["state"] == "ready" and done["binding"]["replay"]["analysisVersion"] == label
        ids.append((done["eventCandidates"][0]["mentionCandidateId"], done["eventCandidates"][0]["eventCandidateId"], done["binding"]["adapter"]["fingerprint"]))
    assert all(a != b for a, b in zip(*ids))
    relabelled = k.replay("r-relabel").extract(w.art["a1"], [w.mentions["a1"]])
    relabelled.doc["analysisVersion"] = "authored-analysis-3"     # records stay keyed under authored-analysis-1
    stopped = k.job("run", k.submit("job-relabel", w.refs["a1"]), replay=relabelled.write())
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "replay_response_missing" and stopped["usage"]["replayCalls"] == 0


def test_the_catalogue_is_part_of_the_extract_request_so_another_catalogue_finds_no_authored_response(world):
    w, k = world, world.kit
    replay = k.replay("r-cat").extract(w.art["a1"], [w.mentions["a1"]]).write()
    request = k.submit("job-cat", w.refs["a1"])
    other = {**request, "catalogue": {**request["catalogue"], "companies": [{**request["catalogue"]["companies"][0], "name": "다른이름"}, *request["catalogue"]["companies"][1:]]}}
    stopped = k.job("run", other, replay=replay)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "replay_response_missing" and stopped["usage"]["replayCalls"] == 0


def valid_doc(w) -> dict:
    return json.loads(w.kit.replay("r-doc").extract(w.art["a1"], [w.mentions["a1"]]).write().read_text(encoding="utf-8"))


def mutated(doc: dict, how: str) -> dict:
    doc = json.loads(json.dumps(doc))
    record = doc["records"][0]
    if how == "stage":
        record["stage"] = "validate"
    elif how == "response-list":
        record["response"] = [record["response"]]
    elif how == "digest-format":
        record["requestDigest"] = "ABC"
    elif how == "record-extra":
        record["input"] = {"copied": "source text"}
    elif how == "top-extra":
        doc["format_extra"] = 1
    elif how == "duplicate":
        doc["records"].append(json.loads(json.dumps(record)))
    return doc


@pytest.mark.parametrize("how", ["stage", "response-list", "digest-format", "record-extra", "top-extra", "duplicate"])
def test_a_header_valid_fixture_with_an_invalid_record_stops_the_job_before_any_call_is_reserved(world, how):
    w, k = world, world.kit
    path = k.root / f"{how}.replay.json"
    path.write_text(json.dumps(mutated(valid_doc(w), how), ensure_ascii=False), encoding="utf-8")
    stopped = k.job("run", k.submit("job-" + how, w.refs["a1"]), replay=path)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "replay_fixture_invalid"
    assert stopped["usage"]["replayCalls"] == 0 and calls(k) == []
    assert k.job("resume", k.job_selector("job-" + how))["failure"]["code"] == "replay_fixture_required"


def test_a_non_json_a_kindless_and_an_old_format_fixture_are_refused_with_nothing_written(world):
    w, k = world, world.kit
    request = k.submit("job-bad", w.refs["a1"])
    old = {"format": "investmate-replay-v2", "synthetic": True, "prompt_version": PROMPT, "model_version": "authored-model-1", "analysis_version": ANALYSIS,
           "embedding_version": "authored-embedding-1", "records": [{"stage": "extract", "input": {"article": "source text"}, "response": {"mentions": []}}]}
    kindless = {name: value for name, value in valid_doc(w).items() if name != "recordingKind"}
    for name, payload in (("not-json", b"{not json"), ("old-v2", json.dumps(old).encode()), ("no-kind", json.dumps(kindless).encode())):
        path = k.root / f"{name}.json"
        path.write_bytes(payload)
        with pytest.raises(ExtractionFailure, match="replay_fixture_invalid"):
            k.job("run", request, replay=path)
    assert rows(k.root) == []


def test_the_command_refuses_unusable_fixtures_with_the_stable_code_and_no_ledger_for_non_json(world):
    w, k = world, world.kit
    request = k.submit("job-cli-bad", w.refs["a1"])
    path = k.root / "garbage.json"
    path.write_bytes(b"\xff\xfe not json")
    assert k.run("run", request, replay=path, expected=2)["error"]["code"] == "replay_fixture_invalid" and not (k.root / "extraction").exists()
    old = k.root / "old.json"
    old.write_text(json.dumps({"format": "investmate-replay-v2", "synthetic": True, "records": []}), encoding="utf-8")
    assert k.run("run", request, replay=old, expected=2)["error"]["code"] == "replay_fixture_invalid" and rows(k.root) == []


def test_resuming_a_ready_native_job_needs_no_fixture_adds_no_call_and_returns_the_identical_result(world):
    w, k = world, world.kit
    request, ready = run_native(w, "job-receipt")
    before = calls(k)
    assert k.job("resume", k.job_selector("job-receipt")) == ready == k.job("inspect", k.job_selector("job-receipt"))
    assert calls(k) == before and [c[1] for c in before] == ["received", "received"]


# ---------------------------------------------------------------- jobs stored before the native cutover ------------

def forbid_source_reads(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("a legacy job read a source, its authority or built a context")

    for name in ("export", "resolve"):
        monkeypatch.setattr(Sources, name, forbidden)
    monkeypatch.setattr(Extractor, "_context", forbidden)


def test_inspecting_a_stored_legacy_job_shows_its_history_verbatim_but_delivers_nothing_and_reads_no_source(world, monkeypatch):
    w, k = world, world.kit
    _, native = run_native(w)
    legacy = copy_as_legacy(k.root, "job-native", "job-legacy")
    forbid_source_reads(monkeypatch)
    result = k.job("inspect", k.job_selector("job-legacy"))
    assert result["state"] == "ready" and result["binding"] == legacy["binding"] and result["binding"]["adapter"]["pocCommit"]
    assert result["delivery"] == {"status": "withheld", "code": "analysis_contract_changed"}
    assert "eventCandidates" not in result and "topicCandidates" not in result and Q3B not in json.dumps(result, ensure_ascii=False)
    assert result["counts"]["eventCandidates"] == native["counts"]["eventCandidates"] and result["usage"]["replayCalls"] == 2
    monkeypatch.undo()
    assert k.job("inspect", k.job_selector("job-native"))["delivery"]["status"] == "current"
    cli = k.run("inspect", k.job_selector("job-legacy"), expected=2)
    assert cli["delivery"] == {"status": "withheld", "code": "analysis_contract_changed"} and "eventCandidates" not in cli and cli["binding"] == legacy["binding"]


@pytest.mark.parametrize("state", ["queued", "stopped", "ready", "reconciling"])
def test_run_and_resume_refuse_a_legacy_job_in_every_state_before_any_read_call_or_write(world, monkeypatch, state):
    w, k = world, world.kit
    request, _ = run_native(w)
    replay = k.root / "r-job-native.replay.json"
    legacy = copy_as_legacy(k.root, "job-native", "job-legacy", state=state, children=state in {"ready", "stopped"},
                            failure="topic_replay_required" if state == "stopped" else None)
    before, before_children = rows(k.root), counts(k.root, "job-legacy")
    forbid_source_reads(monkeypatch)
    resubmitted = {**legacy["request"]}
    for command, argument, fixture in (("resume", k.job_selector("job-legacy"), replay), ("resume", k.job_selector("job-legacy"), None),
                                       ("run", resubmitted, replay)):
        with pytest.raises(ExtractionFailure, match="analysis_contract_changed"):
            k.job(command, argument, replay=fixture)
    other = k.replay("r-other").extract(w.art["a1"], [w.mentions["a1"]]).write()
    with pytest.raises(ExtractionFailure, match="analysis_contract_changed"):
        k.job("resume", k.job_selector("job-legacy"), replay=other)     # refused before the fixture hash is even compared
    assert rows(k.root) == before and counts(k.root, "job-legacy") == before_children
    monkeypatch.undo()
    for argv in (("resume", k.job_selector("job-legacy"), replay), ("run", resubmitted, replay)):
        assert k.run(argv[0], argv[1], replay=argv[2], expected=2)["error"]["code"] == "analysis_contract_changed"
    assert rows(k.root) == before


def test_a_native_resubmission_of_a_legacy_job_id_is_refused_as_history_instead_of_rewriting_or_conflicting(world):
    w, k = world, world.kit
    request, _ = run_native(w)
    copy_as_legacy(k.root, "job-native", "job-legacy", fixture_hash="9" * 64)
    before = rows(k.root)
    with pytest.raises(ExtractionFailure, match="analysis_contract_changed"):
        k.job("run", {**request, "jobId": "job-legacy"}, replay=k.root / "r-job-native.replay.json")
    assert rows(k.root) == before


def test_downstream_export_of_a_legacy_job_is_refused_by_the_owner_and_an_unready_one_stays_unready(world):
    w, k = world, world.kit
    run_native(w)
    copy_as_legacy(k.root, "job-native", "job-legacy")
    copy_as_legacy(k.root, "job-native", "job-legacy-queued", state="queued", children=False)
    with pytest.raises(ExtractionFailure, match="analysis_contract_changed"):
        k.job("export", k.job_selector("job-legacy"))
    with pytest.raises(ExtractionFailure, match="upstream_not_ready"):
        k.job("export", k.job_selector("job-legacy-queued"))
    assert k.job("export", k.job_selector("job-native"))[1]["delivery"]["status"] == "current"


def test_a_new_native_job_freezes_into_a_ledger_that_also_holds_legacy_jobs_without_touching_them(world):
    w, k = world, world.kit
    run_native(w)
    copy_as_legacy(k.root, "job-native", "job-legacy")
    legacy_before = [r for r in rows(k.root) if r["job_id"] == "job-legacy"]
    second = k.job("run", k.submit("job-native-2", w.refs["a3"]), replay=k.replay("r-n2").extract(w.art["a3"], [w.mentions["a3"]]).write())
    assert second["state"] == "ready" and second["delivery"]["status"] == "current" and current(second["binding"])
    assert [r for r in rows(k.root) if r["job_id"] == "job-legacy"] == legacy_before
    db = sqlite3.connect(k.root / "extraction" / "extraction.sqlite3")
    try:
        assert db.execute("SELECT value FROM meta WHERE key='ledger'").fetchone()[0] == "zoop-extraction-ledger-1"
    finally:
        db.close()
    assert k.job("inspect", k.job_selector("job-legacy"))["delivery"]["code"] == "analysis_contract_changed"


def test_cancel_is_the_explicit_way_to_retire_a_legacy_job_and_keeps_every_stored_row(world):
    w, k = world, world.kit
    run_native(w)
    copy_as_legacy(k.root, "job-native", "job-legacy-queued", state="queued", children=False)
    copy_as_legacy(k.root, "job-native", "job-legacy-stopped", state="stopped", children=True, failure="topic_replay_required")
    kept = counts(k.root, "job-legacy-stopped")
    for job in ("job-legacy-queued", "job-legacy-stopped"):
        cancelled = k.job("cancel", k.job_selector(job))
        assert cancelled["state"] == "cancelled" and cancelled["resumeMode"] == "none" and cancelled["delivery"] == {"status": "withheld", "code": "job_cancelled"}
        assert "eventCandidates" not in cancelled
    assert counts(k.root, "job-legacy-stopped") == kept and kept["event_candidates"] == 1 and kept["calls"] == 2
    copy_as_legacy(k.root, "job-native", "job-legacy-ready")
    assert k.job("cancel", k.job_selector("job-legacy-ready"))["state"] == "ready"   # a finished job is never cancelled, legacy or not
