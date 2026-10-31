#!/usr/bin/env python3
"""Actual ingestion + S2 + S3 world -> installed `zoop-ai-handoff` subprocesses (no Neo4j: the handoff does not read the private graph).

    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_handoff_smoke.py [--write-fixture DIR]
    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_handoff_smoke.py --write-package DIR        # retained operator package (see below)
    ai/pipeline/.venv/bin/python ai/pipeline/scripts/graph_handoff_smoke.py --verify-package DIR [--export-out FILE]

Two S2 jobs (two events, one frozen snapshot event with two documents) and two S3 jobs are authored replay: no model, no provider, no original PoC state,
no network (every CLI subprocess runs under a socket audit hook). Expectations are written by hand from the authored world, never derived from the
planner under test. `--write-fixture DIR` additionally writes the valid export envelope (bundle `-7`, no operator verdict, default `not-proposed` impact rows, `not-requested` summaries), the real export of a `rich` impact world, the real exports of a hand-reviewed SYNTHETIC world
(`export-field-verdicts.json`, handoff `handoff-verdicts-1`, also importable through `verdict_export`) and of a time-withheld one (`export-field-verdicts-time.json`), the
hand-written expected original mentions (`expected-mentions.json`), field provenance (`expected-field-provenance.json`), verdicts (`expected-field-verdicts.json`) and public
headline values (`expected-headline-values.json`), the real withheld envelope of a handoff frozen under an earlier bundle schema and negative fixtures the backend import can be tested with.
The issue-summary world (`export-summary.json`: an available summary and a deterministic `temporal-review-pending`; `export-summary-withheld.json`: a `verifier-hold` job result and `not-requested`; the hand-written
`expected-summaries.json` of every export and one rule broken per `bundle-summary-NN.json`) pins REAL authored-replay `zoop-ai-issue-summary` job results in the decisions and freezes them with
`--issue-summary-state-dir`; the export never opens that ledger and no model or provider is called.
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
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.ingestion_smoke import json_bytes, ownership_env  # noqa: E402
from scripts.extraction_smoke import page  # noqa: E402
from scripts.relation_smoke import RelKit, SUP, INV, co, converge, ev, find, impact_item, impact_verifier_reply, proposal, tree, world_cite  # noqa: E402
from zoop_ai_pipeline.graph_projection import review_state  # noqa: E402
from zoop_ai_pipeline.handoff_contracts import POLICY, app_evidence_id, content_digest  # noqa: E402
from zoop_ai_pipeline.issue_summary import producer_payload, verifier_payload  # noqa: E402
from zoop_ai_pipeline.issue_summary_contracts import summary_basis  # noqa: E402
from zoop_ai_pipeline.issue_summary_prompts import claims_from  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import canonical, digest  # noqa: E402

CUSTOM = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
EVT_A = "합성기업은 2026년 3분기 공급 계약을 발표했다."
GEO_A = "계약은 국내 시장 중심이다."
EVT_A2 = "합성기업이 3분기 공급 계약 체결을 공개했다."
QB = "합성기업은 4분기 신규 공장 착공을 알렸다."
GEO_B = "착공은 미국에서 이뤄진다."
QB3 = "합성투자는 해외 합작 공장 지분을 인수했다."
ACTION_SNAPSHOT = "공급 계약 재공지"         # what upstream b's snapshot says about document a's mention when the two upstreams disagree about it
SAME = object()                                # `a2_event_time` default: the second document dates the event like the first one
UNSET = object()                               # `decisions_doc(published_time=...)`/`structural_binding`: the authored world's own event time
# Operator-declared publishing outlets of the authored world, by document name. Only "a" declares one; a2 and b stay unspecified (no key, so the
# application stores NULL for them). The outlet is written into the real fixture item before it is hashed, never patched in afterwards.
PUBLISHERS = {"a": "합성일보 Synthetic Daily"}
# The S2 participants of the authored mentions, each a different mapping case (the canonical registry and the public decisions below decide the rest).
ISSUER = {"company_id": "SYNTH-1", "name": "합성기업", "role": "issuer"}          # every upstream maps it to co:synth-1 -> KRX:005930, which the bundle publishes
SUPPLIER = {"company_id": "SYNTH-3", "name": "합성부품", "role": "supplier"}      # every upstream maps it to co:synth-3 -> KRX:000660, which the bundle publishes
PARTNER = {"company_id": "SYNTH-2", "name": "합성협력", "role": "partner"}        # mapped to co:synth-2, which no public decision carries
STRANGER = {"company_id": "SYNTH-9", "name": "미등록 법인", "role": "observer"}   # no canonical entry in any upstream
UNKNOWN = {"company_id": None, "name": "미상 거래처", "role": "counterparty"}      # a name without any company id


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
CHAIN = "합성투자는 합성부품에 소재를 공급한다."     # `chain=True` worlds: the second SUPPLIES link (SYNTH-4 supplies SYNTH-3) that makes a two-relation structural path
# A real reviewer name and review note live ONLY in the S3 relation ledger (see the unit tests' review helper). They are unique synthetic markers so that the
# privacy check cannot collide with legitimate public vocabulary such as the `operator-asserted` status or the operator-asserted reviewer id below.
PRIVATE_REVIEWER = "private-reviewer-zq7x"
PRIVATE_NOTE = "private-review-note-zq7x"
PRIVATE = (SUP, INV, EVT_A, GEO_A, EVT_A2, QB, GEO_B, QB3, PRIVATE_REVIEWER, PRIVATE_NOTE)     # source sentences / S3 review text that must never appear in any output
REVIEWER = "reviewer-a"                                                                       # the operator's PUBLIC attestation reviewer id (intended export)
APPROVER = "final-approver-1"                                                                  # the S3 operator whose FINAL approval a manual relation carries (intended audit export)
ORIGIN_SHARED = "origin:synth-wire-1"                                                          # the one declared origin documents a and a2 (different texts) share
ORIGINS = {"a": ORIGIN_SHARED, "a2": ORIGIN_SHARED}                                            # operator-declared origins by document name; b declares none (unknown)


# ---------------------------------------------------------------- the authored world (also used by the unit tests) -----------------

UNCITED_SOURCE = "synthetic-source-uncited"          # the source (and grant) document a2 is ingested under in the issue-summary worlds


def uncited_source_entry(base: dict) -> dict:
    """A second registry source: a copy of the world's only source under its OWN source id and its OWN grant, so one grant can be revoked while the other stays."""
    return {**base, "sourceId": UNCITED_SOURCE, "grant": {**base["grant"], "grantId": "operator-grant-uncited", "sourceId": UNCITED_SOURCE}}


def ingest_in_source(kit, name: str, document: dict, source_id: str) -> dict:
    """`Kit.ingest` for ONE document under another source id (its checkpoint starts at revision 0): the exact observation ref."""
    item = kit.item("c0", document["supplier"], f"https://example.invalid/{name}/0", ref="d0", publisher=document.get("publisher"))
    item["publishedAt"] = document.get("published", "2026-10-08T00:00:00+00:00")
    manifest = kit.manifest(name, [[item]], bodies={"d0": document["html"]})
    payload = json.loads(manifest.read_bytes())
    payload["sourceId"] = source_id
    manifest.write_bytes(json_bytes(payload))
    request = {**kit.request(manifest, f"round-{name}", 0), "sourceId": source_id}
    result = kit.cli("run", request, state="ingestion", manifest=manifest)
    assert result["state"] == "complete" and result["counts"]["textReady"] == 1, result
    ref = result["documentRefs"][0]
    return {"roundId": request["roundId"], "sourceId": source_id, "page": ref["page"], "ordinal": ref["ordinal"], "documentId": ref["documentId"],
            "rawVersion": ref["rawVersion"], "documentVersion": ref["documentVersion"]}


def set_grant(world, source_id: str, enabled: bool) -> None:
    """Revoke or restore the grant of ONE source of the world's registry (the other sources are untouched)."""
    registry = json.loads(world.kit.registry_path.read_text())
    next(source for source in registry["sources"] if source["sourceId"] == source_id)["grant"]["enabled"] = enabled
    world.kit.registry_path.write_bytes(json_bytes(registry))


def build_world(root: Path, *, collide: bool = False, a2_differs: bool = True, a_countries: tuple = ("KR",), a2_countries: tuple = ("KR",), dated: bool = False,
                valid_from: str | None = "2026-01-01", valid_until: str | None = "2026-12-31", event_time: str | None = "2026-09-30",
                a2_event_time=SAME, snapshot_differs: bool = False, approve: bool = False, chain: bool = False, impact: str | None = None,
                uncited_source: bool = False, raw_time_evidence: bool = False) -> SimpleNamespace:
    """The authored world. Variants (each is a REAL ingestion + S2 + S3 world, used by the integrity regressions):
    collide: the two documents of snapshot event-a use the SAME local mention id (S2 scopes member identity by documentVersion + mentionId, so this is legal);
    a2_differs: the second member's title differs (a metadata conflict unless the operator picks a representative); a2_countries: its country field;
    dated: rel-b also holds an eligible SUPPLIES basis whose validity dates are proven ONLY by a sentence in another document (b); `valid_from`/`valid_until`
    (None = unknown, no sentence, no citation) are that basis's validity and `event_time` is the supply issue's event time in BOTH of its documents;
    a2_event_time: the second document's own event time for its mention (default: `event_time`);
    snapshot_differs: the snapshot upstream b froze says another `action` for document a's mention (`m-a`) than upstream a's own extraction of it, i.e. ONE mention
    identity carried by two upstreams with different values;
    approve: the authored independent verifier HOLDs two relations the issues depend on (rel-a's SUPPLIES basis and rel-b's PARTICIPATES_IN of event-a) and the operator FINALLY
    approves exactly those two through the real S3 review path (effect `approved`, no call): the other relations stay automatic;
    chain: document a also states that SYNTH-4 supplies SYNTH-3 and rel-a holds that eligible SUPPLIES relation (with its own business/product scope), so SYNTH-4 -> SYNTH-3 -> SYNTH-1 is
    a two-relation structural basis over the supply issue's participant SYNTH-1.
    impact: `verified` (rel-a's participation: a verified POSITIVE impact over its own sentence plus an uncited sentence of document a; rel-b's participation in `event-a`: a verified
    NEGATIVE one on the SAME supply edge; the factory participation: `no-evidence`, plus an off-target company that is never exported) or `rejected` (the verifier contradicts the
    target of rel-a's impact, finds rel-b's `event-a` target insufficient, and the factory impact cites a document outside the relation); default none: every impact stage is complete
    with no candidate (`not-proposed`).
    uncited_source: document a2 is ingested under its OWN source id and grant (`UNCITED_SOURCE`), so revoking that grant alone removes one article of the supply issue's summary basis."""
    kit = RelKit(root)
    valid_text = validity_sentence(valid_from, valid_until) if dated else None
    raw_a = (f"계약 날짜 표기는 {event_time}이다.",) if raw_time_evidence else ()
    raw_a2 = (f"계약 날짜 표기는 {event_time if a2_event_time is SAME else a2_event_time}이다.",) if raw_time_evidence else ()
    docs = [{"supplier": "supplier-a", "html": page(SUP, INV, EVT_A, GEO_A, *raw_a, *((CHAIN,) if chain else ())), "publisher": PUBLISHERS["a"]},
            {"supplier": "supplier-a2", "html": page(EVT_A2, *raw_a2)},
            {"supplier": "supplier-b", "html": page(QB, GEO_B, QB3, *((valid_text,) if valid_text else ())), "published": None}]
    if uncited_source:
        kit.registry["sources"].append(uncited_source_entry(kit.registry["sources"][0]))
        kit.save_registry()
        # a and b are the SAME article versions the standard world registers (the app keeps one row per documentId+version, URL included): b keeps the URL it has there (`docs/2`).
        d1, d3 = kit.ingest("docs", [docs[0], {**docs[2], "url": "https://example.invalid/docs/2"}])
        d2 = ingest_in_source(kit, "docs-a2", docs[1], UNCITED_SOURCE)
    else:
        d1, d2, d3 = kit.ingest("docs", docs)
    refs = {"a": d1, "a2": d2, "b": d3}
    art = {name: kit.article(ref) for name, ref in refs.items()}
    m_a = {**kit.mention(art["a"], "m-a", [kit.evidence(art["a"], EVT_A)], event_time=event_time), "countries": list(a_countries), "participants": [ISSUER, SUPPLIER, UNKNOWN]}
    second = {} if a2_differs else {"title": "합성 공급 계약"}
    m_a2 = {**kit.mention(art["a2"], "m-a" if collide else "m-a2", [kit.evidence(art["a2"], EVT_A2)], event_time=event_time if a2_event_time is SAME else a2_event_time,
                          **({"title": "합성 공급 계약 체결 공개"} | second)), "countries": list(a2_countries)}
    m_b = {**kit.mention(art["b"], "m-b", [kit.evidence(art["b"], QB)], period="2026Q4", title="합성 공장 착공", action="공장 착공 알림", event_time="2026-11-15"),
           "countries": ["US"], "participants": [ISSUER, PARTNER, STRANGER]}
    m_b3 = {**kit.mention(art["b"], "m-b3", [kit.evidence(art["b"], QB3)], period="2026Q4", title="해외 합작 공장 지분 인수", action="지분 인수"), "countries": ["US"]}
    s2a = kit.job("run", kit.submit("s2-a", d1), replay=kit.replay("s2a").extract(art["a"], [m_a]).write())
    assert s2a["state"] == "ready", s2a.get("failure")
    m_a_snapshot = {**m_a, "action": ACTION_SNAPSHOT} if snapshot_differs else m_a
    event_a = kit.event("event-a", [(d1, m_a_snapshot), (d2, m_a2)])
    members = [(d1, art["a"], m_a_snapshot), (d2, art["a2"], m_a2)]
    replay_b = (kit.replay("s2b").extract(art["b"], [m_b, m_b3])
                .compare(m_b, "event-a", members, art["b"], "FOLLOWS", "후속 착공", [kit.evidence(art["b"], QB), kit.evidence(art["a"], EVT_A)])
                .compare(m_b3, "event-a", members, art["b"], "DIFFERENT", "다른 사건", []).write())
    s2b = kit.job("run", kit.submit("s2-b", d3, [event_a]), replay=replay_b)
    assert s2b["state"] == "ready", s2b.get("failure")
    evc = {"a": s2a["eventCandidates"][0]["eventCandidateId"],
           "b": next(c["eventCandidateId"] for c in s2b["eventCandidates"] if c["localMentionId"] == "m-b"),
           "b3": next(c["eventCandidateId"] for c in s2b["eventCandidates"] if c["localMentionId"] == "m-b3")}
    world = SimpleNamespace(kit=kit, refs=refs, art=art, s2={"a": s2a, "b": s2b}, evc=evc, root=root, collide=collide, a2_differs=a2_differs)
    wa, wb = (SimpleNamespace(kit=kit, refs=refs, art=art, s2=s2) for s2 in (s2a, s2b))
    cite = lambda w, name, text: world_cite(w, name, text)  # noqa: E731
    held = {"rel-a": lambda r: r["type"] == "SUPPLIES" and r["subject"]["ref"] == "SYNTH-3" and r["object"]["ref"] == "SYNTH-1",
            "rel-b": lambda r: r["type"] == "PARTICIPATES_IN" and r["subject"]["ref"] == "SYNTH-1" and r["object"]["ref"] == "event-a"} if approve else {}
    verify = {job: (lambda r, match=match: {"type": "insufficient"} if match(r) else None) for job, match in held.items()}
    scripts, effects = impact_scripts(impact, wa, wb, evc, cite)
    jobs = {
        "rel-a": converge(wa, "rel-a", [
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(evc["a"]), [cite(wa, "a", EVT_A)]),
            proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [cite(wa, "a", SUP)], product="배터리 부품"),
            proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [cite(wa, "a", INV)]),
            proposal("SHARES_ISSUE", co("SYNTH-1"), co("SYNTH-2"), [cite(wa, "a", SUP)]),
            *([proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(evc["a"]), [cite(wa, "a", EVT_A)], countries=["KR"])] if impact == "rich" else []),
            *([proposal("SUPPLIES", co("SYNTH-4"), co("SYNTH-3"), [cite(wa, "a", CHAIN)], business="소재 사업", product="소재")] if chain else [])],
                        verify=verify.get("rel-a"), impacts=scripts.get("rel-a"), effects=effects),
        "rel-b": converge(wb, "rel-b", [
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev("event-a"), [cite(wb, "a2", EVT_A2)]),
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(evc["b"]), [cite(wb, "b", QB)]),
            proposal("PARTICIPATES_IN", co("SYNTH-2"), ev(evc["b"]), [cite(wb, "b", QB)]),
            proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(evc["b3"]), [cite(wb, "b", QB3)]),
            *([proposal("PARTICIPATES_IN", co("SYNTH-1"), ev("event-a"), [cite(wb, "a2", EVT_A2)], countries=["KR"]),
               proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(evc["b"]), [cite(wb, "b", QB)], countries=["US"])] if impact == "rich" else []),
            *([proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [cite(wb, "a", SUP)], product="배터리 부품",
                        validity={"from": valid_from, "until": valid_until, "citations": [cite(wb, "b", valid_text)] if valid_text else []})] if dated else [])],
                        verify=verify.get("rel-b"), impacts=scripts.get("rel-b"), effects=effects)}
    for name, out in jobs.items():
        assert out["state"] == "ready", (name, out.get("failure"))
    for job, match in held.items():
        candidate = next(r for r in jobs[job]["relations"] if match(r))
        assert candidate["eligibility"]["status"] == "hold" and candidate["eligibility"]["approvalBasis"] is None, (job, candidate["eligibility"])
        reviewed = kit.rel("review", {**kit.rsel(job), "relationCandidateId": candidate["relationCandidateId"], "expectedRevision": candidate["eligibility"]["revision"],
                                      "decision": "allow", "reviewer": APPROVER, "note": PRIVATE_NOTE})
        jobs[job] = {**jobs[job], **reviewed}          # the S3 result after the operator's final decision (same job, input digest and binding)
        assert next(r for r in jobs[job]["relations"] if match(r))["eligibility"]["approvalBasis"]["kind"] == "operator-final-approval"
    world.jobs, world.dated, world.valid_text, world.event_time, world.approve, world.chain, world.impact = jobs, dated, valid_text, event_time, approve, chain, impact
    return world


def build_context_world(root: Path, *, count: int = 2):
    """Two genuine operating ledgers with independent grants and native jobs, generated only by a loopback fixture."""
    from scripts.extraction_smoke import FAKE_KEYS, Kit, Q3, SimulatedProvider
    from scripts.operating_smoke import CONFIG, MANIFEST, Owner, STAGES, policy
    from zoop_ai_pipeline.extraction import Extractor, Sources, Store as ExtractionStore
    from zoop_ai_pipeline.graph_projection import Paths, Source
    from zoop_ai_pipeline.ingestion_contracts import Authority

    assert count >= 2
    root.mkdir()
    contexts, jobs, refs, art, runtimes = [], {}, {}, {}, []
    canonical_document = {"schemaVersion": "zoop-graph-canonical-1", "entries": []}
    decisions = {"schemaVersion": "zoop-public-decisions-4", "policyVersion": POLICY,
                 "companies": [{"canonicalId": "co:context", "publicId": "KRX:005930", "label": "합성기업", "decisionRef": "synthetic-catalog"}],
                 "issues": [], "structural": [], "follows": [], "origins": []}
    native = []
    with SimulatedProvider() as provider:
        for index in range(2):
            cid = f"context-{index}"
            directory = root / cid
            directory.mkdir()
            kit = Kit(directory / "inputs")
            kit.registry["sources"][0]["grant"].update(grantId=f"grant-{cid}", revision=f"revision-{cid}")
            kit.save_registry()
            selected = kit.ingest(cid, [{"supplier": f"{cid}-document-{n}", "html": page(Q3, "계약은 국내 시장 중심이다.")}
                                        for n in range(index, count, 2)])
            config = {"schemaVersion": CONFIG, "policy": {**policy(), "operationId": f"operation-{cid}"},
                      "ledgerDirectory": str(directory / "metering"), "stateDirectory": str(directory / "native"),
                      "runtime": {"model": "gpt-6-luna", "effort": "high", "maxOutputTokens": 24000,
                                  "openaiEndpoint": provider.base_url, "verifierEndpoint": provider.base_url, "verifierModel": "jev-1.14.0"}}
            units = [{"setId": f"{cid}-{n}", "extraction": kit.submit_live(f"s2-{cid}-{n}", ref),
                      "relationJobId": f"s3-{cid}-{n}", "stageAllowances": {stage: 10 for stage in STAGES},
                      "ingestionStateDirectory": str(kit.root / "ingestion"), "sources": str(kit.registry_path)}
                     for n, ref in enumerate(selected)]
            config_path, input_path = directory / "config.json", directory / "inputs.json"
            config_path.write_bytes(json_bytes(config))
            input_path.write_bytes(json_bytes({"schemaVersion": MANIFEST, "sets": units}))
            env = {"PATH": os.defpath, "HOME": str(Path.home()), "PYTHONDONTWRITEBYTECODE": "1",
                   **ownership_env(), "ZOOP_AI_PIPELINE_LIVE_ENABLED": "1", **FAKE_KEYS}

            def operate(command, *args):
                child = subprocess.run([sys.executable, "-m", "zoop_ai_pipeline.operating", command, "--config", str(config_path), *args],
                                       env=env, capture_output=True, timeout=300)
                assert child.returncode == 0, (command, child.stdout.decode(), child.stderr.decode())
                return json.loads(child.stdout)

            operate("init")
            kit.allow_model_send(Owner(config).runtime(units[0], "offline"), STAGES)
            operate("register", "--manifest", str(input_path))
            for _ in units:
                operate("run", "--max-sets", "1")
            status = operate("status")
            assert status["reconciliation"] == {"monetaryWithoutNative": [], "nativeWithoutMonetary": [], "receiptsAwaitingNativeRecovery": []}
            paths = Paths(directory / "native/s3", directory / "native/s2", kit.root / "ingestion", kit.registry_path, root / "canonical.json")
            pins = []
            with Source(paths) as source:
                for n, unit in enumerate(units):
                    result = source.inspect(unit["relationJobId"])
                    assert result["state"] == "ready" and result["delivery"]["status"] == "current", result
                    jobs[result["jobId"]] = result
                    pins.append({"relation": {"jobId": result["jobId"], "inputDigest": result["inputDigest"]},
                                 "upstream": result["binding"]["upstream"], "reviewDigest": digest(review_state(result))})
                    store = ExtractionStore(paths.extraction, paths.ingestion, existing=True)
                    try:
                        _, s2 = Extractor(store, Sources(paths.ingestion, Authority(paths.sources))).export(unit["extraction"]["jobId"])
                    finally:
                        store.close()
                    runtimes.append(s2["binding"])
                    upstream_pin = {"jobId": s2["jobId"], "inputDigest": s2["inputDigest"]}
                    for candidate in s2["eventCandidates"]:
                        canonical_document["entries"].append({"upstream": upstream_pin, "kind": "event", "ref": candidate["eventCandidateId"],
                                                              "canonicalId": f"issue:{cid}", "decisionRef": "synthetic-event"})
                    canonical_document["entries"].append({"upstream": upstream_pin, "kind": "company", "ref": "SYNTH-1",
                                                          "canonicalId": "co:context", "decisionRef": "synthetic-company"})
                    name = f"{cid}-{n}"
                    refs[name], art[name] = selected[n], kit.article(selected[n])
            first_name = f"{cid}-0"
            partial = SimpleNamespace(refs=refs, art=art)
            decisions["issues"].append({"canonicalId": f"issue:{cid}", "publicId": f"issue:{cid}", "decisionRef": "synthetic-issue",
                                       "geography": {"classification": "domestic", "countries": ["KR"],
                                                     "evidence": [span(partial, first_name, "계약은 국내 시장 중심이다.")],
                                                     "decisionRef": "synthetic-geography", "decisionVersion": "1"},
                                       "representative": None, "fieldVerdicts": [], "summary": None})
            contexts.append({"contextId": cid, "relationStateDirectory": str(paths.relation), "extractionStateDirectory": str(paths.extraction),
                             "ingestionStateDirectory": str(paths.ingestion), "sources": str(paths.sources), "sourcePins": pins, "observations": selected})
            native.append(SimpleNamespace(kit=kit, paths=paths, refs=selected, metering=directory / "metering", status=status))
    context_file = root / "source-contexts.json"
    context_file.write_bytes(json_bytes({"schemaVersion": "zoop-handoff-source-contexts-1", "contexts": contexts}))
    context_file.chmod(0o600)
    world = SimpleNamespace(root=root, kit=native[0].kit, refs=refs, art=art, jobs=jobs, native_contexts=native,
                            context_file=context_file, context_sha=digest_text(context_file.read_text()), contexts=contexts,
                            runtime_bindings=runtimes, fixture_requests=len(provider.requests))
    write_operator(world, canonical_document=canonical_document, decisions=decisions, bindings=bindings_doc(world))
    return world



# ---------------------------------------------------------------- operator documents ---------------------------------------------

def upstream(world, name: str) -> dict:
    return {"jobId": world.s2[name]["jobId"], "inputDigest": world.s2[name]["inputDigest"]}


def canonical_doc(world, *, b_supplier: str = "co:synth-3") -> dict:
    mapping = [("a", "company", "SYNTH-1", "co:synth-1"), ("a", "company", "SYNTH-3", "co:synth-3"), ("a", "company", "SYNTH-4", "co:synth-4"),
               ("a", "event", world.evc["a"], "issue:supply"),
               ("b", "company", "SYNTH-1", "co:synth-1"), ("b", "company", "SYNTH-2", "co:synth-2"), ("b", "company", "SYNTH-3", b_supplier),
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


def structural_binding(world, *, decision_version: str = "v1", job: str = "rel-a", published_time=UNSET) -> str:
    """Hand-written copy of the attestation preimage the operator reviewed (issue source events, basis relation with its S3 revision, decision version). The
    event time is the PUBLIC issue time: `published_time` is None when an operator field verdict withheld it."""
    r = find(world.jobs[job], "SUPPLIES", "SYNTH-3", "SYNTH-1")
    when = getattr(world, "event_time", "2026-09-30") if published_time is UNSET else published_time
    return digest({"policy": POLICY, "issue": "issue:supply", "company": "co:synth-3", "decisionVersion": decision_version, "eventTime": when,
                   "geography": "domestic", "sourceEvents": source_events(world),
                   "basis": [{"jobId": job, "relationCandidateId": r["relationCandidateId"], "relationKey": r["relationKey"], "type": "SUPPLIES",
                              "revision": r["eligibility"]["revision"]}]})


def origins_doc(world, declared: dict) -> list:
    """The operator's `origins[]`: one declaration per named document version (`declared` maps a document name to its origin id)."""
    return [{"documentId": world.refs[name]["documentId"], "documentVersion": world.refs[name]["documentVersion"], "originId": origin, "reviewer": REVIEWER,
            "decisionRef": f"origin-2026-10-21:{name}", "decisionVersion": "o1"} for name, origin in sorted(declared.items())]


def decisions_doc(world, *, verdicts: dict | None = None, published_time=UNSET, origins=UNSET, summaries: dict | None = None) -> dict:
    """The operator's public decisions. `verdicts` maps a canonical issue id to its per-field verdict entries (`field_verdict`); an issue without an entry has none.
    `published_time` is the supply issue's public event time the structural attestation was reviewed against (None: a time verdict withheld it). `origins` maps a document
    name to its declared origin id (default `ORIGINS`: a and a2 share one origin, b declares none). `summaries` maps a canonical issue id to the operator's PIN of one produced issue-summary
    result (`{jobId, inputDigest, resultDigest}`); an issue without one has `summary: null`."""
    verdicts, summaries = verdicts or {}, summaries or {}
    job = "rel-b" if getattr(world, "dated", False) else "rel-a"        # the dated world's structural basis is the SUPPLIES relation whose validity lives in document b
    r = find(world.jobs[job], "SUPPLIES", "SYNTH-3", "SYNTH-1")
    comparison = next(c for c in next(x for x in world.s2["b"]["eventCandidates"] if x["eventCandidateId"] == world.evc["b"])["comparisons"]
                      if c["targetEventId"] == "event-a")
    return {"schemaVersion": "zoop-public-decisions-4", "policyVersion": POLICY,
            "companies": [{"canonicalId": "co:synth-1", "publicId": "KRX:005930", "label": "합성기업", "decisionRef": "catalog-2026-10-16:1"},
                          {"canonicalId": "co:synth-3", "publicId": "KRX:000660", "label": "합성부품", "decisionRef": "catalog-2026-10-16:3"}],
            "issues": [{"canonicalId": "issue:supply", "publicId": "issue:supply-2026q3", "decisionRef": "issue-2026-10-16:supply",
                        "geography": {"classification": "domestic", "countries": ["KR"], "evidence": [span(world, "a", GEO_A)], "decisionRef": "geo-2026-10-16:supply",
                                      "decisionVersion": "g1"},
                        "representative": {"upstream": upstream(world, "a"), "kind": "event-candidate", "ref": world.evc["a"], "mentionId": "m-a",
                                           "documentId": world.refs["a"]["documentId"], "documentVersion": world.refs["a"]["documentVersion"],
                                           "observation": {k: world.refs["a"][k] for k in ("roundId", "sourceId", "page", "ordinal", "documentId", "rawVersion", "documentVersion")}},
                        "fieldVerdicts": verdicts.get("issue:supply", []), "summary": summaries.get("issue:supply")},
                       {"canonicalId": "issue:factory", "publicId": "issue:factory-2026q4", "decisionRef": "issue-2026-10-16:factory",
                        "geography": {"classification": "international", "countries": ["US"], "evidence": [span(world, "b", GEO_B)],
                                      "decisionRef": "geo-2026-10-16:factory", "decisionVersion": "g1"}, "representative": None,
                        "fieldVerdicts": verdicts.get("issue:factory", []), "summary": summaries.get("issue:factory")},
                       {"canonicalId": "issue:overseas", "publicId": "issue:overseas-2026q4", "decisionRef": "issue-2026-10-16:overseas",
                        "geography": {"classification": "domestic", "countries": ["KR"], "evidence": [span(world, "b", QB3)],
                                      "decisionRef": "geo-2026-10-16:overseas", "decisionVersion": "g1"}, "representative": None, "fieldVerdicts": [],
                        "summary": summaries.get("issue:overseas")}],
            "structural": [{"issue": "issue:supply", "company": "co:synth-3", "basis": [{"jobId": job, "relationCandidateId": r["relationCandidateId"]}],
                            "applicability": {"status": "operator-asserted", "reviewer": REVIEWER, "decisionRef": "applic-2026-10-16:1", "decisionVersion": "v1",
                                              "bindingDigest": structural_binding(world, job=job, published_time=published_time)}}],
            "follows": [{"from": "issue:factory", "to": "issue:supply", "decisionRef": "seq-2026-10-16:1", "decisionVersion": "s1",
                         "source": {"upstream": upstream(world, "b"), "eventCandidateId": world.evc["b"], "targetEventId": "event-a",
                                    "groupDigest": comparison["groupDigest"]}}],
            "origins": origins_doc(world, ORIGINS if origins is UNSET else origins)}


# ---------------------------------------------------------------- structural paths (the `chain` world) --------------------------

CATALOG = {"co:synth-1": ("KRX:005930", "합성기업", "catalog-2026-10-16:1"), "co:synth-3": ("KRX:000660", "합성부품", "catalog-2026-10-16:3"),
           "co:synth-4": ("KRX:000999", "합성투자", "catalog-2026-10-16:4")}
ONE_HOP = ("co:synth-3", [("SYNTH-3", "SYNTH-1")])                                  # participant SYNTH-1 <- SYNTH-3
TWO_HOP = ("co:synth-4", [("SYNTH-3", "SYNTH-1"), ("SYNTH-4", "SYNTH-3")])         # participant SYNTH-1 <- SYNTH-3 <- SYNTH-4 (middle SYNTH-3)


def chain_binding(world, company: str, links: list, *, decision_version: str = "v1") -> str:
    """Hand-written attestation preimage of a structural decision over the rel-a SUPPLIES relations `links` (supplier ref, customer ref), in basis order."""
    basis = []
    for supplier, customer in links:
        r = find(world.jobs["rel-a"], "SUPPLIES", supplier, customer)
        basis.append({"jobId": "rel-a", "relationCandidateId": r["relationCandidateId"], "relationKey": r["relationKey"], "type": "SUPPLIES", "revision": r["eligibility"]["revision"]})
    return digest({"policy": POLICY, "issue": "issue:supply", "company": company, "decisionVersion": decision_version, "eventTime": world.event_time, "geography": "domestic",
                   "sourceEvents": source_events(world), "basis": basis})


def chain_decision(world, company: str, links: list) -> dict:
    refs = [{"jobId": "rel-a", "relationCandidateId": find(world.jobs["rel-a"], "SUPPLIES", s, c)["relationCandidateId"]} for s, c in links]
    return {"issue": "issue:supply", "company": company, "basis": refs,
            "applicability": {"status": "operator-asserted", "reviewer": REVIEWER, "decisionRef": f"applic-2026-10-21:{company}", "decisionVersion": "v1",
                              "bindingDigest": chain_binding(world, company, links)}}


def chain_decisions(world, middle: str) -> dict:
    """The operator's decisions over the `chain` world for the supply issue. `known`: the middle company SYNTH-3 is itself the target of the one-relation edge, so the bundle
    publishes it; `private`: only the two-relation edge, SYNTH-3 is mapped but not published; `unmapped`: the operator did not map SYNTH-3 at all."""
    doc = decisions_doc(world)
    mapped = ["co:synth-1", "co:synth-4"] + ([] if middle == "unmapped" else ["co:synth-3"])
    doc["companies"] = [{"canonicalId": c, "publicId": CATALOG[c][0], "label": CATALOG[c][1], "decisionRef": CATALOG[c][2]} for c in sorted(mapped)]
    doc["structural"] = ([chain_decision(world, *ONE_HOP)] if middle == "known" else []) + [chain_decision(world, *TWO_HOP)]
    return doc


def expected_chain(middle: str, public_ids: dict | None = None) -> dict:
    """Hand-written public result of `chain_decisions`: the published companies, the private path companies and each structural edge's `structuralPath` by target."""
    pub = lambda company: (public_ids or {}).get(company, company)  # noqa: E731
    participant, supplier, tail = pub("KRX:005930"), pub("KRX:000660"), pub("KRX:000999")
    paths = {tail: ({"status": "unavailable", "reason": "intermediate_company_unmapped"} if middle == "unmapped" else
                    {"status": "complete", "companyIds": [participant, supplier, tail],
                     "links": [{"supplierCompanyId": supplier, "customerCompanyId": participant}, {"supplierCompanyId": tail, "customerCompanyId": supplier}]})}
    if middle == "known":
        paths[supplier] = {"status": "complete", "companyIds": [participant, supplier], "links": [{"supplierCompanyId": supplier, "customerCompanyId": participant}]}
    companies = sorted([participant, tail, *([supplier] if middle == "known" else [])])
    private = [{"id": supplier, "canonicalId": "co:synth-3", "label": "합성부품", "decisionRef": "catalog-2026-10-16:3"}] if middle == "private" else []
    return {"companies": companies, "pathCompanies": private, "paths": paths}


def bindings_doc(world) -> dict:
    items = []
    for name, ref in world.refs.items():
        items.append({"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "articleId": ref["documentId"], "articleVersion": ref["documentVersion"],
                      "textSha256": digest_text(world.art[name].body), "offsetUnit": "unicode_code_point"})
    return {"schemaVersion": "zoop-app-document-bindings-1", "bindings": sorted(items, key=lambda b: b["documentId"])}


# SYNTHETIC test reviews. The spans are real quotes of the authored documents, but nothing here is a real operator review of real data.
PERIOD_A, PERIOD_A2, PERIOD_B = "2026년 3분기", "3분기", "4분기"


def field_verdict(world, name: str, mention_id: str, field: str, value, decision: str, reason: str, quotes=(), *, version: str = "fv1") -> dict:
    """One operator input entry (`IssueDecision.fieldVerdicts[]`): a verdict on one original mention's `eventTime`/`period` value, with the spans the reviewer saw."""
    ref = world.refs[name]
    return {"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "mentionId": mention_id, "field": field, "value": value,
            "decision": decision, "reasonCode": reason, "evidence": [span(world, name, quote) for quote in quotes], "reviewer": REVIEWER,
            "decisionRef": f"fverdict-2026-10-21:{name}-{mention_id}-{field}", "decisionVersion": version}


def verdict_cases(world) -> dict:
    """The hand-authored review of the authored world, in a deliberately NON-canonical order (the producer sorts by mention identity, then field):
    supply (the operator's representative is document a's `m-a`): REJECT/contradicted on the representative's time (withheld) and ALLOW/stated on its period; on the
    NON-representative second document a HOLD/unstated time (no span) and a REJECT/contradicted period; factory (one mention, no representative = unanimous):
    HOLD/ambiguous period -> its headline is withheld."""
    return {"issue:supply": [field_verdict(world, "a2", "m-a2", "period", "2026Q3", "REJECT", "contradicted", [PERIOD_A2]),
                             field_verdict(world, "a", "m-a", "period", "2026Q3", "ALLOW", "stated", [PERIOD_A]),
                             field_verdict(world, "a2", "m-a2", "eventTime", "2026-09-30", "HOLD", "unstated"),
                             field_verdict(world, "a", "m-a", "eventTime", "2026-09-30", "REJECT", "contradicted", [EVT_A])],
            "issue:factory": [field_verdict(world, "b", "m-b", "period", "2026Q4", "HOLD", "ambiguous", [PERIOD_B])]}


def expected_verdicts(world, cases: dict) -> dict:
    """Hand-written bundle form of reviewed entries: public issue id -> verdicts ascending by (document, version, local mention id, field order), spans replaced by the
    proposed app evidence ids (sorted, unique) and the closed verification label. Issues without a review are `[]`."""
    public = {"issue:supply": "issue:supply-2026q3", "issue:factory": "issue:factory-2026q4"}
    fields = {"eventTime": 0, "period": 1}

    def bundle(entry: dict) -> dict:
        ids = sorted({app_evidence_id(s["documentId"], s["documentVersion"], s["start"], s["end"]) for s in entry["evidence"]})
        return {**{k: v for k, v in entry.items() if k != "evidence"}, "evidenceIds": ids, "verification": "operator-field-verdict"}

    return {public[issue]: [bundle(e) for e in sorted(entries, key=lambda e: (e["documentId"], e["documentVersion"], e["mentionId"], fields[e["field"]]))]
            for issue, entries in cases.items()} | {public[issue]: [] for issue in public if issue not in cases}


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
            "decisions": {"schemaVersion": "zoop-public-decisions-4", "policyVersion": POLICY,
                          "companies": [{"canonicalId": "co:synth-1", "publicId": "KRX:005930", "label": "합성기업", "decisionRef": "catalog-2026-10-16:1"}],
                          "issues": [{"canonicalId": "issue:y", "publicId": "issue:y-2026q3", "decisionRef": "issue-2026-10-16:y",
                                      "geography": {"classification": "domestic", "countries": ["KR"], "evidence": [span(world, "y1", GEO_Y)],
                                                    "decisionRef": "geo-2026-10-16:y", "decisionVersion": "g1"}, "representative": None, "fieldVerdicts": [], "summary": None}],
                          "structural": [], "follows": [], "origins": []},
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
    rows = expected_impacts(world, public_ids)
    return {
        "evidence": sorted([*e.values(), *([evidence_id(world, "a", INV)] if getattr(world, "impact", None) == "rich" else [])]),
        "issues": {"issue:supply-2026q3": {"canonicalId": "issue:supply", "title": "합성 공급 계약", "eventTime": "2026-09-30", "timePrecision": "day",
                                           "geography": "domestic", "evidenceIds": sorted([e["EVT_A"], e["EVT_A2"], e["GEO_A"]])},
                   "issue:factory-2026q4": {"canonicalId": "issue:factory", "title": "합성 공장 착공", "eventTime": "2026-11-15", "timePrecision": "day",
                                            "geography": "international", "evidenceIds": sorted([e["QB"], e["GEO_B"]])}},
        "relations": {("INVOLVES", "issue:supply-2026q3", pub("KRX:005930")): sorted([e["EVT_A"], e["EVT_A2"]]),
                      ("INVOLVES", "issue:factory-2026q4", pub("KRX:005930")): [e["QB"]],
                      ("STRUCTURALLY_RELATED_TO", "issue:supply-2026q3", pub("KRX:000660")): sorted([e["EVT_A"], e["EVT_A2"]]),
                      ("FOLLOWS", "issue:factory-2026q4", "issue:supply-2026q3"): sorted([e["QB"], e["EVT_A"]])},
        "basisEvidence": [e["SUP"]],
        "exclusions": {"geography_countries_disagree": 1, "company_unmapped": 1, "issue_not_public": 1},
        "counts": {"companies": 2, "pathCompanies": 0, "issues": 2, "relations": {"INVOLVES": 2, "STRUCTURALLY_RELATED_TO": 1, "FOLLOWS": 1},
                   "evidence": len(e) + (1 if getattr(world, "impact", None) == "rich" else 0), "articles": 3, "impacts": len(rows), "exclusions": 3},
        "impacts": rows}


IMPACT_REASON = "authored impact reason"
IMPACT_LIMITS = "authored impact limitation 합성 😀"
IMPACT_OFF_TARGET = "SYNTH-77"         # an impacted-company id the model invented (no company of any source): never exported


def impact_scripts(kind: str | None, wa, wb, evc: dict, cite) -> tuple[dict, object]:
    """The authored S3 impact stage per job: `rich` adds a second participation of SYNTH-1 per event (declared countries make a different relation key) so that one world holds
    every status the real replay can produce. Returns ({job: impacts(relation) -> items}, effects(candidate) -> verifier reply or {quote text: effect})."""
    if kind is None:
        return {}, None
    assert kind == "rich", kind

    def rel_a(r: dict) -> list:
        if r["type"] != "PARTICIPATES_IN" or r["subject"]["ref"] != "SYNTH-1" or r["object"]["ref"] != evc["a"]:
            return []
        if r["countries"]:          # the second participation: the verifier will contradict its target
            return [impact_item("SYNTH-1", "positive", [cite(wa, "a", EVT_A)], [])]
        return [impact_item("SYNTH-1", "positive", [cite(wa, "a", EVT_A), cite(wa, "a", INV)], [], IMPACT_LIMITS)]     # INV is cited by no relation: an impact-only quote

    def rel_b(r: dict) -> list:
        if r["type"] != "PARTICIPATES_IN" or r["subject"]["ref"] != "SYNTH-1":
            return []
        if r["object"]["ref"] == "event-a":
            if r["countries"]:      # the verifier finds the target insufficient
                return [impact_item("SYNTH-1", "positive", [cite(wb, "a2", EVT_A2)], [])]
            return [impact_item("SYNTH-1", "negative", [], [cite(wb, "a2", EVT_A2)])]
        if r["object"]["ref"] == evc["b"]:
            if r["countries"]:      # cites a document outside the relation: the deterministic precheck rejects it
                return [impact_item("SYNTH-1", "negative", [cite(wb, "a", EVT_A)], [])]
            return [impact_item("SYNTH-1", "undetermined", [], []), impact_item(IMPACT_OFF_TARGET, "negative", [cite(wb, "b", QB)], [])]
        return []

    def effects(i: dict):
        texts = {q["text"] for q in i["quotes"]}
        if texts == {EVT_A}:
            return impact_verifier_reply(i, {EVT_A: "positive"}, target="contradicted")
        if texts == {EVT_A2} and i["proposal"]["direction"] == "positive":
            return impact_verifier_reply(i, {EVT_A2: "positive"}, target="insufficient")
        return {EVT_A: "positive", INV: "neutral", EVT_A2: "negative"}

    return {"rel-a": rel_a, "rel-b": rel_b}, effects


def edge_id(source: str, target: str) -> str:
    return "edge-" + digest({"type": "INVOLVES", "source": source, "target": target})


def expected_impacts(world, public_ids: dict | None = None) -> list:
    """Hand-written `impacts[]` of the authored world, sorted by (edgeId, jobId, relationCandidateId): ONE row per INVOLVES source relation. Default world: every automatic
    participation is `not-proposed` (the impact stage completed with no candidate), the operator-approved one (`approve`) `not-applicable`. `rich` world: see `impact_scripts`.
    Only the candidate id and the verifier request digest are read from the S3 result (they are S3 identities); every status, label, effect and proposal is written out here."""
    company = (public_ids or {}).get("KRX:005930", "KRX:005930")
    supply, factory = ("issue:supply-2026q3", edge_id("issue:supply-2026q3", company)), ("issue:factory-2026q4", edge_id("issue:factory-2026q4", company))
    approved = getattr(world, "approve", False)

    def rc(job: str, obj: str, countries: list) -> str:
        return find(world.jobs[job], "PARTICIPATES_IN", "SYNTH-1", obj, countries=countries)["relationCandidateId"]

    def candidate(job: str, relation: str) -> dict:
        found = next(r for r in world.jobs[job]["relations"] if r["relationCandidateId"] == relation)["impact"]["candidates"]
        return next(c for c in found if c["impactedCompanyId"] == "SYNTH-1")

    def row(edge: tuple, job: str, relation: str, status: str, **change) -> dict:
        base = {"edgeId": edge[1], "issueId": edge[0], "companyId": company, "sourceRelation": {"jobId": job, "relationCandidateId": relation}, "impactCandidateId": None,
                "status": status, "code": None, "label": None, "targetVerdict": None, "effects": None, "verifier": "not-called", "verifierRequestDigest": None, "proposal": None}
        return {**base, **change}

    def own(job: str, relation: str, called: bool) -> dict:
        c = candidate(job, relation)
        return {"impactCandidateId": c["impactCandidateId"], **({"verifier": "called", "verifierRequestDigest": c["verdict"]["requestDigest"]} if called else {})}

    def said(direction: str, limitations: str | None = None) -> dict:
        return {"direction": direction, "reason": IMPACT_REASON, "limitations": limitations, "verification": "none"}

    def effects(**sides) -> dict:
        return {"positive": [], "negative": [], "neutral": [], "uncertain": [], **{k: sorted(v) for k, v in sides.items()}}

    a1, b1, b3 = rc("rel-a", world.evc["a"], []), rc("rel-b", "event-a", []), rc("rel-b", world.evc["b"], [])
    if getattr(world, "impact", None) != "rich":
        rows = [row(supply, "rel-a", a1, "not-proposed"), row(supply, "rel-b", b1, "not-applicable" if approved else "not-proposed"), row(factory, "rel-b", b3, "not-proposed")]
    else:
        a2, b2, b4 = rc("rel-a", world.evc["a"], ["KR"]), rc("rel-b", "event-a", ["KR"]), rc("rel-b", world.evc["b"], ["US"])
        ea, ea2, inv = evidence_id(world, "a", EVT_A), evidence_id(world, "a2", EVT_A2), evidence_id(world, "a", INV)
        rows = [row(supply, "rel-a", a1, "verified", label="positive", targetVerdict="supported", effects=effects(positive=[ea], neutral=[inv]),
                    proposal=said("positive", IMPACT_LIMITS), **own("rel-a", a1, True)),
                row(supply, "rel-a", a2, "verifier-reject", targetVerdict="contradicted", proposal=said("positive"), **own("rel-a", a2, True)),
                row(supply, "rel-b", b1, "verified", label="negative", targetVerdict="supported", effects=effects(negative=[ea2]), proposal=said("negative"),
                    **own("rel-b", b1, True)),
                row(supply, "rel-b", b2, "verified", label="undetermined", targetVerdict="insufficient", effects=effects(positive=[ea2]), proposal=said("positive"),
                    **own("rel-b", b2, True)),
                row(factory, "rel-b", b3, "no-evidence", proposal=said("undetermined"), **own("rel-b", b3, False)),
                row(factory, "rel-b", b4, "technical-reject", code="impact_precheck_rejected", **own("rel-b", b4, False))]
    return sorted(rows, key=lambda r: (r["edgeId"], r["sourceRelation"]["jobId"], r["sourceRelation"]["relationCandidateId"]))


def relation_id(world, job: str, relation_type: str, subject: str, obj: str) -> str:
    match = {"countries": []} if relation_type == "PARTICIPATES_IN" else {}          # a `rich` world also holds a second participation per event, told apart by its declared countries
    return find(world.jobs[job], relation_type, subject, obj, **match)["relationCandidateId"]


def expected_approvals(world) -> dict:
    """Hand-written approval basis of EVERY S3 relation an emitted edge of the authored world (non-dated) uses, by `(S3 job id, relationCandidateId)`: rel-a's participation
    of SYNTH-1 in the supply event and its SUPPLIES basis, rel-b's participation in `event-a` (the supply issue's second document) and in the factory event. All are
    `automatic-verifier` at revision 1 (the verdict is the only event); in the `approve` world the SUPPLIES basis and the `event-a` participation were HELD by the authored
    verifier and are decided by the operator's final approval at revision 2 (HOLD verdict, then `approved`)."""
    approved = getattr(world, "approve", False)
    automatic = {"kind": "automatic-verifier", "revision": 1, "reviewer": None}
    manual = {"kind": "operator-final-approval", "revision": 2, "reviewer": APPROVER}
    return {("rel-a", relation_id(world, "rel-a", "PARTICIPATES_IN", "SYNTH-1", world.evc["a"])): automatic,
            ("rel-a", relation_id(world, "rel-a", "SUPPLIES", "SYNTH-3", "SYNTH-1")): manual if approved else automatic,
            ("rel-b", relation_id(world, "rel-b", "PARTICIPATES_IN", "SYNTH-1", "event-a")): manual if approved else automatic,
            ("rel-b", relation_id(world, "rel-b", "PARTICIPATES_IN", "SYNTH-1", world.evc["b"])): automatic,
            **({("rel-a", find(world.jobs["rel-a"], "PARTICIPATES_IN", "SYNTH-1", world.evc["a"], countries=["KR"])["relationCandidateId"]): automatic,
                ("rel-b", find(world.jobs["rel-b"], "PARTICIPATES_IN", "SYNTH-1", "event-a", countries=["KR"])["relationCandidateId"]): automatic,
                ("rel-b", find(world.jobs["rel-b"], "PARTICIPATES_IN", "SYNTH-1", world.evc["b"], countries=["US"])["relationCandidateId"]): automatic}
               if getattr(world, "impact", None) == "rich" else {})}


def expected_origins(world) -> dict:
    """Hand-written declared origin of every authored document (by name), or None where the operator declared none (unknown; never inferred from the publisher)."""
    return {name: ({"originId": ORIGINS[name], "reviewer": REVIEWER, "decisionRef": f"origin-2026-10-21:{name}", "decisionVersion": "o1"} if name in ORIGINS else None)
            for name in world.refs}


def expected_support(world) -> dict:
    """Hand-written source support of each public issue of the authored world. Supply cites a and a2 (different texts) that declare ONE shared origin: two articles, one
    lineage group, independent source count 1, no exact duplicate. Factory cites only b, which declares no origin: unknown lineage, so the independent count is null (never
    a guess from the publisher or the host)."""
    ids = {name: ref["documentId"] for name, ref in world.refs.items()}
    return {"issue:supply-2026q3": {"articleCount": 2, "knownLineageCount": 1, "unknownLineageArticles": [], "independentSourceCount": 1, "duplicateGroups": []},
            "issue:factory-2026q4": {"articleCount": 1, "knownLineageCount": 0, "unknownLineageArticles": [ids["b"]], "independentSourceCount": None, "duplicateGroups": []}}


def assert_approvals_support_and_origins(world, bundle: dict) -> None:
    """The producer's approval proof, source provenance, origins and source support equal the hand-written expectation exactly (read from the bundle alone)."""
    approved = getattr(world, "approve", False)
    assert bundle["policy"]["sourceSupport"] == "origin-or-exact-text-union"
    assert {i["id"]: i["sourceSupport"] for i in bundle["issues"]} == expected_support(world)
    assert {a["documentId"]: (a["textSha256"], a["origin"]) for a in bundle["articles"]} == {
        ref["documentId"]: (digest_text(world.art[name].body), None if (origin := expected_origins(world)[name]) is None else {**origin, "verification": "operator-declared-origin"})
        for name, ref in world.refs.items()}
    want = expected_approvals(world)
    used = {(s["relation"]["jobId"], u["relationCandidateId"]): u for s in bundle["sources"] for u in s["reviewUsed"]}
    assert set(used) == set(want), sorted(used)
    for (job, rc), basis in want.items():
        item = next(r for r in world.jobs[job]["relations"] if r["relationCandidateId"] == rc)
        deciding = item["history"][-1]
        assert used[(job, rc)] == {"relationCandidateId": rc, "revision": basis["revision"], "approvalBasis": {**basis, "decidedAt": deciding["createdAt"]}}, (job, rc)
        assert deciding["seq"] == basis["revision"] and deciding["kind"] == ("review" if basis["kind"] == "operator-final-approval" else "verdict")
    assert all(s["reviewUsed"] == sorted(s["reviewUsed"], key=lambda u: u["relationCandidateId"]) for s in bundle["sources"])
    assert all(s["provenance"] == {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"} for s in bundle["sources"])
    # The honest per-edge literal: the automatic claim only when EVERY S3 relation behind the edge was approved by the independent verifier.
    involves = {r["source"]: r["provenance"]["s3SemanticValidation"] for r in bundle["relations"] if r["type"] == "INVOLVES"}
    assert involves == {"issue:supply-2026q3": "manual-operator-final-approval" if approved else "independent-verifier-supported-all-claims",
                        "issue:factory-2026q4": "independent-verifier-supported-all-claims"}, involves          # supply: automatic + (approve world) manual contributor
    structural = next(r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")
    assert structural["provenance"]["basisEligibility"] == ("s3-operator-final-approval" if approved else "s3-independent-verifier-supported-all-claims")
    basis = structural["basis"][0]
    assert basis["verifiedAt"] == used[("rel-a", relation_id(world, "rel-a", "SUPPLIES", "SYNTH-3", "SYNTH-1"))]["approvalBasis"]["decidedAt"]


def expected_mentions(world, public_ids: dict | None = None, *, suppliers_agree: bool = True) -> dict:
    """Hand-written original mentions of each public issue of the authored world: the S2 values exactly as authored (never verified), the app article/evidence ids
    the operator's bindings give, ascending by (document, version, local mention id). A participant's `companyId` is its public company ONLY where every upstream
    carrying the mention maps it to that one company and the bundle publishes it: SYNTH-1 and SYNTH-3 (both upstreams, both published) are mapped; SYNTH-2 (no
    public decision), SYNTH-9 (no canonical entry) and the participant without a company id are null. `suppliers_agree=False` is the world whose operator maps
    upstream b's SYNTH-3 to another company than upstream a does: that one participant is then null as well."""
    pub = lambda company: (public_ids or {}).get(company, company)  # noqa: E731
    issuer = {"sourceCompanyId": "SYNTH-1", "companyId": pub("KRX:005930"), "name": "합성기업", "role": "issuer"}
    supplier = {"sourceCompanyId": "SYNTH-3", "companyId": pub("KRX:000660") if suppliers_agree else None, "name": "합성부품", "role": "supplier"}
    unknown = {"sourceCompanyId": None, "companyId": None, "name": "미상 거래처", "role": "counterparty"}
    partner = {"sourceCompanyId": "SYNTH-2", "companyId": None, "name": "합성협력", "role": "partner"}
    stranger = {"sourceCompanyId": "SYNTH-9", "companyId": None, "name": "미등록 법인", "role": "observer"}

    def mention(name, mention_id, quote, *, title, action, event_time, period, participants):
        ref = world.refs[name]
        return {"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "mentionId": mention_id, "articleId": ref["documentId"],
                "articleVersion": ref["documentVersion"], "verification": "none", "title": title, "action": action, "target": "공급 계약", "eventTime": event_time,
                "timePrecision": "day", "period": period, "assertionStatus": "announced", "background": False, "participants": participants,
                "evidenceIds": [evidence_id(world, name, quote)]}

    order = lambda items: sorted(items, key=lambda m: (m["documentId"], m["documentVersion"], m["mentionId"]))  # noqa: E731
    supply = [mention("a", "m-a", EVT_A, title="합성 공급 계약", action="공급 계약 발표", event_time="2026-09-30", period="2026Q3", participants=[issuer, supplier, unknown]),
              mention("a2", "m-a" if world.collide else "m-a2", EVT_A2, title="합성 공급 계약 체결 공개" if world.a2_differs else "합성 공급 계약", action="공급 계약 발표",
                      event_time="2026-09-30", period="2026Q3", participants=[issuer])]
    factory = [mention("b", "m-b", QB, title="합성 공장 착공", action="공장 착공 알림", event_time="2026-11-15", period="2026Q4", participants=[issuer, partner, stranger])]
    return {"issue:supply-2026q3": order(supply), "issue:factory-2026q4": order(factory)}


def expected_field_provenance(world, withheld: dict | None = None) -> dict:
    """Hand-written `fieldProvenance` of each public issue of the authored world: HOW the issue's six headline values were selected and which original mentions state
    EXACTLY the same SELECTED value (never whether it is true: `verification` is `none`; a withheld headline does not change the lists, they compare the original
    selected value, never the redacted null). The supply issue has the operator's representative (document a's `m-a`), so its selection is `operator-representative`
    even where every mention agrees (the collision world); the representative is in every list. The second document's mention states the representative's action,
    target, event time, period and assertion status; its title differs unless the variant makes it equal (`a2_differs=False`). The factory issue has one mention and
    no representative: `unanimous`, that mention in every list. Each list is ascending by (document, version, local mention id). `withheld` maps a public issue id to
    the headline fields an operator HOLD/REJECT on the selection basis removed (default: none)."""
    def ref(name: str, mention_id: str) -> dict:
        return {"documentId": world.refs[name]["documentId"], "documentVersion": world.refs[name]["documentVersion"], "mentionId": mention_id}

    order = lambda items: sorted(items, key=lambda r: (r["documentId"], r["documentVersion"], r["mentionId"]))  # noqa: E731
    a, a2, b = ref("a", "m-a"), ref("a2", "m-a" if world.collide else "m-a2"), ref("b", "m-b")
    fields = ("title", "action", "target", "eventTime", "period", "assertionStatus")
    withheld = withheld or {}
    return {"issue:supply-2026q3": {"selection": "operator-representative", "verification": "none", "withheld": withheld.get("issue:supply-2026q3", []),
                                    "sameValueMentions": {**{field: order([a, a2]) for field in fields}, "title": [a] if world.a2_differs else order([a, a2])}},
            "issue:factory-2026q4": {"selection": "unanimous", "verification": "none", "withheld": withheld.get("issue:factory-2026q4", []),
                                     "sameValueMentions": {field: [b] for field in fields}}}


def assert_field_provenance_closed(bundle: dict) -> None:
    """Closure of every issue's field provenance and verdicts read from the bundle alone (independent of the producer and of `validate_bundle`): each list is exactly
    the issue's mentions whose value equals the SELECTED value (the representative's, or the shared one), in the mentions' order, never empty; `unanimous` lists every
    mention in every field, `operator-representative` lists the representative's mention in every field; nothing is verified. `withheld` is exactly the judged fields
    with a HOLD/REJECT on the selection basis (the representative's mention, or any mention when unanimous), the issue value of such a field is null (and an event
    time's precision `unknown`), every other issue value is the selected one, and every verdict's value equals its mention's original value."""
    fields = ("title", "action", "target", "eventTime", "period", "assertionStatus")
    identity = lambda m: {k: m[k] for k in ("documentId", "documentVersion", "mentionId")}  # noqa: E731
    for issue in bundle["issues"]:
        provenance = issue["fieldProvenance"]
        assert set(provenance) == {"selection", "verification", "withheld", "sameValueMentions"} and provenance["verification"] == "none", issue["id"]
        assert provenance["selection"] == ("operator-representative" if issue["representative"] else "unanimous"), issue["id"]
        assert set(provenance["sameValueMentions"]) == set(fields), issue["id"]
        basis = [identity(issue["representative"])] if issue["representative"] else [identity(m) for m in issue["mentions"]]
        selected = next(m for m in issue["mentions"] if identity(m) == basis[0])
        bad = {v["field"] for v in issue["fieldVerdicts"] if v["decision"] != "ALLOW" and identity(v) in basis}
        assert provenance["withheld"] == [f for f in ("eventTime", "period") if f in bad], issue["id"]
        for v in issue["fieldVerdicts"]:
            mention = next(m for m in issue["mentions"] if identity(m) == identity(v))
            assert v["value"] == mention[v["field"]] and v["verification"] == "operator-field-verdict", (issue["id"], v["field"])
        for field in fields:
            listed = provenance["sameValueMentions"][field]
            assert listed == [identity(m) for m in issue["mentions"] if m[field] == selected[field]] and listed, (issue["id"], field)
            assert issue[field] == (None if field in provenance["withheld"] else selected[field]), (issue["id"], field)
            if issue["representative"] is None:
                assert listed == [identity(m) for m in issue["mentions"]], (issue["id"], field)
            else:
                assert identity(issue["representative"]) in listed, (issue["id"], field)
        assert "eventTime" not in provenance["withheld"] or issue["timePrecision"] == "unknown", issue["id"]


def assert_mentions_reachable(bundle: dict) -> None:
    """Every mention's article and evidence can be followed inside the bundle, each evidence is on that mention's own article, every verdict's evidence is on the article
    of ITS mention, and an issue's evidence is exactly the union of its mentions', its geography and its verdicts' evidence."""
    evidence = {e["id"]: e for e in bundle["evidence"]}
    articles = {(a["articleId"], a["articleVersion"]): a for a in bundle["articles"]}
    for issue in bundle["issues"]:
        union = set(issue["geography"]["evidenceIds"])
        assert issue["mentions"], issue["id"]
        for m in issue["mentions"]:
            article = articles[(m["articleId"], m["articleVersion"])]
            assert (article["documentId"], article["documentVersion"]) == (m["documentId"], m["documentVersion"]), (issue["id"], m["mentionId"])
            assert m["evidenceIds"], (issue["id"], m["mentionId"])
            for ident in m["evidenceIds"]:
                assert (evidence[ident]["articleId"], evidence[ident]["articleVersion"]) == (m["articleId"], m["articleVersion"]), (issue["id"], ident)
                union.add(ident)
        for v in issue["fieldVerdicts"]:
            owner = next(m for m in issue["mentions"] if (m["documentId"], m["documentVersion"], m["mentionId"]) == (v["documentId"], v["documentVersion"], v["mentionId"]))
            for ident in v["evidenceIds"]:
                assert (evidence[ident]["articleId"], evidence[ident]["articleVersion"]) == (owner["articleId"], owner["articleVersion"]), (issue["id"], ident)
                union.add(ident)
        assert union == set(issue["evidenceIds"]), issue["id"]


def check_export(world, out: dict, public_ids: dict | None = None) -> None:
    """The exported envelope equals the hand-written expectation exactly."""
    want, bundle = expected(world, public_ids), out["bundle"]
    assert out["delivery"]["status"] == "current" and out["publication"] == "not-published" and out["state"] == "ready", out["delivery"]
    assert [x["id"] for x in bundle["evidence"]] == want["evidence"], [x["id"] for x in bundle["evidence"]]
    assert {i["id"]: {"canonicalId": i["canonicalId"], "title": i["title"], "eventTime": i["eventTime"], "timePrecision": i["timePrecision"],
                      "geography": i["geography"]["value"], "evidenceIds": i["evidenceIds"]} for i in bundle["issues"]} == want["issues"]
    assert {i["id"]: i["mentions"] for i in bundle["issues"]} == expected_mentions(world, public_ids)
    assert {i["id"]: i["fieldProvenance"] for i in bundle["issues"]} == expected_field_provenance(world)
    assert {i["id"]: i["fieldVerdicts"] for i in bundle["issues"]} == expected_verdicts(world, {})              # no review: no verdict, nothing withheld, nothing verified
    assert_field_provenance_closed(bundle)
    assert_mentions_reachable(bundle)
    assert_approvals_support_and_origins(world, bundle)
    assert {(r["type"], r["source"], r["target"]): r["evidenceIds"] for r in bundle["relations"]} == want["relations"]
    structural = next(r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")
    assert [b["evidenceIds"] for b in structural["basis"]] == [want["basisEvidence"]] and structural["basis"][0]["relationType"] == "SUPPLIES"
    pub = lambda company: (public_ids or {}).get(company, company)  # noqa: E731
    assert structural["structuralPath"] == {"status": "complete", "companyIds": [pub("KRX:005930"), pub("KRX:000660")],
                                            "links": [{"supplierCompanyId": pub("KRX:000660"), "customerCompanyId": pub("KRX:005930")}]}, structural["structuralPath"]
    assert (structural["basis"][0]["businessScope"], structural["basis"][0]["productScope"]) == (None, "배터리 부품") and bundle["pathCompanies"] == []
    assert all(r["structuralPath"] is None for r in bundle["relations"] if r["type"] != "STRUCTURALLY_RELATED_TO")
    assert structural["provenance"]["origin"] == "manual-operator-review" and structural["provenance"]["s3SemanticValidation"] == "none"
    assert bundle["exclusions"]["counts"] == want["exclusions"] and bundle["counts"] == want["counts"], (bundle["exclusions"], bundle["counts"])
    assert bundle["policy"]["impacts"] == "s3-independent-verifier-quote-effect" and bundle["impacts"] == want["impacts"], bundle["impacts"]
    assert IMPACT_OFF_TARGET not in json.dumps(bundle), "an off-target impacted company id must never be exported"
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

    def cli(self, command: str, request: dict, *, expected: int = 0, hook: str | None = None, state: Path | None = None, absent: bool = False, summaries: Path | None = None):
        """`absent`: every source ledger, grant registry and operator file path names something that does not exist (a command that touches any of them fails). `summaries`: the issue-summary
        ledger given as `--issue-summary-state-dir` (a freeze whose decisions pin a produced summary result needs it; no other command may be given it)."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM}
        program = GUARD + (HOOKS[hook] if hook else "") + "runpy.run_module('zoop_ai_pipeline.handoff_cli', run_name='__main__')\n"
        argv = [sys.executable, "-c", program, command, "--state-dir", str(state or self.state)]
        if command in {"freeze", "export"}:
            base = self.root / "absent" if absent else self.root
            if hasattr(self.world, "context_file"):
                argv += ["--source-contexts", str(self.world.context_file), "--source-contexts-sha256", self.world.context_sha]
            else:
                argv += ["--relation-state-dir", str(base / "relation"), "--extraction-state-dir", str(base / "extraction"),
                         "--ingestion-state-dir", str(base / "ingestion"), "--sources", str(base / "sources.json" if absent else self.world.kit.registry_path)]
            argv += ["--canonical", str(base / "canonical.json"), "--decisions", str(base / "decisions.json"), "--bindings", str(base / "bindings.json")]
        if summaries is not None:
            argv += ["--issue-summary-state-dir", str(summaries)]
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
    assert {i["id"]: i["mentions"] for i in out["bundle"]["issues"]} == expected_mentions(world, public_ids)
    assert {i["id"]: i["fieldProvenance"] for i in out["bundle"]["issues"]} == expected_field_provenance(world)         # representative set, every value agrees: still `operator-representative`
    assert_field_provenance_closed(out["bundle"])
    assert sorted((m["documentId"], m["mentionId"]) for m in supply["mentions"]) == sorted((world.refs[name]["documentId"], "m-a") for name in ("a", "a2")), \
        "three source events, two mention identities: the local id repeats, the (document, version, local id) identity does not"
    assert_mentions_reachable(out["bundle"])
    return world, out


def mention_exclusions(root: Path) -> str:
    """Two mention defects exclude the WHOLE issue, visibly (code and id only), instead of publishing one of several values or guessing a time. Both worlds are real
    ingestion + S2 + S3 worlds through the installed CLI: (1) ONE mention identity (document a, `m-a`) carried by two upstreams that disagree about its action: no value
    is chosen, merged or overwritten; (2) another document's mention whose event time has no offset, which cannot be classified without guessing (the issue's own time,
    the operator's representative's, is a clean day; the earlier bundle schema never looked at the other members' times)."""
    for name, variant, code in (("mention-conflict", {"snapshot_differs": True}, "mention_values_conflict"),
                                ("mention-time", {"a2_event_time": "2026-09-30T10:00:00"}, "mention_event_time_unreviewed"),
                                ("mention-week", {"event_time": "2026-W40-3"}, "mention_event_time_unreviewed")):
        world = build_world(root.parent / name, **variant)
        write_operator(world)
        operator = Operator(world)
        operator.cli("freeze", manifest_doc(world, f"{name}-1", file_hashes(world.root)))
        out = operator.cli("export", operator.sel(f"{name}-1"))
        assert out["delivery"]["status"] == "current", (name, out["delivery"])
        bundle = out["bundle"]
        assert [i for i in bundle["exclusions"]["items"] if i["id"] == "issue:supply"] == [{"kind": "issue", "id": "issue:supply", "jobId": None, "code": code}], name
        assert [i["id"] for i in bundle["issues"]] == ["issue:factory-2026q4"], name
        assert {i["id"]: i["mentions"] for i in bundle["issues"]} == {"issue:factory-2026q4": expected_mentions(world)["issue:factory-2026q4"]}, name
        assert {i["id"]: i["fieldProvenance"] for i in bundle["issues"]} == {"issue:factory-2026q4": expected_field_provenance(world)["issue:factory-2026q4"]}, name
        assert {a["articleId"] for a in bundle["articles"]} == {world.refs["b"]["documentId"]}, f"{name}: a source of the excluded issue reached the bundle"
        assert ACTION_SNAPSHOT not in canonical(out), f"{name}: a value of the conflicting mention reached the bundle"
    return ("mention values: one identity carried by two upstreams with different actions -> issue excluded (mention_values_conflict), no value published; a member's offset-less "
            "event time -> issue excluded (mention_event_time_unreviewed) until explicitly reviewed")


def source_support_variants(root: Path) -> str:
    """Source support through the installed CLI, every expectation hand-written. (1) No declared origin: every cited article is unknown lineage, so the independent count is null
    (nothing is inferred from the publisher the operator declared for document a, nor from any host); (2) three different origins: one lineage group per origin, independent counts
    equal the group counts, still no exact duplicate (the texts differ); (3) an operator binding that maps the second document's version onto the FIRST document's article id makes
    the supply issue cite two versions of one article: the issue is excluded visibly (`issue_article_versions_multiple`, no detail), never resolved by choosing a version."""
    for name, origins in (("support-none", {}), ("support-split", {"a": "origin:x", "a2": "origin:y", "b": "origin:x"})):
        world = build_world(root.parent / name)
        ids = {key: ref["documentId"] for key, ref in world.refs.items()}
        if not origins:
            supply = {"articleCount": 2, "knownLineageCount": 0, "unknownLineageArticles": sorted([ids["a"], ids["a2"]]), "independentSourceCount": None, "duplicateGroups": []}
            factory = {"articleCount": 1, "knownLineageCount": 0, "unknownLineageArticles": [ids["b"]], "independentSourceCount": None, "duplicateGroups": []}
        else:
            supply = {"articleCount": 2, "knownLineageCount": 2, "unknownLineageArticles": [], "independentSourceCount": 2, "duplicateGroups": []}
            factory = {"articleCount": 1, "knownLineageCount": 1, "unknownLineageArticles": [], "independentSourceCount": 1, "duplicateGroups": []}
        out = freeze_export(Operator(world), world, f"{name}-1", decisions_doc(world, origins=origins))
        assert {i["id"]: i["sourceSupport"] for i in out["bundle"]["issues"]} == {"issue:supply-2026q3": supply, "issue:factory-2026q4": factory}, name
        assert {a["documentId"]: a["origin"] and a["origin"]["originId"] for a in out["bundle"]["articles"]} == {
            ids[key]: origins.get(key) for key in ("a", "a2", "b")}, name
    world = build_world(root.parent / "support-versions")
    bindings = bindings_doc(world)
    for item in bindings["bindings"]:
        if item["documentId"] == world.refs["a2"]["documentId"]:
            item["articleId"] = world.refs["a"]["documentId"]
    write_operator(world, bindings=bindings)
    operator = Operator(world)
    operator.cli("freeze", manifest_doc(world, "support-versions-1", file_hashes(world.root)))
    out = operator.cli("export", operator.sel("support-versions-1"))
    assert out["delivery"]["status"] == "current", out["delivery"]
    assert issue_exclusions(out["bundle"], "issue:supply") == [{"kind": "issue", "id": "issue:supply", "jobId": None, "code": "issue_article_versions_multiple"}]
    assert [i["id"] for i in out["bundle"]["issues"]] == ["issue:factory-2026q4"]
    return ("source support: no declared origin -> unknown lineage and a null independent count (not inferred from the publisher); distinct origins -> one group each; one article cited "
            "at two versions -> issue excluded (issue_article_versions_multiple)")


def participants_across_upstreams(world) -> str:
    """In the collision world document a's mention `m-a` is carried by BOTH upstreams, and each maps company ids in its own namespace. When upstream b maps SYNTH-3 to
    another public company than upstream a does, no single company can be claimed: that participant's `companyId` is null (the participant stays as extracted), while
    SYNTH-1 (both agree) stays mapped; SYNTH-2, SYNTH-9 and the participant without a company id are null in either world."""
    write_operator(world, canonical_document=canonical_doc(world, b_supplier="co:synth-1"))
    operator = Operator(world)
    operator.cli("freeze", manifest_doc(world, "handoff-disagree-1", file_hashes(world.root)))
    out = operator.cli("export", operator.sel("handoff-disagree-1"))
    assert out["delivery"]["status"] == "current", out["delivery"]
    assert {i["id"]: i["mentions"] for i in out["bundle"]["issues"]} == expected_mentions(world, suppliers_agree=False)
    assert {i["id"]: i["fieldProvenance"] for i in out["bundle"]["issues"]} == expected_field_provenance(world)
    assert_mentions_reachable(out["bundle"])
    return "participants: a company id mapped by every carrying upstream to one published company is public; unmapped, unknown, unpublished or upstream-disagreeing ids are null and the participant is kept"


# ---------------------------------------------------------------- structural paths: CLI check, closed-validator mutations ------------

def check_chain_export(world, bundle: dict, middle: str) -> None:
    """The chain world's export equals the hand-written expectation: published companies, private path companies, every edge's ordered path with directed links,
    the S3 scopes copied exactly, the unchanged edge id formula and the participants the bundle does not publish."""
    want = expected_chain(middle)
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8"
    assert [c["id"] for c in bundle["companies"]] == want["companies"] and bundle["pathCompanies"] == want["pathCompanies"], (middle, bundle["pathCompanies"])
    assert not {c["id"] for c in bundle["pathCompanies"]} & ({c["id"] for c in bundle["companies"]} | {i["id"] for i in bundle["issues"]})
    assert bundle["counts"]["companies"] == len(want["companies"]) and bundle["counts"]["pathCompanies"] == len(want["pathCompanies"]), bundle["counts"]
    assert bundle["counts"]["relations"]["STRUCTURALLY_RELATED_TO"] == len(want["paths"]) and bundle["digests"]["content"] == content_digest(bundle)
    structural = {r["target"]: r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO"}
    assert {target: r["structuralPath"] for target, r in structural.items()} == want["paths"], (middle, {t: r["structuralPath"] for t, r in structural.items()})
    assert all(r["structuralPath"] is None for r in bundle["relations"] if r["type"] != "STRUCTURALLY_RELATED_TO")
    links = {"KRX:000660": ONE_HOP[1], "KRX:000999": TWO_HOP[1]}
    scopes = {("SYNTH-3", "SYNTH-1"): (None, "배터리 부품"), ("SYNTH-4", "SYNTH-3"): ("소재 사업", "소재")}
    for target, r in structural.items():
        keys = [find(world.jobs["rel-a"], "SUPPLIES", s, c)["relationKey"] for s, c in links[target]]
        assert r["id"] == "edge-" + digest({"type": "STRUCTURALLY_RELATED_TO", "source": "issue:supply-2026q3", "target": target, "basis": keys}), "the edge id formula changed"
        assert [b["relationKey"] for b in r["basis"]] == keys and [(b["businessScope"], b["productScope"]) for b in r["basis"]] == [scopes[link] for link in links[target]]
    assert evidence_id(world, "a", CHAIN) in structural["KRX:000999"]["basis"][1]["evidenceIds"]
    supply = next(i for i in bundle["issues"] if i["id"] == "issue:supply-2026q3")
    supplier = {p["companyId"] for m in supply["mentions"] for p in m["participants"] if p["sourceCompanyId"] == "SYNTH-3"}
    assert supplier == {"KRX:000660" if middle == "known" else None}, "a private path company must never resolve a mention participant"


def path_mutations() -> dict:
    """name -> (the export it breaks, the one change, the validator location that must refuse it). The caller recomputes the content digest, so ONLY the structural-path
    or private-company rule can refuse the bundle. `private` has a two-relation edge over the unpublished SYNTH-3, `known` an extra one-relation edge, `unmapped` an unavailable path."""
    def edge(b, target):
        return next(r for r in b["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO" and r["target"] == target)

    two = lambda b: edge(b, "KRX:000999")                                       # noqa: E731
    path = lambda b: two(b)["structuralPath"]                                  # noqa: E731
    involves = lambda b: next(r for r in b["relations"] if r["type"] == "INVOLVES")   # noqa: E731

    def add_private(b, **change):
        b["pathCompanies"].append({"id": "KRX:000777", "canonicalId": "co:synth-7", "label": "합성미사용", "decisionRef": "catalog-2026-10-16:7", **change})
        b["counts"]["pathCompanies"] += 1

    def drop_private(b):
        b["pathCompanies"].clear()
        b["counts"]["pathCompanies"] = 0

    def also_public(b):
        b["companies"].append(dict(b["pathCompanies"][0]))
        b["counts"]["companies"] += 1

    def issue_named(b):
        b["pathCompanies"][0]["id"] = "issue:supply-2026q3"

    def reverse(b):
        path(b)["companyIds"].reverse()
        path(b)["links"].reverse()

    def set_link(b, n, **change):
        path(b)["links"][n].update(change)

    def set_chain(b, n, value):
        path(b)["companyIds"][n] = value

    def unavailable(b, **change):
        edge(b, "KRX:000660")["structuralPath"] = {"status": "unavailable", "reason": "intermediate_company_unmapped", **change}

    return {
        "an unused private company": ("private", add_private, "pathCompanies.closure"),
        "a complete two-relation path whose middle is in no catalogue": ("private", drop_private, "structuralPath.catalogue"),
        "a private company that is also public": ("private", also_public, "pathCompanies.unique"),
        "a private company with an issue id": ("private", issue_named, "issues.unique"),
        "a private company count that is wrong": ("private", lambda b: b["counts"].update(pathCompanies=0), "counts"),
        "an unavailable one-relation path": ("known", lambda b: unavailable(b), "structuralPath.unavailable"),
        "an unavailable path with another reason": ("unmapped", lambda b: path(b).update(reason="unknown"), "structuralPath.unavailable"),
        "an unavailable path that also lists companies": ("unmapped", lambda b: path(b).update(companyIds=["KRX:005930"]), "structuralPath"),
        "a complete path on an INVOLVES edge": ("private", lambda b: involves(b).update(structuralPath=json.loads(json.dumps(path(b)))), "relation.structuralPath"),
        "a structural edge without a path": ("private", lambda b: two(b).update(structuralPath=None), "structuralPath"),
        "a path with an unknown key": ("private", lambda b: path(b).update(causality="positive"), "structuralPath"),
        "a chain repeating a company": ("private", lambda b: set_chain(b, 1, path(b)["companyIds"][0]), "structuralPath.companyIds"),
        "a chain that does not start at an issue participant": ("private", reverse, "structuralPath.ends"),
        "a chain through a company of no catalogue": ("private", lambda b: set_chain(b, 1, "KRX:000555"), "structuralPath.catalogue"),
        "a link joining non-adjacent companies": ("private", lambda b: set_link(b, 1, supplierCompanyId="KRX:005930", customerCompanyId="KRX:000999"), "structuralPath.link"),
        "a link from a company to itself": ("private", lambda b: set_link(b, 0, customerCompanyId=path(b)["links"][0]["supplierCompanyId"]), "structuralPath.link"),
        "a missing link": ("private", lambda b: path(b).update(links=path(b)["links"][:1]), "structuralPath.links"),
        "links in the wrong order": ("private", lambda b: path(b)["links"].reverse(), "structuralPath.link"),
        "an oversized product scope": ("private", lambda b: two(b)["basis"][1].update(productScope="가" * 501), "basis.productScope.length"),
        "an oversized business scope": ("private", lambda b: two(b)["basis"][1].update(businessScope="가" * 501), "basis.businessScope.length"),
        "a scope that is not text": ("private", lambda b: two(b)["basis"][1].update(productScope=5), "basis.productScope"),
        "a basis without its scope keys": ("private", lambda b: two(b)["basis"][0].pop("businessScope"), "basis"),
    }


def structural_paths(root: Path) -> tuple[str, SimpleNamespace, dict]:
    """Structural paths through the installed CLI over a world whose rel-a also holds SYNTH-4 -> SYNTH-3 -> SYNTH-1: a PUBLISHED middle (`known`), a mapped but unpublished one
    (`private`: a private support company, never a public company) and one the operator did not map (`unmapped`: unavailable, never invented)."""
    world = build_world(root.parent / "chain", chain=True)
    operator = Operator(world)
    exports = {}
    for middle in ("known", "private", "unmapped"):
        exports[middle] = freeze_export(operator, world, f"path-{middle}-1", chain_decisions(world, middle))
        check_chain_export(world, exports[middle]["bundle"], middle)
    return ("structural paths: a one- and a two-relation edge name participant -> (middle ->) target with one directed link per basis and the S3 scopes; a mapped but unpublished middle "
            "is a private pathCompany (never a company, issue or mention participant), an unmapped middle makes the path unavailable (intermediate_company_unmapped), the edge id is unchanged"), world, exports


# ---------------------------------------------------------------- handoffs frozen under an earlier bundle schema ----------------------

BUNDLE_1 = "zoop-graph-handoff-bundle-1"           # before original mentions: no issue `mentions`, no `fieldProvenance`
BUNDLE_2 = "zoop-graph-handoff-bundle-2"           # before field provenance: `mentions`, no issue `fieldProvenance`
BUNDLE_3 = "zoop-graph-handoff-bundle-3"           # before field verdicts: `fieldProvenance` without `withheld`, no issue `fieldVerdicts`
BUNDLE_4 = "zoop-graph-handoff-bundle-4"           # before structural paths: no `pathCompanies`, `structuralPath` or basis scopes
BUNDLE_5 = "zoop-graph-handoff-bundle-5"           # before impacts: no `impacts`, `counts.impacts` or `policy.impacts`
BUNDLE_6 = "zoop-graph-handoff-bundle-6"           # before issue summaries: no issue `summary`, no `policy.issueSummary`
BUNDLE_7 = "zoop-graph-handoff-bundle-7"           # policy 1 requires nonempty source countries and supported original times
LEGACY_AT = "2026-10-15T00:00:00+00:00"
LEGACY_CODE = "handoff_contract_changed"


def legacy_bundle(bundle: dict, manifest: dict, schema: str) -> dict:
    """The bundle an earlier build froze for this manifest: today's export under that build's schema string, without what that build did not yet write. `-6` has no issue `summary`
    and no `policy.issueSummary` (its content digest already covered the seven collections); `-5` also has no top-level `impacts`, `counts.impacts` or `policy.impacts` (and its content
    digest does not cover them); `-4` has no top-level
    `pathCompanies`, no relation `structuralPath`, no basis `businessScope`/`productScope` and no `counts.pathCompanies`; `-3` also has no issue `fieldVerdicts` and no
    `fieldProvenance.withheld`; `-2` has no `fieldProvenance` either; `-1` has none of them nor the issues' `mentions`. The content digest is recomputed over the earlier
    collections (its formula never included `pathCompanies`)."""
    assert schema in (BUNDLE_1, BUNDLE_2, BUNDLE_3, BUNDLE_4, BUNDLE_5, BUNDLE_6, BUNDLE_7), schema
    old = json.loads(json.dumps(bundle))
    old["policy"]["version"] = "zoop-public-projection-policy-1"
    for issue in old["issues"]:
        assert all(b["countries"] == issue["geography"]["countries"] for b in issue["geography"]["basis"])
        assert all(m["timePrecision"] != "unresolved" for m in issue["mentions"])
        assert all(v["reasonCode"] != "unsupported-format" for v in issue["fieldVerdicts"])
        issue["geography"]["policyVersion"] = "zoop-public-projection-policy-1"
    if schema == BUNDLE_7:
        old.update(schemaVersion=schema, handoffId=manifest["handoffId"], manifestDigest=digest(manifest))
        old["digests"]["content"] = content_digest(old)
        return old
    for issue in old["issues"]:
        del issue["summary"]                                                        # `-7` added the closed per-issue summary and its policy literal
    del old["policy"]["issueSummary"]
    if schema == BUNDLE_6:
        old.update(schemaVersion=schema, handoffId=manifest["handoffId"], manifestDigest=digest(manifest))
        old["digests"]["content"] = content_digest(old)
        return old
    del old["impacts"], old["counts"]["impacts"], old["policy"]["impacts"]          # `-6` added the receipt-only impact rows, their count and policy literal
    if schema == BUNDLE_5:
        old.update(schemaVersion=schema, handoffId=manifest["handoffId"], manifestDigest=digest(manifest))
        old["digests"]["content"] = digest({key: old[key] for key in ("companies", "pathCompanies", "issues", "relations", "evidence", "articles")})
        return old
    assert not old["pathCompanies"], "an earlier schema cannot carry a private path company"
    del old["pathCompanies"], old["counts"]["pathCompanies"]
    for relation in old["relations"]:
        del relation["structuralPath"]
        for basis in relation["basis"]:
            del basis["businessScope"], basis["productScope"]
    for issue in old["issues"]:
        assert not issue["fieldVerdicts"] and not issue["fieldProvenance"]["withheld"], "an earlier schema cannot carry a verdict or a withheld field"
        if schema == BUNDLE_4:
            continue
        del issue["fieldVerdicts"]
        if schema == BUNDLE_3:
            del issue["fieldProvenance"]["withheld"]
        else:
            del issue["fieldProvenance"]
        if schema == BUNDLE_1:
            del issue["mentions"]
    old.update(schemaVersion=schema, handoffId=manifest["handoffId"], manifestDigest=digest(manifest))
    old["digests"]["content"] = digest({key: old[key] for key in ("companies", "issues", "relations", "evidence", "articles")})
    return old


KILLED_WRITER = ("import json, os, sqlite3, sys\n"
                 "spec = json.load(sys.stdin)\n"
                 "db = sqlite3.connect(spec['database'], isolation_level=None)\n"
                 "db.execute('BEGIN IMMEDIATE')\n"
                 "for statement, args in spec['statements']:\n"
                 "    db.execute(statement, args)\n"
                 "db.execute('COMMIT')\n"
                 "os._exit(9)\n")          # no close, no checkpoint: the committed rows stay ONLY in the write-ahead log


def plant_legacy_handoff(state: Path, manifest: dict, bundle: dict, *, row_state: str = "ready", artifact: str = "written", schema: str = BUNDLE_2,
                         damaged: bool = False, wal: bool = False) -> dict:
    """Adds ONE row of an earlier build (`schema`: `BUNDLE_1` to `BUNDLE_4`, see `legacy_bundle`) to an existing handoff ledger with the ledger's own INSERT statements
    (schema, triggers and every other row stay as they are). `artifact`: `written` (the earlier bundle's exact bytes), `missing` or `garbage` (a file that is no bundle at
    all: the row must never be judged by it); `damaged` leaves the receipt without a bundle schema (damaged state, not history). `wal`: the rows are committed by a
    writer process that dies without closing the ledger, so they exist ONLY in a non-empty `handoff.sqlite3-wal` (a stale `-shm` stays beside it), exactly what a killed
    pre-cutover writer leaves behind."""
    import hashlib
    import sqlite3
    manifest = {**manifest, "policyVersion": "zoop-public-projection-policy-1"}
    old = legacy_bundle(bundle, manifest, schema)
    raw = canonical(old).encode("utf-8")
    bundle_digest = hashlib.sha256(raw).hexdigest()
    receipt = {"handoffId": manifest["handoffId"], "manifestDigest": digest(manifest), "bundleSchema": schema, "bundleDigest": bundle_digest,
               "contentDigest": old["digests"]["content"], "bundleBytes": len(raw), "provenance": old["provenance"],
               "sources": [{"relation": s["relation"], "upstream": s["upstream"], "reviewDigest": s["reviewDigest"]} for s in old["sources"]],
               "files": manifest["files"], "counts": old["counts"], "exclusionCodes": old["exclusions"]["counts"], "checks": old["checks"], "frozenAt": LEGACY_AT}
    if damaged:
        del receipt["bundleSchema"]
    failure = "handoff_artifact_missing" if row_state == "failed" else None
    attempts = {"reserved": [], "ready": [(1, "freeze", "written", None)], "failed": [(1, "recover", "artifact-missing", failure)]}[row_state]
    statements = [("INSERT INTO handoffs(handoff_id,input_digest,manifest,bundle_digest,content_digest,bundle_bytes,receipt,state,failure,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?)", [manifest["handoffId"], digest(manifest), canonical(manifest), bundle_digest, old["digests"]["content"], len(raw),
                                                     canonical(receipt), row_state, failure, LEGACY_AT, LEGACY_AT])]
    statements += [("INSERT INTO attempts VALUES(?,?,?,?,?,?)", [manifest["handoffId"], n, kind, outcome, code, LEGACY_AT]) for n, kind, outcome, code in attempts]
    if wal:
        child = subprocess.run([sys.executable, "-c", KILLED_WRITER], input=json_bytes({"database": str(state / "handoff.sqlite3"), "statements": statements}),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        assert child.returncode == 9 and not child.stderr, (child.returncode, child.stderr.decode()[-1000:])
        assert (state / "handoff.sqlite3-wal").stat().st_size > 0, "the killed writer left no write-ahead log"
    else:
        db = sqlite3.connect(state / "handoff.sqlite3")
        try:
            for statement, args in statements:
                db.execute(statement, args)
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            db.close()
    path = state / "bundles" / f"{bundle_digest}.json"
    if artifact != "missing":
        path.write_bytes(raw if artifact == "written" else b"{this is not a bundle")
    return {"receipt": receipt, "artifact": path, "state": row_state, "attempts": [{"n": n, "kind": k, "outcome": o, "code": c} for n, k, o, c in attempts], "failure": failure}


def ledger_snapshot(state: Path) -> dict:
    """Everything a handoff ledger directory holds: mode, mtime, size and content hash of every file and directory."""
    import hashlib
    found = {}
    for path in [state, *sorted(state.rglob("*"))]:
        info = path.stat()
        found[str(path.relative_to(state))] = (stat.S_IMODE(info.st_mode), info.st_mtime_ns,
                                               None if path.is_dir() else (info.st_size, hashlib.sha256(path.read_bytes()).hexdigest()))
    return found


def legacy_history(world, exported: dict) -> tuple[str, dict]:
    """Rows frozen by an earlier build (bundle `-4`, before structural paths, `-3`, before field verdicts, `-2`, before field provenance, and `-1`, before original mentions) are immutable HISTORY through
    the installed CLI. The ledger is a real current one into which three `-2` rows are planted (ready with its bundle, reserved without its file, failed with a garbage file),
    one `-1` ready row, a `-3` ready and reserved row and a `-4` ready, reserved and failed row, and which a writer would visibly re-permission: every command below answers from the ledger alone (the source ledgers, grant registry and operator files
    do not even exist for it) and leaves every byte, mode, mtime and file as it was, while a NEW handoff id in the same ledger still freezes and exports and the history
    stays as it was. Returns the check text and the real withheld envelope of the ready `-2` row."""
    operator = Operator(world)
    state = world.root / "handoff-legacy"
    files = file_hashes(world.root)
    operator.cli("freeze", manifest_doc(world, "current-0", files), state=state)
    planted = {name: plant_legacy_handoff(state, manifest_doc(world, name, files), exported["bundle"], row_state=row_state, artifact=artifact, schema=schema)
               for name, schema, row_state, artifact in (("legacy-ready", BUNDLE_2, "ready", "written"), ("legacy-reserved", BUNDLE_2, "reserved", "missing"),
                                                         ("legacy-failed", BUNDLE_2, "failed", "garbage"), ("legacy-ready-1", BUNDLE_1, "ready", "written"),
                                                         ("legacy-ready-3", BUNDLE_3, "ready", "written"), ("legacy-reserved-3", BUNDLE_3, "reserved", "missing"),
                                                         ("legacy-ready-4", BUNDLE_4, "ready", "written"), ("legacy-reserved-4", BUNDLE_4, "reserved", "missing"),
                                                         ("legacy-failed-4", BUNDLE_4, "failed", "garbage"), ("legacy-ready-5", BUNDLE_5, "ready", "written"),
                                                         ("legacy-reserved-5", BUNDLE_5, "reserved", "missing"), ("legacy-ready-6", BUNDLE_6, "ready", "written"),
                                                         ("legacy-reserved-6", BUNDLE_6, "reserved", "missing"))}
    assert {row["receipt"]["bundleSchema"] for row in planted.values()} == {BUNDLE_1, BUNDLE_2, BUNDLE_3, BUNDLE_4, BUNDLE_5, BUNDLE_6}
    os.chmod(state, 0o755)
    for path in (state / "bundles", *(state / "bundles").iterdir(), state / "handoff.sqlite3", state / "handoff.lock"):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    before, artifacts = ledger_snapshot(state), {n: (p["artifact"].read_bytes() if p["artifact"].exists() else None) for n, p in planted.items()}
    withheld = None
    for name, row in planted.items():
        seen = operator.cli("inspect", operator.sel(name), expected=2, state=state)
        assert seen["state"] == row["state"] and seen["next"] is None and seen["delivery"] == {"status": "withheld", "code": LEGACY_CODE}, seen
        assert seen["receipt"] == row["receipt"] and seen["attempts"] == row["attempts"] and seen["failure"] == ({"code": row["failure"]} if row["failure"] else None), seen
        gone = operator.cli("export", operator.sel(name), expected=2, state=state, absent=True)
        assert gone == {"schemaVersion": "zoop-ai-handoff-1", "handoffId": name, "state": row["state"], "publication": "not-published",
                        "delivery": {"status": "withheld", "code": LEGACY_CODE}, "usage": {"providerCalls": 0, "modelCalls": 0}}, gone
        assert operator.cli("recover", operator.sel(name), expected=2, state=state)["error"]["code"] == LEGACY_CODE
        for manifest in (manifest_doc(world, name, files), {**manifest_doc(world, name, files), "sourceKind": "actual"}):
            assert operator.cli("freeze", manifest, expected=2, state=state, absent=True)["error"]["code"] == LEGACY_CODE
        withheld = gone if name == "legacy-ready" else withheld
    assert ledger_snapshot(state) == before, "a legacy command changed the ledger directory"
    operator.cli("freeze", manifest_doc(world, "current-1", files), state=state)
    assert operator.cli("export", operator.sel("current-1"), state=state)["delivery"]["status"] == "current"
    assert {n: (p["artifact"].read_bytes() if p["artifact"].exists() else None) for n, p in planted.items()} == artifacts
    for name, row in planted.items():
        seen = operator.cli("inspect", operator.sel(name), expected=2, state=state)
        assert seen["receipt"] == row["receipt"] and seen["attempts"] == row["attempts"] and seen["state"] == row["state"], seen
    return ("earlier-schema history (`-6`, `-5`, `-4` and `-3` ready/reserved rows, `-2` ready/reserved/failed rows and a `-1` ready row): inspect shows the stored receipt and attempts (next null, withheld handoff_contract_changed), "
            "export is withheld, recover and a same-id freeze are refused, all from the ledger alone with no source/operator file/artifact read; bytes, modes and mtimes unchanged; "
            "a new handoff id still freezes and exports"), withheld


def issue_exclusions(bundle: dict, canonical_id: str) -> list:
    return [i for i in bundle["exclusions"]["items"] if i["kind"] == "issue" and i["id"] == canonical_id]


def freeze_export(operator: Operator, world, handoff_id: str, decisions: dict) -> dict:
    """Writes the operator's decisions file, freezes a NEW handoff over it and exports it (current)."""
    write_operator(world, decisions=decisions)
    operator.cli("freeze", manifest_doc(world, handoff_id, file_hashes(world.root)))
    out = operator.cli("export", operator.sel(handoff_id))
    assert out["delivery"]["status"] == "current" and out["state"] == "ready", (handoff_id, out["delivery"])
    return out


def reviewed(world, *, cases: dict | None = None, **options) -> dict:
    return decisions_doc(world, verdicts=json.loads(json.dumps(verdict_cases(world) if cases is None else cases)), **options)


def invalid_review_files(operator: Operator, world) -> str:
    """A malformed operator file is refused WHOLE (`decisions_invalid`, nothing frozen): a duplicate (mention, field), a decision/reason pair that does not exist, a span
    count that does not fit the decision, a free-text note, a null or unknown field, a missing or oversized verdict list and a file of the earlier decisions schema."""
    long_spans = [span(world, "a", EVT_A[:n]) for n in range(3, 24)]

    def variants():
        yield "duplicate", lambda v: v.append(json.loads(json.dumps(v[1])))
        yield "allow-without-span", lambda v: v[1].update(evidence=[])
        yield "unstated-with-span", lambda v: v[2].update(evidence=[span(world, "a2", PERIOD_A2)])
        yield "reject-stated", lambda v: v[0].update(reasonCode="stated")
        yield "hold-ambiguous-without-span", lambda v: v.append(field_verdict(world, "b", "m-b", "eventTime", "2026-11-15", "HOLD", "ambiguous"))
        yield "free-text-note", lambda v: v[0].update(note="private review note")
        yield "null-value", lambda v: v[0].update(value=None)
        yield "title-field", lambda v: v[0].update(field="title")
        yield "too-many-spans", lambda v: v[1].update(evidence=long_spans)
        yield "lowercase-decision", lambda v: v[1].update(decision="allow")

    for name, change in variants():
        doc = reviewed(world)
        change(doc["issues"][0]["fieldVerdicts"])
        write_operator(world, decisions=doc)
        assert operator.cli("freeze", manifest_doc(world, f"invalid-{name}", file_hashes(world.root)), expected=2)["error"]["code"] == "decisions_invalid", name
        assert operator.cli("inspect", operator.sel(f"invalid-{name}"), expected=2)["error"]["code"] == "handoff_not_found", name
    missing = reviewed(world)
    del missing["issues"][0]["fieldVerdicts"]
    old = reviewed(world)
    old["schemaVersion"] = "zoop-public-decisions-1"
    for issue in old["issues"]:
        del issue["fieldVerdicts"]
    before_summaries = reviewed(world)                       # the earlier decisions schema (-2): the same file without the per-issue `summary` pin
    before_summaries["schemaVersion"] = "zoop-public-decisions-2"
    for issue in before_summaries["issues"]:
        del issue["summary"]
    no_pin_key = reviewed(world)
    del no_pin_key["issues"][0]["summary"]
    for name, doc in (("missing-list", missing), ("earlier-schema", old), ("decisions-2", before_summaries), ("missing-summary-pin", no_pin_key)):
        write_operator(world, decisions=doc)
        assert operator.cli("freeze", manifest_doc(world, f"invalid-{name}", file_hashes(world.root)), expected=2)["error"]["code"] == "decisions_invalid", name
    return "malformed review files are refused whole (decisions_invalid, nothing frozen): duplicate (mention, field), ALLOW without a span, HOLD/unstated with a span, REJECT/stated, HOLD/ambiguous without a span, free-text note, null value, unjudgeable field, 21 spans, lowercase decision, missing verdict list, earlier decisions schemas (-1 and -2), missing summary pin key"


def unbindable_reviews(operator: Operator, world) -> str:
    """A well-formed verdict that cannot be bound to this issue's original mention and exact text excludes ONLY that issue, visibly (code and id), never the bundle and
    never silently: a stale value, a mention outside the issue, a span of another document, a tampered quote hash, a shifted span and a span past the text. The other
    issue keeps its own verdict and its withheld headline."""
    def change(entry_index: int, **fields):
        return lambda v: v[entry_index].update(**fields)

    def shifted(v):
        s = v[1]["evidence"][0]
        s.update(start=s["start"] + 1, end=s["end"] + 1)

    cases = (("stale", "field_verdict_stale", change(3, value="2026-10-01")),
             ("misbound", "field_verdict_unbound", lambda v: v.append(field_verdict(world, "b", "m-b", "period", "2026Q4", "ALLOW", "stated", [PERIOD_B]))),
             ("unknown-mention", "field_verdict_unbound", change(3, mentionId="m-zzz")),
             ("foreign-document-span", "field_verdict_evidence_unbound", change(1, evidence=[span(world, "b", PERIOD_B)])),
             ("tampered-quote-hash", "field_verdict_evidence_mismatch", lambda v: v[1]["evidence"][0].update(quoteSha256="0" * 64)),
             ("shifted-span", "field_verdict_evidence_mismatch", shifted),
             ("span-past-text", "field_verdict_evidence_mismatch", lambda v: v[1]["evidence"][0].update(end=10_000)))
    for name, code, mutate in cases:
        doc = reviewed(world)
        mutate(doc["issues"][0]["fieldVerdicts"])
        out = freeze_export(operator, world, f"unbindable-{name}", doc)
        bundle = out["bundle"]
        assert issue_exclusions(bundle, "issue:supply") == [{"kind": "issue", "id": "issue:supply", "jobId": None, "code": code}], (name, issue_exclusions(bundle, "issue:supply"))
        assert [i["id"] for i in bundle["issues"]] == ["issue:factory-2026q4"], name
        assert bundle["issues"][0]["fieldVerdicts"] == expected_verdicts(world, verdict_cases(world))["issue:factory-2026q4"], name
        assert bundle["issues"][0]["fieldProvenance"]["withheld"] == ["period"] and bundle["issues"][0]["period"] is None, name
    return ("unbindable reviews exclude only their issue, visibly: stale value (field_verdict_stale), mention outside the issue or unknown (field_verdict_unbound), span of another document "
            "(field_verdict_evidence_unbound), tampered hash / shifted / past-the-text span (field_verdict_evidence_mismatch); the other issue keeps its verdict and its withheld period")


VERDICT_HANDOFF = "handoff-verdicts-1"
VERDICT_WITHHELD = {"issue:supply-2026q3": ["eventTime"], "issue:factory-2026q4": ["period"]}       # the headline fields `verdict_cases` withholds


def verdict_export(root: Path, public_ids: dict | None = None) -> tuple[SimpleNamespace, dict]:
    """The real export (handoff `handoff-verdicts-1`) of the HAND-REVIEWED world through the installed CLI, checked against hand-written expectations. Supply (representative:
    document a's `m-a`): the representative's event time is REJECT/contradicted -> the headline time is withheld (null, precision `unknown`; the original mention time stays) and,
    because the operator re-attested the structural relation against that withheld time, the structural edge is still exported; its period is ALLOW; the NON-representative second
    document has a HOLD/unstated time (no span) and a REJECT/contradicted period that withhold nothing. Factory (one mention, unanimous): HOLD/ambiguous period citing a span no
    mention cites -> the headline period is withheld and the issue's evidence is the union with the verdict's. A SYNTHETIC test review, not a real one. `public_ids` maps the
    authored public company ids to an importer smoke's own catalog."""
    world = build_world(root)
    cases = verdict_cases(world)
    decisions = reviewed(world, published_time=None)
    for company in decisions["companies"]:
        company["publicId"] = (public_ids or {}).get(company["publicId"], company["publicId"])
    out = freeze_export(Operator(world), world, VERDICT_HANDOFF, decisions)
    bundle = out["bundle"]
    ids = {name: evidence_id(world, name, quote) for name, quote in (("a", PERIOD_A), ("a2", PERIOD_A2), ("b", PERIOD_B))}
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8" and bundle["handoffId"] == VERDICT_HANDOFF
    assert {i["id"]: i["fieldVerdicts"] for i in bundle["issues"]} == expected_verdicts(world, cases)
    assert {i["id"]: i["fieldProvenance"] for i in bundle["issues"]} == expected_field_provenance(world, VERDICT_WITHHELD)
    assert {i["id"]: i["mentions"] for i in bundle["issues"]} == expected_mentions(world, public_ids), "an original mention value was changed by a verdict"
    assert {i["id"]: (i["eventTime"], i["timePrecision"], i["period"]) for i in bundle["issues"]} == expected_headlines(world, VERDICT_WITHHELD)
    assert {i["id"]: i["evidenceIds"] for i in bundle["issues"]} == {
        "issue:supply-2026q3": sorted({*expected(world)["issues"]["issue:supply-2026q3"]["evidenceIds"], ids["a"], ids["a2"]}),
        "issue:factory-2026q4": sorted({*expected(world)["issues"]["issue:factory-2026q4"]["evidenceIds"], ids["b"]})}
    assert {(r["type"], r["source"], r["target"]): r["evidenceIds"] for r in bundle["relations"]} == expected(world, public_ids)["relations"]
    assert bundle["counts"]["evidence"] == 9 and bundle["exclusions"]["counts"] == expected(world)["exclusions"], bundle["counts"]
    assert_field_provenance_closed(bundle)
    assert_mentions_reachable(bundle)
    dumped = json.dumps(out, ensure_ascii=False)
    assert all(text not in dumped for text in (*PRIVATE, PERIOD_A, PERIOD_A2, PERIOD_B)), "reviewed source text or a review note leaked"
    return world, out


APPROVED_HANDOFF = "handoff-approved-1"


def approved_export(root: Path, public_ids: dict | None = None) -> tuple[SimpleNamespace, dict]:
    """The real export (handoff `handoff-approved-1`) of the `approve` world through the installed CLI, checked against hand-written expectations. The authored independent
    verifier HELD rel-a's SUPPLIES basis and rel-b's participation in `event-a`; the operator FINALLY approved exactly those two (revision 2, effect `approved`, no call). So the
    bundle is MIXED in approval: the factory INVOLVES edge is purely automatic, the supply INVOLVES edge has an automatic and a manual contributor (it must NOT claim the
    independent verifier supported all claims) and the structural edge rests on a manual basis. Documents a and a2 (different texts) declare ONE origin (one lineage group, independent
    count 1: articleCount 2 > knownLineageCount 1 > 0), b declares none (unknown, independent count null). A SYNTHETIC test world, not a real review. `public_ids` maps the authored
    public company ids to an importer smoke's own catalog."""
    world = build_world(root, approve=True)
    decisions = decisions_doc(world)
    for company in decisions["companies"]:
        company["publicId"] = (public_ids or {}).get(company["publicId"], company["publicId"])
    out = freeze_export(Operator(world), world, APPROVED_HANDOFF, decisions)
    bundle = out["bundle"]
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8" and bundle["handoffId"] == APPROVED_HANDOFF
    check_export(world, out, public_ids)
    kinds = sorted(u["approvalBasis"]["kind"] for s in bundle["sources"] for u in s["reviewUsed"])
    assert kinds == ["automatic-verifier", "automatic-verifier", "operator-final-approval", "operator-final-approval"], kinds
    dumped = json.dumps(out, ensure_ascii=False)
    assert all(text not in dumped for text in PRIVATE), "source text or an S3 review note leaked"
    return world, out

IMPACT_HANDOFF = "handoff-impacts-1"
RICH_STATUSES = [("verified", None), ("verifier-reject", None), ("verified", None), ("verified", None), ("no-evidence", None), ("technical-reject", "impact_precheck_rejected")]


def impact_export(root: Path, public_ids: dict | None = None) -> tuple[SimpleNamespace, dict]:
    """The real export (handoff `handoff-impacts-1`) of the `rich` impact world through the installed CLI, checked against the hand-written rows: on the supply edge a verified POSITIVE
    (own sentence + an impact-only sentence of document a), a verifier-rejected (target contradicted), a verified NEGATIVE of the other S3 job and a verified-but-undetermined (target
    insufficient) row, all four kept apart; on the factory edge a `no-evidence` row (label null) and a precheck-rejected technical reject. The invented off-target company is never exported.
    The verifier here is an AUTHORED replay, not an independent inference. A SYNTHETIC world."""
    world = build_world(root, impact="rich")
    decisions = decisions_doc(world)
    for company in decisions["companies"]:
        company["publicId"] = (public_ids or {}).get(company["publicId"], company["publicId"])
    out = freeze_export(Operator(world), world, IMPACT_HANDOFF, decisions)
    bundle = out["bundle"]
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8" and bundle["handoffId"] == IMPACT_HANDOFF
    check_export(world, out, public_ids)
    assert sorted(((r["status"], r["code"]) for r in bundle["impacts"]), key=repr) == sorted(RICH_STATUSES, key=repr), [(r["status"], r["code"]) for r in bundle["impacts"]]
    assert len({r["edgeId"] for r in bundle["impacts"] if r["issueId"] == "issue:supply-2026q3"}) == 1 and sum(r["issueId"] == "issue:supply-2026q3" for r in bundle["impacts"]) == 4
    assert all(r["label"] is None for r in bundle["impacts"] if r["status"] != "verified") and bundle["counts"]["impacts"] == 6
    dumped = json.dumps(out, ensure_ascii=False)
    assert all(text not in dumped for text in PRIVATE), "source text or an S3 review note leaked"
    return world, out


def impact_mutations() -> dict:
    """name -> (the one change to the `rich` export bundle, the validator location that must refuse it, whether the content digest is recomputed). Every change breaks ONE rule of the
    closed impact rows (or their counts/policy/digest); the digest is refreshed so that only that rule can refuse it, except the one case about the digest itself."""
    import copy

    def pick(b, status, code=None, nth=0):
        return [r for r in b["impacts"] if r["status"] == status and r["code"] == code][nth]

    def count(b):
        b["counts"]["impacts"] = len(b["impacts"])

    def missing(b):
        b["impacts"].pop(0)
        count(b)

    def extra(b):
        b["impacts"].append({**copy.deepcopy(b["impacts"][0]), "edgeId": "edge-" + "0" * 64, "impactCandidateId": "ic-" + "9" * 64})
        count(b)

    def structural(b):
        pick(b, "no-evidence")["edgeId"] = next(r["id"] for r in b["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")

    def duplicate(b):
        b["impacts"].append(copy.deepcopy(b["impacts"][-1]))
        count(b)

    def forged_not_applicable(b):
        pick(b, "verifier-reject").update(status="not-applicable", impactCandidateId=None, verifier="not-called", verifierRequestDigest=None, proposal=None, targetVerdict=None)

    def forged_manual(b):
        row = pick(b, "verified")
        source = next(s for s in b["sources"] if s["relation"]["jobId"] == row["sourceRelation"]["jobId"])
        used = next(u for u in source["reviewUsed"] if u["relationCandidateId"] == row["sourceRelation"]["relationCandidateId"])
        used["approvalBasis"].update(kind="operator-final-approval", reviewer="forged-reviewer")
        for relation in b["relations"]:
            if relation["id"] == row["edgeId"]:
                relation["provenance"]["s3SemanticValidation"] = "manual-operator-final-approval"

    def other_article(b):
        evidence = {e["id"]: e for e in b["evidence"]}
        row = next(r for r in b["impacts"] if r["status"] == "verified")
        edge = next(r for r in b["relations"] if r["id"] == row["edgeId"])
        own = {evidence[x]["articleId"] for x in edge["evidenceIds"]}
        foreign = next(i for i, e in evidence.items() if e["articleId"] not in own)
        row["effects"]["uncertain"] = [foreign]
        row["label"] = "undetermined"          # the label the rules yield for an uncertain effect, so only the article rule can refuse this row

    def both_sides(b):
        row = next(r for r in b["impacts"] if r["status"] == "verified" and r["effects"]["positive"])
        row["effects"]["negative"] = list(row["effects"]["positive"])

    def source_evidence_twice(b):
        row = pick(b, "verified")
        evidence = {e["id"]: e for e in b["evidence"]}
        twin = copy.deepcopy(evidence[next(x for side in ("positive", "negative", "neutral", "uncertain") for x in row["effects"][side])])
        twin.update(start=twin["start"] + 1, end=twin["end"] + 1)
        twin["id"] = app_evidence_id(twin["articleId"], twin["articleVersion"], twin["start"], twin["end"])
        b["evidence"] = sorted([*b["evidence"], twin], key=lambda e: e["id"])
        b["counts"]["evidence"] += 1
        row["effects"]["uncertain"] = [twin["id"]]
        row["label"] = "undetermined"

    def live_invalid(b):
        b["provenance"].update(executionMode="live", recordingKind="provider")
        for s in b["sources"]:
            s["provenance"].update(executionMode="live", recordingKind="provider")
        pick(b, "verifier-reject").update(status="technical-reject", code="verifier_reply_invalid", targetVerdict=None)

    def unsorted_side(b):
        row = next(r for r in b["impacts"] if r["status"] == "verified" and r["effects"]["positive"])
        side = "positive"
        row["effects"][side] = [*row["effects"][side], *row["effects"][side]]

    def insufficient_positive(b):
        next(r for r in b["impacts"] if r["targetVerdict"] == "insufficient").update(label="positive")

    def shared_candidate(b):
        reject = pick(b, "verifier-reject")
        reject["impactCandidateId"] = next(r for r in b["impacts"] if r["status"] == "verified" and r["sourceRelation"]["jobId"] == reject["sourceRelation"]["jobId"])["impactCandidateId"]

    return {
        "a missing impact row": (missing, "impacts.coverage", True),
        "a duplicated impact row": (duplicate, "impacts.impactCandidateId.unique", True),
        "an extra row on no INVOLVES edge": (extra, "impacts.edgeClosure", True),
        "a row pointing at the STRUCTURAL edge": (structural, "impacts.edgeClosure", True),
        "a row whose company is not the edge target": (lambda b: pick(b, "no-evidence").update(companyId="KRX:000660"), "impacts.endpoints", True),
        "rows out of order": (lambda b: b["impacts"].reverse(), "impacts.coverage", True),
        "a source relation of no emitted edge": (lambda b: pick(b, "no-evidence")["sourceRelation"].update(relationCandidateId="rc-" + "0" * 64), "impacts.sourceClosure", True),
        "not-applicable on an automatic relation": (forged_not_applicable, "impacts.approval", True),
        "a verified row forged on an operator-approved relation": (forged_manual, "impacts.approval", True),
        "a label that does not follow from the effects (mixed)": (lambda b: pick(b, "verified").update(label="mixed"), "impacts.label", True),
        "a positive label although the verdict is insufficient": (insufficient_positive, "impacts.label", True),
        "a verified row without effects": (lambda b: pick(b, "verified").update(effects={"positive": [], "negative": [], "neutral": [], "uncertain": []}), "impacts.effects.union", True),
        "an effect id outside the bundle evidence": (lambda b: pick(b, "verified")["effects"].update(neutral=["ev-" + "1" * 64]), "impacts.effects.neutral", True),
        "one id on two sides": (both_sides, "impacts.effects.union", True),
        "an effect side with a duplicate id": (unsorted_side, "impacts.effects.positive", True),
        "an effect on another article version than the edge's": (other_article, "impacts.effects.articleClosure", True),
        "two effects of one row with the same source evidence": (source_evidence_twice, "impacts.effects.sourceEvidenceId", True),
        "verified with the verdict contradicted": (lambda b: pick(b, "verified").update(targetVerdict="contradicted"), "impacts.targetVerdict", True),
        "a verifier-reject without the contradicted verdict": (lambda b: pick(b, "verifier-reject").update(targetVerdict="supported"), "impacts.targetVerdict", True),
        "no-evidence carrying a label": (lambda b: pick(b, "no-evidence").update(label="undetermined"), "impacts.verifiedOnly", True),
        "no-evidence with the verifier called": (lambda b: pick(b, "no-evidence").update(verifier="called", verifierRequestDigest="a" * 64), "impacts.state", True),
        "a called verifier without a request digest": (lambda b: pick(b, "verifier-reject").update(verifierRequestDigest=None), "impacts.verifierRequestDigest", True),
        "verifier_reply_invalid in a live bundle": (live_invalid, "impacts.code.replayOnly", True),
        "a technical reject with an unknown code": (lambda b: pick(b, "technical-reject", "impact_precheck_rejected").update(code="reply_broken"), "impacts.code", True),
        "a precheck-rejected row carrying a proposal": (lambda b: pick(b, "technical-reject", "impact_precheck_rejected").update(
            proposal={"direction": "negative", "reason": "r", "limitations": None, "verification": "none"}), "impacts.state", True),
        "a withheld row carrying a label": (lambda b: pick(b, "verifier-reject").update(status="withheld", code="impact_quote_ambiguous", targetVerdict=None, label="positive"),
                                            "impacts.verifiedOnly", True),
        "a proposal that claims verification": (lambda b: pick(b, "verified")["proposal"].update(verification="verified"), "impacts.proposal.verification", True),
        "a proposal reason over 2000 code points": (lambda b: pick(b, "verified")["proposal"].update(reason="x" * 2001), "impacts.proposal.reason.length", True),
        "a malformed impact candidate id": (lambda b: pick(b, "verified").update(impactCandidateId="ic-" + "g" * 64), "impacts.impactCandidateId", True),
        "one impact candidate on two rows of a job": (shared_candidate, "impacts.impactCandidateId.unique", True),
        "a row with another key": (lambda b: pick(b, "verified").update(note="x"), "impacts", True),
        "a row without a key": (lambda b: pick(b, "verified").pop("label"), "impacts", True),
        "an impact count that is wrong": (lambda b: b["counts"].update(impacts=1), "counts", True),
        "another impact policy": (lambda b: b["policy"].update(impacts="s3-model-label"), "policy.impacts", True),
        "edited impact rows under the old content digest": (lambda b: pick(b, "verified")["proposal"].update(reason="edited"), "digests.content", False),
    }



def unicode_impact_rows(rows: list) -> list:
    """The hand-authored expected rows of `unicode_impact_bundle`: the first verified row (bundle order = expected order) carries the 2000/1000 code-point proposal."""
    copy = json.loads(json.dumps(rows))
    next(r for r in copy if r["status"] == "verified")["proposal"].update(reason="😀" * 2000, limitations="😀" * 1000)
    return copy


def unicode_impact_envelope(out: dict) -> dict:
    """The export envelope of `unicode_impact_bundle` with the receipt resealed to the new bundle (content digest, artifact bytes and their digest), never the old receipt."""
    import hashlib
    bundle = unicode_impact_bundle(out["bundle"])
    raw = canonical(bundle).encode("utf-8")
    receipt = {**out["receipt"], "contentDigest": bundle["digests"]["content"], "bundleDigest": hashlib.sha256(raw).hexdigest(), "bundleBytes": len(raw)}
    return {**out, "bundle": bundle, "receipt": receipt}

def unicode_impact_bundle(bundle: dict) -> dict:
    """A VALID copy of the `rich` bundle whose first verified proposal states 2000 reason and 1000 limitation code points of astral characters (4000 and 2000 UTF-16 units): the lengths
    are Unicode code points, never UTF-16 units. The content digest is recomputed."""
    copy = json.loads(json.dumps(bundle))
    row = next(r for r in copy["impacts"] if r["status"] == "verified")
    row["proposal"].update(reason="😀" * 2000, limitations="😀" * 1000)
    copy["digests"]["content"] = content_digest(copy)
    return copy



def expected_headlines(world, withheld: dict | None = None) -> dict:
    """Hand-written public `(eventTime, timePrecision, period)` of each public issue of the authored world: the supply issue's representative states 2026-09-30 / 2026Q3, the
    factory's only mention 2026-11-15 / 2026Q4; a withheld event time is `(None, "unknown")`, a withheld period `None`."""
    withheld = withheld or {}
    supply, factory = withheld.get("issue:supply-2026q3", []), withheld.get("issue:factory-2026q4", [])
    return {"issue:supply-2026q3": (None if "eventTime" in supply else "2026-09-30", "unknown" if "eventTime" in supply else "day", None if "period" in supply else "2026Q3"),
            "issue:factory-2026q4": (None if "eventTime" in factory else "2026-11-15", "unknown" if "eventTime" in factory else "day", None if "period" in factory else "2026Q4")}


def field_verdicts(root: Path) -> tuple[list, SimpleNamespace]:
    """Operator per-field verdicts through the installed CLI, expectations hand-written. A verdict is an OPERATOR review of one original mention's `eventTime`/`period` (S2/S3
    verify neither). ALLOW keeps the value; HOLD/REJECT on the SELECTION BASIS (the representative's mention, or any mention when unanimous) withholds the issue headline
    (null; an event time's precision `unknown`), with no fallback to another mention, while the original mention values and the verdict stay in the bundle; a HOLD/REJECT on a
    non-representative mention withholds nothing. No review keeps today's values and says nothing about verification."""
    checks = []
    world, first = verdict_export(root / "verdict-reviewed")
    bundle, cases = first["bundle"], verdict_cases(world)
    operator = Operator(world)
    checks.append("field verdicts: representative time REJECT/contradicted withholds the supply time (null, unknown precision, original mention time kept) while the re-attested structural edge is "
                  "exported, representative period ALLOW and non-representative HOLD/unstated + REJECT/contradicted withhold nothing, unanimous HOLD/ambiguous withholds the factory period; "
                  "verdicts ordered by mention identity then field, spans as app evidence of the mention's own article, issue evidence = mentions' + geography + verdicts' (also a span "
                  "no mention cites); relations unchanged; no source text or note exported")

    # A changed review is a different decisions file: the frozen handoff is withheld with no content, its receipt stays, a NEW id carries the new review.
    old_receipt = operator.cli("inspect", operator.sel(VERDICT_HANDOFF))
    changed = json.loads(json.dumps(cases))
    changed["issue:supply"][3] = field_verdict(world, "a", "m-a", "eventTime", "2026-09-30", "ALLOW", "stated", [EVT_A], version="fv2")
    write_operator(world, decisions=reviewed(world, cases=changed))
    gone = operator.cli("export", operator.sel(VERDICT_HANDOFF), expected=2)
    assert gone["delivery"] == {"status": "withheld", "code": "decisions_changed"} and "bundle" not in gone, gone
    assert operator.cli("inspect", operator.sel(VERDICT_HANDOFF)) == old_receipt, "the old receipt changed"
    operator.cli("freeze", manifest_doc(world, "handoff-verdicts-2", file_hashes(world.root)))
    second = operator.cli("export", operator.sel("handoff-verdicts-2"))["bundle"]
    assert second["handoffId"] == "handoff-verdicts-2" and second["digests"]["content"] != bundle["digests"]["content"]
    supply = next(i for i in second["issues"] if i["id"] == "issue:supply-2026q3")
    assert (supply["eventTime"], supply["timePrecision"], supply["fieldProvenance"]["withheld"]) == ("2026-09-30", "day", [])
    assert [r["type"] for r in second["relations"]].count("STRUCTURALLY_RELATED_TO") == 1
    write_operator(world, decisions=reviewed(world, published_time=None))
    assert operator.cli("export", operator.sel(VERDICT_HANDOFF))["bundle"] == bundle, "restoring the reviewed file did not restore the frozen handoff"
    checks.append("changed review: the frozen handoff is withheld (decisions_changed, no content) and its receipt unchanged; a new handoff id carries the new verdicts (an ALLOW restores the "
                  "time); restoring the exact file makes the old id current again")

    checks.append(unbindable_reviews(operator, world))
    checks.append(invalid_review_files(operator, world))

    # An event time withheld from the issue is a STRUCTURAL input: the attestation was reviewed against another (or no) time.
    time_world = build_world(root / "verdict-time")
    time_cases = {"issue:supply": [field_verdict(time_world, "a", "m-a", "eventTime", "2026-09-30", "REJECT", "contradicted", [EVT_A])]}
    time_operator = Operator(time_world)
    stale = freeze_export(time_operator, time_world, "time-1", reviewed(time_world, cases=time_cases))
    supply = next(i for i in stale["bundle"]["issues"] if i["id"] == "issue:supply-2026q3")
    assert (supply["eventTime"], supply["timePrecision"], supply["fieldProvenance"]["withheld"]) == (None, "unknown", ["eventTime"]) and supply["period"] == "2026Q3"
    assert {m["eventTime"] for m in supply["mentions"]} == {"2026-09-30"}
    items = {(i["kind"], i["id"]): i for i in stale["bundle"]["exclusions"]["items"]}
    mismatch = items[("structural", "issue:supply>co:synth-3")]
    assert mismatch["code"] == "applicability_binding_mismatch" and mismatch["detail"] == {"expectedBindingDigest": structural_binding(time_world, published_time=None)}, mismatch
    assert [r["type"] for r in stale["bundle"]["relations"]].count("STRUCTURALLY_RELATED_TO") == 0 and stale["bundle"]["counts"]["relations"]["FOLLOWS"] == 1
    assert_field_provenance_closed(stale["bundle"])
    assert {i["id"]: i["mentions"] for i in stale["bundle"]["issues"]} == expected_mentions(time_world, suppliers_agree=False), \
        "the time-withheld export's mentions differ from the hand-written ones (supplier unpublished -> companyId null; original values unchanged)"
    renewed = freeze_export(time_operator, time_world, "time-2", reviewed(time_world, cases=time_cases, published_time=None))
    assert [r["type"] for r in renewed["bundle"]["relations"]].count("STRUCTURALLY_RELATED_TO") == 1, "a re-reviewed attestation against the withheld time was refused"
    dated = build_world(root / "verdict-time-dated", dated=True)
    unprovable = freeze_export(Operator(dated), dated, "time-3", reviewed(dated, cases={"issue:supply": [field_verdict(dated, "a", "m-a", "eventTime", "2026-09-30", "HOLD", "ambiguous", [EVT_A])]}))
    items = {(i["kind"], i["id"]): i["code"] for i in unprovable["bundle"]["exclusions"]["items"]}
    assert items[("structural", "issue:supply>co:synth-3")] == "basis_validity_unprovable", items
    checks.append("a withheld event time is a structural input: the old attestation is refused (applicability_binding_mismatch with the digest of the withheld time), a re-reviewed one is "
                  "accepted, a basis with a validity window is refused (basis_validity_unprovable); FOLLOWS and INVOLVES are untouched")

    # Unanimous (no representative) issue with two mentions: a verdict on ANY mention is on the selection basis.
    one = build_world(root / "verdict-unanimous", a2_differs=False)
    doc = reviewed(one, cases={"issue:supply": [field_verdict(one, "a2", "m-a2", "period", "2026Q3", "HOLD", "ambiguous", [PERIOD_A2]),
                                                  field_verdict(one, "a", "m-a", "eventTime", "2026-09-30", "ALLOW", "stated", [EVT_A])]})
    doc["issues"][0]["representative"] = None
    out = freeze_export(Operator(one), one, "unanimous-1", doc)
    supply = next(i for i in out["bundle"]["issues"] if i["id"] == "issue:supply-2026q3")
    assert supply["representative"] is None and supply["fieldProvenance"]["selection"] == "unanimous" and supply["fieldProvenance"]["withheld"] == ["period"], supply["fieldProvenance"]
    assert (supply["period"], supply["eventTime"]) == (None, "2026-09-30") and {m["period"] for m in supply["mentions"]} == {"2026Q3"}
    assert_field_provenance_closed(out["bundle"])
    checks.append("unanimous issue (no representative, two agreeing mentions): a HOLD on the non-first mention withholds the period for the whole issue, the other mention and the time keep their values")
    return checks, SimpleNamespace(world=world, cases=cases, valid=first, time_world=time_world, time_cases=time_cases, time=stale)




# ---------------------------------------------------------------- issue summaries (bundle -7) ------------------------------------

SUMMARY_HANDOFF = "handoff-summary-1"
SUMMARY_WITHHELD_HANDOFF = "handoff-summary-withheld-1"
SUPPLY, FACTORY = "issue:supply-2026q3", "issue:factory-2026q4"
# The authored summary of the supply issue: ONE hand-written Korean claim that cites only the quote of document a. The issue's second mention (document a2, another article under its own
# source and grant) is NOT cited, yet the summary rests on it too: the model saw both quotes, so the basis, the pin and the rights all cover the uncited article. SYNTHETIC: nothing here
# is a real model's output, and no claim repeats a source sentence.
SUMMARY_CLAIMS = (("합성기업이 공급 계약을 발표했다.", "a", EVT_A),)
UNCITED = ("a2", EVT_A2)                          # the document and quote of the supply issue's mention that no claim cites
PENDING = {"status": "unavailable", "code": "temporal-review-pending", "pinned": False}
NOT_REQUESTED = {"status": "unavailable", "code": "not-requested", "pinned": False}


def summary_cli(world, command: str, request: dict, *, fixture: Path | None = None, expected: int = 0, state: Path | None = None):
    """The installed `zoop-ai-issue-summary` in a child process under the same network guard as the handoff CLI: authored replay only, no key and no model."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM}
    program = GUARD + "runpy.run_module('zoop_ai_pipeline.issue_summary_cli', run_name='__main__')\n"
    argv = [sys.executable, "-c", program, command, "--state-dir", str(state or world.root / "summary")]
    if command in {"submit", "run", "resume", "inspect", "export"}:               # the commands that consult sources and rights; `cancel` and `live-binding` take none
        root = world.root
        argv += ["--relation-state-dir", str(root / "relation"), "--extraction-state-dir", str(root / "extraction"), "--ingestion-state-dir", str(root / "ingestion"),
                 "--sources", str(world.kit.registry_path), "--canonical", str(root / "canonical.json"), "--decisions", str(root / "decisions.json"),
                 "--bindings", str(root / "bindings.json")]
    if fixture is not None:
        argv += ["--fixture", str(fixture)]
    child = subprocess.run(argv, input=json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=300)
    text = child.stdout.decode()
    assert child.returncode == expected, (command, child.returncode, text[:2000], child.stderr.decode()[-2000:])
    assert not child.stderr, child.stderr.decode()[-2000:]
    return json.loads(text)


def summary_fixture(world, bundle: dict, issue_id: str, claims: tuple, decisions: list) -> dict:
    """The authored replay fixture of one summary job: the model reply (the hand-written `claims`, each citing the positional label of its quote) and the independent verifier's
    answer (one hand-written decision per claim, no advice, no unsupported causality, no background-as-current), each keyed by the digest of the exact native stage payload.
    The basis is the pure `summary_basis` of the UNPINNED export; the quoted texts are sliced from the authored documents by the bundle's own evidence offsets."""
    issue = next(i for i in bundle["issues"] if i["id"] == issue_id)
    evidence = {e["id"]: e for e in bundle["evidence"]}
    articles = {(a["articleId"], a["articleVersion"]): a for a in bundle["articles"]}
    basis = summary_basis(issue, evidence, articles)
    name_of = {ref["documentId"]: name for name, ref in world.refs.items()}          # the authored bindings give an article the id of its document
    texts = {q["evidenceId"]: world.art[name_of[q["articleId"]]].body[q["start"]:q["end"]] for q in basis["quotes"]}
    payload = producer_payload(basis, texts)
    labels = {q["evidenceId"]: f"q{n}" for n, q in enumerate(basis["quotes"], 1)}
    reply = {"claims": [{"text": text, "quoteIds": [labels[evidence_id(world, name, quote)]]} for text, name, quote in claims]}
    produced = claims_from(reply, payload)
    verdict = {"claims": [{"claimId": c["claimId"], "decision": d, "reason": "authored"} for c, d in zip(produced, decisions)],
               "prohibitedAdvice": "absent", "unsupportedCausality": "absent", "backgroundAsCurrent": "absent"}
    return {"format": "zoop-issue-summary-fixture-1", "synthetic": True, "recordingKind": "authored-test",
            "records": [{"stage": "issue-summary", "requestDigest": digest(payload), "response": reply},
                        {"stage": "verify-issue-summary", "requestDigest": digest(verifier_payload(payload, produced)), "response": verdict}]}


def expected_available(world) -> dict:
    """Hand-written part of the supply issue's available summary that no digest, time or job id decides."""
    claims = [{"claimId": f"c{n}", "text": text, "evidenceIds": [evidence_id(world, name, quote)]} for n, (text, name, quote) in enumerate(SUMMARY_CLAIMS, 1)]
    return {"status": "available", "pinned": True, "text": "\n".join(text for text, _, _ in SUMMARY_CLAIMS), "claims": claims,
            "evidenceIds": sorted(c["evidenceIds"][0] for c in claims), "language": "ko", "producerKind": "authored-replay", "verifierKind": "authored-replay"}


def check_summary_part(summary: dict, want: dict) -> None:
    """One issue's exported `summary` equals the hand-written expectation (see `expected_summaries`): status/code, pinned or not, and for an available one the text, claims,
    evidence union, language and the two kinds."""
    assert summary["status"] == want["status"], (summary, want)
    assert (summary["source"] is not None) == want["pinned"], (summary, want)
    if want["status"] == "unavailable":
        assert set(summary) == {"status", "code", "source"} and summary["code"] == want["code"], (summary, want)
        return
    for key in ("text", "claims", "evidenceIds", "language"):
        assert summary[key] == want[key], (key, summary[key], want[key])
    assert summary["producer"]["kind"] == want["producerKind"] and summary["verifier"]["kind"] == want["verifierKind"], summary
    assert summary["producer"]["model"] is None and summary["verifier"]["model"] is None, "an authored replay names no model"


def summary_world(root: Path, handoff_id: str, outcome: str, public_ids: dict | None = None) -> tuple[SimpleNamespace, dict]:
    """The real export (`handoff_id`) of an ISSUE-SUMMARY world through the installed CLIs, checked against hand-written expectations. `outcome` `available`: the supply issue is summarised
    by an authored replay job (ONE claim, supported, citing the first article only; the second article of the issue is uncited but part of the basis) whose immutable result the decisions pin, and
    the factory issue carries a HOLD period verdict (deterministic `temporal-review-pending`, no job); `verifier-hold`: the verifier finds the claim insufficient, so the pinned result is a job-coded unavailable, and the
    factory issue has no verdict and no pin (`not-requested`). Flow: freeze+export an UNPINNED handoff (its bundle is the basis of the job input) -> `submit` (queued, no call) ->
    `run` (exactly two replay calls, no provider call) -> `run` again (no further call) -> `export` the pin fields -> decisions-3 pin them -> `freeze --issue-summary-state-dir` ->
    `export` (no summary ledger or flag: it works with the ledger moved away). The summary ledger is never written by freeze or export. A SYNTHETIC test world."""
    assert outcome in ("available", "verifier-hold"), outcome
    held = outcome == "available"
    world = build_world(root, uncited_source=True)          # document a2 (the uncited article) lives under its own source and grant
    verdicts = {"issue:factory": [field_verdict(world, "b", "m-b", "period", "2026Q4", "HOLD", "ambiguous", [PERIOD_B])]} if held else None

    def decisions(summaries: dict | None = None, extra: dict | None = None) -> dict:
        doc = decisions_doc(world, verdicts={**(verdicts or {}), **(extra or {})}, summaries=summaries)
        for company in doc["companies"]:
            company["publicId"] = (public_ids or {}).get(company["publicId"], company["publicId"])
        return doc

    operator = Operator(world)
    first = freeze_export(operator, world, f"{handoff_id}-input", decisions())
    assert {i["id"]: i["summary"] for i in first["bundle"]["issues"]} == {
        SUPPLY: {"status": "unavailable", "code": "not-requested", "source": None},
        FACTORY: {"status": "unavailable", "code": "temporal-review-pending" if held else "not-requested", "source": None}}, "an unpinned handoff states the zero-call table"
    assert first["bundle"]["policy"]["issueSummary"] == "zoop-issue-summary-policy-1"

    fixture = world.root / f"summary-{outcome}-fixture.json"
    fixture.write_bytes(json_bytes(summary_fixture(world, first["bundle"], SUPPLY, SUMMARY_CLAIMS, ["supported" if held else "insufficient"])))
    job = f"summary-job-{outcome}"
    request = {"schemaVersion": "zoop-issue-summary-1", "jobId": job, "issueId": SUPPLY, "mode": "replay", "manifest": first["manifest"]}
    queued = summary_cli(world, "submit", request)
    assert queued["state"] == "queued" and queued["usage"]["replayCalls"] == 0 and queued["usage"]["providerCalls"] == 0 and queued["usage"]["modelCalls"] == 0, queued
    ran = summary_cli(world, "run", request, fixture=fixture)
    assert ran["state"] == "ready" and ran["result"]["outcome"] == ("available" if held else "verifier-hold"), ran
    assert ran["usage"]["replayCalls"] == 2 and ran["usage"]["providerCalls"] == 0 and ran["usage"]["modelCalls"] == 0, ran["usage"]
    assert summary_cli(world, "run", request, fixture=fixture)["usage"] == ran["usage"], "a second run made another call"
    pinned = summary_cli(world, "export", {"schemaVersion": "zoop-issue-summary-1", "jobId": job})
    pin = {key: pinned[key] for key in ("jobId", "inputDigest", "resultDigest")}
    # The job's own delivery follows the CURRENT rights like the S2/S3 results: a revoked grant withholds the stored result (identity and usage only: no pin fields, outcome or text); restored, the same
    # result is shown again. The CITED article's source and, separately, the UNCITED article's source: the model saw both, so either grant alone withholds it.
    selector = {"schemaVersion": "zoop-issue-summary-1", "jobId": job}
    for source_id in ("synthetic-source", UNCITED_SOURCE):
        set_grant(world, source_id, False)
        hidden = summary_cli(world, "export", selector, expected=2)
        assert hidden["delivery"]["status"] == "withheld" and not {"summary", "outcome", "resultDigest", "provenance"} & set(hidden), (source_id, hidden)
        assert all(text not in json.dumps(hidden, ensure_ascii=False) for text, _, _ in SUMMARY_CLAIMS), "a withheld summary export carried text"
        set_grant(world, source_id, True)
        assert summary_cli(world, "export", selector) == pinned, f"restoring the grant of {source_id} did not restore the same result"

    pinned_decisions = decisions({"issue:supply": pin})
    write_operator(world, decisions=pinned_decisions)
    ledger = world.root / "summary"
    ledger_before = ledger_snapshot(ledger)
    frozen = operator.cli("freeze", manifest_doc(world, handoff_id, file_hashes(world.root)), summaries=ledger)
    assert frozen["state"] == "ready" and frozen["usage"] == {"providerCalls": 0, "modelCalls": 0}, frozen
    out = operator.cli("export", operator.sel(handoff_id))
    assert out["delivery"]["status"] == "current" and out["usage"] == {"providerCalls": 0, "modelCalls": 0}, out["delivery"]
    assert ledger_snapshot(ledger) == ledger_before, "freeze or export wrote the issue-summary ledger"
    # Pinning rewrote the decisions file the job's own manifest pinned: the job's public export is withheld now, while the handoff freeze proved the sources and rights with ITS manifest.
    moved_on = summary_cli(world, "export", selector, expected=2)
    assert moved_on["delivery"]["status"] == "withheld" and "summary" not in moved_on and "resultDigest" not in moved_on, moved_on
    bundle = out["bundle"]
    by_id = {i["id"]: i for i in bundle["issues"]}
    want = expected_summaries_of(world, outcome)
    for issue_id, expectation in want.items():
        check_summary_part(by_id[issue_id]["summary"], expectation)
    summary = by_id[SUPPLY]["summary"]
    assert summary == pinned["summary"], "the bundle did not carry the job's exact result"
    assert (summary["source"]["jobId"], summary["source"]["inputDigest"], summary["source"]["resultDigest"]) == (pin["jobId"], pin["inputDigest"], pin["resultDigest"])
    basis = summary_basis(next(i for i in first["bundle"]["issues"] if i["id"] == SUPPLY), {e["id"]: e for e in first["bundle"]["evidence"]},
                          {(a["articleId"], a["articleVersion"]): a for a in first["bundle"]["articles"]})
    uncited = evidence_id(world, *UNCITED)
    assert summary["source"]["basisDigest"] == digest(basis) and len(basis["quotes"]) == 2, "the summary rests on both mention quotes of the supply issue"
    assert uncited in {q["evidenceId"] for q in basis["quotes"]} and uncited not in summary.get("evidenceIds", []), "the uncited quote must be part of the basis although no claim cites it"
    assert bundle["schemaVersion"] == "zoop-graph-handoff-bundle-8" and bundle["handoffId"] == handoff_id
    assert canonical(bundle).encode() == (operator.state / "bundles" / f"{frozen['receipt']['bundleDigest']}.json").read_bytes(), "export is not the frozen artifact"
    dumped = json.dumps(out, ensure_ascii=False)
    assert all(text not in dumped for text in PRIVATE), "source text leaked"

    # Export needs neither the summary ledger nor a new flag: the same bundle with the ledger moved away, and the flag is refused for export.
    moved = world.root / "summary-moved"
    ledger.rename(moved)
    assert operator.cli("export", operator.sel(handoff_id))["bundle"] == bundle, "export depends on the summary ledger"
    assert operator.cli("export", operator.sel(handoff_id), expected=2, summaries=moved)["error"]["code"] == "input_or_configuration_invalid"
    moved.rename(ledger)

    # Current rights: a revoked grant withholds the handoff with no summary text; restored, it is current again. The UNCITED article's own grant counts as much as the cited one's.
    for source_id in ("synthetic-source", UNCITED_SOURCE):
        set_grant(world, source_id, False)
        gone = operator.cli("export", operator.sel(handoff_id), expected=2)
        assert gone["delivery"]["status"] == "withheld" and "bundle" not in gone and all(text not in json.dumps(gone, ensure_ascii=False) for text, _, _ in SUMMARY_CLAIMS), (source_id, gone)
        set_grant(world, source_id, True)
        assert operator.cli("export", operator.sel(handoff_id))["bundle"] == bundle, f"restoring the grant of {source_id} did not restore the same export"
    world.summary = SimpleNamespace(pin=pin, job=job, pinned_decisions=pinned_decisions, decisions=decisions, ledger=ledger, first=first, operator=operator,
                                    uncited=SimpleNamespace(name=UNCITED[0], source=UNCITED_SOURCE, document_id=world.refs[UNCITED[0]]["documentId"], evidence_id=uncited))
    return world, out


def expected_summaries_of(world, outcome: str) -> dict:
    """Hand-written summaries of the two public issues of a summary world."""
    if outcome == "available":
        return {SUPPLY: expected_available(world), FACTORY: PENDING}
    return {SUPPLY: {"status": "unavailable", "code": "verifier-hold", "pinned": True}, FACTORY: NOT_REQUESTED}


def summary_refusals(world, out: dict) -> str:
    """A pin the handoff cannot honor refuses the WHOLE freeze with a stable code and writes nothing (the refused id does not exist afterwards), through the installed CLI over the
    `available` summary world: a pin without the ledger flag, the flag without a pin, a wrong result or input digest, an unknown job, a pinned issue that is now held, a pinned issue that is not
    public, and a pin whose basis the current sources no longer give because the UNCITED article (document a2, which no claim cites) is bound differently: another article id, another article
    version, or a text hash that does not match its source (the issue is not published). The operator files are restored after each case, so the frozen handoff is still current at the end."""
    ctx = world.summary
    operator, root, ledger = ctx.operator, world.root, ctx.ledger
    handoff_id = out["handoffId"]
    frozen_bytes = {name: (root / f"{name}.json").read_bytes() for name in ("canonical", "decisions", "bindings")}
    state_before = ledger_snapshot(ledger)

    def refuse(name: str, code: str, decisions: dict, *, bindings: dict | None = None, flag: bool = True) -> None:
        write_operator(world, decisions=decisions, bindings=bindings)
        refused = operator.cli("freeze", manifest_doc(world, name, file_hashes(root)), expected=2, summaries=ledger if flag else None)
        assert refused["error"]["code"] == code, (name, refused)
        assert operator.cli("inspect", operator.sel(name), expected=2)["error"]["code"] == "handoff_not_found", f"{name}: a refused freeze left a handoff row"

    pin = ctx.pin
    refuse("pin-without-ledger", "issue_summary_state_missing", ctx.pinned_decisions, flag=False)
    refuse("ledger-without-pin", "issue_summary_state_unused", ctx.decisions())
    refuse("pin-wrong-result", "issue_summary_pin_mismatch", ctx.decisions({"issue:supply": {**pin, "resultDigest": "0" * 64}}))
    refuse("pin-wrong-input", "issue_summary_pin_mismatch", ctx.decisions({"issue:supply": {**pin, "inputDigest": "0" * 64}}))
    refuse("pin-unknown-job", "issue_summary_not_found", ctx.decisions({"issue:supply": {**pin, "jobId": "no-such-summary-job"}}))
    held = {"issue:supply": [field_verdict(world, "a", "m-a", "period", "2026Q3", "HOLD", "ambiguous", [PERIOD_A])]}
    refuse("pin-on-held-issue", "issue_summary_temporal_review_pending", ctx.decisions({"issue:supply": pin}, extra=held))
    refuse("pin-on-unpublished-issue", "issue_summary_issue_not_public", ctx.decisions({"issue:supply": pin, "issue:overseas": pin}))
    uncited_document = ctx.uncited.document_id
    moved = bindings_doc(world)
    next(b for b in moved["bindings"] if b["documentId"] == uncited_document)["articleId"] = "doc-" + "5" * 64
    refuse("pin-after-uncited-article-id-change", "issue_summary_basis_changed", ctx.pinned_decisions, bindings=moved)
    versioned = bindings_doc(world)
    next(b for b in versioned["bindings"] if b["documentId"] == uncited_document)["articleVersion"] = "6" * 64
    refuse("pin-after-uncited-article-version-change", "issue_summary_basis_changed", ctx.pinned_decisions, bindings=versioned)
    unhashed = bindings_doc(world)
    next(b for b in unhashed["bindings"] if b["documentId"] == uncited_document)["textSha256"] = "7" * 64
    refuse("pin-after-uncited-binding-hash-change", "issue_summary_issue_not_public", ctx.pinned_decisions, bindings=unhashed)
    for name, raw in frozen_bytes.items():
        (root / f"{name}.json").write_bytes(raw)
    assert ledger_snapshot(ledger) == state_before, "a refused freeze wrote the issue-summary ledger"
    assert operator.cli("export", operator.sel(handoff_id))["bundle"] == out["bundle"], "a refused freeze changed the frozen handoff"
    artifact = operator.state / "bundles" / f"{operator.cli('inspect', operator.sel(handoff_id))['receipt']['bundleDigest']}.json"
    original = artifact.read_bytes()
    os.chmod(artifact, 0o600)
    artifact.write_bytes(original.replace(SUMMARY_CLAIMS[0][0].encode(), "합성기업이 공급 계약을 취소했다.".encode(), 1))
    assert operator.cli("export", operator.sel(handoff_id), expected=2)["error"]["code"] == "handoff_artifact_invalid", "an edited summary text in the artifact was exported"
    artifact.write_bytes(original)
    assert operator.cli("export", operator.sel(handoff_id))["bundle"] == out["bundle"]
    return ("issue summaries: freeze refuses a pin without the ledger flag (issue_summary_state_missing), the flag without a pin (issue_summary_state_unused), a wrong result or input digest "
            "(issue_summary_pin_mismatch), an unknown job (issue_summary_not_found), a pinned held issue (issue_summary_temporal_review_pending), a pinned unpublished issue "
            "(issue_summary_issue_not_public), and a basis the sources no longer give because the UNCITED article is bound to another article id or version (issue_summary_basis_changed) or "
            "by a wrong text hash (the issue is not published), each with no handoff row and an untouched summary ledger; an edited summary text in the artifact is refused on export "
            "(handoff_artifact_invalid)")


def expected_summaries(summary_world_: SimpleNamespace, withheld_world: SimpleNamespace, path_exports: dict) -> dict:
    """Hand-written summary of every public issue of every export file: not-requested unless an operator HOLD/REJECT verdict (`verdict_cases` / `time_cases`) leaves
    `temporal-review-pending`; the two summary worlds pin a job. Keyed by export file name, then public issue id."""
    plain = {SUPPLY: NOT_REQUESTED, FACTORY: NOT_REQUESTED}
    return {"export-valid.json": plain, "export-collision.json": plain, "export-approved.json": plain, "export-impacts.json": plain, "export-impacts-unicode.json": plain,
            **{f"export-path-{middle}.json": plain for middle in path_exports},
            "export-field-verdicts.json": {SUPPLY: PENDING, FACTORY: PENDING},
            "export-field-verdicts-time.json": {SUPPLY: PENDING, FACTORY: NOT_REQUESTED},
            "export-summary.json": expected_summaries_of(summary_world_, "available"), "export-summary-withheld.json": expected_summaries_of(withheld_world, "verifier-hold")}


def summary_mutations() -> dict:
    """name -> (the one change to the `export-summary.json` bundle, the validator location that must refuse it). The caller recomputes the content digest, so ONLY the summary rule can
    refuse the bundle: the supply issue carries the available summary, the factory issue (a HOLD period verdict) `temporal-review-pending`."""
    def issue(b, issue_id):
        return next(i for i in b["issues"] if i["id"] == issue_id)

    def geography_evidence(b):
        return issue(b, SUPPLY)["geography"]["evidenceIds"][0]

    def foreign_claim(b):
        issue(b, SUPPLY)["summary"]["claims"][0]["evidenceIds"] = [geography_evidence(b)]

    def uncited_mention(b):
        """The supply mention whose quote no claim cites: it is in the summary's basis only."""
        supply = issue(b, SUPPLY)
        cited = set(supply["summary"]["evidenceIds"])
        return next(m for m in supply["mentions"] if not cited & set(m["evidenceIds"]))

    def uncited_article_hash(b):
        mention = uncited_mention(b)
        next(a for a in b["articles"] if (a["articleId"], a["articleVersion"]) == (mention["articleId"], mention["articleVersion"]))["textSha256"] = "7" * 64

    def forge(key, value):
        return lambda b: issue(b, SUPPLY)["summary"].__setitem__(key, value)

    return {
        "a summary text that is not the claims joined": (forge("text", "다른 문장이다."), "issue.summary.text"),
        "a claim edited behind the summary text": (lambda b: issue(b, SUPPLY)["summary"]["claims"][0].__setitem__("text", "합성기업이 공급 계약을 취소했다."), "issue.summary.text"),
        "a claim citing evidence outside the issue's mention quotes": (foreign_claim, "issue.summary.claims.evidenceIds"),
        "a basis digest of another basis": (lambda b: issue(b, SUPPLY)["summary"]["source"].__setitem__("basisDigest", "0" * 64), "issue.summary.source.basisDigest"),
        "a forged result digest": (lambda b: issue(b, SUPPLY)["summary"]["source"].__setitem__("resultDigest", "0" * 64), "issue.summary.source.resultDigest"),
        "a forged result version": (forge("resultVersion", "isr-" + "0" * 64), "issue.summary.resultVersion"),
        "a replay summary relabelled as a provider's": (lambda b: issue(b, SUPPLY)["summary"]["producer"].__setitem__("kind", "provider"), "issue.summary.producer.kind"),
        "a summary language other than ko": (forge("language", "en"), "issue.summary.language"),
        "an available summary on the issue whose time field is held": (lambda b: issue(b, FACTORY).__setitem__("summary", json.loads(json.dumps(issue(b, SUPPLY)["summary"]))),
                                                                      "issue.summary.status"),
        "not-requested on the issue whose time field is held": (lambda b: issue(b, FACTORY).__setitem__("summary", {"status": "unavailable", "code": "not-requested", "source": None}),
                                                               "issue.summary.code"),
        "temporal-review-pending on an issue nobody held": (lambda b: issue(b, SUPPLY).__setitem__("summary", {"status": "unavailable", "code": "temporal-review-pending", "source": None}),
                                                           "issue.summary.code"),
        "an issue without its summary key": (lambda b: issue(b, SUPPLY).pop("summary"), "issue"),
        "another summary policy": (lambda b: b["policy"].__setitem__("issueSummary", "zoop-issue-summary-policy-2"), "policy.issueSummary"),
        "the uncited mention turned into a background one under an unchanged summary": (lambda b: uncited_mention(b).__setitem__("background", True), "issue.summary.resultVersion"),
        "the uncited article's text hash edited under an unchanged summary": (uncited_article_hash, "issue.summary.resultVersion"),
    }


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
    checks.append("legal local mentionId collision (documents a and a2 both use `m-a`): both source members and the second document's evidence survive, the representative is kept; "
                  "three source events give two mentions, identified by (document, version, local id)")
    checks.append("original mentions: every public issue carries its hand-written S2 mentions (fields as extracted, verification none, one record per identity although a "
                  "mention is carried by two upstreams), every mention evidence reachable on its own article, issue evidence = mentions' + geography evidence")
    checks.append("field provenance: every public issue records HOW its six headline values were selected (`operator-representative`, also where every mention agrees, or "
                  "`unanimous`; verification none) and lists in each field exactly the original mentions stating the issue's value (hand-written for the representative with one "
                  "differing title, the one-mention issue and the collision world); nothing is verified or supported")
    checks.append(mention_exclusions(root))
    checks.append(source_support_variants(root))
    approved_world, approved = approved_export(root.parent / "approved")
    checks.append("operator final approval: the authored verifier HELD two relations the issues depend on, the operator approved them (revision 2, effect `approved`), and the bundle is MIXED in "
                  "approval: the per-source approval proof (kind, revision, reviewer, decision time) equals the hand-written one, the supply INVOLVES edge (one automatic and one manual "
                  "contributor) and the structural edge never claim the independent verifier supported all claims, the purely automatic factory edge does, and the structural basis "
                  "time is the approval time")
    checks.append(participants_across_upstreams(collision_world))
    verdict_checks, verdict_fixtures = field_verdicts(root.parent)
    checks.extend(verdict_checks)
    path_check, path_world, path_exports = structural_paths(root)
    checks.append(path_check)
    impact_world, impact_out = impact_export(root.parent / "impacts")
    checks.append("receipt-only impact rows: the default world's every automatic participation is `not-proposed` and the approved world's operator-approved one `not-applicable` (hand-written); the "
                  "`rich` world keeps four rows on the supply edge apart (verified positive with an impact-only sentence, verifier-rejected, verified negative of the other S3 job, "
                  "verified-but-undetermined) and `no-evidence`/precheck-rejected rows on the factory edge, labels exist only on verified rows, the invented off-target company is never exported")
    legacy_check, legacy_withheld = legacy_history(world, exported)
    checks.append(legacy_check)
    summary_ns, summary_out = summary_world(root.parent / "summary", SUMMARY_HANDOFF, "available")
    checks.append("issue summaries: a REAL authored-replay `zoop-ai-issue-summary` job (submit = queued with no call, run = exactly two replay calls and no provider call, a second run = no further call) "
                  "whose immutable result the decisions-3 pin carries into bundle -7 through `freeze --issue-summary-state-dir`: the supply issue's available summary (ONE claim citing the first article; the "
                  "second article, under its own source and grant, is uncited but in the basis) equals the hand-written text, claims, evidence and kinds and is the job's exact object; the factory issue's HOLD "
                  "verdict leaves `temporal-review-pending` with no job; export is the frozen artifact, needs no summary ledger or flag (works with the ledger moved away), freeze and export leave the "
                  "ledger byte-identical and call no model; revoking EITHER source's grant (the cited or the uncited article's) withholds the summary job's export and the whole handoff with no summary text, "
                  "and restoring it gives the same output")
    checks.append(summary_refusals(summary_ns, summary_out))
    withheld_ns, withheld_out = summary_world(root.parent / "summary-withheld", SUMMARY_WITHHELD_HANDOFF, "verifier-hold")
    checks.append("a job the independent verifier held (`verifier-hold`) is pinned as a job-coded unavailable summary with its source pin and no text; an issue with no verdict and no pin is `not-requested`")

    if fixture is not None:
        write_fixture(fixture, world, exported, withheld, legacy_withheld, collision_world, collision, verdict_fixtures, path_exports, path_world, impact_world, impact_out,
                      approved_world, approved, summary_ns, summary_out, withheld_ns, withheld_out)
        checks.append(f"fixtures written to {fixture}")
    return {"status": "passed", "providerCalls": 0, "modelCalls": 0, "checks": checks}


def write_fixture(directory: Path, world, valid: dict, withheld: dict, legacy_withheld: dict, collision_world, collision: dict, verdict_fixtures: SimpleNamespace,
                  path_exports: dict, path_world, impact_world, impact_out: dict, approved_world, approved: dict, summary_ns: SimpleNamespace, summary_out: dict,
                  withheld_ns: SimpleNamespace, withheld_out: dict) -> None:
    """The valid export envelope (bundle `-7`, no operator verdict: `fieldVerdicts` empty; default `not-proposed` impact rows; every summary `not-requested`), the real export of the legal local-mentionId collision world, the real export of the hand-reviewed
    verdict world (`export-field-verdicts.json`) and of the time-withheld world (`export-field-verdicts-time.json`), the hand-written expected original mentions, field provenance and
    verdicts of them, negative bundles (each MUST be refused by an importer; the verdict and structural-path ones keep a recomputed content digest so only their own rule can refuse them),
    the real exports of the structural-path world (`export-path-known|private|unmapped.json`, `expected-structural-paths.json`, one rule broken per `bundle-path-NN.json`)
    and the two withheld envelopes (no bundle at all): drift (`export-withheld`) and a handoff frozen under an earlier bundle schema (`export-withheld-legacy`, a `-2` row)."""
    directory.mkdir()                                                    # the caller proved it does not exist: a fixture directory is never reused or overwritten
    write = lambda name, value: (directory / name).write_bytes(json_bytes(value) + b"\n")  # noqa: E731
    write("export-valid.json", valid)
    write("export-withheld.json", withheld)
    write("export-withheld-legacy.json", legacy_withheld)
    write("export-collision.json", collision)
    tw, tc = verdict_fixtures.time_world, verdict_fixtures.time_cases
    vw, vc = verdict_fixtures.world, verdict_fixtures.cases
    time_withheld = {"issue:supply-2026q3": ["eventTime"]}
    write("export-field-verdicts.json", verdict_fixtures.valid)
    write("export-field-verdicts-time.json", verdict_fixtures.time)
    write("expected-mentions.json", {"export-valid.json": expected_mentions(world), "export-collision.json": expected_mentions(collision_world),
                                     "export-field-verdicts.json": expected_mentions(vw),
                                     # the structural edge is excluded here, so the supplier company is not published and its participant `companyId` is null
                                     "export-field-verdicts-time.json": expected_mentions(tw, suppliers_agree=False)})
    write("expected-field-provenance.json", {"export-valid.json": expected_field_provenance(world), "export-collision.json": expected_field_provenance(collision_world),
                                             "export-field-verdicts.json": expected_field_provenance(vw, VERDICT_WITHHELD),
                                             "export-field-verdicts-time.json": expected_field_provenance(tw, time_withheld)})
    write("expected-field-verdicts.json", {"export-valid.json": expected_verdicts(world, {}), "export-collision.json": expected_verdicts(collision_world, {}),
                                           "export-field-verdicts.json": expected_verdicts(vw, vc), "export-field-verdicts-time.json": expected_verdicts(tw, tc)})
    headlines = lambda values: {issue: {"eventTime": t, "timePrecision": p, "period": period} for issue, (t, p, period) in values.items()}   # noqa: E731
    write("expected-headline-values.json", {"export-valid.json": headlines(expected_headlines(world)), "export-collision.json": headlines(expected_headlines(collision_world)),
                                            "export-field-verdicts.json": headlines(expected_headlines(vw, VERDICT_WITHHELD)),
                                            "export-field-verdicts-time.json": headlines(expected_headlines(tw, time_withheld))})
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

    verdict_envelope = verdict_fixtures.valid

    def mutate_verdict(name: str, change) -> None:
        """A copy of the verdict export with one rule broken and the content digest recomputed, so that ONLY the verdict rule can refuse it."""
        copy = json.loads(json.dumps(verdict_envelope["bundle"]))
        change(copy)
        copy["digests"]["content"] = content_digest(copy)
        write(name, {**verdict_envelope, "bundle": copy})

    supply = lambda b: next(i for i in b["issues"] if i["id"] == "issue:supply-2026q3")      # noqa: E731
    factory = lambda b: next(i for i in b["issues"] if i["id"] == "issue:factory-2026q4")    # noqa: E731
    foreign = evidence_id(verdict_fixtures.world, "b", QB)                                       # an evidence of ANOTHER document's article

    def verdict_of(b, issue, mention_id: str, field: str) -> dict:
        return next(v for v in issue(b)["fieldVerdicts"] if (v["mentionId"], v["field"]) == (mention_id, field))

    def cite_foreign(b):
        verdict_of(b, supply, "m-a", "period")["evidenceIds"] = [foreign]
        supply(b)["evidenceIds"] = sorted({*supply(b)["evidenceIds"], foreign})

    def unstated_with_evidence(b):
        verdict_of(b, supply, "m-a2", "eventTime")["evidenceIds"] = list(verdict_of(b, supply, "m-a2", "period")["evidenceIds"])

    def orphan(b):
        lost = verdict_of(b, supply, "m-a2", "period")["evidenceIds"][0]
        supply(b)["evidenceIds"] = [i for i in supply(b)["evidenceIds"] if i != lost]

    mutate_verdict("bundle-verdict-headline-not-withheld.json", lambda b: factory(b).update(period="2026Q4"))
    mutate_verdict("bundle-verdict-withheld-forged.json", lambda b: supply(b)["fieldProvenance"].update(withheld=["eventTime", "period"]))
    mutate_verdict("bundle-verdict-withheld-missing.json", lambda b: factory(b)["fieldProvenance"].update(withheld=[]))
    mutate_verdict("bundle-verdict-precision-not-unknown.json", lambda b: supply(b).update(timePrecision="day"))
    mutate_verdict("bundle-verdict-stale-value.json", lambda b: verdict_of(b, supply, "m-a", "eventTime").update(value="2026-10-01"))
    mutate_verdict("bundle-verdict-foreign-evidence.json", cite_foreign)
    mutate_verdict("bundle-verdict-duplicate.json", lambda b: supply(b)["fieldVerdicts"].append(json.loads(json.dumps(supply(b)["fieldVerdicts"][0]))))
    mutate_verdict("bundle-verdict-unsorted.json", lambda b: supply(b)["fieldVerdicts"].reverse())
    mutate_verdict("bundle-verdict-note.json", lambda b: supply(b)["fieldVerdicts"][0].update(note="private note"))
    mutate_verdict("bundle-verdict-unstated-with-evidence.json", unstated_with_evidence)
    mutate_verdict("bundle-verdict-unknown-mention.json", lambda b: factory(b)["fieldVerdicts"][0].update(mentionId="m-zzz"))
    mutate_verdict("bundle-verdict-title-field.json", lambda b: factory(b)["fieldVerdicts"][0].update(field="title"))
    mutate_verdict("bundle-verdict-evidence-orphan.json", orphan)

    def forge_manifest(name: str, change) -> None:
        copy = json.loads(json.dumps(valid["manifest"]))
        change(copy)
        write(name, {**valid, "manifest": copy})

    forge_manifest("manifest-wrong-digest.json", lambda m: m.update({"sourceKind": "actual"}))
    forge_manifest("manifest-wrong-source-pin.json", lambda m: m["sources"][0].update({"reviewDigest": "f" * 64}))
    forge_manifest("manifest-wrong-file-pin.json", lambda m: m["files"].update({"bindings": "f" * 64}))
    forge_manifest("manifest-unknown-field.json", lambda m: m.update({"operatorPath": "/private/x"}))
    write("export-missing-manifest.json", {key: value for key, value in valid.items() if key != "manifest"})

    # Structural paths: the real exports of the chain world (a published middle, a private middle, an unmapped middle) and one rule broken per negative bundle (content digest recomputed).
    for middle, out in path_exports.items():
        write(f"export-path-{middle}.json", out)
    for number, (name, (middle, change, at)) in enumerate(path_mutations().items(), 1):
        copy = json.loads(json.dumps(path_exports[middle]["bundle"]))
        change(copy)
        copy["digests"]["content"] = content_digest(copy)
        write(f"bundle-path-{number:02d}.json", {**path_exports[middle], "bundle": copy})
    write("expected-structural-paths.json", {f"export-path-{middle}.json": expected_chain(middle) for middle in path_exports} |
          {f"bundle-path-{number:02d}.json": {"breaks": name, "validatorLocation": at} for number, (name, (_, _, at)) in enumerate(path_mutations().items(), 1)})

    # Impacts: the real export of the `rich` impact world, the approved world's (a `not-applicable` row), a VALID export whose proposal lengths exceed their UTF-16 bounds,
    # the hand-written rows of every export above and one rule broken per `bundle-impact-NN.json` (content digest recomputed unless the case is about the digest itself).
    write("export-impacts.json", impact_out)
    write("export-approved.json", approved)
    write("export-impacts-unicode.json", unicode_impact_envelope(impact_out))
    mutations = impact_mutations()
    for number, (name, (change, at, refresh)) in enumerate(mutations.items(), 1):
        copy = json.loads(json.dumps(impact_out["bundle"]))
        change(copy)
        if refresh:
            copy["digests"]["content"] = content_digest(copy)
        write(f"bundle-impact-{number:02d}.json", {**impact_out, "bundle": copy})
    write("expected-impacts.json", {"export-valid.json": expected_impacts(world), "export-collision.json": expected_impacts(collision_world),
                                    "export-field-verdicts.json": expected_impacts(vw), "export-field-verdicts-time.json": expected_impacts(tw),
                                    "export-approved.json": expected_impacts(approved_world), "export-impacts.json": expected_impacts(impact_world),
                                    "export-impacts-unicode.json": unicode_impact_rows(expected_impacts(impact_world)),
                                    **{f"export-path-{middle}.json": expected_impacts(path_world) for middle in path_exports},
                                    **{f"bundle-impact-{number:02d}.json": {"breaks": name, "validatorLocation": at} for number, (name, (_, at, _)) in enumerate(mutations.items(), 1)}})
    # Issue summaries: the real exports of the two summary worlds, the hand-written summary of every public issue of every export above and one rule broken per `bundle-summary-NN.json`
    # (content digest recomputed, so only the summary rule can refuse it).
    write("export-summary.json", summary_out)
    write("export-summary-withheld.json", withheld_out)
    summary_changes = summary_mutations()
    for number, (name, (change, at)) in enumerate(summary_changes.items(), 1):
        copy = json.loads(json.dumps(summary_out["bundle"]))
        change(copy)
        copy["digests"]["content"] = content_digest(copy)
        write(f"bundle-summary-{number:02d}.json", {**summary_out, "bundle": copy})
    write("expected-summaries.json", {**expected_summaries(summary_ns, withheld_ns, path_exports),
                                      **{f"bundle-summary-{number:02d}.json": {"breaks": name, "validatorLocation": at}
                                         for number, (name, (_, at)) in enumerate(summary_changes.items(), 1)}})


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


def verify_historical_delivery(root: Path) -> dict:
    """Read an existing delivery with this consumer; the original wrappers and source stores remain untouched."""
    import hashlib

    root = root.resolve(strict=True)
    commands = json.loads((root / "origin-commands.json").read_bytes())
    matches = [entry["argv"] for entry in commands if entry["label"] == "handoff-export"]
    assert len(matches) == 1, "one pinned historical export command required"
    historical = matches[0]
    args = historical[historical.index("export") + 1:]
    flags = dict(zip(args[::2], args[1::2], strict=True))
    assert len(args) == 16 and set(flags) == {"--state-dir", "--relation-state-dir", "--extraction-state-dir", "--ingestion-state-dir",
                                             "--sources", "--canonical", "--decisions", "--bindings"}, "historical source flags differ"
    assert Path(flags["--state-dir"]) == root / "handoff", "historical handoff ownership differs"
    manifest = json.loads((root / "handoff-manifest.json").read_bytes())
    expected = json.loads((root / "export-envelope.json").read_bytes())
    stored_bundle = (root / "bundle.json").read_bytes()
    assert canonical(json.loads(stored_bundle)) == canonical(expected["bundle"]), "historical bundle pins disagree"
    watched = [root, *(Path(flags[name]) for name in ("--relation-state-dir", "--extraction-state-dir", "--ingestion-state-dir"))]
    authority = Path(flags["--sources"])

    def fingerprint():
        info = authority.stat()
        return {"trees": [ledger_snapshot(path) for path in watched],
                "authority": (stat.S_IMODE(info.st_mode), info.st_mtime_ns, info.st_size, hashlib.sha256(authority.read_bytes()).hexdigest())}

    before = fingerprint()
    sandbox = "(version 1) (allow default) (deny network*) (deny file-write*)"
    env = {"PATH": os.defpath, "HOME": str(Path.home()), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONNOUSERSITE": "1", "PYTHONPATH": str(PIPELINE / "src"), **ownership_env()}
    try:
        child = subprocess.run(["/usr/bin/sandbox-exec", "-p", sandbox, sys.executable, "-B", "-m", "zoop_ai_pipeline.handoff_cli", "export", *args],
                               input=json_bytes({"schemaVersion": "zoop-ai-handoff-1", "handoffId": manifest["handoffId"]}),
                               capture_output=True, env=env, cwd=PIPELINE, timeout=600)
        result = json.loads(child.stdout)
        assert child.returncode == 0, result.get("error", result.get("delivery"))
        assert result["delivery"]["status"] == "current", result["delivery"]
        assert result["manifest"] == manifest and result["bundle"] == expected["bundle"], "historical native output changed"
        assert result["receipt"] == expected["receipt"], "historical receipt changed"
    finally:
        assert fingerprint() == before, "historical source bytes, modes or mtimes changed"
    return {"status": "passed", "bundleSchema": result["bundle"]["schemaVersion"],
            "sources": len(result["bundle"]["sources"]), "issues": len(result["bundle"]["issues"]),
            "bundleDigest": result["receipt"]["bundleDigest"], "ledgerReadOnly": True,
            "networkDenied": True, "fileWritesDenied": True, "providerCalls": 0, "modelCalls": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write-fixture", type=Path, help="run the full smoke and write the importer fixtures into this NEW directory")
    parser.add_argument("--write-package", type=Path, help="build the retained operator package in this NEW directory (no smoke, nothing temporary)")
    parser.add_argument("--verify-package", type=Path, help="re-export an existing package in fresh processes and compare with its pins")
    parser.add_argument("--verify-historical-delivery", type=Path, help="read-only new-consumer check against pinned origin-commands/export files; macOS sandbox required")
    parser.add_argument("--export-out", type=Path, help="with --verify-package: write the current export envelope to this NEW file")
    args = parser.parse_args()
    modes = [name for name in ("write_fixture", "write_package", "verify_package", "verify_historical_delivery") if getattr(args, name) is not None]
    if len(modes) > 1 or (args.export_out is not None and args.verify_package is None):
        parser.error("choose one verification or fixture mode; --export-out needs --verify-package")
    if args.verify_historical_delivery is not None:
        print(json.dumps(verify_historical_delivery(args.verify_historical_delivery), ensure_ascii=False, indent=1))
        return 0
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
