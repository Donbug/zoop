"""Nonpublic S3 -> Neo4j version projection: everything that does not need a running Neo4j.

The upstream is a REAL ingestion + S2 extraction + S3 relation world read through the owners' own read-only seams; expectations are written by hand from
the authored world (see scripts/graph_projection_smoke.py), never echoed from the code under test. What needs a database (init, the transactional write,
recovery, the full-graph read verification, focus over a stored version) is proven by that smoke against a real Neo4j 5 instead of any driver double.
No network, no model, no PoC database or app state.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from neo4j.exceptions import AuthError, ClientError, ConstraintError, IncompleteCommit, ServiceUnavailable
from pydantic import ValidationError

from scripts import graph_projection_smoke as gs
from scripts.ingestion_smoke import json_bytes
from scripts.relation_smoke import build_world
from zoop_ai_pipeline import graph_neo4j as neo
from zoop_ai_pipeline import graph_projection as gp
from zoop_ai_pipeline import graph_projection_cli as cli
from zoop_ai_pipeline.graph_projection_contracts import (EDGE_KEYS, EDGE_SPECS, LABELS, MAX_EDGES, MAX_ENTRIES, SCHEMA, CanonicalEntry, CanonicalRegistry,
    ExtractionFailure, Focus, Freeze, Init, Selector, entry_key, graph_digest, node_key, normalized_props, observed_props, relation_id, split_key, stored_props)
from zoop_ai_pipeline.relation_contracts import TYPES

HASH = "a" * 64
HOSTILE = ("x'}) DETACH DELETE n //", "v1' OR 1=1 //", '"; MATCH (n) DETACH DELETE n; //', "v1|kr-000100", "a b", "é", "line\nbreak", "a\0b", "v" * 201, "")


# ---------------------------------------------------------------- fixtures -----------------------------------------------------------

@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """One real world with its five S3 jobs, never mutated by a test (mutating scenarios use a private copy, see `rig`)."""
    world = build_world(tmp_path_factory.mktemp("zoop-graph") / "owned")
    jobs = gs.build_relations(world, process=False)
    return SimpleNamespace(world=world, jobs=jobs, main=gs.expected_main(world, jobs), two=gs.expected_two(world, jobs))


class Rig:
    """A private copy of the source ledgers and grants plus a fresh, empty graph ledger (created without any Neo4j) and a canonical registry."""

    def __init__(self, shared, tmp_path: Path):
        self.shared, self.world = shared, shared.world
        self.root = tmp_path / "rig"
        self.root.mkdir()
        for name in ("ingestion", "extraction", "relation"):
            shutil.copytree(shared.world.kit.root / name, self.root / name)
        self.sources = self.root / "sources.json"
        shutil.copy(shared.world.kit.registry_path, self.sources)
        self.canonical = self.root / "canonical.json"
        self.canonical.write_bytes(json_bytes(gs.registry(shared.world)))
        self.state = self.root / "graph"
        gp.Store(self.state, *self.upstream(), mode="create").close()

    def upstream(self) -> tuple[Path, Path, Path]:
        return self.root / "relation", self.root / "extraction", self.root / "ingestion"

    def run(self, command: str, request, *, expected: int = 0, state: Path | None = None, canonical: Path | None = None, extra: tuple = (), raw: bytes | None = None):
        argv = ["zoop-ai-graph", command, "--state-dir", str(state or self.state)]
        if command in cli.SOURCED:
            relation, extraction, ingestion = self.upstream()
            argv += ["--relation-state-dir", str(relation), "--extraction-state-dir", str(extraction), "--ingestion-state-dir", str(ingestion),
                     "--sources", str(self.sources), "--canonical", str(canonical or self.canonical)]
        argv += list(extra)
        out = io.StringIO()
        data = raw if raw is not None else json_bytes(request)
        with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(data))), contextlib.redirect_stdout(out):
            code = cli.main()
        text = out.getvalue()
        assert code == expected, text
        assert text.endswith("\n") and text.count("\n") == 1, text
        return json.loads(text), text

    def sel(self, name: str = "v1") -> dict:
        return {"schemaVersion": SCHEMA, "versionId": name}

    def freeze(self, name: str, job: str, *, expected: int = 0, canonical: Path | None = None):
        relation = {"jobId": job, "inputDigest": self.shared.jobs[job]["inputDigest"]}
        return self.run("freeze", {**self.sel(name), "relation": relation}, expected=expected, canonical=canonical)

    def grant(self, **change) -> None:
        document = json.loads(self.sources.read_text())
        document["sources"][0]["grant"].update(change)
        self.sources.write_bytes(json_bytes(document))

    def ledger(self) -> str:
        db = sqlite3.connect(self.state / "graph.sqlite3")
        try:
            return json.dumps([db.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall() for table in ("meta", "versions", "attempts")], ensure_ascii=False)
        finally:
            db.close()

    def plan(self, name: str = "v1") -> dict:
        db = sqlite3.connect(self.state / "graph.sqlite3")
        try:
            return json.loads(db.execute("SELECT plan FROM versions WHERE version_id=?", (name,)).fetchone()[0])
        finally:
            db.close()


@pytest.fixture
def rig(shared, tmp_path):
    return Rig(shared, tmp_path)


def error(out: dict, code: str, detail: dict | None = None) -> None:
    assert out == {"schemaVersion": SCHEMA, "error": {"code": code, **({"detail": detail} if detail else {})}}, out


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        digest.update(item.name.encode() + (item.read_bytes() if item.is_file() else b""))
    return digest.hexdigest()


# ---------------------------------------------------------------- wire contract and identifiers ------------------------------------

def test_wire_models_refuse_hostile_identifiers_wrong_shapes_and_the_system_database():
    for text in HOSTILE:
        with pytest.raises(ValidationError):
            Selector.model_validate({"schemaVersion": SCHEMA, "versionId": text})
        with pytest.raises(ValidationError):
            Focus.model_validate({"schemaVersion": SCHEMA, "versionId": "v1", "companyId": text, "depth": 1})
        with pytest.raises(ValidationError):
            Init.model_validate({"schemaVersion": SCHEMA, "storeId": text, "database": "neo4j"})
    for depth in (0, 4, True, False, "2", 2.0, None):
        with pytest.raises(ValidationError):
            Focus.model_validate({"schemaVersion": SCHEMA, "versionId": "v1", "companyId": "c", "depth": depth})
    assert [Focus.model_validate({"schemaVersion": SCHEMA, "versionId": "v1", "companyId": "kr:1.2-3_4", "depth": d}).depth for d in (1, 2, 3)] == [1, 2, 3]
    for database in ("system", "SYSTEM", "ab", "9db", "with_underscore", ""):
        with pytest.raises(ValidationError):
            Init.model_validate({"schemaVersion": SCHEMA, "storeId": "s", "database": database})
    for relation in ({"jobId": "j", "inputDigest": "A" * 64}, {"jobId": "j", "inputDigest": "a" * 63}, {"jobId": "j", "inputDigest": HASH, "extra": 1}):
        with pytest.raises(ValidationError):
            Freeze.model_validate({"schemaVersion": SCHEMA, "versionId": "v1", "relation": relation})
    with pytest.raises(ValidationError):
        Selector.model_validate({"schemaVersion": SCHEMA, "versionId": "v1", "extra": 1})
    with pytest.raises(ValidationError):
        Selector.model_validate({"schemaVersion": "other", "versionId": "v1"})


def entry(i: int, **override) -> dict:
    return {"upstream": {"jobId": "s2", "inputDigest": HASH}, "kind": "company", "ref": f"R{i}", "canonicalId": f"c{i}", "decisionRef": f"d{i}", **override}


def test_canonical_registry_is_strict_closed_bounded_and_keyed_by_the_exact_s2_upstream():
    ok = CanonicalRegistry.model_validate({"schemaVersion": "zoop-graph-canonical-1", "entries": [entry(1), entry(2, kind="event"), entry(3, kind="topic")]})
    assert len(ok.entries) == 3
    other_upstream = entry(1, upstream={"jobId": "s2", "inputDigest": "b" * 64})
    assert len(CanonicalRegistry.model_validate({"schemaVersion": "zoop-graph-canonical-1", "entries": [entry(1), other_upstream]}).entries) == 2   # same ref, other S2 input
    bad = [entry(1, canonicalId=text) for text in HOSTILE] + [entry(1, decisionRef=text) for text in HOSTILE] + [entry(1, kind="other"), entry(1, extra=1)]
    for item in bad:
        with pytest.raises(ValidationError):
            CanonicalRegistry.model_validate({"schemaVersion": "zoop-graph-canonical-1", "entries": [item]})
    for document in ({"schemaVersion": "zoop-graph-canonical-1", "entries": [entry(1), entry(1, canonicalId="other")]},   # one key, two decisions
                     {"schemaVersion": "zoop-graph-canonical-2", "entries": []}, {"schemaVersion": "zoop-graph-canonical-1"},
                     {"schemaVersion": "zoop-graph-canonical-1", "entries": [entry(i) for i in range(MAX_ENTRIES + 1)]}):
        with pytest.raises(ValidationError):
            CanonicalRegistry.model_validate(document)
    # Many refs may map to one canonical ID (aliases); the mapping is not required to be injective.
    assert len(CanonicalRegistry.model_validate({"schemaVersion": "zoop-graph-canonical-1", "entries": [entry(1, canonicalId="same"), entry(2, canonicalId="same")]}).entries) == 2


def test_registry_file_is_read_without_symlinks_and_within_its_size_cap(tmp_path):
    good = tmp_path / "ok.json"
    good.write_bytes(json_bytes({"schemaVersion": "zoop-graph-canonical-1", "entries": [entry(1)]}))
    loaded = gp.load_registry(good)
    assert list(loaded.entries) == [entry_key("s2", HASH, "company", "R1")]
    link = tmp_path / "link.json"
    link.symlink_to(good)
    (tmp_path / "big.json").write_bytes(b" " * 2_000_001)
    (tmp_path / "bad.json").write_bytes(b"{")
    for path in (link, tmp_path / "big.json", tmp_path / "bad.json", tmp_path / "missing.json", tmp_path):
        with pytest.raises(ExtractionFailure) as exc:
            gp.load_registry(path)
        assert exc.value.code == "canonical_registry_invalid"
    good.write_bytes(good.read_bytes() + b" ")
    with pytest.raises(ExtractionFailure) as exc:
        gp.registry_unchanged(loaded, good)
    assert exc.value.code == "canonical_registry_changed"


def test_node_and_edge_keys_round_trip_with_an_unambiguous_separator_and_length_caps():
    for version in ("v1", "a" * 120, "x:y.z-1_2"):
        for ident in ("kr-000100", "i" * 200, "event:main-event", "a.b_c-d:e"):
            key = node_key(version, ident)
            assert len(key) <= 321 and split_key(version, key) == ident
    for version, key in (("v1", "v10|a"), ("v1", "v1|a|b"), ("v1", "v1|"), ("v1", "v1|" + "i" * 201), ("v1", "v1|é"), ("v1", "v1|a b"), ("v1", "v1|a\n"),
                         ("v1", "x|a"), ("v1", None), ("v1", 5), ("v1", "v1")):
        with pytest.raises(ValueError):
            split_key(version, key)


def test_edge_properties_omit_nulls_round_trip_and_reject_unknown_or_foreign_data():
    edge_id = "rel-" + "a" * 64
    props = normalized_props({"id": edge_id, "direction": "directed", "connection": "direct", "productScope": "부품", "evidenceIds": ["ev-" + "1" * 32]})
    assert list(props) == list(EDGE_KEYS) and props["businessScope"] is None and props["countries"] == [] and props["evidenceIds"] == ["ev-" + "1" * 32]
    stored = stored_props("v1", props)
    assert stored == {"vk": f"v1|{edge_id}", "v": "v1", "id": edge_id, "direction": "directed", "connection": "direct", "productScope": "부품",
                      "evidenceIds": ["ev-" + "1" * 32]}   # no null, no empty list is ever written
    assert observed_props("v1", stored) == props
    for broken in ({**stored, "active": True}, {**stored, "v": "v2"}, {**stored, "vk": "v1|rel-other"}, {**stored, "countries": []}, {**stored, "evidenceIds": [1]},
                   {**stored, "productScope": ["x"]}, {**stored, "evidenceIds": "ev-1"}, {k: v for k, v in stored.items() if k != "vk"}, "not a map"):
        with pytest.raises(ValueError):
            observed_props("v1", broken)


def test_relation_ids_and_graph_digests_are_deterministic_order_independent_and_content_sensitive():
    company = lambda i: {"kind": "company", "id": f"c{i}"}  # noqa: E731
    args = ("SUPPLIES", company(1), company(2), "scope", None, "2026-01-01", None, "direct", ["KR"], [])
    assert relation_id(*args) == relation_id(*args) and relation_id(*args).startswith("rel-") and len(relation_id(*args)) == 68
    variants = [("INVESTS_IN", *args[1:]), (args[0], company(2), company(1), *args[3:]), (*args[:3], "other", *args[4:]), (*args[:4], "p", *args[5:]),
                (*args[:5], "2026-01-02", *args[6:]), (*args[:7], "indirect", *args[8:]), (*args[:8], [], args[9]),
                (*args[:9], [{"type": "SUPPLIES", "subject": company(1), "object": company(3)}])]
    assert len({relation_id(*args), *(relation_id(*v) for v in variants)}) == len(variants) + 1
    props = lambda i, **kw: normalized_props({"id": f"rel-{i}", "direction": "directed", "connection": "direct", **kw})  # noqa: E731
    nodes = [("ZgCompany", "b"), ("ZgCompany", "a"), ("ZgTopic", "t")]
    edges = [("SUPPLIES", "rel-1", ("ZgCompany", "a"), ("ZgCompany", "b"), props(1)), ("RELATES_TO_TOPIC", "rel-2", ("ZgCompany", "a"), ("ZgTopic", "t"), props(2, productScope="x"))]
    base = graph_digest("v1", nodes, edges)
    assert graph_digest("v1", reversed(nodes), reversed(edges)) == base != graph_digest("v2", nodes, edges)
    assert graph_digest("v1", nodes[:2], edges) != base and graph_digest("v1", nodes, edges[:1]) != base
    assert graph_digest("v1", nodes, [edges[0], (*edges[1][:4], props(2, productScope="y"))]) != base
    assert graph_digest("v1", nodes, [edges[0], ("SUPPLIES", *edges[1][1:])]) != base


def test_edge_specs_cover_exactly_the_s3_vocabulary_so_a_new_type_cannot_be_dropped_silently():
    assert set(EDGE_SPECS) == set(TYPES)
    for name, (subject, obj, direction) in TYPES.items():
        spec = EDGE_SPECS[name]
        assert (spec.subject, spec.object, spec.direction) == (subject, obj, direction) and spec.relationship == f"ZG_{name}"
    assert len({spec.relationship for spec in EDGE_SPECS.values()}) == len(EDGE_SPECS) and set(LABELS) == {"company", "event", "topic"}


# ---------------------------------------------------------------- connection configuration, statements and error mapping ---------------

def test_target_uris_are_loopback_plain_bolt_or_certificate_verified_tls_only():
    assert neo.validate_uri("bolt://127.0.0.1:7687") == "bolt://127.0.0.1:7687"
    assert neo.validate_uri("bolt://LOCALHOST:7687") == "bolt://localhost:7687" and neo.validate_uri("bolt://[::1]:7687") == "bolt://[::1]:7687"
    assert neo.validate_uri("bolt+s://graph.example.org:7687") == "bolt+s://graph.example.org:7687" and neo.is_secure("bolt+s://h:1")
    for bad in ("bolt://user:pw@127.0.0.1:7687", "bolt://127.0.0.1", "bolt://127.0.0.1:0", "bolt://127.0.0.1:70000", "bolt://127.0.0.1:7687/db", "bolt://127.0.0.1:7687/",
                "bolt://127.0.0.1:7687?x=1", "bolt://127.0.0.1:7687#f", "neo4j://127.0.0.1:7687", "neo4j+s://graph.example.org:7687", "bolt+ssc://graph.example.org:7687",
                "bolt://example.com:7687", "bolt://10.0.0.5:7687", "http://127.0.0.1:7687", "bolt:127.0.0.1:7687", "bolt://127.0.0.1:7687 ", "bolt://127.0.0.1:7687\n",
                "bolt+s://:7687", "bolt+s://under_score.example:7687", "bolt://é:7687", "", None, 7687, "bolt://127.0.0.1:7687/" + "a" * 400):
        with pytest.raises(ExtractionFailure) as exc:
            neo.validate_uri(bad)
        assert exc.value.code == "graph_uri_invalid", bad


def test_credentials_come_only_from_the_environment_and_are_never_part_of_an_error():
    local, secure = "bolt://127.0.0.1:7687", "bolt+s://graph.example.org:7687"
    assert neo.read_auth(local, {"ZOOP_GRAPH_AUTH": "none"}) is None
    assert neo.read_auth(local, {"ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": "u", "ZOOP_GRAPH_PASSWORD": "p"}) == ("u", "p")
    assert neo.read_auth(secure, {"ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": "u", "ZOOP_GRAPH_PASSWORD": "p"}) == ("u", "p")
    for uri, env in ((local, {}), (local, {"ZOOP_GRAPH_AUTH": "other"}), (local, {"ZOOP_GRAPH_AUTH": "basic"}), (local, {"ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": "u"}),
                     (local, {"ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": "", "ZOOP_GRAPH_PASSWORD": "secret-password"}),
                     (secure, {"ZOOP_GRAPH_AUTH": "none"}), (secure, {"ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": "u" * 201, "ZOOP_GRAPH_PASSWORD": "secret-password"})):
        with pytest.raises(ExtractionFailure) as exc:
            neo.read_auth(uri, env)
        assert exc.value.code == "graph_auth_unconfigured" and "secret-password" not in repr(exc.value) and exc.value.detail is None


def test_the_cypher_runner_refuses_unregistered_statements_before_any_server_contact():
    # tx=None: a registered statement gets as far as touching the transaction (AttributeError); anything else is refused first with a stable code.
    for statement in ("MATCH (n) DETACH DELETE n", "CREATE (n)", "MATCH (n:ZgCompany) RETURN n; MATCH (m) DELETE m", neo.READ_MARKER + " ", "", "CALL dbms.listConfig()"):
        with pytest.raises(ExtractionFailure) as exc:
            neo.run(None, statement)
        assert exc.value.code == "graph_internal_failure"
    for statement in (neo.COUNT_NODES, neo.READ_MARKER, neo.STORE_CREATE, neo.READ_OWNED_EDGES, neo.READ_OWNED_NODES, *neo.DDL, *neo.NODE_WRITE.values(),
                      *neo.EDGE_WRITE.values(), *neo.READ_EDGES.values()):
        with pytest.raises(AttributeError):
            neo.run(None, statement)


def test_existing_schema_with_an_expected_name_but_another_definition_is_a_conflict_while_a_correct_partial_schema_is_not():
    constraints, indexes = neo.expected_schema()
    assert not neo.schema_conflicts({}, {}) and not neo.schema_conflicts(constraints, indexes)
    partial = ({k: constraints[k] for k in list(constraints)[:3]}, {k: indexes[k] for k in list(indexes)[:2]})   # an interrupted earlier init
    assert not neo.schema_conflicts(*partial)
    populating = {name: (*found[:4], "POPULATING") for name, found in indexes.items()}
    assert not neo.schema_conflicts({}, populating)
    name = "zg_company_vk"
    for wrong in (("UNIQUENESS", "NODE", ("ZgOther",), ("other",)), ("UNIQUENESS", "NODE", ("ZgCompany",), ("other",)), ("NODE_KEY", "NODE", ("ZgCompany",), ("vk",)),
                  ("UNIQUENESS", "RELATIONSHIP", ("ZgCompany",), ("vk",))):
        assert neo.schema_conflicts({name: wrong}, {}), wrong
    right_index = indexes[name]
    for wrong_index in (("RANGE", "NODE", ("ZgOther",), ("other",), "ONLINE"), ("TEXT", *right_index[1:]), (*right_index[:4], "FAILED")):
        assert neo.schema_conflicts({}, {name: wrong_index}), wrong_index
    assert not neo.schema_conflicts({"unrelated": ("UNIQUENESS", "NODE", ("X",), ("y",))}, {"other_index": ("TEXT", "NODE", ("X",), ("y",), "ONLINE")})   # other names: not this question


def test_a_token_lookup_index_is_part_of_the_schema_only_under_a_name_of_this_schema():
    def show(name, kind, labels, properties, entity="NODE"):
        return {"name": name, "type": kind, "entityType": entity, "labelsOrTypes": labels, "properties": properties, "state": "ONLINE"}

    defaults = [show("index_343aff4e", "LOOKUP", None, None), show("index_f7700477", "LOOKUP", None, None, "RELATIONSHIP")]   # the database's own, other names
    constraints, indexes = neo.schema_objects([], defaults)
    assert indexes == {} and not neo.schema_conflicts(constraints, indexes)
    for planted in (show("zg_company_vk", "LOOKUP", None, None), show("zg_company_v", "LOOKUP", None, None), show("zg_supplies_vk", "LOOKUP", None, None, "RELATIONSHIP")):
        constraints, indexes = neo.schema_objects([], [*defaults, planted])
        assert set(indexes) == {planted["name"]}, planted
        assert neo.schema_conflicts(constraints, indexes), planted
    expected_constraints, expected_indexes = neo.expected_schema()
    constraint_rows = [{"name": name, "type": kind, "entityType": entity, "labelsOrTypes": list(labels), "properties": list(properties)}
                       for name, (kind, entity, labels, properties) in expected_constraints.items()]
    index_rows = [show(name, kind, list(labels), list(properties), entity) for name, (kind, entity, labels, properties, _) in expected_indexes.items()]
    assert neo.schema_objects(constraint_rows, [*index_rows, *defaults]) == (expected_constraints, expected_indexes)   # the complete schema, the defaults aside


def test_driver_errors_become_stable_codes_and_never_keep_messages_or_uris():
    secret = "bolt://user:secret-password@host:7687 failed at /private/path"
    for exc, code, detail in ((ServiceUnavailable(secret), "graph_unavailable", {"driver": "ServiceUnavailable"}), (OSError(secret), "graph_unavailable", {"driver": "OSError"}),
                              (AuthError(secret), "graph_auth_failed", None), (ClientError(secret), "graph_query_failed", None)):
        failure = neo.translate(exc)
        assert failure.code == code and "secret-password" not in repr((failure.code, failure.detail)) and "/private" not in repr(failure.detail)
        if detail:
            assert failure.detail == detail
    assert neo.translate(ClientError(secret), write=True).code == "graph_write_failed" and neo.translate(ValueError(secret)).code == "graph_internal_failure"


def test_commit_outcomes_are_classified_from_the_real_driver_exceptions():
    classify = gp.Projector._classify
    unknown = ("unknown", "unknown", "graph_commit_unknown")
    for exc in (IncompleteCommit("lost"), ServiceUnavailable("x"), ValueError("anything raised by commit()"), ClientError("x")):
        verdict = classify(exc, True)
        assert (verdict.state, verdict.outcome, verdict.code) == unknown
    verdict = classify(ConstraintError("another writer may hold the marker"), False)
    assert (verdict.state, verdict.outcome, verdict.code) == unknown
    verdict = classify(ExtractionFailure("graph_write_mismatch"), False)
    assert (verdict.state, verdict.outcome, verdict.code) == ("frozen", "rolled-back", "graph_write_mismatch")
    verdict = classify(ServiceUnavailable("down"), False)
    assert (verdict.state, verdict.outcome, verdict.code, verdict.detail) == ("frozen", "not-committed", "graph_unavailable", {"driver": "ServiceUnavailable"})
    verdict = classify(ClientError("syntax"), False)
    assert (verdict.state, verdict.outcome, verdict.code) == ("frozen", "not-committed", "graph_write_failed")
    verdict = classify(KeyError("bug"), False)
    assert (verdict.state, verdict.outcome, verdict.code) == ("frozen", "not-committed", "graph_internal_failure")


# ---------------------------------------------------------------- planning over the real world ---------------------------------------

def plan_edges(plan: dict) -> list[dict]:
    return [{"type": e["type"], "start": e["subject"]["id"], "end": e["object"]["id"], **{k: e["props"][k] for k in EDGE_KEYS if k != "id"}} for e in plan["edges"]]


def test_freeze_maps_all_five_types_with_exact_counts_merges_and_no_source_content(rig):
    shared = rig.shared
    out, text = rig.freeze("v1", "rel-main")
    assert out["state"] == "frozen" and out["next"] == "project" and out["publication"] == "not-published" and out["failure"] is None and out["attempts"] == []
    assert out["counts"] == {"nodes": {"company": 4, "event": 1, "topic": 1}, "edges": {"SUPPLIES": 2, "INVESTS_IN": 1, "COMPETES_WITH": 1, "PARTICIPATES_IN": 1,
                                                                                  "RELATES_TO_TOPIC": 1}, "evidence": 7}
    assert out["audit"] == shared.main["audit"] and out["canonical"]["entries"] == 7 and out["usage"] == {"providerCalls": 0, "modelCalls": 0}
    assert out["source"]["relation"] == {"jobId": "rel-main", "inputDigest": shared.jobs["rel-main"]["inputDigest"]}
    assert out["source"]["upstream"] == shared.jobs["rel-main"]["binding"]["upstream"] and out["source"]["provenance"] == shared.jobs["rel-main"]["provenance"]
    plan = rig.plan()
    wanted = [{"type": e["type"], "start": e["start"], "end": e["end"], **gs.full(e)} for e in shared.main["edges"]]
    key = lambda d: (d["type"], d["start"], d["end"])  # noqa: E731
    assert sorted(plan_edges(plan), key=key) == sorted(wanted, key=key)   # incl. the re-sorted symmetric pair, the 3-company path and the merged event edge
    assert sorted((label, ident) for label, ident in plan["nodes"]) == sorted((label, ident) for label, ids in shared.main["nodes"].items() for ident in ids)
    assert [e["evidenceId"] for e in plan["evidence"]] == shared.main["evidence"] and all(set(e) == {"evidenceId", "documentId", "documentVersion", "rawVersion", "start", "end"}
                                                                                         for e in plan["evidence"])
    everything = text + json.dumps(plan, ensure_ascii=False)
    assert not [p for p in gs.PRIVATE if p in everything] and '"quote"' not in everything and "https://" not in text
    assert not any(k in everything for k in ('"active"', '"approved"', '"public"', '"published"'))
    assert rig.run("inspect", rig.sel())[0] == out


def test_symmetric_pairs_are_resorted_by_canonical_id_not_by_the_s3_order(rig):
    rig.freeze("v1", "rel-main")
    plan = rig.plan()
    competes = [e for e in plan["edges"] if e["type"] == "COMPETES_WITH"]
    assert len(competes) == 1 and (competes[0]["subject"]["id"], competes[0]["object"]["id"]) == ("kr-000050", "kr-000100")   # S3's own order is SYNTH-1, SYNTH-2
    reordered = rig.root / "reordered.json"
    swap = {**gs.mapping(rig.world), ("company", "SYNTH-1"): "kr-000010"}
    reordered.write_bytes(json_bytes(gs.registry(rig.world, swap)))
    rig.freeze("v2", "rel-main", canonical=reordered)
    again = [e for e in rig.plan("v2")["edges"] if e["type"] == "COMPETES_WITH"]
    assert (again[0]["subject"]["id"], again[0]["object"]["id"]) == ("kr-000010", "kr-000050") and again[0]["props"]["id"] != competes[0]["props"]["id"]


def test_an_unresolved_endpoint_a_self_collapse_and_a_path_collapse_each_fail_the_whole_freeze(rig):
    world, before = rig.world, rig.ledger()
    only = {k: v for k, v in gs.mapping(world).items() if k != ("topic", world.tp)}
    unresolved = rig.root / "unresolved.json"
    unresolved.write_bytes(json_bytes(gs.registry(world, only)))
    out, _ = rig.freeze("bad", "rel-main", expected=2, canonical=unresolved)
    error(out, "canonical_mapping_unresolved", {"total": 1, "unresolved": [{"kind": "topic", "ref": world.tp}]})
    self_collapse = rig.root / "self.json"
    self_collapse.write_bytes(json_bytes(gs.registry(world, {**gs.mapping(world), ("company", "SYNTH-4"): "kr-000300"})))
    out, _ = rig.freeze("bad", "rel-two", expected=2, canonical=self_collapse)
    assert out["error"]["code"] == "canonical_mapping_conflict" and out["error"]["detail"]["reason"] == "self_relation"
    path_collapse = rig.root / "path.json"
    path_collapse.write_bytes(json_bytes(gs.registry(world, {**gs.mapping(world), ("company", "SYNTH-1"): "kr-000300"})))
    out, _ = rig.freeze("bad", "rel-path", expected=2, canonical=path_collapse)
    assert out["error"]["code"] == "canonical_mapping_conflict" and out["error"]["detail"]["reason"] == "path_collapsed"
    error(rig.run("inspect", rig.sel("bad"), expected=2)[0], "version_not_found")
    assert rig.ledger() == before


def test_excluded_candidates_need_no_decision_and_every_eligible_endpoint_does(rig):
    world = rig.world
    # The registry has no entry for the topic-kind spelling of an event ID (REJECT) and none for anything the HOLD touches beyond mapped companies.
    assert ("topic", world.event) not in gs.mapping(world)
    out, _ = rig.freeze("v1", "rel-main")
    assert out["audit"]["eligibility"] == {"eligible": 7, "hold": 1, "reject": 1, "pending": 0} and out["audit"]["projectedCandidates"] == 7
    for kind, ref in [("company", "SYNTH-3"), ("event", world.event), ("event", world.evc)]:
        subset = rig.root / f"no-{ref}.json"
        subset.write_bytes(json_bytes(gs.registry(world, {k: v for k, v in gs.mapping(world).items() if k != (kind, ref)})))
        out, _ = rig.freeze(f"x-{kind}-{len(ref)}", "rel-main", expected=2, canonical=subset)
        assert out["error"]["code"] == "canonical_mapping_unresolved" and out["error"]["detail"]["unresolved"] == [{"kind": kind, "ref": ref}]


def test_zero_eligible_relations_is_a_valid_empty_version(rig):
    out, _ = rig.freeze("v-empty", "rel-empty")
    assert out["counts"] == {"nodes": {"company": 0, "event": 0, "topic": 0}, "edges": {name: 0 for name in EDGE_SPECS}, "evidence": 0}
    assert out["audit"] == {"s3Relations": 1, "eligibility": {"eligible": 0, "hold": 1, "reject": 0, "pending": 0}, "reviewPending": 0, "projectedCandidates": 0,
                            "approvals": {"automatic": 0, "operatorFinal": 0}, "canonicalMerges": 0, "impactCandidatesNotProjected": 0} and out["canonical"]["entries"] == 0
    plan = rig.plan("v-empty")
    assert plan["nodes"] == [] and plan["edges"] == [] and plan["evidence"] == []
    assert out["digests"]["graph"] == graph_digest("v-empty", [], []) and rig.run("inspect", rig.sel("v-empty"))[0] == out
    empty_registry = rig.root / "empty.json"
    empty_registry.write_bytes(json_bytes({"schemaVersion": "zoop-graph-canonical-1", "entries": []}))
    assert rig.freeze("v-empty-2", "rel-empty", canonical=empty_registry)[0]["counts"] == out["counts"]   # no decision is needed when nothing is eligible


def test_freeze_is_idempotent_a_different_request_conflicts_and_nothing_is_written(rig):
    out, _ = rig.freeze("v1", "rel-main")
    assert rig.freeze("v1", "rel-main")[0] == out
    before = rig.ledger()
    error(rig.freeze("v1", "rel-two", expected=2)[0], "version_input_conflict")
    bad_digest = {**rig.sel(), "relation": {"jobId": "rel-main", "inputDigest": "0" * 64}}
    error(rig.run("freeze", bad_digest, expected=2)[0], "version_input_conflict")
    assert rig.ledger() == before
    other = {**rig.sel("v9"), "relation": {"jobId": "rel-main", "inputDigest": "0" * 64}}
    assert rig.run("freeze", other, expected=2)[0]["error"]["code"] == "relation_input_mismatch"
    error(rig.run("freeze", {**rig.sel("v9"), "relation": {"jobId": "no-such-job", "inputDigest": HASH}}, expected=2)[0], "job_not_found")
    assert rig.ledger() == before


def test_a_repeated_freeze_stays_bound_to_the_frozen_upstream_across_grant_changes(rig):
    out, _ = rig.freeze("v1", "rel-main")
    before = rig.ledger()
    rig.grant(revision="rights-2")
    error(rig.freeze("v1", "rel-main", expected=2)[0], "grant_revision_changed")   # the request is byte-identical; the S2 digest it was frozen under is not current
    error(rig.freeze("v2", "rel-main", expected=2)[0], "grant_revision_changed")
    rig.grant(revision="rights-1", enabled=False)
    error(rig.freeze("v1", "rel-main", expected=2)[0], "source_unauthorized")
    rig.grant(enabled=True)
    assert rig.ledger() == before and rig.freeze("v1", "rel-main")[0] == out
    assert rig.run("inspect", rig.sel("v2"), expected=2)[0]["error"]["code"] == "version_not_found"


def test_canonical_decisions_are_read_fresh_by_every_command_and_pinned_exactly(rig):
    world = rig.world
    out, _ = rig.freeze("v1", "rel-main")
    before = rig.ledger()
    for label, document in (("decision identity", gs.registry(world, decision="decision-other")),
                            ("re-mapped company", gs.registry(world, {**gs.mapping(world), ("company", "SYNTH-3"): "kr-000301"})),
                            ("revoked topic", gs.registry(world, {k: v for k, v in gs.mapping(world).items() if k != ("topic", world.tp)}))):
        changed = rig.root / "changed.json"
        changed.write_bytes(json_bytes(document))
        assert rig.freeze("v1", "rel-main", expected=2, canonical=changed)[0] == {"schemaVersion": SCHEMA, "error": {"code": "canonical_mapping_changed"}}, label
    assert rig.freeze("v1", "rel-main")[0] == out and rig.ledger() == before


def test_the_source_ledgers_are_only_read_by_freeze(rig):
    before = {name: tree_hash(rig.root / name) for name in ("ingestion", "extraction", "relation")}
    rig.freeze("v1", "rel-main")
    rig.freeze("v1", "rel-main")
    rig.run("inspect", rig.sel())
    assert {name: tree_hash(rig.root / name) for name in before} == before
    assert sorted(p.name for p in rig.state.iterdir()) == ["graph.lock", "graph.sqlite3"] and oct((rig.state / "graph.sqlite3").stat().st_mode & 0o777) == "0o600"


# ---------------------------------------------------------------- hostile and malformed commands touch nothing ----------------------------

def test_hostile_and_malformed_inputs_are_refused_before_any_ledger_is_opened(rig, tmp_path):
    rig.freeze("v1", "rel-main")
    before_ledger, before_files = rig.ledger(), tree_hash(rig.state)
    for text in HOSTILE:
        for command, body in (("freeze", {**rig.sel(text), "relation": {"jobId": "rel-main", "inputDigest": HASH}}), ("project", rig.sel(text)), ("recover", rig.sel(text)),
                              ("inspect", rig.sel(text)), ("read", rig.sel(text)),
                              ("focus", {**rig.sel(), "companyId": text, "depth": 1})):
            error(rig.run(command, body, expected=2)[0], "input_or_configuration_invalid")
    for raw in (b"", b"[]", b"null", b'{"schemaVersion": "zoop-graph-projection-1"}', b"{not json", b"\xff\xfe"):
        error(rig.run("focus", None, expected=2, raw=raw)[0], "input_or_configuration_invalid")
    error(rig.run("inspect", None, expected=2, raw=b"x" * 70_000)[0], "command_input_limit")
    unsafe = tmp_path / "never-created"
    for uri in ("bolt://user:pw@127.0.0.1:7687", "neo4j://127.0.0.1:7687", "bolt://example.com:7687", "bolt://127.0.0.1:7687/db"):
        error(rig.run("init", {"schemaVersion": SCHEMA, "storeId": "s", "database": "neo4j"}, expected=2, state=unsafe, extra=("--graph-uri", uri))[0], "graph_uri_invalid")
        assert not unsafe.exists()
    error(rig.run("init", {"schemaVersion": SCHEMA, "storeId": "s", "database": "system"}, expected=2, state=unsafe, extra=("--graph-uri", "bolt://127.0.0.1:7687"))[0],
          "input_or_configuration_invalid")
    assert not unsafe.exists() and rig.ledger() == before_ledger and tree_hash(rig.state) == before_files


def test_flags_not_used_by_a_command_or_missing_for_it_are_refused_without_creating_state(rig, tmp_path):
    fresh = tmp_path / "fresh-state"
    body = rig.sel()
    error(rig.run("init", {"schemaVersion": SCHEMA, "storeId": "s", "database": "neo4j"}, expected=2, state=fresh)[0], "input_or_configuration_invalid")   # no --graph-uri
    error(rig.run("project", body, expected=2, state=fresh, extra=("--graph-uri", "bolt://127.0.0.1:7687"))[0], "input_or_configuration_invalid")
    error(rig.run("recover", body, expected=2, state=fresh, extra=("--sources", str(rig.sources)))[0], "input_or_configuration_invalid")
    error(rig.run("inspect", body, expected=2, state=fresh, extra=("--canonical", str(rig.canonical)))[0], "input_or_configuration_invalid")
    argv = ["zoop-ai-graph", "freeze", "--state-dir", str(fresh), "--relation-state-dir", str(rig.root / "relation")]   # a sourced command with flags missing
    out = io.StringIO()
    with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(json_bytes(body)))), contextlib.redirect_stdout(out):
        assert cli.main() == 2
    error(json.loads(out.getvalue()), "input_or_configuration_invalid")
    assert not fresh.exists()


def test_read_only_commands_create_no_state_when_the_ledger_is_missing(rig, tmp_path):
    missing = tmp_path / "missing-state"
    for command, body in (("inspect", rig.sel()), ("read", rig.sel()), ("focus", {**rig.sel(), "companyId": "c", "depth": 2})):
        error(rig.run(command, body, expected=2, state=missing)[0], "graph_state_missing")
        assert not missing.exists()
    for command, body in (("freeze", {**rig.sel(), "relation": {"jobId": "rel-main", "inputDigest": HASH}}), ("project", rig.sel()), ("recover", rig.sel())):
        error(rig.run(command, body, expected=2, state=missing)[0], "graph_state_missing")   # a writer never creates a ledger either: only init does
        assert not missing.exists()
    empty = tmp_path / "empty-state"
    empty.mkdir()
    error(rig.run("inspect", rig.sel(), expected=2, state=empty)[0], "graph_state_missing")
    assert list(empty.iterdir()) == []


# ---------------------------------------------------------------- ledger namespace and immutability ---------------------------------

def test_the_graph_ledger_namespace_is_disjoint_from_every_source_and_app_state_root(rig, tmp_path):
    relation, extraction, ingestion = rig.upstream()
    for candidate in (relation, extraction, ingestion, relation / "graph", ingestion / "nested", rig.root, rig.root.parent):
        with pytest.raises(ExtractionFailure) as exc:
            gp.Store(candidate, relation, extraction, ingestion, mode="write")
        assert exc.value.code == "state_namespace_conflict", candidate
    home = Path.home() / "InvestMateLogicTest" / "never-created-graph-state"
    with pytest.raises(ExtractionFailure) as exc:
        gp.Store(home, relation, extraction, ingestion, mode="create")
    assert exc.value.code == "state_namespace_conflict" and not home.exists()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ExtractionFailure) as exc:
        gp.Store(link / "state", relation, extraction, ingestion, mode="create")
    assert exc.value.code == "state_namespace_invalid" and list(real.iterdir()) == []
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("x")
    with pytest.raises(ExtractionFailure) as exc:
        gp.Store(foreign, relation, extraction, ingestion, mode="create")
    assert exc.value.code == "state_namespace_conflict"
    held = gp.Store(rig.state, relation, extraction, ingestion, mode="write")
    try:
        with pytest.raises(ExtractionFailure) as exc:
            gp.Store(rig.state, relation, extraction, ingestion, mode="write")   # one writer at a time
        assert exc.value.code == "graph_busy"
        with pytest.raises(ExtractionFailure) as exc:
            gp.Store(rig.state, mode="read")
        assert exc.value.code == "graph_busy"
    finally:
        held.close()


def test_ledger_identity_attempt_outcomes_and_terminal_states_are_immutable_in_sqlite(rig):
    rig.freeze("v1", "rel-main")
    db = sqlite3.connect(rig.state / "graph.sqlite3", isolation_level=None)
    try:
        for sql in ("UPDATE versions SET plan='{}'", "UPDATE versions SET payload_digest='x'", "UPDATE versions SET version_id='other'", "UPDATE versions SET input_digest='x'",
                    "UPDATE versions SET created_at='x'", "DELETE FROM versions", "UPDATE meta SET value='x'", "DELETE FROM meta"):
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(sql)
        with pytest.raises(sqlite3.DatabaseError):
            db.execute("UPDATE versions SET state='bogus'")   # the CHECK constraint
        db.execute("INSERT INTO attempts(version_id,n,reserved_at) VALUES('v1',1,'t')")
        db.execute("UPDATE attempts SET outcome='unknown' WHERE n=1")
        db.execute("UPDATE attempts SET outcome='confirmed',code=NULL WHERE n=1")   # unknown may still be settled once
        for sql in ("UPDATE attempts SET outcome='unknown'", "DELETE FROM attempts", "UPDATE attempts SET n=2", "UPDATE attempts SET reserved_at='x'"):
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(sql)
        db.execute("UPDATE versions SET state='ready' WHERE version_id='v1'")
        for sql in ("UPDATE versions SET state='frozen'", "UPDATE versions SET failure='x'", "UPDATE versions SET state='failed'"):
            with pytest.raises(sqlite3.DatabaseError):
                db.execute(sql)   # `ready` is terminal
    finally:
        db.close()


def tamper(rig, column: str, value: str | None = None) -> str:
    """Rewrite one frozen column the way a damaged disk or a manual edit would. The guard triggers are captured, dropped for the edit and RESTORED exactly as
    defined, so the ledger keeps its full object set (ownership/schema identity) and only the column differs; then close so no WAL is left."""
    db = sqlite3.connect(rig.state / "graph.sqlite3", isolation_level=None)
    try:
        triggers = db.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name IN ('immutable_versions_identity','terminal_versions')").fetchall()
        for name, _ in triggers:
            db.execute(f"DROP TRIGGER IF EXISTS {name}")
        original = db.execute(f"SELECT {column} FROM versions").fetchone()[0]
        db.execute(f"UPDATE versions SET {column}=?", (value if value is not None else original[:-1] + ("0" if original[-1] != "0" else "1"),))
        for _, sql in triggers:
            db.execute(sql)
        return original
    finally:
        db.close()


def test_a_damaged_plan_or_digest_and_a_foreign_ledger_fail_closed(rig):
    rig.freeze("v1", "rel-main")
    for column in ("plan", "payload_digest", "graph_digest"):
        original = tamper(rig, column)
        error(rig.run("inspect", rig.sel(), expected=2)[0], "graph_state_invalid")
        tamper(rig, column, original)
    assert rig.run("inspect", rig.sel())[0]["state"] == "frozen"
    other = rig.root / "other-ledger"
    other.mkdir()
    foreign = sqlite3.connect(other / "graph.sqlite3")
    foreign.execute("CREATE TABLE unrelated(x)")
    foreign.commit()
    foreign.close()
    (other / "graph.lock").write_bytes(b"")
    with pytest.raises(ExtractionFailure) as exc:
        gp.Store(other, *rig.upstream(), mode="write")
    assert exc.value.code == "graph_state_invalid"


# ---------------------------------------------------------------- gate order and focus over a verified plan ---------------------------

def mark_ready(rig, name: str = "v1", uri: str = "bolt://127.0.0.1:1") -> None:
    """Unit-level stand-in for a completed init+project: ONLY to prove that every authority gate answers before any Neo4j access. Nothing here is a
    claim about the graph; the real write/read paths are exercised by the smoke against Neo4j."""
    store = gp.Store(rig.state, *rig.upstream(), mode="write")
    try:
        binding = {"uri": uri, "database": "neo4j", "dbId": "d" * 8, "storeId": "s", "owner": "o" * 32, "schema": "zoop-graph-store-1", "server": {"agent": "x", "edition": "x"}}
        store.bind(binding)
        store.mark_ready(binding)
        store.db.execute("UPDATE versions SET state='ready' WHERE version_id=?", (name,))
    finally:
        store.close()


def test_a_withheld_read_answers_from_the_gates_before_any_neo4j_connection(rig, monkeypatch):
    rig.freeze("v1", "rel-main")
    mark_ready(rig)
    monkeypatch.setenv("ZOOP_GRAPH_AUTH", "none")
    before = rig.ledger()
    for command, body in (("read", rig.sel()), ("focus", {**rig.sel(), "companyId": "kr-000100", "depth": 1})):
        rig.grant(revision="rights-2")
        out, text = rig.run(command, body, expected=2)
        assert set(out) == gs.WITHHELD_KEYS and out["delivery"] == {"status": "withheld", "code": "grant_revision_changed"} and out["state"] == "ready"
        assert out["publication"] == "not-published" and not any(p in text for p in gs.PRIVATE) and "kr-0001" not in text and "배터리" not in text
        rig.grant(revision="rights-1", enabled=False)
        assert rig.run(command, body, expected=2)[0]["delivery"]["code"] == "source_unauthorized"
        rig.grant(enabled=True)
        changed = rig.root / "changed.json"
        changed.write_bytes(json_bytes(gs.registry(rig.world, decision="decision-other")))
        assert rig.run(command, body, expected=2, canonical=changed)[0]["delivery"]["code"] == "canonical_mapping_changed"
        changed.write_bytes(b"{")
        error(rig.run(command, body, expected=2, canonical=changed)[0], "canonical_registry_invalid")   # a broken registry is an error, never an empty or served result
    assert rig.ledger() == before   # a read never writes the ledger
    # With every gate open the read proceeds to Neo4j: an unreachable endpoint is a read FAILURE (error), never an empty success and never `withheld`.
    out, _ = rig.run("read", rig.sel(), expected=2)
    assert out["error"]["code"] == "graph_unavailable" and "delivery" not in out and "graph" not in out


def test_neo4j_credentials_and_the_target_never_appear_in_any_output(rig, monkeypatch):
    rig.freeze("v1", "rel-main")
    rig.freeze("v2", "rel-main")
    mark_ready(rig, "v1", "bolt://127.0.0.1:1")
    monkeypatch.setenv("ZOOP_GRAPH_AUTH", "basic")
    monkeypatch.setenv("ZOOP_GRAPH_USER", "secret-user")
    monkeypatch.setenv("ZOOP_GRAPH_PASSWORD", "secret-password")
    for command, name, expected in (("read", "v1", 2), ("project", "v2", 2), ("inspect", "v1", 0)):
        out, text = rig.run(command, rig.sel(name), expected=expected)
        assert "secret-user" not in text and "secret-password" not in text and "127.0.0.1:1" not in text and "bolt://" not in text, command
        assert not expected or out["error"]["code"] == "graph_unavailable", out
    assert rig.run("inspect", rig.sel("v2"))[0]["state"] == "frozen" and rig.run("inspect", rig.sel("v2"))[0]["attempts"] == []   # a refused project reserved nothing
    monkeypatch.delenv("ZOOP_GRAPH_AUTH")
    error(rig.run("read", rig.sel(), expected=2)[0], "graph_auth_unconfigured")
    error(rig.run("project", rig.sel("v2"), expected=2)[0], "graph_auth_unconfigured")


def test_focus_is_a_bounded_breadth_first_view_of_the_verified_version(rig):
    rig.freeze("v1", "rel-main")
    plan = rig.plan()

    def view(company, depth):
        found = gp.focus_of(plan, company, depth)
        return found["found"], {n["id"]: n["distance"] for n in found["nodes"]}, sorted((e["type"], e["subject"]["id"], e["object"]["id"]) for e in found["edges"])

    ab, cb, ca, dc = (("COMPETES_WITH", "kr-000050", "kr-000100"), ("SUPPLIES", "kr-000300", "kr-000100"), ("SUPPLIES", "kr-000300", "kr-000050"), ("INVESTS_IN", "kr-000400", "kr-000300"))
    be, bt = ("PARTICIPATES_IN", "kr-000100", "event:main-event"), ("RELATES_TO_TOPIC", "kr-000100", "topic:ev-supply-chain")
    assert {(e["type"], e["start"], e["end"]) for e in plan_edges(plan)} == {ab, cb, ca, dc, be, bt}
    assert view("kr-000100", 1) == (True, {"kr-000100": 0, "kr-000300": 1, "kr-000050": 1, "event:main-event": 1, "topic:ev-supply-chain": 1}, sorted([ab, cb, be, bt]))
    two = {"kr-000100": 0, "kr-000300": 1, "kr-000050": 1, "event:main-event": 1, "topic:ev-supply-chain": 1, "kr-000400": 2}
    assert view("kr-000100", 2) == (True, two, sorted([ab, cb, ca, dc, be, bt])) == view("kr-000100", 3)
    assert view("kr-000400", 1) == (True, {"kr-000400": 0, "kr-000300": 1}, [dc])
    assert view("kr-000400", 2) == (True, {"kr-000400": 0, "kr-000300": 1, "kr-000100": 2, "kr-000050": 2}, sorted([dc, cb, ca]))
    assert view("kr-000400", 3)[1] == {"kr-000400": 0, "kr-000300": 1, "kr-000100": 2, "kr-000050": 2, "event:main-event": 3, "topic:ev-supply-chain": 3}
    assert view("kr-000400", 3)[2] == sorted([dc, cb, ca, ab, be, bt])
    assert gp.focus_of(plan, "kr-999999", 2) == {"found": False, "nodes": [], "edges": []} and gp.focus_of(plan, "event:main-event", 1)["found"] is False   # only companies are roots
    assert gp.focus_of(plan, "kr-000100", 4) == {"found": False, "nodes": [], "edges": []}


def test_focus_finds_a_path_intermediate_company_that_is_a_node_of_the_version_without_synthetic_step_edges(rig):
    # rel-path alone: kr-000300 -> kr-000050 (indirect) through the intermediate kr-000100. The planner stores the intermediate as a company node of the
    # version although no projected edge has it as an endpoint, so it is PRESENT in the verified version and must be found (alone, at distance 0).
    rig.freeze("v1", "rel-path")
    plan = rig.plan()
    assert sorted(ident for label, ident in plan["nodes"]) == ["kr-000050", "kr-000100", "kr-000300"] and len(plan["edges"]) == 1
    for depth in (1, 2, 3):
        assert gp.focus_of(plan, "kr-000100", depth) == {"found": True, "nodes": [{"kind": "company", "id": "kr-000100", "distance": 0}], "edges": []}, depth
    ends = gp.focus_of(plan, "kr-000300", 3)   # the real edge only: no synthetic step edge reaches the intermediate
    assert {n["id"]: n["distance"] for n in ends["nodes"]} == {"kr-000300": 0, "kr-000050": 1}
    assert [(e["subject"]["id"], e["object"]["id"], e["props"]["connection"]) for e in ends["edges"]] == [("kr-000300", "kr-000050", "indirect")]
    assert gp.focus_of(plan, "kr-999999", 1)["found"] is False   # a company that is not a node stays absent


# ---------------------------------------------------------------- the planner on constructed S3-shaped data -----------------------------

UPSTREAM = {"jobId": "s2", "inputDigest": HASH}


def citation(n: int, **override) -> dict:
    return {"evidenceId": "ev-" + f"{n:032x}", "documentId": "doc", "documentVersion": "d" * 64, "rawVersion": "r" * 64, "start": n, "end": n + 5, "quote": "PRIVATE-QUOTE",
            "textArtifactId": "t", "rawLocatorIds": ["l"], "sourceSegments": [], **override}


def relation(i: int, rtype: str = "SUPPLIES", *, status: str = "eligible", pending: bool = False, manual: bool = False, **override) -> dict:
    """An S3-shaped relation. Eligible and not pending carries its history-proven approval basis: the automatic verdict (revision 1), or with `manual` a HOLD verdict
    followed by the operator's final approval `approved` (revision 2)."""
    spec = EDGE_SPECS[rtype]
    at = f"2026-10-21T00:00:{i % 60:02d}+00:00"
    if manual:
        history = [{"seq": 1, "kind": "verdict", "createdAt": "2026-10-21T00:00:00+00:00", "eligibility": "hold"},
                   {"seq": 2, "kind": "review", "createdAt": at, "decision": "allow", "reviewer": "operator-a", "effect": "approved", "expectedRevision": 1}]
        basis = {"kind": "operator-final-approval", "revision": 2, "reviewer": "operator-a", "decidedAt": at}
    else:
        history = [{"seq": 1, "kind": "verdict", "createdAt": at, "eligibility": status}]
        basis = {"kind": "automatic-verifier", "revision": 1, "reviewer": None, "decidedAt": at}
    return {"relationCandidateId": f"rc-{i:064x}", "relationKey": f"key-{i}", "type": rtype, "direction": spec.direction,
            "subject": {"kind": spec.subject, "ref": f"S{i}"}, "object": {"kind": spec.object, "ref": f"O{i}"}, "connection": "direct", "businessScope": None,
            "productScope": None, "validity": {"from": None, "until": None, "citations": []}, "countries": [], "citations": [citation(i)], "path": [],
            "eligibility": {"status": status, "reviewPending": pending, "revision": basis["revision"] if manual else 1,
                            "approvalBasis": basis if status == "eligible" and not pending else None}, "history": history, **override}


def result_of(relations: list) -> dict:
    states = [r["eligibility"]["status"] for r in relations]
    return {"jobId": "rel", "inputDigest": HASH, "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
            "binding": {"upstream": {**UPSTREAM, "digest": "b" * 64}, "versions": {"policy": "p"}}, "relations": relations,
            "counts": {"eligibility": {s: states.count(s) for s in ("eligible", "hold", "reject", "pending")}, "impactCandidates": 3}}


def entries_for(relations: list, extra: dict | None = None) -> dict:
    mapped = {}
    for r in relations:
        for endpoint in (r["subject"], r["object"], *(e for s in r["path"] for e in (s["subject"], s["object"]))):
            mapped[(endpoint["kind"], endpoint["ref"])] = f"c-{endpoint['kind']}-{endpoint['ref']}"
    mapped.update(extra or {})
    return {entry_key("s2", HASH, k, ref): CanonicalEntry.model_validate({"upstream": UPSTREAM, "kind": k, "ref": ref, "canonicalId": cid, "decisionRef": "d1"})
            for (k, ref), cid in mapped.items()}


def code_of(call) -> ExtractionFailure:
    with pytest.raises(ExtractionFailure) as exc:
        call()
    return exc.value


def test_planner_projects_only_eligible_unpending_relations_and_counts_the_rest():
    eligible = [relation(i) for i in range(1, 4)]
    excluded = [relation(10, status="hold"), relation(11, "COMPETES_WITH", status="reject"), relation(12, status="pending"), relation(13, pending=True)]
    relations = [*eligible, *excluded]
    plan = gp.plan_version("v1", result_of(relations), entries_for(eligible))   # no decision exists for any excluded endpoint
    assert len(plan["edges"]) == 3 and plan["audit"] == {"s3Relations": 7, "eligibility": {"eligible": 4, "hold": 1, "reject": 1, "pending": 1}, "reviewPending": 1,
                                                       "projectedCandidates": 3, "approvals": {"automatic": 3, "operatorFinal": 0}, "canonicalMerges": 0,
                                                       "impactCandidatesNotProjected": 3}
    assert plan["source"]["review"]["projected"] == [{"relationCandidateId": r["relationCandidateId"], "revision": 1, "approvalBasis": r["eligibility"]["approvalBasis"]}
                                                     for r in sorted(eligible, key=lambda x: x["relationCandidateId"])]
    assert "PRIVATE-QUOTE" not in json.dumps(plan) and plan["schema"] == "zoop-graph-plan-2" and plan["source"]["upstream"] == {**UPSTREAM, "digest": "b" * 64}
    assert sorted(e["subject"]["id"] for e in plan["edges"]) == ["c-company-S1", "c-company-S2", "c-company-S3"]
    unresolved = code_of(lambda: gp.plan_version("v1", result_of(relations), entries_for(eligible[:2])))
    assert unresolved.code == "canonical_mapping_unresolved" and unresolved.detail == {"total": 2, "unresolved": [{"kind": "company", "ref": "O3"}, {"kind": "company", "ref": "S3"}]}


def test_planner_limits_unsupported_types_and_malformed_payloads_fail_the_whole_freeze():
    many = [relation(i) for i in range(1, MAX_EDGES + 2)]
    assert code_of(lambda: gp.plan_version("v1", result_of(many), entries_for(many))).code == "version_limit_exceeded"
    boundary = many[:MAX_EDGES]
    assert len(gp.plan_version("v1", result_of(boundary), entries_for(boundary))["edges"]) == MAX_EDGES
    unsupported = [relation(1), relation(2, "SUPPLIES", **{"type": "FOLLOWS"})]
    assert code_of(lambda: gp.plan_version("v1", result_of(unsupported), entries_for(unsupported))).code == "relation_type_unsupported"
    failed_citation = [relation(1, citations=[citation(1, error="quote_mismatch")])]
    assert code_of(lambda: gp.plan_version("v1", result_of(failed_citation), entries_for(failed_citation))).code == "relation_payload_invalid"
    missing = relation(1)
    del missing["validity"]
    assert code_of(lambda: gp.plan_version("v1", result_of([missing]), entries_for([missing]))).code == "relation_payload_invalid"
    wrong_kind = [relation(1, "RELATES_TO_TOPIC", subject={"kind": "topic", "ref": "S1"})]
    assert code_of(lambda: gp.plan_version("v1", result_of(wrong_kind), entries_for(wrong_kind))).code == "relation_payload_invalid"
    conflict = [relation(1, citations=[citation(1)]), relation(2, citations=[citation(1, end=99)])]
    assert code_of(lambda: gp.plan_version("v1", result_of(conflict), entries_for(conflict))).code == "evidence_record_conflict"
    direct_with_path = [relation(1, path=[{"type": "SUPPLIES", "subject": {"kind": "company", "ref": "S1"}, "object": {"kind": "company", "ref": "O1"}, "citations": []}])]
    assert code_of(lambda: gp.plan_version("v1", result_of(direct_with_path), entries_for(direct_with_path))).code == "relation_payload_invalid"


def test_aliases_merge_equal_canonical_claims_with_unioned_evidence_and_self_or_path_collapse_fails():
    first, second = relation(1, citations=[citation(1)]), relation(2, citations=[citation(2)])
    shared = entries_for([first, second], {("company", "S2"): "c-company-S1", ("company", "O2"): "c-company-O1"})
    plan = gp.plan_version("v1", result_of([first, second]), shared)
    assert len(plan["edges"]) == 1 and plan["audit"]["canonicalMerges"] == 1 and plan["audit"]["projectedCandidates"] == 2
    props = plan["edges"][0]["props"]
    assert props["sourceRelationCandidateIds"] == sorted([first["relationCandidateId"], second["relationCandidateId"]]) and props["evidenceIds"] == [citation(1)["evidenceId"], citation(2)["evidenceId"]]
    scoped = relation(3, productScope="x")   # a different scope never merges
    assert len(gp.plan_version("v1", result_of([first, scoped]), entries_for([first, scoped], {("company", "S3"): "c-company-S1", ("company", "O3"): "c-company-O1"}))["edges"]) == 2
    same = relation(1)
    collapsed = code_of(lambda: gp.plan_version("v1", result_of([same]), entries_for([same], {("company", "O1"): "c-company-S1"})))
    assert collapsed.code == "canonical_mapping_conflict" and collapsed.detail["reason"] == "self_relation"
    path = [{"type": "SUPPLIES", "subject": {"kind": "company", "ref": "S1"}, "object": {"kind": "company", "ref": "M1"}, "citations": [citation(5)]},
            {"type": "SUPPLIES", "subject": {"kind": "company", "ref": "M1"}, "object": {"kind": "company", "ref": "O1"}, "citations": [citation(6)]}]
    indirect = relation(1, connection="indirect", citations=[], path=path)
    ok = gp.plan_version("v1", result_of([indirect]), entries_for([indirect]))["edges"][0]["props"]
    assert ok["pathCompanyIds"] == ["c-company-S1", "c-company-M1", "c-company-O1"] and ok["step1EvidenceIds"] == [citation(5)["evidenceId"]] and ok["evidenceIds"] == []
    folded = code_of(lambda: gp.plan_version("v1", result_of([indirect]), entries_for([indirect], {("company", "M1"): "c-company-S1"})))
    assert folded.code == "canonical_mapping_conflict" and folded.detail["reason"] == "path_collapsed"
    broken = [relation(1, connection="indirect", citations=[], path=path[:1])]
    assert code_of(lambda: gp.plan_version("v1", result_of(broken), entries_for(broken))).code == "relation_payload_invalid"


# ---------------------------------------------------------------- approval basis: automatic verdict vs the operator's final approval ----------

def test_the_approval_basis_is_proven_from_the_history_and_a_forged_or_legacy_basis_is_refused():
    automatic, manual = relation(1), relation(2, manual=True)
    assert gp.approval_basis(automatic) == {"kind": "automatic-verifier", "revision": 1, "reviewer": None, "decidedAt": "2026-10-21T00:00:01+00:00"}
    assert gp.approval_basis(manual) == {"kind": "operator-final-approval", "revision": 2, "reviewer": "operator-a", "decidedAt": "2026-10-21T00:00:02+00:00"}
    # An approval claimed over the wrong evidence is never trusted: the owner's history must prove exactly this kind, reviewer, revision and time.
    forged = [
        relation(3, manual=True, history=relation(3)["history"]),                                                    # operator basis over an automatic verdict
        relation(4, history=relation(4, manual=True)["history"]),                                                     # automatic basis over an operator approval
        relation(5, manual=True, eligibility={**relation(5, manual=True)["eligibility"], "revision": 3}),             # revision is not the deciding event's
        relation(6, manual=True, eligibility={**relation(6, manual=True)["eligibility"], "approvalBasis": {**relation(6, manual=True)["eligibility"]["approvalBasis"],
                                                                                                          "reviewer": "someone-else"}}),
        relation(7, manual=True, eligibility={**relation(7, manual=True)["eligibility"], "approvalBasis": {**relation(7, manual=True)["eligibility"]["approvalBasis"],
                                                                                                          "decidedAt": "2026-01-01T00:00:00+00:00"}}),
        relation(8, manual=True, eligibility={**relation(8, manual=True)["eligibility"], "approvalBasis": None}),
        relation(9, manual=True, eligibility={**relation(9, manual=True)["eligibility"], "approvalBasis": {"kind": "operator-final-approval", "revision": 2}}),
        relation(10, manual=True, history=[relation(10, manual=True)["history"][0], {**relation(10, manual=True)["history"][1], "effect": "revalidation-requested"}]),
        relation(11, history=[]),
        relation(12, status="hold"),
        relation(13, pending=True)]
    for item in forged:
        assert code_of(lambda: gp.approval_basis(item)).code == "relation_payload_invalid", item["relationCandidateId"]
    assert code_of(lambda: gp.plan_version("v1", result_of([forged[0]]), entries_for([forged[0]]))).code == "relation_payload_invalid"
    for stamp in ("2026-10-21T00:00:14", "garbage", "2026-10-21"):                       # no offset / not a timestamp: the app's OffsetDateTime parse would refuse it
        bad_time = relation(14)
        bad_time["eligibility"]["approvalBasis"]["decidedAt"] = bad_time["history"][-1]["createdAt"] = stamp
        assert code_of(lambda: gp.approval_basis(bad_time)).code == "relation_payload_invalid", stamp


def test_the_plan_pins_each_projected_relations_basis_and_keeps_automatic_and_manual_apart_on_every_edge():
    auto, hand = relation(1), relation(2, manual=True)
    merged_hand = relation(3, manual=True, citations=[citation(3)])
    shared = entries_for([auto, hand, merged_hand], {("company", "S3"): "c-company-S1", ("company", "O3"): "c-company-O1"})
    plan = gp.plan_version("v1", result_of([auto, hand, merged_hand]), shared)
    assert plan["schema"] == "zoop-graph-plan-2" and len(plan["edges"]) == 2 and plan["audit"]["approvals"] == {"automatic": 1, "operatorFinal": 2}
    assert plan["source"]["review"]["projected"] == [{"relationCandidateId": r["relationCandidateId"], "revision": r["eligibility"]["revision"],
                                                      "approvalBasis": r["eligibility"]["approvalBasis"]} for r in (auto, hand, merged_hand)]
    by_target = {e["subject"]["id"]: e for e in plan["edges"]}
    assert by_target["c-company-S1"]["approvals"] == [{"relationCandidateId": auto["relationCandidateId"], "kind": "automatic-verifier"},
                                                      {"relationCandidateId": merged_hand["relationCandidateId"], "kind": "operator-final-approval"}]
    assert by_target["c-company-S2"]["approvals"] == [{"relationCandidateId": hand["relationCandidateId"], "kind": "operator-final-approval"}]
    assert gp.edge_view(by_target["c-company-S2"])["sourceApprovals"] == by_target["c-company-S2"]["approvals"]
    assert "operator-a" not in json.dumps([gp.edge_view(e) for e in plan["edges"]])          # the reviewer lives in the frozen plan only, never in a read view
    # The per-edge kinds are part of the stored plan: a plan whose edge disagrees with the pinned basis is a damaged ledger.
    row = {"plan": json.dumps(plan), "version_id": "v1", "payload_digest": gp.digest(plan), "graph_digest": gp.plan_graph_digest(plan)}
    assert gp.verify_plan(row) == plan
    broken = json.loads(json.dumps(plan))
    next(e for e in broken["edges"] if e["subject"]["id"] == "c-company-S1")["approvals"][0]["kind"] = "operator-final-approval"
    row.update(plan=json.dumps(broken), payload_digest=gp.digest(broken))
    assert code_of(lambda: gp.verify_plan(row)).code == "graph_state_invalid"


def test_a_manual_approval_is_current_only_while_exactly_the_pinned_basis_stands():
    hand = relation(1, manual=True)
    plan = gp.plan_version("v1", result_of([hand]), entries_for([hand]))
    same = gp.Projector._unchanged_review(plan, result_of([hand]))
    assert same is True
    swapped = relation(1)                      # the same candidate, now decided by the automatic verdict: another kind, revision and time
    for changed in (swapped, relation(1, manual=True, eligibility={**hand["eligibility"], "revision": 3}), relation(1, status="hold"), relation(1, pending=True)):
        assert code_of(lambda: gp.Projector._unchanged_review(plan, result_of([changed]))).code == "review_revision_changed"
    later = relation(1, manual=True)
    later["history"] = [*later["history"], {"seq": 3, "kind": "review", "createdAt": "2026-10-21T01:00:00+00:00", "decision": "reject", "reviewer": "operator-b", "effect": "excluded"}]
    later["eligibility"] = {"status": "reject", "reviewPending": False, "revision": 3, "approvalBasis": None}
    assert code_of(lambda: gp.Projector._unchanged_review(plan, result_of([later]))).code == "review_revision_changed"


def test_a_ledger_row_frozen_under_the_earlier_plan_contract_is_history_and_never_projected_recovered_or_served(rig):
    rig.freeze("v1", "rel-main")
    current = rig.plan()
    assert current["schema"] == "zoop-graph-plan-2" and current["audit"]["approvals"] == {"automatic": current["audit"]["projectedCandidates"], "operatorFinal": 0}
    earlier = {**current, "schema": "zoop-graph-plan-1"}
    earlier["source"] = {**earlier["source"], "review": {**earlier["source"]["review"], "projected": [[p["relationCandidateId"], p["revision"]]
                                                                                                      for p in earlier["source"]["review"]["projected"]]}}
    tamper(rig, "plan", json.dumps(earlier, sort_keys=True))
    before = rig.ledger()
    shown, _ = rig.run("inspect", rig.sel(), expected=2)
    assert shown["state"] == "frozen" and shown["next"] is None and shown["delivery"] == {"status": "withheld", "code": "graph_contract_changed"}
    for command, body in (("project", rig.sel()), ("recover", rig.sel())):
        error(rig.run(command, body, expected=2)[0], "graph_contract_changed")
    relation_ref = {"jobId": "rel-main", "inputDigest": rig.shared.jobs["rel-main"]["inputDigest"]}
    error(rig.run("freeze", {**rig.sel(), "relation": relation_ref}, expected=2)[0], "graph_contract_changed")
    served, _ = rig.run("read", rig.sel(), expected=2)
    assert served["delivery"] == {"status": "withheld", "code": "graph_contract_changed"} and "graph" not in served
    assert rig.ledger() == before                    # nothing was noted, settled or rewritten
    fresh, _ = rig.run("freeze", {**rig.sel("v2"), "relation": relation_ref})
    assert fresh["state"] == "frozen" and fresh["next"] == "project"       # the operator freezes a NEW version id under the current contract


# ---------------------------------------------------------------- history is decided read-only, before any writer opens the ledger ----------

def earlier_plan(rig, name: str = "v1") -> dict:
    current = rig.plan(name)
    earlier = {**current, "schema": "zoop-graph-plan-1"}
    earlier["source"] = {**earlier["source"], "review": {**earlier["source"]["review"], "projected": [[p["relationCandidateId"], p["revision"]]
                                                                                                      for p in earlier["source"]["review"]["projected"]]}}
    return earlier


def disk(root: Path) -> dict:
    """Everything the ledger directory holds: its own mode and, per file, mode, size, mtime and bytes."""
    found = {".": (root.stat().st_mode, root.stat().st_mtime_ns)}
    for p in sorted(root.iterdir()):
        info = p.stat()
        found[p.name] = (info.st_mode, info.st_size, info.st_mtime_ns, p.read_bytes())
    return found


KILLED_WRITER = ("import json, os, sqlite3, sys\n"
                 "spec = json.load(sys.stdin)\n"
                 "db = sqlite3.connect(spec['database'], isolation_level=None)\n"
                 "db.execute('PRAGMA journal_mode=WAL')\n"
                 "db.execute('PRAGMA wal_autocheckpoint=0')\n"
                 "for statement in spec['statements']:\n"
                 "    db.execute(statement[0], statement[1:])\n"
                 "os._exit(0)\n")        # committed rows stay in the WAL: no checkpoint, no close


def kill_writer(rig, *statements) -> None:
    import subprocess
    out = subprocess.run([sys.executable, "-c", KILLED_WRITER], input=json.dumps({"database": str(rig.state / "graph.sqlite3"),
                         "statements": [list(s) for s in statements]}).encode(), capture_output=True, timeout=60)
    assert out.returncode == 0, out.stderr.decode()
    assert (rig.state / "graph.sqlite3-wal").stat().st_size > 0


def loosen(rig) -> None:
    """Modes a writer would re-permission (0700 directory, 0600 files): the history decision must leave them exactly as they are."""
    rig.state.chmod(0o755)
    for p in rig.state.iterdir():
        p.chmod(0o644)


def test_history_is_decided_from_the_ledger_alone_and_no_command_changes_a_byte_mode_or_mtime(rig):
    rig.freeze("v1", "rel-main")
    tamper(rig, "plan", json.dumps(earlier_plan(rig), sort_keys=True))
    loosen(rig)
    before = disk(rig.state)
    relation_ref = {"jobId": "rel-main", "inputDigest": rig.shared.jobs["rel-main"]["inputDigest"]}
    for command, body, expected in (("inspect", rig.sel(), 2), ("project", rig.sel(), 2), ("recover", rig.sel(), 2), ("read", rig.sel(), 2),
                                    ("focus", {**rig.sel(), "companyId": "kr-000100", "depth": 1}, 2), ("freeze", {**rig.sel(), "relation": relation_ref}, 2)):
        out, _ = rig.run(command, body, expected=expected)
        assert (out.get("error", {}).get("code") or out["delivery"]["code"]) == "graph_contract_changed", command
        assert disk(rig.state) == before, command       # no chmod, no WAL/SHM file, no checkpoint, no rewrite


def test_a_history_row_that_only_lives_in_a_hot_wal_is_still_history_and_the_ledger_is_untouched(rig):
    rig.freeze("v1", "rel-main")
    loosen(rig)
    plan = json.dumps(earlier_plan(rig), sort_keys=True)
    db = sqlite3.connect(rig.state / "graph.sqlite3")
    triggers = db.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND name IN ('immutable_versions_identity','terminal_versions')").fetchall()
    db.close()
    kill_writer(rig, *[(f"DROP TRIGGER {name}",) for name, _ in triggers], ("UPDATE versions SET plan=?", plan), *[(sql,) for _, sql in triggers])    # schema restored in the WAL
    before = disk(rig.state)
    assert any(name.endswith("-wal") and values[1] > 0 for name, values in before.items() if name != ".")
    relation_ref = {"jobId": "rel-main", "inputDigest": rig.shared.jobs["rel-main"]["inputDigest"]}
    shown, _ = rig.run("inspect", rig.sel(), expected=2)
    assert shown["state"] == "frozen" and shown["delivery"] == {"status": "withheld", "code": "graph_contract_changed"}
    for command, body in (("project", rig.sel()), ("recover", rig.sel()), ("freeze", {**rig.sel(), "relation": relation_ref})):
        error(rig.run(command, body, expected=2)[0], "graph_contract_changed")
    assert rig.run("read", rig.sel(), expected=2)[0]["delivery"] == {"status": "withheld", "code": "graph_contract_changed"}
    assert disk(rig.state) == before
    assert not list(Path(tempfile_dir()).glob("zoop-graph-history-*"))             # the private scratch copy was removed


def tempfile_dir() -> str:
    import tempfile
    return tempfile.gettempdir()


def test_a_busy_writer_or_a_foreign_ledger_is_refused_not_opened_writable_on_the_history_path(rig):
    import fcntl
    import os
    rig.freeze("v1", "rel-main")
    fd = os.open(rig.state / "graph.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = disk(rig.state)
        error(rig.run("inspect", rig.sel(), expected=2)[0], "graph_busy")
        error(rig.run("project", rig.sel(), expected=2)[0], "graph_busy")
        assert disk(rig.state) == before
    finally:
        os.close(fd)
    foreign = rig.root / "foreign"
    foreign.mkdir()
    db = sqlite3.connect(foreign / "graph.sqlite3")
    db.execute("CREATE TABLE unrelated(x)")
    db.commit()
    db.close()
    (foreign / "graph.lock").write_bytes(b"")
    before = disk(foreign)
    error(rig.run("project", rig.sel(), state=foreign, expected=2)[0], "graph_state_invalid")
    assert disk(foreign) == before


def test_a_current_plan_with_a_hot_wal_still_recovers_through_the_writer_and_a_reader_still_refuses_it(rig):
    rig.freeze("v1", "rel-main")
    relation_ref = {"jobId": "rel-main", "inputDigest": rig.shared.jobs["rel-main"]["inputDigest"]}
    kill_writer(rig, ("UPDATE versions SET updated_at=?", "2099-01-01T00:00:00+00:00"))
    before = disk(rig.state)
    error(rig.run("inspect", rig.sel(), expected=2)[0], "graph_recovery_required")          # a reader never settles somebody else's WAL
    assert disk(rig.state) == before
    echoed, _ = rig.run("freeze", {**rig.sel(), "relation": relation_ref})                 # the writer opens, replays the WAL and answers
    assert echoed["state"] == "frozen" and echoed["next"] == "project"
    assert rig.run("inspect", rig.sel())[0]["state"] == "frozen"                            # the ledger is settled: readers work again


def test_a_ledger_with_a_missing_guard_trigger_or_a_foreign_schema_is_refused_before_any_writer_and_never_classified(rig):
    """Ownership/schema identity is proven (identity row AND the full table/trigger set) before a row is classified as absent, current or history, with the
    ledger untouched, whether the damage is in the main file or only in a hot WAL."""
    rig.freeze("v1", "rel-main")
    relation_ref = {"jobId": "rel-main", "inputDigest": rig.shared.jobs["rel-main"]["inputDigest"]}
    db = sqlite3.connect(rig.state / "graph.sqlite3", isolation_level=None)
    db.execute("DROP TRIGGER terminal_versions")
    db.close()
    loosen(rig)
    before = disk(rig.state)
    for command, body in (("inspect", rig.sel()), ("project", rig.sel()), ("recover", rig.sel()), ("freeze", {**rig.sel(), "relation": relation_ref})):
        error(rig.run(command, body, expected=2)[0], "ledger_version_unknown")
        assert disk(rig.state) == before, command
    # the same damage that exists only in a hot WAL (a writer that died before checkpointing)
    other = rig.root / "wal-ledger"
    shutil.copytree(rig.state, other)
    db = sqlite3.connect(other / "graph.sqlite3", isolation_level=None)
    db.execute("CREATE TRIGGER terminal_versions BEFORE UPDATE ON versions WHEN OLD.state IN ('ready','failed') BEGIN SELECT RAISE(ABORT,'terminal'); END")
    db.close()
    rig.state, kept = other, rig.state
    try:
        kill_writer(rig, ("CREATE TABLE intruder(x)",))
        before = disk(other)
        error(rig.run("project", rig.sel(), expected=2)[0], "ledger_version_unknown")
        error(rig.run("inspect", rig.sel(), expected=2)[0], "ledger_version_unknown")
        assert disk(other) == before
    finally:
        rig.state = kept
