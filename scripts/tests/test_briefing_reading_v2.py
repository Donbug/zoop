"""New roles and quality decisions are independent of legacy length-only reading."""
from pathlib import Path
import copy,sys,unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
import briefing_company_reading as r
class ReadingV2Test(unittest.TestCase):
 def frozen(self):
  return {'schemaVersion':r.SCHEMA_V2,'targets':[{'companyId':'A','sourceIds':['a']}],'sources':{'a':{},'b':{}}}
 def draft(self):
  return {'companies':[{'companyId':'A',**{k:{'text':k+' 구체적 관측','evidenceIds':['a']} for k in ('brief','fact','watch','background','change')}}]}
 def test_roles_are_required_and_longer_judgment_does_not_erase_fact(self):
  d=self.draft();d['companies'][0]['brief']['text']='판단'*40;r.validate(d,self.frozen())
  del d['companies'][0]['fact']
  with self.assertRaises(r.base.ReplayError):r.validate(d,self.frozen())
 def test_background_cannot_cite_another_company(self):
  d=self.draft();d['companies'][0]['background']['evidenceIds']=['b']
  with self.assertRaisesRegex(ValueError,'foreign_source'):r.validate(d,self.frozen())
 def test_factually_supported_but_generic_text_is_withheld_after_one_repair(self):
  test=self
  class Client:
   def request_digest(self,*a,**kw):return 'a'*64
   def call(self,stage,*a):
    if stage.endswith('generation'):return test.draft()
    return {'checks':[{'companyId':'A','supported':True,'reason':'factual but generic',
      'quality':{k:k!='specificity' for k in r.QUALITY}}]}
  result=r.assess(Client(),self.frozen())
  self.assertEqual(result['status'],'WITHHELD');self.assertIsNone(result['draft']);self.assertEqual(len(result['attempts']),2)
 def test_quality_false_or_missing_does_not_become_supported(self):
  schema=r.verification_schema(self.frozen());d={'checks':[{'companyId':'A','supported':True,'reason':'source checked'}]}
  with self.assertRaises(r.base.ReplayError):r.base.validate_schema(d,schema)
 def test_copied_judgments_across_companies_are_rejected(self):
  f=self.frozen();f['targets'].append({'companyId':'B','sourceIds':['a']})
  d=self.draft();second=copy.deepcopy(d['companies'][0]);second['companyId']='B';d['companies'].append(second)
  with self.assertRaisesRegex(ValueError,'repeated_brief'):r.validate(d,f)
 def test_v1_schema_remains_unchanged(self):
  f=self.frozen();f['schemaVersion']=r.SCHEMA
  d=self.draft();d['companies'][0].pop('fact');d['companies'][0].pop('background');r.validate(d,f)
  self.assertNotIn('quality',r.verification_schema(f)['properties']['checks']['items']['properties'])
if __name__=='__main__':unittest.main()
