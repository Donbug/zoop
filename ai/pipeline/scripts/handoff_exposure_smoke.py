#!/usr/bin/env python3
"""Authored ingestion + S2 + S3 worlds -> REAL frozen handoffs -> the installed `zoop-ai-handoff-exposure` CLI in child processes (no model, no network, no write).

    ai/pipeline/.venv/bin/python ai/pipeline/scripts/handoff_exposure_smoke.py      # needs `make pipeline-install` (the console script must exist)

Every world is built from the existing authored builders of `graph_handoff_smoke` (unmodified): the default world with a second source/grant for the uncited article
(`uncited_source`), the `chain` world (structural paths) and the `rich` impact world. Handoffs are frozen through the installed `zoop-ai-handoff`. Every expected report
below is HAND-WRITTEN from the authored graph (documents, quotes, S3 relations, issues, edges); no core function computes an expectation. The exposure CLI runs as a child
process under an audit hook that aborts on a network attempt, a process spawn, a write/mutation anywhere under the owned state root, and any SQLite connection under it that is
not `file:...?mode=ro&immutable=1`; every run also compares the whole owned tree (every file's mode, mtime, size and hash, every directory's mode and mtime) before and after.
Fresh owned state is always removed.

A source change is closed over the frozen bindings (S4): the articles/quotes of the affected documents, the issues resting on them, the S2 disposition inputs, and -- because an S3
producer reads every document its S2 upstream bound -- EVERY bundle-used relation of an S3 job on an affected upstream (`upstream-input`), cited or not. A relation retraction is
precise (only the named pair; never an article or a quote). A report is a PROPOSAL for the selected handoffs only: nothing is excluded, revised, overlaid or activated, current rights
are never evaluated, and an empty or smaller report is no statement of global safety (the final JSON says so from the observed `effect`/`scope.notCovered` of real runs).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from functools import cached_property
from pathlib import Path
from types import SimpleNamespace

PIPELINE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PIPELINE)]

from scripts import graph_handoff_smoke as hs  # noqa: E402
from scripts.extraction_smoke import page  # noqa: E402
from scripts.ingestion_smoke import json_bytes, ownership_env  # noqa: E402
from scripts.relation_smoke import find  # noqa: E402
from zoop_ai_pipeline.extraction import Store as ExtractionStore  # noqa: E402

SCHEMA = "zoop-handoff-exposure-1"
BUNDLE = "zoop-graph-handoff-bundle-8"
CLI = "zoop-ai-handoff-exposure"
SUPPLY, FACTORY = hs.SUPPLY, hs.FACTORY
FULL, LEAN = "exposure-full-1", "exposure-lean-1"      # same S2/S3 sources; LEAN's operator decisions publish neither a structural nor a FOLLOWS edge
CITED, UNCITED = "synthetic-source", hs.UNCITED_SOURCE
EXTRA_TEXT = "무관한 합성 문장이다."                      # a document the ingestion ledger records that no S2 job binds
NOT_COVERED = ["unselected-handoffs", "history-only-handoffs", "app-versions-not-imported-from-selected-handoffs", "app-exclusion-state", "app-article-listing",
               "graph-versions", "s1-worker", "published-briefings", "chat", "pins", "caches", "issue-summary-ledger", "poc-repository"]
# What each cause's `basis` must say (substrings of the hand-written contract wording).
BASIS_SOURCE = "every relation of an S3 job whose S2 upstream binds an affected document under its frozen binding"
BASIS_RELATION = "only the named S3 relation (job and candidate) is retracted"
AUTO = object()
STATS = {"runs": 0, "snapshotsCompared": 0, "readOnlyOpens": 0, "sqliteOpens": 0, "auditViolations": 0}
IDS = re.compile(r"(?:doc|ev|edge|rc)-[a-f0-9]{64}|issue:")
HANGUL = re.compile(r"[가-힣]")


# ---------------------------------------------------------------- the child process: audit guard ------------------------------------------------------------

GUARD = r'''
import json, os, sys
_FD, _ROOT = int(os.environ.pop("ZOOP_EXPOSURE_AUDIT_FD")), os.environ.pop("ZOOP_EXPOSURE_AUDIT_ROOT")
_NETWORK = {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo", "socket.bind", "socket.sendto",
            "socket.sendmsg", "http.client.connect", "urllib.Request", "ssl.wrap_socket", "ssl.get_server_certificate"}
_SPAWN = {"subprocess.Popen", "os.system", "os.exec", "os.fork", "os.forkpty", "os.posix_spawn", "os.spawn"}
_MUTATE = {"os.chmod", "os.chown", "os.mkdir", "os.remove", "os.rename", "os.replace", "os.rmdir", "os.truncate", "os.utime", "os.symlink", "os.link", "os.mkfifo",
           "os.mknod", "os.setxattr", "os.removexattr", "shutil.copyfile", "shutil.copymode", "shutil.copystat", "shutil.copytree", "shutil.move", "shutil.rmtree",
           "shutil.chown"}
_WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_SEEN = {"violations": [], "opened": set(), "relative": set(), "sqlite": set()}


def _inside(value):
    try:
        text = os.fsdecode(value)
    except Exception:
        return None
    if text == _ROOT:
        return ""
    return text[len(_ROOT) + 1:] if text.startswith(_ROOT + os.sep) else None


def _fail(kind, event, detail=""):
    _SEEN["violations"].append(kind + ":" + event + (":" + detail if detail else ""))
    raise RuntimeError(kind + " attempted")


def _guard(event, args):
    if event in _NETWORK:
        _fail("network", event)
    if event in _SPAWN:
        _fail("spawn", event)
    if event in _MUTATE:
        for value in args[:2]:
            inner = _inside(value)
            if inner is not None:
                _fail("write", event, inner)
    elif event == "open":
        inner, mode, flags = _inside(args[0]), args[1], args[2]
        writing = (isinstance(flags, int) and flags & _WRITE) or (isinstance(mode, str) and any(c in mode for c in "wax+"))
        if inner is not None:
            if writing:
                _fail("write", "open", inner)
            _SEEN["opened"].add(inner)
        else:
            try:
                name = os.fsdecode(args[0])
            except Exception:
                name = ""
            if name and not name.startswith(os.sep):
                # opened relative to a directory descriptor (`read_file` walks a path that way): the leaf name is all the audit event carries
                if writing:
                    _fail("write", "open", "relative:" + name)
                _SEEN["relative"].add(name)
    elif event == "sqlite3.connect":
        database = str(args[0])
        if _ROOT in database:
            tail = database[database.index(_ROOT) + len(_ROOT) + 1:].split("?")[0]
            _SEEN["sqlite"].add(tail)
            if not (database.startswith("file:") and "mode=ro" in database and "immutable=1" in database):
                _fail("write", "sqlite3.connect", tail)


sys.addaudithook(_guard)


def _report():
    os.write(_FD, json.dumps({"violations": _SEEN["violations"], "opened": sorted(_SEEN["opened"]), "relative": sorted(_SEEN["relative"]), "sqlite": sorted(_SEEN["sqlite"])}).encode())
'''
# The installed console script's entry point (not the module file): the pyproject wiring is part of what runs.
ENTRY = f'''
from importlib.metadata import entry_points
_entries = [e for e in entry_points(group="console_scripts") if e.name == {CLI!r}]
assert len(_entries) == 1, {CLI + " is not an installed console script (run `make pipeline-install`)"!r}
_main = _entries[0].load()
try:
    _code = _main()
finally:
    _report()
raise SystemExit(_code)
'''
# A tiny output limit through the module globals the CLI reads (`MAX_OUTPUT`), set before `main()` runs.
LIMIT = ("import zoop_ai_pipeline.handoff_exposure as _e, zoop_ai_pipeline.handoff_exposure_cli as _c, zoop_ai_pipeline.handoff_exposure_contracts as _k\n"
         "assert hasattr(_c, 'MAX_OUTPUT'), 'the CLI no longer reads a module-level MAX_OUTPUT'\n"
         "for _m in (_e, _c, _k):\n"
         "    if hasattr(_m, 'MAX_OUTPUT'):\n"
         "        _m.MAX_OUTPUT = int(os.environ['ZOOP_EXPOSURE_LIMIT'])\n")


def expose(root: Path, query, *, state: Path, ledgers: dict | None, expected: int = 0, stdin: bytes | None = None, limit: int | None = None,
           usage_error: bool = False) -> SimpleNamespace:
    """ONE child process of the installed CLI. `root` is the owned tree the audit hook and the before/after comparison cover; `ledgers` maps `ingestion`/`extraction` (and, to prove
    the removed flag is refused, `relation`) to the directories handed over as flags (None: no flag at all); `stdin` replaces the JSON of `query`; `limit` patches `MAX_OUTPUT`;
    `usage_error`: the command line itself is refused by argparse (exit 2, usage on stderr, no stdout)."""
    root = Path(root)
    flags = [part for name in ("ingestion", "extraction", "relation") if name in (ledgers or {}) for part in (f"--{name}-state-dir", str(ledgers[name]))]
    data = stdin if stdin is not None else json_bytes(query)
    with tempfile.TemporaryFile() as log:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **hs.CUSTOM,
               "ZOOP_EXPOSURE_AUDIT_FD": str(log.fileno()), "ZOOP_EXPOSURE_AUDIT_ROOT": str(root)}
        if limit is not None:
            env["ZOOP_EXPOSURE_LIMIT"] = str(limit)
        argv = [sys.executable, "-c", GUARD + (LIMIT if limit is not None else "") + ENTRY, "--state-dir", str(state), *flags]
        before = hs.ledger_snapshot(root)
        child = subprocess.run(argv, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=300, pass_fds=(log.fileno(),))
        log.seek(0)
        raw = log.read()
    after = hs.ledger_snapshot(root)
    text, tail = child.stdout.decode(), child.stderr.decode()[-2000:]
    assert raw, ("the audit guard did not report (the child died before it)", child.returncode, text[:500], tail)
    audit = json.loads(raw)
    STATS["runs"] += 1
    STATS["auditViolations"] += len(audit["violations"])
    STATS["readOnlyOpens"] += len(audit["opened"])
    STATS["sqliteOpens"] += len(audit["sqlite"])
    assert not audit["violations"], ("the audit hook aborted the process", audit["violations"], text[:500], tail)
    changed = sorted({name for name in {*before, *after} if before.get(name) != after.get(name)})
    assert not changed, ("the owned tree changed across a read-only report", changed[:20])
    STATS["snapshotsCompared"] += 1
    if usage_error:
        assert child.returncode == 2 and not text and "unrecognized arguments" in tail, (child.returncode, text[:500], tail)
        return SimpleNamespace(code=2, text=text, out=None, audit=audit, stderr=tail)
    assert child.returncode == expected and not tail, (child.returncode, expected, text[:2000], tail)
    out = json.loads(text)
    validate(out, text, root, child.returncode)
    return SimpleNamespace(code=child.returncode, text=text, out=out, audit=audit, stderr=tail)


REPORT_KEYS = {"schemaVersion", "changed", "cause", "identity", "scope", "basis", "consistency", "effect", "handoffs", "usage"}
HANDOFF_KEYS = {"handoffId", "bundleSchema", "manifestDigest", "bundleDigest", "contentDigest", "bound", "exposed", "articles", "issues", "relations", "evidenceIds", "counts"}
WANT_KEYS = ("bound", "exposed", "articles", "issues", "relations", "evidenceIds", "counts")


def validate(out: dict, text: str, root: Path, code: int) -> None:
    """What holds for EVERY output, success or error."""
    assert text.endswith("\n") and "\n" not in text[:-1], "stdout is not exactly one line"
    assert text == hs.canonical(out) + "\n", "stdout is not the canonical one-line form"
    assert not HANGUL.search(text) and "example.invalid" not in text and str(root) not in text and not any(p in text for p in hs.PRIVATE), "source text, URL or path leaked"
    assert out["schemaVersion"] == SCHEMA
    if code == 2:
        assert set(out) == {"schemaVersion", "error"} and set(out["error"]) <= {"code", "detail"}, out
        assert not IDS.search(text), "an error carried an issue, relation, evidence or article identity"
        return
    assert code == 0 and set(out) == REPORT_KEYS, (code, sorted(out))
    assert out["usage"] == {"providerCalls": 0, "modelCalls": 0}
    # No false completeness, no application: the report says what it is and what it does not cover.
    assert out["scope"]["selection"] == "explicit" and out["scope"]["notCovered"] == NOT_COVERED and out["scope"]["handoffIds"] == sorted(out["scope"]["handoffIds"])
    assert out["effect"].startswith("none: identity-only proposal") and "nothing was excluded, revised, overlaid, activated or written" in out["effect"]
    assert "never clears or narrows any existing exclusion" in out["effect"]
    assert out["cause"] in {"source-change", "relation-retraction"} and set(out["identity"]) == {"boundInSelection", "recordedInIngestion"}
    assert "current registry, rights and delivery were not evaluated" in out["basis"] and out["consistency"].startswith("shared locks")
    assert (BASIS_SOURCE if out["cause"] == "source-change" else BASIS_RELATION) in out["basis"], out["basis"]
    assert [h["handoffId"] for h in out["handoffs"]] == out["scope"]["handoffIds"], "the selection was expanded, reordered or narrowed"
    for h in out["handoffs"]:
        assert set(h) == HANDOFF_KEYS and h["bundleSchema"] == BUNDLE, sorted(h)
        article_keys = [(a["articleId"], a["articleVersion"]) for a in h["articles"]]
        assert article_keys == sorted(set(article_keys)) and all(set(a) == {"articleId", "articleVersion", "documentId", "documentVersion"} for a in h["articles"])
        for name in ("issues", "relations"):
            assert [i["id"] for i in h[name]] == sorted({i["id"] for i in h[name]}), (name, "not sorted/unique")
            assert all(i["reasons"] == sorted(set(i["reasons"])) and i["reasons"] for i in h[name]), (name, "reasons not sorted/unique/non-empty")
        assert h["evidenceIds"] == sorted(set(h["evidenceIds"]))
        assert h["counts"] == {"articles": len(h["articles"]), "issues": len(h["issues"]), "relations": len(h["relations"]), "evidence": len(h["evidenceIds"])}
        assert h["exposed"] is any((h["articles"], h["issues"], h["relations"], h["evidenceIds"])) and isinstance(h["bound"], bool)
        if not h["bound"]:
            assert not h["exposed"], "an unbound handoff must expose nothing"


def refused(run: SimpleNamespace, code: str, detail=None) -> None:
    """A whole-command refusal: exit 2, exactly this error, no partial report."""
    assert run.code == 2 and run.out == {"schemaVersion": SCHEMA, "error": {"code": code, **({"detail": detail} if detail is not None else {})}}, run.out


ARTIFACT = re.compile(r"(?:^|/)([a-f0-9]{64})\.json$")


def artifacts_read(run: SimpleNamespace) -> list:
    """The bundle artifacts (`<bundleDigest>.json`) a child opened, from the audit: absolute opens and the leaf names of opens relative to a directory descriptor."""
    return sorted({m.group(1) for p in (*run.audit["opened"], *run.audit["relative"]) if (m := ARTIFACT.search(p))})


def same(got, want, label: str) -> None:
    assert got == want, f"{label}\n got: {json.dumps(got, indent=1, ensure_ascii=False)}\nwant: {json.dumps(want, indent=1, ensure_ascii=False)}"


# ---------------------------------------------------------------- hand-written expectations ------------------------------------------------------------------

def want(m: SimpleNamespace, *, bound: bool = True, articles=(), issues: dict | None = None, relations: dict | None = None, evidence=()) -> dict:
    """One handoff's expected entry: article NAMES, issue id -> reasons, edge id -> reasons, evidence ids (every list written sorted and unique)."""
    issues, relations = issues or {}, relations or {}
    found = sorted(m.article[name] for name in articles)
    return {"bound": bound, "exposed": bool(found or issues or relations or evidence),
            "articles": [dict(zip(("articleId", "articleVersion", "documentId", "documentVersion"), a)) for a in found],
            "issues": [{"id": i, "reasons": sorted(r)} for i, r in sorted(issues.items())],
            "relations": [{"id": e, "type": m.type[e], "reasons": sorted(r)} for e, r in sorted(relations.items())],
            "evidenceIds": sorted(set(evidence)),
            "counts": {"articles": len(found), "issues": len(issues), "relations": len(relations), "evidence": len(set(evidence))}}


def check_report(ctx: "Ctx", run: SimpleNamespace, query: dict, wants: dict, *, recorded) -> None:
    """A successful report equals the hand-written expectation for every selected handoff, with its receipt pins and the change echoed exactly."""
    out, ids = run.out, sorted(query["handoffIds"])
    assert run.code == 0, run.out
    same(out["changed"], query["changed"], "changed is not echoed exactly")
    assert out["cause"] == ("relation-retraction" if query["changed"]["kind"] == "s3-relation" else "source-change"), out["cause"]
    same(out["identity"], {"boundInSelection": any(wants[i]["bound"] for i in ids), "recordedInIngestion": recorded}, "identity")
    assert out["scope"]["handoffIds"] == ids
    for entry in out["handoffs"]:
        hid = entry["handoffId"]
        same({k: entry[k] for k in ctx.pins[hid]}, ctx.pins[hid], f"{hid}: receipt pins")
        same({k: entry[k] for k in WANT_KEYS}, wants[hid], f"{hid}: report")


# ---------------------------------------------------------------- queries --------------------------------------------------------------------------------

def q(ids, changed: dict) -> dict:
    return {"schemaVersion": SCHEMA, "handoffIds": list(ids), "changed": changed}


def doc_change(ref: dict, *, version: bool = True, raw: bool = False) -> dict:
    return {"kind": "document", "documentId": ref["documentId"], "documentVersion": ref["documentVersion"] if version else None, "rawVersion": ref["rawVersion"] if raw else None}


def source_change(source_id: str) -> dict:
    return {"kind": "source", "sourceId": source_id}


def grant_change(grant_id: str, revision: str | None = None) -> dict:
    return {"kind": "grant", "grantId": grant_id, "revision": revision}


def relation_change(job: str, rc: str) -> dict:
    return {"kind": "s3-relation", "jobId": job, "relationCandidateId": rc}


# ---------------------------------------------------------------- worlds ---------------------------------------------------------------------------------

class Ctx:
    """One authored world, its frozen handoffs (real `zoop-ai-handoff` freezes) and the exposure CLI over its OWN ledgers."""

    def __init__(self, world, operator, exports: dict, m: SimpleNamespace):
        self.world, self.operator, self.exports, self.m = world, operator, exports, m
        self.root, self.state = Path(world.root), Path(operator.state)
        # A source change needs exactly the ingestion and the extraction ledger (the S3 relation ledger is never read); a relation retraction needs neither.
        self.ledgers = {name: self.root / name for name in ("ingestion", "extraction")}
        self.pins = {hid: {k: out["receipt"][k] for k in ("manifestDigest", "bundleDigest", "contentDigest")} for hid, out in exports.items()}

    def run(self, query, *, ledgers=AUTO, state: Path | None = None, root: Path | None = None, **kw) -> SimpleNamespace:
        """A relation retraction is given no source ledger by default (it forbids them); every other change is given both."""
        if ledgers is AUTO:
            ledgers = None if query is not None and query["changed"]["kind"] == "s3-relation" else self.ledgers
        return expose(root or self.root, query, state=state or self.state, ledgers=ledgers, **kw)

    def sel(self, hid: str) -> dict:
        return self.operator.sel(hid)


def graph_of(bundle: dict) -> dict:
    """The authored shape of a frozen bundle's edges, read from the bundle alone: id -> (type, source, target, evidence, S3 source refs, structural basis)."""
    return {r["id"]: (r["type"], r["source"], r["target"], sorted(r["evidenceIds"]), sorted((s["jobId"], s["id"]) for s in r["sourceRefs"] if s["kind"] == "s3-relation"),
                      sorted((b["sourceRelation"]["jobId"], b["sourceRelation"]["relationCandidateId"], tuple(sorted(b["evidenceIds"]))) for b in r["basis"]))
            for r in bundle["relations"]}


def assert_authored(m: SimpleNamespace, bundle: dict, hid: str) -> None:
    """The authored graph is what the hand-written expectations assume (a mis-authored world fails HERE, not as a puzzling report difference)."""
    assert bundle["schemaVersion"] == BUNDLE and bundle["handoffId"] == hid
    same(graph_of(bundle), m.graph[hid], f"{hid}: authored edges")
    same(sorted(e["id"] for e in bundle["evidence"]), sorted(m.evidence[hid]), f"{hid}: authored evidence")
    same(sorted((a["articleId"], a["articleVersion"], a["documentId"], a["documentVersion"]) for a in bundle["articles"]), sorted(m.article.values()), f"{hid}: authored articles")
    same({i["id"]: sorted((s["upstream"]["jobId"], s["kind"], s["ref"], s["documentId"]) for s in i["sourceEvents"]) for i in bundle["issues"]}, m.source_events,
         f"{hid}: authored source events")
    same(sorted((s["relation"]["jobId"], s["upstream"]["jobId"]) for s in bundle["sources"]), [("rel-a", "s2-a"), ("rel-b", "s2-b")], f"{hid}: authored S3 jobs and their S2 upstreams")


def freeze_all(operator, world, decisions: dict) -> dict:
    """Freezes and exports one REAL handoff per (id -> decisions); the default operator files are restored afterwards so the first handoff stays exportable."""
    exports = {hid: hs.freeze_export(operator, world, hid, doc) for hid, doc in decisions.items()}
    hs.write_operator(world)
    return exports


def lean_decisions(world) -> dict:
    doc = hs.decisions_doc(world)
    doc["follows"], doc["structural"] = [], []
    return doc


def authored(world) -> SimpleNamespace:
    """The hand-written model of the default (non-chain) worlds: articles, evidence, S3 relation candidates and edge ids, written from the authored data."""
    jobs, refs = world.jobs, world.refs
    m = SimpleNamespace(world=world)
    m.article = {n: (r["documentId"], r["documentVersion"], r["documentId"], r["documentVersion"]) for n, r in refs.items()}
    m.ev = {"EA": hs.evidence_id(world, "a", hs.EVT_A), "GA": hs.evidence_id(world, "a", hs.GEO_A), "SA": hs.evidence_id(world, "a", hs.SUP),
            "EA2": hs.evidence_id(world, "a2", hs.EVT_A2), "QB": hs.evidence_id(world, "b", hs.QB), "GB": hs.evidence_id(world, "b", hs.GEO_B)}
    pi = "PARTICIPATES_IN"
    m.rc = {"A1": hs.relation_id(world, "rel-a", pi, "SYNTH-1", world.evc["a"]), "B1": hs.relation_id(world, "rel-b", pi, "SYNTH-1", "event-a"),
            "B3": hs.relation_id(world, "rel-b", pi, "SYNTH-1", world.evc["b"]), "B2": hs.relation_id(world, "rel-b", pi, "SYNTH-2", world.evc["b"]),
            "SUP": hs.relation_id(world, "rel-a", "SUPPLIES", "SYNTH-3", "SYNTH-1")}
    key = find(jobs["rel-a"], "SUPPLIES", "SYNTH-3", "SYNTH-1")["relationKey"]
    m.e = {"INV_S": hs.edge_id(SUPPLY, "KRX:005930"), "INV_F": hs.edge_id(FACTORY, "KRX:005930"),
           "STR": "edge-" + hs.digest({"type": "STRUCTURALLY_RELATED_TO", "source": SUPPLY, "target": "KRX:000660", "basis": [key]}),
           "FOL": "edge-" + hs.digest({"type": "FOLLOWS", "source": FACTORY, "target": SUPPLY})}
    m.type = {m.e["INV_S"]: "INVOLVES", m.e["INV_F"]: "INVOLVES", m.e["STR"]: "STRUCTURALLY_RELATED_TO", m.e["FOL"]: "FOLLOWS"}
    # The S2 events behind the issues: supply = a's candidate (upstream s2-a) + the snapshot event event-a of upstream s2-b (members a and a2); factory = b's candidate (s2-b).
    m.source_events = {SUPPLY: sorted([("s2-a", "event-candidate", world.evc["a"], refs["a"]["documentId"]), ("s2-b", "snapshot-event", "event-a", refs["a"]["documentId"]),
                                       ("s2-b", "snapshot-event", "event-a", refs["a2"]["documentId"])]),
                       FACTORY: [("s2-b", "event-candidate", world.evc["b"], refs["b"]["documentId"])]}
    return m


def default_graphs(m: SimpleNamespace) -> None:
    """The authored edges of the FULL and LEAN handoffs of a default world (see `authored`), by handoff id."""
    ev_, rc, e = m.ev, m.rc, m.e
    inv = {e["INV_S"]: ("INVOLVES", SUPPLY, "KRX:005930", sorted([ev_["EA"], ev_["EA2"]]), sorted([("rel-a", rc["A1"]), ("rel-b", rc["B1"])]), []),
           e["INV_F"]: ("INVOLVES", FACTORY, "KRX:005930", [ev_["QB"]], [("rel-b", rc["B3"])], [])}
    m.graph = {FULL: {**inv, e["STR"]: ("STRUCTURALLY_RELATED_TO", SUPPLY, "KRX:000660", sorted([ev_["EA"], ev_["EA2"]]), [("rel-a", rc["SUP"])],
                                        [("rel-a", rc["SUP"], (ev_["SA"],))]),
                      e["FOL"]: ("FOLLOWS", FACTORY, SUPPLY, sorted([ev_["QB"], ev_["EA"]]), [], [])},
               LEAN: inv}
    m.evidence = {FULL: list(ev_.values()), LEAN: [v for k, v in ev_.items() if k != "SA"]}


def build_main(base: Path) -> Ctx:
    """The default world whose second document (a2, the supply issue's uncited mention) lives under its OWN source and grant, plus one ingested document no S2 job binds."""
    world = hs.build_world(base / "main", uncited_source=True)
    # Its OWN supplier document id: a document id is derived from (source, supplier id), so reusing `supplier-b` would make this a new VERSION of document b (b's id, which b's frozen binding names).
    world.extra = world.kit.ingest("extra", [{"supplier": "supplier-extra", "html": page(EXTRA_TEXT)}])[0]
    assert world.extra["documentId"] not in {ref["documentId"] for ref in world.refs.values()}, "the extra document must be a document of its own"
    operator = hs.Operator(world)
    hs.write_operator(world)
    exports = freeze_all(operator, world, {FULL: hs.decisions_doc(world), LEAN: lean_decisions(world)})
    m = authored(world)
    default_graphs(m)
    m.grants = {"cited": world.kit.registry["sources"][0]["grant"], "uncited": world.kit.registry["sources"][1]["grant"]}
    assert m.grants["uncited"]["grantId"] != m.grants["cited"]["grantId"] and world.kit.registry["sources"][1]["sourceId"] == UNCITED
    ctx = Ctx(world, operator, exports, m)
    for hid in (FULL, LEAN):
        assert_authored(m, exports[hid]["bundle"], hid)
    return ctx


CHAIN = {"known": "exposure-chain-known-1", "private": "exposure-chain-private-1", "unmapped": "exposure-chain-unmapped-1"}


def build_chain(base: Path) -> Ctx:
    """The `chain` world: rel-a also holds SYNTH-4 -> SYNTH-3 -> SYNTH-1. The middle company is published (`known`), mapped but unpublished (`private`) or unmapped
    (`unmapped`: the structural path is unavailable)."""
    world = hs.build_world(base / "chain", chain=True)
    operator = hs.Operator(world)
    hs.write_operator(world)
    exports = freeze_all(operator, world, {hid: hs.chain_decisions(world, middle) for middle, hid in CHAIN.items()})
    m = SimpleNamespace(world=world)
    jobs, refs = world.jobs, world.refs
    m.article = {n: (r["documentId"], r["documentVersion"], r["documentId"], r["documentVersion"]) for n, r in refs.items()}
    pi = "PARTICIPATES_IN"
    m.ev = {"EA": hs.evidence_id(world, "a", hs.EVT_A), "GA": hs.evidence_id(world, "a", hs.GEO_A), "SA": hs.evidence_id(world, "a", hs.SUP),
            "CH": hs.evidence_id(world, "a", hs.CHAIN), "EA2": hs.evidence_id(world, "a2", hs.EVT_A2), "QB": hs.evidence_id(world, "b", hs.QB),
            "GB": hs.evidence_id(world, "b", hs.GEO_B)}
    m.rc = {"A1": hs.relation_id(world, "rel-a", pi, "SYNTH-1", world.evc["a"]), "SUP": hs.relation_id(world, "rel-a", "SUPPLIES", "SYNTH-3", "SYNTH-1"),
            "CHAIN": hs.relation_id(world, "rel-a", "SUPPLIES", "SYNTH-4", "SYNTH-3"), "B1": hs.relation_id(world, "rel-b", pi, "SYNTH-1", "event-a")}
    k_sup, k_chain = (find(jobs["rel-a"], "SUPPLIES", s, c)["relationKey"] for s, c in (("SYNTH-3", "SYNTH-1"), ("SYNTH-4", "SYNTH-3")))
    structural = lambda target, keys: "edge-" + hs.digest({"type": "STRUCTURALLY_RELATED_TO", "source": SUPPLY, "target": target, "basis": keys})  # noqa: E731
    m.e = {"INV_S": hs.edge_id(SUPPLY, "KRX:005930"), "INV_F": hs.edge_id(FACTORY, "KRX:005930"), "STR1": structural("KRX:000660", [k_sup]),
           "STR2": structural("KRX:000999", [k_sup, k_chain]), "FOL": "edge-" + hs.digest({"type": "FOLLOWS", "source": FACTORY, "target": SUPPLY})}
    m.type = {m.e["INV_S"]: "INVOLVES", m.e["INV_F"]: "INVOLVES", m.e["STR1"]: "STRUCTURALLY_RELATED_TO", m.e["STR2"]: "STRUCTURALLY_RELATED_TO", m.e["FOL"]: "FOLLOWS"}
    ctx = Ctx(world, operator, exports, m)
    # What the authored bundles hold (hand-written): the two-relation edge exists in every handoff, the one-relation edge only where the middle company is published.
    ev_, e = m.ev, m.e
    for middle, hid in CHAIN.items():
        edges = {e["INV_S"], e["INV_F"], e["STR2"], e["FOL"], *([e["STR1"]] if middle == "known" else [])}
        got = graph_of(exports[hid]["bundle"])
        assert set(got) == edges, (hid, sorted(got))
        assert got[e["STR2"]][4] == sorted([("rel-a", m.rc["SUP"]), ("rel-a", m.rc["CHAIN"])]) and got[e["STR2"]][3] == sorted([ev_["EA"], ev_["EA2"]]), got[e["STR2"]]
        assert ev_["CH"] in {x for b in got[e["STR2"]][5] for x in b[2]} and ev_["CH"] in {x["id"] for x in exports[hid]["bundle"]["evidence"]}, "basis-only quote"
        assert ev_["CH"] not in {x for edge in got.values() for x in edge[3]}, "the chain sentence must be a basis-only quote"
        paths = {r["id"]: r["structuralPath"]["status"] for r in exports[hid]["bundle"]["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO"}
        assert paths[e["STR2"]] == ("unavailable" if middle == "unmapped" else "complete"), (hid, paths)
    return ctx


RICH = "exposure-impacts-1"


def build_rich(base: Path) -> Ctx:
    """The `rich` impact world: document a also holds an impact-only sentence (cited by no relation and no issue, only as a verified impact effect)."""
    world = hs.build_world(base / "rich", impact="rich")
    operator = hs.Operator(world)
    hs.write_operator(world)
    exports = freeze_all(operator, world, {RICH: hs.decisions_doc(world)})
    m = authored(world)
    m.ev["INV"] = hs.evidence_id(world, "a", hs.INV)
    ctx = Ctx(world, operator, exports, m)
    bundle = exports[RICH]["bundle"]
    on_edges = {x for r in bundle["relations"] for x in (*r["evidenceIds"], *(y for b in r["basis"] for y in b["evidenceIds"]))}
    on_issues = {x for i in bundle["issues"] for x in i["evidenceIds"]}
    assert m.ev["INV"] in {x["id"] for x in bundle["evidence"]} and m.ev["INV"] not in on_edges | on_issues, "the impact-only sentence must be on no edge and no issue"
    assert any(m.ev["INV"] in {x for side in row["effects"].values() for x in side} for row in bundle["impacts"] if row["effects"]), "it is a verified impact effect"
    return ctx


class Worlds:
    """The authored worlds under one owned base directory, each built once on first use."""

    def __init__(self, base: Path):
        self.base = Path(base)

    @cached_property
    def main(self) -> Ctx:
        return build_main(self.base)

    @cached_property
    def chain(self) -> Ctx:
        return build_chain(self.base)

    @cached_property
    def rich(self) -> Ctx:
        return build_rich(self.base)


# ---------------------------------------------------------------- closure tables of the DEFAULT world (all hand-written) -------------------------------------
# Names: a/a2/b = documents; EA/GA/SA = quotes of a (event, geography, supply basis), EA2 = the quote of a2, QB/GB = quotes of b. INV_S/INV_F = INVOLVES edges of the supply and the
# factory issue, STR = the structural edge of supply, FOL = factory FOLLOWS supply. The supply issue rests on a (two source events) and a2; the factory issue's only source event is
# b's candidate, whose DISPOSITION was computed over the snapshot event event-a (members a and a2).
# S2 upstreams: s2-a binds {a}; s2-b binds {b (incoming), a, a2 (members of event-a)}. S3: rel-a is on s2-a and uses A1 (INV_S) and SUP (STR); rel-b is on s2-b and uses B1 (INV_S) and
# B3 (INV_F). A source change that reaches an upstream taints EVERY used relation of the S3 jobs on it (`upstream-input`), whether it cites or ends at the changed document or not.

def expect_a2(m: SimpleNamespace) -> dict:
    """The uncited article's document, source or grant: only s2-b is reached (rel-b tainted). a2's article and quote only; the supply issue (source-document) and, through its S2
    disposition input, the factory issue. rel-b's factory participation cites and ends at nothing of a2, yet its edge is listed (upstream-input)."""
    ev_, e = m.ev, m.e
    issues = {SUPPLY: ["source-document"], FACTORY: ["disposition-input"]}
    inv = {e["INV_S"]: ["evidence", "issue", "upstream-input"], e["INV_F"]: ["issue", "upstream-input"]}
    return {FULL: want(m, articles=["a2"], evidence=[ev_["EA2"]], issues=issues, relations={**inv, e["STR"]: ["anchor", "evidence", "issue"], e["FOL"]: ["issue"]}),
            LEAN: want(m, articles=["a2"], evidence=[ev_["EA2"]], issues=issues, relations=inv)}


def expect_cited(m: SimpleNamespace) -> dict:
    """The cited source/grant (documents a and b): both S2 upstreams reached, a2's article and quote stay out of the report."""
    ev_, e = m.ev, m.e
    issues = {SUPPLY: ["source-document"], FACTORY: ["disposition-input", "source-document"]}
    inv = {e["INV_S"]: ["evidence", "issue", "upstream-input"], e["INV_F"]: ["evidence", "issue", "upstream-input"]}
    return {FULL: want(m, articles=["a", "b"], evidence=[ev_[k] for k in ("EA", "GA", "SA", "QB", "GB")], issues=issues,
                       relations={**inv, e["STR"]: ["anchor", "basis-evidence", "evidence", "issue", "upstream-input"], e["FOL"]: ["evidence", "issue"]}),
            LEAN: want(m, articles=["a", "b"], evidence=[ev_[k] for k in ("EA", "GA", "QB", "GB")], issues=issues, relations=inv)}


def expect_a(m: SimpleNamespace) -> dict:
    """Document a alone (the supply issue's cited article, also a member of event-a): s2-a and s2-b reached; its quotes only, never b's or a2's."""
    ev_, e = m.ev, m.e
    issues = {SUPPLY: ["source-document"], FACTORY: ["disposition-input"]}
    inv = {e["INV_S"]: ["evidence", "issue", "upstream-input"], e["INV_F"]: ["issue", "upstream-input"]}
    return {FULL: want(m, articles=["a"], evidence=[ev_[k] for k in ("EA", "GA", "SA")], issues=issues,
                       relations={**inv, e["STR"]: ["anchor", "basis-evidence", "evidence", "issue", "upstream-input"], e["FOL"]: ["evidence", "issue"]}),
            LEAN: want(m, articles=["a"], evidence=[ev_[k] for k in ("EA", "GA")], issues=issues, relations=inv)}


def expect_b(m: SimpleNamespace) -> dict:
    """Document b alone (the factory issue's only article, NOT a member of event-a, no citation or endpoint of the supply side): only s2-b is reached, but rel-b's participation in
    event-a (cited a2, the supply edge's) is a model input of that job all the same: the supply INVOLVES edge is listed with `upstream-input` as its ONLY reason, and being the
    supply issue's only involvement it takes the issue down through `involvement-lost` (no source-document, no disposition input). The report is NOT falsely empty for the supply
    side, while only b's article and quotes are listed."""
    ev_, e = m.ev, m.e
    issues = {FACTORY: ["source-document"], SUPPLY: ["involvement-lost"]}
    inv = {e["INV_S"]: ["upstream-input"], e["INV_F"]: ["evidence", "issue", "upstream-input"]}
    return {FULL: want(m, articles=["b"], evidence=[ev_["QB"], ev_["GB"]], issues=issues,
                       relations={**inv, e["STR"]: ["anchor", "issue"], e["FOL"]: ["evidence", "issue"]}),
            LEAN: want(m, articles=["b"], evidence=[ev_["QB"], ev_["GB"]], issues=issues, relations=inv)}


def expect_retraction(m: SimpleNamespace, rc: str) -> dict:
    """A semantic retraction of ONE S3 relation (precise): edges and issues only, never a quote or an article, no upstream-input."""
    e = m.e
    # one of the two sourceRefs of the supply INVOLVES edge (A1 or B1): the WHOLE edge is listed, and since it is the supply issue's only involvement the issue is lost with it
    supply = {FULL: want(m, issues={SUPPLY: ["involvement-lost"]}, relations={e["INV_S"]: ["source-relation"], e["STR"]: ["anchor", "issue"], e["FOL"]: ["issue"]}),
              LEAN: want(m, issues={SUPPLY: ["involvement-lost"]}, relations={e["INV_S"]: ["source-relation"]})}
    cases = {"A1": supply, "B1": supply,
             # the factory issue's only involvement: its FOLLOWS edge goes, the supply side stays
             "B3": {FULL: want(m, issues={FACTORY: ["involvement-lost"]}, relations={e["INV_F"]: ["source-relation"], e["FOL"]: ["issue"]}),
                    LEAN: want(m, issues={FACTORY: ["involvement-lost"]}, relations={e["INV_F"]: ["source-relation"]})},
             # the structural basis: that edge alone; LEAN publishes no structural edge, so it does not use the relation
             "SUP": {FULL: want(m, relations={e["STR"]: ["source-relation"]}), LEAN: want(m, bound=False)}}
    return cases[rc]


# ---------------------------------------------------------------- planted ledger rows, held locks, copies --------------------------------------------------

def plant_current(state: Path, template: str, handoff_id: str, *, row_state: str = "ready", bundle_digest: str | None = None) -> None:
    """Adds ONE row of the CURRENT bundle schema to a ledger with the ledger's own INSERT statements: a copy of the real `template` row under ANOTHER id (so the artifact it names
    belongs to another handoff), another state or another artifact name. For a damaged receipt of a coherent row see `plant_receipt`."""
    db = sqlite3.connect(state / "handoff.sqlite3")
    try:
        row = db.execute("SELECT input_digest,manifest,bundle_digest,content_digest,bundle_bytes,receipt FROM handoffs WHERE handoff_id=?", (template,)).fetchone()
        assert row is not None, template
        failure = "handoff_artifact_missing" if row_state == "failed" else None
        db.execute("INSERT INTO handoffs(handoff_id,input_digest,manifest,bundle_digest,content_digest,bundle_bytes,receipt,state,failure,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (handoff_id, row[0], row[1], bundle_digest or row[2], row[3], row[4], row[5], row_state, failure, hs.LEGACY_AT, hs.LEGACY_AT))
        for n, kind, outcome, code in {"reserved": [], "ready": [(1, "freeze", "written", None)], "failed": [(1, "recover", "artifact-missing", failure)]}[row_state]:
            db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?)", (handoff_id, n, kind, outcome, code, hs.LEGACY_AT))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        db.close()


def plant_receipt(state: Path, source: Path, handoff_id: str, edit) -> None:
    """Inserts the REAL frozen row of `handoff_id` (read from `source`, a ledger that froze it under that very id) into `state`, its artifact copied beside the others, with `edit`
    applied to the stored receipt alone: the row columns, the frozen manifest and the artifact stay coherent with the id, so only the receipt is damaged."""
    origin = sqlite3.connect((source / "handoff.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        row = origin.execute("SELECT input_digest,manifest,bundle_digest,content_digest,bundle_bytes,receipt,state,created_at,updated_at FROM handoffs WHERE handoff_id=?",
                             (handoff_id,)).fetchone()
    finally:
        origin.close()
    assert row is not None and row[6] == "ready", (handoff_id, row and row[6])
    shutil.copyfile(source / "bundles" / f"{row[2]}.json", state / "bundles" / f"{row[2]}.json")
    db = sqlite3.connect(state / "handoff.sqlite3")
    try:
        db.execute("INSERT INTO handoffs(handoff_id,input_digest,manifest,bundle_digest,content_digest,bundle_bytes,receipt,state,failure,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,?,?,'ready',NULL,?,?)", (handoff_id, row[0], row[1], row[2], row[3], row[4], hs.canonical(edit(json.loads(row[5]))), row[7], row[8]))
        db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?)", (handoff_id, 1, "freeze", "written", None, row[7]))
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        db.close()


@contextmanager
def held(path: Path, kind: int):
    """A lock another process holds on a ledger's lock file (`LOCK_EX`: a writer, `LOCK_SH`: another reader)."""
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, kind)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def copy_dir(source: Path, target: Path) -> Path:
    shutil.copytree(source, target)
    return target


def operator_files(ctx: Ctx) -> dict:
    return hs.file_hashes(ctx.root)


# The audit guard is not vacuous: a child that TRIES each forbidden action is aborted by the very hook every exposure run uses, and the permitted reads pass.
PROBE = r'''
import os, socket, sqlite3, subprocess


def attempt(action):
    try:
        action()
    except RuntimeError:
        pass


attempt(lambda: socket.socket().connect(("127.0.0.1", 9)))
attempt(lambda: open(os.path.join(_ROOT, "new"), "w"))
attempt(lambda: os.mkdir(os.path.join(_ROOT, "dir")))
attempt(lambda: os.rename(os.path.join(_ROOT, "keep"), os.path.join(_ROOT, "moved")))
attempt(lambda: subprocess.run(["true"]))
attempt(lambda: sqlite3.connect(os.path.join(_ROOT, "plain.db")))
open(os.path.join(_ROOT, "keep"), "rb").close()
sqlite3.connect("file:" + os.path.join(_ROOT, "ro.db") + "?mode=ro&immutable=1", uri=True).close()
_report()
'''


def guard_effective(scratch: Path) -> str:
    """Runs `PROBE` under the guard in a throwaway directory (removed afterwards): every forbidden action is recorded and aborted, nothing it tried exists afterwards, the
    read of an existing file and the immutable read-only SQLite connection are allowed and listed."""
    scratch.mkdir(parents=True)
    try:
        (scratch / "keep").write_bytes(b"x")
        db = sqlite3.connect(scratch / "ro.db")
        db.execute("CREATE TABLE t(a)")
        db.commit()
        db.close()
        with tempfile.TemporaryFile() as log:
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **hs.CUSTOM,
                   "ZOOP_EXPOSURE_AUDIT_FD": str(log.fileno()), "ZOOP_EXPOSURE_AUDIT_ROOT": str(scratch)}
            child = subprocess.run([sys.executable, "-c", GUARD + PROBE], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=PIPELINE, timeout=120,
                                   pass_fds=(log.fileno(),))
            log.seek(0)
            audit = json.loads(log.read())
        assert child.returncode == 0 and not child.stderr, (child.returncode, child.stderr.decode()[-1000:])
        same(audit["violations"], ["network:socket.connect", "write:open:new", "write:os.mkdir:dir", "write:os.rename:keep", "spawn:subprocess.Popen",
                                   "write:sqlite3.connect:plain.db"], "audit violations")
        same((audit["opened"], audit["sqlite"]), (["keep"], ["plain.db", "ro.db"]), "permitted reads")
        assert sorted(p.name for p in scratch.iterdir()) == ["keep", "ro.db"], "a probe action took effect"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return ("audit guard self-test: a child that tries a network connect, a write-open, a mkdir, a rename, a process spawn and a plain (non-immutable) SQLite connection under the owned root "
            "is aborted by the same hook and none of it takes effect, while reading an existing file and an immutable read-only SQLite connection pass")


def check_audit_guard(worlds: Worlds) -> str:
    return guard_effective(worlds.base / "guard")


# ================================================================ checks (each returns the sentence the final JSON reports) ===================================

def check_authored_worlds(worlds: Worlds) -> str:
    """Every world's frozen bundles equal the authored graph the expectations assume, and the hand-written ids are real ones (builders already asserted the edges)."""
    main = worlds.main
    for hid in (FULL, LEAN):
        assert main.operator.cli("inspect", main.sel(hid))["state"] == "ready"
    for ctx in (worlds.chain, worlds.rich):
        assert ctx.exports and all(out["bundle"]["schemaVersion"] == BUNDLE for out in ctx.exports.values())
    return ("authored worlds: the default world's FULL/LEAN bundles, the chain world's three and the rich impact world's equal the hand-written edges, quotes, S3 source refs, "
            "S3 jobs with their S2 upstreams, source events and the basis-only/impact-only quotes the expectations assume")


def check_revoked_uncited_source(worlds: Worlds) -> str:
    """Acceptance: the selected-bundle report is BYTE-IDENTICAL before and after the uncited source's grant is revoked, while the ordinary export withholds; the cited
    source's own revocation changes nothing either; neither report evaluates rights."""
    main = worlds.main
    m, world, operator = main.m, main.world, main.operator
    queries = {"uncited": q([FULL, LEAN], source_change(UNCITED)), "cited": q([FULL, LEAN], source_change(CITED)),
               "grant": q([LEAN, FULL], grant_change(m.grants["uncited"]["grantId"]))}
    before = {name: main.run(query) for name, query in queries.items()}
    assert operator.cli("export", main.sel(FULL))["delivery"]["status"] == "current"
    try:
        for source_id in (UNCITED, CITED):
            hs.set_grant(world, source_id, False)
            gone = operator.cli("export", main.sel(FULL), expected=2)
            assert gone["delivery"]["status"] == "withheld" and "bundle" not in gone, (source_id, gone)
            for name, query in queries.items():
                after = main.run(query)
                assert after.text == before[name].text, f"revoking {source_id} changed the {name} report"
                assert after.audit["sqlite"] == before[name].audit["sqlite"], "another ledger was opened"
            hs.set_grant(world, source_id, True)
    finally:
        hs.set_grant(world, UNCITED, True)
        hs.set_grant(world, CITED, True)
    again = operator.cli("export", main.sel(FULL))
    assert again["delivery"]["status"] == "current" and again["bundle"] == main.exports[FULL]["bundle"]
    wants = expect_a2(m)
    check_report(main, before["uncited"], queries["uncited"], wants, recorded=True)
    check_report(main, before["grant"], queries["grant"], wants, recorded=True)
    check_report(main, before["cited"], queries["cited"], expect_cited(m), recorded=True)
    return ("revoked grants: the selected-bundle reports of the uncited source (also by grant id), and of the cited source, are byte-identical before/after revoking EITHER grant while "
            "`zoop-ai-handoff export` withholds the handoff (no bundle); rights are never evaluated and restoring them gives the same export")


def check_source_closures(worlds: Worlds) -> str:
    """Source changes through every selector: only the matching articles and quote ids; the all-input basis issue and its linked edges; a source grant distinct from the cited
    article stays isolated; the S2 disposition input reaches the factory issue; every used relation of an S3 job on an affected S2 upstream is a model input (upstream-input), also
    where it cites nothing of the changed document; raw-version-only selectors join the frozen bindings."""
    main = worlds.main
    m = main.m
    refs = main.world.refs
    cases = [("a2 source", source_change(UNCITED), expect_a2), ("a2 grant", grant_change(m.grants["uncited"]["grantId"]), expect_a2),
             ("a2 grant revision", grant_change(m.grants["uncited"]["grantId"], m.grants["uncited"]["revision"]), expect_a2),
             ("a2 document", doc_change(refs["a2"]), expect_a2), ("a2 document+raw", doc_change(refs["a2"], raw=True), expect_a2),
             ("a2 raw only", doc_change(refs["a2"], version=False, raw=True), expect_a2),
             ("cited source", source_change(CITED), expect_cited), ("cited grant", grant_change(m.grants["cited"]["grantId"]), expect_cited),
             ("cited grant revision", grant_change(m.grants["cited"]["grantId"], m.grants["cited"]["revision"]), expect_cited),
             ("a document", doc_change(refs["a"]), expect_a), ("a raw only", doc_change(refs["a"], version=False, raw=True), expect_a),
             ("b document", doc_change(refs["b"]), expect_b), ("b document+raw", doc_change(refs["b"], raw=True), expect_b),
             ("b raw only", doc_change(refs["b"], version=False, raw=True), expect_b)]
    for label, changed, table in cases:
        query = q([LEAN, FULL], changed)
        run = main.run(query)
        check_report(main, run, query, table(m), recorded=True)
        assert run.audit["sqlite"] and not [p for p in run.audit["opened"] + run.audit["sqlite"] if p.startswith("relation/")], f"{label}: the relation ledger was opened"
        assert artifacts_read(run) == sorted(main.pins[h]["bundleDigest"] for h in (FULL, LEAN)), f"{label}: not exactly the selected artifacts were read"
    # Only the handoffs named are reported (never expanded), each with its OWN quotes (LEAN has no supply-basis quote).
    only = main.run(q([LEAN], source_change(CITED)))
    check_report(main, only, q([LEAN], source_change(CITED)), {LEAN: expect_cited(m)[LEAN]}, recorded=True)
    assert FULL not in only.text and only.out["scope"]["handoffIds"] == [LEAN]
    assert artifacts_read(only) == [main.pins[LEAN]["bundleDigest"]], "a handoff that was not selected was read"
    return ("source closures through source/grant/grant-revision/document/document+raw/raw-version-only selectors equal the hand-written reports: the uncited a2 grant reaches a2's "
            "article and quote only, the supply issue (source-document) and the factory issue (S2 disposition input over event-a); every used relation of the S3 job on an affected S2 "
            "upstream is listed as upstream-input (the factory participation that cites and ends at nothing of a2 too); document b alone, which no supply citation or endpoint names, "
            "still lists the supply edge (upstream-input only) and the supply issue (involvement-lost only) with only b's article and quotes; the cited grant leaves a2's quote out; "
            "each handoff reports its own quotes and a narrower selection is never expanded; the S3 relation ledger is never opened")


def check_relation_retraction(worlds: Worlds) -> str:
    """A retracted S3 relation (precise): shared edge (either of its two source refs lists the whole edge), last involvement, FOLLOWS, structural anchor; no article, no quote, no
    upstream-input; no ledger but the handoff's is needed (the same report comes from a directory that holds only the handoff ledger); a pair no selected handoff uses is refused."""
    main = worlds.main
    m = main.m
    ids = [LEAN, FULL]
    for name, job in (("A1", "rel-a"), ("B1", "rel-b"), ("B3", "rel-b"), ("SUP", "rel-a")):
        query = q(ids, relation_change(job, m.rc[name]))
        run = main.run(query)
        check_report(main, run, query, expect_retraction(m, name), recorded=None)
        assert all(not h["articles"] and not h["evidenceIds"] for h in run.out["handoffs"]), "a semantic retraction withdrew a quote"
        assert not [r for h in run.out["handoffs"] for x in h["relations"] for r in x["reasons"] if r == "upstream-input"], "a retraction marked a model input"
        assert not [p for p in run.audit["opened"] + run.audit["sqlite"] if p.split("/")[0] in ("ingestion", "extraction", "relation")], "a source ledger was opened"
        assert artifacts_read(run) == sorted(main.pins[h]["bundleDigest"] for h in (FULL, LEAN)), "a relation report did not read exactly the selected artifacts"
    first = main.run(q(ids, relation_change("rel-a", m.rc["A1"])))
    second = main.run(q(ids, relation_change("rel-b", m.rc["B1"])))
    assert [h["relations"] for h in first.out["handoffs"]] == [h["relations"] for h in second.out["handoffs"]], "the two source refs of one edge list different edges"
    # No source ledger at all: the handoff ledger copied alone into an empty directory answers byte-identically.
    isolated = main.root / "isolated"
    try:
        shutil.copytree(main.state, isolated / "handoff")
        alone = expose(isolated, q(ids, relation_change("rel-a", m.rc["A1"])), state=isolated / "handoff", ledgers=None)
        assert alone.text == first.text, "a relation report depends on a source ledger"
    finally:
        shutil.rmtree(isolated, ignore_errors=True)
    # Unused pairs: a company the operator did not map, a candidate of ANOTHER job, an unknown job, and a pair only the NOT selected handoff uses.
    for changed in (relation_change("rel-b", m.rc["B2"]), relation_change("rel-a", m.rc["B3"]), relation_change("rel-zzz", "rc-" + "0" * 64)):
        refused(main.run(q(ids, changed), expected=2), "changed_relation_unused")
    refused(main.run(q([LEAN], relation_change("rel-a", m.rc["SUP"])), expected=2), "changed_relation_unused")
    one = main.run(q([FULL], relation_change("rel-a", m.rc["SUP"])))
    check_report(main, one, q([FULL], relation_change("rel-a", m.rc["SUP"])), {FULL: expect_retraction(m, "SUP")[FULL]}, recorded=None)
    return ("relation retraction (precise, no upstream-input): either source ref of the shared supply edge lists the whole edge, the lost involvement removes the supply (or factory) issue "
            "with its structural/FOLLOWS edges, the structural basis lists that edge alone, LEAN (no structural edge) is bound=false/exposed=false, articles and evidence stay empty, no "
            "source ledger is opened (identical bytes from a directory holding only the handoff ledger); unused pairs (unmapped company, another job's candidate, unknown job, only an "
            "unselected handoff uses it) refuse as changed_relation_unused")


def check_chain_retraction(worlds: Worlds) -> str:
    """Structural anchors: a published/private middle company names the participant (anchor); an unavailable path cannot, so it is marked conservatively
    (anchor-undetermined) only when an INVOLVES edge of the same issue is affected; basis relations are shared across structural edges."""
    chain = worlds.chain
    m, e = chain.m, chain.m.e
    known, private, unmapped = CHAIN["known"], CHAIN["private"], CHAIN["unmapped"]
    ids = [unmapped, known, private]
    lost = {SUPPLY: ["involvement-lost"]}
    query = q(ids, relation_change("rel-a", m.rc["A1"]))
    check_report(chain, chain.run(query), query, {
        known: want(m, issues=lost, relations={e["INV_S"]: ["source-relation"], e["STR1"]: ["anchor", "issue"], e["STR2"]: ["anchor", "issue"], e["FOL"]: ["issue"]}),
        private: want(m, issues=lost, relations={e["INV_S"]: ["source-relation"], e["STR2"]: ["anchor", "issue"], e["FOL"]: ["issue"]}),
        unmapped: want(m, issues=lost, relations={e["INV_S"]: ["source-relation"], e["STR2"]: ["anchor-undetermined", "issue"], e["FOL"]: ["issue"]})}, recorded=None)
    query = q(ids, relation_change("rel-a", m.rc["SUP"]))
    check_report(chain, chain.run(query), query, {
        known: want(m, relations={e["STR1"]: ["source-relation"], e["STR2"]: ["source-relation"]}), private: want(m, relations={e["STR2"]: ["source-relation"]}),
        unmapped: want(m, relations={e["STR2"]: ["source-relation"]})}, recorded=None)
    query = q(ids, relation_change("rel-a", m.rc["CHAIN"]))
    check_report(chain, chain.run(query), query, {hid: want(m, relations={e["STR2"]: ["source-relation"]}) for hid in ids}, recorded=None)
    # The basis-only quote (the chain sentence of document a, cited by no issue and no edge's own evidence) is reached by a document change, and its edge says why.
    entry = chain.run(q([known], doc_change(chain.world.refs["a"]))).out["handoffs"][0]
    assert m.ev["CH"] in entry["evidenceIds"] and "basis-evidence" in {r for x in entry["relations"] if x["id"] == e["STR2"] for r in x["reasons"]}, entry
    assert [a["documentId"] for a in entry["articles"]] == [chain.world.refs["a"]["documentId"]]
    return ("chain world: an INVOLVES retraction marks the structural edges whose first path company is the participant (anchor) and, for the unavailable path of the unmapped-middle handoff, "
            "conservatively anchor-undetermined; a retracted basis relation lists exactly the structural edges resting on it (SUPPLIES: both edges, the second link: the two-relation edge); "
            "a document change reaches the basis-only chain quote (basis-evidence) without it being on any edge's own evidence")


def check_impact_evidence(worlds: Worlds) -> str:
    """The impact-only sentence of document a (on no edge and no issue) is reached by a change of document a."""
    rich = worlds.rich
    m, e = rich.m, rich.m.e
    query = q([RICH], doc_change(rich.world.refs["a"]))
    run = rich.run(query)
    entry = run.out["handoffs"][0]
    same(entry["evidenceIds"], sorted([m.ev[k] for k in ("EA", "GA", "SA", "INV")]), "rich: document a's quotes, the impact-only one included")
    assert [a["documentId"] for a in entry["articles"]] == [rich.world.refs["a"]["documentId"]]
    same({r["id"]: r["reasons"] for r in entry["relations"]}, {e["INV_S"]: ["evidence", "issue", "upstream-input"], e["INV_F"]: ["issue", "upstream-input"],
                                                                    e["STR"]: ["anchor", "basis-evidence", "evidence", "issue", "upstream-input"], e["FOL"]: ["evidence", "issue"]}, "rich: edges")
    same({i["id"]: i["reasons"] for i in entry["issues"]}, {SUPPLY: ["source-document"], FACTORY: ["disposition-input"]}, "rich: issues")
    assert rich.pins[RICH] == {k: entry[k] for k in rich.pins[RICH]}
    return "rich impact world: a change of document a reaches its impact-only sentence (on no edge and no issue) together with its other quotes; document b's quotes stay out"


def check_identities(worlds: Worlds) -> str:
    """Unknown versus recorded-but-unbound identities."""
    main = worlds.main
    m, world = main.m, main.world
    ids = [FULL, LEAN]
    ref_a2 = world.refs["a2"]
    unknown = [source_change("no-such-source"), grant_change("no-such-grant"), grant_change(m.grants["cited"]["grantId"], "rights-9"),
               {"kind": "document", "documentId": "doc-unknown", "documentVersion": None, "rawVersion": None},
               {"kind": "document", "documentId": ref_a2["documentId"], "documentVersion": ref_a2["documentVersion"], "rawVersion": "0" * 64},
               {"kind": "document", "documentId": ref_a2["documentId"], "documentVersion": None, "rawVersion": "0" * 64}]
    for changed in unknown:
        refused(main.run(q(ids, changed), expected=2), "changed_identity_unknown")
    extra = world.extra
    for changed in (doc_change(extra), doc_change(extra, version=False, raw=True), {"kind": "document", "documentId": extra["documentId"], "documentVersion": None, "rawVersion": None}):
        query = q(ids, changed)
        run = main.run(query)
        assert run.out["identity"] == {"boundInSelection": False, "recordedInIngestion": True}, run.out["identity"]
        check_report(main, run, query, {hid: want(m, bound=False) for hid in ids}, recorded=True)
    return ("identities: an unknown source, grant, grant revision, document id and a wrong raw version are changed_identity_unknown (never a success-empty report); a document the ingestion "
            "ledger records but no selected handoff binds is exit 0 with boundInSelection=false, recordedInIngestion=true and every handoff bound=false/exposed=false/empty")


def check_invalid_input(worlds: Worlds) -> str:
    """Input and flag errors are refused before ANY ledger opens: the ledger directories do not even exist, and no file or database is opened."""
    main = worlds.main
    m = main.m
    absent = main.root / "absent"
    nowhere = {name: absent / name for name in ("ingestion", "extraction")}
    good = q([FULL], source_change(UNCITED))
    relation = q([FULL], relation_change("rel-a", m.rc["A1"]))
    bad: dict[str, tuple] = {}

    def add(name, value, ledgers=nowhere):
        bad[name] = (value if isinstance(value, bytes) else json_bytes(value), ledgers)

    add("not json", b"not json")
    add("array", b"[]")
    add("empty object", {})
    add("invalid utf-8", b'{"schemaVersion":"\xff"}')
    add("wrong schema", {**good, "schemaVersion": "zoop-handoff-exposure-2"})
    add("unknown top-level key", {**good, "surprise": 1})
    add("unknown changed key", {**good, "changed": {**good["changed"], "surprise": 1}})
    add("missing changed key", {**good, "changed": {"kind": "source"}})
    add("missing handoffIds", {key: value for key, value in good.items() if key != "handoffIds"})
    add("no handoff", q([], good["changed"]))
    add("duplicate handoff", q([FULL, FULL], good["changed"]))
    add("21 handoffs", q([f"h{n:02d}" for n in range(21)], good["changed"]))
    add("handoff id with a space", q(["a b"], good["changed"]))
    add("empty handoff id", q([""], good["changed"]))
    add("201-character handoff id", q(["h" * 201], good["changed"]))
    add("unknown kind", q([FULL], {"kind": "article", "sourceId": "x"}))
    add("document version not a hash", q([FULL], {"kind": "document", "documentId": "d", "documentVersion": "ABC", "rawVersion": None}))
    add("document key missing (all keys are required)", q([FULL], {"kind": "document", "documentId": "d", "documentVersion": None}))
    add("candidate id without a job", q([FULL], {"kind": "s3-relation", "relationCandidateId": "rc-" + "0" * 64}), None)
    add("job without a candidate id", q([FULL], {"kind": "s3-relation", "jobId": "rel-a"}), None)
    add("malformed candidate id", q([FULL], relation_change("rel-a", "rc-1234")), None)
    add("relation retraction given both source ledgers", relation)
    add("relation retraction given one source ledger", relation, {"extraction": nowhere["extraction"]})
    add("source change without source ledgers", good, None)
    add("source change with only the ingestion ledger", good, {"ingestion": nowhere["ingestion"]})
    add("source change with only the extraction ledger", good, {"extraction": nowhere["extraction"]})
    for name, (data, ledgers) in bad.items():
        run = main.run(None, stdin=data, ledgers=ledgers, state=absent / "handoff", expected=2)
        refused(run, "input_or_configuration_invalid")
        assert run.audit["opened"] == [] and run.audit["sqlite"] == [], (name, "a file or ledger was opened", run.audit)
    assert not absent.exists(), "a refused command created a directory"
    # The same flag errors with REAL ledgers: still nothing opened.
    for query, ledgers in ((good, {"ingestion": main.ledgers["ingestion"]}), (good, {"extraction": main.ledgers["extraction"]}), (relation, main.ledgers), (good, None)):
        run = main.run(query, ledgers=ledgers, expected=2)
        refused(run, "input_or_configuration_invalid")
        assert run.audit["opened"] == [] and run.audit["sqlite"] == []
    # The S3 relation ledger is no input any more: its flag does not exist (argparse refuses the command line before anything is read).
    gone = main.run(good, ledgers={**main.ledgers, "relation": main.root / "relation"}, usage_error=True)
    assert gone.audit["opened"] == [] and "--relation-state-dir" in gone.stderr, gone.stderr
    # Size: exactly 65,536 bytes of (valid) JSON is read; one more byte is command_input_limit.
    raw = json_bytes(relation)
    limit = main.run(None, stdin=raw + b" " * (65_537 - len(raw)), expected=2)
    refused(limit, "command_input_limit")
    assert limit.audit["opened"] == []
    fits = main.run(None, stdin=raw + b" " * (65_536 - len(raw)), ledgers=None)
    check_report(main, fits, relation, {FULL: expect_retraction(m, "A1")[FULL]}, recorded=None)
    # 20 handoff ids are allowed: 19 unknown ones are ALL listed (sorted), the real one is not, and nothing is reported.
    names = sorted(f"h{n:02d}" for n in range(19))
    run = main.run(q([FULL, *reversed(names)], relation_change("rel-a", m.rc["A1"])), expected=2)
    refused(run, "handoff_selection_unmappable", {"handoffs": [{"handoffId": n, "code": "handoff_not_found"} for n in names]})
    return (f"invalid input: {len(bad) + 4} malformed commands (bad JSON/UTF-8/schema/keys, 0/duplicate/21 handoffs, bad ids and hashes, a bare candidate id, wrong ingestion/extraction flag "
            "combinations) are input_or_configuration_invalid before any file or database is opened (the ledger directories do not exist and are not created); the removed "
            "--relation-state-dir is refused by argparse; 65,536 bytes are read, 65,537 are command_input_limit; 20 handoff ids are accepted and every unknown one is listed")


def check_selection_refusals(worlds: Worlds) -> str:
    """One unmappable selected handoff refuses the WHOLE report (never a partial success), listing every failing handoff and no identity; history is judged from the ledger
    alone (its artifact and the source ledgers are never opened); a selection that does not name the damaged rows is unaffected."""
    main = worlds.main
    m, world = main.m, main.world
    state = copy_dir(main.state, main.root / "handoff-damaged")
    files, bundle = operator_files(main), main.exports[FULL]["bundle"]
    plant_current(state, FULL, "exp-alias")                                       # the real artifact of FULL under another id: the bundle names another handoff
    plant_current(state, FULL, "exp-nofile", bundle_digest="0" * 64)              # a ready row whose artifact does not exist
    plant_current(state, FULL, "exp-reserved", row_state="reserved")
    plant_current(state, FULL, "exp-failed", row_state="failed")
    hs.plant_legacy_handoff(state, hs.manifest_doc(world, "exp-badreceipt", files), bundle, schema=hs.BUNDLE_4, damaged=True)       # a receipt without a bundle schema
    hs.plant_legacy_handoff(state, hs.manifest_doc(world, "hist-4", files), bundle, schema=hs.BUNDLE_4, artifact="garbage")           # history: its garbage artifact is never read
    hs.plant_legacy_handoff(state, hs.manifest_doc(world, "hist-6", files), bundle, schema=hs.BUNDLE_6, row_state="reserved", artifact="missing")
    artifact = state / "bundles" / f"{main.pins[LEAN]['bundleDigest']}.json"
    original = artifact.read_bytes()
    os.chmod(artifact, 0o600)
    artifact.write_bytes(original.replace(b'"KRX:005930"', b'"KRX:005931"', 1))
    assert artifact.read_bytes() != original
    detail = sorted([{"handoffId": "exp-alias", "code": "handoff_artifact_invalid"}, {"handoffId": "exp-badreceipt", "code": "handoff_state_invalid"},
                     {"handoffId": "exp-failed", "code": "handoff_not_ready", "state": "failed"}, {"handoffId": LEAN, "code": "handoff_artifact_invalid"},
                     {"handoffId": "exp-nofile", "code": "handoff_artifact_missing"}, {"handoffId": "exp-reserved", "code": "handoff_not_ready", "state": "reserved"},
                     {"handoffId": "ghost", "code": "handoff_not_found"}, {"handoffId": "hist-4", "code": "handoff_contract_changed"},
                     {"handoffId": "hist-6", "code": "handoff_contract_changed"}], key=lambda item: item["handoffId"])
    selection = [FULL, *(item["handoffId"] for item in reversed(detail))]
    for changed in (relation_change("rel-a", m.rc["A1"]), source_change(UNCITED)):
        run = main.run(q(selection, changed), state=state, expected=2)
        refused(run, "handoff_selection_unmappable", {"handoffs": detail})
        assert FULL not in [item["handoffId"] for item in run.out["error"]["detail"]["handoffs"]], "the intact handoff was listed as failing"
    # The intact handoff alone is unaffected by the damaged rows around it (the report equals the one over the pristine ledger).
    for query in (q([FULL], relation_change("rel-a", m.rc["A1"])), q([FULL], source_change(UNCITED))):
        assert main.run(query, state=state).text == main.run(query).text
    # History only: no artifact, no source ledger (the flags name directories that do not exist), and the garbage/missing artifacts are never opened.
    absent = main.root / "absent-sources"
    nowhere = {name: absent / name for name in ("ingestion", "extraction")}
    run = main.run(q(["hist-4", "hist-6"], source_change(UNCITED)), state=state, ledgers=nowhere, expected=2)
    refused(run, "handoff_selection_unmappable", {"handoffs": [{"handoffId": "hist-4", "code": "handoff_contract_changed"}, {"handoffId": "hist-6", "code": "handoff_contract_changed"}]})
    assert artifacts_read(run) == [] and not absent.exists(), run.audit
    assert not [p for p in run.audit["opened"] + run.audit["sqlite"] if p.split("/")[0] in ("ingestion", "extraction", "relation")]
    # Mixed schema: one history handoff refuses the whole report although the other is current.
    mixed = main.run(q([FULL, "hist-4"], relation_change("rel-a", m.rc["A1"])), state=state, expected=2)
    refused(mixed, "handoff_selection_unmappable", {"handoffs": [{"handoffId": "hist-4", "code": "handoff_contract_changed"}]})
    # A ledger or directory that is not one: missing, a foreign file.
    missing = main.root / "handoff-missing"
    refused(main.run(q([FULL], relation_change("rel-a", m.rc["A1"])), state=missing, expected=2), "handoff_state_missing")
    assert not missing.exists(), "a missing ledger was created"
    foreign = copy_dir(main.state, main.root / "handoff-foreign")
    (foreign / "foreign.txt").write_bytes(b"x")
    refused(main.run(q([FULL], relation_change("rel-a", m.rc["A1"])), state=foreign, expected=2), "state_namespace_conflict", {"ledger": "handoff"})
    return ("selection refusals: a ledger holding a ghost id, a history row (`-4` garbage artifact, `-6` reserved without its file), a receipt without a schema, a reserved and a failed current "
            "row, a missing artifact, an artifact of another handoff and a tampered artifact refuses the WHOLE report (relation and source changes alike) listing every failing handoff "
            "sorted with its code and no identity; the intact handoff is not listed and reports normally when selected alone; history-only selections open no artifact and no source ledger; "
            "mixed current+history selections refuse; a missing ledger is not created, a foreign file is state_namespace_conflict")


def check_damaged_current_receipts(worlds: Worlds) -> str:
    """A receipt that names the CURRENT bundle schema is not thereby valid: one that is nothing but the schema string, one whose content, bundle or manifest digest is forged, one
    whose source pin is forged and one holding an equal-valued float/bool substitute are damaged state. The rows are REAL: each handoff is frozen under its OWN id by the installed
    CLI (so its row columns, frozen manifest and artifact agree with each other and with that id, and only the receipt is damaged afterwards). A ledger holding them refuses the WHOLE
    report (relation and source changes alike, intact handoffs beside them included), listing them without any identity; the intact handoffs, selected alone, report as before."""
    main = worlds.main
    m, world, operator = main.m, main.world, main.operator
    files = operator_files(main)
    damage = {"exp-schema-only": lambda r: {"bundleSchema": r["bundleSchema"]}, "exp-forged-content": lambda r: {**r, "contentDigest": "1" * 64},
              "exp-forged-bundle": lambda r: {**r, "bundleDigest": "2" * 64}, "exp-forged-manifest": lambda r: {**r, "manifestDigest": "3" * 64},
              "exp-forged-source": lambda r: {**r, "sources": [{**r["sources"][0], "reviewDigest": "4" * 64}, *r["sources"][1:]]},
              # equal-valued substitutes of another JSON type: 123.0 for 123, false for 0
              "exp-float-bytes": lambda r: {**r, "bundleBytes": float(r["bundleBytes"])}, "exp-bool-count": lambda r: {**r, "counts": {**r["counts"], "pathCompanies": False}}}
    names = sorted(damage)
    pristine = main.root / "handoff-receipts-src"          # a scratch ledger holding ONLY these seven real, intact handoffs
    for name in names:
        operator.cli("freeze", hs.manifest_doc(world, name, files), state=pristine)
    query = q(names, relation_change("rel-a", m.rc["A1"]))
    control = main.run(query, state=pristine)
    reference = main.run(q([FULL], relation_change("rel-a", m.rc["A1"]))).out["handoffs"][0]
    keys = ("bound", "exposed", "articles", "issues", "relations", "evidenceIds", "counts")
    assert [h["handoffId"] for h in control.out["handoffs"]] == names and all({k: h[k] for k in keys} == {k: reference[k] for k in keys} for h in control.out["handoffs"]), \
        "the undamaged twins of the planted rows must report exactly like the handoff they were frozen from"
    state = copy_dir(main.state, main.root / "handoff-receipts")
    for name, edit in damage.items():
        plant_receipt(state, pristine, name, edit)
    detail = [{"handoffId": name, "code": "handoff_state_invalid"} for name in names]
    selection = [LEAN, *reversed(names), FULL]
    for changed in (relation_change("rel-a", m.rc["A1"]), source_change(UNCITED)):
        refused(main.run(q(selection, changed), state=state, expected=2), "handoff_selection_unmappable", {"handoffs": detail})
    for name in names:
        refused(main.run(q([name], relation_change("rel-a", m.rc["A1"])), state=state, expected=2), "handoff_selection_unmappable",
                {"handoffs": [{"handoffId": name, "code": "handoff_state_invalid"}]})
    for check in (q([FULL, LEAN], relation_change("rel-a", m.rc["A1"])), q([FULL, LEAN], source_change(UNCITED))):
        assert main.run(check, state=state).text == main.run(check).text, "damaged rows around the selection changed its report"
    return ("damaged current receipts: seven REAL handoffs (own ids, coherent row/manifest/artifact; their undamaged twins report exactly like FULL) whose stored receipt names the current "
            "bundle schema but is schema-string-only, carries a forged content/bundle/manifest digest or source pin, or an equal-valued float/bool substitute (123.0, false) are "
            "handoff_state_invalid; selected with intact handoffs (relation and source changes alike) they refuse the WHOLE report listing only the damaged ones and no identity; the intact "
            "handoffs selected alone report byte-identically to the pristine ledger")


def check_hot_wal(worlds: Worlds) -> str:
    """A hot WAL is a failure, never a recovery: no artifact fast path, no checkpoint (the bytes of every file stay); a writer settles it and the report is then the same."""
    main = worlds.main
    m, world, operator = main.m, main.world, main.operator
    files, bundle = operator_files(main), main.exports[FULL]["bundle"]
    relation = lambda ids: q(ids, relation_change("rel-a", m.rc["A1"]))  # noqa: E731
    baseline = main.run(relation([FULL]))
    # (1) a writer killed after its reservation leaves a committed row ONLY in the write-ahead log.
    wal = copy_dir(main.state, main.root / "handoff-wal")
    operator.cli("freeze", hs.manifest_doc(world, "killed-1", files), expected=9, hook="kill-after-reserve", state=wal)
    assert (wal / "handoff.sqlite3-wal").stat().st_size > 0
    for ids in ([FULL], ["killed-1"], [FULL, LEAN]):
        run = main.run(relation(ids), state=wal, expected=2)
        refused(run, "handoff_recovery_required")
        assert artifacts_read(run) == [], "an artifact was read behind a hot WAL"
    run = main.run(q([FULL], source_change(UNCITED)), state=wal, expected=2)
    refused(run, "handoff_recovery_required")
    assert not [p for p in run.audit["opened"] + run.audit["sqlite"] if p.split("/")[0] in ("ingestion", "extraction", "relation")], "a source ledger was opened behind a hot WAL"
    settled = operator.cli("recover", operator.sel("killed-1"), state=wal)
    assert settled["state"] == "failed"
    assert main.run(relation([FULL]), state=wal).text == baseline.text, "settling the WAL changed the report"
    refused(main.run(relation(["killed-1"]), state=wal, expected=2), "handoff_selection_unmappable", {"handoffs": [{"handoffId": "killed-1", "code": "handoff_not_ready", "state": "failed"}]})
    # (2) history rows that exist ONLY in the WAL are judged from the ledger alone (a private read-only copy outside the owned tree): contract_changed; any current handoff
    # selected beside them still meets the hot WAL.
    history = copy_dir(main.state, main.root / "handoff-wal-history")
    hs.plant_legacy_handoff(history, hs.manifest_doc(world, "hist-wal", files), bundle, schema=hs.BUNDLE_4, artifact="garbage", wal=True)
    assert (history / "handoff.sqlite3-wal").stat().st_size > 0
    run = main.run(relation(["hist-wal"]), state=history, expected=2)
    refused(run, "handoff_selection_unmappable", {"handoffs": [{"handoffId": "hist-wal", "code": "handoff_contract_changed"}]})
    assert artifacts_read(run) == [], "the history artifact was read"
    refused(main.run(relation([FULL, "hist-wal"]), state=history, expected=2), "handoff_recovery_required")
    return ("hot WAL: a killed writer's row only in the write-ahead log makes any selection a handoff_recovery_required (relation and source changes, current or unknown ids; no artifact and "
            "no source ledger opened, every byte, mode and mtime kept, including the WAL); after a writer settles it the same report is returned; a history row only in the WAL is "
            "contract_changed from a private read-only copy with its artifact never read")


def check_source_ledgers(worlds: Worlds) -> str:
    """Missing, hot, foreign, damaged, empty and wrong source ledgers, a busy writer, coexisting readers, and no need of the S3 relation ledger."""
    main, chain = worlds.main, worlds.chain
    m = main.m
    query = q([FULL], source_change(UNCITED))
    expected_report = main.run(query)
    check_report(main, expected_report, query, {FULL: expect_a2(m)[FULL]}, recorded=True)
    # Missing: refused, never created (each ledger alone).
    for name, code in (("ingestion", "ingestion_state_missing"), ("extraction", "extraction_state_missing")):
        gone = main.root / f"{name}-missing"
        refused(main.run(query, ledgers={**main.ledgers, name: gone}, expected=2), code)
        assert not gone.exists(), f"a missing {name} ledger was created"
    # Hot WAL, damaged database, foreign file: refused with the owner's code (ledger-ambiguous codes name the ledger).
    for name, code in (("ingestion", "ingestion_recovery_required"), ("extraction", "extraction_recovery_required")):
        hot = copy_dir(main.ledgers[name], main.root / f"{name}-hot")
        (hot / f"{name}.sqlite3-wal").write_bytes(b"hot")
        refused(main.run(query, ledgers={**main.ledgers, name: hot}, expected=2), code)
    damaged = copy_dir(main.ledgers["extraction"], main.root / "extraction-damaged")
    (damaged / "extraction.sqlite3").write_bytes(b"this is not a database" * 64)
    refused(main.run(query, ledgers={**main.ledgers, "extraction": damaged}, expected=2), "extraction_state_invalid")
    foreign = copy_dir(main.ledgers["extraction"], main.root / "extraction-foreign")
    (foreign / "foreign.txt").write_bytes(b"x")
    refused(main.run(query, ledgers={**main.ledgers, "extraction": foreign}, expected=2), "state_namespace_conflict", {"ledger": "extraction"})
    # An extraction ledger that does not hold the bundle's S2 upstream (an EMPTY one), and the wrong world's ledgers (the chain world's: same S2 job ids, other inputs): the pinned
    # upstream is not what the scanned ledger froze, never a success-empty report.
    empty = main.root / "extraction-empty"
    ExtractionStore(empty, main.ledgers["ingestion"]).close()
    refused(main.run(query, ledgers={**main.ledgers, "extraction": empty}, expected=2), "handoff_selection_unmappable",
            {"handoffs": [{"handoffId": FULL, "code": "handoff_source_unresolved", "jobId": "s2-a", "reason": "upstream_not_in_scanned_ledger"}]})
    wrong = expose(main.root.parent, query, state=main.state, ledgers=chain.ledgers, expected=2)
    refused(wrong, "handoff_selection_unmappable", {"handoffs": [{"handoffId": FULL, "code": "handoff_source_unresolved", "jobId": "s2-a", "reason": "upstream_input_mismatch"}]})
    # A writer holds a ledger: busy (every reader fails), while other readers coexist.
    with held(main.state / "handoff.lock", fcntl.LOCK_EX):
        refused(main.run(query, expected=2), "handoff_busy")
    for name, code in (("ingestion", "ingestion_busy"), ("extraction", "extraction_busy")):
        with held(main.ledgers[name] / f"{name}.lock", fcntl.LOCK_EX):
            refused(main.run(query, expected=2), code)
    with ExitStack() as stack:
        for path in (main.state / "handoff.lock", *(main.ledgers[n] / f"{n}.lock" for n in main.ledgers)):
            stack.enter_context(held(path, fcntl.LOCK_SH))
        assert main.run(query).text == expected_report.text, "a shared lock held by another reader changed the report"
    # The S3 relation ledger is not needed: a directory holding only copies of the handoff, ingestion and extraction ledgers answers byte-identically.
    isolated = main.root / "isolated-sources"
    try:
        for name, path in (("handoff", main.state), *main.ledgers.items()):
            shutil.copytree(path, isolated / name)
        alone = expose(isolated, query, state=isolated / "handoff", ledgers={name: isolated / name for name in main.ledgers})
        assert alone.text == expected_report.text, "a source report depends on a ledger other than ingestion and extraction"
    finally:
        shutil.rmtree(isolated, ignore_errors=True)
    return ("source ledgers: a missing ingestion/extraction ledger is refused and not created, a hot WAL, a damaged database and a foreign file are refused with the owner's code "
            "(the ledger-ambiguous one names the ledger), an empty extraction ledger (upstream_not_in_scanned_ledger) and the wrong world's ledgers (upstream_input_mismatch) are "
            "handoff_source_unresolved naming the S2 upstream, a held exclusive lock on any ledger is *_busy while shared locks of other readers coexist and change nothing; the S3 relation "
            "ledger is not needed (byte-identical report from copies of the handoff, ingestion and extraction ledgers alone)")


def check_determinism_and_limits(worlds: Worlds) -> str:
    """Same input, same canonical bytes (any key order, whitespace or handoff order); a selected scope is never expanded; an oversized report refuses whole."""
    main = worlds.main
    query = q([FULL, LEAN], source_change(CITED))
    first = main.run(query)
    assert main.run(query).text == first.text, "the same input gave other bytes"
    assert main.run(q([LEAN, FULL], source_change(CITED))).text == first.text, "the handoff order changed the report"
    shuffled = json.dumps({"changed": {"sourceId": CITED, "kind": "source"}, "handoffIds": [LEAN, FULL], "schemaVersion": SCHEMA}, indent=2).encode()
    assert main.run(None, stdin=shuffled).text == first.text, "key order or whitespace changed the report"
    # One handoff of two: the other is never reported.
    alone = main.run(q([LEAN], source_change(CITED)))
    assert FULL not in alone.text and [h["handoffId"] for h in alone.out["handoffs"]] == [LEAN]
    assert artifacts_read(alone) == [main.pins[LEAN]["bundleDigest"]], "a handoff that was not selected was read"
    assert artifacts_read(first) == sorted(main.pins[h]["bundleDigest"] for h in (FULL, LEAN))
    # The limit: exactly the output size fits, one byte less is refused whole (no partial report, nothing truncated).
    size = len(first.text.encode())
    assert main.run(query, limit=size).text == first.text
    refused(main.run(query, limit=size - 1, expected=2), "exposure_report_limit", {"bytes": size, "limit": size - 1})
    refused(main.run(query, limit=100, expected=2), "exposure_report_limit", {"bytes": size, "limit": 100})
    return ("determinism: the same query gives the same canonical bytes in separate processes, in any handoff order, key order and whitespace; a narrower selection reports only the named "
            "handoff; MAX_OUTPUT = the exact output size fits, one byte less is exposure_report_limit with {bytes, limit} and no partial output")


def check_console_script(worlds: Worlds) -> str:
    """The installed console script itself (no audit hook) gives the same bytes as the entry point under the hook, and leaves the owned tree untouched."""
    main = worlds.main
    script = Path(sys.executable).parent / CLI
    if not (script.is_file() and os.access(script, os.X_OK)):
        raise SystemExit(f"{CLI} is not installed next to {sys.executable} (run `make pipeline-install`)")
    query = q([FULL, LEAN], source_change(UNCITED))
    guarded = main.run(query)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **ownership_env(), **hs.CUSTOM}
    argv = [str(script), "--state-dir", str(main.state), *(part for name, path in main.ledgers.items() for part in (f"--{name}-state-dir", str(path)))]
    before = hs.ledger_snapshot(main.root)
    child = subprocess.run(argv, input=json_bytes(query), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=main.root, timeout=300)
    assert child.returncode == 0 and not child.stderr and child.stdout.decode() == guarded.text, (child.returncode, child.stderr.decode()[-1000:])
    assert hs.ledger_snapshot(main.root) == before
    return f"console script: the installed `{CLI}` (no hook) prints byte-identical output to the guarded entry-point run and changes nothing"


CHECKS = (check_audit_guard, check_authored_worlds, check_revoked_uncited_source, check_source_closures, check_relation_retraction, check_chain_retraction,
          check_impact_evidence, check_identities, check_invalid_input, check_selection_refusals, check_damaged_current_receipts, check_hot_wal, check_source_ledgers,
          check_determinism_and_limits, check_console_script)


# ================================================================ smoke ======================================================================================

def smoke(base: Path) -> dict:
    worlds = Worlds(base)
    checks = [check(worlds) for check in CHECKS]
    sample = worlds.main.run(q([FULL], source_change(UNCITED))).out
    assert STATS["auditViolations"] == 0 and STATS["runs"] > 0
    return {"status": "passed", "schemaVersion": SCHEMA, "providerCalls": 0, "modelCalls": 0, "checks": checks,
            "childProcesses": STATS["runs"], "ownedTreeComparisons": STATS["snapshotsCompared"], "ledgerOrStateWrites": 0,
            "networkAttempts": "the audit hook rejected sockets, process spawns, writes under the owned state root and any non-immutable SQLite connection in every exposure child; none occurred",
            "readOnlyOpens": {"files": STATS["readOnlyOpens"], "sqliteConnections": STATS["sqliteOpens"]},
            "appliedToApp": ("NO. Every report is a private, identity-only PROPOSAL for the selected handoffs; the app exclusion overlay, app versions, Neo4j graph versions, article listing and "
                             "every other store were neither read nor changed"),
            "completeness": ("NO global completeness is claimed: an empty or smaller report never clears or narrows an existing exclusion (a recorded-but-unbound identity reports "
                             "exposed=false); the reports themselves list what they do not cover"),
            "observedEffect": sample["effect"], "observedNotCovered": sample["scope"]["notCovered"], "observedBasis": sample["basis"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="zoop-handoff-exposure-smoke-")).resolve()      # a symlinked parent (macOS /tmp -> /private/tmp) is refused by every pipeline ledger
    try:
        result = smoke(root / "owned")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    assert not root.exists()
    result["temporaryStateCleanup"] = {"removed": True, "root": str(root)}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
