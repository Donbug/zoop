"""Scheduling, source clocks and safe authority composition; synthetic only."""
import copy,json,tempfile,unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import Mock,patch
import briefing_auto_chain as chain
import briefing_source_time as clock
import briefing_priority_generation as priority
from test_briefing_priority_generation import inputs,business_answer
from zoop_ai_service import grants


class ChainTests(unittest.TestCase):
    def cfg(self,path):return {'enabled':True,'autoChain':chain.VERSION,'priorityContract':priority.VERSION,'nativeCallLimit':6,'additiveGraphAllowed':True,'work':path,'authorizationRef':'synthetic','dsn':'synthetic'}
    def test_slots_cross_midnight_with_exact_original_cutoffs(self):
        day=datetime.fromisoformat('2026-11-04T09:02:00+09:00').date()
        am=chain.round_for(day,'morning');pm=chain.round_for(day,'evening')
        self.assertEqual('2026-11-03T17:30:00+09:00',am['windowFrom']);self.assertEqual(am['windowTo'],pm['windowFrom'])
        self.assertEqual('2026-11-04T17:30:00+09:00',pm['windowTo'])
    def test_new_schedule_preserves_old_slots_and_one_day_test_window(self):
        cfg={'schedule':{'effectiveFrom':'2026-11-05','morning':'08:30','evening':'17:30','testEveningAt':'2026-11-04T22:00:00+09:00'}}
        day=datetime.fromisoformat('2026-11-04T21:30:00+09:00').date()
        old=chain.round_for(day,'morning',cfg);test=chain.round_for(day,'evening',cfg)
        new=chain.round_for(day+timedelta(days=1),'morning',cfg)
        pm=chain.round_for(day+timedelta(days=1),'evening',cfg)
        self.assertEqual('2026-11-04T09:20:00+09:00',old['windowTo'])
        self.assertEqual('2026-11-04T22:00:00+09:00',test['windowTo'])
        self.assertEqual(test['windowTo'],new['windowFrom'])
        self.assertEqual('2026-11-05T08:30:00+09:00',new['windowTo'])
        self.assertEqual(new['windowTo'],pm['windowFrom'])
        self.assertEqual('2026-11-05T17:30:00+09:00',pm['windowTo'])
    def test_new_schedule_dispatch_uses_the_configured_preparation_time(self):
        with tempfile.TemporaryDirectory() as d:
            cfg={**self.cfg(d),'schedule':{'effectiveFrom':'2026-11-05','morning':'08:30','evening':'17:30'}}
            conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False)
            conn.execute.return_value.fetchone.return_value=None;run=Mock()
            now=lambda:datetime.fromisoformat('2026-11-05T08:12:00+09:00')
            self.assertTrue(chain.work_once(cfg,now=now,connect=lambda:conn,run=run))
            self.assertEqual('morning',run.call_args.args[1])
    def test_test_clock_requires_explicit_kst_offset(self):
        import briefing_schedule
        with self.assertRaises(ValueError):briefing_schedule.slot(datetime.fromisoformat('2026-11-04').date(),'evening',{'schedule':{'testEveningAt':'2026-11-04T22:00:00'}})
    def test_opt_in_and_native_capacity_cannot_be_inferred(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=self.cfg(d);chain.config_check(cfg)
            for key,value in [('enabled',False),('autoChain','legacy'),('priorityContract','old'),('nativeCallLimit',12),('additiveGraphAllowed',False)]:
                with self.assertRaises(ValueError):chain.config_check({**cfg,key:value})
    def test_source_day_does_not_become_a_publication_instant(self):
        f=inputs()[0];source=f['sources']['e0'];source.update(publishedAt=None,publishedDate='2026-10-22',availableAt='2026-10-22T08:05:00+09:00',eligibilityBasis='first_observed');f=priority.m.seal(f)
        frozen=priority.freeze([f],'common');priority.c.validate(business_answer(frozen,'common'),frozen,'common')
        projected=clock.projection(source);self.assertIsNone(projected['publishedAt']);self.assertEqual('2026-10-22',projected['publishedDate'])
        f['sources']['e0']['availableAt']='2027-01-01T00:00:00+09:00';f=priority.m.seal(f)
        with self.assertRaisesRegex(ValueError,'future_source'):priority.freeze([f],'common')
    def test_journal_never_copies_prompt_document_or_account_values(self):
        with tempfile.TemporaryDirectory() as d:
            j=chain.Journal(self.cfg(d),'r');j('native','started',{'graphVersion':'g','prompt':'private','memberId':'private'})
            value=json.loads((j.root/'native-started.json').read_text());self.assertEqual({'graphVersion':'g'},value['detail'])
            old=(j.root/'native-started.json').read_bytes();j('native','started',{'graphVersion':'other'});self.assertEqual(old,(j.root/'native-started.json').read_bytes())
    def test_delegate_grants_are_fresh_and_never_overwrite_another_owner(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'a';b=root/'b';index=root/'delegates'
            # Valid empty independent owner registries; duplicate/nested roots are refused.
            a.write_text(json.dumps({'schemaVersion':grants.SCHEMA,'grants':[]}));b.write_bytes(a.read_bytes())
            index.write_text(json.dumps({'schemaVersion':'zoop-grant-authority-delegates-1','delegates':[str(a),str(b)]}))
            self.assertEqual({},grants.load(index).grants)
            before=a.read_bytes();b.write_text(json.dumps({'schemaVersion':'zoop-grant-authority-delegates-1','delegates':[str(a)]}))
            with self.assertRaises(grants.GrantRegistryError):grants.load(index)
            self.assertEqual(before,a.read_bytes())
    def test_delegated_grant_revocation_is_immediate_and_duplicate_owners_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'a';b=root/'b';index=root/'delegates'
            grant={'grantId':'one','revision':'v1','sourceId':'source','enabled':True,'rights':'known',
                   'allowedOperations':sorted(grants.OPERATIONS),'recipients':['synthetic'],
                   'purposes':['briefing-outlook'],'evidence':['synthetic-only'],'expiresAt':None}
            a.write_text(json.dumps({'schemaVersion':grants.SCHEMA,'grants':[grant]}));b.write_text(json.dumps({'schemaVersion':grants.SCHEMA,'grants':[]}))
            index.write_text(json.dumps({'schemaVersion':'zoop-grant-authority-delegates-1','delegates':[str(a),str(b)]}))
            args={'source_id':'source','revision':'v1','purposes':['briefing-outlook'],'recipients':['synthetic']}
            self.assertIsNone(grants.evaluate(grants.load(index).current('one'),**args))
            grant['enabled']=False;a.write_text(json.dumps({'schemaVersion':grants.SCHEMA,'grants':[grant]}))
            self.assertEqual('source_rights_unknown_or_denied',grants.evaluate(grants.load(index).current('one'),**args))
            b.write_bytes(a.read_bytes())
            with self.assertRaisesRegex(grants.GrantRegistryError,'grant_authority_conflict'):grants.load(index)
    def test_new_auto_authority_keeps_the_old_runtime_grant_and_revocation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);old={**self.cfg(d),'authorityRoot':str(root/'old'),'originalSourceAuthority':'/synthetic/original'}
            chain.native.initialize_authority({k:v for k,v in old.items() if k!='autoChain'})
            original=root/'old/grants.json';before=original.read_bytes()
            new={**old,'authorityRoot':str(root/'new'),'originalReadGrants':str(original)}
            chain.native.initialize_authority(new)
            both=grants.load(root/'new/serving-grants.json')
            self.assertEqual({'briefing-kogl1-live','briefing-kogl1-auto-v1'},set(both.grants))
            self.assertEqual(before,original.read_bytes())
            original.write_text(original.read_text().replace('"enabled":true','"enabled":false'))
            self.assertFalse(grants.load(root/'new/serving-grants.json').current('briefing-kogl1-live')['enabled'])
    def test_interrupted_collection_has_a_failed_attempt_and_never_dispatches(self):
        with tempfile.TemporaryDirectory() as d:
            conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False);run=Mock()
            conn.execute.return_value.fetchone.side_effect=[{'status':'queued'},{'owned':True},None,None]
            now=lambda:datetime.fromisoformat('2026-11-04T09:21:00+09:00')
            with patch.object(chain.server,'published',return_value=False),patch.object(chain.server,'record_input_failure') as failure:
                self.assertFalse(chain.work_once(self.cfg(d),now=now,connect=lambda:conn,run=run))
                run.assert_not_called();failure.assert_called_once()
                self.assertEqual('collection',failure.call_args.kwargs['stage'])
                self.assertEqual('interrupted_slot_not_resent',failure.call_args.kwargs['reason'])
    def test_worker_does_not_start_before_collection_window(self):
        with tempfile.TemporaryDirectory() as d:
            conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False);run=Mock()
            now=lambda:datetime.fromisoformat('2026-11-04T08:59:59+09:00')
            self.assertFalse(chain.work_once(self.cfg(d),now=now,connect=lambda:conn,run=run));run.assert_not_called();conn.execute.assert_not_called()
    def test_completed_or_recovery_slot_is_not_automatically_resent(self):
        with tempfile.TemporaryDirectory() as d:
            conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False);run=Mock()
            conn.execute.return_value.fetchone.return_value={'status':'requires_recovery'}
            now=lambda:datetime.fromisoformat('2026-11-04T09:03:00+09:00')
            self.assertFalse(chain.work_once(self.cfg(d),now=now,connect=lambda:conn,run=run));run.assert_not_called()
    def test_early_lease_contention_does_not_turn_a_competitors_job_into_failure(self):
        with tempfile.TemporaryDirectory() as d:
            conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False);conn.execute.return_value.fetchone.return_value=None
            run=Mock(side_effect=ValueError('briefing_server_another_briefing_writer'));now=lambda:datetime.fromisoformat('2026-11-04T09:03:00+09:00')
            self.assertTrue(chain.work_once(self.cfg(d),now=now,connect=lambda:conn,run=run));self.assertEqual(1,conn.execute.call_count)
    def test_missed_collection_window_records_a_zero_call_failure_without_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False);run=Mock()
            conn.execute.return_value.fetchone.side_effect=[None,{'owned':True},{'id':'brf-2026-11-04-morning'}]
            now=lambda:datetime.fromisoformat('2026-11-04T09:11:00+09:00')
            with patch.object(chain.server,'record_input_failure') as failure:
                self.assertFalse(chain.work_once(self.cfg(d),now=now,connect=lambda:conn,run=run))
                run.assert_not_called();failure.assert_called_once()
                self.assertEqual('collection_window_missed',failure.call_args.kwargs['reason'])
            self.assertEqual('requires_recovery',json.loads((Path(d)/'chain/brf-2026-11-04-morning/slot-requires_recovery.json').read_text())['status'])
