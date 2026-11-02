"""Admission and save recovery exercise the real worker bridge without a provider or key."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import briefing_admin_reprocess as bridge
from briefing_usage import digest


class Pipe:
    def __init__(self): self.events = []
    def send(self, event):
        self.events.append(event)
        if event['op'] == 'claim':
            return {'ok': True, 'attemptId': 'attempt-test', 'ownerToken': 'owner-test',
                    'roundId': 'round-test', 'attemptNo': 1, 'status': 'running',
                    'reused': False, 'leaseUntil': '2026-12-01T00:00:00Z'}
        return {'ok': True, 'created': True}
    def close(self): pass


class AdminBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.pipe = Pipe()
        raw = json.dumps({'schemaVersion': 'briefing-recorded-result-v1', 'roundId': 'round-test',
                          'purpose': 'generation', 'outcome': 'available',
                          'result': {'verification': {'status': 'PASS'}}}).encode()
        (self.root / 'input.json').write_bytes(raw)
        self.spec = {'schemaVersion': 'briefing-recorded-producer-v1', 'operation': 'save_only_generation',
                     'round': {'id': 'round-test'}, 'requestKey': 'request-test', 'trigger': 'admin',
                     'adminId': 'admin-test', 'inputArtifactId': 'input-test', 'inputFile': 'input.json',
                     'inputSha256': digest(raw), 'maxCalls': 0, 'authorizationRef': 'synthetic-no-provider'}
        self.job = self.root / 'job.json'
    def run_job(self):
        self.job.write_text(json.dumps(self.spec))
        with patch.dict(os.environ, {'ZOOP_BRIEFING_LEDGER_COMMAND': '["not-executed"]'}, clear=True), \
             patch('briefing_usage_run.CommandPipe', return_value=self.pipe):
            return bridge.execute(self.job, self.root / 'output')
    def test_save_recovery_records_no_live_call_and_preserves_result(self):
        result = self.run_job()
        self.assertEqual('SAVED_ONLY', result['status']); self.assertEqual(0, result['newModelCalls'])
        ops = [e['op'] for e in self.pipe.events]
        self.assertNotIn('model_start', ops)
        reuse = next(e for e in self.pipe.events if e['op'] == 'local')
        self.assertEqual('save_only', reuse['mode'])
        self.assertTrue((self.root / 'output/result.json').is_file())
    def test_live_generation_without_operator_authorization_never_claims_or_sends(self):
        self.spec.update(operation='generation', maxCalls=2)
        with self.assertRaisesRegex(ValueError, 'live_reprocessing_not_authorized'): self.run_job()
        self.assertEqual([], self.pipe.events)
    def test_corrupted_pinned_input_never_claims_or_sends(self):
        (self.root / 'input.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'usage_job_input_digest'): self.run_job()
        self.assertEqual([], self.pipe.events)


if __name__ == '__main__': unittest.main()
