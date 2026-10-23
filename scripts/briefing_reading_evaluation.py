#!/usr/bin/env python3
"""Same-input, order-reversed comparison of legacy and specific company reading.

Offline by default. Model judgments are a small-sample evaluation, not financial
performance or a factual ground-truth label. Original results remain immutable.
"""
import argparse
import copy
import os
from pathlib import Path
import briefing_company_reading as reading
base = reading.base
CRITERIA = reading.QUALITY


def compare_input(row):
    value = copy.deepcopy(row['frozen'])
    value.pop('schemaVersion')
    return value


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


def run(args, transport=None):
    source, output = Path(args.improved).resolve(), Path(args.output).resolve()
    reading.company.require(source != output and source not in output.parents and output not in source.parents, 'evaluation_separate_output')
    raw = base.regular(source / 'bundle-v2.json')
    bundle = base.strict_load(raw)
    layer = bundle['marketEnrichment']['seriesCompanyReading']
    reading.company.require(layer['schemaVersion'] == reading.SCHEMA_V2, 'evaluation_v2_required')
    rows = [row for row in layer['rounds'] if row['status'] == 'PASS' and
            (not args.round_id or row['roundId'] == args.round_id) and len(row['draft']['companies']) >= 3]
    reading.company.require(bool(rows), 'evaluation_three_companies_required')
    improved = rows[0]
    full = next(row for row in bundle['marketEnrichment']['seriesCompanyOutlooks']['rounds'] if row['roundId'] == improved['roundId'])
    legacy_frozen = reading.freeze(full, reading.VERSION)
    reading.company.require(compare_input(improved) == {k: v for k, v in legacy_frozen.items() if k != 'schemaVersion'}, 'evaluation_same_input')
    prompts = reading.company.context.PROMPTS.with_name('reading-pairwise-v1')
    identity = {'improvedBundleSha256': base.digest(raw), 'roundId': improved['roundId'],
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
    selected = sorted(c['companyId'] for c in improved['draft']['companies'])[:3]
    old = {c['companyId']: c for c in legacy['draft']['companies']}
    new = {c['companyId']: c for c in improved['draft']['companies']}
    judge = reading.company.context.legacy.MarketSummaryClient(output, send, args.max_calls, prompt_root=prompts)
    results = []
    for improved_is_a in (False, True):
        a, b = (new, old) if improved_is_a else (old, new)
        data = {'context': compare_input(improved), 'companies': [{'companyId': cid, 'A': a[cid], 'B': b[cid]} for cid in selected]}
        digest = judge.request_digest('company_reading_pairwise', data, 'review.md', 'unused', 6000, judge_schema(selected))
        answer = judge.call('company_reading_pairwise', data, 'review.md', 'unused', 6000, judge_schema(selected))
        validate_judgment(answer, selected)
        results.append({'improvedIsA': improved_is_a, 'requestDigest': digest, 'judgment': answer})
    proof = {'status': 'COMPLETE', 'identity': identity, 'sampleSize': len(selected), 'orderReversed': True,
             'results': results, 'newPaidCalls': len(legacy_client.new_calls | judge.new_calls),
             'limitation': 'Model comparison of three companies under identical frozen inputs; not human calibration or investment performance.'}
    base.write_once(output / 'comparison.json', base.canonical(proof))
    return proof


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('improved', 'output', 'authorization-ref'): p.add_argument('--' + name, required=True)
    p.add_argument('--round-id'); p.add_argument('--key-file')
    p.add_argument('--max-calls', type=int, choices=range(1, 513), default=150)
    p.add_argument('--execute', action='store_true')
    return p


if __name__ == '__main__':
    print(base.canonical(run(parser().parse_args())).decode())
