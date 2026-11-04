#!/usr/bin/env python3
"""Bind saved results to explicit current read grants and declared registered graphs.

Offline only. Never creates a grant, registers/activates a graph, runs a model,
connects to a DB or publishes. The server publisher independently rechecks all
current authority and the real registered graph before committing publication.
"""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import re

from prepare_briefing_read_bindings import at, canonical, sha, unique
from render_briefing_staging_sql import TABLES, verify_bundle


def strict(raw):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('duplicate JSON key')
            result[k]=v
        return result
    return json.loads(raw,object_pairs_hook=pairs)


def grants(raw):
    if len(raw)>1_000_000:raise ValueError('grant registry too large')
    obj=strict(raw)
    if not isinstance(obj,dict) or obj.get('schemaVersion')!='zoop-ai-s1-1' or not isinstance(obj.get('grants'),list):raise ValueError('grant registry schema')
    current={};history={}
    for grant in obj['grants']:
        fields={'grantId','revision','sourceId','enabled','rights','allowedOperations','recipients','purposes','evidence','expiresAt'}
        if not isinstance(grant,dict) or set(grant)!=fields:raise ValueError('grant registry schema')
        if (any(not isinstance(grant[k],str) or not grant[k] for k in ('grantId','revision','sourceId'))
                or type(grant['enabled']) is not bool or grant['rights'] not in ('known','unknown','denied')
                or grant['expiresAt'] is not None and not isinstance(grant['expiresAt'],str)):
            raise ValueError('grant registry schema')
        for key in ('allowedOperations','recipients','purposes','evidence'):
            if not isinstance(grant[key],list) or any(not isinstance(x,str) for x in grant[key]):raise ValueError('grant registry schema')
        if (not set(grant['allowedOperations'])<={'read','store','model-send','quote-display'}
                or not set(grant['purposes'])<={'document-summary','document-sentiment','semantic-verification','briefing-outlook'}):
            raise ValueError('grant registry schema')
        key=(grant['grantId'],grant['revision'])
        if key in history and history[key]!=grant:raise ValueError('grant revision conflict')
        history[key]=grant;current[grant['grantId']]=grant
    return current


def read_denial(grant,provider,binding,now):
    if (grant is None or grant.get('enabled') is not True or grant.get('rights')!='known'
            or not grant.get('evidence') or any(not isinstance(x,str) or not x.strip() for x in grant['evidence'])):
        return 'current_read_authority_unconfirmed'
    if grant['sourceId']!=provider or grant['revision']!=binding['grantRevision']:return 'grant_identity_changed'
    if provider.lower().replace('_','-') in ('naver-search','naver-developers-search'):return 'source_ai_reuse_prohibited'
    if grant.get('expiresAt') is not None:
        try:
            if at(grant['expiresAt'])<=now:return 'grant_expired'
        except (ValueError,TypeError):return 'grant_expiry_invalid'
    if not {'read','quote-display'}<=set(grant['allowedOperations']):return 'read_or_quote_denied'
    recipients=binding['recipients']
    if (not isinstance(recipients,list) or not recipients or any(not isinstance(x,str) or not x.strip() for x in recipients)
            or len(set(recipients))!=len(recipients) or not set(recipients)<=set(grant['recipients'])
            or 'briefing-outlook' not in grant['purposes']):return 'purpose_or_recipient_denied'
    return None


def inspect(bundle,request,registry,now):
    manifest=verify_bundle(bundle);tables={t:[strict(s) for s in (bundle/'tables'/f'{t}.jsonl').read_text().splitlines()] for t in TABLES}
    if request.get('schemaVersion') not in ('briefing-finalization-request-v1','briefing-finalization-request-v2') or request.get('sourceManifestSha256')!=sha((bundle/'manifest.json').read_bytes()):
        raise ValueError('source manifest binding mismatch')
    if not request.get('memberId','').strip() or type(request.get('preferenceRevision')) is not int or request['preferenceRevision']<1:
        raise ValueError('explicit member and demo revision required')
    imported=at(request['importedAt'])
    if imported>now:raise ValueError('future import time')
    bindings=unique(request['documents'],lambda d:(d['documentId'],d['documentVersion']))
    graphs=copy.deepcopy(unique(request['rounds'],lambda r:r['roundId']));articles=unique(tables['articles'],lambda a:a['id'])
    versions=unique(tables['article_versions'],lambda v:(v['article_id'],v['version']));artifacts=unique(tables['artifacts'],lambda a:a['id'])
    if set(bindings)!=set(versions) or set(graphs)!={r['id'] for r in tables['briefing_rounds']}:raise ValueError('incomplete or extra binding scope')
    blockers=[]
    for key,v in versions.items():
        b=bindings[key]
        if b.get('bodySha256')!=artifacts[v['text_artifact_id']]['sha256']:raise ValueError('document body mismatch')
        denial=read_denial(registry.get(b.get('grantId')),articles[key[0]]['provider'],b,now)
        if denial:blockers.append(dict(kind='document',documentId=key[0],code=denial))
    for rid,g in graphs.items():
        if (request['schemaVersion']=='briefing-finalization-request-v2' and g.get('basisMode')=='retained-results'
                and g.get('graphVersion') is None and g.get('snapshotSha256') is None):
            continue
        if not re.fullmatch(r'gv-[0-9a-f]{64}',g.get('graphVersion') or '') or not re.fullmatch(r'[0-9a-f]{64}',g.get('snapshotSha256') or ''):
            blockers.append(dict(kind='round',roundId=rid,code='registered_internal_basis_required'))
    return manifest,tables,bindings,graphs,blockers


def bind_tables(tables,bindings,graphs,context_artifacts=None,imported_at=None):
    result=copy.deepcopy(tables);rounds={r['id']:r for r in result['briefing_rounds']};pools={p['round_id']:p for p in result['briefing_personal_pools']}
    evidence=unique(result['evidence'],lambda e:e['id']);versions=unique(result['article_versions'],lambda v:(v['article_id'],v['version']))
    context_artifacts={} if context_artifacts is None else context_artifacts
    def source_binding(key):
        b=bindings[key]
        return {k:copy.deepcopy(b[k]) for k in ('documentId','documentVersion','grantId','grantRevision','recipients')}
    for row in sorted(rounds.values(),key=lambda r:at(r['window_to'])):
        rid=row['id'];snapshot=row['public_snapshot'];payload=row['published_payload'];g=graphs[rid]
        row['graph_version_id']=payload['graphVersion']=payload['metadata']['graphVersion']=g['graphVersion']
        context=snapshot.get('priorityContext');previous=[];archived=[]
        docs={(b['documentId'],b['documentVersion']) for b in snapshot['sourceBindings']}
        if context:
            if context['roundId']!=rid or at(context['cutoff'])!=at(row['window_to']):raise ValueError('foreign context')
            for key,entry in context['contexts'].items():
                if key not in ('context:market','context:sessions','context:previous') or sha(canonical(entry['value']))!=entry['sha256']:
                    raise ValueError('context digest mismatch')
            old=context['contexts'].get('context:previous',{}).get('value',{})
            if old.get('status')=='available':
                prior=rounds.get(old['roundId'])
                if prior is None or at(prior['window_to'])>=at(row['window_to']) or at(prior['window_to'])!=at(old['cutoff']):
                    raise ValueError('previous summary binding mismatch')
                reference=dict(roundId=prior['id'],cutoff=prior['window_to'],resultVersion=old['resultVersion'])
                if prior['public_snapshot']['prioritySummary']['resultVersion']==old['resultVersion']:
                    previous=[reference]
                else:
                    ids=set()
                    def collect(value):
                        if isinstance(value,dict):
                            for key,child in value.items():
                                if key=='evidenceIds':ids.update(s for s in child if not s.startswith('context:'))
                                else:collect(child)
                        elif isinstance(value,list):
                            for child in value:collect(child)
                    collect(old)
                    if not ids:raise ValueError('archived previous input has no article evidence')
                    for eid in ids:
                        e=evidence[eid];v=versions[(e['article_id'],e['article_version'])]
                        if at(v['published_at'])>at(old['cutoff']):raise ValueError('future evidence in previous input')
                        docs.add((e['article_id'],e['article_version']))
                    entry=context['contexts']['context:previous']
                    raw=canonical(dict(schemaVersion='briefing-archived-previous-context-v1',roundId=rid,
                        sourceContextSha256=entry['sha256'],context=old))
                    digest=sha(raw);aid='saved-context-'+digest;name='artifacts/'+digest+'.json';context_artifacts[name]=raw
                    result['artifacts'].append(dict(id=aid,kind='briefing_input',storage_uri='artifact-root:'+name,sha256=digest,
                        bytes=len(raw),media_type='application/json',created_at=imported_at or row['window_to']))
                    reference.update(artifactId=aid,contextSha256=entry['sha256'],evidenceIds=sorted(ids));archived=[reference]
                    payload['metadata'].setdefault('failures',[]).append(dict(section='comparison',code='archived_prior_input_version',
                        message='이전 판단 비교는 보존된 당시 입력 버전 기준이며, 현재 제공되는 이전 회차 버전과 다릅니다.',retryable=False,asOf=old['cutoff']))
                docs.update((b['documentId'],b['documentVersion']) for b in prior['public_snapshot']['sourceBindings'])
        snapshot['sourceBindings']=[source_binding(k) for k in sorted(docs)]
        snapshot['savedResultContext']=dict(previous=previous,archivedPrevious=archived)
        pool=pools[rid];p=pool['snapshot']
        for candidate in p['candidates']:
            for source in candidate['sources']:
                b=bindings[(source['documentId'],source['documentVersion'])]
                source.update({k:copy.deepcopy(b[k]) for k in ('grantId','grantRevision','recipients')})
        p.pop('inputSha256');digest=sha(canonical(p));p['inputSha256']=digest;pool['input_sha256']=digest
        pool['id']='final-pool-'+sha((rid+'\n'+digest).encode())[:40]
    for delivery in result['briefing_personal_deliveries']:
        rid=delivery['round_id'];pool=pools[rid]
        for name in ('selection_snapshot','result_snapshot'):
            selection=delivery[name];selection['poolVersion']=pool['input_sha256']
            selection['selectionVersion']='saved-import-'+sha(canonical([selection['selectionVersion'],pool['input_sha256'],selection['choice']]))
            for view in ('presentation','verifiedPresentation'):
                p=selection.get(view)
                if p:
                    p['graphVersion']=graphs[rid]['graphVersion']
                    if p.get('metadata'):p['metadata']['graphVersion']=graphs[rid]['graphVersion']
    return result


def retained_bases(tables,graphs,source_manifest_sha,files,imported_at):
    """Register exact saved inputs, never an invented native graph or AI verdict."""
    pools={p['round_id']:p for p in tables['briefing_personal_pools']}
    for row in tables['briefing_rounds']:
        g=graphs[row['id']]
        if g.get('basisMode')!='retained-results':continue
        if row['graph_version_id'] is not None or row['published_payload']['graphVersion'] is not None:
            raise ValueError('retained result cannot impersonate a graph')
        pool=pools[row['id']]
        raw=canonical(dict(schemaVersion='briefing-retained-result-basis-v1',
            sourceManifestSha256=source_manifest_sha,roundId=row['id'],cutoff=row['window_to'],
            payload=row['published_payload'],snapshot=row['public_snapshot'],poolId=pool['id'],pool=pool['snapshot'],
            provenance=dict(origin='retained-generated-results',nativeGraphRegistration='not-performed',
                newSemanticVerification='not-performed')))
        digest=sha(raw);aid='retained-basis-'+digest;name='artifacts/'+digest+'.json';files[name]=raw
        tables['artifacts'].append(dict(id=aid,kind='briefing_input',storage_uri='artifact-root:'+name,
            sha256=digest,bytes=len(raw),media_type='application/json',created_at=imported_at))
        pin=dict(artifactId=aid,sha256=digest)
        row['public_snapshot']['retainedBasis']=copy.deepcopy(pin)
        g.pop('basisMode');g['retainedBasis']=pin


def finalize(bundle,request_file,grants_file,output,check_only=False,now=None):
    if output.exists():raise ValueError('output exists; preserve previous preparation')
    now=now or datetime.now().astimezone();request_raw=request_file.read_bytes();grant_raw=grants_file.read_bytes();request=strict(request_raw)
    manifest,tables,bindings,graphs,blockers=inspect(bundle,request,grants(grant_raw),now)
    protected={str(p):sha(p.read_bytes()) for p in (bundle/'manifest.json',request_file,grants_file)}
    if blockers or check_only:
        report=dict(schemaVersion='briefing-finalization-readiness-v1',bound=False,publicationReady=False,blockers=blockers,
            memberMapped=True,serverRegistrationVerified=False,newAiCalls=0,serverChangesPerformed=False)
        with output.open('xb') as f:output.chmod(0o600);f.write(canonical(report))
        return report
    context_artifacts={};tables=bind_tables(tables,bindings,graphs,context_artifacts,request['importedAt'])
    retained_bases(tables,graphs,protected[str(bundle/'manifest.json')],context_artifacts,request['importedAt'])
    output.mkdir(mode=0o700,parents=True);files={}
    def write(name,raw):
        p=output/name;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);p.parent.chmod(0o700)
        with p.open('xb') as f:p.chmod(0o600);f.write(raw)
        files[name]=dict(bytes=len(raw),sha256=sha(raw))
    for name in manifest['files']:
        if not name.startswith('tables/'):write(name,(bundle/name).read_bytes())
    for name,raw in context_artifacts.items():write(name,raw)
    for table,rows in tables.items():write(f'tables/{table}.jsonl',b''.join(canonical(r)+b'\n' for r in rows))
    write('archive/pre-finalization-manifest.json',(bundle/'manifest.json').read_bytes())
    final=copy.deepcopy(manifest);final.update(files=files,targetMemberId=request['memberId'],
        finalization=dict(schemaVersion='briefing-finalization-v2' if request['schemaVersion'].endswith('-v2') else 'briefing-finalization-v1',sourceManifestSha256=protected[str(bundle/'manifest.json')],
            requestSha256=sha(request_raw),grantsSha256=sha(grant_raw),memberId=request['memberId'],
            preferenceRevision=request['preferenceRevision'],importedAt=request['importedAt'],rounds=list(graphs.values()),
            serverRegistrationVerified=False,newModelCallsAuthorized=False))
    with (output/'manifest.json').open('xb') as f:(output/'manifest.json').chmod(0o600);f.write(canonical(final))
    if any(sha(Path(p).read_bytes())!=s for p,s in protected.items()):raise ValueError('finalization input changed')
    return dict(bound=True,publicationReady=False,rounds=len(graphs),documents=len(bindings),newAiCalls=0,serverRegistrationVerified=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('bundle','request','grants-file','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--check-only',action='store_true');a=p.parse_args()
    print(json.dumps(finalize(a.bundle,a.request,a.grants_file,a.output,a.check_only)))


if __name__=='__main__':main()
