from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
import briefing_reading_evaluation as e
class PairwiseTest(unittest.TestCase):
 def check(self,cid):
  return {'companyId':cid,'supportedA':True,'supportedB':True,**{k:'tie' for k in e.CRITERIA},'reason':'동일 근거에 대한 합성 비교'}
 def test_duplicate_company_cannot_hide_a_missing_comparison(self):
  with self.assertRaisesRegex(ValueError,'coverage'):
   e.validate_judgment({'checks':[self.check('A'),self.check('A'),self.check('B')]},['A','B','C'])
 def test_each_dimension_is_required_and_a_tie_is_valid(self):
  value={'checks':[self.check('A'),self.check('B'),self.check('C')]};e.validate_judgment(value,['A','B','C'])
  del value['checks'][0]['continuity']
  with self.assertRaises(e.base.ReplayError):e.validate_judgment(value,['A','B','C'])
 def test_three_companies_of_one_story_are_not_three_representative_issues(self):
  f={'targets':[{'companyId':x,'issueIds':['same-story']} for x in ('A','B','C')]}
  self.assertEqual(e.representative_cases(f),[])
  f['targets'][0]['issueIds'].append('second-story');f['targets'][2]['issueIds']=['third-story']
  self.assertEqual(e.representative_cases(f),[])
  f['targets'][0]['issueIds']=['second-story']
  cases=e.representative_cases(f);self.assertEqual(len({c['issueId'] for c in cases}),3)
 def test_same_input_hash_ignores_only_output_contract_version(self):
  row={'frozen':{'schemaVersion':'v1','sources':{'a':'actual quote'},'previous':'exact-version'}}
  other={'frozen':{**row['frozen'],'schemaVersion':'v2'}}
  self.assertEqual(e.compare_input(row),e.compare_input(other))
  other['frozen']['previous']='another-version';self.assertNotEqual(e.compare_input(row),e.compare_input(other))
 def test_multi_round_sampling_preserves_round_identity_and_distinct_company_issues(self):
  rows=[{'roundId':'r1','frozen':{'targets':[{'companyId':'A','issueIds':['one']},{'companyId':'B','issueIds':['two']}]}},
        {'roundId':'r2','frozen':{'targets':[{'companyId':'A','issueIds':['three']},{'companyId':'C','issueIds':['three']}]}}]
  cases=e.representative_round_cases(rows)
  self.assertEqual(3,len(cases));self.assertEqual({'A','B','C'},{c['companyId'] for c in cases})
  self.assertEqual({'one','two','three'},{c['issueId'] for c in cases})
  self.assertEqual('r2',next(c['roundId'] for c in cases if c['companyId']=='C'))
if __name__=='__main__':unittest.main()
