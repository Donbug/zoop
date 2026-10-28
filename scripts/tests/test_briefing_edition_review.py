from pathlib import Path
import copy
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1]))
import briefing_edition_review as e


def source(sid, body, at):
    return {'evidenceId': sid, 'documentId': sid, 'documentVersion': 'sha', 'bodySha256': e.base.digest(body.encode()), 'quote': body.split('\n')[0], 'publishedAt': at, 'title': '합성 출처', 'url': 'https://example.com/' + sid}

def current(cid, date, edition, body):
    cutoff = date + ('T09:20:00+09:00' if edition == 'morning' else 'T17:30:00+09:00')
    return {'roundId': date + edition, 'date': date, 'edition': edition, 'cutoff': cutoff, 'resultVersion': 'a-' + cid, 'frozen': {'targets': [{'companyId': cid, 'companyName': cid, 'sourceIds': [cid]}], 'sources': {cid: source(cid, body, cutoff)}}}

class EditionReviewTest(unittest.TestCase):
    def setUp(self):
        self.now = current('B', '2026-10-22', 'evening', '새 계획\n추가 조건')
        self.prior = {'resultVersion': 'previous', 'draft': {'companies': [{'companyId': 'A', 'watch': [{'text': '실제 납품 확인', 'evidenceIds': ['A']}]}]},
                      'frozen': {'roundId': 'morning', 'date': '2026-10-22', 'edition': 'morning', 'cutoff': '2026-10-22T09:20:00+09:00',
                          'sources': {'A': {**source('A', '이전 계약 계획', '2026-10-21T17:00:00+09:00'), 'fullBody': '이전 계약 계획'}},
                          'targets': [{'companyId': 'A', 'companyName': 'A', 'sourceIds': ['A']}]}}
        with patch.object(e.prices, 'snapshot', return_value={'status': 'unavailable'}):
            self.f = e.freeze(self.now, self.prior, {'B': {'body': '새 계획\n추가 조건', 'bodySha256': self.now['frozen']['sources']['B']['bodySha256']}}, 'a'*64, {'A': [], 'B': []}, Path('.'))
    def draft(self):
        s = lambda text, ids: {'text': text, 'evidenceIds': ids}
        companies = []
        for t in self.f['targets']:
            cid = t['companyId']; stmt = s('확인 조건입니다.', t['sourceIds'])
            companies.append({'companyId': cid, 'stance': 'watch', **{k: copy.deepcopy(stmt) for k in ('title','takeaway','newInformation','judgment','positive','negative')},
                              'watch': [s('실제 납품 확인', t['sourceIds'])] if t['previous'] is not None else [copy.deepcopy(stmt)], 'checks': [] if t['previous'] is None else [{'condition':'실제 납품 확인','status':'not_observed','observation':copy.deepcopy(stmt)}]})
        return {'headline':'합성 퇴근 검토','summary':s('자료의 한계를 구분합니다.', []),'marketInterpretation':s('종가 기준입니다.', []),
                'comparison':s('조건은 아직 관측되지 않았습니다.', []),'nextSession':s('다음 확인 조건입니다.', []),'companies':companies}
    def test_new_selection_keeps_all_morning_companies_and_actual_conditions(self):
        self.assertEqual([(t['companyId'],t['role']) for t in self.f['targets']], [('B','selected'),('A','tracked')])
        self.assertEqual(self.f['targets'][1]['previous'],self.prior['draft']['companies'][0]);e.validate(self.draft(),self.f)
        d=self.draft();d['companies'].pop()
        with self.assertRaises((e.base.ReplayError,ValueError)):e.validate(d,self.f)
    def test_price_movement_cannot_substitute_for_a_new_condition_evidence(self):
        for status in ['confirmed','contradicted']:
            d=self.draft();d['companies'][1]['checks'][0]['status']=status
            with self.assertRaisesRegex(ValueError,'no_new_condition_evidence'):e.validate(d,self.f)
    def test_previous_conditions_cannot_be_rewritten_or_silently_dropped(self):
        for action in ['rewrite','drop']:
            d=self.draft()
            if action=='drop':d['companies'][1]['checks']=[]
            else:d['companies'][1]['checks'][0]['condition']='새로 바꾼 조건'
            with self.assertRaisesRegex(ValueError,'previous_condition_coverage'):e.validate(d,self.f)
    def test_other_company_and_future_evidence_remain_forbidden(self):
        d=self.draft();d['companies'][1]['judgment']['evidenceIds']=['B']
        with self.assertRaisesRegex(ValueError,'edition_evidence'):e.validate(d,self.f)
        self.now['frozen']['sources']['B']['publishedAt']='2026-10-23T01:00:00+09:00'
        with patch.object(e.prices,'snapshot',return_value={}):
            with self.assertRaisesRegex(ValueError,'future_source'):e.freeze(self.now,self.prior,{'B':{'body':'새 계획\n추가 조건','bodySha256':self.now['frozen']['sources']['B']['bodySha256']}},'a'*64,{'A':[],'B':[]},Path('.'))
    def test_unobserved_condition_stays_on_the_next_watch_list(self):
        d=self.draft();d['companies'][1]['watch']=[{'text':'새로 바꾼 관찰 과제','evidenceIds':['A']}]
        with self.assertRaisesRegex(ValueError,'unresolved_condition_dropped'):e.validate(d,self.f)

    def test_missing_morning_is_explicit_and_no_manual_file_mutation(self):
        self.prior['frozen']['date']='2026-10-21';self.assertIsNone(e.reference(self.prior,self.now))
        d=self.draft();original=copy.deepcopy(d);e.validate(d,self.f);self.assertEqual(d,original)

if __name__=='__main__':unittest.main()
