"""Actual native collection/ingestion with synthetic news pages; no model or external network."""
import copy
from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import briefing_news_intake as news
import briefing_news_refill as refill
from prepare_briefing_news_registry import prepare as prepare_registry
from test_briefing_news_intake import source,article
from zoop_ai_pipeline.collection import Fetched


class NewsRefillTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.parent=self.root/'collection'
        self.round={'id':'synthetic-refill','windowFrom':'2026-11-04T17:30:00+09:00','windowTo':'2026-11-05T08:30:00+09:00'}
        self.clock=datetime.fromisoformat('2026-11-05T08:05:00+09:00');self.seconds=0;self.sent=[]
        self.registry=self.root/'sources.json'
        self.cfg={'newsSourceRegistry':str(self.registry),'newsCollectionPolicy':{'version':refill.VERSION,**refill.DEFAULTS,
                   'targetDocuments':3,'articlesPerSourcePass':1}}
        self.save([source()])

    def save(self,sources):
        self.registry.write_text(json.dumps({'schemaVersion':news.EXPANDED_SCHEMA,'revision':'synthetic-v2','sources':sources}))
        self.registry.chmod(0o600)

    def sleep(self,seconds):self.seconds+=seconds;self.clock+=timedelta(seconds=seconds)

    def factory(self,policy,hosts):
        test=self
        class Fetch:
            def __init__(self):self.policy=policy;self.run_deadline=float('inf');self.authority_guard=None;self.requests=0;self.downloaded=0
            def fetch(self,url):
                self.authority_guard();test.sent.append(url);self.requests+=1
                if 'feed' in url:
                    origin='https://blogs.nvidia.com/blog/'
                    links=''.join(f'<item><title>NVIDIA synthetic contract {i}</title><link>{origin}synthetic-{i}/</link><pubDate>Wed, 04 Nov 2026 23:00:00 +0000</pubDate></item>' for i in range(1,5))
                    body=('<rss version="2.0"><channel>'+links+'</channel></rss>').encode()
                    return Fetched(url,url,200,'application/rss+xml','application/rss+xml',body,{},[],[],1,fetched_at=test.clock.isoformat())
                row=article(url=url,observed=test.clock.isoformat());row.body=row.body.replace('합성 제품을'.encode(),('합성 '+url.rsplit('/',2)[-2]+' 제품을').encode());self.downloaded+=len(row.body);return row
        return Fetch()

    def collect(self,extra=False):
        with patch.object(news,'datetime',wraps=datetime) as clock:
            clock.now.side_effect=lambda *args:self.clock
            return refill.collect(self.cfg,self.round,self.parent,fetcher_factory=self.factory,monotonic=lambda:self.seconds,refill=extra,sleep=self.sleep)

    def test_refill_adds_only_unvisited_urls_and_preserves_original_pass_and_native_bodies(self):
        entries,first=self.collect();self.assertEqual(1,len(entries));self.assertTrue(first['canRefill'])
        original={p:p.read_bytes() for p in (self.parent/'news-sources-refill-v1/pass-00').rglob('*') if p.is_file()}
        entries,second=self.collect(True)
        self.assertEqual(2,len(entries));self.assertEqual(2,second['passCount'])
        self.assertEqual(2,len([u for u in self.sent if 'synthetic-' in u]));self.assertEqual(len(self.sent),len(set(self.sent)))
        self.assertTrue(all(p.read_bytes()==raw for p,raw in original.items()))
        self.assertTrue(all('실제 사건이 아닌' in exported['document']['text'] for _,exported,_ in entries))
        self.assertEqual(0,second['modelCalls']);self.assertEqual(0,second['memberSpecificRequests'])
        saved=copy.deepcopy(second);sent=list(self.sent);self.clock+=timedelta(days=1)
        repeated,reused=self.collect()
        self.assertEqual(saved,reused);self.assertEqual(sent,self.sent);self.assertEqual(2,len(repeated))

    def test_initial_target_is_not_an_obstacle_to_explicit_post_rejection_refill(self):
        self.cfg['newsCollectionPolicy']['targetDocuments']=1
        entries,result=self.collect();self.assertTrue(result['targetReached']);self.assertTrue(result['canRefill'])
        entries,result=self.collect(True);self.assertEqual(2,len(entries));self.assertEqual(2,result['passCount'])

    def test_hard_request_budget_and_cutoff_stop_before_another_request(self):
        self.cfg['newsCollectionPolicy']['maxRequests']=2
        entries,result=self.collect();self.assertEqual(2,result['requests']);self.assertFalse(result['canRefill'])
        sent=list(self.sent);self.collect(True);self.assertEqual(sent,self.sent)
        with tempfile.TemporaryDirectory() as other:
            self.parent=Path(other)/'late';self.clock=datetime.fromisoformat('2026-11-05T08:25:00+09:00');self.sent=[]
            entries,result=self.collect();self.assertEqual([],entries);self.assertFalse(self.sent)
            self.assertEqual('preparation_deadline',result['stopReason'])

    def test_preconnection_refusal_does_not_invent_a_physical_request(self):
        from zoop_ai_pipeline.ingestion_contracts import IngestionFailure
        class Refused:
            def __init__(self,*args):self.requests=0;self.downloaded=0;self.run_deadline=float('inf')
            def fetch(self,url):raise IngestionFailure('private_address')
        self.factory=Refused
        entries,result=self.collect()
        self.assertEqual([],entries);self.assertEqual(0,result['requests'])
        self.assertEqual(1,result['sources'][0]['excluded']['private_address'])

    def test_expired_refill_window_appends_a_zero_call_boundary_without_rewriting_the_saved_result(self):
        entries,first=self.collect();self.clock=datetime.fromisoformat('2026-11-05T08:25:00+09:00')
        sent=list(self.sent);entries,last=self.collect(True)
        self.assertEqual(sent,self.sent);self.assertEqual(2,last['passCount']);self.assertFalse(last['canRefill'])
        self.assertEqual('preparation_deadline',last['stopReason'])
        self.assertEqual(first['requests'],last['requests'])

    def test_partial_pass_is_not_automatically_repeated_and_source_revocation_is_not_hidden(self):
        self.collect();pass1=self.parent/'news-sources-refill-v1/pass-01';pass1.mkdir();(pass1/'started.json').write_text('{}')
        sent=list(self.sent)
        with self.assertRaisesRegex(ValueError,'interrupted_acquisition_not_repeated'):self.collect(True)
        self.assertEqual(sent,self.sent)
        (pass1/'started.json').unlink();pass1.rmdir()
        value=json.loads(self.registry.read_bytes());value['sources'][0]['enabled']=False;self.save(value['sources'])
        with self.assertRaisesRegex(ValueError,'saved_collection_binding'):self.collect()

    def test_unauthorized_sources_remain_disabled_and_received_failures_do_not_stop_other_sources(self):
        denied=source('meta-newsroom');denied['grant']['rights']='unknown';self.save([denied,source()])
        entries,result=self.collect();self.assertEqual(1,len(entries))
        self.assertEqual('rights_prerequisite',result['sources'][0]['status'])
        self.assertTrue(all('about.fb.com' not in u for u in self.sent))

    def test_multiple_publishers_are_interleaved_and_share_one_request_budget(self):
        self.save([source(),source('amd-newsroom')]);self.cfg['newsCollectionPolicy']['maxRequests']=4
        original=self.factory
        def factory(policy,hosts):
            if 'newsroom.amd.com' not in hosts:return original(policy,hosts)
            test=self
            class AMD:
                def __init__(self):self.policy=policy;self.run_deadline=float('inf');self.requests=0;self.downloaded=0
                def fetch(self,url):
                    self.authority_guard();test.sent.append(url);self.requests+=1
                    if 'rss' in url or 'sitemap' in url:
                        if 'sitemap' in url:
                            body=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://newsroom.amd.com/news/synthetic-first</loc></url></urlset>'
                        else:body=b'<rss><channel><item><title>AMD synthetic contract</title><link>https://newsroom.amd.com/news/synthetic-first</link></item></channel></rss>'
                        return Fetched(url,url,200,'application/xml','application/xml',body,{},[],[],1,fetched_at=test.clock.isoformat())
                    raw=('<html><head><meta property="og:title" content="AMD synthetic contract"/><meta property="og:site_name" content="Synthetic AMD"/>'
                         '<meta property="article:published_time" content="2026-11-05T08:00:00+09:00"/><link rel="canonical" href="'+url+'"/></head>'
                         '<body><article><div class="article-body"><div class="content-body">AMD 합성 투자 계약. 실제 기사가 아닌 회귀 시험입니다.</div></div></article></body></html>').encode()
                    return Fetched(url,url,200,'text/html','text/html',raw,{'content-length':str(len(raw)),'etag':None,'last-modified':None,'date':None},[],[],1,fetched_at=test.clock.isoformat())
            return AMD()
        self.factory=factory
        entries,result=self.collect()
        self.assertEqual({'nvidia-blog','amd-newsroom'},{e[0]['sourceId'] for e in entries},result)
        self.assertEqual(4,result['requests']);self.assertEqual(4,len(self.sent));self.assertFalse(result['canRefill'])

    def test_robots_denial_is_not_retried_in_a_later_pass(self):
        from zoop_ai_pipeline.ingestion_contracts import IngestionFailure
        self.save([source('meta-newsroom'),source()]);original=self.factory
        def factory(policy,hosts):
            if 'about.fb.com' not in hosts:return original(policy,hosts)
            test=self
            class Denied:
                def __init__(self):self.policy=policy;self.run_deadline=float('inf');self.requests=0;self.downloaded=0
                def fetch(self,url):
                    test.sent.append(url);self.requests+=1;raise IngestionFailure('robots_denied')
            return Denied()
        self.factory=factory
        entries,result=self.collect();self.assertEqual(1,len(entries))
        entries,result=self.collect(True);self.assertEqual(2,len(entries))
        self.assertEqual(1,len([u for u in self.sent if 'about.fb.com' in u]))

    def test_same_text_at_a_different_url_is_preserved_but_not_added_to_the_pool(self):
        original=self.factory
        def factory(policy,hosts):
            fetcher=original(policy,hosts);get=fetcher.fetch
            def fetch(url):
                response=get(url)
                if 'synthetic-' in url:
                    slug=url.rsplit('/',2)[-2]
                    response.body=response.body.replace(('합성 '+slug+' 제품을').encode(),'합성 제품을'.encode())
                return response
            fetcher.fetch=fetch;return fetcher
        self.factory=factory
        self.collect();entries,result=self.collect(True)
        self.assertEqual(1,len(entries));self.assertEqual(1,result['sources'][0]['excluded']['duplicate_text'])
        self.assertEqual(2,len(list((self.parent/'news-sources-refill-v1').glob('pass-*/items/*/export.json'))))

    def test_legacy_completed_collection_remains_byte_identical_when_new_policy_is_present(self):
        legacy={k:v for k,v in self.cfg.items() if k!='newsCollectionPolicy'}
        with patch.object(news,'datetime',wraps=datetime) as clock:
            clock.now.side_effect=lambda *args:self.clock
            entries,result=news.collect(legacy,self.round,self.parent,fetcher_factory=self.factory,monotonic=lambda:self.seconds)
        before={p:p.read_bytes() for p in self.parent.rglob('*') if p.is_file()};sent=list(self.sent)
        _,reused=news.collect(self.cfg,self.round,self.parent,fetcher_factory=Mock(side_effect=AssertionError('unexpected GET')))
        self.assertEqual(result,reused);self.assertEqual(sent,self.sent)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
        self.assertFalse((self.parent/'news-sources-refill-v1').exists())

    def test_registry_expansion_preserves_all_existing_authorities_and_never_edits_the_active_file(self):
        before=self.registry.read_bytes();additional=self.root/'extra.json'
        extra=source('meta-newsroom');additional.write_text(json.dumps([extra]));additional.chmod(0o600)
        out=self.root/'new/sources-v2.json';proof=prepare_registry(self.registry,out,'synthetic-expanded',additional)
        self.assertEqual(before,self.registry.read_bytes());value=json.loads(out.read_bytes())
        old=json.loads(before)['sources'][0]
        self.assertEqual(old['grant'],value['sources'][0]['grant']);self.assertEqual(old['nativeProcessing'],value['sources'][0]['nativeProcessing'])
        self.assertEqual(2,len(value['sources']));self.assertEqual(60,value['sources'][0]['maxArticleAttempts'])
        self.assertEqual(0,proof['modelCalls']);self.assertFalse(proof['activeRegistryChanged'])
        self.assertEqual(0o600,out.stat().st_mode&0o777)

    def test_registry_expansion_rejects_enabled_unknown_rights_instead_of_manufacturing_a_grant(self):
        extra=source('meta-newsroom');extra['nativeProcessing']['recipients']=['openai']
        path=self.root/'extra.json';path.write_text(json.dumps([extra]));path.chmod(0o600)
        out=self.root/'new/invalid.json'
        with self.assertRaisesRegex(ValueError,'enabled_source_authority_required'):prepare_registry(self.registry,out,'invalid-native-recipient',path)
        self.assertFalse(out.exists())

    def test_private_registry_cannot_be_written_through_an_alias_into_a_checkout(self):
        checkout=self.root/'checkout';checkout.mkdir();(checkout/'.git').write_text('synthetic worktree marker')
        alias=self.root/'alias';alias.symlink_to(checkout,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'registry_outside_checkout'):
            prepare_registry(self.registry,alias/'private-registry.json','synthetic-new')
        self.assertFalse((checkout/'private-registry.json').exists())


if __name__=='__main__':unittest.main()
