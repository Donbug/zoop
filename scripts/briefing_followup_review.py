"""Project a recorded editorial review of saved sources, with no model calls.

The reviewer, not this module, checks semantic entailment and event identity.
The module enforces receipts, exact conditions, source integrity, chronology and
completion evidence. A plan, price move or another event cannot complete a task.
The projection is separate from the original publication and AI assessments.
"""
import copy
import hashlib
import json

from briefing_issue_followups import attach_followups, _time


def condition_ref(entry):
    return copy.deepcopy({k: entry[k] for k in
                          ('issueId', 'companyId', 'origin', 'condition')})


def _key(ref):
    return json.dumps(ref, sort_keys=True, ensure_ascii=False)


def attach_review(current, history, review, documents):
    response = attach_followups(current, history)
    base = response['issueFollowUps']
    if any(review[k] != base[k] for k in ('roundId', 'baseResultVersion', 'cutoff')):
        raise ValueError('review_round_binding')
    _time(review['reviewedAt'])
    expected = {_key(condition_ref(e)): e for e in base['entries']}
    seen = set()
    output = []
    for entry in review['entries']:
        key = _key(entry['ref'])
        if key not in expected or key in seen:
            raise ValueError('review_condition_binding')
        seen.add(key)
        origin = _time(entry['ref']['origin']['cutoff'])
        sources = {}
        for evidence in entry['sources']:
            doc = documents[evidence['documentId']]
            digest = hashlib.sha256(doc['body'].encode()).hexdigest()
            if digest != doc['bodySha256'] or digest != evidence['bodySha256']:
                raise ValueError('review_source_hash')
            if doc['timestampVerified'] is not True or doc['historicalVersionExcluded']:
                raise ValueError('review_source_clock')
            published = _time(doc['publishedAt'])
            if published > _time(base['cutoff']):
                raise ValueError('review_future_source')
            start, end = evidence['start'], evidence['end']
            if (type(start) is not int or type(end) is not int or
                    not 0 <= start < end <= len(doc['body']) or
                    doc['body'][start:end] != evidence['quote'] or not evidence['quote'].strip()):
                raise ValueError('review_quote_span')
            if evidence['id'] in sources:
                raise ValueError('review_duplicate_source')
            if evidence['relation'] not in ('same_event', 'related_event') or evidence['kind'] not in (
                    'plan', 'completed_action', 'background'):
                raise ValueError('review_evidence_kind')
            sources[evidence['id']] = {
                **copy.deepcopy(evidence),
                **{k: doc[k] for k in ('title', 'url', 'publishedAt')},
                'period': 'after_condition' if published > origin else 'prior_background',
            }
        if not entry['summary'].strip() or not entry['requirements']:
            raise ValueError('review_empty')
        for fact in entry['facts']:
            if not fact['text'].strip() or not fact['sourceIds'] or not set(fact['sourceIds']) <= sources.keys():
                raise ValueError('review_fact_source')
        completed = True
        for requirement in entry['requirements']:
            if not requirement['text'].strip() or requirement['observation'] not in ('unverified', 'completed'):
                raise ValueError('review_requirement')
            if not set(requirement['sourceIds']) <= sources.keys():
                raise ValueError('review_requirement_source')
            if requirement['observation'] == 'unverified':
                completed = False
                continue
            if not requirement['sourceIds'] or not all(
                    sources[s]['kind'] == 'completed_action' and
                    sources[s]['relation'] == 'same_event' and
                    sources[s]['period'] == 'after_condition'
                    for s in requirement['sourceIds']):
                raise ValueError('review_completion_evidence')
        output.append({**copy.deepcopy(entry), 'sources': list(sources.values()),
                       'status': 'fulfilled' if completed else 'insufficient_evidence'})
    if seen != expected.keys():
        raise ValueError('review_incomplete_conditions')
    response['issueFollowUpReview'] = {
        'schemaVersion': 'issue-followup-review-v1',
        'method': 'recorded_editorial_review',
        **{k: review[k] for k in ('roundId', 'baseResultVersion', 'cutoff', 'reviewedAt')},
        'entries': output,
    }
    return response
