"""Regression cases from PR303. All provider responses are authored, with no network."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
import briefing_semantic_support as semantic
import briefing_series_company as company
import briefing_round_flow as flow
import briefing_team_demo as demo
import test_briefing_round_flow as fixtures
import test_briefing_series_prices as price_fixtures

base = company.base


class Review303Test(unittest.TestCase):
    def test_source_digest_must_match_baseline_before_any_model_client_is_created(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=fixtures.fixture(root);sources=root/'sources.jsonl';sources.write_bytes(b'{}\n')
            bundle=json.loads((source/'bundle-v2.json').read_bytes());bundle['sourceFileSha256']='b'*64
            (source/'bundle-v2.json').write_bytes(base.canonical(bundle))
            args=company.parser().parse_args(['--baseline',str(source),'--output',str(root/'output'),
                '--sources',str(sources),'--authorization-ref','local:authored','--execute'])
            with patch.object(base,'authenticated_transport',side_effect=AssertionError('client created')):
                with self.assertRaisesRegex(base.ReplayError,'source_baseline_mismatch'):company.generate(args)
    def test_legacy_company_or_role_cannot_borrow_grounding(self):
        raw = {'participants': [{'company_id':'TEST:A','name':'기업A','role':'buyer'}]}
        mention = {'companies':[{'companyId':'TEST:A','name':'기업A','role':'buyer'}]}
        self.assertTrue(semantic.participants_bound(mention, raw))
        for key, value in [('companyId','TEST:B'), ('role','seller'), ('name','기업B')]:
            changed = copy.deepcopy(mention); changed['companies'][0][key] = value
            self.assertFalse(semantic.participants_bound(changed, raw))

    def test_completed_company_reuse_binds_source_bytes_and_comparison_policy_without_key(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = fixtures.fixture(root); output = root/'completed'
            base.private_dir(output)
            sources = root/'sources.jsonl'; sources.write_bytes(b'{"documentId":"one"}\n')
            raw = base.regular(source/'bundle-v2.json')
            args = company.parser().parse_args(['--baseline',str(source),'--output',str(output),
                '--sources',str(sources),'--authorization-ref','local:authored','--execute','--without-prices'])
            proof = {'identity':{'baselineSha256':base.digest(raw),'sourceSha256':base.digest(sources.read_bytes()),
                'comparisonContract':None,'authorizationRef':'local:authored','maximumCalls':80},'bundleSha256':base.digest(raw)}
            base.write_once(output/'bundle-v2.json',raw); base.write_once(output/'completed.json',base.canonical(proof))
            with patch.object(base,'authenticated_transport',side_effect=AssertionError('paid request')):
                self.assertEqual(0, company.generate(args)['newPaidCalls'])
                args.edition_bound_comparison = True
                with self.assertRaisesRegex(base.ReplayError,'reuse_mismatch'): company.generate(args)
                args.edition_bound_comparison = False
                sources.write_bytes(b'{"documentId":"changed"}\n')
                with self.assertRaisesRegex(base.ReplayError,'reuse_mismatch'): company.generate(args)

    def test_all_withheld_completes_price_stage_without_provider_or_text_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = fixtures.fixture(root)
            bundle = json.loads((source/'bundle-v2.json').read_bytes())
            for row in bundle['marketEnrichment']['seriesCompanyOutlooks']['rounds']: row['status']='WITHHELD'
            (source/'bundle-v2.json').write_bytes(base.canonical(bundle))
            result = flow.price_step(source, root/'flow', 'local:authored',transport=lambda _:self.fail('price request'))
            saved = json.loads(Path(result['bundle']).read_bytes())
            self.assertEqual([],saved['marketEnrichment']['seriesCompanyPrices']['rounds'])
            saved['marketEnrichment'].pop('seriesCompanyPrices'); self.assertEqual(bundle,saved)
            self.assertTrue(flow.validate_prices(result,source,'local:authored'))

    def test_actual_completed_price_identity_cannot_be_rehashed_into_an_old_proof(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=fixtures.fixture(root); output=root/'prices'
            args=SimpleNamespace(baseline=str(source),output=str(output),authorization_ref='local:authored')
            flow.prices.run(args,price_fixtures.SeriesPricesTest().transport)
            bundle=json.loads((output/'bundle-v2.json').read_bytes())
            bundle['marketEnrichment']['seriesCompanyPrices']['period1']-=86400
            raw=base.canonical(bundle); (output/'bundle-v2.json').write_bytes(raw)
            proof=json.loads((output/'prices-proof.json').read_bytes()); proof['bundleSha256']=base.digest(raw)
            (output/'prices-proof.json').write_bytes(base.canonical(proof))
            with self.assertRaisesRegex(ValueError,'completed_identity_changed'): flow.prices.run(args,lambda _:self.fail('refetch'))

    def test_pid_reuse_is_rejected_even_when_the_foreign_service_is_healthy(self):
        record={'pid':os.getpid(),'url':'http://127.0.0.1:1/health','processIdentity':'old-process','responseIdentity':'old'}
        with patch.object(flow,'get',return_value={'status':'available'}) as network:
            with self.assertRaisesRegex(flow.base.ReplayError,'ownership_changed'): flow.owned_process(record,record['url'])
            network.assert_not_called()

    def test_demo_forces_frontend_to_its_local_proxy(self):
        env=demo.frontend_environment({'VITE_API_BASE_URL':'https://foreign.invalid'},'http://127.0.0.1:8000')
        self.assertEqual('',env['VITE_API_BASE_URL'])
        self.assertEqual('http://127.0.0.1:8000',env['ZOOP_DEV_API_TARGET'])

    def test_create_failure_cleanup_checks_exact_run_owner_and_preserves_foreign_container(self):
        for actual, expected in [('this-run',True),('someone-else',False)]:
            commands=[]
            def docker(*args):
                commands.append(args)
                return actual if args[0]=='inspect' else ''
            demo.cleanup_owned_container(docker,'exact-container','this-run')
            self.assertEqual(expected,any(c[0]=='rm' for c in commands))
            self.assertTrue(all(c[-1]=='exact-container' for c in commands))


if __name__=='__main__': unittest.main()
