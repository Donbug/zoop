"""Series short reading is additive, independently checked, immutable and replayable without a price producer."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import briefing_company_reading as r
b=r.base
class ReadingSeriesTest(unittest.TestCase):
    def test_series_preserves_full_analysis_and_reuses_completed_short_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';output=root/'output';b.private_dir(source)
            company={'roundId':'authored-round','edition':'morning','cutoff':'2026-10-22T00:20:00Z','status':'PASS','resultVersion':'authored-full',
                'draft':{'companies':[{'companyId':'NASDAQ:ASML','assessment':'watch'}]},
                'frozen':{'targets':[{'companyId':'NASDAQ:ASML','sourceIds':['e']}],'sources':{'e':{'quote':'authored source'}}}}
            bundle={'roundSeries':{'schemaVersion':'authored'},'marketEnrichment':{'seriesCompanyOutlooks':{'rounds':[company]}}}
            b.save_json(source/'bundle-v2.json',bundle);calls=[]
            def transport(raw):
                calls.append(raw);q=b.strict_load(raw);d=b.strict_load(q['input'])
                if q['text']['format']['name'].endswith('verification'):
                    value={'checks':[{'companyId':'NASDAQ:ASML','supported':True,'reason':'authored source and original watch assessment retained'}]}
                else:
                    value={'companies':[{'companyId':'NASDAQ:ASML',**{k:{'text':'생산능력 확대 실행을 확인합니다.','evidenceIds':['e']} for k in ('brief','watch','change')}}]}
                return 200,b.canonical({'id':'authored-'+str(len(calls)),'status':'completed','usage':{'input_tokens':10,'output_tokens':10},
                    'output':[{'type':'message','content':[{'type':'output_text','text':b.canonical(value).decode()}]}]})
            args=SimpleNamespace(baseline=str(source),output=str(output),prices=None,authorization_ref='authored',run_id='authored',max_calls=4,execute=True)
            result=r.run(args,transport);self.assertEqual(result['pass'],1);self.assertEqual(len(calls),2)
            saved=b.strict_load(b.regular(output/'bundle-v2.json'))
            self.assertEqual(saved['marketEnrichment']['seriesCompanyOutlooks'],bundle['marketEnrichment']['seriesCompanyOutlooks'])
            reading=saved['marketEnrichment']['seriesCompanyReading']['rounds'][0]
            self.assertEqual(reading['pricePolicy'],'not_connected');self.assertNotIn('prices',reading)
            self.assertEqual(r.run(args,transport)['newPaidCalls'],0);self.assertEqual(len(calls),2)
            self.assertEqual(b.strict_load(b.regular(source/'bundle-v2.json')),bundle)
if __name__=='__main__':unittest.main()
