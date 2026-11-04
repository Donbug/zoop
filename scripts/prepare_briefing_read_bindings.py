#!/usr/bin/env python3
"""Prepare private member, document-authority and internal evidence-basis requests.

Offline only: no account changes, grants, graph registration, publication, SQL
execution, provider calls or past-map UI. Pending authority is never approved.
"""
import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path

from render_briefing_staging_sql import TABLES, literal, verify_bundle


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def at(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('timezone required')
    return result


def unique(rows,key):
    result={}
    for row in rows:
        k=key(row)
        if k in result:raise ValueError('duplicate immutable identity')
        result[k]=row
    return result


def plan(tables,profile,registry,target_member_id=None):
    if target_member_id is not None and not target_member_id.strip():
        raise ValueError('blank target member')
    rounds=unique(tables['briefing_rounds'],lambda x:x['id'])
    pools=unique(tables['briefing_personal_pools'],lambda x:x['round_id'])
    deliveries=unique(tables['briefing_personal_deliveries'],lambda x:x['round_id'])
    evidence=unique(tables['evidence'],lambda x:x['id'])
    versions=unique(tables['article_versions'],lambda x:(x['article_id'],x['version']))
    articles=unique(tables['articles'],lambda x:x['id'])
    artifacts=unique(tables['artifacts'],lambda x:x['id'])
    sources=unique(registry['sources'],lambda x:x['sourceId'])
    if not rounds or set(rounds)!=set(pools) or set(rounds)!=set(deliveries):
        raise ValueError('unpaired common, personal or candidate pool')
    choice=profile['choice']
    member=dict(schemaVersion='briefing-member-binding-request-v1',sourceMemberId=profile['member_id'],
        sourcePreferenceId=profile['preference_id'],sourceRevision=profile['revision'],choice=copy.deepcopy(choice),
        sourceCreatedAt=profile['created_at'],sourceEffectiveFrom=profile['effective_from'],
        targetMemberId=target_member_id,mappingVerified=False,mode='demo',
        existingSettingsUpdateAllowed=False,existingDeliveryUpdateAllowed=False,
        roundsBeforeSourcePreference=sorted(r['id'] for r in rounds.values() if at(r['scheduled_at'])<at(profile['effective_from'])))
    requests=[]
    for key,version in sorted(versions.items()):
        article=articles[version['article_id']];provider=article['provider']
        if provider not in sources:raise ValueError('document provider absent from source registry')
        grant=sources[provider]['grant']
        if grant['sourceId']!=provider:raise ValueError('source/grant mismatch')
        body=artifacts[version['text_artifact_id']]
        requests.append(dict(documentId=key[0],documentVersion=key[1],bodySha256=body['sha256'],sourceId=provider,
            evidenceIds=sorted(e['id'] for e in evidence.values() if (e['article_id'],e['article_version'])==key),
            observedGrant=dict(grantId=grant['grantId'],revision=grant['revision'],enabled=grant['enabled'],rights=grant['rights'],
                allowedOperations=grant['allowedOperations'],purposes=grant['purposes'],recipients=grant['recipients']),
            requiredByCurrentReader=dict(operations=['read','quote-display'],
                purposes=['briefing-outlook'],requiresCurrentEvidence=True),
            requiredForNewModelCalls=dict(operations=['read','store','model-send','quote-display'],
                purposes=['briefing-outlook','semantic-verification'],requiresSeparateAuthorization=True),
            proposedGrantId=None,proposedRevision=None,proposedRecipients=[],authorizationEvidence=[],
            approvalStatus='pending',newModelCallsAuthorized=False))
    basis=[]
    for rid,round_ in sorted(rounds.items(),key=lambda x:at(x[1]['window_to'])):
        pool=pools[rid];snapshot=pool['snapshot'];unsealed=copy.deepcopy(snapshot);unsealed.pop('inputSha256')
        if snapshot['roundId']!=rid or at(snapshot['cutoff'])!=at(round_['window_to']) or sha(canonical(unsealed))!=pool['input_sha256'] or snapshot['inputSha256']!=pool['input_sha256']:
            raise ValueError('pool binding or input digest mismatch')
        if snapshot['candidateCount']!=len(snapshot['candidates']):raise ValueError('candidate count mismatch')
        candidates=unique(snapshot['candidates'],lambda x:x['issueId'])
        required=set(round_['published_payload']['references']['evidenceIds']);links=[];issues=[];supplements=[]
        for iid,candidate in sorted(candidates.items()):
            ids=set()
            for source in candidate['sources']:
                eid=source['evidenceId'];e=evidence[eid];key=(e['article_id'],e['article_version'])
                v=versions[key];a=artifacts[v['text_artifact_id']]
                if (source['documentId'],source['documentVersion'])!=key or source['bodySha256']!=a['sha256'] or source['quote']!=e['quote']:
                    raise ValueError('candidate/evidence identity mismatch')
                if at(source['publishedAt'])!=at(v['published_at']) or at(source['publishedAt'])>at(round_['window_to']):
                    raise ValueError('future or mismatched publication time')
                ids.add(eid)
            if not ids:raise ValueError('candidate without evidence')
            required.update(ids);issues.append(dict(issueId=iid,evidenceIds=sorted(ids)))
            for company in candidate['companies']:
                refs=set(company['evidenceIds'])
                if not refs or not refs<=ids:raise ValueError('unbound issue-company relation')
                links.append(dict(issueId=iid,companyId=company['companyId'],evidenceIds=sorted(refs),
                    status='retained_reference_only',businessImpactApproved=False))
        # All retained candidates are used, independent of any member's holdings.
        # No selected/holding/watch or member identifier is emitted into this basis.
        personal=deliveries[rid]['result_snapshot']['presentation']['personalPriority']
        if set(personal['companyIds'])!=set(choice['companyIds']):raise ValueError('personal scope mismatch')
        for scope,priority in (('common',round_['public_snapshot']['commonPriority']),('personal',personal)):
            if priority['roundId']!=rid or at(priority['cutoff'])!=at(round_['window_to']):raise ValueError('foreign priority')
            for item in priority['items']:
                if item['issueId'] not in candidates:raise ValueError('selected issue absent from retained pool')
                for source in item['sources']:
                    candidate=candidates[item['issueId']]
                    eid=source['evidenceId'];e=evidence[eid];v=versions[(e['article_id'],e['article_version'])]
                    if source['quote']!=e['quote'] or at(source['publishedAt'])!=at(v['published_at']):
                        raise ValueError('selected evidence mismatch')
                    if eid not in {s['evidenceId'] for s in candidate['sources']}:
                        # Common generation may retain a longer exact quote from the
                        # same frozen document. Do not rewrite or reseal the pool.
                        docs={(s['documentId'],s['documentVersion']) for s in candidate['sources']}
                        if scope!='common' or (e['article_id'],e['article_version']) not in docs:
                            raise ValueError('selected source absent from retained pool or frozen document')
                        supplements.append(dict(issueId=item['issueId'],evidenceId=eid,origin='saved_common_analysis',approvalStatus='pending_registration'))
                        issue=next(i for i in issues if i['issueId']==item['issueId'])
                        issue['evidenceIds']=sorted(set(issue['evidenceIds'])|{eid})
                    required.add(eid)
        pins=[]
        for eid in sorted(required):
            e=evidence[eid];v=versions[(e['article_id'],e['article_version'])]
            if at(v['published_at'])>at(round_['window_to']):raise ValueError('future disclosed evidence')
            pins.append(dict(evidenceId=eid,documentId=e['article_id'],documentVersion=e['article_version'],
                bodySha256=artifacts[v['text_artifact_id']]['sha256'],quoteSha256=sha(e['quote'].encode())))
        request=dict(schemaVersion='briefing-internal-basis-request-v1',roundId=rid,cutoff=round_['window_to'],
            poolInputSha256=pool['input_sha256'],issues=issues,companyReferences=links,evidence=pins,
            supplementalReferences=supplements,
            graphVersion=None,registrationStatus='pending',origin='late_collected_historical_reconstruction',
            mapUiIncluded=False,graphActivationRequested=False,sourceRightsApproved=False)
        request['requestedScopeSha256']=sha(canonical(request));basis.append(request)
    return dict(member=member,documents=dict(schemaVersion='briefing-document-authority-request-v1',
        reuseExistingResultsOnly=True,requests=requests),basis=basis)


def preflight(result):
    member=result['member'];ids=[member['sourceMemberId']]
    if member['targetMemberId']:ids.append(member['targetMemberId'])
    wanted=json.dumps([dict(document_id=d['documentId'],document_version=d['documentVersion'],body_sha256=d['bodySha256']) for d in result['documents']['requests']])
    members=','.join(literal(x) for x in sorted(set(ids)))
    return '\n'.join([
        '-- Private read-only verification. Does not create members, grants, versions or deliveries.',
        'BEGIN READ ONLY;',
        'SET LOCAL standard_conforming_strings=on;',
        'SELECT id,status FROM members WHERE id IN ('+members+');',
        'SELECT id,member_id,revision,created_at,effective_from FROM briefing_personal_preferences WHERE member_id IN ('+members+') ORDER BY revision;',
        'WITH wanted AS (SELECT * FROM jsonb_to_recordset('+literal(wanted)+'::jsonb) AS x(document_id text,document_version text,body_sha256 text))',
        'SELECT w.*,a.provider,a.access_status,v.version AS stored_version,t.sha256 AS stored_body_sha256 FROM wanted w LEFT JOIN articles a ON a.id=w.document_id LEFT JOIN article_versions v ON v.article_id=w.document_id AND v.version=w.document_version LEFT JOIN artifacts t ON t.id=v.text_artifact_id;',
        'SELECT id,round_date,edition,status,graph_version_id,payload_sha256 FROM briefing_rounds WHERE id IN ('+','.join(literal(x['roundId']) for x in result['basis'])+');',
        "SELECT id,kind,active FROM graph_versions ORDER BY created_at DESC LIMIT 20;",
        '-- A matching title or active graph alone does not establish the exact registered basis.',
        'ROLLBACK;',''])


def prepare(bundle,profile_file,registry_file,output,target_member_id=None):
    if output.exists():raise ValueError('output exists; preserve prior preparation')
    manifest=verify_bundle(bundle)
    protected={str(p):sha(p.read_bytes()) for p in (bundle/'manifest.json',profile_file,registry_file)}
    tables={t:[json.loads(s) for s in (bundle/'tables'/f'{t}.jsonl').read_text().splitlines()] for t in TABLES}
    result=plan(tables,json.loads(profile_file.read_text()),json.loads(registry_file.read_text()),target_member_id)
    output.mkdir(mode=0o700,parents=True)
    files={}
    def write(name,raw):
        p=output/name;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);p.parent.chmod(0o700)
        with p.open('xb') as f:p.chmod(0o600);f.write(raw)
        files[name]=dict(sha256=sha(raw),bytes=len(raw))
    write('member-mapping.json',canonical(result['member']))
    write('document-authority-requests.json',canonical(result['documents']))
    index=[]
    for basis in result['basis']:
        name='internal-basis/'+basis['requestedScopeSha256']+'.json';write(name,canonical(basis))
        index.append(dict(roundId=basis['roundId'],path=name,scopeSha256=basis['requestedScopeSha256'],graphVersion=None))
    write('internal-basis-index.json',canonical(index));write('server-preflight-readonly.sql',preflight(result).encode())
    gates=dict(schemaVersion='briefing-read-binding-gates-v1',publicationReady=False,
        archiveIntegrity='passed',referenceClosure='passed',memberMapping='pending_server_identity_check',
        documentAuthority='pending_current_authorization',internalGraphBinding='pending_native_registration',
        serverPreflight='not_executed',rounds=len(index),documents=len(result['documents']['requests']),
        pastMapUiAdded=False,newAiCalls=0,serverChangesPerformed=False)
    write('gates.json',canonical(gates))
    write('manifest.json',canonical(dict(schemaVersion='briefing-read-bindings-preparation-v1',
        sourceBundleManifestSha256=protected[str(bundle/'manifest.json')],sourceFiles=protected,files=files,
        publicationReady=False,notAnAuthorityRegistry=True,notANativeGraphPublication=True)))
    if any(sha(Path(p).read_bytes())!=s for p,s in protected.items()):raise ValueError('input changed')
    return gates


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('bundle','profile-file','source-registry','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--target-member-id')
    a=p.parse_args()
    print(json.dumps(prepare(a.bundle,a.profile_file,a.source_registry,a.output,a.target_member_id)))


if __name__=='__main__':main()
