"""Cutoff capture contracts using authored provider bodies; no live AI/DB/network."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
import briefing_live_market as live
import briefing_native_intake as native
import briefing_server_runtime as runtime
from test_briefing_market_data import index_bytes, fx_bytes


def round_(day='2026-10-05', edition='evening', at=None):
    return {'id': 'brf-' + day + '-' + edition, 'date': day, 'edition': edition,
            'windowTo': day + (at or ('T17:30:00+09:00' if edition == 'evening' else 'T08:30:00+09:00'))}


class LiveMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.clock = '2026-10-05T17:10:00+09:00'; self.sent = []
    def send(self, url):
        self.sent.append(url)
        if 'FX_USDKRW' in url: return 200, fx_bytes()
        value = live.b.strict_load(index_bytes('^KS11' if '%5EKS11' in url else '^KQ11'))
        stamp = int(datetime.fromisoformat('2026-10-05T15:30:00+09:00').timestamp())
        value['chart']['result'][0]['meta']['currentTradingPeriod'] = {'regular': {'end': stamp}}
        return 200, live.b.canonical(value)
    def collect(self, r=None, send=None):
        with patch.object(live.b, 'now', return_value=self.clock):
            return live.collect(self.root, r or round_(), send or self.send)
    def test_evening_close_and_captured_bank_reference_are_frozen_once(self):
        value = self.collect(); self.assertTrue(value['capturedBeforeCutoff'])
        items = value['marketVariables']['indicators']
        self.assertEqual(['close', 'close', 'reference'], [x['valueKind'] for x in items])
        self.assertEqual(['2026-10-05'] * 3, [x['observedDate'] for x in items])
        self.assertEqual(['2026-10-02'] * 3, [x['baseline']['date'] for x in items])
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(value, live.load(self.root, round_()))
        self.assertEqual(value, self.collect(send=Mock(side_effect=AssertionError('no resend'))))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(3, len(self.sent))
    def test_morning_uses_previous_close_instead_of_a_running_daily_candle(self):
        self.clock = '2026-10-05T08:10:00+09:00'; value = self.collect(round_(edition='morning'))
        self.assertEqual(['2026-10-02'] * 2, [x['observedDate'] for x in value['marketVariables']['indicators'][:2]])
        self.assertEqual('2026-10-05', value['marketVariables']['indicators'][2]['observedDate'])
    def test_provider_session_delay_cannot_be_reported_as_a_close(self):
        self.clock = '2026-10-05T17:10:00+09:00'
        def send(url):
            status, raw = self.send(url)
            if 'FX_USDKRW' not in url:
                value = live.b.strict_load(raw)
                value['chart']['result'][0]['meta']['currentTradingPeriod']['regular']['end'] = int(datetime.fromisoformat('2026-10-05T18:30:00+09:00').timestamp())
                raw = live.b.canonical(value)
            return status, raw
        value = self.collect(send=send)
        self.assertEqual('2026-10-02', value['marketVariables']['indicators'][0]['observedDate'])
    def test_weekend_carries_actual_previous_records_without_zeroing_change(self):
        self.clock = '2026-10-04T17:10:00+09:00'; value = self.collect(round_('2026-10-04'))
        for item in value['marketVariables']['indicators']:
            self.assertEqual('2026-10-02', item['observedDate']); self.assertEqual('delayed', item['status'])
            self.assertNotEqual(0, item['change']); self.assertEqual('2026-10-01', item['baseline']['date'])
    def test_partial_failure_keeps_other_indicators_and_does_not_zero_fill(self):
        value = self.collect(send=lambda url: (403, b'denied') if '%5EKS11' in url else self.send(url))
        items = value['marketVariables']['indicators']
        self.assertIsNone(items[0]['value']); self.assertIsNone(items[0]['changeRate'])
        self.assertEqual('failed', items[0]['status']); self.assertIsNotNone(items[1]['value'])
    def test_late_fetch_is_retained_but_cannot_become_a_publication_input(self):
        self.clock = '2026-10-05T17:31:00+09:00'; value = self.collect()
        self.assertFalse(value['capturedBeforeCutoff']); self.assertIsNone(live.publication(self.root, round_()))
        self.assertEqual(value, live.load(self.root, round_(), allow_late=True)); self.assertEqual(3, len(self.sent))
    def test_modified_snapshot_or_raw_receipt_fails_closed_without_network(self):
        value = self.collect(); path = live.root_for(self.root, round_()['id']) / 'capture.json'
        value['marketVariables']['indicators'][0]['value'] = 999
        path.write_bytes(live.b.canonical(value))
        self.assertIsNone(live.publication(self.root, round_())); self.assertEqual(3, len(self.sent))
    def test_missing_cache_must_not_refetch_during_publication(self):
        self.collect(); root = live.root_for(self.root, round_()['id'])
        (root / 'market/providers/kospi.json').unlink()
        self.assertIsNone(live.publication(self.root, round_())); self.assertEqual(3, len(self.sent))
    def test_wrong_cutoff_and_path_traversal_cannot_reuse_a_capture(self):
        self.collect(); other = round_(at='T17:31:00+09:00')
        self.assertIsNone(live.publication(self.root, other))
        with self.assertRaises(live.b.ReplayError): live.root_for(self.root, '../../other')
    def test_database_utc_serialization_keeps_the_same_cutoff_binding(self):
        value = self.collect(); r = round_(); r['windowTo'] = '2026-10-05T08:30:00+00:00'
        self.assertEqual(value, live.load(self.root, r))
    def test_market_failure_does_not_withhold_news(self):
        observer = Mock()
        with patch.object(live, 'collect', side_effect=live.b.ReplayError('missing')):
            native.capture_market({'work': str(self.root)}, round_(), observer)
        self.assertEqual(('market', 'failed'), observer.call_args.args[:2])
    def test_publication_uses_saved_indicators_without_new_calls_or_prose_rewrite(self):
        self.collect(); r = round_(); r.update(scheduledAt=r['windowTo'], windowFrom='2026-10-05T08:30:00+09:00')
        prepared = {'round': r, 'graphVersion': 'synthetic', 'inputSha256': 'a'*64, 'coverage': {}, 'sourceBindings': [], 'reviewRevision': 0, 'ruleRevision': 0}
        frozen = {'roundId': r['id'], 'date': r['date'], 'edition': r['edition'], 'cutoff': r['windowTo'], 'candidates': [], 'scope': 'synthetic', 'inputSha256': 'b'*64}
        payload, snapshot, _ = runtime.make_publication(prepared, frozen, {'selected': []}, [], [], {}, {}, self.clock, cfg={'work': str(self.root)})
        self.assertEqual(3, len(payload['marketVariables']['indicators']))
        self.assertIn('marketCapture', snapshot); self.assertEqual(3, len(self.sent))


if __name__ == '__main__': unittest.main()
