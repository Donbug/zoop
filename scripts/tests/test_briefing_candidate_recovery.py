import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import briefing_native_intake as n


def entry(key):
    return ({'candidate':{'title':key},'nativeBodySha256':'a'*64,'nativeReceiptSha256':'b'*64,
             'inputPriority':{'version':n.INPUT_PRIORITY},'matchedCompanyIds':['company']},
            {'document':{'documentId':key,'documentVersion':'original'}},[],Path('/synthetic'))


class CandidateRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.cfg={'work':str(self.root),'sharePriorityAnalysis':True,'nativeCallLimit':8}
        self.round={'id':'brf-2026-11-05-morning'}

    def test_held_candidate_moves_to_next_without_relabelling_previous_verdict(self):
        seen=[]
        def process(cfg,round,selected,root):
            key=selected[1]['document']['documentId'];seen.append(key)
            if key=='first':
                n.write_once(root/'native.started.json',{'sent':True})
                result={'status':'withheld','reason':'no_verified_company_involvement'}
                n.write_once(root/'source-qualification.json',result)
                return result
            return {'root':str(root),'documentId':key,'status':'ready'}
        with patch.object(n,'prepare_candidate',side_effect=process):
            result=n.prepare_candidates(self.cfg,self.round,[entry('first'),entry('second')],self.root)
        self.assertEqual(['first','second'],seen);self.assertEqual('second',result['documentId'])
        saved=list(self.root.glob('candidates-v3/*/source-qualification.json'))
        self.assertEqual('withheld',json.loads(saved[0].read_bytes())['status'])
        self.assertIn(('first','original'),n.attempted_documents(self.root.parent))

    def test_unknown_transport_does_not_start_next_or_retry_started_document(self):
        def unknown(cfg,round,selected,root):
            n.write_once(root/'native.started.json',{'sent':True});raise TimeoutError('unknown')
        with patch.object(n,'prepare_candidate',side_effect=unknown) as run:
            with self.assertRaises(TimeoutError):n.prepare_candidates(self.cfg,self.round,[entry('first'),entry('second')],self.root)
            self.assertEqual(1,run.call_count)
        with patch.object(n,'prepare_candidate') as run:
            with self.assertRaisesRegex(ValueError,'interrupted_requires_recovery'):
                n.prepare_candidates(self.cfg,self.round,[entry('first'),entry('second')],self.root)
            run.assert_not_called()

    def test_shared_ceiling_is_checked_before_sending_an_unfinishable_document(self):
        budget=self.root/'budget';budget.mkdir()
        for i in range(4):(budget/(str(i)+'.json')).write_text(json.dumps({'roundId':self.round['id'],'phase':'native'}))
        with patch.object(n,'prepare_candidate') as run:
            result=n.prepare_candidates(self.cfg,self.round,[entry('first')],self.root)
            run.assert_not_called()
        self.assertEqual('remaining_shared_call_capacity',result['candidates'][0]['reason'])
        self.assertEqual('remaining_shared_call_capacity',result['reason'])

    def test_four_paid_calls_then_hold_can_reach_next_candidate_with_explicit_expansion(self):
        budget=self.root/'budget';budget.mkdir()
        for i in range(4):(budget/(str(i)+'.json')).write_text(json.dumps({'roundId':self.round['id'],'phase':'native'}))
        cfg={**self.cfg,'roundCallLimit':32,'nativeCallLimit':24}
        with patch.object(n,'prepare_candidate',return_value={'status':'ready','documentId':'next'}) as run:
            result=n.prepare_candidates(cfg,self.round,[entry('next')],self.root)
        self.assertEqual('next',result['documentId']);run.assert_called_once()
        self.assertEqual(4,len(list(budget.glob('*.json'))))

    def test_capacity_stop_records_each_unexamined_candidate_separately(self):
        budget=self.root/'budget';budget.mkdir()
        for i in range(4):(budget/(str(i)+'.json')).write_text(json.dumps({'roundId':self.round['id'],'phase':'native'}))
        with patch.object(n,'prepare_candidate') as run:
            result=n.prepare_candidates(self.cfg,self.round,[entry('next'),entry('third')],self.root)
        run.assert_not_called()
        self.assertEqual(['not_sent','not_sent'],[r['status']for r in result['candidates']])
        self.assertEqual('remaining_shared_call_capacity',result['reason'])

    def test_expanded_budget_still_retains_publication_capacity(self):
        budget=self.root/'budget';budget.mkdir()
        cfg={**self.cfg,'roundCallLimit':32,'nativeCallLimit':24}
        for i in range(20):(budget/(str(i)+'.json')).write_text(json.dumps({'roundId':self.round['id'],'phase':'native'}))
        with patch.object(n,'prepare_candidate') as run:
            result=n.prepare_candidates(cfg,self.round,[entry('next')],self.root)
        run.assert_not_called();self.assertEqual('remaining_shared_call_capacity',result['reason'])

    def test_existing_ready_result_is_reused_without_collection_or_new_provider(self):
        collection=self.root/'native'/self.round['id'];ready=collection/(self.round['id']+'-native-v2')/'ready.json';ready.parent.mkdir(parents=True)
        ready.write_text(json.dumps({'documentId':'saved','proof':'original'}))
        with patch.object(n,'collect') as collect,patch.object(n,'prepare_candidate') as model:
            self.assertEqual('saved',n.prepare(self.cfg,self.round)['documentId'])
            collect.assert_not_called();model.assert_not_called()

    def test_legacy_import_request_stays_identical_to_the_immutable_ready_record(self):
        ready={'documentId':'first','root':'synthetic-native-root','handoffReceipt':'synthetic-receipt'}
        with patch.object(n,'prepare_candidate',return_value=ready):
            result=n.prepare_candidates(self.cfg,self.round,[entry('first')],self.root)
        self.assertEqual(ready,result)
        self.assertNotIn('outcomeFile',result);self.assertNotIn('status',result)


if __name__=='__main__':unittest.main()
