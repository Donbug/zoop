#!/usr/bin/env python3
"""Freeze cutoff-bound Toss chart responses for deterministic briefing analysis. No model calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import urllib.parse
import urllib.request
import urllib.error
import briefing_replay as base

SCHEMA = 'zoop-company-price-context-v1'


def transport(url):
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            return r.status, r.read(2_000_001)
    except urllib.error.HTTPError as e:
        return e.code, e.read(2_000_001)


def run(args, fetch=transport):
    source, output = Path(args.baseline).resolve(), Path(args.output).resolve()
    if source == output or source in output.parents or output in source.parents:
        raise base.ReplayError('price_context_separate_output')
    origin = urllib.parse.urlsplit(args.api_base)
    if origin.scheme != 'http' or origin.hostname not in ('127.0.0.1', 'localhost') or origin.path or origin.query or origin.fragment or origin.username:
        raise base.ReplayError('price_context_local_api_required')
    raw = base.regular(source / 'bundle-v2.json'); bundle = base.strict_load(raw)
    presentation = bundle['presentationEnrichment']
    if 'priceContextLayer' in presentation:
        raise base.ReplayError('price_context_layer_exists')
    base.private_dir(output); archive = output / 'price-context-responses'; base.private_dir(archive)
    ledger = output / 'price-context-requests'; base.private_dir(ledger)
    identity = {'baselineSha256': base.digest(raw), 'apiBase': args.api_base,
                'authorizationRef': args.authorization_ref, 'requestNote': args.request_note}
    if getattr(args, 'integrate_outlook', False):
        identity['outlookIntegrationVersion'] = 'zoop-company-price-outlook-v1'
    started = output / 'price-context-started.json'
    if started.exists():
        saved = base.strict_load(base.regular(started))
        if any(saved[k] != v for k, v in identity.items()):
            raise base.ReplayError('price_context_resume_identity')
    else:
        saved = {**identity, 'generatedAt': base.now()}; base.write_once(started, base.canonical(saved))
    rows, requests = [], {}
    for row in presentation['editionReviewLayer']['rounds']:
        f = row['frozen']
        refs = []
        for c in f['targets']:
            pair = {}
            for kind, period in [('daily', '1m'), ('intraday', '1d')]:
                request = {'companyId': c['companyId'], 'period': period, 'cutoff': f['cutoff']}
                key = base.digest(base.canonical(request)); requests[key] = request; pair[kind] = key
            refs.append({'companyId': c['companyId'], **pair})
        rows.append({'roundId': f['roundId'], 'reviewVersion': row['resultVersion'], 'companies': refs})
    if len(requests) > 96:
        raise base.ReplayError('price_context_request_limit')

    existing = {key for key in requests if (ledger / (key + '.json')).exists()}
    completed = len(existing)

    def one(entry):
        key, request = entry
        path = ledger / (key + '.json')
        if path.exists():
            receipt = base.strict_load(base.regular(path))
            if receipt['request'] != request or base.digest(base.regular(archive / (receipt['sha256'] + '.bin'))) != receipt['sha256']:
                raise base.ReplayError('price_context_cache_changed')
            return receipt
        cache = Path(args.reuse) if args.reuse else None
        reuse_path = cache / 'price-context-requests' / (key + '.json') if cache else None
        url = args.api_base + '/api/v1/companies/' + urllib.parse.quote(request['companyId'], safe='') + '/prices?' + urllib.parse.urlencode({'period': request['period'], 'to': request['cutoff']})
        if reuse_path and reuse_path.is_file():
            prior = base.strict_load(base.regular(reuse_path))
            body = base.regular(cache / 'price-context-responses' / (prior['sha256'] + '.bin'))
            if prior['request'] != request or base.digest(body) != prior['sha256']:
                raise base.ReplayError('price_context_reuse_changed')
            status = prior['httpStatus']; provenance = 'saved_api_response'
        else:
            status, body = fetch(url); provenance = 'api_response'
        if len(body) > 2_000_000:
            raise base.ReplayError('price_context_response_limit')
        decoded = base.strict_load(body)
        if status == 200 and decoded.get('companyId') != request['companyId']:
            raise base.ReplayError('price_context_company_mismatch')
        sha = base.digest(body); base.write_once(archive / (sha + '.bin'), body)
        receipt = {'id': key, 'request': request, 'httpStatus': status, 'sha256': sha,
                   'bytes': len(body), 'collectedAt': base.now(), 'provenance': provenance}
        base.write_once(path, base.canonical(receipt)); return receipt

    with ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(pool.map(one, sorted(requests.items())))
    for file in source.rglob('*'):
        if file.is_file() and file.name != 'bundle-v2.json':
            target = output / file.relative_to(source); base.private_dir(target.parent)
            if not target.exists(): os.link(file, target)
    presentation['priceContextLayer'] = {'schemaVersion': SCHEMA, 'authorizationRef': args.authorization_ref,
        'requestNote': args.request_note, 'generatedAt': saved['generatedAt'], 'rounds': rows, 'receipts': receipts}
    if getattr(args, 'integrate_outlook', False):
        presentation['priceContextLayer']['outlookIntegrationVersion'] = identity['outlookIntegrationVersion']
    base.write_once(output / 'bundle-v2.json', base.canonical(bundle))
    proof = {**identity, 'schemaVersion': SCHEMA, 'rounds': len(rows), 'requests': len(receipts),
             'savedResponsesReused': sum(r['provenance'] != 'api_response' for r in receipts),
             'unavailableResponses': sum(r['httpStatus'] != 200 for r in receipts),
             'bundleSha256': base.digest(base.regular(output / 'bundle-v2.json')), 'modelCalls': 0}
    base.write_once(output / 'price-context-proof.json', base.canonical(proof))
    return {**proof, 'completedRequestsReused': completed, 'newRequests': sum(r['id'] not in existing and r['provenance'] == 'api_response' for r in receipts)}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'output', 'api-base', 'authorization-ref', 'request-note'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--reuse')
    p.add_argument('--integrate-outlook', action='store_true', help='Compose source-bound business/price outlook and dated market references; keeps the baseline unchanged')
    return p


if __name__ == '__main__':
    print(base.canonical(run(parser().parse_args())).decode())
