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
from briefing_usage import CommandPipe,UsageSession,write_once

b=server.b
require=server.require
SCHEMA='briefing-native-intake-v1'

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
    matches=[]
    for company in companies:
        for alias in [company['name'],*company['aliases']]:
            if len(alias)<3:continue
            expression=r'(?<![A-Za-z0-9])'+re.escape(alias)+r'(?![A-Za-z0-9])' if alias.isascii() else re.escape(alias)
            if re.search(expression,text,re.I):matches.append(company['companyId']);break
    return matches

def collect(cfg,round,root):
    from zoop_ai_pipeline.korea_corpus import Config,run,package
    from zoop_ai_pipeline.korea_portal import BODY_XPATH,tree,text as node_text
    base=Path(cfg['work'])/'native';root.mkdir(mode=0o700,parents=True,exist_ok=True)
    config_path=root/'collection-config.json'
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
            'channels':[{'name':'policy-news','maxPages':1,'maxDocuments':10},{'name':'press-release','maxPages':1,'maxDocuments':20}],
            'maxListingPages':2,'maxCandidates':60,'maxDocuments':30,
            'policy':{'schemaVersion':'zoop-collection-policy-1','userAgent':'ZoopTextCorpus/1.0','timeoutSeconds':30,
                'maxTotalSeconds':300,'maxRedirects':0,'maxRequests':50,'maxResponseBytes':5000000,'maxTotalBytes':60000000,
                'minIntervalSeconds':2.0,'allowedMediaTypes':['text/html'],'syntheticLoopback':False},
            'grant':{'grantId':round['id']+'-acquisition','revision':'kogl1-text-v1','sourceId':'korea-portal','enabled':True,
                'rights':'known','allowedOperations':['read','store','quote-display'],'recipients':[],'purposes':[],
                'evidence':[rights['policyUrl'],rights['rule']],'expiresAt':None},
            'rightsEvidence':refs['rights'],'exclusionManifest':refs['exclusions']}
        write_once(config_path,config)
    config=Config.model_validate_json(config_path.read_bytes());result=run(config)
    write_once(root/'collection-result.json',result)
    catalogue=json.loads(Path(cfg['companyCatalogue']).read_bytes())
    companies=[{'companyId':c['company_id'],'name':c['name'],'aliases':c['aliases'],'ticker':c['ticker']} for c in catalogue['companies']]
    eligible=[]
    for row in result['documents']:
        exported=json.loads((root/'collection'/row['exportFile']).read_bytes())
        native=root/'collection/native/collections'/('item-'+row['candidate']['newsId'])
        raw=(native/'bodies'/(row['nativeBodySha256']+'.bin')).read_bytes()
        require(b.digest(raw)==row['nativeBodySha256'],'native_body_pin')
        dom=tree(raw);body=dom.xpath(BODY_XPATH);require(len(body)==1,'article_scope')
        # A disposable DOM copy for relevance only; the native canonical text and offsets remain unchanged.
        for node in body[0].xpath('.//*[contains(@class,"law_copy_wrap") or self::script or self::style]'):
            if node.getparent() is not None:node.getparent().remove(node)
        matches=source_matches(node_text(body[0]),companies)
        if matches:eligible.append((row,exported,matches))
    eligible.sort(key=lambda x:(x[0]['candidate']['publicationDay'],x[0]['candidate']['newsId']),reverse=True)
    require(bool(eligible),'no_current_company_source')
    # One source set leaves at least four physical calls for briefing generation/verification and bounded repairs.
    chosen,exported,matches=eligible[0]
    write_once(root/'selected-source.json',{'candidate':chosen['candidate'],'documentId':exported['document']['documentId'],
        'documentVersion':exported['document']['documentVersion'],'matchedCompanyIds':matches,
        'nativeBodySha256':chosen['nativeBodySha256'],'nativeReceiptSha256':chosen['nativeReceiptSha256'],
        'coverage':{'complete':False,'candidateDocuments':len(eligible),'selectedDocuments':1,'collection':result['counts']}})
    return chosen,exported,companies

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
        require(sum(json.loads(p.read_bytes()).get('roundId')==self.budget.round_id and json.loads(p.read_bytes()).get('phase')=='native' for p in rows)<12,'native_phase_call_limit')
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
    def close(self):self.peer.close()

def read_verifier(path):
    import stat
    require(not path.is_symlink() and stat.S_IMODE(path.stat().st_mode)==0o600,'private_verifier_file')
    key=path.read_text().strip().removeprefix('TYPESAFE_API_KEY=')
    require(bool(key) and not any(c.isspace() for c in key),'verifier_key_format')
    return key

def configure_runtime(cfg,root,cutoff):
    from zoop_ai_pipeline.live_runtime import LiveRuntime
    start=datetime.now(timezone.utc)
    end=datetime.fromisoformat(cutoff).astimezone(timezone.utc)
    require((end-start).total_seconds()>600,'native_preparation_window')
    os.environ.update({'ZOOP_AI_PIPELINE_LIVE_ENABLED':'1','ZOOP_AI_PIPELINE_LIVE_MODEL':'gpt-6-luna',
        'ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT':'high','ZOOP_AI_PIPELINE_LIVE_MAX_OUTPUT_TOKENS':'12000',
        'ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS':'180','ZOOP_AI_PIPELINE_LIVE_MAX_CALLS':'12','ZOOP_AI_PIPELINE_LIVE_MAX_USD':'1',
        'ZOOP_AI_PIPELINE_LIVE_SHARED_MAX_USD':'0.9','ZOOP_AI_PIPELINE_LIVE_PERSONAL_MAX_USD':'0.1',
        'ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR':str(root/'native-budget'),'ZOOP_AI_PIPELINE_LIVE_PROFILE':'admitted-set-capped-v4',
        'ZOOP_AI_PIPELINE_LIVE_RUN_ID':root.name,'ZOOP_AI_PIPELINE_LIVE_SET_ID':root.name,
        'ZOOP_AI_PIPELINE_LIVE_ADMIT_FROM':start.strftime('%Y-%m-%dT%H:%M:%SZ'),'ZOOP_AI_PIPELINE_LIVE_ADMIT_UNTIL':(start+timedelta(seconds=60)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'ZOOP_AI_PIPELINE_LIVE_FINISH_BY':end.strftime('%Y-%m-%dT%H:%M:%SZ'),'ZOOP_AI_PIPELINE_LIVE_OUTPUT_CONTRACT':'citation-enum-1',
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

def prepare(cfg,round):
    from zoop_ai_pipeline import extraction,relation
    from zoop_ai_pipeline.extraction_contracts import Submit
    from zoop_ai_pipeline.relation_contracts import Submit as RelationSubmit
    from zoop_ai_pipeline.ingestion_contracts import Authority
    root=Path(cfg['work'])/'native'/round['id'];root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if (root/'ready.json').exists():return json.loads((root/'ready.json').read_bytes())
    require(not (root/'native.started.json').exists(),'native_interrupted_requires_recovery')
    chosen,exported,companies=collect(cfg,round,root)
    runtime_type=configure_runtime(cfg,root,round['windowTo']);pure=runtime_type.from_env()
    original=root/'collection/items'/chosen['candidate']['newsId']
    sources=Path(cfg['authorityRoot'])/('source-'+round['id']+'.json');sources.parent.mkdir(mode=0o700,parents=True,exist_ok=True);current=json.loads((original/'sources.json').read_bytes())
    grant=current['sources'][0]['grant'];grant.update({'grantId':round['id']+'-processing','revision':'kogl1-prospective-v1',
        'allowedOperations':['read','store','quote-display','model-send'],
        'purposes':[pure.purpose(stage) for stage in ('extract','compare','topic','relation','impact','verify-relation','verify-impact')],
        'recipients':sorted({pure.recipient(stage) for stage in ('extract','compare','topic','relation','impact','verify-relation','verify-impact')}),
        'evidence':grant['evidence']+['Prospective source processing for the user-authorized latest briefing; exact article badge, body and receipt pinned in selected-source.json.']})
    write_once(sources,current)
    ingestion=original/'ingestion';authority=Authority(sources)
    def current_rights():
        authority.check('korea-portal',chosen['candidate']['newsId'],('read','store','quote-display','model-send'))
        require(json.loads((original/'rights.json').read_bytes())==chosen['rights'],'rights_pin')
    # Prospective grant is read anew by native engines; no acquisition registry or old source grant is edited.
    source=extraction.Sources(ingestion,authority)
    selector={k:exported['observation'][k] for k in ['roundId','sourceId','page','ordinal','documentId','rawVersion','documentVersion']}
    request={'schemaVersion':'zoop-extraction-s2-2','jobId':round['id']+'-s2','provenance':{'sourceKind':'actual','executionMode':'live','recordingKind':'provider'},
        'promptVersion':'briefing-native-v1','incoming':selector,'catalogue':{'revision':'server-catalogue-'+b.digest(b.canonical(companies))[:16],'companies':companies},
        'snapshot':{'revision':'fresh-document-no-prior-native-mentions','events':[]},'topic':None}
    from zoop_ai_pipeline.live_budget import Budget as NativeBudget
    from zoop_ai_pipeline.live_funding import capped_set_funding_policy
    policy=capped_set_funding_policy(root.name,os.environ['ZOOP_AI_PIPELINE_LIVE_ADMIT_FROM'],
        os.environ['ZOOP_AI_PIPELINE_LIVE_ADMIT_UNTIL'],1000000000,900000000,100000000)
    metering=NativeBudget(root/'native-budget',1000000000,12,funding=policy,
        bucket_caps={'shared':900000000,'personal':100000000},finish_by=os.environ['ZOOP_AI_PIPELINE_LIVE_FINISH_BY'])
    metering.admit_set(root.name,b.digest(b.canonical(request)),{'extract':1,'compare':1,'topic':0,'relation':1,'impact':4,'verify-relation':4,'verify-impact':4})
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
            write_once(root/'s2-result.json',s2);require(s2['state']=='ready' and s2['delivery']['status']=='current','native_s2_not_ready')
            store=relation.Store(root/'s3',root/'s2',ingestion)
            try:s3=relation.Engine(store,source,root/'s2',ingestion,lambda need_send:factory(need_send=need_send)).run(RelationSubmit.model_validate({
                'schemaVersion':'zoop-relation-s3','jobId':round['id']+'-s3','provenance':request['provenance'],
                'upstream':{'jobId':s2['jobId'],'inputDigest':s2['inputDigest']}}),relation.Fixtures(None,None))
            finally:store.close()
            write_once(root/'s3-result.json',s3);require(s3['state']=='ready' and s3['delivery']['status']=='current','native_s3_not_ready')
            manifest,envelope=handoff(root,sources,ingestion,exported,s2,s3,companies)
            result={'schemaVersion':SCHEMA,'root':str(root),'sourceFile':str(sources),'ingestionState':str(ingestion),
                'observation':selector,'manifest':manifest,'handoffReceipt':envelope.get('receipt'),
                'sourceId':'korea-portal','documentId':exported['document']['documentId'],'documentVersion':exported['document']['documentVersion'],
                'bodySha256':b.digest(exported['document']['text'].encode()),'readyAt':b.now()}
            write_once(root/'ready.json',result);return result
    finally:
        if transport:transport.close()
        os.environ.pop('ZOOP_AI_API_KEY',None);os.environ.pop('TYPESAFE_API_KEY',None)
        pipe.close()

def initialize_authority(cfg):
    root=Path(cfg['authorityRoot']);root.mkdir(mode=0o700,parents=True,exist_ok=True)
    write_once(root/'serving-delegates.json',{'schemaVersion':'zoop-source-authority-delegates-1',
        'delegates':[cfg['originalSourceAuthority'],str(root/'new-authorities.json')]})
    if not (root/'new-authorities.json').exists():
        write_once(root/'new-authorities.json',{'schemaVersion':'zoop-ingestion-s2-1','revision':'empty-before-first-live-input','sources':[]})
    write_once(root/'grants.json',{'schemaVersion':'zoop-ai-s1-1','grants':[{
        'grantId':'briefing-kogl1-live','revision':'prospective-20261103-v1','sourceId':'korea-portal','enabled':True,'rights':'known',
        'allowedOperations':['read','store','quote-display','model-send'],'recipients':['openai'],
        'purposes':['briefing-outlook','semantic-verification'],'evidence':['https://www.korea.kr/guide/copyRight.do',
            'Article-level KOGL1 text badge and exact native source/body scope required before every model send. '+cfg['authorizationRef']],
        'expiresAt':None}]})
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

def run_slot(cfg,edition,cutoff=None):
    """One finite ECS task per slot. Collection starts before cutoff; publication starts at cutoff."""
    import time,psycopg
    from psycopg.rows import dict_row
    now=datetime.now(server.KST)
    hour,minute=(9,20) if edition=='morning' else (17,30)
    slot=datetime.fromisoformat(cutoff).astimezone(server.KST) if cutoff else now.replace(hour=hour,minute=minute,second=0,microsecond=0)
    require(slot.date()==now.date() and slot>now+timedelta(minutes=10),'slot_preparation_window')
    start=(slot-timedelta(days=1)).replace(hour=17,minute=30) if edition=='morning' else slot.replace(hour=9,minute=20)
    round={'id':'brf-'+str(slot.date())+'-'+edition,'date':str(slot.date()),'edition':edition,
        'scheduledAt':slot.isoformat(),'windowFrom':start.isoformat(),'windowTo':slot.isoformat()}
    root=Path(cfg['work'])/'native'/round['id'];root.mkdir(mode=0o700,parents=True,exist_ok=True)
    initialize_authority(cfg)
    with psycopg.connect(cfg['dsn'],autocommit=True,row_factory=dict_row) as conn:
        # The same lock as the original common producer also fences overlapping ECS deliveries.
        require(conn.execute("SELECT pg_try_advisory_lock(hashtext('zoop-briefing-server-v1')) AS owned").fetchone()['owned'],'another_briefing_writer')
        existing=conn.execute('SELECT * FROM briefing_common_schedule_jobs WHERE round_date=%s AND edition=%s',(slot.date(),edition)).fetchone()
        if existing:
            if server.published(conn,existing):print(json.dumps({'roundId':round['id'],'status':'already_published','newModelCalls':0}),flush=True);return
            # A fresh scheduler delivery must not replay a failed or unknown previous task.
            require(False,'existing_slot_requires_explicit_recovery')
        conn.execute('INSERT INTO briefing_common_schedule_jobs(id,round_date,edition,scheduled_at,window_from) VALUES(%s,%s,%s,%s,%s)',
            (round['id'],slot.date(),edition,slot,start))
        try:
            baseline=native_command(cfg,'state',{},root/'baseline.request.json');write_once(root/'baseline.json',baseline)
            print(json.dumps({'roundId':round['id'],'stage':'bounded_source_collection','cutoff':slot.isoformat()}),flush=True)
            ready=prepare(cfg,round);register_authority(cfg,ready)
            incoming=native_command(cfg,'import',ready,root/'import.request.json');write_once(root/'imported.json',incoming)
            require(datetime.now(server.KST)<slot-timedelta(seconds=10),'native_after_cutoff')
            activated=native_command(cfg,'activate',{'baseline':baseline,'incoming':incoming},root/'activate.request.json')
            write_once(root/'activated.json',activated)
            print(json.dumps({'roundId':round['id'],'stage':'native_source_ready','graphVersion':activated['graphVersion']}),flush=True)
            while (remaining:=(slot-datetime.now(server.KST)).total_seconds())>0:time.sleep(min(30,remaining))
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='running' WHERE id=%s AND status='queued'",(round['id'],))
            job=conn.execute('SELECT * FROM briefing_common_schedule_jobs WHERE id=%s',(round['id'],)).fetchone()
            server.produce(cfg,job);require(server.published(conn,job),'live_publication_proof')
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='completed',finished_at=now() WHERE id=%s AND status='running'",(round['id'],))
            print(json.dumps({'roundId':round['id'],'status':'published','cutoff':slot.isoformat()}),flush=True)
        except BaseException:
            conn.execute("UPDATE briefing_common_schedule_jobs SET status='requires_recovery',finished_at=now() WHERE id=%s AND status IN ('queued','running')",(round['id'],))
            raise
