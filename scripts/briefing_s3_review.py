"""Opt-in historical S3 impact stage over preserved briefing citations; never rewrite a publication.

Reuses the pipeline impact prompt/schema, Jev verifier and label policy. Existing issue/company
membership is the input, not a claim that native S2/S3 relation extraction was rerun. Input text
is the preserved quote context, not a reconstructed full article or a price forecast.
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.request
from pathlib import Path
from briefing_s3_source import REPO, canonical, sha, now, native_version, once

sys.path.insert(0, str(REPO / 'ai/pipeline/src'))
from zoop_ai_pipeline import relation_rules as rules
from zoop_ai_pipeline.live_runtime import LiveRuntime, LiveFailure
from zoop_ai_pipeline.extraction_contracts import CitationFailure

ROUNDS = [('2026-10-21','evening'),('2026-10-22','morning'),('2026-10-22','evening'),('2026-10-23','morning')]

def get(api, path):
    with urllib.request.urlopen(api + path, timeout=15) as f:
        return json.load(f)

def detail(api, round_id, event_id):
    return get(api, f'/api/v1/briefings/{round_id}/items/{event_id}')

def freeze(api):
    import psycopg
    result=[]
    with psycopg.connect(host='127.0.0.1',port=55437,user='company_test',dbname='zoop_briefing_replay_local_ai_price156_final',options='-c default_transaction_read_only=on') as db:
        for date,edition in ROUNDS:
            r=get(api,f'/api/v1/briefings?date={date}&edition={edition}')
            with db.cursor() as q:
                q.execute('select payload_sha256 from briefing_rounds where id=%s',(r['id'],));publication=q.fetchone()[0]
            for item in r['items']:
                d=detail(api,r['id'],item['eventId'])
                assert set(item['evidenceIds']) == {e['id'] for e in d['evidence']}
                for e in d['evidence']:
                    assert e['quoteVerified'] and e['publishedAt'] and e['publishedAt'] <= r['dataAsOf']
                    context=e.get('bodyContext')
                    if context:
                        assert len(context['text'])==context['end']-context['start']
                        assert context['text'][context['quoteStart']-context['start']:context['quoteEnd']-context['start']]==e['quote']
                basis={'roundId':r['id'],'eventId':item['eventId'],'dataAsOf':r['dataAsOf'],
                       'publicationSha256':publication,'companies':[{'id':c['id'],'name':c['name']} for c in item['companies']],
                       'evidence':d['evidence']}
                result.append({'basis':basis,'title':item['title'],'inputDigest':sha(canonical(basis))})
    return result

def configure(args):
    from dotenv import dotenv_values

    approval=json.loads(args.approval.read_text())
    assert approval['additionalCallsMaximum']==16 and approval['aggregateCallsMaximum']==212
    assert approval['previousCallsReserved']==196 and approval['aggregateUsdMaximum']==3
    a=dotenv_values(args.credentials/'openai.env',interpolate=False)
    j=dotenv_values(args.credentials/'typesafe.env',interpolate=False)
    os.environ.update({'ZOOP_AI_PIPELINE_LIVE_ENABLED':'1','ZOOP_AI_PIPELINE_LIVE_MODEL':'gpt-6-luna',
        'ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT':'high','TYPESAFE_VALIDATION_MODEL':'jev-1.14.0',
        'ZOOP_AI_PIPELINE_LIVE_MAX_OUTPUT_TOKENS':'6000','ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS':'300',
        'ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR':str(args.budget.resolve()),'ZOOP_AI_PIPELINE_LIVE_MAX_CALLS':'16',
        'ZOOP_AI_PIPELINE_LIVE_MAX_USD':str(approval['additionalUsdMaximum']),
        'ZOOP_AI_API_KEY':a['OPENAI_API_KEY'],'TYPESAFE_API_KEY':j['TYPESAFE_API_KEY']})
    return LiveRuntime.from_env(need_send=True),approval

def payload(case, company):
    basis=case['basis'];docs=[];original={}
    for e in basis['evidence']:
        context=e.get('bodyContext');text=context['text'] if context else e['quote']
        docs.append({'documentId':e['documentId'],'documentVersion':e['documentVersion'],'text':text,'title':e['title']})
        original[(e['documentId'],native_version(e['documentVersion']))]=e
    target={'kind':'company','ref':company['id'],'names':[company['name']]}
    facts={'type':'PARTICIPATES_IN','direction':'directed','subject':target,
           'object':{'kind':'event','ref':basis['eventId'],'names':[case['title']]},
           'connection':'direct','businessScope':None,'productScope':None,'validity':{'from':None,'until':None},'countries':[],'path':[]}
    relation={**facts,'facts':facts,'quotes':[{'quoteId':e['id'],'text':e['quote']} for e in basis['evidence']]}
    return rules.impact_request(relation,docs),relation,original

def resolve(c, originals):
    e=originals[(c['documentId'],c['documentVersion'])];context=e.get('bodyContext')
    text=context['text'] if context else e['quote'];quote=c['quote'];start=c.get('start');end=c.get('end')
    if start is None or end is None:
        if not quote or text.count(quote)!=1:raise CitationFailure('quote_ambiguous')
        start=text.index(quote);end=start+len(quote)
    if type(start)!=int or type(end)!=int or start<0 or end<=start or text[start:end]!=quote:
        raise CitationFailure('quote_not_exact')
    return {**c,'start':start,'end':end,'evidenceId':'ev-'+sha(canonical([c['documentId'],c['documentVersion'],start,end,quote]))[:32]}

def normalize_answer(value, originals):
    """Resolve literal unique quotes before strict native parsing; never alter their text or meaning."""
    if isinstance(value,list):return [normalize_answer(x,originals) for x in value]
    if not isinstance(value,dict):return value
    result={k:normalize_answer(v,originals) for k,v in value.items()}
    if {'documentId','documentVersion','quote'}<=result.keys():
        result['documentVersion']=native_version(result['documentVersion'])
        fixed=resolve(result,originals)
        result['start'],result['end']=fixed['start'],fixed['end']
    return result

def send(args,runtime,approval,stage,request,case):
    prepared=runtime.prepare(stage,request);identity=sha(canonical([case['inputDigest'],stage,prepared['requestDigest']]))
    path=args.output/'receipts'/f'{identity}.json'
    if path.is_file():return json.loads(path.read_text()),path
    intent=args.output/'attempts'/f'{identity}.json'
    if intent.exists():raise RuntimeError('unknown_request_never_resent')
    existing=list((args.output/'attempts').glob('*.json')) if (args.output/'attempts').exists() else []
    if len(existing)>=16:raise RuntimeError('additional_16_call_limit')
    # Outer conservative reservation covers both providers and includes old unknown outcomes.
    reserved=(len(canonical(prepared['body']))*.5 + 6000*1.5)/1_000_000
    spent=0.0
    for old in existing:
        v=json.loads(old.read_text());receipt=args.output/'receipts'/old.name
        if receipt.is_file():
            used=runtime.usage(json.loads(receipt.read_text()))
            if isinstance(used.get('inputTokens'),int) and isinstance(used.get('outputTokens'),int):
                spent+=(used['inputTokens']*.5+used['outputTokens']*1.5)/1_000_000
            else:spent+=v['reservedUpperUsd']
        else:spent+=v['reservedUpperUsd']
    if approval['previousChargedUpperUsd']+spent+reserved>3:raise RuntimeError('aggregate_3_usd_limit')
    once(intent,{'stage':stage,'requestDigest':prepared['requestDigest'],'reservedUpperUsd':reserved,'startedAt':now()})
    once(args.output/'requests'/f'{identity}.json',prepared)
    def authorize():
        current=detail(args.api,case['basis']['roundId'],case['basis']['eventId'])
        if current['evidence']!=case['basis']['evidence']:raise RuntimeError('current_input_or_rights_changed')
    print(json.dumps({'stage':stage,'state':'sending','case':case['inputDigest'][:12]}),flush=True)
    receipt=runtime.send(prepared,attempt_id='review162-'+identity,authorize=authorize)
    once(path,receipt)
    status=receipt['http']['status']
    print(json.dumps({'stage':stage,'state':'received','httpStatus':status,'usage':runtime.usage(receipt)}),flush=True)
    if status in [401,403]:raise RuntimeError('provider_authentication_failed_'+stage)
    return receipt,path

def review(args,runtime,approval,case):
    output=[];proofs=[]
    for company in case['basis']['companies']:
        request,relation,originals=payload(case,company)
        generated,file=send(args,runtime,approval,'impact',request,case);proofs.append(file)
        answer=normalize_answer(runtime.answer('impact',generated),originals)
        candidates=rules.evaluate_impacts(rules.parse_impacts(answer),relation,set(originals),lambda c:resolve(c,originals))
        candidates=[c for c in candidates if c['impactedCompanyId']==company['id']]
        if not candidates:
            output.append({'companyId':company['id'],'companyName':company['name'],'status':'not-proposed','label':None,'targetVerdict':None,'evidence':[]})
            continue
        if len(candidates)!=1:raise RuntimeError('duplicate_company_impact')
        candidate=candidates[0]
        status=candidate['precheck']['state'];label=None;effects=[];target=None
        if status=='pending':
            verification=rules.impact_verifier_request(candidate,{'policyVersion':'zoop-impact-policy-1'})
            verified,file=send(args,runtime,approval,'verify-impact',verification,case);proofs.append(file)
            verdict=runtime.answer('verify-impact',verified)
            decision=rules.decide_impact(candidate,verdict)
            target=decision['targetVerdict'];status='verified' if decision['status']=='verified' else 'verifier-reject';label=decision['label']
            once(args.output/'verdicts'/f'{case["inputDigest"]}.json',{'verdict':verdict,'decision':decision,'audit':runtime.audit('verify-impact',verified)})
            if status=='verified':
                mapped={qid:side for side,ids in decision['mapped'].items() for qid in ids}
                for q in candidate['quotes']:
                    source=originals[(q['documentId'],q['documentVersion'])];context=source.get('bodyContext')
                    base=context['start'] if context else 0
                    if not context:raise RuntimeError('source_offsets_unavailable')
                    effects.append({'id':q['quoteId'],'effect':mapped[q['quoteId']],'quote':q['text'],
                        'articleId':q['documentId'],'articleVersion':source['documentVersion'],'title':source['title'],'url':source['url'],
                        'publishedAt':source['publishedAt'],'start':base+q['start'],'end':base+q['end'],'sourceEvidenceId':source['id']})
        elif status=='no-evidence':status='no-evidence'
        else:raise RuntimeError('impact_precheck_rejected')
        output.append({'companyId':company['id'],'companyName':company['name'],'status':status,'label':label,
                       'targetVerdict':target,'evidence':effects})
    return {'basis':case['basis'],'inputDigest':case['inputDigest'],'assessedAt':now(),'assessments':output,
            'proofs':[proof_reference(p,args.output) for p in proofs]}

def proof_reference(receipt,root):
    request=root/'requests'/receipt.name
    return {'path':str(receipt.relative_to(root)),'sha256':sha(receipt.read_bytes()),'bytes':receipt.stat().st_size,
            'request':{'path':str(request.relative_to(root)),'sha256':sha(request.read_bytes()),'bytes':request.stat().st_size}}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api',default='http://127.0.0.1:18159');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--credentials',type=Path,required=True);p.add_argument('--approval',type=Path,required=True)
    p.add_argument('--budget',type=Path,required=True);p.add_argument('--execute',action='store_true');args=p.parse_args()
    args.output=args.output.resolve();args.output.mkdir(mode=0o700,parents=True,exist_ok=True)
    frozen=args.output/'inputs.json'
    if frozen.is_file():cases=json.loads(frozen.read_text())
    else:cases=freeze(args.api);once(frozen,cases)
    print(json.dumps({'cases':len(cases),'plannedCalls':2*sum(len(c['basis']['companies']) for c in cases),'execute':args.execute}),flush=True)
    if not args.execute:return
    runtime,approval=configure(args);reviews=[]
    for case in cases:
        out=args.output/'completed'/f'{case["inputDigest"]}.json'
        if out.is_file():value=json.loads(out.read_text())
        else:value=review(args,runtime,approval,case);once(out,value)
        reviews.append(value)
        print(json.dumps({'completed':len(reviews),'labels':[a['label'] for a in value['assessments']]}),flush=True)
    manifest={'schemaVersion':'zoop-briefing-impact-reviews-1','sourceKind':'actual','executionMode':'live','recordingKind':'provider',
              'inputScope':'preserved_quote_context','generationModel':'gpt-6-luna','verifierModel':'jev-1.14.0','reviews':reviews}
    once(args.output/'manifest.json',manifest)
    print(json.dumps({'state':'complete','reviews':len(reviews),'manifestSha256':sha(canonical(manifest))}),flush=True)

if __name__=='__main__':
    try:main()
    except (RuntimeError,LiveFailure) as failure:
        print(json.dumps({'state':'stopped','code':getattr(failure,'code',str(failure))}),flush=True);raise SystemExit(2)
