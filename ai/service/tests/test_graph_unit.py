"""The read-only graph door, everything that needs no child process: all-or-nothing configuration, the version allowlist, the exit-code interpretation,
the allowlisted projection, the delivery rules (with a scripted process object) and the generated examples.

The behavior that needs a real service process (argv, environment, working directory, concurrency, deadlines, logs) lives in `test_graph_http.py`
with a test-owned stand-in command; the real installed `zoop-ai-graph` is exercised by `pipeline_tests/test_graph_real_cli.py` and the real Neo4j by
`scripts/graph_service_smoke.py`.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from graph_support import (EDGES, EVIDENCE, GRAPH_DIGEST, GRAPH_VARS, NODES, OTHER_VERSION, PAYLOAD_DIGEST, PRIVATE_KEYS, RELATION_DIGEST,
                           RELATION_JOB, VERSION, VERSIONS_SCHEMA, GraphWorkspace, error_output, focus_output, read_output, version_entry, view, withheld_output)
from zoop_ai_service import graph_access
from zoop_ai_service.config import GRAPH_SWITCH, ConfigError, load
from zoop_ai_service.graph_reads import GraphError, GraphReads
from zoop_ai_service.graph_runtime import interpret
from zoop_ai_service.graph_wire import GraphErrorEnvelope, GraphFocusResult, GraphRead, GraphVersionStatus
from zoop_ai_service.jobs import ApiError, Observation
from zoop_ai_service.relation_runtime import RelationGate
from zoop_ai_service.runtime import Outcome

BASE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"}
CREDENTIALS = ("ZOOP_GRAPH_USER", "ZOOP_GRAPH_PASSWORD")


def refused(env: dict[str, str]) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load(env)
    return caught.value


def without_graph(ws: GraphWorkspace) -> dict[str, str]:
    return {key: value for key, value in ws.env().items() if key not in (*GRAPH_VARS, *CREDENTIALS)}


# ---- configuration: all or nothing -------------------------------------------------------------------------------------

def test_without_any_graph_variable_the_feature_is_off_and_the_auth_variable_alone_does_not_switch_it_on(tmp_path):
    ws = GraphWorkspace(tmp_path)
    env = without_graph(ws)
    assert load(env).graph is None
    assert load({**env, "ZOOP_GRAPH_AUTH": "none"}).graph is None   # an operator shell may export it for the pipeline CLI
    assert load({**env, "ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": "u", "ZOOP_GRAPH_PASSWORD": "p"}).graph is None


def test_a_complete_group_loads_and_only_the_graph_child_gets_the_credentials(tmp_path):
    ws = GraphWorkspace(tmp_path, with_relation=True)
    config = load(ws.env())
    graph = config.graph
    assert graph is not None and graph.shared_gate and graph.state_dir == ws.graph_state and graph.versions_path == ws.versions
    assert dict(graph.child_env) == {**BASE_ENV, "ZOOP_STATE_DIR": str(ws.app_state), "ZOOP_AI_WORKER_STATE_DIR": str(ws.worker),
                                     "ZOOP_GRAPH_AUTH": "basic", "ZOOP_GRAPH_USER": ws.user, "ZOOP_GRAPH_PASSWORD": ws.password}
    # S1, S3 (and S2) children are built without them, so no other door can forward a graph credential.
    assert config.relation is not None
    for environment in (config.child_env, config.relation.child_env):
        assert not [key for key in environment if key.startswith("ZOOP_GRAPH_")]


def test_auth_none_hands_the_child_the_mode_and_nothing_else_and_a_group_without_s2_s3_does_not_share_their_gate(tmp_path):
    ws = GraphWorkspace(tmp_path, auth={"ZOOP_GRAPH_AUTH": "none"})
    graph = load(ws.env()).graph
    assert graph is not None and not graph.shared_gate
    assert dict(graph.child_env) == {**BASE_ENV, "ZOOP_STATE_DIR": str(ws.app_state), "ZOOP_AI_WORKER_STATE_DIR": str(ws.worker), "ZOOP_GRAPH_AUTH": "none"}


@pytest.mark.parametrize("name", GRAPH_VARS)
def test_a_partial_group_refuses_to_start_and_names_the_missing_variable(tmp_path, name):
    ws = GraphWorkspace(tmp_path)
    error = refused(ws.env(**{name: None}))
    assert (error.field, error.reason) == (name, "graph_group_incomplete")


def test_every_member_is_validated_when_any_is_present_and_no_value_is_ever_named(tmp_path):
    ws = GraphWorkspace(tmp_path)
    assert refused(ws.env(ZOOP_STATE_DIR=None)).field == "ZOOP_STATE_DIR"
    assert refused(ws.env(ZOOP_AI_SERVICE_GRAPH_COMMAND="relative/cli")).reason == "not_absolute_normalized"
    assert refused(ws.env(ZOOP_AI_SERVICE_GRAPH_COMMAND=str(ws.sources))).reason == "file_unusable"   # exists, is not executable
    for name in ("ZOOP_AI_GRAPH_STATE_DIR", "ZOOP_AI_GRAPH_RELATION_STATE_DIR", "ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR", "ZOOP_AI_GRAPH_INGESTION_STATE_DIR"):
        error = refused(ws.env(**{name: str(tmp_path / "absent")}))
        assert (error.field, error.reason) == (name, "directory_missing")
    for name in ("ZOOP_AI_SERVICE_GRAPH_SOURCES", "ZOOP_AI_SERVICE_GRAPH_CANONICAL", "ZOOP_AI_SERVICE_GRAPH_VERSIONS"):
        error = refused(ws.env(**{name: str(tmp_path / "absent.json")}))
        assert (error.field, error.reason) == (name, "file_unusable")
    link = tmp_path / "linked"
    link.symlink_to(ws.graph_state, target_is_directory=True)
    assert refused(ws.env(ZOOP_AI_GRAPH_STATE_DIR=str(link))).reason == "symlinked_component"
    error = refused(ws.env(ZOOP_GRAPH_PASSWORD="x" * 2001))
    assert (error.field, error.reason) == ("ZOOP_GRAPH_PASSWORD", "invalid") and str(error) == "ZOOP_GRAPH_PASSWORD" and "xxxx" not in repr(error)


def test_the_graph_roots_may_not_overlap_each_other_or_the_service_worker_and_app_roots(tmp_path):
    ws = GraphWorkspace(tmp_path)
    inner = ws.relation_state / "inner"
    inner.mkdir()
    ws.worker.mkdir(exist_ok=True)   # the S1 worker root exists in a running service; the graph root must be disjoint from it too
    for name, value in (("ZOOP_AI_GRAPH_STATE_DIR", str(ws.state)), ("ZOOP_AI_GRAPH_STATE_DIR", str(ws.worker)), ("ZOOP_AI_GRAPH_STATE_DIR", str(inner)),
                        ("ZOOP_AI_GRAPH_STATE_DIR", str(ws.ingestion_state)), ("ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR", str(ws.ingestion_state)),
                        ("ZOOP_STATE_DIR", str(ws.graph_state)), ("ZOOP_AI_GRAPH_STATE_DIR", str(tmp_path))):
        error = refused(ws.env(**{name: value}))
        assert error.reason in {"graph_roots_overlap", "overlaps_worker_state", "overlaps_app_state"}, (name, value, error.reason)


def test_the_graph_reads_exactly_the_ledgers_an_s3_group_of_the_same_process_writes(tmp_path):
    ws = GraphWorkspace(tmp_path, with_relation=True)
    other = tmp_path / "other"
    other.mkdir()
    for name in ("ZOOP_AI_GRAPH_RELATION_STATE_DIR", "ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR", "ZOOP_AI_GRAPH_INGESTION_STATE_DIR"):
        error = refused(ws.env(**{name: str(other)}))
        assert (error.field, error.reason) == (name, "graph_source_inconsistent")
    registry = tmp_path / "other-sources.json"
    registry.write_text("{}")
    error = refused(ws.env(ZOOP_AI_SERVICE_GRAPH_SOURCES=str(registry)))
    assert (error.field, error.reason) == ("ZOOP_AI_SERVICE_GRAPH_SOURCES", "graph_source_inconsistent")
    assert load(ws.env()).graph is not None


def test_credentials_are_required_for_basic_forbidden_for_none_and_the_mode_is_closed(tmp_path):
    ws = GraphWorkspace(tmp_path)
    assert (refused(ws.env(ZOOP_GRAPH_USER=None)).field, refused(ws.env(ZOOP_GRAPH_USER=None)).reason) == ("ZOOP_GRAPH_USER", "missing")
    assert refused(ws.env(ZOOP_GRAPH_PASSWORD="")).field == "ZOOP_GRAPH_PASSWORD"
    assert refused(ws.env(ZOOP_GRAPH_USER="u" * 201)).reason == "invalid"
    error = refused(ws.env(ZOOP_GRAPH_AUTH="none"))   # the user and password are still in the environment
    assert (error.field, error.reason) == ("ZOOP_GRAPH_USER", "graph_auth_unexpected")
    error = refused(ws.env(ZOOP_GRAPH_AUTH="token"))
    assert (error.field, error.reason) == ("ZOOP_GRAPH_AUTH", "invalid")


# ---- the version allowlist ---------------------------------------------------------------------------------------------

def document(*entries: Any, **extra: Any) -> str:
    return json.dumps({"schemaVersion": VERSIONS_SCHEMA, "versions": list(entries), **extra})


@pytest.mark.parametrize("content,reason", [
    ("{not json", "version_allowlist_not_json"),
    ("[]", "version_allowlist_shape"),
    (json.dumps({"schemaVersion": "wrong", "versions": []}), "version_allowlist_shape"),
    (document(extra=1), "version_allowlist_shape"),
    (document({"principal": "grapher"}), "version_allowlist_entry_shape"),
    (document({**version_entry(), "storeId": "store-1"}), "version_allowlist_entry_shape"),
    (document(version_entry(graph="short")), "version_allowlist_entry_invalid"),
    (document(version_entry(payload="A" * 64)), "version_allowlist_entry_invalid"),
    (document(version_entry(version="bad id")), "version_allowlist_entry_invalid"),
    (document(version_entry(version="x" * 121)), "version_allowlist_entry_invalid"),
    (document(version_entry(sourceRelation={"jobId": RELATION_JOB})), "version_allowlist_entry_invalid"),
    (document(version_entry(sourceRelation={"jobId": "bad job", "inputDigest": RELATION_DIGEST})), "version_allowlist_entry_invalid"),
    (document(version_entry(sourceRelation="x")), "version_allowlist_entry_invalid"),
    (document(version_entry(principal="nobody")), "version_allowlist_unknown_principal"),
    (document(version_entry(), version_entry(graph="d" * 64)), "version_allowlist_duplicate"),
    ('{"schemaVersion":"%s","versions":[],"versions":[]}' % VERSIONS_SCHEMA, "version_allowlist_not_json"),
])
def test_the_version_allowlist_is_strict_and_fails_closed_at_start(tmp_path, content, reason):
    ws = GraphWorkspace(tmp_path)
    ws.versions.write_text(content)
    error = refused(ws.env())
    assert (error.field, error.reason) == ("ZOOP_AI_SERVICE_GRAPH_VERSIONS", reason)


def test_the_allowlist_binds_a_principal_to_exact_versions_and_digests_and_is_read_fresh(tmp_path):
    path = tmp_path / "versions.json"
    path.write_text(document(version_entry(), version_entry("alpha", OTHER_VERSION, "d" * 64, "e" * 64,
                                                            sourceRelation={"jobId": RELATION_JOB, "inputDigest": RELATION_DIGEST})))
    access = graph_access.load(path, ["grapher", "alpha"])
    pinned = access.find("alpha", OTHER_VERSION)
    assert access.find("grapher", VERSION) == graph_access.Entry("grapher", VERSION, GRAPH_DIGEST, PAYLOAD_DIGEST)
    assert pinned is not None and (pinned.source_job_id, pinned.source_input_digest) == (RELATION_JOB, RELATION_DIGEST)
    assert access.find("alpha", VERSION) is None and access.find("grapher", OTHER_VERSION) is None   # another principal's version is not yours
    path.write_text(document())
    assert graph_access.load(path, ["grapher"]).find("grapher", VERSION) is None
    path.unlink()
    with pytest.raises(graph_access.AccessError) as caught:
        graph_access.load(path, ["grapher"])
    assert caught.value.code == "version_allowlist_unreadable"


# ---- the exit-code interpretation ----------------------------------------------------------------------------------------

def encode(value: Any) -> bytes:
    return json.dumps(value).encode()


def test_exit_zero_is_a_current_result_and_exit_two_a_withheld_result_or_an_error_object():
    current = interpret(0, encode(read_output()))
    assert (current.kind, current.exit_code, current.result["versionId"]) == ("result", 0, VERSION)
    withheld = interpret(2, encode(withheld_output()))
    assert (withheld.kind, withheld.exit_code) == ("result", 2)
    refusal = interpret(2, encode(error_output("version_not_ready", {"state": "frozen"})))
    assert (refusal.kind, refusal.code, refusal.exit_code) == ("error", "version_not_ready", 2)
    assert refusal.result["error"]["detail"] == {"state": "frozen"}   # kept: the state of a not-ready version travels in the detail


@pytest.mark.parametrize("code,raw", [
    (0, encode(withheld_output())), (2, encode(read_output())), (0, encode(error_output("graph_busy"))), (3, encode(read_output())),
    (1, b""), (0, b"not json"), (0, b"[]"), (0, encode({**read_output(), "schemaVersion": "zoop-relation-s3"})),
    (0, encode({**read_output(), "versionId": None})), (0, encode({**read_output(), "delivery": None})),
    (2, encode(error_output("Not A Code"))), (2, encode({"schemaVersion": "zoop-graph-projection-1", "error": "x"})),
    (2, b"\xff\xfe"),
])
def test_anything_else_is_abnormal_and_never_read_as_a_result(code, raw):
    assert interpret(code, raw).kind == "abnormal"


# ---- the allowlisted projection --------------------------------------------------------------------------------------------

def test_the_projection_drops_what_the_application_may_not_read():
    for out in (read_output(), focus_output()):
        wire = GraphRead.model_validate(out).wire()
        text = json.dumps(wire)
        for private in ("s2-private-upstream", "reviewDigest", "attempts", "audit", "canonical", "counts", "provenance", "authority", "next"):
            assert private not in text, private
        assert set(wire) <= {"schemaVersion", "versionId", "state", "publication", "delivery", "usage", "digests", "source", "verification", "focus", "graph",
                             "evidence"}


@pytest.mark.parametrize("mutate", [
    lambda out: out.pop("usage"),
    lambda out: out["usage"].update(providerCalls=1),
    lambda out: out["usage"].update(modelCalls=True),
    lambda out: out["delivery"].update(status="maybe"),
    lambda out: out.update(state="published"),
    lambda out: out.update(publication="published"),
    lambda out: out["verification"].update(marker="unchecked"),
    lambda out: out["verification"].update(nodes="6"),
    lambda out: out["digests"].update(graph="short"),
    lambda out: out["graph"]["edges"][0].pop("evidence"),
    lambda out: out["graph"]["edges"][0].update(direction="both"),
    lambda out: out["graph"]["edges"][0]["subject"].update(kind="person"),
    lambda out: out["evidence"][0].pop("documentId"),
    lambda out: out["evidence"][0].update(start="0"),
    lambda out: out["graph"]["nodes"][0].update(kind="person"),
])
def test_the_projection_fails_closed_on_a_missing_or_mistyped_field(mutate):
    out = read_output()
    mutate(out)
    with pytest.raises(ValidationError):
        GraphRead.model_validate(out)


# ---- delivery, with a scripted process ---------------------------------------------------------------------------------------

def result(out: dict, code: int = 0) -> Outcome:
    return Outcome("result", result=out, exit_code=code)


def refusal(code: str, detail: dict | None = None) -> Outcome:
    return Outcome("error", result=error_output(code, detail), code=code, exit_code=2)


class Scripted:
    """The process object of `GraphReads`: answers what the test queued and records what it was asked."""

    def __init__(self, *outcomes: Outcome, on_call: Callable[[], None] | None = None):
        self.outcomes, self.calls, self.on_call = list(outcomes), [], on_call

    def _next(self) -> Outcome:
        if self.on_call:
            self.on_call()
        return self.outcomes.pop(0)

    def read(self, version_id: str) -> Outcome:
        self.calls.append(("read", version_id))
        return self._next()

    def focus(self, version_id: str, company_id: str, depth: int) -> Outcome:
        self.calls.append(("focus", version_id, company_id, depth))
        return self._next()


def reads(tmp_path: Path, *outcomes: Outcome, gate: RelationGate | None = None, versions: list[dict] | None = None, busy_wait: float = 0.05,
          on_call: Callable[[], None] | None = None) -> tuple[GraphReads, Scripted, GraphWorkspace]:
    ws = GraphWorkspace(tmp_path, versions=versions)
    process = Scripted(*outcomes, on_call=on_call)
    return GraphReads(load(ws.env()), process, gate, busy_wait=busy_wait), process, ws


def body(reply) -> dict:
    assert reply.status == 200
    return reply.body.wire()


def refusal_of(call: Callable[[], Any]) -> GraphError:
    with pytest.raises(GraphError) as caught:
        call()
    return caught.value


def test_a_current_status_carries_identity_verification_and_no_content(tmp_path):
    service, process, _ = reads(tmp_path, result(read_output()))
    wire = body(service.status("grapher", VERSION, Observation()))
    assert wire["schemaVersion"] == "zoop-ai-internal-graph-1" and wire["publication"] == "not-published"
    assert (wire["versionId"], wire["state"], wire["delivery"]) == (VERSION, "ready", {"state": "current", "reason": None})
    assert wire["verification"] == {"graphDigest": GRAPH_DIGEST, "payloadDigest": PAYLOAD_DIGEST, "nodes": len(NODES), "edges": len(EDGES)}
    assert not {"graph", "evidence", "focus"} & set(wire) and process.calls == [("read", VERSION)]
    assert json.loads(json.dumps(wire)) == wire and not PRIVATE_KEYS & (set(wire) - {"versionId"})


@pytest.mark.parametrize("company,depth", [("kr-000100", 1), ("kr-000100", 2), ("kr-000100", 3), ("kr-000400", 1), ("kr-000400", 2), ("kr-000400", 3),
                                           ("kr-000300", 3)])
def test_a_current_focus_is_exactly_the_verified_neighbourhood_with_only_the_evidence_it_references(tmp_path, company, depth):
    service, process, _ = reads(tmp_path, result(focus_output(company=company, depth=depth)))
    wire = body(service.focus("grapher", VERSION, company, depth, Observation()))
    expected = view(company, depth)
    assert wire["focus"] == {"companyId": company, "depth": depth, "found": True}
    assert wire["graph"]["nodes"] == expected["nodes"] and [e["relationId"] for e in wire["graph"]["edges"]] == [e["relationId"] for e in expected["edges"]]
    referenced = {i for e in expected["edges"] for i in (*e["evidence"]["relation"], *e["evidence"]["validity"])}
    assert {e["evidenceId"] for e in wire["evidence"]} == referenced <= {e["evidenceId"] for e in EVIDENCE}
    assert process.calls == [("focus", VERSION, company, depth)]
    for edge in wire["graph"]["edges"]:   # the edge allowlist: exactly these keys, and `from` / `object` are the documented names
        assert set(edge) == {"relationId", "type", "direction", "connection", "subject", "object", "businessScope", "productScope", "validity", "countries",
                             "path", "evidence", "sourceRelationCandidateIds"}
        assert set(edge["validity"]) == {"from", "until"}


def test_an_absent_company_is_a_verified_not_found_with_empty_content(tmp_path):
    service, _, _ = reads(tmp_path, result(focus_output(company="kr-999999", depth=2)))
    wire = body(service.focus("grapher", VERSION, "kr-999999", 2, Observation()))
    assert wire["delivery"]["state"] == "current" and wire["focus"]["found"] is False
    assert wire["graph"] == {"nodes": [], "edges": []} and wire["evidence"] == []


@pytest.mark.parametrize("code", ["source_unauthorized", "canonical_mapping_changed", "graph_version_corrupt", "upstream_changed", "review_revision_changed",
                                  "graph_store_identity_mismatch"])
def test_a_withheld_result_is_a_200_with_identity_state_and_a_reason_and_nothing_else(tmp_path, code):
    service, _, _ = reads(tmp_path, result(withheld_output(code=code), 2), result(withheld_output(code=code), 2))
    status = body(service.status("grapher", VERSION, Observation()))
    focus = body(service.focus("grapher", VERSION, "kr-000100", 2, Observation()))
    assert status["delivery"] == focus["delivery"] == {"state": "withheld", "reason": code}
    assert status["verification"] is None and (focus["verification"], focus["graph"], focus["evidence"]) == (None, None, None)
    assert focus["focus"] == {"companyId": "kr-000100", "depth": 2, "found": None} and status["publication"] == "not-published"
    for text in (json.dumps(status), json.dumps(focus)):
        assert "kr-000300" not in text and "ev-" not in text and "rel-" not in text and GRAPH_DIGEST not in text


def test_a_version_that_is_not_listed_is_refused_before_any_child_with_one_answer(tmp_path):
    service, process, ws = reads(tmp_path, result(read_output()), versions=[version_entry(), version_entry("alpha", OTHER_VERSION)])
    unlisted = [service.status, lambda *args: service.focus(*args[:2], "kr-000100", 1, args[2])]
    answers = []
    for call, owner, version in ((unlisted[0], "grapher", OTHER_VERSION),      # exists, but listed for another principal
                                 (unlisted[0], "grapher", "graph-never-existed"),
                                 (unlisted[0], "beta", VERSION),               # a principal without any entry
                                 (unlisted[1], "grapher", OTHER_VERSION)):
        error = refusal_of(lambda: call(owner, version, Observation()))
        assert (error.status, error.code) == (403, "version_not_allowed")
        answers.append(error.envelope("req-1").wire())
    assert all(answer == answers[0] for answer in answers) and process.calls == []


def test_the_listed_digests_must_equal_the_ones_the_pipeline_reports(tmp_path):
    pin = {"jobId": RELATION_JOB, "inputDigest": RELATION_DIGEST}
    cases = [(read_output(graph="1" * 64), None, "version_pin_mismatch"), (read_output(payload="2" * 64), None, "version_pin_mismatch"),
             (read_output(relation=("another-job", RELATION_DIGEST)), pin, "source_pin_mismatch"),
             (read_output(relation=(RELATION_JOB, "3" * 64)), pin, "source_pin_mismatch")]
    seen_cases: list[str] = []
    for out, source, reason in cases:
        entry = version_entry(**({} if source is None else {"sourceRelation": source}))
        service, _, _ = reads(tmp_path / f"{reason}-{len(seen_cases)}", result(out), versions=[entry])
        seen_cases.append(reason)
        wire = body(service.status("grapher", VERSION, Observation()))
        assert wire["delivery"] == {"state": "withheld", "reason": reason} and wire["verification"] is None
    service, _, _ = reads(tmp_path / "pinned", result(read_output()), versions=[version_entry(sourceRelation=pin)])
    assert body(service.status("grapher", VERSION, Observation()))["delivery"]["state"] == "current"


def test_an_entry_removed_or_changed_while_the_child_ran_stops_delivery(tmp_path):
    for index, change in enumerate((document(), document(version_entry(graph="9" * 64)))):
        service, _, ws = reads(tmp_path / str(index), result(focus_output()))
        # the scripted process rewrites the server-owned file, as an operator would, while the "child" runs
        service.process.on_call = lambda ws=ws, change=change: ws.versions.write_text(change)
        error = refusal_of(lambda: service.focus("grapher", VERSION, "kr-000100", 1, Observation()))
        assert (error.status, error.code) == (403, "version_not_allowed")


def test_an_unreadable_allowlist_closes_with_a_retryable_503_and_no_child(tmp_path):
    service, process, ws = reads(tmp_path, result(read_output()))
    ws.versions.unlink()
    seen = Observation()
    error = refusal_of(lambda: service.status("grapher", VERSION, seen))
    assert (error.status, error.code, seen.problem) == (503, "service_configuration_invalid", "version_allowlist_unreadable")
    assert error.envelope("r").error.retryable and process.calls == []


@pytest.mark.parametrize("code,status,public", [
    ("graph_busy", 503, "runtime_busy"), ("relation_busy", 503, "runtime_busy"), ("extraction_busy", 503, "runtime_busy"), ("ingestion_busy", 503, "runtime_busy"),
    ("graph_unavailable", 503, "runtime_unavailable"), ("graph_query_failed", 503, "runtime_unavailable"),
    ("graph_auth_failed", 503, "service_configuration_invalid"), ("graph_auth_unconfigured", 503, "service_configuration_invalid"),
    ("graph_store_unbound", 503, "service_configuration_invalid"), ("graph_state_missing", 503, "service_configuration_invalid"),
    ("graph_state_invalid", 503, "service_configuration_invalid"), ("canonical_registry_invalid", 503, "service_configuration_invalid"),
    ("state_namespace_conflict", 503, "service_configuration_invalid"), ("relation_state_missing", 503, "service_configuration_invalid"),
    ("input_or_configuration_invalid", 503, "service_configuration_invalid"), ("persistence_failed", 503, "service_configuration_invalid"),
    ("version_not_found", 404, "version_not_found"), ("something_new", 500, "internal_error"),
])
def test_pipeline_refusals_map_to_stable_codes_and_never_to_an_empty_graph(tmp_path, code, status, public):
    service, _, _ = reads(tmp_path, refusal(code))
    seen = Observation()
    error = refusal_of(lambda: service.status("grapher", VERSION, seen))
    assert (error.status, error.code) == (status, public)
    assert error.runtime_code == (code if public in {"runtime_busy", "runtime_unavailable", "version_not_found", "internal_error"} else None)
    assert error.envelope("r").error.retryable == (public in {"runtime_busy", "runtime_unavailable", "service_configuration_invalid"})
    if public == "service_configuration_invalid":
        assert seen.problem == code
    if status == 503:
        assert error.headers["Retry-After"]


def test_a_version_that_is_not_ready_is_a_withheld_answer_with_its_state(tmp_path):
    for state in ("frozen", "reserved", "unknown", "failed"):
        service, _, _ = reads(tmp_path / state, refusal("version_not_ready", {"state": state}))
        wire = body(service.status("grapher", VERSION, Observation()))
        assert (wire["state"], wire["delivery"]) == (state, {"state": "withheld", "reason": "version_not_ready"}) and wire["verification"] is None
    for index, detail in enumerate((None, {"state": "ready"}, {"state": "published"}, {"state": 5})):
        service, _, _ = reads(tmp_path / f"bad{index}", refusal("version_not_ready", detail))
        assert refusal_of(lambda: service.status("grapher", VERSION, Observation())).code == "runtime_unavailable"


@pytest.mark.parametrize("kind", ["abnormal", "timeout", "unavailable", "abandoned"])
def test_a_child_that_did_not_answer_is_a_retryable_503(tmp_path, kind):
    service, _, _ = reads(tmp_path, Outcome(kind, exit_code=None))
    error = refusal_of(lambda: service.status("grapher", VERSION, Observation()))
    assert (error.status, error.code) == (503, "runtime_unavailable") and error.envelope("r").error.retryable


def test_a_result_that_does_not_belong_to_the_request_or_is_incomplete_is_never_delivered(tmp_path):
    cases = [(lambda: read_output(OTHER_VERSION), "status", 500, "runtime_binding_mismatch"),
             (lambda: focus_output(company="kr-000300", depth=1), "focus", 500, "runtime_binding_mismatch"),
             (lambda: focus_output(company="kr-000100", depth=2), "focus", 500, "runtime_binding_mismatch")]
    for index, (make, route, status, code) in enumerate(cases):
        service, _, _ = reads(tmp_path / str(index), result(make()))
        # the scripted process does not echo: the request names kr-000100 at depth 1, the answer names something else
        error = refusal_of(lambda: service.status("grapher", VERSION, Observation()) if route == "status" else service.focus("grapher", VERSION, "kr-000100", 1, Observation()))
        assert (error.status, error.code) == (status, code)
    broken = [lambda o: o.pop("verification"), lambda o: o.pop("digests"), lambda o: o.pop("source"), lambda o: o["verification"].update(graphDigest="7" * 64),
              lambda o: o.update(state="frozen"), lambda o: o["usage"].update(modelCalls=1), lambda o: o.pop("focus"), lambda o: o.pop("graph"), lambda o: o.pop("evidence")]
    for index, mutate in enumerate(broken):
        out = focus_output(company="kr-000100", depth=1)
        mutate(out)
        service, _, _ = reads(tmp_path / f"broken{index}", result(out))
        error = refusal_of(lambda: service.focus("grapher", VERSION, "kr-000100", 1, Observation()))
        assert (error.status, error.code) == (503, "runtime_unavailable"), index


def test_the_slot_limit_and_the_shared_gate_answer_busy_and_never_start_a_child(tmp_path):
    gate = RelationGate()
    service, process, _ = reads(tmp_path / "gated", result(read_output()), gate=gate)
    assert gate.acquire(0)   # an S2/S3 child of this process holds the gate
    error = refusal_of(lambda: service.status("grapher", VERSION, Observation()))
    assert (error.status, error.code, error.headers["Retry-After"]) == (503, "runtime_busy", "2") and process.calls == []
    gate.release()
    assert body(service.status("grapher", VERSION, Observation()))["delivery"]["state"] == "current"   # the gate is released again after a read
    service, process, _ = reads(tmp_path / "slots", result(read_output()))
    taken = [service._slots.acquire(blocking=False) for _ in range(4)]
    assert all(taken)
    error = refusal_of(lambda: service.status("grapher", VERSION, Observation()))
    assert (error.status, error.code) == (503, "service_busy") and process.calls == []
    for _ in taken:
        service._slots.release()


def test_without_a_shared_gate_reads_do_not_wait_for_each_other(tmp_path):
    started, release = threading.Event(), threading.Event()

    def hold() -> None:
        started.set()
        assert release.wait(10)

    service, _, ws = reads(tmp_path, result(read_output()))
    first = Scripted(result(read_output()), on_call=hold)
    service.process = first
    worker = threading.Thread(target=lambda: service.status("grapher", VERSION, Observation()))
    worker.start()
    assert started.wait(10)
    service.process = Scripted(result(read_output()))
    assert body(service.status("grapher", VERSION, Observation()))["delivery"]["state"] == "current"   # while another read is in flight
    release.set()
    worker.join(10)


# ---- freshness of the allowlist: a revoked entry never starts a child and nothing of an answer outlives it -------------------------------------

EMPTY_VERSIONS = json.dumps({"schemaVersion": VERSIONS_SCHEMA, "versions": []})


def test_an_entry_revoked_while_a_request_waits_for_the_gate_starts_no_child(tmp_path):
    gate = RelationGate()
    service, process, ws = reads(tmp_path, result(read_output()), gate=gate, busy_wait=10.0)
    assert gate.acquire(0)   # an S2/S3 child of this process holds the gate
    outcome: dict[str, Any] = {}

    def request() -> None:
        try:
            outcome["reply"] = service.status("grapher", VERSION, Observation())
        except GraphError as error:
            outcome["error"] = error

    waiting = threading.Thread(target=request)
    waiting.start()
    waiting.join(0.5)
    assert waiting.is_alive() and process.calls == []   # listed when it arrived, now parked on the gate
    ws.versions.write_text(EMPTY_VERSIONS)               # the operator revokes while it waits
    gate.release()
    waiting.join(10)
    assert not waiting.is_alive() and "reply" not in outcome
    assert (outcome["error"].status, outcome["error"].code) == (403, "version_not_allowed") and process.calls == []   # zero children


@pytest.mark.parametrize("answer", [
    pytest.param(result(read_output()), id="current"), pytest.param(result(withheld_output(), 2), id="withheld"),
    pytest.param(refusal("version_not_ready", {"state": "frozen"}), id="not-ready-state"), pytest.param(refusal("version_not_found"), id="not-found"),
    pytest.param(refusal("graph_busy"), id="busy"), pytest.param(refusal("graph_state_invalid"), id="configuration"),
    pytest.param(refusal("something_new"), id="unknown-code"), pytest.param(Outcome("abnormal", exit_code=3), id="abnormal")])
def test_an_entry_revoked_before_the_answer_is_used_returns_only_the_refusal_whatever_the_answer_was(tmp_path, answer):
    service, process, ws = reads(tmp_path, answer, on_call=None)
    process.on_call = lambda: ws.versions.write_text(EMPTY_VERSIONS)
    for call in (lambda: service.status("grapher", VERSION, Observation()), lambda: service.focus("grapher", VERSION, "kr-000100", 1, Observation())):
        process.outcomes = [answer]
        ws.write_versions([version_entry()])
        error = refusal_of(call)
        assert (error.status, error.code, error.runtime_code) == (403, "version_not_allowed", None)   # no state, reason, 404 or busy hint of the version
    assert len(process.calls) == 2


def test_an_entry_revoked_just_before_the_validated_content_is_built_returns_no_content(tmp_path):
    for operation in ("status", "focus"):
        out = read_output() if operation == "status" else focus_output(company="kr-000100", depth=1)
        service, process, ws = reads(tmp_path / operation, result(out))
        listed = service._still_listed
        reads_so_far: list[int] = []

        def watched(entry, seen, listed=listed, reads_so_far=reads_so_far, ws=ws) -> None:
            reads_so_far.append(1)
            if len(reads_so_far) == 3:   # 1: before the child starts, 2: when it answered, 3: the last read before the content is built
                ws.versions.write_text(EMPTY_VERSIONS)
            listed(entry, seen)

        service._still_listed = watched
        call = (lambda: service.status("grapher", VERSION, Observation())) if operation == "status" \
            else (lambda: service.focus("grapher", VERSION, "kr-000100", 1, Observation()))
        error = refusal_of(call)
        assert (error.status, error.code) == (403, "version_not_allowed") and len(reads_so_far) == 3 and len(process.calls) == 1


# ---- errors and the generated examples ----------------------------------------------------------------------------------------

def test_graph_errors_use_their_own_envelope_without_a_message(tmp_path):
    error = GraphError(503, "runtime_busy", runtime_code="graph_busy", retry_after=2)
    assert isinstance(error, ApiError)
    wire = error.envelope("req-1").wire()
    assert wire == {"schemaVersion": "zoop-ai-internal-graph-1", "error": {"code": "runtime_busy", "retryable": True, "requestId": "req-1",
                                                                              "runtimeCode": "graph_busy", "field": None}}
    assert GraphError(403, "version_not_allowed").envelope("r").error.retryable is False


def test_every_authored_graph_example_validates_through_the_wire_models_and_withheld_ones_carry_no_content():
    spec = json.loads((Path(__file__).resolve().parents[3] / "docs/api/internal-ai-openapi.json").read_text(encoding="utf-8"))
    found: list[dict] = []

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("schemaVersion") == "zoop-ai-internal-graph-1":
                found.append(node)
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect({path: item for path, item in spec["paths"].items() if "graph-versions" in path})
    assert len(found) >= 10
    for value in found:
        if "error" in value:
            GraphErrorEnvelope.model_validate(value)
        elif "focus" in value:
            model = GraphFocusResult.model_validate(value)
            assert (model.delivery.state == "withheld") == (model.graph is None and model.evidence is None and model.verification is None)
        else:
            model = GraphVersionStatus.model_validate(value)
            assert (model.delivery.state == "withheld") == (model.verification is None)
        if "delivery" in value:
            assert value["publication"] == "not-published"
