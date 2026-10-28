#!/usr/bin/env python3
"""Run an existing briefing generator/outlook producer with its PostgreSQL usage ledger.

Default is an offline plan. Execution requires an explicit operator authorization
and a Java ledger command array. This does not install a scheduler or publish an
unvalidated result. The existing validated publisher uses BriefingUsageLedger.publish.
"""
import argparse
import importlib.util
import json
from pathlib import Path

from briefing_usage import CommandPipe, UsageSession, digest, recorded, write_once

OUTLOOK_PROMPT_VERSIONS = frozenset('company-outlook-v'+str(n) for n in range(1,6))


def helper(name):
    spec = importlib.util.spec_from_file_location('_usage_'+name, Path(__file__).with_name(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load(path):
    raw = Path(path).read_bytes()
    if len(raw) > 4*1024*1024:
        raise ValueError('usage_job_input_too_large')
    return raw, json.loads(raw)


def run(job_path, output, command=None, *, execute=False, transport=None, key_file=None, pipe=None):
    job_path, output = Path(job_path).resolve(), Path(output).resolve()
    raw, job = load(job_path)
    expected = {'schemaVersion','operation','round','requestKey','trigger','adminId','inputArtifactId',
                'inputFile','inputSha256','maxCalls','authorizationRef'}
    if set(job) != expected or job['schemaVersion'] != 'briefing-recorded-producer-v1':
        raise ValueError('usage_job_contract')
    if job['operation'] not in ('generation','outlook','save_only_generation','save_only_outlook'):
        raise ValueError('usage_job_operation')
    source = (job_path.parent/job['inputFile']).resolve()
    if job_path.parent not in source.parents or source.is_symlink():
        raise ValueError('usage_job_input_path')
    data_raw, data = load(source)
    if digest(data_raw) != job['inputSha256']:
        raise ValueError('usage_job_input_digest')
    purpose = 'outlook' if job['operation'].endswith('outlook') else 'generation'
    if type(job['maxCalls']) is not int or not 0 <= job['maxCalls'] <= 16:
        raise ValueError('usage_job_call_limit')
    prompt_binding = None
    if job['operation'] == 'outlook':
        producer = helper('briefing_company_outlook')
        version = data.get('promptVersion', producer.VERSION)
        if not isinstance(version, str) or version not in OUTLOOK_PROMPT_VERSIONS:
            raise ValueError('usage_outlook_prompt_version')
        prompts = producer.PROMPTS.with_name(version)
        prompt_binding = {'promptVersion': version, 'promptArtifacts': {
            name: digest((prompts/name).read_bytes()) for name in ('generation.md','verification.md')}}
    plan = {'schemaVersion':'briefing-recorded-producer-v1','roundId':job['round']['id'],
            'purpose':purpose,'inputSha256':job['inputSha256'],'jobSha256':digest(raw),'newModelCalls':0}
    if not execute:
        return {**plan, 'status':'OFFLINE_PLAN'}
    if not job['authorizationRef'] or not (pipe or command):
        raise ValueError('usage_job_authorization_and_ledger_required')
    output.mkdir(mode=0o700,parents=True,exist_ok=True)
    if output.is_symlink() or output.stat().st_mode & 0o077:
        raise ValueError('usage_private_output_required')
    binding_path = output/'outlook-prompts.json'
    if prompt_binding is not None and not binding_path.exists() and (output/'identity.json').exists() \
            and version != 'company-outlook-v1':
        # Older non-v1 runs used v1 files despite their input version. Preserve
        # those records, but never reuse them as a verified run of the new version.
        raise ValueError('usage_legacy_outlook_prompt_binding_missing')
    write_once(output/'identity.json',plan)
    if prompt_binding is not None:
        write_once(binding_path, prompt_binding)
    result_path=output/'result.json'
    if result_path.exists():
        _, saved=load(result_path)
        if saved.get('jobSha256') != plan['jobSha256']:
            raise ValueError('usage_saved_result_identity')
        if (output/'ledger-finished.json').exists():
            return {**plan,'status':'REUSED_COMPLETE','newModelCalls':0}
    owned_pipe = pipe is None
    connection = pipe or CommandPipe(command)
    claim = {k:job[k] for k in ('round','requestKey','trigger','adminId','inputArtifactId')}
    claim['purpose']=purpose
    claim['inputDigest']=plan['inputSha256']
    session=UsageSession(connection,claim,output/'usage')
    try:
        if result_path.exists():
            with session:
                session.outcome=saved['outcome']
                if not session.terminal:
                    session.save_only(plan['inputSha256'],lambda:None)
            write_once(output/'ledger-finished.json',{'jobSha256':plan['jobSha256'],'attemptId':session.owner['attemptId']})
            return {**plan,'status':'REUSED_COMPLETE','newModelCalls':0}
        if job['operation'].startswith('save_only_'):
            if data.get('schemaVersion') != 'briefing-recorded-result-v1' or data.get('roundId') != job['round']['id'] \
                    or data.get('purpose') != purpose or data.get('outcome') not in ('available','withheld'):
                raise ValueError('usage_recovery_identity')
            with session:
                if session.terminal:raise ValueError('completed_attempt_without_saved_output')
                session.outcome=data['outcome']
                session.save_only(job['inputSha256'],lambda:write_once(result_path,{**data,'jobSha256':plan['jobSha256']}))
            write_once(output/'ledger-finished.json',{'jobSha256':plan['jobSha256'],'attemptId':session.owner['attemptId']})
            return {**plan,'status':'SAVED_ONLY','newModelCalls':0}
        if transport is None and key_file is None:
            raise ValueError('usage_live_transport_required')
        if job['operation']=='outlook':
            base=producer.base
            if data.get('roundId') != job['round']['id'] or data.get('date') != job['round']['date'] \
                    or data.get('edition') != job['round']['edition'] or data.get('cutoff') != job['round']['windowTo']:
                raise ValueError('usage_outlook_round_identity')
            client=producer.context.legacy.MarketSummaryClient(output,transport or base.authenticated_transport(Path(key_file)),
                job['maxCalls'],prompt_root=prompts)
            generate=lambda:producer.assess(client,data)
        else:
            producer=helper('briefing_round_simulation');base=producer.base
            if set(data) != {'selected','context','maxRepairs'} or data['context'].get('context',{}).get('date') != job['round']['date'] \
                    or data['context'].get('context',{}).get('edition') != job['round']['edition']:
                raise ValueError('usage_generation_round_identity')
            identity=data['context']['context']
            if identity.get('window',{}).get('to') != job['round']['windowTo'] \
                    or identity.get('window',{}).get('from') != job['round']['windowFrom'] \
                    or data['context'].get('contextSha256') != digest(base.canonical(identity)):
                raise ValueError('usage_generation_window_identity')
            if type(data['maxRepairs']) is not int or data['maxRepairs'] not in (0,1):
                raise ValueError('usage_generation_repairs')
            client=producer.SimulationClient(output,transport or base.authenticated_transport(Path(key_file)),job['maxCalls'])
            generate=lambda:producer.generate_round(client,data['selected'],job['round']['edition'],data['context'],data['maxRepairs'])
        with recorded(client,session):
            if session.terminal:raise ValueError('completed_attempt_without_saved_output')
            result=generate()
            passed=result.get('status')=='PASS' if purpose=='outlook' else result.get('verification',{}).get('status')=='PASS'
            session.outcome='available' if passed else 'withheld'
            session.stage='save'
            write_once(result_path,{**plan,'schemaVersion':'briefing-recorded-result-v1',
                'outcome':session.outcome,'result':result})
        write_once(output/'ledger-finished.json',{'jobSha256':plan['jobSha256'],'attemptId':session.owner['attemptId']})
        return {**plan,'status':'COMPLETE','outcome':session.outcome,'newModelCalls':len(client.new_calls)}
    finally:
        if owned_pipe:
            connection.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--ledger-command-file',type=Path)
    parser.add_argument('--key-file',type=Path)
    args=parser.parse_args()
    command=json.loads(args.ledger_command_file.read_bytes()) if args.ledger_command_file else None
    print(json.dumps(run(args.job,args.output,command,execute=args.execute,key_file=args.key_file),ensure_ascii=False))


if __name__=='__main__':main()
