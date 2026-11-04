"""Fresh, receipt-bound business views for the priority read contract. No DB/provider initialization."""
import copy
import briefing_source_time as source_time
from pathlib import Path
import briefing_issue_intelligence as m
import briefing_issue_intelligence_view as receipts
import briefing_priority_contracts as c
b = m.base
VERSION = 'priority-business-producer-v1'
PROMPTS = Path(__file__).resolve().parents[1] / 'docs/prompts' / VERSION
STAGES = {
    'common': ('priority-common', 'priority-common-check', 'common-generation.md', 'common-verification.md'),
    'personal': ('priority-personal', 'priority-personal-check', 'personal-generation.md', 'personal-verification.md'),
}


def priority_input(original):
    m.check_seal(original)
    return m.seal({**copy.deepcopy(original), 'priorityContract': VERSION})


def freeze(inputs, scope):
    c.require(bool(inputs) and len(inputs) <= 3, 'priority_input_count')
    c.require(len({f['issueId'] for f in inputs}) == len(inputs), 'priority_duplicate_issue')
    first = inputs[0]; issues = []
    for f in inputs:
        m.check_seal(f)
        c.require(all(f[k] == first[k] for k in ('roundId', 'date', 'edition', 'cutoff')), 'priority_mixed_rounds')
        for source in f['sources'].values():
            c.require(source_time.available(source) <= c.aware(f['cutoff']), 'priority_future_source')
        assessment = f['selection']['assessment']; targets = []
        for target in f['targets']:
            targets.append({'companyId': target['companyId'], 'name': target['companyName'],
                'evidenceIds': copy.deepcopy(target['sourceIds']), 'connectionReason': next(
                    (r['basis']['text'] for r in assessment['relations'] if r['companyId'] == target['companyId']),
                    assessment['whyImportant']['text']),
                'frozenPrice': copy.deepcopy(target['observedMovement']), 'previous': copy.deepcopy(target['previous'])})
        issues.append({'issueId': f['issueId'], 'title': f['title'],
            'kind': 'core' if assessment['businessImportance'] >= 2 else 'relative_issue',
            'effectScope': 'selected_company_business', 'importance': assessment['businessImportance'],
            'whyImportant': copy.deepcopy(assessment['whyImportant']), 'whyNow': copy.deepcopy(assessment['whyNow']),
            'sources': copy.deepcopy(f['sources']), 'targets': targets})
    return m.seal({'version': c.COMMON if scope == 'common' else c.PERSONAL, 'producerVersion': VERSION,
        **{k: first[k] for k in ('roundId', 'date', 'edition', 'cutoff')}, 'minimumIssues': 1,
        'scope': 'verified_public_issue_company_business', 'issues': issues,
        'sourceInputSha256s': [f['inputSha256'] for f in inputs]})


def _call(client, stage, data, prompt, schema, limit=12000):
    return client.call(stage, data, str(PROMPTS / prompt), 'unused', limit, schema)


def generate(client, inputs, scope):
    frozen = freeze(inputs, scope); gen, check, gp, vp = STAGES[scope]
    draft = _call(client, gen, {'frozen': frozen}, gp, c.generation_schema(frozen, scope))
    c.validate(draft, frozen, scope)
    verified = _call(client, check, {'frozen': frozen, 'draft': draft}, vp, c.verification_schema(frozen, scope))
    failed = c.failures(verified, frozen, scope)
    c.require(not failed, 'priority_semantic_verification_failed')
    record = {'scope': scope, 'frozen': frozen, 'draft': draft, 'verification': verified,
              'promptVersion': c.COMMON if scope == 'common' else c.PERSONAL}
    record['resultVersion'] = record['promptVersion'] + '-' + b.digest(b.canonical(record))
    return record


def prove(record, calls):
    scope = record['scope']; frozen = record['frozen']; draft = record['draft']; checked = record['verification']
    m.check_seal(frozen)
    expected = c.COMMON if scope == 'common' else c.PERSONAL
    c.require(record['promptVersion'] == frozen['version'] == expected and frozen['producerVersion'] == VERSION, 'priority_version_binding')
    c.validate(draft, frozen, scope)
    c.require(not c.failures(checked, frozen, scope), 'priority_unverified_record')
    unsigned = {k: v for k, v in record.items() if k != 'resultVersion'}
    c.require(record['resultVersion'] == record['promptVersion'] + '-' + b.digest(b.canonical(unsigned)), 'priority_record_digest')
    gen, check, _, _ = STAGES[scope]
    generated = [r for r in calls if r.get('priorityBound') and r['stage'] == gen and r['input'] == {'frozen': frozen} and r['answer'] == draft]
    verified = [r for r in calls if r.get('priorityBound') and r['stage'] == check and r['input'] == {'frozen': frozen, 'draft': draft} and r['answer'] == checked]
    c.require(generated and verified and generated[-1]['key'] != verified[-1]['key'], 'priority_model_receipts_missing')
    return {'generationRequestDigest': generated[-1]['key'], 'verificationRequestDigest': verified[-1]['key']}


def item(record, issue_id):
    f = record['frozen']; issue = next(i for i in f['issues'] if i['issueId'] == issue_id)
    answer = record['draft']['issues'][issue_id]; personal = record['scope'] == 'personal'
    companies, analyses = [], []
    for target in issue['targets']:
        cid = target['companyId']; a = answer['companies'][cid]
        c.korean_prose({'text': target['connectionReason']})
        companies.append({'companyId': cid, 'name': target['name'], 'reason': target['connectionReason']})
        analysis = {k: a[k]['text'] for k in ('keyPoint', 'confirmedFact', 'businessImpact', 'outlook', 'nextCheck')}
        connection = 'forMyStocks' if personal else 'companyConnection'; analysis[connection] = a[connection]['text']
        analysis.update(companyId=cid, companyName=target['name'], roundId=f['roundId'], cutoff=f['cutoff'],
            resultVersion=record['resultVersion'], verificationMode='separate_request_same_model', direction=a['direction'],
            positive=None if a['positive'] is None else a['positive']['text'],
            negative=None if a['negative'] is None else a['negative']['text'],
            priceObservation=None if a['priceObservation'] is None else a['priceObservation']['text'],
            previousChange={k: a['previousChange'][k] for k in ('status', 'text')},
            evidenceIds=sorted(set(target['evidenceIds'])),
            judgmentBasis={'promptVersion': record['promptVersion'], 'directionReason': a['directionReason']['text'],
                'confidence': a['directionConfidence'], 'effectSizeStatus': a['effectSizeStatus']})
        if personal:
            # This is a new scheduled round, not a same-round legacy rewrite. No fabricated old baseline.
            analysis['comparison'] = {'status': 'newly_selected', 'baseline': None}
        analyses.append(analysis)
    sources = [source_time.projection(s) for s in issue['sources'].values()]
    out = {'issueId': issue_id, 'kind': 'new_issue' if personal else issue['kind'],
        'title': answer['headline']['text'], 'topicTag': answer['topicTag'], 'reason': answer['subline']['text'],
        'originRoundId': f['roundId'], 'originCutoff': f['cutoff'], 'sources': sources, 'aiAnalyses': analyses}
    if personal:
        out.update(connections=companies, priorAnalysis=[], price=None)
    else:
        c.korean_prose({'text': issue['whyNow']['text']})
        out.update(companies=companies, importance=issue['importance'], whyNow=issue['whyNow']['text'],
                   prices=[], analysisResultVersion=record['resultVersion'])
    return out


def common_view(record, candidate_count):
    f = record['frozen']; items = [item(record, i['issueId']) for i in f['issues']]
    return {'schemaVersion': 'common-relative-priority-view-v1', 'roundId': f['roundId'], 'cutoff': f['cutoff'],
        'resultVersion': record['resultVersion'], 'generationVersion': record['promptVersion'],
        'candidateCount': candidate_count, 'minimumIssues': 2, 'minimumShortfall': max(0, 2 - len(items)),
        'status': 'available' if items else 'collection_insufficient', 'items': items}


def summary(client, common_record):
    f = common_record['frozen']; refs = sorted({e for i in f['issues'] for e in i['sources']})
    frozen = m.seal({'version': 'priority-round-business-v1', **{k: f[k] for k in ('roundId', 'date', 'edition', 'cutoff')},
        'references': refs, 'selectedIssues': f['issues'], 'verifiedBusiness': common_record['draft'],
        'marketObservation': {'status': 'unavailable'}, 'previousSummary': {'status': 'unavailable'},
        'scopeNote': '선정 기업 사업 관점만 요약. 시장 전체 흐름·가격 반응·직전 종합 판단은 평가하지 않음.'})
    # Context/market/prior statements are kept out of this article-grounded summary contract.
    schema = c.summary_schema(frozen); schema['properties'].pop('judgmentChange'); schema['required'].remove('judgmentChange')
    checks = c.summary_verification_schema(frozen); checks['properties'].pop('judgmentChange'); checks['required'].remove('judgmentChange')
    draft = _call(client, 'priority-summary', {'frozen': frozen}, 'fresh-summary-generation.md', schema, 6000)
    b.validate_schema(draft, schema); c.korean_prose(draft)
    verified = _call(client, 'priority-summary-check', {'frozen': frozen, 'draft': draft}, 'fresh-summary-verification.md', checks, 5000)
    b.validate_schema(verified, checks); c.require(all(v['supported'] for v in verified.values()), 'priority_summary_withheld')
    record = {'frozen': frozen, 'draft': draft, 'verification': verified}
    record['resultVersion'] = frozen['version'] + '-' + b.digest(b.canonical(record))
    statements = [draft[k] for k in ('headline', 'roundAssessment', 'nextSessionOutlook')] + draft['nextChecks']
    for s in statements:
        c.require(len(set(s['evidenceIds'])) == len(s['evidenceIds']) and set(s['evidenceIds']) <= set(refs), 'priority_summary_foreign_evidence')
    return record, {'schemaVersion': 'briefing-priority-summary-v1', 'roundId': f['roundId'], 'cutoff': f['cutoff'],
        'resultVersion': record['resultVersion'], 'text': '\n\n'.join(s['text'] for s in statements),
        'evidenceIds': sorted({e for s in statements for e in s['evidenceIds']})}


def prove_summary(record, calls):
    f, draft, verdict = record['frozen'], record['draft'], record['verification']
    m.check_seal(f)
    schema = c.summary_schema(f); schema['properties'].pop('judgmentChange'); schema['required'].remove('judgmentChange')
    check_schema = c.summary_verification_schema(f); check_schema['properties'].pop('judgmentChange'); check_schema['required'].remove('judgmentChange')
    b.validate_schema(draft, schema); c.korean_prose(draft); b.validate_schema(verdict, check_schema)
    c.require(all(v['supported'] for v in verdict.values()), 'priority_summary_withheld')
    unsigned = {k: v for k, v in record.items() if k != 'resultVersion'}
    c.require(record['resultVersion'] == f['version'] + '-' + b.digest(b.canonical(unsigned)), 'priority_summary_digest')
    generated = [r for r in calls if r.get('priorityBound') and r['stage'] == 'priority-summary' and r['input'] == {'frozen': f} and r['answer'] == draft]
    verified = [r for r in calls if r.get('priorityBound') and r['stage'] == 'priority-summary-check' and r['input'] == {'frozen': f, 'draft': draft} and r['answer'] == verdict]
    c.require(generated and verified and generated[-1]['key'] != verified[-1]['key'], 'priority_summary_receipts_missing')
    return {'generationRequestDigest': generated[-1]['key'], 'verificationRequestDigest': verified[-1]['key']}


def prompt_for(stage):
    for gen, check, gp, vp in STAGES.values():
        if stage == gen: return PROMPTS / gp
        if stage == check: return PROMPTS / vp
    return {'priority-summary': PROMPTS / 'fresh-summary-generation.md',
            'priority-summary-check': PROMPTS / 'fresh-summary-verification.md'}.get(stage)


def verified_calls(directory):
    calls = receipts.verified_calls(directory)
    for call in calls:
        if not call['stage'].startswith('priority-'): continue
        request = b.strict_load(b.regular(Path(directory) / 'calls' / (call['key'] + '.request.json')))
        prompt = prompt_for(call['stage'])
        c.require(prompt is not None and request['instructions'] == prompt.read_text(), 'priority_prompt_receipt_mismatch')
        c.require(request['text']['format']['strict'] is True and request['text']['format']['type'] == 'json_schema', 'priority_strict_receipt')
        f = call['input']['frozen']; stage = call['stage']
        if stage in ('priority-summary', 'priority-summary-check'):
            schema = c.summary_schema(f) if stage == 'priority-summary' else c.summary_verification_schema(f)
            schema['properties'].pop('judgmentChange'); schema['required'].remove('judgmentChange')
        else:
            scope = 'personal' if stage.startswith('priority-personal') else 'common'
            schema = c.verification_schema(f, scope) if stage.endswith('-check') else c.generation_schema(f, scope)
        c.require(request['text']['format']['schema'] == schema, 'priority_schema_receipt_mismatch')
        call['priorityBound'] = True
    return calls
