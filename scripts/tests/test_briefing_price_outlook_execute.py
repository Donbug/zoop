import copy
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import briefing_price_outlook_execute as e

class SequentialPriceTest(unittest.TestCase):
    def fixture(self, edition='morning'):
        return {'date': '2026-10-22', 'edition': edition, 'cutoff': '2026-10-22T00:20:00Z',
                'targets': [{'companyId': 'A', 'previous': {'status': 'available', 'kind': 'preserved_editorial_review'},
                             'observedMovement': {'latest': {'value': '110'}}}], 'inputSha256': 'original'}
    def prior(self, status='PASS', date='2026-10-21', edition='evening'):
        return {'status': status, 'date': date, 'edition': edition, 'roundId': 'old', 'cutoff': '2026-10-21T08:30:00Z',
                'resultVersion': 'ai-old', 'draft': {'companies': [{'companyId': 'A', 'outlook': {'text': '실제 이전 판단'}}]}}
    def test_next_uses_verified_ai_and_preserves_prepared_input(self):
        f=self.fixture();old=copy.deepcopy(f);result=e.sequential(f,[self.prior()])
        self.assertEqual(f,old);p=result['targets'][0]['previous']
        self.assertEqual((p['resultVersion'],p['kind']),('ai-old','verified_ai_price_outlook'))
        self.assertEqual(result['targets'][0]['observedMovement'],f['targets'][0]['observedMovement'])
        digest=result.pop('inputSha256');self.assertEqual(digest,e.base.digest(e.base.canonical(result)))
    def test_withheld_and_wrong_edition_are_not_previous_success(self):
        for prior in [self.prior('WITHHELD'),self.prior(edition='morning'),self.prior(date='2026-10-20')]:
            self.assertEqual(e.sequential(self.fixture(),[prior])['targets'][0]['previous']['status'],'unavailable')
    def test_evening_only_compares_same_day_morning(self):
        self.assertEqual(e.sequential(self.fixture('evening'),[self.prior(date='2026-10-22',edition='morning')])['targets'][0]['previous']['status'],'available')
        self.assertEqual(e.sequential(self.fixture('evening'),[self.prior()])['targets'][0]['previous']['status'],'unavailable')

if __name__=='__main__':unittest.main()
