import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import briefing_price_context as stage


class PriceContextCollectionTest(unittest.TestCase):
    def setup_run(self, folder):
        root = Path(folder); source = root / 'source'; stage.base.private_dir(source)
        b = {'presentationEnrichment': {'editionReviewLayer': {'rounds': [
            {'resultVersion': 'edition-1', 'frozen': {'roundId': 'r', 'cutoff': '2026-10-22T00:20:00Z',
                'targets': [{'companyId': 'NASDAQ:AAPL'}]}}]}}}
        stage.base.write_once(source / 'bundle-v2.json', stage.base.canonical(b))
        return SimpleNamespace(baseline=str(source), output=str(root / 'result'), api_base='http://127.0.0.1:18150',
                               authorization_ref='test-only', request_note='synthetic-test', reuse=None)

    def test_completed_responses_are_reused_without_any_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.setup_run(folder); calls = []
            def fetch(url):
                calls.append(url)
                return 200, stage.base.canonical({'companyId': 'NASDAQ:AAPL', 'status': 'unavailable'})
            first = stage.run(args, fetch)
            second = stage.run(args, lambda _: self.fail('unexpected source request'))
            self.assertEqual(2, len(calls)); self.assertEqual(0, second['newRequests'])
            self.assertEqual(first['bundleSha256'], second['bundleSha256'])

    def test_saved_receipts_from_another_output_resume_with_zero_new_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.setup_run(folder)
            stage.run(args, lambda _: (200, stage.base.canonical({'companyId': 'NASDAQ:AAPL', 'status': 'unavailable'})))
            args.reuse = args.output; args.output = str(Path(folder) / 'second-result')
            first = stage.run(args, lambda _: self.fail('unexpected source request'))
            resumed = stage.run(args, lambda _: self.fail('unexpected resumed request'))
            self.assertEqual(2, first['savedResponsesReused'])
            self.assertEqual(0, resumed['newRequests'])
            self.assertEqual(2, resumed['completedRequestsReused'])

    def test_outlook_composition_is_opt_in_and_preserves_the_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.setup_run(folder); before = Path(args.baseline, 'bundle-v2.json').read_bytes()
            args.integrate_outlook = True
            stage.run(args, lambda _: (200, stage.base.canonical({'companyId': 'NASDAQ:AAPL', 'status': 'unavailable'})))
            bundle = stage.base.strict_load(Path(args.output, 'bundle-v2.json').read_bytes())
            self.assertEqual('zoop-company-price-outlook-v1', bundle['presentationEnrichment']['priceContextLayer']['outlookIntegrationVersion'])
            self.assertEqual(before, Path(args.baseline, 'bundle-v2.json').read_bytes())
            self.assertEqual(0, stage.run(args, lambda _: self.fail('unexpected request'))['newRequests'])

    def test_wrong_company_and_remote_origins_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.setup_run(folder)
            with self.assertRaises(stage.base.ReplayError):
                stage.run(args, lambda _: (200, stage.base.canonical({'companyId': 'NYSE:OTHER'})))
            args.api_base = 'http://remote.example'
            with self.assertRaises(stage.base.ReplayError): stage.run(args)

    def test_cache_changes_and_baseline_replacement_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            args = self.setup_run(folder)
            stage.run(args, lambda _: (200, stage.base.canonical({'companyId': 'NASDAQ:AAPL', 'status': 'unavailable'})))
            archive = next((Path(args.output) / 'price-context-responses').glob('*.bin'))
            archive.write_bytes(b'{}')
            with self.assertRaises(stage.base.ReplayError): stage.run(args, lambda _: self.fail('unexpected request'))


if __name__ == '__main__': unittest.main()
