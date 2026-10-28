import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]))
import briefing_price_aware_prompt as stage


class PriceAwarePromptTest(unittest.TestCase):
    def response(self):
        return {'id': 'r', 'editionReview': {'roundId': 'r', 'resultVersion': 'review', 'date': '2026-10-22',
            'edition': 'morning', 'cutoff': '2026-10-22T00:20:00Z', 'previousReview': None,
            'sources': {'s': {'quote': '도입 계획입니다.', 'publishedAt': '2026-10-21T20:01:00Z'}},
            'companies': [{'companyId': 'NASDAQ:A', 'companyName': '합성 기업', 'role': 'selected', 'sourceIds': ['s'],
                'previous': None, 'newInformation': {'text': '계획', 'evidenceIds': ['s']}}]},
            'companyPriceContext': {'roundId': 'r', 'reviewVersion': 'review', 'date': '2026-10-22', 'edition': 'morning',
                'cutoff': '2026-10-22T00:20:00Z', 'resultVersion': 'price', 'companies': [{
                'companyId': 'NASDAQ:A', 'currency': 'USD', 'provider': 'toss', 'cutoff': '2026-10-22T00:20:00Z',
                'status': 'available', 'responseSha256s': ['a'*64, 'b'*64], 'sessionDate': '2026-10-21',
                'exchangeTimezone': 'America/New_York', 'completeSession': True, 'barCount': 78,
                'latest': {'value': '100', 'kind': 'daily_close', 'observedAt': '2026-10-21T20:00:00Z'},
                'day': {'changeRatePercent': '1.00', 'baselineDate': '2026-10-20'},
                'news': [{'evidenceId': 's', 'publishedAt': '2026-10-21T20:01:00Z', 'timing': 'after_session',
                          'status': 'no_post_news_trade', 'postNewsBars': 0, 'before': None, 'changeRatePercent': None,
                          'observation': '규칙으로 만든 문장'}],
                'sinceMorning': {'status': 'unavailable', 'observation': '규칙 문장'},
                'outlook': {'text': '규칙 기반 기존 전망'}, 'interpretation': '규칙 해석'}]}}

    def test_real_observations_replace_unavailable_without_sending_rule_generated_opinions(self):
        r = self.response(); before = copy.deepcopy(r); frozen = stage.freeze(r)
        price = frozen['targets'][0]['observedMovement']
        self.assertEqual('available', price['status']); self.assertEqual('1.00', price['day']['changeRatePercent'])
        self.assertEqual('no_post_news_trade', price['news'][0]['status'])
        self.assertNotIn('outlook', price); self.assertNotIn('interpretation', price)
        self.assertNotIn('observation', price['news'][0]); self.assertEqual(r, before)

    def test_future_and_other_company_data_are_rejected_before_a_request_is_built(self):
        for kind in ('future_price', 'future_news', 'other_company'):
            r = self.response(); p = r['companyPriceContext']['companies'][0]
            if kind == 'future_price': p['latest']['observedAt'] = '2026-10-23T20:00:00Z'
            if kind == 'future_news': r['editionReview']['sources']['s']['publishedAt'] = '2026-10-23T20:01:00Z'
            if kind == 'other_company': p['companyId'] = 'NASDAQ:B'
            with self.assertRaises(ValueError): stage.freeze(r)

    def test_preparation_produces_an_immutable_structured_request_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'source'; source.mkdir(); output = Path(folder)/'output'
            file = source/'2026-10-22-morning.json'; file.write_bytes(stage.base.canonical(self.response())); before = file.read_bytes()
            args = SimpleNamespace(responses=str(source), output=str(output))
            proof = stage.run(args); request = json.loads((output/'2026-10-22-morning.request.json').read_bytes())
            self.assertEqual('PREPARED_ONLY', proof['status']); self.assertEqual(0, proof['paidCalls'])
            self.assertEqual('gpt-6-luna', request['model']); self.assertFalse(request['store'])
            self.assertTrue(request['text']['format']['strict'])
            self.assertIn('실제 시세를 활용한 기업 전망 v5', request['instructions'])
            self.assertEqual('available', json.loads(request['input'])['frozen']['targets'][0]['observedMovement']['status'])
            self.assertEqual(proof, stage.run(args)); self.assertEqual(before, file.read_bytes())


if __name__ == '__main__': unittest.main()
