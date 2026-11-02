import unittest
from datetime import UTC,datetime
from types import SimpleNamespace
from unittest.mock import Mock
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import briefing_common_schedule_worker as w
class CommonScheduleWorkerTests(unittest.TestCase):
 def job(self):return {'id':'brf-2026-10-30-morning','round_date':'2026-10-30','edition':'morning','scheduled_at':datetime(2026,10,30,0,20,tzinfo=UTC),'window_from':datetime(2026,10,29,8,30,tzinfo=UTC)}
 def test_exact_queue_basis_is_sent_without_a_shell(self):
  invoke=Mock(return_value=SimpleNamespace(returncode=0));cfg={'producerCommand':['/srv/zoop/produce','--round','{roundId}','--cutoff','{cutoff}']}
  w.run_producer(cfg,self.job(),invoke=invoke);args,kwargs=invoke.call_args;self.assertEqual('brf-2026-10-30-morning',args[0][2]);self.assertEqual('2026-10-30T00:20:00+00:00',args[0][4]);self.assertNotIn('shell',kwargs)
 def test_no_demo_or_missing_producer_can_be_called_a_server_worker(self):
  for cfg in ({},{'producerCommand':['python','scripts/briefing_local_run.py']},{'producerCommand':[]}):
   with self.assertRaises(ValueError):w.command_for(cfg,self.job())
 def test_unknown_or_failed_invocation_is_not_presented_as_a_publication(self):
  with self.assertRaises(ValueError):w.run_producer({'producerCommand':['test']},self.job(),invoke=Mock(return_value=SimpleNamespace(returncode=1)))
