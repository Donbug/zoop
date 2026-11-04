"""Business-view schemas matching common-impact-relative-v1 / personal-impact-relative-v3.

No provider, DB or filesystem mutations. Stored older prose is never relabelled.
"""
import copy
import re
from datetime import datetime
import briefing_replay as b

COMMON = 'common-impact-relative-v1'
PERSONAL = 'personal-impact-relative-v3'
SUMMARY = 'common-round-relative-v1'
BASE_FIELDS = ('direction', 'keyPoint', 'confirmedFact', 'businessImpact', 'outlook',
               'positive', 'negative', 'priceObservation', 'previousChange', 'nextCheck',
               'directionReason', 'directionConfidence', 'effectSizeStatus')


def require(value, code):
    if not value:
        raise ValueError(code)


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def statement(ids, limit=500, minimum=1):
    return obj({'text': {'type': 'string', 'minLength': minimum, 'maxLength': limit},
                'evidenceIds': {'type': 'array', 'items': {'type': 'string', 'enum': sorted(ids)},
                                'minItems': 1, 'maxItems': len(ids)}})


def aware(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(value.tzinfo is not None, 'priority_timezone_required')
    return value


def generation_schema(frozen, scope):
    require(scope in ('common', 'personal'), 'priority_scope')
    issues, all_ids = {}, set()
    for issue in frozen['issues']:
        companies = {}; all_ids.update(issue['sources'])
        for target in issue['targets']:
            ids = target['evidenceIds']; previous = copy.deepcopy(statement(ids))
            statuses = ['unavailable'] if target['previous']['status'] != 'available' else ['maintained', 'strengthened', 'weakened', 'unavailable']
            if scope == 'common' and issue['kind'] in ('related_reference', 'previous_issue'):
                statuses = [s for s in statuses if s in ('maintained', 'unavailable')]
            previous['properties']['status'] = {'type': 'string', 'enum': statuses}; previous['required'].append('status')
            price = {'type': 'null'}
            if target['frozenPrice']['status'] == 'available':
                price = {'anyOf': [obj({'text': {'type': 'string', 'minLength': 1, 'maxLength': 500},
                    'companyId': {'type': 'string', 'enum': [target['companyId']]},
                    'observedAt': {'type': 'string', 'enum': [target['frozenPrice']['latest']['observedAt']]}}), {'type': 'null'}]}
            companies[target['companyId']] = obj({
                'direction': {'type': 'string', 'enum': ['positive', 'negative', 'mixed', 'watch']},
                'keyPoint': statement(ids, 180), 'confirmedFact': statement(ids), 'businessImpact': statement(ids),
                'companyConnection' if scope == 'common' else 'forMyStocks': statement(ids),
                'outlook': statement(ids, minimum=20),
                'positive': {'anyOf': [statement(ids, 250), {'type': 'null'}]},
                'negative': {'anyOf': [statement(ids, 250), {'type': 'null'}]},
                'priceObservation': price, 'previousChange': previous, 'nextCheck': statement(ids),
                'directionReason': statement(ids), 'directionConfidence': {'type': 'string', 'enum': ['limited', 'moderate', 'high']},
                'effectSizeStatus': {'type': 'string', 'enum': ['unquantified', 'quantified'] if target.get('effectSizeEvidence') else ['unquantified']}})
        issues[issue['issueId']] = obj({'headline': statement(issue['sources'], 65),
            'topicTag': {'type': 'string', 'minLength': 1, 'maxLength': 12},
            'subline': statement(issue['sources'], 100), 'companies': obj(companies)})
    return obj({'overview': statement(all_ids, 350), 'issues': obj(issues)})


def verification_schema(frozen, scope):
    check = obj({'supported': {'type': 'boolean'}, 'reason': {'type': 'string', 'minLength': 1, 'maxLength': 500}})
    fields = (*BASE_FIELDS, 'companyConnection' if scope == 'common' else 'forMyStocks')
    return obj({'overview': copy.deepcopy(check), 'issues': obj({issue['issueId']: obj({
        **{field: copy.deepcopy(check) for field in ('headline', 'topicTag', 'subline', 'eventScope')},
        'companies': obj({target['companyId']: obj({field: copy.deepcopy(check) for field in fields}) for target in issue['targets']})
    }) for issue in frozen['issues']})})


def korean_prose(value):
    """Reject foreign-script spill in newly generated prose; source quotes remain untouched."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('text', 'topicTag') and isinstance(item, str):
                require(not re.search(r'[\u3040-\u30ff]|[\u4e00-\u9fff]{5,}', item), 'priority_foreign_script_spill')
            else:
                korean_prose(item)
    elif isinstance(value, list):
        for item in value:
            korean_prose(item)


def validate(draft, frozen, scope):
    b.validate_schema(draft, generation_schema(frozen, scope)); korean_prose(draft)
    cutoff = aware(frozen['cutoff'])
    for issue in frozen['issues']:
        for source in issue['sources'].values():
            require(aware(source['publishedAt']) <= cutoff, 'priority_future_source')
        for target in issue['targets']:
            company = draft['issues'][issue['issueId']]['companies'][target['companyId']]
            ids = set(target['evidenceIds']); require(ids and ids <= set(issue['sources']), 'priority_target_evidence')
            for value in company.values():
                if isinstance(value, dict) and 'evidenceIds' in value:
                    refs = value['evidenceIds']; require(len(set(refs)) == len(refs) and set(refs) <= ids, 'priority_foreign_evidence')
            if company['direction'] != 'watch':
                required = ('positive', 'negative') if company['direction'] == 'mixed' else (company['direction'],)
                require(all(company[k] is not None for k in required), 'priority_direction_without_pathway')
            if company['effectSizeStatus'] == 'quantified':
                size = target.get('effectSizeEvidence')
                require(isinstance(size, dict) and size.get('text') and size.get('evidenceIds') and set(size['evidenceIds']) <= ids,
                        'priority_unproved_effect_size')
            previous = target['previous']
            if previous['status'] != 'available':
                require(company['previousChange']['status'] == 'unavailable', 'priority_invented_previous')
            else:
                require(previous['issueId'] == issue['issueId'] and previous['companyId'] == target['companyId']
                        and aware(previous['cutoff']) < cutoff, 'priority_previous_identity')


def failures(answer, frozen, scope):
    b.validate_schema(answer, verification_schema(frozen, scope)); failed = []
    if not answer['overview']['supported']: failed.append('overview')
    for issue in frozen['issues']:
        iid = issue['issueId']; checked = answer['issues'][iid]
        for field in ('headline', 'topicTag', 'subline', 'eventScope'):
            if not checked[field]['supported']: failed.append(iid + ':' + field)
        for target in issue['targets']:
            cid = target['companyId']
            for field, check in checked['companies'][cid].items():
                if not check['supported']: failed.append(iid + ':' + cid + ':' + field)
    return failed


SUMMARY_FIELDS = ('headline', 'roundAssessment', 'judgmentChange', 'nextSessionOutlook', 'nextChecks')


def summary_schema(frozen):
    return obj({'headline': statement(frozen['references'], 90), 'roundAssessment': statement(frozen['references'], 600),
        'judgmentChange': statement(frozen['references'], 600), 'nextSessionOutlook': statement(frozen['references'], 600),
        'nextChecks': {'type': 'array', 'items': statement(frozen['references'], 250), 'minItems': 1, 'maxItems': 4}})


def summary_verification_schema(frozen):
    check = obj({'supported': {'type': 'boolean'}, 'reason': {'type': 'string', 'minLength': 1, 'maxLength': 500}})
    return obj({field: copy.deepcopy(check) for field in SUMMARY_FIELDS})
