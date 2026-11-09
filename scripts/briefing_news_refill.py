"""Append-only shared news acquisition. No provider key, model call or per-member crawl.

Each pass preserves its observations and queues. A later pass visits new article URLs
or a verified next page; one bounded feed refresh may discover newly posted URLs.
Source authority, article clocks and exact native ingestion stay in news_intake.
"""
import copy
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import briefing_news_intake as news
from briefing_usage import write_once

VERSION='briefing-news-refill-v1'
DEFAULTS={'targetDocuments':20,'maxPasses':6,'maxRequests':120,'maxNetworkSeconds':300,
          'maxBytes':100_000_000,'nativeReserveSeconds':360,'articlesPerSourcePass':8}


def policy(cfg):
    value=cfg.get('newsCollectionPolicy')
    news.require(isinstance(value,dict) and set(value)=={'version',*DEFAULTS} and value['version']==VERSION,'refill_policy')
    for k,lo,hi in [('targetDocuments',1,40),('maxPasses',1,8),('maxRequests',1,200),
                    ('maxNetworkSeconds',1,600),('maxBytes',5_000_000,200_000_000),
                    ('nativeReserveSeconds',360,900),('articlesPerSourcePass',1,16)]:
        news.require(type(value[k]) is int and lo<=value[k]<=hi,'refill_policy')
    return value


def enabled(cfg):
    return cfg.get('newsCollectionPolicy') is not None


def now():
    return news.datetime.now(news.KST)


def _owned(root,relative):
    p=root/relative
    news.require(not p.is_symlink() and p.resolve().is_relative_to(root.resolve()),'saved_item_path')
    return p


def _read_passes(root,binding):
    result=[]
    for index,p in enumerate(sorted(root.glob('pass-*'))):
        news.require(p.name==f'pass-{index:02d}' and not p.is_symlink(),'refill_pass_sequence')
        news.require((p/'commit.json').is_file(),'interrupted_acquisition_not_repeated')
        commit=json.loads((p/'commit.json').read_bytes())
        news.require(set(commit)=={'binding','files'} and set(commit['files'])=={'state.json','result.json','aggregate.json'}
                     and commit['binding']==binding,'saved_collection_binding')
        for name,sha in commit['files'].items():
            news.require(name in ('state.json','result.json','aggregate.json') and news.b.digest(_owned(p,name).read_bytes())==sha,'saved_item_pin')
        value=json.loads((p/'result.json').read_bytes());state=json.loads((p/'state.json').read_bytes())
        news.require(value['binding']==binding and state['binding']==binding,'saved_collection_binding')
        result.append((p,value,state))
    return result


def _initial(source,round_):
    from zoop_ai_pipeline.news_archives import initial_tasks
    descriptor=news.profile(source['sourceId'])[1]
    return [asdict(t) for t in initial_tasks(source['sourceId'],round_['windowFrom'][:10],round_['windowTo'][:10],descriptor=descriptor)]


def _state(registry,round_,binding):
    return {'binding':binding,'requests':0,'networkSeconds':0.0,'downloadedBytes':0,
            'lastHosts':{},'attemptedUrls':[],'textDigests':[],'sources':{s['sourceId']:{
                'sourceId':s['sourceId'],'status':'partial' if news.authorized(s) else 'rights_prerequisite',
                'listingPages':0,'articleAttempts':0,'retained':0,'excluded':{},'halted':False,
                'queue':_initial(s,round_) if news.authorized(s) else [],'candidates':[],
                'seenTasks':[],'refreshes':0} for s in registry[0]['sources']}}


def _reason(state,round_,p):
    if (datetime.fromisoformat(round_['windowTo'])-now()).total_seconds()<=p['nativeReserveSeconds']:return 'preparation_deadline'
    if state['requests']>=p['maxRequests']:return 'request_budget'
    if state['networkSeconds']>=p['maxNetworkSeconds']:return 'time_budget'
    if state['downloadedBytes']>=p['maxBytes']:return 'byte_budget'
    return None


def _aggregate(passes,registry,binding,p,round_,*,saved=True):
    entries=[];items=[];state=passes[-1][2] if passes else _state(registry,round_,binding)
    for root,value,_ in passes:
        for rel in value['items']:
            item=_owned(root,rel)
            for name,sha in value['itemPins'][rel].items():
                news.require(name in ('row.json','export.json','rights.json','sources.json','collection-result.json')
                             and news.b.digest(_owned(item,name).read_bytes())==sha,'saved_item_pin')
            row=json.loads((item/'row.json').read_bytes());exported=json.loads((item/'export.json').read_bytes())
            news.current_source({'newsSourceRegistry':binding['registryPath']},row['sourceId'],binding['registrySha256'])
            news.require(Path(row['nativeItemRoot'])==item,'saved_item_path')
            news.publication_in_window(exported['observation']['publishedAt'],round_,row['fetchedAt'])
            body=root/'native/collections'/row['candidate']['newsId']/'bodies'/(row['nativeBodySha256']+'.bin')
            news.require(news.b.digest(body.read_bytes())==row['nativeBodySha256'],'saved_body_pin')
            entries.append((row,exported,root));items.append(str(item))
    if passes and saved:
        return entries,json.loads((passes[-1][0]/'aggregate.json').read_bytes())
    sources=[{k:v for k,v in s.items() if k not in ('queue','candidates','seenTasks')} for s in state['sources'].values()]
    reason=_reason(state,round_,p)
    if len(passes)>=p['maxPasses']:reason=reason or 'pass_limit'
    elif not any(not s['halted'] and (s['queue'] or s['candidates'] or s['refreshes']==0)
                 and news.authorized(next(x for x in registry[0]['sources'] if x['sourceId']==s['sourceId']))
                 for s in state['sources'].values()):reason=reason or 'sources_exhausted'
    return entries,{'schemaVersion':news.RESULT,'binding':binding,'sources':sources,'items':items,
        'status':'partial','complete':False,'modelCalls':0,'memberSpecificRequests':0,
        'collectionPolicy':VERSION,'passCount':len(passes),'targetDocuments':p['targetDocuments'],
        'targetReached':len(entries)>=p['targetDocuments'],'canRefill':reason is None,
        'stopReason':reason,'requests':state['requests'],'networkSeconds':state['networkSeconds'],
        'downloadedBytes':state['downloadedBytes'],
        'message':'Bounded registered sources; a document target is not a new-issue or market-coverage guarantee.'}


def collect(cfg,round_,parent,*,fetcher_factory=None,monotonic=time.monotonic,refill=False,sleep=time.sleep):
    from zoop_ai_pipeline.collection import Fetcher
    from zoop_ai_pipeline.news_archives import ArchiveTask,Candidate,parse_listing,validate_article_url
    p=policy(cfg);registry=news.load_registry(cfg)
    if registry is None:
        return news.collect({k:v for k,v in cfg.items() if k!='newsCollectionPolicy'},round_,parent,fetcher_factory=fetcher_factory,monotonic=monotonic)
    root=parent/'news-sources-refill-v1';root.mkdir(mode=0o700,parents=True,exist_ok=True)
    binding={'roundId':round_['id'],'windowFrom':round_['windowFrom'],'windowTo':round_['windowTo'],
             'registrySha256':registry[1],'registryPath':str(Path(cfg['newsSourceRegistry']).resolve()),
             'policySha256':news.b.digest(news.b.canonical(p))}
    passes=_read_passes(root,binding)
    if passes:
        prior=_aggregate(passes,registry,binding,p,round_)
        if not refill or not prior[1]['canRefill']:return prior
    state=copy.deepcopy(passes[-1][2]) if passes else _state(registry,round_,binding)
    dest=root/f'pass-{len(passes):02d}';dest.mkdir(mode=0o700)
    write_once(dest/'started.json',binding)
    items=[];sources=registry[0]['sources'];target_before=len(state['textDigests'])
    # Once an initial pool was rejected, an explicit refill must still acquire a new batch.
    goal=max(p['targetDocuments'],target_before+p['articlesPerSourcePass'] if refill and target_before>=p['targetDocuments'] else 0)
    companies=None
    if cfg.get('companyCatalogue'):
        from briefing_company_names import catalogue_companies
        companies=catalogue_companies(json.loads(Path(cfg['companyCatalogue']).read_bytes()))

    def fetch(fetcher,url,source,discovery=False):
        news.current_source(cfg,source['sourceId'],registry[1])
        reason=_reason(state,round_,p);news.require(reason is None,reason or 'budget')
        host=urlsplit(url).netloc;wait=max(0,2-(now().timestamp()-state['lastHosts'].get(host,0)))
        if wait:sleep(wait);state['networkSeconds']+=wait
        reason=_reason(state,round_,p);news.require(reason is None,reason or 'budget')
        base=news.policy().model_copy(update={'max_requests':max(1,min(30,getattr(fetcher,'requests',0)+p['maxRequests']-state['requests'])),
            'max_total_bytes':max(1,min(30_000_000,getattr(fetcher,'downloaded',0)+p['maxBytes']-state['downloadedBytes']))})
        fetcher.policy=news.DiscoveryPolicy(base) if discovery else base
        fetcher.run_deadline=min(fetcher.run_deadline,monotonic()+p['maxNetworkSeconds']-state['networkSeconds'],
            monotonic()+max(0,(datetime.fromisoformat(round_['windowTo'])-now()).total_seconds()-p['nativeReserveSeconds']))
        start=monotonic();before=getattr(fetcher,'requests',0);bytes_before=getattr(fetcher,'downloaded',0)
        try:return fetcher.fetch(url)
        finally:
            state['requests']+=max(1,getattr(fetcher,'requests',before+1)-before)
            state['downloadedBytes']+=max(0,getattr(fetcher,'downloaded',bytes_before)-bytes_before)
            state['networkSeconds']+=max(0,monotonic()-start);state['lastHosts'][host]=now().timestamp()

    # Rotate which registered source goes first; no one publisher owns every pass.
    offset=len(passes)%max(1,len(sources));ordered=sources[offset:]+sources[:offset]
    for source in ordered:
        sid=source['sourceId'];s=state['sources'][sid]
        if not news.authorized(source) or s['halted']:continue
        if _reason(state,round_,p):break
        row_profile,descriptor=news.profile(sid)
        fetcher=(fetcher_factory or Fetcher)(news.DiscoveryPolicy(news.policy()),row_profile['articleHosts'])
        fetcher.authority_guard=lambda sid=sid:news.current_source(cfg,sid,registry[1])
        source_root=dest/sid;source_root.mkdir(mode=0o700)
        try:
            news.current_source(cfg,sid,registry[1])
            if not s['queue'] and not s['candidates'] and s['refreshes']==0:
                s['queue']=_initial(source,round_);s['refreshes']=1;s['seenTasks']=[]
            if s['articleAttempts']>=source['maxArticleAttempts'] or s['retained']>=source['maxDocuments']:
                s['halted']=True;s['status']='source_limit';continue
            # Advance one listing per source/pass without starving other feeds or pending articles.
            if s['queue'] and s['listingPages']<source['maxListingPages']:
                task=ArchiveTask(**s['queue'].pop(0));s['listingPages']+=1
                response=fetch(fetcher,task.url,source,True)
                label='listing-'+news.b.digest(task.url.encode())[:24]
                news.b.write_once(source_root/(label+'.bin'),response.body)
                write_once(source_root/(label+'.json'),{'url':response.final_url,'observedAt':response.fetched_at,'sha256':news.b.digest(response.body)})
                listing=parse_listing(sid,task,response.body,response.final_url,descriptor=descriptor)
                s['seenTasks'].append(task.key)
                for task in listing.next_tasks:
                    if task.key not in s['seenTasks'] and task.key not in {t['key'] for t in s['queue']}:s['queue'].append(asdict(task))
                excess=max(0,len(s['queue'])-64)
                if excess:
                    s['excluded']['listing_queue_limit']=s['excluded'].get('listing_queue_limit',0)+excess
                    s['queue']=s['queue'][:64]
                existing={c['url'] for c in s['candidates']}|set(state['attemptedUrls'])
                for candidate in listing.candidates:
                    if candidate.url not in existing:
                        s['candidates'].append(asdict(candidate));existing.add(candidate.url)
                s['candidates'].sort(key=lambda c:news.discovery_rank(Candidate(**c),round_,companies or []),reverse=True)
                # Preserve the raw listing while bounding the resumable queue, even for very large sitemaps.
                excess=max(0,len(s['candidates'])-240)
                if excess:
                    s['excluded']['candidate_queue_limit']=s['excluded'].get('candidate_queue_limit',0)+excess
                    s['candidates']=s['candidates'][:240]
            for _ in range(p['articlesPerSourcePass']):
                if not s['candidates'] or _reason(state,round_,p):break
                if s['articleAttempts']>=source['maxArticleAttempts'] or s['retained']>=source['maxDocuments']:
                    s['halted']=True;s['status']='source_limit';break
                candidate=Candidate(**s['candidates'].pop(0));validate_article_url(sid,candidate.url,descriptor=descriptor)
                if candidate.url in state['attemptedUrls']:continue
                state['attemptedUrls'].append(candidate.url);s['articleAttempts']+=1
                try:
                    response=fetch(fetcher,candidate.url,source)
                    observation=source_root/('article-'+news.b.digest(candidate.url.encode())[:24])
                    news.b.write_once(observation.with_suffix('.bin'),response.body)
                    write_once(observation.with_suffix('.json'),{'url':response.final_url,'fetchedAt':response.fetched_at,'bodySha256':news.b.digest(response.body),'httpStatus':response.status})
                    row,exported,_=news.retain(source,registry[1],round_,dest,response,companies)
                    text_sha=news.b.digest(exported['document']['text'].encode())
                    if text_sha in state['textDigests']:
                        s['excluded']['duplicate_text']=s['excluded'].get('duplicate_text',0)+1;continue
                    state['textDigests'].append(text_sha);s['retained']+=1;items.append(str(Path(row['nativeItemRoot']).relative_to(dest)))
                    if len(state['textDigests'])>=goal:break
                except Exception as error:
                    code=getattr(error,'code',str(error))
                    if code in ('authority_changed','briefing_news_source_authority_changed','briefing_news_source_not_authorized'):raise
                    code=code if isinstance(code,str) and code.replace('_','').isalnum() and len(code)<130 else 'article_unavailable'
                    s['excluded'][code]=s['excluded'].get(code,0)+1
                    if code in news.DENIALS|{'timeout','request_budget','byte_budget'} or code.startswith('briefing_news_') and code.endswith(('budget','deadline')):
                        s['halted']=True;s['status']=code;break
        except Exception as error:
            code=getattr(error,'code',str(error))
            if code in ('authority_changed','briefing_news_source_authority_changed','briefing_news_source_not_authorized'):raise
            code=code if isinstance(code,str) and code.replace('_','').isalnum() and len(code)<130 else 'listing_unavailable'
            s['excluded'][code]=s['excluded'].get(code,0)+1;s['status']=code
            if code in news.DENIALS|{'timeout','request_budget','byte_budget'}:s['halted']=True
        if s['listingPages']>=source['maxListingPages'] and not s['candidates']:s['halted']=True;s['status']='source_limit'
        if len(state['textDigests'])>=goal:break
    pins={item:{name:news.b.digest((dest/item/name).read_bytes()) for name in ('row.json','export.json','rights.json','sources.json','collection-result.json')} for item in items}
    value={'binding':binding,'items':items,'itemPins':pins,'newDocuments':len(state['textDigests'])-target_before}
    write_once(dest/'state.json',state);write_once(dest/'result.json',value)
    passes.append((dest,value,state))
    entries,aggregate=_aggregate(passes,registry,binding,p,round_,saved=False)
    write_once(dest/'aggregate.json',aggregate)
    write_once(dest/'commit.json',{'binding':binding,'files':{name:news.b.digest((dest/name).read_bytes()) for name in ('state.json','result.json','aggregate.json')}})
    return entries,aggregate
