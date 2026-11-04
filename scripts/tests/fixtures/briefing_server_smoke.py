"""Synthetic local-only E2E driver. Never imported by the deployment entry point."""
import copy,json,os,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import briefing_server_runtime as runtime
from test_briefing_issue_intelligence import assess,checks,statement
m=runtime.m
calls=[]
mode=sys.argv[4] if len(sys.argv)>4 else "normal"
def transport(raw):
    request = json.loads(raw); data = json.loads(request['input']); stage = request['text']['format']['name']
    calls.append(stage)
    if stage == 'selection': answer = assess(data['frozen'])
    elif stage == 'selection-verification': answer = checks(data['frozen'])
    elif stage == 'analysis-verification': answer = {'checks': {f['issueId']: {'supported': mode!='withheld', 'reason': '합성 검증'} for f in data['issues']}}
    else:
        issues = {}
        for f in data['issues']:
            companies = []
            for t in f['targets']:
                s = statement(text='합성 보완 계약의 이행 조건을 확인합니다.' if data.get('repair') else '합성 계약의 이행 조건을 확인합니다.',evidence=t['sourceIds'][0])
                companies.append({'companyId': t['companyId'], 'assessment': 'watch',
                    **{k: copy.deepcopy(s) for k in ['takeaway','positive','negative','newInformation','impact','outlook']},
                    'conditions': [s], 'risks': [s], 'comparison': {**s,'status':'unavailable','previousResultVersion':None}})
            issues[f['issueId']] = {'headline': statement(evidence=next(iter(f['sources']))), 'companies': companies}
        answer = {'issues': issues}
    return 200, m.base.canonical({'id': 'synthetic-'+str(len(calls)), 'status': 'completed',
        'usage': {'input_tokens': 100, 'output_tokens': 50},
        'output': [{'type': 'message', 'content': [{'type':'output_text','text':json.dumps(answer)}]}]})
root=Path(sys.argv[1]).resolve();classpath=sys.argv[2];edition=sys.argv[3]
runtime.b.authenticated_transport=lambda key:transport
java=[os.environ['JAVA'],'-cp',classpath]
cfg={'work':str(root/'work'),'authorizationRef':'synthetic-server-test','keyFile':str(root/'never-read-key'),
     'serverCommand':java+['com.zoop.briefing.server.BriefingServerCommand'],
     'ledgerCommand':java+['com.zoop.briefing.usage.BriefingUsageCommand','--stdio']}
job={'id':'brf-2026-11-02-'+edition,'round_date':'2026-11-02','edition':edition,
     'scheduled_at':datetime.fromisoformat('2026-11-02T01:03:03+00:00'),
     'window_from':datetime.fromisoformat('2026-10-07T00:00:00+00:00')}
if mode=='input-failed':
    work=Path(cfg['work'])/job['id'];work.mkdir(mode=0o700)
    r={'id':job['id'],'date':str(job['round_date']),'edition':job['edition'],'scheduledAt':job['scheduled_at'].isoformat(),
       'windowFrom':job['window_from'].isoformat(),'windowTo':job['scheduled_at'].isoformat()}
    attempt=runtime.record_input_failure(cfg,r,work)
    assert attempt==runtime.record_input_failure(cfg,r,work)
    assert not calls
elif mode=='withheld':
    try:runtime.produce(cfg,job)
    except ValueError as error:assert str(error)=='briefing_server_selected_issue_withheld'
    else:raise AssertionError('unsupported issue was published')
    assert len(calls)==6
else:
    result=runtime.produce(cfg,job)
    assert result['status']=='published'
    assert len(calls)==4
print(json.dumps({'syntheticCalls':len(calls),'mode':mode}))
