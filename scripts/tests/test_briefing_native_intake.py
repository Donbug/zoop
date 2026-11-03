import json,os,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ai/pipeline/src'))
import httpx
import briefing_native_intake as native
import briefing_server_runtime as server

class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.cfg={'work':str(self.root),'authorizationRef':'synthetic-only'}
    def request(self,number=0,model='gpt-6-luna'):
        return httpx.Request('POST','https://api.openai.com/v1/chat/completions',content=json.dumps({'model':model,
            'service_tier':'default','messages':[{'role':'user','content':'synthetic '+str(number)}],'max_completion_tokens':1000}).encode())
    def setup_transport(self,peer):
        session=Mock();session.send.return_value={'created':True}
        session._receipt.side_effect=lambda *args:args
        budget=server.Budget(self.cfg,'brf-2026-11-03-evening',lambda:None,Mock())
        receipts=self.root/'receipts';receipts.mkdir()
        with patch.object(httpx,'HTTPTransport',return_value=peer):transport=native.NativeTransport(session,budget,receipts)
        return transport,session,budget
    def test_native_and_briefing_share_the_same_sixteen_call_ceiling(self):
        peer=Mock();peer.handle_request.side_effect=lambda req:httpx.Response(200,json={'usage':{'prompt_tokens':10,'completion_tokens':2}},request=req)
        transport,session,budget=self.setup_transport(peer)
        for i in range(12):transport.handle_request(self.request(i))
        with self.assertRaisesRegex(ValueError,'native_phase_call_limit'):transport.handle_request(self.request(12))
        for i in range(4):
            raw=json.dumps({'model':'gpt-6-luna','store':False,'service_tier':'default','instructions':'briefing'+str(i),'max_output_tokens':10}).encode()
            reservation=budget.reserve(raw);budget.settle(reservation,b'{"usage":{"input_tokens":1,"output_tokens":1}}')
        with self.assertRaisesRegex(ValueError,'round_budget'):budget.reserve(json.dumps({'model':'gpt-6-luna','store':False,'service_tier':'default','max_output_tokens':10,'instructions':'seventeenth'}).encode())
        self.assertEqual(12,peer.handle_request.call_count)
    def test_each_http_client_borrows_transport_until_explicit_slot_shutdown(self):
        peer=Mock();peer.handle_request.side_effect=lambda req:httpx.Response(200,json={'usage':{'prompt_tokens':10,'completion_tokens':2}},request=req)
        transport,session,_=self.setup_transport(peer)
        for number in (1,2):
            with httpx.Client(transport=transport) as client:
                request=self.request(number)
                client.send(request)
        self.assertEqual(2,peer.handle_request.call_count)
        peer.close.assert_not_called()
        transport.shutdown();peer.close.assert_called_once()

    def test_unknown_native_transport_never_retries_or_turns_unknown_usage_into_zero(self):
        peer=Mock();peer.handle_request.side_effect=httpx.ReadTimeout('synthetic')
        transport,session,_=self.setup_transport(peer)
        with self.assertRaises(httpx.ReadTimeout):transport.handle_request(self.request())
        with self.assertRaisesRegex(ValueError,'uncertain_or_reused_request'):transport.handle_request(self.request())
        self.assertEqual(1,peer.handle_request.call_count);self.assertEqual(1,session.send.call_count)
        args=session._receipt.call_args.args
        self.assertEqual(('unknown',None,None,None),args[1:5])
    def test_current_authority_revocation_stops_before_budget_or_ai_start(self):
        peer=Mock();transport,session,budget=self.setup_transport(peer)
        budget.authority=Mock(side_effect=ValueError('revoked'))
        with self.assertRaisesRegex(ValueError,'revoked'):transport.handle_request(self.request())
        session.send.assert_not_called();peer.handle_request.assert_not_called()
    def test_native_configuration_uses_finite_current_window_and_no_fallback_provider(self):
        for name,key in [('openai','OPENAI_API_KEY'),('typesafe','TYPESAFE_API_KEY')]:
            p=self.root/name;p.write_text(key+'=synthetic-only\n');p.chmod(0o600)
        with patch.dict(os.environ,{},clear=True):
            cls=native.configure_runtime({'keyFile':str(self.root/'openai'),'verifierKeyFile':str(self.root/'typesafe')},
                self.root,(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat())
            runtime=cls.from_env(need_send=True)
            self.assertEqual('citation-refs-default-1',os.environ['ZOOP_AI_PIPELINE_LIVE_OUTPUT_CONTRACT'])
            self.assertEqual('admitted-set-capped-v4',os.environ['ZOOP_AI_PIPELINE_LIVE_PROFILE'])
            self.assertNotIn('fallback',runtime.binding()['generation'])
    def test_new_authority_does_not_copy_or_replace_original_routes(self):
        cfg={**self.cfg,'authorityRoot':str(self.root/'authority'),'originalSourceAuthority':'/synthetic/original-serving-authorities.json'}
        native.initialize_authority(cfg)
        before=(self.root/'authority/serving-delegates.json').read_bytes()
        self.assertEqual([cfg['originalSourceAuthority'],str(self.root/'authority/new-authorities.json')],json.loads(before)['delegates'])
        native.initialize_authority(cfg)
        self.assertEqual(before,(self.root/'authority/serving-delegates.json').read_bytes())
    def test_share_controls_and_next_article_are_not_company_news(self):
        companies=[{'companyId':'synthetic-kakao','name':'카카오','aliases':[]},
            {'companyId':'synthetic-samsung','name':'삼성전자','aliases':[]}]
        raw='<div class="article_body"><div class="view_cont"><p>수목원 한파 대비</p><section class="area_page">다음기사 삼성전자</section><div class="view_opt"><div class="share"><button>카카오톡</button></div></div></div></div>'.encode()
        self.assertEqual([],native.source_matches(native.relevance_text(raw),companies))
        self.assertIn('수목원',native.relevance_text(raw))

    def test_embedded_english_substring_is_not_a_company_match(self):
        companies=[{'companyId':'synthetic-kia','name':'가상기아','aliases':['Kia']}]
        self.assertEqual([],native.source_matches('Helsinkiannual unrelated word',companies))
        self.assertEqual(['synthetic-kia'],native.source_matches('Kia supplied a component.',companies))

if __name__=='__main__':unittest.main()
