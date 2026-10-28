#!/usr/bin/env python3
"""Add independently checked short reading and archived cutoff prices, preserving the full outlook."""
import argparse
import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location('_reading_company', Path(__file__).with_name('briefing_company_outlook.py'))
company = importlib.util.module_from_spec(spec)
spec.loader.exec_module(company)
spec = importlib.util.spec_from_file_location('_reading_prices', Path(__file__).with_name('briefing_company_prices.py'))
prices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prices)
base = company.base
VERSION = 'company-reading-v1'
SCHEMA = 'zoop-company-reading-v1'
V2 = 'company-reading-v2'
SCHEMA_V2 = 'zoop-company-reading-v2'
CARD = 'company-card-v1'
SCHEMA_CARD = 'zoop-company-card-v1'
CARD_QUALITY = ('concise', 'distinctRoles', 'qualifiersPreserved', 'noUnsupportedClaim')
QUALITY = ('specificity', 'newInformation', 'continuity', 'nonRepetition')


def freeze(row, version=VERSION):
    company.require(version in (VERSION, V2, CARD), 'reading_version')
    return {'schemaVersion': SCHEMA_CARD if version == CARD else SCHEMA_V2 if version == V2 else SCHEMA, 'roundId': row['roundId'], 'edition': row['edition'], 'cutoff': row['cutoff'],
            'companyResultVersion': row['resultVersion'], 'draft': row['draft'], 'targets': row['frozen']['targets'],
            'sources': row['frozen']['sources']}


def schema(frozen):
    def s(length):
        value = company.statement(sorted(frozen['sources']))
        value['properties']['text']['maxLength'] = length
        return value
    v2 = frozen.get('schemaVersion', SCHEMA) == SCHEMA_V2
    card = frozen.get('schemaVersion') == SCHEMA_CARD
    fields = {'topic': s(12), 'title': s(32), 'description': s(64)} if card else {'brief': s(140), 'fact': s(160), 'watch': s(180), 'background': s(240), 'change': s(180)} if v2 else {'brief': s(70), 'watch': s(50), 'change': s(60)}
    item = company.obj({'companyId': {'type': 'string', 'enum': [t['companyId'] for t in frozen['targets']]},
                        **fields})
    count = len(frozen['targets'])
    return company.obj({'companies': {'type': 'array', 'items': item, 'minItems': count, 'maxItems': count}})


def validate(draft, frozen):
    base.validate_schema(draft, schema(frozen))
    expected = {t['companyId']: t for t in frozen['targets']}
    company.require({c['companyId'] for c in draft['companies']} == set(expected), 'reading_coverage')
    card = frozen.get('schemaVersion') == SCHEMA_CARD
    if frozen.get('schemaVersion', SCHEMA) == SCHEMA_V2 or card:
        for key in (('title',) if card else ('brief', 'watch')):
            normalized = [c[key]['text'].translate(str.maketrans('', '', ' \t\r\n')) for c in draft['companies']]
            company.require(len(set(normalized)) == len(normalized), 'reading_repeated_' + key)
    for c in draft['companies']:
        for key in (('topic', 'title', 'description') if card else ('brief', 'fact', 'watch', 'background', 'change') if frozen.get('schemaVersion', SCHEMA) == SCHEMA_V2 else ('brief', 'watch', 'change')):
            s = c[key]
            company.require(set(s['evidenceIds']) <= set(expected[c['companyId']]['sourceIds']), 'reading_foreign_source')
            company.require(len(s['evidenceIds']) == len(set(s['evidenceIds'])), 'reading_duplicate_source')


def verification_schema(frozen):
    value = company.verification_schema(frozen)
    card = frozen.get('schemaVersion') == SCHEMA_CARD
    if frozen.get('schemaVersion', SCHEMA) == SCHEMA_V2 or card:
        item = value['properties']['checks']['items']
        item['properties']['quality'] = company.obj({k: {'type': 'boolean'} for k in (CARD_QUALITY if card else QUALITY)})
        item['required'].append('quality')
    return value


def assess(client, frozen, initial_attempts=None, card_prompt_version=CARD):
    attempts = list(initial_attempts or [])
    card = frozen.get('schemaVersion') == SCHEMA_CARD
    company.require(not card or len(attempts) <= 4, 'card_attempt_limit')
    prefix = 'company_card_' if card else 'company_reading_'
    limit = 2000 if card else 5000
    for _ in range(2):
        repair = attempts[-1] if attempts else None
        if card and repair is not None:
            repair = {'previousAttempt': repair, 'guidance': '제목은 자연스러운 짧은 사건 명사구로 다시 작성하세요. 날짜·금액을 모두 담으려 자르거나 조사를 남기지 마세요. 부차적인 효력 날짜는 제목에서 통째로 생략할 수 있습니다. 날짜를 유지한다면 예정·목표 상태를 반드시 포함하세요. 주제와 설명도 각각 검증하세요.'}
        data = {'frozen': frozen, 'repair': repair}
        gs = schema(frozen)
        gd = client.request_digest(prefix + 'generation', data, 'generation.md', 'unused', limit, gs)
        draft = client.call(prefix + 'generation', data, 'generation.md', 'unused', limit, gs)
        try:
            validate(draft, frozen)
        except (ValueError, base.ReplayError) as error:
            attempts.append({'draft': draft, 'generationRequestDigest': gd, 'error': str(error), **({'promptVersion': card_prompt_version} if card else {})})
            continue
        vs = verification_schema(frozen)
        data = {'frozen': frozen, 'draft': draft}
        vd = client.request_digest(prefix + 'verification', data, 'verification.md', 'unused', limit, vs)
        verified = client.call(prefix + 'verification', data, 'verification.md', 'unused', limit, vs)
        base.validate_schema(verified, vs)
        ids = [c['companyId'] for c in verified['checks']]
        company.require(len(ids) == len(set(ids)) and set(ids) == {t['companyId'] for t in frozen['targets']}, 'reading_verification_coverage')
        attempts.append({'draft': draft, 'generationRequestDigest': gd, 'verificationRequestDigest': vd, 'verification': verified, **({'promptVersion': card_prompt_version} if card else {})})
        if all(c['supported'] and (frozen.get('schemaVersion', SCHEMA) not in (SCHEMA_V2, SCHEMA_CARD) or all(c['quality'].values())) for c in verified['checks']):
            return {'status': 'PASS', 'draft': draft, 'attempts': attempts,
                    'generationRequestDigest': gd, 'verificationRequestDigest': vd}
    return {'status': 'WITHHELD', 'draft': None, 'attempts': attempts}


def run(args, transport=None):
    version = getattr(args, 'prompt_version', VERSION)
    company.require(version in (VERSION, V2), 'reading_version')
    baseline, output = Path(args.baseline).resolve(), Path(args.output).resolve()
    company.require(baseline != output and baseline not in output.parents and output not in baseline.parents, 'reading_separate_output')
    base.private_dir(output)
    identity = {'baselineSha256': base.digest(base.regular(baseline / 'bundle-v2.json')),
                'pricesSha256': base.digest(base.regular(Path(args.prices).resolve() / 'receipts.json')) if args.prices else None,
                'authorizationRef': args.authorization_ref, 'runId': args.run_id, 'maximumPaidCalls': args.max_calls,
                'promptArtifacts': {p.name: base.digest(base.regular(p)) for p in sorted(company.context.PROMPTS.with_name(version).iterdir()) if p.is_file()}}
    if version != VERSION: identity['promptVersion'] = version
    identity_file = output / 'reading-execution.json'
    if (output / 'reading-proof.json').exists():
        company.require(identity_file.exists() and base.strict_load(base.regular(identity_file)) == identity, 'reading_request_identity_changed')
        proof = base.strict_load(base.regular(output / 'reading-proof.json'))
        company.require(proof['bundleSha256'] == base.digest(base.regular(output / 'bundle-v2.json')), 'reading_completed_changed')
        return {**proof, 'newPaidCalls': 0, 'reusedCompletedRun': True}
    bundle = base.strict_load(base.regular(baseline / 'bundle-v2.json'))
    series = 'seriesCompanyOutlooks' in bundle.get('marketEnrichment', {})
    layer = bundle['marketEnrichment'] if series else bundle['presentationEnrichment']
    if series: company.require(not args.prices, 'series_reading_price_connection_separate')
    else: company.require(bool(args.prices), 'reading_prices_required')
    company.require(('seriesCompanyReading' if series else 'companyReadingLayer') not in layer, 'reading_layer_exists')
    rows = layer['seriesCompanyOutlooks' if series else 'companyOutlookLayer']['rounds']
    company.require(len(rows) <= 4 and all(r['status'] == 'PASS' for r in rows), 'reading_valid_company_inputs')
    prior = len(list((baseline / 'calls').glob('*.pending.json')))
    plan = {'priorReservations': prior, 'minimumNewCalls': len(rows) * 2,
            'maximumNewCalls': min(args.max_calls - prior, len(rows) * 4), 'maximumTotalCalls': args.max_calls}
    if not args.execute:
        return {**plan, 'newPaidCalls': 0}
    company.require(prior + 2 * len(rows) <= args.max_calls <= 512, 'reading_call_limit')
    lock = output / '.reading-execution.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        base.write_once(identity_file, base.canonical(identity))
        for file in baseline.rglob('*'):
            if file.is_file() and file.name != 'bundle-v2.json':
                target = output / file.relative_to(baseline)
                base.private_dir(target.parent)
                if not target.exists():
                    os.link(file, target)
        price_root = Path(args.prices).resolve() if args.prices else None
        price_receipts = base.strict_load(base.regular(price_root / 'receipts.json')) if price_root else {}
        base.private_dir(output / 'company-prices')
        for file in (price_root / 'company-prices').iterdir() if price_root else []:
            target = output / 'company-prices' / file.name
            if not target.exists():
                os.link(file, target)
        prompts = company.context.PROMPTS.with_name(version)
        client = company.context.legacy.MarketSummaryClient(output, transport or base.authenticated_transport(Path(args.key_file), timeout=600),
                                                          args.max_calls, prompt_root=prompts)
        completed = []
        for row in rows:
            frozen = freeze(row, version)
            path = output / 'reading-rounds' / (row['roundId'] + '.json')
            if path.exists():
                result = base.strict_load(base.regular(path))
                company.require(result['frozen'] == frozen, 'reading_resume_changed')
            else:
                result = assess(client, frozen)
                result.update(roundId=row['roundId'], cutoff=row['cutoff'], frozen=frozen, generatedAt=base.now())
                if series: result['pricePolicy'] = 'not_connected'
                else: result['prices'] = {t['companyId']: prices.snapshot(t['companyId'], row['cutoff'], price_receipts[t['companyId']], output) for t in frozen['targets']}
                result['resultVersion'] = ('reading-v2-' if version == V2 else 'reading-v1-') + base.digest(base.canonical(result))
                base.private_dir(path.parent)
                base.write_once(path, base.canonical(result))
            completed.append(result)
            print(base.canonical({'roundId': row['roundId'], 'status': result['status'], 'newCalls': len(client.new_calls)}).decode(), flush=True)
        owned = {a[k] for r in completed for a in r['attempts'] for k in ('generationRequestDigest', 'verificationRequestDigest') if k in a}
        receipts = [r for r in client.receipts() if r['requestDigest'] in owned]
        if not series:
            layer['maximumPaidCallsIncludingPrior'] = args.max_calls
            layer['runId'] = args.run_id
        layer['seriesCompanyReading' if series else 'companyReadingLayer'] = {'schemaVersion': SCHEMA_CARD if version == CARD else SCHEMA_V2 if version == V2 else SCHEMA, 'authorizationRef': args.authorization_ref,
                                        'rounds': completed, 'receipts': receipts}
        base.write_once(output / 'bundle-v2.json', base.canonical(bundle))
        proof = {**plan, 'status': 'COMPLETE', 'pass': sum(r['status'] == 'PASS' for r in completed),
                 'newPaidCalls': len(client.new_calls), 'totalReservations': len(list(client.calls.glob('*.pending.json'))),
                 'bundleSha256': base.digest(base.regular(output / 'bundle-v2.json')),
                 'inputTokens': sum(r['inputTokens'] for r in receipts if r['usageKnown'] and r['requestDigest'] in client.new_calls),
                 'outputTokens': sum(r['outputTokens'] for r in receipts if r['usageKnown'] and r['requestDigest'] in client.new_calls)}
        base.write_once(output / 'reading-proof.json', base.canonical(proof))
        return proof
    finally:
        lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('baseline', 'output', 'authorization-ref', 'run-id'):
        p.add_argument('--' + flag, required=True)
    p.add_argument('--prices', help='Archived prices for legacy presentation mode; series short reading keeps prices separate')
    p.add_argument('--prompt-version', choices=[VERSION, V2], default=V2)
    p.add_argument('--key-file')
    p.add_argument('--max-calls', type=int, default=400)
    p.add_argument('--execute', action='store_true')
    return p


if __name__ == '__main__':
    print(base.canonical(run(parser().parse_args())).decode(), flush=True)
