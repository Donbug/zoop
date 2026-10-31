#!/usr/bin/env python3
"""Authored HTML -> actual ingestion + extraction JSON subprocesses. Fresh owned state is always removed.

Replay here is authored response replay, not independent AI inference: no network, no model, no original PoC state.
"""
from __future__ import annotations

import html as htmllib
import hashlib
import http.server
import json
import os
import subprocess
import sys
import shutil
import tempfile
import threading
import stat
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts.ingestion_smoke import OfflineFixture, exact_check, json_bytes, ownership_env  # noqa: E402
from zoop_ai_pipeline import extraction_replay as analysis  # noqa: E402
from zoop_ai_pipeline.extraction_contracts import REPLAY_FORMAT, SCHEMA, TOPIC_RESPONSE, Catalogue, Mention, digest  # noqa: E402

PROMPT = "zoop-extraction-authored-1"
LIVE_PROMPT = "zoop-extraction-live-label-1"  # an operator label: the prompt the provider is actually given is frozen in the runtime binding
INGESTION_SCHEMA = "zoop-ingestion-s2-1"
CATALOGUE = {"revision": "catalogue-1", "companies": [
    {"companyId": "SYNTH-1", "name": "합성기업", "aliases": [], "ticker": None},
    {"companyId": "SYNTH-2", "name": "합성상대", "aliases": [], "ticker": None}]}
CUSTOM = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
Q3 = "합성기업은 2026년 3분기 공급 계약을 발표했다😀 & 확인."
Q3B = "합성기업이 3분기 공급 계약 체결을 공개했다."


def page(*paragraphs: str) -> bytes:
    return ("<html><body><article>" + "".join(f"<p>{htmllib.escape(p, quote=False)}</p>" for p in paragraphs) + "</article></body></html>").encode()


class Kit(OfflineFixture):
    """Authored sources, ingestion state, replay authoring and process runners."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.rounds = 0

    # ---- ingestion ----------------------------------------------------------------------------------------------
    def ingest(self, name: str, documents: list[dict], *, slot: str | None = None) -> list[dict]:
        """documents: [{"supplier": str|None, "html": bytes, "published": iso|None, "url": str, "publisher": str|None}] -> exact observation refs.

        `publisher` is the operator-declared outlet written into the real fixture item (absent or None: unspecified, no key)."""
        items, bodies = [], {}
        for index, document in enumerate(documents):
            ref = f"d{index}"
            bodies[ref] = document["html"]
            item = self.item(f"c{index}", document["supplier"], document.get("url", f"https://example.invalid/{name}/{index}"), ref=ref, publisher=document.get("publisher"))
            item["publishedAt"] = document.get("published", "2026-10-08T00:00:00+00:00")
            items.append(item)
        manifest = self.manifest(name, [items], bodies=bodies, coverage=slot)
        rid = f"round-{name}"
        result = self.cli("run", self.request(manifest, rid, self.rounds, {"from": slot, "through": slot} if slot else None), state="ingestion", manifest=manifest)
        self.rounds += 1
        assert result["state"] == "complete" and result["counts"]["textReady"] == len(documents), result
        return [{"roundId": rid, "sourceId": "synthetic-source", "page": r["page"], "ordinal": r["ordinal"], "documentId": r["documentId"],
                 "rawVersion": r["rawVersion"], "documentVersion": r["documentVersion"]} for r in result["documentRefs"]]

    def export(self, ref: dict) -> dict:
        """Authorized exact observation export through the installed ingestion code (in-process authoring helper)."""
        from zoop_ai_pipeline.ingestion import Ingestor, Store
        from zoop_ai_pipeline.ingestion_contracts import Authority, Export
        store = Store(self.root / "ingestion", existing=True)
        try:
            return Ingestor(store, Authority(self.registry_path)).export(Export.model_validate({"schemaVersion": INGESTION_SCHEMA, **ref}))
        finally:
            store.close()

    def article(self, ref: dict):
        return analysis.article(self.export(ref), True)

    # ---- authored contents -----------------------------------------------------------------------------------
    @staticmethod
    def evidence(article, quote: str, nth: int = 0, span: bool = True) -> dict:
        start = -1
        for _ in range(nth + 1):
            start = article.body.index(quote, start + 1)
        base = {"article_id": article.article_id, "article_version": article.version, "quote": quote}
        return {**base, "start": start, "end": start + len(quote)} if span else {**base, "start": None, "end": None}

    def mention(self, article, mention_id: str, evidence: list[dict], *, period="2026Q3", event_time=None, title="합성 공급 계약", action="공급 계약 발표", status="announced") -> dict:
        return {"mention_id": mention_id, "article_id": article.article_id, "article_version": article.version, "title": title,
                "event_type": "supply_contract", "action": action, "target": "공급 계약", "event_time": event_time, "period": period,
                "assertion_status": status, "participants": [{"company_id": "SYNTH-1", "name": "합성기업", "role": "issuer"}],
                "evidence": evidence, "keywords": [], "background": False, "countries": []}

    @staticmethod
    def catalogue() -> Catalogue:
        return Catalogue.model_validate(CATALOGUE)

    def replay(self, name: str) -> "Replay":
        return Replay(self, name)

    # ---- requests ---------------------------------------------------------------------------------------------
    @staticmethod
    def event(event_id: str, members: list[tuple[dict, dict]], revision: str = "rev-1") -> dict:
        return {"eventId": event_id, "revision": revision, "members": [{"observation": ref, "mention": mention} for ref, mention in members]}

    def submit(self, job: str, incoming: dict, events: list[dict] | None = None, *, topic: bool = False, source_kind: str = "synthetic", prompt: str = PROMPT) -> dict:
        return {"schemaVersion": SCHEMA, "jobId": job, "provenance": {"sourceKind": source_kind, "executionMode": "replay", "recordingKind": "authored-test"},
                "promptVersion": prompt, "incoming": incoming, "catalogue": CATALOGUE, "snapshot": {"revision": "snapshot-1", "events": events or []},
                "topic": {"producerVersion": "zoop-topic-replay-producer-1"} if topic else None}

    def submit_live(self, job: str, incoming: dict, events: list[dict] | None = None, *, topic: bool = False, source_kind: str = "synthetic", prompt: str = LIVE_PROMPT) -> dict:
        """A live job request: the provenance pair is executionMode live + recordingKind provider; `sourceKind` stays the truth about the documents."""
        request = self.submit(job, incoming, events, topic=topic, source_kind=source_kind, prompt=prompt)
        return {**request, "provenance": {"sourceKind": source_kind, "executionMode": "live", "recordingKind": "provider"}}

    def allow_model_send(self, runtime, stages=("extract", "compare", "topic")) -> None:
        """Grant exactly the model-send right the runtime will ask for: the operation, its purposes and its recipients (the live authority is only this registry)."""
        grant = self.registry["sources"][0]["grant"]
        grant["allowedOperations"] = ["read", "store", "quote-display", "model-send"]
        grant["purposes"] = [runtime.purpose(stage) for stage in stages]
        grant["recipients"] = sorted({runtime.recipient(stage) for stage in stages})
        self.save_registry()

    @staticmethod
    def job_selector(job: str) -> dict:
        return {"schemaVersion": SCHEMA, "jobId": job}

    # ---- process runner -------------------------------------------------------------------------------------
    def run(self, command: str, request: dict, *, state: str = "extraction", replay: Path | None = None, topic: Path | None = None,
            crash: str | None = None, expected: int = 0, sources: bool = True, raw: bool = False, forbid_execution: bool = False,
            live: dict | None = None, extra: tuple = ()):
        """`forbid_execution` ends the process with 76 if it reaches stage execution, a replay model or a call reservation (a submit must not).

        `live` is the child environment of a live job (gate, endpoints, keys, budget): only then may the process reach the network (loopback or the real
        provider); every other process keeps the audit hook that rejects any socket use. `extra` is extra CLI arguments (`--initial-only`)."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM, **(live or {})}
        guard = ("import os, sys, runpy\n"
                 + ("" if live else "def _guard(event, args):\n"
                    " if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.bind'}:\n"
                    "  raise RuntimeError('network attempted')\n"
                    "sys.addaudithook(_guard)\n")
                 + "from zoop_ai_pipeline.extraction import Extractor\n")
        hook = ""
        if forbid_execution:
            hook = ("from zoop_ai_pipeline.extraction import Fixtures\n"
                    "def _forbidden(*a, **k):\n os._exit(76)\n"
                    "Extractor._execute = Extractor._reserve = Extractor._receipted = Extractor._live_receipted = Fixtures.index = _forbidden\n")
        if crash:
            kind, _, argument = crash.partition(":")
            hook = {
                "unknown": "Extractor._receive = lambda *a: os._exit(75)",
                "receipt": "original = Extractor._receive\ncount = [0]\ndef stop(self, *a):\n original(self, *a)\n count[0] += 1\n if count[0] == " + (argument or "1") + ":\n  os._exit(75)\nExtractor._receive = stop",
                "stage": "Extractor._stage_saved = lambda self, stage: os._exit(75) if stage == " + repr(argument) + " else None",
            }[kind]
        argv = [sys.executable, "-c", guard + hook + "\nrunpy.run_module('zoop_ai_pipeline.extraction_cli', run_name='__main__')", command, *extra]
        argv += ["--state-dir", str(self.root / state), "--ingestion-state-dir", str(self.root / "ingestion")]
        if sources:
            argv += ["--sources", str(self.registry_path)]
        if replay:
            argv += ["--replay", str(replay)]
        if topic:
            argv += ["--topic-replay", str(topic)]
        child = subprocess.run(argv, input=json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=120)
        assert child.returncode == expected, (command, child.returncode, child.stdout.decode(), child.stderr.decode())
        assert not child.stderr or expected != 0, child.stderr.decode()
        if raw:
            return child.stdout.decode()
        return json.loads(child.stdout) if child.stdout else None

    def job(self, command: str, request: dict, *, replay: Path | None = None, topic: Path | None = None, state: str = "extraction"):
        """Same orchestration in-process (focused tests); errors surface as ExtractionFailure."""
        from zoop_ai_pipeline.extraction import Extractor, Fixtures, Sources, Store
        from zoop_ai_pipeline.extraction_contracts import Selector, Submit
        from zoop_ai_pipeline.ingestion_contracts import Authority
        store = Store(self.root / state, self.root / "ingestion")
        try:
            fixtures = Fixtures(replay.read_bytes() if replay else None, topic.read_bytes() if topic else None)
            extractor = Extractor(store, Sources(self.root / "ingestion", Authority(self.registry_path)))
            if command == "run":
                return extractor.run(Submit.model_validate(request), fixtures)
            if command == "submit":
                submit = Submit.model_validate(request)
                extractor.freeze(submit, fixtures)
                return extractor.inspect(submit.job_id)
            job_id = Selector.model_validate(request).job_id
            return extractor.resume(job_id, fixtures) if command == "resume" else getattr(extractor, command)(job_id)
        finally:
            store.close()


class Replay:
    """Authored zoop-analysis-replay-1 builder: each response is keyed by the digest of the exact request it answers (production preimages)."""

    def __init__(self, kit: Kit, name: str, *, synthetic: bool = True, prompt: str = PROMPT):
        self.kit, self.name, self.prompt, self.catalogue = kit, name, prompt, kit.catalogue()
        self.doc = {"format": REPLAY_FORMAT, "synthetic": synthetic, "recordingKind": "authored-test", "promptVersion": prompt,
                    "analysisVersion": "authored-analysis-1", "records": []}

    def _record(self, stage: str, request: dict, response) -> None:
        self.doc["records"].append({"stage": stage, "requestDigest": analysis.request_digest(stage, request, self.doc["analysisVersion"]), "response": response})

    def extract(self, article, mentions: list[dict], *, response=None) -> "Replay":
        self._record("extract", analysis.extract_input(article, self.prompt, self.catalogue), response if response is not None else {"mentions": mentions})
        return self

    def compare(self, mention: dict, event_id: str, members: list[tuple[dict, object, dict]], article, relation: str, reason: str, evidence: list[dict]) -> "Replay":
        """members: [(observationRef, Article, Mention dict)]; whole event and its articles by document key."""
        seen, articles = set(), []
        for ref, member_article, _ in members:
            if digest(ref) not in seen:
                seen.add(digest(ref))
                articles.append(member_article)
        request = analysis.compare_input(Mention.model_validate(mention), event_id, [Mention.model_validate(m) for _, _, m in members], articles, article)
        self._record("compare", request, {"relation": relation, "reason": reason, "evidence": evidence})
        return self

    def write(self) -> Path:
        path = self.kit.root / f"{self.name}.replay.json"
        path.write_bytes(json_bytes(self.doc))
        return path


def topic_replay(kit: Kit, name: str, records: dict[str, dict], *, synthetic: bool = True) -> Path:
    path = kit.root / f"{name}.topic.json"
    path.write_bytes(json_bytes({"format": "zoop-topic-replay-1", "synthetic": synthetic, "recordingKind": "authored-test", "producerVersion": "zoop-topic-replay-producer-1",
                                 "records": [{"requestDigest": key, "response": response} for key, response in records.items()]}))
    return path


def topic_response(topics: list[dict]) -> dict:
    return {"schemaVersion": "zoop-topic-response-1", "producerVersion": "zoop-topic-replay-producer-1", "topics": topics}


def topic_citation(ref: dict, article, quote: str) -> dict:
    start = article.body.index(quote)
    return {"documentId": ref["documentId"], "documentVersion": ref["documentVersion"], "start": start, "end": start + len(quote), "quote": quote}


# ======================================================================== actual subprocess smoke ===================

def smoke(root: Path) -> dict:
    kit = Kit(root)
    a1, a2, b, c = kit.ingest("docs", [
        {"supplier": "supplier-a1", "html": page(Q3, "계약 상대는 합성상대다.")},
        {"supplier": "supplier-a2", "html": page(Q3B, "상대는 합성상대로 확인됐다.")},
        {"supplier": "supplier-b", "html": page("합성기업은 4분기 신규 공장 착공을 알렸다.", "착공은 2026년 11월 예정이다."), "published": None},
        {"supplier": "supplier-c", "html": page("합성기업은 2026년 4분기 공급 계약을 발표했다.", "계약 상대는 합성상대다.")}])
    art = {name: kit.article(ref) for name, ref in (("a1", a1), ("a2", a2), ("b", b), ("c", c))}
    m1 = kit.mention(art["a1"], "m1", [kit.evidence(art["a1"], Q3)])
    m2 = kit.mention(art["a2"], "m2", [kit.evidence(art["a2"], Q3B)])
    mb = kit.mention(art["b"], "mb", [kit.evidence(art["b"], "합성기업은 4분기 신규 공장 착공을 알렸다.")], period="2026Q4", title="합성 공장 착공", action="공장 착공 알림")
    mc = kit.mention(art["c"], "mc", [kit.evidence(art["c"], "합성기업은 2026년 4분기 공급 계약을 발표했다.")], period="2026Q4")
    checks = []

    # 1. First document: no snapshot -> new event candidate; exact citation validated by S1 exact and ingestion resolver.
    first = kit.run("run", kit.submit("job-a1", a1), replay=kit.replay("r-a1").extract(art["a1"], [m1]).write())
    assert first["state"] == "ready" and first["stages"]["compare"]["comparisons"] == 0, first
    candidate = first["eventCandidates"][0]
    assert candidate["state"] == "candidate" and candidate["approved"] is False and candidate["disposition"]["status"] == "new-event-candidate"
    assert candidate["eventCandidateId"].startswith("evc-") and candidate["mentionCandidateId"].startswith("mc-")
    assert candidate["document"]["documentId"] == a1["documentId"] and candidate["eventCandidateId"] != a1["documentId"]
    citation = candidate["citations"][0]
    selector = kit.selector("round-docs", documentId=a1["documentId"], documentVersion=a1["documentVersion"])
    inspected = kit.cli("inspect", selector, state="ingestion")["document"]
    assert citation["quote"] == Q3 and inspected["text"][citation["start"]:citation["end"]] == Q3 and citation["end"] - citation["start"] == len(Q3) == 34
    exact_check(inspected, citation["start"], citation["end"])
    assert first["usage"]["replayCalls"] == 1 and first["usage"]["paidModelCalls"] == 0
    checks.append("event candidate with exact Korean/emoji/entity citation (S1 exact + ingestion resolver)")

    # 2. Separate document, same event: grounded SAME against a frozen whole event -> same-event candidate, distinct identities.
    event1 = kit.event("event-1", [(a1, m1)])
    r2 = kit.replay("r-a2").extract(art["a2"], [m2]).compare(m2, "event-1", [(a1, art["a1"], m1)], art["a2"], "SAME", "같은 3분기 계약",
        [kit.evidence(art["a2"], Q3B), kit.evidence(art["a1"], Q3)])
    second = kit.run("run", kit.submit("job-a2", a2, [event1]), replay=r2.write())
    cand2 = second["eventCandidates"][0]
    assert cand2["disposition"] == {**cand2["disposition"], "status": "same-event-candidate", "targetEventId": "event-1"}
    assert {x["documentId"] for x in (a1, a2)} == {a1["documentId"], a2["documentId"]} and a1["documentId"] != a2["documentId"]
    assert cand2["eventCandidateId"] != candidate["eventCandidateId"] and len(cand2["comparisons"][0]["citations"]) == 2
    checks.append("two documents, same event: SAME grounded in both documents, distinct document/mention/event identities")

    # 3. Distinct event, same topic: separate producer, explicit membership and exact document citations.
    r3 = kit.replay("r-b").extract(art["b"], [mb]).compare(mb, "event-1", [(a1, art["a1"], m1)], art["b"], "DIFFERENT", "다른 분기 사건", [])
    pending = kit.run("run", kit.submit("job-b", b, [event1], topic=True), replay=r3.write())
    assert pending["state"] == "stopped" and pending["failure"]["code"] == "topic_replay_required" and pending["stages"]["compare"]["state"] == "complete"
    request_digest = pending["failure"]["detail"]["topicRequestDigest"]
    event_b = pending["eventCandidates"][0]["eventCandidateId"]
    assert pending["eventCandidates"][0]["disposition"]["status"] == "new-event-candidate"
    topic = topic_replay(kit, "t-b", {request_digest: topic_response([{
        "label": "합성기업 계약과 공장 투자", "criteria": "같은 기업의 서로 다른 후속 사업 사건을 한 주제로 묶는다.", "rationale": "authored replay",
        "members": [{"kind": "event-candidate", "ref": event_b}, {"kind": "snapshot-event", "ref": "event-1"}],
        "citations": [topic_citation(b, art["b"], "합성기업은 4분기 신규 공장 착공을 알렸다."), topic_citation(a1, art["a1"], Q3)]}])})
    done = kit.run("resume", kit.job_selector("job-b"), topic=topic)
    assert done["state"] == "ready" and len(done["topicCandidates"]) == 1 and done["usage"]["replayCalls"] == 3
    tp = done["topicCandidates"][0]
    assert tp["status"] == "candidate" and tp["approved"] is False and tp["topicCandidateId"].startswith("tp-") and len(tp["members"]) == 2
    assert tp["topicCandidateId"] not in {event_b, "event-1"} and done["eventCandidates"][0]["eventCandidateId"] == event_b
    checks.append("distinct events, same topic: separate producer receipt + stable topic candidate; resume made no extra extraction/compare call")

    # 4. Known contract conflicts downgrade a model SAME against any member; missing dates stay unknown, never invented.
    q4 = {**m2, "period": "2026Q4"}
    r4 = kit.replay("r-conflict").extract(art["a2"], [q4]).compare(q4, "event-1", [(a1, art["a1"], m1)], art["a2"], "SAME", "모델은 SAME", [kit.evidence(art["a2"], Q3B), kit.evidence(art["a1"], Q3)])
    conflict = kit.run("run", kit.submit("job-conflict", a2, [event1]), replay=r4.write())["eventCandidates"][0]
    assert conflict["comparisons"][0]["original"]["relation"] == "SAME" and conflict["comparisons"][0]["effective"] == {"relation": "DIFFERENT", "reason": "known event identity conflicts with an existing member", "rule": "all_member_incompatibility"}
    assert conflict["disposition"]["status"] == "new-event-candidate"
    undated = {**m2, "period": None, "event_time": None}
    undated_member = {**m1, "period": None, "event_time": None}
    r4b = kit.replay("r-undated").extract(art["a2"], [undated]).compare(undated, "event-1", [(a1, art["a1"], undated_member)], art["a2"], "SAME", "날짜 없음", [kit.evidence(art["a2"], Q3B), kit.evidence(art["a1"], Q3)])
    unknown = kit.run("run", kit.submit("job-undated", a2, [kit.event("event-1", [(a1, undated_member)])]), replay=r4b.write())["eventCandidates"][0]
    assert unknown["comparisons"][0]["effective"]["relation"] == "SAME" and unknown["disposition"]["status"] == "same-event-candidate"
    checks.append("conflicting contract periods downgrade SAME; missing dates stay unknown (SAME kept)")

    # 5. Two grounded SAME events: held with no winner and no transitive union.
    a3, rep = kit.ingest("more", [{"supplier": "supplier-a3", "html": page("합성기업은 3분기 공급 계약을 공시했다.", "공시 상대는 합성상대다.")},
                                   {"supplier": "supplier-rep", "html": page("반복 문장이다.", "반복 문장이다.", "끝.")}])
    art["a3"], art["rep"] = kit.article(a3), kit.article(rep)
    m3 = kit.mention(art["a3"], "m3", [kit.evidence(art["a3"], "합성기업은 3분기 공급 계약을 공시했다.")])
    r5 = kit.replay("r-multi").extract(art["a2"], [m2])
    for event_id, ref, article, mention, quote in (("event-1", a1, art["a1"], m1, Q3), ("event-3", a3, art["a3"], m3, "합성기업은 3분기 공급 계약을 공시했다.")):
        r5.compare(m2, event_id, [(ref, article, mention)], art["a2"], "SAME", "authored", [kit.evidence(art["a2"], Q3B), kit.evidence(article, quote)])
    multi = kit.run("run", kit.submit("job-multi", a2, [event1, kit.event("event-3", [(a3, m3)])]), replay=r5.write())["eventCandidates"][0]["disposition"]
    assert multi["status"] == "held" and multi["targetEventId"] is None and multi["sameTargets"] == ["event-1", "event-3"] and multi["reason"] == "multiple_same_events"
    checks.append("multiple grounded SAME events: held, no selected target")

    # 6. Exact code-point quotes: generated separator rejected; repeated quote needs the exact span.
    separated = kit.evidence(art["a1"], "확인.\n계약 상대는")
    sep = kit.run("run", kit.submit("job-sep", a1), replay=kit.replay("r-sep").extract(art["a1"], [m1, kit.mention(art["a1"], "m-sep", [separated])]).write())
    rejected = next(e for e in sep["eventCandidates"] if e["localMentionId"] == "m-sep")
    assert rejected["state"] == "rejected" and rejected["reason"] == "raw_locator_mismatch" and rejected["citations"] == []
    exact_check(inspected, separated["start"], separated["end"], False)
    null_span = kit.mention(art["rep"], "m-rep", [kit.evidence(art["rep"], "반복 문장이다.", span=False)])
    ambiguous = kit.run("run", kit.submit("job-rep", rep), replay=kit.replay("r-rep").extract(art["rep"], [null_span]).write())
    assert ambiguous["state"] == "stopped" and ambiguous["failure"]["code"] == "extraction_reply_invalid" and ambiguous["calls"][0]["verdict"] == "extraction_reply_invalid"
    second = kit.mention(art["rep"], "m-rep", [kit.evidence(art["rep"], "반복 문장이다.", nth=1)])
    exact = kit.run("run", kit.submit("job-rep2", rep), replay=kit.replay("r-rep2").extract(art["rep"], [second]).write())
    assert exact["eventCandidates"][0]["citations"][0]["start"] == art["rep"].body.rindex("반복 문장이다.")
    checks.append("generated separator rejected; repeated quote rejected without a span and exact with the second span")

    # 7. Raw-only change: equal Article.version, different documentVersion and every candidate identity.
    raw1, = kit.ingest("raw-1", [{"supplier": "supplier-raw", "html": page(Q3), "url": "https://example.invalid/raw"}])
    raw2, = kit.ingest("raw-2", [{"supplier": "supplier-raw", "html": page(Q3).replace(b"&amp;", b"&#38;"), "url": "https://example.invalid/raw"}])
    ra, rb = kit.article(raw1), kit.article(raw2)
    assert ra.version == rb.version and raw1["documentId"] == raw2["documentId"] and raw1["documentVersion"] != raw2["documentVersion"]
    mr = kit.mention(ra, "m-raw", [kit.evidence(ra, Q3)])
    r7 = kit.replay("r-raw").extract(ra, [mr]).write()
    one = kit.run("run", kit.submit("job-raw-1", raw1), replay=r7)["eventCandidates"][0]
    two = kit.run("run", kit.submit("job-raw-2", raw2), replay=r7)["eventCandidates"][0]
    assert one["mentionCandidateId"] != two["mentionCandidateId"] and one["eventCandidateId"] != two["eventCandidateId"]
    assert kit.run("run", kit.submit("job-raw-1", raw2), replay=r7, expected=2)["error"]["code"] == "job_input_conflict"
    checks.append("raw-only version change: equal Article.version, distinct candidate identities, same job/different version conflicts")

    # 8. Forged snapshot/citation and bad topic membership are never accepted.
    forged = {**m1, "article_version": "0" * 64}
    assert kit.run("run", kit.submit("job-forged-snapshot", a2, [kit.event("event-1", [(a1, forged)])]), replay=r2.write(), expected=2)["error"]["code"] == "snapshot_member_invalid"
    bad_cite = kit.replay("r-bad-cite").extract(art["a2"], [m2]).compare(m2, "event-1", [(a1, art["a1"], m1)], art["a2"], "SAME", "authored", [
        kit.evidence(art["a2"], Q3B), {**kit.evidence(art["a1"], Q3), "article_version": "f" * 64}]).write()
    stopped = kit.run("run", kit.submit("job-bad-cite", a2, [event1]), replay=bad_cite)
    assert stopped["failure"]["code"] == "comparison_reply_invalid" and stopped["calls"][-1]["verdict"] == "comparison_reply_invalid"
    assert kit.run("resume", kit.job_selector("job-bad-cite"), replay=bad_cite) == stopped
    pending_bad = kit.run("run", kit.submit("job-topic-bad", b, [event1], topic=True), replay=r3.write())
    candidate_b = pending_bad["eventCandidates"][0]["eventCandidateId"]
    bad_topic = topic_replay(kit, "t-bad", {pending_bad["failure"]["detail"]["topicRequestDigest"]: topic_response([{
        "label": "잘못된 주제", "criteria": "authored", "rationale": "authored", "members": [{"kind": "event-candidate", "ref": candidate_b}, {"kind": "event-candidate", "ref": "evc-unknown"}],
        "citations": [topic_citation(b, art["b"], "합성기업은 4분기 신규 공장 착공을 알렸다.")]}])})
    bad = kit.run("resume", kit.job_selector("job-topic-bad"), topic=bad_topic)
    assert bad["failure"]["code"] == "topic_member_unknown" and bad["topicCandidates"] == [] and bad["calls"][-1]["verdict"] == "topic_member_unknown"
    assert kit.run("resume", kit.job_selector("job-topic-bad")) == bad
    checks.append("forged snapshot member, forged comparison citation and unknown topic member rejected; rejected receipts are not resent")

    # 9. Revoked grant withholds every candidate/citation; a stale ready job never restores it.
    kit.registry["sources"][0]["grant"]["enabled"] = False
    kit.save_registry()
    text = kit.run("inspect", kit.job_selector("job-a2"), expected=2, raw=True)
    assert json.loads(text)["delivery"] == {"status": "withheld", "code": "source_unauthorized"} and Q3 not in text and Q3B not in text
    assert kit.run("resume", kit.job_selector("job-a2"), expected=2, raw=True) == text
    kit.registry["sources"][0]["grant"]["enabled"] = True
    kit.save_registry()
    assert kit.run("inspect", kit.job_selector("job-a2"))["delivery"]["status"] == "current"
    checks.append("revoked grant: candidates/citations withheld, no private text in output")

    # 10. Process death at receipt, started-without-receipt and stage commits; resume makes zero additional calls.
    r10 = kit.replay("r-crash").extract(art["a2"], [m2]).compare(m2, "event-1", [(a1, art["a1"], m1)], art["a2"], "SAME", "authored", [kit.evidence(art["a2"], Q3B), kit.evidence(art["a1"], Q3)]).write()
    kit.run("run", kit.submit("job-crash", a2, [event1]), replay=r10, crash="receipt:1", expected=75)
    kit.run("resume", kit.job_selector("job-crash"), replay=r10, crash="stage:extract", expected=75)
    kit.run("resume", kit.job_selector("job-crash"), replay=r10, crash="receipt:1", expected=75)
    r10.unlink()
    recovered = kit.run("resume", kit.job_selector("job-crash"))
    assert recovered["state"] == "ready" and recovered["usage"]["replayCalls"] == 2 and recovered["eventCandidates"][0]["disposition"]["status"] == "same-event-candidate"
    assert kit.run("resume", kit.job_selector("job-crash")) == recovered
    lost_replay = kit.replay("r-lost").extract(art["a1"], [m1]).write()
    kit.run("run", kit.submit("job-lost", a1), replay=lost_replay, crash="unknown", expected=75)
    lost = kit.run("resume", kit.job_selector("job-lost"), replay=lost_replay)
    assert lost["state"] == "reconciling" and lost["resumeMode"] == "reconcile_only" and lost["usage"]["replayCalls"] == 0 and lost["usage"]["startedWithoutReceipt"] == 1
    checks.append("process death after receipt/stage commit resumes with zero additional calls; started-without-receipt is reconcile-only, never resent")

    # 11. Review regressions: an invalid fixture never becomes a receipt, ungrounded snapshot members are refused,
    #     and the ingestion read side is really read-only (modes/bytes/files unchanged, no recovery/schema writes).
    duplicated = kit.replay("r-dup").extract(art["a1"], [m1]).extract(art["a1"], [m1]).write()
    invalid = kit.run("run", kit.submit("job-dup", a1), replay=duplicated)
    assert invalid["state"] == "stopped" and invalid["failure"]["code"] == "replay_fixture_invalid" and invalid["calls"] == []
    after_invalid = kit.run("resume", kit.job_selector("job-dup"))
    assert after_invalid["state"] == "stopped" and after_invalid["failure"]["code"] == "replay_fixture_required" and after_invalid["calls"] == []
    member_with_separator = kit.mention(art["a1"], "m-sep-member", [separated])
    refused = kit.run("run", kit.submit("job-sep-member", a2, [kit.event("event-1", [(a1, member_with_separator)])]), replay=r2.write(), expected=2)
    assert refused["error"]["code"] == "snapshot_member_unmapped"
    ingestion = kit.root / "ingestion"

    def tree() -> dict:
        return {p.name: (stat.S_IMODE(p.stat().st_mode), p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(ingestion.iterdir())} | {
            ".": (stat.S_IMODE(ingestion.stat().st_mode), ingestion.stat().st_mtime_ns)}

    os.chmod(ingestion, 0o750)
    os.chmod(ingestion / "ingestion.lock", 0o640)
    os.chmod(ingestion / "ingestion.sqlite3", 0o440)
    before = tree()
    kit.run("run", kit.submit("job-read-only", a2, [event1]), replay=r2.write())
    exported = kit.cli("export", {"schemaVersion": INGESTION_SCHEMA, **a1}, state="ingestion")
    assert exported["observation"]["documentId"] == a1["documentId"] and tree() == before
    assert sorted(before) == [".", "ingestion.lock", "ingestion.sqlite3"]
    os.chmod(ingestion / "ingestion.sqlite3", 0o600)
    os.chmod(ingestion / "ingestion.lock", 0o600)
    os.chmod(ingestion, 0o700)
    checks.append("invalid fixture never becomes a receipt; separator snapshot member refused; ingestion export/extraction read side leaves modes, bytes and files unchanged")

    # 12. Submit-only registration (actual processes): the frozen job is durable and offline, execution is a later `resume`, and a repeated
    #     submit only reports the stored job (never resumes, re-freezes or resets it) whatever its state. `forbid_execution` ends a process
    #     with 76 if it reaches stage execution, a replay model or a call reservation.
    r12, sel12 = kit.replay("r-submit").extract(art["a1"], [m1]).write(), kit.job_selector("job-submit")
    submitted = kit.submit("job-submit", a1)
    queued = kit.run("submit", submitted, replay=r12, forbid_execution=True)
    assert queued["state"] == "queued" and queued["phase"] == "extract" and queued["resumeMode"] == "resume" and queued["failure"] is None
    assert queued["calls"] == [] and queued["usage"]["replayCalls"] == 0 and queued["eventCandidates"] == [] and queued["delivery"]["status"] == "current"
    assert {s["state"] for s in queued["stages"].values()} == {"pending"} and len(queued["binding"]["replay"]["fixtureHash"]) == 64
    assert kit.run("submit", submitted, replay=r12, forbid_execution=True) == kit.run("inspect", sel12) == queued
    assert kit.run("submit", submitted, expected=2)["error"]["code"] == "replay_fixture_required"
    assert kit.run("submit", submitted, replay=r12, topic=r12, expected=2)["error"]["code"] == "fixture_not_allowed"
    live = {**submitted, "provenance": {**submitted["provenance"], "executionMode": "live", "recordingKind": "provider"}}
    assert kit.run("submit", live, replay=r12, expected=2)["error"]["code"] == "fixture_not_allowed"
    other12 = kit.replay("r-submit-other").extract(art["a1"], [m1])
    other12.doc["analysisVersion"] = "authored-analysis-2"
    for changed, fixture in (({**submitted, "snapshot": {"revision": "snapshot-2", "events": []}}, r12), (submitted, other12.write())):
        assert kit.run("submit", changed, replay=fixture, expected=2, forbid_execution=True)["error"]["code"] == "job_input_conflict"
    assert kit.run("inspect", sel12) == queued
    grant = kit.registry["sources"][0]["grant"]
    grant["revision"] = "rights-2"
    kit.save_registry()
    moved = kit.run("inspect", sel12, expected=2)
    assert moved["state"] == "queued" and moved["delivery"] == {"status": "withheld", "code": "grant_revision_changed"} and moved["calls"] == []
    stopped12 = kit.run("resume", sel12, replay=r12, expected=2)
    assert stopped12["state"] == "stopped" and stopped12["failure"]["code"] == "grant_revision_changed" and stopped12["calls"] == [] and stopped12["usage"]["replayCalls"] == 0
    grant["revision"] = "rights-1"
    kit.save_registry()
    again = kit.run("submit", submitted, replay=r12, forbid_execution=True)
    assert again["state"] == "stopped" and again["failure"]["code"] == "grant_revision_changed" and again["calls"] == [] and again["delivery"]["status"] == "current"
    done12 = kit.run("resume", sel12, replay=r12)
    assert done12["state"] == "ready" and done12["usage"]["replayCalls"] == 1 and done12["eventCandidates"][0]["disposition"]["status"] == "new-event-candidate"
    assert kit.run("submit", submitted, replay=r12, forbid_execution=True) == done12
    cancel_request, cancel_selector = kit.submit("job-submit-cancel", a1), kit.job_selector("job-submit-cancel")
    kit.run("submit", cancel_request, replay=r12, forbid_execution=True)
    cancelled12 = kit.run("cancel", cancel_selector, expected=2)
    assert cancelled12["state"] == "cancelled" and cancelled12["resumeMode"] == "none" and cancelled12["calls"] == [] and cancelled12["delivery"] == {"status": "withheld", "code": "job_cancelled"}
    assert kit.run("resume", cancel_selector, replay=r12, expected=2) == cancelled12
    assert kit.run("submit", cancel_request, replay=r12, expected=2, forbid_execution=True) == cancelled12
    checks.append("submit-only: durable queued job with zero attempts and no replay model, idempotent same submit, conflicting request/fixture, required/forbidden fixture arguments, "
                  "rights revision change before execution stops resume without calls, duplicate submit never resumes a stopped/ready/cancelled job, queued cancel")
    return {"status": "passed", "schemaVersion": SCHEMA, "checks": checks, "providerCalls": 0, "modelCalls": 0, "networkAttempts": "audit hook rejected socket use in every CLI subprocess; none occurred"}


# ======================================================================== live provider path ==========================
# Two entry points over the same scenario: `--live-loopback` runs it (plus a fault matrix) against a deterministic provider SIMULATOR on 127.0.0.1 with fake
# keys, no paid call; `--live` runs it ONCE against the real provider with the live environment the operator exported (gate, models, budget directory, keys).
# Neither asserts what a model decides: the structural invariants (provenance, binding, receipts, counts, rights, no resend, no secret in any state) hold
# whatever the answer is, and a legitimately held/rejected or unusable reply is reported as such rather than coerced.

LIVE_ENV_NAMES = ("ZOOP_AI_PIPELINE_LIVE_ENABLED", "ZOOP_AI_PIPELINE_LIVE_MODEL", "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT", "ZOOP_AI_PIPELINE_LIVE_MAX_OUTPUT_TOKENS",
                  "ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS", "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR", "ZOOP_AI_PIPELINE_LIVE_MAX_USD", "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS",
                  "ZOOP_AI_BASE_URL", "ZOOP_AI_API_KEY", "TYPESAFE_BASE_URL", "TYPESAFE_API_KEY", "TYPESAFE_VALIDATION_MODEL")
SECRET_NAMES = ("ZOOP_AI_API_KEY", "TYPESAFE_API_KEY")


def process_live_env() -> dict[str, str]:
    """The live variables of THIS process (real mode: exactly what the operator exported). Nothing else is ever handed to a child."""
    return {name: os.environ[name] for name in LIVE_ENV_NAMES if name in os.environ}


def no_secret_anywhere(root: Path, env: dict[str, str], *texts: str) -> None:
    """Neither a key nor its bearer header may be in any state file, ledger, WAL or delivered output."""
    secrets = [env[name].encode() for name in SECRET_NAMES if env.get(name)]
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        data = path.read_bytes()
        assert not any(secret in data for secret in secrets), path.name
    assert not any(secret.decode() in text for secret in secrets for text in texts)


def summary(result: dict) -> dict:
    """What a live run reports about itself: facts and counts, never the model's text."""
    return {"state": result["state"], "phase": result["phase"], "failure": result["failure"], "stages": {k: v["state"] for k, v in result["stages"].items()},
            "counts": result["counts"], "usage": result["usage"], "delivery": result["delivery"]["status"],
            "calls": [{k: c[k] for k in ("stage", "state", "verdict", "httpStatus", "model", "usage", "cost")} for c in result["calls"]]}


class LiveWorld:
    """Two synthetic documents (a frozen snapshot event over the first, the incoming second) and exactly the model-send grant the runtime asks for."""

    def __init__(self, root: Path, env: dict[str, str]):
        from zoop_ai_pipeline.live_runtime import LiveRuntime
        self.env = env
        previous = {name: os.environ.get(name) for name in LIVE_ENV_NAMES}
        os.environ.update(env)
        try:
            self.runtime = LiveRuntime.from_env()  # configuration only: no network, no key is needed
        finally:
            for name, value in previous.items():
                os.environ.pop(name, None) if value is None else os.environ.__setitem__(name, value)
        self.kit = kit = Kit(root)
        self.a1, self.a2 = kit.ingest("live-docs", [{"supplier": "supplier-a1", "html": page(Q3, "계약 상대는 합성상대다.")},
                                                     {"supplier": "supplier-a2", "html": page(Q3B, "상대는 합성상대로 확인됐다.")}])
        article = kit.article(self.a1)
        self.event1 = kit.event("event-1", [(self.a1, kit.mention(article, "m1", [kit.evidence(article, Q3)]))])
        kit.allow_model_send(self.runtime)
        self.identity = self.runtime.binding()["identity"]

    def request(self, job: str, *, snapshot: bool = True, topic: bool = True) -> dict:
        return self.kit.submit_live(job, self.a2, [self.event1] if snapshot else [], topic=topic)

    def run(self, command: str, request: dict, *, env: dict | None = None, **options):
        return self.kit.run(command, request, live=self.env if env is None else env, **options)

    def documents(self) -> dict:
        found = {}
        for ref in (self.a1, self.a2):
            selector = self.kit.selector("round-live-docs", documentId=ref["documentId"], documentVersion=ref["documentVersion"])
            found[(ref["documentId"], ref["documentVersion"])] = self.kit.cli("inspect", selector, state="ingestion")["document"]["text"]
        return found


def check_delivered(world: LiveWorld, done: dict) -> None:
    """A ready live job: every call is a stored 2xx receipt, the counts add up, nothing is approved, and every citation is an exact source quote."""
    assert done["provenance"] == {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"} and "replay" not in done["binding"]
    usage, calls = done["usage"], done["calls"]
    assert {s["state"] for s in done["stages"].values()} == {"complete"} and done["delivery"]["status"] == "current" and usage["executionMode"] == "live"
    assert all(c["state"] == "received" and c["verdict"] is None and c["httpStatus"] == 200 for c in calls)
    assert usage["providerCalls"] == usage["receivedCalls"] == len(calls) and usage["startedWithoutReceipt"] == usage["unsentCalls"] == usage["replayCalls"] == 0
    assert all(c["recipient"] == world.runtime.recipient(c["stage"]) and c["purpose"] == world.runtime.purpose(c["stage"]) for c in calls)
    texts = world.documents()
    for candidate in done["eventCandidates"]:
        assert candidate["approved"] is False
        for citation in candidate["citations"] + [x for c in candidate["comparisons"] for x in c["citations"]]:
            assert texts[(citation["documentId"], citation["documentVersion"])][citation["start"]:citation["end"]] == citation["quote"]
    for topic in done["topicCandidates"]:
        assert topic["approved"] is False
        for citation in topic["citations"]:
            assert texts[(citation["documentId"], citation["documentVersion"])][citation["start"]:citation["end"]] == citation["quote"]


def live_scenario(world: LiveWorld, requests=None) -> dict:
    """submit (frozen binding, no call) -> automatic dispatch once -> nothing re-dispatchable -> env-free inspect -> no resend. `requests` counts provider hits."""
    kit, job = world.kit, "live-main"
    request, selector = world.request(job), kit.job_selector(job)
    queued = world.run("submit", request, forbid_execution=True)
    assert queued["state"] == "queued" and queued["calls"] == [] and queued["provenance"] == request["provenance"] and "replay" not in queued["binding"]
    live = queued["binding"]["live"]
    assert live["bindingDigest"] == world.identity == live["runtime"]["identity"] and live["runtime"] == world.runtime.binding() and live["analysisVersion"] == "live-" + world.identity
    assert queued["binding"]["adapter"]["version"] == "zoop-extraction-native-live-2" and queued["usage"]["executionMode"] == "live" and queued["usage"]["providerCalls"] == 0
    assert world.run("submit", request, forbid_execution=True) == queued and (requests is None or len(requests) == 0)
    assert world.run("submit", request, env={}, expected=2)["error"]["code"] == "live_not_enabled"  # a live freeze needs the gate; nothing was written for it
    done = world.run("resume", selector, extra=("--initial-only",))
    assert world.run("resume", selector, extra=("--initial-only",), expected=2) == {"schemaVersion": SCHEMA, "error": {"code": "initial_dispatch_taken"}}
    assert world.run("inspect", selector, env={}) == done, "inspect needs neither the environment nor a key"
    if done["state"] == "ready":
        check_delivered(world, done)
        sent = None if requests is None else len(requests)
        assert world.run("resume", selector) == done and (sent is None or len(requests) == sent), "a finished job is never re-sent"
    no_secret_anywhere(kit.root, world.env, json.dumps(done))
    return summary(done)


# ---- authored provider simulator: NOT an AI and never a stand-in for one -------------------------------------------------
# A deterministic OpenAI-compatible chat-completions server that answers each stage with a reply grounded in the exact projection the runtime sent. It exists
# only so the offline fault matrix can exercise the real live path (request building, budget, receipt, decode, parse, exact grounding) without a paid call.

FAKE_KEYS = {"ZOOP_AI_API_KEY": "sk-offline-simulator-openai-key", "TYPESAFE_API_KEY": "tsk-offline-simulator-jev-key"}


def first_reference(source: dict) -> dict:
    return {"segmentId": next(s["segmentId"] for s in source["segments"] if s["segmentId"] is not None and s["text"].strip())}


def simulated_answer(stage: str, projection: dict, sources: list[dict]) -> dict:
    if stage == "extract":
        article = projection["article"]
        evidence = first_reference(sources[0])
        return {"mentions": [{"mention_id": "m-sim-1", "article_id": article["article_id"], "article_version": article["article_version"], "title": "합성 공급 계약",
                              "event_type": "supply_contract", "action": "공급 계약 발표", "target": "공급 계약", "event_time": None, "period": "2026Q3",
                              "assertion_status": "announced", "participants": [{"company_id": "SYNTH-1", "name": "합성기업", "role": "issuer"}],
                              "evidence": [evidence], "keywords": [], "background": False, "countries": []}]}
    if stage == "compare":
        incoming, member = projection["article"], projection["issue"]["articles"][0]
        return {"relation": "SAME", "reason": "simulated: same 2026Q3 supply contract", "evidence": [
            first_reference(next(s for s in sources if s["article_version"] == a["article_version"])) for a in (incoming, member)]}
    if stage == "topic":
        # The request carries schemaVersion zoop-topic-request-1, but the reply contract (and the strict schema the provider enforces) pins the RESPONSE literal.
        return {"schemaVersion": TOPIC_RESPONSE, "producerVersion": projection["producerVersion"], "topics": [{
            "label": "합성 공급 계약", "criteria": "simulated: same company contract events", "rationale": "simulated grouping",
            "members": [{"kind": e["kind"], "ref": e["ref"]} for e in projection["events"]],
            "citations": [first_reference(d) for d in sources[:2]]}]}
    if stage == "relation":
        event = next(e for e in projection["events"] if e["origin"] == "event-candidate")
        document = event["documents"][0]
        src = next(s for s in sources if all(s[k] == document[k] for k in ("documentId", "documentVersion")))
        return {"schemaVersion": "zoop-relation-response-1", "producerVersion": "zoop-relation-producer-1", "relations": [{
            "type": "PARTICIPATES_IN", "subject": {"kind": "company", "ref": "SYNTH-1"}, "object": {"kind": "event", "ref": event["ref"]},
            "connection": "direct", "businessScope": None, "productScope": "공급 계약", "validity": {"from": None, "until": None, "citations": []},
            "countries": [], "reason": "synthetic control", "citations": [first_reference(src)], "path": []}]}
    if stage == "impact":
        return {"schemaVersion": "zoop-impact-response-1", "producerVersion": "zoop-impact-producer-1", "impacts": [{
            "impactedCompanyId": "SYNTH-1", "direction": "positive", "reason": "synthetic control",
            "supporting": [first_reference(sources[0])], "opposing": [], "limitations": None}]}
    raise AssertionError(stage)


def chat_reply(content: str, *, prompt_tokens: int = 1200, completion_tokens: int = 300, reasoning_tokens: int = 120) -> dict:
    return {"id": "chatcmpl-simulated", "object": "chat.completion", "model": "gpt-6-luna-simulated",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "prompt_tokens_details": {"cached_tokens": 0},
                      "completion_tokens_details": {"reasoning_tokens": reasoning_tokens}}}


def simulate(body: dict) -> dict:
    if "questions" in body:
        answers = {}
        for key, question in body["questions"].items():
            choices = list(question["criteria"])
            winner = "supported" if "supported" in choices else "positive"
            answers[key] = {"type": "choice", "choice": winner, "confidence": .95,
                            "probabilities": {c: .97 if c == winner else .03 / (len(choices) - 1) for c in choices}}
        return {"model": "jev-1.14.0", "answers": answers, "usage": {"input_tokens": 1200, "output_tokens": 0}}
    stage_input = json.loads(body["messages"][1]["content"])
    answer = simulated_answer(stage_input["stage"], stage_input["input"], stage_input["sources"])
    return chat_reply(json.dumps({**answer, "citationFormat": stage_input["citationFormat"]}, ensure_ascii=False))


class SimulatedProvider:
    """Loopback server for the OpenAI chat wire. `mode`: ok | garbage (HTTP 200, content is not JSON) | http500 | silent (connection closed, no reply).
    `requests` records every request that reached it, in order."""

    def __init__(self):
        self.mode, self.requests = "ok", []
        provider = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                provider.requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), "body": body})
                if provider.mode == "silent":
                    self.close_connection = True
                    return
                status = 500 if provider.mode == "http500" else 200
                reply = {"error": {"message": "simulated"}} if status == 500 else chat_reply("this is not json") if provider.mode == "garbage" else simulate(body)
                data = json.dumps(reply, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self) -> "SimulatedProvider":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def simulator_env(base_url: str, budget: Path, **changes: str) -> dict[str, str]:
    return {"ZOOP_AI_PIPELINE_LIVE_ENABLED": "1", "ZOOP_AI_PIPELINE_LIVE_MODEL": "gpt-6-luna", "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT": "high",
            "TYPESAFE_VALIDATION_MODEL": "jev-1.14.0", "ZOOP_AI_BASE_URL": base_url, "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR": str(budget),
            "ZOOP_AI_PIPELINE_LIVE_MAX_USD": "5", "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS": "40", "ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS": "10", **FAKE_KEYS, **changes}


def relation_scenario(world: LiveWorld, hits: list) -> dict:
    """Actual S3 module CLI over the completed S2 job and the same synthetic loopback provider."""
    kit = world.kit
    upstream = world.run("inspect", kit.job_selector("live-main"), env={})
    request = {"schemaVersion": "zoop-relation-s3", "jobId": "live-relation", "provenance": upstream["provenance"],
               "upstream": {"jobId": "live-main", "inputDigest": upstream["inputDigest"]}}
    common = ["--state-dir", str(kit.root / "relation"), "--extraction-state-dir", str(kit.root / "extraction"),
              "--ingestion-state-dir", str(kit.root / "ingestion"), "--sources", str(kit.registry_path)]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM}

    def run(command, value, live):
        child = subprocess.run([sys.executable, "-m", "zoop_ai_pipeline.relation_cli", command, *common], input=json_bytes(value),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**env, **(world.env if live else {})}, cwd=PIPELINE, timeout=120)
        assert child.returncode == 0 and not child.stderr, (child.returncode, child.stdout.decode(), child.stderr.decode())
        return json.loads(child.stdout)

    before = len(hits)
    done = run("run", request, True)
    assert done["state"] == "ready" and done["delivery"]["status"] == "current", done
    assert done["counts"]["eligibility"]["eligible"] == 1 and done["counts"]["impactLabels"]["positive"] == 1, done
    assert len(hits) == before + 4 and all(c["state"] == "received" and c["verdict"] is None for c in done["calls"])
    assert {c["stage"] for c in done["calls"]} == {"relation", "verify-relation", "impact", "verify-impact"}
    for hit in hits[before:]:
        key = "TYPESAFE_API_KEY" if hit["path"].endswith("systemone") else "ZOOP_AI_API_KEY"
        assert hit["authorization"] == "Bearer " + FAKE_KEYS[key]
    texts = world.documents()
    for c in done["relations"][0]["citations"]:
        assert texts[(c["documentId"], c["documentVersion"])][c["start"]:c["end"]] == c["quote"]
    selector = {"schemaVersion": "zoop-relation-s3", "jobId": "live-relation"}
    assert run("inspect", selector, False) == done and run("resume", selector, False) == done and len(hits) == before + 4
    return {"state": done["state"], "delivery": done["delivery"]["status"], "counts": done["counts"], "providerRequests": 4}


def loopback_smoke(root: Path) -> dict:
    """The live path through actual CLI subprocesses against the simulator: the main scenario plus every provider/process fault the contract names."""
    checks = []
    with SimulatedProvider() as provider:
        env = simulator_env(provider.base_url, root / "budget", TYPESAFE_BASE_URL=provider.base_url)
        world = LiveWorld(root / "world", env)
        kit, hits = world.kit, provider.requests
        kit.allow_model_send(world.runtime, ("extract", "compare", "topic", "relation", "verify-relation", "impact", "verify-impact"))

        report = live_scenario(world, hits)
        assert report["state"] == "ready" and report["usage"]["providerCalls"] == 3 == len(hits) and report["counts"]["topicCandidates"] == 1, report
        assert report["usage"]["inputTokens"] == 3 * 1200 and report["usage"]["outputTokens"] == 3 * 300 and report["usage"]["paidModelCalls"] == 3, report
        assert all(h["authorization"] == "Bearer " + FAKE_KEYS["ZOOP_AI_API_KEY"] for h in hits)
        assert not any(leak in h["body"]["messages"][1]["content"] for h in hits for leak in ("allow_model_send", "example.invalid", "operator-grant"))
        checks.append("main scenario: frozen live binding, one automatic dispatch, extract+compare+topic receipts, exact citations, env-free inspect, no resend, no key in any state file")
        relation_report = relation_scenario(world, hits)
        checks.append("S3 module CLI: relation+impact references expand after raw receipts, independent verifier requests, ready/current, env-free read and resume")

        # Provider silence after the request left: reconciling, never resent, usage unknown rather than zero.
        before, provider.mode = len(hits), "silent"
        silent = world.run("run", world.request("live-silent", topic=False))
        provider.mode = "ok"
        assert silent["state"] == "reconciling" and silent["resumeMode"] == "reconcile_only" and silent["failure"]["code"] == "live_response_unknown", silent
        assert len(hits) == before + 1 and silent["usage"]["startedWithoutReceipt"] == 1 and silent["usage"]["providerCalls"] == 1 and silent["usage"]["estimatedUsd"] is None
        assert [c["state"] for c in silent["calls"]] == ["started"] and silent["calls"][0]["httpStatus"] is None
        assert world.run("resume", kit.job_selector("live-silent")) == silent and len(hits) == before + 1
        cancelled = world.run("cancel", kit.job_selector("live-silent"), expected=2)
        assert cancelled["state"] == "cancelled" and len(hits) == before + 1
        checks.append("provider silence: started-without-receipt is reconciling, never resent, usage unknown not zero, cancel allowed")

        # A received reply that cannot be used stays durable and failed; another call never repairs it.
        for mode, code in (("garbage", "live_reply_not_json"), ("http500", "live_http_500")):
            job, before, provider.mode = f"live-{mode}", len(hits), mode
            failed = world.run("run", world.request(job, topic=False))
            provider.mode = "ok"
            assert failed["state"] == "stopped" and failed["failure"]["code"] == code and failed["calls"][0]["verdict"] == code, failed
            assert failed["calls"][0]["state"] == "received" and failed["usage"]["receivedCalls"] == 1 and len(hits) == before + 1
            assert world.run("resume", kit.job_selector(job)) == failed and len(hits) == before + 1
        checks.append("malformed 200 and HTTP 500 replies are stored receipts with a failed verdict; resume never calls the provider again")

        # Death after the provider answered but before the receipt was stored: indistinguishable from a lost reply, so reconcile-only.
        before = len(hits)
        world.run("run", world.request("live-lost", topic=False), crash="unknown", expected=75)
        lost = world.run("resume", kit.job_selector("live-lost"))
        assert lost["state"] == "reconciling" and lost["failure"]["code"] == "live_response_unknown" and len(hits) == before + 1 and lost["usage"]["startedWithoutReceipt"] == 1
        checks.append("process death before the receipt is stored: reconcile-only after exactly one provider request")

        # Death after the receipt is stored: recovery decodes the stored receipt with NO environment and NO key, and sends nothing.
        before = len(hits)
        world.run("run", world.request("live-recover", snapshot=False, topic=False), crash="receipt:1", expected=75)
        recovered = world.run("resume", kit.job_selector("live-recover"), env={})
        assert recovered["state"] == "ready" and recovered["usage"]["providerCalls"] == recovered["usage"]["receivedCalls"] == 1 and len(hits) == before + 1, recovered
        check_delivered(world, recovered)
        checks.append("process death after the receipt: resume with no environment/key decodes the stored receipt and makes zero provider calls")

        # Rights and configuration are re-checked against the CURRENT state before any send.
        before, grant = len(hits), kit.registry["sources"][0]["grant"]
        queued = world.run("submit", world.request("live-rights", snapshot=False, topic=False), forbid_execution=True)
        allowed, grant["allowedOperations"] = grant["allowedOperations"], ["read", "store", "quote-display"]
        kit.save_registry()
        denied = world.run("resume", kit.job_selector("live-rights"), expected=0)
        assert denied["state"] == "stopped" and denied["failure"]["code"] == "source_operation_denied" and denied["calls"] == [] and len(hits) == before, denied
        grant["allowedOperations"], grant["recipients"] = allowed, []
        kit.save_registry()
        assert world.run("resume", kit.job_selector("live-rights"))["failure"]["code"] == "source_purpose_or_recipient_denied" and len(hits) == before
        grant["recipients"] = sorted({world.runtime.recipient(s) for s in ("extract", "compare", "topic")})
        kit.save_registry()
        granted = world.run("resume", kit.job_selector("live-rights"))
        assert queued["state"] == "queued" and granted["state"] == "ready" and len(hits) == before + 1
        drifted = world.request("live-drift", snapshot=False, topic=False)
        world.run("submit", drifted, forbid_execution=True)
        other = {**env, "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT": "low"}
        stopped = world.run("resume", kit.job_selector("live-drift"), env=other)
        assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "live_config_changed" and stopped["calls"] == [] and len(hits) == before + 1
        assert world.run("submit", drifted, env=other, expected=2)["error"]["code"] == "job_input_conflict"
        checks.append("model-send rights (operation, purpose, recipient) and the frozen configuration are enforced before any send; a drifted environment cannot resume or re-freeze a job")

        no_secret_anywhere(root, env)
    return {"status": "passed", "schemaVersion": SCHEMA, "checks": checks, "s2": report, "s3": relation_report, "providerRequests": len(hits), "paidModelCalls": 0,
            "network": "loopback simulator only (no external host, fake keys)"}


def real_smoke(root: Path) -> dict:
    """ONE real-provider run of the main scenario (a handful of paid calls under the operator's budget). Needs the live environment exported by the caller."""
    env = process_live_env()
    for name in ("ZOOP_AI_PIPELINE_LIVE_ENABLED", "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR", "ZOOP_AI_API_KEY"):
        assert env.get(name), f"{name} must be exported for the real live smoke"
    assert not Path(env["ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"]).resolve().is_relative_to(root), "the budget directory must outlive the smoke state"
    report = live_scenario(LiveWorld(root, env))
    return {"status": "completed" if report["state"] == "ready" else report["state"], "schemaVersion": SCHEMA, "report": report}


def main() -> None:
    flags = set(sys.argv[1:]) - {"--keep"}
    assert flags <= {"--live", "--live-loopback"} and len(flags) <= 1, "usage: extraction_smoke.py [--live | --live-loopback] [--keep]"
    run = real_smoke if "--live" in flags else loopback_smoke if "--live-loopback" in flags else smoke
    with tempfile.TemporaryDirectory(prefix="zoop-s2-2-smoke-") as temporary:
        root = Path(temporary).resolve()
        result = run(root)
        if "--keep" in sys.argv:
            kept = Path(tempfile.mkdtemp(prefix="zoop-s2-2-kept-")) / "state"
            shutil.copytree(root, kept)
            result["keptState"] = str(kept)
    assert not root.exists()
    result["temporaryStateCleanup"] = {"removed": True, "root": str(root)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] not in {"passed", "completed"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
