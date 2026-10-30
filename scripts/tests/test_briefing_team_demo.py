import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import briefing_team_demo as demo


class TeamDemoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'demo'
        shutil.copytree(demo.DATA, self.root)
        self.addCleanup(self.temp.cleanup)

    def change(self, path, value):
        raw = demo.canonical(value)
        (self.root / path).write_bytes(raw)
        index = json.loads((self.root / 'index.json').read_bytes())
        item = next(i for i in index['files'] if i['path'] == path)
        item.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        (self.root / 'index.json').write_bytes(demo.canonical(index))

    def test_recorded_three_rounds_have_intact_hashes_and_no_account_tables(self):
        index, files = demo.validate(self.root)
        self.assertEqual([0, 2, 3], [r['coreItems'] for r in index['expected']])
        self.assertEqual(set(demo.TABLES), set(index['tables']))
        self.assertEqual(0, index['newAiCalls'])
        self.assertTrue(all(not p.startswith(('accounts/', 'sessions/')) for p in files))
        self.assertEqual(3, sum(p.startswith('artifacts/') for p in files))

    def test_changed_publication_and_graph_bytes_fail_closed(self):
        for name in ('tables/briefing_rounds.json', 'artifacts/briefing_graphs'):
            path = self.root / name
            if path.is_dir():
                path = next(path.glob('*.json'))
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.assertRaisesRegex(demo.DemoError, 'file_changed'):
                demo.validate(self.root)
            path.write_bytes(original)

    def test_permission_cannot_be_replaced_by_only_refreshing_file_hash(self):
        grants = json.loads((self.root / 'grants.json').read_bytes())
        grants['scope'] = 'production'
        self.change('grants.json', grants)
        with self.assertRaisesRegex(demo.DemoError, 'authority_changed'):
            demo.validate(self.root)

    def test_arbitrary_tables_and_production_rows_rejected(self):
        original = (self.root / 'index.json').read_bytes()
        index = json.loads(original)
        index['tables']['member_sessions'] = 1
        (self.root / 'index.json').write_bytes(demo.canonical(index))
        with self.assertRaisesRegex(demo.DemoError, 'invalid_demo_scope'):
            demo.validate(self.root)
        (self.root / 'index.json').write_bytes(original)
        rows = json.loads((self.root / 'tables/briefing_rounds.json').read_bytes())
        rows[0]['public_snapshot']['replay']['operationalCollectionGate'] = True
        self.change('tables/briefing_rounds.json', rows)
        with self.assertRaisesRegex(demo.DemoError, 'only_completed_local'):
            demo.validate(self.root)

    def test_parent_path_and_symlink_rejected(self):
        with self.assertRaisesRegex(demo.DemoError, 'invalid_data_path'):
            demo.safe_file(self.root, '../index.json')
        try:
            (self.root / 'alias.json').symlink_to(self.root / 'index.json')
        except OSError:
            self.skipTest('symlinks unavailable')
        with self.assertRaisesRegex(demo.DemoError, 'symlink'):
            demo.safe_file(self.root, 'alias.json')

    def test_json_is_not_sql_and_existing_data_is_not_overwritten(self):
        _, files = demo.validate(self.root)
        malicious = "'; DROP TABLE members; --"
        changed = dict(files)
        row = json.loads(changed['tables/articles.json'])
        row[0]['provider'] = malicious
        changed['tables/articles.json'] = demo.canonical(row)
        sql = demo.seed_sql(changed)
        self.assertIn("''; DROP TABLE members; --", sql)
        self.assertIn('demo_requires_empty_database', sql)
        self.assertIn('stored_payload_changed', sql)
        self.assertNotIn('ON CONFLICT', sql)
        self.assertNotIn('TRUNCATE', sql)

    def test_provider_and_existing_database_environment_not_inherited(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'authored-secret', 'DART_API_KEY': 'authored-secret',
                                     'DB_URL': 'production', 'JAVA_TOOL_OPTIONS': '-Dunsafe=true'}):
            env = demo.clean_environment()
        self.assertFalse(set(env) & {'OPENAI_API_KEY', 'DART_API_KEY', 'DB_URL', 'JAVA_TOOL_OPTIONS'})

    def test_exact_recorded_response_comparison_detects_stale_or_changed_results(self):
        payload = {'status': 'published', 'items': []}
        expected = {'expected': [{'date': '2026-10-21', 'edition': 'evening', 'coreItems': 0,
                                  'path': '/api/v1/briefings?date=2026-10-21&edition=evening',
                                  'responseSha256': demo.digest(demo.canonical(payload)), 'relatedResponses': {}}]}
        with patch.object(demo, 'get', return_value=payload):
            self.assertEqual(1, len(demo.verify('http://127.0.0.1:8080', expected)))
        with patch.object(demo, 'get', return_value={'status': 'published', 'items': [{'wrong': True}]}):
            with self.assertRaisesRegex(demo.DemoError, 'recorded_response_changed'):
                demo.verify('http://127.0.0.1:8080', expected)

    def test_additive_feedback_version_is_bound_to_recorded_publication_without_changing_original_digest(self):
        payload = {'id': 'round', 'status': 'published', 'graphVersion': None, 'items': []}
        path = '/api/v1/briefings?date=2026-10-21&edition=evening'
        index = {'expected': [{'date': '2026-10-21', 'edition': 'evening', 'coreItems': 0,
                              'path': path, 'responseSha256': demo.response_digest(payload), 'relatedResponses': {}}]}
        files = {'tables/briefing_rounds.json': demo.canonical([
            {'id': 'round', 'graph_version_id': None, 'payload_sha256': 'a' * 64}])}
        response = {**payload, 'feedbackVersion': 'publication:' + 'a' * 64}
        with patch.object(demo, 'get', return_value=response):
            self.assertEqual(1, len(demo.verify('http://127.0.0.1:8080', index, files)))
            with self.assertRaisesRegex(demo.DemoError, 'feedback_version_changed'):
                demo.verify('http://127.0.0.1:8080', index)  # never blindly discard an unbound version
        for changed in ({**response, 'feedbackVersion': 'publication:' + 'b' * 64},
                        {**response, 'feedbackVersion': None},
                        {**response, 'id': 'different-round'},
                        {**response, 'items': [{'changed': True}]}):
            with patch.object(demo, 'get', return_value=changed):
                with self.assertRaises(demo.DemoError):
                    demo.verify('http://127.0.0.1:8080', index, files)
        self.assertNotEqual(demo.response_digest(payload), demo.response_digest(response))

    def test_default_frontend_run_binds_feedback_versions_on_both_api_and_proxy(self):
        # Exercise run(), not only verify(): both default startup checks must receive the publication files.
        jar = Path(self.temp.name) / 'api.jar'
        jar.write_bytes(b'authored dummy jar; never executed')
        args = demo.parser().parse_args(['--data', str(self.root), '--jar', str(jar), '--once'])
        index, files = demo.validate(self.root)
        seen = []
        def checked(api, actual_index, actual_files=None):
            self.assertEqual(index, actual_index)
            self.assertEqual(files, actual_files)
            seen.append(api)
            return []
        process = MagicMock()
        process.poll.return_value = None
        done = SimpleNamespace(returncode=0, stdout='127.0.0.1:55432')
        with patch.object(demo, 'free_port', side_effect=[18080, 13080]), \
             patch.object(demo, 'java_command', return_value='java'), \
             patch.object(demo.shutil, 'which', return_value='node'), \
             patch.object(demo.Path, 'is_file', return_value=True), \
             patch.object(demo.subprocess, 'run', return_value=done), \
             patch.object(demo.subprocess, 'Popen', return_value=process), \
             patch.object(demo, 'get', return_value={}), \
             patch.object(demo, 'verify', side_effect=checked), \
             patch.object(demo, 'cleanup_owned_container'):
            self.assertEqual('READY', demo.run(args)['status'])
        self.assertEqual(['http://127.0.0.1:18080', 'http://127.0.0.1:13080'], seen)

    def test_check_mode_needs_no_tools_or_network(self):
        args = demo.parser().parse_args(['--data', str(self.root), '--check'])
        with patch.object(demo.subprocess, 'run', side_effect=AssertionError('process executed')):
            with patch.object(demo, 'get', side_effect=AssertionError('network used')):
                self.assertEqual('CHECKED', demo.run(args)['status'])

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(demo.DemoError, 'duplicate_json_key'):
            demo.load('{"scope":"production","scope":"recorded_read_projection"}')

    def test_only_request_trace_is_excluded_from_response_comparison(self):
        original = {'metadata': {'requestId': 'request-one', 'dataAsOf': '2026-10-22T08:30:00Z'}, 'items': []}
        another = {'metadata': {'requestId': 'request-two', 'dataAsOf': '2026-10-22T08:30:00Z'}, 'items': []}
        self.assertEqual(demo.response_digest(original), demo.response_digest(another))
        another['metadata']['dataAsOf'] = '2026-10-23T08:30:00Z'
        self.assertNotEqual(demo.response_digest(original), demo.response_digest(another))


if __name__ == '__main__':
    unittest.main()
