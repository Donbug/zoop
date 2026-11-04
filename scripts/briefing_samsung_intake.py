"""First-party Samsung text into the existing native collector and ingestion ledger.

Opt-in, no model calls. A published reuse notice and an in-house byline are both
required. Images, attachments, external authors and unknown timestamps are refused.
RSS only orders acquisition; the actual article supplies publication and text.
"""
from __future__ import annotations
from datetime import datetime
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
from urllib.parse import urlsplit

import briefing_replay as b
from briefing_usage import write_once

SOURCE='samsung-newsroom'
FEED='https://news.samsung.com/kr/feed'
NOTICE='https://news.samsung.com/kr/%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90-%EB%89%B4%EC%8A%A4%EB%A3%B8-%EC%BD%98%ED%85%90%EC%B8%A0-%EC%9D%B4%EC%9A%A9%EC%97%90-%EB%8C%80%ED%95%9C-%EC%95%88%EB%82%B4'
OWN_AUTHORS={'SamsungNewsroom','Samsung Newsroom','삼성전자 뉴스룸','삼성전자뉴스룸'}

def require(ok,reason):
    if not ok:raise ValueError('briefing_samsung_'+reason)

def feed_candidates(raw,first,last):
    """Hints are never promoted to article publication clocks."""
    from lxml import etree
    require(len(raw)<=5_000_000 and b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(),'feed_xml')
    root=etree.fromstring(raw,parser=etree.XMLParser(resolve_entities=False,no_network=True))
    require(root.tag=='rss' and len(root.findall('./channel'))==1,'feed_xml')
    entries=root.findall('./channel/item');require(len(entries)<=1000,'feed_size')
    selected=[]
    for ordinal,item in enumerate(entries):
        creator=(item.findtext('{http://purl.org/dc/elements/1.1/}creator') or '').strip()
        if creator not in OWN_AUTHORS:continue
        try:
            stamp=parsedate_to_datetime(item.findtext('pubDate') or '')
            require(stamp.tzinfo is not None,'feed_time')
        except (TypeError,ValueError,OverflowError):continue
        # Broad discovery dates only; source body and actual observed time are checked below.
        if not first<=stamp.date().isoformat()<=last:continue
        url=item.findtext('link') or '';p=urlsplit(url)
        if p.scheme!='https' or p.netloc!='news.samsung.com' or not p.path.startswith('/kr/') or p.query or p.fragment:continue
        selected.append({'url':url,'creator':creator,'hint':stamp.isoformat(),'ordinal':ordinal})
    return sorted(selected,key=lambda x:(x['hint'],-x['ordinal']),reverse=True)

def article_facts(raw,url,round_,observed_at=None):
    from lxml import html
    from zoop_ai_pipeline.news_archives import article_metadata
    from zoop_ai_pipeline.news_sources import source_descriptor
    meta=article_metadata(SOURCE,raw,url,descriptor=source_descriptor(SOURCE))
    require(bool(meta.published_at) and bool(meta.publisher) and bool(meta.article_xpath),'article_metadata')
    tree=html.document_fromstring(raw)
    authors=tree.xpath('//meta[translate(@name,"AUTHOR","author")="author"]/@content | //header//*[@rel="author"]/text()')
    require(all(a.strip() in OWN_AUTHORS for a in authors if a.strip()),'external_author')
    published=datetime.fromisoformat(meta.published_at)
    cutoff=datetime.fromisoformat(round_['windowTo']);start=datetime.fromisoformat(round_['windowFrom'])
    if published.tzinfo is not None:
        require(start<published<=cutoff,'article_outside_window')
        if observed_at:require(published<=datetime.fromisoformat(observed_at),'future_publication')
    else:
        require(len(meta.published_at)==10 and start.date().isoformat()<=meta.published_at<=cutoff.date().isoformat(),'article_day')
    require(meta.canonical_url is None or meta.canonical_url==url,'article_identity')
    return meta

def policy():
    from zoop_ai_pipeline.collection_contracts import Policy
    return Policy.model_validate({'schemaVersion':'zoop-collection-policy-1','userAgent':'ZoopBriefing/1.0',
        'timeoutSeconds':20,'maxTotalSeconds':120,'maxRedirects':0,'maxRequests':12,
        'maxResponseBytes':5_000_000,'maxTotalBytes':40_000_000,'minIntervalSeconds':2,
        'allowedMediaTypes':['text/html'],'syntheticLoopback':False})

class DiscoveryPolicy:
    def __init__(self,base):self.base=base;self.allowed_media_types=['text/html','text/xml','application/xml','application/rss+xml']
    def __getattr__(self,key):return getattr(self.base,key)

def retain(cfg,round_,root,response,creator,notice):
    from zoop_ai_pipeline.collection import Fetcher,collect as native_collect
    from zoop_ai_pipeline.collection_contracts import Request
    from zoop_ai_pipeline.ingestion import Ingestor,Store
    from zoop_ai_pipeline.ingestion_contracts import Authority,Run,Export
    meta=article_facts(response.body,response.final_url,round_,response.fetched_at)
    observed=datetime.fromisoformat(response.fetched_at)
    require(datetime.fromisoformat(round_['windowFrom'])<observed<=datetime.fromisoformat(round_['windowTo']),'observed_outside_window')
    identifier='samsung-'+b.digest(response.final_url.encode())[:32]
    item=root/'items'/identifier;item.mkdir(mode=0o700,parents=True,exist_ok=True)
    native=root/'native';native.mkdir(mode=0o700,exist_ok=True);scope=identifier;body_policy=policy()
    rights={'sourceId':SOURCE,'rightsBasis':'publisher-first-party-text-reuse-notice','noticeUrl':NOTICE,
        'noticeBodySha256':b.digest(notice.body),'creator':creator,'articleUrl':response.final_url,
        'bodySha256':b.digest(response.body),'fetchedAt':response.fetched_at,
        'restrictions':['first-party text only','no images, attachments, third-party bylines or raw-article redistribution','literal evidence stays unchanged; generated analysis is separate'],
        'authorizationRef':cfg.get('sourceAuthorizationRef',cfg['authorizationRef'])}
    write_once(item/'rights.json',rights)
    grant={'grantId':round_['id']+'-samsung-acquisition','revision':'publisher-first-party-text-1','sourceId':SOURCE,
        'enabled':True,'rights':'known','allowedOperations':['read','store','quote-display'],'recipients':[],'purposes':[],
        'evidence':[NOTICE,'Verified first-party RSS creator and article byline; native original retained; no external articles or media.'], 'expiresAt':None}
    sources={'schemaVersion':'zoop-ingestion-s2-1','revision':round_['id']+'-samsung-1','sources':[{
        'sourceId':SOURCE,'adapter':'collected-http','inputRoot':str(native),'allowedHosts':['news.samsung.com'],
        'scopes':[{'scopeId':scope,'selection':'one verified in-house Samsung article','initialCursor':None,
            'articleXPath':meta.article_xpath,'timestampLimitations':['RSS is discovery only; actual article publication metadata and real GET observation retained']}],
        'grant':grant}]}
    write_once(item/'sources.json',sources)
    target={'candidateId':identifier,'url':response.final_url,'supplierDocumentId':identifier,'title':meta.title,
        'publisher':meta.publisher,'publishedAt':meta.published_at,'documentKind':'news'}
    request=Request.model_validate({'schemaVersion':'zoop-collection-1','collectionId':identifier,'sourceId':SOURCE,'scopeId':scope,'targets':[target]})
    class Captured(Fetcher):
        def fetch(self,url):
            require(url==response.final_url,'captured_response_identity')
            self.authority_guard();return response
    capture=Captured(body_policy,['news.samsung.com'])
    result=native_collect(item/'sources.json',body_policy,request,fetcher=capture,
        validate_response=lambda target,body:require(b.digest(body.body)==rights['bodySha256'],'body_pin'))
    require(result['state']=='complete','native_collection')
    write_once(item/'collection-result.json',result)
    store=Store(item/'ingestion')
    try:
        engine=Ingestor(store,Authority(item/'sources.json'))
        ingested=engine.run(Run.model_validate({'schemaVersion':'zoop-ingestion-s2-1','roundId':identifier,'sourceId':SOURCE,
            'scopeId':scope,'window':None,'checkpointRevision':0,'fixtureManifestHash':result['manifest']['sha256'],'cleanerVersion':'exact-copy-1'}),Path(result['manifestPath']))
        ref=ingested['documentRefs'][0]
        exported=engine.export(Export.model_validate({'schemaVersion':'zoop-ingestion-s2-1','roundId':identifier,'sourceId':SOURCE,
            **{k:ref[k] for k in ('page','ordinal','documentId','rawVersion','documentVersion')}}),require_store=True)
    finally:store.close()
    write_once(item/'export.json',exported)
    row={'sourceId':SOURCE,'nativeItemRoot':str(item),'candidate':{'newsId':identifier,'channel':'first-party-newsroom',
        'title':meta.title,'publisher':meta.publisher,'publicationDay':meta.published_at[:10],'url':response.final_url},
        'documentId':ref['documentId'],'documentVersion':ref['documentVersion'],'fetchedAt':response.fetched_at,
        'nativeBodySha256':result['targets'][0]['bodySha256'],'nativeReceiptSha256':result['targets'][0]['receiptSha256'],'rights':rights}
    return row,exported,root

def collect(cfg,round_,parent):
    from zoop_ai_pipeline.collection import Fetcher
    root=parent/'samsung-newsroom';root.mkdir(mode=0o700,parents=True,exist_ok=True)
    done=root/'result.json'
    if done.exists():
        saved=json.loads(done.read_bytes())
        return [(json.loads((root/p/'row.json').read_bytes()),json.loads((root/p/'export.json').read_bytes()),root) for p in saved['items']]
    require(not (root/'started.json').exists(),'interrupted_acquisition_not_repeated')
    write_once(root/'started.json',{'at':b.now(),'authorizationRef':cfg['authorizationRef'],'modelCalls':0})
    fetcher=Fetcher(DiscoveryPolicy(policy()),['news.samsung.com']);items=[];errors=[]
    try:
        notice=fetcher.fetch(NOTICE)
        text=notice.body.decode('utf-8')
        require('직접 제작한 기사와 이미지' in text and '자유롭게 사용' in text and '작성자' in text,'reuse_notice_changed')
        write_once(root/'notice.json',{'url':NOTICE,'sha256':b.digest(notice.body),'observedAt':notice.fetched_at})
        b.write_once(root/'notice.html',notice.body)
        feed=fetcher.fetch(FEED);b.write_once(root/'feed.xml',feed.body)
        candidates=feed_candidates(feed.body,round_['windowFrom'][:10],round_['windowTo'][:10])
        for candidate in candidates[:3]:
            try:
                fetcher.policy=policy();response=fetcher.fetch(candidate['url'])
                result=retain(cfg,round_,root,response,candidate['creator'],notice)
                row,exported,_=result;item=Path(row['nativeItemRoot']);write_once(item/'row.json',row)
                items.append(str(item.relative_to(root)))
                if len(items)==2:break
            except Exception as error:errors.append({'url':candidate['url'],'reason':str(error)[:160]})
    except Exception as error:errors.append({'reason':str(error)[:160]})
    finally:
        write_once(done,{'items':items,'errors':errors,'coverage':'rolling official feed, first-party text only; partial','modelCalls':0})
    return [(json.loads((root/p/'row.json').read_bytes()),json.loads((root/p/'export.json').read_bytes()),root) for p in items]
