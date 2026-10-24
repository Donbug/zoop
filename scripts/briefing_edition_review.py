#!/usr/bin/env python3
"""Source-bound AM/PM editorial review. No network client, keys or model calls."""
import argparse
import copy
import os
from pathlib import Path
import briefing_company_outlook as company
import briefing_company_prices as prices
base = company.base
SCHEMA = 'zoop-edition-review-v1'
MAX_BODY_CHARS = 100000


def reference(previous, current):
    if previous is None: return None
    from datetime import date, timedelta
    f = previous['frozen']
    bound = ((current['edition'] == 'evening' and f['edition'] == 'morning' and f['date'] == current['date']) or
             (current['edition'] == 'morning' and f['edition'] == 'evening' and date.fromisoformat(f['date']) == date.fromisoformat(current['date']) - timedelta(days=1)))
    if not bound: return None
    return {k: copy.deepcopy(previous[k]) for k in ('resultVersion', 'draft')} | {
        k: f[k] for k in ('roundId', 'date', 'edition', 'cutoff')}


def freeze(current, previous, metadata, market, price_sources, archive):
    import re
    company.require(isinstance(market, str) and re.fullmatch(r'[0-9a-f]{64}', market) is not None, 'edition_market_binding')
    prior = reference(previous, current)
    sources = copy.deepcopy(previous['frozen']['sources']) if prior else {}
    targets = {}
    for t in current['frozen']['targets']:
        cid = t['companyId']
        targets[cid] = {'companyId': cid, 'companyName': t['companyName'], 'role': 'selected',
                        'sourceIds': list(t['sourceIds']), 'previous': None}
    if prior:
        for t in previous['frozen']['targets']:
            cid = t['companyId']
            target = targets.setdefault(cid, {'companyId': cid, 'companyName': t['companyName'], 'role': 'tracked', 'sourceIds': [], 'previous': None})
            target['sourceIds'] = list(dict.fromkeys([*target['sourceIds'], *t['sourceIds']]))
            target['previous'] = copy.deepcopy(next(c for c in prior['draft']['companies'] if c['companyId'] == cid))
    for sid, s in current['frozen']['sources'].items():
        doc = metadata[s['documentId']]; body = doc['body']
        company.require(base.digest(body.encode()) == doc['bodySha256'] == s['bodySha256'] and s['quote'] in body and len(body) <= MAX_BODY_CHARS, 'edition_full_body')
        value = {**s, 'fullBody': body}
        company.require(sid not in sources or sources[sid] == value, 'edition_source_conflict')
        sources[sid] = value
    for s in sources.values(): company.require(company.context.legacy._aware(s['publishedAt']) <= company.context.legacy._aware(current['cutoff']), 'edition_future_source')
    company.require(len(targets) <= 12 and sum(len(s['fullBody']) for s in sources.values()) <= 256000, 'edition_tracking_capacity')
    for cid, t in targets.items():
        company.require(cid in price_sources, 'edition_price_archive_missing')
        t['price'] = prices.snapshot(cid, current['cutoff'], price_sources[cid], archive)
    return {'schemaVersion': SCHEMA, **{k: current[k] for k in ('roundId', 'date', 'edition', 'cutoff')},
        'analysisVersion': current['resultVersion'], 'previousReview': prior,
        'targets': list(targets.values()), 'sources': sources, 'marketSnapshotSha256': market,
        'capabilities': {'intraday': 'unavailable', 'sectors': 'unavailable', 'flows': 'unavailable', 'calendar': 'unverified'},
        'scopeNote': '원발행 시각 기준 과거 시뮬레이션·원문 대조 편집본입니다. 나중에 조회한 보존 자료이며 당시 본문 동일성·주가 인과·예측 적중은 입증하지 않습니다.'}


def schema(frozen):
    def s(length, ids=None):
        allowed = sorted(frozen['sources']) if ids is None else ids
        refs = {'type': 'array', 'items': {'type': 'string', **({'enum': allowed} if allowed else {})}, 'minItems': 0 if ids is None else 1, 'maxItems': 6 if allowed else 0}
        return company.obj({'text': {'type': 'string', 'minLength': 1, 'maxLength': length}, 'evidenceIds': refs})
    ids = [t['companyId'] for t in frozen['targets']]
    item = company.obj({'companyId': {'type': 'string', **({'enum': ids} if ids else {})},
        'stance': {'type': 'string', 'enum': ['priority_watch', 'watch', 'cautious_watch', 'deferred']},
        'title': s(40), 'takeaway': s(100), 'newInformation': s(600), 'judgment': s(600),
        'watch': {'type': 'array', 'items': s(240), 'minItems': 1, 'maxItems': 3},
        'positive': s(300), 'negative': s(300),
        'checks': {'type': 'array', 'items': company.obj({'condition': {'type': 'string', 'minLength': 1, 'maxLength': 240},
            'status': {'type': 'string', 'enum': ['confirmed', 'contradicted', 'not_observed']}, 'observation': s(400)}), 'maxItems': 3}})
    return company.obj({'headline': {'type': 'string', 'minLength': 1, 'maxLength': 120}, 'summary': s(600),
        'marketInterpretation': s(700), 'comparison': s(600), 'nextSession': s(600),
        'companies': {'type': 'array', 'items': item, 'minItems': len(ids), 'maxItems': len(ids)}})


def validate(draft, frozen):
    base.validate_schema(draft, schema(frozen))
    expected = {t['companyId']: t for t in frozen['targets']}
    company.require(len({c['companyId'] for c in draft['companies']}) == len(draft['companies']) and {c['companyId'] for c in draft['companies']} == set(expected), 'edition_company_coverage')
    def refs(statement, allowed, required):
        ids = statement['evidenceIds']
        company.require(len(set(ids)) == len(ids) and set(ids) <= set(allowed) and (bool(ids) or not required), 'edition_evidence')
    for key in ('summary', 'marketInterpretation', 'comparison', 'nextSession'): refs(draft[key], frozen['sources'], False)
    for c in draft['companies']:
        t = expected[c['companyId']]
        for k in ('title', 'takeaway', 'newInformation', 'judgment', 'positive', 'negative'): refs(c[k], t['sourceIds'], True)
        for s in c['watch']: refs(s, t['sourceIds'], True)
        old = [] if t['previous'] is None else [s['text'] for s in t['previous']['watch']]
        company.require([x['condition'] for x in c['checks']] == old, 'edition_previous_condition_coverage')
        company.require(all(x['status'] != 'not_observed' or x['condition'] in {w['text'] for w in c['watch']} for x in c['checks']), 'edition_unresolved_condition_dropped')
        for check in c['checks']:
            refs(check['observation'], t['sourceIds'], check['status'] != 'not_observed')
            if check['status'] != 'not_observed':
                company.require(any(company.context.legacy._aware(frozen['previousReview']['cutoff']) < company.context.legacy._aware(frozen['sources'][sid]['publishedAt']) <= company.context.legacy._aware(frozen['cutoff']) for sid in check['observation']['evidenceIds']), 'edition_no_new_condition_evidence')


def run(args):
    baseline, output = Path(args.baseline).resolve(), Path(args.output).resolve()
    company.require(baseline != output and baseline not in output.parents and output not in baseline.parents, 'edition_separate_output')
    raw = base.regular(baseline / 'bundle-v2.json'); bundle = base.strict_load(raw)
    sources_raw = base.regular(Path(args.sources)); company.require(base.digest(sources_raw) == bundle['sourceFileSha256'], 'edition_source_digest')
    metadata = {r['documentId']: r for r in (base.strict_load(line) for line in sources_raw.splitlines() if line.strip())}
    review_raw = base.regular(Path(args.reviews)); reviews = base.strict_load(review_raw)
    company.require(reviews['author'] == 'codex' and reviews['verificationMode'] == 'editorial_source_review', 'edition_review_mode')
    identity = {'baselineSha256': base.digest(raw), 'reviewsSha256': base.digest(review_raw), 'authorizationRef': args.authorization_ref}
    if (output / 'edition-proof.json').exists():
        proof = base.strict_load(base.regular(output / 'edition-proof.json'))
        company.require(all(proof[k] == v for k, v in identity.items()) and proof['bundleSha256'] == base.digest(base.regular(output / 'bundle-v2.json')), 'edition_resume_identity')
        return {**proof, 'reusedCompletedRun': True}
    layer = bundle['presentationEnrichment']; company.require('editionReviewLayer' not in layer, 'edition_layer_exists')
    rows = layer['companyOutlookLayer']['rounds']; definitions = {r['roundId']: r for r in layer['rounds']}
    company.require(set(reviews['rounds']) == {r['roundId'] for r in rows}, 'edition_review_rounds')
    price_sources = {}
    for row in layer['companyReadingLayer']['rounds']:
        for cid, value in row['prices'].items():
            company.require(cid not in price_sources or price_sources[cid] == value['sources'], 'edition_price_registry_conflict')
            price_sources[cid] = value['sources']
    results = []
    for current in sorted(rows, key=lambda r: company.context.legacy._aware(r['cutoff'])):
        frozen = freeze(current, results[-1] if results else None, metadata, definitions[current['roundId']]['marketEnrichment']['marketSnapshotSha256'], price_sources, baseline)
        draft = reviews['rounds'][current['roundId']]; validate(draft, frozen)
        value = {'status': 'REVIEWED', 'frozen': frozen, 'draft': copy.deepcopy(draft), 'reviewer': reviews['author'], 'verificationMode': reviews['verificationMode'], 'reviewedAt': reviews['reviewedAt']}
        value['resultVersion'] = 'edition-v1-' + base.digest(base.canonical(value)); results.append(value)
    base.private_dir(output); lock = output / '.edition-execution.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    try:
        for file in baseline.rglob('*'):
            if file.is_file() and file.name != 'bundle-v2.json':
                target = output / file.relative_to(baseline); base.private_dir(target.parent)
                if not target.exists(): os.link(file, target)
        layer['editionReviewLayer'] = {'schemaVersion': SCHEMA, 'authorizationRef': args.authorization_ref, 'rounds': results}
        base.write_once(output / 'edition-review-source.json', review_raw)
        base.write_once(output / 'bundle-v2.json', base.canonical(bundle))
        proof = {**identity, 'newPaidCalls': 0, 'rounds': len(results), 'bundleSha256': base.digest(base.regular(output / 'bundle-v2.json'))}
        base.write_once(output / 'edition-proof.json', base.canonical(proof)); return proof
    finally: lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'output', 'sources', 'reviews', 'authorization-ref'): p.add_argument('--' + name, required=True)
    return p
if __name__ == '__main__': print(base.canonical(run(parser().parse_args())).decode(), flush=True)
