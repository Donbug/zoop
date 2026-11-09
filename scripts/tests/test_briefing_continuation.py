"""Forward candidate continuation does not author verdicts, retry unknowns or erase old receipts."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import briefing_native_intake as native
import briefing_call_limits as limits
from test_briefing_candidate_recovery import entry


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.cfg={'work':str(self.root),'selectionContinuation':True,'sharePriorityAnalysis':True,'roundCallLimit':32,'nativeCallLimit':24}
        self.round={'id':'brf-2026-11-09-morning','windowTo':(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()}

    def reserve(self, number, finished=True, phase='native'):
        root=self.root/'budget'; root.mkdir(exist_ok=True); key=str(number)
        (root/(key+'.json')).write_text(json.dumps({'roundId':self.round['id'],'phase':phase,'requestDigest':key}))
        if finished:
            (root/'finished').mkdir(exist_ok=True); (root/'finished'/(key+'.json')).write_text('{}')

    def test_final_importance_rejection_reaches_next_native_article_and_preserves_first(self):
        examined=[]
        def process(cfg, round_, selected, root):
            key=selected[1]['document']['documentId']; examined.append(key)
            result={'status':'ready','documentId':key}
            native.write_once(root/'ready.json',result)
            return result
        def qualify(result, root):
            return {'status':'withheld','reason':'selection_no_fresh_priority_issue'} if result['documentId']=='first' else {'status':'ready'}
        with patch.object(native,'prepare_candidate',side_effect=process):
            result=native.prepare_candidates(self.cfg,self.round,[entry('first'),entry('second')],self.root,qualifier=qualify)
        self.assertEqual(['first','second'],examined); self.assertEqual('second',result['documentId'])
        old=next(p for p in self.root.glob('candidates-v3/*/ready.json') if json.loads(p.read_bytes())['documentId']=='first')
        self.assertEqual('ready',json.loads(old.read_bytes())['status'])
        proof=json.loads((self.root/result['outcomeFile']).read_bytes())
        self.assertEqual(['withheld','ready'],[x['status'] for x in proof['candidates']])

    def test_known_received_truncation_and_work_exhaustion_can_move_on_but_unknowns_cannot(self):
        for code in ('live_output_truncated','live_set_work_exhausted'):
            result={'state':'stopped','failure':{'code':code},'usage':{'providerCalls':1,'receivedCalls':1,'startedWithoutReceipt':0}}
            self.assertIsNotNone(native.received_failure(result,self.cfg,self.round['id']))
            result['usage']['startedWithoutReceipt']=1
            self.assertIsNone(native.received_failure(result,self.cfg,self.round['id']))
        other={'state':'stopped','failure':{'code':'live_transport_timeout'},'usage':{'providerCalls':1,'receivedCalls':1,'startedWithoutReceipt':0}}
        self.assertIsNone(native.received_failure(other,self.cfg,self.round['id']))
        self.reserve(1,finished=False)
        result={'state':'stopped','failure':{'code':'live_output_truncated'},'usage':{'providerCalls':1,'receivedCalls':1,'startedWithoutReceipt':0}}
        with self.assertRaisesRegex(ValueError,'unsettled_call_requires_reconciliation'): native.received_failure(result,self.cfg,self.round['id'])

    def test_internal_document_and_stage_ceilings_follow_remaining_shared_capacity(self):
        calls, stages=limits.document_work(self.cfg,self.round['id'],documents_left=2)
        self.assertEqual(11,calls); self.assertGreater(stages['verify-relation'],4)
        self.assertEqual(20,limits.document_work(self.cfg,self.round['id'])[0])
        for i in range(15): self.reserve(i)
        calls,stages=limits.document_work(self.cfg,self.round['id'])
        self.assertEqual(5,calls); self.assertEqual(5,stages['verify-impact'])
        self.reserve(15)
        with self.assertRaisesRegex(ValueError,'remaining_shared_call_capacity'): limits.document_work(self.cfg,self.round['id'])
        self.assertEqual(16,len(list((self.root/'budget').glob('*.json'))))

    def test_s3_received_receipts_support_capacity_classification_without_s2_aggregate(self):
        result={'state':'stopped','failure':{'code':'live_set_work_exhausted'},
                'usage':{'providerCalls':5,'startedWithoutReceipt':0},
                'calls':[{'state':'received','responseDigest':str(i)*64} for i in range(5)]
                        +[{'state':'refused','responseDigest':None,'verdict':'live_set_work_exhausted'}]}
        self.assertEqual('native_document_capacity',native.received_failure(result,self.cfg,self.round['id']))
        result['calls'][0]['state']='started'
        self.assertIsNone(native.received_failure(result,self.cfg,self.round['id']))

    def test_long_first_document_and_rejected_selection_still_leave_a_normal_next_document(self):
        allowance,_=limits.document_work(self.cfg,self.round['id'],documents_left=2)
        for i in range(allowance):self.reserve(i)
        for i in range(allowance,allowance+4):self.reserve(i,phase='briefing')
        self.assertEqual(5,limits.document_work(self.cfg,self.round['id'])[0])
        self.assertEqual(allowance+4,len(list((self.root/'budget').glob('*.json'))))

    def test_deadline_marks_each_unexamined_source_without_provider_calls(self):
        round_={**self.round,'windowTo':(datetime.now(timezone.utc)+timedelta(seconds=199)).isoformat()}
        with patch.object(native,'prepare_candidate') as provider:
            result=native.prepare_candidates(self.cfg,round_,[entry('first'),entry('second')],self.root)
        provider.assert_not_called(); self.assertEqual('preparation_deadline',result['reason'])
        self.assertEqual(['not_sent','not_sent'],[x['status'] for x in result['candidates']])

    def test_continuation_configuration_never_silently_raises_a_previously_approved_cap(self):
        limits.validate_auto(self.cfg)
        with self.assertRaisesRegex(ValueError,'selection_continuation_capacity'):
            limits.validate_auto({**self.cfg,'roundCallLimit':16,'nativeCallLimit':8})
        self.assertEqual(16,limits.environment_limit({}))

    def test_saved_withheld_preserves_reason_and_never_resends_the_document(self):
        def hold(cfg,round_,selected,root):
            native.write_once(root/'native.started.json',{'sent':True})
            result={'status':'withheld','reason':'no_verified_company_involvement'}
            native.write_once(root/'source-qualification.json',result)
            return result
        with patch.object(native,'prepare_candidate',side_effect=hold):
            native.prepare_candidates(self.cfg,self.round,[entry('first')],self.root)
        with patch.object(native,'prepare_candidate') as sender:
            result=native.prepare_candidates(self.cfg,self.round,[entry('first')],self.root)
        sender.assert_not_called()
        self.assertEqual('saved_withheld',result['candidates'][0]['status'])
        self.assertEqual('no_verified_company_involvement',result['candidates'][0]['reason'])


if __name__=='__main__': unittest.main()
