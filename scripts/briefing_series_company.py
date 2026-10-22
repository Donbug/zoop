#!/usr/bin/env python3
"""Use the existing company outlook generator over an explicit retrospective sequence."""
import argparse
import copy
import os
from pathlib import Path
import briefing_company_outlook as company
base=company.base


def run(args):
    source=Path(args.baseline).resolve();output=Path(args.output).resolve()
    if source==output or source in output.parents or output in source.parents:
        raise base.ReplayError('series_company_separate_output_required')
    raw=base.regular(source/'bundle-v2.json');bundle=base.strict_load(raw)
    if not bundle.get('roundSeries'):raise base.ReplayError('series_required')
    identity={'baselineSha256':base.digest(raw),'authorizationRef':args.authorization_ref,'maximumCalls':args.max_calls}
    if not args.execute:
        return {'status':'OFFLINE','minimumNewCalls':2*len(bundle['marketEnrichment']['rounds']),'maximumTotalCalls':args.max_calls,'newPaidCalls':0}
    if not args.key_file:raise base.ReplayError('series_company_key_required')
    base.private_dir(output)
    if (output/'completed.json').exists():
        proof=base.strict_load(base.regular(output/'completed.json'))
        if proof['identity']!=identity or base.digest(base.regular(output/'bundle-v2.json'))!=proof['bundleSha256']:
            raise base.ReplayError('series_company_reuse_mismatch')
        return {**proof,'newPaidCalls':0}
    for f in source.rglob('*'):
        if f.is_file() and f.name not in {'bundle-v2.json','bundle.binding.json','completed.json','plan.json'}:
            target=output/f.relative_to(source);base.private_dir(target.parent)
            if not target.exists():os.link(f,target)
    metadata={d['documentId']:d for d in [base.strict_load(line) for line in base.regular(Path(args.sources)).decode().splitlines()]}
    receipts=[];history=[];news={r['roundId']:r for r in bundle['rounds']}
    client=company.context.legacy.MarketSummaryClient(output,base.authenticated_transport(Path(args.key_file),timeout=600),args.max_calls,prompt_root=company.PROMPTS)
    for market in bundle['marketEnrichment']['rounds']:
        definition=news[market['roundId']]
        row={'roundId':market['roundId'],'date':market['date'],'edition':market['edition'],'marketEnrichment':market}
        frozen=company.freeze(row,definition,metadata,history)
        path=output/'company-rounds'/(row['roundId']+'.json');base.private_dir(path.parent)
        if path.exists():
            record=base.strict_load(base.regular(path))
            if record['frozen']!=frozen:raise base.ReplayError('series_company_history_changed')
        else:
            record=company.assess(client,frozen)
            record.update(roundId=row['roundId'],date=row['date'],edition=row['edition'],cutoff=frozen['cutoff'],frozen=frozen,
                generatedAt=base.now(),resultVersion='company-v1-'+base.digest(base.canonical(record)))
            base.write_once(path,base.canonical(record))
        history.append(record)
        print(base.canonical({'round':row['date']+'-'+row['edition'],'companyStatus':record['status']}).decode(),flush=True)
    owned={a[k] for r in history for a in r['attempts'] for k in ('generationRequestDigest','verificationRequestDigest') if k in a}
    receipts=[r for r in client.receipts() if r['requestDigest'] in owned]
    bundle['marketEnrichment']['seriesCompanyOutlooks']={'schemaVersion':company.SCHEMA,'authorizationRef':args.authorization_ref,'rounds':history,'receipts':receipts}
    base.write_once(output/'bundle-v2.json',base.canonical(bundle))
    result={'status':'COMPLETE','identity':identity,'pass':sum(r['status']=='PASS' for r in history),'rounds':len(history),
        'newPaidCalls':len(client.new_calls),'bundleSha256':base.digest(base.regular(output/'bundle-v2.json'))}
    base.write_once(output/'completed.json',base.canonical(result));return result


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('baseline','output','sources','authorization-ref'):p.add_argument('--'+key,required=True)
    p.add_argument('--key-file');p.add_argument('--execute',action='store_true')
    p.add_argument('--max-calls',type=int,choices=range(1,513),default=80)
    return p

if __name__=='__main__':print(base.canonical(run(parser().parse_args())).decode(),flush=True)
