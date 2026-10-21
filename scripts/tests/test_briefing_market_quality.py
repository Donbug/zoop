"""v2.3 source anchors, semantic flags and unsupported-condition prevention (offline)."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('quality_fixtures', Path(__file__).with_name('test_briefing_market_context.py'))
f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)
c = f.context

class MarketQualityTest(unittest.TestCase):
    def setUp(self):
        self.old = c.PROMPTS
        c.PROMPTS = c.PROMPTS.with_name(c.QUALITY_VERSION)
    def tearDown(self):
        c.PROMPTS = self.old
    def data(self):
        data, _, _ = f.input_data()
        data['context']['summaryPromptVersion'] = c.QUALITY_VERSION
        data['contextSha256'] = c.base.digest(c.base.canonical(data['context']))
        return data
    def test_fact_cannot_combine_two_documents_or_two_indicators_or_prior_summary(self):
        evidence={'a': {'documentId':'one'}, 'b': {'documentId':'two'}, 'a2': {'documentId':'one'}}
        for claim in [f.claim('독립 사실 둘', ['a','b']), f.claim('지표 둘', indicators=['kospi','kosdaq']),
                      f.claim('기사와 지표', ['a'], ['kospi']), f.claim('이전 요약을 원문 대체', previousPublicationIds=['old']),
                      f.claim('문서 없는 근거', ['missing'])]:
            with self.subTest(claim=claim['text']), self.assertRaisesRegex(c.ContextError, 'fact_anchor'):
                c.quality_claims([claim], {**evidence, 'missing':{}})
        c.quality_claims([f.claim('한 문서 여러 인용', ['a','a2']), f.claim('한 지표', indicators=['kospi'])], evidence)
    def test_unsupported_and_circular_conditions_rejected_but_basic_outlook_allowed(self):
        for condition in ['지수가 기준값보다 높게 마감하면', '기대가 확산되면']:
            with self.subTest(condition=condition), self.assertRaisesRegex(c.ContextError, 'observations_missing'):
                c.quality_claims([f.claim('상승을 전망', kind='forecast', conditions=[condition])], {})
        c.quality_claims([f.claim('엇갈린 근거로 기본 방향은 불확실', kind='forecast')], {})
    def execute(self, flag=None, remove_flag=False):
        data=self.data()
        def change(stage, answer):
            if stage=='market_summary_generation':
                for claim in answer['claims']:
                    if claim['kind']=='forecast': claim.update(conditions=[],text='엇갈린 근거로 기본 방향은 불확실합니다.',direction='uncertain')
            else:
                for check in answer['checks'].values(): check.update({k: True for k in c.QUALITY_FLAGS})
                if flag:
                    first=next(iter(answer['checks'].values()))
                    if remove_flag: first.pop(flag)
                    else: first[flag]=False
        with tempfile.TemporaryDirectory() as d:
            transport=f.ContextTransport(change)
            client=c.legacy.MarketSummaryClient(Path(d),transport,8,prompt_root=c.PROMPTS)
            return c.generate_market_summary(client,data,0), transport
    def test_nested_history_is_rejected_before_new_paid_execution(self):
        from types import SimpleNamespace
        spec=importlib.util.spec_from_file_location('quality_runner',Path(__file__).parents[1]/'briefing_market_outlook_run.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as d:
            Path(d,'bundle-v2.json').write_bytes(c.base.canonical({'presentationEnrichment':{
                'schemaVersion':'zoop-briefing-presentation-enrichment-v1','outlookHistory':{'bundleSha256':'old'}}}))
            with self.assertRaisesRegex(runner.context.ContextError,'nested_history_not_supported'):
                runner.prepare(SimpleNamespace(baseline=d))
    def test_complete_quality_verification_passes(self):
        result, transport=self.execute()
        self.assertEqual('PASS',result['verification']['status']); self.assertEqual(2,len(transport.requests))
    def test_each_semantic_failure_withholds_without_relabeling_old_checks(self):
        for flag in c.QUALITY_FLAGS:
            with self.subTest(flag=flag):
                result,_=self.execute(flag)
                self.assertEqual('WITHHELD',result['verification']['status']); self.assertIsNone(result['summary'])
    def test_missing_quality_flag_is_not_a_pass(self):
        with self.assertRaises(Exception): self.execute('qualifiersPreserved',True)
    def test_invalid_generation_retains_receipt_without_stale_verified_claims(self):
        def change(stage,answer):
            if stage=='market_summary_generation': answer['claims'][0]['indicatorIds']=['kospi']
        with tempfile.TemporaryDirectory() as d:
            transport=f.ContextTransport(change)
            client=c.legacy.MarketSummaryClient(Path(d),transport,8,prompt_root=c.PROMPTS)
            result=c.generate_market_summary(client,self.data(),0)
        self.assertEqual('WITHHELD',result['verification']['status']); self.assertEqual([],result['claims'])
        self.assertIsNone(result['verificationRequestDigest']); self.assertEqual(1,len(transport.requests))

    def test_semantic_rejection_routes_adversarial_wording_to_withheld(self):
        # Authored verifier decisions exercise the gate; they do not measure model detection accuracy.
        cases = [
            ('실적 기대가 지속되는 가운데 지수 상승을 전망합니다.', 'observableConditionsOnly'),
            ('기자가 인용한 애널리스트의 수요 전망을 회사가 확정 발표했습니다.', 'evidenceClauseCoverage'),
            ('합성 원문의 약20억원 예상과 달리 20억원 확정으로 썼습니다.', 'qualifiersPreserved'),
        ]
        for wording, flag in cases:
            with self.subTest(flag=flag):
                def change(stage, answer):
                    if stage == 'market_summary_generation': answer['claims'][0]['text'] = wording
                    else:
                        for check in answer['checks'].values(): check.update({k:True for k in c.QUALITY_FLAGS})
                        check=next(iter(answer['checks'].values()))
                        check.update(verdict='UNSUPPORTED',reason='Authored rejection: '+flag);check[flag]=False
                with tempfile.TemporaryDirectory() as d:
                    transport=f.ContextTransport(change)
                    client=c.legacy.MarketSummaryClient(Path(d),transport,8,prompt_root=c.PROMPTS)
                    result=c.generate_market_summary(client,self.data(),0)
                self.assertEqual('WITHHELD',result['verification']['status']);self.assertIsNone(result['summary'])
                self.assertEqual(2,len(result['claims'])) # audit retains both; no silent one-claim publication
                self.assertEqual(2,len(result['usage']))

    def test_repair_with_invalid_anchor_clears_final_draft_but_keeps_attempt_history(self):
        generations=0
        def change(stage,answer):
            nonlocal generations
            if stage=='market_summary_generation':
                generations+=1
                if generations==2: answer['claims'][0]['indicatorIds']=['kospi']
            else:
                for check in answer['checks'].values(): check.update({k:True for k in c.QUALITY_FLAGS})
                check=next(iter(answer['checks'].values()));check['atomicClaim']=False
                check.update(verdict='UNSUPPORTED',reason='Authored first-attempt semantic failure')
        with tempfile.TemporaryDirectory() as d:
            transport=f.ContextTransport(change)
            client=c.legacy.MarketSummaryClient(Path(d),transport,8,prompt_root=c.PROMPTS)
            result=c.generate_market_summary(client,self.data(),1)
        self.assertEqual('WITHHELD',result['verification']['status']);self.assertEqual([],result['claims'])
        self.assertIsNone(result['verificationRequestDigest']);self.assertIsNone(result['summary'])
        self.assertEqual(2,len(result['attempts']));self.assertEqual(3,len(result['usage']))
        self.assertIsNotNone(result['attempts'][0]['verificationRequestDigest'])
        self.assertTrue(result['attempts'][0]['verification']['checks'])
        self.assertNotIn('verificationRequestDigest',result['attempts'][1])

    def test_rejected_generation_can_be_repaired_without_rewriting_the_first_attempt(self):
        generations=0
        def change(stage,answer):
            nonlocal generations
            if stage=='market_summary_generation':
                generations+=1
                if generations==1: answer['claims'][0]['indicatorIds']=['kospi']
            else:
                for check in answer['checks'].values(): check.update({k:True for k in c.QUALITY_FLAGS})
        with tempfile.TemporaryDirectory() as d:
            transport=f.ContextTransport(change)
            client=c.legacy.MarketSummaryClient(Path(d),transport,8,prompt_root=c.PROMPTS)
            result=c.generate_market_summary(client,self.data(),1)
        self.assertEqual('PASS',result['verification']['status']);self.assertEqual(2,len(result['attempts']))
        self.assertEqual('WITHHELD',result['attempts'][0]['verification']['status'])
        self.assertIn('fact_anchor',result['attempts'][0]['verification']['reason'])
        self.assertEqual(3,len(result['usage']))

if __name__=='__main__': unittest.main()
