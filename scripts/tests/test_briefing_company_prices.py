import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('company_prices_test', Path(__file__).parents[1] / 'briefing_company_prices.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class CompanyPriceTest(unittest.TestCase):
    def archive(self, root, cid='KRX:005930'):
        symbol, currency, zone = p.identity(cid)
        def send(url):
            daily = 'interval=1d' in url
            if currency == 'KRW':
                stamps = ['2026-10-07T00:00:00Z', '2026-10-08T00:00:00Z'] if daily else [
                    '2026-10-08T00:15:00Z', '2026-10-08T00:20:00Z', '2026-10-21T06:00:00Z']
                values = [270000, 262000] if daily else [268500, 999999, 888888]
            else:
                stamps = ['2026-10-07T13:30:00Z']
                values = [472]
            data = {'chart': {'error': None, 'result': [{'meta': {'symbol': symbol, 'currency': currency,
                    'exchangeTimezoneName': zone, 'regularMarketPrice': 99999999},
                    'timestamp': [int(p.market.aware(s).timestamp()) for s in stamps],
                    'indicators': {'quote': [{'close': values}]}}]}}
            return 200, json.dumps(data).encode()
        return p.collect([cid], root, send)[cid]

    def test_morning_uses_completed_bar_not_future_bar_daily_close_or_live_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            refs = self.archive(root)
            result = p.snapshot('KRX:005930', '2026-10-08T09:20:00+09:00', refs, root)
            self.assertEqual('268500.00', result['latest']['value'])
            self.assertEqual('2026-10-08T00:20:00Z', result['latest']['observedAt'])
            self.assertEqual('270000.00', result['baseline']['value'])
            self.assertEqual('five_minute_close', result['latest']['kind'])

    def test_evening_compares_same_day_morning_not_previous_daily_close(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = p.snapshot('KRX:005930', '2026-10-08T17:30:00+09:00', self.archive(root), root)
            self.assertEqual('262000.00', result['latest']['value'])
            self.assertEqual('268500.00', result['baseline']['value'])
            self.assertEqual('-2.42', result['changeRate'])
            self.assertEqual('morning_cutoff', result['baselineKind'])

    def test_us_has_no_new_regular_session_between_korean_morning_and_evening(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = p.snapshot('NYSE:TSM', '2026-10-08T17:30:00+09:00', self.archive(root, 'NYSE:TSM'), root)
            self.assertEqual('no_new_session', result['comparisonStatus'])
            self.assertIsNone(result['changeRate'])
            self.assertIsNone(result['change'])

    def test_cache_is_reused_and_modified_raw_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            refs = self.archive(root)
            reused = p.collect(['KRX:005930'], root, lambda _: self.fail('cache refetched'))
            self.assertEqual(refs, reused['KRX:005930'])
            (root / 'company-prices' / (refs[0]['sha256'] + '.bin')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'cache_changed'):
                p.collect(['KRX:005930'], root, lambda _: self.fail('changed raw refetched'))

    def test_other_company_receipt_and_empty_history_are_not_substituted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            refs = self.archive(root)
            wrong = copy.deepcopy(refs)
            wrong[0]['companyId'] = 'KRX:000660'
            result = p.snapshot('KRX:005930', '2026-10-08T09:20:00+09:00', wrong, root)
            self.assertEqual('unavailable', result['status'])
            self.assertIsNone(result['latest'])

    def test_provider_failure_is_distinct_from_successful_empty_history(self):
        for status in (200, 503):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                symbol, currency, zone = p.identity('KRX:005930')
                raw = json.dumps({'chart': {'error': None, 'result': [{'meta': {
                    'symbol': symbol, 'currency': currency, 'exchangeTimezoneName': zone},
                    'timestamp': [], 'indicators': {'quote': [{'close': []}]}}]}}).encode()
                calls = []
                def send(url):
                    calls.append(url)
                    return status, raw if status == 200 else b'provider temporarily unavailable'
                refs = p.collect(['KRX:005930'], root, send)['KRX:005930']
                result = p.snapshot('KRX:005930', '2026-10-08T09:20:00+09:00', refs, root)
                self.assertEqual('unavailable', result['status'])
                self.assertEqual('eligible_price_missing' if status == 200 else 'provider_request_failed', result['reason'])
                self.assertEqual([status, status], [r['httpStatus'] for r in result['sources']])
                self.assertEqual(2, len(calls))
                self.assertIsNone(result['latest'])


if __name__ == '__main__':
    unittest.main()
