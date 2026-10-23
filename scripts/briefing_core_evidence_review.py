#!/usr/bin/env python3
"""Revalidate a completed bundle under semantic eligibility without changing AI decisions."""
from pathlib import Path
import argparse
import briefing_grouped_rounds as G
import briefing_semantic_support as S
import briefing_grouped_recovery_run as recovery
B = G.base


def review(bundle_path):
    path = Path(bundle_path)
    bundle = B.strict_load(B.regular(path))
    archive = B.strict_load(B.regular(path.parent / 'grouped-issues.json'))
    G.require(B.digest(B.regular(path.parent / 'grouped-issues.json')) == bundle['groupArchiveSha256'], 'review_archive_binding')
    support = S.load(archive, path.parent)
    result = {'policy': S.POLICY, 'sourceBundleSha256': B.digest(B.regular(path)),
              'selectionReexecuted': False, 'newPaidCalls': 0, 'rounds': []}
    history = []
    for r in bundle['rounds']:
        old = G.build_grouped_candidates(archive, r)
        new = S.apply(old, support)
        allowed_old = G.selection_schema(old, r['identity'].get('publicationCompanyIds'))['properties']['selected']
        allowed_new = G.selection_schema(new, r['identity'].get('publicationCompanyIds'))['properties']['selected']
        def ids(schema):
            items = schema['items']
            return {v['properties']['issueId']['enum'][0] for v in items.get('anyOf', [])} if 'anyOf' in items else set(items['properties']['issueId']['enum']) - {'__no_candidate__'}
        answer, receipt = recovery.reply(path.parent / 'calls', r['groupedSelectionRequestDigest'])
        G.require(receipt in r['receipts'], 'review_selection_receipt_binding')
        # Validate the unchanged actual completed choice under the new schema.
        G.freeze_grouped_selection(answer, new, 'review-only-not-a-provider-input', history)
        selected = {i['issueId'] for i in r['selected']}
        rows = []
        for c in new:
            assessment = answer['assessments'][c['issueId']]
            evidence, companies = G._catalog(c)
            chars = sum(len(evidence[e]['quote']) for e in c['newEvidenceIds'])
            rows.append({'issueId': c['issueId'], 'title': c['title'], 'quoteCharacters': chars,
                'semanticSupported': S.eligible(c), 'wasAllowed': c['issueId'] in ids(allowed_old),
                'isAllowed': c['issueId'] in ids(allowed_new), 'importance': assessment['importance'],
                'status': assessment['status'], 'reason': assessment['reason'], 'selected': c['issueId'] in selected,
                'companyIds': sorted(companies), 'supportRequestDigests': sorted(set(c['semanticSupport'].values()))})
        result['rounds'].append({'roundId': r['roundId'], 'date': r['date'], 'edition': r['edition'],
            'selectedCount': len(selected), 'selected': sorted(selected), 'candidates': rows,
            'newlyAllowed': sorted(ids(allowed_new) - ids(allowed_old)), 'selectionRequestDigest': r['groupedSelectionRequestDigest']})
        history.extend(r['selected'])
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--bundle', required=True); p.add_argument('--output', required=True)
    args = p.parse_args(); value = review(args.bundle)
    B.write_once(Path(args.output), B.canonical(value))
    print(B.canonical({**{k: v for k, v in value.items() if k != 'rounds'}, 'rounds': [
        {k: v for k, v in r.items() if k != 'candidates'} for r in value['rounds']]}).decode())
