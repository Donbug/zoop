#!/usr/bin/env python3
"""Actual ingestion + S2 + S3 world -> installed `zoop-ai-handoff` subprocesses (no Neo4j: the handoff does not read the private graph).

    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_handoff_smoke.py [--write-fixture DIR]
    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_handoff_smoke.py --write-package DIR        # retained operator package (see below)
    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_handoff_smoke.py --verify-package DIR [--export-out FILE]

Two S2 jobs (two events, one frozen snapshot event with two documents) and two S3 jobs are authored replay: no model, no provider, no original PoC state,
no network (every CLI subprocess runs under a socket audit hook). Expectations are written by hand from the authored world, never derived from the
planner under test. `--write-fixture DIR` additionally writes the valid export envelope and negative fixtures the backend import can be tested with.
Without `--write-package` fresh owned state is always removed; the source ledgers must be byte-identical after every command.

`--write-package DIR` builds the same authored world (synthetic company ids SYNTH:000001/SYNTH:000002) directly in the NEW directory DIR, freezes ONE handoff
through the installed CLI, checks the export against the hand-written expectation and KEEPS the world: source ledgers, the operator files, the pins and the
inputs of the document import and of the graph handoff import. DIR must not exist (nothing is ever overwritten; a failed build removes what it created) and its
parent must be a real, non-symlinked directory. The package is bound to the absolute path it was built at (the S2-1 ledger pins `inputRoot` of `sources.json`):
to deliver it elsewhere, run `--write-package` there. `--verify-package DIR` re-exports it in fresh processes through the installed `zoop-ai-handoff` and
`zoop-ai-ingest` and compares the result with the pins in PACKAGE.json; `--export-out FILE` also stores the current export envelope in a new file.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.ingestion_smoke import json_bytes, ownership_env  # noqa: E402
from scripts.extraction_smoke import page  # noqa: E402
from scripts.relation_smoke import RelKit, SUP, INV, co, converge, ev, find, proposal, tree, world_cite  # noqa: E402
from zoop_ai_pipeline.graph_projection import review_state  # noqa: E402
from zoop_ai_pipeline.handoff_contracts import POLICY, app_evidence_id  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import canonical, digest  # noqa: E402

CUSTOM = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
EVT_A = "합성기업은 2026년 3분기 공급 계약을 발표했다."
GEO_A = "계약은 국내 시장 중심이다."
EVT_A2 = "합성기업이 3분기 공급 계약 체결을 공개했다."
QB = "합성기업은 4분기 신규 공장 착공을 알렸다."
GEO_B = "착공은 미국에서 이뤄진다."
QB3 = "합성투자는 해외 합작 공장 지분을 인수했다."


def korean_date(day: str) -> str:
    year, month, date = (int(part) for part in day.split("-"))
    return f"{year}년 {month}월 {date}일"


def validity_sentence(valid_from: str | None, valid_until: str | None) -> str | None:
    """The one sentence of document b that proves a validity window. It states the end as the LAST VALID DAY ("through D"; FS042: `validFrom <= time <=
    validUntil`), so the S3 value `validUntil` is exactly the day the source names: nothing is shifted by a day and no midnight is added."""
    if valid_from and valid_until:
        return f"공급 계약은 {korean_date(valid_from)}부터 {korean_date(valid_until)}까지 유효하다."
    if valid_from:
        return f"공급 계약은 {korean_date(valid_from)}부터 유효하며 종료일은 밝혀지지 않았다."
    if valid_until:
        return f"공급 계약은 {korean_date(valid_until)}까지 유효하며 시작일은 밝혀지지 않았다."
    return None


VALID2 = validity_sentence("2026-01-01", "2026-12-31")
EVT_IN = "합성기업은 2026년 10월 신규 투자 계획을 밝혔다."
EVT_Y = "합성기업은 2026년 9월 해외 공급 계약을 체결했다."
GEO_Y = "계약은 국내 시장 중심이다."
# A real reviewer name and review note live ONLY in the S3 relation ledger (see the unit tests' review helper). They are unique synthetic markers so that the
# privacy check cannot collide with legitimate public vocabulary such as the `operator-asserted` status or the operator-asserted reviewer id below.
PRIVATE_REVIEWER = "private-reviewer-zq7x"
PRIVATE_NOTE = "private-review-note-zq7x"
PRIVATE = (SUP, INV, EVT_A, GEO_A, EVT_A2, QB, GEO_B, QB3, PRIVATE_REVIEWER, PRIVATE_NOTE)     # source sentences / S3 review text that must never appear in any output
REVIEWER = "reviewer-a"                                                                       # the operator's PUBLIC attestation reviewer id (intended export)


# ---------------------------------------------------------------- the authored world (also used by the unit tests) -----------------

def build_world(root: Path, *, collide: bool = False, a2_differs: bool = True, a2_countries: tuple = ("KR",), dated: bool = False,
                valid_from: str | None = "2026-01-01", valid_until: str | None = "2026-12-31", event_time: str | None = "2026-09-30") -> SimpleNamespace:
    """The authored world. Variants (each is a REAL ingestion + S2 + S3 world, used by the integrity regressions):
    collide: the two documents of snapshot event-a use the SAME local mention id (S2 scopes member identity by documentVersion + mentionId, so this is legal);
    a2_differs: the second member's title differs (a metadata conflict unless the operator picks a representative); a2_countries: its country field;
    dated: rel-b also holds an eligible SUPPLIES basis whose validity dates are proven ONLY by a sentence in another document (b); `valid_from`/`valid_until`
    (None = unknown, no sentence, no citation) are that basis's validity and `event_time` is the supply issue's event time in BOTH of its documents."""
    kit = RelKit(root)
    valid_text = validity_sentence(valid_from, valid_until) if dated else None
    d1, d2, d3 = kit.ingest("docs", [{"supplier": "supplier-a", "html": page(SUP, INV, EVT_A, GEO_A)},
                                     {"supplier": "supplier-a2", "html": page(EVT_A2)},
                                     {"supplier": "supplier-b", "html": page(QB, GEO_B, QB3, *((valid_text,) if valid_text else ())), "published": None}])
    refs = {"a": d1, "a2": d2, "b": d3}
    art = {name: kit.article(ref) for name, ref in refs.items()}
    m_a = {**kit.mention(art["a"], "m-a", [kit.evidence(art["a"], EVT_A)], event_time=event_time), "countries": ["KR"]}
    second = {} if a2_differs else {"title": "합성 공급 계약"}
    m_a2 = {**kit.mention(art["a2"], "m-a" if collide else "m-a2", [kit.evidence(art["a2"], EVT_A2)], event_time=event_time,
                          **({"title": "합성 공급 계약 체결 공개"} | second)), "countries": list(a2_countries)}
    m_b = {**kit.mention(art["b"], "m-b", [kit.evidence(art["b"], QB)], period="2026Q4", title="합성 공장 착공", action="공장 착공 알림", event_time="2026-11-15"),
           "countries": ["US"]}
    m_b3 = {**kit.mention(art["b"], "m-b3", [kit.evidence(art["b"], QB3)], period="2026Q4", title="해외 합작 공장 지분 인수", action="지분 인수"), "countries": []}
    s2a = kit.job("run", kit.submit("s2-a", d1), replay=kit.replay("s2a").extract(art["a"], [m_a]).write())
    assert s2a["state"] == "ready", s2a.get("failure")
    event_a = kit.event("event-a", [(d1, m_a), (d2, m_a2)])
    members = [(d1, art["a"], m_a), (d2, art["a2"], m_a2)]
    replay_b = (kit.replay("s2b").extract(art["b"], [m_b, m_b3])
                .compare(m_b, "event-a", members, art["b"], "FOLLOWS", "후속 착공", [kit.evidence(art["b"], QB), kit.evidence(art["a"], EVT_A)])
                .compare(m_b3, "event-a", members, art["b"], "DIFFERENT", "다른 사건", []).write())
    s2b = kit.job("run", kit.submit("s2-b", d3, [event_a]), replay=replay_b)
    assert s2b["state"] == "ready", s2b.get("failure")
    evc = {"a": s2a["eventCandidates"][0]["eventCandidateId"],
           "b": next(c["eventCandidateId"] for c in s2b["eventCandidates"] if c["localMentionId"] == "m-b"),
           "b3": next(c["eventCandidateId"] for c in s2b["eventCandidates"] if c["localMentionId"] == "m-b3")}
    world = SimpleNamespace(kit=kit, refs=refs, art=art, s2={"a": s2a, "b": s2b}, evc=evc, root=root, collide=collide)
    wa, wb = (SimpleNamespace(kit=kit, refs=refs, art=art, s2=s2) for s2 in (s2a, s2b))
    cite = lambda w, name, text: world_cite(w, name, text)  # noqa: E731
    jobs = {
        "rel-a": converge(wa, "rel-a", [
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(evc["a"]), [cite(wa, "a", EVT_A)]),
            proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [cite(wa, "a", SUP)], product="배터리 부품"),
            proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [cite(wa, "a", INV)]),
            proposal("SHARES_ISSUE", co("SYNTH-1"), co("SYNTH-2"), [cite(wa, "a", SUP)])]),
        "rel-b": converge(wb, "rel-b", [
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev("event-a"), [cite(wb, "a2", EVT_A2)]),
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(evc["b"]), [cite(wb, "b", QB)]),
            proposal("PARTICIPATES_IN", co("SYNTH-2"), ev(evc["b"]), [cite(wb, "b", QB)]),
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(evc["b3"]), [cite(wb, "b", QB3)]),
            *([proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [cite(wb, "a", SUP)], product="배터리 부품",
                        validity={"from": valid_from, "until": valid_until, "citations": [cite(wb, "b", valid_text)] if valid_text else []})] if dated else [])])}
    for name, out in jobs.items():
        assert out["state"] == "ready", (name, out.get("failure"))
    world.jobs, world.dated, world.valid_text, world.event_time = jobs, dated, valid_text, event_time
    return world


# ---------------------------------------------------------------- operator documents ---------------------------------------------

def upstream(world, name: str) -> dict:
    return {"jobId": world.s2[name]["jobId"], "inputDigest": world.s2[name]["inputDigest"]}


def canonical_doc(world) -> dict:
    mapping = [("a", "company", "SYNTH-1", "co:synth-1"), ("a", "company", "SYNTH-3", "co:synth-3"), ("a", "company", "SYNTH-4", "co:synth-4"),
               ("a", "event", world.evc["a"], "issue:supply"),
               ("b", "company", "SYNTH-1", "co:synth-1"), ("b", "company", "SYNTH-2", "co:synth-2"), ("b", "company", "SYNTH-3", "co:synth-3"),
               ("b", "event", "event-a", "issue:supply"), ("b", "event", world.evc["b"], "issue:factory"), ("b", "event", world.evc["b3"], "issue:overseas")]
    return {"schemaVersion": "zoop-graph-canonical-1",
            "entries": [{"upstream": upstream(world, s2), "kind": kind, "ref": ref, "canonicalId": cid, "decisionRef": f"canon-2026-10-16:{kind}"} for s2, kind, ref, cid in mapping]}


def span(world, name: str, quote: str) -> dict:
    text = world.art[name].body
    start = text.index(quote)
    ref = world.refs[name]
    return {"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "start": start, "end": start + len(quote),
            "quoteSha256": digest_text(quote)}


def digest_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_events(world) -> list:
    """Three exact source members; local mention IDs are scoped by document and observation."""
    ua, ub = upstream(world, "a"), upstream(world, "b")
    observation = lambda name: {k: world.refs[name][k] for k in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")}  # noqa: E731
    def member(name, up, kind, ref, mention_id):
        doc = world.refs[name]
        return {"upstream": up, "kind": kind, "ref": ref, "mentionId": mention_id,
                "documentId": doc["documentId"], "documentVersion": doc["documentVersion"], "observation": observation(name)}
    return sorted([member("a", ua, "event-candidate", world.evc["a"], "m-a"),
                   member("a", ub, "snapshot-event", "event-a", "m-a"),
                   member("a2", ub, "snapshot-event", "event-a", "m-a" if world.collide else "m-a2")], key=canonical)


def structural_binding(world, *, decision_version: str = "v1", job: str = "rel-a") -> str:
    """Hand-written copy of the attestation preimage the operator reviewed (issue source events, basis relation with its S3 revision, decision version)."""
    r = find(world.jobs[job], "SUPPLIES", "SYNTH-3", "SYNTH-1")
    return digest({"policy": POLICY, "issue": "issue:supply", "company": "co:synth-3", "decisionVersion": decision_version, "eventTime": getattr(world, "event_time", "2026-09-30"),
                   "geography": "domestic", "sourceEvents": source_events(world),
                   "basis": [{"jobId": job, "relationCandidateId": r["relationCandidateId"], "relationKey": r["relationKey"], "type": "SUPPLIES",
                              "revision": r["eligibility"]["revision"]}]})


def decisions_doc(world) -> dict:
    job = "rel-b" if getattr(world, "dated", False) else "rel-a"        # the dated world's structural basis is the SUPPLIES relation whose validity lives in document b
    r = find(world.jobs[job], "SUPPLIES", "SYNTH-3", "SYNTH-1")
    comparison = next(c for c in next(x for x in world.s2["b"]["eventCandidates"] if x["eventCandidateId"] == world.evc["b"])["comparisons"]
                      if c["targetEventId"] == "event-a")
    return {"schemaVersion": "zoop-public-decisions-1", "policyVersion": POLICY,
            "companies": [{"canonicalId": "co:synth-1", "publicId": "KRX:005930", "label": "합성기업", "decisionRef": "catalog-2026-10-16:1"},
                          {"canonicalId": "co:synth-3", "publicId": "KRX:000660", "label": "합성부품", "decisionRef": "catalog-2026-10-16:3"}],
            "issues": [{"canonicalId": "issue:supply", "publicId": "issue:supply-2026q3", "decisionRef": "issue-2026-10-16:supply",
                        "geography": {"classification": "domestic", "countries": ["KR"], "evidence": [span(world, "a", GEO_A)], "decisionRef": "geo-2026-10-16:supply",
                                      "decisionVersion": "g1"},
                        "representative": {"upstream": upstream(world, "a"), "kind": "event-candidate", "ref": world.evc["a"], "mentionId": "m-a",
                                           "documentId": world.refs["a"]["documentId"], "documentVersion": world.refs["a"]["documentVersion"],
                                           "observation": {k: world.refs["a"][k] for k in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")}}},
                       {"canonicalId": "issue:factory", "publicId": "issue:factory-2026q4", "decisionRef": "issue-2026-10-16:factory",
                        "geography": {"classification": "international", "countries": ["US"], "evidence": [span(world, "b", GEO_B)],
                                      "decisionRef": "geo-2026-10-16:factory", "decisionVersion": "g1"}, "representative": None},
                       {"canonicalId": "issue:overseas", "publicId": "issue:overseas-2026q4", "decisionRef": "issue-2026-10-16:overseas",
                        "geography": {"classification": "domestic", "countries": ["KR"], "evidence": [span(world, "b", QB3)],
                                      "decisionRef": "geo-2026-10-16:overseas", "decisionVersion": "g1"}, "representative": None}],
            "structural": [{"issue": "issue:supply", "company": "co:synth-3", "basis": [{"jobId": job, "relationCandidateId": r["relationCandidateId"]}],
                            "applicability": {"status": "operator-asserted", "reviewer": REVIEWER, "decisionRef": "applic-2026-10-16:1", "decisionVersion": "v1",
                                              "bindingDigest": structural_binding(world, job=job)}}],
            "follows": [{"from": "issue:factory", "to": "issue:supply", "decisionRef": "seq-2026-10-16:1", "decisionVersion": "s1",
                         "source": {"upstream": upstream(world, "b"), "eventCandidateId": world.evc["b"], "targetEventId": "event-a",
                                    "groupDigest": comparison["groupDigest"]}}]}


def bindings_doc(world) -> dict:
    items = []
    for name, ref in world.refs.items():
        items.append({"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "articleId": ref["documentId"], "articleVersion": ref["documentVersion"],
                      "textSha256": digest_text(world.art[name].body), "offsetUnit": "unicode_code_point"})
    return {"schemaVersion": "zoop-app-document-bindings-1", "bindings": sorted(items, key=lambda b: b["documentId"])}


def build_observation_world(root: Path, *, same_url: bool = False) -> SimpleNamespace:
    """One supplier document observed twice in separate rounds, with matching or conflicting URLs; the incoming event is a separate document."""
    kit = RelKit(root)
    (d_in,) = kit.ingest("incoming", [{"supplier": "supplier-in", "html": page(EVT_IN)}])
    (y1,) = kit.ingest("obs1", [{"supplier": "supplier-y", "html": page(EVT_Y, GEO_Y), "url": "https://example.invalid/y/one"}])
    (y2,) = kit.ingest("obs2", [{"supplier": "supplier-y", "html": page(EVT_Y, GEO_Y),
                                   "url": "https://example.invalid/y/one" if same_url else "https://example.invalid/y/two"}])
    assert (y1["documentId"], y1["documentVersion"]) == (y2["documentId"], y2["documentVersion"]) and (y1["roundId"], y1["ordinal"]) != (y2["roundId"], y2["ordinal"]), (y1, y2)
    refs = {"in": d_in, "y1": y1, "y2": y2}
    art = {name: kit.article(ref) for name, ref in refs.items()}
    m_in = {**kit.mention(art["in"], "m-in", [kit.evidence(art["in"], EVT_IN)], event_time="2026-10-01"), "countries": ["KR"]}
    m_y1 = {**kit.mention(art["y1"], "m-y1", [kit.evidence(art["y1"], EVT_Y)], event_time="2026-09-30"), "countries": ["KR"]}
    m_y2 = {**kit.mention(art["y2"], "m-y2", [kit.evidence(art["y2"], EVT_Y)], event_time="2026-09-30"), "countries": ["KR"]}
    event_y = kit.event("event-y", [(y1, m_y1), (y2, m_y2)])
    replay = (kit.replay("s2obs").extract(art["in"], [m_in])
              .compare(m_in, "event-y", [(y1, art["y1"], m_y1), (y2, art["y2"], m_y2)], art["in"], "DIFFERENT", "다른 사건", []).write())
    s2 = kit.job("run", kit.submit("s2-obs", d_in, [event_y]), replay=replay)
    assert s2["state"] == "ready", s2.get("failure")
    world = SimpleNamespace(kit=kit, refs=refs, art=art, s2={"obs": s2}, root=root, dated=False)
    w = SimpleNamespace(kit=kit, refs=refs, art=art, s2=s2)
    out = converge(w, "rel-obs", [proposal("PARTICIPATES_IN", co("SYNTH-1"), ev("event-y"), [world_cite(w, "y1", EVT_Y)])])
    assert out["state"] == "ready", out.get("failure")
    world.jobs = {"rel-obs": out}
    return world


def observation_docs(world) -> dict:
    """Operator documents of the double-observation world: one public issue (domestic by verdict), one company, one binding for the single document version."""
    up = upstream(world, "obs")
    ref = world.refs["y1"]
    return {"canonical": {"schemaVersion": "zoop-graph-canonical-1", "entries": [
                {"upstream": up, "kind": "company", "ref": "SYNTH-1", "canonicalId": "co:synth-1", "decisionRef": "canon-2026-10-16:company"},
                {"upstream": up, "kind": "event", "ref": "event-y", "canonicalId": "issue:y", "decisionRef": "canon-2026-10-16:event"}]},
            "decisions": {"schemaVersion": "zoop-public-decisions-1", "policyVersion": POLICY,
                          "companies": [{"canonicalId": "co:synth-1", "publicId": "KRX:005930", "label": "합성기업", "decisionRef": "catalog-2026-10-16:1"}],
                          "issues": [{"canonicalId": "issue:y", "publicId": "issue:y-2026q3", "decisionRef": "issue-2026-10-16:y",
                                      "geography": {"classification": "domestic", "countries": ["KR"], "evidence": [span(world, "y1", GEO_Y)],
                                                    "decisionRef": "geo-2026-10-16:y", "decisionVersion": "g1"}, "representative": None}],
                          "structural": [], "follows": []},
            "bindings": {"schemaVersion": "zoop-app-document-bindings-1", "bindings": [
                {"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "articleId": ref["documentId"], "articleVersion": ref["documentVersion"],
                 "textSha256": digest_text(world.art["y1"].body), "offsetUnit": "unicode_code_point"}]}}


def manifest_doc(world, handoff_id: str, files: dict, *, source_kind: str = "synthetic") -> dict:
    sources = []
    for job, out in sorted(world.jobs.items()):
        sources.append({"relation": {"jobId": job, "inputDigest": out["inputDigest"]}, "upstream": dict(out["binding"]["upstream"]),
                        "reviewDigest": digest(review_state(out))})
    return {"schemaVersion": "zoop-ai-handoff-1", "handoffId": handoff_id, "sourceKind": source_kind, "policyVersion": POLICY, "sources": sources, "files": files}


def file_hashes(root: Path) -> dict:
    import hashlib
    return {name: hashlib.sha256((root / f"{name}.json").read_bytes()).hexdigest() for name in ("canonical", "decisions", "bindings")}


def write_operator(world, *, canonical_document=None, decisions=None, bindings=None) -> None:
    for name, doc in (("canonical", canonical_document or canonical_doc(world)), ("decisions", decisions or decisions_doc(world)), ("bindings", bindings or bindings_doc(world))):
        (world.root / f"{name}.json").write_bytes(json_bytes(doc))


def evidence_id(world, name: str, quote: str) -> str:
    """Hand-written expectation of the proposed app evidence id for an authored span."""
    s = span(world, name, quote)
    return app_evidence_id(s["documentId"], s["documentVersion"], s["start"], s["end"])


def expected(world, public_ids: dict | None = None) -> dict:
    """Hand-written expectation of the full handoff over the authored world and operator documents above (`public_ids` maps the authored public company ids)."""
    pub = lambda company: (public_ids or {}).get(company, company)  # noqa: E731
    e = {"EVT_A": evidence_id(world, "a", EVT_A), "GEO_A": evidence_id(world, "a", GEO_A), "SUP": evidence_id(world, "a", SUP),
         "EVT_A2": evidence_id(world, "a2", EVT_A2), "QB": evidence_id(world, "b", QB), "GEO_B": evidence_id(world, "b", GEO_B)}
    return {
        "evidence": sorted(e.values()),
        "issues": {"issue:supply-2026q3": {"canonicalId": "issue:supply", "title": "합성 공급 계약", "eventTime": "2026-09-30", "timePrecision": "day",
                                           "geography": "domestic", "evidenceIds": sorted([e["EVT_A"], e["EVT_A2"], e["GEO_A"]])},
                   "issue:factory-2026q4": {"canonicalId": "issue:factory", "title": "합성 공장 착공", "eventTime": "2026-11-15", "timePrecision": "day",
                                            "geography": "international", "evidenceIds": sorted([e["QB"], e["GEO_B"]])}},
        "relations": {("INVOLVES", "issue:supply-2026q3", pub("KRX:005930")): sorted([e["EVT_A"], e["EVT_A2"]]),
                      ("INVOLVES", "issue:factory-2026q4", pub("KRX:005930")): [e["QB"]],
                      ("STRUCTURALLY_RELATED_TO", "issue:supply-2026q3", pub("KRX:000660")): sorted([e["EVT_A"], e["EVT_A2"]]),
                      ("FOLLOWS", "issue:factory-2026q4", "issue:supply-2026q3"): sorted([e["QB"], e["EVT_A"]])},
        "basisEvidence": [e["SUP"]],
        "exclusions": {"geography_unproven": 1, "company_unmapped": 1, "issue_not_public": 1},
        "counts": {"companies": 2, "issues": 2, "relations": {"INVOLVES": 2, "STRUCTURALLY_RELATED_TO": 1, "FOLLOWS": 1}, "evidence": 6, "articles": 3, "exclusions": 3}}


def check_export(world, out: dict, public_ids: dict | None = None) -> None:
    """The exported envelope equals the hand-written expectation exactly."""
    want, bundle = expected(world, public_ids), out["bundle"]
    assert out["delivery"]["status"] == "current" and out["publication"] == "not-published" and out["state"] == "ready", out["delivery"]
    assert [x["id"] for x in bundle["evidence"]] == want["evidence"], [x["id"] for x in bundle["evidence"]]
    assert {i["id"]: {"canonicalId": i["canonicalId"], "title": i["title"], "eventTime": i["eventTime"], "timePrecision": i["timePrecision"],
                      "geography": i["geography"]["value"], "evidenceIds": i["evidenceIds"]} for i in bundle["issues"]} == want["issues"]
    assert {(r["type"], r["source"], r["target"]): r["evidenceIds"] for r in bundle["relations"]} == want["relations"]
    structural = next(r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")
    assert [b["evidenceIds"] for b in structural["basis"]] == [want["basisEvidence"]] and structural["basis"][0]["relationType"] == "SUPPLIES"
    assert structural["provenance"]["origin"] == "manual-operator-review" and structural["provenance"]["s3SemanticValidation"] == "none"
    assert bundle["exclusions"]["counts"] == want["exclusions"] and bundle["counts"] == want["counts"], (bundle["exclusions"], bundle["counts"])
    assert bundle["provenance"] == {"declaredSourceKind": "synthetic", "observedSourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}
    assert bundle["readiness"] == {"app": "import-pending", "evidenceRegistration": "not-registered", "publicActivation": "none", "graphDb": "none"}
    assert [c["id"] for c in bundle["companies"]] == sorted((public_ids or {}).get(c, c) for c in ("KRX:000660", "KRX:005930"))
    assert [a["articleId"] for a in bundle["articles"]] == sorted(r["documentId"] for r in world.refs.values())
    manifest = out["manifest"]
    assert set(manifest) == {"schemaVersion", "handoffId", "sourceKind", "policyVersion", "sources", "files"} and set(manifest["files"]) == {"canonical", "decisions", "bindings"}
    assert digest(manifest) == bundle["manifestDigest"] == out["receipt"]["manifestDigest"]
    assert manifest["handoffId"] == bundle["handoffId"] and manifest["files"] == bundle["policy"]["files"]
    assert sorted(canonical(s) for s in manifest["sources"]) == sorted(
        canonical({"relation": s["relation"], "upstream": s["upstream"], "reviewDigest": s["reviewDigest"]}) for s in bundle["sources"])


# ---------------------------------------------------------------- operator harness (real subprocesses) ---------------------------

GUARD = ("import os, sys, runpy\n"
         "def _guard(event, args):\n"
         " if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.bind'}:\n"
         "  raise RuntimeError('network attempted')\n"
         "sys.addaudithook(_guard)\n"
         "from zoop_ai_pipeline.handoff import Handoff\n")
HOOKS = {"kill-after-reserve": "Handoff._after_reserve = lambda self: os._exit(9)\n",
         "kill-after-artifact": "Handoff._after_artifact = lambda self: os._exit(9)\n"}


class Operator:
    def __init__(self, world):
        self.world, self.root = world, world.root
        self.state = self.root / "handoff"
        self.outputs: list[str] = []

    def cli(self, command: str, request: dict, *, expected: int = 0, hook: str | None = None, state: Path | None = None):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM}
        program = GUARD + (HOOKS[hook] if hook else "") + "runpy.run_module('zoop_ai_pipeline.handoff_cli', run_name='__main__')\n"
        argv = [sys.executable, "-c", program, command, "--state-dir", str(state or self.state)]
        if command in {"freeze", "export"}:
            argv += ["--relation-state-dir", str(self.root / "relation"), "--extraction-state-dir", str(self.root / "extraction"),
                     "--ingestion-state-dir", str(self.root / "ingestion"), "--sources", str(self.world.kit.registry_path),
                     "--canonical", str(self.root / "canonical.json"), "--decisions", str(self.root / "decisions.json"), "--bindings", str(self.root / "bindings.json")]
        child = subprocess.run(argv, input=json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=300)
        text = child.stdout.decode()
        self.outputs.append(text)
        assert child.returncode == expected, (command, child.returncode, text[:2000], child.stderr.decode()[-2000:])
        assert expected == 9 or not child.stderr, child.stderr.decode()[-2000:]
        return json.loads(text) if text else None

    def sel(self, handoff_id: str) -> dict:
        return {"schemaVersion": "zoop-ai-handoff-1", "handoffId": handoff_id}


def validity_end_inclusive(root: Path) -> str:
    """FS042 `validFrom <= time <= validUntil` through the installed CLI: the supply issue's event time is 2026-09-30. A basis whose last valid day is BEFORE that
    day is excluded visibly; one whose last valid day IS that day, or later, is exported unchanged (`validUntil` verbatim, nothing shifted)."""
    for name, valid_until in (("end-before-event-day", "2026-09-29"), ("end-on-event-day", "2026-09-30"), ("end-after-event-day", "2026-10-01")):
        world = build_world(root.parent / f"validity-{name}", dated=True, valid_until=valid_until)
        write_operator(world)
        operator = Operator(world)
        operator.cli("freeze", manifest_doc(world, "validity-1", file_hashes(world.root)))
        out = operator.cli("export", operator.sel("validity-1"))
        assert out["delivery"]["status"] == "current", (name, out["delivery"])
        bundle = out["bundle"]
        structural = [r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO"]
        items = {(i["kind"], i["id"]): i["code"] for i in bundle["exclusions"]["items"]}
        if name == "end-before-event-day":
            assert not structural and items[("structural", "issue:supply>co:synth-3")] == "basis_validity_outside_event_time", (name, items)
        else:
            assert len(structural) == 1 and structural[0]["basis"][0]["validUntil"] == valid_until, (name, structural)
            assert ("structural", "issue:supply>co:synth-3") not in items, (name, items)
    return "FS042 end-inclusive validity via CLI: a basis whose last valid day is before the event day is excluded (basis_validity_outside_event_time), one whose last valid day is the event day or later is exported with validUntil verbatim"


def collision_export(root: Path, public_ids: dict | None = None) -> tuple[SimpleNamespace, dict]:
    """The real export of the LEGAL collision world through the installed CLI: documents `a` and `a2` of one issue both use the local mention id `m-a` (S2 scopes
    member identity by documentVersion + mentionId). Both source members and the second document's evidence must survive, and the issue keeps the operator's
    representative (the member of document `a`). The backend maps such a handoff by (article id, article version, local mention id), never by the local id alone.
    `public_ids` maps the authored public company ids to others (an importer smoke's own catalog)."""
    world = build_world(root, collide=True, a2_differs=False)
    decisions = decisions_doc(world)
    for company in decisions["companies"]:
        company["publicId"] = (public_ids or {}).get(company["publicId"], company["publicId"])
    write_operator(world, decisions=decisions)
    operator = Operator(world)
    operator.cli("freeze", manifest_doc(world, "handoff-collision-1", file_hashes(world.root)))
    out = operator.cli("export", operator.sel("handoff-collision-1"))
    assert out["delivery"]["status"] == "current" and out["state"] == "ready", out["delivery"]
    supply = next(i for i in out["bundle"]["issues"] if i["id"] == "issue:supply-2026q3")
    assert {(e["documentId"], e["mentionId"]) for e in supply["sourceEvents"]} == {(world.refs[name]["documentId"], "m-a") for name in ("a", "a2")}, supply["sourceEvents"]
    assert supply["representative"]["mentionId"] == "m-a" and supply["representative"]["documentId"] == world.refs["a"]["documentId"], supply["representative"]
    assert evidence_id(world, "a2", EVT_A2) in supply["evidenceIds"], "the second document's evidence was dropped"
    return world, out


def smoke(root: Path, fixture: Path | None) -> dict:
    world = build_world(root)
    write_operator(world)
    operator = Operator(world)
    manifest = manifest_doc(world, "handoff-1", file_hashes(root))
    sources_before = {name: tree(root / name) for name in ("ingestion", "extraction", "relation")}
    checks = []

    frozen = operator.cli("freeze", manifest)
    assert frozen["state"] == "ready" and frozen["publication"] == "not-published" and frozen["usage"] == {"providerCalls": 0, "modelCalls": 0}, frozen
    assert frozen["receipt"]["counts"] == expected(world)["counts"] and frozen["next"] == "export" and "bundle" not in frozen
    assert frozen["receipt"]["checks"]["appImportPending"] and "graphDb" not in json.dumps(frozen["receipt"]["checks"])
    checks.append("freeze over two S3 jobs / two S2 upstreams: ready receipt bound to manifest digest and source revisions, counts only")

    again = operator.cli("freeze", manifest)
    assert again == frozen
    changed = json.loads(json.dumps(manifest))
    changed["sourceKind"] = "actual"
    assert operator.cli("freeze", changed, expected=2)["error"]["code"] == "handoff_input_conflict"
    checks.append("same handoffId + same input idempotent (identical receipt, no new attempt); changed input conflicts")

    exported = operator.cli("export", operator.sel("handoff-1"))
    check_export(world, exported)
    assert exported["manifest"] == manifest and digest(exported["manifest"]) == frozen["receipt"]["manifestDigest"] == exported["bundle"]["manifestDigest"]
    assert "manifest" not in frozen and "manifest" not in operator.cli("inspect", operator.sel("handoff-1")), "status must not carry the manifest"
    assert exported["bundle"]["digests"]["content"] == frozen["receipt"]["contentDigest"]
    raw_bundle = (operator.state / "bundles" / f"{frozen['receipt']['bundleDigest']}.json").read_bytes()
    assert canonical(exported["bundle"]).encode() == raw_bundle
    for text in PRIVATE:
        assert text not in json.dumps(exported, ensure_ascii=False), "source content leaked"
    checks.append("export: full pinned bundle equals the hand-written expectation, byte-identical to the stored artifact, no quote/body text")

    # Unknown outcome: killed after the reservation / after the artifact; `recover` settles from the stored artifact only.
    for name, hook in (("handoff-reserved", "kill-after-reserve"), ("handoff-artifact", "kill-after-artifact")):
        operator.cli("freeze", manifest_doc(world, name, file_hashes(root)), expected=9, hook=hook)
        # The killed writer leaves committed data in the WAL: a reader refuses it until a writer command has settled the ledger.
        assert operator.cli("inspect", operator.sel(name), expected=2)["error"]["code"] == "handoff_recovery_required"
        settled = operator.cli("recover", operator.sel(name))
        want = "failed" if hook == "kill-after-reserve" else "ready"
        assert settled["state"] == want and settled["attempts"][-1]["kind"] == "recover", settled
        if want == "failed":
            assert settled["failure"] == {"code": "handoff_artifact_missing"} and operator.cli("recover", operator.sel(name), expected=2)["error"]["code"] == "recovery_not_required"
        else:
            assert operator.cli("export", operator.sel(name))["bundle"]["handoffId"] == name
    checks.append("kill after reserve -> recover marks the handoff failed (never regenerated); kill after artifact -> recover confirms and export works")

    # Current authority: a revoked grant withholds the stored-ready handoff with no content.
    registry = json.loads(world.kit.registry_path.read_text())
    registry["sources"][0]["grant"]["enabled"] = False
    world.kit.registry_path.write_bytes(json_bytes(registry))
    withheld = operator.cli("export", operator.sel("handoff-1"), expected=2)
    assert set(withheld) == {"schemaVersion", "handoffId", "state", "publication", "delivery", "usage"} and withheld["delivery"]["status"] == "withheld", withheld
    registry["sources"][0]["grant"]["enabled"] = True
    world.kit.registry_path.write_bytes(json_bytes(registry))
    assert operator.cli("export", operator.sel("handoff-1"))["delivery"]["status"] == "current"
    checks.append("revoked grant -> withheld envelope (no bundle, counts or ids); restored -> current again")

    # Altered artifact.
    artifact = operator.state / "bundles" / f"{frozen['receipt']['bundleDigest']}.json"
    original = artifact.read_bytes()
    os.chmod(artifact, 0o600)
    artifact.write_bytes(original.replace(b'"KRX:000660"', b'"KRX:000661"', 1))
    assert operator.cli("inspect", operator.sel("handoff-1"), expected=2)["error"]["code"] == "handoff_artifact_invalid"
    assert operator.cli("export", operator.sel("handoff-1"), expected=2)["error"]["code"] == "handoff_artifact_invalid"
    artifact.write_bytes(original)
    assert operator.cli("inspect", operator.sel("handoff-1"))["state"] == "ready"
    checks.append("altered artifact bytes -> inspect/export refuse (handoff_artifact_invalid)")

    assert {name: tree(root / name) for name in ("ingestion", "extraction", "relation")} == sources_before
    checks.append("source ledgers byte/mode/mtime identical after every command")
    checks.append(validity_end_inclusive(root))
    collision_world, collision = collision_export(root.parent / "collision")
    checks.append("legal local mentionId collision (documents a and a2 both use `m-a`): both source members and the second document's evidence survive, the representative is kept")

    if fixture is not None:
        write_fixture(fixture, exported, withheld, collision)
        checks.append(f"fixtures written to {fixture}")
    return {"status": "passed", "providerCalls": 0, "modelCalls": 0, "checks": checks}


def write_fixture(directory: Path, valid: dict, withheld: dict, collision: dict) -> None:
    """The valid export envelope, the real export of the legal local-mentionId collision world, negative bundles (each MUST be refused by an importer) and the withheld envelope (no bundle at all)."""
    directory.mkdir()                                                    # the caller proved it does not exist: a fixture directory is never reused or overwritten
    write = lambda name, value: (directory / name).write_bytes(json_bytes(value) + b"\n")  # noqa: E731
    write("export-valid.json", valid)
    write("export-withheld.json", withheld)
    write("export-collision.json", collision)
    bundle = valid["bundle"]

    def mutate(name: str, change) -> None:
        copy = json.loads(json.dumps(bundle))
        change(copy)
        write(name, {**valid, "bundle": copy})

    def forge_evidence(b):
        b["evidence"][0]["id"] = "ev-" + "0" * 64

    def drop_geography(b):
        b["issues"][0]["geography"] = None

    def dangle(b):
        b["relations"][0]["target"] = "KRX:999999"

    mutate("bundle-forged-evidence-id.json", forge_evidence)
    mutate("bundle-missing-geography.json", drop_geography)
    mutate("bundle-dangling-endpoint.json", dangle)
    mutate("bundle-wrong-article-version.json", lambda b: b["evidence"][0].update({"articleVersion": "f" * 64}))
    mutate("bundle-shares-issue-edge.json", lambda b: b["relations"][0].update({"type": "SHARES_ISSUE"}))

    def forge_manifest(name: str, change) -> None:
        copy = json.loads(json.dumps(valid["manifest"]))
        change(copy)
        write(name, {**valid, "manifest": copy})

    forge_manifest("manifest-wrong-digest.json", lambda m: m.update({"sourceKind": "actual"}))
    forge_manifest("manifest-wrong-source-pin.json", lambda m: m["sources"][0].update({"reviewDigest": "f" * 64}))
    forge_manifest("manifest-wrong-file-pin.json", lambda m: m["files"].update({"bindings": "f" * 64}))
    forge_manifest("manifest-unknown-field.json", lambda m: m.update({"operatorPath": "/private/x"}))
    write("export-missing-manifest.json", {key: value for key, value in valid.items() if key != "manifest"})


# ---------------------------------------------------------------- retained operator package ----------------------------------------

PACKAGE_SCHEMA = "zoop-handoff-package-1"
PACKAGE_HANDOFF_ID = "synthetic-handoff-1"
PACKAGE_OPERATOR = "package-operator"
SYNTH_PUBLIC_IDS = {"KRX:005930": "SYNTH:000001", "KRX:000660": "SYNTH:000002"}   # the app catalog's seeded ids are never reused
LEDGERS = ("ingestion", "extraction", "relation", "handoff")
OPERATOR_FILES = ("sources", "canonical", "decisions", "bindings")


def new_output(path: Path, *, real_parent: bool = False) -> Path:
    """The absolute, not yet existing output path. Nothing is ever overwritten. A world's parent must be a real directory: a symlinked parent (macOS
    /tmp -> /private/tmp) is refused by every pipeline ledger."""
    given = Path(os.path.abspath(path))
    if os.path.lexists(given):
        raise SystemExit(f"refusing to overwrite: {given} already exists")
    if not given.parent.is_dir() or (real_parent and Path(os.path.realpath(given.parent)) != given.parent):
        raise SystemExit(f"the parent of {given} must be an existing directory" + (" without a symlink component (use the real path)" if real_parent else ""))
    return given


def put_new(path: Path, value) -> None:
    with open(path, "xb") as handle:
        handle.write(json_bytes(value) + b"\n")


def file_sha(path: Path) -> str:
    return digest_text_bytes(path.read_bytes())


def digest_text_bytes(raw: bytes) -> str:
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def write_package(directory: Path) -> dict:
    """Builds the authored world IN `directory` (a new path), freezes and exports one handoff through the installed CLI and keeps everything the recipient needs."""
    directory.mkdir(mode=0o700)
    try:
        return build_package(directory)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)               # only what this run created: the directory did not exist before
        raise


def build_package(root: Path) -> dict:
    world = build_world(root)
    decisions = decisions_doc(world)
    for company in decisions["companies"]:
        company["publicId"] = SYNTH_PUBLIC_IDS[company["publicId"]]
    write_operator(world, decisions=decisions)
    operator = Operator(world)
    sources_before = {name: tree(root / name) for name in ("ingestion", "extraction", "relation")}
    manifest = manifest_doc(world, PACKAGE_HANDOFF_ID, file_hashes(root))
    frozen = operator.cli("freeze", manifest)
    assert frozen["state"] == "ready" and frozen["publication"] == "not-published" and frozen["usage"] == {"providerCalls": 0, "modelCalls": 0}, frozen
    out = operator.cli("export", operator.sel(PACKAGE_HANDOFF_ID))
    check_export(world, out, SYNTH_PUBLIC_IDS)
    receipt, bundle = frozen["receipt"], out["bundle"]
    pins = {"manifestDigest": digest(manifest), "bundleDigest": digest_text_bytes(canonical(bundle).encode("utf-8")), "contentDigest": receipt["contentDigest"]}
    assert pins["manifestDigest"] == receipt["manifestDigest"] and pins["bundleDigest"] == receipt["bundleDigest"] == out["receipt"]["bundleDigest"], "pins are not the canonical hashes"
    assert {name: tree(root / name) for name in ("ingestion", "extraction", "relation")} == sources_before, "a source ledger changed"
    observations = [{key: ref[key] for key in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")} for ref in world.refs.values()]
    put_new(root / "export-request.json", operator.sel(PACKAGE_HANDOFF_ID))
    put_new(root / "document-import-request.json", {"schemaVersion": "zoop-document-import-1", "items": [{"kind": "news", "observation": o} for o in observations]})
    put_new(root / "graph-handoff-import-request.json", {"schemaVersion": "zoop-graph-handoff-import-1", "handoffId": PACKAGE_HANDOFF_ID, "expectedManifestDigest": pins["manifestDigest"],
                                                         "expectedBundleDigest": pins["bundleDigest"], "operator": PACKAGE_OPERATOR})
    put_new(root / "export-valid.json", out)
    summary = {"schemaVersion": PACKAGE_SCHEMA, "handoffId": PACKAGE_HANDOFF_ID, "sourceKind": "synthetic", "provenance": bundle["provenance"], "pins": pins,
               "operatorFiles": {name: file_sha(root / f"{name}.json") for name in OPERATOR_FILES}, "ledgers": list(LEDGERS), "counts": bundle["counts"],
               "companies": [{"id": c["id"], "label": c["label"]} for c in bundle["companies"]], "documents": len(observations), "locationBound": True,
               "publication": "not-published", "activation": "none", "providerCalls": 0, "modelCalls": 0}
    put_new(root / "PACKAGE.json", summary)
    return summary


def installed(name: str) -> Path:
    """The console script of the interpreter's own environment (the installed, non-editable CLI)."""
    path = Path(sys.executable).parent / name
    if not (path.is_file() and os.access(path, os.X_OK)):
        raise SystemExit(f"{name} is not installed next to {sys.executable} (run `make pipeline-install`)")
    return path


def verify_package(directory: Path, export_out: Path | None) -> dict:
    """Fresh-process re-export of a package through the installed CLIs; the current pins must be the ones recorded at generation."""
    root = Path(os.path.abspath(directory))
    if Path(os.path.realpath(root)) != root or not root.is_dir():
        raise SystemExit("the package must be given by its real, non-symlinked directory path")
    package = json.loads((root / "PACKAGE.json").read_bytes())
    assert package.get("schemaVersion") == PACKAGE_SCHEMA, "not a zoop-handoff-package-1 directory"
    for name in OPERATOR_FILES:
        assert file_sha(root / f"{name}.json") == package["operatorFiles"][name], f"{name}.json differs from PACKAGE.json"
    registry = json.loads((root / "sources.json").read_bytes())
    if any(source["inputRoot"] != str(root / "inputs") for source in registry["sources"]):
        raise SystemExit("the package was moved or copied: the S2-1 ledger pins the absolute path it was generated at. Run --write-package at the new location.")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM}
    before = {name: tree(root / name) for name in ("ingestion", "extraction", "relation")}
    request = (root / "export-request.json").read_bytes()
    argv = [str(installed("zoop-ai-handoff")), "export", "--state-dir", str(root / "handoff"), "--relation-state-dir", str(root / "relation"),
            "--extraction-state-dir", str(root / "extraction"), "--ingestion-state-dir", str(root / "ingestion"), "--sources", str(root / "sources.json"),
            "--canonical", str(root / "canonical.json"), "--decisions", str(root / "decisions.json"), "--bindings", str(root / "bindings.json")]
    child = subprocess.run(argv, input=request, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=root, timeout=300)
    assert child.returncode == 0, ("export", child.returncode, child.stdout.decode()[:2000], child.stderr.decode()[-2000:])
    out = json.loads(child.stdout)
    assert out["delivery"]["status"] == "current" and out["publication"] == "not-published" and out["handoffId"] == package["handoffId"], out["delivery"]
    pins = {"manifestDigest": digest(out["manifest"]), "bundleDigest": digest_text_bytes(canonical(out["bundle"]).encode("utf-8")),
            "contentDigest": out["receipt"]["contentDigest"]}
    assert pins == package["pins"] == {"manifestDigest": out["receipt"]["manifestDigest"], "bundleDigest": out["receipt"]["bundleDigest"],
                                       "contentDigest": out["bundle"]["digests"]["content"]}, ("pins differ", pins, package["pins"])
    documents = json.loads((root / "document-import-request.json").read_bytes())["items"]
    for item in documents:
        done = subprocess.run([str(installed("zoop-ai-ingest")), "export", "--state-dir", str(root / "ingestion"), "--sources", str(root / "sources.json"), "--require-store"],
                              input=json_bytes({"schemaVersion": "zoop-ingestion-s2-1", **item["observation"]}), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                              cwd=root, timeout=120)
        assert done.returncode == 0 and isinstance(json.loads(done.stdout), dict), ("ingestion export", item["observation"]["documentId"], done.returncode, done.stdout.decode()[:500])
    assert {name: tree(root / name) for name in ("ingestion", "extraction", "relation")} == before, "a source ledger changed"
    if export_out is not None:
        with open(export_out, "xb") as handle:
            handle.write(child.stdout)
    return {"status": "passed", "handoffId": package["handoffId"], "pins": pins, "pinsEqualPackage": True, "documentsExported": len(documents),
            "exportOut": export_out is not None, "providerCalls": 0, "modelCalls": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write-fixture", type=Path, help="run the full smoke and write the importer fixtures into this NEW directory")
    parser.add_argument("--write-package", type=Path, help="build the retained operator package in this NEW directory (no smoke, nothing temporary)")
    parser.add_argument("--verify-package", type=Path, help="re-export an existing package in fresh processes and compare with its pins")
    parser.add_argument("--export-out", type=Path, help="with --verify-package: write the current export envelope to this NEW file")
    args = parser.parse_args()
    modes = [name for name in ("write_fixture", "write_package", "verify_package") if getattr(args, name) is not None]
    if len(modes) > 1 or (args.export_out is not None and args.verify_package is None):
        parser.error("--write-fixture, --write-package and --verify-package are exclusive; --export-out needs --verify-package")
    if args.verify_package is not None:
        print(json.dumps(verify_package(args.verify_package, new_output(args.export_out) if args.export_out else None), ensure_ascii=False, indent=1))
        return 0
    if args.write_package is not None:
        print(json.dumps(write_package(new_output(args.write_package, real_parent=True)), ensure_ascii=False, indent=1))
        return 0
    fixture = new_output(args.write_fixture) if args.write_fixture else None
    root = Path(tempfile.mkdtemp(prefix="zoop-handoff-smoke-")).resolve()      # a symlinked parent (macOS /tmp -> /private/tmp) is refused by every pipeline ledger
    try:
        print(json.dumps(smoke(root / "owned", fixture), ensure_ascii=False, indent=1))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
