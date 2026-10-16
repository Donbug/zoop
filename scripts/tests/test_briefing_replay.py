"""Offline authored examples only: no credentials, external sources or paid provider requests."""

import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "briefing_replay.py"
SPEC = importlib.util.spec_from_file_location("briefing_replay", MODULE)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def record(document_id="authored-document", body=None):
    body = body or ("합성 시험용 원문입니다. 시험 기업은 새로운 계약 계획을 발표했습니다. 이 자료는 실제 뉴스가 아닙니다. " * 4)
    return {"documentId": document_id, "body": body, "bodySha256": replay.digest(body.encode()),
            "url": "https://example.invalid/authored", "title": "합성 계약 계획", "sourceKind": "news",
            "companyAssociations": [{"companyName": "시험 기업"}], "allowModelSend": False, "rightsStatus": "unconfirmed",
            "providerEstimatedCalendarDatesKST": ["2026-10-05"], "bodyAcquiredAt": "2026-10-16T00:00:00Z"}


def response(value, request, usage=True):
    out = {"id": "authored-response-" + replay.digest(request)[:16], "status": "completed",
           "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value, ensure_ascii=False)}]}]}
    if usage:
        out["usage"] = {"input_tokens": 100, "output_tokens": 50, "output_tokens_details": {"reasoning_tokens": 5}}
    return 200, replay.canonical(out)


class AuthoredTransport:
    def __init__(self):
        self.requests = []

    def __call__(self, raw):
        self.requests.append(raw)
        request = replay.strict_load(raw)
        assert request["store"] is False and request["model"] == "gpt-6-luna"
        data = replay.strict_load(request["input"])
        stage = request["text"]["format"]["name"]
        if stage == "briefing_population_importance":
            value = {"assessments": [{"documentId": row["documentId"], "importance": 2, "priority": 75,
                                     "status": "ELIGIBLE", "eventKey": row["documentId"], "headline": "합성 계약 계획",
                                     "reason": "원문에 확인되는 시험 계획", "scope": "COMPANY", "affectedSectors": [],
                                     "transmission": "", "limitations": ["합성 자료이며 날짜는 추정입니다."]}
                                    for row in data["documents"]]}
            if request["text"]["format"]["schema"]["properties"]["assessments"]["type"] == "object":
                value["assessments"] = {item["documentId"]: item for item in value["assessments"]}
        elif stage == "briefing_global_selection":
            row = data["documents"][0]
            value = {"selected": [{"eventKey": "authored-event", "title": "합성 계약 계획", "reason": "시험 계약 계획 확인",
                                   "importance": 2, "priority": 75, "companyNames": row["companyNames"],
                                   "limitations": ["합성 자료이며 운영 발행이 아닙니다."],
                                   "sources": [{"documentId": row["documentId"], "quotes": [row["body"][:110]]}]}], "held": []}
        elif stage.endswith("_generation"):
            value = {"items": [{"issueId": row["issueId"], "rank": row["rank"], "title": "합성 시험 계약 계획",
                                "titleEvidenceIds": [row["sources"][0]["evidenceId"]],
                                "claims": [{"text": "시험 기업이 계약 계획을 발표했습니다.", "type": "fact",
                                            "evidenceIds": [row["sources"][0]["evidenceId"]]},
                                           {"text": "이 계약은 합성 시험의 계획 단계입니다.", "type": "plan",
                                            "evidenceIds": [row["sources"][0]["evidenceId"]]}]} for row in data["selected"]]}
        else:
            ids = []
            for item in data["draft"]["items"]:
                ids.append(item["issueId"] + ":title")
                ids.extend(item["issueId"] + ":claim:" + str(index) for index in range(len(item["claims"])))
            value = {"checks": [{"targetId": target, "verdict": "SUPPORTED", "typeAppropriate": True,
                                 "temporalAppropriate": True, "noUnsupportedNumbers": True, "noInvestmentAdvice": True,
                                 "reason": "직접 작성한 합성 인용과 일치하는 시험 응답"} for target in ids]}
        return response(value, raw)


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "private"
        replay.private_dir(self.output)
        self.sources = self.root / "authored.jsonl"
        self.sources.write_bytes(replay.canonical(record()) + b"\n")

    def tearDown(self):
        self.temp.cleanup()

    def args(self, execute=True):
        args = ["--sources", str(self.sources), "--output", str(self.output), "--user-inbox-ref", "inbox/authored-test.md"]
        if execute:
            args.append("--execute-authorized-development")
        return replay.parser().parse_args(args)

    def test_population_preserves_denied_original_permissions_and_uncertain_dates(self):
        rows, audit = replay.population(self.sources)
        self.assertEqual(1, len(rows))
        original = audit["records"][0]["sourceMetadata"]
        self.assertIs(original["allowModelSend"], False)
        self.assertEqual("unconfirmed", original["rightsStatus"])
        self.assertEqual("provider_estimated_date", rows[0]["dateContext"]["precision"])

    def test_duplicates_and_hash_mismatch_are_audited_before_any_model_call(self):
        one = record()
        duplicate = record("duplicate", one["body"])
        bad = {**record("bad", "다른 원문이 있는 합성 자료 " * 12), "bodySha256": "0" * 64}
        self.sources.write_bytes(b"\n".join(replay.canonical(row) for row in [one, duplicate, bad]))
        rows, audit = replay.population(self.sources)
        self.assertEqual(1, len(rows))
        self.assertEqual([None, "duplicate_exact_body", "body_hash_mismatch"], [row["exclusionReason"] for row in audit["records"]])

    def test_offline_default_never_uses_transport(self):
        transport = AuthoredTransport()
        result = replay.run(self.args(False), transport)
        self.assertEqual("OFFLINE_AUDIT_ONLY", result["status"])
        self.assertEqual([], transport.requests)

    def test_weekly_real_execution_is_rejected_before_key_source_or_output_access(self):
        existing_key = self.root / "existing-private-key.env"
        existing_key.write_text("OPENAI_API_KEY=synthetic-never-read\n")
        existing_key.chmod(0o600)
        for index, key in enumerate((self.root / "missing-key.env", existing_key)):
            args = self.args()
            target = self.root / ("must-not-be-created-" + str(index))
            args.output, args.key_file = str(target), str(key)
            with patch.object(replay, "private_dir") as directories, \
                    patch.object(replay, "regular") as reads, \
                    patch.object(replay, "read_key") as keys, \
                    patch.object(replay, "authenticated_transport") as network:
                with self.assertRaisesRegex(replay.ReplayError, "^weekly_pool_execution_disabled_use_per_round$"):
                    replay.run(args)
                directories.assert_not_called()
                reads.assert_not_called()
                keys.assert_not_called()
                network.assert_not_called()
            self.assertFalse(target.exists())

    def test_cli_main_rejects_weekly_paid_execution_without_side_effects(self):
        target = self.root / "cli-must-not-create-output"
        stderr = io.StringIO()
        argv = [str(MODULE), "--sources", str(self.root / "missing-source.jsonl"), "--output", str(target),
                "--key-file", str(self.root / "missing-key.env"), "--user-inbox-ref", "inbox/authored.md",
                "--execute-authorized-development"]
        with patch.object(replay.sys, "argv", argv), redirect_stderr(stderr), \
                patch.object(replay, "authenticated_transport") as network, patch.object(replay, "read_key") as keys:
            self.assertEqual(2, replay.main())
            network.assert_not_called()
            keys.assert_not_called()
        self.assertEqual("weekly_pool_execution_disabled_use_per_round", json.loads(stderr.getvalue())["reason"])
        self.assertFalse(target.exists())

    def test_entire_pipeline_and_same_output_resume_are_byte_identical(self):
        transport = AuthoredTransport()
        result = replay.run(self.args(), transport)
        self.assertEqual("PASS", result["status"])
        self.assertTrue(result["paidCallsMade"])
        self.assertEqual(6, result["newPaidCalls"])
        self.assertEqual(1, result["selectedCount"])
        before = (self.output / "bundle.json").read_bytes()
        second = replay.run(self.args(), transport)
        self.assertEqual("PASS", second["status"])
        self.assertEqual(0, second["newPaidCalls"])
        self.assertFalse(second["paidCallsMade"])
        self.assertEqual(6, len(transport.requests))
        self.assertEqual(before, (self.output / "bundle.json").read_bytes())
        bundle = replay.strict_load(before)
        self.assertIsNone(bundle["graphVersion"])
        self.assertFalse(bundle["authorization"]["productionAuthorized"])
        self.assertTrue(all("newCallThisProcess" not in receipt for receipt in bundle["receipts"]))
        self.assertTrue(all(value["verification"]["status"] == "PASS" for value in bundle["editions"].values()))

    def test_pending_unknown_attempt_prevents_a_second_transport_call(self):
        calls = []

        def failed(raw):
            calls.append(raw)
            raise OSError("private provider error text")

        client = replay.ResponsesClient(self.output, failed)
        for _ in range(2):
            with self.assertRaises(replay.ReplayError):
                client.call("briefing_population_importance", {}, "importance.md", "importance.schema.json")
        self.assertEqual(1, len(calls))
        self.assertIsNone(client.receipts()[0]["inputTokens"])

    def test_missing_usage_remains_unknown_and_does_not_retry(self):
        calls = []

        def no_usage(raw):
            calls.append(raw)
            return response({"assessments": []}, raw, False)

        client = replay.ResponsesClient(self.output, no_usage)
        for _ in range(2):
            with self.assertRaises(replay.ReplayError):
                client.call("briefing_population_importance", {}, "importance.md", "importance.schema.json")
        self.assertEqual(1, len(calls))
        self.assertFalse(client.receipts()[0]["usageKnown"])
        self.assertIsNone(client.receipts()[0]["outputTokens"])

    def test_unknown_attempt_also_stops_different_queued_requests(self):
        calls = []

        def failed(raw):
            calls.append(raw)
            raise OSError("authored unknown outcome")

        client = replay.ResponsesClient(self.output, failed)
        for document in ("first", "different-next-batch"):
            with self.assertRaises(replay.ReplayError):
                client.call("briefing_population_importance", {"document": document}, "importance.md", "importance.schema.json")
        self.assertEqual(1, len(calls))

    def test_exact_quote_offsets_use_unicode_code_points_and_reject_rewriting(self):
        row = record(body="😀 앞말 " + "정확한 한국어 인용과 조건을 보존하는 합성 원문입니다. " * 5)
        self.sources.write_bytes(replay.canonical(row))
        rows, _ = replay.population(self.sources)
        candidate = {"documentId": row["documentId"]}
        quote = row["body"][5:65]
        choice = {"eventKey": "authored-event", "title": "제목", "reason": "사유", "importance": 2, "priority": 50,
                  "companyNames": [], "limitations": ["합성"], "sources": [{"documentId": row["documentId"], "quotes": [quote]}]}
        selected = replay.freeze_selection({"selected": [choice]}, [candidate], rows, "0" * 64)
        source = selected[0]["sources"][0]
        self.assertEqual(5, source["start"])
        self.assertEqual(quote, row["body"][source["start"]:source["end"]])
        choice["sources"][0]["quotes"] = ["실제 원문에는 없지만 그럴듯하게 재작성한 부정확한 인용문입니다."]
        with self.assertRaises(replay.ReplayError):
            replay.freeze_selection({"selected": [choice]}, [candidate], rows, "0" * 64)

    def test_verification_must_cover_every_title_and_claim(self):
        draft = {"items": [{"issueId": "event", "claims": [{}, {}]}]}
        with self.assertRaises(replay.ReplayError):
            replay.semantic_passed(draft, {"checks": []})

    def test_batch_schema_binds_exact_document_ids_and_count(self):
        rows, _ = replay.population(self.sources)
        transport = AuthoredTransport()
        client = replay.ResponsesClient(self.output, transport)
        values = replay.assess_all(client, rows, {"scope": "development_replay"})
        self.assertEqual(1, len(values))
        request = replay.strict_load(transport.requests[0])
        schema = request["text"]["format"]["schema"]["properties"]["assessments"]
        self.assertEqual("object", schema["type"])
        self.assertEqual([rows[0]["documentId"]], schema["required"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual([rows[0]["documentId"]], schema["properties"][rows[0]["documentId"]]["properties"]["documentId"]["enum"])
        self.assertEqual(12000, request["max_output_tokens"])

    def test_completed_bad_coverage_gets_new_constraints_and_three_good_batches_reuse(self):
        documents = [record(f"authored-{index}", (f"직접 작성한 합성 시험 원문 번호 {index}입니다. 실제 뉴스가 아닙니다. " * 4))
                     for index in range(100)]
        self.sources.write_bytes(b"\n".join(replay.canonical(row) for row in documents))
        rows, _ = replay.population(self.sources)
        authorization = {"scope": "development_replay"}
        authored = AuthoredTransport()
        static_requests = []

        def static_transport(raw):
            static_requests.append(raw)
            _, body = authored(raw)
            value = replay.output_of(replay.strict_load(body))
            if len(static_requests) == 1:
                value["assessments"].pop()
            elif len(static_requests) == 2:
                value["assessments"][0]["documentId"] = "invented-by-authored-test"
            return response(value, raw)

        initial = replay.ResponsesClient(self.output, static_transport)
        for offset in range(0, 100, 20):
            initial.call("briefing_population_importance", replay.assessment_input(rows[offset:offset + 20], authorization),
                         "importance.md", "importance.schema.json")
        before = {path.name: path.read_bytes() for path in initial.calls.glob("*.complete.json")}
        correction_transport = AuthoredTransport()
        corrected = replay.ResponsesClient(self.output, correction_transport)
        values = replay.assess_all(corrected, rows, authorization, 20, 3)
        self.assertEqual(100, len(values))
        self.assertEqual({row["documentId"] for row in rows}, {value["documentId"] for value in values})
        self.assertEqual(2, len(correction_transport.requests))
        self.assertEqual(7, len(corrected.receipts()))
        self.assertEqual(700, sum(value["inputTokens"] for value in corrected.receipts()))
        self.assertEqual(2, len(list((self.output / "coverage-repairs").glob("*.json"))))
        for name, old in before.items():
            self.assertEqual(old, (initial.calls / name).read_bytes())
        final_transport = AuthoredTransport()
        final = replay.ResponsesClient(self.output, final_transport)
        self.assertEqual(values, replay.assess_all(final, rows, authorization, 20, 3))
        self.assertEqual([], final_transport.requests)

    def test_duplicate_ids_are_rejected_even_when_enum_and_array_length_match(self):
        expected = {"first", "second"}
        problem = replay.assessment_coverage([{"documentId": "first"}, {"documentId": "first"}], expected)
        self.assertEqual(["second"], problem["missingDocumentIds"])
        self.assertEqual(["first"], problem["duplicateDocumentIds"])
        self.assertEqual([], problem["inventedDocumentIds"])

    def test_unknown_static_reservation_cannot_escape_through_a_dynamic_request(self):
        rows, _ = replay.population(self.sources)
        authorization = {"scope": "development_replay"}

        def failed(raw):
            raise OSError("authored unknown transport")

        initial = replay.ResponsesClient(self.output, failed)
        with self.assertRaises(replay.ReplayError):
            initial.call("briefing_population_importance", replay.assessment_input(rows, authorization),
                         "importance.md", "importance.schema.json")
        transport = AuthoredTransport()
        client = replay.ResponsesClient(self.output, transport)
        with self.assertRaises(replay.ReplayError):
            replay.assess_all(client, rows, authorization)
        self.assertEqual([], transport.requests)

    def test_completed_duplicate_array_is_corrected_by_required_id_object(self):
        other = record("second", "별도 직접 작성한 합성 시험 원문입니다. 실제 경제 소식이 아닌 시험 자료입니다. " * 4)
        self.sources.write_bytes(replay.canonical(record()) + b"\n" + replay.canonical(other))
        rows, _ = replay.population(self.sources)
        authorization = {"scope": "development_replay"}
        data = replay.assessment_input(rows, authorization)
        array_schema, _ = replay.importance_batch_schemas({row["documentId"] for row in rows})
        authored = AuthoredTransport()

        def duplicate(raw):
            _, body = authored(raw)
            value = replay.output_of(replay.strict_load(body))
            value["assessments"][1] = dict(value["assessments"][0])
            return response(value, raw)

        initial = replay.ResponsesClient(self.output, duplicate)
        initial.call("briefing_population_importance", data, "importance.md", "importance.schema.json", schema_override=array_schema)
        original = {p.name: p.read_bytes() for p in initial.calls.glob("*.complete.json")}
        transport = AuthoredTransport()
        client = replay.ResponsesClient(self.output, transport)
        values = replay.assess_all(client, rows, authorization)
        self.assertEqual(2, len(values))
        self.assertEqual(1, len(transport.requests))
        self.assertEqual("object", replay.strict_load(transport.requests[0])["text"]["format"]["schema"]["properties"]["assessments"]["type"])
        for name, before in original.items():
            self.assertEqual(before, (initial.calls / name).read_bytes())
        final = replay.ResponsesClient(self.output, transport)
        self.assertEqual(values, replay.assess_all(final, rows, authorization))
        self.assertEqual(1, len(transport.requests))

    def test_known_output_truncation_requires_exact_digest_authorization(self):
        rows, _ = replay.population(self.sources)
        authorization = {"scope": "development_replay", "userInboxRef": "inbox/authored.md", "sourceSha256": "0" * 64}
        data = replay.assessment_input(rows, authorization)
        array_schema, _ = replay.importance_batch_schemas({row["documentId"] for row in rows})

        def truncated(raw):
            return 200, replay.canonical({"id": "authored-truncated", "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "usage": {"input_tokens": 100, "output_tokens": 8000},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"assessments":['}]}]})

        initial = replay.ResponsesClient(self.output, truncated)
        key = initial.request_digest("briefing_population_importance", data, "importance.md", "importance.schema.json", schema_override=array_schema)
        with self.assertRaises(replay.ReplayError):
            initial.call("briefing_population_importance", data, "importance.md", "importance.schema.json", schema_override=array_schema)
        original = (initial.calls / (key + ".complete.json")).read_bytes()
        transport = AuthoredTransport()
        without_permission = replay.ResponsesClient(self.output, transport)
        with self.assertRaises(replay.ReplayError):
            replay.assess_all(without_permission, rows, authorization)
        self.assertEqual([], transport.requests)
        corrected = replay.ResponsesClient(self.output, transport, authorized_truncations={key})
        self.assertEqual(1, len(replay.assess_all(corrected, rows, authorization)))
        self.assertEqual(1, len(transport.requests))
        self.assertEqual(original, (initial.calls / (key + ".complete.json")).read_bytes())
        audit = replay.coverage_corrections(corrected, authorization)[0]
        self.assertEqual("operator_authorized_known_output_truncation", audit["reason"])
        self.assertEqual("max_output_tokens", audit["originalIncompleteReason"])
        self.assertEqual("incomplete", audit["originalStatus"])
        self.assertEqual(8050, sum(row["outputTokens"] for row in corrected.receipts()))

    def test_pending_array_cannot_be_hidden_by_a_good_static_cache(self):
        rows, _ = replay.population(self.sources)
        authorization = {"scope": "development_replay"}
        data = replay.assessment_input(rows, authorization)
        array_schema, _ = replay.importance_batch_schemas({row["documentId"] for row in rows})
        replay.ResponsesClient(self.output, AuthoredTransport()).call(
            "briefing_population_importance", data, "importance.md", "importance.schema.json")

        def failed(raw):
            raise OSError("unknown authored result")

        with self.assertRaises(replay.ReplayError):
            replay.ResponsesClient(self.output, failed).call(
                "briefing_population_importance", data, "importance.md", "importance.schema.json", schema_override=array_schema)
        transport = AuthoredTransport()
        with self.assertRaises(replay.ReplayError):
            replay.assess_all(replay.ResponsesClient(self.output, transport), rows, authorization)
        self.assertEqual([], transport.requests)

    def test_object_key_and_document_value_must_match(self):
        with self.assertRaises(replay.ReplayError):
            replay.normalize_assessments({"first": {"documentId": "second"}})

    def test_key_file_must_be_regular_and_private(self):
        key = self.root / "authored.env"
        key.write_text("OPENAI_API_KEY=synthetic-test-only\n")
        key.chmod(0o644)
        with self.assertRaises(replay.ReplayError):
            replay.read_key(key)
        key.chmod(0o600)
        self.assertEqual("synthetic-test-only", replay.read_key(key))
        link = self.root / "linked.env"
        link.symlink_to(key)
        with self.assertRaises(replay.ReplayError):
            replay.read_key(link)

    def test_prompt_change_cannot_reuse_an_existing_run_identity(self):
        replay.run(self.args(False))
        prompts = self.root / "prompts"
        prompts.mkdir()
        (prompts / "changed.md").write_text("A different reviewed prompt")
        with patch.object(replay, "PROMPTS", prompts):
            with self.assertRaises(replay.ReplayError):
                replay.run(self.args(False))

    def test_cached_edition_tampering_is_rejected_without_new_paid_calls(self):
        transport = AuthoredTransport()
        replay.run(self.args(), transport)
        path = self.output / "morning.json"
        value = replay.strict_load(path.read_bytes())
        value["items"][0]["title"] = "몰래 바뀐 시험 제목"
        path.write_bytes(replay.canonical(value))
        with self.assertRaises(replay.ReplayError):
            replay.run(self.args(), transport)
        self.assertEqual(6, len(transport.requests))


if __name__ == "__main__":
    unittest.main()
