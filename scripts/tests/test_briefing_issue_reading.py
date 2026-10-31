"""Receipt-backed authored fixtures only; transport never leaves this process."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import briefing_issue_intelligence as m
import briefing_issue_intelligence_view as view
from briefing_issue_reading import annotate
from test_briefing_issue_intelligence import frozen, assess, checks
from test_briefing_review_regressions import draft_for


def fixture(*, round_id='r', cutoff='2026-10-22T09:20:00+09:00',
            edition='morning', issue_prefix='', condition_text=None):
    baseline = {'id': round_id, 'date': cutoff[:10], 'edition': edition,
                'dataAsOf': cutoff, 'items': [], 'metadata': {'selection': {}}, 'graphVersion': None}
    source = frozen(3)
    source.update(roundId=round_id, cutoff=cutoff, date=cutoff[:10], edition=edition)
    for candidate in source['candidates']:
        candidate['issueId'] = issue_prefix + candidate['issueId']
        candidate['companies'][0]['role'] = 'manufacturer'
        # Equal companies/documents still contain distinct, independent quotes.
        next(iter(candidate['sources'].values()))['documentId'] = 'shared-doc'
    source = m.seal({**source, 'baselineResponseSha256': m.base.digest(m.base.canonical(baseline))})
    def transport(raw):
        request = json.loads(raw); data = json.loads(request['input']); stage = request['text']['format']['name']
        if stage == 'selection': answer = assess(data['frozen'])
        elif stage == 'selection-verification': answer = checks(data['frozen'])
        elif stage == 'analysis':
            answer = draft_for(data['issues'])
            if condition_text is not None:
                for issue in answer['issues'].values():
                    for company in issue['companies']:
                        company['conditions'][0]['text'] = condition_text
        else: answer = {'checks': {i['issueId']: {'supported': True, 'reason': 'Synthetic check'} for i in data['issues']}}
        return 200, m.base.canonical({'id': 'synthetic-' + stage, 'status': 'completed',
            'usage': {'input_tokens': 1, 'output_tokens': 1},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(answer)}]}]})
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); prepared = root/'in'; prepared.mkdir()
        (prepared/'r.input.json').write_bytes(m.base.canonical(source))
        recorded = m.run(prepared, root/'out', transport, 8, 'synthetic')['rounds'][0]
        calls = view.verified_calls(root/'out')
    return view.project(baseline, source, recorded, calls)['response'], recorded, source, calls


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.response, self.recorded, self.frozen, self.calls = fixture()

    def annotate(self, groups=()):
        return annotate(self.response, self.recorded, groups, frozen=self.frozen, calls=self.calls)

    def test_no_implicit_same_company_document_merge_and_originals_unchanged(self):
        before = copy.deepcopy((self.response, self.recorded, self.frozen, self.calls))
        result = self.annotate()
        self.assertEqual(result['issueReading']['groups'], [])
        self.assertEqual(result['issueIntelligence'], before[0]['issueIntelligence'])
        self.assertEqual(result['issueReading']['issues'][0]['connections'][0]['position'], 'primary')
        self.assertEqual((self.response, self.recorded, self.frozen, self.calls), before)
        self.assertEqual(self.annotate(), result)

    def test_explicit_group_keeps_independent_event_and_exact_support(self):
        group = {'id': 'family', 'title': 'Decision and dependent execution', 'issueIds': ['i0', 'i1'], 'reason': 'Reviewed conditional dependency.'}
        result = self.annotate([group])
        self.assertEqual(result['items'], self.response['items'])
        self.assertEqual([s['issueId'] for s in result['issueReading']['groups'][0]['support']], ['i0', 'i1'])
        self.assertEqual(len(result['issueReading']['issues']), 3)

    def test_rejects_overlapping_groups(self):
        group = {'id': 'f', 'title': 'Decision', 'issueIds': ['i0', 'i1'], 'reason': 'Reviewed'}
        with self.assertRaisesRegex(AssertionError, 'overlapping_groups'): self.annotate([group, group])

    def test_rejects_changed_candidate_source(self):
        self.recorded['selection']['selected'][0]['candidate']['sources']['e0']['quote'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'selected_assessment_binding'): self.annotate()

    def test_rejects_changed_verification(self):
        self.recorded['selectionVerification']['checks']['i0']['supported'] = False
        with self.assertRaisesRegex(ValueError, 'reused_assessment_receipts'): self.annotate()

    def test_rejects_reason_copy_tampering(self):
        self.recorded['selection']['selected'][0]['assessment']['whyImportant']['text'] = 'Not the verified reason.'
        with self.assertRaisesRegex(ValueError, 'selected_assessment_binding'): self.annotate()

    def test_rejects_changed_projected_reason(self):
        self.response['items'][0]['reason'] = 'Different reason'
        with self.assertRaisesRegex(ValueError, 'reading_projection_changed:items'): self.annotate()

    def test_rejects_relation_changed_in_both_copies_despite_unchanged_owned_sources(self):
        before = copy.deepcopy(self.calls)
        self.recorded['selection']['selected'][0]['assessment']['relations'][0]['basis']['text'] = 'Not verified'
        self.recorded['assessments']['assessments']['i0']['relations'][0]['basis']['text'] = 'Not verified'
        with self.assertRaisesRegex(ValueError, 'reused_assessment_receipts'): self.annotate()
        self.assertEqual(self.calls, before)

    def test_rejects_changed_price_ranking_flag_with_original_analysis_receipts(self):
        self.recorded['selection']['selected'][0]['priceSignal']['usedForRanking'] = True
        with self.assertRaisesRegex(ValueError, 'analysis_input_binding'): self.annotate()

    def test_rejects_missing_receipts_instead_of_using_matching_copies(self):
        self.calls = []
        with self.assertRaisesRegex(ValueError, 'reused_assessment_receipts'): self.annotate()

    def test_rejects_changed_projected_model(self):
        self.response['issueIntelligence']['issues'][0]['companies'][0]['takeaway']['text'] = 'Changed prose'
        with self.assertRaisesRegex(ValueError, 'reading_projection_changed:issueIntelligence'): self.annotate()


if __name__ == '__main__': unittest.main()
