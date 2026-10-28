"""Add reviewed reading metadata without rewriting model output or source IDs.

Grouping is an explicit editorial decision with exact source bindings. Equal
companies/documents alone never imply the same event. No model/network calls.
"""
import copy


def annotate(response, recorded_round, groups=()):
    model = response['issueIntelligence']
    assert recorded_round['round']['roundId'] == response['id'], 'round_mismatch'
    assert model['roundId'] == response['id'], 'model_round_mismatch'
    selected = {s['issueId']: s for s in recorded_round['selection']['selected']}
    issues = {i['issueId']: i for i in model['issues']}
    reading = {'schemaVersion': 'issue-reading-review-v1', 'roundId': response['id'],
               'baseResultVersion': model['resultVersion'], 'cutoff': model['cutoff'],
               'groups': [], 'issues': []}
    for iid, issue in issues.items():
        record = selected[iid]
        assert recorded_round['selectionVerification']['checks'][iid]['supported'], 'unverified_selection'
        assessment = recorded_round['assessments']['assessments'][iid]
        assert record['assessment'] == assessment, 'selection_assessment_changed'
        item = next(i for i in response['items'] if i['eventId'] == iid)
        assert item['reason'] == assessment['whyImportant']['text'] + ' ' + assessment['whyNow']['text'], 'projected_reason_changed'
        def supported(statement, company_id=None):
            assert statement['text'].strip() and statement['evidenceIds'], 'empty_statement'
            for eid in statement['evidenceIds']:
                original = issue['sources'][eid]
                old = record['candidate']['sources'][eid]
                assert all(original[k] == old[k] for k in ('documentId', 'bodySha256', 'quote')), 'source_changed'
                if company_id:
                    company = next(c for c in issue['companies'] if c['companyId'] == company_id)
                    assert eid in company['sourceIds'], 'foreign_company_source'
            return copy.deepcopy(statement)
        connections = []
        for relation in assessment['relations']:
            link = next(c for c in record['candidate']['companies'] if c['companyId'] == relation['companyId'])
            role = (link.get('role') or '').lower()
            # Sort by recorded event role, never by company name or general centrality.
            position = ('unconfirmed' if relation['directness'] == 'unconfirmed' else
                        'primary' if relation['directness'] == 'direct' and role in
                        {'manufacturer', 'issuer', 'declaring company', 'producer', 'operator', 'supplier'} else 'related')
            connections.append({'companyId': relation['companyId'], 'position': position,
                                'basis': supported(relation['basis'], relation['companyId'])})
        reading['issues'].append({'issueId': iid,
            'whyImportant': supported(assessment['whyImportant']), 'whyNow': supported(assessment['whyNow']),
            'priceUsedForRanking': bool(record['priceSignal'].get('usedForRanking')),
            'connections': connections})
    used = set()
    for group in groups:
        assert len(group['issueIds']) >= 2 and len(set(group['issueIds'])) == len(group['issueIds']), 'group_members'
        assert group['title'].strip() and group['reason'].strip(), 'group_reason'
        assert not used.intersection(group['issueIds']), 'overlapping_groups'
        used.update(group['issueIds'])
        bound = []
        for iid in group['issueIds']:
            for eid, source in issues[iid]['sources'].items():
                bound.append({'issueId': iid, 'evidenceId': eid,
                    **{k: source[k] for k in ('documentId', 'bodySha256', 'quote')}})
        reading['groups'].append({**copy.deepcopy(group), 'support': bound})
    result = copy.deepcopy(response)
    result['issueReading'] = reading
    return result
