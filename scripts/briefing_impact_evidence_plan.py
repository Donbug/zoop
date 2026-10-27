"""Offline evidence enrichment. Never calls a model or changes an existing assessment.

Exact excerpts come from hash-checked, previously registered article bodies. Editorial
needs and background are separate from verified effect citations and future follow-up.
"""
from __future__ import annotations
import argparse
import copy
import json
import re
from datetime import datetime
from pathlib import Path
import briefing_s3_review as base
import briefing_s3_citation_context as context
from zoop_ai_pipeline.live_jev import build_impact_request


def excerpt(source, text, anchor):
    if text.count(anchor)!=1:raise ValueError('nonunique_source_anchor')
    offset=text.index(anchor)
    start=text.rfind('\n',0,offset)+1
    end=text.find('\n',offset+len(anchor));end=len(text) if end<0 else end
    while start<end and text[start].isspace():start+=1
    while end>start and text[end-1].isspace():end-=1
    quote=text[start:end]
    if not quote or len(quote)>2000 or not re.search(r'[.!?。！？]["”’)]?$',quote):
        raise ValueError('incomplete_or_oversized_excerpt')
    return {'id':'supplement-'+base.sha(base.canonical([source['documentId'],source['documentVersion'],start,end]))[:24],
            'sourceEvidenceId':source['id'],'articleId':source['documentId'],'articleVersion':source['documentVersion'],
            'title':source['title'],'url':source['url'],'publishedAt':source['publishedAt'],
            'quote':quote,'start':start,'end':end,'bodySha256':source['bodySha256']}


def build(parent, index, specs, prepared_at=None):
    result=copy.deepcopy(parent);requests=[];queue=[]
    prepared_at=prepared_at or base.now()
    for review in result['reviews']:
        assessment=review['assessments'][0]
        if assessment['label']!='undetermined':continue
        basis=review['basis'];company=basis['companies'][0];spec=specs[company['id']]
        registered=next(x for x in index if x['inputDigest']==review['inputDigest'])
        raw=Path(registered['path']).read_bytes();text=raw.decode('utf-8');source=basis['evidence'][0]
        if base.sha(raw)!=registered['bodySha256'] or len(raw)!=registered['bytes']:
            raise ValueError('source_artifact_changed')
        if source['bodySha256']!=registered['bodySha256'] or source['documentId']!=registered['articleId'] or source['documentVersion']!=registered['articleVersion']:
            raise ValueError('source_version_mismatch')
        if datetime.fromisoformat(source['publishedAt'].replace('Z','+00:00'))>datetime.fromisoformat(basis['dataAsOf'].replace('Z','+00:00')):
            raise ValueError('future_source')
        additions=[]
        for selection in spec['selections']:
            fact=excerpt(source,text,selection['anchor'])
            additions.append({'scope':selection['scope'],'note':selection['note'],'forVerification':selection['forVerification'],'source':fact})
        plan={'status':'prepared_not_evaluated','preparedAt':prepared_at,'reason':spec['reason'],
              'existingEvidence':additions,'collectionNeeds':spec['needs']}
        assessment['evidencePlan']=plan
        # Prepared native request only. No transport/key/runtime is configured by this module.
        case={'basis':copy.deepcopy(basis),'title':spec['title'],'inputDigest':review['inputDigest']}
        full=case['basis']['evidence'][0]['bodyContext'];full.update(text=text,start=0,end=len(text))
        facts=[a['source'] for a in additions if a['forVerification']]
        seed={'schemaVersion':'zoop-impact-response-1','producerVersion':'zoop-impact-producer-1',
              'impacts':[{'impactedCompanyId':company['id'],'direction':'undetermined','reason':'Offline evidence preparation only.',
                          'limitations':None,'supporting':[],'opposing':[]}]}
        candidate=context.candidate_for(case,company,seed,facts)
        body,expect=build_impact_request(base.rules.impact_verifier_request(candidate,{'policyVersion':'zoop-impact-policy-1'}),'jev-1.14.0')
        requests.append({'companyId':company['id'],'roundId':basis['roundId'],'eventId':basis['eventId'],
             'status':'prepared_not_sent','basisInputDigest':review['inputDigest'],
             'expandedInputDigest':base.sha(base.canonical({'basis':basis,'facts':facts})),
             'body':body,'expect':expect,'requiresNewCallApproval':True,
             'directEvidenceChanged':any(not any(f['quote'] in e['quote'] for e in assessment['evidence']) for f in facts),
             'recommendedAction':'reverify_after_approval' if any(not any(f['quote'] in e['quote'] for e in assessment['evidence']) for f in facts) else 'collect_direct_evidence_first'})
        for number,need in enumerate(spec['needs'],1):
            queue.append({'id':f"{review['inputDigest'][:12]}-{number}",'companyId':company['id'],'eventId':basis['eventId'],
                          'roundId':basis['roundId'],'cutoff':basis['dataAsOf'],'status':'not_collected',**need})
    return result,requests,queue


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['parent','source-index','plan','output']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    parent=json.loads(args.parent.read_text())
    stamp=args.output/'prepared-at.json'
    if not stamp.exists():base.once(stamp,{'preparedAt':base.now()})
    result,requests,queue=build(parent,json.loads(args.source_index.read_text()),json.loads(args.plan.read_text()),json.loads(stamp.read_text())['preparedAt'])
    result['previousManifestSha256']=base.sha(args.parent.read_bytes())
    base.once(args.output/'manifest.json',result)
    for file in (args.parent.parent/'receipts').glob('*.json'):base.once(args.output/'receipts'/file.name,file.read_bytes())
    base.once(args.output/'prepared-verifications.json',requests)
    base.once(args.output/'collection-queue.json',queue)
    print(json.dumps({'supplementedIssues':len(requests),'preparedNotSent':len(requests),'collectionTasks':len(queue),'newModelCalls':0}))


if __name__=='__main__':main()
