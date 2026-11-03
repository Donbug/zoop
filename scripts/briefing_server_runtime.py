"""Server-only common producer: fixed graph inputs, recorded model calls, fenced immutable publication.

The existing first47 reader/importer and graph scheduler remain independent.
All mutable files live under an operator-owned, durable private briefing root.
"""
from __future__ import annotations
import argparse,copy,fcntl,hashlib,json,os,re,subprocess,time
from datetime import datetime,timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import briefing_issue_intelligence as m
import briefing_issue_intelligence_view as view
import briefing_personal_pool as pools
import briefing_selected_generation as selected_view
from briefing_usage import CommandPipe,UsageSession,recorded,write_once
from briefing_common_schedule_worker import published

b=m.base
KST=ZoneInfo('Asia/Seoul')

def require(value,code):
    if not value:raise ValueError('briefing_server_'+code)

def java(cfg,operation,request,path):
    write_once(path,request)
    result=subprocess.run(cfg['serverCommand']+[operation,str(path)],capture_output=True,timeout=90,check=False)
    # Raw stdout can contain source quotes. Keep it private and never forward it to task logs.
    require(result.returncode==0,'source_or_publication_not_ready')
    marker=b'BRIEFING_SERVER_RESULT='
    lines=[line[len(marker):] for line in result.stdout.splitlines() if line.startswith(marker)]
    require(len(lines)==1 and len(lines[0])<=4*1024*1024,'bounded_command_response')
    return json.loads(lines[0])

class Budget:
    """Write-ahead reservations include unknown outcomes; no refund without an actual usage receipt."""
    def __init__(self,cfg,round_id,authority,transport):
        self.cfg,self.round_id,self.authority,self.transport=cfg,round_id,authority,transport
    def reserve(self,encoded):
        self.authority()
        require(re.fullmatch(r"brf-\d{4}-\d{2}-\d{2}-(morning|evening)",self.round_id),"round_identity")
        request=json.loads(encoded);require(request['model']=='gpt-6-luna' and request['store'] is False and not request.get('tools') and request.get('service_tier')=='default','model_policy')
        root=Path(self.cfg['work'])/'budget';root.mkdir(mode=0o700,exist_ok=True)
        key=hashlib.sha256(encoded).hexdigest();day=str(datetime.now(KST).date())
        # Same conservative token envelope used by the existing briefing request recorder.
        reserve=(Decimal(2*len(encoded)+4096)*Decimal('.5')+Decimal(request['max_output_tokens'])*Decimal('1.5'))/1000000
        with (root/'.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            rows=[json.loads(p.read_bytes()) for p in root.glob('*.json')]
            require(not any(r['requestDigest']==key for r in rows),'uncertain_or_reused_request')
            own=[r for r in rows if r['roundId']==self.round_id];today=[r for r in rows if r['day']==day]
            def amount(r):
                done=root/'finished'/(r['requestDigest']+'.json')
                return Decimal(json.loads(done.read_bytes())['upperUsd']) if done.exists() else Decimal(r['reservedUpperUsd'])
            require(len(own)<16 and sum(map(amount,own),Decimal(0))+reserve<=1,'round_budget')
            require(sum(map(amount,today),Decimal(0))+reserve<=2,'daily_budget')
            write_once(root/(key+'.json'),{'requestDigest':key,'roundId':self.round_id,'day':day,'reservedUpperUsd':str(reserve),'reservedAt':b.now(),
                'costBasis':'openai-2026-11-03-standard-upper-envelope-v1','currency':'USD','actualCost':None,
                'authorizationRef':self.cfg.get('authorizationRef')})
        return key,reserve
    def dispatch(self,encoded,reservation):
        key,reserve=reservation;root=Path(self.cfg['work'])/'budget'
        status,raw=self.transport(encoded)
        try:response=json.loads(raw)
        except (ValueError,UnicodeError):response={}
        usage=response.get('usage') or {}
        known=all(type(usage.get(k)) is int and usage[k]>=0 for k in ('input_tokens','output_tokens'))
        cost=(Decimal(usage['input_tokens'])*Decimal('.5')+Decimal(usage['output_tokens'])*Decimal('1.5'))/1000000 if known else reserve
        (root/'finished').mkdir(mode=0o700,exist_ok=True)
        write_once(root/'finished'/(key+'.json'),{'requestDigest':key,'upperUsd':str(cost),'usageKnown':known,'actualCost':None,'finishedAt':b.now()})
        return status,raw
    def __call__(self,encoded):
        return self.dispatch(encoded,self.reserve(encoded))

class ServerUsageSession(UsageSession):
    """Admission precedes model_start so denied/over-budget work is never a live AI execution."""
    def invoke(self,stage,encoded,transport):
        reservation=self.budget.reserve(encoded)
        return super().invoke(stage.replace('-','_'),encoded,lambda body:self.budget.dispatch(body,reservation))
    def replay(self,stage,call):
        return super().replay(stage.replace('-','_'),call)

class RecordedClient(m.company.context.legacy.MarketSummaryClient):
    def request(self,*args,**kwargs):
        encoded,schema,prompt_sha=super().request(*args,**kwargs)
        value=json.loads(encoded);value['service_tier']='default'
        return b.canonical(value),schema,prompt_sha
    def call(self,stage,*args,**kwargs):
        if self.usage is not None:
            self.usage.feature='briefing-outlook' if stage.startswith('analysis') else 'briefing'
            if stage in ('selection','analysis'):
                self.usage.unit=stage+'-repair-1' if args and args[0].get('repair') else None
        return super().call(stage,*args,**kwargs)

def frozen_input(prepared):
    r=prepared['round']
    return m.seal({'schemaVersion':m.VERSION,'policyVersion':m.POLICY,'roundId':r['id'],'date':r['date'],'edition':r['edition'],
        'cutoff':r['windowTo'],'window':{'from':r['windowFrom'],'to':r['windowTo']},'candidates':prepared['candidates'],
        'freshnessPolicy':'native-canonical-and-independent-review-v1','previousSelected':prepared.get('previous',{}).get('selected',[]),
        'excluded':[],'candidatePoolCount':len(prepared['candidates']),'scope':'published_graph_snapshot_only',
        'marketReference':{'status':'unavailable','reason':'no_validated_market_input_at_cutoff'},
        'baselineResponseSha256':prepared['inputSha256']})

def make_publication(prepared,frozen,selection,passed,calls,assessed,checked,now):
    r=prepared['round']; metadata={'source':'published-graph-briefing-server','asOf':r['windowTo'],
        'graphVersion':prepared['graphVersion'],'partial':True,'requestId':'server:'+r['id'],
        'schedule':{'morning':'09:20','evening':'17:30','confirmed':True},
        'selection':{'basis':'market','reason':'현재 공개 그래프에 보존된 자료 범위에서 검증한 사업 중요도와 신규 정보입니다.'},
        'failures':[{'section':'collection','code':'limited_source_coverage','message':'전체 뉴스·시장 지표를 수집한 결과가 아닙니다.','retryable':False,'asOf':r['windowTo']}]}
    items=[]; analyses=[]; details={}
    for record in passed:
        view.prove_issue(record,calls)
        value=selected_view.materialize(record,metadata,now);item=value['item'];iid=record['issueId']
        candidate=next(c for c in prepared['candidates'] if c['issueId']==iid)
        item['rank']=len(items)+1
        for link in item['companies']:
            original=next(c for c in candidate['companies'] if c['companyId']==link['id'])
            link['relationType']=original['relationType']
        item['reportedAt']=max(s['publishedAt'] for s in candidate['sources'].values())
        item['matchedCompanyIds']=[];item['documentSentiments']=[]
        documents=sorted({s['documentId'] for s in candidate['sources'].values()})
        item['sourceSupport']={'articleCount':len(documents),'knownLineageCount':None,'independentSourceCount':None,'unknownLineageArticles':documents,'duplicateGroups':[]}
        item['summary']['text']='\n'.join(c['takeaway']['text']+' '+c['newInformation']['text']+' 다음 확인: '+' '.join(x['text'] for x in c['conditions']) for c in record['draft']['companies'])
        item['summary']['evidenceIds']=sorted({e for c in record['draft']['companies'] for field in ['takeaway','newInformation'] for e in c[field]['evidenceIds']} |
            {e for c in record['draft']['companies'] for x in c['conditions'] for e in x['evidenceIds']})
        detail=value['detail'];detail['summary']=copy.deepcopy(item['summary']);detail['companies']=copy.deepcopy(item['companies'])
        detail['metadata']=copy.deepcopy(metadata)
        detail['evidence']=[{'id':sid,'quote':s['quote'],'documentId':s['documentId'],'documentVersion':s['documentVersion'],
            'title':s.get('title') or '', 'publisher':s.get('publisher') or '', 'url':s['url'],'publishedAt':s['publishedAt'],
            'quoteVerified':True,'sourceKind':s['sourceKind'],'bodySha256':s['bodySha256'],'bodyContext':None} for sid,s in candidate['sources'].items()]
        detail['claims']=[{**copy.deepcopy(c[key]),'type':kind} for c in record['draft']['companies'] for key,kind in [('newInformation','fact'),('impact','outlook'),('outlook','outlook')]]
        details[iid]=detail
        items.append(item);analyses.append(value['analysis'])
    payload={'id':r['id'],'date':r['date'],'edition':r['edition'],'scheduledAt':r['scheduledAt'],'generatedAt':now,
        'dataWindow':{'start':r['windowFrom'],'end':r['windowTo'],'openStart':False},'graphVersion':prepared['graphVersion'],
        'reviewRevision':prepared['reviewRevision'],'ruleRevision':prepared['ruleRevision'],'selectedFrom':len(frozen['candidates']),
        'items':items,'references':{'eventIds':[i['eventId'] for i in items],
            'evidenceIds':sorted({e for i in items for e in i['evidenceIds']}),'companyIds':sorted({c['id'] for i in items for c in i['companies']})},
        'emptyReason':None if items else 'no_issues_in_window','marketVariables':None,'metadata':metadata,'outlook':None}
    snapshot={'sourceBindings':prepared['sourceBindings'],'itemDetails':details,'marketSummary':{'status':'unavailable','reason':'회차 마감에 결속된 시장 요약·지표 입력이 없습니다.'},
        'serverGeneration':{'version':'briefing-server-v1','inputSha256':prepared['inputSha256'],'coverage':prepared['coverage'],'analyses':analyses,'records':passed,'selected':selection['selected']}}
    row={'round':{k:frozen[k] for k in ['roundId','date','edition','cutoff']},'selection':selection,'assessments':assessed,
         'selectionVerification':checked,'passed':passed}
    registry={(s['documentId'],s['documentVersion']):s for c in frozen['candidates'] for s in c['sources'].values()}
    pool=pools.compile_pool(frozen,row,calls,registry) if frozen['candidates'] else {
        'schemaVersion':'personal-candidate-pool-v1','roundId':r['id'],'cutoff':r['windowTo'],'scope':frozen['scope'],
        'complete':True,'candidateCount':0,'candidates':[],'inputSha256':frozen['inputSha256'],'selectionPolicyVersion':m.POLICY}
    return payload,snapshot,pool

def produce(cfg,job):
    work=Path(cfg['work'])/job['id'];work.mkdir(mode=0o700,exist_ok=True)
    r={'id':job['id'],'date':str(job['round_date']),'edition':job['edition'],'scheduledAt':job['scheduled_at'].isoformat(),
       'windowFrom':job['window_from'].isoformat(),'windowTo':job['scheduled_at'].isoformat()}
    prepared=java(cfg,'prepare',{'round':r},work/'prepare.request.json')
    write_once(work/'prepared.json',prepared);frozen=frozen_input(prepared);write_once(work/'frozen.json',frozen)
    def current():
        java(cfg,'check',{'prepared':prepared},work/'check.request.json')
    write_once(work/'authorization.json',{'authorizationRef':cfg['authorizationRef'],'roundCalls':16,'roundUpperUsd':'1','dayUpperUsd':'2','model':'gpt-6-luna'})
    claim={'round':r,'requestKey':'server-'+prepared['inputSha256'],'purpose':'generation','trigger':'scheduler','adminId':None,
           'inputArtifactId':None,'inputDigest':prepared['inputSha256']}
    pipe=CommandPipe(cfg['ledgerCommand']);session=ServerUsageSession(pipe,claim,work/'model'/'usage',estimate={'currency':'USD','priceVersion':'openai-luna-standard-20261103','inputPerMillion':0.10,'outputPerMillion':0.50})
    session.budget=Budget(cfg,r['id'],current,b.authenticated_transport(Path(cfg['keyFile'])))
    client=RecordedClient(work/'model',session.budget.transport,16,prompt_root=m.PROMPTS)
    try:
        with recorded(client,session):
            require(not session.terminal,'completed_result_requires_recovery')
            if frozen['candidates']:
                assessed,checked,selection_attempts=m.assess_candidates(client,frozen)
                selection=m.select(frozen,assessed,checked,prepared.get('previous',{}).get('selected',[]))
            else:
                assessed,checked={'assessments':{}},{'checks':{}};selection={'selected':[],'rejected':[],'ranked':[],'policyVersion':m.POLICY,'inputSha256':frozen['inputSha256']}
            targets=m.analysis_inputs(frozen,selection,prepared.get('previous',{}).get('records',[]))
            drafted,verdicts,attempts=m.analyze(client,targets) if targets else ({'issues':{}},{'checks':{}},[])
            write_once(work/'analysis-attempts.json',attempts)
            passed=[]
            for target in targets:
                iid=target['issueId']
                if not verdicts['checks'][iid]['supported']:continue
                row={**{k:target[k] for k in ['roundId','date','edition','cutoff','issueId']},'status':'PASS','frozen':target,
                     'draft':drafted['issues'][iid],'verification':verdicts['checks'][iid]}
                row['resultVersion']=m.VERSION+'-'+b.digest(b.canonical(row));passed.append(row)
            # A rejected selected issue is a held generation, never a false "no new issue" publication.
            require(passed or not targets,'selected_issue_withheld')
            calls=view.verified_calls(work/'model')
            payload,snapshot,pool=make_publication(prepared,frozen,selection,passed,calls,assessed,checked,b.now())
            write_once(work/'result.json',{'payload':payload,'snapshot':snapshot,'pool':pool})
            session.send('heartbeat');session.stop.set()
            if session.thread:session.thread.join(timeout=10)
            result=java(cfg,'publish',{'prepared':prepared,'payload':payload,'snapshot':snapshot,'pool':pool,
                'attemptId':session.owner['attemptId'],'ownerToken':session.owner['ownerToken']},work/'publish.request.json')
            require(result['status']=='published' and result['roundId']==r['id'],'publication_proof')
            session.terminal=True;write_once(work/'published.json',result)
            return result
    finally:pipe.close()

def record_input_failure(cfg,round,work):
    """A failed input admission is still a generation attempt, with zero model executions."""
    digest=b.digest(b.canonical(round))
    claim={'round':round,'requestKey':'server-input-'+digest,'purpose':'generation','trigger':'scheduler','adminId':None,
           'inputArtifactId':None,'inputDigest':digest}
    pipe=CommandPipe(cfg['ledgerCommand'])
    try:
        owner=pipe.send({'op':'claim',**claim})
        directory=work/'input-usage';directory.mkdir(mode=0o700,exist_ok=True)
        write_once(directory/'attempt.json',{k:owner[k] for k in ('attemptId','ownerToken','roundId','attemptNo')})
        # A committed prepare failure is recovered under the same request identity, without another attempt or call.
        require(owner['status'] in ('running','failed'),'input_attempt_state')
        if owner['status']=='running':
            pipe.send({'op':'finish','attemptId':owner['attemptId'],'ownerToken':owner['ownerToken'],
                'outcome':'failed','failureStage':'prepare','failureReason':'approved_current_window_input_unavailable'})
        return owner['attemptId']
    finally:pipe.close()


def enqueue(conn,now):
    day=now.astimezone(KST).date()
    for edition,hour,minute in [('morning',9,20),('evening',17,30)]:
        slot=datetime(day.year,day.month,day.day,hour,minute,tzinfo=KST)
        if slot>now:continue
        start=slot.replace(hour=9,minute=20) if edition=='evening' else (slot-timedelta(days=1)).replace(hour=17,minute=30)
        conn.execute('INSERT INTO briefing_common_schedule_jobs(id,round_date,edition,scheduled_at,window_from) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(round_date,edition) DO NOTHING',
                     ('brf-'+str(day)+'-'+edition,day,edition,slot,start))

def work_once(cfg):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(cfg['dsn'],autocommit=True,row_factory=dict_row) as conn:
        # One dedicated producer, even when a replacement ECS task overlaps a rolling deployment.
        if not conn.execute("SELECT pg_try_advisory_lock(hashtext('zoop-briefing-server-v1')) AS owned").fetchone()['owned']:return False
        # Interrupted work is reconciled from the stored publication, never sent to the provider again.
        interrupted=conn.execute("SELECT * FROM briefing_common_schedule_jobs WHERE status='running'").fetchall()
        for old in interrupted:
            active=conn.execute("SELECT 1 FROM briefing_attempts WHERE round_id=%s AND status IN ('queued','running','verifying') AND lease_until>now()",(old['id'],)).fetchone()
            if not active:
                state='completed' if published(conn,old) else 'requires_recovery'
                conn.execute("UPDATE briefing_common_schedule_jobs SET status=%s,finished_at=now() WHERE id=%s AND status='running'",(state,old['id']))
        enqueue(conn,datetime.now(KST))
        job=conn.execute("SELECT * FROM briefing_common_schedule_jobs WHERE status='queued' ORDER BY scheduled_at LIMIT 1").fetchone()
        if not job:return False
        if published(conn,job):
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='completed',finished_at=now() WHERE id=%s AND status='queued'",(job['id'],));return True
        # Missing producer input is checked before consuming the queue or reserving a paid request.
        work=Path(cfg['work'])/job['id'];work.mkdir(mode=0o700,exist_ok=True)
        round={'id':job['id'],'date':str(job['round_date']),'edition':job['edition'],'scheduledAt':job['scheduled_at'].isoformat(),
               'windowFrom':job['window_from'].isoformat(),'windowTo':job['scheduled_at'].isoformat()}
        try:java(cfg,'prepare',{'round':round},work/'prepare.request.json')
        except (ValueError,subprocess.TimeoutExpired):
            age=(datetime.now(KST)-job['scheduled_at']).total_seconds()
            if age>cfg.get('inputGraceSeconds',1800):
                attempt=record_input_failure(cfg,round,work)
                conn.execute("UPDATE briefing_common_schedule_jobs SET status='requires_recovery',finished_at=now() WHERE id=%s AND status='queued'",(job['id'],))
                write_once(work/'input-unavailable.json',{'roundId':job['id'],'attemptId':attempt,'reason':'approved_current_window_input_unavailable','noModelCalls':True})
                print(json.dumps({'roundId':job['id'],'status':'requires_recovery','reason':'current_input_unavailable'}),flush=True)
                return True
            print(json.dumps({'roundId':job['id'],'status':'waiting_for_approved_published_input'}),flush=True);return False
        admitted=conn.execute("UPDATE briefing_common_schedule_jobs SET status='running' WHERE id=%s AND status='queued' RETURNING id",(job['id'],)).fetchone()
        if not admitted:return False
        try:
            produce(cfg,job)
            require(published(conn,job),'database_publication_and_pool_proof')
            state='completed'
        except Exception:
            state='completed' if published(conn,job) else 'requires_recovery'
        conn.execute("UPDATE briefing_common_schedule_jobs SET status=%s,finished_at=now() WHERE id=%s AND status='running'",(state,job['id']))
        print(json.dumps({'roundId':job['id'],'status':state}),flush=True);return True

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True,type=Path);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    require(not args.config.is_symlink() and args.config.stat().st_mode&0o077==0,'private_config')
    cfg=json.loads(args.config.read_bytes());require(cfg.get('enabled') is True,'enabled')
    root=Path(cfg['work']);root.mkdir(mode=0o700,parents=True,exist_ok=True);require(root.stat().st_mode&0o077==0,'private_work')
    while True:
        work_once(cfg)
        if args.once:return
        time.sleep(30)
if __name__=='__main__':main()
