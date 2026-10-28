#!/usr/bin/env python3
"""Generate a separately verified card layer without rewriting readings or prices."""
import argparse
import os
from pathlib import Path
import briefing_company_reading as reading

base = reading.base


def run(args, transport=None):
    baseline, output = Path(args.baseline).resolve(), Path(args.output).resolve()
    reading.company.require(baseline != output and baseline not in output.parents and output not in baseline.parents,
                            'card_separate_output')
    bundle_bytes = base.regular(baseline / 'bundle-v2.json')
    bundle = base.strict_load(bundle_bytes)
    series = 'seriesCompanyOutlooks' in bundle.get('marketEnrichment', {})
    layer = bundle['marketEnrichment'] if series else bundle['presentationEnrichment']
    key = 'seriesCompanyCards' if series else 'companyCardLayer'
    reading.company.require(key not in layer, 'card_layer_exists')
    rows = layer['seriesCompanyOutlooks' if series else 'companyOutlookLayer']['rounds']
    reading.company.require(0 < len(rows) <= 4 and all(r['status'] == 'PASS' for r in rows), 'card_valid_company_inputs')
    prompt_version = getattr(args, 'prompt_version', reading.CARD)
    prompts = reading.company.context.PROMPTS.with_name(prompt_version)
    identity = {'baselineSha256': base.digest(bundle_bytes), 'promptVersion': prompt_version,
                'promptArtifacts': {p.name: base.digest(base.regular(p)) for p in sorted(prompts.iterdir()) if p.is_file()},
                'runId': args.run_id, 'authorizationRef': args.authorization_ref, 'maximumPaidCalls': args.max_calls}
    previous = Path(args.previous_cards).resolve() if getattr(args, 'previous_cards', None) else None
    previous_rows = {}
    if previous:
        identity['previousCardsSha256'] = base.digest(base.regular(previous / 'bundle-v2.json'))
        prior_bundle = base.strict_load(base.regular(previous / 'bundle-v2.json'))
        original = dict(prior_bundle['marketEnrichment'] if series else prior_bundle['presentationEnrichment'])
        previous_rows = {r['roundId']: r for r in original.pop(key)['rounds']}
        # Only the presentation accounting ceiling is mutable. All content, sources and analysis stay bound.
        expected = dict(layer)
        if not series:
            for value in (original, expected):
                ceiling = value.pop('maximumPaidCallsIncludingPrior', None)
                reading.company.require(type(ceiling) is int and 0 < ceiling <= 512 and ceiling <= args.max_calls,
                                        'card_previous_call_ceiling')
        reading.company.require(original == expected, 'card_previous_input_changed')
    inherited = previous or baseline
    prior = len(list((inherited / 'calls').glob('*.pending.json')))
    needed = sum(previous_rows.get(r['roundId'], {}).get('status') != 'PASS' for r in rows)
    plan = {'priorReservations': prior, 'minimumNewCalls': 2 * needed,
            'maximumNewCalls': min(4 * needed, args.max_calls - prior), 'maximumTotalCalls': args.max_calls}
    if not args.execute:
        return {**plan, 'status': 'OFFLINE', 'newPaidCalls': 0}
    reading.company.require(prior + 2 * needed <= args.max_calls <= 512, 'card_call_limit')
    base.private_dir(output)
    if (output / 'card-proof.json').exists():
        reading.company.require(base.strict_load(base.regular(output / 'card-execution.json')) == identity, 'card_identity_changed')
        proof = base.strict_load(base.regular(output / 'card-proof.json'))
        reading.company.require(proof['bundleSha256'] == base.digest(base.regular(output / 'bundle-v2.json')), 'card_completed_changed')
        return {**proof, 'newPaidCalls': 0, 'reusedCompletedRun': True}
    lock = output / '.card-execution.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        base.write_once(output / 'card-execution.json', base.canonical(identity))
        for file in inherited.rglob('*'):
            if file.is_file() and file.name not in ('bundle-v2.json', 'card-execution.json', 'card-proof.json') and 'card-rounds' not in file.relative_to(inherited).parts:
                target = output / file.relative_to(inherited)
                base.private_dir(target.parent)
                if not target.exists(): os.link(file, target)
        client = reading.company.context.legacy.MarketSummaryClient(
            output, transport or base.authenticated_transport(Path(args.key_file), timeout=600),
            args.max_calls, prompt_root=prompts)
        completed = []
        for row in rows:
            frozen = reading.freeze(row, reading.CARD)
            path = output / 'card-rounds' / (row['roundId'] + '.json')
            if path.exists():
                result = base.strict_load(base.regular(path))
                reading.company.require(result['frozen'] == frozen, 'card_resume_changed')
            else:
                old = previous_rows.get(row['roundId'])
                if old:
                    reading.company.require(old['frozen'] == frozen, 'card_previous_frozen_changed')
                if old and old['status'] == 'PASS':
                    result = old
                else:
                    result = reading.assess(client, frozen, initial_attempts=old['attempts'] if old else None, card_prompt_version=prompt_version)
                if not old or old['status'] != 'PASS':
                    result.update(roundId=row['roundId'], cutoff=row['cutoff'], frozen=frozen,
                                  generatedAt=base.now(), pricePolicy='not_connected')
                    result['resultVersion'] = 'card-v1-' + base.digest(base.canonical(result))
                base.private_dir(path.parent)
                base.write_once(path, base.canonical(result))
            completed.append(result)
            print(base.canonical({'roundId': row['roundId'], 'status': result['status'], 'newCalls': len(client.new_calls)}).decode(), flush=True)
        owned = {a[k] for row in completed for a in row['attempts']
                 for k in ('generationRequestDigest', 'verificationRequestDigest') if k in a}
        receipts = [r for r in client.receipts() if r['requestDigest'] in owned]
        layer[key] = {'schemaVersion': reading.SCHEMA_CARD, 'authorizationRef': args.authorization_ref,
                      'rounds': completed, 'receipts': receipts}
        if not series: layer['maximumPaidCallsIncludingPrior'] = args.max_calls
        base.write_once(output / 'bundle-v2.json', base.canonical(bundle))
        proof = {**plan, 'status': 'COMPLETE', 'pass': sum(r['status'] == 'PASS' for r in completed),
                 'newPaidCalls': len(client.new_calls), 'totalReservations': len(list(client.calls.glob('*.pending.json'))),
                 'bundleSha256': base.digest(base.regular(output / 'bundle-v2.json')),
                 'inputTokens': sum(r['inputTokens'] for r in receipts if r['requestDigest'] in client.new_calls),
                 'outputTokens': sum(r['outputTokens'] for r in receipts if r['requestDigest'] in client.new_calls)}
        base.write_once(output / 'card-proof.json', base.canonical(proof))
        return proof
    finally:
        lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'output', 'authorization-ref', 'run-id'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--prompt-version', choices=['company-card-v1', 'company-card-v2'], default='company-card-v2')
    p.add_argument('--previous-cards', help='Reuse passed cards and preserve failed attempts in a new output directory')
    p.add_argument('--key-file')
    p.add_argument('--max-calls', type=int, default=400)
    p.add_argument('--execute', action='store_true')
    return p


if __name__ == '__main__':
    print(base.canonical(run(parser().parse_args())).decode(), flush=True)
