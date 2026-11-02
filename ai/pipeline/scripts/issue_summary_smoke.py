#!/usr/bin/env python3
"""Actual `zoop-ai-issue-summary` processes over the authored handoff world (real ingestion + S2 + S3 ledgers, authored replay) and a loopback provider simulator.

    ai/pipeline/.venv/bin/python ai/pipeline/scripts/issue_summary_smoke.py [--keep]

REPLAY (no model, no provider, no network: every child runs under a socket audit hook that aborts on any connection). The world is `graph_handoff_smoke.build_world`
(two public issues: supply over documents a/a2 and factory over b; a third authored issue is not public); expectations (basis digests, evidence ids, claim evidence, pin fields) are written by hand
from the authored documents, never derived from the code under test. Covered through the installed command's own `-c` entry (`runpy`):
submit freezes a queued job with no call; an authored replay run is `available` with every field pinned and re-runs change nothing; verifier hold and reject are READY
withheld results pinned to the job; a HOLD/REJECT time verdict is refused at submit with no row and no call while another issue of the same bundle still summarises;
the same job id with another request conflicts, the same input under another job id is a duplicate; a tampered pin (review/upstream/relation/operator file) is refused
with its own code and writes nothing; a changed basis (another app article version in the bindings) is a different pinned basis; a queued job stops when an operator file
it is pinned to moves; a revoked grant stops a job before it records anything and restoring it resumes; the source ledgers stay byte/mode/mtime identical.

LIVE (loopback only: http://127.0.0.1 on an ephemeral port, FAKE keys, a scripted simulator that is NOT an AI and a stand-in for nothing): the real CLI, ledger, runtime,
budget and HTTP transport against the simulator. The ONE stubbed seam is the handoff planner (`plan_summary_input`, replaced inside the child by a hand-written live
issue): the repository has no live S2/S3 world to plan from, and the planner is covered by the replay half above. Covered: offline binding, submit with no call, a run with
two calls, no key in any state file, env-free inspect/export, no resend; a provider that never answers is `provider_outcome_unknown` and is never retried; a process killed
after the reservation is unknown and nothing is sent; a process killed after the receipt is recovered from the stored receipt with one more call only; missing rights mean
no send; rights revoked while the provider answers keep the receipt and the job resumes without resending; an exhausted budget never opens a socket.

Exit 0 = every check passed. Nothing is paid, nothing leaves the machine. State is removed unless `--keep`. The helpers below (`make_replay_world`, `author`, `Summarizer`)
are reusable by other smokes.
"""
from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts import graph_handoff_smoke as hs  # noqa: E402
from scripts.ingestion_smoke import json_bytes, ownership_env  # noqa: E402
from scripts.relation_smoke import tree  # noqa: E402
from zoop_ai_pipeline import issue_summary as isum  # noqa: E402
from zoop_ai_pipeline import issue_summary_contracts as c  # noqa: E402
from zoop_ai_pipeline import issue_summary_jev as jev  # noqa: E402
from zoop_ai_pipeline import issue_summary_prompts as prompts  # noqa: E402
from zoop_ai_pipeline.extraction_contracts import ExtractionFailure  # noqa: E402
from zoop_ai_pipeline.handoff import HandoffPaths, plan_summary_input  # noqa: E402
from zoop_ai_pipeline.handoff_contracts import Manifest, app_evidence_id  # noqa: E402
from zoop_ai_pipeline.ingestion_contracts import digest  # noqa: E402

SCHEMA = "zoop-issue-summary-1"
REPLAY = ("replay", "authored-test")
CUSTOM = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
SUPPLY, FACTORY = "issue:supply-2026q3", "issue:factory-2026q4"          # the PUBLIC issues of the authored world (`issue:overseas` is excluded: its mention states no country)
FAKE_KEYS = {"ZOOP_AI_API_KEY": "sk-offline-simulator-openai-key", "TYPESAFE_API_KEY": "tsk-offline-simulator-jev-key"}

# The authored claims of each issue: (claim text, the quotes of the world it cites). Hand-written, Korean, one fact each.
CLAIMS = {SUPPLY: [("합성기업은 2026년 3분기 공급 계약을 발표했다.", [hs.EVT_A]), ("합성기업이 3분기 공급 계약 체결을 공개했다.", [hs.EVT_A2])],
          FACTORY: [("합성기업은 4분기 신규 공장 착공을 알렸다.", [hs.QB])],
          }
# issue -> (public headline title, [(document name, quote)]) exactly as the authored mentions say them
SOURCES = {SUPPLY: ("합성 공급 계약", [("a", hs.EVT_A), ("a2", hs.EVT_A2)]), FACTORY: ("합성 공장 착공", [("b", hs.QB)])}

# One network audit hook per child: a connection is refused unless it is the loopback simulator (live half only).
GUARD = ("import os, sys, runpy\n"
         "ALLOW = {'127.0.0.1'} if os.environ.get('ZOOP_SMOKE_LOOPBACK') == '1' else set()\n"
         "def _guard(event, args):\n"
         " if event == 'socket.connect' and args[1][0] in ALLOW:\n"
         "  return\n"
         " if event == 'socket.getaddrinfo' and args[0] in ALLOW:\n"
         "  return\n"
         " if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.bind'}:\n"
         "  raise RuntimeError('network attempted')\n"
         "sys.addaudithook(_guard)\n"
         "from zoop_ai_pipeline.issue_summary import Engine\n")
HOOKS = {"kill-after-reserve": "Engine._after_reserve = lambda self, stage: os._exit(9)\n",
         "kill-after-receipt": "Engine._after_receipt = lambda self, stage: os._exit(9)\n"}
REAL_MAIN = "runpy.run_module('zoop_ai_pipeline.issue_summary_cli', run_name='__main__')\n"
STUB_MAIN = ("import zoop_ai_pipeline.issue_summary_cli as cli\n"
             "from scripts import issue_summary_smoke as smoke\n"
             "cli.plan_summary_input = smoke.stub_planner(os.environ['ZOOP_SMOKE_STUB'])\n"
             "raise SystemExit(cli.main())\n")


def selector(job: str) -> dict:
    return {"schemaVersion": SCHEMA, "jobId": job}


def request(job: str, issue: str, manifest: dict, mode: str = "replay") -> dict:
    return {"schemaVersion": SCHEMA, "jobId": job, "issueId": issue, "mode": mode, "manifest": manifest}


class Summarizer:
    """Runs the installed command's module as a child process over one operator root. `state` names the summary ledger directory under the root; `stub` (a control
    file) swaps the handoff planner for the hand-written live issue (live half only)."""

    def __init__(self, root: Path, registry: Path, *, state: str = "issue-summary", stub: Path | None = None):
        self.root, self.registry, self.state, self.stub = root, registry, root / state, stub

    def cli(self, command: str, request: dict | None = None, *, expected: int = 0, fixture: Path | None = None, hook: str | None = None, env: dict | None = None,
            state: str | None = None, sourced: bool | None = None):
        loopback = bool(env and env.get("ZOOP_AI_BASE_URL"))
        child_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **CUSTOM, **(env or {})}
        if loopback:
            child_env["ZOOP_SMOKE_LOOPBACK"] = "1"
        if self.stub is not None:
            child_env["ZOOP_SMOKE_STUB"] = str(self.stub)
        program = GUARD + (HOOKS[hook] if hook else "") + (STUB_MAIN if self.stub is not None else REAL_MAIN)
        argv = [sys.executable, "-c", program, command]
        if command != "live-binding":
            argv += ["--state-dir", str(self.root / state if state else self.state)]
        if command in {"submit", "run", "resume", "inspect", "export"} if sourced is None else sourced:
            argv += ["--relation-state-dir", str(self.root / "relation"), "--extraction-state-dir", str(self.root / "extraction"),
                     "--ingestion-state-dir", str(self.root / "ingestion"), "--sources", str(self.registry), "--canonical", str(self.root / "canonical.json"),
                     "--decisions", str(self.root / "decisions.json"), "--bindings", str(self.root / "bindings.json")]
        if fixture is not None:
            argv += ["--fixture", str(fixture)]
        child = subprocess.run(argv, input=json_bytes(request) if request is not None else b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env,
                               cwd=PIPELINE, timeout=300)
        text = child.stdout.decode()
        assert child.returncode == expected, (command, child.returncode, text[:2000], child.stderr.decode()[-2000:])
        assert expected == 9 or not child.stderr, child.stderr.decode()[-2000:]
        return json.loads(text) if text else None


# ================================================================================================== authored replay world ==========

def paths_of(world) -> HandoffPaths:
    root = world.root
    return HandoffPaths(root / "relation", root / "extraction", root / "ingestion", world.kit.registry_path, root / "canonical.json", root / "decisions.json",
                        root / "bindings.json")


def plan(world, manifest: dict, issue_id: str):
    """The planner's read-only value object of one public issue (the same function the command calls)."""
    return plan_summary_input(paths_of(world), Manifest.model_validate(manifest), issue_id)


def expected_basis(world, issue_id: str, *, article_versions: dict | None = None) -> dict:
    """Written out by hand from the authored mentions: the issue's headline title and the union of its mentions' quotes (never the geography sentence), pinned to the
    article version the operator's bindings give (default: the document version itself) and to the hash of the exact quote, all `report` (no authored mention is background)."""
    title, spans = SOURCES[issue_id]
    quotes, articles = [], {}
    for name, quote in spans:
        ref, cite = world.refs[name], hs.span(world, name, quote)
        version = (article_versions or {}).get(name, ref["documentVersion"])
        quotes.append({"evidenceId": app_evidence_id(ref["documentId"], version, cite["start"], cite["end"]), "articleId": ref["documentId"], "articleVersion": version,
                       "start": cite["start"], "end": cite["end"], "quoteSha256": hs.digest_text(quote), "context": "report"})
        articles[(ref["documentId"], version)] = {"articleId": ref["documentId"], "articleVersion": version, "documentId": ref["documentId"],
                                                  "documentVersion": ref["documentVersion"], "textSha256": hs.digest_text(world.art[name].body)}
    return {"policy": "zoop-issue-summary-policy-1", "issueId": issue_id, "title": title, "quotes": sorted(quotes, key=lambda q: q["evidenceId"]),
            "articles": [articles[key] for key in sorted(articles)]}


def answer(decisions=("supported",), advice="absent", causality="absent", framing="absent") -> dict:
    return {"claims": [{"claimId": f"c{n + 1}", "decision": d, "reason": "authored"} for n, d in enumerate(decisions)],
            "prohibitedAdvice": advice, "unsupportedCausality": causality, "backgroundAsCurrent": framing}


def author(world, manifest: dict, issue_id: str, name: str, verdict: dict | None = None, *, synthetic: bool = True) -> tuple[Path, dict]:
    """An authored `zoop-issue-summary-fixture-1` file for one issue (each record keyed by the digest of the exact native payload it answers, computed from the planner's
    read of the world) and the pieces a check needs: the model reply and the produced claims. `verdict` is the interpreted verifier answer (default: all supported)."""
    planned = plan(world, manifest, issue_id)
    basis = c.summary_basis(planned.issue, planned.evidence, planned.articles)
    texts = {}
    for q in basis["quotes"]:
        article = next(a for a in basis["articles"] if (a["articleId"], a["articleVersion"]) == (q["articleId"], q["articleVersion"]))
        text = planned.documents[(article["documentId"], article["documentVersion"])][0][1]["document"]["text"]
        texts[q["evidenceId"]] = text[q["start"]:q["end"]]
    payload = isum.producer_payload(basis, texts)
    label = {q["text"]: f"q{n + 1}" for n, q in enumerate(payload["quotes"])}
    reply = {"claims": [{"text": text, "quoteIds": [label[quote] for quote in quotes]} for text, quotes in CLAIMS[issue_id]]}
    claims = prompts.claims_from(reply, payload)
    verify = isum.verifier_payload(payload, claims)
    records = [{"stage": "issue-summary", "requestDigest": digest(payload), "response": reply},
               {"stage": "verify-issue-summary", "requestDigest": digest(verify), "response": verdict or answer(("supported",) * len(claims))}]
    path = world.root / "fixtures" / f"{name}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(json_bytes({"format": "zoop-issue-summary-fixture-1", "synthetic": synthetic, "recordingKind": "authored-test", "records": records}))
    return path, {"reply": reply, "claims": claims, "verifyDigest": digest(verify)}


def make_replay_world(root: Path) -> SimpleNamespace:
    """The authored world with its operator files, one handoff manifest and a summarizer over it (reusable by other smokes and service tests)."""
    world = hs.build_world(root)
    hs.write_operator(world)
    manifest = hs.manifest_doc(world, "handoff-isum-1", hs.file_hashes(root))
    return SimpleNamespace(world=world, manifest=manifest, root=root, summarizer=Summarizer(root, world.kit.registry_path))


def ledger_counts(state: Path) -> dict:
    """Row counts of a summary ledger, read-only (nothing may be created, so an absent ledger counts as empty)."""
    database = state / "issue-summary.sqlite3"
    if not database.exists():
        return {"jobs": 0, "calls": 0, "results": 0}
    db = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("jobs", "calls", "results")}
    finally:
        db.close()


def check_ready(world, manifest: dict, out: dict, issue_id: str, outcome: str, sentinel: dict) -> dict:
    """A ready job over the authored world equals the hand-written expectation; returns its exact bundle `summary`."""
    basis = expected_basis(world, issue_id)
    assert out["state"] == "ready" and out["phase"] == "complete" and out["failure"] is None and out["result"]["outcome"] == outcome, out
    assert out["basis"] == {"digest": digest(basis), "quotes": len(basis["quotes"]), "articles": len(basis["articles"])}, out["basis"]
    assert out["usage"] == {"executionMode": "replay", "replayCalls": sentinel["calls"], "startedWithoutReceipt": 0, "providerCalls": 0, "modelCalls": 0,
                            "creatorJobId": out["jobId"]}, out["usage"]
    summary = out["result"]["summary"]
    planned = plan(world, manifest, issue_id)
    c.check_summary(planned.issue, summary, c.summary_basis(planned.issue, planned.evidence, planned.articles), REPLAY)     # the bundle validator accepts exactly this value
    assert summary["source"]["basisDigest"] == digest(basis) and summary["source"]["inputDigest"] == out["inputDigest"]
    return summary


def replay_half(root: Path) -> list[str]:
    checks: list[str] = []
    built = make_replay_world(root)
    world, manifest, s = built.world, built.manifest, built.summarizer
    sources_before = {name: tree(root / name) for name in ("ingestion", "extraction", "relation")}

    # 1. submit: a queued job with the exact pinned basis and no call; idempotent; inspect is a read-only command (it takes the source flags like every command that proves sources).
    request1 = request("isum-supply", SUPPLY, manifest)
    queued = s.cli("submit", request1)
    assert queued["state"] == "queued" and queued["calls"] == [] and queued["result"] is None and queued["usage"]["replayCalls"] == 0 and queued["failure"] is None, queued
    assert queued["basis"] == {"digest": digest(expected_basis(world, SUPPLY)), "quotes": 2, "articles": 2} and queued["issueId"] == SUPPLY, queued
    assert s.cli("submit", request1) == queued == s.cli("inspect", selector("isum-supply")) and ledger_counts(s.state) == {"jobs": 1, "calls": 0, "results": 0}
    checks.append("submit: queued job pinned to the hand-written basis digest (title + the two mention quotes, no geography sentence), zero calls, idempotent, inspect is read-only")

    # 2. an authored replay run (resume of the queued job): available, every field hand-written; a second resume needs no fixture and changes nothing.
    fixture, pieces = author(world, manifest, SUPPLY, "supply")
    done = s.cli("resume", selector("isum-supply"), fixture=fixture)
    summary = check_ready(world, manifest, done, SUPPLY, "available", {"calls": 2})
    ev_a, ev_a2 = hs.evidence_id(world, "a", hs.EVT_A), hs.evidence_id(world, "a2", hs.EVT_A2)
    texts = [text for text, _ in CLAIMS[SUPPLY]]
    assert summary["text"] == "\n".join(texts) and summary["language"] == "ko" and summary["evidenceIds"] == sorted([ev_a, ev_a2])
    assert summary["claims"] == [{"claimId": "c1", "text": texts[0], "evidenceIds": [ev_a]}, {"claimId": "c2", "text": texts[1], "evidenceIds": [ev_a2]}], summary["claims"]
    spec = prompts.SPECS["issue-summary"]
    assert summary["producer"] == {"kind": "authored-replay", "model": None, "reasoningEffort": None, "promptVersion": spec.prompt_version, "schemaDigest": spec.schema_digest,
                                   "runtimeIdentity": hashlib.sha256(fixture.read_bytes()).hexdigest()}, summary["producer"]
    assert summary["verifier"] == {"kind": "authored-replay", "model": None, "adapterIdentity": jev.identity(), "requestDigest": pieces["verifyDigest"]}, summary["verifier"]
    assert s.cli("resume", selector("isum-supply")) == done
    exported = s.cli("export", selector("isum-supply"))
    assert exported == {"schemaVersion": SCHEMA, "jobId": "isum-supply", "inputDigest": done["inputDigest"], "resultDigest": done["result"]["resultDigest"], "issueId": SUPPLY,
                        "outcome": "available", "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}, "summary": summary}
    assert [c_["state"] for c_ in done["calls"]] == ["received", "received"] and ledger_counts(s.state) == {"jobs": 1, "calls": 2, "results": 1}
    checks.append("authored replay run: available, claims/evidence ids/producer/verifier/identity hand-checked, accepted by the bundle validator, a rerun needs no fixture and adds no call, export = the pin fields + the exact summary")

    # 3. verifier hold and reject are READY withheld results pinned to the job (never an empty summary).
    rejects = Summarizer(root, world.kit.registry_path, state="issue-summary-reject")       # the supply input already has a job in the main ledger: another ledger, another run
    for runner, job, issue, verdict, outcome in ((s, "isum-factory", FACTORY, answer(("insufficient",)), "verifier-hold"),
                                                 (rejects, "isum-supply-reject", SUPPLY, answer(("contradicted", "supported")), "verifier-reject")):
        withheld, _ = author(world, manifest, issue, job, verdict)
        out = runner.cli("run", request(job, issue, manifest), fixture=withheld)
        got = check_ready(world, manifest, out, issue, outcome, {"calls": 2})
        assert got == {"status": "unavailable", "code": outcome, "source": {"jobId": job, "inputDigest": out["inputDigest"], "basisDigest": digest(expected_basis(world, issue)),
                                                                          "resultDigest": c.result_digest(job, out["inputDigest"], digest(expected_basis(world, issue)),
                                                                                                          {"status": "unavailable", "code": outcome})}}, got
    checks.append("verifier hold and reject: ready withheld results (code + source pin, no text), accepted by the bundle validator")

    # 4. a HOLD/REJECT time verdict on the supply issue: refused at submit with no row and no call; the bundle's other public issue (factory, no verdict) still summarises.
    hs.write_operator(world, decisions=hs.reviewed(world, cases={"issue:supply": hs.verdict_cases(world)["issue:supply"]}, published_time=None))
    held_manifest = hs.manifest_doc(world, "handoff-isum-held", hs.file_hashes(root))
    held = Summarizer(root, world.kit.registry_path, state="issue-summary-held")
    valid, _ = author(world, held_manifest, SUPPLY, "held-supply")                    # a perfectly good fixture exists: it is never consulted
    for command in ("submit", "run"):
        out = held.cli(command, request("held-supply", SUPPLY, held_manifest), fixture=valid if command == "run" else None, expected=2)
        assert out["error"]["code"] == "issue_temporal_review_pending", out
    assert held.cli("inspect", selector("held-supply"), expected=2)["error"]["code"] == "job_not_found"
    assert ledger_counts(held.state) == {"jobs": 0, "calls": 0, "results": 0}
    other_fixture, _ = author(world, held_manifest, FACTORY, "held-factory")
    other = held.cli("run", request("held-factory", FACTORY, held_manifest), fixture=other_fixture)
    assert other["state"] == "ready" and other["result"]["outcome"] == "available" and ledger_counts(held.state) == {"jobs": 1, "calls": 2, "results": 1}
    hs.write_operator(world)
    assert hs.file_hashes(root) == manifest["files"]
    checks.append("HOLD/REJECT field verdict: submit and run refused (issue_temporal_review_pending), no job row, no call, a valid fixture never consulted; the unaffected issue of the same bundle is summarised")

    # 5. duplicate identity.
    other_manifest = hs.manifest_doc(world, "handoff-isum-1b", hs.file_hashes(root))
    conflict = s.cli("submit", request("isum-supply", SUPPLY, other_manifest), expected=2)
    assert conflict["error"]["code"] == "job_input_conflict"
    duplicate = s.cli("submit", request("isum-supply-twin", SUPPLY, manifest), expected=2)
    assert duplicate["error"] == {"code": "issue_summary_input_duplicate", "detail": {"jobId": "isum-supply"}} and ledger_counts(s.state) == {"jobs": 2, "calls": 4, "results": 2}
    checks.append("duplicate identity: same job id + another request = job_input_conflict, same input under another job id = issue_summary_input_duplicate, nothing written")

    # 6. tampered pins and a changed basis.
    pins = Summarizer(root, world.kit.registry_path, state="issue-summary-pins")
    for name, tamper, code in (("review", lambda m: m["sources"][0].update(reviewDigest="0" * 64), "review_revision_changed"),
                               ("upstream", lambda m: m["sources"][0]["upstream"].update(digest="1" * 64), "upstream_changed"),
                               ("relation", lambda m: m["sources"][0]["relation"].update(inputDigest="2" * 64), "relation_input_mismatch"),
                               ("file", lambda m: m["files"].update(decisions="3" * 64), "operator_file_pin_mismatch")):
        forged = json.loads(json.dumps(manifest))
        tamper(forged)
        assert pins.cli("submit", request(f"isum-forged-{name}", SUPPLY, forged), expected=2)["error"]["code"] == code, name
    assert ledger_counts(pins.state) == {"jobs": 0, "calls": 0, "results": 0}
    changed = Summarizer(root, world.kit.registry_path, state="issue-summary-basis")
    pinned_bindings = (root / "bindings.json").read_bytes()
    version = hs.digest_text("another app article version of document a")
    edited = hs.bindings_doc(world)
    next(b for b in edited["bindings"] if b["documentId"] == world.refs["a"]["documentId"])["articleVersion"] = version
    (root / "bindings.json").write_bytes(json_bytes(edited))
    manifest_changed = hs.manifest_doc(world, "handoff-isum-2", hs.file_hashes(root))
    moved = changed.cli("submit", request("isum-supply-bindings", SUPPLY, manifest_changed))
    basis_changed = expected_basis(world, SUPPLY, article_versions={"a": version})
    assert moved["basis"]["digest"] == digest(basis_changed) != digest(expected_basis(world, SUPPLY)), moved["basis"]
    (root / "bindings.json").write_bytes(pinned_bindings)                          # the operator file the job is pinned to moves back: the job is bound to the manifest it was submitted with
    stopped = changed.cli("resume", selector("isum-supply-bindings"), fixture=author(world, manifest, SUPPLY, "supply-again")[0])
    assert stopped["state"] == "stopped" and stopped["failure"]["code"] == "operator_file_pin_mismatch" and stopped["calls"] == [] and stopped["result"] is None, stopped
    cancelled = changed.cli("cancel", selector("isum-supply-bindings"))
    assert cancelled["state"] == "failed" and cancelled["failure"] == {"code": "job_cancelled"} and cancelled["result"] is None, cancelled
    assert changed.cli("export", selector("isum-supply-bindings"), expected=2)["error"]["code"] == "issue_summary_not_ready"
    assert changed.cli("cancel", selector("isum-supply-bindings"), expected=2)["error"]["code"] == "job_already_terminal"
    checks.append("tampered pins (review digest, upstream digest, relation input, operator file) each refused with its own code and no row; a changed app article version is a different pinned basis; "
                  "a queued job stops with operator_file_pin_mismatch when the file it is pinned to moves, with no call; cancel releases it (failed job_cancelled, cannot be exported or cancelled twice)")

    # 7. a revoked grant stops a job before it records anything; restoring it resumes.
    rights = Summarizer(root, world.kit.registry_path, state="issue-summary-rights")
    assert rights.cli("submit", request("isum-rights", SUPPLY, manifest))["state"] == "queued"
    valid, _ = author(world, manifest, SUPPLY, "supply-rights")
    grant = world.kit.registry["sources"][0]["grant"]
    grant["enabled"] = False
    world.kit.save_registry()
    revoked = rights.cli("resume", selector("isum-rights"), fixture=valid)
    assert revoked["state"] == "stopped" and revoked["failure"]["code"] and revoked["calls"] == [] and revoked["result"] is None, revoked
    grant["enabled"] = True
    world.kit.save_registry()
    ready = rights.cli("resume", selector("isum-rights"), fixture=valid)
    assert ready["state"] == "ready" and ready["delivery"]["status"] == "current" and ready["result"]["outcome"] == "available", ready
    # A READY result is shown only while the current source rights and the frozen basis prove: revoked = identity/state/usage only, delivery withheld (exit 2), no text.
    grant["enabled"] = False
    world.kit.save_registry()
    hidden = rights.cli("inspect", selector("isum-rights"), expected=2)
    assert hidden["state"] == "ready" and hidden["result"] is None and hidden["delivery"]["status"] == "withheld" and hidden["delivery"]["code"], hidden
    assert (hidden["jobId"], hidden["inputDigest"], hidden["usage"]) == (ready["jobId"], ready["inputDigest"], ready["usage"])
    gone = rights.cli("export", selector("isum-rights"), expected=2)
    assert set(gone) == {"schemaVersion", "jobId", "inputDigest", "issueId", "state", "delivery", "usage"} and gone["delivery"] == hidden["delivery"], gone
    shown = json.dumps([hidden, gone], ensure_ascii=False)
    assert not any(text in shown for text, _ in CLAIMS[SUPPLY]) and ready["result"]["resultDigest"] not in shown
    assert ledger_counts(rights.state) == {"jobs": 1, "calls": 2, "results": 1}
    grant["enabled"] = True
    world.kit.save_registry()
    assert rights.cli("inspect", selector("isum-rights")) == ready and rights.cli("export", selector("isum-rights"))["summary"] == ready["result"]["summary"]
    checks.append("revoked source grant: the job stops before recording any call (no result), restoring it resumes to ready; a READY result whose grant is revoked is delivery-withheld "
                  "(identity/state/usage only, exit 2, no text or digest, no call) and the same immutable result again once restored")

    assert {name: tree(root / name) for name in ("ingestion", "extraction", "relation")} == sources_before
    checks.append("source ledgers byte/mode/mtime identical after every command; no provider, model or network (socket audit hook)")
    return checks


# ================================================================================================== loopback live half =============

LIVE_ISSUE = "issue:live-1"
LIVE_SENTENCES = ("합성기업은 2026년 3분기 공급 계약을 발표했다.", "계약 상대는 합성부품이다.", "합성부품은 이전에 시험 생산을 마쳤다.")
LIVE_TITLE = "고유제목표지 합성 계약"
LIVE_CLAIMS = (("합성기업은 2026년 3분기 공급 계약을 발표했으며 계약 상대는 합성부품이다.", (0, 1)), ("합성부품은 이전에 시험 생산을 마쳤다.", (2,)))


def stub_manifest() -> dict:
    def h(label: str) -> str:
        return hashlib.sha256(label.encode()).hexdigest()
    return {"schemaVersion": "zoop-ai-handoff-1", "handoffId": "handoff-live-1", "sourceKind": "synthetic", "policyVersion": "zoop-public-projection-policy-2",
            "sources": [{"relation": {"jobId": "rel-live", "inputDigest": h("rel")}, "upstream": {"jobId": "s2-live", "inputDigest": h("s2"), "digest": h("up")},
                         "reviewDigest": h("review")}], "files": {"canonical": h("canonical"), "decisions": h("decisions"), "bindings": h("bindings")}}


class StubSources:
    """The live issue's model-send authority: refuses with the code the control file names (read at every check, so a test can revoke mid-run)."""

    def __init__(self, control: str):
        self.control = control

    def authorize_model_send(self, ref, purpose, recipient):
        denied = json.loads(Path(self.control).read_text()).get("denied")
        if denied:
            raise ExtractionFailure(denied)


def stub_planner(control: str):
    """The hand-written stand-in for `plan_summary_input` inside a live child: one public issue over one article, mode live/provider, synthetic. Nothing else of the
    handoff is touched; the real planner is exercised by the replay half."""
    text = " ".join(LIVE_SENTENCES)
    article, version, document_version = "doc-" + hashlib.sha256(b"live-article").hexdigest(), hashlib.sha256(b"live-article-version").hexdigest(), hashlib.sha256(b"live-doc").hexdigest()
    evidence = {}
    for sentence in LIVE_SENTENCES:
        start = text.index(sentence)
        ident = app_evidence_id(article, version, start, start + len(sentence))
        evidence[ident] = {"id": ident, "articleId": article, "articleVersion": version, "start": start, "end": start + len(sentence),
                           "quoteSha256": hashlib.sha256(sentence.encode()).hexdigest()}
    ids = list(evidence)
    articles = {(article, version): {"articleId": article, "articleVersion": version, "documentId": "doc-live", "documentVersion": document_version,
                                     "textSha256": hashlib.sha256(text.encode()).hexdigest()}}
    sources = StubSources(control)

    def plan(paths, manifest, issue_id):
        if issue_id != LIVE_ISSUE:
            raise ExtractionFailure("issue_not_public")
        issue = {"id": LIVE_ISSUE, "title": LIVE_TITLE, "fieldVerdicts": [],
                 "mentions": [{"mentionId": "m1", "background": False, "evidenceIds": ids[:-1]}, {"mentionId": "m2", "background": True, "evidenceIds": ids[-1:]}]}
        return SimpleNamespace(handoff_id=manifest.handoff_id, issue=issue, evidence=json.loads(json.dumps(evidence)), articles=articles, execution=("live", "provider"),
                               source_kind="synthetic", documents={("doc-live", document_version): (("ref-live", {"document": {"text": text}}),)}, sources=sources)

    return plan


def chat_reply(body: dict) -> dict:
    quotes = json.loads(body["messages"][1]["content"])["input"]["quotes"]
    label = {q["text"]: q["id"] for q in quotes}
    claims = [{"text": claim, "quoteIds": [label[LIVE_SENTENCES[i]] for i in cited]} for claim, cited in LIVE_CLAIMS]
    return {"id": "chatcmpl-simulated", "object": "chat.completion", "model": "gpt-6-luna-simulated",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps({"claims": claims}, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 120}}}


def jev_reply(body: dict) -> dict:
    answers = {}
    for key, question in body["questions"].items():
        options = list(question["criteria"])
        winner = "supported" if "supported" in options else "absent"
        answers[key] = {"type": "choice", "choice": winner, "probabilities": {o: 0.97 if o == winner else 0.03 / (len(options) - 1) for o in options}, "confidence": 0.95}
    return {"model": "jev-1.14.0", "answers": answers, "usage": {"input_tokens": 1000, "output_tokens": 0}}


class Simulator:
    """Loopback OpenAI-chat + Jev wires. `mode`: ok | silent (connection closed, no reply). `on_chat` runs while a generation request is being answered."""

    def __init__(self):
        self.mode, self.requests, self.on_chat = "ok", [], None
        simulator = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                simulator.requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), "body": body})
                chat = self.path.endswith("/chat/completions")
                if chat and simulator.on_chat:
                    simulator.on_chat()
                if chat and simulator.mode == "silent":
                    self.close_connection = True
                    return
                data = json.dumps(chat_reply(body) if chat else jev_reply(body), ensure_ascii=False).encode()
                self.send_response(200)
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

    def __enter__(self) -> "Simulator":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()


def live_env(base_url: str, budget: Path, **changes: str) -> dict[str, str]:
    return {"ZOOP_AI_PIPELINE_LIVE_ENABLED": "1", "ZOOP_AI_PIPELINE_LIVE_MODEL": "gpt-6-luna", "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT": "high",
            "TYPESAFE_VALIDATION_MODEL": "jev-1.14.0", "ZOOP_AI_BASE_URL": base_url, "TYPESAFE_BASE_URL": base_url, "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR": str(budget),
            "ZOOP_AI_PIPELINE_LIVE_MAX_USD": "5", "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS": "40", "ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS": "10", **FAKE_KEYS, **changes}


def live_half(root: Path) -> list[str]:
    checks: list[str] = []
    control = root / "stub-control.json"
    control.write_text(json.dumps({"denied": None}))
    manifest = stub_manifest()
    with Simulator() as provider:
        env = live_env(provider.base_url, root / "budget")
        live = Summarizer(root, root / "sources.json", stub=control)
        hits = provider.requests

        def where(ledger: str) -> Summarizer:
            return Summarizer(root, root / "sources.json", state=ledger, stub=control)

        binding = live.cli("live-binding", env=env)
        assert binding["binding"]["version"] == "zoop-issue-summary-runtime-1" and set(binding["binding"]["stages"]) == {"issue-summary", "verify-issue-summary"}
        assert live.cli("live-binding", env={}, expected=2)["error"]["code"] == "live_not_enabled" and not hits
        checks.append("live-binding: offline and keyless, exactly the two issue-summary stages; without the live gate it refuses")

        # 1. the main scenario.
        req = request("live-main", LIVE_ISSUE, manifest, "live")
        queued = live.cli("submit", req, env=env)
        assert queued["state"] == "queued" and queued["usage"]["executionMode"] == "live" and queued["calls"] == [] and not hits
        done = live.cli("resume", selector("live-main"), env=env)
        assert done["state"] == "ready" and done["result"]["outcome"] == "available" and len(hits) == 2, done
        assert [r["path"].rsplit("/", 1)[-1] for r in hits] == ["completions", "systemone"]
        assert hits[0]["authorization"] == "Bearer " + FAKE_KEYS["ZOOP_AI_API_KEY"] and hits[1]["authorization"] == "Bearer " + FAKE_KEYS["TYPESAFE_API_KEY"]
        assert done["usage"] == {"executionMode": "live", "replayCalls": 0, "startedWithoutReceipt": 0, "providerCalls": 2, "modelCalls": 2, "creatorJobId": "live-main"}, done["usage"]
        summary = done["result"]["summary"]
        assert summary["producer"]["kind"] == "provider" and summary["producer"]["model"] == "gpt-6-luna" and summary["producer"]["reasoningEffort"] == "high"
        assert summary["verifier"]["kind"] == "independent-verifier" and summary["verifier"]["model"] == "jev-1.14.0"
        assert summary["text"] == "\n".join(claim for claim, _ in LIVE_CLAIMS) and summary["source"]["inputDigest"] == done["inputDigest"]
        chat, verify = json.dumps(hits[0]["body"], ensure_ascii=False), json.dumps(hits[1]["body"], ensure_ascii=False)
        assert LIVE_TITLE in chat and LIVE_TITLE not in verify and all(s in chat for s in LIVE_SENTENCES)
        assert live.cli("inspect", selector("live-main")) == done == live.cli("resume", selector("live-main"), env=env) and len(hits) == 2
        assert live.cli("export", selector("live-main"))["summary"] == summary
        control.write_text(json.dumps({"denied": "source_purpose_or_recipient_denied"}))
        assert live.cli("inspect", selector("live-main")) == done and len(hits) == 2        # model-send rights gate the send, never a later read of the stored result
        control.write_text(json.dumps({"denied": None}))
        for path in sorted((live.state).iterdir()):
            assert not any(key.encode() in path.read_bytes() for key in FAKE_KEYS.values()), path.name
        checks.append("live main: submit freezes with no call, the run makes exactly a generation and a verification call with the right keys, only the title and quotes are sent, "
                      "no key in any state file, inspect/export need no environment, a rerun sends nothing")

        # 2. unknown outcome: never retried.
        before, provider.mode = len(hits), "silent"
        silent = where("live-silent").cli("run", req, env=env)
        provider.mode = "ok"
        assert silent["state"] == "failed" and silent["failure"] == {"code": "provider_outcome_unknown"} and len(hits) == before + 1, silent
        assert silent["usage"]["startedWithoutReceipt"] == 1 and silent["usage"]["providerCalls"] == 1 and silent["result"] is None
        assert where("live-silent").cli("resume", selector("live-main"), env=env) == silent and len(hits) == before + 1
        assert where("live-silent").cli("export", selector("live-main"), expected=2)["error"]["code"] == "issue_summary_not_ready"
        checks.append("provider silence after the request left: failed provider_outcome_unknown, never resent, cannot be exported; a resume sends nothing")

        # 3. a process killed after the reservation: nothing was (provably) sent, still never sent later.
        before = len(hits)
        killed = where("live-killed")
        killed.cli("run", req, env=env, hook="kill-after-reserve", expected=9)
        again = killed.cli("resume", selector("live-main"), env=env)
        assert again["state"] == "failed" and again["failure"] == {"code": "provider_outcome_unknown"} and len(hits) == before and again["usage"]["startedWithoutReceipt"] == 1, again
        checks.append("process killed after the reservation: resume settles it provider_outcome_unknown and sends nothing")

        # 4. a process killed after the receipt: recovered from the stored receipt, exactly one more call.
        before = len(hits)
        recovered = where("live-recovered")
        recovered.cli("run", req, env=env, hook="kill-after-receipt", expected=9)
        assert len(hits) == before + 1
        healed = recovered.cli("resume", selector("live-main"), env=env)
        assert healed["state"] == "ready" and healed["result"]["outcome"] == "available" and len(hits) == before + 2, healed
        assert [r["path"].rsplit("/", 1)[-1] for r in hits[before:]] == ["completions", "systemone"]
        checks.append("process killed after the first receipt: resume decodes the stored receipt (no resend) and makes only the verification call")

        # 5. rights: missing before the send = no send; revoked while the provider answers = receipt kept, reply unused, no resend.
        before = len(hits)
        gated = where("live-rights")
        control.write_text(json.dumps({"denied": "source_purpose_or_recipient_denied"}))
        denied = gated.cli("run", req, env=env)
        assert denied["state"] == "stopped" and denied["failure"]["code"] == "source_purpose_or_recipient_denied" and denied["calls"] == [] and len(hits) == before, denied
        control.write_text(json.dumps({"denied": None}))
        assert gated.cli("resume", selector("live-main"), env=env)["state"] == "ready" and len(hits) == before + 2
        before = len(hits)
        provider.on_chat = lambda: control.write_text(json.dumps({"denied": "source_unauthorized"}))
        revoked = where("live-midreply").cli("run", req, env=env)
        provider.on_chat = None
        assert revoked["state"] == "stopped" and revoked["failure"]["code"] == "source_unauthorized" and revoked["result"] is None and len(hits) == before + 1, revoked
        assert [(c_["stage"], c_["state"]) for c_ in revoked["calls"]] == [("issue-summary", "received")]
        control.write_text(json.dumps({"denied": None}))
        resumed = where("live-midreply").cli("resume", selector("live-main"), env=env)
        assert resumed["state"] == "ready" and len(hits) == before + 2, resumed
        checks.append("rights: missing model-send rights send nothing and reserve nothing; rights revoked while the provider answers keep the receipt, the reply is not used, and the resumed job sends only the verification call")

        # 6. an exhausted budget never opens a socket.
        before = len(hits)
        limited = live_env(provider.base_url, root / "budget-limited", ZOOP_AI_PIPELINE_LIVE_MAX_CALLS="1")
        budget = where("live-budget").cli("run", req, env=limited)
        assert budget["state"] == "stopped" and budget["failure"]["code"] == "live_budget_exhausted_calls" and len(hits) == before + 1, budget
        assert [(c_["stage"], c_["state"]) for c_ in budget["calls"]] == [("issue-summary", "received"), ("verify-issue-summary", "refused")]
        checks.append("exhausted call budget: the verification is refused before any socket (recorded as a refusal), the stored generation receipt stays")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="keep the temporary state (printed)")
    args = parser.parse_args()
    os.environ.update(ownership_env())
    root = Path(tempfile.mkdtemp(prefix="zoop-issue-summary-smoke-")).resolve()      # a symlinked parent (macOS /tmp -> /private/tmp) is refused by every pipeline ledger
    try:
        checks = replay_half(root / "owned")
        (root / "live").mkdir()
        checks += live_half(root / "live")
        print(json.dumps({"status": "passed", "providerCalls": 0, "paidModelCalls": 0, "network": "none (replay); loopback simulator with fake keys (live)", "checks": checks},
                         ensure_ascii=False, indent=1))
    finally:
        if args.keep:
            print(f"kept: {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
