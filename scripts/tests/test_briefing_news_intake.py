"""Synthetic source clocks/permissions plus the real native collector/ingestor; no network/model."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import briefing_news_intake as news
import briefing_native_intake as native
from zoop_ai_pipeline.collection import Fetched


def source(source_id='nvidia-blog'):
    return {'sourceId': source_id, 'enabled': True, 'authorizationRef': 'synthetic-source-review',
        'nativeProcessing': {'profile': 'briefing-native-v2-standard', 'recipients': ['openai', 'typesafe-native'],
                             'authorizationRef': 'synthetic-native-processing-only'},
        'maxListingPages': 1, 'maxArticleAttempts': 3, 'maxDocuments': 2,
        'grant': {'grantId': 'synthetic-' + source_id, 'revision': 'synthetic-v1', 'sourceId': source_id,
        'enabled': True, 'rights': 'known', 'allowedOperations': sorted(news.OPERATIONS),
        'recipients': ['openai'], 'purposes': ['briefing-outlook', 'semantic-verification'],
        'evidence': ['Synthetic test permission only; not a real publisher licence.'], 'expiresAt': None}}


def article(url='https://blogs.nvidia.com/blog/synthetic-release/', observed='2026-11-05T08:10:00+09:00',
            published='2026-11-05T08:00:00+09:00'):
    raw = ('<html><head><meta property="og:title" content="NVIDIA 합성 제품 출시"/>'
        '<meta property="og:site_name" content="합성 공식 뉴스룸"/>'
        '<meta property="article:published_time" content="' + published + '"/>'
        '<link rel="canonical" href="' + url + '"/></head><body><div class="entry-content">'
        '<p>NVIDIA는 합성 제품을 출시했다. 실제 사건이 아닌 회귀 시험용 원문이다.</p></div></body></html>').encode()
    return Fetched(url, url, 200, 'text/html', 'text/html', raw,
        {'content-length': str(len(raw)), 'etag': None, 'last-modified': None, 'date': None}, [], [], 1, fetched_at=observed)


class NewsIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.round = {'id': 'synthetic-news-round', 'windowFrom': '2026-11-04T17:30:00+09:00',
                      'windowTo': '2026-11-05T08:30:00+09:00'}

    def registry(self, sources=None):
        path = self.root / 'registry.json'
        path.write_text(json.dumps({'schemaVersion': news.SCHEMA, 'revision': 'synthetic-v1',
                                   'sources': sources if sources is not None else [source()]}))
        path.chmod(0o600)
        return {'newsSourceRegistry': str(path)}

    def test_real_native_export_pins_exact_body_publisher_and_source_clocks(self):
        captured = article()
        row, exported, _ = news.retain(source(), 'a' * 64, self.round, self.root, captured)
        self.assertEqual('collected_http', exported['observation']['provenance'])
        self.assertEqual(captured.fetched_at, row['fetchedAt'])
        self.assertEqual('2026-11-05T08:00:00+09:00', exported['observation']['publishedAt'])
        self.assertEqual('합성 공식 뉴스룸', exported['observation']['publisher'])
        self.assertIn('실제 사건이 아닌 회귀 시험용', exported['document']['text'])
        body = self.root / 'native/collections' / row['candidate']['newsId'] / 'bodies' / (row['nativeBodySha256'] + '.bin')
        self.assertEqual(captured.body, body.read_bytes())
        self.assertFalse(row['rights']['rawRedistribution'])

    def test_new_hankyung_body_shape_keeps_article_only_and_legacy_scope(self):
        url='https://www.hankyung.com/article/synthetic123'
        head='<html><head><meta property="og:title" content="삼성전자 합성 계약"/><meta property="og:site_name" content="합성 언론"/><meta property="article:published_time" content="2026-11-05T08:00:00+09:00"/></head><body>'
        body='<article class="article-container"><div class="article-body-wrap"><div class="article-body">삼성전자는 합성 공급 계약을 체결했다.</div><div class="article-license">LICENSE OUTSIDE</div></div><aside>RELATED OUTSIDE</aside></article>'
        captured=article(url=url);object.__setattr__(captured,'body',(head+body+'</body></html>').encode())
        row,exported,_=news.retain(source('hankyung-feed'),'a'*64,self.round,self.root,captured)
        self.assertIn('합성 공급 계약',exported['document']['text'])
        self.assertNotIn('LICENSE OUTSIDE',exported['document']['text']);self.assertNotIn('RELATED OUTSIDE',exported['document']['text'])
        self.assertEqual(captured.fetched_at,row['fetchedAt'])

    def test_duplicate_hankyung_bodies_remain_ambiguous(self):
        from zoop_ai_pipeline.news_archives import article_metadata
        url='https://www.hankyung.com/article/synthetic123'
        raw=b'<html><head><meta property="og:title" content="synthetic"/></head><body><article class="article-container"><div class="article-body-wrap"><div class="article-body">one</div><div class="article-body">two</div></div></article></body></html>'
        with self.assertRaisesRegex(Exception,'article_scope_ambiguous_or_missing'):article_metadata('hankyung-feed',raw,url)

    def test_new_scope_still_rejects_explicit_access_restrictions(self):
        from zoop_ai_pipeline.ingestion_parsers import prepare
        from zoop_ai_pipeline.news_archives import article_metadata
        url='https://www.hankyung.com/article/synthetic123'
        raw=b'<html><head><meta property="og:title" content="synthetic"/></head><body><article class="article-container"><div class="article-body-wrap"><div class="article-body">synthetic body</div></div><div class="subscription-required">restricted</div></article></body></html>'
        meta=article_metadata('hankyung-feed',raw,url)
        with self.assertRaisesRegex(Exception,'access_restricted'):prepare(raw,'text/html',meta.article_xpath)

    def test_discovery_days_only_prioritize_and_never_replace_source_clock_checks(self):
        from zoop_ai_pipeline.news_archives import Candidate
        companies=[{'companyId':'a','name':'Apple','aliases':[]}]
        fresh=Candidate('https://example.invalid/fresh','other company',None,None,'2026-11-05')
        old=Candidate('https://example.invalid/old','Apple investment',None,None,'2026-11-03')
        self.assertGreater(news.discovery_rank(fresh,self.round,companies),news.discovery_rank(old,self.round,companies))
        with self.assertRaisesRegex(ValueError,'publication_outside_window'):
            news.publication_in_window('2026-11-03T08:00:00+09:00',self.round,'2026-11-05T08:10:00+09:00')

    def test_expanded_discovery_stays_bounded_by_the_operator_registry(self):
        selected=source();selected.update(maxListingPages=3,maxArticleAttempts=24,maxDocuments=8)
        cfg=self.registry([selected]);self.assertEqual(24,news.load_registry(cfg)[0]['sources'][0]['maxArticleAttempts'])
        selected['maxArticleAttempts']=25;Path(cfg['newsSourceRegistry']).write_text(json.dumps({'schemaVersion':news.SCHEMA,'revision':'synthetic-v2','sources':[selected]}))
        with self.assertRaisesRegex(ValueError,'source_limit'):news.load_registry(cfg)

    def test_foreign_canonical_or_changed_article_identity_is_not_admitted(self):
        captured = article()
        object.__setattr__(captured, 'body', captured.body.replace(captured.final_url.encode(), b'https://attacker.invalid/other'))
        with self.assertRaisesRegex(ValueError, 'article_identity'):
            news.retain(source(), 'a' * 64, self.round, self.root, captured)

    def test_only_related_article_body_consumes_the_native_document_allowance(self):
        with self.assertRaisesRegex(ValueError, 'no_catalogued_company'):
            news.retain(source(), 'a' * 64, self.round, self.root, article(),
                companies=[{'companyId': 'synthetic-apple', 'name': 'Apple', 'aliases': []}])
        self.assertFalse((self.root / 'items').exists())

    def test_serving_permission_does_not_implicitly_authorize_another_native_recipient(self):
        selected = source(); selected['nativeProcessing']['recipients'] = ['openai']
        self.assertFalse(news.authorized(selected))
        selected = source(); selected['grant']['recipients'] = ['unrelated-provider']
        self.assertFalse(news.authorized(selected))

    def test_article_date_observation_and_window_are_independent(self):
        for published, observed, reason in [
            ('2026-11-04T17:30:00+09:00', '2026-11-05T08:10:00+09:00', 'publication_outside_window'),
            ('2026-11-05T08:00:00+09:00', '2026-11-05T08:31:00+09:00', 'observed_outside_window'),
            ('2026-11-05T08:15:00+09:00', '2026-11-05T08:10:00+09:00', 'publication_outside_window'),
            ('2026-11-05T08:00:00', '2026-11-05T08:10:00+09:00', 'publication_timezone_missing'),
            ('2026-11-03', '2026-11-05T08:10:00+09:00', 'publication_outside_window')]:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                news.publication_in_window(published, self.round, observed)

    def test_visible_calendar_day_stays_a_day_and_uses_only_the_real_first_observation(self):
        round_ = {**self.round, 'windowFrom': '2026-11-03T17:30:00+09:00'}
        news.publication_in_window('November 4, 2026', round_, '2026-11-05T08:10:00+09:00')
        news.publication_in_window('2026.11.04', round_, '2026-11-05T08:10:00+09:00')
        self.assertEqual('first_observed', news.publication_in_window('November 4, 2026', self.round, '2026-11-05T08:10:00+09:00'))
        self.assertEqual('published_at', news.publication_in_window('2026-11-05T08:00:00+09:00', self.round, '2026-11-05T08:10:00+09:00'))
        with self.assertRaisesRegex(ValueError, 'observed_outside_window'):
            news.publication_in_window('November 4, 2026', self.round, '2026-11-05T08:31:00+09:00')

    def test_unknown_rights_never_become_public_or_model_permissions(self):
        denied = source(); denied['grant']['rights'] = 'unknown'
        cfg = self.registry([denied]); factory = Mock()
        entries, result = news.collect(cfg, self.round, self.root / 'collection', fetcher_factory=factory)
        self.assertEqual([], entries); factory.assert_not_called()
        self.assertEqual('rights_prerequisite', result['sources'][0]['status'])
        self.assertEqual(0, result['modelCalls']); self.assertEqual(0, result['memberSpecificRequests'])

    def test_no_registry_is_an_explicit_coverage_gap_and_never_a_model_call(self):
        entries, result = news.collect({}, self.round, self.root / 'collection', fetcher_factory=Mock())
        self.assertEqual([], entries); self.assertEqual('not_configured', result['status'])
        self.assertFalse(result['complete'])
        self.assertEqual(0, result['modelCalls'])

    def test_registry_file_permissions_and_revocation_are_checked_again(self):
        cfg = self.registry(); registry, digest = news.load_registry(cfg)
        self.assertEqual(source(), news.current_source(cfg, 'nvidia-blog', digest))
        value = copy.deepcopy(registry); value['sources'][0]['enabled'] = False
        Path(cfg['newsSourceRegistry']).write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'source_authority_changed'):
            news.current_source(cfg, 'nvidia-blog', digest)
        Path(cfg['newsSourceRegistry']).chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'private_registry_required'):
            news.load_registry(cfg)

    def test_supported_editorial_and_first_party_adapters_use_distinct_profiles(self):
        self.assertEqual('editorial', news.profile('etnews-ai')[0]['category'])
        self.assertEqual('editorial', news.profile('hankyung-daily')[0]['category'])
        self.assertEqual('corporate-pr', news.profile('amd-newsroom')[0]['category'])
        for unsupported in ('reuters-business', 'gdelt-doc', 'missing-source'):
            with self.assertRaises(ValueError): news.profile(unsupported)

    def test_append_serving_grant_preserves_old_authorities_and_cannot_replace_them(self):
        cfg = {**self.registry(), 'authorityRoot': str(self.root / 'authority'),
               'originalSourceAuthority': '/synthetic/original', 'authorizationRef': 'synthetic-only'}
        native.initialize_authority(cfg)
        path = self.root / 'authority/grants.json'; before = path.read_bytes()
        grants = json.loads(before)['grants']
        self.assertEqual(source()['grant'], next(g for g in grants if g['sourceId'] == 'nvidia-blog'))
        native.initialize_authority(cfg)
        self.assertEqual(before, path.read_bytes())

    def test_source_failure_does_not_stop_other_authorized_publishers_and_completed_results_are_reused(self):
        cfg = self.registry([source('meta-newsroom'), source()])
        round_ = self.round
        captured = article()
        feed = ('<rss version="2.0"><channel><item><title>합성 NVIDIA 출시</title><link>' + captured.final_url +
                '</link><pubDate>Wed, 04 Nov 2026 23:00:00 +0000</pubDate></item></channel></rss>').encode()
        class Fetch:
            def __init__(self, policy, hosts):
                self.policy = policy; self.run_deadline = float('inf'); self.authority_guard = None
            def fetch(self, url):
                self.authority_guard()
                if 'about.fb.com' in url: raise RuntimeError('synthetic listing unavailable')
                if url.endswith('/feed/'):
                    return Fetched(url, url, 200, 'application/rss+xml', 'application/rss+xml', feed, {}, [], [], 1,
                                   fetched_at=captured.fetched_at)
                return captured
        factory = Mock(side_effect=Fetch)
        with patch.object(news, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat('2026-11-05T08:05:00+09:00')
            entries, result = news.collect(cfg, round_, self.root / 'collection', fetcher_factory=factory)
        self.assertEqual('listing_unavailable', result['sources'][0]['status'])
        self.assertEqual(1, len(entries)); self.assertEqual('nvidia-blog', entries[0][0]['sourceId'])
        before = {p: p.read_bytes() for p in (self.root / 'collection').rglob('*.json')}
        factory.reset_mock()
        reused, same = news.collect(cfg, round_, self.root / 'collection', fetcher_factory=factory)
        factory.assert_not_called(); self.assertEqual(result, same); self.assertEqual(entries, reused)
        self.assertTrue(all(p.read_bytes() == raw for p, raw in before.items()))
        row = Path(entries[0][0]['nativeItemRoot']) / 'export.json'; row.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'saved_item_pin'):
            news.collect(cfg, round_, self.root / 'collection', fetcher_factory=factory)


if __name__ == '__main__': unittest.main()
