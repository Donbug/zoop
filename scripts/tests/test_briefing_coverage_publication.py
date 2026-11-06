from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import briefing_coverage_publication as gap
import briefing_native_intake as native


class CoverageNoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.cfg={'work':str(self.root)}
        self.round={'id':'brf-2026-11-06-morning','date':'2026-11-06','edition':'morning',
                    'scheduledAt':'2026-11-06T08:30:00+09:00','windowFrom':'2026-11-05T17:30:00+09:00','windowTo':'2026-11-06T08:30:00+09:00'}
        self.source=self.root/'native'/self.round['id'];self.source.mkdir(parents=True)
        gap.write_once(self.source/'source-coverage.json',{'complete':False,'candidateDocuments':0})

    def test_notice_pins_existing_coverage_and_original_cutoff_without_a_model(self):
        now=datetime.fromisoformat('2026-11-06T08:13:30+09:00')
        sha=gap.record(self.cfg,self.round,'no_current_company_source',now)
        p=self.source/'coverage-notice.json';saved=p.read_bytes();value=json.loads(saved)
        self.assertEqual(gap.runtime.b.digest(saved),sha)
        self.assertEqual(self.round,value['round']);self.assertEqual(now.isoformat(),value['recordedAt'])
        self.assertEqual(gap.runtime.b.digest((self.source/'source-coverage.json').read_bytes()),value['files']['source-coverage.json'])
        self.assertEqual(sha,gap.record(self.cfg,self.round,'no_current_company_source',datetime.fromisoformat('2026-11-06T08:15:00+09:00')))
        self.assertEqual(saved,p.read_bytes())

    def test_a_late_observation_cannot_manufacture_a_historical_gap_notice(self):
        with self.assertRaisesRegex(ValueError,'coverage_notice_after_cutoff'):
            gap.record(self.cfg,self.round,'no_current_company_source',datetime.fromisoformat('2026-11-06T08:31:00+09:00'))
        self.assertFalse((self.source/'coverage-notice.json').exists())

    def test_unknown_send_or_provider_error_cannot_be_relabelled_as_a_quiet_round(self):
        for reason in ['unknown','timeout','native_s3_not_ready','interrupted_or_stage_failed']:
            with self.assertRaisesRegex(ValueError,'coverage_notice_reason'):
                gap.record(self.cfg,self.round,reason,datetime.fromisoformat('2026-11-06T08:13:00+09:00'))

    def test_completed_verdict_and_capacity_reasons_preserve_their_outcome_pin(self):
        gap.write_once(self.source/'candidate-outcomes-v3.json',{'reason':'remaining_shared_call_capacity','status':'withheld','candidates':[{'status':'not_sent'}]})
        gap.record(self.cfg,self.round,'remaining_shared_call_capacity',datetime.fromisoformat('2026-11-06T08:13:00+09:00'))
        saved=(self.source/'coverage-notice.json').read_bytes()
        (self.source/'candidate-outcomes-v3.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'coverage_notice_changed'):
            gap.record(self.cfg,self.round,'remaining_shared_call_capacity',datetime.fromisoformat('2026-11-06T08:14:00+09:00'))
        self.assertEqual(saved,(self.source/'coverage-notice.json').read_bytes())

    def test_market_capture_precedes_source_shortage_and_notice_does_not_activate_a_graph(self):
        clock=[datetime.fromisoformat('2026-11-06T08:10:00+09:00')];seen=[]
        cfg={**self.cfg,'dsn':'synthetic-only','schedule':{'effectiveFrom':'2026-11-05','morning':'08:30','evening':'17:30'}}
        conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False)
        def execute(sql,*args):
            result=Mock()
            if 'pg_try_advisory_lock' in sql:result.fetchone.return_value={'owned':True}
            elif 'WHERE id=' in sql:result.fetchone.return_value={'id':self.round['id']}
            else:result.fetchone.return_value=None
            return result
        conn.execute.side_effect=execute
        def source(*args,**kwargs):seen.append('source');raise ValueError('briefing_server_no_current_company_source')
        def capture(*args):seen.append('market')
        def produce(context,job):seen.append('publication');self.assertIn('coverageNoticeSha256',context);self.assertNotIn('expectedGraphVersion',context)
        def sleep(seconds):clock[0]=clock[0]+__import__('datetime').timedelta(seconds=seconds)
        with patch('psycopg.connect',return_value=conn),patch.object(native,'initialize_authority'),patch.object(native,'native_command',return_value={'baseline':'synthetic'}) as command,patch.object(native,'capture_market',side_effect=capture),patch.object(native,'prepare',side_effect=source),patch.object(native.server,'published',return_value=True):
            native.run_slot(cfg,'morning',producer=produce,now=lambda:clock[0],sleep=sleep)
        self.assertEqual(['market','source','publication'],seen)
        self.assertEqual(['state'],[c.args[1]for c in command.call_args_list])
        self.assertTrue((self.source/'coverage-notice.json').exists())

    def test_resumed_outcomes_are_pinned_without_overwriting_the_first_result(self):
        original=self.source/'candidate-outcomes-v3.json'
        gap.write_once(original,{'reason':'remaining_shared_call_capacity'})
        saved=original.read_bytes();name='candidates-v3/outcomes-'+'a'*16+'.json'
        (self.source/'candidates-v3').mkdir()
        gap.write_once(self.source/name,{'reason':'all_company_candidates_withheld'})
        gap.record(self.cfg,self.round,'all_company_candidates_withheld',datetime.fromisoformat('2026-11-06T08:13:00+09:00'),name)
        self.assertEqual(saved,original.read_bytes())
        self.assertIn(name,json.loads((self.source/'coverage-notice.json').read_bytes())['files'])
        with self.assertRaisesRegex(ValueError,'coverage_outcome_path'):
            gap.record(self.cfg,self.round,'all_company_candidates_withheld',datetime.fromisoformat('2026-11-06T08:14:00+09:00'),'../outside.json')
