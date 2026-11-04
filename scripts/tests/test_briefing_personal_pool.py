"""Receipt integrity and whole-pool offline compilation; all material is synthetic."""
import copy
import unittest
import briefing_personal_pool as personal
import briefing_issue_intelligence as m
from test_briefing_issue_intelligence import frozen, assess, checks

class PersonalPoolTests(unittest.TestCase):
    def setUp(self):
        self.f=m.seal({**frozen(4),'scope':'synthetic_test','baselineResponseSha256':'b'*64})
        self.a=assess(self.f);self.v=checks(self.f)
        self.row={'assessments':self.a,'selectionVerification':self.v,'passed':[]}
        self.calls=[{'key':'generation','stage':'selection','input':{'frozen':self.f},'answer':self.a},
                    {'key':'verification','stage':'selection-verification','input':{'frozen':self.f,'draft':self.a},'answer':self.v}]
    def test_compiles_all_candidates_not_only_three_selected_and_keeps_unregistered_sources_closed(self):
        old=copy.deepcopy(self.f)
        pool=personal.compile_pool(self.f,self.row,self.calls,{})
        self.assertEqual(4,len(pool['candidates']))
        self.assertEqual(old,self.f)
        self.assertEqual([],pool['candidates'][0]['sources'][0]['recipients'])
        self.assertEqual(0,pool['proof']['newAiCalls'])
        self.assertIsNone(pool['candidates'][0]['analysis'])
    def test_missing_independent_receipt_and_changed_assessment_cannot_be_imported(self):
        with self.assertRaises(ValueError):personal.compile_pool(self.f,self.row,self.calls[:1],{})
        changed=copy.deepcopy(self.row);changed['assessments']['assessments']['i0']['businessImportance']=3
        with self.assertRaises(ValueError):personal.compile_pool(self.f,changed,self.calls,{})
    def test_document_binding_cannot_overwrite_an_individual_evidence_passage(self):
        registry={}
        for candidate in self.f['candidates']:
            for source in candidate['sources'].values():
                registry[(source['documentId'],'sha256-'+source['bodySha256'])]={**source,
                    'documentVersion':'sha256-'+source['bodySha256'],'grantId':'grant','grantRevision':'1','recipients':['openai'],
                    'evidenceId':'different-passage','quote':'다른 인용'}
        pool=personal.compile_pool(self.f,self.row,self.calls,registry)
        for candidate in pool['candidates']:
            source=candidate['sources'][0];original=self.f['candidates'][int(candidate['issueId'][1:])]['sources']
            self.assertIn(source['evidenceId'],original)
            self.assertEqual(original[source['evidenceId']]['quote'],source['quote'])
            self.assertEqual('grant',source['grantId'])

    def test_sql_never_updates_publication_or_feedback_and_binds_original_sha(self):
        value=personal.sql(personal.compile_pool(self.f,self.row,self.calls,{}))
        self.assertIn('publicationPayloadSha256',value)
        self.assertIn('ON CONFLICT(id) DO NOTHING',value)
        self.assertNotIn('UPDATE ',value)
        self.assertNotIn('feedback',value)
