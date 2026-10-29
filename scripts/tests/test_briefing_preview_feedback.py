"""Synthetic local-reader feedback; SQLite durability and HTTP boundary tests."""
import copy
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from briefing_preview_feedback import PreviewFeedbackStore, PreviewFeedbackHttp, FeedbackError, ENDPOINT


def response(version='v1'):
    return {'id':'round-a','status':'published','items':[{'eventId':'issue-a'},{'eventId':'issue-b'}],
            'issueIntelligence':{'roundId':'round-a','schemaVersion':'issue-intelligence-v1',
                'resultVersion':version,'issues':[{'issueId':'issue-a'},{'issueId':'issue-b'}]}}


def target(version='v1', issue=None):
    return {'roundId':'round-a','resultVersion':version,'feature':'briefing_issue' if issue else 'briefing_round',
            'targetId':'round-a/'+issue if issue else 'round-a'}


class PreviewFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'ratings.sqlite3'
        self.store = PreviewFeedbackStore(self.path, [response()])
        self.first, self.cookie = self.store.read(target(), None)

    def write(self, value, reason=None, t=None):
        return self.store.write({**(t or target()),'value':value,'reason':reason},self.cookie,self.first['csrfToken'])

    def test_persists_restore_and_repeated_upsert_is_one_rating(self):
        self.write('up'); self.write('up')
        reopened = PreviewFeedbackStore(self.path,[response()])
        self.assertEqual(reopened.read(target(), self.cookie)[0]['value'],'up')
        with reopened.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM ratings').fetchone()[0],1)

    def test_none_cancels_without_deletion_and_up_clears_reason(self):
        self.write('down','  합성 근거를 더 보고 싶어요.  ')
        self.assertEqual(self.store.read(target(),self.cookie)[0]['reason'],'합성 근거를 더 보고 싶어요.')
        self.write('up');self.assertIsNone(self.store.read(target(),self.cookie)[0]['reason'])
        self.write('none')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT value FROM ratings').fetchall(),[('none',)])

    def test_round_issues_and_browsers_are_isolated(self):
        self.write('up');self.write('down','합성 사유',target(issue='issue-a'))
        self.assertEqual(self.store.read(target(issue='issue-b'),self.cookie)[0]['value'],'none')
        other,other_cookie=self.store.read(target(),None)
        self.assertNotEqual(other['csrfToken'],self.first['csrfToken'])
        self.assertEqual(self.store.read(target(),other_cookie)[0]['value'],'none')

    def test_new_revision_does_not_inherit_or_erase_old_vote(self):
        self.write('up');new=PreviewFeedbackStore(self.path,[response('v2')])
        self.assertEqual(new.read(target('v2'),self.cookie)[0]['value'],'none')
        with self.assertRaises(FeedbackError) as e:new.read(target(),self.cookie)
        self.assertEqual(e.exception.status,409)
        with new.connect() as db:self.assertEqual(db.execute('SELECT result_version,value FROM ratings').fetchall(),[('v1','up')])

    def test_foreign_target_or_missing_csrf_cannot_write(self):
        with self.assertRaises(FeedbackError) as e:self.write('up',t=target(issue='foreign'))
        self.assertEqual(e.exception.status,404)
        for cookie,csrf in [(None,None),(self.cookie,'wrong')]:
            with self.assertRaises(FeedbackError) as e:self.store.write({**target(),'value':'down','reason':None},cookie,csrf)
            self.assertEqual(e.exception.status,403)

    def test_bad_reasons_and_unknown_fields_rejected(self):
        for v,reason in [('up','사유'),('down','x'*201),('down',12),('bad',None)]:
            with self.assertRaises(FeedbackError):self.write(v,reason)
        with self.assertRaises(FeedbackError):self.store.write({**target(),'value':'up','reason':None,'memberId':'forged'},self.cookie,self.first['csrfToken'])

    def test_concurrent_same_goal_keeps_one_row(self):
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:self.write('up'),range(8)))
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT value FROM ratings').fetchall(),[('up',)])

    def test_http_requires_exact_origin_json_csrf_and_never_exposes_cors(self):
        store=self.store
        class Handler(PreviewFeedbackHttp):
            feedback_store=store;feedback_origins=frozenset({'http://localhost:13188'})
            def send_response(self,status):self.status=status
            def send_header(self,k,v):self.out_headers[k]=v
            def end_headers(self):pass
        def send(headers):
            h=Handler();h.path=ENDPOINT;h.command='PUT';h.out_headers={};h.wfile=io.BytesIO()
            body=json.dumps({**target(),'value':'up','reason':None}).encode();h.rfile=io.BytesIO(body)
            h.headers={'Content-Length':str(len(body)),'Content-Type':'application/json','Cookie':self.cookie,'X-Preview-CSRF-Token':self.first['csrfToken'],**headers}
            self.assertTrue(h.feedback_request());return h
        self.assertEqual(send({'Origin':'https://foreign.example'}).status,403)
        self.assertEqual(send({}).status,403)
        self.assertEqual(send({'Origin':'http://localhost:13188','Content-Type':'text/plain'}).status,415)
        good=send({'Origin':'http://localhost:13188'})
        self.assertEqual(good.status,200);self.assertEqual(good.out_headers['Cache-Control'],'no-store')
        self.assertNotIn('Access-Control-Allow-Origin',good.out_headers)


if __name__=='__main__':unittest.main()
