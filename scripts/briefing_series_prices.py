#!/usr/bin/env python3
"""Archive cutoff prices for a completed local series without any AI call or text change."""
import argparse
import os
from datetime import timedelta, timezone
from pathlib import Path
import briefing_company_prices as prices

base = prices.base
SCHEMA = 'zoop-series-company-prices-v1'


def run(args, transport=None):
    baseline, output = Path(args.baseline).resolve(), Path(args.output).resolve()
    if baseline == output or baseline in output.parents or output in baseline.parents:
        raise ValueError('prices_separate_output')
    original = base.regular(baseline / 'bundle-v2.json')
    bundle = base.strict_load(original)
    if 'roundSeries' not in bundle:
        raise ValueError('prices_explicit_series_required')
    layer = bundle['marketEnrichment']
    company_layer = layer['seriesCompanyOutlooks']
    if args.authorization_ref != company_layer['authorizationRef'] or 'seriesCompanyPrices' in layer:
        raise ValueError('prices_authorization_or_existing_layer')
    rows = [r for r in company_layer['rounds'] if r['status'] == 'PASS']
    if not rows or len(rows) > 14:
        raise ValueError('prices_company_rounds')
    cutoffs = [prices.market.aware(r['cutoff']) for r in rows]
    start = min(cutoffs).astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
    end = max(cutoffs).astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    bounds = prices.period(int(start.timestamp()), int(end.timestamp()))
    identity = {'schemaVersion': SCHEMA, 'baseBundleSha256': base.digest(original),
                'authorizationRef': args.authorization_ref, 'period1': bounds[0], 'period2': bounds[1]}
    base.private_dir(output)
    base.write_once(output / 'prices-baseline.json', original)
    if (output / 'prices-proof.json').exists():
        proof = base.strict_load(base.regular(output / 'prices-proof.json'))
        if proof['identity'] != identity or proof['bundleSha256'] != base.digest(base.regular(output / 'bundle-v2.json')):
            raise ValueError('prices_completed_changed')
        completed = base.strict_load(base.regular(output / 'bundle-v2.json'))['marketEnrichment']['seriesCompanyPrices']
        for row in completed['rounds']:
            for cid, archived in row['prices'].items():
                if prices.snapshot(cid, row['cutoff'], archived['sources'], output) != archived:
                    raise ValueError('prices_completed_raw_changed')
        return {**proof, 'reusedCompletedRun': True, 'newPaidCalls': 0}
    base.write_once(output / 'prices-execution.json', base.canonical(identity))
    lock = output / '.prices.lock'
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        # Keep originals immutable. No symlink traversal or overwrite of a completed archive.
        for file in baseline.rglob('*'):
            if file.is_symlink():
                raise ValueError('prices_baseline_symlink')
            if file.is_file() and file.name != 'bundle-v2.json':
                target = output / file.relative_to(baseline)
                base.private_dir(target.parent)
                if not target.exists():
                    os.link(file, target)
        ids = sorted({t['companyId'] for r in rows for t in r['frozen']['targets']})
        receipts = prices.collect(ids, output, transport or prices.market.transport, start=bounds[0], end=bounds[1])
        completed = []
        for original_row in rows:
            row = {'roundId': original_row['roundId'], 'cutoff': original_row['cutoff'],
                   'companyResultVersion': original_row['resultVersion'], 'recordedAt': base.now(),
                   'prices': {t['companyId']: prices.snapshot(t['companyId'], original_row['cutoff'], receipts[t['companyId']], output)
                              for t in original_row['frozen']['targets']}}
            row['resultVersion'] = 'company-prices-v1-' + base.digest(base.canonical(row))
            completed.append(row)
        layer['seriesCompanyPrices'] = {**identity, 'rounds': completed}
        base.write_once(output / 'bundle-v2.json', base.canonical(bundle))
        proof = {'identity': identity, 'originalFileSha256': base.digest(original),
                 'bundleSha256': base.digest(base.regular(output / 'bundle-v2.json')), 'newPaidCalls': 0,
                 'companyCount': len(ids), 'rounds': [{'roundId': r['roundId'], 'prices': {
                     cid: {'status': p['status'], 'reason': p['reason'], 'comparisonStatus': p['comparisonStatus']}
                     for cid, p in r['prices'].items()}} for r in completed]}
        base.write_once(output / 'prices-proof.json', base.canonical(proof))
        return proof
    finally:
        lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('baseline', 'output', 'authorization-ref'):
        p.add_argument('--' + flag, required=True)
    return p


if __name__ == '__main__':
    print(base.canonical(run(parser().parse_args())).decode(), flush=True)
