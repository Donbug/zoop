#!/usr/bin/env python3
"""Prepare source/price-bound v5 AI requests offline. No key, transport or execution option."""
import argparse
import copy
from pathlib import Path
import briefing_company_outlook as company

base = company.base
VERSION = 'company-outlook-v5'
PROMPTS = company.PROMPTS.with_name(VERSION)


def require(ok, reason):
    company.require(ok, 'price_prompt_' + reason)


def freeze(response):
    r, p = response['editionReview'], response['companyPriceContext']
    aware = company.context.legacy._aware
    cutoff = aware(r['cutoff'])
    require(response['id'] == r['roundId'] == p['roundId'] and r['resultVersion'] == p['reviewVersion']
            and r['date'] == p['date'] and r['edition'] == p['edition'] and aware(p['cutoff']) == cutoff, 'round_binding')
    sources = copy.deepcopy(r['sources'])
    require(all(aware(s['publishedAt']) <= cutoff for s in sources.values()), 'future_source')
    prices = {c['companyId']: c for c in p['companies']}
    require(len(prices) == len(p['companies']) == len(r['companies'])
            and set(prices) == {c['companyId'] for c in r['companies']}, 'company_coverage')
    targets = []
    for c in r['companies']:
        price = prices[c['companyId']]
        require(aware(price['cutoff']) == cutoff and set(c['sourceIds']) <= set(sources), 'company_binding')
        fields = ['companyId', 'status', 'currency', 'provider', 'cutoff', 'responseSha256s']
        if price['status'] == 'available':
            require(aware(price['latest']['observedAt']) <= cutoff, 'future_price')
            require(price['currency'] == ('KRW' if c['companyId'].startswith('KRX:') else 'USD'), 'currency')
            fields += ['sessionDate', 'exchangeTimezone', 'completeSession', 'barCount', 'latest', 'day']
        else:
            require(price['status'] == 'unavailable', 'price_status'); fields += ['reason']
        movement = {k: copy.deepcopy(price[k]) for k in fields}
        if price['status'] == 'available':
            movement['news'] = []
            for n in price['news']:
                require(n['evidenceId'] in c['sourceIds'] and n['evidenceId'] in sources
                        and aware(n['publishedAt']) == aware(sources[n['evidenceId']]['publishedAt']) <= cutoff, 'news_binding')
                require(n['before'] is None or aware(n['before']['observedAt']) <= aware(n['publishedAt']), 'pre_news_clock')
                movement['news'].append({k: copy.deepcopy(n[k]) for k in (
                    'evidenceId', 'publishedAt', 'timing', 'status', 'postNewsBars', 'before', 'changeRatePercent')})
            movement['sinceMorning'] = {k: copy.deepcopy(v) for k, v in price['sinceMorning'].items() if k != 'observation'}
        previous = {'status': 'unavailable', 'reason': 'comparable_previous_company_review_missing'}
        if c['previous'] is not None:
            prev = r['previousReview']
            require(prev is not None and aware(prev['cutoff']) < cutoff
                    and prev['edition'] == ('morning' if r['edition'] == 'evening' else 'evening')
                    and (r['edition'] != 'evening' or prev['date'] == r['date']), 'previous_clock')
            previous = {k: copy.deepcopy(prev[k]) for k in ('roundId', 'date', 'edition', 'cutoff', 'resultVersion')}
            previous.update(status='available', kind='preserved_editorial_review', judgment=copy.deepcopy(c['previous']))
        targets.append({'companyId': c['companyId'], 'companyName': c['companyName'], 'role': c['role'],
            'sourceIds': list(c['sourceIds']), 'previous': previous, 'observedMovement': movement,
            'facts': [{'text': sources[sid]['quote'], 'evidenceIds': [sid]} for sid in c['newInformation']['evidenceIds']]})
    market = copy.deepcopy(p.get('marketReference', {'status': 'unavailable', 'indicators': [], 'note': 'not_supplied'}))
    for i in market['indicators']:
        require(i['observedDate'] <= cutoff.astimezone(company.context.legacy.KST).date().isoformat()
                and (i['observedAt'] is None or aware(i['observedAt']) <= cutoff)
                and (i['baselineDate'] is None or i['baselineDate'] < i['observedDate']), 'market_clock')
        i.pop('text', None)
    # Only numerical observations and actual article data are supplied. The prior
    # deterministic outlook/interpretation/summary is deliberately excluded.
    frozen = {'schemaVersion': company.SCHEMA, 'promptVersion': VERSION, 'comparisonContract': 'edition-bound-v2',
        **{k: r[k] for k in ('roundId', 'date', 'edition', 'cutoff')}, 'targets': targets, 'sources': sources,
        'marketReference': market, 'priceContextVersion': p['resultVersion'], 'reviewVersion': r['resultVersion'],
        'scopeNote': '과거 원발행 시각 기준 재생 입력. 가격은 사후 수집 관측이며 뉴스 인과·예측 적중을 입증하지 않는다.'}
    frozen['inputSha256'] = base.digest(base.canonical(frozen))
    return frozen


def run(args):
    source, output = Path(args.responses).resolve(), Path(args.output).resolve()
    require(source != output and source not in output.parents and output not in source.parents, 'separate_output')
    rows = []
    for path in source.glob('2026-*-*.json'):
        raw = base.regular(path); response = base.strict_load(raw)
        rows.append((freeze(response), base.digest(raw)))
    rows.sort(key=lambda pair: company.context.legacy._aware(pair[0]['cutoff']))
    require(0 < len(rows) <= 4 and len({r['roundId'] for r, _ in rows}) == len(rows), 'round_count')
    base.private_dir(output)
    proofs = []
    for frozen, response_sha in rows:
        data = {'frozen': frozen, 'repair': None}
        encoded, _, prompt_sha = company.context.legacy.prepare_market_request(
            PROMPTS, 'company_price_outlook_generation', data, 'generation.md', 'unused', 8000, company.generation_schema(frozen))
        prefix = output / (frozen['date'] + '-' + frozen['edition'])
        base.write_once(prefix.with_suffix('.input.json'), base.canonical(frozen))
        base.write_once(prefix.with_suffix('.request.json'), encoded)
        proofs.append({'roundId': frozen['roundId'], 'responseSha256': response_sha, 'inputSha256': frozen['inputSha256'],
                       'requestSha256': base.digest(encoded), 'requestBytes': len(encoded), 'promptSha256': prompt_sha,
                       'companies': len(frozen['targets'])})
    for path in PROMPTS.iterdir(): base.write_once(output / path.name, base.regular(path))
    proof = {'status': 'PREPARED_ONLY', 'promptVersion': VERSION, 'model': base.MODEL, 'rounds': proofs,
             'minimumFutureCalls': 2 * len(rows), 'maximumFutureCallsWithOneRepair': 4 * len(rows),
             'paidCalls': 0, 'newSourceRequests': 0, 'previousPolicy': 'preserved_editorial_review',
             'note': '생성 요청 준비만 완료. 실제 검증 요청에는 새 초안이 필요하며 새 AI 결과/화면 반영은 아직 없다.'}
    base.write_once(output / 'prepared-proof.json', base.canonical(proof)); return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--responses', required=True); parser.add_argument('--output', required=True)
    print(base.canonical(run(parser.parse_args())).decode())
