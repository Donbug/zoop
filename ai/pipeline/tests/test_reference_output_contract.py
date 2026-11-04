"""Large native citation catalogues remain grounded without changing historical contracts."""
import copy
from datetime import datetime,timedelta,timezone
import pytest
from tests.live_support import environment
from tests.test_live_prompts import extraction_case
from zoop_ai_pipeline import live_prompts,live_runtime
from zoop_ai_pipeline.extraction_contracts import ReplyInvalid
from zoop_ai_pipeline.live_runtime import LiveFailure,LiveRuntime

def setup(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc)
    environment(monkeypatch,tmp_path,**{
        live_runtime.PROFILE_VAR:'admitted-set-capped-v4',live_runtime.OUTPUT_VAR:'citation-refs-default-1',
        live_runtime.RUN_ID_VAR:'synthetic-reference-run',live_runtime.SET_ID_VAR:'synthetic-reference-set',
        live_runtime.ADMIT_FROM_VAR:now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        live_runtime.ADMIT_UNTIL_VAR:(now+timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        live_runtime.FINISH_BY_VAR:(now+timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        live_runtime.SHARED_MAX_VAR:'0.9',live_runtime.PERSONAL_MAX_VAR:'0.1'})
    return LiveRuntime.from_env()

def test_large_catalogue_restores_exactly_without_fallback_or_tier_change(monkeypatch,tmp_path):
    runtime=setup(monkeypatch,tmp_path)
    _,payload,_=extraction_case('\n'.join('가상 원문 구간 '+str(n) for n in range(541)))
    _,refs=live_prompts.catalogue('extract',payload)
    assert len(refs)>=541
    with pytest.raises(ValueError,match='live_output_schema_limits'):
        live_prompts.citation_schema('extract',list(refs))
    prepared=runtime.prepare('extract',payload)
    assert prepared['body']['service_tier']=='default'
    assert 'fallback' not in runtime.binding()['generation'] and 'fallback' not in prepared
    schema=prepared['body']['response_format']['json_schema']['schema']
    assert 'enum' not in schema['$defs']['Evidence']['properties']['segmentId']
    restored=LiveRuntime.from_binding(runtime.binding())
    assert restored.prepare('extract',payload)==prepared
    restored._check_prepared(prepared)

def test_reference_owner_still_rejects_an_invented_citation_and_contract_tampering(monkeypatch,tmp_path):
    runtime=setup(monkeypatch,tmp_path)
    _,payload,answer=extraction_case('합성 근거 문장')
    _,refs=live_prompts.catalogue('extract',payload)
    answer['mentions'][0]['evidence']=[{'segmentId':next(iter(refs))}]
    assert live_prompts.expand('extract',payload,answer)['mentions'][0]['evidence']
    answer['mentions'][0]['evidence']=[{'segmentId':'q-not-supplied'}]
    with pytest.raises(ReplyInvalid,match='live_citation_reference_unknown'):
        live_prompts.expand('extract',payload,answer)
    binding=copy.deepcopy(runtime.binding());binding['generation']['outputContract']['name']='citation-enum-1'
    from zoop_ai_pipeline.relation_contracts import digest
    binding['identity']=digest({k:v for k,v in binding.items() if k!='identity'})
    with pytest.raises(LiveFailure,match='live_binding_mismatch'):LiveRuntime.from_binding(binding)
