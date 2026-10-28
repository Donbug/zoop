"""Failure boundaries of the actual producer client; the command pipe itself is exercised against PostgreSQL in Java."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1];sys.path.insert(0,str(SCRIPTS))
from briefing_usage import UsageSession,recorded,reconcile
import briefing_usage_run as runner

spec=importlib.util.spec_from_file_location('usage_base',SCRIPTS/'briefing_replay.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)


class Pipe:
    def __init__(self,reject=None):self.events=[];self.reject=reject
    def send(self,event):
        self.events.append(event)
        if event['op']==self.reject:raise ValueError('authored_ledger_failure')
        if event['op']=='claim':return {'ok':True,'attemptId':'attempt-authored','ownerToken':'owner-authored',
            'roundId':'round-authored','attemptNo':1,'status':'running','reused':False,'leaseUntil':'2026-12-01T00:00:00Z'}
        return {'ok':True,'created':True}


class Client(base.ResponsesClient):
    def request(self,stage,data,*args,**kwargs):
        schema={'type':'object','properties':{'value':{'type':'string'}},'required':['value'],'additionalProperties':False}
        request={'model':'authored-model','instructions':'authored instruction','input':json.dumps(data),
                 'text':{'format':{'name':stage}},'reasoning':{'effort':'low'}}
        return base.canonical(request),schema,base.digest(b'authored instruction')


def response(usage=None):
    return 200,base.canonical({'id':'authored-response','model':'authored-provider-model','status':'completed',
        'usage':{'input_tokens':10,'output_tokens':3} if usage is None else usage,
        'output':[{'type':'message','content':[{'type':'output_text','text':'{"value":"authored result"}'}]}]})


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.output=self.root/'output';self.output.mkdir(mode=0o700)
        self.claim={'round':{'id':'round-authored'},'purpose':'generation','requestKey':'authored-key','inputDigest':'a'*64,
                    'trigger':'scheduler','adminId':None,'inputArtifactId':None}
    def session(self,pipe=None,name='usage'):
        return UsageSession(pipe or Pipe(),self.claim,self.output/name,heartbeat_seconds=0)
    def test_records_before_actual_dispatch_and_keeps_only_receipt_metadata(self):
        pipe=Pipe()
        def transport(raw):
            self.assertEqual('model_start',pipe.events[-1]['op']);return response()
        client=Client(self.output,transport)
        with recorded(client,self.session(pipe)):
            self.assertEqual({'value':'authored result'},client.call('briefing_generation',{},'unused','unused'))
        finish=next(e for e in pipe.events if e['op']=='model_finish')
        self.assertEqual('low',next(e for e in pipe.events if e['op']=='model_start')['reasoningEffort'])
        self.assertEqual(10,finish['inputTokens']);self.assertEqual('authored-provider-model',finish['reportedModel'])
        serialized=json.dumps(pipe.events)
        self.assertNotIn('authored instruction',serialized);self.assertNotIn('authored result',serialized)
        self.assertTrue(list((self.output/'calls').glob('*.response.json')))
        self.assertFalse((self.output/'usage/.owner.lock').exists())
    def test_failed_start_never_dispatches_and_failed_attempt_is_closed(self):
        pipe=Pipe('model_start');calls=[];client=Client(self.output,lambda raw:calls.append(raw))
        with self.assertRaises(base.ReplayError):
            with recorded(client,self.session(pipe)):client.call('briefing_generation',{},'unused','unused')
        self.assertFalse(calls);self.assertEqual('failed',pipe.events[-1]['outcome'])
    def test_failed_db_finish_retains_raw_provider_response_and_content_free_recovery_receipt(self):
        pipe=Pipe('model_finish');client=Client(self.output,lambda _:response())
        with self.assertRaises(base.ReplayError):
            with recorded(client,self.session(pipe)):client.call('briefing_generation',{},'unused','unused')
        self.assertEqual(1,len(list((self.output/'calls').glob('*.response.json'))))
        self.assertEqual(1,len(list((self.output/'usage').glob('*.receipt.json'))))
        self.assertNotIn('authored result',next((self.output/'usage').glob('*.receipt.json')).read_text())
        recovery=Pipe()
        self.assertEqual(0,reconcile(self.output/'usage',recovery)['newModelCalls'])
        self.assertEqual(['model_finish'],[e['op'] for e in recovery.events])
        self.assertEqual(next(e for e in pipe.events if e['op']=='model_finish'),recovery.events[0])
    def test_unknown_network_failure_preserves_unknown_null_usage_and_does_not_resend(self):
        pipe=Pipe();sent=[]
        def fail(raw):sent.append(raw);raise OSError('authored unknown outcome')
        client=Client(self.output,fail)
        with self.assertRaises(base.ReplayError):
            with recorded(client,self.session(pipe)):client.call('briefing_generation',{},'unused','unused')
        row=next(e for e in pipe.events if e['op']=='model_finish')
        self.assertEqual('unknown',row['status']);self.assertIsNone(row['transmissionConfirmed']);self.assertIsNone(row['inputTokens'])
        other=Client(self.output,fail)
        with self.assertRaises(base.ReplayError):other.call('briefing_generation',{},'unused','unused')
        self.assertEqual(1,len(sent))
    def test_missing_one_token_is_null_without_discarding_known_other_token(self):
        pipe=Pipe();client=Client(self.output,lambda _:response({'input_tokens':10}))
        with self.assertRaises(base.ReplayError):
            with recorded(client,self.session(pipe)):client.call('briefing_generation',{},'unused','unused')
        row=next(e for e in pipe.events if e['op']=='model_finish')
        self.assertEqual('succeeded',row['status']);self.assertEqual(10,row['inputTokens']);self.assertIsNone(row['outputTokens'])
    def test_provider_failure_and_cancellation_keep_reported_usage(self):
        for state in ('failed','cancelled','incomplete'):
            with self.subTest(state=state):
                output=self.output/state;output.mkdir(mode=0o700)
                code,raw=response();body=json.loads(raw);body['status']=state
                body['error']={'code':'rate_limit_exceeded','message':'private provider detail must not enter ledger'}
                pipe=Pipe();client=Client(output,lambda _: (code,base.canonical(body)))
                with self.assertRaises(base.ReplayError):
                    with recorded(client,UsageSession(pipe,self.claim,output/'usage',heartbeat_seconds=0)):
                        client.call('briefing_generation',{},'unused','unused')
                row=next(e for e in pipe.events if e['op']=='model_finish')
                self.assertEqual('cancelled' if state=='cancelled' else 'failed',row['status'])
                self.assertTrue(row['transmissionConfirmed']);self.assertEqual(10,row['inputTokens'])
                self.assertEqual('rate_limit_exceeded',row['errorCode'])
                self.assertNotIn('private provider detail',json.dumps(pipe.events))
    def test_completed_call_cache_uses_replay_observation_and_never_transport(self):
        original=Client(self.output,lambda _:response());original.call('briefing_generation',{},'unused','unused')
        pipe=Pipe();client=Client(self.output,lambda _:self.fail('replay dispatched'))
        with recorded(client,self.session(pipe)):
            client.call('briefing_generation',{},'unused','unused')
        observations=[e for e in pipe.events if e['op']=='local']
        self.assertEqual(['replay'],[e['mode'] for e in observations]);self.assertFalse(any(e['op']=='model_start' for e in pipe.events))
    def test_same_output_concurrent_owner_is_refused_before_claim_or_dispatch(self):
        pipe=Pipe()
        with self.session(pipe):
            with self.assertRaises(FileExistsError):
                with self.session(pipe):pass
        self.assertEqual(1,sum(e['op']=='claim' for e in pipe.events))
    def test_duplicate_ai_attempt_never_dispatches_after_lost_acknowledgement(self):
        class Existing(Pipe):
            def send(self,event):
                value=super().send(event)
                if event['op']=='model_start':value['created']=False
                return value
        pipe=Existing();client=Client(self.output,lambda _:self.fail('duplicate dispatch'))
        with self.assertRaises(base.ReplayError):
            with recorded(client,self.session(pipe)):client.call('briefing_generation',{},'unused','unused')
    def test_save_only_runs_the_saved_result_callback_without_a_model(self):
        pipe=Pipe();called=[]
        with self.session(pipe) as session:
            session.save_only('saved-authored',lambda:called.append('saved'))
        self.assertEqual(['saved'],called);self.assertFalse(any(e['op']=='model_start' for e in pipe.events))
        self.assertEqual('save_only',next(e for e in pipe.events if e['op']=='local')['mode'])
    def test_output_for_another_owner_is_not_adopted(self):
        class Existing(Pipe):
            def send(self,event):
                value=super().send(event)
                if event['op']=='claim':value['reused']=True
                return value
        with self.assertRaisesRegex(ValueError,'another_output'):
            with self.session(Existing()):pass
        self.assertFalse((self.output/'usage/.owner.lock').exists())


if __name__=='__main__':unittest.main()
