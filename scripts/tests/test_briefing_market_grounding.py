"""Authored transport exercises provenance and failure paths, not real-model accuracy."""
import copy
import re
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('ground_fixture', Path(__file__).with_name('test_briefing_market_context.py'))
f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)
c = f.context


class GroundTransport:
    def __init__(self, reject_first=False, flag='scopePreserved', reject_fact=False):
        self.requests, self.verifications, self.reject_first, self.flag = [], 0, reject_first, flag
        self.reject_fact = reject_fact

    def __call__(self, raw):
        self.requests.append(raw); request = c.base.strict_load(raw); data = c.base.strict_load(request['input'])
        phase = data['phase']
        if 'modelView' in data:
            view=data['modelView'];data={**data,'marketContext':{**view['round'],**{k:view[k] for k in ['forecastTargets','previousPublication','forecastEvaluations']}},'claimRequirements':view['claimRequirements'],'allowedPreviousForecastIds':[f['forecastId'] for f in view['previousPublication'].get('summary',{}).get('forecasts',[])],'allowedPreviousPublicationIds':[view['previousPublication']['roundId']] if view['previousPublication']['status']=='available' else [],'allowedEvaluationIds':[e['evaluationId']for e in view['forecastEvaluations']]}
        if phase == 'facts':
            doc = next(d for d in data['marketContext']['documents'] if '계약' in d['sources'][0]['quote']); source = doc['sources'][0]
            quote = re.search(r'[^.!?。]*계약[^.!?。]*[.!?。]?', source['quote']).group().strip()
            result = {'facts': [{'text':quote, 'sourceQuote':quote, 'subject':next((name for name in doc['companyNames'] if name in quote), '합성 기업'),
                       'metric':'계약', 'period':'', 'qualifiers':[], 'evidenceId':source['evidenceId']}]}
            if data['context'].get('summaryPromptVersion') == c.grounding.VERSION:
                result={'facts':[{'text':quote,'sourceIds':[source['evidenceId']],'factType':'plan'}]}
        elif phase == 'analysis':
            refs = c.grounding.sources(data['factPlan']['facts'][0])
            def claim(text, kind='interpretation', **extra):
                return f.claim(text, refs, kind=kind, basisFactIds=['fact:0'], **extra)
            result = {'claims':[claim('합성 기업의 계획은 미확정 정보이며 지수 방향의 근거는 제한적입니다.' + (' 보완했습니다.' if data['repairAttempt'] else ''))], 'requiredClaims':{}}
            for kind in data['claimRequirements']['requiredKinds']:
                extra = {}
                if kind == 'forecast':
                    extra = dict(targetId=data['marketContext']['forecastTargets'][0]['targetId'], direction='uncertain', counterFactors=['확정되지 않은 합성 계획'])
                if kind == 'forecast_update':
                    extra = dict(previousForecastIds=data['allowedPreviousForecastIds'][:1], updateAction='maintain')
                if kind == 'result_comparison':
                    extra = dict(previousForecastIds=data['allowedPreviousForecastIds'], evaluationIds=data['allowedEvaluationIds'], previousPublicationIds=data['allowedPreviousPublicationIds'])
                result['requiredClaims'][kind] = claim('직접 작성한 합성 ' + kind + ' 문장입니다.', kind, **extra)
        else:
            self.verifications += 1
            flags = ['noUnsupportedNumbers','noUnsupportedCausality','temporalAppropriate','noInvestmentAdvice','comparisonAppropriate','forecastAppropriate',*c.ROLE_FLAGS,*c.grounding.FLAGS]
            result = {'checks': {claim['claimId']: {'targetId':claim['claimId'], 'verdict':'SUPPORTED', 'reason':'Authored checks', **{flag:True for flag in flags}} for claim in data['draft']['claims']}}
            if self.reject_first and self.verifications == 1:
                check = list(result['checks'].values())[0 if self.reject_fact else 1];check.update(verdict='UNSUPPORTED', reason='Authored unsupported scope');check[self.flag] = False
        return f.fixtures.response(result, raw)


class GroundingTest(unittest.TestCase):
    def data(self):
        data, _, _ = f.input_data(records=[f.prior()]);data['marketContext']['forecastTargets']=[f.target()]
        data['context'].update(summaryPromptVersion=c.grounding.VERSION, marketContextSha256=c.base.digest(c.base.canonical(data['marketContext'])))
        data['contextSha256']=c.base.digest(c.base.canonical(data['context']));return data

    def run_draft(self, transport, repairs=0):
        with tempfile.TemporaryDirectory() as directory:
            client=c.legacy.MarketSummaryClient(Path(directory),transport,8,prompt_root=c.PROMPTS.with_name(c.grounding.VERSION))
            old=c.PROMPTS;c.PROMPTS=c.PROMPTS.with_name(c.grounding.VERSION)
            try:return c.generate_market_summary(client,self.data(),repairs)
            finally:c.PROMPTS=old

    def test_fact_plan_is_paid_once_and_analysis_cannot_rewrite_its_text(self):
        transport=GroundTransport();result=self.run_draft(transport)
        self.assertEqual('PASS',result['verification']['status']);self.assertEqual(3,len(result['usage']))
        self.assertEqual(['facts','analysis','verify'],[c.base.strict_load(c.base.strict_load(r)['input'])['phase'] for r in transport.requests])
        self.assertEqual(result['factPlan']['facts'][0]['text'],result['claims'][0]['text'])
        self.assertEqual(result['factPlanRequestDigest'],result['factPlanAttempts'][0]['requestDigest'])

    def test_repair_reuses_same_facts_and_retains_required_outlook_and_comparison(self):
        transport=GroundTransport(reject_first=True);result=self.run_draft(transport,1)
        self.assertEqual('PASS',result['verification']['status']);self.assertEqual(5,len(result['usage']))
        inputs=[c.base.strict_load(c.base.strict_load(r)['input']) for r in transport.requests]
        analyses=[r for r in inputs if r['phase']=='analysis'];self.assertEqual(analyses[0]['factPlan'],analyses[1]['factPlan'])
        self.assertEqual(['WITHHELD','PASS'],[a['verification']['status'] for a in result['attempts']])
        self.assertTrue({'forecast','result_comparison'} <= {x['kind'] for x in result['claims']})

    def test_fact_semantic_failure_routes_repair_back_to_fact_generation(self):
        transport=GroundTransport(reject_first=True,reject_fact=True);result=self.run_draft(transport,1)
        self.assertEqual('PASS',result['verification']['status']);self.assertEqual(6,len(result['usage']))
        phases=[c.base.strict_load(c.base.strict_load(r)['input'])['phase'] for r in transport.requests]
        self.assertEqual(['facts','analysis','verify','facts','analysis','verify'],phases)
        self.assertEqual(2,len(result['factPlanAttempts']))

    def test_any_new_verifier_flag_failure_withholds_the_whole_market_summary(self):
        for flag in c.grounding.FLAGS:
            with self.subTest(flag=flag):
                result=self.run_draft(GroundTransport(True,flag));self.assertEqual('WITHHELD',result['verification']['status']);self.assertIsNone(result['text'])

    def test_fact_guard_rejects_two_metrics_quote_invention_and_missing_qualifier(self):
        for field,value,reason in [('text','시험 매출 1원과 영업이익 2원','multiple_metrics'),('sourceQuote','실제 인용에 없는 열두 글자 이상의 내용','exact_quote'),('qualifiers',['잠정'],'qualifier')]:
            plan={'facts':[{'text':'시험 기업의 매출은 약 1원이다.', 'sourceQuote':'시험 기업의 매출은 약 1원이다.', 'subject':'시험 기업','metric':'매출','period':'','qualifiers':['약'],'evidenceId':'e'}]}
            evidence={'e':{'quote':plan['facts'][0]['sourceQuote']}};plan['facts'][0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(c.ContextError,reason):c.grounding.validate_facts(plan,evidence,c.require)

    def test_foreign_fact_reference_and_source_rebinding_and_japanese_are_rejected(self):
        plan={'facts':[{'text':'고정 사실','evidenceId':'e'}]}
        for extra,reason in [({'basisFactIds':['fact:1']},'foreign_fact'),({'evidenceIds':['other']},'fact_evidence'),({'text':'뒷付け'},'foreign_language')]:
            claim=f.claim('합성 분석',['e'],kind='interpretation',basisFactIds=['fact:0']);claim.update(extra)
            with self.subTest(reason=reason),self.assertRaisesRegex(c.ContextError,reason):c.grounding.project({'claims':[claim]},plan,c.require)

    def test_translated_qualifiers_keep_both_source_spelling_and_korean_rendering(self):
        plan={'facts':[{'text':'시험 기업의 잠정 매출은 약 1원이다.', 'sourceQuote':'시험 기업 preliminary revenue approximately 1 won',
            'subject':'시험 기업','metric':'revenue','period':'','qualifiers':[{'sourceText':'preliminary','renderedText':'잠정'},{'sourceText':'approximately','renderedText':'약'}],'evidenceId':'e'}]}
        evidence={'e':{'quote':plan['facts'][0]['sourceQuote']}}
        c.grounding.validate_facts(plan,evidence,c.require,True)
        plan['facts'][0]['text']='시험 기업의 매출은 1원이다.'
        with self.assertRaisesRegex(c.ContextError,'qualifier'):c.grounding.validate_facts(plan,evidence,c.require,True)

    def test_new_analysis_schema_and_projection_reject_duplicate_required_roles(self):
        old=c.PROMPTS;c.PROMPTS=c.PROMPTS.with_name(c.grounding.VERSION)
        try:
            values=c._prepare(self.data());schema=c._schema(*values[:5])
        finally:c.PROMPTS=old
        plan={'facts':[{'text':'고정 사실','evidenceId':'e'}]}
        schema=c.grounding.analysis_schema(schema,plan,True)
        self.assertEqual(['interpretation'],schema['properties']['claims']['items']['properties']['kind']['enum'])
        self.assertEqual(1,schema['properties']['claims']['maxItems'])
        claim=f.claim('중복 문장',['e'],kind='interpretation',basisFactIds=['fact:0'])
        with self.assertRaisesRegex(c.ContextError,'duplicate_claim'):c.grounding.project({'claims':[claim,copy.deepcopy(claim)]},plan,c.require,True)

    def test_source_id_plan_never_accepts_generated_quote_or_foreign_document(self):
        plan={'facts':[{'text':'시험 기업의 잠정 매출은 약 1원이다.','sourceIds':['e','identity'],'factType':'revenue'}]}
        evidence={'e':{'documentId':'doc'},'identity':{'documentId':'doc'},'foreign':{'documentId':'other'}}
        c.grounding.validate_facts(plan,evidence,c.require,True,True)
        self.assertEqual(['e','identity'],c.grounding.fact_claims(plan)[0]['evidenceIds'])
        plan['facts'][0]['sourceQuote']='모델이 새로 만든 인용'
        with self.assertRaisesRegex(c.ContextError,'fields'):c.grounding.validate_facts(plan,evidence,c.require,True,True)
        plan['facts'][0].pop('sourceQuote');plan['facts'][0]['sourceIds']=['e','foreign']
        with self.assertRaisesRegex(c.ContextError,'source_owner'):c.grounding.validate_facts(plan,evidence,c.require,True,True)


if __name__=='__main__':unittest.main()
