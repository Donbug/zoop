#!/usr/bin/env python3
"""Cutoff-bound company outlooks; preserve news, market summaries and paid history."""
import argparse
import copy
import importlib.util
import os
from datetime import date, timedelta
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
    statuses = ['updated','compared','unavailable']
    if frozen.get('comparisonContract') is not None:
        require(frozen['comparisonContract'] in ('edition-bound-v2','issue-company-v1'),'comparison_contract')
        statuses = ['updated','unavailable'] if frozen['edition']=='morning' else ['compared','unavailable']
    cmp=copy.deepcopy(s);cmp['properties'].update(status={'type':'string','enum':statuses},previousResultVersion={'type':['string','null']});cmp['required']=list(cmp['properties'])
    item=obj({'companyId':{'type':'string','enum':[t['companyId'] for t in frozen['targets']]},
        'assessment':{'type':'string','enum':['positive','negative','mixed','watch']},'impact':s,'outlook':s,
        'conditions':{'type':'array','items':s,'minItems':1,'maxItems':3},'risks':{'type':'array','items':s,'minItems':1,'maxItems':3},'comparison':cmp})
    return obj({'companies':{'type':'array','items':item,'minItems':len(frozen['targets']),'maxItems':len(frozen['targets'])}})


def previous_for(company,date_value,edition,history,strict=False,issue_id=None,cutoff=None):
    if issue_id is not None:
        return previous_issue_company(company, issue_id, date_value, edition, cutoff, history)
    for row in reversed(history):
        if row['status']!='PASS' or (edition=='evening' and (row['date']!=date_value or row['edition']!='morning')): continue
        if strict and edition == 'morning' and (row['edition'] != 'evening' or row['date'] != (date.fromisoformat(date_value)-timedelta(days=1)).isoformat()): continue
        found=next((c for c in row['draft']['companies'] if c['companyId']==company),None)
        if found: return {'status':'available','roundId':row['roundId'],'cutoff':row['cutoff'],'resultVersion':row['resultVersion'],'judgment':found}
    return {'status':'unavailable','reason':'same_day_morning_company_judgment_missing' if edition=='evening' else 'previous_company_judgment_missing'}


def previous_issue_company(company, issue_id, date_value, edition, cutoff, history):
    """Resolve the corresponding publication first, then the event/company pair.

    Never search backwards for a convenient old judgment when that pair is
    missing from the immediately corresponding publication. Stable archive IDs
    provide continuity; similar company names/titles do not create aliases.
    """
    boundary = context.legacy._aware(cutoff)
    eligible = [r for r in history if r.get('status') == 'PASS'
        and context.legacy._aware(r['cutoff']) < boundary
        and ((edition == 'evening' and r['date'] == date_value and r['edition'] == 'morning')
             or (edition == 'morning' and r['date'] < date_value and r['edition'] == 'evening'))]
    if not eligible:
        return {'status': 'unavailable', 'reason': 'corresponding_round_missing'}
    latest = max(context.legacy._aware(r['cutoff']) for r in eligible)
    eligible = [r for r in eligible if context.legacy._aware(r['cutoff']) == latest]
    matches = []
    for row in eligible:
        targets = row.get('frozen', {}).get('targets', [])
        target = next((t for t in targets if t['companyId'] == company and t.get('issueIds') == [issue_id]), None)
        judgment = next((c for c in row['draft']['companies'] if c['companyId'] == company), None)
        if target and judgment:
            matches.append((row, judgment))
    if len(matches) != 1:
        return {'status': 'unavailable', 'reason': 'same_issue_company_judgment_missing_or_ambiguous'}
    row, judgment = matches[0]
    return {'status': 'available', 'issueId': issue_id, 'companyId': company,
        'roundId': row['roundId'], 'date': row['date'], 'edition': row['edition'],
        'cutoff': row['cutoff'], 'resultVersion': row['resultVersion'], 'judgment': copy.deepcopy(judgment)}


def freeze_issue_inputs(row, effective, metadata, history, version=VERSION):
    """One generation input per issue; the same company can occur in many inputs.
    Preparation is offline. No existing AI receipt is upgraded to a new verdict.
    """
    return [freeze(row, effective, metadata, history, version, issue_id=item['issueId'])
            for item in effective['result']['items']]


def freeze(row,effective,metadata,history,version=VERSION,issue_id=None):
    market=row['marketEnrichment']
    # Extractive presentation replays have verified selected evidence but no
    # generated broad-market context. Do not invent background documents.
    broad=market['marketContext'] if 'marketContext' in market else {'window':{'to':market['cutoff']},'documents':[]}
    cutoff=context.legacy._aware(broad['window']['to'])
    selected={i['issueId']:i for i in effective['selected']};targets={};sources={}
    for item in effective['result']['items']:
        if issue_id is not None and item['issueId'] != issue_id: continue
        issue=selected[item['issueId']]
        companies=[{'id':c['companyId'],'name':c['name']} for c in issue['companyLinks']]
        for company in companies:
            cid,name=company['id'],company['name']
            target=targets.setdefault(cid,{'companyId':cid,'companyName':name,'issueIds':[],'facts':[],'sourceIds':[],
                'previous':previous_for(cid,row['date'],row['edition'],history,strict=version in ('company-outlook-v3','company-outlook-v4'), issue_id=issue_id, cutoff=broad['window']['to']),
                'observedMovement':{'status':'unavailable','reason':'cutoff_bound_company_price_feed_missing'}})
            target['issueIds'].append(item['issueId']);target['facts'].extend({'text':c['text'],'evidenceIds':c['evidenceIds']} for c in item['claims'])
            own=list(issue['sources']);docs=[d for d in broad['documents'] if set(d['companyNames']) & ({name,'Alphabet'} if cid=='NASDAQ:GOOGL' else {name})]
            docs.sort(key=lambda d:(any(x in metadata[d['documentId']]['url'] for x in ('news.samsung','samsung.com','nvidia.com','investor','ir.','news.skhynix','tsmc.com','abc.xyz')),d['sources'][0]['publishedAt']),reverse=True)
            for d in docs[:8]: own.extend(d['sources'])
            if issue_id is not None:
                target['issueEvidenceIds'] = [s['evidenceId'] for s in issue['sources']]
                foreign = {s['evidenceId'] for other_id, other in selected.items() if other_id != issue_id for s in other['sources']} - set(target['issueEvidenceIds'])
                own = [s for s in own if s['evidenceId'] not in foreign]
            for s in own:
                doc=metadata[s['documentId']]
                published=(s.get('publishedAt') or s.get('publicationClock',{}).get('publishedAt')
                           or s.get('dateContext',{}).get('publishedAt')
                           or next(d['sources'][0]['publishedAt'] for d in broad['documents'] if d['documentId']==s['documentId']))
                require(context.legacy._aware(published)<=cutoff,'future_source')
                sid=s['evidenceId'];value={'evidenceId':sid,'documentId':s['documentId'],'documentVersion':'sha256-'+s['bodySha256'],
                    'bodySha256':s['bodySha256'],'quote':s['quote'],'publishedAt':published,'title':doc['title'],'url':doc['url']}
                if sid in sources: require(sources[sid]==value,'source_conflict')
                sources[sid]=value
                if sid not in target['sourceIds']: target['sourceIds'].append(sid)
    require(targets,'empty_targets')
    frozen={'schemaVersion':SCHEMA,'roundId':row['roundId'],'date':row['date'],'edition':row['edition'],'cutoff':broad['window']['to'],
        'newsResultSha256':effective['resultSha256'],'targets':list(targets.values()),'sources':sources,'promptVersion':version,
        'scopeNote':'원발행 시각 기준 과거 시뮬레이션입니다. 기업 사업 영향의 조건부 해석이며 주가·목표가 예측이 아닙니다. 당시 수집·본문 동일성은 입증하지 않습니다.'}
    if version in ('company-outlook-v2','company-outlook-v3','company-outlook-v4'):frozen['comparisonContract']='edition-bound-v2'
    if issue_id is not None:
        frozen.update(issueId=issue_id, comparisonContract='issue-company-v1',
            scopeRule='Interpret only this event and its cited company links. Previous company-wide judgments about other events are not comparable.')
    return frozen


def validate(draft,frozen):
    base.validate_schema(draft,generation_schema(frozen));expected={t['companyId']:t for t in frozen['targets']}
    require(len({c['companyId'] for c in draft['companies']})==len(expected),'company_coverage')
    for c in draft['companies']:
        t=expected[c['companyId']]
        for s in [c['impact'],c['outlook'],*c['conditions'],*c['risks'],c['comparison']]:
            require(set(s['evidenceIds'])<=set(t['sourceIds']) and len(set(s['evidenceIds']))==len(s['evidenceIds']),'foreign_company_evidence')
        prev=t['previous'];cmp=c['comparison'];
        if frozen.get('comparisonContract') == 'issue-company-v1':
            require(t['issueIds'] == [frozen['issueId']], 'issue_scope')
            own = set(t['issueEvidenceIds'])
            require(own and own <= set(t['sourceIds']), 'issue_evidence_scope')
            require(all(set(s['evidenceIds']) & own for s in [c['impact'], c['outlook'], c['comparison'], *c['conditions'], *c['risks']]), 'issue_anchor_missing')
            if prev['status'] == 'available':
                require(prev.get('issueId') == frozen['issueId'] and prev.get('companyId') == c['companyId']
                    and context.legacy._aware(prev['cutoff']) < context.legacy._aware(frozen['cutoff'])
                    and (prev.get('date') == frozen['date'] and prev.get('edition') == 'morning' if frozen['edition'] == 'evening'
                         else prev.get('date', '9999') < frozen['date'] and prev.get('edition') == 'evening'), 'previous_issue_scope')
        require(cmp['previousResultVersion']==prev.get('resultVersion'),'previous_version')
        require(cmp['status']==('unavailable' if prev['status']=='unavailable' else 'updated' if frozen['edition']=='morning' else 'compared'),'comparison_status')


def verification_schema(frozen):
    item=obj({'companyId':{'type':'string','enum':[t['companyId'] for t in frozen['targets']]},'supported':{'type':'boolean'},'reason':{'type':'string','minLength':1,'maxLength':700}})
    return obj({'checks':{'type':'array','items':item,'minItems':len(frozen['targets']),'maxItems':len(frozen['targets'])}})


def assess(client,frozen,initial_repair=None):
    attempts=[]
    for attempt in range(2):
        if getattr(client, 'usage', None) is not None: client.usage.retry(attempt)
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


def execution_identity(args, baseline_raw, sources_raw, chosen):
    version=getattr(args,'prompt_version',VERSION)
    prompts=PROMPTS if version==VERSION else PROMPTS.with_name(version)
    return {'baselineSha256':base.digest(baseline_raw),'sourcesSha256':base.digest(sources_raw),
        'dates':sorted(set(args.date)),'roundIds':[r['roundId'] for r in chosen],
        'promptArtifacts':{p.name:base.digest(base.regular(p)) for p in sorted(prompts.iterdir()) if p.is_file()},
        'model':base.MODEL,'maximumPaidCalls':args.max_calls,'runId':args.run_id,'authorizationRef':args.authorization_ref}


def company_plan(chosen, all_rows, old_rows, recovery, metadata, version=VERSION):
    selected={r['roundId'] for r in chosen};by_id={r['roundId']:r for r in all_rows}
    require(set(old_rows)<=set(by_id),'prior_round_missing_from_news')
    timeline=sorted([r for r in all_rows if r['roundId'] in selected or r['roundId'] in old_rows],
                    key=lambda r:context.legacy._aware(r['marketEnrichment']['cutoff']))
    require(len(timeline)<=4,'round_count')
    history=[];changed=None
    for row in timeline:
        old=old_rows.get(row['roundId'])
        frozen=(freeze(row,recovery[row['roundId']],metadata,history) if version==VERSION
                else freeze(row,recovery[row['roundId']],metadata,history,version))
        if row['roundId'] not in selected:
            require(old is not None and old['frozen']==frozen,'preserved_round_input_changed')
        if row['roundId'] in selected and (not old or old['status']!='PASS' or old['frozen']!=frozen):
            changed=changed or frozen['cutoff']
        if old: history.append(old)
    if changed:
        boundary=context.legacy._aware(changed)
        require(all(r['roundId'] in selected for r in timeline if r['roundId'] in old_rows
                    and context.legacy._aware(r['marketEnrichment']['cutoff'])>boundary),
                'dependent_rounds_must_be_selected_before_execution')
    new_rounds=sum(r['roundId'] in selected and changed is not None and
                  context.legacy._aware(r['marketEnrichment']['cutoff'])>=context.legacy._aware(changed) for r in timeline)
    return timeline,new_rounds


def _run(args,transport=None):
    version=getattr(args,'prompt_version',VERSION)
    prompts=PROMPTS if version==VERSION else PROMPTS.with_name(version)
    baseline=Path(args.baseline).resolve();output=Path(args.output).resolve()
    require(output!=baseline and output not in baseline.parents and baseline not in output.parents,'separate_output')
    raw=base.regular(baseline/'bundle-v2.json');bundle=base.strict_load(raw)
    sources_raw=base.regular(Path(args.sources));metadata={r['documentId']:r for r in
        (base.strict_load(line) for line in sources_raw.decode().splitlines() if line.strip())}
    require(base.digest(sources_raw)==bundle['sourceFileSha256'],'source_digest')
    all_rows=bundle['presentationEnrichment']['rounds']
    chosen=sorted([r for r in all_rows if r['date'] in args.date],key=lambda r:context.legacy._aware(r['marketEnrichment']['cutoff']))
    require(chosen and len(chosen)<=4,'round_count')
    require(set(args.date)=={r['date'] for r in chosen},'requested_date_missing')
    identity=execution_identity(args,raw,sources_raw,chosen)
    if args.execute and (output/'company-proof.json').exists():
        require((output/'company-execution.json').exists(),'completed_identity_missing_use_new_output')
        require(base.strict_load(base.regular(output/'company-execution.json'))==identity,'completed_request_identity_changed')
        proof=base.strict_load(base.regular(output/'company-proof.json'))
        require(base.digest(base.regular(output/'bundle-v2.json'))==proof['bundleSha256'],'completed_bundle_changed')
        return {**proof,'newPaidCalls':0,'reusedCompletedRun':True}
    prior=len(list((baseline/'calls').glob('*.pending.json')));require(prior<=args.max_calls<=512,'call_limit')
    old_layer=bundle['presentationEnrichment'].get('companyOutlookLayer')
    old_rows={r['roundId']:r for r in old_layer['rounds']} if old_layer else {}
    recovery={r['roundId']:r for r in bundle['briefingRecovery']['rounds']}
    timeline,new_rounds=company_plan(chosen,all_rows,old_rows,recovery,metadata,version)
    plan={**identity,'priorReservations':prior,'minimumNewCalls':2*new_rounds,
          'maximumNewCalls':min(4*new_rounds,args.max_calls-prior),'maximumTotalCalls':args.max_calls}
    require(not new_rounds or 'companyReadingLayer' not in bundle['presentationEnrichment'],
            'downstream_company_reading_requires_separate_rebuild')
    if not args.execute: return {**plan,'status':'OFFLINE','newPaidCalls':0}
    require(plan['minimumNewCalls']<=args.max_calls-prior,'call_limit')
    require(not new_rounds or not old_layer or len(old_layer.get('previousRuns',[]))<2,'history_limit')
    require(args.authorization_ref and (new_rounds==0 or args.key_file or transport),'authorization')
    base.private_dir(output);base.write_once(output/'company-execution.json',base.canonical(identity))
    for file in sorted(baseline.rglob('*')):
        if file.is_file() and file.name not in {'bundle-v2.json','company-plan.json','company-proof.json','company-execution.json'} and 'company-rounds' not in file.relative_to(baseline).parts:
            target=output/file.relative_to(baseline);base.private_dir(target.parent)
            if not target.exists(): os.link(file,target)
    base.write_once(output/('company-plan-'+base.digest(base.canonical(plan))+'.json'),base.canonical(plan))
    active_prompts=output/'company-prompts'/version
    base.private_dir(active_prompts)
    for file in prompts.iterdir():
        base.write_once(active_prompts/file.name,base.regular(file))
    def cache_only(_): raise base.ReplayError('company_cache_only_request_not_completed')
    send=transport or (base.authenticated_transport(Path(args.key_file),timeout=600) if new_rounds else cache_only)
    client=context.legacy.MarketSummaryClient(output,send,args.max_calls,prompt_root=active_prompts)
    completed=[];selected_ids={r['roundId'] for r in chosen}
    for row in timeline:
        frozen=(freeze(row,recovery[row['roundId']],metadata,completed) if version==VERSION
                else freeze(row,recovery[row['roundId']],metadata,completed,version))
        if version in ('company-outlook-v2','company-outlook-v3','company-outlook-v4'):frozen['comparisonContract']='edition-bound-v2'
        finished=output/'company-rounds'/(row['roundId']+'.json');previous=old_rows.get(row['roundId'])
        if finished.exists():
            saved=base.strict_load(base.regular(finished));require(saved['frozen']==frozen,'resume_frozen_changed');completed.append(saved);continue
        if previous and previous['frozen']==frozen and (previous['status']=='PASS' or row['roundId'] not in selected_ids):
            completed.append(previous);continue
        require(row['roundId'] in selected_ids,'dependent_round_not_selected')
        result=assess(client,frozen,previous['attempts'][-1] if previous and previous['status']=='WITHHELD' else None)
        result.update(roundId=row['roundId'],date=row['date'],edition=row['edition'],cutoff=frozen['cutoff'],frozen=frozen,
                      generatedAt=base.now(),resultVersion='company-v1-'+base.digest(base.canonical(result)))
        completed.append(result);base.private_dir(output/'company-rounds')
        base.write_once(finished,base.canonical(result))
        print(base.canonical({'round':row['date']+'-'+row['edition'],'status':result['status'],
                             'companies':len(frozen['targets']),'newCalls':len(client.new_calls)}).decode(),flush=True)
    layer=bundle['presentationEnrichment'];layer['runId']=args.run_id;layer['maximumPaidCallsIncludingPrior']=args.max_calls
    owned={a[d] for r in completed for a in r['attempts'] for d in ['generationRequestDigest','verificationRequestDigest'] if d in a}
    if old_layer: owned.update(r['requestDigest'] for r in old_layer['receipts'])
    receipts=[r for r in client.receipts() if r['requestDigest'] in owned]
    unchanged=old_layer and completed==old_layer['rounds']
    if not unchanged:
        layer['companyOutlookLayer']={'schemaVersion':SCHEMA,'authorizationRef':args.authorization_ref,'rounds':completed,'receipts':receipts}
        if old_layer:
            prior_layer=copy.deepcopy(old_layer);prior_runs=prior_layer.pop('previousRuns',[])
            layer['companyOutlookLayer']['previousRuns']=[*prior_runs,prior_layer]
    base.write_once(output/'bundle-v2.json',base.canonical(bundle))
    proof={**plan,'status':'COMPLETE','pass':sum(r['status']=='PASS' for r in completed),'newPaidCalls':len(client.new_calls),
        'totalReservations':len(list(client.calls.glob('*.pending.json'))),'bundleSha256':base.digest(base.regular(output/'bundle-v2.json')),
        'inputTokens':sum(r['inputTokens'] for r in receipts if r['usageKnown'] and r['requestDigest'] in client.new_calls),
        'outputTokens':sum(r['outputTokens'] for r in receipts if r['usageKnown'] and r['requestDigest'] in client.new_calls),
        'newUsageKnown':all(r['usageKnown'] for r in receipts)}
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
    p.add_argument('--prompt-version',choices=['company-outlook-v1','company-outlook-v2','company-outlook-v3','company-outlook-v4'],default=VERSION)
    p.add_argument('--date',action='append',required=True);p.add_argument('--max-calls',type=int,default=400);p.add_argument('--key-file');p.add_argument('--execute',action='store_true');return p


if __name__=='__main__': print(base.canonical(run(parser().parse_args())).decode(),flush=True)
