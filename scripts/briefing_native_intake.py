"""Bounded KOGL1 acquisition -> native S2/S3 -> current-authority handoff, for one briefing slot.

Uses the production native engines and their real verifier. Never authors verdicts or
approves a HOLD. All state and raw receipts stay on the private durable worker volume.
"""
from __future__ import annotations
import copy,fcntl,hashlib,json,os,re
from datetime import datetime,timedelta,timezone
from pathlib import Path
import httpx
import briefing_server_runtime as server
import briefing_call_limits as limits
from briefing_usage import CommandPipe,UsageSession,write_once

b=server.b
require=server.require
SCHEMA='briefing-native-intake-v1'
INPUT_PRIORITY='briefing-source-priority-v4'
BUSINESS_ACTION=re.compile(r'계약|수주|투자|인수|합병|매출|영업이익|손실|실적|공급|생산|양산|공장|출시|허가|승인|규제|제재|소송|리콜|가동.{0,8}중단|증자|배당|자사주|납품|도입|철회|취소|감산|증설|contract|revenue|earnings|investment|acqui|factory|production|launch|approval|recall|layoff',re.I)

def source_priority(title,text,companies,matches):
    """Input preparation order, never a business-importance or sentiment verdict."""
    relevant=[c for c in companies if c['companyId'] in matches]
    head=source_matches(title,relevant)
    clauses=[p for p in re.split(r'[\n.!?。]+',text) if BUSINESS_ACTION.search(p)
             and source_matches(p,relevant)]
    score=(int(bool(head) and bool(BUSINESS_ACTION.search(title))),min(len(clauses),3),int(bool(head)))
    return {'version':INPUT_PRIORITY,'rank':list(score),'headlineCompanyIds':head,
            'businessClauseCount':len(clauses),'meaning':'preparation relevance only; native and independent verification still required'}

def source_rank(entry):
    row,_,_,_=entry
    return (*row['inputPriority']['rank'],row['candidate']['publicationDay'],row['candidate']['url'])

def attempted_documents(base):
    processed=set()
    for ready_path in base.glob('*/*-native-v2/ready.json'):
        ready=json.loads(ready_path.read_bytes());processed.add((ready['documentId'],ready['documentVersion']))
    for selected_path in base.glob('*/selected-source.json'):
        if any(selected_path.parent.glob('*-native-v2/native.started.json')):
            prior=json.loads(selected_path.read_bytes());processed.add((prior['documentId'],prior['documentVersion']))
    for selected_path in base.glob('*/candidates-v3/*/selected-source.json'):
        if (selected_path.parent/'native.started.json').exists():
            prior=json.loads(selected_path.read_bytes());processed.add((prior['documentId'],prior['documentVersion']))
    return processed

def atomic(path,value):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    raw=b.canonical(value);temp=path.with_name('.'+path.name+'.'+os.urandom(8).hex())
    with temp.open('xb') as stream:
        os.chmod(temp,0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def source_matches(text,companies):
    """Relevance only. Actual roles and importance still need native and independent model checks."""
    from briefing_company_names import matches
    return matches(text,companies)


def relevance_text(raw):
    """Disposable article DOM for picking inputs; never changes native text or citation offsets."""
    from zoop_ai_pipeline.korea_portal import BODY_XPATH,tree,text as node_text
    body=tree(raw).xpath(BODY_XPATH);require(len(body)==1,'article_scope')
    excluded={'law_copy_wrap','area_page','view_opt','share','share_lst'}
    for node in list(body[0].iterdescendants()):
        if not isinstance(node.tag,str):continue
        if node.tag in ('script','style','button') or excluded.intersection((node.get('class') or '').split()):
            if node.getparent() is not None:node.getparent().remove(node)
    return node_text(body[0])

def collect(cfg,round,root,*,all_candidates=False):
    from zoop_ai_pipeline.korea_corpus import Config,run,package
    base=Path(cfg['work'])/'native';root.mkdir(mode=0o700,parents=True,exist_ok=True)
    config_path=root/'collection-config.json'
    if cfg.get('recordedOnly'):
        require(config_path.is_file() and (root/'collection-result.json').is_file(),'recorded_collection_required')
    if not config_path.exists():
        exclusions=set()
        for state in base.glob('*/collection/STATE.json'):
            old=json.loads(state.read_bytes())
            exclusions.update(i for i,row in old['items'].items() if row['outcome'] not in ('pending',))
        rights={'reviewedAt':b.now(),'authorizationRef':cfg['authorizationRef'],
            'policyUrl':'https://www.korea.kr/guide/copyRight.do',
            'rule':'Exact article-level KOGL1 text-only badge and original title/outlet/day required. Preserve attribution; no images, attachments or third-party works.',
            'collectionOnly':True,'models':'None in acquisition. A separate prospective processing grant is required.'}
        refs={}
        for name,value in [('rights',rights),('exclusions',{'schemaVersion':'zoop-korea-exclusions-1','newsIds':sorted(exclusions)})]:
            path=root/(name+'.json');write_once(path,value);refs[name]={'path':str(path),'sha256':b.digest(path.read_bytes())}
        until=datetime.fromisoformat(round['windowTo']).astimezone(server.KST).date()
        start=datetime.fromisoformat(round['windowFrom']).astimezone(server.KST).date()
        config={'schemaVersion':'zoop-korea-corpus-1','planId':round['id']+'-sources-v1','stateDir':str(root/'collection'),
            'fromDay':str(start),'throughDay':str(until),'listingOrigin':'https://www.korea.kr','articleOrigin':'https://m.korea.kr',
            'exactHosts':['www.korea.kr','m.korea.kr'],
            'channels':[{'name':'policy-news','maxPages':2,'maxDocuments':20},{'name':'press-release','maxPages':3,'maxDocuments':35},
                        {'name':'clarifications','maxPages':1,'maxDocuments':5}],
            'maxListingPages':6,'maxCandidates':120,'maxDocuments':60,
            'policy':{'schemaVersion':'zoop-collection-policy-1','userAgent':'ZoopTextCorpus/1.0','timeoutSeconds':30,
                'maxTotalSeconds':360,'maxRedirects':0,'maxRequests':100,'maxResponseBytes':5000000,'maxTotalBytes':100000000,
                'minIntervalSeconds':2.0,'allowedMediaTypes':['text/html'],'syntheticLoopback':False},
            'grant':{'grantId':round['id']+'-acquisition','revision':'kogl1-text-v1','sourceId':'korea-portal','enabled':True,
                'rights':'known','allowedOperations':['read','store','quote-display'],'recipients':[],'purposes':[],
                'evidence':[rights['policyUrl'],rights['rule']],'expiresAt':None},
            'rightsEvidence':refs['rights'],'exclusionManifest':refs['exclusions']}
        write_once(config_path,config)
    config=Config.model_validate_json(config_path.read_bytes())
    result=json.loads((root/'collection-result.json').read_bytes()) if (root/'collection-result.json').exists() else run(config)
    write_once(root/'collection-result.json',result)
    catalogue=json.loads(Path(cfg['companyCatalogue']).read_bytes())
    from briefing_company_names import catalogue_companies
    companies=catalogue_companies(catalogue)
    eligible=[]
    # Reuse unprocessed acquisitions from this owned worker, without fetching them or changing their clocks.
    cohorts=[(root,result)]
    for package in sorted(base.glob('*/collection-result.json')):
        if package.parent!=root and not package.is_symlink():cohorts.append((package.parent,json.loads(package.read_bytes())))
    # A withheld or unknown paid preparation is not a fresh source to send again.
    processed=attempted_documents(base)
    seen=set()
    for collection_root,cohort in cohorts:
      for row in cohort['documents']:
        identity=(row['documentId'],row['documentVersion'])
        observed=datetime.fromisoformat(row['fetchedAt'])
        if identity in seen or identity in processed or not datetime.fromisoformat(round['windowFrom'])<observed<=datetime.fromisoformat(round['windowTo']):continue
        seen.add(identity)
        exported=json.loads((collection_root/'collection'/row['exportFile']).read_bytes())
        native=collection_root/'collection/native/collections'/('item-'+row['candidate']['newsId'])
        raw=(native/'bodies'/(row['nativeBodySha256']+'.bin')).read_bytes()
        require(b.digest(raw)==row['nativeBodySha256'],'native_body_pin')
        text=relevance_text(raw);matches=source_matches(text,companies)
        if matches:
            row={**row,'inputPriority':source_priority(row['candidate']['title'],text,companies,matches)}
            eligible.append((row,exported,matches,collection_root))
    official_coverage={'enabled':cfg.get('samsungNewsroomEnabled') is True,'retained':0,'excludedOrUnavailable':0}
    if cfg.get('samsungNewsroomEnabled') is True:
        import briefing_samsung_intake as samsung
        if cfg.get('recordedOnly'):require((root/'samsung-newsroom/result.json').is_file(),'recorded_official_collection_required')
        official=samsung.collect(cfg,round,root);official_coverage['retained']=len(official)
        official_coverage['excludedOrUnavailable']=len(json.loads((root/'samsung-newsroom/result.json').read_bytes())['errors'])
        for row,exported,selected_root in official:
            identity=(row['documentId'],row['documentVersion'])
            if identity in seen or identity in processed:continue
            seen.add(identity)
            text=exported['document']['text'];matches=source_matches(text,companies)
            if matches:
                row={**row,'inputPriority':source_priority(row['candidate']['title'],text,companies,matches)}
                eligible.append((row,exported,matches,selected_root))
    import briefing_news_intake as news
    if cfg.get('recordedOnly') and cfg.get('newsSourceRegistry'):
        require((root/'news-sources/result.json').is_file(),'recorded_news_collection_required')
    news_entries,news_result=news.collect(cfg,round,root)
    for row,exported,selected_root in news_entries:
        identity=(row['documentId'],row['documentVersion'])
        if identity in seen or identity in processed:continue
        seen.add(identity)
        text=exported['document']['text'];matches=source_matches(text,companies)
        if matches:
            row={**row,'inputPriority':source_priority(row['candidate']['title'],text,companies,matches)}
            eligible.append((row,exported,matches,selected_root))
    eligible.sort(key=source_rank,reverse=True)
    coverage={'complete':False,'candidateDocuments':len(eligible),'selectedDocuments':min(1,len(eligible)),
        'collection':result['counts'],'samsungNewsroom':official_coverage,
        'newsSources':{k:news_result[k] for k in ('status','sources','modelCalls','memberSpecificRequests')}}
    write_once(root/'source-coverage.json',coverage)
    require(bool(eligible),'no_current_company_source')
    if all_candidates:
        return [({**row,'coverage':coverage,'matchedCompanyIds':matched},exported,companies,selected_root) for row,exported,matched,selected_root in eligible]
    chosen,exported,matches,selected_root=eligible[0]
    write_once(root/'selected-source.json',{'candidate':chosen['candidate'],'documentId':exported['document']['documentId'],
        'documentVersion':exported['document']['documentVersion'],'matchedCompanyIds':matches,
        'nativeBodySha256':chosen['nativeBodySha256'],'nativeReceiptSha256':chosen['nativeReceiptSha256'],'collectionRoot':str(selected_root),
        'inputPriority':chosen['inputPriority'],
        'coverage':coverage})
    return chosen,exported,companies,selected_root

class NativeTransport(httpx.BaseTransport):
    def __init__(self,session,budget,root):
        self.session,self.budget,self.root=session,budget,root
        self.peer=httpx.HTTPTransport(retries=0)
    def handle_request(self,request):
        raw=request.content;value=json.loads(raw);host=request.url.host
        provider='openai' if host=='api.openai.com' else 'typesafe' if host=='api.typesafe.ai' else None
        require(provider is not None and request.method=='POST' and request.url.scheme=='https','native_provider')
        model=value.get('model');require(model==('gpt-6-luna' if provider=='openai' else 'jev-1.14.0'),'native_model')
        require(value.get('store') is not True and (provider!='openai' or value.get('service_tier')=='default'),'native_request_policy')
        rows=list((Path(self.budget.cfg['work'])/'budget').glob('*.json'))
        require(sum(json.loads(p.read_bytes()).get('roundId')==self.budget.round_id and json.loads(p.read_bytes()).get('phase')=='native' for p in rows)<self.budget.cfg.get('nativeCallLimit',12),'native_phase_call_limit')
        reservation=self.budget.reserve_physical(raw,value.get('max_completion_tokens',0),provider,model,phase='native',input_multiplier=max(1,len(value.get('questions',[]))))
        key=reservation[0]
        stage=value.get('response_format',{}).get('json_schema',{}).get('name','native_verification')
        stage='native_'+re.sub('[^a-z0-9_]','_',stage.lower())[:65]
        self.session.stage=stage
        started=self.session.send('model_start',callId=key,stage=stage,feature='briefing',provider=provider,model=model,
            promptVersion='native-'+b.digest(raw)[:16],retryUnit=None,reasoningEffort=value.get('reasoning_effort'))
        require(started.get('created') is True,'native_existing_attempt_not_resent')
        write_once(self.root/(key+'.request.json'),{'requestDigest':key,'bytes':len(raw),'provider':provider,'model':model})
        try:
            response=self.peer.handle_request(request)
            parts=[];size=0
            try:
                for chunk in response.iter_bytes():
                    size+=len(chunk);require(size<=8*1024*1024,'native_response_too_large');parts.append(chunk)
                answer=b''.join(parts)
            finally:response.close()
        except BaseException:
            self.session._finish(self.session._receipt(key,'unknown',None,None,None,None,'transport_unknown',None));raise
        self.budget.settle(reservation,answer)
        write_once(self.root/(key+'.response.json'),{'httpStatus':response.status_code,'body':answer.decode('utf-8',errors='replace')})
        try:parsed=json.loads(answer)
        except (ValueError,UnicodeError):parsed={}
        usage=parsed.get('usage') or {}
        def tokens(a,z):
            v=usage.get(a,usage.get(z));return v if type(v) is int and v>=0 else None
        inp,out=tokens('input_tokens','prompt_tokens'),tokens('output_tokens','completion_tokens')
        self.session.estimate={'currency':'USD','priceVersion':'provider-standard-usd-20261103','inputPerMillion':0.10 if provider=='openai' else 0.042,'outputPerMillion':0.50 if provider=='openai' else 0}
        state='succeeded' if 200<=response.status_code<300 else 'failed'
        self.session._finish(self.session._receipt(key,state,True,inp,out,b.digest(answer),None if state=='succeeded' else 'provider_http_error',parsed.get('model')))
        headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-encoding','content-length','transfer-encoding')}
        return httpx.Response(response.status_code,headers=headers,content=answer,request=request)
    def close(self):
        # Individual runtime HTTP clients borrow this transport; the slot owns its lifetime.
        pass
    def shutdown(self):self.peer.close()

def read_verifier(path):
    import stat
    require(not path.is_symlink() and stat.S_IMODE(path.stat().st_mode)==0o600,'private_verifier_file')
    key=path.read_text().strip().removeprefix('TYPESAFE_API_KEY=')
    require(bool(key) and not any(c.isspace() for c in key),'verifier_key_format')
    return key

def configure_runtime(cfg,root,cutoff):
    from zoop_ai_pipeline.live_runtime import LiveRuntime
    start=datetime.now(timezone.utc)
    end=datetime.fromisoformat(cfg.get('recoveryDeadline') or cutoff).astimezone(timezone.utc)
    require((end-start).total_seconds()>190,'native_preparation_window')
    calls = cfg.get('nativeDocumentCallLimit', 12)
    output = 30000 if cfg.get('selectionContinuation') else 12000
    os.environ.update({'ZOOP_AI_PIPELINE_LIVE_ENABLED':'1','ZOOP_AI_PIPELINE_LIVE_MODEL':'gpt-6-luna',
        'ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT':'high','ZOOP_AI_PIPELINE_LIVE_MAX_OUTPUT_TOKENS':str(output),
        'ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS':'180','ZOOP_AI_PIPELINE_LIVE_MAX_CALLS':str(calls),'ZOOP_AI_PIPELINE_LIVE_MAX_USD':'1',
        'ZOOP_AI_PIPELINE_LIVE_SHARED_MAX_USD':'0.9','ZOOP_AI_PIPELINE_LIVE_PERSONAL_MAX_USD':'0.1',
        'ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR':str(root/'native-budget'),'ZOOP_AI_PIPELINE_LIVE_PROFILE':'admitted-set-capped-v4',
        'ZOOP_AI_PIPELINE_LIVE_RUN_ID':root.name,'ZOOP_AI_PIPELINE_LIVE_SET_ID':root.name,
        'ZOOP_AI_PIPELINE_LIVE_ADMIT_FROM':start.strftime('%Y-%m-%dT%H:%M:%SZ'),'ZOOP_AI_PIPELINE_LIVE_ADMIT_UNTIL':(start+timedelta(seconds=60)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'ZOOP_AI_PIPELINE_LIVE_FINISH_BY':(end+timedelta(seconds=180)).strftime('%Y-%m-%dT%H:%M:%SZ'),'ZOOP_AI_PIPELINE_LIVE_OUTPUT_CONTRACT':'citation-refs-default-1',
        'ZOOP_AI_BASE_URL':'https://api.openai.com/v1','TYPESAFE_BASE_URL':'https://api.typesafe.ai/v1','TYPESAFE_VALIDATION_MODEL':'jev-1.14.0',
        'ZOOP_AI_API_KEY':b.read_key(Path(cfg['keyFile'])),'TYPESAFE_API_KEY':read_verifier(Path(cfg['verifierKeyFile']))})
    return LiveRuntime

def handoff(root,sources,ingestion,exported,s2,s3,companies):
    from zoop_ai_pipeline.graph_projection import review_state
    from zoop_ai_pipeline.ingestion_contracts import digest as native_digest
    from zoop_ai_pipeline.handoff import Store,Handoff,HandoffPaths
    from zoop_ai_pipeline.handoff_contracts import Manifest,Selector
    upstream={'jobId':s2['jobId'],'inputDigest':s2['inputDigest']}
    used=set()
    for relation in s3['relations']:
        if relation['eligibility']['status']!='eligible' or relation['eligibility']['reviewPending']:continue
        for endpoint in [relation['subject'],relation['object'],*[step[role] for step in relation['path'] for role in ('subject','object')]]:
            used.add((endpoint['kind'],endpoint['ref']))
    labels={c['companyId']:c['name'] for c in companies};entries=[];public_companies=[];issues=[]
    for kind,ref in sorted(used):
        if kind=='company':require(ref in labels,'catalogue_endpoint');identity=ref
        else:identity='brfi:'+b.digest(b.canonical([exported['document']['documentId'],exported['document']['documentVersion'],kind,ref]))
        entries.append({'upstream':upstream,'kind':kind,'ref':ref,'canonicalId':identity,'decisionRef':'native-identity-v1:'+kind})
        if kind=='company':public_companies.append({'canonicalId':identity,'publicId':identity,'label':labels[ref],'decisionRef':'native-catalogue-v1'})
        elif kind=='event':issues.append({'canonicalId':identity,'publicId':identity,'geography':{'classification':None,'countries':[],
            'evidence':[],'reasonCode':'not-supported','decisionRef':'no-country-verdict','decisionVersion':'v1'},
            'representative':None,'decisionRef':'native-event-identity-v1','fieldVerdicts':[],'summary':None})
    require(bool(issues),'no_independently_eligible_event')
    files={'canonical':{'schemaVersion':'zoop-graph-canonical-1','entries':entries},
        'decisions':{'schemaVersion':'zoop-public-decisions-5','policyVersion':'zoop-public-projection-policy-3',
            'companies':public_companies,'issues':issues,'structural':[],'follows':[],'origins':[]},
        'bindings':{'schemaVersion':'zoop-app-document-bindings-1','bindings':[{
            'documentId':exported['document']['documentId'],'documentVersion':exported['document']['documentVersion'],
            'articleId':exported['document']['documentId'],'articleVersion':exported['document']['documentVersion'],
            'textSha256':b.digest(exported['document']['text'].encode()),'offsetUnit':'unicode_code_point'}]}}
    hashes={}
    for name,value in files.items():path=root/(name+'.json');write_once(path,value);hashes[name]=b.digest(path.read_bytes())
    manifest={'schemaVersion':'zoop-ai-handoff-1','handoffId':root.name+'-handoff','sourceKind':'actual',
        'policyVersion':'zoop-public-projection-policy-3','sources':[{'relation':{'jobId':s3['jobId'],'inputDigest':s3['inputDigest']},
            'upstream':s3['binding']['upstream'],'reviewDigest':native_digest(review_state(s3))}],'files':hashes}
    paths=HandoffPaths(root/'s3',root/'s2',ingestion,sources,root/'canonical.json',root/'decisions.json',root/'bindings.json')
    store=Store(root/'handoff',root/'s3',root/'s2',ingestion,mode='create')
    try:
        engine=Handoff(store,paths);ready=engine.freeze(Manifest.model_validate(manifest))
        require(ready['state']=='ready','native_handoff_not_ready')
        envelope=engine.export(Selector.model_validate({'schemaVersion':'zoop-ai-handoff-1','handoffId':manifest['handoffId']}))
        write_once(root/'handoff-export.json',envelope)
        return manifest,envelope
    finally:store.close()


def source_qualification(root,s3,session):
    """A completed native analysis can still provide no independently eligible public company link."""
    require(s3.get('state')=='ready' and s3.get('delivery',{}).get('status')=='current','native_s3_not_current')
    approved=[r for r in s3['relations'] if r['eligibility']['status']=='eligible' and not r['eligibility']['reviewPending']
        and r['type']=='PARTICIPATES_IN' and r['direction']=='directed' and r['connection']=='direct'
        and r['subject']['kind']=='company' and r['object']['kind']=='event'
        and r['citations'] and not any('error' in c for c in r['citations'])]
    if approved:return None
    result={'schemaVersion':SCHEMA,'status':'withheld','reason':'no_verified_company_involvement',
        'relationCandidates':len(s3['relations']),'additionalModelCalls':0}
    write_once(root/'source-qualification.json',result)
    session.stage='source_qualification';session.outcome='withheld'
    return result

def candidate_pin(entry):
    chosen,exported,companies,selected_root=entry
    return {'candidate':chosen['candidate'],'documentId':exported['document']['documentId'],
        'documentVersion':exported['document']['documentVersion'],'matchedCompanyIds':chosen['matchedCompanyIds'],
        'nativeBodySha256':chosen['nativeBodySha256'],'nativeReceiptSha256':chosen['nativeReceiptSha256'],
        'collectionRoot':str(selected_root),'inputPriority':chosen['inputPriority'],'coverage':chosen.get('coverage',{})}


def received_failure(result,cfg,round_id):
    """A known received failure is not a missing response or an evidence rejection."""
    code = (result.get('failure') or {}).get('code')
    reasons = {'live_output_truncated': 'received_output_truncated',
               'live_set_work_exhausted': 'native_document_capacity'}
    usage = result.get('usage') or {}
    if result.get('state') != 'stopped' or code not in reasons:
        return None
    received = usage.get('receivedCalls')
    if received is None:
        # S3 exposes its per-call receipts rather than the S2 receivedCalls aggregate.
        calls=result.get('calls')
        if not isinstance(calls,list) or any(c.get('state')!='received'
                and not (c.get('state')=='refused' and c.get('verdict')==code) for c in calls):return None
        finished=[c for c in calls if c.get('state')=='received']
        if any(not re.fullmatch('[a-f0-9]{64}',str(c.get('responseDigest',''))) for c in finished):return None
        received=len(finished)
    if type(received) is not int or received<0 or type(usage.get('startedWithoutReceipt')) is not int \
            or usage.get('startedWithoutReceipt') != 0 or type(usage.get('providerCalls')) is not int \
            or usage.get('providerCalls') != received:
        return None
    # A shared write-ahead reservation without a response must never become a quiet bulletin.
    limits.remaining_native(cfg, round_id)
    return reasons[code]


def prepare_candidates(cfg,round,entries,collection_root,observer=None,qualifier=None):
    """Terminal quality failures move to the next unsent document, never a verdict upgrade."""
    notify=observer or (lambda *args:None)
    attempt_root=collection_root/'candidates-v3';attempt_root.mkdir(mode=0o700,parents=True,exist_ok=True)
    outcomes=[];reserved_common=limits.candidate_reserve(cfg)
    def accepted(result, qualified, pin):
        outcomes.append({'documentId':pin['documentId'],'status':'ready','reason':'selection_verified' if qualifier else 'native_verified'})
        outcomes.extend({'documentId':entry[1]['document']['documentId'],'status':'not_examined','reason':'selection_satisfied'}
                        for entry in entries[index+1:])
        proof={'schemaVersion':SCHEMA,'status':'ready','candidates':outcomes,
               'roundCallLimit':limits.round_limit(cfg),'publicationCallReserve':reserved_common}
        path=attempt_root/('outcomes-'+b.digest(b.canonical(proof))[:16]+'.json');write_once(path,proof)
        # Legacy import compares the request to the immutable ready.json byte-for-byte.
        return {**result,**qualified,'outcomeFile':str(path.relative_to(collection_root))} if qualifier else result
    for index,entry in enumerate(entries):
        pin=candidate_pin(entry);root=attempt_root/(round['id']+'-'+b.digest(b.canonical([pin['documentId'],pin['documentVersion']]))[:16]+'-native-v2')
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        write_once(root/'selected-source.json',pin)
        if (root/'ready.json').exists():
            result=json.loads((root/'ready.json').read_bytes())
            qualified=qualifier(result,root) if qualifier else {'status':'ready'}
            if qualified['status']=='ready':return accepted(result,qualified,pin)
            outcomes.append({'documentId':pin['documentId'],'status':'withheld','reason':qualified['reason']});continue
        if (root/'native.started.json').exists():
            # Closed/HOLD records remain preserved. Unknown sends are never replayed.
            if (root/'source-qualification.json').exists():
                if cfg.get('selectionContinuation'):limits.remaining_native(cfg,round['id'])
                prior=json.loads((root/'source-qualification.json').read_bytes())
                outcomes.append({'documentId':pin['documentId'],'status':'saved_withheld','reason':prior['reason']});continue
            raise ValueError('briefing_server_native_interrupted_requires_recovery')
        if cfg.get('selectionContinuation') and datetime.now(timezone.utc)+timedelta(seconds=200)>=datetime.fromisoformat(round['windowTo']):
            for remaining in entries[index:]:
                outcomes.append({'documentId':remaining[1]['document']['documentId'],'status':'not_sent','reason':'preparation_deadline'})
            break
        rows=[json.loads(p.read_bytes()) for p in (Path(cfg['work'])/'budget').glob('*.json')]
        own=[r for r in rows if r['roundId']==round['id']]
        native_calls=sum(r.get('phase')=='native' for r in own)
        # A normal successful native document needs 5 calls. Do not start one
        # that cannot fit while retaining generation AND independent checking.
        if len(own)+5+reserved_common>limits.round_limit(cfg) or native_calls+5>limits.native_limit(cfg):
            outcomes.append({'documentId':pin['documentId'],'status':'not_sent','reason':'remaining_shared_call_capacity'})
            for remaining in entries[index+1:]:
                outcomes.append({'documentId':remaining[1]['document']['documentId'],'status':'not_sent','reason':'remaining_shared_call_capacity'})
            break
        document_cfg=dict(cfg)
        if cfg.get('selectionContinuation'):
            document_cfg['nativeDocumentCallLimit'],document_cfg['nativeWorkLimits']=limits.document_work(cfg,round['id'],len(entries)-index)
        try:result=prepare_candidate(document_cfg,round,entry,root)
        except ValueError as error:
            if (not cfg.get('selectionContinuation') or (root/'native.started.json').exists()
                    or str(error) not in ('briefing_server_native_dispatch_deadline','briefing_server_native_preparation_window')):raise
            for remaining in entries[index:]:
                outcomes.append({'documentId':remaining[1]['document']['documentId'],'status':'not_sent','reason':'preparation_deadline'})
            break
        if result.get('status')!='withheld':
            qualified=qualifier(result,root) if qualifier else {'status':'ready'}
            if qualified['status']=='ready':
                notify('native','completed');return accepted(result,qualified,pin)
            result=qualified
        outcomes.append({'documentId':pin['documentId'],'status':'withheld','reason':result['reason']})
    reason=('preparation_deadline' if any(o['reason']=='preparation_deadline' for o in outcomes)
            else 'remaining_shared_call_capacity' if any(o['status']=='not_sent' for o in outcomes)
            else 'all_company_candidates_withheld')
    result={'schemaVersion':SCHEMA,'status':'withheld','reason':reason,'candidates':outcomes,
        'roundCallLimit':limits.round_limit(cfg),'nativeCallLimit':limits.native_limit(cfg),'publicationCallReserve':reserved_common}
    # New unique recovery roots keep older outcomes and unknown reservations intact.
    path=collection_root/'candidate-outcomes-v3.json'
    if path.exists():path=attempt_root/('outcomes-'+b.digest(b.canonical(result))[:16]+'.json')
    write_once(path,result)
    return {**result,'outcomeFile':str(path.relative_to(collection_root))}


def prepare(cfg,round,observer=None,qualifier=None):
    observer=observer or (lambda *args:None)
    collection_root=Path(cfg.get('recordedCollectionRoot') or Path(cfg['work'])/'native'/round['id'])
    legacy=collection_root/(round['id']+'-native-v2')/'ready.json'
    if not qualifier:
        if legacy.exists():return json.loads(legacy.read_bytes())
        for ready in sorted((collection_root/'candidates-v3').glob('*/ready.json')):
            return json.loads(ready.read_bytes())
    observer('collection','started')
    entries=collect(cfg,round,collection_root,all_candidates=True)
    observer('collection','completed');observer('native','started')
    return prepare_candidates(cfg,round,entries,collection_root,observer,qualifier)


def prepare_candidate(cfg,round,entry,root):
    from zoop_ai_pipeline import extraction,relation
    from zoop_ai_pipeline.extraction_contracts import Submit
    from zoop_ai_pipeline.relation_contracts import Submit as RelationSubmit
    from zoop_ai_pipeline.ingestion_contracts import Authority
    chosen,exported,companies,selected_collection=entry
    runtime_type=configure_runtime(cfg,root,round['windowTo']);pure=runtime_type.from_env()
    original=Path(chosen['nativeItemRoot']) if chosen.get('nativeItemRoot') else selected_collection/'collection/items'/chosen['candidate']['newsId']
    sources=Path(cfg['authorityRoot'])/('source-'+root.name+'.json');sources.parent.mkdir(mode=0o700,parents=True,exist_ok=True);current=json.loads((original/'sources.json').read_bytes())
    grant=current['sources'][0]['grant'];grant.update({'grantId':root.name+'-processing','revision':('news-source-prospective-v1' if chosen['rights'].get('rightsBasis')=='explicit-current-source-authority' else 'first-party-prospective-v1') if chosen.get('sourceId') else 'kogl1-prospective-v2',
        'allowedOperations':['read','store','quote-display','model-send'],
        'purposes':[pure.purpose(stage) for stage in ('extract','compare','topic','relation','impact','verify-relation','verify-impact')],
        'recipients':sorted({pure.recipient(stage) for stage in ('extract','compare','topic','relation','impact','verify-relation','verify-impact')}),
        'evidence':grant['evidence']+['Prospective source processing for the user-authorized latest briefing; exact article rights, body and receipt pinned in selected-source.json.']})
    write_once(sources,current)
    ingestion=original/'ingestion';authority=Authority(sources)
    def current_rights():
        require(datetime.now(timezone.utc)<datetime.fromisoformat(cfg.get('recoveryDeadline') or round['windowTo']).astimezone(timezone.utc)-timedelta(seconds=190),'native_dispatch_deadline')
        authority.check(chosen.get('sourceId','korea-portal'),chosen['candidate']['newsId'],('read','store','quote-display','model-send'))
        require(json.loads((original/'rights.json').read_bytes())==chosen['rights'],'rights_pin')
        if chosen['rights'].get('rightsBasis')=='explicit-current-source-authority':
            import briefing_news_intake as news
            news.current_source(cfg,chosen['sourceId'],chosen['rights']['registrySha256'])
    # Prospective grant is read anew by native engines; no acquisition registry or old source grant is edited.
    source=extraction.Sources(ingestion,authority)
    selector={k:exported['observation'][k] for k in ['roundId','sourceId','page','ordinal','documentId','rawVersion','documentVersion']}
    request={'schemaVersion':'zoop-extraction-s2-2','jobId':root.name+'-s2','provenance':{'sourceKind':'actual','executionMode':'live','recordingKind':'provider'},
        'promptVersion':'briefing-native-v2-standard','incoming':selector,'catalogue':{'revision':'server-catalogue-'+b.digest(b.canonical(companies))[:16],'companies':companies},
        'snapshot':{'revision':'fresh-document-no-prior-native-mentions','events':[]},'topic':None}
    from zoop_ai_pipeline.live_budget import Budget as NativeBudget
    from zoop_ai_pipeline.live_funding import capped_set_funding_policy
    policy=capped_set_funding_policy(root.name,os.environ['ZOOP_AI_PIPELINE_LIVE_ADMIT_FROM'],
        os.environ['ZOOP_AI_PIPELINE_LIVE_ADMIT_UNTIL'],1000000000,900000000,100000000)
    metering=NativeBudget(root/'native-budget',1000000000,cfg.get('nativeDocumentCallLimit',12),funding=policy,
        bucket_caps={'shared':900000000,'personal':100000000},finish_by=os.environ['ZOOP_AI_PIPELINE_LIVE_FINISH_BY'])
    metering.admit_set(root.name,b.digest(b.canonical(request)),cfg.get('nativeWorkLimits') or {'extract':1,'compare':1,'topic':0,'relation':1,'impact':4,'verify-relation':4,'verify-impact':4})
    claim={'round':round,'requestKey':'source-'+b.digest(b.canonical(request)),'purpose':'generation','trigger':'scheduler','adminId':None,
        'inputArtifactId':None,'inputDigest':b.digest(b.canonical(request))}
    pipe=CommandPipe(cfg['ledgerCommand']);session=UsageSession(pipe,claim,root/'usage')
    transport=None
    try:
        with session:
            budget=server.Budget(cfg,round['id'],current_rights,lambda x:None)
            transport=NativeTransport(session,budget,root/'receipts');(root/'receipts').mkdir(mode=0o700,exist_ok=True)
            def factory(**kwargs):return runtime_type.from_env(transport=transport,**kwargs)
            write_once(root/'native.started.json',{'startedAt':b.now(),'inputSha256':claim['inputDigest']})
            store=extraction.Store(root/'s2',ingestion)
            try:s2=extraction.Extractor(store,source,extraction.LiveAccess(from_env=factory)).run(Submit.model_validate(request),extraction.Fixtures(None,None))
            finally:store.close()
            write_once(root/'s2-result.json',s2)
            known=received_failure(s2,cfg,round['id']) if cfg.get('selectionContinuation') else None
            if known:
                result={'schemaVersion':SCHEMA,'status':'withheld','reason':known,'additionalModelCalls':0}
                write_once(root/'source-qualification.json',result);session.stage='native_received_failure';session.outcome='withheld';return result
            require(s2['state']=='ready' and s2['delivery']['status']=='current','native_s2_not_ready')
            store=relation.Store(root/'s3',root/'s2',ingestion)
            try:s3=relation.Engine(store,source,root/'s2',ingestion,lambda need_send:factory(need_send=need_send)).run(RelationSubmit.model_validate({
                'schemaVersion':'zoop-relation-s3','jobId':root.name+'-s3','provenance':request['provenance'],
                'upstream':{'jobId':s2['jobId'],'inputDigest':s2['inputDigest']}}),relation.Fixtures(None,None))
            finally:store.close()
            write_once(root/'s3-result.json',s3)
            known=received_failure(s3,cfg,round['id']) if cfg.get('selectionContinuation') else None
            if known:
                result={'schemaVersion':SCHEMA,'status':'withheld','reason':known,'additionalModelCalls':0}
                write_once(root/'source-qualification.json',result);session.stage='native_received_failure';session.outcome='withheld';return result
            require(s3['state']=='ready' and s3['delivery']['status']=='current','native_s3_not_ready')
            qualification=source_qualification(root,s3,session)
            if qualification is not None:return qualification
            manifest,envelope=handoff(root,sources,ingestion,exported,s2,s3,companies)
            result={'schemaVersion':SCHEMA,'root':str(root),'sourceFile':str(sources),'ingestionState':str(ingestion),
                'observation':selector,'manifest':manifest,'handoffReceipt':envelope.get('receipt'),
                'sourceId':chosen.get('sourceId','korea-portal'),'documentId':exported['document']['documentId'],'documentVersion':exported['document']['documentVersion'],
                'bodySha256':b.digest(exported['document']['text'].encode()),'readyAt':b.now()}
            write_once(root/'ready.json',result);return result
    finally:
        if transport:transport.shutdown()
        os.environ.pop('ZOOP_AI_API_KEY',None);os.environ.pop('TYPESAFE_API_KEY',None)
        pipe.close()

def ensure_grants(path,additions):
    """Append owned grants without changing or copying any existing grant's values."""
    with path.with_name('.grants-update.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not path.exists():write_once(path,{'schemaVersion':'zoop-ai-s1-1','grants':additions});return
        value=json.loads(path.read_bytes());require(value.get('schemaVersion')=='zoop-ai-s1-1','grant_schema')
        old={g['grantId']:g for g in value['grants']};require(len(old)==len(value['grants']),'duplicate_grant')
        fresh=[]
        for grant in additions:
            require(grant['grantId'] not in old or old[grant['grantId']]==grant,'existing_grant_values_changed')
            if grant['grantId'] not in old:fresh.append(grant)
        if fresh:atomic(path,{**value,'grants':[*value['grants'],*fresh]})

def initialize_authority(cfg):
    root=Path(cfg['authorityRoot']);root.mkdir(mode=0o700,parents=True,exist_ok=True)
    auto=cfg.get('autoChain')=='briefing-auto-chain-v1'
    write_once(root/'serving-delegates.json',{'schemaVersion':'zoop-source-authority-delegates-1',
        'delegates':[cfg['originalSourceAuthority'],str(root/'new-authorities.json')]})
    if not (root/'new-authorities.json').exists():
        write_once(root/'new-authorities.json',{'schemaVersion':'zoop-ingestion-s2-1','revision':'empty-before-first-live-input','sources':[]})
    additions=[{
        'grantId':'briefing-kogl1-auto-v1' if auto else 'briefing-kogl1-live',
        'revision':'prospective-20261104-auto-v1' if auto else 'prospective-20261103-v1','sourceId':'korea-portal','enabled':True,'rights':'known',
        'allowedOperations':['read','store','quote-display','model-send'],'recipients':['openai'],
        'purposes':['briefing-outlook','semantic-verification'],'evidence':['https://www.korea.kr/guide/copyRight.do',
            'Article-level KOGL1 text badge and exact native source/body scope required before every model send. '+cfg['authorizationRef']],
        'expiresAt':None}]
    if cfg.get('samsungNewsroomEnabled') is True:
        from briefing_samsung_intake import SOURCE,NOTICE
        additions.append({'grantId':'briefing-samsung-auto-v1','revision':'publisher-first-party-text-1',
            'sourceId':SOURCE,'enabled':True,'rights':'known','allowedOperations':['read','store','quote-display','model-send'],
            'recipients':['openai'],'purposes':['briefing-outlook','semantic-verification'],
            'evidence':[NOTICE,'In-house article text only, checked creator/byline and immutable literal evidence; no images, attachments or external authors. '+cfg.get('sourceAuthorizationRef',cfg['authorizationRef'])],
            'expiresAt':None})
    if cfg.get('newsSourceRegistry'):
        import briefing_news_intake as news
        registry,_=news.load_registry(cfg)
        for source in registry['sources']:
            if news.authorized(source):
                # Keep the reviewed source's exact public-serving grant. Acquisition
                # and prospective native grants remain separate document bindings.
                additions.append(source['grant'])
    ensure_grants(root/'grants.json',additions)
    if cfg.get('originalReadGrants'):
        write_once(root/'serving-grants.json',{'schemaVersion':'zoop-grant-authority-delegates-1','delegates':[cfg['originalReadGrants'],str(root/'grants.json')]})
    if not (root/'model-scope.json').exists():
        write_once(root/'model-scope.json',{'schemaVersion':'briefing-model-scope-v1','authorizationRef':cfg['authorizationRef'],'sources':[]})

def register_authority(cfg,ready):
    root=Path(cfg['authorityRoot']);source=json.loads(Path(ready['sourceFile']).read_bytes())['sources'][0]
    grant=source['grant'];route={'sourceId':ready['sourceId'],'grantId':grant['grantId'],'revision':grant['revision'],'sources':ready['sourceFile']}
    with (root/'.update.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        old=json.loads((root/'new-authorities.json').read_bytes())
        routes=old['authorities'] if old['schemaVersion']=='zoop-source-authority-set-1' else []
        existing=[r for r in routes if (r['sourceId'],r['grantId'],r['revision'])==(route['sourceId'],route['grantId'],route['revision'])]
        require(not existing or existing==[route],'source_route_conflict')
        if not existing:routes.append(route)
        atomic(root/'new-authorities.json',{'schemaVersion':'zoop-source-authority-set-1','authorities':routes})
        scope=json.loads((root/'model-scope.json').read_bytes())
        pin={k:ready[k] for k in ['sourceId','documentId','documentVersion','bodySha256']}
        prior=[p for p in scope['sources'] if (p['documentId'],p['documentVersion'])==(pin['documentId'],pin['documentVersion'])]
        require(not prior or prior==[pin],'source_model_scope_conflict')
        if not prior:scope['sources'].append(pin)
        atomic(root/'model-scope.json',scope)

def native_command(cfg,operation,request,path):
    return server.java({**cfg,'serverCommand':cfg['nativeCommand']},operation,request,path)

def run_slot(cfg,edition,cutoff=None,recover_unpaid=False,*,producer=None,observer=None,now=None,sleep=None):
    """One finite ECS task per slot. Collection starts before cutoff; publication starts at cutoff."""
    import time,psycopg
    from psycopg.rows import dict_row
    notify=observer or (lambda *args:None);last_stage=['collection']
    def observer(stage,status,detail=None):
        last_stage[0]=stage;notify(stage,status,detail)
    clock=now or (lambda:datetime.now(server.KST));sleep=sleep or time.sleep
    now=clock()
    from briefing_schedule import round_for
    planned=round_for(now.astimezone(server.KST).date(),edition,cfg)
    slot=datetime.fromisoformat(cutoff).astimezone(server.KST) if cutoff else datetime.fromisoformat(planned['windowTo'])
    require(slot.date()==now.date() and slot>now+timedelta(minutes=4 if recover_unpaid else 10),'slot_preparation_window')
    start=datetime.fromisoformat(planned['windowFrom'])
    round={'id':'brf-'+str(slot.date())+'-'+edition,'date':str(slot.date()),'edition':edition,
        'scheduledAt':slot.isoformat(),'windowFrom':start.isoformat(),'windowTo':slot.isoformat()}
    collection_root=Path(cfg['work'])/'native'/round['id']
    root=collection_root/'recovery-standard-v2' if recover_unpaid else collection_root
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    initialize_authority(cfg)
    with psycopg.connect(cfg['dsn'],autocommit=True,row_factory=dict_row) as conn:
        # The same lock as the original common producer also fences overlapping ECS deliveries.
        require(conn.execute("SELECT pg_try_advisory_lock(hashtext('zoop-briefing-server-v1')) AS owned").fetchone()['owned'],'another_briefing_writer')
        existing=conn.execute('SELECT * FROM briefing_common_schedule_jobs WHERE round_date=%s AND edition=%s',(slot.date(),edition)).fetchone()
        if existing:
            if server.published(conn,existing):print(json.dumps({'roundId':round['id'],'status':'already_published','newModelCalls':0}),flush=True);return
            # Explicit recovery is restricted to this proved-unsent schema compilation failure.
            require(recover_unpaid and existing['status']=='requires_recovery' and existing['scheduled_at']==slot and existing['window_from']==start,'existing_slot_requires_explicit_recovery')
            require(conn.execute('SELECT count(*) AS n FROM ai_executions e JOIN briefing_attempts a ON a.id=e.briefing_attempt_id WHERE a.round_id=%s',(round['id'],)).fetchone()['n']==0,'recovery_has_model_calls')
            require(conn.execute("SELECT count(*) AS n FROM briefing_attempts WHERE round_id=%s AND status IN ('queued','running','verifying')",(round['id'],)).fetchone()['n']==0,'recovery_has_active_owner')
            result=json.loads((collection_root/'s2-result.json').read_bytes())
            require(result['failure']['code']=='live_output_schema_limits' and not result['calls'],'recovery_not_proved_unsent')
            import sqlite3
            with sqlite3.connect((collection_root/'native-budget/live-budget.sqlite3').as_uri()+'?mode=ro',uri=True) as check:
                require(check.execute('SELECT count(*) FROM reservations').fetchone()[0]==0,'recovery_has_reservations')
            require(not any(json.loads(p.read_bytes())['roundId']==round['id'] for p in (Path(cfg['work'])/'budget').glob('*.json')),'recovery_has_physical_reservations')
            write_once(root/'unpaid-recovery.json',{'previousState':'live_output_schema_limits','previousModelCalls':0,'newContract':'native-standard-no-fallback','recoveredAt':b.now(),'authorizationRef':cfg['authorizationRef']})
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='queued',finished_at=NULL WHERE id=%s AND status='requires_recovery'",(round['id'],))
        else:
            require(not recover_unpaid,'recovery_requires_existing_slot')
            conn.execute('INSERT INTO briefing_common_schedule_jobs(id,round_date,edition,scheduled_at,window_from) VALUES(%s,%s,%s,%s,%s)',
                (round['id'],slot.date(),edition,slot,start))
        try:
            baseline=native_command(cfg,'state',{},root/'baseline.request.json');write_once(root/'baseline.json',baseline)
            # Market observations are independent of whether a company/event is admissible.
            # A later failed native stage must not discard an already captured cutoff reference.
            capture_market(cfg,round,observer)
            print(json.dumps({'roundId':round['id'],'stage':'bounded_source_collection','cutoff':slot.isoformat()}),flush=True)
            context=dict(cfg)
            def qualify_ready(candidate,candidate_root):
                # Each source is imported additively before cutoff, then assessed against the actual reader input.
                from briefing_selection_gate import qualify, dispatch_window
                if (candidate_root/'selection/qualification.json').is_file():
                    activated=json.loads((candidate_root/'activated.json').read_bytes())
                    selected=qualify(cfg,round,candidate_root,activated['graphVersion'])
                    if selected['status']=='ready':
                        context.update(expectedGraphVersion=activated['graphVersion'],qualifiedProducerWork=selected['producerWork'])
                    return selected
                try:dispatch_window(round)
                except ValueError as error:
                    if str(error)!='briefing_server_selection_dispatch_deadline':raise
                    limits.remaining_native(cfg,round['id'])
                    return {'status':'withheld','reason':'preparation_deadline'}
                before=native_command(cfg,'state',{},candidate_root/'baseline.request.json')
                observer('authority','started');register_authority(cfg,candidate);observer('authority','completed')
                observer('import','started')
                incoming=native_command(cfg,'import',candidate,candidate_root/'import.request.json')
                write_once(candidate_root/'imported.json',incoming);observer('import','completed')
                require(clock()<slot-timedelta(seconds=10),'native_after_cutoff')
                observer('activation','started')
                activated=native_command(cfg,'activate',{'baseline':before,'incoming':incoming},candidate_root/'activate.request.json')
                write_once(candidate_root/'activated.json',activated)
                observer('activation','completed',{'graphVersion':activated['graphVersion']})
                try:selected=qualify(cfg,round,candidate_root,activated['graphVersion'])
                except ValueError as error:
                    if str(error)!='briefing_server_selection_dispatch_deadline':raise
                    limits.remaining_native(cfg,round['id'])
                    selected={'status':'withheld','reason':'preparation_deadline'}
                if selected['status']=='ready':
                    context['expectedGraphVersion']=activated['graphVersion']
                    context['qualifiedProducerWork']=selected['producerWork']
                return selected
            try:
                ready=prepare(cfg,round,observer=observer,qualifier=qualify_ready) if cfg.get('selectionContinuation') else prepare(cfg,round,observer=observer)
            except ValueError as error:
                if str(error)!='briefing_server_no_current_company_source':raise
                ready={'status':'withheld','reason':'no_current_company_source'}
            if ready.get('status')=='withheld':
                from briefing_coverage_publication import record
                context['coverageNoticeSha256']=record(cfg,round,ready['reason'],clock(),ready.get('outcomeFile'))
                observer('native','failed',{'reason':ready['reason']})
            elif not cfg.get('selectionContinuation'):
                observer('authority','started');register_authority(cfg,ready);observer('authority','completed')
                observer('import','started')
                incoming=native_command(cfg,'import',ready,root/'import.request.json');write_once(root/'imported.json',incoming)
                observer('import','completed')
                require(clock()<slot-timedelta(seconds=10),'native_after_cutoff')
                observer('activation','started')
                activated=native_command(cfg,'activate',{'baseline':baseline,'incoming':incoming},root/'activate.request.json')
                write_once(root/'activated.json',activated)
                observer('activation','completed',{'graphVersion':activated['graphVersion']})
                context['expectedGraphVersion']=activated['graphVersion']
                print(json.dumps({'roundId':round['id'],'stage':'native_source_ready','graphVersion':activated['graphVersion']}),flush=True)
            observer('cutoff','started',{'cutoff':slot.isoformat()})
            while (remaining:=(slot-clock()).total_seconds())>0:sleep(min(30,remaining))
            observer('cutoff','completed')
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='running' WHERE id=%s AND status='queued'",(round['id'],))
            job=conn.execute('SELECT * FROM briefing_common_schedule_jobs WHERE id=%s',(round['id'],)).fetchone()
            observer('generation','started')
            (producer or server.produce)(context,job)
            observer('generation','completed');require(server.published(conn,job),'live_publication_proof')
            observer('publication','completed')
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='completed',finished_at=now() WHERE id=%s AND status='running'",(round['id'],))
            print(json.dumps({'roundId':round['id'],'status':'published','cutoff':slot.isoformat()}),flush=True)
        except BaseException:
            proof_job={'id':round['id'],'round_date':slot.date(),'edition':edition,'scheduled_at':slot,'window_from':start}
            if server.published(conn,proof_job):
                conn.execute("UPDATE briefing_common_schedule_jobs SET status='completed',finished_at=now() WHERE id=%s AND status IN ('queued','running')",(round['id'],))
                observer('publication','completed',{'reason':'committed_publication_recovered'})
                return {'roundId':round['id'],'status':'published','recoveredFromStorage':True}
            latest=conn.execute('SELECT status FROM briefing_attempts WHERE round_id=%s ORDER BY attempt_no DESC LIMIT 1',(round['id'],)).fetchone()
            if latest is None or latest['status']=='completed':
                (root/'failure').mkdir(mode=0o700,exist_ok=True)
                server.record_input_failure(cfg,round,root/'failure',stage=last_stage[0],reason='automatic_chain_failed')
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='requires_recovery',finished_at=now() WHERE id=%s AND status IN ('queued','running')",(round['id'],))
            raise


def capture_market(cfg,round_,observer):
    import briefing_live_market as market
    observer('market','started')
    try:
        value=market.collect(cfg['work'],round_)
        count=sum(x['value'] is not None for x in value['marketVariables']['indicators'])
        observer('market','completed',{'availableIndicators':count})
    except (OSError,ValueError,KeyError,TypeError,market.b.ReplayError):
        observer('market','failed',{'reason':'market_capture_unavailable'})
