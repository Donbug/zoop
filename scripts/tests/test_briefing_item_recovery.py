"""Authored item recovery fixtures; no API key or real model transport."""

import importlib.util
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("item_recovery", Path(__file__).resolve().parents[1] / "briefing_item_recovery.py")
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)
base = recovery.base


def selection(key="issue-one", quote="합성기업은 건물 관리 기술 적용 계약을 체결했습니다.", published="2026-10-07T08:00:00+09:00"):
    body = "작성한 합성 원문입니다. " + quote
    sha = base.digest(body.encode())
    clock = {"status": "verified_timestamp", "documentId": "doc-" + key, "bodySha256": sha,
             "publishedAt": published, "checkedAt": "2026-10-20T00:00:00Z"}
    start = body.index(quote)
    proof = {"evidenceId": "ev-" + key, "documentId": "doc-" + key, "documentVersion": "sha256-" + sha,
        "bodySha256": sha, "quote": quote, "start": start, "end": start + len(quote), "offsetUnit": "unicode_code_point",
        "publicationClock": clock, "clockRecordSha256": base.digest(base.canonical(clock)),
        "sourceMetadata": {"oldGeneratedText": "SHOULD_NOT_LEAK_SOURCE_METADATA"}}
    return {"issueId": key, "rank": 3, "title": "SHOULD_NOT_LEAK_SELECTION_TITLE", "reason": "SHOULD_NOT_LEAK_SELECTION_REASON",
            "sources": [proof], "companyLinks": [{"companyId": "authored-company", "name": "합성기업", "role": "계약 당사자",
                "evidenceIds": [proof["evidenceId"]]}]}


def context():
    return {"context": {"date": "2026-10-07", "edition": "morning",
        "window": {"from": "2026-10-06T17:30:00+09:00", "to": "2026-10-07T09:20:00+09:00", "openStart": False},
        "simulatedPreviousOutput": {"title": "SHOULD_NOT_LEAK_PREVIOUS"},
        "recoveryRunId": "authored-recovery", "policyVersion": "item-recovery-v1", "baseBundleSha256": "b" * 64,
        "clockFileSha256": "c" * 64}, "contextSha256": "a" * 64,
        "priorSelectedIssues": [{"body": "SHOULD_NOT_LEAK_OTHER_ROUND"}]}


def item(sel, claim=None, title="합성기업의 기술 적용 계약"):
    evidence = sel["sources"][0]["evidenceId"]
    return {"issueId": sel["issueId"], "rank": 1, "title": title, "titleEvidenceIds": [evidence],
            "claims": [{"text": claim or sel["sources"][0]["quote"], "type": "fact", "evidenceIds": [evidence]}]}


class AuthoredTransport:
    def __init__(self, generation_mutations=None, verification_mutations=None, novelty_decisions=None):
        self.requests = []
        self.generation_mutations = generation_mutations or {}
        self.verification_mutations = verification_mutations or {}
        self.novelty_decisions = novelty_decisions or {}

    def __call__(self, raw):
        self.requests.append(raw)
        request = base.strict_load(raw)
        data = base.strict_load(request["input"])
        stage = request["text"]["format"]["name"]
        if stage == recovery.STAGES["generation"]:
            items = {}
            for sel in data["selections"]:
                draft = item(sel)
                draft.update(self.generation_mutations.get(sel["issueId"], {}))
                items[sel["issueId"]] = draft
            value = {"items": items}
        elif stage == recovery.STAGES["verification"]:
            checks = {}
            for row in data["items"]:
                draft = row["draft"]
                targets = [(row["issueId"] + ":title", draft["title"])] + [
                    (row["issueId"] + ":claim:" + str(i), c["text"]) for i, c in enumerate(draft["claims"])]
                for target, text in targets:
                    checks[target] = {"targetId": target, "checkedText": text, "verdict": "SUPPORTED",
                        "flags": {name: True for name in recovery.FLAGS}, "reason": "현재 합성 인용과 일치", "unsupportedSpan": None}
                    checks[target].update(self.verification_mutations.get(target, {}))
            value = {"checks": checks}
        else:
            old = {s["quote"] for h in data["history"] for s in h["sources"]}
            decisions = {}
            for sel in data["selections"]:
                decision = "REPEAT" if all(s["quote"] in old for s in sel["sources"]) else "NEW"
                decisions[sel["issueId"]] = {"issueId": sel["issueId"], "decision": decision,
                    "reason": "합성 원문의 사건 차이를 비교", "deltaEvidenceIds": []}
                decisions[sel["issueId"]].update(self.novelty_decisions.get(sel["issueId"], {}))
            value = {"decisions": decisions}
        return 200, base.canonical({"id": "authored-" + base.digest(raw)[:16], "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 50}, "output": [{"type": "message",
            "content": [{"type": "output_text", "text": base.canonical(value).decode()}]}]})


class ItemRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "private"

    def tearDown(self):
        self.temp.cleanup()

    def client(self, transport, max_calls=400):
        return recovery.RecoveryClient(self.output, transport, max_calls=max_calls)

    def test_one_claim_is_valid_and_rank_is_normalized_without_mutating_selection(self):
        sel = selection()
        original = base.canonical(sel)
        self.assertEqual(1, recovery.prepare_selections([sel], context())[0]["rank"])
        self.assertEqual(item(sel), recovery.validate_item(item(sel), sel))
        self.assertEqual(original, base.canonical(sel))

    def test_item_identity_citations_lengths_types_and_atomic_sentence_guards(self):
        sel = selection()
        changes = [{"issueId": "foreign"}, {"rank": 2}, {"title": "가" * 81}, {"claims": []},
            {"titleEvidenceIds": ["foreign"]}, {"claims": [{"text": "가" * 251, "type": "fact", "evidenceIds": ["ev-issue-one"]}]},
            {"claims": [{"text": "첫 사실입니다. 두 번째 사실입니다.", "type": "fact", "evidenceIds": ["ev-issue-one"]}]},
            {"claims": [{"text": "합성 사실", "type": "unknown", "evidenceIds": ["ev-issue-one"]}]}]
        for change in changes:
            with self.subTest(change=change):
                draft = item(sel); draft.update(change)
                with self.assertRaises(recovery.ReplayError):
                    recovery.validate_item(draft, sel)

    def test_quantified_conditions_and_english_korean_qualifiers_are_preserved(self):
        for quote, text, valid in [("합성기업 지분은 approximately 3%입니다.", "합성기업 지분은 약 3%입니다.", True),
            ("합성기업 지분은 approximately 3%입니다.", "합성기업 지분은 3%입니다.", False),
            ("합성기업은 최대 5개 건물을 지원합니다.", "합성기업은 5개 건물 이하를 지원합니다.", True),
            ("합성기업은 최대 5개 건물을 지원합니다.", "합성기업은 5개 건물을 지원합니다.", False)]:
            with self.subTest(quote=quote, text=text):
                sel = selection(quote=quote)
                if valid:
                    recovery.validate_item(item(sel, text), sel)
                else:
                    with self.assertRaisesRegex(recovery.ReplayError, "quantified_condition_omitted"):
                        recovery.validate_item(item(sel, text), sel)

    def test_plan_guard_rejects_only_clear_completion_and_keeps_unrelated_current_fact(self):
        planned = selection(quote="합성기업은 계약을 체결할 예정입니다.")
        with self.assertRaisesRegex(recovery.ReplayError, "plan_changed_to_completed_fact"):
            recovery.validate_item(item(planned, "합성기업은 계약을 체결했습니다."), planned)
        mixed = selection(quote="합성기업은 기존 계약을 체결했습니다. 새 제품 출시는 예정입니다.")
        recovery.validate_item(item(mixed, "합성기업은 기존 계약을 체결했습니다."), mixed)

    def test_generation_takes_only_missing_items_and_keeps_one_bad_item_withheld(self):
        good, bad = selection("good"), selection("bad")
        transport = AuthoredTransport(generation_mutations={"bad": {"claims": []}})
        result = recovery.generate_items(self.client(transport), [good, bad], context(),
            prior_failures={"normal": "NORMAL_ITEM_MUST_NOT_ENTER", "bad": "recovery_draft_missing"})
        self.assertEqual(["good"], [x["issueId"] for x in result["items"]])
        self.assertEqual({"good": "PASS", "bad": "WITHHELD"}, result["perIssueStatuses"])
        self.assertEqual([], result["rawReply"]["items"]["bad"]["claims"])
        raw = transport.requests[0].decode()
        self.assertNotIn("NORMAL_ITEM_MUST_NOT_ENTER", raw)
        self.assertNotIn("SHOULD_NOT_LEAK", raw)
        self.assertEqual(8000, base.strict_load(transport.requests[0])["max_output_tokens"])

    def test_fact_verification_uses_current_text_only_and_keeps_other_pass_items(self):
        good, bad = selection("good"), selection("bad")
        transport = AuthoredTransport(verification_mutations={"bad:claim:0": {
            "verdict": "UNSUPPORTED", "unsupportedSpan": "계약", "reason": "실제 현재 문장에 있는 문제 구간"}})
        result = recovery.verify_items(self.client(transport), [good, bad], [item(good), item(bad)], context())
        self.assertEqual({"good": "PASS", "bad": "WITHHELD"}, result["perIssueStatuses"])
        self.assertEqual(4, len(result["checks"]))
        request = base.strict_load(transport.requests[0])
        self.assertEqual(10000, request["max_output_tokens"])
        data = base.strict_load(request["input"])
        self.assertEqual({"schemaVersion", "context", "promptArtifacts", "items"}, set(data))
        self.assertEqual({"issueId", "draft", "sources"}, set(data["items"][0]))
        self.assertNotIn("SHOULD_NOT_LEAK", request["input"])
        self.assertEqual("authored-recovery", data["context"]["recoveryRunId"])

    def test_invented_checked_text_or_unsupported_span_never_fails_another_item(self):
        good, bad = selection("good"), selection("bad")
        for mutation, failure in [({"checkedText": "현재 문장에 없는 과거 문장입니다."}, "checked_text_mismatch"),
                ({"unsupportedSpan": "문장에 없는 표현"}, "invented_unsupported_span")]:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                transport = AuthoredTransport(verification_mutations={"bad:claim:0": mutation})
                client = recovery.RecoveryClient(Path(directory) / "private", transport)
                result = recovery.verify_items(client, [good, bad], [item(good), item(bad)], context())
                self.assertEqual("PASS", result["perIssueStatuses"]["good"])
                self.assertEqual("WITHHELD", result["perIssueStatuses"]["bad"])
                self.assertIn(failure, result["failures"]["bad"])
                self.assertEqual(mutation.get("checkedText", item(bad)["claims"][0]["text"]), result["checks"][-1]["checkedText"])

    def test_missing_invalid_draft_is_withheld_without_rewriting_valid_item(self):
        good, bad = selection("good"), selection("bad")
        transport = AuthoredTransport()
        result = recovery.verify_items(self.client(transport), [good, bad], [item(good)], context())
        self.assertEqual({"good": "PASS", "bad": "WITHHELD"}, result["perIssueStatuses"])
        self.assertEqual(1, len(base.strict_load(base.strict_load(transport.requests[0])["input"])["items"]))

    def test_novelty_is_separate_raw_history_and_repeat_decision_remains_visible(self):
        current = selection("new-id")
        prior = selection("different-old-id", published="2026-10-06T17:00:00+09:00")
        prior.update(title="SHOULD_NOT_LEAK_PRIOR_TITLE", generatedBody="SHOULD_NOT_LEAK_PRIOR_BODY")
        transport = AuthoredTransport()
        result = recovery.assess_novelty(self.client(transport), [current], [prior], context())
        self.assertEqual("REPEAT", result["decisions"][0]["decision"])
        self.assertEqual("WITHHELD", result["perIssueStatuses"]["new-id"])
        request = base.strict_load(transport.requests[0])
        self.assertEqual(8000, request["max_output_tokens"])
        data = base.strict_load(request["input"])
        self.assertEqual({"issueId", "sources"}, set(data["history"][0]))
        self.assertNotIn("SHOULD_NOT_LEAK", request["input"])
        self.assertNotIn("draft", data)

    def test_empty_history_uses_explicit_server_decision_and_no_model_call(self):
        transport = AuthoredTransport()
        result = recovery.assess_novelty(self.client(transport), [selection()], [], context())
        self.assertEqual("NEW", result["decisions"][0]["decision"])
        self.assertEqual("server_empty_history", result["decisionSource"])
        self.assertIsNone(result["requestDigest"])
        self.assertIsNone(result["rawReply"])
        self.assertEqual([], transport.requests)

    def test_novelty_uncertain_or_foreign_delta_is_withheld_but_raw_decision_kept(self):
        current = selection("current", "합성기업은 별도의 신규 적용 계약을 체결했습니다.")
        prior = selection("old", published="2026-10-06T17:00:00+09:00")
        transport = AuthoredTransport(novelty_decisions={"current": {"decision": "MATERIAL_UPDATE", "deltaEvidenceIds": ["foreign"]}})
        result = recovery.assess_novelty(self.client(transport), [current], [prior], context())
        self.assertEqual("WITHHELD", result["perIssueStatuses"]["current"])
        self.assertEqual(["foreign"], result["decisions"][0]["deltaEvidenceIds"])
        self.assertEqual(result["rawReply"]["decisions"]["current"], result["decisions"][0])

    def test_future_sources_history_or_changed_snapshot_fail_before_any_call(self):
        for mutation in ("source", "history", "snapshot"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                current = selection()
                prior = selection("prior", published="2026-10-06T17:00:00+09:00")
                if mutation == "source":
                    current["sources"][0]["documentVersion"] = "changed"
                elif mutation == "history":
                    prior = selection("prior", published="2026-10-07T08:00:00+09:00")
                else:
                    snapshot = {"issueId": current["issueId"], "newMentions": [], "asOfSnapshotSha256": "a" * 64}
                    current.update(frozenGroupedIssueSnapshot=snapshot, groupedIssueSnapshotSha256="a" * 64)
                transport = AuthoredTransport()
                client = recovery.RecoveryClient(Path(directory) / "private", transport)
                with self.assertRaises(recovery.ReplayError):
                    recovery.assess_novelty(client, [current], [prior], context())
                self.assertEqual([], transport.requests)

    def test_all_completed_phases_cache_replay_with_no_new_calls_or_file_changes(self):
        sel = selection()
        old = selection("old", "합성기업은 이전에 다른 기술 계약을 검토했습니다.", "2026-10-06T17:00:00+09:00")
        transport = AuthoredTransport()
        client = self.client(transport)
        generated = recovery.generate_items(client, [sel], context())
        verified = recovery.verify_items(client, [sel], generated["items"], context())
        novelty = recovery.assess_novelty(client, [sel], [old], context())
        self.assertEqual(3, len(transport.requests))
        before = {p.name: base.digest(p.read_bytes()) for p in client.calls.iterdir()}
        def deny(_):
            raise AssertionError("completed cache must not contact the provider")
        reused = self.client(deny)
        self.assertEqual(generated, recovery.generate_items(reused, [sel], context()))
        self.assertEqual(verified, recovery.verify_items(reused, [sel], generated["items"], context()))
        self.assertEqual(novelty, recovery.assess_novelty(reused, [sel], [old], context()))
        self.assertEqual(0, len(reused.new_calls))
        self.assertEqual(before, {p.name: base.digest(p.read_bytes()) for p in client.calls.iterdir()})

    def test_old_unknown_request_is_never_resent_and_new_version_has_new_digest(self):
        def unknown(_):
            raise OSError("authored old request outcome unknown")
        old = base.ResponsesClient(self.output, unknown, max_calls=400)
        with self.assertRaises(base.ReplayError):
            old.call("round_simulation_morning_generation", {"oldFixedInput": "authored"},
                "generation-morning.md", "generation.schema.json")
        old_pending = next(old.calls.glob("*.pending.json"))
        old_key = old_pending.name.removesuffix(".pending.json")
        before = {p.name: p.read_bytes() for p in old.calls.iterdir()}
        transport = AuthoredTransport()
        result = recovery.generate_items(self.client(transport), [selection()], context())
        self.assertNotEqual(old_key, result["requestDigest"])
        self.assertEqual(1, len(transport.requests))
        for name, raw in before.items():
            self.assertEqual(raw, (old.calls / name).read_bytes())
        self.assertEqual(2, len(list(old.calls.glob("*.pending.json"))))

    def test_new_unknown_and_shared_budget_exhaustion_are_not_automatically_retried(self):
        def unknown(_):
            raise OSError("authored current transport unknown")
        client = self.client(unknown, max_calls=1)
        with self.assertRaisesRegex(recovery.ReplayError, "transport_unknown_usage"):
            recovery.generate_items(client, [selection()], context())
        self.assertTrue(client.stopped.is_set())
        transport = AuthoredTransport()
        resumed = self.client(transport, max_calls=1)
        with self.assertRaisesRegex(recovery.ReplayError, "paid_call_budget_exhausted"):
            recovery.generate_items(resumed, [selection("different")], context())
        self.assertEqual([], transport.requests)
        self.assertEqual(1, len(list(resumed.calls.glob("*.pending.json"))))

    def test_money_scale_negative_guard_rejects_40_trillion_won_as_4_trillion(self):
        sel = selection(quote="SK hynix announced an investment of 40 trillion won.")
        for title, claim in [("SK하이닉스 4조원 투자", "투자 금액은 40조원입니다."),
                ("SK하이닉스 투자 발표", "투자 금액은 4조원입니다.")]:
            with self.subTest(title=title, claim=claim):
                with self.assertRaisesRegex(recovery.ReplayError, "currency_quantity_not_supported"):
                    recovery.validate_item(item(sel, claim, title), sel)
        recovery.validate_item(item(sel, "투자 금액은 40조원입니다.", "SK하이닉스 40조원 투자"), sel)

    def test_money_units_compounds_and_currencies_have_exact_equivalent_values(self):
        pairs = [("40 trillion won", "40조원", "KRW", "40000000000000"),
            ("4.2462 trillion won", "42,462억원", "KRW", "4246200000000"),
            ("42,462억원", "4조 2462억 원", "KRW", "4246200000000"),
            ("29 billion dollars", "290억달러", "DOLLAR", "29000000000"),
            ("US$29 billion", "290억 미국달러", "USD", "29000000000"),
            ("3 million euros", "300만유로", "EUR", "3000000"),
            ("NT$29 billion", "290억 대만달러", "TWD", "29000000000"),
            ("29 billion New Taiwan dollars", "290억 타이완달러", "TWD", "29000000000")]
        for original, translated, currency, value in pairs:
            with self.subTest(original=original, translated=translated):
                left, right = recovery.currency_quantities(original), recovery.currency_quantities(translated)
                self.assertEqual([(currency, Decimal(value))], [(v["currency"], v["value"]) for v in left])
                self.assertEqual([(currency, Decimal(value))], [(v["currency"], v["value"]) for v in right])
                recovery._preserve_currency_quantities(translated, [original])

    def test_money_currency_scope_is_not_silently_converted(self):
        for original, translated in [("29 billion U.S. dollars", "290억 대만달러"),
                ("29 billion New Taiwan dollars", "290억 미국달러"),
                ("3 million euros", "300만 미국달러"), ("40 trillion won", "40조달러")]:
            with self.subTest(original=original, translated=translated):
                with self.assertRaisesRegex(recovery.ReplayError, "currency_quantity_not_supported"):
                    recovery._preserve_currency_quantities(translated, [original])

    def test_money_parser_does_not_confuse_percent_year_range_or_unsupported_units(self):
        for text in ["USD 40%", "USD 40 billion%", "2026년 매출이 40% 증가", "30~40조원",
                "between 30 and 40 trillion won", "KRW4천억원", "3,5억원", "달러당 1300원", "1달러당 1300원"]:
            with self.subTest(text=text):
                self.assertEqual([], recovery.currency_quantities(text))
        value = recovery.currency_quantities("2024~2028년 투자 기간에 매출이 40% 증가했고 투자액은 4조원입니다.")
        self.assertEqual([Decimal("4000000000000")], [v["value"] for v in value])
        recovery._preserve_currency_quantities("2024~2028년 투자액은 4조원입니다.",
            ["The investment over 2024-2028 is 4 trillion won; sales increased 40%."])
        # Do not require every quoted amount to appear, or compare unrelated
        # percent/date numbers as money. Unknown source forms remain AI-checked.
        recovery._preserve_currency_quantities("투자액은 4조원입니다.", ["4 trillion won was invested; another project cost 3 billion dollars."])
        recovery._preserve_currency_quantities("매출이 40% 증가했습니다.", ["The investment is 4 trillion won."])
        recovery._preserve_currency_quantities("투자액은 4조원입니다.", ["투자액은 4천억원입니다."])

    def test_cached_original_money_mistake_is_withheld_without_new_request_or_prompt_change(self):
        sel = selection(quote="SK hynix announced an investment of 40 trillion won.")
        transport = AuthoredTransport(generation_mutations={sel["issueId"]: {"title": "SK하이닉스 4조원 투자"}})
        client = self.client(transport)
        safe = recovery.prepare_selections([sel], context())
        rows = [(safe[0]["issueId"], {
            ("properties", "titleEvidenceIds", "items"): ["ev-issue-one"],
            ("properties", "claims", "items", "properties", "evidenceIds", "items"): ["ev-issue-one"]})]
        data = {**recovery._envelope(context()), "selections": safe, "priorFailures": {}}
        original_digest, raw_reply = recovery._call(client, "generation", data,
            recovery._keyed_schema("generation", "items", rows, "issueId"))
        before = {p.name: p.read_bytes() for p in client.calls.iterdir()}
        prompts = recovery.prompt_artifacts()
        def deny(_):
            raise AssertionError("host-only rejection must reuse the recorded original request")
        result = recovery.generate_items(self.client(deny), [sel], context())
        self.assertEqual(original_digest, result["requestDigest"])
        self.assertEqual(raw_reply, result["rawReply"])
        self.assertEqual([], result["items"])
        self.assertEqual("WITHHELD", result["perIssueStatuses"][sel["issueId"]])
        self.assertEqual("recovery_currency_quantity_not_supported", result["failures"][sel["issueId"]])
        self.assertEqual(before, {p.name: p.read_bytes() for p in client.calls.iterdir()})
        self.assertEqual(prompts, recovery.prompt_artifacts())

    def test_bn_abbreviation_keeps_tsmc_original_title_equivalent(self):
        quote = "TSMC reported September consolidated revenue of approximately NT$511.86 billion, up 54.6% year over year."
        sel = selection(quote=quote)
        title = "TSMC 9월 연결 매출 약 NT$511.86bn…전년 대비54.6%증가"
        claim = "TSMC의 9월 연결 매출은 약 NT$511.86bn입니다."
        recovery.validate_item(item(sel, claim, title), sel)
        self.assertEqual([("TWD", Decimal("511860000000"))],
            [(v["currency"], v["value"]) for v in recovery.currency_quantities(title)])
        recovery._preserve_currency_quantities("290억 달러", ["29bn dollars"])

    def test_unknown_ascii_unit_and_partial_decimal_backtracking_are_not_money(self):
        for text in ("NT$511.86xyz", "NT$511.86bnXYZ", "USD3,5bn", "US$511.86B", "KRW4foo"):
            with self.subTest(text=text):
                self.assertEqual([], recovery.currency_quantities(text))
        self.assertEqual(Decimal("511860000000"), recovery.currency_quantities("NT$511.86bn.")[0]["value"])
        self.assertEqual(Decimal("511.86"), recovery.currency_quantities("NT$511.86.")[0]["value"])

    def test_bn_guard_reuses_fixed_cached_provider_text_without_request_changes(self):
        quote = "TSMC reported revenue of approximately NT$511.86 billion."
        sel = selection(quote=quote)
        title = "TSMC 연결 매출 약 NT$511.86bn"
        transport = AuthoredTransport(generation_mutations={sel["issueId"]: {"title": title}})
        client = self.client(transport)
        first = recovery.generate_items(client, [sel], context())
        self.assertEqual("PASS", first["perIssueStatuses"][sel["issueId"]])
        before = {p.name: p.read_bytes() for p in client.calls.iterdir()}
        prompts = recovery.prompt_artifacts()
        def deny(_):
            raise AssertionError("bn hostguard must not contact the provider")
        replay = recovery.generate_items(self.client(deny), [sel], context())
        self.assertEqual(first, replay)
        self.assertEqual(before, {p.name: p.read_bytes() for p in client.calls.iterdir()})
        self.assertEqual(prompts, recovery.prompt_artifacts())


if __name__ == "__main__":
    unittest.main()
