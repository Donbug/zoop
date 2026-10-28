import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
import briefing_round_flow as flow
import briefing_series_company as company
import test_briefing_series_prices as price_fixtures

base = flow.base


def fixture(root):
    original = root / 'original'
    base.private_dir(original)
    rows = [{'roundId': edition, 'cutoff': '2026-10-22T' + time + ':00+09:00',
             'generatedAt': '2026-10-23T00:00:00Z', 'status': 'PASS', 'resultVersion': 'original-' + edition,
             'frozen': {'targets': [{'companyId': 'NASDAQ:META'}]}, 'draft': {'text': 'original'}}
            for edition, time in [('morning', '09:20'), ('evening', '17:30')]]
    bundle = {'roundSeries': {'unchanged': True}, 'marketEnrichment': {
        'seriesCompanyOutlooks': {'authorizationRef': 'local:authored', 'rounds': rows}, 'rounds': []}}
    base.write_once(original / 'bundle-v2.json', base.canonical(bundle))
    base.write_once(original / 'ai-response.json', b'{"text":"original recorded AI"}')
    return original


class RoundFlowTest(unittest.TestCase):
    def test_completed_step_not_repeated_failed_step_retried_with_history(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            calls = []
            ledger = flow.Ledger(root)
            ledger.step('ai', lambda: calls.append('ai') or {'sha': 'original'})
            def fail():
                raise TimeoutError('unavailable')
            with self.assertRaises(TimeoutError):
                ledger.step('prices', fail)
            old = (root / 'prices/0001.result.json').read_bytes()
            resumed = flow.Ledger(root)
            resumed.step('ai', lambda: self.fail('AI regenerated'), lambda r: r == {'sha': 'original'})
            resumed.step('prices', lambda: calls.append('prices') or {'sha': 'restored'})
            self.assertEqual(['ai', 'prices'], calls)
            self.assertEqual(['ai'], resumed.reused)
            self.assertEqual(['prices'], resumed.executed)
            self.assertEqual(old, (root / 'prices/0001.result.json').read_bytes())
            self.assertEqual('FAILED', json.loads(old)['status'])
            self.assertEqual('COMPLETE', json.loads((root / 'prices/0002.result.json').read_bytes())['status'])

    def test_invalid_completed_archive_is_not_silently_regenerated(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = flow.Ledger(Path(d))
            ledger.step('ai', lambda: {'sha': 'original'})
            def changed(_): raise base.ReplayError('archive_changed')
            with self.assertRaisesRegex(base.ReplayError, 'archive_changed'):
                ledger.step('ai', lambda: self.fail('regenerated'), changed)
            self.assertEqual(1, len(list(Path(d).glob('ai/*.result.json'))))

    def test_failed_interval_only_is_refetched_and_originals_are_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); original = fixture(root); work = root / 'work'
            response = price_fixtures.SeriesPricesTest().transport
            first_urls = []
            def first(url):
                first_urls.append(url)
                return (503, b'not available') if 'interval=1d' in url else response(url)
            with self.assertRaisesRegex(base.ReplayError, 'request_failed'):
                flow.price_step(original, work, 'local:authored', transport=first)
            old = {p.relative_to(work): p.read_bytes() for p in work.rglob('*') if p.is_file()}
            second_urls = []
            def second(url):
                self.assertIn('interval=1d', url)
                second_urls.append(url)
                return response(url)
            result = flow.price_step(original, work, 'local:authored', transport=second)
            self.assertEqual(2, len(first_urls)); self.assertEqual(1, len(second_urls))
            for path, raw in old.items(): self.assertEqual(raw, (work / path).read_bytes())
            self.assertTrue(flow.validate_prices(result, original, 'local:authored'))
            again = flow.price_step(original, work, 'local:authored', transport=lambda _: self.fail('refetched'))
            self.assertEqual(result, again)
            self.assertEqual(b'{"text":"original recorded AI"}', (original / 'ai-response.json').read_bytes())
            raw = next(Path(result['bundle']).parent.glob('company-prices/*.bin'))
            raw.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'completed_raw_changed'):
                flow.validate_prices(result, original, 'local:authored')

    def test_interrupted_price_stage_reuses_success_receipt_without_unlocking_old_archive(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); original = fixture(root); work = root / 'work'
            response = price_fixtures.SeriesPricesTest().transport
            def interrupted(url):
                if 'interval=1d' in url: raise KeyboardInterrupt()
                return response(url)
            with self.assertRaises(KeyboardInterrupt):
                flow.price_step(original, work, 'local:authored', transport=interrupted)
            urls = []
            def recovered(url):
                urls.append(url); self.assertIn('interval=1d', url); return response(url)
            result = flow.price_step(original, work, 'local:authored', transport=recovered)
            self.assertEqual(1, len(urls))
            self.assertTrue(flow.validate_prices(result, original, 'local:authored'))

    def test_cli_completed_ai_needs_no_key_and_collects_prices_automatically(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = fixture(root); output = root / 'generated'
            base.private_dir(output)
            raw = base.regular(source / 'bundle-v2.json')
            sources = root / 'sources.jsonl'; sources.write_bytes(b'{}\n')
            base.write_once(output / 'bundle-v2.json', raw)
            proof = {'status': 'COMPLETE', 'identity': {'baselineSha256': base.digest(raw),
                     'authorizationRef': 'local:authored', 'maximumCalls': 80, 'sourceSha256': base.digest(sources.read_bytes()), 'comparisonContract': None}, 'bundleSha256': base.digest(raw)}
            base.write_once(output / 'completed.json', base.canonical(proof))
            args = company.parser().parse_args(['--baseline', str(source), '--output', str(output),
                '--sources', str(sources), '--authorization-ref', 'local:authored', '--execute'])
            with patch.object(flow.prices.prices.market, 'transport', price_fixtures.SeriesPricesTest().transport):
                result = company.run(args)
            self.assertEqual('COMPLETE', result['priceStage'])
            self.assertEqual(0, result['newPaidCalls'])
            with patch.object(flow.prices.prices.market, 'transport', side_effect=AssertionError('refetched')):
                self.assertEqual(result['finalBundle'], company.run(args)['finalBundle'])
            self.assertEqual(raw, base.regular(output / 'bundle-v2.json'))

    def test_offline_mode_does_not_open_inputs_or_call_providers(self):
        args = SimpleNamespace(baseline='/missing', output='/missing-output', serve=True, execute=False)
        self.assertEqual('OFFLINE', flow.run(args, lambda _: self.fail('provider call'))['status'])


if __name__ == '__main__': unittest.main()
