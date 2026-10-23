"""Short evidence is allowed only with completed semantic proofs; grades/novelty stay strict."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import briefing_semantic_support as S
from test_briefing_grouped_rounds import archive, document, mention, round_spec, selection, record_grounding
G, B = S.grouped, S.base

class CoreEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        q = '합성 기업은 계약을 체결했다.'
        d = document('authored-doc', '2026-10-07T08:00:00+09:00', q)
        self.a = archive(('authored-issue', [(d, mention(d, 'authored-mention', q))]))
        self.key = record_grounding(self.a, self.root)

    def candidates(self):
        c = G.build_grouped_candidates(self.a, round_spec())
        c[0]['freshnessReview'] = {'decision': 'DISTINCT_EVENT', 'deltaEvidenceIds': []}
        return S.apply(c, S.load(self.a, self.root))

    def test_short_supported_grade_two_can_be_a_core_issue(self):
        c = self.candidates()
        self.assertLess(len(c[0]['newMentions'][0]['evidence'][0]['quote']), 80)
        frozen = G.freeze_grouped_selection(selection(c), c, 'identity')
        self.assertEqual(2, frozen[0]['importance'])
        self.assertEqual(S.POLICY, frozen[0]['frozenGroupedIssueSnapshot']['evidencePolicy'])

    def test_low_importance_does_not_become_core_because_quote_is_valid(self):
        c = self.candidates(); r = selection(c); r['assessments']['authored-issue']['importance'] = 1
        with self.assertRaisesRegex(G.ReplayError, 'not_eligible'): G.freeze_grouped_selection(r, c, 'identity')

    def test_reprint_and_uncertain_are_excluded_even_with_supported_quote(self):
        for verdict in ('REPEAT', 'UNCERTAIN'):
            c = self.candidates(); c[0]['freshnessReview']['decision'] = verdict
            c = S.apply(c, S.load(self.a, self.root))
            self.assertEqual(0, G.selection_schema(c)['properties']['selected']['maxItems'])

    def test_long_text_without_semantic_proof_is_excluded(self):
        c = self.candidates(); c[0]['newMentions'][0]['evidence'][0]['quote'] *= 100
        c = S.apply(c, S.load(self.a, self.root))
        self.assertFalse(S.eligible(c[0])); self.assertEqual(0, G.selection_schema(c)['properties']['selected']['maxItems'])

    def test_archive_supported_flag_cannot_replace_a_completed_receipt(self):
        self.a['receipts'] = []
        c = S.apply(G.build_grouped_candidates(self.a, round_spec()), S.load(self.a, self.root))
        self.assertFalse(S.eligible(c[0]))

    def test_tampered_original_or_event_and_receipt_are_rejected(self):
        for mutation in ('body', 'action', 'receipt'):
            with self.subTest(mutation=mutation):
                a = copy.deepcopy(self.a)
                if mutation == 'body': a['documents'][0]['body'] += '바뀜'
                elif mutation == 'action': a['issues'][0]['mentions'][0]['action'] = '새로운 해석'
                else: a['receipts'][0]['responseSha256'] = '0' * 64
                with self.assertRaises(G.ReplayError): S.load(a, self.root)

    def test_material_update_still_needs_exact_current_delta(self):
        c = self.candidates(); c[0]['freshnessReview']['decision'] = 'MATERIAL_UPDATE'
        c[0]['freshnessReview']['deltaEvidenceIds'] = c[0]['newEvidenceIds']; c = S.apply(c, S.load(self.a, self.root))
        r = selection(c)
        with self.assertRaises(G.ReplayError): G.freeze_grouped_selection(r, c, 'identity')
        r['selected'][0].update(novelty='MATERIAL_UPDATE', deltaEvidenceIds=c[0]['newEvidenceIds'])
        self.assertEqual(1, len(G.freeze_grouped_selection(r, c, 'identity')))

    def test_new_policy_creates_distinct_snapshot_without_mutating_old_candidate(self):
        old = G.build_grouped_candidates(self.a, round_spec()); before = B.canonical(old)
        new = S.apply(old, S.load(self.a, self.root))
        self.assertEqual(before, B.canonical(old)); self.assertNotEqual(old[0]['asOfSnapshotSha256'], new[0]['asOfSnapshotSha256'])


    def test_short_supported_quote_still_requires_all_linked_companies(self):
        c = self.candidates(); r = selection(c); r['selected'][0]['companyIds'] = []
        with self.assertRaises(G.ReplayError): G.freeze_grouped_selection(r, c, 'identity')

    def test_importance_three_still_requires_proven_broad_impact(self):
        c = self.candidates(); r = selection(c); r['assessments']['authored-issue']['importance'] = 3
        with self.assertRaisesRegex(G.ReplayError, 'impact_proof'): G.freeze_grouped_selection(r, c, 'identity')

    def test_new_run_prompt_is_versioned_and_legacy_prompt_stays_available(self):
        with tempfile.TemporaryDirectory() as out:
            client = G.GroupedSimulationClient(Path(out), lambda _: self.fail('offline schema construction cannot call provider'))
            data = {'context': {'selectionEvidencePolicy': S.POLICY, 'promptArtifacts': {
                'grouped-selection.md': B.digest(B.regular(G.PROMPTS/'selection-semantic-v2.md'))}}}
            raw, _, _ = client.request(G.SELECTION_STAGE, data, 'selection.md', 'selection.schema.json')
            self.assertEqual(B.strict_load(raw)['instructions'], B.regular(G.PROMPTS/'selection-semantic-v2.md').decode())
            legacy, _, _ = client.request(G.SELECTION_STAGE, {'context': {}}, 'selection.md', 'selection.schema.json')
            self.assertNotEqual(B.digest(raw), B.digest(legacy))
            self.assertEqual(B.strict_load(legacy)['instructions'], B.regular(G.PROMPTS/'selection.md').decode())

    def test_held_round_recovery_keeps_the_frozen_semantic_policy_and_short_quote(self):
        import briefing_grouped_recovery_run as recovery
        from test_briefing_grouped_rounds import AuthoredTransport
        candidates = S.apply(G.build_grouped_candidates(self.a, round_spec()), S.load(self.a, self.root))
        client = G.GroupedSimulationClient(self.root, AuthoredTransport())
        outcome = G.attempt_grouped_selection(client, candidates, {'context': {
            'selectionEvidencePolicy': S.POLICY}}, 'authored-identity')
        record = {**round_spec(), 'selectionStatus': 'HELD_VALIDATION',
            'identity': {'selectionEvidencePolicy': S.POLICY}, 'identitySha256': 'authored-identity',
            'groupedSelectionRequestDigest': outcome['requestDigest'],
            'receipts': [r for r in client.receipts() if r['stage'] == G.SELECTION_STAGE]}
        repaired = recovery.prepare_round(record, self.a, self.root/'calls', [])
        self.assertEqual('NEEDS_DRAFT', repaired[0]['status'])
        self.assertEqual(candidates[0], repaired[0]['selection']['frozenGroupedIssueSnapshot'])
        self.assertLess(len(repaired[0]['selection']['sources'][0]['quote']), 80)

if __name__ == '__main__': unittest.main()
