#!/usr/bin/env python3
"""Prepare immutable briefing results for the server schema, without publishing.

No network, model calls, database writes, or grant creation. Output is private.
The original result bytes remain archived; context references are never fabricated
as article evidence. Member mapping and current publication authority remain gates.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def load(path):
    return json.loads(path.read_text())


def rows(path):
    source = path.resolve(strict=True)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as con:
        records = con.execute('SELECT scope,day,edition,payload,sha256 FROM round_results ORDER BY day,edition,scope').fetchall()
    result = []
    for scope, day, edition, raw, sha in records:
        if digest(raw.encode()) != sha:
            raise ValueError('archive payload digest mismatch')
        value = json.loads(raw)
        if scope not in ('common', 'personal') or value['date'] != day or value['edition'] != edition:
            raise ValueError('archive scope or slot mismatch')
        result.append(dict(scope=scope, day=day, edition=edition, payload=value, raw=raw, sha256=sha))
    return result


def source_registry(native, release, personal_release):
    units = {u['observation']['documentId']: u for u in load(native / 'corpus-v2/units.json')}
    sources, candidates, appearances, assessments = {}, {}, {}, {}
    inputs = []
    for base in (native / 'revision2', native / 'personal-aligned'):
        for folder in ('prepared-common', 'prepared-personal'):
            inputs += sorted((base / folder).glob('*.input.json'))
        for file in base.glob('executed-*/results.json'):
            for row in load(file)['rounds']:
                assessments.update((row.get('assessments') or {}).get('assessments', {}))
    for file in inputs:
        packet = load(file)
        for candidate in packet['candidates']:
            iid = candidate['issueId']
            candidates[iid] = candidate
            appearances.setdefault(iid, []).append(dict(roundId=packet['roundId'], cutoff=packet['cutoff']))
            for sid, s in candidate['sources'].items():
                register_source(sources, units, sid, s)
    for entry in load(release / 'release-v2-effective-results.json').values():
        for issue in load(release / entry['impactInput'])['issues']:
            for sid, s in issue['sources'].items():
                register_source(sources, units, sid, s)
    for entry in load(personal_release / 'effective-results.json').values():
        packet = load(personal_release / entry['input'])
        for issue in packet['issues']:
            for sid, s in issue['sources'].items():
                register_source(sources, units, sid, s)
            # Personal execution may retain an explicitly admitted native fact
            # outside the common pool; preserve that original frozen basis.
            iid = issue['issueId']
            if iid not in candidates:
                candidates[iid] = dict(issueId=iid, title=issue['title'], sources=issue['sources'],
                    companies=[dict(companyId=t['companyId'], name=t['name'], evidenceIds=t['evidenceIds'],
                                    role=t['connectionReason']) for t in issue['targets']])
            appearances.setdefault(iid, []).append(dict(roundId=packet['roundId'], cutoff=packet['cutoff']))
    return units, sources, candidates, appearances, assessments


def register_source(sources, units, sid, source):
    s = copy.deepcopy(source)
    u = units[s['documentId']]
    if digest(u['text'].encode()) != s['bodySha256'] or s['quote'] not in u['text']:
        raise ValueError('source text or quote mismatch')
    if sid != s['evidenceId']:
        raise ValueError('source identity mismatch')
    native_version = u['observation']['documentVersion']
    if s.get('documentVersion') and s['documentVersion'] != native_version:
        raise ValueError('source version mismatch')
    s.update(title=s.get('title') or u['title'], publisher=urlsplit(s['url']).hostname,
             start=u['text'].index(s['quote']), documentVersion=native_version)
    s['end'] = s['start'] + len(s['quote'])
    old = sources.get(sid)
    if old and any(old[k] != s[k] for k in ('quote', 'url', 'documentId', 'bodySha256')):
        raise ValueError('conflicting immutable evidence')
    if old and instant(old['publishedAt']) != instant(s['publishedAt']):
        raise ValueError('conflicting publication timestamp')
    sources[sid] = s


def project_summary(payload, release, sources):
    key = payload['date'] + '-' + payload['edition']
    packet = load(release / 'summary-views-v2' / (key + '.json'))
    summary = copy.deepcopy(payload['marketSummary'])
    original_ids = list(summary['evidenceIds'])
    contexts, evidence = {}, []
    for sid in original_ids:
        if sid in sources:
            evidence.append(sid)
        elif sid in ('context:market', 'context:sessions', 'context:previous'):
            value = packet['references'][sid]
            if sid == 'context:sessions' and instant(value['cutoff']) != instant(payload['dataAsOf']):
                raise ValueError('foreign session context')
            if sid == 'context:previous' and value.get('cutoff') and instant(value['cutoff']) >= instant(payload['dataAsOf']):
                raise ValueError('future previous context')
            contexts[sid] = dict(sha256=digest(canonical(value)), value=value)
        else:
            raise ValueError('unresolved summary reference')
    if not evidence:
        raise ValueError('summary has no article evidence')
    # Server evidenceIds enumerate actual article citations only. The original
    # model reference list and full context snapshots are retained separately.
    summary['evidenceIds'] = sorted(set(evidence))
    priority = dict(schemaVersion='briefing-priority-summary-v1', roundId=payload['id'],
                    cutoff=payload['dataAsOf'], resultVersion=summary['resultVersion'],
                    text=summary['text'], evidenceIds=summary['evidenceIds'])
    context = dict(schemaVersion='briefing-priority-context-v1', roundId=payload['id'],
                   cutoff=payload['dataAsOf'], originalReferenceIds=original_ids, contexts=contexts)
    return summary, priority, context


def item_projection(item, generated, sources):
    evidence = [sources[s['evidenceId']] for s in item['sources']]
    text = '\n\n'.join(a['companyName'] + ' · ' + a['confirmedFact'] for a in item['aiAnalyses'])
    return dict(eventId=item['issueId'], rank=0, title=item['title'], reason=item['reason'],
                eventTime=None, timePrecision='unknown', reportedAt=min(s['publishedAt'] for s in evidence),
                evidenceCount=len(evidence), evidenceIds=[s['evidenceId'] for s in item['sources']],
                matchedCompanyIds=[], documentSentiments=[],
                companies=[dict(id=c['companyId'], name=c['name'], role=c['reason'], roleUnconfirmed=False,
                                relationType='INVOLVES') for c in item['companies']],
                summary=dict(text=text, evidenceIds=[s['evidenceId'] for s in item['sources']],
                             generatedAt=generated, resultVersion=item['analysisResultVersion']),
                sourceSupport=dict(articleCount=len({s['documentId'] for s in evidence}), knownLineageCount=None,
                                   independentSourceCount=None, unknownLineageArticles=sorted({s['documentId'] for s in evidence}), duplicateGroups=[]))


def company_record(cid, name):
    exchange, _, ticker = cid.partition(':')
    listed = exchange in ('KRX', 'NASDAQ', 'NYSE')
    return dict(id=cid, name=name, ticker=ticker if listed else None, exchange_code=exchange if listed else None,
                name_key=name.casefold(), search_text=name+' '+cid, aliases=[], profile={})


def prepare(input_sqlite, native, release, personal_release, profile_file, output):
    if output.exists():
        raise ValueError('output already exists; never overwrite a preparation')
    protected = [input_sqlite.resolve(), native / 'corpus-v2/units.json', profile_file,
                 release / 'release-v2-effective-results.json', personal_release / 'effective-results.json']
    original_hashes = {str(p): digest(p.read_bytes()) for p in protected}
    archive = rows(input_sqlite)
    units, sources, candidates, appearances, assessments = source_registry(native, release, personal_release)
    observations = {}
    for did, unit in units.items():
        path = Path(unit['index']['recordPath'])
        record_raw = path.read_bytes()
        if digest(record_raw) != unit['rawRecordSha256']:
            raise ValueError('retained collection record changed')
        original_hashes[str(path)] = digest(record_raw)
        observed = load(path)['observedAt']
        instant(observed)
        observations[did] = dict(documentId=did, originalObservation=unit['observation'], collectedAt=observed,
            publicationAvailableAfter=unit['availableAfter'], rawRecordSha256=unit['rawRecordSha256'])
    common = {r['payload']['id']: r for r in archive if r['scope'] == 'common'}
    personal = {r['payload']['id']: r for r in archive if r['scope'] == 'personal'}
    if set(common) != set(personal):
        raise ValueError('missing paired common or personal round')
    profile = load(profile_file)
    member_ref = 'source-member-' + digest(profile['member_id'].encode())[:20]
    choice = profile['choice']
    tables = {k: [] for k in ('companies', 'artifacts', 'articles', 'article_versions', 'evidence',
                              'briefing_rounds', 'briefing_personal_pools', 'briefing_personal_preferences', 'briefing_personal_deliveries')}
    tables['briefing_personal_preferences'].append(dict(id='prep-pref-' + digest(profile['preference_id'].encode())[:24],
        member_id=None, revision=1, choice=choice, created_at=profile['created_at'], effective_from=profile['effective_from']))
    contexts, checks, required_ids, contracts = [], [], set(), []
    now = datetime.now(timezone.utc).isoformat()
    for rid, record in sorted(common.items(), key=lambda kv: instant(kv[1]['payload']['dataAsOf'])):
        raw = record['payload']; personal_raw = personal[rid]['payload']
        verified_ids = {i['issueId'] for r in archive if instant(r['payload']['dataAsOf']) <= instant(raw['dataAsOf'])
                        for i in r['payload'][r['scope']+'Priority']['items'] if i.get('aiAnalyses')
                        and all(a['verificationMode'] == 'separate_request_same_model' for a in i['aiAnalyses'])}
        priority = copy.deepcopy(raw['commonPriority']); personal_priority = copy.deepcopy(personal_raw['personalPriority'])
        if priority['roundId'] != rid or personal_priority['roundId'] != rid or set(personal_priority['companyIds']) != set(choice['companyIds']):
            raise ValueError('priority or frozen member scope mismatch')
        summary, priority_summary, context = project_summary(raw, release, sources)
        contexts.append(context)
        items = [item_projection(i, raw['generatedAt'], sources) for i in priority['items']]
        for n, item in enumerate(items, 1):
            item['rank'] = n
        evidence_ids = sorted(set(priority_summary['evidenceIds']) | {sid for i in items for sid in i['evidenceIds']})
        required_ids.update(evidence_ids)
        meta = copy.deepcopy(raw['metadata'])
        meta.update(source='zoop-briefing-publication-clock-simulation', graphVersion=None)
        meta['selection'] = dict(basis='market', reason='기존 생성 결과의 과거 시뮬레이션 반입 준비본입니다.')
        payload = dict(id=rid, date=raw['date'], edition=raw['edition'], scheduledAt=raw['scheduledAt'],
            generatedAt=raw['generatedAt'], dataWindow=raw['dataWindow'], graphVersion=None,
            reviewRevision=0, ruleRevision=0, selectedFrom=max(priority['candidateCount'], len(items)),
            items=items, references=dict(eventIds=[i['eventId'] for i in items],
                companyIds=sorted({c['id'] for i in items for c in i['companies']}), evidenceIds=evidence_ids),
            emptyReason=None if items else 'no_issues_in_window', marketVariables=raw['marketVariables'], metadata=meta, outlook=raw['outlook'])
        docs = sorted({(sources[s]['documentId'], sources[s]['documentVersion']) for s in evidence_ids})
        bindings = [dict(documentId=d, documentVersion=v, grantId=None, grantRevision=None, recipients=[])
                    for d, v in docs]
        snapshot = dict(marketSummary=summary, commonPriority=priority, prioritySummary=priority_summary,
                        priorityContext=context, sourceBindings=bindings)
        row = dict(id=rid, round_date=raw['date'], edition=raw['edition'], scheduled_at=raw['scheduledAt'],
            window_from=raw['dataWindow']['start'], window_to=raw['dataAsOf'], open_start=raw['dataWindow']['openStart'],
            status='scheduled', review_revision=0, rule_revision=0, graph_version_id=None,
            published_payload=payload, public_snapshot=snapshot, schema_version='zoop-briefing-read-v1',
            payload_sha256=None, generated_at=raw['generatedAt'], published_at=None,
            comparison_snapshot=None if raw['edition']=='morning' else dict(status='unavailable', reason='이전 비교 문안은 보존된 AI 분석에 포함되며 정식 비교 스냅샷 등록은 대기 중입니다.'))
        tables['briefing_rounds'].append(row)
        # Include the complete retained eligible corpus up to the cutoff, plus
        # the original tracking candidates. Never copy common picks as personal picks.
        pool_items = []
        for iid, candidate in sorted(candidates.items()):
            if not any(instant(p['cutoff']) <= instant(raw['dataAsOf']) for p in appearances[iid]):
                continue
            src = [dict(evidenceId=sid, quote=s['quote'], url=s['url'], publishedAt=s['publishedAt'],
                        documentId=s['documentId'], documentVersion=s['documentVersion'], bodySha256=s['bodySha256'],
                        grantId=None, grantRevision=None, recipients=[]) for sid in candidate['sources'] for s in [sources[sid]]]
            if any(instant(s['publishedAt']) > instant(raw['dataAsOf']) for s in src):
                raise ValueError('future pool source')
            links = [dict(companyId=c['companyId'], name=c['name'], reason=c.get('role') or '원문 추출 관련 기업',
                          directnessStatus='not_classified_by_preparation', evidenceIds=c['evidenceIds']) for c in candidate['companies']]
            pool_items.append(dict(issueId=iid, title=candidate['title'], importance=assessments.get(iid, {}).get('businessImportance', 0),
                verified=iid in verified_ids, companies=links, sources=src, verificationBasis='reused_saved_briefing_analysis' if iid in verified_ids else 'not_promoted_by_preparation'))
        for item in personal_priority['items']:
            match = next((i for i in pool_items if i['issueId']==item['issueId']), None)
            if not match:
                raise ValueError('personal issue absent from retained candidate pool')
            for s in item['sources']:
                source = sources[s['evidenceId']]
                if s['quote'] != source['quote'] or s['url'] != source['url'] or instant(s['publishedAt']) != instant(source['publishedAt']):
                    raise ValueError('personal source mismatch')
                required_ids.add(s['evidenceId'])
                if s['evidenceId'] not in {v['evidenceId'] for v in match['sources']}:
                    if instant(source['publishedAt']) > instant(raw['dataAsOf']):
                        raise ValueError('future personal supplemental source')
                    match['sources'].append(dict(evidenceId=s['evidenceId'], quote=source['quote'], url=source['url'],
                        publishedAt=source['publishedAt'], documentId=source['documentId'],
                        documentVersion=source['documentVersion'], bodySha256=source['bodySha256'],
                        grantId=None, grantRevision=None, recipients=[]))
        pool = dict(schemaVersion='personal-candidate-pool-v1', complete=True, roundId=rid,
            cutoff=raw['dataAsOf'], candidateCount=len(pool_items), candidates=pool_items,
            scope='retained_eligible_corpus_and_previous_tracking; historical_simulation')
        pool['inputSha256'] = digest(canonical(pool))
        tables['briefing_personal_pools'].append(dict(id='prep-pool-'+digest(rid.encode())[:24], round_id=rid,
            input_sha256=pool['inputSha256'], snapshot=pool, snapshot_sha256=None))
        presentation = copy.deepcopy(personal_raw)
        for private_key in ('issueIntelligence', 'localReview'):
            presentation.pop(private_key, None)
        presentation['items'] = []
        presentation['references'] = dict(eventIds=[i['issueId'] for i in personal_priority['items']],
            companyIds=sorted({c['companyId'] for i in personal_priority['items'] for c in i['connections']}),
            evidenceIds=sorted({s['evidenceId'] for i in personal_priority['items'] for s in i['sources']}))
        presentation['marketSummary'] = dict(status='unavailable', reason='재선정 이전 회차 요약은 원본 기록에 보존했습니다. 새 개인화 이슈의 영향·전망은 아래에서 확인할 수 있습니다.')
        selection = dict(roundId=rid, poolVersion=pool['inputSha256'], choice=choice,
            selectionVersion=personal_priority['resultVersion'], presentation=presentation,
            verifiedPresentation=copy.deepcopy(presentation), tracking=[], minimumShortfall=0,
            status='ready', analysisStatus='ready', eligibleCount=personal_priority['candidateCount'],
            matchingCount=len(personal_priority['items']))
        tables['briefing_personal_deliveries'].append(dict(id='prep-delivery-'+digest((rid+member_ref).encode())[:24],
            member_id=None, round_id=rid, preference_id=tables['briefing_personal_preferences'][0]['id'],
            mode='demo', scheduled_at=raw['scheduledAt'], selection_snapshot=selection, selection_sha256=None,
            result_snapshot=copy.deepcopy(selection), result_sha256=None, status='ready', finished_at=now))
        for scope, v in [('common',priority),('personal',personal_priority)]:
            contracts.append(dict(scope=scope, roundId=rid, cutoff=raw['dataAsOf'], priority=v))
        checks.append(dict(roundId=rid, commonIssues=len(items), personalIssues=len(personal_priority['items']),
                           sourceCommonSha256=record['sha256'], sourcePersonalSha256=personal[rid]['sha256'],
                           sourcePublishedAt=raw['publishedAt'], stagingStatus='scheduled', publicationReady=False))
    # Pool sources must exist even when not selected.
    required_ids.update(s['evidenceId'] for p in tables['briefing_personal_pools'] for c in p['snapshot']['candidates'] for s in c['sources'])
    companies = {company['companyId']:company['name'] for candidate in candidates.values() for company in candidate['companies']}
    for cid in choice['companyIds']:
        companies.setdefault(cid, cid)
    tables['companies'] = [company_record(cid,name) for cid,name in sorted(companies.items())]
    output.mkdir(parents=True, mode=0o700)
    files = {}
    def write(name, raw):
        path = output / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True); path.parent.chmod(0o700)
        with path.open('xb') as f:
            path.chmod(0o600); f.write(raw)
        files[name] = dict(sha256=digest(raw), bytes=len(raw))
    docs = {sources[s]['documentId'] for s in required_ids}
    def artifact(kind, raw, suffix):
        sha = digest(raw); aid='prep258-'+kind+'-'+sha
        name='artifacts/'+sha+suffix
        if name not in files:
            write(name,raw)
            tables['artifacts'].append(dict(id=aid, kind=kind, storage_uri='artifact-root:'+name, sha256=sha,
                bytes=len(raw), media_type='application/json' if suffix=='.json' else 'text/plain', created_at=now))
        return aid
    for did in sorted(docs):
        unit = units[did]; raw = unit['text'].encode(); aid=artifact('extracted_text',raw,'.txt')
        s=next(s for s in sources.values() if s['documentId']==did)
        tables['articles'].append(dict(id=did, kind='news', provider=s['publisher'], access_status='private', current_version=None, created_at=now))
        tables['article_versions'].append(dict(article_id=did, version=s['documentVersion'], title=unit['title'],
            publisher=s['publisher'], url=s['url'], published_at=s['publishedAt'], published_date=None,
            publication_precision='datetime', text_artifact_id=aid, raw_artifact_id=None, collected_at=observations[did]['collectedAt']))
    for sid in sorted(required_ids):
        s=sources[sid]; receipt=dict(schemaVersion='exact-source-span-preparation-v1', evidenceId=sid,
            documentId=s['documentId'], bodySha256=s['bodySha256'], quoteSha256=digest(s['quote'].encode()),
            start=s['start'], end=s['end'], offsetUnit='unicode_code_point',
            exactMatch=True, semanticApproval=False, publicUseAuthorized=False)
        receipt_id=artifact('verification_receipt',canonical(receipt),'.json')
        tables['evidence'].append(dict(id=sid, article_id=s['documentId'], article_version=s['documentVersion'],
            text_artifact_id='prep258-extracted_text-'+s['bodySha256'], quote=s['quote'], start_offset=s['start'],
            end_offset=s['end'], offset_unit='unicode_code_point', input_kind='body',
            raw_locator_ids=[s.get('nativeEventCandidateId') or 'exact-span:'+s['bodySha256']+':'+str(s['start'])],
            quote_verified=True, verification_artifact_id=receipt_id, verified_at=now, created_at=now))
    for row in archive:
        write('archive/'+row['scope']+'/'+row['day']+'-'+row['edition']+'.json', row['raw'].encode())
    language_findings = []
    def scan(value, path, scope, rid):
        if isinstance(value, dict):
            for k, v in value.items():
                scan(v, path+[k], scope, rid)
        elif isinstance(value, list):
            for k, v in enumerate(value):
                scan(v, path+[k], scope, rid)
        elif isinstance(value, str) and re.search('[\u3040-\u30ff]', value):
            language_findings.append(dict(scope=scope, roundId=rid, path=path,
                finding='kana_in_saved_analysis', originalSha256=digest(value.encode()), corrected=False))
    for row in archive:
        scan(row['payload'][row['scope']+'Priority'], [row['scope']+'Priority'], row['scope'], row['payload']['id'])
    write('language-findings.json',canonical(language_findings))
    for table,data in tables.items():
        write('tables/'+table+'.jsonl',b''.join(canonical(r)+b'\n' for r in data))
    write('contexts.jsonl',b''.join(canonical(c)+b'\n' for c in contexts))
    write('source-observations.jsonl',b''.join(canonical(observations[did])+b'\n' for did in sorted(docs)))
    write('priority-contracts.jsonl',b''.join(canonical(c)+b'\n' for c in contracts))
    write('round-checks.json',canonical(checks))
    pending = ['current_document_publication_authority', 'registered_public_graph_version',
               'target_member_mapping_and_demo_scope', 'target_database_collision_check',
               'historical_context_registry_binding', 'language_findings_review', 'candidate_relation_directness_review']
    manifest=dict(schemaVersion='briefing-server-staging-bundle-v1', pr=553, sourceCommit='b47701d0221ab44da192aac420cf9f5af3dc793d',
        sourceFiles=original_hashes, files=files, tableCounts={k:len(v) for k,v in tables.items()},
        memberBindingRef=member_ref, targetMemberId=None, publicationReady=False, pendingChecks=pending,
        noAutomaticPublish=True, sourceResultsPreserved=True, newAiCalls=0,
        notes=['Staged rows are not historical operational deliveries.', 'Grant IDs and recipients are unresolved, never fabricated.',
               'JSONB digest columns must be computed by PostgreSQL, not copied from canonical JSON hashes.',
               'Legacy personal summaries remain in the byte-exact archive; priority issue analyses are unchanged.'])
    write('manifest.json',canonical(manifest))
    if any(digest(Path(p).read_bytes())!=sha for p,sha in original_hashes.items()):
        raise ValueError('source changed during preparation')
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('input-sqlite','native-root','release-root','personal-release-root','profile-file','output'):
        p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    result=prepare(a.input_sqlite.resolve(),a.native_root.resolve(),a.release_root.resolve(),a.personal_release_root.resolve(),a.profile_file.resolve(),a.output.resolve())
    print(json.dumps({k:result[k] for k in ('tableCounts','publicationReady','newAiCalls','sourceResultsPreserved')}))


if __name__=='__main__':
    main()
