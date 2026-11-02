"""Explicit selection worker: same common issue prompts, analysis and independent validation.

No member ID/choice/account data is sent to the model. A private operator config
provides local DB/grants/key paths and a shared, bounded paid-call budget.
Queued/running/completed records are never automatically re-dispatched after
an unknown network outcome or process loss.
"""
import argparse
import copy
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import re
from urllib.parse import urlsplit
import briefing_issue_intelligence as m
import briefing_issue_intelligence_view as view
b=m.base
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ai/service/src'))
from zoop_ai_service import grants


def validate_snapshot(snapshot):
    selection=snapshot['selection']; expected=[r['eventId'] for r in selection['presentation']['items']]
    m.require(snapshot['selectedIssueIds']==expected and len(set(expected))==len(expected)<=3,'selected_identity')
    m.require(snapshot['roundId']==selection['roundId'] and snapshot['cutoff']==selection['dataAsOf']
        and snapshot['poolVersion']==selection['poolVersion'] and snapshot['selectionVersion']==selection['selectionVersion'],'selected_scope')
    seen=set()
    for f in snapshot['inputs']:
        m.check_seal(f)
        m.require(f['issueId'] in expected and f['issueId'] not in seen and f['roundId']==snapshot['roundId']
            and m.aware(f['cutoff'])==m.aware(snapshot['cutoff']),'selected_input_scope');seen.add(f['issueId'])
        for s in f['sources'].values():m.require(m.aware(s['publishedAt'])<=m.aware(snapshot['cutoff']),'selected_future_source')
        for t in f['targets']:
            price=t['observedMovement']
            if price['status']=='available':m.require(m.aware(price['latest']['observedAt'])<=m.aware(snapshot['cutoff']),'selected_future_price')


def materialize(record,metadata,generated_at):
    f=record['frozen'];draft=record['draft'];iid=f['issueId']
    sources={k:{**copy.deepcopy(s),'title':'원문 자료'} for k,s in f['sources'].items()}
    companies=[];links=[]
    for c in draft['companies']:
        target=next(t for t in f['targets'] if t['companyId']==c['companyId'])
        companies.append({**copy.deepcopy(c),'sourceIds':target['sourceIds'],'previous':copy.deepcopy(target['previous'])})
        links.append({'id':target['companyId'],'name':target['companyName'],'relationType':'INVOLVES',
            'role':target['role'],'roleUnconfirmed':target['role'] is None})
    refs=sorted(sources);summary={'text':'\n'.join(c['newInformation']['text'] for c in draft['companies']),
        'evidenceIds':sorted({e for c in draft['companies'] for e in c['newInformation']['evidenceIds']}),
        'generatedAt':generated_at,'resultVersion':record['resultVersion']}
    item={'eventId':iid,'rank':1,'title':draft['headline']['text'],'reason':f['selection']['assessment']['whyImportant']['text']+' '+f['selection']['assessment']['whyNow']['text'],
        'companies':links,'evidenceIds':refs,'evidenceCount':len(refs),'summary':summary,'eventTime':None,'timePrecision':'unknown'}
    evidence=[]
    for sid,s in sources.items():
        context=None
        if s.get('context') and s['quote'] in s['context']:
            start=s['contextStart'];q=start+s['context'].index(s['quote'])
            context={'text':s['context'],'start':start,'end':s['contextEnd'],'quoteStart':q,'quoteEnd':q+len(s['quote']),'offsetUnit':'unicode_code_point'}
        evidence.append({**s,'id':sid,'documentVersion':'sha256-'+s['bodySha256'],'publisher':'','quoteVerified':True,'sourceKind':'news','bodyContext':context})
    detail={'roundId':f['roundId'],'eventId':iid,'title':item['title'],'summary':summary,'selectionReason':item['reason'],
        'companies':links,'claims':[{**c['newInformation'],'type':'fact'} for c in draft['companies']],
        'evidence':evidence,'limitations':[],'metadata':copy.deepcopy(metadata)}
    detail['metadata']['graphVersion']=None
    return {'item':item,'analysis':{'issueId':iid,'status':'PASS','resultVersion':record['resultVersion'],
        'headline':draft['headline'],'sources':sources,'companies':companies},'detail':detail,'generatedAt':generated_at}


def prove(record,calls):
    return view.prove_issue(record,calls)


class BudgetTransport:
    def __init__(self,cfg,conn,job_id,authority):self.cfg=cfg;self.conn=conn;self.job_id=job_id;self.authority=authority
    def amount(self,row):
        done=Path(self.cfg['budget'])/'finished'/(row.get('budgetId',row['requestDigest'])+'.json')
        return Decimal(b.strict_load(b.regular(done))['chargedUpperUsd']) if done.exists() else Decimal(row['reservedUpperUsd'])
    def __call__(self,raw):
        self.authority();req=b.strict_load(raw);stage=req['text']['format']['name'];key=b.digest(raw)
        m.require(req['model']==b.MODEL and req['store'] is False and stage in ['analysis','analysis-verification']
            and req['instructions']==(m.PROMPTS/(stage+'.md')).read_text(),'selected_transport_contract')
        root=Path(self.cfg['budget']);reserve=(Decimal(len(raw)+4096)*Decimal('.5')+Decimal(req['max_output_tokens'])*Decimal('1.5'))/1000000
        for p in [root,root/'finished',root/'responses']:b.private_dir(p)
        with (root/'.lock').open('a+') as guard:
            fcntl.flock(guard,fcntl.LOCK_EX);rows=[b.strict_load(b.regular(p)) for p in root.glob('*.json')]
            m.require(not any(r['requestDigest']==key for r in rows),'unknown_or_duplicate_not_resent')
            m.require(sum(r.get('task')==self.cfg['task'] for r in rows)<self.cfg['maxNewCalls']
                and self.cfg['baselineCalls']+len(rows)<self.cfg['maxAggregateCalls'],'selected_call_budget')
            spent=Decimal(self.cfg['baselineUsd'])+sum((self.amount(r) for r in rows),Decimal(0))
            m.require(spent+reserve<=Decimal(self.cfg['maxUsd']),'selected_cost_budget')
            row={'budgetId':key,'requestDigest':key,'task':self.cfg['task'],'stage':stage,'status':'pending','reservedUpperUsd':str(reserve),'startedAt':b.now()}
            b.write_once(root/(key+'.json'),b.canonical(row))
        self.conn.execute("INSERT INTO briefing_selected_generation_calls(request_sha256,job_id,stage,reserved_upper_usd) VALUES (%s,%s,%s,%s)",(key,self.job_id,stage,reserve))
        actual=b.authenticated_transport(Path(self.cfg['keyFile']),timeout=180)
        status,answer=actual(raw);b.write_once(root/'responses'/(key+'.response.json'),answer)
        value=b.strict_load(answer);usage=value.get('usage') or {};known=all(type(usage.get(k)) is int for k in ['input_tokens','output_tokens'])
        charged=(Decimal(usage['input_tokens'])*Decimal('.5')+Decimal(usage['output_tokens'])*Decimal('1.5'))/1000000 if known else reserve
        row.update(status='recorded',chargedUpperUsd=str(charged),finishedAt=b.now())
        if known:row.update(inputTokens=usage['input_tokens'],outputTokens=usage['output_tokens'])
        b.write_once(root/'finished'/(key+'.json'),b.canonical(row))
        self.conn.execute("UPDATE briefing_selected_generation_calls SET http_status=%s,input_tokens=%s,output_tokens=%s,charged_upper_usd=%s,finished_at=now() WHERE request_sha256=%s",(status,usage.get('input_tokens'),usage.get('output_tokens'),charged,key))
        print(json.dumps({'stage':stage,'reservedAggregateCalls':self.cfg['baselineCalls']+len(rows)+1,'usageKnown':known}),flush=True)
        return status,answer


def current_authority(conn,cfg,snapshot,job_id=None):
    # Fresh authority before EVERY send and again before publishing a checked result.
    if job_id:
        active=conn.execute("SELECT m.status FROM briefing_selected_generation_jobs j JOIN members m ON m.id=j.member_id WHERE j.id=%s",(job_id,)).fetchone()
        m.require(active and active[0]=='active','selected_member_unavailable')
    changed=conn.execute("SELECT 1 FROM briefing_changes WHERE round_id=%s AND kind='correction' LIMIT 1",(snapshot['roundId'],)).fetchone()
    m.require(not changed,'selected_publication_corrected')
    row=conn.execute("SELECT status,payload_sha256 FROM briefing_rounds WHERE id=%s",(snapshot['roundId'],)).fetchone()
    m.require(row and row[0]=='published','selected_round_unavailable')
    pool=conn.execute("SELECT snapshot FROM briefing_personal_pools WHERE round_id=%s AND input_sha256=%s AND snapshot_sha256=encode(sha256(convert_to(snapshot::text,'UTF8')),'hex')",(snapshot['roundId'],snapshot['poolVersion'])).fetchone()
    m.require(pool and pool[0]['publicationPayloadSha256']==row[1],'selected_publication_changed')
    latest=conn.execute("""SELECT input_sha256 FROM briefing_personal_pools WHERE round_id=%s AND snapshot->>'publicationPayloadSha256'=%s ORDER BY created_at DESC,id COLLATE "C" LIMIT 1""",(snapshot['roundId'],row[1])).fetchone()
    m.require(latest and latest[0]==snapshot['poolVersion'],'selected_pool_changed')
    b.strict_load(b.regular(Path(cfg['grants'])));registry=grants.load(Path(cfg['grants']))
    for iid in snapshot['selectedIssueIds']:
        candidate=next(c for c in pool[0]['candidates'] if c['issueId']==iid)
        for s in candidate['sources']:
            source=conn.execute("SELECT a.provider,t.sha256,v.published_at FROM articles a JOIN article_versions v ON v.article_id=a.id JOIN artifacts t ON t.id=v.text_artifact_id WHERE a.id=%s AND v.version=%s AND a.access_status='available'",(s['documentId'],s['documentVersion'])).fetchone()
            m.require(source and source[1]==s['bodySha256'] and source[2]==m.aware(s['publishedAt']),'selected_source_changed')
            m.require('openai' in s['recipients'],'selected_model_recipient_denied')
            m.require(grants.evaluate(registry.current(s['grantId']),source_id=source[0],revision=s['grantRevision'],purposes=['briefing-outlook','semantic-verification'],recipients=s['recipients']) is None,'selected_rights_changed')


def process(conn,cfg,job_id):
    from psycopg.types.json import Jsonb
    row=conn.execute("SELECT request_snapshot,request_sha256,status,retry_of FROM briefing_selected_generation_jobs WHERE id=%s",(job_id,)).fetchone()
    if not row or row[2]!='running':return
    snapshot=row[0];validate_snapshot(snapshot);current_authority(conn,cfg,snapshot,job_id)
    locks=[];targets=[]
    try:
        for f in sorted(snapshot['inputs'],key=lambda f:f['inputSha256']):
            lock=int(f['inputSha256'][:15],16)
            if not conn.execute('SELECT pg_try_advisory_lock(%s)',(lock,)).fetchone()[0]:
                conn.execute("UPDATE briefing_selected_generation_jobs SET status='queued' WHERE id=%s AND status='running'",(job_id,));return
            locks.append(lock)
            cached=conn.execute("SELECT 1 FROM briefing_shared_issue_analyses WHERE round_id=%s AND issue_id=%s AND input_sha256=%s",(f['roundId'],f['issueId'],f['inputSha256'])).fetchone()
            if not cached:targets.append(f)
        out=Path(cfg['work'])/job_id;b.private_dir(out);b.write_once(out/'request-snapshot.json',b.canonical(snapshot))
        client=m.company.context.legacy.MarketSummaryClient(out,BudgetTransport(cfg,conn,job_id,lambda:current_authority(conn,cfg,snapshot,job_id)),4,prompt_root=m.PROMPTS)
        initial_repair=None
        if row[3] and targets:
            previous=b.strict_load(b.regular(Path(cfg['work'])/row[3]/'attempts.json'));ids={f['issueId'] for f in targets}
            prior_draft={};prior_checks={}
            for attempt in previous:
                prior_draft.update({i:d for i,d in attempt['draft']['issues'].items() if i in ids})
                prior_checks.update({i:d for i,d in attempt['verification']['checks'].items() if i in ids})
            initial_repair={'draft':{'issues':prior_draft},'verification':{'checks':prior_checks},
                'instruction':'사실·사업 판단·전망을 보존하고 지적된 누락만 고친다. outlook에서 가격이 available이면 전일 종가 관측과, news.status=observed인 경우 그 관측도 함께 구분한다. 기사 직전 봉 시각과 기사 발행 시각을 같은 것으로 부르지 말고 before.observedAt부터 latest.observedAt까지의 정확한 기준·가격·변동률을 명시한다. 주가 변동의 원인으로 뉴스를 단정하지 않는다.',
                'priceRequirements':[{ 'issueId':f['issueId'],'targets':[{'companyId':t['companyId'],'observedMovement':t['observedMovement']} for t in f['targets']]} for f in targets]}
        drafted,checked,attempts=m.analyze(client,targets,initial_repair=initial_repair) if targets else ({'issues':{}},{'checks':{}},[])
        b.write_once(out/'attempts.json',b.canonical(attempts));calls=view.verified_calls(out);passed=[];withheld=[]
        for f in targets:
            iid=f['issueId']
            if not checked['checks'][iid]['supported']:
                withheld.append({'issueId':iid,'reason':checked['checks'][iid]['reason']});continue
            record={**{k:f[k] for k in ('roundId','date','edition','cutoff','issueId')},'status':'PASS','frozen':f,'draft':drafted['issues'][iid],'verification':checked['checks'][iid]}
            record['resultVersion']=m.VERSION+'-'+b.digest(b.canonical(record));proof=prove(record,calls);generated=b.now()
            rendered=materialize(record,snapshot['selection']['presentation']['metadata'],generated);receipts=[]
            for key in [proof['generationRequestDigest'],proof['verificationRequestDigest']]:
                request=b.regular(out/'calls'/(key+'.request.json'));response=b.regular(out/'calls'/(key+'.response.json'))
                receipts.append({'request':request.decode(),'response':response.decode(),'requestSha256':b.digest(request),'responseSha256':b.digest(response)})
            current_authority(conn,cfg,snapshot,job_id)
            conn.execute("INSERT INTO briefing_shared_issue_analyses(result_version,round_id,issue_id,input_sha256,input_snapshot,result_record,view,view_sha256,provider_proof) VALUES (%s,%s,%s,%s,%s,%s,%s,encode(sha256(convert_to((%s::jsonb)::text,'UTF8')),'hex'),%s) ON CONFLICT DO NOTHING",(record['resultVersion'],f['roundId'],iid,f['inputSha256'],Jsonb(f),Jsonb(record),Jsonb(rendered),Jsonb(rendered),Jsonb(receipts)))
            b.write_once(out/(iid+'.verified.json'),b.canonical({'record':record,'proof':proof,'view':rendered}));passed.append(iid)
        status='ready' if not withheld else 'partial' if passed or len(snapshot['selectedIssueIds'])>len(snapshot['inputs']) else 'withheld'
        outcome={'passedIssueIds':passed,'withheld':withheld,'newCalls':len(client.new_calls),'reusedCalls':len(client.reused_calls),'model':b.MODEL,'verificationMode':'separate_request_same_model'}
        conn.execute("UPDATE briefing_selected_generation_jobs SET status=%s,outcome=%s,finished_at=now() WHERE id=%s AND status='running'",(status,Jsonb(outcome),job_id))
        print(json.dumps({'jobId':job_id,'status':status,'passed':len(passed),'withheld':len(withheld),'newCalls':len(client.new_calls)}),flush=True)
    finally:
        for key in locks:conn.execute('SELECT pg_advisory_unlock(%s)',(key,))


def work_once(cfg):
    import psycopg
    with psycopg.connect(cfg['dsn'],autocommit=True) as conn:
        with conn.transaction():
            row=conn.execute("SELECT j.id FROM briefing_selected_generation_jobs j JOIN members m ON m.id=j.member_id WHERE j.status='queued' AND m.status='active' ORDER BY j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1").fetchone()
            if not row:return False
            job_id=row[0];conn.execute("UPDATE briefing_selected_generation_jobs SET status='running' WHERE id=%s",(job_id,))
        try:process(conn,cfg,job_id)
        except Exception as e:
            text=str(e);status='budget_exhausted' if 'budget' in text else 'requires_recovery' if any(s in text for s in ['unknown','automatic_retry','transport']) else 'failed'
            conn.execute("UPDATE briefing_selected_generation_jobs SET status=%s,outcome=%s,finished_at=now() WHERE id=%s AND status='running'",(status,Jsonb({'reason':status,'errorType':type(e).__name__}),job_id))
            print(json.dumps({'jobId':job_id,'status':status,'errorType':type(e).__name__}),flush=True)
        return True


def load_config(path):
    m.require(path.stat().st_mode&0o077==0,'private_worker_config');cfg=b.strict_load(b.regular(path))
    approval_path=Path(cfg['authorizationFile'])
    m.require(approval_path.stat().st_mode&0o077==0,'private_authorization_file')
    approval=b.strict_load(b.regular(approval_path))
    m.require(approval['task']==cfg['task'] and approval['model']==b.MODEL
        and 1<=cfg['maxNewCalls']<=min(32,approval['maximumNewCalls'])
        and cfg['maxAggregateCalls']<=approval['maximumAggregateCalls']
        and Decimal(cfg['maxUsd'])<=Decimal(approval['maximumAggregateUsd']),'explicit_authorization_bound')
    target=urlsplit(cfg['dsn'])
    m.require(target.scheme=='postgresql' and target.hostname=='127.0.0.1' and not target.query and bool(re.fullmatch(r'/[a-z0-9_]*briefing_replay[a-z0-9_]*',target.path)),'local_worker_database')
    return cfg


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--once',action='store_true');args=p.parse_args()
    cfg=load_config(args.config)
    while True:
        found=work_once(cfg)
        if args.once:return
        if not found:time.sleep(2)
if __name__=='__main__':main()
