"""Synthetic input, proof and paid-call guards. No external transport."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import briefing_selected_generation as g
from test_briefing_issue_intelligence import frozen,assess,checks,statement
m=g.m;b=g.b

def snapshot():
    f=frozen(1);selected=m.select(f,assess(f),checks(f));inputs=m.analysis_inputs(f,selected,[])
    return {'roundId':'r','cutoff':f['cutoff'],'poolVersion':'p','selectionVersion':'s','selectedIssueIds':['i0'],'inputs':inputs,
        'selection':{'roundId':'r','dataAsOf':f['cutoff'],'poolVersion':'p','selectionVersion':'s','presentation':{'items':[{'eventId':'i0'}],'metadata':{'graphVersion':None}}}}

class SelectedGenerationTests(unittest.TestCase):
    def test_freezes_exact_round_cutoff_selection_and_future_prices(self):
        s=snapshot();g.validate_snapshot(s);old=copy.deepcopy(s)
        for field,value in [('roundId','other'),('cutoff','2027-01-01T00:00:00Z'),('selectedIssueIds',['other'])]:
            bad=copy.deepcopy(s);bad[field]=value
            with self.assertRaises(ValueError):g.validate_snapshot(bad)
        bad=copy.deepcopy(s);bad['inputs'][0]['targets'][0]['observedMovement']={'status':'available','latest':{'observedAt':'2027-01-01T00:00:00Z'}};bad['inputs'][0]=m.seal(bad['inputs'][0])
        with self.assertRaises(ValueError):g.validate_snapshot(bad)
        self.assertEqual(s,old)
    def test_uses_common_generator_independent_checker_and_proves_exact_output(self):
        s=snapshot();sent=[]
        def transport(raw):
            req=json.loads(raw);data=json.loads(req['input']);stage=req['text']['format']['name'];sent.append(stage)
            if stage=='analysis-verification':answer={'checks':{f['issueId']:{'supported':True,'reason':'합성 대조'} for f in data['issues']}}
            else:
                issues={}
                for f in data['issues']:
                    company=[]
                    for t in f['targets']:
                        text=statement(evidence=t['sourceIds'][0]);company.append({'companyId':t['companyId'],'assessment':'watch',**{k:copy.deepcopy(text) for k in ['takeaway','positive','negative','newInformation','impact','outlook']},'conditions':[text],'risks':[text],'comparison':{**text,'status':'unavailable','previousResultVersion':None}})
                    issues[f['issueId']]={'headline':statement(),'companies':company}
                answer={'issues':issues}
            return 200,b.canonical({'id':'synthetic-'+str(len(sent)),'status':'completed','usage':{'input_tokens':5,'output_tokens':5},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]})
        with tempfile.TemporaryDirectory() as d:
            client=m.company.context.legacy.MarketSummaryClient(Path(d),transport,4,prompt_root=m.PROMPTS)
            drafted,verified,attempts=m.analyze(client,s['inputs']);f=s['inputs'][0]
            record={**{k:f[k] for k in ['roundId','date','edition','cutoff','issueId']},'status':'PASS','frozen':f,'draft':drafted['issues']['i0'],'verification':verified['checks']['i0']};record['resultVersion']=m.VERSION+'-'+b.digest(b.canonical(record))
            calls=g.view.verified_calls(d);self.assertTrue(g.prove(record,calls));v=g.materialize(record,{'graphVersion':None},b.now())
            self.assertEqual('i0',v['item']['eventId']);self.assertEqual('PASS',v['analysis']['status'])
            m.analyze(client,s['inputs']);self.assertEqual(['analysis','analysis-verification'],sent)
            bad=copy.deepcopy(record);bad['draft']['headline']['text']='변조'
            with self.assertRaises(ValueError):g.prove(bad,calls)
    def test_unknown_duplicate_cannot_dispatch_or_change_existing_budget(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);b.private_dir(root/'finished');b.private_dir(root/'responses');raw=b.canonical({'model':b.MODEL,'store':False,'instructions':(m.PROMPTS/'analysis.md').read_text(),'max_output_tokens':20,'text':{'format':{'name':'analysis'}}});key=b.digest(raw)
            existing={'budgetId':key,'requestDigest':key,'task':'older','reservedUpperUsd':'0.01'};(root/(key+'.json')).write_bytes(b.canonical(existing))
            cfg={'budget':d,'task':'test','maxNewCalls':8,'baselineCalls':0,'baselineUsd':'0','maxAggregateCalls':8,'maxUsd':'3'}
            conn=Mock();authority=Mock();t=g.BudgetTransport(cfg,conn,'job',authority)
            with patch.object(b,'authenticated_transport') as actual:
                with self.assertRaisesRegex(ValueError,'duplicate_not_resent'):t(raw)
                actual.assert_not_called();conn.execute.assert_not_called()
            self.assertEqual(existing,json.loads((root/(key+'.json')).read_text()))

    def test_worker_bound_to_private_authorization_and_local_replay_database(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);auth=root/'approval.json';config=root/'config.json'
            auth.write_text(json.dumps({'task':'test','model':b.MODEL,'maximumNewCalls':8,'maximumAggregateCalls':254,'maximumAggregateUsd':'3'}));auth.chmod(0o600)
            cfg={'task':'test','authorizationFile':str(auth),'maxNewCalls':8,'maxAggregateCalls':254,'maxUsd':'3','dsn':'postgresql://user:local@127.0.0.1:5432/test_briefing_replay'}
            config.write_text(json.dumps(cfg));config.chmod(0o600)
            self.assertEqual(cfg,g.load_config(config))
            for key,value in [('maxNewCalls',9),('maxAggregateCalls',255),('maxUsd','3.01'),('task','different'),('dsn','postgresql://user:local@remote:5432/test_briefing_replay'),('dsn','postgresql://127.0.0.1:5432/production'),('dsn','postgresql://127.0.0.1:5432/test_briefing_replay?host=remote')]:
                config.write_text(json.dumps({**cfg,key:value}))
                with self.assertRaises(ValueError):g.load_config(config)
    def test_worker_rejects_readable_secrets_before_start(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);auth=root/'approval.json';config=root/'config.json'
            auth.write_text('{}');auth.chmod(0o644);config.write_text(json.dumps({'authorizationFile':str(auth)}));config.chmod(0o600)
            with self.assertRaisesRegex(ValueError,'private_authorization_file'):g.load_config(config)
            config.chmod(0o644)
            with self.assertRaisesRegex(ValueError,'private_worker_config'):g.load_config(config)
