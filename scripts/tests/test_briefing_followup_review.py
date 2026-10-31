import copy
import hashlib
import unittest

from briefing_followup_review import attach_review, condition_ref
from briefing_issue_followups import attach_followups
from test_briefing_issue_followups import bundle


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.prior = bundle()
        self.current = bundle(round_id='evening', cutoff='2026-10-22T17:30:00+09:00',
                              edition='evening', issue_prefix='different-')
        self.base = attach_followups(self.current, [self.prior])
        body = 'Synthetic: the contracted delivery was completed.'
        self.docs = {'doc': dict(body=body, bodySha256=hashlib.sha256(body.encode()).hexdigest(),
            publishedAt='2026-10-22T12:00:00+09:00', title='Synthetic source',
            url='https://example.test', timestampVerified=True, historicalVersionExcluded=False)}
        self.review = {k:self.base['issueFollowUps'][k] for k in ('roundId','baseResultVersion','cutoff')}
        self.review.update(reviewedAt='2026-10-29T09:00:00+09:00', entries=[])
        for e in self.base['issueFollowUps']['entries']:
            self.review['entries'].append(dict(ref=condition_ref(e), summary='Synthetic recorded review.',
                sources=[dict(id='s',documentId='doc',bodySha256=self.docs['doc']['bodySha256'],
                              quote=body,start=0,end=len(body),relation='same_event',kind='completed_action')],
                facts=[dict(text='Synthetic completion fact.',sourceIds=['s'])],
                requirements=[dict(text='Synthetic delivery completion.',observation='completed',sourceIds=['s'])]))

    def apply(self):
        return attach_review(self.current,[self.prior],self.review,self.docs)

    def test_completion_supported_by_later_evidence_without_mutating_original(self):
        before=copy.deepcopy((self.current,self.prior,self.review,self.docs))
        result=self.apply()
        self.assertTrue(all(e['status']=='fulfilled' for e in result['issueFollowUpReview']['entries']))
        result.pop('issueFollowUpReview')
        self.assertEqual(result,self.base)
        self.assertEqual(before,(self.current,self.prior,self.review,self.docs))

    def test_one_unconfirmed_part_keeps_whole_condition_pending(self):
        self.review['entries'][0]['requirements'].append(dict(text='Additional required acceptance.',observation='unverified',sourceIds=[]))
        self.assertEqual(self.apply()['issueFollowUpReview']['entries'][0]['status'],'insufficient_evidence')

    def test_no_sources_means_no_completion_not_failure(self):
        e=self.review['entries'][0]
        e['sources']=[];e['facts']=[]
        e['requirements'][0].update(observation='unverified',sourceIds=[])
        self.assertEqual(self.apply()['issueFollowUpReview']['entries'][0]['status'],'insufficient_evidence')

    def test_plans_other_events_and_old_evidence_cannot_complete(self):
        original=copy.deepcopy((self.review,self.docs))
        for kind in ['plan','background','related_event','before_origin']:
            with self.subTest(kind=kind):
                self.review,self.docs=copy.deepcopy(original)
                s=self.review['entries'][0]['sources'][0]
                if kind in ('plan','background'):s['kind']=kind
                elif kind=='related_event':s['relation']=kind
                else:self.docs['doc']['publishedAt']='2026-10-22T08:00:00+09:00'
                with self.assertRaisesRegex(ValueError,'completion_evidence'):self.apply()

    def test_reject_invalid_source_condition_or_round_bindings(self):
        original=copy.deepcopy((self.review,self.docs))
        for kind in ['future','hash','quote','clock','version','condition','origin','missing','duplicate','foreign_fact','empty_requirements']:
            with self.subTest(kind=kind):
                self.review,self.docs=copy.deepcopy(original)
                e=self.review['entries'][0]
                if kind=='future':self.docs['doc']['publishedAt']='2026-10-23T12:00:00+09:00'
                if kind=='hash':self.docs['doc']['body']+=' altered'
                if kind=='quote':e['sources'][0]['quote']='Invented'
                if kind=='clock':self.docs['doc']['historicalVersionExcluded']=True
                if kind=='version':self.review['baseResultVersion']='other'
                if kind=='condition':e['ref']['condition']['text']='Other task, same company'
                if kind=='origin':e['ref']['origin']['resultVersion']='other'
                if kind=='missing':self.review['entries'].pop()
                if kind=='duplicate':self.review['entries'].append(copy.deepcopy(e))
                if kind=='foreign_fact':e['facts'][0]['sourceIds']=['missing']
                if kind=='empty_requirements':e['requirements']=[]
                with self.assertRaises(ValueError):self.apply()

    def test_original_receipts_still_required(self):
        self.current['calls']=[]
        with self.assertRaises(ValueError):self.apply()


if __name__=='__main__':unittest.main()
