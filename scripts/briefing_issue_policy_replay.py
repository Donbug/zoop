#!/usr/bin/env python3
"""Offline policy comparison and issue/company input preparation. No transport/key option.

This reuses only the recorded selected proposals; it cannot invent assessments
for omitted candidates or certify a new AI result. Outputs are write-once and
must be kept outside the original bundle directory.
"""
import argparse
import importlib.util
from pathlib import Path


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


grouped = load_module('briefing_grouped_rounds')
company = load_module('briefing_company_outlook')
base = grouped.base


def replay(bundle, metadata):
    effective = {r['roundId']: r for r in bundle.get('briefingRecovery', {}).get('rounds', [])}
    presentations = {r['roundId']: r for r in bundle['presentationEnrichment']['rounds']}
    history = bundle['presentationEnrichment']['companyOutlookLayer']['rounds']
    rows = []
    for original in bundle['rounds']:
        r = effective.get(original['roundId'], original)
        selected = r['selected']
        proposals = [{'issueId': s['issueId'], 'title': s['title'],
            'evidenceIds': [v['evidenceId'] for v in s['sources']],
            'companyIds': [v['companyId'] for v in s['companyLinks']],
            'novelty': s['novelty'][0]['decision'], 'deltaEvidenceIds': s['novelty'][0]['deltaEvidenceIds'],
            'limitations': s['limitations']} for s in selected]
        assessments = {s['issueId']: {'importance': s['importance'], 'priority': s['score'],
            'status': 'SELECTABLE', 'reason': s['reason'], 'scope': s['scope'],
            'affectedSectors': s['affectedSectors'], 'transmission': s['transmission']} for s in selected}
        candidates = [s['frozenGroupedIssueSnapshot'] for s in selected]
        # Keep the original decision lineage for novelty checks. Do not feed this
        # policy replay back into the historical publication/AI receipt chain.
        prior = [s for past in bundle['rounds'] if past['identity']['window']['to'] < original['identity']['window']['to']
                 for s in effective.get(past['roundId'], past)['selected']]
        after = grouped.freeze_grouped_selection({'selected': proposals, 'assessments': assessments},
            candidates, original['identitySha256'], prior, grouped.issue_policy.VERSION) if candidates else []
        prepared = company.freeze_issue_inputs(presentations[r['roundId']], r, metadata, history,
            version='company-outlook-v4') if selected else []
        before_context = next((h for h in history if h['roundId'] == r['roundId']), None)
        rows.append({'roundId': r['roundId'], 'date': r['date'], 'edition': r['edition'],
            'before': [s['issueId'] for s in selected], 'after': [s['issueId'] for s in after],
            'selected': after, 'preparedIssueInputs': prepared,
            'companyOnlyPreviousCount': sum(t['previous']['status'] == 'available' for t in before_context['frozen']['targets']) if before_context else 0,
            'issueCompanyPreviousCount': sum(t['previous']['status'] == 'available' for f in prepared for t in f['targets']),
            'originalResultSha256': r.get('resultSha256'),
            'preservedTracking': [{'issueIds': t.get('issueIds', []), 'companyId': t['companyId'],
                'roundId': h['roundId'], 'conditions': c['conditions']}
                for h in history if h['status'] == 'PASS' and h['cutoff'] < presentations[r['roundId']]['marketEnrichment']['cutoff']
                for t in h['frozen']['targets'] for c in h['draft']['companies'] if t['companyId'] == c['companyId']]})
    return {'policyVersion': grouped.issue_policy.VERSION, 'newPaidCalls': 0,
        'scope': 'recorded_selected_proposals_only', 'unselectedCandidatesReassessed': False,
        'resultMeaning': 'offline_policy_comparison_not_new_model_validation_or_publication', 'rounds': rows}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    original, output = args.bundle.resolve(), args.output.resolve()
    grouped.require(original.parent != output and original.parent not in output.parents
        and output not in original.parents, 'separate_replay_output_required')
    raw, source = base.regular(original), base.regular(args.sources)
    bundle = base.strict_load(raw)
    grouped.require(base.digest(source) == bundle['sourceFileSha256'], 'source_digest')
    metadata = {r['documentId']: r for r in (base.strict_load(line) for line in source.decode().splitlines() if line.strip())}
    result = replay(bundle, metadata)
    result.update(originalBundleSha256=base.digest(raw), sourceSha256=base.digest(source))
    base.private_dir(output)
    base.write_once(output / 'policy-comparison.json', base.canonical(result))
    grouped.require(base.regular(original) == raw and base.regular(args.sources) == source, 'original_changed')
    print(base.canonical({'rounds': len(result['rounds']), 'newPaidCalls': 0,
        'orderChanged': sum(r['before'] != r['after'] for r in result['rounds']),
        'beforeComparisons': sum(r['companyOnlyPreviousCount'] for r in result['rounds']),
        'afterComparisons': sum(r['issueCompanyPreviousCount'] for r in result['rounds']),
        'originalsUnchanged': True}).decode())


if __name__ == '__main__':
    main()
