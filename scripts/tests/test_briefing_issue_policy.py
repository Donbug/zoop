"""Authored regression cases; never contact an AI/data provider."""
import copy
import unittest
import tempfile
from pathlib import Path
import test_briefing_grouped_rounds as f
import test_briefing_company_outlook as outlook

g, company = f.grouped, outlook.c
POLICY = g.issue_policy.VERSION


class IssuePolicyTests(unittest.TestCase):
    def candidates(self, count=4):
        groups = []
        for i in range(count):
            doc = f.document(str(i), '2026-10-07T08:00:00+09:00')
            groups.append(('issue-' + str(i), [(doc, f.mention(doc, str(i)))]))
        return g.build_grouped_candidates(f.archive(*groups), f.round_spec())

    def select(self, candidates, reply=None, previous=()):
        return g.freeze_grouped_selection(reply or f.selection(candidates, list(range(len(candidates)))),
            candidates, 'a' * 64, previous, POLICY)

    def test_same_company_can_have_three_independent_issues(self):
        c = self.candidates()
        old = g.freeze_grouped_selection(f.selection(c), c, 'a' * 64)
        new = self.select(c)
        self.assertEqual([x['issueId'] for x in old], ['issue-2', 'issue-1', 'issue-0'])
        self.assertEqual([x['issueId'] for x in new], ['issue-0', 'issue-1', 'issue-2'])
        self.assertEqual(len({x['companyLinks'][0]['companyId'] for x in new}), 1)
        self.assertTrue(all(x['selectionPolicy']['priceSignal']['value'] is None for x in new))

    def test_same_document_distinct_exact_event_spans_are_allowed(self):
        a = '합성 기업은 장비 공급 계약을 체결했습니다.'
        b = '합성 기업은 공장 투자계획을 별도로 확대했습니다.'
        doc = f.document('one', '2026-10-07T08:00:00+09:00', a + ' ' + b)
        archive = f.archive(('a', [(doc, f.mention(doc, 'a', a))]), ('b', [(doc, f.mention(doc, 'b', b))]))
        archive['documents'] = [doc]
        c = g.build_grouped_candidates(archive, f.round_spec())
        self.assertEqual(len(self.select(c)), 2)
        with self.assertRaisesRegex(g.ReplayError, 'one_source'):
            g.freeze_grouped_selection(f.selection(c), c, 'a' * 64)

    def test_same_span_under_different_ids_is_only_one_issue(self):
        doc = f.document('one', '2026-10-07T08:00:00+09:00')
        archive = f.archive(('a', [(doc, f.mention(doc, 'a'))]), ('b', [(doc, f.mention(doc, 'b'))]))
        archive['documents'] = [doc]
        c = g.build_grouped_candidates(archive, f.round_spec())
        self.assertEqual(len(self.select(c)), 1)

    def test_failed_material_update_uses_next_eligible_not_relaxed_evidence(self):
        c = self.candidates(); reply = f.selection(c, [0, 1, 2, 3])
        previous = [{'issueId': 'issue-0', 'sources': []}]
        self.assertEqual([x['issueId'] for x in self.select(c, reply, previous)], ['issue-1', 'issue-2', 'issue-3'])

    def test_no_filling_with_low_importance_or_invented_price(self):
        c = self.candidates(); reply = f.selection(c, [0, 1, 2, 3])
        for a in reply['assessments'].values(): a['importance'] = 1
        self.assertEqual(self.select(c, reply), [])

    def test_policy_is_in_request_identity_and_old_requests_unchanged(self):
        c = self.candidates()
        legacy = g.grouped_selection_data(c, {'context': {}})
        self.assertNotIn('maximumPublishedIssues', legacy)
        data = g.grouped_selection_data(c, {'context': {'issueSelectionPolicy': POLICY}})
        self.assertEqual(data['maximumIssues'], 4)
        self.assertEqual(data['maximumPublishedIssues'], 3)
        self.assertEqual(g.selection_schema(c, policy=POLICY)['properties']['selected']['maxItems'], 4)


class IssueCompanyComparisonTests(unittest.TestCase):
    def row(self, issue='contract', day='2026-10-23', edition='evening'):
        return {'status': 'PASS', 'date': day, 'edition': edition,
            'cutoff': day + ('T17:30:00+09:00' if edition == 'evening' else 'T09:20:00+09:00'),
            'roundId': day + edition, 'resultVersion': 'recorded',
            'frozen': {'targets': [{'companyId': 'A', 'issueIds': [issue]}]},
            'draft': {'companies': [{'companyId': 'A', 'outlook': {'text': '기존 판단', 'evidenceIds': ['a']}}]}}

    def before(self, rows, issue='contract', day='2026-10-26', edition='morning'):
        return company.previous_issue_company('A', issue, day, edition,
            day + ('T09:20:00+09:00' if edition == 'morning' else 'T17:30:00+09:00'), rows)

    def test_weekend_uses_latest_evening_and_same_event(self):
        rows = [self.row()]; baseline = copy.deepcopy(rows)
        self.assertEqual(self.before(rows)['status'], 'available')
        self.assertEqual(self.before(rows, issue='equity')['status'], 'unavailable')
        self.assertEqual(rows, baseline)

    def test_does_not_fall_back_past_corresponding_round(self):
        self.assertEqual(self.before([self.row(day='2026-10-22'), self.row(issue='equity')])['status'], 'unavailable')

    def test_evening_only_uses_same_day_morning(self):
        self.assertEqual(self.before([self.row()], day='2026-10-26', edition='evening')['status'], 'unavailable')
        self.assertEqual(self.before([self.row(day='2026-10-26', edition='morning')], day='2026-10-26', edition='evening')['status'], 'available')

    def test_future_and_multi_issue_company_judgments_are_not_comparisons(self):
        self.assertEqual(self.before([self.row(day='2026-10-27')])['status'], 'unavailable')
        row = self.row(); row['frozen']['targets'][0]['issueIds'].append('equity')
        self.assertEqual(self.before([row])['status'], 'unavailable')

    def test_conflicting_revisions_are_not_chosen_arbitrarily(self):
        self.assertEqual(self.before([self.row(), self.row()])['status'], 'unavailable')


class IssueInputTests(unittest.TestCase):
    def test_separate_inputs_preserve_same_company_and_do_not_mix_issue_facts(self):
        helper = IssuePolicyTests(); candidates = helper.candidates(3)
        selected = helper.select(candidates)
        metadata = {s['documentId']: {'title': '합성 문서', 'url': 'https://example.invalid/' + s['documentId']} for v in selected for s in v['sources']}
        effective = {'selected': selected, 'resultSha256': 'a' * 64, 'result': {'items': [
            {'issueId': v['issueId'], 'claims': [{'text': '해당 사건의 사실', 'evidenceIds': [v['sources'][0]['evidenceId']]}]} for v in selected]}}
        row = {'roundId': 'r', 'date': '2026-10-07', 'edition': 'morning', 'marketEnrichment': {'cutoff': '2026-10-07T09:20:00+09:00'}}
        before = copy.deepcopy(effective)
        inputs = company.freeze_issue_inputs(row, effective, metadata, [])
        self.assertEqual(len(inputs), 3)
        self.assertEqual({v['targets'][0]['companyId'] for v in inputs}, {'company-authored'})
        for value in inputs:
            self.assertEqual(value['targets'][0]['issueIds'], [value['issueId']])
            self.assertEqual(len(value['sources']), 1)
        self.assertEqual(effective, before)

    def test_background_only_statement_cannot_impersonate_issue_analysis(self):
        case = outlook.CompanyOutlookTest(); frozen = case.frozen(); draft = case.draft()
        frozen.update(comparisonContract='issue-company-v1', issueId='contract', date='2026-10-26', cutoff='2026-10-26T09:20:00+09:00')
        frozen['targets'][0].update(issueIds=['contract'], issueEvidenceIds=['a'], sourceIds=['a','background'])
        frozen['sources']['background'] = {}
        company.validate(draft, frozen)
        draft['companies'][0]['impact']['evidenceIds'] = ['background']
        with self.assertRaisesRegex(ValueError, 'issue_anchor_missing'): company.validate(draft, frozen)


class PolicyRejectionAuditTest(unittest.TestCase):
    def test_all_rejected_is_validation_hold_not_source_shortage_or_model_retry(self):
        c = IssuePolicyTests().candidates(1)
        context = {'context': {'issueSelectionPolicy': POLICY}}
        with tempfile.TemporaryDirectory() as tmp:
            transport = f.AuthoredTransport()
            client = g.GroupedSimulationClient(Path(tmp), transport)
            result = g.attempt_grouped_selection(client, c, context, 'a' * 64, [{'issueId': 'issue-0', 'sources': []}])
            self.assertEqual(result['failure'], 'issue_policy_all_proposals_rejected')
            self.assertEqual(result['rejectedSelections'][0]['reason'], 'grouped_repeat_issue_without_supported_material_update')
            self.assertEqual(len(transport.requests), 1)
