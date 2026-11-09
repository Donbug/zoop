"""Synthetic providers only: preview -> checked selection -> exact cached publication input."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import briefing_selection_gate as gate
import briefing_server_runtime as runtime
from briefing_usage import recorded
from test_briefing_issue_intelligence import candidate
from test_briefing_priority_generation import Transport


class Session:
    def __init__(self, *args, **kwargs):
        self.terminal = False
        self.replays = []
        self.unit = None
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def invoke(self, stage, raw, transport): return self.budget(raw)
    def replay(self, stage, key): self.replays.append(key)


class SelectionGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        cutoff = datetime.now(timezone.utc) + timedelta(minutes=10)
        self.round = {'id': 'brf-'+str(cutoff.date())+'-morning', 'date': str(cutoff.date()),
                      'edition': 'morning', 'windowFrom': (cutoff-timedelta(days=1)).isoformat(),
                      'windowTo': cutoff.isoformat(), 'scheduledAt': cutoff.isoformat()}
        self.root = self.work/'native'/self.round['id']/'candidates-v3'/'synthetic-native-v2'
        self.cfg = {'work': str(self.work), 'roundCallLimit': 32, 'nativeCallLimit': 24,
                    'sharePriorityAnalysis': True, 'selectionContinuation': True,
                    'ledgerCommand': ['never-run'], 'keyFile': '/never-read'}
        self.prepared = {'round': self.round, 'candidates': [candidate(0)], 'previous': {},
                         'graphVersion': 'synthetic-published-graph', 'inputSha256': 'a'*64,
                         'selectionPreview': True}

    def qualify(self, transport):
        with patch.object(runtime, 'java', side_effect=lambda cfg,op,*args: copy.deepcopy(self.prepared) if op=='prepare-selection' else {'status':'current'}), \
                patch.object(runtime, 'ServerUsageSession', Session), patch.object(gate, 'CommandPipe'), \
                patch.object(runtime.b, 'authenticated_transport', return_value=transport):
            return gate.qualify(self.cfg, self.round, self.root, self.prepared['graphVersion'])

    def test_completed_selection_is_reused_at_publication_with_no_second_physical_call(self):
        transport = Transport(); result = self.qualify(transport)
        self.assertEqual('ready', result['status']); self.assertEqual(2, len(transport.requests))
        original = (self.root/'selection/prepared.json').read_bytes()
        later = {**self.round, **{k: datetime.fromisoformat(self.round[k]).astimezone(timezone(timedelta(hours=9))).isoformat()
                                 for k in ('scheduledAt','windowFrom','windowTo')}}
        with patch.object(runtime, 'java', return_value={'status':'current'}), \
                patch.object(runtime.b, 'authenticated_transport', side_effect=AssertionError('saved qualification read a key')):
            repeated = gate.qualify(self.cfg, later, self.root, self.prepared['graphVersion'])
            root, prepared = gate.prepared_for_publication({**self.cfg,'qualifiedProducerWork':result['producerWork']}, later)
        self.assertEqual(result, repeated)
        client = runtime.RecordedClient(root/'model', Mock(side_effect=AssertionError('duplicate physical call')), 16, prompt_root=gate.intelligence.PROMPTS)
        session = Session()
        with recorded(client, session): gate.intelligence.assess_candidates(client, runtime.frozen_input(prepared))
        self.assertEqual(2, len(session.replays)); self.assertEqual(2, len(transport.requests))
        self.assertEqual(original, (root/'prepared.json').read_bytes())
        gate.check_replayed_selection(root,{'selected':[{'issueId':'i0'}]})
        with self.assertRaisesRegex(ValueError,'qualified_selection_changed'):
            gate.check_replayed_selection(root,{'selected':[]})

    def test_repeat_and_unimportant_candidates_remain_rejected_without_threshold_relaxation(self):
        def reject(request, answer):
            if request['text']['format']['name']=='selection':
                answer['assessments']['i0'].update(businessImportance=0, informationChange='repeat')
        result = self.qualify(Transport(reject))
        self.assertEqual('withheld', result['status'])
        proof = json.loads((self.root/'selection/qualification.json').read_bytes())
        self.assertFalse(proof['selectedIssueIds']); self.assertTrue(proof['rejected'])
        self.assertEqual(0, proof['attempts'][0]['draft']['assessments']['i0']['businessImportance'])

    def test_changed_input_wrong_slot_and_outside_work_cannot_reuse_a_qualification(self):
        result = self.qualify(Transport()); cfg = {**self.cfg,'qualifiedProducerWork':result['producerWork']}
        wrong = {**self.round,'edition':'evening'}
        with patch.object(runtime, 'java') as check:
            with self.assertRaisesRegex(ValueError,'qualified_input_changed'): gate.prepared_for_publication(cfg, wrong)
            check.assert_not_called()
            with self.assertRaisesRegex(ValueError,'qualified_work_path'):
                gate.prepared_for_publication({**cfg,'qualifiedProducerWork':str(self.work)}, self.round)
            path = self.root/'selection/prepared.json'; raw = json.loads(path.read_bytes()); raw['inputSha256']='b'*64; path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError,'qualified_input_changed'): gate.prepared_for_publication(cfg, self.round)

    def test_empty_reader_input_never_opens_a_provider_or_ledger(self):
        self.prepared['candidates'] = []
        with patch.object(runtime,'java',return_value=self.prepared), patch.object(gate,'CommandPipe') as ledger, \
                patch.object(runtime.b,'authenticated_transport') as transport:
            result=gate.qualify(self.cfg,self.round,self.root,self.prepared['graphVersion'])
        self.assertEqual('withheld',result['status']); ledger.assert_not_called(); transport.assert_not_called()

    def test_selection_send_is_refused_before_cutoff_without_fabricating_a_backdated_decision(self):
        round_={**self.round,'windowTo':(datetime.now(timezone.utc)+timedelta(seconds=180)).isoformat()}
        with patch.object(runtime,'java') as reader, self.assertRaisesRegex(ValueError,'selection_dispatch_deadline'):
            gate.qualify(self.cfg,round_,self.root,self.prepared['graphVersion'])
        reader.assert_not_called()


if __name__=='__main__': unittest.main()
