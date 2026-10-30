"""Issue-first selection, using recorded judgments without calling a model.

No company quota, price-magnitude score, or inferred business sentiment. Old
assessment importance is an explicitly labelled compatibility input; a policy
change must never masquerade as new factual evidence.
"""
VERSION = 'issue-selection-policy-v1'


def order(choices, assessments):
    # NEW_EVENT and MATERIAL_UPDATE are equally eligible new information.
    # Reconfirmation/re-reporting is excluded by the existing evidence gates.
    # Legacy priority mixes editorial signals, so it is NOT a business score.
    return sorted(choices, key=lambda c: (-assessments[c['issueId']]['importance'], c['issueId']))


def evidence_keys(sources):
    # Same publisher document may contain independent events. Identical exact
    # support cannot become two headline events merely by changing its ID/title.
    return {(s['documentId'], s['bodySha256'], s['quote']) for s in sources}


def audit(choice, assessment, candidate, cutoff):
    review = candidate.get('freshnessReview')
    return {'version': VERSION, 'cutoff': cutoff,
        'businessImportance': assessment['importance'],
        'importanceBasis': 'recorded_importance_not_a_new_business_assessment',
        'whyImportant': assessment['reason'],
        'whyNow': {'decision': choice['novelty'], 'deltaEvidenceIds': choice['deltaEvidenceIds'],
                   'review': review},
        'companyQuota': None, 'legacyPriorityUsed': False,
        'priceSignal': {'status': 'not_used', 'value': None,
                        'reason': 'no_independent_comparable_issue_price_signal'},
        'relationSignal': {'status': 'context_only', 'reason': 'cited_company_links_not_centrality_score'},
        'tieBreak': 'stable_issue_id', 'changeKind': 'policy_replay_not_new_facts'}
