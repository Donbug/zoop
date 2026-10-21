"""Saved comparison only: new role failures and rejected raw slots must stay visible."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('compare_test',Path(__file__).parents[1]/'briefing_outlook_compare.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class CompareTest(unittest.TestCase):
    def bundle(self,root,summary):
        value={'presentationEnrichment':{'rounds':[{'roundId':'round-one','marketEnrichment':{
            'roundId':'round-one','date':'2026-10-08','edition':'evening',
            'context':{'summaryPromptVersion':'market-context-v2.4-outlook'},
            'marketContext':{'coverage':{'documents':1},'previousPublication':{'status':'available'}},
            'summaryResult':summary}}]}}
        p=root/'bundle-v2.json';p.write_text(json.dumps(value));return p
    def summary(self):
        return {'verification':{'status':'WITHHELD','checks':[]},'claims':[],'forecasts':[],
                'forecastEvaluations':[],'resultVersion':None,'text':None,'generationRequestDigest':'saved-generation'}
    def test_new_role_false_is_visible_even_if_provider_verdict_is_supported(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);s=self.summary();s['verification']['checks']=[{'verdict':'SUPPORTED','factUnitAppropriate':False,'reason':'Authored fact-role rejection'}]
            p=self.bundle(root,s);v=c.compare(p,p)['rounds'][0]['new']
            self.assertEqual(['Authored fact-role rejection'],v['rejectionReasons'])
    def test_rejected_forecast_slot_is_audit_only_and_never_published(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'calls').mkdir();p=self.bundle(root,self.summary())
            draft={'claims':[{'kind':'fact','text':'Authored raw fact'}],
                   'requiredClaims':{'forecast':{'kind':'forecast','text':'Authored rejected outlook'},
                                     'result_comparison':{'kind':'result_comparison','text':'Authored rejected comparison'}}}
            response={'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(draft)}]}]}
            (root/'calls/saved-generation.response.json').write_text(json.dumps(response))
            v=c.compare(p,p)['rounds'][0]['new']
            self.assertEqual(['fact','forecast','result_comparison'],[x['kind'] for x in v['rejectedDraft']])
            self.assertEqual([],v['claims']);self.assertEqual([],v['forecasts']);self.assertIsNone(v['text'])

if __name__=='__main__':unittest.main()
