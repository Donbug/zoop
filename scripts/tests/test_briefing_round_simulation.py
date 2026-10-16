"""Authored source/HTML/model examples only; no real publisher or model network call."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "briefing_round_simulation.py"
SPEC = importlib.util.spec_from_file_location("round_simulation", MODULE)
sim = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sim)


def source(document, published, body=None):
    body = body or (document + " 합성 시험 기업이 새 계약 계획을 발표했습니다. 실제 뉴스가 아닌 직접 작성한 시험 원문입니다. ") * 4
    return {"documentId": document, "body": body, "bodySha256": sim.digest(body.encode()),
            "url": "https://example.invalid/" + document, "title": "합성 계약 계획", "sourceKind": "news",
            "companyAssociations": [{"companyName": "시험 기업"}], "allowModelSend": False, "rightsStatus": "unconfirmed",
            "bodyAcquiredAt": "2026-10-16T00:00:00Z", "authoredPublishedAt": published}


def response(value, request):
    return 200, sim.canonical({"id": "authored-" + sim.digest(request)[:16], "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "output": [{"type": "message", "content": [{"type": "output_text", "text": sim.canonical(value).decode()}]}]})


class AuthoredTransport:
    def __init__(self, held=False, insufficient=False, select_none=False, quote_marker=None, semantic_failure=None,
                 quote_errors=0, quote_error_document=None, selection_transport_failure=None):
        self.requests = []
        self.held = held
        self.insufficient = insufficient
        self.select_none = select_none
        self.quote_marker = quote_marker
        self.semantic_failure = semantic_failure
        self.quote_errors = quote_errors
        self.quote_error_document = quote_error_document
        self.selection_transport_failure = selection_transport_failure
        self.quote_error_attempts = 0

    def __call__(self, raw):
        self.requests.append(raw)
        request = sim.base.strict_load(raw)
        data = sim.base.strict_load(request["input"])
        assert data["context"]["mode"] == sim.MODE and request["store"] is False
        stage = request["text"]["format"]["name"]
        if stage == "round_simulation_importance":
            value = {"assessments": {row["documentId"]: {"documentId": row["documentId"], "importance": 2,
                "priority": 75, "status": "HOLD" if self.held else "ELIGIBLE", "eventKey": row["documentId"],
                "headline": "합성 계약 계획", "reason": "직접 작성한 시험 원문", "scope": "COMPANY", "affectedSectors": [],
                "transmission": "", "limitations": ["현재 선언 시각 기반 합성 과거 시뮬레이션"]} for row in data["documents"]}}
        elif stage == "round_simulation_selection":
            if self.selection_transport_failure == "unknown":
                raise OSError("authored unknown transport outcome")
            row = data["documents"][0]
            start = row["body"].index(self.quote_marker) if self.quote_marker else 0
            value = {"selected": [{"eventKey": row["documentId"], "title": "합성 계약 계획", "reason": "시험 원문의 계약 계획",
                "importance": 2, "priority": 75, "companyNames": row["companyNames"], "limitations": ["합성 시뮬레이션"],
                "sources": [{"documentId": row["documentId"], "quotes": [row["body"][start:start + 120]]}],
                "scope": "COMPANY", "affectedSectors": [], "transmission": ""}], "held": []}
            if self.select_none:
                value = {"selected": [], "held": [{"documentId": row["documentId"], "reason": "전체 본문에도 확정 근거가 없어 보류"}]}
            if self.quote_error_document in (None, row["documentId"]) and self.quote_error_attempts < self.quote_errors:
                value["selected"][0]["sources"][0]["quotes"] = ["An authored English translation that is absent from the original Korean body."]
                self.quote_error_attempts += 1
            if self.selection_transport_failure == "http":
                return 503, response(value, raw)[1]
        elif stage.endswith("_generation"):
            value = {"items": {row["issueId"]: {"issueId": row["issueId"], "rank": row["rank"], "title": "시험 기업의 계약 계획",
                "titleEvidenceIds": [row["sources"][0]["evidenceId"]], "claims": [
                    {"text": "시험 기업이 계약 계획을 발표했습니다.", "type": "fact", "evidenceIds": [row["sources"][0]["evidenceId"]]},
                    {"text": "새 계약은 계획 단계입니다.", "type": "plan", "evidenceIds": [row["sources"][0]["evidenceId"]]}]}
                for row in data["selected"]}}
            if self.insufficient:
                for item in value["items"].values():
                    item["claims"] = []
        else:
            targets = [target for row in data["draft"]["items"] for target in [row["issueId"] + ":title",
                *(row["issueId"] + ":claim:" + str(i) for i in range(len(row["claims"])))] ]
            value = {"checks": {target: {"targetId": target, "verdict": "SUPPORTED", "typeAppropriate": True,
                "temporalAppropriate": True, "noUnsupportedNumbers": True, "noInvestmentAdvice": True,
                "reason": "직접 작성한 합성 원문과 일치하는 시험 응답"} for target in targets}}
            if self.semantic_failure:
                name, verdict = self.semantic_failure
                value["checks"][targets[0]][name] = verdict
        return response(value, raw)


class RoundSimulationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.sources = self.root / "sources.jsonl"
        self.clocks = self.root / "registry.json"
        self.html = self.root / "html"
        self.html.mkdir()
        self.output = self.root / "private-output"

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, rows, unverified=()):
        self.sources.write_bytes(b"\n".join(sim.canonical(row) for row in rows) + b"\n")
        source_sha = sim.digest(self.sources.read_bytes())
        records = []
        for row in rows:
            html = ("<meta property='article:published_time' content='" + row["authoredPublishedAt"] + "'>").encode()
            sha = sim.digest(html)
            (self.html / (sha + ".html")).write_bytes(html)
            records.append({"schemaVersion": "zoop-publication-clock-v1", "sourceFileSha256": source_sha,
                "documentId": row["documentId"], "bodySha256": row["bodySha256"], "url": row["url"],
                "status": "unverified" if row["documentId"] in unverified else "verified_timestamp",
                "publishedAt": None if row["documentId"] in unverified else row["authoredPublishedAt"],
                "checkedAt": "2026-10-16T00:00:00Z", "htmlSha256": sha, "httpStatus": 200,
                "declarations": [{"value": row["authoredPublishedAt"], "source": "authored-meta"}],
                "finalUrl": row["url"], "meaning": "Current publisher date declaration observed; unchanged historical body unproven"})
        self.clocks.write_bytes(sim.canonical({"schemaVersion": "zoop-publication-clock-registry-v1",
            "sourceFileSha256": source_sha, "records": records}))

    def args(self, execute=False):
        values = ["--sources", str(self.sources), "--clocks", str(self.clocks), "--output", str(self.output),
                  "--user-inbox-ref", "inbox/authored-publication-simulation.md"]
        if execute:
            values.append("--execute-authorized-simulation")
        return sim.parser().parse_args(values)

    def test_fourteen_windows_have_explicit_baseline_and_open_left_boundary(self):
        self.prepare([source("boundary-am", "2026-10-02T09:20:00+09:00"),
                      source("boundary-pm", "2026-10-02T17:30:00+09:00")])
        rows, unknown, _ = sim.load_inputs(self.sources, self.clocks)
        windows = sim.windows()
        self.assertEqual(14, len(windows))
        self.assertEqual(sim.BASELINE, windows[0]["window"]["from"])
        self.assertFalse(windows[0]["window"]["openStart"])
        self.assertEqual(["boundary-am"], [r["documentId"] for r in sim.pool_for_round(rows, windows[0], len(unknown))[0]])
        self.assertEqual(["boundary-pm"], [r["documentId"] for r in sim.pool_for_round(rows, windows[1], len(unknown))[0]])
        self.assertEqual([], sim.pool_for_round(rows, windows[2], len(unknown))[0])

    def test_deduplication_occurs_after_window_split(self):
        same = "같은 본문을 가진 합성 문서이며 각 발행 선언 시각은 서로 다릅니다. " * 5
        self.prepare([source("morning-copy", "2026-10-02T09:00:00+09:00", same),
                      source("evening-copy", "2026-10-02T10:00:00+09:00", same)])
        rows, unknown, _ = sim.load_inputs(self.sources, self.clocks)
        self.assertEqual(1, len(sim.pool_for_round(rows, sim.windows()[0], len(unknown))[0]))
        self.assertEqual(1, len(sim.pool_for_round(rows, sim.windows()[1], len(unknown))[0]))

    def test_unknown_clock_is_global_coverage_not_a_normal_zero(self):
        self.prepare([source("unknown", "2026-10-02T09:00:00+09:00")], {"unknown"})
        transport = AuthoredTransport()
        result = sim.run(self.args(True), transport)
        bundle = sim.base.strict_load((self.output / "bundle-v2.json").read_bytes())
        self.assertEqual(14, result["heldSourceCoverageRounds"])
        self.assertTrue(all(row["selectionStatus"] == "HELD_SOURCE_COVERAGE" for row in bundle["rounds"]))
        self.assertEqual([], transport.requests)

    def test_full_round_simulation_keeps_am_pm_separate_and_previous_is_immediate_pass(self):
        self.prepare([source("morning", "2026-10-02T09:00:00+09:00"), source("evening", "2026-10-02T10:00:00+09:00"),
                      source("unknown", "2026-10-03T10:00:00+09:00")], {"unknown"})
        transport = AuthoredTransport()
        result = sim.run(self.args(True), transport)
        self.assertEqual(2, result["selectedRounds"])
        self.assertEqual(8, result["newPaidCalls"])
        bundle_bytes = (self.output / "bundle-v2.json").read_bytes()
        bundle = sim.base.strict_load(bundle_bytes)
        morning, evening, held, after_held = bundle["rounds"][:4]
        self.assertNotEqual(morning["selected"][0]["issueId"], evening["selected"][0]["issueId"])
        self.assertEqual("unavailable", morning["previous"]["status"])
        self.assertEqual(morning["resultSha256"], evening["previous"]["resultSha256"])
        self.assertEqual(morning["roundId"], evening["previous"]["roundId"])
        self.assertEqual("available", held["previous"]["status"])
        self.assertEqual("unavailable", after_held["previous"]["status"])
        self.assertTrue(bundle["retrospectiveBodies"])
        self.assertFalse(bundle["operationalCollectionGate"])
        self.assertEqual(4, len(morning["receipts"]))
        self.assertEqual(2, len(morning["result"]["usage"]))
        self.assertTrue(all(receipt["stage"].endswith(("_generation", "_verification")) for receipt in morning["result"]["usage"]))
        for raw in transport.requests:
            request = sim.base.strict_load(raw)
            data = sim.base.strict_load(request["input"])
            self.assertIn(data["context"]["edition"], ("morning", "evening"))
            self.assertEqual(data["contextSha256"], sim.digest(sim.canonical(data["context"])))
            stage = request["text"]["format"]["name"]
            if stage.endswith("_generation"):
                self.assertIn("envelope/metadata", request["instructions"])
                self.assertIn("제목·claims에는 이번 sources에서 확인한 내용만", request["instructions"])
            elif stage.endswith("_verification"):
                self.assertIn("그 자체만을 이유로 false를 주지 않는다", request["instructions"])
                self.assertIn("사건 시점 왜곡", request["instructions"])
                self.assertIn("여전히 UNSUPPORTED", request["instructions"])
        replay = sim.run(self.args(True), transport)
        self.assertEqual(0, replay["newPaidCalls"])
        self.assertEqual(8, len(transport.requests))
        self.assertEqual(bundle_bytes, (self.output / "bundle-v2.json").read_bytes())

    def test_partial_round_record_recovery_reuses_all_receipts_and_keeps_result_hash(self):
        self.prepare([source("morning", "2026-10-02T09:00:00+09:00")])
        transport = AuthoredTransport()
        sim.run(self.args(True), transport)
        before = (self.output / "bundle-v2.json").read_bytes()
        directory = self.output / "2026-10-02-morning"
        (directory / "round.json").unlink()
        (directory / "round.binding.json").unlink()
        result = sim.run(self.args(True), transport)
        self.assertEqual(0, result["newPaidCalls"])
        self.assertEqual(4, len(transport.requests))
        self.assertEqual(before, (self.output / "bundle-v2.json").read_bytes())

    def test_insufficient_claims_are_held_without_fabrication_or_semantic_pass(self):
        self.prepare([source("morning", "2026-10-02T09:00:00+09:00")])
        transport = AuthoredTransport(insufficient=True)
        result = sim.run(self.args(True), transport)
        self.assertEqual(1, result["heldValidationRounds"])
        self.assertEqual(3, result["newPaidCalls"])
        bundle = sim.base.strict_load((self.output / "bundle-v2.json").read_bytes())
        self.assertEqual("HELD_VALIDATION", bundle["rounds"][0]["selectionStatus"])
        self.assertIsNone(bundle["rounds"][0]["result"])
        self.assertFalse(any(sim.base.strict_load(raw)["text"]["format"]["name"].endswith("_verification") for raw in transport.requests))

    def test_importance_two_hold_gets_full_body_review_and_only_exact_new_evidence_is_selected(self):
        marker = "본문 재검토 근거: "
        full = ("확정 조건이 없는 합성 보도의 배경 설명입니다. " * 70) + marker + \
               ("시험 기업이 계약 계획을 발표했습니다. 새 계약은 계획 단계입니다. " * 3) + \
               ("추가 정보가 없는 합성 자료의 일반 안내입니다. " * 70)
        self.prepare([source("hold-full-body", "2026-10-02T09:00:00+09:00", full)])
        transport = AuthoredTransport(held=True, quote_marker=marker)
        result = sim.run(self.args(True), transport)
        bundle = sim.base.strict_load((self.output / "bundle-v2.json").read_bytes())
        first = bundle["rounds"][0]
        self.assertEqual(1, result["selectedRounds"])
        self.assertEqual("SELECTED", first["selectionStatus"])
        self.assertEqual("PASS", first["result"]["verification"]["status"])
        assessment_request = sim.base.strict_load(sim.base.strict_load(transport.requests[0])["input"])
        self.assertTrue(all(marker not in text for text in assessment_request["documents"][0]["excerpts"]))
        review_request = sim.base.strict_load(sim.base.strict_load(transport.requests[1])["input"])
        self.assertEqual("HOLD", review_request["documents"][0]["assessment"]["status"])
        self.assertIn(marker, review_request["documents"][0]["body"])
        citation = first["selected"][0]["sources"][0]
        self.assertTrue(citation["quote"].startswith(marker))
        self.assertEqual(citation["quote"], full[citation["start"]:citation["end"]])
        identity = sim.base.strict_load((self.output / "run-identity.json").read_bytes())
        self.assertEqual(sim.SHORTLIST_POLICY, identity["shortlistPolicy"])

    def test_importance_two_hold_full_body_without_support_remains_held_and_is_not_filled(self):
        body = "시험 기업의 계약 협의 가능성만 언급됐으며, 구체적인 조건이나 확정 발표는 없는 합성 자료입니다. " * 30
        self.prepare([source("hold-unresolved", "2026-10-02T09:00:00+09:00", body),
                      source("unknown-source", "2026-10-03T10:00:00+09:00")], {"unknown-source"})
        transport = AuthoredTransport(held=True, select_none=True)
        result = sim.run(self.args(True), transport)
        bundle = sim.base.strict_load((self.output / "bundle-v2.json").read_bytes())
        first = bundle["rounds"][0]
        self.assertEqual(2, result["newPaidCalls"])
        self.assertEqual("HELD_SOURCE_COVERAGE", first["selectionStatus"])
        self.assertEqual([], first["selected"])
        self.assertIsNone(first["result"])
        review_request = sim.base.strict_load(sim.base.strict_load(transport.requests[1])["input"])
        self.assertEqual("HOLD", review_request["documents"][0]["assessment"]["status"])
        self.assertFalse(any(sim.base.strict_load(raw)["text"]["format"]["name"].endswith("_generation") for raw in transport.requests))

    def test_simulation_clarification_does_not_bypass_temporal_or_source_support_failure(self):
        for name, value in (("temporalAppropriate", False), ("verdict", "UNSUPPORTED")):
            with self.subTest(failed_check=name):
                self.prepare([source("morning", "2026-10-02T09:00:00+09:00")])
                args = self.args(True)
                args.output = self.root / ("failure-" + name)
                transport = AuthoredTransport(semantic_failure=(name, value))
                result = sim.run(args, transport)
                bundle = sim.base.strict_load((args.output / "bundle-v2.json").read_bytes())
                self.assertEqual(1, result["heldValidationRounds"])
                self.assertEqual("HELD_VALIDATION", bundle["rounds"][0]["selectionStatus"])
                self.assertIsNone(bundle["rounds"][0]["result"])

    def test_known_inexact_quote_is_corrected_once_with_same_bodies_and_complete_history(self):
        self.prepare([source("morning", "2026-10-02T09:00:00+09:00"), source("evening", "2026-10-02T10:00:00+09:00")])
        transport = AuthoredTransport(quote_errors=1, quote_error_document="evening")
        result = sim.run(self.args(True), transport)
        self.assertEqual(2, result["selectedRounds"])
        self.assertEqual(9, result["newPaidCalls"])
        raw_bundle = (self.output / "bundle-v2.json").read_bytes()
        bundle = sim.base.strict_load(raw_bundle)
        morning, evening = bundle["rounds"][:2]
        audit = evening["selectionCorrections"][0]
        self.assertEqual("PASS", audit["status"])
        self.assertEqual(5, len(evening["receipts"]))
        calls = self.output / "calls"
        original = sim.base.strict_load((calls / (audit["originalRequestDigest"] + ".request.json")).read_bytes())
        corrected = sim.base.strict_load((calls / (audit["correctedRequestDigest"] + ".request.json")).read_bytes())
        original_data, corrected_data = (sim.base.strict_load(value["input"]) for value in (original, corrected))
        self.assertEqual(original_data["documents"], corrected_data["documents"])
        self.assertEqual(original_data["contextSha256"], corrected_data["contextSha256"])
        self.assertEqual(original["instructions"], corrected["instructions"])
        self.assertEqual(audit["originalResponseSha256"], sim.digest((calls / (audit["originalRequestDigest"] + ".response.json")).read_bytes()))
        self.assertEqual("citation_is_not_exact_original_substring", corrected_data["selectionStructuralCorrection"]["reason"])
        citation = evening["selected"][0]["sources"][0]
        self.assertEqual(source("evening", "2026-10-02T10:00:00+09:00")["body"][citation["start"]:citation["end"]], citation["quote"])
        self.assertEqual(morning["resultSha256"], evening["previous"]["resultSha256"])
        self.assertEqual(0, sim.run(self.args(True), transport)["newPaidCalls"])
        self.assertEqual(9, len(transport.requests))
        self.assertEqual(raw_bundle, (self.output / "bundle-v2.json").read_bytes())

    def test_second_inexact_quote_holds_only_that_round_and_continues_without_older_previous(self):
        self.prepare([source("morning", "2026-10-02T09:00:00+09:00"), source("evening", "2026-10-02T10:00:00+09:00")])
        transport = AuthoredTransport(quote_errors=2)
        result = sim.run(self.args(True), transport)
        bundle = sim.base.strict_load((self.output / "bundle-v2.json").read_bytes())
        morning, evening = bundle["rounds"][:2]
        self.assertEqual(1, result["heldValidationRounds"])
        self.assertEqual("HELD_VALIDATION", morning["selectionStatus"])
        self.assertIsNone(morning["result"])
        self.assertEqual(3, len(morning["receipts"]))
        self.assertEqual("WITHHELD", morning["selectionCorrections"][0]["status"])
        self.assertEqual("SELECTED", evening["selectionStatus"])
        self.assertEqual("unavailable", evening["previous"]["status"])
        self.assertEqual(7, result["newPaidCalls"])

    def test_unknown_or_failed_selection_is_never_corrected_or_resent_from_cache(self):
        self.prepare([source("morning", "2026-10-02T09:00:00+09:00")])
        for failure in ("unknown", "http"):
            with self.subTest(failure=failure):
                args = self.args(True)
                args.output = self.root / ("transport-" + failure)
                transport = AuthoredTransport(selection_transport_failure=failure)
                with self.assertRaises(sim.ReplayError):
                    sim.run(args, transport)
                self.assertEqual(2, len(transport.requests))
                with self.assertRaises(sim.ReplayError):
                    sim.run(args, transport)
                self.assertEqual(2, len(transport.requests))
                self.assertFalse((args.output / "bundle-v2.json").exists())

    def test_source_clock_or_html_tampering_fails_before_key_or_network(self):
        self.prepare([source("document", "2026-10-02T09:00:00+09:00")])
        record = sim.base.strict_load(self.clocks.read_bytes())["records"][0]
        (self.html / (record["htmlSha256"] + ".html")).write_bytes(b"tampered authored html")
        with patch.object(sim.base, "authenticated_transport") as transport:
            with self.assertRaisesRegex(sim.ReplayError, "html_digest_mismatch"):
                sim.run(self.args(True))
            transport.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_naive_and_date_only_are_not_accepted_as_exact_publication_clock(self):
        self.prepare([source("document", "2026-10-02T09:00:00")])
        with self.assertRaises(sim.ReplayError):
            sim.load_inputs(self.sources, self.clocks)
        registry = sim.base.strict_load(self.clocks.read_bytes())
        registry["records"][0]["status"] = "date_only"
        registry["records"][0]["publishedAt"] = None
        self.clocks.write_bytes(sim.canonical(registry))
        rows, unknown, _ = sim.load_inputs(self.sources, self.clocks)
        self.assertEqual([], rows)
        self.assertEqual(1, len(unknown))

    def test_importance_precedes_priority_and_missing_canonical_is_not_invented(self):
        pool = [{**source("wide", "2026-10-02T09:00:00+09:00"), "companyNames": [], "dateContext": {}},
                {**source("narrow", "2026-10-02T09:00:00+09:00"), "companyNames": [], "dateContext": {}}]
        values = [{"documentId": "wide", "status": "ELIGIBLE", "importance": 3, "priority": 10, "eventKey": "wide"},
                  {"documentId": "narrow", "status": "ELIGIBLE", "importance": 2, "priority": 99, "eventKey": "narrow"}]
        candidates = sim.shortlist_round(values, pool)
        self.assertEqual("wide", candidates[0]["documentId"])
        self.assertNotIn("canonicalId", candidates[0])

    def test_budget_preflight_prevents_network_creation(self):
        self.prepare([source("document", "2026-10-02T09:00:00+09:00")])
        args = self.args(True)
        args.max_calls = 1
        with patch.object(sim.base, "authenticated_transport") as transport:
            with self.assertRaisesRegex(sim.ReplayError, "planned_calls_exceed_explicit_budget"):
                sim.run(args)
            transport.assert_not_called()

    def test_offline_audit_does_not_use_model_transport(self):
        self.prepare([source("document", "2026-10-02T09:00:00+09:00")])
        transport = AuthoredTransport()
        result = sim.run(self.args(), transport)
        self.assertEqual("OFFLINE_PUBLICATION_CLOCK_AUDIT", result["status"])
        self.assertEqual([], transport.requests)


if __name__ == "__main__":
    unittest.main()
