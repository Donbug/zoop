"""The actual collector/native boundary with recorded response peers; no model keys."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock,patch
import briefing_native_intake as native
import briefing_news_refill as refill
from test_briefing_candidate_recovery import entry


class RefillFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.collection=self.root/'native/brf-2026-11-09-morning'
        self.cfg={'work':str(self.root),'roundCallLimit':32,'nativeCallLimit':24,'sharePriorityAnalysis':True,
                  'selectionContinuation':True,'newsCollectionPolicy':{'version':refill.VERSION,**refill.DEFAULTS,'targetDocuments':1}}
        self.round={'id':'brf-2026-11-09-morning','windowTo':'2099-11-09T08:30:00+09:00'}

    def result(self,number,entries,can_refill):
        return entries,{'complete':False,'candidateDocuments':len(entries),'selectedDocuments':min(1,len(entries))}, {'canRefill':can_refill,'passCount':number}

    def test_final_rejection_requests_a_new_acquisition_pass_and_preserves_closed_attempts(self):
        seen=[]
        def process(cfg,round_,selected,root):
            key=selected[1]['document']['documentId'];seen.append(key)
            native.write_once(root/'native.started.json',{'fixtureSent':True})
            return {'status':'ready','documentId':key}
        def qualifier(result,root):
            return {'status':'withheld','reason':'selection_no_fresh_priority_issue'} if result['documentId']=='old' else {'status':'ready'}
        with patch.object(native,'collect',side_effect=[self.result(1,[entry('old')],True),self.result(2,[entry('new')],False)]) as gather, \
                patch.object(native,'prepare_candidate',side_effect=process):
            result=native.prepare_with_refill(self.cfg,self.round,self.collection,Mock(),qualifier)
        self.assertEqual('new',result['documentId']);self.assertEqual(['old','new'],seen)
        self.assertTrue(gather.call_args_list[1].kwargs['refill'])
        self.assertEqual(2,json.loads((self.collection/'source-coverage.json').read_bytes())['candidateDocuments'])
        self.assertEqual('withheld',json.loads((self.collection/'candidate-outcomes-v3.json').read_bytes())['status'])

    def test_initial_pool_is_filled_before_any_paid_analysis(self):
        self.cfg['newsCollectionPolicy']['targetDocuments']=2;sequence=[]
        values=[self.result(1,[entry('one')],True),self.result(2,[entry('one'),entry('two')],False)]
        def collect(*args,**kwargs):sequence.append('collect');return values.pop(0)
        def analyze(*args,**kwargs):sequence.append('native');return {'documentId':'one'}
        with patch.object(native,'collect',side_effect=collect),patch.object(native,'prepare_candidates',side_effect=analyze):
            result=native.prepare_with_refill(self.cfg,self.round,self.collection,Mock(),None)
        self.assertEqual(['collect','collect','native'],sequence);self.assertEqual('one',result['documentId'])

    def test_unknown_response_stops_before_refill_and_does_not_manufacture_a_coverage_notice(self):
        with patch.object(native,'collect',return_value=self.result(1,[entry('one')],True)) as collect, \
                patch.object(native,'prepare_candidates',side_effect=TimeoutError('unknown fixture response')):
            with self.assertRaises(TimeoutError):native.prepare_with_refill(self.cfg,self.round,self.collection,Mock(),None)
        self.assertEqual(1,collect.call_count);self.assertFalse((self.collection/'source-coverage.json').exists())

    def test_analysis_capacity_stop_never_triggers_wasteful_extra_collection(self):
        held={'status':'withheld','reason':'remaining_shared_call_capacity','candidates':[{'documentId':'one','status':'not_sent','reason':'remaining_shared_call_capacity'}]}
        with patch.object(native,'collect',return_value=self.result(1,[entry('one')],True)) as collect, \
                patch.object(native,'prepare_candidates',return_value=held):
            result=native.prepare_with_refill(self.cfg,self.round,self.collection,Mock(),None)
        self.assertEqual(1,collect.call_count);self.assertEqual('remaining_shared_call_capacity',result['reason'])


if __name__=='__main__':unittest.main()
