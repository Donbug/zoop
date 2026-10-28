import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
import briefing_series_prices as series

p = series.prices


class SeriesPricesTest(unittest.TestCase):
    def transport(self, url):
        daily = 'interval=1d' in url
        times = ['2026-10-20T13:30:00Z', '2026-10-21T13:30:00Z'] if daily else [
            '2026-10-21T19:55:00Z', '2026-10-22T13:30:00Z', '2026-10-23T13:30:00Z']
        values = [100, 105] if daily else [105, 9999, 8888]
        result = {'meta': {'symbol': 'META', 'currency': 'USD', 'exchangeTimezoneName': 'America/New_York',
                           'regularMarketPrice': 777777},
                  'timestamp': [int(p.market.aware(t).timestamp()) for t in times],
                  'indicators': {'quote': [{'close': values}]}}
        return 200, json.dumps({'chart': {'error': None, 'result': [result]}}).encode()

    def test_later_round_has_frozen_price_not_future_day_or_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            refs = p.collect(['NASDAQ:META'], root, self.transport,
                             start='2026-10-14T00:00:00Z', end='2026-10-23T00:00:00Z')['NASDAQ:META']
            morning = p.snapshot('NASDAQ:META', '2026-10-22T09:20:00+09:00', refs, root)
            evening = p.snapshot('NASDAQ:META', '2026-10-22T17:30:00+09:00', refs, root)
            self.assertEqual('105.00', morning['latest']['value'])
            self.assertEqual('100.00', morning['baseline']['value'])
            self.assertEqual('5.00', morning['changeRate'])
            self.assertEqual('no_new_session', evening['comparisonStatus'])
            self.assertIsNone(evening['changeRate'])
            self.assertEqual('2026-10-21T20:00:00Z', evening['latest']['observedAt'])
            self.assertEqual(refs, p.collect(['NASDAQ:META'], root, lambda _: self.fail('refetched'),
                                            start=refs[0]['period1'], end=refs[0]['period2'])['NASDAQ:META'])
            with self.assertRaisesRegex(ValueError, 'cache_changed'):
                p.collect(['NASDAQ:META'], root, self.transport,
                          start='2026-10-13T00:00:00Z', end='2026-10-23T00:00:00Z')
            changed = copy.deepcopy(refs); changed[0]['period2'] += 86400
            self.assertEqual('provider_history_unverified', p.snapshot('NASDAQ:META', '2026-10-22T17:30:00+09:00', changed, root)['reason'])

    def test_completed_ai_text_is_preserved_and_price_only_enrichment_reuses_receipts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); original = root / 'original'; original.mkdir(mode=0o700)
            rows = [{'roundId': edition, 'cutoff': '2026-10-22T' + time + ':00+09:00',
                     'generatedAt': '2026-10-23T00:00:00Z', 'status': 'PASS', 'resultVersion': 'authored-original-' + edition,
                     'frozen': {'targets': [{'companyId': 'NASDAQ:META'}]}, 'draft': {'text': 'original'}}
                    for edition, time in [('morning', '09:20'), ('evening', '17:30')]]
            bundle = {'roundSeries': {'unchanged': True}, 'marketEnrichment': {
                'seriesCompanyOutlooks': {'authorizationRef': 'local:authored', 'rounds': rows},
                'seriesCompanyReading': {'unchanged': 'exact recorded short reading'}}}
            raw = p.base.canonical(bundle); p.base.write_once(original / 'bundle-v2.json', raw)
            p.base.write_once(original / 'recorded-ai.txt', b'original model response')
            args = SimpleNamespace(baseline=str(original), output=str(root / 'new'), authorization_ref='local:authored')
            report = series.run(args, self.transport)
            self.assertEqual(0, report['newPaidCalls'])
            self.assertEqual(raw, (original / 'bundle-v2.json').read_bytes())
            new = p.base.strict_load((root / 'new/bundle-v2.json').read_bytes())
            new['marketEnrichment'].pop('seriesCompanyPrices')
            self.assertEqual(bundle, new)
            self.assertEqual(b'original model response', (root / 'new/recorded-ai.txt').read_bytes())
            self.assertTrue(series.run(args, lambda _: self.fail('refetched'))['reusedCompletedRun'])
            rawfile = next((root / 'new/company-prices').glob('*.bin')); rawfile.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'completed_raw_changed'):
                series.run(args, lambda _: self.fail('refetched'))

    def test_invalid_range_and_connection_failure_are_not_empty_success(self):
        for start, end in [(None, 1792713600), (True, 1792713600), (1792022401, 1792713600),
                           (1792022400, 1792022400 + 32 * 86400)]:
            with self.assertRaises(ValueError):
                p.period(start, end)
        with tempfile.TemporaryDirectory() as d:
            def failed(_): raise TimeoutError('authored failure')
            refs = p.collect(['NASDAQ:META'], Path(d), failed, start='2026-10-14T00:00:00Z', end='2026-10-23T00:00:00Z')['NASDAQ:META']
            self.assertEqual([0, 0], [r['httpStatus'] for r in refs])
            self.assertEqual('provider_request_failed', p.snapshot('NASDAQ:META', '2026-10-22T09:20:00+09:00', refs, Path(d))['reason'])


if __name__ == '__main__': unittest.main()
