"""Offline S2-2 candidate behavior: exact observations, SAME guards, topic producer, recovery and rights.

Replay is authored-response replay, never independent AI inference. No network, model, PoC database or app state is used.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts.extraction_smoke import (INGESTION_SCHEMA, PROMPT, Q3, Q3B, Kit, page, topic_citation, topic_replay, topic_response)
from scripts.ingestion_smoke import exact_check
from zoop_ai_pipeline.extraction import Store
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure

QB = "합성기업은 4분기 신규 공장 착공을 알렸다."
QC = "합성기업은 2026년 4분기 공급 계약을 발표했다."
Q3C = "합성기업은 3분기 공급 계약을 공시했다."
SEPARATED = "확인.\n계약 상대는"


@pytest.fixture
def world(tmp_path):
    kit = Kit(tmp_path / "owned")
    refs = dict(zip(("a1", "a2", "b", "c", "a3"), kit.ingest("docs", [
        {"supplier": "supplier-a1", "html": page(Q3, "계약 상대는 합성상대다.")},
        {"supplier": "supplier-a2", "html": page(Q3B, "상대는 합성상대로 확인됐다.")},
        {"supplier": "supplier-b", "html": page(QB, "착공은 2026년 11월 예정이다."), "published": None},
        {"supplier": "supplier-c", "html": page(QC, "계약 상대는 합성상대다.")},
        {"supplier": "supplier-a3", "html": page(Q3C, "공시 상대는 합성상대다.")}])))
    art = {name: kit.article(ref) for name, ref in refs.items()}
    quotes = {"a1": Q3, "a2": Q3B, "b": QB, "c": QC, "a3": Q3C}
    periods = {"a1": "2026Q3", "a2": "2026Q3", "b": "2026Q4", "c": "2026Q4", "a3": "2026Q3"}
    mentions = {n: kit.mention(art[n], "m-" + n, [kit.evidence(art[n], quotes[n])], period=periods[n]) for n in refs}
    return SimpleNamespace(kit=kit, refs=refs, art=art, quotes=quotes, mentions=mentions)


def calls(kit):
    db = sqlite3.connect(kit.root / "extraction" / "extraction.sqlite3")
    try:
        return db.execute("SELECT stage,state,verdict FROM calls ORDER BY started_at,attempt_id").fetchall()
    finally:
        db.close()


def dump(path):
    db = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()
    finally:
        db.close()


def same_of(w, incoming, *members, relation="SAME", name="same", evidence=None, event_id="event-1", member_mentions=None):
    """Replay for `incoming` extraction plus one compare against a whole event made of `members`."""
    mention = w.mentions[incoming]
    replay = w.kit.replay(name).extract(w.art[incoming], [mention])
    group = [(w.refs[m], w.art[m], (member_mentions or w.mentions)[m]) for m in members]
    default = [w.kit.evidence(w.art[incoming], w.quotes[incoming]), w.kit.evidence(w.art[members[0]], w.quotes[members[0]])]
    replay.compare(mention, event_id, group, w.art[incoming], relation, "authored decision", default if evidence is None else evidence)
    return replay


def event(w, event_id, *members, member_mentions=None):
    return w.kit.event(event_id, [(w.refs[m], (member_mentions or w.mentions)[m]) for m in members])


def disposition(result):
    return result["eventCandidates"][0]["disposition"]


# ---------------------------------------------------------------- ingestion export seam ------------------------------

def test_export_is_exact_authorized_observation_with_server_owned_metadata(world):
    kit, ref = world.kit, world.refs["b"]
    before = dump(kit.root / "ingestion" / "ingestion.sqlite3")
    exported = kit.cli("export", {"schemaVersion": INGESTION_SCHEMA, **ref}, state="ingestion")
    assert exported["observation"]["url"] == "https://example.invalid/docs/2" and exported["observation"]["publishedAt"] is None
    assert exported["observation"]["title"] == "authored" and exported["grant"] == {"grantId": "operator-grant", "revision": "rights-1"}
    selector = kit.selector("round-docs", documentId=ref["documentId"], documentVersion=ref["documentVersion"])
    assert exported["document"] == kit.cli("inspect", selector, state="ingestion")["document"]
    assert exported["locatorMetadata"]["rawVersion"] == ref["rawVersion"] != ref["documentVersion"]
    for forged in ({"documentVersion": "0" * 64}, {"rawVersion": "1" * 64}, {"ordinal": 9}, {"documentId": "doc-forged"}):
        assert kit.cli("export", {"schemaVersion": INGESTION_SCHEMA, **{**ref, **forged}}, state="ingestion", expected=2)["error"]["code"] == "observation_not_found"
    assert kit.cli("export", {"schemaVersion": INGESTION_SCHEMA, **{**ref, "roundId": "other"}}, state="ingestion", expected=2)["error"]["code"] == "round_not_found"
    assert dump(kit.root / "ingestion" / "ingestion.sqlite3") == before
    kit.registry["sources"][0]["grant"]["allowedOperations"] = ["read", "store"]
    kit.save_registry()
    assert kit.cli("export", {"schemaVersion": INGESTION_SCHEMA, **ref}, state="ingestion", expected=2)["error"]["code"] == "source_unauthorized"


# ---------------------------------------------------------------- identities / same event / topic -------------------

def test_two_documents_same_event_keep_document_mention_and_event_identities_separate(world):
    k, w = world.kit, world
    first = k.job("run", k.submit("job-a1", w.refs["a1"]), replay=k.replay("r1").extract(w.art["a1"], [w.mentions["a1"]]).write())
    assert first["state"] == "ready" and first["eventCandidates"][0]["disposition"]["status"] == "new-event-candidate"
    second = k.job("run", k.submit("job-a2", w.refs["a2"], [event(w, "event-1", "a1")]), replay=same_of(w, "a2", "a1").write())
    c1, c2 = first["eventCandidates"][0], second["eventCandidates"][0]
    assert disposition(second)["status"] == "same-event-candidate" and disposition(second)["targetEventId"] == "event-1"
    assert len({c1["eventCandidateId"], c2["eventCandidateId"], c1["mentionCandidateId"], c2["mentionCandidateId"]}) == 4
    assert c1["document"]["documentId"] != c2["document"]["documentId"] and c2["eventCandidateId"] != "event-1"
    comparison = c2["comparisons"][0]
    assert comparison["original"]["relation"] == comparison["effective"]["relation"] == "SAME" and len(comparison["citations"]) == 2
    assert {c["documentId"] for c in comparison["citations"]} == {w.refs["a1"]["documentId"], w.refs["a2"]["documentId"]}
    binding = second["binding"]["documents"][next(iter(second["binding"]["documents"]))]
    assert second["binding"]["adapter"]["pocCommit"] and binding["articleVersion"] in {a.version for a in w.art.values()}
    assert second["comparisonScope"]["retrieval"] == "none" and second["usage"]["paidModelCalls"] == 0
    for citation in c1["citations"]:
        document = k.cli("inspect", k.selector("round-docs", documentId=citation["documentId"], documentVersion=citation["documentVersion"]), state="ingestion")["document"]
        exact_check(document, citation["start"], citation["end"])


def test_distinct_events_same_topic_use_separate_producer_and_stable_candidate_ids(world):
    k, w = world.kit, world
    replay = k.replay("r").extract(w.art["b"], [w.mentions["b"]]).compare(w.mentions["b"], "event-1", [(w.refs["a1"], w.art["a1"], w.mentions["a1"])], w.art["b"], "DIFFERENT", "다른 분기", []).write()
    request = k.submit("job-topic", w.refs["b"], [event(w, "event-1", "a1")], topic=True)
    pending = k.job("run", request, replay=replay)
    assert pending["state"] == "stopped" and pending["failure"]["code"] == "topic_replay_required"
    digest = pending["failure"]["detail"]["topicRequestDigest"]
    candidate = pending["eventCandidates"][0]["eventCandidateId"]
    assert pending["eventCandidates"][0]["disposition"]["status"] == "new-event-candidate" and pending["topicCandidates"] == []
    topic = topic_replay(k, "t", {digest: topic_response([{
        "label": "합성 계약과 공장", "criteria": "같은 기업의 후속 사업", "rationale": "authored", "members": [
            {"kind": "event-candidate", "ref": candidate}, {"kind": "snapshot-event", "ref": "event-1"}],
        "citations": [topic_citation(w.refs["b"], w.art["b"], QB), topic_citation(w.refs["a1"], w.art["a1"], Q3)]}])})
    done = k.job("resume", k.job_selector("job-topic"), topic=topic)
    assert done["state"] == "ready" and done["usage"]["replayCalls"] == 3 and [c["stage"] for c in done["calls"]] == ["extract", "compare", "topic"]
    only = done["topicCandidates"][0]
    assert only["status"] == "candidate" and only["approved"] is False and only["topicCandidateId"].startswith("tp-")
    assert {m["ref"] for m in only["members"]} == {candidate, "event-1"} and len(only["citations"]) == 2
    assert done["eventCandidates"][0]["eventCandidateId"] == candidate != only["topicCandidateId"]
    topic_call = done["calls"][-1]
    assert topic_call["requestDigest"] == digest and topic_call["fixtureHash"] == hashlib.sha256(topic.read_bytes()).hexdigest()
    again = k.job("run", k.submit("job-topic-2", w.refs["b"], [event(w, "event-1", "a1")], topic=True), replay=replay, topic=topic)
    assert again["topicCandidates"][0]["topicCandidateId"] == only["topicCandidateId"] and again["eventCandidates"][0]["eventCandidateId"] == candidate


@pytest.mark.parametrize("mutate,code", [
    (lambda t, ev, w: t["members"].append({"kind": "event-candidate", "ref": "evc-unknown"}), "topic_member_unknown"),
    (lambda t, ev, w: t["members"].append({"kind": "snapshot-event", "ref": ev}), "topic_member_duplicate"),
    (lambda t, ev, w: t.update(members=[{"kind": "snapshot-event", "ref": "event-9"}]), "topic_member_unknown"),
    (lambda t, ev, w: t["citations"].append(topic_citation(w.refs["c"], w.art["c"], QC)), "topic_citation_unbound"),
    (lambda t, ev, w: t["citations"].__setitem__(0, {**t["citations"][0], "quote": t["citations"][0]["quote"][:-1]}), "quote_mismatch"),
    (lambda t, ev, w: t.update(members=[]), "topic_reply_invalid"),
    (lambda t, ev, w: t.update(extra="unknown"), "topic_reply_invalid"),
])
def test_bad_topic_membership_or_citation_is_received_but_never_becomes_a_topic(world, mutate, code):
    k, w = world.kit, world
    replay = k.replay("r").extract(w.art["b"], [w.mentions["b"]]).compare(w.mentions["b"], "event-1", [(w.refs["a1"], w.art["a1"], w.mentions["a1"])], w.art["b"], "DIFFERENT", "다른 분기", []).write()
    pending = k.job("run", k.submit("job-bad", w.refs["b"], [event(w, "event-1", "a1")], topic=True), replay=replay)
    candidate = pending["eventCandidates"][0]["eventCandidateId"]
    proposal = {"label": "합성 주제", "criteria": "authored", "rationale": "authored", "members": [{"kind": "event-candidate", "ref": candidate}, {"kind": "snapshot-event", "ref": "event-1"}],
                "citations": [topic_citation(w.refs["b"], w.art["b"], QB), topic_citation(w.refs["a1"], w.art["a1"], Q3)]}
    mutate(proposal, "event-1", w)
    topic = topic_replay(k, "t", {pending["failure"]["detail"]["topicRequestDigest"]: topic_response([proposal])})
    failed = k.job("resume", k.job_selector("job-bad"), topic=topic)
    assert failed["state"] == "stopped" and failed["failure"]["code"] == code and failed["topicCandidates"] == []
    assert failed["stages"]["topic"]["state"] == "pending" and failed["eventCandidates"][0]["state"] == "candidate"
    before = calls(k)
    assert before[-1] == ("topic", "received", code)
    # The rejected receipt stays failed: no resend, no repair, no new row.
    assert k.job("resume", k.job_selector("job-bad"))["failure"]["code"] == code and calls(k) == before


def test_zero_events_never_fabricates_topic_or_calls_producer(world):
    k, w = world.kit, world
    replay = k.replay("r").extract(w.art["a1"], [], response={"mentions": []}).write()
    result = k.job("run", k.submit("job-zero", w.refs["a1"], topic=True), replay=replay)
    assert result["state"] == "ready" and result["eventCandidates"] == [] and result["topicCandidates"] == []
    assert result["stages"]["topic"] == {"state": "complete", "status": "no-events", "topics": 0} and result["usage"]["replayCalls"] == 1
    assert k.job("run", k.submit("job-off", w.refs["a1"]), replay=replay)["stages"]["topic"]["status"] == "not-requested"


# ---------------------------------------------------------------- SAME guards -----------------------------------------

@pytest.mark.parametrize("field,left,right", [("period", "2026Q3", "2026Q4"), ("event_time", "2026-09-30", "2026-10-31"), ("assertion_status", "announced", "planned")])
def test_known_contract_conflict_downgrades_model_same_but_unknown_does_not(world, field, left, right):
    k, w = world.kit, world
    incoming = {**w.mentions["a2"], field: left}
    member = {**w.mentions["a1"], field: right}
    replay = k.replay("conflict").extract(w.art["a2"], [incoming]).compare(incoming, "event-1", [(w.refs["a1"], w.art["a1"], member)], w.art["a2"], "SAME", "authored", [
        k.evidence(w.art["a2"], Q3B), k.evidence(w.art["a1"], Q3)])
    result = k.job("run", k.submit("job-conflict", w.refs["a2"], [k.event("event-1", [(w.refs["a1"], member)])]), replay=replay.write())
    comparison = result["eventCandidates"][0]["comparisons"][0]
    assert comparison["original"]["relation"] == "SAME" and comparison["effective"] == {"relation": "DIFFERENT", "rule": "all_member_incompatibility", "reason": comparison["effective"]["reason"]}
    assert disposition(result)["status"] == "new-event-candidate"
    # Missing values on either side are unknown, not conflicts and not invented dates.
    empty = "unknown" if field == "assertion_status" else None
    unknown_member = {**w.mentions["a1"], field: empty}
    unknown_incoming = {**w.mentions["a2"], field: empty}
    replay = k.replay("unknown").extract(w.art["a2"], [unknown_incoming]).compare(unknown_incoming, "event-1", [(w.refs["a1"], w.art["a1"], unknown_member)], w.art["a2"], "SAME", "authored", [
        k.evidence(w.art["a2"], Q3B), k.evidence(w.art["a1"], Q3)])
    result = k.job("run", k.submit("job-unknown", w.refs["a2"], [k.event("event-1", [(w.refs["a1"], unknown_member)])]), replay=replay.write())
    assert result["eventCandidates"][0]["comparisons"][0]["effective"]["relation"] == "SAME"
    assert disposition(result)["status"] == "same-event-candidate"


def test_every_member_is_checked_so_one_matching_member_never_unions_the_event(world):
    k, w = world.kit, world
    group = [(w.refs["a1"], w.art["a1"], w.mentions["a1"]), (w.refs["c"], w.art["c"], w.mentions["c"])]
    replay = k.replay("all").extract(w.art["a2"], [w.mentions["a2"]]).compare(w.mentions["a2"], "event-1", group, w.art["a2"], "SAME", "authored", [
        k.evidence(w.art["a2"], Q3B), k.evidence(w.art["a1"], Q3)])
    result = k.job("run", k.submit("job-all", w.refs["a2"], [k.event("event-1", [(w.refs["a1"], w.mentions["a1"]), (w.refs["c"], w.mentions["c"])])]), replay=replay.write())
    assert result["eventCandidates"][0]["comparisons"][0]["effective"]["relation"] == "DIFFERENT"
    assert result["eventCandidates"][0]["comparisons"][0]["effective"]["rule"] == "all_member_incompatibility"


def test_multiple_same_or_unresolved_hold_prevents_selection_without_transitive_union(world):
    k, w = world.kit, world
    mention = w.mentions["a2"]
    members = {"event-1": "a1", "event-2": "a3"}

    def build(relations, name):
        replay = k.replay(name).extract(w.art["a2"], [mention])
        for event_id, member in members.items():
            replay.compare(mention, event_id, [(w.refs[member], w.art[member], w.mentions[member])], w.art["a2"], relations[event_id], "authored",
                           [k.evidence(w.art["a2"], Q3B), k.evidence(w.art[member], w.quotes[member])] if relations[event_id] in {"SAME", "FOLLOWS"} else [])
        events = [event(w, event_id, member) for event_id, member in members.items()]
        return k.job("run", k.submit("job-" + name, w.refs["a2"], events), replay=replay.write())

    both = build({"event-1": "SAME", "event-2": "SAME"}, "both")
    held = disposition(both)
    assert (held["status"], held["reason"], held["targetEventId"], held["sameTargets"], held["comparedEvents"]) == ("held", "multiple_same_events", None, ["event-1", "event-2"], 2)
    mixed = build({"event-1": "SAME", "event-2": "HOLD"}, "mixed")
    assert disposition(mixed)["status"] == "held" and disposition(mixed)["heldBy"] == ["event-2"] and disposition(mixed)["targetEventId"] is None
    conflict = build({"event-1": "SAME", "event-2": "CONFLICT"}, "conflict")
    assert disposition(conflict)["status"] == "held"
    follows = build({"event-1": "FOLLOWS", "event-2": "DIFFERENT"}, "follows")
    assert disposition(follows)["status"] == "new-event-candidate" and disposition(follows)["follows"] == ["event-1"] and disposition(follows)["targetEventId"] is None


def test_same_without_exact_incoming_evidence_or_follows_without_incoming_source_holds(world):
    k, w = world.kit, world
    only_member = [k.evidence(w.art["a1"], Q3)]
    result = k.job("run", k.submit("job-follow", w.refs["a2"], [event(w, "event-1", "a1")]), replay=same_of(w, "a2", "a1", relation="FOLLOWS", evidence=only_member, name="follow").write())
    comparison = result["eventCandidates"][0]["comparisons"][0]
    assert comparison["original"]["relation"] == "FOLLOWS" and comparison["effective"]["relation"] == "HOLD" and comparison["effective"]["rule"] == "follows_incoming_evidence_missing"
    empty = k.job("run", k.submit("job-empty", w.refs["a2"], [event(w, "event-1", "a1")]), replay=same_of(w, "a2", "a1", evidence=[], name="empty").write())
    assert empty["eventCandidates"][0]["comparisons"][0]["effective"]["rule"] == "evidence_missing" and disposition(empty)["status"] == "held"


def test_forged_comparison_evidence_is_a_received_invalid_reply_and_never_reused(world):
    k, w = world.kit, world
    forged = [k.evidence(w.art["a2"], Q3B), {**k.evidence(w.art["a1"], Q3), "article_version": "f" * 64}]
    request = k.submit("job-forged", w.refs["a2"], [event(w, "event-1", "a1")])
    replay = same_of(w, "a2", "a1", evidence=forged, name="forged").write()
    failed = k.job("run", request, replay=replay)
    assert failed["state"] == "stopped" and failed["failure"]["code"] == "comparison_reply_invalid" and failed["stages"]["compare"]["state"] == "pending"
    rows = calls(k)
    assert rows[-1] == ("compare", "received", "comparison_reply_invalid")
    assert k.job("resume", k.job_selector("job-forged"), replay=replay)["failure"]["code"] == "comparison_reply_invalid" and calls(k) == rows


# ---------------------------------------------------------------- exact citations ------------------------------------

def test_exact_korean_emoji_citation_uses_code_points_and_rejects_generated_separator(world):
    k, w = world.kit, world
    quote_a = w.art["a1"]
    separated = k.evidence(quote_a, SEPARATED)
    assert quote_a.body[separated["start"]:separated["end"]] == SEPARATED  # PoC Evidence.matches alone would accept this
    mention = k.mention(quote_a, "m-sep", [separated])
    replay = k.replay("sep").extract(quote_a, [w.mentions["a1"], mention]).write()
    result = k.job("run", k.submit("job-sep", w.refs["a1"]), replay=replay)
    good, bad = (next(c for c in result["eventCandidates"] if c["localMentionId"] == i) for i in ("m-a1", "m-sep"))
    assert good["state"] == "candidate" and bad["state"] == "rejected" and bad["reason"] == "raw_locator_mismatch" and bad["citations"] == []
    citation = good["citations"][0]
    assert citation["end"] - citation["start"] == 34 and len(citation["quote"].encode("utf-16-le")) // 2 == 35
    assert citation["offsetUnit"] == "unicode_code_point" and citation["rawLocatorIds"] and citation["sourceSegments"][0]["domPath"].endswith("/p[1]")
    document = k.cli("inspect", k.selector("round-docs", documentId=citation["documentId"], documentVersion=citation["documentVersion"]), state="ingestion")["document"]
    exact_check(document, citation["start"], citation["end"])
    exact_check(document, separated["start"], separated["end"], False)
    assert result["counts"]["eventCandidates"] == {"total": 2, "candidate": 1, "rejected": 1}


def test_repeated_quote_requires_disambiguating_exact_span(world):
    k = world.kit
    ref, = k.ingest("repeat", [{"supplier": "supplier-r", "html": page("반복 문장이다.", "반복 문장이다.", "끝.")}])
    article = k.article(ref)
    ambiguous = k.mention(article, "m-r", [k.evidence(article, "반복 문장이다.", span=False)])
    failed = k.job("run", k.submit("job-r1", ref), replay=k.replay("r1").extract(article, [ambiguous]).write())
    assert failed["state"] == "stopped" and failed["failure"]["code"] == "extraction_reply_invalid" and calls(k)[-1] == ("extract", "received", "extraction_reply_invalid")
    second = k.mention(article, "m-r", [k.evidence(article, "반복 문장이다.", nth=1)])
    ok = k.job("run", k.submit("job-r2", ref), replay=k.replay("r2").extract(article, [second]).write())
    citation = ok["eventCandidates"][0]["citations"][0]
    assert citation["start"] == article.body.rindex("반복 문장이다.") and citation["sourceSegments"][0]["domPath"].endswith("/p[2]")


# ---------------------------------------------------------------- raw-only version / identity binding --------------

def test_raw_only_change_keeps_article_version_but_changes_every_candidate_identity(world):
    k, w = world.kit, world
    first_ref, = k.ingest("one", [{"supplier": "s-same", "html": page(Q3), "url": "https://example.invalid/same"}])
    second_ref, = k.ingest("two", [{"supplier": "s-same", "html": page(Q3).replace(b"&amp;", b"&#38;"), "url": "https://example.invalid/same"}])
    a, b = k.article(first_ref), k.article(second_ref)
    assert a.version == b.version and first_ref["documentId"] == second_ref["documentId"] and first_ref["documentVersion"] != second_ref["documentVersion"]
    mention = k.mention(a, "m-same", [k.evidence(a, Q3)])
    replay = k.replay("raw").extract(a, [mention]).write()
    one = k.job("run", k.submit("job-one", first_ref), replay=replay)
    two = k.job("run", k.submit("job-two", second_ref), replay=replay)
    c1, c2 = one["eventCandidates"][0], two["eventCandidates"][0]
    assert c1["mentionCandidateId"] != c2["mentionCandidateId"] and c1["eventCandidateId"] != c2["eventCandidateId"]
    assert c1["citations"][0]["documentVersion"] != c2["citations"][0]["documentVersion"] and c1["citations"][0]["quote"] == c2["citations"][0]["quote"]
    # A saved job cannot be satisfied by the other prepared version even though Article.version and request key are equal.
    with pytest.raises(ExtractionFailure, match="job_input_conflict"):
        k.job("run", k.submit("job-one", second_ref), replay=replay)
    # Equal Article.version in one comparison: the evidence source is ambiguous, so SAME holds (never newest/first).
    group = [(first_ref, a, mention)]
    compare = k.replay("ambiguous").extract(b, [mention]).compare(mention, "event-1", group, b, "SAME", "authored", [k.evidence(b, Q3), k.evidence(a, Q3)])
    held = k.job("run", k.submit("job-ambiguous", second_ref, [k.event("event-1", group_pairs(group))]), replay=compare.write())
    comparison = held["eventCandidates"][0]["comparisons"][0]
    assert comparison["effective"]["relation"] == "HOLD" and comparison["effective"]["rule"] == "evidence_source_ambiguous"


def group_pairs(group):
    return [(ref, mention) for ref, _, mention in group]


# ---------------------------------------------------------------- frozen input / contracts ---------------------------

def test_same_job_different_input_or_fixture_conflicts_and_wire_is_closed(world):
    k, w = world.kit, world
    replay = k.replay("r").extract(w.art["a1"], [w.mentions["a1"]]).write()
    request = k.submit("job-1", w.refs["a1"])
    k.job("run", request, replay=replay)
    for changed in ({**request, "promptVersion": "other"}, {**request, "incoming": w.refs["a2"]}, {**request, "snapshot": {"revision": "x", "events": []}}):
        with pytest.raises(ExtractionFailure, match="job_input_conflict|replay_prompt_version_conflict"):
            k.job("run", changed, replay=replay)
    other = k.replay("other").extract(w.art["a1"], [w.mentions["a1"]])
    other.doc["model_version"] = "authored-model-2"
    with pytest.raises(ExtractionFailure, match="job_input_conflict"):
        k.job("run", request, replay=other.write())
    with pytest.raises(ExtractionFailure, match="replay_fixture_changed"):
        k.job("resume", k.job_selector("job-1"), replay=other.write())
    for bad in ({**request, "unknown": 1}, {**request, "schemaVersion": "zoop-extraction-s2-9"}, {**request, "provenance": {**request["provenance"], "executionMode": "live", "recordingKind": "provider"}}):
        with pytest.raises(Exception):
            k.job("run", bad, replay=replay)
    live = k.run("run", {**request, "provenance": {**request["provenance"], "executionMode": "live", "recordingKind": "provider"}}, replay=replay, expected=2)
    assert live["error"]["code"] == "live_mode_unsupported"
    assert k.run("run", {**request, "unknown": 1}, replay=replay, expected=2)["error"]["code"] == "input_or_configuration_invalid"


@pytest.mark.parametrize("attack", ["version", "quote", "article", "forged-ref", "self", "duplicate", "reserved"])
def test_forged_or_ungrounded_snapshot_member_is_rejected_before_any_replay(world, attack):
    k, w = world.kit, world
    member = dict(w.mentions["a1"])
    ref = w.refs["a1"]
    members = [(ref, member)]
    if attack == "version":
        member["article_version"] = "0" * 64
    elif attack == "quote":
        member["evidence"] = [{**member["evidence"][0], "quote": "합성기업은 없는 문장이다.", "end": member["evidence"][0]["start"] + 14}]
    elif attack == "article":
        member["article_id"] = "doc-forged"
    elif attack == "forged-ref":
        ref = {**ref, "documentVersion": "2" * 64}
        members = [(ref, member)]
    elif attack == "self":
        members = [(w.refs["a2"], w.mentions["a2"])]
    elif attack == "duplicate":
        members = [(ref, member), (ref, member)]
    code = {"forged-ref": "observation_not_found"}.get(attack, "snapshot_member_invalid")
    events = [k.event("event-1", members)]
    if attack == "duplicate":
        events = [k.event("event-1", members[:1]), k.event("event-2", members[1:])]
    if attack == "reserved":
        events = [k.event("evc-1", members)]
    replay = k.replay("r").extract(w.art["a2"], [w.mentions["a2"]]).write()
    with pytest.raises(Exception) as caught:
        k.job("run", k.submit("job-snapshot", w.refs["a2"], events), replay=replay)
    assert code in str(caught.value) or attack == "reserved"
    assert calls(k) == [] if (k.root / "extraction").exists() else True


# ---------------------------------------------------------------- recovery / receipts ---------------------------------

def test_process_death_after_receipt_resumes_without_replay_file_or_new_call(world):
    k, w = world.kit, world
    replay = k.replay("r").extract(w.art["a1"], [w.mentions["a1"]]).write()
    request = k.submit("job-crash", w.refs["a1"])
    k.run("run", request, replay=replay, crash="receipt", expected=75)
    replay.unlink()
    resumed = k.run("resume", k.job_selector("job-crash"))
    assert resumed["state"] == "ready" and resumed["usage"]["replayCalls"] == 1 and len(resumed["calls"]) == 1
    assert k.run("resume", k.job_selector("job-crash")) == resumed
    assert k.run("inspect", k.job_selector("job-crash")) == resumed


def test_started_call_without_receipt_is_unknown_and_never_auto_resent(world):
    k, w = world.kit, world
    replay = k.replay("r").extract(w.art["a1"], [w.mentions["a1"]]).write()
    request = k.submit("job-unknown", w.refs["a1"])
    k.run("run", request, replay=replay, crash="unknown", expected=75)
    state = k.run("resume", k.job_selector("job-unknown"), replay=replay)
    assert state["state"] == "reconciling" and state["resumeMode"] == "reconcile_only" and state["failure"]["code"] == "replay_response_unknown"
    assert state["usage"]["replayCalls"] == 0 and state["usage"]["startedWithoutReceipt"] == 1 and state["eventCandidates"] == []
    assert k.run("resume", k.job_selector("job-unknown"), replay=replay) == state
    assert calls(k) == [("extract", "started", None)]
    cancelled = k.run("cancel", k.job_selector("job-unknown"), expected=2)
    assert cancelled["state"] == "cancelled" and cancelled["delivery"] == {"status": "withheld", "code": "job_cancelled"}


def test_stage_commit_boundaries_reuse_candidates_and_receipts_without_fixture(world):
    k, w = world.kit, world
    replay = same_of(w, "a2", "a1").write()
    request = k.submit("job-stage", w.refs["a2"], [event(w, "event-1", "a1")])
    k.run("run", request, replay=replay, crash="stage:extract", expected=75)
    k.run("run", request, replay=replay, crash="stage:compare", expected=75)
    replay.unlink()
    done = k.run("resume", k.job_selector("job-stage"))
    assert done["state"] == "ready" and done["usage"]["replayCalls"] == 2 and disposition(done)["status"] == "same-event-candidate"
    assert done["counts"]["comparisons"] == 1 and done["counts"]["eventCandidates"]["total"] == 1
    rows = sqlite3.connect(k.root / "extraction" / "extraction.sqlite3")
    try:
        assert rows.execute("SELECT COUNT(*) FROM event_candidates").fetchone() == (1,) and rows.execute("SELECT COUNT(*) FROM comparisons").fetchone() == (1,)
    finally:
        rows.close()


def test_receipts_and_candidates_are_immutable(world):
    k, w = world.kit, world
    k.job("run", k.submit("job-i", w.refs["a1"]), replay=k.replay("r").extract(w.art["a1"], [w.mentions["a1"]]).write())
    db = sqlite3.connect(k.root / "extraction" / "extraction.sqlite3")
    try:
        for sql in ("UPDATE calls SET response='{}'", "DELETE FROM calls", "UPDATE event_candidates SET state='x'", "DELETE FROM stages",
                    "UPDATE jobs SET request='{}'", "UPDATE meta SET value='x'"):
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(sql)
    finally:
        db.close()


def test_missing_authored_response_is_a_failure_not_a_fallback_or_call(world):
    k, w = world.kit, world
    empty = k.replay("empty").write()
    result = k.job("run", k.submit("job-missing", w.refs["a1"]), replay=empty)
    assert result["state"] == "stopped" and result["failure"]["code"] == "replay_response_missing" and result["usage"]["replayCalls"] == 0 and calls(k) == []
    with pytest.raises(ExtractionFailure, match="replay_provenance_conflict"):
        k.job("run", k.submit("job-prov", w.refs["a1"], source_kind="actual"), replay=empty)
    wrong = k.replay("wrong")
    wrong.doc["prompt_version"] = "other"
    with pytest.raises(ExtractionFailure, match="replay_prompt_version_conflict"):
        k.job("run", k.submit("job-prompt", w.refs["a1"]), replay=wrong.write())


# ---------------------------------------------------------------- rights ------------------------------------------

def test_revocation_withholds_candidates_and_stale_job_never_restores_rights(world):
    k, w = world.kit, world
    replay = same_of(w, "a2", "a1").write()
    request = k.submit("job-rights", w.refs["a2"], [event(w, "event-1", "a1")])
    ready = k.run("run", request, replay=replay)
    assert ready["state"] == "ready" and Q3B in json.dumps(ready, ensure_ascii=False)
    grant = k.registry["sources"][0]["grant"]
    grant["enabled"] = False
    k.save_registry()
    text = k.run("inspect", k.job_selector("job-rights"), expected=2, raw=True)
    withheld = json.loads(text)
    assert withheld["delivery"] == {"status": "withheld", "code": "source_unauthorized"} and "eventCandidates" not in withheld
    assert Q3B not in text and Q3 not in text and '"mention":' not in text and withheld["state"] == "ready"
    grant["enabled"] = True
    grant["revision"] = "rights-2"
    k.save_registry()
    changed = k.run("inspect", k.job_selector("job-rights"), expected=2)
    assert changed["delivery"]["code"] == "grant_revision_changed" and "eventCandidates" not in changed
    grant["revision"] = "rights-1"
    k.save_registry()
    assert k.run("inspect", k.job_selector("job-rights")) == ready


def test_resume_stops_on_revocation_without_calls_and_continues_after_current_rights_return(world):
    k, w = world.kit, world
    replay = same_of(w, "a2", "a1").write()
    request = k.submit("job-stop", w.refs["a2"], [event(w, "event-1", "a1")])
    k.run("run", request, replay=replay, crash="stage:extract", expected=75)
    k.registry["sources"][0]["grant"]["allowedOperations"] = ["read", "store"]
    k.save_registry()
    stopped = k.run("resume", k.job_selector("job-stop"), replay=replay, expected=2)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "source_unauthorized" and stopped["delivery"]["status"] == "withheld"
    assert stopped["usage"]["replayCalls"] == 1 and "eventCandidates" not in stopped
    k.registry["sources"][0]["grant"]["allowedOperations"] = ["read", "store", "quote-display"]
    k.save_registry()
    done = k.run("resume", k.job_selector("job-stop"), replay=replay)
    assert done["state"] == "ready" and done["usage"]["replayCalls"] == 2 and disposition(done)["status"] == "same-event-candidate"


def test_registry_removal_or_expiry_also_denies_every_bound_document(world):
    k, w = world.kit, world
    request = k.submit("job-gone", w.refs["a2"], [event(w, "event-1", "a1")])
    replay = same_of(w, "a2", "a1").write()
    assert k.run("run", request, replay=replay)["state"] == "ready"
    k.registry["sources"][0]["grant"]["expiresAt"] = "2000-01-01T00:00:00+00:00"
    k.save_registry()
    assert k.run("inspect", k.job_selector("job-gone"), expected=2)["delivery"]["code"] == "source_unauthorized"
    k.registry["sources"] = []
    k.save_registry()
    assert k.run("inspect", k.job_selector("job-gone"), expected=2)["delivery"]["code"] == "source_unauthorized"


# ---------------------------------------------------------------- state / dependencies --------------------------------

def test_dedicated_ledger_rejects_mixed_overlapping_unknown_roots_and_versions(world, tmp_path):
    k, w = world.kit, world
    k.job("run", k.submit("job-ns", w.refs["a1"]), replay=k.replay("r").extract(w.art["a1"], [w.mentions["a1"]]).write())
    assert sorted(p.name for p in (k.root / "extraction").iterdir() if not p.name.endswith(("-wal", "-shm"))) == ["extraction.lock", "extraction.sqlite3"]
    for name, files in (("ingestion", ()), ("app-state", ("app.sqlite3",)), ("s1-state", ("worker.sqlite3",)), ("mixed", ("extraction.sqlite3", "ingestion.sqlite3"))):
        folder = k.root / name
        folder.mkdir(parents=True, exist_ok=True)
        for file in files:
            (folder / file).write_bytes(b"untouched sentinel")
        with pytest.raises(ExtractionFailure, match="state_namespace_conflict"):
            Store(folder, k.root / "ingestion").close()
        assert all((folder / f).read_bytes() == b"untouched sentinel" for f in files)
    with pytest.raises(ExtractionFailure, match="state_namespace_conflict"):
        Store(k.root / "ingestion" / "inside", k.root / "ingestion")
    foreign = k.root / "foreign"
    foreign.mkdir()
    db = sqlite3.connect(foreign / "extraction.sqlite3")
    db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO meta VALUES('ledger','zoop-extraction-ledger-0')")
    db.commit()
    db.close()
    with pytest.raises(ExtractionFailure, match="ledger_version_unknown"):
        Store(foreign, k.root / "ingestion")
    held = Store(k.root / "extraction", k.root / "ingestion")
    try:
        with pytest.raises(ExtractionFailure, match="extraction_busy"):
            Store(k.root / "extraction", k.root / "ingestion")
    finally:
        held.close()


def test_extraction_never_writes_ingestion_state_and_leaks_no_private_internals(world):
    k, w = world.kit, world
    before = dump(k.root / "ingestion" / "ingestion.sqlite3")
    replay = same_of(w, "a2", "a1").write()
    text = k.run("run", k.submit("job-leak", w.refs["a2"], [event(w, "event-1", "a1")]), replay=replay, raw=True)
    result = json.loads(text)
    assert dump(k.root / "ingestion" / "ingestion.sqlite3") == before and result["state"] == "ready"
    assert str(k.root) not in text and str(replay) not in text and "https://example.invalid" not in text
    for forbidden in ('"response"', '"text":', "sourceText", "registry", "evidence\":[\"operator"):
        assert forbidden not in text
    assert all(len(c["responseDigest"]) == 64 for c in result["calls"]) and set(result["calls"][0]) == {"stage", "state", "requestDigest", "fixtureHash", "responseDigest", "verdict"}


def test_cancel_fences_a_stopped_job_and_resume_cannot_revive_it(world):
    k, w = world.kit, world
    replay = k.replay("r").extract(w.art["a1"], [w.mentions["a1"]]).write()
    request = k.submit("job-cancel", w.refs["a1"], topic=True)
    stopped = k.job("run", request, replay=replay)
    assert stopped["failure"]["code"] == "topic_replay_required"
    cancelled = k.job("cancel", k.job_selector("job-cancel"))
    assert cancelled["state"] == "cancelled" and cancelled["resumeMode"] == "none" and "eventCandidates" not in cancelled
    assert k.job("resume", k.job_selector("job-cancel"), replay=replay)["state"] == "cancelled"
    assert k.job("cancel", k.job_selector("job-cancel"))["state"] == "cancelled"


def test_no_database_pipeline_graph_or_network_modules_are_loaded(world):
    import subprocess
    import sys
    code = ("import sys\nfrom zoop_ai_pipeline import extraction, extraction_cli\nprint([m for m in sys.modules if m.startswith(('investmate.storage', 'investmate.pipeline', 'investmate.graph', 'psycopg', 'neo4j', 'zoop_bff', 'zoop_ai.'))] + (['zoop_ai'] if 'zoop_ai' in sys.modules else []))")
    child = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, cwd=world.kit.root, env={"PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"), "PATH": "/usr/bin:/bin"})
    assert child.returncode == 0 and child.stdout.strip() == "[]", child.stderr
    assert PROMPT


def test_app_and_worker_state_environment_roots_are_never_adopted(world, monkeypatch, tmp_path):
    for name in ("ZOOP_STATE_DIR", "ZOOP_AI_WORKER_STATE_DIR"):
        shared = tmp_path / name.lower()
        monkeypatch.setenv(name, str(shared))
        for candidate in (shared, shared / "extraction"):
            with pytest.raises(ExtractionFailure, match="state_namespace_conflict"):
                Store(candidate, world.kit.root / "ingestion")
        monkeypatch.delenv(name)


# ---------------------------------------------------------------- review regressions ---------------------------------

def test_duplicate_valid_extract_record_is_a_fixture_failure_never_an_accepted_receipt(world):
    k, w = world.kit, world
    duplicated = k.replay("dup").extract(w.art["a1"], [w.mentions["a1"]]).extract(w.art["a1"], [w.mentions["a1"]]).write()
    stopped = k.job("run", k.submit("job-dup", w.refs["a1"]), replay=duplicated)
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "replay_fixture_invalid" and calls(k) == []
    # Without a valid fixture nothing was received that a later no-fixture resume could sanitize into ready.
    again = k.job("resume", k.job_selector("job-dup"))
    assert again["state"] == "stopped" and again["failure"]["code"] == "replay_fixture_required" and calls(k) == [] and again["eventCandidates"] == []


def test_snapshot_member_evidence_must_be_exact_mapped_runs_and_citable(world):
    k, w = world.kit, world
    separated = k.evidence(w.art["a1"], SEPARATED)
    assert w.art["a1"].body[separated["start"]:separated["end"]] == SEPARATED  # PoC Evidence.matches accepts it
    member = k.mention(w.art["a1"], "m-sep", [separated])
    replay = k.replay("r").extract(w.art["a2"], [w.mentions["a2"]]).write()
    with pytest.raises(ExtractionFailure, match="snapshot_member_unmapped"):
        k.job("run", k.submit("job-member", w.refs["a2"], [k.event("event-1", [(w.refs["a1"], member)])]), replay=replay)
    assert [row for row in calls(k)] == []
    # A comparison that cites the separator span in a member document is also never SAME evidence.
    clean = w.mentions["a1"]
    compare = same_of(w, "a2", "a1", evidence=[k.evidence(w.art["a2"], Q3B), separated], name="sep-compare")
    held = k.job("run", k.submit("job-sep-compare", w.refs["a2"], [event(w, "event-1", "a1")]), replay=compare.write())
    effective = held["eventCandidates"][0]["comparisons"][0]["effective"]
    assert effective["relation"] == "HOLD" and effective["rule"] == "raw_locator_mismatch" and clean


def test_ingestion_read_is_actually_read_only_with_explicit_shared_lock_and_no_recovery_writes(world):
    import os
    import stat
    from zoop_ai_pipeline.ingestion import Store as IngestionStore
    from zoop_ai_pipeline.ingestion_contracts import IngestionFailure
    k, w = world.kit, world
    root = k.root / "ingestion"

    def state():
        return {p.name: (stat.S_IMODE(p.stat().st_mode), p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_uid, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(root.iterdir())} | {
            ".": (stat.S_IMODE(root.stat().st_mode), root.stat().st_mtime_ns)}

    # Deliberately unusual owner-readable modes: any chmod/ownership repair, create or write would be visible.
    os.chmod(root, 0o750)
    os.chmod(root / "ingestion.lock", 0o640)
    os.chmod(root / "ingestion.sqlite3", 0o440)
    before = state()
    exported = k.export(w.refs["a1"])
    replay = same_of(w, "a2", "a1").write()
    result = k.job("run", k.submit("job-ro", w.refs["a2"], [event(w, "event-1", "a1")]), replay=replay)
    assert exported["observation"]["documentId"] == w.refs["a1"]["documentId"] and result["state"] == "ready"
    assert state() == before and sorted(before) == [".", "ingestion.lock", "ingestion.sqlite3"]
    reader = IngestionStore(root, existing=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader.db.execute("INSERT INTO blobs VALUES('x', x'00')")
        with pytest.raises(sqlite3.OperationalError):
            reader.db.execute("CREATE TABLE intruder(x)")
        IngestionStore(root, existing=True).close()  # shared readers coexist
        with pytest.raises(IngestionFailure, match="ingestion_busy"):
            IngestionStore(root)  # a writer cannot start while a reader is active
    finally:
        reader.close()
    os.chmod(root / "ingestion.sqlite3", 0o600)
    os.chmod(root / "ingestion.lock", 0o600)
    os.chmod(root, 0o700)
    writer = IngestionStore(root)
    try:
        with pytest.raises(IngestionFailure, match="ingestion_busy"):
            IngestionStore(root, existing=True)
    finally:
        writer.close()
    with pytest.raises(IngestionFailure, match="ingestion_state_missing"):
        IngestionStore(k.root / "not-created", existing=True)
    assert not (k.root / "not-created").exists()


def test_hot_ingestion_wal_requires_a_writer_recovery_instead_of_being_ignored_or_written_by_a_reader(world):
    k, w = world.kit, world
    manifest = k.manifest("hot", [[k.item("hot", "supplier-hot", "https://example.invalid/hot", ref="hot")]], bodies={"hot": page(Q3, "다른 문장입니다.")})
    request = k.request(manifest, "round-hot", k.rounds)
    k.cli("run", request, state="ingestion", manifest=manifest, crash="raw", expected=75)
    assert (k.root / "ingestion" / "ingestion.sqlite3-wal").stat().st_size > 0
    before = sorted(p.name for p in (k.root / "ingestion").iterdir())
    with pytest.raises(ExtractionFailure, match="ingestion_recovery_required"):
        k.job("run", k.submit("job-hot", w.refs["a1"]), replay=k.replay("r").extract(w.art["a1"], [w.mentions["a1"]]).write())
    assert sorted(p.name for p in (k.root / "ingestion").iterdir()) == before
    recovered = k.cli("resume", k.selector("round-hot"), state="ingestion")
    assert recovered["state"] == "complete"
    ok = k.job("run", k.submit("job-hot", w.refs["a1"]), replay=k.replay("r2").extract(w.art["a1"], [w.mentions["a1"]]).write())
    assert ok["state"] == "ready"


def test_downstream_export_seam_is_read_only_current_and_refuses_unfinished_or_revoked_jobs(world):
    import os
    import stat
    from zoop_ai_pipeline.extraction import Extractor, Sources
    from zoop_ai_pipeline.ingestion_contracts import Authority
    k, w = world.kit, world
    done = k.job("run", k.submit("job-export", w.refs["a2"], [event(w, "event-1", "a1")]), replay=same_of(w, "a2", "a1").write())
    pending = k.job("run", k.submit("job-export-pending", w.refs["b"], [event(w, "event-1", "a1")], topic=True),
                    replay=k.replay("r-pending").extract(w.art["b"], [w.mentions["b"]]).compare(w.mentions["b"], "event-1", [(w.refs["a1"], w.art["a1"], w.mentions["a1"])],
                                                                                               w.art["b"], "DIFFERENT", "다른 사건", []).write())
    root = k.root / "extraction"

    def state():
        return {p.name: (stat.S_IMODE(p.stat().st_mode), p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(root.iterdir())} | {
            ".": (stat.S_IMODE(root.stat().st_mode), root.stat().st_mtime_ns)}

    os.chmod(root / "extraction.sqlite3", 0o440)
    before = state()

    def export(job):
        store = Store(root, k.root / "ingestion", existing=True)
        try:
            return Extractor(store, Sources(k.root / "ingestion", Authority(k.registry_path))).export(job)
        finally:
            store.close()

    request, result = export("job-export")
    assert request.job_id == "job-export" and result["inputDigest"] == done["inputDigest"] and result["delivery"]["status"] == "current" and sorted(before) == [".", "extraction.lock", "extraction.sqlite3"]
    with pytest.raises(ExtractionFailure, match="upstream_not_ready"):
        export("job-export-pending")
    with pytest.raises(ExtractionFailure, match="job_not_found"):
        export("missing")
    reader = Store(root, k.root / "ingestion", existing=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader.db.execute("DELETE FROM jobs")
        with pytest.raises(ExtractionFailure, match="extraction_busy"):
            Store(root, k.root / "ingestion")
    finally:
        reader.close()
    k.registry["sources"][0]["grant"]["enabled"] = False
    k.save_registry()
    with pytest.raises(ExtractionFailure, match="source_unauthorized"):
        export("job-export")
    k.registry["sources"][0]["grant"]["enabled"] = True
    k.save_registry()
    assert state() == before and pending["state"] == "stopped"
    os.chmod(root / "extraction.sqlite3", 0o600)
    with pytest.raises(ExtractionFailure, match="extraction_state_missing"):
        Store(k.root / "not-created", k.root / "ingestion", existing=True)
    assert not (k.root / "not-created").exists()
