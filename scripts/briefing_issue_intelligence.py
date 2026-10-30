"""Evidence-first selection and issue/company analysis, with immutable offline inputs.

No transport is created here. A separately authorized, budgeted launcher injects
one. Old publisher results, source files and paid receipts are never rewritten.
"""
import copy
import itertools
from decimal import Decimal
from pathlib import Path

import briefing_company_outlook as company
import briefing_grouped_rounds as grouped
import briefing_price_aware_prompt as price_prompt

base = company.base
VERSION = 'issue-intelligence-v1'
POLICY = 'issue-selection-policy-v2'
PROMPTS = company.PROMPTS.with_name(VERSION)
aware = company.context.legacy._aware
obj = company.obj


def require(ok, reason):
    if not ok:
        raise ValueError('issue_intelligence_' + reason)


def seal(value):
    result = copy.deepcopy(value)
    result.pop('inputSha256', None)
    result['inputSha256'] = base.digest(base.canonical(result))
    return result


def check_seal(value):
    require(seal(value) == value, 'input_hash')


def quarantine_documents(frozen, audits):
    """Apply recorded source disqualifications without editing old clocks/results.

    The audit is a separate input pinned to document and body versions. A source
    conflict cannot become eligible merely because an earlier request used it.
    """
    check_seal(frozen)
    result = copy.deepcopy(frozen)
    for audit in audits:
        require(audit['status'] in ('publisher_time_disagreement', 'source_withdrawn') and
                audit['action'] == 'quarantine' and len(audit['evidenceSha256']) == 64,
                'qualification_audit')
        rejected = [c for c in result['candidates'] if any(
            s['documentId'] == audit['documentId'] and s['bodySha256'] == audit['bodySha256']
            for s in c['sources'].values())]
        ids = {c['issueId'] for c in rejected}
        result['candidates'] = [c for c in result['candidates'] if c['issueId'] not in ids]
        result.setdefault('excluded', []).extend({'issueId': iid, 'reason': audit['status'],
            'auditSha256': audit['evidenceSha256']} for iid in sorted(ids))
    result['qualificationAudits'] = copy.deepcopy(audits)
    result['supersedesInputSha256'] = frozen['inputSha256']
    return seal(result)


def source_view(source):
    published = source.get('publishedAt') or source.get('publicationClock', {}).get('publishedAt')
    return {'evidenceId': source['evidenceId'], 'documentId': source['documentId'],
            'bodySha256': source['bodySha256'], 'quote': source['quote'],
            'url': source.get('url'), 'publishedAt': published}


def preserved_context(source, saved):
    """Expand to complete adjacent paragraphs only in the same hashed body."""
    result = copy.deepcopy(source)
    body = saved.get('fullBody', '')
    if not body or base.digest(body.encode()) != source['bodySha256']:
        return result
    quote = source['quote']
    start = body.find(quote)
    require(start >= 0, 'saved_quote_missing')
    end = start + len(quote)
    left = body.rfind('\n\n', 0, start)
    right = body.find('\n\n', end)
    left, right = max(0, left + 2), len(body) if right < 0 else right
    if right - left <= 3000:
        result['context'] = body[left:right]
        result['contextStart'], result['contextEnd'] = left, right
    return result


def prepare_round(recorded_input, response):
    """Reuse the complete historical candidate pool and its exact eligibility gates.

    The caller authenticates the old request/receipt before invoking this adapter.
    The old *selection* and importance labels are deliberately not model inputs.
    """
    ctx = recorded_input['context']
    require(ctx['date'] == response['date'] and ctx['edition'] == response['edition']
            and aware(ctx['window']['to']) == aware(response['dataAsOf']), 'round_binding')
    require(base.digest(base.canonical(ctx)) == recorded_input['contextSha256'], 'context_hash')
    prices = price_prompt.freeze(response)  # validates source, price and market clocks
    by_company = {t['companyId']: t['observedMovement'] for t in prices['targets']}
    allowed = set(recorded_input['selectionEligibility']['allowedIssueIds'])
    candidates, excluded = [], []
    cutoff = aware(ctx['window']['to'])
    seen = set()
    for c in recorded_input['issues']:
        iid = c['issueId']
        require(iid not in seen, 'duplicate_issue'); seen.add(iid)
        plain = {k: v for k, v in c.items() if k != 'asOfSnapshotSha256'}
        require(base.digest(base.canonical(plain)) == c['asOfSnapshotSha256'], 'candidate_hash')
        require(c['window'] == ctx['window'], 'candidate_window')
        evidence, links = grouped._catalog(c)
        require(all(aware(source_view(e)['publishedAt']) <= cutoff for e in evidence.values()), 'future_source')
        decision = c.get('freshnessReview', {}).get('decision')
        reason = ('repeat_or_uncertain' if decision in ('REPEAT', 'UNCERTAIN') else
                  'semantic_support_missing' if not grouped.evidence_eligible(c) else
                  'outside_recorded_publication_eligibility' if iid not in allowed else None)
        if reason:
            excluded.append({'issueId': iid, 'reason': reason}); continue
        require(decision in ('DISTINCT_EVENT', 'MATERIAL_UPDATE'), 'freshness_record_missing')
        ids = set(c['newEvidenceIds'])
        saved_sources = response['editionReview']['sources']
        sources = {eid: preserved_context(source_view(evidence[eid]), saved_sources.get(eid, {})) for eid in sorted(ids)}
        connected = []
        for cid, link in sorted(links.items()):
            refs = sorted(set(link['evidenceIds']) & ids)
            if not refs: continue
            movement = copy.deepcopy(by_company.get(cid, {'status': 'unavailable', 'reason': 'saved_price_missing'}))
            if movement['status'] == 'available':
                movement['news'] = [n for n in movement['news'] if n['evidenceId'] in ids]
            connected.append({'companyId': cid, 'name': link['name'], 'role': link.get('role'),
                              'evidenceIds': refs, 'observedMovement': movement})
        require(connected, 'company_links_missing')
        candidates.append({'issueId': iid, 'title': c['title'], 'freshnessReview': copy.deepcopy(c['freshnessReview']),
            'sources': sources, 'companies': connected, 'snapshotSha256': c['asOfSnapshotSha256']})
    require(allowed <= seen, 'allowed_issue_missing')
    return seal({'schemaVersion': VERSION, 'policyVersion': POLICY, 'roundId': response['id'],
        'date': response['date'], 'edition': response['edition'], 'cutoff': ctx['window']['to'],
        'window': copy.deepcopy(ctx['window']), 'candidates': candidates, 'excluded': excluded,
        'candidatePoolCount': len(seen), 'marketReference': prices['marketReference'],
        'baselineResponseSha256': base.digest(base.canonical(response)),
        'scope': 'historical_simulation_not_original_publication'})


def prepare(recorded, responses, output, qualification_audits=()):
    recorded, responses, output = map(lambda p: Path(p).resolve(), (recorded, responses, output))
    require(all(output != p and p not in output.parents and output not in p.parents for p in (recorded, responses)), 'separate_preparation')
    raw = base.regular(recorded / 'bundle-v2.json'); bundle = base.strict_load(raw)
    proofs = []
    base.private_dir(output)
    for row in bundle['rounds']:
        key = row['groupedSelectionRequestDigest']
        require(len(key) == 64 and all(c in '0123456789abcdef' for c in key), 'recorded_request_id')
        request_raw = base.regular(recorded / 'calls' / (key + '.request.json'))
        reply_raw = base.regular(recorded / 'calls' / (key + '.response.json'))
        receipt = next(r for r in bundle['receipts'] if r['requestDigest'] == key)
        require(base.digest(request_raw) == key and base.digest(reply_raw) == receipt['responseSha256']
                and receipt['status'] == 'completed' and receipt['httpStatus'] == 200 and receipt['usageKnown'], 'recorded_receipt')
        request, reply = base.strict_load(request_raw), base.strict_load(reply_raw)
        require(request['model'] == receipt['model'] == base.MODEL and request['store'] is False
                and reply['id'] == receipt['responseId'] and reply['status'] == 'completed'
                and request['text']['format']['name'] == 'grouped_issue_selection', 'recorded_provider_binding')
        prefix = row['date'] + '-' + row['edition']
        response_raw = base.regular(responses / (prefix + '.json'))
        response = base.strict_load(response_raw)
        require(response['id'] == row['roundId'], 'response_round')
        frozen = prepare_round(base.strict_load(request['input']), response)
        if qualification_audits:
            frozen = quarantine_documents(frozen, qualification_audits)
        encoded, _, prompt_sha = company.context.legacy.prepare_market_request(PROMPTS, 'selection',
            {'frozen': frozen}, 'selection.md', 'unused', 10000, assessment_schema(frozen))
        base.write_once(output / (prefix + '.input.json'), base.canonical(frozen))
        base.write_once(output / (prefix + '.selection-request.json'), encoded)
        proofs.append({'roundId': row['roundId'], 'date': row['date'], 'edition': row['edition'],
            'candidatePoolCount': frozen['candidatePoolCount'], 'eligibleCandidates': len(frozen['candidates']),
            'excluded': frozen['excluded'], 'inputSha256': frozen['inputSha256'],
            'sourceRequestSha256': key, 'baselineResponseSha256': base.digest(response_raw),
            'selectionRequestBytes': len(encoded), 'promptSha256': prompt_sha})
    for path in PROMPTS.glob('*.md'): base.write_once(output / path.name, base.regular(path))
    proof = {'status': 'PREPARED_ONLY', 'version': VERSION, 'policyVersion': POLICY, 'rounds': proofs,
        'recordedBundleSha256': base.digest(raw), 'newPaidCalls': 0,
        'plannedCalls': 4 * len(proofs), 'minimumIfNoCoreIssues': 2 * len(proofs),
        'maximumCallsWithOneRepairPerStage': 8 * len(proofs),
        'note': 'No new AI selection, analysis, or publication yet. Completed evidence is reused; inference requires authorization.'}
    base.write_once(output / 'prepared-proof.json', base.canonical(proof))
    return proof


def assessment_schema(frozen):
    properties = {}
    for c in frozen['candidates']:
        statement = company.statement(list(c['sources']))
        relation = obj({'companyId': {'type': 'string', 'enum': [x['companyId'] for x in c['companies']]},
            'directness': {'type': 'string', 'enum': ['direct', 'indirect', 'unconfirmed']},
            'basis': statement})
        properties[c['issueId']] = obj({
            'businessImportance': {'type': 'integer', 'minimum': 0, 'maximum': 3},
            'informationChange': {'type': 'string', 'enum': ['new_event', 'material_update', 'repeat', 'uncertain']},
            'whyImportant': statement, 'whyNow': statement,
            'relations': {'type': 'array', 'items': relation, 'minItems': len(c['companies']), 'maxItems': len(c['companies'])}})
    return obj({'assessments': obj(properties)})


def validate_assessments(answer, frozen):
    base.validate_schema(answer, assessment_schema(frozen))
    for c in frozen['candidates']:
        a = answer['assessments'][c['issueId']]
        require({r['companyId'] for r in a['relations']} == {r['companyId'] for r in c['companies']}, 'relation_coverage')
        for r in a['relations']:
            link = next(x for x in c['companies'] if x['companyId'] == r['companyId'])
            require(set(r['basis']['evidenceIds']) <= set(link['evidenceIds']), 'foreign_relation_evidence')
        if a['informationChange'] == 'material_update':
            delta = set(c['freshnessReview'].get('deltaEvidenceIds', []))
            require(bool(delta & set(a['whyNow']['evidenceIds'])), 'material_delta_missing')
        if a['informationChange'] == 'new_event':
            require(c['freshnessReview']['decision'] == 'DISTINCT_EVENT', 'update_relabelled_new')


def verification_schema(ids):
    return obj({'checks': obj({iid: obj({'supported': {'type': 'boolean'},
        'reason': {'type': 'string', 'minLength': 1, 'maxLength': 700}}) for iid in ids})})


def price_signal(candidate):
    """Only event-window observations; a previous close is not a news reaction."""
    observations = []
    for c in candidate['companies']:
        p = c['observedMovement']
        if p['status'] != 'available': continue
        for n in p.get('news', []):
            if n['status'] != 'observed' or n['before'] is None or n['changeRatePercent'] is None: continue
            rate = Decimal(str(n['changeRatePercent']))
            require(rate.is_finite(), 'price_nonfinite')
            key = (c['companyId'], n['before']['observedAt'], p['latest']['observedAt'], p['currency'])
            observations.append({'key': key, 'value': min(Decimal('3'), abs(rate)),
                'basis': (n['before']['observedAt'], p['latest']['observedAt'], p['currency']),
                'evidenceId': n['evidenceId']})
    # A single consistent interval per event is necessary for ranking.
    bases = {o['basis'] for o in observations}
    if len(bases) != 1:
        return {'status': 'unavailable', 'value': None, 'reason': 'no_single_comparable_event_window', 'keys': []}
    unique = {o['key']: o for o in observations}
    return {'status': 'observed', 'value': str(sum(o['value'] for o in unique.values()) / len(unique)),
            'basis': list(next(iter(bases))), 'keys': [list(k) for k in unique]}


def select(frozen, assessed, verified, previous_selected=()):
    validate_assessments(assessed, frozen)
    base.validate_schema(verified, verification_schema([c['issueId'] for c in frozen['candidates']]))
    eligible, rejected = [], []
    previous = {r['issueId']: r for r in previous_selected}
    for c in frozen['candidates']:
        iid = c['issueId']; a = assessed['assessments'][iid]
        reason = ('assessment_not_supported' if not verified['checks'][iid]['supported'] else
                  'importance_below_core_threshold' if a['businessImportance'] < 2 else
                  'repeat_or_uncertain' if a['informationChange'] in ('repeat', 'uncertain') else None)
        if iid in previous:
            old = previous[iid]
            delta = set(c['freshnessReview'].get('deltaEvidenceIds', []))
            old_quotes = {s['quote'] for s in old['candidate']['sources'].values()}
            if a['informationChange'] != 'material_update' or not any(c['sources'][k]['quote'] not in old_quotes for k in delta if k in c['sources']):
                reason = 'previous_issue_without_verified_new_fact'
        if reason:
            rejected.append({'issueId': iid, 'reason': reason}); continue
        # Duplicate extraction of the same edge/company cannot raise the count.
        relation_count = len({r['companyId'] for r in a['relations'] if r['directness'] == 'direct'})
        eligible.append({'issueId': iid, 'candidate': copy.deepcopy(c), 'assessment': copy.deepcopy(a),
            'priceSignal': price_signal(c), 'relationSignal': {'value': min(3, relation_count),
                'basis': 'verified_distinct_direct_parties_capped_3'},
            'policyVersion': POLICY, 'cutoff': frozen['cutoff']})
    ordered = []
    for _, values in itertools.groupby(sorted(eligible, key=lambda x: (-x['assessment']['businessImportance'], x['issueId'])),
                                        lambda x: x['assessment']['businessImportance']):
        cohort = list(values)
        keys = [tuple(k) for r in cohort for k in r['priceSignal'].get('keys', [])]
        comparable = bool(cohort) and all(r['priceSignal']['status'] == 'observed' for r in cohort)
        comparable = comparable and len({tuple(r['priceSignal']['basis']) for r in cohort}) == 1 and len(keys) == len(set(keys))
        for r in cohort:
            r['priceSignal']['usedForRanking'] = comparable
            if not comparable: r['priceSignal']['rankingReason'] = 'missing_incomparable_or_shared_observation_in_tied_group'
        # Missing prices do not silently become zero or lose a tie. If one is
        # missing/shared, this entire equal-importance group skips price ranking.
        cohort.sort(key=lambda r: (-(Decimal(r['priceSignal']['value']) if comparable else 0),
                                   -r['relationSignal']['value'], r['issueId']))
        ordered.extend(cohort)
    selected, support = [], set()
    for r in ordered:
        exact = {(s['documentId'], s['bodySha256'], s['quote']) for s in r['candidate']['sources'].values()}
        if exact & support:
            rejected.append({'issueId': r['issueId'], 'reason': 'duplicate_exact_event_support'}); continue
        support |= exact; selected.append({**r, 'rank': len(selected) + 1})
        if len(selected) == 3: break
    return {'selected': selected, 'rejected': rejected, 'ranked': [r['issueId'] for r in ordered],
            'policyVersion': POLICY, 'inputSha256': frozen['inputSha256']}


def analysis_inputs(frozen, selection, history):
    result = []
    for s in selection['selected']:
        c = s['candidate']; targets = []
        for link in c['companies']:
            previous = company.previous_issue_company(link['companyId'], c['issueId'], frozen['date'],
                frozen['edition'], frozen['cutoff'], history)
            targets.append({'companyId': link['companyId'], 'companyName': link['name'], 'issueIds': [c['issueId']],
                'role': link['role'], 'sourceIds': link['evidenceIds'], 'issueEvidenceIds': link['evidenceIds'],
                'facts': [{'text': c['sources'][sid]['quote'], 'evidenceIds': [sid]} for sid in link['evidenceIds']],
                'previous': previous, 'observedMovement': copy.deepcopy(link['observedMovement'])})
        result.append(seal({'schemaVersion': company.SCHEMA, 'promptVersion': VERSION,
            'comparisonContract': 'issue-company-v1', 'issueId': c['issueId'], 'title': c['title'],
            **{k: frozen[k] for k in ('roundId', 'date', 'edition', 'cutoff')},
            'targets': targets, 'sources': copy.deepcopy(c['sources']),
            'selection': {k: copy.deepcopy(v) for k, v in s.items() if k != 'candidate'},
            'marketReference': copy.deepcopy(frozen['marketReference'])}))
    return result


def analysis_schema(inputs):
    fields = {}
    for f in inputs:
        value = company.generation_schema(f)
        statement = company.statement(list(f['sources']))
        item = value['properties']['companies']['items']
        item['properties'].update({k: copy.deepcopy(statement) for k in ('takeaway', 'positive', 'negative', 'newInformation')})
        item['required'] = list(item['properties'])
        value['properties']['headline'] = copy.deepcopy(statement)
        value['properties']['headline']['properties']['text']['maxLength'] = 65
        value['required'] = list(value['properties'])
        fields[f['issueId']] = value
    return obj({'issues': obj(fields)})


def validate_analysis(answer, inputs):
    base.validate_schema(answer, analysis_schema(inputs))
    for f in inputs:
        draft = answer['issues'][f['issueId']]
        stripped = {'companies': [{k: v for k, v in c.items() if k not in ('takeaway', 'positive', 'negative', 'newInformation')}
                                 for c in draft['companies']]}
        company.validate(stripped, f)
        for c in draft['companies']:
            target = next(t for t in f['targets'] if t['companyId'] == c['companyId'])
            for field in ('takeaway', 'positive', 'negative', 'newInformation'):
                refs = c[field]['evidenceIds']
                require(set(refs) <= set(target['sourceIds']) and len(refs) == len(set(refs)), 'summary_foreign_evidence')


def _call(client, stage, data, schema, limit=10000):
    return client.call(stage, data, stage + '.md', 'unused', limit, schema)


def assess_candidates(client, frozen):
    """Repair unsupported classifications once, without rewriting supported ones."""
    assessed = _call(client, 'selection', {'frozen': frozen}, assessment_schema(frozen))
    validate_assessments(assessed, frozen)
    verified = _call(client, 'selection-verification', {'frozen': frozen, 'draft': assessed},
        verification_schema([c['issueId'] for c in frozen['candidates']]))
    attempts = [{'draft': copy.deepcopy(assessed), 'verification': copy.deepcopy(verified)}]
    failed = [c for c in frozen['candidates'] if not verified['checks'][c['issueId']]['supported']]
    if failed:
        subset = seal({**frozen, 'candidates': failed})
        ids = [c['issueId'] for c in failed]
        repair = {'draft': {i: assessed['assessments'][i] for i in ids},
                  'checks': {i: verified['checks'][i] for i in ids}}
        amended = _call(client, 'selection', {'frozen': subset, 'repair': repair}, assessment_schema(subset))
        validate_assessments(amended, subset)
        checked = _call(client, 'selection-verification', {'frozen': subset, 'draft': amended}, verification_schema(ids))
        attempts.append({'draft': amended, 'verification': checked})
        assessed['assessments'].update(amended['assessments'])
        verified['checks'].update(checked['checks'])
    return assessed, verified, attempts


def analyze(client, targets, initial_repair=None):
    """One bounded repair of rejected issues; preserve each passed draft verbatim."""
    remaining = list(targets)
    passed, final_checks, attempts = {}, {}, []
    for attempt in range(2):
        if not remaining: break
        ids = [f['issueId'] for f in remaining]
        repair = copy.deepcopy(initial_repair) if not attempts else {
            'draft': {'issues': {i: attempts[-1]['draft']['issues'].get(i) for i in ids}},
            'verification': {'checks': {i: final_checks[i] for i in ids}}}
        data = {'issues': remaining, 'repair': repair}
        drafted = _call(client, 'analysis', data, analysis_schema(remaining), 12000)
        checked, valid = {'checks': {}}, []
        for f in remaining:
            iid = f['issueId']
            try:
                validate_analysis({'issues': {iid: drafted['issues'].get(iid)}}, [f])
            except (ValueError, base.ReplayError) as error:
                checked['checks'][iid] = {'supported': False, 'reason': str(error)}
            else:
                valid.append(f)
        if valid:
            valid_ids = [f['issueId'] for f in valid]
            verified = _call(client, 'analysis-verification', {'issues': valid,
                'draft': {'issues': {i: drafted['issues'][i] for i in valid_ids}}},
                verification_schema(valid_ids), 6000)
            base.validate_schema(verified, verification_schema(valid_ids))
            checked['checks'].update(verified['checks'])
        attempts.append({'draft': drafted, 'verification': checked})
        for f in remaining:
            iid = f['issueId']; verdict = checked['checks'][iid]
            final_checks[iid] = verdict
            if verdict['supported']: passed[iid] = drafted['issues'][iid]
        remaining = [f for f in remaining if f['issueId'] not in passed]
    return {'issues': passed}, {'checks': final_checks}, attempts


def run(prepared, output, transport, maximum_calls, authorization_ref):
    """Four stages per round. Each stage reuses its exact completed request.

    Semantic rejects are retained per issue. No unverified item is projected.
    One bounded analysis repair preserves prior passes and all failed drafts.
    """
    prepared, output = Path(prepared).resolve(), Path(output).resolve()
    require(prepared != output and prepared not in output.parents and output not in prepared.parents, 'separate_output')
    require(authorization_ref and type(maximum_calls) is int and 1 <= maximum_calls <= 32, 'authorization_and_call_limit')
    inputs = [base.strict_load(base.regular(p)) for p in sorted(prepared.glob('*.input.json'))]
    inputs.sort(key=lambda f: aware(f['cutoff']))
    require(0 < len(inputs) <= 4 and len({r['roundId'] for r in inputs}) == len(inputs), 'round_coverage')
    for f in inputs: check_seal(f)
    identity = {'version': VERSION, 'policyVersion': POLICY, 'model': base.MODEL,
        'authorizationRef': authorization_ref, 'maximumCalls': maximum_calls,
        'inputs': [f['inputSha256'] for f in inputs],
        'prompts': {p.name: base.digest(base.regular(p)) for p in sorted(PROMPTS.glob('*.md'))}}
    base.private_dir(output)
    import os
    lock = output / '.execution.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    try:
        base.write_once(output / 'execution.json', base.canonical(identity))
        client = company.context.legacy.MarketSummaryClient(output, transport, maximum_calls, prompt_root=PROMPTS)
        history, selected_history, rounds = [], [], []
        for frozen in inputs:
            prefix = frozen['date'] + '-' + frozen['edition']
            assessed, verified, selection_attempts = assess_candidates(client, frozen)
            selection = select(frozen, assessed, verified, selected_history)
            targets = analysis_inputs(frozen, selection, history)
            # No event is fabricated just to fill three slots.
            drafted = {'issues': {}}
            checked = {'checks': {}}
            if targets:
                drafted, checked, analysis_attempts = analyze(client, targets)
            else:
                analysis_attempts = []
            passed = []
            for f in targets:
                ok = checked['checks'][f['issueId']]['supported']
                row = {**{k: f[k] for k in ('roundId', 'date', 'edition', 'cutoff', 'issueId')},
                    'status': 'PASS' if ok else 'WITHHELD', 'frozen': f,
                    'draft': drafted['issues'][f['issueId']] if ok else None,
                    'verification': checked['checks'][f['issueId']]}
                row['resultVersion'] = VERSION + '-' + base.digest(base.canonical(row))
                history.append(row)
                if ok: passed.append(row)
            # Explicit round marker prevents falling back to older convenient
            # judgments after a missing/withheld corresponding round.
            history.append({**{k: frozen[k] for k in ('roundId', 'date', 'edition', 'cutoff')},
                'status': 'PASS', 'resultVersion': VERSION + '-round', 'frozen': {'targets': []}, 'draft': {'companies': []}})
            row = {'round': {k: frozen[k] for k in ('roundId', 'date', 'edition', 'cutoff')},
                'selection': selection, 'assessments': assessed, 'selectionVerification': verified,
                'selectionAttempts': selection_attempts,
                'analysisInputs': targets, 'draft': drafted, 'analysisVerification': checked, 'passed': passed,
                'analysisAttempts': analysis_attempts,
                'status': 'PASS' if passed else 'WITHHELD', 'generatedAt': base.now()}
            path = output / (prefix + '.json')
            # generatedAt is metadata, not a reason to overwrite an old result.
            if path.exists():
                old = base.strict_load(base.regular(path)); row['generatedAt'] = old['generatedAt']
            base.write_once(path, base.canonical(row)); rounds.append(row)
            selected_history.extend(r for r in selection['selected'] if r['issueId'] in {x['issueId'] for x in passed})
        result = {'version': VERSION, 'policyVersion': POLICY, 'rounds': rounds, 'receipts': client.receipts()}
        base.write_once(output / 'results.json', base.canonical(result))
        return result
    finally:
        lock.unlink()
