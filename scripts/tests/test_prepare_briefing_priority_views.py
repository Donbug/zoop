import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'prepare_briefing_priority_views.py'
spec = importlib.util.spec_from_file_location('priority_transfer', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PriorityTransferTest(unittest.TestCase):
    def payload(self):
        priority = json.loads((SCRIPT.parents[1] / 'api/src/test/resources/briefing/priority-authored.json').read_text())
        return {'id': priority['roundId'], 'date': '2026-10-15', 'edition': 'evening',
                'dataAsOf': priority['cutoff'], 'commonPriority': priority,
                'marketSummary': {'text': '[합성시험] 저장 요약', 'resultVersion': 'summary-v1',
                                  'evidenceIds': ['brf-test-evidence']},
                'providerResponse': 'not copied', 'memberId': 'not copied'}

    def test_only_display_fragment_is_prepared_and_no_publication_authority_is_created(self):
        payload = self.payload()
        before = copy.deepcopy(payload)
        result = module.prepare('common', payload, 'a' * 64)
        self.assertEqual(before, payload)
        self.assertFalse(result['publicationReady'])
        self.assertEqual({'commonPriority', 'prioritySummary'}, set(result['fragment']))
        self.assertNotIn('providerResponse', result['fragment'])
        self.assertNotIn('memberId', result['fragment'])

    def test_foreign_round_or_nested_provider_metadata_cannot_enter_a_display_fragment(self):
        payload = self.payload()
        payload['commonPriority']['roundId'] = 'other'
        with self.assertRaises(ValueError):
            module.prepare('common', payload, 'a' * 64)
        payload = self.payload()
        payload['commonPriority']['providerResponse'] = 'private'
        with self.assertRaises(ValueError):
            module.prepare('common', payload, 'a' * 64)

    def test_cli_preserves_source_rejects_bad_digest_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / 'completed.sqlite3'
            output = Path(temp) / 'fragments.jsonl'
            raw = json.dumps(self.payload(), ensure_ascii=False)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE round_results(scope,day,edition,payload,sha256)')
                db.execute('INSERT INTO round_results VALUES(?,?,?,?,?)', ('common', '2026-10-15', 'evening', raw, digest))
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            cmd = [sys.executable, str(SCRIPT), '--input-sqlite', str(database), '--output', str(output)]
            self.assertEqual(0, subprocess.run(cmd, capture_output=True).returncode)
            original = output.read_bytes()
            self.assertNotEqual(0, subprocess.run(cmd, capture_output=True).returncode)
            self.assertEqual(original, output.read_bytes())
            self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())
            with sqlite3.connect(database) as db:
                db.execute("UPDATE round_results SET sha256='invalid'")
            other = Path(temp) / 'invalid.jsonl'
            self.assertNotEqual(0, subprocess.run(cmd[:-1] + [str(other)], capture_output=True).returncode)
            self.assertFalse(other.exists())


if __name__ == '__main__':
    unittest.main()
