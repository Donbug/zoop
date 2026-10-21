"""Immutable two-generation ancestry, before any paid execution (authored only)."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('continuation_runner',Path(__file__).parents[1]/'briefing_market_outlook_run.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class OutlookContinuationTest(unittest.TestCase):
    def chain(self,d):
        root=Path(d);r.base.private_dir(root/'market/outlook-history')
        first={'news':'unchanged','presentationEnrichment':{'receipts':[{'requestDigest':'first'}]}}
        raw=r.base.canonical(first);sha=r.base.digest(raw);r.base.write_once(root/'market/outlook-history'/ (sha+'.json'),raw)
        second={'news':'unchanged','presentationEnrichment':{'receipts':[{'requestDigest':'second'}],
            'outlookHistory':{'bundleSha256':sha,'receipts':first['presentationEnrichment']['receipts']}}}
        raw2=r.base.canonical(second);sha2=r.base.digest(raw2);r.base.write_once(root/'market/outlook-history'/ (sha2+'.json'),raw2)
        current={'news':'unchanged','presentationEnrichment':{'receipts':[{'requestDigest':'new'}],
            'outlookHistory':{'bundleSha256':sha2,'receipts':second['presentationEnrichment']['receipts']}}}
        return root,current,[sha2,sha]
    def test_two_layers_are_preserved_without_paid_transport(self):
        with tempfile.TemporaryDirectory() as d:
            root,current,expected=self.chain(d);before=copy.deepcopy(current)
            self.assertEqual(expected,r.history_chain(root,current));self.assertEqual(before,current)
    def test_deepest_changed_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root,current,expected=self.chain(d);(root/'market/outlook-history'/ (expected[1]+'.json')).write_text('{}')
            with self.assertRaisesRegex(r.context.ContextError,'bundle_digest'):r.history_chain(root,current)
    def test_receipt_omission_and_changed_news_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root,current,_=self.chain(d);current['presentationEnrichment']['outlookHistory']['receipts']=[]
            with self.assertRaisesRegex(r.context.ContextError,'receipt_ledger'):r.history_chain(root,current)
        with tempfile.TemporaryDirectory() as d:
            root,current,_=self.chain(d);current['news']='altered'
            with self.assertRaisesRegex(r.context.ContextError,'news_changed'):r.history_chain(root,current)
    def test_bounded_history_refuses_excess_depth(self):
        with tempfile.TemporaryDirectory() as d:
            root,current,_=self.chain(d)
            with self.assertRaisesRegex(r.context.ContextError,'cycle_or_depth'):r.history_chain(root,current,max_depth=1)

    def test_insufficient_approved_ceiling_rejects_execution_before_transport_or_output(self):
        plan = {'minimumTotalReservations':432,'maxCallsIncludingPrior':425,'priorReservations':424,'plannedNewCalls':8}
        prepared = (b'{}',{},[],[],{},[],{},plan)
        args = SimpleNamespace(execute_authorized_generation=True,max_calls=425)
        calls = []
        with patch.object(r,'prepare',return_value=prepared):
            with self.assertRaisesRegex(r.context.ContextError,'shared_budget_insufficient'):
                r.run(args,lambda request: calls.append(request))
        self.assertEqual([],calls)

if __name__=='__main__':unittest.main()
