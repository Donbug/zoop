"""Authored synthetic business results only; provider/network access is never used."""
import copy,json,tempfile,unittest
from pathlib import Path
import briefing_priority_generation as p
import briefing_priority_server as server
from test_briefing_issue_intelligence import frozen,assess,checks,statement
m=p.m;b=p.b


def inputs():
    f=frozen(2);return m.analysis_inputs(f,m.select(f,assess(f),checks(f)),[])


def business_answer(f,scope):
    issues={}
    for issue in f['issues']:
        companies={}
        for target in issue['targets']:
            s=statement('합성 계약의 이행이 확인되면 매출 기반이 넓어질 수 있어 실제 공급 여부를 확인합니다.',target['evidenceIds'][0])
            companies[target['companyId']]={**{k:copy.deepcopy(s) for k in ['keyPoint','confirmedFact','businessImpact','outlook','nextCheck','directionReason', 'companyConnection' if scope=='common' else 'forMyStocks']},
                'direction':'watch','positive':None,'negative':None,'priceObservation':None,
                'previousChange':{**s,'status':'unavailable'},'directionConfidence':'limited','effectSizeStatus':'unquantified'}
        s=statement(evidence=next(iter(issue['sources'])))
        issues[issue['issueId']]={'headline':s,'topicTag':'공급 계약','subline':s,'companies':companies}
    return {'overview':statement(evidence=next(iter(f['issues'][0]['sources']))),'issues':issues}


def supported(schema):
    if schema.get('type')=='object':
        if set(schema['properties'])=={'supported','reason'}:return {'supported':True,'reason':'합성 사실·기업 경로를 대조했습니다.'}
        return {k:supported(v) for k,v in schema['properties'].items()}
    raise AssertionError('verification schema changed')


def answer_for(request):
    data=json.loads(request['input']);stage=request['text']['format']['name']
    if stage.endswith('-check'):return supported(request['text']['format']['schema'])
    if stage in ('priority-common','priority-personal'):
        return business_answer(data['frozen'],'personal' if stage.endswith('personal') else 'common')
    if stage=='priority-summary':
        s=statement('선정 기업의 계약 이행과 공급 확인이 다음 판단의 조건입니다.',data['frozen']['references'][0])
        return {**{k:copy.deepcopy(s) for k in ['headline','roundAssessment','nextSessionOutlook']},'nextChecks':[s]}
    if stage=='selection':
        result=assess(data['frozen'])
        for candidate in data['frozen']['candidates']:
            if candidate['freshnessReview']['decision']!='DISTINCT_EVENT':
                a=result['assessments'][candidate['issueId']];a['informationChange']='material_update'
                delta=candidate['freshnessReview'].get('deltaEvidenceIds',[])
                if delta:a['whyNow']['evidenceIds']=[delta[0]]
                else:a['informationChange']='uncertain'
        return result
    if stage=='selection-verification':return checks(data['frozen'])
    if stage=='analysis-verification':return {'checks':{f['issueId']:{'supported':True,'reason':'합성 대조'} for f in data['issues']}}
    if stage=='analysis':
        issues={}
        for f in data['issues']:
            companies=[]
            for target in f['targets']:
                s=statement(evidence=target['sourceIds'][0]);companies.append({'companyId':target['companyId'],'assessment':'watch',
                    **{k:copy.deepcopy(s) for k in ['takeaway','positive','negative','newInformation','impact','outlook']},'conditions':[s],'risks':[s],
                    'comparison':{**s,'status':'unavailable','previousResultVersion':None}})
            issues[f['issueId']]={'headline':statement(evidence=next(iter(f['sources']))),'companies':companies}
        return {'issues':issues}
    raise AssertionError(stage)


class Transport:
    def __init__(self,mutate=None):self.requests=[];self.mutate=mutate
    def __call__(self,raw):
        req=json.loads(raw);self.requests.append(req);answer=answer_for(req)
        if self.mutate: self.mutate(req,answer)
        return 200,b.canonical({'id':'synthetic-'+str(len(self.requests)),'status':'completed','usage':{'input_tokens':100,'output_tokens':50},
            'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]})


class PriorityGenerationTests(unittest.TestCase):
    def client(self,path,t):return m.company.context.legacy.MarketSummaryClient(Path(path),t,16,prompt_root=m.PROMPTS)
    def test_independent_requests_and_exact_receipts_bind_both_views_and_summary(self):
        t=Transport()
        with tempfile.TemporaryDirectory() as path:
            client=self.client(path,t);common=p.generate(client,inputs(),'common');personal=p.generate(client,inputs(),'personal');summary=p.summary(client,common)
            calls=p.verified_calls(path);self.assertTrue(p.prove(common,calls));self.assertTrue(p.prove(personal,calls));self.assertTrue(p.prove_summary(summary[0],calls))
            self.assertEqual(6,len(t.requests));self.assertEqual('personal-impact-relative-v3',personal['promptVersion'])
            self.assertEqual('separate_request_same_model',p.item(personal,'i0')['aiAnalyses'][0]['verificationMode'])
            self.assertTrue(all(r['store'] is False and r['text']['format']['strict'] for r in t.requests))
            self.assertNotIn('memberId',json.dumps(t.requests));self.assertNotIn('choice',json.dumps(t.requests))
            p.generate(client,inputs(),'common');self.assertEqual(6,len(t.requests))
            bad=copy.deepcopy(common);bad['draft']['issues']['i0']['companies']['C']['outlook']['text']='다른 문장'
            with self.assertRaises((ValueError,b.ReplayError,p.c.b.ReplayError)):p.prove(bad,calls)
            with self.assertRaises((ValueError,b.ReplayError,p.c.b.ReplayError)):p.prove(common,[])
            with self.assertRaises((ValueError,b.ReplayError,p.c.b.ReplayError)):p.prove_summary(summary[0],[])
    def test_business_field_rejection_prevents_materialization(self):
        def reject(req,answer):
            if req['text']['format']['name']=='priority-personal-check':answer['issues']['i0']['companies']['C']['businessImpact']['supported']=False
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaisesRegex(ValueError,'semantic_verification_failed'):p.generate(self.client(path,Transport(reject)),inputs(),'personal')
    def test_future_scope_foreign_evidence_and_language_are_not_repaired_into_a_pass(self):
        f=p.freeze(inputs(),'common');draft=business_answer(f,'common');p.c.validate(draft,f,'common')
        for field,value in [('keyPoint',statement(evidence='foreign')),('outlook',statement('中国消息需要关注重要变化并等待确认')),('positive',None)]:
            bad=copy.deepcopy(draft);a=bad['issues']['i0']['companies']['C'];a[field]=value
            if field=='positive':a['direction']='positive'
            with self.assertRaises((ValueError,b.ReplayError,p.c.b.ReplayError)):p.c.validate(bad,f,'common')
        f['issues'][0]['sources']['e0']['publishedAt']='2027-01-01T00:00:00+09:00'
        with self.assertRaises((ValueError,b.ReplayError,p.c.b.ReplayError)):p.c.validate(draft,f,'common')
    def test_frozen_round_and_cache_namespace_cannot_relabel_old_result(self):
        values=inputs();old=copy.deepcopy(values[0]);sealed=p.priority_input(old)
        self.assertNotEqual(sealed['inputSha256'],old['inputSha256']);self.assertEqual(old,values[0]);m.check_seal(sealed)
        values[1]['roundId']='other';values[1]=m.seal(values[1])
        with self.assertRaisesRegex(ValueError,'mixed_rounds'):p.freeze(values,'common')
    def test_relative_priority_preserves_core_and_actual_importance_and_dedup(self):
        f=frozen(3);a=assess(f);a['assessments']['i1']['businessImportance']=1;a['assessments']['i2']['businessImportance']=0
        core=m.select(f,a,checks(f));picked=server.priority_selection(f,a,checks(f),core)
        self.assertEqual(['i0'],[v['issueId'] for v in core['selected']]);self.assertEqual(['i0','i1'],[v['issueId'] for v in picked['selected']]);self.assertEqual(1,picked['selected'][1]['assessment']['businessImportance'])
        self.assertEqual(1,a['assessments']['i1']['businessImportance'])
    def test_unknown_response_is_never_automatically_resent(self):
        sent=[]
        def lost(raw):sent.append(raw);raise TimeoutError('synthetic transport lost')
        with tempfile.TemporaryDirectory() as path:
            with self.assertRaisesRegex(Exception,'transport_unknown_usage_no_automatic_retry'):p.generate(self.client(path,lost),inputs(),'common')
            with self.assertRaises(Exception):p.generate(self.client(path,lost),inputs(),'common')
        self.assertEqual(1,len(sent))
