import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import briefing_native_intake as n
import briefing_samsung_intake as s

class SourcePriorityTests(unittest.TestCase):
    companies=[{'companyId':'NAVER','name':'네이버','aliases':[]},{'companyId':'SAMSUNG','name':'삼성전자','aliases':[]},
               {'companyId':'AMD','name':'AMD','aliases':[]}]
    def entry(self,title,text,day='2026-11-04',url='https://example.invalid/one'):
        matched=n.source_matches(text,self.companies)
        return ({'candidate':{'title':title,'publicationDay':day,'url':url},'inputPriority':n.source_priority(title,text,self.companies,matched)},None,matched,None)
    def test_real_business_change_precedes_incidental_tool_use_and_later_day(self):
        tool=self.entry('QR코드를 활용한 안전교육','네이버 QR코드를 사용해 안전교육을 진행했다.','2026-11-05')
        event=self.entry('삼성전자, 제품 허가 획득','삼성전자가 제품 판매에 필요한 허가를 획득했다.')
        self.assertEqual(event,max([tool,event],key=n.source_rank))
    def test_negative_business_events_have_the_same_preparation_access(self):
        negative=self.entry('삼성전자 공장 가동 중단','삼성전자는 공장 가동을 중단했다.')
        self.assertEqual(1,negative[0]['inputPriority']['rank'][0])
    def test_short_verified_fact_is_not_excluded_by_character_count(self):
        event=self.entry('AMD 공급 계약','AMD가 공급 계약을 체결했다.')
        self.assertGreater(event[0]['inputPriority']['businessClauseCount'],0)
    def test_company_mentions_and_price_alone_do_not_become_business_verdicts(self):
        event=self.entry('삼성전자 주가 상승','삼성전자 주가가 2% 상승했다.')
        self.assertEqual(0,event[0]['inputPriority']['rank'][0])
        self.assertNotIn('sentiment',event[0]['inputPriority'])
    def test_equal_company_independent_events_are_both_retained(self):
        rows=[self.entry('삼성전자 공급 계약','삼성전자 공급 계약.'),self.entry('삼성전자 공장 증설','삼성전자 공장 증설.')]
        self.assertEqual(2,len(sorted(rows,key=n.source_rank)))
    def test_appending_one_source_grant_keeps_all_previous_values(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'grants.json';old={'schemaVersion':'zoop-ai-s1-1','grants':[{'grantId':'old','enabled':False,'evidence':['original']}]}
            p.write_text(json.dumps(old));n.ensure_grants(p,[{'grantId':'new','enabled':True}])
            actual=json.loads(p.read_text());self.assertEqual(old['grants'][0],actual['grants'][0])
            before=p.read_bytes();n.ensure_grants(p,[old['grants'][0]]);self.assertEqual(before,p.read_bytes())
            with self.assertRaisesRegex(ValueError,'existing_grant_values_changed'):n.ensure_grants(p,[{'grantId':'old','enabled':True}])
    def test_withheld_and_unknown_preparations_are_not_reused_as_unattempted_sources(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t)
            for state in ('withheld','unknown'):
                root=base/state;native=root/(state+'-native-v2');native.mkdir(parents=True)
                (root/'selected-source.json').write_text(json.dumps({'documentId':state,'documentVersion':'original'}))
                (native/'native.started.json').write_text('{}')
            self.assertEqual({('withheld','original'),('unknown','original')},n.attempted_documents(base))

class OfficialFeedTests(unittest.TestCase):
    def test_actual_native_collection_and_ingestion_keep_original_body_clock_and_publisher(self):
        from zoop_ai_pipeline.collection import Fetched
        from zoop_ai_pipeline.ingestion_contracts import byte_hash
        url='https://news.samsung.com/kr/synthetic-release'
        raw=('<html><head><meta property="og:title" content="삼성전자 합성 제품 허가"/>'
             '<meta property="og:site_name" content="삼성전자 뉴스룸"/>'
             '<meta property="article:published_time" content="2026-11-05T08:00:00+09:00"/>'
             '<link rel="canonical" href="'+url+'"/></head><body><div class="single_contents">'
             '<p>삼성전자는 합성 제품 허가를 받았다. 실제 사건이 아닌 회귀 시험 문장이다.</p></div></body></html>').encode()
        captured=Fetched(url,url,200,'text/html','text/html',raw,
            {'content-length':str(len(raw)),'etag':None,'last-modified':None,'date':None},[],[],1,fetched_at='2026-11-05T08:10:00+09:00')
        notice=Fetched(s.NOTICE,s.NOTICE,200,'text/html','text/html',b'synthetic policy fixture',{},[],[],1)
        with tempfile.TemporaryDirectory() as t:
            row,exported,_=s.retain({'authorizationRef':'synthetic-only'},
                {'id':'synthetic-source-round','windowFrom':'2026-11-04T17:30:00+09:00','windowTo':'2026-11-05T08:30:00+09:00'},
                Path(t).resolve(),captured,'SamsungNewsroom',notice)
            self.assertEqual(byte_hash(raw),row['nativeBodySha256'])
            self.assertEqual('samsung-newsroom',exported['observation']['sourceId'])
            self.assertIn('합성 제품 허가',exported['document']['text'])
            self.assertEqual('삼성전자 뉴스룸',row['candidate']['publisher'])
            self.assertEqual('2026-11-05T08:10:00+09:00',row['fetchedAt'])

    def feed(self,items):
        return ('<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>'+''.join(
            '<item><link>https://news.samsung.com/kr/'+name+'</link><dc:creator>'+author+'</dc:creator><pubDate>'+date+'</pubDate></item>'
            for name,author,date in items)+'</channel></rss>').encode()
    def test_recent_feed_entry_is_first_and_external_author_is_not_admitted(self):
        raw=self.feed([('old','SamsungNewsroom','Tue, 03 Nov 2026 00:00:00 +0000'),
                       ('external','외부 기고자','Thu, 05 Nov 2026 00:00:00 +0000'),
                       ('new','SamsungNewsroom','Wed, 04 Nov 2026 23:00:00 +0000')])
        rows=s.feed_candidates(raw,'2026-11-04','2026-11-05')
        self.assertEqual(['https://news.samsung.com/kr/new'],[r['url'] for r in rows])
    def test_entities_and_foreign_urls_are_not_discovery_targets(self):
        with self.assertRaisesRegex(ValueError,'feed_xml'):s.feed_candidates(b'<!DOCTYPE rss><rss/>','2026-11-04','2026-11-05')
        raw=self.feed([('okay','SamsungNewsroom','Thu, 05 Nov 2026 00:00:00 +0000')]).replace(b'https://news.samsung.com/kr/okay',b'https://attacker.invalid/kr/okay')
        self.assertEqual([],s.feed_candidates(raw,'2026-11-04','2026-11-05'))
    def test_unknown_publication_or_named_external_author_is_refused(self):
        from types import SimpleNamespace
        meta=SimpleNamespace(published_at=None,publisher='Samsung',article_xpath='//article')
        r={'windowFrom':'2026-11-05T00:00:00+09:00','windowTo':'2026-11-05T08:30:00+09:00'}
        with patch('zoop_ai_pipeline.news_archives.article_metadata',return_value=meta):
            with self.assertRaisesRegex(ValueError,'article_metadata'):s.article_facts(b'<article/>','https://news.samsung.com/kr/one',r)
        meta.published_at='2026-11-05T08:00:00+09:00';meta.canonical_url=None
        with patch('zoop_ai_pipeline.news_archives.article_metadata',return_value=meta):
            with self.assertRaisesRegex(ValueError,'external_author'):s.article_facts(b'<html><meta name="author" content="Guest Writer"/><article/></html>','https://news.samsung.com/kr/one',r)
            with self.assertRaisesRegex(ValueError,'future_publication'):s.article_facts(b'<article/>','https://news.samsung.com/kr/one',r,'2026-11-05T07:00:00+09:00')

if __name__=='__main__':unittest.main()
