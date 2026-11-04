#!/usr/bin/env python3
"""One authored S2/S3 world -> private Neo4j projection AND public app handoff -> explicit cross-store reconciliation (synthetic, local).

Run with the installed pipeline Python from the repository root:
  ai/pipeline/.venv/bin/python api/scripts/graph_handoff_reconciliation_smoke.py \
    --result /tmp/zoop-graph-reconciliation-result.json

Requires the existing API boot jar, JDK 21+, the installed pipeline (`zoop-ai-handoff`, `zoop-ai-ingest`, `zoop-ai-graph`), the cached project PostgreSQL
image and the cached digest-pinned `neo4j:5.26.32` image. Never builds, installs, pulls, borrows a database or calls a provider/model. Creates only an owned
Docker bridge, a tmpfs PostgreSQL, a tmpfs Neo4j on one loopback port, loopback JVMs and temporary synthetic ledgers, and removes exactly those.

The ONE authored world (ingestion + two S2 jobs + two S3 jobs, `graph_handoff_smoke.build_world`) is
  1. frozen as ONE handoff by the installed `zoop-ai-handoff` (producer manifest/bundle/content pins),
  2. frozen and projected by the installed `zoop-ai-graph` as one private Neo4j version per S3 job, with the SAME canonical.json the handoff uses,
  3. imported by the built jar into an empty PostgreSQL + artifact root (receipt/snapshot/evidence rows), activated through the real admin HTTP route
     with the default exclusion reader and read through the public graph, edge, event and evidence HTTP routes.
Neo4j is read twice: through the real driver (the stored nodes, relationships and their evidence ids) and through `zoop-ai-graph read` (evidence coordinates).

The comparator joins the stores through an explicit, hand-written domain mapping (source company ref -> canonical id -> master/public id -> app catalog row;
S2 source event -> canonical issue -> public issue id; the S3 relationCandidateId as the join key of a private relationship and a public relation, basis or
exclusion; evidence through its (documentVersion, start, end) coordinates, because the private `ev-`+32hex and the app `ev-`+64hex ids are different
namespaces). It never compares version ids or counts alone. Rejection, HOLD and exclusion are checked in both directions (nothing public the private graph
does not imply, nothing private that reaches a public body). Same-version re-project/re-import idempotence and current-rights revocation/restoration run
against the real stores.

Negative controls are separate and labelled: `productControl` writes a REAL second Neo4j version through the real CLI under a deliberately different operator
canonical mapping; `harnessTamper` mutates in-memory copies of what was observed (no store is touched). Both must be detected by the same comparator.
The result JSON is metadata only (ids, digests, counts, statuses): no article text, quote, title or credential.
"""
from __future__ import annotations

import base64
import collections
import copy
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

sys.dont_write_bytecode = True

import graph_handoff_activation_smoke as activation  # noqa: E402

handoff = activation.handoff
hs, base, check = handoff.hs, handoff.base, handoff.check
local = activation.local
from scripts import graph_projection_smoke as gp  # noqa: E402
from scripts import graph_tls_smoke as tls  # noqa: E402

SMOKE = "reconciliation"
HANDOFF_ID = "handoff-reconcile-1"
PUBLIC = handoff.PUBLIC_IDS                       # authored master id -> the app catalog id this smoke seeds
STATS: collections.Counter = collections.Counter()
DATABASE = "neo4j"
# The stored Neo4j relationship types (written out by hand) and the domain relation types they carry.
STORED_TYPES = {"ZG_SUPPLIES": "SUPPLIES", "ZG_INVESTS_IN": "INVESTS_IN", "ZG_COMPETES_WITH": "COMPETES_WITH", "ZG_PARTICIPATES_IN": "PARTICIPATES_IN",
                "ZG_RELATES_TO_TOPIC": "RELATES_TO_TOPIC"}
NEO4J_LABEL = "com.zoop.graph-reconciliation-neo4j"
CLAIMS = {
    "#53": "covered: every public evidence row the real import registered is reached over HTTP with its exact span and document version under current rights, "
           "from a private Neo4j evidence coordinate or from the operator's geography decision; the private-only spans are refused publicly",
    "#75": "NOT covered: no name -> company master -> SAME/NEW/HOLD decision is exercised; only the operator-authored company ref -> canonical id -> master id -> "
           "app catalog id mapping is proven (participants without a mapping stay null, never guessed). Entity linking of names stays open",
    "#76": "covered for the authored world: every projected Neo4j relationship is the canonical image of its S3 relation (type, direction, direct/structural meaning, "
           "evidence coordinates) and the S3 HOLD relation is absent from every store. Real-source relation quality is not covered",
    "#78": "covered locally: a real empty Neo4j version and a real staged+activated app version of the SAME S2/S3 pins, idempotent re-project/re-import. "
           "No AWS/Fargate/RBAC and no automatic Neo4j -> app publication path (the operator feeds the two stores separately)",
    "#149": "covered locally for one synthetic world: producer pins <-> Neo4j <-> app receipt/snapshot/evidence rows <-> public HTTP, with negative controls. "
            "Not real data, not a production scheduler, not volume",
}
NOT_PROVEN = [
    "name -> company master -> SAME/NEW/HOLD entity linking (#75)", "real-source rights, quality or volume", "production publication readiness",
    "exclusion command mutations", "an automatic Neo4j -> app publication path",
    "password login/OAuth/operator provisioning", "AWS/Fargate/Neo4j RBAC/TLS", "external AI/model path",
]


class Mismatch(AssertionError):
    """A reconciliation finding with a stable code (the negative controls assert the code)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def need(condition, code: str, detail: str = "") -> None:
    if not condition:
        raise Mismatch(code, detail)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def display_id(relation_type: str, source: str, target: str) -> str:
    """The public display-edge id by the documented rule (DisplayGraph.edgeId), written out by hand: `edge-` + first 16 hex of SHA-256("type|source|target")."""
    return "edge-" + sha256(f"{relation_type}|{source}|{target}".encode("utf-8"))[:16]


# ------------------------------------------------------------------------------------------------- the authored domain mapping --------------

def authored(world) -> SimpleNamespace:
    """Everything the comparator may assume, written out by hand from the authored world and operator files (never read back from a store under test)."""
    eva, evb, evb3 = world.evc["a"], world.evc["b"], world.evc["b3"]
    quotes = {"EVT_A": ("a", hs.EVT_A), "GEO_A": ("a", hs.GEO_A), "SUP": ("a", hs.SUP), "INV": ("a", hs.INV), "EVT_A2": ("a2", hs.EVT_A2),
              "QB": ("b", hs.QB), "GEO_B": ("b", hs.GEO_B), "QB3": ("b", hs.QB3)}
    spans = {label: hs.span(world, name, quote) for label, (name, quote) in quotes.items()}
    coords = {label: [s["documentVersion"], s["start"], s["end"]] for label, s in spans.items()}

    def rid(job, relation_type, subject, obj):
        return hs.relation_id(world, job, relation_type, subject, obj)

    def relation(job, relation_type, start, end, ev, fate):
        return dict(job=job, type=relation_type, start=start, end=end, ev=ev, fate=fate)

    relations = {   # S3 relationCandidateId -> authored meaning; `fate` = what the operator's decisions make of it publicly
        rid("rel-a", "PARTICIPATES_IN", "SYNTH-1", eva): relation("rel-a", "PARTICIPATES_IN", "co:synth-1", "issue:supply", ["EVT_A"], "involves"),
        rid("rel-a", "SUPPLIES", "SYNTH-3", "SYNTH-1"): relation("rel-a", "SUPPLIES", "co:synth-3", "co:synth-1", ["SUP"], "structural-basis"),
        rid("rel-a", "INVESTS_IN", "SYNTH-4", "SYNTH-3"): relation("rel-a", "INVESTS_IN", "co:synth-4", "co:synth-3", ["INV"], "private-type"),
        rid("rel-b", "PARTICIPATES_IN", "SYNTH-1", "event-a"): relation("rel-b", "PARTICIPATES_IN", "co:synth-1", "issue:supply", ["EVT_A2"], "involves"),
        rid("rel-b", "PARTICIPATES_IN", "SYNTH-1", evb): relation("rel-b", "PARTICIPATES_IN", "co:synth-1", "issue:factory", ["QB"], "involves"),
        rid("rel-b", "PARTICIPATES_IN", "SYNTH-2", evb): relation("rel-b", "PARTICIPATES_IN", "co:synth-2", "issue:factory", ["QB"], "excluded:company_unmapped"),
        rid("rel-b", "PARTICIPATES_IN", "SYNTH-1", evb3): relation("rel-b", "PARTICIPATES_IN", "co:synth-1", "issue:overseas", ["QB3"], "excluded:issue_not_public"),
    }
    hold = hs.find(world.jobs["rel-a"], "SHARES_ISSUE", "SYNTH-1", "SYNTH-2")["relationCandidateId"]
    upstream = {name: hs.upstream(world, name) for name in ("a", "b")}
    doc = {name: ref["documentId"] for name, ref in world.refs.items()}
    companies = {   # source company ref -> canonical id, master id, app catalog id, label: the label is what S2 wrote for it, never a guess
        "SYNTH-1": dict(canonical="co:synth-1", master="KRX:005930", app=PUBLIC["KRX:005930"], label=hs.ISSUER["name"]),
        "SYNTH-3": dict(canonical="co:synth-3", master="KRX:000660", app=PUBLIC["KRX:000660"], label=hs.SUPPLIER["name"]),
        "SYNTH-2": dict(canonical="co:synth-2", master=None, app=None, label=hs.PARTNER["name"]),
        "SYNTH-4": dict(canonical="co:synth-4", master=None, app=None, label=None),
    }
    issues = {
        "issue:supply": dict(public="issue:supply-2026q3", title="합성 공급 계약", evidence=["EVT_A", "EVT_A2", "GEO_A"], geography=["GEO_A"],
                             source_events={(upstream["a"]["jobId"], "event-candidate", eva, "m-a", doc["a"]), (upstream["b"]["jobId"], "snapshot-event", "event-a", "m-a", doc["a"]),
                                            (upstream["b"]["jobId"], "snapshot-event", "event-a", "m-a2", doc["a2"])}),
        "issue:factory": dict(public="issue:factory-2026q4", title="합성 공장 착공", evidence=["QB", "GEO_B"], geography=["GEO_B"],
                              source_events={(upstream["b"]["jobId"], "event-candidate", evb, "m-b", doc["b"])}),
        "issue:overseas": dict(public=None, title=None, evidence=[], geography=[], source_events=set()),
    }
    pub_company = {c["canonical"]: c for c in companies.values() if c["app"]}
    pub_issue = {k: v["public"] for k, v in issues.items() if v["public"]}
    c1, c3 = companies["SYNTH-1"]["app"], companies["SYNTH-3"]["app"]
    s_pub, f_pub = issues["issue:supply"]["public"], issues["issue:factory"]["public"]
    public_relations = {     # (type, public source, public target) -> authored evidence labels
        ("INVOLVES", s_pub, c1): ["EVT_A", "EVT_A2"], ("INVOLVES", f_pub, c1): ["QB"], ("STRUCTURALLY_RELATED_TO", s_pub, c3): ["EVT_A", "EVT_A2"],
        ("FOLLOWS", f_pub, s_pub): ["QB", "EVT_A"]}
    display = {display_id(*key): dict(type=key[0], source=key[1], target=key[2], derived=False, ev=value) for key, value in public_relations.items()}
    display[display_id("SHARES_ISSUE", c1, c3)] = dict(type="SHARES_ISSUE", source=c1, target=c3, derived=True, via=[s_pub], ev=[], via_ev=["EVT_A", "EVT_A2"])
    jobs = {job: {"relation": {"jobId": out["jobId"], "inputDigest": out["inputDigest"]}, "upstream": dict(out["binding"]["upstream"]),
                  "reviewDigest": hs.digest(hs.review_state(out))} for job, out in world.jobs.items()}
    participants = {"SYNTH-1": hs.ISSUER["name"], "SYNTH-3": hs.SUPPLIER["name"], "SYNTH-2": hs.PARTNER["name"], "SYNTH-9": hs.STRANGER["name"], None: hs.UNKNOWN["name"]}
    return SimpleNamespace(
        quotes=quotes, spans=spans, coords=coords, relations=relations, hold=hold, companies=companies, issues=issues, pub_company=pub_company, pub_issue=pub_issue,
        display=display, jobs=jobs, participants=participants, publics=SimpleNamespace(c1=c1, c3=c3, supply=s_pub, factory=f_pub),
        events={("a", "event-candidate", eva): "issue:supply", ("b", "snapshot-event", "event-a"): "issue:supply", ("b", "event-candidate", evb): "issue:factory",
                ("b", "event-candidate", evb3): "issue:overseas"},
        private_evidence_only=["INV", "QB3"], operator_evidence_only=["GEO_A", "GEO_B"], world=world)


# ------------------------------------------------------------------------------------------------- the private store ------------------------

def neo4j_observation(raw, version: str) -> dict:
    """What Neo4j ACTUALLY stores for one version, read through the driver: marker, nodes, relationships (with every evidence-bearing property) and 2-hop paths."""
    marker = raw.q("MATCH (m:ZgVersion {versionId: $v}) RETURN properties(m) AS p", v=version)
    need(len(marker) == 1, "neo4j_state", "marker")
    nodes = sorted([row["l"][0], row["p"]["id"]] for row in raw.q("MATCH (n) WHERE n.v = $v RETURN labels(n) AS l, properties(n) AS p", v=version))
    edges = sorted(({"type": STORED_TYPES[row["t"]], "start": row["start"], "end": row["end"], "props": {key: row["p"].get(key, [] if key in gp.LISTS else None) for key in gp.EDGE_KEYS}} for row in raw.edges_of(version)),
                   key=lambda e: e["props"]["id"])
    kinds = {e["type"] for e in edges}
    paths = [] if not {"SUPPLIES", "PARTICIPATES_IN"} <= kinds else raw.q("MATCH (s)-[a:ZG_SUPPLIES]->(c)-[p:ZG_PARTICIPATES_IN]->(e) WHERE a.v = $v AND p.v = $v AND s.v = $v "
                  "RETURN s.id AS supplier, c.id AS customer, e.id AS issue, a.sourceRelationCandidateIds AS basis, a.evidenceIds AS basisEvidence, "
                  "p.evidenceIds AS participationEvidence ORDER BY supplier, customer, issue", v=version)
    return {"marker": marker[0]["p"], "nodes": nodes, "edges": edges, "paths": paths}


class GraphOperator:
    """The installed `zoop_ai_pipeline.graph_projection_cli` (the `zoop-ai-graph` entry point) exactly as an operator runs it, under the graph smoke's socket audit
    hook (only the one owned Neo4j port): every command output is one JSON object with no credential."""

    def __init__(self, world, uri: str, database: str, run: str):
        self.world, self.uri, self.database, self.run = world, uri, database, run
        self.root, self.kit, self.jobs = world.root, world.kit, world.jobs
        self.port = urlsplit(uri).port
        self.canonical = self.root / "canonical.json"

    def vid(self, name: str) -> str:
        return f"{self.run}-{name}"

    def sel(self, name: str) -> dict:
        return {"schemaVersion": gp.SCHEMA, "versionId": self.vid(name)}

    def exec(self, command: str, request: dict, *, canonical: Path | None = None) -> tuple[int, dict | None, str]:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()), "LANG": "en_US.UTF-8", **hs.ownership_env(), **gp.CUSTOM,
               **{key: value for key, value in os.environ.items() if key.startswith("ZOOP_GRAPH_")}}
        program = gp.guard_source(self.port) + "runpy.run_module('zoop_ai_pipeline.graph_projection_cli', run_name='__main__')\n"
        argv = [sys.executable, "-c", program, command, "--state-dir", str(self.root / "graph")]
        if command in gp.SOURCED:
            argv += ["--relation-state-dir", str(self.root / "relation"), "--extraction-state-dir", str(self.root / "extraction"),
                     "--ingestion-state-dir", str(self.root / "ingestion"), "--sources", str(self.kit.registry_path), "--canonical", str(canonical or self.canonical)]
        if command == "init":
            argv += ["--graph-uri", self.uri]
        child = subprocess.run(argv, input=hs.json_bytes(request), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=handoff.PIPELINE, timeout=300)
        text = child.stdout.decode()
        STATS["zoop-ai-graph " + command] += 1
        gp.assert_no_credential_leak(text, self.database)
        return child.returncode, json.loads(text) if text else None, child.stderr.decode()

    def graph(self, command: str, request: dict, *, expected: int = 0, canonical: Path | None = None) -> dict:
        code, out, error = self.exec(command, request, canonical=canonical)
        check(code == expected and not error, f"zoop-ai-graph {command}: exit {code} (wanted {expected}) {json.dumps(out)[:300]} {error[-300:]}")
        return out

    def freeze(self, name: str, job: str, canonical: Path | None = None) -> dict:
        return self.graph("freeze", {**self.sel(name), "relation": {"jobId": job, "inputDigest": self.jobs[job]["inputDigest"]}}, canonical=canonical)

    def ledger(self) -> str:
        import sqlite3
        db = sqlite3.connect((self.root / "graph" / "graph.sqlite3").as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            return json.dumps([db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall() for table in ("meta", "versions", "attempts")], ensure_ascii=False)
        finally:
            db.close()


class OwnedNeo4j:
    """A private tmpfs Neo4j 5 Community on 127.0.0.1 from the digest-pinned, already cached image; removed by exact container name in `stop`."""

    def __init__(self, evidence: dict):
        self.evidence, self.name, self.port, self.password = evidence, "zoop-reconcile-neo4j-" + secrets.token_hex(6), None, secrets.token_urlsafe(24)

    def start(self) -> str:
        image = local.docker("image", "inspect", tls.IMAGE, "--format", "{{.Id}}")
        check(image.returncode == 0 and image.stdout.strip() == tls.IMAGE_DIGEST, "the digest-pinned neo4j image is not cached locally (this smoke never pulls)")
        self.evidence["neo4jImage"] = {"name": tls.IMAGE_TAG, "id": image.stdout.strip()}
        self.evidence["cleanup"]["neo4j"] = False
        self.evidence["resources"]["neo4j"] = {"container": self.name, "label": NEO4J_LABEL + "=1"}
        settings = {"NEO4J_dbms_usage__report_enabled": "false", "NEO4J_server_memory_heap_initial__size": "384m", "NEO4J_server_memory_heap_max__size": "512m",
                    "NEO4J_server_memory_pagecache_size": "128m"}
        args = ["run", "-d", "--pull", "never", "--name", self.name, "--label", NEO4J_LABEL + "=1", "--memory", "1536m", "-p", "127.0.0.1::7687",
                "--tmpfs", "/data", "--tmpfs", "/logs", "-e", "NEO4J_AUTH"]
        for key, value in settings.items():
            args += ["-e", f"{key}={value}"]
        started = local.docker(*args, tls.IMAGE, timeout=120, env={**os.environ, "NEO4J_AUTH": f"neo4j/{self.password}"})
        check(started.returncode == 0, "owned Neo4j container creation failed")
        mapping = local.docker("port", self.name, "7687/tcp").stdout.strip().splitlines()[0]
        host, _, port = mapping.rpartition(":")
        check(host == "127.0.0.1" and port.isdigit(), "Bolt must be published on one loopback port")
        self.port = int(port)
        os.environ.update({"ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": "neo4j", "ZOOP_GRAPH_PASSWORD": self.password})
        uri = f"bolt://127.0.0.1:{self.port}"
        deadline, nodes = time.monotonic() + 240, None
        while time.monotonic() < deadline and nodes is None:
            check(local.docker("inspect", self.name, "--format", "{{.State.Status}}").stdout.strip() == "running", "the Neo4j container stopped")
            try:
                probe = gp.Raw(uri, DATABASE)
                try:
                    nodes = probe.count("MATCH (n) RETURN count(n) AS c")
                finally:
                    probe.close()
            except Exception:  # noqa: BLE001 - not ready yet; the deadline decides
                time.sleep(2)
        check(nodes == 0, "the owned Neo4j database is not ready and empty")
        return uri

    def stop(self) -> None:
        if "neo4j" not in self.evidence["resources"]:
            return
        local.docker("rm", "-f", "-v", self.name, timeout=60)
        self.evidence["cleanup"]["neo4j"] = local.docker("container", "inspect", self.name).returncode != 0


# ------------------------------------------------------------------------------------------------- the comparator ---------------------------

def canonical_index(document: dict) -> dict:
    return {(e["upstream"]["jobId"], e["upstream"]["inputDigest"], e["kind"], e["ref"]): e["canonicalId"] for e in document["entries"]}


def coords_of(record) -> tuple:
    return (record["documentVersion"], record["start"], record["end"])


def app_ids_by_coords(obs: dict) -> dict:
    return {(row["article_version"], row["start_offset"], row["end_offset"]): row["id"] for row in obs["app"]["pg"]["evidence"]}


def app_id(by_coords: dict, coords: tuple) -> str:
    need(coords in by_coords, "evidence_mapping", "a private evidence coordinate that a public relation needs has no registered app evidence row")
    return by_coords[coords]


def s3_relations(dom, job: str) -> dict:
    return {r["relationCandidateId"]: r for r in dom.world.jobs[job]["relations"]}


def check_pins(obs: dict, dom) -> dict:
    pins, app = obs["pins"], obs["app"]
    manifest, bundle, receipt, result = pins["manifest"], pins["bundle"], app["receipt"], pins["importResult"]
    need(hs.digest(manifest) == pins["export"]["manifestDigest"] == bundle["manifestDigest"] == hs.digest(receipt["manifest"]) == result["digests"]["manifest"],
         "pin_mismatch", "manifest digest differs between producer, bundle, app receipt and import result")
    need(sha256(hs.canonical(bundle).encode()) == pins["export"]["bundleDigest"] == sha256(hs.canonical(receipt["bundle"]).encode()) == result["digests"]["bundle"],
         "pin_mismatch", "bundle digest differs between producer, app receipt and import result")
    need(pins["export"]["contentDigest"] == result["digests"]["content"] == receipt["contentDigest"], "pin_mismatch", "content digest")
    need(receipt["manifest"] == manifest and receipt["bundle"] == bundle, "pin_mismatch", "the app receipt is not the producer's manifest and bundle")
    need(manifest["files"]["canonical"] == pins["canonicalSha256Before"] == pins["canonicalSha256After"], "pin_mismatch", "canonical.json changed between handoff and graph runs")
    need(app["snapshot"]["sourceBundleId"] == manifest["handoffId"] and app["pg"]["graphVersion"]["source_label"] == "graph-handoff:" + manifest["handoffId"],
         "pin_mismatch", "the app version is not this handoff")
    need(len(app["pg"]["artifacts"]) == 2 and all(a["sha256"] == app["files"][a["id"]] for a in app["pg"]["artifacts"]), "pin_mismatch", "artifact registry hash differs from the retained file")
    counts = bundle["counts"]
    cardinalities = (counts["companies"], counts["issues"], sum(counts["relations"].values()), counts["articles"], counts["evidence"])
    need(result["counts"] == dict(zip(("companies", "issues", "relations", "articles", "evidence"), cardinalities)), "pin_mismatch", "import result counts differ from the bundle")
    need(tuple(len(app["snapshot"][key]) for key in ("companies", "issues", "relations", "articles", "evidence")) == cardinalities, "pin_mismatch",
         "snapshot cardinalities differ from the bundle")
    index = canonical_index(obs["canonicalDoc"])
    for job, want in dom.jobs.items():
        for place, source in (("manifest", next((s for s in manifest["sources"] if s["relation"]["jobId"] == job), None)),
                              ("bundle", next((s for s in bundle["sources"] if s["relation"]["jobId"] == job), None)),
                              ("app-receipt-bundle", next((s for s in receipt["bundle"]["sources"] if s["relation"]["jobId"] == job), None)),
                              ("app-receipt-manifest", next((s for s in receipt["manifest"]["sources"] if s["relation"]["jobId"] == job), None)),
                              ("graph", obs["graph"][job]["inspect"]["source"])):
            need(source is not None and source["relation"] == want["relation"] and source["upstream"] == want["upstream"] and source["reviewDigest"] == want["reviewDigest"],
                 "pin_mismatch", f"{place} pin of {job} is not the S3/S2 job's own")
        graph = obs["graph"][job]
        bundle_source = next(s for s in bundle["sources"] if s["relation"]["jobId"] == job)
        need(graph["inspect"]["audit"]["eligibility"] == bundle_source["audit"]["eligibility"] and graph["inspect"]["audit"]["s3Relations"] == bundle_source["audit"]["s3Relations"],
             "pin_mismatch", f"{job}: the private and the public audit count different S3 relations")
        marker = graph["neo4j"]["marker"]
        need(marker["payloadDigest"] == graph["inspect"]["digests"]["payload"] and marker["graphDigest"] == graph["inspect"]["digests"]["graph"]
             and marker["nodeCount"] == len(graph["neo4j"]["nodes"]) and marker["edgeCount"] == len(graph["neo4j"]["edges"]),
             "pin_mismatch", f"{job}: the stored Neo4j version is not the frozen ledger plan")
        need(graph["read"]["delivery"]["status"] == "current" and graph["read"]["verification"]["marker"] == "matched", "pin_mismatch", f"{job}: graph read is not current")
        endpoints = {(e["kind"], e["ref"]) for r in dom.world.jobs[job]["relations"] if r["eligibility"]["status"] == "eligible" and not r["eligibility"]["reviewPending"]
                     for e in (r["subject"], r["object"])}
        need(graph["inspect"]["canonical"]["entries"] == len(endpoints) and all((want["upstream"]["jobId"], want["upstream"]["inputDigest"], k, r) in index for k, r in endpoints),
             "pin_mismatch", f"{job}: the graph version does not pin exactly the canonical decisions its endpoints need")
    return {"s3Jobs": len(dom.jobs), "pinPlaces": 5, "digestsAgreeingAcrossProducerAppAndImport": 3, "canonicalJsonSharedByBothStores": True}


def check_companies(obs: dict, dom) -> dict:
    bundle, snapshot, pg = obs["pins"]["bundle"], obs["app"]["snapshot"], obs["app"]["pg"]
    index = canonical_index(obs["canonicalDoc"])
    upstreams = {dom.world.s2[name]["jobId"]: dom.world.s2[name]["inputDigest"] for name in ("a", "b")}
    entries = 0
    for (job_id, digest, kind, ref), canonical_id in index.items():
        need(upstreams.get(job_id) == digest, "company_mapping", "canonical.json holds an entry of an unknown S2 upstream")
        if kind == "company":
            need(ref in dom.companies and dom.companies[ref]["canonical"] == canonical_id, "company_mapping", f"{ref} -> {canonical_id} is not the authored canonical id")
            entries += 1
    need(entries > 0, "company_mapping", "canonical.json holds no company entry")
    for job in dom.jobs:
        mine = [r for r in dom.relations.values() if r["job"] == job]
        want = sorted([["ZgCompany", c] for c in {x for r in mine for x in (r["start"], r["end"]) if x.startswith("co:")}]
                      + [["ZgEvent", e] for e in {r["end"] for r in mine if r["end"].startswith("issue:")}])
        need(obs["graph"][job]["neo4j"]["nodes"] == want, "company_mapping", f"{job}: the stored Neo4j nodes are not the canonical image of the projected relations")
    need(sorted((c["canonicalId"], c["id"], c["label"]) for c in bundle["companies"]) == sorted((c["canonical"], c["app"], c["label"]) for c in dom.pub_company.values()),
         "company_mapping", "the bundle's companies differ from the authored canonical -> master -> app mapping")
    need(sorted(c["companyId"] for c in snapshot["companies"]) == sorted(c["app"] for c in dom.pub_company.values()), "company_mapping", "snapshot companies")
    decided = {c["canonicalId"]: (c["publicId"], c["label"], c["decisionRef"]) for c in obs["decisions"]["companies"]}
    need(decided == {c["canonical"]: (c["app"], c["label"], hs.CATALOG[c["canonical"]][2]) for c in dom.pub_company.values()}, "company_mapping",
         "the operator's catalog decisions (publicId <-> canonical master identifier) differ from the authored mapping")
    catalog = {row["id"]: row["name"] for row in pg["companies"]}
    for company in dom.pub_company.values():
        need(catalog.get(company["app"]) == company["label"], "company_mapping", f"app catalog row {company['app']} is missing or carries another label")
    http_companies = {n["id"]: n["label"] for n in obs["http"]["graph"]["nodes"] if n["kind"] == "company"}
    need(http_companies == {c["app"]: c["label"] for c in dom.pub_company.values()}, "company_mapping", "public graph company nodes")
    participants = mapped = 0
    for issue in bundle["issues"]:
        for mention in issue["mentions"]:
            for person in mention["participants"]:
                source = person["sourceCompanyId"]
                need(source in dom.participants and person["name"] == dom.participants[source], "company_mapping", f"participant {source}: its name is not what S2 wrote")
                expected = dom.companies[source]["app"] if source in dom.companies else None
                need(person["companyId"] == expected, "company_mapping", f"participant {source} -> {person['companyId']} (authored {expected})")
                participants += 1
                mapped += expected is not None
    public_participants = 0
    for body in obs["http"]["events"].values():
        for mention in (body or {}).get("mentions", []):
            for person in mention["participants"]:
                known = [s for s, name in dom.participants.items() if name == person["name"]]
                need(len(known) == 1, "company_mapping", "a public participant name is not an S2 name")
                need(person["companyId"] == (dom.companies[known[0]]["app"] if known[0] in dom.companies else None), "company_mapping",
                     f"public participant {known[0]} -> {person['companyId']}")
                public_participants += 1
    return {"sourceCompanyRefs": len(dom.companies), "publicByMaster": len(dom.pub_company), "privateOnly": len(dom.companies) - len(dom.pub_company),
            "receiptParticipantsChecked": participants, "receiptParticipantsMapped": mapped, "participantsNullByContract": participants - mapped, "publicParticipantsChecked": public_participants}


def check_issues(obs: dict, dom) -> dict:
    bundle, snapshot = obs["pins"]["bundle"], obs["app"]["snapshot"]
    index = canonical_index(obs["canonicalDoc"])
    s2 = {dom.world.s2[name]["jobId"]: dom.world.s2[name]["inputDigest"] for name in ("a", "b")}
    for (name, kind, ref), canonical_id in dom.events.items():
        need(index.get((dom.world.s2[name]["jobId"], dom.world.s2[name]["inputDigest"], "event", ref)) == canonical_id, "issue_grouping",
             f"canonical.json: ({name},{ref}) is not {canonical_id}")
    public = {i["canonicalId"]: i for i in bundle["issues"]}
    need(sorted(public) == sorted(k for k, v in dom.issues.items() if v["public"]), "issue_grouping", "the bundle's issues")
    need(sorted(i["issueId"] for i in snapshot["issues"]) == sorted(dom.pub_issue.values()), "issue_grouping", "the snapshot's issues")
    for canonical_id, issue in public.items():
        authored_issue = dom.issues[canonical_id]
        need(issue["id"] == authored_issue["public"] and issue["title"] == authored_issue["title"], "issue_grouping", f"{canonical_id}: public id/title")
        events = {(e["upstream"]["jobId"], e["kind"], e["ref"], e["mentionId"], e["documentId"]) for e in issue["sourceEvents"]}
        need(events == authored_issue["source_events"], "issue_grouping", f"{canonical_id}: the source events differ from the authored grouping")
        for upstream_job, _, ref, _, _ in events:
            need(index.get((upstream_job, s2[upstream_job], "event", ref)) == canonical_id, "issue_grouping", f"{canonical_id}: canonical.json maps a source event elsewhere")
    by_coords = app_ids_by_coords(obs)
    private_evidence = collections.defaultdict(set)
    nodes = set()
    for job in dom.jobs:
        g = obs["graph"][job]
        coord_of = {e["evidenceId"]: coords_of(e) for e in g["read"]["evidence"]}
        nodes |= {n[1] for n in g["neo4j"]["nodes"]}
        for edge in g["neo4j"]["edges"]:
            if edge["type"] == "PARTICIPATES_IN":
                private_evidence[edge["end"]] |= {coord_of[i] for i in edge["props"]["evidenceIds"]}
    for canonical_id, authored_issue in dom.issues.items():
        need(canonical_id in nodes, "issue_grouping", f"{canonical_id} is not a stored Neo4j event")
        if not authored_issue["public"]:
            continue
        snapshot_issue = next(i for i in snapshot["issues"] if i["issueId"] == authored_issue["public"])
        public_coords = {c for c, i in by_coords.items() if i in snapshot_issue["evidenceIds"]}
        implied = private_evidence[canonical_id]
        need(implied <= public_coords, "issue_grouping", f"{canonical_id}: private participation evidence is not public evidence of the issue")
        need(public_coords - implied == {tuple(dom.coords[label]) for label in authored_issue["geography"]}, "issue_grouping",
             f"{canonical_id}: the public evidence beyond the private graph is not exactly the operator's geography evidence "
             f"(public {sorted((c[1], c[2]) for c in public_coords)}, private {sorted((c[1], c[2]) for c in implied)})")
        need(len(public_coords) == len(snapshot_issue["evidenceIds"]), "issue_grouping", f"{canonical_id}: an issue evidence id has no app evidence row")
    excluded = {(i["code"], i["id"]) for i in bundle["exclusions"]["items"] if i["kind"] == "issue"}
    need(excluded == {("geography_countries_disagree", "issue:overseas")}, "issue_grouping", "the private-only issue is not the producer's visible exclusion")
    return {"canonicalIssues": len(dom.issues), "public": len(public), "privateOnly": len(dom.issues) - len(public),
            "sourceEvents": sum(len(v["source_events"]) for v in dom.issues.values()), "eventRefsMappedByCanonicalJson": len(dom.events)}


def check_relations(obs: dict, dom) -> dict:
    bundle, snapshot, decisions = obs["pins"]["bundle"], obs["app"]["snapshot"], obs["decisions"]
    index = canonical_index(obs["canonicalDoc"])
    by_coords = app_ids_by_coords(obs)
    stored: dict[str, tuple] = {}
    coord_of = {}
    for job in dom.jobs:
        g = obs["graph"][job]
        coord_of[job] = {e["evidenceId"]: coords_of(e) for e in g["read"]["evidence"]}
        s3, upstream = s3_relations(dom, job), dom.jobs[job]["upstream"]
        view = {e["relationId"]: e for e in g["read"]["graph"]["edges"]}
        need(sorted(view) == sorted(e["props"]["id"] for e in g["neo4j"]["edges"]), "relation_mapping", f"{job}: zoop-ai-graph read and the stored relationships differ")
        for edge in g["neo4j"]["edges"]:
            rcs = edge["props"]["sourceRelationCandidateIds"]
            need(rcs and view[edge["props"]["id"]]["sourceRelationCandidateIds"] == rcs, "relation_mapping", f"{job}: a stored relationship has no (or another) S3 source")
            union = set()
            for rc in rcs:
                need(rc in s3 and rc not in stored, "relation_mapping", f"{job}: S3 candidate {rc[:12]} is unknown or projected twice")
                relation = s3[rc]
                need(relation["eligibility"]["status"] == "eligible" and not relation["eligibility"]["reviewPending"], "hold_leak", f"{job}: a non-eligible S3 relation is in Neo4j")
                subject = index[(upstream["jobId"], upstream["inputDigest"], relation["subject"]["kind"], relation["subject"]["ref"])]
                obj = index[(upstream["jobId"], upstream["inputDigest"], relation["object"]["kind"], relation["object"]["ref"])]
                need((relation["type"], subject, obj) == (edge["type"], edge["start"], edge["end"]), "relation_mapping",
                     f"{job}: the stored relationship is not the canonical image of S3 {rc[:12]} (type, direction or endpoints)")
                authored_relation = dom.relations.get(rc)
                need(authored_relation is not None and (authored_relation["job"], authored_relation["type"], authored_relation["start"], authored_relation["end"])
                     == (job, edge["type"], edge["start"], edge["end"]), "relation_mapping", f"{job}: the stored relationship differs from the authored expectation")
                need(edge["props"]["direction"] == "directed" and edge["props"]["connection"] == relation["connection"] == "direct", "relation_mapping", "direction/connection")
                union |= {c["evidenceId"] for c in relation["citations"]}
                need(sorted(coord_of[job][i] for i in {c["evidenceId"] for c in relation["citations"]}) == sorted(tuple(dom.coords[l]) for l in authored_relation["ev"]),
                     "evidence_mapping", f"{job}: the private evidence of {authored_relation['type']} does not resolve to the authored document/span coordinates")
                stored[rc] = (job, edge)
            need(sorted(edge["props"]["evidenceIds"]) == sorted(union), "evidence_mapping", f"{job}: the stored evidence ids differ from the S3 citations")
    need(sorted(stored) == sorted(dom.relations), "relation_mapping", "the projected S3 candidates are not exactly the authored eligible ones")
    hold = next(r for r in dom.world.jobs["rel-a"]["relations"] if r["relationCandidateId"] == dom.hold)
    need(hold["eligibility"]["status"] == "hold" and dom.hold not in stored, "hold_leak", "the S3 HOLD relation is in Neo4j")
    need(dom.hold not in json.dumps(bundle) and dom.hold not in json.dumps(snapshot), "hold_leak", "the S3 HOLD relation reaches the public bundle/snapshot")
    need(all(obs["graph"][job]["inspect"]["audit"]["eligibility"]["hold"] == (1 if job == "rel-a" else 0) for job in dom.jobs), "hold_leak", "private HOLD audit")
    # the public side: which S3 candidates did the producer use, which did it visibly exclude, and does each partition cell match its authored fate?
    used = {}
    for relation in bundle["relations"]:
        for ref in relation["sourceRefs"]:
            if ref["kind"] == "s3-relation":
                used[ref["id"]] = (ref["jobId"], relation["type"], relation["source"], relation["target"])
        for item in relation["basis"]:
            used[item["sourceRelation"]["relationCandidateId"]] = (item["sourceRelation"]["jobId"], "basis:" + item["relationType"], relation["source"], relation["target"])
    excluded = {i["id"]: i["code"] for i in bundle["exclusions"]["items"] if i["kind"] == "relation"}
    fates = collections.Counter()
    for rc, authored_relation in dom.relations.items():
        job, edge = stored[rc]
        fate = authored_relation["fate"]
        if fate == "involves":
            need(rc in used and used[rc][:2] == (job, "INVOLVES") and rc not in excluded, "relation_mapping", f"{fate}: {rc[:12]} is not a public INVOLVES")
            need(used[rc][2] == dom.pub_issue[edge["end"]] and used[rc][3] == dom.pub_company[edge["start"]]["app"], "relation_mapping", "INVOLVES endpoints are not the mapped image")
        elif fate == "structural-basis":
            need(rc in used and used[rc][:2] == (job, "basis:SUPPLIES") and rc not in excluded, "relation_mapping", f"{fate}: {rc[:12]} is not a public structural basis")
            need(used[rc][3] == dom.pub_company[edge["start"]]["app"] and used[rc][2] == dom.publics.supply, "relation_mapping", "the structural target is not the supplier's public id")
        elif fate.startswith("excluded:"):
            need(rc not in used and excluded.get(rc) == fate.split(":", 1)[1], "relation_mapping", f"{fate}: {rc[:12]} is not the producer's visible exclusion")
        else:
            need(rc not in used and rc not in excluded, "relation_mapping", f"{fate}: {rc[:12]} reached the public bundle")
            need(sum(s["audit"]["eligibleNotPublicByType"].get(authored_relation["type"], 0) for s in bundle["sources"]) >= 1, "relation_mapping", "the producer audit omits the type")
        fates[fate] += 1
    need(sorted(used) == sorted(rc for rc, r in dom.relations.items() if r["fate"] in ("involves", "structural-basis")), "relation_mapping",
         "the public relations use S3 candidates the private graph does not hold")
    reviewed = {u["relationCandidateId"]: u for s in bundle["sources"] for u in s["reviewUsed"]}
    need(sorted(reviewed) == sorted(used), "relation_mapping", "reviewUsed is not exactly the used S3 candidates")
    for rc, item in reviewed.items():
        job, edge = stored[rc]
        private = {a["relationCandidateId"]: a["kind"] for a in next(v for v in obs["graph"][job]["read"]["graph"]["edges"] if v["relationId"] == edge["props"]["id"])["sourceApprovals"]}
        need(private[rc] == item["approvalBasis"]["kind"] == "automatic-verifier", "relation_mapping", "the approval basis differs between the private and the public store")
        revision = next(r for r in dom.world.jobs[job]["relations"] if r["relationCandidateId"] == rc)["eligibility"]["revision"]
        need(item["revision"] == revision, "relation_mapping", "the sourceRevision of a used relation is not the S3 review revision")
    # what the private graph implies publicly (INVOLVES from stored participations, STRUCTURAL from a stored supplier -> customer -> issue path the operator attested)
    expected: dict = {}
    for rc, (job, edge) in stored.items():
        if edge["type"] == "PARTICIPATES_IN" and edge["start"] in dom.pub_company and edge["end"] in dom.pub_issue:
            key = ("INVOLVES", dom.pub_issue[edge["end"]], dom.pub_company[edge["start"]]["app"])
            expected.setdefault(key, set()).update(app_id(by_coords, coord_of[job][i]) for i in edge["props"]["evidenceIds"])
    paths = [dict(p, job=job) for job in dom.jobs for p in obs["graph"][job]["neo4j"]["paths"]]
    need(len(bundle["relations"]) and len(decisions["structural"]) == 1, "relation_mapping", "the operator's structural decisions")
    decision = decisions["structural"][0]
    path = [p for p in paths if set(p["basis"]) == {b["relationCandidateId"] for b in decision["basis"]}]
    need(len(path) == 1 and path[0]["supplier"] == decision["company"] and path[0]["issue"] == decision["issue"], "relation_mapping",
         "no private supplier -> participant -> issue path backs the operator's structural decision")
    path = path[0]
    expected[("STRUCTURALLY_RELATED_TO", dom.pub_issue[path["issue"]], dom.pub_company[path["supplier"]]["app"])] = {
        app_id(by_coords, coord_of[job][i]) for rc, (job, edge) in stored.items() if edge["type"] == "PARTICIPATES_IN" and edge["start"] == path["customer"] and edge["end"] == path["issue"]
        for i in edge["props"]["evidenceIds"]}
    structural = next(r for r in bundle["relations"] if r["type"] == "STRUCTURALLY_RELATED_TO")
    need(structural["structuralPath"]["links"] == [{"supplierCompanyId": dom.pub_company[path["supplier"]]["app"], "customerCompanyId": dom.pub_company[path["customer"]]["app"]}],
         "relation_mapping", "the public structural path direction is not the private supplier -> customer one")
    need(sorted(structural["basis"][0]["evidenceIds"]) == sorted(app_id(by_coords, coord_of[path["job"]][i]) for i in path["basisEvidence"]), "evidence_mapping",
         "the public structural basis evidence is not the private SUPPLIES evidence")
    follows = decisions["follows"][0]
    s2b = dom.world.s2["b"]
    comparison = next(c for cand in s2b["eventCandidates"] if cand["eventCandidateId"] == follows["source"]["eventCandidateId"]
                      for c in cand["comparisons"] if c["targetEventId"] == follows["source"]["targetEventId"])
    need(comparison["effective"]["relation"] == "FOLLOWS" and index[(s2b["jobId"], s2b["inputDigest"], "event", follows["source"]["eventCandidateId"])] == follows["from"]
         and index[(s2b["jobId"], s2b["inputDigest"], "event", follows["source"]["targetEventId"])] == follows["to"], "relation_mapping",
         "the FOLLOWS decision is not the S2 comparison mapped through canonical.json")
    expected[("FOLLOWS", dom.pub_issue[follows["from"]], dom.pub_issue[follows["to"]])] = {app_id(by_coords, coords_of(c)) for c in comparison["citations"]}
    actual: dict = {}
    for relation in snapshot["relations"]:
        actual.setdefault((relation["relationType"], relation["source"], relation["target"]), set()).update(relation["evidenceIds"])
    need(actual == expected, "relation_mapping", "the public snapshot relations differ from the private image under the mapping")
    need({(r["type"], r["source"], r["target"]): r["id"] for r in bundle["relations"]} == {(r["relationType"], r["source"], r["target"]): r["relationId"] for r in snapshot["relations"]},
         "relation_mapping", "the bundle and snapshot relation ids differ")
    return {"s3EligibleProjectedToNeo4j": len(stored), "partition": dict(fates), "s3HoldAbsentEverywhere": 1, "approvalsMatched": len(reviewed),
            "privateRelationships": sum(len(obs["graph"][j]["neo4j"]["edges"]) for j in dom.jobs), "publicRelations": len(snapshot["relations"]),
            "publicRelationsImpliedByPrivateGraph": len(expected), "structuralPathsMatched": 1, "followsFromS2Comparison": 1}


def check_evidence(obs: dict, dom) -> dict:
    by_coords = app_ids_by_coords(obs)
    pg_rows = {row["id"]: row for row in obs["app"]["pg"]["evidence"]}
    need(set(by_coords) == {tuple(dom.coords[label]) for label in ("EVT_A", "GEO_A", "SUP", "EVT_A2", "QB", "GEO_B")}, "evidence_mapping",
         "the registered app evidence rows are not exactly the authored public spans")
    private = {}
    labels = {tuple(coords): label for label, coords in dom.coords.items()}
    for job in dom.jobs:
        for record in obs["graph"][job]["read"]["evidence"]:
            need(coords_of(record) in labels, "evidence_mapping", "private evidence coordinate")
            label = labels[coords_of(record)]
            need(record["documentId"] == dom.spans[label]["documentId"], "evidence_mapping", "private evidence document identity")
            private[record["evidenceId"]] = coords_of(record)
    need(set(private.values()) == {tuple(dom.coords[label]) for label in ("EVT_A", "SUP", "INV", "EVT_A2", "QB", "QB3")}, "evidence_mapping", "private evidence coordinates")
    need(set(pg_rows).isdisjoint(private) and not {len(i) for i in pg_rows} & {len(i) for i in private}, "evidence_mapping", "the two stores share an evidence id namespace")
    mapped = {i: by_coords[c] for i, c in private.items() if c in by_coords}
    private_only = [i for i, c in private.items() if c not in by_coords]
    need(sorted(private[i] for i in private_only) == sorted(tuple(dom.coords[l]) for l in dom.private_evidence_only), "evidence_mapping", "the private-only evidence")
    need(sorted(set(by_coords.values()) - set(mapped.values())) == sorted(by_coords[tuple(dom.coords[l])] for l in dom.operator_evidence_only), "evidence_mapping",
         "the operator-only evidence")
    http = obs["http"]
    by_label = {tuple(v): k for k, v in dom.coords.items()}
    snapshot_issues = obs["app"]["snapshot"]["issues"]
    served = 0
    for evidence_id, row in pg_rows.items():
        label = by_label[(row["article_version"], row["start_offset"], row["end_offset"])]
        span = dom.spans[label]
        response = http["evidence"].get(evidence_id)
        need(response is not None and response["status"] == 200, "evidence_mapping", f"public evidence {label} does not resolve")
        body = response["body"]
        need(body["quote"] == dom.quotes[label][1] and (body["start"], body["end"]) == (span["start"], span["end"]) and body["articleId"] == span["documentId"]
             and body["articleVersion"] == span["documentVersion"] and body["quoteVerified"] is True and body["id"] == evidence_id
             and row["quote"] == dom.quotes[label][1] and row["article_id"] == span["documentId"] and row["offset_unit"] == "unicode_code_point" and row["quote_verified"] is True,
             "evidence_mapping", f"public evidence {label}: exact span or document version")
        citing = sorted(i["issueId"] for i in snapshot_issues if evidence_id in i["evidenceIds"] or evidence_id in i["geographyEvidenceIds"])
        basis_only = evidence_id in {i for r in obs["pins"]["bundle"]["relations"] for b in r["basis"] for i in b["evidenceIds"]}
        need(sorted(body["eventIds"]) == citing and (citing or basis_only), "evidence_mapping", f"public evidence {label}: cited by other issues than the snapshot's (a basis-only span has none)")
        need(body["metadata"]["graphVersion"] == obs["app"]["pg"]["graphVersion"]["id"], "evidence_mapping", "the evidence read is not pinned to the imported version")
        served += 1
    for label in dom.private_evidence_only:
        need(http["unregistered"][label]["status"] == 404, "evidence_mapping", f"the private-only span {label} is served publicly")
    return {"privateEvidenceCoordinates": len(private), "appEvidenceRows": len(pg_rows), "mappedByCoordinates": len(set(mapped.values())), "privateOnly": len(private_only),
            "operatorGeographyOnly": len(dom.operator_evidence_only), "publicServedWithExactSpan": served, "privateOnlyRefusedPublicly": len(dom.private_evidence_only)}


def check_public(obs: dict, dom) -> dict:
    http, snapshot, by_coords = obs["http"], obs["app"]["snapshot"], app_ids_by_coords(obs)
    version = obs["app"]["pg"]["graphVersion"]["id"]
    graph = http["graph"]
    need(graph["metadata"]["graphVersion"] == version, "public_display", "the graph is not the imported version")
    need({n["id"]: n["kind"] for n in graph["nodes"]} == {**{c["app"]: "company" for c in dom.pub_company.values()}, **{i: "issue" for i in dom.pub_issue.values()}},
         "public_display", "public graph nodes")
    need(sorted(e["id"] for e in graph["edges"]) == sorted(dom.display), "public_display", "the public display edge ids are not the hand-computed (type,source,target) ids")
    groups = collections.defaultdict(list)
    for relation in snapshot["relations"]:
        groups[(relation["relationType"], relation["source"], relation["target"])].append(relation["relationId"])
    for edge in graph["edges"]:
        want = dom.display[edge["id"]]
        need((edge["relationType"], edge["source"], edge["target"], edge["derived"]) == (want["type"], want["source"], want["target"], want["derived"]), "public_display",
             f"edge {want['type']}: endpoints or derived flag")
        need(sorted(edge["evidenceIds"]) == sorted(app_id(by_coords, tuple(dom.coords[l])) for l in want["ev"]), "public_display", f"edge {want['type']}: evidence")
        detail = http["edges"][edge["id"]]
        need(detail["id"] == edge["id"] and detail["derived"] == want["derived"] and detail["metadata"]["graphVersion"] == version, "public_display", "edge detail identity")
        if want["derived"]:
            need(edge["via"] == want["via"] and detail["relationIds"] == [] and [v["id"] for v in detail["via"]] == want["via"]
                 and detail["verification"]["status"] == "not_applicable", "public_display", "derived SHARES_ISSUE: via issue, no stored relation, not a verification")
            need(sorted(detail["via"][0]["evidenceIds"]) == sorted(app_id(by_coords, tuple(dom.coords[l])) for l in want["via_ev"]), "public_display", "derived via evidence")
        else:
            need(sorted(detail["relationIds"]) == sorted(groups[(want["type"], want["source"], want["target"])]) and sorted(detail["evidenceIds"]) == sorted(edge["evidenceIds"])
                 and detail["verification"]["status"] == "ALLOW", "public_display", f"edge {want['type']}: relation ids / verification")
    for canonical_id, authored_issue in dom.issues.items():
        body = http["events"][canonical_id]
        if not authored_issue["public"]:
            need(body is None, "public_display", "the private-only issue is publicly readable")
            continue
        need(body["id"] == authored_issue["public"] and body["metadata"]["graphVersion"] == version, "public_display", "event identity")
        need(sorted(body["evidenceIds"]) == sorted(app_id(by_coords, tuple(dom.coords[l])) for l in authored_issue["evidence"]), "public_display", "event evidence")
        mine = {i for i, w in dom.display.items() if not w["derived"] and authored_issue["public"] in (w["source"], w["target"])}
        shown = set()
        for relation in body["relations"]:
            need(relation["edgeId"] == display_id(relation["relationType"], relation["source"], relation["target"]) and relation["edgeId"] in dom.display
                 and relation["id"] in groups[(relation["relationType"], relation["source"], relation["target"])], "public_display", "event relation -> display edge mapping")
            shown.add(relation["edgeId"])
        need(shown <= mine and {i for i in mine if dom.display[i]["type"] != "FOLLOWS"} <= shown, "public_display", f"{canonical_id}: the event's relations are not its display edges")
    table = {}
    for relation in obs["pins"]["bundle"]["relations"]:
        did = display_id(relation["type"], relation["source"], relation["target"])
        need(did in http["edges"] and relation["id"] in http["edges"][did]["relationIds"], "public_display",
             "a bundle relation is not behind the display edge its (type, source, target) identity names")
        for ref in relation["sourceRefs"]:
            table[f"{ref['jobId']}:{ref['id']}"] = did
        for item in relation["basis"]:
            table[f"{item['sourceRelation']['jobId']}:{item['sourceRelation']['relationCandidateId']}"] = did
    need(len(table) == 5, "public_display", "the S3 -> display edge table is incomplete")
    return {"sourceRelationToDisplayEdge": table, "displayEdges": len(graph["edges"]), "storedRelationGroups": len(groups), "derived": sum(1 for e in graph["edges"] if e["derived"]),
            "eventsRead": sum(1 for b in http["events"].values() if b), "privateOnlyEventRefused": sum(1 for b in http["events"].values() if b is None)}


def check_leaks(obs: dict, dom) -> dict:
    http = obs["http"]
    public_text = json.dumps([http["graph"], list(http["edges"].values()), list(http["events"].values()), [e["body"] for e in http["evidence"].values()], obs["app"]["snapshot"]], ensure_ascii=False)
    private_ids = {e["evidenceId"] for j in dom.jobs for e in obs["graph"][j]["read"]["evidence"]} | {e["props"]["id"] for j in dom.jobs for e in obs["graph"][j]["neo4j"]["edges"]}
    literal = ["co:synth-", "issue:overseas", '"rel-a"', '"rel-b"', "non_relationship_basis", "sourceCompanyId", "합성투자는", "해외 합작", "SYNTH-2", "SYNTH-4", "SYNTH-9", dom.hold,
               *sorted(private_ids)]
    patterns = [r"rc-[0-9a-f]{16}", r"rel-[0-9a-f]{16}"]
    for word in literal:
        need(word not in public_text, "leak", f"a private-only identifier or fact reached a public body: {word[:24]}")
    for pattern in patterns:
        need(not re.search(pattern, public_text), "leak", f"a private candidate or relationship id reached a public body: {pattern}")
    neo_text = json.dumps([obs["graph"][j]["neo4j"] for j in dom.jobs], ensure_ascii=False)
    for word in [*dom.pub_issue.values(), *[c["app"] for c in dom.pub_company.values()], *obs["app"]["pg"]["evidenceIds"]]:
        need(word not in neo_text, "leak", "an app id is stored in the private graph")
    return {"publicBodiesScanned": len(http["edges"]) + len(http["events"]) + len(http["evidence"]) + 2, "forbiddenTerms": len(literal) + len(patterns),
            "appIdsAbsentFromNeo4j": len(dom.pub_issue) + len(dom.pub_company) + len(obs["app"]["pg"]["evidenceIds"])}


def reconcile(obs: dict, dom) -> dict:
    return {"pins": check_pins(obs, dom), "companies": check_companies(obs, dom), "issues": check_issues(obs, dom), "relations": check_relations(obs, dom),
            "evidence": check_evidence(obs, dom), "public": check_public(obs, dom), "leaks": check_leaks(obs, dom)}


# ------------------------------------------------------------------------------------------------- negative controls -----------------------

def tampers(obs: dict, dom):
    """In-memory mutations of OBSERVED data (never a store): each yields (what, expected code, mutated observation, mapping)."""
    def mutate(label, code, change, mapping=None):
        copied = copy.deepcopy(obs)
        change(copied)
        return label, code, copied, mapping or dom

    def first(o, job, kind):
        return next(e for e in o["graph"][job]["neo4j"]["edges"] if e["type"] == kind)

    def swap_evidence(o):
        edge = first(o, "rel-a", "PARTICIPATES_IN")
        edge["props"]["evidenceIds"] = [next(e["evidenceId"] for e in o["graph"]["rel-a"]["read"]["evidence"] if e["evidenceId"] not in edge["props"]["evidenceIds"])]

    def shift_span(o):
        o["graph"]["rel-a"]["read"]["evidence"][0]["start"] += 1

    yield mutate("the app receipt pins another S3 inputDigest", "pin_mismatch",
                 lambda o: o["app"]["receipt"]["manifest"]["sources"][0]["relation"].update(inputDigest="0" * 64))
    yield mutate("the graph version pins another S3 inputDigest", "pin_mismatch", lambda o: o["graph"]["rel-a"]["inspect"]["source"]["relation"].update(inputDigest="1" * 64))
    yield mutate("the graph version pins another S2 upstream digest", "pin_mismatch", lambda o: o["graph"]["rel-a"]["inspect"]["source"]["upstream"].update(digest="2" * 64))
    yield mutate("a stored Neo4j participation cites another document span", "issue_grouping", swap_evidence)
    yield mutate("a private evidence coordinate is one code point off", "evidence_mapping", shift_span)
    yield mutate("a stored Neo4j SUPPLIES relationship is reversed", "relation_mapping", lambda o: first(o, "rel-a", "SUPPLIES").update(start="co:synth-1", end="co:synth-3"))
    def list_hold(o):
        edge = first(o, "rel-a", "INVESTS_IN")
        edge["props"]["sourceRelationCandidateIds"].append(dom.hold)
        next(v for v in o["graph"]["rel-a"]["read"]["graph"]["edges"] if v["relationId"] == edge["props"]["id"])["sourceRelationCandidateIds"].append(dom.hold)
    yield mutate("the S3 HOLD candidate is listed as a stored source", "hold_leak", list_hold)
    yield mutate("a public evidence quote differs from the authored span", "evidence_mapping", lambda o: next(iter(o["http"]["evidence"].values()))["body"].update(quote="변조된 인용"))
    yield mutate("the public derived SHARES_ISSUE edge is missing", "public_display",
                 lambda o: o["http"]["graph"].update(edges=[e for e in o["http"]["graph"]["edges"] if not e["derived"]]))
    yield mutate("a private-only company id leaks into a public event body", "leak", lambda o: o["http"]["events"]["issue:factory"].update(note="co:synth-2"))
    wrong = copy.copy(dom)
    wrong.companies = {**dom.companies, "SYNTH-3": {**dom.companies["SYNTH-3"], "canonical": "co:synth-1"}}
    yield mutate("the authored mapping binds SYNTH-3 to the wrong canonical company", "company_mapping", lambda o: None, wrong)


# ------------------------------------------------------------------------------------------------- provenance ------------------------------

def tree_pin(root: Path) -> str:
    return hs.digest({str(path.relative_to(root)): sha256(path.read_bytes()) for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts})


def provenance(args, evidence: dict) -> None:
    """Pin the installed package bytes every console script and this interpreter actually run, not just a checkout HEAD beside an unrelated venv."""
    from zoop_ai_pipeline import ingestion_contracts
    expected = tree_pin(handoff.PIPELINE / "src/zoop_ai_pipeline")
    package = Path(ingestion_contracts.__file__).resolve().parent
    check(tree_pin(package) == expected, "pipeline interpreter package differs from current source")
    installed = {"name": "zoop-ai-pipeline", "version": importlib.metadata.version("zoop-ai-pipeline"),
                 "sourceSha256": expected, "moduleRoot": str(package), "python": str(Path(sys.executable).absolute()), "consoleScripts": {}}
    program = ("import hashlib, importlib.metadata, json, sys\nfrom pathlib import Path\nfrom zoop_ai_pipeline import ingestion_contracts\n"
               "root = Path(ingestion_contracts.__file__).resolve().parent\n"
               "files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*.py')) if '__pycache__' not in p.parts}\n"
               "raw = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()\n"
               "print(json.dumps({'sourceSha256': hashlib.sha256(raw).hexdigest(), 'version': importlib.metadata.version('zoop-ai-pipeline'), "
               "'moduleRoot': str(root), 'python': str(Path(sys.executable).absolute())}))\n")
    entry = {"zoop-ai-handoff": "zoop_ai_pipeline.handoff_cli", "zoop-ai-ingest": "zoop_ai_pipeline.ingestion_cli", "zoop-ai-graph": "zoop_ai_pipeline.graph_projection_cli"}
    for cli in (args.handoff_cli, args.ingest_cli, args.graph_cli):
        check(cli.is_file() and os.access(cli, os.X_OK), "installed pipeline console script required: " + cli.name)
        text = cli.read_text()
        first = text.splitlines()[0]
        check(first.startswith("#!/") and " " not in first[2:], "console script needs an absolute Python shebang")
        check(f"from {entry[cli.name]} import main" in text, f"{cli.name} does not enter {entry[cli.name]}.main")
        done = subprocess.run([first[2:], "-c", program], env={**activation.START_ENV, **hs.CUSTOM}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        check(done.returncode == 0, "console script interpreter provenance unavailable")
        pin = json.loads(done.stdout)
        check(pin["sourceSha256"] == expected and pin["version"] == installed["version"], "console script package differs from current source")
        installed["consoleScripts"][cli.name] = {**pin, "scriptSha256": sha256(cli.read_bytes()), "entry": entry[cli.name] + ":main"}
    evidence["pipelinePackage"] = installed
    evidence["sourceFiles"] = {str(path.relative_to(activation.REPO)): sha256(path.read_bytes()) for path in (
        Path(__file__).resolve(), Path(activation.__file__).resolve(), Path(handoff.__file__).resolve(), Path(base.__file__).resolve(), Path(hs.__file__).resolve(),
        Path(gp.__file__).resolve(), Path(tls.__file__).resolve(), Path(local.__file__).resolve(), handoff.PIPELINE / "pyproject.toml", handoff.PIPELINE / "uv.lock")}


# ------------------------------------------------------------------------------------------------- the scenario --------------------------------

def mark(evidence: dict, name: str, **detail) -> None:
    evidence["steps"].append({"step": name, "status": "passed", **detail})
    base.step(name)


def timed(evidence: dict, phase: str, started: float) -> None:
    evidence.setdefault("runtimeSeconds", {})[phase] = round(time.monotonic() - started, 1)


def get_json(web, path: str, *, headers=None) -> tuple[int, dict | None]:
    STATS["http GET"] += 1
    code, raw, _ = web.request(path, headers=headers)
    try:
        return code, json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return code, None


def scenario(args, db, scratch, evidence, layouts):
    try:
        run_scenario(args, db, scratch, evidence, layouts)
    except Exception as error:
        if isinstance(error, Mismatch):
            print("finding: " + str(error)[:1200], file=sys.stderr)   # ids, codes and offsets only
        if not isinstance(error, AssertionError):
            import traceback
            print("unexpected " + type(error).__name__ + " at " + " <- ".join(f"{Path(f.filename).name}:{f.lineno}" for f in reversed(traceback.extract_tb(error.__traceback__)[-3:])), file=sys.stderr)
        raise


def run_scenario(args, db, scratch, evidence, layouts):
    started_all, started = time.monotonic(), time.monotonic()
    run = "rc" + secrets.token_hex(4)
    evidence.update({"schema": "zoop-graph-reconciliation-1", "run": run, "claims": CLAIMS, "negativeControls": {}})
    args.graph_cli = handoff.PIPELINE / ".venv/bin/zoop-ai-graph"
    evidence["phase"] = "preflight"
    provenance(args, evidence)
    evidence["runtime"] = {"python": sys.version.split()[0], "docker": local.first_line(local.docker("version", "--format", "{{.Server.Version}}").stdout),
                           "java": local.first_line(subprocess.run([args.java, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout)}

    # ---- 1. ONE authored world, ONE producer handoff ----------------------------------------------------------------------------------
    evidence["phase"] = "authored-world"
    published_at = "2026-10-08T00:00:00+00:00"
    world = hs.build_world(scratch / "world", b_published_at=published_at)
    decisions = hs.decisions_doc(world)
    decisions.update(schemaVersion="zoop-public-decisions-5", policyVersion="zoop-public-projection-policy-3")
    # The shared fixture authors a policy-2 attestation; its preimage must name this world's policy-3 contract before freeze.
    basis = hs.find(world.jobs["rel-a"], "SUPPLIES", "SYNTH-3", "SYNTH-1")
    decisions["structural"][0]["applicability"]["bindingDigest"] = hs.digest({
        "policy": decisions["policyVersion"], "issue": "issue:supply", "company": "co:synth-3", "decisionVersion": "v1",
        "eventTime": world.event_time, "geography": "domestic", "sourceEvents": hs.source_events(world),
        "basis": [{"jobId": "rel-a", "relationCandidateId": basis["relationCandidateId"], "relationKey": basis["relationKey"],
                   "type": "SUPPLIES", "revision": basis["eligibility"]["revision"]}]})
    for company in decisions["companies"]:
        company["publicId"] = PUBLIC[company["publicId"]]
    hs.write_operator(world, decisions=decisions)
    dom = authored(world)
    layout = handoff.Layout(world, args.ingest_cli)
    layouts.append(layout.work)
    source_dirs = ("ingestion", "extraction", "relation")
    sources_before = {name: handoff.fingerprint(world.root / name) for name in source_dirs}
    registry_before = layout.registry_path.read_bytes()
    canonical_path = world.root / "canonical.json"
    canonical_before = sha256(canonical_path.read_bytes())
    check(canonical_before == hs.file_hashes(world.root)["canonical"], "canonical.json changed while writing")
    operator = hs.Operator(world)
    manifest = hs.manifest_doc(world, HANDOFF_ID, hs.file_hashes(world.root))
    manifest["policyVersion"] = decisions["policyVersion"]
    check(all(s["relation"] == dom.jobs[s["relation"]["jobId"]]["relation"] and s["upstream"] == dom.jobs[s["relation"]["jobId"]]["upstream"] for s in manifest["sources"]),
          "the manifest does not pin the S3/S2 jobs")
    check(operator.cli("freeze", manifest)["state"] == "ready", "handoff freeze failed")
    exported = operator.cli("export", operator.sel(HANDOFF_ID))
    STATS["zoop-ai-handoff freeze"] += 1
    STATS["zoop-ai-handoff export"] += 1
    check(exported["bundle"]["schemaVersion"] == "zoop-graph-handoff-bundle-9"
          and exported["bundle"]["policy"]["version"] == decisions["policyVersion"], "expected bundle9/policy3")
    hs.check_export(world, exported, PUBLIC)
    factory_article, = (a for a in exported["bundle"]["articles"] if a["documentId"] == world.refs["b"]["documentId"])
    check(factory_article["publicationPrecision"] == "datetime"
          and datetime.fromisoformat(factory_article["publishedAt"]) == datetime.fromisoformat(published_at),
          "factory article must preserve its authored pre-ingestion publication timestamp")
    manifest_digest = hs.digest(manifest)
    bundle_digest = sha256(hs.canonical(exported["bundle"]).encode())
    check(manifest_digest == exported["receipt"]["manifestDigest"] and bundle_digest == exported["receipt"]["bundleDigest"], "the producer digests are not the canonical hashes")
    again = operator.cli("export", operator.sel(HANDOFF_ID))
    STATS["zoop-ai-handoff export"] += 1
    check(again["bundle"] == exported["bundle"] and again["receipt"] == exported["receipt"], "the producer export is not deterministic")
    mark(evidence, "one-authored-world-and-handoff-frozen", jobs=sorted(world.jobs), bundle="zoop-graph-handoff-bundle-9",
         policy=decisions["policyVersion"], factoryPublishedAt=published_at, exportDeterministic=True)
    timed(evidence, "authoredWorldAndHandoff", started)

    neo4j = OwnedNeo4j(evidence)
    raw = None
    try:
        # ---- 2. the SAME world as private Neo4j versions through the installed graph CLI ------------------------------------------------
        evidence["phase"] = "neo4j-projection"
        started = time.monotonic()
        uri = neo4j.start()
        raw = gp.Raw(uri, DATABASE)
        op = GraphOperator(world, uri, DATABASE, run)
        store = op.graph("init", {"schemaVersion": gp.SCHEMA, "storeId": f"{run}-store", "database": DATABASE})
        check(store["store"]["state"] == "bound" and store["usage"] == {"providerCalls": 0, "modelCalls": 0}, "graph init failed")
        names = list(dom.jobs)
        for job in names:
            frozen = op.freeze(job, job)
            check(frozen["state"] == "frozen" and frozen["publication"] == "not-published", f"graph freeze {job}")
            check(frozen["source"]["relation"] == dom.jobs[job]["relation"] and frozen["source"]["upstream"] == dom.jobs[job]["upstream"]
                  and frozen["source"]["reviewDigest"] == dom.jobs[job]["reviewDigest"], f"graph freeze {job} pins another S3/S2 identity")
        check(raw.count("MATCH (n) RETURN count(n) AS c") == 1, "a freeze wrote to Neo4j (only the ZgStore node may exist)")
        projected = {job: op.graph("project", op.sel(job)) for job in names}
        check(all(p["state"] == "ready" and p["usage"] == {"providerCalls": 0, "modelCalls": 0} for p in projected.values()), "graph project failed")
        mark(evidence, "neo4j-versions-frozen-and-projected", versions=len(names), schemaObjects=store["store"]["schemaObjects"])
        timed(evidence, "neo4jProjection", started)

        # ---- 3. the app side: documents, fixture pointer, handoff import (real jar, real PostgreSQL) ------------------------------------
        evidence["phase"] = "spring-import"
        started = time.monotonic()
        smoke = handoff.Smoke(args, db, layout)
        smoke.jar = activation.FixtureJar(args.java, args.jar, db, layout)
        status, result, _ = smoke.jar.run("documents", [base.item(ref) for ref in world.refs.values()], artifact_root=layout.artifacts)
        STATS["jar documents import"] += 1
        check(status == 0 and result and result["status"] == "succeeded", "document staging failed")
        db.run("INSERT INTO companies (id, name, name_key, search_text) VALUES " + ", ".join(f"('{cid}', '{name}', '', '')" for cid, name in handoff.COMPANIES))
        with activation.Web(smoke.jar, {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "fixture"}, ready="Graph fixture fixture-2026-10-08 "):
            STATS["jar web (fixture pointer seed)"] += 1
        before = activation.publication_state(db)
        check(before["active"] == "fixture-2026-10-08", "the fixture seeder did not establish the active pointer")
        vid = handoff.version_id(HANDOFF_ID)
        status, imported, output = smoke.graph_import("reconcile-stage", smoke.request(HANDOFF_ID, manifest_digest, bundle_digest))
        STATS["jar graph handoff import"] += 1
        check(status == 0 and imported and imported["outcome"] == "staged" and imported["graphVersionId"] == vid and imported["active"] is False
              and imported["activation"] == "not-activated", f"handoff staging failed: {imported} {output[-400:]}")
        staged = activation.publication_state(db)
        check(staged["active"] == before["active"] and staged["activations"] == before["activations"], "the import activated a version")
        mark(evidence, "spring-staged-import", outcome="staged", importActivationWrites=0, activePointerUnchanged=True)
        timed(evidence, "springImport", started)

        # ---- 4. idempotence: same-version re-freeze / re-project / re-import write nothing -------------------------------------------------
        evidence["phase"] = "idempotence"
        started = time.monotonic()
        dumps = {job: raw.dump(op.vid(job)) for job in names}
        ledger = op.ledger()
        reads = {job: op.graph("read", op.sel(job)) for job in names}
        for job in names:
            check(op.freeze(job, job) == op.graph("inspect", op.sel(job)) == projected[job], f"{job}: a repeated freeze changed the version")
            check(op.graph("project", op.sel(job)) == projected[job], f"{job}: a repeated project reserved a new attempt or changed the result")
        check({job: raw.dump(op.vid(job)) for job in names} == dumps and op.ledger() == ledger, "re-freeze/re-project changed Neo4j or the graph ledger")
        check({job: op.graph("read", op.sel(job)) for job in names} == reads, "a read after re-project differs")
        snapshot_file = layout.artifacts / "graph_snapshot" / f"{vid}.json"
        receipt_file = layout.artifacts / "verification_receipt" / f"{vid}.json"
        files = {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) for path in (snapshot_file, receipt_file)}
        tables = smoke.table_fingerprint()
        status, repeat, _ = smoke.graph_import("reconcile-again", smoke.request(HANDOFF_ID, manifest_digest, bundle_digest))
        STATS["jar graph handoff import"] += 1
        check(status == 0 and repeat and repeat["outcome"] == "unchanged" and repeat["evidenceRows"] == {"registered": 0, "existing": imported["counts"]["evidence"]}, f"re-import: {repeat}")
        check(smoke.table_fingerprint() == tables and {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in files} == files,
              "an identical re-import changed the database or the retained files")
        evidence["idempotence"] = {"neo4j": "re-freeze and re-project: same result, no new attempt, stored nodes/relationships/marker and the graph ledger byte-identical, read unchanged",
                                   "app": "re-import: outcome unchanged, 0 evidence rows written, database fingerprint and retained snapshot/receipt bytes+inode+mtime identical",
                                   "producer": "re-export: bundle and receipt identical"}
        mark(evidence, "same-version-idempotence", neo4jVersions=len(names), appVersions=1)
        timed(evidence, "idempotence", started)

        # ---- 5. observe the private and app stores, then activate and read publicly -----------------------------------------------------
        evidence["phase"] = "observe"
        started = time.monotonic()
        canonical_doc = json.loads(canonical_path.read_text("utf-8"))
        obs = {"canonicalDoc": canonical_doc, "decisions": json.loads((world.root / "decisions.json").read_text("utf-8")),
               "graph": {job: {"inspect": op.graph("inspect", op.sel(job)), "read": reads[job], "neo4j": neo4j_observation(raw, op.vid(job))} for job in names}}
        receipt = json.loads(receipt_file.read_text("utf-8"))
        snapshot = json.loads(snapshot_file.read_text("utf-8"))
        pg = {"graphVersion": db.rows(f"""SELECT id, kind, active, review_revision, created_by, policy_version, source_label, issue_count, relation_count, article_count,
                                          snapshot_artifact_id, published_at IS NULL AS unpublished FROM graph_versions WHERE id = '{vid}'""")[0],
              "evidence": db.rows("""SELECT id, article_id, article_version, quote, start_offset, end_offset, offset_unit, quote_verified, verification_artifact_id
                                     FROM evidence ORDER BY id"""),
              "companies": db.rows("SELECT id, name FROM companies WHERE id LIKE 'SYNTH:%' ORDER BY id"),
              "artifacts": db.rows(f"SELECT id, kind, sha256, bytes FROM artifacts WHERE id IN ('artifact-{vid}', 'artifact-receipt-{vid}') ORDER BY id")}
        pg["evidenceIds"] = [row["id"] for row in pg["evidence"]]
        obs["app"] = {"snapshot": snapshot, "receipt": receipt, "pg": pg,
                      "files": {f"artifact-{vid}": sha256(snapshot_file.read_bytes()), f"artifact-receipt-{vid}": sha256(receipt_file.read_bytes())}}
        obs["pins"] = {"manifest": manifest, "bundle": exported["bundle"], "export": exported["receipt"], "importResult": imported,
                       "canonicalSha256Before": canonical_before, "canonicalSha256After": sha256(canonical_path.read_bytes())}
        check(pg["graphVersion"]["active"] is False and pg["graphVersion"]["unpublished"] is True and pg["graphVersion"]["review_revision"] == 0, "the staged version row")
        registry = layout.registry_path.read_bytes()
        public_http = {"graph": None, "edges": {}, "events": {}, "evidence": {}, "unregistered": {}}
        auth = activation.bootstrap_session(db)
        key = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        env = {"ZOOP_GRAPH_SNAPSHOT_SOURCE": "artifact", "ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT": str(layout.artifacts), "ZOOP_DOCUMENT_READ_ARTIFACT_ROOT": str(layout.artifacts),
               "ZOOP_DOCUMENT_READ_INGESTION_SOURCES": str(layout.registry_path), "ZOOP_AUTH_CSRF_ACTIVE_KEY_ID": "activation-test", "ZOOP_AUTH_CSRF_KEYS": "activation-test=" + key,
               "SPRING_PROFILES_ACTIVE": "local", "ZOOP_AUTH_ALLOWED_ORIGINS": activation.ORIGIN, "ZOOP_API_CORS_ALLOWED_ORIGINS": activation.ORIGIN}
        evidence["phase"] = "activate-and-read"
        with activation.Web(smoke.jar, env) as web:
            STATS["jar web (activation + public reads)"] += 1
            code, session = get_json(web, "/api/v1/admin/auth/session", headers=auth)
            check(code == 200 and session and session.get("authenticated") and session.get("csrfToken"), "the synthetic admin session is unavailable")
            headers = {**auth, "Origin": activation.ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrfToken"], "Idempotency-Key": "reconcile-activate"}
            STATS["http POST admin activation"] += 1
            code, body, _ = web.request(f"/api/v1/admin/graph/versions/{vid}/activate", payload={"reason": "Synthetic local reconciliation", "expectedActiveVersionId": before["active"], "mode": "forward"},
                                        headers=headers)
            check(code == 200 and json.loads(body) == {"activeVersionId": vid, "previousActiveVersionId": before["active"], "idempotent": False}, f"admin activation answered {code}")
            active = activation.publication_state(db)
            check(active["active"] == vid and len(active["activations"]) == len(staged["activations"]) + 1, "the admin activation did not move the pointer exactly once")
            evidence.update({"importActivationWrites": 0, "sqlHarnessActivations": 0, "fixtureSeedActivations": len(before["activations"]),
                             "adminHttpActivations": 1, "httpPointerChanges": 1})
            code, public_http["graph"] = get_json(web, f"/api/v1/graph?graphVersion={vid}")
            check(code == 200 and public_http["graph"], f"public graph answered {code}")
            code, current = get_json(web, "/api/v1/graph")
            check(code == 200 and current["metadata"]["graphVersion"] == vid, "the default public read is not the activated version")
            for edge in public_http["graph"]["edges"]:
                code, public_http["edges"][edge["id"]] = get_json(web, f"/api/v1/graph/edges/{edge['id']}?graphVersion={vid}")
                check(code == 200, f"edge detail {edge['relationType']} answered {code}")
            for canonical_id, authored_issue in dom.issues.items():
                public_id = authored_issue["public"] or canonical_id
                code, body = get_json(web, "/api/v1/events/" + urllib.parse.quote(public_id, safe="") + "?" + urllib.parse.urlencode({"graphVersion": vid}))
                check(code == (200 if authored_issue["public"] else 404), f"event {canonical_id} answered {code}")
                public_http["events"][canonical_id] = body if authored_issue["public"] else None
            for evidence_id in pg["evidenceIds"]:
                code, body = get_json(web, f"/api/v1/evidence/{evidence_id}?graphVersion={vid}")
                public_http["evidence"][evidence_id] = {"status": code, "body": body}
            for label in dom.private_evidence_only:
                name, quote = dom.quotes[label]
                code, _ = get_json(web, f"/api/v1/evidence/{hs.evidence_id(world, name, quote)}?graphVersion={vid}")
                public_http["unregistered"][label] = {"status": code}
            obs["http"] = public_http
            timed(evidence, "observe", started)

            # ---- 6. reconcile the real observations ---------------------------------------------------------------------------------------
            evidence["phase"] = "reconcile"
            started = time.monotonic()
            coverage = reconcile(obs, dom)
            evidence["reconciliation"] = {
                "mappingCoverage": coverage, "assumedMappings": 0,
                "pins": {job: {"s3": dom.jobs[job]["relation"], "s2Upstream": dom.jobs[job]["upstream"], "reviewDigest": dom.jobs[job]["reviewDigest"]} for job in names},
                "producer": {"manifestDigest": manifest_digest, "bundleDigest": bundle_digest, "contentDigest": exported["receipt"]["contentDigest"]},
                "canonicalJsonSha256": canonical_before, "sourcesRegistrySha256": sha256(registry_before),
                "domainMapping": {"companies": dom.companies, "issues": {k: v["public"] for k, v in dom.issues.items()}},
                "private": {"nodes": {job: len(obs["graph"][job]["neo4j"]["nodes"]) for job in names},
                            "relationships": {job: len(obs["graph"][job]["neo4j"]["edges"]) for job in names},
                            "evidenceCoordinates": coverage["evidence"]["privateEvidenceCoordinates"]},
                "app": {"companies": len(snapshot["companies"]), "issues": len(snapshot["issues"]), "relations": len(snapshot["relations"]), "evidenceRows": len(pg["evidence"]),
                        "displayEdges": len(public_http["graph"]["edges"])}}
            evidence["reconciliation"]["identityEvidence"] = {
                "neo4j": {job: {"versionId": op.vid(job), "observationSha256": hs.digest(obs["graph"][job]["neo4j"]),
                                "evidence": reads[job]["evidence"]} for job in names},
                "snapshotSha256": sha256(snapshot_file.read_bytes()), "receiptSha256": sha256(receipt_file.read_bytes()),
                "publicGraphSha256": hs.digest(public_http["graph"]),
                "publicRelations": [{"id": r["relationId"], "type": r["relationType"], "source": r["source"],
                                     "target": r["target"], "evidenceIds": r["evidenceIds"]} for r in snapshot["relations"]],
                "publicEvidence": [{"id": row["id"], "articleId": row["article_id"], "articleVersion": row["article_version"],
                                    "start": row["start_offset"], "end": row["end_offset"], "offsetUnit": row["offset_unit"],
                                    "quoteSha256": sha256(row["quote"].encode()),
                                    "httpBodySha256": hs.digest(public_http["evidence"][row["id"]]["body"])} for row in pg["evidence"]]}
            mark(evidence, "cross-store-reconciliation", coverage={k: coverage[k] for k in ("pins", "relations", "evidence")})
            timed(evidence, "reconcile", started)

            # ---- 7. current rights: the one registry file the private CLIs and the app read -------------------------------------------------
            evidence["phase"] = "current-rights"
            started = time.monotonic()
            rights = {}
            for label, change in (("disabled", lambda g: g.update({"enabled": False})),
                                  ("quote-display-revoked", lambda g: g.update({"allowedOperations": [x for x in g["allowedOperations"] if x != "quote-display"]})),
                                  ("revision-changed", lambda g: g.update({"revision": g["revision"] + "-changed"}))):
                smoke.set_registry(change)
                try:
                    statuses = [get_json(web, f"/api/v1/evidence/{i}?graphVersion={vid}")[0] for i in pg["evidenceIds"]]
                    event_status = get_json(web, "/api/v1/events/" + urllib.parse.quote(dom.publics.supply, safe="") + f"?graphVersion={vid}")[0]
                    private_reads = {job: op.exec("read", op.sel(job))[:2] for job in names}
                finally:
                    layout.registry_path.write_bytes(registry)
                check(all(s == 404 for s in statuses) and event_status == 404, f"{label}: public evidence/event still served ({statuses}, {event_status})")
                check(all(code == 2 and out and out["delivery"]["status"] == "withheld" and "graph" not in out for code, out in private_reads.values()),
                      f"{label}: the private graph read must be withheld with exit 2 and no graph")
                rights[label] = {"publicEvidence404": len(statuses), "publicEvent": event_status,
                                 "privateRead": {job: {"exit": code, "delivery": (out or {}).get("delivery", {}).get("code", (out or {}).get("delivery", {}).get("status"))}
                                                 for job, (code, out) in private_reads.items()}}
                restored = [get_json(web, f"/api/v1/evidence/{i}?graphVersion={vid}")[0] for i in pg["evidenceIds"]]
                check(all(s == 200 for s in restored) and {job: op.graph("read", op.sel(job)) for job in names} == reads, f"{label}: the restore did not bring both stores back")
            check(layout.registry_path.read_bytes() == registry_before, "the source registry was not restored byte for byte")
            evidence["currentRights"] = rights
            mark(evidence, "current-rights-both-stores", cases=list(rights))
            timed(evidence, "currentRights", started)

        # ---- 8. negative controls -----------------------------------------------------------------------------------------------------
        evidence["phase"] = "negative-controls"
        started = time.monotonic()
        remap = copy.deepcopy(canonical_doc)
        for entry in remap["entries"]:
            if entry["kind"] == "company" and entry["ref"] == "SYNTH-3" and entry["upstream"]["jobId"] == world.s2["a"]["jobId"]:
                entry["canonicalId"] = "co:synth-9"
        remap_path = world.root / "canonical-remap.json"
        remap_path.write_bytes(hs.json_bytes(remap))
        op.freeze("rel-a-remap", "rel-a", canonical=remap_path)
        check(op.graph("project", op.sel("rel-a-remap"), canonical=remap_path)["state"] == "ready", "the remapped control version was not projected")
        control = copy.deepcopy(obs)
        control["graph"]["rel-a"] = {"inspect": op.graph("inspect", op.sel("rel-a-remap")), "read": op.graph("read", op.sel("rel-a-remap"), canonical=remap_path),
                                     "neo4j": neo4j_observation(raw, op.vid("rel-a-remap"))}
        try:
            reconcile(control, dom)
        except Mismatch as error:
            check(error.code == "company_mapping", f"the remapped Neo4j version was detected as {error.code}, not company_mapping")
            evidence["negativeControls"]["productControl"] = {"what": "a REAL Neo4j version written by the real CLI under another canonical mapping (SYNTH-3 -> co:synth-9)",
                                                              "detectedAs": error.code, "storesTouched": "one extra private version; the handoff and the app version are unchanged"}
        else:
            raise AssertionError("the comparator accepted a Neo4j version under another canonical mapping")
        check(op.graph("read", op.sel("rel-a")) == reads["rel-a"] and raw.dump(op.vid("rel-a")) == dumps["rel-a"], "the control disturbed the real rel-a version")
        results = []
        for label, code, mutated, mapping in tampers(obs, dom):
            try:
                reconcile(mutated, mapping)
            except Mismatch as error:
                check(error.code == code, f"harness tamper '{label}': detected as {error.code}, expected {code}")
                results.append({"tamper": label, "detectedAs": error.code})
            else:
                raise AssertionError(f"harness tamper '{label}' was accepted by the comparator")
        evidence["negativeControls"]["harnessTamper"] = {"what": "in-memory deep copies of observed data; no store, ledger or file touched", "controls": results}
        check(reconcile(obs, dom) == coverage, "the comparator is not stable over the untampered observations")
        mark(evidence, "negative-controls-detected", productControls=1, harnessTampers=len(results))
        timed(evidence, "negativeControls", started)

        # ---- 9. nothing but the intended stores changed -------------------------------------------------------------------------------
        evidence["phase"] = "ledgers"
        check({name: handoff.fingerprint(world.root / name) for name in source_dirs} == sources_before, "an S1/S2/S3 source ledger changed")
        check(layout.registry_path.read_bytes() == registry_before and sha256(canonical_path.read_bytes()) == canonical_before, "an operator input changed")
        check(activation.publication_state(db)["active"] == vid, "the active pointer moved after the reconciled read")
        evidence["ledgerReadOnly"] = True
        evidence["commands"] = dict(sorted(STATS.items()))
        evidence["providerCalls"] = evidence["modelCalls"] = 0
        evidence["notProven"] = NOT_PROVEN
        evidence["exclusionStoreAuthoritative"] = True
        evidence["developmentOptInOnly"] = False
    finally:
        if raw is not None:
            raw.close()
        neo4j.stop()
    evidence["runtimeSeconds"]["total"] = round(time.monotonic() - started_all, 1)


if __name__ == "__main__":
    sys.exit(activation.run_smoke(scenario, smoke_name=SMOKE, description=__doc__, not_proven=NOT_PROVEN))
