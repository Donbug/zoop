import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('bundle', Path(__file__).parents[1] / 'prepare_briefing_server_bundle.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


class ServerPreparationTest(unittest.TestCase):
    def test_nonlisted_organization_is_not_made_into_a_tradable_ticker(self):
        org=B.company_record('ORG:OPENAI','OpenAI')
        self.assertIsNone(org['ticker']);self.assertIsNone(org['exchange_code'])
        listed=B.company_record('KRX:005930','삼성전자')
        self.assertEqual(listed['ticker'],'005930');self.assertEqual(listed['exchange_code'],'KRX')

    def test_mismatching_archive_digest_fails_before_any_projection(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'records.sqlite3'
            with sqlite3.connect(path) as c:
                c.execute('create table round_results(scope,day,edition,payload,sha256)')
                c.execute('insert into round_results values(?,?,?,?,?)',('common','2026-10-28','morning','{}','0'*64))
            with self.assertRaisesRegex(ValueError,'digest'):
                B.rows(path)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d); marker=path/'previous';marker.write_text('keep')
            with self.assertRaisesRegex(ValueError,'already exists'):
                B.prepare(path/'missing',path,path,path,path/'missing',path)
            self.assertEqual(marker.read_text(),'keep')

    def test_article_citations_and_market_context_are_separate_without_rewriting_text(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'summary-views-v2').mkdir()
            context={'context:market':{'value':100},'context:sessions':{'cutoff':'2026-10-28T09:20:00+09:00'},'context:previous':{'status':'unavailable'}}
            (root/'summary-views-v2/2026-10-28-morning.json').write_text(json.dumps({'references':context}))
            p={'date':'2026-10-28','edition':'morning','id':'r','dataAsOf':'2026-10-28T00:20:00Z','marketSummary':{'text':'saved text','resultVersion':'unchanged-v1','evidenceIds':['news','context:market','context:sessions','context:previous']}}
            before=B.canonical(p)
            summary,display,retained=B.project_summary(p,root,{'news':{}})
            self.assertEqual(display['text'],'saved text');self.assertEqual(display['resultVersion'],'unchanged-v1')
            self.assertEqual(summary['evidenceIds'],['news'])
            self.assertEqual(retained['originalReferenceIds'],p['marketSummary']['evidenceIds'])
            self.assertEqual(set(retained['contexts']),set(context))
            self.assertEqual(B.canonical(p),before)

    def test_foreign_or_future_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'summary-views-v2').mkdir()
            (root/'summary-views-v2/2026-10-28-morning.json').write_text(json.dumps({'references':{'context:previous':{'cutoff':'2026-10-28T00:20:00Z'}}}))
            p={'date':'2026-10-28','edition':'morning','id':'r','dataAsOf':'2026-10-28T00:20:00Z','marketSummary':{'text':'saved','resultVersion':'v','evidenceIds':['news','context:previous']}}
            with self.assertRaisesRegex(ValueError,'future previous'):
                B.project_summary(p,root,{'news':{}})
            p['marketSummary']['evidenceIds']=['invented-citation']
            with self.assertRaisesRegex(ValueError,'unresolved'):
                B.project_summary(p,root,{'news':{}})

    def test_exact_source_check_does_not_accept_modified_quotes(self):
        source={'documentId':'d','evidenceId':'e','bodySha256':B.digest(b'original'),'quote':'changed','url':'https://example.invalid','publishedAt':'2026-10-27T00:00:00Z'}
        units={'d':{'text':'original','title':'title'}}
        with self.assertRaisesRegex(ValueError,'quote mismatch'):
            B.register_source({},units,'e',source)


if __name__=='__main__':
    unittest.main()
