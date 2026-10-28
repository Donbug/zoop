import copy
import unittest
from briefing_issue_reading import annotate


def fixture():
    source = {'documentId': 'shared-doc', 'bodySha256': 'a' * 64, 'quote': 'Synthetic approved event.'}
    statement = {'text': 'Confirmed change.', 'evidenceIds': ['e']}
    model = {'roundId': 'r', 'resultVersion': 'v', 'cutoff': '2026-10-22T00:20:00Z',
             'issues': [{'issueId': i, 'sources': {'e': dict(source, quote=source['quote'] + i)},
                         'companies': [{'companyId': 'c', 'sourceIds': ['e']}]} for i in ('a', 'b', 'c')]}
    recorded = {'round': {'roundId': 'r'}, 'selection': {'selected': []},
                'selectionVerification': {'checks': {i: {'supported': True} for i in ('a', 'b', 'c')}}}
    for issue in model['issues']:
        recorded['selection']['selected'].append({'issueId': issue['issueId'],
            'candidate': {'sources': copy.deepcopy(issue['sources']), 'companies': [{'companyId': 'c', 'role': 'manufacturer'}]},
            'assessment': {'whyImportant': statement, 'whyNow': statement,
                'relations': [{'companyId': 'c', 'directness': 'direct', 'basis': statement}]},
            'priceSignal': {'usedForRanking': False}})
    recorded['assessments'] = {'assessments': {s['issueId']: copy.deepcopy(s['assessment']) for s in recorded['selection']['selected']}}
    return {'id': 'r', 'issueIntelligence': model, 'items': [{'eventId': i, 'reason': 'Confirmed change. Confirmed change.'} for i in ('a', 'b', 'c')]}, recorded


class ReadingTests(unittest.TestCase):
    def test_no_implicit_same_company_document_merge_and_originals_unchanged(self):
        response, recorded = fixture(); before = copy.deepcopy(response)
        result = annotate(response, recorded)
        self.assertEqual(result['issueReading']['groups'], [])
        self.assertEqual(response, before)
        self.assertEqual(result['issueIntelligence'], before['issueIntelligence'])
        self.assertEqual(result['issueReading']['issues'][0]['connections'][0]['position'], 'primary')

    def test_explicit_group_keeps_independent_event_and_exact_support(self):
        response, recorded = fixture()
        group = {'id': 'family', 'title': 'Decision and dependent execution', 'issueIds': ['a', 'b'], 'reason': 'Reviewed conditional dependency.'}
        result = annotate(response, recorded, [group])
        self.assertEqual(result['items'], response['items'])
        self.assertEqual([s['issueId'] for s in result['issueReading']['groups'][0]['support']], ['a', 'b'])
        self.assertEqual(len(result['issueReading']['issues']), 3)

    def test_rejects_changed_sources_unverified_selection_and_overlapping_groups(self):
        response, recorded = fixture()
        recorded['selection']['selected'][0]['candidate']['sources']['e']['quote'] = 'Changed'
        with self.assertRaisesRegex(AssertionError, 'source_changed'): annotate(response, recorded)
        response, recorded = fixture(); recorded['selectionVerification']['checks']['a']['supported'] = False
        with self.assertRaisesRegex(AssertionError, 'unverified_selection'): annotate(response, recorded)
        response, recorded = fixture()
        group = {'id': 'f', 'title': 'Decision', 'issueIds': ['a', 'b'], 'reason': 'Reviewed'}
        with self.assertRaisesRegex(AssertionError, 'overlapping_groups'): annotate(response, recorded, [group, group])

    def test_rejects_reason_copy_tampering(self):
        response, recorded = fixture()
        recorded['selection']['selected'][0]['assessment']['whyImportant']['text'] = 'Not the verified reason.'
        with self.assertRaisesRegex(AssertionError, 'selection_assessment_changed'): annotate(response, recorded)
        response, recorded = fixture(); response['items'][0]['reason'] = 'Different reason'
        with self.assertRaisesRegex(AssertionError, 'projected_reason_changed'): annotate(response, recorded)


if __name__ == '__main__': unittest.main()
