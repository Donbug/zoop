import copy
import unittest
from briefing_issue_followups import attach_followups
from test_briefing_issue_reading import fixture


def bundle(**kwargs):
    response, recorded, frozen, calls = fixture(**kwargs)
    return dict(response=response, recorded=recorded, frozen=frozen, calls=calls)


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.prior = bundle()
        self.current = bundle(round_id='evening', cutoff='2026-10-22T17:30:00+09:00',
                              edition='evening', issue_prefix='different-')

    def test_same_company_distinct_issues_retained_with_original_evidence(self):
        before = copy.deepcopy((self.current, self.prior))
        result = attach_followups(self.current, [self.prior])
        entries = result['issueFollowUps']['entries']
        self.assertEqual([e['issueId'] for e in entries], ['i0', 'i1', 'i2'])
        self.assertTrue(all(e['status'] == 'outcome_unverified' for e in entries))
        self.assertEqual(entries[0]['sources'][0]['quote'],
                         self.prior['response']['issueIntelligence']['issues'][0]['sources']['e0']['quote'])
        self.assertEqual((self.current, self.prior), before)
        result.pop('issueFollowUps')
        self.assertEqual(result, self.current['response'])

    def test_current_pairs_stay_in_current_cards_not_carry_list(self):
        current = bundle(round_id='evening', cutoff='2026-10-22T17:30:00+09:00', edition='evening')
        self.assertEqual(attach_followups(current, [self.prior])['issueFollowUps']['entries'], [])

    def test_no_history_is_explicit_not_claim_of_no_pending_conditions(self):
        result = attach_followups(self.current, [])['issueFollowUps']
        self.assertEqual(result['reviewedRounds'], [])
        self.assertEqual(result['entries'], [])
        self.assertEqual(result['scope'], 'provided_verified_rounds')

    def test_changed_conditions_do_not_erase_older_unverified_conditions(self):
        next_round = bundle(round_id='next', cutoff='2026-10-23T09:20:00+09:00', issue_prefix='new-')
        updated = bundle(round_id='evening', cutoff='2026-10-22T17:30:00+09:00', edition='evening',
                         condition_text='합성 납품 일정을 추가 확인합니다.')
        entries = attach_followups(next_round, [updated, self.prior])['issueFollowUps']['entries']
        self.assertEqual(len(entries), 6)
        self.assertEqual({e['origin']['roundId'] for e in entries}, {'r', 'evening'})
        self.assertTrue(all(e['status'] == 'outcome_unverified' for e in entries))

    def test_identical_repeated_conditions_keep_latest_verified_origin(self):
        next_round = bundle(round_id='next', cutoff='2026-10-23T09:20:00+09:00', issue_prefix='new-')
        repeated = bundle(round_id='evening', cutoff='2026-10-22T17:30:00+09:00', edition='evening')
        entries = attach_followups(next_round, [repeated, self.prior])['issueFollowUps']['entries']
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(e['origin']['roundId'] == 'evening' for e in entries))

    def test_rejects_future_round_and_duplicate_revision(self):
        with self.assertRaisesRegex(ValueError, 'future_round'):
            attach_followups(self.prior, [self.current])
        with self.assertRaisesRegex(ValueError, 'ambiguous_round'):
            attach_followups(self.current, [self.prior, self.prior])

    def test_rejects_edited_history_and_missing_receipts(self):
        self.prior['response']['issueIntelligence']['issues'][0]['companies'][0]['conditions'][0]['text'] = 'Fake'
        with self.assertRaisesRegex(ValueError, 'followup_projection_changed'):
            attach_followups(self.current, [self.prior])
        self.prior = bundle()
        self.prior['calls'] = []
        with self.assertRaisesRegex(ValueError, 'reused_assessment_receipts'):
            attach_followups(self.current, [self.prior])

    def test_rejects_edited_current_round(self):
        self.current['response']['dataAsOf'] = '2026-10-30T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'followup_projection_changed:dataAsOf'):
            attach_followups(self.current, [self.prior])


if __name__ == '__main__': unittest.main()
