"""Carry previous verified conditions, without inferring outcomes or calling AI.

History is an explicit finite set of recorded rounds, not a claim of complete
publication history. Every round is re-projected against verified call receipts.
"""
import copy
from datetime import datetime
from briefing_issue_intelligence_view import project


def _time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('followup_timezone_required')
    return parsed


def _authenticate(bundle):
    response = bundle['response']
    expected = project(response['preservedPublication']['response'],
                       bundle['frozen'], bundle['recorded'], bundle['calls'])['response']
    for key in ('id', 'date', 'edition', 'dataAsOf', 'items', 'issueIntelligence',
                'preservedPublication'):
        if response[key] != expected[key]:
            raise ValueError('followup_projection_changed:' + key)
    model = expected['issueIntelligence']
    if (_time(model['cutoff']) != _time(expected['dataAsOf']) or
            any(model[k] != expected[k] for k in ('date', 'edition'))):
        raise ValueError('followup_round_binding')
    return expected


def attach_followups(current, history):
    """Bundles contain response/frozen/recorded/calls (verified_calls output).

    Pair identity is exact issueId + companyId; titles and companies alone never
    merge events. Repeated identical conditions use the latest authenticated
    origin. Different conditions remain, even when a newer analysis omits them.
    Current selected pairs remain in their issue cards, separately from this list.
    """
    response = _authenticate(current)
    cutoff = _time(response['dataAsOf'])
    prior = [_authenticate(bundle) for bundle in history]
    rounds = {response['id']}
    times = {cutoff}
    for old in prior:
        when = _time(old['dataAsOf'])
        if old['id'] in rounds or when in times:
            raise ValueError('followup_ambiguous_round')
        if when >= cutoff:
            raise ValueError('followup_future_round')
        rounds.add(old['id'])
        times.add(when)
    prior.sort(key=lambda old: _time(old['dataAsOf']))
    selected = {(i['issueId'], c['companyId'])
                for i in response['issueIntelligence']['issues'] for c in i['companies']}
    retained = {}
    reviewed_rounds = []
    for old in prior:
        model = old['issueIntelligence']
        origin = {key: model[key] for key in
                  ('roundId', 'date', 'edition', 'cutoff', 'resultVersion')}
        reviewed_rounds.append(origin)
        for issue in model['issues']:
            item = next(i for i in old['items'] if i['eventId'] == issue['issueId'])
            for company in issue['companies']:
                pair = (issue['issueId'], company['companyId'])
                if pair in selected:
                    continue
                name = next(c['name'] for c in item['companies'] if c['id'] == pair[1])
                for condition in company['conditions']:
                    if not condition['text'].strip() or not condition['evidenceIds']:
                        raise ValueError('followup_missing_condition')
                    sources = []
                    for eid in condition['evidenceIds']:
                        if eid not in company['sourceIds']:
                            raise ValueError('followup_foreign_source')
                        source = issue['sources'][eid]
                        if _time(source['publishedAt']) > _time(model['cutoff']):
                            raise ValueError('followup_future_source')
                        sources.append(source)
                    retained[(*pair, condition['text'].strip())] = {
                        'issueId': pair[0], 'companyId': pair[1],
                        'title': item['title'], 'companyName': name,
                        'status': 'outcome_unverified', 'origin': origin,
                        'condition': condition, 'sources': sources,
                    }
    result = copy.deepcopy(current['response'])
    result['issueFollowUps'] = copy.deepcopy({
        'schemaVersion': 'issue-followups-v1', 'roundId': response['id'],
        'baseResultVersion': response['issueIntelligence']['resultVersion'],
        'cutoff': response['dataAsOf'], 'scope': 'provided_verified_rounds',
        'reviewedRounds': reviewed_rounds, 'entries': list(retained.values()),
    })
    return result
