#!/usr/bin/env python3
"""Cutoff-bound company outlooks; preserve news, market summaries and paid history."""
import argparse
import copy
import importlib.util
import os
from pathlib import Path
spec=importlib.util.spec_from_file_location('_company_context',Path(__file__).with_name('briefing_market_context.py'))
context=importlib.util.module_from_spec(spec);spec.loader.exec_module(context)
base=context.base
VERSION='company-outlook-v1'
PROMPTS=context.PROMPTS.with_name(VERSION)
SCHEMA='zoop-company-outlooks-v1'


def require(ok,reason):
    if not ok: raise ValueError('company_outlook_'+reason)


def obj(props):
    return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}


def statement(ids):
    return obj({'text':{'type':'string','minLength':1,'maxLength':420},'evidenceIds':{
        'type':'array','items':{'type':'string','enum':ids},'minItems':1,'maxItems':6}})


def generation_schema(frozen):
    ids=sorted(frozen['sources']);s=statement(ids)
    cmp=copy.deepcopy(s);cmp['properties'].update(status={'type':'string','enum':['updated','compared','unavailable']},previousResultVersion={'type':['string','null']});cmp['required']=list(cmp['properties'])
    item=obj({'companyId':{'type':'string','enum':[t['companyId'] for t in frozen['targets']]},
        'assessment':{'type':'string','enum':['positive','negative','mixed','watch']},'impact':s,'outlook':s,
        'conditions':{'type':'array','items':s,'minItems':1,'maxItems':3},'risks':{'type':'array','items':s,'minItems':1,'maxItems':3},'comparison':cmp})
    return obj({'companies':{'type':'array','items':item,'minItems':len(frozen['targets']),'maxItems':len(frozen['targets'])}})


def previous_for(company,date,edition,history):
    for row in reversed(history):
        if row['status']!='PASS' or (edition=='evening' and (row['date']!=date or row['edition']!='morning')): continue
        found=next((c for c in row['draft']['companies'] if c['companyId']==company),None)
        if found: return {'status':'available','roundId':row['roundId'],'cutoff':row['cutoff'],'resultVersion':row['resultVersion'],'judgment':found}
    return {'status':'unavailable','reason':'same_day_morning_company_judgment_missing' if edition=='evening' else 'previous_company_judgment_missing'}


def freeze(row,effective,metadata,history):
    broad=row['marketEnrichment']['marketContext'];cutoff=context.legacy._aware(broad['window']['to'])
    selected={i['issueId']:i for i in effective['selected']};targets={};sources={}
    for item in effective['result']['items']:
        issue=selected[item['issueId']]
        companies=[{'id':c['companyId'],'name':c['name']} for c in issue['companyLinks']]
        for company in companies:
            cid,name=company['id'],company['name']
            target=targets.setdefault(cid,{'companyId':cid,'companyName':name,'issueIds':[],'facts':[],'sourceIds':[],
                'previous':previous_for(cid,row['date'],row['edition'],history),
                'observedMovement':{'status':'unavailable','reason':'cutoff_bound_company_price_feed_missing'}})
            target['issueIds'].append(item['issueId']);target['facts'].extend({'text':c['text'],'evidenceIds':c['evidenceIds']} for c in item['claims'])
            own=list(issue['sources']);docs=[d for d in broad['documents'] if set(d['companyNames']) & ({name,'Alphabet'} if cid=='NASDAQ:GOOGL' else {name})]
            docs.sort(key=lambda d:(any(x in metadata[d['documentId']]['url'] for x in ('news.samsung','samsung.com','nvidia.com','investor','ir.','news.skhynix','tsmc.com','abc.xyz')),d['sources'][0]['publishedAt']),reverse=True)
            for d in docs[:8]: own.extend(d['sources'])
            for s in own:
                doc=metadata[s['documentId']]
                published=s.get('publishedAt') or next(d['sources'][0]['publishedAt'] for d in broad['documents'] if d['documentId']==s['documentId'])
                require(context.legacy._aware(published)<=cutoff,'future_source')
                sid=s['evidenceId'];value={'evidenceId':sid,'documentId':s['documentId'],'documentVersion':'sha256-'+s['bodySha256'],
                    'bodySha256':s['bodySha256'],'quote':s['quote'],'publishedAt':published,'title':doc['title'],'url':doc['url']}
                if sid in sources: require(sources[sid]==value,'source_conflict')
                sources[sid]=value
                if sid not in target['sourceIds']: target['sourceIds'].append(sid)
    require(targets,'empty_targets')
    return {'schemaVersion':SCHEMA,'roundId':row['roundId'],'date':row['date'],'edition':row['edition'],'cutoff':broad['window']['to'],
        'newsResultSha256':effective['resultSha256'],'targets':list(targets.values()),'sources':sources,'promptVersion':VERSION,
        'scopeNote':'원발행 시각 기준 과거 시뮬레이션입니다. 기업 사업 영향의 조건부 해석이며 주가·목표가 예측이 아닙니다. 당시 수집·본문 동일성은 입증하지 않습니다.'}


def validate(draft,frozen):
    base.validate_schema(draft,generation_schema(frozen));expected={t['companyId']:t for t in frozen['targets']}
    require(len({c['companyId'] for c in draft['companies']})==len(expected),'company_coverage')
    for c in draft['companies']:
        t=expected[c['companyId']]
        for s in [c['impact'],c['outlook'],*c['conditions'],*c['risks'],c['comparison']]:
            require(set(s['evidenceIds'])<=set(t['sourceIds']) and len(set(s['evidenceIds']))==len(s['evidenceIds']),'foreign_company_evidence')
        prev=t['previous'];cmp=c['comparison'];require(cmp['previousResultVersion']==prev.get('resultVersion'),'previous_version')
        require(cmp['status']==('unavailable' if prev['status']=='unavailable' else 'updated' if frozen['edition']=='morning' else 'compared'),'comparison_status')


def verification_schema(frozen):
    item=obj({'companyId':{'type':'string','enum':[t['companyId'] for t in frozen['targets']]},'supported':{'type':'boolean'},'reason':{'type':'string','minLength':1,'maxLength':700}})
    return obj({'checks':{'type':'array','items':item,'minItems':len(frozen['targets']),'maxItems':len(frozen['targets'])}})


def assess(client,frozen,initial_repair=None):
    attempts=[]
    for attempt in range(2):
        data={'frozen':frozen,'repair':attempts[-1] if attempts else initial_repair};schema=generation_schema(frozen)
        digest=client.request_digest('company_outlook_generation',data,'generation.md','unused',8000,schema)
        draft=client.call('company_outlook_generation',data,'generation.md','unused',8000,schema)
        try: validate(draft,frozen);error=None
        except (ValueError,base.ReplayError) as exc: error=str(exc)
        if error:
            attempts.append({'draft':draft,'generationRequestDigest':digest,'error':error});continue
        vd={'frozen':frozen,'draft':draft};vs=verification_schema(frozen)
        verify_digest=client.request_digest('company_outlook_verification',vd,'verification.md','unused',8000,vs)
        verified=client.call('company_outlook_verification',vd,'verification.md','unused',8000,vs)
        require({c['companyId'] for c in verified['checks']}=={t['companyId'] for t in frozen['targets']}
            and len({c['companyId'] for c in verified['checks']})==len(verified['checks']),'verification_coverage')
        record={'draft':draft,'generationRequestDigest':digest,'verificationRequestDigest':verify_digest,'verification':verified};attempts.append(record)
        if all(c['supported'] for c in verified['checks']): return {'status':'PASS','draft':draft,'attempts':attempts,'generationRequestDigest':digest,'verificationRequestDigest':verify_digest}
    return {'status':'WITHHELD','draft':None,'attempts':attempts}


def _run(args,transport=None):
    baseline=Path(args.baseline).resolve();output=Path(args.output).resolve()
    require(output!=baseline and output not in baseline.parents and baseline not in output.parents,'separate_output')
    bundle=base.strict_load(base.regular(baseline/'bundle-v2.json'));metadata={r['documentId']:r for r in (base.strict_load(line) for line in base.regular(Path(args.sources)).decode().splitlines() if line.strip())}
    require(base.digest(base.regular(Path(args.sources)))==bundle['sourceFileSha256'],'source_digest')
    chosen=sorted([r for r in bundle['presentationEnrichment']['rounds'] if r['date'] in args.date],key=lambda r:context.legacy._aware(r['marketEnrichment']['cutoff']))
    require(chosen and len(chosen)<=4,'round_count');prior=len(list((baseline/'calls').glob('*.pending.json')))
    require(prior<args.max_calls<=512,'call_limit')
    old=bundle['presentationEnrichment'].get('companyOutlookLayer')
    old_by_id={r['roundId']:r for r in old['rounds']} if old else {}
    invalidated=False;new_rounds=0
    for row in chosen:
        invalidated=invalidated or old_by_id.get(row['roundId'],{}).get('status')!='PASS'
        new_rounds+=int(invalidated)
    plan={'priorReservations':prior,'minimumNewCalls':2*new_rounds,'maximumNewCalls':min(4*new_rounds,args.max_calls-prior),'maximumTotalCalls':args.max_calls,'roundIds':[r['roundId'] for r in chosen]}
    if not args.execute: return {**plan,'status':'OFFLINE','newPaidCalls':0}
    if (output/'company-proof.json').exists():
        proof=base.strict_load(base.regular(output/'company-proof.json'));require(base.digest(base.regular(output/'bundle-v2.json'))==proof['bundleSha256'],'completed_bundle_changed');return {**proof,'newPaidCalls':0,'reusedCompletedRun':True}
    require(plan['minimumNewCalls']<=args.max_calls-prior,'call_limit')
    require(not old or len(old.get('previousRuns',[]))<2 or new_rounds==0,'history_limit')
    require(args.authorization_ref and (args.key_file or transport),'authorization');base.private_dir(output)
    for file in sorted(baseline.rglob('*')):
        if file.is_file() and file.name not in {'bundle-v2.json','company-plan.json','company-proof.json'} and 'company-rounds' not in file.relative_to(baseline).parts:
            target=output/file.relative_to(baseline);base.private_dir(target.parent)
            if not target.exists(): os.link(file,target)
    base.write_once(output/('company-plan-'+base.digest(base.canonical(plan))+'.json'),base.canonical(plan))
    for file in PROMPTS.iterdir():
        base.private_dir(output/'company-prompts');base.write_once(output/'company-prompts'/file.name,base.regular(file))
    client=context.legacy.MarketSummaryClient(output,transport or base.authenticated_transport(Path(args.key_file),timeout=600),args.max_calls,prompt_root=output/'company-prompts')
    recovery={r['roundId']:r for r in bundle['briefingRecovery']['rounds']};completed=[]
    old_layer=bundle['presentationEnrichment'].get('companyOutlookLayer');old_rows={r['roundId']:r for r in old_layer['rounds']} if old_layer else {}
    for row in chosen:
        frozen=freeze(row,recovery[row['roundId']],metadata,completed)
        finished=output/'company-rounds'/(row['roundId']+'.json')
        if finished.exists():
            saved=base.strict_load(base.regular(finished));require(saved['frozen']==frozen,'resume_frozen_changed');completed.append(saved);continue
        previous=old_rows.get(row['roundId'])
        if previous and previous['status']=='PASS' and previous['frozen']==frozen:
            completed.append(previous);continue
        result=assess(client,frozen,previous['attempts'][-1] if previous and previous['status']=='WITHHELD' else None)
        result.update(roundId=row['roundId'],date=row['date'],edition=row['edition'],cutoff=frozen['cutoff'],frozen=frozen,generatedAt=base.now(),resultVersion='company-v1-'+base.digest(base.canonical(result)))
        completed.append(result);base.private_dir(output/'company-rounds');base.write_once(output/'company-rounds'/(row['roundId']+'.json'),base.canonical(result))
        print(base.canonical({'round':row['date']+'-'+row['edition'],'status':result['status'],'companies':len(frozen['targets']),'newCalls':len(client.new_calls)}).decode(),flush=True)
    layer=bundle['presentationEnrichment'];layer['runId']=args.run_id;layer['maximumPaidCallsIncludingPrior']=args.max_calls
    owned={a[d] for r in completed for a in r['attempts'] for d in ['generationRequestDigest','verificationRequestDigest'] if d in a};owned.update(r['requestDigest'] for r in old_layer['receipts']) if old_layer else None;receipts=[r for r in client.receipts() if r['requestDigest'] in owned]
    layer['companyOutlookLayer']={'schemaVersion':SCHEMA,'authorizationRef':args.authorization_ref,'rounds':completed,'receipts':receipts}
    if old_layer:
        prior_layer=copy.deepcopy(old_layer);prior_runs=prior_layer.pop('previousRuns',[]);require(len(prior_runs)<2,'history_limit');layer['companyOutlookLayer']['previousRuns']=[*prior_runs,prior_layer]
    base.write_once(output/'bundle-v2.json',base.canonical(bundle))
    proof={**plan,'status':'COMPLETE','pass':sum(r['status']=='PASS' for r in completed),'newPaidCalls':len(client.new_calls),'totalReservations':len(list(client.calls.glob('*.pending.json'))),'bundleSha256':base.digest(base.regular(output/'bundle-v2.json')),
        'inputTokens':sum(r['inputTokens'] for r in receipts if r['usageKnown'] and r['requestDigest'] in client.new_calls),'outputTokens':sum(r['outputTokens'] for r in receipts if r['usageKnown'] and r['requestDigest'] in client.new_calls),'newUsageKnown':all(r['usageKnown'] for r in receipts)}
    base.write_once(output/'company-proof.json',base.canonical(proof));return proof


def run(args,transport=None):
    if not args.execute: return _run(args,transport)
    output=Path(args.output).resolve();baseline=Path(args.baseline).resolve()
    require(output!=baseline and baseline not in output.parents and output not in baseline.parents,'separate_output')
    base.private_dir(output);lock=output/'.company-execution.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try: return _run(args,transport)
    finally: lock.unlink(missing_ok=True)


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ['baseline','sources','output','authorization-ref','run-id']: p.add_argument('--'+flag,required=True)
    p.add_argument('--date',action='append',required=True);p.add_argument('--max-calls',type=int,default=400);p.add_argument('--key-file');p.add_argument('--execute',action='store_true');return p


if __name__=='__main__': print(base.canonical(run(parser().parse_args())).decode(),flush=True)
