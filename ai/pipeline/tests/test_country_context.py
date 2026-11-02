"""Fresh authored ingestion -> real S2 export -> real S3 context/precheck/verifier receipt; never a paid job replay."""
from __future__ import annotations

import json
import sqlite3

import pytest

from scripts.relation_smoke import SUP, build_world, co, converge, proposal, tree, world_cite
from zoop_ai_pipeline import relation_rules as rules
from zoop_ai_pipeline.extraction import Sources
from zoop_ai_pipeline.ingestion_contracts import Authority
from zoop_ai_pipeline.relation import Engine, Store
from zoop_ai_pipeline.relation_contracts import ExtractionFailure, Review, digest


CASES = [
    pytest.param(["Saudi Arabia"], ["SA"], ["SA"], [], "pass", id="saudi-name"),
    pytest.param(["Saudi Arabia", "북미", "유럽", "한국"], ["SA"], ["KR", "SA"], ["북미", "유럽"], "pass", id="observed-amd-context"),
    pytest.param(["한국"], ["KR"], ["KR"], [], "pass", id="korean-name"),
    pytest.param(["  sAuDi   aRaBiA\t", "사우디아라비아", "sa"], ["SA"], ["SA"], [], "pass", id="saudi-alias-case-space"),
    pytest.param(["대한민국", " South   Korea ", "Republic of Korea", "kr"], ["KR"], ["KR"], [], "pass", id="korean-alias-case-space"),
    pytest.param(["미국", "United States of America", "US"], ["US"], ["US"], [], "pass", id="other-country-aliases"),
    pytest.param(["jp", "DE", "나이지리아", "NG"], ["DE", "JP", "NG"], ["DE", "JP", "NG"], ["나이지리아"], "pass", id="iso-code-with-unlisted-name"),
    pytest.param(["Saudi Arabia"], ["KR"], ["SA"], [], "conflict", id="real-country-mismatch"),
    pytest.param(["US"], ["KR", "US"], ["US"], [], "conflict", id="partial-country-mismatch"),
    pytest.param(["북미", "유럽"], ["SA"], [], ["북미", "유럽"], "unverified", id="regions-only"),
    pytest.param(["Korea", "Congo", "Georgia", "UK", "EU", "ZZ", "Saudi-Arabia"], ["KR"], [],
                 ["Korea", "Congo", "Georgia", "UK", "EU", "ZZ", "Saudi-Arabia"], "unverified", id="ambiguous-reserved-unlisted"),
    pytest.param(["한국", "유럽"], ["FR"], ["KR"], ["유럽"], "unverified", id="mixed-incomplete-context"),
    pytest.param([], ["KR"], [], [], "unverified", id="empty-source"),
    pytest.param(["유럽"], [], [], ["유럽"], "unknown", id="empty-declaration"),
    pytest.param([], [], [], [], "unknown", id="all-empty"),
]


@pytest.mark.parametrize("origin", ["event-candidate", "snapshot-member"])
@pytest.mark.parametrize("raw,declared,known,unresolved,check", CASES)
def test_country_context_from_real_s2_is_not_an_automatic_approval(tmp_path, origin, raw, declared, known, unresolved, check):
    w = build_world(tmp_path / "owned", tuple(raw) if origin == "event-candidate" else (),
                    snapshot_countries=tuple(raw) if origin == "snapshot-member" else ())
    upstream = {name: tree(w.kit.root / name) for name in ("ingestion", "extraction")}
    raw_digest = digest(w.s2)
    p = proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [world_cite(w, "main", SUP)], countries=declared)
    # A deterministic pass must still reach the independent verifier, whose insufficient/contradicted answer is not overridden.
    claim = "context" if declared else "type"
    out = converge(w, "country", [p], verify=lambda _: {claim: "insufficient"})
    r = out["relations"][0]
    assert r["precheck"]["state"] == ("hold" if check == "conflict" else "pending")
    assert r["context"]["check"] == check
    assert r["context"] == {"market": "unknown" if not declared else "domestic" if declared == ["KR"] else "international",
                             "check": check, "knownCountries": known, "normalizationVersion": "zoop-country-context-1",
                             "rawGeography": sorted(set(raw)), "unresolvedGeography": sorted(set(unresolved))}
    assert r["countries"] == sorted(declared) and r["approved"] is False
    assert r["eligibility"]["status"] == "hold"
    assert r["eligibility"]["reasons"] == ([{"code": "country_context_conflict"}] if check == "conflict"
                                            else [{"code": "claim_insufficient", "at": claim}])
    assert [c["stage"] for c in out["calls"]] == (["relation"] if check == "conflict" else ["relation", "verify-relation"])
    if check != "conflict":
        assert ("context" in [c["claimId"] for c in r["claims"]]) == bool(declared)
        assert r["facts"]["countries"] == sorted(declared)
        rejected = converge(w, "country-contradiction", [p], verify=lambda _: {claim: "contradicted"})
        assert rejected["relations"][0]["eligibility"]["status"] == "reject"
    assert {name: tree(w.kit.root / name) for name in upstream} == upstream
    assert digest(w.s2) == raw_digest
    stored_s2 = w.kit.job("inspect", w.kit.job_selector("s2-job"))
    assert stored_s2["eventCandidates"][0]["mention"]["countries"] == (raw if origin == "event-candidate" else [])
    assert w.s2_request["snapshot"]["events"][0]["members"][0]["mention"]["countries"] == (raw if origin == "snapshot-member" else [])


def test_country_context_observed_shape_through_offline_cli(tmp_path):
    w = build_world(tmp_path / "owned", ("Saudi Arabia", "북미", "유럽", "한국"))
    out = converge(w, "country-cli", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [world_cite(w, "main", SUP)], countries=["SA"])],
                   verify=lambda _: {"context": "insufficient"}, process=True)
    assert out["state"] == "ready"
    r = out["relations"][0]
    assert r["precheck"] == {"state": "pending", "reasons": []}
    assert r["context"]["check"] == "pass"
    assert r["eligibility"]["reasons"] == [{"code": "claim_insufficient", "at": "context"}]
    assert [call["stage"] for call in out["calls"]] == ["relation", "verify-relation"]
    assert out["usage"]["providerCalls"] == out["usage"]["modelCalls"] == 0


@pytest.mark.parametrize("declared", [["Saudi Arabia"], ["한국"], ["sa"], ["USA"]])
def test_country_context_does_not_loosen_s3_producer_shape(declared):
    from zoop_ai_pipeline.relation_contracts import ReplyInvalid
    from scripts.relation_smoke import relation_reply

    with pytest.raises(ReplyInvalid, match="relation_reply_invalid"):
        rules.parse_relations(relation_reply([proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [], countries=declared)]))


def test_country_context_legacy_binding_withholds_without_rewriting_receipts(tmp_path):
    w = build_world(tmp_path / "owned", ("Saudi Arabia",))
    out = converge(w, "current", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [world_cite(w, "main", SUP)], countries=["SA"])],
                   verify=lambda _: {"context": "insufficient"})
    # Deliberately impossible mixed tuple: policy-1 could not consume current S2 adapter-3. Preserve copied receipts as a negative fixture.
    path = w.kit.root / "relation" / "relation.sqlite3"
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute("SELECT * FROM jobs WHERE job_id='current'").fetchone())
        binding, request = json.loads(row["binding"]), json.loads(row["request"])
        binding["versions"]["policy"] = "zoop-relation-policy-1"
        binding["versions"].pop("countryContext", None)
        request["jobId"] = "historical"
        row.update(job_id="historical", input_digest=digest(request), request=json.dumps(request), binding=json.dumps(binding))
        db.execute(f"INSERT INTO jobs({','.join(row)}) VALUES({','.join('?' for _ in row)})", tuple(row.values()))
        for table in ("relation_candidates", "relation_events"):
            for child in db.execute(f"SELECT * FROM {table} WHERE job_id='current'").fetchall():
                child = dict(child)
                child["job_id"] = "historical"
                db.execute(f"INSERT INTO {table}({','.join(child)}) VALUES({','.join('?' for _ in child)})", tuple(child.values()))
        for call in db.execute("SELECT * FROM calls WHERE job_id='current'").fetchall():
            call = dict(call)
            call.update(job_id="historical", attempt_id="historical-" + call["attempt_id"])
            db.execute(f"INSERT INTO calls({','.join(call)}) VALUES({','.join('?' for _ in call)})", tuple(call.values()))
    db.close()
    before = tree(w.kit.root / "relation")
    store = Store(w.kit.root / "relation", w.kit.root / "extraction", w.kit.root / "ingestion", existing=True)
    try:
        engine = Engine(store, Sources(w.kit.root / "ingestion", Authority(w.kit.registry_path)), w.kit.root / "extraction", w.kit.root / "ingestion")
        historical = engine.inspect("historical")
        assert historical["delivery"] == {"status": "withheld", "code": "job_binding_changed"}
        assert historical["calls"] == out["calls"] and "relations" not in historical
        held = out["relations"][0]
        with pytest.raises(ExtractionFailure, match="analysis_contract_changed"):
            engine.review(Review.model_validate({**w.kit.rsel("historical"), "relationCandidateId": held["relationCandidateId"],
                "expectedRevision": held["eligibility"]["revision"], "decision": "allow", "reviewer": "authored", "note": "must not reinterpret"}))
    finally:
        store.close()
    assert tree(w.kit.root / "relation") == before
