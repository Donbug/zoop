"""Behavior tests of the zoop-ai-graph tool baseline (record/score/mutator/fingerprint plumbing).

Every timing here is a FAKE clock tick chosen by the test and every tool answer is a TEST DOUBLE derived from the hand-authored expectation or deliberately
broken. Nothing in this file is a benchmark number and no process, Neo4j or network is involved."""
import copy
import importlib.util
import io
import contextlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from zoop_eval import graph_tool as gt
from zoop_eval.contracts import Rejected

from support import Case

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "graph-tool"
QUERIES, QUERIES_SHA = gt.load_queries(FIXTURES / "queries.json")
EXPECTED = json.loads((FIXTURES / "expected.json").read_text("utf-8"))
MANIFEST = {"schemaVersion": gt.SCHEMA_MANIFEST, "runId": "gtbtest", "owned": False, "stateDir": "/nonexistent-secret-path/graph",
            "relationStateDir": "/nonexistent-secret-path/relation", "extractionStateDir": "/nonexistent-secret-path/extraction",
            "ingestionStateDir": "/nonexistent-secret-path/ingestion", "sources": "/nonexistent-secret-path/sources.json",
            "canonical": "/nonexistent-secret-path/canonical.json", "neo4jLoopbackPort": 7687,
            "versions": {"main": "gtbtest-main", "split": "gtbtest-split"}, "worldDigest": "0" * 64}
META = {"measurementId": "gtm-test", "recordedAt": "2026-10-15T00:00:00+00:00", "clock": "fake tick", "timeoutSeconds": 1.0, "invoker": "test double",
        "system": {"tool": "test double"}}
STEP = 2_000_000   # a fake tick, not a measurement
CASE_BY_KEY = {(c["version"], c["command"], c.get("companyId"), c.get("depth")): c["caseId"] for c in QUERIES["cases"]}
VERSION_OF_ID = {v: k for k, v in MANIFEST["versions"].items()}
CASES = {c["caseId"]: c for c in QUERIES["cases"]}
WITHHELD_CODE = {"grant-disabled": "source_unauthorized", "grant-revision-changed": "grant_revision_changed", "canonical-topic-removed": "canonical_mapping_changed"}
USAGE = {"providerCalls": 0, "modelCalls": 0}
OWNER_MARKER = ".zoop-graph-tool-owned"   # the marker file `prepare` writes into the owned root (content = run id)
REGISTRY_NAMES = ("sources.json", "canonical.json")


def edge_json(e):
    kinds = EXPECTED["nodeKinds"]
    return {"relationId": "rel-test", "type": e["type"], "direction": e["direction"], "connection": e["connection"],
            "subject": {"kind": kinds[e["subject"]], "id": e["subject"]}, "object": {"kind": kinds[e["object"]], "id": e["object"]},
            "businessScope": None, "productScope": None, "validity": {"from": e["validFrom"], "until": e["validUntil"]}, "countries": [],
            "path": {"companyIds": list(e["pathCompanyIds"])}, "evidence": {"relation": ["ev-1"], "validity": [], "steps": [[], []]}, "sourceRelationCandidateIds": []}


def cli_doc(case_id):
    case, expect = CASES[case_id], EXPECTED["cases"][case_id]
    if case["command"] == "inspect":
        return {"schemaVersion": gt.PROJECTION_SCHEMA, "state": expect["state"], "counts": {"nodes": {"company": expect["nodeCount"]}, "edges": {"SUPPLIES": expect["edgeCount"]}},
                "digests": {"payload": "a" * 64, "graph": "b" * 64}, "usage": USAGE}
    nodes = []
    for ident, distance in expect["nodes"].items():
        node = {"kind": EXPECTED["nodeKinds"][ident], "id": ident}
        if case["command"] == "focus":
            node["distance"] = distance
        nodes.append(node)
    edges = [edge_json(EXPECTED["edgeDefs"][r]) for r in expect["edges"]]
    doc = {"schemaVersion": gt.PROJECTION_SCHEMA, "state": "ready", "publication": "not-published", "delivery": {"status": "current", "authority": "test double"},
           "graph": {"nodes": nodes, "edges": edges}, "evidence": [], "verification": {"marker": "matched", "nodes": len(nodes), "edges": len(edges)},
           "digests": {"payload": "a" * 64, "graph": "b" * 64}, "usage": USAGE}
    if case["command"] == "focus":
        doc["focus"] = {"companyId": case["companyId"], "depth": case["depth"], "found": expect["found"]}
    return doc


def inv(doc, code=0):
    return gt.Invocation(code, json.dumps(doc).encode(), 0)


def withheld(code):
    return inv({"schemaVersion": gt.PROJECTION_SCHEMA, "state": "ready", "publication": "not-published", "delivery": {"status": "withheld", "code": code}, "usage": USAGE}, 2)


def refusal(code):
    return inv({"schemaVersion": gt.PROJECTION_SCHEMA, "error": {"code": code}}, 2)


class Fake:
    """Fake clock and fake tool. `edit(index, case_id, doc)` may return a replacement document, an Invocation or None."""

    def __init__(self, step=lambda index: STEP, edit=None):
        self.now, self.index, self.step, self.edit, self.active, self.calls, self.restored = 0, 0, step, edit, None, [], 0

    def clock(self):
        return self.now

    def mutate(self, name):
        self.active = name

        def restore():
            self.active, self.restored = None, self.restored + 1
        return restore

    def invoke(self, command, stdin):
        body = json.loads(stdin)
        index, self.index = self.index, self.index + 1
        self.calls.append((command, body))
        self.now += self.step(index)
        if self.active:
            return withheld(WITHHELD_CODE[self.active])
        if body["versionId"].endswith("-absent"):
            return refusal("version_not_found")
        case_id = CASE_BY_KEY.get((VERSION_OF_ID[body["versionId"]], command, body.get("companyId"), body.get("depth")))
        if case_id is None:
            return refusal("input_or_configuration_invalid")
        doc = cli_doc(case_id)
        out = self.edit(index, case_id, doc) if self.edit else None
        if isinstance(out, gt.Invocation):
            return out
        return inv(out if out is not None else doc)


def measure(fake=None, repeats=3, warmups=1, **kwargs):
    fake = fake or Fake()
    run = gt.run_measurement(manifest=MANIFEST, queries=QUERIES, queries_sha256=QUERIES_SHA, invoke=fake.invoke, repeats=repeats, warmups=warmups, meta=META,
                             clock=fake.clock, **kwargs)
    return json.loads(json.dumps(run))   # what a recorded file round-trips to


def score(run, expected=EXPECTED, queries=QUERIES, sha=QUERIES_SHA):
    return gt.score_run(copy.deepcopy(run), queries, sha, copy.deepcopy(expected))


def tamper(case_id, change, only_once=False):
    done = []

    def edit(index, got, doc):
        if got == case_id and not (only_once and done):
            done.append(index)
            return change(doc)
        return None
    return edit


def case_row(result, case_id):
    return next(r for r in result["cases"] if r["caseId"] == case_id)


def ok(block):
    return block["num"], block["den"]


class ExpectationIsIndependentOfTheTool(Case):
    """The hand-authored gold equals the documented focus rule applied to the authored edge facts (not to any tool output)."""
    VERSION_EDGES = {"main": ["ab", "cb", "ca", "dc", "be", "bt"], "split": ["sab", "sdc"]}

    def neighborhood(self, version, anchor, depth):
        defs, edges = EXPECTED["edgeDefs"], self.VERSION_EDGES[version]
        adjacency = defaultdict(set)
        for ref in edges:
            adjacency[defs[ref]["subject"]].add(defs[ref]["object"])
            adjacency[defs[ref]["object"]].add(defs[ref]["subject"])
        if anchor not in adjacency:
            return None
        distance, frontier = {anchor: 0}, [anchor]
        for step in range(1, (depth or 0) + 1):
            following = []
            for node in frontier:
                for other in sorted(adjacency[node]):
                    if other not in distance:
                        distance[other] = step
                        following.append(other)
            frontier = following
        if depth is None:
            return {n: None for n in adjacency}, list(edges)
        shown = [r for r in edges if min(distance.get(defs[r]["subject"], 99), distance.get(defs[r]["object"], 99)) <= depth - 1]
        return distance, shown

    def test_every_neighborhood_case_matches_an_independent_bfs_over_the_facts(self):
        for case in QUERIES["cases"]:
            expect = EXPECTED["cases"][case["caseId"]]
            if expect["kind"] != "neighborhood":
                continue
            found = self.neighborhood(case["version"], case.get("companyId", "kr-000050"), case.get("depth"))
            with self.subTest(case=case["caseId"]):
                if found is None:
                    self.assertEqual((expect["found"], expect["nodes"], expect["edges"]), (False, {}, []))
                    continue
                distance, shown = found
                self.assertTrue(expect["found"])
                self.assertEqual(expect["nodes"], distance)
                self.assertEqual(sorted(expect["edges"]), sorted(shown))

    def test_expectation_covers_exactly_the_query_set_and_hops_differ(self):
        gt.parse_expected(copy.deepcopy(EXPECTED), QUERIES)
        depths = {c["depth"] for c in QUERIES["cases"] if c.get("depth")}
        self.assertEqual(depths, {1, 2, 3})
        for anchor_depths in ((1, 2), (2, 3)):   # the anchor kr-000400 changes at every depth step; kr-000100 is saturated at 2
            nodes = [set(EXPECTED["cases"][CASE_BY_KEY[("main", "focus", "kr-000400", d)]]["nodes"]) for d in anchor_depths]
            self.assertLess(nodes[0], nodes[1])
        self.assertEqual(EXPECTED["cases"]["GT05"]["nodes"], EXPECTED["cases"]["GT06"]["nodes"])


class MeasurementIsSeparateFromScoring(Case):
    def test_measurement_has_no_expectation_input_and_never_opens_the_file(self):
        self.assertNotIn("expected", gt.run_measurement.__kwdefaults__ or {})
        import inspect
        self.assertFalse([p for p in inspect.signature(gt.run_measurement).parameters if "expect" in p or "gold" in p])
        opened = []
        sys.addaudithook(lambda event, args: opened.append(str(args[0])) if event == "open" and flag[0] else None)
        flag[0] = True
        try:
            run = measure()
        finally:
            flag[0] = False
        self.assertFalse([p for p in opened if p.endswith(("expected.json", "gold.json"))])
        self.assertNotIn("edgeDefs", json.dumps(run))

    def test_phases_counts_and_order(self):
        fake = Fake()
        run = measure(fake, repeats=3, warmups=2)
        cases = len(QUERIES["cases"])
        by_phase = defaultdict(list)
        for a in run["attempts"]:
            by_phase[a["phase"]].append(a)
        self.assertEqual({k: len(v) for k, v in by_phase.items()}, {"integrity": 4, "warmup": cases * 2, "measure": cases * 3})
        self.assertEqual([a["seq"] for a in run["attempts"]], list(range(len(run["attempts"]))))
        phases = [a["phase"] for a in run["attempts"]]
        self.assertEqual(phases, ["integrity"] * 2 + ["warmup"] * (cases * 2) + ["measure"] * (cases * 3) + ["integrity"] * 2)
        first_round = [a["caseId"] for a in by_phase["measure"][:cases]]
        self.assertEqual(first_round, [c["caseId"] for c in QUERIES["cases"]])   # round robin: repeat 0 of every case before repeat 1
        self.assertEqual(len(fake.calls), len(run["attempts"]))
        self.assertEqual(run["fingerprints"], {})
        self.assertIsNone(run["config"]["checksRun"])

    def test_bad_repeat_and_warmup_arguments_are_refused_before_any_call(self):
        fake = Fake()
        for repeats, warmups in ((0, 1), (1001, 1), (True, 1), (3, -1), (3, 21)):
            self.rejected(lambda r=repeats, w=warmups: measure(fake, repeats=r, warmups=w), "bad_argument")
        self.assertEqual(fake.calls, [])

    def test_missing_manifest_version_fails_before_any_process(self):
        fake = Fake()
        manifest = {**MANIFEST, "versions": {"main": "gtbtest-main"}}
        self.rejected(lambda: gt.run_measurement(manifest=manifest, queries=QUERIES, queries_sha256=QUERIES_SHA, invoke=fake.invoke, repeats=1, warmups=0,
                                                 meta=META, clock=fake.clock), "manifest_mismatch")
        self.assertEqual(fake.calls, [])

    def test_the_record_leaks_no_path_and_no_credential(self):
        old = os.environ.get("ZOOP_GRAPH_PASSWORD")
        os.environ["ZOOP_GRAPH_PASSWORD"] = "never-recorded-secret"
        try:
            text = json.dumps(measure(), ensure_ascii=False)
        finally:
            os.environ.pop("ZOOP_GRAPH_PASSWORD") if old is None else os.environ.__setitem__("ZOOP_GRAPH_PASSWORD", old)
        for secret in ("nonexistent-secret-path", "never-recorded-secret", "bolt://"):
            self.assertNotIn(secret, text)


flag = [False]


class WallTimeComesFromTheClockAroundTheWholeInvocation(Case):
    def test_wall_ns_is_the_clock_difference_and_start_ns_is_relative(self):
        run = measure(Fake(step=lambda index: 1_000 + index))
        for a in run["attempts"]:
            self.assertEqual(a["wallNs"], 1_000 + a["seq"])
        self.assertEqual(run["attempts"][0]["startNs"], 0)
        self.assertEqual(run["attempts"][1]["startNs"], 1_000)

    def test_scored_timing_is_the_fake_tick_with_no_invented_components(self):
        result = score(measure(repeats=20, warmups=1))
        row = case_row(result, "GT03")
        self.assertEqual(row["timing"]["successWallMs"]["n"], 20)
        self.assertEqual((row["timing"]["successWallMs"]["p50"], row["timing"]["successWallMs"]["p95"]), (2.0, 2.0))
        self.assertEqual(row["timing"]["successWallMs"]["caveats"], [])
        self.assertTrue(all(v is None for v in result["decomposition"]["components"].values()))
        self.assertEqual(set(result["decomposition"]["components"]), set(gt.COMPONENTS))

    def test_fewer_than_twenty_repeats_carry_the_percentile_caveat(self):
        row = case_row(score(measure(repeats=3)), "GT03")
        self.assertTrue(any("p95_insufficient" in c for c in row["timing"]["successWallMs"]["caveats"]))

    def test_warmups_are_recorded_but_excluded_from_statistics(self):
        cases = len(QUERIES["cases"])
        slow = range(2, 2 + cases)   # the single warm-up call of every case
        result = score(measure(Fake(step=lambda i: 900_000_000 if i in slow else STEP), repeats=3, warmups=1))
        self.assertEqual(result["warmupsExcluded"]["attempts"], cases)
        self.assertEqual(result["warmupsExcluded"]["wallMs"]["max"], 900.0)
        for row in result["cases"]:
            self.assertEqual(row["timing"]["allAttemptsWallMs"]["max"], 2.0)
            self.assertEqual(row["warmupWallMs"]["n"], 1)

    def test_depth_pools_exclude_the_unknown_company_case_and_report_every_depth(self):
        result = score(measure(repeats=2))
        self.assertEqual(sorted(result["byDepth"]), ["1", "2", "3"])
        for block in result["byDepth"].values():
            self.assertNotIn("GT10", block["cases"])
        self.assertEqual(sorted(result["byCommand"]), ["focus", "inspect", "read"])


class OracleDoubleScoresPerfectly(Case):
    def test_all_cases_fully_correct_and_nothing_failed(self):
        result = score(measure(repeats=4))
        self.assertEqual(ok(result["headline"]["fullyCorrectRate"]), (len(QUERIES["cases"]) * 4,) * 2)
        self.assertEqual(ok(result["headline"]["failureRate"]), (0, len(QUERIES["cases"]) * 4))
        self.assertEqual(ok(result["headline"]["successCoverage"]), (len(QUERIES["cases"]),) * 2)
        self.assertEqual(result["failedAttempts"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["integrity"], {v: {"beforeOutcome": "current", "afterOutcome": "current", "bothCurrent": True, "sameVerifiedGraph": True}
                                               for v in ("main", "split")})
        self.assertEqual(result["checks"]["status"], "not_run")
        self.assertEqual(result["readOnly"]["status"], "not_recorded")
        self.assertEqual(case_row(result, "GT03")["distinctResults"], 1)


class HopSetsAndDirectionsAreScoredIndependently(Case):
    def verdicts(self, case_id, change):
        result = score(measure(Fake(edit=tamper(case_id, change)), repeats=2))
        return {name: ok(block) for name, block in case_row(result, case_id)["correctness"].items()}

    def test_a_depth_three_answer_for_a_depth_two_request_fails_the_node_and_edge_sets(self):
        wrong = cli_doc("GT03")
        v = self.verdicts("GT02", lambda doc: {**wrong, "focus": doc["focus"]})
        self.assertEqual(v["nodeSet"], (0, 2))
        self.assertEqual(v["edgeSet"], (0, 2))
        self.assertEqual(v["full"], (0, 2))
        self.assertEqual(v["found"], (2, 2))

    def test_wrong_distances_with_the_right_nodes_fail_only_the_distances(self):
        def change(doc):
            doc["graph"]["nodes"] = [{**n, "distance": 1 if n["distance"] else 0} for n in doc["graph"]["nodes"]]
            return doc
        v = self.verdicts("GT02", change)
        self.assertEqual((v["nodeSet"], v["distances"], v["edgeSet"], v["orientation"], v["attributes"]), ((2, 2), (0, 2), (2, 2), (2, 2), (2, 2)))

    def test_a_reversed_directed_edge_keeps_reachability_but_fails_orientation(self):
        def change(doc):
            for e in doc["graph"]["edges"]:
                if e["type"] == "INVESTS_IN":
                    e["subject"], e["object"] = e["object"], e["subject"]
            return doc
        v = self.verdicts("GT09", change)
        self.assertEqual((v["edgeSet"], v["orientation"], v["full"]), ((2, 2), (0, 2), (0, 2)))

    def test_a_reversed_symmetric_edge_is_not_an_orientation_error(self):
        def change(doc):
            for e in doc["graph"]["edges"]:
                if e["direction"] == "symmetric":
                    e["subject"], e["object"] = e["object"], e["subject"]
            return doc
        v = self.verdicts("GT07", change)
        self.assertEqual((v["edgeSet"], v["orientation"], v["attributes"], v["full"]), ((2, 2),) * 4)

    def test_a_directed_edge_declared_symmetric_fails_orientation_and_attributes(self):
        def change(doc):
            for e in doc["graph"]["edges"]:
                if e["type"] == "SUPPLIES":
                    e["direction"] = "symmetric"
            return doc
        v = self.verdicts("GT09", change)
        self.assertEqual((v["edgeSet"], v["orientation"], v["attributes"]), ((2, 2), (0, 2), (0, 2)))

    def test_wrong_connection_validity_path_or_citation_fail_only_the_attributes(self):
        # GT02 holds the dated INVESTS_IN edge (dc), a direct SUPPLIES edge (cb) and the indirect two-step SUPPLIES edge (ca)
        picks = {"connection": (lambda e: e["connection"] == "indirect", lambda e: e.update(connection="direct")),
                 "validity": (lambda e: e["validity"]["until"] is not None, lambda e: e["validity"].update({"until": None})),
                 "path": (lambda e: bool(e["path"]["companyIds"]), lambda e: e["path"].update({"companyIds": []})),
                 "citation": (lambda e: e["type"] == "INVESTS_IN", lambda e: e["evidence"].update({"relation": [], "steps": [[], []]}))}
        for label, (select, edit) in picks.items():
            def aimed(doc, select=select, edit=edit):
                edit(next(e for e in doc["graph"]["edges"] if select(e)))
                return doc
            v = self.verdicts("GT02", aimed)
            with self.subTest(label):
                self.assertEqual((v["edgeSet"], v["orientation"], v["attributes"], v["full"]), ((2, 2), (2, 2), (0, 2), (0, 2)))

    def test_a_missing_and_a_duplicated_edge_fail_the_edge_set(self):
        missing = self.verdicts("GT03", lambda doc: {**doc, "graph": {**doc["graph"], "edges": doc["graph"]["edges"][1:]}})
        duplicated = self.verdicts("GT03", lambda doc: {**doc, "graph": {**doc["graph"], "edges": doc["graph"]["edges"] + doc["graph"]["edges"][:1]}})
        self.assertEqual((missing["edgeSet"], duplicated["edgeSet"]), ((0, 2), (0, 2)))

    def test_unknown_company_must_be_found_false_with_empty_sets(self):
        wrong = self.verdicts("GT10", lambda doc: {**doc, "focus": {**doc["focus"], "found": True}})
        self.assertEqual(wrong["found"], (0, 2))
        self.assertEqual(wrong["full"], (0, 2))

    def test_a_disconnected_component_leaking_into_the_answer_fails(self):
        leak = self.verdicts("GT11", lambda doc: {**doc, "graph": cli_doc("GC02")["graph"]})
        self.assertEqual((leak["nodeSet"], leak["edgeSet"], leak["full"]), ((0, 2), (0, 2), (0, 2)))

    def test_read_and_inspect_controls_are_judged_on_their_own_terms(self):
        result = score(measure(Fake(edit=tamper("GC03", lambda doc: {**doc, "state": "frozen"})), repeats=2))
        self.assertEqual(case_row(result, "GC03")["correctness"]["state"]["num"], 0)
        self.assertEqual(case_row(result, "GC03")["correctness"]["counts"]["num"], 2)
        self.assertEqual(case_row(result, "GC04")["correctness"]["full"]["num"], 2)
        self.assertEqual(result["byCategory"]["control-ledger-inspect"]["correctness"]["full"], {"num": 2, "den": 4, "value": 0.5})


class FailuresAreKeptNeverDropped(Case):
    def test_withheld_and_error_and_timeout_and_garbage_are_distinct_outcomes_with_a_failure_rate(self):
        replies = {"GT01": withheld("source_unauthorized"), "GT02": refusal("graph_internal_failure"), "GT03": gt.Invocation(None, b"", 0, "timeout"),
                   "GT04": gt.Invocation(0, b"not json", 12), "GT05": gt.Invocation(0, b"[]", 0), "GT06": gt.Invocation(0, json.dumps({"delivery": {"status": "withheld", "code": "x"}}).encode(), 0)}

        def edit(index, case_id, doc):
            return replies.get(case_id)
        run = measure(Fake(edit=edit), repeats=2)
        outcomes = {c: {a["outcome"] for a in run["attempts"] if a["caseId"] == c and a["phase"] == "measure"} for c in replies}
        self.assertEqual(outcomes, {"GT01": {"withheld"}, "GT02": {"error"}, "GT03": {"timeout"}, "GT04": {"invalid_output"}, "GT05": {"invalid_output"},
                                    "GT06": {"invalid_output"}})
        stderr = next(a for a in run["attempts"] if a["caseId"] == "GT04")["stderrBytes"]
        self.assertEqual(stderr, 12)
        result = score(run)
        self.assertEqual(ok(result["headline"]["failureRate"]), (12, len(QUERIES["cases"]) * 2))
        self.assertEqual(len(result["failedAttempts"]), 12)
        self.assertEqual(ok(result["headline"]["successCoverage"]), (len(QUERIES["cases"]) - 6, len(QUERIES["cases"])))
        row = case_row(result, "GT01")
        self.assertEqual(ok(row["timing"]["failureRate"]), (2, 2))
        self.assertEqual(row["timing"]["successWallMs"]["n"], 0)
        self.assertEqual(row["timing"]["allAttemptsWallMs"]["n"], 2)
        self.assertEqual(row["correctness"]["full"]["num"], 0)
        self.assertTrue(any("did not succeed" in w for w in result["warnings"]))

    def test_a_slow_attempt_is_neither_dropped_nor_hidden(self):
        slow_index = 2 + len(QUERIES["cases"]) + 3   # skip the two integrity reads and the one warm-up call per case; this is a measured call
        result = score(measure(Fake(step=lambda i: 700_000_000 if i == slow_index else STEP), repeats=2, warmups=1))
        self.assertEqual(result["slowestAttempts"][0]["wallMs"], 700.0)
        self.assertEqual(max(r["timing"]["allAttemptsWallMs"]["max"] for r in result["cases"]), 700.0)


class ClassifyReadsTheRealCliShapes(Case):
    def test_exit_codes_and_shapes(self):
        self.assertEqual(gt.classify("focus", inv(cli_doc("GT01")))[0], "current")
        self.assertEqual(gt.classify("focus", withheld("source_unauthorized"))[:2], ("withheld", "source_unauthorized"))
        self.assertEqual(gt.classify("focus", refusal("version_not_found"))[:2], ("error", "version_not_found"))
        self.assertEqual(gt.classify("inspect", inv(cli_doc("GC03")))[0], "ledger")
        self.assertEqual(gt.classify("focus", inv(cli_doc("GT01"), 2))[0], "invalid_output")   # a current document with a failing exit code is not trusted
        self.assertEqual(gt.classify("read", withheld("x"))[0], "withheld")
        self.assertEqual(gt.classify("focus", gt.Invocation(0, b"\xff\xfe", 0))[0], "invalid_output")
        self.assertEqual(gt.classify("focus", gt.Invocation(None, b"", 0, "spawn_error"))[0], "spawn_error")

    def test_the_record_keeps_orientation_and_drops_relation_hashes(self):
        outcome, _, result, usage = gt.classify("focus", inv(cli_doc("GT09")))
        self.assertEqual(usage, USAGE)
        edge = next(e for e in result["edges"] if e["type"] == "INVESTS_IN")
        self.assertEqual((edge["subject"], edge["object"], edge["direction"]), ("kr-000400", "kr-000300", "directed"))
        self.assertNotIn("relationId", json.dumps(result))


class RecordValidation(Case):
    def base(self):
        return measure(repeats=2)

    def test_a_clean_record_scores_and_unknown_keys_are_refused(self):
        run = self.base()
        score(run)
        self.rejected(lambda: score({**run, "extra": 1}), "malformed")

    def test_duplicates_are_refused(self):
        run = self.base()
        clone = copy.deepcopy(run)
        clone["attempts"].append({**clone["attempts"][5], "seq": 9999})
        self.rejected(lambda: score(clone), "duplicate_attempt")
        clone = copy.deepcopy(run)
        clone["attempts"].append({**clone["attempts"][5], "repeat": 77})
        self.rejected(lambda: score(clone), "duplicate_attempt")

    def test_malformed_times_are_refused_not_repaired(self):
        for key in ("wallNs", "startNs"):
            for bad in (-1, 1.5, True, "3", None, float("nan"), float("inf")):
                run = self.base()
                run["attempts"][4][key] = bad
                with self.subTest(key=key, bad=bad):
                    self.rejected(lambda run=run: score(run), "malformed")

    def test_a_tampered_result_does_not_hash_to_its_key(self):
        run = self.base()
        digest = run["attempts"][4]["resultDigest"]
        run["results"][digest] = {**run["results"][digest], "found": not run["results"][digest].get("found", True)}
        self.rejected(lambda: score(run), "result_digest_mismatch")

    def test_attempt_result_rules(self):
        run = self.base()
        run["attempts"][4]["resultDigest"] = "f" * 64
        self.rejected(lambda: score(run), "malformed")
        run = self.base()
        run["attempts"][4]["outcome"], run["attempts"][4]["code"] = "timeout", None
        self.rejected(lambda: score(run), "malformed")   # a timeout cannot carry a result

    def test_only_tool_measurements_are_scored(self):
        run = self.base()
        for change in ({"kind": "authored_control"}, {"kind": "real_measured"}, {"graphConstruction": "gold_graph"}):
            bad = copy.deepcopy(run)
            bad["provenance"].update(change)
            with self.subTest(change=change):
                self.rejected(lambda bad=bad: score(bad), "incompatible_run")
        control = json.loads((ROOT / "fixtures" / "controls" / "oracle-dev.run.json").read_text("utf-8"))
        self.rejected(lambda: score(control), "incompatible_run")
        self.rejected(lambda: score([1]), "incompatible_run")

    def test_observed_model_or_provider_calls_are_not_scored(self):
        for key in ("modelCalls", "providerCalls"):
            run = self.base()
            run["usage"][key] = 1
            self.rejected(lambda run=run: score(run), "unexpected_model_call")

    def test_usage_is_summed_from_observed_outputs_and_absent_usage_is_counted(self):
        def edit(index, case_id, doc):
            if case_id == "GT01":
                doc.pop("usage")
                return doc
        run = measure(Fake(edit=edit), repeats=2)
        self.assertEqual(run["usage"]["attemptsWithoutUsage"], 3)   # one warm-up and two measured calls of GT01
        self.assertEqual((run["usage"]["modelCalls"], run["usage"]["providerCalls"]), (0, 0))

    def test_scope_mismatches_and_unknown_cases_are_refused(self):
        run = self.base()
        self.rejected(lambda: score(run, sha="0" * 64), "scope_mismatch")
        other = copy.deepcopy(run)
        other["scope"]["queriesId"] = "other"
        self.rejected(lambda: score(other), "scope_mismatch")
        bad = copy.deepcopy(run)
        bad["attempts"][4]["caseId"] = "GT99"
        self.rejected(lambda: score(bad), "unmatched_case")

    def test_expectation_must_cover_exactly_the_queries(self):
        expected = copy.deepcopy(EXPECTED)
        del expected["cases"]["GT01"]
        self.rejected(lambda: score(self.base(), expected=expected), "scope_mismatch")
        expected = copy.deepcopy(EXPECTED)
        expected["cases"]["GT01"]["edges"].append("nope")
        self.rejected(lambda: score(self.base(), expected=expected), "malformed")
        expected = copy.deepcopy(EXPECTED)
        del expected["checks"]["CK01"]
        self.rejected(lambda: score(self.base(), expected=expected), "scope_mismatch")

    def test_query_set_validation(self):
        base = json.loads((FIXTURES / "queries.json").read_text("utf-8"))

        def mutated(change):
            doc = copy.deepcopy(base)
            change(doc)
            return lambda: gt.parse_queries(doc)
        self.rejected(mutated(lambda d: d.update(split="test")), "malformed")
        self.rejected(mutated(lambda d: d["cases"][0].update(depth=4)), "malformed")
        self.rejected(mutated(lambda d: d["cases"][0].update(version="nope")), "malformed")
        self.rejected(mutated(lambda d: d["cases"].append(copy.deepcopy(d["cases"][0]))), "duplicate_case")
        self.rejected(mutated(lambda d: d["cases"][-1].update(depth=1)), "malformed")
        self.rejected(mutated(lambda d: d["checks"][0].update(mutation="rm -rf")), "malformed")
        self.rejected(mutated(lambda d: d["cases"][0].update(extra=1)), "malformed")


class ReadOnlyProofAndChecks(Case):
    def test_fingerprints_are_compared_before_and_after_and_report_only_labels(self):
        ticks = iter([{"graphLedgerRows": "1" * 64, "canonicalRegistry": "2" * 64}, {"graphLedgerRows": "9" * 64, "canonicalRegistry": "2" * 64}])
        result = score(measure(fingerprint=lambda: next(ticks), repeats=1, warmups=0))
        self.assertEqual(result["readOnly"]["status"], "CHANGED")
        self.assertEqual(result["readOnly"]["changedLabels"], ["graphLedgerRows"])
        self.assertTrue(any("read-only proof failed" in w for w in result["warnings"]))
        same = score(measure(fingerprint=lambda: {"graphLedgerRows": "1" * 64}, repeats=1, warmups=0))
        self.assertEqual((same["readOnly"]["status"], same["readOnly"]["changedLabels"]), ("unchanged", []))

    def test_graph_content_drift_between_integrity_reads_is_reported(self):
        calls = []

        def edit(index, case_id, doc):
            if case_id == "GC01":
                calls.append(index)
                if len(calls) == 1:   # the first full read is the integrity-before read; make the verified graph differ afterwards
                    return None
                doc["digests"]["graph"] = "c" * 64
                return doc
        result = score(measure(Fake(edit=edit), repeats=1, warmups=0))
        self.assertFalse(result["integrity"]["main"]["sameVerifiedGraph"])
        self.assertTrue(any("integrity" in w for w in result["warnings"]))

    def test_authority_checks_run_outside_timing_and_pass(self):
        fake = Fake()
        run = measure(fake, repeats=2, mutate=fake.mutate)
        self.assertEqual(fake.restored, 3)
        self.assertEqual(run["config"]["checksRun"], ["CK01", "CK02", "CK03", "CK04", "CK05"])
        self.assertEqual({a["phase"] for a in run["attempts"] if a["caseId"].startswith("CK")}, {"check", "recheck"})
        result = score(run)
        self.assertEqual(result["checks"]["status"], "passed")
        self.assertEqual([r["status"] for r in result["checks"]["rows"]], ["passed"] * 5)
        self.assertEqual(ok(result["headline"]["failureRate"])[0], 0)   # denials never enter the timing failure rate
        self.assertEqual(sum(r["timing"]["attempts"] for r in result["cases"]), len(QUERIES["cases"]) * 2)

    def test_a_wrong_denial_outcome_fails_the_check_and_a_missing_one_is_not_run(self):
        fake = Fake()
        run = measure(fake, repeats=1, warmups=0, mutate=fake.mutate)
        target = next(a for a in run["attempts"] if a["caseId"] == "CK01" and a["phase"] == "check")
        target["outcome"], target["code"] = "current", None
        target["resultDigest"] = next(a["resultDigest"] for a in run["attempts"] if a["caseId"] == "GT04" and a["phase"] == "measure")
        result = score(run)
        self.assertEqual(result["checks"]["status"], "FAILED")
        self.assertEqual(result["checks"]["rows"][0]["status"], "FAILED")

    def test_the_mutation_is_restored_even_when_the_call_blows_up(self):
        fake = Fake()
        original = fake.invoke

        def boom(command, stdin):
            if fake.active:
                raise RuntimeError("boom")
            return original(command, stdin)
        with self.assertRaises(RuntimeError):
            gt.run_measurement(manifest=MANIFEST, queries=QUERIES, queries_sha256=QUERIES_SHA, invoke=boom, repeats=1, warmups=0, meta=META, clock=fake.clock,
                               mutate=fake.mutate)
        self.assertEqual((fake.active, fake.restored), (None, 1))


class MutatorAndFingerprintsOnRealFiles(Case):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="zoop-gt-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name in ("relation", "extraction", "ingestion", "graph"):
            (self.dir / name).mkdir()
            (self.dir / name / "data.bin").write_bytes(name.encode())
        db = sqlite3.connect(self.dir / "graph" / "graph.sqlite3")
        db.execute("CREATE TABLE versions (id TEXT, state TEXT)")
        db.execute("INSERT INTO versions VALUES ('v1', 'ready')")
        db.commit()
        db.close()
        sources = {"sources": [{"grant": {"enabled": True, "revision": "rights-1"}}]}
        canonical = {"entries": [{"kind": "company", "ref": "a"}, {"kind": "topic", "ref": "t"}]}
        (self.dir / "sources.json").write_bytes(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode())
        (self.dir / "canonical.json").write_bytes(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode())
        os.chmod(self.dir / "canonical.json", 0o600)
        (self.dir / OWNER_MARKER).write_text(MANIFEST["runId"], "utf-8")
        self.manifest = {**MANIFEST, "owned": True, "root": str(self.dir), "stateDir": str(self.dir / "graph"), "relationStateDir": str(self.dir / "relation"),
                         "extractionStateDir": str(self.dir / "extraction"), "ingestionStateDir": str(self.dir / "ingestion"),
                         "sources": str(self.dir / "sources.json"), "canonical": str(self.dir / "canonical.json")}

    def test_fingerprints_are_stable_label_keyed_digests_without_paths(self):
        first = gt.fingerprint_state(self.manifest)
        self.assertEqual(first, gt.fingerprint_state(self.manifest))
        self.assertEqual(set(first), {"relationState", "extractionState", "ingestionState", "graphLedgerRows", "graphStateFiles", "sourcesRegistry", "canonicalRegistry"})
        self.assertNotIn(str(self.dir), json.dumps(first))
        (self.dir / "relation" / "data.bin").write_bytes(b"changed")
        second = gt.fingerprint_state(self.manifest)
        self.assertEqual([k for k in first if first[k] != second[k]], ["relationState"])
        db = sqlite3.connect(self.dir / "graph" / "graph.sqlite3")
        db.execute("UPDATE versions SET state='failed'")
        db.commit()
        db.close()
        self.assertNotEqual(gt.fingerprint_state(self.manifest)["graphLedgerRows"], first["graphLedgerRows"])

    def test_each_mutation_changes_one_registry_and_restores_exact_bytes_and_mode(self):
        mutate = gt.make_mutator(self.manifest)
        before = gt.fingerprint_state(self.manifest)
        sources, canonical = (self.dir / "sources.json").read_bytes(), (self.dir / "canonical.json").read_bytes()
        restore = mutate("grant-disabled")
        self.assertFalse(json.loads((self.dir / "sources.json").read_bytes())["sources"][0]["grant"]["enabled"])
        restore()
        restore = mutate("grant-revision-changed")
        self.assertNotEqual(json.loads((self.dir / "sources.json").read_bytes())["sources"][0]["grant"]["revision"], "rights-1")
        restore()
        restore = mutate("canonical-topic-removed")
        self.assertEqual([e["kind"] for e in json.loads((self.dir / "canonical.json").read_bytes())["entries"]], ["company"])
        self.assertEqual(stat.S_IMODE((self.dir / "canonical.json").stat().st_mode), 0o600)
        restore()
        self.assertEqual(((self.dir / "sources.json").read_bytes(), (self.dir / "canonical.json").read_bytes()), (sources, canonical))
        self.assertEqual(stat.S_IMODE((self.dir / "canonical.json").stat().st_mode), 0o600)
        self.assertEqual(gt.fingerprint_state(self.manifest), before)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [OWNER_MARKER, "canonical.json", "extraction", "graph", "ingestion", "relation", "sources.json"])
        self.assertRaises(ValueError, lambda: mutate("rm -rf"))

    def test_mutations_are_refused_on_state_the_runner_does_not_own(self):
        self.rejected(lambda: gt.make_mutator({**self.manifest, "owned": False}), "not_owned")


class ScriptCommands(Case):
    """The command line wiring, in-process on a fake record (no tool, no Neo4j)."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("graph_tool_bench", ROOT / "scripts" / "graph_tool_bench.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.module.main(list(argv))
        return code, json.loads(out.getvalue())

    def test_score_writes_json_and_markdown_and_states_what_is_not_measured(self):
        with tempfile.TemporaryDirectory(prefix="zoop-gt-cli-") as tmp:
            path = Path(tmp) / "run.json"
            path.write_text(json.dumps(measure(repeats=2, mutate=None)), "utf-8")
            code, summary = self.run_main("score", str(path), "--out", str(Path(tmp) / "score.json"), "--markdown", str(Path(tmp) / "report.md"))
            self.assertEqual(code, 0)
            self.assertEqual(summary["headline"]["failureRate"]["num"], 0)
            score_doc = json.loads((Path(tmp) / "score.json").read_text("utf-8"))
            self.assertEqual(score_doc["schemaVersion"], gt.SCHEMA_SCORE)
            report = (Path(tmp) / "report.md").read_text("utf-8")
            self.assertNotIn("/nonexistent-secret-path", report)

    def test_score_refuses_a_control_run_file_with_exit_2(self):
        code, out = self.run_main("score", str(ROOT / "fixtures" / "controls" / "oracle-dev.run.json"))
        self.assertEqual((code, out["error"]["code"]), (2, "incompatible_run"))

    def test_measure_refuses_to_overwrite_and_needs_a_manifest(self):
        with tempfile.TemporaryDirectory(prefix="zoop-gt-cli-") as tmp:
            existing = Path(tmp) / "run.json"
            existing.write_text("{}", "utf-8")
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps({**MANIFEST}), "utf-8")
            python = Path(sys.executable)
            with self.assertRaises(SystemExit):
                self.run_main("measure", "--manifest", str(manifest), "--out", str(existing), "--pipeline-python", str(python))

    def test_authority_checks_are_refused_for_unowned_state(self):
        with tempfile.TemporaryDirectory(prefix="zoop-gt-cli-") as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps({**MANIFEST}), "utf-8")
            code, out = self.run_main("measure", "--manifest", str(manifest), "--out", str(Path(tmp) / "run.json"), "--pipeline-python", sys.executable,
                                      "--authority-checks")
            self.assertEqual((code, out["error"]["code"]), (2, "not_owned"))


# ---------------------------------------------------------------------------------------------------------------------
# Review findings, written RED FIRST (no production change accompanies them). Each class names the finding it pins.
# Contracts these tests introduce for the fixers:
#   * Rejected code `attempt_slots_mismatch` for any missing/extra/shifted attempt slot (graph_tool.score_run).
#   * make_mutator refuses with `not_owned` BEFORE reading or writing a registry unless manifest.root holds the OWNER_MARKER of the same run and both
#     registries are regular, non-symlink files inside that root.
#   * The Markdown report shows the success count and the attempt count as separate numbers and lists the distribution caveat codes per case.
# Exact Neo4j cleanup is proven by scripts/graph_tool_cleanup_adversarial.py against a real database, not by a unit test.
# ---------------------------------------------------------------------------------------------------------------------

class OpenWatch:
    """Collects the path of every `open` audit event while a `watching()` block is active (the hook is installed once per process)."""
    installed, active = False, None

    @staticmethod
    def hook(event, args):
        if OpenWatch.active is not None and event == "open":
            OpenWatch.active.append(str(args[0]))


@contextlib.contextmanager
def watching():
    if not OpenWatch.installed:
        sys.addaudithook(OpenWatch.hook)
        OpenWatch.installed = True
    seen = []
    OpenWatch.active = seen
    try:
        yield seen
    finally:
        OpenWatch.active = None


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(Path(root).rglob("*")) if p.is_file() and not p.is_symlink()}


class MutationRequiresPreparedOwnership(Case):
    """Finding: `owned: true` alone must not authorize replacing registry files."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="zoop-gt-own-")).resolve()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.root, self.outside = self.dir / "root", self.dir / "outside"
        self.root.mkdir()
        self.outside.mkdir()
        sources = json.dumps({"sources": [{"grant": {"enabled": True, "revision": "rights-1"}}]}, sort_keys=True, separators=(",", ":")).encode()
        canonical = json.dumps({"entries": [{"kind": "topic", "ref": "t"}]}, sort_keys=True, separators=(",", ":")).encode()
        for directory in (self.root, self.outside):
            (directory / "sources.json").write_bytes(sources)
            (directory / "canonical.json").write_bytes(canonical)
        (self.root / OWNER_MARKER).write_text(MANIFEST["runId"], "utf-8")
        self.manifest = {**MANIFEST, "owned": True, "root": str(self.root), "sources": str(self.root / "sources.json"), "canonical": str(self.root / "canonical.json")}

    def refused(self, manifest, name="grant-disabled"):
        before = snapshot(self.dir)
        with watching() as seen:
            try:
                restore = gt.make_mutator(manifest)(name)
            except Rejected as exc:
                error = exc
            else:
                restore()
                error = None
        self.assertIsNotNone(error, "the mutation was allowed")
        self.assertEqual(error.code, "not_owned")
        self.assertEqual([p for p in seen if p.endswith(REGISTRY_NAMES)], [], "a registry file was opened before the refusal")
        self.assertEqual(snapshot(self.dir), before, "a file changed")

    def test_prepared_state_still_mutates_and_restores_exactly(self):
        before = snapshot(self.root)
        restore = gt.make_mutator(self.manifest)("grant-disabled")
        self.assertNotEqual(snapshot(self.root)["sources.json"][0], before["sources.json"][0])
        restore()
        self.assertEqual({k: v[0] for k, v in snapshot(self.root).items()}, {k: v[0] for k, v in before.items()})

    def test_owned_false_refuses_before_any_read_or_write(self):
        self.refused({**self.manifest, "owned": False})

    def test_missing_marker_refuses(self):
        (self.root / OWNER_MARKER).unlink()
        self.refused(self.manifest)

    def test_marker_of_another_run_refuses(self):
        (self.root / OWNER_MARKER).write_text("someone-elses-run", "utf-8")
        self.refused(self.manifest)

    def test_manifest_without_a_root_refuses(self):
        self.refused({k: v for k, v in self.manifest.items() if k != "root"})

    def test_registries_outside_the_prepared_root_refuse(self):
        self.refused({**self.manifest, "sources": str(self.outside / "sources.json"), "canonical": str(self.outside / "canonical.json")})
        self.refused({**self.manifest, "canonical": str(self.outside / "canonical.json")}, "canonical-topic-removed")

    def test_dotdot_escape_refuses(self):
        self.refused({**self.manifest, "sources": f"{self.root}/../outside/sources.json"})

    def test_symlinked_registry_refuses_and_its_target_is_untouched(self):
        (self.root / "sources.json").unlink()
        os.symlink(self.outside / "sources.json", self.root / "sources.json")
        self.refused(self.manifest)


class AttemptSlotsAreExact(Case):
    """Finding: completeness is the exact planned slot set, not list lengths. Any deviation is rejected before statistics are computed."""
    CODE = "attempt_slots_mismatch"

    def record(self, checks=False):
        fake = Fake()
        return measure(fake, repeats=2, warmups=1, mutate=fake.mutate if checks else None)

    def gone(self, run, case, phase, repeat=0):
        run["attempts"] = [a for a in run["attempts"] if not (a["caseId"] == case and a["phase"] == phase and a["repeat"] == repeat)]

    def extra(self, run, case, phase, repeat, like=None):
        like = like or next(a for a in run["attempts"] if a["caseId"] == case)
        run["attempts"].append({**like, "seq": max(a["seq"] for a in run["attempts"]) + 1, "caseId": case, "phase": phase, "repeat": repeat})

    def assertSlotsRejected(self, run):
        self.rejected(lambda: score(run), self.CODE)

    def test_complete_records_still_score(self):
        score(self.record())
        score(self.record(checks=True))

    def test_a_missing_measured_repeat_is_rejected_not_warned(self):
        run = self.record()
        self.gone(run, "GT03", "measure", 1)
        self.assertSlotsRejected(run)

    def test_a_repeat_shifted_to_another_number_is_rejected(self):
        run = self.record()
        next(a for a in run["attempts"] if a["caseId"] == "GT03" and a["phase"] == "measure" and a["repeat"] == 1)["repeat"] = 99
        self.assertSlotsRejected(run)

    def test_an_extra_measured_repeat_is_rejected(self):
        run = self.record()
        self.extra(run, "GT03", "measure", 2)
        self.assertSlotsRejected(run)

    def test_warmup_slots_are_exact(self):
        run = self.record()
        self.gone(run, "GT03", "warmup")
        self.assertSlotsRejected(run)
        run = self.record()
        self.extra(run, "GT03", "warmup", 1)
        self.assertSlotsRejected(run)

    def test_a_whole_case_missing_is_rejected(self):
        run = self.record()
        run["attempts"] = [a for a in run["attempts"] if a["caseId"] != "GC04"]
        self.assertSlotsRejected(run)

    def test_integrity_slots_are_exactly_one_before_and_one_after_per_version(self):
        run = self.record()
        self.gone(run, "INTEGRITY:main:after", "integrity")
        self.assertSlotsRejected(run)
        run = self.record()
        self.extra(run, "INTEGRITY:main:before", "integrity", 1)
        self.assertSlotsRejected(run)

    def test_check_slots_follow_the_checks_that_were_run(self):
        run = self.record(checks=True)
        self.gone(run, "CK01", "recheck")            # a mutated check owes a recheck
        self.assertSlotsRejected(run)
        run = self.record(checks=True)
        self.extra(run, "CK04", "recheck", 0)         # an unmutated check owes none
        self.assertSlotsRejected(run)
        run = self.record(checks=True)
        self.gone(run, "CK02", "check")               # listed in checksRun but absent
        self.assertSlotsRejected(run)
        run = self.record(checks=False)
        self.extra(run, "CK01", "check", 0, like=run["attempts"][0])   # not listed in checksRun (null) but present
        self.assertSlotsRejected(run)


class MarkdownShowsTheSampleSizesAndCaveats(Case):
    """Finding: success-only percentiles must not be shown beside the total attempt count alone, and the distribution caveats must survive into the report.
    The tests read numbers and the caveat codes that `stats.distribution` already emits; they do not pin any column title or sentence."""

    @staticmethod
    def cells(markdown, first):
        line = next(line for line in markdown.splitlines() if line.startswith(f"| {first} |"))
        return [c.strip() for c in line.strip().strip("|").split("|")]

    def thin_report(self):
        calls = defaultdict(int)

        def edit(index, case_id, doc):
            if case_id != "GT03":
                return None
            calls[case_id] += 1
            return None if calls[case_id] <= 3 else gt.Invocation(None, b"", 0, "timeout")   # the warm-up and 2 measured calls succeed, 18 time out
        result = score(measure(Fake(edit=edit), repeats=20, warmups=1))
        return result, gt.render_markdown(result)

    def test_a_case_row_shows_both_the_success_count_and_the_attempt_count(self):
        result, markdown = self.thin_report()
        self.assertEqual(case_row(result, "GT03")["timing"]["successWallMs"]["n"], 2)
        thin, full = self.cells(markdown, "GT03"), self.cells(markdown, "GT01")
        self.assertIn("2", thin)
        self.assertIn("20", thin)
        self.assertGreaterEqual(full.count("20"), 2)

    def test_depth_and_command_rows_show_both_counts(self):
        _, markdown = self.thin_report()
        depth_three = self.cells(markdown, "3")     # GT03 (2 of 20) + GT06, GT11, GT12 (20 of 20 each)
        self.assertIn("62", depth_three)
        self.assertIn("80", depth_three)
        focus = self.cells(markdown, "focus")       # the 13 focus cases, 260 attempts
        self.assertIn("242", focus)
        self.assertIn("260", focus)

    def test_the_distribution_caveats_are_listed_for_the_thin_case_only(self):
        _, markdown = self.thin_report()
        lines = markdown.splitlines()
        self.assertTrue(any("GT03" in line and "p95_insufficient_samples" in line and "p50_insufficient_samples" in line for line in lines))
        self.assertFalse(any("GT01" in line and "insufficient" in line for line in lines))

    def test_a_fully_sampled_report_has_no_caveat(self):
        self.assertNotIn("insufficient", gt.render_markdown(score(measure(repeats=20))))



if __name__ == "__main__":
    unittest.main()
