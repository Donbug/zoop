"""Actual loopback collection/native engines/import/publication, with authored provider peers only."""
import json,os,sys,time,copy,subprocess
from pathlib import Path
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit,parse_qs,urlencode
from unittest.mock import patch
root=Path(sys.argv[1]).resolve();repo=Path(__file__).resolve().parents[3];classpath=sys.argv[2]
sys.path[:0]=[str(repo/'scripts'),str(repo/'scripts/tests'),str(repo/'ai/pipeline'),str(repo/'ai/pipeline/src'),str(repo/'ai/service/src')]
from freezegun import freeze_time
import httpx,psycopg
import briefing_auto_chain as chain
import briefing_native_intake as native
import briefing_usage as usage
from test_briefing_priority_generation import Transport
from scripts.collection_smoke import LocalSite
from scripts.korea_corpus_smoke import config,article,listing,SUBSTANCE
from scripts.extraction_smoke import simulate
from zoop_ai_pipeline.korea_portal import ROUTES
# Only simulated source/provider clocks are frozen. JDBC leases and usage receipt timestamps use the real clock.
def receipt_now(epoch=time.time):return datetime.fromtimestamp(epoch(),timezone.utc).isoformat()
java=[os.environ['JAVA'],'-cp',classpath]
u=urlsplit(os.environ['DB_URL'].removeprefix('jdbc:'));schema=parse_qs(u.query)['currentSchema'][0]
dsn='postgresql://company_test@127.0.0.1:'+str(u.port)+u.path+'?'+urlencode({'options':'-csearch_path='+schema})
work=root/'auto-work';work.mkdir(mode=0o700);authority=root/'auto-authority'
catalog=root/'auto-catalogue.json';catalog.write_text(json.dumps({'companies':[{'company_id':'SYNTH-1','name':'합성기업','aliases':[],'ticker':None}]}))
for name,value in [('key','OPENAI_API_KEY=synthetic-only'),('verifier','TYPESAFE_API_KEY=synthetic-only')]:
 p=root/name;p.write_text(value);p.chmod(0o600)
original_source=os.environ['ZOOP_DOCUMENT_READ_INGESTION_SOURCES'];original_grants=os.environ['ZOOP_DOCUMENT_READ_GRANTS']
cfg={'enabled':True,'autoChain':chain.VERSION,'priorityContract':'priority-business-producer-v1','nativeCallLimit':6,'additiveGraphAllowed':True,
     'dsn':dsn,'work':str(work),'authorityRoot':str(authority),'originalSourceAuthority':original_source,'originalReadGrants':original_grants,
     'authorizationRef':'synthetic-whole-chain','companyCatalogue':str(catalog),'keyFile':str(root/'key'),'verifierKeyFile':str(root/'verifier'),
     'serverCommand':java+['com.zoop.briefing.server.BriefingServerCommand'],
     'nativeCommand':java+['com.zoop.briefing.server.BriefingAutoNativeTestCommand'],
     'ledgerCommand':java+['com.zoop.briefing.usage.BriefingUsageCommand','--stdio']}
shared=os.environ.get('BRIEFING_AUTO_TEST_SHARED')=='true'
if shared:cfg.update(sharePriorityAnalysis=True,nativeCallLimit=8)
# Test-owned executables; never install or overwrite the host's /usr/local/bin.
for label,module in [('ingest','zoop_ai_pipeline.ingestion_cli'),('handoff','zoop_ai_pipeline.handoff_cli')]:
 p=root/label;p.write_text('#!'+sys.executable+'\nimport sys\nsys.path.insert(0,'+repr(str(repo/'ai/pipeline/src'))+')\nfrom '+module+' import main\nraise SystemExit(main())\n');p.chmod(0o700)
os.environ.update({'BRIEFING_SERVER_WORK_ROOT':str(work),'BRIEFING_SERVER_AUTHORITY_ROOT':str(authority),
    'BRIEFING_SERVER_ADDITIVE_GRAPH_ALLOWED':'true','BRIEFING_SERVER_AUTHORIZATION_REF':'synthetic-whole-chain',
    'ZOOP_DOCUMENT_READ_INGESTION_SOURCES':str(authority/'serving-delegates.json'),'ZOOP_DOCUMENT_READ_GRANTS':str(authority/'serving-grants.json'),
    'BRIEFING_SERVER_SOURCE_SCOPE':str(authority/'model-scope.json'),'ZOOP_INGESTION_EXECUTABLE':str(root/'ingest'),'ZOOP_GRAPH_HANDOFF_EXECUTABLE':str(root/'handoff'),
    'PYTHONPATH':os.pathsep.join([str(repo/'ai/pipeline/src'),str(repo/'scripts'),str(repo/'ai/service/src')])})
site=LocalSite();provider=[];business=Transport();real_transport=httpx.HTTPTransport
class Peer(httpx.BaseTransport):
 def __init__(self,*args,**kwargs):self.local=real_transport(*args,**kwargs)
 def handle_request(self,request):
  if request.url.host in ('api.openai.com','api.typesafe.ai'):
   payload=json.loads(request.content);provider.append(payload);reply=simulate(payload);reply['model']=payload['model']
   if shared and len(provider)==2:
    answer=json.loads(reply['choices'][0]['message']['content']);assert 'relations' in answer
    answer['relations']=[];reply['choices'][0]['message']['content']=json.dumps(answer)
   return httpx.Response(200,json=reply,request=request)
  assert request.url.host=='127.0.0.1','unexpected network peer'
  return self.local.handle_request(request)
 def close(self):self.local.close()
try:
 site.route('/robots.txt',b'User-agent: *\nAllow: /\n',content_type='text/plain')
 site.route(ROUTES['policy-news'][0],listing(['100000001','100000002'] if shared else ['100000001']).replace(b'2026.10.23',b'2026.11.04').replace(b'2026-10-01',b'2026-11-03').replace(b'2026-10-23',b'2026-11-04'))
 body='합성기업은 공급 계약을 발표했다. '+SUBSTANCE
 def serve_article():
  identifier=parse_qs(urlsplit(site.log[-1]['path']).query)['newsId'][0]
  site.routes[ROUTES['policy-news'][1]]['body']=article(site,identifier,body=body).replace(b'2026.10.23',b'2026.11.04')
 site.route(ROUTES['policy-news'][1],hook=serve_article)
 with freeze_time('2026-11-04 00:02:00+00:00') as frozen:
  r=chain.round_for(datetime.now(native.server.KST).date(),'morning');collection=work/'native'/r['id'];collection.mkdir(parents=True,mode=0o700)
  raw,_=config(collection,site,planId=r['id']+'-sources-v1',stateDir=str(collection/'collection'),fromDay='2026-11-03',throughDay='2026-11-04')
  (collection/'collection-config.json').write_text(json.dumps(raw))
  def sleep(seconds):frozen.tick(timedelta(seconds=seconds))
  original_run=subprocess.run
  def command(*args,**kwargs):
   result=original_run(*args,**kwargs)
   if result.returncode!=0 and isinstance(result.stderr,bytes):print('syntheticCommandFailure:'+result.stderr.decode(),file=sys.stderr)
   return result
  with patch.object(subprocess,'run',command),patch.object(httpx,'HTTPTransport',Peer),patch.object(native.server.b,'authenticated_transport',return_value=business),patch.object(usage,'now',receipt_now):
   chain.run_slot(cfg,'morning',sleep=sleep)
  journal=work/'chain'/r['id']
  assert (journal/'collection-completed.json').exists() and (journal/'publication-completed.json').exists()
  assert len(provider)<=(8 if shared else 6),len(provider)
  assert len(business.requests)==(8 if shared else 10),len(business.requests)
  if shared:
   assert len(provider)==7,len(provider)
   assert len(list(collection.glob('candidates-v3/*/source-qualification.json')))==1
  before=len(provider)+len(business.requests)
  with patch.object(httpx,'HTTPTransport',Peer),patch.object(native.server.b,'authenticated_transport',return_value=business):
   assert chain.work_once(cfg) is False
  assert before==len(provider)+len(business.requests)
 with psycopg.connect(dsn) as conn:
  row=conn.execute("SELECT public_snapshot FROM briefing_rounds WHERE id='brf-2026-11-04-morning' AND status='published'").fetchone();assert row
  source=row[0]['commonPriority']['items'][0]['sources'][0]
  assert source['publishedAt'] is None and source['publishedDate']=='2026-11-04'
  assert conn.execute("SELECT count(*) FROM ai_executions WHERE actual_cost IS NOT NULL").fetchone()[0]==0
 (root/'auto-proof.json').write_text(json.dumps({'nativeSyntheticCalls':len(provider),'briefingSyntheticCalls':len(business.requests),'sourceRequests':len(site.log),'sourcePublishedAt':None,'sourcePublishedDate':source['publishedDate'],'repeatNewCalls':0}))
 print(json.dumps({'status':'passed','nativeSyntheticCalls':len(provider),'briefingSyntheticCalls':len(business.requests),'sourceRequests':len(site.log)}))
except BaseException:
 for native_result in work.glob('native/*/*/s?-result.json'):
  value=json.loads(native_result.read_bytes());print(json.dumps({'syntheticNative':native_result.name,'failure':value.get('failure'),'calls':value.get('calls'),'state':value.get('state')},ensure_ascii=False),file=sys.stderr)
 for result in work.glob('native/*/collection-result.json'):
  value=json.loads(result.read_bytes());print(json.dumps({'syntheticCollectionCounts':value.get('counts'),'syntheticDispositions':value.get('dispositions'),'sourceRequests':site.log},ensure_ascii=False),file=sys.stderr)
 raise
finally:site.close()
