"""Authored issue archive and model responses; no real source/API calls."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("grouped_rounds", Path(__file__).resolve().parents[1] / "briefing_grouped_rounds.py")
grouped = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grouped)
base = grouped.base


def document(key, published, quote=None):
    quote = quote or "합성 기업이 건물 관리 기술의 적용 계약을 체결했습니다. 실제 뉴스가 아닌 시험 문장입니다."
    body = "작성한 합성 원문입니다. " + quote + " 추가 설명은 새로운 투자 전망을 주장하지 않습니다."
    sha = base.digest(body.encode())
    clock = {"status": "verified_timestamp", "documentId": key, "bodySha256": sha,
             "publishedAt": published, "checkedAt": "2026-10-20T01:00:00Z"}
    return {"documentId": key, "documentVersion": "sha256-" + sha, "bodySha256": sha, "body": body,
            "title": "합성 기술 계약", "url": "https://example.invalid/" + key,
            "dateContext": {"publishedAt": published, "historicalBodyUnchangedProven": False},
            "clockRecord": clock, "clockRecordSha256": base.digest(base.canonical(clock)),
            "companyNames": ["합성 기업"], "collectedAt": "2026-10-20T01:00:00Z"}


def mention(doc, key, quote=None):
    quote = quote or doc["body"][doc["body"].index("합성 기업"):doc["body"].index(" 추가 설명")]
    start = doc["body"].index(quote)
    evidence = {"evidenceId": "ev-" + key, "articleId": doc["documentId"],
                "articleVersion": doc["documentVersion"], "quote": quote, "start": start, "end": start + len(quote)}
    return {"mentionId": key, "articleId": doc["documentId"], "articleVersion": doc["documentVersion"],
            "publishedAt": doc["dateContext"]["publishedAt"], "bodySha256": doc["bodySha256"],
            "title": doc["title"], "action": "체결", "target": "건물 관리 기술 적용 계약", "eventTime": None,
            "keywords": ["건물 관리 기술"], "companies": [{"companyId": "company-authored", "name": "합성 기업",
                "role": "계약 당사자", "evidence": [evidence]}], "evidence": [evidence]}


def archive(*groups):
    documents = [doc for _, pairs in groups for doc, _ in pairs]
    return {"schemaVersion": "zoop-grouped-issues-v1", "sourceFileSha256": "a" * 64,
            "documents": documents, "receipts": [], "issues": [
                {"issueId": key, "title": "미래 기사를 보고 바뀐 제목", "mentions": [m for _, m in pairs]}
                for key, pairs in groups]}


def round_spec(edition="morning"):
    return {"date": "2026-10-07", "edition": edition, "window": {"from": "2026-10-06T17:30:00+09:00",
            "to": "2026-10-07T09:20:00+09:00", "openStart": False}}


def selection(candidates, indexes=None):
    indexes = list(range(min(3, len(candidates)))) if indexes is None else indexes
    return {"assessments": {c["issueId"]: {"importance": 2, "priority": min(100, 70 + i),
        "status": "SELECTABLE", "reason": "실제 적용 계약을 합성 원문으로 확인", "scope": "COMPANY",
        "affectedSectors": [], "transmission": ""} for i, c in enumerate(candidates)},
        "selected": [{"issueId": candidates[i]["issueId"], "title": "합성 건물 관리 기술 적용 계약",
            "evidenceIds": list(candidates[i]["newEvidenceIds"]), "companyIds": ["company-authored"],
            "novelty": "NEW_EVENT", "deltaEvidenceIds": [], "limitations": ["늦게 수집한 합성 과거 시뮬레이션"]}
            for i in indexes]}


class AuthoredTransport:
    def __init__(self, semantic_repeat=False):
        self.requests = []
        self.semantic_repeat = semantic_repeat

    def __call__(self, raw):
        self.requests.append(raw)
        request = base.strict_load(raw)
        data = base.strict_load(request["input"])
        stage = request["text"]["format"]["name"]
        if stage == grouped.SELECTION_STAGE:
            value = selection(data["issues"])
        elif stage.endswith("_generation"):
            value = {"items": {row["issueId"]: {"issueId": row["issueId"], "rank": row["rank"],
                "title": "합성 기업의 건물 관리 기술 계약", "titleEvidenceIds": [row["sources"][0]["evidenceId"]],
                "claims": [{"text": "합성 기업이 건물 관리 기술 적용 계약을 체결했습니다.", "type": "fact",
                            "evidenceIds": [row["sources"][0]["evidenceId"]]},
                           {"text": "계약의 대상은 건물 관리 기술입니다.", "type": "fact",
                            "evidenceIds": [row["sources"][0]["evidenceId"]]}]} for row in data["selected"]}}
        else:
            targets = [target for row in data["draft"]["items"] for target in [row["issueId"] + ":title",
                       *(row["issueId"] + ":claim:" + str(i) for i in range(len(row["claims"])))] ]
            value = {"checks": {target: {"targetId": target, "verdict": "SUPPORTED", "typeAppropriate": True,
                "temporalAppropriate": True, "noUnsupportedNumbers": True, "noInvestmentAdvice": True,
                "reason": "합성 근거와 일치"} for target in targets}}
            if self.semantic_repeat:
                assert data["priorSelectedIssues"]
                assert "의미상 재보도이면" in request["instructions"]
                assert "실질 변화" in request["instructions"]
                for target in targets[:2]:
                    value["checks"][target].update(verdict="UNSUPPORTED", temporalAppropriate=False,
                        reason="같은 계약 체결 사실을 다른 문구로 재보도했으며 실질 변화는 없습니다.")
        return 200, base.canonical({"id": "authored-" + base.digest(raw)[:16], "status": "completed",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": base.canonical(value).decode()}]}]})


class CorrectionTransport(AuthoredTransport):
    def __init__(self, always_invalid=False, unknown=False):
        super().__init__()
        self.always_invalid, self.unknown = always_invalid, unknown

    def __call__(self, raw):
        status, response_raw = super().__call__(raw)
        if self.unknown:
            raise OSError("authored unknown provider result")
        request = base.strict_load(raw)
        data = base.strict_load(request["input"])
        if request["text"]["format"]["name"] == grouped.SELECTION_STAGE \
                and (self.always_invalid or "selectionCorrection" not in data):
            response = base.strict_load(response_raw)
            value = base.strict_load(response["output"][0]["content"][0]["text"])
            value["selected"][0]["companyIds"] = ["authored-invented-company"]
            response["output"][0]["content"][0]["text"] = base.canonical(value).decode()
            response_raw = base.canonical(response)
        return status, response_raw


class GroupedRoundTests(unittest.TestCase):
    def test_unverified_company_group_is_held_only_after_its_member_becomes_available(self):
        first = document("identity-first", "2026-10-07T08:00:00+09:00")
        later = document("identity-later", "2026-10-07T12:00:00+09:00")
        old, bad = mention(first, "identity-old"), mention(later, "identity-bad")
        for value, eligible in [(old, True), (bad, False)]:
            value["companyProjection"] = {"policy": "canonical-evidence-v1", "briefingEligible": eligible,
                                          "audit": []}
        value = archive(("issue-identity", [(first, old), (later, bad)]))
        value["identity"] = {"companyProjectionVersion": "canonical-evidence-v1"}
        holds = []
        self.assertEqual(1, len(grouped.build_grouped_candidates(value, round_spec(), holds)))
        self.assertEqual([], holds)
        evening = {"date": "2026-10-07", "edition": "evening", "window": {
            "from": "2026-10-07T09:20:00+09:00", "to": "2026-10-07T17:30:00+09:00", "openStart": False}}
        self.assertEqual([], grouped.build_grouped_candidates(value, evening, holds))
        self.assertEqual([{"issueId": "issue-identity", "mentionIds": ["identity-bad"],
            "reason": "unverified_company_link_in_asof_group"}], holds)

    def test_projection_policy_cannot_be_removed_or_its_required_marker_omitted(self):
        doc = document("identity-policy", "2026-10-07T08:00:00+09:00")
        m = mention(doc, "identity-policy")
        value = archive(("issue-identity", [(doc, m)]))
        value["identity"] = {"companyProjectionVersion": "canonical-evidence-v1"}
        with self.assertRaisesRegex(grouped.ReplayError, "grouped_company_projection_missing_or_invalid"):
            grouped.build_grouped_candidates(value, round_spec())
        m["companyProjection"] = {"policy": "canonical-evidence-v1", "briefingEligible": True, "audit": []}
        self.assertEqual(1, len(grouped.build_grouped_candidates(value, round_spec())))
        del value["identity"]
        with self.assertRaisesRegex(grouped.ReplayError, "grouped_company_projection_policy_missing"):
            grouped.build_grouped_candidates(value, round_spec())

    def setUp(self):
        self.doc = document("doc-current", "2026-10-07T08:00:00+09:00")
        self.mention = mention(self.doc, "mention-current")
        self.archive = archive(("issue-stable", [(self.doc, self.mention)]))

    def candidates(self):
        return grouped.build_grouped_candidates(self.archive, round_spec())

    def test_only_asof_content_and_new_mentions_create_candidates(self):
        old = document("doc-old", "2026-10-06T17:30:00+09:00")
        future = document("doc-future", "2026-10-07T09:20:01+09:00", "미래 기업이 뒤늦게 추가한 사건은 과거 입력에서 제외합니다.")
        self.archive = archive(("issue-stable", [(old, mention(old, "old")), (self.doc, self.mention),
            (future, mention(future, "future", "미래 기업이 뒤늦게 추가한 사건은 과거 입력에서 제외합니다."))]))
        out = self.candidates()
        self.assertEqual(1, len(out))
        self.assertEqual(["mention-current"], [m["mentionId"] for m in out[0]["newMentions"]])
        self.assertEqual(["old"], [m["mentionId"] for m in out[0]["backgroundMentions"]])
        self.assertEqual(old["title"], out[0]["title"])
        self.assertNotIn("미래", base.canonical(out).decode())
        only_old = archive(("old-only", [(old, mention(old, "only-old"))]))
        self.assertEqual([], grouped.build_grouped_candidates(only_old, round_spec()))

    def test_cutoff_is_inclusive_start_is_exclusive(self):
        self.doc["clockRecord"]["publishedAt"] = round_spec()["window"]["to"]
        self.doc["dateContext"]["publishedAt"] = round_spec()["window"]["to"]
        self.doc["clockRecordSha256"] = base.digest(base.canonical(self.doc["clockRecord"]))
        self.mention["publishedAt"] = round_spec()["window"]["to"]
        self.assertEqual(1, len(self.candidates()))
        self.mention["publishedAt"] = round_spec()["window"]["from"]
        self.doc["clockRecord"]["publishedAt"] = self.mention["publishedAt"]
        self.doc["dateContext"]["publishedAt"] = self.mention["publishedAt"]
        self.doc["clockRecordSha256"] = base.digest(base.canonical(self.doc["clockRecord"]))
        self.assertEqual([], self.candidates())

    def test_source_version_clock_and_exact_span_are_checked(self):
        for field, replacement, error in (("articleVersion", "wrong", "version_mismatch"),
                ("bodySha256", "0" * 64, "version_mismatch")):
            with self.subTest(field=field):
                old = self.mention[field]
                self.mention[field] = replacement
                with self.assertRaisesRegex(grouped.ReplayError, error):
                    self.candidates()
                self.mention[field] = old
        self.mention["evidence"][0]["start"] += 1
        with self.assertRaisesRegex(grouped.ReplayError, "exact_original_span"):
            self.candidates()

    def test_unknown_or_future_evidence_and_company_are_rejected(self):
        candidates = self.candidates()
        reply = selection(candidates)
        reply["selected"][0]["evidenceIds"] = ["not-a-citation"]
        with self.assertRaisesRegex(grouped.ReplayError, "unknown_or_duplicate_citation"):
            grouped.freeze_grouped_selection(reply, candidates, "identity")
        reply = selection(candidates)
        reply["selected"][0]["companyIds"] = ["invented-company"]
        with self.assertRaisesRegex(grouped.ReplayError, "unknown_or_duplicate_company"):
            grouped.freeze_grouped_selection(reply, candidates, "identity")

    def test_background_is_not_generation_evidence(self):
        old = document("doc-old", "2026-10-06T17:30:00+09:00")
        self.archive = archive(("issue-stable", [(old, mention(old, "old")), (self.doc, self.mention)]))
        candidates = self.candidates()
        reply = selection(candidates)
        reply["selected"][0]["evidenceIds"].append("ev-old")
        with self.assertRaisesRegex(grouped.ReplayError, "outside_current_round"):
            grouped.freeze_grouped_selection(reply, candidates, "identity")

    def test_stable_issue_and_exact_company_links_remain_in_generation_shape(self):
        candidates = self.candidates()
        selected = grouped.freeze_grouped_selection(selection(candidates), candidates, "identity")
        self.assertEqual("issue-stable", selected[0]["issueId"])
        self.assertEqual(["합성 기업"], selected[0]["companyNames"])
        self.assertEqual(["ev-mention-current"], selected[0]["companyLinks"][0]["evidenceIds"])
        self.assertEqual(candidates[0], selected[0]["frozenGroupedIssueSnapshot"])
        self.assertEqual(self.doc["documentVersion"], selected[0]["sources"][0]["documentVersion"])
        self.assertFalse(selected[0]["frozenGroupedIssueSnapshot"]["operationalCollectionGate"])

    def test_same_issue_needs_new_fact_and_not_just_new_document_id(self):
        candidates = self.candidates()
        previous = grouped.freeze_grouped_selection(selection(candidates), candidates, "identity")
        later = {"date": "2026-10-07", "edition": "evening", "window": {"from": round_spec()["window"]["to"],
            "to": "2026-10-07T17:30:00+09:00", "openStart": False}}
        copy = document("doc-copy", "2026-10-07T12:00:00+09:00")
        repeated = grouped.build_grouped_candidates(archive(("issue-stable", [(copy, mention(copy, "copy"))])), later)
        reply = selection(repeated)
        with self.assertRaisesRegex(grouped.ReplayError, "repeat_issue_without_supported"):
            grouped.freeze_grouped_selection(reply, repeated, "next", previous)
        reply["selected"][0].update({"novelty": "MATERIAL_UPDATE", "deltaEvidenceIds": ["ev-copy"]})
        with self.assertRaisesRegex(grouped.ReplayError, "repeat_issue_without_supported"):
            grouped.freeze_grouped_selection(reply, repeated, "next", previous)
        changed = document("doc-update", "2026-10-07T12:00:00+09:00",
            "합성 기업은 계약을 변경하여 실제 적용 건물을 세 곳에서 다섯 곳으로 늘렸습니다.")
        updated = grouped.build_grouped_candidates(archive(("issue-stable", [(changed, mention(changed, "update"))])), later)
        reply = selection(updated)
        reply["selected"][0].update({"novelty": "MATERIAL_UPDATE", "deltaEvidenceIds": ["ev-update"]})
        self.assertEqual("issue-stable", grouped.freeze_grouped_selection(reply, updated, "next", previous)[0]["issueId"])

    def test_mutated_snapshot_and_future_history_are_rejected(self):
        candidates = self.candidates()
        previous = grouped.freeze_grouped_selection(selection(candidates), candidates, "identity")
        with self.assertRaisesRegex(grouped.ReplayError, "future_or_undated_previous_source"):
            grouped.freeze_grouped_selection(selection(candidates), candidates, "identity", previous)
        candidates[0]["title"] = "바뀐 제목"
        with self.assertRaisesRegex(grouped.ReplayError, "changed_after_input_freeze"):
            grouped.freeze_grouped_selection(selection(candidates), candidates, "identity")

    def test_all_issues_assessed_and_no_more_than_three_selected(self):
        pairs = []
        for i in range(4):
            doc = document("doc-" + str(i), "2026-10-07T08:00:00+09:00")
            pairs.append(("issue-" + str(i), [(doc, mention(doc, "mention-" + str(i)))]))
        candidates = grouped.build_grouped_candidates(archive(*pairs), round_spec())
        reply = selection(candidates)
        selected = grouped.freeze_grouped_selection(reply, candidates, "identity")
        self.assertEqual(["issue-2", "issue-1", "issue-0"], [s["issueId"] for s in selected])
        reply = selection(candidates, [0, 1, 2, 3])
        with self.assertRaises(grouped.ReplayError):
            grouped.freeze_grouped_selection(reply, candidates, "identity")
        reply = selection(candidates)
        del reply["assessments"]["issue-3"]
        with self.assertRaises(grouped.ReplayError):
            grouped.freeze_grouped_selection(reply, candidates, "identity")

    def test_three_requires_real_scope_structure(self):
        candidates = self.candidates()
        reply = selection(candidates)
        reply["assessments"]["issue-stable"]["importance"] = 3
        with self.assertRaisesRegex(grouped.ReplayError, "impact_proof_missing"):
            grouped.freeze_grouped_selection(reply, candidates, "identity")

    def test_model_selection_original_generation_and_cached_replay(self):
        candidates = self.candidates()
        transport = AuthoredTransport()
        with tempfile.TemporaryDirectory() as directory:
            client = grouped.GroupedSimulationClient(Path(directory) / "private", transport)
            context = {"context": {"mode": grouped.sim.MODE, "roundId": "authored-round"},
                       "contextSha256": "identity", "qualityPolicy": grouped.sim.QUALITY_V2}
            selected = grouped.choose_grouped_round(client, candidates, context, "identity")
            result = grouped.sim.generate_round(client, selected, "morning", context, 0)
            self.assertEqual("PASS", result["verification"]["status"])
            self.assertEqual(3, len(transport.requests))
            self.assertIn("저장된 사건", base.strict_load(transport.requests[0])["instructions"])
            self.assertIn("출근 회차", base.strict_load(transport.requests[1])["instructions"])
            self.assertTrue(all(base.strict_load(raw)["store"] is False for raw in transport.requests))
            self.assertEqual(selected, grouped.choose_grouped_round(client, candidates, context, "identity"))
            self.assertEqual(3, len(transport.requests))
            self.assertEqual(3, len(client.receipts()))

    def test_empty_pool_never_calls_model(self):
        class NeverCall:
            def call(self, *args, **kwargs):
                raise AssertionError("empty population must not consume tokens")
        self.assertEqual([], grouped.choose_grouped_round(NeverCall(), [], {}, "identity"))

    def test_prompt_and_schema_digests_prevent_unfrozen_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            client = grouped.GroupedSimulationClient(Path(directory) / "private", AuthoredTransport())
            data = {"context": {"promptArtifacts": {"grouped-selection.md": "bad"}}}
            with self.assertRaisesRegex(grouped.ReplayError, "prompt_changed"):
                client.request(grouped.SELECTION_STAGE, data, "selection.md", "selection.schema.json")
            data = {"context": {"promptArtifacts": {"grouped-selection.schema.json": "bad"}}}
            with self.assertRaisesRegex(grouped.ReplayError, "schema_changed"):
                client.request(grouped.SELECTION_STAGE, data, "selection.md", "selection.schema.json")

    def test_grouped_generation_preserves_strict_original_and_checks_each_prompt_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            client = grouped.GroupedSimulationClient(Path(directory) / "private", AuthoredTransport())
            for edition in ("morning", "evening"):
                stage = "round_simulation_" + edition + "_generation"
                data = {"context": {}, "edition": edition}
                raw, schema, _ = client.request(stage, data, "generation-" + edition + ".md", "generation.schema.json")
                request = base.strict_load(raw)
                original = base.regular(grouped.sim.PROMPTS / ("generation-v2-" + edition + ".md")).decode()
                self.assertTrue(request["instructions"].startswith(original))
                self.assertIn("companyLinks", request["instructions"])
                self.assertIn("deltaEvidenceIds", request["instructions"])
                self.assertIn("수혜·주가 영향을 추측하지 않는다", request["instructions"])
                self.assertEqual(stage, request["text"]["format"]["name"])
                self.assertEqual(grouped.sim.schema("generation"), schema)
                data["context"]["promptArtifacts"] = {"grouped-generation-" + edition + ".md": "bad"}
                with self.assertRaisesRegex(grouped.ReplayError, "prompt_changed"):
                    client.request(stage, data, "generation-" + edition + ".md", "generation.schema.json")
            data = {"context": {}, "edition": "morning"}
            raw, schema, _ = client.request("round_simulation_morning_verification", data,
                "verification.md", "verification.schema.json")
            self.assertTrue(base.strict_load(raw)["instructions"].startswith(base.regular(grouped.sim.PROMPTS / "verification.md").decode()))
            self.assertEqual(grouped.sim.schema("verification"), schema)
            data["context"]["promptArtifacts"] = {"grouped-verification.md": "bad"}
            with self.assertRaisesRegex(grouped.ReplayError, "prompt_changed"):
                client.request("round_simulation_morning_verification", data, "verification.md", "verification.schema.json")

    def test_rephrased_same_event_can_pass_string_guard_but_semantic_verifier_withholds(self):
        original = self.candidates()
        prior = grouped.freeze_grouped_selection(selection(original), original, "original")
        later = {"date": "2026-10-07", "edition": "evening", "window": {"from": round_spec()["window"]["to"],
            "to": "2026-10-07T17:30:00+09:00", "openStart": False}}
        doc = document("doc-rephrased", "2026-10-07T12:00:00+09:00",
            "합성 기업은 건물 관리 기술의 적용 계약 체결 사실을 보도자료에서 다시 알렸습니다.")
        candidates = grouped.build_grouped_candidates(archive(("issue-stable", [(doc, mention(doc, "rephrased"))])), later)
        reply = selection(candidates)
        reply["selected"][0].update(novelty="MATERIAL_UPDATE", deltaEvidenceIds=["ev-rephrased"])
        selected = grouped.freeze_grouped_selection(reply, candidates, "later", prior)
        with tempfile.TemporaryDirectory() as directory:
            transport = AuthoredTransport(semantic_repeat=True)
            client = grouped.GroupedSimulationClient(Path(directory) / "private", transport)
            context = {"context": {"mode": grouped.sim.MODE, "roundId": "later", "window": later["window"]},
                       "contextSha256": "later", "qualityPolicy": grouped.sim.QUALITY_V2,
                       "priorSelectedIssues": prior}
            result = grouped.sim.generate_round(client, selected, "evening", context, 0)
            self.assertEqual("WITHHELD", result["verification"]["status"])
            self.assertEqual(2, len(transport.requests))
            self.assertEqual(["round_simulation_evening_generation", "round_simulation_evening_verification"],
                [base.strict_load(raw)["text"]["format"]["name"] for raw in transport.requests])
            self.assertEqual(prior, base.strict_load(base.strict_load(transport.requests[-1])["input"])["priorSelectedIssues"])
            self.assertEqual(2, len(client.receipts()))

    def test_different_issue_id_new_event_still_reaches_full_history_semantic_guard(self):
        original = self.candidates()
        prior = grouped.freeze_grouped_selection(selection(original), original, "original")
        later = {"date": "2026-10-07", "edition": "evening", "window": {"from": round_spec()["window"]["to"],
            "to": "2026-10-07T17:30:00+09:00", "openStart": False}}
        doc = document("doc-split", "2026-10-07T12:00:00+09:00",
            "합성 기업의 건물 관리 기술 적용 계약 체결 사실이 다른 보도에서 다시 소개됐습니다.")
        candidates = grouped.build_grouped_candidates(archive(("issue-split-id", [(doc, mention(doc, "split"))])), later)
        selected = grouped.freeze_grouped_selection(selection(candidates), candidates, "later", prior)
        self.assertEqual("NEW_EVENT", selected[0]["novelty"][0]["decision"])
        self.assertNotEqual(prior[0]["issueId"], selected[0]["issueId"])
        with tempfile.TemporaryDirectory() as directory:
            transport = AuthoredTransport(semantic_repeat=True)
            client = grouped.GroupedSimulationClient(Path(directory) / "private", transport)
            context = {"context": {"mode": grouped.sim.MODE, "roundId": "split", "window": later["window"]},
                "contextSha256": "later", "priorSelectedIssues": prior}
            result = grouped.sim.generate_round(client, selected, "evening", context, 0)
            self.assertEqual("WITHHELD", result["verification"]["status"])
            self.assertEqual(2, len(transport.requests))
            verifier = base.strict_load(transport.requests[-1])
            self.assertIn("NEW_EVENT로 잘못 선정됐을 수도 있다", verifier["instructions"])
            self.assertIn("다른 issueId", verifier["instructions"])
            self.assertEqual("issue-split-id", selected[0]["issueId"])
            self.assertEqual("issue-stable", prior[0]["issueId"])

    def test_all_grouped_prompts_compare_other_ids_without_rewriting_archive_ids(self):
        for name in ("selection.md", "generation-morning.md", "generation-evening.md", "verification.md"):
            with self.subTest(prompt=name):
                text = base.regular(grouped.PROMPTS / name).decode()
                self.assertIn("전체", text)
                self.assertIn("다른 issueId", text)
                self.assertIn("NEW_EVENT", text)
                self.assertIn("MATERIAL_UPDATE", text)
                self.assertIn("deltaEvidenceIds", text)
                self.assertIn("중복 브리핑", text)

    def test_known_completed_company_mistake_corrected_once_with_exact_final_digest(self):
        candidates = self.candidates()
        context = {"context": {"mode": grouped.sim.MODE}, "contextSha256": "identity"}
        with tempfile.TemporaryDirectory() as directory:
            transport = CorrectionTransport()
            client = grouped.GroupedSimulationClient(Path(directory) / "private", transport)
            outcome = grouped.attempt_grouped_selection(client, candidates, context, "identity")
            self.assertIsNone(outcome["failure"])
            self.assertEqual("issue-stable", outcome["selected"][0]["issueId"])
            self.assertEqual(2, len(transport.requests))
            self.assertEqual(base.digest(transport.requests[-1]), outcome["requestDigest"])
            audit = outcome["corrections"][0]
            self.assertEqual("PASS", audit["status"])
            self.assertEqual(base.digest(transport.requests[0]), audit["originalRequestDigest"])
            first = base.strict_load(base.strict_load(transport.requests[0])["input"])
            second = base.strict_load(base.strict_load(transport.requests[1])["input"])
            correction = second.pop("selectionCorrection")
            self.assertEqual(first, second)
            self.assertEqual("grouped_unknown_or_duplicate_company", correction["failure"])
            self.assertEqual(["authored-invented-company"], correction["previousReply"]["selected"][0]["companyIds"])
            self.assertEqual(audit["originalResponseSha256"], correction["originalResponseSha256"])
            self.assertEqual(2, len(client.receipts()))
            self.assertTrue(all(r["usageKnown"] is True for r in client.receipts()))
            # Both immutable paid responses replay: the correction is not paid again.
            self.assertEqual(outcome, grouped.attempt_grouped_selection(client, candidates, context, "identity"))
            self.assertEqual(2, len(transport.requests))

    def test_repeated_selection_mistake_stops_after_two_completed_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = CorrectionTransport(always_invalid=True)
            client = grouped.GroupedSimulationClient(Path(directory) / "private", transport)
            outcome = grouped.attempt_grouped_selection(client, self.candidates(), {}, "identity")
            self.assertEqual([], outcome["selected"])
            self.assertEqual("grouped_unknown_or_duplicate_company", outcome["failure"])
            self.assertEqual("WITHHELD", outcome["corrections"][0]["status"])
            self.assertEqual(2, len(transport.requests))
            self.assertEqual(base.digest(transport.requests[-1]), outcome["requestDigest"])
            self.assertEqual(2, len(client.receipts()))
            self.assertFalse(client.stopped.is_set())

    def test_changed_source_snapshot_never_spends_or_corrects(self):
        candidates = self.candidates()
        candidates[0]["newMentions"][0]["evidence"][0]["quote"] = "변조된 원문"
        with tempfile.TemporaryDirectory() as directory:
            transport = CorrectionTransport()
            client = grouped.GroupedSimulationClient(Path(directory) / "private", transport)
            with self.assertRaisesRegex(grouped.ReplayError, "changed_after_input_freeze"):
                grouped.attempt_grouped_selection(client, candidates, {}, "identity")
            self.assertEqual(0, len(transport.requests))
            self.assertEqual([], client.receipts())

    def test_provider_unknown_and_exhausted_budget_are_not_bypassed_by_correction(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = CorrectionTransport(unknown=True)
            client = grouped.GroupedSimulationClient(Path(directory) / "unknown", transport)
            with self.assertRaises(grouped.ReplayError):
                grouped.attempt_grouped_selection(client, self.candidates(), {}, "identity")
            self.assertEqual(1, len(transport.requests))
            self.assertTrue(client.stopped.is_set())
            transport = CorrectionTransport()
            client = grouped.GroupedSimulationClient(Path(directory) / "budget", transport, max_calls=1)
            with self.assertRaisesRegex(grouped.ReplayError, "paid_call_budget_exhausted"):
                grouped.attempt_grouped_selection(client, self.candidates(), {}, "identity")
            self.assertEqual(1, len(transport.requests))
            self.assertEqual(1, len(client.receipts()))
            self.assertTrue(client.stopped.is_set())

    def test_output_cap_uses_full_population_length_floor_and_stable_id_size(self):
        rows = [{"issueId": "issue-" + format(i, "024x")} for i in range(174)]
        plans = [grouped.selection_output_plan(rows[:n]) for n in (0, 1, 8, 45, 95, 174)]
        caps = [p["maxOutputTokens"] for p in plans]
        self.assertEqual([12000, 12000, 12000], caps[:3])
        self.assertEqual(sorted(caps), caps)
        self.assertEqual(33792, caps[-1])
        self.assertEqual(25957, plans[-1]["minimumJsonCharacters"])
        self.assertEqual(46757, plans[-1]["realisticJsonCharacters"])
        self.assertTrue(plans[-1]["providerOutputLimitVerified"])
        self.assertEqual(plans[-1], grouped.selection_output_plan(list(reversed(rows))))
        longer = [{"issueId": "issue-" + "x" * 100 + str(i)} for i in range(174)]
        self.assertGreater(grouped.selection_output_cap(longer), caps[-1])

    def test_oversized_exhaustive_output_plan_stops_before_provider_call(self):
        rows = [{"issueId": "issue-" + format(i, "024x")} for i in range(2000)]
        with self.assertRaisesRegex(grouped.ReplayError, "grouped_selection_output_plan_exceeds_provider_limit"):
            grouped.selection_output_cap(rows)

    def test_large_population_initial_digest_and_single_correction_share_dynamic_cap(self):
        groups = []
        for i in range(95):
            doc = document("doc-cap-" + str(i), "2026-10-07T08:00:00+09:00")
            groups.append(("issue-" + format(i, "024x"), [(doc, mention(doc, "cap-" + str(i)))]))
        candidates = grouped.build_grouped_candidates(archive(*groups), round_spec())
        with tempfile.TemporaryDirectory() as directory:
            transport = CorrectionTransport()
            client = grouped.GroupedSimulationClient(Path(directory) / "private", transport)
            expected_cap = grouped.selection_output_cap(candidates)
            self.assertGreater(expected_cap, 12000)
            first_digest = client.request_digest(grouped.SELECTION_STAGE,
                grouped.grouped_selection_data(candidates, {}), "selection.md", "selection.schema.json",
                max_output=expected_cap, schema_override=grouped.selection_schema(candidates))
            outcome = grouped.attempt_grouped_selection(client, candidates, {}, "identity")
            self.assertIsNone(outcome["failure"])
            self.assertEqual(2, len(transport.requests))
            self.assertEqual(first_digest, base.digest(transport.requests[0]))
            self.assertEqual(outcome["requestDigest"], base.digest(transport.requests[-1]))
            for raw in transport.requests:
                request = base.strict_load(raw)
                self.assertEqual(expected_cap, request["max_output_tokens"])
                self.assertEqual(95, len(base.strict_load(request["input"])["issues"]))
            self.assertEqual(2, len(client.receipts()))

    def test_hold_unknown_checks_request_digest_model_stage_and_bytes_before_disposition(self):
        for mutation in ("requestDigest", "model", "stage", "request_bytes", "pending_json"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "private"
                first = grouped.GroupedSimulationClient(output, CorrectionTransport(unknown=True))
                candidates = self.candidates()
                with self.assertRaises(grouped.ReplayError):
                    grouped.attempt_grouped_selection(first, candidates, {}, "identity")
                digest = next(first.calls.glob("*.pending.json")).name.removesuffix(".pending.json")
                reservation_path = first.calls / (digest + ".pending.json")
                if mutation == "request_bytes":
                    (first.calls / (digest + ".request.json")).write_bytes(b"{}")
                elif mutation == "pending_json":
                    reservation_path.write_bytes(b"{invalid")
                else:
                    reservation = base.strict_load(reservation_path.read_bytes())
                    reservation[mutation] = "invalid-binding"
                    reservation_path.write_bytes(base.canonical(reservation))
                transport = AuthoredTransport()
                resumed = grouped.GroupedSimulationClient(output, transport, hold_unresolved_requests=True)
                with self.assertRaises(grouped.ReplayError) as caught:
                    grouped.attempt_grouped_selection(resumed, candidates, {}, "identity")
                self.assertNotIsInstance(caught.exception, grouped.HeldPaidRequest)
                self.assertTrue(resumed.stopped.is_set())
                self.assertEqual([], transport.requests)

    def test_holding_old_unknown_preserves_its_budget_slot_and_new_unknown_still_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "private"
            first = grouped.GroupedSimulationClient(output, CorrectionTransport(unknown=True), max_calls=1)
            candidates = self.candidates()
            with self.assertRaises(grouped.ReplayError):
                grouped.attempt_grouped_selection(first, candidates, {}, "first")
            before = {p.name: p.read_bytes() for p in first.calls.iterdir() if p.is_file()}
            transport = AuthoredTransport()
            resumed = grouped.GroupedSimulationClient(output, transport, max_calls=1, hold_unresolved_requests=True)
            with self.assertRaises(grouped.HeldPaidRequest):
                grouped.attempt_grouped_selection(resumed, candidates, {}, "first")
            self.assertFalse(resumed.stopped.is_set())
            self.assertEqual(before, {p.name: p.read_bytes() for p in resumed.calls.iterdir() if p.is_file()})
            with self.assertRaisesRegex(grouped.ReplayError, "paid_call_budget_exhausted"):
                grouped.attempt_grouped_selection(resumed, candidates, {"newRequest": True}, "second")
            self.assertTrue(resumed.stopped.is_set())
            self.assertEqual([], transport.requests)
            self.assertEqual(1, len(list(resumed.calls.glob("*.pending.json"))))


if __name__ == "__main__":
    unittest.main()
