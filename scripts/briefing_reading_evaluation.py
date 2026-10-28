#!/usr/bin/env python3
"""Same-input, order-reversed comparison of legacy and specific company reading.

Offline by default. Model judgments are a small-sample evaluation, not financial
performance or a factual ground-truth label. Original results remain immutable.
"""
import argparse
import copy
import os
from itertools import combinations
from pathlib import Path
import briefing_company_reading as reading
base = reading.base
CRITERIA = reading.QUALITY
SAMPLE_POLICY = 'single-issue-company-v1'


def compare_input(row):
    value = copy.deepcopy(row['frozen'])
    value.pop('schemaVersion')
    return value


def representative_cases(frozen):
    # Company-wide prose cannot be attributed to one of several issue IDs.
    # Only unambiguous single-issue targets count towards the three-issue sample.
    targets = sorted((t for t in frozen['targets'] if len(t['issueIds']) == 1), key=lambda t: t['companyId'])
    for chosen in combinations(targets, 3):
        if len({t['issueIds'][0] for t in chosen}) == 3:
            return [{'companyId': t['companyId'], 'issueId': t['issueIds'][0]} for t in chosen]
    return []


def representative_round_cases(rows):
    pool = [{**case, 'roundId': row['roundId']} for row in rows
            for target in sorted(row['frozen']['targets'], key=lambda t: t['companyId'])
            if len(target['issueIds']) == 1
            for case in ({'companyId': target['companyId'], 'issueId': issue} for issue in target['issueIds'])]
    for chosen in combinations(pool, 3):
        if len({c['companyId'] for c in chosen}) == len({c['issueId'] for c in chosen}) == 3:
            return list(chosen)
    return []


def run_multiround(args, source, output, bundle, parent, layer, raw, transport):
    rows = [r for r in layer['rounds'] if r['status'] == 'PASS' and (not args.round_id or r['roundId'] == args.round_id)]
    cases = representative_round_cases(rows)
    reading.company.require(bool(cases), 'evaluation_three_distinct_company_issues_required')
    chosen = [r for r in rows if r['roundId'] in {c['roundId'] for c in cases}]
    fulls = {r['roundId']: r for r in parent['seriesCompanyOutlooks' if 'seriesCompanyOutlooks' in parent else 'companyOutlookLayer']['rounds']}
    frozen = {r['roundId']: reading.freeze(fulls[r['roundId']], reading.VERSION) for r in chosen}
    for row in chosen:
        reading.company.require(compare_input(row) == {k:v for k,v in frozen[row['roundId']].items() if k != 'schemaVersion'}, 'evaluation_same_input')
    prompts = reading.company.context.PROMPTS.with_name('reading-pairwise-multiround-v1')
    identity = {'contract': 'same-input-multi-round-v1', 'samplePolicy': SAMPLE_POLICY,
                'improvedBundleSha256': base.digest(raw), 'cases': cases,
                'commonInputSha256ByRound': {r['roundId']: base.digest(base.canonical(compare_input(r))) for r in chosen},
                'promptArtifacts': {p.name: base.digest(base.regular(p)) for p in prompts.iterdir() if p.is_file()},
                'legacyPromptArtifacts': {p.name: base.digest(base.regular(p)) for p in reading.company.context.PROMPTS.with_name(reading.VERSION).iterdir() if p.is_file()},
                'authorizationRef': args.authorization_ref, 'maximumPaidCalls': args.max_calls}
    if not args.execute:
        return {'status':'OFFLINE', 'identity':identity, 'minimumNewCalls':2*len(chosen)+2, 'maximumNewCalls':4*len(chosen)+2, 'newPaidCalls':0}
    if (output/'comparison.json').exists():
        saved=base.strict_load(base.regular(output/'comparison.json'))
        reading.company.require(saved['identity']==identity, 'evaluation_resume_identity')
        return {**saved, 'newPaidCalls':0}
    reading.company.require(bool(args.authorization_ref) and bool(transport or args.key_file), 'evaluation_authorization')
    base.private_dir(output/'calls');base.private_dir(output/'legacy-rounds')
    for p in (source/'calls').glob('*.json'):
        if not (output/'calls'/p.name).exists():os.link(p,output/'calls'/p.name)
    send=transport or base.authenticated_transport(Path(args.key_file), timeout=600)
    legacy_client=reading.company.context.legacy.MarketSummaryClient(output, send, args.max_calls,
        prompt_root=reading.company.context.PROMPTS.with_name(reading.VERSION))
    legacy={}
    for row in chosen:
        result=reading.assess(legacy_client, frozen[row['roundId']])
        base.write_once(output/'legacy-rounds'/(row['roundId']+'.json'),base.canonical(result))
        reading.company.require(result['status']=='PASS','evaluation_legacy_withheld_not_a_valid_baseline')
        legacy[row['roundId']]={c['companyId']:c for c in result['draft']['companies']}
    improved={r['roundId']:{c['companyId']:c for c in r['draft']['companies']} for r in chosen}
    judge=reading.company.context.legacy.MarketSummaryClient(output,send,args.max_calls,prompt_root=prompts)
    ids=[c['companyId'] for c in cases];results=[]
    for improved_is_a in (False,True):
        a,b=(improved,legacy) if improved_is_a else (legacy,improved)
        data={'context':{'rounds':{r['roundId']:compare_input(r) for r in chosen}},
              'companies':[{'companyId':c['companyId'],'roundId':c['roundId'],'issueId':c['issueId'],
                  'A':a[c['roundId']][c['companyId']],'B':b[c['roundId']][c['companyId']]} for c in cases]}
        digest=judge.request_digest('company_reading_pairwise',data,'review.md','unused',6000,judge_schema(ids))
        answer=judge.call('company_reading_pairwise',data,'review.md','unused',6000,judge_schema(ids))
        validate_judgment(answer,ids);results.append({'improvedIsA':improved_is_a,'requestDigest':digest,'judgment':answer})
    proof={'status':'COMPLETE','identity':identity,'sampleSize':3,'cases':cases,'orderReversed':True,'results':results,
           'newPaidCalls':len(legacy_client.new_calls|judge.new_calls),
           'limitation':'Each company uses identical frozen inputs across A/B within its own round; three model-reviewed cases, not human calibration or investment performance.'}
    base.write_once(output/'comparison.json',base.canonical(proof));return proof


def judge_schema(ids):
    choice = {'type': 'string', 'enum': ['A', 'B', 'tie']}
    fields = {'companyId': {'type': 'string', 'enum': ids},
              'supportedA': {'type': 'boolean'}, 'supportedB': {'type': 'boolean'},
              **{key: choice for key in CRITERIA},
              'reason': {'type': 'string', 'minLength': 1, 'maxLength': 700}}
    return reading.company.obj({'checks': {'type': 'array', 'minItems': len(ids), 'maxItems': len(ids),
                                          'items': reading.company.obj(fields)}})


def validate_judgment(value, ids):
    base.validate_schema(value, judge_schema(ids))
    reading.company.require(len({c['companyId'] for c in value['checks']}) == len(ids), 'evaluation_coverage')


def _run(args, transport=None):
    source, output = Path(args.improved).resolve(), Path(args.output).resolve()
    reading.company.require(source != output and source not in output.parents and output not in source.parents, 'evaluation_separate_output')
    raw = base.regular(source / 'bundle-v2.json')
    bundle = base.strict_load(raw)
    series = 'seriesCompanyReading' in bundle.get('marketEnrichment', {})
    parent = bundle['marketEnrichment'] if series else bundle['presentationEnrichment']
    layer = parent['seriesCompanyReading' if series else 'companyReadingLayer']
    reading.company.require(layer['schemaVersion'] == reading.SCHEMA_V2, 'evaluation_v2_required')
    if getattr(args, 'multi_round', False):
        return run_multiround(args, source, output, bundle, parent, layer, raw, transport)
    rows = [row for row in layer['rounds'] if row['status'] == 'PASS' and
            (not args.round_id or row['roundId'] == args.round_id) and len(row['draft']['companies']) >= 3 and representative_cases(row['frozen'])]
    reading.company.require(bool(rows), 'evaluation_three_companies_required')
    improved = rows[0]
    full = next(row for row in parent['seriesCompanyOutlooks' if series else 'companyOutlookLayer']['rounds'] if row['roundId'] == improved['roundId'])
    legacy_frozen = reading.freeze(full, reading.VERSION)
    reading.company.require(compare_input(improved) == {k: v for k, v in legacy_frozen.items() if k != 'schemaVersion'}, 'evaluation_same_input')
    prompts = reading.company.context.PROMPTS.with_name('reading-pairwise-v1')
    identity = {'samplePolicy': SAMPLE_POLICY, 'improvedBundleSha256': base.digest(raw), 'roundId': improved['roundId'],
                'commonInputSha256': base.digest(base.canonical(compare_input(improved))),
                'promptArtifacts': {p.name: base.digest(base.regular(p)) for p in prompts.iterdir() if p.is_file()},
                'legacyPromptArtifacts': {p.name: base.digest(base.regular(p)) for p in reading.company.context.PROMPTS.with_name(reading.VERSION).iterdir() if p.is_file()},
                'authorizationRef': args.authorization_ref, 'maximumPaidCalls': args.max_calls}
    if not args.execute:
        return {'status': 'OFFLINE', 'identity': identity, 'minimumNewCalls': 4, 'maximumNewCalls': 6, 'newPaidCalls': 0}
    if (output / 'comparison.json').exists():
        saved = base.strict_load(base.regular(output / 'comparison.json'))
        reading.company.require(saved['identity'] == identity, 'evaluation_resume_identity')
        return {**saved, 'newPaidCalls': 0}
    reading.company.require(bool(args.authorization_ref) and bool(transport or args.key_file), 'evaluation_authorization')
    base.private_dir(output / 'calls')
    for path in (source / 'calls').glob('*.json'):
        target = output / 'calls' / path.name
        if not target.exists(): os.link(path, target)
    send = transport or base.authenticated_transport(Path(args.key_file), timeout=600)
    legacy_client = reading.company.context.legacy.MarketSummaryClient(output, send, args.max_calls,
        prompt_root=reading.company.context.PROMPTS.with_name(reading.VERSION))
    legacy = reading.assess(legacy_client, legacy_frozen)
    base.write_once(output / 'legacy.json', base.canonical(legacy))
    reading.company.require(legacy['status'] == 'PASS', 'evaluation_legacy_withheld_not_a_valid_baseline')
    cases = representative_cases(improved['frozen'])
    selected = [case['companyId'] for case in cases]
    old = {c['companyId']: c for c in legacy['draft']['companies']}
    new = {c['companyId']: c for c in improved['draft']['companies']}
    judge = reading.company.context.legacy.MarketSummaryClient(output, send, args.max_calls, prompt_root=prompts)
    results = []
    for improved_is_a in (False, True):
        a, b = (new, old) if improved_is_a else (old, new)
        data = {'context': compare_input(improved), 'companies': [
            {'companyId': case['companyId'], 'issueId': case['issueId'],
             'A': a[case['companyId']], 'B': b[case['companyId']]} for case in cases]}
        digest = judge.request_digest('company_reading_pairwise', data, 'review.md', 'unused', 6000, judge_schema(selected))
        answer = judge.call('company_reading_pairwise', data, 'review.md', 'unused', 6000, judge_schema(selected))
        validate_judgment(answer, selected)
        results.append({'improvedIsA': improved_is_a, 'requestDigest': digest, 'judgment': answer})
    proof = {'status': 'COMPLETE', 'identity': identity, 'sampleSize': len(selected), 'cases': cases, 'orderReversed': True,
             'results': results, 'newPaidCalls': len(legacy_client.new_calls | judge.new_calls),
             'limitation': 'Model comparison of three companies under identical frozen inputs; not human calibration or investment performance.'}
    base.write_once(output / 'comparison.json', base.canonical(proof))
    return proof


def run(args, transport=None):
    if not args.execute:
        return _run(args, transport)
    source, output = Path(args.improved).resolve(), Path(args.output).resolve()
    reading.company.require(source != output and source not in output.parents and output not in source.parents,
                            'evaluation_separate_output')
    base.private_dir(output)
    lock = output / '.reading-evaluation.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        return _run(args, transport)
    finally:
        lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('improved', 'output', 'authorization-ref'): p.add_argument('--' + name, required=True)
    p.add_argument('--round-id'); p.add_argument('--key-file')
    p.add_argument('--multi-round', action='store_true', help='Select three distinct company/issues across rounds; preserve the same input separately for each round')
    p.add_argument('--max-calls', type=int, choices=range(1, 513), default=150)
    p.add_argument('--execute', action='store_true')
    return p


if __name__ == '__main__':
    print(base.canonical(run(parser().parse_args())).decode())
