#!/usr/bin/env python3
"""Authored HTML -> actual ingestion + extraction JSON subprocesses. Fresh owned state is always removed.

Replay here is authored response replay, not independent AI inference: no network, no model, no original PoC state.
"""
from __future__ import annotations

import html as htmllib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import stat
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from investmate.domain import IssueSnapshot, Mention  # noqa: E402

from scripts.ingestion_smoke import OfflineFixture, exact_check, json_bytes, ownership_env  # noqa: E402
from zoop_ai_pipeline import extraction_poc as poc  # noqa: E402
from zoop_ai_pipeline.extraction_contracts import SCHEMA, Catalogue, digest  # noqa: E402

PROMPT = "zoop-extraction-authored-1"
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
    def ingest(self, name: str, documents: list[dict]) -> list[dict]:
        """documents: [{"supplier": str|None, "html": bytes, "published": iso|None, "url": str}] -> exact observation refs."""
        items, bodies = [], {}
        for index, document in enumerate(documents):
            ref = f"d{index}"
            bodies[ref] = document["html"]
            item = self.item(f"c{index}", document["supplier"], document.get("url", f"https://example.invalid/{name}/{index}"), ref=ref)
            item["publishedAt"] = document.get("published", "2026-10-08T00:00:00+00:00")
            items.append(item)
        manifest = self.manifest(name, [items], bodies=bodies)
        rid = f"round-{name}"
        result = self.cli("run", self.request(manifest, rid, self.rounds), state="ingestion", manifest=manifest)
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
        return poc.article(self.export(ref), True)

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

    def settings(self, prompt: str = PROMPT):
        return poc.settings(prompt, Catalogue.model_validate(CATALOGUE))

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

    @staticmethod
    def job_selector(job: str) -> dict:
        return {"schemaVersion": SCHEMA, "jobId": job}

    # ---- process runner -------------------------------------------------------------------------------------
    def run(self, command: str, request: dict, *, state: str = "extraction", replay: Path | None = None, topic: Path | None = None,
            crash: str | None = None, expected: int = 0, sources: bool = True, raw: bool = False, forbid_execution: bool = False):
        """`forbid_execution` ends the process with 76 if it reaches stage execution, a replay model or a call reservation (a submit must not)."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM}
        guard = ("import os, sys, runpy\n"
                 "def _guard(event, args):\n"
                 " if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.bind'}:\n"
                 "  raise RuntimeError('network attempted')\n"
                 "sys.addaudithook(_guard)\n"
                 "from zoop_ai_pipeline.extraction import Extractor\n")
        hook = ""
        if forbid_execution:
            hook = ("from zoop_ai_pipeline.extraction import Fixtures\n"
                    "def _forbidden(*a, **k):\n os._exit(76)\n"
                    "Extractor._execute = Extractor._reserve = Extractor._receipted = Fixtures.model = _forbidden\n")
        if crash:
            kind, _, argument = crash.partition(":")
            hook = {
                "unknown": "Extractor._receive = lambda *a: os._exit(75)",
                "receipt": "original = Extractor._receive\ncount = [0]\ndef stop(self, *a):\n original(self, *a)\n count[0] += 1\n if count[0] == " + (argument or "1") + ":\n  os._exit(75)\nExtractor._receive = stop",
                "stage": "Extractor._stage_saved = lambda self, stage: os._exit(75) if stage == " + repr(argument) + " else None",
            }[kind]
        argv = [sys.executable, "-c", guard + hook + "\nrunpy.run_module('zoop_ai_pipeline.extraction_cli', run_name='__main__')", command]
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
    """Authored investmate-replay-v2 builder using the installed pure request/key functions."""

    def __init__(self, kit: Kit, name: str, *, synthetic: bool = True, prompt: str = PROMPT):
        self.kit, self.name, self.settings = kit, name, kit.settings(prompt)
        self.doc = {"format": "investmate-replay-v2", "synthetic": synthetic, "prompt_version": prompt, "model_version": "authored-model-1",
                    "analysis_version": "authored-analysis-1", "embedding_version": "authored-embedding-1", "records": []}

    def extract(self, article, mentions: list[dict], *, response=None) -> "Replay":
        self.doc["records"].append({"stage": "extract", "input": poc.extract_input(article, self.settings),
                                    "response": response if response is not None else {"mentions": mentions}})
        return self

    def compare(self, mention: dict, event_id: str, members: list[tuple[dict, object, dict]], article, relation: str, reason: str, evidence: list[dict]) -> "Replay":
        """members: [(observationRef, Article, Mention dict)]; whole event and its articles by document key."""
        seen, articles = set(), []
        for ref, member_article, _ in members:
            if digest(ref) not in seen:
                seen.add(digest(ref))
                articles.append(member_article)
        issue = IssueSnapshot(issue_id=event_id, mentions=[Mention.model_validate(m) for _, _, m in members], articles=articles)
        self.doc["records"].append({"stage": "compare", "input": poc.compare_input(Mention.model_validate(mention), issue, article),
                                    "response": {"relation": relation, "reason": reason, "evidence": evidence}})
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
    assert kit.run("submit", live, replay=r12, expected=2)["error"]["code"] == "live_mode_unsupported"
    other12 = kit.replay("r-submit-other").extract(art["a1"], [m1])
    other12.doc["model_version"] = "authored-model-2"
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


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zoop-s2-2-smoke-") as temporary:
        root = Path(temporary).resolve()
        result = smoke(root)
    assert not root.exists()
    result["temporaryStateCleanup"] = {"removed": True, "root": str(root)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
