"""Finished-publication replay and real HTTP feedback persistence (no providers)."""
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import briefing_playback as playback
from briefing_preview_feedback import ENDPOINT


class PlaybackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / 'feedback.sqlite3'
        self.catalog = playback.load_catalog()
        self.server = playback.make_server(self.catalog, self.state, 0, 13196)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = None
        response = self.catalog['2026-10-23-morning.json']['response']
        self.target = {'roundId': response['id'],
                       'resultVersion': response['issueIntelligence']['resultVersion'],
                       'feature': 'briefing_round', 'targetId': response['id']}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, value=None, csrf=None, origin='http://127.0.0.1:13196'):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'Origin': origin}
        if self.cookie:
            headers['Cookie'] = self.cookie
        if csrf:
            headers['X-Preview-CSRF-Token'] = csrf
        raw = None
        if value is not None:
            headers['Content-Type'] = 'application/json'
            raw = json.dumps(value).encode()
        connection.request(method, path, raw, headers)
        response = connection.getresponse()
        cookie = response.getheader('Set-Cookie')
        if cookie:
            self.cookie = cookie.split(';')[0]
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def read_vote(self, target=None):
        from urllib.parse import urlencode
        return self.request('GET', ENDPOINT + '?' + urlencode(target or self.target))

    def test_four_rounds_and_every_detail_are_exact_projections(self):
        status, history = self.request('GET', '/api/v1/briefings/rounds')
        self.assertEqual(status, 200)
        self.assertEqual(len(history['items']), 4)
        self.assertIsNone(history['nextCursor'])
        self.assertEqual(self.request('GET', '/api/v1/auth/session')[1],
                         {'authenticated': False, 'kind': 'anonymous', 'user': None,
                          'setup': None, 'csrfToken': None, 'expiresAt': None})
        for pack in self.catalog.values():
            r = pack['response']
            status, actual = self.request('GET', f"/api/v1/briefings?date={r['date']}&edition={r['edition']}")
            self.assertEqual((status, actual), (200, r))
            for event, detail in pack['details'].items():
                status, actual = self.request('GET', f"/api/v1/briefings/{r['id']}/items/{event}")
                self.assertEqual((status, actual), (200, detail))
        status, _ = self.request('GET', '/api/v1/briefings?date=2026-10-21&edition=morning')
        self.assertEqual(status, 404)
        self.assertEqual(self.request('GET', '/api/v1/feedback')[0], 404)
        self.assertEqual(self.request('GET', '/api/v1/briefings?edition=morning&edition=evening')[0], 422)

    def test_feedback_round_issue_reason_cancel_and_reopen(self):
        self.assertEqual(self.read_vote()[1]['value'], 'none')
        csrf = self.read_vote()[1]['csrfToken']
        for value, reason in [('up', None), ('down', '판단 조건이 더 필요해요'), ('none', None)]:
            vote = {**self.target, 'value': value, 'reason': reason}
            for _ in range(2):  # Same final state creates one rating, including retries.
                self.assertEqual(self.request('PUT', ENDPOINT, vote, csrf)[0], 200)
            self.assertEqual(self.read_vote()[1]['value'], value)
        event = next(iter(self.catalog['2026-10-23-morning.json']['details']))
        issue = {**self.target, 'feature': 'briefing_issue',
                 'targetId': self.target['roundId'] + '/' + event}
        self.assertEqual(self.request('PUT', ENDPOINT, {**issue, 'value': 'down', 'reason': '근거 확인'}, csrf)[0], 200)
        # Reopen the actual SQLite store using a new server/store instance.
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.server = playback.make_server(self.catalog, self.state, 0, 13196)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.assertEqual(self.read_vote(issue)[1]['reason'], '근거 확인')
        with sqlite3.connect(self.state) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ratings').fetchone()[0], 2)
        self.cookie = None
        self.assertEqual(self.read_vote(issue)[1]['value'], 'none')  # Another browser.

    def test_failed_save_keeps_confirmed_vote_and_can_retry(self):
        csrf = self.read_vote()[1]['csrfToken']
        up = {**self.target, 'value': 'up', 'reason': None}
        down = {**self.target, 'value': 'down', 'reason': '확인 필요'}
        self.assertEqual(self.request('PUT', ENDPOINT, up, csrf)[0], 200)
        with patch.object(self.server.RequestHandlerClass.feedback_store, 'write',
                          side_effect=sqlite3.OperationalError('test unavailable')):
            self.assertEqual(self.request('PUT', ENDPOINT, down, csrf)[0], 503)
        self.assertEqual(self.read_vote()[1]['value'], 'up')
        self.assertEqual(self.request('PUT', ENDPOINT, down, csrf)[0], 200)
        self.assertEqual(self.read_vote()[1]['value'], 'down')

    def test_feedback_rejects_cross_origin_csrf_stale_and_wrong_target(self):
        csrf = self.read_vote()[1]['csrfToken']
        vote = {**self.target, 'value': 'up', 'reason': None}
        self.assertEqual(self.request('PUT', ENDPOINT, vote, csrf, 'https://unrelated.example')[0], 403)
        self.assertEqual(self.request('PUT', ENDPOINT, vote)[0], 403)
        self.assertEqual(self.request('PUT', ENDPOINT, {**vote, 'resultVersion': 'stale'}, csrf)[0], 409)
        self.assertEqual(self.request('PUT', ENDPOINT, {**vote, 'targetId': 'another-round'}, csrf)[0], 404)
        self.assertEqual(self.read_vote()[1]['value'], 'none')

    def test_integrity_and_no_generation_inputs(self):
        root = Path(self.temp.name) / 'data'
        shutil.copytree(playback.DATA, root)
        path = root / '2026-10-23-morning.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            playback.load_catalog(root)
        with self.assertRaisesRegex(ValueError, 'generation_or_private'):
            playback.check_projection({'nested': [{'fullBody': 'article input'}]})
        for key in ('generationRequestDigest', 'verificationRequestDigest', 'inputSha256',
                    'promptVersion', 'context', 'preservedPublication'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'generation_or_private'):
                playback.check_projection({'nested': [{key: 'not display data'}]})
        with self.assertRaisesRegex(ValueError, 'generation_or_private'):
            playback.check_projection({'bodyContext': {'text': 'article surroundings'}})
        for pack in self.catalog.values():
            playback.check_projection(pack)
            raw = json.dumps(pack, ensure_ascii=False)
            self.assertNotIn('/Users/', raw)
            self.assertNotIn('sk-proj-', raw)

    def test_runner_overrides_stale_frontend_environment(self):
        env = playback.frontend_environment({'PATH': '/bin', 'VITE_API_BASE_URL': 'https://old.example',
                                            'VITE_BRIEFING_PREVIEW_FEEDBACK': 'false',
                                            'ZOOP_DEV_HTTPS_CERT': 'missing.pem'}, 18196)
        self.assertEqual(env['VITE_API_BASE_URL'], '')
        self.assertEqual(env['VITE_BRIEFING_PREVIEW_FEEDBACK'], 'true')
        self.assertEqual(env['ZOOP_DEV_API_TARGET'], 'http://127.0.0.1:18196')
        self.assertEqual(env['ZOOP_DEV_HTTPS_CERT'], '')


if __name__ == '__main__':
    unittest.main()
