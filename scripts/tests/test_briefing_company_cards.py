from pathlib import Path
import copy
import sys
import unittest
import tempfile
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).parents[1]))
import briefing_company_reading as r
import briefing_company_cards as cards

class CompanyCardsTest(unittest.TestCase):
    def previous_fixture(self,root):
        baseline=root/'baseline';previous=root/'previous';baseline.mkdir();previous.mkdir()
        layer={'maximumPaidCallsIncludingPrior':160,'companyOutlookLayer':{'rounds':[{'roundId':'r','status':'PASS'}]}}
        bundle={'presentationEnrichment':layer}
        (baseline/'bundle-v2.json').write_bytes(r.base.canonical(bundle))
        old=copy.deepcopy(bundle);old['presentationEnrichment']['maximumPaidCallsIncludingPrior']=180
        old['presentationEnrichment']['companyCardLayer']={'rounds':[{'roundId':'r','status':'PASS'}]}
        (previous/'bundle-v2.json').write_bytes(r.base.canonical(old))
        args=SimpleNamespace(baseline=str(baseline),previous_cards=str(previous),output=str(root/'out'),
            prompt_version='company-card-v2',run_id='test',authorization_ref='authored-test',max_calls=180,execute=False)
        return args,previous,old
    def test_previous_presentation_cards_survive_only_accounting_ceiling_change(self):
        with tempfile.TemporaryDirectory() as temp:
            args,_,_=self.previous_fixture(Path(temp));plan=cards.run(args)
            self.assertEqual(plan['minimumNewCalls'],0);self.assertEqual(plan['newPaidCalls'],0)
    def test_accounting_exception_does_not_accept_changed_analysis_or_lower_budget(self):
        for changed in ('content','ceiling'):
            with tempfile.TemporaryDirectory() as temp:
                args,path,old=self.previous_fixture(Path(temp))
                if changed=='content':
                    old['presentationEnrichment']['companyOutlookLayer']['rounds'][0]['resultVersion']='different'
                    (path/'bundle-v2.json').write_bytes(r.base.canonical(old))
                else:args.max_calls=160
                with self.assertRaisesRegex(ValueError,'card_previous_'):cards.run(args)
    def frozen(self):
        return {'schemaVersion':r.SCHEMA_CARD, 'targets':[{'companyId':'A','sourceIds':['a']}], 'sources':{'a':{},'b':{}}}
    def draft(self):
        return {'companies':[{'companyId':'A', 'topic':{'text':'설비 투자','evidenceIds':['a']},
            'title':{'text':'2028년까지 도입 계획','evidenceIds':['a']},
            'description':{'text':'실제 도입 규모는 자료에 없음','evidenceIds':['a']}}]}
    def test_three_distinct_roles_and_no_long_prose_fallback(self):
        d=self.draft();r.validate(d,self.frozen())
        del d['companies'][0]['description']
        with self.assertRaises(r.base.ReplayError):r.validate(d,self.frozen())
    def test_long_headline_foreign_evidence_and_duplicate_evidence_are_rejected(self):
        for change in ('long','foreign','duplicate'):
            d=self.draft();s=d['companies'][0]['title']
            if change=='long':s['text']='긴 문장'*20
            if change=='foreign':s['evidenceIds']=['b']
            if change=='duplicate':s['evidenceIds']=['a','a']
            with self.assertRaises((r.base.ReplayError,ValueError)):r.validate(d,self.frozen())
    def test_qualifier_verification_cannot_be_overridden_by_supported(self):
        test=self
        class Client:
            def request_digest(self,*a):return 'a'*64
            def call(self,stage,*a):
                if stage.endswith('generation'):return test.draft()
                return {'checks':[{'companyId':'A','supported':True,'reason':'계획 한정 누락',
                    'quality':{k:k!='qualifiersPreserved' for k in r.CARD_QUALITY}}]}
        result=r.assess(Client(),self.frozen())
        self.assertEqual(result['status'],'WITHHELD');self.assertIsNone(result['draft'])
    def test_provider_contract_requires_every_quality_check(self):
        with self.assertRaises(r.base.ReplayError):
            r.base.validate_schema({'checks':[{'companyId':'A','supported':True,'reason':'not sufficient'}]},r.verification_schema(self.frozen()))
    def test_completed_attempts_are_preserved_on_repair(self):
        previous=[{'error':'previous failure','draft':self.draft(),'generationRequestDigest':'b'*64}]
        original=copy.deepcopy(previous);test=self
        class Client:
            def request_digest(self,*a):return 'a'*64
            def call(self,stage,*a):
                if stage.endswith('generation'):return test.draft()
                return {'checks':[{'companyId':'A','supported':True,'reason':'same-source plan retained',
                    'quality':{k:True for k in r.CARD_QUALITY}}]}
        result=r.assess(Client(),self.frozen(),initial_attempts=previous,card_prompt_version='company-card-v2')
        self.assertEqual(result['status'],'PASS');self.assertEqual(previous,original)
        self.assertEqual(result['attempts'][0],original[0]);self.assertEqual(result['attempts'][1]['promptVersion'],'company-card-v2')

if __name__=='__main__':unittest.main()
