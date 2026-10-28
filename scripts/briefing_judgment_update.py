#!/usr/bin/env python3
"""A separately audited judgment update; preserve selected items and original analyses."""
import argparse
import copy
import os
from pathlib import Path
import briefing_company_outlook as company
base = company.base
VERSION = 'judgment-update-v1'
SCHEMA = 'zoop-judgment-update-v1'
QUALITY = ('factsSupported', 'materialConditionsPreserved', 'previousJudgmentFaithful', 'interpretationBounded', 'cardsMatchConclusion')


def schema(frozen, phase='generation'):
    if phase == 'verification':
        return company.obj({**{k: {'type': 'boolean'} for k in QUALITY}, 'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1600}})
    def s(n):
        v = company.statement(sorted(frozen['sources']))
        v['properties']['text']['maxLength'] = n
        return v
    item = company.obj({'companyId': {'type': 'string', 'enum': [t['companyId'] for t in frozen['targets']]},
        'decision': {'type': 'string', 'enum': ['initial', 'maintained', 'strengthened', 'weakened', 'unassessable']},
        'newEvidence': s(500), 'reason': s(500), 'strengthenIf': s(240), 'weakenIf': s(240),
        'topic': s(12), 'title': s(32), 'description': s(64)})
    return company.obj({'conclusion': s(420), 'industryChange': s(700),
        'companies': {'type': 'array', 'items': item, 'minItems': len(frozen['targets']), 'maxItems': len(frozen['targets'])},
        'limits': s(500)})


def freeze(current, previous, metadata):
    company.require(current['status'] == previous['status'] == 'PASS', 'judgment_pass_inputs')
    now, before = company.context.legacy._aware(current['cutoff']), company.context.legacy._aware(previous['cutoff'])
    company.require(before < now, 'judgment_previous_clock')
    # Only the immediate edition-bound reference, never an arbitrary older same-company judgment.
    from datetime import date, timedelta
    company.require((current['edition'] == 'evening' and previous['edition'] == 'morning' and current['date'] == previous['date']) or
        (current['edition'] == 'morning' and previous['edition'] == 'evening' and
         date.fromisoformat(previous['date']) == date.fromisoformat(current['date']) - timedelta(days=1)), 'judgment_previous_edition')
    sources, targets = {}, {}
    for row, role in ((current, 'selected'), (previous, 'watch')):
        for t in row['frozen']['targets']:
            cid = t['companyId']
            if cid not in targets:
                old = next((c for c in previous['draft']['companies'] if c['companyId'] == cid), None)
                targets[cid] = {'companyId': cid, 'companyName': t['companyName'], 'role': role, 'sourceIds': [],
                    'previousJudgment': old, 'previousResultVersion': previous['resultVersion'] if old else None}
            for sid in t['sourceIds']:
                saved = row['frozen']['sources'][sid]
                doc = metadata[saved['documentId']]
                body = doc['body']
                company.require(base.digest(body.encode()) == saved['bodySha256'] == doc['bodySha256'], 'judgment_full_body_digest')
                company.require(saved['quote'] in body and 0 < len(body) <= 24000, 'judgment_full_body_or_truncation')
                company.require(company.context.legacy._aware(saved['publishedAt']) <= now, 'judgment_future_source')
                value = {**saved, 'fullBody': body}
                company.require(sid not in sources or sources[sid] == value, 'judgment_source_conflict')
                sources[sid] = value
                if sid not in targets[cid]['sourceIds']: targets[cid]['sourceIds'].append(sid)
    company.require(0 < len(targets) <= 6, 'judgment_target_count')
    return {'schemaVersion': SCHEMA, 'roundId': current['roundId'], 'date': current['date'], 'edition': current['edition'],
        'cutoff': current['cutoff'], 'companyResultVersion': current['resultVersion'],
        'previousRoundId': previous['roundId'], 'previousResultVersion': previous['resultVersion'], 'previousCutoff': previous['cutoff'],
        'previousDraft': previous['draft'], 'targets': list(targets.values()), 'sources': sources,
        'scopeNote': '원발행 시각 기준 과거 시뮬레이션입니다. 늦게 수집한 보존 원문을 사용하며 당시 본문 동일성은 입증하지 않습니다. 산업 해석과 같은 기업의 이전 판단을 구분합니다.'}


def validate(draft, frozen):
    base.validate_schema(draft, schema(frozen))
    expected = {t['companyId']: t for t in frozen['targets']}
    company.require({c['companyId'] for c in draft['companies']} == set(expected), 'judgment_coverage')
    def check(s, allowed):
        refs = s['evidenceIds']
        company.require(len(set(refs)) == len(refs) and set(refs) <= set(allowed), 'judgment_foreign_evidence')
    for k in ('conclusion', 'industryChange', 'limits'): check(draft[k], frozen['sources'])
    for c in draft['companies']:
        t = expected[c['companyId']]
        if t['previousJudgment'] is None:
            company.require(c['decision'] in ('initial', 'unassessable'), 'judgment_invented_previous')
        if t['role'] == 'watch': company.require(c['decision'] in ('maintained', 'unassessable'), 'judgment_watch_without_update')
        for k in ('newEvidence', 'reason', 'strengthenIf', 'weakenIf', 'topic', 'title', 'description'): check(c[k], t['sourceIds'])



def apply_editorial(row, review):
    """Explicit source review; never label edited copy as independently model-verified."""
    company.require(row['status'] == 'PASS' and review['reviewer'] == 'codex' and
        review['modelVerificationAppliesTo'] == 'pre_edit_draft' and
        review['frozenSha256'] == base.digest(base.canonical(row['frozen'])), 'judgment_editorial_identity')
    company.require(company.context.legacy._aware(review['reviewedAt']) >= company.context.legacy._aware(row['generatedAt']) and review['reason'].strip(), 'judgment_editorial_clock')
    draft = copy.deepcopy(row['draft']); seen = set()
    for change in review['changes']:
        cid, field = change['companyId'], change['field']
        company.require((cid, field) not in seen, 'judgment_editorial_duplicate'); seen.add((cid, field))
        if cid is None:
            company.require(field in ('conclusion', 'industryChange', 'limits'), 'judgment_editorial_scope')
            target = draft
        else:
            company.require(field in ('topic', 'title', 'description', 'newEvidence', 'reason', 'strengthenIf', 'weakenIf'), 'judgment_editorial_scope')
            target = next(c for c in draft['companies'] if c['companyId'] == cid)
        company.require(target[field] == change['before'], 'judgment_editorial_before')
        target[field] = copy.deepcopy(change['after'])
    validate(draft, row['frozen'])
    return draft


def assess(client, frozen):
    data = {'frozen': frozen}
    gs = schema(frozen)
    gd = client.request_digest('judgment_update_generation', data, 'generation.md', 'unused', 6500, gs)
    draft = client.call('judgment_update_generation', data, 'generation.md', 'unused', 6500, gs)
    try: validate(draft, frozen)
    except (ValueError, base.ReplayError) as exc:
        return {'status': 'WITHHELD', 'draft': None, 'attempts': [{'draft': draft, 'generationRequestDigest': gd, 'error': str(exc)}]}
    data = {'frozen': frozen, 'draft': draft}; vs = schema(frozen, 'verification')
    vd = client.request_digest('judgment_update_verification', data, 'verification.md', 'unused', 2500, vs)
    verification = client.call('judgment_update_verification', data, 'verification.md', 'unused', 2500, vs)
    base.validate_schema(verification, vs)
    passed = all(verification[k] for k in QUALITY)
    attempt = {'draft': draft, 'generationRequestDigest': gd, 'verificationRequestDigest': vd, 'verification': verification}
    return {'status': 'PASS' if passed else 'WITHHELD', 'draft': draft if passed else None, 'attempts': [attempt]}


def run(args, transport=None):
    baseline, output = Path(args.baseline).resolve(), Path(args.output).resolve()
    company.require(baseline != output and baseline not in output.parents and output not in baseline.parents, 'judgment_separate_output')
    raw = base.regular(baseline / 'bundle-v2.json'); bundle = base.strict_load(raw)
    source_raw = base.regular(Path(args.sources))
    company.require(base.digest(source_raw) == bundle['sourceFileSha256'], 'judgment_sources_digest')
    metadata = {d['documentId']: d for d in (base.strict_load(line) for line in source_raw.splitlines() if line.strip())}
    layer = bundle['presentationEnrichment']; company.require('judgmentUpdateLayer' not in layer, 'judgment_layer_exists')
    rows = layer['companyOutlookLayer']['rounds']; current = next(r for r in rows if r['roundId'] == args.round_id)
    before = [r for r in rows if company.context.legacy._aware(r['cutoff']) < company.context.legacy._aware(current['cutoff'])]
    company.require(before, 'judgment_previous_missing')
    previous = max(before, key=lambda r: company.context.legacy._aware(r['cutoff']))
    frozen = freeze(current, previous, metadata); prompts = company.context.PROMPTS.with_name(VERSION)
    identity = {'baselineSha256': base.digest(raw), 'frozenSha256': base.digest(base.canonical(frozen)),
        'authorizationRef': args.authorization_ref, 'runId': args.run_id, 'maximumPaidCalls': args.max_calls,
        'promptArtifacts': {p.name: base.digest(base.regular(p)) for p in sorted(prompts.iterdir())}}
    prior = len(list((baseline / 'calls').glob('*.pending.json')))
    if not args.execute: return {**identity, 'status': 'OFFLINE', 'minimumNewCalls': 2, 'maximumNewCalls': 2, 'priorReservations': prior}
    base.private_dir(output)
    if (output / 'judgment-proof.json').exists():
        company.require(base.strict_load(base.regular(output / 'judgment-execution.json')) == identity, 'judgment_identity_changed')
        proof = base.strict_load(base.regular(output / 'judgment-proof.json'))
        company.require(proof['bundleSha256'] == base.digest(base.regular(output / 'bundle-v2.json')), 'judgment_completed_changed')
        return {**proof, 'newPaidCalls': 0, 'reusedCompletedRun': True}
    company.require(prior + 2 <= args.max_calls <= 512, 'judgment_call_limit')
    lock = output / '.judgment-execution.lock'; fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    try:
        base.write_once(output / 'judgment-execution.json', base.canonical(identity))
        for file in baseline.rglob('*'):
            if file.is_file() and file.name not in ('bundle-v2.json', 'judgment-execution.json', 'judgment-proof.json'):
                target = output / file.relative_to(baseline); base.private_dir(target.parent)
                if not target.exists(): os.link(file, target)
        client = company.context.legacy.MarketSummaryClient(output, transport or base.authenticated_transport(Path(args.key_file), timeout=600), args.max_calls, prompt_root=prompts)
        finished = output / 'judgment-round.json'
        if finished.exists():
            result = base.strict_load(base.regular(finished)); company.require(result['frozen'] == frozen, 'judgment_resume_changed')
        else:
            result = assess(client, frozen)
            result.update(roundId=current['roundId'], frozen=frozen, generatedAt=base.now())
            result['resultVersion'] = 'judgment-v1-' + base.digest(base.canonical(result))
            base.write_once(finished, base.canonical(result))
        owned = {a[k] for a in result['attempts'] for k in ('generationRequestDigest', 'verificationRequestDigest') if k in a}
        layer['judgmentUpdateLayer'] = {'schemaVersion': SCHEMA, 'authorizationRef': args.authorization_ref,
            'rounds': [result], 'receipts': [r for r in client.receipts() if r['requestDigest'] in owned]}
        layer['maximumPaidCallsIncludingPrior'] = args.max_calls
        base.write_once(output / 'bundle-v2.json', base.canonical(bundle))
        proof = {**identity, 'status': result['status'], 'roundId': current['roundId'], 'previousRoundId': previous['roundId'],
            'newPaidCalls': len(client.new_calls), 'bundleSha256': base.digest(base.regular(output / 'bundle-v2.json'))}
        base.write_once(output / 'judgment-proof.json', base.canonical(proof)); return proof
    finally: lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'output', 'sources', 'round-id', 'authorization-ref', 'run-id'): p.add_argument('--' + name, required=True)
    p.add_argument('--max-calls', type=int, default=400); p.add_argument('--key-file'); p.add_argument('--execute', action='store_true')
    return p

if __name__ == '__main__': print(base.canonical(run(parser().parse_args())).decode(), flush=True)
