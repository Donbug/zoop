#!/usr/bin/env python3
"""Prepare read-only display fragments from a completed local result archive. No DB/network writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3


def prepare(scope, payload, raw_sha):
    if scope not in ('common', 'personal'):
        raise ValueError('unknown scope')
    key = scope + 'Priority'
    priority = payload[key]
    def reject_private_keys(value):
        if isinstance(value, dict):
            if set(value).intersection({'prompt', 'providerResponse', 'responseBody', 'requestBody',
                                        'authorization', 'headers', 'memberId', 'userId', 'email'}):
                raise ValueError('non-display metadata in priority fragment')
            for child in value.values():
                reject_private_keys(child)
        elif isinstance(value, list):
            for child in value:
                reject_private_keys(child)
    reject_private_keys(priority)
    if priority['roundId'] != payload['id'] or priority['cutoff'] != payload['dataAsOf']:
        raise ValueError('round binding mismatch')
    refs = {'eventIds': set(), 'companyIds': set(), 'evidenceIds': set()}
    for item in priority['items']:
        refs['eventIds'].add(item['issueId'])
        refs['companyIds'].update(c['companyId'] for c in item['connections' if scope == 'personal' else 'companies'])
        refs['evidenceIds'].update(s['evidenceId'] for s in item['sources'])
    fragment = {key: priority}
    if scope == 'common' and 'text' in payload.get('marketSummary', {}):
        summary = payload['marketSummary']
        saved_evidence = payload.get('summaryEvidence')
        evidence = summary.get('evidenceIds') or (saved_evidence.get('evidenceIds') if isinstance(saved_evidence, dict) else None)
        # Some archives keep summary citations as a list rather than inside marketSummary.
        if not evidence:
            evidence = [s['evidenceId'] for s in saved_evidence] if isinstance(saved_evidence, list) else []
        if not evidence:
            raise ValueError('summary citations are required')
        refs['evidenceIds'].update(evidence)
        fragment['prioritySummary'] = {
            'schemaVersion': 'briefing-priority-summary-v1', 'roundId': payload['id'],
            'cutoff': payload['dataAsOf'], 'resultVersion': summary['resultVersion'],
            'text': summary['text'], 'evidenceIds': sorted(set(evidence)),
        }
    return {
        'schemaVersion': 'briefing-priority-transfer-v1', 'scope': scope,
        'roundId': payload['id'], 'cutoff': payload['dataAsOf'], 'sourcePayloadSha256': raw_sha,
        'destination': 'briefing_rounds.public_snapshot' if scope == 'common' else 'briefing_personal_deliveries.result_snapshot.presentation',
        'fragment': fragment, 'requiredReferences': {k: sorted(v) for k, v in refs.items()},
        'memberBindingRequired': scope == 'personal', 'publicationReady': False,
        'pendingChecks': ['current_document_and_graph_authority', 'original_publication_binding',
                          *(['frozen_member_delivery_and_complete_candidate_pool'] if scope == 'personal' else [])],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-sqlite', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.input_sqlite.resolve(strict=True)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT scope,day,edition,payload,sha256 FROM round_results ORDER BY day,edition,scope').fetchall()
    output = []
    for scope, day, edition, raw, saved_sha in rows:
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        if digest != saved_sha:
            raise ValueError('archive payload digest mismatch')
        payload = json.loads(raw)
        if payload['date'] != day or payload['edition'] != edition:
            raise ValueError('archive slot mismatch')
        output.append(prepare(scope, payload, digest))
    # A transfer fragment is not a publication; do not overwrite any existing file.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        args.output.chmod(0o600)
        for value in output:
            f.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(json.dumps({'records': len(output), 'publicationReady': False, 'sourceUnchanged': True}))


if __name__ == '__main__':
    main()
