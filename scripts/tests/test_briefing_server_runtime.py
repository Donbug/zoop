import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from zoneinfo import ZoneInfo
import briefing_server_runtime as runtime

class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cfg={'work':self.temp.name};self.calls=[]
    def request(self,n=0,output=10):
        return json.dumps({'model':'gpt-6-luna','store':False,'instructions':'proof'+str(n),'max_output_tokens':output}).encode()
    def transport(self,raw):
        self.calls.append(raw)
        return 200,b'{"status":"completed","usage":{"input_tokens":2,"output_tokens":1}}'
    def test_round_cap_is_checked_before_seventeenth_provider_send(self):
        budget=runtime.Budget(self.cfg,'brf-2026-11-03-morning',lambda:None,self.transport)
        for i in range(16):budget(self.request(i))
        with self.assertRaisesRegex(ValueError,'round_budget'):budget(self.request(17))
        self.assertEqual(16,len(self.calls))
    def test_unknown_transmission_keeps_reservation_and_forbids_automatic_resend(self):
        def unknown(raw):self.calls.append(raw);raise TimeoutError()
        budget=runtime.Budget(self.cfg,'brf-2026-11-03-morning',lambda:None,unknown)
        with self.assertRaises(TimeoutError):budget(self.request())
        with self.assertRaisesRegex(ValueError,'uncertain_or_reused_request'):budget(self.request())
        self.assertEqual(1,len(self.calls))
        self.assertEqual(1,len(list((Path(self.temp.name)/'budget').glob('*.json'))))
    def test_cost_reservation_above_round_cap_does_not_send(self):
        budget=runtime.Budget(self.cfg,'brf-2026-11-03-morning',lambda:None,self.transport)
        with self.assertRaisesRegex(ValueError,'round_budget'):budget(self.request(output=1000000))
        self.assertFalse(self.calls)
    def test_daily_cap_is_execution_date_even_for_historical_rounds(self):
        root=Path(self.temp.name)/'budget';root.mkdir()
        day=str(runtime.datetime.now(runtime.KST).date())
        (root/'existing.json').write_text(json.dumps({'requestDigest':'old','roundId':'another-round','day':day,'reservedUpperUsd':'2'}))
        budget=runtime.Budget(self.cfg,'brf-2026-10-21-evening',lambda:None,self.transport)
        with self.assertRaisesRegex(ValueError,'daily_budget'):budget(self.request())
        self.assertFalse(self.calls)
    def test_tools_and_nonstandard_tiers_cannot_bypass_the_cost_basis(self):
        budget=runtime.Budget(self.cfg,'brf-2026-11-03-morning',lambda:None,self.transport)
        for extra in ({'tools':[{'type':'web_search'}]},{'service_tier':'priority'}):
            req=json.loads(self.request());req.update(extra)
            with self.assertRaisesRegex(ValueError,'model_policy'):budget(json.dumps(req).encode())
        self.assertFalse(self.calls)
    def test_revoked_authority_is_checked_before_reservation(self):
        def denied():raise ValueError('revoked')
        budget=runtime.Budget(self.cfg,'brf-2026-11-03-morning',denied,self.transport)
        with self.assertRaisesRegex(ValueError,'revoked'):budget(self.request())
        self.assertFalse((Path(self.temp.name)/'budget').exists())

class AdmissionTests(unittest.TestCase):
    def test_denied_budget_never_starts_an_ai_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            pipe=Mock();session=runtime.ServerUsageSession(pipe,{'purpose':'generation'},Path(temp)/'usage')
            session.budget=Mock();session.budget.reserve.side_effect=ValueError('round_budget')
            with self.assertRaisesRegex(ValueError,'round_budget'):session.invoke('analysis-verification',b'{}',Mock())
            pipe.send.assert_not_called()
    def test_ledger_stage_names_use_the_existing_identifier_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            session=runtime.ServerUsageSession(Mock(),{'purpose':'generation'},Path(temp)/'usage');session.budget=Mock()
            with patch.object(runtime.UsageSession,'invoke',return_value='recorded') as invoke:
                self.assertEqual('recorded',session.invoke('analysis-verification',b'{}',Mock()))
                self.assertEqual('analysis_verification',invoke.call_args.args[0])

class ScheduleTests(unittest.TestCase):
    class Connection:
        def __init__(self):self.rows=[]
        def execute(self,sql,args):self.rows.append(args)
    def test_before_morning_does_not_reserve_future_slot(self):
        db=self.Connection();runtime.enqueue(db,datetime(2026,11,3,9,19,59,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertEqual([],db.rows)
    def test_startup_after_evening_preserves_both_exact_windows(self):
        db=self.Connection();runtime.enqueue(db,datetime(2026,11,3,18,tzinfo=ZoneInfo('Asia/Seoul')))
        self.assertEqual(['morning','evening'],[r[2] for r in db.rows])
        self.assertEqual('2026-11-02T17:30:00+09:00',db.rows[0][4].isoformat())
        self.assertEqual('2026-11-03T09:20:00+09:00',db.rows[1][4].isoformat())
        self.assertEqual('2026-11-03T17:30:00+09:00',db.rows[1][3].isoformat())

if __name__=='__main__':unittest.main()
