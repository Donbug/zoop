"""Read-only projection of receipt-bound issue revisions; never edits publications."""
import copy
from pathlib import Path
import briefing_issue_intelligence as m

b = m.base


def verified_calls(output):
    calls = []
    for path in sorted((Path(output) / 'calls').glob('*.complete.json')):
        receipt = b.strict_load(b.regular(path)); key = receipt['requestDigest']
        request_raw = b.regular(path.with_name(key + '.request.json'))
        response_raw = b.regular(path.with_name(key + '.response.json'))
        m.require(b.digest(request_raw) == key and b.digest(response_raw) == receipt['responseSha256'], 'view_receipt_hash')
        request, response = b.strict_load(request_raw), b.strict_load(response_raw)
        m.require(receipt['httpStatus'] == 200 and receipt['usageKnown'] and
                  response['id'] == receipt['responseId'] and response['status'] == 'completed' and
                  request['model'] == receipt['model'] == b.MODEL and request['store'] is False, 'view_receipt_binding')
        calls.append({'key': key, 'stage': request['text']['format']['name'],
                      'input': b.strict_load(request['input']), 'answer': b.output_of(response)})
    return calls


def prove_issue(issue, calls):
    frozen, draft, iid = issue['frozen'], issue['draft'], issue['issueId']
    m.check_seal(frozen)
    m.validate_analysis({'issues': {iid: draft}}, [frozen])
    unsigned = {k: v for k, v in issue.items() if k != 'resultVersion'}
    m.require(issue['status'] == 'PASS' and issue['verification']['supported'] and
              issue['resultVersion'] == m.VERSION + '-' + b.digest(b.canonical(unsigned)), 'view_result_hash')
    def bound(c):
        return any(f == frozen for f in c['input'].get('issues', []))
    generated = [c for c in calls if c['stage'] == 'analysis' and bound(c) and c['answer']['issues'].get(iid) == draft]
    checked = [c for c in calls if c['stage'] == 'analysis-verification' and bound(c)
               and c['input']['draft']['issues'].get(iid) == draft and c['answer']['checks'][iid]['supported']]
    m.require(generated and checked, 'view_model_receipts_missing')
    return {'generationRequestDigest': generated[-1]['key'], 'verificationRequestDigest': checked[-1]['key']}


def reuse_candidate_assessments(frozen, row, calls):
    """Reuse only unchanged candidates whose classification and check have receipts."""
    assessed, checked, proof = {}, {}, []
    for candidate in frozen['candidates']:
        iid = candidate['issueId']; a = row['assessments']['assessments'][iid]; v = row['selectionVerification']['checks'][iid]
        def bound(call):
            source = call['input'].get('frozen', {})
            return all(source.get(k) == frozen[k] for k in ('roundId', 'date', 'edition', 'cutoff')) and candidate in source.get('candidates', [])
        gen = [c for c in calls if c['stage'] == 'selection' and bound(c) and c['answer']['assessments'].get(iid) == a]
        ver = [c for c in calls if c['stage'] == 'selection-verification' and bound(c)
               and c['input']['draft']['assessments'].get(iid) == a and c['answer']['checks'].get(iid) == v]
        m.require(gen and ver, 'reused_assessment_receipts')
        assessed[iid], checked[iid] = copy.deepcopy(a), copy.deepcopy(v)
        proof.append({'issueId': iid, 'generationRequestDigest': gen[-1]['key'], 'verificationRequestDigest': ver[-1]['key']})
    return {'assessments': assessed}, {'checks': checked}, proof


def project(baseline, frozen, row, calls):
    m.check_seal(frozen)
    # A verified prose receipt does not prove a separately edited selection reason.
    assessed, verified, _ = reuse_candidate_assessments(frozen, row, calls)
    m.validate_assessments(assessed, frozen)
    selection = row['selection']
    m.require(selection['inputSha256'] == frozen['inputSha256'] and
              selection['policyVersion'] == frozen['policyVersion'], 'view_selection_binding')
    selected_by_id = {s['issueId']: s for s in selection['selected']}
    m.require(len(selected_by_id) == len(selection['selected']) <= 3 and
              len({p['issueId'] for p in row['passed']}) == len(row['passed']), 'view_selection_coverage')
    for selected in selection['selected']:
        iid = selected['issueId']
        m.require(selected['assessment'] == assessed['assessments'][iid] and
                  verified['checks'][iid]['supported'] and
                  selected['candidate'] in frozen['candidates'], 'view_selected_assessment_binding')
    m.require(b.digest(b.canonical(baseline)) == frozen['baselineResponseSha256'] and
              row['round']['roundId'] == baseline['id'] and row['round']['cutoff'] == frozen['cutoff'], 'view_baseline_binding')
    response = copy.deepcopy(baseline)
    items, issues, details = [], [], {}
    for passed in row['passed']:
        proof = prove_issue(passed, calls)
        f, draft = passed['frozen'], passed['draft']
        m.require(f['issueId'] in selected_by_id, 'view_selected_issue_missing')
        selected = selected_by_id[f['issueId']]
        candidate = selected['candidate']
        m.require(any(c == candidate for c in frozen['candidates']), 'view_candidate_binding')
        expected = m.analysis_inputs(frozen, {'selected': [selected]}, [])[0]
        # Previous judgments are authenticated by the analysis receipts above.
        # All current round/candidate/selection fields must match independently.
        for target in expected['targets']:
            bound = next((t for t in f['targets'] if t['companyId'] == target['companyId']), None)
            m.require(bound is not None, 'view_target_binding')
            target['previous'] = copy.deepcopy(bound['previous'])
        m.require(m.seal(expected) == f and f in row['analysisInputs'], 'view_analysis_input_binding')
        assessment = assessed['assessments'][f['issueId']]
        sources = {sid: {**copy.deepcopy(s), 'title': baseline.get('editionReview', {}).get('sources', {}).get(sid, {}).get('title') or '원문 자료'}
                   for sid, s in f['sources'].items()}
        companies = []
        for c in draft['companies']:
            t = next(t for t in f['targets'] if t['companyId'] == c['companyId'])
            companies.append({**copy.deepcopy(c), 'sourceIds': t['sourceIds'], 'previous': t['previous']})
        issues.append({'issueId': f['issueId'], 'status': 'PASS', 'resultVersion': passed['resultVersion'],
            'headline': draft['headline'], 'sources': sources, 'companies': companies, **proof})
        refs = sorted(sources)
        linked = [{'id': t['companyId'], 'name': t['companyName'], 'relationType': 'INVOLVES',
                   'role': t['role'], 'roleUnconfirmed': t['role'] is None} for t in f['targets']]
        summary = {'text': '\n'.join(c['newInformation']['text'] for c in draft['companies']),
            'evidenceIds': sorted({e for c in draft['companies'] for e in c['newInformation']['evidenceIds']}),
            'generatedAt': row['generatedAt'], 'resultVersion': passed['resultVersion']}
        item = {'eventId': f['issueId'], 'rank': len(items) + 1, 'title': draft['headline']['text'],
            'reason': assessment['whyImportant']['text'] + ' ' + assessment['whyNow']['text'],
            'companies': linked, 'evidenceIds': refs, 'evidenceCount': len(refs), 'summary': summary,
            'eventTime': None, 'timePrecision': 'unknown', 'reportedAt': min(s['publishedAt'] for s in sources.values())}
        items.append(item)
        evidence = []
        for sid, s in sources.items():
            context = None
            if s.get('context') and s['quote'] in s['context']:
                start = s['contextStart']; quote_start = start + s['context'].index(s['quote'])
                context = {'text': s['context'], 'start': start, 'end': s['contextEnd'],
                    'quoteStart': quote_start, 'quoteEnd': quote_start + len(s['quote']), 'offsetUnit': 'unicode_code_point'}
            evidence.append({**s, 'id': sid, 'documentVersion': 'sha256-' + s['bodySha256'],
                'publisher': '', 'quoteVerified': True, 'sourceKind': 'news', 'bodyContext': context})
        details[f['issueId']] = {'roundId': response['id'], 'eventId': f['issueId'], 'title': item['title'],
            'summary': summary, 'selectionReason': item['reason'], 'companies': linked,
            'claims': [{**c['newInformation'], 'type': 'fact'} for c in draft['companies']],
            'evidence': evidence, 'limitations': ['회차 마감 이전 원발행 시각 기준의 과거 자료 재분석입니다.'],
            'metadata': copy.deepcopy(response['metadata'])}
    value = {'schemaVersion': m.VERSION, 'policyVersion': m.POLICY, 'model': b.MODEL,
        'baselineResponseSha256': frozen['baselineResponseSha256'],
        'verificationMode': 'separate_model_request', **row['round'], 'generatedAt': row['generatedAt'], 'issues': issues}
    value['resultVersion'] = m.VERSION + '-view-' + b.digest(b.canonical(value))
    response['items'], response['issueIntelligence'] = items, value
    response['preservedPublication'] = {'sha256': frozen['baselineResponseSha256'],
                                        'response': copy.deepcopy(baseline)}
    response['generatedAt'] = row['generatedAt']
    response['graphVersion'] = None  # the new selection has no published graph snapshot
    response['metadata']['graphVersion'] = None
    response['metadata']['selection']['reason'] = '근거 검증 후 사건 중요도·새 정보를 평가한 별도 재분석입니다.'
    response['emptyReason'] = None if items else 'no_issues_in_window'
    response.pop('continuity', None)
    response['notice'] = {'kind': 'analysis_revision', 'message': '이슈 중심 정책으로 새로 생성·검증한 비교본입니다.',
                          'reason': None, 'at': row['generatedAt']}
    response['references'] = {'eventIds': [i['eventId'] for i in items],
        'companyIds': sorted({c['id'] for i in items for c in i['companies']}),
        'evidenceIds': sorted({e for i in items for e in i['evidenceIds']})}
    # Old candidate-list comparisons cannot describe the new candidate list.
    response['sinceMorning'] = {'status': 'unavailable', 'reason': '새 분석의 판단 비교는 이슈 상세에서 확인하세요.'} if response['edition'] == 'evening' else None
    response['previousComparison'] = {'status': 'unavailable', 'reason': '새 분석의 판단 비교는 이슈 상세에서 확인하세요.'}
    for d in details.values(): d['metadata']['graphVersion'] = None
    return {'response': response, 'details': details,
        'comparison': {'old': [{'issueId': i['eventId'], 'title': i['title']} for i in baseline['items']],
                       'new': [{'issueId': i['eventId'], 'title': i['title']} for i in items]}}
