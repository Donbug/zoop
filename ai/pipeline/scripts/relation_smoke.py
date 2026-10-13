#!/usr/bin/env python3
"""Authored HTML -> actual ingestion + S2 extraction + S3 relation/impact JSON subprocesses. Fresh owned state is always removed.

Replay here is authored response replay for BOTH the producer and the independent verifier: no network, no model, no original PoC state,
and no claim about real AI relation/impact quality.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.extraction_smoke import PROMPT, Kit, page, topic_replay, topic_response  # noqa: E402
from scripts.ingestion_smoke import json_bytes, ownership_env  # noqa: E402
from zoop_ai_pipeline import relation_rules as rules  # noqa: E402
from zoop_ai_pipeline.relation import document_view, next_attempt  # noqa: E402
from zoop_ai_pipeline.relation_contracts import IMPACT_POLICY, SCHEMA, digest  # noqa: E402

CATALOGUE = {"revision": "catalogue-rel-1", "companies": [
    {"companyId": "SYNTH-1", "name": "합성기업", "aliases": [], "ticker": None},
    {"companyId": "SYNTH-2", "name": "합성상대", "aliases": [], "ticker": None},
    {"companyId": "SYNTH-3", "name": "합성부품", "aliases": [], "ticker": None},
    {"companyId": "SYNTH-4", "name": "합성투자", "aliases": [], "ticker": None}]}
SUP = "합성부품은 합성기업에 배터리 부품을 공급한다😀 & 확인."
SUP2 = "합성기업은 합성상대에 완성차를 공급한다."
COMP = "합성기업과 합성상대는 같은 전기차 시장에서 경쟁한다."
INV = "합성투자는 합성부품에 지분을 투자했다."
VALID = "투자 약정은 2026년 1월 1일부터 2026년 12월 31일까지 유효하다."
CO = "합성기업과 합성상대가 함께 박람회에 참가했다."
EVT = "합성기업은 2026년 3분기 공급 계약을 발표했다."
GOOD = "시장은 합성기업의 실적 개선을 기대했다."
BAD = "합성기업의 일부 생산 라인은 가동을 중단했다."
QB = "합성기업은 4분기 신규 공장 착공을 알렸다."
MAIN_TEXT = (SUP, SUP2, COMP, INV, VALID, CO, EVT, GOOD, BAD)
CUSTOM = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
PRODUCER, VERIFIER = "zoop-relation-producer-1", "zoop-relation-verifier-1"


# ---------------------------------------------------------------- authored wire builders ------------------------------

def co(ref: str) -> dict:
    return {"kind": "company", "ref": ref}


def ev(ref: str) -> dict:
    return {"kind": "event", "ref": ref}


def tp(ref: str) -> dict:
    return {"kind": "topic", "ref": ref}


def step(relation_type: str, subject: dict, obj: dict, citations: list[dict]) -> dict:
    return {"type": relation_type, "subject": subject, "object": obj, "citations": citations}


def proposal(relation_type: str, subject: dict, obj: dict, citations: list[dict], *, connection: str = "direct", path: list[dict] | None = None,
             business: str | None = None, product: str | None = None, validity: dict | None = None, countries: list[str] | None = None,
             reason: str = "authored producer reason") -> dict:
    return {"type": relation_type, "subject": subject, "object": obj, "connection": connection, "businessScope": business, "productScope": product,
            "validity": validity or {"from": None, "until": None, "citations": []}, "countries": countries or [], "reason": reason,
            "citations": citations, "path": path or []}


def relation_reply(proposals: list[dict]) -> dict:
    return {"schemaVersion": "zoop-relation-response-1", "producerVersion": PRODUCER, "relations": proposals}


def verifier_reply(candidate: dict, **verdicts: str) -> dict:
    """Every claim supported with its own quotes, except claims overridden by id (use `step_1` for `step:1`)."""
    claims = []
    for claim in candidate["claims"]:
        verdict = verdicts.get(claim["claimId"].replace(":", "_"), "supported")
        claims.append({"claimId": claim["claimId"], "verdict": verdict, "quoteIds": claim["quoteIds"] if verdict == "supported" else claim["quoteIds"][:1]})
    return {"schemaVersion": "zoop-relation-verify-response-1", "verifierVersion": VERIFIER, "claims": claims}


def impact_item(company: str, direction: str, supporting: list[dict], opposing: list[dict], limitations: str | None = None) -> dict:
    return {"impactedCompanyId": company, "direction": direction, "reason": "authored impact reason", "supporting": supporting, "opposing": opposing,
            "limitations": limitations}


def impact_reply(items: list[dict]) -> dict:
    return {"schemaVersion": "zoop-impact-response-1", "producerVersion": "zoop-impact-producer-1", "impacts": items}


def impact_verifier_reply(candidate: dict, effects: dict[str, str] | None = None, *, target: str = "supported", default: str = "neutral") -> dict:
    """effects: quote text -> positive|negative|neutral (quotes are matched by exact text)."""
    by_text = effects or {}
    return {"schemaVersion": "zoop-impact-verify-response-1", "verifierVersion": "zoop-impact-verifier-1", "target": target,
            "quotes": [{"quoteId": q["quoteId"], "effect": by_text.get(q["text"], default)} for q in candidate["quotes"]]}


# ---------------------------------------------------------------- kit ------------------------------------------------

class RelKit(Kit):
    """Kit with a four-company catalogue plus authored producer/verifier fixtures and relation process runners."""

    def settings(self, prompt: str = PROMPT):
        from zoop_ai_pipeline import extraction_poc as poc
        from zoop_ai_pipeline.extraction_contracts import Catalogue
        return poc.settings(prompt, Catalogue.model_validate(CATALOGUE))

    def submit(self, job: str, incoming: dict, events: list[dict] | None = None, *, topic: bool = False, source_kind: str = "synthetic", prompt: str = PROMPT) -> dict:
        return {**super().submit(job, incoming, events, topic=topic, source_kind=source_kind, prompt=prompt), "catalogue": CATALOGUE}

    @staticmethod
    def rsubmit(job: str, upstream: dict, *, source_kind: str = "synthetic") -> dict:
        return {"schemaVersion": SCHEMA, "jobId": job, "provenance": {"sourceKind": source_kind, "executionMode": "replay", "recordingKind": "authored-test"},
                "upstream": {"jobId": upstream["jobId"], "inputDigest": upstream["inputDigest"]}}

    @staticmethod
    def rsel(job: str) -> dict:
        return {"schemaVersion": SCHEMA, "jobId": job}

    def fixture(self, role: str, name: str, records: list[tuple[str, str, dict]], *, synthetic: bool = True) -> Path:
        path = self.root / f"{name}.{role}.json"
        path.write_bytes(json_bytes({"format": "zoop-relation-replay-1", "role": role, "synthetic": synthetic, "recordingKind": "authored-test",
                                     "records": [{"stage": s, "requestDigest": d, "response": r} for s, d, r in records]}))
        return path

    def rel(self, command: str, request: dict, *, replay: Path | None = None, verifier: Path | None = None, state: str = "relation",
            crash: str | None = None, expected: int = 0, raw: bool = False, forbid_execution: bool = False):
        """Actual relation JSON subprocess with a socket audit hook (any network attempt aborts the process)."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM}
        guard = ("import os, sys, runpy\n"
                 "def _guard(event, args):\n"
                 " if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.bind'}:\n"
                 "  raise RuntimeError('network attempted')\n"
                 "sys.addaudithook(_guard)\n"
                 "from zoop_ai_pipeline.relation import Engine\n")
        hook = ""
        if forbid_execution:
            # A submit-only process exits 76 if it reaches stage execution or a call reservation.
            hook = "def _forbidden(*a, **k):\n os._exit(76)\nEngine._execute = Engine._reserve = Engine._receipted = _forbidden\n"
        if crash:
            kind, _, argument = crash.partition(":")
            hook = {
                "unknown": "Engine._receive = lambda *a: os._exit(75)",
                "receipt": "original = Engine._receive\ncount = [0]\ndef stop(self, *a):\n original(self, *a)\n count[0] += 1\n if count[0] == " + (argument or "1") + ":\n  os._exit(75)\nEngine._receive = stop",
                "stage": "Engine._stage_saved = lambda self, stage: os._exit(75) if stage == " + repr(argument) + " else None",
            }[kind]
        argv = [sys.executable, "-c", guard + hook + "\nrunpy.run_module('zoop_ai_pipeline.relation_cli', run_name='__main__')", command,
                "--state-dir", str(self.root / state), "--extraction-state-dir", str(self.root / "extraction"),
                "--ingestion-state-dir", str(self.root / "ingestion"), "--sources", str(self.registry_path)]
        if replay:
            argv += ["--replay", str(replay)]
        if verifier:
            argv += ["--verifier-replay", str(verifier)]
        child = subprocess.run(argv, input=json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=180)
        assert child.returncode == expected, (command, child.returncode, child.stdout.decode(), child.stderr.decode())
        assert not child.stderr or expected != 0, child.stderr.decode()
        if raw:
            return child.stdout.decode()
        return json.loads(child.stdout) if child.stdout else None

    def rel_job(self, command: str, request: dict, *, replay: Path | None = None, verifier: Path | None = None, state: str = "relation"):
        """Same orchestration in-process (focused tests); errors surface as ExtractionFailure."""
        from zoop_ai_pipeline.extraction import Sources
        from zoop_ai_pipeline.ingestion_contracts import Authority
        from zoop_ai_pipeline.relation import Engine, Fixtures, Store
        from zoop_ai_pipeline.relation_contracts import Revalidate, Review, Selector, Submit
        store = Store(self.root / state, self.root / "extraction", self.root / "ingestion")
        try:
            fixtures = Fixtures(replay.read_bytes() if replay else None, verifier.read_bytes() if verifier else None)
            engine = Engine(store, Sources(self.root / "ingestion", Authority(self.registry_path)), self.root / "extraction", self.root / "ingestion")
            if command == "run":
                return engine.run(Submit.model_validate(request), fixtures)
            if command == "submit":
                submit = Submit.model_validate(request)
                engine.freeze(submit)
                return engine.inspect(submit.job_id)
            if command == "review":
                return engine.review(Review.model_validate(request))
            if command == "revalidate":
                return engine.revalidate(Revalidate.model_validate(request), fixtures)
            job_id = Selector.model_validate(request).job_id
            return engine.resume(job_id, fixtures) if command == "resume" else getattr(engine, command)(job_id)
        finally:
            store.close()


def build_world(root: Path, countries: tuple[str, ...] = ()) -> SimpleNamespace:
    """Actual ingestion subprocess + actual S2 extraction (in-process) producing one READY upstream job with an event candidate,
    a snapshot event and a topic candidate. Nothing downstream may be written into it."""
    kit = RelKit(root)
    main, other = kit.ingest("docs", [{"supplier": "supplier-main", "html": page(*MAIN_TEXT)},
                                      {"supplier": "supplier-b", "html": page(QB, "착공은 2026년 11월 예정이다."), "published": None}])
    art = {"main": kit.article(main), "b": kit.article(other)}
    mention = {**kit.mention(art["main"], "m-main", [kit.evidence(art["main"], EVT)]), "countries": list(countries)}
    mention_b = kit.mention(art["b"], "m-b", [kit.evidence(art["b"], QB)], period="2026Q4", title="합성 공장 착공", action="공장 착공 알림")
    snapshot = kit.event("event-1", [(other, mention_b)])
    replay = kit.replay("s2").extract(art["main"], [mention]).compare(mention, "event-1", [(other, art["b"], mention_b)], art["main"], "DIFFERENT", "다른 사건", []).write()
    request = kit.submit("s2-job", main, [snapshot], topic=True)
    pending = kit.job("run", request, replay=replay)
    assert pending["failure"]["code"] == "topic_replay_required", pending["failure"]
    evc = pending["eventCandidates"][0]["eventCandidateId"]
    world = SimpleNamespace(kit=kit, refs={"main": main, "b": other}, art=art, evc=evc, event="event-1", s2_replay=replay, snapshot=snapshot)
    topic = topic_replay(kit, "s2-topic", {pending["failure"]["detail"]["topicRequestDigest"]: topic_response([{
        "label": "합성기업 계약과 공장", "criteria": "같은 기업의 서로 다른 사업 사건", "rationale": "authored replay",
        "members": [{"kind": "event-candidate", "ref": evc}, {"kind": "snapshot-event", "ref": "event-1"}],
        "citations": [world_cite(world, "main", EVT), world_cite(world, "b", QB)]}])})
    done = kit.job("resume", kit.job_selector("s2-job"), topic=topic)
    assert done["state"] == "ready" and len(done["topicCandidates"]) == 1, done
    world.s2, world.tp = done, done["topicCandidates"][0]["topicCandidateId"]
    world.s2_request, world.s2_topic = request, topic  # the exact authored S2 Submit and topic fixture, for the S2 HTTP service tests
    world.submit = kit.rsubmit("rel-main", done)
    return world


def world_cite(world: SimpleNamespace, name: str, quote: str, nth: int = 0) -> dict:
    article, ref = world.art[name], world.refs[name]
    start = -1
    for _ in range(nth + 1):
        start = article.body.index(quote, start + 1)
    return {"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "start": start, "end": start + len(quote), "quote": quote}


def forged_span(world: SimpleNamespace, name: str, quote: str, *, shift: int = 1) -> dict:
    """A real quote at a fabricated span: the text at [start, end) is not the quote."""
    c = world_cite(world, name, quote)
    return {**c, "start": c["start"] + shift, "end": c["end"] + shift}


def cross_separator(world: SimpleNamespace) -> dict:
    """A span over generated paragraph separators (not source text)."""
    quote = "확인.\n합성기업은 합성상대에"
    return world_cite(world, "main", quote)


def find(out: dict, relation_type: str, subject: str | None = None, obj: str | None = None, **match) -> dict:
    found = [r for r in out["relations"] if r["type"] == relation_type and (subject is None or r["subject"]["ref"] == subject) and (obj is None or r["object"]["ref"] == obj)
             and all(r.get(k) == v for k, v in match.items())]
    assert len(found) == 1, (relation_type, subject, obj, match, [(r["type"], r["subject"], r["object"]) for r in out["relations"]])
    return found[0]


# ---------------------------------------------------------------- authoring loop -----------------------------------

def converge(world: SimpleNamespace, job: str, proposals: list[dict], *, verify=None, impacts=None, effects=None, process: bool = False,
             seed: tuple[list, list] | None = None, limit: int = 30) -> dict:
    """Run/resume until the job stops for a reason authoring cannot satisfy. Each stop that asks for an unrecorded reply
    (`*_replay_required`/`*_replay_missing`) is answered with authored records derived from the real stored candidates, never from a mock echo.

    verify(relation) -> verifier reply | dict of claim overrides | None;  impacts(relation) -> impact items;  effects(impact) -> {quote: effect} or reply.
    """
    kit = world.kit
    producer, verifier = list(seed[0]) if seed else [], list(seed[1]) if seed else []
    request = kit.rsubmit(job, world.s2)
    call = kit.rel if process else kit.rel_job
    for _ in range(limit):
        replay = kit.fixture("producer", f"{job}-p", producer) if producer else None
        verifier_file = kit.fixture("verifier", f"{job}-v", verifier) if verifier else None
        out = call("run", request, replay=replay, verifier=verifier_file)
        failure = out.get("failure")
        if out["state"] != "stopped" or not failure or not failure["code"].endswith(("_replay_required", "_replay_missing")):
            out["fixtures"] = (producer, verifier)
            return out
        added = False

        def add(records: list, record: tuple[str, str, dict]) -> None:
            nonlocal added
            if not any(r[0] == record[0] and r[1] == record[1] for r in records):
                records.append(record)
                added = True

        if failure["detail"]["stage"] == "relation":
            add(producer, ("relation", failure["detail"]["requestDigest"], relation_reply(proposals)))
        for r in out.get("relations", []):
            if r["eligibility"]["status"] == "pending" and r["precheck"]["state"] == "pending":
                reply = verify(r) if verify else None
                add(verifier, ("verify-relation", digest(rules.verifier_request(r, next_attempt(r["history"], "initial"))),
                               reply if isinstance(reply, dict) and "claims" in reply else verifier_reply(r, **(reply or {}))))
            if r["eligibility"]["status"] == "eligible" and r["impact"]["status"] == "pending":
                docs = [document_view(kit.export(next(ref for ref in world.refs.values() if ref["documentId"] == q["documentId"] and ref["documentVersion"] == q["documentVersion"])))
                        for q in sorted({(q["documentId"], q["documentVersion"]): q for q in r["quotes"]}.values(), key=lambda q: (q["documentId"], q["documentVersion"]))]
                items = impacts(r) if impacts else []
                add(producer, ("impact", digest(rules.impact_request(r, docs)), items if isinstance(items, dict) else impact_reply(items)))
            for i in r["impact"]["candidates"]:
                if i["verdict"] is None and i["precheck"]["state"] == "pending":
                    reply = effects(i) if effects else None
                    attempt = {"kind": "initial", "seq": 0, "policyVersion": IMPACT_POLICY, "priorVerdictDigest": None}
                    add(verifier, ("verify-impact", digest(rules.impact_verifier_request(i, attempt)),
                                   reply if isinstance(reply, dict) and "quotes" in reply else impact_verifier_reply(i, reply)))
        if not added:
            out["fixtures"] = (producer, verifier)
            return out
    raise AssertionError("authoring did not converge")


# ======================================================================== actual subprocess smoke ===================

def tree(path: Path) -> dict:
    return {p.name: (stat.S_IMODE(p.stat().st_mode), p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(path.iterdir())} | {
        ".": (stat.S_IMODE(path.stat().st_mode), path.stat().st_mtime_ns)}


def main_proposals(world: SimpleNamespace) -> list[dict]:
    c = lambda text, nth=0: world_cite(world, "main", text, nth)  # noqa: E731
    return [
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(SUP)], product="배터리 부품"),                      # correct direction
        proposal("SUPPLIES", co("SYNTH-1"), co("SYNTH-3"), [c(SUP)], product="배터리 부품"),                      # reversed direction
        proposal("COMPETES_WITH", co("SYNTH-1"), co("SYNTH-2"), [c(COMP)], business="전기차 시장"),
        proposal("COMPETES_WITH", co("SYNTH-2"), co("SYNTH-1"), [c(COMP)], business="전기차 시장"),                # reversed duplicate
        proposal("COMPETES_WITH", co("SYNTH-1"), co("SYNTH-2"), [c(COMP)], business="배터리 시장"),                # same pair, other scope
        proposal("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(SUP2)], product="완성차"),                          # same pair, other type
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-2"), [], connection="indirect", product="부품",
                 path=[step("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(SUP)]), step("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(SUP2)])]),
        proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-1"), [], connection="indirect",
                 path=[step("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(INV)]), step("INVESTS_IN", co("SYNTH-3"), co("SYNTH-1"), [])]),  # step uncited
        proposal("SUPPLIES", co("SYNTH-9"), co("SYNTH-1"), [c(SUP)], product="미상"),                              # unknown endpoint
        proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(INV)]),                                          # validity unknown
        proposal("SUPPLIES", co("SYNTH-1"), co("SYNTH-2"), [c(CO)]),                                             # co-mention only
        proposal("PARTICIPATES_IN", co("SYNTH-1"), ev(world.evc), [c(EVT)]),
        proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp(world.tp), [c(EVT)]),
        proposal("RELATES_TO_TOPIC", co("SYNTH-1"), tp(world.event), [c(EVT)]),                                  # event ID as topic alias
        proposal("SHARES_ISSUE", co("SYNTH-1"), co("SYNTH-2"), [c(CO)]),                                         # not a relationship proof
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [forged_span(world, "main", SUP)], product="허위 구간"),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [cross_separator(world)], product="구분자 구간"),
        proposal("INVESTS_IN", co("SYNTH-4"), co("SYNTH-3"), [c(INV)], validity={"from": "2026-01-01", "until": "2026-12-31", "citations": [c(VALID)]}),
        proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(SUP)], product="날짜 근거 없음", validity={"from": "2026-01-01", "until": None, "citations": []}),
    ]


def smoke(root: Path) -> dict:
    world = build_world(root)
    kit, checks = world.kit, []
    proposals = main_proposals(world)
    c = lambda text, nth=0: world_cite(world, "main", text, nth)  # noqa: E731

    def verify(r: dict):
        if r["type"] == "SUPPLIES" and r["subject"]["ref"] == "SYNTH-1" and r["object"]["ref"] == "SYNTH-3":
            return {"direction": "reversed"}
        if r["type"] == "SUPPLIES" and r["subject"]["ref"] == "SYNTH-1" and r["object"]["ref"] == "SYNTH-2" and r["productScope"] is None:
            return {"type": "insufficient", "direction": "insufficient"}
        return None

    def impacts(r: dict):
        if r["type"] == "SUPPLIES" and r["subject"]["ref"] == "SYNTH-3" and r["object"]["ref"] == "SYNTH-1" and r["connection"] == "direct" and r["productScope"] == "배터리 부품":
            return [impact_item("SYNTH-1", "positive", [c(GOOD)], [c(BAD)])]
        if r["type"] == "COMPETES_WITH" and r["businessScope"] == "전기차 시장":
            return [impact_item("SYNTH-1", "positive", [c(GOOD)], [])]
        if r["type"] == "SUPPLIES" and r["subject"]["ref"] == "SYNTH-1" and r["object"]["ref"] == "SYNTH-2":
            return [impact_item("SYNTH-2", "positive", [], [])]
        return []

    effects = lambda i: {GOOD: "positive", BAD: "negative"}  # noqa: E731
    before = {name: tree(root / name) for name in ("ingestion", "extraction")}
    out = converge(world, "rel-main", proposals, verify=verify, impacts=impacts, effects=effects, process=True)
    assert out["state"] == "ready" and out["usage"]["providerCalls"] == 0 and out["usage"]["modelCalls"] == 0, out.get("failure")
    states = {(r["type"], r["subject"]["ref"], r["object"]["ref"], r["productScope"], r["businessScope"], r["connection"]): r for r in out["relations"]}

    # 1. Direction: stated direction eligible; the reversed proposal is a distinct candidate held by the independent verifier.
    good = find(out, "SUPPLIES", "SYNTH-3", "SYNTH-1", productScope="배터리 부품")
    reversed_ = find(out, "SUPPLIES", "SYNTH-1", "SYNTH-3")
    assert good["eligibility"]["status"] == "eligible" and good["approved"] is False and good["relationCandidateId"] != reversed_["relationCandidateId"]
    assert reversed_["eligibility"]["status"] == "hold" and reversed_["eligibility"]["reasons"] == [{"code": "direction_reversed", "at": "direction"}]
    assert reversed_["impact"]["status"] == "not-applicable"
    checks.append("direction reversal held (independent verifier), stated direction eligible, no automatic flip")

    # 2/3. Competition normalized to one canonical pair; same pair keeps different type and scope separately.
    competes = [r for r in out["relations"] if r["type"] == "COMPETES_WITH"]
    assert len(competes) == 2 and {r["businessScope"] for r in competes} == {"전기차 시장", "배터리 시장"}
    market = next(r for r in competes if r["businessScope"] == "전기차 시장")
    assert (market["subject"]["ref"], market["object"]["ref"]) == ("SYNTH-1", "SYNTH-2") and market["proposalCount"] == 2 and market["reordered"] is True
    assert find(out, "SUPPLIES", "SYNTH-1", "SYNTH-2", productScope="완성차")["eligibility"]["status"] == "eligible"
    checks.append("symmetric competition canonical and duplicate-merged; same pair keeps type and business scope separately")

    # 4/5. Missing path step, unknown endpoint, direct vs 2-hop.
    two_hop = find(out, "SUPPLIES", "SYNTH-3", "SYNTH-2", connection="indirect")
    assert two_hop["eligibility"]["status"] == "eligible" and "connection" in [x["claimId"] for x in two_hop["claims"]] and len(two_hop["path"]) == 2
    uncited = find(out, "INVESTS_IN", "SYNTH-4", "SYNTH-1", connection="indirect")
    assert uncited["eligibility"]["status"] == "hold" and {"code": "path_step_uncited", "at": "step:2"} in uncited["eligibility"]["reasons"] and uncited["history"][0]["verifier"] == "not-called"
    assert find(out, "SUPPLIES", "SYNTH-9", "SYNTH-1")["eligibility"]["reasons"] == [{"code": "target_unknown", "at": "subject"}]
    checks.append("missing path step and unknown endpoint held privately; direct and 2-hop distinct and each step cited")

    # 6. Impact label and relation eligibility are separate.
    assert good["impact"]["candidates"][0]["verdict"]["label"] == "mixed" and good["eligibility"]["status"] == "eligible"
    assert market["impact"]["candidates"][0]["verdict"]["label"] == "positive"
    undetermined = find(out, "SUPPLIES", "SYNTH-1", "SYNTH-2", productScope="완성차")["impact"]["candidates"][0]["verdict"]
    assert undetermined["label"] == "undetermined" and undetermined["verifier"] == "not-called"
    assert out["counts"]["impactLabels"] == {"positive": 1, "negative": 0, "mixed": 1, "undetermined": 1}
    checks.append("mixed (both sides mapped) / positive / undetermined impacts; relation eligibility unchanged by impact uncertainty")

    # 7. Event vs topic are different endpoint kinds; SAME/SHARES_ISSUE/co-mention never prove a relationship.
    assert find(out, "PARTICIPATES_IN")["eligibility"]["status"] == "eligible" and find(out, "RELATES_TO_TOPIC", "SYNTH-1", world.tp)["eligibility"]["status"] == "eligible"
    assert find(out, "RELATES_TO_TOPIC", "SYNTH-1", world.event)["eligibility"]["reasons"] == [{"code": "event_id_not_topic", "at": "object"}]
    assert find(out, "SHARES_ISSUE")["eligibility"]["reasons"] == [{"code": "non_relationship_basis"}]
    comention = states[("SUPPLIES", "SYNTH-1", "SYNTH-2", None, None, "direct")]
    assert comention["eligibility"]["status"] == "hold" and {"code": "claim_insufficient", "at": "type"} in comention["eligibility"]["reasons"]
    checks.append("event participation and company-topic are explicit distinct kinds; event ID as topic, SHARES_ISSUE and co-mention never become relations")

    # 8. Exact Korean + emoji + entity citation; fabricated and separator spans rejected; unknown validity stays unknown.
    assert good["citations"][0]["quote"] == SUP and good["citations"][0]["end"] - good["citations"][0]["start"] == len(SUP) and good["validity"]["fromStatus"] == "unknown"
    assert find(out, "SUPPLIES", productScope="허위 구간")["eligibility"]["reasons"][0] == {"code": "citation_invalid", "at": "citations:1", "detail": "quote_mismatch"}
    assert find(out, "SUPPLIES", productScope="구분자 구간")["eligibility"]["reasons"][0]["detail"] == "raw_locator_mismatch"
    dated = [r for r in out["relations"] if r["type"] == "INVESTS_IN" and r["subject"]["ref"] == "SYNTH-4" and r["object"]["ref"] == "SYNTH-3"]
    assert {r["validity"]["fromStatus"] for r in dated} == {"unknown", "known"} and all(r["eligibility"]["status"] == "eligible" for r in dated)
    assert find(out, "SUPPLIES", productScope="날짜 근거 없음")["eligibility"]["reasons"] == [{"code": "validity_uncited"}]
    checks.append("exact Korean/emoji/entity quote; fabricated span and generated separator rejected; validity unknown unless cited")

    # 9. HOLD review allow only requests a new automatic attempt; it never publishes or bypasses verification.
    held = comention
    revision = held["eligibility"]["revision"]
    reviewed = kit.rel("review", {**kit.rsel("rel-main"), "relationCandidateId": held["relationCandidateId"], "expectedRevision": revision, "decision": "allow",
                                  "reviewer": "operator-a", "note": "authored review"})
    item = next(r for r in reviewed["relations"] if r["relationCandidateId"] == held["relationCandidateId"])
    assert item["eligibility"]["status"] == "hold" and item["eligibility"]["reviewPending"] is True and item["history"][-1]["effect"] == "revalidation-requested"
    stale = kit.rel("review", {**kit.rsel("rel-main"), "relationCandidateId": held["relationCandidateId"], "expectedRevision": revision, "decision": "allow",
                               "reviewer": "operator-a", "note": "stale"}, expected=2)
    assert stale["error"]["code"] == "review_revision_conflict"
    request = rules.verifier_request(item, next_attempt(item["history"], "revalidation"))
    again = kit.fixture("verifier", "reval", [("verify-relation", digest(request), verifier_reply(item, type="insufficient", direction="insufficient"))])
    revalidated = kit.rel("revalidate", {**kit.rsel("rel-main"), "relationCandidateId": held["relationCandidateId"], "expectedRevision": revision + 1}, verifier=again)
    item = next(r for r in revalidated["relations"] if r["relationCandidateId"] == held["relationCandidateId"])
    verdicts = [e for e in item["history"] if e["kind"] == "verdict"]
    assert item["eligibility"]["status"] == "hold" and item["eligibility"]["reviewPending"] is False and len(verdicts) == 2 and verdicts[0]["attempt"] != verdicts[1]["attempt"]
    assert verdicts[1]["attempt"]["policyVersion"] == "zoop-relation-revalidation-policy-1" and verdicts[1]["attempt"]["priorVerdictDigest"] is not None
    assert verdicts[0]["requestDigest"] != verdicts[1]["requestDigest"] and item["approved"] is False
    checks.append("HOLD admin allow only records a revalidation request; a distinct policy/attempt re-verifies and the prior verdict stays visible")

    # 10. The upstream S2/ingestion state was only read; nothing app/S1 was written; ledger is private.
    after = {name: tree(root / name) for name in ("ingestion", "extraction")}
    assert before == after
    assert sorted(p.name for p in (root / "relation").iterdir()) == ["relation.lock", "relation.sqlite3"]
    checks.append("upstream S2 and ingestion directories byte/mode/mtime unchanged; relation ledger private to its own directory")

    # 11. Receipt crash recovery: a saved receipt is validated/saved on resume without any additional call or fixture.
    generation = next(call["requestDigest"] for call in out["calls"] if call["stage"] == "relation")
    mini = kit.fixture("producer", "mini-p", [("relation", generation, relation_reply([proposals[0]]))])
    request = kit.rsubmit("rel-crash", world.s2)
    kit.rel("run", request, replay=mini, crash="receipt:1", expected=75)
    resumed = kit.rel("resume", kit.rsel("rel-crash"))
    assert resumed["state"] == "stopped" and resumed["failure"]["code"] == "verifier_replay_required" and sum(x["stage"] == "relation" for x in resumed["calls"]) == 1
    assert resumed["usage"]["replayCalls"] == 1 and resumed["stages"]["relation"]["relations"] == 1
    candidate = resumed["relations"][0]
    verdict_file = kit.fixture("verifier", "mini-v", [("verify-relation", digest(rules.verifier_request(candidate, next_attempt(candidate["history"], "initial"))), verifier_reply(candidate))])
    kit.rel("resume", kit.rsel("rel-crash"), verifier=verdict_file, crash="receipt:1", expected=75)
    after_crash = kit.rel("resume", kit.rsel("rel-crash"))
    assert after_crash["relations"][0]["eligibility"]["status"] == "eligible" and after_crash["usage"]["replayCalls"] == 2 and after_crash["failure"]["code"] == "producer_replay_required"
    lost_request = kit.rsubmit("rel-lost", world.s2)
    kit.rel("run", lost_request, replay=mini, crash="unknown", expected=75)
    lost = kit.rel("resume", kit.rsel("rel-lost"), replay=mini)
    assert lost["state"] == "reconciling" and lost["resumeMode"] == "reconcile_only" and lost["usage"]["replayCalls"] == 0 and lost["usage"]["startedWithoutReceipt"] == 1
    checks.append("process death after receipt resumes with zero additional calls and without the fixture; started-without-receipt is reconcile-only, never resent")

    # 11b. Death after a revalidation receipt is saved but before its verdict commits: resume appends the verdict, no fixture, no extra call.
    orphan = converge(world, "rel-orphan", [proposal("SUPPLIES", co("SYNTH-3"), co("SYNTH-1"), [c(SUP)], product="scope-hold")],
                      verify=lambda r: {"scope": "insufficient"}, process=True)
    held = find(orphan, "SUPPLIES", productScope="scope-hold")
    reviewed = kit.rel("review", {**kit.rsel("rel-orphan"), "relationCandidateId": held["relationCandidateId"], "expectedRevision": held["eligibility"]["revision"],
                                  "decision": "allow", "reviewer": "operator-a", "note": "authored review"})
    allowed = find(reviewed, "SUPPLIES", productScope="scope-hold")
    key = digest(rules.verifier_request(allowed, next_attempt(allowed["history"], "revalidation")))
    revalidation = kit.fixture("verifier", "orphan", [("verify-relation", key, verifier_reply(allowed))])
    kit.rel("revalidate", {**kit.rsel("rel-orphan"), "relationCandidateId": allowed["relationCandidateId"], "expectedRevision": allowed["eligibility"]["revision"]},
            verifier=revalidation, crash="receipt:1", expected=75)
    revalidation.unlink()
    stuck = kit.rel("inspect", kit.rsel("rel-orphan"))
    assert find(stuck, "SUPPLIES", productScope="scope-hold")["eligibility"]["status"] == "hold" and find(stuck, "SUPPLIES", productScope="scope-hold")["eligibility"]["reviewPending"] is True
    recovered = kit.rel("resume", kit.rsel("rel-orphan"))
    done = find(recovered, "SUPPLIES", productScope="scope-hold")
    assert done["eligibility"]["status"] == "eligible" and [e["kind"] for e in done["history"]] == ["verdict", "review", "verdict"] and done["history"][-1]["attempt"]["kind"] == "revalidation"
    assert recovered["usage"]["replayCalls"] == stuck["usage"]["replayCalls"] == 3 and done["history"][0] == find(stuck, "SUPPLIES", productScope="scope-hold")["history"][0]
    checks.append("process death after a revalidation receipt: resume (and revalidate) append the verdict from the saved receipt with no fixture, no extra call and prior history intact")

    # 12. Forged upstream, bad fixture and revoked rights fail closed without exposing private text.
    forged = kit.rel("run", {**kit.rsubmit("rel-forged", world.s2), "upstream": {"jobId": "s2-job", "inputDigest": "0" * 64}}, expected=2)
    assert forged["error"]["code"] == "upstream_input_mismatch"
    duplicated = kit.fixture("producer", "dup", [("relation", generation, relation_reply([])), ("relation", generation, relation_reply([]))])
    assert kit.rel("run", kit.rsubmit("rel-dup", world.s2), replay=duplicated, expected=2)["error"]["code"] == "relation_replay_invalid"
    assert kit.rel("run", kit.rsubmit("rel-live", world.s2) | {"provenance": {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "authored-test"}}, expected=2)["error"]["code"] == "live_mode_unsupported"
    kit.registry["sources"][0]["grant"]["enabled"] = False
    kit.save_registry()
    text = kit.rel("inspect", kit.rsel("rel-main"), expected=2, raw=True)
    assert json.loads(text)["delivery"] == {"status": "withheld", "code": "source_unauthorized"} and SUP not in text and COMP not in text
    kit.registry["sources"][0]["grant"]["enabled"] = True
    kit.save_registry()
    assert kit.rel("inspect", kit.rsel("rel-main"))["delivery"]["status"] == "current"
    checks.append("forged upstream digest, invalid fixture, live mode and revoked rights fail closed; withheld output has no private text")

    # 13. Submit-only registration (actual processes): a ready current S2 upstream and NO fixture freeze a durable queued job; execution and its per-call
    #     producer/verifier fixtures belong to a later `resume`. A repeated submit only reports the stored job. `forbid_execution` ends a process with
    #     76 if it reaches stage execution or a call reservation.
    pending = kit.job("run", kit.submit("s2-pending", world.refs["main"], [world.snapshot], topic=True), replay=world.s2_replay)
    assert pending["state"] == "stopped"
    assert kit.rel("submit", kit.rsubmit("rel-premature", pending), expected=2, forbid_execution=True)["error"]["code"] == "upstream_not_ready"
    assert kit.rel("inspect", kit.rsel("rel-premature"), expected=2)["error"]["code"] == "job_not_found"
    request13, sel13 = kit.rsubmit("rel-submit", world.s2), kit.rsel("rel-submit")
    for fixtures in ({"replay": mini}, {"verifier": verdict_file}, {"replay": mini, "verifier": verdict_file}):
        assert kit.rel("submit", request13, expected=2, **fixtures)["error"]["code"] == "fixture_not_allowed"
    live13 = {**request13, "provenance": {**request13["provenance"], "executionMode": "live"}}
    assert kit.rel("submit", live13, expected=2)["error"]["code"] == "live_mode_unsupported"
    assert kit.rel("inspect", sel13, expected=2)["error"]["code"] == "job_not_found"
    queued = kit.rel("submit", request13, forbid_execution=True)
    assert queued["state"] == "queued" and queued["phase"] == "relation" and queued["resumeMode"] == "resume" and queued["failure"] is None
    assert queued["calls"] == [] and queued["usage"]["replayCalls"] == 0 and queued["relations"] == [] and queued["delivery"]["status"] == "current"
    assert queued["stages"]["relation"] == {"state": "pending"} and queued["binding"]["upstream"]["jobId"] == "s2-job"
    assert kit.rel("submit", request13, forbid_execution=True) == kit.rel("inspect", sel13) == queued
    conflicting = {**request13, "upstream": {"jobId": "s2-pending", "inputDigest": pending["inputDigest"]}}
    assert kit.rel("submit", conflicting, expected=2, forbid_execution=True)["error"]["code"] == "job_input_conflict"
    assert kit.rel("inspect", sel13) == queued
    reference = converge(world, "rel-submit-reference", [proposals[0]], process=True)
    assert reference["state"] == "ready" and reference["relations"][0]["eligibility"]["status"] == "eligible"
    producer13 = kit.fixture("producer", "rel-submit-p", reference["fixtures"][0])
    verifier13 = kit.fixture("verifier", "rel-submit-v", reference["fixtures"][1])
    grant = kit.registry["sources"][0]["grant"]
    grant["revision"] = "rights-2"
    kit.save_registry()
    moved = kit.rel("inspect", sel13, expected=2)
    assert moved["state"] == "queued" and moved["delivery"] == {"status": "withheld", "code": "grant_revision_changed"} and moved["calls"] == []
    stopped13 = kit.rel("resume", sel13, replay=producer13, verifier=verifier13, expected=2)
    assert stopped13["state"] == "stopped" and stopped13["failure"]["code"] == "grant_revision_changed" and stopped13["calls"] == [] and stopped13["usage"]["replayCalls"] == 0
    grant["revision"] = "rights-1"
    kit.save_registry()
    again = kit.rel("submit", request13, forbid_execution=True)
    assert again["state"] == "stopped" and again["failure"]["code"] == "grant_revision_changed" and again["calls"] == [] and again["delivery"]["status"] == "current"
    done13 = kit.rel("resume", sel13, replay=producer13, verifier=verifier13)
    assert done13["state"] == "ready" and done13["counts"] == reference["counts"] and done13["usage"]["replayCalls"] == reference["usage"]["replayCalls"]
    assert done13["relations"][0]["relationCandidateId"] == reference["relations"][0]["relationCandidateId"]
    assert kit.rel("submit", request13, forbid_execution=True) == done13
    cancel13, cancel_selector = kit.rsubmit("rel-submit-cancel", world.s2), kit.rsel("rel-submit-cancel")
    kit.rel("submit", cancel13, forbid_execution=True)
    cancelled13 = kit.rel("cancel", cancel_selector, expected=2)
    assert cancelled13["state"] == "cancelled" and cancelled13["resumeMode"] == "none" and cancelled13["calls"] == [] and cancelled13["delivery"] == {"status": "withheld", "code": "job_cancelled"}
    assert kit.rel("resume", cancel_selector, replay=producer13, verifier=verifier13, expected=2) == cancelled13
    assert kit.rel("submit", cancel13, expected=2, forbid_execution=True) == cancelled13
    checks.append("submit-only: premature (non-ready) upstream refused without a job, fixtures refused, durable queued job with zero attempts, idempotent same submit, conflicting upstream, "
                  "rights revision change before execution stops resume without calls, duplicate submit never resumes a stopped/ready/cancelled job, resume completes with per-call fixtures, queued cancel")
    return {"status": "passed", "schemaVersion": SCHEMA, "checks": checks, "providerCalls": 0, "modelCalls": 0,
            "networkAttempts": "audit hook rejected socket use in every CLI subprocess; none occurred"}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zoop-s3-smoke-") as temporary:
        root = Path(temporary).resolve()
        result = smoke(root)
    assert not root.exists()
    result["temporaryStateCleanup"] = {"removed": True, "root": str(root)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
