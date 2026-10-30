"""Compile ALL receipt-bound round candidates into an immutable DB input. No AI/network transport.

Registry is a private operator export of existing article-version/grant bindings, never published.
SQL output targets a separate DB; it cannot update a publication or feedback row.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import briefing_issue_intelligence as intelligence
import briefing_issue_intelligence_view as view


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def compile_pool(frozen, row, calls, registry, previous_id=None):
    intelligence.check_seal(frozen)
    assessed, checked, proof = view.reuse_candidate_assessments(frozen, row, calls)
    intelligence.validate_assessments(assessed, frozen)
    intelligence.base.validate_schema(checked, intelligence.verification_schema([c['issueId'] for c in frozen['candidates']]))
    passed = {p['issueId']: p for p in row['passed']}
    for p in passed.values():
        view.prove_issue(p, calls)
    candidates = []
    for c in frozen['candidates']:
        iid = c['issueId']; a = assessed['assessments'][iid]
        sources = []
        for sid, s in c['sources'].items():
            bound = registry.get((s['documentId'], 'sha256-' + s['bodySha256']))
            if bound is None:
                # Retain the whole assessed pool; current access checks will exclude this source.
                bound = {'documentId': s['documentId'], 'documentVersion': 'sha256-' + s['bodySha256'],
                         'bodySha256': s['bodySha256'], 'grantId': '', 'grantRevision': '', 'recipients': []}
            if bound['bodySha256'] != s['bodySha256']:
                raise ValueError('source_version_changed:' + iid)
            sources.append({**copy.deepcopy(s), **copy.deepcopy(bound), 'quoteVerified': True})
        companies = []
        for link in c['companies']:
            relation = next(r for r in a['relations'] if r['companyId'] == link['companyId'])
            companies.append({'companyId': link['companyId'], 'name': link['name'],
                'directness': relation['directness'], 'reason': relation['basis']['text'],
                'evidenceIds': relation['basis']['evidenceIds'], 'nextCheck': None})
        analysis, next_check = None, None
        if iid in passed:
            draft = passed[iid]['draft']
            analysis = '\n'.join(t['outlook']['text'] for t in draft['companies'])
            checks = []
            for t in draft['companies']:
                conditions = [c['text'] for c in t['conditions']]
                checks.extend(conditions)
                for relation in companies:
                    if relation['companyId'] == t['companyId']: relation['nextCheck'] = '\n'.join(conditions) or None
            next_check = '\n'.join(checks) or None
        candidates.append({'issueId': iid, 'eventKey': iid, 'title': passed[iid]['draft']['headline']['text'] if iid in passed else c['title'], 'importance': a['businessImportance'],
            'informationChange': a['informationChange'], 'verified': checked['checks'][iid]['supported'],
            'whyImportant': a['whyImportant']['text'], 'whyNow': a['whyNow']['text'],
            'companies': companies, 'sources': sources, 'analysis': analysis, 'nextCheck': next_check})
    version = hashlib.sha256(canonical({'frozen': frozen['inputSha256'], 'assessments': assessed, 'checks': checked, 'compilerVersion': 'personal-pool-compiler-v2', 'candidates': candidates})).hexdigest()
    return {'schemaVersion': 'personal-candidate-pool-v1', 'roundId': frozen['roundId'], 'cutoff': frozen['cutoff'],
        'scope': frozen['scope'], 'complete': True, 'candidateCount': len(candidates), 'candidates': candidates,
        'inputSha256': version, 'selectionPolicyVersion': frozen['policyVersion'], 'previousRoundId': previous_id,
        'proof': {'sourceInputSha256': frozen['inputSha256'], 'baselineResponseSha256': frozen['baselineResponseSha256'],
                  'receipts': proof, 'newAiCalls': 0}}


def sql(pool):
    text = canonical(pool).decode(); digest = hashlib.sha256(text.encode()).hexdigest()
    tag = '$personal_' + digest[:16] + '$'
    return ("INSERT INTO briefing_personal_pools(id,round_id,input_sha256,snapshot,snapshot_sha256)\n"
            f"SELECT 'personal-{digest}',p->>'roundId',p->>'inputSha256',p,encode(sha256(convert_to(p::text,'UTF8')),'hex')\n"
            f"FROM (SELECT {tag}{text}{tag}::jsonb || jsonb_build_object('publicationPayloadSha256',r.payload_sha256) p "
            f"FROM briefing_rounds r WHERE r.id='{pool['roundId'].replace(chr(39), chr(39)*2)}' "
            "AND r.status='published' AND r.published_at IS NOT NULL) v ON CONFLICT(id) DO NOTHING;\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--executed', type=Path, required=True)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    registry = {(r['documentId'], r['documentVersion']): r for r in json.loads(args.registry.read_text())}
    calls = view.verified_calls(args.executed)
    frozen = [json.loads(f.read_text()) for f in args.prepared.glob('*.input.json')]
    frozen.sort(key=lambda r: intelligence.aware(r['cutoff']))
    args.output.mkdir(parents=True, exist_ok=True)
    previous = None; summary = []
    for f in frozen:
        name = f['date'] + '-' + f['edition']; row = json.loads((args.executed / (name + '.json')).read_text())
        # Only attach a truly adjacent predecessor. Never jump over a missing/held round.
        prior_id = previous['roundId'] if previous and intelligence.aware(previous['cutoff']) == intelligence.aware(f['window']['from']) else None
        pool = compile_pool(f, row, calls, registry, prior_id)
        dest = args.output / (name + '.sql')
        if dest.exists(): raise ValueError('output_exists')
        dest.write_text(sql(pool)); (args.output / (name + '.json')).write_bytes(canonical(pool))
        summary.append({'roundId': f['roundId'], 'candidateCount': len(pool['candidates']), 'inputSha256': pool['inputSha256']})
        previous = f
    print(json.dumps({'status': 'COMPILED_OFFLINE', 'newAiCalls': 0, 'rounds': summary}, ensure_ascii=False))

if __name__ == '__main__': main()
