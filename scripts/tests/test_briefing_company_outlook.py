import copy
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('company_outlook',Path(__file__).parents[1]/'briefing_company_outlook.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class CompanyOutlookTest(unittest.TestCase):
    def frozen(self):
        return {'edition':'morning','targets':[{'companyId':'A','sourceIds':['a'],'previous':{'status':'unavailable'}}], 'sources':{'a':{}}}
    def draft(self):
        stmt={'text':'확인할 조건','evidenceIds':['a']}
        return {'companies':[{'companyId':'A','assessment':'watch','impact':stmt,'outlook':stmt,'conditions':[stmt],'risks':[stmt],
            'comparison':{**stmt,'status':'unavailable','previousResultVersion':None}}]}
    def test_edition_bound_comparison_schema_rejects_morning_status_in_evening(self):
        f=self.frozen();f['edition']='evening';f['comparisonContract']='edition-bound-v2'
        d=self.draft();d['companies'][0]['comparison']['status']='updated'
        with self.assertRaises(c.base.ReplayError):c.base.validate_schema(d,c.generation_schema(f))
    def test_foreign_company_evidence_rejected(self):
        f=self.frozen();f['sources']['b']={};d=copy.deepcopy(self.draft());d['companies'][0]['outlook']['evidenceIds']=['b']
        with self.assertRaisesRegex(ValueError,'foreign_company_evidence'): c.validate(d,f)
    def test_evening_never_uses_yesterdays_or_another_company_judgment(self):
        h=[{'status':'PASS','date':'2026-10-07','edition':'evening','draft':{'companies':[{'companyId':'A'}]}}]
        self.assertEqual('unavailable',c.previous_for('A','2026-10-08','evening',h)['status'])
    def test_v3_morning_does_not_call_an_older_morning_the_previous_evening(self):
        row={'status':'PASS','date':'2026-10-22','edition':'morning','roundId':'r','cutoff':'2026-10-22T09:20:00+09:00','resultVersion':'old-am','draft':{'companies':[{'companyId':'A'}]}}
        self.assertEqual('unavailable',c.previous_for('A','2026-10-23','morning',[row],strict=True)['status'])
        row['edition']='evening';row['resultVersion']='exact-pm'
        self.assertEqual('exact-pm',c.previous_for('A','2026-10-23','morning',[row],strict=True)['resultVersion'])

    def test_exact_previous_version_required(self):
        f=self.frozen();f['targets'][0]['previous']={'status':'available','resultVersion':'new'};d=self.draft();d['companies'][0]['comparison'].update(status='updated',previousResultVersion='old')
        with self.assertRaisesRegex(ValueError,'previous_version'): c.validate(d,f)
    def test_same_company_morning_update(self):
        row={'status':'PASS','date':'2026-10-07','edition':'evening','roundId':'r','cutoff':'2026-10-07T17:30:00+09:00','resultVersion':'v','draft':{'companies':[{'companyId':'A'}]}}
        self.assertEqual('v',c.previous_for('A','2026-10-08','morning',[row])['resultVersion'])
        self.assertEqual('unavailable',c.previous_for('B','2026-10-08','morning',[row])['status'])
    def test_cutoff_search_rejects_a_future_document(self):
        source={'documentId':'d','evidenceId':'a','bodySha256':'a'*64,'quote':'plan', 'publishedAt':'2026-10-08T10:00:00+09:00'}
        row={'roundId':'r','date':'2026-10-08','edition':'morning','marketEnrichment':{'marketContext':{
            'window':{'to':'2026-10-08T09:20:00+09:00'},'documents':[{'documentId':'d','companyNames':['A'],'sources':[source]}]}}}
        effective={'resultSha256':'b'*64,'selected':[{'issueId':'i','companyLinks':[{'companyId':'A','name':'A'}],'sources':[source]}],
            'result':{'items':[{'issueId':'i','claims':[{'text':'plan','evidenceIds':['a']}]}]}}
        with self.assertRaisesRegex(ValueError,'future_source'):
            c.freeze(row,effective,{'d':{'title':'source','url':'https://example.com'}},[])

    def test_valid_watch_still_has_outlook_and_conditions(self):
        c.validate(self.draft(),self.frozen())
        d=self.draft();d['companies'][0]['conditions']=[]
        with self.assertRaises(c.base.ReplayError): c.validate(d,self.frozen())

    def test_v4_selected_only_presentation_cannot_invent_background_sources(self):
        source={'documentId':'d','evidenceId':'a','bodySha256':'a'*64,'quote':'A가 계약 이행을 계획한다.',
                'publishedAt':'2026-10-22T17:00:00+09:00'}
        row={'roundId':'r','date':'2026-10-22','edition':'evening','marketEnrichment':{'cutoff':'2026-10-22T17:30:00+09:00'}}
        effective={'resultSha256':'b'*64,'selected':[{'issueId':'i','companyLinks':[{'companyId':'A','name':'A'}],'sources':[source]}],
                   'result':{'items':[{'issueId':'i','claims':[{'text':'계약 이행 계획','evidenceIds':['a']}]}]}}
        frozen=c.freeze(row,effective,{'d':{'title':'원문','url':'https://example.com/source'}},[],version='company-outlook-v4')
        self.assertEqual(['a'],frozen['targets'][0]['sourceIds']);self.assertEqual({'a'},set(frozen['sources']))
        self.assertEqual('unavailable',frozen['targets'][0]['previous']['status'])
        self.assertEqual('edition-bound-v2',frozen['comparisonContract'])

if __name__=='__main__': unittest.main()
