"""Test-owned synthetic provider, actual existing generators and actual JDBC command. Never a real model call."""
import copy
import json
import os
from pathlib import Path
import sys

SCRIPTS=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(SCRIPTS));sys.path.insert(0,str(SCRIPTS/'tests'))
import briefing_usage_run as runner
from briefing_usage import CommandPipe,UsageSession,recorded,digest,reconcile
from test_briefing_company_outlook import CompanyOutlookTest
from test_briefing_round_simulation import AuthoredTransport,response

work=Path(sys.argv[1]).resolve();classpath=sys.argv[2]
command=[os.environ['JAVA'],'-cp',classpath,'com.zoop.briefing.usage.BriefingUsageCommand','--stdio']


def job(name,operation,data,date,round_id=None):
    raw=json.dumps(data,ensure_ascii=False).encode();(work/(name+'.input.json')).write_bytes(raw)
    r={'id':round_id or name,'date':date,'edition':'morning','scheduledAt':date+'T00:20:00Z',
       'windowFrom':None,'windowTo':date+'T00:20:00Z'}
    spec={'schemaVersion':'briefing-recorded-producer-v1','operation':operation,'round':r,'requestKey':'authored-'+name,
          'trigger':'scheduler','adminId':None,'inputArtifactId':None,'inputFile':name+'.input.json',
          'inputSha256':digest(raw),'maxCalls':8,'authorizationRef':'authored-test-no-network'}
    path=work/(name+'.job.json');path.write_text(json.dumps(spec));return path,spec


fixture=CompanyOutlookTest();frozen=fixture.frozen()
frozen.update(roundId='usage-outlook',date='2026-10-28',cutoff='2026-10-28T00:20:00Z')
checks=0
generations=0


def outlook_transport(raw):
    global checks,generations
    request=json.loads(raw);stage=request['text']['format']['name']
    if stage.endswith('generation'):
        draft=fixture.draft()
        generations+=1
        if generations>1:draft['companies'][0]['outlook']['text']='구체적인 합성 확인 조건'
    else:
        checks+=1
        draft={'checks':[{'companyId':'A','supported':checks>1,'reason':'authored independent check'}]}
    code,body=response(draft,raw)
    value=json.loads(body);value['model']='authored-reported-model'
    return code,json.dumps(value).encode()


path,spec=job('outlook','outlook',frozen,'2026-10-28','usage-outlook')
result=runner.run(path,work/'outlook',command,execute=True,transport=outlook_transport)
assert result['newModelCalls']==4 and result['outcome']=='available'
recovery=CommandPipe(command)
try:
    assert reconcile(work/'outlook/usage',recovery)=={'status':'RECONCILED','receipts':4,'newModelCalls':0}
finally:recovery.close()
assert runner.run(path,work/'outlook',command,execute=True,transport=lambda _:(_ for _ in ()).throw(AssertionError('cached result must not send')))['newModelCalls']==0

# Cache reuse inside a distinct domain attempt creates replay observations, not old live rows/tokens.
producer=runner.helper('briefing_company_outlook')
client=producer.context.legacy.MarketSummaryClient(work/'outlook',lambda _:(_ for _ in ()).throw(AssertionError('replay sent')),8,prompt_root=producer.PROMPTS)
pipe=CommandPipe(command)
claim={k:spec[k] for k in ('round','requestKey','trigger','adminId','inputArtifactId')};claim.update(purpose='outlook',requestKey='authored-replay')
claim['inputDigest']=spec['inputSha256']
try:
    with recorded(client,UsageSession(pipe,claim,work/'replay-usage')) as session:
        assert producer.assess(client,frozen)['status']=='PASS'
finally:pipe.close()
assert not client.new_calls and len(client.reused_calls)==4

saved=json.loads((work/'outlook/result.json').read_bytes())
path,_=job('save','save_only_outlook',saved,'2026-10-28','usage-outlook')
assert runner.run(path,work/'save',command,execute=True)['newModelCalls']==0

selected=[{'issueId':'issue-authored','rank':1,'sources':[{'evidenceId':'evidence-authored'}]}]
context={'context':{'mode':'historical_round_simulation_v1','date':'2026-10-27','edition':'morning'}}
sim=runner.helper('briefing_round_simulation');context['context']['mode']=sim.MODE
context['context']['window']={'from':None,'to':'2026-10-27T00:20:00Z','openStart':True}
context['contextSha256']=sim.digest(sim.canonical(context['context']))
path,_=job('generation','generation',{'selected':selected,'context':context,'maxRepairs':0},'2026-10-27','usage-generation')
assert runner.run(path,work/'generation',command,execute=True,transport=AuthoredTransport())['newModelCalls']==2

unknown=copy.deepcopy(frozen);unknown.update(roundId='usage-unknown',date='2026-10-26',cutoff='2026-10-26T00:20:00Z')
path,_=job('unknown','outlook',unknown,'2026-10-26','usage-unknown')
try:
    runner.run(path,work/'unknown',command,execute=True,transport=lambda _:(_ for _ in ()).throw(OSError('authored unknown transmission')))
except Exception:pass
else:raise AssertionError('unknown transmission must stop')
print(json.dumps({'status':'PASS','newExternalProviderCalls':0,'syntheticModelAttempts':7,'replayObservations':4,'saveOnly':1}))
