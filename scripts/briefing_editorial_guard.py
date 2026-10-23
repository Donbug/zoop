"""Source-bound editorial checks over completed groups; never re-extract or rewrite PoC groups."""
import copy
import re
from pathlib import Path
import briefing_grouped_rounds as grouped
import briefing_market_summary as summary

base = grouped.base
PROMPTS = grouped.PROMPTS.with_name('editorial-freshness-v3')
POLICY = 'accepted-issue-company-evidence-v1'


def company_names(archive, document_id, cutoff):
    """A query's association is not an entity proof. Use accepted, exact mention evidence only."""
    names = set()
    for issue in archive['issues']:
        for mention in issue['mentions']:
            if mention['articleId'] != document_id or grouped.sim.aware(mention['publishedAt']) > cutoff:
                continue
            if not mention.get('companyProjection', {}).get('briefingEligible', True):
                continue
            if mention.get('grounding', {}).get('verdict') != 'SUPPORTED':
                continue
            names.update(c['name'] for c in mention['companies'])
    return sorted(names)


def load_history(path):
    history = base.strict_load(base.regular(Path(path)))
    grouped.require(history['schemaVersion'] == 'zoop-editorial-history-v1', 'editorial_history_schema')
    ids = set()
    for report in history['reports']:
        grouped.require(report['reportId'] not in ids, 'editorial_history_duplicate')
        ids.add(report['reportId'])
        grouped.require(base.digest(report['body'].encode()) == report['bodySha256']
                        and report['quote'] and report['quote'] in report['body']
                        and report['companyIds'] and report['url'].startswith('https://'), 'editorial_history_source')
        grouped.require(report['clockStatus'] in ('verified_publisher_day', 'verified_publisher_timestamp', 'unverified_search_index'),
                        'editorial_history_clock_status')
        grouped.sim.aware(report['availableBefore'])
    return history


def review_inputs(archive, spec, history):
    candidates = grouped.build_grouped_candidates(archive, spec)
    start = grouped.sim.aware(spec['window']['from'])
    reports = [r for r in history['reports'] if grouped.sim.aware(r['availableBefore']) <= start]
    issues = []
    for c in candidates:
        evidence, companies = grouped._catalog(c)
        words = set(re.findall(r"[a-z0-9가-힣]{2,}", (c['title']+' '+ ' '.join(e['quote'] for e in evidence.values())).lower()))
        ranked = [r for r in reports if set(r['companyIds']) & set(companies)]
        # A bounded lexical match can otherwise bury a reviewed issuer release
        # under several copies of a later news article. Ranking is retrieval,
        # never approval: the independent freshness review still checks dates,
        # quotes and the actual event. Legacy histories keep their exact order.
        issuer_first = history.get('retrievalPolicy') == 'reviewed-issuer-first-v1'
        ranked.sort(key=lambda r: (
            0 if issuer_first and r.get('sourceRole') in ('issuer_release','prior_publication') and r.get('reviewStatus') == 'reviewed' else 1,
            -len(words & set(re.findall(r"[a-z0-9가-힣]{2,}", (r.get('title','')+' '+r['quote']).lower()))), r['reportId']))
        related = [r['reportId'] for r in ranked[:4]]
        issues.append({'issueId': c['issueId'], 'title': c['title'], 'priorReportIds': related,
                       'mentionEventTimes': [m['eventTime'] for m in c['newMentions']],
                       'newEvidence': [evidence[i] for i in c['newEvidenceIds']]})
    used = {i for c in issues for i in c['priorReportIds']}
    return {'window': spec['window'], 'reports': [r for r in reports if r['reportId'] in used], 'issues': issues}


def schema(frozen):
    return {'type': 'object', 'properties': {i['issueId']: {'type': 'object', 'properties': {
        'decision': {'type': 'string', 'enum': ['REPEAT', 'MATERIAL_UPDATE', 'DISTINCT_EVENT', 'UNCERTAIN']},
        'deltaEvidenceIds': {'type': 'array', 'items': {'type': 'string', 'enum': [e['evidenceId'] for e in i['newEvidence']]}},
        'reason': {'type': 'string', 'minLength': 1}},
        'required': ['decision', 'deltaEvidenceIds', 'reason'], 'additionalProperties': False} for i in frozen['issues']},
        'required': [i['issueId'] for i in frozen['issues']], 'additionalProperties': False}


def validate(answer, frozen):
    base.validate_schema(answer, schema(frozen))
    for value in answer.values():
        grouped.require(len(set(value['deltaEvidenceIds'])) == len(value['deltaEvidenceIds'])
                        and (bool(value['deltaEvidenceIds']) == (value['decision'] == 'MATERIAL_UPDATE')),
                        'editorial_delta_binding')


def review(archive, series, history, output, key_file, max_calls=96):
    base.private_dir(output)
    client = summary.MarketSummaryClient(output, base.authenticated_transport(key_file, timeout=600), max_calls, prompt_root=PROMPTS)
    rounds = []
    for spec in series['rounds']:
        frozen = review_inputs(archive, spec, history)
        digest = None
        if frozen['issues']:
            s = schema(frozen)
            digest = client.request_digest('editorial_freshness', frozen, 'review.md', 'unused', 14000, s)
            answer = client.call('editorial_freshness', frozen, 'review.md', 'unused', 14000, s)
            corrections = []
            try:
                validate(answer, frozen)
            except base.ReplayError as error:
                # One known completed semantic-format correction; never resend an unknown call.
                if str(error) != 'editorial_delta_binding': raise
                receipt, response = client.inspect_recorded(digest)
                correction = {'attempt': 1, 'failure': str(error), 'originalRequestDigest': digest,
                    'originalResponseSha256': receipt['responseSha256'], 'previousReply': answer,
                    'instruction': 'Keep the same evidence/history. MATERIAL_UPDATE requires a nonempty exact current deltaEvidenceIds. If no change can be proved use UNCERTAIN or REPEAT. For a genuine new numerical change cite its current evidence, not the older report.'}
                data = {**frozen, 'editorialCorrection': correction}
                digest = client.request_digest('editorial_freshness', data, 'review.md', 'unused', 14000, s)
                answer = client.call('editorial_freshness', data, 'review.md', 'unused', 14000, s)
                validate(answer, frozen); corrections = [correction]
        else:
            answer = {}; corrections = []
        rounds.append({'window': spec['window'], 'frozen': frozen, 'decisions': answer, 'requestDigest': digest, 'corrections': corrections})
    return {'schemaVersion': 'zoop-editorial-freshness-v1', 'promptVersion': 'editorial-freshness-v3', 'history': history, 'rounds': rounds,
            'receipts': client.receipts()}, len(client.new_calls)


def decision(archive, spec, issue_id):
    layer = archive.get('editorialReview')
    if not layer:
        return None
    rows = [r for r in layer['rounds'] if r['window'] == spec['window']]
    grouped.require(len(rows) == 1, 'editorial_review_round_missing')
    row = rows[0]
    value = row['decisions'].get(issue_id)
    return ({**copy.deepcopy(value), 'reviewRequestDigest': row['requestDigest']} if value else
            {'decision': 'NOT_CHECKED', 'deltaEvidenceIds': [], 'reason': 'No matching earlier report in the bounded history; novelty is not proven.',
             'reviewRequestDigest': None})


def run(args):
    """Operator CLI. Offline planning is the default; old groups remain immutable."""
    import briefing_round_series as series_rules
    source, output = Path(args.archive).resolve(), Path(args.output).resolve()
    grouped.require(output != source.parent and source.parent not in output.parents
                    and output not in source.parent.parents, 'editorial_separate_output')
    raw = base.regular(source); archive = base.strict_load(raw)
    grouped.require(not archive.get('editorialReview'), 'editorial_requires_native_parent')
    history = load_history(args.history)
    series = series_rules.load(args.round_series, archive['sourceFileSha256'])
    identity = {'parentArchiveSha256': base.digest(raw), 'historySha256': base.digest(base.canonical(history)),
                'seriesSha256': base.digest(base.canonical(series)), 'promptSha256': base.digest(base.regular(PROMPTS/'review.md')),
                'authorizationRef': args.authorization_ref, 'maxCalls': args.max_calls}
    if not args.execute:
        return {'status': 'OFFLINE', 'newPaidCalls': 0, 'identity': identity,
                'candidates': [len(review_inputs(archive, spec, history)['issues']) for spec in series['rounds']]}
    grouped.require(args.key_file and args.authorization_ref, 'editorial_authorization_required')
    base.private_dir(output)
    if (output/'completed.json').exists():
        done = base.strict_load(base.regular(output/'completed.json'))
        grouped.require(done['identity'] == identity and done['archiveSha256'] == base.digest(base.regular(output/'grouped-issues.json')),
                        'editorial_completed_identity_changed')
        return {**done, 'newPaidCalls': 0}
    base.private_dir(output/'calls')
    for old in (source.parent/'calls').glob('*.json'):
        base.write_once(output/'calls'/old.name, base.regular(old))
    layer, calls = review(archive, series, history, output, Path(args.key_file), args.max_calls)
    archive['editorialReview'] = layer
    archive['editorialParentArchiveSha256'] = base.digest(raw)
    archive['identity']['editorialReviewSha256'] = base.digest(base.canonical(layer))
    archive['identitySha256'] = base.digest(base.canonical(archive['identity']))
    archive['receipts'] += [r for r in layer['receipts'] if r['stage'] == 'editorial_freshness']
    base.write_once(output/'grouped-issues.json', base.canonical(archive))
    done = {'status': 'COMPLETE', 'identity': identity, 'newPaidCalls': calls,
            'archiveSha256': base.digest(base.regular(output/'grouped-issues.json'))}
    base.write_once(output/'completed.json', base.canonical(done))
    return done


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('archive', 'history', 'round-series', 'output', 'authorization-ref'):
        p.add_argument('--'+flag, required=True)
    p.add_argument('--execute', action='store_true'); p.add_argument('--key-file')
    p.add_argument('--max-calls', type=int, choices=range(1, 513), default=80)
    print(base.canonical(run(p.parse_args())).decode(), flush=True)
